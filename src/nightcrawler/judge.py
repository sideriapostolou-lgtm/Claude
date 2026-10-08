"""Jev, the AI judge (owner: O4). Runs ONLY after every hard rule passed.

Implementation contract (follow exactly; Anthropic Python SDK ``anthropic>=1.0``,
container has 1.12.1; import ``anthropic`` lazily so the package works without
the ``judge`` extra):

* ``client = anthropic.Anthropic(api_key=<settings.anthropic_api_key.reveal()>,
  timeout=JUDGE_TIMEOUT_S, max_retries=2)`` (tests inject ``client``).
* Request (:func:`build_request`)::

      client.beta.messages.create(
          model=JUDGE_MODEL, max_tokens=1024,
          system=[{"type": "text", "text": STATIC_SYSTEM_PROMPT,
                   "cache_control": {"type": "ephemeral"}}],
          messages=[{"role": "user", "content": json.dumps(features, sort_keys=True)}],
          output_config={"effort": JUDGE_EFFORT,
                         "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
          # ONLY when uses_fallbacks(model):
          betas=[FALLBACK_BETA], fallbacks="default",
      )

  Do NOT pass ``thinking`` or ``temperature``.
* Check ``response.stop_reason == "refusal"`` FIRST -> ``Verdict(decision="no",
  source="error", error="refusal")``.
* Parse the first ``text`` block with ``json.loads``; clamp ``confidence`` to
  [0, 1]; keep at most 3 reasons (each <= 200 chars). A verdict without any
  reason, or with a decision other than yes/no, is bad output.
* Errors: catch ``anthropic.RateLimitError``, ``anthropic.APITimeoutError``,
  ``anthropic.APIConnectionError``, ``anthropic.APIStatusError`` (in that
  order), plus ``json.JSONDecodeError``/``KeyError``/``TypeError`` for bad
  output -> FAIL CLOSED: ``Verdict(decision="no", source="error",
  error=<short class name>)``. Anything else unexpected also fails closed
  (``decide`` never raises). Log the request id (``response._request_id``,
  or ``getattr(exc, "request_id", None)`` for API errors) - never the API key.
* Cost: :func:`estimate_cost_usd` from ``response.usage`` (``input_tokens``,
  ``cache_read_input_tokens``, ``cache_creation_input_tokens``,
  ``output_tokens``) and :data:`PRICE_TABLE`, priced at the model that
  actually served the response (``response.model``; differs from
  ``JUDGE_MODEL`` after a server-side fallback). ``Verdict.model`` is that
  served model.
* Cache verdicts per mint (``features["mint"]``) for ``JUDGE_CACHE_MIN``;
  a cached verdict is returned as a copy with ``cached=True`` and
  ``cost_usd=0.0``. Error verdicts are NOT cached.
* Budget: if today's (UTC) judge spend >= ``JUDGE_MAX_DAILY_USD`` return
  ``Verdict("no", source="error", error="daily budget exceeded")`` without
  calling the API. Spend is accumulated in memory and, when a ledger is
  given, persisted in kv ``judge.cost_usd_day`` = ``{"day": "YYYY-MM-DD",
  "usd": float}``, ``judge.cost_usd_total`` (float) and ``judge.calls`` (int);
  a restarted Judge resumes from those keys.
* ``JUDGE_MODE=off`` -> ``Verdict("yes", 1.0, ["judge off: rules only"],
  model="rules", latency_ms=0, cost_usd=0.0, source="rules")`` without any
  API call. ``advisory`` and ``required`` both call the model; what the engine
  does with a "no" differs (advisory: log only; required: block the entry).
"""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Any, Mapping, Sequence

from nightcrawler.clock import Clock, RealClock, utc_day
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import (
    Candle,
    MarketSnapshot,
    RadarSignal,
    SafetyReport,
    Signal,
    TokenCandidate,
    Verdict,
)

__all__ = [
    "STATIC_SYSTEM_PROMPT",
    "VERDICT_SCHEMA",
    "PRICE_TABLE",
    "FALLBACK_BETA",
    "Judge",
    "uses_fallbacks",
    "estimate_cost_usd",
    "build_features",
    "build_request",
]

log = get_logger(__name__)

#: Byte-stable system prompt (no timestamps/ids) so prompt caching works.
STATIC_SYSTEM_PROMPT = """You are Jev, a terse, honest, risk-first judge for brand-new Solana memecoins.
A rules-based filter has ALREADY passed this token: mint and freeze authority renounced, no dangerous \
token extensions, holder concentration and creator holdings under limits, no recent insider dumping \
detected, and a dip-rebound price pattern confirmed on closed 1-minute candles.

Your job: decide whether to open a small long position NOW. Answer "no" unless the evidence for an \
organic dip-rebound is clear. Most new memecoins go to zero; a missed trade costs nothing, a bad trade \
costs real money.

Weigh: holder concentration and insider/creator selling; buy vs sell pressure (counts and volume); \
liquidity versus our position size (price impact, ability to exit); token age and how violent the \
pump and dump were; presence and plausibility of socials; paid promotion; anything inconsistent in \
the data.

Rules:
- Use ONLY the JSON you are given. Never invent data. Missing fields count against the trade.
- Reply with JSON matching the schema: decision "yes" or "no", confidence between 0 and 1, and at \
most 3 short reasons (under 20 words each).
- No hype, no price predictions, no advice beyond the decision."""

#: Structured-output schema for ``output_config.format``.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["yes", "no"]},
        "confidence": {"type": "number"},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "confidence", "reasons"],
    "additionalProperties": False,
}

#: USD per million tokens: (input, output, cache_read). Cache writes (5-minute
#: ephemeral) are billed at 1.25x input. Fable 5.1 is listed because a
#: server-side fallback (or JUDGE_MODEL) may route there; it is the priciest row.
PRICE_TABLE: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
}
CACHE_WRITE_MULTIPLIER = 1.25
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_PRICE_MODEL = "claude-opus-5-5"

MAX_TOKENS = 1024
MAX_REASONS = 3
MAX_REASON_CHARS = 200
RECENT_CLOSES_MAX = 30
SIGNIFICANT_DIGITS = 6

KV_COST_DAY = "judge.cost_usd_day"
KV_COST_TOTAL = "judge.cost_usd_total"
KV_CALLS = "judge.calls"

_USAGE_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
_SOCIAL_KEYS = ("twitter", "website", "telegram")


# --------------------------------------------------------------------------- pure helpers


def uses_fallbacks(model: str) -> bool:
    """True when the server-side fallback beta is sent: model starts with
    ``claude-opus`` or ``claude-fable``, or equals ``claude-sonnet-5-5``."""
    return model.startswith(("claude-opus", "claude-fable")) or model == "claude-sonnet-5-5"


def _field(obj: Any, name: str) -> Any:
    """Read ``name`` from a mapping or an object; ``None`` when absent."""
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _token_count(usage: Any, name: str) -> int:
    value = _field(usage, name)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def estimate_cost_usd(model: str, usage: Any) -> float:
    """Estimated USD cost of one response from its ``usage`` object/dict.

    ``input_tokens*in + cache_read_input_tokens*cache_read +
    cache_creation_input_tokens*in*1.25 + output_tokens*out`` (per MTok).
    Missing usage fields count as 0. Unknown models use the
    ``claude-opus-5-5`` row.
    """
    in_rate, out_rate, cache_read_rate = PRICE_TABLE.get(model, PRICE_TABLE[DEFAULT_PRICE_MODEL])
    tokens = {name: _token_count(usage, name) for name in _USAGE_FIELDS}
    per_mtok = (
        tokens["input_tokens"] * in_rate
        + tokens["cache_read_input_tokens"] * cache_read_rate
        + tokens["cache_creation_input_tokens"] * in_rate * CACHE_WRITE_MULTIPLIER
        + tokens["output_tokens"] * out_rate
    )
    return per_mtok / 1_000_000


def build_request(model: str, effort: str, features: dict[str, Any]) -> dict[str, Any]:
    """Keyword arguments for ``client.beta.messages.create`` (exact contract shape).

    The system block is byte-stable and marked for prompt caching; the user
    message is ``json.dumps(features, sort_keys=True)``. The fallback beta and
    ``fallbacks="default"`` are added only when :func:`uses_fallbacks`.
    """
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": STATIC_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": json.dumps(features, sort_keys=True)}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
    }
    if uses_fallbacks(model):
        request["betas"] = [FALLBACK_BETA]
        request["fallbacks"] = "default"
    return request


def _round_sig(value: float) -> float | None:
    """Round to :data:`SIGNIFICANT_DIGITS` significant digits; NaN/inf -> None."""
    if not math.isfinite(value):
        return None
    return float(f"{value:.{SIGNIFICANT_DIGITS}g}")


def _compact(value: Any) -> Any:
    """JSON-native copy with sorted dict keys and floats rounded (see :func:`_round_sig`)."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return _round_sig(value)
    if isinstance(value, Mapping):
        return {str(k): _compact(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_compact(v) for v in value]
    return str(value)


def _first_known(*values: Any) -> Any:
    return next((v for v in values if v is not None), None)


def _age_min(candidate: TokenCandidate, snapshot: MarketSnapshot | None) -> float | None:
    """Token age at the snapshot time when possible (fresher than the discovery-time age)."""
    if snapshot is not None and candidate.created_at is not None:
        return max(0.0, (snapshot.ts - candidate.created_at) / 60.0)
    return candidate.age_min


def _flow_features(snapshot: MarketSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return dict.fromkeys(("buys_m5", "sells_m5", "buys_h1", "sells_h1", "volume_m5_usd", "volume_h1_usd",
                              "price_change_m5_pct", "price_change_h1_pct"))
    return {
        "buys_m5": snapshot.buys_m5,
        "sells_m5": snapshot.sells_m5,
        "buys_h1": snapshot.buys_h1,
        "sells_h1": snapshot.sells_h1,
        "volume_m5_usd": snapshot.volume_m5,
        "volume_h1_usd": snapshot.volume_h1,
        "price_change_m5_pct": snapshot.price_change_m5,
        "price_change_h1_pct": snapshot.price_change_h1,
    }


def _signal_features(signal: Signal) -> dict[str, Any]:
    """``{reason, dip_pct, ...signal.metrics}``; ``dip_pct`` = metrics ``dip`` (fraction) x 100."""
    metrics = dict(signal.metrics)
    dip_pct = metrics.get("dip_pct")
    dip = metrics.get("dip")
    if dip_pct is None and isinstance(dip, (int, float)) and not isinstance(dip, bool):
        dip_pct = dip * 100.0
    return {**metrics, "reason": signal.reason, "dip_pct": dip_pct}


def _safety_features(safety: SafetyReport) -> dict[str, Any]:
    m = safety.metrics
    return {
        "warnings": list(safety.warnings),
        "top10_pct": m.get("top10_pct"),
        "max_holder_pct": m.get("max_holder_pct"),
        "creator_pct": m.get("creator_pct"),
        "insider_pct": m.get("insider_pct"),
        "lp_locked_pct": m.get("lp_locked_pct"),
    }


def _radar_features(radar: RadarSignal | None) -> dict[str, Any] | None:
    if radar is None:
        return None
    return {
        "window_min": radar.window_min,
        "big_sells_usd": radar.big_sells_usd,
        "insider_sell_usd": radar.insider_sell_usd,
        "creator_sold": radar.creator_sold,
        "flagged": radar.flagged,
    }


def _recent_closes(candles: Sequence[Candle] | None, now: float | None) -> list[float] | None:
    """Closes of the last :data:`RECENT_CLOSES_MAX` closed candles, oldest first."""
    if not candles:
        return None
    closed = sorted((c for c in candles if now is None or c.is_closed(now)), key=lambda c: c.ts)
    closes = [c.c for c in closed[-RECENT_CLOSES_MAX:]]
    return closes or None


def build_features(candidate: TokenCandidate, snapshot: MarketSnapshot | None, safety: SafetyReport,
                   radar: RadarSignal | None, signal: Signal, position_usd: float,
                   candles: list[Candle] | None = None, *, now: float | None = None) -> dict[str, Any]:
    """Deterministic, compact feature dict sent to the model (also stored in the decision receipt).

    Keys (missing values are ``None``, floats rounded to 6 significant digits,
    dict keys sorted at every level):
    ``mint, symbol, name, age_min, dex, graduated, mcap_usd, liquidity_usd,
    price_usd, holder_count, position_usd, position_vs_liquidity_pct,
    buys_m5, sells_m5, buys_h1, sells_h1, volume_m5_usd, volume_h1_usd,
    price_change_m5_pct, price_change_h1_pct, signal: {reason, dip_pct, ...signal.metrics},
    safety: {warnings, top10_pct, max_holder_pct, creator_pct, insider_pct, lp_locked_pct},
    radar: {window_min, big_sells_usd, insider_sell_usd, creator_sold, flagged} | None,
    socials: {twitter, website, telegram} (bools), paid_promo, organic_score,
    recent_closes: last 30 closed-candle closes (USD) | None``.

    Market values prefer the (fresher) ``snapshot`` over the candidate;
    ``age_min`` is measured at ``snapshot.ts`` when both timestamps are known.
    ``candles`` are assumed closed unless ``now`` is given, in which case
    still-open candles are dropped. No timestamps of "now" are included
    (keeps requests cache-friendly and reproducible); NaN/inf become ``None``.
    """
    liquidity = _first_known(snapshot.liquidity_usd if snapshot else None, candidate.liquidity_usd)
    features: dict[str, Any] = {
        "mint": candidate.mint,
        "symbol": candidate.symbol or None,
        "name": candidate.name or None,
        "age_min": _age_min(candidate, snapshot),
        "dex": _first_known(candidate.dex, snapshot.dex if snapshot else None),
        "graduated": candidate.graduated,
        "mcap_usd": _first_known(snapshot.mcap_usd if snapshot else None, candidate.mcap_usd),
        "liquidity_usd": liquidity,
        "price_usd": _first_known(snapshot.price_usd if snapshot else None, candidate.price_usd),
        "holder_count": _first_known(candidate.holder_count, safety.metrics.get("holder_count")),
        "position_usd": float(position_usd),
        "position_vs_liquidity_pct": position_usd / liquidity * 100.0 if liquidity else None,
        **_flow_features(snapshot),
        "signal": _signal_features(signal),
        "safety": _safety_features(safety),
        "radar": _radar_features(radar),
        "socials": {key: bool(candidate.socials.get(key)) for key in _SOCIAL_KEYS},
        "paid_promo": candidate.paid_promo,
        "organic_score": candidate.organic_score,
        "recent_closes": _recent_closes(candles, now),
    }
    return _compact(features)


def _first_text(response: Any) -> Any:
    """Text of the first ``text`` content block (thinking blocks are skipped)."""
    for block in _field(response, "content") or []:
        if _field(block, "type") == "text":
            return _field(block, "text")
    raise ValueError("response has no text block")


def _parse_verdict(text: Any) -> tuple[str, float, list[str]]:
    """``(decision, confidence clamped to [0, 1], <= 3 reasons of <= 200 chars)``.

    Raises ``json.JSONDecodeError``/``ValueError``/``KeyError``/``TypeError`` on bad output.
    """
    data = json.loads(text)
    decision = data["decision"]
    if decision not in ("yes", "no"):
        raise ValueError(f"invalid decision {decision!r}")
    confidence = float(data["confidence"])
    if not math.isfinite(confidence):
        raise ValueError("confidence is not finite")
    raw_reasons = data["reasons"]
    if not isinstance(raw_reasons, list):
        raise TypeError("reasons must be a list")
    reasons = [r.strip()[:MAX_REASON_CHARS] for r in raw_reasons if isinstance(r, str) and r.strip()]
    if not reasons:
        raise ValueError("verdict has no reasons")
    return decision, min(1.0, max(0.0, confidence)), reasons[:MAX_REASONS]


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


# --------------------------------------------------------------------------- the judge


class Judge:
    """Calls Claude to approve/deny an entry. See module docstring for the exact contract."""

    def __init__(self, settings: Settings, client: Any | None = None, clock: Clock | None = None,
                 ledger: Any | None = None) -> None:
        self.settings = settings
        self.client = client
        self.clock = clock if clock is not None else RealClock()
        self.ledger = ledger
        self._cache: dict[str, tuple[float, Verdict]] = {}
        self.calls = int(_safe_float(self._kv_get(KV_CALLS, 0)))
        self.cost_usd_total = _safe_float(self._kv_get(KV_COST_TOTAL, 0.0))
        self._spend_day: str | None = None
        self._spend_today = 0.0

    # ------------------------------------------------------------------ public API
    def decide(self, features: dict[str, Any]) -> Verdict:
        """Return a :class:`Verdict` for ``features`` (needs key ``mint``). Never raises."""
        if not self.settings.judge_enabled:
            return Verdict("yes", 1.0, ["judge off: rules only"], model="rules", latency_ms=0,
                           cost_usd=0.0, source="rules")
        mint = features.get("mint") if isinstance(features, Mapping) else None
        if not mint:
            log.warning("judge rejected reason=features_missing_mint")
            return self._error_verdict("missing mint")
        cached = self._cached(mint)
        if cached is not None:
            return cached
        if self.spent_today_usd() >= self.settings.judge_max_daily_usd:
            log.warning("judge budget_exceeded mint=%s spent_usd=%.4f cap_usd=%.4f",
                        mint, self._spend_today, self.settings.judge_max_daily_usd)
            return self._error_verdict("daily budget exceeded")
        verdict = self._ask_model(features)
        log.info("judge verdict mint=%s decision=%s confidence=%.2f source=%s model=%s cost_usd=%.6f "
                 "latency_ms=%d request_id=%s error=%s", mint, verdict.decision, verdict.confidence,
                 verdict.source, verdict.model, verdict.cost_usd, verdict.latency_ms, verdict.request_id,
                 verdict.error)
        if verdict.source == "claude":
            self._store(mint, verdict)
        return verdict

    def spent_today_usd(self) -> float:
        """Judge spend so far in the current UTC day (USD)."""
        day = utc_day(self.clock.now())
        if day != self._spend_day:
            stored = self._kv_get(KV_COST_DAY, None)
            same_day = isinstance(stored, Mapping) and stored.get("day") == day
            self._spend_today = _safe_float(stored.get("usd")) if same_day else 0.0
            self._spend_day = day
        return self._spend_today

    # ------------------------------------------------------------------ model call
    def _ask_model(self, features: dict[str, Any]) -> Verdict:
        started = self.clock.now()
        try:
            import anthropic
        except ImportError:
            log.error("judge sdk_missing hint=pip_install_nightcrawler[judge]")
            return self._error_verdict("anthropic not installed")
        try:
            client = self._get_client(anthropic)
            response = client.beta.messages.create(
                **build_request(self.settings.judge_model, self.settings.judge_effort, features))
        except anthropic.RateLimitError as exc:
            verdict = self._api_failure(exc, started, "rate limited")
        except anthropic.APITimeoutError as exc:
            verdict = self._api_failure(exc, started, f"timed out after {self.settings.judge_timeout_s:g}s")
        except anthropic.APIConnectionError as exc:
            verdict = self._api_failure(exc, started, "connection error")
        except anthropic.APIStatusError as exc:
            verdict = self._api_failure(exc, started, f"http status {exc.status_code}")
        except Exception as exc:  # decide() never raises: anything unexpected fails closed, with traceback
            log.exception("judge unexpected_error error=%s", type(exc).__name__)
            verdict = self._error_verdict(type(exc).__name__, started)
        else:
            verdict = self._verdict_from_response(response, started)
        self._account(verdict.cost_usd)
        return verdict

    def _get_client(self, anthropic: Any) -> Any:
        if self.client is None:
            key = self.settings.anthropic_api_key
            self.client = anthropic.Anthropic(api_key=key.reveal() if key else None,
                                              timeout=self.settings.judge_timeout_s, max_retries=2)
        return self.client

    def _api_failure(self, exc: Exception, started: float, detail: str) -> Verdict:
        request_id = getattr(exc, "request_id", None)
        log.warning("judge api_error error=%s detail=%s request_id=%s", type(exc).__name__, detail, request_id)
        return self._error_verdict(type(exc).__name__, started, request_id=request_id)

    def _verdict_from_response(self, response: Any, started: float) -> Verdict:
        served = _field(response, "model")
        model = served if isinstance(served, str) and served else self.settings.judge_model
        latency_ms = self._latency_ms(started)
        cost = estimate_cost_usd(model, _field(response, "usage"))
        request_id = getattr(response, "_request_id", None)
        stop_reason = _field(response, "stop_reason")
        if stop_reason == "refusal":
            category = _field(_field(response, "stop_details"), "category")
            log.warning("judge refusal category=%s model=%s request_id=%s", category, model, request_id)
            reason = f"model refused ({category})" if category else "model refused"
            return Verdict("no", 0.0, [reason], model, latency_ms, cost, "error", request_id=request_id,
                           error="refusal")
        try:
            decision, confidence, reasons = _parse_verdict(_first_text(response))
        except (ValueError, KeyError, TypeError) as exc:  # json.JSONDecodeError is a ValueError
            name = type(exc).__name__
            log.warning("judge bad_output error=%s detail=%s stop_reason=%s request_id=%s",
                        name, exc, stop_reason, request_id)
            return Verdict("no", 0.0, [f"judge error: {name}"], model, latency_ms, cost, "error",
                           request_id=request_id, error=name)
        return Verdict(decision, confidence, reasons, model, latency_ms, cost, "claude", request_id=request_id)

    def _error_verdict(self, error: str, started: float | None = None, request_id: str | None = None) -> Verdict:
        latency_ms = self._latency_ms(started) if started is not None else 0
        return Verdict("no", 0.0, [f"judge error: {error}"], self.settings.judge_model, latency_ms, 0.0, "error",
                       request_id=request_id, error=error)

    def _latency_ms(self, started: float) -> int:
        return max(0, round((self.clock.now() - started) * 1000))

    # ------------------------------------------------------------------ cache
    @property
    def _cache_ttl_s(self) -> float:
        return self.settings.judge_cache_min * 60.0

    def _cached(self, mint: str) -> Verdict | None:
        entry = self._cache.get(mint)
        if entry is None:
            return None
        stored_at, verdict = entry
        if self.clock.now() - stored_at >= self._cache_ttl_s:
            del self._cache[mint]
            return None
        return dataclasses.replace(verdict, reasons=list(verdict.reasons), cached=True, cost_usd=0.0)

    def _store(self, mint: str, verdict: Verdict) -> None:
        if self._cache_ttl_s <= 0:
            return
        now = self.clock.now()
        self._cache = {m: e for m, e in self._cache.items() if now - e[0] < self._cache_ttl_s}
        self._cache[mint] = (now, verdict)

    # ------------------------------------------------------------------ spend accounting
    def _account(self, cost_usd: float) -> None:
        """Count one API attempt and its estimated cost (memory + ledger kv)."""
        self.spent_today_usd()  # roll the UTC day first
        self.calls += 1
        self.cost_usd_total += cost_usd
        self._spend_today += cost_usd
        if self.ledger is None:
            return
        try:
            self.ledger.set_kv(KV_COST_DAY, {"day": self._spend_day, "usd": self._spend_today})
            self.ledger.set_kv(KV_COST_TOTAL, self.cost_usd_total)
            self.ledger.set_kv(KV_CALLS, self.calls)
        except Exception as exc:  # spend is still enforced from memory; never break decide()
            log.warning("judge ledger_write_failed error=%s", type(exc).__name__)

    def _kv_get(self, key: str, default: Any) -> Any:
        if self.ledger is None:
            return default
        try:
            return self.ledger.get_kv(key, default)
        except Exception as exc:  # a broken ledger must not stop the judge from failing closed
            log.warning("judge ledger_read_failed key=%s error=%s", key, type(exc).__name__)
            return default

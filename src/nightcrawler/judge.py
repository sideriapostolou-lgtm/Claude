"""Jev, the AI judge (owner: O4). Runs ONLY after every hard rule passed.

Implementation contract (follow exactly; Anthropic Python SDK ``anthropic>=1.0``,
container has 1.12.1; import ``anthropic`` lazily so the package works without
the ``judge`` extra):

* ``client = anthropic.Anthropic(api_key=<settings.anthropic_api_key.reveal()>,
  timeout=JUDGE_TIMEOUT_S, max_retries=2)`` (tests inject ``client``).
* Request::

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
  [0, 1]; keep at most 3 reasons (each <= 200 chars).
* Errors: catch ``anthropic.RateLimitError``, ``anthropic.APITimeoutError``,
  ``anthropic.APIConnectionError``, ``anthropic.APIStatusError`` (in that
  order), plus ``json.JSONDecodeError``/``KeyError``/``TypeError`` for bad
  output -> FAIL CLOSED: ``Verdict(decision="no", source="error",
  error=<short class name>)``. Log the request id (``response._request_id``,
  or ``getattr(exc, "request_id", None)`` for API errors) - never the API key.
* Cost: :func:`estimate_cost_usd` from ``response.usage`` (``input_tokens``,
  ``cache_read_input_tokens``, ``cache_creation_input_tokens``,
  ``output_tokens``) and :data:`PRICE_TABLE`.
* Cache verdicts per mint (``features["mint"]``) for ``JUDGE_CACHE_MIN``;
  a cached verdict is returned as a copy with ``cached=True`` and
  ``cost_usd=0.0``. Error verdicts are NOT cached.
* Budget: if today's (UTC) judge spend >= ``JUDGE_MAX_DAILY_USD`` return
  ``Verdict("no", source="error", error="daily budget exceeded")`` without
  calling the API. Spend is accumulated in memory and, when a ledger is
  given, persisted in kv ``judge.cost_usd_day`` = ``{"day": "YYYY-MM-DD",
  "usd": float}`` and ``judge.cost_usd_total`` (float).
* ``JUDGE_MODE=off`` -> ``Verdict("yes", 1.0, ["judge off: rules only"],
  model="rules", latency_ms=0, cost_usd=0.0, source="rules")`` without any
  API call. ``advisory`` and ``required`` both call the model; what the engine
  does with a "no" differs (advisory: log only; required: block the entry).
"""

from __future__ import annotations

from typing import Any

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
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
]

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
#: ephemeral) are billed at 1.25x input.
PRICE_TABLE: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
CACHE_WRITE_MULTIPLIER = 1.25
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def uses_fallbacks(model: str) -> bool:
    """True when the server-side fallback beta is sent: model starts with
    ``claude-opus`` or ``claude-fable``, or equals ``claude-sonnet-5-5``."""
    return model.startswith(("claude-opus", "claude-fable")) or model == "claude-sonnet-5-5"


def estimate_cost_usd(model: str, usage: Any) -> float:
    """Estimated USD cost of one response from its ``usage`` object/dict.

    ``input_tokens*in + cache_read_input_tokens*cache_read +
    cache_creation_input_tokens*in*1.25 + output_tokens*out`` (per MTok).
    Missing usage fields count as 0. Unknown models use the
    ``claude-opus-5-5`` row (conservative).
    """
    raise NotImplementedError


def build_features(candidate: TokenCandidate, snapshot: MarketSnapshot | None, safety: SafetyReport,
                   radar: RadarSignal | None, signal: Signal, position_usd: float,
                   candles: list[Candle] | None = None) -> dict[str, Any]:
    """Deterministic, compact feature dict sent to the model (also stored in the decision receipt).

    Keys (missing values are ``None``, floats rounded to 6 significant digits):
    ``mint, symbol, name, age_min, dex, graduated, mcap_usd, liquidity_usd,
    price_usd, holder_count, position_usd, position_vs_liquidity_pct,
    buys_m5, sells_m5, buys_h1, sells_h1, volume_m5_usd, volume_h1_usd,
    price_change_m5_pct, price_change_h1_pct, signal: {reason, dip_pct, ...signal.metrics},
    safety: {warnings, top10_pct, max_holder_pct, creator_pct, insider_pct, lp_locked_pct},
    radar: {big_sells_usd, insider_sell_usd, creator_sold, flagged} | None,
    socials: {twitter, website, telegram} (bools), paid_promo, organic_score,
    recent_closes: last 30 closed-candle closes (USD) | None``.
    No timestamps of "now" (keeps requests cache-friendly and reproducible).
    """
    raise NotImplementedError


class Judge:
    """Calls Claude to approve/deny an entry. See module docstring for the exact contract."""

    def __init__(self, settings: Settings, client: Any | None = None, clock: Clock | None = None,
                 ledger: Any | None = None) -> None:
        self.settings = settings
        self.client = client
        self.clock = clock
        self.ledger = ledger
        self._cache: dict[str, tuple[float, Verdict]] = {}
        self.calls = 0
        self.cost_usd_total = 0.0

    def decide(self, features: dict[str, Any]) -> Verdict:
        """Return a :class:`Verdict` for ``features`` (needs key ``mint``). Never raises."""
        raise NotImplementedError

    def spent_today_usd(self) -> float:
        """Judge spend so far in the current UTC day (USD)."""
        raise NotImplementedError

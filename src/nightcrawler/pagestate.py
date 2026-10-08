"""Data for the one page at ``/`` (owner: O6): ``/api/page``, built from the ledger ONLY (no network calls).

It combines what ``/api/state`` (:func:`nightcrawler.dashboard.build_state`) and ``/api/team``
(:func:`nightcrawler.teamroom.build_team_state`) already know, in plain words, plus the learning card and
the "ready for real money?" checklist (:mod:`nightcrawler.readiness`). Served by
:class:`nightcrawler.teamroom.TeamRoom` behind the dashboard token, scrubbed of secrets; every text taken
from the ledger is redacted, THEN clipped, and the page inserts it as text only.

Schema (lists capped: members 9, events <= 5, open trades <= 10, closed trades 10, variants 5)::

    {
      "version", "generated_at", "mode": "PAPER"|"LIVE", "refresh_s",
      "alerts": [{"level": "bad"|"warn", "text"}],                    # header banners, worst first
      "money": {"label", "usd", "start_usd", "sol", "sol_usd",
                "since_start": {"usd", "pct"}, "today": {"usd", "pct"},   # the bot's own result (in SOL,
                "sol_price_effect_usd",                                   #  shown at today's SOL price)
                "curve": [[ts, usd], ...], "chart_ready": bool},          # chart after one hour of data
      "team": {"counts": {status: n}, "members": [{"id", "name", "role", "status", "why", "doing",
                                                    "last_activity", "events", "bars"?}]},
      "trades": {"open": [{"coin", "entry_usd", "now_usd", "pnl_usd", "pnl_pct", "opened_at", "partial"}],
                 "closed": [{"coin", "opened_at", "closed_at", "pnl_usd", "pnl_pct", "result", "why"}],
                 "max_open"},
      "learning": {"source": "card"|"fallback", "state", "headline", "variants": [{"name", "n", "avg",
                   "proof"}], "data", "rule"},
      "ready": readiness.readiness(...),
      "receipts": {"count", "verified", "first_bad_seq", "head", "head_short"},
      "usage": [{"label", "pct": float|null, "level": "ok"|"warn"|"over"|null, "text"}],
      "about": {"version", "uptime_s", "commit", "started_at"}
    }

MONEY honesty (same rule as the old dashboard tiles): "since start" and "today" are the bot's result
measured in SOL - the unit the risk limits use - and shown in dollars at today's SOL price, so a SOL price
rise can never paint a losing bot green. The SOL price effect is reported apart.

LEARNING: :func:`learning_card` calls ``nightcrawler.learn.card.learning_card_state(settings, now)`` when
that module exists (it is built on another branch) and keeps only these keys, each type-checked::

    headline: str, state: str, variants | top_variants: [{name | id, n | trades | n_trades,
    avg | average (PERCENT per trade), proof | proof_progress (0..1)}], data | data_line: str,
    champion: str | {"name": str}, champion_passed_locked_test: bool, paper_matches_backtest: bool,
    paper_matches_backtest_reason | paper_reason: str, updated_at: epoch seconds

Anything missing, of the wrong type, a raising module or an absent one falls back to a "collecting" card.
Only an explicit ``True`` ever counts towards the checklist.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from nightcrawler import __version__
from nightcrawler.config import Settings
from nightcrawler.dashboard import build_state, scrub
from nightcrawler.logging_setup import get_logger, redact_text
from nightcrawler.models import LAMPORTS_PER_SOL
from nightcrawler.page import LEARNING_RULE, MEMBERS, REFRESH_S
from nightcrawler.readiness import readiness
from nightcrawler.teamroom import build_team_state, derive_status

__all__ = ["LEARNING_RULE", "MEMBERS", "STALE_BANNER_S", "build_page_state", "learning_card"]

log = get_logger(__name__)

#: The header turns red when the engine's heartbeat is older than this (it beats every 15 s).
STALE_BANNER_S = 120.0
CHART_MIN_SPAN_S = 3600.0
OPEN_MAX = 10
CLOSED_MAX = 10
COIN_MAX = 24
WHY_MAX = 60
TEXT_MAX = 160
VARIANTS_MAX = 5
#: The learning card is recomputed at most this often (the page refreshes every few seconds).
LEARNING_TTL_S = 60.0
#: The Coach counts as working when its card was updated this recently (it learns nightly).
COACH_WINDOW_S = 26 * 3600.0
DAY_S = 86_400.0

#: Why a position was closed (``Position.exit_reason``), in plain words.
EXIT_WORDS = {
    "stop_loss": "Stop-loss: cut the loss", "trailing_stop": "Sold after the price fell from its high",
    "time_stop": "Time limit reached", "take_profit_partial": "Took profit", "kill_switch": "Kill switch: sold all",
    "manual": "Sold by hand",
}
_CARD_ALIASES = {
    "variants": ("variants", "top_variants"), "data": ("data", "data_line"),
    "reason": ("paper_matches_backtest_reason", "paper_reason"),
    "name": ("name", "id"), "n": ("n", "trades", "n_trades"), "avg": ("avg", "average"),
    "proof": ("proof", "proof_progress"),
}


# =========================================================================== helpers


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _num(value: Any) -> float | None:
    """A finite number (bool is not a number), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _pct(part: float | None, whole: float | None) -> float | None:
    return part / whole * 100.0 if part is not None and whole else None


def _times(a: float | None, b: float | None) -> float | None:
    return a * b if a is not None and b is not None else None


def _first(mapping: Mapping[str, Any], key: str) -> Any:
    return next((mapping[k] for k in _CARD_ALIASES[key] if k in mapping), None)


def _short(mint: str) -> str:
    return f"{mint[:4]}…{mint[-4:]}" if len(mint) > 12 else mint


class _Text:
    """Redact secrets FIRST, then clip, so a clipped secret can never slip past the scrub."""

    def __init__(self, settings: Settings) -> None:
        self.secrets = tuple(settings.secret_values())

    def __call__(self, value: Any, limit: int = TEXT_MAX) -> str:
        return _clip(redact_text(str(value), self.secrets), limit)

    def opt(self, value: Any, limit: int = TEXT_MAX) -> str | None:
        """Non-empty strings only, else None."""
        return self(value.strip(), limit) if isinstance(value, str) and value.strip() else None


# =========================================================================== learning card


def learning_card(settings: Settings, now: float, ledger: Any, memory: dict[str, Any] | None = None
                  ) -> dict[str, Any]:
    """The Coach's learning card, sanitized (schema in the module docstring), or a "collecting" card.

    Never raises. ``memory`` (kept between requests) caches the card for :data:`LEARNING_TTL_S`."""
    cached = memory.get("learning") if memory is not None else None
    if cached is not None and 0 <= now - cached[0] < LEARNING_TTL_S:
        return dict(cached[1])
    card = _sanitize(_load_card(settings, now), _Text(settings)) or _collecting(now, ledger)
    if card["headline"] is None:
        card["headline"] = _collecting(now, ledger)["headline"]
    if memory is not None:
        memory["learning"] = (now, card)
    return dict(card)


def _load_card(settings: Settings, now: float) -> Any:
    try:
        from nightcrawler.learn.card import learning_card_state  # built on another branch; may be absent
    except ImportError:
        return None
    try:
        return learning_card_state(settings, now)
    except Exception as exc:  # a broken learning module must never take the page down
        log.warning("learning_card_failed error=%s", type(exc).__name__)
        return None


def _sanitize(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    champion = raw.get("champion")
    if isinstance(champion, Mapping):
        champion = champion.get("name")
    variants = _first(raw, "variants")
    items = variants if isinstance(variants, list) else []
    kept = [v for v in (_variant(item, text) for item in items) if v is not None]
    return {
        "source": "card",
        "state": text.opt(raw.get("state"), 60),
        "headline": text.opt(raw.get("headline")),
        "variants": kept[:VARIANTS_MAX],
        "data": text.opt(_first(raw, "data"), 200),
        "champion": text.opt(champion, 60),
        "champion_passed_locked_test": raw.get("champion_passed_locked_test") is True,
        "paper_matches_backtest": raw.get("paper_matches_backtest") is True,
        "paper_matches_backtest_reason": text.opt(_first(raw, "reason")),
        "updated_at": _num(raw.get("updated_at")),
    }


def _variant(item: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    name = text.opt(_first(item, "name"), 40)
    if name is None:
        return None
    n = _first(item, "n")
    avg, proof = _num(_first(item, "avg")), _num(_first(item, "proof"))
    return {"name": name,
            "n": n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None,
            "avg": avg if avg is not None and abs(avg) < 1e6 else None,
            "proof": min(1.0, max(0.0, proof)) if proof is not None else None}


def _collecting(now: float, ledger: Any) -> dict[str, Any]:
    """The fallback card: the Coach is still collecting data (day N since the first receipt)."""
    first = ledger.receipts(after_seq=0, limit=1)
    day = int(max(0.0, now - first[0].ts) // DAY_S) + 1 if first else 1
    return {"source": "fallback", "state": "collecting", "headline": f"Collecting data, day {day}",
            "variants": [], "data": "The Coach needs dozens of finished trades before it can judge any strategy.",
            "champion": None, "champion_passed_locked_test": False, "paper_matches_backtest": False,
            "paper_matches_backtest_reason": None, "updated_at": None}


# =========================================================================== sections


def _money(settings: Settings, eq: dict[str, Any]) -> dict[str, Any]:
    sol, sol_usd = eq["sol"], eq["sol_usd"]
    total, today = eq["pnl_total_sol"], eq["pnl_today_sol"]
    curve = eq["curve"]
    span = curve[-1][0] - curve[0][0] if len(curve) >= 2 else 0.0
    return {
        "label": "Real money" if settings.is_live else "Paper money (pretend)",
        "usd": eq["usd"], "start_usd": eq["start_usd"], "sol": sol, "sol_usd": sol_usd,
        "since_start": {"usd": eq["pnl_total_trading_usd"],
                        "pct": _pct(total, sol - total if sol is not None and total is not None else None)},
        "today": {"usd": _times(today, sol_usd),
                  "pct": _pct(today, sol - today if sol is not None and today is not None else None)},
        "sol_price_effect_usd": eq["sol_price_effect_usd"],
        "curve": curve, "chart_ready": span >= CHART_MIN_SPAN_S,
    }


def _members(team: dict[str, Any], card: dict[str, Any], now: float) -> list[dict[str, Any]]:
    panels = {p["id"]: p for p in team["panels"]}
    out = []
    for mid, name, role in MEMBERS:
        if mid == "coach":
            status, why = derive_status(now, card["updated_at"], COACH_WINDOW_S,
                                        waiting=("collecting data: nothing to learn from yet"
                                                 if card["state"] == "collecting" else None),
                                        idle="no new lesson recently")
            out.append({"id": mid, "name": name, "role": role, "status": status, "why": why,
                        "doing": card["headline"], "last_activity": card["updated_at"], "events": []})
            continue
        p = panels[mid]
        member = {"id": mid, "name": name, "role": role, "status": p["status"], "why": p["why"],
                  "doing": p["doing"], "last_activity": p["last_activity"], "events": p["events"]}
        if p.get("bars"):
            member["bars"] = p["bars"]
        out.append(member)
    return out


def _trades(ledger: Any, settings: Settings, state: dict[str, Any], text: _Text) -> dict[str, Any]:
    mode = "live" if settings.is_live else "paper"
    sol_usd = state["equity"]["sol_usd"]
    opened = [{"coin": text(p["symbol"] or _short(p["mint"]), COIN_MAX), "entry_usd": p["entry_price_usd"] or None,
               "now_usd": p["last_price_usd"], "pnl_usd": _times(p["unrealized_pnl_sol"], sol_usd),
               "pnl_pct": p["unrealized_pnl_pct"], "opened_at": p["opened_at"], "partial": p["partial_taken"]}
              for p in state["positions"][:OPEN_MAX]]
    rows = ledger.positions(status="closed", limit=5 * CLOSED_MAX, mode=mode)
    rows.sort(key=lambda p: p.closed_at if p.closed_at is not None else p.opened_at, reverse=True)
    closed = []
    for p in rows[:CLOSED_MAX]:
        pnl = p.pnl_lamports() / LAMPORTS_PER_SOL
        reason = p.exit_reason or ""
        why = "Danger spotted, sold early" if reason.startswith("radar") else EXIT_WORDS.get(reason, "Sold")
        closed.append({"coin": text(p.symbol or _short(p.mint), COIN_MAX), "opened_at": p.opened_at,
                       "closed_at": p.closed_at, "pnl_usd": _times(pnl, sol_usd),
                       "pnl_pct": _pct(pnl, p.cost_lamports / LAMPORTS_PER_SOL),
                       "result": "won" if pnl > 0 else "lost" if pnl < 0 else "even", "why": text(why, WHY_MAX)})
    return {"open": opened, "closed": closed, "max_open": settings.max_open_positions}


def _usage(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """``(rows, alerts)``: one row per provider; a budget that is used up also goes to the header."""
    rows, alerts = [], []
    for r in state["usage"]["providers"]:
        when = "today" if r["period"] == "day" else "this month"
        if r["budget"]:
            if r["unit"] == "usd":
                used = f"${r['used']:.2f} of ${r['budget']:.2f} {when}"
            else:
                used = f"{int(r['used']):,} of {int(r['budget']):,} {r['unit']} {when}"
            rows.append({"label": r["label"], "pct": r["used_pct"], "level": r["level"], "text": used})
            if r["level"] == "over":
                alerts.append({"level": "warn", "text": f"{r['label']} is over its "
                               f"{'daily' if r['period'] == 'day' else 'monthly'} budget ({r['used_pct']:.0f}%)."})
        else:
            calls = int(r["calls_today"])
            rows.append({"label": r["label"], "pct": None, "level": None,
                         "text": f"{calls:,} call{'' if calls == 1 else 's'} today"})
    return rows, alerts


def _alerts(ledger: Any, state: dict[str, Any], now: float) -> list[dict[str, str]]:
    """Header banners from real trouble only, worst first."""
    out = []
    if state["kill"] == "sell_all":
        out.append(("bad", "Kill switch is ON: the bot is selling everything and buying nothing."))
    elif state["kill"] == "stop":
        out.append(("bad", "Kill switch is ON: the bot buys nothing new (open trades are still looked after)."))
    if state["halted"]["halted"]:
        out.append(("bad", "Stopped buying: the money fell too far from its high. It stays stopped until you "
                           "reset it (RESET_HALT_TOKEN in Railway)."))
    status = state["engine"]["status"] or {}
    if status.get("drift"):
        out.append(("bad", "The wallet doesn't match the bot's own records: new buys are blocked until it's checked."))
    if ledger.get_kv("engine.safe_mode") or status.get("safe_mode"):
        out.append(("bad", "Safe mode: the settings are invalid, so the bot only sells. Fix the settings in Railway."))
    heartbeat = state["engine"]["heartbeat"]
    if heartbeat is None:
        out.append(("warn", "The bot has not started yet: nothing is running."))
    elif status.get("state") == "stopped":
        out.append(("bad", "The bot is stopped."))
    elif now - heartbeat > STALE_BANNER_S:
        out.append(("bad", f"The bot has not checked in for {round((now - heartbeat) / 60)} min: it may be down."))
    if status.get("unresolved_swaps"):
        out.append(("warn", "A trade's outcome is unknown: the bot is checking the wallet and pauses new buys."))
    out.sort(key=lambda a: a[0] != "bad")  # stable: worst first, otherwise in the order above
    return [{"level": level, "text": text} for level, text in out]


# =========================================================================== assembly


def build_page_state(ledger: Any, settings: Settings, now: float, engine_status: dict[str, Any] | None = None,
                     *, verify_cache: dict[str, Any] | None = None, memory: dict[str, Any] | None = None,
                     deploy: dict[str, str | None] | None = None) -> dict[str, Any]:
    """Assemble ``/api/page`` (schema in the module docstring). Same arguments as
    :func:`nightcrawler.teamroom.build_team_state`; ``memory`` also caches the learning card."""
    text = _Text(settings)
    state = build_state(ledger, settings, now, verify_cache)
    team = build_team_state(ledger, settings, now, engine_status, verify_cache=verify_cache, memory=memory,
                            deploy=deploy, state=state)
    card = learning_card(settings, now, ledger, memory)
    members = _members(team, card, now)
    counts = {"working": 0, "idle": 0, "waiting": 0, "blocked": 0}
    for m in members:
        counts[m["status"]] += 1
    usage, usage_alerts = _usage(state)
    receipts = state["receipts"]
    head = receipts["head_hash"]
    out = {
        "version": __version__,
        "generated_at": now,
        "mode": state["mode"],
        "refresh_s": REFRESH_S,
        "alerts": _alerts(ledger, state, now) + usage_alerts,
        "money": _money(settings, state["equity"]),
        "team": {"counts": counts, "members": members},
        "trades": _trades(ledger, settings, state, text),
        "learning": {"source": card["source"], "state": card["state"], "headline": card["headline"],
                     "variants": card["variants"], "data": card["data"], "rule": LEARNING_RULE},
        "ready": readiness(settings, card, wallet_address=state["wallet"]["address"],
                           wallet_sol=state["equity"]["sol"] if settings.is_live else None),
        "receipts": {"count": receipts["count"], "verified": receipts["verified"],
                     "first_bad_seq": receipts["first_bad_seq"], "head": head, "head_short": f"{head[:8]}…{head[-8:]}"},
        "usage": usage,
        "about": {"version": __version__, "uptime_s": team["engine"]["uptime_s"],
                  "commit": (deploy or {}).get("commit"), "started_at": team["engine"]["started_at"]},
    }
    clean: dict[str, Any] = scrub(out, text.secrets)
    return clean

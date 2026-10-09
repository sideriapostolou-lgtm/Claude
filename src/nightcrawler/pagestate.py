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
      "money": {"label", "usd", "start_usd", "sol", "sol_usd", "withdrawn_sol",  # live: sent back to the owner
                "since_start": {"usd", "pct"}, "today": {"usd", "pct"},   # the bot's own result (in SOL,
                "sol_price_effect_usd",                                   #  shown at today's SOL price)
                "curve": [[ts, usd], ...], "chart_ready": bool,           # chart after one hour of data
                "as_of": ts|null},                                        # the last money check
      "team": {"counts": {status: n}, "members": [{"id", "name", "role", "status", "why", "doing",
                                                    "last_activity", "events", "bars"?}]},
                                                    # status "absent": the Coach is not built (not counted)
      "trades": {"open": [{"coin", "entry_usd", "now_usd", "pnl_usd", "pnl_pct", "opened_at", "partial", "foreign"}],
                 "closed": [{"coin", "opened_at", "closed_at", "pnl_usd", "pnl_pct", "result", "why"}],
                 "max_open"},
      "learning": {"source": "card"|"missing"|"error", "state", "headline", "variants": [{"name", "n", "avg",
                   "proof"}], "data", "rule": str|null},
      "ready": readiness.readiness(...),
      "wallet": {"address", "sol", "checked_at", "own", "help", "paper_note", "note",   # the deposit address
                 "keep_note", "last_withdrawal": {"sol", "to", "at", "signature"}|null},
      "withdraw": {"status", "to", "level", "text"}|null,     # WITHDRAW_TO, or the hold after it (also a banner)
      "receipts": {"count", "verified", "first_bad_seq", "head", "head_short"},
      "usage": [{"label", "pct": float|null, "level": "ok"|"warn"|"over"|null, "text", "measured": bool}],
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
    paper_matches_backtest_reason | paper_reason: str, updated_at: epoch seconds (not in the future),
    can_stop_trading: bool (the module really can turn real trading off on its own)

Three honest outcomes: ``source: "card"`` (a card with a headline or a state), ``"missing"`` (the module is
not installed: the Coach shows "not built yet" and is left out of the team counts) and ``"error"`` (the
module raised or returned something that is not a card: the Coach is Blocked and checklist steps 1-2 say
unknown). Only an explicit ``True`` ever counts towards the checklist, and the "can turn real trading OFF"
rule is shown only when the card says ``can_stop_trading: true``. Wrong-typed values are dropped.

READY: the checklist (:mod:`nightcrawler.readiness`) never says Ready while any engine banner is up, and
reads the bot wallet's SOL from the last live equity snapshot (live) or the engine's paper-mode reading
(:mod:`nightcrawler.botwallet`), trusting a reading of the last :data:`WALLET_MAX_AGE_S` only.

WALLET: the bot wallet's PUBLIC address (live: kv ``wallet.pubkey``; paper: the bot's own wallet, kv
``keystore.pubkey``, or the address the engine read) with the same SOL reading, and how to fund it from
Phantom (live: right after a withdrawal landed, the balance the withdrawal read, until an equity snapshot is
newer). WITHDRAW: :func:`nightcrawler.withdraw.page_view` of kv ``withdraw.state`` while WITHDRAW_TO is set (or
of the hold after a live withdrawal), also the first banner (red while it is under way; it replaces the
kill-switch banner the engine's forced sell-off or hold would show). The money card adds back only SOL sent
back that the latest equity point already reflects. A wallet the bot made itself but does not use
(``BOT_WALLET_MODE=env``) is a banner too.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from nightcrawler import __version__
from nightcrawler.botwallet import saved_balance, wallet_configured
from nightcrawler.broker.keystore import KV_GENERATED, unused_wallet
from nightcrawler.config import Settings
from nightcrawler.dashboard import build_state, scrub
from nightcrawler.logging_setup import get_logger, redact_text
from nightcrawler.models import LAMPORTS_PER_SOL, EquityPoint
from nightcrawler.page import LEARNING_RULE, MEMBERS, REFRESH_S
from nightcrawler.readiness import readiness
from nightcrawler.teamroom import ENGINE_STALE_S, FUTURE_SKEW_S, build_team_state, derive_status, duration_text
from nightcrawler.withdraw import fresh_balance, last_withdrawal, live_hold, page_view, saved_state, withdrawn_lamports

__all__ = ["LEARNING_RULE", "MEMBERS", "STALE_BANNER_S", "WALLET_MAX_AGE_S", "build_page_state", "learning_card"]

log = get_logger(__name__)

#: The header turns red when the engine's heartbeat is older than this (it beats every 15 s); the team
#: room blocks every member from the same moment, so the banner and the chips always agree.
STALE_BANNER_S = ENGINE_STALE_S
#: The checklist trusts a bot wallet balance read this recently only (live: every minute; paper: 10 min).
WALLET_MAX_AGE_S = 3600.0
#: The learning module itself, as Python names it when it is absent.
_LEARN_MODULES = ("nightcrawler.learn", "nightcrawler.learn.card")
CHART_MIN_SPAN_S = 3600.0
OPEN_MAX = 10
CLOSED_MAX = 10
COIN_MAX = 24
WHY_MAX = 60
TEXT_MAX = 160
VARIANTS_MAX = 5
#: How to fund the bot wallet, for an owner with only the Phantom app.
FUND_HELP = "To fund: in Phantom tap Send, choose SOL, paste this address."
#: The bot's own wallet: its key exists only on the volume (broker/keystore.py).
KEEP_NOTE = ("Its key exists only on the Railway volume: keep the volume's backups on, and never delete the volume "
             "or the service while it holds SOL (withdraw first).")
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
    """The Coach's learning card, sanitized (schema in the module docstring): a real card, a "not installed"
    card or a "failed" card. Never raises. ``memory`` (kept between requests) caches it for
    :data:`LEARNING_TTL_S`."""
    cached = memory.get("learning") if memory is not None else None
    if cached is not None and 0 <= now - cached[0] < LEARNING_TTL_S:
        return dict(cached[1])
    outcome, raw = _load_card(settings, now)
    sanitized = _sanitize(raw, _Text(settings), now) if outcome == "ok" else None
    if outcome == "ok" and sanitized is None:
        log.warning("learning_card_invalid type=%s", type(raw).__name__)
    if outcome == "missing":
        card = _missing(now, ledger)
    else:
        card = sanitized or _failed()
    if memory is not None:
        memory["learning"] = (now, card)
    return dict(card)


def _load_card(settings: Settings, now: float) -> tuple[str, Any]:
    """``("ok", raw card)``, ``("missing", None)`` when the module is not installed, or ``("error", None)``."""
    try:
        from nightcrawler.learn.card import learning_card_state  # built on another branch; may be absent
    except ModuleNotFoundError as exc:
        if exc.name in _LEARN_MODULES:
            return "missing", None
        log.warning("learning_card_failed error=%s", type(exc).__name__)  # installed, but its import broke
        return "error", None
    except ImportError as exc:
        log.warning("learning_card_failed error=%s", type(exc).__name__)
        return "error", None
    try:
        return "ok", learning_card_state(settings, now)
    except Exception as exc:  # a broken learning module must never take the page down
        log.warning("learning_card_failed error=%s", type(exc).__name__)
        return "error", None


def _sanitize(raw: Any, text: _Text, now: float) -> dict[str, Any] | None:
    """The card's known keys, type-checked; None (a failure) unless it has a headline or a state."""
    if not isinstance(raw, Mapping):
        return None
    state, headline = text.opt(raw.get("state"), 60), text.opt(raw.get("headline"))
    if headline is None and state is None:
        return None
    champion = raw.get("champion")
    if isinstance(champion, Mapping):
        champion = champion.get("name")
    variants = _first(raw, "variants")
    items = variants if isinstance(variants, list) else []
    kept = [v for v in (_variant(item, text) for item in items) if v is not None]
    updated_at = _num(raw.get("updated_at"))
    return {
        "source": "card",
        "state": state,
        "headline": headline if headline is not None else f"Learning stage: {state}",
        "variants": kept[:VARIANTS_MAX],
        "data": text.opt(_first(raw, "data"), 200),
        "champion": text.opt(champion, 60),
        "champion_passed_locked_test": raw.get("champion_passed_locked_test") is True,
        "paper_matches_backtest": raw.get("paper_matches_backtest") is True,
        "paper_matches_backtest_reason": text.opt(_first(raw, "reason")),
        "can_stop_trading": raw.get("can_stop_trading") is True,
        # a stamp from the future (a millisecond epoch, say) would keep the Coach "Working" forever
        "updated_at": updated_at if updated_at is not None and updated_at <= now + FUTURE_SKEW_S else None,
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


def _empty_card(source: str, headline: str, data: str | None) -> dict[str, Any]:
    return {"source": source, "state": None, "headline": headline, "variants": [], "data": data, "champion": None,
            "champion_passed_locked_test": False, "paper_matches_backtest": False,
            "paper_matches_backtest_reason": None, "can_stop_trading": False, "updated_at": None}


def _missing(now: float, ledger: Any) -> dict[str, Any]:
    """The learning module is not installed: say so (day N since the first receipt)."""
    first = ledger.receipts(after_seq=0, limit=1)
    day = int(max(0.0, now - first[0].ts) // DAY_S) + 1 if first else 1
    return _empty_card("missing", "Not installed yet: nothing learns by itself in this version.",
                       f"The bot keeps every record from day 1 (today is day {day}) for the Coach to learn from "
                       "once it is added.")


def _failed() -> dict[str, Any]:
    """The learning module raised or returned something that is not a card (details in the logs)."""
    return _empty_card("error", "The learning system failed: see the logs.", None)


# =========================================================================== sections


def _latest_point(ledger: Any, mode: str) -> EquityPoint | None:
    """The newest equity snapshot when it belongs to ``mode`` (what ``build_state`` shows), else None."""
    point = ledger.latest_equity()
    return point if isinstance(point, EquityPoint) and point.mode == mode else None


def _money(settings: Settings, eq: dict[str, Any], point: EquityPoint | None,
           withdrawn: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    """``withdrawn``: live SOL (all time, today) sent back to the owner with WITHDRAW_TO - added back to the
    results, so taking money out never reads as a trading loss."""
    sol, sol_usd = eq["sol"], eq["sol_usd"]
    total, today = eq["pnl_total_sol"], eq["pnl_today_sol"]
    since_usd = eq["pnl_total_trading_usd"]
    out_total, out_today = (w / LAMPORTS_PER_SOL for w in withdrawn) if settings.is_live else (0.0, 0.0)
    base_total = sol - total if sol is not None and total is not None else None
    base_today = sol - today if sol is not None and today is not None else None
    if out_total and total is not None:
        total = total + out_total
        since_usd = _times(total, sol_usd)
    if out_today and today is not None:
        today = today + out_today
    curve = eq["curve"]
    span = curve[-1][0] - curve[0][0] if len(curve) >= 2 else 0.0
    return {
        "label": "Real money" if settings.is_live else "Paper money (pretend)",
        "usd": eq["usd"], "start_usd": eq["start_usd"], "sol": sol, "sol_usd": sol_usd,
        "withdrawn_sol": out_total or None,
        "since_start": {"usd": since_usd, "pct": _pct(total, base_total)},
        "today": {"usd": _times(today, sol_usd), "pct": _pct(today, base_today)},
        "sol_price_effect_usd": eq["sol_price_effect_usd"],
        "curve": curve, "chart_ready": span >= CHART_MIN_SPAN_S,
        "as_of": point.ts if point is not None else (curve[-1][0] if curve else None),
    }


def _withdrawn(ledger: Any, settings: Settings, point: EquityPoint | None, now: float) -> tuple[int, int]:
    """Live SOL sent back to the owner that the latest equity point ``point`` already reflects ``(since the
    start, since today's first point)`` - a later withdrawal is not in that point yet (it would count twice)."""
    if not settings.is_live or point is None or not ledger.get_kv("withdraw.totals"):
        return 0, 0
    first = next((p for p in ledger.equity_series(since=now - now % 86_400) if p.mode == point.mode), None)
    return withdrawn_lamports(ledger, point.ts, first.ts if first is not None else None)


def _coach(card: dict[str, Any], now: float) -> tuple[str, str]:
    if card["source"] == "missing":
        return "absent", "not built yet"
    if card["source"] == "error":
        return "blocked", "the learning system failed: see the logs"
    return derive_status(now, card["updated_at"], COACH_WINDOW_S,
                         waiting="collecting data: nothing to learn from yet" if card["state"] == "collecting"
                         else None, idle="no new lesson recently")


def _members(team: dict[str, Any], card: dict[str, Any], now: float) -> list[dict[str, Any]]:
    panels = {p["id"]: p for p in team["panels"]}
    out = []
    for mid, name, role in MEMBERS:
        if mid == "coach":
            status, why = _coach(card, now)
            out.append({"id": mid, "name": name, "role": role, "status": status, "why": why,
                        "doing": card["headline"], "last_activity": card["updated_at"], "events": []})
            continue
        p = panels[mid]
        last = p["last_activity"]  # never "last active 0 s ago" for a stamp from the future
        member = {"id": mid, "name": name, "role": role, "status": p["status"], "why": p["why"], "doing": p["doing"],
                  "last_activity": last if last is None or last <= now + FUTURE_SKEW_S else None,
                  "events": p["events"]}
        if p.get("bars"):
            member["bars"] = p["bars"]
        out.append(member)
    return out


def _trades(ledger: Any, settings: Settings, state: dict[str, Any], text: _Text) -> dict[str, Any]:
    mode = "live" if settings.is_live else "paper"
    sol_usd = state["equity"]["sol_usd"]
    opened = [{"coin": text(p["symbol"] or _short(p["mint"]), COIN_MAX), "entry_usd": p["entry_price_usd"] or None,
               "now_usd": p["last_price_usd"], "pnl_usd": _times(p["unrealized_pnl_sol"], sol_usd),
               "pnl_pct": p["unrealized_pnl_pct"], "opened_at": p["opened_at"], "partial": p["partial_taken"],
               "foreign": bool(p.get("foreign_wallet"))}
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
    """``(rows, alerts)``: one row per provider; a budget that is used up also goes to the header. Until the
    call counters have saved anything (kv ``usage.providers``) a row says "not measured yet", never "0 calls"
    (the AI judge measures its own spending, so its row always counts)."""
    rows, alerts = [], []
    counted = state["usage"]["updated_at"] is not None
    for r in state["usage"]["providers"]:
        when = "today" if r["period"] == "day" else "this month"
        if not counted and r["id"] != "anthropic":
            rows.append({"label": r["label"], "pct": None, "level": None, "text": "not measured yet",
                         "measured": False})
        elif r["budget"]:
            if r["unit"] == "usd":
                used = f"${r['used']:.2f} of ${r['budget']:.2f} {when}"
            else:
                used = f"{int(r['used']):,} of {int(r['budget']):,} {r['unit']} {when}"
            rows.append({"label": r["label"], "pct": r["used_pct"], "level": r["level"], "text": used,
                         "measured": True})
            if r["level"] == "over":
                alerts.append({"level": "warn", "text": f"{r['label']} is over its "
                               f"{'daily' if r['period'] == 'day' else 'monthly'} budget ({r['used_pct']:.0f}%)."})
        else:
            calls = int(r["calls_today"])
            rows.append({"label": r["label"], "pct": None, "level": None,
                         "text": f"{calls:,} call{'' if calls == 1 else 's'} today", "measured": True})
    return rows, alerts


def _alerts(ledger: Any, state: dict[str, Any], now: float, withdrawal: dict[str, Any] | None = None,
            settings: Settings | None = None) -> list[dict[str, str]]:
    """Header banners from real trouble only, worst first. ``withdrawal``: :func:`nightcrawler.withdraw.page_view`
    (WITHDRAW_TO set, or the hold after a live withdrawal): its banner comes first and replaces the kill-switch
    banner the engine's forced sell-off (or hold) would show."""
    out = []
    if withdrawal is not None:
        out.append((withdrawal["level"], withdrawal["text"]))
    elif state["kill"] == "sell_all":
        out.append(("bad", "Kill switch is ON: the bot is selling everything and buying nothing."))
    elif state["kill"] == "stop":
        out.append(("bad", "Kill switch is ON: the bot buys nothing new (open trades are still looked after)."))
    unused = unused_wallet(settings, ledger) if settings is not None else None
    if unused is not None:
        out.append(("bad", f"The bot's own wallet {unused or '(address unknown)'} is not in use: BOT_WALLET_MODE is "
                           "not 'generated'. If it holds SOL, only the bot can move it: set BOT_WALLET_MODE=generated "
                           "(delete BOT_WALLET_SECRET), then take it back with WITHDRAW_TO."))
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
        out.append(("bad", f"The bot has not checked in for {duration_text(now - heartbeat)}: it may be down."))
    if status.get("unresolved_swaps"):
        out.append(("warn", "A trade's outcome is unknown: the bot is checking the wallet and pauses new buys."))
    out.sort(key=lambda a: a[0] != "bad")  # stable: worst first, otherwise in the order above
    return [{"level": level, "text": text} for level, text in out]


def _wallet(ledger: Any, settings: Settings, state: dict[str, Any], point: EquityPoint | None, now: float
            ) -> tuple[str | None, float | None, float | None]:
    """``(address, SOL, read at)`` of the bot wallet for checklist step 3 and the wallet card; SOL is None unless
    read in the last :data:`WALLET_MAX_AGE_S`. Live: the wallet's SOL in the last snapshot (not its total value,
    which counts the coins it holds). Paper: the engine's own reading, only while a bot wallet is set up; with
    the bot's own wallet its address is known from the start, and a reading of another wallet does not count."""
    if settings.is_live:
        address = state["wallet"]["address"]
        after = fresh_balance(saved_state(ledger), point.ts if point is not None else None)
        if after is not None and now - after[1] <= WALLET_MAX_AGE_S:  # read right after a withdrawal landed
            return address, after[0], after[1]
        if point is None or now - point.ts > WALLET_MAX_AGE_S:
            return address, None, None
        return address, point.sol_lamports / LAMPORTS_PER_SOL, point.ts
    saved = saved_balance(ledger) if wallet_configured(settings) else None
    own = ledger.get_kv(KV_GENERATED) if settings.bot_wallet_mode == "generated" else None
    if isinstance(own, str) and own and (saved is None or saved.address != own):
        return own, None, None
    if saved is None:
        return None, None, None
    if now - saved.checked_at > WALLET_MAX_AGE_S:
        return saved.address, None, None
    return saved.address, saved.sol_lamports / LAMPORTS_PER_SOL, saved.checked_at


def _wallet_card(settings: Settings, address: str | None, sol: float | None, read_at: float | None,
                 withdraw_state: dict[str, Any] | None) -> dict[str, Any]:
    """The bot wallet's deposit address (public), its SOL and how to fund it from Phantom."""
    own = settings.bot_wallet_mode == "generated"
    note = None
    if not address:
        note = ("No bot wallet yet. Set BOT_WALLET_MODE=generated in Railway: the bot makes its own wallet and shows "
                "its address here." if not (settings.is_live or wallet_configured(settings))
                else "The address shows here once the bot has started.")
    return {"address": address, "sol": sol, "checked_at": read_at, "own": own,
            "help": FUND_HELP if address else None, "keep_note": KEEP_NOTE if address and own else None,
            "paper_note": ("This is real SOL, even in paper mode: paper trades never spend it."
                           if address and not settings.is_live else None),
            "note": note, "last_withdrawal": last_withdrawal(withdraw_state)}


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
        if m["status"] in counts:  # a member that is not built yet is not part of the team's count
            counts[m["status"]] += 1
    usage, usage_alerts = _usage(state)
    withdraw_state = saved_state(ledger)
    withdrawal = page_view(settings, withdraw_state, now, live_hold(ledger))
    alerts = _alerts(ledger, state, now, withdrawal, settings)
    point = _latest_point(ledger, "live" if settings.is_live else "paper")
    address, wallet_sol, wallet_read_at = _wallet(ledger, settings, state, point, now)
    receipts = state["receipts"]
    head = receipts["head_hash"]
    out = {
        "version": __version__,
        "generated_at": now,
        "mode": state["mode"],
        "refresh_s": REFRESH_S,
        "alerts": alerts + usage_alerts,
        "money": _money(settings, state["equity"], point, _withdrawn(ledger, settings, point, now)),
        "team": {"counts": counts, "members": members},
        "trades": _trades(ledger, settings, state, text),
        "learning": {"source": card["source"], "state": card["state"], "headline": card["headline"],
                     "variants": card["variants"], "data": card["data"],
                     "rule": LEARNING_RULE if card["source"] == "card" and card["can_stop_trading"] else None},
        # never "Ready" while a banner says the bot is stopped, silent or in trouble (budget banners aside)
        "ready": readiness(settings, card, wallet_address=address, wallet_sol=wallet_sol, stopped=bool(alerts),
                           now=now),
        "wallet": _wallet_card(settings, address, wallet_sol, wallet_read_at, withdraw_state),
        "withdraw": withdrawal,
        "receipts": {"count": receipts["count"], "verified": receipts["verified"],
                     "first_bad_seq": receipts["first_bad_seq"], "head": head, "head_short": f"{head[:8]}…{head[-8:]}"},
        "usage": usage,
        "about": {"version": __version__, "uptime_s": team["engine"]["uptime_s"],
                  "commit": (deploy or {}).get("commit"), "started_at": team["engine"]["started_at"]},
    }
    clean: dict[str, Any] = scrub(out, text.secrets)
    return clean

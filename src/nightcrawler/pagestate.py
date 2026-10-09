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
                "as_of": ts|null,                                         # the last money check
                "polymarket": {"mode": "paper"|"live", "label", "as_of": ts|null,   # see POLYMARKET; null: desk off
                               "paper": {"label": "Paper money (pretend)", "open", "today_usd", "since_start_usd",
                                         "settled_today", "won_today", "settled_total", "won_total"},
                               "real": {"label": "Real money", (the same keys), "at_risk_usd", "contracts",
                                        "cost_usd", "value_usd", "venue_at", "cash_usd", "cash_at"}|null}|null,
                "trend": {"mode": "paper", "label": "Paper money (pretend)", "as_of": ts|null,   # see TREND; null: off
                          "sleeve_usd", "equity_usd", "today_usd", "since_start_usd", "hold_since_start_usd",
                          "in_market": {"BTC": bool, "ETH": bool, "SOL": bool}, "started": "YYYY-MM-DD"|null,
                          "problem": str|null, "lab": {"since_start_usd", "hold_since_start_usd"}|null,
                          "reset_from": str|null}|null},
      "town": {"label", "cost_per_day_usd", "cost_today_usd", "cost_since_start_usd": float|null,  # see TOWN
               "income_today_usd": float|null, "income_since_start_usd": float|null,
               "covered_today": bool|null, "covered_since_start": bool|null, "line",
               "polymarket": {"paper": {"label", "open", "today_usd", "since_start_usd", "line"},  # the desk in words
                              "real": {"label", "open", "contracts", "cost_usd", "value_usd", "today_usd",
                                       "settled_today", "won_today", "since_start_usd", "cash_usd", "line"}|null}|null,
               "trend": {"line"}|null},                                   # the trend desk in words (TREND)
      "team": {"counts": {status: n}, "members": [{"id", "name", "role", "status", "why", "doing",
                                                    "last_activity", "events", "bars"?}]},
                                                    # status "absent": the Coach is not built (not counted)
      "trades": {"open": [{"coin", "entry_usd", "now_usd", "pnl_usd", "pnl_pct", "opened_at", "partial", "foreign"}],
                 "closed": [{"coin", "opened_at", "closed_at", "pnl_usd", "pnl_pct", "result", "why"}],
                 "max_open"},
      "learning": {"source": "card"|"missing"|"error", "state", "headline", "variants": [{"name", "n", "avg",
                   "proof"}], "data", "rule": str|null},
      "experience": {...},                                            # the report cards: see EXPERIENCE below
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

TOWN ("keep the town alive", :func:`town_ledger`): the desks must earn more than the town costs to run. Costs:
Railway's price per month (``TOWN_RAILWAY_USD_MONTH``; a day is 1/30 of it) plus the AI judge's spending
(``judge.cost_usd_today`` and ``judge.cost_usd_total`` of ``/api/state``; a missing figure counts as nothing
recorded, and without a figure for today the total is spread over the days run so far). ``cost_per_day_usd``: the
day rate, Railway's day plus the judge's spend today. ``cost_today_usd``: the cost so far today, Railway's day
prorated over the part of the UTC day that has passed (since the start, when the run began today) plus the
judge's spend today. ``cost_since_start_usd``: Railway's price over the run so far plus the judge's total. The run
starts at the ledger's first record (the first boot on this volume) or at ``engine.started_at``, whichever is
earlier: a redeploy restarts the engine, not the bill, the judge's total or the money since start. Income is the
money card's own result (``money.today.usd``, ``money.since_start.usd``): the SOL bot's figures, nothing else.
Whatever is not known is null (income before the first money check; the since-start cost before the first record)
and the line says so; ``covered_*`` is null while either side is unknown. The Polymarket desk is counted apart
(``town.polymarket``, POLYMARKET below): one line for its paper book and, only while it has a real book, one for its
real money, and ``line`` names each desk ("the Solana desk lost $3.18 and the Polymarket desk lost $1,345.53 today
(paper money, pretend)"); no figure of one kind of money is ever added to another.

POLYMARKET (:func:`polymarket_desk`): the Polymarket desk's books (:func:`nightcrawler.polydesk.panel_state`, its
state file only), kept apart from the SOL wallet and from each other. ``paper`` is the desk's own paper tally (the
candidate rule's pretend tickets); ``real`` is what came from the venue's own book: the open positions the venue
holds (``live``), the desk's real settlements, the venue's contract count, cost and value (``exchange``) and its
cash (``balance``). ``real`` is null unless the desk has a real book (an open real position, a real settlement or
a contract at the venue) or the venue's cash was read; ``money.polymarket`` is null when the desk is off
(``POLYDESK_ENABLED``) or its state cannot be read: nothing is shown rather than a made-up zero. A paper tally of
zero before the desk's first round is marked ``as_of: null`` ("no round finished yet").

TREND (:func:`trend_desk`): the trend desk's paper book (:func:`nightcrawler.trenddesk.panel_state`, its state file
only), a forward test of lab 3's 50-day trend rule on BTC, ETH and SOL with a pretend sleeve. PAPER ONLY: the desk
has no real-money path at all. ``as_of`` is the last daily close it booked (null before the first one: the figures
are then the untouched sleeve). ``equity_usd``, ``today_usd`` (the last day's change) and ``since_start_usd`` are the
rule's book kept as a real account would keep it: three separate thirds, one per coin, never re-balanced.
``hold_since_start_usd`` is the benchmark the rule has to beat: holding the three, bought on day one and never
touched (the desk's ``bh`` book, same costs). ``lab`` is lab 3's own reckoning of both (the book put back to thirds
every day for free), for comparison with the lab only, never the result. ``problem`` says in plain words when the
book is behind (Coinbase not read, a candle late); ``reset_from`` names the earlier record this one replaced because
it could not be read (null otherwise). ``town.trend.line`` says the same in one sentence ("Trend desk (paper,
pretend): in BTC and SOL, out of ETH; since start +$1.20 vs holding the three (bought on day one, never touched)
+$0.40"; "record restarted <day>" after the label while ``reset_from`` is set). Its figures are never added to the
SOL wallet's, the Polymarket desk's or the town's income: the town's own line and bars are untouched. Null when the
desk is off (``TRENDDESK_ENABLED``) or its state cannot be read.

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

EXPERIENCE (docs/EXPERIENCE.md §9): :func:`experience_card` calls
``nightcrawler.experience.state.experience_state(settings, now)`` when that module exists (another team builds
it) and keeps exactly the keys of the §9 schema, each type-checked; every key is always present and unknown
values are null::

    {"source": "state"|"missing"|"error", "headline": [str, str], "bars_line", "money_line", "caveat",
     "team": {"graded", "days", "practised", "practised_window", "skills_shown", "skills_measurable": 4,
              "collecting", "not_measured": [str], "updated_at"},
     "members": {member id: {"kind", "label", "chip", "line", "graded", "days", "practised",
                             "metrics": [{"name", "value", "lo", "hi", "baseline", "unit", "text"}] (<= 3),
                             "exam": {"split", "version12", "date", "result", "current"}|null,
                             "trend": [[week_start, value, lo, hi]] (<= 8), "version_line", "independent",
                             "lessons": {"open", "testing", "adopted", "rejected"}, "coverage", "budget_left"}},
     "loss_types_week": [{"type", "n", "expected", "text"}] (<= 3), "lessons": [{"id", "status", "text"}] (<= 3),
     "playbook": {"validated", "rejected", "in_bot_contradicted", "in_bot_unsupported", "testing",
                  "false_keep_bound"}}

The honesty rules of §5.1 and §8.4 are checked HERE too, at the page's boundary, and a state that breaks one is
shown as ``source: "error"`` (nothing of it is shown): each member has the card kind of :data:`EXPERIENCE_KINDS`
and a label of that kind; "Skill shown" and "Worse than chance" need a primary band entirely on one side of the
chance baseline; "Meets the bar" needs a band on the good side of the bar; the Broker is never graded on paper;
the skill count equals the members labelled skilled. The chip WORD always comes from the label
(:data:`EXPERIENCE_CHIPS`), never from the state's own text. The money line says
:data:`EXPERIENCE_MONEY_LINE` unless the Coach's own card is ``paper_champion``, ``live_ready`` or ``live``, and
the caveat is fixed. Report cards never feed the checklist or the banners: they cannot turn trading on. The
playbook counts fall back to the static ``experience/playbook.json`` (generated from GROUNDED) when the state
has none; an unreadable file gives null counts, never zeros.

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

import functools
import itertools
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from nightcrawler import __version__, trenddesk
from nightcrawler.botwallet import saved_balance, wallet_configured
from nightcrawler.broker.keystore import KV_GENERATED, unused_wallet
from nightcrawler.config import Settings
from nightcrawler.dashboard import build_state, scrub
from nightcrawler.logging_setup import get_logger, redact_text
from nightcrawler.models import LAMPORTS_PER_SOL, EquityPoint
from nightcrawler.page import LEARNING_RULE, MEMBERS, REFRESH_S
from nightcrawler.polydesk import panel_state
from nightcrawler.readiness import readiness
from nightcrawler.teamroom import ENGINE_STALE_S, FUTURE_SKEW_S, build_team_state, derive_status, duration_text
from nightcrawler.withdraw import fresh_balance, last_withdrawal, live_hold, page_view, saved_state, withdrawn_lamports

__all__ = ["EXPERIENCE_CAVEAT", "EXPERIENCE_CHIPS", "EXPERIENCE_KINDS", "EXPERIENCE_MONEY_LINE", "LEARNING_RULE",
           "MEMBERS", "PAPER_LABEL", "PLAYBOOK_PATH", "REAL_LABEL", "STALE_BANNER_S", "TOWN_MONTH_DAYS",
           "WALLET_MAX_AGE_S", "build_page_state", "experience_card", "learning_card", "polymarket_desk", "town_ledger",
           "trend_desk"]

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
#: The town's hosting bill is a monthly price: a day of it is 1/30.
TOWN_MONTH_DAYS = 30.0
#: The money labels: the page must always make clear when the money is pretend.
PAPER_LABEL = "Paper money (pretend)"
REAL_LABEL = "Real money"
#: The page's own minus sign (U+2212), as its script prints a signed dollar figure.
_MINUS = "−"

#: The experience state (the report cards) is re-read at most this often.
EXPERIENCE_TTL_S = 60.0
#: The experience module itself, as Python names it when it is absent.
_EXPERIENCE_MODULES = ("nightcrawler.experience", "nightcrawler.experience.state")
#: The static playbook (generated from docs/EXPERIENCE_GROUNDED.md by scripts/gen_playbook.py).
PLAYBOOK_PATH = Path(__file__).resolve().parent / "experience" / "playbook.json"
#: docs/EXPERIENCE.md §8.2: the last line of the team's headline, always.
EXPERIENCE_CAVEAT = "Avoiding losses is not the same as making money."
#: The money line until the Coach itself has shown a strategy that makes money on coins it never saw.
EXPERIENCE_MONEY_LINE = "Making money: not shown yet — holding cash."
#: Coach card states that let the experience state word the money line itself (LEARNING §9).
_MONEY_STATES = ("paper_champion", "live_ready", "live")
#: The card kind of each member (docs/EXPERIENCE.md §5.1): only "chance" cards can show skill.
EXPERIENCE_KINDS = {"crawler": "bar", "cocoon": "chance", "strategy": "chance", "radar": "chance", "judge": "chance",
                    "broker": "bar", "risk": "bar", "receipts": "self_check", "coach": "self_check"}
#: The chip word of each label, per card kind (§5.1). A self-check is never green.
EXPERIENCE_CHIPS = {
    "chance": {"not_measured": "Not measured", "not_enough": "Collecting", "no_skill_yet": "No skill yet",
               "skilled": "Skill shown", "worse": "Worse than chance"},
    "bar": {"not_measured": "Not measured", "not_enough": "Collecting", "meets_bar": "Meets the bar",
            "below_bar": "Below the bar"},
    "self_check": {"not_built": "Not built yet", "checks_pass": "Checks pass", "check_failed": "Check failed"},
}
#: Risk's bar is a tolerance (§5.1).
_RISK_CHIPS = {"meets_bar": "Within tolerance", "below_bar": "Over tolerance"}
#: The good side of each bar (§5.2): coverage must reach its bar; shortfall and ruin must stay under theirs.
_BAR_GOOD_ABOVE = {"crawler": True, "broker": False, "risk": False}
#: Cocoon, Strategy, Radar and Jev: the cards that can show skill.
SKILL_MEMBERS = sum(kind == "chance" for kind in EXPERIENCE_KINDS.values())
_XP_UNITS = ("pp", "share", "ratio", "count", "s")
_XP_LESSON_KEYS = ("open", "testing", "adopted", "rejected")
_XP_PLAYBOOK_KEYS = ("validated", "rejected", "in_bot_contradicted", "in_bot_unsupported", "testing")
_XP_FALSE_KEEP = "1 in 10"
_XP_WORD = re.compile(r"[a-z][a-z0-9_]{0,29}")
_XP_HEX = re.compile(r"[0-9a-f]{1,12}")
XP_METRICS_MAX = 3
XP_LIST_MAX = 3  # loss types this week and lessons on the page
XP_TREND_MAX = 8  # weeks
XP_NAMES_MAX = 9
XP_LINE_MAX = 320  # a card's plain-words sentence
XP_COUNT_MAX = 10**9
XP_NUM_MAX = 1e9

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


# =========================================================================== experience (report cards)


class _Refused(ValueError):
    """The experience state breaks a rule of the §9 schema or an honesty rule of §5.1: shown as an error."""


def experience_card(settings: Settings, now: float, card: Mapping[str, Any], memory: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """The team's report cards for ``/api/page.experience`` (schema and rules in the module docstring): a sanitized
    state, a "not installed" one or a "failed" one. ``card`` is the sanitized learning card (the money line follows
    the Coach). Never raises. ``memory`` (kept between requests) caches what was read for
    :data:`EXPERIENCE_TTL_S`."""
    cached = memory.get("experience") if memory is not None else None
    if cached is not None and 0 <= now - cached[0] < EXPERIENCE_TTL_S:
        outcome, raw = cached[1]
    else:
        outcome, raw = _load_experience(settings, now)
        if memory is not None:
            memory["experience"] = (now, (outcome, raw))
    static = _static_playbook(str(PLAYBOOK_PATH))
    if outcome != "ok":
        return _xp_empty(outcome, static)
    coach = card.get("state") if card.get("source") == "card" else None
    try:
        return _xp_state(raw, _Text(settings), now, live=settings.is_live, coach_state=coach, static=static)
    except _Refused as exc:
        log.warning("experience_state_refused reason=%s", exc)
    except Exception as exc:  # a strange object from another team's module must never take the page down
        log.warning("experience_state_failed error=%s", type(exc).__name__)
    return _xp_empty("error", static)


def _load_experience(settings: Settings, now: float) -> tuple[str, Any]:
    """``("ok", raw state)``, ``("missing", None)`` when the module is not installed, or ``("error", None)``."""
    try:
        from nightcrawler.experience.state import experience_state  # built by another team; may be absent
    except ModuleNotFoundError as exc:
        if exc.name in _EXPERIENCE_MODULES:
            return "missing", None
        log.warning("experience_state_failed error=%s", type(exc).__name__)  # installed, but its import broke
        return "error", None
    except ImportError as exc:
        log.warning("experience_state_failed error=%s", type(exc).__name__)
        return "error", None
    try:
        return "ok", experience_state(settings, now)
    except Exception as exc:  # a broken experience module must never take the page down
        log.warning("experience_state_failed error=%s", type(exc).__name__)
        return "error", None


@functools.lru_cache(maxsize=4)
def _static_playbook(path: str) -> dict[str, Any]:
    """The playbook counts by initial status, from the static file (read once per process); null when unreadable:
    "0 rules contradicted" would be a false claim."""
    try:
        rules = json.loads(Path(path).read_text(encoding="utf-8"))["rules"]
        statuses = Counter(rule["status"] for rule in rules)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("playbook_unreadable error=%s", type(exc).__name__)
        return {**dict.fromkeys(_XP_PLAYBOOK_KEYS), "false_keep_bound": _XP_FALSE_KEEP}
    return {**{key: statuses.get(key, 0) for key in _XP_PLAYBOOK_KEYS}, "false_keep_bound": _XP_FALSE_KEEP}


def _xp_empty(source: str, playbook: Mapping[str, Any]) -> dict[str, Any]:
    return {"source": source, "headline": ["", ""], "bars_line": "", "money_line": "", "caveat": EXPERIENCE_CAVEAT,
            "team": {"graded": None, "days": None, "practised": None, "practised_window": "", "skills_shown": None,
                     "skills_measurable": SKILL_MEMBERS, "collecting": None, "not_measured": [], "updated_at": None},
            "members": {}, "loss_types_week": [], "lessons": [], "playbook": dict(playbook)}


def _count(value: Any) -> int | None:
    """A whole number in [0, 10**9] (bool is not a number), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and 0 <= value <= XP_COUNT_MAX else None


def _xp_num(value: Any) -> float | None:
    number = _num(value)
    return number if number is not None and abs(number) < XP_NUM_MAX else None


def _xp_str(text: _Text, value: Any, limit: int = TEXT_MAX) -> str:
    return text.opt(value, limit) or ""


def _xp_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _xp_map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _xp_state(raw: Any, text: _Text, now: float, *, live: bool, coach_state: Any,
              static: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _Refused("not a mapping")
    if raw.get("source") in ("missing", "error"):  # the module itself says it has nothing (yet)
        return _xp_empty(raw["source"], static)
    members_raw = raw.get("members")
    if not isinstance(members_raw, Mapping):
        raise _Refused("members")
    members = {}
    for mid, _, _ in MEMBERS:
        if mid not in EXPERIENCE_KINDS:
            continue  # a desk the report cards do not grade (yet), e.g. the Polymarket paper desk
        key = "jev" if mid == "judge" and mid not in members_raw and "jev" in members_raw else mid
        if key in members_raw:
            members[mid] = _xp_member(mid, members_raw[key], text, live=live)
    headline = raw.get("headline")
    lines = [_xp_str(text, line) for line in headline[:2]] if isinstance(headline, list) else []
    lines += [""] * (2 - len(lines))
    if not members and not any(lines):
        raise _Refused("empty")
    team = _xp_team(raw.get("team"), members, text, now)
    money = _xp_str(text, raw.get("money_line")) if coach_state in _MONEY_STATES else ""
    return {
        "source": "state", "headline": lines, "bars_line": _xp_str(text, raw.get("bars_line")),
        "money_line": money or EXPERIENCE_MONEY_LINE, "caveat": EXPERIENCE_CAVEAT, "team": team, "members": members,
        "loss_types_week": _xp_items(raw.get("loss_types_week"), _xp_loss, text),
        "lessons": _xp_items(raw.get("lessons"), _xp_lesson, text),
        "playbook": _xp_playbook(raw.get("playbook"), static, text),
    }


def _xp_member(mid: str, raw: Any, text: _Text, *, live: bool) -> dict[str, Any]:
    kind = EXPERIENCE_KINDS[mid]
    if not isinstance(raw, Mapping):
        raise _Refused(f"member={mid}")
    label = raw.get("label")
    if raw.get("kind") != kind or not isinstance(label, str) or label not in EXPERIENCE_CHIPS[kind]:
        raise _Refused(f"kind_or_label member={mid}")
    items = _xp_list(raw.get("metrics"))
    _xp_check_claim(mid, kind, label, _xp_metric(items[0], text) if items else None, live=live)
    metrics = [m for m in (_xp_metric(item, text) for item in items[:XP_METRICS_MAX]) if m is not None]
    lessons = _xp_map(raw.get("lessons"))
    budget = _xp_num(raw.get("budget_left"))
    chip = _RISK_CHIPS[label] if mid == "risk" and label in _RISK_CHIPS else EXPERIENCE_CHIPS[kind][label]
    return {
        "kind": kind, "label": label, "chip": chip,
        "line": _xp_str(text, raw.get("line"), XP_LINE_MAX), "graded": _count(raw.get("graded")),
        "days": _count(raw.get("days")), "practised": _count(raw.get("practised")), "metrics": metrics,
        "exam": _xp_exam(raw.get("exam"), text), "trend": _xp_trend(raw.get("trend")),
        "version_line": _xp_str(text, raw.get("version_line")), "independent": _xp_str(text, raw.get("independent")),
        "lessons": {key: _count(lessons.get(key)) or 0 for key in _XP_LESSON_KEYS},
        "coverage": _xp_str(text, raw.get("coverage")),
        "budget_left": budget if budget is not None and 0.0 <= budget <= 1.0 else None,
    }


def _xp_check_claim(mid: str, kind: str, label: str, primary: dict[str, Any] | None, *, live: bool) -> None:
    """Green and "worse" claims need the primary band on one side of the baseline or bar (§5.1); on paper the
    Broker is never graded (§5.2: the paper fill and the cost model share the same haircut by construction)."""
    if mid == "broker" and not live and label != "not_measured":
        raise _Refused("broker_graded_on_paper")
    if label not in ("skilled", "worse", "meets_bar"):
        return
    lo, hi, base = (primary or {}).get("lo"), (primary or {}).get("hi"), (primary or {}).get("baseline")
    if lo is None or hi is None or base is None:
        raise _Refused(f"claim_without_band member={mid}")
    if label == "skilled":
        backed = lo > base
    elif label == "worse":
        backed = hi < base
    else:
        backed = lo >= base if _BAR_GOOD_ABOVE[mid] else hi <= base
    if not backed:
        raise _Refused(f"claim_not_backed member={mid}")


def _xp_metric(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or raw.get("unit") not in _XP_UNITS:
        return None
    name = text.opt(raw.get("name"), 60)
    if name is None:
        return None
    lo, hi = _xp_num(raw.get("lo")), _xp_num(raw.get("hi"))
    if lo is None or hi is None or lo > hi:  # half a band, or an upside-down one, is no band
        lo = hi = None
    return {"name": name, "value": _xp_num(raw.get("value")), "lo": lo, "hi": hi,
            "baseline": _xp_num(raw.get("baseline")), "unit": raw["unit"], "text": _xp_str(text, raw.get("text"))}


def _xp_exam(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    result = text.opt(raw.get("result"), 30)
    if result is None:
        return None
    version = raw.get("version12")
    return {"split": _xp_str(text, raw.get("split"), 20),
            "version12": version if isinstance(version, str) and _XP_HEX.fullmatch(version) else "",
            "date": _xp_str(text, raw.get("date"), 20), "result": result, "current": raw.get("current") is True}


def _xp_trend(raw: Any) -> list[list[float | None]]:
    """Weekly ``[week_start, value, lo, hi]`` of the primary metric, the last :data:`XP_TREND_MAX` weeks."""
    weeks = []
    for item in _xp_list(raw):
        if not isinstance(item, list) or len(item) != 4:
            continue
        start, value = _num(item[0]), _xp_num(item[1])  # a week's start is an epoch, not a metric value
        if start is None or value is None:
            continue
        lo, hi = _xp_num(item[2]), _xp_num(item[3])
        weeks.append([start, value, *((lo, hi) if lo is not None and hi is not None and lo <= hi else (None, None))])
    return weeks[-XP_TREND_MAX:]


def _xp_team(raw: Any, members: Mapping[str, Mapping[str, Any]], text: _Text, now: float) -> dict[str, Any]:
    team = _xp_map(raw)
    claimed = _count(team.get("skills_shown"))
    graded = [m for m in members.values() if m["kind"] == "chance"]
    shown = sum(m["label"] == "skilled" for m in graded) if graded else claimed
    if claimed is not None and claimed != shown:  # the headline's count would disagree with the chips
        raise _Refused("skills_shown")
    names = _xp_list(team.get("not_measured"))
    updated = _num(team.get("updated_at"))
    return {
        "graded": _count(team.get("graded")), "days": _count(team.get("days")),
        "practised": _count(team.get("practised")),
        "practised_window": _xp_str(text, team.get("practised_window"), 60), "skills_shown": shown,
        "skills_measurable": SKILL_MEMBERS, "collecting": _count(team.get("collecting")),
        "not_measured": [n for n in (text.opt(name, 40) for name in names[:XP_NAMES_MAX]) if n is not None],
        "updated_at": updated if updated is not None and updated <= now + FUTURE_SKEW_S else None,
    }


def _xp_items(raw: Any, keep: Callable[[Any, _Text], dict[str, Any] | None], text: _Text) -> list[dict[str, Any]]:
    """The first :data:`XP_LIST_MAX` well-formed items of a list (the rest is never even looked at)."""
    kept = (item for item in (keep(x, text) for x in _xp_list(raw)) if item is not None)
    return list(itertools.islice(kept, XP_LIST_MAX))


def _xp_loss(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("type"), str) or not _XP_WORD.fullmatch(raw["type"]):
        return None
    n, expected = _count(raw.get("n")), _xp_num(raw.get("expected"))
    if n is None:
        return None
    return {"type": raw["type"], "n": n, "expected": expected if expected is not None and expected >= 0 else None,
            "text": _xp_str(text, raw.get("text"))}


def _xp_lesson(raw: Any, text: _Text) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    status, words = raw.get("status"), _xp_str(text, raw.get("text"))
    lesson_id = _xp_str(text, raw.get("id"), 40)
    if not isinstance(status, str) or not _XP_WORD.fullmatch(status) or not (words or lesson_id):
        return None
    return {"id": lesson_id, "status": status, "text": words}


def _xp_playbook(raw: Any, static: Mapping[str, Any], text: _Text) -> dict[str, Any]:
    book = _xp_map(raw)
    counts = {key: _count(book.get(key)) for key in _XP_PLAYBOOK_KEYS}
    if all(v is None for v in counts.values()):
        return dict(static)
    return {**counts, "false_keep_bound": _xp_str(text, book.get("false_keep_bound"), 20) or _XP_FALSE_KEEP}


# =========================================================================== sections


def _latest_point(ledger: Any, mode: str) -> EquityPoint | None:
    """The newest equity snapshot when it belongs to ``mode`` (what ``build_state`` shows), else None."""
    point = ledger.latest_equity()
    return point if isinstance(point, EquityPoint) and point.mode == mode else None


def _money(settings: Settings, eq: dict[str, Any], point: EquityPoint | None,
           withdrawn: tuple[int, int] = (0, 0), desk: dict[str, Any] | None = None,
           trend: dict[str, Any] | None = None) -> dict[str, Any]:
    """``withdrawn``: live SOL (all time, today) sent back to the owner with WITHDRAW_TO - added back to the
    results, so taking money out never reads as a trading loss. ``desk``: :func:`polymarket_desk`, carried under
    ``polymarket`` apart from every SOL figure (never added to them); ``trend``: :func:`trend_desk`, likewise."""
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
        "label": _money_label(settings),
        "usd": eq["usd"], "start_usd": eq["start_usd"], "sol": sol, "sol_usd": sol_usd,
        "withdrawn_sol": out_total or None,
        "since_start": {"usd": since_usd, "pct": _pct(total, base_total)},
        "today": {"usd": _times(today, sol_usd), "pct": _pct(today, base_today)},
        "sol_price_effect_usd": eq["sol_price_effect_usd"],
        "curve": curve, "chart_ready": span >= CHART_MIN_SPAN_S,
        "as_of": point.ts if point is not None else (curve[-1][0] if curve else None),
        "polymarket": desk,
        "trend": trend,
    }


def _withdrawn(ledger: Any, settings: Settings, point: EquityPoint | None, now: float) -> tuple[int, int]:
    """Live SOL sent back to the owner that the latest equity point ``point`` already reflects ``(since the
    start, since today's first point)`` - a later withdrawal is not in that point yet (it would count twice)."""
    if not settings.is_live or point is None or not ledger.get_kv("withdraw.totals"):
        return 0, 0
    first = next((p for p in ledger.equity_series(since=now - now % 86_400) if p.mode == point.mode), None)
    return withdrawn_lamports(ledger, point.ts, first.ts if first is not None else None)


def _money_label(settings: Settings) -> str:
    """The money card's label: the page must always make clear when the money is pretend."""
    return REAL_LABEL if settings.is_live else PAPER_LABEL


def _dollars(value: float) -> str:
    return f"${abs(value):,.2f}"


def _signed(value: float) -> str:
    """``+$1.20`` / ``−$1,345.53`` / ``$0.00``, to the cent, as the page's script prints a signed dollar figure."""
    cents = round(value, 2)
    return ("+" if cents > 0 else _MINUS if cents < 0 else "") + _dollars(cents)


def _verb(value: float) -> str:
    return "lost" if value < 0 else "made"


def _run_started(ledger: Any, state: Mapping[str, Any]) -> float | None:
    """When the bot first ran on this volume: the ledger's first record (the first boot's receipt) or the engine's
    start (kv ``engine.started_at``: the current process only), whichever is earlier; None until either exists."""
    first = ledger.receipts(after_seq=0, limit=1)
    stamps = [_num(first[0].ts)] if first else []
    stamps.append(_num(_xp_map(state.get("engine")).get("started_at")))
    known = [ts for ts in stamps if ts is not None]
    return min(known) if known else None


# =========================================================================== the Polymarket desk


def polymarket_desk(settings: Settings, now: float) -> dict[str, Any] | None:
    """The Polymarket desk's books for the money card and the town (POLYMARKET in the module docstring), paper and
    real kept apart and never added together. None when the desk is off (``POLYDESK_ENABLED``) or its state cannot
    be read: nothing is shown rather than a made-up zero. Never raises."""
    if not settings.polydesk_enabled:
        return None
    try:
        desk = panel_state(settings, now)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:  # a malformed state file: never take the page down
        log.warning("polydesk_panel_failed error=%s", type(exc).__name__)
        return None
    raw_real, venue, balance = _xp_map(desk.get("real")), _xp_map(desk.get("exchange")), _xp_map(desk.get("balance"))
    real = _book(raw_real, REAL_LABEL)
    real.update({
        "at_risk_usd": _num(raw_real.get("at_risk_usd")) or 0.0,
        "contracts": _num(venue.get("contracts")), "cost_usd": _num(venue.get("cost_usd")),
        "value_usd": _num(venue.get("value_usd")), "venue_at": _num(venue.get("at")),
        "cash_usd": _num(balance.get("cash")), "cash_at": _num(balance.get("at")),
    })
    live = desk.get("mode") == "live"
    return {
        "mode": "live" if live else "paper", "label": REAL_LABEL if live else PAPER_LABEL,
        "as_of": _num(desk.get("last_ok")),
        "paper": _book(_xp_map(desk.get("paper")), PAPER_LABEL),
        # the venue's cash alone (a key, no contracts) is real money to show, but not a real book for the town
        "real": real if _real_book(real) or real["cash_usd"] is not None else None,
    }


def _book(raw: Mapping[str, Any], label: str) -> dict[str, Any]:
    """One of the desk's two tallies (the panel's ``paper`` or ``real``), type-checked. The desk keeps these as
    running counts from zero, so a missing one is zero."""
    today = _xp_map(raw.get("today"))
    return {"label": label, "open": _count(raw.get("open")) or 0,
            "today_usd": _num(today.get("pnl_usd")) or 0.0, "since_start_usd": _num(raw.get("pnl_total_usd")) or 0.0,
            "settled_today": _count(today.get("settled")) or 0, "won_today": _count(today.get("won")) or 0,
            "settled_total": _count(raw.get("settled_total")) or 0, "won_total": _count(raw.get("won_total")) or 0}


def _real_book(real: Mapping[str, Any]) -> bool:
    """Real money in play: an open real position, a real settlement, or a contract the venue's own book holds."""
    return bool(real["open"] or real["settled_total"] or (real.get("contracts") or 0) > 0)


def _desk_lines(desk: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``town.polymarket``: the desk's books (:func:`polymarket_desk`) in words, one line per kind of money, never
    added together; the real line only while the desk has a real book."""
    if desk is None:
        return None
    paper, real = desk["paper"], desk.get("real")
    line = (f"Polymarket desk (paper, pretend): today {_signed(paper['today_usd'])}, since start "
            f"{_signed(paper['since_start_usd'])}, {paper['open']} open")
    if desk.get("as_of") is None:
        line += "; no round finished yet"
    out: dict[str, Any] = {"paper": {"label": PAPER_LABEL, "open": paper["open"], "today_usd": paper["today_usd"],
                                     "since_start_usd": paper["since_start_usd"], "line": line}, "real": None}
    if real is not None and _real_book(real):
        out["real"] = {"label": REAL_LABEL, "open": real["open"], "contracts": real["contracts"],
                       "cost_usd": real["cost_usd"], "value_usd": real["value_usd"], "today_usd": real["today_usd"],
                       "settled_today": real["settled_today"], "won_today": real["won_today"],
                       "since_start_usd": real["since_start_usd"], "cash_usd": real["cash_usd"],
                       "line": _real_line(real)}
    return out


def _real_line(real: Mapping[str, Any]) -> str:
    """The real line, e.g. ``Polymarket desk (REAL money): 8 contracts at the venue, cost $7.80, worth $7.95 now;
    settled today 0/0 won $0.00; since start +$0.50; cash at the venue $16.27``. A part the venue has not answered
    says so instead of showing a zero."""
    contracts, cost, value, cash = real["contracts"], real["cost_usd"], real["value_usd"], real["cash_usd"]
    if contracts is not None:
        venue = f"{contracts:g} contract{'' if contracts == 1 else 's'} at the venue"
        venue += f", cost {_dollars(cost)}" if cost is not None else ""
        venue += f", worth {_dollars(value)} now" if value is not None else ""
    else:
        venue = f"{real['open']} open ({_dollars(real['at_risk_usd'])} at risk), the venue's book not read yet"
    held = f"cash at the venue {_dollars(cash)}" if cash is not None else "cash at the venue not read yet"
    return (f"Polymarket desk (REAL money): {venue}; settled today {real['won_today']}/{real['settled_today']} won "
            f"{_signed(real['today_usd'])}; since start {_signed(real['since_start_usd'])}; {held}")


def _with_desk(made: str, income_today: float | None, desk: Mapping[str, Any], *, live: bool) -> str:
    """The town's sentence with the Polymarket desk's paper result beside the SOL bot's: the two desks are named
    apart and never added. Both pretend and both known, in one breath: "the Solana desk lost $3.18 and the
    Polymarket desk lost $1,345.53 today (paper money, pretend)"."""
    joiner = "; " if income_today is None else " and "
    if desk.get("as_of") is None:
        return f"{made}{joiner}the Polymarket desk has not finished a round yet (paper money, pretend)"
    poly = desk["paper"]["today_usd"]
    if income_today is not None and not live:
        return (f"the Solana desk {_verb(income_today)} {_dollars(income_today)} and the Polymarket desk "
                f"{_verb(poly)} {_dollars(poly)} today (paper money, pretend)")
    return f"{made}{joiner}the Polymarket desk {_verb(poly)} {_dollars(poly)} today (paper money, pretend)"


def _real_sentence(real: Mapping[str, Any]) -> str:
    """The desk's real money in the town's line: its own sentence, never part of the paper figures."""
    since = f"since start {_signed(real['since_start_usd'])}."
    if not real["settled_today"]:
        return f" Polymarket real money: nothing settled today; {since}"
    return (f" Polymarket real money: {_verb(real['today_usd'])} {_dollars(real['today_usd'])} today "
            f"({real['won_today']}/{real['settled_today']} won); {since}")


# =========================================================================== the trend desk


def trend_desk(settings: Settings, now: float) -> dict[str, Any] | None:
    """The trend desk's paper book for the money card (TREND in the module docstring), type-checked: its own figures,
    never added to anything else. None when the desk is off (``TRENDDESK_ENABLED``) or its state cannot be read or
    holds junk: nothing is shown rather than a made-up number. Never raises."""
    if not settings.trenddesk_enabled:
        return None
    try:
        raw = trenddesk.panel_state(settings, now)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:  # a malformed state file: never take the page down
        log.warning("trenddesk_panel_failed error=%s", type(exc).__name__)
        return None
    figures = {key: _num(raw.get(key)) for key in ("sleeve_usd", "equity_usd", "today_usd", "since_start_usd")}
    figures["hold_since_start_usd"] = _num(raw.get("bh_since_start_usd"))  # holding the three, bought on day one
    if any(value is None for value in figures.values()):
        return None
    lab = {"since_start_usd": _num(raw.get("lab_since_start_usd")),
           "hold_since_start_usd": _num(raw.get("lab_hold_since_start_usd"))}
    in_market = _xp_map(raw.get("in_market"))
    started, problem, reset = raw.get("started"), raw.get("problem"), raw.get("reset_from")
    return {"mode": "paper", "label": PAPER_LABEL, "as_of": _num(raw.get("as_of")), **figures,
            "in_market": {coin: in_market.get(coin) is True for coin in trenddesk.COINS},
            "started": started if isinstance(started, str) else None,
            "problem": _clip(problem, TEXT_MAX) if isinstance(problem, str) and problem else None,
            "lab": lab if all(value is not None for value in lab.values()) else None,
            "reset_from": _clip(reset, 80) if isinstance(reset, str) and reset else None}


def _trend_line(trend: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """``town.trend``: the trend desk in one sentence, paper and pretend, its own figures only (never summed),
    against holding the three bought on day one and never touched; a record that replaced an unreadable one says
    so."""
    if trend is None:
        return None
    who = "Trend desk (paper, pretend)"
    if trend.get("reset_from"):
        who = f"Trend desk (paper, pretend; record restarted {trend.get('started') or 'today'})"
    if trend["as_of"] is None:
        first = (f"first booking at the close of {trend['started']} (UTC midnight)" if trend.get("started")
                 else "not started")
        line = f"{who}: {first}; nothing booked yet"
    else:
        line = (f"{who}: {trenddesk.in_out_text(trend['in_market'])}; since start "
                f"{_signed(trend['since_start_usd'])} vs holding the three (bought on day one, never touched) "
                f"{_signed(trend['hold_since_start_usd'])}")
    if trend.get("problem"):
        line += "; behind: the newest daily close is not booked yet"
    return {"line": line}


# =========================================================================== the town


def town_ledger(settings: Settings, money: Mapping[str, Any], judge: Mapping[str, Any] | None, now: float,
                started_at: float | None) -> dict[str, Any]:
    """The town's books (TOWN in the module docstring): what running the bot costs against what the desks made,
    today and since the start. ``money`` is the page's money card (its ``polymarket`` block, :func:`polymarket_desk`
    or absent, is the Polymarket desk: counted apart, in its own lines, never in the income figures), ``judge`` the
    ``judge`` block of ``/api/state`` (None, or missing or junk figures, count as nothing recorded), ``started_at``
    when the run began (None: not known). Never a made-up number: an unknown side is null and the line says so."""
    spend = _xp_map(judge)
    fixed_day = settings.town_railway_usd_month / TOWN_MONTH_DAYS
    uptime_s = max(0.0, now - started_at) if started_at is not None else None
    judge_total = max(0.0, _num(spend.get("cost_usd_total")) or 0.0)
    judge_today = _num(spend.get("cost_usd_today"))
    if judge_today is None:  # no figure for today: the total spread over the days run so far (at least one)
        judge_today = judge_total / max(1.0, (uptime_s or 0.0) / DAY_S)
    judge_today = max(0.0, judge_today)
    day_start = now - now % DAY_S
    since = max(day_start, started_at) if started_at is not None else day_start
    cost_per_day = fixed_day + judge_today
    cost_today = fixed_day * min(1.0, max(0.0, now - since) / DAY_S) + judge_today
    cost_since = fixed_day * uptime_s / DAY_S + judge_total if uptime_s is not None else None
    income_today = _num(_xp_map(money.get("today")).get("usd"))
    income_since = _num(_xp_map(money.get("since_start")).get("usd"))
    desk = money.get("polymarket")  # the Polymarket desk's books, or nothing: the desk is off
    trend = money.get("trend")  # the trend desk's paper book, or nothing
    if not (isinstance(trend, Mapping) and "as_of" in trend and isinstance(trend.get("in_market"), Mapping)):
        trend = None
    desk = desk if isinstance(desk, Mapping) and isinstance(desk.get("paper"), Mapping) else None
    kind = "real money" if settings.is_live else "paper money"
    who = "Solana desk" if desk is not None else "desks"
    if income_today is None:
        made = f"what the {who} made today ({kind}) is not known yet: no money check so far"
    else:
        made = f"the {who} {_verb(income_today)} {_dollars(income_today)} today ({kind})"
    if desk is not None:
        made = _with_desk(made, income_today, desk, live=settings.is_live)
    line = f"The town costs {_dollars(cost_per_day)} a day to run; {made}."
    real = desk.get("real") if desk is not None else None
    if real is not None and _real_book(real):
        line += _real_sentence(real)
    if cost_since is None:
        line += " How long the town has been running is not known yet."
    return {
        "label": _money_label(settings),
        "cost_per_day_usd": cost_per_day,
        "cost_today_usd": cost_today,
        "cost_since_start_usd": cost_since,
        "income_today_usd": income_today,
        "income_since_start_usd": income_since,
        "covered_today": income_today >= cost_today if income_today is not None else None,
        "covered_since_start": (income_since >= cost_since if income_since is not None and cost_since is not None
                                else None),
        "line": line,
        "polymarket": _desk_lines(desk),
        "trend": _trend_line(trend),  # its own line: never in the income figures or the line above
    }


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
        if isinstance(p.get("positions"), list):  # the Polymarket desk's open positions (paper or real), capped
            member["positions"] = [
                {"question": str(x.get("question") or "")[:80], "side": str(x.get("side") or ""),
                 "p_in": x.get("p_in"), "category": str(x.get("category") or ""), "live": bool(x.get("live"))}
                for x in p["positions"][:10] if isinstance(x, dict)
            ]
            member["label"] = str(p.get("label") or "")
            member["open_real"] = int(p.get("open_real") or 0)  # real-money positions open (whole book)
            member["open_paper"] = int(p.get("open_paper") or 0)  # paper ones, e.g. running off after a switch
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
    desk = polymarket_desk(settings, now)  # the Polymarket desk's books, apart from the SOL wallet (never summed)
    trend = trend_desk(settings, now)  # the trend desk's paper book, apart from everything else (never summed)
    money = _money(settings, state["equity"], point, _withdrawn(ledger, settings, point, now), desk, trend)
    receipts = state["receipts"]
    head = receipts["head_hash"]
    out = {
        "version": __version__,
        "generated_at": now,
        "mode": state["mode"],
        "refresh_s": REFRESH_S,
        "alerts": alerts + usage_alerts,
        "money": money,
        # the town: what running the bot costs against what the desks made (same clock as the judge's total)
        "town": town_ledger(settings, money, state.get("judge"), now, _run_started(ledger, state)),
        "team": {"counts": counts, "members": members},
        "trades": _trades(ledger, settings, state, text),
        "learning": {"source": card["source"], "state": card["state"], "headline": card["headline"],
                     "variants": card["variants"], "data": card["data"],
                     "rule": LEARNING_RULE if card["source"] == "card" and card["can_stop_trading"] else None},
        # read-only: the report cards never feed the checklist below or the banners
        "experience": experience_card(settings, now, card, memory),
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

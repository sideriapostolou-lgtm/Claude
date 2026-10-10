"""The Polymarket desk: a PAPER desk on Polymarket US that watches the venue all day and keeps a paper book under
one candidate rule, so the owner can watch the team work on prediction markets before any rule has earned real
money.

What it does, every ``polydesk_poll_s`` seconds, in its own thread (the trading loop is never blocked):

1. Watch list from the venue's PUBLIC gateway (``gateway.polymarket.us``, no key): every open non-sports market
   ending within :data:`HORIZON_H` hours (per category, the listing is sports-first otherwise) plus the
   match-winner markets of sports games in progress (events with a live period), capped at :data:`SPORTS_CAP`.
2. One best bid / offer per watched market (a small thread pool, well under the gateway's 20 req/s).
3. The candidate rule (lab 4's "near-certain grind", PLAN §2-3): once per market, the first time a side can be
   bought at or above ``polydesk_theta`` within the last ``polydesk_hours`` before the market's end, buy
   ``polydesk_ticket_usd`` of it on paper at the printed price (long at the ask, short at 1 - bid), pay the
   market's own taker fee ``feeCoefficient x shares x p x (1 - p)``, hold to settlement.
4. Settlement: a position whose market left the watch list (or ended) is settled at the venue's settlement price;
   the paper P&L is booked and the day's total updated.

**Live mode** (``POLYDESK_MODE=live`` + ``POLYDESK_LIVE_CONFIRM`` + the account's key in Railway variables, the
owner's explicit switch): the same rule, but a real limit order on Polymarket US for ``polydesk_live_contracts``
contracts of the YES side (long only: the venue prices every order on the YES side, so shorts stay paper-only),
immediate-or-cancel at the printed ask, through :mod:`nightcrawler.polymarket_us`. Caps, checked before every
order: money in open positions <= ``polydesk_live_max_open_usd``; the UTC day's realised loss <=
``polydesk_live_daily_loss_usd`` (then no more buys today); total realised loss <=
``polydesk_live_total_loss_usd`` (then the desk switches itself back to paper for good and says so; only the owner
can switch it live again). Live starts only after a successful balance read; a rejected key leaves the desk on
paper with the reason on the page. Every live order and settlement is receipted in the ledger's hash chain.

State lives in ``DATA_DIR/polydesk/state.json`` (atomic rewrite): open positions, the last closed positions,
daily P&L, counters, the last poll, the live status and the last balance. The team-room panel
(:func:`panel_state`) reads that file. The rule is a CANDIDATE: it earns a real seat only by passing lab 4's
TRAIN / VAL / TEST, and the page says "paper" or "real" everywhere this desk's numbers appear.

**The desk learns from its own record** (2026-10-09, after the paper rule lost 46 of 114 settlements in a day):

* Rule versions. Every position the rule opens (paper or real) is stamped ``rule`` = :func:`rule_id`:
  :data:`RULE_VERSION` (bumped whenever the rule's code changes; ``2026-10-09b`` is the :data:`MAX_SPREAD` guard)
  with the theta, hours and max spread it bought under (rows stamped before 2026-10-09 evening carry the bare
  version, an older rule), plus the book at entry: ``bid_in``, ``ask_in``, ``spread_in``. A position adopted from
  the venue's book is stamped ``rule: "venue"`` (not this rule's buy, no quote). Closed rows inherit the fields;
  rows from before the stamp have no ``rule`` and count as "before the fix". The panel's ``since_fix`` is the
  current rule's own record (open, settled, won, P&L; paper and real apart) and ``before_fix`` everything else
  (older rules too), so a new rule is never judged on an old rule's losses. The
  per-rule record is kept as it settles (``by_rule``), not re-read from the capped closed list.
* Lessons. From its last :data:`CLOSED_KEEP` settlements (at least :data:`LESSONS_MIN_ROWS`), the desk derives up
  to :data:`LESSONS_MAX` plain sentences (:func:`lessons`): by category, by the book's spread at entry (tight /
  wide / unknown book), by price band, by time to the end, and tight books per category. Every sentence carries
  the count and the result, paper and real stated apart. ``worst`` is the single biggest losing row. When a lesson
  is new (not a changed count: a new group, a flipped sign, a book that joined) the desk records one
  ``Lesson: ...`` event, so the office can say it; the sentences it last derived are kept in ``last_lessons``.
* The paper book is capped at :data:`PAPER_MAX_OPEN` open paper positions at once, so it can never balloon past
  what the owner can read; a market skipped for the cap is not marked tried and may be bought once a slot frees.

**The risk manager** (:mod:`nightcrawler.deskguard`, 2026-10-09, after the paper desk lost about $1,388 of pretend
money in a day and kept buying). A RULE is :func:`rule_id`: :data:`RULE_VERSION` plus every setting that changes
what the rule buys (theta, hours, :data:`MAX_SPREAD`), so changing ``POLYDESK_THETA`` or ``POLYDESK_HOURS`` starts a
new scorecard; positions are stamped with it (rows stamped before it carry the bare version: an older rule). Every
settlement is kept per rule and book (``by_rule[rule][book]``: ``pnls`` rounded to 1e-4, ``costs`` the money at
risk, ``keys`` the event it belongs to; the newest :data:`GUARD_KEEP` for the current rule, :data:`GUARD_KEEP_OLD`
for older ones). The P&L is judged per dollar at risk (a ticket change never mixes scales) and per EVENT: a game's
markets, or a ladder's markets ending together, settle on one outcome and count as one draw (lab 4's Amendment 3).
Every round, before buying and again after settling, the desk judges the CURRENT rule's own record, paper and real
apart (:meth:`PolyDesk._guard`):

* ``losing`` (95 % sure the rule loses money per event; from 10 events, 99 % sure as an early stop) PAUSES new
  buys: ``state["paused"] = {at, reason, rule}`` for the paper record (it stops paper buys and real ones: real
  money never follows a rule its own paper record shows losing), ``state["paused_real"]`` for the real record (it
  stops real buys). One event says it ("Risk manager paused the desk: <reason>"). Open positions still settle
  normally. A pause sticks for its rule; a changed rule starts a fresh record and lifts it; ``POLYDESK_GUARD=off``
  is the owner's switch (no pause at all, and no small book).
* Size follows evidence: until the paper record is ``winning`` the paper book holds at most
  :data:`PAPER_LEARNING_OPEN` open positions (then :data:`PAPER_MAX_OPEN`), so a new rule risks about
  ``POLYDESK_GUARD_MIN_N`` + 10 tickets before its first full verdict.
* ``winning`` (99 % sure, enough events and losses, the loss stress test) only records one event and the flag
  ``state["candidate"]``. While :data:`RULE_LAB_PASSED` is False (lab 4 found no edge for this rule) it is NOT
  called a candidate for real money: "the paper record clears the risk manager's bar (lab 4 has not passed this
  rule: no real money)". When the flag clears, one event and a receipt say so, and a later return is said again.
  The guard NEVER changes ``mode``, the live client, ``live_halted``, ``live_status`` or any setting: it can only
  ever stop buying.
* ``learning`` / ``unclear`` change nothing. The panel (:func:`panel_state`) carries ``guard``: each book's
  verdict, reason and pause (since when), and a plain line for the page.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from nightcrawler import deskguard
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.polymarket_us import PolymarketUSClient, PolymarketUSError

log = logging.getLogger("nightcrawler.polydesk")

GATEWAY = "https://gateway.polymarket.us/v1"
UA = {"User-Agent": "nightcrawler/polydesk (paper desk; public market data)"}
PAGE = 100
HORIZON_H = 48.0
SPORTS_CAP = 150
SPORTS_LOOKBACK_H = 12.0
CATEGORIES = (
    "climate",
    "weather",
    "crypto",
    "politics",
    "culture",
    "finance",
    "technology",
    "macro",
    "geopolitics",
    "science",
    "economics",
    "mentions",
    "tech",
)
WINNER_KINDS = ("MONEYLINE", "DRAWABLE_OUTCOME")
NOT_LIVE_PERIODS = {"NS", "", "CAN", "SUS", "PST", "FT", "AOT", "FINAL", "ENDED"}
THREADS = 8
REQ_SLEEP_S = 0.05
MAX_PRICE = 0.999
MAX_SPREAD = 0.03  # a quote counts as near-certain only when bid and ask agree (a wide book is not a belief)
US_TAKER = 0.0695
CLOSED_KEEP = 200
ADOPTED_END_GUESS_S = 3 * 3600.0  # a venue position on a market the watch list no longer carries: check settlement after this
EVENTS_KEEP = 40
REAL_CLOSED_SHOWN = 5  # the panel's newest real settlements (read from the kept closed rows: the 3D trophy shelf)
STATE_VERSION = 1
FIRST_POLL_DELAY_S = 20.0
RULE_VERSION = "2026-10-09b"  # bump when the rule changes; "b" = the MAX_SPREAD guard added 2026-10-09 18:07 UTC
RULE_VENUE = "venue"  # a position adopted from the venue's book: not this rule's buy
BEFORE_FIX = "before the fix"  # rows with no rule stamp (bought before RULE_VERSION existed)
PAPER_MAX_OPEN = 60  # open paper positions at once: the paper book stays readable
PAPER_LEARNING_OPEN = 10  # open paper positions at once until the rule's paper record is winning (size small)
LESSONS_MIN_ROWS = 10  # settled rows before the desk states a lesson
LESSONS_MAX = 5
GUARD_KEEP = 5000  # per-settlement P&Ls kept per rule and book for the risk manager (the newest)
GUARD_KEEP_OLD = 200  # ... for an older rule (never judged again; its settled/won/pnl_usd totals stay whole)
GUARD_LISTS = ("pnls", "costs", "keys")  # the risk manager's per-settlement lists, kept aligned
GUARD_BOOKS = (("paused", "paper", "the desk"), ("paused_real", "real", "real buys"))  # (state key, book, name)
#: The desk's own risk-manager events (the team room's risk member lists them).
GUARD_EVENTS = ("Risk manager", "Candidate for real money", "Paper record clears", "No longer")
#: True only once this rule passes lab 4's TEST. Until then a winning paper record is never called a candidate for
#: real money (lab 4 TRAIN found no edge for it; a paper flag on it is most likely luck).
RULE_LAB_PASSED = False
_DIGITS = re.compile(r"\d[\d,.]*")
_CUTS = ("spread", "category", "price", "time", "tight")
_CATEGORY_WORDS = {"sports": "sports", "crypto": "crypto"}


def _get(
    path: str,
    params: dict[str, Any] | None = None,
    tries: int = 3,
    timeout: float = 20.0,
) -> Any:
    last: str = "no response"
    for attempt in range(tries):
        try:
            r = requests.get(
                f"{GATEWAY}{path}", params=params, headers=UA, timeout=timeout
            )
            if r.status_code == 429:
                last = "HTTP 429"
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(1.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed: {last}")


def parse_iso(value: Any) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()  # Python 3.11+ accepts the trailing Z
    except ValueError:
        return None


def _num(v: Any) -> float | None:
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _market_rec(
    m: dict[str, Any], category: str, end_ts: float, **extra: Any
) -> dict[str, Any]:
    return {
        "slug": m["slug"],
        "question": str(m.get("question") or m.get("title") or m["slug"])[:120],
        "category": category,
        "end_ts": end_ts,
        "fee_coef": _num(m.get("feeCoefficient")),
        **extra,
    }


def open_markets(
    now: float, horizon_h: float = HORIZON_H, max_pages: int = 20
) -> list[dict[str, Any]]:
    """Open non-sports markets ending within ``horizon_h`` hours, listed per category."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat in CATEGORIES:
        for page in range(max_pages):
            reply = _get(
                "/markets",
                {
                    "limit": PAGE,
                    "offset": page * PAGE,
                    "closed": "false",
                    "categories": cat,
                },
            )
            ms = reply.get("markets") if isinstance(reply, dict) else None
            if not ms:
                break
            for m in ms:
                c = (m.get("category") or "").lower()
                if c == "sports" or m["slug"] in seen:
                    continue
                end_ts = parse_iso(m.get("endDate"))
                if (
                    end_ts is None
                    or end_ts < now - 3600
                    or end_ts > now + horizon_h * 3600
                ):
                    continue
                seen.add(m["slug"])
                out.append(_market_rec(m, c, end_ts))
            if len(ms) < PAGE:
                break
            time.sleep(REQ_SLEEP_S)
        time.sleep(REQ_SLEEP_S)
    return out


def live_sports_markets(now: float, cap: int = SPORTS_CAP) -> list[dict[str, Any]]:
    """Match-winner markets of games in progress (events started within SPORTS_LOOKBACK_H with a live period)."""
    start_min = datetime.fromtimestamp(now - SPORTS_LOOKBACK_H * 3600, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    start_max = datetime.fromtimestamp(now + 300, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[dict[str, Any]] = []
    for page in range(5):
        reply = _get(
            "/events",
            {
                "limit": PAGE,
                "offset": page * PAGE,
                "closed": "false",
                "categories": "sports",
                "startDateMin": start_min,
                "startDateMax": start_max,
            },
        )
        evs = reply.get("events") if isinstance(reply, dict) else None
        if not evs:
            break
        for ev in evs:
            started = parse_iso(ev.get("startTime") or ev.get("startDate"))
            period = str(ev.get("period") or "").upper()
            if started is None or started > now or period in NOT_LIVE_PERIODS:
                continue
            for m in ev.get("markets") or []:
                kind = str(
                    m.get("sportsMarketTypeV2") or m.get("marketType") or ""
                ).upper()
                if not any(w in kind for w in WINNER_KINDS) or m.get("closed"):
                    continue
                out.append(
                    _market_rec(
                        m,
                        "sports",
                        started + 6 * 3600,
                        game_start=started,
                        period=period,
                        event=str(ev.get("title") or ev.get("slug") or "")[:80],
                    )
                )
        if len(evs) < PAGE:
            break
        time.sleep(REQ_SLEEP_S)
    out.sort(key=lambda m: -m["game_start"])
    return out[:cap]


def bbo(slug: str) -> dict[str, float | None]:
    reply = _get(f"/markets/{slug}/bbo")
    md = reply.get("marketData", reply) if isinstance(reply, dict) else {}
    return {
        "best_bid": _num(md.get("bestBid")),
        "best_ask": _num(md.get("bestAsk")),
        "last": _num(md.get("lastTradePx")),
    }


def settlement(slug: str) -> float | None:
    reply = _get(f"/markets/{slug}/settlement")
    return _num(reply.get("settlement")) if isinstance(reply, dict) else None


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "positions": {},
        "closed": [],
        "days": {},
        "events": [],
        "counters": {
            "polls": 0,
            "quotes": 0,
            "errors": 0,
            "bought": 0,
            "settled": 0,
            "won": 0,
        },
        "last_poll": None,
        "last_ok": None,
        "watched": 0,
        "last_error": None,
        "rule": None,
        "mode": "paper",
        "live_status": None,
        "live_halted": False,
        "balance": None,
        "live_days": {},
        "live_pnl_total_usd": 0.0,
        "by_rule": {},
        "last_lessons": [],
        "paper_full": False,
        "guard": None,  # the risk manager's last verdicts (PolyDesk._guard)
        "paused": None,  # {at, reason, rule}: new buys stopped by the risk manager (the paper record is losing)
        "paused_real": None,  # {at, reason, rule}: new real buys stopped (the real record is losing)
        "candidate": None,  # {at, reason, rule}: the paper record is winning: a candidate for real money (owner decides)
        "candidate_said": None,  # the rule version whose candidacy was announced (said once per rule)
    }


def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and doc.get("version") == STATE_VERSION:
            base = empty_state()
            base.update(doc)
            if not base["by_rule"]:  # a file from before the per-rule record: rebuilt from the rows it kept
                base["by_rule"] = _by_rule_from_rows(base["closed"])
            else:
                _backfill_pnls(base["by_rule"], base["closed"])
            return base
    except (OSError, ValueError):
        pass
    return empty_state()


# ---------------------------------------------------------------------- the desk's own record
def _rule_of(row: dict[str, Any]) -> str:
    return str(row.get("rule") or BEFORE_FIX)


def _book_of(row: dict[str, Any]) -> str:
    return "real" if row.get("live") else "paper"


def rule_id(settings: Settings) -> str:
    """The rule a position is bought under: :data:`RULE_VERSION` plus every setting that changes what it buys
    (theta, hours, :data:`MAX_SPREAD`). A changed setting is a changed rule: a fresh scorecard, and its own pause.
    The ticket size is not part of it: the risk manager judges the return per dollar at risk."""
    return f"{RULE_VERSION}|t{float(settings.polydesk_theta):.3f}|h{float(settings.polydesk_hours):g}|s{MAX_SPREAD}"


def _cluster_of(row: dict[str, Any]) -> str:
    """The draw a settlement belongs to: a game's markets settle on one result (``event``, with its end time so two
    games of the same name stay apart), a ladder's markets (same category, same end time) on one price; each such
    group is one event for the risk manager. Short (a digest of the event's name): one is kept per settlement."""
    end = int(_num(row.get("end_ts")) or 0)
    event = row.get("event")
    if event:
        return f"e{zlib.crc32(str(event).encode()):08x}:{end}"
    return f"{row.get('category') or 'other'}:{end}"


def _stake_of(row: dict[str, Any]) -> float | None:
    """The money a settlement put at risk (``cost_usd``; else shares x price), or None when unknown."""
    cost = _num(row.get("cost_usd"))
    if cost is None:
        shares, price = _num(row.get("shares")), _num(row.get("p_in"))
        cost = shares * price if shares is not None and price is not None else None
    return round(cost, 4) if cost is not None and cost > 0 else None


def _tally(by_rule: dict[str, Any], row: dict[str, Any], pnl: float, won: bool) -> None:
    """One settlement into the per-rule record: ``by_rule[rule][paper|real] = {settled, won, pnl_usd, pnls, costs,
    keys}`` (the risk manager's input, oldest first, the newest :data:`GUARD_KEEP`, aligned: ``pnls`` the P&L to
    1e-4, ``costs`` the money at risk, ``keys`` the event it belongs to)."""
    rec = by_rule.setdefault(_rule_of(row), {}).setdefault(_book_of(row), {"settled": 0, "won": 0, "pnl_usd": 0.0})
    rec["settled"] += 1
    rec["won"] += int(won)
    rec["pnl_usd"] += pnl
    for name, value in zip(GUARD_LISTS, (round(pnl, 4), _stake_of(row), _cluster_of(row))):
        kept = rec.setdefault(name, [])
        kept.append(value)
        del kept[:-GUARD_KEEP]


def _settled_rows(closed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The closed rows that are settlements (an unresolved or replaced row has no P&L), oldest first."""
    return [r for r in reversed(closed) if r.get("won") is not None and _num(r.get("pnl_usd")) is not None]


def _by_rule_from_rows(closed: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in _settled_rows(closed):
        _tally(out, row, float(row["pnl_usd"]), bool(row["won"]))
    return out


def _aligned(rec: dict[str, Any]) -> bool:
    lists = [rec.get(name) for name in GUARD_LISTS]
    return all(isinstance(x, list) for x in lists) and len({len(x) for x in lists if isinstance(x, list)}) == 1


def _backfill_pnls(by_rule: dict[str, Any], closed: list[dict[str, Any]]) -> None:
    """A per-rule record without the risk manager's aligned lists (a file from before them, or one an older build
    wrote to) gets them from the closed rows the file kept (the newest :data:`CLOSED_KEEP`): the risk manager then
    judges those settlements, never made-up ones."""
    missing = {(rule, book) for rule, books in by_rule.items() if isinstance(books, dict)
               for book, rec in books.items() if isinstance(rec, dict) and not _aligned(rec)}
    if not missing:
        return
    for rule, book in missing:
        by_rule[rule][book].update({name: [] for name in GUARD_LISTS})
    for row in _settled_rows(closed):
        if (_rule_of(row), _book_of(row)) in missing:
            rec = by_rule[_rule_of(row)][_book_of(row)]
            for name, value in zip(GUARD_LISTS, (round(float(row["pnl_usd"]), 4), _stake_of(row), _cluster_of(row))):
                rec[name].append(value)


def _trim_old(by_rule: Any, current: str) -> None:
    """An older rule's lists keep only their newest :data:`GUARD_KEEP_OLD` (it is never judged again; its
    ``settled`` / ``won`` / ``pnl_usd`` totals stay whole): the state file stays small."""
    if not isinstance(by_rule, dict):
        return
    for rule, books in by_rule.items():
        if rule == current or not isinstance(books, dict):
            continue
        for rec in books.values():
            for name in GUARD_LISTS:
                kept = rec.get(name) if isinstance(rec, dict) else None
                if isinstance(kept, list):
                    del kept[:-GUARD_KEEP_OLD]


def _fit(values: Any, n: int, filler: Any) -> list[Any]:
    """``values`` lined up with the newest ``n`` P&Ls (both lists are trimmed from the front)."""
    kept = list(values) if isinstance(values, list) else []
    return kept[-n:] if len(kept) >= n else [filler(i) for i in range(n - len(kept))] + kept


def judge_book(settings: Settings, by_rule: Any, book: str) -> deskguard.Verdict:
    """The risk manager's verdict on one book (``paper`` / ``real``) of the CURRENT rule's own record
    (:func:`rule_id`): each event one draw, judged per dollar at risk."""
    rec = by_rule.get(rule_id(settings)) if isinstance(by_rule, dict) else None
    rec = rec.get(book) if isinstance(rec, dict) else None
    pnls = rec.get("pnls") if isinstance(rec, dict) else None
    pnls = pnls if isinstance(pnls, list) else []
    rec = rec if isinstance(rec, dict) else {}
    return deskguard.judge(pnls, groups=_fit(rec.get("keys"), len(pnls), lambda i: None),
                           stakes=_fit(rec.get("costs"), len(pnls), lambda i: None),
                           min_n=int(settings.polydesk_guard_min_n), win_n=int(settings.polydesk_guard_win_n))


def _current(record: Any, rule: str) -> dict[str, Any] | None:
    """A pause (or flag) record that belongs to the current rule (:func:`rule_id`), else None (an older rule's
    is stale: a changed rule starts a fresh record)."""
    return record if isinstance(record, dict) and record.get("rule") == rule else None


def _money(value: float) -> str:
    sign = "-" if value < 0 else "+"
    size = abs(value)
    return f"{sign}${size:,.0f}" if size >= 100 else f"{sign}${size:.2f}"


def _cuts(row: dict[str, Any]) -> list[tuple[str, str]]:
    """``(cut, group)`` for one settled row: its category, the book's spread at entry, the price band, the time
    to the end at entry, and (tight books only) the category again."""
    cat = str(row.get("category") or "other")
    word = _CATEGORY_WORDS.get(cat, "other markets")
    out = [("category", word.capitalize() if cat in _CATEGORY_WORDS else "Other markets (not sports or crypto)")]
    spread = _num(row.get("spread_in"))
    if spread is None:
        out.append(("spread", "Unknown book (no quote saved at entry)"))
    elif spread <= MAX_SPREAD + 1e-9:
        out.append(("spread", f"Tight books (spread {MAX_SPREAD:.2f} or less)"))
        out.append(("tight", f"Tight books in {word}"))
    else:
        out.append(("spread", f"Wide books (spread over {MAX_SPREAD:.2f})"))
    p = float(row.get("p_in") or 0.0)
    if p >= 0.99:
        band = "Bought at 0.99 or above"
    elif p >= 0.97:
        band = "Bought at 0.97-0.99"
    elif p >= 0.95:
        band = "Bought at 0.95-0.97"
    else:
        band = "Bought under 0.95"
    out.append(("price", band))
    if cat == "sports":
        when = "Sports in play"
    elif row.get("end_known") is False:
        when = "End time unknown at entry"
    else:
        left = float(row.get("end_ts") or 0.0) - float(row.get("t_in") or 0.0)
        when = "Bought in the last hour before the end" if left <= 3600.0 else "Bought more than an hour before the end"
    out.append(("time", when))
    return out


def _sentence(label: str, rows: list[dict[str, Any]]) -> tuple[str, float]:
    """``(sentence, weight)``: the group's count and result per book, paper and real stated apart, never added;
    the weight (the larger of the two books' absolute results) ranks the lessons."""
    parts = []
    weight = 0.0
    for book in ("paper", "real"):
        rs = [r for r in rows if _book_of(r) == book]
        if not rs:
            continue
        pnl = sum(float(r["pnl_usd"]) for r in rs)
        parts.append(f"{sum(1 for r in rs if r.get('won'))} of {len(rs)} won, {_money(pnl)} ({book})")
        weight = max(weight, abs(pnl))
    text = f"{label}: " + "; ".join(parts)
    if label.startswith("Wide books"):
        text += " — never again (now blocked)"
    return text + ".", weight


def lessons(closed: list[dict[str, Any]]) -> list[str]:
    """Up to :data:`LESSONS_MAX` plain sentences from the settled rows (at least :data:`LESSONS_MIN_ROWS`, else
    none): the most telling group of each cut (by the larger absolute result in either book), biggest first."""
    rows = [r for r in closed if r.get("won") is not None and _num(r.get("pnl_usd")) is not None]
    if len(rows) < LESSONS_MIN_ROWS:
        return []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        for key in _cuts(r):
            groups.setdefault(key, []).append(r)
    scored = {key: _sentence(key[1], rs) for key, rs in groups.items()}
    picked: list[tuple[str, str]] = []
    for cut in _CUTS:
        best = max((k for k in scored if k[0] == cut), key=lambda k: scored[k][1], default=None)
        if best is not None:
            picked.append(best)
    rest = sorted((k for k in scored if k not in picked), key=lambda k: -scored[k][1])
    picked += rest[: max(0, LESSONS_MAX - len(picked))]
    picked.sort(key=lambda k: -scored[k][1])
    return [scored[k][0] for k in picked[:LESSONS_MAX]]


def lesson_key(text: str) -> str:
    """A lesson with its numbers blanked: a changed count is the same lesson; a new group, a flipped sign or a
    book that joined is a new one."""
    return _DIGITS.sub("#", text)


def worst_row(closed: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The single biggest losing settled row, labelled paper or real as the row is; None without a loss."""
    rows = [r for r in closed if r.get("won") is not None and _num(r.get("pnl_usd")) is not None and r["pnl_usd"] < 0]
    if not rows:
        return None
    r = min(rows, key=lambda r: float(r["pnl_usd"]))
    return {
        "question": str(r.get("question") or r.get("slug") or "")[:120],
        "p_in": _num(r.get("p_in")),
        "category": str(r.get("category") or "other"),
        "pnl_usd": float(r["pnl_usd"]),
        "book": _book_of(r),
        "rule": _rule_of(r),
        "settled_at": _num(r.get("settled_at")),
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":"), sort_keys=True))
    os.replace(tmp, path)


def state_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / "polydesk" / "state.json"


def _reveal(value: Any) -> str:
    """A secret setting's text (``Secret.reveal()``), or the plain string; never logged."""
    return str(value.reveal()) if hasattr(value, "reveal") else str(value or "")


class PolyDesk:
    """The paper desk's runtime (one daemon thread). ``poll(now)`` is also callable directly (tests)."""

    def __init__(
        self,
        settings: Settings,
        path: Path | None = None,
        ledger: Any = None,
        client_factory: Any = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.path = path or state_path(settings)
        self.theta = float(settings.polydesk_theta)
        self.hours = float(settings.polydesk_hours)
        self.ticket = float(settings.polydesk_ticket_usd)
        self.poll_s = float(settings.polydesk_poll_s)
        self.contracts = float(settings.polydesk_live_contracts)
        self.client: PolymarketUSClient | None = None  # places orders: live mode only
        self.reader: PolymarketUSClient | None = None  # reads balances and positions whenever the key is set
        self._key_status: str | None = None
        self._client_factory = client_factory or PolymarketUSClient
        self.live_requested = (
            settings.polydesk_mode == "live"
            and settings.polydesk_live_confirm == LIVE_CONFIRM_PHRASE
            and bool(settings.polymarket_us_key_id)
            and bool(settings.polymarket_us_secret_key)
        )
        self.state = load_state(self.path)
        self.state["rule"] = {
            "theta": self.theta,
            "hours": self.hours,
            "ticket_usd": self.ticket,
            "version": RULE_VERSION,
            "id": self.rule,
            "label": f"candidate rule: buy at >= {self.theta:.2f} within the last {self.hours:g} h when bid and ask "
            f"are within {MAX_SPREAD:.2f}, ${self.ticket:.0f} paper tickets. Lab 4 TRAIN (2026-10-09): NO EDGE in any "
            "cell after fees, so this rule never gets real money",
        }
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state["mode"] = "paper"
        if bool(settings.polymarket_us_key_id) and bool(settings.polymarket_us_secret_key):
            self.reader = self._open_reader()
        if self.live_requested and self.state.get("live_halted"):
            self.state["live_status"] = (
                "Live was switched off by the total-loss cap; the desk stays on paper until the owner resets it."
            )
        elif self.live_requested:
            self._connect()
        elif settings.polydesk_mode == "live":
            self.state["live_status"] = (
                "Live requested but the confirm phrase or the key is missing: staying on paper."
            )
        else:
            self.state["live_status"] = None
        self._save()

    @property
    def rule(self) -> str:
        """The rule this desk buys under now (:func:`rule_id`)."""
        return rule_id(self.settings)

    def _open_reader(self) -> PolymarketUSClient | None:
        """A read link to the venue (balances, positions) once the key is accepted, in paper mode too: the
        venue's book is the truth about real money. A rejected key leaves the reason for the panel."""
        try:
            client = self._client_factory(
                _reveal(self.settings.polymarket_us_key_id), _reveal(self.settings.polymarket_us_secret_key)
            )
            bal = client.balances()
        except (PolymarketUSError, ValueError) as exc:
            status = exc.status if isinstance(exc, PolymarketUSError) else "bad key format"
            self._key_status = (
                f"Polymarket rejected the API key ({status}): make a new key in the app and put it in "
                "Railway; staying on paper."
            )
            log.warning("polydesk_key_rejected status=%s", status)
            return None
        self.state["balance"] = {**bal, "at": time.time()}
        return client

    def _connect(self) -> None:
        """Live only after the venue accepts the key (a balance read); otherwise paper, with the reason."""
        if self.reader is None:
            self.client = None
            self.state["mode"] = "paper"
            self.state["live_status"] = self._key_status
            return
        bal = self.state["balance"]
        self.client = self.reader
        self.state["mode"] = "live"
        self.state["live_status"] = None
        log.info(
            "polydesk_live_connected cash=%.2f buying_power=%.2f",
            bal["cash"],
            bal["buying_power"],
        )
        self._receipt(
            "polydesk_live_connected",
            {"cash": bal["cash"], "buying_power": bal["buying_power"]},
        )

    def _receipt(self, kind: str, payload: dict[str, Any]) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.append_receipt(kind, payload)
        except Exception as exc:  # noqa: BLE001 (a receipt failure must not stop the desk)
            log.warning("polydesk_receipt_failed kind=%s error=%s", kind, type(exc).__name__)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="polydesk", daemon=True)
        self._thread.start()
        log.info(
            "polydesk_started theta=%.2f hours=%g ticket_usd=%.0f poll_s=%g (%s)",
            self.theta,
            self.hours,
            self.ticket,
            self.poll_s,
            "LIVE: %g contract(s) per order" % self.contracts if self.state.get("mode") == "live" else "paper",
        )

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(
            FIRST_POLL_DELAY_S
        )  # a bot built and closed within seconds (tests) never touches the network
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.poll(t0)
            except Exception as exc:  # noqa: BLE001 (a desk keeps going; the trading loop is unaffected)
                self.state["counters"]["errors"] += 1
                self.state["last_error"] = f"{type(exc).__name__}"
                self._save()
                log.warning("polydesk_poll_failed error=%s", type(exc).__name__)
            self._stop.wait(max(5.0, self.poll_s - (time.time() - t0)))

    def _save(self) -> None:
        _trim_old(self.state.get("by_rule"), self.rule)
        save_state(self.path, self.state)

    def _event(self, ts: float, text: str, tone: str = "neutral") -> None:
        self.state["events"].insert(0, {"ts": ts, "text": text[:160], "tone": tone})
        del self.state["events"][EVENTS_KEEP:]

    # ------------------------------------------------------------------ one round
    def poll(self, now: float) -> dict[str, int]:
        st = self.state
        st["counters"]["polls"] += 1
        st["last_poll"] = now
        watch = open_markets(now)
        try:
            watch += live_sports_markets(now)
        except RuntimeError:
            st["counters"]["errors"] += 1
        quotes = self._quotes(watch)
        st["counters"]["quotes"] += len(quotes)
        adopted = self._reconcile(now, watch) if self.reader is not None else 0
        self._guard(now)  # the record so far decides whether this round may buy
        bought = self._apply_rule(now, watch, quotes)
        settled = self._settle(now, {m["slug"] for m in watch})
        if settled:
            self._guard(now)  # this round's settlements count at once (the panel, the next round)
        if bought and st["mode"] == "live" and self.reader is not None:
            adopted += self._reconcile(now, watch)  # the venue summary after this round's real buys
        self._learn(now)
        st["watched"] = len(watch)
        st["last_ok"] = now
        st["last_error"] = None
        if self.reader is not None:
            try:
                st["balance"] = {**self.reader.balances(), "at": now}
            except PolymarketUSError as exc:
                st["counters"]["errors"] += 1
                log.warning("polydesk_balance_failed status=%s", exc.status)
        self._save()
        return {
            "watched": len(watch),
            "quotes": len(quotes),
            "bought": bought,
            "settled": settled,
            "adopted": adopted,
        }

    def _reconcile(self, now: float, watch: list[dict[str, Any]]) -> int:
        """The venue's book is the truth for real money. Every contract it holds that this desk never recorded
        (an order reply that showed no fill, a buy from another place) is adopted as a live position, so it is
        counted against the caps, settled and shown. The venue summary is kept for the panel."""
        assert self.reader is not None
        st = self.state
        try:
            rows = self.reader.positions()
        except PolymarketUSError as exc:
            st["counters"]["errors"] += 1
            log.warning("polydesk_positions_failed status=%s", exc.status)
            return 0
        held = [r for r in rows if r["qty"] > 0 and not r["expired"] and r["slug"]]
        st["exchange"] = {
            "positions": len(held),
            "contracts": sum(r["qty"] for r in held),
            "cost_usd": sum(r["cost"] if r["cost"] > 0 else r["qty"] * r["avg_price"] for r in held),
            "value_usd": sum(r["value"] for r in held),
            "at": now,
        }
        by_slug = {m["slug"]: m for m in watch}
        adopted = 0
        for r in held:
            slug = r["slug"]
            pos = st["positions"].get(slug)
            if pos is not None and pos.get("live"):
                continue
            if pos is not None:  # a paper position on the same market: the real one takes the slot, no paper P&L
                st["closed"].insert(0, {**pos, "settled_at": now, "won": None, "unresolved": True, "replaced_by_real": True})
                del st["closed"][CLOSED_KEEP:]
            m = by_slug.get(slug)
            price = r["avg_price"] if r["avg_price"] > 0 else (r["cost"] / r["qty"] if r["cost"] > 0 else 0.0)
            cost = r["cost"] if r["cost"] > 0 else price * r["qty"]
            coef = m["fee_coef"] if m is not None and m.get("fee_coef") is not None else US_TAKER
            label = f"{r['title']} · {r['outcome']}" if r["outcome"] else r["title"]
            question = m["question"] if m is not None else (label or slug)
            st["positions"][slug] = {
                "slug": slug,
                "question": question,
                "category": m["category"] if m is not None else ("sports" if r["event_slug"] else "other"),
                "side": "long",
                "p_in": price,
                "shares": r["qty"],
                "fee_usd": r["qty"] * coef * price * (1.0 - price),
                "cost_usd": cost,
                "t_in": now,
                "end_ts": m["end_ts"] if m is not None else now + ADOPTED_END_GUESS_S,
                "event": m.get("event") if m is not None else None,
                "live": True,
                "adopted": True,
                "end_known": m is not None,
                "rule": RULE_VENUE,
            }
            st["counters"]["bought"] += 1
            adopted += 1
            self._event(
                now,
                f"REAL position found at the venue: {question[:60]} · {r['qty']:g} contract at {price:.3f} "
                f"(${cost:.2f})",
                "good",
            )
            self._receipt(
                "polydesk_position_adopted",
                {"slug": slug, "contracts": r["qty"], "price": price, "cost_usd": cost},
            )
        if adopted:
            log.info("polydesk_adopted n=%d venue_contracts=%g", adopted, st["exchange"]["contracts"])
        return adopted

    def _fill_from_positions(self, slug: str, fill: dict[str, Any]) -> dict[str, Any]:
        """An order reply without executions is not the last word: the venue's book decides whether it filled."""
        assert self.client is not None
        try:
            rows = self.client.positions()
        except PolymarketUSError as exc:
            self.state["counters"]["errors"] += 1
            log.warning("polydesk_positions_failed status=%s", exc.status)
            return fill
        for r in rows:
            if r["slug"] == slug and r["qty"] > 0:
                price = r["avg_price"] if r["avg_price"] > 0 else (r["cost"] / r["qty"] if r["cost"] > 0 else 0.0)
                if price <= 0:
                    return fill
                return {**fill, "filled": r["qty"], "avg_price": price,
                        "cost": r["cost"] if r["cost"] > 0 else price * r["qty"], "via": "positions"}
        return fill

    def _quotes(
        self, watch: list[dict[str, Any]]
    ) -> dict[str, dict[str, float | None]]:
        def one(m: dict[str, Any]) -> tuple[str, dict[str, float | None]] | None:
            try:
                q = bbo(m["slug"])
            except RuntimeError:
                return None
            time.sleep(REQ_SLEEP_S)
            return m["slug"], q

        with ThreadPoolExecutor(max_workers=THREADS) as pool:
            return {
                slug: q
                for r in pool.map(one, watch)
                if r is not None
                for slug, q in [r]
            }

    def _apply_rule(
        self,
        now: float,
        watch: list[dict[str, Any]],
        quotes: dict[str, dict[str, float | None]],
    ) -> int:
        st = self.state
        bought = 0
        tried: set[str] = set(st.setdefault("tried", []))
        paper_open = sum(1 for p in st["positions"].values() if not p.get("live"))
        cap = self._paper_cap()
        st["paper_full"] = bool(st.get("paper_full")) and paper_open >= cap
        # The risk manager's pauses (self._guard): a losing paper record stops paper AND real buys (real money never
        # follows a rule its own paper record shows losing); a losing real record stops real buys. Paused markets
        # are not marked tried: they may be bought once the pause lifts (a changed rule, the owner's switch).
        paper_paused = self._paused("paused")
        real_paused = paper_paused or self._paused("paused_real")
        for m in watch:
            slug = m["slug"]
            if slug in st["positions"] or slug in tried:
                continue
            if m["category"] != "sports" and now < m["end_ts"] - self.hours * 3600.0:
                continue  # not yet inside the window (sports: the live list IS the window)
            q = quotes.get(slug)
            if not q:
                continue
            ask, bid = q.get("best_ask"), q.get("best_bid")
            # Both sides of the book must say "near-certain". A thin book quoting bid 0.14 / ask 0.69 has an ask
            # that can sit above theta while the market believes nothing of the kind; the paper desk bought such
            # quotes on 2026-10-09 and lost 60% of them. The lab's rule reads trade prints, which have no such gap.
            if ask is None or bid is None or ask - bid > MAX_SPREAD + 1e-9:
                continue
            side: str | None = None
            price = 0.0
            if ask is not None and ask >= self.theta:
                side, price = "long", float(ask)
            elif bid is not None and (1.0 - bid) >= self.theta:
                side, price = "short", float(1.0 - bid)
            if side is None:
                continue
            price = min(price, MAX_PRICE)
            coef = m["fee_coef"] if m.get("fee_coef") is not None else US_TAKER
            stamp = {"rule": self.rule, "bid_in": float(bid), "ask_in": float(ask), "spread_in": float(ask) - float(bid)}
            if st["mode"] == "live" and self.client is not None:
                if side != "long":
                    continue  # live: the YES side only (the venue prices every order on YES); shorts stay paper-only
                if real_paused:
                    continue  # the risk manager stopped real buys (never starts any)
                if not self._live_allows(now, price):
                    continue
                tried.add(slug)
                try:
                    fill = self.client.buy_long_ioc(slug, price, self.contracts)
                except PolymarketUSError as exc:
                    st["counters"]["errors"] += 1
                    self._event(now, f"Order rejected by the venue ({exc.status}): {m['question'][:50]}", "bad")
                    self._receipt("polydesk_order_rejected", {"slug": slug, "status": exc.status})
                    continue
                if fill["filled"] <= 0:
                    fill = self._fill_from_positions(slug, fill)
                if fill["filled"] <= 0:
                    self._event(now, f"No fill at {price:.3f}: {m['question'][:50]} (order cancelled)")
                    continue
                shares = float(fill["filled"])
                p_fill = float(fill["avg_price"])
                cost = float(fill["cost"])
                fee = shares * coef * p_fill * (1.0 - p_fill)
                st["positions"][slug] = {
                    "slug": slug,
                    "question": m["question"],
                    "category": m["category"],
                    "side": "long",
                    "p_in": p_fill,
                    "shares": shares,
                    "fee_usd": fee,
                    "cost_usd": cost,
                    "t_in": now,
                    "end_ts": m["end_ts"],
                    "event": m.get("event"),
                    "live": True,
                    "order_id": fill.get("id"),
                    **stamp,
                }
                st["counters"]["bought"] += 1
                bought += 1
                self._event(
                    now,
                    f"REAL buy: {m['question'][:60]} · {shares:g} contract at {p_fill:.3f} (${cost:.2f}, "
                    f"{m['category']})",
                    "good",
                )
                self._receipt(
                    "polydesk_order_filled",
                    {"slug": slug, "order_id": fill.get("id"), "contracts": shares, "price": p_fill, "cost_usd": cost},
                )
                continue
            if paper_paused:
                continue  # the risk manager paused paper buys; open positions still settle
            if paper_open >= cap:  # not marked tried: the market may be bought once a slot frees
                if not st["paper_full"]:
                    st["paper_full"] = True
                    why = "" if cap >= PAPER_MAX_OPEN else ", the most until the rule's paper record is winning"
                    self._event(now, f"Paper book full ({cap} open{why}): no new paper buys until some settle.")
                continue
            shares = self.ticket / price
            fee = shares * coef * price * (1.0 - price)
            st["positions"][slug] = {
                "slug": slug,
                "question": m["question"],
                "category": m["category"],
                "side": side,
                "p_in": price,
                "shares": shares,
                "fee_usd": fee,
                "cost_usd": self.ticket,
                "t_in": now,
                "end_ts": m["end_ts"],
                "event": m.get("event"),
                "live": False,
                **stamp,
            }
            tried.add(slug)
            paper_open += 1
            st["counters"]["bought"] += 1
            bought += 1
            self._event(
                now,
                f"Paper buy: {m['question'][:60]} · {side} at {price:.3f} · ${self.ticket:.0f} "
                f"({m['category']})",
            )
        st["tried"] = sorted(tried)[-5000:]
        return bought

    # ------------------------------------------------------------------ live caps
    def _live_allows(self, now: float, price: float) -> bool:
        st = self.state
        s = self.settings
        open_usd = sum(float(p.get("cost_usd") or 0.0) for p in st["positions"].values() if p.get("live"))
        if open_usd + price * self.contracts > float(s.polydesk_live_max_open_usd):
            return False
        day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
        day_pnl = float((st.get("live_days") or {}).get(day, {}).get("pnl_usd") or 0.0)
        if day_pnl <= -float(s.polydesk_live_daily_loss_usd):
            note = "Daily loss cap reached: no more real buys today."
            if st.get("live_status") != note:
                st["live_status"] = note
                self._event(now, note, "bad")
            return False
        return True

    def _check_total_loss(self, now: float) -> None:
        st = self.state
        total = float(st.get("live_pnl_total_usd") or 0.0)
        if total <= -float(self.settings.polydesk_live_total_loss_usd) and st["mode"] == "live":
            st["mode"] = "paper"
            st["live_halted"] = True
            st["live_status"] = (
                f"Total loss cap reached ({total:+.2f} $): the desk switched itself back to paper for good; "
                "only the owner can switch it live again."
            )
            self.client = None
            self._event(now, "Total loss cap reached: real trading stopped, back to paper.", "bad")
            self._receipt("polydesk_live_halted", {"live_pnl_total_usd": total})
            log.warning("polydesk_live_halted total=%.2f", total)

    def _settle(self, now: float, watched: set[str]) -> int:
        st = self.state
        settled = 0
        for slug, pos in list(st["positions"].items()):
            if slug in watched and now < pos["end_ts"]:
                continue
            if pos["category"] != "sports" and now < pos["end_ts"]:
                continue
            try:
                value = settlement(slug)
            except RuntimeError:
                continue
            if value is None:
                if (
                    now > pos["end_ts"] + 7 * 86400
                ):  # never settled in a week: drop it as unresolved (no P&L)
                    pos["pnl_usd"] = None
                    st["closed"].insert(
                        0, {**pos, "settled_at": now, "won": None, "unresolved": True}
                    )
                    del st["positions"][slug]
                continue
            payout = pos["shares"] * (value if pos["side"] == "long" else 1.0 - value)
            pnl = payout - pos["fee_usd"] - float(pos.get("cost_usd", self.ticket))
            won = pnl > 0
            day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
            d = st["days"].setdefault(day, {"pnl_usd": 0.0, "settled": 0, "won": 0})
            d["pnl_usd"] += pnl
            d["settled"] += 1
            d["won"] += int(won)
            _tally(st.setdefault("by_rule", {}), pos, pnl, won)
            st["closed"].insert(
                0,
                {**pos, "settled_at": now, "value": value, "pnl_usd": pnl, "won": won},
            )
            del st["closed"][CLOSED_KEEP:]
            del st["positions"][slug]
            st["counters"]["settled"] += 1
            st["counters"]["won"] += int(won)
            settled += 1
            word = "real" if pos.get("live") else "paper"
            self._event(
                now,
                f"Settled: {pos['question'][:60]} · {'won' if won else 'lost'} {pnl:+.2f} $ ({word})",
                "good" if won else "bad",
            )
            if pos.get("live"):
                d_live = st.setdefault("live_days", {}).setdefault(day, {"pnl_usd": 0.0, "settled": 0, "won": 0})
                d_live["pnl_usd"] += pnl
                d_live["settled"] = int(d_live.get("settled") or 0) + 1
                d_live["won"] = int(d_live.get("won") or 0) + int(won)
                st["live_pnl_total_usd"] = float(st.get("live_pnl_total_usd") or 0.0) + pnl
                self._receipt(
                    "polydesk_settled",
                    {"slug": slug, "value": value, "pnl_usd": pnl, "contracts": pos["shares"]},
                )
                self._check_total_loss(now)
            time.sleep(REQ_SLEEP_S)
        return settled

    def _learn(self, now: float) -> None:
        """The desk reads its own settled rows after every round. A NEW lesson (a group, a sign or a book not in
        the last derived set; a changed count is not news) is said once as a ``Lesson: ...`` event."""
        st = self.state
        new = lessons(st["closed"])
        old = st.get("last_lessons") or []
        known = {lesson_key(t) for t in old}
        fresh = [t for t in new if lesson_key(t) not in known]
        if fresh:
            self._event(now, f"Lesson: {fresh[0]}", "bad" if "-$" in fresh[0] else "good")
        if new != old:
            st["last_lessons"] = new

    # ------------------------------------------------------------------ the risk manager
    def _paused(self, key: str) -> bool:
        """``state[key]`` (``paused`` / ``paused_real``) stops buying now: the guard is on and the pause is the
        current rule's."""
        return bool(self.settings.polydesk_guard) and _current(self.state.get(key), self.rule) is not None

    def _paper_cap(self) -> int:
        """Open paper positions allowed now (size follows evidence): :data:`PAPER_MAX_OPEN` once the current rule's
        paper record is winning or the owner switched the guard off, else :data:`PAPER_LEARNING_OPEN` (never more
        than :data:`PAPER_MAX_OPEN`)."""
        g = self.state.get("guard")
        paper = g.get("paper") if isinstance(g, dict) and g.get("rule") == self.rule else None
        proven = isinstance(paper, dict) and paper.get("verdict") == deskguard.WINNING
        if proven or not self.settings.polydesk_guard:
            return PAPER_MAX_OPEN
        return min(PAPER_MAX_OPEN, PAPER_LEARNING_OPEN)

    def _guard(self, now: float) -> None:
        """The risk manager (module docstring, :mod:`nightcrawler.deskguard`) on the current rule's own record, paper
        and real apart. It writes only ``guard``, ``paused``, ``paused_real``, ``candidate`` and ``candidate_said``,
        events and receipts: never ``mode``, the client, ``live_halted``, ``live_status`` or a setting. A pause only
        ever stops buying; a winning record is a flag for the owner."""
        st = self.state
        on = bool(self.settings.polydesk_guard)
        rule = self.rule
        by_rule = st.get("by_rule") or {}
        verdicts = {book: judge_book(self.settings, by_rule, book) for _, book, _ in GUARD_BOOKS}
        st["guard"] = {"on": on, "rule": rule, "at": now, **{book: v.to_dict() for book, v in verdicts.items()}}
        for key, book, what in GUARD_BOOKS:
            st[key], text = deskguard.pause_step(st.get(key), verdicts[book], rule=rule, now=now, on=on, what=what)
            if text:
                paused = st[key] is not None
                self._event(now, text, "bad" if paused else "neutral")
                self._receipt("polydesk_guard", {"book": book, "paused": paused, "rule": rule,
                                                 "verdict": verdicts[book].verdict, "n": verdicts[book].n,
                                                 "total_usd": verdicts[book].total})
                log.warning("polydesk_guard book=%s paused=%s n=%d verdict=%s", book, paused, verdicts[book].n,
                            verdicts[book].verdict)
        self._flag(now, on, verdicts["paper"])

    def _flag(self, now: float, on: bool, paper: deskguard.Verdict) -> None:
        """The winning flag (``state["candidate"]``): set while the current rule's paper record is winning, said
        once; while :data:`RULE_LAB_PASSED` is False it is NOT called a candidate for real money. When it clears (the
        record fell back, the rule changed, the guard was switched off) one event and a receipt say so, and a later
        return is said again. A flag for the owner: nothing here touches mode, the client or a setting."""
        st, rule = self.state, self.rule
        old = st.get("candidate") if isinstance(st.get("candidate"), dict) else None
        if on and paper.verdict == deskguard.WINNING:
            cand = _current(old, rule)
            st["candidate"] = {"at": cand["at"] if cand else now, "reason": paper.reason, "rule": rule,
                               "lab_passed": RULE_LAB_PASSED}
            if st.get("candidate_said") != rule:
                st["candidate_said"] = rule
                text = ("Candidate for real money (owner decides): " if RULE_LAB_PASSED else
                        "Paper record clears the risk manager's bar (lab 4 has not passed this rule: no real money): ")
                self._event(now, text + paper.summary, "good")
                self._receipt("polydesk_candidate", {"rule": rule, "n": paper.n, "total_usd": paper.total,
                                                     "lab_passed": RULE_LAB_PASSED, "cleared": False})
                log.info("polydesk_candidate rule=%s n=%d lab_passed=%s", rule, paper.n, RULE_LAB_PASSED)
            return
        st["candidate"] = None
        st["candidate_said"] = None  # a later return is said again
        if old is None:
            return
        if not on:
            why = "the risk manager is off"
        elif old.get("rule") != rule:
            why = "the rule changed, its record starts from zero"
        else:
            why = f"the paper record is {paper.phrase} now, {paper.summary}"
        word = "No longer a candidate" if old.get("lab_passed") else "No longer clears the risk manager's bar"
        self._event(now, f"{word}: {why}", "neutral")
        self._receipt("polydesk_candidate", {"rule": old.get("rule"), "n": paper.n, "total_usd": paper.total,
                                             "lab_passed": bool(old.get("lab_passed")), "cleared": True})
        log.info("polydesk_candidate_cleared rule=%s why=%s", old.get("rule"), why)


# ---------------------------------------------------------------------- the panel's view
def _since(ts: Any, now: float | None) -> str | None:
    """When a pause began, in UTC: ``18:40 UTC`` on the same UTC day as ``now``, else with the date."""
    at = _num(ts)
    if at is None:
        return None
    when = datetime.fromtimestamp(at, UTC)
    same_day = now is not None and datetime.fromtimestamp(now, UTC).date() == when.date()
    return when.strftime("%H:%M UTC" if same_day else "%Y-%m-%d %H:%M UTC")


def _guard_line(book: str, v: deskguard.Verdict, pause: dict[str, Any] | None, on: bool, flag: str | None,
                now: float | None) -> str:
    """The risk manager's verdict on one book in one plain sentence (the page's line). A pause says since when
    and what the record said then; when the record has moved since, it says what the record says now too."""
    if not on:
        return f"Risk manager off (the owner's switch); the {book} record is {v.phrase}: {v.reason}."
    if pause is not None:
        since = _since(pause.get("at"), now)
        head = f"Paused by the risk manager{f' since {since}' if since else ''} ({book} buys stopped"
        then = str(pause.get("reason") or "")
        if not then or then == v.reason:
            return f"{head}): {v.reason}."
        return f"{head}; then: {then}); the {book} record now: {v.reason}."
    if flag == "candidate":
        return f"Risk manager ({book}, winning): a candidate for real money, the owner decides. {v.reason}."
    if flag == "bar":
        return (f"Risk manager ({book}, winning): the record clears the bar, but lab 4 has not passed this rule, so no "
                f"real money. {v.reason}.")
    return f"Risk manager ({book}, {v.phrase}): {v.reason}."


def guard_view(settings: Settings, st: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """The risk manager's view for the panel and the page: each book's verdict on the current rule's own record
    (:func:`judge_book`, recomputed from the file), whether its buys are paused and since when (a pause of an older
    rule, or any pause with the guard off, does not count), and a plain ``line``. ``real`` is None until the
    current rule has a real settlement, a real pause, or the desk is live. ``clears_bar`` is the winning flag;
    ``candidate`` is it only once the rule passed lab 4 (:data:`RULE_LAB_PASSED`)."""
    on = bool(settings.polydesk_guard)
    rule = rule_id(settings)
    by_rule = st.get("by_rule") or {}
    paused = _current(st.get("paused"), rule) if on else None
    paused_real = _current(st.get("paused_real"), rule) if on else None
    flagged = _current(st.get("candidate"), rule) if on else None
    candidate = flagged if flagged is not None and RULE_LAB_PASSED and flagged.get("lab_passed") else None
    paper = judge_book(settings, by_rule, "paper")
    real = judge_book(settings, by_rule, "real")
    real_pause = paused_real or (  # a losing paper record stops real buys too, and the real line says why
        {**paused, "reason": f"the paper record was losing, {paused.get('reason')}"} if paused is not None else None)
    show_real = real.n > 0 or paused_real is not None or st.get("mode") == "live"

    def book_view(book: str, v: deskguard.Verdict, pause: dict[str, Any] | None, flag: str | None) -> dict[str, Any]:
        return {**v.to_dict(), "phrase": v.phrase, "paused": pause is not None,
                "paused_at": _num(pause.get("at")) if pause is not None else None,
                "paused_since": _since(pause.get("at"), now) if pause is not None else None,
                "line": _guard_line(book, v, pause, on, flag, now)}

    flag = "candidate" if candidate is not None else ("bar" if flagged is not None else None)
    return {
        "on": on,
        "rule": rule,
        "paper": book_view("paper", paper, paused, flag),
        "real": book_view("real", real, real_pause, None) if show_real else None,
        "paused": paused,
        "paused_real": paused_real,
        "candidate": candidate,
        "clears_bar": flagged is not None,
        "paper_cap": PAPER_MAX_OPEN if not on or paper.verdict == deskguard.WINNING
        else min(PAPER_MAX_OPEN, PAPER_LEARNING_OPEN),
    }


def panel_state(settings: Settings, now: float) -> dict[str, Any]:
    """What the team room shows for this desk (reads the state file only). Paper and real money are
    tallied apart (``paper`` / ``real``: open positions, money at risk, today's and all-time results), so
    paper positions left over from before a switch to live are never shown as real ones. The top-level
    ``open``/``today``/``*_total`` keys are the combined book. ``since_fix`` is the current rule version's own
    record (:func:`rule_id`) and ``before_fix`` everything else (older rules' rows, venue adoptions), each with
    paper and real apart;
    ``lessons`` and ``worst`` are derived from the closed rows (module docstring); ``guard`` is the risk
    manager's view (:func:`guard_view`)."""
    st = load_state(state_path(settings))
    enabled = bool(settings.polydesk_enabled)
    today = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    day = st["days"].get(today, {"pnl_usd": 0.0, "settled": 0, "won": 0})
    total = sum(float(d.get("pnl_usd") or 0.0) for d in st["days"].values())
    c = st["counters"]
    open_n = len(st["positions"])
    live = st.get("mode") == "live"
    live_days = st.get("live_days") or {}
    live_day = live_days.get(today) or {}
    real_open = [p for p in st["positions"].values() if p.get("live")]
    real_settled = sum(int(d.get("settled") or 0) for d in live_days.values())
    real_won = sum(int(d.get("won") or 0) for d in live_days.values())
    real_total = float(st.get("live_pnl_total_usd") or 0.0)
    real_today = {
        "pnl_usd": float(live_day.get("pnl_usd") or 0.0),
        "settled": int(live_day.get("settled") or 0),
        "won": int(live_day.get("won") or 0),
    }
    real: dict[str, Any] = {
        "open": len(real_open),
        "at_risk_usd": sum(float(p.get("cost_usd") or 0.0) for p in real_open),
        "settled_total": real_settled,
        "won_total": real_won,
        "pnl_total_usd": real_total,
        "today": real_today,
    }
    paper: dict[str, Any] = {
        "open": open_n - len(real_open),
        "settled_total": int(c.get("settled") or 0) - real_settled,
        "won_total": int(c.get("won") or 0) - real_won,
        "pnl_total_usd": total - real_total,
        "today": {
            "pnl_usd": float(day["pnl_usd"]) - real_today["pnl_usd"],
            "settled": int(day["settled"]) - real_today["settled"],
            "won": int(day["won"]) - real_today["won"],
        },
    }
    rule = rule_id(settings)
    since_rec = (st.get("by_rule") or {}).get(rule) or {}
    since_open = [p for p in st["positions"].values() if p.get("rule") == rule]

    def _since_book(book: str) -> dict[str, Any]:
        rec = since_rec.get(book) or {}
        return {
            "open": sum(1 for p in since_open if _book_of(p) == book),
            "settled_total": int(rec.get("settled") or 0),
            "won_total": int(rec.get("won") or 0),
            "pnl_total_usd": float(rec.get("pnl_usd") or 0.0),
        }

    since_fix: dict[str, Any] = {"rule": rule, "paper": _since_book("paper"), "real": _since_book("real")}
    before_fix: dict[str, Any] = {  # everything the current rule did not buy: the whole book less its own record
        "rule": BEFORE_FIX,
        **{
            book: {k: whole[k] - since_fix[book][k] for k in ("open", "settled_total", "won_total", "pnl_total_usd")}
            for book, whole in (("paper", paper), ("real", real))
        },
    }
    return {
        "enabled": enabled,
        "mode": "live" if live else "paper",
        "label": "Real money" if live else "Paper money (pretend)",
        "balance": st.get("balance"),
        "live_status": st.get("live_status"),
        "live_pnl_total_usd": real_total,
        "real": real,
        "paper": paper,
        "exchange": st.get("exchange"),
        "rule": st.get("rule"),
        "last_poll": st.get("last_poll"),
        "last_ok": st.get("last_ok"),
        "last_error": st.get("last_error"),
        "watched": int(st.get("watched") or 0),
        "open": open_n,
        "settled_total": int(c.get("settled") or 0),
        "won_total": int(c.get("won") or 0),
        "pnl_total_usd": total,
        "today": {
            "pnl_usd": float(day["pnl_usd"]),
            "settled": int(day["settled"]),
            "won": int(day["won"]),
        },
        "positions": [
            {
                "question": p["question"],
                "side": p["side"],
                "p_in": p["p_in"],
                "category": p["category"],
                "t_in": p["t_in"],
                "live": bool(p.get("live")),
                "cost_usd": float(p.get("cost_usd") or 0.0),
            }
            # the real-money ones first (the 3D board shows the first three), each book newest first
            for p in sorted(st["positions"].values(), key=lambda p: (not p.get("live"), -p["t_in"]))[:10]
        ],
        "events": st.get("events", [])[:EVENTS_KEEP],
        "polls": int(c.get("polls") or 0),
        "since_fix": since_fix,
        "before_fix": before_fix,
        "lessons": lessons(st["closed"]),
        "worst": worst_row(st["closed"]),
        # the newest real settlements still in the kept closed rows, newest first (the 3D world's trophy shelf)
        "real_closed": [
            {"question": str(r.get("question") or ""), "settled_at": _num(r.get("settled_at")), "pnl_usd": pnl,
             "won": bool(r["won"])}
            for r in st["closed"]
            if isinstance(r, dict) and r.get("live") and r.get("won") is not None
            and (pnl := _num(r.get("pnl_usd"))) is not None
        ][:REAL_CLOSED_SHOWN],
        "paper_max_open": PAPER_MAX_OPEN,
        "guard": guard_view(settings, st, now),
    }

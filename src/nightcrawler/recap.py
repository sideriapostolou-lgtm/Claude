"""The nightly recap: what the bot did YESTERDAY, from its own records ONLY (the ledger and its receipts), for the 3D
world's recap film (``/api/page`` -> ``recap``; the film plays it by itself at 00:05 in the owner's time zone and on
demand from the "yesterday" chip).

Yesterday is the previous calendar day of the owner's time zone (``OWNER_TZ``, default ``America/Los_Angeles``):
:func:`day_window` turns ``now`` into that day's ``[start, end)`` in epoch seconds (a daylight-saving day is 23 or 25
hours long, as it really is). When the zone cannot be loaded (an unknown name, or no time-zone database on the
machine) the window is the UTC day and ``tz`` says ``"UTC"``: nothing is guessed.

Schema (every key always present; an unknown value is null; lists capped)::

    {"date": "YYYY-MM-DD", "tz": str, "window": [start_ts, end_ts],
     "events": [{"ts", "member", "text", "tone": "good"|"bad"|"neutral", "real": bool}],  # <= RECAP_BEATS_MAX
     "events_total": int,               # how many records of these kinds the day had (the film shows a few)
     "quiet": bool,                     # the ledger holds nothing at all for the day (no receipt, money check, ...)
     "closed": [{"coin", "closed_at", "pnl_usd": float|null, "result", "why", "label"}],   # <= RECAP_CLOSED_MAX
     "real": {"label": "Real money", "start_usd", "end_usd", "settled", "won", "line"}|null,
     "pretend": {"label": "Practice (pretend money)", "line"}|null}

REAL DATA ONLY. Every event is one record of the day, worded by the page's own plain words (the caller's ``words``:
:func:`nightcrawler.pagestate.plain_event`) and named for the member who made it: the Polymarket desk's real-money
records from the receipts (a real buy, a position found at the venue, a settlement, the risk manager's pause, the total
loss stop, the live connection), the Solana bot's closed trades, its halts and kill-switch changes, setups, refusals,
danger flags, the AI judge's verdicts, the scam filter's passes and rejections and the first and last coin found.
``real`` is true for a record of real money: every one of the desk's real-money receipts, and the Solana bot's trades
while it trades real money itself. A busy day keeps :data:`RECAP_BEATS_MAX` of them: up to :data:`HEADLINE_MAX`
headline records first (real money, a halt or the kill switch, a closed trade: one of each kind in turn, so a closed
trade and the risk manager's pause always make it when the day had them), then the other kinds in turn, then more
headlines if the rest ran dry; each kind's records spread over the day.

A closed trade's dollar figure is its result in SOL at the page's own SOL price (``sol_usd``: today's, like the money
card and ``trades.closed``, so the film and the trophy card say the same figure for the same trade); without a price
the figure is in SOL.

``real`` is the Polymarket desk's real money (null unless the desk has a real book): its result since start when the
day began and when it ended, worked back from the money card's own figure (``money.polymarket.real.since_start_usd``)
minus the real settlements receipted since then (both null when more than :data:`QUERY_CAP` settled since the day
began: never a figure from a partial read), and the bets that finished that day (``won``: a positive result).
``pretend`` is the Solana bot's practice result over the day (the equity snapshot the day started with, the last one
of the day, open trades at their price, measured in SOL and shown in dollars at the later snapshot's SOL price), null
while the bot itself trades real money (its line then joins ``real``). Gains are worded "up $X" only where the figure
shows one.

Bounded: every query is limited to the day's window (the settlements since the day began: from its start) and capped
at :data:`QUERY_CAP` rows (that one at one more, to tell a whole read from a cut one), and the page's builder keeps the
day's records (:func:`collect_recap`) for :data:`RECAP_TTL_S` per day, zone and mode; :func:`render_recap` words them
on every page (cheap: a few lines).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import zoneinfo
from collections.abc import Callable, Mapping
from typing import Any

from nightcrawler.models import LAMPORTS_PER_SOL, Decision, EquityPoint, Position
from nightcrawler.teamroom import plain

__all__ = ["HEADLINE_MAX", "QUERY_CAP", "RECAP_BEATS_MAX", "RECAP_CLOSED_MAX", "RECAP_TTL_S", "build_recap",
           "collect_recap", "day_window", "empty_recap", "render_recap", "zone_or_none"]

#: The film's beats: the recap keeps at most this many events (about five seconds each, so the film lasts a minute).
RECAP_BEATS_MAX = 8
#: The headline records (real money, halts, closed trades) the film keeps before any other kind.
HEADLINE_MAX = 5
RECAP_CLOSED_MAX = 10
#: Yesterday does not change: the page's data builder re-reads the day's records at most this often (per day and zone).
RECAP_TTL_S = 1800.0
#: The most rows one query of the recap reads (a day's window is already small; this bounds a pathological one).
QUERY_CAP = 500
TEXT_MAX = 160
COIN_MAX = 24
#: The labels (the page's own words: the money card's and the plain words').
REAL_LABEL = "Real money"
PAPER_LABEL = "Paper money (pretend)"
PRETEND_LABEL = "Practice (pretend money)"
_MINUS = "−"
#: Lower is more important (0 and 1 are the headlines): the film takes one record of each kind in this order, then a
#: second of each, and so on.
_RANK = {"real_settled": 0, "real_halted": 0, "real_guard": 0, "halt": 0, "kill": 0, "closed": 1, "real_buy": 1,
         "real_found": 1, "real_on": 1, "enter": 2, "reject_risk": 2, "reject_radar": 2, "exit_partial": 2,
         "reset": 2, "judge": 3, "buy": 3, "watch": 4, "reject_quote": 4, "reject_cocoon": 5, "unwatch": 5, "found": 5}
#: The Solana bot's own money records: real money while it trades real money itself.
_SOLANA_MONEY = ("closed", "buy", "enter", "exit_partial")
_DECISIONS = ("enter", "reject_risk", "reject_radar", "reject_judge", "reject_quote", "exit_partial", "watch",
              "reject_cocoon", "unwatch")
_REAL_KINDS = ("polydesk_settled", "polydesk_order_filled", "polydesk_position_adopted", "polydesk_guard",
               "polydesk_live_halted", "polydesk_live_connected")
_FEEDS = (("jupiter", "Jupiter"), ("gt_", "GeckoTerminal"), ("dexscreener", "DexScreener"), ("pumpfun", "pump.fun"))
#: The kill switch's modes in plain words (``KILL_SWITCH`` / ``DATA_DIR/KILL``; engine.handle_kill receipts each change).
_KILL_WORDS = {"pause": "no new buys", "stop": "no new buys", "sell_all": "sell everything, buy nothing"}

Words = Callable[[str, str], str]


def zone_or_none(name: str) -> dt.tzinfo | None:
    """The IANA zone ``name``, or None when it is unknown or no time-zone database is installed."""
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return None


def day_window(now: float, tz: str, days_back: int = 1) -> tuple[str, float, float, str]:
    """``(date, start_ts, end_ts, zone)`` of the local calendar day ``days_back`` days before the one holding
    ``now`` in zone ``tz`` (the UTC day, and ``zone == "UTC"``, when the zone cannot be loaded)."""
    zone = zone_or_none(tz)
    name = tz if zone is not None else "UTC"
    zone = zone if zone is not None else dt.UTC
    day = dt.datetime.fromtimestamp(now, zone).date() - dt.timedelta(days=days_back)
    start = dt.datetime.combine(day, dt.time(0), tzinfo=zone)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0), tzinfo=zone)
    return day.isoformat(), start.timestamp(), end.timestamp(), name


def _clip(text: str, limit: int = TEXT_MAX) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _short(mint: str) -> str:
    return f"{mint[:4]}…{mint[-4:]}" if len(mint) > 12 else mint


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _loads(text: Any) -> dict[str, Any]:
    try:
        return _dict(json.loads(text))
    except (TypeError, ValueError):
        return {}


def _dollars(value: float) -> str:
    return f"${abs(value):,.2f}"


def _signed(value: float) -> str:
    cents = round(value, 2)
    return ("+" if cents > 0 else _MINUS if cents < 0 else "") + _dollars(cents)


def _since(value: float) -> str:
    """A result since start in words: "up $X since start" only when the figure shows a gain (the sentence it sits in
    already says whose money it is)."""
    cents = round(value, 2)
    if cents > 0:
        return f"up {_dollars(cents)} since start"
    if cents < 0:
        return f"down {_dollars(cents)} since start"
    return "even since start"


def _day_change(value: float) -> str:
    cents = round(value, 2)
    return f"up {_dollars(cents)}" if cents > 0 else f"down {_dollars(cents)}" if cents < 0 else "even"


def _usd_compact(value: float) -> str:
    if abs(value) >= 1e6:
        return f"${value / 1e6:.1f}M"
    if abs(value) >= 1e3:
        return f"${value / 1e3:.0f}k"
    return f"${value:,.0f}"


def _price(value: float | None) -> str:
    if value is None or value <= 0:
        return "$?"
    if value >= 1:
        return f"${value:.4f}"
    return f"${value:.4g}" if value >= 1e-6 else f"${value:.2e}"


def _rows(ledger: Any, sql: str, params: list[Any]) -> list[Any]:
    """A read-only SELECT through the ledger's own locked connection (the team room does the same)."""
    return ledger._rows(sql, params)


def _event(ts: float, member: str, kind: str, text: str, tone: str) -> dict[str, Any]:
    return {"ts": float(ts), "member": member, "kind": kind, "text": text, "tone": tone}


# --------------------------------------------------------------------------- the Solana bot's records


def _decision_event(d: Decision, money: str = "pretend money") -> dict[str, Any] | None:
    """One decision in the team room's wording (the plain words know it; a part sold for profit and a bad quote in
    plain words here), or None for a kind the film skips. ``money``: what the Solana bot trades with."""
    name = d.symbol or _short(d.mint)
    verdict = d.verdict.to_dict() if d.verdict is not None else None
    if d.action == "enter":
        return _event(d.ts, "strategy", "enter", f"SETUP {name} · the drop and the bounce came · bought", "good")
    if d.action == "reject_risk":
        return _event(d.ts, "risk", "reject_risk", f"REFUSED {name} · {plain(d.reason)}", "bad")
    if d.action == "reject_radar":
        radar = _dict(d.inputs.get("radar"))
        why = "; ".join(str(r) for r in radar.get("reasons") or []) or plain(d.reason.removeprefix("radar: "))
        return _event(d.ts, "radar", "reject_radar", f"FLAGGED {name} · {why}", "bad")
    if d.action == "reject_judge" and verdict and verdict.get("source") not in ("rules", "error"):
        conf = round((_num(verdict.get("confidence")) or 0.0) * 100)
        why = "; ".join(str(r) for r in verdict.get("reasons") or [])
        return _event(d.ts, "judge", "judge", f"NO {conf}% · {name} · {why}", "bad")
    if d.action == "reject_quote":
        return _event(d.ts, "broker", "reject_quote", f"did not buy {name}: the price was not good enough ({plain(d.reason)})", "bad")
    if d.action == "exit_partial":
        return _event(d.ts, "broker", "exit_partial", f"sold part of {name} to take profit ({money})", "good")
    if d.action == "watch":
        return _event(d.ts, "cocoon", "watch", f"PASS {name} · {d.reason}", "good")
    if d.action == "reject_cocoon":
        return _event(d.ts, "cocoon", "reject_cocoon", f"REJECT {name} · {plain(d.reason)}", "bad")
    if d.action == "unwatch":
        return _event(d.ts, "strategy", "unwatch", f"DROP {name} · {d.reason}", "neutral")
    return None


def _judge_yes(d: Decision) -> dict[str, Any] | None:
    """The judge's own YES behind a buy (a ``source="rules"`` verdict is the judge being off: not its work)."""
    verdict = d.verdict.to_dict() if d.verdict is not None else None
    if d.action != "enter" or not verdict or verdict.get("source") in ("rules", "error"):
        return None
    conf = round((_num(verdict.get("confidence")) or 0.0) * 100)
    why = "; ".join(str(r) for r in verdict.get("reasons") or [])
    return _event(d.ts, "judge", "judge", f"YES {conf}% · {d.symbol or _short(d.mint)} · {why}", "good")


def _found_event(data: str, first_seen: float) -> dict[str, Any]:
    c = _loads(data)
    bits = [str(c.get("symbol") or _short(str(c.get("mint", ""))))]
    age = _num(c.get("age_min"))
    if age is not None:
        bits.append(f"{age:.0f} min old" if age < 120 else f"{age / 60:.1f} h old")
    mcap = _num(c.get("mcap_usd"))
    if mcap is not None:
        bits.append(f"worth {_usd_compact(mcap)}")
    feeds = list(dict.fromkeys(next((n for p, n in _FEEDS if str(s).startswith(p)), str(s))
                               for s in c.get("sources") or []))[:2]
    if feeds:
        bits.append("found on " + ", ".join(feeds))
    return _event(first_seen, "crawler", "found", " · ".join(bits), "neutral")


def _closed_trades(ledger: Any, mode: str, start: float, end: float, exit_words: Mapping[str, str],
                   label: str) -> list[dict[str, Any]]:
    """The Solana bot's trades closed in the window, in SOL (the dollar figure is the page's: :func:`render_recap`)."""
    rows = _rows(ledger, "SELECT data FROM positions WHERE status = 'closed' AND closed_at >= ? AND closed_at < ? "
                         "ORDER BY closed_at, rowid LIMIT ?", [start, end, QUERY_CAP])
    out = []
    for (data,) in rows:
        p = Position.from_dict(json.loads(data))
        if p.mode not in (None, mode) or p.closed_at is None:
            continue
        pnl_sol = p.pnl_lamports() / LAMPORTS_PER_SOL
        reason = p.exit_reason or ""
        why = "Danger spotted, sold early" if reason.startswith("radar") else exit_words.get(reason, "Sold")
        out.append({"coin": p.symbol or _short(p.mint), "closed_at": p.closed_at, "pnl_sol": pnl_sol,
                    "result": "won" if pnl_sol > 0 else "lost" if pnl_sol < 0 else "even", "why": why,
                    "label": label})
    return out


def _closed_event(t: Mapping[str, Any], *, live: bool) -> dict[str, Any]:
    figure = _signed(t["pnl_usd"]) if t["pnl_usd"] is not None else f"{t['pnl_sol']:+.4f} SOL"
    kind = "real money" if live else "pretend money"
    tone = "good" if t["result"] == "won" else "bad" if t["result"] == "lost" else "neutral"
    return _event(float(t["closed_at"]), "broker", "closed", f"{t['coin']}: {t['why']} · {t['result']} {figure} ({kind})",
                  tone)


def _halt_event(ts: float, kind: str, payload: Any) -> dict[str, Any]:
    """A halt, a kill-switch change or a reset, worded by what its receipt says: the kill switch turned OFF is said
    so (never "went on"), its other modes in plain words."""
    p = _loads(payload)
    if kind == "kill":
        mode = str(p.get("mode") or "")
        if mode == "off":
            return _event(ts, "risk", "kill", "the kill switch was turned off", "neutral")
        words = _KILL_WORDS.get(mode)
        return _event(ts, "risk", "kill", f"the kill switch went on ({words})" if words
                      else f"the kill switch changed: {plain(mode)}" if mode else "the kill switch changed", "bad")
    detail = plain(str(p.get("reason") or p.get("note") or "")).strip()
    if kind == "halt":
        return _event(ts, "risk", "halt", f"stopped new buys: {detail}" if detail else "stopped new buys", "bad")
    return _event(ts, "risk", "reset", f"the stop was reset: {detail}" if detail else "the stop was reset", "neutral")


def _solana_events(ledger: Any, mode: str, start: float, end: float) -> tuple[list[dict[str, Any]], int]:
    """The Solana bot's decisions, buys, halts and finds of the day ``(events, how many records)``."""
    money = "real money" if mode == "live" else "pretend money"
    events: list[dict[str, Any]] = []
    marks = ",".join("?" for _ in _DECISIONS)
    total = int(_rows(ledger, f"SELECT COUNT(*) FROM decisions WHERE ts >= ? AND ts < ? AND action IN ({marks})",
                      [start, end, *_DECISIONS])[0][0])
    for action in _DECISIONS:  # each kind capped on its own, so one busy kind never crowds out the rest
        for (data,) in _rows(ledger, "SELECT data FROM decisions WHERE ts >= ? AND ts < ? AND action = ? "
                                     "ORDER BY ts, id LIMIT ?", [start, end, action, QUERY_CAP]):
            d = Decision.from_dict(json.loads(data))
            for ev in (_decision_event(d, money), _judge_yes(d)):
                if ev is not None:
                    events.append(ev)
    fills = _rows(ledger, "SELECT data FROM fills WHERE ts >= ? AND ts < ? AND side = 'buy' AND mode = ? "
                          "ORDER BY ts LIMIT ?", [start, end, mode, QUERY_CAP])
    total += len(fills)
    for (data,) in fills:
        f = _loads(data)
        name = str(f.get("symbol") or _short(str(f.get("mint", ""))))
        sol = (_num(f.get("sol_lamports")) or 0.0) / LAMPORTS_PER_SOL
        events.append(_event(_num(f.get("ts")) or start, "broker", "buy",
                             f"BUY {name} for {sol:.4f} SOL at {_price(_num(f.get('price_usd')))}", "neutral"))
    halts = _rows(ledger, "SELECT ts, kind, payload FROM receipts WHERE kind IN ('halt', 'kill', 'reset') "
                          "AND ts >= ? AND ts < ? ORDER BY seq LIMIT ?", [start, end, QUERY_CAP])
    total += len(halts)
    for ts, kind, payload in halts:
        events.append(_halt_event(float(ts), str(kind), payload))
    found_n = int(_rows(ledger, "SELECT COUNT(*) FROM candidates WHERE first_seen >= ? AND first_seen < ?",
                        [start, end])[0][0])
    total += found_n
    if found_n:  # the first and the last coin found
        first = _rows(ledger, "SELECT data, first_seen FROM candidates WHERE first_seen >= ? AND first_seen < ? "
                              "ORDER BY first_seen LIMIT 1", [start, end])
        last = _rows(ledger, "SELECT data, first_seen FROM candidates WHERE first_seen >= ? AND first_seen < ? "
                             "ORDER BY first_seen DESC LIMIT 1", [start, end]) if found_n > 1 else []
        for data, first_seen in first + last:
            events.append(_found_event(data, float(first_seen)))
    return events, total


def _quiet(ledger: Any, start: float, end: float) -> bool:
    """True when the ledger holds nothing at all for the window: no receipt, money check, decision, fill or coin."""
    for sql in ("SELECT 1 FROM receipts WHERE ts >= ? AND ts < ? LIMIT 1",
                "SELECT 1 FROM equity WHERE ts >= ? AND ts < ? LIMIT 1",
                "SELECT 1 FROM decisions WHERE ts >= ? AND ts < ? LIMIT 1",
                "SELECT 1 FROM fills WHERE ts >= ? AND ts < ? LIMIT 1",
                "SELECT 1 FROM candidates WHERE first_seen >= ? AND first_seen < ? LIMIT 1"):
        if _rows(ledger, sql, [start, end]):
            return False
    return True


# --------------------------------------------------------------------------- the Polymarket desk's real money


def _question(questions: Mapping[str, str], slug: str) -> str:
    return questions.get(slug) or slug or "a market"


def _real_events(ledger: Any, start: float, end: float, questions: Mapping[str, str]
                 ) -> tuple[list[dict[str, Any]], list[tuple[float, float]], bool]:
    """The desk's real-money receipts of the day as events (in the desk's own wording, which the plain words know),
    the day's real settlements ``[(ts, pnl_usd)]`` and whether the read stopped at :data:`QUERY_CAP` (then the
    settlements are only the first ones)."""
    marks = ",".join("?" for _ in _REAL_KINDS)
    rows = _rows(ledger, f"SELECT ts, kind, payload FROM receipts WHERE kind IN ({marks}) AND ts >= ? AND ts < ? "
                         "ORDER BY seq LIMIT ?", [*_REAL_KINDS, start, end, QUERY_CAP])
    events, settled = [], []
    for ts, kind, payload in rows:
        p = _loads(payload)
        q = _question(questions, str(p.get("slug") or ""))
        contracts = _num(p.get("contracts")) or 0.0
        noun = "contract" if contracts == 1 else "contracts"
        if kind == "polydesk_settled":
            pnl = _num(p.get("pnl_usd"))
            if pnl is None:
                continue
            settled.append((float(ts), pnl))
            word = "won" if pnl > 0 else "lost"
            events.append(_event(ts, "predict", "real_settled", f"Settled: {q} · {word} {pnl:+.2f} $ (real)",
                                 "good" if pnl > 0 else "bad"))
        elif kind == "polydesk_order_filled":
            price, cost = _num(p.get("price")) or 0.0, _num(p.get("cost_usd")) or 0.0
            events.append(_event(ts, "predict", "real_buy",
                                 f"REAL buy: {q} · {contracts:g} {noun} at {price:.3f} (${cost:.2f})", "neutral"))
        elif kind == "polydesk_position_adopted":
            price, cost = _num(p.get("price")) or 0.0, _num(p.get("cost_usd")) or 0.0
            events.append(_event(ts, "predict", "real_found", f"REAL position found at the venue: {q} · "
                                 f"{contracts:g} {noun} at {price:.3f} (${cost:.2f})", "neutral"))
        elif kind == "polydesk_live_halted":
            events.append(_event(ts, "predict", "real_halted",
                                 "Total loss cap reached: real trading stopped, back to paper.", "bad"))
        elif kind == "polydesk_live_connected":
            cash = _num(p.get("cash"))
            line = f"connected to Polymarket with real money: {_dollars(cash)} cash" if cash is not None else \
                "connected to Polymarket with real money"
            events.append(_event(ts, "predict", "real_on", line, "neutral"))
        elif kind == "polydesk_guard":
            book, paused = p.get("book"), p.get("paused") is True
            what = "the real-money bets" if book == "real" else "the practice bets (and real ones with them)"
            line = (f"the risk manager paused {what}: the record was losing" if paused
                    else f"the risk manager lifted its pause on {what}")
            events.append(_event(ts, "predict", "real_guard", line, "bad" if paused else "neutral"))
    return events, settled, len(rows) >= QUERY_CAP


def _real_block(ledger: Any, start: float, end: float, desk: Mapping[str, Any] | None,
                settled: list[tuple[float, float]], capped: bool = False) -> dict[str, Any] | None:
    """``real`` (module docstring): null unless the desk has a real book. The result since start when the day began and
    when it ended: the money card's figure now minus the real settlements receipted since each moment (none when
    more than :data:`QUERY_CAP` settled since the day began: a partial read would give a wrong figure). ``capped``:
    the day's read stopped at the cap, so the line says "at least" that many finished and no count of wins."""
    real = _dict(_dict(desk).get("real")) if desk is not None else {}
    now_total = _num(real.get("since_start_usd"))
    if not real or now_total is None:
        return None
    later = _rows(ledger, "SELECT ts, payload FROM receipts WHERE kind = 'polydesk_settled' AND ts >= ? "
                          "ORDER BY seq LIMIT ?", [start, QUERY_CAP + 1])
    start_usd: float | None = None
    end_usd: float | None = None
    if len(later) <= QUERY_CAP:
        pnls = [(float(ts), _num(_loads(payload).get("pnl_usd")) or 0.0) for ts, payload in later]
        start_usd = round(now_total - sum(pnl for _, pnl in pnls), 2)
        end_usd = round(now_total - sum(pnl for ts, pnl in pnls if ts >= end), 2)
    won = sum(1 for _, pnl in settled if pnl > 0)
    n = len(settled)
    if capped:
        finished = f"at least {n} bets finished"
    else:
        finished = f"{won} of {n} finished bet{'' if n == 1 else 's'} won" if n else "no bet finished that day"
    if start_usd is not None and end_usd is not None:
        line = (f"Real money yesterday: the day began {_since(start_usd)} and ended {_since(end_usd)}; "
                f"{finished}.")
    else:
        line = f"Real money yesterday: {finished}."
    return {"label": REAL_LABEL, "start_usd": start_usd, "end_usd": end_usd, "settled": n, "won": won, "line": line}


def _solana_day(ledger: Any, mode: str, start: float, end: float) -> float | None:
    """The Solana bot's result over the day in dollars (SOL change at the later snapshot's SOL price), or None
    without a money check that day."""
    before = _rows(ledger, "SELECT data FROM equity WHERE ts < ? AND mode = ? ORDER BY ts DESC, id DESC LIMIT 1",
                   [start, mode])
    first = _rows(ledger, "SELECT data FROM equity WHERE ts >= ? AND ts < ? AND mode = ? ORDER BY ts, id LIMIT 1",
                  [start, end, mode])
    last = _rows(ledger, "SELECT data FROM equity WHERE ts >= ? AND ts < ? AND mode = ? ORDER BY ts DESC, id DESC "
                         "LIMIT 1", [start, end, mode])
    if not last or not (before or first):
        return None
    open_pt = EquityPoint.from_dict(json.loads((before or first)[0][0]))
    close_pt = EquityPoint.from_dict(json.loads(last[0][0]))
    change_sol = (close_pt.equity_lamports - open_pt.equity_lamports) / LAMPORTS_PER_SOL
    return round(change_sol * close_pt.sol_usd, 2)


# --------------------------------------------------------------------------- the film's beats


def _spread(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A kind's records in the order the film takes them, spread over the day: the first, the last, the middle, the
    quarters, the eighths and so on (then whatever is left, in time)."""
    n = len(items)
    picks: list[int] = [0, n - 1] if n else []
    step = 2
    while step < 2 * n:
        picks += [round(k / step * (n - 1)) for k in range(1, step, 2)]
        step *= 2
    return [items[i] for i in dict.fromkeys([*picks, *range(n)])]


def _take(queues: list[list[dict[str, Any]]], kept: list[dict[str, Any]], limit: int, *, mix: bool = False) -> None:
    """One record of each queue in turn (the queues in rank order), then a second of each, until ``kept`` holds
    ``limit`` or the queues are empty. ``mix``: within a round, a kind whose member the film has not shown yet goes
    before one whose member it has (a film of the whole team, not of one busy member)."""
    while len(kept) < limit and any(queues):
        left = [i for i, queue in enumerate(queues) if queue]  # this round: one record of each kind
        while left and len(kept) < limit:
            seen = {e["member"] for e in kept} if mix else set()
            pick = next((i for i in left if queues[i][0]["member"] not in seen), left[0])
            left.remove(pick)
            kept.append(queues[pick].pop(0))


def _beats(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most :data:`RECAP_BEATS_MAX` events, shown in time order: up to :data:`HEADLINE_MAX` headline records (real
    money, a halt or the kill switch, a closed trade: one of each kind in turn, the most important kind first), then
    one of each other kind in rank order (a member not shown yet first), a second of each, and so on; the headlines
    left over fill what the others could not. Every kind's records spread over the day."""
    ordered = sorted(events, key=lambda e: e["ts"])
    kinds: dict[str, list[dict[str, Any]]] = {}
    for ev in ordered:
        kinds.setdefault(ev["kind"], []).append(ev)
    order = sorted(kinds, key=lambda k: (_RANK.get(k, 9), k))
    top = [_spread(kinds[k]) for k in order if _RANK.get(k, 9) <= 1]
    rest = [_spread(kinds[k]) for k in order if _RANK.get(k, 9) > 1]
    kept: list[dict[str, Any]] = []
    _take(top, kept, HEADLINE_MAX)
    _take(rest, kept, RECAP_BEATS_MAX, mix=True)
    _take(top, kept, RECAP_BEATS_MAX)
    return sorted(kept, key=lambda e: e["ts"])


# --------------------------------------------------------------------------- the recap


def empty_recap(now: float, tz: str) -> dict[str, Any]:
    """A recap with nothing in it, for the day before ``now`` (the page shows it when the records cannot be read)."""
    date, start, end, zone = day_window(now, tz)
    return {"date": date, "tz": zone, "window": [start, end], "events": [], "events_total": 0, "quiet": False,
            "closed": [], "real": None, "pretend": None}


def collect_recap(ledger: Any, now: float, *, tz: str, mode: str, exit_words: Mapping[str, str],
                  desk: Mapping[str, Any] | None = None, questions: Mapping[str, str] | None = None
                  ) -> dict[str, Any]:
    """The day's records (the bounded reads; the page keeps this per day): the day before the one holding ``now`` in
    ``tz``. ``mode`` (``paper``/``live``) picks the Solana bot's trades and snapshots; ``exit_words`` the page's words
    for a trade's exit; ``desk`` the money card's Polymarket block (or None: the desk is off); ``questions`` the desk's
    questions by market (a receipt names the market only). :func:`render_recap` words it."""
    date, start, end, zone = day_window(now, tz)
    live = mode == "live"
    events, total = _solana_events(ledger, mode, start, end)
    real_events, settled, capped = _real_events(ledger, start, end, questions or {})
    closed = _closed_trades(ledger, mode, start, end, exit_words, REAL_LABEL if live else PAPER_LABEL)
    total += len(real_events) + len(closed)
    return {"date": date, "tz": zone, "window": [start, end], "live": live, "events": events + real_events,
            "total": total, "quiet": total == 0 and _quiet(ledger, start, end), "closed": closed,
            "real": _real_block(ledger, start, end, desk, settled, capped),
            "day": _solana_day(ledger, mode, start, end)}


def render_recap(raw: Mapping[str, Any], *, words: Words, text: Callable[[Any, int], str] | None = None,
                 sol_usd: float | None = None) -> dict[str, Any]:
    """The ``recap`` block (schema in the module docstring) from :func:`collect_recap`'s records: ``words(member,
    text)`` puts a record in the page's plain words; ``text`` (optional) a redacting clipper applied to every line (the
    page passes its own, so a secret in a ledger text can never reach the film); ``sol_usd`` the page's own SOL price
    (a closed trade's dollar figure, the same as ``trades.closed``'s)."""
    clip: Callable[[Any, int], str] = text if text is not None else (lambda value, limit: _clip(str(value), limit))
    live = bool(raw["live"])
    price = _num(sol_usd)
    closed = [dict(t, pnl_usd=round(t["pnl_sol"] * price, 2) if price is not None else None) for t in raw["closed"]]
    events = [*raw["events"], *(_closed_event(t, live=live) for t in closed)]
    day = raw["day"]
    real = dict(raw["real"]) if raw["real"] is not None else None
    pretend: dict[str, Any] | None = None
    if live:  # the bot itself trades real money: its day is real money, said with the real line
        sentence = "The Solana bot (real money): " + (f"ended the day {_day_change(day)}." if day is not None
                                                      else "no money check that day.")
        if real is None:
            real = {"label": REAL_LABEL, "start_usd": None, "end_usd": None, "settled": 0, "won": 0, "line": sentence}
        else:
            real["line"] += " " + sentence
    else:
        solana = (f"the Solana bot's pretend wallet ended the day {_day_change(day)}, counting open trades at their "
                  "price" if day is not None else "the Solana bot had no money check that day")
        pretend = {"label": PRETEND_LABEL, "line": f"{PRETEND_LABEL}: {solana}."}
    return {
        "date": raw["date"], "tz": raw["tz"], "window": list(raw["window"]),
        "events": [{"ts": e["ts"], "member": e["member"], "text": clip(words(e["member"], e["text"]), TEXT_MAX),
                    "tone": e["tone"],
                    "real": e["kind"].startswith("real_") or (live and e["kind"] in _SOLANA_MONEY)}
                   for e in _beats(events)],
        "events_total": int(raw["total"]),
        "quiet": bool(raw["quiet"]),
        "closed": [{"coin": clip(t["coin"], COIN_MAX), "closed_at": t["closed_at"], "pnl_usd": t["pnl_usd"],
                    "result": t["result"], "why": clip(t["why"], 60), "label": t["label"]}
                   for t in closed[-RECAP_CLOSED_MAX:]],
        "real": real,
        "pretend": pretend,
    }


def build_recap(ledger: Any, now: float, *, tz: str, mode: str, words: Words, exit_words: Mapping[str, str],
                desk: Mapping[str, Any] | None = None, questions: Mapping[str, str] | None = None,
                text: Callable[[Any, int], str] | None = None, sol_usd: float | None = None) -> dict[str, Any]:
    """Yesterday's recap at once: :func:`collect_recap` then :func:`render_recap` (the page keeps the first per day)."""
    raw = collect_recap(ledger, now, tz=tz, mode=mode, exit_words=exit_words, desk=desk, questions=questions)
    return render_recap(raw, words=words, text=text, sol_usd=sol_usd)

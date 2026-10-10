"""The nightly recap: what the bot did YESTERDAY, from its own records ONLY (the ledger and its receipts), for the 3D
world's recap film (``/api/page`` -> ``recap``; the film plays it by itself at 00:05 in the owner's time zone and on
demand from the "yesterday" chip).

Yesterday is the previous calendar day of the owner's time zone (``OWNER_TZ``, default ``America/Los_Angeles``):
:func:`day_window` turns ``now`` into that day's ``[start, end)`` in epoch seconds (a daylight-saving day is 23 or 25
hours long, as it really is). When the zone cannot be loaded (no time-zone database on the machine) the window is the
UTC day and ``tz`` says ``"UTC"``: nothing is guessed.

Schema (every key always present; an unknown value is null; lists capped)::

    {"date": "YYYY-MM-DD", "tz": str, "window": [start_ts, end_ts],
     "events": [{"ts", "member", "text", "tone": "good"|"bad"|"neutral"}],   # <= RECAP_BEATS_MAX, in time order
     "events_total": int,               # how many records of these kinds the day had (the film shows a few)
     "closed": [{"coin", "closed_at", "pnl_usd": float|null, "result", "why", "label"}],   # <= RECAP_CLOSED_MAX
     "real": {"label": "Real money", "start_usd", "end_usd", "settled", "won", "line"}|null,
     "pretend": {"label": "Practice (pretend money)", "line"}|null}

REAL DATA ONLY. Every event is one record of the day, worded by the page's own plain words (the caller's ``words``:
:func:`nightcrawler.pagestate.plain_event`) and named for the member who made it: the Polymarket desk's real-money
records from the receipts (a real buy, a position found at the venue, a settlement, the risk manager's pause, the total
loss stop, the live connection), the Solana bot's closed trades, its halts, setups, refusals, danger flags, the AI
judge's verdicts, the scam filter's passes and rejections and the first and last coin found. A busy day keeps
:data:`RECAP_BEATS_MAX` of them: the headline records first (real money, a halt, a closed trade), then the other
kinds in turn, each spread over the day.

``real`` is the Polymarket desk's real money (null unless the desk has a real book): its result since start when the
day began and when it ended, worked back from the money card's own figure (``money.polymarket.real.since_start_usd``)
minus the real settlements receipted since then, and the bets that finished that day (``won``: a positive result).
``pretend`` is the Solana bot's practice result over the day (the equity snapshot the day started with, the last one
of the day, measured in SOL and shown in dollars at the later snapshot's SOL price, like the money card), null while
the bot itself trades real money (its line then joins ``real``). Gains are worded "up $X since start (real money)"
only where the figure shows one.

Bounded: every query is limited to the day's window and capped (:data:`QUERY_CAP`), and the page's builder keeps the
recap for :data:`RECAP_TTL_S` per day, zone and mode (``memory``).
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
           "day_window", "zone_or_none"]

#: The film has 8-12 beats: the recap keeps at most this many events.
RECAP_BEATS_MAX = 12
#: The headline records (real money, halts, closed trades) the film keeps before any other kind.
HEADLINE_MAX = 8
RECAP_CLOSED_MAX = 10
#: Yesterday does not change: the page's data builder recomputes the recap at most this often (per day and zone).
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
#: Lower is more important: the film takes one record of each kind in this order, then a second of each, and so on.
_RANK = {"real_settled": 0, "real_halted": 0, "real_guard": 0, "halt": 0, "closed": 1, "real_buy": 1,
         "real_found": 1, "real_on": 1, "enter": 2, "reject_risk": 2, "reject_radar": 2, "exit_partial": 2,
         "judge": 3, "buy": 3, "watch": 4, "reject_quote": 4, "reject_cocoon": 5, "unwatch": 5, "found": 5}
_DECISIONS = ("enter", "reject_risk", "reject_radar", "reject_judge", "reject_quote", "exit_partial", "watch",
              "reject_cocoon", "unwatch")
_REAL_KINDS = ("polydesk_settled", "polydesk_order_filled", "polydesk_position_adopted", "polydesk_guard",
               "polydesk_live_halted", "polydesk_live_connected")
_FEEDS = (("jupiter", "Jupiter"), ("gt_", "GeckoTerminal"), ("dexscreener", "DexScreener"), ("pumpfun", "pump.fun"))

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


def _change(value: float, *, real: bool) -> str:
    """A result since start in words (the plain words' own wording): a gain is "up $X since start (real money)" for
    real money, and only when the figure shows it."""
    cents = round(value, 2)
    if cents > 0:
        return f"up {_dollars(cents)} since start" + (" (real money)" if real else "")
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
    rows = _rows(ledger, "SELECT data FROM positions WHERE status = 'closed' AND closed_at >= ? AND closed_at < ? "
                         "ORDER BY closed_at, rowid LIMIT ?", [start, end, QUERY_CAP])
    out = []
    for (data,) in rows:
        p = Position.from_dict(json.loads(data))
        if p.mode not in (None, mode):
            continue
        pnl_sol = p.pnl_lamports() / LAMPORTS_PER_SOL
        # the dollar figure at the SOL price the ledger itself recorded: the sell's, else the nearest money check's
        sell = _rows(ledger, "SELECT data FROM fills WHERE position_id = ? AND side = 'sell' ORDER BY ts DESC LIMIT 1",
                     [p.id])
        sol_usd = _num(_loads(sell[0][0]).get("sol_usd")) if sell else None
        if sol_usd is None and p.closed_at is not None:
            near = _rows(ledger, "SELECT sol_usd FROM equity WHERE ts <= ? AND mode = ? ORDER BY ts DESC, id DESC "
                                 "LIMIT 1", [p.closed_at, mode])
            sol_usd = _num(near[0][0]) if near else None
        reason = p.exit_reason or ""
        why = "Danger spotted, sold early" if reason.startswith("radar") else exit_words.get(reason, "Sold")
        out.append({"coin": p.symbol or _short(p.mint), "closed_at": p.closed_at,
                    "pnl_usd": round(pnl_sol * sol_usd, 2) if sol_usd else None, "pnl_sol": pnl_sol,
                    "result": "won" if pnl_sol > 0 else "lost" if pnl_sol < 0 else "even", "why": why,
                    "label": label})
    return out


def _closed_event(t: Mapping[str, Any], *, live: bool) -> dict[str, Any]:
    figure = _signed(t["pnl_usd"]) if t["pnl_usd"] is not None else f"{t['pnl_sol']:+.4f} SOL"
    kind = "real money" if live else "pretend money"
    tone = "good" if t["result"] == "won" else "bad" if t["result"] == "lost" else "neutral"
    return _event(float(t["closed_at"]), "broker", "closed", f"{t['coin']}: {t['why']} · {t['result']} {figure} ({kind})",
                  tone)


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
        events.append(_event(float(f.get("ts") or start), "broker", "buy",
                             f"BUY {name} for {sol:.4f} SOL at {_price(_num(f.get('price_usd')))}", "neutral"))
    halts = _rows(ledger, "SELECT ts, kind, payload FROM receipts WHERE kind IN ('halt', 'kill', 'reset') "
                          "AND ts >= ? AND ts < ? ORDER BY seq LIMIT ?", [start, end, QUERY_CAP])
    total += len(halts)
    for ts, kind, payload in halts:
        p = _loads(payload)
        detail = plain(str(p.get("reason") or p.get("mode") or p.get("note") or "")).strip()
        what = {"halt": "stopped new buys", "kill": "the kill switch went on"}.get(str(kind), "the stop was reset")
        events.append(_event(float(ts), "risk", "halt", f"{what}: {detail}" if detail else what,
                             "neutral" if kind == "reset" else "bad"))
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


# --------------------------------------------------------------------------- the Polymarket desk's real money


def _question(questions: Mapping[str, str], slug: str) -> str:
    return questions.get(slug) or slug or "a market"


def _real_events(ledger: Any, start: float, end: float, questions: Mapping[str, str]
                 ) -> tuple[list[dict[str, Any]], list[tuple[float, float]]]:
    """The desk's real-money receipts of the day as events (in the desk's own wording, which the plain words know),
    and the day's real settlements ``[(ts, pnl_usd)]``."""
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
    return events, settled


def _real_block(ledger: Any, start: float, end: float, desk: Mapping[str, Any] | None,
                settled: list[tuple[float, float]]) -> dict[str, Any] | None:
    """``real`` (module docstring): null unless the desk has a real book. The result since start when the day began and
    when it ended: the money card's figure now minus the real settlements receipted since each moment."""
    real = _dict(_dict(desk).get("real")) if desk is not None else {}
    now_total = _num(real.get("since_start_usd"))
    if not real or now_total is None:
        return None
    later = _rows(ledger, "SELECT ts, payload FROM receipts WHERE kind = 'polydesk_settled' AND ts >= ? "
                          "ORDER BY seq LIMIT ?", [start, 20 * QUERY_CAP])
    pnls = [(float(ts), _num(_loads(payload).get("pnl_usd")) or 0.0) for ts, payload in later]
    start_usd = round(now_total - sum(pnl for _, pnl in pnls), 2)
    end_usd = round(now_total - sum(pnl for ts, pnl in pnls if ts >= end), 2)
    won = sum(1 for _, pnl in settled if pnl > 0)
    n = len(settled)
    finished = f"{won} of {n} finished bet{'' if n == 1 else 's'} won" if n else "no bet finished that day"
    line = (f"Real money: {_change(start_usd, real=True)} when the day began, {_change(end_usd, real=True)} when it "
            f"ended; {finished}.")
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


def _beats(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most :data:`RECAP_BEATS_MAX` events, shown in time order: the headline records first (real money, a halt,
    a closed trade: up to :data:`HEADLINE_MAX` of them, the most important first), then one of each other kind in rank
    order, a second of each, and so on, each kind's spread over the day."""
    ordered = sorted(events, key=lambda e: e["ts"])
    top = [e for e in ordered if _RANK.get(e["kind"], 9) <= 1]
    kept = sorted(top, key=lambda e: _RANK.get(e["kind"], 9))[:HEADLINE_MAX]  # (stable: in time order per rank)
    kinds: dict[str, list[dict[str, Any]]] = {}
    for ev in ordered:
        if _RANK.get(ev["kind"], 9) > 1:
            kinds.setdefault(ev["kind"], []).append(ev)
    queues = [_spread(kinds[k]) for k in sorted(kinds, key=lambda k: (_RANK.get(k, 9), k))]
    while len(kept) < RECAP_BEATS_MAX and any(queues):
        for queue in queues:
            if queue and len(kept) < RECAP_BEATS_MAX:
                kept.append(queue.pop(0))
    return sorted(kept, key=lambda e: e["ts"])


def build_recap(ledger: Any, now: float, *, tz: str, mode: str, words: Words, exit_words: Mapping[str, str],
                desk: Mapping[str, Any] | None = None, questions: Mapping[str, str] | None = None,
                text: Callable[[Any, int], str] | None = None) -> dict[str, Any]:
    """Yesterday's recap (schema in the module docstring) for the day before the one holding ``now`` in ``tz``.
    ``mode`` (``paper``/``live``) picks the Solana bot's trades and snapshots; ``words(member, text)`` puts a record in
    the page's plain words; ``exit_words`` the page's words for a trade's exit; ``desk`` the money card's Polymarket
    block (or None: the desk is off); ``questions`` the desk's questions by market (a receipt names the market only);
    ``text`` (optional) a redacting clipper applied to every line (the page passes its own, so a secret in a ledger
    text can never reach the film)."""
    date, start, end, zone = day_window(now, tz)
    clip: Callable[[Any, int], str] = text if text is not None else (lambda value, limit: _clip(str(value), limit))
    live = mode == "live"
    label = REAL_LABEL if live else PAPER_LABEL
    events, total = _solana_events(ledger, mode, start, end)
    real_events, settled = _real_events(ledger, start, end, questions or {})
    events += real_events
    total += len(real_events)
    closed = _closed_trades(ledger, mode, start, end, exit_words, label)
    total += len(closed)
    events += [_closed_event(t, live=live) for t in closed]
    real = _real_block(ledger, start, end, desk, settled)
    day = _solana_day(ledger, mode, start, end)
    solana = (f"the Solana bot ended the day {_day_change(day)}" if day is not None
              else "the Solana bot had no money check that day")
    pretend: dict[str, Any] | None = None
    if live:  # the bot itself trades real money: its day is real money, said with the real line
        sentence = "The Solana bot (real money): " + (f"ended the day {_day_change(day)}." if day is not None
                                                      else "no money check that day.")
        if real is None:
            real = {"label": REAL_LABEL, "start_usd": None, "end_usd": None, "settled": 0, "won": 0, "line": sentence}
        else:
            real["line"] += " " + sentence
    else:
        pretend = {"label": PRETEND_LABEL, "line": f"{PRETEND_LABEL}: {solana}."}
    return {
        "date": date, "tz": zone, "window": [start, end],
        "events": [{"ts": e["ts"], "member": e["member"], "text": clip(words(e["member"], e["text"]), TEXT_MAX),
                    "tone": e["tone"]} for e in _beats(events)],
        "events_total": total,
        "closed": [{"coin": clip(t["coin"], COIN_MAX), "closed_at": t["closed_at"], "pnl_usd": t["pnl_usd"],
                    "result": t["result"], "why": clip(t["why"], 60), "label": t["label"]}
                   for t in closed[-RECAP_CLOSED_MAX:]],
        "real": real,
        "pretend": pretend,
    }

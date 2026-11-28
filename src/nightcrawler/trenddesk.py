"""The trend desk: a PAPER forward test of lab 3's one consistently positive rule, "sma50" trend following on the
majors (``research/lab3/RESULTS.md``, T3), run inside the bot once a day so live evidence builds up.

PAPER ONLY. This module has no broker, no swap, no key and no wallet: it reads Coinbase's PUBLIC daily candles and
keeps a pretend book. Every label it produces says "Paper money (pretend)" (:data:`PAPER_LABEL`).

THE RULE (lab 3 PLAN §3-4, hypothesis T3, config ``sma50``: ``research/lab3/core.py`` ``backtest`` and
``hypotheses.py`` ``t2_signal``), re-implemented here because the Docker image ships ``src/`` only.
``tests/test_trenddesk.py`` runs the lab's own code on real candles and requires the same daily positions and the
same equity, bit for bit.

* Data: Coinbase Exchange public daily candles of BTC-USD, ETH-USD and SOL-USD (no key), the lab's own source. A
  bar is one UTC day (it opens at 00:00 UTC); its close is the price at the next 00:00 UTC. Only completed days.
* Signal at day t: close(t) > the mean of the 50 closes t-49 .. t (the 50-day simple moving average, t included; a
  missing bar inside the window means no signal). It reads closes up to t only (:func:`decide` is handed the rows up
  to t and nothing later).
* Universe at day t: the coin has a bar at t and the median of its last 30 days' dollar volume (at least 20 bars) is
  $1M or more. The lab's other entry filter (200 earlier bars) holds for the three majors by years; not re-checked.
* Position: long (1) when the signal is on and the coin is in the universe, else flat (0). Decided at t's close and
  held from t's close to t+1's close: the paper swap is at t's close price.
* A day on which NONE of the three has a candle is not in the desk's calendar (it is the union of the three coins'
  days): the desk carries its positions across it and books two days' move in one row. Lab 3's full 28-coin panel
  would keep such a day as a row without closes for the majors, drop them that day and keep them out for 50 days
  (their averages undefined). It has never happened in lab 3's data (no gap in the majors since 2016-05, no day
  missing for every coin); the parity test holds against a panel of the three majors, and on lab 3's full panel it
  holds bit for bit for every start since 2023-06-15.

THE BOOKS. Every swap costs lab 3's 25 bps of the amount traded plus a $0.02 network fee (:func:`swap_fee`).

* The rule's book (``sleeves``; ``equity_usd``, what the page shows): the paper sleeve is split into three separate
  thirds, one per coin, the way a real account would hold them. A buy spends that coin's third (all its cash) at the
  close; a sell turns that coin back into cash in its own third; nothing is ever moved between the thirds.
* Holding the three (``bh``; ``bh_usd``, the benchmark): each third bought at the record's first close (a coin without
  a candle that day at its next one), with the same costs, then never touched. The rule has to beat THAT, not zero.
* Lab 3's reckoning (``book`` / ``hold``; ``growth`` and ``lab_usd`` for the rule, ``hold_growth`` and
  ``lab_hold_usd`` for holding): the lab's backtest puts the book back to 1/n of each coin in the universe EVERY
  day, at no cost (n = the coins in the universe). Day t+1's return is the sum of (1/n) x position x
  (close(t+1) / close(t) - 1), minus the costs of t's swaps: 25 bps per side of the traded share of the book plus
  $0.02 per swap over the sleeve. The lab books a swap's cost in the NEXT day's return; ``lab_usd`` shows it on the
  day it is paid (growth x sleeve minus the fees of that close's swaps). These figures are kept bit for bit for the
  parity test and shown only as "lab 3's way (re-balanced to thirds daily, free)", never as the result: free daily
  re-balancing alone can decide which book is ahead (on lab 3's data from 2023-06-15 to 2026-10-08: the rule $393.45
  against re-balanced holding $376.95, but the rule in three thirds $370.21 against holding bought once $401.96).

FORWARD TEST. The record starts on the UTC day the desk first ran (``started``); its first swaps are at that day's
close, when the desk was already running. Nothing before it is ever booked or shown as earned. Days the bot was down
are caught up from the same closes at the next poll (the rule is mechanical, so the book is the one it would have
had); every booked day is sealed in the receipts chain when a ledger is attached. A saved record that cannot be read
is kept aside under a new name, and the new record says so for as long as it runs (``reset_from`` and an event).

Runtime (:class:`TrendDesk`, one daemon thread; a crash in it never reaches the trading loop): a poll at start-up,
then once a day shortly after 00:05 UTC. A poll fetches the last :data:`FETCH_DAYS` (more after a long pause) daily
candles of each coin, one request each through :class:`nightcrawler.http.HttpClient` (timeout, retries with
backoff), and books every completed day after the last booked one, up to the last day all three coins have a candle
(a candle that is late is waited for; a day missing for good is booked as the lab books a gap). A candle is read no
sooner than :data:`SETTLE_S` after its close, so a poll right after midnight (a redeploy, a retry, a host clock
running ahead) books nothing and the retry books the day. A failed fetch books nothing, keeps the state as it was
and says so (``last_error``); the desk then retries every :data:`RETRY_S` seconds. No price is ever made up.

State: ``DATA_DIR/trenddesk/state.json`` (atomic rewrite): the four books (the rule's thirds, holding the three, and
lab 3's two), per-coin positions with their entry price, the daily history (capped), the swaps (capped), events, the
last fetch and the last error. :func:`panel_state` reads only that file. The sleeve (``TRENDDESK_SLEEVE_USD``) is
fixed when the record starts.
"""

from __future__ import annotations

import json
import logging
import math
import os
import statistics
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nightcrawler.clock import RealClock, utc_day
from nightcrawler.config import Settings
from nightcrawler.http import HttpClient, HttpError

log = logging.getLogger("nightcrawler.trenddesk")

COINS: tuple[str, ...] = ("BTC", "ETH", "SOL")  # the lab's column order (sorted): sums run in this order
API = "https://api.exchange.coinbase.com"
HOST = "api.exchange.coinbase.com"
UA = "nightcrawler/trenddesk (paper desk; public market data)"
DAY_S = 86_400
GRANULARITY_S = 86_400
SMA_DAYS = 50
VOL_DAYS = 30
VOL_MIN_BARS = 20
MIN_VOL_USD = 1_000_000.0
COST_BPS_SIDE = 25.0  # one side, per unit of the book traded (lab 3 PLAN §3)
NETWORK_USD = 0.02  # per swap, on the sleeve
SWAP_EPS = 1e-12
FETCH_DAYS = 150  # >= 120: the 50-day average, the 30-day volume median, and slack
CONTEXT_DAYS = 90  # rows needed before the first day to book (50 + 30 + slack)
WINDOW_DAYS = 290  # one request: Coinbase serves at most 300 candles
MAX_FETCH_DAYS = 1200
POLL_AT_S = 5 * 60  # 00:05 UTC
RETRY_S = 15 * 60.0
FIRST_POLL_DELAY_S = 30.0
SETTLE_S = 120.0  # a daily candle is read no sooner than 2 minutes after its close (00:00 UTC)
BEHIND_GRACE_S = 3600.0  # a day's close not booked an hour after midnight counts as "behind"
HISTORY_KEEP = 800
TRADES_KEEP = 200
EVENTS_KEEP = 40
STATE_VERSION = 2  # 2: the rule's book in three thirds and holding bought once (1 re-balanced both daily)
PAPER_LABEL = "Paper money (pretend)"
RULE: dict[str, Any] = {
    "id": "lab3-T3-sma50",
    "coins": list(COINS),
    "sma_days": SMA_DAYS,
    "cost_bps_side": COST_BPS_SIDE,
    "network_usd": NETWORK_USD,
    "source": "Coinbase Exchange public daily candles (UTC days)",
    "label": "Lab 3 rule T3 sma50: hold a coin while its daily close is above its 50-day average, else cash; BTC, "
    "ETH and SOL, a third each. Its 2026 TEST look FAILED the pre-registered bar (promising, under-powered), so "
    "this desk is a paper forward test only, judged against holding the three (bought on day one, never touched)",
}

Row = tuple[str, dict[str, tuple[float | None, float | None]]]


# ---------------------------------------------------------------------- days
def day_start(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


def close_ts(day: str) -> float:
    """When ``day``'s bar closed: the next 00:00 UTC."""
    return day_start(day) + DAY_S


def _days_between(a: str, b: str) -> int:
    return round((day_start(b) - day_start(a)) / DAY_S)


# ---------------------------------------------------------------------- data (Coinbase public candles)
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_candles(rows: Any, now: float) -> dict[str, tuple[float, float]]:
    """Coinbase rows ``[time, low, high, open, close, volume]`` -> ``{day: (close, base volume)}``, completed UTC days
    only: the bar closed (the next 00:00 UTC) at least :data:`SETTLE_S` before ``now``, so a bar still open, or one
    read a moment after midnight (or on a host clock running ahead), is never used. A malformed row is dropped, never
    repaired."""
    if not isinstance(rows, list):
        raise TypeError("an unexpected reply")
    out: dict[str, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            ts, close, volume = float(row[0]), float(row[4]), float(row[5])
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (ts, close, volume)) or close <= 0 or volume < 0:
            continue
        if ts % DAY_S or ts + DAY_S + SETTLE_S > now:
            continue
        out[utc_day(ts)] = (close, volume)
    return out


def fetch_coin(http: HttpClient, coin: str, since: float, now: float) -> dict[str, tuple[float, float]]:
    """Every completed daily candle of ``coin``-USD from ``since`` (a 00:00 UTC) up to ``now``, in windows of at most
    :data:`WINDOW_DAYS` days (one request each). Raises :class:`HttpError` (or ``TypeError`` for a reply that is not a list) when Coinbase fails."""
    out: dict[str, tuple[float, float]] = {}
    start = since
    while start < now:
        end = min(start + WINDOW_DAYS * DAY_S, now)
        rows = http.get_json(
            f"{API}/products/{coin}-USD/candles",
            params={"granularity": GRANULARITY_S, "start": _iso(start), "end": _iso(end)},
        )
        out.update(parse_candles(rows, now))
        start = end
    return out


def calendar(candles: Mapping[str, Mapping[str, tuple[float, float]]]) -> list[Row]:
    """The union of the coins' days, oldest first (the lab's panel): a coin without a bar that day is ``None``."""
    days = sorted({d for per_coin in candles.values() for d in per_coin})
    rows: list[Row] = []
    for d in days:
        per: dict[str, tuple[float | None, float | None]] = {}
        for c in COINS:
            bar = candles.get(c, {}).get(d)
            per[c] = (bar[0], bar[1]) if bar is not None else (None, None)
        rows.append((d, per))
    return rows


def frontier(rows: Sequence[Row]) -> str | None:
    """The last day every coin has a candle: later days wait (a candle can be late); earlier gaps are real."""
    for d, per in reversed(rows):
        if all(per[c][0] is not None for c in COINS):
            return d
    return None


# ---------------------------------------------------------------------- the rule (lab 3 T3 sma50)
def sma_signal(closes: Sequence[float | None]) -> bool:
    """``closes`` ends at day t. True when close(t) > the 50-day simple moving average (t included); False when
    fewer than 50 rows or a missing bar in the window (the lab's rolling mean is then undefined)."""
    if len(closes) < SMA_DAYS:
        return False
    window = closes[-SMA_DAYS:]
    if any(c is None for c in window):
        return False
    values = [float(c) for c in window if c is not None]
    return values[-1] > math.fsum(values) / SMA_DAYS


def in_universe(bars: Sequence[tuple[float | None, float | None]]) -> bool:
    """``bars`` (close, base volume) end at day t: a bar at t and a 30-day median dollar volume >= $1M (>= 20 bars)."""
    if not bars or bars[-1][0] is None:
        return False
    usd = [c * v for c, v in bars[-VOL_DAYS:] if c is not None and v is not None]
    return len(usd) >= VOL_MIN_BARS and statistics.median(usd) >= MIN_VOL_USD


def decide(rows: Sequence[Row]) -> dict[str, tuple[bool, bool, str]]:
    """The decision at the LAST row's close, from these rows only: ``{coin: (in universe, signal on, why)}``. ``why``:
    ``above`` / ``below`` (the close against its 50-day average), ``gap`` (a missing bar in the 50 days), ``no_bar``
    (no candle that day), ``thin`` (under $1M a day lately)."""
    out: dict[str, tuple[bool, bool, str]] = {}
    for c in COINS:
        bars = [per[c] for _, per in rows[-max(SMA_DAYS, VOL_DAYS):]]
        closes = [b[0] for b in bars]
        universe = in_universe(bars)
        signal = sma_signal(closes)
        if bars[-1][0] is None:
            why = "no_bar"
        elif not universe:
            why = "thin"
        elif any(x is None for x in closes[-SMA_DAYS:]) or len(closes) < SMA_DAYS:
            why = "gap"
        else:
            why = "above" if signal else "below"
        out[c] = (universe, signal, why)
    return out


def fresh_book() -> dict[str, Any]:
    """A flat book before the first close: no position, no universe yet, no previous close."""
    return {
        "growth": 1.0,
        "target": {c: 0.0 for c in COINS},
        "held": {c: 0.0 for c in COINS},
        "universe": {c: False for c in COINS},
        "close": {c: None for c in COINS},
        "fee_frac": 0.0,
    }


def _weights(universe: Mapping[str, bool]) -> dict[str, float]:
    n = sum(1 for c in COINS if universe.get(c))
    return {c: (1.0 / n if n and universe.get(c) else 0.0) for c in COINS}


def _cost(weights: Mapping[str, float], delta: Mapping[str, float], sleeve: float) -> float:
    """The lab's cost of one day's swaps as a fraction of the book: turnover x 25 bps + swaps x the network fee
    over the sleeve (``core.backtest``: ``turnover * bps / 1e4 + n_swaps * network_usd / capital_usd``)."""
    turnover = 0.0
    swaps = 0
    for c in COINS:
        turnover += weights[c] * abs(delta[c])
        swaps += abs(delta[c]) > SWAP_EPS
    return turnover * COST_BPS_SIDE / 1e4 + swaps * NETWORK_USD / sleeve


def advance(book: Mapping[str, Any], closes: Mapping[str, float | None], target: Mapping[str, float],
            universe: Mapping[str, bool], sleeve: float) -> dict[str, Any]:
    """One day t for one book, as ``core.backtest`` computes it: the position decided at t-1's close is held over t
    (weights from t-1's universe), the swaps of t-1's close are charged, and t's decision (``target``, ``universe``)
    is recorded with the fee its swaps will cost (``fee_frac``, charged in day t+1's return). Returns the new book
    plus ``ret`` (day t's return after costs) and ``gross``."""
    held = {c: float(book["target"][c]) for c in COINS}
    prev_held = {c: float(book["held"][c]) for c in COINS}
    w = _weights(book["universe"])
    gross = 0.0
    for c in COINS:
        p0, p1 = book["close"][c], closes[c]
        r = p1 / p0 - 1.0 if p0 is not None and p1 is not None else 0.0
        gross += w[c] * held[c] * r
    cost = _cost(w, {c: held[c] - prev_held[c] for c in COINS}, sleeve)
    ret = gross - cost
    growth = float(book["growth"]) * (1.0 + ret)
    new_target = {c: float(target[c]) for c in COINS}
    new_universe = {c: bool(universe[c]) for c in COINS}
    fee_frac = _cost(_weights(new_universe), {c: new_target[c] - held[c] for c in COINS}, sleeve)
    return {
        "growth": growth,
        "target": new_target,
        "held": held,
        "universe": new_universe,
        "close": {c: closes[c] for c in COINS},
        "fee_frac": fee_frac,
        "ret": ret,
        "gross": gross,
    }


def _book_only(book: Mapping[str, Any]) -> dict[str, Any]:
    return {k: book[k] for k in ("growth", "target", "held", "universe", "close", "fee_frac")}


# ---------------------------------------------------------------------- the books a real account could keep
def fresh_thirds() -> dict[str, Any]:
    """Three separate thirds of the paper sleeve, one per coin, never re-balanced: ``cash`` (None until the record's
    first close funds it), ``units`` of the coin, and ``mark`` (the coin's last close seen: what the units are worth)."""
    return {"cash": {c: None for c in COINS}, "units": {c: 0.0 for c in COINS}, "mark": {c: None for c in COINS}}


def swap_fee(amount: float) -> float:
    """Lab 3's cost of one swap of ``amount`` dollars: 25 bps of it plus the $0.02 network fee (never more than the
    amount itself)."""
    return min(amount, amount * COST_BPS_SIDE / 1e4 + NETWORK_USD)


def thirds_value(thirds: Mapping[str, Any]) -> float:
    """What the three thirds are worth: each third's cash plus its units at the coin's last close."""
    return math.fsum(float(thirds["cash"][c] or 0.0) + float(thirds["units"][c]) * float(thirds["mark"][c] or 0.0)
                     for c in COINS)


def _mark(thirds: dict[str, Any], closes: Mapping[str, float | None], sleeve: float) -> None:
    """Fund the thirds at the record's first close (a third of the sleeve each) and mark them to the day's closes (a
    coin without a candle keeps its last close)."""
    for c in COINS:
        if thirds["cash"][c] is None:
            thirds["cash"][c] = sleeve / len(COINS)
        if closes[c] is not None:
            thirds["mark"][c] = closes[c]


def _swap(thirds: dict[str, Any], coin: str, side: str) -> tuple[float, float]:
    """One swap of one third at the coin's mark (the day's close): a buy spends all of that third's cash, a sell turns
    all of its units back into that third's cash. Returns ``(amount, fee)`` in dollars."""
    price = float(thirds["mark"][coin])
    if side == "buy":
        amount = float(thirds["cash"][coin] or 0.0)
        fee = swap_fee(amount)
        thirds["units"][coin] = float(thirds["units"][coin]) + (amount - fee) / price
        thirds["cash"][coin] = 0.0
    else:
        amount = float(thirds["units"][coin]) * price
        fee = swap_fee(amount)
        thirds["cash"][coin] = float(thirds["cash"][coin] or 0.0) + amount - fee
        thirds["units"][coin] = 0.0
    return amount, fee


# ---------------------------------------------------------------------- state
def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "rule": dict(RULE),
        "sleeve_usd": None,
        "started": None,
        "started_at": None,
        "last_day": None,
        "reset_from": None,  # the name an unreadable earlier record was kept under, when this record replaced it
        "sleeves": fresh_thirds(),  # the rule's book, three thirds (shown)
        "bh": fresh_thirds(),  # holding the three: bought at the first close, never touched (the benchmark)
        "book": fresh_book(),  # lab 3's reckoning of the rule (re-balanced daily, free; the parity test)
        "hold": fresh_book(),  # lab 3's reckoning of holding (likewise)
        "positions": {c: {"in": False, "since": None, "entry_price": None, "last_close": None} for c in COINS},
        "history": [],
        "trades": [],
        "events": [],
        "last_poll": None,
        "last_fetch": None,
        "last_ok": None,
        "last_error": None,
        "counters": {"polls": 0, "fetches": 0, "errors": 0, "days": 0, "swaps": 0},
    }


def load_state(path: Path) -> dict[str, Any]:
    """The state file, or an empty state when it is missing or unreadable (never raises)."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(doc, dict) or doc.get("version") != STATE_VERSION:
        return empty_state()
    base = empty_state()
    base.update(doc)
    return base


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":"), sort_keys=True, allow_nan=False))
    os.replace(tmp, path)


def state_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / "trenddesk" / "state.json"


def shown_equity(book: Mapping[str, Any], sleeve: float) -> float:
    """Lab 3's book after the swaps of its last close: the lab's equity less the fees those swaps cost."""
    equity = float(book["growth"]) * sleeve
    return equity - equity * float(book["fee_frac"])


def _event(state: dict[str, Any], ts: float, text: str, tone: str = "neutral") -> None:
    state["events"].insert(0, {"ts": ts, "text": text[:160], "tone": tone})
    del state["events"][EVENTS_KEEP:]


_FLIP_WORDS = {
    "above": "closed above its 50-day average -> in",
    "below": "closed below its 50-day average -> out",
    "gap": "has a missing daily candle in its last 50 days -> out",
    "no_bar": "has no daily candle for the day -> out",
    "thin": "traded under $1M a day lately -> out",
}


def book_day(state: dict[str, Any], rows: Sequence[Row]) -> dict[str, Any]:
    """Book the LAST of ``rows`` (day t) into ``state``: the rule decides at t's close from these rows only; its
    three thirds swap at t's close (logged with their fees); holding the three buys any third not bought yet; lab 3's
    two books advance one day; and the day joins the history. ``rows`` must reach back at least :data:`SMA_DAYS`
    rows. Returns the day's summary."""
    day, per = rows[-1]
    sleeve = float(state["sleeve_usd"])
    closes = {c: per[c][0] for c in COINS}
    decision = decide(rows)
    universe = {c: decision[c][0] for c in COINS}
    target = {c: 1.0 if decision[c][0] and decision[c][1] else 0.0 for c in COINS}
    hold_target = {c: 1.0 if universe[c] else 0.0 for c in COINS}
    rule = advance(state["book"], closes, target, universe, sleeve)
    hold = advance(state["hold"], closes, hold_target, universe, sleeve)
    state["book"], state["hold"] = _book_only(rule), _book_only(hold)
    thirds, bh = state["sleeves"], state["bh"]
    _mark(thirds, closes, sleeve)
    _mark(bh, closes, sleeve)
    for c in COINS:  # holding the three: each third bought at its first close, then never touched
        if float(bh["cash"][c] or 0.0) > 0.0 and closes[c] is not None:
            _swap(bh, c, "buy")
    ts = close_ts(day)
    swaps = []
    for c in COINS:
        if abs(target[c] - rule["held"][c]) <= SWAP_EPS:
            continue
        side = "buy" if target[c] > rule["held"][c] else "sell"
        price = thirds["mark"][c]  # the day's close; a coin without a candle sells at its last close
        amount, fee = _swap(thirds, c, side)
        swap = {"day": day, "ts": ts, "coin": c, "side": side, "price": price, "amount_usd": amount, "fee_usd": fee,
                "why": decision[c][2]}
        swaps.append(swap)
        state["trades"].insert(0, swap)
        pos = state["positions"][c]
        if side == "buy":
            state["positions"][c] = {"in": True, "since": day, "entry_price": price, "last_close": price}
        else:
            state["positions"][c] = {"in": False, "since": day, "entry_price": None, "exit_price": price,
                                     "entry_was": pos.get("entry_price"), "last_close": price}
        _event(state, ts, f"Trend desk: {c} {_FLIP_WORDS[decision[c][2]]} (paper)")
    del state["trades"][TRADES_KEEP:]
    for c in COINS:
        if closes[c] is not None:
            state["positions"][c]["last_close"] = closes[c]
    row = {
        "day": day,
        "ts": ts,
        "equity_usd": thirds_value(thirds),  # the rule's book in three thirds, after the close's swaps (shown)
        "bh_usd": thirds_value(bh),  # holding the three, bought on day one, never touched (the benchmark)
        "lab_usd": shown_equity(state["book"], sleeve),  # lab 3's way: re-balanced to thirds daily, free
        "lab_hold_usd": shown_equity(state["hold"], sleeve),
        "growth": state["book"]["growth"],
        "hold_growth": state["hold"]["growth"],
        "in": [c for c in COINS if target[c] > 0],
        "closes": closes,
    }
    state["history"].append(row)
    del state["history"][:-HISTORY_KEEP]
    state["last_day"] = day
    state["counters"]["days"] += 1
    state["counters"]["swaps"] += len(swaps)
    return {**row, "swaps": swaps, "ret": rule["ret"], "hold_ret": hold["ret"]}


def replay(rows: Sequence[Row], start: str, sleeve: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A fresh forward record started on ``start`` and booked over every row from ``start`` on, through
    :func:`book_day` (the runtime's own path; the parity test uses it). Returns (state, the day summaries)."""
    state = empty_state()
    state.update({"sleeve_usd": float(sleeve), "started": start})
    out = []
    for i, (day, _) in enumerate(rows):
        if day >= start:
            out.append(book_day(state, rows[: i + 1]))
    return state, out


# ---------------------------------------------------------------------- the runtime
def _next_poll_at(now: float) -> float:
    """The next 00:05 UTC after ``now``."""
    midnight = now - now % DAY_S
    at = midnight + POLL_AT_S
    return at if at > now else at + DAY_S


class TrendDesk:
    """The paper desk's runtime (one daemon thread). ``poll(now)`` is also callable directly (tests)."""

    def __init__(self, settings: Settings, path: Path | None = None, ledger: Any = None,
                 http: HttpClient | None = None) -> None:
        self.settings = settings
        self.ledger = ledger
        self.path = path or state_path(settings)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.http = http or HttpClient(clock=RealClock(self._stop), rate_limits={HOST: (3.0, 3)}, default_rate=None,
                                       timeout_s=20.0, max_retries=4, backoff_base_s=2.0, user_agent=UA)
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        """The saved record. A file that cannot be read (bad JSON, another state version) is kept aside under a new
        name (never overwritten) and a new record starts that says so for as long as it runs: ``reset_from`` names
        the kept file and an event tells the owner, so a restarted record never passes for the first one."""
        if not self.path.exists():
            return empty_state()
        state = load_state(self.path)
        if state.get("started") is not None or state.get("last_day") is not None:
            return state
        try:
            doc = json.loads(self.path.read_text())
            readable = isinstance(doc, dict) and doc.get("version") == STATE_VERSION
        except (OSError, ValueError):
            readable = False
        if readable:
            return state
        now = time.time()
        aside = self.path.with_name(f"state.unreadable-{int(now)}.json")
        try:
            os.replace(self.path, aside)
        except OSError as exc:
            log.warning("trenddesk_state_unreadable not_moved error=%s", type(exc).__name__)
            return state
        log.warning("trenddesk_state_unreadable kept_as=%s", aside.name)
        state = empty_state()
        state["reset_from"] = aside.name
        _event(state, now, f"Trend desk: the saved paper record could not be read; it was kept as {aside.name} and a "
                           "new record starts today (paper)", "bad")
        try:
            save_state(self.path, state)  # the restart is on file at once, even if the bot stops before a poll
        except OSError as exc:
            log.warning("trenddesk_state_save_failed error=%s", type(exc).__name__)
        return state

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="trenddesk", daemon=True)
        self._thread.start()
        log.info("trenddesk_started coins=%s sleeve_usd=%.2f (paper)", ",".join(COINS), self._sleeve())

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(FIRST_POLL_DELAY_S)  # a bot built and closed within seconds (tests) never touches the network
        while not self._stop.is_set():
            try:
                self.poll(time.time())
            except Exception as exc:  # noqa: BLE001 (a desk keeps going; the trading loop is unaffected)
                self.state["counters"]["errors"] += 1
                self.state["last_error"] = type(exc).__name__
                try:
                    self._save()
                except OSError:
                    pass
                log.warning("trenddesk_poll_failed error=%s", type(exc).__name__)
            self._stop.wait(max(5.0, self.next_wait(time.time())))

    def next_wait(self, now: float) -> float:
        """Seconds to the next poll: the next 00:05 UTC when the book is current, else :data:`RETRY_S`."""
        return _next_poll_at(now) - now if self.current(now) else RETRY_S

    def current(self, now: float) -> bool:
        """Every completed day since the start is booked (or the start day itself has not closed yet)."""
        st = self.state
        yesterday = utc_day(now - DAY_S)
        if st.get("last_day"):
            return str(st["last_day"]) >= yesterday
        return st.get("started") is not None and str(st["started"]) > yesterday

    def _sleeve(self) -> float:
        return float(self.state.get("sleeve_usd") or self.settings.trenddesk_sleeve_usd)

    def _save(self) -> None:
        save_state(self.path, self.state)

    def _receipt(self, kind: str, payload: dict[str, Any]) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.append_receipt(kind, payload)
        except Exception as exc:  # noqa: BLE001 (a receipt failure must not stop the desk)
            log.warning("trenddesk_receipt_failed kind=%s error=%s", kind, type(exc).__name__)

    # ------------------------------------------------------------------ one round
    def poll(self, now: float) -> dict[str, Any]:
        """Fetch the candles and book every completed day not booked yet. A failed fetch books nothing."""
        st = self.state
        st["counters"]["polls"] += 1
        st["last_poll"] = now
        if st.get("started") is None:  # the forward record starts the day the desk first runs
            st["started"] = utc_day(now)
            st["started_at"] = now
            st["sleeve_usd"] = float(self.settings.trenddesk_sleeve_usd)
            _event(st, now, f"Trend desk started (paper): first swaps at the close of {st['started']} (UTC midnight)")
        first = utc_day(day_start(st["last_day"]) + DAY_S) if st.get("last_day") else str(st["started"])
        gap_days = max(0, _days_between(first, utc_day(now)))
        days = min(MAX_FETCH_DAYS, max(FETCH_DAYS, gap_days + CONTEXT_DAYS))
        since = now - now % DAY_S - days * DAY_S
        candles: dict[str, dict[str, tuple[float, float]]] = {}
        try:
            for c in COINS:
                candles[c] = fetch_coin(self.http, c, since, now)
        except (HttpError, TypeError, ValueError) as exc:
            if isinstance(exc, HttpError):
                kind = str(exc).split(" [", 1)[0]
                reason = f"HTTP {exc.status}" if exc.status else ("no answer in time" if "Timeout" in kind
                                                                    else "no connection")
            else:
                reason = str(exc)[:60] or type(exc).__name__
            st["counters"]["errors"] += 1
            st["last_error"] = f"Coinbase candles not read ({reason}) at {_iso(now)}"
            self._save()
            log.warning("trenddesk_fetch_failed reason=%s", reason)
            return {"booked": 0, "error": st["last_error"]}
        st["counters"]["fetches"] += 1
        st["last_fetch"] = now
        rows = calendar(candles)
        edge = frontier(rows)
        booked = []
        problem = None
        for i, (day, _) in enumerate(rows):
            if day < first or edge is None or day > edge:
                continue
            if i < SMA_DAYS + VOL_DAYS:
                problem = f"not enough candle history before {day} to decide it"
                break
            if st.get("last_day") and rows[i - 1][0] != st["last_day"]:
                problem = f"the candles before {day} do not reach the last booked day {st['last_day']}"
                break
            summary = book_day(st, rows[: i + 1])
            booked.append(summary)
            self._receipt("trenddesk_day", {
                "day": day, "closes": summary["closes"], "in": summary["in"],
                **{k: round(summary[k], 6) for k in ("equity_usd", "bh_usd", "lab_usd", "lab_hold_usd")},
                "swaps": [{k: s[k] for k in ("coin", "side", "price", "fee_usd")} for s in summary["swaps"]],
            })
        if len(booked) > 1:
            _event(st, now, f"Trend desk caught up {len(booked)} daily closes after a pause (paper)")
        st["last_error"] = f"Cannot book: {problem}" if problem else None
        st["last_ok"] = now
        self._save()
        if booked:
            last = booked[-1]
            log.info("trenddesk_booked days=%d last=%s equity_usd=%.2f bh_usd=%.2f in=%s", len(booked),
                     last["day"], last["equity_usd"], last["bh_usd"], ",".join(last["in"]) or "-")
        return {"booked": len(booked), "last_day": st.get("last_day"), "error": st["last_error"]}


# ---------------------------------------------------------------------- the panel's view
def in_out_text(in_market: Mapping[str, bool]) -> str:
    """``in BTC and SOL, out of ETH`` / ``in BTC, ETH and SOL`` / ``out of BTC, ETH and SOL (all cash)``."""

    def names(coins: list[str]) -> str:
        return coins[0] if len(coins) == 1 else ", ".join(coins[:-1]) + " and " + coins[-1]

    ins = [c for c in COINS if in_market.get(c)]
    outs = [c for c in COINS if not in_market.get(c)]
    if not ins:
        return f"out of {names(outs)} (all cash)"
    return f"in {names(ins)}" + (f", out of {names(outs)}" if outs else "")


def panel_state(settings: Settings, now: float) -> dict[str, Any]:
    """What the page and the team room show for this desk (reads the state file only). Before the first close the
    figures are the untouched sleeve and ``as_of`` is None. ``problem`` says, in plain words, when the book is behind
    (the last daily close is not booked an hour after midnight) and why; None when it is current.

    The figures: ``equity_usd`` / ``today_usd`` / ``since_start_usd`` are the rule's book in three thirds (what a real
    account following it would hold); ``bh_*`` are holding the three, bought on day one and never touched (the
    benchmark); ``lab_*`` / ``lab_hold_*`` are lab 3's reckoning of both, re-balanced to thirds every day for free
    (for comparison with the lab only, never the result). ``reset_from`` names the unreadable earlier record this one
    replaced, else None."""
    st = load_state(state_path(settings))
    sleeve = float(st.get("sleeve_usd") or settings.trenddesk_sleeve_usd)
    hist = [h for h in st.get("history") or [] if isinstance(h, dict)]
    last = hist[-1] if hist else None
    prev = hist[-2] if len(hist) >= 2 else None

    def figure(key: str) -> tuple[float, float]:
        """(the last booked day's value, the day before's) of one book; the untouched sleeve before any."""
        return (float(last[key]) if last else sleeve), (float(prev[key]) if prev else sleeve)

    (equity, before), (bh, bh_before) = figure("equity_usd"), figure("bh_usd")
    (lab, _), (lab_hold, _) = figure("lab_usd"), figure("lab_hold_usd")
    positions = st.get("positions") or {}
    in_market = {c: bool((positions.get(c) or {}).get("in")) for c in COINS}
    last_day = st.get("last_day")
    started = st.get("started")
    expected = utc_day(now - DAY_S)  # the last completed UTC day
    due = (str(last_day) < expected) if last_day else (started is not None and str(started) <= expected)
    behind = bool(settings.trenddesk_enabled) and due and now - close_ts(expected) > BEHIND_GRACE_S
    problem = None
    if behind:
        held_at = f"the close of {last_day}" if last_day else "the sleeve (nothing booked yet)"
        why = st.get("last_error") or "the newest daily candles from Coinbase are not in yet"
        problem = f"Behind: the book stays at {held_at}; {why}. It retries every {int(RETRY_S // 60)} minutes."
    return {
        "enabled": bool(settings.trenddesk_enabled),
        "mode": "paper",
        "label": PAPER_LABEL,
        "rule": st.get("rule") or dict(RULE),
        "sleeve_usd": sleeve,
        "started": started,
        "started_at": st.get("started_at"),
        "last_day": last_day,
        "as_of": close_ts(str(last_day)) if last_day else None,
        "equity_usd": equity,
        "today_usd": equity - before if last else 0.0,
        "since_start_usd": equity - sleeve,
        "bh_usd": bh,
        "bh_today_usd": bh - bh_before if last else 0.0,
        "bh_since_start_usd": bh - sleeve,
        "lab_usd": lab,
        "lab_since_start_usd": lab - sleeve,
        "lab_hold_usd": lab_hold,
        "lab_hold_since_start_usd": lab_hold - sleeve,
        "reset_from": st.get("reset_from") if isinstance(st.get("reset_from"), str) else None,
        "in_market": in_market,
        "in_out": in_out_text(in_market),
        "positions": {c: dict(positions.get(c) or {}) for c in COINS},
        "trades": (st.get("trades") or [])[:10],
        "events": (st.get("events") or [])[:EVENTS_KEEP],
        "days": len(hist),
        "swaps_total": int((st.get("counters") or {}).get("swaps") or 0),
        "last_poll": st.get("last_poll"),
        "last_fetch": st.get("last_fetch"),
        "last_ok": st.get("last_ok"),
        "last_error": st.get("last_error"),
        "problem": problem,
    }

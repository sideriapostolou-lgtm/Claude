"""Lab 7 engine: in-and-out trading on lab 4's Polymarket tapes (research/lab7/PLAN.md, version lab7-v1).

The owner's idea (2026-10-10): specialists who buy at, say, 50c and sell at 55c, take profits, cut losses fast and
keep strict risk management. Labs 4-6 held every bet to settlement; lab 7 closes positions early (take profit, stop
loss, time stop). This module is the ONE simulator every hypothesis (W1-W4) uses, so the execution conventions are
written once and tested once (research/lab7/tests/test_core.py). Pure functions; nothing here talks to the network.

Conventions (PLAN §4, FIXED):

* **Tape.** One market's taker-side prints (lab 4's cache: ts, price, size, side, outcome_index), stored as the price
  of outcome 0 (``p0``) and ``buy0``: True when the print was a taker BUY on token 0 or a taker SELL on token 1 at
  ``1 - p``. A print is therefore BUYABLE for exactly one outcome (lab 4 Amendment 3) and SELLABLE (a taker sold
  into a bid) for the other: ``buyable(o) == sellable(1 - o)``. :func:`load_tape` reads one market at a time.
* **Decisions** use only prints with timestamps at or before the decision time; every fill is at a real print with
  ``ts >= decision + LATENCY_S`` (10 s), at THAT print's price (slippage is whatever the tape shows).
* **Taker BUY** (every entry): the first buyable print for the outcome at or after ``t_signal + 10 s``, within
  ``ENTRY_WINDOW_S`` (600 s) and before the market's entry deadline; none = "missed".
* **Taker SELL** (stop loss, taker take profit, time stop): the first SELLABLE print for the outcome at or after the
  trigger + 10 s and before ``hard_end``; the order is worked until it fills; none = held to settlement.
* **Maker (resting) limit SELL** (the take profit of the "maker" variant): posted at entry fill + 10 s at
  ``L = entry + tp`` (capped by the fair, see below); it fills only on a TRADE-THROUGH: a buyable print STRICTLY
  above ``L`` (a taker bought above our ask, so by price priority our ask was taken), once the buyable size at or
  above ``L`` since posting covers our order (lab 4 Amendment 4's size rule, mirrored). A print at exactly ``L``
  never fills it. It fills at ``L``. It is cancelled when the stop triggers or the time stop arrives.
* **Triggers.** The position is watched on every print strictly after the entry fill's second and strictly before
  the time stop: a print of the outcome at or above the take-profit target triggers the take profit (taker
  variant); at or below ``entry - sl`` triggers the stop. With ``fair_exit``, the target is ``min(entry + tp,
  fair)`` while the fair known at that print is above the entry price (``Market.fair``, built by the hypothesis
  from data at or before each print). A stop and a take profit on the same print: the stop wins.
* **Time stop.** ``min(entry fill + hold_s, Market.end_t)``. At a ``hold_s`` stop, or an ``end_t`` stop in mode
  "next": a taker SELL at the first sellable print at or after the stop + 10 s. Mode "last_before" (W1, the
  scheduled start): the LAST sellable print in ``[entry fill + 10 s, end_t)``; if there is none, "next" (flagged
  ``late_stop``). Mode "settle": no exit after ``end_t``, the position is held to settlement. A market's ``end_t``
  stop or a settlement ends that market's trading in the cell (no re-entry after it).
* **Settlement**: ``shares x payout[o]`` at ``settle_t``, no fee.
* **Fees per leg** (``contracts x rate x p x (1 - p)``), three schemes: ``us`` (Polymarket US taker 0.0695 on every
  taker leg, maker legs 0: the venue's maker rebate is never counted; SELECTS), ``com`` (polymarket.com's family
  rate on taker legs, maker 0; a reading) and ``stress`` (max(0.0695, family rate) on EVERY leg, maker legs
  included; must stay positive).
* **Sizing and walking.** $20 per position (``shares = 20 / entry price``); one position per market at a time; a new
  signal is taken only strictly after the previous exit fill (or 600 s after a missed entry). :func:`walk`.

Readings: :func:`summarize` (event-bootstrap CI95, fee schemes, exit mix, cents per contract, break-even win rate)
and :func:`risk_book` (max open positions, a $10 daily loss stop overlay, max drawdown, worst day, daily Sharpe).
Bar: :func:`bar` (n >= 100, mean > 0, CI95 lower > 0, stress > 0, lab 4's loss guards, beats the random-entry
placebo of :func:`placebo_matrix` / :func:`placebo_reading`). :func:`select_one`, the split guard
(:func:`check_split_allowed`, :func:`first_test_look`) and the trial ledger (:func:`record_run`,
:func:`trials_count`).
"""

from __future__ import annotations

import hashlib
import heapq
import importlib.util
import json
import math
import os
import sys
import time
import zlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
LEDGER = HERE / "trials.json"
SIBLING_LEDGERS = tuple(HERE.parent / lab / "trials.json" for lab in ("lab2", "lab3", "lab4", "lab5", "lab6"))
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD",
        "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad",
    )
)
LAB4_DATA = Path(os.environ.get("LAB4_DATA", str(SCRATCH / "lab4")))
TRADES_DIR = LAB4_DATA / "trades"
OUT = Path(os.environ.get("LAB7_DATA", str(SCRATCH / "lab7")))  # per-trade files of selected cells only


def _load_lab4_core() -> Any:
    """Lab 4's engine under its own module name, so lab 7 shares its splits, fee families and event bootstrap."""
    if "lab4_core" in sys.modules:
        return sys.modules["lab4_core"]
    spec = importlib.util.spec_from_file_location("lab4_core", HERE.parent / "lab4" / "core.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lab4_core"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


L4 = _load_lab4_core()

SPLITS: dict[str, tuple[str, str]] = dict(L4.SPLITS)  # lab 4's, on closedTime (UTC), half-open
TICKET_USD = 20.0
LATENCY_S = 10.0
ENTRY_WINDOW_S = 600.0  # lab 4's execution window for an entry
US_RATE = 0.0695  # Polymarket US taker feeCoefficient (lab 4 Amendment 2; research/lab4/VENUES.md)
MAKER_RATE = 0.0  # both venues: makers pay no fee (VENUES.md); the US maker rebate is never counted as income
MAX_PRICE = 0.999
EPS = 1e-9
BOOTSTRAP_B = 2000
PLACEBO_DRAWS = 200
PLACEBO_PCT = 95.0
PLACEBO_TRIES = 25
MIN_N = 100
DAILY_LOSS_STOP_USD = 10.0
FEE_SCHEMES = ("us", "com", "stress")
END_MODES = ("next", "last_before", "settle")
TP_MODES = ("taker", "maker")
DAY_S = 86400.0


# --------------------------------------------------------------------------------------------- splits and guards


def split_bounds(split: str) -> tuple[float, float]:
    return L4.split_bounds(split)


def split_of(closed_time: float) -> str | None:
    """The split of a market (and of every trade in it): lab 4's, by the market's closedTime."""
    for name in SPLITS:
        lo, hi = split_bounds(name)
        if lo <= float(closed_time) < hi:
            return name
    return None


def check_split_allowed(split: str) -> None:
    """TEST is one look and refuses without LAB7_ALLOW_TEST=1 (PLAN §3)."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    if split == "test" and os.environ.get("LAB7_ALLOW_TEST") != "1":
        raise PermissionError("TEST is a one-look split: set LAB7_ALLOW_TEST=1 to read it (research/lab7/PLAN.md §3)")


def first_test_look(result_path: Path) -> None:
    """Refuses a second TEST look: a hypothesis's ``test.json`` existing means TEST was already read."""
    check_split_allowed("test")
    if Path(result_path).exists():
        raise PermissionError(f"TEST was already read once ({result_path}); a second look is not allowed")


def prereg_sha256(path: Path = PLAN) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else "none"


# --------------------------------------------------------------------------------------------- tapes


@dataclass
class Tape:
    """One market's prints in time order. ``buy0[i]``: print i was buyable for outcome 0 (a taker BUY on token 0 or
    a taker SELL on token 1); otherwise it was buyable for outcome 1 and sellable for outcome 0."""

    ts: np.ndarray  # float64 seconds, ascending
    p0: np.ndarray  # price of outcome 0
    buy0: np.ndarray  # bool
    size: np.ndarray  # shares

    def __len__(self) -> int:
        return len(self.ts)

    @classmethod
    def from_raw(cls, df: pd.DataFrame) -> Tape:
        """Lab 4's cache format (ts, price, size, side, outcome_index) -> a Tape; invalid prints are dropped and the
        order within one second is kept as the venue reported it (stable sort)."""
        t = df[(df["ts"] > 0) & (df["price"] > 0) & (df["price"] < 1) & df["outcome_index"].isin([0, 1])]
        t = t.sort_values("ts", kind="stable")
        oi = t["outcome_index"].to_numpy()
        side = t["side"].astype(str).str.upper().to_numpy()
        price = t["price"].to_numpy(dtype=float)
        return cls(
            ts=t["ts"].to_numpy(dtype=float),
            p0=np.where(oi == 0, price, 1.0 - price),
            buy0=((oi == 0) & (side == "BUY")) | ((oi == 1) & (side == "SELL")),
            size=t["size"].to_numpy(dtype=float),
        )

    @classmethod
    def from_prints(cls, rows: Iterable[tuple[float, int, str, float, float]]) -> Tape:
        """Hand-made tapes for tests: rows of (ts, outcome_index, side, price, size)."""
        df = pd.DataFrame(list(rows), columns=["ts", "outcome_index", "side", "price", "size"])
        return cls.from_raw(df)

    def price(self, o: int) -> np.ndarray:
        return self.p0 if o == 0 else 1.0 - self.p0

    def buyable(self, o: int) -> np.ndarray:
        return self.buy0 if o == 0 else ~self.buy0

    def sellable(self, o: int) -> np.ndarray:
        return ~self.buyable(o)

    def until(self, t: float) -> Tape:
        """The tape as known at time ``t`` (prints at or before ``t``): the lookahead tests compare against it."""
        k = int(np.searchsorted(self.ts, t, side="right"))
        return Tape(self.ts[:k], self.p0[:k], self.buy0[:k], self.size[:k])


def load_tape(market_id: str, trades_dir: Path = TRADES_DIR, min_fills: int = 0) -> Tape | None:
    """ONE market's tape (the cache is 7.6 GB: never load all of it); None if absent or below ``min_fills``."""
    path = Path(trades_dir) / f"{market_id}.parquet"
    if not path.exists():
        return None
    tape = Tape.from_raw(pd.read_parquet(path, columns=["ts", "price", "size", "side", "outcome_index"]))
    return tape if len(tape) >= min_fills else None


def iter_tapes(ids: Iterable[str], trades_dir: Path = TRADES_DIR, min_fills: int = 0) -> Iterator[tuple[str, Tape]]:
    """Tapes one at a time (memory stays at one market)."""
    for mid in ids:
        tape = load_tape(str(mid), trades_dir, min_fills)
        if tape is not None:
            yield str(mid), tape


# --------------------------------------------------------------------------------------------- fills


def taker_buy_index(
    tape: Tape,
    o: int,
    t_decision: float,
    deadline: float,
    latency_s: float = LATENCY_S,
    window_s: float = ENTRY_WINDOW_S,
) -> int | None:
    """The first BUYABLE print for ``o`` with ``t_decision + latency <= ts <= t_decision + window`` and ``ts <
    deadline``; None = missed. A sellable (bid-side) print never fills a buy."""
    ts = tape.ts
    lo = int(np.searchsorted(ts, t_decision + latency_s, side="left"))
    hi = min(int(np.searchsorted(ts, t_decision + window_s, side="right")), int(np.searchsorted(ts, deadline, "left")))
    if hi <= lo:
        return None
    ok = tape.buyable(o)[lo:hi]
    return lo + int(np.argmax(ok)) if ok.any() else None


def taker_sell_index(tape: Tape, o: int, t_decision: float, hard_end: float, latency_s: float = LATENCY_S) -> int | None:
    """The first SELLABLE print for ``o`` (a taker sold into a bid) with ``ts >= t_decision + latency`` and ``ts <
    hard_end``; the exit order is worked until then. A buyable (ask-side) print never fills a sell."""
    ts = tape.ts
    lo = int(np.searchsorted(ts, t_decision + latency_s, side="left"))
    hi = int(np.searchsorted(ts, hard_end, side="left"))
    if hi <= lo:
        return None
    ok = tape.sellable(o)[lo:hi]
    return lo + int(np.argmax(ok)) if ok.any() else None


def last_sellable_before(tape: Tape, o: int, t_from: float, t_before: float) -> int | None:
    """The LAST sellable print for ``o`` with ``t_from <= ts < t_before`` (W1's time stop at the scheduled start)."""
    ts = tape.ts
    lo = int(np.searchsorted(ts, t_from, side="left"))
    hi = int(np.searchsorted(ts, t_before, side="left"))
    if hi <= lo:
        return None
    ok = tape.sellable(o)[lo:hi]
    if not ok.any():
        return None
    return lo + (hi - lo - 1) - int(np.argmax(ok[::-1]))


def maker_sell_index(tape: Tape, o: int, t_post: float, limit: float, shares: float, until: float) -> int | None:
    """A resting SELL of ``shares`` of ``o`` at ``limit``, live for prints with ``t_post < ts < until``: filled by
    the first buyable print STRICTLY above the limit (a trade-through) once the buyable size at or above the limit
    since posting covers the order. A print at exactly the limit never fills it."""
    if not math.isfinite(limit) or limit >= 1.0:
        return None
    ts = tape.ts
    lo = int(np.searchsorted(ts, t_post, side="right"))
    hi = int(np.searchsorted(ts, until, side="left"))
    if hi <= lo:
        return None
    buy = tape.buyable(o)[lo:hi]
    px = tape.price(o)[lo:hi]
    at_or_above = buy & (px >= limit - EPS)
    through = buy & (px > limit + EPS)
    cum = np.cumsum(np.where(at_or_above, tape.size[lo:hi], 0.0))
    fill = through & (cum >= shares - EPS)
    return lo + int(np.argmax(fill)) if fill.any() else None


def maker_buy_index(tape: Tape, o: int, t_post: float, limit: float, shares: float, until: float) -> int | None:
    """The mirror: a resting BUY at ``limit`` fills on the first SELLABLE print strictly below it once the sellable
    size at or below it since posting covers the order (lab 4 Amendment 4). Not in lab 7's grid; kept for symmetry
    and tested."""
    ts = tape.ts
    lo = int(np.searchsorted(ts, t_post, side="right"))
    hi = int(np.searchsorted(ts, until, side="left"))
    if hi <= lo:
        return None
    sell = tape.sellable(o)[lo:hi]
    px = tape.price(o)[lo:hi]
    at_or_below = sell & (px <= limit + EPS)
    through = sell & (px < limit - EPS)
    cum = np.cumsum(np.where(at_or_below, tape.size[lo:hi], 0.0))
    fill = through & (cum >= shares - EPS)
    return lo + int(np.argmax(fill)) if fill.any() else None


# --------------------------------------------------------------------------------------------- fees


def leg_fee(shares: float, price: float, rate: float) -> float:
    """``contracts x rate x p x (1 - p)`` (Polymarket's formula on both venues)."""
    return float(shares) * float(rate) * float(price) * (1.0 - float(price))


def leg_fees(shares: float, p_entry: float, p_exit: float, exit_leg: str, rate_com: float) -> dict[str, float]:
    """Total fee in $ under each scheme. Entry is always a taker leg; ``exit_leg`` is 'taker', 'maker' or 'settle'
    (redemption is free)."""
    stress = max(US_RATE, float(rate_com))
    rates = {
        "us": (US_RATE, US_RATE if exit_leg == "taker" else MAKER_RATE),
        "com": (float(rate_com), float(rate_com) if exit_leg == "taker" else MAKER_RATE),
        "stress": (stress, stress),
    }
    out = {}
    for scheme, (r_in, r_out) in rates.items():
        fee = leg_fee(shares, p_entry, r_in)
        if exit_leg != "settle":
            fee += leg_fee(shares, p_exit, r_out)
        out[scheme] = fee
    return out


# --------------------------------------------------------------------------------------------- markets and exits


@dataclass(frozen=True)
class Exits:
    """One cell's exit rule. ``tp`` / ``sl``: distances in price points from the entry fill (None = none);
    ``tp_mode``: 'taker' (trigger, then a taker sell) or 'maker' (a resting limit sell, trade-through fills);
    ``fair_exit``: the target is capped by the fair while the fair is above the entry; ``hold_s``: time stop from
    the entry fill (None = only the market's ``end_t``); ``hold_to_settlement``: the reference rule (no exit)."""

    tp: float | None = None
    sl: float | None = None
    tp_mode: str = "taker"
    fair_exit: bool = False
    hold_s: float | None = None
    hold_to_settlement: bool = False

    def __post_init__(self) -> None:
        if self.tp_mode not in TP_MODES:
            raise ValueError(f"tp_mode {self.tp_mode!r}")
        for name in ("tp", "sl", "hold_s"):
            v = getattr(self, name)
            if v is not None and not v > 0:
                raise ValueError(f"{name} must be > 0 or None")


@dataclass
class Market:
    """What the simulator needs to know about one market, built by the hypothesis's runner (PLAN §5).

    ``entry_windows``: half-open intervals where an entry decision may be taken (the random-entry placebo draws its
    times from the same set). ``entry_deadline``: an entry fill must come before it. ``end_t`` / ``end_mode``: the
    market's own time stop. ``hard_end``: no fill at or after it (closedTime or the settlement instant).
    ``payout``: settlement value per share of outcome 0 and 1. ``fair``: shape (2, len(tape)), the fair probability
    of each outcome KNOWN at each print (NaN = unknown), computed from data at or before that print. ``band``: the
    allowed price of the bought outcome at the decision."""

    id: str
    event: str
    split: str | None
    tape: Tape
    rate_com: float
    payout: tuple[float, float]
    settle_t: float
    hard_end: float
    entry_windows: tuple[tuple[float, float], ...]
    entry_deadline: float
    end_t: float
    end_mode: str
    fair: np.ndarray | None = None
    band: tuple[float, float] = (0.0, 1.0)
    info: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.end_mode not in END_MODES:
            raise ValueError(f"end_mode {self.end_mode!r}")
        if self.fair is not None and np.shape(self.fair) != (2, len(self.tape)):
            raise ValueError("fair must have shape (2, len(tape))")
        if self.entry_deadline > self.end_t:
            raise ValueError("entry_deadline must not be after end_t (a time stop would precede the entry)")
        self.entry_windows = tuple(
            (float(a), float(min(b, self.entry_deadline))) for a, b in self.entry_windows if min(b, self.entry_deadline) > a
        )


def in_windows(ts: np.ndarray, windows: Sequence[tuple[float, float]]) -> np.ndarray:
    ok = np.zeros(len(ts), dtype=bool)
    for a, b in windows:
        ok |= (ts >= a) & (ts < b)
    return ok


TRIP_COLUMNS = [
    "id", "event", "split", "o", "t_signal", "p_signal", "t_entry", "p_entry", "shares", "entry_print_size",
    "t_trigger", "t_exit", "p_exit", "reason", "exit_leg", "late_stop", "hold_s", "fee_us", "fee_com", "fee_stress",
    "pnl_us", "pnl_com", "pnl_stress", "net_us", "net_com", "net_stress", "day",
]


def _day(t: float) -> str:
    return datetime.fromtimestamp(float(t), UTC).strftime("%Y-%m-%d")


def simulate(
    mk: Market,
    o: int,
    t_signal: float,
    ex: Exits,
    p_signal: float | None = None,
    ticket: float = TICKET_USD,
    latency_s: float = LATENCY_S,
) -> dict[str, Any] | None:
    """One round trip of outcome ``o`` decided at ``t_signal`` (PLAN §4). None = the entry was missed."""
    tape = mk.tape
    ts, px = tape.ts, tape.price(o)
    deadline = min(mk.entry_deadline, mk.hard_end)
    i_e = taker_buy_index(tape, o, t_signal, deadline, latency_s)
    if i_e is None:
        return None
    p_e = min(float(px[i_e]), MAX_PRICE)
    t_e = float(ts[i_e])
    shares = ticket / p_e
    t_trig: float | None = None
    late = False
    k: int | None = None
    exit_leg, reason, p_x = "settle", "settle", float(mk.payout[o])
    closes_market = False  # an end_t stop or a settlement ends the market's trading in this cell

    if ex.hold_to_settlement:
        closes_market = True
    else:
        if ex.hold_s is not None and t_e + ex.hold_s < mk.end_t:
            T, mode = t_e + ex.hold_s, "next"
        else:
            T, mode = mk.end_t, mk.end_mode
            closes_market = True
        T = max(T, t_e)  # never a stop before the entry fill
        a = int(np.searchsorted(ts, t_e, side="right"))  # strictly after the entry fill's second
        b = max(a, int(np.searchsorted(ts, T, side="left")))  # strictly before the time stop
        seg = px[a:b]
        stop = p_e - ex.sl if ex.sl is not None else -math.inf
        sl_hits = np.flatnonzero(seg <= stop + EPS)
        j_sl = int(sl_hits[0]) if len(sl_hits) else None
        base = p_e + ex.tp if ex.tp is not None else math.inf
        triggered: tuple[int, str] | None = None
        maker_fill: tuple[int, float, str] | None = None
        if ex.tp_mode == "taker":
            tgt = np.full(b - a, base)
            if ex.fair_exit and mk.fair is not None:
                f = mk.fair[o, a:b]
                act = np.isfinite(f) & (f > p_e + EPS)
                tgt = np.where(act, np.minimum(tgt, f), tgt)
            tp_hits = np.flatnonzero(seg >= tgt - EPS)
            j_tp = int(tp_hits[0]) if len(tp_hits) else None
            if j_sl is not None and (j_tp is None or j_sl <= j_tp):
                triggered = (j_sl, "sl")
            elif j_tp is not None:
                triggered = (j_tp, "fair" if tgt[j_tp] < base - EPS else "tp")
        else:
            t_post = t_e + latency_s
            limit, why = base, "tp"
            if ex.fair_exit and mk.fair is not None:
                q = int(np.searchsorted(ts, t_post, side="right")) - 1
                f_post = float(mk.fair[o, q]) if q >= 0 else math.nan
                if math.isfinite(f_post) and f_post > p_e + EPS and f_post < limit:
                    limit, why = f_post, "fair"
            until = float(ts[a + j_sl]) if j_sl is not None else T
            km = maker_sell_index(tape, o, t_post, limit, shares, until) if math.isfinite(limit) else None
            if km is not None:
                maker_fill = (km, limit, why)
            elif j_sl is not None:
                triggered = (j_sl, "sl")
        if maker_fill is not None:
            k, p_x, reason, exit_leg = maker_fill[0], float(maker_fill[1]), maker_fill[2], "maker"
            closes_market = False
        elif triggered is not None:
            t_trig = float(ts[a + triggered[0]])
            reason = triggered[1]
            closes_market = False
            k = taker_sell_index(tape, o, t_trig, mk.hard_end, latency_s)
            if k is None:
                closes_market = True
        else:
            t_trig = T
            reason = "time"
            if mode == "next":
                k = taker_sell_index(tape, o, T, mk.hard_end, latency_s)
            elif mode == "last_before":
                k = last_sellable_before(tape, o, t_e + latency_s, min(T, mk.hard_end))
                if k is None:
                    late = True
                    k = taker_sell_index(tape, o, T, mk.hard_end, latency_s)
            else:  # "settle"
                k = None
                reason = "settle"
        if k is not None and exit_leg != "maker":
            p_x, exit_leg = float(px[k]), "taker"
        elif k is None:
            exit_leg, p_x = "settle", float(mk.payout[o])
            if reason not in ("settle",):
                reason = reason + "->settle"  # a triggered exit that never found a bid before the end
            closes_market = True

    t_x = float(ts[k]) if k is not None else float(mk.settle_t)
    fees = leg_fees(shares, p_e, p_x, exit_leg, mk.rate_com)
    pnl = {s: shares * p_x - ticket - fees[s] for s in FEE_SCHEMES}
    return {
        "id": mk.id,
        "event": mk.event,
        "split": mk.split,
        "o": int(o),
        "t_signal": float(t_signal),
        "p_signal": float(p_signal) if p_signal is not None else math.nan,
        "t_entry": t_e,
        "p_entry": p_e,
        "shares": shares,
        "entry_print_size": float(tape.size[i_e]),
        "t_trigger": t_trig if t_trig is not None else math.nan,
        "t_exit": t_x,
        "p_exit": p_x,
        "reason": reason,
        "exit_leg": exit_leg,
        "late_stop": late,
        "hold_s": t_x - t_e,
        **{f"fee_{s}": fees[s] for s in FEE_SCHEMES},
        **{f"pnl_{s}": pnl[s] for s in FEE_SCHEMES},
        **{f"net_{s}": pnl[s] / ticket for s in FEE_SCHEMES},
        "day": _day(t_x),
        "_closes_market": closes_market,
    }


def walk(mk: Market, sig: np.ndarray, ex: Exits) -> tuple[list[dict[str, Any]], int]:
    """Every round trip of one cell in one market: ``sig[i]`` (-1 none, 0 / 1 the outcome to buy) is the
    hypothesis's signal at print i, computed from prints at or before it. A signal counts only inside the entry
    windows and with the bought outcome's print price inside the band; it is taken only strictly after the previous
    exit fill (600 s after a missed entry). Returns (trips, missed)."""
    ts = mk.tape.ts
    sig = np.asarray(sig)
    if len(sig) != len(ts):
        raise ValueError("one signal per print")
    o_arr = np.where(sig == 1, 1, 0)
    p_sig = np.where(o_arr == 0, mk.tape.p0, 1.0 - mk.tape.p0)
    lo, hi = mk.band
    ok = (sig >= 0) & in_windows(ts, mk.entry_windows) & (p_sig >= lo - EPS) & (p_sig <= hi + EPS)
    cand = np.flatnonzero(ok)
    cts = ts[cand]
    trips: list[dict[str, Any]] = []
    missed = 0
    t_free = -math.inf
    while True:
        j = int(np.searchsorted(cts, t_free, side="right"))
        if j >= len(cand):
            break
        i = int(cand[j])
        rt = simulate(mk, int(o_arr[i]), float(ts[i]), ex, p_signal=float(p_sig[i]))
        if rt is None:
            missed += 1
            t_free = float(ts[i]) + ENTRY_WINDOW_S
            continue
        closes = rt.pop("_closes_market")
        trips.append(rt)
        if closes:
            break
        t_free = rt["t_exit"]
    return trips, missed


def trips_frame(trips: Sequence[dict[str, Any]]) -> pd.DataFrame:
    rows = [{k: v for k, v in t.items() if not k.startswith("_")} for t in trips]
    return pd.DataFrame(rows, columns=TRIP_COLUMNS)


# --------------------------------------------------------------------------------------------- signals


def gap_signals(tape: Tape, fair: np.ndarray, m: float) -> np.ndarray:
    """W1 / W2 entry signal: at each print, the outcome it was buyable for, when that outcome's fair (known at the
    print) exceeds the print price by at least ``m``. -1 elsewhere."""
    o = np.where(tape.buy0, 0, 1)
    p = np.where(o == 0, tape.p0, 1.0 - tape.p0)
    f = np.where(o == 0, fair[0], fair[1])
    hit = np.isfinite(f) & (f - p >= m - EPS)
    return np.where(hit, o, -1).astype(np.int8)


def swing_signals(tape: Tape, x: float, y_s: float, k: int, direction: str) -> np.ndarray:
    """W3 / W4 entry signal from price action only. At print i: the reference is the last print at or before
    ``ts[i] - y_s``; the move is outcome 0's price at print i minus at the reference; at least ``k`` prints after the
    reference up to print i (same-second prints AFTER i are never read). 'mom' buys the outcome that rose by >= x,
    'fade' buys the outcome that fell by >= x. -1 elsewhere."""
    if direction not in ("mom", "fade"):
        raise ValueError(direction)
    ts, p0 = tape.ts, tape.p0
    n = len(ts)
    out = np.full(n, -1, dtype=np.int8)
    if n == 0:
        return out
    r = np.searchsorted(ts, ts - y_s, side="right") - 1
    idx = np.arange(n)
    have = r >= 0
    rr = np.where(have, r, 0)
    move = p0 - p0[rr]
    enough = have & (idx - rr >= k)
    up = enough & (move >= x - EPS)
    down = enough & (move <= -x + EPS)
    if direction == "mom":
        out[up], out[down] = 0, 1
    else:
        out[up], out[down] = 1, 0
    return out


# --------------------------------------------------------------------------------------------- placebo


def _draw_times(windows: Sequence[tuple[float, float]], rng: np.random.Generator, n: int) -> np.ndarray:
    lens = np.array([max(0.0, b - a) for a, b in windows], dtype=float)
    total = float(lens.sum())
    if total <= 0 or n == 0:
        return np.full(n, np.nan)
    cum = np.cumsum(lens)
    r = rng.random(n) * total
    w = np.minimum(np.searchsorted(cum, r, side="right"), len(lens) - 1)
    starts = np.array([a for a, _ in windows], dtype=float)
    return starts[w] + (r - (cum[w] - lens[w]))


def placebo_matrix(
    mk: Market,
    n_trips: int,
    ex: Exits,
    draws: int = PLACEBO_DRAWS,
    rng: np.random.Generator | None = None,
    tries: int = PLACEBO_TRIES,
) -> np.ndarray:
    """The random-entry placebo for one market (PLAN §7): for each of the market's ``n_trips`` real round trips,
    ``draws`` counterparts in the SAME market with the SAME exits, whose decision time is drawn uniformly from the
    market's entry windows and whose outcome is drawn 50 / 50 (redrawn up to ``tries`` times while the entry misses
    or the drawn outcome's last price at the drawn time is outside the band). The side is drawn, not copied: a
    copied side would carry the real signal's hindsight into entries drawn before that signal. Counterparts are
    independent (they may overlap). Returns (draws, n_trips) of net per $ under the US fee; NaN = dropped."""
    rng = rng or np.random.default_rng(0)
    out = np.full((draws, int(n_trips)), np.nan)
    ts = mk.tape.ts
    lo, hi = mk.band
    prices = (mk.tape.price(0), mk.tape.price(1))
    for j in range(int(n_trips)):
        for d in range(draws):
            times = _draw_times(mk.entry_windows, rng, tries)
            sides = rng.integers(0, 2, tries)
            for u, o in zip(times, sides, strict=True):
                if not math.isfinite(u):
                    break
                q = int(np.searchsorted(ts, u, side="right")) - 1
                if q < 0 or not (lo - EPS <= prices[o][q] <= hi + EPS):
                    continue
                rt = simulate(mk, int(o), float(u), ex, p_signal=float(prices[o][q]))
                if rt is not None:
                    out[d, j] = rt["net_us"]
                    break
    return out


def placebo_reading(blocks: Sequence[np.ndarray], real_mean: float, pct: float = PLACEBO_PCT) -> dict[str, Any]:
    """Combine the per-market placebo matrices: one mean per draw over every counterpart that filled."""
    blocks = [b for b in blocks if b.size]
    if not blocks:
        return {"draws": 0, "p95": None, "mean": None, "real_percentile": None, "drop_share": None}
    m = np.hstack(blocks)
    filled = np.isfinite(m)
    with np.errstate(invalid="ignore"):
        means = np.where(filled.any(axis=1), np.nansum(m, axis=1) / np.maximum(filled.sum(axis=1), 1), np.nan)
    means = means[np.isfinite(means)]
    if len(means) == 0:
        return {"draws": int(m.shape[0]), "p95": None, "mean": None, "real_percentile": None, "drop_share": 1.0}
    return {
        "draws": int(m.shape[0]),
        "p95": float(np.percentile(means, pct)),
        "mean": float(means.mean()),
        "real_percentile": float((means < real_mean).mean() * 100.0),
        "drop_share": float(1.0 - filled.mean()),
    }


def placebo_seed(hyp: str, cell: str, split: str) -> int:
    return zlib.crc32(f"lab7|{hyp}|{cell}|{split}".encode())


# --------------------------------------------------------------------------------------------- readings


def event_bootstrap_ci(values: np.ndarray, groups: np.ndarray, B: int = BOOTSTRAP_B, seed: int = 0) -> tuple[float, float]:
    """Lab 4's: the 95 % interval of the mean under resampling of EVENTS (games / windows / markets that move
    together are one draw)."""
    return L4.event_bootstrap_ci(np.asarray(values, dtype=float), np.asarray(groups), B=B, seed=seed)


def _longest_losing_streak(pnl: np.ndarray) -> int:
    best = cur = 0
    for v in pnl:
        cur = cur + 1 if v <= 0 else 0
        best = max(best, cur)
    return int(best)


def max_open_positions(t_entry: np.ndarray, t_exit: np.ndarray) -> int:
    """Most positions open at once across the cell (an exit at the same second as an entry frees its slot first)."""
    ev = sorted([(float(t), 1) for t in t_entry] + [(float(t), -1) for t in t_exit], key=lambda e: (e[0], e[1]))
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return int(best)


def daily_stop_overlay(trips: pd.DataFrame, limit_usd: float = DAILY_LOSS_STOP_USD) -> dict[str, Any]:
    """The risk book's daily loss stop, as an overlay on the cell's trades: an entry is skipped when the US-fee P&L
    REALIZED earlier that UTC day (exit fills at or before the entry) is at or below ``-limit_usd``. A skipped trade
    does not re-open its market earlier (the overlay keeps the cell's other trades as they were)."""
    if len(trips) == 0:
        return {"limit_usd": limit_usd, "n": 0, "skipped": 0, "days_stopped": 0, "mean_net": None, "total_usd": 0.0}
    f = trips.sort_values("t_entry", kind="stable")
    heap: list[tuple[float, float, str]] = []
    realized: dict[str, float] = {}
    keep = []
    stopped_days: set[str] = set()
    for r in f.itertuples(index=False):
        while heap and heap[0][0] <= r.t_entry:
            _, pnl, d = heapq.heappop(heap)
            realized[d] = realized.get(d, 0.0) + pnl
        d_in = _day(r.t_entry)
        if realized.get(d_in, 0.0) <= -limit_usd + EPS:
            stopped_days.add(d_in)
            keep.append(False)
            continue
        keep.append(True)
        heapq.heappush(heap, (float(r.t_exit), float(r.pnl_us), _day(r.t_exit)))
    kept = f[np.array(keep, dtype=bool)]
    return {
        "limit_usd": limit_usd,
        "n": len(kept),
        "skipped": int(len(f) - len(kept)),
        "days_stopped": len(stopped_days),
        "mean_net": float(kept["net_us"].mean()) if len(kept) else None,
        "total_usd": float(kept["pnl_us"].sum()),
    }


def risk_book(trips: pd.DataFrame, split: str) -> dict[str, Any]:
    """PLAN §6 risk book: max open positions (and the capital they lock), the daily loss stop overlay, max drawdown
    of realized P&L in exit order, worst and best day, daily Sharpe over every calendar day of the split (days
    without an exit count as 0), longest losing streak, worst round trip."""
    if len(trips) == 0:
        return {"max_open": 0, "capital_usd": 0.0, "daily_stop": daily_stop_overlay(trips), "max_drawdown_usd": 0.0,
                "worst_day_usd": None, "best_day_usd": None, "sharpe_daily": None, "days_with_exits": 0,
                "longest_losing_streak": 0, "worst_trip_usd": None}
    f = trips.sort_values("t_exit", kind="stable")
    pnl = f["pnl_us"].to_numpy(dtype=float)
    cum = np.concatenate([[0.0], np.cumsum(pnl)])
    dd = float((cum - np.maximum.accumulate(cum)).min())
    daily = f.groupby("day")["pnl_us"].sum()
    lo, hi = split_bounds(split)

    def _ts(d: str) -> float:
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()

    first, last = min(lo, _ts(min(daily.index))), max(hi - 1, _ts(max(daily.index)))
    days = pd.date_range(datetime.fromtimestamp(first, UTC).date(), datetime.fromtimestamp(last, UTC).date(), freq="D")
    series = daily.reindex([d.strftime("%Y-%m-%d") for d in days], fill_value=0.0)
    sd = float(series.std(ddof=1)) if len(series) > 1 else 0.0
    mo = max_open_positions(f["t_entry"].to_numpy(), f["t_exit"].to_numpy())
    return {
        "max_open": mo,
        "capital_usd": mo * TICKET_USD,
        "daily_stop": daily_stop_overlay(f),
        "max_drawdown_usd": dd,
        "worst_day_usd": float(daily.min()),
        "best_day_usd": float(daily.max()),
        "sharpe_daily": float(series.mean() / sd * math.sqrt(365.0)) if sd > 0 else None,
        "days_with_exits": len(daily),
        "longest_losing_streak": _longest_losing_streak(pnl),
        "worst_trip_usd": float(pnl.min()),
    }


def summarize(trips: pd.DataFrame, split: str, missed: int = 0, B: int = BOOTSTRAP_B) -> dict[str, Any]:
    """PLAN §6 per-cell readings (US fee unless named): n round trips, events, missed entries, trips per day, win
    rate, mean net per $ with the event-bootstrap CI95, the same under the polymarket.com and stress fees, the
    rule-of-three worst case, the share of entries whose fill print was smaller than our contracts (the one-print
    fill assumption), exit mix, late time stops, hold time, cents per contract won / lost, the break-even win rate
    those imply, and the risk book."""
    lo, hi = split_bounds(split)
    days = max(1.0, (hi - lo) / DAY_S)
    n = len(trips)
    out: dict[str, Any] = {"n": n, "missed": int(missed), "trips_per_day": n / days}
    if n == 0:
        return {**out, "n_events": 0, "losses": 0, "win_rate": None, "mean_net_us": None, "ci95": [None, None],
                "mean_net_com": None, "mean_net_stress": None, "worst_case_net": None, "mean_pnl_usd": None,
                "total_usd": 0.0, "mean_p_entry": None, "small_entry_share": None, "exit_mix": {}, "late_stops": 0,
                "hold_min_median": None,
                "win_cents": None, "loss_cents": None, "breakeven_win_rate": None, "risk": risk_book(trips, split)}
    net = trips["net_us"].to_numpy(dtype=float)
    groups = trips["event"].fillna(trips["id"]).astype(str).to_numpy()
    ci = event_bootstrap_ci(net, groups, B=B)
    won = net > 0
    losses = int((~won).sum())
    mean_win = float(net[won].mean()) if won.any() else 0.0
    cents = trips["pnl_us"].to_numpy(dtype=float) / trips["shares"].to_numpy(dtype=float) * 100.0
    win_c = float(cents[won].mean()) if won.any() else None
    loss_c = float(-cents[~won].mean()) if (~won).any() else None
    be = (loss_c / (win_c + loss_c)) if (win_c is not None and loss_c is not None and win_c + loss_c > 0) else None
    return {
        **out,
        "n_events": len(np.unique(groups)),
        "losses": losses,
        "win_rate": float(won.mean()),
        "mean_net_us": float(net.mean()),
        "ci95": [ci[0], ci[1]],
        "mean_net_com": float(trips["net_com"].mean()),
        "mean_net_stress": float(trips["net_stress"].mean()),
        "worst_case_net": float((1.0 - 3.0 / n) * mean_win - 3.0 / n),
        "mean_pnl_usd": float(trips["pnl_us"].mean()),
        "total_usd": float(trips["pnl_us"].sum()),
        "mean_p_entry": float(trips["p_entry"].mean()),
        "small_entry_share": float((trips["entry_print_size"] < trips["shares"]).mean()),
        "exit_mix": {str(k): float(v) for k, v in trips["reason"].value_counts(normalize=True).sort_index().items()},
        "late_stops": int(trips["late_stop"].astype(bool).sum()),
        "hold_min_median": float(np.median(trips["hold_s"].to_numpy(dtype=float)) / 60.0),
        "win_cents": win_c,
        "loss_cents": loss_c,
        "breakeven_win_rate": be,
        "risk": risk_book(trips, split),
    }


def bar_checks(s: dict[str, Any], min_n: int = MIN_N) -> dict[str, bool]:
    """The bar without the placebo (PLAN §7): n, mean, CI95 lower bound, stress fee, lab 4's loss guards."""
    mean, lo = s.get("mean_net_us"), (s.get("ci95") or [None, None])[0]
    losses = int(s.get("losses") or 0)
    guards = losses >= 1 and (losses >= 5 or (s.get("worst_case_net") is not None and s["worst_case_net"] > 0))
    return {
        "n": s.get("n", 0) >= min_n,
        "mean": mean is not None and mean > 0,
        "ci_lower": lo is not None and lo > 0,
        "stress": s.get("mean_net_stress") is not None and s["mean_net_stress"] > 0,
        "loss_guards": bool(guards),
    }


def bar(s: dict[str, Any], placebo: dict[str, Any] | None, min_n: int = MIN_N) -> dict[str, Any]:
    """The full bar: :func:`bar_checks` AND the real mean above the random-entry placebo's 95th percentile. The
    placebo only needs computing when the other checks pass (it cannot rescue a cell that fails them)."""
    checks = bar_checks(s, min_n)
    p95 = (placebo or {}).get("p95")
    checks["placebo"] = p95 is not None and s.get("mean_net_us") is not None and s["mean_net_us"] > p95
    return {"checks": checks, "passes": all(checks.values())}


def select_one(cells: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """TRAIN picks at most ONE cell per hypothesis: among selectable cells that pass the full bar, the highest CI95
    lower bound (ties: the higher mean, then the cell key). ``cells``: dicts with 'cell', 'selectable', 'summary',
    'bar'."""
    ok = [c for c in cells if c.get("selectable") and c.get("bar", {}).get("passes")]
    if not ok:
        return None
    return min(ok, key=lambda c: (-c["summary"]["ci95"][0], -c["summary"]["mean_net_us"], str(c["cell"])))


# --------------------------------------------------------------------------------------------- trial ledger


def trials_count(ledger: Path = LEDGER) -> int:
    """Trials across labs 2-7, each ledger read in its own format (lab 4's ``_ledger_size``)."""
    n = 0
    for path in (*SIBLING_LEDGERS, Path(ledger)):
        if path.exists():
            try:
                n += L4._ledger_size(json.loads(path.read_text()))
            except ValueError:
                continue
    return n


LEDGER_KEY = ("lab", "hyp", "cell", "split", "stage")


def record_runs(entries: Sequence[dict[str, Any]], ledger: Path = LEDGER) -> int:
    """Upsert trials in research/lab7/trials.json keyed on (lab, hyp, cell, split, stage): a re-run replaces its
    own entry, a new cell adds one. Four specialists share the file, so the read-modify-write holds an exclusive
    lock (``trials.json.lock``) and the file is replaced atomically. Returns the running count across labs 2-7."""
    import fcntl

    path = Path(ledger)
    now = {"utc": datetime.now(UTC).isoformat(timespec="seconds"), "t": time.time()}
    with open(str(path) + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else []
        for entry in entries:
            entry = {"lab": "lab7", **entry}
            key = tuple(entry.get(k) for k in LEDGER_KEY)
            rows = [e for e in rows if tuple(e.get(k) for k in LEDGER_KEY) != key]
            rows.append({**entry, **now})
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, indent=1, sort_keys=True, default=str) + "\n")
        os.replace(tmp, path)
    return trials_count(path)


def record_run(entry: dict[str, Any], ledger: Path = LEDGER) -> int:
    return record_runs([entry], ledger)

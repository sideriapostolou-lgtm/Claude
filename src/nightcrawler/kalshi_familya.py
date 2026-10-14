"""Family A queue-aware replay and accounting (research/kalshi_edge_search/PROTOCOL.md, kalshi-familyA-v1).

A SIMULATED $25 account per variant replays the public recorder's tape: one-contract post-only bids
on the favourite side of slower markets, decided every whole UTC minute, arriving after the latency L,
queued behind every contract displayed at our price, filled only by real prints that sell into our
side after that queue is used up (partial fills in 0.01 steps), cancelled with the same delay (fills
during a cancel race count, and the reservation stays until the cancel takes effect), and held to
official settlement. Prices, fees and cash are exact decimals on Kalshi's grids; fills follow Kalshi's
direct-account rounding (trade fee up to $0.000001, balance down to $0.0001, a per-order rounding
accumulator and capped rebates). The account's limits are the protocol's simulated ones ($2 per
cluster, $4 outstanding, $3 day loss/risk, $5 lifetime) and never the live account's.

TEST rows are refused until ``family_a/FREEZE.json`` and its published hash exist and match this
run (variant or its matched baseline, E1, 28 days, every frozen parameter including L, the replay
code's SHA-256, a freeze at least 1 h before E1 by its own ``frozen_at``, by git's commit time and by
the recorder's own clock (a ``freeze_witness`` row naming its hash), and the hash written in
``docs/WORKLOG.md``); a TEST account is built only from the permit that check returns, and every use
of a permit runs the check again on its files. TRAIN and VAL are 7 days each; no run without a TEST
permit, whatever its label or length, may have entry days at or after a frozen E1 (an installed copy
with no research directory beside it refuses without a permit), and ``tape``/``feed`` keep the TEST
days' books and prints from it. Each entry day's decision coverage is counted (section 12); below
the section 11/12 floor the run says INCOMPLETE_DATA or INCONCLUSIVE. Every run is labelled with
its kind (primary, pessimistic, latency stress, live-style day stop, UNFUNDED diagnostic). Nothing
here sends, cancels or amends an order: every order below is a simulated object in memory.

    python -m nightcrawler.kalshi_familya replay --data-dir DATA_DIR --phase TRAIN \\
        --first-day 2026-10-20 --days 7 --variant A1 [--model pessimistic] [--latency-ms 1000]
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import heapq
import itertools
import json
import math
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

from .kalshi_familya_universe import (
    PROTOCOL_WINDOW,
    FeeStatus,
    TickGrid,
    admit,
    cluster_of,
    dec,
    parse_grid,
    settlement_block,
    ts,
)
from .kalshi_recorder_store import file_sha256, iter_records, iter_segment, load_index

PROTOCOL_VERSION = "kalshi-familyA-v1"
ZERO, ONE = Decimal(0), Decimal(1)
HALF = Decimal("0.5")
SIZE_STEP = Decimal("0.01")
DIRECT_GRID = Decimal("0.0001")
FCM_GRID = Decimal("0.01")
FEE_GRID = Decimal("0.000001")
RESERVE_PAD = Decimal("0.0100")
START_CASH = Decimal("25.0000")
CLUSTER_LIMIT, OUTSTANDING_LIMIT, DAY_LIMIT, LIFETIME_LIMIT = Decimal(2), Decimal(4), Decimal(3), Decimal(5)
MIN_VOLUME = Decimal(25)
MAX_SPREAD = Decimal("0.10")
BOOK_MAX_AGE_S = 120.0
SWEEP_MAX_AGE_S = 600.0
COVERAGE_S = 120
CUTOFF_S = 6 * 3600.0
ROTATION_S = 6 * 3600.0
TOP_LEVELS = 10
MAKER_RATE, TAKER_RATE = Decimal("0.0175"), Decimal("0.07")
YES, NO = "yes", "no"
UNKNOWN_QUEUE = Decimal("Infinity")  # q outside the 10 best bids at arrival: no print reaches us until a book shows q
PHASE_DAYS = {"TRAIN": 7, "VAL": 7, "TEST": 28}
# Section 11: a TRAIN or VAL phase with fewer than 5 of 7 covered entry days restarts; section 12: TEST needs 26 of
# 28 covered entry days and 90% of all its decisions covered, otherwise it is INCONCLUSIVE.
COVERED_DAYS_NEEDED = {"TRAIN": 5, "VAL": 5, "TEST": 26}
COVERED_SHARE = Decimal("0.90")
MATCHED_BASELINE = {"A1": "MB-J", "A3": "MB-J", "A2": "MB-I", "A4": "MB-I"}
FROZEN_KEYS = ("protocol", "variant", "first_day", "days", "latency_ms", "epsilon_ms")
# This checkout's research/kalshi_edge_search: where a run without a permit looks for the frozen TEST days.
RESEARCH_DIR = Path(__file__).resolve().parents[2] / "research" / "kalshi_edge_search"
# The code a TEST verdict depends on; FREEZE.json pins these files' SHA-256 (section 11).
FAMILYA_CODE = ("kalshi_familya.py", "kalshi_familya_universe.py", "kalshi_recorder_store.py")
RUN_LABELS = {
    "primary": "PRIMARY",
    "pessimistic": "PESSIMISTIC model (section 8)",
    "latency_stress": "LATENCY STRESS (section 8): reported only, never used to choose or to judge",
    "live_style": "LIVE-STYLE DAY STOP sensitivity (section 10): reported only",
    "unfunded": "UNFUNDED diagnostic (section 10): only the $2 cluster limit; never a funded trial or a verdict",
}


# =========================================================================== exact arithmetic
def ceil_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def floor_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


@dataclass(frozen=True)
class FeeTerms:
    fee_type: str
    multiplier: Decimal

    def maker_model_fee(self, count: Decimal, price: Decimal) -> Decimal:
        """Section 9: 0.0175 x M x c x p x (1 - p) only where the series charges makers."""
        if self.fee_type != "quadratic_with_maker_fees":
            return ZERO
        return MAKER_RATE * self.multiplier * count * price * (ONE - price)

    def taker_model_fee(self, count: Decimal, price: Decimal) -> Decimal:
        return TAKER_RATE * self.multiplier * count * price * (ONE - price)


@dataclass(frozen=True)
class FillCash:
    revenue: Decimal
    trade_fee: Decimal
    rounding_fee: Decimal
    rebate: Decimal
    cash_change: Decimal

    @property
    def net_fee(self) -> Decimal:
        return self.trade_fee + self.rounding_fee - self.rebate


@dataclass
class FeeAccumulator:
    """Kalshi's per-order fee rounding (docs.kalshi.com/getting_started/fee_rounding); one per order.

    1. trade fee = model fee rounded up to $0.000001;
    2. aligned change = (revenue - trade fee) rounded down to the balance grid;
    3. rounding fee = (revenue - trade fee) - aligned change, added to this order's accumulator;
    4. rebate = the accumulator in whole grid steps, capped so the fill's net fee is not negative;
    5. cash change = aligned change + rebate.
    """

    grid: Decimal = DIRECT_GRID
    carried: Decimal = ZERO
    rebates: bool = True

    def fill(self, revenue: Decimal, model_fee: Decimal) -> FillCash:
        trade_fee = ceil_to(model_fee, FEE_GRID)
        before = revenue - trade_fee
        aligned = floor_to(before, self.grid)
        rounding = before - aligned
        self.carried += rounding
        rebate = ZERO
        if self.rebates:
            rebate = floor_to(min(self.carried, trade_fee + rounding), self.grid)
            self.carried -= rebate
        return FillCash(revenue, trade_fee, rounding, rebate, aligned + rebate)


class FeeBook:
    """Fee terms in force at a time: series rows, scheduled series changes and event overrides, as received."""

    def __init__(self) -> None:
        self.series_rows: dict[str, list[tuple[float, FeeTerms]]] = defaultdict(list)
        self.series_changes: dict[str, list[tuple[float, FeeTerms]]] = defaultdict(list)
        self.event_changes: dict[str, list[tuple[float, FeeTerms]]] = defaultdict(list)
        self.series_list_at: float | None = None
        self.event_lookup_at: dict[str, float] = {}

    @staticmethod
    def _terms(row: Mapping[str, Any]) -> FeeTerms | None:
        fee_type, multiplier = row.get("fee_type"), row.get("fee_multiplier")
        value = dec(str(multiplier)) if isinstance(multiplier, (int, str)) and not isinstance(multiplier, bool) else (
            dec(repr(multiplier)) if isinstance(multiplier, float) else None)
        if not isinstance(fee_type, str) or value is None:
            return None
        return FeeTerms(fee_type, value)

    def add_series(self, row: Mapping[str, Any], received_at: float) -> None:
        terms, name = self._terms(row), row.get("ticker")
        if terms is not None and isinstance(name, str):
            self.series_rows[name].append((received_at, terms))

    def add_series_changes(self, rows: Iterable[Any], received_at: float) -> None:
        self.series_list_at = received_at
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            terms, name, when = self._terms(row), row.get("series_ticker"), ts(row.get("scheduled_ts"))
            if terms is not None and isinstance(name, str) and when is not None:
                entry = (when, terms)
                if entry not in self.series_changes[name]:
                    self.series_changes[name].append(entry)

    def add_event_changes(self, event: str, rows: Iterable[Any], received_at: float) -> None:
        self.event_lookup_at[event] = received_at
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            terms, when = self._terms(row), ts(row.get("scheduled_ts"))
            if terms is not None and when is not None and (when, terms) not in self.event_changes[event]:
                self.event_changes[event].append((when, terms))

    def terms_at(self, series: str, event: str, at: float) -> FeeTerms | None:
        """The latest known terms by effective time: a later scheduled change beats an older series row."""
        known = [(when, 0, terms) for when, terms in self.series_rows.get(series, []) if when <= at]
        known += [(when, 1, terms) for when, terms in self.series_changes.get(series, []) if when <= at]
        override = [(when, terms) for when, terms in self.event_changes.get(event, []) if when <= at]
        if override:
            return max(override, key=lambda item: item[0])[1]
        if not known:
            return None
        return max(known, key=lambda item: (item[0], item[1]))[2]

    def status(self, event: str) -> FeeStatus:
        return FeeStatus(self.series_list_at, self.event_lookup_at.get(event))


# =========================================================================== books and prints
Level = tuple[Decimal, Decimal]


def parse_levels(raw: Any, top: int = TOP_LEVELS) -> tuple[Level, ...] | None:
    """Kalshi bids are ascending [price, size] strings; keep the ``top`` best (highest) with size."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        return None
    levels: dict[Decimal, Decimal] = {}
    for row in raw:
        if not isinstance(row, list) or len(row) != 2:
            return None
        price, size = dec(row[0]), dec(row[1])
        if price is None or size is None or not ZERO < price < ONE or size < 0:
            return None
        if size > 0:
            levels[price] = levels.get(price, ZERO) + size
    return tuple(sorted(levels.items(), reverse=True)[:top])


@dataclass(frozen=True)
class Book:
    ticker: str
    received_at: float
    yes: tuple[Level, ...]
    no: tuple[Level, ...]

    def bids(self, side: str) -> tuple[Level, ...]:
        return self.yes if side == YES else self.no

    def best(self, side: str) -> Decimal | None:
        levels = self.bids(side)
        return levels[0][0] if levels else None

    def ask(self, side: str) -> Decimal | None:
        """YES ask = 1 - best NO bid; NO ask = 1 - best YES bid."""
        other = self.best(NO if side == YES else YES)
        return None if other is None else ONE - other

    def two_sided(self) -> bool:
        return bool(self.yes) and bool(self.no)

    def crossed_or_locked(self) -> bool:
        return self.two_sided() and self.yes[0][0] + self.no[0][0] >= ONE

    def size_at(self, side: str, price: Decimal) -> Decimal | None:
        """Displayed size at ``price`` (0 when absent inside the 10 best); None when outside the 10 best."""
        levels = self.bids(side)
        for level_price, size in levels:
            if level_price == price:
                return size
        if len(levels) >= TOP_LEVELS and price < levels[-1][0]:
            return None
        return ZERO

    def offered_at_or_below(self, side: str, price: Decimal) -> Decimal:
        """Contracts offered to sell ``side`` at or below ``price``: the other side's bids at >= 1 - price."""
        return sum((size for level_price, size in self.bids(NO if side == YES else YES)
                    if ONE - level_price <= price), ZERO)


@dataclass(frozen=True)
class Print:
    ticker: str
    trade_id: str
    created: float
    received: float
    yes_price: Decimal | None
    no_price: Decimal | None
    count: Decimal
    outcome_side: Any
    book_side: Any
    is_block: Any

    def consistent(self) -> bool:
        return (self.yes_price is not None and self.no_price is not None
                and self.yes_price + self.no_price == ONE
                and (self.outcome_side, self.book_side) in ((YES, "bid"), (NO, "ask")))

    def sells_into(self, side: str) -> bool:
        """(no, ask) sells YES into YES bids; (yes, bid) sells NO into NO bids (section 7.4)."""
        return (self.outcome_side, self.book_side) == ((NO, "ask") if side == YES else (YES, "bid"))

    def price(self, side: str) -> Decimal | None:
        return self.yes_price if side == YES else self.no_price


def parse_print(row: Mapping[str, Any], received: float) -> Print | None:
    ticker, trade_id, created = row.get("ticker"), row.get("trade_id"), ts(row.get("created_time"))
    count = dec(row.get("count_fp"))
    if not isinstance(ticker, str) or not isinstance(trade_id, str) or created is None or count is None or count <= 0:
        return None
    return Print(ticker, trade_id, created, received, dec(row.get("yes_price_dollars")),
                 dec(row.get("no_price_dollars")), count, row.get("taker_outcome_side"), row.get("taker_book_side"),
                 row.get("is_block_trade"))


# =========================================================================== coverage (section 12)
class Intervals:
    """A union of closed integer-second intervals."""

    def __init__(self) -> None:
        self.raw: list[tuple[float, float]] = []
        self._merged: list[tuple[float, float]] | None = None

    def add(self, start: float, end: float) -> None:
        if end >= start:
            self.raw.append((start, end))
            self._merged = None

    def merged(self) -> list[tuple[float, float]]:
        if self._merged is None:
            out: list[tuple[float, float]] = []
            for start, end in sorted(self.raw):
                if out and start <= out[-1][1] + 1:
                    out[-1] = (out[-1][0], max(out[-1][1], end))
                else:
                    out.append((start, end))
            self._merged = out
        return self._merged

    def covers(self, start: float, end: float) -> bool:
        for low, high in self.merged():
            if low <= start and end <= high:
                return True
            if low > start:
                return False
        return False


@dataclass
class Coverage:
    exchange: Intervals = field(default_factory=Intervals)
    by_ticker: dict[str, Intervals] = field(default_factory=lambda: defaultdict(Intervals))
    watched: dict[str, Intervals] = field(default_factory=lambda: defaultdict(Intervals))

    def tape(self, ticker: str, start: float, end: float) -> bool:
        """Complete public tape for ``ticker`` over [start, end]: exchange-wide (while watched) or per ticker."""
        if ticker in self.by_ticker and self.by_ticker[ticker].covers(math.floor(start), math.ceil(end)):
            return True
        return (self.exchange.covers(math.floor(start), math.ceil(end))
                and ticker in self.watched and self.watched[ticker].covers(start, end))


# =========================================================================== the simulated account
@dataclass(frozen=True)
class Variant:
    name: str
    low: Decimal
    high: Decimal
    high_inclusive: bool
    improve: bool
    favourite: bool

    def in_band(self, price: Decimal) -> bool:
        return self.low <= price and (price <= self.high if self.high_inclusive else price < self.high)


VARIANTS = {
    "A1": Variant("A1", Decimal("0.50"), Decimal("0.80"), False, False, True),
    "A2": Variant("A2", Decimal("0.50"), Decimal("0.80"), False, True, True),
    "A3": Variant("A3", Decimal("0.80"), Decimal("0.95"), True, False, True),
    "A4": Variant("A4", Decimal("0.80"), Decimal("0.95"), True, True, True),
    "MB-J": Variant("MB-J", Decimal("0.05"), Decimal("0.95"), True, False, False),
    "MB-I": Variant("MB-I", Decimal("0.05"), Decimal("0.95"), True, True, False),
}


def baseline_side(ticker: str) -> str:
    """Section 10: YES when the first byte of SHA-256('familyA-baseline-v1|<ticker>') is even."""
    return YES if hashlib.sha256(f"familyA-baseline-v1|{ticker}".encode()).digest()[0] % 2 == 0 else NO


@dataclass
class Lot:
    count: Decimal
    cost: Decimal  # cash paid, fees and rounding included
    sent_day: str
    order_id: int


@dataclass
class Position:
    ticker: str
    side: str
    cluster: str
    lots: list[Lot] = field(default_factory=list)

    @property
    def count(self) -> Decimal:
        return sum((lot.count for lot in self.lots), ZERO)

    @property
    def cost(self) -> Decimal:
        return sum((lot.cost for lot in self.lots), ZERO)


@dataclass
class Order:
    oid: int
    ticker: str
    side: str
    price: Decimal
    size: Decimal
    cluster: str
    sent_at: float
    arrives_at: float
    sent_day: str
    per_contract: Decimal
    replacement: bool
    state: str = "pending"  # pending, confirming, resting, cancelling, dead, rejected
    remaining: Decimal = ZERO
    queue: Decimal = ZERO
    buffered: list[Print] = field(default_factory=list)
    cancel_at: float | None = None  # a decided cancel takes effect (is acknowledged) here: decision + L
    cancel_reason: str | None = None
    expires_at: float | None = None  # close time, or a non-active status + L
    expire_reason: str | None = None
    died_at: float | None = None
    crossed: Decimal = ZERO
    fills: list[tuple[float, Decimal]] = field(default_factory=list)
    accumulator: FeeAccumulator = field(default_factory=FeeAccumulator)

    @property
    def live(self) -> bool:
        return self.state in ("pending", "confirming", "resting", "cancelling")

    @property
    def end_at(self) -> float | None:
        """When this quote stops being fillable (before the epsilon margin): its cancel or its expiry."""
        ends = [value for value in (self.cancel_at, self.expires_at) if value is not None]
        return min(ends) if ends else None


class LimitBreach(AssertionError):
    """An accounting defect (section 18), never a result."""


@dataclass
class Account:
    """One independent SIMULATED $25.0000 account. Never reset, topped up or shared.

    ``earmarks`` hold, from a reprice decision until its cancel is acknowledged, the extra budget its
    replacement needs (section 5.9: resting quotes are reviewed first, so new quotes at the same
    decision cannot take it). ``released`` lists the orders whose cancel is acknowledged. Such an order can still
    fill in the clock margin (section 7.4, until the cancel takes effect + epsilon), and section 6 reserves every
    possible loss in advance, so it stays in every limit and cash check until it dies, net of its own live
    replacement (``replaced_by``): a margin fill of the old order trims the replacement (one contract per market),
    so the pair can cost at most the dearer of the two, and the old order counts only its excess over the new one
    (nothing when the replacement is dearer, as when a quote is repriced up). ``exclude`` leaves orders out.
    """

    cash: Decimal = START_CASH
    reserved: dict[int, Decimal] = field(default_factory=dict)
    order_cluster: dict[int, str] = field(default_factory=dict)
    order_day: dict[int, str] = field(default_factory=dict)
    earmarks: dict[int, tuple[str, str, Decimal]] = field(default_factory=dict)  # old oid -> (cluster, day, extra)
    released: set[int] = field(default_factory=set)  # cancel acknowledged; counted until it dies (see above)
    replaced_by: dict[int, int] = field(default_factory=dict)  # released order -> its replacement
    positions: dict[str, Position] = field(default_factory=dict)
    realized: list[dict[str, Any]] = field(default_factory=list)
    day_pnl: dict[str, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    fill_cash: Decimal = ZERO
    payouts: Decimal = ZERO
    fees: Decimal = ZERO
    rounding: Decimal = ZERO
    rebates: Decimal = ZERO

    def _reservations(self, exclude: frozenset[int]) -> Iterator[tuple[str, str, Decimal]]:
        for oid, amount in self.reserved.items():
            if oid in exclude:
                continue
            if oid in self.released:
                new = self.replaced_by.get(oid)
                if new is not None and new not in exclude and new in self.reserved:
                    amount = max(ZERO, amount - self.reserved[new])  # the pair costs at most the dearer of the two
            yield self.order_cluster[oid], self.order_day[oid], amount
        for oid, (cluster, day, amount) in self.earmarks.items():
            if oid not in exclude:
                yield cluster, day, amount

    def capital(self) -> Decimal:
        """Cash tied up now: reservations of sent orders and the cost of unsettled positions (no earmarks)."""
        return sum(self.reserved.values(), ZERO) + sum((position.cost for position in self.positions.values()), ZERO)

    def at_risk(self, exclude: frozenset[int] = frozenset()) -> Decimal:
        return (sum((amount for _, _, amount in self._reservations(exclude)), ZERO)
                + sum((position.cost for position in self.positions.values()), ZERO))

    def cluster_risk(self, cluster: str, exclude: frozenset[int] = frozenset()) -> Decimal:
        return (sum((amount for owner, _, amount in self._reservations(exclude) if owner == cluster), ZERO)
                + sum((position.cost for position in self.positions.values() if position.cluster == cluster), ZERO))

    def day_new_risk(self, day: str, exclude: frozenset[int] = frozenset()) -> Decimal:
        return (sum((amount for _, sent, amount in self._reservations(exclude) if sent == day), ZERO)
                + sum((lot.cost for position in self.positions.values() for lot in position.lots
                       if lot.sent_day == day), ZERO))

    def day_loss(self, day: str) -> Decimal:
        return max(ZERO, -self.day_pnl[day])

    def lifetime_loss(self) -> Decimal:
        return max(ZERO, -sum((row["pnl"] for row in self.realized), ZERO))

    def free_cash(self, exclude: frozenset[int] = frozenset()) -> Decimal:
        return self.cash - sum((amount for _, _, amount in self._reservations(exclude)), ZERO)

    def blocked_by(self, cluster: str, day: str, amount: Decimal, *, day_stop: str = "protocol",
                   unfunded: bool = False, exclude: frozenset[int] = frozenset()) -> str | None:
        """Section 6: the first limit a new order of reservation ``amount`` would break, else None."""
        if self.cluster_risk(cluster, exclude) + amount > CLUSTER_LIMIT:
            return "cluster_2"
        if unfunded:
            return None
        at_risk = self.at_risk(exclude)
        if at_risk + amount > OUTSTANDING_LIMIT:
            return "outstanding_4"
        new_risk = at_risk if day_stop == "live_style" else self.day_new_risk(day, exclude)
        if self.day_loss(day) + new_risk + amount >= DAY_LIMIT:
            return "day_3"
        if self.lifetime_loss() + at_risk + amount >= LIFETIME_LIMIT:
            return "lifetime_5"
        if self.free_cash(exclude) < amount:
            return "cash"
        return None


# =========================================================================== replay configuration
@dataclass(frozen=True)
class ReplayConfig:
    variant: str
    phase: str
    first_day: date
    days: int
    latency_ms: int = 1000
    epsilon_ms: int = 250
    model: str = "primary"
    day_stop: str = "protocol"
    unfunded: bool = False
    latency_stress: bool = False

    def __post_init__(self) -> None:
        if self.variant not in VARIANTS:
            raise ValueError(f"Unknown variant {self.variant!r}")
        if self.phase not in ("TRAIN", "VAL", "TEST"):
            raise ValueError("Phase must be TRAIN, VAL or TEST")
        if self.model not in ("primary", "pessimistic"):
            raise ValueError("Model must be primary or pessimistic")
        if self.day_stop not in ("protocol", "live_style"):
            raise ValueError("Day stop must be protocol or live_style")
        if not 1 <= self.days <= 60 or not 0 < self.latency_ms <= 60_000 or not 0 <= self.epsilon_ms <= 5000:
            raise ValueError("Days, latency or epsilon outside the protocol's range")
        options = [self.model == "pessimistic", self.day_stop == "live_style", self.unfunded, self.latency_stress]
        if sum(options) > 1:
            raise ValueError("A run is one kind: primary, pessimistic, latency stress, live-style or unfunded")

    @property
    def kind(self) -> str:
        """Section 8/10: which preregistered run this is; only primary and pessimistic enter a verdict."""
        if self.unfunded:
            return "unfunded"
        if self.day_stop == "live_style":
            return "live_style"
        if self.latency_stress:
            return "latency_stress"
        return "pessimistic" if self.model == "pessimistic" else "primary"

    @property
    def entry_start(self) -> float:
        return datetime.combine(self.first_day, datetime.min.time(), UTC).timestamp()

    @property
    def entry_end(self) -> float:
        return self.entry_start + self.days * 86400 - 1

    @property
    def resolution_end(self) -> float:
        """TRAIN/VAL resolve 14 days after the last entry day; TEST follows up for 30 days."""
        return self.entry_end + 1 + (30 if self.phase == "TEST" else 14) * 86400

    @property
    def latency_s(self) -> float:
        base = self.latency_ms / 1000.0
        return max(base, 2.0) if self.model == "pessimistic" else base

    def label(self) -> str:
        stress = f" (L={self.latency_ms} ms)" if self.kind == "latency_stress" else ""
        return f"SIMULATED research account; not real money; run: {RUN_LABELS[self.kind]}{stress}"

    def parameters(self) -> dict[str, Any]:
        return {"protocol": PROTOCOL_VERSION, "variant": self.variant, "first_day": self.first_day.isoformat(),
                "days": self.days, "latency_ms": self.latency_ms, "epsilon_ms": self.epsilon_ms, "model": self.model,
                "day_stop": self.day_stop, "unfunded": self.unfunded, "latency_stress": self.latency_stress,
                "kind": self.kind}


class FreezeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Permit:
    """What ``check_scoring_allowed`` returns: the checked config, the freeze it saw (None before one exists) and
    the files it read. A permit proves nothing by itself: every use re-runs the gate on those files (``verify``),
    so a copied, edited or hand-built permit is worth exactly what the freeze on disk and its hashes allow.
    """

    config: ReplayConfig
    freeze: dict[str, Any] | None
    research_dir: Path
    worklog: Path | None = None
    recorder_root: Path | None = None

    def verify(self, config: ReplayConfig) -> None:
        """Raise FreezeError unless this permit is for ``config`` and the gate still allows it on the files now."""
        if config != self.config:
            raise FreezeError("A permit is for one config; this run is another")
        again = check_scoring_allowed(config, self.research_dir, worklog=self.worklog, recorder_root=self.recorder_root)
        if again.freeze != self.freeze:
            raise FreezeError("family_a/FREEZE.json is not the one this permit was issued for")

    def test_window(self) -> tuple[float, float] | None:
        """The frozen TEST entry days [E1 00:00, E28 end] (UTC seconds), from this permit's freeze or this checkout's
        (when this code sits in a checkout; the permit's own research directory had no freeze)."""
        if self.freeze is not None:
            return _test_window(self.freeze)
        return frozen_test_window(RESEARCH_DIR) if (RESEARCH_DIR / "PROTOCOL.md").exists() else None


def _test_window(freeze: Mapping[str, Any] | None) -> tuple[float, float] | None:
    first = freeze.get("E1") if isinstance(freeze, Mapping) else None
    try:
        start = datetime.combine(date.fromisoformat(first), datetime.min.time(), UTC).timestamp() \
            if isinstance(first, str) else None
    except ValueError:
        start = None
    return None if start is None else (start, start + PHASE_DAYS["TEST"] * 86400 - 1)


def frozen_test_window(research_dir: Path) -> tuple[float, float] | None:
    """The TEST entry days named by ``research_dir``'s family_a/FREEZE.json; None when no freeze exists yet."""
    path = research_dir / "family_a" / "FREEZE.json"
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FreezeError("family_a/FREEZE.json is unreadable, so the frozen TEST days are unknown") from exc
    window = _test_window(loaded)
    if window is None:
        raise FreezeError("family_a/FREEZE.json names no readable E1, so the frozen TEST days are unknown")
    return window


def checkout_test_window() -> tuple[float, float] | None:
    """The frozen TEST days for a run without a permit, from the checkout this code sits in.

    An installed copy (``pip install .``, the Docker image) has no research directory next to it, so it cannot know
    whether a freeze exists: it refuses rather than assume none does (a permit names the research directory).
    """
    if not (RESEARCH_DIR / "PROTOCOL.md").exists():
        raise FreezeError(f"No research/kalshi_edge_search next to this code ({RESEARCH_DIR}), so the frozen TEST days "
                          "are unknown: build the replay from check_scoring_allowed's permit for the research directory")
    return frozen_test_window(RESEARCH_DIR)


WITNESS_KIND = "freeze_witness"


def witnessed_freeze(recorder_root: Path, before: float) -> str | None:
    """The FREEZE.json SHA-256 the recorder last wrote, by its own clock, at or before ``before`` (None if none).

    The recorder writes a ``freeze_witness`` row (telemetry lane) when it starts with KALSHI_RECORDER_FREEZE_SHA256
    set. Its time comes from the recording host, not from anything the freeze's author writes (``frozen_at``) or
    sets (git's author and committer dates), and its segment hashes are checked as it is read.
    """
    latest: tuple[float, int, Any] | None = None
    for record in iter_records(recorder_root, frozenset({"telemetry"}), end=before):
        if record.get("kind") == WITNESS_KIND:
            key = (float(record["at"]), int(record["seq"]), record.get("sha256"))
            latest = key if latest is None or key[:2] > latest[:2] else latest
    return latest[2] if latest is not None and isinstance(latest[2], str) else None


def _committed_at(path: Path) -> datetime | None:
    """When ``path`` got its current content in git (the last commit that changed it; the later of its author and
    committer times), or None when it is not committed exactly as it is on disk. Git records this time; the file
    cannot declare it."""
    def git(*args: str) -> bytes:
        return subprocess.run(["git", "-C", str(path.parent), *args], capture_output=True, check=True, timeout=60,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).stdout

    try:
        if git("show", f"HEAD:./{path.name}") != path.read_bytes():
            return None
        stamps = git("log", "-1", "--format=%aI %cI", "HEAD", "--", path.name).decode().split()
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    times = [moment for moment in (_utc_time(stamp) for stamp in stamps) if moment is not None]
    return max(times) if len(times) == 2 else None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_hashes() -> dict[str, str]:
    """SHA-256 of the replay code a TEST result depends on; FREEZE.json must record exactly these."""
    here = Path(__file__).resolve().parent
    return {name: file_sha256(here / name) for name in FAMILYA_CODE}


def _published_hash(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and len(parts[0]) == 64:
            return parts[0]
    return None


def _utc_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _check_test(config: ReplayConfig, freeze: dict[str, Any], freeze_hash: str, research_dir: Path,
                worklog: Path, recorder_root: Path | None) -> None:
    """Section 11's freeze, enforced: everything that could change a TEST decision must match it."""
    frozen = freeze.get("variant")
    if config.variant not in (frozen, MATCHED_BASELINE.get(str(frozen))):
        raise FreezeError("This TEST run is neither the frozen variant nor its matched baseline")
    if (freeze.get("E1") != config.first_day.isoformat() or freeze.get("test_days") != config.days
            or config.days != PHASE_DAYS["TEST"]):
        raise FreezeError("This TEST run does not match the frozen E1 or its 28 entry days")
    expected = freeze.get("parameters")
    if not isinstance(expected, dict) or any(key not in expected for key in FROZEN_KEYS):
        raise FreezeError(f"FREEZE.json must record every frozen parameter: {', '.join(FROZEN_KEYS)}")
    actual = config.parameters()
    mismatched = sorted(key for key in FROZEN_KEYS if key != "variant" and actual[key] != expected[key]
                        and not (key == "latency_ms" and config.kind == "latency_stress"))
    if expected.get("variant") != frozen:
        mismatched.append("variant")
    if mismatched:
        raise FreezeError(f"Frozen parameters differ: {', '.join(mismatched)}")
    if freeze.get("code_sha256") != code_hashes():
        raise FreezeError("The replay code differs from the code FREEZE.json pins (code_sha256)")
    frozen_at = _utc_time(freeze.get("frozen_at"))
    test_start = datetime.combine(config.first_day, datetime.min.time(), UTC)
    if frozen_at is None or frozen_at > test_start - timedelta(hours=1):
        raise FreezeError("FREEZE.json must say when it was frozen (frozen_at), at least 1 h before E1")
    # frozen_at is written inside the file, so it is checked against git's own record of the freeze commit.
    committed = _committed_at(research_dir / "family_a" / "FREEZE.json")
    if committed is None:
        raise FreezeError("FREEZE.json must be committed to git exactly as it is on disk (its commit dates the freeze)")
    if committed > test_start - timedelta(hours=1):
        raise FreezeError("FREEZE.json was committed less than 1 h before E1 (git's commit time, not frozen_at)")
    if not worklog.exists() or freeze_hash not in worklog.read_text(encoding="utf-8"):
        raise FreezeError("The FREEZE.json SHA-256 is not written in docs/WORKLOG.md")
    # frozen_at and git's dates are both set by whoever writes the freeze (GIT_COMMITTER_DATE backdates a commit):
    # the recorder's own clock must have seen this hash at least 1 h before E1.
    if recorder_root is None:
        raise FreezeError("TEST needs the recorder's witness of the freeze: pass the recorder data "
                          "(run_replay does; `check --phase TEST` takes --data-dir)")
    witnessed = witnessed_freeze(recorder_root, (test_start - timedelta(hours=1)).timestamp())
    if witnessed != freeze_hash:
        raise FreezeError("The recorder's last freeze_witness at least 1 h before E1 does not name this FREEZE.json's "
                          "SHA-256 (set KALSHI_RECORDER_FREEZE_SHA256 on the recorder before E1 - 1 h)")


def check_scoring_allowed(config: ReplayConfig, research_dir: Path, *, worklog: Path | None = None,
                          recorder_root: Path | None = None) -> Permit:
    """Refuse TEST rows until a frozen, hash-published configuration matches; keep TRAIN/VAL before TEST.

    ``research_dir`` is ``research/kalshi_edge_search``; ``worklog`` defaults to the repository's
    ``docs/WORKLOG.md`` next to it; ``recorder_root`` (``DATA_DIR/kalshi_recorder``) holds the recorder's witness of
    the freeze, which TEST requires. Returns the permit a TEST account needs (its ``freeze`` is None when none
    exists yet).
    """
    protocol = research_dir / "PROTOCOL.md"
    published = _published_hash(research_dir / "PROTOCOL.sha256", "PROTOCOL.md")
    if published is None or not protocol.exists() or _sha256_file(protocol) != published:
        raise FreezeError("PROTOCOL.md does not match its published SHA-256; no phase can be scored")
    if config.days != PHASE_DAYS[config.phase]:
        raise FreezeError(f"{config.phase} has exactly {PHASE_DAYS[config.phase]} entry days (section 11)")
    freeze_path = research_dir / "family_a" / "FREEZE.json"
    freeze_hash = _published_hash(research_dir / "family_a" / "FREEZE.sha256", "FREEZE.json")
    freeze: dict[str, Any] | None = None
    if freeze_path.exists():
        if freeze_hash is None or _sha256_file(freeze_path) != freeze_hash:
            raise FreezeError("FREEZE.json exists without a matching published FREEZE.sha256")
        loaded = json.loads(freeze_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or loaded.get("protocol_sha256") != published:
            raise FreezeError("FREEZE.json does not name this protocol's SHA-256")
        freeze = loaded
    if config.phase == "TEST":
        if freeze is None or freeze_hash is None:
            raise FreezeError("TEST rows cannot be scored before family_a/FREEZE.json and its hash exist")
        parents = research_dir.resolve().parents  # <repo>/research/kalshi_edge_search -> <repo>
        _check_test(config, freeze, freeze_hash, research_dir,
                    worklog or parents[min(1, len(parents) - 1)] / "docs" / "WORKLOG.md", recorder_root)
    elif freeze is not None and isinstance(freeze.get("E1"), str):
        test_start = datetime.combine(date.fromisoformat(freeze["E1"]), datetime.min.time(), UTC).timestamp()
        if config.entry_end >= test_start:
            raise FreezeError("TRAIN/VAL entry days may not reach the frozen TEST period")
    return Permit(config, freeze, research_dir, worklog, recorder_root)


# =========================================================================== market state
@dataclass
class MarketState:
    ticker: str
    row: dict[str, Any] = field(default_factory=dict)
    book: Book | None = None
    sweep_at: float | None = None
    status_at: float | None = None
    volume: deque[tuple[float, float, Decimal]] = field(default_factory=deque)  # (created, received, count)
    grid: TickGrid | None = None
    settled: bool = False
    yes_value: Decimal | None = None  # what one YES contract paid at settlement (section 7.6)

    def volume_24h(self, at: float) -> Decimal:
        """Section 4.2: the quote sweep's volume_24h_fp when <= 10 min old, else recorded prints received by t."""
        if self.sweep_at is not None and at - self.sweep_at <= SWEEP_MAX_AGE_S:
            value = dec(self.row.get("volume_24h_fp"))
            if value is not None:
                return value
        while self.volume and self.volume[0][0] < at - 86400:
            self.volume.popleft()
        return sum((count for created, received, count in self.volume if received <= at and created >= at - 86400),
                   ZERO)


@dataclass(frozen=True)
class Target:
    side: str
    price: Decimal


@dataclass(order=True)
class _Internal:
    at: float
    seq: int
    kind: str = field(compare=False)
    oid: int = field(compare=False, default=-1)
    data: Any = field(compare=False, default=None)


class FamilyAReplay:
    """One variant, one phase, one SIMULATED account. Feed it time-ordered events, then ``finish``."""

    def __init__(self, config: ReplayConfig, coverage: Coverage | None = None, *, grid: Decimal = DIRECT_GRID,
                 permit: Permit | None = None) -> None:
        if permit is not None:
            permit.verify(config)  # the gate runs again on the files: a permit cannot be copied or built by hand
            window = permit.test_window()
        elif config.phase == "TEST":
            raise FreezeError("A TEST account is built only from check_scoring_allowed's permit for this config")
        else:
            window = checkout_test_window()
        if config.phase != "TEST" and window is not None and config.entry_end >= window[0]:
            # Any label, any length: entry days that reach the frozen TEST days are TEST rows.
            raise FreezeError("TRAIN/VAL entry days may not reach the frozen TEST period")
        self.test_window = window  # books and prints inside it reach only a TEST account (feed)
        self.test_permitted = permit is not None and config.phase == "TEST"
        self.config = config
        self.variant = VARIANTS[config.variant]
        self.coverage = coverage or Coverage()
        self.grid = grid
        self.latency = config.latency_s
        self.epsilon = config.epsilon_ms / 1000.0
        self.pessimistic = config.model == "pessimistic"
        self.account = Account()
        self.fees = FeeBook()
        self.markets: dict[str, MarketState] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.series: dict[str, dict[str, Any]] = {}
        self.orders: dict[int, Order] = {}
        self.market_orders: dict[str, list[int]] = defaultdict(list)
        self.cooldown: dict[str, float] = {}
        self.chain_clock: dict[str, float] = {}
        self.queue: list[_Internal] = []
        self._seq = itertools.count()
        self._oid = itertools.count(1)
        self.now = config.entry_start
        self.ledger: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()
        self.blocks: Counter[str] = Counter()
        self.unidentifiable: list[int] = []
        # Section 12, per UTC entry day: decisions over markets passing section 4.1, how many were covered, and
        # whether a market with a resting quote had an unrecovered trade gap.
        self.day_decisions: Counter[str] = Counter()
        self.day_covered: Counter[str] = Counter()
        self.day_quote_gaps: set[str] = set()
        self.capital_area = ZERO
        self._area_at = config.entry_start
        self.last_settlement_at: float | None = None
        self._schedule(config.entry_start, "decision")
        self._schedule(config.entry_end, "phase_end")

    # ------------------------------------------------------------------ plumbing
    def _schedule(self, at: float, kind: str, oid: int = -1, data: Any = None) -> None:
        heapq.heappush(self.queue, _Internal(at, next(self._seq), kind, oid, data))

    def _log(self, kind: str, at: float, **data: Any) -> None:
        self.ledger.append({"kind": kind, "at": at, **{key: str(value) if isinstance(value, Decimal) else value
                                                         for key, value in data.items()}})

    def _tick_area(self, at: float) -> None:
        if at > self._area_at:
            self.capital_area += self.account.capital() * Decimal(str(at - self._area_at)) / Decimal(86400)
            self._area_at = at

    def _advance(self, until: float, *, inclusive: bool = False) -> None:
        """Run internal events before ``until``: inputs received at a time are known to events at that time."""
        while self.queue and (self.queue[0].at < until or (inclusive and self.queue[0].at <= until)):
            item = heapq.heappop(self.queue)
            self._tick_area(item.at)
            self.now = item.at
            getattr(self, f"_on_{item.kind}")(item)

    def market(self, ticker: str) -> MarketState:
        state = self.markets.get(ticker)
        if state is None:
            state = self.markets[ticker] = MarketState(ticker)
        return state

    def _live(self, ticker: str) -> list[Order]:
        return [self.orders[oid] for oid in self.market_orders.get(ticker, ()) if self.orders[oid].live]

    def _held(self, ticker: str) -> Decimal:
        position = self.account.positions.get(ticker)
        return position.count if position is not None else ZERO

    # ------------------------------------------------------------------ external inputs
    def on_event_row(self, row: Mapping[str, Any], at: float) -> None:
        self._advance(at)
        if isinstance(row.get("event_ticker"), str):
            self.events[row["event_ticker"]] = dict(row)

    def on_series_row(self, row: Mapping[str, Any], at: float) -> None:
        self._advance(at)
        if isinstance(row.get("ticker"), str):
            self.series[row["ticker"]] = dict(row)
            self.fees.add_series(row, at)

    def on_series_fee_changes(self, rows: Iterable[Any], at: float) -> None:
        self._advance(at)
        self.fees.add_series_changes(rows, at)

    def on_event_fee_changes(self, event: str, rows: Iterable[Any], at: float) -> None:
        self._advance(at)
        self.fees.add_event_changes(event, rows, at)

    def on_market_row(self, row: Mapping[str, Any], at: float, *, full: bool, sweep: bool = False) -> None:
        """A full market row, or only its moving fields (merged over the last full row)."""
        self._advance(at)
        ticker = row.get("ticker")
        if not isinstance(ticker, str):
            return
        state = self.market(ticker)
        state.row = dict(row) if full else {**state.row, **row}
        if full:
            state.grid = parse_grid(state.row.get("price_ranges"))
        if sweep:
            state.sweep_at = at
        status = state.row.get("status")
        if status not in ("active", None):
            for order in self._live(ticker):
                if order.state != "pending":
                    self._kill(order, at + self.latency, "market_not_active")
        if status in ("finalized", "settled") and state.row.get("result") in (YES, NO) and not state.settled:
            self._settle(state, at)

    def on_book(self, ticker: str, yes: Any, no: Any, at: float) -> None:
        self._advance(at)
        yes_levels, no_levels = parse_levels(yes), parse_levels(no)
        state = self.market(ticker)
        if yes_levels is None or no_levels is None:
            state.book = None  # an unreadable book is no book: decisions see it as stale
            return
        state.book = Book(ticker, at, yes_levels, no_levels)
        self._after_book(state)

    def on_book_unchanged(self, ticker: str, at: float) -> None:
        self._advance(at)
        state = self.market(ticker)
        if state.book is not None:
            state.book = Book(ticker, at, state.book.yes, state.book.no)
            self._after_book(state)

    def on_print(self, item: Print) -> None:
        self._advance(item.created)
        self.market(item.ticker).volume.append((item.created, item.received, item.count))  # 4.2: every recorded trade
        if item.is_block is not False:
            return  # block trades never touch the book (section 7.4)
        for order in self._live(item.ticker):
            if order.state == "pending" or item.created < order.arrives_at + self.epsilon:
                continue
            if order.state == "confirming":
                order.buffered.append(item)
            else:
                self._apply_print(order, item)

    def finish(self, data_end: float) -> dict[str, Any]:
        """Run every scheduled event up to the earlier of the data end and the resolution end; then summarize.

        A tape that ends before the last entry day ends is never complete, and a quote still live when the tape
        ends rested past its end: section 7.7 counts it as unidentifiable (its fills are unknown).
        """
        end = min(data_end, self.config.resolution_end)
        self._advance(end, inclusive=True)
        self._tick_area(end)
        live = [order for order in self.orders.values() if order.live]
        for order in live:
            if order.oid not in self.unidentifiable:
                self.unidentifiable.append(order.oid)
        short = data_end < self.config.entry_end
        complete = not short and not live and (data_end >= self.config.resolution_end or not self.account.positions)
        unresolved = []
        for position in list(self.account.positions.values()):
            # Section 11: positions unresolved at the limit count at $0 and are listed.
            unresolved.append({"ticker": position.ticker, "side": position.side, "count": str(position.count),
                               "cost": str(position.cost)})
            self._realize(position, ZERO, end, unresolved=True)
        result = self.summary(end, unresolved)
        result["resolution_complete"] = complete
        coverage = self.entry_day_coverage()
        result.update(coverage)
        problems = []
        if short:
            problems.append("INCOMPLETE_DATA: the tape ends before the last entry day")
        elif not complete:
            problems.append("INCOMPLETE_DATA: the tape ends before the resolution limit")
        if not coverage["coverage_floor_met"]:
            # Whatever the time of the last tape item: one late row never makes a gap-ridden phase complete.
            counted = (f"{coverage['covered_entry_days']} of {self.config.days} entry days covered, "
                       f"{coverage['decision_coverage'] or 'no'} of decisions")
            if self.config.phase == "TEST":
                problems.append(f"INCONCLUSIVE: {counted} (section 12 needs {coverage['covered_entry_days_needed']} "
                                f"days and {COVERED_SHARE} of decisions)")
            else:
                problems.append(f"INCOMPLETE_DATA: {counted} (section 11 needs "
                                f"{coverage['covered_entry_days_needed']}): the phase restarts on new days")
        if problems:
            result["status"] = "; ".join(problems)
        return result

    # ------------------------------------------------------------------ books, queue and fills (section 7)
    def _after_book(self, state: MarketState) -> None:
        book = state.book
        if book is None:
            return
        for order in self._live(state.ticker):
            if order.state == "confirming":
                self._confirm(order, book)
            elif order.state in ("resting", "cancelling"):
                self._queue_and_cross(order, book)

    def _queue_and_cross(self, order: Order, book: Book) -> None:
        if not self.pessimistic:
            displayed = book.size_at(order.side, order.price)
            if displayed is not None:
                order.queue = min(order.queue, displayed)  # cancellations move us up only below our queue
        ask = book.ask(order.side)
        if ask is None or ask > order.price:
            return
        offered = book.offered_at_or_below(order.side, order.price) - order.crossed
        if offered <= 0:
            return
        # Someone offered at or below our bid: that size counts once as a print selling into our side.
        order.crossed += offered
        self.counts["crossing_book_prints"] += 1
        yes_price = ask if order.side == YES else ONE - ask
        self._apply_print(order, Print(order.ticker, f"book:{book.received_at}", book.received_at, book.received_at,
                                       yes_price, ONE - yes_price, offered, NO if order.side == YES else YES,
                                       "ask" if order.side == YES else "bid", False))

    def _confirm(self, order: Order, book: Book | None) -> None:
        """Sections 7.2-7.3: post-only against the first later book too; the queue ahead is the larger size."""
        if book is not None:
            ask = book.ask(order.side)
            if ask is not None and order.price >= ask:
                self._reject(order, book.received_at, "post_only_after_arrival")
                return
            displayed = book.size_at(order.side, order.price)
            order.queue = max(order.queue, displayed if displayed is not None else ZERO)
        order.state = "cancelling" if order.cancel_at is not None else "resting"
        buffered, order.buffered = order.buffered, []
        for item in buffered:
            self._apply_print(order, item)

    def _apply_print(self, order: Order, item: Print) -> None:
        end = order.end_at
        if end is not None and item.created > end + self.epsilon:
            return
        price = item.price(order.side)
        if price is None or price > order.price:
            return
        if not item.consistent():
            order.queue = max(ZERO, order.queue - item.count)  # reduces the queue, never fills us
            return
        if not item.sells_into(order.side):
            return
        if self.pessimistic and price < order.price:
            fill = floor_to(min(item.count, order.remaining), SIZE_STEP)  # adverse trade-throughs reach us first
            order.queue = max(ZERO, order.queue - (item.count - fill))
        else:
            ahead = min(item.count, order.queue)
            order.queue -= ahead
            fill = floor_to(min(item.count - ahead, order.remaining), SIZE_STEP)
        if fill > 0:
            self._fill(order, fill, item.created, item.trade_id)

    def _fill(self, order: Order, count: Decimal, at: float, trade_id: str) -> None:
        state = self.markets[order.ticker]
        terms = self.fees.terms_at(self._series_of(state) or "", str(state.row.get("event_ticker") or ""), at)
        model_fee = terms.maker_model_fee(count, order.price) if terms is not None else ZERO
        cash = order.accumulator.fill(-(order.price * count), model_fee)
        account = self.account
        self._tick_area(at)
        account.cash += cash.cash_change
        account.fill_cash += cash.cash_change
        account.fees += cash.trade_fee
        account.rounding += cash.rounding_fee
        account.rebates += cash.rebate
        account.reserved[order.oid] = max(ZERO, account.reserved[order.oid] - count * order.per_contract)
        position = account.positions.get(order.ticker)
        if position is None:
            position = account.positions[order.ticker] = Position(order.ticker, order.side, order.cluster)
        position.lots.append(Lot(count, -cash.cash_change, order.sent_day, order.oid))
        order.remaining -= count
        order.fills.append((at, count))
        self.chain_clock[order.ticker] = at
        self.counts["fills"] += 1
        self._log("fill", at, oid=order.oid, ticker=order.ticker, side=order.side, price=order.price, count=count,
                  trade_id=trade_id, cash_change=cash.cash_change, trade_fee=cash.trade_fee,
                  rounding_fee=cash.rounding_fee, rebate=cash.rebate)
        if account.cash < 0 and not self.config.unfunded:  # the UNFUNDED diagnostic has no cash limit (section 10)
            raise LimitBreach("Simulated cash went negative")
        if order.remaining <= 0:
            self._dead(order, at, "filled")
        self._trim(order.ticker, at)

    def _trim(self, ticker: str, at: float) -> None:
        """At most 1.00 contract per market, filled and resting together: a cancel-race fill trims the newest.

        An order whose cancel is already acknowledged (it can still fill in the clock margin) holds nothing
        open, so it is left out: its late fill trims the replacement to the rest, never kills it.
        """
        live = sorted((order for order in self._live(ticker) if order.cancel_at is None or order.cancel_at > at),
                      key=lambda order: order.oid, reverse=True)
        excess = self._held(ticker) + sum((order.remaining for order in live), ZERO) - ONE
        for order in live:
            if excess <= 0:
                break
            cut = min(excess, order.remaining)
            order.remaining -= cut
            self.account.reserved[order.oid] = max(ZERO, self.account.reserved[order.oid] - cut * order.per_contract)
            excess -= cut
            if order.remaining <= 0:
                self._dead(order, at, "trimmed_one_contract_cap")

    def _dead(self, order: Order, at: float, reason: str) -> None:
        if not order.live:
            return
        self._tick_area(at)
        rested = order.state != "pending"
        order.state, order.died_at = "dead", at
        self.account.reserved.pop(order.oid, None)
        self.account.released.discard(order.oid)
        self.account.replaced_by.pop(order.oid, None)
        if order.oid in self.market_orders.get(order.ticker, []):
            self.market_orders[order.ticker].remove(order.oid)
        if rested and not self.coverage.tape(order.ticker, order.arrives_at, at):
            self.unidentifiable.append(order.oid)  # section 7.7: a tape gap overlapped this resting quote
            self.day_quote_gaps.update(self._entry_days(order.arrives_at, at))  # section 12: those days uncovered
        self._log("dead", at, oid=order.oid, ticker=order.ticker, reason=reason, remaining=order.remaining)

    def _reject(self, order: Order, at: float, reason: str) -> None:
        self._tick_area(at)
        order.state, order.died_at = "rejected", at
        order.buffered = []
        self.account.reserved.pop(order.oid, None)
        self.account.released.discard(order.oid)
        self.account.replaced_by.pop(order.oid, None)
        if order.oid in self.market_orders.get(order.ticker, []):
            self.market_orders[order.ticker].remove(order.oid)
        self.counts["post_only_rejections" if reason.startswith("post_only") else f"rejected_{reason}"] += 1
        self._log("rejected", at, oid=order.oid, ticker=order.ticker, reason=reason)

    def _kill(self, order: Order, at: float, reason: str) -> None:
        """A quote dies at ``at`` (its close time, or a non-active status + L); later prints never fill it."""
        if order.expires_at is None or at < order.expires_at:
            order.expires_at, order.expire_reason = at, reason
            self._schedule(at + self.epsilon, "cutoff", order.oid)

    def _cancel(self, order: Order, at: float, reason: str, replacement: Target | None = None) -> None:
        """Decided at ``at``; acknowledged at at + L (a replacement is sent then); fills count until + epsilon."""
        if order.cancel_at is not None:
            return
        self.counts[f"cancel_{reason}"] += 1
        self._log("cancel", at, oid=order.oid, ticker=order.ticker, reason=reason)
        order.cancel_at, order.cancel_reason = at + self.latency, reason
        if order.state == "resting":
            order.state = "cancelling"
        self._schedule(at + self.latency, "cancel_ack", order.oid, replacement)
        self._schedule(at + self.latency + self.epsilon, "cutoff", order.oid)

    # ------------------------------------------------------------------ internal events
    def _on_arrive(self, item: _Internal) -> None:
        order = self.orders[item.oid]
        if order.state != "pending":
            return
        state = self.markets[order.ticker]
        book = state.book
        ask = book.ask(order.side) if book is not None else None
        if book is None or state.row.get("status") != "active":
            self._reject(order, item.at, "no_book_at_arrival" if book is None else "market_not_active")
            return
        if ask is not None and order.price >= ask:
            self._reject(order, item.at, "post_only_at_arrival")
            return
        displayed = book.size_at(order.side, order.price)
        order.queue = displayed if displayed is not None else UNKNOWN_QUEUE  # 7.3: never assume nobody is ahead
        order.state = "confirming"
        self._schedule(item.at + BOOK_MAX_AGE_S, "confirm_timeout", order.oid)
        closes = ts(state.row.get("close_time"))
        if closes is not None:
            self._kill(order, max(closes, item.at), "market_closed")
        self._log("arrived", item.at, oid=order.oid, ticker=order.ticker, queue=order.queue)
        if item.at > self.config.entry_end:
            self._cancel(order, item.at, "phase_end")

    def _on_confirm_timeout(self, item: _Internal) -> None:
        order = self.orders[item.oid]
        if order.state == "confirming":
            self._confirm(order, None)  # no later book within 120 s: the arrival book alone decides

    def _on_cancel_ack(self, item: _Internal) -> None:
        order = self.orders[item.oid]
        self.account.earmarks.pop(order.oid, None)
        if order.live:
            self.account.released.add(order.oid)  # acknowledged; still fillable (and counted) until ack + epsilon
        if isinstance(item.data, Target):
            self._send(self.markets[order.ticker], item.data, item.at, replacement=True, replaces=order)

    def _on_cutoff(self, item: _Internal) -> None:
        order = self.orders[item.oid]
        end = order.end_at
        if not order.live or end is None or item.at + 1e-9 < end + self.epsilon:
            return
        if order.state == "confirming":
            self._confirm(order, None)
        if order.live:
            cancelled = order.cancel_at is not None and order.cancel_at == end
            self._dead(order, item.at, (order.cancel_reason if cancelled else order.expire_reason) or "cancelled")

    def _on_phase_end(self, item: _Internal) -> None:
        for order in list(self.orders.values()):
            if order.live and order.cancel_at is None and order.state != "pending":
                self._cancel(order, item.at, "phase_end")

    def _on_decision(self, item: _Internal) -> None:
        if item.at > self.config.entry_end:
            return
        self._decide(item.at)
        if item.at + 60 <= self.config.entry_end:
            self._schedule(item.at + 60, "decision")

    # ------------------------------------------------------------------ settlement (section 7.6)
    def _settle(self, state: MarketState, received: float) -> None:
        state.settled = True
        value = dec(state.row.get("settlement_value_dollars"))
        if value is None:
            value = ONE if state.row.get("result") == YES else ZERO
        state.yes_value = value  # kept for every market: section 7.7's lower bound needs unfilled quotes' outcomes
        for order in self._live(state.ticker):
            self._kill(order, received, "settled")
        position = self.account.positions.get(state.ticker)
        if position is None:
            return
        payout_each = value if position.side == YES else ONE - value
        settled_at = ts(state.row.get("settlement_ts")) or received
        self._realize(position, payout_each, settled_at, unresolved=False)
        self.last_settlement_at = max(self.last_settlement_at or settled_at, settled_at)

    def _realize(self, position: Position, payout_each: Decimal, at: float, *, unresolved: bool) -> None:
        account = self.account
        self._tick_area(at)
        payout = position.count * payout_each
        pnl = payout - position.cost
        account.cash += payout
        account.payouts += payout
        account.day_pnl[datetime.fromtimestamp(at, UTC).date().isoformat()] += pnl
        account.realized.append({"ticker": position.ticker, "side": position.side, "cluster": position.cluster,
                                 "count": position.count, "cost": position.cost, "payout": payout, "pnl": pnl,
                                 "at": at, "block": settlement_block(at), "unresolved": unresolved})
        del account.positions[position.ticker]
        self._log("settled", at, ticker=position.ticker, side=position.side, count=position.count,
                  cost=position.cost, payout=payout, pnl=pnl, unresolved=unresolved)

    # ------------------------------------------------------------------ decisions (sections 4.2 and 5)
    def _series_of(self, state: MarketState) -> str | None:
        event = self.events.get(str(state.row.get("event_ticker")))
        name = event.get("series_ticker") if event else None
        return name if isinstance(name, str) else None

    def _cluster(self, state: MarketState) -> str:
        series = self._series_of(state) or ""
        tags = self.series.get(series, {}).get("tags")
        return cluster_of(series, str(state.row.get("event_ticker") or ""), ts(state.row.get("close_time")), tags)

    def _admitted(self, state: MarketState, at: float) -> bool:
        event_ticker = str(state.row.get("event_ticker"))
        decision = admit(state.row, self.events.get(event_ticker), self.series.get(self._series_of(state) or ""), at,
                         window=PROTOCOL_WINDOW, fees=self.fees.status(event_ticker), check_fees=True)
        return decision.admitted

    def _covered(self, state: MarketState, at: float) -> bool:
        """Section 12: book at most 120 s old and a complete tape over the last 120 s."""
        book = state.book
        return (book is not None and at - book.received_at <= BOOK_MAX_AGE_S
                and self.coverage.tape(state.ticker, at - COVERAGE_S, at))

    def _checks(self, state: MarketState, at: float, side: str, price: Decimal) -> str | None:
        """Section 4.2 at price ``price`` on ``side``; None when every check holds."""
        book = state.book
        if book is None or at - book.received_at > BOOK_MAX_AGE_S:
            return "stale_book"
        if not book.two_sided() or book.crossed_or_locked():
            return "one_sided_or_crossed"
        if not self.variant.in_band(price):
            return "outside_band"
        ask = book.ask(side)
        if ask is None or ask <= price:
            return "ask_at_or_below_quote"
        yes_bid, yes_ask = book.best(YES), book.ask(YES)
        if yes_bid is None or yes_ask is None or yes_ask - yes_bid > MAX_SPREAD:
            return "spread_gt_10c"
        closes = ts(state.row.get("close_time"))
        if closes is None or closes - at < CUTOFF_S:
            return "entry_cutoff"
        if not self.config.entry_start <= at <= self.config.entry_end:
            return "outside_entry_days"
        if state.volume_24h(at) < MIN_VOLUME:
            return "volume_lt_25"
        return None

    @staticmethod
    def favourite(book: Book) -> str | None:
        """Section 5.1: YES if the YES mid is above 0.5, NO if below, none at exactly 0.5."""
        yes_bid, yes_ask = book.best(YES), book.ask(YES)
        if yes_bid is None or yes_ask is None:
            return None
        mid = (yes_bid + yes_ask) / 2
        return None if mid == HALF else YES if mid > HALF else NO

    def target(self, state: MarketState, at: float) -> Target | None:
        """Sections 5.1-5.2: the side we bid and the paid price (join, or one valid tick better)."""
        book = state.book
        if book is None or state.grid is None or not book.two_sided():
            return None
        side = self.favourite(book) if self.variant.favourite else baseline_side(state.ticker)
        if side is None:
            return None
        best, ask = book.best(side), book.ask(side)
        if best is None or ask is None:
            return None
        price = best
        if self.variant.improve:
            above = state.grid.next_above(best)
            if above is None or above >= ask:
                return None  # improve needs a spread of at least two ticks and never falls back to joining
            price = above
        if not state.grid.valid(price) or self._checks(state, at, side, price) is not None:
            return None
        return Target(side, price)

    def _keep(self, order: Order, state: MarketState) -> bool:
        """Section 5.5: join keeps q = best bid; improve keeps q = best bid or one tick above it."""
        best = state.book.best(order.side) if state.book is not None else None
        if best is None:
            return False
        if order.price == best:
            return True
        return self.variant.improve and state.grid is not None and state.grid.next_above(best) == order.price

    def _stale_reason(self, order: Order, state: MarketState, at: float) -> str | None:
        """Section 5.6, the coverage rule (12), the entry cutoff (5.7) and rotation (5.8)."""
        if state.row.get("status") != "active":
            return "market_not_active"
        if not self._covered(state, at):
            return "uncovered"
        reason = self._checks(state, at, order.side, order.price)
        if reason is not None:
            return reason
        if self.variant.favourite and state.book is not None and self.favourite(state.book) != order.side:
            return "favourite_flipped"
        if not self._admitted(state, at):
            return "not_admitted"
        if at - self.chain_clock.get(order.ticker, order.sent_at) >= ROTATION_S:
            self.cooldown[order.ticker] = at + ROTATION_S
            return "rotation_6h"
        return None

    def _entry_days(self, start: float, end: float) -> list[str]:
        low, high = max(start, self.config.entry_start), min(end, self.config.entry_end)
        if high < low:
            return []
        first, last = datetime.fromtimestamp(low, UTC).date(), datetime.fromtimestamp(high, UTC).date()
        return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]

    def _count_coverage(self, at: float, day: str) -> None:
        """Section 12: this decision's markets passing section 4.1, how many are covered, and resting-quote gaps.

        The denominator treats the fee lookups as fresh (U10's 26 h rule is about the data being there, which is
        what coverage measures): a recorder outage makes decisions uncovered instead of making markets vanish.
        """
        assumed = FeeStatus(at, at)
        for state in self.markets.values():
            if state.settled or state.row.get("status") != "active":
                continue  # fails U3, so no decision over an admitted market
            event_ticker = str(state.row.get("event_ticker"))
            static = admit(state.row, self.events.get(event_ticker), self.series.get(self._series_of(state) or ""),
                           at, window=PROTOCOL_WINDOW, fees=assumed, check_fees=True)
            if not static.admitted:
                continue
            self.day_decisions[day] += 1
            if self._covered(state, at) and self._admitted(state, at):
                self.day_covered[day] += 1
        for order in self.orders.values():
            if (order.state in ("confirming", "resting", "cancelling")
                    and not self.coverage.tape(order.ticker, max(at - COVERAGE_S, order.arrives_at), at)):
                self.day_quote_gaps.add(day)

    def entry_day_coverage(self) -> dict[str, Any]:
        """Per entry day: decisions, covered decisions and the section 12 verdict on the day; then the phase floor.

        A day with no decision over an admitted market is not covered: the replay cannot tell an empty universe
        from a recorder that was not running, and a covered day must be shown, never assumed.
        """
        days: list[dict[str, Any]] = []
        for offset in range(self.config.days):
            day = (self.config.first_day + timedelta(days=offset)).isoformat()
            decisions, covered = self.day_decisions[day], self.day_covered[day]
            share = Decimal(covered) / Decimal(decisions) if decisions else None
            days.append({"day": day, "decisions": decisions, "covered": covered,
                         "covered_share": str(share.quantize(Decimal("0.0001"))) if share is not None else None,
                         "resting_quote_trade_gap": day in self.day_quote_gaps,
                         "covered_day": share is not None and share >= COVERED_SHARE and day not in self.day_quote_gaps})
        decisions = sum(self.day_decisions[row["day"]] for row in days)
        covered = sum(self.day_covered[row["day"]] for row in days)
        share = Decimal(covered) / Decimal(decisions) if decisions else None
        needed = math.ceil(self.config.days * COVERED_DAYS_NEEDED[self.config.phase] / PHASE_DAYS[self.config.phase])
        covered_days = sum(1 for row in days if row["covered_day"])
        met = covered_days >= needed and (self.config.phase != "TEST" or (share is not None and share >= COVERED_SHARE))
        return {"entry_days": days, "covered_entry_days": covered_days, "covered_entry_days_needed": needed,
                "decision_coverage": str(share.quantize(Decimal("0.0001"))) if share is not None else None,
                "coverage_floor_met": met}

    def _decide(self, at: float) -> None:
        day = datetime.fromtimestamp(at, UTC).date().isoformat()
        self._count_coverage(at, day)
        for order in sorted((order for order in self.orders.values()
                             if order.state in ("confirming", "resting") and order.cancel_at is None),
                            key=lambda order: order.oid):
            state = self.markets[order.ticker]
            reason = self._stale_reason(order, state, at)
            if reason is not None:
                self._cancel(order, at, reason)
            elif not self._keep(order, state):
                target = self.target(state, at)
                if target is not None and target.side == order.side:
                    self.counts["replacements"] += 1
                    self._cancel(order, at, "reprice", replacement=target)
                    self._earmark(order, state, target, at)
                else:
                    self._cancel(order, at, "no_target")
        live_clusters = {order.cluster for order in self.orders.values() if order.live}
        exposed = live_clusters | {position.cluster for position in self.account.positions.values()}
        options: list[tuple[int, Decimal, str, MarketState, Target, str]] = []
        for ticker, state in self.markets.items():
            if (self._live(ticker) or state.settled or self.cooldown.get(ticker, -math.inf) > at
                    or state.row.get("status") != "active" or self._held(ticker) >= ONE):
                continue
            target = self.target(state, at)
            if target is None or not self._covered(state, at) or not self._admitted(state, at):
                continue
            position = self.account.positions.get(ticker)
            if position is not None and position.side != target.side:
                continue  # one side per market: never add the other side to a held position
            cluster = self._cluster(state)
            displayed = (state.book.size_at(target.side, target.price) if state.book is not None else None) or ZERO
            score = state.volume_24h(at) / (displayed + 1)
            options.append((0 if cluster not in exposed else 1, -score, ticker, state, target, cluster))
        for _, _, _ticker, state, target, cluster in sorted(options, key=lambda row: (row[0], row[1], row[2])):
            if cluster in live_clusters:
                continue  # at most one quote rests per risk cluster
            if self._send(state, target, at, replacement=False, cluster=cluster, day=day):
                live_clusters.add(cluster)

    def _order_terms(self, state: MarketState, target: Target, at: float) -> tuple[Decimal, Decimal] | None:
        """(size, reservation per contract) of an order sent now at ``target``; None when it cannot be priced."""
        size = ONE - self._held(state.ticker)
        terms = self.fees.terms_at(self._series_of(state) or "", str(state.row.get("event_ticker") or ""), at)
        if size <= 0 or terms is None:
            return None
        return size, target.price + ceil_to(terms.maker_model_fee(ONE, target.price), FEE_GRID) + RESERVE_PAD

    def _earmark(self, order: Order, state: MarketState, target: Target, at: float) -> None:
        """Section 5.9: hold the extra budget a reprice's replacement will need, ahead of this decision's new quotes."""
        ack = at + self.latency
        planned = self._order_terms(state, target, at)
        if planned is None or ack > self.config.entry_end:
            return
        size, per_contract = planned
        worst = size * max(per_contract, order.per_contract)
        day = datetime.fromtimestamp(ack, UTC).date().isoformat()
        if self.account.blocked_by(order.cluster, day, worst, day_stop=self.config.day_stop,
                                   unfunded=self.config.unfunded, exclude=frozenset({order.oid})) is not None:
            return  # the replacement would be refused anyway: hold nothing back from new quotes
        extra = worst - self.account.reserved.get(order.oid, ZERO)
        if extra > 0:
            self.account.earmarks[order.oid] = (order.cluster, day, extra)

    def _send(self, state: MarketState, target: Target, at: float, *, replacement: bool,
              cluster: str | None = None, day: str | None = None, replaces: Order | None = None) -> bool:
        cluster = cluster or self._cluster(state)
        day = day or datetime.fromtimestamp(at, UTC).date().isoformat()
        if replacement and at > self.config.entry_end:
            # The target was checked at the decision (section 5.5); only the phase end can still stop it.
            self.counts["replacement_skipped"] += 1
            return False
        if any(order.cancel_at is None for order in self._live(state.ticker)):
            return False
        planned = self._order_terms(state, target, at)
        if planned is None:
            if ONE - self._held(state.ticker) > 0:
                self.blocks["fee_terms_unknown"] += 1
            return False
        size, per_contract = planned
        amount = size * per_contract
        exclude: frozenset[int] = frozenset()
        check = amount
        if replaces is not None:
            # The old order may still fill in the clock margin at its own price, and that fill trims this order, so
            # the pair is checked as the dearer of the two (once sent, the old one counts only its excess over it).
            exclude = frozenset({replaces.oid})
            check = size * max(per_contract, replaces.per_contract)
        blocked = self.account.blocked_by(cluster, day, check, day_stop=self.config.day_stop,
                                          unfunded=self.config.unfunded, exclude=exclude)
        if blocked is not None:
            self.blocks[blocked] += 1
            return False
        oid = next(self._oid)
        order = Order(oid, state.ticker, target.side, target.price, size, cluster, at, at + self.latency, day,
                      per_contract, replacement, remaining=size,
                      accumulator=FeeAccumulator(self.grid, rebates=not self.pessimistic))
        self._tick_area(at)
        self.orders[oid] = order
        self.market_orders[state.ticker].append(oid)
        self.account.reserved[oid] = amount
        self.account.order_cluster[oid] = cluster
        self.account.order_day[oid] = day
        if replaces is not None and replaces.live:
            self.account.replaced_by[replaces.oid] = oid
        if not replacement:
            self.chain_clock[state.ticker] = at
        self.counts["replacement_orders" if replacement else "quotes_sent"] += 1
        self._schedule(order.arrives_at, "arrive", oid)
        self._log("sent", at, oid=oid, ticker=state.ticker, side=target.side, price=target.price, size=size,
                  reservation=amount, cluster=cluster, replacement=replacement)
        return True

    # ------------------------------------------------------------------ results (sections 9, 13 and 15)
    def reconcile(self) -> dict[str, Any]:
        """Section 9: rebuild the books from the fill and settlement ledger and require exact agreement.

        Cash = $25 + fill cash changes + payouts; each fill's cash change = -(q x c) - trade fee - rounding +
        rebate; fee, rounding and rebate totals; inventory and cost by market and side; settled P&L by row and in
        total; open exposure; day P&L. Every figure comes from the ledger, so a counter that drifted from the
        ledger is caught. Any mismatch is a defect (section 18) and raises.
        """
        account = self.account
        problems: list[str] = []

        def same(name: str, ours: Decimal, ledger: Decimal) -> None:
            if ours != ledger:
                problems.append(f"{name} {ours} != ledger {ledger}")

        fill_cash = fees = rounding = rebates = payouts = settled_pnl = settled_cost = ZERO
        bought: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        paid: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        settled_rows = 0
        for row in self.ledger:
            if row["kind"] == "fill":
                count, price = Decimal(row["count"]), Decimal(row["price"])
                cash, fee, rounded, rebate = (Decimal(row[key]) for key in
                                              ("cash_change", "trade_fee", "rounding_fee", "rebate"))
                if cash != -(price * count) - fee - rounded + rebate:
                    problems.append(f"fill {row['trade_id']} cash {cash} does not follow its fees")
                fill_cash, fees, rounding, rebates = fill_cash + cash, fees + fee, rounding + rounded, rebates + rebate
                bought[(row["ticker"], row["side"])] += count
                paid[(row["ticker"], row["side"])] -= cash
            elif row["kind"] == "settled":
                count, cost, payout, pnl = (Decimal(row[key]) for key in ("count", "cost", "payout", "pnl"))
                if pnl != payout - cost:
                    problems.append(f"settlement of {row['ticker']} P&L {pnl} != payout - cost")
                key = (row["ticker"], row["side"])
                bought[key] -= count
                paid[key] -= cost
                payouts, settled_pnl, settled_cost = payouts + payout, settled_pnl + pnl, settled_cost + cost
                settled_rows += 1
        same("fill cash", account.fill_cash, fill_cash)
        same("fees", account.fees, fees)
        same("rounding", account.rounding, rounding)
        same("rebates", account.rebates, rebates)
        same("payouts", account.payouts, payouts)
        same("cash", account.cash, START_CASH + fill_cash + payouts)
        same("settled P&L", sum((row["pnl"] for row in account.realized), ZERO), settled_pnl)
        same("day P&L", sum(account.day_pnl.values(), ZERO), settled_pnl)
        if len(account.realized) != settled_rows:
            problems.append(f"{len(account.realized)} realized rows != {settled_rows} ledger settlements")
        open_cost = ZERO
        for key in sorted(set(bought) | {(position.ticker, position.side) for position in account.positions.values()}):
            position = account.positions.get(key[0])
            held = position.count if position is not None and position.side == key[1] else ZERO
            cost = position.cost if position is not None and position.side == key[1] else ZERO
            if held != bought[key] or cost != paid[key]:
                problems.append(f"inventory {key[0]} {key[1]}: {held} for {cost} != ledger {bought[key]} for {paid[key]}")
            open_cost += cost
        same("open exposure", open_cost, -fill_cash - settled_cost)
        reserved = sum(account.reserved.values(), ZERO)
        if any(amount < 0 for amount in account.reserved.values()):
            problems.append("a negative reservation")
        if problems:
            raise LimitBreach("Accounting does not reconcile: " + "; ".join(problems[:5]))
        return {"cash": str(account.cash), "expected_cash": str(START_CASH + fill_cash + payouts),
                "reserved": str(reserved), "free_cash": str(account.cash - reserved), "fees": str(fees),
                "rounding": str(rounding), "rebates": str(rebates), "payouts": str(payouts),
                "settled_pnl": str(settled_pnl), "open_exposure": str(open_cost), "reconciled": True}

    def _lower_bound(self, net: Decimal) -> Decimal:
        """Section 7.7: every unidentifiable quote counts as filled at its price for its remaining size if its side
        lost (or never resolved), capped at 1.00 contract per market; as unfilled if it won."""
        by_ticker: dict[str, list[Order]] = defaultdict(list)
        for oid in self.unidentifiable:
            order = self.orders[oid]
            if order.remaining > 0:
                by_ticker[order.ticker].append(order)
        lower = net
        for ticker, orders in sorted(by_ticker.items()):
            filled = sum((count for order in self.orders.values() if order.ticker == ticker
                          for _, count in order.fills), ZERO)
            room = max(ZERO, ONE - filled)
            state = self.markets.get(ticker)
            value = state.yes_value if state is not None else None
            for order in sorted(orders, key=lambda item: item.per_contract, reverse=True):
                payout = ZERO if value is None else (value if order.side == YES else ONE - value)
                loss_each = order.per_contract - payout  # price + maker fee + the balance-rounding pad
                size = min(order.remaining, room)
                if loss_each > 0 and size > 0:
                    lower -= size * loss_each
                    room -= size
        return lower

    def summary(self, end: float, unresolved: list[dict[str, Any]]) -> dict[str, Any]:
        account = self.account
        last = max(self.config.entry_end + 1, self.last_settlement_at or 0.0)
        if unresolved:
            last = self.config.resolution_end  # 13: D runs to the last settlement, capped at the follow-up end
        days = Decimal(str(min(last, end) - self.config.entry_start)) / Decimal(86400)
        net = account.cash - START_CASH
        clusters: dict[str, Decimal] = defaultdict(lambda: ZERO)
        resolved: dict[str, Decimal] = defaultdict(lambda: ZERO)
        last_settled: dict[str, float] = {}
        unresolved_pnl = ZERO
        for row in account.realized:
            clusters[row["cluster"]] += row["pnl"]
            if row["unresolved"]:
                unresolved_pnl += row["pnl"]
                continue
            resolved[row["cluster"]] += row["pnl"]
            last_settled[row["cluster"]] = max(last_settled.get(row["cluster"], row["at"]), row["at"])
        blocks: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for cluster, at in last_settled.items():  # 4.4: a cluster's block is its LAST settlement's New York date
            blocks[settlement_block(at)] += resolved[cluster]
        traded = {row["cluster"] for row in account.realized if row["count"] >= SIZE_STEP and not row["unresolved"]}
        lower = self._lower_bound(net)
        per_day = (net / days).quantize(Decimal("0.000001")) if days > 0 else None
        lower_per_day = (lower / days).quantize(Decimal("0.000001")) if days > 0 else None
        uses_lower = bool(self.unidentifiable)
        return {
            "label": self.config.label(), "run_kind": self.config.kind,
            "protocol": PROTOCOL_VERSION, "config": self.config.parameters(), "phase": self.config.phase,
            "net_usd": str(net), "days": str(days.quantize(Decimal("0.000001"))),
            "net_per_day_usd_before_opex": str(per_day) if per_day is not None else None,
            "lower_bound_net_usd_unidentifiable": str(lower), "unidentifiable_quotes": len(self.unidentifiable),
            "lower_bound_net_per_day_usd_before_opex": str(lower_per_day) if lower_per_day is not None else None,
            # 7.7: whenever any quote is unidentifiable, every verdict uses the lower bound.
            "verdict_basis": "lower_bound_7_7" if uses_lower else "central",
            "verdict_net_usd": str(lower if uses_lower else net),
            "verdict_net_per_day_usd_before_opex": str(lower_per_day if uses_lower else per_day)
            if per_day is not None else None,
            "capital_days_usd": str(self.capital_area.quantize(Decimal("0.000001"))),
            "counts": dict(self.counts), "limit_blocks": dict(self.blocks),
            "traded_resolved_clusters": len(traded), "settlement_blocks": len(blocks),
            "by_cluster": {key: str(value) for key, value in sorted(clusters.items())},
            "by_block": {key: str(value) for key, value in sorted(blocks.items())},
            "unresolved_pnl_usd_outside_blocks": str(unresolved_pnl),
            "unresolved": unresolved, "accounting": self.reconcile(),
        }


# =========================================================================== reading the recorder's tape
META_LANES = ("markets", "discovery", "fees", "settlement")
META_LOOKBACK_S = 9 * 86400.0
BOOK_LANES = ("books", "book_calls")
_RANK = {"meta": 0, "book": 1, "print": 2}


@dataclass(frozen=True)
class TapeItem:
    at: float
    rank: int
    seq: int
    kind: str
    data: Any


RESTART_LOOKBACK_S = 3 * 86400 + 60  # a recorder restart backfills at most 3 days (older session_started rows)


def load_coverage(root: Path, start: float, end: float) -> Coverage:
    """Trade-tape coverage and watch intervals (the tape is complete for a ticker only while it is watched).

    A recorder restart keeps prints only of the tickers its "resumed" row lists. Every other ticker the tape still
    had open (admitted after the recorder last saved its state, say) is closed at the restart's
    ``keeps_prints_from`` (the earliest print the new session can vouch for; older rows without it: 3 days before
    the restart), so no later coverage row vouches for prints nobody kept.
    """
    coverage = Coverage()
    for record in iter_records(root, frozenset({"trade_coverage"}), start=start - 3 * 86400, end=end + 86400):
        low, high = record.get("from"), record.get("to")
        if isinstance(low, int) and isinstance(high, int):
            scope = record.get("scope")
            (coverage.exchange if scope == "exchange" else coverage.by_ticker[str(scope)]).add(low, high)
    opened: dict[str, float] = {}
    restart: tuple[Any, float] | None = None  # (session, cut) until that session's first watch row

    def close_stale(keep: Iterable[str]) -> None:
        assert restart is not None
        kept = set(keep)
        for ticker in [ticker for ticker in opened if ticker not in kept]:
            coverage.watched[ticker].add(opened.pop(ticker), restart[1])  # empty when the cut is before the start

    starts = (record for record in iter_records(root, frozenset({"gaps"}), end=end)
              if record.get("kind") == "session_started")
    watches = (record for record in iter_records(root, frozenset({"admissions"}), end=end)
               if record.get("kind") == "watch")
    for record in heapq.merge(starts, watches, key=lambda record: (float(record["at"]), int(record["seq"]))):
        if record["kind"] == "session_started":
            if restart is not None:
                close_stale(())  # the previous session started and resumed nothing
            cut = record.get("keeps_prints_from")
            restart = (record.get("session"), float(cut) if isinstance(cut, (int, float)) and not isinstance(cut, bool)
                       else float(record["at"]) - RESTART_LOOKBACK_S)
            continue
        if restart is not None and record.get("session") == restart[0]:
            # The new session's first watch row: its "resumed" list, if it is one, is what it keeps recording.
            close_stale((record.get("tickers") or []) if record.get("action") == "resumed" else ())
            restart = None
        for ticker in record.get("tickers") or []:
            if record.get("action") in ("start", "resumed"):
                opened.setdefault(ticker, float(record.get("at_watch") or record["at"]))
            elif record.get("action") == "stop" and ticker in opened:
                coverage.watched[ticker].add(opened.pop(ticker), float(record["at"]))
    if restart is not None:
        close_stale(())
    for ticker, since in opened.items():
        coverage.watched[ticker].add(since, end)
    return coverage


def record_items(record: dict[str, Any]) -> Iterator[TapeItem]:
    """The replay inputs inside one recorder record."""
    lane, kind, at, seq = record["lane"], record["kind"], float(record["at"]), int(record["seq"])
    if lane == "books" and kind == "book":
        yield TapeItem(at, _RANK["book"], seq, "book", record)
    elif lane == "book_calls":
        for ticker in record.get("unchanged") or []:
            yield TapeItem(at, _RANK["book"], seq, "book_unchanged", ticker)
    elif lane == "markets":
        for row in record.get("rows") or []:
            yield TapeItem(at, _RANK["meta"], seq, "market_full" if "full" in row else "market_dyn",
                           (row, kind == "sweep"))
    elif lane == "settlement":
        for row in record.get("rows") or []:
            yield TapeItem(at, _RANK["meta"], seq, "market_settlement", row)
    elif lane == "discovery":
        if kind == "events_page":
            for row in record.get("rows") or []:
                yield TapeItem(at, _RANK["meta"], seq, "event", row)
        elif kind == "series_list":
            for row in record.get("rows") or []:
                yield TapeItem(at, _RANK["meta"], seq, "series", row)
        elif kind == "series" and isinstance(record.get("series"), dict):
            yield TapeItem(at, _RANK["meta"], seq, "series", record["series"])
    elif lane == "fees":
        raw = record.get("body")
        body: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if kind == "series_fee_changes":
            yield TapeItem(at, _RANK["meta"], seq, "series_fees", body.get("series_fee_change_arr") or [])
        elif kind == "event_fee_changes":
            yield TapeItem(at, _RANK["meta"], seq, "event_fees",
                           (record.get("event_ticker"), body.get("event_fee_changes") or []))


def trade_buckets(root: Path, start: float, end: float, directory: Path) -> list[Path]:
    """A lossless derived copy: Family A prints split by created-time UTC day (deduplicated when read)."""
    files: dict[str, Any] = {}
    with contextlib.ExitStack() as stack:
        for record in iter_records(root, frozenset({"trades"}), start=start - 86400, end=end + 86400):
            for row in record.get("rows") or []:
                created = ts(row.get("created_time"))
                if created is None or not start - 86400 <= created <= end:
                    continue
                day = datetime.fromtimestamp(created, UTC).date().isoformat()
                if day not in files:
                    files[day] = stack.enter_context(
                        gzip.open(directory / f"trades-{day}.jsonl.gz", "at", encoding="utf-8"))
                files[day].write(json.dumps({"r": float(record["at"]), "row": row}, separators=(",", ":")) + "\n")
    return [directory / f"trades-{day}.jsonl.gz" for day in sorted(files)]


def prints_from(paths: list[Path]) -> Iterator[TapeItem]:
    """Prints by created time, one copy per trade id (first receipt kept; conflicting copies never merged)."""
    for path in paths:
        rows: dict[str, tuple[float, dict[str, Any]]] = {}
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                row, received = item["row"], float(item["r"])
                key = str(row.get("trade_id"))
                if key not in rows or received < rows[key][0]:
                    rows[key] = (received, row)
        ordered = sorted((ts(row.get("created_time")) or 0.0, key, received, row)
                         for key, (received, row) in rows.items())
        for created, _key, received, row in ordered:
            parsed = parse_print(row, received)
            if parsed is not None:
                yield TapeItem(created, _RANK["print"], 0, "print", parsed)


def seed_books(root: Path, before: float, tickers: Iterable[str] | None = None,
               lookback: float = META_LOOKBACK_S) -> list[dict[str, Any]]:
    """The newest book record of each ticker received before ``before`` (within ``lookback``).

    The recorder writes a book only when it changes and lists it as "unchanged" after that, so a quiet
    market's current book can be hours or days old when a phase starts. Segments are read newest first and the
    scan stops once every wanted ticker has one; each segment's hash is checked before it is read.
    """
    wanted = None if tickers is None else set(tickers)
    found: dict[str, dict[str, Any]] = {}
    segments = sorted((segment for segment in load_index(root) if segment.lane == "books"
                       and segment.first_at < before and segment.last_at >= before - lookback),
                      key=lambda segment: (segment.last_at, segment.last_seq), reverse=True)
    for segment in segments:
        if wanted is not None and wanted <= found.keys():
            break
        path = root / segment.path
        if file_sha256(path) != segment.sha256:
            raise ValueError(f"Recorder segment {segment.path} does not match its index hash")
        newest: dict[str, dict[str, Any]] = {}
        for record in iter_segment(path):
            ticker = record.get("ticker")
            if (record.get("kind") == "book" and isinstance(ticker, str) and ticker not in found
                    and (wanted is None or ticker in wanted) and before - lookback <= float(record["at"]) < before):
                newest[ticker] = record  # later lines are newer
        found.update(newest)
    return sorted(found.values(), key=lambda record: (float(record["at"]), int(record["seq"])))


def tape(root: Path, start: float, end: float, scratch: Path, *, quotes_end: float | None = None,
         seed_tickers: Iterable[str] | None = None, permit: Permit | None = None) -> Iterator[TapeItem]:
    """Every replay input in time order: metadata and books by receive time, prints by created time.

    Metadata is read from 9 days before ``start`` (a market's full row may date from its first sight, up to
    8 days before its close) to ``end`` (settlements); books and prints only until ``quotes_end`` (no quote
    rests after the last entry day ends). Books are read from 10 minutes before ``start``, after each
    ticker's newest earlier book (``seed_books``), so "unchanged" calls always have a book to re-date.
    Books and prints of the frozen TEST days are read only with a TEST permit (checked again here): a range that
    reaches them is refused, and the look-backs (the seed books up to 9 days back, a day of earlier prints) never
    hand one out either.
    """
    quotes_end = end if quotes_end is None else min(end, quotes_end)
    if permit is not None:
        permit.verify(permit.config)
    window = permit.test_window() if permit is not None else checkout_test_window()
    hidden = window if window is not None and (permit is None or permit.config.phase != "TEST") else None
    if hidden is not None and start - 600 <= hidden[1] and quotes_end >= hidden[0]:
        raise FreezeError("Books and prints of the frozen TEST days are read only with a TEST permit")
    streams: list[Iterator[dict[str, Any]]] = [iter(seed_books(root, start - 600, seed_tickers))]
    streams += [iter_records(root, frozenset({lane}), start=start - 600, end=quotes_end) for lane in BOOK_LANES]
    streams += [iter_records(root, frozenset({lane}), start=start - META_LOOKBACK_S, end=end) for lane in META_LANES]
    records = heapq.merge(*streams, key=lambda record: (float(record["at"]), int(record["seq"])))

    def items() -> Iterator[TapeItem]:
        for record in records:
            yield from record_items(record)

    prints = prints_from(trade_buckets(root, start, quotes_end, scratch))
    for item in heapq.merge(items(), prints, key=lambda item: (item.at, item.rank)):
        if (hidden is not None and item.kind in ("book", "book_unchanged", "print")
                and hidden[0] <= item.at <= hidden[1]):
            continue  # a TEST day's book or print, reached through a look-back: never handed out without a permit
        yield item


def feed(replay: FamilyAReplay, items: Iterable[TapeItem]) -> float:
    """Drive ``replay`` from tape items; returns the last item time.

    A book or print from the frozen TEST days reaches only an account built from a TEST permit.
    """
    last = replay.config.entry_start
    window = None if replay.test_permitted else replay.test_window
    for item in items:
        if (window is not None and item.kind in ("book", "book_unchanged", "print")
                and window[0] <= item.at <= window[1]):
            raise FreezeError("A book or print from the frozen TEST days reached a run without a TEST permit")
        last = max(last, item.at)
        if item.kind == "book":
            book = item.data.get("orderbook_fp") or {}
            replay.on_book(str(item.data["ticker"]), book.get("yes_dollars"), book.get("no_dollars"), item.at)
        elif item.kind == "book_unchanged":
            replay.on_book_unchanged(str(item.data), item.at)
        elif item.kind == "market_full":
            row, sweep = item.data
            replay.on_market_row(row["full"], item.at, full=True, sweep=sweep)
        elif item.kind == "market_dyn":
            row, sweep = item.data
            replay.on_market_row({"ticker": row["ticker"], **(row.get("dyn") or {})}, item.at, full=False, sweep=sweep)
        elif item.kind == "market_settlement":
            replay.on_market_row(item.data, item.at, full=True)
        elif item.kind == "event":
            replay.on_event_row(item.data, item.at)
        elif item.kind == "series":
            replay.on_series_row(item.data, item.at)
        elif item.kind == "series_fees":
            replay.on_series_fee_changes(item.data, item.at)
        elif item.kind == "event_fees":
            event, rows = item.data
            if isinstance(event, str):
                replay.on_event_fee_changes(event, rows, item.at)
        elif item.kind == "print":
            replay.on_print(item.data)
    return last


def run_replay(root: Path, config: ReplayConfig, research_dir: Path, *, worklog: Path | None = None) -> dict[str, Any]:
    """Refuse first (protocol and freeze hashes), then score one SIMULATED account on the recorded tape."""
    permit = check_scoring_allowed(config, research_dir, worklog=worklog, recorder_root=root)
    end = config.resolution_end
    coverage = load_coverage(root, config.entry_start, end)
    replay = FamilyAReplay(config, coverage, permit=permit)
    books_from = config.entry_start - 600
    seeds = [ticker for ticker, spans in coverage.watched.items() if spans.covers(books_from, books_from)]
    quotes_end = config.entry_end + 3600
    if not replay.test_permitted and replay.test_window is not None:
        quotes_end = min(quotes_end, replay.test_window[0] - 1)  # a VAL tail never reads E1's books
    with tempfile.TemporaryDirectory(prefix="familya-trades-") as scratch:
        last = feed(replay, tape(root, config.entry_start, end, Path(scratch), quotes_end=quotes_end,
                                 seed_tickers=seeds, permit=permit))
    return replay.finish(last)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nightcrawler.kalshi_familya", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay", help="Score one variant on recorded data (SIMULATED account)")
    replay.add_argument("--data-dir", type=Path, required=True, help="DATA_DIR (reads <dir>/kalshi_recorder)")
    replay.add_argument("--phase", choices=("TRAIN", "VAL", "TEST"), required=True)
    replay.add_argument("--first-day", type=date.fromisoformat, required=True)
    replay.add_argument("--days", type=int, default=7)
    replay.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    replay.add_argument("--model", choices=("primary", "pessimistic"), default="primary")
    replay.add_argument("--latency-ms", type=int, default=1000)
    replay.add_argument("--day-stop", choices=("protocol", "live_style"), default="protocol")
    replay.add_argument("--unfunded", action="store_true", help="Diagnostic only: just the $2 cluster limit")
    replay.add_argument("--latency-stress", action="store_true",
                        help="A labelled latency stress (section 8): --latency-ms may then differ from the frozen L")
    replay.add_argument("--research-dir", type=Path, default=Path("research/kalshi_edge_search"))
    replay.add_argument("--out", type=Path)
    check = sub.add_parser("check", help="Say whether a phase may be scored (protocol and freeze hashes)")
    check.add_argument("--phase", choices=("TRAIN", "VAL", "TEST"), required=True)
    check.add_argument("--first-day", type=date.fromisoformat, required=True)
    check.add_argument("--days", type=int, default=7)
    check.add_argument("--variant", choices=sorted(VARIANTS), default="A1")
    check.add_argument("--research-dir", type=Path, default=Path("research/kalshi_edge_search"))
    check.add_argument("--data-dir", type=Path, help="DATA_DIR: TEST needs the recorder's witness of the freeze")
    sub.add_parser("hashes", help="Print the replay code's SHA-256 (FREEZE.json's code_sha256)")
    args = parser.parse_args(argv)
    if args.command == "hashes":
        print(json.dumps(code_hashes(), indent=2, sort_keys=True))
        return 0
    if args.command == "check":
        try:
            check_scoring_allowed(ReplayConfig(args.variant, args.phase, args.first_day, args.days), args.research_dir,
                                  recorder_root=args.data_dir / "kalshi_recorder" if args.data_dir else None)
        except FreezeError as exc:
            print(f"refused: {exc}")
            return 1
        print("allowed")
        return 0
    try:
        config = ReplayConfig(args.variant, args.phase, args.first_day, args.days, latency_ms=args.latency_ms,
                              model=args.model, day_stop=args.day_stop, unfunded=args.unfunded,
                              latency_stress=args.latency_stress)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    try:
        result = run_replay(args.data_dir / "kalshi_recorder", config, args.research_dir)
    except FreezeError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

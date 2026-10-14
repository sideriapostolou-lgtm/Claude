"""Kalshi's Liquidity Incentive Program (LIP) score, exactly, as pure functions (PRACTICE and research only).

Ported from the rewards research's ``rules/lip_score.py`` (research/kalshi_rewards/PLAYBOOK.md section 1; 39 tests
there), with its one known defect fixed: :func:`floor_cent` floored a 28-digit decimal approximation, so a payout a
hair under a cent boundary could round up to it; it now floors the exact fraction.

Source of every rule: the CFTC self-certification "Amendment to August 2025 Liquidity Incentive Program"
(rules07152610358, Appendix A, effective 2026-07-30, runs to 2027-01-01) and help.kalshi.com article 13823851.

Per snapshot (one a second, at a random moment inside the second), for each side (a YES ask at p is a NO bid at
1 - p):

1. walk the price levels from the highest bid down, adding the WHOLE level each time;
2. the Reference price is the first level where the running total reaches Target / 5;
3. stop at the first level where the running total reaches the Target; every bid on every level walked qualifies
   (the last level counts whole, so the total can pass the Target);
4. if the side runs out of bids first, nothing on that side qualifies and the snapshot pays nobody.

``score(bid) = DF ** N * size`` with N the ticks between the Reference and the bid (0 at or above it). Each side is
normalized to 1; an owner's snapshot score is its YES share plus its NO share (at most 2). A Time Period pays
``reward * sum(owner snapshot scores) / (2 * snapshots)``, nothing under $1.00, otherwise rounded down to the cent.

Exact arithmetic: prices, sizes, discount factors and scores are :class:`fractions.Fraction`. No network, no key and
no order path: this module only counts.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

YES, NO = "yes", "no"
US = "us"  # the owner id of our own (practice) orders
OTHERS = "others"  # the anonymous public book (the API aggregates each level)
ONE = Fraction(1)
CENT = Decimal("0.01")
MIN_PAYOUT = Fraction(1)


def frac(value: Any) -> Fraction:
    """An exact Fraction from str / int / float / Decimal / Fraction (``"0.5300"`` -> 53/100)."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("a boolean is not a number")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("not a finite number")
        return Fraction(repr(value))
    return Fraction(str(value))


# ---------------------------------------------------------------------- the price grid
@dataclass(frozen=True)
class Grid:
    """A market's price grid from its ``price_ranges``: ``bands`` are ``(start, end, step)`` in dollars; a price p
    belongs to the band with ``start <= p < end`` (the last band also owns its end). N is the number of grid steps
    between two prices; every FX, metals, gas and Coin Race 15-minute market is ``linear_cent``."""

    bands: tuple[tuple[Fraction, Fraction, Fraction], ...]

    @classmethod
    def from_price_ranges(cls, ranges: Sequence[Mapping[str, Any]]) -> Grid:
        bands = tuple(sorted((frac(item["start"]), frac(item["end"]), frac(item["step"])) for item in ranges))
        if not bands:
            raise ValueError("empty price_ranges")
        return cls(bands)

    def step_up_from(self, price: Fraction) -> Fraction:
        for start, end, step in self.bands:
            if start <= price < end:
                return step
        raise ValueError(f"price {price} is outside the grid")

    def on_grid(self, price: Any) -> bool:
        value = frac(price)
        for index, (start, end, step) in enumerate(self.bands):
            last = index == len(self.bands) - 1
            if start <= value < end or (last and value == end):
                return (value - start) % step == 0
        return False

    def ticks_between(self, low: Any, high: Any) -> int:
        """Grid steps from ``low`` up to ``high`` (high >= low); an off-grid price raises."""
        lo, hi = frac(low), frac(high)
        if hi < lo:
            raise ValueError("hi < lo")
        if not (self.on_grid(lo) and self.on_grid(hi)):
            raise ValueError(f"off-grid price in ticks_between({lo}, {hi})")
        steps, price = 0, lo
        while price < hi:
            price += self.step_up_from(price)
            steps += 1
        if price != hi:
            raise ValueError(f"walk overshot: {lo}->{hi}")
        return steps


LINEAR_CENT = Grid.from_price_ranges([{"start": "0", "end": "1", "step": "0.01"}])


# ---------------------------------------------------------------------- bids and books
@dataclass(frozen=True)
class Bid:
    side: str
    price: Fraction  # dollars, strictly between 0 and 1
    size: Fraction  # contracts (Kalshi allows 0.01 steps)
    owner: str = OTHERS

    def __init__(self, side: str, price: Any, size: Any, owner: str = OTHERS) -> None:
        if side not in (YES, NO):
            raise ValueError(f"bad side {side!r}")
        value, amount = frac(price), frac(size)
        if amount < 0:
            raise ValueError("negative size")
        if not 0 < value < 1:
            raise ValueError(f"bid price must be strictly between 0 and 1, got {value}")
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "price", value)
        object.__setattr__(self, "size", amount)
        object.__setattr__(self, "owner", owner)


def yes_ask_as_no_bid(price: Any, size: Any, owner: str = US) -> Bid:
    """A resting sell-YES at p is a NO bid at 1 - p (the filing: "a yes ask is counted as a bid for no")."""
    return Bid(NO, ONE - frac(price), size, owner)


def no_ask_as_yes_bid(price: Any, size: Any, owner: str = US) -> Bid:
    return Bid(YES, ONE - frac(price), size, owner)


def bids_from_orderbook(book: Mapping[str, Any], owner: str = OTHERS) -> list[Bid]:
    """Bids from a ``GET /markets/{ticker}/orderbook`` reply or its ``orderbook_fp`` object (YES and NO bids,
    aggregated per level, with no owner)."""
    raw = book.get("orderbook_fp", book)
    out: list[Bid] = []
    for side, key in ((YES, "yes_dollars"), (NO, "no_dollars")):
        for price, count in raw.get(key) or []:
            if frac(count) > 0:
                out.append(Bid(side, price, count, owner))
    return out


def combine_book(public: Iterable[Bid], ours: Iterable[Bid], ours_in_book: bool) -> list[Bid]:
    """Our orders merged into the public book: added on top (hypothetical), or, when the public book already holds
    them (a live recording of our own resting orders), subtracted from the anonymous size at their level."""
    mine = list(ours)
    if not ours_in_book:
        return list(public) + mine
    levels: dict[tuple[str, Fraction, str], Fraction] = {}
    for bid in public:
        key = (bid.side, bid.price, bid.owner)
        levels[key] = levels.get(key, Fraction(0)) + bid.size
    for bid in mine:
        key = (bid.side, bid.price, OTHERS)
        left = levels.get(key, Fraction(0)) - bid.size
        if left < 0:
            raise ValueError(f"our {bid.side} order {bid.size}@{bid.price} is larger than the public level")
        levels[key] = left
    return [Bid(side, price, size, owner) for (side, price, owner), size in levels.items() if size > 0] + mine


# ---------------------------------------------------------------------- one side of one snapshot
@dataclass
class SideResult:
    side: str
    qualified: bool
    reference_price: Fraction | None
    qualifying_total: Fraction  # the size walked (0 when the side did not qualify)
    levels: list[tuple[Fraction, Fraction, int, Fraction]]  # (price, level size, ticks N, weight DF**N) walked
    raw: dict[str, Fraction] = field(default_factory=dict)  # owner -> sum of DF**N * size
    normalized: dict[str, Fraction] = field(default_factory=dict)  # owner -> share of the side (sums to 1)
    reason: str = ""


def score_side(bids: Iterable[Bid], side: str, target: Any, discount_factor: Any,
               grid: Grid = LINEAR_CENT) -> SideResult:
    """Steps 1-4 for one side, then each bid's score and the side's normalization."""
    goal, df = frac(target), frac(discount_factor)
    by_price: dict[Fraction, list[Bid]] = {}
    for bid in bids:
        if bid.side == side and bid.size > 0:
            by_price.setdefault(bid.price, []).append(bid)
    if not by_price:
        return SideResult(side, False, None, Fraction(0), [], reason="no bids on this side")
    total, reference, walked, reached = Fraction(0), None, [], False
    for price in sorted(by_price, reverse=True):
        total += sum((bid.size for bid in by_price[price]), Fraction(0))
        walked.append(price)
        if reference is None and total >= goal / 5:
            reference = price
        if total >= goal:
            reached = True
            break
    if not reached or reference is None:
        return SideResult(side, False, reference, Fraction(0), [], reason=f"side total {total} < target {goal}")
    levels: list[tuple[Fraction, Fraction, int, Fraction]] = []
    raw: dict[str, Fraction] = {}
    for price in walked:
        ticks = 0 if price >= reference else grid.ticks_between(price, reference)
        weight = df ** ticks
        levels.append((price, sum((bid.size for bid in by_price[price]), Fraction(0)), ticks, weight))
        for bid in by_price[price]:
            raw[bid.owner] = raw.get(bid.owner, Fraction(0)) + weight * bid.size
    whole = sum(raw.values(), Fraction(0))
    if whole == 0:  # only with DF = 0 and every qualifying size below the Reference
        return SideResult(side, False, reference, total, levels, raw, {}, reason="all scores zero (DF = 0)")
    return SideResult(side, True, reference, total, levels, raw, {owner: value / whole for owner, value in raw.items()})


# ---------------------------------------------------------------------- one snapshot
@dataclass
class SnapshotResult:
    valid: bool  # False: an excluded snapshot (it still counts in the period's snapshots and scores nothing)
    reason: str
    yes: SideResult | None
    no: SideResult | None
    scores: dict[str, Fraction]  # owner -> YES share + NO share (0..2); empty when excluded

    def score(self, owner: str = US) -> Fraction:
        return self.scores.get(owner, Fraction(0))


def is_crossed(bids: Iterable[Bid]) -> bool:
    """True when the best YES bid plus the best NO bid is $1 or more: such orders would trade, not rest."""
    items = list(bids)
    best_yes = max((bid.price for bid in items if bid.side == YES and bid.size > 0), default=None)
    best_no = max((bid.price for bid in items if bid.side == NO and bid.size > 0), default=None)
    return best_yes is not None and best_no is not None and best_yes + best_no >= 1


def score_snapshot(bids: Iterable[Bid], target: Any, discount_factor: Any, grid: Grid = LINEAR_CENT,
                   market_open: bool = True, reject_crossed: bool = True) -> SnapshotResult:
    """Every owner's snapshot score. ``reject_crossed`` raises on a crossed book (a hypothetical order of ours
    would have traded instead of resting)."""
    if not market_open:
        return SnapshotResult(False, "market not open for trading", None, None, {})
    items = list(bids)
    if reject_crossed and is_crossed(items):
        raise ValueError("crossed book: a yes bid and a no bid sum to >= $1 (that order would trade)")
    yes = score_side(items, YES, target, discount_factor, grid)
    no = score_side(items, NO, target, discount_factor, grid)
    if not (yes.qualified and no.qualified):
        why = "; ".join(f"{side.side}: {side.reason}" for side in (yes, no) if not side.qualified)
        return SnapshotResult(False, "not two-sided: " + why, yes, no, {})
    scores: dict[str, Fraction] = {}
    for side in (yes, no):
        for owner, value in side.normalized.items():
            scores[owner] = scores.get(owner, Fraction(0)) + value
    return SnapshotResult(True, "", yes, no, scores)


# ---------------------------------------------------------------------- one Time Period
def floor_cent(amount: Any) -> Decimal:
    """Dollars rounded DOWN to the cent, exactly (no decimal approximation first)."""
    value = frac(amount)
    cents = math.floor(value * 100)
    return (Decimal(cents) / 100).quantize(CENT)


@dataclass
class PeriodResult:
    owner: str
    total_snapshots: int
    valid_snapshots: int
    owner_score_sum: Fraction
    all_score_sum: Fraction
    tp_score: Fraction  # the Time Period Liquidity Provider Score (0..1)
    raw_payout: Fraction  # dollars, before the $1 minimum and the rounding
    paid: Decimal  # dollars credited
    reason: str = ""


def paid_amount(raw_payout: Any) -> Decimal:
    """The $1.00 minimum (under it, nothing; never carried over), then rounded down to the cent."""
    value = frac(raw_payout)
    return floor_cent(value) if value >= MIN_PAYOUT else Decimal("0.00")


def payout_from_tp_score(tp_score: Any, reward: Any, valid_snapshots: int, total_snapshots: int,
                         owner: str = US) -> PeriodResult:
    """``payout = TP score * reward * non-excluded / total``; at least $1.00 or nothing; floored to the cent."""
    tp, pool = frac(tp_score), frac(reward)
    if total_snapshots <= 0:
        raise ValueError("total_snapshots must be positive")
    if not 0 <= valid_snapshots <= total_snapshots:
        raise ValueError("valid_snapshots out of range")
    raw = tp * pool * Fraction(valid_snapshots, total_snapshots)
    why = "" if raw >= MIN_PAYOUT else "below the $1.00 minimum"
    return PeriodResult(owner, total_snapshots, valid_snapshots, Fraction(0), Fraction(0), tp, raw, paid_amount(raw),
                        why)


def period_payout(snapshots: Iterable[SnapshotResult], reward: Any, owner: str = US,
                  total_snapshots: int | None = None) -> PeriodResult:
    """Pay one Time Period from its snapshots. ``total_snapshots`` is the period's seconds (900 for 15 minutes);
    seconds missing from a recording then count as excluded, which understates the pay if the book was really
    two-sided then."""
    snaps = list(snapshots)
    total = len(snaps) if total_snapshots is None else int(total_snapshots)
    if total < len(snaps):
        raise ValueError("total_snapshots smaller than the snapshots given")
    valid = [snap for snap in snaps if snap.valid]
    mine = sum((snap.score(owner) for snap in valid), Fraction(0))
    everyone = sum((sum(snap.scores.values(), Fraction(0)) for snap in valid), Fraction(0))
    if not valid or everyone == 0:
        return PeriodResult(owner, total, 0, Fraction(0), Fraction(0), Fraction(0), Fraction(0), Decimal("0.00"),
                            "no non-excluded snapshots")
    result = payout_from_tp_score(mine / everyone, reward, len(valid), total, owner)
    result.owner_score_sum, result.all_score_sum = mine, everyone
    return result


def payout_shortcut(owner_snapshot_scores: Iterable[Any], reward: Any, total_snapshots: int) -> Fraction:
    """The raw payout as ``reward * sum(owner scores) / (2 * snapshots)``: every non-excluded snapshot sums to
    exactly 2 over all owners, and an excluded one gives everyone 0."""
    return frac(reward) * sum((frac(value) for value in owner_snapshot_scores), Fraction(0)) / (2 * total_snapshots)


# ---------------------------------------------------------------------- program parameters
def _when(text: str) -> datetime:
    return datetime.fromisoformat(text)


@dataclass(frozen=True)
class Program:
    """One ``GET /incentive_programs`` liquidity row: the market, its Target, discount factor and reward per Time
    Period, and the period itself."""

    market_ticker: str
    target: Fraction
    discount_factor: Fraction
    reward: Fraction  # dollars per Time Period
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def snapshots(self) -> int:
        """One snapshot a second; a fractional-second bound is floored (UNVERIFIED: the filing says whole seconds)."""
        return int(self.seconds)


def program_from_api(row: Mapping[str, Any]) -> Program:
    """``period_reward`` is in centi-cents (500000 = $50), ``discount_factor_bps`` in basis points and
    ``target_size_fp`` a fixed-point contract string."""
    if row.get("incentive_type") != "liquidity":
        raise ValueError("not a liquidity program")
    return Program(market_ticker=str(row["market_ticker"]), target=frac(row["target_size_fp"]),
                   discount_factor=Fraction(int(row["discount_factor_bps"]), 10000),
                   reward=Fraction(int(row["period_reward"]), 10000), start=_when(str(row["start_date"])),
                   end=_when(str(row["end_date"])))

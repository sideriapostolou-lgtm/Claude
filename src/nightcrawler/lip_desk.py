"""The practice LIP desk: pretend-money quoting of Kalshi's reward (LIP) markets, scored with the exact LIP formula.

PRACTICE ONLY. This module holds no client, no key and no order path, and it opens no network connection: it
replays what the public Kalshi recorder wrote (:mod:`nightcrawler.lip_feed`) and keeps paper books. Every number it
produces is pretend money; nothing here can place, cancel or amend a real order.

What it simulates (research/kalshi_rewards/PREREG.md section 8, fixed before any practice result):

* **Policies** (:data:`POLICIES`): rest 10 contracts per side at each side's Reference price (``ref_stop5``, stop 300 s
  before the close; ``ref_close``, to the close), at the best bid (``best_stop5``), and ``ref_pyth_pull``: the
  Reference policy that cancels the side a Pyth move makes stale (FX 0.5 bp, metals and gas 1 bp, measured from the
  Pyth price at the newest Kalshi book) and re-places it only on a later book that shows the move (its mid moved
  the Pyth move's way since the pull) or :data:`PULL_HOLD_S` after the pull (PREREG.md addendum 1). It never quotes
  without a
  Pyth price received in the last :data:`PYTH_FRESH_S` seconds, and a window counts for it only when Pyth covered at
  least :data:`PYTH_ACTIVE_SHARE` of the window's seconds ("active only when Pyth data exists").
* **Fills** (:data:`FILL_MODELS`), the rewards review's models (simreview_adv ``simlib_r.py``), ported event for
  event: our order joins the BACK of its level; prints at our price eat the queue ahead first; a print through our
  price fills us; the visible level shrinking below the queue ahead shrinks it (cancels come from behind us); a
  public bid on the other side crossing our stale price fills us in proportion to the share of the poll interval our
  order was live (``timed``), and an order we cancelled stays exposed to a crossing the next poll reveals, in
  proportion to how long it rested in that interval. ``fee_timed`` lets a crosser take us only when it gains more
  than Kalshi's taker fee ``0.07 P (1 - P)``. Post-only (an order that would cross the newest book is not placed),
  self-trade prevention, a YES and a NO contract net to $1 at once, decisions act :data:`LATENCY_S` after the book.
* **Reward**: the LIP score of our resting orders at two moments a second (:data:`OFFSETS`) against the newest
  book, ``reward * mean score / (2 * seconds)``, nothing under $1, rounded down to the cent
  (:func:`nightcrawler.lip_score.paid_amount`). Every 15-minute series is ``quadratic``: no maker fee.
* **Marks**: each fill at the public mid 60 s later (the settlement value after the close) and at settlement.
* **Accounts** (:data:`ACCOUNTS`): every policy with no budget per market-period (both fill models; the research
  metric of the playbook's go/no-go bar), and cash-carrying paper accounts ``A45`` (EUR/USD only, $45) and ``A250``
  (the five FX pairs, $250) per policy on the ``timed`` model: resting orders and open positions lock cash until the
  window settles; the reward is credited at settlement (real payouts come a day or more later).

A window is VOID (it counts nowhere) when its feed was incomplete (no poll in its first :data:`FIRST_POLL_S`
seconds, two polls more than :data:`MAX_POLL_GAP_S` apart, or a recorder gap over it) or when no result arrived
:data:`VOID_AFTER_S` after its close.
"""

from __future__ import annotations

import bisect
import heapq
import math
import statistics
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .lip_feed import (
    FX,
    FX_SERIES,
    NO,
    SERIES,
    SYMBOL_SERIES,
    YES,
    BookSnap,
    Levels,
    MarketFacts,
    Print,
    ProgramRow,
    book_from_record,
    call_from_record,
    gap_from_record,
    market_rows_from_record,
    parse_pyth,
    prints_from_record,
    programs_from_record,
    series_of,
)
from .lip_score import paid_amount

EPS = 1e-7
LATENCY_S = 0.25  # from seeing a book to our cancel/replace taking effect (the review's default)
OFFSETS = (0.25, 0.75)  # the score moments inside each second (the expected value over Kalshi's random moment)
MARK_S = 60.0
FIRST_POLL_S = 10.0
MAX_POLL_GAP_S = 10.0
VOID_AFTER_S = 7200.0
PYTH_FRESH_S = 5.0
PULL_HOLD_S = 5.0  # a pulled side comes back on a book showing the move, or this long after the pull
PYTH_ACTIVE_SHARE = 0.9
FX_PERIODS_PER_DAY = 67.3  # the playbook's 7-day average of FX 15-minute periods a day
TAKER_FEE = 0.07  # Kalshi's general taker fee coefficient: fee = 0.07 * P * (1 - P) a contract

SEEN_PRINTS = 500_000  # print ids remembered for de-duplication (the recorder's trade pages overlap)
PRUNE_EVERY_S = 600.0
FORGET_S = 2 * 86_400.0  # books, market facts, programs and gaps of markets this far behind the clock are dropped
# Event kinds, in the order ties are processed (the review's: book < trade < action < pull < stop < score; a window
# opens before anything at its first instant, and Pyth prices land after the book and print of the same instant).
OPEN, POLL, PRINT, PYTH, ACTION, PULL, STOP, CLOSE, SCORE = range(9)


@dataclass(frozen=True)
class Policy:
    name: str
    place: str  # "ref" (each side's Reference price) or "best" (each side's best bid)
    size: float = 10.0
    stop_s: float = 300.0  # cancel everything this long before the close (0: quote to the close)
    pyth_pull: bool = False


POLICIES: tuple[Policy, ...] = (
    Policy("ref_stop5", "ref", 10.0, 300.0),
    Policy("ref_close", "ref", 10.0, 0.0),
    Policy("best_stop5", "best", 10.0, 300.0),
    Policy("ref_pyth_pull", "ref", 10.0, 300.0, pyth_pull=True),
)
POLICY_BY_NAME = {policy.name: policy for policy in POLICIES}
FILL_MODELS = ("timed", "fee_timed")


@dataclass(frozen=True)
class AccountPlan:
    name: str
    series: tuple[str, ...]
    start_cash: float
    shard: int = 0


ACCOUNTS: tuple[AccountPlan, ...] = (
    AccountPlan("A45", ("KXEURUSD15M",), 45.0, 0),
    AccountPlan("A250", FX_SERIES, 250.0, 0),
)


# ---------------------------------------------------------------------- LIP scoring, float (cross-checked with lip_score)
def df_powers(discount_factor: float, count: int = 101) -> list[float]:
    return [discount_factor ** power for power in range(count)]


def side_eval(levels: Levels, target: float, dfp: Sequence[float], price: int | None = None,
              size: float = 0.0) -> tuple[bool, int | None, float, float]:
    """One side of one snapshot: ``(qualified, reference cents, total score, our score)`` with our ``size`` at
    ``price`` merged into its level (``levels``: public bids, best first)."""
    fifth = target / 5.0
    cumulative, reference = 0.0, None
    prices: list[int] = []
    sizes: list[float] = []
    inserted = not (price is not None and size > 0)
    index, count, ours = 0, len(levels), -1
    while True:
        if not inserted and (index >= count or levels[index][0] <= price):  # type: ignore[operator]
            assert price is not None
            if index < count and levels[index][0] == price:
                level_price, level_size = price, levels[index][1] + size
                index += 1
            else:
                level_price, level_size = price, size
            inserted = True
            ours = len(prices)
        elif index < count:
            level_price, level_size = levels[index]
            index += 1
        else:
            return False, reference, 0.0, 0.0
        cumulative += level_size
        prices.append(level_price)
        sizes.append(level_size)
        if reference is None and cumulative >= fifth - EPS:
            reference = level_price
        if cumulative >= target - EPS:
            break
    assert reference is not None
    total = 0.0
    for level_price, level_size in zip(prices, sizes, strict=True):
        below = reference - level_price
        total += level_size if below <= 0 else level_size * dfp[below]
    mine = 0.0
    if ours >= 0 and price is not None:
        below = reference - price
        mine = size if below <= 0 else size * dfp[below]
    return True, reference, total, mine


def ref_price(levels: Levels, target: float) -> int | None:
    fifth, cumulative = target / 5.0, 0.0
    for price, size in levels:
        cumulative += size
        if cumulative >= fifth - EPS:
            return price
    return None


def size_at(levels: Levels, price: int) -> float:
    for level_price, size in levels:
        if level_price == price:
            return size
        if level_price < price:
            return 0.0
    return 0.0


def size_at_or_above(levels: Levels, price: int) -> float:
    total = 0.0
    for level_price, size in levels:
        if level_price < price:
            break
        total += size
    return total


# ---------------------------------------------------------------------- a market window
@dataclass
class Poll:
    """One poll of a market's book as we saw it (``at``: when it arrived)."""

    at: float
    yes: Levels
    no: Levels
    mid: float | None  # cents
    best_yes: int | None
    best_no: int | None
    ref_yes: int | None
    ref_no: int | None


class Window:
    """One liquidity program's Time Period on one market, shared by every resident quoting it."""

    def __init__(self, program: ProgramRow, facts: MarketFacts) -> None:
        series = series_of(program.ticker)
        if series is None:
            raise ValueError(f"not a reward series: {program.ticker}")
        info = SERIES[series]
        self.ticker, self.series, self.group, self.shard = program.ticker, series, info.group, info.shard
        self.open, self.close = program.start, program.end
        self.reward, self.target, self.df = program.reward, program.target, program.discount_factor
        self.dfp = df_powers(self.df)
        self.facts = facts
        self.symbol = info.pyth_symbol
        self.pull_bps = info.pull_bps
        self.polls: list[Poll] = []
        self.poll_times: list[float] = []
        self.cur = -1
        self.desired_cache: dict[tuple[str, float], list[tuple[int | None, int | None]]] = {}
        self.score_cache: dict[tuple[Any, ...], tuple[bool, int | None, float, float]] = {}
        self.sims: list[Sim] = []
        self.void: str | None = None
        self.max_gap = 0.0
        self.closed = False
        self.pyth_ref: float | None = None  # the Pyth price at the newest poll
        self.pyth_last: float | None = None
        self.pyth_last_at: float | None = None
        self.pyth_seconds: set[int] = set()
        self.pending_pull: dict[int, bool] = {}

    @property
    def seconds(self) -> int:
        return round(self.close - self.open)

    def add_poll(self, at: float, yes: Levels, no: Levels) -> int:
        by = yes[0][0] if yes else None
        bn = no[0][0] if no else None
        mid = (by + (100 - bn)) / 2.0 if by is not None and bn is not None else None
        previous = self.poll_times[-1] if self.poll_times else self.open
        self.max_gap = max(self.max_gap, at - previous)
        self.polls.append(Poll(at, yes, no, mid, by, bn, ref_price(yes, self.target), ref_price(no, self.target)))
        self.poll_times.append(at)
        self.cur = len(self.polls) - 1
        self.pyth_ref = self.pyth_last
        return self.cur

    def desired(self, place: str, size: float, index: int) -> tuple[int | None, int | None]:
        """The policy's target prices on poll ``index`` or ``(None, None)`` when a guard fails: both prices defined,
        neither crosses the other side's best bid, and with our size both sides reach the Target."""
        cache = self.desired_cache.setdefault((place, size), [])
        while len(cache) <= index:
            poll = self.polls[len(cache)]
            dy, dn = (poll.best_yes, poll.best_no) if place == "best" else (poll.ref_yes, poll.ref_no)
            ok = dy is not None and dn is not None and poll.best_yes is not None and poll.best_no is not None
            if ok:
                assert dy is not None and dn is not None and poll.best_yes is not None and poll.best_no is not None
                ok = dy + poll.best_no < 100 and dn + poll.best_yes < 100
            if ok:
                ok = (side_eval(poll.yes, self.target, self.dfp, dy, size)[0]
                      and side_eval(poll.no, self.target, self.dfp, dn, size)[0])
            cache.append((dy, dn) if ok else (None, None))
        return cache[index]

    def mid_at(self, at: float, settle: float) -> float:
        """The public mid in dollars at ``at`` from the newest poll at or before it; the settlement value at or after
        the close, or when a side was empty."""
        if at >= self.close:
            return settle
        index = bisect.bisect_right(self.poll_times, at) - 1
        mid = self.polls[max(0, index)].mid if self.polls else None
        return settle if mid is None else mid / 100.0

    def pyth_share(self) -> float:
        return len(self.pyth_seconds) / max(1, self.seconds)


class _Order:
    __slots__ = ("ahead", "cancelled", "left", "level", "placed", "price")

    def __init__(self, price: int, ahead: float, left: float, placed: float) -> None:
        self.price, self.ahead, self.left, self.placed = price, ahead, left, placed
        self.level = ahead  # the last public size seen at our price
        self.cancelled: float | None = None


class Account:
    """A cash-carrying paper account (one policy, one fill model): cash per shard, locked by its windows' resting
    orders and open positions until each window settles."""

    def __init__(self, plan: AccountPlan, policy: Policy, model: str = "timed") -> None:
        self.plan, self.policy, self.model = plan, policy, model
        self.name = f"{plan.name}:{policy.name}"
        self.cash: dict[int, float] = {plan.shard: plan.start_cash}
        self.low = plan.start_cash
        self.sims: list[Sim] = []
        self.periods = 0
        self.reward = 0.0
        self.contracts = 0.0

    def available(self, shard: int) -> float:
        return self.cash.get(shard, 0.0) - sum(sim.committed() for sim in self.sims if sim.window.shard == shard)

    def equity(self) -> float:
        return sum(self.cash.values())

    def settle(self, sim: Sim, value: float, reward: float) -> None:
        shard = sim.window.shard
        self.cash[shard] = self.cash.get(shard, 0.0) + value + reward
        if sim in self.sims:
            self.sims.remove(sim)
        self.periods += 1
        self.reward += reward
        self.contracts += sim.contracts()
        self.low = min(self.low, self.equity())

    def drop(self, sim: Sim) -> None:
        """A void window: its money never moved (the window counts nowhere)."""
        if sim in self.sims:
            self.sims.remove(sim)

    def row(self) -> dict[str, Any]:
        return {"account": self.name, "plan": self.plan.name, "policy": self.policy.name, "model": self.model,
                "series": list(self.plan.series), "start_usd": self.plan.start_cash,
                "equity_usd": round(self.equity(), 4), "low_usd": round(self.low, 4),
                "low_share": round(self.low / self.plan.start_cash, 4) if self.plan.start_cash else None,
                "periods": self.periods, "reward_usd": round(self.reward, 2), "contracts": round(self.contracts, 2),
                "open_windows": len(self.sims)}


class Sim:
    """One resident (policy x fill model x account) quoting one window: a port of the review's ``simulate``."""

    def __init__(self, window: Window, policy: Policy, model: str, account: Account | None = None) -> None:
        if model not in FILL_MODELS:
            raise ValueError(f"unknown fill model {model!r}")
        self.window, self.policy, self.model, self.account = window, policy, model, account
        self.fee = model == "fee_timed"
        self.orders: list[_Order | None] = [None, None]
        self.ghosts: list[list[_Order]] = [[], []]
        # per side: (the newest poll at the pull, its mid, the pull time) until the side may quote again
        self.pulled: list[tuple[int, float | None, float] | None] = [None, None]
        self.cash = 0.0
        self.pos = [0.0, 0.0]
        self.fills: list[tuple[float, int, int, float, str]] = []
        self.fees = 0.0
        self.placed = self.cancelled = self.rejected = 0
        self.score_sum = 0.0
        self.valid_moments = self.quoted_moments = 0
        self.stopped = False
        self.why = {"at": 0.0, "through": 0.0, "cross": 0.0}

    # ------------------------------------------------------------------ money
    def committed(self) -> float:
        held = sum(order.price * order.left / 100.0 for order in self.orders if order is not None)
        held += sum(ghost.price * ghost.left / 100.0 for ghosts in self.ghosts for ghost in ghosts)
        return held + max(0.0, -self.cash)

    def contracts(self) -> float:
        return sum(fill[3] for fill in self.fills)

    def _fill(self, side: int, order: _Order, size: float, at: float, reason: str) -> None:
        self.why[reason] += size
        self.cash -= order.price * size / 100.0  # every 15-minute reward series is "quadratic": no maker fee
        self.pos[side] += size
        pair = min(self.pos)
        if pair > 0:
            self.pos[YES] -= pair
            self.pos[NO] -= pair
            self.cash += pair
        self.fills.append((at, side, order.price, size, reason))
        order.left -= size
        if order.left <= 1e-9 and self.orders[side] is order:
            self.orders[side] = None

    def _fee_ok(self, side: int, price: int, poll: Poll) -> bool:
        """Would a crosser paying the taker fee gain by taking our order at ``price``?"""
        if poll.mid is None:
            return False
        fair = poll.mid if side == YES else 100.0 - poll.mid
        theirs = (100 - price) / 100.0
        return (price - fair) > TAKER_FEE * 100.0 * theirs * (1 - theirs) + 1e-9

    def _cancel(self, side: int, at: float) -> None:
        order = self.orders[side]
        if order is None:
            return
        if order.left > 1e-9:  # timed models: exposed to a crossing the next poll reveals
            order.cancelled = at
            self.ghosts[side].append(order)
        self.orders[side] = None
        self.cancelled += 1

    def _place(self, side: int, price: int, at: float) -> None:
        window, policy = self.window, self.policy
        if self.pulled[side] is not None:
            return
        if policy.pyth_pull and (window.pyth_last_at is None or at - window.pyth_last_at > PYTH_FRESH_S):
            return  # never quote without a live Pyth price
        other = self.orders[1 - side]
        if other is not None and other.price + price >= 100:  # self-trade prevention: cancel the resting one
            self._cancel(1 - side, at)
        size = policy.size
        if self.account is not None:
            available = self.account.available(window.shard)
            size = min(size, math.floor((available + 1e-9) / (price / 100.0)))
            if size < 1:
                return
        poll = window.polls[window.cur]
        mine, theirs = (poll.yes, poll.no) if side == YES else (poll.no, poll.yes)
        if size_at_or_above(theirs, 100 - price) > 0:  # post-only: it would cross the newest book
            self.rejected += 1
            return
        self.orders[side] = _Order(price, size_at(mine, price), float(size), at)
        self.placed += 1

    # ------------------------------------------------------------------ events
    def on_poll(self, index: int, at: float) -> None:
        window = self.window
        poll = window.polls[index]
        previous = window.polls[index - 1].at if index > 0 else None
        for side in (YES, NO):
            mine, theirs = (poll.yes, poll.no) if side == YES else (poll.no, poll.yes)
            used = 0.0
            if self.ghosts[side]:
                for ghost in self.ghosts[side]:
                    crossing = size_at_or_above(theirs, 100 - ghost.price) - used
                    if crossing <= 1e-12 or previous is None or ghost.cancelled is None:
                        continue
                    size = min(ghost.left, crossing)
                    if self.fee and not self._fee_ok(side, ghost.price, poll):
                        size = 0.0
                    span = at - previous
                    if span > 1e-9:
                        size *= max(0.0, min(1.0, (ghost.cancelled - max(previous, ghost.placed)) / span))
                    if size > 1e-12:
                        self._fill(side, ghost, size, at, "cross")
                        used += size
                self.ghosts[side] = []
            order = self.orders[side]
            if order is None:
                continue
            level = size_at(mine, order.price)
            order.level = level
            order.ahead = min(order.ahead, level)
            crossing = size_at_or_above(theirs, 100 - order.price) - used
            if crossing > 1e-12:
                size = min(order.left, crossing)
                if self.fee and not self._fee_ok(side, order.price, poll):
                    size = 0.0
                if size > 0 and previous is not None:
                    span = at - previous
                    if span > 1e-9 and order.placed > previous:
                        size *= max(0.0, min(1.0, (at - order.placed) / span))
                if size > 1e-12:
                    self._fill(side, order, size, at, "cross")

    def on_print(self, item: Print) -> None:
        order = self.orders[item.side]
        if order is None or item.at < self.window.open or item.at >= self.window.close:
            return
        if item.price < order.price:  # the taker swept through our level
            size, reason = min(order.left, item.size), "through"
            order.ahead = 0.0
        elif item.price == order.price:
            use = min(order.ahead, item.size)
            order.level = max(0.0, order.level - item.size)
            order.ahead -= use
            size, reason = min(order.left, item.size - use), "at"
        else:
            return
        if size > 1e-12:
            self._fill(item.side, order, size, item.at, reason)

    def on_action(self, index: int, at: float) -> None:
        window = self.window
        for side in (YES, NO):
            pulled = self.pulled[side]
            if pulled is None or index <= pulled[0]:
                continue
            mid, way = window.polls[index].mid, (1.0 if side == NO else -1.0)  # NO pulled on an up move
            if at - pulled[2] >= PULL_HOLD_S or (mid is not None and pulled[1] is not None
                                                 and (mid - pulled[1]) * way > 0):
                self.pulled[side] = None
        if self.stopped or at >= window.close - self.policy.stop_s or at < window.open or window.cur < 0:
            return
        dy, dn = window.desired(self.policy.place, self.policy.size, index)
        for side, target in ((YES, dy), (NO, dn)):
            order = self.orders[side]
            if target is None:
                self._cancel(side, at)
            elif order is None or order.price != target:
                self._cancel(side, at)
                self._place(side, target, at)

    def on_pull(self, side: int, at: float) -> None:
        if self.orders[side] is not None:
            self._cancel(side, at)
        window = self.window
        self.pulled[side] = (window.cur, window.polls[window.cur].mid if window.cur >= 0 else None, at)

    def on_stop(self, at: float) -> None:
        self.stopped = True
        self._cancel(YES, at)
        self._cancel(NO, at)

    def on_close(self) -> None:
        """Trading ends: nothing rests or fills after the close."""
        self.stopped = True
        self.orders = [None, None]
        self.ghosts = [[], []]

    def on_score(self) -> None:
        window = self.window
        if window.cur < 0:
            return
        poll = window.polls[window.cur]
        yes_order, no_order = self.orders
        results = []
        for side, order, levels in ((YES, yes_order, poll.yes), (NO, no_order, poll.no)):
            key: tuple[Any, ...] = (window.cur, side, order.price, order.left) if order is not None else (
                window.cur, side)
            found = window.score_cache.get(key)
            if found is None:
                found = (side_eval(levels, window.target, window.dfp, order.price, order.left) if order is not None
                         else side_eval(levels, window.target, window.dfp))
                window.score_cache[key] = found
            results.append(found)
        if yes_order is not None and no_order is not None:
            self.quoted_moments += 1
        ry, rn = results
        if ry[0] and rn[0]:
            self.valid_moments += 1
            self.score_sum += (ry[3] / ry[2] if ry[2] > 0 else 0.0) + (rn[3] / rn[2] if rn[2] > 0 else 0.0)

    # ------------------------------------------------------------------ the result
    def result(self, settle: float) -> dict[str, Any]:
        window = self.window
        final = self.cash + self.pos[YES] * settle + self.pos[NO] * (1 - settle)
        mark60 = 0.0
        for at, side, price, size, _ in self.fills:
            mid = window.mid_at(at + MARK_S, settle)
            mark60 += size * ((mid - price / 100.0) if side == YES else ((1 - mid) - price / 100.0))
        mark60 -= self.fees
        seconds = window.seconds
        moments = seconds * len(OFFSETS)
        raw = window.reward * (self.score_sum / len(OFFSETS)) / (2.0 * seconds) if seconds > 0 else 0.0
        paid = float(paid_amount(raw))
        contracts = self.contracts()
        return {
            "ticker": window.ticker, "series": window.series, "group": window.group, "open": window.open,
            "close": window.close, "day": _day(window.close), "policy": self.policy.name, "model": self.model,
            "account": None if self.account is None else self.account.name,
            "reward_pool_usd": window.reward, "target": window.target,
            "gross_raw_usd": round(raw, 6), "reward_usd": paid, "fills": len(self.fills),
            "contracts": round(contracts, 4), "cross_contracts": round(self.why["cross"], 4),
            "at_contracts": round(self.why["at"], 4), "through_contracts": round(self.why["through"], 4),
            "fill_settle_usd": round(final, 6), "fill_m60_usd": round(mark60, 6),
            "net_settle_usd": round(paid + final, 6), "net_m60_usd": round(paid + mark60, 6),
            "orders_placed": self.placed, "orders_cancelled": self.cancelled, "post_only_rejects": self.rejected,
            "share_valid": round(self.valid_moments / moments, 4) if moments else 0.0,
            "share_quoted": round(self.quoted_moments / moments, 4) if moments else 0.0,
            "end_yes": round(self.pos[YES], 4), "end_no": round(self.pos[NO], 4),
            "pyth_share": round(window.pyth_share(), 4) if window.symbol else None,
            "pyth_active": (window.pyth_share() >= PYTH_ACTIVE_SHARE) if self.policy.pyth_pull else None,
            "result": window.facts.result,
        }


def _day(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).date().isoformat()


# ---------------------------------------------------------------------- the desk
@dataclass(order=True)
class _Event:
    at: float
    rank: int
    seq: int
    kind: int = field(compare=False)
    ticker: str = field(compare=False)
    payload: Any = field(compare=False, default=None)


@dataclass
class DeskCounters:
    records: int = 0
    polls: int = 0
    prints: int = 0
    pyth: int = 0
    programs: int = 0
    windows: int = 0
    settled: int = 0
    void: int = 0
    late_records: int = 0


class LipDesk:
    """Every resident on every reward window, fed records in time order and advanced to a watermark.

    :meth:`feed` takes recorder records (any lanes, any order inside a batch) and queues their events;
    :meth:`advance` processes every event at or before ``watermark`` and returns the results of the windows that
    finished (settled, or void). Events older than the last watermark arrive too late and are counted, not used.
    """

    def __init__(self, *, policies: Sequence[Policy] = POLICIES, models: Sequence[str] = FILL_MODELS,
                 accounts: Sequence[AccountPlan] = ACCOUNTS, series: Iterable[str] | None = None,
                 latency_s: float = LATENCY_S, started_at: float | None = None) -> None:
        self.policies = tuple(policies)
        self.models = tuple(models)
        self.series = frozenset(series) if series is not None else frozenset(SERIES)
        self.latency_s = latency_s
        self.accounts = [Account(plan, policy) for plan in accounts for policy in self.policies]
        self.windows: dict[str, Window] = {}  # by market ticker (one open program window per market at a time)
        self.waiting: dict[tuple[str, float], ProgramRow] = {}
        self.facts: dict[str, MarketFacts] = {}
        self.books: dict[str, BookSnap] = {}
        self.last_poll: dict[str, tuple[float, BookSnap]] = {}  # each market's newest poll before its window opened
        self.gaps: list[tuple[float, float]] = []
        self.heap: list[_Event] = []
        self.seq = 0
        self.watermark = -math.inf if started_at is None else started_at
        self.started_at = started_at
        self.seen_programs: set[tuple[str, float, float]] = set()
        self.seen_prints: OrderedDict[str, None] = OrderedDict()
        self.saw_calls = False
        self.counters = DeskCounters()
        self.pruned_at = -math.inf

    # ------------------------------------------------------------------ input
    def _push(self, at: float, kind: int, ticker: str, payload: Any = None) -> None:
        self.seq += 1
        heapq.heappush(self.heap, _Event(at, kind, self.seq, kind, ticker, payload))

    def feed(self, records: Iterable[Mapping[str, Any]]) -> None:
        batch = list(records)
        if not self.saw_calls and any(record.get("kind") == "book_call" for record in batch):
            self.saw_calls = True  # the recorder lists every poll: a written book is only the poll's new state
        for record in batch:
            self.counters.records += 1
            kind = record.get("kind")
            if kind == "book":
                book = book_from_record(record)
                if book is not None and series_of(book.ticker) in self.series:
                    self.books[book.ticker] = book
                    if not self.saw_calls:  # without call rows every written book is a poll
                        self._poll(book.ticker, book.received_at)
                continue
            if kind == "book_call":
                call = call_from_record(record)
                if call is not None and call.ok:
                    for ticker in call.changed + call.unchanged:
                        if series_of(ticker) in self.series:
                            self._poll(ticker, call.received_at)
                continue
            if kind == "trades":
                for item in prints_from_record(record):
                    if series_of(item.ticker) in self.series and item.trade_id not in self.seen_prints:
                        self.seen_prints[item.trade_id] = None
                        if len(self.seen_prints) > SEEN_PRINTS:
                            self.seen_prints.popitem(last=False)
                        self._event(item.at, PRINT, item.ticker, item)
                continue
            if kind == "gap":
                gap = gap_from_record(record)
                # The print tape cannot be checked from the books: a recorder gap on it (or on everything) voids
                # the windows it touches. Book gaps show up as poll gaps, which the window checks itself.
                if gap is not None and (gap.lane in ("all", "trades", "trades_lip")
                                        or gap.cause == "recorder_not_running"):
                    start = gap.start if gap.start is not None else -math.inf
                    self.gaps.append((start, gap.end if gap.end is not None else start))
                continue
            for program in programs_from_record(record):
                self._program(program)
            for ticker, row in market_rows_from_record(record):
                window = self.windows.get(ticker)
                if window is not None:  # only a market with a program window: facts of any other are never needed
                    window.facts.merge(row)
                elif any(key[0] == ticker for key in self.waiting):
                    self.facts.setdefault(ticker, MarketFacts(ticker)).merge(row)
            for tick in parse_pyth(record):
                series = SYMBOL_SERIES.get(tick.symbol)
                if series is not None and series in self.series:
                    self._event(tick.at, PYTH, series, tick)

    def remember(self, records: Iterable[Mapping[str, Any]]) -> None:
        """Books written before the desk started: kept as each market's newest book (a later unchanged poll means
        "still this book"), never played."""
        for record in records:
            book = book_from_record(record)
            if book is not None and series_of(book.ticker) in self.series:
                self.books[book.ticker] = book

    def _event(self, at: float, kind: int, ticker: str, payload: Any) -> None:
        if at < self.watermark:
            self.counters.late_records += 1
            return
        self._push(at, kind, ticker, payload)

    def _poll(self, ticker: str, at: float) -> None:
        book = self.books.get(ticker)
        if book is None:
            return
        self._event(at, POLL, ticker, book)

    def _program(self, program: ProgramRow) -> None:
        key = (program.ticker, program.start, program.end)
        series = series_of(program.ticker)
        if key in self.seen_programs or series is None or series not in self.series or program.reward <= 0:
            return
        self.seen_programs.add(key)
        self.counters.programs += 1
        self.waiting[(program.ticker, program.start)] = program
        late = program.start < self.watermark  # it began before we heard of it: we did not see it from its open
        self._push(max(program.start, self.watermark), OPEN, program.ticker, (program, late))

    # ------------------------------------------------------------------ windows
    def _open(self, program: ProgramRow, late: bool) -> None:
        self.waiting.pop((program.ticker, program.start), None)
        if program.ticker in self.windows:  # an overlapping duplicate program: keep the first
            return
        facts = self.facts.pop(program.ticker, None) or MarketFacts(program.ticker)
        window = Window(program, facts)
        if late or (self.started_at is not None and program.start < self.started_at):
            window.void = "joined_late"
        for policy in self.policies:
            for model in self.models:
                window.sims.append(Sim(window, policy, model))
        for account in self.accounts:
            if window.series in account.plan.series:
                sim = Sim(window, account.policy, account.model, account)
                account.sims.append(sim)
                window.sims.append(sim)
        self.windows[program.ticker] = window
        self.counters.windows += 1
        seed = self.last_poll.pop(program.ticker, None)
        if seed is not None and seed[0] >= window.open - FIRST_POLL_S:  # the book as it stood at the open
            index = window.add_poll(seed[0], seed[1].yes, seed[1].no)
            if seed[0] + self.latency_s >= window.open:
                self._push(seed[0] + self.latency_s, ACTION, window.ticker, index)
        for second in range(window.seconds):
            for offset in OFFSETS:
                if window.open + second + offset >= self.watermark:
                    self._push(window.open + second + offset, SCORE, window.ticker)
        for stop in {policy.stop_s for policy in self.policies if policy.stop_s > 0}:
            self._push(window.close - stop, STOP, window.ticker, stop)
        self._push(window.close, CLOSE, window.ticker)

    def _finish(self, window: Window, now: float) -> list[dict[str, Any]] | None:
        """The window's result rows once it settled, one void row when it is void, or None while it waits."""
        if not window.closed:
            return None
        facts = window.facts
        void = window.void
        if void is None:
            if not window.polls or window.polls[0].at > window.open + FIRST_POLL_S:
                void = "no_first_poll"
            elif max(window.max_gap, window.close - window.polls[-1].at) > MAX_POLL_GAP_S:
                void = "poll_gap"
            elif any(start <= window.close and end >= window.open for start, end in self.gaps):
                void = "recorder_gap"
        if void is None and facts.result is None:
            if now < window.close + VOID_AFTER_S:
                return None
            void = "no_result"
        if void is None and now < window.close + MARK_S:
            return None
        del self.windows[window.ticker]
        if void is not None:
            self.counters.void += 1
            for sim in window.sims:
                if sim.account is not None:
                    sim.account.drop(sim)
            return [{"ticker": window.ticker, "series": window.series, "group": window.group,
                     "open": window.open, "close": window.close, "day": _day(window.close), "void": void}]
        settle = 1.0 if facts.result == "yes" else 0.0
        rows = []
        for sim in window.sims:
            row = sim.result(settle)
            if sim.account is not None:
                sim.account.settle(sim, row["fill_settle_usd"], row["reward_usd"])
            rows.append(row)
        self.counters.settled += 1
        return rows

    # ------------------------------------------------------------------ the clock
    def advance(self, watermark: float) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while self.heap and self.heap[0].at <= watermark:
            event = heapq.heappop(self.heap)
            self._apply(event)
        self.watermark = max(self.watermark, watermark)
        for window in list(self.windows.values()):
            rows = self._finish(window, self.watermark)
            if rows is not None:
                out.extend(rows)
        if math.isfinite(self.watermark) and self.watermark - self.pruned_at >= PRUNE_EVERY_S:
            self._prune(self.watermark)
        return out

    def _prune(self, now: float) -> None:
        """A desk that runs for weeks keeps only what can still matter: every market window adds a book, a poll seed,
        market facts and a program key, which are dropped once it is long finished."""
        self.pruned_at = now
        cutoff = now - FORGET_S
        live = set(self.windows) | {ticker for ticker, _ in self.waiting}
        self.books = {ticker: book for ticker, book in self.books.items()
                      if ticker in live or book.received_at >= cutoff}
        self.last_poll = {ticker: seed for ticker, seed in self.last_poll.items() if seed[0] >= cutoff}
        self.facts = {ticker: fact for ticker, fact in self.facts.items() if ticker in live}
        self.seen_programs = {key for key in self.seen_programs if key[2] >= cutoff}
        self.gaps = [(start, end) for start, end in self.gaps if end >= cutoff]

    def _apply(self, event: _Event) -> None:
        kind, at = event.kind, event.at
        if kind == PYTH:
            self.counters.pyth += 1
            for open_window in self.windows.values():
                if open_window.series == event.ticker and not open_window.closed:
                    self._pyth(open_window, event.payload.price, at)
            return
        if kind == OPEN:
            self._open(*event.payload)
            return
        window = self.windows.get(event.ticker)
        if window is None and kind == POLL:
            self.last_poll[event.ticker] = (at, event.payload)
            return
        if window is None or window.closed:
            return
        if kind == POLL:
            if at < window.open or at >= window.close:
                return
            book: BookSnap = event.payload
            self.counters.polls += 1
            index = window.add_poll(at, book.yes, book.no)
            for sim in window.sims:
                sim.on_poll(index, at)
            self._push(at + self.latency_s, ACTION, window.ticker, index)
        elif kind == PRINT:
            self.counters.prints += 1
            for sim in window.sims:
                sim.on_print(event.payload)
        elif kind == ACTION:
            for sim in window.sims:
                sim.on_action(event.payload, at)
        elif kind == PULL:
            window.pending_pull.pop(event.payload, None)
            for sim in window.sims:
                if sim.policy.pyth_pull:
                    sim.on_pull(event.payload, at)
        elif kind == STOP:
            for sim in window.sims:
                if sim.policy.stop_s == event.payload:
                    sim.on_stop(at)
        elif kind == CLOSE:
            window.closed = True
            for sim in window.sims:
                sim.on_close()
        elif kind == SCORE:
            for sim in window.sims:
                sim.on_score()

    def _pyth(self, window: Window, price: float, at: float) -> None:
        window.pyth_last, window.pyth_last_at = price, at
        if window.open <= at < window.close:
            window.pyth_seconds.add(int(at - window.open))
        if window.pyth_ref is None:
            window.pyth_ref = price
            return
        if window.pull_bps is None or window.pyth_ref <= 0:
            return
        move = 1e4 * math.log(price / window.pyth_ref)
        if abs(move) < window.pull_bps:
            return
        side = NO if move > 0 else YES  # up: our NO bid (a cheap YES offer) is stale; down: our YES bid
        if window.pending_pull.get(side):
            return
        if any(sim.policy.pyth_pull and sim.orders[side] is not None for sim in window.sims):
            window.pending_pull[side] = True
            self._push(at + self.latency_s, PULL, window.ticker, side)

    # ------------------------------------------------------------------ views
    def open_windows(self) -> list[dict[str, Any]]:
        return [{"ticker": window.ticker, "series": window.series, "open": window.open, "close": window.close,
                 "polls": len(window.polls), "void": window.void, "closed": window.closed}
                for window in sorted(self.windows.values(), key=lambda item: (item.close, item.ticker))]


def replay(records: Iterable[Mapping[str, Any]], **options: Any) -> tuple[LipDesk, list[dict[str, Any]]]:
    """Run the desk over recorded records to the end of time: ``(desk, every window result row)``."""
    desk = LipDesk(**options)
    desk.feed(sorted(records, key=lambda row: (float(row.get("at") or 0.0), int(row.get("seq") or 0))))
    return desk, desk.advance(math.inf)


# ---------------------------------------------------------------------- the scorecard
def _range95(values: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    mean = statistics.fmean(values)
    if len(values) < 2:
        return mean, None, None
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - half, mean + half


def scorecard(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The daily scorecard: per UTC day, policy, fill model and family (and the day's ``all``), the unfunded
    market-periods only (account rows are the accounts' own). A Pyth-policy window without Pyth coverage is left
    out ("inactive")."""
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    inactive: dict[tuple[str, str, str, str], int] = {}
    void: dict[str, int] = {}
    for row in rows:
        if row.get("void"):
            void[str(row["day"])] = void.get(str(row["day"]), 0) + 1
            continue
        if row.get("account") is not None:
            continue
        for family in (str(row["group"]), "all"):
            key = (str(row["day"]), str(row["policy"]), str(row["model"]), family)
            if row.get("pyth_active") is False:
                inactive[key] = inactive.get(key, 0) + 1
                continue
            groups.setdefault(key, []).append(row)
    out = []
    for key in sorted(set(groups) | set(inactive)):
        day, policy, model, family = key
        items = groups.get(key, [])
        contracts = sum(float(item["contracts"]) for item in items)
        crossed = sum(float(item["cross_contracts"]) for item in items)
        settle = [float(item["net_settle_usd"]) for item in items]
        m60 = [float(item["net_m60_usd"]) for item in items]
        mean, low, high = _range95(settle)
        mean60, low60, high60 = _range95(m60)
        per_day = FX_PERIODS_PER_DAY if family == FX else None
        out.append({
            "day": day, "policy": policy, "model": model, "family": family, "periods": len(items),
            "inactive_periods": inactive.get(key, 0), "void_periods_day": void.get(day, 0),
            "reward_usd": round(sum(float(item["reward_usd"]) for item in items), 2),
            "contracts": round(contracts, 2), "cross_share": round(crossed / contracts, 4) if contracts else None,
            "fill_m60_usd": round(sum(float(item["fill_m60_usd"]) for item in items), 2),
            "fill_settle_usd": round(sum(float(item["fill_settle_usd"]) for item in items), 2),
            "net_m60_usd": round(sum(m60), 2), "net_settle_usd": round(sum(settle), 2),
            "mean_net_settle_usd": _r(mean), "range95_settle_usd": [_r(low), _r(high)],
            "mean_net_m60_usd": _r(mean60), "range95_m60_usd": [_r(low60), _r(high60)],
            "per_day_settle_usd": _r(None if mean is None or per_day is None else mean * per_day),
            "per_day_range95_usd": [_r(None if low is None or per_day is None else low * per_day),
                                    _r(None if high is None or per_day is None else high * per_day)],
        })
    return out


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def scorecard_text(card: Sequence[Mapping[str, Any]], family: str = FX) -> str:
    """The scorecard in plain words, one line per day, policy and model of one family."""
    lines = [f"Practice LIP desk, pretend money ({family}): net per market-period after fills, 95% range"]
    for row in card:
        if row["family"] != family:
            continue
        low, high = row["range95_settle_usd"]
        span = f"{low:+.2f} to {high:+.2f}" if low is not None and high is not None else "n/a"
        cross = "n/a" if row["cross_share"] is None else f"{100 * row['cross_share']:.0f}%"
        lines.append(f"{row['day']} {row['policy']:<14} {row['model']:<9} periods {row['periods']:>4} "
                     f"reward ${row['reward_usd']:>8.2f} filled {row['contracts']:>8.0f} (crossing {cross}) "
                     f"net@60s ${row['net_m60_usd']:>9.2f} net@settle ${row['net_settle_usd']:>9.2f} "
                     f"per period {span}")
    return "\n".join(lines)


__all__ = ["ACCOUNTS", "FILL_MODELS", "POLICIES", "Account", "AccountPlan", "LipDesk", "Policy", "Sim", "Window",
           "replay", "scorecard", "scorecard_text", "side_eval"]

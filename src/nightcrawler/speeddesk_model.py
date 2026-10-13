"""Pure, practice-only speed desk: market evidence in, simulated receipts out.

There is deliberately no broker, SDK or order client in this module. Pending
orders reserve dollars and exposure. Unknown inputs fail closed; no synthetic
trades, price touches, or a reconstructed opening price can create a fill.
"""

from __future__ import annotations

import itertools
import math
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

Side = Literal["up", "down"]
FeeRounding = Literal["half_even", "kalshi"]
EPSILON = 1e-9
VENUES = ("polymarket_us", "kalshi")
# A lock buy is never placed this close to the close; the live companion's own constant
# (speeddesk_live_model.LOCK_MARGIN_S, kept equal by a test): the market may stop matching.
LOCK_MARGIN_S = 20.0
# Opt-in behaviours for the Kalshi arena's practice residents (nightcrawler.kalshi_arena). At their defaults the desk
# is exactly today's (tests/test_speeddesk_model_genes.py replays a pinned run); config_state leaves them out then.
OPT_IN_FIELDS = ("starter_clip", "starter_delay_s", "starter_stop_s", "rounds", "whole_contracts", "lock_s",
                 "lock_max_price", "stop_s", "stop_pair_cost")


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass(frozen=True)
class Book:
    window: str
    side: Side
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    at: float
    sequence: str
    exchange_at: float | None = None
    source: str = "websocket"
    requested_at: float | None = None


@dataclass(frozen=True)
class Trade:
    window: str
    side: Side
    price: float
    size: float
    at: float
    trade_id: str
    aggressor: Literal["buy", "sell", "unknown"] = "unknown"
    received_at: float | None = None


@dataclass
class Window:
    slug: str
    start: float
    end: float
    start_price: float | None = None
    taker_coefficient: float = 0.0695
    maker_coefficient: float | None = None
    venue_start_price: float | None = None
    tick_size: float = 0.01
    min_trade_qty: float = 0.01
    fee_rounding: FeeRounding = "half_even"
    venue: str = "polymarket_us"


@dataclass(frozen=True)
class SpeedConfig:
    take_edge: float = 0.02
    make_edge: float = 0.03
    clip: float = 25.0
    pair_cap: float = 0.99
    max_imbalance: float = 0.25
    window_usd: float = 20.0
    open_usd: float = 20.0
    day_stop_usd: float = 10.0
    cutoff_s: float = 60.0
    latency_ms: float = 250.0
    stale_s: float = 3.0
    reprice: float = 0.01
    # 3,000 was never reached in quiet hours: Coinbase prints in only about 60-80 % of seconds, so the trailing
    # hour held 2,086-2,979 adjacent one-second returns all evening on 2026-10-12 and the desk never traded.
    # 1,500 returns still pin sigma to about 1.8 % (1 / sqrt(2n)); missing seconds are still never invented.
    sigma_min_samples: int = 1500
    sigma_warmup_s: float = 3600.0
    # The size of a window's first buy (and of each round's); 0 uses clip.
    starter_clip: float = 0.0
    # No starter before the window's start plus this, nor from this long before its close (0: no such wait).
    starter_delay_s: float = 0.0
    starter_stop_s: float = 0.0
    # Rounds: once a window's pair is complete (up = down, nothing pending), the next buy may be a fresh starter.
    rounds: bool = False
    # Whole contracts only, as the live companion sends them.
    whole_contracts: bool = False
    # The live lock: from this long before the close until LOCK_MARGIN_S before it, buy the unpaired side at the ask
    # (immediate-or-cancel, at most lock_max_price, clip contracts at a time); 0: no lock.
    lock_s: float = 0.0
    lock_max_price: float = 0.97
    # A protective stop: from stop_s before the close, complete the pair the same way once completing it would cost
    # at least stop_pair_cost per pair, fees included; 0: off.
    stop_s: float = 0.0
    stop_pair_cost: float = 0.0

    def __post_init__(self) -> None:
        values = asdict(self)
        if any(not math.isfinite(value) or value < 0 for value in values.values()):
            raise ValueError("Speed settings must be finite and nonnegative")
        if not 0 <= self.max_imbalance <= 1 or not 0 < self.pair_cap <= 1:
            raise ValueError("Invalid pair or imbalance limit")
        if not 1 <= self.sigma_min_samples <= 3600:
            raise ValueError("sigma_min_samples must be between 1 and 3600")
        if not 0 < self.lock_max_price <= 0.99 or self.lock_s >= 900 or self.stop_s >= 900:
            raise ValueError("Invalid lock or stop period")
        if self.stop_pair_cost and not 1 < self.stop_pair_cost <= 2:
            raise ValueError("A protective stop's pair cost must be above $1 and at most $2")


def config_state(config: SpeedConfig) -> dict[str, Any]:
    """A saved config without the opt-in fields that hold their defaults, so a release from before them can still
    read the state (the ``speeddesk_live_model.without_default_lock`` precedent); a missing field takes its default."""
    defaults = {item.name: item.default for item in fields(SpeedConfig)}
    return {key: value for key, value in asdict(config).items()
            if not (key in OPT_IN_FIELDS and value == defaults[key])}


def fair_up(spot: float, opening: float, sigma: float, seconds_left: float) -> float | None:
    """Normal-CDF proxy, including a deterministic expiry and zero-vol limit.

    It is not a settlement oracle: the venue's actual outcome books results.
    """
    if (not all(math.isfinite(x) for x in (spot, opening, sigma, seconds_left))
            or spot <= 0 or opening <= 0 or sigma < 0 or seconds_left < 0):
        return None
    if seconds_left == 0:
        return 1.0 if spot >= opening else 0.0
    if sigma == 0:
        return 1.0 if spot > opening else 0.0 if spot < opening else 0.5
    z = (math.log(spot) - math.log(opening)) / (sigma * math.sqrt(seconds_left))
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def fee_per_share(price: float, coefficient: float) -> float:
    if not (math.isfinite(price) and math.isfinite(coefficient)
            and 0 < price < 1 and abs(coefficient) <= 1):
        raise ValueError("Unknown or invalid fee inputs")
    return coefficient * price * (1 - price)


def fill_fee(price: float, size: float, coefficient: float, rounding: FeeRounding = "half_even") -> float:
    """Documented venue rounding; never treat one venue's fee as another's."""
    cost = Decimal(str(size)) * Decimal(str(price))
    value = Decimal(str(coefficient)) * cost * (1 - Decimal(str(price)))
    if rounding == "kalshi":
        if coefficient == 0:
            return 0.0
        # Effective July 7, 2026: position cost plus fee rounds upward to a
        # centicent, $0.0001. It is not the older whole-cent fee schedule.
        return float((cost + value).quantize(Decimal("0.0001"), rounding=ROUND_CEILING) - cost)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def reserved_per_share(price: float, coefficient: float, rounding: FeeRounding = "half_even",
                       min_trade_qty: float = 0.01) -> float:
    raw = max(0.0, fee_per_share(price, coefficient))
    if rounding == "kalshi":
        return price + raw + (0.0001 / min_trade_qty if raw > 0 else 0.0)
    # A rounded positive fee never exceeds twice its unrounded value. Reserve
    # that bound for arbitrary partial fills; never spend an anticipated rebate.
    return price + 2 * raw


class BitcoinTape:
    """One observed close per second; gaps are never invented as zero returns."""

    def __init__(self) -> None:
        self.prices: dict[int, float] = {}
        self.first_prices: dict[int, float] = {}
        self.started_at: float | None = None
        self.last_at: float | None = None
        self.price: float | None = None

    def tick(self, price: float, at: float) -> bool:
        if not math.isfinite(price) or price <= 0 or not math.isfinite(at):
            return False
        if self.last_at is not None and at < self.last_at:
            return False
        if self.started_at is None:
            self.started_at = at
        self.last_at, self.price = at, price
        second = int(at)
        self.prices[second] = price
        self.first_prices.setdefault(second, price)
        self.prices = {stamp: value for stamp, value in self.prices.items() if stamp >= second - 3601}
        self.first_prices = {stamp: value for stamp, value in self.first_prices.items() if stamp >= second - 3601}
        return True

    def opening(self, start: float) -> float | None:
        return self.first_prices.get(int(start))

    def sigma(self, now: float, minimum: int = 1500, warmup_s: float = 3600.0) -> float | None:
        if self.started_at is None or now - self.started_at < warmup_s:
            return None
        last_complete = int(now) - 1
        returns = [math.log(self.prices[second] / self.prices[second - 1])
                   for second in range(last_complete - 3599, last_complete + 1)
                   if second in self.prices and second - 1 in self.prices]
        if len(returns) < minimum:
            return None
        return math.sqrt(sum(value * value for value in returns) / len(returns))


@dataclass
class Holding:
    shares: float = 0.0
    cost: float = 0.0
    fees: float = 0.0

    @property
    def total(self) -> float:
        return self.cost + self.fees


@dataclass
class Inventory:
    up: Holding = field(default_factory=Holding)
    down: Holding = field(default_factory=Holding)

    @property
    def spent(self) -> float:
        return self.up.total + self.down.total


@dataclass
class PracticeOrder:
    order_id: int
    window: str
    side: Side
    kind: Literal["take", "rest"]
    price: float
    size: float
    remaining: float
    placed_at: float
    active_at: float
    fair: float
    coefficient: float
    queue_ahead: float = 0.0
    decision_sequence: str = ""
    fee_rounding: FeeRounding = "half_even"
    min_trade_qty: float = 0.01
    # A lock (or protective stop) completing the window's unpaired contracts; it fills like a take.
    lock: bool = False

    @property
    def counter(self) -> str:
        """The prefix of this order's counters: locks never inflate the takes' fill rates."""
        return "lock" if self.lock else self.kind

    @property
    def reserved(self) -> float:
        return self.remaining * reserved_per_share(self.price, self.coefficient, self.fee_rounding, self.min_trade_qty)


@dataclass(frozen=True)
class Decision:
    event: str
    window: str
    side: str = ""
    price: float = 0.0
    size: float = 0.0
    fair: float | None = None
    edge: float | None = None
    latency_ms: float = 0.0
    bitcoin_price: float | None = None
    bitcoin_staleness_s: float | None = None
    reason: str = ""
    order_id: int = 0
    at: float = 0.0
    fee_usd: float = 0.0
    kind: str = ""


@dataclass(frozen=True)
class Settlement:
    window: str
    at: float
    up_wins: bool
    up_shares: float
    down_shares: float
    cost_usd: float
    fee_usd: float
    payout_usd: float
    locked_usd: float
    direction_usd: float
    pnl_usd: float


def _order_state(order: PracticeOrder) -> dict[str, Any]:
    """A saved order without the lock flag when it is False (readable by the release before locks)."""
    return {key: value for key, value in asdict(order).items() if not (key == "lock" and value is False)}


def utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).date().isoformat()


#: advance() keeps lock orders through these blocks: a lock runs after the cutoff and through the day stop, and
#: needs no Bitcoin price or opening (it uses no fair value).
KEEPS_LOCKS = frozenset({"cutoff", "day_stop", "bitcoin_stale", "opening_price_missing"})


def settlement(window: str, inventory: Inventory, up_wins: bool, now: float) -> Settlement:
    up, down = inventory.up, inventory.down
    pairs = min(up.shares, down.shares)
    up_average = up.total / up.shares if up.shares else 0.0
    down_average = down.total / down.shares if down.shares else 0.0
    locked = pairs * (1 - up_average - down_average)
    payout = up.shares if up_wins else down.shares
    pnl = payout - inventory.spent
    return Settlement(window, now, up_wins, up.shares, down.shares, up.cost + down.cost,
                      up.fees + down.fees, payout, locked, pnl - locked, pnl)


class PracticeDesk:
    """A deterministic paper exchange. All timestamps are UTC epoch seconds.

    The owner approved one starter clip, then balancing buys. The initial
    reservation is unique; while its inventory is over the imbalance cap only
    the lighter side may buy, without assuming another pending order fills.
    """

    def __init__(self, config: SpeedConfig | None = None) -> None:
        self.config = config or SpeedConfig()
        self.tape = BitcoinTape()
        # How old the last spot print may be; None keeps config.stale_s (another coin's desk trades less often).
        self.price_stale_s: float | None = None
        self.windows: dict[str, Window] = {}
        self.inventory: dict[str, Inventory] = {}
        self.books: dict[tuple[str, Side], Book] = {}
        self.orders: dict[int, PracticeOrder] = {}
        self.closed: list[Settlement] = []
        self.days: dict[str, dict[str, float]] = {}
        self.venue_days: dict[str, dict[str, dict[str, float]]] = {venue: {} for venue in VENUES}
        self.venue_incomplete_days: set[str] = set()
        self.venue_filled_orders: set[int] = set()
        self.window_venues: dict[str, str] = {}
        self.traded_days: dict[str, set[str]] = {}
        self.filled_orders: dict[str, set[int]] = {}
        self.next_order_id = 1
        self.seen_trades: set[str] = set()
        self.trade_order: deque[str] = deque()
        self.consumed: dict[tuple[str, Side, float], float] = {}
        self.last_reason: dict[str, str] = {}
        self.bootstrap_order: dict[str, int] = {}
        self.bootstrap_side: dict[str, Side] = {}
        # A starter filter (the Kalshi arena's signal slot): a reason blocks a window's starter, "" allows it; None
        # keeps today's desk. Balancing buys and locks never ask it.
        self.starter_gate: Callable[[Window, float], str] | None = None

    def add_window(self, window: Window) -> None:
        if window.end <= window.start or window.tick_size <= 0 or window.min_trade_qty <= 0:
            raise ValueError("Invalid window")
        existing = self.windows.get(window.slug)
        if window.venue == "kalshi":
            # Kalshi's strike is the previous window's settlement, a 60-second BRTI average before the open. A
            # Coinbase print in the start second missed it by $19.61 on average (up to $100) on 2026-10-12/13,
            # worth about 5 cents of fair value, so only the venue strike opens a Kalshi window, saved or not.
            window.start_price = (existing.start_price if existing and existing.start_price is not None
                                  else window.venue_start_price)
        elif existing and existing.start_price is not None:
            window.start_price = existing.start_price
        if window.start_price is None and window.venue != "kalshi":
            window.start_price = self.tape.opening(window.start)
        self.windows[window.slug] = window
        if window.venue in VENUES:
            self.window_venues.setdefault(window.slug, window.venue)
        self.inventory.setdefault(window.slug, Inventory())

    def tick_btc(self, price: float, at: float) -> None:
        if not self.tape.tick(price, at):
            return
        for window in self.windows.values():
            if window.start_price is None and window.venue != "kalshi" and int(at) == int(window.start):
                window.start_price = price

    def on_book(self, book: Book) -> bool:
        key = (book.window, book.side)
        old = self.books.get(key)
        if old and (book.at < old.at or (book.exchange_at is not None
                                       and old.exchange_at is not None
                                       and book.exchange_at < old.exchange_at)):
            return False
        if any(not math.isfinite(level.price) or not math.isfinite(level.size)
               or not 0 < level.price < 1 or level.size < 0 for level in (*book.bids, *book.asks)):
            return False
        self.books[key] = book
        # An unrelated book update does not replenish a consumed ask. Keep its
        # shadow debit until that price disappears. An increased displayed size
        # adds only the increase; unchanged snapshots never create new depth.
        prices = {level.price for level in book.asks if level.size > 0}
        self.consumed = {item: value for item, value in self.consumed.items()
                         if item[:2] != key or item[2] in prices}
        return True

    def _day(self, now: float) -> dict[str, float]:
        return self.days.setdefault(utc_day(now), {})

    def _venue_day(self, now: float, window: str | None) -> dict[str, float] | None:
        venue = self.window_venues.get(window or "")
        if venue not in VENUES:
            # Never assign unidentified activity to whichever venue is visible.
            self.venue_incomplete_days.add(utc_day(now))
            return None
        return self.venue_days[venue].setdefault(utc_day(now), {})

    def _count_venue(self, now: float, name: str, value: float, window: str | None) -> None:
        day = self._venue_day(now, window)
        if day is not None:
            day[name] = day.get(name, 0.0) + value

    def _count(self, now: float, name: str, value: float = 1.0, *, window: str | None = None,
               track_venue: bool = True) -> None:
        day = self._day(now)
        day[name] = day.get(name, 0.0) + value
        if track_venue:
            self._count_venue(now, name, value, window)

    def _event(self, event: str, now: float, window: str, *, order: PracticeOrder | None = None,
               reason: str = "", size: float | None = None, fee: float = 0.0) -> Decision:
        stale = None if self.tape.last_at is None else max(0.0, now - self.tape.last_at)
        if order is None:
            return Decision(event, window, bitcoin_price=self.tape.price, bitcoin_staleness_s=stale,
                            reason=reason, at=now)
        return Decision(event, window, order.side, order.price, order.remaining if size is None else size,
                        order.fair, order.fair - order.price - fee_per_share(order.price, order.coefficient),
                        max(0.0, now - order.placed_at) * 1000, self.tape.price, stale,
                        reason, order.order_id, now, fee, order.kind)

    def blocked(self, window: Window, now: float) -> str:
        if any(item.window == window.slug for item in self.closed):
            return "settled"
        if now < window.start:
            return "not_started"
        if now >= window.end - self.config.cutoff_s:
            return "cutoff"
        if self._day(now).get("pnl_usd", 0.0) <= -self.config.day_stop_usd:
            return "day_stop"
        price_stale_s = self.config.stale_s if self.price_stale_s is None else self.price_stale_s
        if self.tape.last_at is None or not 0 <= now - self.tape.last_at <= price_stale_s:
            return "bitcoin_stale"
        if window.start_price is None:
            return "opening_price_missing"
        return self._book_reason(window, now)

    def _book_reason(self, window: Window, now: float) -> str:
        """Both books fresh: all a lock needs (it uses no fair value)."""
        for side in ("up", "down"):
            book = self.books.get((window.slug, side))
            if book is None or not 0 <= now - book.at <= self.config.stale_s:
                return "book_stale"
            if (book.source == "rest" and book.requested_at is not None
                    and not 0 <= book.at - book.requested_at <= self.config.stale_s):
                return "book_stale"
            if (book.source != "rest" and book.exchange_at is not None
                    and not 0 <= now - book.exchange_at <= self.config.stale_s):
                return "book_stale"
        return ""

    def _starter(self, window: str) -> bool:
        """The next buy opens the window, or (with rounds) a fresh round after a complete pair with nothing pending."""
        inventory = self.inventory[window]
        if inventory.up.shares + inventory.down.shares <= EPSILON:
            return True
        return (self.config.rounds and abs(inventory.up.shares - inventory.down.shares) <= EPSILON
                and not any(order.window == window for order in self.orders.values()))

    def _starter_hold(self, window: Window, now: float) -> str:
        """Why a starter waits (its timing or the starter filter); "" lets it go."""
        if self.config.starter_delay_s and now < window.start + self.config.starter_delay_s:
            return "starter_wait"
        if self.config.starter_stop_s and now >= window.end - self.config.starter_stop_s:
            return "starter_late"
        return self.starter_gate(window, now) if self.starter_gate is not None else ""

    def _risk_reason(self, window: str, side: Side, price: float, size: float,
                     coefficient: float) -> str:
        inventory = self.inventory[window]
        if size <= EPSILON:
            return "zero_size"
        spec = self.windows[window]
        cost = size * reserved_per_share(price, coefficient, spec.fee_rounding, spec.min_trade_qty)
        pending = [order for order in self.orders.values() if order.window == window]
        if inventory.spent + sum(order.reserved for order in pending) + cost > self.config.window_usd + EPSILON:
            return "window_budget"
        closed = {item.window for item in self.closed}
        open_cost = sum(value.spent for key, value in self.inventory.items() if key not in closed)
        if open_cost + sum(order.reserved for order in self.orders.values()) + cost > self.config.open_usd + EPSILON:
            return "open_budget"
        initial_total = inventory.up.shares + inventory.down.shares
        initial_difference = inventory.up.shares - inventory.down.shares
        starter_pending = self.bootstrap_order.get(window) in self.orders
        bootstrap = (abs(initial_difference) > self.config.max_imbalance * initial_total + EPSILON
                     or starter_pending)
        # A round's starter is a window's first buy again: the imbalance check does not refuse it.
        round_start = initial_total > EPSILON and self.config.rounds and self._starter(window)
        if initial_total <= EPSILON or round_start:
            if pending:
                return "starter_pending"
            if size > (self.config.starter_clip or self.config.clip) + EPSILON:
                return "starter_clip"
            bootstrap = bootstrap or round_start
        elif bootstrap:
            light: Side = "down" if initial_difference > 0 else "up"
            if abs(initial_difference) <= EPSILON or side != light:
                return "balancing_only"
            other_light = sum(order.remaining for order in pending if order.side == light)
            if size + other_light > abs(initial_difference) + EPSILON:
                return "balancing_size"
        # Each pending leg can fill independently. Test the extreme outcomes,
        # never offset one unfilled reservation with another unfilled leg.
        for flags in itertools.product((False, True), repeat=len(pending)):
            shares = {"up": inventory.up.shares, "down": inventory.down.shares}
            paid = {"up": inventory.up.total, "down": inventory.down.total}
            for include, order in zip(flags, pending, strict=True):
                if include:
                    shares[order.side] += order.remaining
                    paid[order.side] += order.reserved
            shares[side] += size
            paid[side] += cost
            total = shares["up"] + shares["down"]
            if (initial_total > EPSILON and not bootstrap
                    and abs(shares["up"] - shares["down"]) > self.config.max_imbalance * total + EPSILON):
                return "imbalance"
            if min(shares.values()) > EPSILON:
                pair_cost = paid["up"] / shares["up"] + paid["down"] / shares["down"]
                if pair_cost > self.config.pair_cap + EPSILON:
                    return "pair_cap"
        return ""

    def can_buy(self, window: str, side: Side, price: float, size: float,
                coefficient: float) -> str:
        """Empty reason means allowed, including outstanding order reservations."""
        return self._risk_reason(window, side, price, size, coefficient)

    def cancel(self, now: float, window: str | None = None, reason: str = "cancelled", *,
               keep_locks: bool = False) -> list[Decision]:
        events = []
        for order_id, order in list(self.orders.items()):
            if (window is None or window == order.window) and not (keep_locks and order.lock):
                events.append(self._event("speeddesk_cancel", now, order.window, order=order, reason=reason))
                del self.orders[order_id]
                self._count(now, f"{order.counter}_cancelled", window=order.window)
        return events

    def place(self, window: str, side: Side, kind: Literal["take", "rest"], price: float,
              size: float, fair: float, now: float) -> Decision:
        spec = self.windows[window]
        reason = self.blocked(spec, now)
        coefficient = spec.taker_coefficient if kind == "take" else spec.maker_coefficient
        if coefficient is None:
            reason = reason or "maker_fee_unknown"
        if any(order.window == window and order.side == side for order in self.orders.values()):
            reason = reason or "order_pending"
        if not reason and coefficient is not None:
            try:
                reason = self._risk_reason(window, side, price, size, coefficient)
            except ValueError:
                reason = "fee_unknown"
        book = self.books.get((window, side))
        if not reason and kind == "take":
            best = min((level.price for level in book.asks), default=1.0) if book else 1.0
            shown = sum(level.size for level in book.asks if abs(level.price - price) < EPSILON) if book else 0.0
            used = self.consumed.get((window, side, price), 0.0) if book else 0.0
            if abs(best - price) > EPSILON or size > shown - used + EPSILON:
                reason = "ask_depth"
        if not reason and kind == "rest" and book and any(level.price <= price + EPSILON for level in book.asks):
            reason = "maker_would_cross"
        if reason or coefficient is None or book is None:
            self.last_reason[window] = reason
            return self._event("speeddesk_skip", now, window, reason=reason)
        queue = sum(level.size for level in book.bids if abs(level.price - price) < EPSILON) if kind == "rest" else 0.0
        order = PracticeOrder(self.next_order_id, window, side, kind, price, size, size, now,
                              now + self.config.latency_ms / 1000, fair, coefficient, queue, book.sequence,
                              spec.fee_rounding, spec.min_trade_qty)
        starter = self._starter(window)
        self.next_order_id += 1
        self.orders[order.order_id] = order
        if starter:
            self.bootstrap_order[window] = order.order_id
            self.bootstrap_side[window] = side
        self._count(now, f"{kind}_orders", window=window)
        self._count(now, f"{kind}_requested_shares", size, window=window)
        self.last_reason[window] = ""
        return self._event(f"speeddesk_{kind}", now, window, order=order)

    def _fill(self, order: PracticeOrder, size: float, now: float) -> Decision:
        holding = getattr(self.inventory[order.window], order.side)
        fee = fill_fee(order.price, size, order.coefficient, order.fee_rounding)
        holding.shares += size
        holding.cost += size * order.price
        holding.fees += fee
        order.remaining -= size
        traded = self.traded_days.setdefault(utc_day(now), set())
        if order.window not in traded:
            traded.add(order.window)
            self._count(now, "windows_traded", window=order.window)
        filled = self.filled_orders.setdefault(utc_day(now), set())
        if order.order_id not in filled:
            filled.add(order.order_id)
            self._count(now, f"{order.counter}_filled_orders", track_venue=False)
        # Per-venue rates are placement-day cohorts, so a later partial fill
        # cannot become a second successful order or a >100% midnight rate.
        if order.order_id not in self.venue_filled_orders:
            self.venue_filled_orders.add(order.order_id)
            self._count_venue(order.placed_at, f"{order.counter}_filled_orders", 1.0, order.window)
        self._count(now, "fills", window=order.window)
        self._count(now, f"{order.counter}_filled_shares", size, window=order.window)
        self._count(now, "latency_ms_total", max(0.0, now - order.placed_at) * 1000, window=order.window)
        self._count(now, "fees_usd", fee, window=order.window)
        if order.remaining <= EPSILON:
            self.orders.pop(order.order_id, None)
        return self._event("speeddesk_fill", now, order.window, order=order, size=size, fee=fee)

    def advance(self, now: float) -> list[Decision]:
        """Resolve against the first genuine book recheck after minimum latency.

        REST may take longer than 250 ms; the receipt records that actual delay.
        Waiting is bounded and cannot continue past a failed first recheck.
        """
        events = []
        closed = {item.window for item in self.closed}
        for window in self.windows.values():
            if window.slug in closed:
                continue
            reason = self.blocked(window, now)
            if reason:
                self.last_reason[window.slug] = reason
                # A lock completes pairs after the cutoff and through the day stop, as live; no lock exists unless
                # SpeedConfig.lock_s or stop_s is set.
                events.extend(self.cancel(now, window.slug, reason, keep_locks=reason in KEEPS_LOCKS))
        for order in list(self.orders.values()):
            if order.kind != "take" or now + EPSILON < order.active_at:
                continue
            if order.lock and (order.window, order.side) not in self.books:
                del self.orders[order.order_id]
                self._count(now, "lock_completed", window=order.window)
                events.append(self._event("speeddesk_cancel", now, order.window, order=order, reason="book_missing"))
                continue
            book = self.books[(order.window, order.side)]
            if now > order.active_at + self.config.stale_s + EPSILON:
                del self.orders[order.order_id]
                self._count(now, f"{order.counter}_completed", window=order.window)
                events.append(self._event("speeddesk_cancel", now, order.window, order=order,
                                          reason="latency_recheck_missing"))
                continue
            shown = sum(level.size for level in book.asks if abs(level.price - order.price) < EPSILON)
            if shown <= EPSILON:
                # Evidence that the decision's ask vanished is sufficient to
                # reject it, even before a qualifying post-delay confirmation.
                # Never hold that decision open for the old price to return.
                del self.orders[order.order_id]
                self._count(now, f"{order.counter}_completed", window=order.window)
                events.append(self._event("speeddesk_cancel", now, order.window, order=order,
                                          reason="ask_moved"))
                continue
            # A REST request made before the delay cannot prove the ask was
            # still present after it; neither can a delayed old WS message.
            proof_at = book.at
            if book.source == "rest" and book.requested_at is not None:
                proof_at = book.requested_at
            elif book.source != "rest" and book.exchange_at is not None:
                proof_at = book.exchange_at
            if proof_at + EPSILON < order.active_at:
                continue
            key = (order.window, order.side, order.price)
            available = max(0.0, shown - self.consumed.get(key, 0.0))
            size = min(order.remaining, available)
            if size > EPSILON:
                self.consumed[key] = self.consumed.get(key, 0.0) + size
                events.append(self._fill(order, size, now))
            # IOC residual is never converted into a later resting order.
            if order.order_id in self.orders:
                del self.orders[order.order_id]
            self._count(now, f"{order.counter}_completed", window=order.window)
            if size <= EPSILON:
                events.append(self._event("speeddesk_cancel", now, order.window, order=order, reason="ask_moved"))
        return events

    def on_trade(self, trade: Trade, now: float | None = None) -> list[Decision]:
        now = trade.received_at if now is None else now
        now = trade.at if now is None else now
        events = self.advance(now)
        identity = f"{trade.window}:{trade.side}:{trade.trade_id}"
        if (not trade.trade_id or identity in self.seen_trades or trade.aggressor != "sell"
                or trade.size <= 0 or not math.isfinite(trade.size) or not 0 < trade.price < 1
                or trade.at > now + EPSILON or now - trade.at > self.config.stale_s):
            return events
        self.seen_trades.add(identity)
        self.trade_order.append(identity)
        while len(self.trade_order) > 10000:
            self.seen_trades.discard(self.trade_order.popleft())
        available = trade.size
        for order in sorted(self.orders.values(), key=lambda item: (-item.price, item.order_id)):
            if (order.window != trade.window or order.side != trade.side or order.kind != "rest"
                    or trade.at <= order.active_at or trade.price > order.price + EPSILON):
                continue
            queued = min(order.queue_ahead, available)
            order.queue_ahead -= queued
            available -= queued
            size = min(order.remaining, available)
            if size > EPSILON:
                events.append(self._fill(order, size, now))
                available -= size
            if available <= EPSILON:
                break
        return events

    def evaluate(self, now: float, *, makers_enabled: bool = True,
                 maker_windows: set[str] | None = None) -> list[Decision]:
        events = self.advance(now)
        if self.config.lock_s > 0 or self.config.stop_s > 0:
            events.extend(self._lock_step(now))
        sigma = self.tape.sigma(now, self.config.sigma_min_samples, self.config.sigma_warmup_s)
        closed = {item.window for item in self.closed}
        for window in self.windows.values():
            if window.slug in closed:
                continue
            reason = self.blocked(window, now)
            if reason or sigma is None:
                self.last_reason[window.slug] = reason or "volatility_warming"
                continue
            assert self.tape.price is not None and window.start_price is not None
            up = fair_up(self.tape.price, window.start_price, sigma, window.end - now)
            if up is None:
                continue
            candidates: list[tuple[Side, float, float]] = []
            for side in ("up", "down"):
                fair = up if side == "up" else 1 - up
                ask = min(self.books[(window.slug, side)].asks, key=lambda level: level.price, default=None)
                edge = fair - ask.price - fee_per_share(ask.price, window.taker_coefficient) if ask else -math.inf
                candidates.append((side, fair, edge))
            # Do not let a first Up maker reservation hide a better Down take.
            for side, fair, _edge in sorted(candidates, key=lambda candidate: -candidate[2]):
                enabled = makers_enabled and (maker_windows is None or window.slug in maker_windows)
                events.extend(self._evaluate_side(window, side, fair, now, enabled))
        return events

    def _evaluate_side(self, window: Window, side: Side, fair: float, now: float,
                       makers_enabled: bool = True) -> list[Decision]:
        book = self.books[(window.slug, side)]
        events = []
        ask = min(book.asks, key=lambda level: level.price, default=None)
        take = bool(ask and ask.price <= fair - self.config.take_edge
                    - fee_per_share(ask.price, window.taker_coefficient))
        for order in list(self.orders.values()):
            if order.window == window.slug and order.side == side:
                if order.kind == "take":
                    return []
                if not take and makers_enabled and abs(fair - order.fair) <= self.config.reprice + EPSILON:
                    return []
                del self.orders[order.order_id]
                self._count(now, "rest_cancelled", window=window.slug)
                reason = "take_available" if take else "reprice" if makers_enabled else "trade_stream_missing"
                events.append(self._event("speeddesk_cancel", now, window.slug, order=order, reason=reason))
        kind: Literal["take", "rest"] = "rest"
        starter = self._starter(window.slug)
        clip = (self.config.starter_clip or self.config.clip) if starter else self.config.clip
        if ask and take:
            price = ask.price
            used = self.consumed.get((window.slug, side, ask.price), 0.0)
            size = min(clip, max(0.0, ask.size - used))
            kind = "take"
        else:
            price = math.floor((fair - self.config.make_edge + EPSILON) / window.tick_size) * window.tick_size
            size = clip
        if kind == "rest" and not makers_enabled:
            self.last_reason[window.slug] = "trade_stream_missing"
            return events
        hold = self._starter_hold(window, now) if starter else ""
        if hold:
            self.last_reason[window.slug] = hold
            return events
        if not 0 < price < 1:
            return events
        # Valid inventory and each pending-order extreme already satisfy the
        # constraints. Along one new buy, allowed quantities form [0, maximum].
        # Search venue-sized increments so thin fractional depth is not ignored.
        coefficient = window.taker_coefficient if kind == "take" else window.maker_coefficient
        if coefficient is None:
            self.last_reason[window.slug] = "maker_fee_unknown"
            return events
        step = 1.0 if self.config.whole_contracts else window.min_trade_qty
        units = max(0, math.floor((size + EPSILON) / step))
        low, high = 0, units
        while low < high:
            middle = (low + high + 1) // 2
            if self._risk_reason(window.slug, side, price, middle * step, coefficient):
                high = middle - 1
            else:
                low = middle
        size = low * step
        if size <= EPSILON:
            self.last_reason[window.slug] = self._risk_reason(window.slug, side, price,
                                                               step, coefficient) or "ask_depth"
            return events
        events.append(self.place(window.slug, side, kind, price, size, fair, now))
        return events

    def _lock_step(self, now: float) -> list[Decision]:
        """Complete a half-filled pair at the ask, the live companion's lock (``speeddesk_live._lock``), and the
        protective stop that does the same earlier once completing would cost at least ``stop_pair_cost``.

        It needs both books fresh, no take or lock pending in the window and at least one whole unpaired contract;
        the budgets, pair cap, edge, cutoff and day stop do not apply, because completing a pair can only lower the
        window's possible loss. A resting bid in the window is cancelled first (new buys stop when the pair is
        completed). The order fills like a take (the first book after the latency, top level only,
        immediate-or-cancel)."""
        events = []
        closed = {item.window for item in self.closed}
        for window in self.windows.values():
            if window.slug in closed or not window.start <= now < window.end - LOCK_MARGIN_S:
                continue
            lock = self.config.lock_s > 0 and now >= window.end - self.config.lock_s
            stop = self.config.stop_pair_cost > 0 and self.config.stop_s > 0 and now >= window.end - self.config.stop_s
            inventory = self.inventory[window.slug]
            difference = inventory.up.shares - inventory.down.shares
            unpaired = math.floor(abs(difference) + EPSILON)
            if (not (lock or stop) or unpaired < 1 or self._book_reason(window, now)
                    or any(order.window == window.slug and order.kind == "take" for order in self.orders.values())):
                continue
            side: Side = "down" if difference > 0 else "up"
            book = self.books[(window.slug, side)]
            ask = min(book.asks, key=lambda level: level.price, default=None)
            # Orders are whole cents: an immediate-or-cancel limit one tick above a sub-penny ask still fills there.
            if ask is None or math.ceil(round(ask.price * 100, 6)) / 100 > self.config.lock_max_price + EPSILON:
                continue
            if not lock:
                heavy = inventory.up if difference > 0 else inventory.down
                cost = heavy.total / heavy.shares + ask.price + fee_per_share(ask.price, window.taker_coefficient)
                if cost < self.config.stop_pair_cost - EPSILON:
                    continue
            used = self.consumed.get((window.slug, side, ask.price), 0.0)
            size = min(unpaired, math.floor(self.config.clip + EPSILON), math.floor(ask.size - used + EPSILON))
            if size < 1:
                continue
            events.extend(self.cancel(now, window.slug, "lock" if lock else "stop"))
            order = PracticeOrder(self.next_order_id, window.slug, side, "take", ask.price, float(size), float(size),
                                  now, now + self.config.latency_ms / 1000, ask.price, window.taker_coefficient,
                                  0.0, book.sequence, window.fee_rounding, window.min_trade_qty, lock=True)
            self.next_order_id += 1
            self.orders[order.order_id] = order
            self._count(now, "lock_orders", window=window.slug)
            self._count(now, "lock_requested_shares", float(size), window=window.slug)
            events.append(self._event("speeddesk_lock", now, window.slug, order=order,
                                      reason="lock" if lock else "stop"))
        return events

    def forget(self, window: str, *, void: bool = False) -> None:
        """Drop a settled window's per-window entries; the Kalshi arena keeps its own record of each window and
        never adds a settled one again. ``void`` drops a window that never settled (no P&L at all). A window
        with orders is never dropped: cancel them first."""
        settled = any(item.window == window for item in self.closed)
        if (not settled and not void) or any(order.window == window for order in self.orders.values()):
            raise ValueError("Only a settled (or void) window without orders can be forgotten")
        self.windows.pop(window, None)
        self.inventory.pop(window, None)
        self.closed = [item for item in self.closed if item.window != window]
        self.books = {key: book for key, book in self.books.items() if key[0] != window}
        self.consumed = {key: size for key, size in self.consumed.items() if key[0] != window}
        for mapping in (self.last_reason, self.bootstrap_order, self.bootstrap_side, self.window_venues):
            mapping.pop(window, None)

    def settle(self, window: str, up_wins: bool, now: float) -> Settlement | None:
        if any(item.window == window for item in self.closed):
            return None
        spec = self.windows[window]
        if now < spec.end:
            raise ValueError("Cannot settle an unfinished window")
        self.cancel(now, window, "settled")
        result = settlement(window, self.inventory[window], up_wins, now)
        self.closed.append(result)
        if result.up_shares + result.down_shares > 0:
            self._count(now, "windows", window=window)
            self._count(now, "won" if result.pnl_usd > 0 else "lost" if result.pnl_usd < 0 else "flat", window=window)
            for key in ("pnl_usd", "locked_usd", "direction_usd"):
                self._count(now, key, getattr(result, key), window=window)
            day = self._day(now)
            day["worst_window_usd"] = min(day.get("worst_window_usd", result.pnl_usd), result.pnl_usd)
            venue_day = self._venue_day(now, window)
            if venue_day is not None:
                venue_day["worst_window_usd"] = min(venue_day.get("worst_window_usd", result.pnl_usd), result.pnl_usd)
        return result

    def daily_summary(self, now: float | str, venue: str | None = None) -> dict[str, Any]:
        day = now if isinstance(now, str) else utc_day(now)
        if venue is not None and venue not in VENUES:
            raise ValueError("Unknown speed desk venue")
        data = self.days.get(day, {}) if venue is None else self.venue_days[venue].get(day, {})
        fills = data.get("fills", 0)
        take_orders = data.get("take_orders", 0)
        maker_orders = data.get("rest_orders", 0)
        take_fills = data.get("take_filled_orders", 0)
        maker_fills = data.get("rest_filled_orders", 0)
        report = {"day": day, "windows": data.get("windows_traded", 0),
                "settled_windows": data.get("windows", 0), "fills": fills,
                "locked_usd": data.get("locked_usd", 0),
                "directional_usd": data.get("direction_usd", 0), "pnl_usd": data.get("pnl_usd", 0),
                "won": data.get("won", 0), "lost": data.get("lost", 0),
                "worst_usd": data.get("worst_window_usd"),
                "take_attempts": take_orders, "take_fills": take_fills,
                "maker_orders": maker_orders, "maker_fills": maker_fills,
                "take_fill_rate": take_fills / take_orders if take_orders else None,
                "maker_fill_rate": maker_fills / maker_orders if maker_orders else None,
                "avg_latency_ms": data.get("latency_ms_total", 0) / fills if fills else None}
        if venue is not None:
            complete = day not in self.venue_incomplete_days
            if not complete:
                # Old aggregate receipts cannot identify past venue attempts,
                # partial executions or latency. No guessed split or false zero.
                report = {key: value if key == "day" else None for key, value in report.items()}
            report.update({"venue": venue, "reporting_complete": complete,
                           "fill_rate_basis": "orders_placed_on_day"})
        return report

    def to_state(self) -> dict[str, Any]:
        return {"version": 1, "mode": "practice", "config": config_state(self.config),
                "windows": {slug: asdict(window) for slug, window in self.windows.items()},
                "inventory": {slug: asdict(value) for slug, value in self.inventory.items()},
                "orders": [_order_state(order) for order in self.orders.values()],
                "closed": [asdict(item) for item in self.closed], "days": self.days,
                "venue_reporting_version": 1, "venue_days": self.venue_days,
                "venue_incomplete_days": sorted(self.venue_incomplete_days),
                "venue_filled_orders": sorted(self.venue_filled_orders),
                "window_venues": self.window_venues,
                "traded_days": {day: sorted(windows) for day, windows in self.traded_days.items()},
                "filled_orders": {day: sorted(orders) for day, orders in self.filled_orders.items()},
                "next_order_id": self.next_order_id, "last_reason": self.last_reason,
                "bootstrap_order": self.bootstrap_order, "bootstrap_side": self.bootstrap_side,
                "seen_trades": list(self.trade_order),
                "consumed": [[window, side, price, size] for (window, side, price), size in self.consumed.items()],
                "bitcoin": {"started_at": self.tape.started_at, "last_at": self.tape.last_at, "price": self.tape.price,
                            "prices": {str(key): value for key, value in self.tape.prices.items()},
                            "first_prices": {str(key): value for key, value in self.tape.first_prices.items()}}}

    def _migrate_venue_reporting(self, state: dict[str, Any]) -> None:
        """An all-zero warm-up can split exactly; historical activity cannot."""
        self.venue_incomplete_days.update(day for day, counters in self.days.items()
                                          if any(value != 0 for value in counters.values()))
        self.venue_incomplete_days.update(day for day, windows in self.traded_days.items() if windows)
        self.venue_incomplete_days.update(day for day, orders in self.filled_orders.items() if orders)
        for result in self.closed:
            if result.up_shares + result.down_shares > 0:
                self.venue_incomplete_days.add(utc_day(result.at))
        for order in state.get("orders", []):
            self.venue_incomplete_days.add(utc_day(float(order["placed_at"])))
        for window, inventory in self.inventory.items():
            if inventory.up.shares + inventory.down.shares > 0 and window in self.windows:
                self.venue_incomplete_days.add(utc_day(self.windows[window].start))
        self.venue_filled_orders = set().union(*self.filled_orders.values())

    @classmethod
    def from_state(cls, state: dict[str, Any], config: SpeedConfig | None = None) -> PracticeDesk:
        """Restore receipts, never resurrect orders/queue positions after a gap."""
        if state.get("version") != 1 or state.get("mode") != "practice":
            raise ValueError("Unsupported speed desk state")
        desk = cls(config or SpeedConfig(**state["config"]))
        for raw in state["windows"].values():
            desk.add_window(Window(**raw))
        for slug, raw in state["inventory"].items():
            desk.inventory[slug] = Inventory(Holding(**raw["up"]), Holding(**raw["down"]))
        desk.closed = [Settlement(**raw) for raw in state["closed"]]
        desk.days = state["days"]
        desk.traded_days = {day: set(windows) for day, windows in state.get("traded_days", {}).items()}
        desk.filled_orders = {day: set(orders) for day, orders in state.get("filled_orders", {}).items()}
        if "venue_reporting_version" in state:
            if state["venue_reporting_version"] != 1:
                raise ValueError("Unsupported venue reporting state")
            desk.venue_days = {venue: state["venue_days"][venue] for venue in VENUES}
            desk.venue_incomplete_days = set(state["venue_incomplete_days"])
            desk.venue_filled_orders = set(state["venue_filled_orders"])
            desk.window_venues = {window: venue for window, venue in state["window_venues"].items() if venue in VENUES}
        else:
            desk._migrate_venue_reporting(state)
        desk.next_order_id = int(state["next_order_id"])
        desk.last_reason = state.get("last_reason", {})
        desk.bootstrap_order = state.get("bootstrap_order", {})
        desk.bootstrap_side = state.get("bootstrap_side", {})
        desk.trade_order = deque(state.get("seen_trades", [])[-10000:])
        desk.seen_trades = set(desk.trade_order)
        desk.consumed = {(window, side, price): size for window, side, price, size in state.get("consumed", [])}
        tape = state.get("bitcoin", {})
        desk.tape.started_at = tape.get("started_at")
        desk.tape.last_at, desk.tape.price = tape.get("last_at"), tape.get("price")
        desk.tape.prices = {int(key): float(value) for key, value in tape.get("prices", {}).items()}
        desk.tape.first_prices = {int(key): float(value) for key, value in tape.get("first_prices", {}).items()}
        # Validate saved accounting before accepting it as a budget source.
        for inventory in desk.inventory.values():
            if any(not all(math.isfinite(value) for value in (holding.shares, holding.cost, holding.fees))
                   or holding.shares < 0 or holding.cost < 0 or holding.total < 0
                   for holding in (inventory.up, inventory.down)):
                raise ValueError("Invalid persisted practice inventory")
        return desk

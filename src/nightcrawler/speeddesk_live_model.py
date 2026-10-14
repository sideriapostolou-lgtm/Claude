"""Durable Kalshi-only execution accounting, with no network or credentials.

Reservations precede network requests and survive uncertainty. Only owned,
identified venue fills change holdings. A requested cancellation is not proof
that the remaining exposure disappeared. The practice ledger is never read.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Any, Literal

from .speeddesk_model import (
    EPSILON,
    Holding,
    Inventory,
    Side,
    Window,
    settlement,
    utc_day,
)

CLIENT_PREFIX = "nc-speed-"
Kind = Literal["take", "rest"]


class LiveRejected(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# A lock buy is never sent this close to the close: the market may stop matching.
LOCK_MARGIN_S = 20.0
# The risk book's own ceilings (LiveLimits clamps every limit to them, the ladder's rungs included).
HARD_WINDOW_USD, HARD_OPEN_USD, HARD_DAY_LOSS_USD, HARD_TOTAL_LOSS_USD = 20.0, 40.0, 12.0, 10.0
# The contract cap's own ceiling (config.py SPEEDDESK_KALSHI_CLIP has the first, hi=25).
HARD_CLIP = 25.0
# Refusals that mean a loss stop binds: one on a one-contract order latches the stop (the day stop for the rest of
# the UTC day, the total stop until a new resume token), and the earned-growth ladder counts it as a stop.
STOP_REFUSALS = frozenset({"day_stop", "total_budget"})
# What a resume value did when the companion saw it (speeddesk_live records one receipt per start).
ResumeOutcome = Literal["applied", "used", "not_halted", "integrity", ""]
# Integrity reset fingerprints live beside the resume ones; the prefix keeps the two kinds from matching.
RESET_DOMAIN = b"kalshi-integrity-reset\x00"
DAY_RESET_DOMAIN = b"kalshi-day-reset\x00"
DAY_KEY = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class LiveLimits:
    # The owner's 2026-10-13 choice: $5 per window, $10 open, -$6 day stop, -$10 total stop.
    window_usd: float = 5.0
    open_usd: float = 10.0
    day_loss_usd: float = 6.0
    total_loss_usd: float = 10.0
    pair_cap: float = 0.99
    max_imbalance: float = 0.25
    clip: float = 25.0
    cutoff_s: float = 180.0
    # From this long before the close, new buys stop and a half-filled pair is completed
    # ("locked") at up to lock_max_price per contract instead of riding to settlement.
    lock_s: float = 240.0
    lock_max_price: float = 0.97
    cash_max_age_s: float = 5.0
    fee_precision: float = 0.01
    min_fill_qty: float = 0.01

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value < 0 for value in asdict(self).values()):
            raise ValueError("Invalid live limits")
        # Second, independent guard on the owner's ceilings (config.py has the first): $10 per window and $20 open since
        # 2026-10-13 15:15 UTC ("ten now double tmr if it works"), and from 16:00 UTC up to $20, $40 and a $12 day stop
        # "when it's winning"; the total stop is unchanged. The earned-growth ladder never goes above these.
        for name, hard in (("window_usd", HARD_WINDOW_USD), ("open_usd", HARD_OPEN_USD),
                           ("day_loss_usd", HARD_DAY_LOSS_USD), ("total_loss_usd", HARD_TOTAL_LOSS_USD),
                           ("clip", HARD_CLIP)):
            object.__setattr__(self, name, min(getattr(self, name), hard))
        object.__setattr__(self, "pair_cap", min(self.pair_cap, 0.99))
        object.__setattr__(self, "max_imbalance", min(self.max_imbalance, 0.25))
        object.__setattr__(self, "cutoff_s", max(60.0, self.cutoff_s))
        object.__setattr__(self, "lock_s", min(899.0, max(self.lock_s, self.cutoff_s, LOCK_MARGIN_S + 30)))
        object.__setattr__(self, "lock_max_price", min(self.lock_max_price, 0.99))
        if self.fee_precision not in (0.0001, 0.01) or self.min_fill_qty != 0.01:
            raise ValueError("Unsupported live fee precision or execution increment")


# The parts of the book's saved state that belong to one window; a finished window's parts can be archived.
WINDOW_PARTS = ("windows", "intents", "inventory", "fills", "settled")


def without_default_lock(row: dict[str, Any]) -> dict[str, Any]:
    """Saved intent without the lock flag when it is False (readable by the release before locks)."""
    return {key: value for key, value in row.items() if not (key == "lock" and value is False)}


def reserve_unit_cost(price: float, coefficient: float, precision: float = 0.01) -> float:
    """Upper cost bound for every partition into actual .01-contract fills.

    The default covers unknown/non-direct account precision. The $.0001
    direct-member precision must be established before selecting that bound.
    No future fee-accumulator rebate is spent in advance.
    """
    if not (math.isfinite(price) and 0 < price < 1 and math.isfinite(coefficient)
            and 0 <= coefficient <= 1 and precision in (0.0001, 0.01)):
        raise LiveRejected("fee_unknown")
    p, k, increment, grid = Decimal(str(price)), Decimal(str(coefficient)), Decimal(".01"), Decimal(str(precision))
    cost = increment * (p + k * p * (1 - p))
    return float((cost / grid).to_integral_value(rounding=ROUND_CEILING) * grid / increment)


@dataclass
class LiveIntent:
    client_order_id: str
    window: str
    side: Side
    kind: Kind
    price: float
    size: float
    created_at: float
    unit_reserve: float
    fair: float | None = None
    order_id: str | None = None
    status: str = "intent"
    filled_size: float = 0.0
    reported_filled_size: float = 0.0
    venue_remaining_size: float | None = None
    reservation_active: bool = True
    cancel_requested: bool = False
    last_snapshot_at: float | None = None
    uncertainty: str | None = None
    # Completes already-bought contracts into $1 pairs: it can only lower the possible loss.
    lock: bool = False

    @property
    def remaining(self) -> float:
        return max(0.0, self.size - self.filled_size)

    @property
    def reserved(self) -> float:
        return self.remaining * self.unit_reserve if self.reservation_active else 0.0


@dataclass(frozen=True)
class ActualFill:
    fill_id: str
    order_id: str
    client_order_id: str
    window: str
    side: Side
    price: float
    size: float
    fee_usd: float
    at: float
    # Optional venue evidence; legacy unknown is not a financial fill change.
    is_taker: bool | None = field(default=None, compare=False)


@dataclass(frozen=True)
class OrderSnapshot:
    client_order_id: str
    order_id: str
    status: str
    filled_size: float
    remaining_size: float
    at: float


@dataclass(frozen=True)
class LiveSettlement:
    window: str
    settlement_id: str
    at: float
    up_wins: bool
    up_shares: float
    down_shares: float
    cost_usd: float
    fee_usd: float
    paired_credit_usd: float
    net_payout_usd: float
    payout_usd: float
    locked_usd: float
    direction_usd: float
    pnl_usd: float


class LiveRiskBook:
    def __init__(self, limits: LiveLimits | None = None) -> None:
        # The configured limits: the owner's floor, and every limit the ladder does not scale.
        self.limits = limits or LiveLimits()
        # The earned-growth ladder's limits for a window, by the window's start (speeddesk_live_ladder.Ladder);
        # None uses the configured limits everywhere. Never persisted here: the controller saves the ladder.
        self.window_limits: Callable[[float], LiveLimits] | None = None
        # When a loss stop last bound (the total stop tripped, or even a one-contract buy was refused by the day or
        # total stop), and who to tell (the ladder: no promotion within 24 h of a stop). Not persisted here.
        self.stop_hit_at: float | None = None
        self.stop_listener: Callable[[float], None] | None = None
        self.windows: dict[str, Window] = {}
        self.intents: dict[str, LiveIntent] = {}
        self.inventory: dict[str, Inventory] = {}
        self.fills: dict[str, ActualFill] = {}
        self.settled: dict[str, LiveSettlement] = {}
        self.day_pnl: dict[str, float] = {}
        # The owner's one-time daily reset: today's loss counts from this result. Keyed by UTC day, so it lapses.
        self.day_anchor: dict[str, float] = {}
        self.realized_pnl = 0.0
        self.stop_anchor = 0.0
        self.halted = False
        self.halt_reason: str | None = None
        # The UTC day whose daily stop has latched (not even a one-contract buy fit under it): no new buys until the
        # day rolls or the owner's one-time day reset. Persisted; the previous release ignores the key.
        self.day_stop_latched: str | None = None
        self.integrity_error: str | None = None
        self.resume_token_hash: str | None = None
        self.seen_resume_hashes: set[str] = set()
        # Resume values seen while no total stop was latched: kept unspent, and never an acknowledgement of a stop
        # that comes later (the stop spends them), so a value left in the settings cannot clear a future halt.
        self.resume_pending: set[str] = set()
        # The stop the owner's one-time reset approved, until it clears or a different check trips.
        self.integrity_reset_armed: str | None = None
        self.bootstrap_order: dict[str, str] = {}
        self.cash_usd: float | None = None
        self.cash_at: float | None = None
        self.cash_debits = 0.0

    def add_window(self, window: Window) -> None:
        if (window.venue != "kalshi" or not window.slug.startswith("KXBTC15M-")
                or not all(math.isfinite(value) for value in (window.start, window.end))
                or abs(window.end - window.start - 900) > EPSILON):
            raise LiveRejected("kalshi_15m_only")
        if window.slug not in self.windows:
            self.windows[window.slug] = window
        self.inventory.setdefault(window.slug, Inventory())

    def limits_for(self, window: str) -> LiveLimits:
        """The limits for buys and locks in one window: fixed by the window's start, so a ladder change never
        reaches a window that has begun."""
        spec = self.windows.get(window)
        if self.window_limits is None or spec is None:
            return self.limits
        return self.window_limits(spec.start)

    def limits_now(self, now: float) -> LiveLimits:
        """The limits of the window under way at `now` (the stops and the status report use them)."""
        return self.limits if self.window_limits is None else self.window_limits(now)

    def update_cash(self, cash_usd: float, now: float) -> None:
        if not math.isfinite(cash_usd) or cash_usd < 0 or not math.isfinite(now):
            raise LiveRejected("cash_unknown")
        if self.cash_at is not None and now < self.cash_at:
            raise LiveRejected("cash_stale")
        self.cash_usd, self.cash_at, self.cash_debits = cash_usd, now, 0.0

    def unit_reserve(self, window: str, price: float, kind: Kind) -> float:
        spec = self.windows[window]
        coefficient = spec.taker_coefficient if kind == "take" else spec.maker_coefficient
        if coefficient is None:
            raise LiveRejected("fee_unknown")
        return reserve_unit_cost(price, coefficient, self.limits.fee_precision)

    @property
    def reserved_usd(self) -> float:
        return sum(intent.reserved for intent in self.intents.values())

    @property
    def open_cost_usd(self) -> float:
        """Gross cost of unsettled windows (both halves of every pair), for display."""
        return sum(value.spent for window, value in self.inventory.items() if window not in self.settled)

    @property
    def open_loss_usd(self) -> float:
        """What unsettled windows can still lose: each window's cost minus the $1 its weaker side pays.

        Up and down pay $1 together whatever happens (Kalshi nets them at once), so a complete pair
        risks nothing and only the unpaired contracts' cost is at risk. Fees are in the cost.
        """
        return sum(max(0.0, value.spent - min(value.up.shares, value.down.shares))
                   for window, value in self.inventory.items() if window not in self.settled)

    @property
    def at_risk_usd(self) -> float:
        """What can still be lost: the open loss plus the pending buys that could add to it.

        A pending lock buy completes pairs, so if it fills the possible loss only falls: it needs cash
        (reserved_usd) but is not added to the loss the stops measure. A pending bid is the same kind of
        order for the part of it that strictly balances its window (see `balancing_contracts`); only the
        rest is new risk.
        """
        return self.open_loss_usd + self.pending_risk_usd

    @property
    def pending_risk_usd(self) -> float:
        """The reserved cost of pending buys that could raise a window's worst-case loss if they fill."""
        total, spare = 0.0, {}  # type: float, dict[str, float]
        for intent in self.intents.values():
            if intent.lock or intent.reserved <= EPSILON:
                continue
            balancing = self.balancing_contracts(intent.window, intent.side, intent.remaining, intent.unit_reserve,
                                                 spare)
            total += (intent.remaining - balancing) * intent.unit_reserve
        return total

    def balancing_contracts(self, window: str, side: Side, size: float, unit: float,
                            spare: dict[str, float] | None = None) -> float:
        """How many of `size` contracts on `side` strictly balance this window: bought on the light side, within
        the unpaired contracts (less any `spare` already claimed by another pending buy of the window), and under
        $1 each at their worst permitted cost.

        Each such contract completes a pair that pays $1 whatever happens, so filling it changes the worst-case
        loss by `unit - 1 < 0`: like a lock, it is exempt from the day and lifetime stops (never from the window
        budget, the open budget, the pair cap or the cash). A buy on the heavy side, a contract beyond the
        unpaired count, or one at $1 or more with fees is new risk. (The pair cap holds for every reserved order:
        `_inventory_guard` refuses a buy that would break it.)
        """
        light, unpaired = self.lock_side(window)
        if light != side or unit >= 1 - EPSILON or size <= EPSILON:
            return 0.0
        left = unpaired if spare is None else spare.setdefault(window, unpaired)
        balancing = max(0.0, min(size, left))
        if spare is not None:
            spare[window] = left - balancing
        return balancing

    def lock_side(self, window: str) -> tuple[Side | None, float]:
        """The side that completes this window's unpaired contracts, and how many are unpaired."""
        value = self.inventory.get(window)
        if value is None or window in self.settled:
            return None, 0.0
        difference = value.up.shares - value.down.shares
        if abs(difference) <= EPSILON:
            return None, 0.0
        return ("down" if difference > 0 else "up"), abs(difference)

    def hedge_unit(self, window: str, price: float, limits: LiveLimits) -> float:
        """The worst permitted cost of one contract of the other side at the pair cap less `price`: what the
        hedge of a first buy at `price` may cost. Raises `pair_cap` when no such price exists."""
        hedge = math.floor((limits.pair_cap - price) * 100 + EPSILON) / 100
        if hedge < 0.01 - EPSILON:
            raise LiveRejected("pair_cap")
        return max(self.unit_reserve(window, hedge, "take"), self.unit_reserve(window, hedge, "rest"))

    def _note_stop(self, now: float) -> None:
        if math.isfinite(now):
            self.stop_hit_at = now if self.stop_hit_at is None else max(self.stop_hit_at, now)
            if self.stop_listener is not None:
                self.stop_listener(now)

    def _halt(self, now: float) -> None:
        """Latch the total stop. Every resume value seen before it is spent by it: a value already in the settings
        when a stop comes never clears that stop (speeddesk_live_model.resume)."""
        if not self.halted:
            self.seen_resume_hashes |= self.resume_pending
            self.resume_pending.clear()
        self.halted, self.halt_reason = True, "total_loss"
        self._note_stop(now)

    def _latch(self, reason: str, now: float) -> None:
        """A stop refused even a one-contract buy: it has tripped, so it latches (and the ladder is told)."""
        if reason == "total_budget":
            self._halt(now)
        elif reason == "day_stop" and math.isfinite(now):
            self.day_stop_latched = utc_day(now)
        self._note_stop(now)

    def day_latched(self, now: float) -> bool:
        return self.day_stop_latched is not None and self.day_stop_latched == utc_day(now)

    def _refresh_stops(self, now: float) -> None:
        loss = max(0.0, self.stop_anchor - self.realized_pnl)
        if loss + self.at_risk_usd >= self.limits.total_loss_usd - EPSILON:
            self._halt(now)

    def latch_bound_stops(self, now: float) -> list[str]:
        """Latch each stop with no room left for even a one-contract hedged first buy (its pair costs at least the
        pair cap less a cent, see `hedge_unit`); returns the stops latched ("total", "day").

        The companion calls this at startup, before it reads any token, so a stop that binds is latched first and
        a token set for it is applied to it, instead of being judged while nothing is latched.
        """
        self._refresh_stops(now)
        limits = self.limits_now(now)
        floor = limits.pair_cap - 0.01
        latched = []
        if not self.halted and (max(0.0, self.stop_anchor - self.realized_pnl) + self.at_risk_usd + floor
                                >= self.limits.total_loss_usd - EPSILON):
            self._halt(now)
            latched.append("total")
        if (math.isfinite(now) and not self.day_latched(now)
                and self.day_loss(now) + self.at_risk_usd + floor >= limits.day_loss_usd - EPSILON):
            self._latch("day_stop", now)
            latched.append("day")
        return latched

    def risk_status(self, now: float) -> dict[str, Any]:
        self._refresh_stops(now)
        limits = self.limits_now(now)
        day_loss = self.day_loss(now)
        total_loss = max(0.0, self.stop_anchor - self.realized_pnl)
        available = None if self.cash_usd is None else max(0.0, self.cash_usd - self.cash_debits - self.reserved_usd)
        day_latched = self.day_latched(now)
        return {"halted": self.halted, "halt_reason": self.halt_reason,
                "integrity_error": self.integrity_error, "reserved_usd": self.reserved_usd,
                "open_cost_usd": self.open_cost_usd, "open_loss_usd": self.open_loss_usd,
                "at_risk_usd": self.at_risk_usd,
                "day_pnl_usd": self.day_pnl.get(utc_day(now), 0.0), "day_loss_usd": day_loss,
                "day_at_risk_usd": day_loss + self.at_risk_usd,
                "day_stopped": day_latched or day_loss + self.at_risk_usd >= limits.day_loss_usd - EPSILON,
                "day_stop_latched": day_latched,
                "total_pnl_usd": self.realized_pnl, "total_loss_usd": total_loss,
                "total_at_risk_usd": total_loss + self.at_risk_usd,
                "available_cash_usd": available, "cash_at": self.cash_at,
                "limits": asdict(limits)}

    def _reject(self, reason: str) -> None:
        raise LiveRejected(reason)

    def _inventory_guard(self, window: str, side: Side, size: float, unit: float, limits: LiveLimits) -> str:
        inventory = self.inventory[window]
        pending = [intent for intent in self.intents.values() if intent.window == window and intent.reserved > EPSILON]
        total = inventory.up.shares + inventory.down.shares
        difference = inventory.up.shares - inventory.down.shares
        starter_id = self.bootstrap_order.get(window)
        starter = self.intents.get(starter_id or "")
        bootstrap = (abs(difference) > limits.max_imbalance * total + EPSILON
                     or bool(starter and starter.reservation_active))
        if total <= EPSILON:
            if pending:
                return "starter_pending"
            if size > limits.clip + EPSILON:
                return "starter_clip"
        elif bootstrap:
            light: Side = "down" if difference > 0 else "up"
            if abs(difference) <= EPSILON or side != light:
                return "balancing_only"
            if size + sum(item.remaining for item in pending if item.side == light) > abs(difference) + EPSILON:
                return "balancing_size"
        for flags in itertools.product((False, True), repeat=len(pending)):
            shares = {"up": inventory.up.shares, "down": inventory.down.shares}
            paid = {"up": inventory.up.total, "down": inventory.down.total}
            for include, intent in zip(flags, pending, strict=True):
                if include:
                    shares[intent.side] += intent.remaining
                    paid[intent.side] += intent.reserved
            shares[side] += size
            paid[side] += size * unit
            if (total > EPSILON and not bootstrap and abs(shares["up"] - shares["down"])
                    > limits.max_imbalance * sum(shares.values()) + EPSILON):
                return "imbalance"
            if min(shares.values()) > EPSILON and sum(paid[key] / shares[key] for key in shares) > limits.pair_cap + EPSILON:
                return "pair_cap"
        return ""

    def can_buy(self, window: str, side: Side, kind: Kind, price: float, size: float, now: float) -> str:
        reason = self._buy_verdict(window, side, kind, price, size, now)
        if reason in STOP_REFUSALS and size <= 1 + EPSILON:
            self._latch(reason, now)  # not even the smallest order fits under the stop: it has tripped, and latches
        return reason

    def starter_fit(self, window: str, side: Side, kind: Kind, price: float, size: float, now: float) -> tuple[int, str]:
        """The largest first buy of at most `size` contracts that leaves room for its hedge, and when none does, why
        one contract is refused.

        A window's first buy must leave room for its hedge (2026-10-13, 3:45 and 4:00 PM PT: first buys sized to the
        last room under the lifetime stop became one-sided bets): the pair's whole worst cost, this buy plus the
        other side at the pair cap less its price (`hedge_unit`), must fit under the day stop and the lifetime stop
        as new risk, and the buy itself must pass `can_buy`. (The companion holds the first buy to whole pairs at
        the pair cap within the window budget before asking.) When not even one hedged contract fits under a stop,
        that stop has tripped and latches, as a refused one-contract buy does in `can_buy`.
        """
        if window not in self.windows or window in self.settled:
            return 0, "window_unknown_or_settled"
        limits = self.limits_for(window)
        try:
            unit = self.unit_reserve(window, price, kind)
            pair = unit + self.hedge_unit(window, price, limits)
        except LiveRejected as exc:
            return 0, exc.reason
        day_room = limits.day_loss_usd - self.day_loss(now) - self.at_risk_usd
        total_room = self.limits.total_loss_usd - max(0.0, self.stop_anchor - self.realized_pnl) - self.at_risk_usd
        reason = ""
        for contracts in range(int(size), 0, -1):
            if contracts * pair >= day_room - EPSILON:
                reason = "day_stop"
            elif contracts * pair >= total_room - EPSILON:
                reason = "total_budget"
            else:
                reason = self._buy_verdict(window, side, kind, price, float(contracts), now)
            if not reason:
                return contracts, ""
        if reason in STOP_REFUSALS:
            self._latch(reason, now)
        return 0, reason

    def _buy_verdict(self, window: str, side: Side, kind: Kind, price: float, size: float, now: float) -> str:
        self._refresh_stops(now)
        if self.integrity_error:
            return "reconciliation_error"
        if self.halted:
            return self.halt_reason or "halted"
        if window not in self.windows or window in self.settled:
            return "window_unknown_or_settled"
        spec = self.windows[window]
        limits = self.limits_for(window)  # the window's ladder rung: every check below uses the same limits
        if now < spec.start or now >= spec.end - limits.lock_s:
            return "cutoff"
        if not (math.isfinite(price) and 0 < price < 1 and abs(price * 100 - round(price * 100)) < EPSILON
                and math.isfinite(size) and size >= 1 and abs(size - round(size)) < EPSILON
                and side in ("up", "down") and kind in ("take", "rest")):
            return "invalid_order"
        if size > limits.clip + EPSILON:
            return "clip"
        if self.cash_at is None or self.cash_usd is None or not 0 <= now - self.cash_at <= limits.cash_max_age_s:
            return "cash_stale"
        if any(item.window == window and item.side == side and item.reservation_active for item in self.intents.values()):
            return "order_pending"
        try:
            unit = self.unit_reserve(window, price, kind)
        except LiveRejected as exc:
            return exc.reason
        cost = size * unit
        # A strictly balancing buy only lowers the worst-case loss: like a lock, it is exempt from both loss stops
        # (never from the window budget, the open budget or the cash). The rest of the buy is new risk.
        risk = cost - self.balancing_contracts(window, side, size, unit) * unit
        current = self.inventory[window].spent + sum(item.reserved for item in self.intents.values() if item.window == window)
        if current + cost > limits.window_usd + EPSILON:
            return "window_budget"
        if self.at_risk_usd + cost > limits.open_usd + EPSILON:
            return "open_budget"
        if self.day_loss(now) + self.at_risk_usd + risk >= limits.day_loss_usd - EPSILON:
            return "day_stop"
        # The lifetime stop never scales: it is the configured one at every rung.
        if max(0.0, self.stop_anchor - self.realized_pnl) + self.at_risk_usd + risk >= self.limits.total_loss_usd - EPSILON:
            return "total_budget"
        if self.day_latched(now):
            return "day_stop"  # latched earlier today; reported after the lifetime stop, the larger of the two
        if cost + self.reserved_usd + self.cash_debits > self.cash_usd + EPSILON:
            return "cash_budget"
        return self._inventory_guard(window, side, size, unit, limits)

    def can_lock(self, window: str, side: Side, price: float, size: float, now: float) -> str:
        """An immediate buy that only completes this window's bought contracts into $1 pairs.

        At any price below $1 including fees it lowers the window's worst-case loss, so the spend
        budgets, pair cap, edge and loss stops (which exist to bound loss) do not apply; it still
        needs reconciled orders, fresh cash and an exact fit to the unpaired contracts.
        """
        if self.integrity_error:
            return "reconciliation_error"
        if window not in self.windows or window in self.settled:
            return "window_unknown_or_settled"
        spec = self.windows[window]
        limits = self.limits_for(window)
        if now < spec.end - limits.lock_s or now >= spec.end - LOCK_MARGIN_S:
            return "not_lock_time"
        if not (math.isfinite(price) and 0 < price < 1 and abs(price * 100 - round(price * 100)) < EPSILON
                and math.isfinite(size) and size >= 1 and abs(size - round(size)) < EPSILON
                and side in ("up", "down")):
            return "invalid_order"
        if price > limits.lock_max_price + EPSILON:
            return "lock_price"
        if size > limits.clip + EPSILON:
            return "clip"
        if self.cash_at is None or self.cash_usd is None or not 0 <= now - self.cash_at <= limits.cash_max_age_s:
            return "cash_stale"
        if any(item.window == window and item.reservation_active for item in self.intents.values()):
            return "order_pending"  # every order in the window is reconciled before the count is trusted
        light, unpaired = self.lock_side(window)
        if light != side or size > unpaired + EPSILON:
            return "lock_size"
        try:
            unit = self.unit_reserve(window, price, "take")
        except LiveRejected as exc:
            return exc.reason
        if unit >= 1 - EPSILON:
            return "lock_price"
        if size * unit + self.reserved_usd + self.cash_debits > self.cash_usd + EPSILON:
            return "cash_budget"
        return ""

    def reserve_intent(self, window: str, side: Side, kind: Kind, price: float, size: float,
                       now: float, client_order_id: str, fair: float | None = None,
                       *, lock: bool = False) -> LiveIntent:
        if (not client_order_id.startswith(CLIENT_PREFIX) or len(client_order_id) <= len(CLIENT_PREFIX)
                or client_order_id in self.intents):
            raise LiveRejected("client_order_id")
        if lock and kind != "take":
            raise LiveRejected("invalid_order")
        reason = (self.can_lock(window, side, price, size, now) if lock
                  else self.can_buy(window, side, kind, price, size, now))
        if reason:
            raise LiveRejected(reason)
        intent = LiveIntent(client_order_id, window, side, kind, price, size, now,
                            self.unit_reserve(window, price, kind), fair, lock=lock)
        self.intents[client_order_id] = intent
        if self.inventory[window].up.shares + self.inventory[window].down.shares <= EPSILON:
            self.bootstrap_order[window] = client_order_id
        return intent

    def mark_submitted(self, client_order_id: str, order_id: str) -> None:
        intent = self.intents[client_order_id]
        if not order_id or (intent.order_id is not None and intent.order_id != order_id):
            self.integrity_error = "order_identity_changed"
            raise LiveRejected(self.integrity_error)
        if any(item.order_id == order_id and item.client_order_id != client_order_id for item in self.intents.values()):
            self.integrity_error = "order_identity_duplicate"
            raise LiveRejected(self.integrity_error)
        if intent.order_id == order_id:
            return  # repeated discovery cannot erase terminal reconciliation evidence
        intent.order_id, intent.status, intent.uncertainty = order_id, "submitted", None

    def mark_uncertain(self, client_order_id: str, reason: str) -> None:
        intent = self.intents[client_order_id]
        safe_reason = reason if reason.isidentifier() and len(reason) <= 64 else "unknown_request_outcome"
        intent.status, intent.uncertainty = "uncertain", safe_reason

    def reject_intent(self, client_order_id: str, reason: str, *, confirmed: bool = False) -> bool:
        """Release only a never-accepted create with definitive caller proof.

        A later rejection cannot disprove an earlier ambiguous create. That
        intent still requires authoritative order/fill reconciliation.
        """
        intent = self.intents[client_order_id]
        if (not confirmed or intent.order_id is not None or intent.filled_size > EPSILON
                or intent.status not in ("intent", "rejected")):
            raise LiveRejected("rejection_unconfirmed")
        if intent.status == "rejected":
            return False
        intent.reservation_active = False
        intent.status = "rejected"
        intent.uncertainty = reason if reason.isidentifier() and len(reason) <= 64 else "create_rejected"
        return True

    def request_cancel(self, client_order_id: str) -> None:
        self.intents[client_order_id].cancel_requested = True

    def record_fill(self, fill: ActualFill) -> bool:
        if fill.fill_id in self.fills:
            if self.fills[fill.fill_id] != fill:
                self.integrity_error = "fill_changed"
                raise LiveRejected(self.integrity_error)
            return False
        intent = self.intents.get(fill.client_order_id)
        if intent is None:
            return False  # owner's orders and account positions never get adopted
        if (not fill.fill_id or not fill.order_id or fill.window != intent.window or fill.side != intent.side
                or (intent.order_id is not None and fill.order_id != intent.order_id)):
            self.integrity_error = "fill_identity_mismatch"
            raise LiveRejected(self.integrity_error)
        if not (all(math.isfinite(value) for value in (fill.price, fill.size, fill.fee_usd, fill.at))
                and 0 < fill.price < 1 and fill.size > 0 and fill.fee_usd >= 0
                and abs(fill.size * 100 - round(fill.size * 100)) < EPSILON):
            self.integrity_error = "fill_values_invalid"
            raise LiveRejected(self.integrity_error)
        if fill.window in self.settled:
            self.integrity_error = "fill_after_settlement"
            raise LiveRejected(self.integrity_error)
        released_before_fill = not intent.reservation_active
        self.mark_submitted(fill.client_order_id, fill.order_id)
        holding = getattr(self.inventory[fill.window], fill.side)
        holding.shares += fill.size
        holding.cost += fill.size * fill.price
        holding.fees += fill.fee_usd
        self.fills[fill.fill_id] = fill
        intent.filled_size += fill.size
        self.cash_debits += fill.size * fill.price + fill.fee_usd
        if released_before_fill:
            # Authoritative new execution contradicts the earlier claim
            # that all terminal fills were reconciled. Keep the real cost
            # and reserve every still-possible contract until reconciled.
            self.integrity_error = "fill_after_terminal_confirmation"
            intent.reservation_active = True
        if intent.filled_size >= intent.size - EPSILON:
            intent.reservation_active = False
            intent.status = "filled"
        if (intent.filled_size > intent.size + EPSILON or fill.price > intent.price + EPSILON
                or fill.size * fill.price + fill.fee_usd > fill.size * intent.unit_reserve + EPSILON):
            self.integrity_error = "fill_exceeded_reserved_terms"
        self._refresh_stops(fill.at)
        return True

    def reconcile_order(self, snapshot: OrderSnapshot, *, fills_complete: bool = False, lag_ok: bool = False) -> bool:
        intent = self.intents.get(snapshot.client_order_id)
        if intent is None:
            return False
        if intent.last_snapshot_at is not None and snapshot.at < intent.last_snapshot_at:
            return False
        if (snapshot.status not in ("resting", "canceled", "executed")
                or not all(math.isfinite(value) and value >= 0 for value in (snapshot.filled_size, snapshot.remaining_size, snapshot.at))
                or snapshot.filled_size + snapshot.remaining_size > intent.size + EPSILON):
            self.integrity_error = "order_snapshot_invalid"
            raise LiveRejected(self.integrity_error)
        if snapshot.filled_size + EPSILON < intent.reported_filled_size:
            intent.uncertainty = "order_fill_count_regressed"
            return False
        if lag_ok and snapshot.filled_size + EPSILON < intent.filled_size:
            # Kalshi's order list can trail its fills list (2026-10-13 02:00:03 UTC: a one-contract fill was
            # booked, then the order was still listed as resting with nothing filled). A report older than fills
            # already booked proves nothing new; the caller re-reads, and stops for good if the lag persists.
            intent.uncertainty = "order_list_behind_fills"
            return False
        if not intent.reservation_active and snapshot.remaining_size > EPSILON:
            intent.reservation_active = True
            self.integrity_error = "order_terminal_regressed"
            raise LiveRejected(self.integrity_error)
        self.mark_submitted(snapshot.client_order_id, snapshot.order_id)
        intent.last_snapshot_at = snapshot.at
        intent.reported_filled_size = max(intent.reported_filled_size, snapshot.filled_size)
        intent.venue_remaining_size = snapshot.remaining_size
        intent.status = snapshot.status
        reconciled = abs(snapshot.filled_size - intent.filled_size) <= EPSILON
        if fills_complete and snapshot.filled_size + EPSILON < intent.filled_size:
            self.integrity_error = "order_fill_count_mismatch"
            raise LiveRejected(self.integrity_error)
        if (snapshot.status in ("canceled", "executed") and fills_complete and reconciled
                and snapshot.remaining_size <= EPSILON):
            intent.reservation_active = False
            intent.uncertainty = None
            return True
        return False

    def expected_position(self, window: str) -> float:
        value = self.inventory.get(window, Inventory())
        return 0.0 if window in self.settled else value.up.shares - value.down.shares

    def settle(self, window: str, up_wins: bool, now: float, settlement_id: str,
               *, net_payout_usd: float | None = None) -> LiveSettlement | None:
        if window in self.settled:
            return None
        if (not settlement_id or window not in self.windows or not isinstance(up_wins, bool)
                or not math.isfinite(now) or now < self.windows[window].end):
            raise LiveRejected("settlement_invalid")
        if any(item.window == window and item.reservation_active for item in self.intents.values()):
            raise LiveRejected("settlement_orders_unreconciled")
        inventory = self.inventory[window]
        gross = settlement(window, inventory, up_wins, now)
        pairs = min(inventory.up.shares, inventory.down.shares)
        expected_net = gross.payout_usd - pairs
        if net_payout_usd is not None and (not math.isfinite(net_payout_usd) or abs(net_payout_usd - expected_net) > 0.000001):
            self.integrity_error = "settlement_net_payout_mismatch"
            raise LiveRejected(self.integrity_error)
        # Each bought opposite pair nets to $1 before final settlement. Add
        # that credit once and only the remaining signed position's payout.
        result = LiveSettlement(window, settlement_id, now, up_wins, gross.up_shares, gross.down_shares,
                                gross.cost_usd, gross.fee_usd, pairs, expected_net, gross.payout_usd,
                                gross.locked_usd, gross.direction_usd, gross.pnl_usd)
        self.settled[window] = result
        self.realized_pnl += result.pnl_usd
        self.day_pnl[utc_day(now)] = self.day_pnl.get(utc_day(now), 0.0) + result.pnl_usd
        self._refresh_stops(now)
        return result

    def resume(self, token: str) -> ResumeOutcome:
        """The owner's acknowledgement of a latched total stop: a new value clears it exactly once and a fresh stop
        budget counts from the result now.

        A value seen while no total stop is latched is not spent ("not_halted"): it stays in the settings unused.
        It is spent the moment a total stop latches, so a value present before a stop never clears it (only a value
        set after the stop acknowledges it). A reconciliation stop keeps the value unspent too ("integrity"); it
        applies once that stop is cleared. Only fingerprints are kept, never the value.
        """
        if not token:
            return ""
        digest = hashlib.sha256(token.encode()).hexdigest()
        if digest in self.seen_resume_hashes:
            return "used"
        if not self.halted or self.integrity_error:
            self.resume_pending.add(digest)
            return "integrity" if self.integrity_error else "not_halted"
        self.resume_pending.discard(digest)
        self.seen_resume_hashes.add(digest)
        self.resume_token_hash = digest
        self.stop_anchor = self.realized_pnl
        self.halted, self.halt_reason = False, None
        return "applied"

    def apply_resume_token(self, token: str) -> bool:
        return self.resume(token) == "applied"

    def day_loss(self, now: float) -> float:
        """Today's settled loss, counted from the owner's one-time reset when one was made today."""
        day = utc_day(now)
        return max(0.0, self.day_anchor.get(day, 0.0) - self.day_pnl.get(day, 0.0))

    def apply_day_reset(self, token: str, now: float) -> str:
        """The owner's one-time fresh daily budget (owner, 2026-10-13: "U can reset it go ahead", "Approve
        everything").

        Today's loss counts again from the result at the moment a new value is first seen, and a latched daily stop
        clears with it. The daily cap itself, the lifetime stop and every other limit are unchanged, and the next
        UTC day starts from zero as always. The value is spent on first sight, with its own fingerprint kind, so no
        restart or rollback resets twice. Returns "reset", "used" or "" (no value)."""
        if not token:
            return ""
        digest = hashlib.sha256(DAY_RESET_DOMAIN + token.encode()).hexdigest()
        if digest in self.seen_resume_hashes:
            return "used"
        self.seen_resume_hashes.add(digest)
        day = utc_day(now)
        self.day_anchor = {day: self.day_pnl.get(day, 0.0)}
        self.day_stop_latched = None
        return "reset"

    def arm_integrity_reset(self, token: str) -> str:
        """The owner's one-time reset of a reconciliation stop (owner, 2026-10-13: "Yes, reset it").

        A value is spent the moment it is first seen, whatever happens next, and its fingerprint is kept with the
        resume fingerprints, which the previous release also keeps: no restart or rollback can let it approve a
        second stop. It approves only the stop present now; with no stop it approves nothing. Returns "armed",
        "no_stop", "used" or "" (no value). The stop is cleared by `reset_integrity`, once the books are clean."""
        if not token:
            return ""
        digest = hashlib.sha256(RESET_DOMAIN + token.encode()).hexdigest()
        if digest in self.seen_resume_hashes:
            return "used"
        self.seen_resume_hashes.add(digest)
        if not self.integrity_error:
            return "no_stop"
        self.integrity_reset_armed = self.integrity_error
        return "armed"

    def disarm_stale_reset(self) -> str | None:
        """Withdraw an approval whose stop is no longer the one present; returns the approved check's code."""
        if self.integrity_reset_armed is not None and self.integrity_reset_armed != self.integrity_error:
            code, self.integrity_reset_armed = self.integrity_reset_armed, None
            return code
        return None

    def integrity_reset_blocker(self) -> str:
        """Why the books cannot clear the approved stop yet; empty when they can."""
        if not self.integrity_error:
            return "no_integrity_error"
        if self.integrity_reset_armed != self.integrity_error:
            return "not_armed"
        if any(intent.reservation_active for intent in self.intents.values()) or self.reserved_usd > EPSILON:
            return "orders_reserved"
        if any(window not in self.settled and value.up.shares + value.down.shares > EPSILON
               for window, value in self.inventory.items()):
            return "positions_open"
        return ""

    def reset_integrity(self) -> str:
        """Clear the approved stop, once; returns the cleared check's code."""
        code = self.integrity_error
        if code is None or self.integrity_reset_blocker():
            raise LiveRejected("integrity_reset_refused")
        self.integrity_error = self.integrity_reset_armed = None
        return code

    def window_parts(self, keep: Callable[[str], bool]) -> dict[str, dict[str, Any]]:
        """The per-window parts of the saved state (WINDOW_PARTS) for the windows ``keep`` accepts."""
        return {"windows": {key: asdict(value) for key, value in self.windows.items() if keep(key)},
                "intents": {key: without_default_lock(asdict(value)) for key, value in self.intents.items()
                            if keep(value.window)},
                "inventory": {key: asdict(value) for key, value in self.inventory.items() if keep(key)},
                "fills": {key: asdict(value) for key, value in self.fills.items() if keep(value.window)},
                "settled": {key: asdict(value) for key, value in self.settled.items() if keep(key)}}

    def to_state(self, without: frozenset[str] | set[str] = frozenset()) -> dict[str, Any]:
        """The saved state; windows in ``without`` are left to the caller's write-once archive."""
        # Fields added for locks are written only when they carry information, so the previous release can
        # still read a state with no pending lock if a deployment is rolled back (limits come from settings).
        limits = {key: value for key, value in asdict(self.limits).items() if key not in ("lock_s", "lock_max_price")}
        return {"version": 1, "venue": "kalshi", "limits": limits,
                **self.window_parts(lambda window: window not in without),
                "day_pnl": self.day_pnl, "realized_pnl": self.realized_pnl, "stop_anchor": self.stop_anchor,
                "halted": self.halted, "halt_reason": self.halt_reason, "integrity_error": self.integrity_error,
                "resume_token_hash": self.resume_token_hash, "seen_resume_hashes": sorted(self.seen_resume_hashes),
                # The previous release ignores this top-level key on a rollback, so a rollback withdraws the approval.
                "integrity_reset_armed": self.integrity_reset_armed,
                # Also ignored by the previous release: a rollback returns to the plain daily stop.
                "day_anchor": self.day_anchor,
                # Also ignored by the previous release: a rollback forgets a latched daily stop (its per-buy check
                # still refuses buys over the stop) and spends a kept resume value on sight, as it always did.
                "day_stop_day": self.day_stop_latched,
                "resume_pending": sorted(self.resume_pending),
                "bootstrap_order": self.bootstrap_order}

    @classmethod
    def from_state(cls, state: dict[str, Any], limits: LiveLimits | None = None) -> LiveRiskBook:
        if state.get("version") != 1 or state.get("venue") != "kalshi":
            raise ValueError("Unsupported live accounting state")
        book = cls(limits or LiveLimits(**state["limits"]))
        for value in state["windows"].values():
            book.add_window(Window(**value))
        book.intents = {key: LiveIntent(**value) for key, value in state["intents"].items()}
        book.inventory = {key: Inventory(Holding(**value["up"]), Holding(**value["down"]))
                          for key, value in state["inventory"].items()}
        book.fills = {key: ActualFill(**value) for key, value in state["fills"].items()}
        book.settled = {key: LiveSettlement(**value) for key, value in state["settled"].items()}
        book.day_pnl = state["day_pnl"]
        book.realized_pnl, book.stop_anchor = state["realized_pnl"], state["stop_anchor"]
        book.halted, book.halt_reason = state["halted"], state["halt_reason"]
        book.integrity_error, book.resume_token_hash = state["integrity_error"], state["resume_token_hash"]
        book.seen_resume_hashes = set(state.get("seen_resume_hashes", []))
        if book.resume_token_hash is not None:
            book.seen_resume_hashes.add(book.resume_token_hash)
        book.integrity_reset_armed = state.get("integrity_reset_armed")
        book.day_anchor = state.get("day_anchor", {})
        book.day_stop_latched = state.get("day_stop_day")
        book.resume_pending = set(state.get("resume_pending", [])) - book.seen_resume_hashes
        book.bootstrap_order = state["bootstrap_order"]
        # A restart cannot release uncertain orders or reuse an old balance.
        book._validate_state()
        return book

    def _validate_state(self) -> None:
        if set(self.inventory) != set(self.windows) or not isinstance(self.halted, bool):
            raise ValueError("Invalid persisted window or stop state")
        if any(not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
               for value in self.seen_resume_hashes | self.resume_pending):
            raise ValueError("Invalid persisted resume token hash")
        if self.day_stop_latched is not None and (not isinstance(self.day_stop_latched, str)
                                                  or not DAY_KEY.fullmatch(self.day_stop_latched)):
            raise ValueError("Invalid persisted daily stop")
        if self.integrity_reset_armed is not None and (not isinstance(self.integrity_reset_armed, str)
                                                       or not self.integrity_reset_armed.isidentifier()):
            raise ValueError("Invalid persisted integrity reset approval")
        if not isinstance(self.day_anchor, dict) or any(
                not isinstance(day, str) or not DAY_KEY.fullmatch(day) or isinstance(value, bool)
                or not isinstance(value, (int, float)) or not math.isfinite(value)
                for day, value in self.day_anchor.items()):
            raise ValueError("Invalid persisted daily reset")
        values = [self.realized_pnl, self.stop_anchor, *self.day_pnl.values()]
        values.extend(value for inventory in self.inventory.values() for holding in (inventory.up, inventory.down)
                      for value in (holding.shares, holding.cost, holding.fees))
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ValueError("Invalid persisted live accounting")
        if any(holding.shares < 0 or holding.cost < 0 or holding.fees < 0
               for inventory in self.inventory.values() for holding in (inventory.up, inventory.down)):
            raise ValueError("Negative persisted live holdings")
        order_ids: set[str] = set()
        for key, intent in self.intents.items():
            if (key != intent.client_order_id or not key.startswith(CLIENT_PREFIX) or intent.window not in self.windows
                    or intent.side not in ("up", "down") or intent.kind not in ("take", "rest")
                    or not all(math.isfinite(value) and value >= 0 for value in
                               (intent.price, intent.size, intent.unit_reserve, intent.filled_size,
                                intent.created_at, intent.reported_filled_size))
                    or not 0 < intent.price < 1 or intent.size < 1
                    or abs(intent.size - round(intent.size)) > EPSILON
                    or abs(intent.price * 100 - round(intent.price * 100)) > EPSILON
                    or intent.unit_reserve < intent.price - EPSILON
                    or not isinstance(intent.reservation_active, bool)
                    or not isinstance(intent.cancel_requested, bool)
                    or not isinstance(intent.lock, bool) or (intent.lock and intent.kind != "take")):
                raise ValueError("Invalid persisted live intent")
            for value in (intent.last_snapshot_at, intent.venue_remaining_size, intent.fair):
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError("Invalid persisted live intent metadata")
            if intent.order_id is not None:
                if not intent.order_id or intent.order_id in order_ids:
                    raise ValueError("Duplicate persisted venue order")
                order_ids.add(intent.order_id)
            full = intent.filled_size >= intent.size - EPSILON
            rejected = intent.status == "rejected" and intent.order_id is None and intent.filled_size <= EPSILON
            terminal = (intent.status in ("canceled", "executed") and intent.order_id is not None
                        and intent.last_snapshot_at is not None and intent.venue_remaining_size == 0
                        and abs(intent.reported_filled_size - intent.filled_size) <= EPSILON)
            if not intent.reservation_active and not (full or rejected or terminal):
                raise ValueError("Persisted reservation lacks terminal evidence")
        if any(window not in self.windows or identity not in self.intents or self.intents[identity].window != window
               for window, identity in self.bootstrap_order.items()):
            raise ValueError("Invalid persisted opening intent")
        rebuilt = {window: Inventory() for window in self.inventory}
        quantities: dict[str, float] = {}
        for key, fill in self.fills.items():
            owner_intent = self.intents.get(fill.client_order_id)
            if (key != fill.fill_id or owner_intent is None or fill.window != owner_intent.window
                    or fill.side != owner_intent.side or fill.order_id != owner_intent.order_id or fill.window not in rebuilt
                    or not all(math.isfinite(value) for value in (fill.size, fill.price, fill.fee_usd, fill.at))
                    or fill.size <= 0 or not 0 < fill.price < 1 or fill.fee_usd < 0
                    or abs(fill.size * 100 - round(fill.size * 100)) > EPSILON):
                raise ValueError("Invalid persisted actual fill")
            holding = getattr(rebuilt[fill.window], fill.side)
            holding.shares += fill.size
            holding.cost += fill.size * fill.price
            holding.fees += fill.fee_usd
            quantities[fill.client_order_id] = quantities.get(fill.client_order_id, 0.0) + fill.size
        for window, inventory in self.inventory.items():
            if window not in self.windows:
                raise ValueError("Unknown persisted live window")
            for side in ("up", "down"):
                observed, expected = getattr(inventory, side), getattr(rebuilt[window], side)
                if any(abs(getattr(observed, name) - getattr(expected, name)) > EPSILON
                       for name in ("shares", "cost", "fees")):
                    raise ValueError("Persisted live inventory does not match actual fills")
        for key, intent in self.intents.items():
            if abs(intent.filled_size - quantities.get(key, 0.0)) > EPSILON:
                raise ValueError("Persisted order quantity does not match actual fills")
        if abs(self.realized_pnl - sum(result.pnl_usd for result in self.settled.values())) > EPSILON:
            raise ValueError("Persisted realized result does not match settlements")
        rebuilt_days: dict[str, float] = {}
        for window, result in self.settled.items():
            amounts = (result.at, result.up_shares, result.down_shares, result.cost_usd, result.fee_usd,
                       result.paired_credit_usd, result.net_payout_usd, result.payout_usd,
                       result.locked_usd, result.direction_usd, result.pnl_usd)
            if (window != result.window or window not in self.windows or not result.settlement_id
                    or not isinstance(result.up_wins, bool) or not all(math.isfinite(value) for value in amounts)
                    or result.at < self.windows[window].end
                    or any(intent.window == window and intent.reservation_active for intent in self.intents.values())):
                raise ValueError("Unknown persisted settlement")
            expected_result = settlement(window, self.inventory[window], result.up_wins, result.at)
            pairs = min(expected_result.up_shares, expected_result.down_shares)
            if any(abs(getattr(result, name) - getattr(expected_result, name)) > EPSILON
                   for name in ("up_shares", "down_shares", "cost_usd", "fee_usd", "payout_usd",
                                "locked_usd", "direction_usd", "pnl_usd")) or (
                    abs(result.paired_credit_usd - pairs) > EPSILON
                    or abs(result.net_payout_usd - expected_result.payout_usd + pairs) > EPSILON):
                raise ValueError("Persisted settlement does not match actual inventory")
            day = utc_day(result.at)
            rebuilt_days[day] = rebuilt_days.get(day, 0.0) + result.pnl_usd
        if any(abs(self.day_pnl.get(day, 0.0) - rebuilt_days.get(day, 0.0)) > EPSILON
               for day in self.day_pnl.keys() | rebuilt_days.keys()):
            raise ValueError("Persisted day result does not match settlements")

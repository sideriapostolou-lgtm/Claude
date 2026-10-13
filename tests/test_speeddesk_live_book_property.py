"""Randomized event orders against LiveRiskBook (the caps review of 2026-10-13, kept as a regression test).

10,000 events per seed: buys, locks, acks, definite and uncertain creates, fills charged the reservation's whole fee,
confirmed cancels, unsent releases, settlements and UTC day rollovers. Invariants after EVERY event (not only after
reservations):
  * every reservation <= clip (5) contracts
  * window gross (spent + reserved) <= window cap, except windows where a lock was reserved (locks are exempt by design)
  * at_risk (worst case over every pending-order combination) <= open cap
  * day realized loss + at_risk < day stop, total realized loss + at_risk < total stop
  * an independent brute-force worst case (grid of partial fills) never exceeds at_risk
  * realized day / total loss never exceeds the stops
  * phi = loss + at_risk never rises on a non-reservation event (fills, cancels, rejections, releases, settlements)
  * the indexed sums (money at risk, reservations, open cost and loss) equal full scans of every order and window
    (latency review: they no longer walk the whole history)
"""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter

import pytest

from nightcrawler.speeddesk_live_model import (
    ActualFill,
    LiveLimits,
    LiveRiskBook,
    OrderSnapshot,
)
from nightcrawler.speeddesk_model import EPSILON, Window, utc_day

EPS = 1e-7
OWNER = LiveLimits(window_usd=10, open_usd=20, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)
T0 = 1_791_892_800.0 - 3 * 900  # 45 minutes before a UTC midnight, so days roll over during the run


def brute_worst(book: LiveRiskBook, window: str, grid: int = 3) -> float:
    inventory = book.inventory[window]
    pending = [i for i in book.intents.values() if i.window == window and i.reserved > 1e-12]
    worst = 0.0
    for fractions in itertools.product([s / grid for s in range(grid + 1)], repeat=len(pending)):
        shares = {"up": inventory.up.shares, "down": inventory.down.shares}
        paid = inventory.spent
        for fraction, intent in zip(fractions, pending, strict=True):
            shares[intent.side] += fraction * intent.remaining
            paid += fraction * intent.reserved
        worst = max(worst, paid - min(shares.values()))
    return worst


def full_scan(book: LiveRiskBook) -> tuple[float, float, float, float]:
    """The sums as the book computed them before its index: over every order and window ever made."""
    legs: dict[str, list[tuple[str, float, float]]] = {}
    for intent in book.intents.values():
        if intent.reserved > EPSILON:
            legs.setdefault(intent.window, []).append((intent.side, intent.remaining, intent.reserved))
    unsettled = [(window, value) for window, value in book.inventory.items() if window not in book.settled]
    return (sum(LiveRiskBook._worst(value, legs.get(window, [])) for window, value in unsettled),  # type: ignore[arg-type]
            sum(intent.reserved for intent in book.intents.values()),
            sum(value.spent for _window, value in unsettled),
            sum(max(0.0, value.spent - min(value.up.shares, value.down.shares)) for _window, value in unsettled))


class Sim:
    def __init__(self, seed: int, limits: LiveLimits, prior_max: float = 4.0) -> None:
        self.rng = random.Random(seed)
        self.limits = limits
        self.book = LiveRiskBook(limits)
        self.now = T0
        self.seq = itertools.count()
        self.windows: list[str] = []
        self.locked_windows: set[str] = set()
        self.counts: Counter[str] = Counter()
        self.next_start = T0 - 30
        self.prior = -round(self.rng.uniform(0, prior_max), 2)
        # A loss earlier today that the book knows (settled before this run).
        self.book.day_pnl[utc_day(self.now)] = self.prior
        self.book.realized_pnl = self.prior
        self.book.update_cash(200.0, self.now)

    # ------------------------------------------------------------------ helpers
    def open_windows(self) -> list[str]:
        return [w for w in self.windows if self.book.windows[w].start <= self.now < self.book.windows[w].end]

    def phi(self) -> tuple[float, float]:
        at_risk = self.book.at_risk_usd
        return (self.book.day_loss(self.now) + at_risk,
                max(0.0, self.book.stop_anchor - self.book.realized_pnl) + at_risk)

    def check(self, event: str, before: tuple[float, float], day_before: str) -> None:
        book, limits = self.book, self.limits
        indexed = (book.at_risk_usd, book.reserved_usd, book.open_cost_usd, book.open_loss_usd)
        assert indexed == pytest.approx(full_scan(book), abs=1e-12), (event, indexed, full_scan(book))
        for intent in book.intents.values():
            assert intent.size <= limits.clip + EPS, intent
        for slug in self.windows:
            if slug in book.settled:
                continue
            gross = book.inventory[slug].spent + sum(i.reserved for i in book.intents.values() if i.window == slug)
            if slug not in self.locked_windows:
                assert gross <= limits.window_usd + EPS, (event, slug, gross)
            assert brute_worst(book, slug) <= book.worst_loss(slug) + EPS
        at_risk = book.at_risk_usd
        assert at_risk <= limits.open_usd + EPS, (event, at_risk)
        day_phi, total_phi = self.phi()
        assert day_phi < limits.day_loss_usd + EPS, (event, day_phi)
        assert total_phi < limits.total_loss_usd + EPS, (event, total_phi)
        assert book.day_loss(self.now) <= limits.day_loss_usd + EPS
        assert max(0.0, book.stop_anchor - book.realized_pnl) <= limits.total_loss_usd + EPS
        if event != "reserve" and utc_day(self.now) == day_before:
            assert day_phi <= before[0] + EPS, (event, before, day_phi)
            assert total_phi <= before[1] + EPS, (event, before, total_phi)

    # ------------------------------------------------------------------ events
    def add_due_windows(self) -> None:
        while self.next_start <= self.now + 60:
            slug = f"KXBTC15M-PROP{next(self.seq)}"
            self.book.add_window(Window(slug, self.next_start, self.next_start + 900, 100.0, taker_coefficient=.07,
                                        maker_coefficient=0.0, venue="kalshi"))
            self.windows.append(slug)
            self.next_start += 900

    def ev_advance(self) -> str:
        self.now += self.rng.choice((0.2, 1.0, 5.0, 20.0, 60.0, 150.0))
        self.add_due_windows()
        if self.rng.random() < .9:
            self.book.update_cash(max(0.0, 200.0 - self.book.cash_debits * 0), self.now)
        return "advance"

    def ev_buy(self) -> str:
        choices = self.open_windows()
        if not choices:
            return "noop"
        slug = self.rng.choice(choices)
        side = self.rng.choice(("up", "down"))
        kind = self.rng.choice(("take", "rest", "rest"))
        price = round(self.rng.uniform(.03, .97), 2)
        size = self.rng.randint(1, 7)
        reason = self.book.can_buy(slug, side, kind, price, size, self.now)
        self.counts[f"can_buy:{reason or 'ok'}"] += 1
        if reason:
            return "noop"
        before_worst = self.book.worst_loss(slug)
        intent = self.book.reserve_intent(slug, side, kind, price, size, self.now, f"nc-speed-{next(self.seq)}", .5)
        if self.book.worst_loss(slug) <= before_worst + EPS:
            self.counts["balancing_reserved"] += 1
        else:
            self.counts["risk_adding_reserved"] += 1
        assert intent.size <= 5
        return "reserve"

    def ev_lock(self) -> str:
        for slug in self.windows:
            side, unpaired = self.book.lock_side(slug)
            if side is None or unpaired < 1:
                continue
            price = round(self.rng.uniform(.5, .99), 2)
            size = self.rng.randint(1, max(1, math.floor(unpaired)))
            if self.book.can_lock(slug, side, price, size, self.now) == "":
                before = self.book.worst_loss(slug)
                self.book.reserve_intent(slug, side, "take", price, size, self.now, f"nc-speed-{next(self.seq)}",
                                         price, lock=True)
                assert self.book.worst_loss(slug) <= before + EPS  # a lock never raises the worst case
                self.locked_windows.add(slug)
                self.counts["lock_reserved"] += 1
                return "reserve"
        return "noop"

    def active(self) -> list:
        return [i for i in self.book.intents.values() if i.reservation_active]

    def ev_ack(self) -> str:
        pending = [i for i in self.active() if i.order_id is None]
        if not pending:
            return "noop"
        intent = self.rng.choice(pending)
        self.book.mark_submitted(intent.client_order_id, f"venue-{intent.client_order_id}")
        return "ack"

    def ev_create_fail(self) -> str:
        pending = [i for i in self.active() if i.order_id is None and i.status == "intent"]
        if not pending:
            return "noop"
        intent = self.rng.choice(pending)
        if self.rng.random() < .5:
            self.book.reject_intent(intent.client_order_id, "definite_create_rejection", confirmed=True)
            return "reject"
        self.book.mark_uncertain(intent.client_order_id, "create_unconfirmed")
        return "uncertain"

    def ev_fill(self) -> str:
        pending = [i for i in self.active() if i.remaining > 1e-9 and i.window not in self.book.settled
                   and self.now < self.book.windows[i.window].end + 5]
        if not pending:
            return "noop"
        intent = self.rng.choice(pending)
        size = min(intent.remaining, self.rng.choice((0.01, 1.0, 2.0, intent.remaining, intent.remaining)))
        size = math.floor(size * 100 + 1e-9) / 100
        if size <= 0:
            return "noop"
        cents = round(intent.price * 100)
        price = self.rng.randint(max(1, cents - 5), cents) / 100 if intent.kind == "take" else intent.price
        # Adversarial fee: as much as the reservation allows (rounded down to the fee grid).
        fee = math.floor((size * intent.unit_reserve - size * price) * 10000 + 1e-9) / 10000
        fee = max(0.0, fee)
        fill = ActualFill(f"fill-{next(self.seq)}", intent.order_id or f"venue-{intent.client_order_id}",
                          intent.client_order_id, intent.window, intent.side, price, size, fee, self.now)
        assert self.book.record_fill(fill)
        assert self.book.integrity_error is None, self.book.integrity_error
        self.counts["fill"] += 1
        return "fill"

    def ev_cancel_confirmed(self) -> str:
        pending = [i for i in self.active() if i.order_id is not None]
        if not pending:
            return "noop"
        intent = self.rng.choice(pending)
        self.book.request_cancel(intent.client_order_id)
        snapshot = OrderSnapshot(intent.client_order_id, intent.order_id, "canceled", intent.filled_size, 0.0,
                                 self.now)
        assert self.book.reconcile_order(snapshot, fills_complete=True)
        self.counts["cancel_confirmed"] += 1
        return "cancel"

    def ev_release_unsent(self) -> str:
        pending = [i for i in self.active() if i.order_id is None and i.filled_size <= 1e-9
                   and self.now >= self.book.windows[i.window].end + 30]
        if not pending:
            return "noop"
        intent = self.rng.choice(pending)
        self.book.release_unsent(intent.client_order_id)
        self.counts["release_unsent"] += 1
        return "release"

    def ev_settle(self) -> str:
        due = [w for w in self.windows if w not in self.book.settled and self.now >= self.book.windows[w].end
               and not any(i.window == w and i.reservation_active for i in self.book.intents.values())]
        if not due:
            return "noop"
        slug = self.rng.choice(due)
        assert self.book.settle(slug, self.rng.random() < .5, self.now, f"settle-{slug}") is not None
        self.counts["settled"] += 1
        return "settle"

    def ev_resume(self) -> str:
        # The owner's resume token: only meaningful when halted; spent once.
        if self.book.halted and self.rng.random() < .5:
            self.book.apply_resume_token(f"resume-{next(self.seq)}")
            self.counts["resume"] += 1
            return "owner"
        return "noop"

    def run(self, events: int) -> None:
        self.add_due_windows()
        table = [(self.ev_advance, 18), (self.ev_buy, 30), (self.ev_lock, 4), (self.ev_ack, 12),
                 (self.ev_create_fail, 3), (self.ev_fill, 18), (self.ev_cancel_confirmed, 8),
                 (self.ev_release_unsent, 2), (self.ev_settle, 6), (self.ev_resume, 1)]
        actions = [action for action, weight in table for _ in range(weight)]
        for _ in range(events):
            before, day = self.phi(), utc_day(self.now)
            event = self.rng.choice(actions)()
            self.counts[event] += 1
            if event in ("owner",):
                continue  # a new stop anchor is the owner's explicit choice
            self.check(event, before, day)


@pytest.mark.parametrize("seed", range(6))
def test_ten_thousand_random_events_never_cross_a_cap_or_stop(seed: int) -> None:
    sim = Sim(seed, OWNER)
    sim.run(10_000)
    # The run must actually exercise the interesting paths.
    print(seed, dict(sorted(sim.counts.items())))
    assert sim.counts["reserve"] > 150 and sim.counts["fill"] > 150 and sim.counts["settled"] > 20
    assert sim.counts["balancing_reserved"] > 20 and sim.counts["risk_adding_reserved"] > 20
    assert sim.counts["can_buy:day_stop"] + sim.counts["can_buy:total_budget"] > 0


@pytest.mark.parametrize("seed", range(3))
def test_small_caps_and_cent_fee_grid(seed: int) -> None:
    limits = LiveLimits(window_usd=2, open_usd=4, day_loss_usd=3, total_loss_usd=5, clip=5, fee_precision=.01)
    sim = Sim(100 + seed, limits, prior_max=0.5)
    sim.run(10_000)
    print(seed, dict(sorted(sim.counts.items())))
    assert sim.counts["reserve"] >= 5

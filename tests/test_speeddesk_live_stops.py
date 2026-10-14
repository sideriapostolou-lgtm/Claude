"""The 2026-10-13 loss fixes: balancing buys are not new risk, a first buy leaves room for its hedge, the stops latch
and the owner's day reset reaches the practice twin. Synthetic windows and a fake Kalshi account only."""

from __future__ import annotations

import asyncio
import itertools
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, events, make_desk

from nightcrawler.config import Secret
from nightcrawler.speeddesk_live import KalshiLiveDesk
from nightcrawler.speeddesk_live_model import (
    STOP_REFUSALS,
    ActualFill,
    LiveIntent,
    LiveLimits,
    LiveRejected,
    LiveRiskBook,
    OrderSnapshot,
    reserve_unit_cost,
)
from nightcrawler.speeddesk_model import PracticeDesk, SpeedConfig, Window, utc_day

T0 = 1_791_475_200.0  # 2026-10-08 16:00 UTC, a quarter-hour boundary
# The owner's floor as Railway sets it (the ladder's rung 0): $10 a window, $20 open, $6 day stop, $10 total stop.
FLOOR = LiveLimits(window_usd=10, open_usd=20, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)
CAPS = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0,
        "speeddesk_kalshi_day_stop_usd": 6.0, "speeddesk_kalshi_total_stop_usd": 10.0}
EPS = 1e-9


def slot(index: int) -> Window:
    start = T0 + 900 * index
    return Window(f"KXBTC15M-S{index + 1000:05d}", start, start + 900, 100, taker_coefficient=.07,
                  maker_coefficient=0, venue="kalshi")


def book_with(index: int = 0, *, limits: LiveLimits = FLOOR, cash: float = 1_000.0) -> tuple[LiveRiskBook, Window, float]:
    book = LiveRiskBook(limits)
    window = slot(index)
    book.add_window(window)
    at = window.start + 10
    book.update_cash(cash, at)
    return book, window, at


def filled(book: LiveRiskBook, window: Window, side: Any, price: float, size: float, at: float, *, kind: Any = "rest",
           name: str | None = None) -> LiveIntent:
    """A buy through the book's own checks, filled in full at its price (a maker bid pays no fee)."""
    client = name or f"nc-speed-{window.slug}-{side}-{len(book.intents)}"
    intent = book.reserve_intent(window.slug, side, kind, price, size, at, client)
    book.mark_submitted(client, f"order-{client}")
    book.record_fill(ActualFill(f"fill-{client}", f"order-{client}", client, window.slug, side, price, size,
                                round(size * (intent.unit_reserve - price), 6), at))
    return intent


# ---- fix 1: a strictly balancing buy is not new risk ------------------------------------------------------------

def test_a_strictly_balancing_bid_is_exempt_from_the_lifetime_and_day_stops():
    """2026-10-13, 3:30 PM PT: down 5 @ 0.40 filled with $1.4 of lifetime room; the up hedge was cut to 1 contract
    because its full cost counted as new risk, and the lock later paid 93.3c for the other 4."""
    book, window, at = book_with()
    book.realized_pnl = -8.6  # $1.40 of room under the $10 lifetime stop
    filled(book, window, "down", .4, 3, at)  # the first buy fits ($1.20 < $1.40) ...
    assert book.at_risk_usd == pytest.approx(1.2)
    assert book.can_buy(window.slug, "up", "rest", .56, 3, at + 1) == ""  # ... and so does its whole hedge
    hedge = book.reserve_intent(window.slug, "up", "rest", .56, 3, at + 1, "nc-speed-hedge")
    assert book.reserved_usd == pytest.approx(1.68)  # the bid holds cash ...
    assert book.at_risk_usd == pytest.approx(1.2)  # ... but adds nothing to the money at risk
    assert not book.risk_status(at + 1)["halted"]
    book.mark_submitted("nc-speed-hedge", "order-hedge")
    book.record_fill(ActualFill("fill-hedge", "order-hedge", "nc-speed-hedge", window.slug, "up", .56, 3, 0, at + 2))
    assert hedge.status == "filled" and book.at_risk_usd == 0  # three $1 pairs: nothing left to lose
    assert book.open_cost_usd == pytest.approx(2.88)
    # The day stop treats it the same way.
    book, window, at = book_with(1)
    book.day_pnl[utc_day(at)] = -4.7  # $1.30 of today's $6 left
    filled(book, window, "down", .43, 3, at)
    assert book.can_buy(window.slug, "up", "rest", .55, 3, at + 1) == ""
    assert book.can_buy(window.slug, "up", "rest", .55, 4, at + 1) == "day_stop"  # the fourth is new risk


def test_a_heavy_side_buy_or_contracts_beyond_the_unpaired_count_are_new_risk():
    wide = LiveLimits(window_usd=20, open_usd=40, day_loss_usd=12, total_loss_usd=10, clip=25, fee_precision=.0001)
    book, window, at = book_with(limits=wide)
    filled(book, window, "up", .4, 10, at)
    filled(book, window, "down", .5, 8, at + 1)  # balanced enough (2 of 18): eight $1 pairs cover the two extra ups
    assert book.at_risk_usd == 0
    assert book.balancing_contracts(window.slug, "down", 5, .5) == 2  # two of five complete pairs
    assert book.balancing_contracts(window.slug, "up", 1, .4) == 0  # the heavy side never balances
    assert book.balancing_contracts(window.slug, "down", 1, 1.0) == 0  # at $1 with fees nothing is gained
    book.realized_pnl = -8.7  # $1.30 of room under the lifetime stop
    assert book.can_buy(window.slug, "down", "rest", .5, 5, at + 2) == "total_budget"  # 3 x $0.50 of new risk
    assert book.can_buy(window.slug, "down", "rest", .5, 4, at + 2) == ""  # 2 x $0.50 < $1.30
    assert book.can_buy(window.slug, "up", "rest", .4, 4, at + 2) == "total_budget"  # heavy side: 4 x $0.40
    assert book.can_buy(window.slug, "up", "rest", .4, 3, at + 2) == ""  # $1.20 < $1.30 (and 5 of 21 is balanced)
    # A pending bid beyond the unpaired count counts for its extra contracts only.
    book.reserve_intent(window.slug, "down", "rest", .5, 4, at + 2, "nc-speed-four")
    assert book.at_risk_usd == pytest.approx(1.0)
    assert book.reserved_usd == pytest.approx(2.0)
    assert book.can_buy(window.slug, "up", "rest", .4, 1, at + 3) == "total_budget"  # $1.00 + $0.40 >= $1.30


def test_a_balancing_bid_still_needs_the_window_budget_the_open_budget_and_the_cash():
    book, window, at = book_with(limits=LiveLimits(window_usd=3, open_usd=3.5, day_loss_usd=6, total_loss_usd=10,
                                                     clip=5, fee_precision=.0001))
    filled(book, window, "up", .5, 5, at)  # $2.50 of the $3 window
    assert book.can_buy(window.slug, "down", "rest", .45, 5, at + 1) == "window_budget"  # $2.25 more
    assert book.can_buy(window.slug, "down", "rest", .45, 1, at + 1) == ""
    book.limits = LiveLimits(window_usd=10, open_usd=3.5, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)
    assert book.can_buy(window.slug, "down", "rest", .45, 5, at + 1) == "open_budget"  # 2.5 at risk + 2.25 > 3.5
    book.limits = FLOOR
    book.update_cash(2.0, at + 1)
    assert book.can_buy(window.slug, "down", "rest", .45, 5, at + 1) == "cash_budget"
    book.update_cash(100.0, at + 1)
    assert book.can_buy(window.slug, "down", "rest", .45, 5, at + 1) == ""


def worst_case_loss(book: LiveRiskBook) -> float:
    """Brute force: the largest loss the open windows can still show, over every combination of pending fills
    (each pending order fills in full at its reserved cost, or not at all) and the worse settlement outcome."""
    total = 0.0
    for slug, inventory in book.inventory.items():
        if slug in book.settled:
            continue
        pending = [item for item in book.intents.values() if item.window == slug and item.reserved > EPS]
        worst = 0.0
        for flags in itertools.product((False, True), repeat=len(pending)):
            shares = {"up": inventory.up.shares, "down": inventory.down.shares}
            paid = inventory.spent
            for include, intent in zip(flags, pending, strict=True):
                if include:
                    shares[intent.side] += intent.remaining
                    paid += intent.reserved
            worst = max(worst, paid - min(shares.values()))
        total += worst
    return total


class Books:
    """A random sequence of first buys, balancing and heavy-side bids, partial fills, cancels, locks, settlements,
    restarts and resume tokens on one risk book, checked against the stops by brute force at every step."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.book = LiveRiskBook(FLOOR)
        self.orders = 0
        self.counts: Counter[str] = Counter()
        self.segments: list[tuple[float, float]] = []  # (stop anchor, final P&L) of each resume segment
        self.day_resets: Counter[str] = Counter()  # the owner's day resets, by UTC day

    def check(self, now: float) -> None:
        book = self.book
        assert book.integrity_error is None
        worst = worst_case_loss(book)
        assert worst <= book.at_risk_usd + 1e-6, (worst, book.at_risk_usd)  # money at risk bounds the worst case
        loss = max(0.0, book.stop_anchor - book.realized_pnl)
        assert loss + worst <= FLOOR.total_loss_usd + 1e-6  # the lifetime stop is never exceeded ...
        assert book.day_loss(now) + worst <= FLOOR.day_loss_usd + 1e-6  # ... nor the day stop
        if book.halted:
            assert book.can_buy(self.window.slug, "up", "rest", .4, 1, now) == "total_loss"

    def restart(self, now: float) -> None:
        state = json.loads(json.dumps(self.book.to_state()))
        self.book = LiveRiskBook.from_state(state, FLOOR)
        self.counts["restart"] += 1

    def buy(self, now: float, *, lock: bool) -> None:
        book, window = self.book, self.window
        book.update_cash(self.rng.choice([3.0, 60.0, 1_000.0, 1_000.0, 1_000.0]), now)
        light, unpaired = book.lock_side(window.slug)
        if lock:
            if light is None or unpaired < 1:
                return
            side, size = light, float(self.rng.randint(1, int(unpaired) + 2))
            price = self.rng.choice([.5, .7, .9, .97, .98])
        elif light is not None and self.rng.random() < .6:
            # Mostly a hedge: the light side, exactly the unpaired count or near it, cheap enough for the pair cap.
            side = light
            size = float(int(unpaired) if self.rng.random() < .5 else self.rng.randint(1, int(unpaired) + 2))
            price = self.rng.choice([.05, .2, .3, .4, .45])
        else:
            side = self.rng.choice(["up", "down"])
            size = float(self.rng.randint(1, 5))
            price = self.rng.choice([.2, .35, .45, .5, .6, .75, .9])
        if size < 1:
            return
        kind = self.rng.choice(["take", "rest"])
        at_risk, day_loss = book.at_risk_usd, book.day_loss(now)
        total_loss = max(0.0, book.stop_anchor - book.realized_pnl)
        self.orders += 1
        try:
            intent = book.reserve_intent(window.slug, side, "take" if lock else kind, price, size, now,
                                         f"nc-speed-b{self.orders}", lock=lock)
        except LiveRejected as exc:
            self.counts["refused_" + exc.reason] += 1
            return
        cost = intent.size * intent.unit_reserve
        # Accepted only because a strictly balancing buy is exempt: the old rule would have refused it.
        if not lock and (day_loss + at_risk + cost >= FLOOR.day_loss_usd - EPS
                         or total_loss + at_risk + cost >= 10 - EPS):
            self.counts["exempt_only"] += 1
        self.counts["lock" if lock else "buy"] += 1

    def fill_or_cancel(self, now: float) -> None:
        active = [item for item in self.book.intents.values() if item.reservation_active]
        if not active:
            return
        intent = self.rng.choice(active)
        order_id = intent.order_id or f"venue-{intent.client_order_id}"
        self.book.mark_submitted(intent.client_order_id, order_id)
        if self.rng.random() < .65 and intent.remaining >= 1:
            size = float(self.rng.randint(1, int(intent.remaining)))
            fee = round(size * (intent.unit_reserve - intent.price) * self.rng.random(), 6)
            self.book.record_fill(ActualFill(f"f-{self.orders}-{len(self.book.fills)}", order_id,
                                             intent.client_order_id, intent.window, intent.side, intent.price, size,
                                             fee, now))
            self.counts["fill"] += 1
        else:
            self.close(intent, now)

    def close(self, intent: LiveIntent, now: float) -> None:
        order_id = intent.order_id or f"venue-{intent.client_order_id}"
        self.book.mark_submitted(intent.client_order_id, order_id)
        assert self.book.reconcile_order(OrderSnapshot(intent.client_order_id, order_id, "canceled",
                                                       intent.filled_size, 0, now), fills_complete=True)

    def run_window(self, index: int, good: bool) -> None:
        self.window = window = slot(index)
        self.book.add_window(window)
        for now in sorted(self.rng.uniform(window.start, window.end - 21) for _ in range(self.rng.randint(6, 24))):
            action = self.rng.random()
            if action < .45:
                self.buy(now, lock=now >= window.end - FLOOR.lock_s)
            elif action < .8:
                self.fill_or_cancel(now)
            elif action < .97:
                self.book.risk_status(now)
            else:
                self.restart(now)
            self.check(now)
        end = window.end
        for intent in [item for item in self.book.intents.values() if item.reservation_active]:
            self.close(intent, end)
        inventory = self.book.inventory[window.slug]
        heavy = inventory.up.shares >= inventory.down.shares
        self.book.settle(window.slug, heavy if self.rng.random() < (.85 if good else .2) else not heavy, end,
                         f"s-{window.slug}")
        self.book.update_cash(1_000.0, end)
        self.check(end)
        if self.book.halted and self.rng.random() < .5:  # the owner acknowledges the stop with a new value
            self.segments.append((self.book.stop_anchor, self.book.realized_pnl))
            assert self.book.resume(f"owner-{index}") == "applied"
            self.counts["resume"] += 1
        if self.book.day_latched(end) and self.rng.random() < .5:  # the owner's one-time fresh daily budget
            assert self.book.apply_day_reset(f"day-{index}", end) == "reset"
            self.day_resets[utc_day(end)] += 1
            self.counts["day_reset"] += 1


def test_random_books_never_let_the_worst_case_loss_pass_a_stop():
    """The brute-force property: whatever fills, cancels, locks and outcomes follow, the realized loss plus the worst
    the open windows can still lose never passes the day or lifetime stop, with balancing buys exempt."""
    totals: Counter[str] = Counter()
    for seed in range(24):
        run = Books(seed)
        good = True
        for index in range(120):
            if index % 12 == 0:
                good = run.rng.random() < .5
            run.run_window(index, good)
        book = run.book
        run.segments.append((book.stop_anchor, book.realized_pnl))
        for anchor, final in run.segments:
            assert anchor - final <= FLOOR.total_loss_usd + 1e-6  # each resume segment lost at most $10
        for day, pnl in book.day_pnl.items():  # no UTC day lost more than $6 per daily budget the owner granted
            assert -pnl <= FLOOR.day_loss_usd * (1 + run.day_resets[day]) + 1e-6, (seed, day, pnl)
        assert run.counts["buy"] and run.counts["fill"] and run.counts["restart"], (seed, run.counts)
        totals.update(run.counts)
    # The exemption was really exercised, and every stop (and the cash bound) was really reached.
    assert totals["exempt_only"] > 20 and totals["lock"] > 0 and totals["resume"] > 0 and totals["day_reset"] > 0, totals
    assert all(totals["refused_" + reason] for reason in ("day_stop", "total_budget", "total_loss", "cash_budget",
                                                          "pair_cap", "imbalance")), totals


# ---- fix 2: a first buy leaves room for its hedge ---------------------------------------------------------------

def test_a_first_buy_is_sized_so_that_its_hedge_still_fits_under_the_stops():
    """2026-10-13, 3:45 PM PT: down 3 @ 0.43 used the last $1.30 under the lifetime stop, so no hedge could follow.
    4:00 PM: up 2 @ 0.42 used the last $0.90. Each hedged contract costs about $1.01 (the other side at 0.99 less
    the price, with the taker fee)."""
    book, window, at = book_with()
    book.realized_pnl = -8.7  # $1.30 of room
    assert book.can_buy(window.slug, "down", "rest", .43, 3, at) == ""  # the buy alone fits ...
    assert book.starter_fit(window.slug, "down", "rest", .43, 5, at) == (1, "")  # ... one contract with its hedge
    assert book.hedge_unit(window.slug, .43, FLOOR) == pytest.approx(reserve_unit_cost(.56, .07, .0001))
    assert not book.halted
    book.realized_pnl = -9.1  # $0.90 of room: nothing fits with its hedge, and the lifetime stop latches
    assert book.starter_fit(window.slug, "up", "rest", .42, 5, at) == (0, "total_budget")
    assert book.halted and book.halt_reason == "total_loss"
    # The day stop the same way, and once the first buy exists the exemption of fix 1 takes over.
    book, window, at = book_with(1)
    book.day_pnl[utc_day(at)] = -3.0  # $3 of today's $6 left: two hedged contracts fit, three do not
    assert book.starter_fit(window.slug, "down", "rest", .5, 5, at) == (2, "")
    filled(book, window, "down", .5, 2, at)
    assert book.can_buy(window.slug, "up", "rest", .48, 2, at + 1) == ""
    book.day_pnl[utc_day(at)] = -5.1
    assert book.starter_fit(window.slug, "down", "rest", .5, 5, at + 2) == (0, "day_stop")
    assert book.day_latched(at + 2) and book.risk_status(at + 2)["day_stop_latched"]
    # A first buy at the pair cap has no hedge price at all.
    book, window, at = book_with(2)
    assert book.starter_fit(window.slug, "up", "rest", .99, 5, at) == (0, "pair_cap")


def test_the_desk_sends_no_one_sided_first_buy_near_a_stop(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, caps=CAPS)
    try:
        desk.book.realized_pnl = -8.7  # $1.30 of room: 3 contracts at 0.4 would fit, one with its hedge does
        asyncio.run(desk.step())
        assert [(c["side"], c["price"], c["size"]) for c in account.creates] == [("up", .4, 1.0)]
        assert not desk.book.halted
    finally:
        desk.close()
    desk, account, clock = make_desk(tmp_path / "none", caps=CAPS)
    try:
        desk.book.realized_pnl = -9.1  # $0.90 of room: not even one hedged contract
        asyncio.run(desk.step())
        assert not account.creates
        note = events(desk, "speeddesk_live_starter")
        assert note and note[0]["reason"] == "total_budget" and note[0]["window"] == TICKER
        assert desk.reason == "No first buy: one contract and its hedge would not fit under the lifetime loss stop"
        # Not even the smallest first buy fits: the lifetime stop has tripped and is latched, for good.
        panel = desk.panel()
        assert panel["total_halted"] and panel["mode"] == "paper"
        assert desk._risk_stop_reason().startswith("Total loss stop")
        latched = events(desk, "speeddesk_live_stop")
        assert latched and latched[0]["stop"] == "total" and latched[0]["total_pnl_usd"] == -9.1
        clock.advance(1)
        asyncio.run(desk.step())
        assert not account.creates and len(events(desk, "speeddesk_live_starter")) == 1  # noted once
    finally:
        desk.close()


# ---- fix 3: the stops latch -------------------------------------------------------------------------------------

def test_a_refused_one_contract_buy_latches_the_stop_and_a_trimmed_size_does_not():
    book, window, at = book_with()
    book.day_pnl[utc_day(at)] = -2.5
    assert book.can_buy(window.slug, "up", "take", .8, 5, at) == "day_stop"  # 5 x $0.81 does not fit ...
    assert not book.day_latched(at) and not book.halted  # ... the stop only trims, nothing latches
    book.day_pnl[utc_day(at)] = -5.7
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "day_stop"  # not even one contract
    assert book.day_latched(at) and book.risk_status(at)["day_stopped"] and book.risk_status(at)["day_stop_latched"]
    book.day_pnl[utc_day(at)] = 0.0  # even with the loss gone (a settlement that won), today stays stopped
    assert book.can_buy(window.slug, "up", "take", .4, 1, at + 1) == "day_stop"
    assert book.can_buy(window.slug, "up", "take", .4, 5, at + 1) == "day_stop"
    tomorrow = slot(96)  # the next UTC day starts fresh
    book.add_window(tomorrow)
    book.update_cash(1_000, tomorrow.start + 10)
    assert utc_day(tomorrow.start) != utc_day(at)
    assert not book.day_latched(tomorrow.start + 10)
    assert book.can_buy(tomorrow.slug, "up", "take", .4, 1, tomorrow.start + 10) == ""
    # The lifetime stop latches as `halted`: paper until a new resume value. (The $9.70 lost since the last resume
    # is modelled with the stop anchor, so the book still restores: realized results must match settlements.)
    book.stop_anchor = 9.7
    assert book.can_buy(tomorrow.slug, "up", "take", .4, 1, tomorrow.start + 11) == "total_budget"
    assert book.halted and book.halt_reason == "total_loss"
    assert book.can_buy(tomorrow.slug, "up", "take", .01, 1, tomorrow.start + 12) == "total_loss"  # no tiny bids
    assert book.can_lock(tomorrow.slug, "down", .8, 1, tomorrow.end - 100) != "total_loss"  # locks still run
    # Both latches survive a restart.
    again = LiveRiskBook.from_state(json.loads(json.dumps(book.to_state())), FLOOR)
    assert again.halted and again.day_stop_latched == utc_day(at)


def test_the_owners_day_reset_clears_a_latched_day_stop_once():
    book, window, at = book_with()
    book.day_pnl[utc_day(at)] = -5.7
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "day_stop" and book.day_latched(at)
    assert book.apply_day_reset("owner-day-reset", at + 1) == "reset"
    assert not book.day_latched(at + 1) and book.day_loss(at + 1) == 0
    assert book.can_buy(window.slug, "up", "take", .4, 1, at + 1) == ""
    book.day_pnl[utc_day(at)] = -11.5  # $5.80 lost since the reset: the fresh $6 is nearly used up again
    assert book.can_buy(window.slug, "up", "take", .4, 1, at + 2) == "day_stop" and book.day_latched(at + 2)
    assert book.apply_day_reset("owner-day-reset", at + 3) == "used"  # the same value never resets twice
    assert book.day_latched(at + 3)


def test_a_binding_stop_latches_at_start_with_no_room_for_a_hedged_contract():
    book, _, at = book_with()
    book.realized_pnl = -9.5  # $0.50 of room: less than the $0.98 floor of a one-contract hedged first buy
    assert book.latch_bound_stops(at) == ["total"] and book.halted
    book, _, at = book_with(1)
    book.day_pnl[utc_day(at)] = -5.2
    assert book.latch_bound_stops(at) == ["day"] and book.day_latched(at) and not book.halted
    assert book.latch_bound_stops(at) == []  # already latched: nothing more to note
    book, _, at = book_with(2)
    book.realized_pnl = -8.9  # $1.10 of room: one hedged contract still fits, so nothing latches
    assert book.latch_bound_stops(at) == [] and not book.halted and not book.day_latched(at)


def test_resume_values_are_kept_while_nothing_is_latched_and_spent_by_the_stop_that_follows():
    book, window, at = book_with()
    assert book.resume("") == ""
    assert book.resume("early") == "not_halted"  # nothing to clear: the value is kept, not spent
    assert book.resume("early") == "not_halted" and not book.seen_resume_hashes  # still kept
    assert not book.apply_resume_token("early")
    book.stop_anchor = 9.7  # $9.70 lost since the last resume (the anchor keeps the book restorable)
    assert book.can_buy(window.slug, "up", "take", .4, 1, at) == "total_budget" and book.halted
    # The stop spends every value seen before it: a value present before a stop never clears that stop.
    assert book.resume("early") == "used" and book.halted
    assert book.resume("after") == "applied" and not book.halted and book.stop_anchor == book.realized_pnl
    assert book.resume("after") == "used" and book.resume("early") == "used"
    assert book.can_buy(window.slug, "up", "take", .4, 5, at + 1) == ""  # a fresh $10 counts from -$9.70
    state = json.dumps(book.to_state())
    assert "early" not in state and "after" not in state  # fingerprints only
    # A value kept while not halted survives a restart unspent, and a reconciliation stop keeps it too.
    assert book.resume("later") == "not_halted"
    again = LiveRiskBook.from_state(json.loads(state), FLOOR)
    assert again.resume("later") == "not_halted"
    again.halted, again.integrity_error = True, "fill_changed"
    assert again.resume("later") == "integrity" and again.halted
    again.integrity_error = None
    assert again.resume("later") == "applied" and not again.halted


def test_the_desk_latches_at_start_before_the_token_and_logs_every_token_use(tmp_path: Path) -> None:
    desk, _, clock = make_desk(tmp_path, caps=CAPS)
    try:
        # 2026-10-13, 4:15 PM PT: $0.0579 of room, `total_halted` false. (The loss since the last resume is modelled
        # with the stop anchor: a saved book's realized result must match its settlements.)
        desk.book.stop_anchor = 9.9421
        desk.checkpoint(durable=True)
    finally:
        desk.close()
    # Without a token: latched at start, paper, no bids at all (a one-contract bid at 4c went out at 4:25 PM PT).
    again, account, clock = make_desk(tmp_path, caps=CAPS)
    try:
        assert again.book.halted and again.panel()["total_halted"] and again.panel()["mode"] == "paper"
        latched = events(again, "speeddesk_live_stop")
        assert [item["stop"] for item in latched] == ["total"] and "at start" in latched[0]["state"]
        assert again._risk_stop_reason() == "Total loss stop; no new bets until a new resume token"
        for _ in range(3):
            asyncio.run(again.step())
            clock.advance(.5)
        assert not account.creates and not events(again, "speeddesk_live_resume")
    finally:
        again.close()
    # A token set now is applied to the latched stop, once, and the receipt never carries the value.
    token = {"speeddesk_kalshi_resume_token": Secret("owner-resume-after-the-stop")}
    resumed, account, clock = make_desk(tmp_path, caps=CAPS, extra=token)
    try:
        receipt = events(resumed, "speeddesk_live_resume")
        assert [item["state"][:7] for item in receipt] == ["applied"]
        assert receipt[0]["counted_from_usd"] == resumed.book.realized_pnl and receipt[0]["total_halted"] is False
        assert resumed.book.stop_anchor == resumed.book.realized_pnl  # a fresh $10 counts from the result now
        assert not resumed.book.halted
        assert "owner-resume-after-the-stop" not in json.dumps(resumed.latest_events)
        assert "owner-resume-after-the-stop" not in json.dumps(resumed.book.to_state())
        asyncio.run(resumed.step())
        assert account.creates and resumed.panel()["mode"] == "live"  # real orders again, within the caps
        resumed.checkpoint(durable=True)
    finally:
        resumed.close()
    used, _, _ = make_desk(tmp_path, caps=CAPS, extra=token)
    try:
        assert events(used, "speeddesk_live_resume")[-1]["state"] == "ignored; this value was already used"
    finally:
        used.close()
    # A token set while nothing is latched is logged as ignored and kept, not spent.
    fresh, _, _ = make_desk(tmp_path / "fresh", caps=CAPS, extra={"speeddesk_kalshi_resume_token": Secret("too-early")})
    try:
        state = events(fresh, "speeddesk_live_resume")[-1]["state"]
        assert state.startswith("ignored; no total loss stop is latched")
        assert not fresh.book.seen_resume_hashes and len(fresh.book.resume_pending) == 1
    finally:
        fresh.close()


def test_a_stop_that_latches_while_trading_cancels_the_resting_bids_and_shows_in_the_status(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, caps=CAPS)
    try:
        asyncio.run(desk.step())
        assert [c["size"] for c in account.creates] == [5.0]  # a bid rests ($2.08 reserved)
        desk.book.realized_pnl = -7.5  # $0.42 of room left beyond the bid (as if earlier windows had just settled)
        assert not desk.book.risk_status(clock.now())["halted"]
        clock.advance(.5)
        asyncio.run(desk.step())  # the other side's first buy: not even one hedged contract fits: latched
        assert desk.book.halted
        assert events(desk, "speeddesk_live_stop")[-1]["stop"] == "total"
        clock.advance(.5)
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"] and len(account.creates) == 1
        panel = desk.panel()
        assert panel["mode"] == "paper" and panel["total_halted"] and not panel["real_orders_available"]
        assert panel["reason"] == "Total loss stop; no new bets until a new resume token"
        assert "stops" in panel["ladder"]["promotion"]["blocked"]  # the ladder's stop note is kept
        assert desk.ladder.state.last_stop_at is not None
    finally:
        desk.close()


def test_a_latched_day_stop_shows_in_the_status_and_lapses_with_the_utc_day(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, caps=CAPS)
    try:
        desk.book.day_pnl[utc_day(clock.now())] = -5.2  # $0.80 of today's $6 left
        asyncio.run(desk.step())
        assert not account.creates and desk.book.day_latched(clock.now())
        assert desk.reason == "No first buy: one contract and its hedge would not fit under the daily loss stop"
        clock.advance(.5)
        asyncio.run(desk.step())
        panel = desk.panel()
        assert panel["day_stop_latched"] and panel["mode"] == "paper"
        assert panel["reason"] == "Daily loss stop; no new buys until 00:00 UTC"
        assert events(desk, "speeddesk_live_stop")[-1]["stop"] == "day"
        assert set(STOP_REFUSALS) == {"day_stop", "total_budget"}
    finally:
        desk.close()


# ---- fix 4: the owner's day reset reaches the practice twin -----------------------------------------------------

def test_the_practice_twin_takes_the_owners_day_reset():
    twin = PracticeDesk(SpeedConfig(day_stop_usd=6.0, window_usd=10, open_usd=20))
    window = slot(0)
    twin.add_window(window)
    at = window.start + 10
    twin.days[utc_day(at)] = {"pnl_usd": -6.8833}  # 2026-10-13: the twin's last loss at 6:45 AM PT
    assert twin.blocked(window, at) == "day_stop" and twin.day_loss(at) == pytest.approx(6.8833)
    twin.apply_day_reset(at)
    assert twin.day_loss(at) == 0 and twin.blocked(window, at) != "day_stop"
    assert twin.day_anchor == {utc_day(at): pytest.approx(-6.8833)}
    restored = PracticeDesk.from_state(json.loads(json.dumps(twin.to_state())), twin.config)
    assert restored.day_loss(at) == 0 and restored.blocked(window, at) != "day_stop"
    restored.days[utc_day(at)]["pnl_usd"] = -12.9  # another $6 lost since the reset
    assert restored.blocked(window, at + 1) == "day_stop"
    tomorrow = slot(96)
    restored.add_window(tomorrow)
    assert restored.blocked(tomorrow, tomorrow.start + 10) != "day_stop"  # the next day starts from zero
    assert "day_anchor" not in PracticeDesk(SpeedConfig()).to_state()  # unchanged saved state until a reset


def test_the_owners_day_reset_reaches_the_practice_twin_at_startup(tmp_path: Path) -> None:
    desk, _, clock = make_desk(tmp_path, caps=CAPS)
    try:
        desk.twin.days[utc_day(clock.now())] = {"pnl_usd": -6.8833}  # the twin's day on 2026-10-13 from 6:45 AM PT
        desk.book.day_anchor = {utc_day(clock.now()): 5.9928}  # the real book's day stop used up, as that morning
        desk.checkpoint(durable=True)
    finally:
        desk.close()
    stopped, _, clock = make_desk(tmp_path, caps=CAPS)
    try:
        window = stopped.book.windows[TICKER]
        assert stopped.twin.blocked(window, clock.now()) == "day_stop" and stopped.book.day_latched(clock.now())
        stopped.checkpoint(durable=True)
    finally:
        stopped.close()
    again, _, clock = make_desk(tmp_path, caps=CAPS, extra={"speeddesk_kalshi_day_reset_token": Secret("owner-day-1")})
    try:
        window = again.book.windows[TICKER]
        assert again.twin.day_loss(clock.now()) == 0 and again.twin.blocked(window, clock.now()) != "day_stop"
        assert again.book.day_loss(clock.now()) == 0 and not again.book.day_latched(clock.now())
        receipt = events(again, "speeddesk_live_day_reset")[-1]
        assert receipt["practice_twin_counted_from_usd"] == pytest.approx(-6.8833)
    finally:
        again.close()


def test_fixtures_only_use_the_fake_account(tmp_path: Path) -> None:
    desk: KalshiLiveDesk
    desk, account, _ = make_desk(tmp_path, caps=CAPS)
    try:
        assert desk.client_factory() is account
    finally:
        desk.close()

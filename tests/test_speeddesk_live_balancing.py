"""Loss plan bug 1: the stops count what an order adds to its window's worst case, so balancing bids that only
shrink a loss are neither cut down nor cancelled by a money stop."""

from __future__ import annotations

import asyncio
import itertools
import random
from pathlib import Path

import pytest
from test_speeddesk_live import TICKER, FakeAccount, make_desk, steps

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_live import KalshiLiveDesk, LiveSnapshot
from nightcrawler.speeddesk_live_model import (
    ActualFill,
    LiveIntent,
    LiveLimits,
    LiveRiskBook,
)
from nightcrawler.speeddesk_model import Book, Level, Window, utc_day

WINDOW = "KXBTC15M-TEST-A"
OWNERS_CAPS = LiveLimits(window_usd=10, open_usd=20, day_loss_usd=6, total_loss_usd=10, clip=5, fee_precision=.0001)


def book_after_first_buy(day_loss: float = 2.0) -> LiveRiskBook:
    """A 5-contract first buy of Down at $0.42 has filled, after a $2 loss earlier the same day."""
    book = LiveRiskBook(OWNERS_CAPS)
    book.add_window(Window(WINDOW, 1000, 1900, 100, taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.day_pnl[utc_day(1010)] = -day_loss
    book.realized_pnl = -day_loss
    book.update_cash(100, 1010)
    first = book.reserve_intent(WINDOW, "down", "rest", .42, 5, 1010, "nc-speed-first", .45)
    assert book.record_fill(ActualFill("first-fill", "venue-first", first.client_order_id, WINDOW, "down",
                                       .42, 5, 0.0, 1011))
    return book


def test_a_balancing_bid_after_a_two_dollar_day_loss_keeps_all_five_contracts() -> None:
    """The loss plan's test: 5 at $0.42 after a $2 day loss, $6 day stop: a 5-contract balancing bid up to $0.57."""
    book = book_after_first_buy()
    assert book.risk_status(1012)["day_at_risk_usd"] == pytest.approx(2 + 2.10)
    assert book.can_buy(WINDOW, "up", "rest", .57, 5, 1012) == ""
    # The old arithmetic added the bid's full $2.85: 2 + 2.10 + 2.85 = 6.95 >= 6, so only 3 contracts fit.
    assert 2 + 2.10 + 5 * .57 >= OWNERS_CAPS.day_loss_usd
    assert book.can_buy(WINDOW, "up", "rest", .58, 5, 1012) == "pair_cap"  # still never above the $0.99 pair cap
    book.reserve_intent(WINDOW, "up", "rest", .57, 5, 1012, "nc-speed-balance", .6)
    status = book.risk_status(1012)
    assert status["at_risk_usd"] == pytest.approx(2.10)  # the bid filling would only shrink the loss
    assert not status["day_stopped"] and not status["halted"]
    assert book.lowers_risk("nc-speed-balance") and not book.lowers_risk("nc-speed-first")


def test_a_first_buy_still_counts_in_full_and_the_stops_hold() -> None:
    book = LiveRiskBook(OWNERS_CAPS)
    book.add_window(Window(WINDOW, 1000, 1900, 100, taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.day_pnl[utc_day(1010)] = -4.0
    book.update_cash(100, 1010)
    assert book.can_buy(WINDOW, "down", "rest", .42, 5, 1010) == "day_stop"  # 4 + 2.10 >= 6
    assert book.can_buy(WINDOW, "down", "rest", .42, 4, 1010) == ""  # 4 + 1.68 < 6
    intent = book.reserve_intent(WINDOW, "down", "rest", .42, 4, 1010, "nc-speed-starter", .45)
    assert book.at_risk_usd == pytest.approx(intent.reserved) and not book.lowers_risk("nc-speed-starter")


def brute_worst(book: LiveRiskBook, window: str, grid: int = 4) -> float:
    """Worst loss over a grid of partial fills of every pending order (fills at the reserved per-contract cost)."""
    inventory = book.inventory[window]
    pending = [intent for intent in book.intents.values() if intent.window == window and intent.reserved > 1e-9]
    worst = 0.0
    for fractions in itertools.product([step / grid for step in range(grid + 1)], repeat=len(pending)):
        shares = {"up": inventory.up.shares, "down": inventory.down.shares}
        paid = inventory.spent
        for fraction, intent in zip(fractions, pending, strict=True):
            shares[intent.side] += fraction * intent.remaining
            paid += fraction * intent.reserved
        worst = max(worst, paid - min(shares.values()))
    return worst


@pytest.mark.parametrize("seed", range(40))
def test_money_at_risk_bounds_the_true_worst_case_and_no_order_crosses_a_stop(seed: int) -> None:
    rng = random.Random(seed)
    book = LiveRiskBook(OWNERS_CAPS)
    day = utc_day(1010)
    book.day_pnl[day] = book.realized_pnl = -round(rng.uniform(0, 5), 2)
    windows = [f"KXBTC15M-PROP-{index}" for index in range(2)]
    for slug in windows:
        book.add_window(Window(slug, 1000, 1900, 100, taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.update_cash(100, 1010)
    names = itertools.count()
    for _ in range(12):
        slug, side = rng.choice(windows), rng.choice(("up", "down"))
        kind = rng.choice(("take", "rest"))
        price, size = round(rng.uniform(.05, .9), 2), rng.randint(1, 5)
        old_rule = book.open_loss_usd + sum(intent.reserved for intent in book.intents.values() if not intent.lock)
        before = book.at_risk_usd
        assert before <= old_rule + 1e-9  # the worst case never exceeds the old sum of every reservation
        if book.can_buy(slug, side, kind, price, size, 1010) == "":
            intent = book.reserve_intent(slug, side, kind, price, size, 1010, f"nc-speed-{next(names)}", .5)
            status = book.risk_status(1010)
            assert status["day_at_risk_usd"] < OWNERS_CAPS.day_loss_usd and status["at_risk_usd"] <= 20 + 1e-9
            assert not status["halted"]
            if rng.random() < .7:  # it fills, wholly or partly, at its limit price
                filled = rng.choice((intent.size, max(1, intent.size // 2)))
                fee = intent.unit_reserve * filled - intent.price * filled
                book.record_fill(ActualFill(f"fill-{intent.client_order_id}", f"venue-{intent.client_order_id}",
                                            intent.client_order_id, slug, side, intent.price, filled,
                                            round(fee, 6), 1010))
        for slug in windows:
            assert brute_worst(book, slug) <= book.worst_loss(slug) + 1e-9
        assert sum(book.worst_loss(slug) for slug in windows) <= book.at_risk_usd + 1e-9
        assert book.day_loss(1010) + book.at_risk_usd < OWNERS_CAPS.day_loss_usd + 1e-9


def balancing_desk(tmp_path: Path) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    """The live loop after a 5-contract first buy, then another window settles at a $2 loss."""
    caps = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0,
            "speeddesk_kalshi_day_stop_usd": 6.0, "speeddesk_kalshi_total_stop_usd": 10.0}
    # The pull off: the Bitcoin jumps below (80000 to 80288 to 80640) are 5c moves, which the pull would hold.
    desk, account, clock = make_desk(tmp_path, caps=caps, extra={"speeddesk_take_edge": 1.0,
                                                                 "speeddesk_kalshi_pull": False})
    window = desk.book.windows[TICKER]
    def view(bitcoin: float, up_ask: float) -> None:
        def snapshot() -> LiveSnapshot:
            books = {(TICKER, side): Book(TICKER, side, (Level(.3, 2),), (Level(up_ask if side == "up" else .6, 10),),
                                          clock.now(), "book", source="rest", requested_at=clock.now())
                     for side in ("up", "down")}
            return LiveSnapshot((window,), books, bitcoin, clock.now(), .001, frozenset({TICKER}))
        desk.snapshot = snapshot  # type: ignore[method-assign]

    view(80288, .4)  # Down fair 0.452: the first buy rests at 0.42 (an Up bid at 0.51 would cross the 0.40 ask)
    asyncio.run(desk.step())
    assert [(c["side"], c["price"], c["size"]) for c in account.creates] == [("down", .42, 5)]
    order = account.orders[0]
    order.update(status="executed", fill_count_fp="5.00", remaining_count_fp="0.00")
    account.executions.append({"fill_id": "first-fill", "order_id": order["order_id"], "ticker": TICKER,
                               "outcome_side": "no", "book_side": "ask", "count_fp": "5.00",
                               "no_price_dollars": ".42", "fee_cost": "0.0000", "ts": clock.now()})
    account.account_positions = [{"ticker": TICKER, "position_fp": "-5.00"}]
    steps(desk, clock, 2)  # the fill is booked
    assert desk.book.inventory[TICKER].down.shares == 5 and not account.cancels
    # The first buy's hedge budget had to fit when sent. A later loss must not shrink the owed hedge.
    desk.book.day_pnl[utc_day(clock.now())] = desk.book.realized_pnl = -2.0
    view(80640, .62)  # Bitcoin rises: Up fair 0.605, so the balancing bid is 0.57
    steps(desk, clock, 3)
    return desk, account, clock


def test_the_live_loop_sends_the_whole_balancing_bid_and_a_money_stop_leaves_it_resting(tmp_path: Path) -> None:
    desk, account, clock = balancing_desk(tmp_path)
    try:
        assert [(c["side"], c["price"], c["size"]) for c in account.creates] == [("down", .42, 5), ("up", .57, 5)]
        balance = next(intent for intent in desk.intents.values() if intent.side == "up")
        assert desk.book.lowers_risk(balance.client_order_id) and desk.panel()["mode"] == "live"
        desk.book.day_pnl[utc_day(clock.now())] = -5.0  # another window settles at a loss: the day stop trips
        assert desk.book.risk_status(clock.now())["day_stopped"]
        steps(desk, clock, 2)
        assert not account.cancels  # the bid can only shrink this window's loss
        assert len(account.creates) == 2  # and no new order goes out during the stop
    finally:
        desk.close()


def test_a_money_stop_keeps_no_pair_of_bids_that_together_add_risk() -> None:
    """Caps review minor: with 5 Up and 5 Down held at $0.49, resting bids of 3 Up and 3 Down at $0.50 each passed
    the per-order test (the other kept the worst case where it was) though together they add $1.40. Neither is on
    a light side, so a money stop cancels both; a lone balancing bid on the light side still rests."""
    book = LiveRiskBook(OWNERS_CAPS)
    book.add_window(Window(WINDOW, 1000, 1900, 100, taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.update_cash(100, 1010)
    for side in ("up", "down"):
        intent = book.reserve_intent(WINDOW, side, "rest", .49, 5, 1010, f"nc-speed-{side}-pair", .5)
        book.mark_submitted(intent.client_order_id, f"venue-{side}-pair")
        book.record_fill(ActualFill(f"fill-{side}-pair", f"venue-{side}-pair", intent.client_order_id, WINDOW, side,
                                    .49, 5, 0.0, 1011))
    # Existing pre-protection orders remain liabilities. New ordinary admission now forbids these bids;
    # seed their legacy reservations explicitly to retain this independent stop-accounting regression.
    up = LiveIntent("nc-speed-up-more", WINDOW, "up", "rest", .50, 3, 1012, .50, .52)
    down = LiveIntent("nc-speed-down-more", WINDOW, "down", "rest", .50, 3, 1012, .50, .52)
    book.intents[up.client_order_id], book.intents[down.client_order_id] = up, down
    assert book.worst_loss(WINDOW) == pytest.approx(book.worst_loss(WINDOW, without=up.client_order_id))
    assert book.worst_loss(WINDOW) - book._worst(book.inventory[WINDOW], []) == pytest.approx(1.40)
    assert not book.lowers_risk(up.client_order_id) and not book.lowers_risk(down.client_order_id)
    # A light side again: 5 Up more filled, so a Down bid completes pairs and is kept; the Up one is not.
    book.mark_submitted(up.client_order_id, "venue-up-more")
    book.record_fill(ActualFill("fill-up-more", "venue-up-more", up.client_order_id, WINDOW, "up", .50, 3, 0.0,
                                1013))
    assert book.lowers_risk(down.client_order_id)

"""HISTORICAL ENTRY MECHANISM ONLY; no current entry authority or profitability claim.

Loss plan bug 2: a stale-priced resting bid is cancelled even while Kalshi account data are stale."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import TICKER, FakeAccount, steps

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_live import KalshiLiveDesk, LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, fair_up


def market(desk: KalshiLiveDesk, clock: FakeClock, bitcoin: float) -> None:
    """Fresh books and a fresh Bitcoin print at ``bitcoin`` on every read of the snapshot."""
    window = desk.book.windows[TICKER]

    def view() -> LiveSnapshot:
        books = {(TICKER, side): Book(TICKER, side, (Level(.3, 2),), (Level(.4 if side == "up" else .6, 10),),
                                      clock.now(), "book", source="rest", requested_at=clock.now())
                 for side in ("up", "down")}
        return LiveSnapshot((window,), books, bitcoin, clock.now(), .001, frozenset({TICKER}))

    desk.snapshot = view  # type: ignore[method-assign]


def resting_bid_with_stale_account(tmp_path: Path) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_take_edge": 1.0})  # makers only, as live
    market(desk, clock, 80000)
    asyncio.run(desk.step())
    assert [(c["side"], c["kind"], c["price"]) for c in account.creates] == [("down", "rest", .47)]
    account.account_positions = [{"ticker": TICKER, "position_fp": "3.00"}]  # unexplained: account data stay stale
    steps(desk, clock, 2)
    assert desk.account_at is None and desk.panel()["waiting"] == "Kalshi account data stale"
    return desk, account, clock


def test_a_bid_priced_from_an_old_fair_is_cancelled_while_account_data_are_stale(tmp_path: Path) -> None:
    desk, account, clock = resting_bid_with_stale_account(tmp_path)
    try:
        assert not account.cancels
        market(desk, clock, 80120)  # Bitcoin up: Down's fair falls from 0.50 to about 0.48
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
        cancel = [event for event in desk.latest_events if event["event"] == "speeddesk_live_cancel"][-1]
        assert cancel["reason"] == "reprice"
        assert len(account.creates) == 1  # no new bid until the account is reconciled again
    finally:
        desk.close()


def test_a_small_fair_move_leaves_the_bid_resting(tmp_path: Path) -> None:
    desk, account, clock = resting_bid_with_stale_account(tmp_path)
    try:
        market(desk, clock, 80010)  # Down's fair moves about 0.2c
        steps(desk, clock, 3)
        assert not account.cancels
    finally:
        desk.close()


def test_a_bid_above_fresh_fair_minus_two_cents_is_cancelled(tmp_path: Path) -> None:
    desk, account, _ = resting_bid_with_stale_account(tmp_path)
    try:
        intent = next(iter(desk.intents.values()))
        intent.fair = .495  # within a cent of fresh fair (0.50), but the 0.47 bid is no longer 2c under it
        desk.book.intents[intent.client_order_id].fair = .495
        intent.price = desk.book.intents[intent.client_order_id].price = .485
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
        assert [event["reason"] for event in desk.latest_events
                if event["event"] == "speeddesk_live_cancel"][-1] == "bid_above_fair"
    finally:
        desk.close()


def test_real_bids_are_priced_from_the_settlement_averages_horizon(tmp_path: Path) -> None:
    """Loss plan item 4: the live desk's fair uses Kalshi's 60-second settlement average, like its practice twin."""
    # The pull off: the jump from make_historical_desk's 80000 to 80288 is a 5c move, which the pull would hold for 10 s.
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_take_edge": 1.0, "speeddesk_kalshi_pull": False})
    try:
        market(desk, clock, 80288)
        asyncio.run(desk.step())
        intent = next(iter(desk.intents.values()))
        window = desk.book.windows[TICKER]
        up = fair_up(80288, 80000, .001, window.end - intent.at, settles_on_average=True)
        assert up is not None and intent.side == "down" and intent.fair == pytest.approx(1 - up)
        assert intent.fair != pytest.approx(1 - (fair_up(80288, 80000, .001, window.end - intent.at) or 0), abs=1e-6)
        assert account.creates[0]["price"] == .42
    finally:
        desk.close()


@pytest.mark.parametrize("bitcoin", [80120, 79880])
def test_the_rule_matches_the_reprice_when_account_data_are_fresh(tmp_path: Path, bitcoin: float) -> None:
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_take_edge": 1.0})
    try:
        market(desk, clock, 80000)
        asyncio.run(desk.step())
        steps(desk, clock, 2)
        assert desk.account_at is not None and not account.cancels
        market(desk, clock, bitcoin)
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
    finally:
        desk.close()


def test_an_acknowledged_cancel_is_not_resent_while_the_order_list_lags(tmp_path: Path) -> None:
    """Review of part 1: once Kalshi accepted the cancel, a lagging order list must not cause a re-cancel (a 404)
    every 2 s, nor a full account read on every step."""
    desk, account, clock = resting_bid_with_stale_account(tmp_path)
    try:
        def lagging_cancel(order_id: str, *, ticker: str) -> dict[str, object]:
            account.cancels.append(order_id)  # accepted, but the order list keeps showing it resting
            return {}

        account.cancel = lagging_cancel  # type: ignore[method-assign]
        market(desk, clock, 80120)
        steps(desk, clock, 12)  # 3.6 s: past the 2 s cancel retry
        assert account.cancels == ["order-1"]
    finally:
        desk.close()


def test_a_small_make_edge_never_cancels_a_fresh_bid_on_sight(tmp_path: Path) -> None:
    """Review of part 1: with SPEEDDESK_MAKE_EDGE below the stale-bid edge, a new bid already sits above fresh fair
    minus 2c; the rule uses the smaller edge so a flat market leaves one bid resting instead of churning."""
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_take_edge": 1.0, "speeddesk_make_edge": 0.01})
    try:
        market(desk, clock, 80000)
        steps(desk, clock, 10)
        assert len(account.creates) == 1 and not account.cancels
    finally:
        desk.close()

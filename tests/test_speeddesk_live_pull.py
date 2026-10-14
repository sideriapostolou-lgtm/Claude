"""The bid pull (owner, 2026-10-13 ~20:15 UTC: "Pulling bids the instant price moves ... test with our current bot"),
on real money, with the practice twin keeping the rule without it as the live control. Offline: no account."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import math
import random
from dataclasses import replace
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pytest
from test_speeddesk_live import TICKER, FakeAccount, fill_order, make_desk, reopen

from nightcrawler import pagestate, speeddesk_live
from nightcrawler.clock import FakeClock
from nightcrawler.config import ConfigError, Settings
from nightcrawler.speeddesk_kalshi_client import WRITES_PER_S, KalshiClientError
from nightcrawler.speeddesk_live import (
    PULL_REASON,
    WRITE_ROOM_REASON,
    KalshiLiveDesk,
    LiveSnapshot,
)
from nightcrawler.speeddesk_live_model import LiveSettlement
from nightcrawler.speeddesk_live_pull import PullGuard, PullRule, compare
from nightcrawler.speeddesk_model import (
    AVERAGE_LEAD_S,
    Book,
    Level,
    Settlement,
    Trade,
    Window,
    fair_up,
    utc_day,
)

# The owner's current $10 / $20 caps (both stops at their defaults), and makers only, as live.
CAPS = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0}
MAKERS = {"speeddesk_take_edge": 1.0}
SIGMA = .001


def horizon(seconds_left: float) -> float:
    """The horizon the bot's fair uses (KalshiLiveDesk._fair, fair_up with settles_on_average): Kalshi settles on
    the 60 s average, which moves like the index AVERAGE_LEAD_S before the close."""
    return seconds_left - AVERAGE_LEAD_S if seconds_left >= 60 else seconds_left


def market(desk: KalshiLiveDesk, clock: FakeClock, up: float, *, ask: float = .55, feed: bool = True) -> None:
    """Fresh books (asks above both bids) and a Bitcoin print that puts the Up fair at ``up`` right now; ``feed``
    also hands the books to the desk, as the feeds do."""
    window = desk.book.windows[TICKER]
    bitcoin = 80000 * math.exp(NormalDist().inv_cdf(up) * SIGMA * math.sqrt(horizon(window.end - clock.now())))

    def view() -> LiveSnapshot:
        books = {(TICKER, side): Book(TICKER, side, (Level(.3, 2),), (Level(ask, 10),), clock.now(), "book",
                                      source="rest", requested_at=clock.now()) for side in ("up", "down")}
        return LiveSnapshot((window,), books, bitcoin, clock.now(), SIGMA, frozenset({TICKER}))

    desk.snapshot = view  # type: ignore[method-assign]
    for book in view().books.values() if feed else ():  # the twin sees the same books
        desk.on_book(book)


def run(desk: KalshiLiveDesk, clock: FakeClock, seconds: float, *, every: float = .3) -> None:
    """The live loop: fresh books and a Bitcoin tick, then a step, every ``every`` seconds."""
    end = clock.now() + seconds
    while clock.now() < end - 1e-9:
        for book in desk.snapshot().books.values():
            desk.on_book(book)
        desk.on_tick(80000, clock.now(), clock.now())
        asyncio.run(desk.step())
        clock.advance(every)


def bids(account: FakeAccount) -> list[tuple[str, float]]:
    """(side, price) of every bid resting on the fake account."""
    return [(create["side"], create["price"])
            for order, create in zip(account.orders, account.creates, strict=True) if order["status"] == "resting"]


def maker_fill(desk: KalshiLiveDesk, account: FakeAccount, clock: FakeClock, index: int, side: str) -> None:
    """Bid ``index`` (5 at 0.47) fills as a maker on Kalshi (no fee at the zero maker coefficient), and a matching sell
    prints, so the practice twin's copy of the bid fills too."""
    clock.advance(.3)  # past the twin's 250 ms practice latency
    fill_order(account, clock, index, side=side, price=.47, size=5)
    account.executions[-1]["fee_cost"] = "0.0000"
    desk.on_trade(Trade(TICKER, side, .47, 5, clock.now(), f"print-{index}", "sell", clock.now()))  # type: ignore[arg-type]


def starter_bid_filled(desk: KalshiLiveDesk, account: FakeAccount, clock: FakeClock) -> None:
    """The first bid, Up 5 at 0.47, fills."""
    market(desk, clock, .5)
    asyncio.run(desk.step())
    assert [(c["side"], c["kind"], c["price"], c["size"]) for c in account.creates] == [("up", "rest", .47, 5)]
    maker_fill(desk, account, clock, 0, "up")
    account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]


def two_bids(tmp_path: Path, **extra: Any) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    """5 Up and 5 Down bought at 0.47 (a pair), then an Up and a Down bid of 3 at 0.47 resting (the most the 25%
    imbalance cap allows), at an Up fair of 0.50; the practice twin holds the same."""
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra={**MAKERS, **extra})
    starter_bid_filled(desk, account, clock)
    run(desk, clock, .6)
    assert [(c["side"], c["price"], c["size"]) for c in account.creates[1:]] == [("down", .47, 5)]
    maker_fill(desk, account, clock, 1, "down")
    account.account_positions = []
    run(desk, clock, 1.5)
    assert sorted(bids(account)) == [("down", .47), ("up", .47)]
    assert [c["size"] for c in account.creates[2:]] == [3, 3]
    assert not account.cancels
    assert sorted((order.side, order.price, order.size) for order in desk.twin.orders.values()) == [
        ("down", .47, 3), ("up", .47, 3)]
    return desk, account, clock


def swing(desk: KalshiLiveDesk, clock: FakeClock, half: float) -> None:
    """The Up fair dips ``half`` below 0.50, then rises ``half`` above it: a move of 2 x ``half`` within 0.3 s, yet each
    bid's own fair (0.50) is only ``half`` away, so the 1c reprice rule alone would leave both bids resting."""
    market(desk, clock, .5 - half)
    run(desk, clock, .3)
    market(desk, clock, .5 + half)
    run(desk, clock, .3)


def pull_lines(desk: KalshiLiveDesk) -> list[dict[str, Any]]:
    desk.checkpoint()
    return [receipt.payload for receipt in desk.ledger.iter_receipts() if receipt.kind == "speeddesk_live_pull"]


def test_a_one_cent_move_within_five_seconds_pulls_both_bids_and_holds_new_ones(tmp_path: Path) -> None:
    desk, account, clock = two_bids(tmp_path)
    try:
        swing(desk, clock, .0053)  # 1.06c within 0.3 s
        assert account.cancels == ["order-4", "order-3"]  # the Up fair ended higher: the Down bid (order-4) first
        pulled = [event for event in desk.latest_events if event["event"] == "speeddesk_live_cancel"]
        assert [event["reason"] for event in pulled] == ["pull", "pull"]
        assert desk.pull.held(TICKER, clock.now())
        # The dip stays inside the 5 s lookback for 5 s (the last trigger 4.8 s after it, on the 0.3 s steps), then
        # the hold runs 5 s more: no new bid until 9.8 s after the dip.
        dipped_at = clock.now() - .6
        run(desk, clock, dipped_at + 9.5 - clock.now())
        assert len(account.creates) == 4 and desk.reason == PULL_REASON
        assert desk.pull.last_trigger[TICKER] == pytest.approx(dipped_at + 4.8)
        assert desk.panel()["pull"]["held"] == {TICKER: pytest.approx(dipped_at + 9.8, abs=1e-3)}
        run(desk, clock, 1.5)
        assert not desk.pull.held(TICKER, clock.now())
        assert sorted(bids(account)) == [("down", .46), ("up", .47)]  # priced from the new fair, 0.5053
        panel = desk.panel()["pull"]
        assert panel["pulls_today"] == 1 and panel["bids_pulled_today"] == 2
        [line] = pull_lines(desk)
        assert line["window"] == TICKER and line["bids_pulled"] == 2 and line["move"] == pytest.approx(.0106, abs=1e-4)
        assert line["held_until"] == pytest.approx(dipped_at + 9.8, abs=1e-3)
        assert line["started_at"] == pytest.approx(dipped_at + .3, abs=1e-3)
    finally:
        desk.close()


@pytest.mark.parametrize("move", ["swing", "rise"])
def test_an_eight_tenths_of_a_cent_move_does_not_pull(tmp_path: Path, move: str) -> None:
    desk, account, clock = two_bids(tmp_path)
    try:
        if move == "swing":
            swing(desk, clock, .004)
        else:
            market(desk, clock, .508)
            run(desk, clock, .6)
        run(desk, clock, 3)
        assert not account.cancels and not desk.pull.held(TICKER, clock.now())
        assert sorted(bids(account)) == [("down", .47), ("up", .47)]
        assert desk.panel()["pull"]["pulls_today"] == 0 and not pull_lines(desk)
    finally:
        desk.close()


def test_a_fast_move_past_the_reprice_rule_still_holds_the_new_bids(tmp_path: Path) -> None:
    """A 1.5c rise cancels both bids under the old rule (reprice; the twin follows that), and the pull's hold then
    keeps the bot from bidding again for the hold, where the old rule would have rebid at once."""
    desk, account, clock = two_bids(tmp_path)
    try:
        market(desk, clock, .515)
        run(desk, clock, .3)
        assert account.cancels == ["order-4", "order-3"]
        assert [event["reason"] for event in desk.latest_events
                if event["event"] == "speeddesk_live_cancel"] == ["reprice", "reprice"]
        run(desk, clock, 4)
        assert len(account.creates) == 4 and desk.pull.held(TICKER, clock.now())
        # The old rule cancelled the twin's copies too, then (without the pull) rebid at the new fair at once.
        assert not set(desk.twin.orders) & {3, 4} and set(desk.twin.orders) == desk.twin_kept
        assert sorted((order.side, order.price, order.size) for order in desk.twin.orders.values()) == [
            ("down", .45, 3), ("up", .48, 3)]
        # Both bids were up when the fair moved: counted as pulled, whichever rule named the cancel.
        assert desk.panel()["pull"]["bids_pulled_today"] == 2
    finally:
        desk.close()


def test_the_twin_does_not_pull_its_bids_stay_resting(tmp_path: Path) -> None:
    desk, account, clock = two_bids(tmp_path)
    try:
        twin_bids = {order_id: (order.side, order.price) for order_id, order in desk.twin.orders.items()}
        swing(desk, clock, .0053)
        assert account.cancels == ["order-4", "order-3"]
        assert {order_id: (order.side, order.price) for order_id, order in desk.twin.orders.items()} == twin_bids
        assert desk.twin_kept == set(twin_bids)
        desk.checkpoint()  # receipts reach the ledger with the next save (within a second), not at the cancel
        assert not [receipt for receipt in desk.ledger.iter_receipts() if receipt.kind == "speeddesk_twin"
                    and receipt.payload.get("event") == "speeddesk_cancel"]
        run(desk, clock, 12)  # the hold ends and the bot bids again; the twin keeps its own (0.50-fair) bids
        assert set(desk.twin.orders) == set(twin_bids)
    finally:
        desk.close()


def test_the_twins_kept_bid_follows_the_old_reprice_rule(tmp_path: Path) -> None:
    desk, account, clock = two_bids(tmp_path)
    try:
        swing(desk, clock, .0053)
        assert desk.twin_kept == {3, 4}
        market(desk, clock, .512)  # 1.2c from the bids' own fair: the old rule reprices them
        run(desk, clock, .6)
        desk.checkpoint()  # receipts reach the ledger with the next save (within a second), not at the cancel
        cancelled = [receipt.payload for receipt in desk.ledger.iter_receipts() if receipt.kind == "speeddesk_twin"
                     and receipt.payload.get("event") == "speeddesk_cancel"]
        assert [(row["order_id"], row["reason"]) for row in cancelled] == [(3, "reprice"), (4, "reprice")]
        # ... and rebids at the new fair (the real companion is still held).
        assert sorted((order.side, order.price) for order in desk.twin.orders.values()) == [("down", .45), ("up", .48)]
        assert set(desk.twin.orders) == desk.twin_kept and len(account.creates) == 4
    finally:
        desk.close()


def test_a_held_window_gets_the_twins_bid_but_no_real_one(tmp_path: Path) -> None:
    """The move comes before the first bid: no real bid is sent, the twin rests the starter the old rule would."""
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        market(desk, clock, .4947)
        desk.on_tick(80000, clock.now(), clock.now())  # the tick wake alone runs the trigger check
        clock.advance(.3)
        market(desk, clock, .5053)
        desk.on_tick(80000, clock.now(), clock.now())
        assert desk.pull.held(TICKER, clock.now())
        run(desk, clock, 3)
        assert not account.creates
        [order] = desk.twin.orders.values()
        assert (order.side, order.kind, order.price, order.size) == ("up", "rest", .47, 5)
        run(desk, clock, 10)
        assert [(c["side"], c["price"]) for c in account.creates] == [("up", .47)]
        assert list(desk.twin.orders.values()) == [order]  # its own bid, not a second copy
    finally:
        desk.close()


@pytest.mark.parametrize("pull", [True, False])
def test_the_send_guard_refuses_a_bid_whose_fair_moved_on_its_way(tmp_path: Path, pull: bool) -> None:
    """The decision passed, then the fair moved 1.2c before the first byte left: the last check under the transport
    lock refuses the resting bid (the edge and the book still allow it, so only the pull refuses it)."""
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra={**MAKERS, "speeddesk_kalshi_pull": pull})
    try:
        market(desk, clock, .5)
        desk.on_tick(80000, clock.now(), clock.now())
        create = account.create_order

        def moved(**kwargs: Any) -> dict[str, Any]:
            market(desk, clock, .512, feed=False)  # the fair moves while the order is on its way
            return create(**kwargs)

        account.create_order = moved  # type: ignore[method-assign]
        asyncio.run(desk.step())
        if pull:
            assert not account.creates
            assert [event["state"] for event in desk.latest_events
                    if event["event"] == "speeddesk_live_order"][-1] == "not sent; prices moved before send"
        else:
            assert [(c["side"], c["price"]) for c in account.creates] == [("up", .47)]
    finally:
        desk.close()


def test_locks_still_fire_during_a_hold(tmp_path: Path) -> None:
    """A lock buy is immediate-or-cancel and only completes pairs: a pull never delays it."""
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        starter_bid_filled(desk, account, clock)
        run(desk, clock, 1.5)
        window = desk.book.windows[TICKER]
        clock.advance(window.end - 239 - clock.now())  # inside the lock period
        market(desk, clock, .2, ask=.25)
        desk.on_tick(80000, clock.now(), clock.now())
        clock.advance(.2)
        market(desk, clock, .23, ask=.25)  # 3c in 0.2 s
        desk.on_tick(80000, clock.now(), clock.now())
        assert desk.pull.held(TICKER, clock.now())
        held_at_send: list[bool] = []
        create = account.create_order

        def watched(**kwargs: Any) -> dict[str, Any]:
            held_at_send.append(desk.pull.held(TICKER, clock.now()))
            return create(**kwargs)

        account.create_order = watched  # type: ignore[method-assign]
        run(desk, clock, 1.5)
        locks = [create for create in account.creates if create["kind"] == "take"]
        assert [(lock["side"], lock["size"]) for lock in locks] == [("down", 5)]
        assert held_at_send == [True]
    finally:
        desk.close()


def test_no_cancel_is_resent_once_kalshi_accepted_it(tmp_path: Path) -> None:
    desk, account, clock = two_bids(tmp_path)
    try:
        def lagging_cancel(order_id: str, *, ticker: str) -> dict[str, object]:
            account.cancels.append(order_id)  # accepted, but the order list keeps showing it resting
            return {}

        account.cancel = lagging_cancel  # type: ignore[method-assign]
        for _ in range(6):  # moves keep coming for about 4 s, past the 2 s cancel retry
            swing(desk, clock, .0053)
            swing(desk, clock, -.0053)
        assert account.cancels == ["order-4", "order-3"]
        assert desk.panel()["pull"]["bids_pulled_today"] == 2
    finally:
        desk.close()


def test_a_burst_of_moves_never_exceeds_the_write_budget(tmp_path: Path) -> None:
    desk, account, clock = two_bids(tmp_path)
    writes: list[float] = []
    create, cancel = account.create_order, account.cancel

    def timed_create(**kwargs: Any) -> dict[str, Any]:
        writes.append(clock.now())
        return create(**kwargs)

    def timed_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
        writes.append(clock.now())
        return cancel(order_id, ticker=ticker)

    account.create_order = timed_create  # type: ignore[method-assign]
    account.cancel = timed_cancel  # type: ignore[method-assign]
    try:
        for step in range(200):  # 20 s of ticks every 0.1 s, the fair jumping 0.6c either way of 0.50
            market(desk, clock, .5 + (.006 if step % 2 else -.006))
            run(desk, clock, .1, every=.1)
        assert sorted(account.cancels) == ["order-3", "order-4"]  # one cancel per bid, nothing re-sent
        assert len(account.creates) == 4 and len(writes) == 2  # no bid while the moves keep coming
        run(desk, clock, 12)  # calm again: the bids come back once each
        assert len(account.creates) == 6 and len(set(account.cancels)) == len(account.cancels)
        assert max(sum(1 for moment in writes if start <= moment < start + 1) for start in writes) <= WRITES_PER_S
        assert desk.panel()["pull"]["pulls_today"] == 1  # one long pull, extended by every move
    finally:
        desk.close()


def test_the_guard_switched_off_is_todays_behaviour(tmp_path: Path) -> None:
    desk, account, clock = two_bids(tmp_path, speeddesk_kalshi_pull=False)
    try:
        swing(desk, clock, .0053)
        run(desk, clock, 2)
        assert not account.cancels and sorted(bids(account)) == [("down", .47), ("up", .47)]
        panel = desk.panel()["pull"]
        assert panel["enabled"] is False and panel["since"] is None and panel["since_pull"] is None
    finally:
        desk.close()


def test_pulls_count_only_while_real_money_is_on(tmp_path: Path) -> None:
    desk, _, clock = make_desk(tmp_path, mode="paper", caps=CAPS, extra=MAKERS)
    try:
        market(desk, clock, .4947)
        run(desk, clock, .3)
        market(desk, clock, .5053)
        run(desk, clock, 12)
        assert desk.panel()["pull"]["pulls_today"] == 0 and not pull_lines(desk)
    finally:
        desk.close()


# The pull's books on their own.

def test_the_trigger_reads_either_direction_within_the_lookback_only() -> None:
    guard = PullGuard(PullRule(), now=0.0)
    guard.observe("w", .50, 0.0, count=True)
    guard.observe("w", .505, 1.0, count=True)
    assert not guard.held("w", 1.0)
    guard.observe("w", .495, 2.0, count=True)  # 1c below the high a second ago
    assert guard.held("w", 2.0) and guard.pulled_since("w", 1.9) and not guard.pulled_since("w", 2.1)
    guard.observe("w", .495, 4.0, count=True)  # the high is still in the lookback: the trigger goes on
    assert guard.last_trigger["w"] == 4.0
    guard.observe("w", .495, 6.5, count=True)  # the high left the lookback at 6.0: no new trigger
    assert guard.last_trigger["w"] == 4.0 and guard.held("w", 8.9) and not guard.held("w", 9.1)
    assert not guard.expire(8.9) and [line["bids_pulled"] for line in guard.expire(9.1)] == [0]
    assert guard.panel(9.1)["pulls_today"] == 1 and guard.panel(9.1)["held"] == {}


def test_the_send_guard_check_refuses_a_bid_the_moment_the_fair_moved() -> None:
    guard = PullGuard(PullRule(hold_s=0), now=0.0)
    guard.observe("w", .50, 0.0, count=True)
    assert not guard.blocks("w", .505, .1)
    assert guard.blocks("w", .4899, .1)  # not yet sampled, but already a trigger against the lookback
    assert not guard.blocks("w", .4899, 6.0)  # the samples are too old to count


def test_saved_counts_survive_a_restart_and_a_changed_rule_restarts_the_comparison() -> None:
    guard = PullGuard(PullRule(), now=100.0)
    guard.observe("w", .50, 100.0, count=True)
    guard.observe("w", .52, 100.5, count=True)
    guard.note_bid("w", 100.5)
    saved = guard.to_state()
    again = PullGuard(PullRule(), now=500.0, saved=saved)
    assert again.since == 100.0 and again.panel(500.0)["pulls_today"] == 1
    assert again.panel(500.0)["bids_pulled_today"] == 1
    changed = PullGuard(PullRule(move=.02), now=500.0, saved=saved)
    assert changed.since == 500.0 and changed.panel(500.0)["pulls_today"] == 1
    assert PullGuard(PullRule(enabled=False), now=500.0, saved=saved).since is None
    assert PullGuard(PullRule(), now=500.0, saved={"version": 9}).since == 500.0


def test_compare_counts_pnl_where_both_traded_and_fills_where_either_did() -> None:
    starts = {"a": 10.0, "b": 20.0, "c": 30.0, "old": 1.0}
    live = {"a": .5, "b": -1.0, "old": 9.0}
    twin = {"a": .25, "c": 2.0, "old": -9.0}
    report = compare(starts, live, twin, [("a", 5), ("a", 2), ("b", 5), ("old", 5)], [("a", 5), ("c", 5), ("c", 5)],
                     start=5.0)
    assert report == {"windows_both_traded": 1, "live_pnl_usd": .5, "twin_pnl_usd": .25, "live_minus_twin_usd": .25,
                      "windows_either_traded": 3, "live_pnl_either_usd": -.5, "twin_pnl_either_usd": 2.25,
                      "live_minus_twin_either_usd": -2.75, "live_maker_fills": 3, "live_maker_contracts": 12,
                      "live_maker_fills_per_window": 1.0, "twin_maker_fills": 3, "twin_maker_contracts": 15,
                      "twin_maker_fills_per_window": 1.0, "live_locks": 0, "live_lock_contracts": 0,
                      "live_lock_cost_usd": 0, "live_locks_per_window": 0.0}
    before = compare(starts, live, twin, [("old", 5)], [], start=0.0, end=5.0)
    assert before["windows_both_traded"] == 1 and before["live_minus_twin_usd"] == 18.0
    assert compare({}, {}, {}, [], [], start=0.0)["live_maker_fills_per_window"] is None


def test_the_panel_compares_real_and_twin_since_the_pull_went_live(tmp_path: Path) -> None:
    desk, _, clock = two_bids(tmp_path)
    try:
        window = desk.book.windows[TICKER]
        panel = desk.panel()["pull"]
        assert panel["since"] > window.start  # this window opened before the pull went live
        assert panel["since_pull"]["windows_either_traded"] == 0
        assert panel["week_before"]["live_maker_fills"] == 0  # not settled yet
        # Settle the window by hand: the real pair made 0.30, the twin's (the same two fills, practice) 0.25.
        desk.book.settled[TICKER] = LiveSettlement(TICKER, "kalshi:x", clock.now(), True, 5, 5, 4.7, 0, 5, 5, 5,
                                                   .3, 0, .3)
        desk.twin.closed.append(Settlement(TICKER, clock.now(), True, 5, 5, 4.7, .05, 5, .25, 0, .25))
        # Open when the pull first went live, it is in neither comparison; as if it went live at this window's close:
        desk.pull.first_live = window.end
        control = desk.panel()["pull"]["week_before"]
        assert (control["windows_both_traded"], control["live_pnl_usd"], control["twin_pnl_usd"]) == (1, .3, .25)
        assert (control["windows_either_traded"], control["live_maker_fills"], control["twin_maker_fills"]) == (1, 2, 2)
        assert control["live_maker_contracts"] == control["twin_maker_contracts"] == 10
        desk.pull.since = window.start
        assert desk.panel()["pull"]["since_pull"]["live_minus_twin_usd"] == pytest.approx(.05)
        status = desk.panel()
        assert status["pull"]["day"] == utc_day(clock.now()) and "pull" in desk.ledger.get_kv("kalshi_live_state")
    finally:
        desk.close()


def test_the_page_feed_carries_the_pull_numbers_and_nothing_else(tmp_path: Path) -> None:
    desk, _, clock = two_bids(tmp_path)
    try:
        swing(desk, clock, .0053)
        raw = desk.panel()
        raw["pull"]["held"]["<script>"] = 1.0
        page = pagestate._kalshi_pull(raw["pull"], utc_day(clock.now()))
        assert page is not None and page["enabled"] and page["pulls_today"] == 1 and page["bids_pulled_today"] == 2
        assert list(page["held"]) == [TICKER] and page["since_pull"]["live_pnl_usd"] == 0
        assert page["first_live"] == raw["pull"]["first_live"] and page["since_pull"]["live_locks"] == 0
        assert page["since_pull"]["live_pnl_either_usd"] == 0 and page["week_before"]["live_lock_cost_usd"] == 0
        assert pagestate._kalshi_pull(raw["pull"], "2099-01-01")["pulls_today"] is None  # another day: unknown
        assert pagestate._kalshi_pull(None, "x") is None
    finally:
        desk.close()


# Settings.

def test_pull_settings_default_on_with_the_replay_values() -> None:
    settings = Settings()
    assert settings.speeddesk_kalshi_pull is True
    assert (settings.speeddesk_kalshi_pull_move, settings.speeddesk_kalshi_pull_lookback_s,
            settings.speeddesk_kalshi_pull_hold_s) == (.01, 5, 5)
    assert PullRule.from_settings(settings) == PullRule()
    assert Settings.from_env({"SPEEDDESK_KALSHI_PULL": "false"}).speeddesk_kalshi_pull is False


@pytest.mark.parametrize(("name", "low", "high"), [("speeddesk_kalshi_pull_move", .002, .10),
                                                    ("speeddesk_kalshi_pull_lookback_s", .5, 30),
                                                    ("speeddesk_kalshi_pull_hold_s", 0, 60)])
def test_pull_settings_are_validated(name: str, low: float, high: float) -> None:
    assert getattr(Settings(**{name: low}), name) == low
    assert getattr(Settings.from_env({name.upper(): str(high)}), name) == high
    for value in (low - .0001, high + .0001, float("nan"), float("inf"), True, "0.01"):
        with pytest.raises(ConfigError, match=name.upper()):
            Settings(**{name: value})
    with pytest.raises(ConfigError, match=name.upper()):
        Settings.from_env({name.upper(): "lots"})


@pytest.mark.parametrize("value", ["yes please", 1, None])
def test_the_pull_switch_is_a_plain_boolean(value: Any) -> None:
    with pytest.raises(ConfigError, match="SPEEDDESK_KALSHI_PULL"):
        Settings(speeddesk_kalshi_pull=value)
    with pytest.raises(ConfigError, match="SPEEDDESK_KALSHI_PULL"):
        Settings.from_env({"SPEEDDESK_KALSHI_PULL": "maybe"})


def test_fair_helper_matches_the_bots_fair() -> None:
    clock = FakeClock()
    end = clock.now() + 890
    for up in (.3, .5, .5053, .9):
        bitcoin = 80000 * math.exp(NormalDist().inv_cdf(up) * SIGMA * math.sqrt(horizon(end - clock.now())))
        assert fair_up(bitcoin, 80000, SIGMA, end - clock.now(), settles_on_average=True) == pytest.approx(up, abs=1e-9)
        window = Window(TICKER, end - 900, end, start_price=80000, venue="kalshi")
        snapshot = LiveSnapshot((window,), {}, bitcoin, clock.now(), SIGMA, frozenset({TICKER}))
        assert KalshiLiveDesk._fair(window, snapshot, clock.now()) == pytest.approx(up, abs=1e-9)


# Review findings (2026-10-13 fix round), each reproduced first as the reviewers found it.

def _resting(account: FakeAccount, order_id: str) -> bool:
    return any(order["order_id"] == order_id and order["status"] == "resting" for order in account.orders)


def _flaky_cancel(account: FakeAccount) -> list[str]:
    """The next cancel gets a 503 (outcome unconfirmed); later ones go through. Returns the failed order ids."""
    cancel, failed = account.cancel, []

    def flaky(order_id: str, *, ticker: str) -> dict[str, Any]:
        if not failed:
            failed.append(order_id)
            raise KalshiClientError("cancel", "result unconfirmed", status=503, uncertain=True)
        return cancel(order_id, ticker=ticker)

    account.cancel = flaky  # type: ignore[method-assign]
    return failed


def test_a_pull_cancel_that_fails_inside_a_reconcile_is_sent_again(tmp_path: Path) -> None:
    """H1: the fair jumps while the order list is being read (the cancel check runs after every account read); the
    first pull cancel gets a 503, and the same reconcile then matches the order's fills and clears its uncertainty.
    Before the fix nothing was sent again: the pulled bid rested until it expired and blocked every new order."""
    desk, account, clock = two_bids(tmp_path)
    try:
        market(desk, clock, .4947)
        run(desk, clock, .3)
        failed = _flaky_cancel(account)
        list_orders, moved = account.list_orders, []

        def moving(**kwargs: Any) -> list[dict[str, Any]]:
            if not moved:
                moved.append(True)
                market(desk, clock, .5053, feed=False)
            return list_orders(**kwargs)

        account.list_orders = moving  # type: ignore[method-assign]
        clock.advance(1.0)  # a reconcile is due
        asyncio.run(desk.step())
        [first] = failed
        assert account.cancels == [({"order-3", "order-4"} - {first}).pop()]
        intent = next(item for item in desk.intents.values() if item.order_id == first)
        assert intent.cancel_requested and not intent.uncertain  # the case the old acknowledgement test misread
        run(desk, clock, 3)  # past the 2 s retry gate
        assert account.cancels.count(first) == 1 and not _resting(account, first)
        assert desk.panel()["pull"]["bids_pulled_today"] == 2
    finally:
        desk.close()


def test_a_pull_on_a_bid_whose_create_reply_was_lost_still_cancels_it(tmp_path: Path) -> None:
    """H1: the create reached Kalshi but its reply was lost, so the order id is unknown when the pull comes. The
    cancel goes out in the reconcile that learns the id (that reconcile waits out the create error's own backoff);
    before the fix it was never sent."""
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        market(desk, clock, .4947)
        create = account.create_order

        def lost(**kwargs: Any) -> dict[str, Any]:
            create(**kwargs)
            raise KalshiClientError("create_order", "transport failure", uncertain=True, timed_out=True)

        account.create_order = lost  # type: ignore[method-assign]
        asyncio.run(desk.step())
        assert len(account.creates) == 1 and _resting(account, "order-1")
        account.create_order = create  # type: ignore[method-assign]
        clock.advance(.3)
        market(desk, clock, .5053)
        desk.on_tick(80000, clock.now(), clock.now())
        cancelled_at: list[float] = []
        read_at: list[float] = []
        cancel, list_orders = account.cancel, account.list_orders

        def timed(order_id: str, *, ticker: str) -> dict[str, Any]:
            cancelled_at.append(clock.now())
            return cancel(order_id, ticker=ticker)

        def reading(**kwargs: Any) -> list[dict[str, Any]]:
            read_at.append(clock.now())
            return list_orders(**kwargs)

        account.cancel = timed  # type: ignore[method-assign]
        account.list_orders = reading  # type: ignore[method-assign]
        run(desk, clock, 3)
        assert account.cancels == ["order-1"] and not _resting(account, "order-1")
        assert cancelled_at == [read_at[0]]  # within the first reconcile that read the order list
    finally:
        desk.close()


def test_a_failed_cancel_is_sent_again_after_its_reason_passed(tmp_path: Path) -> None:
    """H1's root cause predates the pull (seen on 61ca112): a failed cancel was re-sent only while its reason still
    held. Pull off: a 1.5c rise reprices both bids, the first cancel gets a 503, the fair comes back before the retry:
    the cancel still goes out once."""
    desk, account, clock = two_bids(tmp_path, speeddesk_kalshi_pull=False)
    try:
        failed = _flaky_cancel(account)
        market(desk, clock, .515)
        run(desk, clock, .3)
        [first] = failed
        market(desk, clock, .5)
        run(desk, clock, 4)
        assert account.cancels.count(first) == 1 and not _resting(account, first)
    finally:
        desk.close()


def _write_burst(tmp_path: Path, *, counted: bool, pull: bool = True) -> tuple[int, list[str]]:
    """Two resting bids; the fair drifts past the 1c reprice rule too slowly to pull (0.15c a second), so both are
    repriced and the bot bids again, and then the fair jumps 1c: the pull's cancels come on top of those writes.
    ``counted``: the account reports its rolling write count, as the real client does."""
    desk, account, clock = two_bids(tmp_path, speeddesk_kalshi_pull=pull)
    writes: list[tuple[str, float]] = []
    create, cancel = account.create_order, account.cancel

    def timed_create(**kwargs: Any) -> dict[str, Any]:
        writes.append(("create", clock.now()))
        return create(**kwargs)

    def timed_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
        writes.append(("cancel", clock.now()))
        return cancel(order_id, ticker=ticker)

    account.create_order = timed_create  # type: ignore[method-assign]
    account.cancel = timed_cancel  # type: ignore[method-assign]
    if counted:
        account.writes_last_second = lambda: sum(1 for _, at in writes if at > clock.now() - 1)  # type: ignore[attr-defined]
    try:
        up = .5
        while up < .5102:
            up += .00015
            market(desk, clock, up)
            run(desk, clock, .1, every=.1)
        run(desk, clock, .4, every=.1)
        market(desk, clock, up + .0105)
        run(desk, clock, 1.5, every=.1)
        stamps = [at for _, at in writes]
        return max(sum(1 for at in stamps if start <= at < start + 1) for start in stamps), [name for name, _ in writes]
    finally:
        desk.close()


def test_new_bids_keep_write_room_for_the_pulls_cancels(tmp_path: Path) -> None:
    """M2: two reprice cancels, two new bids, then the pull's two cancels made six writes in 0.8 s against the
    client's five a second, so a pull cancel waited on the wire. A new bid now waits while the last second already
    holds WRITES_PER_S - 2 writes."""
    peak, names = _write_burst(tmp_path / "before", counted=False)
    assert peak == 6 > WRITES_PER_S and names == ["cancel", "cancel", "create", "create", "cancel", "cancel"]
    peak, names = _write_burst(tmp_path / "after", counted=True)
    assert peak <= WRITES_PER_S - 1 and names == ["cancel", "cancel", "create", "cancel"]
    # Pull off: today's behaviour, the client's own budget only.
    assert _write_burst(tmp_path / "off", counted=True, pull=False)[1][:4] == ["cancel", "cancel", "create", "create"]


def test_a_bid_held_back_for_write_room_rests_in_the_twin(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        busy = [WRITES_PER_S - 2]
        account.writes_last_second = lambda: busy[0]  # type: ignore[attr-defined]
        market(desk, clock, .5)
        asyncio.run(desk.step())
        assert not account.creates and desk.reason == WRITE_ROOM_REASON
        [order] = desk.twin.orders.values()  # without the pull the bid was sent: the twin rests it
        assert (order.side, order.price, order.size) == ("up", .47, 5) and desk.twin_kept == {order.order_id}
        busy[0] = WRITES_PER_S - 3
        run(desk, clock, .6)
        assert [(c["side"], c["price"]) for c in account.creates] == [("up", .47)]
    finally:
        desk.close()


def test_a_pull_leaves_the_account_read_to_the_regular_reconcile(tmp_path: Path) -> None:
    """M3: a pull cancel no longer forces an immediate account re-read (the hold and the unconfirmed cancel already
    keep new orders back); the old stale-bid cancel still does."""
    desk, account, clock = two_bids(tmp_path)
    try:
        market(desk, clock, .4947)
        run(desk, clock, .3)
        market(desk, clock, .5053, feed=False)
        desk.on_tick(80000, clock.now(), clock.now())
        fresh = desk.account_at
        asyncio.run(desk._cancel_unsafe())
        assert sorted(account.cancels) == ["order-3", "order-4"] and fresh is not None and desk.account_at == fresh
    finally:
        desk.close()
    desk, account, clock = two_bids(tmp_path / "off", speeddesk_kalshi_pull=False)
    try:
        market(desk, clock, .515, feed=False)
        asyncio.run(desk._cancel_unsafe())
        assert sorted(account.cancels) == ["order-3", "order-4"] and desk.account_at is None
    finally:
        desk.close()


def _choppy(tmp_path: Path, *, pull: bool) -> dict[str, Any]:
    """The Up fair flips between 0.495 and 0.505 every 10.2 s for a minute: a 1c move each time, yet the bids
    priced at 0.50 are never 1c from their own fair, so the rule without the pull never cancels them."""
    desk, account, clock = two_bids(tmp_path, speeddesk_kalshi_pull=pull)
    try:
        flip, next_flip, end = 1, clock.now(), clock.now() + 60
        while clock.now() < end - 1e-9:
            if clock.now() >= next_flip - 1e-9:
                flip = -flip
                market(desk, clock, .5 + .005 * flip)
                next_flip += 10.2
            run(desk, clock, .2, every=.2)
        desk.checkpoint()  # receipts reach the ledger with the next save (within a second), not at the cancel
        twin = [receipt.payload for receipt in desk.ledger.iter_receipts() if receipt.kind == "speeddesk_twin"]
        return {"twin": sorted((order.side, order.price, order.size) for order in desk.twin.orders.values()),
                "twin_cancels": [row for row in twin if row.get("event") == "speeddesk_cancel"],
                "twin_rests": sum(row.get("event") == "speeddesk_rest" for row in twin),
                "creates": len(account.creates), "cancels": len(account.cancels), "panel": desk.panel()["pull"]}
    finally:
        desk.close()


def test_in_a_choppy_market_the_twin_is_the_bot_without_the_pull(tmp_path: Path) -> None:
    """M4: every real re-bid lands at an extreme fair, so the old 1c rule names the next cancel ("reprice"), and
    such a cancel used to cancel the twin's kept bids too: the twin copied the pulled bot (20 cancels in 2 minutes)
    instead of keeping the no-pull bot's bids. Now it matches a genuine pull-off run, and every real cancel at a move
    counts as pulled."""
    on, off = _choppy(tmp_path / "on", pull=True), _choppy(tmp_path / "off", pull=False)
    assert off["creates"] == 4 and off["cancels"] == 0 and not off["twin_cancels"]
    assert on["creates"] > 4 and on["cancels"] > 2  # the real bot pulls and bids again after each hold
    assert not on["twin_cancels"] and on["twin"] == off["twin"] and on["twin_rests"] == off["twin_rests"]
    assert on["panel"]["bids_pulled_today"] == on["cancels"]


def test_the_twin_bids_again_when_its_kept_bid_is_repriced_while_the_real_one_rests(tmp_path: Path) -> None:
    """Correctness review 1 (HIGH): after a hold the real bot rests new bids at 0.5053 while the twin keeps its 0.50
    ones; the fair then sits at 0.512 (0.7c from the real bids, 1.2c from the twin's). The old rule reprices the
    twin's and bids again at once; the twin used to stay bidless until the real bids ended."""
    desk, account, clock = two_bids(tmp_path)
    try:
        swing(desk, clock, .0053)
        run(desk, clock, 12)
        assert sorted(bids(account)) == [("down", .46), ("up", .47)] and desk.twin_kept == {3, 4}
        market(desk, clock, .512)
        run(desk, clock, 6)
        assert sorted(bids(account)) == [("down", .46), ("up", .47)] and not desk.pull.held(TICKER, clock.now())
        assert sorted((order.side, order.price, round(order.fair, 3)) for order in desk.twin.orders.values()) == [
            ("down", .45, .488), ("up", .48, .512)]
        assert set(desk.twin.orders) == desk.twin_kept and not desk.twin_owed
    finally:
        desk.close()


def test_a_bid_the_pull_stops_at_the_send_leaves_the_twins_kept_bids_alone(tmp_path: Path) -> None:
    """Correctness review 6: a trigger between the decision and the first byte made the send guard refuse the real
    bid, and the refusal cancelled every twin bid in the window. Without the pull the bid was sent: the twin keeps
    its bids."""
    desk, _, clock = two_bids(tmp_path)
    try:
        swing(desk, clock, .0053)
        run(desk, clock, 8.7)  # the hold is nearly over; the twin keeps both bids
        before = {order_id: (order.side, order.price) for order_id, order in desk.twin.orders.items()}
        assert set(before) == desk.twin_kept == {3, 4}
        blocks, calls = desk.pull.blocks, []

        def once(window: str, up: float, now: float) -> bool:
            calls.append(now)
            return len(calls) == 1 or blocks(window, up, now)

        desk.pull.blocks = once  # type: ignore[method-assign]
        run(desk, clock, 1.8)
        assert calls and any(event.get("state") == "not sent; prices moved before send" for event in desk.latest_events)
        assert {order_id: (order.side, order.price) for order_id, order in desk.twin.orders.items()} == before
        desk.checkpoint()  # receipts reach the ledger with the next save (within a second), not at the cancel
        assert not [receipt for receipt in desk.ledger.iter_receipts() if receipt.kind == "speeddesk_twin"
                    and receipt.payload.get("event") == "speeddesk_cancel"]
    finally:
        desk.close()


def test_twin_logic_never_touches_the_real_risk_book(tmp_path: Path) -> None:
    """L8/review 8: the held window's twin bid was sized with the real book's can_buy, which notes a real stop (and
    holds the ladder) when even one contract is refused. It is sized by the twin's own books now."""
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        desk.book.can_buy = lambda *args, **kwargs: pytest.fail("practice code asked the real risk book")  # type: ignore[method-assign]
        market(desk, clock, .4947)
        desk.on_tick(80000, clock.now(), clock.now())
        clock.advance(.3)
        market(desk, clock, .5053)
        desk.on_tick(80000, clock.now(), clock.now())
        run(desk, clock, 3)
        assert not account.creates and desk.book.stop_hit_at is None
        [order] = desk.twin.orders.values()
        assert (order.side, order.price, order.size) == ("up", .47, 5)
    finally:
        desk.close()


def test_a_kept_twin_bid_is_cancelled_when_a_take_is_available(tmp_path: Path) -> None:
    """Review 10 (latent, takes are off): the old rule cancels a resting bid when the ask can be taken; a kept twin
    bid that ignored it would refuse the twin's copy of the real take."""
    desk, _, clock = two_bids(tmp_path)
    try:
        swing(desk, clock, .0053)
        assert desk.twin_kept == {3, 4}
        desk.settings = replace(desk.settings, speeddesk_take_edge=.01)
        # Asks at 0.47 (0.49 with the fee reserve): Up (fair 0.5053) can take it, Down (fair 0.4947) cannot.
        market(desk, clock, .5053, ask=.47, feed=False)
        desk._twin_unpulled(desk.snapshot(), clock.now())
        desk.checkpoint()
        cancelled = [receipt.payload for receipt in desk.ledger.iter_receipts() if receipt.kind == "speeddesk_twin"
                     and receipt.payload.get("event") == "speeddesk_cancel"]
        assert [(row["side"], row["reason"]) for row in cancelled] == [("up", "take_available")]
        assert [desk.twin.orders[order_id].side for order_id in desk.twin_kept] == ["down"] and not desk.twin_owed
    finally:
        desk.close()


def test_the_bid_whose_fair_fell_is_cancelled_first(tmp_path: Path) -> None:
    """L5: after a rise the Down bid is the one now priced too high (it sold to us next), and the cancels go one at a
    time with a save and a round trip each: it goes first. After a fall, the Up bid goes first."""
    for direction, first in ((1, "order-4"), (-1, "order-3")):
        desk, account, clock = two_bids(tmp_path / str(direction))
        try:
            market(desk, clock, .5 + .0106 * direction)
            run(desk, clock, .3)
            assert account.cancels[0] == first and sorted(account.cancels) == ["order-3", "order-4"]
        finally:
            desk.close()


def test_one_fair_value_behind_every_decision_and_trigger(tmp_path: Path) -> None:
    """Review 5 (merge hazard): the speed branch changes fair_up's arguments at each call site; the trigger had its
    own call and would have kept the old fair. Every check now goes through KalshiLiveDesk._fair."""
    assert inspect.getsource(speeddesk_live).count("fair_up(") == 1
    desk, _, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        market(desk, clock, .5)
        asyncio.run(desk.step())
        [intent] = desk.intents.values()
        assert intent.side == "up" and desk.pull.fairs[TICKER].low[-1][1] == intent.fair
    finally:
        desk.close()


def test_a_hold_survives_a_restart(tmp_path: Path) -> None:
    """L9: a redeploy right after a jump used to let the bot bid again as soon as the startup reconcile finished."""
    desk, account, clock = two_bids(tmp_path)
    swing(desk, clock, .0053)
    desk.checkpoint()
    restored = reopen(tmp_path, desk, account, clock, caps=CAPS)
    try:
        assert restored.pull.held(TICKER, clock.now()) and restored.pull.since == desk.pull.since
        clock.advance(restored.pull.rule.hold_s + .1)
        assert not restored.pull.held(TICKER, clock.now())
    finally:
        restored.close()


def test_a_long_lookback_keeps_its_whole_history() -> None:
    """L7: the history was capped at 4,096 samples (20 s at 200 a second, against an allowed 30 s lookback) and each
    sample rescanned it. The running extremes match a full scan of the lookback on every sample."""
    rng = random.Random(3)
    for lookback in (.5, 5.0, 30.0):
        guard = PullGuard(PullRule(lookback_s=lookback, move=.01), now=0.0)
        history: list[tuple[float, float]] = []
        up, now = .5, 0.0
        for _ in range(8000):
            now += .005
            up = round(up + rng.choice((-1, 1)) * .0003, 6)  # every sample a new value: 6,000 in 30 s
            guard.observe("w", up, now, count=True)
            history.append((now, up))
            if len(history) % 97 == 0:  # a full scan of the lookback, every 97th sample
                inside = [value for at, value in history if at >= now - lookback - 1e-8]
                low, high, _ = guard.range["w"]
                assert (low, high) == (min(inside), max(inside))


def test_a_clock_step_back_never_stretches_the_hold() -> None:
    """L6: a trigger at 1000 and the wall clock stepping back to 900 held the window until 1005 (105 s)."""
    guard = PullGuard(PullRule(), now=990.0)
    guard.observe("w", .50, 999.0, count=True)
    guard.observe("w", .52, 1000.0, count=True)
    guard.observe("w", .52, 900.0, count=True)
    assert guard.held("w", 900.0) and guard.held("w", 905.0) and not guard.held("w", 905.1)
    assert guard.open["w"].held_until == 905.0


def test_the_week_before_baseline_starts_from_the_first_go_live() -> None:
    """Review 7: a changed setting restarts ``since``; the baseline must still end where the pull first went live,
    or it covers days the pull was already on."""
    first = PullGuard(PullRule(), now=1000.0)
    changed = PullGuard(PullRule(move=.02), now=5000.0, saved=first.to_state())
    assert (changed.since, changed.first_live) == (5000.0, 1000.0)
    off = PullGuard(PullRule(enabled=False), now=6000.0, saved=changed.to_state())
    assert (off.since, off.first_live) == (None, 1000.0)
    again = PullGuard(PullRule(), now=7000.0, saved=off.to_state())
    assert (again.since, again.first_live) == (7000.0, 1000.0)
    legacy = {key: value for key, value in first.to_state().items() if key != "first_live"}
    assert PullGuard(PullRule(move=.02), now=5000.0, saved=legacy).first_live == 1000.0


def test_compare_shows_pnl_where_either_traded_and_the_real_lock_buys() -> None:
    """Review 2 and 3: the pull's main effect is fewer fills, and windows only one side traded were left out of the
    P&L; and a pull that leaves more windows half filled buys more locks, on the real side only."""
    starts = {"a": 10.0, "b": 20.0, "c": 30.0, "old": 1.0}
    live, twin = {"a": .5, "b": -1.0, "old": 9.0}, {"a": .25, "c": 2.0}
    report = compare(starts, live, twin, [], [], [("b", 5, 4.1), ("a", 2, 1.9), ("old", 5, 5.0)], start=5.0)
    assert (report["live_pnl_usd"], report["twin_pnl_usd"]) == (.5, .25)  # both traded: "a" only
    assert (report["live_pnl_either_usd"], report["twin_pnl_either_usd"], report["live_minus_twin_either_usd"]) == (
        -.5, 2.25, -2.75)
    assert (report["live_locks"], report["live_lock_contracts"], report["live_lock_cost_usd"]) == (2, 7, 6.0)
    assert report["live_locks_per_window"] == pytest.approx(2 / 3, abs=1e-4)


def test_the_panel_counts_the_real_lock_buys(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        starter_bid_filled(desk, account, clock)
        run(desk, clock, 1.5)
        window = desk.book.windows[TICKER]
        clock.advance(window.end - 239 - clock.now())
        market(desk, clock, .2, ask=.25)
        run(desk, clock, 1.5)
        [lock] = [index for index, create in enumerate(account.creates) if create["kind"] == "take"]
        fill_order(account, clock, lock, side="down", price=.25, size=5)
        account.account_positions = []
        run(desk, clock, 1.5)
        desk.book.settled[TICKER] = LiveSettlement(TICKER, "kalshi:x", clock.now(), True, 5, 5, 3.6, 0, 5, 5, 5,
                                                   1.4, 0, 1.4)
        desk.pull.since = desk.pull.first_live = window.start
        control = desk.panel()["pull"]["since_pull"]
        assert (control["live_locks"], control["live_lock_contracts"]) == (1, 5)
        assert control["live_lock_cost_usd"] == pytest.approx(5 * .25 + .0656, abs=1e-4)  # price and taker fee
        assert control["windows_either_traded"] == 1 and control["live_pnl_either_usd"] == 1.4
    finally:
        desk.close()


def test_a_broken_comparison_never_stops_a_save_or_a_cancel(tmp_path: Path) -> None:
    """Review 11: the A/B is computed inside every save, including the one before each cancel; and the twin's own
    step runs before the loop's error handling. Neither may stop a real cancel."""
    desk, account, clock = two_bids(tmp_path)
    try:
        def broken(*args: Any) -> dict[str, Any]:
            raise RuntimeError("bad row")

        desk._pull_control = broken  # type: ignore[method-assign]
        desk._twin_unpulled = broken  # type: ignore[method-assign]
        desk._pull_ab = None
        swing(desk, clock, .0053)
        assert sorted(account.cancels) == ["order-3", "order-4"]
        assert desk.panel()["pull"]["error"] == "RuntimeError" and desk.panel()["pull"]["since_pull"] is None
    finally:
        desk.close()


# Rebreak findings (2026-10-14), each reproduced first on 703d942.

@pytest.mark.parametrize("pull", [False, True])
def test_a_cancel_that_keeps_failing_never_starves_the_order_list_read_or_the_lock(tmp_path: Path, pull: bool) -> None:
    """Major: a cancel whose DELETE keeps failing (500) after Kalshi already took the order down was sent again first
    thing in every step once its backoff ended; each failure set the backoff again, so the reconcile that would show
    the order gone never ran: no bid, fill or lock for as long as it failed (61ca112 read the order list 2.1 s later
    and locked the pair). Now a failed cancel goes out again only once an order list read since the failure still
    shows the order open. With the pull on, its reason ("pull") never passes, so it starved the same way."""
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra={**MAKERS, "speeddesk_kalshi_pull": pull})
    try:
        starter_bid_filled(desk, account, clock)
        run(desk, clock, .6)
        assert [(c["side"], c["price"], c["size"]) for c in account.creates[1:]] == [("down", .47, 5)]  # order-2
        cancel, list_orders = account.cancel, account.list_orders
        failed: list[float] = []
        reads: list[float] = []
        start = clock.now()

        def failing(order_id: str, *, ticker: str) -> dict[str, Any]:
            if order_id != "order-2":
                return cancel(order_id, ticker=ticker)
            failed.append(round(clock.now() - start, 1))
            account.orders[1].update(status="canceled", remaining_count_fp="0.00")  # Kalshi took it down anyway
            raise KalshiClientError("cancel", "result unconfirmed", status=500, uncertain=True)

        def reading(**kwargs: Any) -> list[dict[str, Any]]:
            reads.append(round(clock.now() - start, 1))
            return list_orders(**kwargs)

        account.cancel = failing  # type: ignore[method-assign]
        account.list_orders = reading  # type: ignore[method-assign]
        market(desk, clock, .485)  # the Down fair rises 1.5c: the reprice rule cancels the Down bid
        run(desk, clock, .3)
        assert failed == [0.0]
        market(desk, clock, .5)  # and comes straight back
        run(desk, clock, 30)
        [order_2] = [intent for intent in desk.intents.values() if intent.order_id == "order-2"]
        assert reads and reads[0] <= 3.0 and order_2.terminal and desk.errors == 0 and failed == [0.0]
        clock.advance(desk.book.windows[TICKER].end - 239 - clock.now())  # the lock period, Down ask 0.55
        market(desk, clock, .5)
        run(desk, clock, 6)
        assert [(c["side"], c["kind"], c["price"], c["size"]) for c in account.creates if c["kind"] == "take"] == [
            ("down", "take", .55, 5)]
    finally:
        desk.close()


def test_a_cancel_that_timed_out_but_went_through_is_not_sent_again(tmp_path: Path) -> None:
    """Minor: the first cancel timed out but Kalshi did cancel the order; the order list read after the backoff shows
    it, so no second DELETE goes out once the reason has passed (it went out, a 404, and cost a write)."""
    desk, account, clock = two_bids(tmp_path, speeddesk_kalshi_pull=False)
    try:
        cancel, seen = account.cancel, []

        def timing_out(order_id: str, *, ticker: str) -> dict[str, Any]:
            seen.append(order_id)
            cancel(order_id, ticker=ticker)
            if len(seen) == 1:
                raise KalshiClientError("cancel", "transport failure", uncertain=True, timed_out=True)
            return {}

        account.cancel = timing_out  # type: ignore[method-assign]
        market(desk, clock, .515)
        run(desk, clock, .3)
        market(desk, clock, .5)  # the reprice reason passes
        run(desk, clock, 8)
        assert seen == ["order-4", "order-3"] and desk.errors == 0 and len(account.creates) == 6
    finally:
        desk.close()


def _broken_twin_run(tmp_path: Path, hook: str | None) -> dict[str, Any]:
    """Two resting bids, then a 1.5c move: the old rule reprices both (twin ``cancel_order``), the pull holds the
    window (the twin's own bid there, sized with ``can_buy``), and after the hold the bot bids again (twin ``place``);
    every step advances the twin (``advance``). ``hook``: that practice-twin method raises throughout."""
    desk, account, clock = two_bids(tmp_path)
    try:
        if hook is not None:
            def broken(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("twin bug")

            setattr(desk.twin, hook, broken)
        market(desk, clock, .515, feed=False)  # the loop below hands the books over
        end, errors = clock.now() + 12, 0
        while clock.now() < end - 1e-9:
            for book in desk.snapshot().books.values():
                with contextlib.suppress(RuntimeError):  # a feed callback's error halts the companion; not tested here
                    desk.on_book(book)
            desk.on_tick(80000, clock.now(), clock.now())
            asyncio.run(desk.step())
            errors = max(errors, desk.errors)
            clock.advance(.3)
        return {"cancels": list(account.cancels), "errors": errors, "counts": dict(desk.loop_stats.counts),
                "creates": [(c["side"], c["kind"], c["price"], c["size"]) for c in account.creates]}
    finally:
        desk.close()


@pytest.mark.parametrize("hook", ["cancel_order", "can_buy", "place", "advance"])
def test_a_practice_twin_error_never_changes_the_real_cancels_or_bids(tmp_path: Path, hook: str) -> None:
    """Major: a twin error inside _cancel (before the real cancel was sent) stopped the real cancels, and one in
    _decide (the held window's or an owed side's twin bid) was taken for a Kalshi error and paused the real loop.
    Now each is counted in the status line and the real cancels, bids and error count are those of a healthy twin."""
    healthy = _broken_twin_run(tmp_path / "healthy", None)
    broken = _broken_twin_run(tmp_path / hook, hook)
    assert broken["cancels"] == healthy["cancels"] == ["order-4", "order-3"]
    assert broken["creates"] == healthy["creates"] and len(healthy["creates"]) == 6
    assert broken["errors"] == healthy["errors"] == 0
    assert any(name.endswith("_RuntimeError") for name in broken["counts"])
    assert not any(name.endswith("_RuntimeError") for name in healthy["counts"])


def test_a_practice_twin_error_never_stops_the_cancels_at_shutdown(tmp_path: Path) -> None:
    desk, account, _ = two_bids(tmp_path)
    try:
        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("twin bug")

        desk.twin.cancel_order = broken  # type: ignore[method-assign]
        desk.twin.cancel = broken  # type: ignore[method-assign]
        asyncio.run(desk.shutdown())
        assert sorted(account.cancels) == ["order-3", "order-4"] and desk.shutdown_done
    finally:
        desk.close()


def test_a_cancel_sent_again_after_its_reason_passed_leaves_the_twin_alone(tmp_path: Path) -> None:
    """Minor: the re-send of a failed cancel whose reason has passed did what a fresh real cancel does to the practice
    twin again, with the first reason; only the first ask does now."""
    desk, account, clock = two_bids(tmp_path, speeddesk_kalshi_pull=False)
    try:
        failed = _flaky_cancel(account)
        twin_cancels: list[str] = []
        twin_cancel = desk._twin_cancel

        def counted(intent: Any, reason: str) -> None:
            twin_cancels.append(intent.order_id)
            twin_cancel(intent, reason)

        desk._twin_cancel = counted  # type: ignore[method-assign]
        market(desk, clock, .515)
        run(desk, clock, .3)
        [first] = failed
        market(desk, clock, .5)
        run(desk, clock, 4)
        assert account.cancels.count(first) == 1 and not _resting(account, first)  # sent again
        assert sorted(twin_cancels) == ["order-3", "order-4"]
    finally:
        desk.close()


def test_the_window_open_at_the_first_go_live_is_in_neither_comparison(tmp_path: Path) -> None:
    """Minor: the window under way when the pull first went live already had pulls, so it is no part of the no-pull
    baseline (week_before); it started before the pull, so it is not in since_pull either."""
    desk, account, clock = two_bids(tmp_path)
    try:
        swing(desk, clock, .0053)
        assert account.cancels == ["order-4", "order-3"]  # pulled
        desk.book.settled[TICKER] = LiveSettlement(TICKER, "kalshi:x", clock.now(), True, 5, 5, 4.7, 0, 5, 5, 5,
                                                   .3, 0, .3)
        desk.twin.closed.append(Settlement(TICKER, clock.now(), True, 5, 5, 4.7, .05, 5, .25, 0, .25))
        window, panel = desk.book.windows[TICKER], desk.panel()["pull"]
        assert window.start < panel["first_live"] < window.end
        assert panel["week_before"]["windows_either_traded"] == panel["since_pull"]["windows_either_traded"] == 0
    finally:
        desk.close()


def test_a_pulls_logged_move_stops_at_the_lock_zone() -> None:
    """Minor: in nonstop chop a pull stays open to the close, and its one log line showed the close's swing to 0 or 1
    as its move; the move now grows only while the pull counts (before the lock zone)."""
    guard = PullGuard(PullRule(), now=100.0)
    guard.observe("w", .50, 100.0, count=True)
    guard.observe("w", .52, 100.5, count=True)
    guard.observe("w", .99, 101.0, count=False)  # in the lock zone
    [line] = guard.expire(200.0)
    assert line["move"] == .02 and line["held_until"] == 106.0

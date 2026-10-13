"""The bid pull (owner, 2026-10-13 ~20:15 UTC: "Pulling bids the instant price moves ... test with our current bot"),
on real money, with the practice twin keeping the rule without it as the live control. Offline: no account."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pytest
from test_speeddesk_live import TICKER, FakeAccount, fill_order, make_desk

from nightcrawler import pagestate
from nightcrawler.clock import FakeClock
from nightcrawler.config import ConfigError, Settings
from nightcrawler.speeddesk_kalshi_client import WRITES_PER_S
from nightcrawler.speeddesk_live import PULL_REASON, KalshiLiveDesk, LiveSnapshot
from nightcrawler.speeddesk_live_model import LiveSettlement
from nightcrawler.speeddesk_live_pull import PullGuard, PullRule, compare
from nightcrawler.speeddesk_model import (
    Book,
    Level,
    Settlement,
    Trade,
    fair_up,
    utc_day,
)

# The owner's current $10 / $20 caps (both stops at their defaults), and makers only, as live.
CAPS = {"speeddesk_kalshi_window_usd": 10.0, "speeddesk_kalshi_open_usd": 20.0}
MAKERS = {"speeddesk_take_edge": 1.0}
SIGMA = .001


def market(desk: KalshiLiveDesk, clock: FakeClock, up: float, *, ask: float = .55, feed: bool = True) -> None:
    """Fresh books (asks above both bids) and a Bitcoin print that puts the Up fair at ``up`` right now; ``feed``
    also hands the books to the desk, as the feeds do."""
    window = desk.book.windows[TICKER]
    bitcoin = 80000 * math.exp(NormalDist().inv_cdf(up) * SIGMA * math.sqrt(window.end - clock.now()))

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
        assert account.cancels == ["order-3", "order-4"]
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
        assert account.cancels == ["order-3", "order-4"]
        assert [event["reason"] for event in desk.latest_events
                if event["event"] == "speeddesk_live_cancel"] == ["reprice", "reprice"]
        run(desk, clock, 4)
        assert len(account.creates) == 4 and desk.pull.held(TICKER, clock.now())
        # The old rule cancelled the twin's copies too, then (without the pull) rebid at the new fair at once.
        assert not set(desk.twin.orders) & {3, 4} and set(desk.twin.orders) == desk.twin_kept
        assert sorted((order.side, order.price, order.size) for order in desk.twin.orders.values()) == [
            ("down", .45, 3), ("up", .48, 3)]
        assert desk.panel()["pull"]["bids_pulled_today"] == 0
    finally:
        desk.close()


def test_the_twin_does_not_pull_its_bids_stay_resting(tmp_path: Path) -> None:
    desk, account, clock = two_bids(tmp_path)
    try:
        twin_bids = {order_id: (order.side, order.price) for order_id, order in desk.twin.orders.items()}
        swing(desk, clock, .0053)
        assert account.cancels == ["order-3", "order-4"]
        assert {order_id: (order.side, order.price) for order_id, order in desk.twin.orders.items()} == twin_bids
        assert desk.twin_kept == set(twin_bids)
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
        assert account.cancels == ["order-3", "order-4"]
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
        assert account.cancels == ["order-3", "order-4"]  # one cancel per bid, nothing re-sent
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
                      "windows_either_traded": 3, "live_maker_fills": 3, "live_maker_contracts": 12,
                      "live_maker_fills_per_window": 1.0, "twin_maker_fills": 3, "twin_maker_contracts": 15,
                      "twin_maker_fills_per_window": 1.0}
    before = compare(starts, live, twin, [("old", 5)], [], start=0.0, end=5.0)
    assert before["windows_both_traded"] == 1 and before["live_minus_twin_usd"] == 18.0
    assert compare({}, {}, {}, [], [], start=0.0)["live_maker_fills_per_window"] is None


def test_the_panel_compares_real_and_twin_since_the_pull_went_live(tmp_path: Path) -> None:
    desk, _, clock = two_bids(tmp_path)
    try:
        window = desk.book.windows[TICKER]
        panel = desk.panel()["pull"]
        assert panel["since"] > window.start  # this window opened before the pull went live: it is the control
        assert panel["since_pull"]["windows_either_traded"] == 0
        assert panel["week_before"]["live_maker_fills"] == 0  # not settled yet
        # Settle the window by hand: the real pair made 0.30, the twin's (the same two fills, practice) 0.25.
        desk.book.settled[TICKER] = LiveSettlement(TICKER, "kalshi:x", clock.now(), True, 5, 5, 4.7, 0, 5, 5, 5,
                                                   .3, 0, .3)
        desk.twin.closed.append(Settlement(TICKER, clock.now(), True, 5, 5, 4.7, .05, 5, .25, 0, .25))
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
        bitcoin = 80000 * math.exp(NormalDist().inv_cdf(up) * SIGMA * math.sqrt(end - clock.now()))
        assert fair_up(bitcoin, 80000, SIGMA, end - clock.now()) == pytest.approx(up, abs=1e-9)

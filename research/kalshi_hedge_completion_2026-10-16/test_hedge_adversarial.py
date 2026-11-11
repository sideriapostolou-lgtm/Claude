"""Independent fake-only review: no client/network/venue credentials are used.

Run against the implementation source using an explicit PYTHONPATH. The seeded
first fill is a pre-existing obligation, not an alternative-fill profitability
simulation. These assertions cover boundaries rather than profits.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, make_desk

from nightcrawler.speeddesk_live import Intent, KalshiLiveDesk, LiveSnapshot
from nightcrawler.speeddesk_live_model import ActualFill
from nightcrawler.speeddesk_model import Book, Level, utc_day


@pytest.fixture(autouse=True)
def fixed_fair(monkeypatch: pytest.MonkeyPatch) -> None:
    # Includes the static stale-bid path, not merely the instance decision path.
    monkeypatch.setattr(KalshiLiveDesk, "_fair", staticmethod(lambda *_args: .8))


def view(desk: Any, clock: Any, *, up: tuple[Level, ...], down: tuple[Level, ...]) -> None:
    window = desk.book.windows[TICKER]

    def snapshot() -> LiveSnapshot:
        books = {(TICKER, side): Book(TICKER, side, (), asks, clock.now(), "review",
                                      source="rest", requested_at=clock.now())
                 for side, asks in (("up", up), ("down", down))}
        return LiveSnapshot((window,), books, 80000, clock.now(), .001, frozenset({TICKER}))

    desk.snapshot = snapshot


def seeded(tmp_path: Path, *, cap: str | None = None, filled: float = 5,
           window_budget: float = 5.0) -> tuple[Any, Any, Any]:
    caps = {"speeddesk_kalshi_window_usd": window_budget, "speeddesk_kalshi_open_usd": 10.0}
    if cap:
        caps[cap] = 3.0
    desk, account, clock = make_desk(tmp_path, caps=caps, extra={"speeddesk_kalshi_pull": False})
    # Fresh fair deliberately dislikes the missing side. A cost-capped pair
    # completion should not require the standalone directional edge.
    desk._fair = lambda *_args: .8
    view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 20),))
    asyncio.run(desk._ensure_client())
    asyncio.run(desk._startup())
    identity = "nc-speed-review-seed"
    desk.book.reserve_intent(TICKER, "up", "rest", .57, 5, clock.now(), identity, .8)
    desk.intents[identity] = Intent(identity, TICKER, "up", "rest", .57, 5, .8, clock.now(),
                                    order_id="seed", terminal=filled == 5)
    desk.book.record_fill(ActualFill("seed-fill", "seed", identity, TICKER, "up", .57,
                                     filled, 0, clock.now()))
    account.orders.append({"order_id": "seed", "client_order_id": identity, "ticker": TICKER,
                           "status": "executed" if filled == 5 else "resting",
                           "fill_count_fp": str(filled), "remaining_count_fp": str(5 - filled),
                           "initial_count_fp": "5", "outcome_side": "yes", "book_side": "bid",
                           "yes_price_dollars": ".57", "no_price_dollars": ".43"})
    account.executions.append({"fill_id": "seed-fill", "order_id": "seed", "ticker": TICKER,
                               "outcome_side": "yes", "book_side": "bid", "count_fp": str(filled),
                               "yes_price_dollars": ".57", "fee_cost": "0.0000", "ts": clock.now()})
    account.account_positions = [{"ticker": TICKER, "position_fp": str(filled)}]
    return desk, account, clock


def test_under_cap_early_ioc_despite_directional_fair(tmp_path: Path) -> None:
    desk, account, _ = seeded(tmp_path)
    try:
        asyncio.run(desk.step())
        assert [(row["side"], row["kind"], row["size"]) for row in account.creates] == [("down", "take", 5)]
        assert not next(row for row in desk.book.intents.values() if row.client_order_id != "nc-speed-review-seed").lock
    finally:
        desk.close()


@pytest.mark.parametrize("cap", ["speeddesk_kalshi_window_usd", "speeddesk_kalshi_open_usd"])
def test_early_ioc_keeps_ordinary_spend_limits(tmp_path: Path, cap: str) -> None:
    desk, account, _ = seeded(tmp_path, cap=cap)
    try:
        asyncio.run(desk.step())
        assert not account.creates
    finally:
        desk.close()


def test_early_ioc_never_exceeds_visible_whole_depth(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 2.9), Level(.6, 20)))
        asyncio.run(desk.step())
        takes = [row for row in account.creates if row["kind"] == "take"]
        assert len(takes) == 1 and takes[0]["size"] == 2
    finally:
        desk.close()


def test_early_ioc_does_not_consume_over_cap_ask(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.41, 20),))
        asyncio.run(desk.step())
        assert not [row for row in account.creates if row["kind"] == "take"]
    finally:
        desk.close()


def test_postjournal_shrinking_depth_stops_ioc(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    original = account.create_order

    def during_transport(**kwargs: Any) -> dict[str, Any]:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 1),))
        return original(**kwargs)

    account.create_order = during_transport
    try:
        asyncio.run(desk.step())
        assert not account.creates
        attempted = [row for row in desk.book.intents.values() if row.client_order_id != "nc-speed-review-seed"]
        assert attempted and all(not row.reservation_active for row in attempted)
    finally:
        desk.close()


def test_partial_starter_remainder_cancels_when_hedge_depth_disappears(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path, filled=2)
    try:
        view(desk, clock, up=(Level(.9, 20),), down=())
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["seed"]
        # A cancellation acknowledgement alone cannot release the risk model.
        assert desk.book.intents["nc-speed-review-seed"].reservation_active
        assert desk.book.intents["nc-speed-review-seed"].remaining == 3
    finally:
        desk.close()


def test_partial_starter_requires_depth_for_existing_and_remaining_exposure(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path, filled=2)
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 3),))
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["seed"]
        assert desk.book.intents["nc-speed-review-seed"].reservation_active
        assert desk.book.intents["nc-speed-review-seed"].remaining == 3
        assert desk.book.inventory[TICKER].up.shares == 2
    finally:
        desk.close()


def test_empty_opposite_book_blocks_that_first_side(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_pull": False})
    try:
        desk._fair = lambda *_args: .8
        view(desk, clock, up=(Level(.5, 20),), down=())
        asyncio.run(desk.step())
        assert not [row for row in account.creates if row["side"] == "up"]
    finally:
        desk.close()


def test_transport_rechecks_actual_balancing_classification(tmp_path: Path) -> None:
    desk, account, _ = seeded(tmp_path)
    original = account.create_order

    def during_transport(**kwargs: Any) -> dict[str, Any]:
        # Adversarial state injection at the trust boundary: it tests the
        # predicate, without claiming this is a reconstructed venue history.
        desk.book.inventory[TICKER].down.shares = 5
        desk.book.inventory[TICKER].down.cost = 2
        return original(**kwargs)

    account.create_order = during_transport
    try:
        asyncio.run(desk.step())
        assert not account.creates
    finally:
        desk.close()


def test_raw_crossing_maker_quote_can_become_valid_capped_hedge(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path, window_budget=10)
    try:
        desk.settings = replace(desk.settings, speeddesk_take_edge=1.0)
        desk._fair = lambda *_args: .35
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.6, 20),))
        asyncio.run(desk._decide())
        assert [(row["side"], row["kind"], row["price"]) for row in account.creates] == [("down", "rest", .42)]
    finally:
        desk.close()


def test_raw_crossing_first_entry_is_not_added_as_new_opportunity(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_pull": False,
                                                     "speeddesk_take_edge": 1.0})
    try:
        view(desk, clock, up=(Level(.7, 20),), down=(Level(.4, 20),))
        # Up's raw maker quote is .77 and crosses .70. A cap-adjusted .57
        # would be valid, but restoring the existing first-entry policy means
        # it cannot manufacture that new starter opportunity.
        asyncio.run(desk.step())
        assert not [row for row in account.creates if row["side"] == "up"]
    finally:
        desk.close()


def test_valid_maker_is_not_cancelled_for_unaffordable_ioc(tmp_path: Path) -> None:
    desk, account, _ = seeded(tmp_path, cap="speeddesk_kalshi_window_usd")
    try:
        window = desk.book.windows[TICKER]
        assert asyncio.run(desk._send(window, "down", "rest", .02, 5, .2))
        asyncio.run(desk._reconcile())
        asyncio.run(desk._complete_early())
        assert not account.cancels
    finally:
        desk.close()


def test_existing_money_stops_allow_only_capped_completion_without_reset(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        desk.book.realized_pnl = -10
        desk.book.day_pnl[utc_day(clock.now())] = -6
        desk.book.latch_bound_stops(clock.now())
        assert desk.book.halted and desk.book.day_latched(clock.now())
        before = (desk.book.realized_pnl, dict(desk.book.day_pnl), desk.book.stop_anchor,
                  set(desk.book.seen_resume_hashes), desk.book.limits)
        asyncio.run(desk.step())
        assert [(row["side"], row["kind"]) for row in account.creates] == [("down", "take")]
        assert desk.book.halted and desk.book.day_latched(clock.now())
        assert (desk.book.realized_pnl, dict(desk.book.day_pnl), desk.book.stop_anchor,
                set(desk.book.seen_resume_hashes), desk.book.limits) == before
    finally:
        desk.close()


def test_early_ioc_preserves_write_room_for_urgent_cancels(tmp_path: Path) -> None:
    desk, account, _ = seeded(tmp_path)
    try:
        desk.pull.rule = replace(desk.pull.rule, enabled=True)
        account.writes_last_second = lambda: 100
        asyncio.run(desk.step())
        assert not account.creates
    finally:
        desk.close()


@pytest.mark.parametrize("stage", ["decision", "admission", "transport"])
def test_early_ioc_never_bypasses_pull_hold(tmp_path: Path, stage: str) -> None:
    desk, account, clock = seeded(tmp_path)
    desk.pull.rule = replace(desk.pull.rule, enabled=True)

    def trigger() -> None:
        desk.pull.observe(TICKER, .5, clock.now() - .1, count=True)
        desk.pull.observe(TICKER, .52, clock.now(), count=True)
        assert desk.pull.held(TICKER, clock.now())

    try:
        if stage == "transport":
            original = account.create_order

            def during_transport(**kwargs: Any) -> dict[str, Any]:
                trigger()
                return original(**kwargs)

            account.create_order = during_transport
            asyncio.run(desk._decide())
        else:
            trigger()
            if stage == "admission":
                assert not asyncio.run(desk._send(desk.book.windows[TICKER], "down", "take", .4, 5, .2,
                                                  completion=True))
            else:
                asyncio.run(desk._decide())
        assert not account.creates
        assert desk.book.inventory[TICKER].down.shares == 0
        if stage == "transport":
            attempted = [item for identity, item in desk.book.intents.items() if identity != "nc-speed-review-seed"]
            assert attempted and all(item.status == "rejected" and not item.reservation_active for item in attempted)
            assert not any(item.uncertain for item in desk.intents.values())
    finally:
        desk.close()

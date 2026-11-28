"""Fake-only completion regressions; no client/network/venue credentials are used.

The first eleven cases were adapted from the independent review's
review_checks/test_hedge_adversarial.py. Additional implementation regressions
cover queue retention, entry races, own-liquidity removal and persistence.

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
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import TICKER, make_desk, reopen

from nightcrawler.speeddesk_kalshi_client import WRITES_PER_S
from nightcrawler.speeddesk_live import (
    STATE_KEY,
    Intent,
    KalshiLiveDesk,
    LiveSnapshot,
    durable_state,
)
from nightcrawler.speeddesk_live_completion import external_asks
from nightcrawler.speeddesk_live_model import ActualFill
from nightcrawler.speeddesk_live_pull import PullGuard, PullRule
from nightcrawler.speeddesk_model import Book, Level


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


def test_partial_starter_depth_covers_filled_plus_remaining(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path, filled=2)
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 3),))
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["seed"]
        assert desk.book.intents["nc-speed-review-seed"].reserved > 0
    finally:
        desk.close()


def test_historical_first_price_is_lowered_for_fee_capped_visible_hedge(tmp_path: Path) -> None:
    """Prior entry sizing mechanism only; current production forbids first legs."""
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_kalshi_pull": False, "speeddesk_take_edge": 1.0})
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 20),))
        asyncio.run(desk.step())
        assert [(row["side"], row["price"]) for row in account.creates] == [("up", .57)]
        assert .57 + desk.book.unit_reserve(TICKER, .4, "take") == pytest.approx(.99)
    finally:
        desk.close()


def test_postjournal_opposite_depth_disappears_before_starter_send(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, extra={"speeddesk_kalshi_pull": False, "speeddesk_take_edge": 1.0})
    original = account.create_order
    try:
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.4, 20),))

        def vanished(**kwargs: Any) -> dict[str, Any]:
            view(desk, clock, up=(Level(.9, 20),), down=())
            return original(**kwargs)

        account.create_order = vanished
        asyncio.run(desk.step())
        assert not account.creates
        assert all(not item.reservation_active for item in desk.book.intents.values())
    finally:
        desk.close()


def test_terminal_original_own_quote_is_not_external_depth(tmp_path: Path) -> None:
    desk, _, clock = seeded(tmp_path)
    try:
        # The first own Up bid reflects at a Down ask of 43c; a public snapshot may still contain it.
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.43, 5), Level(.44, 2)))
        assert external_asks(desk.book, TICKER, "down", desk.snapshot().books[(TICKER, "down")]) == [(.44, 2)]
    finally:
        desk.close()


def test_capped_maker_keeps_queue_after_favorable_fair_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk, account, clock = seeded(tmp_path, window_budget=10)
    try:
        desk.settings = replace(desk.settings, speeddesk_take_edge=1.0)
        desk._fair = lambda *_args: .35
        monkeypatch.setattr(KalshiLiveDesk, "_fair", staticmethod(lambda *_args: .35))
        view(desk, clock, up=(Level(.9, 20),), down=(Level(.6, 20),))
        asyncio.run(desk._decide())
        asyncio.run(desk._reconcile())
        desk._fair = lambda *_args: .30
        monkeypatch.setattr(KalshiLiveDesk, "_fair", staticmethod(lambda *_args: .30))
        asyncio.run(desk._cancel_unsafe())
        asyncio.run(desk._decide())
        assert not account.cancels
        assert [(row["side"], row["price"]) for row in account.creates] == [("down", .42)]
    finally:
        desk.close()


def test_completion_classification_survives_restart(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    asyncio.run(desk.step())
    desk.checkpoint(durable=True)
    identity = account.creates[0]["client_order_id"]
    assert desk.intents[identity].completion and desk.book.intents[identity].completion
    desk.close()
    restored = reopen(tmp_path, desk, account, clock)
    try:
        assert restored.intents[identity].completion and restored.book.intents[identity].completion
        assert not restored.fatal_reason
        assert restored.book.intents[identity].reservation_active
    finally:
        restored.close()


def test_completion_marker_is_durable_before_send(tmp_path: Path) -> None:
    desk, account, _ = seeded(tmp_path)
    original = account.create_order

    def durable(**kwargs: Any) -> dict[str, Any]:
        saved = durable_state(desk.ledger)
        assert saved is not None
        identity = kwargs["client_order_id"]
        assert saved["intents"][identity]["completion"] is True
        assert saved["book"]["intents"][identity]["completion"] is True
        return original(**kwargs)

    account.create_order = durable
    try:
        asyncio.run(desk.step())
        assert account.creates
    finally:
        desk.close()


def test_completion_marker_mismatch_halts_restore(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    asyncio.run(desk.step())
    desk.checkpoint(durable=True)
    identity = account.creates[0]["client_order_id"]
    saved = desk.ledger.get_kv(STATE_KEY)
    saved["intents"][identity]["completion"] = False
    desk.ledger.set_kv(STATE_KEY, saved)
    desk.close()
    with pytest.raises(ValueError, match="reserved terms"):
        reopen(tmp_path, desk, account, clock)


@pytest.mark.parametrize("change", ["cash_age", "paper", "fee", "clip", "pair_cap", "pull"])
def test_completion_transport_keeps_safety_checks(tmp_path: Path, change: str) -> None:
    desk, account, clock = seeded(tmp_path)
    original = account.create_order

    def changed(**kwargs: Any) -> dict[str, Any]:
        if change == "cash_age":
            desk.book.cash_at = clock.now() - 6
        elif change == "paper":
            desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
        elif change == "fee":
            desk.book.windows[TICKER] = replace(desk.book.windows[TICKER], taker_coefficient=.2)
        elif change == "clip":
            limits = desk.book.limits_for(TICKER)
            desk.book.window_limits = lambda _start: replace(limits, clip=1)
        elif change == "pull":
            desk.pull = PullGuard(PullRule.from_settings(replace(desk.settings, speeddesk_kalshi_pull=True)), clock.now())
            desk.pull.observe(TICKER, .5, clock.now() - .1, count=True)
            desk.pull.observe(TICKER, .52, clock.now(), count=True)
        else:
            limits = desk.book.limits_for(TICKER)
            desk.book.window_limits = lambda _start: replace(limits, pair_cap=.98)
        return original(**kwargs)

    account.create_order = changed
    try:
        asyncio.run(desk.step())
        assert not account.creates
        assert desk.book.inventory[TICKER].down.shares == 0
        assert desk.twin.inventory[TICKER].down.shares == 0
        attempts = [item for key, item in desk.book.intents.items() if key != "nc-speed-review-seed"]
        assert attempts and all(not item.reservation_active for item in attempts)
        assert not any(item.uncertain for key, item in desk.intents.items() if key != "nc-speed-review-seed")
        assert not desk.fatal_reason and desk.errors == 0
        assert any(event.get("event") == "speeddesk_live_order"
                   and event.get("state") == "not sent; prices moved before send" for event in desk.latest_events)
    finally:
        desk.close()


def test_early_completion_preserves_write_room_for_cancels(tmp_path: Path) -> None:
    desk, account, clock = seeded(tmp_path)
    try:
        desk.pull = PullGuard(PullRule.from_settings(replace(desk.settings, speeddesk_kalshi_pull=True)), clock.now())
        account.writes_last_second = lambda: WRITES_PER_S - 2
        asyncio.run(desk._complete_early())
        assert not account.creates
        assert desk.book.inventory[TICKER].down.shares == 0
    finally:
        desk.close()

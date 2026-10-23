"""Independent stop-fix controller regressions: fake venue executions, no network."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import pytest
from test_speeddesk_live import TICKER, FakeAccount, fill_order, make_desk, reopen
from test_speeddesk_live_pull import CAPS, MAKERS, market

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_live import Intent, KalshiLiveDesk
from nightcrawler.speeddesk_live_model import ActualFill, LiveIntent
from nightcrawler.speeddesk_model import utc_day

Stop = Literal["day", "total"]


def _filled_starter(tmp_path: Path) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    market(desk, clock, .5, ask=.50)
    asyncio.run(desk.step())
    assert not account.creates  # Current production policy cannot create a new first leg.
    # Existing owned execution from before containment: seed its original intent and venue records.
    # All hedge admission, transport, cancellation and stop behavior below uses the production desk.
    identity = "nc-speed-review-existing-starter"
    desk.intents[identity] = Intent(identity, TICKER, "up", "rest", .47, 5, .5, clock.now(),
                                    order_id="order-1", terminal=True)
    desk.book.intents[identity] = LiveIntent(identity, TICKER, "up", "rest", .47, 5, clock.now(), .47,
                                           order_id="order-1")
    desk.book.bootstrap_order[TICKER] = identity
    account.creates.append({"client_order_id": identity, "ticker": TICKER, "side": "up",
                            "kind": "rest", "price": .47, "size": 5})
    account.orders.append({"client_order_id": identity, "order_id": "order-1", "ticker": TICKER,
                           "status": "resting", "initial_count_fp": "5.00", "fill_count_fp": "0.00",
                           "remaining_count_fp": "5.00", "outcome_side": "yes", "book_side": "bid",
                           "yes_price_dollars": ".47", "no_price_dollars": ".53"})
    clock.advance(.3)
    fill_order(account, clock, 0, side="up", price=.47, size=5)
    account.executions[-1]["fee_cost"] = "0.0000"
    assert desk.book.record_fill(ActualFill("fill-0", "order-1", identity, TICKER, "up", .47, 5, 0,
                                           clock.now()))
    account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
    market(desk, clock, .5, starter_ask=.50)
    asyncio.run(desk._reconcile())
    assert desk.book.inventory[TICKER].up.shares == 5
    assert desk.book.inventory[TICKER].down.shares == 0
    assert not desk.book.integrity_error
    return desk, account, clock


def _stop(desk: KalshiLiveDesk, clock: FakeClock, kind: Stop) -> None:
    # Move the reset anchor to model loss since an earlier reset while leaving the fake settlement ledger
    # internally consistent. The actual current-window holdings still come only from account executions.
    if kind == "total":
        desk.book.stop_anchor = 9.94
    else:
        desk.book.day_anchor[utc_day(clock.now())] = 5.94
    desk._watch_stops()
    assert desk.book.halted if kind == "total" else desk.book.day_latched(clock.now())


def _hedge(tmp_path: Path) -> tuple[KalshiLiveDesk, FakeAccount, FakeClock]:
    desk, account, clock = _filled_starter(tmp_path)
    asyncio.run(desk.step())
    assert [(item["side"], item["size"]) for item in account.creates] == [("up", 5), ("down", 5)]
    return desk, account, clock


@pytest.mark.parametrize("stop", ["day", "total"])
def test_financial_latch_preserves_a_resting_hedge_of_real_fills(tmp_path: Path, stop: Stop) -> None:
    desk, account, clock = _hedge(tmp_path)
    try:
        _stop(desk, clock, stop)
        asyncio.run(desk.step())
        assert not account.cancels
        assert len(account.creates) == 2
        assert desk.book.reserved_usd == pytest.approx(2.35)
        assert desk.book.at_risk_usd == pytest.approx(2.35)
        panel = desk.panel()
        assert panel["mode"] == "live" and panel["real_orders_available"]
        assert "only completing" in panel["waiting"]
    finally:
        desk.close()


@pytest.mark.parametrize("stop", ["day", "total"])
def test_a_latched_desk_can_send_only_the_light_side_from_real_inventory(tmp_path: Path, stop: Stop) -> None:
    desk, account, clock = _filled_starter(tmp_path)
    try:
        _stop(desk, clock, stop)
        assert not asyncio.run(desk._send(desk.book.windows[TICKER], "up", "rest", .47, 1, .5))
        assert len(account.creates) == 1
        asyncio.run(desk.step())
        assert [(item["side"], item["price"], item["size"]) for item in account.creates] == [
            ("up", .47, 5), ("down", .47, 5)]
        assert not account.cancels
    finally:
        desk.close()


@pytest.mark.parametrize("stop", ["day", "total"])
@pytest.mark.parametrize("trigger", ["paper", "stale", "integrity", "pull", "cutoff", "errors", "shutdown"])
def test_financial_hedge_exemption_never_bypasses_other_cancels(
    tmp_path: Path, stop: Stop, trigger: str,
) -> None:
    desk, account, clock = _hedge(tmp_path)
    try:
        _stop(desk, clock, stop)
        if trigger == "paper":
            desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
        elif trigger == "stale":
            snapshot = replace(desk.snapshot(), bitcoin_at=clock.now() - 3.01)
            desk.snapshot = lambda: snapshot
        elif trigger == "integrity":
            desk.book.integrity_error = "review_forced_integrity_error"
        elif trigger == "pull":
            market(desk, clock, .52)
        elif trigger == "cutoff":
            clock.advance(desk.book.windows[TICKER].end - desk.book.limits.lock_s - clock.now())
            market(desk, clock, .5)
        elif trigger == "errors":
            desk.errors = 3
        if trigger == "shutdown":
            asyncio.run(desk.shutdown())
        else:
            asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["order-2"]
        assert len(account.creates) == 2
    finally:
        desk.close()


@pytest.mark.parametrize("stop", ["day", "total"])
def test_partial_actual_hedge_fill_leaves_only_the_unpaired_quantity_exempt(tmp_path: Path, stop: Stop) -> None:
    desk, account, clock = _hedge(tmp_path)
    try:
        _stop(desk, clock, stop)
        account.orders[1].update(fill_count_fp="2.25", remaining_count_fp="2.75")
        account.executions.append({"fill_id": "review-partial-hedge", "order_id": "order-2", "ticker": TICKER,
                                   "outcome_side": "no", "book_side": "ask", "count_fp": "2.25",
                                   "no_price_dollars": ".47", "fee_cost": "0.0000", "ts": clock.now()})
        account.account_positions = [{"ticker": TICKER, "position_fp": "2.75"}]
        asyncio.run(desk._reconcile())
        hedge_id = account.creates[1]["client_order_id"]
        assert desk.book.inventory[TICKER].down.shares == 2.25
        assert desk.book.intents[hedge_id].remaining == 2.75
        assert desk.book.strictly_balancing_intent(hedge_id)
        asyncio.run(desk._cancel_unsafe())
        assert not account.cancels
        assert desk.book.reserved_usd == pytest.approx(2.75 * .47)
    finally:
        desk.close()


def _competing_reservation(desk: KalshiLiveDesk, source_id: str, *, uncertain: bool = False) -> str:
    """A legacy concurrent reservation must remain a liability even without a venue order id."""
    source = desk.book.intents[source_id]
    other = source_id + "-review-competing"
    desk.book.intents[other] = replace(source, client_order_id=other, size=1, filled_size=0,
                                      reported_filled_size=0, venue_remaining_size=None, order_id=None,
                                      uncertainty="create_timeout" if uncertain else None)
    desk.intents[other] = replace(desk.intents[source_id], client_order_id=other, size=1, order_id=None,
                                 uncertain=uncertain)
    return other


def test_presend_rechecks_aggregate_remaining_hedges_under_a_latched_stop(tmp_path: Path) -> None:
    desk, account, clock = _filled_starter(tmp_path)
    original = account.create_order

    def add_competitor_before_transport_guard(**kwargs: Any) -> dict[str, Any]:
        _competing_reservation(desk, kwargs["client_order_id"])
        return original(**kwargs)

    try:
        _stop(desk, clock, "total")
        account.create_order = add_competitor_before_transport_guard
        asyncio.run(desk.step())
        # Decision-time reservation passed; another same-side liability appeared before the transport guard.
        # Five real unpaired shares cannot exempt six remaining hedge contracts.
        assert len(account.creates) == 1
        assert any("competing" in key for key in desk.book.intents)
        assert not desk.book.integrity_error
    finally:
        desk.close()


@pytest.mark.parametrize("uncertain", [False, True])
def test_excess_competing_reservation_removes_resting_hedge_stop_exemption(
    tmp_path: Path, uncertain: bool,
) -> None:
    desk, account, clock = _hedge(tmp_path)
    try:
        _stop(desk, clock, "total")
        hedge_id = account.creates[1]["client_order_id"]
        _competing_reservation(desk, hedge_id, uncertain=uncertain)
        assert not desk.book.strictly_balancing_intent(hedge_id)
        asyncio.run(desk._cancel_unsafe())
        assert "order-2" in account.cancels
        assert len(account.creates) == 2
    finally:
        desk.close()


def test_startup_still_cancels_a_saved_financially_exempt_hedge(tmp_path: Path) -> None:
    desk, account, clock = _hedge(tmp_path)
    _stop(desk, clock, "total")
    desk.checkpoint(durable=True)
    desk = reopen(tmp_path, desk, account, clock, caps=CAPS)
    try:
        asyncio.run(desk.step())
        assert "order-2" in account.cancels
        assert desk.book.halted
    finally:
        desk.close()


@pytest.mark.parametrize("stop", ["day", "total"])
def test_stop_receipt_is_durable_once_and_not_repeated_after_restarts(tmp_path: Path, stop: Stop) -> None:
    desk, account, clock = make_desk(tmp_path, caps=CAPS, extra=MAKERS)
    try:
        _stop(desk, clock, stop)
        for _ in range(3):
            desk._watch_stops()
            desk.checkpoint(durable=True)
            receipts = [receipt.payload for receipt in desk.ledger.iter_receipts()
                        if receipt.kind == "speeddesk_live_stop" and receipt.payload.get("stop") == stop]
            assert len(receipts) == 1
            desk = reopen(tmp_path, desk, account, clock, caps=CAPS)
        desk.checkpoint(durable=True)
        assert len([receipt for receipt in desk.ledger.iter_receipts()
                    if receipt.kind == "speeddesk_live_stop" and receipt.payload.get("stop") == stop]) == 1
    finally:
        desk.close()

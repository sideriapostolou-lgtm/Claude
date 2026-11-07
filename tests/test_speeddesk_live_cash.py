"""Historical admission fixtures exercise prior entry mechanics; they do not establish current production admission.

Shard funding and durable funding refusals, with offline account fakes only."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_kalshi import SERIES, START, market
from test_speeddesk_live import TICKER, at_lock_time, make_desk, reopen
from test_speeddesk_live_model import WINDOW, actual_fill, make_book, reserve
from test_speeddesk_live_safety import SimulatedCrash

from nightcrawler.speeddesk_kalshi import parse_window
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live import JOURNAL_KEY, STATE_KEY, Intent
from nightcrawler.speeddesk_live_cash import ShardFunding, primary_balances
from nightcrawler.speeddesk_live_model import ActualFill, LiveRiskBook


def row(shard: Any = 2, cash: Any = "25.0000", account: Any = 0) -> dict[str, Any]:
    return {"subaccount_number": account, "exchange_index": shard, "balance": cash, "updated_ts": 0}


@pytest.mark.parametrize("shard", [0, 2, 7])
def test_market_route_is_preserved_without_category_inference(shard: int) -> None:
    window = parse_window({**market(), "exchange_index": shard}, SERIES, START)
    assert window is not None and window.exchange_index == shard


@pytest.mark.parametrize("shard", [None, True, -1, "2", 2.0, float("nan")])
def test_invalid_market_route_remains_unknown_for_practice(shard: Any) -> None:
    window = parse_window({**market(), "exchange_index": shard}, SERIES, START)
    assert window is not None and window.exchange_index is None


@pytest.mark.parametrize("rows", [None, {}, [None], [{}], [row(shard=None)], [row(shard=True)],
                                  [row(shard=-1)], [row(shard="2")], [row(account=True)],
                                  [row(account=-1)], [row(account=64)], [row(cash=2500)],
                                  [row(cash=25.0)], [row(cash=True)], [row(cash="-0.01")],
                                  [row(cash="nan")], [row(cash="Infinity")], [row(cash="2e1")],
                                  [row(cash="0.0000001")], [row(), row(cash="1.0000")]])
def test_unknown_invalid_duplicates_and_wrong_units_fail_closed(rows: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        primary_balances(rows)


def test_exact_cash_uses_only_primary_subaccount_and_usd_strings() -> None:
    assert primary_balances([row(0, "20.0000"), row(2, "0.121900"), row(2, "99.0000", 1)]) == {
        0: 20.0, 2: .1219}
    assert primary_balances([]) == {}
    assert primary_balances([row(account=1)]) == {}


@pytest.mark.parametrize("rows", [[], [row(0)], [row(2, "0.0000")], [row(account=1)]])
def test_aggregate_funded_does_not_fund_empty_or_missing_primary_shard(tmp_path: Path, rows: Any) -> None:
    desk, account, _ = make_historical_desk(tmp_path)
    account.subaccount_balances = lambda: rows  # type: ignore[method-assign]
    try:
        asyncio.run(desk.step())
        assert account.creates == []
        panel = desk.panel()
        assert panel["cash_total_usd"] == 25.0
        assert panel["cash_usd"] == 25.0
        assert not panel["trading_now"]
        assert panel["shard_funding"]["refusal"]["exchange_index"] == 2
        assert panel["shard_funding"]["refusal"]["code"] in {"shard_cash_unknown", "shard_cash_budget"}
    finally:
        desk.close()


def test_failed_new_snapshot_invalidates_previous_shard_cash() -> None:
    cash = ShardFunding()
    cash.update([row()], 1010)
    with pytest.raises(ValueError):
        cash.update([row(cash=True)], 1011)
    assert cash.at is None and cash.balances == {} and cash.error == "shard_cash_invalid"


def test_reservations_partial_fills_fees_and_shards_cannot_share_funding() -> None:
    book = make_book()
    first = book.windows[WINDOW]
    first.exchange_index = 2
    second = replace(first, slug="KXBTC15M-OTHER", exchange_index=0)
    book.add_window(second)
    cash = ShardFunding()
    cash.update([row(2, "1.0000"), row(0, "5.0000")], 1010)
    order = reserve(book, size=2)
    reserve(book, window=second.slug, size=2, name="other")
    reserved = order.reserved
    assert cash.check(first, book, 1010, cost=1 - reserved) == ""
    assert cash.check(first, book, 1010, cost=1 - reserved + .0001) == "shard_cash_budget"
    # A requested cancel continues to reserve; the cash read's old mutation timestamp is irrelevant.
    book.request_cancel(order.client_order_id)
    assert cash.check(first, book, 1010, cost=.2) == "shard_cash_budget"
    fill = actual_fill(book, order, size=1, fee=.01)
    required = 1 - order.reserved - fill.price - fill.fee_usd
    assert cash.check(first, book, 1011, cost=required) == ""
    assert cash.check(first, book, 1011, cost=required + .0001) == "shard_cash_budget"
    assert cash.check(second, book, 1011, cost=3) == ""
    assert cash.check(first, book, 1016) == "shard_cash_stale"
    # Exact fresh account cash replaces old debits only after a complete balance refresh.
    book.update_cash(5.59, 1011)
    cash.update([row(2, "0.5900"), row(0, "5.0000")], 1011)
    assert not book.cash_debits_by_window
    assert cash.check(first, book, 1011, cost=.17) == ""


@pytest.mark.parametrize("part", ["reservation", "debit"])
def test_unknown_commitment_route_cannot_be_charged_to_another_shard(part: str) -> None:
    book = make_book()
    first = book.windows[WINDOW]
    second = replace(first, slug="KXBTC15M-OTHER", exchange_index=2)
    book.add_window(second)
    cash = ShardFunding()
    cash.update([row()], 1010)
    intent = reserve(book)
    if part == "debit":
        actual_fill(book, intent)
    assert cash.check(second, book, 1011, cost=.1) == f"{part}_shard_unknown"


def test_foreign_resting_orders_survive_recent_scans_until_terminal_evidence() -> None:
    cash, book = ShardFunding(), make_book()
    book.windows[WINDOW].exchange_index = 2
    cash.update([row()], 1010)
    foreign = {"order_id": "owner", "client_order_id": "owner", "ticker": "OTHER-SERIES", "status": "resting"}
    cash.orders([foreign], book, full=True)
    cash.orders([], book, full=False)
    cash.orders([{**foreign, "status": "unknown"}], book, full=False)
    assert cash.check(book.windows[WINDOW], book, 1010) == "external_resting_funding_unknown"
    cash.orders([{**foreign, "status": "canceled"}], book, full=False)
    assert cash.check(book.windows[WINDOW], book, 1010) == ""


def test_new_foreign_rest_between_order_reads_blocks_creation(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path)
    original = account.list_orders
    reads = 0

    def orders(**kwargs: Any) -> list[dict[str, Any]]:
        nonlocal reads
        reads += 1
        return original(**kwargs) + ([{"order_id": "owner", "status": "resting", "ticker": "OTHER-SERIES"}]
                                    if reads >= 2 else [])

    account.list_orders = orders  # type: ignore[method-assign]
    try:
        asyncio.run(desk.step())
        assert not account.creates
        assert desk.panel()["shard_funding"]["external_resting_orders"] == 1
    finally:
        desk.close()


def test_funding_refusal_survives_successful_reconciles_and_restart(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "request rejected", status=400,
                                            code="insufficient_balance")
    try:
        asyncio.run(desk.step())
        until = clock.now() + 60
        assert len(account.creates) == 1 and desk.create_cooldown_until == until
        state = desk.ledger.get_kv(STATE_KEY)
        assert state["create_funding_cooldown"] == {"until": until, "refusals": 1}
        assert all(item["terminal"] for item in state["intents"].values())
        assert not desk.ledger.get_kv(JOURNAL_KEY)["intents"]
        for _ in range(5):
            clock.advance(1)
            asyncio.run(desk.step())
        assert desk.errors == 0 and len(account.creates) == 1
        assert desk.create_cooldown_until == until and not desk.panel()["trading_now"]
        desk = reopen(tmp_path, desk, account, clock)
        assert desk.create_cooldown_until == until and desk.insufficient_balance_refusals == 1
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        assert not asyncio.run(desk._send_lock(desk.book.windows[TICKER], "down", .4, 1))
    finally:
        desk.close()


def test_repeated_funding_refusals_escalate_to_five_minutes(tmp_path: Path) -> None:
    from test_speeddesk_live_reads import view

    desk, account, clock = make_historical_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "request rejected", status=400,
                                            code="insufficient_balance")
    try:
        window = desk.book.windows[TICKER]
        for delay in (60, 120, 240, 300):
            desk.snapshot = lambda: view(clock, window)  # type: ignore[method-assign]
            asyncio.run(desk.step())
            assert desk.create_cooldown_until == clock.now() + delay
            clock.advance(delay)
        assert len(account.creates) == 4
    finally:
        desk.close()


def test_cooldown_does_not_starve_unsafe_cancellation_or_account_reads(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        desk.create_cooldown_until = clock.now() + 300
        reads = account.reads
        clock.advance(4)  # stale market data must cancel even during create cooldown
        asyncio.run(desk.step())
        assert account.cancels and account.reads > reads
        assert len(account.creates) == 1
        assert desk.create_cooldown_until > clock.now()
    finally:
        desk.close()


@pytest.mark.parametrize("lock", [False, True])
def test_final_guard_rechecks_cash_and_cooldown_after_transport_wait(tmp_path: Path, lock: bool) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        desk.client = account
        # An actual filled position makes this a currently permitted reduction.
        # Seed it directly so the production desk never needs historical admission.
        held_side = "up" if lock else "down"
        desk.book.update_cash(account.cash, clock.now())
        desk.book.reserve_intent(TICKER, held_side, "rest", .2, 5, clock.now(), "nc-speed-held", .5)
        assert desk.book.record_fill(ActualFill("held-fill", "held-order", "nc-speed-held", TICKER,
                                                held_side, .2, 5, 0, clock.now()))
        desk.intents["nc-speed-held"] = Intent("nc-speed-held", TICKER, held_side, "rest", .2, 5, .5,
                                                clock.now(), order_id="held-order", terminal=True)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00" if lock else "-5.00"}]
        if lock:
            at_lock_time(desk, clock, up_ask=.2, down_ask=.8)
        asyncio.run(desk._reconcile())
        desk.startup_done = True
        intent_id = "nc-speed-guard"
        side, price = ("down", .8) if lock else ("up", .4)
        desk.book.reserve_intent(TICKER, side, "take", price, 1, clock.now(), intent_id, .9, lock=lock)
        desk.intents[intent_id] = Intent(intent_id, TICKER, side, "take", price, 1, .9, clock.now(), lock=lock)
        desk.account_at = clock.now()
        desk.funding.update([row()], clock.now())
        assert desk._send_guard(intent_id)
        desk.create_cooldown_until = clock.now() + 60
        assert not desk._send_guard(intent_id)
        desk.create_cooldown_until = 0
        desk.funding.update([row(cash="0.0000")], clock.now())
        assert not desk._send_guard(intent_id)
    finally:
        desk.close()


def test_unknown_create_keeps_reservation_without_retry_or_funding_classification(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True,
                                            code="insufficient_balance")
    try:
        asyncio.run(desk.step())
        intent = next(iter(desk.intents.values()))
        assert intent.uncertain and desk.book.intents[intent.client_order_id].reservation_active
        assert desk.create_cooldown_until == 0 and desk.insufficient_balance_refusals == 0
        clock.advance(3)
        asyncio.run(desk.step())
        assert len(account.creates) == 1
    finally:
        desk.close()


def test_legacy_window_metadata_needs_fresh_exact_market_record(tmp_path: Path) -> None:
    desk, _, clock = make_desk(tmp_path)
    try:
        state = desk.book.to_state()
        assert "exchange_index" not in state["windows"][TICKER]
        desk.book = LiveRiskBook.from_state(state, desk.book.limits)
        old = desk.book.windows[TICKER]
        assert old.exchange_index is None
        desk.funding.update([row()], clock.now())
        assert desk.funding.check(old, desk.book, clock.now()) == "shard_cash_unknown"
        desk.on_windows([replace(old, exchange_index=2)])
        assert desk.book.windows[TICKER].exchange_index == 2
        assert desk.funding.check(old, desk.book, clock.now()) == ""
    finally:
        desk.close()


def test_paper_never_constructs_client_for_shard_balances(tmp_path: Path) -> None:
    desk, _, _ = make_desk(tmp_path, mode="paper")
    try:
        desk.client_factory = lambda: pytest.fail("practice touched trading client")
        asyncio.run(desk.step())
        assert desk.client is None and desk.funding.at is None
    finally:
        desk.close()


@pytest.mark.parametrize("after_commit", [False, True])
def test_crash_at_refusal_checkpoint_restores_reservation_or_durable_cooldown(
    tmp_path: Path, after_commit: bool,
) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "request rejected", status=400,
                                            code="insufficient_balance")
    checkpoint = desk.checkpoint

    def crash(durable: bool = False) -> None:
        if desk.insufficient_balance_refusals:
            if after_commit:
                checkpoint(durable=durable)
            raise SimulatedCrash
        checkpoint(durable=durable)

    desk.checkpoint = crash  # type: ignore[method-assign]
    try:
        with pytest.raises(SimulatedCrash):
            asyncio.run(desk.step())
        desk = reopen(tmp_path, desk, account, clock)
        intent = next(iter(desk.intents.values()))
        reserved = desk.book.intents[intent.client_order_id]
        if after_commit:
            assert intent.terminal and not reserved.reservation_active
            assert desk.create_cooldown_until == clock.now() + 60
        else:
            assert not intent.terminal and reserved.reservation_active
        asyncio.run(desk.step())
        assert len(account.creates) == 1
    finally:
        desk.close()


def test_persisted_live_practice_and_journal_windows_are_rollback_readable(tmp_path: Path) -> None:
    desk, account, _ = make_historical_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert account.creates
        assert all("exchange_index" not in window for window in desk.book.to_state()["windows"].values())
        assert all("exchange_index" not in window for window in desk.twin.to_state()["windows"].values())
        desk._journal_intent(next(iter(desk.intents.values())), desk.book.windows[TICKER])
        journal = desk.ledger.get_kv(JOURNAL_KEY)
        assert journal["intents"]
        assert all("exchange_index" not in item["window"] for item in journal["intents"].values())
    finally:
        desk.close()

"""Historical admission fixtures exercise prior entry mechanics; they do not establish current production admission.

Observation hooks cannot become a second trading or accounting path.

Real fills come from the existing fake account and actual reconciliation. No
network, credentials, hypothetical orders or production records are involved.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import TICKER, fill_order, make_desk
from test_speeddesk_runtime import LocalFeeds

from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_live import QUIET_RECORDS, KalshiLiveDesk
from nightcrawler.speeddesk_markouts import FillMarkouts
from nightcrawler.speeddesk_model import Book, Decision, Level, Side


class Observer:
    """A diagnostic spy with no account, order, risk or ledger capabilities."""

    def __init__(self, broken: str = "") -> None:
        self.broken = broken
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, method: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append((method, args, kwargs))
        if method == self.broken:
            raise RuntimeError("synthetic observation failure")
        return []

    def observe_fill(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("observe_fill", *args, **kwargs)

    def on_book(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("on_book", *args, **kwargs)

    def expire(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("expire", *args, **kwargs)

    def needs_book(self, *args: Any) -> bool:
        self._call("needs_book", *args)
        return True

    def status(self) -> dict[str, Any]:
        self._call("status")
        return {"mode": "diagnostic", "enabled": True, "realized_pnl": False}


def install(desk: KalshiLiveDesk, observer: Observer) -> None:
    desk.markouts = observer  # type: ignore[assignment]


def financial_state(desk: KalshiLiveDesk) -> tuple[Any, ...]:
    return (desk.book.to_state(), desk.cash_usd, desk.cash_at, desk.errors,
            desk.authenticated, desk.auth_failed, desk.fatal_reason, desk.reason,
            asdict(desk.book.limits), desk._stops())


def quote(at: float, *, side: Side = "up", sequence: str = "markout-quote") -> Book:
    return Book(TICKER, side, (Level(.50, 20),), (Level(.60, 20),),
                at, sequence, exchange_at=at)


def test_reconciliation_registers_actual_new_fill_once_at_batch_return(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    observer = Observer()
    install(desk, observer)
    desk.monotonic = lambda: clock.now() - 1000
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        fill_at = clock.now()
        original = account.fills

        def delayed_batch(**kwargs: Any) -> list[dict[str, Any]]:
            result = original(**kwargs)
            clock.advance(.25)
            return result

        account.fills = delayed_batch  # type: ignore[method-assign]
        asyncio.run(desk._reconcile())
        asyncio.run(desk._reconcile())
        observed = [call for call in observer.calls if call[0] == "observe_fill"]
        assert len(observed) == 1
        _, args, kwargs = observed[0]
        assert args[0] == desk.book.fills["fill-0"]
        assert args[0].at == fill_at
        assert args[1] is desk.book.windows[TICKER]
        assert kwargs == {"observed_at": fill_at + .25, "observed_mono": fill_at + .25 - 1000,
                          "fee_precision": .0001, "fee_verified": True}
        assert desk.book.inventory[TICKER].up.shares == 5
        assert desk.book.integrity_error is None
    finally:
        desk.close()


def test_practice_events_never_enter_real_fill_diagnostic(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, mode="paper")
    observer = Observer()
    install(desk, observer)
    try:
        desk._twin_events([Decision("speeddesk_fill", TICKER, "up", .4, 2,
                                   at=clock.now(), fee_usd=.01, kind="take")])
        asyncio.run(desk.step())
        assert not any(call[0] == "observe_fill" for call in observer.calls)
        assert not desk.book.fills
        assert not account.creates and account.reads == 0
    finally:
        desk.close()


@pytest.mark.parametrize("method", ["needs_book", "on_book", "expire", "status"])
def test_failed_diagnostic_does_not_change_account_state_or_block_cancel(tmp_path: Path, method: str) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        observer = Observer(method)
        install(desk, observer)
        before, reads = financial_state(desk), account.reads
        if method in {"needs_book", "on_book"}:
            desk._markout_book(quote(clock.now()))
        elif method == "expire":
            desk._markout_call("expire", now=clock.now(), mono=desk.monotonic())
        else:
            assert desk._markout_panel()["enabled"] is False
        assert financial_state(desk) == before
        assert account.reads == reads and not account.cancels
        clock.advance(4)
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"]
        assert len(account.creates) == 1
        assert desk.errors == 0 and not desk.auth_failed
    finally:
        desk.close()


def test_failed_observation_keeps_authoritative_fill_and_fee(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        install(desk, Observer("observe_fill"))
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        asyncio.run(desk._reconcile())
        fill = desk.book.fills["fill-0"]
        assert desk.book.inventory[TICKER].up.shares == 5
        assert desk.book.inventory[TICKER].up.fees == fill.fee_usd
        assert desk.book.inventory[TICKER].up.cost == pytest.approx(5 * .4)
        assert desk.cash_usd == account.cash  # a fresh balance read already absorbed the debit
        assert desk.book.integrity_error is None and desk.errors == 0
        assert desk.markouts is None and desk.markout_error == "RuntimeError"
    finally:
        desk.close()


def test_broken_diagnostic_at_start_does_not_block_authorized_send(tmp_path: Path) -> None:
    desk, account, _ = make_historical_desk(tmp_path)
    try:
        install(desk, Observer("expire"))
        desk._markout_call("expire", now=desk.clock(), mono=desk.monotonic())
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        assert account.creates[0]["side"] == "up"
        assert account.creates[0]["size"] == 5
        assert desk.errors == 0
    finally:
        desk.close()


def test_own_reserved_bids_include_uncertain_cancel_and_foreign_window(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_take_edge": 1.0})
    observer = Observer()
    try:
        asyncio.run(desk.step())
        install(desk, observer)
        reserved = next(iter(desk.book.intents.values()))
        assert reserved.kind == "rest"
        reserved.filled_size = 1
        reserved.cancel_requested = True
        reserved.uncertainty = "cancel_unconfirmed"
        desk.foreign_windows.add(TICKER)
        before, reads = financial_state(desk), account.reads
        desk._markout_book(quote(clock.now(), side=reserved.side))
        passed = next(call[2] for call in observer.calls if call[0] == "on_book")
        assert passed["own_bids"] == {reserved.price: reserved.size}
        assert passed["ownership_unknown"] is True
        observer.calls.clear()
        desk._markout_book(quote(clock.now(), side="down" if reserved.side == "up" else "up"))
        assert next(call[2] for call in observer.calls if call[0] == "on_book")["own_bids"] == {}
        assert financial_state(desk) == before
        assert account.reads == reads
    finally:
        desk.close()


@pytest.mark.parametrize("status,filled", [("canceled", 0), ("canceled", 1), ("filled", 5)])
def test_buffered_quote_excludes_original_own_size_after_release(tmp_path: Path, status: str, filled: int) -> None:
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_take_edge": 1.0})
    observer = Observer()
    try:
        asyncio.run(desk.step())
        install(desk, observer)
        order = next(iter(desk.book.intents.values()))
        order.status, order.filled_size, order.reservation_active = status, filled, False
        before, reads = financial_state(desk), account.reads
        desk._markout_book(quote(clock.now(), side=order.side))
        passed = next(call[2] for call in observer.calls if call[0] == "on_book")
        # The quote may have been captured before the terminal acknowledgement.
        # Even fully released or filled bids are conservatively removed in full.
        assert passed["own_bids"] == {order.price: order.size}
        assert financial_state(desk) == before and account.reads == reads
    finally:
        desk.close()


@pytest.mark.parametrize("through_runner", [False, True])
def test_rejected_first_quote_cannot_be_replaced_by_later_profitable_quote(
    tmp_path: Path, through_runner: bool,
) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    desk.monotonic = clock.now
    desk.markouts = FillMarkouts(clock.now(), clock.now())
    runner: SpeedRunner | None = None
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        asyncio.run(desk._reconcile())
        deliver = desk.on_book
        trading_desk = desk.twin
        if through_runner:
            runner = SpeedRunner(Settings(data_dir=tmp_path / "runner"), threading.Event(), clock=clock,
                                 monotonic=clock.now, feed_factory=LocalFeeds,
                                 live_factory=lambda *_args, **_kwargs: desk)
            runner.on_windows([desk.book.windows[TICKER]])
            deliver, trading_desk = runner.on_book, runner.desk
        financial, reads = financial_state(desk), account.reads
        clock.advance(1.1)
        invalid = replace(quote(clock.now(), sequence="first-invalid"), bids=(Level(.5, -1),))
        deliver(invalid)
        stored = trading_desk.books.get((TICKER, "up"))
        assert stored is None or stored.sequence != "first-invalid"
        deliver(quote(clock.now(), sequence="later-good"))
        assert trading_desk.books[TICKER, "up"].sequence == "later-good"
        desk.checkpoint()
        gaps = [row for row in desk.ledger.receipts() if row.kind == "speeddesk_fill_markout_gap"
                and row.payload["horizon_s"] == 1]
        successful = [row for row in desk.ledger.receipts() if row.kind == "speeddesk_fill_markout"
                      and row.payload["horizon_s"] == 1]
        assert len(gaps) == 1 and gaps[0].payload["reason"] == "invalid_level"
        assert gaps[0].payload["hypothetical_net_usd"] is None
        assert not successful
        assert financial_state(desk) == financial and account.reads == reads
        assert len(account.creates) == 1 and not account.cancels
    finally:
        if runner is not None:
            runner.close()
        desk.close()


def test_real_observations_persist_separately_without_profit_or_order_effect(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    desk.monotonic = clock.now
    desk.markouts = FillMarkouts(clock.now(), clock.now())
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        asyncio.run(desk._reconcile())
        financial, reads = financial_state(desk), account.reads
        latest = list(desk.latest_events)
        clock.advance(1.1)
        desk.on_book(quote(clock.now()))
        desk.checkpoint()
        assert financial_state(desk) == financial
        assert account.reads == reads and len(account.creates) == 1 and not account.cancels
        assert desk.latest_events[:len(latest)] == latest
        assert not any(item["event"] in QUIET_RECORDS for item in desk.latest_events)
        observed = desk.ledger.last_receipt("speeddesk_fill_observed")
        result = desk.ledger.last_receipt("speeddesk_fill_markout")
        assert observed is not None and result is not None
        assert observed.payload["fill_source"] == "real"
        assert result.payload["mode"] == "diagnostic"
        assert result.payload["execution_assumption"] == "instantaneous_visible_bid_depth_no_order_sent"
        assert result.payload["hypothetical_net_usd"] > 0
        assert desk.book.realized_pnl == 0
        assert desk.ledger.verify_chain() == (True, None)
    finally:
        desk.close()


def test_all_diagnostic_event_types_are_quiet(tmp_path: Path) -> None:
    desk, _, _ = make_desk(tmp_path, mode="paper")
    try:
        latest = list(desk.latest_events)
        kinds = {"speeddesk_fill_observed", "speeddesk_fill_markout", "speeddesk_fill_markout_gap",
                 "speeddesk_fill_markout_status"}
        assert kinds <= QUIET_RECORDS
        for kind in kinds:
            desk._record(kind, mode="diagnostic", hypothetical_net_usd=1)
        assert desk.latest_events == latest
        desk.checkpoint()
        assert all(desk.ledger.last_receipt(kind) is not None for kind in kinds)
        assert desk.book.realized_pnl == 0
    finally:
        desk.close()


def test_expiry_probe_runs_while_account_read_is_waiting(tmp_path: Path) -> None:
    desk, account, clock = make_historical_desk(tmp_path)
    observer = Observer()
    install(desk, observer)
    desk.stop_event = threading.Event()
    try:
        async def exercise() -> None:
            await desk.step()
            blocked, entered = asyncio.Event(), asyncio.Event()
            original = desk._read

            async def held_read(name: str, callback: Any, *args: Any, **kwargs: Any) -> Any:
                if name == "fills":
                    entered.set()
                    await blocked.wait()
                return await original(name, callback, *args, **kwargs)

            desk._read = held_read  # type: ignore[method-assign]
            account_read = asyncio.create_task(desk._reconcile())
            probe = asyncio.create_task(desk._markout_probe())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                reads = account.reads
                await asyncio.sleep(.15)
                assert not account_read.done()
                assert any(call[0] == "expire" for call in observer.calls)
                assert account.reads == reads and len(account.creates) == 1 and not account.cancels
            finally:
                blocked.set()
                desk.stop_event.set()
                await account_read
                await probe

        asyncio.run(exercise())
        assert desk.errors == 0
        assert all(call[2]["now"] == clock.now() for call in observer.calls if call[0] == "expire")
    finally:
        desk.close()


@pytest.mark.parametrize("coinbase,stream", [("connected", False), ("disconnected", True)])
def test_global_snapshot_invalidation_expires_pending_diagnostics(tmp_path: Path, coinbase: str, stream: bool) -> None:
    desk, account, _ = make_desk(tmp_path, mode="paper")
    observer = Observer()
    install(desk, observer)
    try:
        desk.on_status({"coinbase": coinbase, "trade_stream": stream, "gap_windows": []})
        expired = [call[2] for call in observer.calls if call[0] == "expire"]
        assert len(expired) == 1 and expired[0]["reason"] == "book_snapshot_invalidated"
        assert "window" not in expired[0]
        assert account.reads == 0 and not account.creates and not account.cancels
    finally:
        desk.close()


@pytest.mark.parametrize("cause", ["gap", "settlement", "shutdown"])
def test_terminal_events_expire_diagnostics_without_extra_network(tmp_path: Path, cause: str) -> None:
    desk, account, clock = make_desk(tmp_path, mode="paper")
    observer = Observer()
    install(desk, observer)
    try:
        if cause == "gap":
            desk.on_status({"coinbase": "connected", "trade_stream": True, "gap_windows": [TICKER]})
        elif cause == "settlement":
            clock.advance(desk.book.windows[TICKER].end - clock.now() + 1)
            desk.on_settlement(TICKER, True, clock.now())
        else:
            asyncio.run(desk.shutdown())
        expired = [call[2] for call in observer.calls if call[0] == "expire"]
        reasons = {"gap": "venue_feed_gap", "settlement": "market_settled", "shutdown": "shutdown"}
        assert len(expired) == 1 and expired[0]["reason"] == reasons[cause]
        if cause != "shutdown":
            assert expired[0]["window"] == TICKER
        assert account.reads == 0 and not account.creates and not account.cancels
    finally:
        desk.close()

"""Independent callback-attribution boundary checks; fake accounts and clocks only."""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fakes import FakeClock
from test_speeddesk_live import TICKER, fill_order, make_desk
from test_speeddesk_live_runtime import PublicFeeds

from nightcrawler.config import Settings
from nightcrawler.speeddesk import STATE_KEY, SpeedRunner
from nightcrawler.speeddesk_model import Book, Level, Window
from nightcrawler.speeddesk_worktrace import WorkTrace


class BrokenObserver:
    def span(self, _name: str) -> Any:
        raise RuntimeError("observer span unavailable")

    def overlap(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("observer overlap unavailable")

    def status(self) -> Any:
        raise RuntimeError("observer status unavailable")


def runner_at(path: Path) -> SpeedRunner:
    return SpeedRunner(Settings(data_dir=path), threading.Event(), clock=FakeClock(), feed_factory=PublicFeeds)


def test_runner_and_live_share_observer_without_opening_account(tmp_path: Path) -> None:
    class NestedFeeds(PublicFeeds):
        def __init__(self, settings: Settings, **callbacks: Any) -> None:
            super().__init__(settings, **callbacks)
            self.adapters = {"kalshi": SimpleNamespace(_ws=SimpleNamespace()),
                             "polymarket_us": SimpleNamespace()}

    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=FakeClock(), feed_factory=NestedFeeds)
    try:
        assert runner.live is not None
        assert runner.live.work_trace is runner.work_trace
        assert runner.feeds.adapters["kalshi"].work_trace is runner.work_trace
        assert runner.feeds.adapters["kalshi"]._ws.work_trace is runner.work_trace
        assert runner.feeds.adapters["polymarket_us"].work_trace is runner.work_trace
        asyncio.run(runner.live.step())
        runner.panel(runner.clock.now())
        assert runner.work_trace.enabled
        assert runner.live.client is None
        assert not runner.live.book.intents
    finally:
        runner.close()


@pytest.mark.parametrize("operation", ["overlap", "status"])
def test_observer_query_fault_does_not_disable_accounting(tmp_path: Path, operation: str) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        desk.work_trace = BrokenObserver()  # type: ignore[assignment]
        if operation == "status":
            assert desk._trace_panel()["callback_work"] == {"enabled": False}
        before_reads, before_creates = account.reads, len(account.creates)
        asyncio.run(desk._reconcile())
        assert account.reads - before_reads == 4
        assert len(account.creates) == before_creates
        assert desk.book.inventory[TICKER].up.shares == 5
        assert not desk.stopping and desk.fatal_reason is None
        assert desk.read_trace is not None
        assert desk.work_trace is None
        assert desk.ledger.verify_chain() == (True, None)
    finally:
        desk.close()


def test_worktrace_rows_do_not_advance_existing_save_cadence(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path, mode="paper")
    desk.monotonic = clock.now
    desk.work_trace = WorkTrace(monotonic=clock.now, thread_cpu=lambda: 0.0)
    try:
        asyncio.run(desk.step())
        desk.checkpoint()
        saved = desk.last_checkpoint
        assert desk.read_trace is not None
        desk.read_trace.begin(clock.now(), clock.now(), False, 0)
        with desk.work_trace.span("practice_checkpoint"):
            clock.advance(.01)
        desk._trace_finish(failed=True)
        assert len(desk._trace_pending) == 1 and not desk.pending
        clock.advance(2)
        desk._heartbeat()
        assert desk.last_checkpoint == saved
        assert len(desk._trace_pending) == 1
        clock.advance(3)
        desk._heartbeat()
        assert not desk._trace_pending
        assert desk.ledger.verify_chain() == (True, None)
        assert account.reads == 0 and not account.creates and not account.cancels
    finally:
        desk.close()


def test_actual_read_wrapper_joins_nested_work_to_worker_resume_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    desk, account, clock = make_desk(tmp_path, mode="paper")
    mono = [10.0]
    cpu = [0.0]
    work = WorkTrace(monotonic=lambda: mono[0], thread_cpu=lambda: cpu[0])
    desk.monotonic = lambda: mono[0]
    desk.work_trace = work
    assert desk.read_trace is not None
    desk.read_trace.begin(clock.now(), mono[0], False, 0)

    def start(callback: Any, *args: Any, _read_span: Any = None, **kwargs: Any) -> asyncio.Task[Any]:
        async def worker_then_blocking_callback() -> Any:
            # Deterministic worker completion followed by same-loop callback work.
            # The production _read wrapper still owns waiting/cancellation/joining.
            assert _read_span is not None
            _read_span.mark("worker_started", 10.0)
            result = callback(*args, **kwargs)
            mono[0] = 11.0
            _read_span.mark("worker_completed", mono[0])
            with work.span("practice_checkpoint"):
                mono[0], cpu[0] = 11.25, .1
                with work.span("practice_ledger"):
                    mono[0], cpu[0] = 12.5, .4
                mono[0], cpu[0] = 13.0, .5
            return result

        return asyncio.create_task(worker_then_blocking_callback())

    monkeypatch.setattr(desk, "_start_io", start)
    try:
        assert asyncio.run(desk._read("list_orders", account.list_orders)) == []
        desk._trace_finish(failed=True)
        row = desk._trace_pending[-1]
        assert row["reads"][0]["marks_ms"]["worker_completed"] == 1000
        assert row["reads"][0]["marks_ms"]["coroutine_resumed"] == 3000
        assert row["read_resume_work"] == [{"read": "list_orders", **work.overlap(11, 13, max_spans=8)}]
        overlap = row["read_resume_work"][0]
        assert overlap["covered_wall_ms"] == 2000
        assert overlap["unattributed_wall_ms"] == 0
        assert sum(span["overlap_wall_ms"] for span in overlap["spans"]) == 3250
        assert {span["name"]: span["cpu_ms"] for span in overlap["spans"]} == pytest.approx(
            {"practice_checkpoint": 500, "practice_ledger": 300})
        assert account.reads == 1 and not account.creates and not account.cancels
        assert not desk.pending and not desk.book.intents
    finally:
        desk.close()


def test_span_failure_keeps_first_save_receipt_then_mirror_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = runner_at(tmp_path)
    events: list[str] = []
    original_transaction = runner.ledger.transaction
    original_sync = runner.ledger.set_synchronous
    from nightcrawler import speeddesk

    original_mirror = speeddesk._atomic_json

    @contextmanager
    def transaction() -> Any:
        events.append("begin")
        with original_transaction():
            yield
        events.append("commit")

    def synchronous(enabled: bool) -> None:
        events.append(f"sync:{enabled}")
        original_sync(enabled)

    def mirror(path: Path, state: dict[str, Any], *, durable: bool = True) -> None:
        assert runner.ledger.get_kv(STATE_KEY)["updated_at"] == state["updated_at"]
        assert any(row.kind == "integration_probe" for row in runner.ledger.receipts())
        assert not runner.pending
        assert events.index("sync:True") < events.index("commit") < events.index("sync:False")
        events.append("mirror")
        original_mirror(path, state, durable=durable)

    monkeypatch.setattr(runner.ledger, "transaction", transaction)
    monkeypatch.setattr(runner.ledger, "set_synchronous", synchronous)
    monkeypatch.setattr(speeddesk, "_atomic_json", mirror)
    runner.work_trace = BrokenObserver()  # type: ignore[assignment]
    try:
        runner.record("integration_probe", {"at": runner.clock.now()})
        runner.checkpoint(runner.clock.now())
        assert events[-1] == "mirror"
        assert runner._first_save_synced
        assert runner.live is not None and not runner.live.stopping
        assert runner.ledger.verify_chain() == (True, None)
    finally:
        runner.close()


def test_broken_observer_does_not_mask_business_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = runner_at(tmp_path)
    failure = OSError("synthetic ledger failure")

    def broken(_key: str, _value: Any) -> None:
        raise failure

    try:
        runner.work_trace = BrokenObserver()  # type: ignore[assignment]
        monkeypatch.setattr(runner.ledger, "set_kv", broken)
        runner.record("integration_probe", {"at": runner.clock.now()})
        with pytest.raises(OSError) as caught:
            runner.checkpoint(runner.clock.now())
        assert caught.value is failure
        assert runner.pending
        assert not runner.path.exists()
    finally:
        runner.close()


def test_broken_observer_preserves_gap_invalidation_before_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = runner_at(tmp_path)
    seen: list[bool] = []
    try:
        now = runner.clock.now()
        window = Window("KXBTC15M-test", now, now + 900, 80_000, venue_start_price=80_000, venue="kalshi")
        runner.on_windows([window])
        runner.on_status({"coinbase": "connected", "trade_stream": True})
        runner.on_book(Book(window.slug, "up", (), (Level(.4, 3),), now, "1"))
        assert runner.live_snapshot().books
        runner.record("integration_probe", {"at": now})
        original = runner.checkpoint

        def check(at: float) -> None:
            seen.append(True)
            assert not runner.live_snapshot().books
            assert not runner.live_snapshot().maker_windows
            original(at)

        monkeypatch.setattr(runner, "checkpoint", check)
        runner.work_trace = BrokenObserver()  # type: ignore[assignment]
        runner.on_status({"coinbase": "disconnected", "trade_stream": False})
        assert seen
        assert runner.live is not None and not runner.live.stopping
        assert runner.live_problem is None
    finally:
        runner.close()

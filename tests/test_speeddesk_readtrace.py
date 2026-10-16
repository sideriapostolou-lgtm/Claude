"""Fake clocks and account callbacks only; trace data has no trading authority."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, fill_order, make_desk

from nightcrawler.speeddesk_live import QUIET_RECORDS, KalshiLiveDesk
from nightcrawler.speeddesk_readtrace import (
    MAX_CANCEL_SPANS,
    MAX_FILLS,
    MAX_READS,
    MAX_REPORTS_PER_MINUTE,
    ReadSpan,
    ReconcileTrace,
)


def test_clock_decomposition_and_previous_successful_fills_read() -> None:
    trace = ReconcileTrace()
    trace.begin(1000, 10, True, 0)
    read = trace.read_start("fills", 10.1)
    assert read is not None
    read.mark("worker_started", 10.2)
    read.mark("worker_completed", 10.4)
    read.mark("coroutine_resumed", 12.4)
    read.cancel("pending_read", 10.3, 12.3)
    read.cancel("completed_read", 12.4, 12.7)
    read.mark("wrapper_returned", 12.7)
    read.complete(3, 2, 700)
    trace.fills_returned(1002.7, 12.7)
    trace.fill("fill-1", 1000.2, 12.8)
    trace.mark("checkpoint_started", 13)
    trace.mark("checkpoint_completed", 13.3)
    row = trace.finish(1003.4, 13.4, False)
    assert row is not None
    assert row["previous_fills_returned_at"] is None
    assert row["reads"][0]["marks_ms"] == {
        "submitted": 100, "worker_started": 200, "worker_completed": 400,
        "coroutine_resumed": 2400, "wrapper_returned": 2700}
    assert row["reads"][0]["cancel_ms"] == 2300
    assert row["reads"][0]["pages"] == 2
    assert row["new_fills"] == [{"fill_id": "fill-1", "venue_fill_at": 1000.2, "registered_ms": 2800}]
    trace.begin(1004, 14, False, 0)
    row = trace.finish(1008, 18, False)
    assert row is not None and row["previous_fills_returned_at"] == 1002.7


def test_memory_and_logging_bounds_preserve_omission_counts() -> None:
    trace = ReconcileTrace()
    trace.begin(1000, 0, False, 0)
    for _ in range(MAX_READS + 4):
        trace.read_start("fills", 0)
    for i in range(MAX_FILLS + 3):
        trace.fill(f"fill-{i}", 999, 0)
    read = trace.reads[0]
    for _ in range(MAX_CANCEL_SPANS + 5):
        read.cancel("pending_read", 0, .01)
    row = trace.finish(1001, 1, False)
    assert row is not None
    assert len(row["reads"]) == MAX_READS and row["reads_omitted"] == 4
    assert len(row["new_fills"]) == MAX_FILLS and row["new_fills_omitted"] == 3
    assert len(row["reads"][0]["cancel_spans"]) == MAX_CANCEL_SPANS
    assert row["reads"][0]["cancel_spans_omitted"] == 5
    assert trace.active is None and not trace.reads
    for i in range(MAX_REPORTS_PER_MINUTE + 3):
        trace.begin(1002 + i, 2 + i, False, 0)
        trace.finish(1002 + i, 2 + i, True)
    assert trace.counts["reported"] == MAX_REPORTS_PER_MINUTE
    assert trace.counts["suppressed"] == 4
    assert len(trace.emitted) == MAX_REPORTS_PER_MINUTE
    trace.begin(1062, 62, False, 0)
    assert trace.finish(1062, 62, True) is not None


def test_quiet_cycles_are_counted_without_detail_publication() -> None:
    trace = ReconcileTrace()
    trace.begin(1000, 0, False, 0)
    assert trace.finish(1001, 1, False) is None
    assert trace.status()["counts"] == {"cycles": 1, "reported": 0, "quiet": 1, "suppressed": 0}


def state(desk: KalshiLiveDesk) -> tuple[Any, ...]:
    return (desk.book.to_state(), desk.cash_usd, desk.cash_at, desk.errors,
            desk.authenticated, desk.auth_failed, desk.fatal_reason,
            asdict(desk.book.limits), desk._stops())


def test_real_fill_trace_is_once_and_records_checkpoint_without_extra_reads(tmp_path: Path) -> None:
    desk, account, clock = make_desk(tmp_path)
    desk.monotonic = clock.now
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=.4, size=5)
        account.account_positions = [{"ticker": TICKER, "position_fp": "5.00"}]
        before = account.reads
        asyncio.run(desk._reconcile())
        rows = list(desk._trace_pending)
        assert len(rows) == 1
        row = rows[0]
        assert row["new_fills"][0]["fill_id"] == "fill-0"
        assert row["marks_ms"]["checkpoint_completed"] >= row["marks_ms"]["checkpoint_started"]
        assert [read["read"] for read in row["reads"]] == [
            "list_orders", "fills", "list_orders", "positions", "balance", "subaccount_balances"]
        assert account.reads - before == 4  # unchanged fake's counted endpoints
        assert desk.book.inventory[TICKER].up.shares == 5
        assert "speeddesk_reconcile_trace" in QUIET_RECORDS
        assert not any(event["event"] == "speeddesk_reconcile_trace" for event in desk.latest_events)
        assert not any(kind == "speeddesk_reconcile_trace" for kind, _ in desk.pending)
        asyncio.run(desk._reconcile())
        assert desk.read_trace is not None and desk.read_trace.counts["reported"] == 1
    finally:
        desk.close()


def test_practice_never_constructs_client_or_produces_account_traces(tmp_path: Path) -> None:
    desk, account, _ = make_desk(tmp_path, mode="paper")
    try:
        asyncio.run(desk.step())
        assert desk.client is None and account.reads == 0 and not account.creates
        assert desk.read_trace is not None and desk.read_trace.counts["cycles"] == 0
        assert not any(kind == "speeddesk_reconcile_trace" for kind, _ in desk.pending)
    finally:
        desk.close()


def test_trace_does_not_advance_quiet_checkpoint_cadence(tmp_path: Path) -> None:
    desk, _, clock = make_desk(tmp_path, mode="paper")
    try:
        asyncio.run(desk.step())
        desk.checkpoint()
        saved_at = desk.last_checkpoint
        assert desk.read_trace is not None
        desk.read_trace.begin(clock.now(), desk.monotonic(), False, 0)
        desk._trace_finish(failed=True)
        assert len(desk._trace_pending) == 1 and not desk.pending
        clock.advance(2)
        desk._heartbeat()
        assert desk.last_checkpoint == saved_at  # ordinary quiet checkpoint still waits five seconds
        assert len(desk._trace_pending) == 1
        clock.advance(3)
        desk._heartbeat()
        assert desk.last_checkpoint == clock.now()
        assert not desk._trace_pending and desk.ledger.verify_chain() == (True, None)
    finally:
        desk.close()


def test_trace_buffer_bound_and_publication_failure_leave_checkpoint_working(tmp_path: Path) -> None:
    desk, _, clock = make_desk(tmp_path, mode="paper")
    desk.monotonic = clock.now
    try:
        asyncio.run(desk.step())
        assert desk.read_trace is not None
        for i in range(MAX_REPORTS_PER_MINUTE + 2):
            desk.read_trace.begin(clock.now(), desk.monotonic(), False, 0)
            desk._trace_finish(failed=True)
            clock.advance(61)
        assert len(desk._trace_pending) == MAX_REPORTS_PER_MINUTE
        assert desk._trace_panel()["buffer_dropped"] == 2
        before = state(desk)
        original = desk._record

        def broken(kind: str, **payload: Any) -> None:
            if kind == "speeddesk_reconcile_trace":
                raise RuntimeError("synthetic diagnostic publication failure")
            original(kind, **payload)

        desk._record = broken  # type: ignore[method-assign]
        desk.checkpoint()
        assert desk.last_checkpoint == clock.now() and desk.ledger.verify_chain() == (True, None)
        assert state(desk) == before
        assert desk.read_trace is None and desk.read_trace_error == "RuntimeError"
        assert not desk._trace_pending
    finally:
        desk.close()


@pytest.mark.parametrize("method", ["begin", "read_start", "fills_returned", "fill", "mark", "finish", "status"])
def test_observer_failure_never_changes_fills_caps_or_cancellation(tmp_path: Path, method: str) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=.4, size=2)
        account.orders[0].update(status="resting", remaining_count_fp="3.00")
        account.account_positions = [{"ticker": TICKER, "position_fp": "2.00"}]
        before = asdict(desk.book.limits)

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic diagnostic failure")

        assert desk.read_trace is not None
        setattr(desk.read_trace, method, broken)
        asyncio.run(desk._reconcile())
        desk._trace_panel()
        assert desk.book.inventory[TICKER].up.shares == 2
        assert asdict(desk.book.limits) == before
        assert desk.errors == 0 and desk.book.integrity_error is None
        assert desk.read_trace is None and desk.read_trace_error == "RuntimeError"
        clock.advance(4)
        asyncio.run(desk.step())
        assert account.cancels == ["order-1"] and len(account.creates) == 1
    finally:
        desk.close()


def test_worker_trace_failure_does_not_change_callback_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desk, _, _ = make_desk(tmp_path)
    try:
        before = state(desk)

        def broken(*args: Any) -> None:
            raise RuntimeError("synthetic worker observation failure")

        monkeypatch.setattr(ReadSpan, "mark", broken)

        async def run() -> int:
            return int(await desk._start_io(lambda: 42, _read_span=ReadSpan("fills", 0)))

        assert asyncio.run(run()) == 42
        assert state(desk) == before
        assert desk.read_trace is None
    finally:
        desk.close()


def test_read_cancellation_overlap_and_final_cancellation_are_distinct(tmp_path: Path) -> None:
    desk, _, clock = make_desk(tmp_path)
    desk.monotonic = clock.now
    worker_started, release = threading.Event(), threading.Event()
    calls = 0

    def callback() -> list[dict[str, Any]]:
        worker_started.set()
        assert release.wait(3)
        return [{"id": "fake-fill"}]

    async def cancellation() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert worker_started.is_set()
            clock.advance(.25)
            release.set()
            # Let the worker finish while the existing synchronous cancel call is pending.
            await asyncio.sleep(.05)
            clock.advance(2)
        else:
            clock.advance(.5)

    async def run() -> list[dict[str, Any]]:
        assert desk.read_trace is not None
        desk.read_trace.begin(clock.now(), clock.now(), False, 0)
        desk._cancel_unsafe = cancellation  # type: ignore[method-assign]
        return list(await desk._read("fills", callback))

    try:
        assert asyncio.run(run()) == [{"id": "fake-fill"}]
        assert desk.read_trace is not None
        read = desk.read_trace.reads[0].result()
        assert calls == 2  # the original pending and final safety checks both still execute
        assert [span["kind"] for span in read["cancel_spans"]] == ["pending_read", "completed_read"]
        assert read["marks_ms"]["worker_completed"] == 250
        assert read["marks_ms"]["coroutine_resumed"] == 2250
        assert read["marks_ms"]["wrapper_returned"] == 2750
    finally:
        release.set()
        desk.close()

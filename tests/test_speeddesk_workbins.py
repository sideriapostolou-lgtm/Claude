"""Independent interval-union oracle, exact boundaries and diagnostic isolation."""

from __future__ import annotations

import json
import random
from typing import Any

import pytest

from nightcrawler.speeddesk_workbins import BIN_S, MAX_BINS, WorkBins
from nightcrawler.speeddesk_worktrace import WorkTrace


def test_quiet_callback_occupancy_is_visible_without_retaining_callback_rows() -> None:
    wall = cpu = 0.0
    trace = WorkTrace(monotonic=lambda: wall, thread_cpu=lambda: cpu)
    for _ in range(128):
        with trace.span("feed_book"):
            wall += 1 / 1024
            cpu += 1 / 4096
    result = trace.overlap(0, wall)
    assert result["spans"] == [] and result["covered_wall_ms"] == 0
    bins = result["all_sync_work_lower_bound"]
    assert bins["covered_wall_lower_bound_ms"] == 125
    assert bins["contained_span_cpu_ms"] == 31.25
    assert bins["retained_full_bins"] == 4 and bins["not_additive_to_slow_span_coverage"]
    assert trace.status()["retained"] == 0 and trace.status()["quiet"] == 128
    json.dumps(result, allow_nan=False)


def test_nested_spans_never_double_count_wall_or_cpu() -> None:
    wall = cpu = 0.0
    trace = WorkTrace(monotonic=lambda: wall, thread_cpu=lambda: cpu)
    with trace.span("practice_checkpoint"):
        wall += BIN_S
        cpu += .001
        with trace.span("practice_ledger"):
            wall += 2 * BIN_S
            cpu += .003
        wall += BIN_S
        cpu += .001
    result = trace.overlap(0, wall)
    bins = result["all_sync_work_lower_bound"]
    assert bins["covered_wall_lower_bound_ms"] == 4 * BIN_S * 1000
    assert bins["top_level_spans"] == 1
    assert bins["contained_span_cpu_ms"] == 0  # Crossing CPU is never apportioned.
    assert result["covered_wall_ms"] == bins["covered_wall_lower_bound_ms"]


def test_query_edges_are_omitted_and_never_claimed_complete() -> None:
    bins = WorkBins()
    for i in range(128):
        bins.record(i / 1024, (i + 1) / 1024, 1 / 4096)
    result = bins.overlap(BIN_S / 2, 3.5 * BIN_S)
    assert result["covered_wall_lower_bound_ms"] == 2 * BIN_S * 1000
    assert result["query_boundary_ms"] == BIN_S * 1000
    assert result["unattributed_or_boundary_ms"] == BIN_S * 1000
    assert result["contained_span_cpu_ms"] == 2 * BIN_S * 250
    assert bins.overlap(.001, .002)["covered_wall_lower_bound_ms"] == 0


def test_eviction_and_long_span_processing_have_hard_storage_and_work_bounds() -> None:
    bins = WorkBins()
    for i in range(MAX_BINS + 4):
        bins.record(i * BIN_S, (i + 1) * BIN_S, .001)
    result = bins.overlap(0, (MAX_BINS + 4) * BIN_S)
    assert result["retention_loss"] and result["retained_full_bins"] == MAX_BINS
    assert result["covered_wall_lower_bound_ms"] == MAX_BINS * BIN_S * 1000
    assert not bins.overlap(4 * BIN_S, (MAX_BINS + 4) * BIN_S)["retention_loss"]
    assert all(len(values) == MAX_BINS for values in (bins._epochs, bins._wall, bins._cpu))
    huge = WorkBins()
    huge.record(0, 1_000_000, 1)
    result = huge.overlap(0, 1_000_000)
    assert result["retention_loss"] and result["clipped_spans"] == 1
    assert result["covered_wall_lower_bound_ms"] == MAX_BINS * BIN_S * 1000
    assert result["contained_span_cpu_ms"] == 0


def test_sparse_gaps_clock_origin_empty_and_zero_queries_are_explicit() -> None:
    bins = WorkBins()
    empty = bins.overlap(0, 1)
    assert empty["before_observation"] and empty["after_last_completed_span"]
    assert empty["covered_wall_lower_bound_ms"] == 0
    bins.record(10, 10 + BIN_S, .001)
    bins.record(11, 11 + BIN_S, .002)
    result = bins.overlap(10, 11 + BIN_S)
    assert result["covered_wall_lower_bound_ms"] == 2 * BIN_S * 1000
    assert result["contained_span_cpu_ms"] == 3
    assert bins.overlap(10, 10)["covered_wall_lower_bound_ms"] == 0
    assert bins.overlap(9, 12)["before_observation"]
    assert bins.overlap(9, 12)["after_last_completed_span"]


def test_random_queries_never_exceed_exact_union_and_cpu_matches_whole_span_oracle() -> None:
    rng = random.Random(20261014)
    bins = WorkBins()
    intervals: list[tuple[float, float, float]] = []
    now = 0.0
    for _ in range(2000):
        start = now + rng.randrange(8) / 1024
        end = start + rng.randrange(1, 64) / 1024
        cpu = (end - start) / 4
        intervals.append((start, end, cpu))
        bins.record(start, end, cpu)
        now = end
    floor = max(0, math_floor_bin(intervals[-1][1] - 1 / 2048) - MAX_BINS + 1)
    for _ in range(100):
        a, b = sorted([rng.random() * now, rng.random() * now])
        result = bins.overlap(a, b)
        full = [(i * BIN_S, (i + 1) * BIN_S)
                for i in range(max(floor, math_ceil_bin(a)), math_floor_bin(b))]
        expected_wall = sum(max(0.0, min(end, right) - max(start, left))
                            for left, right in full for start, end, _ in intervals)
        expected_cpu = sum(cpu for start, end, cpu in intervals
                           if any(left <= start and end <= right for left, right in full))
        exact = sum(max(0.0, min(end, b) - max(start, a)) for start, end, _ in intervals)
        assert result["covered_wall_lower_bound_ms"] == pytest.approx(expected_wall * 1000)
        assert result["covered_wall_lower_bound_ms"] <= exact * 1000 + 1e-8
        assert result["contained_span_cpu_ms"] == pytest.approx(expected_cpu * 1000)


def math_floor_bin(value: float) -> int:
    return int(value // BIN_S)


def math_ceil_bin(value: float) -> int:
    return -int(-value // BIN_S)


def test_bin_fault_disables_only_diagnostic_and_preserves_business_exception() -> None:
    class Broken:
        def record(self, *_args: Any) -> None:
            raise RuntimeError("synthetic bin error")

    trace = WorkTrace()
    trace._bins = Broken()  # type: ignore[assignment]
    failure = ValueError("business")
    with pytest.raises(ValueError) as caught, trace.span("feed_trade"):
        raise failure
    assert caught.value is failure and not trace.enabled
    assert trace.error == "observer_finish_failed"
    json.dumps(trace.status(), allow_nan=False)


def test_bin_status_failure_is_isolated_before_publishing_enabled_state() -> None:
    class Broken:
        def status(self) -> dict[str, Any]:
            raise RuntimeError("synthetic status error")

    trace = WorkTrace()
    trace._bins = Broken()  # type: ignore[assignment]
    status = trace.status()
    assert not status["enabled"] and status["error"] == "observer_bin_status_failed"
    assert status["all_sync_work_lower_bound"] == {"available": False}
    json.dumps(status, allow_nan=False)

"""Boundary and publication contracts independent of the bin implementation."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from nightcrawler.speeddesk_workbins import BIN_S, WorkBins
from nightcrawler.speeddesk_worktrace import WorkTrace


@pytest.mark.parametrize("origin", [0.0, 3_546_000.0, float(2**40)])
def test_representable_query_edges_never_include_work_outside_query(origin: float) -> None:
    bins = WorkBins()
    boundary = origin + BIN_S
    before = math.nextafter(boundary, -math.inf)
    after = math.nextafter(boundary, math.inf)
    bins.record(before, boundary, .000001)
    bins.record(boundary, after, .000002)
    left = bins.overlap(origin, boundary)
    right = bins.overlap(boundary, origin + 2 * BIN_S)
    assert left["covered_wall_lower_bound_ms"] == (boundary - before) * 1000
    assert right["covered_wall_lower_bound_ms"] == (after - boundary) * 1000
    assert left["contained_span_cpu_ms"] == pytest.approx(.001)
    assert right["contained_span_cpu_ms"] == pytest.approx(.002)
    assert bins.overlap(before, after)["covered_wall_lower_bound_ms"] == 0


def test_large_finite_clock_origin_fails_only_observation() -> None:
    trace = WorkTrace(monotonic=lambda: 1e308, thread_cpu=lambda: 0.0)
    visits = []
    with trace.span("feed_book"):
        visits.append("business ran")
    assert visits == ["business ran"]
    assert not trace.enabled
    json.dumps(trace.status(), allow_nan=False)


def test_accumulated_finite_cpu_cannot_publish_nonfinite_json() -> None:
    wall = cpu = 0.0
    trace = WorkTrace(monotonic=lambda: wall, thread_cpu=lambda: cpu)
    for _ in range(10):
        with trace.span("feed_book"):
            wall += 1 / 1024
            cpu += 1e305
    result = trace.overlap(0, BIN_S)
    assert not result["enabled"]
    assert result["error"] == "observer_query_failed"
    json.dumps(result, allow_nan=False)


def test_query_failure_preserves_completed_business_work() -> None:
    class BrokenQuery:
        def overlap(self, *_args: Any) -> dict[str, Any]:
            raise ArithmeticError("diagnostic query")

    wall = cpu = 0.0
    trace = WorkTrace(monotonic=lambda: wall, thread_cpu=lambda: cpu)
    with trace.span("feed_trade"):
        wall += BIN_S
        cpu += .001
    assert trace.completed == 1
    trace._bins = BrokenQuery()  # type: ignore[assignment]
    result = trace.overlap(0, wall)
    assert trace.completed == 1
    assert not trace.enabled and result["error"] == "observer_query_failed"
    json.dumps(result, allow_nan=False)

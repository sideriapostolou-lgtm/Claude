"""Clock-controlled attribution and fault isolation; no network or account work."""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any

import pytest

from nightcrawler.speeddesk_worktrace import (
    MAX_DEPTH,
    MAX_SPANS,
    SECTIONS,
    WorkTrace,
    observed,
    work_span,
)


class Clocks:
    def __init__(self) -> None:
        self.wall = 0.0
        self.cpu = 0.0

    def advance(self, wall: float, cpu: float) -> None:
        self.wall += wall
        self.cpu += cpu

    def trace(self) -> WorkTrace:
        return WorkTrace(monotonic=lambda: self.wall, thread_cpu=lambda: self.cpu)


def test_nested_and_clipped_intervals_use_union_not_sum_or_apportioned_cpu() -> None:
    clocks = Clocks()
    trace = clocks.trace()
    with trace.span("practice_checkpoint"):
        clocks.advance(.010, .002)
        with trace.span("practice_ledger"):
            clocks.advance(.020, .003)
        clocks.advance(.010, .001)
    result = trace.overlap(.015, .035)
    outer, inner = result["spans"]
    assert inner["parent_id"] == outer["span_id"]
    assert outer["parent_id"] is None
    assert outer["start_mono"] == 0 and outer["end_mono"] == pytest.approx(.040)
    assert outer["overlap_start_mono"] == .015 and outer["overlap_end_mono"] == .035
    assert outer["cpu_ms"] == pytest.approx(6)  # Full .040s span, not its clipped .020s interval.
    assert inner["cpu_ms"] == pytest.approx(3)
    assert result["covered_wall_ms"] == pytest.approx(20)
    assert result["unattributed_wall_ms"] == pytest.approx(0)
    assert not result["retention_loss"] and not result["omitted_spans"]
    assert "not apportioned" in result["cpu_basis"] and "not additive" in result["cpu_basis"]
    json.dumps(result, allow_nan=False)


def test_quiet_work_is_aggregated_and_remains_unattributed_in_interval_details() -> None:
    clocks = Clocks()
    trace = clocks.trace()
    for _ in range(10):
        with trace.span("feed_tick"):
            clocks.advance(.001, .0002)
    status = trace.status()
    assert status["quiet"] == status["completed"] == 10 and status["retained"] == 0
    assert set(status["sections"]) == SECTIONS
    assert status["sections"]["feed_tick"] == {
        "count": 10, "quiet": 10, "slow": 0, "max_wall_ms": pytest.approx(1),
        "max_cpu_ms": pytest.approx(.2),
    }
    result = trace.overlap(0, clocks.wall)
    assert result["spans"] == [] and result["quiet_spans_total"] == 10
    assert result["covered_wall_ms"] == 0 and result["unattributed_wall_ms"] == pytest.approx(10)
    assert "slow" in result["coverage_scope"]
    status["sections"]["feed_tick"]["count"] = 999
    assert trace.status()["sections"]["feed_tick"]["count"] == 10


def test_detail_omission_keeps_union_of_all_retained_work_and_hard_bounds() -> None:
    clocks = Clocks()
    trace = clocks.trace()
    for _ in range(40):
        with trace.span("practice_mirror"):
            clocks.advance(.010, .001)
        clocks.advance(.010, 0)
    result = trace.overlap(0, clocks.wall, max_spans=1000)
    assert len(result["spans"]) == 32 and result["omitted_spans"] == 8
    assert result["covered_wall_ms"] == pytest.approx(400)
    assert result["unattributed_wall_ms"] == pytest.approx(400)
    assert not result["retention_loss"]
    none = trace.overlap(0, clocks.wall, max_spans=0)
    assert none["spans"] == [] and none["omitted_spans"] == 40
    assert none["covered_wall_ms"] == pytest.approx(400)


def test_eviction_is_explicit_and_queries_after_lost_history_remain_distinguishable() -> None:
    clocks = Clocks()
    trace = clocks.trace()
    for _ in range(MAX_SPANS + 4):
        with trace.span("practice_state"):
            clocks.advance(.010, .001)
    status = trace.status()
    assert status["retained"] == MAX_SPANS and status["evicted"] == 4
    result = trace.overlap(0, clocks.wall)
    assert result["retention_loss"] and result["evicted_spans"] == 4
    assert result["unattributed_wall_ms"] == pytest.approx(40)
    recent = trace.overlap(clocks.wall - .020, clocks.wall)
    assert not recent["retention_loss"]
    assert recent["covered_wall_ms"] == pytest.approx(20)
    assert trace.overlap(0, 0)["spans"] == []
    assert trace.overlap(0, 1)["spans"][0]["span_id"] > 4


@pytest.mark.parametrize("which,when", [("wall", "entry"), ("cpu", "entry"),
                                       ("wall", "exit"), ("cpu", "exit")])
def test_failing_clocks_disable_only_observation_and_preserve_business_exception(which: str, when: str) -> None:
    clocks = Clocks()
    calls = 0

    def failing() -> float:
        nonlocal calls
        calls += 1
        if calls == (1 if when == "entry" else 2):
            raise RuntimeError("synthetic clock fault")
        return clocks.wall if which == "wall" else clocks.cpu

    trace = WorkTrace(monotonic=failing if which == "wall" else lambda: clocks.wall,
                      thread_cpu=failing if which == "cpu" else lambda: clocks.cpu)
    business = ValueError("business exception")
    with pytest.raises(ValueError) as raised, trace.span("practice_checkpoint"):
        clocks.advance(.010, .001)
        raise business
    assert raised.value is business
    assert not trace.status()["enabled"] and trace.status()["errors"] == 1
    calls_before = calls
    with trace.span("practice_checkpoint"):
        clocks.advance(.010, .001)
    assert calls == calls_before
    json.dumps(trace.status(), allow_nan=False)


@pytest.mark.parametrize("wall,cpu", [(float("nan"), 0), (0, float("inf")), (-1, 0),
                                      (True, 0), (0, -.1)])
def test_invalid_clock_values_are_isolated_and_status_stays_json_safe(wall: Any, cpu: Any) -> None:
    trace = WorkTrace(monotonic=lambda: wall, thread_cpu=lambda: cpu)
    ran = []
    with trace.span("feed_book"):
        ran.append(True)
    assert ran == [True] and trace.status()["errors"] == 1
    json.dumps(trace.status(), allow_nan=False)
    json.dumps(trace.overlap(0, .1), allow_nan=False)


def test_clock_reversal_and_unknown_section_never_change_observed_work() -> None:
    clocks = Clocks()
    clocks.advance(1, 1)
    trace = clocks.trace()
    with trace.span("feed_trade"):
        clocks.advance(-.1, 0)
    assert not trace.status()["enabled"]
    invalid = clocks.trace()
    with invalid.span("arbitrary unbounded label"):
        assert True
    assert invalid.status()["error"] == "invalid_section"
    assert len(invalid.status()["sections"]) == len(SECTIONS)


def test_invalid_query_disables_diagnostic_without_unsafe_json_values() -> None:
    trace = WorkTrace()
    result = trace.overlap(float("nan"), 1)
    assert not result["enabled"] and result["covered_wall_ms"] is None and result["retention_loss"]
    json.dumps(result, allow_nan=False)


def test_deep_nesting_is_bounded_and_active_span_is_not_claimed_completed() -> None:
    clocks = Clocks()
    trace = clocks.trace()
    with trace.span("practice_step"):
        clocks.advance(.020, .001)
        pending = trace.overlap(0, .020)
        assert pending["active_spans"] == 1 and pending["covered_wall_ms"] == 0
    with ExitStack() as stack:
        for _ in range(MAX_DEPTH + 1):
            stack.enter_context(trace.span("practice_step"))
    assert trace.status()["error"] == "nesting_limit"


@pytest.mark.parametrize("failure", ["none", "enter", "exit", "business"])
def test_decorator_and_optional_context_keep_return_exception_and_execution_count(failure: str) -> None:
    class Broken:
        def span(self, _name: str) -> Broken:
            return self

        def __enter__(self) -> None:
            if failure == "enter":
                raise RuntimeError("observer entry")

        def __exit__(self, *_args: object) -> None:
            if failure == "exit":
                raise RuntimeError("observer exit")

    class Worker:
        work_trace: Any = None if failure == "none" else Broken()

        def __init__(self) -> None:
            self.calls = 0

        @observed("feed_tick")
        def run(self, value: int) -> int:
            self.calls += 1
            if failure == "business":
                raise ValueError("business")
            return value + 1

    worker = Worker()
    if failure == "business":
        with pytest.raises(ValueError, match="business"):
            worker.run(4)
    else:
        assert worker.run(4) == 5
    assert worker.calls == 1 and worker.run.__name__ == "run"
    with work_span(None, "feed_tick"):
        worker.calls += 1
    assert worker.calls == 2

"""Bounded observations of synchronous work on the shared speed-desk loop.

This module observes only. CPU belongs to the full span, even when its wall
interval is clipped by a query, and nested wall/CPU values must not be added.
The observer is intended for one event-loop thread; it neither moves work nor
changes persistence, callbacks, account operations, or their order.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from nightcrawler.speeddesk_workbins import WorkBins

MAX_SPANS = 512
MAX_DETAILS = 32
MAX_DEPTH = 64
SLOW_S = .005
SECTIONS = frozenset({
    "practice_checkpoint", "practice_daily_reports", "practice_state", "practice_panel",
    "practice_ledger", "practice_logs", "practice_mirror", "practice_step",
    "feed_tick", "feed_book", "feed_trade", "feed_windows", "feed_status",
    "live_checkpoint", "live_state", "live_ledger", "live_logs", "live_mirror", "live_reports", "live_panel",
    "kalshi_decode_apply", "coinbase_decode",
})


class WorkTrace:
    """Keep a fixed ring of slow spans and fixed per-section aggregates."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic,
                 thread_cpu: Callable[[], float] = time.thread_time) -> None:
        self.monotonic, self.thread_cpu = monotonic, thread_cpu
        self.enabled = True
        self.error: str | None = None
        self.errors = self.quiet = self.evicted = self.completed = 0
        self._next_id = 0
        self._active: list[int] = []
        self._spans: deque[dict[str, Any]] = deque(maxlen=MAX_SPANS)
        self._aggregates = {name: {"count": 0, "quiet": 0, "slow": 0,
                                  "max_wall_ms": 0.0, "max_cpu_ms": 0.0} for name in sorted(SECTIONS)}
        self._last_clocks: tuple[float, float] | None = None
        self._first_mono: float | None = None
        self._evicted_until: float | None = None
        self._bins = WorkBins()

    def _disable(self, reason: str) -> None:
        if self.enabled:
            self.errors += 1
            self.error = reason
            self.enabled = False
            self._active.clear()

    def _clocks(self) -> tuple[float, float]:
        wall, cpu = self.monotonic(), self.thread_cpu()
        if (isinstance(wall, bool) or isinstance(cpu, bool)
                or not isinstance(wall, (float, int)) or not isinstance(cpu, (float, int))
                or not math.isfinite(wall) or not math.isfinite(cpu) or wall < 0 or cpu < 0
                or (self._last_clocks is not None
                    and (wall < self._last_clocks[0] or cpu < self._last_clocks[1]))):
            raise ValueError("invalid observer clock")
        self._last_clocks = float(wall), float(cpu)
        return self._last_clocks

    def _begin(self, name: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            if name not in SECTIONS:
                self._disable("invalid_section")
                return None
            if len(self._active) >= MAX_DEPTH:
                self._disable("nesting_limit")
                return None
            wall, cpu = self._clocks()
            self._next_id += 1
            token = {"name": name, "span_id": self._next_id,
                     "parent_id": self._active[-1] if self._active else None,
                     "start_mono": wall, "cpu_start": cpu}
            self._active.append(self._next_id)
            if self._first_mono is None:
                self._first_mono = wall
            return token
        except Exception:  # noqa: BLE001 - a diagnostic cannot prevent the observed work.
            self._disable("observer_start_failed")
            return None

    def _finish(self, token: dict[str, Any] | None) -> None:
        if token is None or not self.enabled:
            return
        try:
            wall, cpu = self._clocks()
            elapsed, used = wall - token["start_mono"], cpu - token["cpu_start"]
            if not math.isfinite(elapsed * 1000) or not math.isfinite(used * 1000):
                raise ValueError("invalid observer interval")
            if not self._active or self._active.pop() != token["span_id"]:
                raise ValueError("invalid observer nesting")
            if token["parent_id"] is None:
                self._bins.record(token["start_mono"], wall, used)
            self.completed += 1
            aggregate = self._aggregates[token["name"]]
            aggregate["count"] += 1
            aggregate["max_wall_ms"] = max(aggregate["max_wall_ms"], elapsed * 1000)
            aggregate["max_cpu_ms"] = max(aggregate["max_cpu_ms"], used * 1000)
            if elapsed < SLOW_S:
                self.quiet += 1
                aggregate["quiet"] += 1
                return
            aggregate["slow"] += 1
            if len(self._spans) == MAX_SPANS:
                evicted = self._spans[0]
                self.evicted += 1
                self._evicted_until = max(self._evicted_until or 0.0, evicted["end_mono"])
            self._spans.append({"name": token["name"], "span_id": token["span_id"],
                                "parent_id": token["parent_id"], "start_mono": token["start_mono"],
                                "end_mono": wall, "wall_ms": elapsed * 1000, "cpu_ms": used * 1000})
        except Exception:  # noqa: BLE001 - preserve business exceptions and persistence behavior.
            self._disable("observer_finish_failed")

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        """Run work exactly once, with failures confined to this observer."""
        token = self._begin(name)
        try:
            yield
        finally:
            self._finish(token)

    def overlap(self, start: float, end: float, *, max_spans: int = MAX_DETAILS) -> dict[str, Any]:
        """Join completed slow work to an absolute monotonic interval.

        Covered wall uses ALL retained overlaps, including omitted detail rows.
        Quiet span details remain absent from slow-span coverage. A separate
        fixed time-bin lower bound includes quiet top-level work; the two
        overlapping coverage populations must never be added.
        Retention loss is conservative: eviction can make an earlier query
        incomplete even if the particular lost spans cannot be reconstructed.
        """
        try:
            if (isinstance(start, bool) or isinstance(end, bool)
                    or not isinstance(start, (float, int)) or not isinstance(end, (float, int))
                    or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start
                    or not math.isfinite((end - start) * 1000)):
                raise ValueError("invalid observer query")
            if isinstance(max_spans, bool) or not isinstance(max_spans, int) or max_spans < 0:
                raise ValueError("invalid detail bound")
            limit = min(max_spans, MAX_DETAILS)
            rows = [{**row, "overlap_start_mono": max(start, row["start_mono"]),
                     "overlap_end_mono": min(end, row["end_mono"]),
                     "overlap_wall_ms": (min(end, row["end_mono"]) - max(start, row["start_mono"])) * 1000}
                    for row in self._spans if start < end and row["start_mono"] < end and row["end_mono"] > start]
            intervals = sorted((row["overlap_start_mono"], row["overlap_end_mono"]) for row in rows)
            covered = 0.0
            right = start
            for left, finish in intervals:
                covered += max(0.0, finish - max(left, right))
                right = max(right, finish)
            details = sorted(rows, key=lambda row: (-row["overlap_wall_ms"], row["span_id"]))[:limit]
            details.sort(key=lambda row: (row["overlap_start_mono"], row["span_id"]))
            return {"enabled": self.enabled, "error": self.error, "start_mono": float(start),
                    "end_mono": float(end), "interval_wall_ms": (end - start) * 1000,
                    "spans": details, "retained_overlapping_spans": len(rows),
                    "omitted_spans": len(rows) - len(details), "covered_wall_ms": covered * 1000,
                    "unattributed_wall_ms": max(0.0, end - start - covered) * 1000,
                    "retention_loss": self._evicted_until is not None and start < self._evicted_until,
                    "evicted_spans": self.evicted,
                    "before_observation": self._first_mono is None or start < self._first_mono,
                    "active_spans": len(self._active), "quiet_spans_total": self.quiet,
                    "coverage_scope": "completed retained slow synchronous spans only",
                    "all_sync_work_lower_bound": self._bins.overlap(start, end),
                    "cpu_basis": "full span thread CPU; not apportioned to overlap; nested values are not additive"}
        except Exception:  # noqa: BLE001 - bad diagnostics cannot change account-read processing.
            self._disable("observer_query_failed")
            return {"enabled": False, "error": self.error, "spans": [], "retention_loss": True,
                    "coverage_scope": "unavailable", "covered_wall_ms": None, "unattributed_wall_ms": None}

    def status(self) -> dict[str, Any]:
        bins: dict[str, Any] = {"available": False}
        if self.enabled:
            try:
                bins = self._bins.status()
            except Exception:  # noqa: BLE001 - status is optional observation too.
                self._disable("observer_bin_status_failed")
        return {"enabled": self.enabled, "error": self.error, "completed": self.completed,
                "quiet": self.quiet, "evicted": self.evicted, "errors": self.errors,
                "retained": len(self._spans), "max_spans": MAX_SPANS,
                "max_details": MAX_DETAILS, "slow_threshold_ms": SLOW_S * 1000,
                "sections": {name: dict(values) for name, values in self._aggregates.items()},
                "all_sync_work_lower_bound": bins,
                "cpu_basis": "thread CPU; full and nested spans are not additive"}


P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def work_span(trace: WorkTrace | None, name: str) -> Iterator[None]:
    """Keep optional or replaced diagnostics outside the work's error path."""
    context = None
    try:
        if trace is not None:
            context = trace.span(name)
            context.__enter__()
    except Exception:  # noqa: BLE001 - a faulty observer cannot prevent the work.
        context = None
    try:
        yield
    finally:
        if context is not None:
            try:
                context.__exit__(None, None, None)
            except Exception:  # noqa: BLE001, S110 - preserve work; optional observer must add no callback I/O.
                pass


def observed(name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Observe synchronous methods with a ``work_trace`` attribute, if present."""
    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                trace = getattr(args[0], "work_trace", None) if args else None
            except Exception:  # noqa: BLE001 - even a replaced observer must not prevent the callback.
                trace = None
            with work_span(trace, name):
                return function(*args, **kwargs)
        return wrapped
    return decorate

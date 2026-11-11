"""Fixed-memory lower bounds for completed synchronous top-level work.

Keep no per-callback record. Wall occupancy splits at exact binary time-bin
boundaries; CPU is kept only for whole spans inside one bin, never prorated.
One event-loop thread owns this helper. It performs no I/O and reads no clocks.
"""

from __future__ import annotations

import math
from typing import Any

BIN_S = 1 / 32
MAX_BINS = 512


class WorkBins:
    """Retain at most sixteen seconds of observed occupancy in fixed arrays."""

    def __init__(self) -> None:
        self._epochs: list[int | None] = [None] * MAX_BINS
        self._wall = [0.0] * MAX_BINS
        self._cpu = [0.0] * MAX_BINS
        self._latest: int | None = None
        self._first: float | None = None
        self._end: float | None = None
        self.spans = self.clipped_spans = 0

    def record(self, start: float, end: float, cpu: float) -> None:
        """Accept sequential completed top-level spans from the validated owner."""
        if (not all(math.isfinite(value) for value in (start, end, cpu))
                or start < 0 or end < start or cpu < 0
                or (self._end is not None and start < self._end)):
            raise ValueError("invalid top-level work interval")
        first = math.floor(start / BIN_S)
        last = math.floor(math.nextafter(end, -math.inf) / BIN_S) if end > start else first
        self._latest = max(self._latest if self._latest is not None else last, last)
        floor = self._latest - MAX_BINS + 1
        if self._first is None:
            self._first = start
        self._end = end
        self.spans += 1
        if first < floor:
            self.clipped_spans += 1
        # At most MAX_BINS iterations even for a very long completed span.
        for epoch in range(max(first, floor), last + 1):
            slot = epoch % MAX_BINS
            if self._epochs[slot] != epoch:
                self._epochs[slot], self._wall[slot], self._cpu[slot] = epoch, 0.0, 0.0
            self._wall[slot] += max(0.0, min(end, (epoch + 1) * BIN_S) - max(start, epoch * BIN_S))
            if first == last:
                self._cpu[slot] += cpu

    def overlap(self, start: float, end: float) -> dict[str, Any]:
        """Count only fully contained retained bins, leaving both edges unknown."""
        if (not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start
                or not math.isfinite((end - start) * 1000)):
            raise ValueError("invalid work-bin query")
        first, last = math.ceil(start / BIN_S), math.floor(end / BIN_S) - 1
        query_bins = max(0, last - first + 1)
        floor = self._latest - MAX_BINS + 1 if self._latest is not None else 0
        left, right = max(first, floor), min(last, self._latest if self._latest is not None else -1)
        retained = max(0, right - left + 1)
        wall = cpu = 0.0
        populated = 0
        for epoch in range(left, right + 1):
            slot = epoch % MAX_BINS
            if self._epochs[slot] == epoch:
                wall += min(BIN_S, self._wall[slot])
                cpu += self._cpu[slot]
                populated += 1
        duration = end - start
        covered = min(duration, wall)
        cpu_ms = cpu * 1000
        if not math.isfinite(cpu_ms):
            raise ValueError("invalid aggregate work-bin CPU")
        return {
            "covered_wall_lower_bound_ms": covered * 1000,
            "unattributed_or_boundary_ms": max(0.0, duration - covered) * 1000,
            "contained_span_cpu_ms": cpu_ms,
            "cpu_basis": "whole top-level spans inside one retained full bin only; crossing spans omitted",
            "query_boundary_ms": max(0.0, duration - query_bins * BIN_S) * 1000,
            "query_full_bins": query_bins, "retained_full_bins": retained, "populated_full_bins": populated,
            "retention_loss": self._latest is not None and first < floor,
            "before_observation": self._first is None or start < self._first,
            "after_last_completed_span": self._end is None or end > self._end,
            "bin_ms": BIN_S * 1000, "capacity": MAX_BINS,
            "top_level_spans": self.spans, "clipped_spans": self.clipped_spans,
            "scope": "completed top-level synchronous work, including quiet spans; full bins only",
            "not_additive_to_slow_span_coverage": True,
        }

    def status(self) -> dict[str, Any]:
        return {"capacity": MAX_BINS, "bin_ms": BIN_S * 1000,
                "retention_s": MAX_BINS * BIN_S, "top_level_spans": self.spans,
                "clipped_spans": self.clipped_spans,
                "scope": "completed top-level synchronous work; conservative fully contained bins"}

"""Bounded observation of account reconciliation, with no trading capabilities.

All offsets use one process monotonic clock. Worker completion means the whole
client callback returned (all pages), not the exchange's first response byte.
The controller owns this object; workers only stamp their own read's two fields.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

MAX_READS, MAX_FILLS, MAX_CANCEL_SPANS = 12, 16, 8
MAX_REPORTS_PER_MINUTE = 12
SLOW_CYCLE_MS = 3000


@dataclass
class ReadSpan:
    name: str
    base: float
    marks: dict[str, float] = field(default_factory=dict)
    cancels: list[dict[str, Any]] = field(default_factory=list)
    cancel_calls: int = 0
    cancel_ms: float = 0
    cancel_spans_omitted: int = 0
    rows: int | None = None
    pages: int | None = None
    bytes: int | None = None

    def mark(self, name: str, mono: float) -> None:
        self.marks[name] = round((mono - self.base) * 1000, 3)

    def cancel(self, kind: str, start: float, end: float) -> None:
        self.cancel_calls += 1
        elapsed = max(0.0, end - start) * 1000
        self.cancel_ms += elapsed
        # No-op checks remain in totals, without filling the detailed span bound.
        if elapsed < 1:
            return
        if len(self.cancels) < MAX_CANCEL_SPANS:
            self.cancels.append({"kind": kind, "start_ms": round((start - self.base) * 1000, 3),
                                 "end_ms": round((end - self.base) * 1000, 3)})
        else:
            self.cancel_spans_omitted += 1

    def complete(self, rows: int | None, pages: int | None, byte_count: int | None) -> None:
        self.rows, self.pages, self.bytes = rows, pages, byte_count

    def result(self) -> dict[str, Any]:
        return {"read": self.name, "marks_ms": dict(self.marks), "rows": self.rows,
                "pages": self.pages, "bytes": self.bytes, "cancel_calls": self.cancel_calls,
                "cancel_ms": round(self.cancel_ms, 3), "cancel_spans": list(self.cancels),
                "cancel_spans_omitted": self.cancel_spans_omitted}


class ReconcileTrace:
    """Only one current cycle and a 12-element rate-limit deque are retained."""

    def __init__(self) -> None:
        self.sequence = 0
        self.active: dict[str, Any] | None = None
        self.reads: list[ReadSpan] = []
        self.previous_fills_returned_at: float | None = None
        self.emitted: deque[float] = deque(maxlen=MAX_REPORTS_PER_MINUTE)
        self.counts = {"cycles": 0, "reported": 0, "quiet": 0, "suppressed": 0}
        self.base = 0.0

    def begin(self, at: float, mono: float, full: bool, retry_remaining_s: float) -> None:
        self.sequence += 1
        self.counts["cycles"] += 1
        self.base, self.reads = mono, []
        self.active = {"cycle": self.sequence, "started_at": at, "full": full,
                       "retry_remaining_s": max(0.0, retry_remaining_s),
                       "previous_fills_returned_at": self.previous_fills_returned_at,
                       "marks_ms": {}, "new_fills": [], "new_fills_omitted": 0,
                       "reads_omitted": 0}

    def mark(self, name: str, mono: float) -> None:
        if self.active is not None:
            self.active["marks_ms"][name] = round((mono - self.base) * 1000, 3)

    def read_start(self, name: str, mono: float) -> ReadSpan | None:
        if self.active is None:
            return None
        if len(self.reads) >= MAX_READS:
            self.active["reads_omitted"] += 1
            return None
        span = ReadSpan(name, self.base)
        span.mark("submitted", mono)
        self.reads.append(span)
        return span

    def fills_returned(self, at: float, mono: float) -> None:
        self.previous_fills_returned_at = at
        self.mark("fills_wrapper_returned", mono)

    def fill(self, fill_id: str, fill_at: float, mono: float) -> None:
        if self.active is None:
            return
        if len(self.active["new_fills"]) < MAX_FILLS:
            self.active["new_fills"].append({"fill_id": fill_id, "venue_fill_at": fill_at,
                                             "registered_ms": round((mono - self.base) * 1000, 3)})
        else:
            self.active["new_fills_omitted"] += 1

    def finish(self, at: float, mono: float, failed: bool) -> dict[str, Any] | None:
        row, self.active = self.active, None
        reads, self.reads = self.reads, []
        if row is None:
            return None
        elapsed = max(0.0, mono - self.base) * 1000
        if not failed and not row["new_fills"] and elapsed < SLOW_CYCLE_MS:
            self.counts["quiet"] += 1
            return None
        while self.emitted and mono - self.emitted[0] >= 60:
            self.emitted.popleft()
        if len(self.emitted) >= MAX_REPORTS_PER_MINUTE:
            self.counts["suppressed"] += 1
            return None
        self.emitted.append(mono)
        self.counts["reported"] += 1
        return {"at": at, "mode": "diagnostic", "version": 1, **row,
                "elapsed_ms": round(elapsed, 3), "failed": failed,
                "reads": [span.result() for span in reads], "counts": dict(self.counts),
                "clock_basis": "monotonic_offsets_from_started_at",
                "worker_complete_basis": "entire_client_callback_not_http_arrival",
                "not_realized_pnl": True, "max_reports_per_60s": MAX_REPORTS_PER_MINUTE}

    def status(self) -> dict[str, Any]:
        return {"mode": "diagnostic", "enabled": True, "version": 1,
                "counts": dict(self.counts), "max_reports_per_60s": MAX_REPORTS_PER_MINUTE,
                "max_reads": MAX_READS, "max_new_fills": MAX_FILLS,
                "max_cancel_spans_per_read": MAX_CANCEL_SPANS,
                "previous_fills_returned_at": self.previous_fills_returned_at,
                "session_only": True}

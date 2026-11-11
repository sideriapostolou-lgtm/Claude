"""Bounded own-order queue observations. These measurements have no trading or simulated-fill authority."""

from __future__ import annotations

import asyncio
import math
import re
import time
import uuid
from collections import Counter, deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any

from .speeddesk_kalshi_client import KalshiClientError, OwnQueueReader

CADENCE_S, MAX_CANDIDATES, MAX_BUFFERED = 1.0, 32, 64
MAX_AGE_S = 3.0


@dataclass(frozen=True)
class QueueContext:
    client_order_id: str
    order_id: str
    window: str
    side: str
    price: float
    remaining: float
    status: str
    twin_order_id: int
    twin_queue_ahead: float | None
    twin_remaining: float | None


def _bounded_context(value: QueueContext) -> bool:
    strings = (value.client_order_id, value.order_id, value.window, value.side, value.status)
    numbers = (value.price, value.remaining, value.twin_queue_ahead, value.twin_remaining)
    return (all(isinstance(item, str) and len(item) <= 128 for item in strings)
            and type(value.twin_order_id) is int and 0 <= value.twin_order_id <= 2**63 - 1
            and all(item is None or isinstance(item, (int, float)) and not isinstance(item, bool)
                    and math.isfinite(item) and abs(item) <= 1e18 for item in numbers))


class QueueObserver:
    """One background GET at most; results are joined on the event loop and flushed at existing saves.

    Its task deliberately does not belong to the controller's execution workers. Shutdown may stop
    dispatch immediately, cancel real orders first, and only then drain/close this observer.
    """

    def __init__(self, reader: OwnQueueReader | None, *, clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.reader, self.clock, self.monotonic = reader, clock, monotonic
        self.task: asyncio.Future[dict[str, Any]] | None = None
        self.worker: Future[dict[str, Any]] | None = None
        self.executor: ThreadPoolExecutor | None = None
        self.session_id = uuid.uuid4().hex
        self.context: QueueContext | None = None
        self.next_at = -math.inf
        self.stopping = self.disabled = False
        self.failures = 0
        self.rotation = 0
        self.counts: Counter[str] = Counter()
        self.rows: deque[dict[str, Any]] = deque(maxlen=MAX_BUFFERED)
        self.last: dict[str, Any] | None = None
        self.tracked: deque[str] = deque(maxlen=MAX_CANDIDATES)

    def register(self, client_id: str) -> None:
        """Only newly acknowledged ordinary owned maker IDs enter this bounded registry."""
        if len(self.tracked) == MAX_CANDIDATES:
            self.counts["registry_dropped"] += 1
        self.tracked.append(client_id)

    def _read(self, context: QueueContext, selected_at: float, selected_mono: float) -> dict[str, Any]:
        started, mono = self.clock(), self.monotonic()
        try:
            assert self.reader is not None
            value = self.reader.read(context.order_id)
            if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,12}\.[0-9]{2}", value) is None:
                raise KalshiClientError("queue_position", "observer_invalid_response")
            result: dict[str, Any] = {"queue_position_fp": value, "reason": "observed", "http_status": 200}
        except KalshiClientError as exc:
            result = {"queue_position_fp": None, "reason": exc.reason, "http_status": exc.status}
        except Exception:  # noqa: BLE001 - never propagate optional worker failures or response text.
            result = {"queue_position_fp": None, "reason": "observer_worker_error", "http_status": None}
        returned_mono = self.monotonic()
        return {**result, "selected_at": selected_at, "worker_started_at": started,
                "response_returned_at": self.clock(), "worker_elapsed_ms": (returned_mono - mono) * 1000,
                "selection_to_worker_ms": (mono - selected_mono) * 1000,
                "selection_to_return_ms": (returned_mono - selected_mono) * 1000}

    def _finish(self, current: Callable[[QueueContext], QueueContext | None], *, enabled: bool) -> None:
        # Cancelling an asyncio wrapper does not stop an HTTP thread. Only the underlying Future proves
        # completion, permits another dispatch, or allows the Session to close.
        if self.worker is None or not self.worker.done() or self.context is None:
            return
        worker, context = self.worker, self.context
        self.task, self.worker, self.context = None, None, None
        try:
            result = worker.result()
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - optional failure has no execution authority
            result = {"queue_position_fp": None, "reason": "observer_worker_error", "http_status": None,
                      "selected_at": self.clock(), "worker_started_at": self.clock(),
                      "response_returned_at": self.clock(), "worker_elapsed_ms": None,
                      "selection_to_worker_ms": None, "selection_to_return_ms": None}
        reason = result["reason"]
        self.counts[reason] += 1
        clock_values = [result.get(key) for key in
                        ("selected_at", "worker_started_at", "response_returned_at", "worker_elapsed_ms",
                         "selection_to_worker_ms", "selection_to_return_ms")]
        clock_values.append(self.clock())
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
               for value in clock_values):
            self.counts["invalid_clock"] += 1
            self.disabled = True
            return
        if reason == "observer_budget_busy":
            return  # quota pressure is a count, not an ever-growing stream of missing observations
        if reason != "observed":
            self.failures += 1
            self.next_at = max(self.next_at, self.monotonic() + min(60.0, 2.0 ** min(self.failures, 6)))
            if result["http_status"] in (401, 403):
                self.disabled = True
        else:
            self.failures = 0
        after = current(context)
        if after is not None and not _bounded_context(after):
            self.counts["invalid_context"] += 1
            after = None
        changes = []
        if after is None:
            changes.append("ownership_or_order_missing")
        else:
            for field in ("client_order_id", "order_id", "window", "side", "price", "remaining", "status",
                          "twin_order_id", "twin_queue_ahead", "twin_remaining"):
                if getattr(after, field) != getattr(context, field):
                    changes.append(field)
        if not enabled:
            changes.append("observer_gate_closed")
        stale = (result["selection_to_return_ms"] > MAX_AGE_S * 1000
                 or not 0 <= self.clock() - result["response_returned_at"] <= MAX_AGE_S)
        state = ("unknown_error" if reason != "observed" else "unknown_stale" if stale else
                 "unknown_context_changed" if changes else "observed_interval_only")
        row = {"at": self.clock(), "version": 1, "session_id": self.session_id,
               "event": "speeddesk_live_queue", "window": context.window,
               "client_order_id": context.client_order_id, "order_id": context.order_id,
               **result, "status": state, "context_changes": changes, "stale": stale,
               "dispatch": asdict(context), "completion": asdict(after) if after is not None else None,
               "clock_basis": "local_selection_worker_return_intervals; includes_budget_signing_decode; not_network_RTT",
               "venue_snapshot_time": None,
               "authority": "diagnostic_only; no_queue_or_fill_override"}
        if len(self.rows) == MAX_BUFFERED:
            self.counts["buffer_dropped"] += 1
        self.rows.append(row)
        self.last = row

    def poll(self, candidates: list[QueueContext], current: Callable[[QueueContext], QueueContext | None], *,
             enabled: bool) -> None:
        self._finish(current, enabled=enabled)
        if self.stopping or self.disabled or self.reader is None or not enabled:
            return
        now = self.monotonic()
        if not math.isfinite(now):
            self.counts["invalid_clock"] += 1
            self.disabled = True
            return
        if now < self.next_at:
            return
        if self.worker is not None:
            self.counts["busy"] += 1
            self.next_at = now + CADENCE_S
            return
        eligible = []
        for item in candidates[:MAX_CANDIDATES]:
            if not _bounded_context(item):
                self.counts["invalid_context"] += 1
            elif item.status == "resting":
                eligible.append(item)
        if len(candidates) > MAX_CANDIDATES:
            self.counts["candidate_omitted"] += len(candidates) - MAX_CANDIDATES
        if not eligible:
            self.counts["no_candidate"] += 1
            self.next_at = now + CADENCE_S
            return
        context = eligible[self.rotation % len(eligible)]
        self.rotation += 1
        self.context = context
        self.next_at = now + CADENCE_S
        self.counts["started"] += 1
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kalshi-queue")
        self.worker = self.executor.submit(self._read, context, self.clock(), now)
        self.task = asyncio.wrap_future(self.worker)
        self.task.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    def drain(self) -> list[dict[str, Any]]:
        rows = list(self.rows)
        self.rows.clear()
        return rows

    def status(self) -> dict[str, Any]:
        return {"mode": "diagnostic", "version": 1, "session_id": self.session_id,
                "enabled": self.reader is not None and not self.disabled and not self.stopping,
                "in_flight": self.worker is not None, "buffered": len(self.rows), "max_buffered": MAX_BUFFERED,
                "cadence_s": CADENCE_S, "counts": dict(self.counts), "last": self.last,
                "registry_size": len(self.tracked), "registry_limit": MAX_CANDIDATES,
                "coverage": "new_owned_ordinary_rest_acks_only; no_history_or_recovered_order_backfill",
                "publication": "next_existing_checkpoint", "financial_authority": False}

    def stop(self) -> None:
        self.stopping = True

    async def close(self, current: Callable[[QueueContext], QueueContext | None]) -> None:
        self.stop()
        if self.worker is not None:
            try:
                await asyncio.shield(asyncio.wrap_future(self.worker))
            except Exception:  # noqa: BLE001 - consume optional worker failure in _finish below.
                self.counts["shutdown_worker_error"] += 1
            self._finish(current, enabled=False)
        self.close_idle(current)
        # The controller already saved final financial state before draining optional HTTP. Do not force a
        # second checkpoint for a late diagnostic; retain the loss count and explicitly leave it unpublished.
        self.counts["shutdown_unpublished"] += len(self.rows)
        self.rows.clear()

    def close_idle(self, current: Callable[[QueueContext], QueueContext | None]) -> bool:
        """A synchronous close never shuts a connection under an outstanding worker."""
        self.stop()
        if self.worker is not None and not self.worker.done():
            return False
        self._finish(current, enabled=False)
        if self.reader is not None:
            self.reader.close()
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
        return True

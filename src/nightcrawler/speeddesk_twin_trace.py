"""Bounded, session-only evidence for the existing approximate practice twin.

No clock, persistence, feed, financial book or order decisions live here. Every
terminal fact comes from an actual practice event, never from an absent mapping.
"""

from __future__ import annotations

import math
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import TypeAlias

from .speeddesk_model import Decision, PracticeOrder

Scalar: TypeAlias = str | int | float | bool | None
Row: TypeAlias = dict[str, Scalar]
VERSION = 1
MAX_PENDING = 128
MAX_TERMINAL = 256
MAX_TEXT = 128


@dataclass(frozen=True)
class OrderState:
    order_id: int
    window: str
    side: str
    kind: str
    price: float
    remaining: float
    queue_ahead: float | None
    placed_at: float | None
    active_at: float | None


def capture(order: PracticeOrder | None) -> OrderState | None:
    """Read only scalar current fields; the caller isolates all extraction errors."""
    if order is None:
        return None
    values = (
        order.price,
        order.remaining,
        order.queue_ahead,
        order.placed_at,
        order.active_at,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("nonfinite_twin_snapshot")
    return OrderState(
        order.order_id,
        order.window,
        order.side,
        order.kind,
        order.price,
        order.remaining,
        order.queue_ahead,
        order.placed_at,
        order.active_at,
    )


class TwinTrace:
    def __init__(self, session: str) -> None:
        if not session or len(session) > MAX_TEXT:
            raise ValueError("invalid_trace_session")
        self.session = session
        self.pending: deque[Row] = deque()
        self.terminal: OrderedDict[int, Row] = OrderedDict()
        self.pending_dropped = 0
        self.terminal_evicted = 0
        self.identities_omitted = 0

    def _text(self, value: str | None) -> str | None:
        if value is None or len(value) <= MAX_TEXT:
            return value
        # Never truncate an identity into a misleading exact association.
        self.identities_omitted += 1
        return None

    def _row(self, action: str, at: float) -> Row:
        if not math.isfinite(at):
            raise ValueError("nonfinite_trace_clock")
        return {"version": VERSION, "session": self.session, "action": action, "at": at}

    def _snapshot(self, state: OrderState | None) -> Row:
        if state is None:
            return {
                "twin_queue_ahead": None,
                "twin_remaining": None,
                "twin_placed_at": None,
                "twin_active_at": None,
            }
        return {
            "twin_queue_ahead": state.queue_ahead,
            "twin_remaining": state.remaining,
            "twin_placed_at": state.placed_at,
            "twin_active_at": state.active_at,
        }

    def _append(self, row: Row) -> None:
        self._validate(row)
        if len(self.pending) == MAX_PENDING:
            self.pending.popleft()
            self.pending_dropped += 1
        self.pending.append(row)

    @staticmethod
    def _validate(row: Row) -> None:
        if type(row) is not dict:
            raise ValueError("invalid_trace_row")
        if len(row) > 40 or any(type(key) is not str or len(key) > 64 for key in row):
            raise ValueError("unbounded_trace_fields")
        for value in row.values():
            if value is not None and type(value) not in (str, int, float, bool):
                raise ValueError("invalid_trace_scalar")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("nonfinite_trace_scalar")
            if isinstance(value, str) and len(value) > MAX_TEXT:
                raise ValueError("unbounded_trace_text")
            if isinstance(value, int) and value.bit_length() > 63:
                raise ValueError("unbounded_trace_integer")

    def event(
        self,
        event: Decision,
        current: PracticeOrder | None,
        *,
        parent_client_id: str | None = None,
        parent_twin_id: int | None = None,
        scope: str = "practice_model",
        before: OrderState | None = None,
    ) -> None:
        if event.event not in {
            "speeddesk_rest",
            "speeddesk_take",
            "speeddesk_skip",
            "speeddesk_cancel",
            "speeddesk_fill",
        }:
            return
        after = capture(current)
        state = before if before is not None else after
        action = (
            "copy"
            if event.event in {"speeddesk_rest", "speeddesk_take", "speeddesk_skip"}
            else "cancel"
            if event.event == "speeddesk_cancel"
            else "practice_fill"
        )
        row = {
            **self._row(action, event.at),
            "window": self._text(event.window),
            "side": self._text(event.side),
            "twin_order_id": event.order_id,
            "parent_client_order_id": self._text(parent_client_id),
            "parent_twin_order_id": parent_twin_id,
            "scope": self._text(scope),
            "practice_event": event.event,
            "reason": self._text(event.reason),
            "snapshot_basis": "pre_removal"
            if before is not None
            else "current_after_event"
            if after
            else "event_only",
            **self._snapshot(state),
        }
        if event.event == "speeddesk_cancel":
            # Decision.size is cancelled remaining quantity; it is not a queue.
            if before is None:
                row["twin_remaining"] = event.size
            row["terminal_state"] = "cancelled"
        elif event.event == "speeddesk_fill":
            row["practice_fill_size"] = event.size
            row["terminal_state"] = (
                "terminal_after_fill" if current is None else "partial_fill"
            )
            if current is None:
                # IOC residual can be removed after a partial execution, so
                # absence proves neither full requested fill nor its residual.
                row["twin_remaining"] = None
                row["remaining_basis"] = "unknown_after_order_removal"
        self._validate(row)
        if (
            event.event == "speeddesk_cancel"
            or event.event == "speeddesk_fill"
            and current is None
        ):
            self.terminal[event.order_id] = dict(row)
            self.terminal.move_to_end(event.order_id)
            if len(self.terminal) > MAX_TERMINAL:
                self.terminal.popitem(last=False)
                self.terminal_evicted += 1
        self._append(row)

    def real_fill(
        self,
        *,
        client_id: str,
        twin_id: int,
        window: str,
        side: str,
        fill_id: str,
        venue_fill_at: float,
        observed_at: float,
        current: PracticeOrder | None,
    ) -> None:
        row = {
            **self._row("real_fill_reconcile", observed_at),
            "client_order_id": self._text(client_id),
            "twin_order_id": twin_id,
            "window": self._text(window),
            "side": self._text(side),
            "fill_id": self._text(fill_id),
            "venue_fill_at": venue_fill_at,
            "observation_basis": "snapshot_during_reconcile_not_venue_fill_time",
            "clock_basis": "fills_batch_return",
            "snapshot_time_exact": False,
        }
        if (
            current is not None
            and current.order_id == twin_id
            and current.window == window
            and current.side == side
        ):
            row.update(self._snapshot(capture(current)))
            row["twin_state"] = "current_order"
        else:
            terminal = self.terminal.get(twin_id)
            if (
                terminal is not None
                and terminal["window"] == window
                and terminal["side"] == side
                and twin_id > 0
            ):
                row.update(
                    {
                        key: terminal[key]
                        for key in (
                            "twin_queue_ahead",
                            "twin_remaining",
                            "twin_placed_at",
                            "twin_active_at",
                        )
                    }
                )
                row["twin_state"] = "observed_terminal"
                row["terminal_state"] = terminal["terminal_state"]
                row["terminal_at"] = terminal["at"]
                row["terminal_reason"] = terminal["reason"]
                row["terminal_snapshot_basis"] = terminal["snapshot_basis"]
            else:
                row.update(self._snapshot(None))
                row["twin_state"] = "unknown_absent_or_unmapped"
        self._append(row)

    def drain(self, *, failures: int = 0, error: str | None = None) -> list[Row]:
        rows = list(self.pending)
        self.pending.clear()
        for row in rows:
            row.update(
                {
                    "pending_dropped": self.pending_dropped,
                    "terminal_evicted": self.terminal_evicted,
                    "identities_omitted": self.identities_omitted,
                    "helper_failures": failures,
                    "helper_error": error,
                }
            )
        return rows

    def status(self) -> Row:
        return {
            "version": VERSION,
            "session": self.session,
            "pending": len(self.pending),
            "max_pending": MAX_PENDING,
            "pending_dropped": self.pending_dropped,
            "terminal_cached": len(self.terminal),
            "max_terminal": MAX_TERMINAL,
            "terminal_evicted": self.terminal_evicted,
            "identities_omitted": self.identities_omitted,
        }


def validated_rows(value: object) -> list[Row]:
    """Validate an observer return before any diagnostic enters financial pending."""
    if type(value) is not list or len(value) > MAX_PENDING:
        raise ValueError("invalid_trace_batch")
    for row in value:
        TwinTrace._validate(row)
        if (
            type(row.get("at")) not in (int, float)
            or not math.isfinite(row["at"])
            or type(row.get("version")) is not int
            or row["version"] != VERSION
            or type(row.get("session")) is not str
            or not row["session"]
            or type(row.get("action")) is not str
        ):
            raise ValueError("missing_trace_clock_or_identity")
    return value


def validated_status(value: object) -> Row:
    if type(value) is not dict:
        raise ValueError("invalid_trace_status")
    TwinTrace._validate(value)
    return value

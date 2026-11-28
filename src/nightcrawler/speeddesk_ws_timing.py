"""Bounded, diagnostic-only native WebSocket message residence timings.

Use ``create_connection=TimingClientConnection`` with websockets.asyncio.client.
Acceptance is after the library processes the final data frame. Residence includes
library buffering and event-loop scheduling; it isn't NIC, kernel or provider
latency. No payload, frame, header or request is retained by this observer.
"""
from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Any, Literal, overload

from websockets.asyncio.client import ClientConnection
from websockets.frames import Frame, Opcode
from websockets.protocol import Event
from websockets.typing import Data


@dataclass(frozen=True, slots=True)
class ReceiptTiming:
    ordinal: int
    status: str
    accepted_monotonic: float | None = None
    accepted_wall: float | None = None
    received_monotonic: float | None = None
    received_wall: float | None = None
    residence_ms: float | None = None

    def as_dict(self) -> dict[str, int | float | str | None]:
        return asdict(self)


class TimingClientConnection(ClientConnection):
    """Preserve native receive behavior; single complete-message reader only.

    Unsupported streaming/concurrent readers permanently disable timing claims.
    Cancellation or a failed recv consumes no ordinal. Overflow loses the oldest
    stamps, never shifts a later stamp onto an earlier received message.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._timing_stamps: deque[tuple[int, float, float]] = deque(maxlen=256)
        self._timing_accepted = 0
        self._timing_received = 0
        self._timing_overflow = 0
        self._timing_dropped_through = 0
        self._timing_unknown = 0
        self._timing_known = 0
        self._timing_max_residence_ms = 0.0
        self._timing_errors = 0
        self._timing_unsupported = 0
        self._timing_disabled = False
        self._timing_fragmented = False
        self._timing_readers = 0
        self._timing_last_accepted: tuple[float, float] | None = None
        self.last_receipt: ReceiptTiming | None = None

    def timing_status(self) -> dict[str, int | float]:
        """Cumulative counts; accepted stops on disable, known counts samples.

        Received counts all successful complete-message receives. Max residence
        describes only known samples, never total traffic or missing coverage.
        """
        return {
            "accepted": self._timing_accepted,
            "received": self._timing_received,
            "retained": len(self._timing_stamps),
            "overflow": self._timing_overflow,
            "unknown": self._timing_unknown,
            "known": self._timing_known,
            "max_residence_ms": self._timing_max_residence_ms,
            "disabled": int(self._timing_disabled),
            "errors": self._timing_errors,
            "unsupported": self._timing_unsupported,
        }

    def _disable_timing(self) -> None:
        self._timing_disabled = True
        self._timing_stamps.clear()
        # A previous receipt mustn't appear usable after correspondence is lost.
        self.last_receipt = None

    def process_event(self, event: Event) -> None:
        super().process_event(event)
        try:
            self._observe_event(event)
        except Exception:  # noqa: BLE001 - diagnostics must not break native receive
            self._timing_errors += 1
            self._disable_timing()

    def _observe_event(self, event: Event) -> None:
        if self._timing_disabled or not isinstance(event, Frame):
            return
        if event.opcode in (Opcode.TEXT, Opcode.BINARY):
            if self._timing_fragmented:
                self._disable_timing()
                return
            self._timing_fragmented = not event.fin
        elif event.opcode is Opcode.CONT:
            if not self._timing_fragmented:
                self._disable_timing()
                return
            self._timing_fragmented = not event.fin
        else:
            return
        if event.fin:
            monotonic, wall = time.monotonic(), time.time()
            previous = self._timing_last_accepted
            if (not math.isfinite(monotonic) or not math.isfinite(wall)
                    or (previous is not None
                        and (monotonic < previous[0] or wall < previous[1]))):
                raise ValueError("invalid diagnostic acceptance clocks")
            self._timing_last_accepted = (monotonic, wall)
            self._timing_accepted += 1
            stamp = (self._timing_accepted, monotonic, wall)
            if len(self._timing_stamps) == self._timing_stamps.maxlen:
                self._timing_overflow += 1
                self._timing_dropped_through = self._timing_stamps[0][0]
            self._timing_stamps.append(stamp)

    def _record_receipt(self) -> None:
        ordinal = self._timing_received
        if self._timing_disabled:
            self.last_receipt = ReceiptTiming(ordinal, "disabled")
            self._timing_unknown += 1
            return
        received, received_wall = time.monotonic(), time.time()
        if not math.isfinite(received) or not math.isfinite(received_wall):
            raise ValueError("invalid diagnostic receipt clocks")
        if self._timing_stamps and self._timing_stamps[0][0] == ordinal:
            _, accepted, wall = self._timing_stamps.popleft()
            if received < accepted or received_wall < wall:
                raise ValueError("backwards diagnostic receipt clocks")
            residence_ms = (received - accepted) * 1000
            if not math.isfinite(residence_ms):
                raise ValueError("invalid diagnostic residence")
            self.last_receipt = ReceiptTiming(
                ordinal, "known", accepted, wall, received, received_wall, residence_ms,
            )
            self._timing_known += 1
            self._timing_max_residence_ms = max(self._timing_max_residence_ms, residence_ms)
            return
        if (ordinal <= self._timing_dropped_through and self._timing_stamps
                and self._timing_stamps[0][0] > ordinal):
            self.last_receipt = ReceiptTiming(
                ordinal, "overflow", received_monotonic=received, received_wall=received_wall,
            )
        else:
            # Missing or out-of-order metadata cannot establish correspondence.
            self._disable_timing()
            self.last_receipt = ReceiptTiming(
                ordinal, "unknown", received_monotonic=received, received_wall=received_wall,
            )
        self._timing_unknown += 1

    @overload
    async def recv(self, decode: Literal[True]) -> str: ...

    @overload
    async def recv(self, decode: Literal[False]) -> bytes: ...

    @overload
    async def recv(self, decode: bool | None = None) -> Data: ...

    async def recv(self, decode: bool | None = None) -> Data:
        self._timing_readers += 1
        if self._timing_readers > 1:
            self._timing_unsupported += 1
            self._disable_timing()
        try:
            message = await super().recv(decode)
            # No await between successful native recv and its ordinal/stamp match.
            self._timing_received += 1
            try:
                self._record_receipt()
            except Exception:  # noqa: BLE001 - diagnostics must not break native receive
                self._timing_errors += 1
                self._timing_unknown += 1
                self._disable_timing()
            return message
        finally:
            self._timing_readers -= 1

    @overload
    def recv_streaming(self, decode: Literal[True]) -> AsyncIterator[str]: ...

    @overload
    def recv_streaming(self, decode: Literal[False]) -> AsyncIterator[bytes]: ...

    @overload
    def recv_streaming(self, decode: bool | None = None) -> AsyncIterator[Data]: ...

    async def recv_streaming(self, decode: bool | None = None) -> AsyncIterator[Data]:
        self._timing_unsupported += 1
        self._disable_timing()
        async for fragment in super().recv_streaming(decode):
            yield fragment

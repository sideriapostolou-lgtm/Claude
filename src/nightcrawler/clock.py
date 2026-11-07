"""Time abstraction so the engine, HTTP retries and backtests are deterministic.

Convention: all timestamps in nightcrawler are **epoch seconds, UTC, as float**
(``Clock.now()``), except candle open times which are ``int`` epoch seconds.
Durations carry their unit in the name (``*_s``, ``*_min``, ``*_h``).

Use :class:`RealClock` in production and :class:`FakeClock` in tests and the
backtester. Never call ``time.time()`` / ``time.sleep()`` directly in modules
that take a clock.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "RealClock", "FakeClock", "utc_day", "iso_utc", "minute_floor"]


@runtime_checkable
class Clock(Protocol):
    """Anything with ``now()`` (epoch seconds UTC, float) and ``sleep(seconds)``."""

    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class RealClock:
    """Wall clock. ``sleep`` is interruptible through an optional ``stop_event``.

    When ``stop_event`` is set (e.g. by a SIGTERM handler), any in-progress or
    future ``sleep`` returns immediately so the engine can shut down promptly.
    """

    def __init__(self, stop_event: threading.Event | None = None) -> None:
        self.stop_event = stop_event

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self.stop_event is not None:
            self.stop_event.wait(seconds)
        else:
            time.sleep(seconds)


class FakeClock:
    """Manually advanced clock for tests and backtests.

    ``sleep(s)`` does not block: it records ``s`` in :attr:`sleeps` and advances
    the clock by ``s``. Thread-safe.
    """

    def __init__(self, start: float = 1_791_475_200.0) -> None:  # 2026-10-08T16:00:00Z
        self._now = float(start)
        self._lock = threading.Lock()
        self.sleeps: list[float] = []

    def now(self) -> float:
        with self._lock:
            return self._now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            s = max(0.0, float(seconds))
            self.sleeps.append(s)
            self._now += s

    def advance(self, seconds: float) -> float:
        """Move time forward by ``seconds`` (must be >= 0); returns the new now()."""
        if seconds < 0:
            raise ValueError("FakeClock cannot go backwards")
        with self._lock:
            self._now += float(seconds)
            return self._now

    def set(self, ts: float) -> None:
        """Jump to absolute epoch seconds ``ts`` (must not be in the past)."""
        with self._lock:
            if ts < self._now:
                raise ValueError("FakeClock cannot go backwards")
            self._now = float(ts)


def utc_day(ts: float) -> str:
    """UTC calendar day of epoch seconds ``ts`` as ``YYYY-MM-DD``."""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def iso_utc(ts: float | None) -> str | None:
    """ISO-8601 UTC string with ``Z`` suffix and second precision (None -> None)."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def minute_floor(ts: float) -> int:
    """Start of the UTC minute containing ``ts`` (int epoch seconds)."""
    return int(ts // 60 * 60)

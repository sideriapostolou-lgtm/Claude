"""This process's memory, in megabytes, for status lines and heartbeats: ``rss_mb`` (resident now, from
``/proc/self/statm``) and ``max_rss_mb`` (the high-water mark, ``getrusage``). Bounded cost (one small file read and
one system call), standard library only, never raises: a platform without either figure reports it as None."""

from __future__ import annotations

import os
import sys
from typing import Any

__all__ = ["process_memory"]

_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_MB = 1 << 20


def _rss_bytes() -> int | None:
    try:
        with open("/proc/self/statm", "rb") as stream:
            fields = stream.read().split()
        return int(fields[1]) * _PAGE
    except (OSError, ValueError, IndexError):
        return None


def _max_rss_bytes() -> int | None:
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:  # noqa: BLE001 - a platform without getrusage reports None
        return None
    # Linux reports kilobytes, macOS bytes.
    return int(peak) if sys.platform == "darwin" else int(peak) * 1024


def process_memory() -> dict[str, Any]:
    """``{"rss_mb": float | None, "max_rss_mb": float | None}`` for the calling process."""
    rss, peak = _rss_bytes(), _max_rss_bytes()
    return {"rss_mb": None if rss is None else round(rss / _MB, 1),
            "max_rss_mb": None if peak is None else round(peak / _MB, 1)}

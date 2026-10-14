"""This process's memory for status lines: resident now and its high-water mark, never an exception."""

from __future__ import annotations

import os
from typing import Any

import pytest

from nightcrawler import procmem
from nightcrawler.procmem import process_memory


def test_process_memory_reports_megabytes_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    figures = process_memory()
    assert set(figures) == {"rss_mb", "max_rss_mb"}
    if os.path.exists("/proc/self/statm"):
        assert figures["rss_mb"] is not None and 5 < figures["rss_mb"] < 10_000
        assert figures["max_rss_mb"] is not None and figures["max_rss_mb"] >= figures["rss_mb"] - 1
    ballast = bytearray(64 << 20)
    grown = process_memory()
    if os.path.exists("/proc/self/statm"):
        assert grown["max_rss_mb"] >= figures["max_rss_mb"]
    del ballast

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("synthetic")

    monkeypatch.setattr(procmem, "open", broken, raising=False)
    monkeypatch.setattr("builtins.open", broken)
    assert process_memory()["rss_mb"] is None  # a platform without /proc: unknown, not an error

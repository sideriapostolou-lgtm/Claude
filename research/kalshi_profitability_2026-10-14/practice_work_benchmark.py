"""Offline mixed-history callback benchmark; no network, credentials or venue orders.

From the repository root:
  PYTHONPATH=src:tests python research/kalshi_profitability_2026-10-14/practice_work_benchmark.py

Uses the exact locally available 13bf55b model methods as its baseline. The new
methods come from the working tree. Synthetic history proportions are explicit;
they are not a measurement of production's unresolved settlement count. Timing
depends on the host; correctness belongs in the deterministic regression tests.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from fakes import FakeClock
from test_speeddesk_runtime import runner_at

from nightcrawler import speeddesk_model
from nightcrawler.speeddesk_model import Book, Level, Settlement, Window

BASELINE = "13bf55bdd1b594ab340630e0755affdf97c6fdf5"
METHODS = ("on_book", "blocked", "advance", "evaluate")


def baseline_methods() -> dict[str, Any]:
    # Only committed local source is executed, never a downloaded payload.
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:src/nightcrawler/speeddesk_model.py"], text=True)
    parsed = ast.parse(source)
    model = next(node for node in parsed.body if isinstance(node, ast.ClassDef) and node.name == "PracticeDesk")
    methods = {}
    for node in model.body:
        if isinstance(node, ast.FunctionDef) and node.name in METHODS:
            namespace: dict[str, Any] = {}
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            exec(segment, vars(speeddesk_model), namespace)  # noqa: S102 — pinned local source, not user input
            methods[node.name] = namespace[node.name]
    assert set(methods) == set(METHODS)
    return methods


def install(methods: dict[str, Any]) -> None:
    for name, method in methods.items():
        setattr(speeddesk_model.PracticeDesk, name, method)


def run() -> dict[str, Any]:
    old = baseline_methods()
    new = {name: getattr(speeddesk_model.PracticeDesk, name) for name in METHODS}
    rows = []
    with tempfile.TemporaryDirectory(prefix="speeddesk-benchmark-") as directory:
        now = 1_791_989_400.0
        runner = runner_at(Path(directory), FakeClock(now))
        runner.arena = None
        assert runner.live is not None
        try:
            for index in range(399):
                end = now - (399 - index) * 900
                slug = f"KXBTC15M-FAKE-{index}"
                window = Window(slug, end - 900, end, 80000, venue="kalshi", venue_start_price=80000)
                closed = Settlement(slug, end, True, 0, 0, 0, 0, 0, 0, 0, 0)
                for desk in (runner.desk, runner.live.twin):
                    desk.add_window(window)
                    if index < 173:
                        desk.closed.append(closed)
            slug = "KXBTC15M-ACTIVE"
            runner.on_windows([Window(slug, now - 20, now + 880, 80000,
                                      venue="kalshi", venue_start_price=80000)])
            runner.opening_logged = set(runner.desk.windows)
            runner.feed_status["trade_stream"] = True
            runner.checkpoint(now)
            bids = tuple(Level(.49 - index * .0001, 100) for index in range(111))
            asks = tuple(Level(.51 + index * .0001, 100) for index in range(168))
            events = []
            for index in range(150):
                changed = (*bids[:55], replace(bids[55], size=100 + index % 3), *bids[56:])
                opposite = tuple(Level(1 - row.price, row.size) for row in changed)
                no = tuple(Level(1 - row.price, row.size) for row in asks)
                events.extend([Book(slug, "up", changed, asks, now, str(index), now),
                               Book(slug, "down", no, opposite, now, str(index), now)])
            for pass_number in range(3):
                for label, methods in (("baseline_13bf55b", old), ("working_tree", new)):
                    install(methods)
                    # New quotes arrive as new objects. Do not reuse warmed Book
                    # caches across timed passes; construction is outside timing.
                    fresh_events = [replace(book) for book in events]
                    wall, cpu = time.perf_counter(), time.thread_time()
                    for book in fresh_events:
                        runner.on_book(book)
                    rows.append({"version": label, "pass": pass_number, "callbacks": len(events),
                                 "wall_ms": (time.perf_counter() - wall) * 1000,
                                 "cpu_ms": (time.thread_time() - cpu) * 1000})
        finally:
            install(new)
            runner.close()
    return {"baseline": BASELINE, "inputs": {"windows_per_desk": 400, "closed_per_desk": 173,
            "unresolved_expired_per_desk": 226, "active_windows": 1, "desks": ["original", "live_twin"],
            "yes_levels": 111, "no_levels": 168, "updates_per_pass": 150, "callbacks_per_pass": 300},
            "metric": "thread CPU milliseconds; wall milliseconds also recorded",
            "book_cache": "fresh Book objects per timed pass, constructed outside timing",
            "limits": "Synthetic callback CPU comparison; no orders, network, production history or live latency measured.",
            "rows": rows}


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    print(json.dumps(run(), indent=2, allow_nan=False))

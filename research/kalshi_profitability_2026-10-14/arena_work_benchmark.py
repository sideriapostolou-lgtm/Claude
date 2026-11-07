"""Read-only CPU comparison for the practice arena's busy, deep-book path.

Run from the repository with PYTHONPATH=src. Uses no network or credentials;
each synthetic arena uses a temporary directory. This measures execution cost,
not profitable fills, live scheduling, or complete production coverage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import marshal
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any

from nightcrawler import speeddesk_model
from nightcrawler.kalshi_arena import (
    ArenaConfig,
    KalshiArena,
    WireView,
    book_wire,
    trade_wire,
)
from nightcrawler.speeddesk_model import (
    Book,
    Level,
    PracticeDesk,
    PracticeOrder,
    Trade,
    Window,
)

BASELINE = "13bf55b"
START = 1_791_478_800.0
NOW = START + 1
METHODS = ("on_book", "advance", "blocked")


def market_payload(count: int) -> tuple[Window, bytes, dict[str, tuple[Level, ...]],
                                         dict[str, tuple[Level, ...]], int]:
    window = Window("KXBTC15M-benchmark", START, START + 900, None,
                    venue_start_price=80_000, venue="kalshi")
    bids = {side: tuple(Level(round(0.49 - n / 1000, 4), 10 + n) for n in range(depth))
            for side, depth in (("up", 111), ("down", 168))}
    asks = {side: tuple(Level(round(1 - level.price, 4), level.size) for level in levels)
            for side, levels in bids.items()}
    previous: dict[str, tuple[tuple[Level, ...], tuple[Level, ...]]] = {}
    records: list[Any] = []
    prints = 0
    for sequence in range(count // 2):
        changed = "up" if sequence % 2 else "down"
        index = sequence % len(bids[changed])
        price, size = bids[changed][index].price, 11 + sequence % 100
        bids[changed] = bids[changed][:index] + (Level(price, size),) + bids[changed][index + 1:]
        asks[changed] = asks[changed][:index] + (Level(round(1 - price, 4), size),) + asks[changed][index + 1:]
        for side, other in (("up", "down"), ("down", "up")):
            book = Book(window.slug, side, bids[side], asks[other], NOW, str(sequence), NOW)  # type: ignore[arg-type]
            records.append(book_wire(book, previous.get(side)))
            previous[side] = (book.bids, book.asks)
        if sequence % 50 == 0:
            records.append(trade_wire(Trade(window.slug, "up", 0.6, 1, NOW, str(sequence), "sell", NOW)))
            prints += 1
    return window, marshal.dumps(("batch", 1, NOW, 0, 0, records), 2), bids, asks, prints


def sample(window: Window, payload: bytes, bids: dict[str, tuple[Level, ...]],
           asks: dict[str, tuple[Level, ...]], expected: int) -> float:
    view = WireView(windows=(window,), bitcoin_price=80_000, bitcoin_at=NOW,
                    sigma=0.0003, maker_windows=frozenset({window.slug}))
    with tempfile.TemporaryDirectory(prefix="arena-work-") as temporary:
        arena = KalshiArena(ArenaConfig(Path(temporary)), lambda: view, clock=lambda: START - 1)
        arena._windows(view, START)
        arena.clock = lambda: NOW
        arena.tape.feed(80_000, NOW, 0.0003)
        for resident in arena.residents.values():
            for side, other in (("up", "down"), ("down", "up")):
                resident.desk.on_book(Book(window.slug, side, bids[side], asks[other],  # type: ignore[arg-type]
                                          NOW, "initial", NOW))
            resident.desk.orders[1] = PracticeOrder(1, window.slug, "up", "rest", 0.20, 1, 1,
                                                   NOW - 1, NOW - 0.75, 0.5, 0.07)
        started = time.thread_time()
        arena.receive(marshal.loads(payload), view)
        arena._drain(NOW)
        elapsed = time.thread_time() - started
        assert arena.received == expected
        assert arena.coalesced == 0 and arena.late == 0 and not arena.degraded
        assert sum(len(resident.desk.orders) for resident in arena.residents.values()) == 12
        return round(elapsed, 4)


def compare(iterations: int, books: int) -> dict[str, Any]:
    source = subprocess.run(["git", "show", f"{BASELINE}:src/nightcrawler/speeddesk_model.py"],
                            check=True, capture_output=True, text=True).stdout
    legacy = types.ModuleType("nightcrawler._arena_benchmark_legacy_model")
    sys.modules[legacy.__name__] = legacy
    exec(compile(source, "baseline_model.py", "exec"), legacy.__dict__)  # noqa: S102
    methods = {name: getattr(PracticeDesk, name) for name in METHODS}
    window, payload, bids, asks, prints = market_payload(books)
    results: dict[str, list[float]] = {}
    try:
        for label in ("baseline", "optimized"):
            for name, method in methods.items():
                setattr(PracticeDesk, name, getattr(legacy.PracticeDesk, name) if label == "baseline" else method)
            results[label] = [sample(window, payload, bids, asks, books + prints) for _ in range(iterations)]
    finally:
        for name, method in methods.items():
            setattr(PracticeDesk, name, method)
        del sys.modules[legacy.__name__]
    return {
        "baseline": BASELINE,
        "optimized_model_sha256": hashlib.sha256(Path(speeddesk_model.__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "iterations": iterations,
        "books": books,
        "trades": prints,
        "side_depths": [111, 168],
        "residents": 12,
        "orders_per_resident": 1,
        "metric": "thread CPU seconds: marshal decode + receive + drain",
        "results": results,
        "median_speedup": statistics.median(results["baseline"]) / statistics.median(results["optimized"]),
        "assertions": {"all_events_received": True, "coalesced": 0, "late": 0,
                       "degraded_windows": 0, "resting_orders_retained": 12},
        "limitations": "Fake frozen-clock load; excludes producer and scheduling; no profitability or coverage claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--books", type=int, default=3000, help="Positive even book count")
    args = parser.parse_args()
    if args.iterations < 1 or args.books < 2 or args.books % 2:
        parser.error("iterations must be positive; books must be positive and even")
    print(json.dumps(compare(args.iterations, args.books), indent=2))


if __name__ == "__main__":
    main()

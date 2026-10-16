"""Fake-data local helper cost; excludes I/O and does not measure production latency or profit."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from functools import partial
from pathlib import Path

from nightcrawler.speeddesk_live_completion import (
    external_asks,
    maker_price,
    starter_fit,
)
from nightcrawler.speeddesk_live_model import LiveIntent, LiveLimits, LiveRiskBook
from nightcrawler.speeddesk_model import Book, Level, Window

WINDOW = "KXBTC15M-BENCH-CURRENT"
PAST = "KXBTC15M-BENCH-PAST"


def fixture(retained: int, current: int) -> tuple[LiveRiskBook, Book]:
    risk = LiveRiskBook(LiveLimits(window_usd=20, open_usd=40, clip=5, fee_precision=.0001))
    risk.add_window(Window(PAST, 0, 900, 100, taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    risk.settle(PAST, False, 900, "bench-settlement", net_payout_usd=0)
    risk.add_window(Window(WINDOW, 1000, 1900, 100, taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    risk.update_cash(100, 1010)
    for index in range(retained + current):
        window = PAST if index < retained else WINDOW
        identity = f"nc-speed-bench-{index}"
        risk.intents[identity] = LiveIntent(identity, window, "up", "rest", .57, 5, 1005, .57,
                                           status="canceled", reservation_active=False)
    risk._index()
    market = Book(WINDOW, "down", (), tuple(Level(i / 1000, 10000) for i in range(1, 1000)),
                  1010, "synthetic", source="rest", requested_at=1010)
    return risk, market


def timing(function: object, runs: int = 40) -> dict[str, float]:
    assert callable(function)
    function()
    samples = []
    for _ in range(runs):
        start = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    ordered = sorted(samples)
    return {"runs": runs, "median_ms": statistics.median(samples),
            "p95_ms": ordered[int((runs - 1) * .95)], "max_ms": max(samples)}


def main() -> None:
    results = []
    for retained, current in ((0, 0), (10000, 100), (50000, 500)):
        risk, market = fixture(retained, current)
        levels = external_asks(risk, WINDOW, "down", market)
        entry = timing(partial(starter_fit, risk, WINDOW, "up", "rest", .97, 5, levels))
        no_fit = timing(partial(starter_fit, risk, WINDOW, "up", "rest", .99, 5, [(1.0, 5)]))
        depth = timing(partial(external_asks, risk, WINDOW, "down", market))
        risk.inventory[WINDOW].up.shares = 5
        risk.inventory[WINDOW].up.cost = 2.85
        risk._index_key = None
        risk._index()
        hedge = timing(partial(maker_price, risk, WINDOW, "down", .97, 5, 1010))
        assert maker_price(risk, WINDOW, "down", .97, 5, 1010) == .42
        results.append({"retained_terminal_orders": retained, "current_terminal_orders": current,
                        "book_levels": len(market.asks), "clip": 5,
                        "starter_search": entry, "starter_no_fit_99_ticks": no_fit,
                        "external_depth": depth, "maker_fallback": hedge})
    root = Path(__file__).resolve().parents[2]
    hashes = {name: hashlib.sha256((root / "src/nightcrawler" / name).read_bytes()).hexdigest()
              for name in ("speeddesk_live.py", "speeddesk_live_model.py", "speeddesk_live_completion.py")}
    print(json.dumps({"scope": "Local synthetic helper timings only; hot indexes; no venue, network or ledger I/O",
                      "source_sha256": hashes, "cases": results}, indent=2))


if __name__ == "__main__":
    main()

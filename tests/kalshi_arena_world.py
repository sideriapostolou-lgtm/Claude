"""A synthetic Kalshi Bitcoin 15-minute market for the arena's tests: windows, books, sell prints and outcomes,
published the way the speed desk publishes them (``LiveSnapshot``) and fed through the town's own inbox, in the test's
process (the link and the town's process have their own tests: tests/test_kalshi_arena_feed.py)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fakes import FakeClock

from nightcrawler.kalshi_arena import ArenaConfig, KalshiArena
from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, Trade, Window

T0 = 1_791_475_200.0 + 3600  # 2026-10-08 17:00 UTC, a window boundary
SIGMA = 0.0003


def kalshi_window(start: float, strike: float | None = 80_000.0, length: float = 900.0) -> Window:
    return Window(f"KXBTC15M-{int(start)}", start, start + length, None, taker_coefficient=0.07, maker_coefficient=0.0,
                  venue_start_price=strike, venue="kalshi", fee_rounding="kalshi")


@dataclass
class Market:
    """Drive a town through simulated time; every book and print goes through ``arena.feed_*`` like the runner."""

    path: Path
    population: int = 12
    seed: int = 7
    length: float = 900.0  # shorter windows keep a test quick; nothing in the arena assumes 15 minutes
    clock: FakeClock = field(default_factory=lambda: FakeClock(T0 - 5))
    price: float = 80_000.0
    windows: list[Window] = field(default_factory=list)
    outcomes: dict[str, bool] = field(default_factory=dict)
    snap: LiveSnapshot = field(default_factory=LiveSnapshot)
    arena: Any = None
    books: int = 0
    trades: int = 0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.config = ArenaConfig(data_dir=self.path, population=self.population)

    def start(self, **kwargs: Any) -> KalshiArena:
        self.publish()
        self.arena = KalshiArena(self.config, lambda: self.snap, clock=self.clock.now, **kwargs)
        return self.arena

    def publish(self) -> None:
        now = self.clock.now()
        live = tuple(window for window in self.windows if window.end > now - 3600)
        current = {window.slug for window in live if window.start <= now < window.end}
        self.snap = LiveSnapshot(windows=live, bitcoin_price=self.price, bitcoin_at=now, sigma=SIGMA,
                                 maker_windows=frozenset(current), outcomes=dict(self.outcomes))

    def fair_up(self, window: Window, now: float) -> float:
        strike = window.venue_start_price or self.price
        left = max(1.0, window.end - now)
        z = math.log(self.price / strike) / (SIGMA * math.sqrt(left))
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))

    def run(self, seconds: float, *, step_s: float = 0.25, book_every: int = 2, trade_every: int = 3,
            drift: float = 0.0, step: bool = True, book_rounds: int = 1) -> None:
        """Advance ``seconds``: a new window every 15 minutes, books (``book_rounds`` per side) and prints for the
        open one, outcomes 5 s after each close, and one arena pass per ``step_s`` (when ``step``)."""
        ticks = round(seconds / step_s)
        for index in range(ticks):
            now = self.clock.now()
            start = T0 + math.floor((now - T0) / self.length) * self.length
            if not any(window.start == start for window in self.windows) and now >= T0 - 60:
                self.windows.append(kalshi_window(start, round(self.price, 2), self.length))
            self.price *= math.exp(drift * step_s + self.rng.gauss(0, SIGMA * math.sqrt(step_s)))
            for window in self.windows:
                if window.slug not in self.outcomes and now >= window.end + 5:
                    self.outcomes[window.slug] = self.price >= (window.venue_start_price or 0)
            self.publish()
            for window in self.windows:
                if not window.start <= now < window.end or self.arena is None:
                    continue
                up = self.fair_up(window, now)
                if index % book_every == 0:
                    for round_ in range(book_rounds):
                        for side, fair in (("up", up), ("down", 1 - up)):
                            ask = round(min(0.99, max(0.01, fair + 0.02 + self.rng.uniform(-0.01, 0.01))), 2)
                            bid = round(max(0.01, ask - 0.03), 2)
                            self.arena.feed_book(Book(window.slug, side, (Level(bid, 20),),  # type: ignore[arg-type]
                                                      (Level(ask, 40),), now, f"{side}-{now}-{round_}", now))
                            self.books += 1
                if index % trade_every == 0:
                    side = self.rng.choice(("up", "down"))
                    fair = up if side == "up" else 1 - up
                    price = round(min(0.99, max(0.01, fair - 0.03 + self.rng.uniform(-0.03, 0.02))), 2)
                    self.arena.feed_trade(Trade(window.slug, side, price, round(self.rng.uniform(1, 8)),  # type: ignore[arg-type]
                                                now - 0.05, f"t{index}-{now}", "sell", now))
                    self.trades += 1
            if step and self.arena is not None:
                self.arena.step(now)
            self.clock.advance(step_s)

"""The Kalshi arena never slows or breaks the live speed desk: the feed's cost, isolation, and the scheduler."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import statistics
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from kalshi_arena_world import T0, Market, kalshi_window

from nightcrawler import kalshi_arena
from nightcrawler.config import Settings
from nightcrawler.kalshi_arena import QUEUE_MAX, ArenaConfig, ArenaFeed, KalshiArena
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, Trade, Window

SLUG = "KXBTC15M-feed"


class LocalFeeds:
    """No network; no maker_windows, so every print passes the runner's gate once the trade stream is up."""

    def __init__(self, _settings: Settings, **_callbacks: Any) -> None:
        pass

    async def settlement(self, _slug: str) -> None:
        return None

    async def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.01)


class SpyLive:
    """A live companion that only counts what the runner hands it."""

    def __init__(self, _settings: Settings, _path: Path, snapshot: Any, **_kwargs: Any) -> None:
        self.snapshot = snapshot
        self.calls: Counter[str] = Counter()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("on_") or name == "observe_market":
            return lambda *_args: self.calls.update([name])
        raise AttributeError(name)

    def panel(self) -> dict[str, Any]:
        return {}

    async def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.01)

    async def shutdown(self) -> None:
        pass

    def close(self) -> None:
        pass


class Spy:
    """Records every use of the arena by the live loop."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.calls.append(name)
        return lambda *_args, **_kwargs: None


def runner_at(path: Path, clock: FakeClock, **settings: Any) -> SpeedRunner:
    return SpeedRunner(Settings(data_dir=path, **settings), threading.Event(), clock=clock,
                       feed_factory=LocalFeeds, live_factory=SpyLive)


def prepare(runner: SpeedRunner, clock: FakeClock, *, start: float | None = None) -> str:
    """A Kalshi window with a live trade stream and a fresh Bitcoin price."""
    now = clock.now()
    start = now - 60 if start is None else start
    runner.on_windows([Window(SLUG, start, start + 900, 80000, taker_coefficient=.07, maker_coefficient=0,
                              venue_start_price=80000, venue="kalshi", fee_rounding="kalshi")])
    runner.on_tick(80000, now, now)
    runner.on_status({"coinbase": "connected", "trade_stream": True, "markets": "connected"})
    return SLUG


def book(at: float, n: int) -> Book:
    return Book(SLUG, "up" if n % 2 else "down", (Level(.30, 2),), (Level(.60, 10),), at, f"b{n}", at)


def trade(at: float, n: int) -> Trade:
    return Trade(SLUG, "up", .30, 1, at, f"t{n}", "sell", at)


def p99(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[int(0.99 * len(ordered))]


def wait_for(check: Any, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return bool(check())


# ---------------------------------------------------------------------- the producer side
def test_ticks_and_windows_never_reach_the_arena(tmp_path: Path) -> None:
    clock = FakeClock(T0)
    runner = runner_at(tmp_path, clock)
    try:
        prepare(runner, clock)
        spy = Spy()
        runner.arena = spy
        for n in range(10_000):
            clock.advance(0.01)
            runner.on_tick(80000 + n % 7, clock.now(), clock.now())
        runner.on_windows(list(runner.desk.windows.values()))
        runner.step(clock.now())
        assert spy.calls == []  # no arena code on a Bitcoin tick, a window list or the runner's step
        runner.on_book(book(clock.now(), 1))
        runner.on_trade(trade(clock.now(), 1))
        assert spy.calls == ["feed_book", "feed_trade"]
    finally:
        runner.arena = None
        runner.close()


def test_a_put_is_one_bounded_append_that_never_raises() -> None:
    feed = ArenaFeed(QUEUE_MAX)
    item = ("book", book(T0, 1))
    started = time.perf_counter()
    for _ in range(100_000):
        feed.put(item)
    per_put_us = (time.perf_counter() - started) / 100_000 * 1e6
    assert per_put_us < 5, per_put_us  # about 0.2 us here
    assert len(feed) == feed.puts == QUEUE_MAX and feed.dropped == 100_000 - QUEUE_MAX
    feed.queue = None  # type: ignore[assignment]  # even a broken queue cannot raise into the live loop
    feed.put(item)
    feed.closed = True
    feed.put(item)
    assert feed.dropped == 100_000 - QUEUE_MAX + 1


def test_the_live_loop_pays_almost_nothing_per_book_and_print(tmp_path: Path) -> None:
    clock = FakeClock(T0)
    runner = runner_at(tmp_path, clock)
    try:
        prepare(runner, clock)
        arena = runner.arena
        assert isinstance(arena, KalshiArena)
        before = arena.feed.puts + arena.feed.dropped  # the status update in prepare() is one gap event
        on: list[float] = []
        off: list[float] = []
        n = 0
        for block in range(20):  # interleaved, so drift hits both alike
            runner.arena = arena if block % 2 else None
            sink = on if block % 2 else off
            for _ in range(1000):
                n += 1
                clock.advance(0.001)
                now = clock.now()
                started = time.perf_counter_ns()
                runner.on_book(book(now, n))
                runner.on_trade(trade(now, n))
                sink.append((time.perf_counter_ns() - started) / 1e6)
        extra_mean, extra_p99 = statistics.fmean(on) - statistics.fmean(off), p99(on) - p99(off)
        assert extra_mean < 0.02 and extra_p99 < 0.5, (extra_mean, extra_p99)
        assert arena.feed.puts + arena.feed.dropped - before == 20_000  # every book and print of its blocks
    finally:
        runner.close()


# ---------------------------------------------------------------------- isolation
def test_a_parked_arena_never_blocks_the_live_loop_and_counts_its_drops(tmp_path: Path) -> None:
    clock = FakeClock(T0)
    runner = runner_at(tmp_path, clock)
    stop, release, parked = threading.Event(), threading.Event(), threading.Event()
    try:
        prepare(runner, clock)
        arena = runner.arena
        assert isinstance(arena, KalshiArena) and isinstance(runner.live, SpyLive)
        real_step = arena.step

        def park(now: float) -> None:
            parked.set()
            release.wait(10)
            real_step(now)

        arena.step = park  # type: ignore[method-assign]
        arena.poll_s = 0.01
        arena.start(stop)
        assert parked.wait(5)
        queued = len(arena.feed)  # the status update in prepare()
        calls = QUEUE_MAX + 3000
        times = []
        for n in range(calls // 2):
            clock.advance(0.001)
            started = time.perf_counter_ns()
            runner.on_book(book(clock.now(), n))
            runner.on_trade(trade(clock.now(), n))
            times.append((time.perf_counter_ns() - started) / 1e6)
        runner.step(clock.now())
        dropped = calls + queued - QUEUE_MAX
        assert len(arena.feed) == QUEUE_MAX and arena.feed.dropped == dropped  # exactly the overflow
        assert runner.live.calls["on_book"] >= calls // 2 and runner.live.calls["on_trade"] >= calls // 2
        assert statistics.fmean(times) < 0.5, statistics.fmean(times)
        release.set()
        assert wait_for(lambda: len(arena.feed) == 0)  # it resumes and drains
        assert wait_for(lambda: (tmp_path / "kalshi_arena" / "panel.json").exists())
        assert kalshi_arena.panel_state(tmp_path, clock.now())["feed"]["dropped"] == dropped
    finally:
        stop.set()
        release.set()
        runner.close()


def test_a_crashing_arena_halts_itself_and_the_live_desk_trades_on(tmp_path: Path, caplog: Any) -> None:
    clock = FakeClock(T0)
    runner = runner_at(tmp_path, clock)
    stop = threading.Event()
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    try:
        prepare(runner, clock)
        arena = runner.arena
        assert isinstance(arena, KalshiArena) and isinstance(runner.live, SpyLive)

        def boom(_now: float) -> None:
            raise RuntimeError("synthetic arena fault")

        arena.step = boom  # type: ignore[method-assign]
        arena.poll_s = 0.001
        arena.start(stop)
        assert arena._thread is not None
        arena._thread.join(5)
        assert not arena._thread.is_alive() and arena.feed.closed and arena.errors == kalshi_arena.HALT_AFTER
        assert arena.problem and "live desk is unaffected" in arena.problem
        dropped, books = arena.feed.dropped, runner.live.calls["on_book"]
        runner.on_book(book(clock.now() + 1, 1))
        runner.on_trade(trade(clock.now() + 1, 1))
        runner.step(clock.now() + 1)
        assert arena.feed.dropped == dropped + 2 and len(arena.feed) == 0  # later puts are counted no-ops
        assert runner.live.calls["on_book"] == books + 1 and runner.live.calls["on_trade"] >= 1
        assert caplog.text.count("kalshi_arena_step_failed error=RuntimeError") == kalshi_arena.HALT_AFTER
        assert "kalshi_arena_halted error=RuntimeError" in caplog.text and "synthetic" not in caplog.text
        assert kalshi_arena.panel_state(tmp_path, clock.now())["problem"] == arena.problem
    finally:
        stop.set()
        runner.close()


def test_an_arena_that_cannot_start_leaves_the_desk_trading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           caplog: Any) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(kalshi_arena, "KalshiArena", broken)
    clock = FakeClock(T0)
    runner = runner_at(tmp_path / "broken", clock)
    try:
        assert runner.arena is None and "kalshi_arena_not_started error=RuntimeError" in caplog.text
        prepare(runner, clock)
        runner.on_book(book(clock.now(), 1))
        runner.on_trade(trade(clock.now(), 1))
        runner.step(clock.now())
        assert isinstance(runner.live, SpyLive) and runner.live.calls["on_book"] == 1
    finally:
        runner.close()
    monkeypatch.undo()
    for settings in ({"kalshi_arena_enabled": False}, {"speeddesk_kalshi_enabled": False}):
        off = runner_at(tmp_path / str(len(settings)) / next(iter(settings)), clock, **settings)
        try:
            assert off.arena is None
        finally:
            off.close()


def test_the_shared_stop_event_ends_the_arena_and_close_never_waits(tmp_path: Path) -> None:
    clock = FakeClock(T0)
    runner = runner_at(tmp_path, clock)
    arena = runner.arena
    assert isinstance(arena, KalshiArena)
    arena.start(runner.stop)
    assert arena._thread is not None and wait_for(lambda: arena.saved_at > 0)
    runner.stop.set()
    arena._thread.join(1.0)
    assert not arena._thread.is_alive()

    parked_runner = runner_at(tmp_path / "parked", clock)
    parked = parked_runner.arena
    assert isinstance(parked, KalshiArena)
    hold, entered = threading.Event(), threading.Event()
    parked.step = lambda _now: entered.set() or hold.wait(10)  # type: ignore[assignment, method-assign, func-returns-value]
    parked.start(parked_runner.stop)
    assert entered.wait(5)
    started = time.monotonic()
    parked_runner.close()
    assert time.monotonic() - started < 0.2  # close() sets an event; it never joins the practice thread
    hold.set()
    assert parked._thread is not None
    parked._thread.join(1.0)
    assert not parked._thread.is_alive()


def test_the_speed_desk_run_starts_and_stops_the_arena(tmp_path: Path) -> None:
    runner = runner_at(tmp_path, FakeClock(T0))
    arena = runner.arena
    assert isinstance(arena, KalshiArena)
    timer = threading.Timer(0.3, runner.stop.set)
    timer.start()
    try:
        asyncio.run(runner.run())
    finally:
        timer.cancel()
        runner.close()
    assert arena._thread is not None
    arena._thread.join(1.0)
    assert not arena._thread.is_alive() and (tmp_path / "kalshi_arena" / "state.json").exists()


def test_the_arena_never_changes_the_runners_windows_or_books(tmp_path: Path) -> None:
    clock = FakeClock(T0 - 5)
    runner = runner_at(tmp_path, clock)
    try:
        arena = runner.arena
        assert isinstance(arena, KalshiArena)
        arena._sleep = lambda _seconds: None
        prepare(runner, clock, start=T0)
        fed = []
        for n in range(40):
            clock.set(T0 + 1 + n * 0.5)
            runner.on_tick(80000 + n, clock.now(), clock.now())
            fed.append(book(clock.now(), n))
            runner.on_book(fed[-1])
            runner.on_trade(trade(clock.now(), n))
            arena.step(clock.now())
        windows = copy.deepcopy(list(runner.desk.windows.values()))
        published = copy.deepcopy(runner.live_snapshot().windows)
        books = dict(runner.desk.books)
        clock.set(T0 + 905)
        runner.desk.settle(SLUG, True, clock.now())
        runner._refresh_live_snapshot()
        arena.step(clock.now())
        assert arena.town["windows"] == 1 and SLUG not in arena.windows
        assert list(runner.desk.windows.values()) == windows and runner.live_snapshot().windows == published
        assert all(runner.desk.books[key] is value for key, value in books.items())
        assert books[(SLUG, "up")] is fed[-1] or books[(SLUG, "down")] is fed[-1]
    finally:
        runner.close()


# ---------------------------------------------------------------------- the scheduler
def test_work_slices_stay_short_and_each_ends_with_a_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A synthetic hour-like load: 12 residents, about 60 books and 3 prints a second, a settled window."""
    monkeypatch.setattr(kalshi_arena, "STATUS_EVERY_S", 1e12)
    market = Market(tmp_path, seed=3, length=300)  # a shorter window keeps the test quick; the load is per second
    rests: list[float] = []
    # CPU time, so another process on a shared machine cannot fake a long slice (the opt-in test below and the
    # production status line measure wall time).
    arena = market.start(perf=time.thread_time, sleep=rests.append)
    sink: list[float] = []

    class Tap(deque):  # type: ignore[type-arg]
        def append(self, value: float) -> None:
            sink.append(value)
            super().append(value)

    arena.slices = Tap(maxlen=kalshi_arena.SLICES_KEEP)
    passes = 3_300  # 330 simulated seconds, a pass every 0.1 s: one window opens, trades and settles
    market.run(passes * 0.1, step_s=0.1, book_every=1, book_rounds=3, trade_every=3)
    assert arena.town["windows"] >= 1 and any(res.row["traded"] for res in arena.residents.values())
    assert market.books > 50 * 300 and arena.feed.dropped == 0
    ordered = sorted(sink)
    median, p99_ms = ordered[len(ordered) // 2] * 1000, ordered[int(0.99 * len(ordered))] * 1000
    assert median < 0.3 and p99_ms < 0.5, (median, p99_ms)
    assert len(rests) == len(sink) - passes and all(rest == kalshi_arena.REST_S for rest in rests)
    assert sum(sink) < 0.02 * passes * 0.1  # under 2 % of one core (about 0.5 % measured)


@pytest.mark.skipif(os.environ.get("NIGHTCRAWLER_PERF_TESTS") != "1",
                    reason="wall-clock timing; set NIGHTCRAWLER_PERF_TESTS=1 to run")
def test_the_arena_thread_barely_delays_a_one_millisecond_loop(tmp_path: Path) -> None:
    """The live loop's view: a thread that sleeps 1 ms at a time, feeding about 50 books and 3 prints a second,
    while the arena's thread runs the town in real time in alternate half-second blocks (parked in between, which
    costs nothing), so drift on a shared machine hits both conditions alike."""
    window = kalshi_window(time.time() + 1.0)
    view = {"snap": LiveSnapshot()}
    arena = KalshiArena(ArenaConfig(data_dir=tmp_path), lambda: view["snap"])
    running, stop = threading.Event(), threading.Event()
    real_step = arena.step

    def gated(now: float) -> None:
        while not running.wait(0.05):
            if stop.is_set():
                return
        real_step(time.time())

    arena.step = gated  # type: ignore[method-assign]
    arena.start(stop)
    samples: dict[bool, list[float]] = {True: [], False: []}
    n = 0
    try:
        for block in range(28):
            on = block % 2 == 1
            running.set() if on else running.clear()
            began = time.perf_counter()
            while time.perf_counter() - began < 0.5:
                t0 = time.perf_counter()
                time.sleep(0.001)
                samples[on].append((time.perf_counter() - t0 - 0.001) * 1000)
                n += 1
                now = time.time()
                if n % 10 == 0:
                    view["snap"] = LiveSnapshot(windows=(window,), bitcoin_price=80_000 + n % 13, bitcoin_at=now,
                                                sigma=0.0003, maker_windows=frozenset({window.slug}))
                if window.start <= now and n % 20 == 0:
                    arena.feed_book(Book(window.slug, "up" if n % 40 else "down", (Level(.47, 20),),
                                         (Level(.52, 40),), now, f"b{n}", now))
                if window.start <= now and n % 300 == 0:
                    arena.feed_trade(Trade(window.slug, "up", .46, 3, now, f"t{n}", "sell", now))
    finally:
        stop.set()
        running.set()
    off, loaded = samples[False], samples[True]
    rise = p99(loaded) - p99(off)
    print(f"lateness ms: parked p50 {statistics.median(off):.3f} p99 {p99(off):.3f} max {max(off):.3f}; running "
          f"p50 {statistics.median(loaded):.3f} p99 {p99(loaded):.3f} max {max(loaded):.3f}; p99 rise {rise:.3f}; "
          f"arena {arena.telemetry(time.time())}")
    assert any(res.desk.orders or res.desk.windows for res in arena.residents.values())  # the town was trading
    assert rise < 0.5

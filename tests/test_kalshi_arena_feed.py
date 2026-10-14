"""The Kalshi arena never slows or breaks the live speed desk: the link's cost, the town's own process, isolation.

The town runs in a child process (``nightcrawler.kalshi_arena.worker_main``). These tests start real ones: the town
itself, and stand-ins that never read, spin on every core or die, to show what the live loop pays in each case.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import statistics
import sys
import threading
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from kalshi_arena_world import T0, kalshi_window

from nightcrawler import kalshi_arena
from nightcrawler.config import Settings
from nightcrawler.kalshi_arena import (
    PENDING_MAX,
    ArenaConfig,
    ArenaLink,
    apply_ladder,
    book_from_wire,
    book_wire,
    frame,
    ladder_change,
    worker_command,
)
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, Trade, Window

SLUG = "KXBTC15M-feed"
ROOT = str(Path(kalshi_arena.__file__).resolve().parent.parent)


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
        self.closed = False

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
        self.closed = True


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


class Ladders:
    """A Kalshi ladder as the market socket keeps it: each delta rebuilds one side around one changed level and
    reuses every other level (speeddesk_kalshi_ws.MarketState), and yields an up and a down book."""

    def __init__(self, slug: str, depth: int = 25, seed: int = 1) -> None:
        self.slug, self.rng, self.n = slug, random.Random(seed), 0
        self.yes = tuple(Level(round(.49 - k / 100, 2), 10.0 + k) for k in range(depth))
        self.no = tuple(Level(round(.49 - k / 100, 2), 12.0 + k) for k in range(depth))
        self.yes_asks = tuple(Level(round(1 - level.price, 8), level.size) for level in self.yes)
        self.no_asks = tuple(Level(round(1 - level.price, 8), level.size) for level in self.no)

    def delta(self, at: float) -> tuple[Book, Book]:
        self.n += 1
        side = "yes" if self.rng.random() < 0.5 else "no"
        bids, asks = getattr(self, side), getattr(self, side + "_asks")
        k = self.rng.randrange(len(bids))
        size = self.rng.choice((0.0, 5.0, 20.0, 33.0))
        level = (Level(bids[k].price, size),) if size else ()
        twin = (Level(round(1 - bids[k].price, 8), size),) if size else ()
        if not size and len(bids) < 3:
            level, twin = (Level(bids[k].price, 1.0),), (Level(round(1 - bids[k].price, 8), 1.0),)
        setattr(self, side, bids[:k] + level + bids[k + 1:])
        setattr(self, side + "_asks", asks[:k] + twin + asks[k + 1:])
        sequence = f"kalshi-ws:1:{self.n}"
        return (Book(self.slug, "up", self.yes, self.no_asks, at, sequence, at),
                Book(self.slug, "down", self.no, self.yes_asks, at, sequence, at))


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def p99(values: list[float]) -> float:
    return quantile(values, 0.99)


def wait_for(check: Any, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return bool(check())


def stand_in(code: str) -> list[str]:
    """A town process that runs ``code`` instead of the town (its socket's number is ``sys.argv[-1]``)."""
    return [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1])\n" + code, ROOT]


def lateness_ms(seconds: float) -> list[float]:
    """The live loop's view: how late a 1 ms sleep wakes, sampled for ``seconds``."""
    out, end = [], time.perf_counter() + seconds
    while time.perf_counter() < end:
        began = time.perf_counter()
        time.sleep(0.001)
        out.append((time.perf_counter() - began - 0.001) * 1000)
    return out


# ---------------------------------------------------------------------- the wire
def test_ladders_travel_as_changes_and_rebuild_exactly() -> None:
    ladders = Ladders(SLUG, depth=40, seed=3)
    sent: dict[tuple[str, str], tuple[Any, Any]] = {}
    received: dict[tuple[str, str], tuple[Any, Any]] = {}
    sizes = []
    for n in range(3000):
        for original in ladders.delta(T0 + n):
            key = (original.window, original.side)
            record = book_wire(original, sent.get(key))
            sent[key] = (original.bids, original.asks)
            sizes.append(len(frame(record)))
            rebuilt = book_from_wire(json.loads(json.dumps(record)) if n % 500 == 7 else record, received)
            assert rebuilt == original
    assert statistics.median(sizes) < 200  # one level a delta, not a 40-level ladder (about 1,400 bytes)
    first = Ladders(SLUG, depth=5).delta(T0)[0]
    assert ladder_change(None, first.bids) == (0, None, tuple((level.price, level.size) for level in first.bids))
    assert ladder_change(first.bids, first.bids) is None
    inserted = first.bids[:2] + (Level(0.995, 1.0),) + first.bids[2:]
    assert apply_ladder(first.bids, ladder_change(first.bids, inserted)) == inserted
    removed = first.bids[:1] + first.bids[2:]
    assert apply_ladder(first.bids, ladder_change(first.bids, removed)) == removed
    rebuilt_rest = tuple(Level(level.price, level.size) for level in first.bids)  # a REST book: new objects
    assert apply_ladder(first.bids, ladder_change(first.bids, rebuilt_rest)) == first.bids
    with pytest.raises(LookupError):
        apply_ladder(None, (1, 2, ()))


# ---------------------------------------------------------------------- the producer side
def test_ticks_and_windows_never_reach_the_arena_and_a_step_flushes_once(tmp_path: Path) -> None:
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
        assert spy.calls == []  # no arena code on a Bitcoin tick or a window list
        runner.on_book(book(clock.now(), 1))
        runner.on_trade(trade(clock.now(), 1))
        runner.step(clock.now())
        assert spy.calls == ["feed_book", "feed_trade", "flush"]
    finally:
        runner.arena = None
        runner.close()


def test_a_put_is_one_bounded_append_that_never_raises(tmp_path: Path) -> None:
    """Books take one slot per window and side (the latest replaces the one waiting: a busy book is never a
    backlog); prints queue behind them, bounded, and past the bound they are dropped, counted and their window
    remembered for the town. Production on 2026-10-13 dropped a third of the feed at 1,024 waiting."""
    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    item = book(T0, 1)
    link.feed_book(item)
    assert link.pending == [] and link.dropped == 0  # a town that is not running is not fed (and not counted)
    link.running = True
    started = time.perf_counter()
    for _ in range(100_000):
        link.feed_book(item)
    per_put_us = (time.perf_counter() - started) / 100_000 * 1e6
    assert per_put_us < 5, per_put_us  # about 0.25 us here
    assert len(link.pending) == 1 and link.puts == 100_000 and link.coalesced == 99_999 and link.dropped == 0
    assert PENDING_MAX >= 16_384
    for n in range(PENDING_MAX + 500):
        link.feed_trade(trade(T0, n))
    assert len(link.pending) == PENDING_MAX and link.dropped == 501 and link.drop_slugs == {SLUG}
    other = Book("KXBTC15M-other", "up", (Level(.30, 2),), (Level(.60, 10),), T0, "o1", T0)
    link.feed_book(other)  # a first book for a market when the queue is full: dropped and named too
    assert link.dropped == 502 and link.drop_slugs == {SLUG, other.window}
    newer = book(T0 + 1, 1)
    link.feed_book(newer)  # a waiting market's book still takes its slot
    assert link.pending[0] is newer and link.dropped == 502
    link.feed_gap(("x",), True, True)  # a gap (a few a minute) always goes
    assert len(link.pending) == PENDING_MAX + 1
    link.pending = None  # type: ignore[assignment]  # even a broken link cannot raise into the live loop
    link.feed_trade(trade(T0, 1))
    link.feed_book(newer)
    link.feed_gap(("x",), True, True)


def test_a_full_queue_costs_a_few_megabytes(tmp_path: Path) -> None:
    """The memory behind PENDING_MAX: a queue full of prints plus a 25-level book for every market the live desk
    follows (books share their Level objects with the market socket's own ladders)."""
    import tracemalloc

    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    link.running = True
    ladders = [Ladders(f"KXBTC15M-m{k}", depth=25, seed=k) for k in range(8)]
    tracemalloc.start()
    try:
        for n in range(PENDING_MAX):
            link.feed_trade(Trade(ladders[n % 8].slug, "up", 0.45, 2.0, T0 + n / 1000, f"t{n}", "sell", T0 + n / 1000))
        for lad in ladders:
            for item in lad.delta(T0):
                link.feed_book(item)
        current, _peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    print(f"a full queue ({len(link.pending)} events): {current / 1e6:.1f} MB")
    assert len(link.pending) == PENDING_MAX and link.dropped == 16
    assert current < 16 << 20, current  # about 6 MB here


def test_the_live_loop_pays_almost_nothing_per_book_and_print(tmp_path: Path) -> None:
    clock = FakeClock(T0)
    runner = runner_at(tmp_path, clock)
    try:
        prepare(runner, clock)
        link = runner.arena
        assert isinstance(link, ArenaLink)
        link.running = True  # the hot path only (no process): flushing is measured below
        on: list[float] = []
        off: list[float] = []
        n = 0
        for block in range(20):  # interleaved, so drift hits both alike
            runner.arena = link if block % 2 else None
            sink = on if block % 2 else off
            link.pending.clear()
            for _ in range(500):
                n += 1
                clock.advance(0.001)
                now = clock.now()
                started = time.perf_counter_ns()
                runner.on_book(book(now, n))
                runner.on_trade(trade(now, n))
                sink.append((time.perf_counter_ns() - started) / 1e6)
        extra_mean, extra_p99 = statistics.fmean(on) - statistics.fmean(off), p99(on) - p99(off)
        assert extra_mean < 0.02 and extra_p99 < 0.5, (extra_mean, extra_p99)
        assert link.puts == 10_000  # every book and print of its blocks
    finally:
        runner.arena = None
        runner.close()


def test_a_flush_of_a_busy_market_costs_well_under_half_a_millisecond(tmp_path: Path) -> None:
    """The live loop's whole per-step cost with the real town running: 400 books a second of 25-level Kalshi ladders
    (10 deltas a 50 ms step), prints and a moving price, in the live thread's own CPU time (another process on a
    shared machine cannot fake it; the wall-clock lateness test is below)."""
    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    link.start()
    try:
        assert link.running and wait_for(lambda: (tmp_path / "kalshi_arena" / "panel.json").exists())
        now = time.time()
        window = Window("KXBTC15M-busy", now - 30, now + 870, None, taker_coefficient=0.07, maker_coefficient=0.0,
                        venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi")
        ladders = Ladders(window.slug, depth=25)
        cpu: list[float] = []
        for step in range(200):
            now = time.time()
            for _ in range(10):
                for item in ladders.delta(now):
                    link.feed_book(item)
            link.feed_trade(Trade(window.slug, "up", 0.45, 2.0, now, f"t{step}", "sell", now))
            snap = LiveSnapshot(windows=(window,), bitcoin_price=80_000.0 + step, bitcoin_at=now, sigma=0.0003,
                                maker_windows=frozenset({window.slug}))
            started = time.thread_time_ns()
            link.flush(snap)
            cpu.append((time.thread_time_ns() - started) / 1e6)
            time.sleep(0.05)
        ordered = sorted(cpu)
        median, high = ordered[len(ordered) // 2], ordered[int(0.99 * len(ordered))]
        print(f"flush CPU ms: median {median:.3f} p99 {high:.3f} max {ordered[-1]:.3f}; link {link.telemetry()}")
        assert median < 0.25 and high < 0.5, (median, high)
        assert link.dropped == 0 and link.frames >= 200
        # Of each step's 20 books only the latest per window and side travels (2), with the print.
        assert link.puts == 200 * 21 and link.coalesced == 200 * 18
    finally:
        link.close(wait_s=10)
    feed = kalshi_arena.panel_state(tmp_path, time.time())["feed"]
    assert feed["received"] == 200 * 3 and feed["dropped"] == 0 and feed["live_flush_us_p99"] is not None
    assert feed["rss_mb"] > 0 and feed["max_rss_mb"] >= feed["rss_mb"]  # the town's own memory, for the page


def test_a_busy_feed_with_live_loop_stalls_drops_nothing_inside_the_budget(tmp_path: Path) -> None:
    """Production's shape on 2026-10-13, three times over: 2,000 Kalshi events a second (books on three windows, two
    sides, 2 % prints) with the live loop's stalls (a 2.3 s one, an 8 s one: the events of the stall arrive in one
    burst before a single flush) through the real town. Nothing is dropped, the flush's CPU p99 on the live thread
    stays under half a millisecond, and the budget leaves what it cannot encode for the next step instead."""
    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    link.start()
    try:
        assert link.running and wait_for(lambda: (tmp_path / "kalshi_arena" / "panel.json").exists())
        now = time.time()
        windows = tuple(Window(f"KXBTC15M-s{k}", now - 30 + 900 * k, now + 870 + 900 * k, None, taker_coefficient=0.07,
                               maker_coefficient=0.0, venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi")
                        for k in range(3))
        ladders = [Ladders(window.slug, depth=25, seed=k) for k, window in enumerate(windows)]
        prints = 0

        def feed(count: int, at: float) -> None:
            nonlocal prints
            for i in range(count):
                lad = ladders[i % 3]
                if i % 50 == 49:
                    prints += 1
                    link.feed_trade(Trade(lad.slug, "up", 0.45, 2.0, at, f"t{prints}", "sell", at))
                else:
                    for item in lad.delta(at):
                        link.feed_book(item)

        cpu: list[float] = []
        stalls = {40: 2.3, 80: 8.0}
        for step in range(120):
            stall = stalls.get(step, 0.0)  # a stall's events carry the times they arrived, before the loop froze
            feed(int(2000 * (stall or 0.05)), time.time() - stall)
            snap = LiveSnapshot(windows=windows, bitcoin_price=80_000.0 + step % 50, bitcoin_at=time.time(),
                                sigma=0.0003, maker_windows=frozenset(window.slug for window in windows))
            started = time.thread_time_ns()
            link.flush(snap)
            cpu.append((time.thread_time_ns() - started) / 1e6)
            time.sleep(0.05)
        for _ in range(20):  # whatever a budget left behind drains over the next steps
            link.flush(snap)
            time.sleep(0.05)
        ordered = sorted(cpu)
        telemetry = link.telemetry()
        print(f"2,000 events/s with stalls: flush CPU ms p50 {ordered[len(ordered) // 2]:.3f} "
              f"p99 {ordered[int(0.99 * len(ordered))]:.3f} max {ordered[-1]:.3f}; link {telemetry}")
        assert telemetry["dropped"] == 0 and telemetry["pending"] == 0 and telemetry["put"] > 60_000
        assert ordered[int(0.99 * len(ordered))] < 0.5, ordered[int(0.99 * len(ordered))]
        assert telemetry["pending_peak"] <= 16_000 * 2 // 50 + 6 + 10  # a stall's prints plus one book a market
    finally:
        link.close(wait_s=10)
    feed_status = kalshi_arena.panel_state(tmp_path, time.time())["feed"]
    assert feed_status["dropped"] == 0 and feed_status["received"] == telemetry["put"] - telemetry["coalesced"]
    assert feed_status["received"] >= prints  # every print reached the town, plus the latest books
    assert feed_status["late"] == 0  # the town read every frame within its own budget
    assert feed_status["held"] > 0 and feed_status["open_incomplete"] == 0  # the stalls were the live loop's


def test_a_backlog_is_encoded_in_slices_within_the_budget(tmp_path: Path) -> None:
    """A queue of 12,000 prints (an 8 s stall of a busy market): one flush encodes only what fits the CPU budget
    (and never more than FLUSH_MAX); the rest goes at the next steps, in order, and nothing is dropped."""
    import marshal

    class Socket:
        def __init__(self) -> None:
            self.frames: list[bytes] = []

        def send(self, data: bytes) -> int:
            self.frames.append(data[4:])  # decoded after the timing, outside the flush
            return len(data)

        def close(self) -> None:
            pass

    class Proc:
        pid = 1

        def poll(self) -> None:
            return None

    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    sock = Socket()
    link.sock, link.proc, link.running = sock, Proc(), True  # type: ignore[assignment]
    snap = LiveSnapshot(windows=(kalshi_window(T0),), bitcoin_price=80_000.0, bitcoin_at=T0, sigma=0.0003)
    for n in range(12_000):
        link.feed_trade(trade(T0 + n / 1000, n))
    flushes = 0
    cpu: list[float] = []
    while link.pending and flushes < 100:
        started = time.thread_time_ns()
        link.flush(snap)
        cpu.append((time.thread_time_ns() - started) / 1e6)
        flushes += 1
    messages = [marshal.loads(data) for data in sock.frames]
    print(f"backlog of 12,000 prints: {flushes} flushes, CPU ms max {max(cpu):.3f} p50 {quantile(cpu, 0.5):.3f}")
    assert link.sliced >= 1 and link.dropped == 0 and flushes >= 3
    sent = [record for message in messages for record in message[5] if record[0] == "t"]
    assert [record[6] for record in sent] == [f"t{n}" for n in range(12_000)]  # every print, in order
    assert all(len(message[5]) <= kalshi_arena.FLUSH_MAX + 4 for message in messages)
    assert max(cpu) < 1.0, max(cpu)  # the budget, the frame's marshal and send, and a margin for a shared machine


# ---------------------------------------------------------------------- isolation
def test_a_town_that_never_reads_never_blocks_the_live_loop(tmp_path: Path) -> None:
    link = ArenaLink(ArenaConfig(data_dir=tmp_path), command=stand_in("import time; time.sleep(60)"))
    link.start()
    try:
        assert link.running
        ladders = Ladders(SLUG, depth=60)
        window = kalshi_window(T0)
        cpu, wall = [], []
        for step in range(400):
            now = time.time()
            for _ in range(40):
                for item in ladders.delta(now):
                    link.feed_book(item)
            for n in range(60):  # prints are not coalesced: they fill the socket, then the queue
                link.feed_trade(trade(now, step * 60 + n))
            snap = LiveSnapshot(windows=(window,), bitcoin_price=80_000.0 + step, bitcoin_at=now, sigma=0.0003)
            began, began_cpu = time.perf_counter_ns(), time.thread_time_ns()
            link.flush(snap)
            cpu.append((time.thread_time_ns() - began_cpu) / 1e6)
            wall.append((time.perf_counter_ns() - began) / 1e6)
        # The socket filled: the frame waits for the next step, the books keep replacing each other in their two
        # slots and the prints queue, bounded; past the bound they are dropped and counted.
        assert link.running and link.blocked > 0 and link.out and 0 < len(link.pending) <= PENDING_MAX
        assert max(cpu) < 5 and p99(cpu) < 1.5, (max(cpu), p99(cpu))  # never waits, however full
        assert statistics.median(wall) < 1, statistics.median(wall)
    finally:
        started = time.monotonic()
        link.close()
        assert time.monotonic() - started < 0.2  # close() never waits unless asked


@pytest.mark.skipif(not hasattr(os, "SCHED_IDLE"), reason="the idle scheduling class is Linux only")
def test_a_town_spinning_on_every_core_never_delays_the_live_loop(tmp_path: Path) -> None:
    """The reviewers' hung and CPU-bound passes: hardened like the real town (idle class, lowest priority), a
    stand-in spins without end on every core. The live loop's 1 ms sleeps wake as on time as with no town at all
    (blocks interleaved, so drift on a shared machine hits both alike)."""
    spinners: list[ArenaLink] = []
    samples: dict[bool, list[float]] = {True: [], False: []}
    try:
        for index in range(os.cpu_count() or 2):
            link = ArenaLink(ArenaConfig(data_dir=tmp_path / str(index)), command=stand_in(
                "from nightcrawler.kalshi_arena import _harden\n_harden()\nwhile True:\n    pass"))
            link.start()
            assert link.running
            spinners.append(link)
        time.sleep(0.3)
        for block in range(12):
            on = block % 2 == 1
            for link in spinners:
                assert link.proc is not None
                os.kill(link.proc.pid, signal.SIGCONT if on else signal.SIGSTOP)  # spin, then park
            time.sleep(0.05)
            samples[on].extend(lateness_ms(0.4))
    finally:
        for link in spinners:
            if link.proc is not None:
                link.proc.kill()
            link.close(wait_s=2)
    off, loaded = samples[False], samples[True]
    rise_median = statistics.median(loaded) - statistics.median(off)
    rise_p90 = quantile(loaded, 0.9) - quantile(off, 0.9)
    print(f"lateness ms with {len(spinners)} spinning towns: median {statistics.median(off):.3f} -> "
          f"{statistics.median(loaded):.3f}, p90 {quantile(off, 0.9):.3f} -> {quantile(loaded, 0.9):.3f}, "
          f"p99 {p99(off):.3f} -> {p99(loaded):.3f}")
    # A town thread spinning the same way raised the median from 0.12 to 5.3 ms (the review of 2026-10-13); the
    # tail of a shared machine (p99 about 3 ms here at load 10) is noise either way, so the robust quantiles decide.
    assert rise_median < 0.1 and rise_p90 < 0.25, (rise_median, rise_p90)


def test_a_dead_town_is_noticed_and_never_reaches_the_live_desk(tmp_path: Path, caplog: Any) -> None:
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    link = ArenaLink(ArenaConfig(data_dir=tmp_path), command=stand_in("import sys; sys.exit(7)"))
    link.start()
    assert link.proc is not None
    link.proc.wait(10)
    snap = LiveSnapshot(windows=(kalshi_window(T0),), bitcoin_price=80_000.0, bitcoin_at=T0, sigma=0.0003)
    for n in range(50):  # whether the socket refuses first or the exit check sees it, never an error
        link.feed_book(book(T0, n))
        link.flush(snap)
        link.checked_at = -1e18
    assert not link.running and link.returncode in (7, None)
    assert "kalshi_arena_exited returncode=" in caplog.text
    link.feed_book(book(T0, 1))
    link.flush(snap)
    assert link.pending == []
    broken = ArenaLink(ArenaConfig(data_dir=tmp_path / "x"), command=["/nonexistent/python"])
    broken.start()  # a process that cannot start: logged, the town stays off
    assert not broken.running and "kalshi_arena_not_started error=FileNotFoundError" in caplog.text
    broken.feed_book(book(T0, 1))
    broken.flush(snap)
    broken.close(wait_s=1)


def test_a_town_behind_holds_the_frame_and_the_events_wait(tmp_path: Path) -> None:
    """When the socket takes nothing (the town is behind), the frame waits for the next step and so do the events:
    books in their slots (the latest replaces the waiting one), prints behind them. Nothing is dropped until the
    queue's bound, and then the drop is counted and named by its window in the next frame."""
    import marshal

    class Socket:
        """Takes what each test step allows: everything, nothing (a full buffer) or a few bytes."""

        def __init__(self) -> None:
            self.takes: list[int | None] = []
            self.wire = bytearray()

        def send(self, data: bytes) -> int:
            take = self.takes.pop(0) if self.takes else len(data)
            if take is None:
                raise BlockingIOError
            self.wire += data[:take]
            return take

        def close(self) -> None:
            pass

    class Proc:
        pid = 1

        def poll(self) -> None:
            return None

    def frames(sock: Socket) -> list[Any]:
        out = []
        while len(sock.wire) >= 4:
            size = int.from_bytes(sock.wire[:4], "little")
            out.append(marshal.loads(bytes(sock.wire[4:4 + size])))
            del sock.wire[:4 + size]
        return out

    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    sock = Socket()
    link.sock, link.proc, link.running = sock, Proc(), True  # type: ignore[assignment]
    ladders = Ladders(SLUG)
    snap = LiveSnapshot(windows=(kalshi_window(T0),), bitcoin_price=80_000.0, bitcoin_at=T0, sigma=0.0003)
    town: dict[tuple[str, str], tuple[Any, Any]] = {}

    def send(*books: Book) -> None:
        for item in books:
            link.feed_book(item)
        link.flush(snap)

    def rebuild() -> list[Book]:
        return [book_from_wire(record, town) for message in frames(sock) for record in message[5] if record[0] == "b"]

    send(*ladders.delta(T0))
    (first,) = frames(sock)
    assert [record[0] for record in first[5]] == ["w", "k", "o", "m", "b", "b"]
    for record in first[5][4:]:
        book_from_wire(record, town)
    # The town is behind: the socket takes nothing. The frame is kept whole; nothing is dropped.
    sock.takes = [None]
    send(*ladders.delta(T0 + 1))
    assert link.dropped == 0 and link.out and link.frames == 2 and link.pending == [] and link.seq == 2
    # Still behind at the next step: this step's books wait in their slots, nothing new is encoded.
    sock.takes = [None]
    send(*ladders.delta(T0 + 2))
    assert link.blocked == 1 and link.dropped == 0 and len(link.pending) == 2 and link.frames == 2
    latest = ladders.delta(T0 + 3)
    send(*latest)  # replaces the waiting books; the socket is open again: the held frame first, then these
    assert link.coalesced == 2 and link.out == b"" and link.frames == 3
    second, third = frames(sock)
    assert (second[1], third[1]) == (2, 3) and [record[0] for record in third[5]] == ["b", "b"]
    sock.wire = bytearray()
    for message in (second, third):
        for record in message[5]:
            if record[0] == "b":
                town_book = book_from_wire(record, town)
    assert town_book == latest[1]  # the ladders rebuild exactly through the hold
    # A frame taken in part: the rest goes first next time, before any new frame.
    sock.takes = [100]
    send(*ladders.delta(T0 + 4))
    assert len(link.out) > 0 and link.frames == 4
    newest = ladders.delta(T0 + 5)
    send(*newest)
    assert link.out == b"" and link.frames == 5
    assert rebuild()[-2:] == list(newest)
    # The last resort: a queue full of prints while the town is behind drops the rest, counted and named.
    sock.takes = [None]
    for n in range(PENDING_MAX + 10):
        link.feed_trade(trade(T0 + 6, n))
    assert link.dropped == 10 and link.drop_slugs == {SLUG}
    link.flush(snap)  # a frame with the first slice is built and held whole; the rest waits in the queue
    assert link.out and link.dropped == 10 and link.sliced == 1 and 0 < len(link.pending) < PENDING_MAX
    sock.takes = [None]
    link.flush(snap)
    assert link.blocked == 2 and link.sliced == 1  # still behind: nothing more is encoded
    sock.takes = []
    flushes = 0
    while link.pending and flushes < 50:
        link.flush(snap)
        flushes += 1
    sent = frames(sock)
    assert sent[0][5][0] == ("d", (SLUG,)) and sent[0][3] == 10  # the windows that lost events, and the count
    assert sum(record[0] == "t" for message in sent for record in message[5]) == PENDING_MAX
    assert link.sliced >= 2 and link.drop_slugs == set() and link.out == b""


def test_the_feed_status_line_carries_the_live_process_memory(tmp_path: Path, caplog: Any) -> None:
    """``kalshi_arena_feed`` (every 5 minutes) says what the live process costs in memory, besides what the link
    put, coalesced, dropped and how a flush went."""
    import marshal

    class Socket:
        def send(self, data: bytes) -> int:
            marshal.loads(data[4:])
            return len(data)

        def close(self) -> None:
            pass

    class Proc:
        pid = 1

        def poll(self) -> None:
            return None

    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    link.sock, link.proc, link.running = Socket(), Proc(), True  # type: ignore[assignment]
    link.status_at = -1e18
    link.feed_book(book(T0, 1))
    link.flush(LiveSnapshot(windows=(kalshi_window(T0),), bitcoin_price=80_000.0, bitcoin_at=T0, sigma=0.0003))
    line = next(record.getMessage() for record in caplog.records if "kalshi_arena_feed" in record.getMessage())
    telemetry = link.telemetry()
    assert telemetry["rss_mb"] > 0 and telemetry["max_rss_mb"] >= telemetry["rss_mb"]
    for key in ("put=1", "coalesced=0", "dropped=0", "pending=1", "pending_peak=1", "sliced=0", "blocked=0",
                f"rss_mb={telemetry['rss_mb']}", f"max_rss_mb={telemetry['max_rss_mb']}"):
        assert key in line, (key, line)



def test_only_windows_the_town_can_use_travel_and_only_when_they_change(tmp_path: Path) -> None:
    """The speed desk keeps every window it ever saw (about 100 a day) and rebuilds its tuple on every discovery;
    the link sends only windows the town can still trade or settle, and only when they changed."""
    import marshal

    class Socket:
        def __init__(self) -> None:
            self.frames: list[Any] = []

        def send(self, data: bytes) -> int:
            self.frames.append(marshal.loads(data[4:]))
            return len(data)

        def close(self) -> None:
            pass

    class Proc:
        pid = 1

        def poll(self) -> None:
            return None

    now = T0 + 30 * 86_400
    link = ArenaLink(ArenaConfig(data_dir=tmp_path), clock=lambda: now)
    sock = Socket()
    link.sock, link.proc, link.running = sock, Proc(), True  # type: ignore[assignment]
    old = [kalshi_window(now - 3 * 3600 - 900 * k) for k in range(3000)]  # a month of finished windows
    current, upcoming = kalshi_window(now - 100), kalshi_window(now + 800)
    outcomes = {window.slug: True for window in old}

    def facts(windows: list[Window], outcome: dict[str, bool]) -> dict[str, Any]:
        sock.frames.clear()
        snap = LiveSnapshot(windows=tuple(replace(window) for window in windows), bitcoin_price=80_000.0,
                            bitcoin_at=now, sigma=0.0003, outcomes=outcome)
        started = time.thread_time_ns()
        link.flush(snap)
        cpu = (time.thread_time_ns() - started) / 1e6
        records = {record[0]: record for message in sock.frames for record in message[5]}
        return {"cpu": cpu, **records}

    first = facts([*old, current], outcomes)
    assert [values[0] for values in first["w"][1]] == [current.slug] and first["o"][1] == ()
    assert first["cpu"] < 5, first["cpu"]  # a month of windows filtered in a few ms, once per discovery
    again = facts([*old, current], dict(outcomes))  # the desk's fresh copies of the same windows
    assert "w" not in again and "o" not in again  # nothing changed for the town
    later = facts([*old, current, upcoming], {**outcomes, current.slug: False})
    assert [values[0] for values in later["w"][1]] == [current.slug, upcoming.slug]
    assert later["o"][1] == ((current.slug, False),)


def test_the_town_process_holds_no_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "kalshi-private-key-value-xyz"
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", secret)
    monkeypatch.setenv("KALSHI_KEY_ID", "key-id-value-abc")
    clock = FakeClock(T0)
    runner = SpeedRunner(Settings(data_dir=tmp_path, kalshi_key_id="key-id-value-abc", kalshi_private_key=secret),
                         threading.Event(), clock=clock, feed_factory=LocalFeeds, live_factory=SpyLive)
    try:
        link = runner.arena
        assert isinstance(link, ArenaLink)
        assert secret not in json.dumps(link.wire) and "key-id-value-abc" not in json.dumps(link.wire)
        assert set(vars(link)) >= {"wire", "command", "pending"} and not any(
            isinstance(value, Settings) for value in vars(link).values())
        link.start()
        assert link.proc is not None and wait_for(lambda: (tmp_path / "kalshi_arena" / "state.json").exists())
        if Path(f"/proc/{link.proc.pid}/environ").exists():
            environ = Path(f"/proc/{link.proc.pid}/environ").read_bytes().split(b"\0")
            assert sorted(item.split(b"=")[0] for item in environ if item) == [b"LANG", b"PATH", b"TZ"]
            assert secret.encode() not in Path(f"/proc/{link.proc.pid}/cmdline").read_bytes()
        assert link.command == worker_command() and secret not in " ".join(link.command)
    finally:
        runner.close()
    assert link.proc is not None and link.proc.wait(10) == 0  # closing the link gave the town its final save


def test_the_real_town_runs_end_to_end_and_saves_on_close(tmp_path: Path, caplog: Any) -> None:
    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    link.start()
    try:
        assert wait_for(lambda: (tmp_path / "kalshi_arena" / "panel.json").exists())
        now = time.time()
        window = Window("KXBTC15M-e2e", now - 5, now + 895, None, taker_coefficient=0.07, maker_coefficient=0.0,
                        venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi")
        ladders = Ladders(window.slug)
        for step in range(40):
            now = time.time()
            for item in ladders.delta(now):
                link.feed_book(item)
            link.feed_trade(Trade(window.slug, "up", 0.45, 2.0, now, f"t{step}", "sell", now))
            link.feed_gap((), True, True)
            link.flush(LiveSnapshot(windows=(window,), bitcoin_price=80_000.0, bitcoin_at=now, sigma=0.0003,
                                    maker_windows=frozenset({window.slug})))
            time.sleep(0.05)
    finally:
        link.close(wait_s=10)
    assert link.proc is not None and link.proc.wait(10) == 0
    state = json.loads((tmp_path / "kalshi_arena" / "state.json").read_text(encoding="utf-8"))
    assert len(state["residents"]) == 12 and state["feed"]["received"] == 120 and state["feed"]["dropped"] == 0
    assert state["town"]["void_windows"] == 1  # the window was open when the town started: void for everyone
    panel = kalshi_arena.panel_state(tmp_path, time.time())
    assert panel["feed"]["late"] == 0 and panel["feed"]["errors"] == 0


def test_the_speed_desk_run_starts_the_town_and_shuts_it_down_last(tmp_path: Path) -> None:
    runner = runner_at(tmp_path, FakeClock(T0))
    link = runner.arena
    assert isinstance(link, ArenaLink)
    order: list[str] = []
    real_close = link.close
    link.close = lambda wait_s=0.0: order.append("arena") or real_close(wait_s)  # type: ignore[method-assign]
    real_checkpoint = runner.checkpoint
    runner.checkpoint = lambda now: order.append("checkpoint") or real_checkpoint(now)  # type: ignore[method-assign]
    timer = threading.Timer(1.0, runner.stop.set)
    timer.start()
    try:
        asyncio.run(runner.run())
        assert link.proc is not None and order[-2:] == ["checkpoint", "arena"]  # after the last real-money step
    finally:
        timer.cancel()
        runner.close()
    assert isinstance(runner.live, SpyLive) and runner.live.closed
    assert link.proc.wait(10) == 0 and (tmp_path / "kalshi_arena" / "state.json").exists()


def test_a_failing_arena_close_never_skips_the_live_shutdown(tmp_path: Path, caplog: Any) -> None:
    runner = runner_at(tmp_path, FakeClock(T0))

    class Broken:
        def close(self, _wait_s: float = 0.0) -> None:
            raise RuntimeError("synthetic")

    runner.arena = Broken()
    runner.close()
    assert isinstance(runner.live, SpyLive) and runner.live.closed
    assert "kalshi_arena_close_failed error=RuntimeError" in caplog.text


def test_an_arena_that_cannot_be_built_leaves_the_desk_trading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                               caplog: Any) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(kalshi_arena, "ArenaLink", broken)
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


# ---------------------------------------------------------------------- the town's own process
def test_the_town_serves_frames_and_halts_itself_after_repeated_errors(tmp_path: Path, caplog: Any) -> None:
    import socket

    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    ours, theirs = socket.socketpair()
    clock = {"now": time.time()}
    ours.sendall(frame(("config", kalshi_arena.config_wire(ArenaConfig(data_dir=tmp_path)))))
    ours.sendall(frame(("batch", 1, clock["now"], 0, 50, [("m", 80_000.0, clock["now"], 0.0003)])))
    bad = [frame(("batch", 2 + n, clock["now"], 0, 50, [("?",)])) for n in range(kalshi_arena.HALT_AFTER)]

    def sleep(_seconds: float) -> None:  # one frame the town cannot read before each pass
        clock["now"] += 0.1
        if bad:
            ours.sendall(bad.pop(0))

    code = kalshi_arena.serve(theirs.fileno(), clock=lambda: clock["now"], sleep=sleep, alarm=lambda _s: None)
    assert code == kalshi_arena.EXIT_HALTED
    panel = kalshi_arena.panel_state(tmp_path, clock["now"])
    assert panel["problem"] and "live desk is unaffected" in panel["problem"]
    assert "kalshi_arena_halted error=ValueError" in caplog.text
    ours.close()
    theirs.close()
    # A town whose link closes saves and exits cleanly.
    ours, theirs = socket.socketpair()
    ours.sendall(frame(("config", kalshi_arena.config_wire(ArenaConfig(data_dir=tmp_path / "clean")))))
    ours.close()
    assert kalshi_arena.serve(theirs.fileno(), sleep=lambda _s: None, alarm=lambda _s: None) == 0
    assert (tmp_path / "clean" / "kalshi_arena" / "state.json").exists()
    theirs.close()
    ours, theirs = socket.socketpair()
    ours.close()
    assert kalshi_arena.serve(theirs.fileno(), sleep=lambda _s: None, alarm=lambda _s: None) == 2  # no configuration
    theirs.close()


def test_the_town_hardens_itself(tmp_path: Path) -> None:
    """The town's own steps, and what it reports back: the idle class at nice 19, first for the OOM killer, a memory
    limit, and no core dump (its working directory is DATA_DIR, the live desk's volume) even when the soft limit it
    inherits allows one."""
    code = ("import resource\nhard = resource.getrlimit(resource.RLIMIT_CORE)[1]\n"
            "resource.setrlimit(resource.RLIMIT_CORE, (hard, hard))\n"
            "from nightcrawler.kalshi_arena import _harden, report_hardening\n_harden()\nimport json, os\n"
            "print(os.getpriority(os.PRIO_PROCESS, 0), os.sched_getscheduler(0) == getattr(os, 'SCHED_IDLE', -1), "
            "resource.getrlimit(resource.RLIMIT_AS)[0], open('/proc/self/oom_score_adj').read().strip(), "
            "*resource.getrlimit(resource.RLIMIT_CORE))\nprint(json.dumps(report_hardening()))")
    import subprocess

    result = subprocess.run(stand_in(code), capture_output=True, text=True, timeout=30, check=True, env={})
    first, second = result.stdout.splitlines()
    nice, idle, memory, oom, core_soft, core_hard = first.split()
    assert int(nice) == 19 and memory == str(kalshi_arena.MEMORY_BYTES) and oom == "1000"
    assert idle == "True" or not hasattr(os, "SCHED_IDLE")
    assert (core_soft, core_hard) == ("0", "0")
    assert json.loads(second) == {"nice": 19, "sched": "idle", "as_limit_bytes": kalshi_arena.MEMORY_BYTES,
                                  "oom_score_adj": 1000, "applied": True}
    assert "kalshi_arena_hardened" not in result.stderr  # applied: an INFO line (no WARNING), here unconfigured


def test_the_town_reports_the_isolation_it_actually_got(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        caplog: Any) -> None:
    """A runtime that refuses _harden's steps (a seccomp or gVisor profile, a read-only /proc) is no longer silent:
    what took effect is read back, logged once (a WARNING when the town competes for the CPU at normal priority)
    and carried in the panel's feed for the page."""
    import socket

    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    monkeypatch.setattr(kalshi_arena.os, "getpriority", lambda *_args: 0)
    monkeypatch.setattr(kalshi_arena.os, "sched_getscheduler", lambda _pid: 0)  # SCHED_OTHER
    report = kalshi_arena.report_hardening()
    monkeypatch.undo()
    assert (report["nice"], report["sched"], report["applied"]) == (0, "other", False)
    warned = [record.getMessage() for record in caplog.records
              if record.levelno == logging.WARNING and "kalshi_arena_hardened" in record.getMessage()]
    assert len(warned) == 1 and "nice=0 sched=other" in warned[0] and "applied=False" in warned[0]
    ours, theirs = socket.socketpair()
    ours.sendall(frame(("config", kalshi_arena.config_wire(ArenaConfig(data_dir=tmp_path)))))
    ours.close()
    assert kalshi_arena.serve(theirs.fileno(), sleep=lambda _s: None, alarm=lambda _s: None, hardening=report) == 0
    theirs.close()
    assert kalshi_arena.panel_state(tmp_path, time.time())["feed"]["hardening"] == report


def test_frames_that_arrive_with_the_configuration_are_read_not_dropped(tmp_path: Path) -> None:
    """The link's first flush lands 50 ms after start, while the town is still importing, so it reaches the town in
    the same read as the configuration. It carries the window list and whole ladders: it is read before the first
    pass (a dropped one left the town without its windows, and every later ladder change unreadable)."""
    import socket

    from nightcrawler.kalshi_arena import window_wire

    now = time.time()
    window = Window("KXBTC15M-early", now + 60, now + 960, None, taker_coefficient=0.07, maker_coefficient=0.0,
                    venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi")
    ladders = Ladders(window.slug)
    first, second = ladders.delta(now), ladders.delta(now + 0.05)
    sent: dict[tuple[str, str], Any] = {}
    records = []
    for item in (*first, *second):
        records.append(book_wire(item, sent.get((item.window, item.side))))
        sent[(item.window, item.side)] = (item.bids, item.asks)
    ours, theirs = socket.socketpair()
    ours.sendall(frame(("config", kalshi_arena.config_wire(ArenaConfig(data_dir=tmp_path)))))
    ours.sendall(frame(("batch", 1, now, 0, 40, [("w", (window_wire(window),)), *records[:2]])))
    ours.sendall(frame(("batch", 2, now, 0, 40, records[2:])))  # changes to the ladders frame 1 sent whole
    ours.close()
    # frame 2 holds changes to the ladders frame 1 sent whole (readable only with frame 1)
    assert any(change is not None and change[1] is not None for record in records[2:] for change in record[3:5])
    assert kalshi_arena.serve(theirs.fileno(), sleep=lambda _s: None, alarm=lambda _s: None) == 0
    theirs.close()
    state = json.loads((tmp_path / "kalshi_arena" / "state.json").read_text(encoding="utf-8"))
    assert state["active_windows"] == [[window.slug, window.start]]  # the town knows the window from frame 1
    assert state["feed"]["received"] == 4 and state["feed"]["errors"] == 0
    panel = kalshi_arena.panel_state(tmp_path, time.time())
    assert panel["feed"]["open_incomplete"] == 0 and panel["feed"]["last_frame_at"] is not None


@pytest.mark.skipif(not hasattr(signal, "SIGVTALRM"), reason="the CPU-time timer is POSIX only")
def test_a_spinning_pass_dies_on_its_cpu_budget(tmp_path: Path) -> None:
    """A pass that spins is ended by its CPU budget (SIGVTALRM after PASS_CPU_S of the process's CPU), not after two
    minutes of a core by the wall-clock alarm; the budget is re-armed every pass and cleared with the alarm."""
    import subprocess

    code = ("from nightcrawler import kalshi_arena as k\nk.PASS_CPU_S = 0.3\n"
            "def spin(self, now):\n    while True:\n        pass\n"
            "k.KalshiArena.step = spin\nraise SystemExit(k.serve(int(sys.argv[-1])))")
    link = ArenaLink(ArenaConfig(data_dir=tmp_path), command=stand_in(code))
    began = time.monotonic()
    link.start()
    try:
        assert link.proc is not None
        returncode = link.proc.wait(timeout=60)
    finally:
        if link.proc is not None and link.proc.poll() is None:
            link.proc.kill()
        link.close()
    assert returncode == -signal.SIGVTALRM and time.monotonic() - began < 30
    clear = ("from nightcrawler import kalshi_arena as k\nimport time\nk.PASS_CPU_S = 0.2\nk._alarm(120)\n"
             "k._alarm(0)\nend = time.process_time() + 0.5\nwhile time.process_time() < end:\n    pass\n"
             "print('alive')")
    result = subprocess.run(stand_in(clear), capture_output=True, text=True, timeout=30, env={}, check=False)
    assert result.returncode == 0 and result.stdout.strip() == "alive"


@pytest.mark.skipif(os.environ.get("NIGHTCRAWLER_PERF_TESTS") != "1",
                    reason="wall-clock timing; set NIGHTCRAWLER_PERF_TESTS=1 to run")
def test_the_town_barely_delays_a_one_millisecond_loop_at_a_busy_rate(tmp_path: Path) -> None:
    """The live loop's view under a busy market: a thread that sleeps 1 ms at a time builds 400 books a second of
    25-level ladders in every block; in alternate blocks it also feeds them to the real town and flushes every
    50 ms, so the only difference between the blocks is the arena."""
    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    link.start()
    assert wait_for(lambda: (tmp_path / "kalshi_arena" / "panel.json").exists())
    now = time.time()
    window = Window("KXBTC15M-perf", now - 30, now + 870, None, taker_coefficient=0.07, maker_coefficient=0.0,
                    venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi")
    ladders = Ladders(window.slug)
    samples: dict[bool, list[float]] = {True: [], False: []}
    try:
        for block in range(40):
            on = block % 2 == 1
            began = last_book = last_flush = time.perf_counter()
            while time.perf_counter() - began < 0.5:
                t0 = time.perf_counter()
                time.sleep(0.001)
                samples[on].append((time.perf_counter() - t0 - 0.001) * 1000)
                if time.perf_counter() - last_book >= 0.005:  # a delta (two books) every 5 ms
                    last_book = time.perf_counter()
                    now = time.time()
                    books = ladders.delta(now)
                    if on:
                        for item in books:
                            link.feed_book(item)
                if on and time.perf_counter() - last_flush >= 0.05:
                    last_flush = time.perf_counter()
                    link.flush(LiveSnapshot(windows=(window,), bitcoin_price=80_000.0, bitcoin_at=time.time(),
                                            sigma=0.0003, maker_windows=frozenset({window.slug})))
    finally:
        link.close(wait_s=10)
    off, loaded = samples[False], samples[True]
    print(f"lateness ms: off p50 {statistics.median(off):.3f} p90 {quantile(off, 0.9):.3f} p99 {p99(off):.3f}; "
          f"on p50 {statistics.median(loaded):.3f} p90 {quantile(loaded, 0.9):.3f} p99 {p99(loaded):.3f}; "
          f"link {link.telemetry()}")
    assert statistics.median(loaded) - statistics.median(off) < 0.05
    assert quantile(loaded, 0.9) - quantile(off, 0.9) < 0.25
    assert p99(loaded) - p99(off) < 0.5 or p99(off) > 1.0  # a shared machine's own tail beyond 1 ms is noise


# ---------------------------------------------------------------------- preflight: the real town's process, end to end
# Python 3.12's pathlib imports urllib.parse (string handling only); a client needs one of these.
NO_ORDER_PATH = ("nightcrawler.speeddesk_live", "nightcrawler.speeddesk_kalshi", "nightcrawler.polymarket_us",
                 "nightcrawler.broker", "nightcrawler.polydesk", "requests", "websockets", "aiohttp", "httpx", "ssl",
                 "_ssl", "http.client", "urllib.request", "asyncio")


def held_files(fds: Path, town_dir: Path) -> dict[str, str]:
    """The files a running town holds, read while it may be saving: a descriptor that closes mid-read is skipped,
    and a save's temporary file under DATA_DIR/kalshi_arena (open for a moment, then renamed) is not one it keeps."""
    held: dict[str, str] = {}
    for item in fds.iterdir():
        try:
            target = os.readlink(item)
        except FileNotFoundError:
            continue
        if not (target.startswith(str(town_dir)) and target.endswith(".tmp")):
            held[item.name] = target
    return held


@pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="reads /proc")
def test_held_files_skip_a_save_in_flight(tmp_path: Path) -> None:
    town_dir = tmp_path / "kalshi_arena"
    town_dir.mkdir()
    with (town_dir / "panel.json.tmp").open("w") as saving, (town_dir / "town.lock").open("a") as lock:
        held = held_files(Path("/proc/self/fd"), town_dir)
        assert str(town_dir / "town.lock") in held.values() and not any(path.endswith(".tmp") for path in held.values())
        assert saving.fileno() >= 0 and lock.fileno() >= 0


def test_the_real_town_imports_no_order_path_and_inherits_no_live_file(tmp_path: Path, capfd: Any) -> None:
    """The exact worker command (plus -X importtime, which only reports) started by a SpeedRunner holding the REAL
    Kalshi companion's controller lock and ledgers: the town's process holds none of them (a town outliving its bot
    would otherwise lock a restarted live desk out), and over a whole session it imports no module of an order path,
    no speeddesk_live module at all, and nothing that speaks HTTP or TLS."""
    clock = FakeClock(time.time())
    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock, feed_factory=LocalFeeds)
    link = runner.arena
    try:
        assert runner.live is not None and isinstance(link, ArenaLink)
        live_files = {os.readlink(f"/proc/self/fd/{fd}") for fd in os.listdir("/proc/self/fd")
                      if os.path.exists(f"/proc/self/fd/{fd}")} if Path("/proc/self/fd").exists() else set()
        command = worker_command()
        link.command = [command[0], "-X", "importtime", *command[1:]]
        link.start()
        assert link.proc is not None and wait_for(lambda: (tmp_path / "kalshi_arena" / "state.json").exists())
        fds = Path(f"/proc/{link.proc.pid}/fd")
        if fds.exists():
            held = held_files(fds, tmp_path / "kalshi_arena")
            own = str(tmp_path / "kalshi_arena" / "town.lock")
            assert any(path.endswith("controller.lock") for path in live_files)  # the parent holds the live lock
            assert not [path for path in held.values()
                        if path != own and ("speeddesk" in path or path.endswith((".db", ".lock")))], held
            assert sum(path.startswith("socket:") for path in held.values()) == 1 and len(held) <= 5, held
        now = time.time()
        window = Window("KXBTC15M-mods", now + 1, now + 901, None, taker_coefficient=0.07, maker_coefficient=0.0,
                        venue_start_price=80_000, venue="kalshi", fee_rounding="kalshi")
        for step in range(20):
            now = time.time()
            link.feed_book(Book(window.slug, "up", (Level(.45, 10),), (Level(.55, 10),), now, f"u{step}", now))
            link.feed_trade(Trade(window.slug, "up", 0.45, 2.0, now, f"t{step}", "sell", now))
            link.flush(LiveSnapshot(windows=(window,), bitcoin_price=80_000.0, bitcoin_at=now, sigma=0.0003,
                                    maker_windows=frozenset({window.slug})))
            time.sleep(0.05)
    finally:
        runner.close()
    assert link.proc is not None and link.proc.wait(10) == 0
    modules = {line.rsplit("|", 1)[1].strip() for line in capfd.readouterr().err.splitlines()
               if line.startswith("import time:") and "|" in line}
    assert "nightcrawler.kalshi_arena" in modules and "nightcrawler.speeddesk_model" in modules
    assert not {name for name in modules if name.startswith(NO_ORDER_PATH)}, sorted(modules)


def test_one_town_per_data_dir(tmp_path: Path, caplog: Any) -> None:
    """A second town on the same DATA_DIR (a wedged one outliving its bot outside a container, or a second bot on the
    same volume) exits at once and never writes; after the first exits, a town starts again."""
    import socket

    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    first = ArenaLink(ArenaConfig(data_dir=tmp_path))
    first.start()
    state = tmp_path / "kalshi_arena" / "state.json"
    try:
        assert wait_for(state.exists)
        before = state.stat().st_mtime_ns
        ours, theirs = socket.socketpair()
        ours.sendall(frame(("config", kalshi_arena.config_wire(ArenaConfig(data_dir=tmp_path)))))
        ours.close()  # without the lock, a second town would run one pass, save and return 0
        clock = {"now": time.time()}

        def wait(seconds: float) -> None:
            clock["now"] += seconds

        code = kalshi_arena.serve(theirs.fileno(), clock=lambda: clock["now"], sleep=wait, alarm=lambda _s: None)
        theirs.close()
        assert code == kalshi_arena.EXIT_BUSY and "kalshi_arena_busy" in caplog.text
        assert clock["now"] - time.time() >= kalshi_arena.LOCK_WAIT_S - 1  # it waited for the old town first
        assert state.stat().st_mtime_ns == before  # the second town wrote nothing
    finally:
        first.close(wait_s=10)
    assert first.proc is not None and first.proc.wait(10) == 0
    # An old town that finishes while the new one waits: the new one takes over.
    import fcntl

    held = (tmp_path / "kalshi_arena" / "town.lock").open("a", encoding="utf-8")
    fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    waits: list[float] = []

    def release_after_two(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            held.close()  # the old town's process ends

    ours, theirs = socket.socketpair()
    ours.sendall(frame(("config", kalshi_arena.config_wire(ArenaConfig(data_dir=tmp_path)))))
    ours.close()
    assert kalshi_arena.serve(theirs.fileno(), sleep=release_after_two, alarm=lambda _s: None) == 0
    assert len(waits) >= 2
    theirs.close()


@pytest.mark.skipif(not hasattr(os, "SCHED_IDLE"), reason="the idle scheduling class is Linux only")
def test_the_town_lowers_its_priority_before_it_imports_the_package(tmp_path: Path) -> None:
    """The exact boot of worker_command, pointed at a stand-in package: when ``nightcrawler.kalshi_arena`` is first
    imported (most of a start's CPU), the process already runs in the idle class at nice 19."""
    import subprocess

    package = tmp_path / "nightcrawler"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "kalshi_arena.py").write_text(
        "import os\nSEEN = (os.getpriority(os.PRIO_PROCESS, 0), os.sched_getscheduler(0) == os.SCHED_IDLE)\n"
        "def worker_main():\n    print(*SEEN)\n    return 0\n", encoding="utf-8")
    command = worker_command()
    result = subprocess.run([*command[:-1], str(tmp_path), "99"], capture_output=True, text=True, timeout=30,
                            check=True, env=kalshi_arena.worker_env())
    nice, idle = result.stdout.split()
    assert int(nice) == 19 and idle == "True"

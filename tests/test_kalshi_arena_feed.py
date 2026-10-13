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
    link = ArenaLink(ArenaConfig(data_dir=tmp_path))
    item = book(T0, 1)
    link.feed_book(item)
    assert link.pending == [] and link.dropped == 0  # a town that is not running is not fed (and not counted)
    link.running = True
    started = time.perf_counter()
    for _ in range(100_000):
        link.feed_book(item)
    per_put_us = (time.perf_counter() - started) / 100_000 * 1e6
    assert per_put_us < 5, per_put_us  # about 0.15 us here
    assert len(link.pending) == link.puts == PENDING_MAX and link.dropped == 100_000 - PENDING_MAX
    link.pending = None  # type: ignore[assignment]  # even a broken link cannot raise into the live loop
    link.feed_trade(trade(T0, 1))
    link.feed_gap(("x",), True, True)


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
    finally:
        link.close(wait_s=10)
    feed = kalshi_arena.panel_state(tmp_path, time.time())["feed"]
    assert feed["received"] == 200 * 21 and feed["dropped"] == 0 and feed["live_flush_us_p99"] is not None


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
            snap = LiveSnapshot(windows=(window,), bitcoin_price=80_000.0 + step, bitcoin_at=now, sigma=0.0003)
            began, began_cpu = time.perf_counter_ns(), time.thread_time_ns()
            link.flush(snap)
            cpu.append((time.thread_time_ns() - began_cpu) / 1e6)
            wall.append((time.perf_counter_ns() - began) / 1e6)
        assert link.running and link.dropped > 0  # the socket filled: whole frames dropped and counted
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


def test_a_town_behind_drops_whole_frames_then_sends_whole_ladders(tmp_path: Path) -> None:
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

    send(*ladders.delta(T0))
    (first,) = frames(sock)
    assert [record[0] for record in first[5]] == ["w", "k", "o", "m", "b", "b"]
    for record in first[5][4:]:
        book_from_wire(record, town)
    # The town is behind: the socket takes nothing, so the frame is dropped whole and the ladders reset.
    sock.takes = [None]
    send(*ladders.delta(T0 + 1))
    assert link.dropped == 2 and link.out == b"" and link._ladders == {} and link._windows is None
    # Then it takes a few bytes of the next frame: the rest goes first next time, before any new frame.
    sock.takes = [100]
    send(*ladders.delta(T0 + 2))
    assert len(link.out) > 0 and link.frames == 2
    latest = ladders.delta(T0 + 3)
    send(*latest)
    assert link.out == b"" and link.frames == 3
    second, third = frames(sock)
    assert (second[1], third[1], second[3]) == (2, 3, 2)  # in order, and the drop count travels with them
    assert [record[0] for record in second[5]] == ["w", "k", "o", "m", "b", "b"]  # every fact again after a drop
    assert all(record[3][1] is None and record[4][1] is None for record in second[5][4:])  # whole ladders again
    rebuilt = [book_from_wire(record, town) for message in (second, third) for record in message[5]
               if record[0] == "b"]
    assert rebuilt[-2:] == list(latest) and [record[0] for record in third[5]] == ["b", "b"]
    # Still behind with a frame unfinished: that step's events are dropped before they are even encoded.
    sock.takes = [10, None]
    send(ladders.delta(T0 + 4)[0])
    send(ladders.delta(T0 + 5)[0])
    assert link.dropped == 3 and link.pending == [] and len(link.out) > 0


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
    code = ("from nightcrawler.kalshi_arena import _harden\n_harden()\nimport os, resource\n"
            "print(os.getpriority(os.PRIO_PROCESS, 0), os.sched_getscheduler(0) == getattr(os, 'SCHED_IDLE', -1), "
            "resource.getrlimit(resource.RLIMIT_AS)[0], open('/proc/self/oom_score_adj').read().strip())")
    import subprocess

    result = subprocess.run(stand_in(code), capture_output=True, text=True, timeout=30, check=True, env={})
    nice, idle, memory, oom = result.stdout.split()
    assert int(nice) == 19 and memory == str(kalshi_arena.MEMORY_BYTES) and oom == "1000"
    assert idle == "True" or not hasattr(os, "SCHED_IDLE")


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

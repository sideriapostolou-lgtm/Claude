"""Lossless bounded hand-over under bursts; genuine gaps and stale evidence still invalidate practice windows."""

from __future__ import annotations

import marshal
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from kalshi_arena_world import T0, kalshi_window

from nightcrawler import kalshi_arena as arena
from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, PracticeOrder, Trade


class Socket:
    def __init__(self) -> None:
        self.blocked = False
        self.messages: list[Any] = []

    def send(self, data: bytes) -> int:
        if self.blocked:
            raise BlockingIOError
        self.messages.append(marshal.loads(data[4:]))
        return len(data)

    def close(self) -> None:
        pass


class Process:
    pid = 123

    def poll(self) -> None:
        return None


def link_at(path: Path, clock: FakeClock) -> tuple[arena.ArenaLink, Socket]:
    link = arena.ArenaLink(arena.ArenaConfig(data_dir=path), clock=clock.now)
    sock = Socket()
    link.sock, link.proc, link.running = sock, Process(), True  # type: ignore[assignment]
    return link, sock


def snapshot(clock: FakeClock) -> LiveSnapshot:
    window = kalshi_window(T0)
    return LiveSnapshot(windows=(window,), bitcoin_price=80_000, bitcoin_at=clock.now(), sigma=0.0003,
                        maker_windows=frozenset({window.slug}))


def feed_events(link: arena.ArenaLink, now: float, count: int) -> list[Book | Trade]:
    slug = kalshi_window(T0).slug
    expected: list[Book | Trade] = []
    for n in range(count):
        item: Book | Trade
        if n % 3:
            # A disappearing ask then its return must be transported, not replaced by the latest book.
            asks = (Level(0.50, 5 + n % 10),) if n % 2 else ()
            item = Book(slug, "up", (Level(0.48, 10),), asks, now, str(n), now)
            link.feed_book(item)
        else:
            item = Trade(slug, "up", 0.48, 1, now, str(n), "sell", now)
            link.feed_trade(item)
        expected.append(item)
    return expected


def decode(sock: Socket) -> list[Book | Trade]:
    ladders: dict[Any, Any] = {}
    return [arena.book_from_wire(record, ladders) if record[0] == "b" else arena.trade_from_wire(record)
            for message in sock.messages for record in message[5] if record[0] in {"b", "t"}]


def drain(link: arena.ArenaLink, snap: LiveSnapshot) -> None:
    for _ in range(arena.PENDING_MAX):
        link.flush(snap)
        if not link.pending and not link.out:
            return
    pytest.fail("bounded fake feed did not drain")


def test_large_burst_preserves_every_intermediate_book_and_print(tmp_path: Path) -> None:
    clock = FakeClock(T0 + 1)
    link, sock = link_at(tmp_path, clock)
    expected = feed_events(link, clock.now(), 6000)
    drain(link, snapshot(clock))
    assert decode(sock) == expected
    assert link.dropped == 0 and link.sliced > 0
    assert all(message[3] == 0 for message in sock.messages)
    assert [message[1] for message in sock.messages] == list(range(1, len(sock.messages) + 1))


def test_sustained_three_thousand_events_per_second_does_not_build_a_backlog(tmp_path: Path) -> None:
    """150 events per nominal 50 ms live step, above the measured production rate of 2,335/s.

    This exercises actual budget checks (no fake performance clock); a 150 us encoding budget could not keep up.
    A small transient backlog is permitted on a shared worker, but not growth toward the 16k overflow bound.
    """
    clock = FakeClock(T0 + 1)
    link, sock = link_at(tmp_path, clock)
    snap = snapshot(clock)
    slug = snap.windows[0].slug
    bids = tuple(Level(round(0.49 - n / 100, 2), 10 + n) for n in range(40))
    asks = tuple(Level(round(0.51 + n / 100, 2), 10 + n) for n in range(40))
    for step in range(400):
        for n in range(150):
            index = n % len(bids)
            bids = bids[:index] + (Level(bids[index].price, 10 + (step + n) % 100),) + bids[index + 1:]
            link.feed_book(Book(slug, "up", bids, asks, clock.now(), f"{step}:{n}", clock.now()))
        link.flush(snap)
    assert link.dropped == 0
    assert len(link.pending) < 1500 and link.pending_peak < 3000
    drain(link, snap)
    assert sum(record[0] == "b" for message in sock.messages for record in message[5]) == 60_000


def test_encoding_budget_leaves_unencoded_events_at_the_front(tmp_path: Path) -> None:
    clock = FakeClock(T0 + 1)
    link, sock = link_at(tmp_path, clock)
    expected = feed_events(link, clock.now(), 100)
    ticks = iter(range(0, 1000 * arena.FLUSH_BUDGET_NS, arena.FLUSH_BUDGET_NS))
    link.perf = lambda: next(ticks)
    link.flush(snapshot(clock))
    assert decode(sock) == expected[:arena.FLUSH_CHUNK]
    assert list(link.pending) == expected[arena.FLUSH_CHUNK:]
    assert link.sliced == 1 and link.dropped == 0
    drain(link, snapshot(clock))
    assert decode(sock) == expected


def test_blocked_socket_retains_backlog_and_overflow_still_voids(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arena, "PENDING_MAX", 64)
    clock = FakeClock(T0 + 1)
    link, sock = link_at(tmp_path / "link", clock)
    snap = snapshot(clock)
    town = arena.KalshiArena(arena.ArenaConfig(data_dir=tmp_path / "town"), lambda: snap,
                            clock=lambda: T0)
    town._windows(snap, T0)
    town.clock = clock.now
    view = arena.WireView()
    sock.blocked = True
    first = feed_events(link, clock.now(), 1)
    link.flush(snap)
    assert link.out and link.dropped == 0
    for _ in range(3):
        link.flush(snap)
    assert link.blocked == 3 and link.dropped == 0
    following = feed_events(link, clock.now(), 65)
    assert len(link.pending) == 64 and link.dropped == 1
    sock.blocked = False
    drain(link, snap)
    assert decode(sock) == first + following[:64]
    assert sock.messages[-1][3] == 1
    for message in sock.messages:
        town.receive(message, view)
    assert town.degraded == {snap.windows[0].slug: "feed_dropped"}
    assert town.town["windows"] == 0  # overflow never becomes successful coverage


def test_buffering_never_changes_an_events_age_or_hides_lateness(tmp_path: Path) -> None:
    clock = FakeClock(T0 + 1)
    link, sock = link_at(tmp_path / "link", clock)
    expected = feed_events(link, clock.now(), 30)
    clock.advance(arena.LATE_S + 0.1)
    snap = snapshot(clock)
    drain(link, snap)
    assert decode(sock) == expected
    town = arena.KalshiArena(arena.ArenaConfig(data_dir=tmp_path / "town"), lambda: snap,
                            clock=lambda: T0)
    town._windows(snap, T0)
    town.clock = clock.now
    view = arena.WireView()
    for message in sock.messages:
        town.receive(message, view)
    town._drain(clock.now())
    assert town.late == 30 and town.degraded == {snap.windows[0].slug: "feed_late"}


def test_retained_ask_disappearance_cannot_turn_into_a_later_ioc_fill(tmp_path: Path) -> None:
    clock = FakeClock(T0 + 1)
    snap = snapshot(clock)
    slug = snap.windows[0].slug
    town = arena.KalshiArena(arena.ArenaConfig(data_dir=tmp_path / "town"), lambda: snap,
                            clock=lambda: T0)
    town._windows(snap, T0)
    town.clock = clock.now
    town.tape.feed(80_000, clock.now(), 0.0003)
    res = next(iter(town.residents.values()))
    bids, asks = (Level(0.48, 10),), (Level(0.5, 10),)
    for side in ("up", "down"):
        res.desk.on_book(Book(slug, side, bids, asks, clock.now(), "initial", clock.now()))
    res.desk.orders[1] = PracticeOrder(1, slug, "up", "take", 0.5, 1, 1, T0 + 0.5, T0 + 0.75,
                                     0.6, 0.07)
    link, sock = link_at(tmp_path / "link", clock)
    absent = Book(slug, "up", bids, (), clock.now(), "absent", clock.now())
    returned = replace(absent, asks=asks, sequence="returned")
    link.feed_book(absent)
    link.feed_book(returned)
    sock.blocked = True
    link.flush(snap)
    sock.blocked = False
    drain(link, snap)
    view = arena.WireView()
    for message in sock.messages:
        town.receive(message, view)
    town._drain(clock.now())
    assert not res.desk.orders and res.desk.inventory[slug].spent == 0
    assert town.coalesced == 0 and town.degraded == {}


def test_fifo_maker_fills_wait_for_the_full_queue_ahead(tmp_path: Path) -> None:
    clock = FakeClock(T0 + 1)
    snap = snapshot(clock)
    slug = snap.windows[0].slug
    town = arena.KalshiArena(arena.ArenaConfig(data_dir=tmp_path / "town"), lambda: snap,
                            clock=lambda: T0)
    town._windows(snap, T0)
    town.clock = clock.now
    town.tape.feed(80_000, clock.now(), 0.0003)
    res = next(iter(town.residents.values()))
    for side in ("up", "down"):
        res.desk.on_book(Book(slug, side, (Level(0.48, 10),), (Level(0.50, 10),),
                              clock.now(), "initial", clock.now()))
    res.desk.orders[1] = PracticeOrder(1, slug, "up", "rest", 0.48, 2, 2, T0 + 0.1, T0 + 0.2,
                                     0.51, 0, queue_ahead=3)
    link, sock = link_at(tmp_path / "link", clock)
    for n in range(2):
        link.feed_trade(Trade(slug, "up", 0.48, 2, clock.now(), f"print{n}", "sell", clock.now()))
    sock.blocked = True
    link.flush(snap)
    sock.blocked = False
    drain(link, snap)
    view = arena.WireView()
    for message in sock.messages:
        town.receive(message, view)
    town._drain(clock.now())
    assert res.desk.orders[1].queue_ahead == 0 and res.desk.orders[1].remaining == 1
    assert res.desk.inventory[slug].up.shares == 1 and res.desk.inventory[slug].spent == 0.48

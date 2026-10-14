"""Independent attacks on arena evidence transport; all feeds and sockets are local fakes."""

from __future__ import annotations

import marshal
from collections import deque
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from kalshi_arena_world import T0, kalshi_window

from nightcrawler import kalshi_arena as arena
from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, PracticeOrder, Trade


class PartialSocket:
    def __init__(self, chunks: list[int | None] | None = None) -> None:
        self.chunks = deque(chunks or [])
        self.wire = bytearray()

    def send(self, data: bytes) -> int:
        amount = self.chunks.popleft() if self.chunks else len(data)
        if amount is None:
            raise BlockingIOError
        amount = min(amount, len(data))
        self.wire.extend(data[:amount])
        return amount

    def close(self) -> None:
        pass

    def messages(self) -> list[Any]:
        result: list[Any] = []
        offset = 0
        while offset < len(self.wire):
            size = int.from_bytes(self.wire[offset:offset + 4], "little")
            assert len(self.wire) >= offset + 4 + size, "an incomplete frame must stay buffered"
            result.append(marshal.loads(self.wire[offset + 4:offset + 4 + size]))
            offset += 4 + size
        return result


class Process:
    pid = 123

    def poll(self) -> None:
        return None


def fake_link(path: Path, sock: PartialSocket) -> arena.ArenaLink:
    ticks = iter(range(0, 100_000 * arena.FLUSH_BUDGET_NS, arena.FLUSH_BUDGET_NS))
    link = arena.ArenaLink(arena.ArenaConfig(data_dir=path), clock=lambda: T0 + 1,
                           perf=lambda: next(ticks))
    link.sock, link.proc, link.running = sock, Process(), True  # type: ignore[assignment]
    return link


def finish(link: arena.ArenaLink, snap: LiveSnapshot) -> None:
    for _ in range(1000):
        link.flush(snap)
        if not link.pending and not link.out:
            return
    pytest.fail("finite fake backlog failed to drain")


def new_town(path: Path) -> tuple[arena.KalshiArena, arena.WireView, FakeClock]:
    clock = FakeClock(T0 - 5)
    view = arena.WireView()
    town = arena.KalshiArena(arena.ArenaConfig(data_dir=path), lambda: view, clock=clock.now)
    clock.advance(5)
    return town, view, clock


def test_drop_report_in_first_window_frame_cannot_become_valid_coverage(tmp_path: Path) -> None:
    town, view, clock = new_town(tmp_path)
    window = kalshi_window(T0)
    town.receive(("batch", 1, clock.now(), 1, 0, [("w", (arena.window_wire(window),))]), view)
    town._windows(view, clock.now())
    assert town.degraded == {window.slug: "feed_dropped"}


@pytest.mark.parametrize("report", ["counter", "sequence"])
def test_gap_received_just_after_close_still_voids_unsettled_window(tmp_path: Path, report: str) -> None:
    town, view, clock = new_town(tmp_path)
    window = kalshi_window(T0)
    town.receive(("batch", 1, clock.now(), 0, 0, [("w", (arena.window_wire(window),))]), view)
    town._windows(view, clock.now())
    clock.advance(900.2)
    seq, dropped = (2, 1) if report == "counter" else (3, 0)
    town.receive(("batch", seq, clock.now(), dropped, 0, [("o", ((window.slug, True),))]), view)
    town._settle(view, clock.now())
    assert town.town["void_feed"] == 1 and town.town["windows"] == 0
    assert window.slug not in town.windows


def test_outcome_cannot_overtake_earlier_book_and_print_slices(tmp_path: Path) -> None:
    sock = PartialSocket()
    link = fake_link(tmp_path, sock)
    window = kalshi_window(T0)
    for n in range(arena.FLUSH_CHUNK * 3 + 1):
        link.feed_trade(Trade(window.slug, "up", .4, 1, T0 + 899, str(n), "sell", T0 + 899))
    snap = LiveSnapshot(windows=(window,), outcomes={window.slug: True})
    finish(link, snap)
    seen = 0
    outcomes = 0
    for message in sock.messages():
        seen += sum(record[0] == "t" for record in message[5])
        if any(record[0] == "o" and record[1] for record in message[5]):
            outcomes += 1
            assert seen == arena.FLUSH_CHUNK * 3 + 1, "settlement overtook unsent trade evidence"
    assert outcomes == 1 and link.dropped == 0


def test_partial_frames_and_backpressure_preserve_each_event_exactly_once(tmp_path: Path) -> None:
    sock = PartialSocket([None, 1, None, 3, 7, None, 11, 2, None])
    link = fake_link(tmp_path, sock)
    window = kalshi_window(T0)
    expected: list[Book | Trade] = []
    for n in range(100):
        if n % 3:
            item = Book(window.slug, "up", (Level(.4, n + 1),),
                        (Level(.6, 2),) if n % 2 else (), T0 + 1, str(n), T0 + 1)
            link.feed_book(item)
        else:
            item = Trade(window.slug, "up", .4, 1, T0 + 1, str(n), "sell", T0 + 1)
            link.feed_trade(item)
        expected.append(item)
    finish(link, LiveSnapshot(windows=(window,)))
    ladders: dict[Any, Any] = {}
    decoded = [arena.book_from_wire(record, ladders) if record[0] == "b" else arena.trade_from_wire(record)
               for message in sock.messages() for record in message[5] if record[0] in {"b", "t"}]
    assert decoded == expected
    assert [message[1] for message in sock.messages()] == list(range(1, link.frames + 1))
    assert link.dropped == 0 and link.blocked > 0


def test_encoding_a_slice_never_scans_or_copies_the_remaining_queue(tmp_path: Path) -> None:
    class FrontOnly(deque[Any]):
        def __iter__(self) -> Any:
            pytest.fail("producer scanned the backlog instead of popping its bounded prefix")

        def __getitem__(self, index: Any) -> Any:
            pytest.fail("producer indexed or sliced the backlog")

    sock = PartialSocket()
    link = fake_link(tmp_path, sock)
    window = kalshi_window(T0)
    link.pending = FrontOnly(Trade(window.slug, "up", .4, 1, T0, str(n), "sell", T0)
                             for n in range(arena.PENDING_MAX))
    link.flush(LiveSnapshot(windows=(window,)))
    assert len(link.pending) == arena.PENDING_MAX - arena.FLUSH_CHUNK
    assert sum(record[0] == "t" for record in sock.messages()[0][5]) == arena.FLUSH_CHUNK
    assert link.dropped == 0


def test_intermediate_stale_book_cancels_resting_bid_before_later_sell_print(tmp_path: Path) -> None:
    town, view, clock = new_town(tmp_path)
    window = kalshi_window(T0)
    view.windows = (window,)
    town._windows(view, clock.now())
    clock.advance(4.2)
    now = clock.now()
    town.tape.feed(80_000, now, .0003)
    resident = next(iter(town.residents.values()))
    bids, asks = (Level(.4, 0),), (Level(.6, 5),)
    resident.desk.on_book(Book(window.slug, "up", bids, asks, T0 + .5, "old", T0 + .5))
    resident.desk.on_book(Book(window.slug, "down", bids, asks, now, "down", now))
    resident.desk.orders[1] = PracticeOrder(1, window.slug, "up", "rest", .4, 1, 1,
                                           T0, T0 + .25, .6, 0)
    town.feed_book(Book(window.slug, "up", bids, asks, now, "stale", T0 + 1))
    town.feed_book(Book(window.slug, "up", bids, asks, now, "fresh", now))
    town.feed_trade(Trade(window.slug, "up", .39, 2, now, "sell", "sell", now))
    town._drain(now)
    assert resident.desk.inventory[window.slug].spent == 0
    assert not resident.desk.orders and town.coalesced == 0

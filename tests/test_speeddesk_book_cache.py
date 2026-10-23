"""Immutable market facts are shared; each practice desk still owns its fill history."""

from __future__ import annotations

import gc
import weakref
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest
from kalshi_arena_world import T0, kalshi_window

from nightcrawler import speeddesk_model as model
from nightcrawler.kalshi_arena import ArenaConfig, KalshiArena, WireView, book_wire
from nightcrawler.speeddesk_model import (
    Book,
    Level,
    PracticeDesk,
    PracticeOrder,
    SpeedConfig,
)


def book(sequence: str = "one") -> Book:
    return Book("KXBTC15M-cache", "up", (Level(0.49, 10),), (Level(0.51, 7),), T0, sequence, T0)


def test_shared_book_validates_levels_once_without_changing_wire_or_dataclass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = book()
    before, wire, hashed = asdict(sample), book_wire(sample), hash(sample)
    names = tuple(field.name for field in fields(sample))
    desks = [PracticeDesk(SpeedConfig()) for _ in range(12)]
    checks = 0
    finite = model.math.isfinite

    def counted(value: float) -> bool:
        nonlocal checks
        checks += 1
        return finite(value)

    monkeypatch.setattr(model.math, "isfinite", counted)
    assert all(desk.on_book(sample) for desk in desks)
    assert checks == 4  # two numeric facts per level, once across all residents
    assert asdict(sample) == before and book_wire(sample) == wire and hash(sample) == hashed
    assert tuple(field.name for field in fields(sample)) == names
    assert all(desk.books[(sample.window, sample.side)] is sample for desk in desks)


@pytest.mark.parametrize("side", ["bids", "asks"])
@pytest.mark.parametrize("level", [Level(float("nan"), 1), Level(0.5, float("inf")),
                                  Level(1, 1), Level(0, 1), Level(0.5, -1)])
def test_invalid_shared_book_is_rejected_by_every_resident(side: str, level: Level) -> None:
    sample = replace(book(), **{side: (level,)})
    for _ in range(3):
        desk = PracticeDesk(SpeedConfig())
        assert not desk.on_book(sample)
        assert not desk.books


def test_same_cached_book_keeps_each_desks_timestamp_and_consumed_depth_separate() -> None:
    sample = book()
    first, second = PracticeDesk(SpeedConfig()), PracticeDesk(SpeedConfig())
    key = (sample.window, sample.side, 0.51)
    first.consumed[key] = 4
    second.consumed[key] = 2
    assert first.on_book(sample) and second.on_book(sample)
    assert first.consumed[key] == 4 and second.consumed[key] == 2
    newer = replace(sample, at=T0 + 1, exchange_at=T0 + 1, sequence="newer")
    assert second.on_book(newer)
    assert first.on_book(sample) and not second.on_book(sample)
    assert second.books[(sample.window, sample.side)] is newer
    absent = replace(newer, asks=(), sequence="absent")
    assert first.on_book(absent) and key not in first.consumed
    returned = replace(newer, sequence="returned")
    assert first.on_book(returned) and key not in first.consumed
    assert second.consumed[key] == 2


def test_book_cache_does_not_retain_books_after_consumers_release_them() -> None:
    sample = book()
    desk = PracticeDesk(SpeedConfig())
    assert desk.on_book(sample)
    reference = weakref.ref(sample)
    desk.books.clear()
    del sample
    gc.collect()
    assert reference() is None


def test_deep_books_with_resting_orders_advance_every_resident_every_event(tmp_path: Path) -> None:
    window = kalshi_window(T0)
    now = T0 + 1
    view = WireView(windows=(window,), bitcoin_price=80_000, bitcoin_at=now, sigma=0.0003,
                    maker_windows=frozenset({window.slug}))
    arena = KalshiArena(ArenaConfig(tmp_path), lambda: view, clock=lambda: T0 - 1)
    arena._windows(view, T0)
    arena.clock = lambda: now
    arena.tape.feed(80_000, now, 0.0003)
    bids = tuple(Level(round(0.49 - n / 1000, 4), 10 + n) for n in range(111))
    asks = tuple(Level(round(0.51 + n / 1000, 4), 10 + n) for n in range(168))
    for resident in arena.residents.values():
        for side in ("up", "down"):
            resident.desk.on_book(Book(window.slug, side, bids, asks, now, "initial", now))
        resident.desk.orders[1] = PracticeOrder(1, window.slug, "up", "rest", 0.20, 1, 1,
                                               now - 1, now - 0.75, 0.5, 0.07)
    calls: list[str] = []
    for resident in arena.residents.values():
        advance = resident.desk.advance

        def counted(at: float, original=advance, resident_id=resident.id):  # type: ignore[no-untyped-def]
            calls.append(resident_id)
            return original(at)

        resident.desk.advance = counted  # type: ignore[method-assign]
    for sequence in range(300):
        index = sequence % len(bids)
        bids = bids[:index] + (Level(bids[index].price, 20 + sequence),) + bids[index + 1:]
        arena.feed_book(Book(window.slug, "up", bids, asks, now, str(sequence), now))
    arena._drain(now)
    assert arena.coalesced == 0 and arena.late == 0
    assert len(calls) == 300 * len(arena.residents)
    for resident in arena.residents.values():
        assert resident.desk.books[(window.slug, "up")].sequence == "299"
        assert list(resident.desk.orders) == [1]

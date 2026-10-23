"""Independent cache attacks: mutable input, time ordering, shadow depth and object lifetime."""

from __future__ import annotations

import gc
import math
import random
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from typing import Any

import pytest

from nightcrawler.speeddesk_model import Book, Level, PracticeDesk


def quote(**changes: Any) -> Book:
    return replace(Book("window", "up", (Level(.3, 2),), (Level(.4, 5),), 10, "a", 10), **changes)


@pytest.mark.parametrize("kind", ["list", "tuple_subclass", "level_subclass", "book_subclass", "number_subclass"])
def test_mutable_or_overridden_ladders_never_reuse_old_validation(kind: str) -> None:
    state: dict[str, Any] = {"price": .4, "levels": [Level(.4, 5)]}

    class Ladder(tuple[Any, ...]):
        def __iter__(self) -> Any:
            return iter(state["levels"])

    class ChangingLevel(Level):
        def __getattribute__(self, name: str) -> Any:
            return state["price"] if name == "price" else super().__getattribute__(name)

    class ChangingBook(Book):
        def __getattribute__(self, name: str) -> Any:
            return tuple(state["levels"]) if name == "asks" else super().__getattribute__(name)

    class ChangingNumber(float):
        def __gt__(self, other: Any) -> bool:
            return bool(state["price"] > other)

        def __lt__(self, other: Any) -> bool:
            return bool(state["price"] < other)

    if kind == "list":
        book = quote(asks=state["levels"])
    elif kind == "tuple_subclass":
        book = quote(asks=Ladder())
    elif kind == "level_subclass":
        book = quote(asks=(ChangingLevel(.4, 5),))
    elif kind == "book_subclass":
        book = ChangingBook(**asdict(quote()))
        # asdict turns bids into dictionaries; restore the normal ladder so only asks are overridden.
        object.__setattr__(book, "bids", (Level(.3, 2),))
    else:
        book = quote(asks=(Level(ChangingNumber(.4), 5),))
    desk = PracticeDesk()
    assert desk.on_book(book)
    state["price"] = -.1
    state["levels"][:] = [Level(.4, math.nan)]
    assert not desk.on_book(book)
    state["price"] = .4
    state["levels"][:] = [Level(.4, 5)]
    assert desk.on_book(book)


def test_cached_validation_does_not_replenish_or_cross_contaminate_shadow_depth() -> None:
    shared = quote()
    first, second = PracticeDesk(), PracticeDesk()
    for desk in (first, second):
        assert desk.on_book(shared)
    first.consumed[("window", "up", .4)] = 4
    second.consumed[("window", "up", .4)] = 2
    first.consumed[("other", "down", .4)] = 9
    assert first.on_book(shared) and second.on_book(shared)
    assert first.consumed == {("window", "up", .4): 4, ("other", "down", .4): 9}
    assert second.consumed == {("window", "up", .4): 2}
    # Same price, zero size: the visible ask disappeared; a new Book must invalidate that shadow debit.
    disappeared = replace(shared, asks=(Level(.4, 0),), at=11, exchange_at=11)
    assert first.on_book(disappeared)
    assert first.consumed == {("other", "down", .4): 9}
    assert second.consumed == {("window", "up", .4): 2}


@pytest.mark.parametrize("stale_field", ["at", "exchange_at"])
def test_a_prevalidated_older_book_cannot_replace_current_book_or_clear_its_debits(stale_field: str) -> None:
    older = quote(asks=(), **{stale_field: 9})
    assert PracticeDesk().on_book(older)  # another resident already validated this same object
    desk = PracticeDesk()
    current = quote()
    assert desk.on_book(current)
    desk.consumed[("window", "up", .4)] = 4
    assert not desk.on_book(older)
    assert desk.books[("window", "up")] is current
    assert desk.consumed == {("window", "up", .4): 4}


def test_validation_cache_never_changes_book_serialization_or_dataclass_replace() -> None:
    book = quote()
    original = asdict(book)
    assert PracticeDesk().on_book(book)
    assert asdict(book) == original
    invalid = replace(book, asks=(Level(.4, -1),))
    assert not PracticeDesk().on_book(invalid)
    assert set(asdict(invalid)) == set(original)


def test_retired_books_are_not_kept_alive_by_validation_cache() -> None:
    desk = PracticeDesk()
    refs: list[weakref.ReferenceType[Book]] = []
    for n in range(2000):
        book = quote(at=10 + n, exchange_at=10 + n, sequence=str(n))
        refs.append(weakref.ref(book))
        assert desk.on_book(book)
    del book
    gc.collect()
    assert sum(ref() is not None for ref in refs) == 1  # only the desk's latest quote
    desk.books.clear()
    gc.collect()
    assert all(ref() is None for ref in refs)


def test_concurrent_readers_share_only_immutable_facts_and_keep_separate_depth() -> None:
    book = quote(asks=tuple(Level(.4 + index / 1000, 5) for index in range(100)))

    def consume(count: int) -> dict[Any, Any]:
        desk = PracticeDesk()
        desk.consumed[("window", "up", .4)] = count
        for _ in range(100):
            assert desk.on_book(book)
        return desk.consumed

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(consume, range(12)))
    assert results == [{("window", "up", .4): n} for n in range(12)]


def test_random_book_acceptance_and_consumed_depth_match_uncached_reference() -> None:
    def reference(desk: PracticeDesk, book: Book) -> bool:
        key = (book.window, book.side)
        old = desk.books.get(key)
        if old and (book.at < old.at or (book.exchange_at is not None and old.exchange_at is not None
                                       and book.exchange_at < old.exchange_at)):
            return False
        if any(not math.isfinite(level.price) or not math.isfinite(level.size)
               or not 0 < level.price < 1 or level.size < 0 for level in (*book.bids, *book.asks)):
            return False
        desk.books[key] = book
        prices = {level.price for level in book.asks if level.size > 0}
        desk.consumed = {item: value for item, value in desk.consumed.items()
                         if item[:2] != key or item[2] in prices}
        return True

    rng = random.Random(914)
    cached, plain = PracticeDesk(), PracticeDesk()
    for n in range(1000):
        price = rng.choice([.3, .4, .5, -1, 1])
        size = rng.choice([0, 1, 5, -1, math.nan])
        at = 10 + n // 5 - rng.choice([0, 0, 1])
        book = quote(asks=(Level(price, size),), at=at, exchange_at=at, sequence=str(n))
        for desk in (cached, plain):
            desk.consumed.update({("window", "up", .4): 2, ("unrelated", "up", .3): 1})
        assert cached.on_book(book) == reference(plain, book)
        assert cached.books == plain.books and cached.consumed == plain.consumed

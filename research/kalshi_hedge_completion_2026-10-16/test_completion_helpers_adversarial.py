"""Independent pure boundary probes for the proposed completion helper module."""

from __future__ import annotations

from pathlib import Path

from test_hedge_adversarial import seeded

from nightcrawler.speeddesk_live_completion import completion_guard, external_asks
from nightcrawler.speeddesk_live_model import LiveIntent, OrderSnapshot
from nightcrawler.speeddesk_model import Book, Level


def reflected(desk, clock, quantity=5):
    return Book(next(iter(desk.book.windows)), "down", (), (Level(.43, quantity),),
                clock.now(), "review", source="rest", requested_at=clock.now())


def test_partial_fill_cannot_make_old_own_depth_look_external(tmp_path: Path) -> None:
    desk, _, clock = seeded(tmp_path, filled=2)
    try:
        # The book predates the private fill, but is within the three-second
        # freshness allowance. All five displayed contracts can still be ours.
        book = reflected(desk, clock)
        assert external_asks(desk.book, book.window, "down", book) == []
    finally:
        desk.close()


def test_terminal_cancel_cannot_make_old_own_depth_look_external(tmp_path: Path) -> None:
    desk, _, clock = seeded(tmp_path, filled=2)
    try:
        identity = "nc-speed-review-seed"
        slug = next(iter(desk.book.windows))
        desk.book.reconcile_order(OrderSnapshot(identity, "seed", "canceled", 2, 0, clock.now()),
                                  fills_complete=True)
        assert not desk.book.intents[identity].reservation_active
        book = reflected(desk, clock)
        assert external_asks(desk.book, slug, "down", book) == []
    finally:
        desk.close()


def test_overlapping_pending_claims_fail_transport_guard(tmp_path: Path) -> None:
    desk, _, clock = seeded(tmp_path)
    try:
        slug = next(iter(desk.book.windows))
        first = desk.book.reserve_intent(slug, "down", "take", .4, 3, clock.now(),
                                         "nc-speed-review-hedge", completion=True)
        # Inject a second liability at the transport trust boundary; ordinary
        # admission prohibits this, but the guard must independently refuse it.
        other = LiveIntent("nc-speed-review-overlap", slug, "down", "take", .4, 3,
                           clock.now(), first.unit_reserve, completion=True)
        desk.book.intents[other.client_order_id] = other
        assert not completion_guard(desk.book, first.client_order_id, clock.now())
    finally:
        desk.close()

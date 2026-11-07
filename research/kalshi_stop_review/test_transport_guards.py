"""Additional fake-only post-journal/before-send attacks for final stop integration."""

import asyncio
from dataclasses import replace

import pytest
from test_speeddesk_live import TICKER
from test_speeddesk_live_pull import market
from test_speeddesk_live_stop_controller_review import _filled_starter, _stop

from nightcrawler.speeddesk_model import Holding


@pytest.mark.parametrize(
    "trigger",
    [
        "paper",
        "no_confirmation",
        "no_keys",
        "authentication_error",
        "no_balance",
        "account_stale",
        "bitcoin_stale",
        "book_stale",
        "shutdown",
        "foreign",
        "changed_terms",
        "cutoff",
        "pull",
        "no_longer_balancing",
        "unknown_halt",
        "integrity",
    ],
)
def test_financial_stop_hedge_cannot_bypass_gate_that_changes_before_send(
    tmp_path, trigger
):
    desk, account, clock = _filled_starter(tmp_path)
    original = account.create_order
    guard_results = []

    def attack(**kwargs):
        if trigger == "paper":
            desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
        elif trigger == "no_confirmation":
            desk.settings = replace(desk.settings, speeddesk_kalshi_live_confirm=None)
        elif trigger == "no_keys":
            desk.settings = replace(desk.settings, kalshi_key_id=None)
        elif trigger == "authentication_error":
            desk.auth_failed = True
        elif trigger == "no_balance":
            desk.authenticated = False
        elif trigger == "account_stale":
            desk.account_at = clock.now() - 3.01
        elif trigger == "bitcoin_stale":
            snap = replace(desk.snapshot(), bitcoin_at=clock.now() - 3.01)
            desk.snapshot = lambda: snap
        elif trigger == "book_stale":
            snap = desk.snapshot()
            books = {
                key: replace(book, at=clock.now() - 4)
                for key, book in snap.books.items()
            }
            snap = replace(snap, books=books)
            desk.snapshot = lambda: snap
        elif trigger == "shutdown":
            desk.stopping = True
        elif trigger == "foreign":
            desk.foreign_windows.add(TICKER)
        elif trigger == "changed_terms":
            desk.changed_windows.add(TICKER)
        elif trigger == "cutoff":
            clock.advance(
                desk.book.windows[TICKER].end - desk.book.limits.lock_s - clock.now()
            )
            market(desk, clock, 0.5)
            desk.account_at = clock.now()
        elif trigger == "pull":
            market(desk, clock, 0.52)
        elif trigger == "no_longer_balancing":
            desk.book.inventory[TICKER].down = Holding(shares=5, cost=2.35)
        elif trigger == "unknown_halt":
            desk.book.halt_reason = "unknown_stop"
        elif trigger == "integrity":
            desk.book.integrity_error = "bad_fill"
        guard = kwargs["before_send"]

        def observe_guard():
            result = guard()
            guard_results.append(result)
            return result

        kwargs["before_send"] = observe_guard
        return original(**kwargs)

    try:
        _stop(desk, clock, "total")
        account.create_order = attack
        asyncio.run(desk.step())
        assert len(account.creates) == 1
        assert guard_results == [False]
        assert desk.book.halted
    finally:
        desk.close()

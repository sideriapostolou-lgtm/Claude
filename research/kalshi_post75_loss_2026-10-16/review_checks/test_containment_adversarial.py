"""Independent production-policy fakes; no network or containment-helper overrides.

Historical orders/fills are injected as explicitly identified venue receipts.
They supply existing obligations, never authorize a new controller first entry.
Run with repository src and tests on pytest's pythonpath.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_speeddesk_live import TICKER, make_desk, reopen

from nightcrawler.speeddesk_live import (
    Intent,
    KalshiLiveDesk,
    LiveSnapshot,
    durable_state,
)
from nightcrawler.speeddesk_live_model import ActualFill, LiveIntent
from nightcrawler.speeddesk_model import Book, Level


def fresh(desk: Any, clock: Any, *, age: float = 0) -> None:
    window = desk.book.windows[TICKER]
    books = {(TICKER, side): Book(TICKER, side, (), (Level(price, 20),),
                                  clock.now() - age, "independent-fake", source="rest",
                                  requested_at=clock.now() - age)
             for side, price in (("up", .9), ("down", .4))}
    snapshot = LiveSnapshot((window,), books, 80000, clock.now(), .001, frozenset({TICKER}))
    desk.snapshot = lambda: snapshot


def production(tmp_path: Path) -> tuple[Any, Any, Any]:
    desk, account, clock = make_desk(tmp_path, caps={"speeddesk_kalshi_window_usd": 20,
                                                  "speeddesk_kalshi_open_usd": 40},
                                     extra={"speeddesk_kalshi_pull": False})
    # Guard against a future historical-factory import accidentally weakening this suite.
    assert type(desk) is KalshiLiveDesk
    assert "_entry_allowed" not in desk.__dict__
    assert "_entry_intent_allowed" not in desk.__dict__
    fresh(desk, clock)
    asyncio.run(desk._ensure_client())
    asyncio.run(desk._startup())
    return desk, account, clock


def legacy_receipt(desk: Any, account: Any, clock: Any, name: str, side: str,
                   size: float, filled: float, price: float = .6) -> str:
    """Install a prior owned order and its confirmed fills, not a new admission."""
    identity, order_id = "nc-speed-audit-" + name, "audit-" + name
    item = LiveIntent(identity, TICKER, side, "rest", price, size, clock.now(), price,
                      fair=.5, order_id=order_id)
    desk.book.intents[identity] = item
    desk.intents[identity] = Intent(identity, TICKER, side, "rest", price, size, .5,
                                    clock.now(), order_id=order_id, terminal=filled == size)
    if filled:
        assert desk.book.record_fill(ActualFill("fill-" + name, order_id, identity, TICKER,
                                                side, price, filled, 0, clock.now()))
        account.executions.append({"fill_id": "fill-" + name, "order_id": order_id,
                                   "ticker": TICKER, "outcome_side": "yes" if side == "up" else "no",
                                   "book_side": "bid" if side == "up" else "ask", "count_fp": str(filled),
                                   "yes_price_dollars": str(price if side == "up" else 1 - price),
                                   "fee_cost": "0.0000", "ts": clock.now()})
    account.orders.append({"order_id": order_id, "client_order_id": identity, "ticker": TICKER,
                           "status": "executed" if filled == size else "resting",
                           "fill_count_fp": str(filled), "remaining_count_fp": str(size - filled),
                           "initial_count_fp": str(size), "outcome_side": "yes" if side == "up" else "no",
                           "book_side": "bid" if side == "up" else "ask",
                           "yes_price_dollars": str(price if side == "up" else 1 - price),
                           "no_price_dollars": str(price if side == "down" else 1 - price)})
    value = desk.book.inventory[TICKER]
    difference = value.up.shares - value.down.shares
    account.account_positions = ([{"ticker": TICKER, "position_fp": str(difference)}] if difference else [])
    assert desk.book.integrity_error is None
    return identity


@pytest.mark.parametrize("side", ["up", "down"])
@pytest.mark.parametrize("kind", ["rest", "take"])
def test_equal_negative_pair_has_no_entry_permission(tmp_path: Path, side: str, kind: str) -> None:
    desk, account, clock = production(tmp_path)
    try:
        legacy_receipt(desk, account, clock, "up-loss", "up", 1, 1)
        legacy_receipt(desk, account, clock, "down-loss", "down", 1, 1)
        value = desk.book.inventory[TICKER]
        assert value.spent == pytest.approx(1.2)
        assert min(value.up.shares, value.down.shares) - value.spent == pytest.approx(-.2)
        assert TICKER not in desk.book.protected_windows
        assert not asyncio.run(desk._send(desk.book.windows[TICKER], side, kind, .1, 1, .5))
        assert not account.creates and desk.errors == 0
    finally:
        desk.close()


@pytest.mark.parametrize("size", [0, -1, float("nan"), float("inf"), .5, 6])
def test_invalid_or_excess_amount_never_reaches_transport(tmp_path: Path, size: float) -> None:
    desk, account, clock = production(tmp_path)
    try:
        legacy_receipt(desk, account, clock, "held", "up", 5, 5)
        assert not asyncio.run(desk._send(desk.book.windows[TICKER], "down", "rest", .1, size, .5))
        assert not account.creates and len(desk.intents) == 1 and desk.errors == 0
    finally:
        desk.close()


@pytest.mark.parametrize("unit", [1.0, 1.01, float("inf")])
def test_unit_cost_at_least_one_is_not_reduction(tmp_path: Path, unit: float) -> None:
    desk, account, clock = production(tmp_path)
    try:
        legacy_receipt(desk, account, clock, "held", "up", 5, 5)
        assert not desk._entry_allowed(TICKER, "down", 1, unit)
        old = legacy_receipt(desk, account, clock, "costly", "down", 1, 0, .1)
        desk.book.intents[old].unit_reserve = unit
        assert not desk._entry_intent_allowed(old)
        asyncio.run(desk._cancel_unsafe())
        assert account.cancels == ["audit-costly"]
        assert desk.book.intents[old].reservation_active
    finally:
        desk.close()


@pytest.mark.parametrize("state", ["partial", "uncertain", "cancel_requested"])
def test_new_transport_cannot_reuse_older_claimed_inventory(tmp_path: Path, state: str) -> None:
    desk, account, clock = production(tmp_path)
    legacy_receipt(desk, account, clock, "held", "up", 5, 5)
    send = account.create_order
    older: list[str] = []

    def race(**kwargs: Any) -> dict[str, Any]:
        attempted = kwargs["client_order_id"]
        saved = durable_state(desk.ledger)
        assert saved is not None and attempted in saved["book"]["intents"]
        identity = legacy_receipt(desk, account, clock, "older-claim", "down", 3,
                                  2 if state == "partial" else 0, .1)
        older.append(identity)
        if state == "uncertain":
            desk.intents[identity].uncertain = True
            desk.book.mark_uncertain(identity, "fake-prior-request")
        if state == "cancel_requested":
            desk.intents[identity].cancel_requested = True
            desk.book.request_cancel(identity)
        return send(**kwargs)

    account.create_order = race
    try:
        assert asyncio.run(desk._send(desk.book.windows[TICKER], "down", "rest", .1, 5, .5))
        assert not account.creates and len(older) == 1
        attempted = next(item for key, item in desk.intents.items()
                         if key not in {"nc-speed-audit-held", older[0]})
        assert attempted.terminal and not attempted.uncertain
        assert not desk.book.intents[attempted.client_order_id].reservation_active
        assert desk.book.intents[older[0]].reservation_active
        assert desk.book.intents[older[0]].remaining == (1 if state == "partial" else 3)
        assert desk.book.inventory[TICKER].down.shares == (2 if state == "partial" else 0)
        assert desk.errors == 0 and desk.fatal_reason is None
        assert any(row.get("state") == "not sent; prices moved before send" for row in desk.latest_events)
    finally:
        desk.close()


@pytest.mark.parametrize("venue", ["kalshi", "polymarket"])
def test_another_window_cannot_borrow_existing_obligation(tmp_path: Path, venue: str) -> None:
    desk, account, clock = production(tmp_path)
    try:
        legacy_receipt(desk, account, clock, "held", "up", 5, 5)
        old = desk.snapshot()
        slug = "KXBTC15M-other" if venue == "kalshi" else "foreign-btc-window"
        other = replace(old.windows[0], slug=slug, venue=venue)
        if venue == "kalshi":
            desk.on_windows([other])
        books = {(slug, side): replace(book, window=slug) for (_, side), book in old.books.items()}
        snapshot = replace(old, windows=(other,), books=books, maker_windows=frozenset({slug}))
        desk.snapshot = lambda: snapshot
        asyncio.run(desk._decide())
        assert not account.creates and desk.errors == 0
        assert desk._entry_contracts(slug, "down") == 0
    finally:
        desk.close()


@pytest.mark.parametrize("filled", [0, 2])
def test_recovered_legacy_starter_cannot_retain_risk_increasing_remainder(tmp_path: Path, filled: float) -> None:
    desk, account, clock = production(tmp_path)
    identity = legacy_receipt(desk, account, clock, "restored", "up", 5, filled)
    desk.checkpoint(durable=True)
    restored = reopen(tmp_path, desk, account, clock, caps={"speeddesk_kalshi_window_usd": 20,
                                                        "speeddesk_kalshi_open_usd": 40})
    try:
        assert type(restored) is KalshiLiveDesk
        assert restored.book.intents[identity].reservation_active
        asyncio.run(restored._ensure_client())
        asyncio.run(restored._cancel_unsafe())
        assert account.cancels == ["audit-restored"]
        assert restored.book.intents[identity].reservation_active
        assert restored.book.intents[identity].remaining == 5 - filled
        asyncio.run(restored._reconcile())
        assert not restored.book.intents[identity].reservation_active
        assert restored.book.inventory[TICKER].up.shares == filled
        assert restored.panel()["pair_execution"]["automatic_resume"] is False
    finally:
        restored.close()


@pytest.mark.parametrize("gate", ["fresh", "stale_book", "foreign", "not_late"])
def test_late_lock_is_preserved_with_its_original_guards(tmp_path: Path, gate: str) -> None:
    desk, account, clock = production(tmp_path)
    try:
        legacy_receipt(desk, account, clock, "held", "up", 5, 5)
        if gate != "not_late":
            clock.advance(780)
        fresh(desk, clock, age=4 if gate == "stale_book" else 0)
        asyncio.run(desk._reconcile())
        if gate == "foreign":
            desk.foreign_windows.add(TICKER)
        asyncio.run(desk._send_lock(desk.book.windows[TICKER], "down", .4, 5))
        assert len(account.creates) == (1 if gate == "fresh" else 0)
        assert desk.errors == 0 and desk.fatal_reason is None
        if account.creates:
            assert desk.intents[account.creates[0]["client_order_id"]].lock
    finally:
        desk.close()

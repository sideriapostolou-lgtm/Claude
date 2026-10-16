"""Historical admission fixtures exercise prior policy; they do not establish current production admission.

Slow reads must not delay safe cancellation; all network and account state here is fake."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_kalshi_client import Response, ack, create, pem
from test_speeddesk_live import TICKER

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_kalshi_client import KalshiClient, KalshiClientError


def client(transport: Any, clock: FakeClock | None = None, **kwargs: Any) -> KalshiClient:
    return KalshiClient("throwaway-responsiveness-test", pem(Ed25519PrivateKey.generate()),
                        transport=transport, clock=clock or FakeClock(1000), **kwargs)


@pytest.mark.parametrize("trigger", ["stale", "cutoff", "mode", "confirmation", "fair_drop", "stop"])
def test_pending_account_read_checks_cancellations_without_admitting_new_buys(tmp_path: Path, trigger: str) -> None:
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_kalshi_pull": False,
                                                    "speeddesk_take_edge": 1.0, "speeddesk_make_edge": .12})
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    original, cancel = account.list_orders, account.cancel

    def slow_orders(**kwargs: Any) -> list[dict[str, Any]]:
        entered.set()
        assert release.wait(3), "Fake read was not released"
        return original(**kwargs)

    def observed_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
        result = cancel(order_id, ticker=ticker)
        cancelled.set()
        return result

    async def scenario() -> None:
        await desk.step()
        assert len(account.creates) == 1 and account.creates[0]["kind"] == "rest"
        reserved = desk.book.reserved_usd
        account.list_orders = slow_orders  # type: ignore[method-assign]
        account.cancel = observed_cancel  # type: ignore[method-assign]
        task = asyncio.create_task(desk.step())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            if trigger == "stale":
                clock.advance(4)
            elif trigger == "cutoff":
                clock.advance(711)
            elif trigger == "mode":
                desk.settings = replace(desk.settings, speeddesk_kalshi_mode="paper")
            elif trigger == "confirmation":
                desk.settings = replace(desk.settings, speeddesk_kalshi_live_confirm=None)
            elif trigger == "fair_drop":
                snapshot = replace(desk.snapshot(), bitcoin_price=79000)
                desk.snapshot = lambda: snapshot
            else:
                desk.stop_event = threading.Event()
                desk.stop_event.set()
            assert await asyncio.to_thread(cancelled.wait, 2)
            assert not task.done() and desk.book.reserved_usd == reserved
            assert len(account.creates) == 1 and account.cancels == ["order-1"]
        finally:
            release.set()
            await asyncio.wait_for(task, 3)
        # Once the complete read proves the cancel, fair-value repricing may start a fresh quote normally.
        assert len(account.creates) == (2 if trigger == "fair_drop" else 1)
        assert not desk.book.integrity_error

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        desk.close()


def test_get_and_cancel_have_separate_transport_lanes() -> None:
    entered, release = threading.Event(), threading.Event()

    def transport(method: str, _url: str, **_kwargs: Any) -> Response:
        if method == "GET":
            entered.set()
            assert release.wait(3)
            return Response({"balance": 2500})
        return Response({"order_id": "owned", "reduced_by": "2.00", "ts_ms": 1000000})

    c = client(transport)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(c.balance)
            try:
                assert entered.wait(2)
                cancelling = pool.submit(c.cancel, "owned", ticker=TICKER)
                assert cancelling.result(timeout=2)["reduced_by"] == "2.00"
                assert not reading.done()
            finally:
                release.set()
            reading.result(timeout=2)
    finally:
        release.set()
        c.close()


@pytest.mark.parametrize("status", [200, 404])
def test_fill_racing_a_cancel_during_get_is_booked_once_before_reservation_release(tmp_path: Path, status: int) -> None:
    desk, account, clock = make_historical_desk(tmp_path, extra={"speeddesk_kalshi_pull": False,
                                                    "speeddesk_take_edge": 1.0, "speeddesk_make_edge": .12})
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    original = account.list_orders

    def slow_orders(**kwargs: Any) -> list[dict[str, Any]]:
        entered.set()
        assert release.wait(3)
        return original(**kwargs)

    def fill_then_cancel(order_id: str, *, ticker: str) -> dict[str, Any]:
        account.cancels.append(order_id)
        order = account.orders[0]
        assert ticker == order["ticker"] and order_id == order["order_id"]
        order.update(status="canceled", fill_count_fp="2.00", remaining_count_fp="0.00")
        account.executions.append({"fill_id": "race-fill", "order_id": order_id, "ticker": ticker,
                                   "outcome_side": "yes", "book_side": "bid", "count_fp": "2.00",
                                   "yes_price_dollars": "0.38", "fee_cost": "0.0000", "ts": clock.now()})
        account.account_positions = [{"ticker": ticker, "position_fp": "2.00"}]
        account.cash = 25 - .76
        cancelled.set()
        if status == 404:
            raise KalshiClientError("cancel", "request rejected", status=404)
        return {}

    async def scenario() -> None:
        await desk.step()
        reserved = desk.book.reserved_usd
        account.list_orders = slow_orders  # type: ignore[method-assign]
        account.cancel = fill_then_cancel  # type: ignore[method-assign]
        task = asyncio.create_task(desk.step())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            clock.advance(4)
            assert await asyncio.to_thread(cancelled.wait, 2)
            assert desk.book.reserved_usd == reserved
            assert desk.book.inventory[TICKER].up.shares == 0  # no simulated inventory from cancel ack
        finally:
            release.set()
            await asyncio.wait_for(task, 3)
        assert desk.book.inventory[TICKER].up.shares == 2
        assert desk.book.reserved_usd == 0 and desk.book.at_risk_usd == pytest.approx(.76)
        assert len(desk.book.fills) == 1 and len(account.creates) == 1
        await desk._reconcile()
        assert len(desk.book.fills) == 1 and desk.book.inventory[TICKER].up.shares == 2
        assert not desk.book.integrity_error and desk.errors == 0

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        desk.close()


def test_reads_and_writes_reuse_different_sessions_and_both_are_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, requests.Session]] = []
    closed: list[requests.Session] = []

    def request(session: requests.Session, method: str, _url: str, **_kwargs: Any) -> Response:
        calls.append((method, session))
        return Response({"balance": 2500} if method == "GET" else
                        {"order_id": "owned", "reduced_by": "2.00", "ts_ms": 1000000})

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr(requests.Session, "close", lambda session: closed.append(session))
    c = KalshiClient("throwaway-session-test", pem(Ed25519PrivateKey.generate()), clock=FakeClock(1000))
    try:
        for _ in range(2):
            c.balance()
            c.cancel("owned", ticker=TICKER)
        assert calls[0][1] is calls[2][1] and calls[1][1] is calls[3][1]
        assert calls[0][1] is not calls[1][1]
    finally:
        c.close()
    assert len(closed) == 2 and set(closed) == {calls[0][1], calls[1][1]}


def test_writes_stay_serialized_and_guard_runs_only_after_the_prior_write() -> None:
    entered, release, attempted, guarded = (threading.Event() for _ in range(4))
    methods: list[str] = []

    def transport(method: str, _url: str, **_kwargs: Any) -> Response:
        methods.append(method)
        if method == "DELETE":
            entered.set()
            assert release.wait(3)
            return Response({"order_id": "owned", "reduced_by": "2.00", "ts_ms": 1000000})
        return ack()

    c = client(transport)

    def order() -> dict[str, Any]:
        attempted.set()

        def guard() -> bool:
            guarded.set()
            return False  # price moved while waiting for the preceding write

        return create(c, before_send=guard)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancelling = pool.submit(c.cancel, "owned", ticker=TICKER)
            try:
                assert entered.wait(2)
                creating = pool.submit(order)
                assert attempted.wait(2)
                assert not guarded.wait(.03) and methods == ["DELETE"]
            finally:
                release.set()
            cancelling.result(timeout=2)
            with pytest.raises(KalshiClientError, match="send_guard_rejected"):
                creating.result(timeout=2)
            assert guarded.is_set() and methods == ["DELETE"]
    finally:
        release.set()
        c.close()


def test_get_rate_wait_does_not_hold_the_write_budget_lock() -> None:
    sleeping, release = threading.Event(), threading.Event()

    class BlockingClock(FakeClock):
        def sleep(self, seconds: float) -> None:
            sleeping.set()
            assert release.wait(3)
            super().sleep(seconds)

    clock = BlockingClock(1000)
    sent: list[tuple[str, float]] = []

    def transport(method: str, _url: str, **_kwargs: Any) -> Response:
        sent.append((method, clock.now()))
        return Response({"balance": 2500} if method == "GET" else
                        {"order_id": "owned", "reduced_by": "2.00", "ts_ms": 1000000})

    c = client(transport, clock, reads_per_s=1)
    try:
        c.balance()
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(c.balance)
            try:
                assert sleeping.wait(2)
                pool.submit(c.cancel, "owned", ticker=TICKER).result(timeout=2)
                assert sent == [("GET", 1000), ("DELETE", 1000)]
            finally:
                release.set()
            reading.result(timeout=2)
            assert sent[-1] == ("GET", 1001)
    finally:
        release.set()
        c.close()


def test_other_lane_success_cannot_erase_a_new_shared_429_cooldown() -> None:
    entered, release = threading.Event(), threading.Event()
    clock = FakeClock(1000)
    reads, writes = 0, 0

    def transport(method: str, _url: str, **_kwargs: Any) -> Response:
        nonlocal reads, writes
        if method == "GET":
            reads += 1
            if reads == 1:
                entered.set()
                assert release.wait(3)
                return Response({"balance": 2500})
            return Response({}, 429)
        writes += 1
        return (Response({}, 429) if writes == 1 else
                Response({"order_id": "owned", "reduced_by": "2.00", "ts_ms": 1000000}))

    c = client(transport, clock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(c.balance)
            try:
                assert entered.wait(2)
                with pytest.raises(KalshiClientError) as error:
                    pool.submit(c.cancel, "owned", ticker=TICKER).result(timeout=2)
                assert error.value.status == 429
            finally:
                release.set()
            reading.result(timeout=2)  # arrived after 429, before its cooldown expired
        with pytest.raises(KalshiClientError):
            c.balance()
        assert clock.now() == 1002
        c.cancel("owned", ticker=TICKER)
        assert clock.now() == 1006 and clock.sleeps == [2, 4]
    finally:
        release.set()
        c.close()


def test_partial_second_page_stays_an_error_while_cancel_lane_is_available() -> None:
    entered, release = threading.Event(), threading.Event()
    reads = 0

    def transport(method: str, _url: str, **_kwargs: Any) -> Response:
        nonlocal reads
        if method == "GET":
            reads += 1
            if reads == 1:
                return Response({"orders": [{"order_id": "first-page"}], "cursor": "next"})
            entered.set()
            assert release.wait(3)
            return Response({}, 503)
        return Response({"order_id": "owned", "reduced_by": "2.00", "ts_ms": 1000000})

    c = client(transport)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(c.list_orders)
            try:
                assert entered.wait(2)
                pool.submit(c.cancel, "owned", ticker=TICKER).result(timeout=2)
                assert not reading.done()
            finally:
                release.set()
            with pytest.raises(KalshiClientError) as error:
                reading.result(timeout=2)
            assert error.value.status == 503 and "list_orders" not in c.read_stats
    finally:
        release.set()
        c.close()


def test_request_diagnostics_are_numeric_bounded_and_include_errors_without_sensitive_text() -> None:
    calls = 0

    def transport(_method: str, _url: str, **_kwargs: Any) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise requests.Timeout("sensitive fake header and response text")
        return Response({"balance": 2500})

    c = client(transport)
    try:
        with pytest.raises(KalshiClientError):
            c.balance()
        report = c.request_timings()
        failed = report["samples"][0]
        assert failed["operation"] == "balance" and failed["ok"] is False
        assert failed["http_ms"] >= 0 and failed["decode_ms"] is None
        assert "sensitive" not in json.dumps(report) and "throwaway" not in json.dumps(report)
        for _ in range(1026):
            c.balance()
        report = c.request_timings()
        assert len(report["samples"]) == 1024 and report["dropped"] == 2
        assert all(sample["ok"] and sample["total_ms"] >= sample["http_ms"] >= 0 for sample in report["samples"])
        assert c.request_timings() == {"samples": [], "dropped": 0}
    finally:
        c.close()

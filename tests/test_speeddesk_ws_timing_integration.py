"""Timing is additive to the real market receiver and its freshness rejection."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from test_speeddesk_feed_fairness import NOW, reader
from test_speeddesk_kalshi_ws import TICKER, FakeSocket, ack, delta, settings, snapshot
from test_speeddesk_ws_timing import connection, feed, text

from nightcrawler import speeddesk_kalshi_ws
from nightcrawler.speeddesk_kalshi_ws import KalshiMarketWS, MarketDataGap
from nightcrawler.speeddesk_worktrace import WorkTrace
from nightcrawler.weatherwatch_markets import WeatherWS


def records(caplog: Any) -> list[dict[str, Any]]:
    return [json.loads(record.message.split("speeddesk_feed_kalshi_ws_timing ", 1)[1])
            for record in caplog.records if "speeddesk_feed_kalshi_ws_timing " in record.message]


def test_native_receipt_logs_correspondence_and_keeps_complete_book_pair(caplog: Any) -> None:
    async def run() -> None:
        ws, stop, callbacks = connection(), threading.Event(), []
        feed(ws, text(json.dumps(delta(at=NOW))))
        def callback(kind: str, value: Any) -> None:
            callbacks.append((kind, value))
            stop.set()
        receiver = reader(callback, [])
        await receiver._session(ws, frozenset({TICKER}), stop)
        assert [value.side for _, value in callbacks] == ["up", "down"]
        assert all(value.at == NOW for _, value in callbacks)
        row = records(caplog)[0]
        assert row["event"] == "status" and row["kind"] == "orderbook_delta"
        assert row["receipt"]["ordinal"] == row["connection"]["received"] == 1
        assert row["receipt"]["status"] == "known"
        assert row["receipt"]["accepted_monotonic"] <= row["recv_return_mono"] <= row["apply_mono"]
        assert row["sending_ts_ms"] == row["engine_ts_ms"] == int(NOW * 1000)
        assert receiver.state.exchange_at[TICKER] == NOW
    caplog.set_level("INFO")
    asyncio.run(run())


def test_stale_message_keeps_original_rejection_and_reports_both_source_domains(caplog: Any) -> None:
    async def run() -> None:
        ws = connection()
        raw = delta(at=NOW - 3.5)
        raw["msg"]["ts_ms"] = int((NOW - 4) * 1000)
        feed(ws, text(json.dumps(raw)))
        callbacks: list[Any] = []
        receiver = reader(lambda *args: callbacks.append(args), [])
        receiver.work_trace = WorkTrace()
        with pytest.raises(MarketDataGap, match="orderbook_delta_network:age_s=3.500"):
            await receiver._session(ws, frozenset({TICKER}), threading.Event())
        assert records(caplog) == []  # No query/log before the existing invalidation path.
        receiver.connected = False
        receiver._report("reconnecting_public_rest_fallback", invalidate=True)
        receiver._flush_timing_gap(ws)
        row = records(caplog)[0]
        assert row["event"] == "gap"
        assert row["sending_ts_ms"] == raw["sending_ts_ms"]
        assert row["engine_ts_ms"] == raw["msg"]["ts_ms"]
        assert row["apply_wall"] == NOW and row["receipt"]["status"] == "known"
        assert row["local_work"]["start_mono"] == row["receipt"]["accepted_monotonic"]
        assert not callbacks
    caplog.set_level("INFO")
    asyncio.run(run())


def test_diagnostic_failure_preserves_stale_rejection_and_never_logs_arbitrary_frame(caplog: Any) -> None:
    async def run() -> None:
        ws = connection()
        feed(ws, text(json.dumps(delta(at=NOW - 3.5))))
        def broken() -> Any:
            raise RuntimeError("DO_NOT_LOG_SERVER_OR_SECRET_TEXT")
        ws.timing_status = broken  # type: ignore[method-assign]
        receiver = reader(lambda *_: pytest.fail("stale callback"), [])
        with pytest.raises(MarketDataGap, match="orderbook_delta_network"):
            await receiver._session(ws, frozenset({TICKER}), threading.Event())
        receiver._flush_timing_gap(ws)
        assert "speeddesk_feed_kalshi_ws_timing_unavailable" in caplog.text
        assert "DO_NOT_LOG" not in caplog.text
        # Only fixed kinds and genuine integer timestamps reach timing logs.
        del ws.timing_status
        receiver._timing_report(ws, event="gap", call_mono=1, returned_mono=2,
            apply_mono=3, apply_wall=NOW, raw={"type": "DO_NOT_LOG_ARBITRARY_KIND",
                "sending_ts_ms": "DO_NOT_LOG_ARBITRARY_VALUE", "msg": {"ts_ms": True}}, previous=None)
        assert records(caplog)[-1]["kind"] == "other"
        assert records(caplog)[-1]["sending_ts_ms"] is None
        assert records(caplog)[-1]["engine_ts_ms"] is None
        assert "DO_NOT_LOG" not in caplog.text
    caplog.set_level("INFO")
    asyncio.run(run())


def test_run_invalidates_before_gap_diagnostic_and_before_awaiting_close() -> None:
    config, _ = settings()
    stop, statuses, observed = threading.Event(), [], []
    ws = FakeSocket([ack(), snapshot(), delta(at=NOW - 3.5)], stop, statuses)
    receiver = KalshiMarketWS(config, tickers=lambda: frozenset({TICKER}),
        on_book=lambda _: pytest.fail("stale callback"), on_trade=lambda _: None,
        on_status=statuses.append, clock=lambda: NOW, ws_connect=lambda *_, **__: ws)
    def diagnostic(_ws: Any, **context: Any) -> None:
        if context["event"] == "status":
            return
        assert context["event"] == "gap"
        assert receiver.connected is False and statuses[-1]["gap_windows"] == [TICKER]
        assert not ws.closed  # The close handshake has not started.
        observed.append(context)
    receiver._timing_report = diagnostic  # type: ignore[method-assign]
    asyncio.run(receiver.run(stop))
    assert len(observed) == 1 and ws.closed
    assert receiver._timing_gap is None and not receiver.state.depth


def test_idle_receive_timeouts_do_not_inflate_previous_yield(caplog: Any, monkeypatch: Any) -> None:
    class Socket:
        def __init__(self) -> None:
            self.calls, self.now = 0, 10.0
        async def send(self, _raw: str) -> None:
            pass
        async def recv(self) -> str:
            self.calls += 1
            if self.calls in (2, 3):
                self.now += 0.2
                raise TimeoutError
            return json.dumps(delta(seq=3 if self.calls == 1 else 4,
                                    at=NOW if self.calls == 1 else NOW - 3.5))
    async def run() -> None:
        ws = Socket()
        monkeypatch.setattr(speeddesk_kalshi_ws, "time", SimpleNamespace(monotonic=lambda: ws.now))
        receiver = reader(lambda *_: None, [])
        with pytest.raises(MarketDataGap, match="orderbook_delta_network"):
            await receiver._session(ws, frozenset({TICKER}), threading.Event())
        receiver._flush_timing_gap(ws)
        gap = records(caplog)[-1]
        assert gap["previous_message"]["yield_resume_ms"] == 0
        assert ws.calls == 4 and ws.now == pytest.approx(10.4)
    caplog.set_level("INFO")
    asyncio.run(run())


def test_broken_diagnostic_log_sink_preserves_rejection_invalidation_and_close(monkeypatch: Any, caplog: Any) -> None:
    config, _ = settings()
    stop, statuses = threading.Event(), []
    ws = FakeSocket([ack(), snapshot(), delta(at=NOW - 3.5)], stop, statuses)
    receiver = KalshiMarketWS(config, tickers=lambda: frozenset({TICKER}),
        on_book=lambda _: pytest.fail("stale callback"), on_trade=lambda _: None,
        on_status=statuses.append, clock=lambda: NOW, ws_connect=lambda *_, **__: ws)
    original_info, attempts = speeddesk_kalshi_ws.log.info, []
    def broken(message: str, *args: Any, **kwargs: Any) -> None:
        if message.startswith("speeddesk_feed_kalshi_ws_timing"):
            attempts.append(message)
            raise RuntimeError("diagnostic log sink unavailable")
        original_info(message, *args, **kwargs)
    monkeypatch.setattr(speeddesk_kalshi_ws.log, "info", broken)
    asyncio.run(receiver.run(stop))
    assert ws.closed and receiver.connected is False and not receiver.state.depth
    assert receiver._timing_gap is None
    assert len(attempts) == 4  # Initial status and rejected frame, including each fallback.
    assert "orderbook_delta_network:age_s=3.500" in caplog.text


def test_inherited_weather_reader_has_distinct_evidence_identity(caplog: Any) -> None:
    async def run() -> None:
        ws = connection()
        base = reader(lambda *_: None, [])
        weather = WeatherWS(base._settings, tickers=lambda: frozenset({TICKER}),
            on_book=lambda _: None, on_trade=lambda _: None, on_status=lambda _: None,
            on_snapshot=lambda _: None, clock=lambda: NOW)
        for receiver in (base, weather):
            receiver._timing_session = 1
            receiver._timing_report(ws, event="status", call_mono=1, returned_mono=2,
                apply_mono=3, apply_wall=NOW, raw={}, previous=None)
        rows = records(caplog)
        assert [row["reader"]["kind"] for row in rows] == ["speeddesk", "derived_market_reader"]
        assert rows[0]["reader"]["instance"] != rows[1]["reader"]["instance"]
        assert all(row["reader"]["process"] == os.getpid() and row["session"] == 1 for row in rows)
    caplog.set_level("INFO")
    asyncio.run(run())


def test_failed_connection_does_not_reuse_previous_session_identity(caplog: Any) -> None:
    config, _ = settings()
    stop = threading.Event()
    class FailedConnection:
        async def __aenter__(self) -> Any:
            stop.set()
            raise ConnectionError("DO_NOT_LOG_REMOTE_ERROR_TEXT")
        async def __aexit__(self, *_: object) -> None:
            pass
    receiver = KalshiMarketWS(config, tickers=lambda: frozenset({TICKER}),
        on_book=lambda _: None, on_trade=lambda _: None, on_status=lambda _: None,
        clock=lambda: NOW, ws_connect=lambda *_, **__: FailedConnection())
    receiver._timing_session = 7
    asyncio.run(receiver.run(stop))
    assert "reader_session=None" in caplog.text
    assert "reader_session=7" not in caplog.text and receiver._timing_session == 7
    assert "reason=ConnectionError" in caplog.text and "DO_NOT_LOG" not in caplog.text

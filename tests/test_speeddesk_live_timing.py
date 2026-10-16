"""Historical factory cases are HISTORICAL ENTRY MECHANISM ONLY; they do not prove current
entry authority or profitability. Other cases retain the production factory.

Speed plan step 0: timing and clock measurements in the Kalshi companion's records (logging only)."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import FakeAccount, make_desk

import nightcrawler.speeddesk_live as live
from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_live import KalshiLiveDesk


class StampingAccount(FakeAccount):
    """Kalshi's create and cancel replies carry the venue's processing time in ms (ts_ms)."""

    def __init__(self, clock: FakeClock, venue_ahead_s: float = .25) -> None:
        super().__init__(clock)
        self.venue_ahead_s = venue_ahead_s

    def _stamp(self) -> int:
        return int((self.clock.now() + self.venue_ahead_s) * 1000)

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        return {**super().create_order(**kwargs), "ts_ms": self._stamp()}

    def cancel(self, order_id: str, *, ticker: str) -> dict[str, Any]:
        super().cancel(order_id, ticker=ticker)
        return {"order_id": order_id, "reduced_by": "5.00", "ts_ms": self._stamp()}


def stamping_desk(tmp_path: Path) -> tuple[KalshiLiveDesk, StampingAccount, FakeClock]:
    desk, _, clock = make_historical_desk(tmp_path)
    account = StampingAccount(clock)
    desk.client_factory = lambda: account
    return desk, account, clock


def logged(caplog: pytest.LogCaptureFixture, kind: str) -> list[dict[str, Any]]:
    """Parse the log lines the way the deploy-log scripts do (" <kind> " then the JSON payload)."""
    rows = []
    for record in caplog.records:
        message = record.getMessage()
        if message.startswith(kind + " {"):
            rows.append(json.loads(message.split(kind + " ", 1)[1]))
    return rows


def test_order_and_cancel_records_carry_kalshis_reply_time_and_the_clock_offset(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="nightcrawler.speeddesk")
    desk, account, clock = stamping_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        assert account.creates
        clock.advance(4)  # the Bitcoin feed goes stale: the resting bid is cancelled
        asyncio.run(desk.step())
        desk.checkpoint()
        accepted = [row for row in logged(caplog, "speeddesk_live_order") if row.get("order_id")]
        assert set(accepted[-1]["stages"]) == {"save_ms", "decision_to_send_ms", "send_to_ack_ms"}  # unchanged
        venue = accepted[-1]["venue"]
        assert venue["ts_ms"] == account._stamp() - 4000 and venue["rtt_ms"] == 0
        assert venue["offset_ms"] == pytest.approx(250, abs=1)  # the fake venue runs a quarter second ahead
        cancel = logged(caplog, "speeddesk_live_cancel")[-1]
        assert cancel["reduced_by"] == "5.00" and cancel["venue"]["offset_ms"] == pytest.approx(250, abs=1)
        assert cancel["timing"]["decision_to_ack_ms"] >= cancel["timing"]["send_to_ack_ms"] >= 0
    finally:
        desk.close()


def test_status_line_reports_step_phases_cancel_timings_and_clock_offsets(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="nightcrawler.speeddesk")
    desk, _, clock = stamping_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        clock.advance(4)
        asyncio.run(desk.step())
        clock.advance(61)
        asyncio.run(desk.step())
        desk.checkpoint()
        first, line = logged(caplog, "speeddesk_live_status")[-2:]  # the first step's line, then a minute later
        phases = {**first["phases"], **line["phases"]}
        assert {"observe", "cancel_unsafe", "startup", "reconcile", "lock", "decide", "heartbeat",
                "step"} <= set(phases)
        assert all(item["n"] >= 1 and item["max_ms"] >= item["p90_ms"] >= item["median_ms"] >= 0
                   for item in phases.values())
        assert line["loop"]["ms"]["cancel_decision_to_ack"]["n"] == 1
        for status in (first, line):  # one reply each: the order's, then the cancel's
            assert status["clock"]["kalshi"]["samples"] == 1 and status["clock"]["kalshi"]["fresh"] is True
            assert status["clock"]["kalshi"]["offset_ms"] == pytest.approx(250, abs=1)
        desk._heartbeat()  # the next minute had no reply from Kalshi: its last estimate is kept, not fresh
        clock.advance(61)
        desk._heartbeat()
        desk.checkpoint()
        later = logged(caplog, "speeddesk_live_status")[-1]
        assert later["clock"]["kalshi"]["fresh"] is False and later["clock"]["kalshi"]["samples"] == 0
        # Each line covers only what came after the previous one: here the end of the step that wrote it.
        assert set(later["phases"]) == {"heartbeat", "step"} and later["phases"]["step"]["n"] == 1
    finally:
        desk.close()


def test_run_measures_event_loop_lag_and_coinbase_clock_and_stops_both_probes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "IDLE_STEP_S", .01)
    desk, _, clock = make_desk(tmp_path)
    probes: list[float] = []

    def coinbase_clock() -> float:
        probes.append(clock.now())
        return clock.now() - .04  # Coinbase 40 ms behind the local clock

    desk.time_probe = coinbase_clock

    async def scenario() -> None:
        async def quiet_step() -> None:
            await asyncio.sleep(0)

        desk.step = quiet_step  # type: ignore[method-assign]
        stop = threading.Event()
        task = asyncio.create_task(desk.run(stop))
        await asyncio.sleep(.2)
        stop.set()
        await asyncio.wait_for(task, 5)
        assert all(task.done() for task in asyncio.all_tasks() if task is not asyncio.current_task())

    try:
        asyncio.run(scenario())
        assert probes == [clock.now()]  # once at start, then every CLOCK_PROBE_S
        assert desk.loop_stats.counts["event_loop_lag"] >= 5
        assert desk.clock_offsets.summary()["coinbase"]["offset_ms"] == pytest.approx(-40)
    finally:
        desk.close()


def test_a_failing_clock_probe_is_counted_and_never_stops_the_desk(tmp_path: Path) -> None:
    desk, _, _ = make_desk(tmp_path)

    def broken() -> float:
        raise TimeoutError("no route")

    desk.time_probe = broken

    async def scenario() -> None:
        task = asyncio.create_task(desk._clock_probe())
        await asyncio.sleep(.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(scenario())
        assert desk.loop_stats.counts == {"clock_probe_TimeoutError": 1}
    finally:
        desk.close()


def test_coinbase_time_reads_the_exchange_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Reply:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {"iso": "2026-10-13T18:53:43.810Z", "epoch": 1791917623.81}

    class Session:
        def get(self, url: str, **_kwargs: Any) -> Reply:
            calls.append(url)
            return Reply()

    import nightcrawler.speeddesk_feeds as feeds

    monkeypatch.setattr(feeds.requests, "Session", Session)
    monkeypatch.setattr(feeds, "_THREAD", threading.local())
    assert live.coinbase_time() == 1791917623.81 and live.coinbase_time() == 1791917623.81
    assert calls == [live.COINBASE_TIME] * 2

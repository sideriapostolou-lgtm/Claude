"""Durability and lifecycle regressions, with fake adapters and no network."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from nightcrawler.config import Settings
from nightcrawler.skipwatch_journal import iter_records, source_paths
from nightcrawler.weatherwatch import WeatherwatchRunner, report_markdown
from nightcrawler.weatherwatch_markets import MarketFeeds

START = 1_791_849_600.0


def make_runner(tmp_path, now=None, **kwargs):
    clock = now if now is not None else [START]
    return WeatherwatchRunner(Settings(data_dir=tmp_path), threading.Event(), clock=lambda: clock[0], **kwargs)


def observed(at, valid=None):
    return {"station": "KNYC", "source": "nws", "observation_id": str(valid or at - 1),
        "valid_at": valid or at - 1, "received_at": at, "quality": "accepted",
        "lower_f": 62, "upper_f": 62.2}


def add_market(runner):
    runner.emit("weather_market", {"venue": "kalshi", "market_id": "kalshi:TEST", "kind": "high",
        "station": "KNYC", "station_verified": True, "period_start": START, "period_end": START + 86400,
        "date": "2026-10-13", "strike_type": "between", "floor": 60, "cap": 61}, START)


def test_receipt_is_preserved_but_dispatch_is_not_backdated(tmp_path):
    now = [START + 10]
    runner = make_runner(tmp_path, now)
    runner.on_event("weather_observation", observed(START + 5), START + 5)
    runner.drain()
    runner.checkpoint()
    rows = list(iter_records(runner.directory))
    row = next(row for row in rows if row["kind"] == "weather_observation")
    assert row["observed_at"] == START + 10
    assert row["payload"]["received_at"] == row["payload"]["source_received_at"] == START + 5
    runner.close()


def test_restart_replays_sources_without_duplicate_reading_or_watch(tmp_path):
    now = [START]
    runner = make_runner(tmp_path, now)
    add_market(runner)
    now[0] += 10
    runner.on_event("weather_observation", observed(now[0]), now[0])
    runner.drain()
    before = runner.model.first_seen.copy()
    runner.checkpoint()
    runner.close()
    now[0] += 30
    restored = make_runner(tmp_path, now)
    assert restored.started_at == START
    assert restored.model.first_seen == before
    assert restored.model.books == {}
    restored.on_event("weather_observation", observed(START + 10), START + 10)
    restored.drain()
    assert restored.model.first_seen == before
    assert len(restored.model.locks) == 1
    assert restored.model.restarts == 1
    restored.close()


def test_invalid_checkpoint_hash_cannot_restart_trial(tmp_path):
    runner = make_runner(tmp_path)
    path = runner.path
    runner.close()
    saved = json.loads(path.read_text())
    saved["hash"] = "not the source hash"
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="does not match"):
        make_runner(tmp_path)


def test_missing_journal_cannot_reset_trial(tmp_path):
    runner = make_runner(tmp_path)
    runner.close()
    for path in source_paths(runner.directory):
        path.unlink()
    with pytest.raises(ValueError, match="journal missing"):
        make_runner(tmp_path)


def test_single_writer_lock(tmp_path):
    runner = make_runner(tmp_path)
    with pytest.raises(RuntimeError, match="already owned"):
        make_runner(tmp_path)
    runner.close()


def test_storage_limit_pauses_and_keeps_evidence(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    paths = source_paths(runner.directory)
    monkeypatch.setattr(runner, "_storage_ok", lambda: False)
    assert not runner.emit("weather_observation", observed(START + 1), START + 1)
    assert runner.paused
    assert all(path.exists() for path in paths)
    assert list(iter_records(runner.directory))[-1]["kind"] == "weather_gap"
    assert json.loads(runner.path.read_text())["panel"]["status"] == "PAUSED"
    assert not runner.emit("weather_observation", observed(START + 2), START + 2)
    runner.close()


def test_free_disk_reserve_is_enforced(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    monkeypatch.setattr("nightcrawler.weatherwatch.shutil.disk_usage", lambda _: SimpleNamespace(free=127 * 1024**2))
    assert not runner._storage_ok()
    runner.close()


def test_clock_regression_pauses_without_invalidating_hash_order(tmp_path):
    now = [START]
    runner = make_runner(tmp_path, now)
    now[0] -= 1
    assert not runner.emit("weather_tick", {}, now[0])
    assert runner.paused
    rows = list(iter_records(runner.directory))
    assert [row["observed_at"] for row in rows] == sorted(row["observed_at"] for row in rows)
    runner.close()


def test_capacity_rejection_is_durable_and_replayed(tmp_path):
    now = [START]
    runner = make_runner(tmp_path, now)
    add_market(runner)
    runner.markets = SimpleNamespace(watch=lambda request: False)
    now[0] += 10
    runner.on_event("weather_observation", observed(now[0]), now[0])
    runner.drain()
    assert runner.capacity_skips == 1
    runner.checkpoint()
    runner.close()
    now[0] += 10
    restored = make_runner(tmp_path, now)
    assert restored.capacity_skips == 1
    restored.close()


def test_reports_keep_unknown_earnings_and_retention_never_deletes_source(tmp_path):
    runner = make_runner(tmp_path)
    runner.emit("weather_tick", {}, START)
    directory = runner.directory / "daily"
    directory.mkdir()
    stale = directory / "2020-01-01.json"
    stale.write_text("{}")
    runner.reports()
    assert not stale.exists()
    assert source_paths(runner.directory)
    report = next(directory.glob("*.md")).read_text()
    assert "Achievable cents/day: unknown" in report
    assert "Do not add them" in report
    assert "No orders or actual fills" in report
    assert runner.panel()["real_orders_available"] is False
    runner.close()


def test_daily_empty_disagreements_does_not_claim_agreement():
    text = report_markdown({"day": "2026-10-13", "cli_disagreements": []})
    assert "does not establish coverage or agreement" in text


def test_rejected_restart_keeps_settlement_audit_without_recapturing(tmp_path):
    now = [START]
    runner = make_runner(tmp_path, now)
    add_market(runner)
    now[0] += 10
    runner.emit("weather_observation", observed(now[0]), now[0])
    runner.emit("weather_watch_rejected", {"market_id": "kalshi:TEST", "reason": "capacity"}, now[0])
    feeds = MarketFeeds(lambda *args: None, runner.stop, settings=runner.settings, clock=lambda: now[0])
    feeds.restore(runner.model.markets, runner.restored_watches())
    assert "kalshi:TEST" not in feeds.watches
    assert "kalshi:TEST" in feeds._pending_settlements
    runner.close()


def test_callback_overflow_is_a_visible_gap_not_silent_data_loss(tmp_path):
    runner = make_runner(tmp_path)
    for number in range(257):
        runner.on_event("weather_source_status", {"source": "nws", "number": number}, START)
    assert len(runner.pending) == 256
    runner.drain()
    assert runner.paused and "queue capacity" in runner.problem
    assert not runner.pending
    assert list(iter_records(runner.directory))[-1]["kind"] == "weather_gap"
    runner.close()


def test_reentrant_market_callback_never_backdates_outer_actions(tmp_path):
    now = [START]
    runner = make_runner(tmp_path, now)
    add_market(runner)

    def watch(request):
        now[0] += .1
        runner.on_event("weather_gap", {"reason": "capacity", "market_id": request["market_id"]}, now[0])
        return False

    runner.markets = SimpleNamespace(watch=watch)
    now[0] += 10
    runner.on_event("weather_observation", observed(now[0]), now[0])
    runner.drain()
    runner.checkpoint()
    assert not runner.paused
    rows = list(iter_records(runner.directory))
    assert [row["observed_at"] for row in rows] == sorted(row["observed_at"] for row in rows)
    assert runner.capacity_skips == 1
    runner.close()


def test_concurrent_callbacks_only_journal_on_serial_dispatch(tmp_path):
    now = [START]
    runner = make_runner(tmp_path, now)
    threads = [threading.Thread(target=runner.on_event, args=("weather_source_status",
        {"source": "nws", "status": "ok", "sample": sample}, START + sample)) for sample in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(runner.pending) == 32
    assert len(list(iter_records(runner.directory))) == 1
    now[0] += 40
    runner.drain()
    runner.checkpoint()
    rows = list(iter_records(runner.directory))
    assert len(rows) == 33
    assert all(row["observed_at"] == START + 40 for row in rows[1:])
    runner.close()


def test_fake_feeds_run_and_shutdown_flushes(tmp_path):
    stop = threading.Event()
    cancelled = []

    class Markets:
        def __init__(self, emit, stop, **kwargs):
            self.emit = emit
            self.stations = []

        def restore(self, markets, watches):
            assert markets == watches == {}

        async def run(self):
            try:
                while True:
                    await asyncio.sleep(0)
            finally:
                cancelled.append("markets")

    class Observations:
        def __init__(self, emit, stop, stations, **kwargs):
            assert stations() == []

        async def run(self):
            stop.set()
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append("observations")

    runner = WeatherwatchRunner(Settings(data_dir=tmp_path), stop, clock=lambda: START,
        market_factory=Markets, observation_factory=Observations)
    asyncio.run(runner.run())
    assert sorted(cancelled) == ["markets", "observations"]
    rows = list(iter_records(runner.directory))
    assert rows[-1]["kind"] == "weather_gap"
    assert rows[-1]["payload"]["reason"] == "shutdown"
    runner.close()


def test_observer_files_do_not_import_order_or_portfolio_clients():
    # This protects the capability boundary in addition to fake-adapter tests.
    directory = Path(__file__).parents[1] / "src" / "nightcrawler"
    for path in directory.glob("weatherwatch*.py"):
        source = path.read_text()
        assert "speeddesk_kalshi_client" not in source
        assert "speeddesk_live" not in source
        assert "/portfolio/" not in source
        assert "requests.post(" not in source

"""Durability and public-only runtime checks; all external inputs are fakes."""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from nightcrawler.config import Settings
from nightcrawler.skipwatch import SkipwatchRunner, iter_records


def runner(tmp_path, now=None, **kwargs):
    clock = now if now is not None else [1000.0]
    return SkipwatchRunner(Settings(data_dir=tmp_path), threading.Event(), clock=lambda: clock[0], **kwargs)


def fill(identity="fill-1", **changes):
    return {"fill_id": identity, "market_id": "m", "token_id": "u", "side": "up", "action": "buy",
            "price": .4, "size": 3, "exchange_at": 999} | changes


def test_recovery_preserves_fill_dedup_and_poll_watermark_through_repeated_restarts(tmp_path):
    first = runner(tmp_path)
    first.emit("wallet_fill", fill(), 1000)
    first.emit("health", {"source": "wallet", "status": "connected", "wallet_watermark": 999}, 1000)
    first.checkpoint()
    first.close()
    for _ in range(2):
        resumed = runner(tmp_path, [1001])
        try:
            assert resumed.wallet_watermark == 999
            assert not resumed.emit("wallet_fill", fill(), 1001)
            assert resumed.model.inventory["m"]["up"] == 3
            assert not resumed.model.coverage(1001)["wallet"]
        finally:
            resumed.close()
    assert sum(row["kind"] == "wallet_fill" for row in iter_records(tmp_path / "skipwatch")) == 1


def test_runtime_owns_single_writer_and_releases_lock_even_after_flush_error(tmp_path, monkeypatch):
    first = runner(tmp_path)
    with pytest.raises(RuntimeError, match="already owned"):
        runner(tmp_path)
    monkeypatch.setattr(first, "flush", lambda: (_ for _ in ()).throw(OSError("fake full disk")))
    with pytest.raises(OSError):
        first.close()
    second = runner(tmp_path)
    second.close()


def test_storage_pause_records_gap_keeps_evidence_and_never_deletes(tmp_path, monkeypatch):
    watch = runner(tmp_path)
    before = list(iter_records(watch.directory))
    monkeypatch.setattr(watch, "_storage_ok", lambda: False)
    try:
        assert not watch.emit("wallet_fill", fill(), 1000)
        assert watch.paused and "storage" in watch.problem
        assert not watch.panel()["real_orders_available"]
        rows = list(iter_records(watch.directory))
        assert rows[:len(before)] == before
        assert rows[-1]["kind"] == "gap" and rows[-1]["payload"]["source"] == "storage"
        assert not any(watch.panel()["coverage"].values())
        assert watch.panel()["free_storage_bytes"] > watch.panel()["reserved_free_bytes"]
    finally:
        watch.close()


def test_backward_dispatch_clock_pauses_without_rewriting_evidence(tmp_path):
    watch = runner(tmp_path)
    try:
        assert not watch.emit("health", {"source": "wallet", "status": "connected"}, 999)
        assert watch.paused and "clock" in watch.problem
        assert all(row["observed_at"] == 1000 for row in iter_records(watch.directory))
    finally:
        watch.close()


def test_callback_source_receipt_is_preserved_while_dispatch_is_causal_boundary(tmp_path):
    watch = runner(tmp_path)
    try:
        watch.on_event("bitcoin_tick", {"price": 60_000, "exchange_at": 998}, 999)
        watch.on_event("bitcoin_tick", {"price": 60_001, "exchange_at": 997}, 998.5)
        watch.checkpoint()
        rows = list(iter_records(watch.directory))[-2:]
        assert not watch.paused
        assert [row["observed_at"] for row in rows] == [1000, 1000]
        assert [row["payload"]["source_received_at"] for row in rows] == [999, 998.5]
        assert watch.model._btc_before(999) is None
    finally:
        watch.close()


def test_missing_wallet_side_can_use_only_verified_matching_token_metadata(tmp_path):
    watch = runner(tmp_path)
    try:
        watch.emit("market", {"market_id": "m", "start": 900, "end": 1200,
                              "up_token": "u", "down_token": "d"}, 1000)
        watch.on_event("wallet_fill", fill(side="unknown"), 1000)
        assert watch.model.inventory["m"]["up"] == 3
        watch.on_event("wallet_fill", fill("fill-2", side="unknown", market_id="different"), 1000)
        assert not watch.model.inventory.get("different")
    finally:
        watch.close()


def test_partial_tail_is_quarantined_and_visible_on_recovery(tmp_path):
    watch = runner(tmp_path)
    path = next(watch.directory.glob("*.jsonl"))
    watch.close()
    with path.open("ab") as stream:
        stream.write(b'{"unfinished":')
    restored = runner(tmp_path, [1001])
    try:
        records = list(iter_records(restored.directory))
        assert records[-1]["payload"]["partial_tail_quarantined"] is True
        assert next(restored.directory.glob("*.partial.bin")).read_bytes() == b'{"unfinished":'
    finally:
        restored.close()


def test_fake_background_workers_shutdown_and_publish_only_public_status(tmp_path):
    seen = []

    class Feeds:
        def __init__(self, settings, **kwargs):
            self.callback = kwargs["on_event"]
            seen.append(kwargs["wallet_since"])

        async def run(self, stop):
            self.callback("health", {"source": "wallet", "status": "connected", "wallet_watermark": 1000}, 1000)
            await asyncio.sleep(.02)
            stop.set()
            await asyncio.sleep(10)

    class Probes:
        def __init__(self, **kwargs):
            pass

        def poll(self):
            return [{"kind": "public_probe", "at": 1000}]

        def state(self):
            return {"public": True}

    watch = runner(tmp_path, feed_factory=Feeds, probes_factory=Probes,
                   fit_due=lambda *args: {"status": "collecting_train", "live_promotion": False})
    try:
        asyncio.run(watch.run())
        state = json.loads(watch.path.read_text())
        assert seen == [None]
        assert state["probes"] == {"public": True}
        assert state["fit"]["live_promotion"] is False
        assert state["seq"] == list(iter_records(watch.directory))[-1]["seq"]
        assert any(row["kind"] == "gap" and row["payload"]["reason"] == "shutdown"
                   for row in iter_records(watch.directory))
    finally:
        watch.close()


def test_research_io_failure_backs_off_without_repeated_archive_scans(tmp_path, monkeypatch):
    calls, delays = [], []

    def unavailable(*args):
        calls.append(True)
        return {"status": "research_blocked", "reason": "OSError", "retry_after_s": 3600}

    watch = runner(tmp_path, fit_due=unavailable)

    async def wait(delay):
        delays.append(delay)
        watch.stop.set()

    monkeypatch.setattr(asyncio, "sleep", wait)
    try:
        asyncio.run(watch._fit())
        assert calls == [True] and delays == [3600]
    finally:
        watch.close()


def test_canceled_fit_subprocess_is_terminated_before_return(tmp_path, monkeypatch):
    processes = []

    class Process:
        returncode = None
        terminated = False

        async def communicate(self):
            await asyncio.sleep(10)

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            return self.returncode

    async def spawn(*args, **kwargs):
        assert args[1:3] == ("-m", "nightcrawler.skipwatch_fit")
        process = Process()
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    watch = runner(tmp_path)

    async def check():
        task = asyncio.create_task(watch._fit_subprocess())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].terminated

    try:
        asyncio.run(check())
    finally:
        watch.close()

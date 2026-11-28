"""Durable, bounded public observation worker, isolated from money execution."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import math
import os
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from .config import Settings
from .skipwatch_execution import PROTOCOL_HASH, PredictionRecorder
from .skipwatch_journal import (
    BATCH_BYTES,
    GENESIS,
    ObservationJournal,
    iter_records,
    record_hash,
    source_paths,
)
from .skipwatch_model import SkipwatchModel

log = logging.getLogger("nightcrawler.skipwatch")
__all__ = ["SkipwatchRunner", "iter_records", "record_hash", "run_skipwatch"]


class SkipwatchRunner:
    def __init__(self, settings: Settings, stop: threading.Event, *, clock: Callable[[], float] = time.time,
                 feed_factory: Callable[..., Any] | None = None, probes_factory: Callable[..., Any] | None = None,
                 fit_due: Callable[..., dict[str, Any]] | None = None) -> None:
        self.settings, self.stop, self.clock = settings, stop, clock
        self.directory = settings.data_dir / "skipwatch"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.lock = (self.directory / "observer.lock").open("a", encoding="utf-8")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Watcher journal is already owned by another process") from None
        self.seq, self.previous_hash = 0, GENESIS
        self.started_at = self.clock()
        self.receipt_clock_id = uuid.uuid4().hex
        self.storage_bytes = 0
        self.journal: ObservationJournal | None = None
        self.max_bytes = int(settings.skipwatch_max_storage_mb * 1024 * 1024)
        self.paused = False
        self.problem: str | None = None
        self.last_checkpoint = -math.inf
        self.last_flush = -math.inf
        self.last_heartbeat = -math.inf
        self.last_observed_at: float | None = None
        self.fit_status: dict[str, Any] = {"status": "collecting prospective evidence"}
        self.probes: Any = None
        self.feed_factory, self.probes_factory, self.fit_due = feed_factory, probes_factory, fit_due
        try:
            self._restore()
        except BaseException:
            if self.journal is not None:
                self.journal.close()
            self.lock.close()
            raise

    def _restore(self) -> None:
        saved: dict[str, Any] = {}
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                saved = {}
        files = source_paths(self.directory)
        if self.path.exists() and not files:
            raise ValueError("Watcher source journal is missing beside saved evidence")
        self.journal = ObservationJournal(self.directory)
        self.storage_bytes = self.journal.storage_bytes
        checkpoint_seq = int(saved.get("seq", 0))
        checkpoint_matched = checkpoint_seq == 0
        self.model = SkipwatchModel(self.started_at, poll_s=self.settings.skipwatch_poll_s)
        self.predictions = PredictionRecorder(self.started_at)
        for record in iter_records(self.directory):
            if self.seq == 0:
                self.started_at = float(record["session_started_at"])
                self.model = SkipwatchModel(self.started_at, poll_s=self.settings.skipwatch_poll_s)
                self.predictions = PredictionRecorder(self.started_at)
            self.seq, self.previous_hash = int(record["seq"]), str(record["hash"])
            self.journal.recover_record(record)
            if self.seq == checkpoint_seq:
                if self.previous_hash != saved.get("hash"):
                    raise ValueError("Watcher checkpoint hash does not match the source journal")
                checkpoint_matched = True
            self.last_observed_at = float(record["observed_at"])
            self.model.ingest(record["kind"], record["payload"], self.last_observed_at)
            self.predictions.restore(record["kind"], record["payload"])
        if not checkpoint_matched:
            raise ValueError("Watcher source journal is missing checkpointed records")
        self.wallet_watermark = self.model.wallet_watermark
        self.saved_probes = saved.get("probes", {})
        self.fit_status = saved.get("fit", self.fit_status)
        if self.seq:
            self.emit("gap", {"source": "runtime", "reason": "restart",
                              "from": self.last_observed_at, "to": self.clock(),
                              "partial_tail_quarantined": self.journal.recovered_tail}, self.clock())
        else:
            self.emit("session_started", {"public_only": True, "real_orders_available": False,
                                          "cancellations": "unobservable"}, self.clock())
        self.checkpoint()

    def _storage_ok(self) -> bool:
        return (self.storage_bytes + BATCH_BYTES * 2 < self.max_bytes
                and shutil.disk_usage(self.directory).free >= self.settings.skipwatch_min_free_mb * 1024 * 1024)

    def emit(self, kind: str, payload: dict[str, Any], observed_at: float, *, critical: bool = False) -> bool:
        if self.paused and not critical:
            return False
        if kind == "wallet_fill" and str(payload.get("fill_id")) in self.model.seen_fills:
            return False
        if not critical and not self._storage_ok():
            self.paused, self.problem = True, "Observation paused: storage limit or free-space reserve reached"
            self.emit("gap", {"source": "storage", "reason": self.problem, "from": observed_at,
                              "to": None}, observed_at, critical=True)
            self.checkpoint()
            return False
        at = float(payload.get("exchange_at", payload.get("at", observed_at)))
        if not math.isfinite(at) or not math.isfinite(observed_at):
            raise ValueError("Watcher timestamp is nonfinite")
        if self.last_observed_at is not None and observed_at < self.last_observed_at:
            self.paused, self.problem = True, "Observation paused: receipt clock moved backwards"
            self.model.gaps += 1
            self.model.health.clear()
            self.model.bitcoin.ingest("gap", {"source": "runtime"}, observed_at)
            log.error("skipwatch_clock_gap")
            self.checkpoint()
            return False
        data = dict(payload)
        if kind == "book_delta":
            data.pop("bids", None)
            data.pop("asks", None)
        elif kind == "book_deltas":
            data["updates"] = [{key: value for key, value in update.items() if key not in {"bids", "asks"}}
                               for update in data["updates"]]
        assert self.journal is not None
        self.journal.append(kind, data, at, observed_at, self.started_at)
        self.seq, self.previous_hash = self.journal.seq, self.journal.previous_hash
        self.storage_bytes = self.journal.storage_bytes
        self.last_observed_at = observed_at
        self.model.ingest(kind, data, observed_at)
        if kind == "opportunity":
            batches = self.predictions.observe(data, seq=self.seq, issued_at=self.clock(),
                                               monotonic_ns=time.monotonic_ns(), clock_id=self.receipt_clock_id)
            for batch in batches:
                issued = self.clock()
                batch.update(at=issued, observed_at=issued, issued_monotonic_ns=time.monotonic_ns())
                self.emit("execution_prediction_batch", batch, issued)
        if kind in {"window_summary", "gap", "skipwatch_us_5m_listing", "skipwatch_binance_availability"}:
            log.info("skipwatch_%s %s", kind, json.dumps(data, allow_nan=False, separators=(",", ":")))
        return True

    def on_event(self, kind: str, payload: dict[str, Any], received_at: float) -> None:
        if not self.paused:
            # A decoder can emit health before the rest of the same wire frame.
            # Preserve the source receipt, but knowledge becomes available to
            # this model only when this callback actually runs.
            data = {**payload, "source_received_at": received_at}
            if kind == "wallet_fill" and data.get("side") not in {"up", "down"}:
                mapping = self.model.tokens.get(str(data.get("token_id", "")))
                if mapping and mapping[0] == data.get("market_id"):
                    data["side"] = mapping[1]
                    data["side_source"] = "verified Gamma token mapping at observation time"
            self.emit(kind, data, self.clock())

    def panel(self) -> dict[str, Any]:
        now = self.clock()
        coverage = self.model.coverage(now)
        current = [market for market in self.model.markets.values() if market["start"] <= now < market["end"]]
        if current:
            coverage["book"] = any(self.model.coverage(now, str(market.get("up_token", "")))["book"]
                                   for market in current)
        if self.paused:
            coverage = dict.fromkeys(("bitcoin", "book", "wallet", "trades"), False)
        bitcoin_sources = self.model.bitcoin_summary(now)
        if self.paused:
            for source in bitcoin_sources["venues"].values():
                source.update(fresh=False, connected=False)
        return {"enabled": self.settings.skipwatch_enabled, "as_of": now, "started_at": self.started_at,
                "status": "PAUSED" if self.paused else "OBSERVING PUBLIC DATA", "problem": self.problem,
                "windows_observed": len(self.model.observed_windows), "wallet_fills": len(self.model.seen_fills),
                "matched_inferred": self.model.match_counts["inferred"],
                "ambiguous": self.model.match_counts["ambiguous"], "unmatched": self.model.match_counts["unmatched"],
                "coverage": coverage, "storage_bytes": self.storage_bytes, "max_storage_bytes": self.max_bytes,
                "free_storage_bytes": shutil.disk_usage(self.directory).free,
                "reserved_free_bytes": self.settings.skipwatch_min_free_mb * 1024 * 1024,
                "gaps": self.model.gaps, "last_wallet_at": self.model.last_wallet_at,
                "last_btc_at": self.model.btc[-1][1] if self.model.btc else None,
                "latest_window": current[0].get("slug") if current else None,
                "fit": self.fit_status, "probes": self.probes.state() if self.probes else self.saved_probes,
                "bitcoin_sources": bitcoin_sources,
                "execution_target": {"protocol_hash": PROTOCOL_HASH, "recall_target": .70,
                                     "time_tolerance_s": 5, "price_tolerance_usd": .02,
                                     "shadow_started_at": self.predictions.started_at,
                                     "qualified_epoch_started_at": None, "strict_recall": None,
                                     "strict_gate_passed": False, "status": "execution_timing_unqualified"},
                "cancellations_visible": False, "real_orders_available": False,
                "confidence_note": "Public fills and possible print matches; exact orders and identity are unknown"}

    def flush(self) -> None:
        assert self.journal is not None
        self.journal.flush(self.started_at)
        self.seq, self.previous_hash = self.journal.seq, self.journal.previous_hash
        self.storage_bytes = self.journal.storage_bytes
        self.last_flush = self.clock()

    def checkpoint(self) -> None:
        self.flush()
        state = {"version": 1, "seq": self.seq, "hash": self.previous_hash, "started_at": self.started_at,
                 "last_observed_at": self.last_observed_at, "panel": self.panel(),
                 "probes": self.probes.state() if self.probes else self.saved_probes, "fit": self.fit_status}
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        self.last_checkpoint = self.clock()

    async def _probes(self) -> None:
        while not self.stop.is_set():
            try:
                for event in await asyncio.to_thread(self.probes.poll):
                    payload = dict(event)
                    kind = str(payload.pop("kind"))
                    self.emit(kind, payload, self.clock())
                self.checkpoint()
            except Exception as exc:  # noqa: BLE001 — public probe faults do not stop evidence feeds.
                log.warning("skipwatch_probe_error error=%s", type(exc).__name__)
            await asyncio.sleep(30)

    async def _fit(self) -> None:
        while not self.stop.is_set():
            try:
                if self.fit_due is not None:
                    self.fit_status = await asyncio.to_thread(self.fit_due, self.directory, self.clock(), self.started_at)
                elif self.clock() - self.started_at < 48 * 3600:
                    from .skipwatch_fit import run_due
                    # Before the frozen cutoff this only writes a tiny status
                    # artifact; it does not scan the observation tape.
                    self.fit_status = run_due(self.directory, self.clock(), self.started_at)
                else:
                    self.fit_status = await self._fit_subprocess()
            except Exception as exc:  # noqa: BLE001 — a research fault must not affect money or observation.
                self.fit_status = {"status": "research paused", "reason": type(exc).__name__}
                log.warning("skipwatch_fit_error error=%s", type(exc).__name__)
            retry = self.fit_status.get("retry_after_s", 60)
            delay = (min(3600.0, max(60.0, float(retry)))
                     if isinstance(retry, (int, float)) and not isinstance(retry, bool) and math.isfinite(retry)
                     else 60.0)
            await asyncio.sleep(delay)

    async def _fit_subprocess(self) -> dict[str, Any]:
        # Freeze only after every already-observed pre-cutoff row is durable.
        self.flush()
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "nightcrawler.skipwatch_fit", "--data-dir", str(self.directory),
            "--now", str(self.clock()), "--session-started-at", str(self.started_at),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=128 * 1024)
        try:
            output, _ = await process.communicate()
            if process.returncode != 0 or len(output) > 128 * 1024:
                raise ValueError("Research worker did not return a bounded result")
            result = json.loads(output)
            if not isinstance(result, dict):
                raise TypeError("Invalid research worker result")
            return result
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except TimeoutError:
                    process.kill()
                    await process.wait()

    async def run(self) -> None:
        if self.feed_factory is None:
            from .skipwatch_feeds import SkipwatchFeeds
            self.feed_factory = SkipwatchFeeds
        if self.probes_factory is None:
            from .skipwatch_alerts import PublicProbes
            self.probes_factory = PublicProbes
        self.probes = self.probes_factory(clock=self.clock, initial=self.saved_probes,
                                          region=os.getenv("RAILWAY_REPLICA_REGION"), check_availability=True)
        watermark = self.wallet_watermark
        feeds = self.feed_factory(self.settings, on_event=self.on_event, clock=self.clock, wallet_since=watermark,
                                  receipt_clock_id=self.receipt_clock_id)
        tasks = [asyncio.create_task(feeds.run(self.stop)), asyncio.create_task(self._probes()),
                 asyncio.create_task(self._fit())]
        try:
            while not self.stop.is_set():
                for task in tasks:
                    if task.done():
                        task.result()
                        raise RuntimeError("Watcher background task exited")
                now = self.clock()
                if not self.paused:
                    for event in self.model.due(now):
                        self.emit(event.kind, event.payload, self.clock())
                if now - self.last_heartbeat >= 60:
                    log.info("skipwatch_status %s", json.dumps(self.panel(), allow_nan=False, separators=(",", ":")))
                    self.last_heartbeat = now
                if now - self.last_flush >= 1:
                    self.flush()
                if now - self.last_checkpoint >= 5:
                    self.checkpoint()
                await asyncio.sleep(.1)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.emit("gap", {"source": "runtime", "reason": "shutdown", "from": self.clock(), "to": None},
                      self.clock())
            self.checkpoint()

    def close(self) -> None:
        try:
            if self.journal is not None:
                try:
                    self.flush()
                finally:
                    self.journal.close()
        finally:
            self.lock.close()


def run_skipwatch(settings: Settings, stop_event: threading.Event) -> None:
    runner = None
    for attempt in range(30):
        if stop_event.is_set():
            return
        try:
            runner = SkipwatchRunner(settings, stop_event)
            break
        except RuntimeError as exc:
            if "already owned" not in str(exc) or attempt == 29:
                log.error("skipwatch_halted error=%s", type(exc).__name__)
                return
            stop_event.wait(1)
        except Exception as exc:  # noqa: BLE001 — observer startup faults never reach the trading thread.
            log.error("skipwatch_halted error=%s", type(exc).__name__)
            return
    if runner is None:
        return
    try:
        asyncio.run(runner.run())
    except Exception as exc:  # noqa: BLE001 — never log arbitrary request/response exception strings.
        log.error("skipwatch_halted error=%s", type(exc).__name__)
        runner.paused, runner.problem = True, "Public watcher halted; inspect its source journal"
        try:
            runner.checkpoint()
        except Exception:  # noqa: BLE001 — an unavailable disk cannot supply an honest new report.
            log.error("skipwatch_state_unavailable")
    finally:
        runner.close()

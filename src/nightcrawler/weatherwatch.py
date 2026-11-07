"""Durable, bounded weather measurements with no portfolio or order capability."""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import math
import os
import shutil
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .skipwatch_journal import (
    BATCH_BYTES,
    ObservationJournal,
    iter_records,
    source_paths,
)
from .weatherwatch_model import WeatherwatchModel

log = logging.getLogger("nightcrawler.weatherwatch")
INPUTS = frozenset({"weather_market", "weather_observation", "weather_book", "weather_trade",
    "weather_settlement", "weather_cli", "weather_source_status", "weather_venue_status",
    "weather_gap", "weather_watch_rejected"})


def report_markdown(report: dict[str, Any]) -> str:
    """A daily artifact for a later verified WORKLOG entry, never a GitHub write."""
    lines = [f"# Weather stopwatch — {report.get('day', 'unknown')}", "",
        "MEASURE ONLY. No orders or actual fills. Achievable cents/day: unknown.", "",
        (f"Candidate crossings: {report.get('candidate_locks', 0)}; "
        f"confirmed observation proxies: {report.get('confirmed_observation_proxies', 0)}; "
        f"recorded seconds: {report.get('recorded_seconds', 0):.1f}; "
        f"gaps: {report.get('gaps', 0)}. Coverage remains partial."), "",
        "Two readings are not proof that a different settlement source agrees.", "",
        "| Source | Readings | Startup/backfill excluded | First-receipt delay median / p95 (seconds) |",
        "| --- | ---: | ---: | --- |"]
    for source, row in report.get("sources", {}).items():
        lines.append(f"| {source} | {row.get('readings', 0)} | {row.get('bootstrap_readings', 0)} | "
                     f"{row.get('median')} / {row.get('p95')} |")
    lines.extend(["", ("The 97¢ and 98¢ scenarios are alternatives: one contract per market, "
        "conditional on quote persistence. Do not add them or treat displayed depth as fills."), "",
        ("| Venue | Limit | Displayed contracts | Conditional entries | Settled | Hold P&L | "
        "99¢ exit observations | Exit P&L |"), "| --- | --- | ---: | ---: | ---: | --- | ---: | --- |"])
    for venue, scenarios in report.get("conditional_scenarios", {}).items():
        for limit, row in scenarios.items():
            lines.append(f"| {venue} | {limit} | {row.get('displayed_contracts_at_assessment', 0)} | "
                f"{row.get('conditional_entries', 0)} | {row.get('settled_entries', 0)} | "
                f"{row.get('conditional_hold_pnl_usd')} | {row.get('exit_observations', 0)} | "
                f"{row.get('conditional_exit_pnl_usd')} |")
    lines.extend(["", ("P&L columns are conditional USD after modeled taker fees, not earnings. "
        "None means unknown or pending. Resting-maker fills are not inferred."), "",
        ("CLI comparisons and actual venue settlements are separate. An empty disagreement "
        "list does not establish coverage or agreement."), "",
        f"CLI reports: {report.get('cli_reports', 0)}; comparisons: {report.get('cli_comparisons', 0)}.",
        f"CLI disagreements: {json.dumps(report.get('cli_disagreements', []), allow_nan=False)}",
        f"Venue disagreements: {json.dumps(report.get('settlement_disagreements', []), allow_nan=False)}", ""])
    return "\n".join(lines)


def _atomic(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class WeatherwatchRunner:
    def __init__(self, settings: Settings, stop: threading.Event, *,
                 clock: Callable[[], float] = time.time,
                 market_factory: Callable[..., Any] | None = None,
                 observation_factory: Callable[..., Any] | None = None) -> None:
        self.settings, self.stop, self.clock = settings, stop, clock
        self.market_factory, self.observation_factory = market_factory, observation_factory
        self.directory = settings.data_dir / "weatherwatch"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.lock = (self.directory / "observer.lock").open("a", encoding="utf-8")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Weather journal is already owned by another process") from None
        self.mutex = threading.RLock()
        self.pending: deque[tuple[str, dict[str, Any], int]] = deque()
        self.pending_bytes = 0
        self.queue_overflow = False
        self.started_at = self.clock()
        self.receipt_clock_id = uuid.uuid4().hex
        self.max_bytes = settings.weatherwatch_max_storage_mb * 1024 * 1024
        self.journal: ObservationJournal | None = None
        self.markets: Any = None
        self.paused = False
        self.problem: str | None = None
        self.capacity_skips = 0
        self.last_observed_at: float | None = None
        self.last_tick = self.last_flush = self.last_checkpoint = self.last_report = -math.inf
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
            # Invalid evidence is not permission to restart the trial silently.
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or saved.get("version") != 1:
                raise ValueError("Invalid weather checkpoint")
            if not source_paths(self.directory):
                raise ValueError("Weather source journal missing beside saved state")
        self.journal = ObservationJournal(self.directory)
        checkpoint_seq = int(saved.get("seq", 0))
        matched = checkpoint_seq == 0
        self.model = WeatherwatchModel(self.started_at)
        for record in iter_records(self.directory):
            if self.journal.seq == 0:
                self.started_at = float(record["session_started_at"])
                self.model = WeatherwatchModel(self.started_at)
            self.journal.recover_record(record)
            if record["seq"] == checkpoint_seq:
                if record["hash"] != saved.get("hash"):
                    raise ValueError("Weather checkpoint does not match source evidence")
                matched = True
            observed = float(record["observed_at"])
            self.last_observed_at = observed
            if record["kind"] in INPUTS:
                self.model.ingest(record["kind"], record["payload"], observed)
            elif record["kind"] == "weather_tick":
                self.model.tick(observed)
            if record["kind"] == "weather_watch_rejected":
                self.capacity_skips += 1
        if not matched:
            raise ValueError("Weather journal missing checkpointed records")
        now = self.clock()
        if self.last_observed_at is not None and now < self.last_observed_at:
            self._pause("Receipt clock moved backwards; recording paused", self.last_observed_at)
        elif self.journal.seq:
            self.emit("weather_gap", {"source": "runtime", "reason": "restart",
                "from": self.last_observed_at, "to": now,
                "partial_tail_quarantined": self.journal.recovered_tail}, now)
        else:
            self.emit("weather_session_started", {"read_only": True, "real_orders_available": False}, now)
        self.checkpoint()

    def _storage_ok(self) -> bool:
        assert self.journal is not None
        auxiliary = sum(path.stat().st_size for path in self.directory.rglob("*")
                        if path.is_file() and path.suffix in {".json", ".md", ".tmp"})
        return (self.journal.storage_bytes + self.journal.pending_bytes + auxiliary + 8 * BATCH_BYTES < self.max_bytes
                and shutil.disk_usage(self.directory).free >
                self.settings.weatherwatch_min_free_mb * 1024 * 1024 + 8 * BATCH_BYTES)

    def _append(self, kind: str, payload: dict[str, Any], observed: float) -> None:
        assert self.journal is not None
        self.journal.append(kind, payload, observed, observed, self.started_at)
        self.last_observed_at = observed

    def _pause(self, reason: str, now: float) -> None:
        self.paused, self.problem = True, reason
        data = {"source": "runtime", "reason": reason, "from": now, "to": None}
        self._append("weather_gap", data, now)
        self.model.ingest("weather_gap", data, now)
        log.warning("weatherwatch_paused reason=%s", reason)

    def emit(self, kind: str, payload: dict[str, Any], observed: float) -> bool:
        with self.mutex:
            if self.paused:
                return False
            if not math.isfinite(observed):
                raise ValueError("Nonfinite weather dispatch time")
            if self.last_observed_at is not None and observed < self.last_observed_at:
                self._pause("Receipt clock moved backwards; recording paused", self.last_observed_at)
                self.checkpoint()
                return False
            if not self._storage_ok():
                self._pause("Storage limit or free-space reserve reached", observed)
                self.checkpoint()
                return False
            self._append(kind, payload, observed)
            if kind == "weather_tick":
                actions = self.model.tick(observed)
            elif kind in INPUTS:
                actions = self.model.ingest(kind, payload, observed)
            else:
                actions = []
            for action in actions:
                if not self._storage_ok():
                    self._pause("Storage limit reached while recording capture actions", observed)
                    self.checkpoint()
                    break
                data = dict(action)
                action_kind = str(data.pop("kind"))
                self._append(action_kind, data, observed)
                if action_kind == "watch_request" and self.markets is not None and not self.markets.watch(data):
                    self.capacity_skips += 1
                    rejected = {"market_id": data.get("market_id"), "reason": "capture_capacity_or_unsupported"}
                    self._append("weather_watch_rejected", rejected, observed)
                    self.model.ingest("weather_watch_rejected", rejected, observed)
            return True

    def on_event(self, kind: str, payload: dict[str, Any], received_at: float) -> None:
        # HTTP adapters may finish on executor threads. Market watch() can also
        # emit a status inline. Neither may re-enter the model/journal mid-event.
        data = {**payload, "source_received_at": received_at}
        size = len(json.dumps(data, allow_nan=False, separators=(",", ":")).encode())
        with self.mutex:
            if self.paused:
                return
            if size > 256 * 1024 or len(self.pending) >= 256 or self.pending_bytes + size > 4 * 1024 * 1024:
                self.queue_overflow = True
                return
            self.pending.append((kind, data, size))
            self.pending_bytes += size

    def drain(self) -> None:
        with self.mutex:
            if self.queue_overflow and not self.paused:
                now = max(self.clock(), self.last_observed_at or self.started_at)
                self._pause("Callback queue capacity exceeded; capture has a gap", now)
                self.pending.clear()
                self.pending_bytes = 0
                self.checkpoint()
                return
            for _ in range(256):
                if not self.pending or self.paused:
                    break
                kind, payload, size = self.pending.popleft()
                self.pending_bytes -= size
                self.emit(kind, payload, self.clock())

    def panel(self) -> dict[str, Any]:
        with self.mutex:
            return self._panel()

    def _panel(self) -> dict[str, Any]:
        assert self.journal is not None
        now = self.clock()
        result = self.model.summary(now)
        reports = result.get("reports", {})
        today = result.get("today", {})
        if today.get("day"):
            reports.setdefault(today["day"], today)
        result["reports"] = {day: reports[day] for day in sorted(reports)[-self.settings.weatherwatch_retention_days:]}
        return {**result, "as_of": now, "read_only": True, "real_orders_available": False,
            "status": "PAUSED" if self.paused else "MEASURING", "problem": self.problem,
            "storage_bytes": self.journal.storage_bytes + self.journal.pending_bytes,
            "active_watches": sum(lock["capture_until"] >= now and not lock.get("watch_rejected")
                                  for lock in self.model.locks.values()),
            "capacity_skips": self.capacity_skips}

    def flush(self) -> None:
        with self.mutex:
            assert self.journal is not None
            self.journal.flush(self.started_at)
            self.last_flush = self.clock()

    def checkpoint(self) -> None:
        with self.mutex:
            self.flush()
            assert self.journal is not None
            state = {"version": 1, "seq": self.journal.seq, "hash": self.journal.previous_hash,
                "started_at": self.started_at, "last_observed_at": self.last_observed_at, "panel": self.panel()}
            _atomic(self.path, json.dumps(state, allow_nan=False, separators=(",", ":")))
            self.last_checkpoint = self.clock()

    def reports(self) -> None:
        with self.mutex:
            self._reports()

    def _reports(self) -> None:
        directory = self.directory / "daily"
        directory.mkdir(exist_ok=True)
        panel = self.panel()
        reports = panel.get("reports", {})
        for day, report in reports.items():
            _atomic(directory / f"{day}.json", json.dumps(report, allow_nan=False, indent=2))
            _atomic(directory / f"{day}.md", report_markdown(report))
        # Only derivative reports are pruned, never the verifiable source tape.
        for path in directory.iterdir():
            if path.suffix in {".json", ".md"} and path.stem not in reports:
                path.unlink()
        today = panel.get("today", {})
        log.info("weatherwatch_status mode=MEASURE_ONLY real_orders=false status=%s markets=%s "
            "proxies=%s gaps=%s cents_per_day=unknown", panel["status"], panel.get("markets", 0),
            today.get("confirmed_observation_proxies", 0), today.get("gaps", 0))
        self.last_report = self.clock()

    async def run(self) -> None:
        if self.market_factory is None:
            from .weatherwatch_markets import MarketFeeds
            self.market_factory = MarketFeeds
        if self.observation_factory is None:
            from .weatherwatch_observations import ObservationFeeds
            self.observation_factory = ObservationFeeds
        self.markets = self.market_factory(self.on_event, self.stop, settings=self.settings,
            clock=self.clock, receipt_clock_id=self.receipt_clock_id,
            discovery_s=self.settings.weatherwatch_discovery_s,
            max_active_watches=self.settings.weatherwatch_max_active_watches)
        self.markets.restore(self.model.markets, self.restored_watches())
        observations = self.observation_factory(self.on_event, self.stop, lambda: self.markets.stations,
            clock=self.clock, receipt_clock_id=self.receipt_clock_id)
        tasks = [asyncio.create_task(self.markets.run()), asyncio.create_task(observations.run())]
        try:
            while not self.stop.is_set() and not self.paused:
                for task in tasks:
                    if task.done():
                        task.result()
                        raise RuntimeError("Weather source task exited")
                self.drain()
                now = self.clock()
                if now - self.last_tick >= 1:
                    self.emit("weather_tick", {"now": now}, now)
                    self.last_tick = now
                if now - self.last_flush >= 1:
                    self.flush()
                if now - self.last_checkpoint >= 10:
                    self.checkpoint()
                if now - self.last_report >= 60:
                    self.reports()
                await asyncio.sleep(.025)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.drain()
            self.emit("weather_gap", {"source": "runtime", "reason": "shutdown", "to": None}, self.clock())
            self.checkpoint()

    def restored_watches(self) -> dict[str, float]:
        # Rejected/revised proxies must not regain capture capacity on restart,
        # but their eventual outcomes remain part of the disagreement audit.
        now = self.clock()
        return {key: min(row["capture_until"], now)
                if row.get("watch_rejected") or row.get("assessment_blocked_reason") else row["capture_until"]
                for key, row in self.model.locks.items()}

    def close(self) -> None:
        with self.mutex:
            self._close()

    def _close(self) -> None:
        try:
            if self.journal is not None:
                try:
                    self.flush()
                    self.journal.seal()
                finally:
                    self.journal.close()
        finally:
            self.lock.close()


def run_weatherwatch(settings: Settings, stop: threading.Event) -> None:
    if not settings.weatherwatch_enabled:
        return
    runner = None
    try:
        for attempt in range(30):
            if stop.is_set():
                return
            try:
                runner = WeatherwatchRunner(settings, stop)
                break
            except RuntimeError as exc:
                if "already owned" not in str(exc) or attempt == 29:
                    raise
                stop.wait(1)
        if runner is not None:
            asyncio.run(runner.run())
    except Exception as exc:  # noqa: BLE001 — measurement faults never affect a money thread.
        log.error("weatherwatch_halted error=%s", type(exc).__name__)
        if runner is not None:
            runner.paused, runner.problem = True, "Weather capture halted; source evidence needs inspection"
            try:
                runner.checkpoint()
            except Exception:  # noqa: BLE001 — no arbitrary request or credential error text.
                log.error("weatherwatch_state_unavailable")
    finally:
        if runner is not None:
            try:
                runner.close()
            except Exception:  # noqa: BLE001 — shutdown errors stay isolated.
                log.error("weatherwatch_close_failed")

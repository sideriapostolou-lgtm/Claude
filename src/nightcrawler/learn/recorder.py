"""The recorder: forward capture of every pump.fun graduate (docs/LEARNING.md §3.1, §10). I/O only.

A daemon :class:`RecorderThread` runs :meth:`Recorder.step` every :data:`STEP_EVERY_S`:

1. **emits** - rows the engine queued with :meth:`Recorder.emit` (``put_nowait``; a full queue drops
   the row and counts it, so trading never waits for learning) are appended to the tape.
2. **census** - every 5 min the top pages (offsets 0/70/140) of pump.fun's graduated-coin census,
   every 6 h a full sweep (offsets 0-980) for late graduates. A coin seen for the first time is
   enrolled: its census row goes to the ``universe`` stream and its fetches are scheduled at FIXED
   ages since first seen - candles at +3 h, +12 h and +50 h, DexScreener snapshots at
   +5/15/30/60/120/240/360 min. No fetch ever depends on how a coin is doing.
3. **candles** - due candle fetches (swap API, up to 1000 traded minutes) -> ``candles`` rows
   (new closed minutes only, revisions counted; :func:`~nightcrawler.learn.tape.candle_fetch_row`).
4. **snaps** - due snapshots, batched 30 mints per DexScreener call -> raw pairs in ``snaps``.
5. **roots** - every hour the bytes appended since the last root are hashed and queued as a
   ``tape_root`` outbox row (the engine receipts it).
6. **seal** - a finished day whose coins are all closed is sealed (``tape_seal`` outbox row).

A fetch that fails is retried with backoff; after :data:`MAX_ATTEMPTS` it is given up and the coin
becomes ``incomplete``. A 429 or 403 pauses that HOST for :data:`BREAKER_S` (the fetch is postponed,
no attempt counted). The recorder has its OWN :class:`~nightcrawler.http.HttpClient`
(:func:`build_http`: buckets below every host's spare capacity, no inline retries), so it can never
take a token from trading. Free space below :data:`LOW_DISK_BYTES` pauses every learning write.
A crash inside a step is caught by the thread and the step is retried with exponential backoff;
every step is idempotent (the queue and the marks live in learn.db).

Imports only ``http``, ``sources`` and ``learn.{tape,store}`` (``tests/test_learn_boundary.py``).
"""

from __future__ import annotations

import logging
import queue
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from nightcrawler.http import HttpClient, HttpError, host_of
from nightcrawler.learn.store import LearnStore, learn_dir
from nightcrawler.learn.tape import (
    TapeSealed,
    TapeWriter,
    candle_fetch_row,
    candle_mark,
    segment_root,
    tape_day,
    universe_row,
)
from nightcrawler.sources.dexscreener import BASE_URL as DEXSCREENER_URL
from nightcrawler.sources.dexscreener import MAX_BATCH, DexScreenerClient
from nightcrawler.sources.pumpfun import CENSUS_HOST, CENSUS_PAGE, PumpFunClient, PumpFunCoolingDown
from nightcrawler.sources.pumpfun import HOST as SWAP_HOST

__all__ = [
    "STEP_EVERY_S",
    "CENSUS_EVERY_S",
    "SWEEP_EVERY_S",
    "TOP_OFFSETS",
    "SWEEP_OFFSETS",
    "CANDLE_FETCH_H",
    "SNAP_AGES_MIN",
    "MAX_ATTEMPTS",
    "RETRY_BACKOFF_S",
    "BREAKER_S",
    "ROOT_EVERY_S",
    "LOW_DISK_BYTES",
    "RATE_LIMITS",
    "build_http",
    "Recorder",
    "RecorderThread",
    "start_recorder",
]

log = logging.getLogger("nightcrawler.learn.recorder")

STEP_EVERY_S = 20.0
CENSUS_EVERY_S = 300.0
SWEEP_EVERY_S = 6 * 3600.0
TOP_OFFSETS = (0, 70, 140)
SWEEP_OFFSETS = tuple(range(0, 981, CENSUS_PAGE))
#: Coins first found beyond the top pages graduated long after creation: flagged ``late``.
LATE_OFFSET = TOP_OFFSETS[-1] + CENSUS_PAGE
CANDLE_FETCH_H = (3, 12, 50)
SNAP_AGES_MIN = (5, 15, 30, 60, 120, 240, 360)
CANDLES_PER_STEP = 2
MAX_ATTEMPTS = 5
RETRY_BACKOFF_S = (60.0, 300.0, 900.0, 1800.0, 3600.0)
BREAKER_S = 600.0
BREAKER_STATUSES = frozenset({403, 429})
ROOT_EVERY_S = 3600.0
LOW_DISK_BYTES = 1 << 30
EMITS_PER_STEP = 5000
DEXSCREENER_HOST = host_of(DEXSCREENER_URL)
#: The recorder's own buckets (requests per second, burst): census ~0.7/min used of 12/min, candles
#: ~2.5/min of 6/min, snapshots <= 1.5/min of 4/min (DexScreener allows 60/min; trading uses ~5).
RATE_LIMITS: dict[str, tuple[float, float]] = {
    CENSUS_HOST: (12 / 60, 3),
    SWAP_HOST: (6 / 60, 2),
    DEXSCREENER_HOST: (4 / 60, 2),
}


def build_http(session: Any = None, clock: Any = None) -> HttpClient:
    """The recorder's own client: capped buckets, NO inline retries (the queue retries later)."""
    return HttpClient(session=session, clock=clock, rate_limits=RATE_LIMITS, default_rate=(1 / 60, 1), max_retries=0)


def _free_bytes(path: Path) -> int | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            try:
                return shutil.disk_usage(candidate).free
            except OSError:
                return None
    return None


def _hour(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H")


class Recorder:
    """One recorder pass at a time (see the module docstring). Not thread-safe except :meth:`emit`."""

    def __init__(self, store: LearnStore, tape: TapeWriter, http: HttpClient, *, clock: Any = None,
                 emit_maxsize: int = 10_000) -> None:
        self.store = store
        self.tape = tape
        self.http = http
        self.clock = clock if clock is not None else http.clock
        self.pumpfun = PumpFunClient(http, clock=self.clock)
        self.dexscreener = DexScreenerClient(http)
        self.paused_until: dict[str, float] = {}
        self.stats: dict[str, int] = {"census_calls": 0, "candle_calls": 0, "snap_calls": 0, "enrolled": 0,
                                      "revisions": 0, "errors": 0, "breaker_trips": 0, "emits_dropped": 0,
                                      "low_disk_skips": 0}
        self._emits: queue.Queue[tuple[str, Mapping[str, Any]]] = queue.Queue(maxsize=emit_maxsize)

    def close(self) -> None:
        self.tape.close()
        self.store.close()

    # ---------------------------------------------------------------- engine side (never blocks)
    def emit(self, stream: str, row: Mapping[str, Any]) -> bool:
        """Queue an engine row (``evals`` / ``fills`` / ``lag``) for the tape; False when dropped."""
        try:
            self._emits.put_nowait((stream, row))
            return True
        except queue.Full:
            self.stats["emits_dropped"] += 1
            return False

    # ---------------------------------------------------------------- the pass
    def step(self) -> dict[str, Any]:
        now = self.clock.now()
        free = _free_bytes(self.tape.root)
        if free is not None and free < LOW_DISK_BYTES:
            self.stats["low_disk_skips"] += 1
            if self.stats["low_disk_skips"] == 1:
                log.warning("learn_paused reason=low_disk free_mb=%d", free // (1 << 20))
            return {"skipped": "low disk"}
        return {"emits": self._drain_emits(now), "census": self._census(now), "candles": self._candles(now),
                "snaps": self._snaps(now), "roots": self._roots(now), "sealed": self._seal(now)}

    def paused(self, host: str, now: float | None = None) -> bool:
        return (self.clock.now() if now is None else now) < self.paused_until.get(host, 0.0)

    def _backing_off(self, host: str, exc: Exception, now: float) -> bool:
        """A 429/403 (or pump.fun's own cool-down) opens the host's circuit breaker; True if so."""
        if isinstance(exc, PumpFunCoolingDown) or (isinstance(exc, HttpError) and exc.status in BREAKER_STATUSES):
            self.paused_until[host] = now + BREAKER_S
            self.stats["breaker_trips"] += 1
            log.warning("learn_breaker_open host=%s pause_s=%.0f", host, BREAKER_S)
            return True
        return False

    def _drain_emits(self, now: float) -> int:
        n = 0
        while n < EMITS_PER_STEP:
            try:
                stream, row = self._emits.get_nowait()
            except queue.Empty:
                break
            coin = self.store.coin(row["mint"]) if isinstance(row.get("mint"), str) else None
            day = coin["day"] if coin else tape_day(float(row.get("ts", now)))
            try:
                self.tape.append(stream, day, row)
            except TapeSealed:
                self.tape.append(stream, tape_day(now), row)
            n += 1
        return n

    # ---------------------------------------------------------------- census
    def _census(self, now: float) -> int:
        if now - float(self.store.get_meta("recorder.census_at", 0.0)) < CENSUS_EVERY_S:
            return 0
        sweep = now - float(self.store.get_meta("recorder.sweep_at", 0.0)) >= SWEEP_EVERY_S
        enrolled = 0
        for offset in SWEEP_OFFSETS if sweep else TOP_OFFSETS:
            if self.paused(CENSUS_HOST, now):
                return enrolled  # rate limited: this pass is finished after the pause
            try:
                rows = self.pumpfun.census_page(offset)
            except Exception as exc:
                if self._backing_off(CENSUS_HOST, exc, now):
                    return enrolled
                self.stats["errors"] += 1
                log.warning("learn_census_failed offset=%d error=%s", offset, type(exc).__name__)
                break  # any other failure: the next pass is the regular one, never a retry storm
            self.stats["census_calls"] += 1
            fetched = self.clock.now()
            enrolled += sum(self._enroll(row, fetched, offset) for row in rows if isinstance(row, Mapping))
        self.store.set_meta("recorder.census_at", now)
        if sweep:
            self.store.set_meta("recorder.sweep_at", now)
        return enrolled

    def _enroll(self, row: Mapping[str, Any], fetched: float, offset: int) -> int:
        mint = row.get("mint")
        if not isinstance(mint, str) or self.store.coin(mint) is not None:
            return 0
        universe = universe_row(row, fetched_ts=fetched, offset=offset, late=offset >= LATE_OFFSET)
        if universe is None:
            return 0
        day = tape_day(fetched)
        self.tape.append("universe", day, universe)  # the tape first: a crash here only repeats the row
        launch = universe["launch"]
        with self.store.transaction():
            self.store.add_coin(mint, created_ts=universe["created_ts"], first_seen_ts=fetched, day=day,
                                pool=launch.get("pump_swap_pool"), quote_mint=launch.get("quote_mint"),
                                mayhem=launch["mayhem"], late=universe["late"], launch=launch)
            for hours in CANDLE_FETCH_H:
                self.store.schedule(mint, "candles", fetched + hours * 3600)
            for age in SNAP_AGES_MIN:
                self.store.schedule(mint, "snaps", fetched + age * 60)
        self.stats["enrolled"] += 1
        return 1

    # ---------------------------------------------------------------- fetch queue
    def _candles(self, now: float) -> int:
        done = 0
        for item in self.store.due(now, kind="candles", limit=CANDLES_PER_STEP):
            if self.paused(SWAP_HOST, now):
                break
            try:
                rows = self.pumpfun.raw_candles(item["mint"])
            except Exception as exc:
                if self._backing_off(SWAP_HOST, exc, now):
                    self.store.postpone_fetch(item["mint"], "candles", item["due_ts"], now + BREAKER_S)
                    break
                self._failed(item, now, exc)
                continue
            self.stats["candle_calls"] += 1
            fetched = self.clock.now()
            coin = self.store.coin(item["mint"])
            if coin is None:
                continue
            mark = coin["mark"]
            row = candle_fetch_row(item["mint"], rows, fetched_ts=fetched, previous=mark,
                                   fetch_no=int((mark or {}).get("fetches", 0)) + 1)
            self.tape.append("candles", coin["day"], row)
            self.stats["revisions"] += len(row["revised"])
            with self.store.transaction():
                self.store.set_coin_mark(item["mint"], candle_mark(row, mark))
                self.store.finish_fetch(item["mint"], "candles", item["due_ts"], fetched)
                self._maybe_close(item["mint"])
            done += 1
        return done

    def _snaps(self, now: float) -> int:
        if self.paused(DEXSCREENER_HOST, now):
            return 0
        due = self.store.due(now, kind="snaps", limit=MAX_BATCH)
        if not due:
            return 0
        try:
            pairs = self.dexscreener.tokens([item["mint"] for item in due])
        except Exception as exc:
            if self._backing_off(DEXSCREENER_HOST, exc, now):
                for item in due:
                    self.store.postpone_fetch(item["mint"], "snaps", item["due_ts"], now + BREAKER_S)
            else:
                for item in due:
                    self._failed(item, now, exc)
            return 0
        self.stats["snap_calls"] += 1
        fetched = self.clock.now()
        for item in due:
            coin = self.store.coin(item["mint"])
            if coin is None:
                continue
            age = round((item["due_ts"] - coin["first_seen_ts"]) / 60)
            self.tape.append("snaps", coin["day"], {
                "v": 1, "ts": fetched, "mint": item["mint"], "src": {"dexscreener": [fetched, 200]},
                "age_min": age, "pair": pairs.get(item["mint"])})
            with self.store.transaction():
                self.store.finish_fetch(item["mint"], "snaps", item["due_ts"], fetched)
                self._maybe_close(item["mint"])
        return len(due)

    def _failed(self, item: Mapping[str, Any], now: float, exc: Exception) -> None:
        self.stats["errors"] += 1
        backoff = RETRY_BACKOFF_S[min(int(item["attempts"]), len(RETRY_BACKOFF_S) - 1)]
        attempts = self.store.retry_fetch(item["mint"], item["kind"], item["due_ts"], now + backoff)
        log.warning("learn_fetch_failed kind=%s attempts=%d error=%s", item["kind"], attempts, type(exc).__name__)
        if attempts >= MAX_ATTEMPTS:  # given up: the coin ends ``incomplete`` once its other fetches are done
            with self.store.transaction():
                self.store.fail_fetch(item["mint"], item["kind"], item["due_ts"], now)
                self._maybe_close(item["mint"])

    def _maybe_close(self, mint: str) -> None:
        """Once nothing is left to fetch: ``closed``, or ``incomplete`` if any fetch was given up."""
        if self.store.open_fetches(mint) == 0:
            failed = any(f["failed"] for f in self.store.fetches(mint))
            self.store.set_coin_status(mint, "incomplete" if failed else "closed")

    # ---------------------------------------------------------------- roots and seals
    def _roots(self, now: float, force: bool = False) -> int:
        if not force and now - float(self.store.get_meta("tape.root_at", 0.0)) < ROOT_EVERY_S:
            return 0
        offsets = dict(self.store.get_meta("tape.offsets", {}))
        segments = self.tape.segments(offsets)
        with self.store.transaction():
            if segments:
                self.store.add_outbox("tape_root", {"hour": _hour(now), "segments": segments,
                                                    "root": segment_root(segments)}, now)
                offsets.update({s["file"]: s["end"] for s in segments})
                self.store.set_meta("tape.offsets", offsets)
            self.store.set_meta("tape.root_at", now)
        return len(segments)

    def _seal(self, now: float) -> int:
        sealed_days = list(self.store.get_meta("tape.sealed_days", []))
        today = tape_day(now)
        sealed = 0
        for day in self.store.days():
            if day >= today or day in sealed_days:
                continue
            counts = self.store.day_counts(day)
            if counts["open"]:
                continue
            self._roots(now, force=True)  # every byte gets an hourly root before the files are compressed
            manifest = self.tape.seal(day)
            with self.store.transaction():
                self.store.add_outbox("tape_seal", {
                    "day": day, "files": manifest["files"], "root": manifest["root"],
                    "completeness": counts["closed"] / counts["coins"] if counts["coins"] else 0.0}, now)
                sealed_days.append(day)
                self.store.set_meta("tape.sealed_days", sealed_days)
                offsets = self.store.get_meta("tape.offsets", {})
                self.store.set_meta("tape.offsets", {f: e for f, e in offsets.items() if not f.startswith(day + "/")})
            self.tape.finish_seal(day)
            sealed += 1
        return sealed


class RecorderThread(threading.Thread):
    """Runs ``recorder.step()`` forever on a daemon thread; a crash is logged (type only) and retried with
    exponential backoff (``backoff_s = (first, max)``). Nothing ever propagates to the engine."""

    def __init__(self, recorder: Any, *, interval_s: float = STEP_EVERY_S,
                 backoff_s: tuple[float, float] = (5.0, 600.0), stop_event: threading.Event | None = None) -> None:
        super().__init__(name="learn-recorder", daemon=True)
        self.recorder = recorder
        self.interval_s = interval_s
        self.backoff_min, self.backoff_max = backoff_s
        self.stop_event = stop_event or threading.Event()
        self.crashes = 0
        self.last_error: str | None = None

    def run(self) -> None:
        delay = self.backoff_min
        while not self.stop_event.is_set():
            try:
                self.recorder.step()
            except Exception as exc:  # a dead recorder is restarted; trading never notices
                self.crashes += 1
                self.last_error = type(exc).__name__
                log.warning("learn_recorder_crash error=%s restart_in_s=%.1f", self.last_error, delay)
                wait, delay = delay, min(delay * 2, self.backoff_max)
            else:
                wait, delay = self.interval_s, self.backoff_min
            self.stop_event.wait(wait)

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.is_alive():
            self.join(timeout)
        close = getattr(self.recorder, "close", None)
        if callable(close) and not self.is_alive():
            close()


def start_recorder(settings: Any, *, session: Any = None, clock: Any = None,
                   interval_s: float = STEP_EVERY_S) -> RecorderThread | None:
    """Start the recorder for ``settings.data_dir``. None - and not one call or file - when LEARN_ENABLED is
    off; None (logged) when the learn directory is unusable: learning never stops the engine from starting."""
    if not settings.learn_enabled:
        return None
    root = learn_dir(settings.data_dir)
    try:
        store = LearnStore(root / "learn.db")
    except Exception as exc:
        log.warning("learn_recorder_not_started error=%s", type(exc).__name__)
        return None
    http = build_http(session=session, clock=clock)
    thread = RecorderThread(Recorder(store, TapeWriter(root / "tape"), http, clock=clock), interval_s=interval_s)
    thread.start()
    return thread

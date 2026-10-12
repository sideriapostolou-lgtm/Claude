"""Independent Bitcoin speed desk. All holdings and orders are practice only.

The receipt ledger is the durable source of truth; state.json is its atomic,
read-only dashboard mirror. A crash can lose a cached quote, never a booked
fill. Only the read-only feed adapter receives venue credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .clock import Clock, RealClock
from .config import Settings
from .ledger import Ledger
from .speeddesk_model import (
    Book,
    Decision,
    PracticeDesk,
    SpeedConfig,
    Trade,
    Window,
    utc_day,
)
from .speeddesk_venues import MarketFeeds

log = logging.getLogger("nightcrawler.speeddesk")
STATE_KEY = "speeddesk_state"


def practice_config(settings: Settings) -> SpeedConfig:
    if settings.speeddesk_mode != "paper":
        raise ValueError("Speed desk only supports practice mode")
    return SpeedConfig(take_edge=settings.speeddesk_take_edge, make_edge=settings.speeddesk_make_edge,
                       clip=settings.speeddesk_clip, pair_cap=settings.speeddesk_pair_cap,
                       max_imbalance=settings.speeddesk_max_imbalance,
                       window_usd=settings.speeddesk_window_usd, open_usd=settings.speeddesk_open_usd,
                       day_stop_usd=settings.speeddesk_day_stop_usd, cutoff_s=settings.speeddesk_cutoff_s,
                       latency_ms=settings.speeddesk_latency_ms)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, allow_nan=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def panel_state(settings: Settings, now: float) -> dict[str, Any]:
    """Read practice evidence only. Missing/corrupt reports are not zero profit."""
    path = settings.data_dir / "speeddesk" / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != 1 or state.get("mode") != "practice":
        raise ValueError("Invalid practice report")
    panel = state.get("panel")
    if not isinstance(panel, dict):
        raise TypeError("Missing practice panel")
    return panel


class SpeedRunner:
    """Owns one event loop, independent caps, durable receipts and daily reports."""

    def __init__(self, settings: Settings, stop: threading.Event, *, clock: Clock | None = None,
                 feed_factory: Callable[..., Any] = MarketFeeds) -> None:
        config = practice_config(settings)
        self.clock = clock or RealClock(stop)
        self.stop = stop
        self.directory = settings.data_dir / "speeddesk"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.ledger = Ledger(self.directory / "receipts.db", self.clock)
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.last_checkpoint = -math.inf
        self.last_heartbeat = -math.inf
        self.last_step = self.clock.now()
        self.feed_status: dict[str, Any] = {"coinbase": "connecting", "markets": "connecting",
                                           "trade_stream": False}
        self.problem: str | None = None
        try:
            saved = self.ledger.get_kv(STATE_KEY)
            if saved is None and self.path.exists():
                # Never silently reset a trial whose durable ledger disappeared.
                raise ValueError("Practice receipt ledger missing beside existing report")
            if saved is not None:
                if saved.get("version") != 1 or saved.get("mode") != "practice":
                    raise ValueError("Unsupported persisted practice trial")
                self.desk = PracticeDesk.from_state(saved["model"], config)
                self.started_at = float(saved["started_at"])
                self.reports: dict[str, dict[str, Any]] = saved.get("reports", {})
                self.observed: dict[str, float] = saved.get("observed_seconds", {})
                self.feed_latency: dict[str, list[float]] = saved.get("feed_latency", {})
                self.opening_logged: set[str] = set(saved.get("opening_logged", []))
                for order in saved["model"].get("orders", []):
                    self.record("speeddesk_cancel", {**order, "at": self.clock.now(), "reason": "restart"})
            else:
                self.desk = PracticeDesk(config)
                self.started_at = self.clock.now()
                self.reports = {}
                self.observed = {}
                self.feed_latency = {}
                self.opening_logged = set()
            self.feeds = feed_factory(settings, on_tick=self.on_tick, on_book=self.on_book,
                                      on_trade=self.on_trade, on_windows=self.on_windows,
                                      on_status=self.on_status, clock=self.clock.now)
        except BaseException:
            self.ledger.close()
            raise

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        self.pending.append((kind, {"mode": "practice", **payload}))

    def decisions(self, events: list[Decision]) -> None:
        for event in events:
            # Repeated unchanged skips belong in the heartbeat reason map, not
            # thousands of identical receipts on every tick.
            if event.event != "speeddesk_skip":
                self.record(event.event, asdict(event))
        if self.pending:
            self.checkpoint(self.clock.now())

    def on_tick(self, price: float, event_at: float, received_at: float) -> None:
        if not 0 <= received_at - event_at <= self.desk.config.stale_s:
            return
        self.desk.tick_btc(price, event_at)
        daily = self.feed_latency.setdefault(utc_day(received_at), [0.0, 0.0])
        daily[0] += (received_at - event_at) * 1000
        daily[1] += 1
        for window in self.desk.windows.values():
            if window.start_price is not None and window.slug not in self.opening_logged:
                self.opening_logged.add(window.slug)
                self.record("speeddesk_opening", {"window": window.slug, "at": received_at,
                                                 "coinbase_start_price": window.start_price,
                                                 "venue_start_price": window.venue_start_price,
                                                 "settlement_source": "venue BRTI outcome"})

    def on_book(self, book: Book) -> None:
        if self.desk.on_book(book):
            # Resolve the first eligible post-delay snapshot immediately. A
            # later favorable update may never replace a failed recheck.
            self.decisions(self.desk.advance(self.clock.now()))

    def on_trade(self, trade: Trade) -> None:
        allowed = not hasattr(self.feeds, "maker_windows") or trade.window in self.feeds.maker_windows()
        if self.feed_status.get("trade_stream") and allowed:
            self.decisions(self.desk.on_trade(trade, self.clock.now()))

    def on_windows(self, windows: list[Window]) -> None:
        for window in windows:
            previous = self.desk.windows.get(window.slug)
            terms = ("taker_coefficient", "maker_coefficient", "tick_size", "min_trade_qty", "fee_rounding")
            if previous is not None and any(getattr(previous, key) != getattr(window, key) for key in terms):
                self.decisions(self.desk.cancel(self.clock.now(), window.slug, "venue_terms_changed"))
                self.desk.books = {key: book for key, book in self.desk.books.items() if key[0] != window.slug}
            self.desk.add_window(window)

    def on_status(self, status: dict[str, Any]) -> None:
        old = self.feed_status
        self.feed_status = status
        if ((old.get("trade_stream") and not status.get("trade_stream"))
                or (old.get("coinbase") == "connected" and status.get("coinbase") != "connected")):
            self.decisions(self.desk.cancel(self.clock.now(), reason="feed_gap"))
            self.desk.books.clear()
        else:
            for slug in status.get("gap_windows", []):
                self.decisions(self.desk.cancel(self.clock.now(), slug, "venue_feed_gap"))
                self.desk.books = {key: book for key, book in self.desk.books.items() if key[0] != slug}

    def summary(self, day: str) -> dict[str, Any]:
        report = self.desk.daily_summary(day)
        latency = self.feed_latency.get(day, [0.0, 0.0])
        report.update(observed_seconds=self.observed.get(day, 0.0),
                      avg_bitcoin_feed_latency_ms=latency[0] / latency[1] if latency[1] else None,
                      latency_definition="decision to simulated fill; maker includes resting time")
        for prefix in ("take", "maker"):
            attempts = report["take_attempts" if prefix == "take" else "maker_orders"]
            report[f"{prefix}_fill_rate_pct"] = 100 * report[f"{prefix}_fills"] / attempts if attempts else None
        return report

    def daily_reports(self, now: float) -> None:
        day = datetime.fromtimestamp(self.started_at, UTC).date()
        current = datetime.fromtimestamp(now, UTC).date()
        while day < current:
            key = day.isoformat()
            if key not in self.reports:
                report = self.summary(key)
                report.update(mode="practice", partial_day=self.observed.get(key, 0) < 86395,
                              started_at=self.started_at, reported_at=now)
                self.reports[key] = report
                self.record("speeddesk_daily", report)
            day += timedelta(days=1)

    def panel(self, now: float) -> dict[str, Any]:
        btc_at = self.desk.tape.last_at
        books = [book.at for book in self.desk.books.values()
                 if book.window in self.desk.windows and self.desk.windows[book.window].start <= now
                 < self.desk.windows[book.window].end]
        warm = self.desk.tape.sigma(now, self.desk.config.sigma_min_samples) is None
        status = "Warming up Bitcoin volatility" if warm else "Practice feeds running"
        if btc_at is None or not 0 <= now - btc_at <= self.desk.config.stale_s:
            status = "Practice paused: Bitcoin feed stale"
        elif not books or now - min(books) > self.desk.config.stale_s:
            status = "Practice paused: waiting for fresh books"
        if not self.feed_status.get("trade_stream"):
            status += "; trade stream unavailable, maker fills disabled"
        return {"mode": "paper", "as_of": now, "started_at": self.started_at,
                "status": status, "problem": self.problem,
                "btc_age_s": max(0.0, now - btc_at) if btc_at is not None else None,
                "book_age_s": max(0.0, now - min(books)) if books else None,
                "today": self.summary(utc_day(now)), "reports": self.reports,
                "feeds": self.feed_status, "window_reasons": dict(self.desk.last_reason),
                "real_orders_available": False}

    def checkpoint(self, now: float) -> None:
        self.daily_reports(now)
        state = {"version": 1, "mode": "practice", "started_at": self.started_at, "updated_at": now,
                 "model": self.desk.to_state(), "reports": self.reports, "observed_seconds": self.observed,
                 "feed_latency": self.feed_latency, "opening_logged": sorted(self.opening_logged),
                 "panel": self.panel(now)}
        with self.ledger.transaction():
            for kind, payload in self.pending:
                self.ledger.append_receipt(kind, payload, ts=payload.get("at", now))
            self.ledger.set_kv(STATE_KEY, state)
        for kind, payload in self.pending:
            log.info("%s %s", kind, json.dumps(payload, allow_nan=False, separators=(",", ":")))
        self.pending.clear()
        # A mirror failure halts practice, but the committed ledger survives it.
        _atomic_json(self.path, state)
        self.last_checkpoint = now

    def step(self, now: float) -> None:
        # Count observed runtime, never claim coverage for offline gaps.
        duration = max(0.0, min(1.0, now - self.last_step))
        self.observed[utc_day(now)] = self.observed.get(utc_day(now), 0.0) + duration
        self.last_step = now
        maker_windows = self.feeds.maker_windows() if hasattr(self.feeds, "maker_windows") else None
        self.decisions(self.desk.evaluate(now, makers_enabled=bool(self.feed_status.get("trade_stream")),
                                          maker_windows=maker_windows))
        if now - self.last_heartbeat >= 60:
            self.record("speeddesk_status", self.panel(now))
            self.last_heartbeat = now
        if self.pending or now - self.last_checkpoint >= 5:
            self.checkpoint(now)

    async def _settlements(self) -> None:
        while not self.stop.is_set():
            closed = {item.window for item in self.desk.closed}
            for window in list(self.desk.windows.values()):
                if window.slug in closed or self.clock.now() < window.end:
                    continue
                outcome = await self.feeds.settlement(window.slug)
                if outcome not in (0.0, 1.0):
                    continue
                now = self.clock.now()
                self.decisions(self.desk.cancel(now, window.slug, "settled"))
                result = self.desk.settle(window.slug, outcome == 1.0, now)
                if result is not None:
                    self.record("speeddesk_window", {**asdict(result), "side": "both", "price": None,
                                                     "size": result.up_shares + result.down_shares,
                                                     "fair": None, "edge": None, "latency_ms": None,
                                                     "bitcoin_price": self.desk.tape.price,
                                                     "bitcoin_staleness_s": self.panel(now)["btc_age_s"]})
                    self.checkpoint(now)
            await asyncio.sleep(15)

    async def run(self) -> None:
        self.record("speeddesk_started", {"at": self.clock.now(), "real_orders": False,
                                          "trial_started_at": self.started_at, "config": asdict(self.desk.config)})
        self.checkpoint(self.clock.now())
        tasks = [asyncio.create_task(self.feeds.run(self.stop)), asyncio.create_task(self._settlements())]
        try:
            while not self.stop.is_set():
                for task in tasks:
                    if task.done():
                        task.result()
                        if not self.stop.is_set():
                            raise RuntimeError("Practice background task exited")
                self.step(self.clock.now())
                await asyncio.sleep(0.05)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.decisions(self.desk.cancel(self.clock.now(), reason="shutdown"))
            self.checkpoint(self.clock.now())

    def close(self) -> None:
        self.ledger.close()


def run_speeddesk(settings: Settings, stop_event: threading.Event) -> None:
    """Engine thread entry point. A practice fault never enables a real path."""
    runner = None
    try:
        runner = SpeedRunner(settings, stop_event)
        asyncio.run(runner.run())
    except Exception as exc:  # noqa: BLE001 — isolate practice; log no credential-bearing exception text.
        log.error("speeddesk_halted mode=PRACTICE error=%s", type(exc).__name__)
        if runner is not None:
            runner.problem = "Practice desk halted; inspect speeddesk logs"
            try:
                runner.checkpoint(runner.clock.now())
            except Exception:  # noqa: BLE001 — preserve the original durable state if storage failed.
                log.error("speeddesk_state_unavailable mode=PRACTICE")
    finally:
        if runner is not None:
            runner.close()

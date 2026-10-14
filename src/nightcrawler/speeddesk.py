"""Independent Bitcoin practice desk with a separately gated Kalshi companion.

The receipt ledger is the durable source of truth; state.json is its atomic,
read-only dashboard mirror. A crash can lose a cached quote, never a booked
fill. Real Kalshi accounting lives in the companion's own ledger; the
Polymarket US leg and this original practice trial never submit real orders.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .clock import Clock, RealClock
from .config import Settings
from .ledger import Ledger
from .speeddesk_live import KalshiLiveDesk, LiveSnapshot
from .speeddesk_metrics import (
    LatencyMetrics,
    TickReceipt,
    WindowEvidence,
    fresh_window_slugs,
)
from .speeddesk_model import (
    FUTURE_SKEW_S,
    VENUES,
    BitcoinTape,
    Book,
    Decision,
    PracticeDesk,
    SpeedConfig,
    Trade,
    Window,
    config_state,
    utc_day,
)
from .speeddesk_scorecard import window_scorecard
from .speeddesk_venues import MarketFeeds

log = logging.getLogger("nightcrawler.speeddesk")
STATE_KEY = "speeddesk_state"
ARENA_EXIT_WAIT_S = 1.0  # kalshi_arena.EXIT_WAIT_S: at close, time for the practice town's final save


def practice_config(settings: Settings) -> SpeedConfig:
    if settings.speeddesk_mode != "paper":
        raise ValueError("Speed desk only supports practice mode")
    return SpeedConfig(take_edge=settings.speeddesk_take_edge, make_edge=settings.speeddesk_make_edge,
                       clip=settings.speeddesk_clip, pair_cap=settings.speeddesk_pair_cap,
                       max_imbalance=settings.speeddesk_max_imbalance,
                       window_usd=settings.speeddesk_window_usd, open_usd=settings.speeddesk_open_usd,
                       day_stop_usd=settings.speeddesk_day_stop_usd, cutoff_s=settings.speeddesk_cutoff_s,
                       latency_ms=settings.speeddesk_latency_ms)


def _atomic_json(path: Path, value: dict[str, Any], *, durable: bool = True) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        # The compact encoder avoids tens of thousands of Python write calls on the live event loop.
        stream.write(json.dumps(value, allow_nan=False, separators=(",", ":")))
        if durable:
            stream.flush()
            os.fsync(stream.fileno())
    os.replace(temporary, path)


def panel_state(settings: Settings, now: float) -> dict[str, Any]:
    """Read practice evidence and the separate Kalshi execution status."""
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

    arena: Any = None  # the Kalshi arena's link (a practice town in its own process) when it runs

    def __init__(self, settings: Settings, stop: threading.Event, *, clock: Clock | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 feed_factory: Callable[..., Any] = MarketFeeds,
                 live_factory: Callable[..., Any] = KalshiLiveDesk) -> None:
        config = practice_config(settings)
        self.clock = clock or RealClock(stop)
        self.monotonic = monotonic
        self.tick_receipt: TickReceipt | None = None
        self.stop = stop
        self.directory = settings.data_dir / "speeddesk"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.ledger = Ledger(self.directory / "receipts.db", self.clock)
        # Practice only, on the real-money desk's event loop (speed plan step 2): its saves are not synced to disk.
        # A process crash loses nothing; a host or power failure can lose the last practice receipts. The first
        # save on a fresh ledger is synced (crash review, 2026-10-13): otherwise a host failure could leave the
        # display copy without its ledger state, and the "missing beside existing report" check below would stop
        # SpeedRunner, which also builds the real-money companion, from starting (or cancelling) at all.
        self.ledger.set_synchronous(False)
        self._first_save_synced = False
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.last_checkpoint = -math.inf
        self.last_heartbeat = -math.inf
        self.last_step = self.clock.now()
        self.last_fresh_venues: set[str] = set()
        self.last_maker_venues: set[str] = set()
        self.feed_status: dict[str, Any] = {"coinbase": "connecting", "markets": "connecting",
                                           "trade_stream": False}
        self.problem: str | None = None
        self.live: KalshiLiveDesk | None = None
        self.live_problem: str | None = None
        self.live_task: asyncio.Task[None] | None = None
        self.live_started = False
        self.last_live_panel: dict[str, Any] = {}
        self._live_market_snapshot = LiveSnapshot()
        self._bitcoin_revision = 0
        self._sigma_key: tuple[int | tuple[str, int, int] | None, int, int, float, float | None, bool] | None = None
        self._sigma_tape: BitcoinTape | None = None
        self._sigma_prices: dict[int, float] | None = None
        self._sigma_value: float | None = None
        self._live_windows_dirty = True
        self._live_windows: tuple[Window, ...] = ()
        self._live_slugs: frozenset[str] = frozenset()
        self._live_opening_seconds: set[int] = set()
        self._live_windows_generation = 0
        self._live_outcome_key: tuple[int, int, int] | None = None
        self._live_outcomes: dict[str, bool] = {}
        self.enabled_venues = {"polymarket_us"}
        if settings.speeddesk_kalshi_enabled:
            self.enabled_venues.add("kalshi")
        try:
            saved = self.ledger.get_kv(STATE_KEY)
            if saved is None and self.path.exists():
                # Never silently reset a trial whose durable ledger disappeared.
                raise ValueError("Practice receipt ledger missing beside existing report")
            self._first_save_synced = saved is not None
            if saved is not None:
                if saved.get("version") != 1 or saved.get("mode") != "practice":
                    raise ValueError("Unsupported persisted practice trial")
                self.desk = PracticeDesk.from_state(saved["model"], config)
                self.started_at = float(saved["started_at"])
                self.reports: dict[str, dict[str, Any]] = saved.get("reports", {})
                self.observed: dict[str, float] = saved.get("observed_seconds", {})
                self.feed_latency: dict[str, list[float]] = saved.get("feed_latency", {})
                self.opening_logged: set[str] = set(saved.get("opening_logged", []))
                self.venue_reporting_started_at = float(saved.get("venue_reporting_started_at", self.clock.now()))
                self.venue_coverage: dict[str, dict[str, dict[str, float]]] = saved.get("venue_coverage", {})
                for order in saved["model"].get("orders", []):
                    self.record("speeddesk_cancel", {**order, "at": self.clock.now(), "reason": "restart"})
            else:
                self.desk = PracticeDesk(config)
                self.started_at = self.clock.now()
                self.reports = {}
                self.observed = {}
                self.feed_latency = {}
                self.opening_logged = set()
                self.venue_reporting_started_at = self.started_at
                self.venue_coverage = {}
            self.metrics = LatencyMetrics(self.clock.now(), saved.get("latency_metrics") if saved else None)
            self.evidence = WindowEvidence(self.clock.now(), saved.get("window_evidence") if saved else None)
            # Previously stored reports contain only combined metrics. Keep
            # those totals, and let the model identify missing venue history.
            for day, report in self.reports.items():
                if "venues" not in report:
                    report["venues"] = {venue: self.summary(day, venue) for venue in VENUES}
            self.feeds = feed_factory(settings, on_tick=self.on_tick, on_book=self.on_book,
                                      on_trade=self.on_trade, on_windows=self.on_windows,
                                      on_status=self.on_status, clock=self.clock.now)
            self._refresh_live_snapshot()
            try:
                self.live = live_factory(settings, self.directory / "kalshi_live", self.live_snapshot,
                                         clock=self.clock.now,
                                         monotonic=self.monotonic,
                                         direct_member_verified=settings.speeddesk_kalshi_account_type == "direct")
                self.live.on_windows(list(self.desk.windows.values()))
            except Exception as exc:  # noqa: BLE001 — isolate live state failure from the running practice trial.
                self.live_problem = "Kalshi companion unavailable; new real orders disabled; inspect live logs"
                log.error("speeddesk_live_status mode=paper reason=initialization_failed error=%s", type(exc).__name__)
                if self.live is not None:
                    try:
                        self.live.close()
                    except Exception:  # noqa: BLE001 — a companion cleanup fault must not stop public feeds.
                        log.error("speeddesk_live_status mode=paper reason=initialization_cleanup_failed")
                self.live = None
            # The Kalshi arena (practice town, nightcrawler.kalshi_arena) runs in its own process: the event loop
            # appends Kalshi books and prints to a bounded list and hands them over once per step, never waiting.
            if settings.kalshi_arena_enabled and settings.speeddesk_kalshi_enabled:
                try:
                    from .kalshi_arena import ArenaLink, arena_config

                    self.arena = ArenaLink(arena_config(settings), clock=self.clock.now)
                except Exception as exc:  # noqa: BLE001 — a practice town never stops the speed desk.
                    log.warning("kalshi_arena_not_started error=%s", type(exc).__name__)
                    self.arena = None
        except BaseException:
            self.ledger.close()
            raise

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        venue = self.desk.window_venues.get(payload.get("window", ""))
        if venue is not None:
            payload = {**payload, "venue": venue}
        self.pending.append((kind, {"mode": "practice", **payload}))

    def decisions(self, events: list[Decision]) -> None:
        for event in events:
            # Repeated unchanged skips belong in the heartbeat reason map, not
            # thousands of identical receipts on every tick.
            if event.event != "speeddesk_skip":
                payload = asdict(event)
                if event.event in ("speeddesk_take", "speeddesk_rest"):
                    venue = self.desk.window_venues.get(event.window, "unknown")
                    payload["timing"] = self.metrics.decision(
                        venue, event.at, self.tick_receipt, self.monotonic())
                if event.event == "speeddesk_fill":
                    self.evidence.fill({**payload, "is_taker": event.kind == "take"})
                self.record(event.event, payload)
        if self.pending:
            self.checkpoint(self.clock.now())

    def on_tick(self, price: float, event_at: float, received_at: float) -> None:
        received_mono = self.monotonic()
        if not -FUTURE_SKEW_S <= received_at - event_at <= self.desk.config.stale_s:
            return
        previous = self.desk.tape.revision
        self.desk.tick_btc(price, event_at)
        # BitcoinTape counts accepted ticks, including same-second revisions.
        # Rejected ticks do not dirty the sigma cache or publish an opening
        # that the model never accepted.
        if self.desk.tape.revision != previous:
            self.tick_receipt = TickReceipt(event_at, received_at, received_mono)
            self._bitcoin_revision += 1
            if int(event_at) in self._live_opening_seconds:
                self._live_windows_dirty = True
        self._refresh_live_snapshot()
        self._live_call("on_tick", price, event_at, received_at)
        daily = self.feed_latency.setdefault(utc_day(received_at), [0.0, 0.0])
        daily[0] += (received_at - event_at) * 1000
        daily[1] += 1
        for window in self.desk.windows.values():
            if window.start_price is not None and window.slug not in self.opening_logged:
                self.opening_logged.add(window.slug)
                self.record("speeddesk_opening", {"window": window.slug, "at": received_at,
                                                 "start_price": window.start_price,
                                                 "opening_source": ("venue strike" if window.venue == "kalshi"
                                                                    else "coinbase"),
                                                 "coinbase_start_price": self.desk.tape.opening(window.start),
                                                 "venue_start_price": window.venue_start_price,
                                                 "settlement_source": "venue BRTI outcome"})

    def on_book(self, book: Book) -> None:
        # Optional measurement sees rejected quotes too; it never changes the accepted trading snapshot.
        try:
            observer = getattr(self.live, "observe_book", None)
            if observer is not None:
                observer(book)
        except Exception:  # noqa: BLE001 - a diagnostic must never interrupt the production feed.
            log.warning("speeddesk_fill_markout_callback_failed")
        if self.desk.on_book(book):
            self._refresh_live_snapshot()
            self._live_call("on_book", book)
            if self.arena is not None and book.window in self._live_slugs:
                self.arena.feed_book(book)  # one bounded append (practice town, sent at the next step)
            # Resolve the first eligible post-delay snapshot immediately. A
            # later favorable update may never replace a failed recheck.
            self.decisions(self.desk.advance(self.clock.now()))

    def on_trade(self, trade: Trade) -> None:
        allowed = not hasattr(self.feeds, "maker_windows") or trade.window in self.feeds.maker_windows()
        if self.feed_status.get("trade_stream") and allowed:
            self.decisions(self.desk.on_trade(trade, self.clock.now()))
            self._live_call("on_trade", trade)
            if self.arena is not None and trade.window in self._live_slugs:
                self.arena.feed_trade(trade)  # one bounded append (practice town, sent at the next step)

    def on_windows(self, windows: list[Window]) -> None:
        self.evidence.discover([asdict(window) for window in windows], self.clock.now())
        self._live_windows_dirty = True
        for window in windows:
            previous = self.desk.windows.get(window.slug)
            terms = ("taker_coefficient", "maker_coefficient", "tick_size", "min_trade_qty", "fee_rounding")
            if previous is not None and any(getattr(previous, key) != getattr(window, key) for key in terms):
                self._live_market_snapshot = replace(self._live_market_snapshot, books={}, maker_windows=frozenset())
                self.decisions(self.desk.cancel(self.clock.now(), window.slug, "venue_terms_changed"))
                self.desk.books = {key: book for key, book in self.desk.books.items() if key[0] != window.slug}
            self.desk.add_window(window)
        self._refresh_live_snapshot()
        self._live_call("on_windows", windows)

    def on_status(self, status: dict[str, Any]) -> None:
        if status.get("coinbase") != "connected" or not status.get("trade_stream"):
            self.evidence.last_fresh.clear()
        self.evidence.last_fresh.difference_update(status.get("gap_windows", []))
        old = self.feed_status
        self.feed_status = status
        if (status.get("gap_windows") or (old.get("trade_stream") and not status.get("trade_stream"))
                or (old.get("coinbase") == "connected" and status.get("coinbase") != "connected")):
            # Invalidate before a checkpoint releases the GIL to a pending HTTP
            # send guard. Known disconnects cannot borrow the previous book.
            self._live_market_snapshot = replace(self._live_market_snapshot, books={}, maker_windows=frozenset())
        if ((old.get("trade_stream") and not status.get("trade_stream"))
                or (old.get("coinbase") == "connected" and status.get("coinbase") != "connected")):
            self.decisions(self.desk.cancel(self.clock.now(), reason="feed_gap"))
            self.desk.books.clear()
        else:
            for slug in status.get("gap_windows", []):
                self.decisions(self.desk.cancel(self.clock.now(), slug, "venue_feed_gap"))
                self.desk.books = {key: book for key, book in self.desk.books.items() if key[0] != slug}
        self._refresh_live_snapshot()
        self._live_call("on_status", status)
        if self.arena is not None:  # rare; the practice town applies the same gap rule in its own process
            self.arena.feed_gap(tuple(status.get("gap_windows", ())), bool(status.get("trade_stream")),
                                status.get("coinbase") == "connected")

    def summary(self, day: str, venue: str | None = None) -> dict[str, Any]:
        report = self.desk.daily_summary(day, venue=venue)
        latency = self.feed_latency.get(day, [0.0, 0.0])
        report.update(observed_seconds=self.observed.get(day, 0.0),
                      avg_bitcoin_feed_latency_ms=latency[0] / latency[1] if latency[1] else None,
                      bitcoin_feed_latency_scope="shared Coinbase feed",
                      latency_definition="decision to simulated fill; maker includes resting time")
        for prefix in ("take", "maker"):
            attempts = report["take_attempts" if prefix == "take" else "maker_orders"]
            fills = report[f"{prefix}_fills"]
            report[f"{prefix}_fill_rate_pct"] = 100 * fills / attempts if attempts and fills is not None else None
        if venue is None:
            report["venues"] = {name: self.summary(day, name) for name in VENUES}
        else:
            report["latency"] = self.metrics.report(day, venue)
            windows = [asdict(window) for window in self.desk.windows.values()
                       if window.venue == venue and window.end <= self.clock.now()]
            report["scorecard"] = window_scorecard(
                day, windows=windows, fills=self.evidence.fills, settlements=[asdict(row) for row in self.desk.closed],
                coverage=self.evidence.coverage(windows), scope="practice", as_of=self.clock.now(),
                day_coverage_complete=self.evidence.complete_kalshi_day(day, windows, self.clock.now())
                if venue == "kalshi" else False)
            report["scorecard"].update(self.evidence.availability(
                [window for window in windows if utc_day(window["end"]) == day]))
            if day < utc_day(self.clock.now() - 30 * 86400):
                # Detailed evidence is bounded; preserve an already published
                # older report instead of revising known history into no data.
                previous = self.reports.get(day, {}).get("venues", {}).get(venue, {})
                for key in ("latency", "scorecard"):
                    if key in previous:
                        report[key] = previous[key]
            coverage = self.venue_coverage.get(day, {}).get(venue, {})
            # No backfilling coverage from combined uptime on upgrade.
            predates_coverage = day < utc_day(self.venue_reporting_started_at)
            fresh = None if predates_coverage else coverage.get("fresh_data_seconds", 0.0)
            report.update(venue=venue, enabled=venue in self.enabled_venues if day == utc_day(self.clock.now()) else None,
                          reporting_started_at=self.venue_reporting_started_at,
                          coverage_started_at=self.venue_reporting_started_at,
                          fresh_data_seconds=fresh,
                          maker_data_seconds=None if predates_coverage else coverage.get("maker_data_seconds", 0.0),
                          partial_day=fresh is None or fresh < 86395,
                          coverage_definition="fresh Bitcoin and both books of at least one active venue window; "
                          "maker coverage also requires its verified trade stream; warm-up is included")
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
            else:
                venues = {venue: self.summary(key, venue) for venue in VENUES}
                if self.reports[key].get("venues") != venues:
                    # A carry-over order's first fill updates its placement-day
                    # fill-rate cohort without moving execution P&L across days.
                    self.reports[key]["venues"] = venues
                    self.reports[key]["revised_at"] = now
                    self.record("speeddesk_daily_correction", self.reports[key])
            day += timedelta(days=1)

    def panel(self, now: float) -> dict[str, Any]:
        btc_at = self.desk.tape.last_at
        books = [book.at for book in self.desk.books.values()
                 if book.window in self.desk.windows and self.desk.windows[book.window].start <= now
                 < self.desk.windows[book.window].end]
        warm = self.desk.tape.sigma(now, self.desk.config.sigma_min_samples) is None
        last_complete = int(now) - 1
        samples = sum(second in self.desk.tape.prices and second - 1 in self.desk.tape.prices
                      for second in range(last_complete - 3599, last_complete + 1))
        status = "Warming up Bitcoin volatility" if warm else "Practice feeds running"
        if warm:
            status += f" ({samples:,}/{self.desk.config.sigma_min_samples:,} observed one-second returns)"
        if btc_at is None or not -FUTURE_SKEW_S <= now - btc_at <= self.desk.config.stale_s:
            status = "Practice paused: Bitcoin feed stale"
        elif not books or now - max(books) > self.desk.config.stale_s:
            status = "Practice paused: waiting for fresh books"
        elif now - min(books) > self.desk.config.stale_s:
            status += "; some venue books are stale"
        if not self.feed_status.get("trade_stream"):
            status += "; trade stream unavailable, maker fills disabled"
        return {"mode": "paper", "as_of": now, "started_at": self.started_at,
                "status": status, "problem": self.problem,
                "btc_age_s": max(0.0, now - btc_at) if btc_at is not None else None,
                "book_age_s": max(0.0, now - min(books)) if books else None,
                "volatility": {"source": "observed one-second Coinbase returns", "samples": samples,
                               "required_samples": self.desk.config.sigma_min_samples, "ready": not warm,
                               "required_elapsed_s": self.desk.config.sigma_warmup_s},
                "today": self.summary(utc_day(now)), "reports": self.reports,
                "feeds": self.feed_status, "window_reasons": dict(self.desk.last_reason),
                "real_orders_available": False, "kalshi_live": self.live_panel(now)}

    def live_snapshot(self) -> LiveSnapshot:
        """Return an atomic market view, including from the HTTP worker thread."""
        return self._live_market_snapshot

    def _live_sigma(self, now: float) -> float | None:
        """Cache only unchanged mathematical inputs; price/book freshness is never cached.

        ``sigma`` uses completed seconds but its elapsed warm-up can cross in
        the middle of one second. The predicate is therefore part of the key,
        alongside the completed second, both settings and the number of
        accepted ticks in completed seconds (speed plan step 3: the key held
        every accepted tick, so each Bitcoin trade recomputed the hour; a tick
        in the current second cannot change it, a late one stamped in a
        completed second does). The tape and its dictionaries are compared by
        identity too, so a restored/replaced tape never reuses a result.
        """
        tape, config = self.desk.tape, self.desk.config
        warmed = tape.started_at is not None and now - tape.started_at >= config.sigma_warmup_s
        completed = tape.completed_revision(now)
        key = (completed, int(now) - 1, config.sigma_min_samples, config.sigma_warmup_s, tape.started_at, warmed)
        if (completed is None or key != self._sigma_key or tape is not self._sigma_tape
                or tape.prices is not self._sigma_prices):
            value = tape.sigma(now, config.sigma_min_samples, config.sigma_warmup_s)
            self._sigma_key, self._sigma_tape, self._sigma_prices = key, tape, tape.prices
            self._sigma_value = value
        return self._sigma_value

    def _refresh_live_windows(self) -> None:
        # The model mutates an opening on its first accepted Bitcoin tick in
        # that second; all other venue terms arrive through on_windows. Copies
        # remain independent of the model and earlier worker-thread snapshots.
        self._live_windows = tuple(replace(window) for window in self.desk.windows.values() if window.venue == "kalshi")
        self._live_slugs = frozenset(window.slug for window in self._live_windows)
        self._live_opening_seconds = {int(window.start) for window in self._live_windows
                                     if window.start_price is None and math.isfinite(window.start)}
        self._live_windows_generation += 1
        self._live_windows_dirty = False

    def _refresh_live_snapshot(self) -> None:
        """Publish on the event loop; never mix a previous price with a new timestamp."""
        now = self.clock.now()
        if self._live_windows_dirty:
            self._refresh_live_windows()
        slugs = self._live_slugs
        outcome_key = (id(self.desk.closed), len(self.desk.closed), self._live_windows_generation)
        if outcome_key != self._live_outcome_key:
            self._live_outcomes = {item.window: item.up_wins for item in self.desk.closed if item.window in slugs}
            self._live_outcome_key = outcome_key
        maker_windows = self.feeds.maker_windows() if hasattr(self.feeds, "maker_windows") else set()
        self._live_market_snapshot = LiveSnapshot(windows=self._live_windows,
                            books={key: book for key, book in self.desk.books.items() if key[0] in slugs},
                            bitcoin_price=self.desk.tape.price, bitcoin_at=self.desk.tape.last_at,
                            sigma=self._live_sigma(now),
                            maker_windows=frozenset(maker_windows & slugs),
                            outcomes=self._live_outcomes, tick_receipt=self.tick_receipt)

    def live_panel(self, now: float) -> dict[str, Any]:
        current = self._live_call("panel")
        if isinstance(current, dict):
            self.last_live_panel = dict(current)
        panel = dict(self.last_live_panel)
        if self.live_problem is not None or self.live is None:
            # Failure cannot turn unverified actual exposure into pretend zero.
            panel.update(as_of=now, mode="paper", authenticated=False, real_orders_available=False,
                         reason=self.live_problem or "Kalshi companion unavailable", exposure_unknown=True)
        return panel

    def _live_call(self, method: str, *args: Any) -> Any:
        if self.live is None or self.live_problem is not None:
            return None
        try:
            return getattr(self.live, method)(*args)
        except Exception as exc:  # noqa: BLE001 — companion callbacks cannot stop the public practice trial.
            self.live_problem = "Kalshi companion halted; real exposure unknown; inspect live logs"
            # Close the last-moment send gate immediately, before async cleanup.
            self.live.stopping = True
            log.error("speeddesk_live_status mode=paper reason=callback_failed error=%s", type(exc).__name__)
            if self.live_started and self.live_task is not None and not self.live_task.done():
                self.live_task.cancel()
            return None

    async def _run_live(self) -> None:
        assert self.live is not None
        self.live_started = True
        try:
            if self.live_problem is not None:
                return
            await self.live.run(self.stop)
            if not self.stop.is_set():
                raise RuntimeError("Kalshi companion exited before shutdown")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — preserve the public practice trial after a companion fault.
            self.live_problem = "Kalshi companion halted; new real orders disabled; inspect live logs"
            log.error("speeddesk_live_status mode=paper reason=companion_halted error=%s", type(exc).__name__)
        finally:
            try:
                await self.live.shutdown()
            except Exception as exc:  # noqa: BLE001 — retain reservations and show cleanup uncertainty.
                self.live_problem = "Kalshi cleanup unconfirmed; real exposure may remain; inspect live logs"
                log.error("speeddesk_live_status mode=paper reason=cleanup_unconfirmed error=%s", type(exc).__name__)

    def checkpoint(self, now: float) -> None:
        self.daily_reports(now)
        state = {"version": 1, "mode": "practice", "started_at": self.started_at, "updated_at": now,
                 "model": self.desk.to_state(), "reports": self.reports, "observed_seconds": self.observed,
                 "feed_latency": self.feed_latency, "opening_logged": sorted(self.opening_logged),
                 "latency_metrics": self.metrics.state(),
                 "window_evidence": self.evidence.state(),
                 "venue_reporting_started_at": self.venue_reporting_started_at,
                 "venue_coverage": self.venue_coverage,
                 "panel": self.panel(now)}
        first = not self._first_save_synced
        if first:
            self.ledger.set_synchronous(True)  # the ledger state is on disk before the display copy can be
        with self.ledger.transaction():
            for kind, payload in self.pending:
                self.ledger.append_receipt(kind, payload, ts=payload.get("at", now))
            self.ledger.set_kv(STATE_KEY, state)
        if first:
            self.ledger.set_synchronous(False)
            self._first_save_synced = True
        for kind, payload in self.pending:
            log.info("%s %s", kind, json.dumps(payload, allow_nan=False, separators=(",", ":")))
        self.pending.clear()
        # A mirror failure halts practice, but the committed ledger survives it. A display copy: not synced.
        _atomic_json(self.path, state, durable=False)
        self.last_checkpoint = now

    def step(self, now: float) -> None:
        self._refresh_live_snapshot()
        windows = [asdict(window) for window in self.desk.windows.values()]
        makers = self.feeds.maker_windows() if hasattr(self.feeds, "maker_windows") else set()
        if not self.feed_status.get("trade_stream"):
            makers = set()
        self.evidence.advance(now, windows, fresh_window_slugs(windows, self.desk.books,
                                                              self.desk.tape.last_at, makers, now))
        # Public observation cadence is independent of slower account reads.
        # This report-only callback performs no trading or private I/O.
        if self.live is not None and hasattr(self.live, "observe_market"):
            self._live_call("observe_market", now)
        # Count observed runtime, never claim coverage for offline gaps.
        duration = max(0.0, min(1.0, now - self.last_step))
        interval_start = now - duration
        maker_windows = self.feeds.maker_windows() if hasattr(self.feeds, "maker_windows") else None
        fresh, maker = self._coverage_windows(now, maker_windows)
        interval_fresh = fresh & self.last_fresh_venues
        interval_maker = maker & self.last_maker_venues
        # Split the small observed interval at UTC midnight rather than moving
        # yesterday's final fraction into today's report.
        while interval_start < now:
            day = utc_day(interval_start)
            midnight = datetime.combine(datetime.fromtimestamp(interval_start, UTC).date() + timedelta(days=1),
                                        datetime.min.time(), UTC).timestamp()
            end = min(now, midnight)
            elapsed = end - interval_start
            self.observed[day] = self.observed.get(day, 0.0) + elapsed
            for venue in self.enabled_venues:
                coverage = self.venue_coverage.setdefault(day, {}).setdefault(venue, {})
                for key, active in (("fresh_data_seconds", interval_fresh), ("maker_data_seconds", interval_maker)):
                    if venue in active:
                        coverage[key] = coverage.get(key, 0.0) + elapsed
            interval_start = end
        self.last_step = now
        self.last_fresh_venues, self.last_maker_venues = fresh, maker
        self.decisions(self.desk.evaluate(now, makers_enabled=bool(self.feed_status.get("trade_stream")),
                                          maker_windows=maker_windows))
        if now - self.last_heartbeat >= 60:
            heartbeat = self.panel(now)
            # Completed reports already have daily receipts and remain in the
            # page state. Do not duplicate a growing trial history every minute.
            heartbeat.pop("reports")
            self.record("speeddesk_status", heartbeat)
            self.last_heartbeat = now
        if self.pending or now - self.last_checkpoint >= 5:
            self.checkpoint(now)
        if self.arena is not None:
            # One frame to the practice town: what arrived since the last step plus the market facts that changed;
            # a non-blocking write that drops (and counts) when the town is behind, and never raises.
            self.arena.flush(self._live_market_snapshot)

    def _coverage_windows(self, now: float, maker_windows: set[str] | None) -> tuple[set[str], set[str]]:
        fresh: set[str] = set()
        maker: set[str] = set()
        btc_at = self.desk.tape.last_at
        if btc_at is None or not -FUTURE_SKEW_S <= now - btc_at <= self.desk.config.stale_s:
            return fresh, maker
        for window in self.desk.windows.values():
            if window.venue not in self.enabled_venues or not window.start <= now < window.end:
                continue
            books = [self.desk.books.get((window.slug, side)) for side in ("up", "down")]
            if not all(book is not None and 0 <= now - book.at <= self.desk.config.stale_s for book in books):
                continue
            if any(book is not None and (
                (book.source == "rest" and book.requested_at is not None
                 and not 0 <= book.at - book.requested_at <= self.desk.config.stale_s)
                or (book.source != "rest" and book.exchange_at is not None
                    and not 0 <= now - book.exchange_at <= self.desk.config.stale_s)
            ) for book in books):
                continue
            fresh.add(window.venue)
            if self.feed_status.get("trade_stream") and (maker_windows is None or window.slug in maker_windows):
                maker.add(window.venue)
        return fresh, maker

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
                if window.venue == "kalshi":
                    self._live_call("on_settlement", window.slug, outcome == 1.0, now)
                self.decisions(self.desk.cancel(now, window.slug, "settled"))
                result = self.desk.settle(window.slug, outcome == 1.0, now)
                self._refresh_live_snapshot()
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
                                          "trial_started_at": self.started_at,
                                          "config": config_state(self.desk.config)})
        self.checkpoint(self.clock.now())
        if self.arena is not None:
            try:
                self.arena.start()  # its own process; it ends when the link closes (or this process dies)
            except Exception as exc:  # noqa: BLE001 — a practice town never stops the speed desk.
                log.warning("kalshi_arena_not_started error=%s", type(exc).__name__)
                self.arena = None
        tasks = [asyncio.create_task(self.feeds.run(self.stop)), asyncio.create_task(self._settlements())]
        self.live_task = asyncio.create_task(self._run_live()) if self.live is not None else None
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
            if self.live_task is not None:
                if not self.stop.is_set() and not self.live_task.done():
                    self.live_task.cancel()
                await asyncio.gather(self.live_task, return_exceptions=True)
            self.decisions(self.desk.cancel(self.clock.now(), reason="shutdown"))
            self.checkpoint(self.clock.now())
            self._close_arena()  # after every real-money shutdown step; never waits

    def _close_arena(self, wait_s: float = 0.0) -> None:
        if self.arena is not None:
            try:
                self.arena.close(wait_s)
            except Exception as exc:  # noqa: BLE001 — a practice town never stops the speed desk.
                log.warning("kalshi_arena_close_failed error=%s", type(exc).__name__)

    def close(self) -> None:
        try:
            if self.live is not None:
                self.live.close()
        finally:
            try:
                # Last, after the live companion closed: a moment for the town's final save (this process may be
                # the container's first, whose exit ends every other process in it).
                self._close_arena(ARENA_EXIT_WAIT_S)
            finally:
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

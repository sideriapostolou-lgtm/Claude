"""Kalshi execution companion with a durable, independent real-fill ledger.

Public paper operation never constructs an account client. A prior live run
may need a read/cancel-only recovery client after the owner switches to paper;
that narrow client deliberately has no order-creation method.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import math
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from .config import Secret, Settings
from .ledger import Ledger
from .speeddesk_kalshi_client import KalshiClient, KalshiClientError
from .speeddesk_live_model import (
    LOCK_MARGIN_S,
    WINDOW_PARTS,
    ActualFill,
    LiveLimits,
    LiveRejected,
    LiveRiskBook,
    OrderSnapshot,
    without_default_lock,
)
from .speeddesk_metrics import (
    LatencyMetrics,
    TickReceipt,
    WindowEvidence,
    fresh_window_slugs,
)
from .speeddesk_model import (
    Book,
    PracticeDesk,
    Side,
    SpeedConfig,
    Trade,
    Window,
    fair_up,
    utc_day,
)
from .speeddesk_scorecard import window_scorecard

log = logging.getLogger("nightcrawler.speeddesk")
PREFIX = "nc-speed-"
STATE_KEY = "kalshi_live_state"
EPS = 1e-8
# How long Kalshi's order list may trail its fills list before the mismatch stops real orders for good
# (seen trailing by under a second on 2026-10-13; every read in between counts as not yet reconciled).
ORDER_LIST_LAG_S = 30.0
# The live loop steps on each Bitcoin tick or book change, at most every MIN_STEP_S, and at least every IDLE_STEP_S.
MIN_STEP_S, IDLE_STEP_S = 0.02, 0.25
# A window an hour past its close, settled and with nothing open, moves once into a write-once archive chunk
# (ledger key ARCHIVE_KEY + sequence). Every save rewrote every order ever made: 206 ms per save on Railway by
# 2026-10-13 13:45 UTC, about 87 us more per stored order, several saves a second, all on the event loop.
ARCHIVE_KEY, ARCHIVE_AFTER_S = "kalshi_live_archive/", 3600.0
# The money page rebuilds and checks the whole real book from state.json (FRESH_SECONDS = 60 there): it gets every
# window, archived ones from memory, at most every MIRROR_EVERY_S. A display copy, so no fsync; the ledger is durable.
MIRROR_EVERY_S = 10.0
# Saves that must survive a host or power failure, not only a process crash: the one before an order's first
# network byte, startup and shutdown, and any that record an owner's one-time action. The others (a fsync of
# about 57 ms each on Railway, twice a second in reconcile) hold account facts the next reconcile reads again.
OWNER_RECORDS = frozenset({"speeddesk_live_day_reset", "speeddesk_live_integrity_reset"})


@dataclass(frozen=True)
class LiveSnapshot:
    windows: tuple[Window, ...] = ()
    books: dict[tuple[str, Side], Book] = field(default_factory=dict)
    bitcoin_price: float | None = None
    bitcoin_at: float | None = None
    sigma: float | None = None
    maker_windows: frozenset[str] = frozenset()
    outcomes: dict[str, bool] = field(default_factory=dict)
    tick_receipt: TickReceipt | None = None


@dataclass
class Intent:
    client_order_id: str
    window: str
    side: Side
    kind: Literal["take", "rest"]
    price: float
    size: float
    fair: float
    at: float
    order_id: str = ""
    terminal: bool = False
    uncertain: bool = False
    cancel_requested: bool = False
    twin_order_id: int = 0
    lock: bool = False


class _Clock:
    def __init__(self, now: Callable[[], float]) -> None:
        self.now = now


class _RecoveryClient:
    """Only account reconciliation and cancellation are available in recovery."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def balance(self) -> dict[str, Any]:
        return self._client.balance()  # type: ignore[no-any-return]

    def list_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._client.list_orders(**kwargs)  # type: ignore[no-any-return]

    def fills(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._client.fills(**kwargs)  # type: ignore[no-any-return]

    def positions(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._client.positions(**kwargs)  # type: ignore[no-any-return]

    def settlements(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._client.settlements(**kwargs)  # type: ignore[no-any-return]

    def subaccount_balances(self) -> list[dict[str, Any]]:
        return self._client.subaccount_balances()  # type: ignore[no-any-return]

    def cancel(self, order_id: str, *, ticker: str) -> dict[str, Any]:
        return self._client.cancel(order_id, ticker=ticker)  # type: ignore[no-any-return]

    def close(self) -> None:
        self._client.close()


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("Boolean is not a monetary amount")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite account value")
    return number


def _stamp(value: Any) -> float:
    if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
        moment = datetime.fromisoformat(value)
        if moment.utcoffset() is None:
            raise ValueError("Venue timestamp must include its UTC offset")
        return moment.timestamp()
    return _number(value)


def _secret(value: Secret | str | None) -> str:
    return value.reveal() if isinstance(value, Secret) else value or ""


class KalshiLiveDesk:
    """One serialized controller; network work never blocks the Bitcoin feed."""

    def __init__(self, settings: Settings, directory: Path, snapshot: Callable[[], LiveSnapshot], *,
                 clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic,
                 client_factory: Callable[[], Any] | None = None,
                 direct_member_verified: bool = False) -> None:
        self.settings, self.directory, self.snapshot, self.clock = settings, directory, snapshot, clock
        self.monotonic = monotonic
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock_stream = (directory / "controller.lock").open("a", encoding="utf-8")
        try:
            fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_stream.close()
            raise RuntimeError("Another Kalshi companion already holds the account ledger lock") from None
        self.path = directory / "state.json"
        self.ledger = Ledger(directory / "receipts.db", _Clock(clock))
        self.client_factory = client_factory or self._default_client
        self.client: Any = None
        self.authenticated = False
        self.auth_failed = False
        # This is an externally established fact, never inferred from a key's
        # algorithm, account cash, or the primary subaccount every user has.
        self.fee_verified = direct_member_verified
        self.stopping = False
        self.stop_event: threading.Event | None = None
        self.shutdown_done = False
        self._workers: set[asyncio.Task[Any]] = set()
        self.startup_done = False
        self.closed = False
        self.account_at: float | None = None
        # Set by every accepted Bitcoin tick and Kalshi book change: the loop decides at once instead of on a timer.
        self.wake = asyncio.Event()
        self.cash_usd: float | None = None
        self.cash_at: float | None = None
        self.last_sync = -math.inf
        self.last_status = -math.inf
        self.last_checkpoint = -math.inf
        self.save_ms: float | None = None
        self.save_stages: dict[str, float | None] = {}
        self.retry_at = -math.inf
        self.cancel_retry_at: dict[str, float] = {}
        self.errors = 0
        # Definite single-order refusals since the last accepted create; three in a row pause.
        self.refusals = 0
        self.lock_notes: dict[str, str] = {}
        self.reason: str | None = "Practice only; live switches are off"
        self.foreign_windows: set[str] = set()
        self.changed_windows: set[str] = set()
        self.position_sizes: dict[str, float] = {}
        self.final_outcomes: dict[str, bool] = {}
        self.latest_events: list[dict[str, Any]] = []
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.fatal_reason: str | None = None
        # Which reconciliation check stopped real orders, logged once per stop (and once after each restart).
        self.integrity_logged: str | None = None
        # What the owner's approved one-time reset of that stop is waiting for (each reason logged once).
        self.reset_blocker = ""
        self.reset_reported: set[str] = set()
        # When each order's Kalshi report was first seen trailing its booked fills (ORDER_LIST_LAG_S).
        self.order_list_lag: dict[str, float] = {}
        limits = LiveLimits(window_usd=settings.speeddesk_kalshi_window_usd,
                            open_usd=settings.speeddesk_kalshi_open_usd,
                            day_loss_usd=settings.speeddesk_kalshi_day_stop_usd,
                            total_loss_usd=settings.speeddesk_kalshi_total_stop_usd,
                            pair_cap=settings.speeddesk_pair_cap,
                            max_imbalance=settings.speeddesk_max_imbalance,
                            clip=settings.speeddesk_clip, cutoff_s=settings.speeddesk_kalshi_cutoff_s,
                            lock_s=settings.speeddesk_kalshi_lock_s,
                            lock_max_price=settings.speeddesk_kalshi_lock_max_price,
                            fee_precision=0.0001 if direct_member_verified else 0.01)
        twin_config = SpeedConfig(window_usd=limits.window_usd, open_usd=limits.open_usd,
                                  day_stop_usd=limits.day_loss_usd, cutoff_s=settings.speeddesk_kalshi_cutoff_s,
                                  take_edge=settings.speeddesk_take_edge, make_edge=settings.speeddesk_make_edge,
                                  pair_cap=limits.pair_cap, max_imbalance=limits.max_imbalance,
                                  clip=limits.clip, latency_ms=settings.speeddesk_latency_ms)
        try:
            if self.ledger.verify_chain()[0] is not True:
                raise ValueError("Real receipt ledger hash chain is invalid")
            saved = self.ledger.get_kv(STATE_KEY)
            self.archived: set[str] = set()
            self.archive_chunks = 0
            self.archive_parts: dict[str, dict[str, Any]] = {part: {} for part in (*WINDOW_PARTS, "live_intents")}
            self.last_mirror = -math.inf
            if saved is None and self.path.exists():
                raise ValueError("Real receipt ledger missing beside existing state")
            if saved is None:
                self.book = LiveRiskBook(limits)
                self.intents: dict[str, Intent] = {}
                self.twin = PracticeDesk(twin_config)
                self.started_at = clock()
            else:
                if saved.get("version") != 1:
                    raise ValueError("Unsupported real receipt ledger version")
                self._merge_archive(saved)
                self.book = LiveRiskBook.from_state(saved["book"], limits)
                self.intents = {key: Intent(**item) for key, item in saved["intents"].items()}
                if set(self.intents) != set(self.book.intents):
                    raise ValueError("Real intent journal does not match reserved liabilities")
                for key, intent in self.intents.items():
                    reserved = self.book.intents[key]
                    if (key != intent.client_order_id or intent.window != reserved.window
                            or intent.side != reserved.side or intent.kind != reserved.kind
                            or intent.price != reserved.price or intent.size != reserved.size
                            or (intent.order_id or None) != reserved.order_id
                            or any(not isinstance(value, bool) for value in
                                   (intent.terminal, intent.uncertain, intent.cancel_requested))
                            or intent.terminal and reserved.reservation_active):
                        raise ValueError("Real intent journal changed its reserved terms")
                self.twin = PracticeDesk.from_state(saved["twin"], twin_config)
                self.started_at = float(saved["started_at"])
                self.fatal_reason = saved.get("fatal_reason")
                self.foreign_windows = set(saved.get("foreign_windows", []))
                self.changed_windows = set(saved.get("changed_windows", []))
                self.final_outcomes = saved.get("final_outcomes", {})
                self.latest_events = saved.get("latest_events", [])[-20:]
            self.metrics = LatencyMetrics(clock(), saved.get("latency_metrics") if saved else None)
            self.evidence = WindowEvidence(clock(), saved.get("window_evidence") if saved else None)
            self.reports: dict[str, dict[str, Any]] = dict(saved.get("reports", {})) if saved else {}
            token = _secret(settings.speeddesk_kalshi_resume_token)
            if token:
                self.book.apply_resume_token(token)
            outcome = self.book.arm_integrity_reset(_secret(settings.speeddesk_kalshi_integrity_reset_token))
            if outcome == "armed":
                self._record("speeddesk_live_integrity_reset", code=self.book.integrity_reset_armed,
                             state="armed; clears only after a clean Kalshi reconcile with nothing open")
            elif outcome == "no_stop":
                self._record("speeddesk_live_integrity_reset", state="ignored; no stop to clear, so the value is spent")
            elif outcome == "used" and self.book.integrity_reset_armed is None:
                self._record("speeddesk_live_integrity_reset", code=self.book.integrity_error,
                             state="ignored; this value was already used")
            reset_at = clock()
            day_reset = self.book.apply_day_reset(_secret(settings.speeddesk_kalshi_day_reset_token), reset_at)
            if day_reset == "reset":
                self._record("speeddesk_live_day_reset", day=utc_day(reset_at),
                             counted_from_usd=self.book.day_anchor[utc_day(reset_at)],
                             state="fresh daily budget from now until 00:00 UTC; caps and lifetime stop unchanged")
            elif day_reset == "used":
                self._record("speeddesk_live_day_reset", state="ignored; this value was already used")
            self.checkpoint(durable=True)
        except BaseException:
            self.ledger.close()
            self._lock_stream.close()
            raise

    def _default_client(self) -> KalshiClient:
        assert self.settings.kalshi_key_id is not None and self.settings.kalshi_private_key is not None
        return KalshiClient(self.settings.kalshi_key_id, self.settings.kalshi_private_key)

    def _gates(self) -> str:
        if not self.settings.speeddesk_enabled or not self.settings.speeddesk_kalshi_enabled:
            return "Practice only; Kalshi speed desk is disabled"
        if self.settings.speeddesk_kalshi_mode != "live":
            return "Practice only; live mode is off"
        if _secret(self.settings.speeddesk_kalshi_live_confirm) != "yes":
            return "Practice only; live confirmation is missing"
        if not self.settings.kalshi_key_id or not self.settings.kalshi_private_key:
            return "Practice only; Kalshi credentials are missing"
        if self.auth_failed:
            return "Practice only; Kalshi authentication failed this run"
        return ""

    def _active(self) -> list[Intent]:
        return [intent for intent in self.intents.values() if not intent.terminal]

    def _record(self, receipt_kind: str, **payload: Any) -> None:
        item = {"at": self.clock(), "venue": "kalshi", **payload}
        self.pending.append((receipt_kind, item))
        if receipt_kind != "speeddesk_live_status":
            self.latest_events.append({"event": receipt_kind, **item})
            self.latest_events = self.latest_events[-20:]

    async def _io(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        task = asyncio.create_task(asyncio.to_thread(callback, *args, **kwargs))
        self._workers.add(task)
        task.add_done_callback(self._workers.discard)
        return await asyncio.shield(task)

    async def _read(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        result = await self._io(callback, *args, **kwargs)
        # Serialize all accounting mutations, but give cancellations priority
        # between each private read instead of waiting for every account page.
        await self._cancel_unsafe()
        return result

    def _merge_archive(self, saved: dict[str, Any]) -> None:
        """Restore archived windows under the saved state, so restore and its checks see the full books."""
        chunks, listed = saved.get("archive_chunks", 0), saved.get("archived_windows", [])
        if (not isinstance(chunks, int) or isinstance(chunks, bool) or chunks < 0 or not isinstance(listed, list)
                or not all(isinstance(item, str) for item in listed)):
            raise ValueError("Invalid real archive index")
        archived: set[str] = set()
        merged: dict[str, dict[str, Any]] = {part: {} for part in (*WINDOW_PARTS, "live_intents")}
        for seq in range(chunks):
            chunk = self.ledger.get_kv(f"{ARCHIVE_KEY}{seq}")
            if not isinstance(chunk, dict) or chunk.get("version") != 1:
                raise ValueError("Real archive chunk missing or unsupported")
            windows = set(chunk["windows"])
            book_parts, intents = chunk["book"], chunk["intents"]
            if (set(book_parts) != set(WINDOW_PARTS)
                    or not set(book_parts["windows"]) <= windows or not set(book_parts["inventory"]) <= windows
                    or not set(book_parts["settled"]) <= windows
                    or any(row["window"] not in windows for part in ("intents", "fills")
                           for row in book_parts[part].values())
                    or any(row["window"] not in windows for row in intents.values())):
                raise ValueError("Real archive chunk does not match its windows")
            archived |= windows
            # A window archived again after activity came back is newer in the later chunk: it wins.
            for part in WINDOW_PARTS:
                merged[part].update(book_parts[part])
            merged["live_intents"].update(intents)
        # Windows the index no longer lists were reopened: the saved state holds their newer full copy.
        if not set(listed) <= archived or not archived - set(listed) <= set(saved["book"]["windows"]):
            raise ValueError("Real archive index does not match its chunks")
        for part in WINDOW_PARTS:
            saved["book"][part] = {**merged[part], **saved["book"][part]}
        saved["intents"] = {**merged["live_intents"], **saved["intents"]}
        self.archived, self.archive_chunks, self.archive_parts = set(listed), chunks, merged

    def _live_windows(self) -> set[str]:
        """Windows with anything that can still change: a reservation or an unfinished or uncertain order."""
        # A finished order keeps cancel_requested once a cancel was sent; it no longer makes its window live.
        return ({item.window for item in self.book.intents.values() if item.reservation_active}
                | {item.window for item in self.intents.values() if not item.terminal or item.uncertain})

    def _cold_windows(self, now: float, live: set[str]) -> set[str]:
        traded = {item.window for item in self.book.intents.values()} | {fill.window for fill in self.book.fills.values()}
        return {slug for slug, window in self.book.windows.items()
                if slug not in self.archived and slug not in live and window.end <= now - ARCHIVE_AFTER_S
                and (slug in self.book.settled or slug not in traded)}

    def checkpoint(self, durable: bool = False) -> None:
        started = time.perf_counter()
        withdrawn = self.book.disarm_stale_reset()
        if withdrawn:
            self._record("speeddesk_live_integrity_reset", code=self.book.integrity_error, previous=withdrawn,
                         state="disarmed; a different check tripped after the reset was approved")
            self.reset_blocker = ""
        if self.book.integrity_error and self.book.integrity_error != self.integrity_logged:
            self.integrity_logged = self.book.integrity_error
            self._record("speeddesk_live_integrity", code=self.book.integrity_error,
                         state="real orders stopped until the books and Kalshi are reconciled")
        for key, intent in self.intents.items():
            if intent.terminal and self.book.intents[key].reservation_active:
                # A contradictory venue fill reopens a frozen liability in the
                # accounting book; never hide it from cancellation or recovery.
                intent.terminal, intent.uncertain, intent.cancel_requested = False, True, True
        self._daily_reports()
        live = self._live_windows()
        # Activity came back to an archived window: save it in full again; it is archived anew once finished.
        self.archived -= live
        cold = self._cold_windows(self.clock(), live)
        hidden = self.archived | cold
        chunk: dict[str, Any] | None = ({"version": 1, "windows": sorted(cold), "book": self.book.window_parts(lambda window: window in cold),
                  "intents": {key: without_default_lock(asdict(value)) for key, value in self.intents.items()
                              if value.window in cold}} if cold else None)
        state: dict[str, Any] = {"version": 1, "started_at": self.started_at, "updated_at": self.clock(),
                 "book": self.book.to_state(without=hidden),
                 "intents": {key: without_default_lock(asdict(value)) for key, value in self.intents.items()
                             if value.window not in hidden},
                 "archived_windows": sorted(self.archived | cold), "archive_chunks": self.archive_chunks + bool(cold),
                 "twin": self.twin.to_state(), "fatal_reason": self.fatal_reason,
                 "foreign_windows": sorted(self.foreign_windows), "final_outcomes": self.final_outcomes,
                 "changed_windows": sorted(self.changed_windows),
                 "latency_metrics": self.metrics.state(),
                 "window_evidence": self.evidence.state(),
                 "reports": self.reports,
                 "latest_events": self.latest_events, "panel": self.panel()}
        building = time.perf_counter()
        self.ledger.set_synchronous(durable or any(kind in OWNER_RECORDS for kind, _ in self.pending))
        with self.ledger.transaction():
            for kind, payload in self.pending:
                self.ledger.append_receipt(kind, payload, ts=payload["at"])
            if chunk is not None:
                self.ledger.set_kv(f"{ARCHIVE_KEY}{self.archive_chunks}", chunk)
            self.ledger.set_kv(STATE_KEY, state)
        saved = time.perf_counter()
        if chunk is not None:  # only once the chunk and the state that lists it are committed together
            self.archived |= cold
            self.archive_chunks += 1
            for part in WINDOW_PARTS:
                self.archive_parts[part].update(chunk["book"][part])
            self.archive_parts["live_intents"].update(chunk["intents"])
        for kind, payload in self.pending:
            log.info("%s %s", kind, json.dumps(payload, allow_nan=False, separators=(",", ":")))
        self.pending.clear()
        mirror_ms = None
        if self.stopping or self.clock() - self.last_mirror >= MIRROR_EVERY_S:
            mirroring = time.perf_counter()
            full = {**state, "intents": {**self.archive_parts["live_intents"], **state["intents"]},
                    "book": {**state["book"], **{part: {**self.archive_parts[part], **state["book"][part]}
                                                 for part in WINDOW_PARTS}}}
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(full, stream, allow_nan=False, separators=(",", ":"))
            os.replace(temporary, self.path)
            self.last_mirror = self.clock()
            mirror_ms = (time.perf_counter() - mirroring) * 1000
        self.last_checkpoint = self.clock()
        self.save_ms = (time.perf_counter() - started) * 1000
        self.save_stages = {"build_ms": (building - started) * 1000, "ledger_ms": (saved - building) * 1000,
                            "mirror_ms": mirror_ms}

    def _twin_events(self, events: list[Any]) -> None:
        for event in events:
            if event.event != "speeddesk_skip":
                self._record("speeddesk_twin", **asdict(event))
                if event.event == "speeddesk_fill":
                    self.evidence.fill({**asdict(event), "is_taker": event.kind == "take"})

    def on_tick(self, price: float, event_at: float, received_at: float) -> None:
        if 0 <= received_at - event_at <= 3:
            self.twin.tick_btc(price, event_at)
            self.wake.set()

    def on_windows(self, windows: list[Window]) -> None:
        self.evidence.discover([asdict(window) for window in windows if window.venue == "kalshi"], self.clock())
        for window in windows:
            if window.venue == "kalshi" and window.slug.startswith("KXBTC15M-"):
                previous = self.book.windows.get(window.slug)
                terms = ("taker_coefficient", "maker_coefficient", "tick_size", "min_trade_qty", "fee_rounding")
                if previous is not None and any(getattr(previous, key) != getattr(window, key) for key in terms):
                    self.changed_windows.add(window.slug)
                    self._twin_events(self.twin.cancel(self.clock(), window.slug, "venue_terms_changed"))
                self.book.add_window(window)
                self.twin.add_window(replace(window))

    def on_book(self, book: Book) -> None:
        if book.window in self.twin.windows and self.twin.on_book(book):
            self._twin_events(self.twin.advance(self.clock()))
            self.wake.set()

    def on_trade(self, trade: Trade) -> None:
        if trade.window in self.snapshot().maker_windows:
            self._twin_events(self.twin.on_trade(trade, self.clock()))

    def on_status(self, status: dict[str, Any]) -> None:
        if status.get("coinbase") != "connected" or not status.get("trade_stream"):
            self.evidence.last_fresh.clear()
        self.evidence.last_fresh.difference_update(status.get("gap_windows", []))
        for slug in status.get("gap_windows", []):
            self._twin_events(self.twin.cancel(self.clock(), slug, "venue_feed_gap"))

    def on_settlement(self, window: str, up_wins: bool, now: float) -> None:
        self.final_outcomes[window] = up_wins
        if window in self.twin.windows:
            self._twin_events(self.twin.cancel(now, window, "settled"))
            result = self.twin.settle(window, up_wins, now)
            if result is not None:
                self._record("speeddesk_twin_settlement", **asdict(result))

    def _feed_reason(self, window: Window, snapshot: LiveSnapshot, now: float) -> str:
        if window.venue != "kalshi" or not window.slug.startswith("KXBTC15M-"):
            return "Kalshi KXBTC15M only"
        if not math.isclose(window.end - window.start, 900, abs_tol=1):
            return "Unverified 15-minute window"
        if now < window.start:
            return "Window has not started"
        if now >= window.end - self.book.limits.lock_s:
            return "Window cutoff"
        if snapshot.bitcoin_at is None or not 0 <= now - snapshot.bitcoin_at <= 3:
            return "Bitcoin feed stale"
        if snapshot.bitcoin_price is None or window.start_price is None:
            return "Bitcoin opening price missing"
        if snapshot.sigma is None:
            return "Warming up Bitcoin volatility"
        return self._book_reason(window, snapshot, now)

    def _book_reason(self, window: Window, snapshot: LiveSnapshot, now: float) -> str:
        """Both books fresh and the window ours alone: all a lock needs (it uses no fair value)."""
        for side in ("up", "down"):
            book = snapshot.books.get((window.slug, side))
            if book is None or not 0 <= now - book.at <= 3:
                return "Kalshi book stale"
            if book.source == "rest" and (book.requested_at is None or not 0 <= now - book.requested_at <= 3):
                return "Kalshi book stale"
            if book.requested_at is not None and not 0 <= book.at - book.requested_at <= 3:
                return "Kalshi book stale"
            if book.source != "rest" and (book.exchange_at is None or not 0 <= now - book.exchange_at <= 3):
                return "Kalshi book stale"
        if window.slug in self.foreign_windows:
            return "Owner activity in this window; bot leaves it alone"
        if window.slug in self.changed_windows:
            return "Venue terms changed; wait for the next window"
        return ""

    def _trade_reason(self) -> str:
        return self._standing_reason() or self._waiting_reason()

    def _standing_reason(self) -> str:
        """Why real money is off or stopped: gates, failures and financial stops."""
        if self.stopping or self.stop_event is not None and self.stop_event.is_set():
            return "Shutting down; no new orders"
        if reason := self._gates():
            return reason
        if self.fatal_reason:
            return self.fatal_reason
        if not self.authenticated:
            return "Waiting for a successful balance read this run"
        return self._risk_stop_reason()

    def _waiting_reason(self) -> str:
        """Seconds-long pauses between orders while real money stays on."""
        if not self.startup_done:
            return "Reconciling startup orders"
        if self.account_at is None or not 0 <= self.clock() - self.account_at <= 3:
            return "Kalshi account data stale"
        if any(intent.uncertain or intent.cancel_requested for intent in self._active()):
            return "Reconciling an uncertain order; no new orders"
        return ""

    def _risk_stop_reason(self) -> str:
        risk = self.book.risk_status(self.clock())
        if risk["halted"]:
            return "Total loss stop; no new bets until a new resume token"
        if risk["integrity_error"]:
            return "Practice only; real account reconciliation needs review"
        if risk["day_stopped"]:
            return "Daily loss stop; no new buys until 00:00 UTC"
        return ""

    async def _cancel_unsafe(self) -> None:
        if self.client is None:
            return
        snapshot, now = self.snapshot(), self.clock()
        for intent in self._active():
            window = self._current_window(intent.window, snapshot)
            reason = (self._gates() or self.fatal_reason
                      or ("Repeated account errors" if self.errors >= 3 else ""))
            if not reason and not intent.lock:
                # A lock buy is immediate-or-cancel and only completes pairs: the window
                # closing or a money stop is exactly when it must be left to finish.
                reason = (self._risk_stop_reason()
                          or (self._feed_reason(window, snapshot, now) if window else "Window missing"))
            if reason:
                await self._cancel(intent, reason)

    def _error(self, exc: Exception) -> None:
        self.errors += 1
        self.retry_at = self.clock() + min(30.0, 2.0 ** min(self.errors, 5))
        if isinstance(exc, KalshiClientError) and exc.auth:
            self.auth_failed = True
            self.authenticated = False
            self.reason = "Practice only; Kalshi authentication failed this run"
        else:
            self.reason = "Kalshi account reconciliation failed; new orders paused"
        # Exception messages may contain request material. Record only type and
        # our fixed reason, never response bodies, headers, or key identifiers.
        # KalshiClientError's operation, reason and HTTP status are fixed strings
        # and an integer (safe by its contract) and name the call that failed.
        detail: dict[str, Any] = ({"operation": exc.operation, "detail": exc.reason, "status": exc.status,
                                   "code": exc.code} if isinstance(exc, KalshiClientError) else {})
        if isinstance(exc, LiveRejected):
            # The book's refusal codes are fixed identifiers: they name the check that refused.
            detail = {"code": exc.reason if exc.reason.isidentifier() and len(exc.reason) <= 64 else "unknown"}
        if self.book.integrity_reset_armed:
            self._reset_waiting("account_unreconciled")
        self._record("speeddesk_live_reject", reason=self.reason, error=type(exc).__name__, **detail)

    async def _ensure_client(self) -> bool:
        if self.client is not None:
            if self.auth_failed and not self._active() and self.book.open_cost_usd <= EPS:
                self.reason = "Practice only; Kalshi authentication failed this run"
                return False
            return True
        gate = self._gates()
        recovering = bool(self._active()) or self.book.open_cost_usd > EPS
        if gate and not recovering:
            self.reason = gate
            return False
        if not self.settings.kalshi_key_id or not self.settings.kalshi_private_key:
            self.reason = "Practice; prior live orders need credentials for cancellation"
            return False
        try:
            client = await self._io(self.client_factory)
            self.client = _RecoveryClient(client) if gate else client
            return True
        except Exception as exc:  # noqa: BLE001 — account construction must fail closed.
            self._error(exc)
            return False

    async def _cancel(self, intent: Intent, reason: str) -> None:
        if intent.terminal:
            return
        if self.clock() < self.cancel_retry_at.get(intent.client_order_id, -math.inf) and reason != "shutdown":
            return
        self.cancel_retry_at[intent.client_order_id] = self.clock() + 2
        intent.cancel_requested = True
        self.book.request_cancel(intent.client_order_id)
        self._twin_events(self.twin.cancel(self.clock(), intent.window, reason))
        self.checkpoint()
        if not intent.order_id:
            intent.uncertain = True
            self.book.mark_uncertain(intent.client_order_id, "cancel_needs_order_id")
            self.checkpoint()
            return
        try:
            await self._io(self.client.cancel, intent.order_id, ticker=intent.window)
            self._record("speeddesk_live_cancel", client_order_id=intent.client_order_id,
                         order_id=intent.order_id, window=intent.window, reason=reason,
                         state="requested; reservation retained until fills reconcile")
        except KalshiClientError as exc:
            if exc.operation == "cancel" and exc.status == 404 and not exc.uncertain:
                # Nothing of ours is resting under that ID (already canceled or
                # filled; seen 2026-10-12 when a repeat cancel looped for minutes).
                # Keep the reservation and let the order list confirm it; this is
                # not an account error and must not pause trading.
                self._record("speeddesk_live_cancel", client_order_id=intent.client_order_id,
                             order_id=intent.order_id, window=intent.window, reason=reason,
                             state="not resting on Kalshi (404); reservation retained until reconciled")
            else:
                intent.uncertain = True
                self.book.mark_uncertain(intent.client_order_id, "cancel_unconfirmed")
                self._error(exc)
                self.cancel_retry_at[intent.client_order_id] = self.retry_at
        except Exception as exc:  # noqa: BLE001 — uncertain cancellation retains the full reservation.
            intent.uncertain = True
            self.book.mark_uncertain(intent.client_order_id, "cancel_unconfirmed")
            self._error(exc)
            self.cancel_retry_at[intent.client_order_id] = self.retry_at
        self.checkpoint()

    async def _cancel_all(self, reason: str) -> None:
        if self.client is None:
            return
        for intent in self._active():
            await self._cancel(intent, reason)

    def _fill(self, raw: dict[str, Any], intent: Intent) -> ActualFill:
        outcome = "yes" if intent.side == "up" else "no"
        expected_book = "bid" if intent.side == "up" else "ask"
        if raw.get("ticker") != intent.window or raw.get("outcome_side") != outcome:
            raise ValueError("Owned fill direction does not match intent")
        if raw.get("book_side") != expected_book:
            raise ValueError("Owned fill is not an authorized buy")
        at = _stamp(raw.get("created_time") or raw.get("ts"))
        # The integer fallback loses subsecond precision. Allow that rounding,
        # but never let a milliseconds value or a future clock poison P&L days.
        if not intent.at - 1 <= at <= self.clock() + 1:
            raise ValueError("Owned fill has an implausible venue timestamp")
        return ActualFill(fill_id=str(raw["fill_id"]), order_id=intent.order_id,
                          client_order_id=intent.client_order_id, window=intent.window, side=intent.side,
                          price=_number(raw[f"{outcome}_price_dollars"]), size=_number(raw["count_fp"]),
                          fee_usd=_number(raw["fee_cost"]), at=at,
                          is_taker=raw.get("is_taker") if type(raw.get("is_taker")) is bool else None)

    def _validate_order(self, raw: dict[str, Any], intent: Intent) -> None:
        outcome = "yes" if intent.side == "up" else "no"
        expected_book = "bid" if intent.side == "up" else "ask"
        if (raw.get("client_order_id") != intent.client_order_id or raw.get("ticker") != intent.window
                or raw.get("outcome_side") != outcome or raw.get("book_side") != expected_book
                or not isinstance(raw.get("order_id"), str) or not raw["order_id"]
                or (intent.order_id and raw["order_id"] != intent.order_id)
                or abs(_number(raw["initial_count_fp"]) - intent.size) > EPS
                or abs(_number(raw[f"{outcome}_price_dollars"]) - intent.price) > EPS):
            self.fatal_reason = "Owned order identity or terms changed; reconciliation required"
            raise ValueError("Owned order identity or terms mismatch")

    async def _reconcile(self) -> None:
        assert self.client is not None
        sync_started = self.clock()
        # Fully paginated reads return all pages or raise. Never interpret a
        # missing/failed page as zero inventory or a canceled order.
        orders = await self._read(self.client.list_orders)
        for raw in orders:
            client_id = str(raw.get("client_order_id", ""))
            ticker = str(raw.get("ticker", ""))
            if not ticker.startswith("KXBTC15M-"):
                continue
            intent = self.intents.get(client_id)
            if client_id.startswith(PREFIX) and intent is None:
                self.fatal_reason = "Untracked prior bot order; manual reconciliation required"
                if raw.get("status") == "resting":
                    await self._io(self.client.cancel, str(raw["order_id"]), ticker=ticker)
                    self._record("speeddesk_live_cancel", order_id=str(raw["order_id"]), window=ticker,
                                 reason="untracked_startup_order")
            elif intent is not None:
                self._validate_order(raw, intent)
                order_id = str(raw["order_id"])
                if intent.order_id and intent.order_id != order_id:
                    raise ValueError("Client order ID resolved to two orders")
                intent.order_id = order_id
                self.book.mark_submitted(client_id, order_id)
            elif raw.get("status") == "resting":
                self.foreign_windows.add(ticker)
        self.checkpoint()
        fills = await self._read(self.client.fills, min_ts=max(0, int(self.started_at) - 60))
        by_order = {intent.order_id: intent for intent in self.intents.values() if intent.order_id}
        consistent = True
        for raw in fills:
            intent = by_order.get(str(raw.get("order_id", "")))
            if intent is None:
                ticker = str(raw.get("ticker", ""))
                if ticker.startswith("KXBTC15M-"):
                    if any(item.window == ticker and not item.order_id for item in self._active()):
                        consistent = False
                    else:
                        self.foreign_windows.add(ticker)
                continue
            fill = self._fill(raw, intent)
            if self.book.record_fill(fill):
                self._record("speeddesk_live_fill", **asdict(fill))
        orders = await self._read(self.client.list_orders)
        for raw in orders:
            intent = self.intents.get(str(raw.get("client_order_id", "")))
            if intent is None:
                continue
            self._validate_order(raw, intent)
            if not intent.order_id:
                intent.order_id = str(raw["order_id"])
                self.book.mark_submitted(intent.client_order_id, intent.order_id)
                consistent = False  # Its fills were fetched before this ID was known.
            status = str(raw.get("status", ""))
            if status not in {"resting", "canceled", "executed"}:
                raise ValueError("Unknown order status")
            order = OrderSnapshot(client_order_id=intent.client_order_id, order_id=intent.order_id,
                                  status=status,  # type: ignore[arg-type]
                                  filled_size=_number(raw["fill_count_fp"]),
                                  remaining_size=_number(raw["remaining_count_fp"]), at=self.clock())
            booked = self.book.intents[intent.client_order_id].filled_size
            # An order already confirmed finished never waits on a stale report (the book ignores those).
            behind = order.filled_size + EPS < booked and not intent.terminal
            if behind:  # the order list trails the fills already booked; tolerated for ORDER_LIST_LAG_S
                since = self.order_list_lag.setdefault(intent.client_order_id, self.clock())
            else:
                self.order_list_lag.pop(intent.client_order_id, None)
            confirmed = self.book.reconcile_order(
                order, fills_complete=True,
                lag_ok=behind and self.clock() - since <= ORDER_LIST_LAG_S)
            if behind:
                consistent = False  # no new orders until a fresh read agrees
            elif order.filled_size > booked + EPS:
                consistent = False
            elif abs(order.filled_size - self.book.intents[intent.client_order_id].filled_size) <= EPS:
                intent.uncertain = False
            if confirmed:
                intent.uncertain = False
                if status in {"canceled", "executed"}:
                    intent.terminal = True
        resting = any(str(raw.get("status", "")) == "resting" and str(raw.get("ticker", "")).startswith("KXBTC15M-")
                      for raw in orders)
        positions = await self._read(self.client.positions)
        actual = {str(item["ticker"]): _number(item["position_fp"]) for item in positions}
        windows = {intent.window for intent in self.intents.values()}
        # Settlement rows only ever close a traded window that has ended and is not yet settled; skip the read otherwise.
        settlement_due = any(ticker not in self.book.settled and (ticker not in self.book.windows
                                                                  or self.book.windows[ticker].end <= self.clock())
                             for ticker in windows)
        settlements = (await self._read(self.client.settlements, min_ts=max(0, int(self.started_at) - 60))
                       if settlement_due else [])
        self.final_outcomes.update(self.snapshot().outcomes)
        settlement_rows = {str(raw.get("ticker", "")): raw for raw in settlements}
        for raw in settlements:
            ticker = str(raw.get("ticker", ""))
            if raw.get("market_result") in {"yes", "no"}:
                self.final_outcomes[ticker] = raw["market_result"] == "yes"
        for ticker in windows:
            expected = self.book.expected_position(ticker)
            current = actual.get(ticker, 0.0)
            if (ticker in self.final_outcomes and not any(item.window == ticker for item in self._active())
                    and abs(current) <= EPS):
                row = settlement_rows.get(ticker)
                # A flat paired position needs no settlement payout. A
                # directional holding requires the venue's actual receipt,
                # except where the owner closed it out by hand: the account is
                # flat in that market, so Kalshi writes no row; the bot settles
                # its own contracts from the finalized outcome instead.
                if row is None and abs(expected) > EPS and ticker not in self.foreign_windows:
                    consistent = False
                    continue
                payout = _number(row["revenue"]) / 100 if row is not None else 0.0
                settled_at = _stamp(row["settled_time"]) if row is not None else self.clock()
                if not self.book.windows[ticker].end <= settled_at <= self.clock():
                    raise ValueError("Invalid venue settlement timestamp")
                # In a window the owner also traded, the venue's revenue includes the owner's contracts
                # (owner, 2026-10-13): the bot's result comes from its own reconciled fills and the outcome.
                result = self.book.settle(ticker, self.final_outcomes[ticker], settled_at,
                                          settlement_id=f"kalshi:{ticker}",
                                          net_payout_usd=None if ticker in self.foreign_windows else payout)
                if result is not None:
                    self._record("speeddesk_live_settlement", **asdict(result), observed_at=self.clock(),
                                 time_source="venue settled_time" if row is not None else
                                 "public final outcome observed; paired position has no cash settlement")
                continue
            if abs(expected - current) > EPS and ticker not in self.foreign_windows:
                # A fill may arrive between paginated account reads. Pause and
                # reconcile again; never assign a mismatched position to us. A
                # window holding a fill that is provably not ours (the owner's
                # trade by hand) mixes the owner's contracts into the venue
                # position; the bot leaves it alone and counts only its own fills.
                consistent = False
        for ticker, amount in actual.items():
            if ticker.startswith("KXBTC15M-") and ticker not in windows and abs(amount) > EPS:
                self.foreign_windows.add(ticker)
        self.position_sizes = actual
        balance = await self._read(self.client.balance)
        cash = (_number(balance["balance_dollars"]) if "balance_dollars" in balance
                else _number(balance["balance"]) / 100)
        if cash < 0:
            raise ValueError("Negative available cash")
        now = self.clock()
        self.book.update_cash(cash, now)
        self.cash_usd, self.cash_at = cash, now
        self.account_at = now if consistent and now - sync_started <= 3 else None
        self._integrity_reset(actual, resting)
        self.authenticated = not self.auth_failed
        self.errors = 0
        self.retry_at = -math.inf
        self.last_sync = now
        self.checkpoint()

    def _integrity_reset(self, positions: dict[str, float], resting: bool) -> None:
        """The owner's one-time clear of a reconciliation stop (owner, 2026-10-13: "Yes, reset it"). Only right
        after a complete, fresh reconcile that matched, with no order open or uncertain, every window the bot
        traded settled, and no Bitcoin 15-minute position or resting order left on the Kalshi account."""
        armed = self.book.integrity_reset_armed
        if armed is None or armed != self.book.integrity_error:
            return
        if not self.startup_done:  # startup cancels and re-reads first; a later full reconcile decides
            self._reset_waiting("startup_pending")
            return
        active = self._active()
        blocker = (("account_unreconciled" if self.account_at is None else "")
                   or ("fatal" if self.fatal_reason else "")
                   or ("orders_open" if resting or active
                       or any(intent.uncertain or intent.cancel_requested for intent in active) else "")
                   or ("positions_open" if any(ticker.startswith("KXBTC15M-") and abs(amount) > EPS
                                               for ticker, amount in positions.items()) else "")
                   or self.book.integrity_reset_blocker())
        if blocker:
            self._reset_waiting(blocker)
            return
        code = self.book.reset_integrity()
        self.reset_blocker = ""
        self.reset_reported.clear()
        self.integrity_logged = None
        self._record("speeddesk_live_integrity_reset", code=code, cash_usd=self.cash_usd,
                     state="cleared; the books and Kalshi matched with nothing open")

    def _reset_waiting(self, blocker: str) -> None:
        if blocker not in self.reset_reported:  # each reason once, however the account flickers
            self.reset_reported.add(blocker)
            self._record("speeddesk_live_integrity_reset", code=self.book.integrity_reset_armed, reason=blocker,
                         state="waiting for clean books")
        self.reset_blocker = blocker

    async def _startup(self) -> None:
        await self._reconcile()
        await self._cancel_all("startup")
        if self._active():
            await self._reconcile()
        self.startup_done = not self._active()
        self.reason = None if self.startup_done else "Reconciling startup orders"

    def _current_window(self, slug: str, snapshot: LiveSnapshot) -> Window | None:
        return next((window for window in snapshot.windows if window.slug == slug), None)

    async def _send(self, window: Window, side: Side, kind: Literal["take", "rest"],
                    price: float, size: float, fair: float) -> bool:
        now = self.clock()
        snapshot = self.snapshot()
        current = self._current_window(window.slug, snapshot)
        reason = self._trade_reason() or (self._feed_reason(current, snapshot, now) if current else "Window missing")
        if reason:
            self.reason = reason
            return False
        assert current is not None and current.start_price is not None
        assert snapshot.bitcoin_price is not None and snapshot.sigma is not None
        fresh_up = fair_up(snapshot.bitcoin_price, current.start_price, snapshot.sigma, current.end - now)
        if fresh_up is None:
            return False
        fair = fresh_up if side == "up" else 1 - fresh_up
        if kind == "rest" and window.slug not in snapshot.maker_windows:
            self.reason = "Waiting for actual trades to verify practice maker fills"
            return False
        try:
            cost = self.book.unit_reserve(window.slug, price, kind)
        except LiveRejected:
            self.reason = "Fee schedule unavailable"
            return False
        edge = self.settings.speeddesk_take_edge if kind == "take" else self.settings.speeddesk_make_edge
        if fair - cost < edge - EPS:
            self.reason = ("Account fee precision unverified; no edge after conservative fee rounding"
                           if not self.fee_verified else "Edge after conservative rounded fees is too small")
            return False
        client_id = PREFIX + uuid.uuid4().hex
        decision_mono = self.monotonic()
        try:
            self.book.reserve_intent(window.slug, side, kind, price, size, now,
                                     client_order_id=client_id, fair=fair)
        except LiveRejected as exc:
            self.reason = str(exc)
            return False
        intent = Intent(client_id, window.slug, side, kind, price, size, fair, now)
        self.intents[client_id] = intent
        self._record("speeddesk_live_order", client_order_id=client_id, window=window.slug,
                     side=side, kind=kind, price=price, size=size, fair=fair, state="durable intent",
                     timing=self.metrics.decision("real_kalshi", now, snapshot.tick_receipt, decision_mono))
        twin_event = self.twin.place(window.slug, side, kind, price, size, fair, now)
        if twin_event.event in ("speeddesk_take", "speeddesk_rest"):
            self.metrics.decision("practice_twin", now, snapshot.tick_receipt, decision_mono)
        intent.twin_order_id = twin_event.order_id
        self._twin_events([twin_event])
        # The order identifier and its complete worst-case liability reach disk
        # before the first network byte can leave this process; one write covers the twin too.
        saving = self.monotonic()
        self.checkpoint(durable=True)
        await self._submit(intent, window, now, decision_mono, save_ms=(self.monotonic() - saving) * 1000)
        return True

    async def _submit(self, intent: Intent, window: Window, now: float, decision_mono: float,
                      save_ms: float | None = None) -> None:
        """Send a durable intent once and settle what its reply proves; never retries a create."""
        client_id, side, kind, price, size = intent.client_order_id, intent.side, intent.kind, intent.price, intent.size
        sent_at: list[float] = []

        def guard() -> bool:
            permitted = self._send_guard(client_id)
            sent_at.append(self.monotonic())  # the request leaves right after this returns
            return permitted

        def timing(value: float | None, status: Literal["ok", "missing", "invalid", "error", "timeout"] = "ok") -> Any:
            # A lock is not a Bitcoin-driven decision: it stays out of the speed measurements.
            return None if intent.lock else self.metrics.observe("real_kalshi", "decision_to_ack", now, value, status)

        assert self.client is not None
        try:
            reply = await self._io(self.client.create_order, ticker=window.slug, side=side,
                                             kind=kind, price=price, size=size, client_order_id=client_id,
                                             expiration_ts=min(int(window.end - self.book.limits.lock_s),
                                                               int(now) + 30)
                                             if kind == "rest" else None,
                                             before_send=guard)
            intent.order_id = str(reply["order_id"])
            if not intent.order_id:
                raise ValueError("Create response has no order identifier")
            self.book.mark_submitted(client_id, intent.order_id)
            self.refusals = 0
            acked = self.monotonic()
            # Where the decision-to-acknowledgement time went: the pre-send disk write, the wait from the decision
            # to the first request byte (disk write, worker hand-off, request budget), and Kalshi's reply.
            stages = {"save_ms": save_ms,
                      "decision_to_send_ms": (sent_at[0] - decision_mono) * 1000 if sent_at else None,
                      "send_to_ack_ms": (acked - sent_at[0]) * 1000 if sent_at else None}
            self._record("speeddesk_live_order", client_order_id=client_id, order_id=intent.order_id,
                         window=window.slug, state="accepted; waiting for real fills",
                         timing=timing((acked - decision_mono) * 1000), stages=stages)
        except asyncio.CancelledError:
            self._record("speeddesk_live_timing", client_order_id=client_id, timing=timing(None, "missing"))
            raise
        except Exception as exc:  # noqa: BLE001 — uncertain requests retain their complete reservation.
            self._record("speeddesk_live_timing", client_order_id=client_id,
                         timing=timing(None, "timeout" if isinstance(exc, KalshiClientError)
                                       and exc.timed_out else "error"))
            if isinstance(exc, KalshiClientError) and not exc.uncertain:
                self.book.reject_intent(client_id, "definite_create_rejection", confirmed=True)
                intent.terminal = True
                if not intent.lock:
                    self._twin_events(self.twin.cancel(self.clock(), window.slug, "real_order_rejected"))
            else:
                intent.uncertain = True
                self.book.mark_uncertain(client_id, "create_unconfirmed")
            if isinstance(exc, KalshiClientError) and not exc.uncertain and exc.reason == "send_guard_rejected":
                # Our own last check stopped it before any byte left: the market moved, nothing failed.
                self._record("speeddesk_live_order", client_order_id=client_id, window=window.slug,
                             state="not sent; prices moved before send")
            elif self._single_order_refusal(exc) and self.refusals < 2:
                assert isinstance(exc, KalshiClientError)
                self.refusals += 1
                self._record("speeddesk_live_reject", client_order_id=client_id, window=window.slug,
                             reason="Kalshi refused this one order; still trading", error=type(exc).__name__,
                             operation=exc.operation, detail=exc.reason, status=exc.status, code=exc.code)
            else:
                self.refusals = 0
                self._error(exc)
        self.checkpoint()
        # Any create, including an IOC, changes available cash and inventory.
        # No second create is possible until a new complete account snapshot.
        self.account_at = None

    async def _lock(self) -> bool:
        """Complete a half-filled pair before the close instead of leaving a coin flip.

        The owner's rule (2026-10-13): pairs are "completely locked in". From limits.lock_s before
        the close, new buys stop; any window holding more of one side buys the other side at the
        ask (up to limits.lock_max_price) so every contract ends in a $1 pair. Above that price the
        window is already decided and is left alone. A lock can only lower the possible loss, so
        it also runs during a money stop; it never runs with the live switches off or after a
        failure, in a window the owner traded, or before every order in the window is reconciled.
        """
        if (self.stopping or (self.stop_event is not None and self.stop_event.is_set()) or self._gates()
                or self.fatal_reason or not self.authenticated or self.book.integrity_error
                or self._waiting_reason()):
            return False
        snapshot, now = self.snapshot(), self.clock()
        for slug in sorted(self.book.windows):
            spec = self.book.windows[slug]
            if slug in self.book.settled or not spec.end - self.book.limits.lock_s <= now < spec.end - LOCK_MARGIN_S:
                continue
            side, unpaired = self.book.lock_side(slug)
            size = math.floor(unpaired + EPS)
            if side is None or size < 1:
                continue
            if any(intent.window == slug for intent in self._active()):
                continue  # earlier orders finish reconciling before the unpaired count is trusted
            window = self._current_window(slug, snapshot)
            reason = self._book_reason(window, snapshot, now) if window else "Window missing"
            book = snapshot.books.get((slug, side))
            ask = min(book.asks, key=lambda level: level.price, default=None) if book and not reason else None
            # Near 0 and 1 Kalshi quotes sub-penny ticks; orders are whole cents. An immediate-or-cancel
            # limit one tick above still fills at the better price, never worse than the limit.
            limit = math.ceil(round(ask.price * 100, 6)) / 100 if ask is not None else None
            if limit is None or limit > self.book.limits.lock_max_price + EPS:
                self._lock_note(slug, reason or ("no_ask" if ask is None else "lock_price"), side, size)
                continue
            assert window is not None
            size = min(size, int(self.book.limits.clip))
            # Lock as many contracts as the cash allows rather than none.
            fit = next((n for n in range(size, 0, -1) if not self.book.can_lock(slug, side, limit, n, now)), 0)
            if not fit:
                self._lock_note(slug, self.book.can_lock(slug, side, limit, size, now) or "lock_refused", side, size)
                continue
            if await self._send_lock(window, side, limit, float(fit)):
                return True
        return False

    def _lock_possible(self) -> bool:
        """A lock is pending, or some window in its lock period still holds unpaired whole contracts."""
        if any(intent.lock for intent in self._active()):
            return True
        now = self.clock()
        for slug, spec in self.book.windows.items():
            if (slug not in self.book.settled and slug not in self.foreign_windows
                    and spec.end - self.book.limits.lock_s <= now < spec.end - LOCK_MARGIN_S
                    and self.book.lock_side(slug)[1] >= 1 - EPS):
                return True
        return False

    def _lock_note(self, window: str, reason: str, side: Side, size: int) -> None:
        if self.lock_notes.get(window) != reason:
            self.lock_notes[window] = reason
            self._record("speeddesk_live_lock", window=window, side=side, size=size,
                         state="waiting to complete the pair", reason=reason)

    async def _send_lock(self, window: Window, side: Side, price: float, size: float) -> bool:
        now, decision_mono = self.clock(), self.monotonic()
        client_id = PREFIX + uuid.uuid4().hex
        try:
            self.book.reserve_intent(window.slug, side, "take", price, size, now,
                                     client_order_id=client_id, fair=price, lock=True)
        except LiveRejected as exc:
            self._lock_note(window.slug, exc.reason, side, int(size))
            return False
        intent = Intent(client_id, window.slug, side, "take", price, size, price, now, lock=True)
        self.intents[client_id] = intent
        self._record("speeddesk_live_order", client_order_id=client_id, window=window.slug, side=side,
                     kind="lock", price=price, size=size, state="durable intent; completing a half-filled pair")
        # Durable before the first network byte, exactly like every other order.
        self.checkpoint(durable=True)
        await self._submit(intent, window, now, decision_mono)
        return True

    def _lock_guard(self, intent: Intent) -> bool:
        """Last check under the transport lock: still the lock period, still unpaired, ask still there."""
        snapshot, now = self.snapshot(), self.clock()
        window = self._current_window(intent.window, snapshot)
        spec = self.book.windows.get(intent.window)
        if (window is None or spec is None or self.stopping
                or (self.stop_event is not None and self.stop_event.is_set())
                or self._gates() or self.fatal_reason or self.book.integrity_error
                or not spec.end - self.book.limits.lock_s <= now < spec.end - LOCK_MARGIN_S
                or self._book_reason(window, snapshot, now)):
            return False
        side, unpaired = self.book.lock_side(intent.window)
        if side != intent.side or intent.size > unpaired + EPS:
            return False
        asks = snapshot.books[(intent.window, intent.side)].asks
        return any(level.price <= intent.price + EPS and level.size > 0 for level in asks)

    @staticmethod
    def _single_order_refusal(exc: Exception) -> bool:
        """A definite 4xx about one order; authentication and rate limits stay account errors."""
        return (isinstance(exc, KalshiClientError) and not exc.uncertain and exc.status is not None
                and 400 <= exc.status < 500 and exc.status not in (401, 403, 429))

    def _send_guard(self, client_id: str) -> bool:
        """Called under the client's transport lock, after any rate-limit wait."""
        intent = self.intents[client_id]
        if intent.lock:
            return self._lock_guard(intent)
        snapshot = self.snapshot()
        current = self._current_window(intent.window, snapshot)
        if (current is None or self._trade_reason()
                or self._feed_reason(current, snapshot, self.clock())):
            return False
        assert current.start_price is not None and snapshot.bitcoin_price is not None and snapshot.sigma is not None
        up = fair_up(snapshot.bitcoin_price, current.start_price, snapshot.sigma, current.end - self.clock())
        if up is None:
            return False
        fair = up if intent.side == "up" else 1 - up
        edge = self.settings.speeddesk_take_edge if intent.kind == "take" else self.settings.speeddesk_make_edge
        if fair - self.book.unit_reserve(intent.window, intent.price, intent.kind) < edge - EPS:
            return False
        asks = snapshot.books[(intent.window, intent.side)].asks
        if intent.kind == "rest":
            return (intent.window in snapshot.maker_windows
                    and all(level.price > intent.price + EPS for level in asks))
        return any(level.price <= intent.price + EPS and level.size > 0 for level in asks)

    async def _decide(self) -> None:
        if reason := self._trade_reason():
            self.reason = reason
            return
        self.reason = (None if self.fee_verified else
                       "Account fee precision unverified; conservative fee rounding is required")
        snapshot, now = self.snapshot(), self.clock()
        candidates: list[tuple[float, Window, Side, float, Literal["take", "rest"], float, int]] = []
        for window in snapshot.windows:
            reason = self._feed_reason(window, snapshot, now)
            if reason:
                self.reason = reason
                continue
            assert snapshot.bitcoin_price is not None and window.start_price is not None and snapshot.sigma is not None
            up = fair_up(snapshot.bitcoin_price, window.start_price, snapshot.sigma, window.end - now)
            if up is None:
                continue
            for side in ("up", "down"):
                fair = up if side == "up" else 1 - up
                book = snapshot.books[(window.slug, side)]
                ask = min(book.asks, key=lambda item: item.price, default=None)
                # The risk model rechecks edge using its conservative rounded
                # fee reservation. This quick filter never authorizes spending.
                take = bool(ask and self.book.unit_reserve(window.slug, ask.price, "take")
                            <= fair - self.settings.speeddesk_take_edge + EPS)
                kind: Literal["take", "rest"] = "take" if take else "rest"
                price = ask.price if ask and take else round(math.floor(
                    (fair - self.settings.speeddesk_make_edge + EPS) / window.tick_size) * window.tick_size, 4)
                pending = [item for item in self._active() if item.window == window.slug and item.side == side]
                for intent in pending:
                    if (intent.kind == "rest" and (take or abs(fair - intent.fair) > 0.01 + EPS
                                                   or window.slug not in snapshot.maker_windows)):
                        await self._cancel(intent, "reprice" if not take else "take_available")
                        self.account_at = None
                        return
                if pending or not 0 < price < 1:
                    continue
                if kind == "rest" and (window.slug not in snapshot.maker_windows
                                       or any(level.price <= price + EPS for level in book.asks)):
                    continue
                units = math.floor(min(self.settings.speeddesk_clip, ask.size if ask and take else 25))
                inventory = self.book.inventory[window.slug]
                if inventory.up.shares + inventory.down.shares <= EPS:
                    # Scale the starter to whole pairs at the authorized pair
                    # cap, so a cheap first side cannot consume the hedge budget.
                    units = min(units, math.floor(self.book.limits.window_usd / self.book.limits.pair_cap))
                    if units == 0:
                        self.reason = "Window budget is too small for a whole capped pair"
                if units:
                    candidates.append((fair - price, window, side, fair, kind, price, units))
        for _, window, side, fair, kind, price, units in sorted(candidates, key=lambda item: -item[0]):
            # Only whole contracts leave the process. With the owner's tiny
            # budget this bounded search generally tries fewer than five sizes.
            for size in range(units, 0, -1):
                if await self._send(window, side, kind, price, float(size), fair):
                    return

    def observe_market(self, observed_at: float) -> None:
        market = self.snapshot()
        windows = [asdict(window) for window in market.windows]
        self.evidence.advance(observed_at, windows, fresh_window_slugs(
            windows, market.books, market.bitcoin_at, market.maker_windows, observed_at))

    async def step(self) -> None:
        self.observe_market(self.clock())
        self._twin_events(self.twin.advance(self.clock()))
        if not await self._ensure_client():
            if self.book.integrity_reset_armed:
                self._reset_waiting("live_off")  # no account read happens, so the reset cannot be judged
            self._heartbeat()
            return
        try:
            await self._cancel_unsafe()
            if self.clock() < self.retry_at:
                self._heartbeat()
                return
            if not self.startup_done:
                await self._startup()
            elif self.clock() - self.last_sync >= 1 or self.account_at is None:
                await self._reconcile()
            gate = self._gates()
            await self._cancel_unsafe()
            if gate:
                self.reason = "Practice; cancelling prior live bids" if self._active() else gate
            elif await self._lock():
                self.reason = "Completing a half-filled pair before the close"
            else:
                await self._decide()
        except Exception as exc:  # noqa: BLE001 — failed account evidence never permits another order.
            self.account_at = None
            self._error(exc)
            if self.errors >= 3 or self.auth_failed:
                await self._cancel_all("authentication_or_repeated_errors")
        self._heartbeat()

    def _heartbeat(self) -> None:
        if self.clock() - self.last_status >= 60:
            self._record("speeddesk_live_status", **self.panel(),
                         save={"last_ms": self.save_ms, **self.save_stages, "archived_windows": len(self.archived),
                               "saved_orders": sum(intent.window not in self.archived for intent in self.intents.values())})
            self.last_status = self.clock()
        if self.pending or self.clock() - self.last_checkpoint >= 5:
            self.checkpoint()

    async def run(self, stop: threading.Event) -> None:
        self.stop_event = stop
        self.wake = asyncio.Event()  # bound to this run's event loop
        try:
            while not stop.is_set():
                self.wake.clear()
                started = self.monotonic()
                await self.step()
                # The next tick or book change wakes the loop at once (a fixed quarter-second sleep added 125 ms
                # on average before each decision); a quiet market still steps every IDLE_STEP_S.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), IDLE_STEP_S)
                await asyncio.sleep(max(0.0, MIN_STEP_S - (self.monotonic() - started)))
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.closed or self.shutdown_done:
            return
        self.stopping = True
        if self._workers:
            await asyncio.gather(*tuple(self._workers), return_exceptions=True)
        if self.client is None and (self._active() or self.book.open_cost_usd > EPS):
            await self._ensure_client()
        known_ids = {intent.order_id for intent in self._active() if intent.order_id}
        # Known resting orders get cancellation priority over slower account
        # pagination. Short server-side expiry also bounds a dead process's bid.
        for intent in self._active():
            if intent.order_id in known_ids:
                await self._cancel(intent, "shutdown")
        # A canceled coroutine may have lost its create response while the
        # shielded HTTP worker completed. Resolve that persisted intent before
        # trying to cancel, so shutdown does not leave the discovered bid live.
        if self.client is not None:
            try:
                await self._reconcile()
            except Exception as exc:  # noqa: BLE001 — unknown requests remain reserved.
                self._error(exc)
        discovered = [intent for intent in self._active() if intent.order_id not in known_ids]
        for intent in discovered:
            await self._cancel(intent, "shutdown")
        if self.client is not None and discovered:
            try:
                await self._reconcile()
            except Exception as exc:  # noqa: BLE001 — leave reservations durable for the next startup.
                self._error(exc)
        self._twin_events(self.twin.cancel(self.clock(), reason="shutdown"))
        self.checkpoint(durable=True)
        self.shutdown_done = True

    def panel(self) -> dict[str, Any]:
        risk = self.book.risk_status(self.clock())
        # The label follows the switches and stops, not the seconds between orders: after every order
        # the desk re-reads the account, and the town showed "PRACTICE" then (2026-10-13 00:15 UTC).
        standing, stop = self._standing_reason(), self._risk_stop_reason()
        # A money stop blocks new bets, but a lock can only lower the loss and still runs before the close:
        # while one is possible, real money is on for completing pairs only (review, 2026-10-13).
        lock_only = bool(standing) and standing == stop and not self.book.integrity_error and self._lock_possible()
        live = not standing or lock_only
        waiting = ((("Paused after a Kalshi error; retrying shortly" if self.clock() < self.retry_at else "")
                    or self._waiting_reason()) if live and not lock_only else "")
        if lock_only:
            waiting = stop + "; only completing half-filled pairs before the close"
        active = self._active()
        reason = self.fatal_reason or (waiting if lock_only else self.reason)
        return {"mode": "live" if live else "paper", "configured_mode": self.settings.speeddesk_kalshi_mode,
                "status": "REAL MONEY (Kalshi)" if live else "PRACTICE", "reason": reason,
                "trading_now": live and not waiting, "waiting": waiting,
                "as_of": self.clock(), "authenticated": self.authenticated,
                "fee_precision_verified": self.fee_verified,
                "fee_precision_usd": self.book.limits.fee_precision,
                "cash_usd": self.cash_usd, "cash_at": self.cash_at,
                "reserved_usd": risk.get("reserved_usd", 0.0), "open_risk_usd": risk.get("open_loss_usd", 0.0),
                "open_cost_usd": risk.get("open_cost_usd", 0.0),
                "at_risk_usd": risk.get("at_risk_usd", 0.0), "open_orders": len(active),
                "positions": sum(abs(value) > EPS for key, value in self.position_sizes.items()
                                 if key in {intent.window for intent in self.intents.values()}),
                "total_halted": risk.get("halted", False), "real_orders_available": live,
                "integrity_error": self.book.integrity_error,
                "integrity_reset": (self.reset_blocker or "armed") if self.book.integrity_reset_armed else None,
                "cleanup_pending": bool(active) and bool(self._gates()),
                # The limits the risk book enforces, not the settings asked for (they once differed silently).
                "caps": {"window_usd": self.book.limits.window_usd, "open_usd": self.book.limits.open_usd,
                         "day_stop_usd": self.book.limits.day_loss_usd,
                         "total_stop_usd": self.book.limits.total_loss_usd},
                "today": self._summary(utc_day(self.clock())), "total": self._summary(None),
                "practice_twin": self._twin_summary(utc_day(self.clock())),
                "reports": self.reports,
                "latest_events": self.latest_events[-10:]}

    def _summary(self, day: str | None) -> dict[str, Any]:
        fills = [fill for fill in self.book.fills.values() if day is None or utc_day(fill.at) == day]
        settlements = [item for item in self.book.settled.values() if day is None or utc_day(item.at) == day]
        orders = [item for item in self.intents.values() if day is None or utc_day(item.at) == day]
        filled_ids = {fill.client_order_id for fill in self.book.fills.values()}
        locks = [item for item in orders if item.lock]
        takes = [item for item in orders if item.kind == "take" and not item.lock]
        makers = [item for item in orders if item.kind == "rest"]
        take_fills = sum(item.client_order_id in filled_ids for item in takes)
        maker_fills = sum(item.client_order_id in filled_ids for item in makers)
        latency = [max(0.0, fill.at - self.intents[fill.client_order_id].at) * 1000 for fill in fills
                   if not self.intents[fill.client_order_id].lock]
        return {"day": day, "windows": len({fill.window for fill in fills}), "fills": len(fills),
                "latency": self.metrics.report(day, "real_kalshi", real=True) if day is not None else None,
                "scorecard": self.scorecard(day) if day is not None else None,
                "settled_windows": len(settlements),
                "fees_usd": sum(fill.fee_usd for fill in fills),
                "locked_usd": sum(item.locked_usd for item in settlements),
                "directional_usd": sum(item.direction_usd for item in settlements),
                "pnl_usd": sum(item.pnl_usd for item in settlements),
                "worst_usd": min((item.pnl_usd for item in settlements), default=None),
                "take_attempts": len(takes), "take_fills": take_fills,
                "maker_orders": len(makers), "maker_fills": maker_fills,
                "locks": len(locks), "lock_fills": sum(item.client_order_id in filled_ids for item in locks),
                "take_fill_rate": take_fills / len(takes) if takes else None,
                "maker_fill_rate": maker_fills / len(makers) if makers else None,
                "avg_latency_ms": sum(latency) / len(latency) if latency else None,
                "latency_definition": "durable real decision to venue fill timestamp; maker includes resting time"}

    def scorecard(self, day: str, *, twin: bool = False) -> dict[str, Any]:
        windows = [asdict(window) for window in self.book.windows.values() if window.end <= self.clock()]
        fills = self.evidence.fills if twin else [asdict(row) for row in self.book.fills.values()]
        settlements = ([asdict(row) for row in self.twin.closed] if twin else
                       [asdict(row) for row in self.book.settled.values()])
        coverage = self.evidence.coverage(windows)
        if not twin:
            for window in windows:
                if self.book.integrity_error or any(
                    intent.window == window["slug"] and (not intent.terminal or intent.uncertain
                        or self.book.intents[intent.client_order_id].reservation_active)
                    for intent in self.intents.values()
                ):
                    coverage[window["slug"]] = None
        report = window_scorecard(day, windows=windows, fills=fills, settlements=settlements,
                                coverage=coverage, scope="practice_twin" if twin else "real",
                                as_of=self.clock(), day_coverage_complete=self.evidence.complete_kalshi_day(
                                    day, windows, self.clock()))
        report.update(self.evidence.availability([window for window in windows if utc_day(window["end"]) == day]))
        return report

    def _twin_summary(self, day: str) -> dict[str, Any]:
        return {**self.twin.daily_summary(day, venue="kalshi"),
                "latency": self.metrics.report(day, "practice_twin"), "scorecard": self.scorecard(day, twin=True)}

    def _daily_reports(self) -> None:
        today = datetime.fromtimestamp(self.clock(), UTC).date()
        day = max(datetime.fromtimestamp(self.started_at, UTC).date(), today - timedelta(days=31))
        while day < today:
            key = day.isoformat()
            report: dict[str, Any] = {"day": key, "real": self._summary(key), "practice_twin": self._twin_summary(key)}
            if day < today - timedelta(days=30):
                previous = self.reports.get(key, {})
                for scope in ("real", "practice_twin"):
                    for field_name in ("scorecard", "latency"):
                        if field_name in previous.get(scope, {}):
                            report[scope][field_name] = previous[scope][field_name]
            if self.reports.get(key) != report:
                kind = "speeddesk_live_daily_correction" if key in self.reports else "speeddesk_live_daily"
                self.reports[key] = report
                self._record(kind, **report)
            day += timedelta(days=1)
        self.reports = {day: self.reports[day] for day in sorted(self.reports)[-31:]}

    def close(self) -> None:
        if not self.closed:
            if any(not task.done() for task in self._workers):
                raise RuntimeError("Cannot release Kalshi account lock while network writes may still run")
            if self.client is not None:
                self.client.close()
            self.ledger.close()
            self._lock_stream.close()
            self.closed = True

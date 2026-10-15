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
from .speeddesk_feeds import thread_session
from .speeddesk_kalshi_client import WRITES_PER_S, KalshiClient, KalshiClientError
from .speeddesk_live_ladder import Ladder, limits_view
from .speeddesk_live_model import (
    LOCK_MARGIN_S,
    WINDOW_PARTS,
    ActualFill,
    LiveIntent,
    LiveLimits,
    LiveRejected,
    LiveRiskBook,
    OrderSnapshot,
    without_default_lock,
)
from .speeddesk_live_pull import PullGuard, PullRule, compare
from .speeddesk_markouts import FillMarkouts
from .speeddesk_metrics import (
    LatencyMetrics,
    TickReceipt,
    WindowEvidence,
    fresh_window_slugs,
)
from .speeddesk_model import (
    FUTURE_SKEW_S,
    Book,
    Inventory,
    PracticeDesk,
    PracticeOrder,
    Side,
    SpeedConfig,
    Trade,
    Window,
    fair_up,
    utc_day,
)
from .speeddesk_readtrace import MAX_REPORTS_PER_MINUTE, ReadSpan, ReconcileTrace
from .speeddesk_scorecard import window_scorecard
from .speeddesk_worktrace import WorkTrace, observed, work_span

log = logging.getLogger("nightcrawler.speeddesk")
PREFIX = "nc-speed-"
STATE_KEY = "kalshi_live_state"
EPS = 1e-8
# How long Kalshi's order list may trail its fills list before the mismatch stops real orders for good
# (seen trailing by under a second on 2026-10-13; every read in between counts as not yet reconciled).
ORDER_LIST_LAG_S = 30.0
# Account reads cover only recent orders and fills: those since the earlier of the oldest unfinished order and one
# window ago, less a margin (Kalshi's min_ts). The complete history (0.5 MB/s on 2026-10-13 and growing with every
# order) is read at startup, every FULL_SCAN_S, and once after each new window opens, so an untracked bot order or
# an owner's order placed before the window opened is still caught before the bot's first order there.
FULL_SCAN_S, RECENT_S, READ_MARGIN_S = 60.0, 900.0, 60.0
# A resting bid is repriced when fair moves more than REPRICE_FAIR from the fair it was priced at (the rule in
# _decide); it is also cancelled once it sits above fresh fair minus STALE_BID_EDGE, even while account data are
# stale (loss plan bug 2).
REPRICE_FAIR, STALE_BID_EDGE = 0.01, 0.02
# Timing samples kept per status line (one a minute); counts stay exact beyond it.
SAMPLE_LIMIT = 8192
# Measurement only (speed plan step 0): a 10 ms timer's oversleep is the event loop's lag, and once a minute the
# local clock is compared with Coinbase's (its /time, the source of every Bitcoin tick's stamp). Kalshi's clock is
# compared on every order and cancel reply (its ts_ms) at no extra request.
LAG_PROBE_S, CLOCK_PROBE_S = 0.01, 60.0
COINBASE_TIME = "https://api.exchange.coinbase.com/time"
# The live loop steps on each Bitcoin tick or book change, at most every MIN_STEP_S, and at least every IDLE_STEP_S.
MIN_STEP_S, IDLE_STEP_S = 0.02, 0.25
# Only cancellation checks run while a private account GET is pending. No second risk writer or decision loop.
CANCEL_CHECK_S = 0.05
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
OWNER_RECORDS = frozenset({"speeddesk_live_day_reset", "speeddesk_live_integrity_reset", "speeddesk_live_resume",
                           "speeddesk_live_stop"})
# What each outcome of the owner's resume value means, in the receipt (the value itself is never written).
RESUME_STATES = {
    "applied": "applied; the total loss stop is cleared and a fresh stop budget counts from the result now",
    "used": "ignored; this value was already used",
    "not_halted": "ignored; no total loss stop is latched, so the value is kept unused (a value present before a "
                  "stop never clears that stop: set a new value after one)",
    "integrity": "ignored; a reconciliation stop is in force, so the value is kept unused until that stop is cleared",
}
# The earned-growth ladder looks at the books at most this often (a change only ever starts at the next window).
LADDER_EVERY_S = 1.0
# Speed plan step 2. The write before an order's first network byte is one small row, synced to disk: the order's
# identity and complete reservation, in the pre-send journal (ledger key JOURNAL_KEY). The full state is saved at
# most every SAVE_EVERY_S, at once after a fill, settlement, stop, release or owner action, and at startup and shutdown;
# each full save empties the journal in the same transaction. A restart reads the last full save plus the journal.
JOURNAL_KEY, SAVE_EVERY_S = "kalshi_live_journal", 1.0
# A journaled order with no Kalshi order id and no fill (a crash between the journal row and the send, or a create
# lost on the way) is released only once its market has closed, so no copy of the request can still execute, and
# two complete order lists read after the close, at least ORDER_LIST_LAG_S apart, leave it out while its window's
# account facts agree (see _release_proof). Absence alone proves nothing while the market trades: a request held in
# a network buffer can arrive late. While one waits, complete lists are read every ORDER_LIST_LAG_S.
# Receipts kept out of the panel's latest events: the status line, and one line per finished pull (each pull's
# cancels are events already; a busy minute of pulls would otherwise push the orders and fills out).
QUIET_RECORDS = frozenset({"speeddesk_live_status", "speeddesk_live_pull", "speeddesk_fill_observed",
                           "speeddesk_fill_markout", "speeddesk_fill_markout_gap",
                           "speeddesk_fill_markout_status", "speeddesk_reconcile_trace"})
PULL_REASON = "Bids pulled: the fair value just moved; no new bid until the hold ends"
# How often the practice twin may try the bid a held window would get without the pull (see _twin_unpulled_bid).
TWIN_RETRY_S = 1.0
# While the pull is on, a new order waits when the last second already used all but CANCEL_ROOM of the client's
# writes, so a pull's two cancels never queue behind creates (review, 2026-10-13: six writes in 0.6 s otherwise).
CANCEL_ROOM = 2
WRITE_ROOM_REASON = "Keeping write room for cancels; the next bid waits a moment"


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


class _Interval:
    """Timings (ms) and counts since the last status line, summarized there and then cleared. Logging only."""

    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = {}
        self.counts: dict[str, int] = {}

    def add(self, name: str, value_ms: float) -> None:
        bucket = self.samples.setdefault(name, [])
        if len(bucket) < SAMPLE_LIMIT:
            bucket.append(value_ms)
        self.count(name)

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def summary(self) -> dict[str, Any]:
        timings = {name: {"n": self.counts.get(name, len(values)), **_spread(values)}
                   for name, values in self.samples.items()}
        counts = {name: value for name, value in self.counts.items() if name not in self.samples}
        self.samples, self.counts = {}, {}
        return {"ms": timings, "counts": counts}


class _ClockOffsets:
    """Venue clock minus local clock, from replies stamped by the venue: offset = venue stamp minus the midpoint
    of the local send and reply times, uncertain by half the round trip. The status line shows each source's
    sample with the shortest round trip since the previous line, and keeps the last one when none came."""

    def __init__(self) -> None:
        self.best: dict[str, dict[str, Any]] = {}
        self.last: dict[str, dict[str, Any]] = {}
        self.samples: dict[str, int] = {}

    def observe(self, source: str, venue_s: float, sent_s: float, received_s: float) -> dict[str, float] | None:
        if not all(math.isfinite(value) for value in (venue_s, sent_s, received_s)) or received_s < sent_s:
            return None
        sample = {"offset_ms": round((venue_s - (sent_s + received_s) / 2) * 1000, 1),
                  "rtt_ms": round((received_s - sent_s) * 1000, 1), "at": received_s}
        self.samples[source] = self.samples.get(source, 0) + 1
        if source not in self.best or sample["rtt_ms"] < self.best[source]["rtt_ms"]:
            self.best[source] = sample
        self.last[source] = sample
        return {"offset_ms": sample["offset_ms"], "rtt_ms": sample["rtt_ms"]}

    def summary(self) -> dict[str, Any]:
        out = {source: {**self.best.get(source, sample), "samples": self.samples.get(source, 0),
                        "fresh": source in self.best}
               for source, sample in self.last.items()}
        self.best, self.samples = {}, {}
        return out


def coinbase_time() -> float:
    """Coinbase Exchange's clock in epoch seconds (public, no key). One kept-alive connection per thread."""
    response = thread_session().get(COINBASE_TIME, timeout=(2.0, 2.0))
    response.raise_for_status()
    epoch = response.json()["epoch"]
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or not math.isfinite(epoch):
        raise ValueError("Invalid Coinbase time")
    return float(epoch)



def _spread(values: list[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    if not ordered:
        return {"median_ms": None, "p90_ms": None, "max_ms": None}
    return {"median_ms": round(ordered[(len(ordered) - 1) // 2], 1),
            "p90_ms": round(ordered[math.ceil(.9 * len(ordered)) - 1], 1), "max_ms": round(ordered[-1], 1)}


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

    @property
    def read_stats(self) -> dict[str, dict[str, int | None]]:
        return getattr(self._client, "read_stats", {})  # type: ignore[no-any-return]

    def cancel(self, order_id: str, *, ticker: str) -> dict[str, Any]:
        return self._client.cancel(order_id, ticker=ticker)  # type: ignore[no-any-return]

    def close(self) -> None:
        self._client.close()

    def request_timings(self) -> dict[str, Any]:
        read = getattr(self._client, "request_timings", None)
        return read() if callable(read) else {"samples": [], "dropped": 0}


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("Boolean is not a monetary amount")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite account value")
    return number


def _same_terms(raw: dict[str, Any], intent: Intent) -> bool:
    """Whether a listed order has the terms ``intent`` was sent with (market, side, size, limit price), whatever its
    client id: the bot's own order would, as _validate_order requires of every listed bot order. Unreadable terms
    prove nothing, so they count as the same."""
    outcome = "yes" if intent.side == "up" else "no"
    try:
        return (raw.get("ticker") == intent.window and raw.get("outcome_side") == outcome
                and raw.get("book_side") == ("bid" if intent.side == "up" else "ask")
                and abs(_number(raw["initial_count_fp"]) - intent.size) <= EPS
                and abs(_number(raw[f"{outcome}_price_dollars"]) - intent.price) <= EPS)
    except (KeyError, TypeError, ValueError):
        return True


def _stamp(value: Any) -> float:
    if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
        moment = datetime.fromisoformat(value)
        if moment.utcoffset() is None:
            raise ValueError("Venue timestamp must include its UTC offset")
        return moment.timestamp()
    return _number(value)


def _secret(value: Secret | str | None) -> str:
    return value.reveal() if isinstance(value, Secret) else value or ""


def replay_journal(saved: dict[str, Any], journal: Any) -> list[str]:
    """Add the orders journaled before their send since ``saved`` was written; returns their client ids.

    Each entry holds exactly what the full save would have held for that order (its reservation, its intent,
    the window when new, and whether it opened the window), so the merged state is the save made at that moment.
    """
    if journal is None:
        return []
    if not isinstance(journal, dict) or journal.get("version") != 1 or not isinstance(journal.get("intents"), dict):
        raise ValueError("Invalid real pre-send journal")
    replayed = []
    for key, entry in journal["intents"].items():
        if key in saved["intents"]:
            continue  # a later full save already holds it
        window = entry["intent"]["window"]
        if window not in saved["book"]["windows"]:
            saved["book"]["windows"][window] = entry["window"]
            saved["book"]["inventory"][window] = asdict(Inventory())
        saved["book"]["intents"][key] = entry["book"]
        saved["intents"][key] = entry["intent"]
        if entry["bootstrap"]:
            saved["book"]["bootstrap_order"][window] = key
        replayed.append(key)
    return replayed


def durable_state(ledger: Ledger) -> dict[str, Any] | None:
    """What a restart reads, before archived windows are merged: the last full save plus the pre-send journal."""
    saved = ledger.get_kv(STATE_KEY)
    if saved is not None:
        replay_journal(saved, ledger.get_kv(JOURNAL_KEY))
    return saved


class KalshiLiveDesk:
    """One serialized controller; network work never blocks the Bitcoin feed."""

    def __init__(self, settings: Settings, directory: Path, snapshot: Callable[[], LiveSnapshot], *,
                 clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic,
                 client_factory: Callable[[], Any] | None = None,
                 direct_member_verified: bool = False,
                 time_probe: Callable[[], float] = coinbase_time) -> None:
        self.settings, self.directory, self.snapshot, self.clock = settings, directory, snapshot, clock
        self.monotonic = monotonic
        self.work_trace: WorkTrace | None = WorkTrace(monotonic=monotonic)
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
        self._read_workers: set[asyncio.Task[Any]] = set()
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
        # Orders journaled since the last full save (JOURNAL_KEY), unsaved changes, and the last daily-report pass.
        self.journal: dict[str, dict[str, Any]] = {}
        self.dirty = False
        self.saved_stops: tuple[Any, ...] = ()
        self.last_reports = -math.inf
        # When each journaled order with no Kalshi order id was first missing from a complete order list.
        self.unsent_absent: dict[str, float] = {}
        # The journal on disk holds entries the next full save must clear (set after a restart replayed them).
        self.journal_on_disk = False
        self.save_ms: float | None = None
        self.save_stages: dict[str, float | None] = {}
        self.retry_at = -math.inf
        self.cancel_retry_at: dict[str, float] = {}
        # Cancels Kalshi accepted (200) or answered with a definite 404 this run; only these are not sent again. A
        # requested cancel that failed or could not be sent yet goes out again (with its first reason) until then.
        self.cancel_acked: set[str] = set()
        self.cancel_reasons: dict[str, str] = {}
        # A cancel that failed goes out again only once an order list read since the failure still shows the order
        # open (rebreak, 2026-10-14: re-sent first thing in every step, a DELETE that kept failing after Kalshi had
        # already taken the order down set the backoff again each time, so the reconcile that would show it gone never
        # ran: no bid, fill or lock for as long as it failed). Each failure keeps order_reads as it was then.
        self.cancel_failed: dict[str, int] = {}
        self.order_reads = 0  # order-list reads begun this run (the read that settles each order's status)
        self.orders_read = 0  # the latest of those whose statuses were applied
        self.errors = 0
        # Definite single-order refusals since the last accepted create; three in a row pause.
        self.refusals = 0
        self.lock_notes: dict[str, str] = {}
        # Why a window got no first buy (once per window and reason), and which stops are latched (a change is
        # recorded once, durably).
        self.starter_notes: dict[str, str] = {}
        self.stop_state = (False, False)
        self.reason: str | None = "Practice only; live switches are off"
        self.foreign_windows: set[str] = set()
        self.changed_windows: set[str] = set()
        self.position_sizes: dict[str, float] = {}
        self.final_outcomes: dict[str, bool] = {}
        self.latest_events: list[dict[str, Any]] = []
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.markouts: FillMarkouts | None = None
        self.markout_error: str | None = None
        self.fatal_reason: str | None = None
        # Which reconciliation check stopped real orders, logged once per stop (and once after each restart).
        self.integrity_logged: str | None = None
        # What the owner's approved one-time reset of that stop is waiting for (each reason logged once).
        self.reset_blocker = ""
        self.reset_reported: set[str] = set()
        # When each order's Kalshi report was first seen trailing its booked fills (ORDER_LIST_LAG_S).
        self.order_list_lag: dict[str, float] = {}
        # When the last complete account read started (FULL_SCAN_S); and what each reconcile cost, for the status line.
        self.full_scan_at = -math.inf
        self.sync_stats = _Interval()
        self.last_sync_report: dict[str, Any] | None = None
        self._sync_reads: list[dict[str, Any]] = []
        self.read_trace: ReconcileTrace | None = ReconcileTrace()
        self.read_trace_error: str | None = None
        self._trace_pending: list[dict[str, Any]] = []
        self._trace_dropped = 0
        # Speed plan step 0: time in each part of step(), event-loop lag, cancel timings and venue clock offsets.
        self.phase_stats = _Interval()
        self.loop_stats = _Interval()
        self.request_stats = _Interval()
        self.clock_offsets = _ClockOffsets()
        self.time_probe = time_probe
        limits = LiveLimits(window_usd=settings.speeddesk_kalshi_window_usd,
                            open_usd=settings.speeddesk_kalshi_open_usd,
                            day_loss_usd=settings.speeddesk_kalshi_day_stop_usd,
                            total_loss_usd=settings.speeddesk_kalshi_total_stop_usd,
                            pair_cap=settings.speeddesk_pair_cap,
                            max_imbalance=settings.speeddesk_max_imbalance,
                            clip=settings.speeddesk_kalshi_clip, cutoff_s=settings.speeddesk_kalshi_cutoff_s,
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
            if saved is None and self.ledger.get_kv(JOURNAL_KEY) is not None:
                raise ValueError("Real pre-send journal without a saved state")
            if saved is None:
                self.book = LiveRiskBook(limits)
                self.intents: dict[str, Intent] = {}
                self.twin = PracticeDesk(twin_config)
                self.started_at = clock()
            else:
                if saved.get("version") != 1:
                    raise ValueError("Unsupported real receipt ledger version")
                self._merge_archive(saved)
                journal = self.ledger.get_kv(JOURNAL_KEY)
                replayed = replay_journal(saved, journal)
                self.journal_on_disk = bool(journal and journal.get("intents"))
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
                for key in replayed:  # saved in full by the startup save below, which empties the journal
                    self._record("speeddesk_live_order", client_order_id=key, window=self.intents[key].window,
                                 state="restored from the pre-send journal; reconciling with Kalshi")
            # The bid pull (owner, 2026-10-13 ~20:15 UTC) and its live control: twin bids the old rule keeps resting
            # while the real ones are pulled (twin order ids; twin orders never survive a restart).
            self.pull = PullGuard(PullRule.from_settings(settings), clock(), saved.get("pull") if saved else None)
            self.twin_kept: set[int] = set()
            # Sides whose kept twin bid the rule without the pull just repriced: that rule bids again at once, while
            # the real bid there (decided after the pull) may still rest, so the twin gets its own (_decide).
            self.twin_owed: dict[tuple[str, Side], float] = {}
            self._twin_tried: dict[tuple[str, str], float] = {}
            # Real resting bids the send guard refused only because of the pull (the HTTP worker adds, the loop reads).
            self._pull_refused: set[str] = set()
            self._pull_ab: tuple[tuple[Any, ...], dict[str, Any]] | None = None
            self.metrics = LatencyMetrics(clock(), saved.get("latency_metrics") if saved else None)
            self.evidence = WindowEvidence(clock(), saved.get("window_evidence") if saved else None)
            self.reports: dict[str, dict[str, Any]] = dict(saved.get("reports", {})) if saved else {}
            # The earned-growth ladder (owner, 2026-10-13: "Max $50,000 a window build the ladder"): the risk book
            # asks it for each window's limits. Its state is a top-level key the previous release ignores.
            self.ladder = Ladder(limits, enabled=settings.speeddesk_kalshi_ladder,
                                 max_window_usd=settings.speeddesk_kalshi_ladder_max_window_usd)
            # Restored stops are not new events. Seed before any startup risk evaluation can latch another.
            self.stop_state = (self.book.halted, self.book.day_latched(clock()))
            started = self.ladder.start(self.book, clock(), saved.get("ladder") if saved else None)
            self.ladder.attach(self.book)
            self.ladder.observe(self.book, clock())  # a saved stop is noted before a token below can clear it
            # A stop that binds (no room for even a one-contract hedged first buy) latches now, before any token is
            # read, so a token set for it is applied to it rather than judged while nothing is latched.
            self.book.latch_bound_stops(clock())
            self._watch_stops("at start")
            self.ladder_at = -math.inf
            self._mirror_twin(self.book.limits_now(clock()))
            self._record("speeddesk_live_ladder", action="start", state=started, rung=self.ladder.rung_for(clock()),
                         limits=limits_view(self.book.limits_now(clock())), ladder_rung=self.ladder.state.rung,
                         effective_from=self.ladder.state.rung_from, top_rung=self.ladder.top,
                         max_window_usd=self.ladder.max_window_usd)
            resumed = self.book.resume(_secret(settings.speeddesk_kalshi_resume_token))
            if resumed:
                self._record("speeddesk_live_resume", state=RESUME_STATES[resumed], total_pnl_usd=self.book.realized_pnl,
                             counted_from_usd=self.book.stop_anchor if resumed == "applied" else None,
                             total_halted=self.book.halted)
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
                # The practice twin's day counts from the same moment, so the A/B control is not left frozen by
                # its own copy of the daily stop while the real book trades again.
                self.twin.apply_day_reset(reset_at)
                self._record("speeddesk_live_day_reset", day=utc_day(reset_at),
                             counted_from_usd=self.book.day_anchor[utc_day(reset_at)],
                             state="fresh daily budget from now until 00:00 UTC; caps and lifetime stop unchanged",
                             practice_twin_counted_from_usd=self.twin.day_anchor[utc_day(reset_at)])
            elif day_reset == "used":
                self._record("speeddesk_live_day_reset", state="ignored; this value was already used")
            # Tokens can clear a stop just recorded above. A later new latch must receive its own receipt.
            self.stop_state = (self.book.halted, self.book.day_latched(clock()))
            try:
                self.markouts = FillMarkouts(self.clock(), self.monotonic())
            except Exception as exc:  # noqa: BLE001 - observation failure never changes trading authority.
                self.markout_error = type(exc).__name__
            self._record("speeddesk_fill_markout_status", **self._markout_panel())
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
        """Unfinished orders, oldest first. Only an open window's orders can be unfinished (a window settles once
        none is, and only an integrity error reopens one), so the risk book's index of open windows is enough; the
        full scan stays for an integrity error or books that are not the same orders (latency review, 2026-10-13:
        this ran over every order ever made, many times a step)."""
        if self.book.integrity_error or len(self.intents) != len(self.book.intents):
            return [intent for intent in self.intents.values() if not intent.terminal]
        return [intent for key in self.book.open_intent_ids()
                if (intent := self.intents.get(key)) is not None and not intent.terminal]

    def _record(self, receipt_kind: str, **payload: Any) -> None:
        item = {"at": self.clock(), "venue": "kalshi", **payload}
        self.pending.append((receipt_kind, item))
        if receipt_kind not in QUIET_RECORDS:
            self.latest_events.append({"event": receipt_kind, **item})
            self.latest_events = self.latest_events[-20:]

    def _markout_call(self, method: str, *args: Any, **kwargs: Any) -> None:
        """Optional evidence only; no exception may reach the account/decision controller."""
        if self.markouts is None:
            return
        try:
            for row in getattr(self.markouts, method)(*args, **kwargs):
                event = row.pop("event")
                self._record(event, **row)
        except Exception as exc:  # noqa: BLE001 - disable broken diagnostics, never real cancellations.
            self.markout_error = type(exc).__name__
            self.markouts = None
            self._record("speeddesk_fill_markout_status", **self._markout_panel())

    def _markout_panel(self) -> dict[str, Any]:
        try:
            return ({**self.markouts.status(), "error": self.markout_error,
                     "own_depth_policy": "all_original_bot_order_sizes_in_window"}
                    if self.markouts is not None else
                    {"mode": "diagnostic", "enabled": False, "error": self.markout_error,
                     "coverage": "unknown; diagnostic unavailable", "realized_pnl": False})
        except Exception as exc:  # noqa: BLE001 - display diagnostics cannot disable real cleanup.
            return {"mode": "diagnostic", "enabled": False, "error": type(exc).__name__,
                    "coverage": "unknown; status unavailable", "realized_pnl": False}

    def _markout_book(self, book: Book) -> None:
        if self.markouts is None:
            return
        try:
            now, mono = self.clock(), self.monotonic()
            if not self.markouts.needs_book(book.window, book.side, mono):
                return
            own_bids: dict[float, float] = {}
            # A fresh buffered quote may predate a cancel or partial fill already reconciled here.
            # Exclude each own order's original size for this entire window, even after cancellation.
            # This deliberately understates outside liquidity rather than counting a stale own bid.
            for order in self.book._window_intents(book.window):
                if order.side == book.side:
                    own_bids[order.price] = own_bids.get(order.price, 0.0) + order.size
            self._markout_call("on_book", book, now=now, mono=mono, own_bids=own_bids,
                               ownership_unknown=book.window in self.foreign_windows
                               or bool(self.book.integrity_error))
        except Exception as exc:  # noqa: BLE001 - no diagnostic can break the feed or trading loop.
            self.markout_error = type(exc).__name__
            self.markouts = None
            self._record("speeddesk_fill_markout_status", **self._markout_panel())

    def _trace_call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Timing evidence has no authority over account state or cancellation."""
        if self.read_trace is None:
            return None
        try:
            return getattr(self.read_trace, method)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - fail only the optional observer.
            self.read_trace_error = type(exc).__name__
            self.read_trace = None
            return None

    def _trace_span(self, span: ReadSpan | None, method: str, *args: Any) -> None:
        if span is None or self.read_trace is None:
            return
        try:
            getattr(span, method)(*args)
        except Exception as exc:  # noqa: BLE001 - also isolated inside account worker threads.
            self.read_trace_error = type(exc).__name__
            self.read_trace = None

    def _trace_finish(self, failed: bool) -> None:
        row = self._trace_call("finish", self.clock(), self.monotonic(), failed)
        if row is not None:
            # Synchronous callback intervals share the read trace's monotonic clock.
            # Nested intervals overlap; union coverage is not their summed wall/CPU time.
            try:
                if self.work_trace is not None and self.read_trace is not None:
                    base = self.read_trace.base
                    row["callback_work"] = self.work_trace.overlap(base, self.monotonic(), max_spans=32)
                    row["read_resume_work"] = [
                        {"read": read["read"], **self.work_trace.overlap(
                            base + marks["worker_completed"] / 1000,
                            base + marks["coroutine_resumed"] / 1000, max_spans=8)}
                        for read in row["reads"]
                        if "worker_completed" in (marks := read["marks_ms"])
                        and "coroutine_resumed" in marks]
            except Exception:  # noqa: BLE001 - the observer cannot interrupt fills, cancels or persistence.
                self.work_trace = None
            # Keep diagnostics out of `pending`: that collection can advance the
            # heartbeat's save cadence. Publish at the next already-chosen save.
            if len(self._trace_pending) == MAX_REPORTS_PER_MINUTE:
                self._trace_pending.pop(0)
                self._trace_dropped += 1
            self._trace_pending.append(row)

    def _trace_flush(self) -> None:
        rows, self._trace_pending = self._trace_pending, []
        for row in rows:
            try:
                self._record("speeddesk_reconcile_trace", **row)
            except Exception as exc:  # noqa: BLE001 - diagnostic publication cannot fail a reconcile.
                self.read_trace_error = type(exc).__name__
                self.read_trace = None
                break

    def _trace_panel(self) -> dict[str, Any]:
        return {**(self._trace_call("status") or
                   {"mode": "diagnostic", "enabled": False, "error": self.read_trace_error}),
                "callback_work": self._work_trace_status(),
                "publication": "next_existing_checkpoint", "buffered": len(self._trace_pending),
                "buffer_dropped": self._trace_dropped}

    def _work_trace_status(self) -> dict[str, Any]:
        try:
            return self.work_trace.status() if self.work_trace is not None else {"enabled": False}
        except Exception:  # noqa: BLE001 - optional diagnostics have no trading authority.
            self.work_trace = None
            return {"enabled": False}

    def _start_io(self, callback: Callable[..., Any], *args: Any,
                  _read_span: ReadSpan | None = None, **kwargs: Any) -> asyncio.Task[Any]:
        queued = self.monotonic()
        stamps: list[float] = []
        name = getattr(callback, "__name__", "")
        operation = name if name in {"balance", "list_orders", "fills", "positions", "settlements",
                                     "subaccount_balances", "create_order", "cancel"} else "other"

        def invoke() -> Any:
            stamps.append(self.monotonic())
            self._trace_span(_read_span, "mark", "worker_started", stamps[0])
            try:
                return callback(*args, **kwargs)
            finally:
                stamps.append(self.monotonic())
                self._trace_span(_read_span, "mark", "worker_completed", stamps[1])

        def finished(task: asyncio.Task[Any]) -> None:
            if len(stamps) == 2:
                self.loop_stats.add(f"{operation}_worker_queue", max(0.0, stamps[0] - queued) * 1000)
                self.loop_stats.add(f"{operation}_worker_resume", max(0.0, self.monotonic() - stamps[1]) * 1000)
            self._io_finished(task)

        task = asyncio.create_task(asyncio.to_thread(invoke))
        self._workers.add(task)
        task.add_done_callback(finished)
        return task

    def _io_finished(self, task: asyncio.Task[Any]) -> None:
        self._workers.discard(task)
        self._read_workers.discard(task)
        if not task.cancelled():
            task.exception()  # retrieve errors even if the shielded caller was cancelled during shutdown

    async def _io(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        task = self._start_io(callback, *args, **kwargs)
        return await asyncio.shield(task)

    async def _read(self, name: str, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        started = self.monotonic()
        span = self._trace_call("read_start", name, started)
        task = self._start_io(callback, *args, _read_span=span, **kwargs)
        self._read_workers.add(task)
        while not task.done():
            # wait() never cancels a still-running HTTP worker. This coroutine remains the only account/risk
            # writer, and never creates orders while the account response is pending. A cancelled caller leaves
            # the shielded worker tracked for shutdown; there is no detached cancellation task.
            done, _ = await asyncio.wait({task}, timeout=CANCEL_CHECK_S)
            if not done:
                cancel_start = self.monotonic()
                try:
                    await self._cancel_unsafe()
                finally:
                    self._trace_span(span, "cancel", "pending_read", cancel_start, self.monotonic())
        self._trace_span(span, "mark", "coroutine_resumed", self.monotonic())
        result = await asyncio.shield(task)
        stats = getattr(self.client, "read_stats", None)
        pages = stats.get(name) if isinstance(stats, dict) else None
        self._sync_reads.append({"read": name, "ms": round((self.monotonic() - started) * 1000, 1),
                                 "rows": len(result) if isinstance(result, list) else None,
                                 "pages": pages.get("pages") if isinstance(pages, dict) else None,
                                 "bytes": pages.get("bytes") if isinstance(pages, dict) else None})
        self._trace_span(span, "complete", len(result) if isinstance(result, list) else None,
                         pages.get("pages") if isinstance(pages, dict) else None,
                         pages.get("bytes") if isinstance(pages, dict) else None)
        # Re-check once before applying the completed response as well.
        cancel_start = self.monotonic()
        try:
            await self._cancel_unsafe()
        finally:
            self._trace_span(span, "cancel", "completed_read", cancel_start, self.monotonic())
        self._trace_span(span, "mark", "wrapper_returned", self.monotonic())
        return result

    def _full_scan_due(self, now: float) -> bool:
        """Startup, every FULL_SCAN_S, and the first read after a window opens read the complete history; so does
        every read while the owner's approved integrity reset waits (only a complete read can clear it, and real
        orders are stopped then anyway). An unsent order waiting for its release after the close gets a complete
        read at once and then every ORDER_LIST_LAG_S, so it is proven 30 s after the close, not 60 to 120."""
        waiting = self._awaiting_release(now)
        return (not self.startup_done or now - self.full_scan_at >= FULL_SCAN_S
                or self.book.integrity_reset_armed is not None
                or any(self.full_scan_at < window.start <= now for window in self.book.windows.values())
                or any(key not in self.unsent_absent for key in waiting)
                or (bool(waiting) and now - self.full_scan_at >= ORDER_LIST_LAG_S))

    def _awaiting_release(self, now: float) -> list[str]:
        """Orders that may never have reached Kalshi (no order id, nothing filled, still reserved) in a market that
        has closed: the ones _release_unsent decides."""
        return [intent.client_order_id for intent in self._active()
                if not intent.order_id and (reserved := self.book.intents[intent.client_order_id]).order_id is None
                and reserved.reservation_active and reserved.filled_size <= EPS
                and now >= self.book.windows[intent.window].end]

    def _recent_since(self, now: float) -> int:
        """Kalshi min_ts covering every order and fill that can still change the books (see RECENT_S).

        Every unfinished, uncertain or reserved order was created after its intent's decision time, and its fills
        after that (``_fill`` refuses earlier ones), so they are inside the bound whether Kalshi filters orders on
        their creation or their last update. So is every order and fill of a window open now (at most RECENT_S old).
        """
        candidates = (self.intents.items() if self.book.integrity_error or len(self.intents) != len(self.book.intents)
                      else ((key, self.intents[key]) for key in self.book.open_intent_ids() if key in self.intents))
        unfinished = [intent.at for key, intent in candidates
                      if not intent.terminal or intent.uncertain or self.book.intents[key].reservation_active]
        return max(0, math.floor(min([now - RECENT_S, *unfinished])) - int(READ_MARGIN_S))

    def _sync_report(self, full: bool, started: float, checks: list[str], failed: bool = False) -> None:
        total = (self.monotonic() - started) * 1000
        self.sync_stats.add("full_ms" if full else "recent_ms", total)
        for read in self._sync_reads:
            self.sync_stats.add(f"{read['read']}_ms", read["ms"])
            for key in ("pages", "rows", "bytes"):
                if isinstance(read[key], int):
                    self.sync_stats.count(f"{key}", read[key])
        for check in checks:
            self.sync_stats.count(f"check_{check}")
        if failed:
            self.sync_stats.count("failed")
        tally: dict[str, int] = {}
        for check in checks:
            tally[check] = tally.get(check, 0) + 1  # counts, not a list: one entry per order would grow the line
        self.last_sync_report = {"full": full, "ms": round(total, 1), "failed": failed, "checks": tally,
                                 "reads": self._sync_reads}

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

    @observed("live_checkpoint")
    def checkpoint(self, durable: bool = False) -> None:
        started = time.perf_counter()
        self._trace_flush()
        # Reconciliation can save a new settlement before the next heartbeat. Never save a latched stop
        # without its receipt: a crash would otherwise restore it as old and suppress the only receipt.
        self._watch_stops()
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
                self.cancel_acked.discard(key)
                self.cancel_reasons.setdefault(key, "reopened")
        if durable or self.clock() - self.last_reports >= 60:  # completed days change rarely: not on every save
            self._daily_reports()
            self.last_reports = self.clock()
        with work_span(self.work_trace, "live_state"):
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
                     "pull": self.pull.to_state(),
                     "foreign_windows": sorted(self.foreign_windows), "final_outcomes": self.final_outcomes,
                     "changed_windows": sorted(self.changed_windows),
                     "latency_metrics": self.metrics.state(),
                     "window_evidence": self.evidence.state(),
                     "reports": self.reports, "ladder": self.ladder.to_state(),
                     "latest_events": self.latest_events}
        building = time.perf_counter()
        with work_span(self.work_trace, "live_ledger"):
            self.ledger.set_synchronous(durable or any(kind in OWNER_RECORDS for kind, _ in self.pending))
            with self.ledger.transaction():
                for kind, payload in self.pending:
                    self.ledger.append_receipt(kind, payload, ts=payload["at"])
                if chunk is not None:
                    self.ledger.set_kv(f"{ARCHIVE_KEY}{self.archive_chunks}", chunk)
                self.ledger.set_kv(STATE_KEY, state)
                if self.journal or self.journal_on_disk:  # the full state now holds every journaled order
                    self.ledger.set_kv(JOURNAL_KEY, {"version": 1, "intents": {}})
        saved = time.perf_counter()
        self.journal.clear()
        self.journal_on_disk = False
        self.dirty, self.saved_stops = False, self._stops()
        if chunk is not None:  # only once the chunk and the state that lists it are committed together
            self.archived |= cold
            self.archive_chunks += 1
            for part in WINDOW_PARTS:
                self.archive_parts[part].update(chunk["book"][part])
            self.archive_parts["live_intents"].update(chunk["intents"])
        with work_span(self.work_trace, "live_logs"):
            for kind, payload in self.pending:
                log.info("%s %s", kind, json.dumps(payload, allow_nan=False, separators=(",", ":")))
            self.pending.clear()
        mirror_ms = None
        if self.stopping or self.clock() - self.last_mirror >= MIRROR_EVERY_S:
            with work_span(self.work_trace, "live_mirror"):
                mirroring = time.perf_counter()
                # The money page reads the panel from this display copy only; the ledger state never needed it.
                full = {**state, "intents": {**self.archive_parts["live_intents"], **state["intents"]},
                        "book": {**state["book"], **{part: {**self.archive_parts[part], **state["book"][part]}
                                                     for part in WINDOW_PARTS}}, "panel": self.panel()}
                temporary = self.path.with_suffix(".tmp")
                with temporary.open("w", encoding="utf-8") as stream:
                    # Encode once, avoiding a Python write call for every JSON fragment.
                    stream.write(json.dumps(full, allow_nan=False, separators=(",", ":")))
                os.replace(temporary, self.path)
                self.last_mirror = self.clock()
                mirror_ms = (time.perf_counter() - mirroring) * 1000
        self.last_checkpoint = self.clock()
        self.save_ms = (time.perf_counter() - started) * 1000
        self.save_stages = {"build_ms": (building - started) * 1000, "ledger_ms": (saved - building) * 1000,
                            "mirror_ms": mirror_ms}

    def _journal_intent(self, intent: Intent, window: Window, *, durable: bool = True) -> None:
        """The one write before an order's first network byte: its identity and complete reservation, synced.

        It holds exactly what a full save would add for this order (``replay_journal``), so a crash right after it
        restores the same books; every other change since the last full save is one the next reconcile proves.
        ``durable=False`` rewrites an entry after a definite refusal (nothing was sent: a lost write only brings
        back the reservation the synced row holds, which the release path then proves away).
        """
        reserved = self.book.intents[intent.client_order_id]
        spec = self.book.windows[window.slug]
        self.journal[intent.client_order_id] = {
            "book": without_default_lock(asdict(reserved)), "intent": without_default_lock(asdict(intent)),
            "window": asdict(spec), "bootstrap": self.book.bootstrap_order.get(window.slug) == intent.client_order_id}
        self.ledger.set_synchronous(durable)
        with self.ledger.transaction():
            self.ledger.set_kv(JOURNAL_KEY, {"version": 1, "intents": self.journal})

    def _save_soon(self) -> None:
        """A change the next full save holds (at most SAVE_EVERY_S later); Kalshi can prove it again after a crash."""
        self.dirty = True

    def _twin_events(self, events: list[Any]) -> None:
        for event in events:
            if event.event != "speeddesk_skip":
                self._record("speeddesk_twin", **asdict(event))
                if event.event == "speeddesk_fill":
                    self.evidence.fill({**asdict(event), "is_taker": event.kind == "take"})

    def on_tick(self, price: float, event_at: float, received_at: float) -> None:
        if -FUTURE_SKEW_S <= received_at - event_at <= 3:
            self.twin.tick_btc(price, event_at)
            self._pull_watch(self.snapshot(), self.clock())
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
                    self._markout_call("expire", now=self.clock(), mono=self.monotonic(),
                                       reason="venue_terms_changed", window=window.slug)
                self.book.add_window(window)
                self.twin.add_window(replace(window))

    def observe_book(self, book: Book) -> None:
        """Raw diagnostic callback; invalid first quotes must not be replaced by better ones."""
        self._markout_book(book)

    def on_book(self, book: Book) -> None:
        self.observe_book(book)
        if book.window in self.twin.windows and self.twin.on_book(book):
            self._twin_events(self.twin.advance(self.clock()))
            self.wake.set()

    def on_trade(self, trade: Trade) -> None:
        if trade.window in self.snapshot().maker_windows:
            self._twin_events(self.twin.on_trade(trade, self.clock()))

    def on_status(self, status: dict[str, Any]) -> None:
        if status.get("coinbase") != "connected" or not status.get("trade_stream"):
            self.evidence.last_fresh.clear()
            self._markout_call("expire", now=self.clock(), mono=self.monotonic(),
                               reason="book_snapshot_invalidated")
        self.evidence.last_fresh.difference_update(status.get("gap_windows", []))
        for slug in status.get("gap_windows", []):
            self._twin_events(self.twin.cancel(self.clock(), slug, "venue_feed_gap"))
            self._markout_call("expire", now=self.clock(), mono=self.monotonic(),
                               reason="venue_feed_gap", window=slug)

    def on_settlement(self, window: str, up_wins: bool, now: float) -> None:
        self.final_outcomes[window] = up_wins
        self._markout_call("expire", now=self.clock(), mono=self.monotonic(),
                           reason="market_settled", window=window)
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
        if snapshot.bitcoin_at is None or not -FUTURE_SKEW_S <= now - self._bitcoin_fresh_at(snapshot) <= 3:
            return "Bitcoin feed stale"
        if snapshot.bitcoin_price is None or window.start_price is None:
            return "Bitcoin opening price missing"
        if snapshot.sigma is None:
            return "Warming up Bitcoin volatility"
        return self._book_reason(window, snapshot, now)

    @staticmethod
    def _bitcoin_fresh_at(snapshot: LiveSnapshot) -> float:
        """When the newest Bitcoin tick counts from: its exchange stamp, or its local receipt when that came first.

        A tick may be stamped up to FUTURE_SKEW_S after the local clock (clock skew). Judged on the stamp alone, the
        feed then stayed "fresh" up to 250 ms past 3 s of silence and the stale-feed cancel fired that much late
        (latency review, 2026-10-13); the receipt is when the bot really last heard from Coinbase.
        """
        assert snapshot.bitcoin_at is not None
        receipt = snapshot.tick_receipt
        if receipt is not None and receipt.exchange_at == snapshot.bitcoin_at:
            return min(snapshot.bitcoin_at, receipt.received_at)
        return snapshot.bitcoin_at

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

    def _trade_reason(self, *, balancing: bool = False) -> str:
        return self._standing_reason(balancing=balancing) or self._waiting_reason()

    def _standing_reason(self, *, balancing: bool = False) -> str:
        """Why real money is off or stopped: gates, failures and financial stops."""
        if self.stopping or self.stop_event is not None and self.stop_event.is_set():
            return "Shutting down; no new orders"
        if reason := self._gates():
            return reason
        if self.fatal_reason:
            return self.fatal_reason
        if not self.authenticated:
            return "Waiting for a successful balance read this run"
        return self._risk_stop_reason(balancing=balancing)

    def _waiting_reason(self) -> str:
        """Seconds-long pauses between orders while real money stays on."""
        if not self.startup_done:
            return "Reconciling startup orders"
        if self.account_at is None or not 0 <= self.clock() - self.account_at <= 3:
            return "Kalshi account data stale"
        if any(intent.uncertain or intent.cancel_requested for intent in self._active()):
            return "Reconciling an uncertain order; no new orders"
        return ""

    def _risk_stop_reason(self, *, balancing: bool = False) -> str:
        risk = self.book.risk_status(self.clock())
        if risk["integrity_error"]:
            return "Practice only; real account reconciliation needs review"
        if risk["halted"] and (not balancing or self.book.halt_reason != "total_loss"):
            return "Total loss stop; no new bets until a new resume token"
        if risk["day_stopped"] and not balancing:
            return "Daily loss stop; no new risk until 00:00 UTC or the owner's day reset"
        return ""

    async def _cancel_unsafe(self) -> None:
        if self.client is None:
            return
        snapshot, now = self.snapshot(), self.clock()
        self._pull_watch(snapshot, now)  # the pull's trigger check never waits for account data
        active = self._active()
        current = {intent.client_order_id for intent in active}
        self.cancel_acked &= current
        self.cancel_reasons = {key: value for key, value in self.cancel_reasons.items() if key in current}
        self.cancel_failed = {key: value for key, value in self.cancel_failed.items() if key in current}
        # The bid whose fair fell most goes first (after a rise, the Down bid is the one now priced too high).
        refresh = False
        for intent in sorted(active, key=lambda item: self._fair_drop(item, snapshot, now)):
            if refresh:
                # A prior cancel yielded to feeds; keep the initial priority order, but recheck fresh inputs.
                snapshot, now = self.snapshot(), self.clock()
                refresh = False
            window = self._current_window(intent.window, snapshot)
            shutting_down = self.stopping or self.stop_event is not None and self.stop_event.is_set()
            reason = (("shutdown" if shutting_down else "") or self._gates() or self.fatal_reason
                      or ("Repeated account errors" if self.errors >= 3 else ""))
            if shutting_down and intent.client_order_id in self.cancel_acked:
                continue
            if not reason and not intent.lock:
                # A lock buy is immediate-or-cancel and only completes pairs: the window
                # closing or a money stop is exactly when it must be left to finish.
                reason = (self._risk_stop_reason(balancing=self.book.strictly_balancing_intent(intent.client_order_id))
                          or (self._feed_reason(window, snapshot, now) if window else "Window missing"))
                if not reason and window is not None:
                    # The stale-bid rules first: the practice twin follows those, never the pull.
                    pulled = intent.kind == "rest" and self.pull.pulled_since(intent.window, intent.at)
                    reason = (self._stale_bid_reason(intent, window, snapshot, now,
                                                     min(STALE_BID_EDGE, self.settings.speeddesk_make_edge))
                              or ("pull" if pulled else ""))
                    if reason and intent.client_order_id in self.cancel_acked:
                        reason = ""  # Kalshi already acknowledged the cancel (200 or 404); the order list confirms it
                    elif reason and not intent.cancel_requested:
                        if pulled:  # counted once per bid, whichever rule named it (the twin follows the rule)
                            self.pull.note_bid(intent.window, now)
                        else:
                            # Once, when the cancel is first asked for: re-read before a new bid. A pulled window
                            # is held anyway and no order goes out until the order list confirms the cancel.
                            self.account_at = None
            again = (not reason and intent.cancel_requested and intent.client_order_id not in self.cancel_acked
                     and intent.client_order_id in self.cancel_reasons)
            if again:
                # Asked for this run but never accepted (it failed, or the order id was unknown): send it again.
                reason = self.cancel_reasons[intent.client_order_id]
            if reason and self.orders_read <= self.cancel_failed.get(intent.client_order_id, -1):
                continue  # it failed: sent again once an order list read since shows the order still open
            if reason:
                await self._cancel(intent, reason, twin=not again)
                refresh = True

    def _fair_drop(self, intent: Intent, snapshot: LiveSnapshot, now: float) -> float:
        """How far a resting bid's fair fell since it was priced (0 when unknown, or not a resting bid)."""
        window = self._current_window(intent.window, snapshot) if intent.kind == "rest" else None
        up = self._fair(window, snapshot, now) if window is not None else None
        return 0.0 if up is None else (up if intent.side == "up" else 1 - up) - intent.fair

    @staticmethod
    def _fair(window: Window, snapshot: LiveSnapshot, now: float) -> float | None:
        """The bot's Up fair value in ``window`` now: the one computation behind every decision, send check, stale-bid
        check and pull trigger, so they can never disagree (a change to fair_up's arguments goes here, once).

        Kalshi settles the window on the simple average of its last sixty one-second index values, which moves like
        the index AVERAGE_LEAD_S (39.5 s) before the close, so the horizon is that much shorter with a minute or more
        left (loss plan item 4, speed part 2; ``settles_on_average`` in speeddesk_model.fair_up).
        """
        if snapshot.bitcoin_price is None or window.start_price is None or snapshot.sigma is None:
            return None
        return fair_up(snapshot.bitcoin_price, window.start_price, snapshot.sigma, window.end - now,
                       settles_on_average=True)

    @staticmethod
    def _stale_bid_reason(intent: Intent | PracticeOrder, window: Window, snapshot: LiveSnapshot, now: float,
                          edge: float) -> str:
        """A resting bid priced from an old fair value (loss plan bug 2: at 9:08:39 AM PT on 2026-10-13 one stayed
        up for 20.7 s while fair rose about 7c, because the reprice in _decide waits for fresh account data).

        Cancelled whatever the account's freshness: fresh fair moved more than REPRICE_FAIR from the order's, or the
        bid sits above fresh fair minus ``edge`` (STALE_BID_EDGE, or the make edge when that is smaller, so a fresh bid
        is never cancelled on sight). A cancel never adds risk. Needs a fresh feed (checked first).
        """
        if intent.kind != "rest":
            return ""
        assert snapshot.bitcoin_price is not None and window.start_price is not None and snapshot.sigma is not None
        up = KalshiLiveDesk._fair(window, snapshot, now)
        if up is None:
            return ""
        fair = up if intent.side == "up" else 1 - up
        if abs(fair - intent.fair) > REPRICE_FAIR + EPS:
            return "reprice"
        return "bid_above_fair" if intent.price > fair - edge + EPS else ""

    # The bid pull (owner, 2026-10-13 ~20:15 UTC: "Pulling bids the instant price moves ... test with our current bot")
    # and its live control, the practice twin, which keeps the rule without the pull (docs/SPEEDDESK_SPEC.md 9.3).

    def _pull_watch(self, snapshot: LiveSnapshot, now: float) -> None:
        """The pull's trigger check: the bot's Up fair (as _decide computes it) in each open Bitcoin window, on every
        tick and every cancel check, so a pull never waits for account data. Logs each counted pull once it ends."""
        if not self.pull.rule.enabled:
            return
        counting = not self._gates()  # a pull counts (and is logged) only while real money is switched on
        for window in snapshot.windows:
            if window.slug not in self.book.windows or not window.start <= now < window.end:
                continue
            up = self._fair(window, snapshot, now)
            if up is not None:
                self.pull.observe(window.slug, up, now, count=counting and now < window.end - self.book.limits.lock_s)
        if self.pull.active:
            # A trigger just now: a hold survives a restart only once saved, and a cancel no longer saves (speed
            # plan step 2), so the next full save (within SAVE_EVERY_S) holds it.
            self._save_soon()
        for record in self.pull.expire(now):
            self._record("speeddesk_live_pull", **record)

    def _practice(self, name: str, action: Callable[..., Any], *args: Any) -> Any:
        """Practice-twin bookkeeping beside a real cancel, order or shutdown: an error there is counted in the status
        line (loop ``<name>_<error>``) and never reaches the real loop (rebreak, 2026-10-14: a twin error before a
        real cancel was sent stopped it, at shutdown too, and one in _decide paused trading as a Kalshi error)."""
        try:
            return action(*args)
        except Exception as exc:  # noqa: BLE001 - practice only; real cancels, orders and errors are unaffected.
            self.loop_stats.count(f"{name}_{type(exc).__name__}")
            return None

    def _twin_cancel(self, intent: Intent, reason: str) -> None:
        """A real cancel cancels the twin's bids in its window, except a pull: the twin is the pull's control, so its
        bid stays resting until the rule without the pull would cancel it (_twin_unpulled)."""
        if reason != "pull":
            self._twin_cancel_window(intent.window, reason)
        elif intent.twin_order_id in self.twin.orders:
            self.twin_kept.add(intent.twin_order_id)

    def _twin_cancel_window(self, window: str, reason: str) -> None:
        """What a real cancel or refusal does to the twin (as before the pull: every twin bid in the window), except
        the kept bids, which only the rule without the pull cancels (_twin_unpulled). Without the pull there are none,
        so this is exactly the old window-wide cancel."""
        now = self.clock()
        for order_id in [key for key, order in self.twin.orders.items()
                         if order.window == window and key not in self.twin_kept]:
            self._twin_events(self.twin.cancel_order(now, order_id, reason))

    def _twin_unpulled(self, snapshot: LiveSnapshot, now: float) -> None:
        """The twin's kept bids follow the rule without the pull: cancelled for what cancels a real resting bid there
        (live switches, failures and money stops, a stale, closing or owner's window, the stale-bid and reprice rules,
        no verified maker trades), never for a fast move alone."""
        self.twin_kept = {order_id for order_id in self.twin_kept if order_id in self.twin.orders}
        bidding = {window.slug for window in snapshot.windows if window.start <= now < window.end - self.book.limits.lock_s}
        self.twin_owed = {key: at for key, at in self.twin_owed.items() if key[0] in bidding}
        standing = (self._gates() or self.fatal_reason or ("Repeated account errors" if self.errors >= 3 else "")
                    or self._risk_stop_reason()) if self.twin_kept else ""
        for order_id in sorted(self.twin_kept):
            order = self.twin.orders[order_id]
            window = self._current_window(order.window, snapshot)
            reason = standing or (self._feed_reason(window, snapshot, now) if window else "Window missing")
            if not reason and window is not None:
                reason = (self._stale_bid_reason(order, window, snapshot, now,
                                                 min(STALE_BID_EDGE, self.settings.speeddesk_make_edge))
                          or self._take_available(order, window, snapshot, now)
                          or ("" if window.slug in snapshot.maker_windows else "maker_trades_unverified"))
            if reason:
                self.twin_kept.discard(order_id)
                self._twin_events(self.twin.cancel_order(now, order_id, reason))
                if reason in ("reprice", "bid_above_fair"):
                    # The rule without the pull rests a new bid there at once (_decide), even while the real bid
                    # there, decided after the pull, keeps resting (review, 2026-10-13: the twin was left bidless).
                    self.twin_owed[(order.window, order.side)] = now

    def _take_available(self, order: PracticeOrder, window: Window, snapshot: LiveSnapshot, now: float) -> str:
        """_decide's take-available reprice for a kept twin bid: the ask is cheap enough to take on that side, so the
        rule without the pull cancels the bid and takes (the twin then copies the real take). Off while takes are off
        (SPEEDDESK_TAKE_EDGE=1.0)."""
        book = snapshot.books.get((window.slug, order.side))
        ask = min(book.asks, key=lambda level: level.price, default=None) if book is not None else None
        up = self._fair(window, snapshot, now) if ask is not None else None
        if ask is None or up is None:
            return ""
        fair = up if order.side == "up" else 1 - up
        try:
            take = self.book.unit_reserve(window.slug, ask.price, "take") <= fair - self.settings.speeddesk_take_edge + EPS
        except (LiveRejected, ValueError):
            return ""
        return "take_available" if take else ""

    def _twin_unpulled_bid(self, window: Window, side: Side, price: float, fair: float, units: int,
                           now: float) -> None:
        """The resting bid the rule without the pull would send, in the practice twin only: in a held window, where
        the write room for cancels holds a real bid back, or where the twin's kept bid was just repriced (owed). Sized
        by the twin's own books (their caps mirror the real ones; the real risk book is never touched, so practice
        cannot trip a real stop or the ladder), none if the twin already has a bid on that side. Tried at most once a
        TWIN_RETRY_S per side, about as often as the real companion decides after an order."""
        if any(order.window == window.slug and order.side == side for order in self.twin.orders.values()):
            self.twin_owed.pop((window.slug, side), None)
            return
        if now - self._twin_tried.get((window.slug, side), -math.inf) < TWIN_RETRY_S:
            return
        self._twin_tried = {key: at for key, at in self._twin_tried.items() if now - at < TWIN_RETRY_S}
        self._twin_tried[(window.slug, side)] = now
        spec = self.twin.windows.get(window.slug)
        try:
            if (spec is None or spec.maker_coefficient is None
                    or fair - self.book.unit_reserve(window.slug, price, "rest") < self.settings.speeddesk_make_edge - EPS):
                return
            self._mirror_twin(self.book.limits_for(window.slug))
            size = next((size for size in range(units, 0, -1)
                         if not self.twin.can_buy(window.slug, side, price, float(size), spec.maker_coefficient)), 0)
        except (LiveRejected, ValueError):
            return
        if size:
            event = self.twin.place(window.slug, side, "rest", price, float(size), fair, now)
            if event.event == "speeddesk_rest":
                self.twin_kept.add(event.order_id)
                self.twin_owed.pop((window.slug, side), None)
                self._twin_events([event])

    def _pull_panel(self) -> dict[str, Any]:
        """Pulls today and the live control: the real companion against its practice twin on settled windows that
        started since the pull went live with these settings (P&L where both traded and where either traded, maker
        fills and real lock buys per window where either traded), and the same for the seven days before the pull
        first went live, the gap between real and practice fills that the pull did not cause. Display only: a
        failure here never stops a save (and so never a cancel)."""
        now, since, first = self.clock(), self.pull.since, self.pull.first_live
        key = (since, first, len(self.book.settled), len(self.twin.closed), len(self.book.fills),
               len(self.evidence.fills))
        if self._pull_ab is None or self._pull_ab[0] != key:
            control: dict[str, Any] = {"since_pull": None, "week_before": None}
            try:
                if since is not None:
                    control = self._pull_control(since, first if first is not None else since)
            except Exception as exc:  # noqa: BLE001 - display numbers only; the books and orders are unaffected.
                control = {"since_pull": None, "week_before": None, "error": type(exc).__name__}
            self._pull_ab = (key, control)
        return {**self.pull.panel(now), **self._pull_ab[1]}

    def _pull_control(self, since: float, first: float) -> dict[str, Any]:
        starts = {slug: window.start for slug, window in self.book.windows.items()}
        live = {slug: row.pnl_usd for slug, row in self.book.settled.items() if row.up_shares + row.down_shares > EPS}
        twin = {row.window: row.pnl_usd for row in self.twin.closed if row.up_shares + row.down_shares > EPS}
        live_maker = [(fill.window, fill.size) for fill in self.book.fills.values()
                      if self.intents[fill.client_order_id].kind == "rest"]
        twin_maker = [(str(row["window"]), float(row["size"])) for row in self.evidence.fills
                      if row.get("is_taker") is False]
        # Lock buys land on the real side only (the twin never locks): count them, so a pull that leaves more windows
        # half filled shows as more locks rather than hiding in the P&L.
        locks: dict[str, list[float]] = {}
        for fill in self.book.fills.values():
            if self.intents[fill.client_order_id].lock:
                row = locks.setdefault(fill.client_order_id, [0.0, 0.0])
                row[0] += fill.size
                row[1] += fill.size * fill.price + fill.fee_usd
        live_locks = [(self.intents[key].window, size, cost) for key, (size, cost) in locks.items()]
        # The baseline holds only windows that closed before the first go-live: the one open then already had pulls.
        closed = {slug: start for slug, start in starts.items() if self.book.windows[slug].end <= first}
        return {"since_pull": compare(starts, live, twin, live_maker, twin_maker, live_locks, start=since),
                "week_before": compare(closed, live, twin, live_maker, twin_maker, live_locks,
                                       start=first - 7 * 86400, end=first)}

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

    async def _cancel(self, intent: Intent, reason: str, *, twin: bool = True) -> None:
        """Cancel one real order. ``twin``: also what a real cancel does to the practice twin (not when an earlier
        cancel is only sent again after its reason passed: that reason no longer holds for the twin either)."""
        if intent.terminal:
            return
        key = intent.client_order_id
        if not intent.order_id and intent.cancel_requested and key in self.cancel_reasons and reason != "shutdown":
            return  # already asked; nothing can be sent until a reconcile learns the order id (then at once)
        if self.clock() < self.cancel_retry_at.get(key, -math.inf) and reason != "shutdown":
            return
        decided = self.monotonic()
        self.cancel_reasons.setdefault(key, reason)
        intent.cancel_requested = True
        self.book.request_cancel(key)
        if twin:
            self._practice("twin_cancel", self._twin_cancel, intent, reason)
        # No save before or after a cancel (speed plan step 2): it only lowers exposure, the reservation is kept
        # until Kalshi confirms, and a restart cancels every open order again (the pull's hold is saved with it).
        self._save_soon()
        if not intent.order_id:
            intent.uncertain = True
            self.book.mark_uncertain(key, "cancel_needs_order_id")
            self.cancel_acked.discard(key)
            self.cancel_retry_at.pop(key, None)  # no retry gate: sent as soon as a reconcile learns the order id
            return  # nothing was sent: the next read can find the id and the cancel go out at once
        self.cancel_retry_at[key] = self.clock() + 2
        sending, sent_wall = self.monotonic(), self.clock()
        try:
            reply = await self._io(self.client.cancel, intent.order_id, ticker=intent.window)
            self.cancel_acked.add(key)
            self.cancel_failed.pop(key, None)
            self._record("speeddesk_live_cancel", client_order_id=intent.client_order_id,
                         order_id=intent.order_id, window=intent.window, reason=reason,
                         state="requested; reservation retained until fills reconcile",
                         reduced_by=reply.get("reduced_by") if isinstance(reply, dict) else None,
                         timing=self._cancel_timing(decided, sending), venue=self._venue_stamp(reply, sent_wall))
        except KalshiClientError as exc:
            if exc.operation == "cancel" and exc.status == 404 and not exc.uncertain:
                # Nothing of ours is resting under that ID (already canceled or
                # filled; seen 2026-10-12 when a repeat cancel looped for minutes).
                # Keep the reservation and let the order list confirm it; this is
                # not an account error and must not pause trading.
                self.cancel_acked.add(key)
                self.cancel_failed.pop(key, None)
                self._record("speeddesk_live_cancel", client_order_id=intent.client_order_id,
                             order_id=intent.order_id, window=intent.window, reason=reason,
                             state="not resting on Kalshi (404); reservation retained until reconciled",
                             timing=self._cancel_timing(decided, sending))
            else:
                intent.uncertain = True
                self.cancel_acked.discard(key)  # sent again (_cancel_unsafe) once the retry gate passes
                self.cancel_failed[key] = self.order_reads  # and an order list read since still shows it open
                self.book.mark_uncertain(intent.client_order_id, "cancel_unconfirmed")
                self._error(exc)
                self.cancel_retry_at[intent.client_order_id] = self.retry_at
        except Exception as exc:  # noqa: BLE001 — uncertain cancellation retains the full reservation.
            intent.uncertain = True
            self.cancel_acked.discard(key)
            self.cancel_failed[key] = self.order_reads
            self.book.mark_uncertain(intent.client_order_id, "cancel_unconfirmed")
            self._error(exc)
            self.cancel_retry_at[intent.client_order_id] = self.retry_at

    def _cancel_timing(self, decided: float, sending: float) -> dict[str, float]:
        """Cancel decision to Kalshi's reply, and the request alone; the decision includes any save before it."""
        acked = self.monotonic()
        timing = {"decision_to_ack_ms": round((acked - decided) * 1000, 1),
                  "send_to_ack_ms": round((acked - sending) * 1000, 1)}
        self.loop_stats.add("cancel_decision_to_ack", timing["decision_to_ack_ms"])
        self.loop_stats.add("cancel_send_to_ack", timing["send_to_ack_ms"])
        return timing

    def _venue_stamp(self, reply: Any, sent_wall: float) -> dict[str, Any] | None:
        """Kalshi's reply time (ts_ms) beside the local send and reply times, and the clock offset they imply."""
        stamp = reply.get("ts_ms") if isinstance(reply, dict) else None
        if not isinstance(stamp, int) or isinstance(stamp, bool) or stamp <= 0:
            return None
        acked_wall = self.clock()
        offset = self.clock_offsets.observe("kalshi", stamp / 1000, sent_wall, acked_wall)
        return {"ts_ms": stamp, "sent_ms": round(sent_wall * 1000, 1), "acked_ms": round(acked_wall * 1000, 1),
                **(offset or {})}

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
        sync_started, started = self.clock(), self.monotonic()
        full = self._full_scan_due(sync_started)
        checks: list[str] = []
        self._sync_reads = []
        self._trace_call("begin", sync_started, started, full, max(0.0, self.retry_at - sync_started))
        try:
            await self._reconcile_reads(sync_started, full, checks)
        except BaseException:
            self._sync_report(full, started, checks, failed=True)
            self._trace_finish(failed=True)
            raise
        if full:
            self.full_scan_at = sync_started
        self._sync_report(full, started, checks)
        self._trace_finish(failed=False)

    async def _reconcile_reads(self, sync_started: float, full: bool, checks: list[str]) -> None:
        """One account reconcile; ``checks`` collects the name of each consistency check that failed."""
        assert self.client is not None
        facts = self._account_facts()
        # Recent reads (RECENT_S) between complete ones; see _recent_since for why nothing that can still change
        # the books is outside the bound. Untracked bot orders and old owner orders wait for the next complete read.
        recent_from = None if full else self._recent_since(sync_started)
        order_filter: dict[str, Any] = {} if recent_from is None else {"min_ts": recent_from}
        # Fully paginated reads return all pages or raise. Never interpret a
        # missing/failed page as zero inventory or a canceled order.
        orders = await self._read("list_orders", self.client.list_orders, **order_filter)
        owner_orders: dict[str, dict[str, Any]] = {}  # listed orders without the bot's client-id prefix, by id
        for raw in orders:
            client_id = str(raw.get("client_order_id", ""))
            ticker = str(raw.get("ticker", ""))
            if not ticker.startswith("KXBTC15M-"):
                continue
            if not client_id.startswith(PREFIX) and raw.get("order_id"):
                owner_orders[str(raw["order_id"])] = raw
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
        listed = {str(raw.get("client_order_id", "")) for raw in orders}
        money_changed = False
        unattributed: set[str] = set()  # windows with a fill Kalshi lists under an order id the bot does not know
        fills = await self._read("fills", self.client.fills,
                                 min_ts=max(0, int(self.started_at) - 60) if recent_from is None else recent_from)
        # Completion of the whole paginated account read, not the exchange/wire receipt of each fill.
        fills_batch_at, fills_batch_mono = self.clock(), self.monotonic()
        self._trace_call("fills_returned", fills_batch_at, fills_batch_mono)
        by_order = {intent.order_id: intent for intent in self.intents.values() if intent.order_id}
        for raw in fills:
            intent = by_order.get(str(raw.get("order_id", "")))
            if intent is None:
                ticker = str(raw.get("ticker", ""))
                if ticker.startswith("KXBTC15M-"):
                    unresolved = [item for item in self._active() if item.window == ticker and not item.order_id]
                    listed_as = owner_orders.get(str(raw.get("order_id", "")))
                    if listed_as is not None and not any(_same_terms(listed_as, item) for item in unresolved):
                        # A fill of an order Kalshi lists without the bot's client id, on terms no unsent bot order
                        # there has, is the owner's: the window is the owner's (and an unsent order there can still
                        # be proven away). On an unsent order's exact terms it could be that order's own, listed
                        # without its client id (rebreak, 2026-10-14: it was counted as the owner's and the order
                        # released, so the bot's own fill vanished), so it holds the order, as on the base.
                        self.foreign_windows.add(ticker)
                    elif unresolved:
                        checks.append("unattributed_fill_beside_unresolved_order")
                        unattributed.add(ticker)
                    else:
                        self.foreign_windows.add(ticker)
                continue
            fill = self._fill(raw, intent)
            if self.book.record_fill(fill):
                self._trace_call("fill", fill.fill_id, fill.at, self.monotonic())
                self._record("speeddesk_live_fill", **asdict(fill))
                self._markout_call("observe_fill", fill, self.book.windows.get(fill.window),
                                   observed_at=fills_batch_at, observed_mono=fills_batch_mono,
                                   fee_precision=self.book.limits.fee_precision, fee_verified=self.fee_verified)
                money_changed = True
        self.order_reads += 1
        reading = self.order_reads  # a cancel that fails from here on was not seen by this read (cancel_failed)
        orders = await self._read("list_orders", self.client.list_orders, **order_filter)
        listed |= {str(raw.get("client_order_id", "")) for raw in orders}
        for raw in orders:
            intent = self.intents.get(str(raw.get("client_order_id", "")))
            if intent is None:
                continue
            self._validate_order(raw, intent)
            if not intent.order_id:
                intent.order_id = str(raw["order_id"])
                self.book.mark_submitted(intent.client_order_id, intent.order_id)
                checks.append("order_found_after_fills")  # Its fills were fetched before this ID was known.
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
                checks.append("order_list_behind_fills")  # no new orders until a fresh read agrees
            elif order.filled_size > booked + EPS:
                checks.append("fills_behind_order_list")
            elif abs(order.filled_size - self.book.intents[intent.client_order_id].filled_size) <= EPS:
                intent.uncertain = False
            if confirmed:
                intent.uncertain = False
                if status in {"canceled", "executed"}:
                    intent.terminal = True
        self.orders_read = reading
        resting = any(str(raw.get("status", "")) == "resting" and str(raw.get("ticker", "")).startswith("KXBTC15M-")
                      for raw in orders)
        positions = await self._read("positions", self.client.positions)
        actual = {str(item["ticker"]): _number(item["position_fp"]) for item in positions}
        windows = {intent.window for intent in self.intents.values()}
        # Settlement rows only ever close a traded window that has ended and is not yet settled; skip the read otherwise.
        settlement_due = any(ticker not in self.book.settled and (ticker not in self.book.windows
                                                                  or self.book.windows[ticker].end <= self.clock())
                             for ticker in windows)
        settlements = (await self._read("settlements", self.client.settlements,
                                        min_ts=max(0, int(self.started_at) - 60))
                       if settlement_due else [])
        self.final_outcomes.update(self.snapshot().outcomes)
        settlement_rows = {str(raw.get("ticker", "")): raw for raw in settlements}
        for raw in settlements:
            ticker = str(raw.get("ticker", ""))
            if raw.get("market_result") in {"yes", "no"}:
                self.final_outcomes[ticker] = raw["market_result"] == "yes"
        if full:  # only complete order lists can prove that an order never reached Kalshi
            # Before the settlement pass, so a released window settles in this same read (its payout check
            # audits the books against Kalshi's revenue).
            money_changed |= self._release_unsent(sync_started, listed, self._release_proof(
                checks, unattributed, actual, settlement_rows))
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
                    checks.append("settlement_row_missing")
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
                    money_changed = True
                continue
            if abs(expected - current) > EPS and ticker not in self.foreign_windows:
                # A fill may arrive between paginated account reads. Pause and
                # reconcile again; never assign a mismatched position to us. A
                # window holding a fill that is provably not ours (the owner's
                # trade by hand) mixes the owner's contracts into the venue
                # position; the bot leaves it alone and counts only its own fills.
                checks.append("position_mismatch")
        for ticker, amount in actual.items():
            if ticker.startswith("KXBTC15M-") and ticker not in windows and abs(amount) > EPS:
                self.foreign_windows.add(ticker)
        self.position_sizes = actual
        balance = await self._read("balance", self.client.balance)
        cash = (_number(balance["balance_dollars"]) if "balance_dollars" in balance
                else _number(balance["balance"]) / 100)
        if cash < 0:
            raise ValueError("Negative available cash")
        now = self.clock()
        self.book.update_cash(cash, now)
        self.cash_usd, self.cash_at = cash, now
        if now - sync_started > 3:
            checks.append("reconcile_slow")
        self.account_at = now if not checks else None
        if full:  # only a complete read can show that no resting order is left on the account
            self._integrity_reset(actual, resting)
        self.authenticated = not self.auth_failed
        self.errors = 0
        self.retry_at = -math.inf
        self.last_sync = now
        # A fill, settlement, stop, release or owner action is saved at once; another change of record at most
        # SAVE_EVERY_S later; a read that changed nothing of record waits for the five-second save (latency
        # review: every reconcile marked the state dirty, so a quiet desk rewrote it every second).
        if money_changed or self._must_save_now():
            self._trace_call("mark", "checkpoint_started", self.monotonic())
            self.checkpoint()
            self._trace_call("mark", "checkpoint_completed", self.monotonic())
        elif self._account_facts() != facts:
            self._save_soon()

    def _account_facts(self) -> tuple[Any, ...]:
        """What a reconcile can change that the full state holds, apart from fills, settlements and stops (saved
        at once): each unfinished order's record (not the time of its last report, which the next read sets
        again), and the windows marked as the owner's, with a final outcome, or with changed terms."""
        orders = []
        for intent in self._active():
            reserved = self.book.intents[intent.client_order_id]
            orders.append((intent.client_order_id, intent.order_id, intent.terminal, intent.uncertain,
                           intent.cancel_requested, reserved.status, reserved.order_id, reserved.reservation_active,
                           reserved.filled_size, reserved.reported_filled_size, reserved.venue_remaining_size,
                           reserved.uncertainty))
        return (tuple(orders), len(self.foreign_windows), len(self.final_outcomes), len(self.changed_windows),
                self.fatal_reason)

    def _release_proof(self, checks: list[str], unattributed: set[str], positions: dict[str, float],
                       settlement_rows: dict[str, Any]) -> Callable[[str], bool]:
        """Whether this complete read's facts about one window agree with an order there never reaching Kalshi.

        Review blocker (2026-10-13): the release used to need a read with no failed check at all. Kalshi settles
        a market about 5 s after the close (KXBTC15M-26OCT131145: settled_time 15:45:04.68 UTC) and a settled
        market leaves the unsettled positions list, so a window still held open by the unsent order failed
        position_mismatch on every read from then on, and the order, a balancing bid or a lock in an unpaired
        window, was never released: real trading stopped for good. A slow read, or a mismatch in another window,
        said nothing about this order either. Now, per window: both order lists agree with the fills (neither
        behind the other), no fill there under an order id the bot does not know (it could be this order's own),
        and the position matches the books or Kalshi has settled the market (its row, and a flat position); in a
        window the owner also trades the position cannot be told apart, so the lists and fills decide.
        """
        lists_agree = not {"order_list_behind_fills", "fills_behind_order_list"} & set(checks)

        def agrees(ticker: str) -> bool:
            current = positions.get(ticker, 0.0)
            return (lists_agree and ticker not in unattributed
                    and (ticker in self.foreign_windows
                         or abs(self.book.expected_position(ticker) - current) <= EPS
                         or (ticker in settlement_rows and abs(current) <= EPS)))
        return agrees

    def _release_unsent(self, started: float, listed: set[str], consistent: Callable[[str], bool]) -> bool:
        """Release journaled orders that never reached Kalshi (see JOURNAL_KEY). Complete reads after the close only.

        Such an order (a crash between its journal row and the send, or a create lost before Kalshi) kept its
        reservation for good and held a restart in "Reconciling startup orders"; until the release it still counts
        in every cap and stop. An order that did reach Kalshi is listed whatever its status, and Kalshi accepts no
        order on a closed market, so after the close two complete lists without it, ORDER_LIST_LAG_S apart, prove
        it never existed, while its window's facts agree (``consistent``, from _release_proof).
        """
        released = False
        for key, intent in self.intents.items():
            reserved = self.book.intents[key]
            if (intent.terminal or intent.order_id or reserved.order_id is not None or key in listed
                    or reserved.filled_size > EPS or not reserved.reservation_active):
                self.unsent_absent.pop(key, None)
                continue
            if started < self.book.windows[intent.window].end:
                continue  # while the market trades a delayed copy of the request could still arrive
            first = self.unsent_absent.setdefault(key, started)
            if not consistent(intent.window) or started - first < ORDER_LIST_LAG_S:
                continue
            self.book.release_unsent(key)
            intent.terminal, intent.uncertain = True, False
            self.unsent_absent.pop(key, None)
            if not intent.lock:
                # As a refusal reaches the twin: the window's other bids, never a bid a pull kept (practice only).
                self._practice("twin_released", self._twin_cancel_window, intent.window, "real_order_never_sent")
            self._record("speeddesk_live_order", client_order_id=key, window=intent.window,
                         state="released; never reached Kalshi (market closed, missing from two complete "
                               "order lists)")
            released = True
        return released

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
        # The risk book below rejects every risk-increasing buy under a financial stop. Keep scanning hedges;
        # authentication, mode, shutdown, account freshness and reconciliation gates are never bypassed.
        reason = (self._trade_reason(balancing=True)
                  or (self._feed_reason(current, snapshot, now) if current else "Window missing"))
        if reason:
            self.reason = reason
            return False
        assert current is not None and current.start_price is not None
        assert snapshot.bitcoin_price is not None and snapshot.sigma is not None
        fresh_up = self._fair(current, snapshot, now)
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

        def twin_copy() -> None:
            self._mirror_twin(self.book.limits_for(window.slug))
            twin_event = self.twin.place(window.slug, side, kind, price, size, fair, now)
            if twin_event.event in ("speeddesk_take", "speeddesk_rest"):
                self.metrics.decision("practice_twin", now, snapshot.tick_receipt, decision_mono)
            intent.twin_order_id = twin_event.order_id
            self._twin_events([twin_event])

        self._practice("twin_place", twin_copy)  # a twin error never leaves a real intent unsent and unsaved
        # The order identifier and its complete worst-case liability reach disk, synced, before the first
        # network byte can leave this process: one small journal row (the full state, the twin's copy among it,
        # follows within a second).
        saving = self.monotonic()
        self._journal_intent(intent, window)
        await self._submit(intent, window, now, decision_mono, save_ms=(self.monotonic() - saving) * 1000)
        return True

    async def _submit(self, intent: Intent, window: Window, now: float, decision_mono: float,
                      save_ms: float | None = None) -> None:
        """Send a durable intent once and settle what its reply proves; never retries a create."""
        client_id, side, kind, price, size = intent.client_order_id, intent.side, intent.kind, intent.price, intent.size
        sent_at: list[float] = []
        sent_wall: list[float] = []

        def guard() -> bool:
            permitted = self._send_guard(client_id)
            sent_at.append(self.monotonic())  # the request leaves right after this returns
            sent_wall.append(self.clock())
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
                         timing=timing((acked - decision_mono) * 1000), stages=stages,
                         venue=self._venue_stamp(reply, sent_wall[0]) if sent_wall else None)
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
                # Review fix: what a restart reads holds the refusal at once, not after the next full save; a
                # crash in that second restored the never-sent order as reserved (and, in an unpaired window,
                # held real trading until the release after the close).
                if client_id in self.journal:
                    self._journal_intent(intent, window, durable=False)
                else:
                    self.checkpoint()
                if client_id in self._pull_refused:
                    # Only the pull stopped it (every other check passed): without the pull it was sent, so the
                    # twin's copy keeps resting under the rule without the pull.
                    if intent.twin_order_id in self.twin.orders:
                        self.twin_kept.add(intent.twin_order_id)
                elif not intent.lock:
                    self._practice("twin_rejected", self._twin_cancel_window, window.slug, "real_order_rejected")
            else:
                intent.uncertain = True
                self.book.mark_uncertain(client_id, "create_unconfirmed")
            self._pull_refused.discard(client_id)
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
        self._save_soon()  # the reply's facts; a restart re-reads the order from Kalshi by its client id
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
            size = min(size, int(self.book.limits_for(slug).clip))
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

    def _balancing_possible(self) -> bool:
        """A current window has real unpaired inventory that a pre-cutoff hedge could reduce."""
        now = self.clock()
        return any(slug not in self.book.settled and slug not in self.foreign_windows
                   and slug not in self.changed_windows
                   and spec.start <= now < spec.end - self.book.limits_for(slug).lock_s
                   and self.book.lock_side(slug)[1] >= 1 - EPS
                   for slug, spec in self.book.windows.items())

    def _lock_note(self, window: str, reason: str, side: Side, size: int) -> None:
        if self.lock_notes.get(window) != reason:
            self.lock_notes[window] = reason
            self._record("speeddesk_live_lock", window=window, side=side, size=size,
                         state="waiting to complete the pair", reason=reason)

    def _starter_note(self, window: str, side: Side, price: float, reason: str) -> str:
        """No first buy in this window because not even one contract with room for its hedge fits under a stop or a
        budget (recorded once per window and reason); returns the plain-words reason for the status. Any other
        refusal (a starter pending on the other side, stale cash) is the status reason as before, with no receipt."""
        plain = {"day_stop": "the daily loss stop", "total_budget": "the lifetime loss stop",
                 "open_budget": "the open budget", "window_budget": "the window budget",
                 "cash_budget": "the Kalshi cash"}.get(reason)
        if plain is None:
            return reason
        text = f"No first buy: one contract and its hedge would not fit under {plain}"
        if self.starter_notes.get(window) != reason:
            self.starter_notes[window] = reason
            risk = self.book.risk_status(self.clock())
            self._record("speeddesk_live_starter", window=window, side=side, price=price, reason=reason, state=text,
                         total_at_risk_usd=risk["total_at_risk_usd"], day_at_risk_usd=risk["day_at_risk_usd"],
                         total_stop_usd=self.book.limits.total_loss_usd, day_stop_usd=risk["limits"]["day_loss_usd"])
        return text

    def _watch_stops(self, when: str = "") -> None:
        """Record each stop the moment it latches (durably: OWNER_RECORDS), with the books' numbers."""
        self.book.latch_bound_stops(self.clock())
        risk = self.book.risk_status(self.clock())
        state = (bool(risk["halted"]), bool(risk["day_stop_latched"]))
        for latched, before, stop, until in ((state[0], self.stop_state[0], "total", "a new resume token"),
                                             (state[1], self.stop_state[1], "day", "00:00 UTC or the owner's day reset")):
            if latched and not before:
                self._record("speeddesk_live_stop", stop=stop, until=until,
                             state=f"{stop} loss stop latched{' ' + when if when else ''}; no new risk until {until}; "
                                   "risk-increasing bids are cancelled; strictly balancing hedges and locks may finish",
                             total_pnl_usd=risk["total_pnl_usd"], total_at_risk_usd=risk["total_at_risk_usd"],
                             total_stop_usd=self.book.limits.total_loss_usd, day_at_risk_usd=risk["day_at_risk_usd"],
                             day_stop_usd=risk["limits"]["day_loss_usd"], at_risk_usd=risk["at_risk_usd"])
        self.stop_state = state

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
        self._journal_intent(intent, window)
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
        if (current is None or self._trade_reason(
                balancing=self.book.strictly_balancing_intent(client_id))
                or self._feed_reason(current, snapshot, self.clock())):
            return False
        assert current.start_price is not None and snapshot.bitcoin_price is not None and snapshot.sigma is not None
        now = self.clock()
        up = self._fair(current, snapshot, now)
        if up is None:
            return False
        fair = up if intent.side == "up" else 1 - up
        edge = self.settings.speeddesk_take_edge if intent.kind == "take" else self.settings.speeddesk_make_edge
        if fair - self.book.unit_reserve(intent.window, intent.price, intent.kind) < edge - EPS:
            return False
        asks = snapshot.books[(intent.window, intent.side)].asks
        if intent.kind == "rest":
            if intent.window not in snapshot.maker_windows or any(level.price <= intent.price + EPS for level in asks):
                return False
            if self.pull.blocks(intent.window, up, now):
                # The fair moved since the decision: the bid is pulled before it is ever sent. Checked last, so
                # the twin knows the rule without the pull would have sent it.
                self._pull_refused.add(client_id)
                return False
            return True
        return any(level.price <= intent.price + EPS and level.size > 0 for level in asks)

    def _write_room_short(self) -> bool:
        """While the pull is on, a new order waits rather than take the client's last CANCEL_ROOM writes of the
        rolling second: a pull's cancels (one per resting bid) then never queue behind creates. Without the pull,
        today's behaviour (the client's own budget only)."""
        writes = getattr(self.client, "writes_last_second", None)
        if not self.pull.rule.enabled or not callable(writes):
            return False
        try:
            return int(writes()) >= WRITES_PER_S - CANCEL_ROOM
        except Exception:  # noqa: BLE001 - a broken count waits: holding a bid back never adds risk.
            return True

    async def _decide(self) -> None:
        if reason := self._trade_reason(balancing=True):
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
            up = self._fair(window, snapshot, now)
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
                    if (intent.kind == "rest" and (take or abs(fair - intent.fair) > REPRICE_FAIR + EPS
                                                   or window.slug not in snapshot.maker_windows)):
                        await self._cancel(intent, "reprice" if not take else "take_available")
                        self.account_at = None
                        return
                # A real bid rests here, but the twin's kept bid was just repriced: the twin bids again (below).
                owed = bool(pending) and kind == "rest" and (window.slug, side) in self.twin_owed
                if pending and not owed or not 0 < price < 1:
                    continue
                if kind == "rest" and (window.slug not in snapshot.maker_windows
                                       or any(level.price <= price + EPS for level in book.asks)):
                    continue
                limits = self.book.limits_for(window.slug)  # the window's ladder rung
                units = math.floor(min(limits.clip, ask.size if ask and take else 25))
                inventory = self.book.inventory[window.slug]
                if inventory.up.shares + inventory.down.shares <= EPS:
                    # Scale the starter to whole pairs at the authorized pair
                    # cap, so a cheap first side cannot consume the hedge budget.
                    units = min(units, math.floor(limits.window_usd / limits.pair_cap))
                    if units == 0:
                        self.reason = "Window budget is too small for a whole capped pair"
                    elif not owed:
                        # Leave room for the hedge under both loss stops. An owed practice bid must never
                        # consult or latch the real risk book; the twin checks its own inventory and budget.
                        units, refused = self.book.starter_fit(window.slug, side, kind, price, units, now)
                        if units == 0:
                            self.reason = self._starter_note(window.slug, side, price, refused)
                if units and owed:  # practice twin only
                    self._practice("twin_unpulled_bid", self._twin_unpulled_bid, window, side, price, fair, units, now)
                elif units:
                    candidates.append((fair - price, window, side, fair, kind, price, units))
        for _, window, side, fair, kind, price, units in sorted(candidates, key=lambda item: -item[0]):
            if kind == "rest" and self.pull.held(window.slug, now):
                self.reason = PULL_REASON  # the practice twin rests the bid the rule without the pull would
                self._practice("twin_unpulled_bid", self._twin_unpulled_bid, window, side, price, fair, units, now)
                continue
            if self._write_room_short():
                self.reason = WRITE_ROOM_REASON
                if kind == "rest":  # without the pull it was sent
                    self._practice("twin_unpulled_bid", self._twin_unpulled_bid, window, side, price, fair, units, now)
                continue
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

    def _ladder_step(self) -> None:
        """Count settled windows and decide a promotion or demotion (it starts at the next window boundary)."""
        now = self.clock()
        if now - self.ladder_at >= LADDER_EVERY_S or self.ladder.due(now):  # a waiting promotion: re-check now
            self.ladder_at = now
            change = self.ladder.evaluate(self.book, now)
            if change is not None:
                self._record("speeddesk_live_ladder", **change)
        self._mirror_twin(self.book.limits_now(now))

    def _mirror_twin(self, limits: LiveLimits) -> None:
        """The practice twin uses the same window, open, daily stop and contract cap as the real orders."""
        config = self.twin.config
        if (config.window_usd, config.open_usd, config.day_stop_usd, config.clip) != (
                limits.window_usd, limits.open_usd, limits.day_loss_usd, limits.clip):
            self.twin.config = replace(config, window_usd=limits.window_usd, open_usd=limits.open_usd,
                                       day_stop_usd=limits.day_loss_usd, clip=limits.clip)

    def _phase(self, name: str, started: float) -> float:
        """Record the time since ``started`` under ``name``; returns now, the next phase's start."""
        now = self.monotonic()
        self.phase_stats.add(name, (now - started) * 1000)
        return now

    async def step(self) -> None:
        began = self.monotonic()
        # Latch before admission/cancels, but keep the durable receipt write after cancellation priority.
        self.book.latch_bound_stops(self.clock())
        self._ladder_step()
        self.observe_market(self.clock())
        self._practice("twin_advance", lambda: self._twin_events(self.twin.advance(self.clock())))
        self._pull_watch(self.snapshot(), self.clock())
        self._practice("twin_unpulled", self._twin_unpulled, self.snapshot(), self.clock())
        self._phase("observe", began)
        if not await self._ensure_client():
            if self.book.integrity_reset_armed:
                self._reset_waiting("live_off")  # no account read happens, so the reset cannot be judged
            self._heartbeat()
            self._phase("step", began)
            return
        try:
            mark = self.monotonic()
            await self._cancel_unsafe()
            mark = self._phase("cancel_unsafe", mark)
            if self.clock() < self.retry_at:
                self._heartbeat()
                self._phase("step", began)
                return
            if not self.startup_done:
                await self._startup()
                mark = self._phase("startup", mark)
            elif self.clock() - self.last_sync >= 1 or self.account_at is None:
                await self._reconcile()
                mark = self._phase("reconcile", mark)
            gate = self._gates()
            await self._cancel_unsafe()
            mark = self._phase("cancel_unsafe", mark)
            if gate:
                self.reason = "Practice; cancelling prior live bids" if self._active() else gate
            elif await self._lock():
                self.reason = "Completing a half-filled pair before the close"
                self._phase("lock", mark)
            else:
                mark = self._phase("lock", mark)
                await self._decide()
                self._phase("decide", mark)
        except Exception as exc:  # noqa: BLE001 — failed account evidence never permits another order.
            self.account_at = None
            self._error(exc)
            if self.errors >= 3 or self.auth_failed:
                await self._cancel_all("authentication_or_repeated_errors")
        mark = self.monotonic()
        self._heartbeat()
        self._phase("heartbeat", mark)
        self._phase("step", began)

    def _heartbeat(self) -> None:
        # Every step exit passes here, including mode-off and backoff. Persist the latch and its receipt
        # together before checkpointing, after any cancellation work that this step could perform.
        self._watch_stops()
        self._request_timings()
        status = self.clock() - self.last_status >= 60
        if status:
            self._record("speeddesk_fill_markout_status", **self._markout_panel())
            # Account reads since the last status line: complete and recent reconcile times, each read's time,
            # pages, rows and bytes, and how often each consistency check failed; plus the latest reconcile.
            self._record("speeddesk_live_status", **self.panel(),
                         save={"last_ms": self.save_ms, **self.save_stages, "archived_windows": len(self.archived),
                               "saved_orders": sum(intent.window not in self.archived for intent in self.intents.values())},
                         reconcile={**self.sync_stats.summary(), "last": self.last_sync_report},
                         reconcile_trace=self._trace_panel(),
                         # Speed plan step 0: time in each part of step() ("step" is the whole), event-loop lag
                         # and cancel timings, and venue clock minus local clock (see _ClockOffsets).
                         phases=self.phase_stats.summary()["ms"], loop=self.loop_stats.summary(),
                         clock=self.clock_offsets.summary(), requests=self.request_stats.summary())
            self.last_status = self.clock()
        since = self.clock() - self.last_checkpoint
        # The once-a-minute status line goes out at once (it is logged when saved), not up to a second later.
        if (status or since >= 5 or self._must_save_now()
                or ((self.dirty or self.pending) and since >= SAVE_EVERY_S)):
            self.checkpoint()

    def _request_timings(self) -> None:
        read = getattr(self.client, "request_timings", None)
        if not callable(read):
            return
        try:
            report = read()
            self.request_stats.count("dropped", report["dropped"])
            for sample in report["samples"]:
                operation = sample["operation"]
                self.request_stats.count(f"{operation}_{'ok' if sample['ok'] else 'error'}")
                for stage in ("lock_wait_ms", "rate_wait_ms", "prepare_ms", "http_ms", "decode_ms", "total_ms"):
                    if sample[stage] is not None:
                        self.request_stats.add(f"{operation}_{stage}", sample[stage])
        except Exception:  # noqa: BLE001 - diagnostics can never stop cancellation or change trading authority
            self.request_stats.count("measurement_error")

    def _stops(self) -> tuple[Any, ...]:
        # And the minute of the ladder's last stop: a promotion waits 24 h after one, so a crash must not forget a
        # new stop (to the minute: a stop that keeps binding is noted on every decision, and saved within a second).
        last_stop = self.ladder.state.last_stop_at
        return (self.book.integrity_error, self.fatal_reason, self.book.halted, self.book.day_stop_latched,
                self.book.integrity_reset_armed, None if last_stop is None else math.floor(last_stop / 60))

    def _must_save_now(self) -> bool:
        """A stop that appeared or cleared, or an owner's one-time action, is saved at once, not within a second."""
        return self._stops() != self.saved_stops or any(kind in OWNER_RECORDS for kind, _ in self.pending)

    async def _lag_probe(self) -> None:
        """Oversleep of a LAG_PROBE_S timer: how long a ready callback waits for the shared event loop."""
        while True:
            started = time.perf_counter()
            await asyncio.sleep(LAG_PROBE_S)
            self.loop_stats.add("event_loop_lag", max(0.0, (time.perf_counter() - started - LAG_PROBE_S) * 1000))

    async def _clock_probe(self) -> None:
        """Local clock against Coinbase's, once every CLOCK_PROBE_S while real money is on. Never fails the desk."""
        while True:
            if not self._gates():
                sent = self.clock()
                try:
                    venue = await asyncio.to_thread(self.time_probe)
                    self.clock_offsets.observe("coinbase", venue, sent, self.clock())
                except Exception as exc:  # noqa: BLE001 — a measurement only; the error type alone is kept.
                    self.loop_stats.count(f"clock_probe_{type(exc).__name__}")
            await asyncio.sleep(CLOCK_PROBE_S)

    async def _markout_probe(self) -> None:
        """Expire absent quotes even while an account GET is in flight; no network or decisions."""
        while self.stop_event is not None and not self.stop_event.is_set():
            await asyncio.sleep(0.1)
            self._markout_call("expire", now=self.clock(), mono=self.monotonic())

    async def run(self, stop: threading.Event) -> None:
        self.stop_event = stop
        self.wake = asyncio.Event()  # bound to this run's event loop
        probes = [asyncio.create_task(self._lag_probe()), asyncio.create_task(self._clock_probe()),
                  asyncio.create_task(self._markout_probe())]
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
            for probe in probes:
                probe.cancel()
            await asyncio.gather(*probes, return_exceptions=True)
            await self.shutdown()

    async def shutdown(self) -> None:
        if self.closed or self.shutdown_done:
            return
        self.stopping = True
        # A cancelled controller may leave a shielded create/cancel in flight. Drain those writes first, but do
        # not let a history GET delay cancellation of known resting orders on the independent write connection.
        writes = self._workers - self._read_workers
        if writes:
            await asyncio.gather(*tuple(writes), return_exceptions=True)
        if self.client is None and (self._active() or self.book.open_cost_usd > EPS):
            await self._ensure_client()
        known_ids = {intent.order_id for intent in self._active() if intent.order_id}
        # Known resting orders get cancellation priority over slower account
        # pagination. Short server-side expiry also bounds a dead process's bid.
        for intent in self._active():
            if intent.order_id in known_ids:
                await self._cancel(intent, "shutdown")
        if self._workers:
            await asyncio.gather(*tuple(self._workers), return_exceptions=True)
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
        self._practice("twin_shutdown", lambda: self._twin_events(self.twin.cancel(self.clock(), reason="shutdown")))
        for record in self._practice("pull_shutdown", lambda: self.pull.expire(self.clock(), everything=True)) or []:
            self._record("speeddesk_live_pull", **record)
        self._markout_call("expire", now=self.clock(), mono=self.monotonic(), reason="shutdown")
        self.checkpoint(durable=True)
        self.shutdown_done = True

    @observed("live_panel")
    def panel(self) -> dict[str, Any]:
        risk = self.book.risk_status(self.clock())
        # The label follows the switches and stops, not the seconds between orders: after every order
        # the desk re-reads the account, and the town showed "PRACTICE" then (2026-10-13 00:15 UTC).
        standing, stop = self._standing_reason(), self._risk_stop_reason()
        # Financial stops permit only risk reduction from actual inventory, including pre-cutoff hedges.
        # The mode must still say REAL MONEY while either path can spend to finish a pair.
        lock_only = (bool(standing) and standing == stop and not self._standing_reason(balancing=True)
                     and (self._lock_possible() or self._balancing_possible()))
        live = not standing or lock_only
        waiting = ((("Paused after a Kalshi error; retrying shortly" if self.clock() < self.retry_at else "")
                    or self._waiting_reason()) if live and not lock_only else "")
        if lock_only:
            waiting = stop + "; only completing half-filled pairs before the close"
        active = self._active()
        reason = self.fatal_reason or (waiting if lock_only else stop if standing == stop and stop else self.reason)
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
                "total_halted": risk.get("halted", False), "day_stop_latched": risk.get("day_stop_latched", False),
                "real_orders_available": live,
                "integrity_error": self.book.integrity_error,
                "integrity_reset": (self.reset_blocker or "armed") if self.book.integrity_reset_armed else None,
                "cleanup_pending": bool(active) and bool(self._gates()),
                # The limits the risk book enforces now (the ladder's rung), not the settings asked for.
                "caps": limits_view(self.book.limits_now(self.clock())),
                "ladder": self.ladder.panel(self.book, self.clock(), risk),
                "today": self._summary(utc_day(self.clock())), "total": self._summary(None),
                "practice_twin": self._twin_summary(utc_day(self.clock())),
                "reports": self.reports,
                "pull": self._pull_panel(),
                "fill_markouts": self._markout_panel(),
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
            # Keep this projection local: public intents and their fields may change
            # between calls. Exotic mappings/fields retain the original lazy scan.
            grouped: dict[str, list[Intent]] | None = None
            if windows and type(self.book) is LiveRiskBook and self.book.integrity_error is None:
                try:
                    native = (
                        type(self.intents) is dict and type(self.book.intents) is dict
                        and all(type(window.get("slug")) is str for window in windows)
                        and all(type(key) is str for key in self.intents)
                        and all(type(key) is str for key in self.book.intents)
                        and all(type(intent) is Intent and type(intent.window) is str
                                and type(intent.client_order_id) is str
                                and type(intent.terminal) is bool and type(intent.uncertain) is bool
                                for intent in self.intents.values())
                        and all(type(intent) is LiveIntent and type(intent.reservation_active) is bool
                                for intent in self.book.intents.values())
                    )
                except AttributeError:
                    native = False
                if native:
                    grouped = {}
                    for intent in self.intents.values():
                        grouped.setdefault(intent.window, []).append(intent)
            for window in windows:
                if self.book.integrity_error or any(
                    intent.window == window["slug"] and (not intent.terminal or intent.uncertain
                        or self.book.intents[intent.client_order_id].reservation_active)
                    for intent in (self.intents.values() if grouped is None else grouped.get(window["slug"], ()))
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

    @observed("live_reports")
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

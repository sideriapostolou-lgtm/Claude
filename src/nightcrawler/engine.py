"""The scheduler that ties everything together (owner: Integrator).

``Engine.tick(now)`` runs whichever stages are due; ``run_forever`` loops
``tick`` with ~1 s sleeps on the clock until stopped (SIGTERM/SIGINT set the
stop event). EVERY stage is wrapped: an exception is logged, stored in kv
``engine.last_error`` and receipted as kind ``error`` (the same error of the
same stage at most once per :data:`ERROR_RECEIPT_EVERY_S`) - the loop never dies.

Stage order inside one tick: ``kill`` -> ``reconcile`` -> ``live_start`` (live, until
recorded) -> ``drift`` -> ``positions`` -> ``discover`` -> ``watch`` -> ``equity`` ->
``heartbeat`` (exits before entries). ``discover`` and ``watch`` stop after a wall-clock
budget of POSITION_INTERVAL_S and run the kill check and (when due) ``positions``
between candidates, so a slow upstream (RugCheck 429s, an LLM timeout) never delays a
stop-loss by more than one slow call.

POSITIONS BELONG TO A MODE: ``Position.mode`` (paper|live) comes from the opening fill
and the engine only sees, values and trades positions of the current TRADING_MODE. At
boot, open positions of the other mode are noted (``note`` ``other_mode_positions``)
and left alone.

``kill`` (every tick)
    ``risk.kill_mode()``: ``stop`` -> no new entries (the watch stage stops
    fetching candles); ``sell_all`` -> exit every position (reason
    ``kill_switch``, retried every POSITION_INTERVAL_S until flat) and behave
    like ``stop``. Mode changes are receipted (kind ``kill``) and stored in kv
    ``engine.kill_mode`` (so a restart does not receipt the same mode again).

``discover`` (DISCOVERY_INTERVAL_S)
    ``crawler.poll()`` -> new candidates go into a FIFO queue (max
    :data:`COCOON_QUEUE_MAX`, oldest dropped). At most
    :data:`MAX_COCOON_PER_TICK` are checked per tick: ``ledger.record_candidate``;
    ``cocoon.check`` -> ``ledger.record_safety``; failed ->
    ``Decision("reject_cocoon")`` receipt; passed -> watchlist (max
    WATCHLIST_MAX, oldest evicted with ``unwatch``) + ``Decision("watch")``.
    A report that failed ONLY because a source was unavailable (e.g. RugCheck
    "not ready" for a freshly matured coin) is not final: the candidate is checked
    again after :data:`COCOON_RETRY_S`, up to :data:`COCOON_ATTEMPTS` times.
    Prefilter rejections are only counted (kv ``engine.status``), not receipted.

``watch`` (WATCH_INTERVAL_S)
    Expire items older than WATCHLIST_TTL_H, items whose snapshot left the
    window by a wide margin (mcap < MIN_MCAP/2 or > MAX_MCAP*2, liquidity <
    MIN_LIQUIDITY/2 - the hysteresis keeps a token that dips through the
    floor during the very dip we are waiting for) and items DexScreener has
    not returned for :data:`SNAPSHOT_MISSING_UNWATCH_S` - whether or not an
    older snapshot exists (``Decision("unwatch")``). A mint with an OPEN
    position is never unwatched (its snapshot feeds the radar's liquidity rule).
    ``crawler.refresh`` (DexScreener batch) for all items; then fetch 1m candles
    (GeckoTerminal ``ohlcv``) covering at least DIP_LOOKBACK_H (and
    CANDLE_WINDOW_MIN) for at most :data:`MAX_CANDLE_FETCH_PER_TICK` items,
    chosen in this priority: never fetched yet; then items whose snapshot price
    is >= DIP_PCT/2 below the rolling high of their last candles (least recently
    fetched first, so every dipping token gets its turn); then least recently
    fetched. Only freshly fetched items are evaluated: candles whose newest
    closed candle is older than :data:`CANDLE_MAX_LAG_S` are skipped (GT lag) ->
    ``strategy.entry_signal`` -> strict universe check (age, mcap and liquidity
    windows, a snapshot no older than 2 x WATCH_INTERVAL_S) -> ``risk.can_open``
    + ``risk.size_position`` (cheap, so the GT/LLM budget is not spent on a
    blocked entry) -> ``cocoon.check`` again (cached COCOON_CACHE_MIN; a hard
    fail rejects and unwatches) -> ``radar.scan`` (reject on flag OR error) ->
    ``judge.decide(build_features(...))`` (required mode: "no" rejects;
    advisory: logged only) -> ``broker.quote("buy")`` (rejected when its price
    is above the strategy's chase ceiling) -> ``Decision("enter")`` receipt
    (inputs: signal, size, quote summary, verdict) -> ``broker.execute`` -> new
    Position in the SAME ledger transaction as the fill (``on_fill``). Rejections
    at each step get a ``reject_*`` decision receipt.

``positions`` (POSITION_INTERVAL_S)
    Mark open positions with Jupiter price v3 (one batched call; DexScreener
    fallback), update ``peak_price_usd``/``last_price_usd``; every
    RADAR_INTERVAL_S also ``radar.scan`` them (errors ignored). On
    ``strategy.exit_signal`` exit: quote the sell of
    ``floor(token_amount * fraction)`` (all tokens when fraction == 1),
    ``Decision("exit"|"exit_partial")`` receipt -> ``broker.execute`` ->
    update/close the Position. Forced exits (everything except the partial
    take-profit) accept up to :data:`EXIT_MAX_IMPACT_PCT` price impact so a
    thinning pool cannot trap a stop-loss. A failed sell is retried next
    interval with a FRESH quote (never re-sent); ``hold`` decisions are
    receipted at most once per :data:`HOLD_RECEIPT_EVERY_S` per position.
    Marks are written with ``ledger.mark_position`` (only peak/last price of a
    still-open row) and sells with ``ledger.update_open_position`` (refused if
    another process changed the row), so a stale copy never reopens a position
    that ``nightcrawler sell-all`` closed meanwhile. A position without a usable
    entry price still exits: time stop, or a stop measured on value vs cost.

``reconcile`` (every tick, live only in practice)
    A live swap whose outcome is unknown (``SwapUnknown``) blocks ALL new
    entries and further trading of that mint. After
    :data:`RECONCILE_AFTER_S` the wallet's token balance (Ultra holdings) is
    compared with the books: unchanged -> the swap did not land (cleared,
    ``note`` receipt); changed -> a reconciliation Fill is recorded from the
    balance change (the actual fill when the broker confirmed the swap but the
    write failed, else SOL estimated pro rata from the quote; flagged in a
    ``note`` receipt) and the Position updated (a reconciled partial
    take-profit counts as taken). Without any SOL/USD price (Jupiter down and
    no USD value on the quote) the item waits instead of booking a zero price.
    Pending items persist in kv ``engine.unresolved`` across restarts.

    IN-FLIGHT MARKER (live): kv ``engine.inflight[mint]`` is written in the same
    transaction as the ``enter``/``exit`` decision receipt, BEFORE the swap is
    sent, and cleared in the transaction that records the fill and the position
    change. A process killed mid-swap (Railway sends SIGKILL right after SIGTERM
    unless a draining time is set) leaves it behind; at restart it becomes an
    unresolved item, so the wallet is reconciled before any new entry.

``live_start`` (live, every tick until done)
    Records kv ``live.start_lamports`` / ``live.start_sol_usd`` (+ ``note``
    ``live_start``) from the wallet BEFORE the first live trade; entries stay
    blocked until it is recorded (the SOL audit needs it).

``drift`` (live, :data:`DRIFT_CHECK_S`)
    Compares Ultra holdings with the books for every mint with an open live
    position or a live fill (unresolved/in-flight mints excepted). A difference
    beyond 1 base unit - or, on a ledger with no live fills, untracked tokens
    worth at least :data:`DRIFT_UNTRACKED_USD` (a lost volume?) - blocks ALL
    entries, is stored in kv ``engine.drift`` and ``engine.status`` (dashboard)
    and receipted (``note`` ``drift``) whenever it changes.

``equity`` (EQUITY_INTERVAL_S)
    ``EquityPoint`` from broker balances + positions of this mode marked at
    their last price (a new position starts at the market price, not its
    fill price) -> ``ledger.record_equity`` (risk limits + dashboard curve).

``heartbeat`` (:data:`HEARTBEAT_S`)
    kv ``engine.heartbeat`` = now and ``engine.status`` (counters for the dashboard/API).

ORDERING GUARANTEE: a Decision/Fill receipt is appended before the engine
fetches any newer price, so recorded intent can never be edited with hindsight.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import os
import signal
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from nightcrawler import __version__
from nightcrawler.clock import Clock, RealClock, iso_utc
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import (
    SOL_MINT,
    Candle,
    Decision,
    EquityPoint,
    Fill,
    MarketSnapshot,
    Position,
    RadarSignal,
    SafetyReport,
    Signal,
    TokenCandidate,
    Verdict,
    effective_price_usd,
    lamports_to_sol,
    new_id,
)
from nightcrawler.strategy import entry_signal, exit_signal, rolling_high

__all__ = [
    "WatchItem",
    "Engine",
    "App",
    "build_app",
    "build_engine",
    "MAX_COCOON_PER_TICK",
    "MAX_CANDLE_FETCH_PER_TICK",
    "COCOON_QUEUE_MAX",
    "EXIT_MAX_IMPACT_PCT",
    "TICK_S",
    "DRIFT_CHECK_S",
    "RECONCILE_AFTER_S",
    "SNAPSHOT_MISSING_UNWATCH_S",
]

log = get_logger(__name__)

MAX_COCOON_PER_TICK = 5
MAX_CANDLE_FETCH_PER_TICK = 3
#: Candidates waiting for a cocoon check; beyond this the oldest are dropped.
COCOON_QUEUE_MAX = 50
#: Price impact a FORCED exit (stop loss, trailing stop, time stop, radar, kill) may accept, percent.
EXIT_MAX_IMPACT_PCT = 25.0
#: Main loop granularity (seconds).
TICK_S = 1.0
#: kv ``engine.heartbeat`` / ``engine.status`` refresh interval (seconds).
HEARTBEAT_S = 15.0
#: The same error of the same stage is receipted at most this often (seconds).
ERROR_RECEIPT_EVERY_S = 300.0
#: A ``hold`` decision (sell could not be executed) is receipted at most this often per position.
HOLD_RECEIPT_EVERY_S = 300.0
#: Wait this long after an unknown live swap outcome before reading the wallet (seconds).
RECONCILE_AFTER_S = 90.0
#: Unwatch a token DexScreener has not returned for this long (seconds).
SNAPSHOT_MISSING_UNWATCH_S = 1800.0
#: Do not re-fetch candles for the same token more often than this (seconds).
MIN_CANDLE_REFETCH_S = 55.0
#: Watchlist hysteresis: unwatch only when mcap/liquidity is this far outside the window.
WINDOW_SLACK = 2.0
#: The engine runs every stage in ONE thread, so a long retry chain on a rate-limited host
#: delays exits. GeckoTerminal answers 429 often on shared IPs; its callers (crawler, candle
#: fetch, radar) all retry on their own schedule, so the engine's client fails fast there.
#: RugCheck and the Solana RPC (``SOLANA_RPC_URL`` host, added by :func:`build_app`) likewise:
#: the cocoon fails closed and retries the candidate later.
ENGINE_HOST_MAX_RETRIES = {"api.geckoterminal.com": 1, "api.rugcheck.xyz": 1}
#: Cap on how long the engine's client honours a ``Retry-After`` (a 60 s wait blocks every stage).
ENGINE_RETRY_AFTER_MAX_S = 10.0
#: Live: how often the wallet is compared with the books (seconds).
DRIFT_CHECK_S = 300.0
#: Live: on a ledger with no live fills, untracked tokens worth at least this block entries (USD).
DRIFT_UNTRACKED_USD = 1.0
#: Token drift up to this many base units is rounding, not drift.
DRIFT_TOLERANCE = 1
#: Newest CLOSED candle older than this (seconds past its close) = GeckoTerminal lagging: no entry.
CANDLE_MAX_LAG_S = 120.0
#: A watched token's DexScreener snapshot older than this many WATCH_INTERVAL_S is "no fresh data".
SNAPSHOT_MAX_AGE_INTERVALS = 2.0
#: A cocoon report that failed only on an unavailable source is retried after this long ...
COCOON_RETRY_S = 120.0
#: ... and becomes a final ``reject_cocoon`` on this attempt.
COCOON_ATTEMPTS = 3

_SAFETY_METRIC_KEYS = ("top10_pct", "max_holder_pct", "creator_pct", "insider_pct", "graph_insiders",
                       "dev_mints", "lp_locked_pct", "holder_count", "rugcheck_score_normalised")
_NOT_FORCED = frozenset({"take_profit_partial"})


# ======================================================================= helpers


def _clean(value: Any) -> Any:
    """JSON-native copy with non-finite floats replaced by None (receipts reject NaN/inf)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_clean(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _clean(dataclasses.asdict(value))
    return value


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _safety_summary(report: SafetyReport) -> dict[str, Any]:
    return {"passed": report.passed, "hard_fail_reasons": list(report.hard_fail_reasons),
            "warnings": list(report.warnings), "unverified": list(report.unverified),
            "metrics": {k: report.metrics.get(k) for k in _SAFETY_METRIC_KEYS if k in report.metrics}}


def _candidate_summary(c: TokenCandidate) -> dict[str, Any]:
    return {"symbol": c.symbol, "name": c.name, "pool": c.pool, "dex": c.dex, "sources": list(c.sources),
            "age_min": c.age_min, "mcap_usd": c.mcap_usd, "liquidity_usd": c.liquidity_usd,
            "price_usd": c.price_usd, "holder_count": c.holder_count, "paid_promo": c.paid_promo}


def _radar_summary(r: RadarSignal) -> dict[str, Any]:
    return {"window_min": r.window_min, "big_sells_usd": r.big_sells_usd, "insider_sell_usd": r.insider_sell_usd,
            "creator_sold": r.creator_sold, "flagged": r.flagged, "reasons": list(r.reasons),
            "trades_seen": r.trades_seen, "liquidity_usd": r.liquidity_usd, "error": r.error}


def _signal_summary(s: Signal) -> dict[str, Any]:
    return {"kind": s.kind, "reason": s.reason, "confidence": s.confidence, "fraction": s.fraction,
            "metrics": dict(s.metrics)}


def _quote_summary(quote: Any) -> dict[str, Any]:
    from nightcrawler.broker.base import quote_summary

    return quote_summary(quote)


def _only_unavailable(report: SafetyReport) -> bool:
    """True when a failed report failed ONLY because a source could not be consulted (retryable)."""
    return bool(report.unverified) and all(str(r).startswith("source unavailable")
                                           for r in report.hard_fail_reasons)


def _candles_stale(candles: list[Candle], now: float) -> str | None:
    """Why ``candles`` are too old to decide on (GeckoTerminal indexing lag), or None.

    Judged on the newest CLOSED candle; the strategy itself stays a pure function of its input
    (the backtester's last candle is always fresh), so this guard lives in the engine.
    """
    closed = [c for c in candles if c.ts + 60 <= now]
    if not closed:
        return None  # entry_signal reports "insufficient data"
    lag = now - (closed[-1].ts + 60)
    if lag > CANDLE_MAX_LAG_S:
        return f"candles stale: newest closed candle ended {lag / 60:.0f} min ago"
    return None


# ======================================================================= watchlist


@dataclass(slots=True)
class WatchItem:
    """A token that passed Cocoon and is being watched for an entry setup."""

    candidate: TokenCandidate
    safety: SafetyReport
    added_at: float
    snapshot: MarketSnapshot | None = None
    candles: list[Candle] = field(default_factory=list)
    candles_at: float | None = None
    last_signal_reason: str | None = None
    snapshot_at: float | None = None

    @property
    def mint(self) -> str:
        return self.candidate.mint

    @property
    def pool(self) -> str | None:
        """Pool for candles/trades: the fresher DexScreener pair if known (graduation moves it)."""
        if self.snapshot is not None and self.snapshot.pool:
            return self.snapshot.pool
        return self.candidate.pool

    def drawdown(self) -> float | None:
        """Current price vs the rolling high of the last fetched candles (fraction), or None."""
        if not self.candles:
            return None
        found = rolling_high(self.candles, self.candles[-1].ts + 60, 24)
        price = self.snapshot.price_usd if self.snapshot is not None else None
        price = price if price is not None else self.candles[-1].c
        if found is None or found[0] <= 0 or price is None:
            return None
        return 1.0 - price / found[0]


# ======================================================================= engine


class Engine:
    """Owns the loop; all dependencies injected (tests pass fakes)."""

    def __init__(self, settings: Settings, *, clock: Clock, ledger: Any, crawler: Any, cocoon: Any,
                 radar: Any, judge: Any, risk: Any, broker: Any, sources: Any = None,
                 stop_event: threading.Event | None = None) -> None:
        self.settings = settings
        self.clock = clock
        self.ledger = ledger
        self.crawler = crawler
        self.cocoon = cocoon
        self.radar = radar
        self.judge = judge
        self.risk = risk
        self.broker = broker
        self.sources = sources
        self.watchlist: dict[str, WatchItem] = {}
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self._last_run: dict[str, float] = {}
        self.params = settings.strategy_params()
        self.queue: deque[TokenCandidate] = deque()
        self._safety: dict[str, SafetyReport] = {}  # mint -> report used for radar on open positions
        self._radar_at: dict[str, float] = {}  # position id -> last radar scan
        self._hold_receipt_at: dict[str, float] = {}  # position id -> last 'hold' receipt
        self._error_receipts: dict[str, tuple[str, float]] = {}  # stage -> (error text, ts)
        self._kill_mode: str | None = None
        self.unresolved: dict[str, dict[str, Any]] = {}
        self.inflight: dict[str, dict[str, Any]] = {}  # live swaps being sent right now (kv engine.inflight)
        self.drift: dict[str, dict[str, int]] = {}  # live: mint -> {books, wallet} (kv engine.drift)
        self._live_start_ok = not settings.is_live
        self._cocoon_attempts: dict[str, int] = {}  # mint -> unavailable-source attempts so far
        self._cocoon_retry: list[tuple[float, TokenCandidate]] = []  # (not before, candidate)
        self._results: dict[str, Any] = {}
        self.counters: Counter[str] = Counter()
        self.prefilter_reasons: Counter[str] = Counter()
        self.last_results: dict[str, str] = {}
        self._booted = False

    # ------------------------------------------------------------------ loop
    def tick(self, now: float) -> dict[str, Any]:
        """Run every due stage once. Returns ``{stage: "ok"|"skipped"|"error: ..."}``. Never raises."""
        s = self.settings
        if not self._booted:
            self._restore_state()
        results: dict[str, Any] = {}
        self._results = results
        self._run("kill", self.handle_kill, now, results)
        self._run("reconcile", self.reconcile_unresolved, now, results)
        if not self._live_start_ok and self._due("live_start", s.position_interval_s, now):
            self._run("live_start", self._ensure_live_start, now, results)
        for name, interval, fn in (("drift", DRIFT_CHECK_S, self.check_drift),
                                   ("positions", s.position_interval_s, self.manage_positions),
                                   ("discover", s.discovery_interval_s, self.discover),
                                   ("watch", s.watch_interval_s, self.watch),
                                   ("equity", s.equity_interval_s, self.snapshot_equity),
                                   ("heartbeat", HEARTBEAT_S, self._heartbeat)):
            if self.stop_event.is_set():
                results[name] = "skipped"
            elif self._due(name, interval, now):
                self._run(name, fn, now, results)
            else:
                results.setdefault(name, "skipped")
        self.last_results = dict(results)
        return results

    def _between_steps(self) -> None:
        """Keep the kill switch and exits responsive while a slow stage works through its list."""
        now = self.clock.now()
        self._run("kill", self.handle_kill, now, self._results)
        if not self.stop_event.is_set() and self._due("positions", self.settings.position_interval_s, now):
            self._run("positions", self.manage_positions, now, self._results)

    def _over_budget(self, started: float) -> bool:
        """True once a slow stage has used up its wall-clock budget (POSITION_INTERVAL_S)."""
        return self.clock.now() - started > self.settings.position_interval_s

    def run_forever(self) -> None:
        """Write a ``boot`` receipt (version, mode, public settings), then loop ``tick`` until
        :attr:`stop_event` is set. Installs SIGTERM/SIGINT handlers when on the main thread."""
        self._install_signal_handlers()
        now = self.clock.now()
        self._restore_state()
        self.ledger.append_receipt("boot", {"version": __version__, "mode": self.settings.trading_mode,
                                            "settings": self.settings.public_dict(), "pid": os.getpid()}, ts=now)
        self.ledger.set_kv("engine.started_at", now)
        self._boot_checks(now)
        self._set_status(now, "running")
        log.info("engine_start version=%s mode=%s judge=%s data_dir=%s", __version__, self.settings.trading_mode,
                 self.settings.judge_mode, self.settings.data_dir)
        try:
            while not self.stop_event.is_set():
                started = self.clock.now()
                self.tick(started)
                if self.stop_event.is_set():
                    break
                self.clock.sleep(max(0.0, TICK_S - (self.clock.now() - started)))
        finally:
            now = self.clock.now()
            try:
                self._set_status(now, "stopped")
                self.ledger.append_receipt("note", {"event": "shutdown", "version": __version__}, ts=now)
            except Exception as exc:  # pragma: no cover - ledger already broken
                log.warning("engine_shutdown_record_failed error=%s", _err(exc))
            log.info("engine_stop")

    def stop(self) -> None:
        """Request a graceful stop (finishes the current stage)."""
        self.stop_event.set()

    def _boot_checks(self, now: float) -> None:
        """Mode switch note, open positions of the OTHER mode (left alone, noted) and the
        phone-friendly halt reset (``RESET_HALT_TOKEN``)."""
        previous = self.ledger.get_kv("engine.mode")
        mode = self.settings.trading_mode
        if previous is not None and previous != mode:
            self.ledger.append_receipt("note", {"event": "mode_change", "from": previous, "to": mode}, ts=now)
            log.warning("mode_change from=%s to=%s (risk limits use %s equity only)", previous, mode, mode)
        self.ledger.set_kv("engine.mode", mode)
        others: dict[str, list[str]] = {}
        for p in self.ledger.open_positions():
            if p.mode != mode:
                others.setdefault(str(p.mode or "unknown"), []).append(p.id)
        for other, ids in sorted(others.items()):
            self.ledger.append_receipt("note", {"event": "other_mode_positions", "mode": other, "positions": ids},
                                       ts=now)
            log.warning("other_mode_positions mode=%s count=%d: a %s engine never trades or counts them; close "
                        "them in %s mode (KILL_SWITCH=sell_all) before switching", other, len(ids), mode, other)
        token = self.settings.reset_halt_token
        if token and token != self.ledger.get_kv("risk.reset_token"):
            self.risk.reset_halt(f"reset via RESET_HALT_TOKEN={token}")
            self.ledger.set_kv("risk.reset_token", token)

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return

        def _handler(signum: int, _frame: Any) -> None:
            log.info("engine_signal signal=%s stopping", signal.Signals(signum).name)
            self.stop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):  # pragma: no cover - not allowed in this context
                pass

    def _due(self, stage: str, interval: float, now: float) -> bool:
        last = self._last_run.get(stage)
        if last is not None and now - last < interval:
            return False
        self._last_run[stage] = now  # set BEFORE running: a failing stage must not hot-loop
        return True

    def _run(self, name: str, fn: Callable[[float], Any], now: float, results: dict[str, Any]) -> None:
        try:
            fn(now)
            results[name] = "ok"
        except Exception as exc:  # the loop never dies
            results[name] = f"error: {type(exc).__name__}"
            self._record_error(name, exc, now)

    def _record_error(self, stage: str, exc: BaseException, now: float) -> None:
        text = _err(exc)
        log.error("engine_stage_error stage=%s error=%s", stage, text, exc_info=exc)
        self.counters["errors"] += 1
        try:
            self.ledger.set_kv("engine.last_error", f"{iso_utc(now)} {stage}: {text}")
            last = self._error_receipts.get(stage)
            if last is None or last[0] != text or now - last[1] >= ERROR_RECEIPT_EVERY_S:
                self.ledger.append_receipt("error", {"stage": stage, "error": text}, ts=now)
                self._error_receipts[stage] = (text, now)
        except Exception as inner:  # the ledger itself may be the problem
            log.error("engine_error_record_failed stage=%s error=%s", stage, _err(inner))

    def _restore_state(self) -> None:
        """Load persisted engine state (kill mode applied, unresolved live swaps). A swap still
        marked IN FLIGHT means the process died while sending it: it becomes unresolved, so the
        wallet is reconciled with the books before anything else trades that mint or enters."""
        self._booted = True
        try:
            applied = self.ledger.get_kv("engine.kill_mode")
            self._kill_mode = applied if applied in ("off", "stop", "sell_all") else None
            pending = self.ledger.get_kv("engine.unresolved")
            if isinstance(pending, dict):
                self.unresolved = {str(k): dict(v) for k, v in pending.items() if isinstance(v, dict)}
            inflight = self.ledger.get_kv("engine.inflight")
            if isinstance(inflight, dict) and inflight:
                self._adopt_inflight({str(k): dict(v) for k, v in inflight.items() if isinstance(v, dict)})
        except Exception as exc:
            log.warning("engine_restore_failed error=%s", _err(exc))

    def _adopt_inflight(self, inflight: dict[str, dict[str, Any]]) -> None:
        now = self.clock.now()
        mode = self.settings.trading_mode
        adopted = {m: {**u, "at": now, "error": "process stopped while the swap was in flight"}
                   for m, u in inflight.items() if u.get("mode", mode) == mode}
        self.unresolved.update(adopted)
        with self.ledger.transaction():
            self.ledger.set_kv("engine.unresolved", _clean(self.unresolved))
            self.ledger.set_kv("engine.inflight", {})
            self.ledger.append_receipt("note", {"event": "inflight_at_restart", "mints": sorted(inflight),
                                                "reconciling": sorted(adopted)}, ts=now)
        log.error("inflight_at_restart mints=%s: the process stopped mid-swap; reconciling with the wallet before "
                  "any new entry", ",".join(sorted(inflight)))

    # ------------------------------------------------------------------ kill switch
    def handle_kill(self, now: float) -> str:
        """Apply the kill switch; returns the active mode."""
        mode = self.risk.kill_mode()
        if mode != self._kill_mode:
            previous = self._kill_mode
            if not (previous is None and mode == "off"):
                self.ledger.append_receipt("kill", {"mode": mode, "previous": previous}, ts=now)
            self.ledger.set_kv("engine.kill_mode", mode)
            log.log(logging.INFO if mode == "off" else logging.WARNING, "kill_switch mode=%s previous=%s", mode,
                    previous)
            self._kill_mode = mode
            self._last_run.pop("sell_all", None)
        if mode == "sell_all" and self._due("sell_all", self.settings.position_interval_s, now):
            if self._open_positions():
                self.sell_all("kill_switch")
        return mode

    @property
    def entries_allowed(self) -> bool:
        return self._entries_blocked_why() is None

    def _entries_blocked_why(self) -> str | None:
        if self._kill_mode not in (None, "off"):
            return f"kill switch {self._kill_mode}"
        if self.unresolved:
            return "unresolved live swap: reconciling first"
        if self.drift:
            return "wallet differs from the books: " + ", ".join(sorted(self.drift))[:200]
        if not self._live_start_ok:
            return "live starting balance not recorded yet"
        return None

    def _open_positions(self) -> list[Position]:
        """Open positions of THIS trading mode (a paper position is never a live one)."""
        return self.ledger.open_positions(mode=self.settings.trading_mode)

    # ------------------------------------------------------------------ discovery
    def discover(self, now: float) -> None:
        new = self.crawler.poll()
        for _candidate, reason in getattr(self.crawler, "last_rejected", []) or []:
            self.prefilter_reasons[str(reason).split(":", 1)[0]] += 1
        queued = {c.mint for c in self.queue}
        due = [c for at, c in self._cocoon_retry if at <= now]
        self._cocoon_retry = [(at, c) for at, c in self._cocoon_retry if at > now]
        for c in [*due, *new]:
            if c.mint in queued or c.mint in self.watchlist:
                continue
            self.queue.append(c)
            queued.add(c.mint)
        while len(self.queue) > COCOON_QUEUE_MAX:
            dropped = self.queue.popleft()
            self.counters["queue_dropped"] += 1
            log.info("cocoon_queue_drop mint=%s", dropped.mint)
        checked = 0
        started = self.clock.now()
        while self.queue and checked < MAX_COCOON_PER_TICK and not self.stop_event.is_set():
            if checked and self._over_budget(started):
                log.info("discover_budget_spent checked=%d queued=%d", checked, len(self.queue))
                break
            candidate = self.queue.popleft()
            checked += 1
            self._check_candidate(candidate, now)
            self._between_steps()

    def _check_candidate(self, c: TokenCandidate, now: float) -> None:
        self.ledger.record_candidate(c)
        report = self.cocoon.check(c)
        self.ledger.record_safety(report)
        self.counters["cocoon_checked"] += 1
        ts = self.clock.now()
        if not report.passed:
            attempts = self._cocoon_attempts.get(c.mint, 0) + 1
            if _only_unavailable(report) and attempts < COCOON_ATTEMPTS:
                self._cocoon_attempts[c.mint] = attempts
                self._cocoon_retry.append((ts + COCOON_RETRY_S, c))
                self.counters["cocoon_retry"] += 1
                log.info("cocoon_retry_later mint=%s attempt=%d reasons=%s", c.mint, attempts,
                         " | ".join(report.hard_fail_reasons[:2]))
                return
            self._cocoon_attempts.pop(c.mint, None)
            self.counters["cocoon_rejected"] += 1
            reasons = report.hard_fail_reasons or ["unverified: " + ", ".join(report.unverified)]
            self._decide(ts, c.mint, "reject_cocoon", "; ".join(reasons[:4]),
                         {"safety": _safety_summary(report), "candidate": _candidate_summary(c)}, symbol=c.symbol)
            log.info("cocoon_reject mint=%s symbol=%s reasons=%s", c.mint, c.symbol, " | ".join(reasons[:4]))
            return
        self._cocoon_attempts.pop(c.mint, None)
        self.counters["cocoon_passed"] += 1
        while len(self.watchlist) >= self.settings.watchlist_max:
            oldest = min(self.watchlist.values(), key=lambda i: i.added_at)
            self._unwatch(oldest.mint, "evicted: watchlist full", ts)
        self.watchlist[c.mint] = WatchItem(candidate=c, safety=report, added_at=now)
        self._safety[c.mint] = report
        self._decide(ts, c.mint, "watch", "passed cocoon" + (f" ({len(report.warnings)} warnings)"
                                                              if report.warnings else ""),
                     {"safety": _safety_summary(report), "candidate": _candidate_summary(c)}, symbol=c.symbol)
        log.info("watch_add mint=%s symbol=%s warnings=%d", c.mint, c.symbol, len(report.warnings))

    def _unwatch(self, mint: str, reason: str, ts: float) -> None:
        item = self.watchlist.pop(mint, None)
        if item is None:
            return
        self._decide(ts, mint, "unwatch", reason, {"last_signal": item.last_signal_reason,
                                                   "snapshot": item.snapshot.to_dict() if item.snapshot else None},
                     symbol=item.candidate.symbol)
        log.info("watch_remove mint=%s symbol=%s reason=%s", mint, item.candidate.symbol, reason)

    # ------------------------------------------------------------------ watchlist
    def watch(self, now: float) -> None:
        s = self.settings
        open_mints = {p.mint for p in self._open_positions()}  # kept watched: their snapshot feeds the radar
        for item in list(self.watchlist.values()):
            if item.mint not in open_mints and now - item.added_at > s.watchlist_ttl_h * 3600:
                self._unwatch(item.mint, f"expired after {s.watchlist_ttl_h:g} h", now)
        if not self.watchlist:
            return
        snaps = self.crawler.refresh(list(self.watchlist))
        for mint, item in list(self.watchlist.items()):
            snap = snaps.get(mint)
            if snap is not None:
                item.snapshot, item.snapshot_at = snap, now
            if mint in open_mints:
                continue
            reason = self._out_of_window(item, now)
            if reason:
                self._unwatch(mint, reason, now)
        if not self.entries_allowed:
            return  # kill switch / unresolved swap / drift: no new entries, save the GeckoTerminal budget
        started = self.clock.now()
        for item in self._pick_for_candles(now, open_mints):
            if self.stop_event.is_set() or self._over_budget(started):
                break
            if item.mint not in self.watchlist:
                continue  # unwatched meanwhile (e.g. failed the safety re-check)
            self._evaluate(item, now)
            self._between_steps()

    def _out_of_window(self, item: WatchItem, now: float) -> str | None:
        s = self.settings
        since = item.snapshot_at or item.added_at  # an OLD snapshot is no market data either
        if now - since >= SNAPSHOT_MISSING_UNWATCH_S:
            return f"no market data for {(now - since) / 60:.0f} min"
        snap = item.snapshot
        if snap is None:
            return None
        if snap.mcap_usd is not None:
            if snap.mcap_usd < s.min_mcap_usd / WINDOW_SLACK:
                return f"mcap fell to ${snap.mcap_usd:,.0f}"
            if snap.mcap_usd > s.max_mcap_usd * WINDOW_SLACK:
                return f"mcap rose to ${snap.mcap_usd:,.0f}"
        if snap.liquidity_usd is not None and snap.liquidity_usd < s.min_liquidity_usd / WINDOW_SLACK:
            return f"liquidity fell to ${snap.liquidity_usd:,.0f}"
        return None

    def _pick_for_candles(self, now: float, open_mints: set[str]) -> list[WatchItem]:
        """Never-fetched items first; then items already >= DIP_PCT/2 below their high, LEAST
        recently fetched first (a deep, dead coin must not take every slot from a fresh setup);
        then the rest, least recently fetched first."""
        half_dip = self.params.dip_pct / 2
        ranked: list[tuple[tuple[float, float], WatchItem]] = []
        for item in self.watchlist.values():
            if item.mint in open_mints or not item.pool:
                continue
            if item.candles_at is not None and now - item.candles_at < MIN_CANDLE_REFETCH_S:
                continue
            if item.candles_at is None:
                key = (0.0, item.added_at)
            else:
                dd = item.drawdown()
                key = (1.0 if dd is not None and dd >= half_dip else 2.0, item.candles_at)
            ranked.append((key, item))
        ranked.sort(key=lambda pair: pair[0])
        return [item for _, item in ranked[:MAX_CANDLE_FETCH_PER_TICK]]

    def _candle_minutes(self) -> int:
        """1m candles to fetch: the whole DIP_LOOKBACK_H window (what the strategy and the
        backtester look at) plus the confirmation candles, and at least CANDLE_WINDOW_MIN."""
        p = self.params
        return max(int(self.settings.candle_window_min), math.ceil(p.dip_lookback_h * 60) + p.confirm_green + 2)

    def _evaluate(self, item: WatchItem, now: float) -> None:
        try:
            candles = self.sources.gecko.ohlcv(item.pool, self._candle_minutes())
        except Exception as exc:  # one token's candles must not stop the others
            item.candles_at = now
            log.warning("candles_failed mint=%s pool=%s error=%s", item.mint, item.pool, _err(exc))
            return
        item.candles, item.candles_at = list(candles), now
        self.counters["candle_fetches"] += 1
        stale = _candles_stale(item.candles, now)
        if stale:  # GeckoTerminal lags: deciding on an old close could buy far above it
            item.last_signal_reason = stale
            log.info("entry_skipped mint=%s reason=%s", item.mint, stale)
            return
        signal_ = entry_signal(item.candles, item.snapshot, self.params, now)
        item.last_signal_reason = signal_.reason
        if signal_.kind != "enter":
            return
        problem = self._universe_problem(item, now)
        if problem:
            item.last_signal_reason = f"setup, but {problem}"
            log.info("entry_skipped mint=%s reason=%s", item.mint, problem)
            return
        self.counters["entry_signals"] += 1
        self._try_enter(item, signal_, now)

    def _universe_problem(self, item: WatchItem, now: float) -> str | None:
        """Strict entry-time window (mirrors the crawler prefilter and the backtester)."""
        s, c, snap = self.settings, item.candidate, item.snapshot
        if snap is None or item.snapshot_at is None:
            return "no market snapshot"
        if now - item.snapshot_at > SNAPSHOT_MAX_AGE_INTERVALS * s.watch_interval_s:
            return f"no fresh market snapshot ({(now - item.snapshot_at) / 60:.0f} min old)"
        if c.created_at is not None:
            age_min = (now - c.created_at) / 60
            if age_min < s.min_age_min or age_min > s.max_age_h * 60:
                return f"age {age_min:.0f} min outside [{s.min_age_min:g} min, {s.max_age_h:g} h]"
        mcap = snap.mcap_usd if snap.mcap_usd is not None else c.mcap_usd
        if mcap is not None and not s.min_mcap_usd <= mcap <= s.max_mcap_usd:
            return f"mcap ${mcap:,.0f} outside the window"
        if snap.liquidity_usd is not None and snap.liquidity_usd < s.min_liquidity_usd:
            return f"liquidity ${snap.liquidity_usd:,.0f} < ${s.min_liquidity_usd:,.0f}"
        return None

    # ------------------------------------------------------------------ entries
    def _try_enter(self, item: WatchItem, signal_: Signal, now: float) -> Fill | None:
        from nightcrawler.broker.base import BrokerError, QuoteRejected, SwapFailed, SwapUnknown
        from nightcrawler.judge import build_features

        c = item.candidate
        mint, symbol = c.mint, c.symbol
        base = {"signal": _signal_summary(signal_), "snapshot": item.snapshot.to_dict() if item.snapshot else None}

        blocked = self._entries_blocked_why()
        if blocked:
            self._decide(self.clock.now(), mint, "reject_risk", f"[blocked] {blocked}", base, symbol=symbol)
            return None
        # 1. risk (cheap, local) before spending the GeckoTerminal / LLM budget
        open_positions = self._open_positions()
        equity_lamports, sol_usd, balances = self._equity_now(open_positions)
        wallet_usd = self._wallet_usd() if self.settings.is_live else None
        ok, reason = self.risk.can_open(mint, open_positions, equity_lamports, wallet_usd)
        sizing = {"equity_lamports": equity_lamports, "sol_usd": sol_usd, "free_lamports": balances.sol_lamports,
                  "wallet_usd": wallet_usd}
        if not ok:
            self._decide(self.clock.now(), mint, "reject_risk", reason, {**base, "sizing": sizing}, symbol=symbol)
            return None
        size = self.risk.size_position(equity_lamports, sol_usd, available_lamports=balances.sol_lamports)
        size_usd = lamports_to_sol(size) * sol_usd
        sizing.update(size_lamports=size, size_usd=size_usd)
        if size <= 0:
            self._decide(self.clock.now(), mint, "reject_risk", "[size] position size is 0 (too little free SOL)",
                         {**base, "sizing": sizing}, symbol=symbol)
            return None
        # 2. the safety verdict again: the one from watch-add can be hours old (cached COCOON_CACHE_MIN)
        if not self._safety_still_ok(item, base, now):
            return None
        # 3. radar: big sells by creator / insiders / top holders. An error rejects (fail closed).
        liquidity = item.snapshot.liquidity_usd if item.snapshot else None
        radar = self.radar.scan(mint, item.pool, item.safety, liquidity_usd=liquidity)
        base["radar"] = _radar_summary(radar)
        if radar.error or radar.flagged:
            why = f"radar unavailable: {radar.error}" if radar.error else "radar: " + "; ".join(radar.reasons)
            self._decide(self.clock.now(), mint, "reject_radar", why, base, symbol=symbol)
            return None
        # 4. judge (after every hard rule passed)
        features = build_features(c, item.snapshot, item.safety, radar, signal_, size_usd, item.candles, now=now)
        verdict: Verdict = self.judge.decide(features)
        if not verdict.approved:
            if self.settings.judge_mode == "required":
                self._decide(self.clock.now(), mint, "reject_judge",
                             "judge: " + ("; ".join(verdict.reasons) or verdict.error or "no"),
                             {**base, "features": features}, symbol=symbol, verdict=verdict)
                return None
            log.info("judge_advisory_no mint=%s reasons=%s", mint, verdict.reasons)
        # 5. quote at the exact size
        decimals = None
        try:
            decimals = self._decimals(item)
            quote = self.broker.quote("buy", mint, int(size), decimals)
        except QuoteRejected as exc:
            self._decide(self.clock.now(), mint, "reject_quote", str(exc), {**base, "sizing": sizing},
                         symbol=symbol, verdict=verdict)
            return None
        except Exception as exc:  # transport / Jupiter errors: no trade
            self._decide(self.clock.now(), mint, "reject_quote", f"quote failed: {_err(exc)}",
                         {**base, "sizing": sizing}, symbol=symbol, verdict=verdict)
            return None
        chasing = self._chasing(signal_, quote, decimals, item)
        if chasing:  # the price ran away between the (closed) candles and now
            self._decide(self.clock.now(), mint, "reject_quote", chasing,
                         {**base, "sizing": sizing, "quote": _quote_summary(quote)}, symbol=symbol, verdict=verdict)
            return None
        # 6. RECEIPT (and the live in-flight marker) before execution
        inputs = {**base, "sizing": sizing, "quote": _quote_summary(quote), "decimals": decimals,
                  "safety": _safety_summary(item.safety), "judge_mode": self.settings.judge_mode}
        with self.ledger.transaction():
            self._decide(self.clock.now(), mint, "enter", signal_.reason, inputs, symbol=symbol, verdict=verdict)
            self._set_inflight(mint, "buy", quote, decimals, None, symbol, item.pool, "entry")
        market_price = item.snapshot.price_usd if item.snapshot is not None else None
        opened: list[Position] = []

        def on_fill(fill: Fill) -> None:  # runs inside the fill's ledger transaction
            opened.append(self._open_position(fill, symbol, item.pool, market_price))
            self._clear_inflight(mint)

        try:
            fill = self.broker.execute(quote, None, symbol=symbol, on_fill=on_fill)
        except SwapUnknown as exc:
            self._mark_unresolved(mint, "buy", quote, decimals, None, symbol, item.pool, exc, reason="entry")
            return None
        except SwapFailed as exc:
            self._clear_inflight(mint)
            log.warning("buy_failed mint=%s error=%s", mint, _err(exc))
            return None
        except (QuoteRejected, BrokerError) as exc:
            self._clear_inflight(mint)
            self._decide(self.clock.now(), mint, "reject_quote", f"execution refused: {exc}",
                         {"quote": _quote_summary(quote)}, symbol=symbol)
            return None
        except Exception as exc:
            self._swap_crashed(mint, "buy", quote, decimals, None, symbol, item.pool, "entry", exc)
            raise
        position = opened[0]
        self._safety[mint] = item.safety
        self.counters["entries"] += 1
        log.info("position_open id=%s mint=%s symbol=%s sol=%.4f price=%.10g tokens=%d", position.id, mint, symbol,
                 lamports_to_sol(fill.sol_lamports), fill.price_usd, fill.token_amount)
        return fill

    def _safety_still_ok(self, item: WatchItem, base: dict[str, Any], now: float) -> bool:
        """Re-run the cocoon (cached COCOON_CACHE_MIN) right before an entry. A hard fail rejects
        and unwatches; an unavailable source only rejects this entry (fail closed, keep watching)."""
        c = item.candidate
        report = self.cocoon.check(c)
        if report is not item.safety and report.checked_at != item.safety.checked_at:
            self.ledger.record_safety(report)
        if report.passed:
            item.safety = self._safety[c.mint] = report
            return True
        reasons = report.hard_fail_reasons or ["unverified: " + ", ".join(report.unverified)]
        self._decide(self.clock.now(), c.mint, "reject_cocoon", "safety re-check: " + "; ".join(reasons[:4]),
                     {**base, "safety": _safety_summary(report)}, symbol=c.symbol)
        if not _only_unavailable(report):
            self._unwatch(c.mint, "failed the safety re-check", now)
        return False

    def _chasing(self, signal_: Signal, quote: Any, decimals: int, item: WatchItem) -> str | None:
        """Why buying at ``quote`` would chase: its price per token is above the strategy's chase
        ceiling (``high * (1 - DIP_PCT/2)``) measured on the candles the decision used."""
        high = signal_.metrics.get("high")
        if not isinstance(high, (int, float)) or high <= 0:
            return None
        ceiling = high * (1.0 - self.params.dip_pct / 2)
        price = None
        if quote.in_usd and quote.out_amount > 0:
            price = quote.in_usd / (quote.out_amount / 10 ** decimals)
        elif item.snapshot is not None:
            price = item.snapshot.price_usd
        if price is None or price <= ceiling:
            return None
        return (f"chasing at execution: quote price ${price:.6g} > chase ceiling ${ceiling:.6g} "
                f"(high ${high:.6g}, last close ${signal_.metrics.get('last_close')})")

    def _open_position(self, fill: Fill, symbol: str, pool: str | None, market_price: float | None = None) -> Position:
        # Marked at the MARKET price (not the fill price, which includes fees and impact), so the
        # first equity snapshot does not hide the entry cost.
        mark = market_price if market_price is not None and market_price > 0 else fill.price_usd
        position = Position(id=new_id("pos"), mint=fill.mint, symbol=symbol, pool=pool, opened_at=fill.ts,
                            token_decimals=fill.token_decimals, entry_fill_ids=[fill.id],
                            token_amount=fill.token_amount, initial_token_amount=fill.token_amount,
                            cost_lamports=fill.sol_lamports, fees_lamports=fill.fees_lamports,
                            rent_lamports=fill.rent_lamports, entry_price_usd=fill.price_usd,
                            peak_price_usd=fill.price_usd, last_price_usd=mark, last_marked_at=fill.ts,
                            mode=fill.mode)
        self.ledger.upsert_position(position)
        return position

    def _decimals(self, item: WatchItem) -> int:
        for value in (item.candidate.decimals, item.safety.metrics.get("decimals")):
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        info = self.sources.rpc.mint_info(item.mint) if self.sources is not None else None
        decimals = (info or {}).get("decimals")
        if not isinstance(decimals, int):
            raise ValueError(f"token decimals unknown for {item.mint}")
        item.candidate.decimals = decimals
        return decimals

    def _wallet_usd(self) -> float | None:
        try:
            return float(self.broker.wallet_value_usd())
        except Exception as exc:  # unknown wallet value refuses the entry (risk rule)
            log.warning("wallet_value_unavailable error=%s", _err(exc))
            return None

    # ------------------------------------------------------------------ positions
    def manage_positions(self, now: float) -> None:
        positions = self._open_positions()
        if not positions:
            return
        prices = self._prices([p.mint for p in positions])
        for position in positions:
            if self.stop_event.is_set():
                break
            if position.mint in self.unresolved:
                continue  # never act on a mint whose last live swap is unresolved
            try:
                self._manage_one(position, prices.get(position.mint), now)
            except Exception as exc:  # one position must not block the others
                self._record_error(f"position:{position.symbol or position.mint[:8]}", exc, now)

    def _prices(self, mints: list[str]) -> dict[str, float]:
        prices: dict[str, float] = {}
        try:
            prices = dict(self.sources.jupiter.prices(mints)) if self.sources is not None else {}
        except Exception as exc:
            log.warning("price_feed_failed source=jupiter error=%s", _err(exc))
        missing = [m for m in mints if m not in prices]
        if missing:
            for mint, snap in self.crawler.refresh(missing).items():
                if snap.price_usd:
                    prices[mint] = snap.price_usd
        return prices

    def _manage_one(self, position: Position, price: float | None, now: float) -> None:
        s = self.settings
        if price is None or price <= 0:
            if now - position.opened_at >= s.max_hold_min * 60:
                self._exit(position, "time_stop", 1.0, now, {"note": "no price available"})
            else:
                log.warning("position_unpriced id=%s mint=%s", position.id, position.mint)
            return
        radar = None
        item = self.watchlist.get(position.mint)
        last = self._radar_at.get(position.id)
        if position.pool and (last is None or now - last >= s.radar_interval_s):
            self._radar_at[position.id] = now
            safety = self._safety.get(position.mint) or self.ledger.latest_safety(position.mint)
            if safety is not None:
                self._safety[position.mint] = safety
            liquidity = item.snapshot.liquidity_usd if item is not None and item.snapshot is not None else None
            radar = self.radar.scan(position.mint, position.pool, safety, liquidity_usd=liquidity)
            if radar.error:
                log.info("radar_error_ignored position=%s error=%s", position.id, radar.error)
        candles = item.candles if item is not None else []
        try:
            sig = exit_signal(position, candles, price, self.params, now, radar)
        except ValueError as exc:  # no usable entry price: the position must still be able to exit
            sig = self._fallback_exit(position, price, now, exc)
        position.peak_price_usd = float(sig.metrics.get("peak_price_usd") or position.peak_price_usd)
        position.last_price_usd, position.last_marked_at = price, now
        if not self.ledger.mark_position(position.id, peak_price_usd=position.peak_price_usd, last_price_usd=price,
                                         last_marked_at=now):
            log.info("position_changed_elsewhere id=%s mint=%s: no longer open", position.id, position.mint)
            return
        if sig.kind == "exit":
            self._exit(position, sig.reason, sig.fraction, now, _signal_summary(sig) | {"price_now": price})

    def _fallback_exit(self, position: Position, price: float, now: float, exc: Exception) -> Signal:
        """Exit rules for a position whose entry price is unknown (``exit_signal`` refuses it):
        the time stop, and a stop-loss measured on marked value vs the cost of the tokens held."""
        s = self.settings
        held_min = (now - position.opened_at) / 60
        metrics: dict[str, Any] = {"held_min": held_min, "fallback": _err(exc)}
        if held_min >= s.max_hold_min:
            return Signal(kind="exit", reason="time_stop", confidence=1.0, metrics=metrics)
        try:
            sol_usd = float(self.broker.sol_price_usd())
        except Exception:
            sol_usd = 0.0
        basis = (position.cost_lamports * position.token_amount // position.initial_token_amount
                 if position.initial_token_amount > 0 else position.cost_lamports)
        value = position.value_lamports(price, sol_usd) if sol_usd > 0 else None
        metrics.update(value_lamports=value, cost_basis_lamports=basis)
        if value is not None and basis > 0 and value <= basis * (1.0 - s.stop_loss_pct):
            return Signal(kind="exit", reason="stop_loss", confidence=1.0, metrics=metrics)
        log.warning("position_without_entry_price id=%s mint=%s: only time stop and value stop apply",
                    position.id, position.mint)
        return Signal(kind="none", reason="hold", metrics=metrics)

    def _exit(self, position: Position, reason: str, fraction: float, now: float,
              inputs: dict[str, Any] | None = None) -> Fill | None:
        from nightcrawler.broker.base import BrokerError, QuoteRejected, SwapFailed, SwapUnknown

        amount = position.token_amount if fraction >= 1.0 else int(math.floor(position.token_amount * fraction))
        if amount <= 0:
            return None
        forced = reason not in _NOT_FORCED
        max_impact = max(self.settings.max_price_impact_pct, EXIT_MAX_IMPACT_PCT) if forced else None
        base = {**(inputs or {}), "position_id": position.id, "fraction": fraction, "amount": amount,
                "forced": forced}
        try:
            quote = self.broker.quote("sell", position.mint, amount, position.token_decimals,
                                      max_impact_pct=max_impact)
        except Exception as exc:  # QuoteRejected, HttpError, JupiterError ...
            self._hold(position, f"{reason}: sell quote failed: {_err(exc)}", base, now)
            return None
        action = "exit" if amount >= position.token_amount else "exit_partial"
        with self.ledger.transaction():
            self._decide(self.clock.now(), position.mint, action, reason, {**base, "quote": _quote_summary(quote)},
                         symbol=position.symbol)
            self._set_inflight(position.mint, "sell", quote, position.token_decimals, position.id, position.symbol,
                               position.pool, reason)

        def on_fill(fill: Fill) -> None:  # runs inside the fill's ledger transaction
            self._apply_sell(position, fill, reason)
            self._clear_inflight(position.mint)

        try:
            fill = self.broker.execute(quote, position, symbol=position.symbol, on_fill=on_fill)
        except SwapUnknown as exc:
            self._mark_unresolved(position.mint, "sell", quote, position.token_decimals, position.id,
                                  position.symbol, position.pool, exc, reason=reason)
            return None
        except SwapFailed as exc:
            self._clear_inflight(position.mint)
            self._hold(position, f"{reason}: swap failed: {_err(exc)}", base, now)
            return None
        except (QuoteRejected, BrokerError) as exc:
            self._clear_inflight(position.mint)
            self._hold(position, f"{reason}: execution refused: {exc}", base, now)
            return None
        except Exception as exc:
            self._swap_crashed(position.mint, "sell", quote, position.token_decimals, position.id, position.symbol,
                               position.pool, reason, exc)
            raise
        return fill

    def _apply_sell(self, position: Position, fill: Fill, reason: str) -> None:
        """Book a sell fill on ``position``; refused (LedgerError) if the stored row changed meanwhile."""
        before = position.token_amount
        position.token_amount -= fill.token_amount
        position.proceeds_lamports += fill.sol_lamports
        position.fees_lamports += fill.fees_lamports
        position.rent_lamports += fill.rent_lamports
        position.exit_fill_ids.append(fill.id)
        if reason == "take_profit_partial":
            position.partial_taken = True
        if position.token_amount <= 0:
            position.token_amount = 0
            position.status = "closed"
            position.closed_at = fill.ts
            position.exit_reason = reason
            self._radar_at.pop(position.id, None)
            self.counters["exits"] += 1
        self.ledger.update_open_position(position, before)
        log.info("position_%s id=%s mint=%s reason=%s sol=%.4f tokens=%d pnl_sol=%.4f",
                 "close" if position.status == "closed" else "reduce", position.id, position.mint, reason,
                 lamports_to_sol(fill.sol_lamports), fill.token_amount,
                 lamports_to_sol(position.pnl_lamports()) if position.status == "closed" else 0.0)

    def _hold(self, position: Position, reason: str, inputs: dict[str, Any], now: float) -> None:
        log.warning("sell_blocked position=%s mint=%s reason=%s", position.id, position.mint, reason)
        last = self._hold_receipt_at.get(position.id)
        if last is None or now - last >= HOLD_RECEIPT_EVERY_S:
            self._hold_receipt_at[position.id] = now
            self._decide(self.clock.now(), position.mint, "hold", reason, inputs, symbol=position.symbol)

    def sell_all(self, reason: str = "manual") -> list[Any]:
        """Exit every open position of this mode now (used by kill sell_all and the ``sell-all`` CLI). Returns fills."""
        now = self.clock.now()
        fills = []
        for position in self._open_positions():
            if position.mint in self.unresolved:
                log.warning("sell_all_skip_unresolved mint=%s", position.mint)
                continue
            fill = self._exit(position, reason, 1.0, now, {"trigger": reason})
            if fill is not None:
                fills.append(fill)
        return fills

    # ------------------------------------------------------------------ in-flight and unknown live outcomes
    def _swap_entry(self, side: str, quote: Any, decimals: int | None, position_id: str | None, symbol: str,
                    pool: str | None, reason: str | None) -> dict[str, Any]:
        return {"side": side, "quote": _quote_summary(quote), "decimals": decimals, "position_id": position_id,
                "symbol": symbol, "pool": pool, "at": self.clock.now(), "reason": reason,
                "mode": self.settings.trading_mode}

    def _set_inflight(self, mint: str, side: str, quote: Any, decimals: int | None, position_id: str | None,
                      symbol: str, pool: str | None, reason: str | None) -> None:
        """Live: persist that a swap of ``mint`` is about to be SENT (see the module docstring)."""
        if not self.settings.is_live:
            return  # a paper swap is one local transaction: nothing can be half done
        self.inflight[mint] = self._swap_entry(side, quote, decimals, position_id, symbol, pool, reason)
        self.ledger.set_kv("engine.inflight", _clean(self.inflight))

    def _clear_inflight(self, mint: str) -> None:
        if self.inflight.pop(mint, None) is not None:
            self.ledger.set_kv("engine.inflight", _clean(self.inflight))

    def _swap_crashed(self, mint: str, side: str, quote: Any, decimals: int | None, position_id: str | None,
                      symbol: str, pool: str | None, reason: str, exc: BaseException) -> None:
        """An unexpected error escaped ``execute``: live cannot know whether the swap was sent, so it
        is treated as unknown; paper rolled the whole swap back, so nothing happened."""
        if self.settings.is_live:
            self._mark_unresolved(mint, side, quote, decimals, position_id, symbol, pool, exc, reason=reason)
        else:
            self._clear_inflight(mint)

    def _mark_unresolved(self, mint: str, side: str, quote: Any, decimals: int | None, position_id: str | None,
                         symbol: str, pool: str | None, exc: BaseException, reason: str | None = None) -> None:
        entry = {**self._swap_entry(side, quote, decimals, position_id, symbol, pool, reason), "error": _err(exc)}
        fill = getattr(exc, "fill", None)
        if isinstance(fill, Fill):  # the broker confirmed the swap but could not record it: keep the real amounts
            entry["fill"] = fill.to_dict()
        self.unresolved[mint] = entry  # in memory FIRST: entries stay blocked even if the ledger is failing
        self.inflight.pop(mint, None)
        try:
            with self.ledger.transaction():
                self.ledger.set_kv("engine.unresolved", _clean(self.unresolved))
                self.ledger.set_kv("engine.inflight", _clean(self.inflight))
        except Exception as inner:
            log.critical("swap_unknown_not_persisted mint=%s error=%s", mint, _err(inner))
        log.error("swap_unknown mint=%s side=%s: entries blocked until reconciled (%s)", mint, side, _err(exc))

    def reconcile_unresolved(self, now: float) -> None:
        if not self.unresolved:
            return
        due = [m for m, u in self.unresolved.items() if now - float(u.get("at", 0)) >= RECONCILE_AFTER_S]
        if not due:
            return
        balances = self.broker.balances()
        for mint in due:
            if self._reconcile_one(mint, self.unresolved[mint], balances.tokens.get(mint, 0), now):
                del self.unresolved[mint]
        self.ledger.set_kv("engine.unresolved", _clean(self.unresolved))

    def _reconcile_one(self, mint: str, u: dict[str, Any], actual: int, now: float) -> bool:
        """Settle one unknown swap from the wallet; False = not settled yet (retried next tick)."""
        position = self.ledger.get_position(u["position_id"]) if u.get("position_id") else None
        if position is None:
            position = next((p for p in self._open_positions() if p.mint == mint), None)
        books = position.token_amount if position is not None else 0
        q = u.get("quote") or {}
        side = u.get("side")
        landed = actual > books if side == "buy" else actual < books
        note = {"event": "reconcile", "mint": mint, "side": side, "books": books, "wallet": actual,
                "landed": landed, "request_id": q.get("request_id")}
        if not landed:
            self.ledger.append_receipt("note", {**note, "result": "swap did not land; nothing changed"}, ts=now)
            log.warning("reconcile mint=%s side=%s result=not_landed", mint, side)
            return True
        delta = actual - books if side == "buy" else books - actual
        stashed = Fill.from_dict(u["fill"]) if isinstance(u.get("fill"), dict) else None
        if stashed is not None and (stashed.side != side or stashed.token_amount != delta):
            stashed = None  # the wallet moved by something else too: fall back to the estimate
        fill = self._reconciliation_fill(mint, u, q, side, delta, position, stashed, now)
        if fill is None:
            log.warning("reconcile_waiting mint=%s side=%s: no SOL/USD price to book the fill; retrying", mint, side)
            return False
        result = ("swap landed; the broker's ACTUAL fill booked (its ledger write had failed)" if stashed is not None
                  else "swap landed; fill reconstructed from the wallet balance, SOL amount ESTIMATED from the quote")
        with self.ledger.transaction():
            self.ledger.append_receipt("note", {**note, "result": result}, ts=now)
            recorded = self.ledger.record_fill(fill)
            if side == "buy" and position is None:
                self._open_position(recorded, str(u.get("symbol") or ""), u.get("pool"))
            elif side == "buy" and position is not None:
                before = position.token_amount
                position.token_amount += recorded.token_amount
                position.initial_token_amount += recorded.token_amount
                position.cost_lamports += recorded.sol_lamports
                position.fees_lamports += recorded.fees_lamports
                position.rent_lamports += recorded.rent_lamports
                position.entry_fill_ids.append(recorded.id)
                self.ledger.update_open_position(position, before)
            elif position is not None:
                self._apply_sell(position, recorded, str(u.get("reason") or "reconciled_sell"))
        log.warning("reconcile mint=%s side=%s result=landed tokens=%d sol=%d actual_fill=%s", mint, side, delta,
                    recorded.sol_lamports, stashed is not None)
        return True

    def _reconciliation_fill(self, mint: str, u: dict[str, Any], q: dict[str, Any], side: Any, delta: int,
                             position: Position | None, stashed: Fill | None, now: float) -> Fill | None:
        position_id = position.id if position is not None else None
        if stashed is not None:
            return dataclasses.replace(stashed, id=new_id("fill"), ts=now, position_id=position_id,
                                       receipt_hash=None)
        in_amount = int(q.get("in_amount") or 0)
        out_amount = int(q.get("expected_out_amount") or 0)
        if side == "buy":
            sol = in_amount if out_amount <= 0 else int(in_amount * min(1.0, delta / out_amount))
        else:
            sol = int(out_amount * min(1.0, delta / in_amount)) if in_amount > 0 else 0
        sol_usd = self._reconcile_sol_usd(side, q)
        if sol_usd is None:
            return None
        decimals = int(u.get("decimals") or (position.token_decimals if position else 0))
        return Fill(id=new_id("fill"), mode=self.settings.trading_mode,  # type: ignore[arg-type]
                    side=side, mint=mint, sol_lamports=sol, token_amount=delta,
                    token_decimals=decimals, price_usd=effective_price_usd(sol, delta, decimals, sol_usd),
                    sol_usd=sol_usd, fees_lamports=0, platform_fee_bps=int(q.get("fee_bps") or 0),
                    price_impact_pct=float(q.get("price_impact_pct") or 0.0), signature=None,
                    request_id=q.get("request_id"), ts=now, position_id=position_id,
                    expected_out_amount=out_amount or None, symbol=str(u.get("symbol") or ""))

    def _reconcile_sol_usd(self, side: Any, q: dict[str, Any]) -> float | None:
        """USD per SOL for a reconciliation fill: Jupiter price v3, else the quote's own valuation
        of its SOL leg (``in_usd`` of a buy, ``out_usd`` of a sell), else None (wait)."""
        try:
            price = float(self.broker.sol_price_usd())
            if price > 0:
                return price
        except Exception as exc:
            log.warning("reconcile_sol_price_unavailable error=%s", _err(exc))
        usd, lamports = (q.get("in_usd"), q.get("in_amount")) if side == "buy" else (
            q.get("out_usd"), q.get("expected_out_amount"))
        if isinstance(usd, (int, float)) and usd > 0 and isinstance(lamports, int) and lamports > 0:
            return float(usd) / lamports_to_sol(lamports)
        return None

    # ------------------------------------------------------------------ live: starting balance and drift
    def _ensure_live_start(self, now: float) -> None:
        """Record the live wallet's starting SOL (kv ``live.start_lamports``) BEFORE any live trade."""
        if self._live_start_ok:
            return
        if self.ledger.get_kv("live.start_lamports") is not None:
            self._live_start_ok = True
            return
        if self.ledger.fills_after_seq(0, mode="live"):
            log.warning("live_start_unknown: fills exist but kv live.start_lamports is missing")
            self._live_start_ok = True  # cannot be recovered; the audit reports it
            return
        balances = self.broker.balances()
        sol_usd = float(self.broker.sol_price_usd())
        with self.ledger.transaction():
            self.ledger.set_kv("live.start_lamports", int(balances.sol_lamports))
            self.ledger.set_kv("live.start_sol_usd", sol_usd)
            self.ledger.append_receipt("note", {"event": "live_start", "start_lamports": int(balances.sol_lamports),
                                                "sol_usd": sol_usd}, ts=now)
        self._live_start_ok = True

    def check_drift(self, now: float) -> None:
        """Live: compare the wallet with the books (see the module docstring)."""
        if not self.settings.is_live:
            return
        balances = self.broker.balances()
        books: dict[str, int] = {}
        for p in self._open_positions():
            books[p.mint] = books.get(p.mint, 0) + p.token_amount
        traded = {f.mint for f in self.ledger.fills_after_seq(0, mode="live")}
        busy = set(self.unresolved) | set(self.inflight)
        drift: dict[str, dict[str, int]] = {}
        for mint in sorted((set(books) | traded) - busy):
            held, want = int(balances.tokens.get(mint, 0)), books.get(mint, 0)
            if abs(held - want) > DRIFT_TOLERANCE:
                drift[mint] = {"books": want, "wallet": held}
        if not traded and not books:
            untracked = {m: int(a) for m, a in balances.tokens.items() if a > 0 and m != SOL_MINT and m not in busy}
            if untracked and self._untracked_value_usd(balances) >= DRIFT_UNTRACKED_USD:
                drift.update({m: {"books": 0, "wallet": a} for m, a in sorted(untracked.items())})
        self._set_drift(drift, now)

    def _untracked_value_usd(self, balances: Any) -> float:
        """USD value of the wallet's tokens (wallet value minus its SOL); unknown counts as untracked."""
        try:
            return float(self.broker.wallet_value_usd()) - lamports_to_sol(int(balances.sol_lamports)) * float(
                self.broker.sol_price_usd())
        except Exception as exc:  # fail closed: unknown value of unknown tokens blocks entries
            log.warning("drift_value_unavailable error=%s", _err(exc))
            return math.inf

    def _set_drift(self, drift: dict[str, dict[str, int]], now: float) -> None:
        if drift == self.drift:
            return
        with self.ledger.transaction():
            self.ledger.set_kv("engine.drift", drift)
            self.ledger.append_receipt("note", {"event": "drift", "mints": sorted(drift), "drift": drift}, ts=now)
        if drift:
            log.error("wallet_drift mints=%s: the wallet differs from the books; new entries are blocked",
                      ",".join(sorted(drift)))
        else:
            log.warning("wallet_drift_cleared")
        self.drift = drift

    # ------------------------------------------------------------------ equity
    def _equity_now(self, positions: list[Position] | None = None) -> tuple[int, float, Any]:
        """``(equity_lamports, sol_usd, balances)``: free SOL + open positions at their last marked price."""
        balances = self.broker.balances()
        sol_usd = float(self.broker.sol_price_usd())
        positions = self._open_positions() if positions is None else positions
        value = sum(p.value_lamports(p.last_price_usd, sol_usd) for p in positions if p.last_price_usd)
        return int(balances.sol_lamports) + int(value), sol_usd, balances

    def snapshot_equity(self, now: float) -> None:
        positions = self._open_positions()
        equity, sol_usd, balances = self._equity_now(positions)
        value = equity - int(balances.sol_lamports)
        point = EquityPoint(ts=now, equity_lamports=equity, sol_usd=sol_usd,
                            equity_usd=lamports_to_sol(equity) * sol_usd, sol_lamports=int(balances.sol_lamports),
                            positions_value_lamports=value, open_positions=len(positions),
                            mode=self.settings.trading_mode)  # type: ignore[arg-type]
        self.ledger.record_equity(point)

    # ------------------------------------------------------------------ status
    def _heartbeat(self, now: float) -> None:
        self._set_status(now, "running")

    def status(self, now: float, state: str = "running") -> dict[str, Any]:
        crawler_stats = self.crawler.stats() if hasattr(self.crawler, "stats") else {}
        return _clean({
            "state": state,
            "mode": self.settings.trading_mode,
            "ts": now,
            "kill_mode": self._kill_mode,
            "watchlist": len(self.watchlist),
            "watching": [{"mint": i.mint, "symbol": i.candidate.symbol, "last_signal": i.last_signal_reason}
                         for i in sorted(self.watchlist.values(), key=lambda i: i.added_at)],
            "cocoon_queue": len(self.queue),
            "unresolved_swaps": sorted(self.unresolved),
            "inflight_swaps": sorted(self.inflight),
            "drift": self.drift,
            "entries_blocked": self._entries_blocked_why(),
            "counters": dict(self.counters),
            "prefilter_rejections": dict(self.prefilter_reasons.most_common(12)),
            "crawler": crawler_stats,
            "stages": self.last_results,
        })

    def _set_status(self, now: float, state: str) -> None:
        self.ledger.set_kv("engine.heartbeat", now)
        self.ledger.set_kv("engine.status", self.status(now, state))

    # ------------------------------------------------------------------ records
    def _decide(self, ts: float, mint: str, action: str, reason: str, inputs: dict[str, Any], *,
                symbol: str = "", verdict: Verdict | None = None) -> Decision:
        decision = Decision(ts=ts, mint=mint, action=action, reason=reason[:500],  # type: ignore[arg-type]
                            inputs=_clean(inputs), verdict=verdict, symbol=symbol)
        self.counters[f"decision.{action}"] += 1
        return self.ledger.record_decision(decision)


# ======================================================================= wiring


@dataclass
class App:
    """Every long-lived component, wired by :func:`build_app`."""

    settings: Settings
    clock: Clock
    stop_event: threading.Event
    http: Any
    sources: Any
    ledger: Any
    crawler: Any
    cocoon: Any
    radar: Any
    judge: Any
    risk: Any
    broker: Any
    auditor: Any
    engine: Engine
    dashboard: Any
    wallet: Any = None

    def close(self) -> None:
        """Stop the dashboard (if running) and close the ledger."""
        try:
            if self.dashboard is not None:
                self.dashboard.stop()
        finally:
            self.ledger.close()


def build_app(settings: Settings, clock: Clock | None = None, *, session: Any = None,
              redaction_filter: Any = None, http: Any = None) -> App:
    """Construct http, clock, sources, crawler, cocoon, radar, judge, ledger, risk, broker
    (paper or live by TRADING_MODE), auditor, dashboard (not started) and the engine.

    ``session``/``http`` let tests inject a fake transport/client. ``redaction_filter``
    (from ``logging_setup.setup_logging``) gets the wallet secret registered.
    Raises ``LiveNotAllowed``/``WalletError`` when live mode preconditions fail.
    """
    from nightcrawler.audit import Auditor
    from nightcrawler.broker.paper import PaperBroker
    from nightcrawler.cocoon import Cocoon
    from nightcrawler.crawler import Crawler
    from nightcrawler.dashboard import DashboardServer, build_state
    from nightcrawler.http import HttpClient, host_of
    from nightcrawler.judge import Judge
    from nightcrawler.ledger import Ledger
    from nightcrawler.radar import Radar
    from nightcrawler.risk import RiskManager
    from nightcrawler.sources import build_sources

    stop_event = threading.Event()
    clock = clock if clock is not None else RealClock(stop_event)
    settings.ensure_data_dir()
    if http is None:
        retries = dict(ENGINE_HOST_MAX_RETRIES)
        rpc_host = host_of(settings.solana_rpc_url)
        if rpc_host:
            retries[rpc_host] = 1
        http = HttpClient.from_settings(settings, session=session, clock=clock, host_max_retries=retries,
                                        retry_after_max_s=ENGINE_RETRY_AFTER_MAX_S)
    sources = build_sources(settings, http)
    ledger = Ledger(settings.db_path, clock=clock)
    try:
        wallet = None
        if settings.bot_wallet_secret:
            from nightcrawler.broker.wallet import load_keypair

            wallet = load_keypair(settings.bot_wallet_secret, redaction_filter)
        if settings.is_live:
            from nightcrawler.broker.live import LiveBroker

            broker: Any = LiveBroker(sources.jupiter, sources.rpc, wallet, ledger, settings, clock)
            ledger.set_kv("wallet.pubkey", wallet.pubkey() if wallet is not None else None)
        else:
            broker = PaperBroker(sources.jupiter, ledger, settings, clock,
                                 taker=wallet.pubkey() if wallet is not None else None)
        crawler = Crawler(sources, settings, clock)
        cocoon = Cocoon(sources, settings, clock)
        radar = Radar(sources, settings, clock)
        judge = Judge(settings, clock=clock, ledger=ledger)
        risk = RiskManager(settings, ledger, clock)
        auditor = Auditor(ledger, broker, clock)
        engine = Engine(settings, clock=clock, ledger=ledger, crawler=crawler, cocoon=cocoon, radar=radar,
                        judge=judge, risk=risk, broker=broker, sources=sources, stop_event=stop_event)
        verify_cache: dict[str, Any] = {}
        dashboard = DashboardServer(settings, lambda: build_state(ledger, settings, clock.now(), verify_cache))
    except BaseException:
        ledger.close()
        raise
    return App(settings=settings, clock=clock, stop_event=stop_event, http=http, sources=sources, ledger=ledger,
               crawler=crawler, cocoon=cocoon, radar=radar, judge=judge, risk=risk, broker=broker,
               auditor=auditor, engine=engine, dashboard=dashboard, wallet=wallet)


def build_engine(settings: Settings, clock: Clock | None = None) -> Engine:
    """Wire real dependencies: HttpClient.from_settings -> Sources -> Crawler/Cocoon/Radar,
    Ledger(settings.db_path), Judge, RiskManager, PaperBroker or LiveBroker (by TRADING_MODE)."""
    return build_app(settings, clock).engine


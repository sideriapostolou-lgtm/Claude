"""pump.fun swap-api TRADES feed: per-coin trade history for :class:`nightcrawler.flow.FlowTracker`.

Endpoint (verified live 2026-10-09, no auth)::

    GET https://swap-api.pump.fun/v2/coins/{mint}/trades?limit=<1..100>&cursor=<slotIndexId>-<ts_ms>

-> ``{"trades": [...], "pagination": {"nextCursor": "<slotIndexId>-<ts_ms>", "hasMore": bool, "limit": n}}``.
Trades come NEWEST FIRST, each ``{"slotIndexId", "tx", "timestamp" (ISO, whole seconds), "userAddress",
"type": "buy" | "sell", "program": "pump" (curve) | "pump_amm" (PumpSwap), "priceSol" (POST-trade price, SOL per
whole token, exact), "amountSol", "baseAmount" (whole tokens, 6 decimals), "quoteAmount", "priceUsd",
"amountUsd", "fillPriceSol", "fillPriceUsd"}``. ``slotIndexId`` = 12-digit slot + 10-digit position, unique per
trade. ``limit > 100`` -> HTTP 400 ("limit must not be greater than 100").

* **Cursor.** ``0000000000000000000000-<T>`` returns trades with ``ts_ms < T`` (exclusive, verified); the
  ``nextCursor`` of a page continues strictly older. Paging with ``nextCursor`` lost no trade against CryptoHouse
  (6,138/6,142 matched; AUDIT section 1).
* **Oldest-first catch-up, then incremental polling** (:class:`CoinSync`): the history from ``start_ts`` is swept
  in windows ``[complete, complete + window)``, each paged newest-first from its upper end down to ``complete``;
  a window's trades go to the tracker when the window is finished, and then ``tracker.complete_through`` moves
  to its end. Once caught up, every sweep is ``[complete, now - settle_s)``: one request when fewer than 100 trades
  arrived. The newest ``settle_s`` seconds are never marked complete (indexing lag).
* **Rate limits.** Cloudflare allows ~12-20 requests/min per IP, SHARED with the candle client
  (:mod:`nightcrawler.sources.pumpfun`, same host, 12/min). This client has its own NON-BLOCKING bucket
  (:data:`RATE_LIMIT`); keep ``trades + candles <= ~20/min``. A 429 / Cloudflare 403 / 503 starts a cool-down of
  ``Retry-After`` seconds (default :data:`DEFAULT_COOLDOWN_S`, at most :data:`MAX_COOLDOWN_S`); pass the candle
  client's ``cooldowns`` dict to share it. Nothing is retried inline: :class:`PollScheduler` decides what to send
  each tick, and a refused or failed request simply waits for a later tick.
* **Usage.** Every request sent is counted on the provider usage panel (``http.usage``, provider ``pumpfun``),
  failed ones too, exactly like the candle client.

BUDGET (lab data, 3,256 tradeable graduates, 34/h, 41 % non-instant): a graduate trades a median 2,657 times in
its first 10 minutes (instant graduates 4,118; peak minute 651, p90 2,573) and then mostly dies (minutes 30-120:
median 0.1 trades/min, p90 73). Following one coin from g to g + 120 min costs ~153 requests at one poll a minute
(median; p90 300), almost all in the first 10 minutes. At 8 requests/min this feed fully tracks ~1 busy fresh
graduate, or ~6-8 quiet coins at 60 s freshness; at 20/min (candles off) ~2-3 busy or ~18 quiet. Live smoke
(2026-10-09): three fresh graduates at 4.5-14.6 trades/s outran 8/min, so :meth:`PollScheduler.demand_per_min`
/ :meth:`PollScheduler.overloaded` exist to shed coins, and catch-up is shortest-job-first.

WIRING ONE STRATEGY (nothing here does it; the engine team owns it)
-------------------------------------------------------------------
1. One :class:`PumpFunTradesClient` per process, sharing the candle client's cool-downs:
   ``PumpFunTradesClient(http, cooldowns=pumpfun_client.cooldowns)``; keep candles + trades <= ~20/min.
2. One :class:`PollScheduler`; call :meth:`PollScheduler.tick` once per engine loop (never blocks or retries).
3. Per candidate coin: ``FlowTracker(mint, created_ts=census created_timestamp / 1000, creator=..., symbol=...,
   g_ts=graduation time if known)`` and ``sched.watch(tracker, start_ts, checkpoints)`` with the strategy's
   decision times on the lab grid (minute boundary + 20 s, :func:`nightcrawler.flow.grid_time`):
   S1 from ``start_ts = created_ts`` (curve inventory), checkpoints g + 6, 8, 10, 15, 20, 30, 45, 60, 90, 120 min;
   M1 from ``start_ts = g`` (pool only), a checkpoint every minute from age 30 to 120 min and while in a position.
   Skip coins with ``tracker.chain_breaks > 0`` (Mayhem or liquidity events) and non-SOL pools; unwatch the
   lowest-value coins while :meth:`PollScheduler.overloaded`.
4. At a checkpoint: ``snap = tracker.as_of(now, sol_usd=...)``; if not ``snap.complete`` skip the decision (the
   scheduler reports it as missed); else run the lab function unchanged (``m1.strategy(snap, params, pos)``,
   ``s1.s1_strategy(...)``: tests/test_flow_lab_strategies.py) and map ``Enter(exits=ExitSpec(...))`` / ``Exit``
   onto the engine's orders. The lab modules import numpy / pandas / research/lab2/common.py: port the chosen
   function into src/ (it only reads the AsOf interface) or add those packages to the image.
"""

from __future__ import annotations

import email.utils
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

import requests

from nightcrawler.clock import Clock
from nightcrawler.flow import DECISION_LAG_S, VENUE_AMM, VENUE_CURVE, FlowTracker, FlowTrade
from nightcrawler.http import HttpClient, HttpError, host_of, provider_of
from nightcrawler.logging_setup import get_logger
from nightcrawler.sources.pumpfun import PumpFunCoolingDown

__all__ = [
    "BASE_URL",
    "HOST",
    "TRADES_PATH",
    "PAGE_LIMIT",
    "RATE_LIMIT",
    "DEFAULT_COOLDOWN_S",
    "MAX_COOLDOWN_S",
    "COOLDOWN_STATUSES",
    "ZERO_SID",
    "TradesPage",
    "TradesBudgetExhausted",
    "RequestBucket",
    "PumpFunTradesClient",
    "CoinSync",
    "Watch",
    "PollScheduler",
    "TickReport",
    "parse_trade",
    "parse_page",
    "cursor_before",
    "split_sid",
    "PumpFunCoolingDown",
]

log = get_logger(__name__)

BASE_URL = "https://swap-api.pump.fun"
HOST = host_of(BASE_URL)
TRADES_PATH = "/v2/coins/{mint}/trades"
PAGE_LIMIT = 100                      # the API refuses more
#: (requests per second, burst) of this client's own bucket: 8/min leaves ~12/min for the candle client.
RATE_LIMIT: tuple[float, float] = (8 / 60, 2)
DEFAULT_COOLDOWN_S = 60.0
MAX_COOLDOWN_S = 900.0
COOLDOWN_STATUSES = frozenset({403, 429, 503})
ZERO_SID = "0" * 22
_PROGRAM_VENUE = {"pump": VENUE_CURVE, "pump_amm": VENUE_AMM}


# --------------------------------------------------------------------------- parsing


def split_sid(sid: str) -> tuple[int, int]:
    """slotIndexId -> (slot, position inside the slot)."""
    return int(sid[:12]), int(sid[12:])


def cursor_before(ts_ms: int) -> str:
    """Cursor that returns trades with ``ts_ms < ts_ms`` (newest first)."""
    return f"{ZERO_SID}-{int(ts_ms)}"


def _iso_s(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def parse_trade(row: Any) -> FlowTrade | None:
    """One swap-api trade row -> :class:`FlowTrade`, or None when it is malformed, not a curve / PumpSwap trade,
    or flagged as failed (defensive: swap-api lists successful swaps only)."""
    if not isinstance(row, Mapping):
        return None
    sid = row.get("slotIndexId")
    venue = _PROGRAM_VENUE.get(str(row.get("program") or ""))
    side = row.get("type")
    ts = _iso_s(row.get("timestamp"))
    wallet = row.get("userAddress")
    price, amount, base = _num(row.get("priceSol")), _num(row.get("amountSol")), _num(row.get("baseAmount"))
    if (not isinstance(sid, str) or len(sid) != 22 or not sid.isdigit() or venue is None or side not in ("buy", "sell")
            or ts is None or not isinstance(wallet, str) or not wallet or price is None or price <= 0
            or amount is None or amount < 0 or base is None or base < 0):
        return None
    if row.get("err") or row.get("error") or row.get("success") is False or row.get("isSuccess") is False:
        return None
    slot, pos = split_sid(sid)
    tok_raw = int(round(base * 1_000_000))
    return FlowTrade(slot=slot, pos=pos, sid=sid, ts=ts, wallet=wallet, is_buy=side == "buy", venue=venue,
                     amount_sol=amount, tok_raw=tok_raw, price=price, tx=str(row.get("tx") or ""))


@dataclass(frozen=True)
class TradesPage:
    trades: list[FlowTrade]          # newest first, as served (malformed rows dropped)
    next_cursor: str | None
    has_more: bool
    n_rows: int
    n_dropped: int


def parse_page(body: Any) -> TradesPage:
    rows = body.get("trades") if isinstance(body, Mapping) else None
    rows = rows if isinstance(rows, list) else []
    trades = [t for t in (parse_trade(r) for r in rows) if t is not None]
    pag = body.get("pagination") if isinstance(body, Mapping) else None
    pag = pag if isinstance(pag, Mapping) else {}
    nxt = pag.get("nextCursor")
    return TradesPage(trades=trades, next_cursor=nxt if isinstance(nxt, str) and nxt else None,
                      has_more=bool(pag.get("hasMore")) and bool(rows), n_rows=len(rows),
                      n_dropped=len(rows) - len(trades))


# --------------------------------------------------------------------------- transport


class TradesBudgetExhausted(Exception):
    """This client's bucket is empty; nothing was sent. ``seconds_left`` until the next token."""

    def __init__(self, seconds_left: float) -> None:
        self.seconds_left = max(0.0, float(seconds_left))
        super().__init__(f"pump.fun trades budget exhausted: next request in {self.seconds_left:.1f}s")


class RequestBucket:
    """Non-blocking token bucket on a :class:`Clock` (thread-safe): :meth:`try_take` never sleeps."""

    def __init__(self, rate_per_s: float, burst: float, clock: Clock) -> None:
        if rate_per_s <= 0 or burst < 1:
            raise ValueError("rate must be > 0 and burst >= 1")
        self.rate, self.capacity, self.clock = float(rate_per_s), float(burst), clock
        self._tokens, self._last = float(burst), clock.now()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self.clock.now()
        self._tokens = min(self.capacity, self._tokens + max(0.0, now - self._last) * self.rate)
        self._last = now

    def tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens

    def try_take(self) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def seconds_until(self, n: float = 1.0) -> float:
        with self._lock:
            self._refill()
            return max(0.0, (n - self._tokens) / self.rate)


class PumpFunTradesClient:
    """swap-api trade pages over the shared :class:`HttpClient` session (its usage counter and stats), with its own
    non-blocking bucket and host cool-down. One call = at most one request; never retried inline."""

    def __init__(self, http: HttpClient, *, base_url: str = BASE_URL, clock: Clock | None = None,
                 rate: tuple[float, float] = RATE_LIMIT, cooldowns: dict[str, float] | None = None) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.host = host_of(self.base_url)
        self.clock = clock if clock is not None else http.clock
        self.bucket = RequestBucket(rate[0], rate[1], self.clock)
        #: host -> epoch seconds before which nothing is sent (share the candle client's dict to share back-off)
        self.cooldowns: dict[str, float] = cooldowns if cooldowns is not None else {}
        self.requests_sent = 0
        self.errors = 0
        #: last ``x-ratelimit-remaining`` / ``x-ratelimit-limit`` the origin reported (observability only)
        self.ratelimit_remaining: int | None = None
        self.ratelimit_limit: int | None = None

    @property
    def cooldown_until(self) -> float:
        return self.cooldowns.get(self.host, 0.0)

    def available(self) -> int:
        """Requests that may be sent right now (0 while cooling down)."""
        if self.clock.now() < self.cooldown_until:
            return 0
        return int(self.bucket.tokens())

    def fetch_page(self, mint: str, cursor: str | None = None, limit: int = PAGE_LIMIT) -> TradesPage:
        """One page of ``mint``'s trades, newest first, older than ``cursor`` (None = the newest).

        Raises :class:`PumpFunCoolingDown` / :class:`TradesBudgetExhausted` (nothing sent) or
        :class:`HttpError` (sent and failed; a 429/403/503 also starts the cool-down)."""
        now = self.clock.now()
        until = self.cooldown_until
        if now < until:
            raise PumpFunCoolingDown(until - now)
        if not self.bucket.try_take():
            raise TradesBudgetExhausted(self.bucket.seconds_until())
        url = f"{self.base_url}{TRADES_PATH.format(mint=mint)}"
        params: dict[str, Any] = {"limit": max(1, min(PAGE_LIMIT, int(limit)))}
        if cursor:
            params["cursor"] = cursor
        stats = self.http.stats[self.host]
        stats["requests"] += 1
        self.requests_sent += 1
        usage = getattr(self.http, "usage", None)
        if usage is not None:
            usage.record(provider_of(self.host))
        try:
            return parse_page(self._send(url, params, now, stats))
        finally:
            if usage is not None:
                usage.maybe_flush()

    def _send(self, url: str, params: dict[str, Any], now: float, stats: dict[str, float]) -> Any:
        try:
            resp = self.http.session.request("GET", url, params=params, json=None,
                                             headers=dict(self.http.default_headers), timeout=self.http.timeout_s)
        except requests.RequestException as exc:
            stats["errors"] += 1
            self.errors += 1
            retryable = isinstance(exc, (requests.ConnectionError, requests.Timeout))
            raise HttpError(type(exc).__name__, url=url, status=None, retryable=retryable) from exc
        headers = getattr(resp, "headers", None) or {}
        self._note_ratelimit(headers)
        status = int(resp.status_code)
        if status >= 400:
            stats["errors"] += 1
            self.errors += 1
            if status in COOLDOWN_STATUSES:
                seconds = self._cooldown_s(headers, now)
                self.cooldowns[self.host] = max(self.cooldowns.get(self.host, 0.0), now + seconds)
                log.warning("pumpfun_trades_backoff status=%s cooldown_s=%.0f", status, seconds)
            raise HttpError(f"HTTP {status}", url=url, status=status, body=_text(resp),
                            retryable=status in COOLDOWN_STATUSES or status >= 500)
        try:
            return resp.json()
        except ValueError:
            stats["errors"] += 1
            self.errors += 1
            raise HttpError("invalid JSON", url=url, status=status, body=_text(resp)) from None

    def _note_ratelimit(self, headers: Any) -> None:
        for key, value in headers.items():
            k = str(key).lower()
            if k in ("x-ratelimit-remaining", "x-ratelimit-limit"):
                try:
                    n = int(str(value).strip())
                except ValueError:
                    continue
                if k.endswith("remaining"):
                    self.ratelimit_remaining = n
                else:
                    self.ratelimit_limit = n

    @staticmethod
    def _cooldown_s(headers: Any, now: float) -> float:
        value = next((str(v).strip() for k, v in headers.items() if str(k).lower() == "retry-after"), "")
        seconds: float | None
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = email.utils.parsedate_to_datetime(value).timestamp() - now
            except (TypeError, ValueError, IndexError):
                seconds = None
        if seconds is None or seconds <= 0:
            return DEFAULT_COOLDOWN_S
        return min(seconds, MAX_COOLDOWN_S)


def _text(resp: Any) -> str | None:
    try:
        return str(resp.text)
    except Exception:  # pragma: no cover - a response without text
        return None


# --------------------------------------------------------------------------- per-coin sync


@dataclass
class _Sweep:
    lo_ms: int
    hi_ms: int
    cursor: str
    buffer: dict[str, FlowTrade] = field(default_factory=dict)
    pages: int = 0


class CoinSync:
    """One coin's cursor state: oldest-first catch-up from ``start_ts``, then incremental polling.

    ``tracker.complete_through`` (seconds) always equals ``complete_ms / 1000``: every trade older than it is in
    the tracker. :meth:`next_cursor` starts or continues a sweep; :meth:`on_page` consumes its page."""

    def __init__(self, tracker: FlowTracker, start_ts: float, *, window_s: float = 60.0, settle_s: float = 3.0,
                 min_window_s: float = 10.0, max_window_s: float = 900.0) -> None:
        self.tracker = tracker
        self.mint = tracker.mint
        self.start_ts = float(start_ts)
        self.window_s = float(window_s)
        self.settle_s = float(settle_s)
        self.min_window_s, self.max_window_s = float(min_window_s), float(max_window_s)
        self.complete_ms = int(math.floor(self.start_ts)) * 1000
        self.sweep: _Sweep | None = None
        self.requests = 0
        self.pages_with_trades = 0
        self.errors = 0
        self.last_request_at: float | None = None
        self.retry_after: float = 0.0
        #: trades per second over the last finished sweeps (EWMA), for request estimates
        self.rate_tps = 0.0
        tracker.set_history_from(self.start_ts)
        tracker.mark_complete(self.complete_ms / 1000)

    @property
    def complete_through(self) -> float:
        return self.complete_ms / 1000

    def backlog_s(self, now: float) -> float:
        """Seconds of history not yet complete (up to ``now - settle_s``)."""
        return max(0.0, now - self.settle_s - self.complete_through)

    def estimate_requests(self, now: float, through: float | None = None) -> int:
        """Requests to bring ``complete_through`` to ``through`` (default now - settle), from the trade rate."""
        end = now - self.settle_s if through is None else min(through, now - self.settle_s)
        span = max(0.0, end - self.complete_through)
        if span <= 0:
            return 0
        pending = len(self.sweep.buffer) if self.sweep is not None else 0
        return max(1, math.ceil((self.rate_tps * span - pending) / 100.0) + (1 if self.rate_tps * span >= 100 else 0))

    def caught_up(self, now: float) -> bool:
        return self.sweep is None and self.backlog_s(now) <= self.window_s

    def next_cursor(self, now: float) -> str | None:
        """The cursor of the next request, starting a sweep when none is open; None when nothing is due."""
        if self.sweep is not None:
            return self.sweep.cursor
        hi = min(self.complete_ms + int(self.window_s * 1000), int(math.floor((now - self.settle_s) * 1000)))
        if hi <= self.complete_ms:
            return None
        self.sweep = _Sweep(lo_ms=self.complete_ms, hi_ms=hi, cursor=cursor_before(hi))
        return self.sweep.cursor

    def on_page(self, page: TradesPage, now: float) -> int:
        """Consume a page of the open sweep. Returns how many trades reached the tracker (0 until the sweep ends)."""
        sw = self.sweep
        if sw is None:
            return 0
        self.requests += 1
        sw.pages += 1
        if page.trades:
            self.pages_with_trades += 1
        reached_lo = False
        for t in page.trades:
            ts_ms = t.ts * 1000
            if ts_ms < sw.lo_ms:
                reached_lo = True
                continue
            if ts_ms < sw.hi_ms:
                sw.buffer[t.sid] = t
        if reached_lo or not page.has_more or not page.trades or not page.next_cursor:
            return self._finish(now)
        sw.cursor = page.next_cursor
        return 0

    def _finish(self, now: float) -> int:
        sw = self.sweep
        assert sw is not None
        n = self.tracker.ingest(sorted(sw.buffer.values(), key=lambda t: t.key))
        span = (sw.hi_ms - sw.lo_ms) / 1000
        if span > 0:
            tps = len(sw.buffer) / span
            self.rate_tps = tps if self.rate_tps == 0 else 0.5 * self.rate_tps + 0.5 * tps
        if sw.pages > 3:
            self.window_s = max(self.min_window_s, self.window_s / 2)
        elif sw.pages == 1 and len(sw.buffer) < 50:
            self.window_s = min(self.max_window_s, self.window_s * 2)
        self.complete_ms = sw.hi_ms
        self.tracker.mark_complete(self.complete_ms / 1000)
        self.sweep = None
        return n


# --------------------------------------------------------------------------- scheduler


@dataclass
class Watch:
    """A watched coin: its sync, the decision times its strategy will evaluate (epoch seconds), and how fresh it
    must be kept between checkpoints."""

    sync: CoinSync
    checkpoints: list[float] = field(default_factory=list)
    max_staleness_s: float | None = 60.0
    weight: float = 1.0
    missed: list[float] = field(default_factory=list)


@dataclass
class TickReport:
    sent: int = 0
    polled: list[str] = field(default_factory=list)
    delivered: int = 0
    stopped: str | None = None            # "cooldown" | "budget" | "network" | None
    errors: dict[str, str] = field(default_factory=dict)
    missed: dict[str, list[float]] = field(default_factory=dict)


class PollScheduler:
    """Decides which watched coins to poll within the request budget, and polls them (non-blocking).

    Priority, highest first (:meth:`plan`, pure):

    1. **due** - a checkpoint ``t_c`` whose cutoff ``tau_c = t_c - lag`` has passed (plus ``settle_s``) while the
       coin is not complete through ``tau_c``: earliest decision first (EDF), ties by estimated requests;
    2. **prefetch** - a checkpoint within ``lead_s``: catch the backlog up before it is due, nearest first;
    3. **catch-up** - history still behind by more than one window (a newly watched coin), oldest backlog first;
    4. **fresh** - background polling of coins staler than their ``max_staleness_s``, stalest first.

    A checkpoint whose decision time passed while the data was incomplete is MISSED: it is dropped and reported
    (the strategy must not decide on an incomplete snapshot: ``snap.complete`` is False)."""

    def __init__(self, client: PumpFunTradesClient, *, lag_s: float = DECISION_LAG_S, lead_s: float = 120.0,
                 clock: Clock | None = None) -> None:
        self.client = client
        self.clock = clock if clock is not None else client.clock
        self.lag_s = float(lag_s)
        self.lead_s = float(lead_s)
        self.watches: dict[str, Watch] = {}

    def watch(self, tracker: FlowTracker, start_ts: float, checkpoints: Iterable[float] = (), *,
              max_staleness_s: float | None = 60.0, window_s: float = 60.0, settle_s: float = 3.0) -> Watch:
        """Track ``tracker``'s coin from ``start_ts`` (creation for curve / wallet features, graduation for pool
        features only). Re-watching keeps the sync and replaces the checkpoints."""
        w = self.watches.get(tracker.mint)
        if w is None:
            w = Watch(CoinSync(tracker, start_ts, window_s=window_s, settle_s=settle_s))
            self.watches[tracker.mint] = w
        w.checkpoints = sorted(float(c) for c in checkpoints)
        w.max_staleness_s = max_staleness_s
        return w

    def unwatch(self, mint: str) -> None:
        self.watches.pop(mint, None)

    def add_checkpoint(self, mint: str, t: float) -> None:
        w = self.watches[mint]
        w.checkpoints = sorted({*w.checkpoints, float(t)})

    # ------------------------------------------------------------------ planning (pure)
    def _expire(self, w: Watch, now: float) -> list[float]:
        done = [c for c in w.checkpoints if w.sync.complete_through > c - self.lag_s]
        missed = [c for c in w.checkpoints if c < now and w.sync.complete_through <= c - self.lag_s]
        if done or missed:
            w.checkpoints = [c for c in w.checkpoints if c not in done and c not in missed]
            w.missed.extend(missed)
        return missed

    def rank(self, w: Watch, now: float) -> tuple | None:
        """Sort key of a watch (lower = sooner), or None when it needs nothing now."""
        s = w.sync
        if now < s.retry_after:
            return None
        if s.sweep is None and s.backlog_s(now) <= 0:
            return None
        nxt = next((c for c in w.checkpoints if c >= now), None)
        if nxt is not None:
            tau_c = nxt - self.lag_s
            need = s.estimate_requests(now, tau_c + 1)
            if now >= tau_c + s.settle_s and s.complete_through <= tau_c:
                return (0, nxt, need)
            if nxt - now <= self.lead_s:
                return (1, nxt, need)
        if s.backlog_s(now) > s.window_s or s.sweep is not None:
            # shortest job first: under overload, finishing one coin beats keeping every coin half-stale
            return (2, s.estimate_requests(now) / max(w.weight, 1e-9), s.complete_through)
        stale = now - s.complete_through
        if w.max_staleness_s is not None and stale >= w.max_staleness_s:
            return (3, -stale / max(w.weight, 1e-9), 0)
        return None

    def demand_per_min(self, now: float | None = None) -> dict[str, float]:
        """Requests per minute each watched coin needs to stay current: its trade rate / 100 per page, at least one
        poll per ``max_staleness_s``. Compare the sum with ``client`` capacity (:meth:`capacity_per_min`) and
        unwatch the least important coins when it does not fit (busy fresh graduates run 300-1,500 trades/min)."""
        now = self.clock.now() if now is None else now
        out = {}
        for mint, w in self.watches.items():
            s = w.sync
            polls = 60.0 / w.max_staleness_s if w.max_staleness_s else 0.0
            out[mint] = max(s.rate_tps * 60.0 / 100.0, polls) + s.estimate_requests(now) / 10.0  # backlog over 10 min
        return out

    def capacity_per_min(self) -> float:
        return self.client.bucket.rate * 60.0

    def overloaded(self, now: float | None = None) -> bool:
        return sum(self.demand_per_min(now).values()) > self.capacity_per_min()

    def plan(self, now: float, budget: int) -> list[str]:
        """Up to ``budget`` mints to poll now, in priority order (one request each)."""
        ranked = []
        for mint, w in self.watches.items():
            key = self.rank(w, now)
            if key is not None:
                ranked.append((key, mint))
        ranked.sort()
        return [m for _, m in ranked[:max(0, budget)]]

    # ------------------------------------------------------------------ polling
    def tick(self, now: float | None = None, max_requests: int | None = None) -> TickReport:
        """Send what the budget allows right now (never blocks, never retries inline)."""
        now = self.clock.now() if now is None else now
        rep = TickReport()
        for mint, w in self.watches.items():
            missed = self._expire(w, now)
            if missed:
                rep.missed[mint] = missed
                log.info("flow_checkpoint_missed mint=%s n=%d", mint, len(missed))
        budget = self.client.available()
        if max_requests is not None:
            budget = min(budget, max_requests)
        if budget <= 0:
            rep.stopped = "cooldown" if now < self.client.cooldown_until else "budget"
            return rep
        while budget > 0:
            order = self.plan(now, 1)
            if not order:
                break
            mint = order[0]
            w = self.watches[mint]
            cursor = w.sync.next_cursor(now)
            if cursor is None:
                w.sync.retry_after = now + 1.0
                continue
            try:
                page = self.client.fetch_page(mint, cursor)
            except PumpFunCoolingDown:
                rep.stopped = "cooldown"
                break
            except TradesBudgetExhausted:
                rep.stopped = "budget"
                break
            except HttpError as exc:
                rep.sent += 1
                w.sync.errors += 1
                rep.errors[mint] = str(exc)
                if exc.status in COOLDOWN_STATUSES:
                    rep.stopped = "cooldown"
                    break
                if exc.status is None or exc.status >= 500:
                    w.sync.retry_after = now + 15.0
                    rep.stopped = "network"
                    break
                w.sync.retry_after = now + 60.0   # 4xx for this coin only (bad mint, ...)
                budget -= 1
                continue
            rep.sent += 1
            budget -= 1
            w.sync.last_request_at = now
            rep.polled.append(mint)
            rep.delivered += w.sync.on_page(page, now)
            for c in list(w.checkpoints):
                if w.sync.complete_through > c - self.lag_s:
                    w.checkpoints.remove(c)
        return rep

    # ------------------------------------------------------------------ status
    def status(self, now: float | None = None) -> dict[str, dict[str, Any]]:
        now = self.clock.now() if now is None else now
        out = {}
        for mint, w in self.watches.items():
            s = w.sync
            out[mint] = {"complete_through": s.complete_through, "lag_s": now - s.complete_through,
                         "backlog_s": s.backlog_s(now), "trades": len(s.tracker), "requests": s.requests,
                         "rate_tps": s.rate_tps, "window_s": s.window_s, "next_checkpoint": w.checkpoints[:1],
                         "missed": len(w.missed), "errors": s.errors}
        return out

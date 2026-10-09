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
* **Fail closed.** A window is marked complete only when a page reached below its start or the API said
  ``hasMore: false`` on a well-formed page. A body that is not a trades page, a row that cannot be parsed (an
  unknown ``program``, a bad number), ``hasMore`` without ``nextCursor``, a cursor that does not move, a page that
  repeats trades, or more than :data:`MAX_SWEEP_PAGES` pages ABORT the sweep: nothing is marked complete, the error
  is counted and reported, and the coin backs off (:data:`COIN_BACKOFF_S`, doubling). Rows flagged as failed
  transactions are skipped by design.
* **Indexing lag.** Caught-up sweeps re-read the last :data:`OVERLAP_S` seconds below the completed edge. A trade
  found there that the tracker lacks was indexed later than ``settle_s``: it is ingested (never lost), counted
  (``late_trades``, :attr:`TickReport.late`), logged, and ``settle_s`` rises to the observed lag + 2 s (at most
  :data:`MAX_SETTLE_S`) for every watched coin. Snapshots taken before the late trade arrived may have been wrong.
* **Rate limits.** Cloudflare allows ~12-20 requests/min per IP, SHARED with the candle client
  (:mod:`nightcrawler.sources.pumpfun`, same host). This client has its own NON-BLOCKING bucket
  (:data:`RATE_LIMIT`) and, when the :class:`HttpClient` limits the host (the engine sets 12/min, burst 3), also
  takes from that shared host bucket, only while it holds >= 2 tokens: candles + trades together stay within the
  host's budget and a trades request never makes the (blocking) candle client wait. A 429 / Cloudflare 403 / 503
  starts a cool-down of ``Retry-After`` seconds (default :data:`DEFAULT_COOLDOWN_S`, at most
  :data:`MAX_COOLDOWN_S`); a timeout, connection error, other 5xx or a non-JSON 200 (a challenge page) starts a
  host back-off of :data:`HOST_BACKOFF_S`, doubling while it repeats, reset by the first good response. Pass the
  candle client's ``cooldowns`` dict to share both. Requests time out after :data:`DEFAULT_TIMEOUT_S`. Nothing is
  retried inline: :class:`PollScheduler` decides what to send each tick, and a refused or failed request simply
  waits for a later tick.
* **Usage.** Every request sent is counted on the provider usage panel (``http.usage``, provider ``pumpfun``),
  failed ones too, exactly like the candle client.

BUDGET (lab data, 3,256 tradeable graduates, 34/h, 41 % non-instant): a graduate trades a median 2,657 times in
its first 10 minutes (instant graduates 4,118; peak minute 651, p90 2,573) and then mostly dies (minutes 30-120:
median 0.1 trades/min, p90 73). Following one coin from g to g + 120 min costs ~153 requests at one poll a minute
(median; p90 300), almost all in the first 10 minutes. At 8 requests/min this feed fully tracks ~1 busy fresh
graduate, or ~6-8 quiet coins at 60 s freshness. The engine's shared host bucket (12/min) caps candles + trades;
20/min for trades needs that host limit raised (and candles off). Live smoke (2026-10-09): three fresh graduates
at 4.5-14.6 trades/s outran 8/min, so :meth:`PollScheduler.demand_per_min` / :meth:`PollScheduler.overloaded`
exist to shed coins, and catch-up is shortest-job-first.

WIRING ONE STRATEGY (nothing here does it; the engine team owns it)
-------------------------------------------------------------------
1. One :class:`PumpFunTradesClient` per process, sharing the candle client's cool-downs:
   ``PumpFunTradesClient(http, cooldowns=pumpfun_client.cooldowns)`` (it shares the engine's host bucket too).
2. One :class:`PollScheduler`; call :meth:`PollScheduler.tick` once per engine loop (never retries; a request
   blocks at most :data:`DEFAULT_TIMEOUT_S`, and a failing host is backed off).
3. Per candidate coin: ``FlowTracker(mint, created_ts=census created_timestamp / 1000, creator=..., symbol=...,
   g_ts=graduation time if known)`` and ``sched.watch(tracker, start_ts, checkpoints)`` with the strategy's
   decision times on the lab grid (minute boundary + 20 s, :func:`nightcrawler.flow.grid_time`):
   S1 from ``start_ts = created_ts`` (curve inventory), checkpoints g + 6, 8, 10, 15, 20, 30, 45, 60, 90, 120 min;
   M1 from ``start_ts = g`` (pool only), a checkpoint every minute from age 30 to 120 min and while in a position
   (:meth:`PollScheduler.add_checkpoint`). A watch stops polling ``lead_s`` after its last checkpoint.
   Skip coins with ``tracker.chain_breaks > 0`` (Mayhem or liquidity events) and non-SOL pools; unwatch the
   lowest-value coins while :meth:`PollScheduler.overloaded`.
4. At a checkpoint ``t_c`` (the grid time, NOT the engine's current time): ``snap = sched.snapshot(mint, t_c,
   sol_usd=...)``. None means the data was not complete: skip the decision (it is reported as missed). Otherwise
   run the lab function unchanged (``m1.strategy(snap, params, pos)``, ``s1.s1_strategy(...)``:
   tests/test_flow_lab_strategies.py) and map ``Enter(exits=ExitSpec(...))`` / ``Exit`` onto the engine's orders;
   ``now - t_c`` is extra decision latency the lab did not have (bound it with ``max_late_s``). The lab modules
   import numpy / pandas / research/lab2/common.py: port the chosen function into src/ (it only reads the AsOf
   interface) or add those packages to the image.
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
from nightcrawler.flow import (
    DECISION_LAG_S,
    MAX_AMOUNT_SOL,
    MAX_PRICE_SOL,
    MAX_TOK_RAW,
    VENUE_AMM,
    VENUE_CURVE,
    FlowSnapshot,
    FlowTracker,
    FlowTrade,
)
from nightcrawler.http import HttpClient, HttpError, RateLimiter, TokenBucket, host_of, provider_of
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
    "DEFAULT_TIMEOUT_S",
    "HOST_BACKOFF_S",
    "COIN_BACKOFF_S",
    "MAX_COIN_BACKOFF_S",
    "MAX_SWEEP_PAGES",
    "OVERLAP_S",
    "MAX_SETTLE_S",
    "ZERO_SID",
    "TradesPage",
    "MalformedTradesPage",
    "TradesBudgetExhausted",
    "TradesHostError",
    "SweepAborted",
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
#: seconds before a request gives up (one tick never stalls the engine loop longer than this)
DEFAULT_TIMEOUT_S = 4.0
#: first host back-off after a timeout / connection error / 5xx / non-JSON 200; doubles while it repeats
HOST_BACKOFF_S = 15.0
#: first back-off of ONE coin after a 4xx, a malformed page or an aborted sweep; doubles up to the max
COIN_BACKOFF_S = 15.0
MAX_COIN_BACKOFF_S = 300.0
#: pages one sweep may use before it is aborted (a 10 s window of a 100 trades/s coin is ~10 pages)
MAX_SWEEP_PAGES = 50
#: seconds below the completed edge that a caught-up sweep re-reads to detect late-indexed trades
OVERLAP_S = 5.0
#: ceiling of the adaptive settle time (checkpoints are due at tau + settle, decided at tau + 20 s)
MAX_SETTLE_S = 12.0
#: tokens of a shared host bucket left for the blocking candle client
SHARED_RESERVE = 1.0
ZERO_SID = "0" * 22
_PROGRAM_VENUE = {"pump": VENUE_CURVE, "pump_amm": VENUE_AMM}
_MAX_BASE_TOKENS = MAX_TOK_RAW / 1_000_000
_TS_RANGE = (1_577_836_800, 4_102_444_800)      # 2020-01-01 .. 2100-01-01: pump.fun's lifetime, with room


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
        ts = int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, OverflowError, OSError):
        return None
    return ts if _TS_RANGE[0] <= ts < _TS_RANGE[1] else None


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def _is_failed(row: Any) -> bool:
    return isinstance(row, Mapping) and bool(row.get("err") or row.get("error") or row.get("success") is False
                                             or row.get("isSuccess") is False)


def parse_trade(row: Any) -> FlowTrade | None:
    """One swap-api trade row -> :class:`FlowTrade`, or None when it is malformed (any field missing, out of range
    or not ASCII digits where digits are due), not a curve / PumpSwap trade, or flagged as failed (defensive:
    swap-api lists successful swaps only). Never raises."""
    try:
        if not isinstance(row, Mapping):
            return None
        sid = row.get("slotIndexId")
        venue = _PROGRAM_VENUE.get(str(row.get("program") or ""))
        side = row.get("type")
        ts = _iso_s(row.get("timestamp"))
        wallet = row.get("userAddress")
        price, amount, base = _num(row.get("priceSol")), _num(row.get("amountSol")), _num(row.get("baseAmount"))
        if (not isinstance(sid, str) or len(sid) != 22 or not (sid.isascii() and sid.isdigit()) or venue is None
                or side not in ("buy", "sell") or ts is None or not isinstance(wallet, str) or not wallet
                or price is None or not 0.0 < price < MAX_PRICE_SOL or amount is None
                or not 0.0 <= amount < MAX_AMOUNT_SOL or base is None or not 0.0 <= base <= _MAX_BASE_TOKENS):
            return None
        if _is_failed(row):
            return None
        slot, pos = split_sid(sid)
        tok_raw = int(round(base * 1_000_000))
        return FlowTrade(slot=slot, pos=pos, sid=sid, ts=ts, wallet=wallet, is_buy=side == "buy", venue=venue,
                         amount_sol=amount, tok_raw=tok_raw, price=price, tx=str(row.get("tx") or ""))
    except Exception:  # noqa: BLE001 - a row must never take the feed down; it is counted as invalid
        return None


class MalformedTradesPage(ValueError):
    """A response body that is not a trades page (no ``trades`` list, no ``pagination`` with a bool ``hasMore``)."""


@dataclass(frozen=True)
class TradesPage:
    trades: list[FlowTrade]          # newest first, as served (failed and unparseable rows dropped)
    next_cursor: str | None
    has_more: bool
    n_rows: int
    n_dropped: int                   # n_failed + n_invalid
    n_failed: int = 0                # rows flagged as failed transactions (excluded by design)
    n_invalid: int = 0               # rows that could not be parsed: the page cannot complete a window


def parse_page(body: Any) -> TradesPage:
    """A trades page, or :class:`MalformedTradesPage` when ``body`` is not one."""
    if not isinstance(body, Mapping):
        raise MalformedTradesPage(f"body is a {type(body).__name__}, not an object")
    rows = body.get("trades")
    if not isinstance(rows, list):
        raise MalformedTradesPage("no trades list")
    pag = body.get("pagination")
    if not isinstance(pag, Mapping):
        raise MalformedTradesPage("no pagination object")
    has_more = pag.get("hasMore")
    if not isinstance(has_more, bool):
        raise MalformedTradesPage("pagination.hasMore is not a bool")
    nxt = pag.get("nextCursor")
    trades: list[FlowTrade] = []
    failed = invalid = 0
    for r in rows:
        t = parse_trade(r)
        if t is not None:
            trades.append(t)
        elif _is_failed(r):
            failed += 1
        else:
            invalid += 1
    return TradesPage(trades=trades, next_cursor=nxt if isinstance(nxt, str) and nxt else None, has_more=has_more,
                      n_rows=len(rows), n_dropped=failed + invalid, n_failed=failed, n_invalid=invalid)


# --------------------------------------------------------------------------- transport


class TradesBudgetExhausted(Exception):
    """This client's bucket (or the shared host bucket) is empty; nothing was sent. ``seconds_left`` until the
    next token."""

    def __init__(self, seconds_left: float) -> None:
        self.seconds_left = max(0.0, float(seconds_left))
        super().__init__(f"pump.fun trades budget exhausted: next request in {self.seconds_left:.1f}s")


class TradesHostError(HttpError):
    """A failure of the HOST, not of one coin (429 / 403 / 503, timeout, connection error, 5xx, a non-JSON 200):
    the host is cooling down; stop sending until it ends."""


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

    def give_back(self) -> None:
        with self._lock:
            self._tokens = min(self.capacity, self._tokens + 1.0)

    def seconds_until(self, n: float = 1.0) -> float:
        with self._lock:
            self._refill()
            return max(0.0, (n - self._tokens) / self.rate)


def _host_bucket(http: HttpClient, host: str) -> TokenBucket | None:
    """The :class:`HttpClient`'s own bucket for ``host`` when one is configured for it (the engine limits the
    pump.fun host for the candle client), else None."""
    limiter = getattr(http, "limiter", None)
    if not isinstance(limiter, RateLimiter) or host not in limiter.limits:
        return None
    return limiter._bucket(host)


def _refill_shared(bucket: TokenBucket) -> None:
    """Refill a :class:`TokenBucket` to now (call under its lock): its own ``acquire`` would sleep instead."""
    now = bucket.clock.now()
    bucket._tokens = min(bucket.capacity, bucket._tokens + max(0.0, now - bucket._last) * bucket.rate)
    bucket._last = now


def _shared_tokens(bucket: TokenBucket) -> float:
    with bucket._lock:
        _refill_shared(bucket)
        return bucket._tokens


def _shared_try_take(bucket: TokenBucket, reserve: float) -> bool:
    """Take one token only when ``reserve`` tokens remain after it (never sleeps)."""
    with bucket._lock:
        _refill_shared(bucket)
        if bucket._tokens >= reserve + 1.0:
            bucket._tokens -= 1.0
            return True
        return False


class PumpFunTradesClient:
    """swap-api trade pages over the shared :class:`HttpClient` session (its usage counter and stats), with its own
    non-blocking bucket, the host's shared bucket and a host cool-down. One call = at most one request; never
    retried inline."""

    def __init__(self, http: HttpClient, *, base_url: str = BASE_URL, clock: Clock | None = None,
                 rate: tuple[float, float] = RATE_LIMIT, cooldowns: dict[str, float] | None = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S, share_host_bucket: bool = True) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.host = host_of(self.base_url)
        self.clock = clock if clock is not None else http.clock
        self.bucket = RequestBucket(rate[0], rate[1], self.clock)
        #: the HttpClient's bucket for this host (shared with the candle client), taken from without sleeping
        self.shared = _host_bucket(http, self.host) if share_host_bucket else None
        #: host -> epoch seconds before which nothing is sent (share the candle client's dict to share back-off)
        self.cooldowns: dict[str, float] = cooldowns if cooldowns is not None else {}
        self.timeout_s = float(timeout_s)
        self.requests_sent = 0
        self.errors = 0
        #: consecutive host-level failures (timeouts, 5xx, non-JSON); the back-off doubles with each
        self.host_failures = 0
        #: last ``x-ratelimit-remaining`` / ``x-ratelimit-limit`` the origin reported (observability only)
        self.ratelimit_remaining: int | None = None
        self.ratelimit_limit: int | None = None

    @property
    def cooldown_until(self) -> float:
        return self.cooldowns.get(self.host, 0.0)

    def capacity_per_s(self) -> float:
        """Sustained requests per second this client may send (its bucket, capped by the shared host bucket)."""
        rate = self.bucket.rate
        return min(rate, self.shared.rate) if self.shared is not None else rate

    def available(self) -> int:
        """Requests that may be sent right now (0 while cooling down)."""
        if self.clock.now() < self.cooldown_until:
            return 0
        n = int(self.bucket.tokens())
        if self.shared is not None:
            n = min(n, int(max(0.0, _shared_tokens(self.shared) - SHARED_RESERVE)))
        return n

    def _take(self) -> float | None:
        """Take a token from both buckets; None when taken, else seconds until one may be."""
        if not self.bucket.try_take():
            return self.bucket.seconds_until()
        if self.shared is not None and not _shared_try_take(self.shared, SHARED_RESERVE):
            self.bucket.give_back()
            left = _shared_tokens(self.shared)
            return max(0.0, (SHARED_RESERVE + 1.0 - left) / self.shared.rate)
        return None

    def fetch_page(self, mint: str, cursor: str | None = None, limit: int = PAGE_LIMIT) -> TradesPage:
        """One page of ``mint``'s trades, newest first, older than ``cursor`` (None = the newest).

        Raises :class:`PumpFunCoolingDown` / :class:`TradesBudgetExhausted` (nothing sent),
        :class:`TradesHostError` (sent; the host is now cooling down) or :class:`HttpError` (sent; this coin's
        request failed: a 4xx other than 403 / 429, or a body that is not a trades page)."""
        now = self.clock.now()
        until = self.cooldown_until
        if now < until:
            raise PumpFunCoolingDown(until - now)
        wait = self._take()
        if wait is not None:
            raise TradesBudgetExhausted(wait)
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
            body = self._send(url, params, now, stats)
            self.host_failures = 0
            try:
                return parse_page(body)
            except MalformedTradesPage as exc:
                stats["errors"] += 1
                self.errors += 1
                raise HttpError(f"malformed trades page: {exc}", url=url, status=200) from None
        finally:
            if usage is not None:
                usage.maybe_flush()

    def _host_failure(self, now: float, why: str) -> None:
        self.host_failures += 1
        seconds = min(MAX_COOLDOWN_S, HOST_BACKOFF_S * 2 ** min(self.host_failures - 1, 10))
        self.cooldowns[self.host] = max(self.cooldowns.get(self.host, 0.0), now + seconds)
        log.warning("pumpfun_trades_host_backoff why=%s cooldown_s=%.0f streak=%d", why, seconds, self.host_failures)

    def _send(self, url: str, params: dict[str, Any], now: float, stats: dict[str, float]) -> Any:
        try:
            resp = self.http.session.request("GET", url, params=params, json=None,
                                             headers=dict(self.http.default_headers), timeout=self.timeout_s)
        except requests.RequestException as exc:
            stats["errors"] += 1
            self.errors += 1
            self._host_failure(now, type(exc).__name__)
            retryable = isinstance(exc, (requests.ConnectionError, requests.Timeout))
            raise TradesHostError(type(exc).__name__, url=url, status=None, retryable=retryable) from exc
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
                raise TradesHostError(f"HTTP {status}", url=url, status=status, body=_text(resp), retryable=True)
            if status >= 500:
                self._host_failure(now, f"HTTP {status}")
                raise TradesHostError(f"HTTP {status}", url=url, status=status, body=_text(resp), retryable=True)
            raise HttpError(f"HTTP {status}", url=url, status=status, body=_text(resp), retryable=False)
        try:
            return resp.json()
        except ValueError:
            stats["errors"] += 1
            self.errors += 1
            self._host_failure(now, "invalid JSON")
            raise TradesHostError("invalid JSON", url=url, status=status, body=_text(resp)) from None

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
        if seconds is None or not math.isfinite(seconds) or seconds <= 0:
            return DEFAULT_COOLDOWN_S
        return min(seconds, MAX_COOLDOWN_S)


def _text(resp: Any) -> str | None:
    try:
        return str(resp.text)
    except Exception:  # pragma: no cover - a response without text
        return None


# --------------------------------------------------------------------------- per-coin sync


class SweepAborted(Exception):
    """A sweep could not be finished safely; nothing was marked complete and the coin backs off (``reason``)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class _Sweep:
    lo_ms: int                   # pages go down to here (below the edge by the overlap when it was fresh)
    hi_ms: int
    edge_ms: int                 # complete_ms when the sweep started: trades below it should already be held
    cursor: str
    started_at: float
    fresh: bool                  # hi was capped by now - settle: the sweep reached real time
    buffer: dict[str, FlowTrade] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)
    pages: int = 0


def _backoff(base: float, n: int, cap: float) -> float:
    return float(min(cap, base * 2 ** min(max(n, 1) - 1, 10)))


class CoinSync:
    """One coin's cursor state: oldest-first catch-up from ``start_ts``, then incremental polling.

    ``tracker.complete_through`` (seconds) always equals ``complete_ms / 1000`` once a sweep finished: every trade
    from ``history_from`` to it is in the tracker. :meth:`next_cursor` starts or continues a sweep; :meth:`on_page`
    consumes its page (and raises :class:`SweepAborted` when the page cannot be trusted).

    A tracker that already covers ``start_ts`` (``history_from <= start_ts <= complete_through``, e.g. a coin
    re-watched with the same tracker) is RESUMED from ``complete_through``; otherwise its coverage is reset to
    ``start_ts`` (:meth:`FlowTracker.reset_history`), so nothing fetched under another start reads as complete."""

    def __init__(self, tracker: FlowTracker, start_ts: float, *, window_s: float = 60.0, settle_s: float = 3.0,
                 min_window_s: float = 10.0, max_window_s: float = 900.0, overlap_s: float = OVERLAP_S,
                 max_settle_s: float = MAX_SETTLE_S, max_pages: int = MAX_SWEEP_PAGES) -> None:
        self.tracker = tracker
        self.mint = tracker.mint
        self.start_ts = float(start_ts)
        self.window_s = float(window_s)
        self.settle_s = float(settle_s)
        self.base_settle_s = self.settle_s
        self.min_window_s, self.max_window_s = float(min_window_s), float(max_window_s)
        self.overlap_s = float(overlap_s)
        self.max_settle_s = max(float(max_settle_s), self.settle_s)
        self.max_pages = int(max_pages)
        self.sweep: _Sweep | None = None
        self.requests = 0
        self.pages_with_trades = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.last_error: str | None = None
        self.last_request_at: float | None = None
        self.retry_after: float = 0.0
        #: trades per second over the last finished sweeps (EWMA), for request estimates
        self.rate_tps = 0.0
        #: trades found below the completed edge that the tracker lacked (indexed later than settle_s)
        self.late_trades = 0
        self.last_late = 0
        self._edge_seen_at: float | None = None
        hf, ct = tracker.history_from, tracker.complete_through
        self.resumed = hf is not None and math.isfinite(ct) and hf <= self.start_ts <= ct
        if self.resumed:
            self.complete_ms = int(math.floor(ct * 1000))
        else:
            self.complete_ms = int(math.floor(self.start_ts)) * 1000
            tracker.reset_history(self.start_ts)

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

    def requests_to(self, through: float) -> int:
        """Requests that will bring ``complete_through`` past ``through`` once it has settled: windows and pages
        (a window is at least one request)."""
        span = through - self.complete_through
        if span <= 0:
            return 0
        pending = len(self.sweep.buffer) if self.sweep is not None else 0
        trades = max(0.0, self.rate_tps * span - pending)
        pages = math.ceil(trades / PAGE_LIMIT) + (1 if trades >= PAGE_LIMIT else 0)
        return max(1, pages, math.ceil(span / max(self.window_s, 1e-9)))

    def caught_up(self, now: float) -> bool:
        return self.sweep is None and self.backlog_s(now) <= self.window_s

    def next_cursor(self, now: float) -> str | None:
        """The cursor of the next request, starting a sweep when none is open; None when nothing is due."""
        if self.sweep is not None:
            return self.sweep.cursor
        cap = int(math.floor((now - self.settle_s) * 1000))
        hi = min(self.complete_ms + int(self.window_s * 1000), cap)
        if hi <= self.complete_ms:
            return None
        lo = self.complete_ms
        if self._edge_seen_at is not None and self.overlap_s > 0:
            floor_ms = int(math.ceil((self.tracker.history_from if self.tracker.history_from is not None
                                      else self.start_ts) * 1000))
            lo = max(floor_ms, self.complete_ms - int(self.overlap_s * 1000))
        self.sweep = _Sweep(lo_ms=lo, hi_ms=hi, edge_ms=self.complete_ms, cursor=cursor_before(hi), started_at=now,
                            fresh=hi == cap)
        return self.sweep.cursor

    def on_page(self, page: TradesPage, now: float) -> int:
        """Consume a page of the open sweep. Returns how many trades reached the tracker (0 until the sweep ends).
        Raises :class:`SweepAborted` (the sweep is dropped, nothing marked complete) when the page cannot be
        trusted: unparseable rows, a page that repeats this sweep's trades, ``hasMore`` without a usable cursor,
        or too many pages."""
        sw = self.sweep
        if sw is None:
            return 0
        self.requests += 1
        sw.pages += 1
        if page.n_invalid:
            self._abort(now, f"{page.n_invalid} of {page.n_rows} rows unparseable")
        if page.trades:
            self.pages_with_trades += 1
            if all(t.sid in sw.seen for t in page.trades):
                self._abort(now, "the page repeats trades of this sweep")
        reached_lo = False
        for t in page.trades:
            sw.seen.add(t.sid)
            ts_ms = t.ts * 1000
            if ts_ms < sw.lo_ms:
                reached_lo = True
                continue
            if ts_ms < sw.hi_ms:
                sw.buffer[t.sid] = t
        if reached_lo or not page.has_more:
            return self._finish(now)
        if page.n_rows == 0:
            self._abort(now, "an empty page says hasMore")
        if not page.next_cursor:
            self._abort(now, "hasMore without nextCursor")
        if page.next_cursor == sw.cursor:
            self._abort(now, "the cursor did not advance")
        if sw.pages >= self.max_pages:
            self._abort(now, f"{sw.pages} pages without reaching the window start")
        sw.cursor = str(page.next_cursor)
        return 0

    def fail(self, now: float, reason: str) -> None:
        """This coin's request or sweep failed: drop the open sweep (never marked complete) and back off."""
        self.sweep = None
        self.errors += 1
        self.consecutive_errors += 1
        self.last_error = reason
        self.retry_after = max(self.retry_after,
                               now + _backoff(COIN_BACKOFF_S, self.consecutive_errors, MAX_COIN_BACKOFF_S))
        log.warning("pumpfun_trades_coin_error mint=%s reason=%s retry_in_s=%.0f", self.mint, reason,
                    self.retry_after - now)

    def _abort(self, now: float, reason: str) -> None:
        self.fail(now, reason)
        raise SweepAborted(reason)

    def _finish(self, now: float) -> int:
        sw = self.sweep
        assert sw is not None
        late = [t for t in sw.buffer.values() if t.ts * 1000 < sw.edge_ms and t.sid not in self.tracker]
        self.last_late = len(late)
        if late:
            self.late_trades += len(late)
            seen_at = self._edge_seen_at if self._edge_seen_at is not None else sw.started_at
            lag = max(seen_at - t.ts for t in late)
            self.settle_s = min(self.max_settle_s, max(self.settle_s, lag + 2.0))
            log.warning("pumpfun_trades_late mint=%s n=%d lag_s=%.1f settle_s=%.1f", self.mint, len(late), lag,
                        self.settle_s)
        n = self.tracker.ingest(sorted(sw.buffer.values(), key=lambda t: t.key))
        span = (sw.hi_ms - sw.edge_ms) / 1000
        if span > 0:
            tps = sum(1 for t in sw.buffer.values() if t.ts * 1000 >= sw.edge_ms) / span
            self.rate_tps = tps if self.rate_tps == 0 else 0.5 * self.rate_tps + 0.5 * tps
        if sw.pages > 3:
            self.window_s = max(self.min_window_s, self.window_s / 2)
        elif sw.pages == 1 and len(sw.buffer) < 50:
            self.window_s = min(self.max_window_s, self.window_s * 2)
        self.complete_ms = sw.hi_ms
        self.tracker.mark_complete(self.complete_ms / 1000)
        self._edge_seen_at = sw.started_at if sw.fresh else None
        self.consecutive_errors = 0
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
    #: the latest checkpoint ever set; ``idle_s`` after it (and none left) the watch stops polling
    last_checkpoint: float | None = None


@dataclass
class TickReport:
    sent: int = 0
    polled: list[str] = field(default_factory=list)
    delivered: int = 0
    stopped: str | None = None            # "cooldown" | "budget" | "network" | None
    errors: dict[str, str] = field(default_factory=dict)
    missed: dict[str, list[float]] = field(default_factory=dict)
    late: dict[str, int] = field(default_factory=dict)   # late-indexed trades found (and recovered) per coin


class PollScheduler:
    """Decides which watched coins to poll within the request budget, and polls them (non-blocking).

    Priority, highest first (:meth:`plan`, pure):

    1. **due** - a checkpoint ``t_c`` whose cutoff ``tau_c = t_c - lag`` has settled (``now - settle_s > tau_c``)
       while the coin is not complete through ``tau_c``: earliest decision first (EDF), ties by estimated requests;
       served until ``t_c + grace_s``;
    2. **prefetch** - a checkpoint within ``lead_s`` that ONE poll after ``tau_c`` settles could not serve (an open
       sweep, a backlog of several windows or pages): catch up before it is due, nearest first. A coin that one
       poll can serve waits for the due time (one request per checkpoint) and is not polled in between;
    3. **catch-up** - history still behind by more than one window (a newly watched coin), shortest job first;
    4. **fresh** - background polling of coins staler than their ``max_staleness_s``, stalest first.

    A checkpoint still incomplete at ``t_c + grace_s`` is MISSED: it is dropped and reported (the strategy must not
    decide on an incomplete snapshot). Read decisions with :meth:`snapshot` at the checkpoint time. A watch whose
    checkpoints are all past by ``idle_s`` stops polling (dormant) until :meth:`add_checkpoint`."""

    def __init__(self, client: PumpFunTradesClient, *, lag_s: float = DECISION_LAG_S, lead_s: float = 120.0,
                 grace_s: float = 10.0, idle_s: float | None = None, clock: Clock | None = None) -> None:
        self.client = client
        self.clock = clock if clock is not None else client.clock
        self.lag_s = float(lag_s)
        self.lead_s = float(lead_s)
        self.grace_s = float(grace_s)
        self.idle_s = self.lead_s if idle_s is None else float(idle_s)
        self.watches: dict[str, Watch] = {}
        #: the highest settle time any coin needed (indexing lag is the host's): applied to every coin
        self.settle_floor = 0.0
        self._missed_pending: dict[str, list[float]] = {}

    def watch(self, tracker: FlowTracker, start_ts: float, checkpoints: Iterable[float] = (), *,
              max_staleness_s: float | None = 60.0, window_s: float = 60.0, settle_s: float = 3.0) -> Watch:
        """Track ``tracker``'s coin from ``start_ts`` (creation for curve / wallet features, graduation for pool
        features only). Re-watching the same tracker from the same or a later start keeps the sync and replaces
        the checkpoints; an earlier start (or another tracker) re-syncs, resuming whatever the tracker already
        covers (:class:`CoinSync`)."""
        w = self.watches.get(tracker.mint)
        hf = tracker.history_from
        if w is None or w.sync.tracker is not tracker or hf is None or float(start_ts) < hf:
            sync = CoinSync(tracker, start_ts, window_s=window_s, settle_s=max(settle_s, self.settle_floor))
            if w is None:
                w = Watch(sync)
                self.watches[tracker.mint] = w
            else:
                w.sync = sync
        w.checkpoints = sorted(float(c) for c in checkpoints)
        w.last_checkpoint = max(w.checkpoints) if w.checkpoints else None
        w.max_staleness_s = max_staleness_s
        return w

    def unwatch(self, mint: str) -> None:
        self.watches.pop(mint, None)
        self._missed_pending.pop(mint, None)

    def add_checkpoint(self, mint: str, t: float) -> None:
        w = self.watches[mint]
        w.checkpoints = sorted({*w.checkpoints, float(t)})
        w.last_checkpoint = max(float(t), w.last_checkpoint if w.last_checkpoint is not None else -math.inf)

    # ------------------------------------------------------------------ decisions
    def snapshot(self, mint: str, t_c: float, *, now: float | None = None, sol_usd: float | None = None,
                 max_late_s: float | None = None) -> FlowSnapshot | None:
        """The coin as of the checkpoint ``t_c`` (cutoff ``t_c - lag``), however late the engine evaluates it, or
        None when it cannot be decided on: the data through the cutoff is not complete, or the evaluation is more
        than ``max_late_s`` after ``t_c``. A None is recorded as MISSED (once) and reported by the next tick."""
        w = self.watches[mint]
        now = self.clock.now() if now is None else now
        snap = w.sync.tracker.as_of(t_c, lag_s=self.lag_s, sol_usd=sol_usd)
        if snap.complete and (max_late_s is None or now - t_c <= max_late_s):
            return snap
        if t_c not in w.missed:
            w.missed.append(t_c)
            self._missed_pending.setdefault(mint, []).append(t_c)
        w.checkpoints = [c for c in w.checkpoints if c != t_c]
        log.info("flow_decision_skipped mint=%s t_c=%.0f complete=%s late_s=%.1f", mint, t_c, snap.complete,
                 now - t_c)
        return None

    # ------------------------------------------------------------------ planning (pure)
    def _expire(self, w: Watch, now: float) -> list[float]:
        done = [c for c in w.checkpoints if w.sync.complete_through > c - self.lag_s]
        missed = [c for c in w.checkpoints if c + self.grace_s < now and w.sync.complete_through <= c - self.lag_s]
        if done or missed:
            w.checkpoints = [c for c in w.checkpoints if c not in done and c not in missed]
            w.missed.extend(missed)
        return missed

    def dormant(self, w: Watch, now: float) -> bool:
        """The watch's checkpoints are all past by ``idle_s``: no background polling (a watch without checkpoints
        is never dormant)."""
        return (w.last_checkpoint is not None and not w.checkpoints
                and now > w.last_checkpoint + self.grace_s + self.idle_s)

    def rank(self, w: Watch, now: float) -> tuple | None:
        """Sort key of a watch (lower = sooner), or None when it needs nothing now."""
        s = w.sync
        if now < s.retry_after:
            return None
        if s.sweep is None and s.backlog_s(now) <= 0:
            return None
        pend = [c for c in w.checkpoints if c + self.grace_s >= now and s.complete_through <= c - self.lag_s]
        if pend:
            c = pend[0]
            tau_c = c - self.lag_s
            if now - s.settle_s > tau_c:
                return (0, c, s.estimate_requests(now, tau_c + 1))
            if c - now <= self.lead_s:
                need = s.requests_to(tau_c + 1)
                if s.sweep is not None or need > 1:
                    return (1, c, need)
                return None          # one poll once tau_c settles serves it (and refreshes the coin)
        if self.dormant(w, now):
            return None
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
        unwatch the least important coins when it does not fit (busy fresh graduates run 300-1,500 trades/min).
        Dormant watches need nothing."""
        now = self.clock.now() if now is None else now
        out = {}
        for mint, w in self.watches.items():
            s = w.sync
            if self.dormant(w, now):
                out[mint] = 0.0
                continue
            polls = 60.0 / w.max_staleness_s if w.max_staleness_s else 0.0
            out[mint] = max(s.rate_tps * 60.0 / 100.0, polls) + s.estimate_requests(now) / 10.0  # backlog over 10 min
        return out

    def capacity_per_min(self) -> float:
        return self.client.capacity_per_s() * 60.0

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
    def _raise_settle(self, s: CoinSync) -> None:
        if s.settle_s > self.settle_floor:
            self.settle_floor = s.settle_s
            for w in self.watches.values():
                w.sync.settle_s = max(w.sync.settle_s, self.settle_floor)

    def tick(self, now: float | None = None, max_requests: int | None = None) -> TickReport:
        """Send what the budget allows right now (never sleeps, never retries inline, never raises for one coin's
        data: errors are counted, reported and backed off)."""
        now = self.clock.now() if now is None else now
        rep = TickReport()
        for mint, ts in self._missed_pending.items():
            rep.missed.setdefault(mint, []).extend(ts)
        self._missed_pending.clear()
        for mint, w in self.watches.items():
            missed = self._expire(w, now)
            if missed:
                rep.missed.setdefault(mint, []).extend(missed)
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
            s = w.sync
            cursor = s.next_cursor(now)
            if cursor is None:
                s.retry_after = now + 1.0
                continue
            try:
                page = self.client.fetch_page(mint, cursor)
            except PumpFunCoolingDown:
                rep.stopped = "cooldown"
                break
            except TradesBudgetExhausted:
                rep.stopped = "budget"
                break
            except TradesHostError as exc:          # the host, not this coin: keep the sweep, stop sending
                rep.sent += 1
                s.errors += 1
                s.last_error = rep.errors[mint] = str(exc)
                rep.stopped = "cooldown" if exc.status in COOLDOWN_STATUSES else "network"
                break
            except HttpError as exc:                # this coin only (bad mint, a body that is not a trades page)
                rep.sent += 1
                budget -= 1
                rep.errors[mint] = str(exc)
                s.fail(now, str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 - one coin's surprise must not stop the loop
                rep.sent += 1
                budget -= 1
                rep.errors[mint] = f"{type(exc).__name__}: {exc}"
                s.fail(now, rep.errors[mint])
                continue
            rep.sent += 1
            budget -= 1
            s.last_request_at = now
            rep.polled.append(mint)
            try:
                rep.delivered += s.on_page(page, now)
            except SweepAborted as exc:
                rep.errors[mint] = f"sweep aborted: {exc.reason}"
                continue
            except Exception as exc:  # noqa: BLE001 - see above
                rep.errors[mint] = f"{type(exc).__name__}: {exc}"
                s.fail(now, rep.errors[mint])
                continue
            if s.last_late:
                rep.late[mint] = rep.late.get(mint, 0) + s.last_late
                s.last_late = 0
                self._raise_settle(s)
            for c in list(w.checkpoints):
                if s.complete_through > c - self.lag_s:
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
                         "rate_tps": s.rate_tps, "window_s": s.window_s, "settle_s": s.settle_s,
                         "next_checkpoint": w.checkpoints[:1], "missed": len(w.missed), "errors": s.errors,
                         "last_error": s.last_error, "late_trades": s.late_trades, "dormant": self.dormant(w, now)}
        return out

"""Shared HTTP client: per-host rate limits, retries with backoff, clear errors.

Every outbound request in nightcrawler goes through :class:`HttpClient` so the
free-tier budgets of each API are respected globally (one bucket per host,
shared by all callers).

Behaviour (the contract):

* **Rate limit**: token bucket per host (``rate`` requests/second, ``burst``
  capacity). Every attempt - including retries - takes a token. Waiting uses
  ``clock.sleep`` so tests/backtests with :class:`~nightcrawler.clock.FakeClock`
  never block. Unknown hosts use ``default_rate``; ``default_rate=None`` and a
  host missing from ``rate_limits`` means unlimited.
* **Retries** (``retry=True``, the default): on HTTP 429 and 5xx, and on
  connection errors / timeouts, up to ``max_retries`` (4) extra attempts.
  Delay = exponential backoff
  ``min(backoff_max_s, backoff_base_s * 2**attempt) * U(0.5, 1.0)``, raised
  to the ``Retry-After`` header when that is longer (seconds or HTTP date,
  capped at ``retry_after_max_s``). ``Retry-After: 0`` (GeckoTerminal sends
  it with 429s) therefore never causes an immediate retry storm.
  Use ``retry=False`` for non-idempotent calls (Ultra ``/execute``).
  ``host_max_retries={"api.geckoterminal.com": 1}`` lowers the retry count
  for one host (the engine does this so a GT 429 storm cannot stall its loop).
* **Errors**: anything that does not end in a 2xx JSON response raises
  :class:`HttpError` with ``status`` (None for network errors), ``url``
  (secrets redacted), ``body`` (first 500 chars), ``payload`` (parsed JSON
  body if any) and ``retryable``.
* **JSON**: 2xx responses are decoded with ``response.json()``; an empty body
  returns ``None``; undecodable bodies raise ``HttpError("invalid JSON")``.
* **Timeouts**: 10 s per attempt by default (``timeout_s``).
* **Logging**: only host + path are logged (never query strings or headers).
* **Provider usage** (``client.usage``, a :class:`UsageTracker`): every attempt
  (retries included: each one counts against a free tier) is counted
  per provider (:func:`provider_of`: ``helius``, ``solana_rpc``, ``jupiter``,
  ``geckoterminal``, ``dexscreener``, ``rugcheck``, ``pumpfun``, ``other``) per
  UTC day and month; Helius also counts 1 credit per call. Counts stay in memory
  until :func:`attach_usage_store` binds a ledger; then they are MERGED into kv
  ``usage.providers`` (one transaction, so processes sharing a ledger add up)
  after a request completes, at most every :data:`USAGE_FLUSH_EVERY_S`. Only
  provider names are stored - never a URL, host or key. The judge's Anthropic
  calls do not go through this client: it reports them with :func:`record_usage`
  and :func:`anthropic_usage_counts`. Stored shape, per provider::

      {"day": "YYYY-MM-DD", "day_counts": {"calls": n, ...},
       "month": "YYYY-MM", "month_counts": {"calls": n, ...}, "updated_at": ts}

The ``session`` is anything with ``requests.Session.request``'s signature:
``request(method, url, params=..., json=..., headers=..., timeout=...)``
returning an object with ``status_code``, ``headers``, ``content``, ``text``
and ``json()``. Tests pass ``tests/fakes.py::FakeHttp``.
"""

from __future__ import annotations

import contextlib
import email.utils
import math
import random
import threading
from collections import defaultdict
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import requests

from nightcrawler import __version__
from nightcrawler.clock import Clock, RealClock, utc_day
from nightcrawler.config import redact_rpc_url, redact_url
from nightcrawler.logging_setup import get_logger

__all__ = [
    "HttpError",
    "TokenBucket",
    "RateLimiter",
    "HttpClient",
    "UsageTracker",
    "DEFAULT_RATE_LIMITS",
    "DEFAULT_RATE",
    "RETRY_STATUSES",
    "PROVIDERS",
    "CREDITS_PER_CALL",
    "KV_USAGE",
    "USAGE_FLUSH_EVERY_S",
    "host_of",
    "provider_of",
    "merge_usage",
    "record_usage",
    "anthropic_usage_counts",
    "attach_usage_store",
    "flush_usage",
]

log = get_logger(__name__)

#: host -> (requests per second, burst capacity)
DEFAULT_RATE_LIMITS: dict[str, tuple[float, float]] = {
    "api.geckoterminal.com": (20 / 60, 2),  # free tier ~30/min on a shared IP -> budget 20/min
    "api.rugcheck.xyz": (1.0, 1),
    "lite-api.jup.ag": (1.0, 1),
    "api.jup.ag": (1.0, 1),
    "api.dexscreener.com": (1.0, 3),  # 60/min
    "api.mainnet-beta.solana.com": (5.0, 5),
}
#: Rate for hosts not listed above (custom RPC URLs etc.).
DEFAULT_RATE: tuple[float, float] = (5.0, 5)
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def host_of(url: str) -> str:
    """Lower-case host (no port) of ``url``."""
    return (urlsplit(url).hostname or "").lower()


def _short(url: str, secret_path: bool = False) -> str:
    parts = urlsplit(url)
    path = "/***" if secret_path and parts.path not in ("", "/") else parts.path
    return f"{parts.hostname}{path}"


# --------------------------------------------------------------------------- provider usage

#: Provider id -> label, in the dashboard's order (see :func:`provider_of`).
PROVIDERS: dict[str, str] = {
    "helius": "Helius", "solana_rpc": "Solana RPC", "jupiter": "Jupiter", "geckoterminal": "GeckoTerminal",
    "dexscreener": "DexScreener", "rugcheck": "RugCheck", "pumpfun": "pump.fun", "anthropic": "Anthropic",
    "other": "Other",
}
#: provider -> its domains (the domain itself or any subdomain), checked in this order.
_PROVIDER_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("helius", ("helius-rpc.com", "helius.xyz", "helius.dev")),
    ("jupiter", ("jup.ag",)),
    ("geckoterminal", ("geckoterminal.com",)),
    ("dexscreener", ("dexscreener.com",)),
    ("rugcheck", ("rugcheck.xyz",)),
    ("pumpfun", ("pump.fun",)),
    ("anthropic", ("anthropic.com",)),
    ("solana_rpc", ("solana.com",)),
)
#: Credits per call for providers that bill in credits (Helius: 1 per standard RPC call; its heavier
#: methods, e.g. getProgramAccounts, cost more but nightcrawler does not use them).
CREDITS_PER_CALL: dict[str, int] = {"helius": 1}
#: Ledger kv key holding the persisted counters (shape in the module docstring).
KV_USAGE = "usage.providers"
#: A bound :class:`UsageTracker` writes to the ledger at most this often (seconds).
USAGE_FLUSH_EVERY_S = 60.0


def provider_of(host: str, rpc_host: str | None = None) -> str:
    """Provider id of ``host`` (a key of :data:`PROVIDERS`); ``rpc_host`` (the SOLANA_RPC_URL
    host) counts as ``solana_rpc`` unless it is a known provider such as Helius."""
    host = host.lower()
    for provider, domains in _PROVIDER_DOMAINS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return provider
    return "solana_rpc" if rpc_host and host == rpc_host.lower() else "other"


def _number(value: Any) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return value if ok else 0


def merge_usage(stored: Any, provider: str, day: str, counts: Mapping[str, float], now: float) -> dict[str, Any]:
    """PURE: kv ``usage.providers`` value ``stored`` plus ``counts`` made by ``provider`` on UTC ``day``.

    A newer day (month) restarts the day (month) counters. Counts of an OLDER day - a late
    flush after midnight - never touch the newer day, but still add to their month while it
    is the stored one.
    """
    data = dict(stored) if isinstance(stored, Mapping) else {}
    entry = dict(data[provider]) if isinstance(data.get(provider), Mapping) else {}
    for period, key in (("day", day), ("month", day[:7])):
        bucket = f"{period}_counts"
        current = entry.get(period)
        if current == key and isinstance(entry.get(bucket), Mapping):
            totals = dict(entry[bucket])
            for name, value in counts.items():
                total = _number(totals.get(name)) + _number(value)
                totals[name] = round(total, 9) if isinstance(total, float) else total
            entry[bucket] = totals
        elif not isinstance(current, str) or key >= current:
            entry[period], entry[bucket] = key, {name: _number(value) for name, value in counts.items()}
    entry["updated_at"] = now
    data[provider] = entry
    return data


def _merge_into(store: Any, pending: Mapping[tuple[str, str], Mapping[str, float]], now: float) -> None:
    """Merge ``{(provider, day): counts}`` into the store's kv in ONE transaction (when it has one)."""
    transaction = getattr(store, "transaction", None)
    with transaction() if callable(transaction) else contextlib.nullcontext():
        data = store.get_kv(KV_USAGE)
        for (provider, day), counts in sorted(pending.items(), key=lambda item: item[0][1]):
            data = merge_usage(data, provider, day, counts, now)
        store.set_kv(KV_USAGE, data)


def record_usage(store: Any, provider: str, now: float, **counts: float) -> None:
    """Add ``counts`` (default ``calls=1``) for ``provider`` at ``now`` straight into ``store``'s kv.

    For calls that do not go through :class:`HttpClient` (the judge's Anthropic SDK calls).
    ``store=None`` does nothing. Never raises: a failure is logged and the count dropped.
    """
    if store is None:
        return
    try:
        _merge_into(store, {(provider, utc_day(now)): counts or {"calls": 1}}, now)
    except Exception as exc:  # usage accounting must never break the caller
        log.warning("usage_record_failed provider=%s error=%s", provider, type(exc).__name__)


def anthropic_usage_counts(usage: Any, cost_usd: float) -> dict[str, float]:
    """Counts for one Anthropic API call from its ``response.usage`` (object, dict or None):
    ``{calls: 1, input_tokens (incl. cache reads/writes), output_tokens, cost_usd}``."""
    def tokens(name: str) -> int:
        value = usage.get(name) if isinstance(usage, Mapping) else getattr(usage, name, None)
        return int(_number(value))

    cache = tokens("cache_read_input_tokens") + tokens("cache_creation_input_tokens")
    return {"calls": 1, "input_tokens": tokens("input_tokens") + cache, "output_tokens": tokens("output_tokens"),
            "cost_usd": float(_number(cost_usd))}


class UsageTracker:
    """Calls (and credits) per provider per UTC day and month; see the module docstring.

    :meth:`record` only touches memory. With a store bound (:meth:`bind`, anything with
    ``get_kv``/``set_kv`` and ideally ``transaction()``), :meth:`maybe_flush` merges the
    pending counts into kv ``usage.providers`` at most every ``flush_every_s``. A failed write
    keeps the counts for the next flush and never raises. Thread-safe.
    """

    def __init__(self, clock: Clock, store: Any = None, *, flush_every_s: float = USAGE_FLUSH_EVERY_S) -> None:
        self.clock = clock
        self.store = store
        self.flush_every_s = flush_every_s
        self._pending: dict[tuple[str, str], dict[str, float]] = {}
        self._last_flush: float | None = None
        self._lock = threading.Lock()

    def bind(self, store: Any) -> None:
        """Persist into ``store`` from now on; counts recorded before are written at the next flush."""
        with self._lock:
            self.store = store
            self._last_flush = None

    def record(self, provider: str, **counts: float) -> None:
        """Add ``counts`` (default ``calls=1``; credits added for credit-billed providers) to today's."""
        counts = dict(counts or {"calls": 1})
        if provider in CREDITS_PER_CALL and "credits" not in counts:
            counts["credits"] = counts.get("calls", 0) * CREDITS_PER_CALL[provider]
        key = (provider, utc_day(self.clock.now()))
        with self._lock:
            self._add(key, counts)

    def maybe_flush(self) -> None:
        """:meth:`flush` when a store is bound and the last flush is at least ``flush_every_s`` old."""
        with self._lock:
            due = self.store is not None and (
                self._last_flush is None or self.clock.now() - self._last_flush >= self.flush_every_s)
        if due:
            self.flush()

    def flush(self) -> bool:
        """Merge the pending counts into the store now. False (counts kept) without a store or on error."""
        now = self.clock.now()
        with self._lock:
            store, pending = self.store, self._pending
            if store is None:
                return False
            self._pending, self._last_flush = {}, now
        if not pending:
            return True
        try:
            _merge_into(store, pending, now)
        except Exception as exc:  # usage accounting must never break a request
            log.warning("usage_flush_failed error=%s", type(exc).__name__)
            with self._lock:
                for key, counts in pending.items():
                    self._add(key, counts)
            return False
        return True

    def _add(self, key: tuple[str, str], counts: Mapping[str, float]) -> None:
        bucket = self._pending.setdefault(key, {})
        for name, value in counts.items():
            bucket[name] = bucket.get(name, 0) + value


def attach_usage_store(http: Any, store: Any) -> None:
    """Persist ``http.usage`` (an :class:`HttpClient`'s tracker) into ``store``, normally the
    ledger. A client without usage tracking (a test double) is left alone."""
    usage = getattr(http, "usage", None)
    if isinstance(usage, UsageTracker):
        usage.bind(store)


def flush_usage(http: Any) -> bool:
    """Write ``http.usage``'s pending counts now (call before closing the ledger at shutdown, so the
    last minute is not lost). False for a client without usage tracking or when nothing could be written."""
    usage = getattr(http, "usage", None)
    return usage.flush() if isinstance(usage, UsageTracker) else False


class HttpError(Exception):
    """A request that did not produce a usable 2xx JSON response.

    ``secret_paths=True`` (hosts such as a QuickNode/Alchemy RPC whose API key is part of
    the PATH) keeps only scheme and host in ``url`` and the message.
    """

    def __init__(self, message: str, *, url: str, status: int | None = None, body: str | None = None,
                 payload: Any = None, retryable: bool = False, secret_paths: bool = False) -> None:
        self.url = redact_rpc_url(url) if secret_paths else redact_url(url)
        self.status = status
        self.body = body[:500] if body else body
        self.payload = payload
        self.retryable = retryable
        where = _short(url, secret_paths)
        super().__init__(f"{message} [{status if status is not None else 'no response'}] {where}")


class _Session(Protocol):  # pragma: no cover - typing only
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class TokenBucket:
    """Classic token bucket driven by a :class:`Clock` (thread-safe)."""

    def __init__(self, rate_per_s: float, burst: float, clock: Clock) -> None:
        if rate_per_s <= 0 or burst < 1:
            raise ValueError("rate must be > 0 and burst >= 1")
        self.rate = float(rate_per_s)
        self.capacity = float(burst)
        self.clock = clock
        self._tokens = float(burst)
        self._last = clock.now()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Take one token, sleeping on the clock if needed. Returns seconds waited."""
        with self._lock:
            now = self.clock.now()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            wait = (1.0 - self._tokens) / self.rate
            self.clock.sleep(wait)
            self._tokens = 0.0
            self._last = self.clock.now()
            return wait


class RateLimiter:
    """Per-host buckets. ``acquire(host)`` blocks (via the clock) until allowed."""

    def __init__(self, clock: Clock, limits: Mapping[str, tuple[float, float]] | None = None,
                 default: tuple[float, float] | None = DEFAULT_RATE) -> None:
        self.clock = clock
        self.limits = dict(DEFAULT_RATE_LIMITS if limits is None else limits)
        self.default = default
        self._buckets: dict[str, TokenBucket | None] = {}
        self._lock = threading.Lock()

    def set_limit(self, host: str, rate_per_s: float, burst: float = 1) -> None:
        with self._lock:
            self.limits[host.lower()] = (rate_per_s, burst)
            self._buckets.pop(host.lower(), None)

    def _bucket(self, host: str) -> TokenBucket | None:
        with self._lock:
            if host not in self._buckets:
                spec = self.limits.get(host, self.default)
                self._buckets[host] = TokenBucket(spec[0], spec[1], self.clock) if spec else None
            return self._buckets[host]

    def acquire(self, host: str) -> float:
        bucket = self._bucket(host.lower())
        return bucket.acquire() if bucket else 0.0


class HttpClient:
    """JSON-over-HTTP with rate limits and retries. See module docstring."""

    def __init__(self, session: _Session | None = None, clock: Clock | None = None, *,
                 rate_limits: Mapping[str, tuple[float, float]] | None = None,
                 default_rate: tuple[float, float] | None = DEFAULT_RATE,
                 timeout_s: float = 10.0, max_retries: int = 4, backoff_base_s: float = 1.0,
                 backoff_max_s: float = 30.0, retry_after_max_s: float = 60.0,
                 rng: random.Random | None = None, user_agent: str | None = None,
                 host_max_retries: Mapping[str, int] | None = None) -> None:
        self.session = session if session is not None else requests.Session()
        #: Per-host override of ``max_retries`` (e.g. fail fast on a rate-limited host whose
        #: callers retry on their own schedule anyway).
        self.host_max_retries = {h.lower(): int(n) for h, n in (host_max_retries or {}).items()}
        #: Hosts whose URL PATH holds an API key (QuickNode/Alchemy-style RPC URLs): errors show host only.
        self.secret_path_hosts: set[str] = set()
        self.clock = clock or RealClock()
        self.limiter = RateLimiter(self.clock, rate_limits, default_rate)
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self.retry_after_max_s = retry_after_max_s
        self.rng = rng or random.Random()
        self.default_headers = {"User-Agent": user_agent or f"nightcrawler/{__version__}",
                                "Accept": "application/json"}
        #: counters per host: requests, retries, errors, rate_wait_s
        self.stats: dict[str, dict[str, float]] = defaultdict(
            lambda: {"requests": 0, "retries": 0, "errors": 0, "rate_wait_s": 0.0})
        #: calls per provider per UTC day/month (persisted once :func:`attach_usage_store` binds a ledger)
        self.usage = UsageTracker(self.clock)
        #: host of SOLANA_RPC_URL (set by :meth:`from_settings`): its calls count as ``solana_rpc``
        self.rpc_host: str | None = None

    @classmethod
    def from_settings(cls, settings: Any, session: _Session | None = None, clock: Clock | None = None,
                      **kwargs: Any) -> "HttpClient":
        """Default client; the host of ``settings.solana_rpc_url`` gets 5 req/s unless listed."""
        client = cls(session=session, clock=clock, **kwargs)
        rpc_url = getattr(settings, "solana_rpc_url", "") or ""
        rpc_host = host_of(rpc_url)
        client.rpc_host = rpc_host or None
        if rpc_host and rpc_host not in client.limiter.limits:
            client.limiter.set_limit(rpc_host, 5.0, 5)
        if rpc_host and urlsplit(rpc_url).path not in ("", "/"):
            client.secret_path_hosts.add(rpc_host)
        return client

    # ------------------------------------------------------------------ public
    def get_json(self, url: str, params: Mapping[str, Any] | None = None,
                 headers: Mapping[str, str] | None = None, *, timeout_s: float | None = None,
                 retry: bool = True) -> Any:
        """GET ``url`` and return decoded JSON (or None for an empty body)."""
        return self.request_json("GET", url, params=params, headers=headers, timeout_s=timeout_s, retry=retry)

    def post_json(self, url: str, json: Any = None, headers: Mapping[str, str] | None = None, *,
                  timeout_s: float | None = None, retry: bool = True) -> Any:
        """POST a JSON body and return decoded JSON. Pass ``retry=False`` for non-idempotent calls."""
        return self.request_json("POST", url, json_body=json, headers=headers, timeout_s=timeout_s, retry=retry)

    def request_json(self, method: str, url: str, *, params: Mapping[str, Any] | None = None,
                     json_body: Any = None, headers: Mapping[str, str] | None = None,
                     timeout_s: float | None = None, retry: bool = True) -> Any:
        try:
            return self._request_json(method, url, params=params, json_body=json_body, headers=headers,
                                      timeout_s=timeout_s, retry=retry)
        finally:  # after the call, never between a request and its send (e.g. Ultra /execute)
            self.usage.maybe_flush()

    def _request_json(self, method: str, url: str, *, params: Mapping[str, Any] | None,
                      json_body: Any, headers: Mapping[str, str] | None, timeout_s: float | None,
                      retry: bool) -> Any:
        host = host_of(url)
        hdrs = {**self.default_headers, **(headers or {})}
        timeout = self.timeout_s if timeout_s is None else timeout_s
        stats = self.stats[host]
        max_retries = self.host_max_retries.get(host, self.max_retries)
        secret_paths = host in self.secret_path_hosts
        provider = provider_of(host, self.rpc_host)
        attempt = 0
        while True:
            stats["rate_wait_s"] += self.limiter.acquire(host)
            stats["requests"] += 1
            self.usage.record(provider)
            try:
                resp = self.session.request(method, url, params=params, json=json_body, headers=hdrs,
                                            timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                err = HttpError(f"{type(exc).__name__}", url=url, status=None, retryable=True,
                                secret_paths=secret_paths)
                if retry and attempt < max_retries:
                    self._sleep_retry(host, attempt, None, f"{type(exc).__name__}")
                    attempt += 1
                    continue
                stats["errors"] += 1
                raise err from exc
            except requests.RequestException as exc:
                stats["errors"] += 1
                raise HttpError(f"{type(exc).__name__}", url=url, status=None, retryable=False,
                                secret_paths=secret_paths) from exc

            status = int(resp.status_code)
            if status in RETRY_STATUSES or 500 <= status < 600:
                if retry and attempt < max_retries:
                    self._sleep_retry(host, attempt, resp, f"status={status}")
                    attempt += 1
                    continue
                stats["errors"] += 1
                raise self._error(f"HTTP {status}", url, resp, retryable=True, secret_paths=secret_paths)
            if status >= 400:
                stats["errors"] += 1
                raise self._error(f"HTTP {status}", url, resp, retryable=False, secret_paths=secret_paths)
            content = getattr(resp, "content", b"")
            if not content or not content.strip():
                return None
            try:
                return resp.json()
            except ValueError:
                stats["errors"] += 1
                raise self._error("invalid JSON", url, resp, retryable=False, secret_paths=secret_paths) from None

    # ------------------------------------------------------------------ internals
    def backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter for retry number ``attempt`` (0-based)."""
        base = min(self.backoff_max_s, self.backoff_base_s * (2 ** attempt))
        return base * (0.5 + self.rng.random() / 2)

    def _retry_after(self, resp: Any) -> float | None:
        if resp is None:
            return None
        headers = getattr(resp, "headers", None) or {}
        value = None
        for k, v in headers.items():
            if k.lower() == "retry-after":
                value = str(v).strip()
                break
        if not value:
            return None
        try:
            seconds = float(value)
        except ValueError:
            try:
                dt = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            seconds = dt.timestamp() - self.clock.now()
        return max(0.0, min(seconds, self.retry_after_max_s))

    def _sleep_retry(self, host: str, attempt: int, resp: Any, why: str) -> None:
        # Retry-After is a FLOOR, never a shortcut: GeckoTerminal answers 429 with
        # ``Retry-After: 0``, and honouring that literally produced back-to-back
        # retries (a 429 storm) that burned the scarcest rate budget.
        backoff = self.backoff_delay(attempt)
        retry_after = self._retry_after(resp)
        delay = backoff if retry_after is None else max(retry_after, backoff)
        self.stats[host]["retries"] += 1
        log.warning("http_retry host=%s why=%s attempt=%d delay_s=%.2f", host, why, attempt + 1, delay)
        self.clock.sleep(delay)

    @staticmethod
    def _error(message: str, url: str, resp: Any, *, retryable: bool, secret_paths: bool = False) -> HttpError:
        text = None
        try:
            text = resp.text
        except Exception:  # pragma: no cover
            text = None
        payload = None
        try:
            payload = resp.json()
        except Exception:
            payload = None
        return HttpError(message, url=url, status=int(resp.status_code), body=text, payload=payload,
                         retryable=retryable, secret_paths=secret_paths)

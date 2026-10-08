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
  Delay = ``Retry-After`` header when present (seconds or HTTP date, capped
  at ``retry_after_max_s``), else exponential backoff
  ``min(backoff_max_s, backoff_base_s * 2**attempt) * U(0.5, 1.0)``.
  Use ``retry=False`` for non-idempotent calls (Ultra ``/execute``).
* **Errors**: anything that does not end in a 2xx JSON response raises
  :class:`HttpError` with ``status`` (None for network errors), ``url``
  (secrets redacted), ``body`` (first 500 chars), ``payload`` (parsed JSON
  body if any) and ``retryable``.
* **JSON**: 2xx responses are decoded with ``response.json()``; an empty body
  returns ``None``; undecodable bodies raise ``HttpError("invalid JSON")``.
* **Timeouts**: 10 s per attempt by default (``timeout_s``).
* **Logging**: only host + path are logged (never query strings or headers).

The ``session`` is anything with ``requests.Session.request``'s signature:
``request(method, url, params=..., json=..., headers=..., timeout=...)``
returning an object with ``status_code``, ``headers``, ``content``, ``text``
and ``json()``. Tests pass ``tests/fakes.py::FakeHttp``.
"""

from __future__ import annotations

import email.utils
import random
import threading
from collections import defaultdict
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import requests

from nightcrawler import __version__
from nightcrawler.clock import Clock, RealClock
from nightcrawler.config import redact_url
from nightcrawler.logging_setup import get_logger

__all__ = [
    "HttpError",
    "TokenBucket",
    "RateLimiter",
    "HttpClient",
    "DEFAULT_RATE_LIMITS",
    "DEFAULT_RATE",
    "RETRY_STATUSES",
    "host_of",
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


def _short(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname}{parts.path}"


class HttpError(Exception):
    """A request that did not produce a usable 2xx JSON response."""

    def __init__(self, message: str, *, url: str, status: int | None = None, body: str | None = None,
                 payload: Any = None, retryable: bool = False) -> None:
        self.url = redact_url(url)
        self.status = status
        self.body = body[:500] if body else body
        self.payload = payload
        self.retryable = retryable
        where = _short(url)
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
                 rng: random.Random | None = None, user_agent: str | None = None) -> None:
        self.session = session if session is not None else requests.Session()
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

    @classmethod
    def from_settings(cls, settings: Any, session: _Session | None = None, clock: Clock | None = None,
                      **kwargs: Any) -> "HttpClient":
        """Default client; the host of ``settings.solana_rpc_url`` gets 5 req/s unless listed."""
        client = cls(session=session, clock=clock, **kwargs)
        rpc_host = host_of(getattr(settings, "solana_rpc_url", "") or "")
        if rpc_host and rpc_host not in client.limiter.limits:
            client.limiter.set_limit(rpc_host, 5.0, 5)
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
        host = host_of(url)
        hdrs = {**self.default_headers, **(headers or {})}
        timeout = self.timeout_s if timeout_s is None else timeout_s
        stats = self.stats[host]
        attempt = 0
        while True:
            stats["rate_wait_s"] += self.limiter.acquire(host)
            stats["requests"] += 1
            try:
                resp = self.session.request(method, url, params=params, json=json_body, headers=hdrs,
                                            timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                err = HttpError(f"{type(exc).__name__}", url=url, status=None, retryable=True)
                if retry and attempt < self.max_retries:
                    self._sleep_retry(host, attempt, None, f"{type(exc).__name__}")
                    attempt += 1
                    continue
                stats["errors"] += 1
                raise err from exc
            except requests.RequestException as exc:
                stats["errors"] += 1
                raise HttpError(f"{type(exc).__name__}", url=url, status=None, retryable=False) from exc

            status = int(resp.status_code)
            if status in RETRY_STATUSES or 500 <= status < 600:
                if retry and attempt < self.max_retries:
                    self._sleep_retry(host, attempt, resp, f"status={status}")
                    attempt += 1
                    continue
                stats["errors"] += 1
                raise self._error(f"HTTP {status}", url, resp, retryable=True)
            if status >= 400:
                stats["errors"] += 1
                raise self._error(f"HTTP {status}", url, resp, retryable=False)
            content = getattr(resp, "content", b"")
            if not content or not content.strip():
                return None
            try:
                return resp.json()
            except ValueError:
                stats["errors"] += 1
                raise self._error("invalid JSON", url, resp, retryable=False) from None

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
        delay = self._retry_after(resp)
        if delay is None:
            delay = self.backoff_delay(attempt)
        self.stats[host]["retries"] += 1
        log.warning("http_retry host=%s why=%s attempt=%d delay_s=%.2f", host, why, attempt + 1, delay)
        self.clock.sleep(delay)

    @staticmethod
    def _error(message: str, url: str, resp: Any, *, retryable: bool) -> HttpError:
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
                         retryable=retryable)

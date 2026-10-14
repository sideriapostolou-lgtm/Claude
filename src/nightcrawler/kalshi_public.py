"""Public, unauthenticated Kalshi GETs for the research recorder; nothing else.

This transport has one request method, ``get``, and it refuses every path that is not on
the public market-data allowlist of ``research/kalshi_edge_search/PROTOCOL.md`` section 2.
It sends no key or signature header, follows no redirect, caps the response size and shares
one request budget across every recorder lane: at most 2 request starts in any rolling second,
spaced at the configured target rate (1.5/s by default). After a 429 the whole recorder slows
by 25% for ten minutes and honours any Retry-After (clamped to 15 minutes); the calling lane also
backs off 2^n seconds (n = 429s in a row, at most 30 s). A reply that is not strict JSON (``NaN`` or
``Infinity`` included) is a failed request, never a record. The session it builds never consults
``~/.netrc`` and keeps no cookies. No order, portfolio or account client is imported.
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import requests

API = "https://api.elections.kalshi.com/trade-api/v2"
RATE_CEILING_PER_S = 2.0
MAX_BODY_BYTES = 16 * 1024 * 1024
RATE_CUT = 0.75
RATE_CUT_S = 600.0
MAX_RETRY_AFTER_S = 900.0  # a longer Retry-After is clamped (and recorded as a gap by the recorder)
_TICKER = r"[A-Z0-9][A-Z0-9._-]{0,99}"
# PROTOCOL.md section 2.1: the only paths this recorder may request.
PUBLIC_PATHS = tuple(re.compile(pattern) for pattern in (
    r"/events", r"/series", rf"/series/{_TICKER}", r"/series/fee_changes", r"/events/fee_changes",
    r"/markets", rf"/markets/{_TICKER}", r"/markets/orderbooks", rf"/markets/{_TICKER}/orderbook",
    r"/markets/trades", r"/historical/cutoff", r"/historical/markets", r"/historical/trades",
    r"/incentive_programs",
))
PUBLIC_PARAMS = frozenset({
    "limit", "cursor", "status", "series_ticker", "event_ticker", "ticker", "tickers", "min_ts", "max_ts",
    "min_close_ts", "max_close_ts", "with_nested_markets", "category", "show_historical", "depth", "type",
})
# Belt and braces: even an allowlisted pattern never reaches an account, order or quote route.
_FORBIDDEN = re.compile(r"portfolio|/orders?\b|order_group|/rfqs?\b|/quotes?\b|amend|decrease|/balance|"
                        r"/positions?\b|/fills?\b|/settlements\b|api_keys|/login|/logout", re.IGNORECASE)


def public_path(path: str) -> bool:
    """True only for the public market-data endpoints listed in PROTOCOL.md section 2.1."""
    return (isinstance(path, str) and _FORBIDDEN.search(path) is None
            and any(pattern.fullmatch(path) for pattern in PUBLIC_PATHS))


def public_ticker(value: Any) -> bool:
    """True for a ticker that may appear in a public path (``/series/{t}``, ``/markets/{t}``)."""
    return isinstance(value, str) and re.fullmatch(_TICKER, value) is not None


def _strict_constant(name: str) -> Any:
    raise ValueError(f"Non-standard JSON constant {name}")


def strict_json(raw: bytes) -> Any:
    """``json.loads`` that refuses ``NaN``, ``Infinity`` and ``-Infinity`` (they cannot be stored or replayed)."""
    return json.loads(raw, parse_constant=_strict_constant)


def _no_auth(request: Any) -> Any:
    """A session-level auth hook that adds nothing; its presence stops requests from reading ``~/.netrc``."""
    return request


class _NoCookies(requests.cookies.RequestsCookieJar):
    """A jar that never keeps a cookie (requests copies the session jar into each request, so a cookie policy
    alone would not stop one being sent)."""

    def set_cookie(self, cookie: http.cookiejar.Cookie, *args: Any, **kwargs: Any) -> None:
        return None


def public_session() -> requests.Session:
    """A requests session that sends no credentials: no netrc lookup and no cookies (proxies still apply)."""
    session = requests.Session()
    session.auth = _no_auth
    session.cookies = _NoCookies()
    return session


def _query(params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None) -> list[tuple[str, str]]:
    rows = list(params.items()) if isinstance(params, Mapping) else list(params or [])
    out: list[tuple[str, str]] = []
    for key, value in rows:
        if key not in PUBLIC_PARAMS:
            raise ValueError(f"Query parameter {key!r} is not on the public allowlist")
        if isinstance(value, bool):
            value = "true" if value else "false"
        if not isinstance(value, (str, int)):
            raise TypeError(f"Query parameter {key!r} must be a string or whole number")
        out.append((key, str(value)))
    return out


def retry_after_seconds(header: str | None, now: float) -> float | None:
    """Kalshi may send seconds or an HTTP date; an unreadable value is ignored, a huge one clamped to 15 min."""
    if not header:
        return None
    try:
        seconds = float(header)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(header).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            return None
    return min(MAX_RETRY_AFTER_S, max(0.0, seconds)) if math.isfinite(seconds) else None


class RateLimiter:
    """One shared budget: <= 2 starts in any rolling second and target-rate spacing between starts."""

    def __init__(self, target_per_s: float = 1.5, *, ceiling_per_s: float = RATE_CEILING_PER_S,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        if not (math.isfinite(ceiling_per_s) and 0 < ceiling_per_s <= RATE_CEILING_PER_S):
            raise ValueError("The public request ceiling is at most 2 per second")
        if not (math.isfinite(target_per_s) and 0 < target_per_s <= ceiling_per_s):
            raise ValueError("The target request rate must be positive and at most the ceiling")
        self.target_per_s, self.ceiling_per_s = target_per_s, ceiling_per_s
        self._clock, self._sleep = clock, sleep
        self._starts: deque[float] = deque()
        self._cut_until = -math.inf
        self._hold_until = -math.inf
        self._lock = threading.Lock()

    def rate(self, now: float | None = None) -> float:
        now = self._clock() if now is None else now
        return self.target_per_s * (RATE_CUT if now < self._cut_until else 1.0)

    def next_start(self, now: float) -> float:
        while self._starts and self._starts[0] <= now - 1.0:
            self._starts.popleft()
        earliest = self._hold_until
        if self._starts:
            earliest = max(earliest, self._starts[-1] + 1.0 / self.rate(now))
            if len(self._starts) >= math.floor(self.ceiling_per_s):
                earliest = max(earliest, self._starts[-math.floor(self.ceiling_per_s)] + 1.0)
        return earliest

    def delay(self) -> float:
        """Seconds until the next request may start (0 when it may start now)."""
        with self._lock:
            now = self._clock()
            return max(0.0, self.next_start(now) - now)

    def wait(self, stop: threading.Event | None = None) -> bool:
        """Block until a request may start; False when ``stop`` was set while waiting."""
        while True:
            with self._lock:
                now = self._clock()
                earliest = self.next_start(now)
                if now >= earliest:
                    self._starts.append(now)
                    return True
                delay = earliest - now
            if stop is not None and stop.is_set():
                return False
            self._sleep(min(delay, 0.5))

    def penalize(self, retry_after_s: float | None = None) -> None:
        """A 429 slows every lane by 25% for ten minutes; a Retry-After holds every lane."""
        with self._lock:
            now = self._clock()
            self._cut_until = now + RATE_CUT_S
            if retry_after_s is not None and retry_after_s > 0:
                self._hold_until = max(self._hold_until, now + min(retry_after_s, MAX_RETRY_AFTER_S))


@dataclass(frozen=True)
class Fetched:
    """One public GET as it happened: request start and receive time (host UTC clock), status, bytes and hash."""

    lane: str
    path: str
    query: tuple[tuple[str, str], ...]
    status: int | None
    error: str | None
    requested_at: float
    received_at: float
    rtt_ms: float
    nbytes: int
    sha256: str | None
    body: Any
    retry_after_s: float | None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None and isinstance(self.body, dict)

    @property
    def url(self) -> str:
        return API + self.path + ("?" + urlencode(list(self.query)) if self.query else "")

    def log_row(self) -> dict[str, Any]:
        return {"request_lane": self.lane, "path": self.path, "query": [list(pair) for pair in self.query],
                "status": self.status, "error": self.error, "requested_at": self.requested_at,
                "received_at": self.received_at, "rtt_ms": round(self.rtt_ms, 3), "bytes": self.nbytes,
                "sha256": self.sha256, "retry_after_s": self.retry_after_s}


class PublicKalshi:
    """GET-only public client. There is deliberately no other HTTP method on this class."""

    def __init__(self, limiter: RateLimiter, *, session: Any | None = None,
                 wall: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic,
                 timeout_s: float = 20.0, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.limiter = limiter
        self._session = session if session is not None else public_session()
        self._wall, self._mono = wall, mono
        self.timeout_s, self.max_bytes = timeout_s, max_bytes
        self.headers = {"Accept": "application/json", "User-Agent": "nightcrawler-kalshi-recorder/1 (public, read-only)"}

    def get(self, lane: str, path: str, params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
            stop: threading.Event | None = None) -> Fetched:
        if not public_path(path):
            raise ValueError(f"{path!r} is not a public Kalshi market-data path")
        query = tuple(_query(params))
        if not self.limiter.wait(stop):
            now = self._wall()
            return Fetched(lane, path, query, None, "stopped", now, now, 0.0, 0, None, None, None)
        requested_at, started = self._wall(), self._mono()
        status: int | None = None
        error: str | None = None
        body: Any = None
        digest: str | None = None
        retry: float | None = None
        size = 0
        try:
            response = self._session.get(API + path, params=list(query), headers=dict(self.headers),
                                         timeout=self.timeout_s, allow_redirects=False, stream=True)
            try:
                status = int(response.status_code)
                retry = retry_after_seconds(response.headers.get("Retry-After"), requested_at)
                chunks: list[bytes] = []
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ValueError("Public response exceeded the size cap")
                    chunks.append(chunk)
                raw = b"".join(chunks)
            finally:
                response.close()
            digest = hashlib.sha256(raw).hexdigest()
            if status == 200:
                try:
                    body = strict_json(raw)
                except (ValueError, RecursionError):  # includes NaN/Infinity, which no record may hold
                    error = "invalid_json"
                if error is None and not isinstance(body, dict):
                    error, body = "not_an_object", None
            elif 300 <= status < 400:
                error = "redirect_refused"
            else:
                error = f"http_{status}"
        except (requests.RequestException, OSError, ValueError) as exc:
            error = type(exc).__name__
        received_at = self._wall()
        rtt_ms = (self._mono() - started) * 1000.0
        if status == 429:
            self.limiter.penalize(retry)
        return Fetched(lane, path, query, status, error, requested_at, received_at, rtt_ms, size, digest, body, retry)

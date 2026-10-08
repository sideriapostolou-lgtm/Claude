"""pump.fun candle client: the FALLBACK 1m candle source for pump.fun coins (owner: runtime/data-source team).

GeckoTerminal is the primary candle source, but its free budget (~20 calls/min) is shared by
discovery-era callers, the candle fetch and the radar, and a shared Railway IP collects 429s. For
coins launched on pump.fun (bonding curve ``pumpfun`` or graduated to ``pumpswap``) pump.fun's own
swap API serves the same candles from a separate budget.

Endpoint (verified live 2026-10-08, no auth)::

    GET https://swap-api.pump.fun/v1/coins/{mint}/candles?interval=1m&limit=<1..1000>

-> a JSON list, ASCENDING, of ``{"timestamp": <ms>, "open", "high", "low", "close": <USD per
whole token as decimal strings>, "volume": <USD decimal string>}`` - the latest ``limit``
minutes THAT HAD TRADES (no-trade minutes are missing, so they are filled here with
:func:`nightcrawler.models.fill_gaps`; nothing is invented after the newest candle, which may still
be open). Prices and USD volume matched GeckoTerminal's PumpSwap pool candles within ~0.3 %
(GARY, 2026-10-08). ``limit > 1000`` -> HTTP 400; an unparsable mint -> HTTP 404; a valid
address pump.fun does not know -> ``[]``. The API also answers for NON-pump coins with only
their (tiny) pump venue trades, so callers must use it for pump.fun coins only
(:func:`is_pumpfun_coin`).

RATE LIMITS: the host sits behind Cloudflare. The engine gives it its own conservative bucket
(:data:`RATE_LIMIT`, ~12 requests/min). A 429 (or a Cloudflare 403/503 block page) starts a
COOL-DOWN of ``Retry-After`` seconds (default :data:`DEFAULT_COOLDOWN_S`, at most
:data:`MAX_COOLDOWN_S`; ``Retry-After: 0`` counts as the default) during which every call raises
:class:`PumpFunCoolingDown` without sending anything. Requests are never retried inline: the
engine runs every stage in one thread, so a fallback must never block a stop-loss.

Failures raise :class:`nightcrawler.http.HttpError` (or :class:`PumpFunCoolingDown`).
"""

from __future__ import annotations

import email.utils
from typing import Any

import requests

from nightcrawler.clock import Clock
from nightcrawler.http import HttpClient, HttpError, host_of
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import Candle, fill_gaps
from nightcrawler.sources._parse import to_float, to_int

__all__ = [
    "BASE_URL",
    "HOST",
    "RATE_LIMIT",
    "CANDLES_MAX_LIMIT",
    "DEFAULT_COOLDOWN_S",
    "MAX_COOLDOWN_S",
    "COOLDOWN_STATUSES",
    "PUMP_DEXES",
    "PumpFunClient",
    "PumpFunCoolingDown",
    "is_pumpfun_coin",
    "parse_candles",
]

log = get_logger(__name__)

BASE_URL = "https://swap-api.pump.fun"
HOST = host_of(BASE_URL)
#: (requests per second, burst) for :data:`HOST`: about 12 a minute (Cloudflare-limited); a burst of 3
#: covers one watch tick's candle fetches (MAX_CANDLE_FETCH_PER_TICK) without blocking the engine thread.
RATE_LIMIT: tuple[float, float] = (12 / 60, 3)
CANDLES_MAX_LIMIT = 1000
#: Cool-down after a 429 / Cloudflare block without a usable Retry-After (seconds).
DEFAULT_COOLDOWN_S = 60.0
#: Longest cool-down honoured from a Retry-After header (seconds).
MAX_COOLDOWN_S = 900.0
#: Statuses that mean "back off": rate limited, or a Cloudflare challenge/block page.
COOLDOWN_STATUSES = frozenset({403, 429, 503})
#: DexScreener-style dex ids of pump.fun venues (bonding curve, PumpSwap AMM).
PUMP_DEXES = frozenset({"pumpfun", "pumpswap"})
_LAUNCHPAD = "pump.fun"
_INTERVAL_S = 60


class PumpFunCoolingDown(Exception):
    """pump.fun asked us to back off; nothing was sent. ``seconds_left`` until requests resume."""

    def __init__(self, seconds_left: float) -> None:
        self.seconds_left = max(0.0, float(seconds_left))
        super().__init__(f"pump.fun cooling down after a rate limit: {self.seconds_left:.0f}s left")


def is_pumpfun_coin(*, launchpad: str | None = None, dex: str | None = None) -> bool:
    """True when pump.fun's candles describe the coin's MAIN market.

    ``dex`` (DexScreener-style id of the coin's current top pair, when known) decides: a pump.fun
    venue (``pumpfun`` curve or ``pumpswap``) -> True, any other venue -> False (pump.fun would only
    see a side pool). Without a dex the launchpad decides (Jupiter ``launchpad == "pump.fun"``).
    """
    if dex:
        return str(dex).lower() in PUMP_DEXES
    return str(launchpad or "").lower() == _LAUNCHPAD


def parse_candles(rows: Any) -> list[Candle]:
    """pump.fun candle rows -> :class:`Candle` list ASCENDING by ``ts`` (epoch SECONDS).

    Rows without a numeric timestamp/open/high/low/close are skipped; a missing volume is 0;
    duplicate timestamps keep the last row. A non-list body gives ``[]``.
    """
    if not isinstance(rows, list):
        return []
    by_ts: dict[int, Candle] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ms = to_int(row.get("timestamp"))
        ohlc = [to_float(row.get(k)) for k in ("open", "high", "low", "close")]
        if ms is None or any(x is None for x in ohlc):
            continue
        ts = ms // 1000
        by_ts[ts] = Candle(ts, *ohlc, to_float(row.get("volume"), 0.0))  # type: ignore[arg-type]
    return [by_ts[ts] for ts in sorted(by_ts)]


class PumpFunClient:
    """Candles from pump.fun's swap API over the shared :class:`HttpClient` (its session, rate
    buckets and stats; see the module docstring for the cool-down and why nothing is retried)."""

    def __init__(self, http: HttpClient, base_url: str = BASE_URL, clock: Clock | None = None) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.clock = clock if clock is not None else http.clock
        #: epoch seconds before which no request is sent (after a 429 / Cloudflare block)
        self.cooldown_until = 0.0

    def candles(self, mint: str, minutes: int, before: int | None = None) -> list[Candle]:
        """1m candles covering ``[end - minutes*60, end)`` ASCENDING, gap-filled (``end`` =
        ``before`` or now). One request of ``limit = min(1000, minutes + 1)`` traded minutes;
        the newest candle may still be open (callers use closed candles only)."""
        if minutes <= 0:
            return []
        end = int(before) if before is not None else int(self.clock.now())
        start = end - int(minutes) * _INTERVAL_S
        limit = min(CANDLES_MAX_LIMIT, int(minutes) + 1)
        rows = self._get(f"/v1/coins/{mint}/candles", {"interval": "1m", "limit": limit})
        candles = fill_gaps(parse_candles(rows), _INTERVAL_S)
        return [c for c in candles if start <= c.ts < end]

    # ------------------------------------------------------------------ transport
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        """One GET through the shared session and rate bucket; ``retry`` never (see module docstring)."""
        now = self.clock.now()
        if now < self.cooldown_until:
            raise PumpFunCoolingDown(self.cooldown_until - now)
        url = f"{self.base_url}{path}"
        host = host_of(url)
        stats = self.http.stats[host]
        stats["rate_wait_s"] += self.http.limiter.acquire(host)
        stats["requests"] += 1
        try:
            resp = self.http.session.request("GET", url, params=params, json=None,
                                             headers=dict(self.http.default_headers), timeout=self.http.timeout_s)
        except requests.RequestException as exc:
            stats["errors"] += 1
            retryable = isinstance(exc, (requests.ConnectionError, requests.Timeout))
            raise HttpError(type(exc).__name__, url=url, status=None, retryable=retryable) from exc
        status = int(resp.status_code)
        if status >= 400:
            stats["errors"] += 1
            if status in COOLDOWN_STATUSES:
                seconds = self._cooldown_s(getattr(resp, "headers", None) or {}, now)
                self.cooldown_until = now + seconds
                log.warning("pumpfun_backoff status=%s cooldown_s=%.0f", status, seconds)
            raise HttpError(f"HTTP {status}", url=url, status=status, body=_text(resp), payload=_json(resp),
                            retryable=status in COOLDOWN_STATUSES or status >= 500)
        content = getattr(resp, "content", b"")
        if not content or not content.strip():
            return None
        try:
            return resp.json()
        except ValueError:
            stats["errors"] += 1
            raise HttpError("invalid JSON", url=url, status=status, body=_text(resp)) from None

    @staticmethod
    def _cooldown_s(headers: Any, now: float) -> float:
        """Seconds to back off: ``Retry-After`` (seconds or HTTP date) clamped to
        ``[DEFAULT_COOLDOWN_S if 0/missing/garbled, MAX_COOLDOWN_S]``."""
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
        return resp.text
    except Exception:  # pragma: no cover - a response without text
        return None


def _json(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:
        return None

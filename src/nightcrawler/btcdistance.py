"""The distance filter for the Polymarket desk's Bitcoin bets (the owner's rule, 2026-10-12).

Real money buys a Bitcoin outcome only when Bitcoin sits far from the line for the time left:
``z = ln(S / K) / (sigma * sqrt(minutes left)) >= MIN_Z``. Here S is Coinbase's BTC-USD price now, K is the line
(the strike of an "above" market, or the window's opening price for an up-or-down market), and sigma is the realized
volatility per sqrt(minute): sqrt(mean of squared 1-minute log returns) over the last 60 complete minutes, the
estimator of research/lab8/tail.py. The desk only buys the long side (YES: "above", "Up"), so z measures how far
spot sits on the winning side.

``MIN_Z = 4`` comes from research/lab8/tail_2019_2025.md (Binance 1-minute closes 2019-01 .. 2026-05, outside every
lab split, trailing 60-minute vol). At z >= 4 with 60 minutes or less left, the close ended on the other side in
0.20-0.58 % of cases (95 % upper bound 0.63 %). That is under the 0.93 % break-even of a 99c contract after the US
fee, and well under the 2.8 % of a 97c one. Most losses of the price-only rule are close calls, which this skips.
Crashes like 2020-03-12 can still beat it.

It fails closed: a Bitcoin market it cannot parse, or a price feed it cannot read, means no real buy (the desk
practises it on paper instead). Coinbase is a public, keyless feed. The US markets settle on CF Benchmarks' BRTI,
of which Coinbase is a constituent; the small basis between them is far inside a 4-sigma margin."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import requests

MIN_Z = 4.0
VOL_MINUTES = 60
MIN_VOL_MINUTES = 50  # at least this many of the last 60 one-minute returns, or no verdict
CACHE_S = 20.0
CANDLES_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"

_ABOVE = re.compile(r"^cpc-btc-above-hr-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})z-(\d+(?:\.\d+)?)$")
_UPDOWN = re.compile(r"^cpc-btc-updown-(15m|1h)-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})z$")
_WINDOW_S = {"15m": 900.0, "1h": 3600.0}

#: A candle: (start unix s, open, close).
Candle = tuple[float, float, float]


def is_crypto(slug: str) -> bool:
    return slug.startswith("cpc-")


def parse(slug: str) -> dict[str, Any] | None:
    """``{"kind": "above", "strike": K}`` or ``{"kind": "updown", "start_ts": window open}``; None when unknown."""
    if m := _ABOVE.match(slug):
        return {"kind": "above", "strike": float(m.group(4))}
    if m := _UPDOWN.match(slug):
        day = datetime.strptime(m.group(2), "%Y-%m-%d").replace(tzinfo=UTC)
        start = day.timestamp() + int(m.group(3)) * 3600 + int(m.group(4)) * 60
        return {"kind": "updown", "start_ts": start, "window_s": _WINDOW_S[m.group(1)]}
    return None


def fetch_candles(timeout: float = 8.0) -> list[Candle]:
    """Coinbase's last 300 one-minute BTC-USD candles, oldest first (the newest one is still forming)."""
    r = requests.get(CANDLES_URL, params={"granularity": 60}, timeout=timeout,
                     headers={"User-Agent": "nightcrawler/1.0"})
    r.raise_for_status()
    rows = r.json()
    out = [(float(c[0]), float(c[3]), float(c[4])) for c in rows if isinstance(c, list) and len(c) >= 5]
    return sorted(out)


def sigma_per_minute(candles: Sequence[Candle], now: float) -> float | None:
    """sqrt(mean r^2) of the 1-minute log returns between consecutive complete minutes of the last
    :data:`VOL_MINUTES`; None under :data:`MIN_VOL_MINUTES` returns."""
    done = {int(t): c for t, _, c in candles if t + 60.0 <= now and c > 0}
    if not done:
        return None
    last = max(done)
    rets = []
    for k in range(VOL_MINUTES):
        t = last - 60 * k
        if t in done and t - 60 in done:
            rets.append(math.log(done[t] / done[t - 60]))
    if len(rets) < MIN_VOL_MINUTES:
        return None
    return math.sqrt(sum(r * r for r in rets) / len(rets))


def z_score(spot: float, line: float, sigma: float, minutes_left: float) -> float | None:
    if spot <= 0 or line <= 0 or sigma <= 0 or minutes_left <= 0:
        return None
    return math.log(spot / line) / (sigma * math.sqrt(minutes_left))


class Distance:
    """The check the desk runs before a real Bitcoin buy. ``check(slug, end_ts, now)`` returns
    ``(z, reason)``: reason None means far enough; ``too_close`` (z under :data:`MIN_Z`) or ``distance_unknown``
    (no parse, no feed, too few minutes, the window's open not in the feed) block real money."""

    def __init__(self, fetch: Callable[[], list[Candle]] | None = None, min_z: float = MIN_Z) -> None:
        self._fetch = fetch
        self.min_z = min_z
        self._cache: tuple[float, list[Candle]] | None = None

    def _candles(self, now: float) -> list[Candle] | None:
        if self._cache is not None and now - self._cache[0] < CACHE_S:
            return self._cache[1]
        try:
            candles = (self._fetch or fetch_candles)()
        except Exception:  # noqa: BLE001 - any feed failure fails closed: no verdict, no real buy
            return None
        self._cache = (now, candles)
        return candles

    def check(self, slug: str, end_ts: float, now: float | None = None) -> tuple[float | None, str | None]:
        now = time.time() if now is None else now
        spec = parse(slug)
        candles = self._candles(now) if spec else None
        if not spec or not candles:
            return None, "distance_unknown"
        spot = candles[-1][2]
        sigma = sigma_per_minute(candles, now)
        if spec["kind"] == "above":
            line = spec["strike"]
        else:
            opens = {int(t): o for t, o, _ in candles}
            line = opens.get(int(spec["start_ts"]))
        z = z_score(spot, line, sigma, (end_ts - now) / 60.0) if (sigma and line) else None
        if z is None:
            return None, "distance_unknown"
        return z, (None if z >= self.min_z else "too_close")

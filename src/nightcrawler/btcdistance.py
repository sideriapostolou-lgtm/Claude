"""The distance filter for the Polymarket desk's Bitcoin bets (the owner's rule, 2026-10-12).

Real money buys a Bitcoin outcome only when Bitcoin sits far from the line for the time left:
``z = ln(S / K) / (sigma * sqrt(minutes left))`` at least the bar for that price and time left (:data:`REQUIRED_Z`). Here S is Coinbase's BTC-USD price now, K is the line
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

MIN_Z = 4.0  # the first version's flat bar (2026-10-12 17:36 UTC); now the floor only for an unknown price
#: The bar since 2026-10-12 ~18:30 UTC, at the owner's "make it less far from the line but lock still so it can
#: keep filling": the smallest z whose miss rate over the last 365 days (research/lab8/year_backtest.py, Binance 1m
#: closes 2025-10-12 .. 2026-10-11, the worst case of a strike exactly at that z) is at most 75 % of the break-even
#: miss rate at that price after the US fee. Rows: the minutes-left bucket (<= 10, 20, 30, 45; up to 60 uses 45);
#: columns: the price paid (a price under 0.95 uses the 0.95 column, which asks for more distance than it needs).
REQUIRED_Z: dict[int, dict[float, float]] = {
    10: {0.95: 1.6, 0.96: 1.8, 0.97: 1.9, 0.98: 2.2, 0.99: 2.8},
    20: {0.95: 1.8, 0.96: 1.9, 0.97: 2.1, 0.98: 2.4, 0.99: 3.1},
    30: {0.95: 2.0, 0.96: 2.1, 0.97: 2.4, 0.98: 2.7, 0.99: 3.3},
    45: {0.95: 2.0, 0.96: 2.2, 0.97: 2.4, 0.98: 2.6, 0.99: 3.6},
}
MAX_MINUTES = 60.0


def required_z(price: float | None, minutes_left: float) -> float | None:
    """The bar for a buy at ``price`` with ``minutes_left`` to go (:data:`REQUIRED_Z`); None past
    :data:`MAX_MINUTES`. An unknown price gets :data:`MIN_Z`."""
    if minutes_left <= 0 or minutes_left > MAX_MINUTES:
        return None
    if price is None:
        return MIN_Z
    row = next(REQUIRED_Z[b] for b in (10, 20, 30, 45) if minutes_left <= b) if minutes_left <= 45 else REQUIRED_Z[45]
    cents = min(0.99, max(0.95, math.ceil(round(price * 100, 6)) / 100))
    return row[round(cents, 2)]
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

    def check(self, slug: str, end_ts: float, now: float | None = None,
              price: float | None = None) -> tuple[float | None, str | None]:
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
        minutes = (end_ts - now) / 60.0
        z = z_score(spot, line, sigma, minutes) if (sigma and line) else None
        bar = required_z(price, minutes) if self.min_z == MIN_Z else self.min_z
        if z is None or bar is None:
            return None, "distance_unknown"
        return z, (None if z >= bar else "too_close")

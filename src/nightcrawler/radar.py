"""Radar: watches big sells by creator / top holders / insiders (owner: O2).

``Radar.scan`` reads GeckoTerminal ``/pools/{pool}/trades`` with
``trade_volume_in_usd_greater_than=RADAR_MIN_TRADE_USD`` (one HTTP call), keeps
SELL trades inside the last ``RADAR_WINDOW_MIN`` minutes and attributes them by
``wallet`` (``tx_from_address``) against the SafetyReport's ``creator``,
``top_holders`` and ``insiders``.

FLAGGED (``flagged=True``, one reason each) when:

* creator sold anything >= ``RADAR_MIN_TRADE_USD`` in the window
  (``"creator sold $X"``);
* creator + top holders + insiders sold >= ``RADAR_INSIDER_SELL_USD`` in total
  (``"insiders sold $X"``);
* total big sells in the window >= ``RADAR_BIG_SELL_LIQ_PCT`` percent of
  ``liquidity_usd`` (when liquidity is known) (``"big sells $X = Y% of liquidity"``).

Rate budget: GeckoTerminal is the scarcest API (~20/min). The engine calls
``scan`` only (a) right before an entry and (b) for open positions every
``RADAR_INTERVAL_S``. ``scan`` caches its result per pool for 60 s.

Failure: on HTTP error returns a RadarSignal with ``error`` set and
``flagged=False`` (entry path rejects on error; exit path ignores it).
"""

from __future__ import annotations

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.models import RadarSignal, SafetyReport
from nightcrawler.sources import Sources

__all__ = ["Radar", "RADAR_CACHE_S"]

RADAR_CACHE_S = 60


class Radar:
    """Big-sell detector over GeckoTerminal trades."""

    def __init__(self, sources: Sources, settings: Settings, clock: Clock) -> None:
        self.sources = sources
        self.settings = settings
        self.clock = clock
        self._cache: dict[str, tuple[float, RadarSignal]] = {}

    def scan(self, mint: str, pool: str, safety: SafetyReport | None,
             liquidity_usd: float | None = None) -> RadarSignal:
        """Scan ``pool``'s recent big trades. Never raises.

        * ``window_min`` = ``RADAR_WINDOW_MIN``; trades with ``ts < now - window`` ignored.
        * ``big_sells_usd`` = sum of SELL ``volume_usd`` in window.
        * ``insider_sell_usd`` = part sold by creator/top holders/insiders
          (wallet sets from ``safety``; when ``safety`` is None only the
          liquidity rule can flag).
        * ``top_holder_sells`` lists each attributed sell
          ``{"wallet", "usd", "ts", "tx_hash", "role"}``.
        * ``trades_seen`` = number of trades returned by the API (any side).
        * ``checked_at`` = now; ``liquidity_usd`` echoed.
        """
        raise NotImplementedError

    @staticmethod
    def evaluate(trades: list[dict], now: float, window_min: float, creator: str | None,
                 top_holders: set[str], insiders: set[str], liquidity_usd: float | None,
                 min_trade_usd: float, insider_sell_usd: float, big_sell_liq_pct: float,
                 mint: str = "") -> RadarSignal:
        """PURE core of :meth:`scan` over normalized GT trades (see ``GeckoTerminalClient.trades``).

        Role precedence when a wallet is in several sets: creator > insider > top_holder.
        """
        raise NotImplementedError

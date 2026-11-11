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
``RADAR_INTERVAL_S``. ``scan`` caches the fetched trades per pool for 60 s and
re-evaluates them on every call (so the window, wallet sets and liquidity are
always the caller's current ones).

Failure: on HTTP error returns a RadarSignal with ``error`` set and
``flagged=False`` (entry path rejects on error; exit path ignores it). Errors
are not cached.
"""

from __future__ import annotations

from typing import Any, Collection

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import RadarSignal, SafetyReport
from nightcrawler.sources import Sources
from nightcrawler.sources._parse import to_float

__all__ = ["Radar", "RADAR_CACHE_S"]

log = get_logger(__name__)

RADAR_CACHE_S = 60
_ERROR_MAX_CHARS = 200


class Radar:
    """Big-sell detector over GeckoTerminal trades."""

    def __init__(self, sources: Sources, settings: Settings, clock: Clock) -> None:
        self.sources = sources
        self.settings = settings
        self.clock = clock
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}  # pool -> (expires_at, trades)

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
        s = self.settings
        now = self.clock.now()
        try:
            trades = self._trades(pool, now)
        except Exception as exc:  # fail closed at entry (caller rejects), ignored for exits
            log.warning("radar_unavailable mint=%s pool=%s error=%s: %s", mint, pool, type(exc).__name__, exc)
            return RadarSignal(mint=mint, window_min=s.radar_window_min, checked_at=now,
                               liquidity_usd=liquidity_usd,
                               error=f"{type(exc).__name__}: {exc}"[:_ERROR_MAX_CHARS])
        signal = self.evaluate(
            trades, now, s.radar_window_min,
            creator=safety.creator if safety else None,
            top_holders=set(safety.top_holders) if safety else set(),
            insiders=set(safety.insiders) if safety else set(),
            liquidity_usd=liquidity_usd,
            min_trade_usd=s.radar_min_trade_usd,
            insider_sell_usd=s.radar_insider_sell_usd,
            big_sell_liq_pct=s.radar_big_sell_liq_pct,
            mint=mint,
        )
        if signal.flagged:
            log.info("radar_flagged mint=%s reasons=%s", mint, "; ".join(signal.reasons))
        return signal

    def _trades(self, pool: str, now: float) -> list[dict[str, Any]]:
        """Big trades for ``pool`` (one GT call, reused for :data:`RADAR_CACHE_S`)."""
        hit = self._cache.get(pool)
        if hit is not None and now < hit[0]:
            return hit[1]
        trades = list(self.sources.gecko.trades(pool, min_usd=self.settings.radar_min_trade_usd) or [])
        for key in [k for k, (expires_at, _) in self._cache.items() if expires_at <= now]:
            del self._cache[key]
        self._cache[pool] = (now + RADAR_CACHE_S, trades)
        return trades

    @staticmethod
    def evaluate(trades: list[dict], now: float, window_min: float, creator: str | None,
                 top_holders: set[str], insiders: set[str], liquidity_usd: float | None,
                 min_trade_usd: float, insider_sell_usd: float, big_sell_liq_pct: float,
                 mint: str = "") -> RadarSignal:
        """PURE core of :meth:`scan` over normalized GT trades (see ``GeckoTerminalClient.trades``).

        Role precedence when a wallet is in several sets: creator > insider > top_holder.
        Only SELL trades with ``ts >= now - window_min*60`` and
        ``volume_usd >= min_trade_usd`` count. The liquidity rule needs a known,
        positive ``liquidity_usd``; thresholds only fire on a non-zero amount.
        """
        since = now - window_min * 60
        big_sells = insider_total = creator_total = 0.0
        attributed: list[dict[str, Any]] = []
        for trade in trades:
            usd = to_float(trade.get("volume_usd"))
            ts = to_float(trade.get("ts"))
            if trade.get("kind") != "sell" or usd is None or ts is None or ts < since or usd < min_trade_usd:
                continue
            big_sells += usd
            wallet = trade.get("wallet")
            role = _role(wallet, creator, insiders, top_holders)
            if role is None:
                continue
            insider_total += usd
            if role == "creator":
                creator_total += usd
            attributed.append({"wallet": wallet, "usd": usd, "ts": ts, "tx_hash": trade.get("tx_hash"),
                               "role": role})

        reasons: list[str] = []
        if creator_total > 0:
            reasons.append(f"creator sold ${creator_total:,.0f}")
        if insider_total > 0 and insider_total >= insider_sell_usd:
            reasons.append(f"insiders sold ${insider_total:,.0f}")
        if big_sells > 0 and liquidity_usd is not None and liquidity_usd > 0:
            share = big_sells / liquidity_usd * 100
            if share >= big_sell_liq_pct:
                reasons.append(f"big sells ${big_sells:,.0f} = {share:.1f}% of liquidity")
        return RadarSignal(
            mint=mint,
            window_min=window_min,
            big_sells_usd=big_sells,
            insider_sell_usd=insider_total,
            creator_sold=creator_total > 0,
            top_holder_sells=attributed,
            flagged=bool(reasons),
            reasons=reasons,
            checked_at=now,
            trades_seen=len(trades),
            liquidity_usd=liquidity_usd,
        )


def _role(wallet: Any, creator: str | None, insiders: Collection[str], top_holders: Collection[str]) -> str | None:
    """``creator`` > ``insider`` > ``top_holder`` > None."""
    if not wallet:
        return None
    if creator and wallet == creator:
        return "creator"
    if wallet in insiders:
        return "insider"
    if wallet in top_holders:
        return "top_holder"
    return None

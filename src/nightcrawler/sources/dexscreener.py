"""DexScreener client (owner: O1). No auth; CDN-cached 30-60 s; budget 60 req/min.

Endpoints (base ``https://api.dexscreener.com``):

* ``/token-profiles/latest/v1`` and ``/token-boosts/latest/v1`` - lists that mix
  chains; keep only ``chainId == "solana"``. Used as a *paid promotion* flag.
* ``/latest/dex/search?q=`` -> ``{"pairs": [...]}``.
* ``/tokens/v1/solana/{m1,m2,...}`` - up to **30** comma-separated mints per
  call, returns a list with (at most) one top pair per token.
* ``/token-pairs/v1/solana/{mint}`` - single mint only, list of pairs.
* ``/latest/dex/pairs/solana/{pair}`` -> ``{"pairs": [...], "pair": {...}}``.

Pair fields used: ``dexId`` (``pumpfun`` = bonding curve, ``pumpswap``,
``raydium``, ``meteora``, ``meteoradbc``, ``orca``), ``pairAddress``,
``baseToken{address,name,symbol}``, ``priceUsd`` (string, may be missing),
``txns.{m5,h1,h6,h24}.{buys,sells}``, ``volume.*``, ``priceChange.*``
(percent), ``liquidity.usd`` (MISSING for pumpfun curve pairs), ``fdv``,
``marketCap``, ``pairCreatedAt`` (ms), ``info.{websites,socials}``,
``boosts.active``.

All methods raise :class:`nightcrawler.http.HttpError` when the request fails
after retries; parsing never raises on missing fields.
"""

from __future__ import annotations

from typing import Any, Sequence

from nightcrawler.http import HttpClient
from nightcrawler.models import MarketSnapshot

__all__ = ["BASE_URL", "MAX_BATCH", "DexScreenerClient", "pair_to_snapshot", "pair_socials"]

BASE_URL = "https://api.dexscreener.com"
MAX_BATCH = 30


class DexScreenerClient:
    """Thin typed client over :class:`HttpClient`."""

    def __init__(self, http: HttpClient, base_url: str = BASE_URL) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    def token_profiles_latest(self) -> list[dict[str, Any]]:
        """Latest token profiles, Solana only.

        Returns ``[{"mint": str, "url": str|None, "description": str|None,
        "links": [{"type"?, "label"?, "url"}]}]`` in API order. Non-solana
        items and items without ``tokenAddress`` are dropped.
        """
        raise NotImplementedError

    def token_boosts_latest(self) -> list[dict[str, Any]]:
        """Latest paid boosts, Solana only.

        Returns ``[{"mint": str, "amount": float|None, "total_amount": float|None,
        "url": str|None}]``. The crawler marks these mints ``paid_promo=True``.
        """
        raise NotImplementedError

    def search(self, query: str) -> list[dict[str, Any]]:
        """``/latest/dex/search?q=`` -> raw pair dicts with ``chainId == "solana"`` only."""
        raise NotImplementedError

    def tokens(self, mints: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Top pair per mint via ``/tokens/v1/solana/{csv}``.

        Splits ``mints`` into batches of :data:`MAX_BATCH` (30) - one HTTP call
        per batch. Returns ``{mint: raw_pair}`` keyed by
        ``pair["baseToken"]["address"]``; mints DexScreener does not know are
        absent. If one token has several pairs in the response, keep the one
        with the highest ``liquidity.usd`` (missing liquidity counts as 0) and,
        as a tie-break, the highest ``volume.h24``. Empty input -> ``{}`` with
        no HTTP call.
        """
        raise NotImplementedError

    def snapshots(self, mints: Sequence[str], now: float) -> dict[str, MarketSnapshot]:
        """``tokens(mints)`` converted with :func:`pair_to_snapshot` (``ts=now``); unparseable pairs skipped."""
        raise NotImplementedError

    def token_pairs(self, mint: str) -> list[dict[str, Any]]:
        """All Solana pairs for ONE mint (``/token-pairs/v1/solana/{mint}``), raw dicts."""
        raise NotImplementedError

    def pair(self, pair_address: str) -> dict[str, Any] | None:
        """One pair by address (``/latest/dex/pairs/solana/{pair}``); ``None`` if not found."""
        raise NotImplementedError


def pair_to_snapshot(pair: dict[str, Any], ts: float) -> MarketSnapshot | None:
    """Convert a raw DexScreener pair to a :class:`MarketSnapshot`.

    * ``mint`` = ``baseToken.address`` (return ``None`` if missing).
    * ``price_usd`` = float(``priceUsd``) or None; ``mcap_usd`` = ``marketCap``
      falling back to ``fdv``; ``liquidity_usd`` = ``liquidity.usd`` or None
      (pumpfun curve pairs have none).
    * counts from ``txns.m5/h1``; volumes from ``volume.m5/h1`` (0.0 if missing);
      ``price_change_m5/h1`` from ``priceChange`` (percent, None if missing).
    * ``pool`` = ``pairAddress``, ``dex`` = ``dexId``, ``fdv_usd`` = ``fdv``,
      ``pair_created_at`` = ``pairCreatedAt / 1000`` (epoch seconds).
    """
    raise NotImplementedError


def pair_socials(pair: dict[str, Any]) -> dict[str, str]:
    """``info.websites`` / ``info.socials`` -> ``{"website": url, "twitter": url, "telegram": url, ...}``.

    First URL per type wins; types lower-cased (``x`` -> ``twitter``).
    """
    raise NotImplementedError

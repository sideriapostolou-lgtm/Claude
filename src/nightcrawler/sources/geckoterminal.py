"""GeckoTerminal client (owner: O1). No auth; budget ~20 calls/min (shared IP gets 429s).

Base ``https://api.geckoterminal.com/api/v2``; send header
``Accept: application/json;version=20230203`` on every call (see :data:`HEADERS`).
**All numerics arrive as strings** - parse with ``sources._parse``. Ids look
like ``solana_<address>`` (use ``_parse.strip_gt_id``).

Endpoints used:

* ``/networks/solana/new_pools?include=base_token,quote_token,dex&page=N``
  (page 1..10, 20 pools/page, newest first; includes pump-fun and
  meteora-dbc **curve** pools whose ``reserve_in_usd`` is ``"0.0"``/null).
* ``/networks/solana/trending_pools?include=base_token&duration=1h&page=N``
* ``/networks/solana/pools/{pool}?include=base_token,quote_token,dex``
* ``/networks/solana/pools/{pool}/trades[?trade_volume_in_usd_greater_than=X]``
  (<= 300 trades, last 24 h, newest first).
* ``/networks/solana/pools/{pool}/ohlcv/minute?aggregate=1|5|15&limit<=1000
  &before_timestamp=T&currency=usd&token=base&include_empty_intervals=true``
  -> ``data.attributes.ohlcv_list`` rows ``[ts, o, h, l, c, vol_usd]``
  **newest first**; ``before_timestamp`` is EXCLUSIVE; data window 180 days.
* ``/networks/solana/tokens/{mint}?include=top_pools``
* ``/networks/solana/tokens/{mint}/info`` (holder stats lag 10-100 min and are
  null on fresh tokens).

HTTP failures raise :class:`nightcrawler.http.HttpError` (404 included); the
methods documented "-> None if not found" return ``None`` on 404 instead.
"""

from __future__ import annotations

from typing import Any, Literal

from nightcrawler.clock import Clock
from nightcrawler.http import HttpClient
from nightcrawler.models import Candle, TokenCandidate

__all__ = [
    "BASE_URL",
    "HEADERS",
    "NETWORK",
    "OHLCV_MAX_LIMIT",
    "GeckoTerminalClient",
    "normalize_pool",
    "pool_to_candidate",
]

BASE_URL = "https://api.geckoterminal.com/api/v2"
HEADERS = {"Accept": "application/json;version=20230203"}
NETWORK = "solana"
OHLCV_MAX_LIMIT = 1000


class GeckoTerminalClient:
    """Thin typed client. ``clock`` is used for ``ohlcv`` end time when ``before`` is None."""

    def __init__(self, http: HttpClient, base_url: str = BASE_URL, clock: Clock | None = None) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.clock = clock if clock is not None else http.clock

    def new_pools(self, page: int = 1) -> list[dict[str, Any]]:
        """Newest Solana pools (``page`` 1..10) normalized with :func:`normalize_pool`.

        Raises ``ValueError`` for page outside 1..10.
        """
        raise NotImplementedError

    def trending_pools(self, page: int = 1, duration: Literal["5m", "1h", "6h", "24h"] = "1h") -> list[dict[str, Any]]:
        """Trending Solana pools normalized with :func:`normalize_pool`."""
        raise NotImplementedError

    def pool(self, address: str) -> dict[str, Any] | None:
        """One pool normalized with :func:`normalize_pool`; ``None`` on 404."""
        raise NotImplementedError

    def trades(self, pool: str, min_usd: float | None = None) -> list[dict[str, Any]]:
        """Recent trades (last 24 h, <= 300, NEWEST FIRST as returned).

        ``min_usd`` -> ``trade_volume_in_usd_greater_than``. Each item:
        ``{"ts": float epoch s (block_timestamp), "tx_hash": str,
        "wallet": str (tx_from_address), "kind": "buy"|"sell",
        "volume_usd": float, "price_usd": float|None (USD per whole BASE token:
        price_to_in_usd for buys, price_from_in_usd for sells),
        "token_amount": float|None (whole base tokens: to_token_amount for buys,
        from_token_amount for sells), "block_number": int|None}``.
        Items with unparseable ``ts`` or ``kind`` are skipped.
        """
        raise NotImplementedError

    def ohlcv_page(self, pool: str, aggregate: int = 1, limit: int = OHLCV_MAX_LIMIT,
                   before: int | None = None) -> list[Candle]:
        """ONE ohlcv/minute request; returns candles sorted ASCENDING by ts.

        Always sends ``currency=usd&token=base&include_empty_intervals=true``.
        ``before`` -> ``before_timestamp`` (exclusive, epoch seconds).
        ``aggregate`` must be 1, 5 or 15; ``limit`` 1..1000 (ValueError otherwise).
        Rows with non-numeric values are skipped; duplicate ts keep the last seen.
        """
        raise NotImplementedError

    def ohlcv(self, pool: str, minutes: int, aggregate: int = 1, before: int | None = None) -> list[Candle]:
        """Candles covering ``[end - minutes*60, end)`` ASCENDING, paginating backwards.

        ``end`` = ``before`` or ``int(clock.now())``. Requests pages of up to
        1000 rows, each with ``before_timestamp`` = oldest ts seen so far,
        until the window is covered or a page comes back empty/short (pool
        creation reached). Result is de-duplicated by ts and trimmed to the
        window. The newest candle may still be OPEN (in progress) - callers
        (strategy) must ignore candles with ``ts + 60*aggregate > now``.
        """
        raise NotImplementedError

    def token(self, mint: str) -> dict[str, Any] | None:
        """``/tokens/{mint}?include=top_pools`` normalized; ``None`` on 404.

        Returns ``{"mint", "name", "symbol", "decimals": int|None,
        "price_usd", "fdv_usd", "mcap_usd", "total_supply": float|None (whole tokens,
        from normalized_total_supply), "reserve_usd", "volume_h24_usd",
        "launchpad": {"graduation_percentage": float|None, "completed": bool|None,
        "completed_at": float|None, "migrated_pool": str|None} | None,
        "top_pools": [pool addresses]}``. Numbers are floats or None.
        """
        raise NotImplementedError

    def token_info(self, mint: str) -> dict[str, Any] | None:
        """``/tokens/{mint}/info`` normalized; ``None`` on 404.

        Returns ``{"mint", "holders_count": int|None, "top10_pct": float|None
        (percent, from holders.distribution_percentage.top_10),
        "holders_updated_at": float|None, "mint_authority_enabled": bool|None
        ("no" -> False, "yes" -> True), "freeze_authority_enabled": bool|None,
        "developer": str|None, "developer_holding_pct": float|None (percent),
        "gt_score": float|None, "websites": [str], "twitter": str|None,
        "telegram": str|None, "is_honeypot": str|None, "launchpad": {...} | None}``.
        """
        raise NotImplementedError


def normalize_pool(item: dict[str, Any], included: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Flatten one GT pool resource (``type == "pool"``).

    Returns ``{"pool": address, "name": str, "dex": str|None (relationships.dex id,
    e.g. "pump-fun", "pumpswap", "meteora-dbc", "raydium"),
    "base_mint": str|None, "quote_mint": str|None, "base_symbol": str|None,
    "base_name": str|None, "base_decimals": int|None (from ``included`` tokens when present),
    "created_at": float|None (pool_created_at), "price_usd": float|None
    (base_token_price_usd), "fdv_usd", "mcap_usd" (market_cap_usd; often null),
    "reserve_usd": float|None (None when null OR 0 - curve pools report 0),
    "volume_usd": {"m5","m15","m30","h1","h6","h24": float|None},
    "txns": {window: {"buys","sells","buyers","sellers": int|None}},
    "price_change_pct": {window: float|None}}``. Missing pieces -> None.
    """
    raise NotImplementedError


def pool_to_candidate(pool: dict[str, Any], now: float, source: str = "gt_new_pools") -> TokenCandidate | None:
    """Normalized pool dict -> :class:`TokenCandidate` (``None`` if no base mint or base is SOL).

    ``created_at`` = pool created_at, ``age_min`` = (now - created_at)/60,
    ``liquidity_usd`` = reserve_usd, ``mcap_usd`` = mcap_usd or fdv_usd,
    ``dex`` mapped to DexScreener ids (``pump-fun`` -> ``pumpfun``,
    ``meteora-dbc`` -> ``meteoradbc``, others unchanged with ``-`` removed),
    ``graduated`` = False for curve dexes (pump-fun, meteora-dbc), else None,
    ``sources = [source]``, ``discovered_at = now``, ``raw = {"gt_pool": pool["pool"]}``.
    """
    raise NotImplementedError

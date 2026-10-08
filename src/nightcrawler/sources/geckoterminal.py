"""GeckoTerminal client (owner: O1). No auth; budget ~20 calls/min (shared IP gets 429s).

Base ``https://api.geckoterminal.com/api/v2``; send header
``Accept: application/json;version=20230203`` on every call (see :data:`HEADERS`).
**All numerics arrive as strings** - parse with ``sources._parse``. Ids look
like ``solana_<address>`` (use ``_parse.strip_gt_id``).

Endpoints used:

* ``/networks/solana/new_pools?include=base_token,quote_token,dex&page=N``
  (page 1..10, 20 pools/page, newest first; includes pump-fun and
  meteora-dbc **curve** pools whose ``reserve_in_usd`` is ``"0.0"``/null).
* ``/networks/solana/trending_pools?include=base_token,quote_token,dex&duration=1h&page=N``
* ``/networks/solana/pools/{pool}?include=base_token,quote_token,dex``
* ``/networks/solana/pools/{pool}/trades[?trade_volume_in_usd_greater_than=X]``
  (<= 300 trades, last 24 h, newest first).
* ``/networks/solana/pools/{pool}/ohlcv/minute?aggregate=1|5|15&limit<=1000
  &before_timestamp=T&currency=usd&token=base&include_empty_intervals=true``
  -> ``data.attributes.ohlcv_list`` rows ``[ts, o, h, l, c, vol_usd]``
  **newest first**; ``before_timestamp`` is EXCLUSIVE; data window 180 days.
  Verified live 2026-10-08: empty intervals are filled only BETWEEN real
  trades, so a page ends at the last traded interval before
  ``before_timestamp`` and the no-trade intervals at a page boundary are
  missing - :meth:`GeckoTerminalClient.ohlcv` fills them.
* ``/networks/solana/tokens/{mint}?include=top_pools``
* ``/networks/solana/tokens/{mint}/info`` (holder stats lag 10-100 min and are
  null on fresh tokens).

HTTP failures raise :class:`nightcrawler.http.HttpError` (404 included); the
methods documented "-> None if not found" return ``None`` on 404 instead.
"""

from __future__ import annotations

from typing import Any, Literal

from nightcrawler.clock import Clock
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.models import SOL_MINT, Candle, TokenCandidate
from nightcrawler.sources._parse import (
    first_not_none,
    get_path,
    parse_ts,
    strip_gt_id,
    to_bool,
    to_float,
    to_int,
)

__all__ = [
    "BASE_URL",
    "HEADERS",
    "NETWORK",
    "OHLCV_MAX_LIMIT",
    "OHLCV_AGGREGATES",
    "MAX_NEW_POOLS_PAGE",
    "GeckoTerminalClient",
    "normalize_pool",
    "pool_to_candidate",
]

BASE_URL = "https://api.geckoterminal.com/api/v2"
HEADERS = {"Accept": "application/json;version=20230203"}
NETWORK = "solana"
OHLCV_MAX_LIMIT = 1000
OHLCV_AGGREGATES = (1, 5, 15)
MAX_NEW_POOLS_PAGE = 10
TRENDING_DURATIONS = ("5m", "1h", "6h", "24h")
POOL_INCLUDE = "base_token,quote_token,dex"
#: Stats windows GeckoTerminal reports on pools.
WINDOWS = ("m5", "m15", "m30", "h1", "h6", "h24")
_TXN_FIELDS = ("buys", "sells", "buyers", "sellers")
#: GeckoTerminal dex ids of bonding-curve launchpads (no AMM liquidity yet).
CURVE_DEXES = frozenset({"pump-fun", "meteora-dbc"})
#: GeckoTerminal dex id -> DexScreener-style id where they differ beyond dashes.
_DEX_ALIASES = {"pump-fun": "pumpfun", "meteora-dbc": "meteoradbc"}


class GeckoTerminalClient:
    """Thin typed client. ``clock`` is used for ``ohlcv`` end time when ``before`` is None."""

    def __init__(self, http: HttpClient, base_url: str = BASE_URL, clock: Clock | None = None) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.clock = clock if clock is not None else http.clock

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.get_json(f"{self.base_url}/networks/{NETWORK}{path}", params=params, headers=HEADERS)

    def _get_or_none(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Like :meth:`_get` but ``None`` on HTTP 404."""
        try:
            return self._get(path, params)
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise

    def new_pools(self, page: int = 1) -> list[dict[str, Any]]:
        """Newest Solana pools (``page`` 1..10) normalized with :func:`normalize_pool`.

        Raises ``ValueError`` for page outside 1..10.
        """
        if not 1 <= page <= MAX_NEW_POOLS_PAGE:
            raise ValueError(f"page must be 1..{MAX_NEW_POOLS_PAGE}, got {page}")
        return _pools(self._get("/new_pools", {"include": POOL_INCLUDE, "page": page}))

    def trending_pools(self, page: int = 1, duration: Literal["5m", "1h", "6h", "24h"] = "1h") -> list[dict[str, Any]]:
        """Trending Solana pools normalized with :func:`normalize_pool`.

        Raises ``ValueError`` for an unknown ``duration``.
        """
        if duration not in TRENDING_DURATIONS:
            raise ValueError(f"duration must be one of {TRENDING_DURATIONS}, got {duration!r}")
        return _pools(self._get("/trending_pools", {"include": POOL_INCLUDE, "duration": duration, "page": page}))

    def pool(self, address: str) -> dict[str, Any] | None:
        """One pool normalized with :func:`normalize_pool`; ``None`` on 404."""
        resp = self._get_or_none(f"/pools/{address}", {"include": POOL_INCLUDE})
        data = get_path(resp, "data")
        if not isinstance(data, dict):
            return None
        return normalize_pool(data, get_path(resp, "included"))

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
        params = {"trade_volume_in_usd_greater_than": _plain_number(min_usd)} if min_usd is not None else None
        resp = self._get(f"/pools/{pool}/trades", params)
        trades = (_trade(item) for item in _dicts(get_path(resp, "data")))
        return [t for t in trades if t is not None]

    def ohlcv_page(self, pool: str, aggregate: int = 1, limit: int = OHLCV_MAX_LIMIT,
                   before: int | None = None) -> list[Candle]:
        """ONE ohlcv/minute request; returns candles sorted ASCENDING by ts.

        Always sends ``currency=usd&token=base&include_empty_intervals=true``.
        ``before`` -> ``before_timestamp`` (exclusive, epoch seconds).
        ``aggregate`` must be 1, 5 or 15; ``limit`` 1..1000 (ValueError otherwise).
        Rows with non-numeric values are skipped; duplicate ts keep the last seen.
        """
        if aggregate not in OHLCV_AGGREGATES:
            raise ValueError(f"aggregate must be one of {OHLCV_AGGREGATES}, got {aggregate}")
        if not 1 <= limit <= OHLCV_MAX_LIMIT:
            raise ValueError(f"limit must be 1..{OHLCV_MAX_LIMIT}, got {limit}")
        params: dict[str, Any] = {"aggregate": aggregate, "limit": limit, "currency": "usd", "token": "base",
                                  "include_empty_intervals": "true"}
        if before is not None:
            params["before_timestamp"] = int(before)
        resp = self._get(f"/pools/{pool}/ohlcv/minute", params)
        by_ts: dict[int, Candle] = {}
        for row in get_path(resp, "data.attributes.ohlcv_list", []):
            candle = _candle(row)
            if candle is not None:
                by_ts[candle.ts] = candle
        return [by_ts[ts] for ts in sorted(by_ts)]

    def ohlcv(self, pool: str, minutes: int, aggregate: int = 1, before: int | None = None) -> list[Candle]:
        """Candles covering ``[end - minutes*60, end)`` ASCENDING, paginating backwards.

        ``end`` = ``before`` or ``int(clock.now())``. Requests pages of up to
        1000 rows, each with ``before_timestamp`` = oldest ts seen so far,
        until the window is covered or a page comes back empty/short (pool
        creation reached). Result is de-duplicated by ts and trimmed to the
        window. The newest candle may still be OPEN (in progress) - callers
        (strategy) must ignore candles with ``ts + 60*aggregate > now``.

        Missing intervals BETWEEN two returned candles (no-trade intervals GT
        drops at page boundaries) are filled like ``include_empty_intervals``
        does: flat candles at the previous close with zero volume. Intervals
        after the newest candle are never invented (GT indexing lags, so "no
        candle yet" does not prove "no trades").
        """
        if minutes <= 0:
            return []
        end = int(before) if before is not None else int(self.clock.now())
        start = end - int(minutes) * 60
        interval_s = 60 * aggregate
        by_ts: dict[int, Candle] = {}
        cursor = end
        while cursor > start:
            limit = min(OHLCV_MAX_LIMIT, -(-(cursor - start) // interval_s) + 1)
            page = self.ohlcv_page(pool, aggregate=aggregate, limit=limit, before=cursor)
            for candle in page:
                by_ts[candle.ts] = candle
            if len(page) < limit or page[0].ts >= cursor:  # pool creation reached / no progress
                break
            cursor = page[0].ts
        candles = _fill_gaps([by_ts[ts] for ts in sorted(by_ts)], interval_s)
        return [c for c in candles if start <= c.ts < end]

    def token(self, mint: str) -> dict[str, Any] | None:
        """``/tokens/{mint}?include=top_pools`` normalized; ``None`` on 404.

        Returns ``{"mint", "name", "symbol", "decimals": int|None,
        "price_usd", "fdv_usd", "mcap_usd", "total_supply": float|None (whole tokens,
        from normalized_total_supply), "reserve_usd", "volume_h24_usd",
        "launchpad": {"graduation_percentage": float|None, "completed": bool|None,
        "completed_at": float|None, "migrated_pool": str|None} | None,
        "top_pools": [pool addresses]}``. Numbers are floats or None.
        """
        resp = self._get_or_none(f"/tokens/{mint}", {"include": "top_pools"})
        data = get_path(resp, "data")
        if not isinstance(data, dict):
            return None
        attrs = data.get("attributes") or {}
        top_pools = (strip_gt_id(ref.get("id")) for ref in _dicts(get_path(data, "relationships.top_pools.data")))
        return {
            "mint": attrs.get("address") or strip_gt_id(data.get("id")) or mint,
            "name": attrs.get("name"),
            "symbol": attrs.get("symbol"),
            "decimals": to_int(attrs.get("decimals")),
            "price_usd": to_float(attrs.get("price_usd")),
            "fdv_usd": to_float(attrs.get("fdv_usd")),
            "mcap_usd": to_float(attrs.get("market_cap_usd")),
            "total_supply": to_float(attrs.get("normalized_total_supply")),
            "reserve_usd": to_float(attrs.get("total_reserve_in_usd")),
            "volume_h24_usd": to_float(get_path(attrs, "volume_usd.h24")),
            "launchpad": _launchpad(attrs.get("launchpad_details")),
            "top_pools": [p for p in top_pools if p],
        }

    def token_info(self, mint: str) -> dict[str, Any] | None:
        """``/tokens/{mint}/info`` normalized; ``None`` on 404.

        Returns ``{"mint", "holders_count": int|None, "top10_pct": float|None
        (percent, from holders.distribution_percentage.top_10),
        "holders_updated_at": float|None, "mint_authority_enabled": bool|None
        ("no" -> False, "yes" -> True), "freeze_authority_enabled": bool|None,
        "developer": str|None, "developer_holding_pct": float|None (percent),
        "gt_score": float|None, "websites": [str], "twitter": str|None,
        "telegram": str|None, "is_honeypot": str|None, "launchpad": {...} | None}``.
        ``twitter`` / ``telegram`` are the handles as GeckoTerminal reports them.
        """
        resp = self._get_or_none(f"/tokens/{mint}/info")
        data = get_path(resp, "data")
        if not isinstance(data, dict):
            return None
        attrs = data.get("attributes") or {}
        return {
            "mint": attrs.get("address") or strip_gt_id(data.get("id")) or mint,
            "holders_count": to_int(get_path(attrs, "holders.count")),
            "top10_pct": to_float(get_path(attrs, "holders.distribution_percentage.top_10")),
            "holders_updated_at": parse_ts(get_path(attrs, "holders.last_updated")),
            "mint_authority_enabled": to_bool(attrs.get("mint_authority")),
            "freeze_authority_enabled": to_bool(attrs.get("freeze_authority")),
            "developer": attrs.get("developer_address") or None,
            "developer_holding_pct": to_float(attrs.get("developer_holding_percentage")),
            "gt_score": to_float(attrs.get("gt_score")),
            "websites": _websites(attrs.get("websites")),
            "twitter": attrs.get("twitter_handle") or None,
            "telegram": attrs.get("telegram_handle") or None,
            "is_honeypot": attrs.get("is_honeypot") or None,
            "launchpad": _launchpad(attrs.get("launchpad_details")),
        }


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
    ``base_symbol`` falls back to the part of the pool ``name`` before ``" / "``
    when the base token is not in ``included``.
    """
    attrs = item.get("attributes") or {}
    rel = item.get("relationships") or {}
    base_id = get_path(rel, "base_token.data.id")
    base = _included_tokens(included).get(base_id, {})
    name = attrs.get("name") or ""
    name_symbol = name.split(" / ")[0].strip() if " / " in name else None
    return {
        "pool": attrs.get("address") or strip_gt_id(item.get("id")),
        "name": name,
        "dex": get_path(rel, "dex.data.id"),
        "base_mint": strip_gt_id(base_id),
        "quote_mint": strip_gt_id(get_path(rel, "quote_token.data.id")),
        "base_symbol": base.get("symbol") or name_symbol,
        "base_name": base.get("name") or None,
        "base_decimals": to_int(base.get("decimals")),
        "created_at": parse_ts(attrs.get("pool_created_at")),
        "price_usd": to_float(attrs.get("base_token_price_usd")),
        "fdv_usd": to_float(attrs.get("fdv_usd")),
        "mcap_usd": to_float(attrs.get("market_cap_usd")),
        "reserve_usd": to_float(attrs.get("reserve_in_usd")) or None,
        "volume_usd": {w: to_float(get_path(attrs, ("volume_usd", w))) for w in WINDOWS},
        "txns": {w: {k: to_int(get_path(attrs, ("transactions", w, k))) for k in _TXN_FIELDS} for w in WINDOWS},
        "price_change_pct": {w: to_float(get_path(attrs, ("price_change_percentage", w))) for w in WINDOWS},
    }


def pool_to_candidate(pool: dict[str, Any], now: float, source: str = "gt_new_pools") -> TokenCandidate | None:
    """Normalized pool dict -> :class:`TokenCandidate` (``None`` if no base mint or base is SOL).

    ``created_at`` = pool created_at, ``age_min`` = (now - created_at)/60,
    ``liquidity_usd`` = reserve_usd, ``mcap_usd`` = mcap_usd or fdv_usd,
    ``dex`` mapped to DexScreener ids (``pump-fun`` -> ``pumpfun``,
    ``meteora-dbc`` -> ``meteoradbc``, others unchanged with ``-`` removed),
    ``graduated`` = False for curve dexes (pump-fun, meteora-dbc), else None,
    ``sources = [source]``, ``discovered_at = now``, ``raw = {"gt_pool": pool["pool"]}``.
    """
    mint = pool.get("base_mint")
    if not mint or mint == SOL_MINT:
        return None
    created_at = pool.get("created_at")
    gt_dex = pool.get("dex")
    return TokenCandidate(
        mint=mint,
        symbol=pool.get("base_symbol") or "",
        name=pool.get("base_name") or "",
        pool=pool.get("pool"),
        dex=_dex_id(gt_dex),
        sources=[source],
        created_at=created_at,
        age_min=(now - created_at) / 60 if created_at is not None else None,
        mcap_usd=first_not_none(pool.get("mcap_usd"), pool.get("fdv_usd")),
        liquidity_usd=pool.get("reserve_usd"),
        price_usd=pool.get("price_usd"),
        fdv_usd=pool.get("fdv_usd"),
        decimals=pool.get("base_decimals"),
        graduated=False if gt_dex in CURVE_DEXES else None,
        discovered_at=now,
        raw={"gt_pool": pool.get("pool")},
    )


# --------------------------------------------------------------------------- helpers


def _dicts(items: Any) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _pools(resp: Any) -> list[dict[str, Any]]:
    """Normalize every ``type == "pool"`` resource of a list response."""
    included = get_path(resp, "included")
    return [normalize_pool(item, included) for item in _dicts(get_path(resp, "data")) if item.get("type") == "pool"]


def _included_tokens(included: Any) -> dict[str, dict[str, Any]]:
    """``{gt_id: attributes}`` for the token resources of an ``included`` list."""
    return {
        item["id"]: item.get("attributes") or {}
        for item in _dicts(included)
        if item.get("type") == "token" and item.get("id")
    }


def _dex_id(gt_dex: str | None) -> str | None:
    if not gt_dex:
        return None
    return _DEX_ALIASES.get(gt_dex, gt_dex.replace("-", ""))


def _trade(item: dict[str, Any]) -> dict[str, Any] | None:
    """One GT trade resource -> flat dict (None when ts or kind is unusable)."""
    attrs = item.get("attributes") or {}
    ts = parse_ts(attrs.get("block_timestamp"))
    kind = str(attrs.get("kind") or "").strip().lower()
    if ts is None or kind not in ("buy", "sell"):
        return None
    base_side = "to" if kind == "buy" else "from"
    return {
        "ts": ts,
        "tx_hash": attrs.get("tx_hash"),
        "wallet": attrs.get("tx_from_address"),
        "kind": kind,
        "volume_usd": to_float(attrs.get("volume_in_usd"), 0.0),
        "price_usd": to_float(attrs.get(f"price_{base_side}_in_usd")),
        "token_amount": to_float(attrs.get(f"{base_side}_token_amount")),
        "block_number": to_int(attrs.get("block_number")),
    }


def _candle(row: Any) -> Candle | None:
    """``[ts, o, h, l, c, v]`` -> Candle; None when any of ts/o/h/l/c is not numeric (v defaults 0)."""
    if not isinstance(row, (list, tuple)) or len(row) < 5:
        return None
    ts = to_int(row[0])
    ohlc = [to_float(x) for x in row[1:5]]
    if ts is None or any(x is None for x in ohlc):
        return None
    volume = to_float(row[5], 0.0) if len(row) > 5 else 0.0
    return Candle(ts, *ohlc, volume)


def _plain_number(value: float) -> str:
    """``300.0`` -> ``"300"``, ``0.5`` -> ``"0.5"`` (never scientific notation)."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _fill_gaps(candles: list[Candle], interval_s: int) -> list[Candle]:
    """Insert flat zero-volume candles (o=h=l=c=previous close) for intervals missing between candles."""
    filled: list[Candle] = []
    for candle in candles:
        if filled:
            prev = filled[-1]
            filled.extend(Candle(ts, prev.c, prev.c, prev.c, prev.c, 0.0)
                          for ts in range(prev.ts + interval_s, candle.ts, interval_s))
        filled.append(candle)
    return filled


def _launchpad(details: Any) -> dict[str, Any] | None:
    if not isinstance(details, dict):
        return None
    return {
        "graduation_percentage": to_float(details.get("graduation_percentage")),
        "completed": to_bool(details.get("completed")),
        "completed_at": parse_ts(details.get("completed_at")),
        "migrated_pool": details.get("migrated_destination_pool_address") or None,
    }


def _websites(items: Any) -> list[str]:
    """Website URLs from a list of strings or ``{"url": ...}`` dicts."""
    if not isinstance(items, list):
        return []
    urls = (item.get("url") if isinstance(item, dict) else item for item in items)
    return [u for u in urls if isinstance(u, str) and u]

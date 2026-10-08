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

from nightcrawler.http import HttpClient, HttpError
from nightcrawler.models import MarketSnapshot
from nightcrawler.sources._parse import chunks, first_not_none, get_path, parse_ts, to_float, to_int

__all__ = ["BASE_URL", "MAX_BATCH", "DexScreenerClient", "pair_to_snapshot", "pair_socials"]

BASE_URL = "https://api.dexscreener.com"
MAX_BATCH = 30
CHAIN = "solana"
#: Social ``type`` aliases normalized by :func:`pair_socials`.
_SOCIAL_ALIASES = {"x": "twitter"}


class DexScreenerClient:
    """Thin typed client over :class:`HttpClient`."""

    def __init__(self, http: HttpClient, base_url: str = BASE_URL) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.get_json(f"{self.base_url}{path}", params=params)

    def token_profiles_latest(self) -> list[dict[str, Any]]:
        """Latest token profiles, Solana only.

        Returns ``[{"mint": str, "url": str|None, "description": str|None,
        "links": [{"type"?, "label"?, "url"}]}]`` in API order. Non-solana
        items and items without ``tokenAddress`` are dropped.
        """
        return [
            {
                "mint": item["tokenAddress"],
                "url": item.get("url") or None,
                "description": item.get("description") or None,
                "links": _links(item.get("links")),
            }
            for item in _solana_items(self._get("/token-profiles/latest/v1"))
            if item.get("tokenAddress")
        ]

    def token_boosts_latest(self) -> list[dict[str, Any]]:
        """Latest paid boosts, Solana only.

        Returns ``[{"mint": str, "amount": float|None, "total_amount": float|None,
        "url": str|None}]``. The crawler marks these mints ``paid_promo=True``.
        """
        return [
            {
                "mint": item["tokenAddress"],
                "amount": to_float(item.get("amount")),
                "total_amount": to_float(item.get("totalAmount")),
                "url": item.get("url") or None,
            }
            for item in _solana_items(self._get("/token-boosts/latest/v1"))
            if item.get("tokenAddress")
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        """``/latest/dex/search?q=`` -> raw pair dicts with ``chainId == "solana"`` only."""
        resp = self._get("/latest/dex/search", params={"q": query})
        return _solana_items(get_path(resp, "pairs"))

    def tokens(self, mints: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Top pair per mint via ``/tokens/v1/solana/{csv}``.

        Splits ``mints`` into batches of :data:`MAX_BATCH` (30) - one HTTP call
        per batch. Returns ``{mint: raw_pair}`` keyed by
        ``pair["baseToken"]["address"]``; mints DexScreener does not know are
        absent. If one token has several pairs in the response, keep the one
        with the highest ``liquidity.usd`` (missing liquidity counts as 0) and,
        as a tie-break, the highest ``volume.h24``. Empty input -> ``{}`` with
        no HTTP call. Duplicate input mints are requested once; pairs whose
        base token was not requested (the mint was the quote side) are ignored.
        """
        best: dict[str, dict[str, Any]] = {}
        for batch in chunks(list(dict.fromkeys(mints)), MAX_BATCH):
            wanted = set(batch)
            for pair in _solana_items(self._get(f"/tokens/v1/{CHAIN}/{','.join(batch)}"), default_chain=CHAIN):
                mint = get_path(pair, "baseToken.address")
                if mint in wanted and (mint not in best or _pair_rank(pair) > _pair_rank(best[mint])):
                    best[mint] = pair
        return best

    def snapshots(self, mints: Sequence[str], now: float) -> dict[str, MarketSnapshot]:
        """``tokens(mints)`` converted with :func:`pair_to_snapshot` (``ts=now``); unparseable pairs skipped."""
        out: dict[str, MarketSnapshot] = {}
        for mint, pair in self.tokens(mints).items():
            snap = pair_to_snapshot(pair, now)
            if snap is not None:
                out[mint] = snap
        return out

    def token_pairs(self, mint: str) -> list[dict[str, Any]]:
        """All Solana pairs for ONE mint (``/token-pairs/v1/solana/{mint}``), raw dicts."""
        resp = self._get(f"/token-pairs/v1/{CHAIN}/{mint}")
        if isinstance(resp, dict):  # tolerate the {"pairs": [...]} envelope of other endpoints
            resp = resp.get("pairs")
        return _solana_items(resp, default_chain=CHAIN)

    def pair(self, pair_address: str) -> dict[str, Any] | None:
        """One pair by address (``/latest/dex/pairs/solana/{pair}``); ``None`` if not found (incl. HTTP 404)."""
        try:
            resp = self._get(f"/latest/dex/pairs/{CHAIN}/{pair_address}")
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise
        pair = get_path(resp, "pair")
        if isinstance(pair, dict):
            return pair
        pairs = _solana_items(get_path(resp, "pairs"), default_chain=CHAIN)
        return pairs[0] if pairs else None


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
    if not isinstance(pair, dict):
        return None
    mint = get_path(pair, "baseToken.address")
    if not mint:
        return None
    fdv = to_float(pair.get("fdv"))
    return MarketSnapshot(
        mint=mint,
        ts=ts,
        price_usd=to_float(pair.get("priceUsd")),
        mcap_usd=first_not_none(to_float(pair.get("marketCap")), fdv),
        liquidity_usd=to_float(get_path(pair, "liquidity.usd")),
        buys_m5=to_int(get_path(pair, "txns.m5.buys"), 0),
        sells_m5=to_int(get_path(pair, "txns.m5.sells"), 0),
        buys_h1=to_int(get_path(pair, "txns.h1.buys"), 0),
        sells_h1=to_int(get_path(pair, "txns.h1.sells"), 0),
        volume_m5=to_float(get_path(pair, "volume.m5"), 0.0),
        volume_h1=to_float(get_path(pair, "volume.h1"), 0.0),
        price_change_m5=to_float(get_path(pair, "priceChange.m5")),
        price_change_h1=to_float(get_path(pair, "priceChange.h1")),
        pool=pair.get("pairAddress") or None,
        dex=pair.get("dexId") or None,
        fdv_usd=fdv,
        pair_created_at=parse_ts(pair.get("pairCreatedAt")),
    )


def pair_socials(pair: dict[str, Any]) -> dict[str, str]:
    """``info.websites`` / ``info.socials`` -> ``{"website": url, "twitter": url, "telegram": url, ...}``.

    First URL per type wins; types lower-cased (``x`` -> ``twitter``).
    """
    out: dict[str, str] = {}
    for site in _dicts(get_path(pair, "info.websites")):
        if site.get("url"):
            out.setdefault("website", site["url"])
    for social in _dicts(get_path(pair, "info.socials")):
        kind = str(social.get("type") or social.get("platform") or "").strip().lower()
        url = social.get("url") or social.get("handle")
        if kind and url:
            out.setdefault(_SOCIAL_ALIASES.get(kind, kind), url)
    return out


# --------------------------------------------------------------------------- helpers


def _dicts(items: Any) -> list[dict[str, Any]]:
    """Only the dict members of ``items`` (empty for anything that is not a list)."""
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _solana_items(items: Any, default_chain: str | None = None) -> list[dict[str, Any]]:
    """Dict items whose ``chainId`` is solana (``default_chain`` applies when ``chainId`` is absent)."""
    return [item for item in _dicts(items) if item.get("chainId", default_chain) == CHAIN]


def _links(links: Any) -> list[dict[str, Any]]:
    """Profile links with a URL, keeping only ``type`` / ``label`` / ``url``."""
    return [
        {key: link[key] for key in ("type", "label", "url") if link.get(key)}
        for link in _dicts(links)
        if link.get("url")
    ]


def _pair_rank(pair: dict[str, Any]) -> tuple[float, float]:
    """Sort key for choosing a token's top pair: (liquidity USD, 24 h volume USD), missing -> 0."""
    return (to_float(get_path(pair, "liquidity.usd"), 0.0), to_float(get_path(pair, "volume.h24"), 0.0))

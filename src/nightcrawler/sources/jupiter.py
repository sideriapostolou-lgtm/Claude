"""Jupiter client (owner: O1): Ultra swap API, token data, prices.

Base URL: ``settings.jupiter_base_url`` - ``https://api.jup.ag`` when
``JUPITER_API_KEY`` is set (sent as header ``x-api-key``), else
``https://lite-api.jup.ag`` (keyless; being retired). Keyless ~0.5-1 req/s.

Ultra (verified live 2026-10-08, fixtures ``jup_ultra_*.json``):

* ``GET {base}/ultra/v1/order?inputMint=&outputMint=&amount=<int base units>[&taker=<pubkey>]``
  -> ``inAmount``, ``outAmount`` (str ints; ``outAmount`` nets pool fees AND the
  Ultra platform fee), ``otherAmountThreshold``, ``slippageBps``,
  ``priceImpactPct`` (str FRACTION, negative = adverse), ``priceImpact``
  (percent number), ``routePlan[]{percent, swapInfo{label, ammKey}}``,
  ``feeBps`` (10), ``feeMint``, ``platformFee``, ``signatureFeeLamports``,
  ``prioritizationFeeLamports``, ``rentFeeLamports``, ``transaction``
  (base64 unsigned tx when the taker has funds; ``null`` without taker,
  ``""`` when funds are insufficient), ``requestId``, ``router``,
  ``inUsdValue``, ``outUsdValue``, ``swapUsdValue``, and on problems
  ``errorCode`` / ``errorMessage`` / ``error`` (e.g. ``"Insufficient funds"`` -
  amounts are still valid). Without a taker ``slippageBps`` is 0.
* ``POST {base}/ultra/v1/execute`` ``{"signedTransaction": b64, "requestId": id}``
  -> ``{status "Success"|"Failed", signature, slot, code, error,
  inputAmountResult, outputAmountResult, totalInputAmount,
  totalOutputAmount, swapEvents}``. NEVER retried automatically.
* ``GET {base}/ultra/v1/holdings/{pubkey}`` -> ``{amount (lamports str),
  uiAmount, tokens: {mint: [{account, amount, uiAmount, decimals, isFrozen, ...}]}}``.
* ``GET {base}/ultra/v1/shield?mints=a,b`` -> ``{warnings: {mint: [{type, message, severity}]}}``
  (severity ``info`` | ``warning`` | ``critical``).

Tokens v2: ``/tokens/v2/recent`` (newest first-pool tokens),
``/tokens/v2/search?query=<mint>``, ``/tokens/v2/toptrending/{5m|1h|6h|24h}?limit=``.
Token fields: ``id`` (mint), ``name``, ``symbol``, ``decimals``, ``dev``,
``launchpad``, ``graduatedPool``, ``graduatedAt``, ``holderCount``, ``mcap``,
``fdv``, ``liquidity``, ``usdPrice``, ``firstPool{id, createdAt}``,
``stats5m`` / ``stats1h`` / ``stats6h`` / ``stats24h`` (``priceChange``,
``holderChange``, ``liquidityChange``, ``buyVolume``, ``sellVolume``,
``buyOrganicVolume``, ``numBuys``, ``numSells``, ``numTraders``,
``numNetBuyers``), ``audit{mintAuthorityDisabled, freezeAuthorityDisabled,
topHoldersPercentage, devBalancePercentage, devMints, devMigrations, isSus}``,
``organicScore`` (0-100), ``organicScoreLabel``, ``tags[]``, ``twitter``, ``website``.

Price v3: ``GET {base}/price/v3?ids=a,b,c`` (<= 50 ids) ->
``{mint: {usdPrice, liquidity, priceChange24h, decimals, blockId}}``; unknown
mints are omitted.
"""

from __future__ import annotations

from typing import Any, Literal, Sequence

from nightcrawler.clock import Clock
from nightcrawler.config import Secret
from nightcrawler.http import HttpClient
from nightcrawler.models import SOL_MINT, Balances, Quote, TokenCandidate

__all__ = [
    "LITE_BASE_URL",
    "KEYED_BASE_URL",
    "PRICE_BATCH",
    "JupiterError",
    "JupiterClient",
    "quote_from_order",
    "token_to_candidate",
]

LITE_BASE_URL = "https://lite-api.jup.ag"
KEYED_BASE_URL = "https://api.jup.ag"
PRICE_BATCH = 50


class JupiterError(Exception):
    """Jupiter answered but the payload is unusable (e.g. order without amounts)."""


class JupiterClient:
    """Thin typed client. ``api_key`` (if any) is sent as ``x-api-key`` and never logged."""

    def __init__(self, http: HttpClient, base_url: str = LITE_BASE_URL, api_key: Secret | None = None,
                 clock: Clock | None = None) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.clock = clock if clock is not None else http.clock

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key.reveal()} if self.api_key else {}

    # ------------------------------------------------------------------ Ultra
    def ultra_order(self, input_mint: str, output_mint: str, amount: int, taker: str | None = None) -> Quote:
        """Ultra ``/order`` for exactly ``amount`` base units of ``input_mint``.

        Side: ``buy`` when ``input_mint == SOL_MINT``, ``sell`` when
        ``output_mint == SOL_MINT``; anything else -> ``ValueError``.
        ``amount`` must be a positive int. Returns :func:`quote_from_order`
        with ``quoted_at = clock.now()``. An Ultra error like "Insufficient
        funds" is NOT raised - it is carried in ``Quote.error`` /
        ``error_code`` with the amounts intact. Raises :class:`JupiterError`
        if ``inAmount``/``outAmount`` are missing, ``HttpError`` on transport failure.
        """
        raise NotImplementedError

    def ultra_execute(self, signed_tx_b64: str, request_id: str) -> dict[str, Any]:
        """POST ``/ultra/v1/execute`` with ``retry=False`` (never double-send).

        Returns ``{"status": "Success"|"Failed", "signature": str|None,
        "slot": int|None, "code": int|None, "error": str|None,
        "input_amount": int|None (inputAmountResult or totalInputAmount),
        "output_amount": int|None (outputAmountResult or totalOutputAmount),
        "raw": dict}``. Transport errors raise ``HttpError`` - the caller must
        then treat the swap outcome as UNKNOWN and reconcile via holdings /
        signature status before doing anything else.
        """
        raise NotImplementedError

    def holdings(self, pubkey: str) -> Balances:
        """Ultra holdings -> :class:`Balances`: ``sol_lamports`` from ``amount``;
        ``tokens[mint]`` = sum of ``amount`` (base units) over that mint's accounts.
        The wrapped-SOL mint, if listed, stays in ``tokens``."""
        raise NotImplementedError

    def shield(self, mints: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        """``{mint: [{"type", "message", "severity"}]}`` for every requested mint (``[]`` if none)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ tokens
    def tokens_recent(self) -> list[dict[str, Any]]:
        """Raw ``/tokens/v2/recent`` list (newest first-pool tokens)."""
        raise NotImplementedError

    def token_search(self, mint: str) -> dict[str, Any] | None:
        """Raw token dict from ``/tokens/v2/search?query=<mint>`` whose ``id == mint``, else None."""
        raise NotImplementedError

    def top_trending(self, window: Literal["5m", "1h", "6h", "24h"] = "1h", limit: int = 50) -> list[dict[str, Any]]:
        """Raw ``/tokens/v2/toptrending/{window}?limit=`` list."""
        raise NotImplementedError

    # ------------------------------------------------------------------ prices
    def prices(self, mints: Sequence[str]) -> dict[str, float]:
        """``{mint: usdPrice}`` via price v3, batched by :data:`PRICE_BATCH`.

        Unknown mints are omitted (never 0). Empty input -> ``{}`` without a call.
        """
        raise NotImplementedError

    def sol_price_usd(self) -> float:
        """USD per SOL (price v3 of :data:`SOL_MINT`). Raises ``JupiterError`` if missing."""
        raise NotImplementedError


def quote_from_order(resp: dict[str, Any], side: Literal["buy", "sell"], quoted_at: float) -> Quote:
    """Parse an Ultra ``/order`` response into :class:`Quote`.

    * ``in_amount`` / ``out_amount`` / ``other_amount_threshold``: ints from strings.
    * ``price_impact_pct`` = ``abs(float(priceImpactPct)) * 100``; fall back to
      ``abs(priceImpact)`` (already percent); 0.0 if both missing.
    * ``fee_bps`` = ``feeBps`` (or ``platformFee.feeBps``), default 0.
    * ``route_labels`` = ``[step.swapInfo.label for step in routePlan]``.
    * ``transaction_b64`` = ``transaction`` or None when null/"".
    * ``error`` = ``errorMessage`` or ``error``; ``error_code`` = ``errorCode``.
    * ``in_usd`` / ``out_usd`` from ``inUsdValue`` / ``outUsdValue``.
    * ``raw`` = ``resp``. Raises :class:`JupiterError` if amounts are missing.
    """
    raise NotImplementedError


def token_to_candidate(token: dict[str, Any], now: float, source: str) -> TokenCandidate:
    """Jupiter tokens/v2 dict -> :class:`TokenCandidate`.

    ``mint=id``; ``pool`` = ``graduatedPool`` or ``firstPool.id``; ``created_at``
    = ``firstPool.createdAt`` (fallback ``createdAt``); ``age_min`` from ``now``;
    ``mcap_usd``, ``fdv_usd``, ``liquidity_usd``, ``price_usd`` (usdPrice),
    ``holder_count``, ``decimals``, ``dev``, ``launchpad``; ``graduated`` =
    True if ``graduatedPool`` else (False if ``launchpad`` else None);
    ``organic_score``; ``audit`` = ``audit`` dict; ``stats`` =
    ``{"5m": stats5m, "1h": stats1h, "6h": stats6h, "24h": stats24h}`` (present
    ones only); ``socials`` from ``twitter`` / ``website`` / ``telegram``;
    ``sources = [source]``; ``discovered_at = now``; ``raw = {"jupiter_id": id}``.
    """
    raise NotImplementedError

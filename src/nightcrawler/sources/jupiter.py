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

import math
from typing import Any, Literal, Sequence

from nightcrawler.clock import Clock
from nightcrawler.config import Secret
from nightcrawler.http import HttpClient
from nightcrawler.models import SOL_MINT, Balances, Quote, TokenCandidate
from nightcrawler.sources._parse import chunks, first_not_none, get_path, parse_ts, to_float, to_int

__all__ = [
    "LITE_BASE_URL",
    "KEYED_BASE_URL",
    "PRICE_BATCH",
    "SHIELD_BATCH",
    "JupiterError",
    "JupiterClient",
    "quote_from_order",
    "token_to_candidate",
    "tokens_to_candidates",
]

LITE_BASE_URL = "https://lite-api.jup.ag"
KEYED_BASE_URL = "https://api.jup.ag"
PRICE_BATCH = 50
SHIELD_BATCH = 50
#: Ultra /execute polls for the transaction's confirmation before answering, so it can take
#: well over the default 10 s; timing out early turns a landed swap into an "unknown" outcome.
EXECUTE_TIMEOUT_S = 60.0
TRENDING_WINDOWS = ("5m", "1h", "6h", "24h")
_SOCIAL_KEYS = ("twitter", "website", "telegram")


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

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.get_json(f"{self.base_url}{path}", params=params, headers=self._headers())

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
        side = _side(input_mint, output_mint)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError(f"amount must be a positive int of base units, got {amount!r}")
        params = {"inputMint": input_mint, "outputMint": output_mint, "amount": str(amount)}
        if taker:
            params["taker"] = taker
        resp = self._get("/ultra/v1/order", params)
        if not isinstance(resp, dict):
            raise JupiterError("Ultra /order returned no JSON object")
        return quote_from_order(resp, side, self.clock.now(), input_mint=input_mint, output_mint=output_mint)

    def ultra_execute(self, signed_tx_b64: str, request_id: str) -> dict[str, Any]:
        """POST ``/ultra/v1/execute`` with ``retry=False`` (never double-send).

        Returns ``{"status": "Success"|"Failed", "signature": str|None,
        "slot": int|None, "code": int|None, "error": str|None,
        "input_amount": int|None (inputAmountResult or totalInputAmount),
        "output_amount": int|None (outputAmountResult or totalOutputAmount),
        "raw": dict}``. Transport errors raise ``HttpError`` - the caller must
        then treat the swap outcome as UNKNOWN and reconcile via holdings /
        signature status before doing anything else. A ``status`` other than
        ``Success``/``Failed`` (or a missing one, ``None``) is passed through
        unchanged and must also be treated as UNKNOWN.
        """
        resp = self.http.post_json(f"{self.base_url}/ultra/v1/execute",
                                   json={"signedTransaction": signed_tx_b64, "requestId": request_id},
                                   headers=self._headers(), retry=False, timeout_s=EXECUTE_TIMEOUT_S)
        resp = resp if isinstance(resp, dict) else {}
        return {
            "status": resp.get("status"),
            "signature": resp.get("signature") or None,
            "slot": to_int(resp.get("slot")),
            "code": to_int(resp.get("code")),
            "error": resp.get("error") or None,
            "input_amount": to_int(first_not_none(resp.get("inputAmountResult"), resp.get("totalInputAmount"))),
            "output_amount": to_int(first_not_none(resp.get("outputAmountResult"), resp.get("totalOutputAmount"))),
            "raw": resp,
        }

    def holdings(self, pubkey: str) -> Balances:
        """Ultra holdings -> :class:`Balances`: ``sol_lamports`` from ``amount``;
        ``tokens[mint]`` = sum of ``amount`` (base units) over that mint's accounts.
        The wrapped-SOL mint, if listed, stays in ``tokens``. Accounts without
        a parseable ``amount`` count as 0 (never overstated)."""
        resp = self._get(f"/ultra/v1/holdings/{pubkey}")
        tokens: dict[str, int] = {}
        raw_tokens = get_path(resp, "tokens", {})
        for mint, accounts in (raw_tokens.items() if isinstance(raw_tokens, dict) else ()):
            accounts = [accounts] if isinstance(accounts, dict) else accounts
            tokens[mint] = sum(to_int(get_path(acc, "amount"), 0) for acc in _dicts(accounts))
        return Balances(sol_lamports=to_int(get_path(resp, "amount"), 0), tokens=tokens)

    def shield(self, mints: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        """``{mint: [{"type", "message", "severity"}]}`` for every requested mint (``[]`` if none).

        ``severity`` is lower-cased. Batched by :data:`SHIELD_BATCH`; empty input -> ``{}`` without a call.
        A 200 body without a ``warnings`` OBJECT (an error body, a renamed key) raises
        :class:`JupiterError`: Shield is a required cocoon source and must fail closed, never
        read as "no warnings".
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for batch in chunks(list(dict.fromkeys(mints)), SHIELD_BATCH):
            resp = self._get("/ultra/v1/shield", {"mints": ",".join(batch)})
            warnings = resp.get("warnings") if isinstance(resp, dict) else None
            if not isinstance(warnings, dict):
                detail = resp.get("error") if isinstance(resp, dict) else None
                raise JupiterError(f"Shield answered without a warnings object ({detail or type(resp).__name__})")
            for mint in batch:
                out[mint] = [_shield_warning(w) for w in _dicts(get_path(warnings, (mint,)))]
        return out

    # ------------------------------------------------------------------ tokens
    def tokens_recent(self) -> list[dict[str, Any]]:
        """Raw ``/tokens/v2/recent`` list (newest first-pool tokens)."""
        return _dicts(self._get("/tokens/v2/recent"))

    def token_search(self, mint: str) -> dict[str, Any] | None:
        """Raw token dict from ``/tokens/v2/search?query=<mint>`` whose ``id == mint``, else None."""
        found = _dicts(self._get("/tokens/v2/search", {"query": mint}))
        return next((token for token in found if token.get("id") == mint), None)

    def top_trending(self, window: Literal["5m", "1h", "6h", "24h"] = "1h", limit: int = 50) -> list[dict[str, Any]]:
        """Raw ``/tokens/v2/toptrending/{window}?limit=`` list. Unknown ``window`` -> ``ValueError``."""
        if window not in TRENDING_WINDOWS:
            raise ValueError(f"window must be one of {TRENDING_WINDOWS}, got {window!r}")
        return _dicts(self._get(f"/tokens/v2/toptrending/{window}", {"limit": limit}))

    # ------------------------------------------------------------------ prices
    def prices(self, mints: Sequence[str]) -> dict[str, float]:
        """``{mint: usdPrice}`` via price v3, batched by :data:`PRICE_BATCH`.

        Unknown mints are omitted (never 0). Empty input -> ``{}`` without a call.
        """
        out: dict[str, float] = {}
        for batch in chunks(list(dict.fromkeys(mints)), PRICE_BATCH):
            resp = self._get("/price/v3", {"ids": ",".join(batch)})
            for mint in batch:
                price = to_float(get_path(resp, (mint, "usdPrice")))
                if price is not None and price > 0:
                    out[mint] = price
        return out

    def sol_price_usd(self) -> float:
        """USD per SOL (price v3 of :data:`SOL_MINT`). Raises ``JupiterError`` if missing."""
        price = self.prices([SOL_MINT]).get(SOL_MINT)
        if price is None:
            raise JupiterError("price v3 returned no SOL price")
        return price


def quote_from_order(resp: dict[str, Any], side: Literal["buy", "sell"], quoted_at: float, *,
                     input_mint: str | None = None, output_mint: str | None = None) -> Quote:
    """Parse an Ultra ``/order`` response into :class:`Quote`.

    * ``in_amount`` / ``out_amount`` / ``other_amount_threshold``: ints from strings.
    * ``price_impact_pct`` = ``abs(float(priceImpactPct)) * 100``; fall back to
      ``abs(priceImpact)`` (already percent); 0.0 if both are missing or
      non-finite, with ``price_impact_known=False`` so callers fail closed.
    * ``fee_bps`` = ``feeBps`` (or ``platformFee.feeBps``), default 0.
    * ``route_labels`` = ``[step.swapInfo.label for step in routePlan]``.
    * ``transaction_b64`` = ``transaction`` or None when null/"".
    * ``error`` = ``errorMessage`` or ``error``; ``error_code`` = ``errorCode``.
    * ``in_usd`` / ``out_usd`` from ``inUsdValue`` / ``outUsdValue``.
    * ``raw`` = ``resp``. Raises :class:`JupiterError` if amounts are missing.

    ``input_mint`` / ``output_mint`` are fallbacks for responses without
    ``inputMint`` / ``outputMint``. Raises :class:`JupiterError` when the mints
    are unknown or do not match ``side`` (buy = SOL in, sell = SOL out). A
    non-zero ``errorCode`` without a message becomes ``error = "Ultra errorCode N"``
    so such a quote is never :attr:`Quote.executable`.
    """
    in_amount, out_amount = to_int(resp.get("inAmount")), to_int(resp.get("outAmount"))
    if in_amount is None or out_amount is None:
        detail = resp.get("errorMessage") or resp.get("error") or "no inAmount/outAmount"
        raise JupiterError(f"Ultra order unusable: {detail}")
    in_mint = resp.get("inputMint") or input_mint
    out_mint = resp.get("outputMint") or output_mint
    if not in_mint or not out_mint or _side(in_mint, out_mint, error=JupiterError) != side:
        raise JupiterError(f"Ultra order mints {in_mint}->{out_mint} do not match side {side!r}")
    error_code = to_int(resp.get("errorCode"))
    error = resp.get("errorMessage") or resp.get("error") or None
    if error is None and error_code:
        error = f"Ultra errorCode {error_code}"
    transaction = resp.get("transaction")
    impact = _impact_pct(resp)
    return Quote(
        side=side,
        input_mint=in_mint,
        output_mint=out_mint,
        in_amount=in_amount,
        out_amount=out_amount,
        price_impact_pct=0.0 if impact is None else impact,
        fee_bps=to_int(first_not_none(resp.get("feeBps"), get_path(resp, "platformFee.feeBps")), 0),
        route_labels=[label for step in _dicts(resp.get("routePlan"))
                      if (label := get_path(step, "swapInfo.label"))],
        request_id=resp.get("requestId") or None,
        transaction_b64=transaction if isinstance(transaction, str) and transaction else None,
        quoted_at=quoted_at,
        in_usd=to_float(resp.get("inUsdValue")),
        out_usd=to_float(resp.get("outUsdValue")),
        slippage_bps=to_int(resp.get("slippageBps"), 0),
        other_amount_threshold=to_int(resp.get("otherAmountThreshold")),
        signature_fee_lamports=to_int(resp.get("signatureFeeLamports"), 0),
        prioritization_fee_lamports=to_int(resp.get("prioritizationFeeLamports"), 0),
        rent_fee_lamports=to_int(resp.get("rentFeeLamports"), 0),
        router=resp.get("router") or None,
        error=str(error) if error is not None else None,
        error_code=error_code,
        raw=resp,
        price_impact_known=impact is not None,
    )


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

    Raises ``ValueError`` when the token has no ``id`` (use
    :func:`tokens_to_candidates` to skip such items).
    """
    mint = token.get("id")
    if not mint:
        raise ValueError("Jupiter token without id")
    created_at = first_not_none(parse_ts(get_path(token, "firstPool.createdAt")), parse_ts(token.get("createdAt")))
    graduated_pool = token.get("graduatedPool") or None
    launchpad = token.get("launchpad") or None
    audit = token.get("audit")
    return TokenCandidate(
        mint=mint,
        symbol=token.get("symbol") or "",
        name=token.get("name") or "",
        pool=graduated_pool or get_path(token, "firstPool.id"),
        sources=[source],
        created_at=created_at,
        age_min=(now - created_at) / 60 if created_at is not None else None,
        mcap_usd=to_float(token.get("mcap")),
        liquidity_usd=to_float(token.get("liquidity")),
        price_usd=to_float(token.get("usdPrice")),
        fdv_usd=to_float(token.get("fdv")),
        holder_count=to_int(token.get("holderCount")),
        decimals=to_int(token.get("decimals")),
        dev=token.get("dev") or None,
        launchpad=launchpad,
        graduated=True if graduated_pool else (False if launchpad else None),
        organic_score=to_float(token.get("organicScore")),
        audit=dict(audit) if isinstance(audit, dict) else {},
        stats={w: token[f"stats{w}"] for w in TRENDING_WINDOWS if isinstance(token.get(f"stats{w}"), dict)},
        socials={k: token[k] for k in _SOCIAL_KEYS if isinstance(token.get(k), str) and token[k]},
        raw={"jupiter_id": mint},
        discovered_at=now,
    )


def tokens_to_candidates(tokens: Sequence[dict[str, Any]], now: float, source: str) -> list[TokenCandidate]:
    """:func:`token_to_candidate` over a raw list, skipping items without an ``id``."""
    return [token_to_candidate(t, now, source) for t in tokens if isinstance(t, dict) and t.get("id")]


# --------------------------------------------------------------------------- helpers


def _dicts(items: Any) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _side(input_mint: str, output_mint: str, error: type[Exception] = ValueError) -> Literal["buy", "sell"]:
    """``buy`` when SOL goes in, ``sell`` when SOL comes out; anything else raises ``error``."""
    if input_mint == SOL_MINT and output_mint != SOL_MINT:
        return "buy"
    if output_mint == SOL_MINT and input_mint != SOL_MINT:
        return "sell"
    raise error(f"exactly one side of the swap must be SOL ({SOL_MINT}): {input_mint} -> {output_mint}")


def _impact_pct(resp: dict[str, Any]) -> float | None:
    """Adverse price impact magnitude in PERCENT (see :class:`~nightcrawler.models.Quote`), or
    None when Ultra sent neither field as a finite number (unknown - never "zero impact")."""
    fraction = to_float(resp.get("priceImpactPct"))
    if fraction is not None and math.isfinite(fraction):
        return abs(fraction) * 100.0
    percent = to_float(resp.get("priceImpact"))
    return abs(percent) if percent is not None and math.isfinite(percent) else None


def _shield_warning(raw: dict[str, Any]) -> dict[str, Any]:
    severity = raw.get("severity")
    return {
        "type": raw.get("type"),
        "message": raw.get("message"),
        "severity": str(severity).lower() if severity is not None else None,
    }

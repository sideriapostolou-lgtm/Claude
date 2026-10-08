"""Live broker: real money through Jupiter Ultra from a DEDICATED bot wallet (owner: O5).

Construction refuses (``LiveNotAllowed``) unless ALL hold:
``settings.trading_mode == "live"``, ``settings.live_confirm ==
"I_ACCEPT_REAL_MONEY_RISK"``, a wallet is loaded, and ``solders`` imports.
Import ``solders`` lazily; if missing raise ``LiveNotAllowed("Live trading needs
the optional dependency: pip install 'nightcrawler[live]'")``.

Swap flow (``execute``):

1. Reject stale quotes (``now - quoted_at > QUOTE_MAX_AGE_S``), quotes this
   broker did not issue, and quotes already sent once -> ``QuoteRejected``.
2. ``quote()`` already required ``quote.transaction_b64`` non-empty and
   ``quote.error`` None (else ``QuoteRejected``).
3. Sign: ``tx = VersionedTransaction.from_bytes(base64.b64decode(quote.transaction_b64))``,
   this wallet's signature slot filled (``Wallet.sign_transaction_b64``; identical to
   ``VersionedTransaction(tx.message, [keypair])`` for single-signer transactions).
4. If ``SIMULATE_BEFORE_SEND``: ``rpc.simulate(b64(bytes(signed)))``; ``err`` or an
   unreachable RPC -> write ``swap_failed`` receipt, raise ``SwapFailed`` (nothing
   sent). A gasless transaction still awaiting Ultra's co-signature cannot pass
   ``sigVerify`` and is sent unsimulated (logged).
5. ``jupiter.ultra_execute(signed_b64, quote.request_id)`` (never retried; the
   quote is marked spent BEFORE sending).
   * Transport error or a status other than Success/Failed -> ``swap_failed``
     receipt with ``outcome="unknown"``, raise ``SwapUnknown`` (engine must
     reconcile before acting on this mint).
   * ``status == "Failed"`` -> ``swap_failed`` receipt, raise ``SwapFailed``.
   * ``status == "Success"`` -> ``Fill`` from ``input_amount`` /
     ``output_amount`` (actual results, NOT the quote; quote amounts only if
     Ultra omitted them), ``signature``, ``fees_lamports`` =
     ``quote.signature_fee_lamports + quote.prioritization_fee_lamports``,
     ``rent_lamports`` = ``quote.rent_fee_lamports`` for buys (0 for sells),
     ``expected_out_amount = quote.out_amount``; record via ``ledger.record_fill``.
6. Never retry a swap blindly (could double-buy). Re-quote instead.

Wallet-cap guard: ``quote('buy', ...)`` raises ``QuoteRejected`` when the
wallet's USD value (SOL + tokens at Jupiter prices) exceeds ``MAX_WALLET_USD``,
or when that value cannot be determined (fail closed).

``balances()`` comes from Ultra holdings for the wallet pubkey.
"""

from __future__ import annotations

import base64
from typing import Any

from nightcrawler.broker.base import (
    BrokerError,
    LiveNotAllowed,
    QuoteRejected,
    SwapFailed,
    SwapUnknown,
    UltraBrokerBase,
    quote_summary,
    require_solders,
)
from nightcrawler.clock import Clock
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.http import HttpError
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import (
    SOL_DECIMALS,
    SOL_MINT,
    Balances,
    Fill,
    Mode,
    Position,
    Quote,
    Side,
    base_to_ui,
    lamports_to_sol,
)
from nightcrawler.sources.jupiter import JupiterError
from nightcrawler.sources.solana_rpc import RpcError

__all__ = ["LiveBroker", "require_solders", "missing_signatures"]

log = get_logger(__name__)


def missing_signatures(tx_b64: str) -> int:
    """Number of still-empty signature slots in a base64 ``VersionedTransaction``."""
    solders = require_solders()
    tx = solders.transaction.VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    empty = solders.signature.Signature.default()
    return sum(1 for sig in tx.signatures if sig == empty)


def _live_refusal(settings: Settings, wallet: Any) -> str | None:
    """Why live trading must not start, or None."""
    if settings.trading_mode != "live":
        return f"TRADING_MODE is {settings.trading_mode!r}; live trading needs TRADING_MODE=live"
    if settings.live_confirm != LIVE_CONFIRM_PHRASE:
        return f"live trading needs LIVE_CONFIRM={LIVE_CONFIRM_PHRASE} (exact)"
    if wallet is None or not wallet.pubkey():
        return "live trading needs a loaded bot wallet (BOT_WALLET_SECRET)"
    return None


class LiveBroker(UltraBrokerBase):
    """Signs Ultra transactions with the bot keypair. Implements ``Broker``."""

    mode: Mode = "live"
    allow_insufficient_funds = False

    def __init__(self, jupiter: Any, rpc: Any, wallet: Any, ledger: Any, settings: Settings,
                 clock: Clock) -> None:
        """Validate the live preconditions (see module docstring) and store dependencies.

        ``wallet``: :class:`~nightcrawler.broker.wallet.Wallet`.
        Raises ``LiveNotAllowed`` when any precondition fails.
        """
        refusal = _live_refusal(settings, wallet)
        if refusal:
            raise LiveNotAllowed(refusal)
        require_solders()
        super().__init__(jupiter, ledger, settings, clock)
        self.rpc = rpc
        self.wallet = wallet
        self._decimals: dict[str, int] = {SOL_MINT: SOL_DECIMALS}

    @property
    def pubkey(self) -> str:
        """The bot wallet's public address (base58)."""
        return self.wallet.pubkey()

    def quote(self, side: Side, mint: str, amount_in: int, decimals: int, *,
              max_impact_pct: float | None = None) -> Quote:
        """Ultra order with ``taker=wallet pubkey`` (see ``Broker.quote``); buys check the wallet cap."""
        quote = self._issue_quote(side, mint, amount_in, decimals, taker=self.pubkey, max_impact_pct=max_impact_pct)
        self._decimals[mint] = decimals
        return quote

    def execute(self, quote: Quote, position: Position | None, *, symbol: str = "") -> Fill:
        """Sign, (simulate), send via Ultra execute; see module docstring."""
        ticket, sol_usd = self._prepare_execution(quote, position)
        signed_b64 = self._sign(quote)
        self._simulate(quote, signed_b64, position)
        ticket.spent = True
        result = self._send(quote, signed_b64, position)
        fill = self._fill_from_result(quote, result, ticket.decimals, sol_usd, position, symbol)
        try:
            recorded = self.ledger.record_fill(fill)
        except Exception:
            log.critical("live_fill_not_recorded signature=%s side=%s mint=%s sol_lamports=%d token_amount=%d",
                         fill.signature, fill.side, fill.mint, fill.sol_lamports, fill.token_amount)
            raise
        log.info("live_fill side=%s mint=%s sol=%.6f tokens=%d expected_out=%d signature=%s",
                 recorded.side, recorded.mint, lamports_to_sol(recorded.sol_lamports), recorded.token_amount,
                 quote.out_amount, recorded.signature)
        return recorded

    def balances(self) -> Balances:
        """Ultra holdings of the wallet."""
        return self.jupiter.holdings(self.pubkey)

    def wallet_value_usd(self) -> float:
        """SOL + token holdings valued at Jupiter prices (unknown prices count 0).

        Token decimals come from earlier quotes or the mint account (RPC, cached).
        """
        holdings = self.balances()
        total = lamports_to_sol(holdings.sol_lamports) * self.sol_price_usd()
        held = {mint: amount for mint, amount in holdings.tokens.items() if amount > 0}
        prices = self.jupiter.prices(list(held)) if held else {}
        for mint, price in prices.items():
            total += base_to_ui(held[mint], self._token_decimals(mint)) * price
        return total

    # ------------------------------------------------------------------ internals
    def _quote_problem(self, quote: Quote, max_impact_pct: float) -> str | None:
        problem = super()._quote_problem(quote, max_impact_pct)
        if problem is None and not quote.transaction_b64:
            problem = "Ultra returned no transaction to sign"
        return problem

    def _before_quote(self, side: Side) -> None:
        """Wallet-cap guard for buys (sells reduce exposure and are always allowed)."""
        if side != "buy":
            return
        limit = self.settings.max_wallet_usd
        try:
            value = self.wallet_value_usd()
        except (HttpError, JupiterError, RpcError, BrokerError) as exc:
            raise QuoteRejected(f"[wallet_cap] wallet value unavailable ({exc}); refusing new entries") from exc
        if value > limit:
            raise QuoteRejected(f"[wallet_cap] wallet worth ${value:.2f} > MAX_WALLET_USD ${limit:.2f}; "
                                "is this really the dedicated bot wallet?")

    def _token_decimals(self, mint: str) -> int:
        if mint not in self._decimals:
            info = self.rpc.mint_info(mint)
            decimals = info.get("decimals") if info else None
            if decimals is None:
                raise BrokerError(f"cannot value held token {mint}: decimals unknown")
            self._decimals[mint] = decimals
        return self._decimals[mint]

    def _sign(self, quote: Quote) -> str:
        try:
            return self.wallet.sign_transaction_b64(quote.transaction_b64)
        except ValueError as exc:  # WalletError / malformed transaction: nothing was sent
            raise QuoteRejected(f"cannot sign the Ultra transaction: {exc}") from None

    def _simulate(self, quote: Quote, signed_b64: str, position: Position | None) -> None:
        if not self.settings.simulate_before_send:
            return
        if missing_signatures(signed_b64):
            log.info("simulate_skipped reason=awaiting_ultra_cosignature request_id=%s", quote.request_id)
            return
        try:
            err = self.rpc.simulate(signed_b64).get("err")
        except (HttpError, RpcError) as exc:
            error = f"simulation unavailable: {exc}"
        else:
            if err is None:
                return
            error = f"simulation failed: {err}"
        self._swap_failed(quote, position, outcome="failed", stage="simulate", error=error)
        raise SwapFailed(error)

    def _send(self, quote: Quote, signed_b64: str, position: Position | None) -> dict[str, Any]:
        try:
            result = self.jupiter.ultra_execute(signed_b64, quote.request_id)
        except Exception as exc:  # the request may have left the machine: outcome UNKNOWN
            self._swap_failed(quote, position, outcome="unknown", stage="execute", error=str(exc))
            raise SwapUnknown(f"Ultra execute outcome unknown ({exc}); reconcile holdings, then re-quote") from exc
        status = result.get("status")
        if status == "Success":
            return result
        outcome = "failed" if status == "Failed" else "unknown"
        error = result.get("error") or f"status {status!r}"
        self._swap_failed(quote, position, outcome=outcome, stage="execute", error=error,
                          signature=result.get("signature"), code=result.get("code"))
        if outcome == "failed":
            raise SwapFailed(f"Ultra execute failed: {error}")
        raise SwapUnknown(f"Ultra execute returned {error}; reconcile holdings, then re-quote")

    def _fill_from_result(self, quote: Quote, result: dict[str, Any], decimals: int, sol_usd: float,
                          position: Position | None, symbol: str) -> Fill:
        actual_in, actual_out = result.get("input_amount"), result.get("output_amount")
        if actual_in is None or actual_out is None:
            log.warning("execute_amounts_missing signature=%s using=quote", result.get("signature"))
            actual_in = quote.in_amount if actual_in is None else actual_in
            actual_out = quote.out_amount if actual_out is None else actual_out
        buy = quote.side == "buy"
        return self._new_fill(
            quote,
            sol_lamports=actual_in if buy else actual_out,
            token_amount=actual_out if buy else actual_in,
            decimals=decimals,
            sol_usd=sol_usd,
            fees_lamports=quote.signature_fee_lamports + quote.prioritization_fee_lamports,
            rent_lamports=quote.rent_fee_lamports if buy else 0,
            signature=result.get("signature"),
            position=position,
            symbol=symbol,
        )

    def _swap_failed(self, quote: Quote, position: Position | None, *, outcome: str, stage: str, error: str,
                     signature: str | None = None, code: int | None = None) -> None:
        payload = {**quote_summary(quote), "mode": self.mode, "outcome": outcome, "stage": stage,
                   "error": str(error), "signature": signature, "code": code,
                   "position_id": position.id if position is not None else None, "wallet": self.pubkey}
        self.ledger.record_swap_failure(payload)
        log.warning("swap_failed outcome=%s stage=%s side=%s mint=%s error=%s",
                    outcome, stage, quote.side, quote.token_mint, error)

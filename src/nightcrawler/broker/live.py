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
4. If ``SIMULATE_BEFORE_SEND``: ``rpc.simulate(b64(bytes(signed)))``; ``err`` ->
   write ``swap_failed`` receipt, raise ``SwapFailed`` (nothing sent). An
   unreachable RPC does the same for BUYS (fail closed); a SELL is then sent
   unsimulated (logged) - Ultra lands it without our RPC, and a stop-loss must
   not be trapped by an RPC outage. A gasless transaction still awaiting Ultra's
   co-signature cannot pass ``sigVerify`` and is sent unsimulated (logged).
5. The quote's age is checked AGAIN (price fetch, signing and simulation take
   time): older than ``QUOTE_MAX_AGE_S`` -> ``QuoteRejected``, nothing sent.
6. ``jupiter.ultra_execute(signed_b64, quote.request_id)`` (the quote is marked
   spent BEFORE sending). Only the IDENTICAL signed transaction is ever re-posted
   (Ultra documents this as safe for ~2 minutes: same signature, it cannot execute
   twice, and the answer reports its status): at most :data:`EXECUTE_REPOLLS` more
   times within :data:`EXECUTE_REPOLL_WINDOW_S` of the quote, after a transport
   error or a non-final answer.
   * Still a transport error, a status other than Success/Failed, or a "Failed"
     whose code does not prove the swap cannot land (:func:`definitely_failed`)
     -> ``swap_failed`` receipt with ``outcome="unknown"``, raise ``SwapUnknown``
     (engine must reconcile before acting on this mint).
   * A definite ``"Failed"`` -> ``swap_failed`` receipt, raise ``SwapFailed``.
   * ``status == "Success"`` -> ``Fill`` from ``input_amount`` /
     ``output_amount`` (actual results, NOT the quote; quote amounts only if
     Ultra omitted them), ``signature``, ``fees_lamports`` =
     ``quote.signature_fee_lamports + quote.prioritization_fee_lamports``,
     ``rent_lamports`` = ``quote.rent_fee_lamports`` for buys (0 for sells),
     ``expected_out_amount = quote.out_amount``; record via ``ledger.record_fill``
     (plus the caller's ``on_fill`` in the same transaction). If that write fails
     the swap HAS landed: log CRITICAL and raise ``SwapUnknown`` carrying the fill,
     so the engine blocks entries and reconciles from the wallet.
7. Never retry a swap blindly (could double-buy). Re-quote instead.

Every ``SwapUnknown`` carries ``.signature``: the one Ultra reported, else the signed
transaction's first signature (the fee payer's = the transaction id; ``None`` for a gasless
transaction, whose first slot is Ultra's). :meth:`LiveBroker.swap_status` reads it with
``getSignatureStatuses``, so the engine can settle an unknown swap as soon as the chain has a
final answer instead of waiting a fixed time.

Wallet-cap guard: ``quote('buy', ...)`` raises ``QuoteRejected`` when the
wallet's USD value (SOL + tokens at Jupiter prices) exceeds ``MAX_WALLET_USD``,
or when that value cannot be determined (fail closed).

``balances()`` comes from Ultra holdings for the wallet pubkey.
"""

from __future__ import annotations

import base64
from typing import Any, Callable

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

__all__ = ["LiveBroker", "require_solders", "missing_signatures", "definitely_failed", "transaction_signature",
           "final_swap_status", "EXECUTE_REPOLLS", "EXECUTE_REPOLL_WINDOW_S", "FINAL_COMMITMENTS"]

log = get_logger(__name__)

#: How many more times the IDENTICAL signed transaction may be posted to learn its status.
EXECUTE_REPOLLS = 2
#: ... but only this long after the quote (Ultra keeps a requestId for ~2 minutes).
EXECUTE_REPOLL_WINDOW_S = 110.0
#: Ultra /execute "Failed" codes that prove the transaction was rejected before broadcast or
#: has expired (it can never land): bad request / unsigned / unknown order (-1..-5), invalid
#: transaction (-1002), not fully signed (-1003), invalid block height (-1004), expired
#: (-1005), gasless unsupported (-1007), RFQ invalid payload / quote expired / rejected
#: (-2002..-2004). Others ("failed to land", "unknown error", "timed out" ...) are NOT final.
DEFINITE_FAILURE_CODES = frozenset({-1, -2, -3, -4, -5, -1002, -1003, -1004, -1005, -1007, -2002, -2003, -2004})


def definitely_failed(result: dict[str, Any]) -> bool:
    """True when an Ultra ``status == "Failed"`` answer proves the swap did not and cannot happen:
    a code from :data:`DEFINITE_FAILURE_CODES`, or a positive program error code with a signature
    (the transaction landed and failed on chain)."""
    code = result.get("code")
    if code in DEFINITE_FAILURE_CODES:
        return True
    return isinstance(code, int) and code > 0 and bool(result.get("signature"))


#: Commitment levels at which a transaction's outcome is final for our purposes ("confirmed" is what
#: Ultra itself reports as Success; a supermajority-confirmed block has never been rolled back).
FINAL_COMMITMENTS = frozenset({"confirmed", "finalized"})


def missing_signatures(tx_b64: str) -> int:
    """Number of still-empty signature slots in a base64 ``VersionedTransaction``."""
    solders = require_solders()
    tx = solders.transaction.VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    empty = solders.signature.Signature.default()
    return sum(1 for sig in tx.signatures if sig == empty)


def transaction_signature(tx_b64: str) -> str | None:
    """The transaction id (first signature, base58) of a signed base64 transaction, or None when
    that slot is still empty (a gasless transaction awaiting Ultra's fee-payer signature)."""
    solders = require_solders()
    try:
        tx = solders.transaction.VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    except (ValueError, TypeError):
        return None
    if not tx.signatures or tx.signatures[0] == solders.signature.Signature.default():
        return None
    return str(tx.signatures[0])


def final_swap_status(status: dict[str, Any] | None) -> str | None:
    """``"landed"`` / ``"failed"`` when a ``SolanaRpc.signature_status`` answer is final (confirmed
    or finalized, without / with an error), else None (unknown signature, or only processed)."""
    if not isinstance(status, dict) or status.get("confirmation_status") not in FINAL_COMMITMENTS:
        return None
    return "failed" if status.get("err") is not None else "landed"


def _unknown(message: str, signature: str | None, fill: Fill | None = None) -> SwapUnknown:
    """A :class:`SwapUnknown` carrying the transaction ``signature`` (None when not known)."""
    exc = SwapUnknown(message, fill)
    exc.signature = signature  # type: ignore[attr-defined]
    return exc


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
    #: ``execute`` accepts ``on_signed`` and ``SwapUnknown`` carries ``.signature``; ``swap_status`` exists.
    reports_signature = True

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

    def execute(self, quote: Quote, position: Position | None, *, symbol: str = "",
                on_fill: Callable[[Fill], Any] | None = None,
                on_signed: Callable[[str | None], Any] | None = None) -> Fill:
        """Sign, (simulate), send via Ultra execute; see module docstring.

        ``on_signed(signature)`` runs right BEFORE the transaction is first posted (signature None for
        a gasless one): the engine stores it in its in-flight marker, so even a process killed while
        the swap is in flight can ask the chain about it. Its failure is logged, never fatal."""
        ticket, sol_usd = self._prepare_execution(quote, position)
        signed_b64 = self._sign(quote)
        self._simulate(quote, signed_b64, position)
        age = self.clock.now() - quote.quoted_at
        if age > self.settings.quote_max_age_s:  # signing/simulation/price fetch took long: never send it
            raise QuoteRejected(f"stale quote before sending: {age:.1f}s old > QUOTE_MAX_AGE_S "
                                f"{self.settings.quote_max_age_s:g}s")
        signature = transaction_signature(signed_b64)
        if on_signed is not None:
            try:
                on_signed(signature)
            except Exception as exc:  # bookkeeping only: the swap itself is still safe to send
                log.warning("on_signed_failed signature=%s error=%s: %s", signature, type(exc).__name__, exc)
        ticket.spent = True
        result = self._send(quote, signed_b64, position, signature)
        fill = self._fill_from_result(quote, result, ticket.decimals, sol_usd, position, symbol)
        try:
            with self.ledger.transaction():
                recorded = self.ledger.record_fill(fill)
                if on_fill is not None:
                    on_fill(recorded)
        except Exception as exc:  # the swap LANDED: never let the engine forget it
            log.critical("live_fill_not_recorded signature=%s side=%s mint=%s sol_lamports=%d token_amount=%d "
                         "error=%s: %s", fill.signature, fill.side, fill.mint, fill.sol_lamports, fill.token_amount,
                         type(exc).__name__, exc)
            raise _unknown(f"swap landed (signature {fill.signature}) but was not recorded "
                           f"({type(exc).__name__}: {exc}); reconcile holdings, then re-quote", fill.signature,
                           fill) from exc
        log.info("live_fill side=%s mint=%s sol=%.6f tokens=%d expected_out=%d signature=%s",
                 recorded.side, recorded.mint, lamports_to_sol(recorded.sol_lamports), recorded.token_amount,
                 quote.out_amount, recorded.signature)
        return recorded

    def balances(self) -> Balances:
        """Ultra holdings of the wallet."""
        return self.jupiter.holdings(self.pubkey)

    def swap_status(self, signature: str) -> str | None:
        """Final on-chain outcome of a sent swap: ``"landed"``, ``"failed"`` or None (not known or not
        final yet) - see :func:`final_swap_status`. Raises ``RpcError``/``HttpError`` when the RPC fails."""
        return final_swap_status(self.rpc.signature_status(signature))

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
            if position is not None:  # a sell: an RPC outage must not trap a stop-loss
                log.warning("simulate_unavailable_sending_exit_unsimulated request_id=%s error=%s",
                            quote.request_id, exc)
                return
            error = f"simulation unavailable: {exc}"
        else:
            if err is None:
                return
            error = f"simulation failed: {err}"
        self._swap_failed(quote, position, outcome="failed", stage="simulate", error=error)
        raise SwapFailed(error)

    def _send(self, quote: Quote, signed_b64: str, position: Position | None,
              signature: str | None = None) -> dict[str, Any]:
        """Post the signed transaction; re-post the IDENTICAL one (never a new swap) to learn a
        final status after a transport error or a non-final answer (see module docstring).
        ``signature``: the transaction id when known before sending (carried by ``SwapUnknown``)."""
        repolls = 0
        while True:
            try:
                result: dict[str, Any] | None = self.jupiter.ultra_execute(signed_b64, quote.request_id)
                problem: BaseException | None = None
            except Exception as exc:  # the request may have left the machine: outcome UNKNOWN
                result, problem = None, exc
            if result is not None:
                status = result.get("status")
                if status == "Success":
                    return result
                if status == "Failed" and definitely_failed(result):
                    error = result.get("error") or "status 'Failed'"
                    self._swap_failed(quote, position, outcome="failed", stage="execute", error=error,
                                      signature=result.get("signature"), code=result.get("code"))
                    raise SwapFailed(f"Ultra execute failed: {error} (code {result.get('code')})")
            if repolls < EXECUTE_REPOLLS and self.clock.now() - quote.quoted_at < EXECUTE_REPOLL_WINDOW_S:
                repolls += 1
                log.warning("execute_status_repoll request_id=%s attempt=%d reason=%s", quote.request_id, repolls,
                            problem if problem is not None else (result or {}).get("error") or
                            f"status {(result or {}).get('status')!r}")
                continue
            if problem is not None:
                self._swap_failed(quote, position, outcome="unknown", stage="execute", error=str(problem),
                                  signature=signature)
                raise _unknown(f"Ultra execute outcome unknown ({problem}); reconcile holdings, then re-quote",
                               signature) from problem
            assert result is not None
            error = result.get("error") or f"status {result.get('status')!r}"
            reported = result.get("signature") or signature
            self._swap_failed(quote, position, outcome="unknown", stage="execute", error=error,
                              signature=reported, code=result.get("code"))
            raise _unknown(f"Ultra execute returned {error} (code {result.get('code')}): not final; "
                           "reconcile holdings, then re-quote", reported)

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

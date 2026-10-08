"""Live broker: real money through Jupiter Ultra from a DEDICATED bot wallet (owner: O5).

Construction refuses (``LiveNotAllowed``) unless ALL hold:
``settings.trading_mode == "live"``, ``settings.live_confirm ==
"I_ACCEPT_REAL_MONEY_RISK"``, a wallet is loaded, and ``solders`` imports.
Import ``solders`` lazily; if missing raise ``LiveNotAllowed("Live trading needs
the optional dependency: pip install 'nightcrawler[live]'")``.

Swap flow (``execute``):

1. Reject stale quotes (``now - quoted_at > QUOTE_MAX_AGE_S``) -> ``QuoteRejected``.
2. Require ``quote.transaction_b64`` non-empty and ``quote.error`` None ->
   else ``QuoteRejected``.
3. ``tx = VersionedTransaction.from_bytes(base64.b64decode(quote.transaction_b64))``;
   ``signed = VersionedTransaction(tx.message, [keypair])``.
4. If ``SIMULATE_BEFORE_SEND``: ``rpc.simulate(b64(bytes(signed)))``; ``err`` ->
   write ``swap_failed`` receipt, raise ``SwapFailed`` (nothing sent).
5. ``jupiter.ultra_execute(signed_b64, quote.request_id)`` (never retried).
   * Transport error -> ``swap_failed`` receipt with ``outcome="unknown"``,
     raise ``SwapUnknown`` (engine must reconcile before acting on this mint).
   * ``status == "Failed"`` -> ``swap_failed`` receipt, raise ``SwapFailed``.
   * ``status == "Success"`` -> ``Fill`` from ``input_amount`` /
     ``output_amount`` (actual results, NOT the quote), ``signature``,
     ``fees_lamports`` = ``quote.signature_fee_lamports +
     quote.prioritization_fee_lamports``, ``rent_lamports`` =
     ``quote.rent_fee_lamports`` for buys (0 if unknown),
     ``expected_out_amount = quote.out_amount``; record via ``ledger.record_fill``.
6. Never retry a swap blindly (could double-buy). Re-quote instead.

Wallet-cap guard: ``quote('buy', ...)`` raises ``QuoteRejected`` when the
wallet's USD value (SOL + tokens at Jupiter prices) exceeds ``MAX_WALLET_USD``.

``balances()`` comes from Ultra holdings for the wallet pubkey.
"""

from __future__ import annotations

from typing import Any

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.models import Balances, Fill, Mode, Position, Quote, Side

__all__ = ["LiveBroker", "require_solders"]


def require_solders() -> Any:
    """Import and return the ``solders`` module or raise ``LiveNotAllowed`` with install instructions."""
    raise NotImplementedError


class LiveBroker:
    """Signs Ultra transactions with the bot keypair. Implements ``Broker``."""

    mode: Mode = "live"

    def __init__(self, jupiter: Any, rpc: Any, wallet: Any, ledger: Any, settings: Settings,
                 clock: Clock) -> None:
        """Validate the live preconditions (see module docstring) and store dependencies.

        ``wallet``: :class:`~nightcrawler.broker.wallet.Wallet`.
        Raises ``LiveNotAllowed`` when any precondition fails.
        """
        raise NotImplementedError

    @property
    def pubkey(self) -> str:
        """The bot wallet's public address (base58)."""
        raise NotImplementedError

    def quote(self, side: Side, mint: str, amount_in: int, decimals: int) -> Quote:
        """Ultra order with ``taker=wallet pubkey`` (see ``Broker.quote``)."""
        raise NotImplementedError

    def execute(self, quote: Quote, position: Position | None) -> Fill:
        """Sign, (simulate), send via Ultra execute; see module docstring."""
        raise NotImplementedError

    def balances(self) -> Balances:
        """Ultra holdings of the wallet."""
        raise NotImplementedError

    def sol_price_usd(self) -> float:
        """USD per SOL (Jupiter price v3), cached 60 s."""
        raise NotImplementedError

    def wallet_value_usd(self) -> float:
        """SOL + token holdings valued at Jupiter prices (unknown prices count 0)."""
        raise NotImplementedError

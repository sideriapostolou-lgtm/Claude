"""Broker protocol shared by paper and live execution (owner: O5).

Paper mode must mirror live exactly: the SAME Jupiter Ultra ``/order`` quote
at the exact size, the same fee accounting; the only difference is that live
signs and sends the transaction.

Amount conventions (see ``models.py``):

* ``quote("buy", mint, amount_in=<lamports of SOL to spend>, decimals)``
* ``quote("sell", mint, amount_in=<token base units to sell>, decimals)``
* ``decimals`` = the token's decimals (needed to compute ``Fill.price_usd``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nightcrawler.models import Balances, Fill, Mode, Position, Quote, Side

__all__ = [
    "Broker",
    "BrokerError",
    "QuoteRejected",
    "SwapFailed",
    "SwapUnknown",
    "InsufficientBalance",
    "LiveNotAllowed",
]


class BrokerError(Exception):
    """Base class for execution errors."""


class QuoteRejected(BrokerError):
    """The quote is unusable: price impact above MAX_PRICE_IMPACT_PCT, an Ultra
    error other than "Insufficient funds" (paper), missing transaction (live),
    or older than QUOTE_MAX_AGE_S. No state changed."""


class InsufficientBalance(BrokerError):
    """Not enough SOL (after SOL_RESERVE, fees and rent) or tokens for the swap. No state changed."""


class SwapFailed(BrokerError):
    """Live swap definitely did not happen (simulation error or Ultra status "Failed").
    A ``swap_failed`` receipt has been written; no position change."""


class SwapUnknown(BrokerError):
    """Live swap outcome unknown (transport error during /execute). DO NOT retry the
    same swap - reconcile balances (Ultra holdings) first, then re-quote."""


class LiveNotAllowed(BrokerError):
    """LiveBroker construction refused (mode/confirmation/wallet/solders missing)."""


@runtime_checkable
class Broker(Protocol):
    """What the engine needs from an execution venue."""

    #: ``"paper"`` or ``"live"``
    mode: Mode

    def quote(self, side: Side, mint: str, amount_in: int, decimals: int) -> Quote:
        """Fetch a fresh Ultra quote for exactly ``amount_in`` (see module docstring).

        Raises ``QuoteRejected`` when impact > ``MAX_PRICE_IMPACT_PCT`` or the
        quote has a disqualifying error; ``HttpError``/``JupiterError`` on
        transport problems.
        """
        ...

    def execute(self, quote: Quote, position: Position | None) -> Fill:
        """Execute ``quote`` and return the recorded :class:`Fill` (already in the ledger,
        with ``receipt_hash`` set).

        ``position``: None for an opening buy; the open position for adds and
        sells (needed for rent refund on a full exit and ``Fill.position_id``).
        Must NOT re-quote silently: paper fills at ``quote.out_amount``; live
        sends ``quote.transaction_b64``. Raises ``QuoteRejected`` (stale),
        ``InsufficientBalance``, ``SwapFailed`` or ``SwapUnknown``. The caller
        (engine) updates the Position from the Fill.
        """
        ...

    def balances(self) -> Balances:
        """Current SOL lamports and token base units (paper: virtual; live: Ultra holdings)."""
        ...

    def sol_price_usd(self) -> float:
        """USD per SOL from Jupiter price v3 (cached <= 60 s)."""
        ...

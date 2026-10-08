"""Paper broker: honest simulated fills from LIVE Jupiter Ultra quotes (owner: O5).

Rules (the contract):

* Starting balance: on first ever start (no ``paper.sol_lamports`` in the
  ledger kv) the virtual wallet gets ``PAPER_START_USD / sol_price_usd``
  SOL (rounded down to lamports); ``paper.start_lamports`` and
  ``paper.start_sol_usd`` are recorded. Restarts resume from kv:
  ``paper.sol_lamports`` (int), ``paper.tokens`` ({mint: int}),
  ``paper.rent`` ({mint: rent lamports locked}).
* Quote: ``jupiter.ultra_order(input, output, amount_in, taker=<bot pubkey if
  configured else None>)``. An ``"Insufficient funds"`` error is fine (amounts
  are valid). Any OTHER Ultra error, or ``price_impact_pct >
  MAX_PRICE_IMPACT_PCT`` -> ``QuoteRejected``.
* Execute (no re-quote): reject if ``now - quote.quoted_at >
  QUOTE_MAX_AGE_S`` (``QuoteRejected("stale quote")``).
  - BUY: require ``sol_lamports - SOL_RESERVE - NETWORK_FEE - rent(if new) >=
    in_amount`` else ``InsufficientBalance``. Debit ``in_amount +
    network_fee_lamports + rent`` where rent = ``TOKEN_ACCOUNT_RENT_LAMPORTS``
    on the FIRST buy of a mint we do not currently hold (else 0). Credit
    exactly ``quote.out_amount`` tokens.
  - SELL: require token balance >= ``in_amount``. Debit tokens, credit
    ``quote.out_amount`` lamports minus ``network_fee_lamports``; if the token
    balance becomes 0, refund the locked rent (``Fill.rent_lamports`` negative).
  - ``Fill``: ``mode="paper"``, ``signature=None``, ``fees_lamports =
    NETWORK_FEE_SOL`` in lamports, ``platform_fee_bps = quote.fee_bps``,
    ``price_impact_pct = quote.price_impact_pct``, ``sol_usd`` from
    :meth:`sol_price_usd`, ``price_usd = effective_price_usd(...)``,
    ``expected_out_amount = quote.out_amount``, ``request_id`` from the quote.
  - Persist new balances AND the fill (``ledger.record_fill``, which appends
    the receipt) in ONE ledger transaction, then return the fill with
    ``receipt_hash`` set.
* ``balances()`` returns the virtual balances (never touches the network).
"""

from __future__ import annotations

from typing import Any

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.models import Balances, Fill, Mode, Position, Quote, Side

__all__ = ["PaperBroker", "SOL_PRICE_TTL_S"]

SOL_PRICE_TTL_S = 60


class PaperBroker:
    """Virtual wallet + live quotes. Implements :class:`nightcrawler.broker.base.Broker`."""

    mode: Mode = "paper"

    def __init__(self, jupiter: Any, ledger: Any, settings: Settings, clock: Clock,
                 taker: str | None = None) -> None:
        """``jupiter``: :class:`~nightcrawler.sources.jupiter.JupiterClient`;
        ``ledger``: :class:`~nightcrawler.ledger.Ledger`; ``taker``: optional
        bot wallet pubkey to quote with (more realistic routing)."""
        self.jupiter = jupiter
        self.ledger = ledger
        self.settings = settings
        self.clock = clock
        self.taker = taker

    def quote(self, side: Side, mint: str, amount_in: int, decimals: int) -> Quote:
        """See :meth:`nightcrawler.broker.base.Broker.quote` and the module rules."""
        raise NotImplementedError

    def execute(self, quote: Quote, position: Position | None) -> Fill:
        """See :meth:`nightcrawler.broker.base.Broker.execute` and the module rules."""
        raise NotImplementedError

    def balances(self) -> Balances:
        """Virtual balances from the ledger kv (initializing them on first call)."""
        raise NotImplementedError

    def sol_price_usd(self) -> float:
        """USD per SOL (Jupiter price v3), cached for :data:`SOL_PRICE_TTL_S`."""
        raise NotImplementedError

    def reset(self, start_usd: float | None = None) -> Balances:
        """Wipe virtual balances and start over with ``start_usd`` (default PAPER_START_USD).

        Writes a ``note`` receipt. Used by tests and an explicit CLI action only.
        """
        raise NotImplementedError

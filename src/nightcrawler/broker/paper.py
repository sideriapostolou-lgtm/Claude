"""Paper broker: honest simulated fills from LIVE Jupiter Ultra quotes (owner: O5).

Rules (the contract):

* Starting balance: on first ever start (no ``paper.sol_lamports`` in the
  ledger kv) the virtual wallet gets ``PAPER_START_USD / sol_price_usd``
  SOL (rounded down to lamports); ``paper.start_lamports`` and
  ``paper.start_sol_usd`` are recorded (plus a ``note`` receipt, so the
  starting bankroll is on the hash chain). Restarts resume from kv:
  ``paper.sol_lamports`` (int), ``paper.tokens`` ({mint: int}),
  ``paper.rent`` ({mint: rent lamports locked}).
* Quote: ``jupiter.ultra_order(input, output, amount_in, taker=<bot pubkey if
  configured else None>)``. An ``"Insufficient funds"`` error is fine (amounts
  are valid). Any OTHER Ultra error, or ``price_impact_pct >
  MAX_PRICE_IMPACT_PCT`` -> ``QuoteRejected``.
* Execute (no re-quote): reject if ``now - quote.quoted_at >
  QUOTE_MAX_AGE_S`` (``QuoteRejected("stale quote")``), or if the quote was
  not issued by this broker or was already executed (see ``broker.base``).
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
    :meth:`sol_price_usd` (falling back to the quote's own SOL valuation if
    the price feed is down), ``price_usd = effective_price_usd(...)``,
    ``expected_out_amount = quote.out_amount``, ``request_id`` from the quote.
  - Persist new balances AND the fill (``ledger.record_fill``, which appends
    the receipt) in ONE ledger transaction, then return the fill with
    ``receipt_hash`` set.
* ``balances()`` returns the virtual balances. It touches the network only
  once ever: on the very first start, to convert PAPER_START_USD to SOL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from nightcrawler.broker.base import (
    SOL_PRICE_TTL_S,
    InsufficientBalance,
    UltraBrokerBase,
)
from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import (
    LAMPORTS_PER_SOL,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    Balances,
    Fill,
    Mode,
    Position,
    Quote,
    Side,
    lamports_to_sol,
)

__all__ = ["PaperBroker", "SOL_PRICE_TTL_S", "paper_out_amount"]

log = get_logger(__name__)

KV_SOL = "paper.sol_lamports"
KV_TOKENS = "paper.tokens"
KV_RENT = "paper.rent"
KV_START_LAMPORTS = "paper.start_lamports"
KV_START_SOL_USD = "paper.start_sol_usd"


def _sol(lamports: int) -> str:
    return f"{lamports_to_sol(lamports):.6f} SOL"


def paper_out_amount(out_amount: int, slippage_bps: int) -> int:
    """What a paper fill receives for a quote promising ``out_amount``: ``PAPER_SLIPPAGE_BPS``
    less (rounded down), modelling the gap between a quote and a landed live swap."""
    return out_amount * (10_000 - slippage_bps) // 10_000


@dataclass(slots=True)
class _PaperWallet:
    """Virtual balances as stored in the ledger kv. Methods validate BEFORE mutating."""

    sol_lamports: int
    tokens: dict[str, int] = field(default_factory=dict)
    rent: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, ledger: Any) -> _PaperWallet | None:
        sol = ledger.get_kv(KV_SOL)
        if sol is None:
            return None
        tokens = {m: int(a) for m, a in (ledger.get_kv(KV_TOKENS) or {}).items()}
        rent = {m: int(a) for m, a in (ledger.get_kv(KV_RENT) or {}).items()}
        return cls(int(sol), tokens, rent)

    def save(self, ledger: Any) -> None:
        ledger.set_kv(KV_SOL, self.sol_lamports)
        ledger.set_kv(KV_TOKENS, self.tokens)
        ledger.set_kv(KV_RENT, self.rent)

    def as_balances(self) -> Balances:
        return Balances(sol_lamports=self.sol_lamports, tokens=dict(self.tokens))

    def buy(self, mint: str, cost: int, received: int, fee: int, reserve: int) -> int:
        """Spend ``cost`` + ``fee`` (+ rent for a new token account); return the rent charged."""
        opens_account = self.tokens.get(mint, 0) == 0 and self.rent.get(mint, 0) == 0
        rent = TOKEN_ACCOUNT_RENT_LAMPORTS if opens_account else 0
        needed = cost + fee + rent + reserve
        if self.sol_lamports < needed:
            raise InsufficientBalance(
                f"need {_sol(needed)} (swap {_sol(cost)} + fee {_sol(fee)} + rent {_sol(rent)} + "
                f"reserve {_sol(reserve)}), have {_sol(self.sol_lamports)}")
        self.sol_lamports -= cost + fee + rent
        self.tokens[mint] = self.tokens.get(mint, 0) + received
        if rent:
            self.rent[mint] = rent
        return rent

    def sell(self, mint: str, amount: int, proceeds: int, fee: int) -> int:
        """Sell ``amount`` tokens for ``proceeds`` minus ``fee``; return the rent refunded (full exit)."""
        held = self.tokens.get(mint, 0)
        if held < amount:
            raise InsufficientBalance(f"need {amount} base units of {mint}, have {held}")
        remaining = held - amount
        refund = self.rent.get(mint, 0) if remaining == 0 else 0
        new_sol = self.sol_lamports + proceeds - fee + refund
        if new_sol < 0:
            raise InsufficientBalance(f"not enough SOL for the network fee ({_sol(fee)})")
        self.sol_lamports = new_sol
        if remaining:
            self.tokens[mint] = remaining
        else:
            self.tokens.pop(mint, None)
            self.rent.pop(mint, None)
        return refund


class PaperBroker(UltraBrokerBase):
    """Virtual wallet + live quotes. Implements :class:`nightcrawler.broker.base.Broker`."""

    mode: Mode = "paper"
    allow_insufficient_funds = True

    def __init__(self, jupiter: Any, ledger: Any, settings: Settings, clock: Clock,
                 taker: str | None = None) -> None:
        """``jupiter``: :class:`~nightcrawler.sources.jupiter.JupiterClient`;
        ``ledger``: :class:`~nightcrawler.ledger.Ledger`; ``taker``: optional
        bot wallet pubkey to quote with (more realistic routing)."""
        super().__init__(jupiter, ledger, settings, clock)
        self.taker = taker

    def quote(self, side: Side, mint: str, amount_in: int, decimals: int, *,
              max_impact_pct: float | None = None) -> Quote:
        """See :meth:`nightcrawler.broker.base.Broker.quote` and the module rules."""
        return self._issue_quote(side, mint, amount_in, decimals, taker=self.taker, max_impact_pct=max_impact_pct)

    def execute(self, quote: Quote, position: Position | None, *, symbol: str = "",
                on_fill: Callable[[Fill], Any] | None = None) -> Fill:
        """See :meth:`nightcrawler.broker.base.Broker.execute` and the module rules.

        ``on_fill`` runs inside the same ledger transaction; if it raises, the whole simulated
        swap (balances, fill, receipt) is rolled back and the error propagates."""
        ticket, sol_usd = self._prepare_execution(quote, position)
        self._ensure_wallet()
        fee = self.settings.network_fee_lamports
        received = paper_out_amount(quote.out_amount, self.settings.paper_slippage_bps)
        with self.ledger.transaction():
            wallet = _PaperWallet.load(self.ledger)
            if quote.side == "buy":
                rent = wallet.buy(quote.token_mint, quote.in_amount, received, fee,
                                  self.settings.sol_reserve_lamports)
                sol_lamports, token_amount = quote.in_amount, received
            else:
                rent = -wallet.sell(quote.token_mint, quote.in_amount, received, fee)
                sol_lamports, token_amount = received, quote.in_amount
            fill = self._new_fill(quote, sol_lamports=sol_lamports, token_amount=token_amount,
                                  decimals=ticket.decimals, sol_usd=sol_usd, fees_lamports=fee,
                                  rent_lamports=rent, signature=None, position=position, symbol=symbol)
            recorded = self.ledger.record_fill(fill)
            wallet.save(self.ledger)
            if on_fill is not None:
                on_fill(recorded)
        ticket.spent = True
        log.info("paper_fill side=%s mint=%s sol=%s tokens=%d impact=%.2f%% fee_bps=%d rent=%d sol_left=%s",
                 recorded.side, recorded.mint, _sol(recorded.sol_lamports), recorded.token_amount,
                 recorded.price_impact_pct, recorded.platform_fee_bps, recorded.rent_lamports,
                 _sol(wallet.sol_lamports))
        return recorded

    def balances(self) -> Balances:
        """Virtual balances from the ledger kv (initializing them on first call)."""
        return self._ensure_wallet().as_balances()

    def reset(self, start_usd: float | None = None) -> Balances:
        """Wipe virtual balances and start over with ``start_usd`` (default PAPER_START_USD).

        Writes a ``note`` receipt. Used by tests and an explicit CLI action only;
        open positions in the ledger are NOT closed here (the caller's job).
        """
        usd = self.settings.paper_start_usd if start_usd is None else float(start_usd)
        if usd <= 0:
            raise ValueError(f"start_usd must be > 0, got {usd}")
        previous = _PaperWallet.load(self.ledger)
        return self._open_wallet(usd, "paper_reset", previous).as_balances()

    # ------------------------------------------------------------------ internals
    def _ensure_wallet(self) -> _PaperWallet:
        """The stored wallet; created from PAPER_START_USD on the very first start."""
        wallet = _PaperWallet.load(self.ledger)
        if wallet is not None:
            return wallet
        return self._open_wallet(self.settings.paper_start_usd, "paper_start", None)

    def _open_wallet(self, start_usd: float, event: str, previous: _PaperWallet | None) -> _PaperWallet:
        sol_usd = self.sol_price_usd()
        wallet = _PaperWallet(int(start_usd / sol_usd * LAMPORTS_PER_SOL))
        with self.ledger.transaction():
            if event == "paper_start":
                existing = _PaperWallet.load(self.ledger)
                if existing is not None:  # another process initialized it meanwhile
                    return existing
            wallet.save(self.ledger)
            self.ledger.set_kv(KV_START_LAMPORTS, wallet.sol_lamports)
            self.ledger.set_kv(KV_START_SOL_USD, sol_usd)
            payload: dict[str, Any] = {"event": event, "start_usd": start_usd, "sol_usd": sol_usd,
                                       "start_lamports": wallet.sol_lamports}
            if previous is not None:
                payload["previous"] = {"sol_lamports": previous.sol_lamports, "tokens": previous.tokens,
                                       "rent": previous.rent}
            self.ledger.append_receipt("note", payload)
        log.info("%s start_usd=%.2f sol_usd=%.4f sol=%s", event, start_usd, sol_usd, _sol(wallet.sol_lamports))
        return wallet

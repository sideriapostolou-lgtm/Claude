"""Broker protocol shared by paper and live execution (owner: O5).

Paper mode must mirror live exactly: the SAME Jupiter Ultra ``/order`` quote
at the exact size, the same fee accounting; the only difference is that live
signs and sends the transaction.

Amount conventions (see ``models.py``):

* ``quote("buy", mint, amount_in=<lamports of SOL to spend>, decimals)``
* ``quote("sell", mint, amount_in=<token base units to sell>, decimals)``
* ``decimals`` = the token's decimals (needed to compute ``Fill.price_usd``).

Quote tickets: ``execute`` only accepts a quote that THIS broker issued via
``quote()`` (so impact/error checks always ran and the token decimals are
known) and never the same quote twice (``request_id`` is spent on first use).
A stale, foreign or already-used quote raises ``QuoteRejected`` - re-quote.

Optional extras beyond the contract (all keyword-only, safe to ignore):
``quote(..., max_impact_pct=None)`` overrides ``MAX_PRICE_IMPACT_PCT`` for one
quote (e.g. a looser cap so a stop-loss can still exit a thinning pool),
``execute(..., symbol="")`` labels the fill and ``execute(..., on_fill=None)``
runs the caller's bookkeeping in the same ledger transaction as the fill.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.http import HttpError
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import (
    LAMPORTS_PER_SOL,
    SOL_MINT,
    Balances,
    Fill,
    Mode,
    Position,
    Quote,
    Side,
    effective_price_usd,
    new_id,
)
from nightcrawler.sources.jupiter import JupiterError

__all__ = [
    "Broker",
    "BrokerError",
    "QuoteRejected",
    "SwapFailed",
    "SwapUnknown",
    "InsufficientBalance",
    "LiveNotAllowed",
    "LIVE_EXTRA_HINT",
    "SOL_PRICE_TTL_S",
    "require_solders",
    "swap_mints",
    "implied_sol_usd",
    "quote_summary",
    "SolPriceCache",
    "UltraBrokerBase",
]

log = get_logger(__name__)

LIVE_EXTRA_HINT = "Live trading needs the optional dependency: pip install 'nightcrawler[live]'"
#: How long a fetched SOL/USD price is reused.
SOL_PRICE_TTL_S = 60.0
#: Tickets of unused quotes are forgotten after this many QUOTE_MAX_AGE_S.
_TICKET_TTL_FACTOR = 4


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
    """Live swap outcome unknown (transport error during /execute, an ambiguous Ultra
    "Failed", or a swap that LANDED but could not be recorded). DO NOT retry the same swap -
    reconcile balances (Ultra holdings) first, then re-quote.

    ``fill``: the actual (unrecorded) Fill when Ultra confirmed the swap but the ledger write
    failed, so reconciliation can book the real amounts instead of an estimate; else None.
    """

    def __init__(self, message: str, fill: Fill | None = None) -> None:
        super().__init__(message)
        self.fill = fill


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

        Optional keyword ``on_fill(recorded_fill)``: called INSIDE the ledger transaction that
        records the fill, so the caller's position update commits (or rolls back) together
        with it. If it raises, nothing is recorded: paper rolls the whole swap back and
        re-raises; live (the swap already landed) raises ``SwapUnknown`` carrying the fill.

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


# --------------------------------------------------------------------------- helpers


def _request_mismatch(quote: Quote, input_mint: str, output_mint: str, amount_in: int) -> str | None:
    """Why Ultra's answer is not a quote for what was asked (other mints or another input amount)."""
    if (quote.input_mint, quote.output_mint, quote.in_amount) != (input_mint, output_mint, amount_in):
        return (f"Ultra quote does not match the request: {quote.input_mint}->{quote.output_mint} for "
                f"{quote.in_amount}, asked {input_mint}->{output_mint} for {amount_in}")
    return None


def require_solders() -> Any:
    """Import and return the ``solders`` package (with the submodules nightcrawler uses)
    or raise :class:`LiveNotAllowed` with install instructions."""
    try:
        solders = importlib.import_module("solders")
        for sub in ("keypair", "message", "signature", "transaction"):
            importlib.import_module(f"solders.{sub}")
    except ImportError as exc:
        raise LiveNotAllowed(LIVE_EXTRA_HINT) from exc
    return solders


def swap_mints(side: Side, mint: str) -> tuple[str, str]:
    """``(input_mint, output_mint)``: buy = SOL -> token, sell = token -> SOL."""
    if mint == SOL_MINT:
        raise ValueError("the traded mint must not be SOL itself")
    if side == "buy":
        return SOL_MINT, mint
    if side == "sell":
        return mint, SOL_MINT
    raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")


def implied_sol_usd(quote: Quote) -> float | None:
    """USD per SOL implied by the quote's own USD valuation of its SOL leg, or None."""
    usd, lamports = (quote.in_usd, quote.in_amount) if quote.side == "buy" else (quote.out_usd, quote.out_amount)
    if not usd or usd <= 0 or lamports <= 0:
        return None
    return usd / (lamports / LAMPORTS_PER_SOL)


def quote_summary(quote: Quote) -> dict[str, Any]:
    """Small JSON-native description of a quote for receipts (no raw payload, no transaction)."""
    return {
        "side": quote.side,
        "mint": quote.token_mint,
        "in_amount": quote.in_amount,
        "expected_out_amount": quote.out_amount,
        "price_impact_pct": quote.price_impact_pct,
        "fee_bps": quote.fee_bps,
        "route_labels": list(quote.route_labels),
        "request_id": quote.request_id,
        "quoted_at": quote.quoted_at,
        "in_usd": quote.in_usd,
        "out_usd": quote.out_usd,
    }


class SolPriceCache:
    """USD per SOL from ``jupiter.sol_price_usd()``, reused for ``ttl_s`` seconds."""

    def __init__(self, jupiter: Any, clock: Clock, ttl_s: float = SOL_PRICE_TTL_S) -> None:
        self.jupiter = jupiter
        self.clock = clock
        self.ttl_s = ttl_s
        self._price: float | None = None
        self._fetched_at = 0.0

    def get(self) -> float:
        """Cached price, refreshed when older than ``ttl_s`` (errors propagate)."""
        now = self.clock.now()
        if self._price is None or now - self._fetched_at > self.ttl_s:
            self._price = float(self.jupiter.sol_price_usd())
            self._fetched_at = now
        return self._price


@dataclass(slots=True)
class _Ticket:
    """A quote this broker issued: what ``execute`` needs to know about it."""

    decimals: int
    quoted_at: float
    spent: bool = False


class UltraBrokerBase:
    """Shared plumbing of :class:`PaperBroker` and :class:`LiveBroker`.

    Both quote through the same Jupiter Ultra ``/order`` call and the same
    checks; subclasses differ only in how a checked quote is executed.
    """

    mode: Mode
    #: Paper accepts Ultra's "Insufficient funds" (amounts are valid); live cannot sign it.
    allow_insufficient_funds: ClassVar[bool] = False

    def __init__(self, jupiter: Any, ledger: Any, settings: Settings, clock: Clock) -> None:
        self.jupiter = jupiter
        self.ledger = ledger
        self.settings = settings
        self.clock = clock
        self._sol_price = SolPriceCache(jupiter, clock)
        self._tickets: dict[str, _Ticket] = {}

    def sol_price_usd(self) -> float:
        """USD per SOL (Jupiter price v3), cached for :data:`SOL_PRICE_TTL_S`."""
        return self._sol_price.get()

    # ------------------------------------------------------------------ quoting
    def _issue_quote(self, side: Side, mint: str, amount_in: int, decimals: int, *, taker: str | None,
                     max_impact_pct: float | None) -> Quote:
        """Fetch an Ultra quote, reject it if unusable, and remember it for :meth:`execute`."""
        input_mint, output_mint = swap_mints(side, mint)
        for name, value, low in (("amount_in", amount_in, 1), ("decimals", decimals, 0)):
            if isinstance(value, bool) or not isinstance(value, int) or value < low:
                raise ValueError(f"{name} must be an int >= {low}, got {value!r}")
        self._before_quote(side)
        quote = self.jupiter.ultra_order(input_mint, output_mint, amount_in, taker=taker)
        limit = self.settings.max_price_impact_pct if max_impact_pct is None else max_impact_pct
        problem = _request_mismatch(quote, input_mint, output_mint, amount_in) or self._quote_problem(quote, limit)
        if problem:
            log.info("quote_rejected mode=%s side=%s mint=%s reason=%s", self.mode, side, mint, problem)
            raise QuoteRejected(problem)
        self._forget_old_tickets()
        self._tickets[quote.request_id] = _Ticket(decimals=decimals, quoted_at=quote.quoted_at)
        return quote

    def _before_quote(self, side: Side) -> None:
        """Hook run after argument validation, before the Ultra request (live: wallet cap)."""

    def _quote_problem(self, quote: Quote, max_impact_pct: float) -> str | None:
        """Why ``quote`` must not be traded, or None when it is acceptable.

        Every quote: a requestId, positive amounts, no disqualifying Ultra error, impact within
        ``max_impact_pct``. BUYS also fail closed on what a sell must never be trapped by: an
        unknown impact, an all-in USD value loss above the cap (+ the platform fee), and a signed
        minimum output more than ``MAX_SLIPPAGE_PCT`` below the quote.
        """
        if not quote.request_id:
            return "Ultra returned no requestId"
        if quote.in_amount <= 0 or quote.out_amount <= 0:
            return f"Ultra quoted a non-positive amount (in {quote.in_amount}, out {quote.out_amount})"
        if quote.error and not (self.allow_insufficient_funds and quote.is_insufficient_funds):
            return f"Ultra error: {quote.error}"
        if quote.price_impact_pct > max_impact_pct:
            return f"price impact {quote.price_impact_pct:.2f}% > max {max_impact_pct:.2f}%"
        if quote.side == "buy":
            return self._buy_problem(quote, max_impact_pct)
        return None

    def _buy_problem(self, quote: Quote, max_impact_pct: float) -> str | None:
        if not quote.price_impact_known:
            return "price impact unknown (Ultra sent no priceImpactPct/priceImpact)"
        loss = quote.usd_value_loss_pct
        loss_cap = max_impact_pct + quote.fee_bps / 100.0
        if loss is not None and loss > loss_cap:
            return f"USD value lost {loss:.2f}% > max {loss_cap:.2f}% (impact cap + platform fee)"
        slip_cap = self.settings.max_slippage_pct
        slippage = quote.slippage_bps / 100.0
        if quote.other_amount_threshold is not None:
            slippage = max(slippage, (quote.out_amount - quote.other_amount_threshold) / quote.out_amount * 100.0)
        if slippage > slip_cap:
            return f"slippage {slippage:.2f}% > MAX_SLIPPAGE_PCT {slip_cap:.2f}% (Ultra's signed minimum output)"
        return None

    def _forget_old_tickets(self) -> None:
        horizon = self.clock.now() - self.settings.quote_max_age_s * _TICKET_TTL_FACTOR
        for request_id in [rid for rid, t in self._tickets.items() if t.quoted_at < horizon]:
            del self._tickets[request_id]

    # ------------------------------------------------------------------ execution
    def _prepare_execution(self, quote: Quote, position: Position | None) -> tuple[_Ticket, float]:
        """Validate ``quote`` for execution; return its ticket and the SOL/USD price for the fill.

        Raises ``QuoteRejected`` (stale, foreign, already used, wrong position,
        no SOL price). Nothing is changed or sent here.
        """
        age = self.clock.now() - quote.quoted_at
        if age > self.settings.quote_max_age_s:
            raise QuoteRejected(f"stale quote: {age:.1f}s old > QUOTE_MAX_AGE_S {self.settings.quote_max_age_s:g}s")
        ticket = self._tickets.get(quote.request_id or "")
        if ticket is None:
            raise QuoteRejected("quote was not issued by this broker; call quote() first")
        if ticket.spent:
            raise QuoteRejected("quote already executed; never re-sent - re-quote instead")
        if position is not None:
            self._check_position(quote, position, ticket)
        return ticket, self._fill_sol_usd(quote)

    @staticmethod
    def _check_position(quote: Quote, position: Position, ticket: _Ticket) -> None:
        if position.mint != quote.token_mint:
            raise QuoteRejected(f"position {position.id} is for {position.mint}, quote is for {quote.token_mint}")
        if not position.is_open:
            raise QuoteRejected(f"position {position.id} is closed")
        if position.token_decimals != ticket.decimals:
            raise QuoteRejected(f"decimals mismatch: position {position.token_decimals}, quote {ticket.decimals}")

    def _fill_sol_usd(self, quote: Quote) -> float:
        """SOL/USD for the fill: Jupiter price v3 (cached), else the quote's own valuation."""
        try:
            return self.sol_price_usd()
        except (HttpError, JupiterError) as exc:
            implied = implied_sol_usd(quote)
            if implied is None:
                raise QuoteRejected(f"no SOL/USD price available: {exc}") from exc
            log.warning("sol_price_fallback source=quote error=%s", exc)
            return implied

    def _new_fill(self, quote: Quote, *, sol_lamports: int, token_amount: int, decimals: int, sol_usd: float,
                  fees_lamports: int, rent_lamports: int, signature: str | None, position: Position | None,
                  symbol: str) -> Fill:
        """A :class:`Fill` for ``quote`` with the given realised amounts (not yet recorded)."""
        return Fill(
            id=new_id("fill"),
            mode=self.mode,
            side=quote.side,
            mint=quote.token_mint,
            sol_lamports=sol_lamports,
            token_amount=token_amount,
            token_decimals=decimals,
            price_usd=effective_price_usd(sol_lamports, token_amount, decimals, sol_usd),
            sol_usd=sol_usd,
            fees_lamports=fees_lamports,
            platform_fee_bps=quote.fee_bps,
            price_impact_pct=quote.price_impact_pct,
            signature=signature,
            request_id=quote.request_id,
            ts=self.clock.now(),
            position_id=position.id if position is not None else None,
            rent_lamports=rent_lamports,
            expected_out_amount=quote.out_amount,
            symbol=symbol or (position.symbol if position is not None else ""),
        )

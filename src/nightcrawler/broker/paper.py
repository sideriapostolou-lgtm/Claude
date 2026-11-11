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
  - BUY: require ``sol_lamports - SOL_RESERVE - network fee - rent(if new) >=
    in_amount`` else ``InsufficientBalance``. Debit ``in_amount + network fee +
    rent`` where rent = :func:`~nightcrawler.broker.base.token_rent_lamports`
    (the rule live books too): Ultra's ``rentFeeLamports`` or
    ``TOKEN_ACCOUNT_RENT_LAMPORTS`` when the virtual wallet has no account for
    the mint yet (no tokens and no rent locked), else 0. Credit the quote's
    ``out_amount`` minus ``PAPER_SLIPPAGE_BPS``.
  - SELL: require token balance >= ``in_amount``. Debit tokens, credit the
    quote's ``out_amount`` (minus ``PAPER_SLIPPAGE_BPS``) minus the network fee.
    NO rent refund, also on a full exit (``Fill.rent_lamports`` 0): like live,
    where Ultra's sell leaves the emptied token account open, the deposit stays
    locked in ``paper.rent`` and a later buy of that mint pays no new rent.
  - Network fee: ``NETWORK_FEE_SOL`` is the FLOOR. When ``SOLANA_RPC_URL`` is a
    Helius host and an ``rpc`` is given, Helius ``getPriorityFeeEstimate``
    (PumpSwap + Jupiter program accounts, every level) is asked at most once per
    :data:`PRIORITY_FEE_REFRESH_S`; the fee is its ``high`` level x
    :data:`SWAP_COMPUTE_UNITS` + :data:`BASE_FEE_LAMPORTS`, never below the floor,
    capped at :data:`MAX_PAPER_NETWORK_FEE_LAMPORTS`. Any error -> the floor
    (until the next refresh).
  - ``Fill``: ``mode="paper"``, ``signature=None``, ``fees_lamports`` = that
    network fee, ``platform_fee_bps = quote.fee_bps``,
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

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from nightcrawler.broker.base import (
    SOL_PRICE_TTL_S,
    InsufficientBalance,
    UltraBrokerBase,
    token_rent_lamports,
)
from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import (
    LAMPORTS_PER_SOL,
    Balances,
    Fill,
    Mode,
    Position,
    Quote,
    Side,
    lamports_to_sol,
)
from nightcrawler.sources.solana_rpc import SWAP_FEE_ACCOUNT_KEYS, is_helius_url

__all__ = ["PaperBroker", "SOL_PRICE_TTL_S", "paper_out_amount", "network_fee_from_priority",
           "PRIORITY_FEE_REFRESH_S", "SWAP_COMPUTE_UNITS", "BASE_FEE_LAMPORTS", "MAX_PAPER_NETWORK_FEE_LAMPORTS"]

log = get_logger(__name__)

KV_SOL = "paper.sol_lamports"
KV_TOKENS = "paper.tokens"
KV_RENT = "paper.rent"
KV_START_LAMPORTS = "paper.start_lamports"
KV_START_SOL_USD = "paper.start_sol_usd"

#: Helius priority fees are asked at most this often (seconds), also after an error.
PRIORITY_FEE_REFRESH_S = 300.0
#: The priority-fee level a paper swap pays (conservative: live lands most swaps for less).
PRIORITY_FEE_LEVEL = "high"
#: Compute units assumed per swap (Ultra/Jupiter swaps use roughly 150k-400k).
SWAP_COMPUTE_UNITS = 300_000
#: Solana base fee for the one signature of a swap.
BASE_FEE_LAMPORTS = 5_000
#: Sanity cap on an estimated paper fee (0.01 SOL, NETWORK_FEE_SOL's own upper bound).
MAX_PAPER_NETWORK_FEE_LAMPORTS = 10_000_000


def _sol(lamports: int) -> str:
    return f"{lamports_to_sol(lamports):.6f} SOL"


def network_fee_from_priority(micro_lamports_per_cu: float) -> int:
    """Network fee of one swap paying ``micro_lamports_per_cu`` for :data:`SWAP_COMPUTE_UNITS`
    plus the base fee, rounded up, capped at :data:`MAX_PAPER_NETWORK_FEE_LAMPORTS`."""
    fee = BASE_FEE_LAMPORTS + math.ceil(micro_lamports_per_cu * SWAP_COMPUTE_UNITS / 1_000_000)
    return min(fee, MAX_PAPER_NETWORK_FEE_LAMPORTS)


class _PaperNetworkFee:
    """``NETWORK_FEE_SOL`` as a floor, raised to the Helius ``high`` priority-fee estimate (see module doc)."""

    def __init__(self, settings: Settings, clock: Clock, rpc: Any | None) -> None:
        self.settings = settings
        self.clock = clock
        self.rpc = rpc if rpc is not None and is_helius_url(settings.solana_rpc_url) else None
        self._estimate: int | None = None
        self._asked_at: float | None = None

    def lamports(self) -> int:
        floor = self.settings.network_fee_lamports
        if self.rpc is None:
            return floor
        now = self.clock.now()
        if self._asked_at is None or now - self._asked_at >= PRIORITY_FEE_REFRESH_S:
            self._asked_at = now
            self._estimate = self._ask(self.rpc)
        return floor if self._estimate is None else max(floor, self._estimate)

    def _ask(self, rpc: Any) -> int | None:
        try:
            level = float(rpc.priority_fee_levels(SWAP_FEE_ACCOUNT_KEYS)[PRIORITY_FEE_LEVEL])
            if not math.isfinite(level) or level < 0:
                raise ValueError(f"unusable {PRIORITY_FEE_LEVEL} level {level!r}")
        except Exception as exc:  # any failure: the NETWORK_FEE_SOL floor until the next refresh
            log.warning("paper_priority_fee_unavailable error=%s: %s using=network_fee_sol", type(exc).__name__, exc)
            return None
        fee = network_fee_from_priority(level)
        log.info("paper_priority_fee level=%s micro_lamports_per_cu=%.1f fee_lamports=%d floor_lamports=%d",
                 PRIORITY_FEE_LEVEL, level, fee, self.settings.network_fee_lamports)
        return fee


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

    def has_account(self, mint: str) -> bool:
        """True when the virtual wallet holds a token account for ``mint`` (tokens or locked rent)."""
        return self.tokens.get(mint, 0) > 0 or self.rent.get(mint, 0) > 0

    def buy(self, quote: Quote, received: int, fee: int, reserve: int) -> int:
        """Spend ``in_amount`` + ``fee`` (+ rent when the buy opens the account); return the rent charged."""
        mint, cost = quote.token_mint, quote.in_amount
        rent = token_rent_lamports(quote, account_open=self.has_account(mint))
        needed = cost + fee + rent + reserve
        if self.sol_lamports < needed:
            raise InsufficientBalance(
                f"need {_sol(needed)} (swap {_sol(cost)} + fee {_sol(fee)} + rent {_sol(rent)} + "
                f"reserve {_sol(reserve)}), have {_sol(self.sol_lamports)}")
        self.sol_lamports -= cost + fee + rent
        self.tokens[mint] = self.tokens.get(mint, 0) + received
        if rent:
            self.rent[mint] = self.rent.get(mint, 0) + rent
        return rent

    def sell(self, quote: Quote, proceeds: int, fee: int) -> int:
        """Sell ``in_amount`` tokens for ``proceeds`` minus ``fee``; return the rent change (always 0:
        like Ultra, a sell never closes the token account, so its rent stays locked in ``rent``)."""
        mint, amount = quote.token_mint, quote.in_amount
        held = self.tokens.get(mint, 0)
        if held < amount:
            raise InsufficientBalance(f"need {amount} base units of {mint}, have {held}")
        new_sol = self.sol_lamports + proceeds - fee
        if new_sol < 0:
            raise InsufficientBalance(f"not enough SOL for the network fee ({_sol(fee)})")
        self.sol_lamports = new_sol
        if held - amount:
            self.tokens[mint] = held - amount
        else:
            self.tokens.pop(mint, None)
        return token_rent_lamports(quote, account_open=self.has_account(mint))


class PaperBroker(UltraBrokerBase):
    """Virtual wallet + live quotes. Implements :class:`nightcrawler.broker.base.Broker`."""

    mode: Mode = "paper"
    allow_insufficient_funds = True

    def __init__(self, jupiter: Any, ledger: Any, settings: Settings, clock: Clock,
                 taker: str | None = None, rpc: Any | None = None) -> None:
        """``jupiter``: :class:`~nightcrawler.sources.jupiter.JupiterClient`;
        ``ledger``: :class:`~nightcrawler.ledger.Ledger`; ``taker``: optional
        bot wallet pubkey to quote with (more realistic routing); ``rpc``: optional
        :class:`~nightcrawler.sources.solana_rpc.SolanaRpc` for live priority fees
        (used only when ``SOLANA_RPC_URL`` is a Helius host)."""
        super().__init__(jupiter, ledger, settings, clock)
        self.taker = taker
        self._network_fee = _PaperNetworkFee(settings, clock, rpc)

    def network_fee_lamports(self) -> int:
        """Network fee a paper swap pays now (``NETWORK_FEE_SOL`` floor, see the module rules)."""
        return self._network_fee.lamports()

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
        fee = self.network_fee_lamports()
        received = paper_out_amount(quote.out_amount, self.settings.paper_slippage_bps)
        with self.ledger.transaction():
            wallet = _PaperWallet.load(self.ledger)
            if wallet is None:  # _ensure_wallet() stored it above; never fill without one
                raise AttributeError("paper wallet missing from the ledger")
            if quote.side == "buy":
                rent = wallet.buy(quote, received, fee, self.settings.sol_reserve_lamports)
                sol_lamports, token_amount = quote.in_amount, received
            else:
                rent = wallet.sell(quote, received, fee)
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

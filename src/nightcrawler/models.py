"""Shared plain data models (dataclasses with slots). No IO here.

UNITS CONVENTIONS (the single source of truth; every module follows these)
==========================================================================

Time
    * Timestamps: epoch **seconds** UTC as ``float`` (``ts``, ``*_at``).
    * Candle ``ts``: ``int`` epoch seconds of the candle's **open** (start of
      the interval). A 1-minute candle with ``ts=T`` is closed once
      ``now >= T + 60``.
    * Durations carry the unit in the name: ``*_s``, ``*_min``, ``*_h``,
      ``latency_ms``.

Money
    * SOL amounts in state, ledger and fills: ``int`` **lamports**
      (``*_lamports``; 1 SOL = 1_000_000_000 lamports). SOL ``float`` appears
      only in Settings (``sol_reserve``, ``network_fee_sol``) and display.
    * Token amounts: ``int`` **base units** (``token_amount``) plus
      ``token_decimals``; whole-token ("UI") floats only for display.
    * USD: ``float`` dollars (``*_usd``). Prices are USD per **whole** token
      (``price_usd``) or USD per SOL (``sol_usd``).

Ratios
    * Fields named ``*_pct`` in models and source outputs are **percent**
      (0-100 scale; ``5.0`` means 5 %). This matches every upstream API
      (RugCheck ``pct``, Jupiter ``*Percentage``, DexScreener ``priceChange``).
      ``price_change_*`` fields are also percent.
    * ``price_impact_pct``: percent, stored as a non-negative **magnitude of
      adverse impact** (see :class:`Quote`).
    * ``confidence`` and ``fraction`` fields are fractions in ``[0, 1]``.
    * Fees in basis points are ``int`` ``*_bps`` (100 bps = 1 %).
    * EXCEPTION (Settings only): the strategy/risk knobs whose env names the
      owner fixed - ``POSITION_PCT, DAILY_LOSS_LIMIT_PCT,
      MAX_DRAWDOWN_HALT_PCT, DIP_PCT, TAKE_PROFIT_PCT, TRAIL_PCT,
      STOP_LOSS_PCT`` - are **fractions** (0.20 = 20 %), mirrored as such in
      :class:`StrategyParams`. ``MAX_PRICE_IMPACT_PCT`` and all ``COCOON_*_PCT``
      / ``RADAR_*_PCT`` settings are percent. ``config.py`` validates both
      families so a wrong scale fails loudly.

Serialization
    Every model has ``to_dict()`` (JSON-native, via :func:`to_jsonable`) and
    ``from_dict()`` (ignores unknown keys, rebuilds nested models). Receipts
    store ``to_dict()`` output.
"""

from __future__ import annotations

import dataclasses
import enum
import math
import types
import typing
import uuid
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, ClassVar, Literal, TypeVar, Union, get_args, get_origin

__all__ = [
    "SOL_MINT",
    "LAMPORTS_PER_SOL",
    "SOL_DECIMALS",
    "TOKEN_ACCOUNT_RENT_LAMPORTS",
    "TOKEN_PROGRAM_ID",
    "TOKEN_2022_PROGRAM_ID",
    "Mode",
    "Side",
    "SignalKind",
    "VerdictSource",
    "DecisionAction",
    "ReceiptKind",
    "KillMode",
    "to_jsonable",
    "new_id",
    "lamports_to_sol",
    "sol_to_lamports",
    "base_to_ui",
    "ui_to_base",
    "effective_price_usd",
    "Candle",
    "TokenCandidate",
    "MarketSnapshot",
    "SafetyReport",
    "RadarSignal",
    "Signal",
    "Verdict",
    "Quote",
    "Fill",
    "Position",
    "Decision",
    "Receipt",
    "EquityPoint",
    "Balances",
    "StrategyParams",
]

# --------------------------------------------------------------------------- constants

SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS_PER_SOL = 1_000_000_000
SOL_DECIMALS = 9
#: Rent-exempt deposit for a 165-byte SPL token account. Token-2022 accounts
#: with extensions can be slightly larger; this is the paper-mode model value.
TOKEN_ACCOUNT_RENT_LAMPORTS = 2_039_280
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# --------------------------------------------------------------------------- literal types

Mode = Literal["paper", "live"]
Side = Literal["buy", "sell"]
SignalKind = Literal["enter", "exit", "none"]
VerdictSource = Literal["claude", "rules", "error"]
KillMode = Literal["off", "stop", "sell_all"]

#: Every value the engine may write into ``Decision.action``.
DecisionAction = Literal[
    "reject_prefilter",  # crawler cheap prefilter said no (usually not receipted; too noisy)
    "reject_cocoon",  # SafetyReport.passed is False
    "watch",  # added to watchlist
    "unwatch",  # removed from watchlist (expired / fell out of window)
    "no_signal",  # evaluated, entry_signal returned 'none' (only logged when notable)
    "reject_radar",  # RadarSignal flagged or errored at entry time
    "reject_judge",  # Verdict 'no' in required mode
    "reject_risk",  # RiskManager.can_open False or size 0
    "reject_quote",  # broker refused the quote (impact, error, stale)
    "enter",  # buy executed (Fill follows)
    "exit",  # full sell executed
    "exit_partial",  # partial take-profit sell executed
    "hold",  # explicit hold (e.g. sell skipped because quote failed)
    "kill",  # kill switch acted
    "error",  # stage failed; reason holds the exception summary
]

#: Every value allowed for ``Receipt.kind``.
ReceiptKind = Literal[
    "boot",  # engine start: version, mode, public settings
    "decision",  # payload = Decision.to_dict()
    "fill",  # payload = Fill.to_dict() (receipt_hash None inside the payload)
    "swap_failed",  # live swap failed / aborted; payload has quote summary + error
    "error",  # stage exception summary
    "kill",  # kill switch change / sell_all executed
    "halt",  # risk halt engaged (drawdown)
    "reset",  # manual halt reset
    "note",  # free-form operator note
]

# --------------------------------------------------------------------------- helpers


def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / tuples / sets / paths / enums to JSON-native values.

    Dict keys become ``str``. Non-finite floats are kept (the hashing layer
    rejects them for receipts). Unknown objects are returned unchanged.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, PurePath):
        return str(obj)
    return obj


def new_id(prefix: str) -> str:
    """Random unique id like ``fill_3f2a9c1d0b7e4a55`` (prefix + 16 hex chars)."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def lamports_to_sol(lamports: int) -> float:
    return lamports / LAMPORTS_PER_SOL


def sol_to_lamports(sol: float) -> int:
    """SOL float -> int lamports, rounded to the nearest lamport."""
    return int(round(sol * LAMPORTS_PER_SOL))


def base_to_ui(amount: int, decimals: int) -> float:
    """Token base units -> whole tokens (float, display only)."""
    return amount / (10**decimals)


def ui_to_base(ui_amount: float, decimals: int) -> int:
    """Whole tokens -> base units, rounded down (never overstate holdings)."""
    return int(math.floor(ui_amount * (10**decimals) + 1e-9))


def effective_price_usd(sol_lamports: int, token_amount: int, token_decimals: int, sol_usd: float) -> float:
    """USD per whole token implied by a swap of ``sol_lamports`` <-> ``token_amount``.

    Returns 0.0 when ``token_amount`` is 0.
    """
    if token_amount <= 0:
        return 0.0
    return (sol_lamports / LAMPORTS_PER_SOL) * sol_usd / (token_amount / 10**token_decimals)


M = TypeVar("M", bound="_Model")
_HINTS: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    h = _HINTS.get(cls)
    if h is None:
        h = typing.get_type_hints(cls)
        _HINTS[cls] = h
    return h


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(tp, type) and dataclasses.is_dataclass(tp) and isinstance(value, dict):
        return tp.from_dict(value)  # type: ignore[attr-defined]
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        for arg in get_args(tp):
            if arg is type(None):
                continue
            if isinstance(arg, type) and dataclasses.is_dataclass(arg) and isinstance(value, dict):
                return arg.from_dict(value)  # type: ignore[attr-defined]
        return value
    if origin is list:
        args = get_args(tp)
        if args and isinstance(args[0], type) and dataclasses.is_dataclass(args[0]):
            return [args[0].from_dict(v) if isinstance(v, dict) else v for v in value]  # type: ignore[attr-defined]
        return list(value)
    return value


class _Model:
    """Mixin: ``to_dict()`` / ``from_dict()`` for slotted dataclasses."""

    __slots__ = ()

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

    @classmethod
    def from_dict(cls: type[M], data: dict[str, Any]) -> M:
        hints = _hints(cls)
        kwargs = {}
        for f in dataclasses.fields(cls):  # type: ignore[arg-type]
            if f.name in data:
                kwargs[f.name] = _convert(hints.get(f.name), data[f.name])
        return cls(**kwargs)


# --------------------------------------------------------------------------- market data


@dataclass(slots=True)
class Candle(_Model):
    """OHLCV candle. ``ts`` = int epoch seconds of the interval **open**.

    ``o, h, l, c`` are USD per whole token; ``v`` is traded volume in USD.
    Source rows (GeckoTerminal, backtest files) are ``[ts, o, h, l, c, v]``.
    """

    ts: int
    o: float
    h: float
    l: float  # noqa: E741 - conventional OHLC name
    c: float
    v: float = 0.0

    @classmethod
    def from_row(cls, row: typing.Sequence[Any]) -> "Candle":
        """Build from ``[ts, o, h, l, c, v]`` (v optional). Values may be str/int/float."""
        v = float(row[5]) if len(row) > 5 and row[5] is not None else 0.0
        return cls(int(float(row[0])), float(row[1]), float(row[2]), float(row[3]), float(row[4]), v)

    def to_row(self) -> list[float]:
        return [self.ts, self.o, self.h, self.l, self.c, self.v]

    def is_closed(self, now: float, interval_s: int = 60) -> bool:
        """True once the interval has ended: ``ts + interval_s <= now``."""
        return self.ts + interval_s <= now

    @property
    def green(self) -> bool:
        return self.c > self.o


@dataclass(slots=True)
class TokenCandidate(_Model):
    """A token discovered by the crawler (pre-safety).

    Unknown values are ``None`` (never 0) so filters can tell "missing" from
    "zero". ``pool`` is the main pool/pair address used for candles/trades.
    ``dex`` is DexScreener-style: ``pumpfun`` (bonding curve), ``pumpswap``,
    ``raydium``, ``meteora``, ``meteoradbc``, ``orca`` or another lowercase id.
    ``sources`` lists every feed that reported the mint, e.g.
    ``["jupiter_recent", "gt_new_pools", "dexscreener_boost"]``.
    ``age_min`` = minutes since ``created_at`` (first pool creation) measured
    at ``discovered_at``. ``audit`` / ``stats`` are Jupiter tokens/v2 dicts as
    returned (``audit.isSus``, ``audit.devMints``, ``stats['5m'|'1h'|...]``).
    ``socials``: ``{"twitter": url, "website": url, "telegram": url}`` (present keys only).
    ``raw``: small source references only (ids, urls) - never whole payloads.
    """

    mint: str
    symbol: str = ""
    name: str = ""
    pool: str | None = None
    dex: str | None = None
    sources: list[str] = field(default_factory=list)
    created_at: float | None = None
    age_min: float | None = None
    mcap_usd: float | None = None
    liquidity_usd: float | None = None
    price_usd: float | None = None
    fdv_usd: float | None = None
    holder_count: int | None = None
    decimals: int | None = None
    dev: str | None = None
    launchpad: str | None = None
    graduated: bool | None = None
    organic_score: float | None = None
    paid_promo: bool = False
    audit: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    socials: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    discovered_at: float | None = None


@dataclass(slots=True)
class MarketSnapshot(_Model):
    """Point-in-time market stats for one token's top pair (DexScreener /tokens/v1).

    ``price_change_m5/h1`` are percent. Counts are numbers of transactions in
    the window. ``liquidity_usd`` is ``None`` for pump.fun bonding-curve pairs.
    """

    mint: str
    ts: float
    price_usd: float | None
    mcap_usd: float | None
    liquidity_usd: float | None
    buys_m5: int = 0
    sells_m5: int = 0
    buys_h1: int = 0
    sells_h1: int = 0
    volume_m5: float = 0.0
    volume_h1: float = 0.0
    price_change_m5: float | None = None
    price_change_h1: float | None = None
    pool: str | None = None
    dex: str | None = None
    fdv_usd: float | None = None
    pair_created_at: float | None = None
    source: str = "dexscreener"

    @property
    def buy_sell_ratio_m5(self) -> float | None:
        """buys/sells over 5 min; sells==0 counts as 1; None when no trades at all."""
        if self.buys_m5 == 0 and self.sells_m5 == 0:
            return None
        return self.buys_m5 / max(self.sells_m5, 1)


# --------------------------------------------------------------------------- safety & signals


@dataclass(slots=True)
class SafetyReport(_Model):
    """Cocoon verdict for one mint.

    ``passed`` is True only if there are no ``hard_fail_reasons`` AND no
    ``unverified`` sources (fail closed). ``metrics`` suggested keys (all
    optional; percent where ``_pct``): ``top10_pct, max_holder_pct,
    creator_pct, insider_pct, graph_insiders, dev_mints, lp_locked_pct,
    holder_count, rugcheck_score_normalised, mint_authority, freeze_authority,
    extensions, shield_warnings``.
    ``top_holders``: owner wallets of the largest holders, AMM/curve/locker
    accounts excluded, largest first. ``insiders``: wallets RugCheck flags as
    insiders. ``creator``: creator/dev wallet. Radar uses these three.
    """

    mint: str
    passed: bool
    hard_fail_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    checked_at: float = 0.0
    unverified: list[str] = field(default_factory=list)
    creator: str | None = None
    top_holders: list[str] = field(default_factory=list)
    insiders: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RadarSignal(_Model):
    """Big-sell radar result for one pool over the last ``window_min`` minutes.

    ``big_sells_usd``: sum of sells >= ``RADAR_MIN_TRADE_USD`` in the window.
    ``insider_sell_usd``: the part of that sold by creator / top holders / insiders.
    ``top_holder_sells``: ``[{"wallet", "usd", "ts", "tx_hash", "role"}]`` with
    role in ``creator|top_holder|insider``.
    ``error``: set when the scan could not run (source down). Callers treat an
    error as a REJECTION at entry time (fail closed) but NOT as an exit trigger.
    """

    mint: str
    window_min: float
    big_sells_usd: float = 0.0
    insider_sell_usd: float = 0.0
    creator_sold: bool = False
    top_holder_sells: list[dict[str, Any]] = field(default_factory=list)
    flagged: bool = False
    reasons: list[str] = field(default_factory=list)
    checked_at: float = 0.0
    trades_seen: int = 0
    liquidity_usd: float | None = None
    error: str | None = None


@dataclass(slots=True)
class Signal(_Model):
    """Output of the pure strategy functions.

    ``confidence`` in [0, 1] (heuristic). For exits, ``fraction`` is the share
    of the position's CURRENT ``token_amount`` to sell (``1.0`` = everything,
    partial take-profit uses ``PARTIAL_TP_FRACTION``).
    """

    kind: SignalKind
    reason: str
    confidence: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    fraction: float = 1.0


@dataclass(slots=True)
class Verdict(_Model):
    """AI judge ("Jev") answer. ``confidence`` in [0, 1]; ``latency_ms`` int;
    ``cost_usd`` estimated from token usage; ``source`` is ``claude`` (model
    answered), ``rules`` (judge off: rules-only yes) or ``error`` (refusal,
    timeout, API error, budget exceeded -> always decision ``no``)."""

    decision: Literal["yes", "no"]
    confidence: float
    reasons: list[str]
    model: str
    latency_ms: int
    cost_usd: float
    source: VerdictSource
    cached: bool = False
    request_id: str | None = None
    error: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision == "yes"


# --------------------------------------------------------------------------- execution


@dataclass(slots=True)
class Quote(_Model):
    """A Jupiter Ultra ``/order`` quote for an exact input amount.

    * ``side='buy'``: input = SOL (lamports), output = token (base units).
      ``side='sell'``: input = token (base units), output = SOL (lamports).
    * ``out_amount`` already nets pool fees and the Ultra platform fee
      (``fee_bps``, typically 10). Paper fills use it exactly.
    * ``price_impact_pct``: percent, **non-negative magnitude**:
      ``abs(float(priceImpactPct)) * 100``. Ultra reports adverse impact as a
      negative fraction (verified 2026-10-08: buying HIGGS for 0.1 SOL gave
      ``priceImpactPct="-0.0219"`` with ``outUsdValue`` 2.2 % below
      ``inUsdValue``); older endpoints used positive numbers. Taking the
      magnitude is conservative. When Ultra sends no usable impact it is 0.0
      with ``price_impact_known=False`` (fail closed: never read as "no impact").
    * ``in_usd`` / ``out_usd``: Ultra ``inUsdValue`` / ``outUsdValue``.
    * ``transaction_b64``: base64 unsigned transaction, ``None`` when Ultra
      returned null/"" (no taker, or taker lacks funds).
    * ``error`` / ``error_code``: Ultra ``errorMessage``/``error`` and
      ``errorCode``. ``"Insufficient funds"`` still carries valid amounts.
    * ``*_fee_lamports``: Ultra's reported signature / priority / rent fees.
    * ``raw``: the full Ultra response (kept for receipts/debugging).
    """

    side: Side
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    price_impact_pct: float
    fee_bps: int
    route_labels: list[str]
    request_id: str | None
    transaction_b64: str | None
    quoted_at: float
    in_usd: float | None
    out_usd: float | None
    slippage_bps: int = 0
    other_amount_threshold: int | None = None
    signature_fee_lamports: int = 0
    prioritization_fee_lamports: int = 0
    rent_fee_lamports: int = 0
    router: str | None = None
    error: str | None = None
    error_code: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    #: False when Ultra reported no usable impact (both fields missing or non-finite);
    #: ``price_impact_pct`` is then 0.0 and MUST NOT be trusted (brokers refuse such buys).
    price_impact_known: bool = True

    @property
    def token_mint(self) -> str:
        """The non-SOL side of the swap."""
        return self.output_mint if self.side == "buy" else self.input_mint

    @property
    def is_insufficient_funds(self) -> bool:
        return bool(self.error) and "insufficient funds" in str(self.error).lower()

    @property
    def usd_value_loss_pct(self) -> float | None:
        """All-in percent of USD value lost in the swap (fees + impact), or None."""
        if not self.in_usd or self.out_usd is None:
            return None
        return (self.in_usd - self.out_usd) / self.in_usd * 100.0

    @property
    def executable(self) -> bool:
        """True when a signable transaction is present and Ultra reported no error."""
        return bool(self.transaction_b64) and not self.error


@dataclass(slots=True)
class Fill(_Model):
    """One executed (paper or live) swap.

    * ``sol_lamports``: buy -> SOL lamports put INTO the swap (quote in_amount);
      sell -> SOL lamports received FROM the swap. Always >= 0.
    * ``token_amount``: buy -> tokens received; sell -> tokens sold (base units).
    * ``price_usd``: effective USD per whole token =
      :func:`effective_price_usd` (pool + platform fees included, network fees
      excluded).
    * ``fees_lamports``: network fees only (signature + priority), lamports.
    * ``rent_lamports``: token-account rent change: ``+2_039_280`` when the
      buy created the account, negative when a full exit refunded it, else 0.
    * ``expected_out_amount``: the quote's ``out_amount`` (live: compare with
      the actual result to measure slippage).
    * ``receipt_hash``: hash of the 'fill' receipt (set by the ledger).
    """

    id: str
    mode: Mode
    side: Side
    mint: str
    sol_lamports: int
    token_amount: int
    token_decimals: int
    price_usd: float
    sol_usd: float
    fees_lamports: int
    platform_fee_bps: int
    price_impact_pct: float
    signature: str | None
    request_id: str | None
    ts: float
    receipt_hash: str | None = None
    position_id: str | None = None
    rent_lamports: int = 0
    expected_out_amount: int | None = None
    symbol: str = ""

    def sol_delta_lamports(self) -> int:
        """Net change of the wallet's SOL caused by this fill (negative for buys)."""
        swap = self.sol_lamports if self.side == "sell" else -self.sol_lamports
        return swap - self.fees_lamports - self.rent_lamports

    def token_delta(self) -> int:
        """Net change of the token balance (base units)."""
        return self.token_amount if self.side == "buy" else -self.token_amount


@dataclass(slots=True)
class Position(_Model):
    """An open or closed position in one mint.

    * ``token_amount``: base units currently held; ``initial_token_amount``:
      total bought.
    * ``cost_lamports``: sum of buy fills' ``sol_lamports``.
    * ``proceeds_lamports``: sum of sell fills' ``sol_lamports``.
    * ``fees_lamports``: sum of network fees of all fills.
    * ``rent_lamports``: rent currently locked for the token account (net).
    * ``entry_price_usd``: average USD per whole token over buy fills.
    * ``peak_price_usd``: highest marked price since open (trailing stop).
    * ``status``: ``open`` | ``closed``; ``exit_reason`` e.g. ``stop_loss``,
      ``take_profit_partial``, ``trailing_stop``, ``time_stop``, ``radar``,
      ``kill_switch``, ``manual``.
    * ``mode``: ``paper`` | ``live`` - the wallet the tokens are in (from the
      opening fill). A paper position is never traded or counted by a live engine
      and vice versa. ``None`` only on rows written before this field existed;
      the ledger infers it from the entry fill when loading.
    """

    id: str
    mint: str
    symbol: str
    pool: str | None
    opened_at: float
    token_decimals: int
    entry_fill_ids: list[str] = field(default_factory=list)
    exit_fill_ids: list[str] = field(default_factory=list)
    token_amount: int = 0
    initial_token_amount: int = 0
    cost_lamports: int = 0
    proceeds_lamports: int = 0
    fees_lamports: int = 0
    rent_lamports: int = 0
    entry_price_usd: float = 0.0
    peak_price_usd: float = 0.0
    last_price_usd: float | None = None
    last_marked_at: float | None = None
    partial_taken: bool = False
    status: Literal["open", "closed"] = "open"
    exit_reason: str | None = None
    closed_at: float | None = None
    mode: Mode | None = None

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    def value_lamports(self, price_usd: float, sol_usd: float) -> int:
        """Mark-to-market value of the remaining tokens in lamports (mid price, no fees)."""
        if sol_usd <= 0 or self.token_amount <= 0:
            return 0
        usd = base_to_ui(self.token_amount, self.token_decimals) * price_usd
        return int(usd / sol_usd * LAMPORTS_PER_SOL)

    def pnl_lamports(self, price_usd: float | None = None, sol_usd: float | None = None) -> int:
        """Total P&L in lamports = proceeds + marked value - cost - fees - locked rent.

        For a closed position (or when no price is given) the marked value is 0.
        Locked rent counts as a cost until it is refunded (conservative).
        """
        value = 0
        if self.token_amount > 0 and price_usd is not None and sol_usd:
            value = self.value_lamports(price_usd, sol_usd)
        return self.proceeds_lamports + value - self.cost_lamports - self.fees_lamports - self.rent_lamports


# --------------------------------------------------------------------------- records


@dataclass(slots=True)
class Decision(_Model):
    """A decision point the engine wants on the record (see :data:`DecisionAction`).

    ``inputs``: the exact numbers the decision used (signal metrics, snapshot,
    safety summary, size, quote summary) - JSON-native, small.
    """

    ts: float
    mint: str
    action: DecisionAction
    reason: str
    inputs: dict[str, Any] = field(default_factory=dict)
    verdict: Verdict | None = None
    symbol: str = ""
    receipt_hash: str | None = None


@dataclass(slots=True)
class Receipt(_Model):
    """One link of the hash chain (see :mod:`nightcrawler.hashing`)."""

    seq: int
    ts: float
    kind: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


@dataclass(slots=True)
class EquityPoint(_Model):
    """Equity snapshot for risk limits and the dashboard curve.

    ``equity_lamports`` = ``sol_lamports`` (free SOL incl. reserve) +
    ``positions_value_lamports`` (open positions marked at mid price).
    """

    ts: float
    equity_lamports: int
    sol_usd: float
    equity_usd: float
    sol_lamports: int = 0
    positions_value_lamports: int = 0
    open_positions: int = 0
    mode: Mode = "paper"


@dataclass(slots=True)
class Balances(_Model):
    """Wallet balances: SOL in lamports and token base units by mint."""

    sol_lamports: int
    tokens: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StrategyParams(_Model):
    """Strategy knobs shared by the live engine and the backtester.

    Fractions (0.55 = 55 %): ``dip_pct, take_profit_pct, partial_tp_fraction,
    trail_pct, stop_loss_pct``. Durations in minutes/hours as named.
    """

    dip_pct: float = 0.55
    confirm_green: int = 2
    min_buy_sell_ratio: float = 1.2
    take_profit_pct: float = 0.40
    partial_tp_fraction: float = 0.5
    trail_pct: float = 0.15
    stop_loss_pct: float = 0.18
    max_hold_min: float = 120.0
    dip_lookback_h: float = 6.0
    min_age_min: float = 60.0
    max_age_h: float = 48.0
    min_mcap_usd: float = 100_000.0
    max_mcap_usd: float = 5_000_000.0
    min_liquidity_usd: float = 30_000.0
    cooldown_min: float = 30.0

    FIELDS_FROM_SETTINGS: ClassVar[tuple[str, ...]] = (
        "dip_pct",
        "confirm_green",
        "min_buy_sell_ratio",
        "take_profit_pct",
        "partial_tp_fraction",
        "trail_pct",
        "stop_loss_pct",
        "max_hold_min",
        "dip_lookback_h",
        "min_age_min",
        "max_age_h",
        "min_mcap_usd",
        "max_mcap_usd",
        "min_liquidity_usd",
        "cooldown_min",
    )

    @classmethod
    def from_settings(cls, settings: Any) -> "StrategyParams":
        """Copy the same-named attributes from a Settings (or any object)."""
        return cls(**{name: getattr(settings, name) for name in cls.FIELDS_FROM_SETTINGS})

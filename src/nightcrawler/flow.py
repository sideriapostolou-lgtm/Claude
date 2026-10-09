"""Per-coin, strictly causal trade-flow features: the live twin of the wave-2 lab (``research/lab2/common.py``).

The lab computes its features from CryptoHouse chain data (``research/flow``). The live bot gets the same trades,
one by one, from pump.fun's swap API (:mod:`nightcrawler.sources.pumpfun_trades`). :class:`FlowTracker` keeps one
coin's trades in chain order and answers :meth:`FlowTracker.as_of` with a :class:`FlowSnapshot` built ONLY from
trades with ``ts <= tau = t - 20 s``, under the lab's names and definitions, so a strategy written against
``common.AsOf`` (``snap.bars``, ``snap["w120_buy_sol"]``, ``snap.top_share()``, ``snap.trades``, ...) runs
unchanged on live data. Pure Python, no I/O, no third-party imports (pandas only inside
:meth:`FlowSnapshot.trades_frame`, when present).

THE CONTRACT
============
* **Causality.** A snapshot at ``t`` reads trades with ``ts <= tau`` only. A minute bar is visible once it ended
  (``minute_ts + 60 <= tau``). Window and AGENT fields raise :class:`NotYetKnown` before their legal time
  (lab rules: ``w120_*`` from g + 120, ``w300_*`` from g + 300, AGENT identity from its detection, AGENT window
  totals from g + 420). Garbage after the cutoff can never change a snapshot (tested).
* **Completeness.** The feed calls :meth:`FlowTracker.mark_complete` once every trade with ``ts < x`` is in.
  ``snap.complete`` is False when trades up to tau may still be missing (``complete_through <= tau``): do not
  trade on such a snapshot. ``history_from`` is the time from which the tracker holds EVERY trade; curve-life,
  launch, wallet-position and reserve features need it to reach back to creation (curve) or graduation (pool),
  otherwise they read ``None`` (the lab's NULL, never 0).
* **Wallet identity.** Pooled program accounts (:data:`POOLED_ACCOUNTS`) are kept in every SOL / token total and
  in the reserve chain (they are real trades) but never count as a wallet (top buyers, AGENT, positions,
  orphans), exactly like ``common.py`` / ``s1.py``. swap-api attributes most pooled trades to the real signer.
* **Failed transactions** never reach the tracker: swap-api lists successful swaps only (its trades matched
  CryptoHouse's ``err = ''`` set 6,138/6,142, the 4 others being pooled-account attribution; AUDIT section 1).
  :func:`nightcrawler.sources.pumpfun_trades.parse_trade` also drops rows that carry an error flag.

SOL CONVENTION (README section 9; ``research/flow/validate.py::net_swap_sol``)
==============================================================================
The lab's ``usol`` is user-side SOL: what the trader paid on a buy (fees included) or received on a sell. swap-api's
``amountSol`` mixes conventions by instruction. :class:`FlowTracker` converts every trade back to ``usol``:

* **PumpSwap sells**: ``amountSol`` is user-side. Exact.
* **PumpSwap buys**: ``priceSol`` is the exact post-trade price ``(x + v) / y`` and the token reserve ``y`` chains
  exactly from the migration pool (206.9M tokens), so the quote that entered the pool, ``q = X1 - X0``, is known
  to the lamport. ``amountSol > q``: a ``buy`` instruction, ``amountSol`` is user-side (exact). ``amountSol = q``:
  a fee-free buy (BOOST/AGENT), exact. ``amountSol < q``: ``buy_exact_quote_in``, ``amountSol`` is net of fees;
  the LP fee ``q - amountSol`` is exact and the protocol + creator fee is taken from the pool's last ``buy``
  instruction (default 90 bps, 123 bps on the 2-bps-LP tier): within ~0.05 % of the lab. Without the pool's whole
  history the chain is unknown and buys are scaled by :data:`AMM_BUY_FALLBACK` (volume-weighted calibration on
  10,470 matched trades), per-trade error within [-0.4 %, +0.9 %].
* **Curve trades**: ``amountSol`` is the curve's ``sol_amount``; the fee is 1.25 % (95 + 30 bps) except for known
  fee-free accounts (:data:`FEE_FREE_ACCOUNTS`), so ``usol = amountSol * 1.0125`` on buys and ``* 0.9875`` on
  sells (within 2 lamports).

The parity harness (``tests/test_flow_parity.py``) checks all of this against the lab's own rows for the same coins.
"""

from __future__ import annotations

import bisect
import math
import statistics
import struct
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "DECISION_LAG_S",
    "AGENT_WINDOW_S",
    "W120_S",
    "W300_S",
    "DUST_SOL",
    "TOKEN_SUPPLY",
    "POOLED_ACCOUNTS",
    "FEE_FREE_ACCOUNTS",
    "VENUE_CURVE",
    "VENUE_AMM",
    "AMM_BUY_FALLBACK",
    "NotYetKnown",
    "ForbiddenFeature",
    "FlowTrade",
    "FlowRow",
    "AgentInfo",
    "Position",
    "FlowBars",
    "FlowSnapshot",
    "FlowTracker",
    "detect_agent",
    "grid_time",
    "pumpswap_fee_components",
    "agent_stats",
    "curve_user_sol",
    "wallet_h",
    "b58decode",
    "cityhash64",
]

# --------------------------------------------------------------------------- constants (research/lab2/common.py)

DECISION_LAG_S = 20            # PLAN 3.2: a decision at t uses events with ts <= tau = t - 20 s
AGENT_WINDOW_S = 420           # BOOST: 29-30 slices x 12 s, last slice ~g + 341-353 s (audit fix 2)
AGENT_MIN_BUYS = 4
AGENT_GAP_RANGE = (11.0, 13.0)
AGENT_BAND = (10.0, 14.0)
AGENT_MIN_BAND_SHARE = 0.6
W120_S, W300_S = 120, 300
LAUNCH_S, SNIPER_S, FIRST_N = 120, 60, 20     # curve.sql launch window, 60 s snipers, first 20 buyers
COMPLETER_RSOL_SOL = 55.0      # curve.sql: COMPLETER = buys while real SOL >= 55 (the last 30 SOL)
DUST_SOL = 0.01                # buyers / sellers count wallets with >= 0.01 SOL; n_dust counts trades below it
TOKEN_SUPPLY = 1_000_000_000   # market cap = price x 1e9 tokens
TOP_K = 10                     # w120_top10 / w300_top10
LAMPORTS = 1_000_000_000
TOK_RAW = 1_000_000            # raw token units per whole token (6 decimals)
_DUST_L = 10_000_000           # DUST_SOL in lamports (b2.sql / curve.sql compare integer lamports)

#: Pooled program accounts: the event ``user`` signs for many people (AUDIT 3.6). Never a wallet.
POOLED_ACCOUNTS = frozenset({"ARu4n5mFdZogZAravu7CcizaojWnS6oqka37gdLT5SZn"})
#: Accounts whose curve trades pay no fee (one bot's PDA; 1,471 + 1,429 fee-free curve trades in the launch sample).
FEE_FREE_ACCOUNTS = frozenset({"BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"})

VENUE_CURVE, VENUE_AMM = 0, 1
CURVE_FEE_BPS = 125.0                          # 95 protocol + 30 creator (launch sample, 2026-10-08)
CURVE_VSOL0_LAMPORTS = 30 * LAMPORTS           # virtual SOL reserve at creation (SOL curves)
CURVE_VTOK0_RAW = 1_073_000_000 * TOK_RAW      # virtual token reserve at creation
POOL_BASE0 = 206_900_000.0                     # tokens in a 2026-10 migration pool
POOL_X0_SOL = 84.990359056                     # pricing reserve x + v of a fresh migration pool (= pool_quote0)
V_MIGRATION_SOL = 17.584505289                 # its virtual quote reserve (only used to split x0 / virt in B1 rows)
#: Volume-weighted usol / amountSol of PumpSwap buys (10,470 tx-matched trades, 2026-10-08) when the reserve
#: chain is unknown.
AMM_BUY_FALLBACK = 1.0043
_CHAIN_TOL_LAMPORTS = 3.0
_DEFAULT_PC_RATE = (5 + 85) / 1e4              # protocol + creator of the 20-bps-LP tier, its commonest creator fee
_TIER2_PC_RATE = (93 + 30) / 1e4               # the 2-bps-LP tier

_WINDOW_FIELDS = {
    "w120_buy_sol", "w120_sell_sol", "w120_n_buyers", "w120_n_sellers", "w120_top10",
    "w300_buy_sol", "w300_sell_sol", "w300_n_buyers", "w300_n_sellers", "w300_top10",
}
_AGENT_ID = ("agent_present", "agent_wallet", "agent_known_at", "agent_first_offset_s")
_AGENT_WIN = ("agent_slices", "agent_sol", "agent_median_gap", "agent_gap_cv", "agent_gap_band_share",
              "w120_top5_share_ex_agent")
_CREATE_FIELDS = ("creator", "created_ts", "c_ts", "c_slot", "vsol0", "symbol", "name", "uri", "created_exact")
_G_FIELDS = (
    "g_ts", "grad_delay_s", "grad_delay_lb_s", "curve_partial", "pool_base0", "pool_quote0",
    "curve_buy_sol", "curve_sell_sol", "curve_buy_tok", "curve_sell_tok", "curve_n_buys", "curve_n_sells",
    "curve_n_buyers", "curve_n_sellers", "curve_top1_buy_sol", "curve_top3_buy_sol", "completer_sol", "completer30",
    "creator_buy_sol", "creator_sell_sol", "creator_buy_tok", "creator_sell_tok", "first20_buy_sol",
)
_LAUNCH_FIELDS = (
    "l_buy_sol", "l_sell_sol", "l_buy_tok", "l_sell_tok", "l_n_buys", "l_n_sells", "l_n_buyers", "l_n_sellers",
    "l_n_wallets", "l_top3_buy_sol", "l_rsol_max", "l_bundle_slots", "l_max_buyers_slot", "l_creator_buy_sol",
    "l_creator_sell_sol", "z_n_buyers", "z_n_buyers_noncreator", "z_buy_sol", "z_buy_tok", "sn60_n_buyers",
    "sn60_buy_sol",
)
#: Lab fields that encode the future or the lab's own collection: never features (common.FORBIDDEN, subset).
FORBIDDEN = frozenset({"n_chunks", "n_pools", "virt_sol", "virt_max_sol", "w_exact", "virt_known", "price_repaired",
                       "n_trades", "first_m", "last_m", "truncated", "minute_idx", "split", "tradeable", "usable"})


class NotYetKnown(KeyError):
    """A legal field was read before the time it becomes knowable (common.NotYetKnown)."""


class ForbiddenFeature(KeyError):
    """A field that encodes the future or the lab's data collection (common.ForbiddenFeature)."""


# --------------------------------------------------------------------------- trades


@dataclass(frozen=True, slots=True)
class FlowTrade:
    """One swap as served by swap-api, typed. ``price`` is the POST-trade price in SOL per whole token (pricing
    reserve ``(x + v) / y`` on PumpSwap, virtual reserves on the curve); ``amount_sol`` is swap-api's
    ``amountSol`` (its own convention, see the module docstring); ``tok_raw`` is exact (6 decimals)."""

    slot: int
    pos: int                 # position inside the slot (slotIndexId digits 13-22)
    sid: str                 # slotIndexId: 12-digit slot + 10-digit position, unique per trade
    ts: int                  # block time, epoch seconds
    wallet: str
    is_buy: bool
    venue: int               # VENUE_CURVE (program "pump") or VENUE_AMM ("pump_amm")
    amount_sol: float
    tok_raw: int
    price: float
    tx: str = ""

    @property
    def key(self) -> tuple[int, int, str]:
        return (self.slot, self.pos, self.sid)

    @property
    def tok(self) -> float:
        return self.tok_raw / TOK_RAW


@dataclass(frozen=True, slots=True)
class FlowRow:
    """A trade plus what the reserve chain says about it (lab B1 columns). Lamports / raw units."""

    trade: FlowTrade
    usol: int                # user-side SOL (lab convention), lamports
    usol_exact: bool
    kind: str                # buy | exact_in | fee_free | sell | curve | curve_fee_free | fallback
    fees: int                # lamports (exact on the curve, estimated on PumpSwap)
    x0: float | None         # curve: virtual SOL before; PumpSwap: real quote before (X0 - v), lamports
    y0: int | None           # curve: virtual tokens before; PumpSwap: pool tokens before, raw
    X0: float | None         # pricing reserve before (curve: = x0), lamports
    y1: int | None
    pooled: bool
    rsol_after: float | None = None   # curve real SOL after the trade (SOL)

    @property
    def sol(self) -> float:
        return self.usol / LAMPORTS

    @property
    def tok(self) -> float:
        return self.trade.tok_raw / TOK_RAW


#: PumpSwap SOL-pool fee schedule, total bps one side by market cap in SOL (research/lab/costs.py, pump.fun docs
#: "Last Updated 20 May 2026"). Components observed on chain: (LP 2, protocol 93, creator 30) below 420 SOL, then
#: (LP 20, protocol 5, creator total - 25).
PUMPSWAP_SOL_TIERS: tuple[tuple[float, float], ...] = (
    (420, 125), (1470, 120), (2460, 115), (3440, 110), (4420, 105), (9820, 100), (14740, 95),
    (19650, 90), (24560, 85), (29470, 80), (34380, 75), (39300, 70), (44210, 65), (49120, 60),
    (54030, 55), (58940, 52.5), (63860, 50), (68770, 47.5), (73681, 45), (78590, 42.5), (83500, 40),
    (88400, 37.5), (93330, 35), (98240, 32.5), (math.inf, 30),
)


def pumpswap_fee_components(mcap_sol: float) -> tuple[float, float, float]:
    """(LP, protocol, creator) bps of a canonical SOL pool at market cap ``mcap_sol``."""
    total = next(bps for upper, bps in PUMPSWAP_SOL_TIERS if mcap_sol < upper)
    if total >= 125:
        return (2.0, 93.0, 30.0)
    return (20.0, 5.0, float(total) - 25.0)


def _invert_exact_in(net: int, bps: tuple[float, float, float]) -> int:
    """usol of a ``buy_exact_quote_in`` whose net quote is ``net``: fees are ceil(usol * b / (1e4 + sum b)) each.
    Several usol can give the same net (ceil steps): the roundest wins (users type round amounts)."""
    d = 1e4 + sum(bps)
    u0 = int(math.ceil(net * d / 1e4))
    best: tuple[int, int] | None = None
    for u in range(u0 - 4, u0 + 5):
        if u - sum(math.ceil(u * b / d) for b in bps) != net:
            continue
        zeros = len(str(u)) - len(str(u).rstrip("0"))
        if best is None or zeros > best[0]:
            best = (zeros, u)
    return best[1] if best is not None else u0


GRID_OFFSET_S = 20             # lab decisions happen at minute boundary + 20 s (the bar that just ended is visible)


def grid_time(g_ts: float, age_s: float) -> float:
    """The lab's decision time for an age after graduation: the grid time t (minute boundary + 20 s) with
    t <= g + age < t + 60 (``s1.checkpoint_time`` / ``m1._grid_time``)."""
    m0 = int(g_ts) // 60 * 60
    return float(m0 + GRID_OFFSET_S + 60 * math.floor((g_ts + age_s - m0 - GRID_OFFSET_S) / 60.0))


def curve_user_sol(is_buy: bool, amount_sol: float, wallet: str,
                   fee_free: frozenset[str] = FEE_FREE_ACCOUNTS) -> tuple[int, int]:
    """(usol, fees) in lamports for a curve trade: swap-api reports the curve's ``sol_amount`` (fees excluded on
    buys, included on sells)."""
    amount = int(round(amount_sol * LAMPORTS))
    if wallet in fee_free:
        return amount, 0
    fee = int(math.ceil(amount * 95 / 1e4)) + int(math.ceil(amount * 30 / 1e4))
    return (amount + fee, fee) if is_buy else (max(amount - fee, 0), fee)


# --------------------------------------------------------------------------- AGENT (research/flow/features.py)


def agent_stats(ts: Sequence[int], sol: Sequence[float]) -> dict[str, float] | None:
    if len(ts) < 2:
        return None
    gaps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
    mean = sum(gaps) / len(gaps)
    sd = math.sqrt(sum((g - mean) ** 2 for g in gaps) / len(gaps)) if len(gaps) > 1 else 0.0
    band = sum(1 for g in gaps if AGENT_BAND[0] <= g <= AGENT_BAND[1]) / len(gaps)
    return {"n_slices": float(len(ts)), "sol": float(sum(sol)), "median_gap": float(statistics.median(gaps)),
            "gap_cv": float(sd / mean) if mean > 0 else math.inf, "gap_band_share": float(band)}


@dataclass(frozen=True)
class AgentInfo:
    """The detected AGENT (BOOST) at a snapshot. ``known_at`` = its 4th buy (lab definition); ``detected_at`` =
    the first trade time at which the causal rule matched (>= known_at when the first gaps were irregular)."""

    wallet: str
    known_at: int
    detected_at: int
    first_offset_s: float
    slices: int
    sol: float
    median_gap: float
    gap_cv: float
    gap_band_share: float
    buy_ts: tuple[int, ...]
    buy_sol: tuple[float, ...]


def detect_agent(cands: Mapping[str, Mapping[str, Any]], g_ts: float, as_of: float | None = None) -> dict | None:
    """research/flow/features.detect_agent (robust rule): >= 4 buys in [g, g + 420 s), no sells, median gap in
    [11, 13] s, >= 60 % of gaps in [10, 14] s; the best wallet by SOL. ``as_of``: buys with ts <= as_of only."""
    best: dict | None = None
    hi = g_ts + AGENT_WINDOW_S if as_of is None else min(g_ts + AGENT_WINDOW_S, as_of + 1)
    for w, d in cands.items():
        if d["sells"]:
            continue
        idx = [i for i, t in enumerate(d["ts"]) if g_ts <= t < hi]
        ts = [d["ts"][i] for i in idx]
        sol = [d["sol"][i] for i in idx]
        if len(ts) < AGENT_MIN_BUYS:
            continue
        st = agent_stats(ts, sol)
        if not st or not (AGENT_GAP_RANGE[0] <= st["median_gap"] <= AGENT_GAP_RANGE[1]):
            continue
        if st["gap_band_share"] < AGENT_MIN_BAND_SHARE:
            continue
        rec: dict[str, Any] = dict(st)
        rec.update({"wallet": w, "first_offset_s": ts[0] - g_ts, "known_at": ts[AGENT_MIN_BUYS - 1],
                    "buy_ts": ts, "buy_sol": sol})
        if best is None or rec["sol"] > best["sol"]:
            best = rec
    return best


# --------------------------------------------------------------------------- wallet hash (B1 wallet_h)

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}
_M64 = (1 << 64) - 1
_K0, _K1, _K2, _K3 = 0xC3A5C85C97CB3127, 0xB492B66FBE98F273, 0x9AE16A3B2F90404F, 0xC949D7C7509E6557


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58_IDX[ch]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def _rot(v: int, s: int) -> int:
    return v if s == 0 else ((v >> s) | (v << (64 - s))) & _M64


def _h128to64(u: int, v: int) -> int:
    kmul = 0x9DDFEA08EB382D69
    a = ((u ^ v) * kmul) & _M64
    a ^= a >> 47
    b = ((v ^ a) * kmul) & _M64
    b ^= b >> 47
    return (b * kmul) & _M64


def cityhash64(b: bytes) -> int:
    """ClickHouse ``cityHash64`` for 17-32 byte strings (research/lab2/s1.py port; Solana keys are 32 bytes)."""
    n = len(b)
    if not 17 <= n <= 32:
        raise ValueError("cityhash64 port covers 17-32 byte inputs only")

    def f(i: int) -> int:
        return int(struct.unpack_from("<Q", b, i)[0])

    a = (f(0) * _K1) & _M64
    bb = f(8)
    c = (f(n - 8) * _K2) & _M64
    d = (f(n - 16) * _K0) & _M64
    return _h128to64((_rot((a - bb) & _M64, 43) + _rot(c, 30) + d) & _M64, (a + _rot(bb ^ _K3, 20) - c + n) & _M64)


def wallet_h(address: str) -> int:
    """B1 ``wallet_h`` of a base58 address (cityHash64 of the raw 32-byte key)."""
    return cityhash64(b58decode(address))


def _wallet_bytes(address: str) -> bytes:
    """Sort key = the raw key bytes (ClickHouse orders wallets by bytes, not by their base58 text)."""
    try:
        return b58decode(address)
    except KeyError:
        return address.encode()


# --------------------------------------------------------------------------- positions


@dataclass
class Position:
    """One wallet's trades in a snapshot prefix (B3 columns): tokens are whole, SOL user-side."""

    n_buys: int = 0
    n_sells: int = 0
    buy_sol: float = 0.0
    sell_sol: float = 0.0
    buy_tok: float = 0.0
    sell_tok: float = 0.0
    curve_buy_sol: float = 0.0
    curve_sell_sol: float = 0.0
    first_ts: int | None = None
    last_ts: int | None = None
    first_buy_ts: int | None = None
    last_sell_ts: int | None = None
    pos_tok: float = 0.0           # running position (end_tok)
    peak_tok: float = 0.0
    orphan_tok: float = 0.0        # tokens sold beyond the holding at that moment (TRANSFEREE signal)
    n_sell_without_holding: int = 0
    cost_sol: float = 0.0          # average-cost basis of the open position (S1 rule)

    @property
    def end_tok(self) -> float:
        return self.pos_tok


# --------------------------------------------------------------------------- bars


_BAR_FIELDS = ("o", "h", "l", "c", "X", "y", "x_real", "buy_sol", "sell_sol", "buy_tok", "sell_tok", "n_buys",
               "n_sells", "n_dust", "n_buyers", "n_sellers", "top5_buy_sol", "agent_buy_sol", "traded")


class FlowBars:
    """Completed minute bars at tau, lab ``common.Bars`` layout (lists instead of numpy arrays).

    Index 0 = the graduation minute (partial). Minutes without trades carry the last close (o = h = l = c) and
    zero flow; ``traded`` is 1.0 for minutes with >= 1 pool trade. ``X`` = pricing reserve x + v and ``y`` = pool
    tokens after the minute (None when the reserve chain is unknown). ``x_real`` is not observable from swap-api
    (None). ``agent_buy_sol`` is NaN before the AGENT is detected. B2 definitions: ``open`` = the price before the
    minute's first trade, ``high`` / ``low`` / ``close`` after trades; buyers / sellers / top5 per wallet."""

    def __init__(self, minute_ts: list[int], cols: dict[str, list[Any]]) -> None:
        self.minute_ts = minute_ts
        self._cols = cols

    def __len__(self) -> int:
        return len(self.minute_ts)

    def __getattr__(self, name: str) -> list[Any]:
        cols = self.__dict__.get("_cols")
        if cols is not None and name in cols:
            return cols[name]
        raise AttributeError(name)

    def as_dict(self) -> dict[str, list[Any]]:
        d: dict[str, list[Any]] = {"minute_ts": list(self.minute_ts)}
        d.update({k: list(v) for k, v in self._cols.items()})
        return d


# --------------------------------------------------------------------------- tracker


@dataclass
class _Meta:
    mint: str
    created_ts: float | None
    creator: str | None
    c_slot: int | None
    g_ts: float | None
    symbol: str | None
    name: str | None
    uri: str | None
    pool_base0: float
    pool_x0_sol: float
    vsol0: float
    pooled: frozenset[str]
    fee_free: frozenset[str]
    max_bars: int | None


class FlowTracker:
    """One coin's trades in chain order (slot, position), deduplicated by slotIndexId.

    ``created_ts`` / ``creator`` / ``c_slot`` / ``symbol`` come from the coin's metadata (pump.fun census);
    ``g_ts`` is the graduation time when known (CompleteEvent block time), otherwise it is inferred causally as the
    time of the last curve trade before the first pool trade. Ingest order does not matter; the feed must call
    :meth:`mark_complete` and set ``history_from`` (see the module docstring)."""

    def __init__(self, mint: str, *, created_ts: float | None = None, creator: str | None = None,
                 c_slot: int | None = None, g_ts: float | None = None, symbol: str | None = None,
                 name: str | None = None, uri: str | None = None, pool_base0: float = POOL_BASE0,
                 pool_x0_sol: float = POOL_X0_SOL, vsol0: float = 30.0, history_from: float | None = None,
                 pooled: Iterable[str] = POOLED_ACCOUNTS, fee_free: Iterable[str] = FEE_FREE_ACCOUNTS,
                 max_bars: int | None = None) -> None:
        self.meta = _Meta(mint=mint, created_ts=created_ts, creator=creator, c_slot=c_slot, g_ts=g_ts, symbol=symbol,
                          name=name, uri=uri, pool_base0=float(pool_base0), pool_x0_sol=float(pool_x0_sol),
                          vsol0=float(vsol0), pooled=frozenset(pooled), fee_free=frozenset(fee_free),
                          max_bars=max_bars)
        #: every trade with ``ts >= history_from`` is held (None = unknown: no curve / reserve / position features)
        self.history_from = history_from
        #: every trade with ``ts < complete_through`` is held (set by the feed); -inf = nothing confirmed
        self.complete_through = -math.inf
        self._trades: list[FlowTrade] = []
        self._keys: list[tuple[int, int, str]] = []
        self._sids: set[str] = set()
        self._rows: list[FlowRow] | None = None
        self._chain_breaks = 0
        self._fee_table_misses = 0
        self.version = 0

    # ------------------------------------------------------------------ ingest
    @property
    def mint(self) -> str:
        return self.meta.mint

    def __len__(self) -> int:
        return len(self._trades)

    @property
    def trades(self) -> tuple[FlowTrade, ...]:
        return tuple(self._trades)

    def ingest(self, trades: Iterable[FlowTrade]) -> int:
        """Add trades (any order); duplicates (same slotIndexId) are ignored. Returns how many were new."""
        added = 0
        for t in trades:
            if t.sid in self._sids:
                continue
            k = t.key
            i = bisect.bisect_right(self._keys, k)
            self._keys.insert(i, k)
            self._trades.insert(i, t)
            self._sids.add(t.sid)
            added += 1
        if added:
            self._rows = None
            self.version += 1
        return added

    def mark_complete(self, through_ts: float) -> None:
        """Every trade with ``ts < through_ts`` is now held (monotone: an earlier time is ignored)."""
        if through_ts > self.complete_through:
            self.complete_through = float(through_ts)
            self.version += 1

    def set_history_from(self, ts: float) -> None:
        self.history_from = float(ts)
        self._rows = None
        self.version += 1

    # ------------------------------------------------------------------ chain derivation
    def g_at(self, tau: float) -> float | None:
        """Graduation time as known at ``tau`` (given, or the last curve trade before the first pool trade)."""
        if self.meta.g_ts is not None:
            return float(self.meta.g_ts)
        last_curve: int | None = None
        for t in self._trades:
            if t.ts > tau:
                continue
            if t.venue == VENUE_AMM:
                return float(last_curve) if last_curve is not None else float(t.ts)
            last_curve = t.ts
        return None

    def _curve_from_creation(self) -> bool:
        m = self.meta
        return self.history_from is not None and m.created_ts is not None and self.history_from <= m.created_ts

    def _pool_from_start(self, g: float | None) -> bool:
        if self.history_from is None:
            return False
        if g is not None and self.history_from <= g:
            return True
        return self._curve_from_creation()

    @property
    def chain_breaks(self) -> int:
        self.rows()
        return self._chain_breaks

    def rows(self) -> list[FlowRow]:
        """Every trade with its chain-derived columns, in chain order (cached until the next ingest)."""
        if self._rows is None:
            self._rows, self._chain_breaks, self._fee_table_misses = self._derive(self._trades, math.inf)
        return self._rows

    def rows_asof(self, tau: float) -> list[FlowRow]:
        """Rows of the trades with ``ts <= tau``, derived from those trades ONLY. Normally they are a prefix of
        :meth:`rows` (block time grows with the slot); if a later-stamped trade sits earlier in chain order, the
        prefix is re-derived on its own, so nothing stamped after tau can reach a snapshot."""
        rows = self.rows()
        n = sum(1 for r in rows if r.trade.ts <= tau)
        if all(r.trade.ts <= tau for r in rows[:n]):
            return rows[:n]
        return self._derive([t for t in self._trades if t.ts <= tau], tau)[0]

    def _derive(self, trades: list[FlowTrade], tau: float) -> tuple[list[FlowRow], int, int]:
        m = self.meta
        curve_ok = self._curve_from_creation()
        pool_ok = self._pool_from_start(self.g_at(tau))
        y_c: int | None = CURVE_VTOK0_RAW if curve_ok else None
        x_c: float | None = m.vsol0 * LAMPORTS if curve_ok else None
        y_a: int | None = int(round(m.pool_base0 * TOK_RAW)) if pool_ok else None
        x_a: float | None = m.pool_x0_sol * LAMPORTS if pool_ok else None
        v_l = V_MIGRATION_SOL * LAMPORTS
        pc_rate = {20: _DEFAULT_PC_RATE, 2: _TIER2_PC_RATE}
        breaks = 0
        misses = 0
        out: list[FlowRow] = []
        for t in trades:
            pooled = t.wallet in m.pooled
            amount = int(round(t.amount_sol * LAMPORTS))
            if t.venue == VENUE_CURVE:
                usol, fees = curve_user_sol(t.is_buy, t.amount_sol, t.wallet, m.fee_free)
                kind = "curve_fee_free" if t.wallet in m.fee_free else "curve"
                x0c, y0c, y1c, rs = x_c, y_c, None, None
                if y_c is not None and x_c is not None:
                    y1c = y_c - t.tok_raw if t.is_buy else y_c + t.tok_raw
                    x1c = t.price * y1c * 1e3 if y1c > 0 else x_c
                    # the curve's sol_amount IS the virtual-SOL move: a gap means SOL left / entered outside trades
                    # (Mayhem curves do that by design) or a trade is missing; x is re-anchored on the price anyway
                    if abs(abs(x1c - x_c) - amount) > max(_CHAIN_TOL_LAMPORTS, amount * 1e-7):
                        breaks += 1
                    rs = (x1c - CURVE_VSOL0_LAMPORTS) / LAMPORTS
                    y_c, x_c = y1c, x1c
                out.append(FlowRow(t, usol, t.wallet in m.fee_free, kind, fees, x0c, y0c, x0c, y1c, pooled, rs))
                continue
            # ---- PumpSwap
            if not t.is_buy:
                usol, kind, exact, fees = amount, "sell", True, 0
            else:
                usol, kind, exact, fees = int(round(amount * AMM_BUY_FALLBACK)), "fallback", False, 0
            X0: float | None = x_a
            y0: int | None = y_a
            y1: int | None = None
            if y_a is not None and x_a is not None:
                y1 = y_a - t.tok_raw if t.is_buy else y_a + t.tok_raw
                X1 = t.price * y1 * 1e3 if y1 > 0 else x_a
                q = X1 - x_a if t.is_buy else x_a - X1
                tol = max(_CHAIN_TOL_LAMPORTS, amount * 1e-7)
                if t.is_buy:
                    diff = amount - q
                    if q <= 0 or abs(diff) > 0.05 * q + tol:
                        breaks += 1
                    elif abs(diff) <= tol:
                        usol, kind, exact, fees = amount, "fee_free", True, 0
                    elif diff > 0:
                        usol, kind, exact = amount, "buy", True
                        fees = int(round(diff))
                        if q >= _DUST_L:                 # small trades are dominated by per-fee rounding up
                            tier = 2 if diff / q > 0.0118 else 20
                            pc_rate[tier] = diff / q
                    else:
                        # buy_exact_quote_in: the user typed usol; each fee is ceil(usol * bps / (1e4 + total)) at
                        # the pool's market-cap tier BEFORE the trade and amountSol = usol - fees (verified to the
                        # lamport on the launch sample). The LP fee q - amountSol confirms the tier group.
                        lp = -diff
                        bps = pumpswap_fee_components((x_a / LAMPORTS) / (y_a / TOK_RAW) * TOKEN_SUPPLY)
                        if abs(lp / max(amount, 1) * 1e4 - bps[0]) < 1.0 or amount < 1_000_000:
                            usol = _invert_exact_in(amount, bps)
                        else:   # the fee schedule moved: exact LP fee + protocol/creator from the last `buy`
                            misses += 1
                            tier = 2 if lp / max(amount, 1) * 1e4 < 6 else 20
                            usol = int(round(amount + lp + amount * pc_rate[tier]))
                        fees, kind, exact = usol - amount, "exact_in", False
                else:
                    if q + tol < amount:
                        breaks += 1
                    fees = max(int(round(q - amount)), 0)
                y_a, x_a = y1, X1
            x0r = X0 - v_l if X0 is not None else None
            out.append(FlowRow(t, usol, exact, kind, fees, x0r, y0, X0, y1, pooled))
        return out, breaks, misses

    # ------------------------------------------------------------------ snapshots
    def as_of(self, t: float, *, lag_s: float = DECISION_LAG_S, sol_usd: float | None = None) -> "FlowSnapshot":
        """Everything knowable about the coin at decision time ``t`` (cutoff ``tau = t - lag_s``)."""
        return FlowSnapshot(self, float(t), float(t) - lag_s, sol_usd)


# --------------------------------------------------------------------------- snapshot


@dataclass
class _Window:
    buy_sol: float
    sell_sol: float
    n_buyers: int
    n_sellers: int
    top10: tuple[tuple[str, float, float], ...]


@dataclass
class _Cache:
    bars: FlowBars | None = None
    agent: AgentInfo | None = None
    agent_done: bool = False
    windows: dict[int, _Window] = field(default_factory=dict)
    curve: dict[str, Any] | None = None
    positions: dict[str, Position] | None = None


class FlowSnapshot:
    """What a strategy may know about one coin at ``t`` (``common.AsOf`` interface on live trades).

    ``snap[name]`` -> value (None = NULL) or raises :class:`NotYetKnown` / :class:`ForbiddenFeature` /
    ``KeyError``; ``snap.get(name)``; ``snap.features()``; ``snap.bars``; ``snap.trades`` (B1 rows, pandas);
    ``snap.positions()``, ``snap.orphan_sellers()``, ``snap.inventory()`` (wallet level)."""

    def __init__(self, tracker: FlowTracker, t: float, tau: float, sol_usd: float | None = None) -> None:
        self._tr = tracker
        self.meta = tracker.meta
        self.mint = tracker.mint
        self.t, self.tau = t, tau
        self._sol_usd = sol_usd
        self._rows = tracker.rows_asof(tau)
        g = tracker.g_at(tau)
        self.g: float = g if g is not None else math.nan
        self.graduated = g is not None
        self.age_s = t - g if g is not None else math.nan
        self.m0 = int(g) // 60 * 60 if g is not None else 0
        k = int(max((tau - self.m0) // 60, 0)) if g is not None else 0
        if tracker.meta.max_bars is not None:
            k = min(k, tracker.meta.max_bars)
        self.k = k
        #: True when every trade with ts <= tau is known (the feed confirmed it): only then trade on it
        self.complete = tracker.complete_through > tau
        self.data_lag_s = t - tracker.complete_through
        self.history_from = tracker.history_from
        self.curve_known = tracker._curve_from_creation()
        self.pool_known = tracker._pool_from_start(g)
        self._c = _Cache()

    # ------------------------------------------------------------------ basic
    @property
    def n_trades(self) -> int:
        return len(self._rows)

    @property
    def rows(self) -> list[FlowRow]:
        """Trade rows with ts <= tau, chain order (pooled included)."""
        return self._rows

    def _amm(self) -> list[FlowRow]:
        if not self.graduated:
            return []
        return [r for r in self._rows if r.trade.venue == VENUE_AMM and r.trade.ts >= self.g]

    def _curve(self) -> list[FlowRow]:
        return [r for r in self._rows if r.trade.venue == VENUE_CURVE]

    # ------------------------------------------------------------------ bars
    @property
    def bars(self) -> FlowBars:
        if self._c.bars is None:
            self._c.bars = self._build_bars()
        return self._c.bars

    def _build_bars(self) -> FlowBars:
        k = self.k
        init_y = self.meta.pool_base0
        init_p = self.meta.pool_x0_sol / init_y
        by_min: dict[int, list[FlowRow]] = {}
        for r in self._amm():
            i = (r.trade.ts - self.m0) // 60
            if 0 <= i < k:
                by_min.setdefault(i, []).append(r)
        agent = self.agent if self.agent_detected else None
        agent_min: dict[int, float] = {}
        if agent is not None:
            for ts, s in zip(agent.buy_ts, agent.buy_sol, strict=True):
                j = (ts - self.m0) // 60
                agent_min[j] = agent_min.get(j, 0.0) + s
        cols: dict[str, list[Any]] = {f: [] for f in _BAR_FIELDS}
        last_p = init_p
        last_y: float | None = init_y if self.pool_known else None
        for i in range(k):
            rs = by_min.get(i)
            if rs:
                o = last_p
                posts = [r.trade.price for r in rs]
                c = posts[-1]
                h = max(max(posts), o, c)
                lo = min(min(posts), o, c)
                buys = [r for r in rs if r.trade.is_buy]
                sells = [r for r in rs if not r.trade.is_buy]
                wb: dict[str, int] = {}
                ws: dict[str, int] = {}
                for r in rs:
                    d = wb if r.trade.is_buy else ws
                    d[r.trade.wallet] = d.get(r.trade.wallet, 0) + r.usol
                y_end = rs[-1].y1 / TOK_RAW if rs[-1].y1 is not None else None
                last_p = c
                last_y = y_end
                vals: dict[str, Any] = {
                    "o": o, "h": h, "l": lo, "c": c,
                    "buy_sol": sum(r.usol for r in buys) / LAMPORTS, "sell_sol": sum(r.usol for r in sells) / LAMPORTS,
                    "buy_tok": sum(r.trade.tok_raw for r in buys) / TOK_RAW,
                    "sell_tok": sum(r.trade.tok_raw for r in sells) / TOK_RAW,
                    "n_buys": len(buys), "n_sells": len(sells),
                    "n_dust": sum(1 for r in rs if r.usol < _DUST_L),
                    "n_buyers": sum(1 for v in wb.values() if v >= _DUST_L),
                    "n_sellers": sum(1 for v in ws.values() if v >= _DUST_L),
                    "top5_buy_sol": sum(sorted(wb.values(), reverse=True)[:5]) / LAMPORTS,
                    "traded": 1.0,
                }
            else:
                vals = {"o": last_p, "h": last_p, "l": last_p, "c": last_p, "buy_sol": 0.0, "sell_sol": 0.0,
                        "buy_tok": 0.0, "sell_tok": 0.0, "n_buys": 0, "n_sells": 0, "n_dust": 0, "n_buyers": 0,
                        "n_sellers": 0, "top5_buy_sol": 0.0, "traded": 0.0}
            vals["y"] = last_y
            vals["X"] = vals["c"] * last_y if last_y is not None else None
            vals["x_real"] = None
            vals["agent_buy_sol"] = agent_min.get(i, 0.0) if agent is not None else math.nan
            for f in _BAR_FIELDS:
                cols[f].append(vals[f])
        return FlowBars([self.m0 + 60 * i for i in range(k)], cols)

    @property
    def price(self) -> float:
        """Pool price at the end of the last completed minute (the fresh pool's price if none)."""
        return float(self.bars.c[self.k - 1]) if self.k > 0 else self.meta.pool_x0_sol / self.meta.pool_base0

    @property
    def last_price(self) -> float | None:
        """Post-trade price of the last trade at or before tau (any venue; finer than :attr:`price`)."""
        return self._rows[-1].trade.price if self._rows else None

    @property
    def mcap_sol(self) -> float:
        return self.price * TOKEN_SUPPLY

    @property
    def sol_usd(self) -> float:
        if self._sol_usd is None:
            raise ValueError("sol_usd was not given to FlowTracker.as_of(); USD features need it")
        return float(self._sol_usd)

    @property
    def mcap_usd(self) -> float:
        return self.mcap_sol * self.sol_usd

    def _win(self, window_s: float) -> range:
        first = max(0, int(math.floor((self.tau - window_s - self.m0) / 60.0)))
        return range(min(first, self.k), self.k)

    def vol_sol(self, window_s: float) -> float:
        b = self.bars
        return float(sum(b.buy_sol[i] + b.sell_sol[i] for i in self._win(window_s)))

    def vol_usd(self, window_s: float) -> float:
        return self.vol_sol(window_s) * self.sol_usd

    def net_flow_sol(self, window_s: float) -> float:
        b = self.bars
        return float(sum(b.buy_sol[i] - b.sell_sol[i] for i in self._win(window_s)))

    def non_agent_buy_sol(self, window_s: float) -> float | None:
        if not self.agent_resolved:
            return None
        b = self.bars
        s = self._win(window_s)
        ag = sum(b.agent_buy_sol[i] for i in s) if self.agent_detected else 0.0
        return float(sum(b.buy_sol[i] for i in s) - ag)

    def ret(self, window_s: float) -> float:
        j = int(math.floor((self.tau - window_s - self.m0) / 60.0)) - 1
        p0 = float(self.bars.c[j]) if 0 <= j < self.k else self.meta.pool_x0_sol / self.meta.pool_base0
        return self.price / p0 - 1.0

    def max_high(self, window_s: float) -> float:
        hs = [self.bars.h[i] for i in self._win(window_s)]
        return float(max(hs)) if hs else self.price

    def alive(self, vol_usd_15m: float = 1500.0, mcap_usd_min: float = 6000.0) -> bool:
        return self.vol_usd(900) >= vol_usd_15m and self.mcap_usd >= mcap_usd_min

    # ------------------------------------------------------------------ AGENT
    @property
    def agent(self) -> AgentInfo | None:
        """The AGENT detected causally at tau (None while undetected)."""
        if not self._c.agent_done:
            self._c.agent = self._detect_agent()
            self._c.agent_done = True
        return self._c.agent

    def _detect_agent(self) -> AgentInfo | None:
        """features.detect_agent(as_of=tau) on pool trades in [g, g + 420 s): candidates are wallets with buys and
        no sell in the window up to tau (the lab's b2.sql counts sells in the window only). ``detected_at`` = the
        first buy of that wallet at which the rule matched on the buys seen so far."""
        if not self.graduated:
            return None
        g = self.g
        cands: dict[str, dict[str, Any]] = {}
        for r in self._amm():
            t = r.trade
            if t.ts >= g + AGENT_WINDOW_S or r.pooled:
                continue
            d = cands.setdefault(t.wallet, {"ts": [], "sol": [], "sells": 0})
            if t.is_buy:
                d["ts"].append(t.ts)
                d["sol"].append(r.sol)
            else:
                d["sells"] += 1
        found = detect_agent(cands, g, as_of=self.tau)
        if found is None:
            return None
        d = cands[found["wallet"]]
        detected_at = int(found["known_at"])
        for i in range(AGENT_MIN_BUYS - 1, len(d["ts"])):
            sub = {found["wallet"]: {"ts": d["ts"][: i + 1], "sol": d["sol"][: i + 1], "sells": 0}}
            if detect_agent(sub, g, as_of=d["ts"][i]) is not None:
                detected_at = int(d["ts"][i])
                break
        return AgentInfo(wallet=found["wallet"], known_at=int(found["known_at"]), detected_at=int(detected_at),
                         first_offset_s=float(found["first_offset_s"]), slices=int(found["n_slices"]),
                         sol=float(found["sol"]), median_gap=float(found["median_gap"]),
                         gap_cv=float(found["gap_cv"]), gap_band_share=float(found["gap_band_share"]),
                         buy_ts=tuple(found["buy_ts"]), buy_sol=tuple(found["buy_sol"]))

    @property
    def agent_detected(self) -> bool:
        return self.agent is not None

    @property
    def agent_resolved(self) -> bool:
        """AGENT presence is decided: detected, or the 420 s window is over."""
        return self.agent_detected or (self.graduated and self.tau >= self.g + AGENT_WINDOW_S)

    # ------------------------------------------------------------------ early windows
    def _window(self, w: int) -> _Window:
        """b2.sql early window: pool trades with g <= ts < g + w, per-wallet sums (lamports), buyers / sellers
        with >= 0.01 SOL, top 10 buyers by buy SOL (pooled accounts then removed, as common.py does)."""
        if w not in self._c.windows:
            g = self.g
            wb: dict[str, int] = {}
            ws: dict[str, int] = {}
            for r in self._amm():
                if r.trade.ts >= g + w:
                    continue
                d = wb if r.trade.is_buy else ws
                d[r.trade.wallet] = d.get(r.trade.wallet, 0) + r.usol
            ranked = sorted(((a, b / LAMPORTS, ws.get(a, 0) / LAMPORTS) for a, b in wb.items() if b > 0),
                            key=lambda x: -x[1])[:TOP_K]
            self._c.windows[w] = _Window(
                buy_sol=sum(wb.values()) / LAMPORTS, sell_sol=sum(ws.values()) / LAMPORTS,
                n_buyers=sum(1 for v in wb.values() if v >= _DUST_L),
                n_sellers=sum(1 for v in ws.values() if v >= _DUST_L),
                top10=tuple(x for x in ranked if x[0] not in self.meta.pooled))
        return self._c.windows[w]

    def top_buyers(self, window: str = "w120", exclude_agent: bool = True) -> tuple | None:
        lst = self[f"{window}_top10"]
        if lst is None:
            return None
        if exclude_agent:
            if not self.agent_resolved:
                raise NotYetKnown("AGENT presence is undecided at tau; cannot exclude it yet")
            aw = self.agent.wallet if self.agent is not None else None
            lst = tuple(w for w in lst if w[0] != aw)
        return lst

    def top_share(self, window: str = "w120", k: int = 5, exclude_agent: bool = True) -> float | None:
        lst = self.top_buyers(window, exclude_agent=exclude_agent)
        total = self[f"{window}_buy_sol"]
        if lst is None or total is None:
            return None
        if exclude_agent and self.agent is not None:
            raw = self[f"{window}_top10"] or ()
            total = total - sum(w[1] for w in raw if w[0] == self.agent.wallet)
        if total <= 0:
            return None
        return float(sum(sorted((w[1] for w in lst), reverse=True)[:k]) / total)

    # ------------------------------------------------------------------ curve / launch (curve.sql)
    def _curve_feats(self) -> dict[str, Any]:
        if self._c.curve is None:
            self._c.curve = self._build_curve()
        return self._c.curve

    @property
    def c_slot(self) -> int | None:
        """Creation slot: given, or inferred as the slot of the first curve trade when it happened in the creation
        second (the creator's dev buy rides in the create transaction). When the first curve trade came later, the
        creation slot is not observable from trades: the slot just before that trade is returned (an upper bound,
        ``c_slot_exact`` False). No trade sits in it, so the BUNDLE (creation-slot buyers) is empty, which is exact;
        pass the real slot (e.g. from the mint's first signature) when a strategy needs the number itself."""
        m = self.meta
        if m.c_slot is not None:
            return m.c_slot
        if m.created_ts is None or not self.curve_known:
            return None
        cur = self._curve()
        if not cur:
            return None
        return cur[0].trade.slot if cur[0].trade.ts <= m.created_ts else cur[0].trade.slot - 1

    @property
    def c_slot_exact(self) -> bool:
        cur = self._curve()
        return self.meta.c_slot is not None or (bool(cur) and self.meta.created_ts is not None
                                                 and cur[0].trade.ts <= self.meta.created_ts)

    def _build_curve(self) -> dict[str, Any]:
        """curve.sql over curve trades with ts <= g (or tau before graduation): curve life, launch window
        [c, c + 120 s], creation slot (BUNDLE), 60 s snipers, creator, COMPLETER, first 20 buyers. Lamport sums;
        per-wallet thresholds >= 0.01 SOL; first-20 ties inside a slot broken by wallet bytes (as the SQL)."""
        m = self.meta
        out: dict[str, Any] = {}
        if not self.curve_known or m.created_ts is None:
            return out
        c_ts = float(m.created_ts)
        c_slot = self.c_slot
        creator = m.creator
        rows = self._curve()
        g = self.g if self.graduated else math.inf
        keys = ("b", "s", "bt", "st", "nb", "ns", "l30", "lb", "ls", "lbt", "lst", "lnb", "lns", "zb", "zbt", "sn")
        per: dict[str, dict[str, int]] = {}
        fb_slot: dict[str, int] = {}
        l_slots: dict[int, set[str]] = {}
        rsol_max = 0.0
        for r in rows:
            t = r.trade
            if t.ts > g:
                continue
            p = per.setdefault(t.wallet, dict.fromkeys(keys, 0))
            launch = t.ts <= c_ts + LAUNCH_S
            if launch and r.rsol_after is not None:
                rsol_max = max(rsol_max, r.rsol_after)
            if t.is_buy:
                p["b"] += r.usol
                p["bt"] += t.tok_raw
                p["nb"] += 1
                fb_slot.setdefault(t.wallet, t.slot)
                if r.rsol_after is not None and r.rsol_after >= COMPLETER_RSOL_SOL:
                    p["l30"] += r.usol
                if launch:
                    p["lb"] += r.usol
                    p["lbt"] += t.tok_raw
                    p["lnb"] += 1
                    l_slots.setdefault(t.slot, set()).add(t.wallet)
                if c_slot is not None and t.slot == c_slot:
                    p["zb"] += r.usol
                    p["zbt"] += t.tok_raw
                if t.ts <= c_ts + SNIPER_S:
                    p["sn"] += r.usol
            else:
                p["s"] += r.usol
                p["st"] += t.tok_raw
                p["ns"] += 1
                if launch:
                    p["ls"] += r.usol
                    p["lst"] += t.tok_raw
                    p["lns"] += 1

        def tot(key: str, div: float = LAMPORTS) -> float:
            return sum(p[key] for p in per.values()) / div

        top3 = sorted((p["b"] for p in per.values()), reverse=True)[:3]
        l_top3 = sorted((p["lb"] for p in per.values()), reverse=True)[:3]
        comp = max(per.items(), key=lambda kv: (kv[1]["l30"], _wallet_bytes(kv[0])), default=None)
        first = sorted((fb_slot[w], _wallet_bytes(w), p["b"]) for w, p in per.items() if p["nb"] > 0)[:FIRST_N]
        cr = per.get(creator or "")
        z = {}.fromkeys(keys, 0)

        def crv(key: str, div: float = LAMPORTS) -> float:
            return (cr or z)[key] / div

        out.update({
            "curve_buy_sol": tot("b"), "curve_sell_sol": tot("s"),
            "curve_buy_tok": tot("bt", TOK_RAW), "curve_sell_tok": tot("st", TOK_RAW),
            "curve_n_buys": int(tot("nb", 1)), "curve_n_sells": int(tot("ns", 1)),
            "curve_n_buyers": sum(1 for p in per.values() if p["b"] >= _DUST_L),
            "curve_n_sellers": sum(1 for p in per.values() if p["s"] >= _DUST_L),
            "curve_top1_buy_sol": (top3[0] if top3 else 0) / LAMPORTS, "curve_top3_buy_sol": sum(top3) / LAMPORTS,
            "completer_sol": comp[1]["l30"] / LAMPORTS if comp is not None else 0.0,
            "completer30": comp[0] if comp is not None and comp[1]["l30"] > 0 else None,
            "first20_buy_sol": sum(x[2] for x in first) / LAMPORTS,
            "creator_buy_sol": crv("b"), "creator_sell_sol": crv("s"),
            "creator_buy_tok": crv("bt", TOK_RAW), "creator_sell_tok": crv("st", TOK_RAW),
            "l_buy_sol": tot("lb"), "l_sell_sol": tot("ls"), "l_buy_tok": tot("lbt", TOK_RAW),
            "l_sell_tok": tot("lst", TOK_RAW), "l_n_buys": int(tot("lnb", 1)), "l_n_sells": int(tot("lns", 1)),
            "l_n_buyers": sum(1 for p in per.values() if p["lb"] >= _DUST_L),
            "l_n_sellers": sum(1 for p in per.values() if p["ls"] >= _DUST_L),
            "l_n_wallets": sum(1 for p in per.values() if p["lnb"] + p["lns"] > 0),
            "l_top3_buy_sol": sum(l_top3) / LAMPORTS, "l_rsol_max": rsol_max,
            "l_bundle_slots": sum(1 for s in l_slots.values() if len(s) >= 2),
            "l_max_buyers_slot": max((len(s) for s in l_slots.values()), default=0),
            "l_creator_buy_sol": crv("lb"), "l_creator_sell_sol": crv("ls"),
            "sn60_n_buyers": sum(1 for w, p in per.items() if p["sn"] > 0 and w != creator),
            "sn60_buy_sol": sum(p["sn"] for w, p in per.items() if w != creator) / LAMPORTS,
        })
        if c_slot is not None:
            out.update({
                "z_n_buyers": sum(1 for p in per.values() if p["zb"] > 0),
                "z_n_buyers_noncreator": sum(1 for w, p in per.items() if p["zb"] > 0 and w != creator),
                "z_buy_sol": tot("zb"), "z_buy_tok": tot("zbt", TOK_RAW),
            })
        elif not rows or rows[0].trade.ts > c_ts:
            # no curve trade in the creation second, so none in the creation slot: the BUNDLE is empty (exact)
            out.update({"z_n_buyers": 0, "z_n_buyers_noncreator": 0, "z_buy_sol": 0.0, "z_buy_tok": 0.0})
        return out

    # ------------------------------------------------------------------ static fields with legality
    def legal_from(self, name: str) -> float | None:
        """Earliest tau at which ``name`` may be read; None = forbidden or unknown (fail closed)."""
        m = self.meta
        g = self.g if self.graduated else math.inf
        created = m.created_ts
        if name in FORBIDDEN:
            return None
        if name == "mint":
            return -math.inf
        if name in _CREATE_FIELDS:
            return float(created) if created is not None else g
        if name.startswith(("l_", "z_", "sn60_")) and name in _LAUNCH_FIELDS:
            return min(float(created) + LAUNCH_S, g) if created is not None else g
        if name in _G_FIELDS:
            return g
        if name.startswith("w120_") and name in _WINDOW_FIELDS:
            return g + W120_S
        if name.startswith("w300_") and name in _WINDOW_FIELDS:
            return g + W300_S
        if name in _AGENT_ID:
            a = self.agent
            return float(a.detected_at) if a is not None else g + AGENT_WINDOW_S
        if name in _AGENT_WIN:
            a = self.agent
            return max(g + AGENT_WINDOW_S, float(a.detected_at)) if a is not None else g + AGENT_WINDOW_S
        return None

    def _value(self, name: str) -> Any:
        m = self.meta
        if name == "mint":
            return self.mint
        if name in ("creator", "symbol", "name", "uri"):
            return getattr(m, name)
        if name in ("created_ts", "c_ts"):
            return m.created_ts
        if name == "c_slot":
            return self.c_slot
        if name == "vsol0":
            return m.vsol0
        if name == "created_exact":
            return m.created_ts is not None
        if name == "g_ts":
            return self.g
        if name == "grad_delay_s":
            return self.g - m.created_ts if m.created_ts is not None else None
        if name == "grad_delay_lb_s":
            return self.g - m.created_ts if m.created_ts is not None else None
        if name == "curve_partial":
            return not self.curve_known
        if name == "pool_base0":
            return m.pool_base0
        if name == "pool_quote0":
            return m.pool_x0_sol
        if name in _WINDOW_FIELDS:
            w = self._window(W120_S if name.startswith("w120_") else W300_S)
            return getattr(w, name.split("_", 1)[1]) if not name.endswith("top10") else w.top10
        a = self.agent
        if name == "agent_present":
            return a is not None
        if name in _AGENT_ID or name in _AGENT_WIN:
            if name == "w120_top5_share_ex_agent":
                return self.top_share("w120", 5, exclude_agent=True)
            if a is None:
                return None
            return {"agent_wallet": a.wallet, "agent_known_at": a.known_at, "agent_first_offset_s": a.first_offset_s,
                    "agent_slices": a.slices, "agent_sol": a.sol, "agent_median_gap": a.median_gap,
                    "agent_gap_cv": a.gap_cv, "agent_gap_band_share": a.gap_band_share}[name]
        if name in _G_FIELDS or name in _LAUNCH_FIELDS:
            return self._curve_feats().get(name)
        raise KeyError(name)

    def __getitem__(self, name: str) -> Any:
        if name == "agent_detected":
            return self.agent_detected
        if name in FORBIDDEN:
            raise ForbiddenFeature(f"{name!r} encodes the future or the lab's data collection: never a feature")
        lf = self.legal_from(name)
        if lf is None:
            raise KeyError(name)
        if self.tau < lf:
            raise NotYetKnown(f"{name!r} is knowable from {lf} (tau = {self.tau})")
        return self._value(name)

    def get(self, name: str, default: Any = None) -> Any:
        """Like ``[]`` but ``default`` for NotYetKnown / unknown names. Forbidden still raises."""
        try:
            return self[name]
        except NotYetKnown:
            return default
        except ForbiddenFeature:
            raise
        except KeyError:
            return default

    def features(self) -> dict[str, Any]:
        """Every field legal at tau (plus ``agent_detected`` and ``age_s``)."""
        names = ("mint", *_CREATE_FIELDS, *_G_FIELDS, *_LAUNCH_FIELDS, *sorted(_WINDOW_FIELDS), *_AGENT_ID, *_AGENT_WIN)
        out: dict[str, Any] = {}
        for n in names:
            lf = self.legal_from(n)
            if lf is not None and self.tau >= lf:
                out[n] = self._value(n)
        out["agent_detected"] = self.agent_detected
        out["age_s"] = self.age_s
        return out

    # ------------------------------------------------------------------ wallets
    def positions(self) -> dict[str, Position]:
        """Per-wallet B3 summary over every trade with ts <= tau (curve + pool, chain order; pooled excluded).
        Meaningful only when ``history_from`` reaches back to creation (otherwise tokens bought earlier read as
        orphan sells): check ``snap.curve_known``."""
        if self._c.positions is None:
            pos: dict[str, Position] = {}
            for r in self._rows:
                if r.pooled:
                    continue
                t = r.trade
                p = pos.setdefault(t.wallet, Position())
                p.first_ts = t.ts if p.first_ts is None else p.first_ts
                p.last_ts = t.ts
                if t.is_buy:
                    p.n_buys += 1
                    p.buy_sol += r.sol
                    p.buy_tok += r.tok
                    p.first_buy_ts = t.ts if p.first_buy_ts is None else p.first_buy_ts
                    if t.venue == VENUE_CURVE:
                        p.curve_buy_sol += r.sol
                    p.cost_sol = (p.cost_sol if p.pos_tok > 0 else 0.0) + r.sol
                    p.pos_tok += r.tok
                    p.peak_tok = max(p.peak_tok, p.pos_tok)
                else:
                    p.n_sells += 1
                    p.sell_sol += r.sol
                    p.sell_tok += r.tok
                    p.last_sell_ts = t.ts
                    if t.venue == VENUE_CURVE:
                        p.curve_sell_sol += r.sol
                    held = max(p.pos_tok, 0.0)
                    if held <= 0:
                        p.n_sell_without_holding += 1
                    p.orphan_tok += max(0.0, r.tok - held)
                    if held > 0:
                        p.cost_sol *= 1.0 - min(r.tok, held) / held
                    p.pos_tok -= r.tok
                    if p.pos_tok <= 0:
                        p.cost_sol = 0.0
            self._c.positions = pos
        return self._c.positions

    def orphan_summary(self) -> dict[str, Any]:
        """B3 per-coin aggregates: buyers / sellers over all wallets (dust included), wallets that sold tokens they
        never bought (orphan), and sell-only wallets."""
        pos = self.positions()
        orph = {w: p for w, p in pos.items() if p.orphan_tok > 0}
        return {"n_buyers_all": sum(1 for p in pos.values() if p.n_buys > 0),
                "n_sellers_all": sum(1 for p in pos.values() if p.n_sells > 0),
                "n_orphan_sellers": len(orph), "orphan_seller_sell_sol": sum(p.sell_sol for p in orph.values()),
                "orphan_tok": sum(p.orphan_tok for p in pos.values()),
                "n_sell_only_wallets": sum(1 for p in pos.values() if p.n_buys == 0 and p.n_sells > 0),
                "history_complete": self.curve_known}

    def orphan_sellers(self, min_frac: float = 0.02) -> dict[str, Position]:
        """Wallets whose orphan part exceeds ``min_frac`` of what they sold (S1/D1 ORPHAN_TOL = 2 %)."""
        return {w: p for w, p in self.positions().items() if p.sell_tok > 0 and p.orphan_tok > min_frac * p.sell_tok}

    def inventory(self) -> dict[str, Any]:
        """Creator and early-buyer inventory at tau (whole tokens): the creator, the creation-slot BUNDLE, the
        SNIPERS (first curve buy within 60 s of creation, or among the first 20 distinct curve buyers), and the
        COMPLETER (largest curve buyer while real SOL >= 55). ``None`` values when curve history is missing."""
        m = self.meta
        if not self.curve_known or m.created_ts is None:
            return {"known": False}
        pos = self.positions()
        first: list[str] = []
        bundle: set[str] = set()
        snipers: set[str] = set()
        for r in self._curve():
            t = r.trade
            if not t.is_buy or r.pooled:
                continue
            if self.c_slot is not None and t.slot == self.c_slot:
                bundle.add(t.wallet)
            if t.wallet not in first:
                first.append(t.wallet)
                if t.ts <= m.created_ts + SNIPER_S:
                    snipers.add(t.wallet)
        snipers.update(first[:FIRST_N])
        comp = self._curve_feats().get("completer30")

        def group(ws: Iterable[str]) -> dict[str, float]:
            ps = [pos[w] for w in ws if w in pos]
            return {"wallets": float(len(ps)), "held_tok": sum(max(p.pos_tok, 0.0) for p in ps),
                    "peak_tok": sum(p.peak_tok for p in ps), "bought_tok": sum(p.buy_tok for p in ps),
                    "sold_tok": sum(p.sell_tok for p in ps), "cost_sol": sum(p.cost_sol for p in ps if p.pos_tok > 0)}

        insiders = set(bundle) | snipers | ({m.creator} if m.creator else set()) | ({comp} if comp else set())
        if self.agent is not None:
            insiders.discard(self.agent.wallet)
        return {"known": True, "creator": group([m.creator] if m.creator else []), "bundle": group(bundle),
                "snipers": group(snipers), "completer": group([comp] if comp else []), "insiders": group(insiders),
                "orphan_sellers": group(self.orphan_sellers())}

    # ------------------------------------------------------------------ B1 rows
    def trade_rows(self, min_sol: float = DUST_SOL) -> list[dict[str, Any]]:
        """B1-shaped rows (``research/flow/README.md``) of trades with ts <= tau and usol >= ``min_sol``:
        slot, tx_idx (in-slot position), pix, ix, ts, mint, venue, is_buy, wallet, wallet_h, usol (lamports),
        tok (raw), x0, y0 (reserves BEFORE the trade; PumpSwap x0 + virt_ksol * 1000 = the pricing reserve,
        their split is not observable from swap-api), fees (lamports), virt_ksol, pooled, src = 1 (swap-api)."""
        vk = int(V_MIGRATION_SOL * LAMPORTS // 1000)
        out = []
        for r in self._rows:
            if r.usol < min_sol * LAMPORTS:
                continue
            t = r.trade
            amm = t.venue == VENUE_AMM
            out.append({"slot": t.slot, "tx_idx": t.pos, "pix": 0, "ix": 0, "ts": t.ts, "mint": self.mint,
                        "venue": t.venue, "is_buy": bool(t.is_buy), "wallet": t.wallet, "wallet_h": wallet_h(t.wallet),
                        "usol": r.usol, "tok": t.tok_raw, "x0": r.x0 if r.x0 is not None else math.nan,
                        "y0": r.y0 if r.y0 is not None else math.nan, "fees": r.fees,
                        "virt_ksol": vk if amm else 0, "pooled": r.pooled, "src": 1})
        return out

    @property
    def trades(self) -> Any:
        """B1 rows with ts <= tau as a pandas DataFrame (``common.AsOf.trades``; ``wallet_h`` as uint64)."""
        return self.trades_frame()

    def trades_frame(self, min_sol: float = DUST_SOL) -> Any:
        try:
            import pandas as pd  # optional: the bot itself does not depend on pandas
        except ImportError as exc:  # pragma: no cover - pandas is present wherever lab code runs
            raise ImportError("FlowSnapshot.trades needs pandas; use trade_rows() for plain dicts") from exc
        df = pd.DataFrame(self.trade_rows(min_sol))
        if len(df):
            df["wallet_h"] = df["wallet_h"].astype("uint64")
        return df

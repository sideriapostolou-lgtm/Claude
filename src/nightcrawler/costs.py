"""Per-trade cost model for $5-$50 swaps of pump.fun graduates via Jupiter Ultra (owner: O3).

An EXACT port of the strategy lab's ``research/lab/costs.py`` (``tests/test_costs_port.py`` checks 50
cases against it to 1e-9), so the lab, the learner's replay and the docs share ONE definition of
costs. Only the network/calibration helpers of the lab file are left out. Added for the learning
loop (docs/LEARNING.md §4.2):

* :func:`replay_model` - the lab model with its MEV buffer replaced by the paper broker's haircut
  (``PAPER_SLIPPAGE_BPS``, 100 bps per side), every component multiplied by a ``cost_scale``;
* :func:`cost_scale` / :func:`cost_tier` - the per-market-cap-tier calibration multiplier, a
  RATCHET that is never below 1.0 (phase 2 raises it from live quotes; lowering needs a PR);
* :func:`side_fill` - one side as an effective USD price per token, the shape the backtester's
  ``cost_fn`` hook expects.

A golden file (``tests/fixtures/costs_golden.json``) fails the build if modelled costs ever DROP
(monotone pessimism).

Every side of a trade pays, in this order (all sources checked 2026-10-08):

1. **Jupiter Ultra platform fee** - ``ULTRA_FEE_BPS = 10`` bps of the swap.
2. **Pool fee** (:func:`fee_bps`) - pump.fun fee schedule (https://pump.fun/docs/fees, 20 May 2026):
   bonding curve 1.25 %; PumpSwap canonical pools tiered by market cap (price in SOL x 1 billion
   tokens): 1.25 % below 420 SOL ... 0.30 % above 98,240 SOL; USDC-paired coins use the USDC table;
   non-canonical pools 0.30 %.
3. **Price impact** from constant-product math (:func:`impact`). Every SOL-paired graduate starts with
   ``K_GRAD = 84.990 * 206.9e6 ~ 1.7585e10`` SOL*token; k only grows afterwards, so using ``K_GRAD``
   is leak-free and slightly CONSERVATIVE. The quote reserve at price ``p`` (SOL per token) is
   ``sqrt(k * p)``. The bonding curve uses pump.fun's virtual reserves (``K_CURVE = 3.219e10``).
4. **Slippage / MEV buffer** - ``mev_bps`` per side (lab default 20 bps; the replay uses the paper
   broker's ``PAPER_SLIPPAGE_BPS`` instead).
5. **Network** - 5,000 lamports base + priority (default 0.0002 SOL per swap), converted at the SOL
   price of that minute. Token-account rent is refunded on the sell -> modelled as 0.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

__all__ = [
    "ULTRA_FEE_BPS",
    "BONDING_CURVE_FEE_BPS",
    "NON_CANONICAL_FEE_BPS",
    "LAMPORTS_PER_SOL",
    "BASE_FEE_LAMPORTS",
    "DEFAULT_PRIORITY_SOL",
    "DEFAULT_MEV_BPS",
    "PUMP_FEE_SUPPLY",
    "K_CURVE",
    "K_GRAD",
    "PUMPSWAP_SOL_TIERS",
    "PUMPSWAP_USDC_TIERS",
    "USDC_MINT",
    "SOL_QUOTE",
    "FALLBACK_SOL_USD",
    "PAPER_SLIPPAGE_BPS",
    "COST_TIERS",
    "fee_bps",
    "quote_reserve_usd",
    "impact",
    "CostModel",
    "CoinCostContext",
    "context_for_coin",
    "SolUsd",
    "round_trip_cost_pct",
    "replay_model",
    "cost_tier",
    "cost_scale",
    "side_fill",
]

# --------------------------------------------------------------------------- constants

ULTRA_FEE_BPS = 10.0
BONDING_CURVE_FEE_BPS = 125.0
NON_CANONICAL_FEE_BPS = 30.0
LAMPORTS_PER_SOL = 1_000_000_000
BASE_FEE_LAMPORTS = 5_000
DEFAULT_PRIORITY_SOL = 0.0002
DEFAULT_MEV_BPS = 20.0
PUMP_FEE_SUPPLY = 1_000_000_000  # pump.fun tiers use price x 1 billion tokens

CURVE_V_SOL0 = 30.0
CURVE_V_TOK0 = 1_073_000_000.0
K_CURVE = CURVE_V_SOL0 * CURVE_V_TOK0  # SOL * token
CURVE_REAL_TOKENS = 793_100_000.0
GRAD_POOL_SOL = 115.005359057 - CURVE_V_SOL0 - 0.015  # real SOL at completion minus graduation fee
GRAD_POOL_TOKENS = PUMP_FEE_SUPPLY - CURVE_REAL_TOKENS  # 206.9 M
K_GRAD = GRAD_POOL_SOL * GRAD_POOL_TOKENS  # ~1.7585e10 SOL * token

# (upper bound of market cap in SOL, total fee bps) - pump.fun/docs/fees, SOL table
PUMPSWAP_SOL_TIERS: tuple[tuple[float, float], ...] = (
    (420, 125), (1470, 120), (2460, 115), (3440, 110), (4420, 105), (9820, 100), (14740, 95),
    (19650, 90), (24560, 85), (29470, 80), (34380, 75), (39300, 70), (44210, 65), (49120, 60),
    (54030, 55), (58940, 52.5), (63860, 50), (68770, 47.5), (73681, 45), (78590, 42.5), (83500, 40),
    (88400, 37.5), (93330, 35), (98240, 32.5), (math.inf, 30),
)
# USDC-paired coins (market cap in USDC)
PUMPSWAP_USDC_TIERS: tuple[tuple[float, float], ...] = (
    (59_000, 125), (300_000, 120), (500_000, 115), (700_000, 110), (900_000, 105), (2_000_000, 100),
    (3_000_000, 95), (4_000_000, 90), (5_000_000, 85), (6_000_000, 80), (7_000_000, 75), (8_000_000, 70),
    (9_000_000, 65), (10_000_000, 60), (11_000_000, 55), (12_000_000, 53), (13_000_000, 50),
    (14_000_000, 48), (15_000_000, 45), (16_000_000, 43), (17_000_000, 40), (18_000_000, 38),
    (19_000_000, 35), (20_000_000, 33), (math.inf, 30),
)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_QUOTE = "11111111111111111111111111111111"
FALLBACK_SOL_USD = 106.0  # SOL/USD at the 2026-10-08 census, used only if no price series is given

#: The paper broker's haircut per side (``Settings.PAPER_SLIPPAGE_BPS`` default); the replay charges it
#: in place of the lab's MEV buffer, so shadow evidence is priced like a paper fill.
PAPER_SLIPPAGE_BPS = 100.0
#: Calibration tiers by market cap (USD): (upper bound, name). Phase 2 calibrates ``cost_scale`` per tier.
COST_TIERS: tuple[tuple[float, str], ...] = ((100_000.0, "lt100k"), (1_000_000.0, "100k-1m"), (math.inf, "1m+"))


def fee_bps(mcap_usd: float, phase: str = "pumpswap", sol_usd: float = FALLBACK_SOL_USD,
            quote: str = "SOL") -> float:
    """Pool fee in bps for one side. ``phase``: "curve" | "pumpswap" | "noncanonical".

    ``mcap_usd`` is price_usd x 1e9 (pump.fun's definition); for SOL-paired coins the tier is
    looked up in SOL (``mcap_usd / sol_usd``). Unknown quote tokens pay the top tier (1.25 %).
    """
    if phase == "curve":
        return BONDING_CURVE_FEE_BPS
    if phase == "noncanonical":
        return NON_CANONICAL_FEE_BPS
    if quote == "SOL":
        mcap = mcap_usd / sol_usd
        tiers = PUMPSWAP_SOL_TIERS
    elif quote == "USDC":
        mcap, tiers = mcap_usd, PUMPSWAP_USDC_TIERS
    else:
        return 125.0
    for upper, bps in tiers:
        if mcap < upper:
            return float(bps)
    return 30.0


def quote_reserve_usd(price_usd: float, k_sol: float, sol_usd: float) -> float:
    """USD value of the quote reserve of an x*y=k pool (k in SOL*token) at mid ``price_usd``.

    p_sol = price_usd / sol_usd; x_sol = sqrt(k * p_sol); x_usd = x_sol * sol_usd.
    """
    if price_usd <= 0 or k_sol <= 0:
        return 0.0
    return math.sqrt(k_sol * price_usd / sol_usd) * sol_usd


def impact(side: str, usd_size: float, price: float, k: float, sol_usd: float = FALLBACK_SOL_USD) -> float:
    """Effective USD fill price per token from constant-product math alone (no fees).

    buy  ``usd_size`` of quote into the pool:  price * (1 + usd_size / x)
    sell ``usd_size`` worth (at mid) of tokens: price / (1 + usd_size / x)
    where x = quote reserve in USD at ``price``. Raises on a bad side.
    """
    x = quote_reserve_usd(price, k, sol_usd)
    if x <= 0:
        return math.inf if side == "buy" else 0.0
    if side == "buy":
        return price * (1.0 + usd_size / x)
    if side == "sell":
        return price / (1.0 + usd_size / x)
    raise ValueError(f"side must be buy|sell, got {side!r}")


# --------------------------------------------------------------------------- the model


@dataclass(frozen=True)
class CostModel:
    """All knobs of the per-side cost model. Defaults = realistic for a $100 bankroll."""

    ultra_bps: float = ULTRA_FEE_BPS
    mev_bps: float = DEFAULT_MEV_BPS
    priority_sol: float = DEFAULT_PRIORITY_SOL
    base_fee_lamports: int = BASE_FEE_LAMPORTS
    fee_mult: float = 1.0  # stress multiplier on pool fees
    impact_mult: float = 1.0  # stress multiplier on price impact (1/k scaling)
    extra_hop_bps: float = 100.0  # non-SOL-quoted coins: Jupiter must route SOL -> quote -> token

    def network_usd(self, sol_usd: float) -> float:
        """USD cost of one swap transaction (base + priority); rent is refundable -> 0."""
        return (self.base_fee_lamports / LAMPORTS_PER_SOL + self.priority_sol) * sol_usd

    def side_bps(self, ctx: "CoinCostContext", price_usd: float, sol_usd: float) -> float:
        """Fee-like bps for one side at ``price_usd``: pool fee + Ultra + MEV buffer (+ hop)."""
        phase = ctx.phase_at_price(price_usd, sol_usd)
        bps = self.fee_mult * fee_bps(price_usd * PUMP_FEE_SUPPLY, phase, sol_usd, ctx.quote) + self.ultra_bps
        bps += self.mev_bps
        if ctx.quote not in ("SOL", "USDC"):
            bps += self.extra_hop_bps
        return bps

    def buy(self, usd_in: float, price_usd: float, ctx: "CoinCostContext", sol_usd: float,
            curve: bool = False) -> tuple[float, dict]:
        """Spend ``usd_in`` (excluding network fee) at mid ``price_usd`` -> (tokens, breakdown)."""
        if usd_in <= 0 or price_usd <= 0:
            return 0.0, {"fee_usd": 0.0, "impact_usd": 0.0}
        bps = self.side_bps(ctx, price_usd, sol_usd) if not curve else (
            self.fee_mult * BONDING_CURVE_FEE_BPS + self.ultra_bps + self.mev_bps)
        net_in = usd_in * (1.0 - bps / 1e4)
        x = ctx.quote_reserve_usd(price_usd, sol_usd, curve) / self.impact_mult
        tokens = (net_in / price_usd) * x / (x + net_in) if x > 0 else 0.0
        return tokens, {"fee_usd": usd_in - net_in, "impact_usd": net_in - tokens * price_usd,
                        "fee_bps": bps, "x_usd": x}

    def sell(self, tokens: float, price_usd: float, ctx: "CoinCostContext", sol_usd: float,
             curve: bool = False) -> tuple[float, dict]:
        """Sell ``tokens`` at mid ``price_usd`` -> (usd_out excluding network fee, breakdown)."""
        if tokens <= 0 or price_usd <= 0:
            return 0.0, {"fee_usd": 0.0, "impact_usd": 0.0}
        bps = self.side_bps(ctx, price_usd, sol_usd) if not curve else (
            self.fee_mult * BONDING_CURVE_FEE_BPS + self.ultra_bps + self.mev_bps)
        x = ctx.quote_reserve_usd(price_usd, sol_usd, curve) / self.impact_mult
        mid_value = tokens * price_usd
        gross = mid_value * x / (x + mid_value) if x > 0 else 0.0
        out = gross * (1.0 - bps / 1e4)
        return out, {"fee_usd": gross - out, "impact_usd": mid_value - gross, "fee_bps": bps, "x_usd": x}

    def stressed(self, factor: float) -> "CostModel":
        """Every cost component x ``factor`` (for sensitivity checks)."""
        return replace(self, ultra_bps=self.ultra_bps * factor, mev_bps=self.mev_bps * factor,
                       priority_sol=self.priority_sol * factor, fee_mult=self.fee_mult * factor,
                       impact_mult=self.impact_mult * factor, extra_hop_bps=self.extra_hop_bps * factor)


@dataclass(frozen=True)
class CoinCostContext:
    """Per-coin constants for the cost model (never shown to strategies)."""

    k_sol: float = K_GRAD  # PumpSwap k in SOL*token (or quote*token for other quotes)
    quote: str = "SOL"  # "SOL" | "USDC" | "OTHER"
    quote_usd: float = 1.0  # only for OTHER quotes (price now; no history available)
    graduated_ts: float = 0.0

    def phase_at_price(self, price_usd: float, sol_usd: float) -> str:
        return "pumpswap"

    def quote_reserve_usd(self, price_usd: float, sol_usd: float, curve: bool = False) -> float:
        if curve:
            return quote_reserve_usd(price_usd, K_CURVE, sol_usd)
        if self.quote == "SOL":
            return quote_reserve_usd(price_usd, self.k_sol, sol_usd)
        # k in quote*token: x_quote = sqrt(k * p_quote), p_quote = price_usd / quote_usd
        q = self.quote_usd if self.quote != "USDC" else 1.0
        return quote_reserve_usd(price_usd, self.k_sol, q)


def context_for_coin(doc: Mapping[str, Any], k_policy: str = "grad") -> CoinCostContext:
    """Cost context from a coin file. ``k_policy``:

    * ``"grad"`` (default, leak-free): SOL-paired -> ``K_GRAD``; other quotes -> current k (no launch
      constant known), shrunk by 2x as a conservative margin; Mayhem-mode coins -> min(current k,
      K_GRAD) because their pools are 100-10,000x shallower.
    * ``"min_now"``: min(K_GRAD, k measured from current reserves) - for calibration only.
    """
    cost = doc.get("cost") or {}
    launch = doc.get("launch") or {}
    qm = cost.get("quote_mint") or launch.get("quote_mint")
    quote = "SOL" if qm == SOL_QUOTE else "USDC" if qm == USDC_MINT else "OTHER"
    k_now = cost.get("k_now_quote_token")
    if launch.get("mayhem"):
        # Mayhem-mode coins "complete" with ~0.1-10 SOL instead of 85 SOL: their pools are tiny.
        k = min(float(k_now), K_GRAD) if k_now else K_GRAD / 1e4
        return CoinCostContext(k_sol=k, quote=quote if quote != "USDC" else "USDC",
                               quote_usd=float(cost.get("quote_price_usd_now") or 1.0),
                               graduated_ts=float(doc.get("graduated_ts") or 0))
    if quote == "SOL":
        k = K_GRAD if k_policy == "grad" or not k_now else min(K_GRAD, float(k_now))
        return CoinCostContext(k_sol=k, quote="SOL", graduated_ts=float(doc.get("graduated_ts") or 0))
    k = float(k_now) / 2 if k_now else K_GRAD / 1e4
    return CoinCostContext(k_sol=k, quote=quote, quote_usd=float(cost.get("quote_price_usd_now") or 1.0),
                           graduated_ts=float(doc.get("graduated_ts") or 0))


class SolUsd:
    """SOL/USD as-of lookup (last minute close at or before ts). Falls back to a constant."""

    def __init__(self, rows: Sequence[Sequence[float]] | None = None, fallback: float = FALLBACK_SOL_USD) -> None:
        rows = sorted(rows or [], key=lambda r: r[0])
        self.ts = [int(r[0]) for r in rows]
        self.px = [float(r[4]) for r in rows]
        self.fallback = fallback

    def at(self, ts: float) -> float:
        if not self.ts:
            return self.fallback
        i = bisect.bisect_right(self.ts, ts) - 1
        return self.px[max(i, 0)]


def round_trip_cost_pct(usd_size: float, mcap_usd: float, model: CostModel | None = None,
                        sol_usd: float = FALLBACK_SOL_USD, ctx: CoinCostContext | None = None,
                        include_network: bool = True) -> float:
    """Percent of ``usd_size`` lost buying then immediately selling at an unchanged mid price."""
    model = model or CostModel()
    ctx = ctx or CoinCostContext()
    price = mcap_usd / PUMP_FEE_SUPPLY
    tokens, _ = model.buy(usd_size, price, ctx, sol_usd)
    back, _ = model.sell(tokens, price, ctx, sol_usd)
    net = model.network_usd(sol_usd) * 2 if include_network else 0.0
    return (usd_size - back + net) / usd_size * 100.0


# --------------------------------------------------------------------------- replay additions


def replay_model(paper_slippage_bps: float = PAPER_SLIPPAGE_BPS, scale: float = 1.0) -> CostModel:
    """The learner's replay model: the lab default with the MEV buffer replaced by the paper broker's
    haircut, every component x ``scale`` (clamped to >= 1: calibration can only make costs worse)."""
    return replace(CostModel(), mev_bps=float(paper_slippage_bps)).stressed(max(1.0, float(scale)))


def cost_tier(mcap_usd: float) -> str:
    """Calibration tier name of a market cap in USD (see :data:`COST_TIERS`)."""
    for upper, name in COST_TIERS:
        if mcap_usd < upper:
            return name
    return COST_TIERS[-1][1]


def cost_scale(scales: Mapping[str, float] | None, mcap_usd: float) -> float:
    """Calibration multiplier for ``mcap_usd``'s tier: ``scales[tier]``, never below 1.0 (a ratchet)."""
    value = (scales or {}).get(cost_tier(mcap_usd), 1.0)
    return max(1.0, float(value))


def side_fill(model: CostModel, side: str, usd_mid: float, price_usd: float, ctx: CoinCostContext,
              sol_usd: float) -> tuple[float, dict]:
    """One side of ``usd_mid`` (USD at mid price) as an effective USD price per token (network fee
    excluded), plus the breakdown with ``impact_pct`` (percent of the swap lost to impact) and
    ``liquidity_usd`` (both pool sides at ``price_usd``). A pool that cannot fill gives ``inf`` for a
    buy and ``0`` for a sell."""
    if side == "buy":
        tokens, info = model.buy(usd_mid, price_usd, ctx, sol_usd)
        fill = usd_mid / tokens if tokens > 0 else math.inf
        swapped = usd_mid - info["fee_usd"]
    elif side == "sell":
        tokens = usd_mid / price_usd if price_usd > 0 else 0.0
        usd_out, info = model.sell(tokens, price_usd, ctx, sol_usd)
        fill = usd_out / tokens if tokens > 0 else 0.0
        swapped = usd_mid
    else:
        raise ValueError(f"side must be buy|sell, got {side!r}")
    x = float(info.get("x_usd", 0.0))
    info = {**info, "impact_pct": info["impact_usd"] / swapped * 100.0 if swapped > 0 else math.inf,
            "liquidity_usd": 2.0 * x}
    return fill, info

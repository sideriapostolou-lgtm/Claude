"""Realistic per-trade cost model for $5-$50 swaps of pump.fun graduates via Jupiter Ultra.

Every side of a trade pays, in this order (all sources checked 2026-10-08):

1. **Jupiter Ultra platform fee** - ``ULTRA_FEE_BPS = 10`` bps of the swap (Ultra ``/order``
   responses report ``feeBps: 10`` / ``platformFee.feeBps: 10`` for SOL <-> pump tokens).
2. **Pool fee** (:func:`fee_bps`) - pump.fun fee schedule, https://pump.fun/docs/fees
   ("Last Updated: 20 May 2026", snapshot saved to LAB/pumpfun_fees_snapshot.html):
   bonding curve 1.25 %; PumpSwap canonical pools tiered by market cap
   (price in SOL x 1 billion tokens): 1.25 % below 420 SOL ... 0.30 % above 98,240 SOL;
   USDC-paired coins use the USDC table; non-canonical pools 0.30 %.
3. **Price impact** from constant-product math (:func:`impact`). PumpSwap canonical pools of
   pump.fun graduates are x*y=k with burned LP; pump.fun migrates the completed curve's real
   reserves (85.005 SOL - 0.015 SOL graduation fee, 206.9 M tokens), so every SOL-paired
   graduate starts with ``K_GRAD = 84.990 * 206.9e6 ~ 1.7585e10`` SOL*token. k only grows
   afterwards (LP fees, third-party deposits), so using ``K_GRAD`` is leak-free (needs no
   future reserve snapshot) and slightly CONSERVATIVE. The quote reserve at a historical price
   ``p`` (SOL per token) is ``sqrt(k * p)``. The bonding curve uses pump.fun's virtual reserves
   (30 SOL x 1,073,000,000 tokens, ``K_CURVE = 3.219e10``).
4. **Slippage / MEV buffer** - ``mev_bps`` per side (default 20 bps): sandwiches, landing a few
   slots late, quote drift between decision and landing.
5. **Network** - 5,000 lamports base + priority (default 0.0002 SOL per swap; parameter),
   converted at the SOL price of that minute and charged as USD per swap. The token-account
   rent (0.00204 SOL) is refunded when the account is closed after the sell -> modelled as 0.

``round_trip_cost_pct(usd_size, mcap_usd)`` reports the total for a buy followed by an immediate
sell at an unchanged mid price. Calibration against live Jupiter Ultra quotes is in
``calibrate()`` (``python research/lab/costs.py calibrate``) and DATASET.md.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

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


def context_for_coin(doc: dict, k_policy: str = "grad") -> CoinCostContext:
    """Cost context from a coin file. ``k_policy``:

    * ``"grad"`` (default, leak-free): SOL-paired -> ``K_GRAD`` (verified: live Jupiter quote
      impact on dead and live graduates gives k = 1.02-1.06 x K_GRAD; GeckoTerminal's
      reserve_in_usd is NOT reliable for dead pools - it implies ~0.22 x); other quotes -> current
      k (no launch constant known), shrunk by 2x as a conservative margin; Mayhem-mode coins ->
      min(current k, K_GRAD) because their pools are 100-10,000x shallower.
    * ``"min_now"``: min(K_GRAD, k measured from current reserves) - for calibration only.
    """
    cost = doc.get("cost") or {}
    launch = doc.get("launch") or {}
    qm = cost.get("quote_mint") or launch.get("quote_mint")
    quote = "SOL" if qm == SOL_QUOTE else "USDC" if qm == USDC_MINT else "OTHER"
    k_now = cost.get("k_now_quote_token")
    if launch.get("mayhem"):
        # Mayhem-mode coins "complete" with ~0.1-10 SOL instead of 85 SOL: their pools are tiny.
        # GeckoTerminal's reserve is the only (rough) estimate; never assume K_GRAD for them.
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

    @classmethod
    def from_lab(cls, lab: Path | None = None) -> "SolUsd":
        path = (lab or _lab()) / "sol_usd.json"
        try:
            return cls(json.loads(path.read_text())["candles"])
        except (OSError, ValueError, KeyError):
            return cls()

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


def _lab() -> Path:
    return Path(os.environ.get(
        "LAB_DATA", "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/lab"))


# --------------------------------------------------------------------------- calibration


def _ultra_order(input_mint: str, output_mint: str, amount: int) -> dict:
    import requests
    for attempt in range(6):
        r = requests.get("https://lite-api.jup.ag/ultra/v1/order",
                         params={"inputMint": input_mint, "outputMint": output_mint, "amount": amount}, timeout=30)
        time.sleep(1.1)  # ~1 req/s etiquette
        if r.status_code == 200:
            return r.json()
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"ultra order {output_mint}: {r.status_code} {r.text[:200]}")


def calibrate(n: int = 5, usd: float = 20.0, out: Path | None = None) -> list[dict]:
    """Live Ultra round trips (quotes only, nothing is signed) vs the model at the same mcap.

    Picks the ``n`` most recently traded SOL-paired graduates of the census whose PumpSwap pool
    still holds >= $5k of reserves (spread over the mcap range), quotes a ~$``usd`` buy
    SOL -> token and the sell of the quoted ``outAmount`` token -> SOL, and compares
    ``1 - sol_back / sol_in`` with the model (pool fee + Ultra fee + impact, no MEV buffer, no
    network fee - quotes carry neither), using k from the current reserves and from K_GRAD.
    """
    import requests
    lab = _lab()
    cen = json.loads((lab / "census.json").read_text())
    pools = json.loads((lab / "pools.json").read_text())["pools"]
    sol_mint = "So11111111111111111111111111111111111111112"
    cands = []
    for c in cen["coins"]:
        p = pools.get(c.get("pump_swap_pool") or "", {})
        if c.get("quote_mint") != SOL_QUOTE or p.get("missing"):
            continue
        try:
            res = float(p["reserve_in_usd"])
        except (TypeError, ValueError, KeyError):
            continue
        if res >= 5000:
            cands.append((c, p, res))
    # spread over market caps: sort by reserve, take evenly spaced picks
    cands.sort(key=lambda t: t[2])
    picks = [cands[int(i * (len(cands) - 1) / max(n - 1, 1))] for i in range(n)] if cands else []
    sol_px = float(requests.get("https://lite-api.jup.ag/price/v3", params={"ids": sol_mint},
                                timeout=30).json()[sol_mint]["usdPrice"])
    lamports = int(usd / sol_px * LAMPORTS_PER_SOL)
    rows = []
    model0 = CostModel(mev_bps=0.0, priority_sol=0.0, base_fee_lamports=0)
    for c, p, res in picks:
        mint = c["mint"]
        buy = _ultra_order(sol_mint, mint, lamports)
        tokens_raw = int(buy["outAmount"])
        sell = _ultra_order(mint, sol_mint, tokens_raw)
        back = int(sell["outAmount"])
        measured = (1 - back / lamports) * 100
        dec = int(c.get("base_decimals") or 6)
        # mid price from the pool (GeckoTerminal, fetched minutes earlier) and from the quotes themselves
        price_quote_mid = math.sqrt((lamports / tokens_raw) * (back / tokens_raw)) * 10 ** dec / LAMPORTS_PER_SOL * sol_px
        q_res = res / 2 / float(p["quote_token_price_usd"])
        k_now = q_res * q_res / float(p["base_token_price_quote_token"])
        ctx_now = CoinCostContext(k_sol=k_now)
        ctx_grad = CoinCostContext(k_sol=K_GRAD)
        mcap = price_quote_mid * PUMP_FEE_SUPPLY
        row = {
            "symbol": c["symbol"], "mint": mint, "mcap_usd": round(mcap), "pool_reserve_usd": round(res),
            "route": [h["swapInfo"]["label"] for h in buy.get("routePlan", [])],
            "sell_route": [h["swapInfo"]["label"] for h in sell.get("routePlan", [])],
            "ultra_fee_bps": [buy.get("feeBps"), sell.get("feeBps")],
            "sol_in": lamports / LAMPORTS_PER_SOL, "sol_back": back / LAMPORTS_PER_SOL,
            "measured_rt_pct": round(measured, 3),
            "model_rt_pct_k_now": round(round_trip_cost_pct(usd, mcap, model0, sol_px, ctx_now, False), 3),
            "model_rt_pct_k_grad": round(round_trip_cost_pct(usd, mcap, model0, sol_px, ctx_grad, False), 3),
            "pool_fee_bps": fee_bps(mcap, "pumpswap", sol_px),
            "k_now_over_k_grad": round(k_now / K_GRAD, 3),
            "price_impact_pct_ultra": [buy.get("priceImpactPct"), sell.get("priceImpactPct")],
            "ts": time.time(),
        }
        rows.append(row)
        print(json.dumps(row))
    out = out or lab / "calibration.json"
    out.write_text(json.dumps({"sol_usd": sol_px, "usd_size": usd, "rows": rows}, indent=1))
    return rows


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "calibrate":
        calibrate(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    else:
        m = CostModel()
        for mc in (30e3, 50e3, 100e3, 300e3, 1e6, 3e6, 10e6):
            print(f"mcap ${mc:>12,.0f}: fee {fee_bps(mc):6.1f} bps  RT $20 = {round_trip_cost_pct(20, mc, m):5.2f}%"
                  f"  RT $5 = {round_trip_cost_pct(5, mc, m):5.2f}%  RT $50 = {round_trip_cost_pct(50, mc, m):5.2f}%")

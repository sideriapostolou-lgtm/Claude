"""Cost model math (offline)."""

import math

import pytest

import costs
from costs import (K_CURVE, K_GRAD, CoinCostContext, CostModel, fee_bps, impact, quote_reserve_usd,
                   round_trip_cost_pct)

SOL = 100.0


@pytest.mark.parametrize("mcap_sol,bps", [
    (10, 125), (419.9, 125), (420, 120), (1469, 120), (1470, 115), (4420, 100), (9819, 100), (9820, 95),
    (54030, 52.5), (98239, 32.5), (98240, 30), (1e7, 30),
])
def test_pumpswap_sol_tiers(mcap_sol, bps):
    assert fee_bps(mcap_sol * SOL, "pumpswap", SOL) == bps


@pytest.mark.parametrize("mcap,bps", [(10_000, 125), (59_000, 120), (299_999, 120), (300_000, 115),
                                      (950_000, 100), (2_000_000, 95), (11_500_000, 53), (25_000_000, 30)])
def test_pumpswap_usdc_tiers(mcap, bps):
    assert fee_bps(mcap, "pumpswap", SOL, quote="USDC") == bps


def test_curve_noncanonical_and_unknown_quote():
    assert fee_bps(5e6, "curve", SOL) == 125
    assert fee_bps(5e6, "noncanonical", SOL) == 30
    assert fee_bps(5e6, "pumpswap", SOL, quote="OTHER") == 125


def test_graduation_constants():
    # pump.fun migrates ~85 SOL and 206.9M tokens; the curve ends at 115.005 virtual SOL / 279.9M tokens
    assert K_GRAD == pytest.approx(84.990359 * 206.9e6, rel=1e-6)
    assert K_CURVE == pytest.approx(3.219e10)
    p_grad_sol = 115.005359057 / 279.9e6
    # quote reserve of the fresh pool at the graduation price ~ 85 SOL
    assert quote_reserve_usd(p_grad_sol * SOL, K_GRAD, SOL) / SOL == pytest.approx(84.99, rel=2e-3)


def test_impact_signs_and_symmetry():
    p = 4e-5
    x = quote_reserve_usd(p, K_GRAD, SOL)
    buy = impact("buy", 20, p, K_GRAD, SOL)
    sell = impact("sell", 20, p, K_GRAD, SOL)
    assert buy > p > sell
    # small trades: impact ~ size / x on both sides
    assert buy / p - 1 == pytest.approx(20 / x, rel=1e-9)
    assert 1 - sell / p == pytest.approx((20 / x) / (1 + 20 / x), rel=1e-9)
    # bigger trade -> bigger impact; deeper pool (higher price, same k) -> smaller impact
    assert impact("buy", 50, p, K_GRAD, SOL) > buy
    assert impact("buy", 20, p * 100, K_GRAD, SOL) / (p * 100) < buy / p
    with pytest.raises(ValueError):
        impact("hold", 1, p, K_GRAD, SOL)


def test_buy_then_sell_constant_product_exact():
    """Without fees a buy then sell of the same tokens returns exactly the input (x*y=k)."""
    m = CostModel(ultra_bps=0, mev_bps=0, fee_mult=0.0)
    ctx = CoinCostContext()
    p = 1e-4
    tokens, _ = m.buy(20.0, p, ctx, SOL)
    back, _ = m.sell(tokens, p * (1 + 20 / quote_reserve_usd(p, K_GRAD, SOL)) ** 2, ctx, SOL)
    # after the buy the mid moved by (1+dx/x)^2; selling at the new mid returns the input
    assert back == pytest.approx(20.0, rel=1e-9)


def test_round_trip_at_20_on_typical_pool():
    m = CostModel()
    # fresh graduate (~$41k at SOL $100): 1.25 % pool fee per side + Ultra + MEV + impact + network
    rt = round_trip_cost_pct(20, 41_000, m, SOL)
    assert 3.4 < rt < 4.2
    # deeper / higher-tier coin is cheaper, tiny trade pays relatively more network
    assert round_trip_cost_pct(20, 5_000_000, m, SOL) < rt
    assert round_trip_cost_pct(5, 41_000, m, SOL) > rt
    # components: no MEV/network -> lower; stress x2 -> higher
    assert round_trip_cost_pct(20, 41_000, CostModel(mev_bps=0, priority_sol=0, base_fee_lamports=0), SOL,
                               include_network=False) < rt
    assert round_trip_cost_pct(20, 41_000, m.stressed(2.0), SOL) > rt


def test_network_fee():
    m = CostModel(priority_sol=0.0002)
    assert m.network_usd(100.0) == pytest.approx((5000 / 1e9 + 0.0002) * 100)


def test_fees_never_negative_and_sell_never_negative():
    m = CostModel()
    ctx = CoinCostContext()
    out, br = m.sell(1e12, 1e-9, ctx, SOL)  # dumping a huge bag into a dead pool
    assert 0 <= out < 1e12 * 1e-9
    assert br["impact_usd"] > 0
    assert math.isfinite(out)


def test_context_for_coin_policies():
    doc = {"cost": {"quote_mint": costs.SOL_QUOTE, "k_now_quote_token": K_GRAD * 3}}
    assert costs.context_for_coin(doc).k_sol == K_GRAD  # leak-free default ignores current reserves
    assert costs.context_for_coin(doc, "min_now").k_sol == K_GRAD
    doc["cost"]["k_now_quote_token"] = K_GRAD / 2
    assert costs.context_for_coin(doc, "min_now").k_sol == K_GRAD / 2
    other = costs.context_for_coin({"cost": {"quote_mint": "X", "k_now_quote_token": 1e6}})
    assert other.quote == "OTHER" and other.k_sol == 5e5

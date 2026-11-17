"""costs.py: exact port of research/lab/costs.py (50-case parity), the replay additions
(paper haircut instead of the MEV buffer, cost_scale ratchet) and the monotone-pessimism golden file."""

from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
from pathlib import Path

import pytest

from nightcrawler import costs

ROOT = Path(__file__).resolve().parents[1]
LAB_COSTS = ROOT / "research" / "lab" / "costs.py"
GOLDEN = Path(__file__).parent / "fixtures" / "costs_golden.json"


@pytest.fixture(scope="module")
def lab():
    if not LAB_COSTS.exists():
        pytest.skip("research/lab/costs.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("lab_costs_reference", LAB_COSTS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _cases(n: int = 50) -> list[dict]:
    rng = random.Random(20261008)
    quotes = ("SOL", "SOL", "SOL", "USDC", "OTHER")
    out = []
    for i in range(n):
        out.append({
            "usd": rng.uniform(1.0, 100.0),
            "mcap": 10 ** rng.uniform(math.log10(5e3), math.log10(5e7)),
            "sol_usd": rng.uniform(80.0, 250.0),
            "quote": quotes[i % len(quotes)],
            "k": costs.K_GRAD * 10 ** rng.uniform(-4, 1),
            "quote_usd": rng.uniform(0.5, 2.0),
            "stress": rng.choice((1.0, 0.5, 1.25, 1.5, 2.0)),
            "mev": rng.choice((0.0, 20.0, 100.0)),
            "priority": rng.choice((0.0, 0.0002, 0.001)),
            "curve": i % 7 == 3,
            "phase": ("pumpswap", "curve", "noncanonical")[i % 3],
        })
    return out


def test_constants_are_the_labs(lab) -> None:
    for name in ("ULTRA_FEE_BPS", "BONDING_CURVE_FEE_BPS", "NON_CANONICAL_FEE_BPS", "LAMPORTS_PER_SOL",
                 "BASE_FEE_LAMPORTS", "DEFAULT_PRIORITY_SOL", "DEFAULT_MEV_BPS", "PUMP_FEE_SUPPLY", "K_CURVE",
                 "K_GRAD", "GRAD_POOL_SOL", "GRAD_POOL_TOKENS", "PUMPSWAP_SOL_TIERS", "PUMPSWAP_USDC_TIERS",
                 "USDC_MINT", "SOL_QUOTE", "FALLBACK_SOL_USD"):
        assert getattr(costs, name) == getattr(lab, name), name


@pytest.mark.parametrize("case", _cases(), ids=lambda c: f"{c['quote']}-{c['mcap']:.0f}")
def test_port_matches_the_lab_model(lab, case) -> None:
    usd, mcap, sol, quote = case["usd"], case["mcap"], case["sol_usd"], case["quote"]
    price = mcap / costs.PUMP_FEE_SUPPLY
    assert _close(costs.fee_bps(mcap, case["phase"], sol, quote), lab.fee_bps(mcap, case["phase"], sol, quote))
    assert _close(costs.quote_reserve_usd(price, case["k"], sol), lab.quote_reserve_usd(price, case["k"], sol))
    for side in ("buy", "sell"):
        assert _close(costs.impact(side, usd, price, case["k"], sol), lab.impact(side, usd, price, case["k"], sol))

    knobs = {"mev_bps": case["mev"], "priority_sol": case["priority"]}
    ours = costs.CostModel(**knobs).stressed(case["stress"])
    theirs = lab.CostModel(**knobs).stressed(case["stress"])
    ctx_kw = {"k_sol": case["k"], "quote": quote, "quote_usd": case["quote_usd"]}
    ctx, lab_ctx = costs.CoinCostContext(**ctx_kw), lab.CoinCostContext(**ctx_kw)
    assert _close(ours.network_usd(sol), theirs.network_usd(sol))

    tokens, info = ours.buy(usd, price, ctx, sol, curve=case["curve"])
    lab_tokens, lab_info = theirs.buy(usd, price, lab_ctx, sol, curve=case["curve"])
    assert _close(tokens, lab_tokens) and info.keys() == lab_info.keys()
    assert all(_close(info[k], lab_info[k]) for k in info)
    back, info = ours.sell(tokens, price, ctx, sol, curve=case["curve"])
    lab_back, lab_info = theirs.sell(lab_tokens, price, lab_ctx, sol, curve=case["curve"])
    assert _close(back, lab_back) and all(_close(info[k], lab_info[k]) for k in info)

    for network in (True, False):
        assert _close(costs.round_trip_cost_pct(usd, mcap, ours, sol, ctx, network),
                      lab.round_trip_cost_pct(usd, mcap, theirs, sol, lab_ctx, network))


@pytest.mark.parametrize("doc", [
    {"launch": {"quote_mint": "11111111111111111111111111111111"}, "graduated_ts": 5},
    {"launch": {"quote_mint": "11111111111111111111111111111111", "mayhem": True}, "cost": {"k_now_quote_token": 3e8}},
    {"launch": {"quote_mint": "11111111111111111111111111111111", "mayhem": True}},
    {"cost": {"quote_mint": costs.USDC_MINT, "k_now_quote_token": 4e9, "quote_price_usd_now": 1.0}},
    {"cost": {"quote_mint": "Other1111", "k_now_quote_token": 2e9, "quote_price_usd_now": 0.3}},
    {"cost": {"quote_mint": "11111111111111111111111111111111", "k_now_quote_token": 1e9}},
])
@pytest.mark.parametrize("policy", ["grad", "min_now"])
def test_context_for_coin_matches(lab, doc, policy) -> None:
    ours, theirs = costs.context_for_coin(doc, policy), lab.context_for_coin(doc, policy)
    assert (ours.k_sol, ours.quote, ours.quote_usd, ours.graduated_ts) == (
        theirs.k_sol, theirs.quote, theirs.quote_usd, theirs.graduated_ts)


def test_sol_usd_lookup_matches(lab) -> None:
    rows = [[60 * i, 0, 0, 0, 100.0 + i, 0] for i in range(10)]
    ours, theirs = costs.SolUsd(rows), lab.SolUsd(rows)
    for ts in (-5, 0, 59, 60, 61, 300, 10_000):
        assert ours.at(ts) == theirs.at(ts)
    assert costs.SolUsd().at(1) == lab.SolUsd().at(1) == costs.FALLBACK_SOL_USD


# --------------------------------------------------------------------------- replay additions


def test_replay_model_swaps_the_mev_buffer_for_the_paper_haircut() -> None:
    model = costs.replay_model()
    assert model.mev_bps == costs.PAPER_SLIPPAGE_BPS == 100.0
    assert costs.replay_model(paper_slippage_bps=50.0).mev_bps == 50.0
    # everything else is the lab's default model
    lab_default = costs.CostModel()
    assert (model.ultra_bps, model.priority_sol, model.fee_mult, model.impact_mult) == (
        lab_default.ultra_bps, lab_default.priority_sol, lab_default.fee_mult, lab_default.impact_mult)


def test_cost_scale_only_raises_costs() -> None:
    assert costs.cost_scale(None, 50_000) == 1.0
    assert costs.cost_scale({"lt100k": 0.5}, 50_000) == 1.0  # a ratchet: never below 1
    assert costs.cost_scale({"lt100k": 1.3}, 50_000) == 1.3
    assert costs.cost_scale({"lt100k": 1.3}, 500_000) == 1.0  # another tier
    assert {costs.cost_tier(m) for m in (1, 99_999)} == {"lt100k"}
    assert costs.cost_tier(100_000) == "100k-1m" and costs.cost_tier(5e6) == "1m+"
    base = costs.round_trip_cost_pct(20, 200_000, costs.replay_model())
    assert costs.round_trip_cost_pct(20, 200_000, costs.replay_model(scale=1.2)) > base
    assert costs.round_trip_cost_pct(20, 200_000, costs.replay_model(scale=0.5)) == base


def test_side_fill_prices_a_buy_and_a_sell() -> None:
    model, ctx, sol = costs.replay_model(), costs.CoinCostContext(), 150.0
    price = 300_000 / costs.PUMP_FEE_SUPPLY
    buy, info = costs.side_fill(model, "buy", 20.0, price, ctx, sol)
    tokens, _ = model.buy(20.0, price, ctx, sol)
    assert buy == pytest.approx(20.0 / tokens) and buy > price
    assert info["impact_pct"] > 0 and info["liquidity_usd"] == pytest.approx(2 * info["x_usd"])
    sell, _ = costs.side_fill(model, "sell", 20.0, price, ctx, sol)
    usd_out, _ = model.sell(20.0 / price, price, ctx, sol)
    assert sell == pytest.approx(usd_out / (20.0 / price)) and sell < price
    with pytest.raises(ValueError):
        costs.side_fill(model, "hold", 20.0, price, ctx, sol)


def _golden_grid() -> list[tuple[float, float, float]]:
    return [(usd, mcap, sol) for usd in (5.0, 20.0, 50.0)
            for mcap in (30e3, 60e3, 100e3, 300e3, 1e6, 3e6, 10e6) for sol in (80.0, 150.0, 250.0)]


def _modelled(usd: float, mcap: float, sol: float) -> dict[str, float]:
    return {"replay": costs.round_trip_cost_pct(usd, mcap, costs.replay_model(), sol),
            "lab_default": costs.round_trip_cost_pct(usd, mcap, costs.CostModel(), sol)}


def test_monotone_pessimism_golden_file() -> None:
    """Modelled round-trip costs may only ever RISE: a change that lowers any of them fails here
    (regenerate the file in the same PR only for a cost INCREASE; see docs/LEARNING.md §4.4)."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows = {(r["usd"], r["mcap"], r["sol_usd"]): r for r in golden["rows"]}
    assert set(rows) == set(_golden_grid())
    for key in _golden_grid():
        now = _modelled(*key)
        for name, value in now.items():
            assert value >= rows[key][name] - 1e-12, f"{name} cost dropped at {key}: {value} < {rows[key][name]}"

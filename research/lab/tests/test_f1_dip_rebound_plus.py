"""F1 dip-rebound-plus: no-lookahead and logic tests (synthetic data; real data only if present)."""

import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

import harness as H
from costs import SolUsd
from harness import Coin, SimConfig

STRAT = Path(__file__).resolve().parents[1] / "strategies" / "f1-dip-rebound-plus.py"
spec = importlib.util.spec_from_file_location("f1_dip_rebound_plus", STRAT)
F1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F1)

T0 = 1_790_000_000 // 60 * 60
SOL = SolUsd()

PARAM_SETS = [
    dict(),
    dict(confirm="green2", exit="atr", min_age_min=0.0, min_vol_usd=0.0),
    dict(confirm="vol", exit="lowstop", min_age_min=0.0, min_vol_usd=500.0, max_entries=3),
    dict(confirm="hl", dd_min=0.2, dd_max=0.95, max_reb=3.0, min_age_min=0.0, min_vol_usd=0.0),
    dict(confirm="break+vol", exit="fixed", tp_frac=0.5, trail_pct=0.15, min_age_min=0.0, min_vol_usd=0.0,
         max_entries=5, lookback_min=60),
]


def pumpy(n=600, seed=1):
    """Random pump/dump/rebound path with bursts of volume (lots of dips for the strategy)."""
    rng = random.Random(seed)
    rows, p = [], 4e-5
    for i in range(n):
        o = p
        shock = rng.gauss(0, 0.06)
        if rng.random() < 0.03:
            shock += rng.choice([-0.5, 0.6, 1.0, -0.7])
        c = max(o * (1 + shock), 1e-9)
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.04)))
        low = min(o, c) * (1 - abs(rng.gauss(0, 0.04)))
        v = rng.choice([0.0, 0.0, rng.uniform(100, 3000), rng.uniform(3000, 40000)])
        rows.append([T0 + 60 * i, o, h, low, c, v])
        p = c
    return rows


def coin_from(rows, grad_bar=0, mint="SYN"):
    return Coin.from_rows(rows, mint=mint, created_ts=rows[0][0], graduated_ts=rows[grad_bar][0] + 30)


@pytest.mark.parametrize("params", PARAM_SETS)
def test_audit_lookahead_clean_on_synthetic(params):
    coins = [coin_from(pumpy(500, seed=s), grad_bar=s % 7, mint=f"SYN{s}") for s in range(8)]
    fac = F1.make(**params)
    res = H.run_per_coin(fac, coins, sol=SOL)
    assert res.trades, "the synthetic paths should trigger at least one trade"
    assert H.audit_lookahead(fac, coins, cuts_per_coin=6, seed=3, sol=SOL) == []


@pytest.mark.parametrize("params", PARAM_SETS[:3])
def test_future_bars_cannot_change_past_decisions(params):
    rows = pumpy(500, seed=21)
    coin = coin_from(rows)
    base = H.run_per_coin(F1.make(**params), [coin], sol=SOL, keep_decisions=True).decisions[coin.mint]
    assert base
    for cut in (120, 250, 400):
        future = [list(r) for r in rows]
        rng = random.Random(cut)
        for r in future[cut + 1:]:  # replace the future with garbage (huge spikes, crashes, volume)
            k = rng.choice([0.01, 50.0, 1.0])
            r[1:5] = [r[1] * k, r[2] * k * 2, r[3] * k / 2, r[4] * k]
            r[5] = rng.uniform(0, 1e6)
        alt = H.run_per_coin(F1.make(**params), [coin_from(future)], sol=SOL,
                             keep_decisions=True).decisions[coin.mint]
        assert [d for d in alt if d[0] <= cut] == [d for d in base if d[0] <= cut]


def _crafted(rebound_close: float, spike_vol: float = 30_000.0):
    """Graduated at bar 0; high 3e-5 at bar 10; low 0.9e-5 (-70 %) at bar 20; quiet; bar 31 rebounds."""
    rows = []
    for i in range(60):
        if i <= 10:
            p = 1e-5 + 2e-5 * i / 10
        elif i <= 20:
            p = 3e-5 - 2.1e-5 * (i - 10) / 10
        else:
            p = 0.95e-5
        rows.append([T0 + 60 * i, p, p * 1.01, p * 0.99, p, 1_000.0])
    rows[10][2] = 3e-5 * 1.01  # the high
    rows[20][3] = 0.9e-5  # the dip low
    rows[31] = [T0 + 60 * 31, 0.95e-5, rebound_close * 1.01, 0.95e-5, rebound_close, spike_vol]
    rows[32][1] = rebound_close
    return coin_from(rows)


BASE = dict(confirm="break+vol", min_age_min=0.0, min_vol_usd=2_000.0, dd_min=0.6, dd_max=0.8,
            max_reb=2.0, min_reb=1.05, min_since_high=5, min_mcap=1_000.0)


def test_entry_fires_on_confirmed_rebound_and_fills_next_open():
    coin = _crafted(1.2e-5)
    res = H.run_per_coin(F1.make(**BASE), [coin], sol=SOL, keep_decisions=True)
    buys = [d for d in res.decisions[coin.mint] if d[1].startswith("Buy")]
    assert buys and buys[0][0] == 31
    assert res.trades[0].entry_ts == coin.ts[32]  # decided at the close of 31 -> filled at the open of 32


def test_anti_chase_blocks_overextended_rebound():
    coin = _crafted(2.5e-5)  # 2.78x the low > max_reb 2.0
    res = H.run_per_coin(F1.make(**BASE), [coin], sol=SOL, keep_decisions=True)
    assert not [d for d in res.decisions[coin.mint] if d[1].startswith("Buy")]


def test_volume_confirmation_required():
    coin = _crafted(1.2e-5, spike_vol=1_500.0)  # no volume uptick
    res = H.run_per_coin(F1.make(**BASE), [coin], sol=SOL, keep_decisions=True)
    assert not [d for d in res.decisions[coin.mint] if d[1].startswith("Buy")]


def test_no_shared_state_between_instances():
    before = {k: v for k, v in vars(F1.DipReboundPlus).items() if not k.startswith("__")}
    coins = [coin_from(pumpy(300, seed=s), mint=f"S{s}") for s in range(4)]
    fac = F1.make(**PARAM_SETS[2])
    a = H.run_per_coin(fac, coins, sol=SOL)
    b = H.run_per_coin(fac, list(reversed(coins)), sol=SOL)
    key = lambda t: (t.mint, t.entry_ts, round(t.pnl_usd, 9))  # noqa: E731
    assert sorted(map(key, a.trades)) == sorted(map(key, b.trades))  # order of coins does not matter
    after = {k: v for k, v in vars(F1.DipReboundPlus).items() if not k.startswith("__")}
    assert before == after


def test_rejects_unknown_params():
    with pytest.raises(TypeError):
        F1.DipReboundPlus(dip=0.5)
    with pytest.raises(ValueError):
        F1.DipReboundPlus(confirm="moon")


@pytest.mark.skipif(not (H.LAB / "coins").exists(), reason="lab data not present")
def test_audit_lookahead_clean_on_real_train_coins():
    coins = H.load_coins(split="train", limit=80)
    for params in (dict(confirm="vol", dd_min=0.6, dd_max=0.8, max_reb=2.0, min_age_min=0.0),
                   dict(confirm="vol", dd_min=0.6, dd_max=0.8, max_reb=2.0, min_age_min=0.0, exit="lowstop",
                        r_mult=1.5, max_hold_min=120.0)):
        assert H.audit_lookahead(F1.make(**params), coins, cuts_per_coin=4, seed=5) == []

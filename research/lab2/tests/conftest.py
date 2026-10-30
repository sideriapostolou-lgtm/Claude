"""Shared fixtures: synthetic CryptoHouse-shaped frames (graduates / b2_coins / b2_bars) and temp ledgers."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

LAB2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB2))

import common as C  # noqa: E402

V0 = 17.584505289
POOLED = "ARu4n5mFdZogZAravu7CcizaojWnS6oqka37gdLT5SZn"
# FLOW/validation.json fixtures. VALID = the census-only record validate.py writes today (no date ranges: it covers
# the census day only); VALID_ALL adds a passing V1/V2/V4 range over every split, validated "after" any test data.
VALID = {"V1": {"pass": True}, "V2": {"chain_ok": 100, "transitions": 100}, "V3": {"both": 10, "coin_windows": 10},
         "V4": {"pass": True}}
VALID_ALL = {**VALID, "ranges": [{"lo_utc": "2026-09-01 00:00:00", "hi_utc": "2026-10-10 00:00:00",
                                  "validated_utc": "2030-01-01 00:00:00", "V1": {"pass": True},
                                  "V2": {"chain_ok": 100, "transitions": 100}, "V4": {"pass": True}}]}


def make_frames(n: int = 24, seed: int = 1, t0: int | None = None, spacing: int = 1800, n_minutes: int = 186,
                slow_every: int = 5, agent_every: int = 3, extra: dict | None = None):
    """Synthetic graduates + B2 tables. Coin i graduates at t0 + i * spacing (+ a random second); prices follow a
    constant-product random walk on the pricing reserve X = x + v; minute 0 contains the graduation."""
    rng = np.random.default_rng(seed)
    t0 = t0 if t0 is not None else C.utc_ts("2026-10-02 00:00")
    grads, coins, bars = [], [], []
    for i in range(n):
        g = t0 + i * spacing + int(rng.integers(0, 60))
        mint, pool = f"MINT{i:03d}{seed}pump", f"POOL{i:03d}{seed}"
        slow = slow_every and i % slow_every == slow_every - 1
        c_ts = g - (int(rng.integers(3600, 7200)) if slow else int(rng.integers(1, 5)))
        grads.append({
            "mint": mint, "g_slot": 1000 + i, "g_ts": g, "c_slot": 0 if slow else 900 + i, "c_ts": 0 if slow else c_ts,
            "has_create": 0 if slow else 1, "completer": f"COMP{i}", "rsol_complete": 85.005,
            "creator": "" if slow else f"CREATOR{i}", "create_user": "" if slow else f"CU{i}", "name": "" if slow else f"N{i}",
            "symbol": "" if slow else f"S{i}", "uri": "", "is_mayhem": 0, "curve_quote_mint": "1" * 32,
            "token_program": "Tokenkeg", "vsol0": 0.0 if slow else 30.0, "curve_buy_sol": 90.0, "curve_sell_sol": 5.0,
            "curve_buy_tok": 8e8, "curve_sell_tok": 1e7, "curve_n_buys": 50, "curve_n_sells": 5, "curve_n_buyers": 40,
            "curve_n_sellers": 4, "curve_top1_buy_sol": 30.0, "curve_top3_buy_sol": 60.0, "completer_sol": 10.0,
            "completer30": f"COMP{i}", "l_buy_sol": 0.0 if slow else 40.0, "l_n_buyers": 0 if slow else 12,
            "z_n_buyers": 0 if slow else 2, "z_buy_tok": 0.0 if slow else 1e8, "sn60_n_buyers": 0 if slow else 5,
            "creator_buy_sol": 0.0 if slow else 1.0, "first20_buy_sol": 0.0 if slow else 20.0,
            "pool": pool, "pool_slot": 1001 + i, "pool_ts": g + 2, "pool_quote_mint": C.WSOL, "pool_creator": "PC",
            "pool_base0": 206.9e6, "pool_quote0": 84.990359, "n_pools": 1,   # = X0 = x0 + v (real x0 = 84.99 - v)
            "grad_delay_s": float(g - c_ts) if not slow else float(g), "sol_quoted": True, "mayhem": False,
        })
        agent = agent_every and i % agent_every == 0
        known = float(g + 40) if agent else math.nan
        top = [[POOLED, 9.0, 0.0], [f"W{i}a", 5.0, 0.0], [f"AGENT{i}" if agent else f"W{i}b", 4.0, 0.0], [f"W{i}c", 1.0, 0.0]]
        coins.append({
            "pool": pool, "mint": mint, "g_ts": g, "virt_sol": V0, "n_chunks": 4, "w_exact": True,
            "w120_buy_sol": 30.0, "w120_sell_sol": 3.0, "w120_n_buyers": 9, "w120_n_sellers": 2,
            "w300_buy_sol": 50.0, "w300_sell_sol": 9.0, "w300_n_buyers": 15, "w300_n_sellers": 6,
            "w120_top10": json.dumps(top), "w300_top10": json.dumps(top), "agent_plan_rule": bool(agent),
            "agent_present": bool(agent), "agent_wallet": f"AGENT{i}" if agent else "",
            "agent_slices": 29 if agent else 0, "agent_sol": 17.58 if agent else 0.0,
            "agent_median_gap": 12.0 if agent else math.nan, "agent_gap_cv": 0.05 if agent else math.nan,
            "agent_gap_band_share": 1.0 if agent else math.nan, "agent_first_offset_s": 2.0 if agent else math.nan,
            "agent_known_at": known, "w120_top5_share_ex_agent": 0.7, "grad_delay_s": 3.0,
        })
        m0 = g // 60 * 60
        X, y = 84.990359, 206.9e6
        for j in range(n_minutes):
            if j > 0 and rng.random() < 0.15:
                continue   # minute without trades
            k = X * y * 1.0001
            p_open = X / y
            dX = float(rng.normal(0.3 if j < 10 else 0.0, 4.0))
            X1 = max(X + dX, 20.0)
            y1 = k / X1
            p1 = X1 / y1
            hi = max(p_open, p1) * (1 + 0.04 * rng.random())
            lo = min(p_open, p1) * (1 - 0.04 * rng.random())
            bars.append({"minute_ts": m0 + 60 * j, "n_buys": 5, "n_sells": 3, "n_dust": 1,
                         "buy_sol": max(dX, 0) + 2.0, "sell_sol": max(-dX, 0) + 2.0, "buy_tok": 1e6, "sell_tok": 1e6,
                         "n_buyers": 4, "n_sellers": 3, "top5_buy_sol": 2.0, "open": p_open, "high": hi, "low": lo,
                         "close": p1, "x_close": X1 - V0, "y_close": y1, "mint": mint, "pool": pool, "g_ts": g,
                         "minute_idx": j, "agent_buy_sol": 2.4 if (agent and j < 6) else 0.0, "price_repaired": 0})
            X, y = X1, y1
    gdf, cdf, bdf = pd.DataFrame(grads), pd.DataFrame(coins), pd.DataFrame(bars)
    return gdf, cdf, bdf


@pytest.fixture
def frames():
    return make_frames()


@pytest.fixture
def ds_train(frames):
    g, c, b = frames
    return C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=C.SolUsd(fallback=100.0))


@pytest.fixture(autouse=True)
def _never_the_real_ledger(tmp_path, monkeypatch):
    """Safety net: no test may write research/lab2/trials.json or shortlists/ (tests opt into tmp_ledger to read)."""
    monkeypatch.setenv("LAB2_TRIALS", str(tmp_path / "_autouse_trials.json"))
    monkeypatch.setenv("LAB2_SHORTLISTS", str(tmp_path / "_autouse_shortlists"))


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    p = tmp_path / "trials.json"
    monkeypatch.setenv("LAB2_TRIALS", str(p))
    monkeypatch.setenv("LAB2_SHORTLISTS", str(tmp_path / "shortlists"))
    return p


def real_flow_available() -> bool:
    f = C.flow_dir()
    return all((f / n).exists() for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))

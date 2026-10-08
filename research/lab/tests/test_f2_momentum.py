"""No-lookahead proofs for the F2 momentum strategies (strategies/f2-momentum.py).

1. ``audit_lookahead`` (truncation at random bars) is clean for every entry family on synthetic coins.
2. Replacing everything after a cut with garbage never changes a decision or fill at or before the cut.
3. If the lab data is present, the audit is also clean on real TRAIN coins (skipped otherwise).
"""

import importlib.util
import random
import sys
from pathlib import Path

import pytest

import harness as H
from costs import SolUsd
from harness import Coin

LAB_DIR = Path(__file__).resolve().parents[1]
T0 = 1_790_000_000 // 60 * 60
SOL = SolUsd()


def _load():
    name = "f2_momentum"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, LAB_DIR / "strategies" / "f2-momentum.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F2 = _load()

# permissive parameters so that every family trades often on a random walk
FAMILIES = {
    "breakout": F2.F2Params(entry="breakout", lookback=10, vol_mult=1.2, vol_base=10, min_vol_usd=1000,
                            max_age_min=600, mc_lo=1_000, max_entries=20, stop_pct=0.1, trail_pct=0.1,
                            max_hold_min=20),
    "breakout_atr_failfast": F2.F2Params(entry="breakout", lookback=10, vol_mult=1.2, vol_base=10,
                                         min_vol_usd=1000, max_age_min=600, mc_lo=1_000, max_entries=20,
                                         higher_lows=True, max_ext=1.0, stop_pct=0.2, trail_pct=None,
                                         trail_atr_mult=3.0, fail_bars=3, fail_ret=0.0, max_hold_min=60,
                                         tp_pct=0.1, tp_fraction=0.5, trail_after_tp=True),
    "early": F2.F2Params(entry="early", check_min=30, max_age_min=40, min_rel_grad=0.5, max_dd=0.6,
                         min_vol_usd=1000, vol_win=15, mc_lo=1_000, stop_pct=0.1, trail_pct=0.1, max_hold_min=60),
    "squeeze": F2.F2Params(entry="squeeze", squeeze_win=10, squeeze_range=0.6, squeeze_active=5, vol_mult=1.2,
                           vol_base=10, min_vol_usd=1000, max_age_min=600, mc_lo=1_000, max_entries=20,
                           stop_pct=0.1, trail_pct=0.1, max_hold_min=20),
}


def walk(n=400, seed=1, p0=5e-5, vol=0.04):
    rng = random.Random(seed)
    rows, p = [], p0
    for i in range(n):
        o = p
        c = max(o * (1 + rng.gauss(0.002, vol)), 1e-9)
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        low = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        v = rng.uniform(0, 5000) * (6 if rng.random() < 0.1 else 1)
        rows.append([T0 + 60 * i, o, h, low, c, v])
        p = c
    return rows


@pytest.mark.parametrize("fam", list(FAMILIES))
def test_audit_lookahead_clean_on_synthetic(fam):
    fac = F2.factory(FAMILIES[fam])
    coins = [Coin.from_rows(walk(400, seed), mint=f"S{seed}") for seed in range(1, 9)]
    res = H.run_per_coin(fac, coins, sol=SOL)
    assert res.trades, f"{fam}: the test parameters must trade"
    assert H.audit_lookahead(fac, coins, cuts_per_coin=6, sol=SOL) == []


@pytest.mark.parametrize("fam", list(FAMILIES))
@pytest.mark.parametrize("seed", [3, 4])
def test_garbage_future_never_changes_past(fam, seed):
    fac = F2.factory(FAMILIES[fam])
    rows = walk(400, seed)
    base = H.run_per_coin(fac, [Coin.from_rows(rows)], sol=SOL, keep_decisions=True)
    rng = random.Random(seed + 100)
    for cut in (45, 120, 250, 380):
        mutated = [list(r) for r in rows[:cut + 1]]
        for r in rows[cut + 1:]:
            p = rng.uniform(1e-6, 1e-3)
            mutated.append([r[0], p, p * 3, p / 3, p * rng.uniform(0.3, 3), rng.uniform(0, 1e6)])
        res = H.run_per_coin(fac, [Coin.from_rows(mutated)], sol=SOL, keep_decisions=True)
        d0 = [d for d in base.decisions["TEST"] if d[0] <= cut]
        d1 = [d for d in res.decisions["TEST"] if d[0] <= cut]
        assert d0 == d1, f"{fam} cut {cut}: decisions changed by future bars"
        lim = rows[cut][0]
        f0 = [(f.ts, f.side, f.mid, f.reason) for t in base.trades for f in t.fills
              if f.ts <= lim and f.reason != "end_of_data"]
        f1 = [(f.ts, f.side, f.mid, f.reason) for t in res.trades for f in t.fills
              if f.ts <= lim and f.reason != "end_of_data"]
        assert f0 == f1, f"{fam} cut {cut}: fills changed by future bars"


def test_no_class_state_shared_between_instances():
    a = F2.F2Momentum(FAMILIES["breakout"])
    b = F2.F2Momentum(FAMILIES["early"])
    a.on_coin_start({"created_ts": 0.0, "supply": 1e9})
    b.on_coin_start({"created_ts": 0.0, "supply": 1e9})
    a.entries = 5
    assert b.entries == 0
    assert "entries" not in vars(F2.F2Momentum)


def test_no_entry_before_graduation():
    rows = walk(200, 5)
    grad = rows[100][0] + 30
    coin = Coin.from_rows(rows, graduated_ts=grad)
    res = H.run_per_coin(F2.factory(FAMILIES["breakout"]), [coin], sol=SOL)
    assert all(t.decision_ts >= grad for t in res.trades)


def _real_coins(n=40):
    try:
        coins = H.load_coins(split="train")
    except Exception:  # pragma: no cover - data not on this machine
        return []
    return coins[:n]


@pytest.mark.skipif(not (H.LAB / "coins").exists(), reason="lab data not present")
def test_audit_lookahead_clean_on_real_train_coins():
    coins = _real_coins(60)
    if not coins:
        pytest.skip("no train coins")
    for prm in FAMILIES.values():
        assert H.audit_lookahead(F2.factory(prm), coins, cuts_per_coin=2) == []

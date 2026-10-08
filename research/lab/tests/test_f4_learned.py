"""No-lookahead proofs for the F4 learned-filter strategy (strategies/f4-learned.py).

1. The causal feature matrix is prefix-stable: the matrix of a coin truncated at bar k equals the
   first k+1 rows of the full matrix (synthetic and real coins), so row i never sees bar i+1.
2. ``audit_lookahead`` is clean for the live-style ``ModelScorer`` on synthetic and real coins.
3. Replacing every bar after a cut with garbage never changes a decision or fill at or before it.
4. Entries fill at the open of the bar after the decision.
5. The fast ``TableScorer`` used in the search makes exactly the same decisions as ``ModelScorer``
   on real TRAIN coins (so the search results are those of the live-style strategy).
6. The label simulator reproduces the harness's net returns exactly.
"""

import importlib.util
import math
import random
import sys
from pathlib import Path

import numpy as np
import pytest

import harness as H
from costs import CostModel, SolUsd
from harness import Coin

LAB_DIR = Path(__file__).resolve().parents[1]
T0 = 1_790_000_000 // 60 * 60
SOL = SolUsd()


def _load(name, rel):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, LAB_DIR / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F4 = _load("f4_learned", "strategies/f4-learned.py")


class ToyModel:
    """Deterministic stand-in for a trained model: a fixed logistic function of a few features."""

    kind = "toy"

    def score(self, X):
        X = np.atleast_2d(X)
        z = 3 * X[:, F4.FIDX["r5"]] + X[:, F4.FIDX["vratio_5_60"]] - 2 * X[:, F4.FIDX["rv15"]]
        return 1 / (1 + np.exp(-np.nan_to_num(z)))


TOY_PARAMS = F4.F4Params(threshold=0.55, tp=0.1, sl=0.1, hold_min=10, max_entries=5, max_age_min=600,
                         min_vol10_usd=100, min_mcap_sol=1.0)


def walk(n=400, seed=1, p0=5e-5, vol=0.04):
    rng = random.Random(seed)
    rows, p = [], p0
    for i in range(n):
        o = p
        c = max(o * (1 + rng.gauss(0.002, vol)), 1e-9)
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        low = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        v = 0.0 if rng.random() < 0.15 else rng.uniform(0, 5000) * (6 if rng.random() < 0.1 else 1)
        rows.append([T0 + 60 * i, o, h, low, c, v])
        p = c
    return rows


def _toy_factory():
    return F4.factory(TOY_PARAMS, F4.ModelScorer(ToyModel(), TOY_PARAMS.gate))


def _same(a, b):
    return np.array_equal(np.isnan(a), np.isnan(b)) and np.array_equal(np.nan_to_num(a), np.nan_to_num(b))


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_feature_matrix_is_prefix_stable_synthetic(seed):
    rows = walk(300, seed)
    coin = Coin.from_rows(rows, graduated_ts=rows[20][0] + 30, created_ts=rows[0][0])
    full = F4.coin_features(coin, SOL)
    for cut in (0, 1, 5, 19, 20, 21, 59, 60, 61, 150, 299):
        part = F4.coin_features(H.truncate(coin, cut), SOL)
        assert _same(full[:cut + 1], part), f"cut {cut}"


def test_view_features_equal_matrix_row():
    rows = walk(200, 4)
    coin = Coin.from_rows(rows, graduated_ts=rows[10][0], created_ts=rows[0][0] - 30)
    full = F4.coin_features(coin, SOL)
    meta = {"mint": coin.mint, "created_ts": coin.created_ts, "launch": coin.launch, "supply": 1e9}
    for i in (10, 11, 50, 120, 199):
        row = F4.view_features(H.View(coin, i, meta, SOL))
        assert _same(full[i], row), i


def test_audit_lookahead_clean_on_synthetic():
    fac = _toy_factory()
    coins = [Coin.from_rows(walk(400, s), mint=f"S{s}") for s in range(1, 7)]
    res = H.run_per_coin(fac, coins, sol=SOL)
    assert res.trades, "the toy parameters must trade"
    assert H.audit_lookahead(fac, coins, cuts_per_coin=6, sol=SOL) == []


@pytest.mark.parametrize("seed", [3, 4])
def test_garbage_future_never_changes_past(seed):
    fac = _toy_factory()
    rows = walk(400, seed)
    base = H.run_per_coin(fac, [Coin.from_rows(rows)], sol=SOL, keep_decisions=True)
    assert base.trades
    rng = random.Random(seed + 100)
    for cut in (45, 120, 250, 380):
        mutated = [list(r) for r in rows[:cut + 1]]
        for r in rows[cut + 1:]:
            p = rng.uniform(1e-6, 1e-3)
            mutated.append([r[0], p, p * 3, p / 3, p * rng.uniform(0.3, 3), rng.uniform(0, 1e6)])
        res = H.run_per_coin(fac, [Coin.from_rows(mutated)], sol=SOL, keep_decisions=True)
        assert [d for d in base.decisions["TEST"] if d[0] <= cut] == \
            [d for d in res.decisions["TEST"] if d[0] <= cut], f"cut {cut}: decisions changed"
        lim = rows[cut][0]
        f0 = [(f.ts, f.side, f.mid, f.reason) for t in base.trades for f in t.fills
              if f.ts <= lim and f.reason != "end_of_data"]
        f1 = [(f.ts, f.side, f.mid, f.reason) for t in res.trades for f in t.fills
              if f.ts <= lim and f.reason != "end_of_data"]
        assert f0 == f1, f"cut {cut}: fills changed"


def test_entries_fill_at_next_open():
    rows = walk(400, 2)
    coin = Coin.from_rows(rows)
    res = H.run_per_coin(_toy_factory(), [coin], sol=SOL)
    assert res.trades
    for t in res.trades:
        j = int(np.searchsorted(coin.ts, t.decision_ts - 60))  # decision = close of bar j
        assert t.entry_ts == coin.ts[j + 1]
        assert t.entry_mid == coin.o[j + 1]


def test_no_entry_before_graduation_and_no_shared_state():
    rows = walk(200, 5)
    grad = rows[100][0] + 30
    coin = Coin.from_rows(rows, graduated_ts=grad)
    res = H.run_per_coin(_toy_factory(), [coin], sol=SOL)
    assert all(t.decision_ts >= grad for t in res.trades)
    a, b = _toy_factory()(), _toy_factory()()
    a.on_coin_start({})
    b.on_coin_start({})
    a.attempts = 3
    assert b.attempts == 0 and "attempts" not in vars(F4.F4Learned)


def test_label_simulator_matches_harness():
    S = _load("f4_learned_search", "f4_learned_search.py")
    cost = CostModel()

    class At(H.Strategy):
        def __init__(self, bar, ex):
            self.bar, self.ex = bar, ex

        def on_candle(self, i, view, pos):
            return H.Buy(exits=self.ex) if i == self.bar and pos is None else None

    for seed in (1, 6):
        coin = Coin.from_rows(walk(300, seed, vol=0.08))
        for i in (5, 40, 100, 200):
            for tp, sl, hold in ((0.15, 0.15, 15), (0.6, 0.3, 60)):
                y = S.simulate_returns(coin, np.array([i]), tp, sl, hold * 60, cost, SOL)[0]
                tr = H.run_per_coin(lambda: At(i, H.Exits(stop_pct=sl, take_profit_pct=tp, max_hold_s=hold * 60)),
                                    [coin], sol=SOL).trades[0]
                if math.isnan(y):
                    assert tr.exit_reason == "end_of_data"
                else:
                    assert abs(tr.ret - y) < 1e-9, (seed, i, tp, sl, hold, tr.ret, y, tr.exit_reason)


# --------------------------------------------------------------------------- real data (skipped if absent)

HAVE_DATA = (H.LAB / "coins").exists()
MODEL = H.LAB / "f4" / "models"


def _train_coins(n):
    coins = H.load_coins(split="train")
    return coins[::max(len(coins) // n, 1)][:n]


@pytest.mark.skipif(not HAVE_DATA, reason="lab data not present")
def test_feature_matrix_is_prefix_stable_real():
    sol = SolUsd.from_lab()
    rng = random.Random(0)
    for coin in _train_coins(25):
        full = F4.coin_features(coin, sol)
        for _ in range(3):
            cut = rng.randrange(0, coin.n)
            assert _same(full[:cut + 1], F4.coin_features(H.truncate(coin, cut), sol)), (coin.symbol, cut)


def _finalist_models():
    if not MODEL.exists():
        return []
    import json
    fin = LAB_DIR / "finalists" / "f4-learned.json"
    if fin.exists():
        recs = json.loads(fin.read_text())
        out = []
        for r in recs:
            p = r["params"]
            out.append((MODEL / f"{p['label']}_{p['model']}.pkl", F4.F4Params(**p["strategy"])))
        if out:
            return out
    pk = sorted(MODEL.glob("*.pkl"))[:1]
    return [(pk[0], F4.F4Params(threshold=0.3, tp=0.15, sl=0.15, hold_min=15))] if pk else []


@pytest.mark.skipif(not HAVE_DATA or not _finalist_models(), reason="lab data / trained models not present")
def test_audit_lookahead_clean_real_model_scorer():
    sol = SolUsd.from_lab()
    coins = _train_coins(40)
    for path, prm in _finalist_models():
        model = F4.FoldEnsemble.load(path)
        loose = F4.F4Params(**{**prm.__dict__, "threshold": min(prm.threshold, 0.2), "max_entries": 3})
        fac = F4.factory(loose, F4.ModelScorer(model, loose.gate))
        assert H.audit_lookahead(fac, coins, cuts_per_coin=2, sol=sol) == []


@pytest.mark.skipif(not HAVE_DATA or not _finalist_models(), reason="lab data / trained models not present")
def test_table_scorer_matches_model_scorer_on_real_coins():
    """The search's precomputed tables must reproduce the live-style scorer bar for bar."""
    sol = SolUsd.from_lab()
    coins = _train_coins(30)
    for path, prm in _finalist_models():
        model = F4.FoldEnsemble.load(path)
        table = {}
        for c in coins:
            Fm = F4.coin_features(c, sol)
            g = F4.gate_mask(Fm, F4.vol10(c.v), prm.gate)
            s = np.full(c.n, np.nan)
            if g.any():
                s[g] = model.score(np.nan_to_num(Fm[g], nan=0.0, posinf=0.0, neginf=0.0).clip(-50, 50))
            table[c.mint] = s
        loose = F4.F4Params(**{**prm.__dict__, "threshold": min(prm.threshold, 0.2), "max_entries": 3})
        live = H.run_per_coin(F4.factory(loose, F4.ModelScorer(model, loose.gate)), coins, sol=sol,
                              keep_decisions=True)
        fast = H.run_per_coin(F4.factory(loose, F4.TableScorer(table)), coins, sol=sol, keep_decisions=True)
        assert live.decisions == fast.decisions
        assert [round(t.ret, 12) for t in live.trades] == [round(t.ret, 12) for t in fast.trades]

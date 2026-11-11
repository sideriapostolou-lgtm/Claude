"""No-lookahead proofs for the F3 lifecycle strategies (strategies/f3-lifecycle.py).

1. ``audit_lookahead`` (truncation at random bars) is clean for every entry family on synthetic
   lifecycle coins (spike, dump, base, second leg, noise) with parameters that trade often.
2. Replacing every bar after a cut with garbage never changes a decision or fill at or before the cut.
3. Lifecycle state (graduation index, instant flag, peak, drawdown, first-15 volume) is identical when
   computed on a truncated copy, and no state lives on the class.
4. No entry before graduation; ``max_entries`` holds even when a trade is stopped out inside its fill bar.
5. If the lab data is present, the audit is also clean on real TRAIN coins (skipped otherwise).
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
    name = "f3_lifecycle"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, LAB_DIR / "strategies" / "f3-lifecycle.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F3 = _load()
P = F3.F3Params

# permissive parameters so that every family trades on the synthetic coins
FAMILIES = {
    "runner": P(entry="runner", cls="any", t_lo=5, t_hi=300, v15_min=100, mc_lo=1000, rp_lo=0.0, rp_hi=1.0,
                max_entries=5, stop_pct=0.2, trail_pct=0.2, max_hold_min=20),
    "runner_dead_exit": P(entry="runner", cls="any", t_lo=5, t_hi=300, v15_min=100, mc_lo=1000, max_entries=5,
                          stop_pct=None, max_hold_min=60, dead_n=5, dead_v=8000),
    "second_leg": P(entry="second_leg", t_lo=5, dump=0.3, W=10, rng=3.0, vmin=100, vk=1.0, mc_lo=1000,
                    max_entries=10, struct_stop=True, stop_pct=None, trail_pct=0.15, max_hold_min=30),
    "base_bounce": P(entry="base_bounce", t_lo=5, dump=0.3, W=10, rng=3.0, vmin=100, q=0.5, mc_lo=1000,
                     max_entries=10, struct_stop=True, stop_pct=None, tp_base_top=True, max_hold_min=20),
    "drifter": P(entry="drifter", cls="any", t_lo=5, W=10, rng=3.0, vmin=100, mc_lo=1000, max_entries=10,
                 stop_pct=0.1, trail_pct=0.1, max_hold_min=30),
    "gated_dip": P(entry="gated_dip", cls="any", t_lo=5, t_hi=1e4, mc_lo=1000, decay_min=0.01, max_entries=10,
                   stop_pct=0.18, tp_pct=0.4, tp_fraction=0.5, trail_pct=0.15, trail_after_tp=True,
                   max_hold_min=60),
}


def lifecycle_rows(n=420, seed=1, p0=5e-5):
    """Synthetic graduate: repeated spike -> dump -> base -> rebound cycles with noise and volume."""
    rng = random.Random(seed)
    rows, p = [], p0
    phase_len = rng.randint(40, 70)
    for i in range(n):
        ph = (i % phase_len) / phase_len
        if ph < 0.15:
            drift, vol, v = 0.05, 0.05, rng.uniform(3000, 12000)  # spike
        elif ph < 0.35:
            drift, vol, v = -0.06, 0.05, rng.uniform(2000, 8000)  # dump
        elif ph < 0.75:
            drift, vol, v = 0.0, 0.015, rng.uniform(200, 2000)  # base
        else:
            drift, vol, v = 0.03, 0.04, rng.uniform(1000, 9000)  # second leg / rebound
        o = p
        c = max(o * (1 + rng.gauss(drift, vol)), 1e-9)
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        low = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        rows.append([T0 + 60 * i, o, h, low, c, v])
        p = c
    return rows


def coins(n=8, length=420):
    return [Coin.from_rows(lifecycle_rows(length, seed), mint=f"S{seed}") for seed in range(1, n + 1)]


@pytest.mark.parametrize("fam", list(FAMILIES))
def test_audit_lookahead_clean_on_synthetic(fam):
    fac = F3.factory(FAMILIES[fam])
    cs = coins()
    res = H.run_per_coin(fac, cs, sol=SOL)
    assert res.trades, f"{fam}: the test parameters must trade"
    assert H.audit_lookahead(fac, cs, cuts_per_coin=6, sol=SOL) == []


@pytest.mark.parametrize("fam", list(FAMILIES))
@pytest.mark.parametrize("seed", [3, 4])
def test_garbage_future_never_changes_past(fam, seed):
    fac = F3.factory(FAMILIES[fam])
    rows = lifecycle_rows(420, seed)
    base = H.run_per_coin(fac, [Coin.from_rows(rows)], sol=SOL, keep_decisions=True)
    rng = random.Random(seed + 100)
    for cut in (30, 90, 200, 330, 410):
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


def _state_after(strat, coin, last):
    meta = {"mint": coin.mint, "created_ts": coin.created_ts, "supply": coin.supply, "launch": dict(coin.launch)}
    strat.on_coin_start(meta)
    for i in range(last + 1):
        strat.on_candle(i, H.View(coin, i, meta, SOL), None)
    return (strat.g, strat.instant, strat.grad_mcap, strat.peak, strat.max_dd, strat.first15)


@pytest.mark.parametrize("cut", [10, 60, 150, 300])
def test_lifecycle_state_equal_on_truncated_copy(cut):
    rows = lifecycle_rows(420, 7)
    grad = rows[3][0] + 30  # organic graduate: graduates inside bar 3
    full = Coin.from_rows(rows, created_ts=rows[0][0], graduated_ts=grad)
    part = H.truncate(full, cut)
    prm = P(entry="runner", t_lo=1e6)  # never trades: only the state is compared
    assert _state_after(F3.F3Lifecycle(prm), full, cut) == _state_after(F3.F3Lifecycle(prm), part, cut)


def test_no_class_state_shared_between_instances():
    a = F3.F3Lifecycle(FAMILIES["runner"])
    b = F3.F3Lifecycle(FAMILIES["drifter"])
    meta = {"created_ts": 0.0, "supply": 1e9}
    a.on_coin_start(meta)
    b.on_coin_start(meta)
    a.entries, a.peak = 5, 123.0
    assert b.entries == 0 and b.peak == 0.0
    for attr in ("entries", "peak", "max_dd", "g", "first15", "candles", "_pending", "_in_pos"):
        assert attr not in vars(F3.F3Lifecycle)


@pytest.mark.parametrize("fam", list(FAMILIES))
def test_no_entry_before_graduation(fam):
    rows = lifecycle_rows(300, 5)
    grad = rows[120][0] + 30
    coin = Coin.from_rows(rows, created_ts=rows[0][0], graduated_ts=grad)
    res = H.run_per_coin(F3.factory(FAMILIES[fam]), [coin], sol=SOL)
    assert all(t.decision_ts >= grad for t in res.trades)


def test_max_entries_counts_trades_closed_inside_fill_bar():
    # a rug every 15 bars: entries are stopped out inside their fill bar; max_entries=1 must still hold
    rows, p = [], 5e-5
    for i in range(300):
        o = p
        rug = i % 15 == 0 and i > 0
        c = o * (0.3 if rug else 1.01)
        rows.append([T0 + 60 * i, o, max(o, c) * 1.001, min(o, c) * 0.999, c, 5000.0])
        p = c if not rug else c * 3.0
    coin = Coin.from_rows(rows)
    # age at the close of bar i is i+1 minutes -> first decision at bar 14, filled at the open of rug bar 15
    prm = P(entry="runner", cls="any", t_lo=15, t_hi=1e4, v15_min=0, mc_lo=0, max_entries=1, stop_pct=0.05,
            max_hold_min=600)
    res = H.run_per_coin(F3.factory(prm), [coin], sol=SOL)
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.entry_ts == rows[15][0] and t.exit_ts == rows[15][0], "the scenario must stop out inside the fill bar"


@pytest.mark.skipif(not (H.LAB / "coins").exists(), reason="lab data not present")
def test_audit_lookahead_clean_on_real_train_coins():
    try:
        cs = H.load_coins(split="train")[:60]
    except Exception:  # pragma: no cover - data not on this machine
        cs = []
    if not cs:
        pytest.skip("no train coins")
    real = {
        "runner": P(entry="runner", cls="any", t_lo=10, t_hi=600, v15_min=500, mc_lo=3000, max_entries=3,
                    stop_pct=0.2, trail_pct=0.2, max_hold_min=60),
        "second_leg": P(entry="second_leg", t_lo=10, dump=0.3, W=20, rng=2.5, vmin=500, vk=1.0, mc_lo=3000,
                        max_entries=5, struct_stop=True, stop_pct=None, trail_pct=0.2, max_hold_min=60),
        "base_bounce": P(entry="base_bounce", t_lo=10, dump=0.3, W=20, rng=2.5, vmin=500, q=0.4, mc_lo=3000,
                         max_entries=5, struct_stop=True, stop_pct=None, tp_base_top=True, max_hold_min=30),
        "drifter": P(entry="drifter", cls="any", t_lo=30, W=30, rng=1.5, vmin=500, mc_lo=3000, max_entries=3,
                     stop_pct=0.1, max_hold_min=120, dead_n=10, dead_v=200),
        "gated_dip": P(entry="gated_dip", cls="any", t_lo=10, t_hi=1e4, mc_lo=3000, decay_min=0.05, max_entries=3,
                       stop_pct=0.18, max_hold_min=60),
    }
    for fam, prm in real.items():
        assert H.audit_lookahead(F3.factory(prm), cs, cuts_per_coin=2) == [], fam

"""Tests for research/lab2/q10.py (LP1, be the house): the 6-config grid, eligibility and the control universe,
the LP position's arithmetic on controlled coins (costs only, boost leverage on a halving, retained LP fees,
waiting protocol fees excluded), placebo matching, the decision rules, no lookahead of the eligibility on real
census bars, stage refusals and the debug hide."""

import json
import math
import shutil
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import q10 as Q
from conftest import make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
HERE = C.Path(__file__).resolve().parent.parent
N = C.N_BARS
X0, Y0, V = 84.990359056, 206.9e6, 17.584505289


def test_grid_is_six_distinct_trials_in_tie_break_order():
    assert len(Q.GRID) == 6 <= Q.BUDGET_TRIALS and len({C.params_hash(p) for p in Q.GRID}) == 6
    assert Q.CONFIG_ORDER == ("M6|D0.7", "M6|D0.5", "M6|deadline", "M3|D0.7", "M3|D0.5", "M3|deadline")
    for p in Q.GRID:
        assert Q.params_of(Q.config_key(p)) == p
        for k, v in Q.FIXED.items():
            assert p[k] == v
    assert Q.PRIMARY_PARAMS in Q.GRID and Q.config_key(Q.PRIMARY_PARAMS) == "M6|D0.7"
    with pytest.raises(ValueError):
        Q.make_params(4, 0.7)
    with pytest.raises(ValueError):
        Q.make_params(3, 0.9)
    assert Q.DECL["position_kind"] == "lp"


# --------------------------------------------------------------------------- controlled coins


def _coin(price, *, vol_sol=0.0, growth=None, v=None, m0=1_790_000_000, g_off=28.0):
    """A CoinData with a given price path (len N), per-bar volume, optional pool growth (retained LP fees:
    X and y scale together at flat price) and virtual reserve path."""
    price = np.asarray(price, float)
    growth = np.ones(N) if growth is None else np.asarray(growth, float)
    v = np.full(N, V) if v is None else np.asarray(v, float)
    p0 = X0 / Y0
    X = X0 * np.sqrt(price / p0) * growth                 # constant product on the effective reserve
    y = X / price
    arr = {k: np.zeros(N) for k in C.BAR_ARRAYS}
    for k in ("o", "h", "l", "c"):
        arr[k] = price.copy()
    arr["X"], arr["y"], arr["x_real"] = X, y, X - v
    arr["buy_sol"] = np.full(N, vol_sol / 2.0)
    arr["sell_sol"] = np.full(N, vol_sol / 2.0)
    arr["traded"] = np.ones(N)
    for k in arr:
        arr[k].setflags(write=False)
    return C.CoinData(mint="MINT", pool="POOL", g=m0 + g_off, m0=m0, row={}, arr=MappingProxyType(arr),
                      agent_nan=np.full(N, np.nan), init_X=X0, init_y=Y0, legal={}, split="train")


def _t_dec(cd):
    t = Q.first_decision_time(cd)
    assert Q.ENTRY_MIN_AGE_S <= t - cd.g < Q.ENTRY_MIN_AGE_S + 60.0
    return t


def test_lp_flat_quiet_pool_costs_only():
    p0 = X0 / Y0
    cd = _coin(np.full(N, p0))                                   # flat price, no volume
    row = Q.simulate_lp(cd, _t_dec(cd), Q.FILL, 100.0, None)
    assert row is not None and row["reason"] == "quiet" and row["bars_held"] == 3
    assert -0.03 < row["ret_net"] < 0.0 and -0.03 < row["ret_5050"] < 0.0      # fees, impact, 4 network fees
    assert row["fee_income_sol"] == 0.0 and row["cash_sol"] >= 0.0 and row["lp_share"] > 0
    assert row["sol_in"] == pytest.approx(20.0 / 100.0) and row["age_dec_s"] >= Q.ENTRY_MIN_AGE_S
    assert row["ret_mid"] == pytest.approx(0.0) and row["is_placebo"] is False and row["stop_pct"] is None
    assert math.isclose(row["v_ref"], V, rel_tol=1e-9) and row["t_in"] == row["t_dec"] + Q.FILL.latency_s


def test_lp_is_levered_against_the_boost_on_a_halving():
    """PREREG 1: value ratio (2X sqrt(r) - v) / (2X - v) instead of sqrt(r)."""
    p0 = X0 / Y0
    cd0 = _coin(np.full(N, p0), vol_sol=10.0)
    t = _t_dec(cd0)
    jf = cd0.bar_of(t + Q.FILL.latency_s)
    price = np.full(N, p0)
    price[jf + 5:] = p0 / 2.0
    cd = _coin(price, vol_sol=10.0)
    row = Q.simulate_lp(cd, t, Q.FILL, 100.0, None)
    assert row is not None and row["reason"] == "deadline" and row["ret_mid"] == pytest.approx(-0.5)
    s, S, cash = row["lp_share"], row["sol_in"], row["cash_sol"]
    predicted = (cash + s * (2 * X0 * math.sqrt(0.5) - V)) / S - 1.0
    plain = (cash + s * 2 * X0 * math.sqrt(0.5)) / S - 1.0 - 0.0            # a pool without the boost
    assert abs(row["ret_net"] - predicted) < 0.03                              # costs explain the rest
    assert predicted < plain                                                   # the boost makes it worse
    assert row["ret_net"] < row["ret_5050"] < 0                                # the 50/50 hold loses 25 % + costs


def test_retained_lp_fees_accrue_to_the_position():
    p0 = X0 / Y0
    growth = 1.0 + 0.002 * np.arange(N)                      # the pool grows 0.2 % per bar at flat price
    cd = _coin(np.full(N, p0), vol_sol=10.0, growth=growth)
    row = Q.simulate_lp(cd, _t_dec(cd), Q.FILL, 100.0, None)
    assert row is not None and row["reason"] == "deadline" and row["ret_net"] > 0.25 and row["fee_income_sol"] > 0
    assert row["ret_net"] > row["ret_5050"] > -0.05            # the hold without fees is flat minus costs


def test_waiting_protocol_fees_are_not_the_lps():
    p0 = X0 / Y0
    cd_a = _coin(np.full(N, p0), vol_sol=10.0)
    t = _t_dec(cd_a)
    jf = cd_a.bar_of(t + Q.FILL.latency_s)
    v = np.full(N, V)
    v[jf + 3:] = V - 1.0                                      # 1 SOL of fees kept in the vault: x_real up, X flat
    cd_b = _coin(np.full(N, p0), vol_sol=10.0, v=v)
    ra, rb = Q.simulate_lp(cd_a, t, Q.FILL, 100.0, None), Q.simulate_lp(cd_b, t, Q.FILL, 100.0, None)
    assert ra is not None and rb is not None
    assert rb["ret_net"] == pytest.approx(ra["ret_net"], abs=1e-12) and rb["v_exit"] == pytest.approx(V - 1.0)


def test_stop_and_same_bar_exits():
    p0 = X0 / Y0
    cd0 = _coin(np.full(N, p0), vol_sol=10.0)
    t = _t_dec(cd0)
    jf = cd0.bar_of(t + Q.FILL.latency_s)
    price = np.full(N, p0)
    price[jf + 4:] = 0.6 * p0
    cd = _coin(price, vol_sol=10.0)
    r1 = Q.simulate_lp(cd, t, Q.FILL, 100.0, 0.7)
    assert r1 is not None and r1["reason"] == "stop" and r1["bars_held"] == 6 and r1["stop_pct"] == pytest.approx(0.3)
    r0 = Q.simulate_lp(cd, t, C.FillConfig(), 100.0, 0.7)    # same-bar exits: one bar earlier
    assert r0 is not None and r0["reason"] == "stop" and r0["bars_held"] == 5
    assert Q.simulate_lp(cd, cd.bar_start(N - 1) + C.GRID_OFFSET_S, Q.FILL, 100.0, None) is None   # no room
    late = Q.simulate_lp(cd, cd.bar_start(N - 2) + C.GRID_OFFSET_S, Q.FILL, 100.0, None)         # last chance
    assert late is not None and late["reason"] in ("deadline", "horizon") and late["bars_held"] == 2


def _snap(age_s=900.0, alive=True, mcap_sol=500.0, r15=0.05, xr=60.0, buy=100.0, sell=100.0, k=20):
    bars = SimpleNamespace(x_real=np.full(k, xr), buy_sol=np.full(k, buy / 15.0), sell_sol=np.full(k, sell / 15.0))
    return SimpleNamespace(age_s=age_s, alive=lambda *a: alive, mcap_sol=mcap_sol, ret=lambda w: r15, bars=bars,
                           k=k, mint="M")


def test_eligibility_and_control_universe():
    p3, p6 = Q.make_params(3, 0.7), Q.make_params(6, None)
    s = _snap()                                                # V15 = 200 SOL, x_real 60 -> ratio 3.33
    assert Q.control_ok(s) and Q.eligible(s, p3) and not Q.eligible(s, p6)
    assert Q._vol_ratio(s) == pytest.approx(200.0 / 60.0)
    assert not Q.eligible(_snap(r15=0.25), p3) and not Q.eligible(_snap(r15=-0.21), p3)
    assert not Q.eligible(_snap(r15=float("nan")), p3) and not Q.eligible(_snap(r15=None), p3)
    assert not Q.control_ok(_snap(mcap_sol=419.0)) and not Q.control_ok(_snap(alive=False))
    assert not Q.control_ok(_snap(age_s=599.0)) and not Q.eligible(_snap(xr=0.0), p3)
    assert Q.eligible(_snap(buy=200.0, sell=200.0), p6)


def _dataset(split="train"):
    g, c, b = make_frames()
    cen = C.Census.empty()
    if split == "final_train":
        created = g["c_ts"] if "c_ts" in g else g["g_ts"] - 600.0
        cts = {str(m): float(t) for m, t in zip(g["mint"], created, strict=True)}
        cts = {m: (t if t == t else float(g.loc[g["mint"] == m, "g_ts"].iloc[0]) - 600.0) for m, t in cts.items()}
        cen = C.Census(MappingProxyType({m: "final_train" for m in cts}), MappingProxyType(cts), math.inf, math.inf,
                       float(C.FINAL_LO), float(C.FINAL_LO))
    ds = C.Dataset.from_frames(split, g, c, b, census=cen, sol=SOL)
    assert len(ds) >= 10
    return ds


def test_trades_placebo_and_backtest_on_synthetic_coins(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "eligible", lambda snap, p: Q.control_ok(snap))    # every alive coin enters
    monkeypatch.setattr(C, "check_sol_coverage", lambda ds: None)
    ds = _dataset()
    p = Q.make_params(3, 0.7)
    t = Q.lp_trades(ds, p, Q.FILL)
    assert len(t) >= 5 and t["mint"].is_unique and set(t["reason"]) <= {"stop", "quiet", "deadline", "horizon"}
    assert (t["age_dec_s"] >= Q.ENTRY_MIN_AGE_S).all() and (t["t_in"] == t["t_dec"] + 30.0).all()
    assert t["ret_net"].between(-1.0, 5.0).all() and t["lp_share"].gt(0).all() and t["cash_sol"].ge(0).all()
    pl = Q.lp_placebo(ds, p, Q.FILL, t, n_draws=3, seed=1)
    assert len(pl) > 0 and pl["is_placebo"].all() and set(pl["signal"]) <= set(range(len(t)))
    assert (pl.groupby("signal").size() <= 3).all() and (pl["mint"] != pl["signal_mint"]).all()
    ages = pl.merge(t[["age_dec_s"]], left_on="signal", right_index=True, suffixes=("", "_sig"))
    assert (abs(ages["age_dec_s"] - ages["age_dec_s_sig"]) <= 180.0).all()        # +-120 s, then the grid
    res = Q.lp_backtest(ds, p, Q.FILL, n_placebo=2, stress={"x": C.FillConfig()}, ledger_path=tmp_path / "l.json")
    assert isinstance(res, C.Result) and len(res.trades) == len(t) and set(res.stress) == {"x"}
    assert res.meta["new_trial"] is True and res.meta["params"] == p
    assert res.meta["declarations"]["position_kind"] == "lp"
    d = C.describe(res.trades, B=50)
    assert d["n"] == len(t) and "mean" in d
    assert set(Q.lp_decomposition(res.trades, B=50)) >= {"ret_mid_mean", "ret_5050_mean", "lp_minus_5050"}


def test_direction_reading():
    assert Q.direction({"n": 10, "placebo": {"diff_ci95": (0.1, 0.2)}}) == "UNDERPOWERED"
    assert Q.direction({"n": 40, "placebo": {"diff_ci95": (0.1, 0.2)}}) == "BEATS_RANDOM"
    assert Q.direction({"n": 40, "placebo": {"diff_ci95": (-0.2, -0.1)}}) == "WORSE_THAN_RANDOM"
    assert Q.direction({"n": 40, "placebo": {"diff_ci95": (-0.1, 0.1)}}) == "NEITHER"


def _ev(n, mean, ci_lo, mw2, pdiff, p=None):
    return {"n": n, "mean": mean, "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.2), "mean_without_top2": mw2,
            "placebo": None if pdiff is None else {"mean_diff": pdiff, "diff_ci95": None},
            "params_hash": C.params_hash(p) if p else "h", "config": Q.config_key(p) if p else "c", "direction": None}


def test_decide_train_top_two_and_tie_break():
    evals = {Q.config_key(p): _ev(50, -0.01, -0.05, -0.02, -0.01, p) for p in Q.GRID}
    assert Q.decide_train(evals)["verdict"] == "NO_CONFIG"
    low = {Q.config_key(p): _ev(29, 0.2, 0.1, 0.1, 0.1, p) for p in Q.GRID}
    assert Q.decide_train(low)["verdict"] == "UNDERPOWERED_TRAIN"
    a, b, c = Q.make_params(3, 0.5), Q.make_params(6, None), Q.make_params(6, 0.7)
    good = dict(evals)
    good[Q.config_key(a)] = _ev(40, 0.05, 0.02, 0.03, 0.04, a)
    good[Q.config_key(b)] = _ev(90, 0.04, 0.02, 0.03, 0.04, b)        # same CI low, lower mean -> 2nd
    good[Q.config_key(c)] = _ev(90, 0.09, 0.01, 0.03, -0.01, c)       # fails the judged control
    d = Q.decide_train(good)
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_keys"] == [Q.config_key(a), Q.config_key(b)]
    assert d["shortlist"] == [a, b]
    tie = dict(evals)
    tie[Q.config_key(a)] = _ev(40, 0.05, 0.02, 0.03, 0.04, a)
    tie[Q.config_key(c)] = _ev(40, 0.05, 0.02, 0.03, 0.04, c)
    assert Q.decide_train(tie)["shortlist_keys"] == [Q.config_key(c), Q.config_key(a)]   # M6 before M3


def test_decide_val():
    p1, p2 = Q.make_params(6, 0.7), Q.make_params(3, None)
    d = Q.decide_val({"sl1": _ev(20, 0.01, 0, 0.005, 0, p1), "sl2": _ev(20, 0.04, 0, 0.02, 0, p2)}, ["sl1", "sl2"])
    assert d["candidate_role"] == "sl2" and d["twin_role"] == "sl1" and d["verdict"] == "SELECTED"
    assert Q.decide_val({"sl1": _ev(40, -0.01, 0, -0.02, 0, p1)}, ["sl1"])["verdict"] == "FAIL_VAL"
    assert Q.decide_val({"sl1": _ev(4, 0.3, 0, 0.3, 0, p1)}, ["sl1"])["verdict"] == "UNDERPOWERED_VAL"


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_eligibility_real_census_train():
    """The entry decision (alive, tier, |R15|, V15 / x_real) is unchanged when the data after tau is garbage."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(31)
    pick = [full.mints[int(i)] for i in rng.choice(len(full.mints), size=16, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    p3, p6 = Q.make_params(3, 0.7), Q.make_params(6, None)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for age in (600.0, 1800.0 + 60.0 * 3, float(rng.uniform(4000, 6900))):
            t = Q._decision_time(cd, cd.bar_of(cd.g + age - C.GRID_OFFSET_S) - 1)
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:
                continue
            a, b = clean.asof(m, t), dirty.asof(m, t)
            fa = (Q.control_ok(a), Q.eligible(a, p3), Q.eligible(a, p6), Q._vol_ratio(a))
            fb = (Q.control_ok(b), Q.eligible(b, p3), Q.eligible(b, p6), Q._vol_ratio(b))
            assert fa[:3] == fb[:3] and (fa[3] == fb[3] or (math.isnan(fa[3]) and math.isnan(fb[3])))
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


def _out(tmp_path):
    out = tmp_path / "Q10"
    out.mkdir()
    shutil.copy(HERE / "Q10" / "PREREG.md", out / "PREREG.md")
    return out


def test_stage_refusals(tmp_path, monkeypatch):
    out = tmp_path / "Q10"
    out.mkdir()
    with pytest.raises(Q.Q10Refused, match="PREREG.md missing"):
        Q.check_prereqs("debug", out)
    shutil.copy(HERE / "Q10" / "PREREG.md", out / "PREREG.md")
    assert Q.check_prereqs("debug", out)["stage"] == "debug"
    monkeypatch.setattr(C, "validation_gates", lambda split, flow=None: (True, []))
    with pytest.raises(Q.Q10Refused, match="no TRAIN result"):
        Q.check_prereqs("val", out)
    (out / "prereg.lock").write_text(json.dumps({"sha256": "0" * 64}))
    with pytest.raises(Q.Q10Refused, match="PREREG.md changed"):
        Q.check_prereqs("train", out)
    (out / "prereg.lock").unlink()
    (out / "train.json").write_text(json.dumps({"provisional": False, "decision": {"verdict": "NO_CONFIG"}}))
    with pytest.raises(Q.Q10Refused, match="TRAIN decision NO_CONFIG"):
        Q.check_prereqs("val", out)
    with pytest.raises(Q.Q10Refused, match="already ran on complete data"):
        Q.check_prereqs("train", out)
    monkeypatch.setattr(C, "validation_gates", lambda split, flow=None: (False, ["V2 failed"]))
    with pytest.raises(Q.Q10Refused, match="data first"):
        Q.check_prereqs("train", out)


def test_debug_stage_hides_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "eligible", lambda snap, p: Q.control_ok(snap))
    ds = _dataset("final_train")
    out = _out(tmp_path)
    doc = Q.run_stage("debug", out_dir=out, ds=ds, ledger_path=tmp_path / "dbg.json", B=50, n_placebo=2)
    assert doc["debug_only"] and doc["decision"]["verdict"] == "DEBUG" and doc["event_counts"]["coins"] == len(ds)
    assert set(doc["configs"]) == set(Q.CONFIG_ORDER)
    for e in doc["configs"].values():
        assert "mean" not in e and "lp" not in e and e["returns"].startswith("hidden") and e["n"] > 0
    md = (out / "debug.md").read_text()
    assert "hidden" in md and "Event counts" in md and "LP decomposition" not in md
    led = json.loads((tmp_path / "dbg.json").read_text())
    assert all(r["debug"] and r["mean"] is None for r in led["runs"])

"""Lab 3 tests: engine arithmetic on a synthetic panel (one-bar lag, costs, universe gating, rebalance filter),
metrics, exposure-preserving placebo, benchmarks, the signals' basic behaviour, decision rules and a full
synthetic TRAIN run."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import core as C  # noqa: E402
import hypotheses as H  # noqa: E402
import run as R  # noqa: E402


def _panel(n_days=900, assets=("AAA", "BBB", "CCC"), seed=0, start="2022-06-01") -> C.Panel:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n_days, freq="D", tz="UTC")
    rows = []
    for j, a in enumerate(assets):
        drift = (0.001, 0.0, -0.001)[j % 3]
        lr = rng.normal(drift, 0.03, n_days)
        close = 100.0 * np.exp(np.cumsum(lr))
        for i, t in enumerate(idx):
            rows.append({"asset": a, "ts": int(t.timestamp()), "open": close[i] * (1 + rng.normal(0, 0.002)),
                         "high": close[i] * 1.02, "low": close[i] * 0.98, "close": close[i], "volume": 1e6, "src": "x"})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.normalize()
    return C.panel(df)


def test_universe_mask_needs_history_and_volume():
    P = _panel(n_days=400)
    U = C.universe_mask(P, min_history=200, min_vol_usd=1.0)
    assert not U.iloc[:200].any().any() and U.iloc[250:].all().all()
    U2 = C.universe_mask(P, min_history=200, min_vol_usd=1e12)
    assert not U2.any().any()


def test_engine_lags_one_bar_and_charges_turnover():
    P = _panel(n_days=400, assets=("AAA",))
    U = pd.DataFrame(True, index=P.dates, columns=P.assets)
    tgt = pd.DataFrame(0.0, index=P.dates, columns=P.assets)
    tgt.iloc[300:350] = 1.0                                 # long for 50 days
    costs = C.Costs(bps_side=25.0, network_usd=0.02, capital_usd=100.0)
    run = C.backtest(P, tgt, "train", costs, U)             # train split covers these synthetic dates
    held = run.held["AAA"]
    assert held.iloc[300] == 0.0 and held.iloc[301] == 1.0 and held.iloc[350] == 1.0 and held.iloc[351] == 0.0
    r = P.close["AAA"].pct_change().fillna(0.0)
    expect_gross = r.iloc[301:351].sum()
    assert run.gross.sum() == pytest.approx(expect_gross, rel=1e-9)
    assert run.turnover.sum() == pytest.approx(2.0)          # one buy, one sell
    assert run.cost.sum() == pytest.approx(2 * 25.0 / 1e4 + 2 * 0.02 / 100.0)
    assert (run.ret - (run.gross - run.cost)).abs().max() < 1e-12
    assert run.exposure.iloc[301:351].mean() == pytest.approx(1.0) and run.exposure.iloc[:300].sum() == 0.0


def test_rebalance_filter_and_equal_weights():
    P = _panel(n_days=400)
    U = pd.DataFrame(True, index=P.dates, columns=P.assets)
    tgt = pd.DataFrame(0.0, index=P.dates, columns=P.assets)
    tgt.iloc[100:, tgt.columns.get_loc("AAA")] = 0.50
    tgt.iloc[200:, tgt.columns.get_loc("AAA")] = 0.52         # a 2 % change: filtered
    tgt.iloc[300:, tgt.columns.get_loc("AAA")] = 0.70         # 18 %: traded
    run = C.backtest(P, tgt, "train", C.Costs(), U)
    h = run.held["AAA"]
    assert h.iloc[150] == 0.5 and h.iloc[250] == 0.5 and h.iloc[350] == 0.7
    assert run.exposure.iloc[350] == pytest.approx(0.7 / 3)  # equal weight across 3 universe assets


def test_out_of_universe_is_flat():
    P = _panel(n_days=400)
    U = pd.DataFrame(True, index=P.dates, columns=P.assets)
    U["BBB"] = False
    tgt = pd.DataFrame(1.0, index=P.dates, columns=P.assets)
    run = C.backtest(P, tgt, "train", C.Costs(), U)
    assert (run.held["BBB"] == 0).all() and run.n_universe.iloc[-1] == 2


def test_describe_and_drawdown():
    r = pd.Series([0.1, -0.5, 0.2, 0.0], index=pd.date_range("2024-01-01", periods=4, tz="UTC"))
    d = C.describe(r)
    assert d["max_drawdown"] == pytest.approx(-0.5) and d["total_return"] == pytest.approx(1.1 * 0.5 * 1.2 - 1)
    assert d["share_positive_days"] == 0.5 and d["n_days"] == 4
    assert C.describe(pd.Series([0.01], index=pd.date_range("2024-01-01", periods=1, tz="UTC")))["sharpe"] is None
    ci = C.block_bootstrap_ci(np.random.default_rng(0).normal(0.001, 0.01, 400), block=30, B=500)
    assert ci is not None and ci[0] < 0.001 < ci[1]


def test_placebo_preserves_exposure_and_randomises_timing():
    P = _panel(n_days=600, assets=("AAA", "BBB"))
    U = C.universe_mask(P, min_history=100, min_vol_usd=1.0)
    tgt = H.t1_signal(P, {"L": 60})
    sh = C.shuffle_positions(tgt, U, seed=3)
    for a in P.assets:
        u = U[a].to_numpy(bool)
        assert sh[a].to_numpy()[u].sum() == pytest.approx(tgt[a].to_numpy()[u].sum())   # same exposure
    assert (sh != tgt).to_numpy().any()
    runs = C.placebo_runs(P, tgt, "train", C.Costs(), U, n=5, seed=1)
    cmp = C.placebo_compare(C.backtest(P, tgt, "train", C.Costs(), U), runs, B=300)
    assert cmp["n_placebo"] == 5 and 0.0 <= cmp["sharpe_p_value"] <= 1.0 and cmp["excess_ci95"] is not None


def test_signals_are_in_range_and_use_no_future():
    P = _panel(n_days=700)
    for hyp in (H.T1, H.T2, H.R1, H.X1):
        for p in hyp["GRID"]:
            s = hyp["signal"](P, p)
            assert s.shape == P.close.shape and s.min().min() >= 0.0 and s.max().max() <= 1.0, hyp["HYP"]
            # a change to the LAST bar never moves earlier targets (no lookahead)
            P2 = C.Panel(open=P.open, high=P.high, low=P.low, close=P.close.copy(), volume_usd=P.volume_usd)
            P2.close.iloc[-1] *= 3.0
            s2 = hyp["signal"](P2, p)
            assert s.iloc[:-1].equals(s2.iloc[:-1]), (hyp["HYP"], p)
    # T1 mechanics: a monotonically rising close is always long after the warm-up
    P3 = _panel(n_days=500, assets=("UPP",))
    P3.close["UPP"] = np.linspace(1, 2, 500)
    assert H.t1_signal(P3, {"L": 30}).iloc[40:].eq(1.0).all().all()
    assert H.t2_signal(P3, {"kind": "sma", "N": 50}).iloc[60:].eq(1.0).all().all()


def test_decision_rules():
    bh = {"sharpe": 0.8, "max_drawdown": -0.6, "cagr": 0.5}
    good = {"sharpe": 1.2, "cagr": 0.4, "max_drawdown": -0.3,
            "placebo": {"excess_ci95": (0.0001, 0.001), "excess_daily_mean": 0.0005}}
    bad = {"sharpe": 0.9, "cagr": 0.4, "max_drawdown": -0.7,
           "placebo": {"excess_ci95": (-0.001, 0.001), "excess_daily_mean": 0.0}}
    assert R.qualifies(good, bh)[0] and not R.qualifies(bad, bh)[0]
    grid = {"a": {"L": 1}, "b": {"L": 2}, "c": {"L": 3}}
    d = R.decide_train({"a": good, "b": {**good, "sharpe": 1.5}, "c": bad}, {"buy_hold_ew": bh}, grid)
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_keys"] == ["b", "a"]
    assert d["shortlist"] == [{"L": 2}, {"L": 1}]
    assert R.decide_train({"c": bad}, {"buy_hold_ew": bh}, grid)["verdict"] == "NO_CONFIG"
    v = R.decide_val({"a": good, "b": {**good, "sharpe": 0.3}}, ["a", "b"])
    assert v["verdict"] == "SELECTED" and v["candidate"] == "a" and v["twin"] == ["b"]
    assert R.decide_val({"a": {**good, "sharpe": -0.1}}, ["a"])["verdict"] == "FAIL_VAL"
    assert R.decide_test(good, bh)["verdict"] == "PASS" and R.decide_test(bad, bh)["verdict"] == "FAIL"


def test_one_look_guard(tmp_path, monkeypatch):
    with pytest.raises(C.Refused, match="one-look"):
        C.check_split_allowed("T1", "test", tmp_path, env={})
    C.check_split_allowed("T1", "test", tmp_path, env={"LAB3_ALLOW_TEST": "1"})
    (tmp_path / "test.json").write_text("{}")
    with pytest.raises(C.Refused, match="already spent"):
        C.check_split_allowed("T1", "test", tmp_path, env={"LAB3_ALLOW_TEST": "1"})


def test_ledger_counts_trials(tmp_path, monkeypatch):
    led = tmp_path / "trials.json"
    monkeypatch.setattr(C, "LAB2_LEDGER", tmp_path / "none.json")
    a = C.record_run("T1", {"L": 30}, "train", {"sharpe": 1.0}, led)
    b = C.record_run("T1", {"L": 30}, "train", {"sharpe": 1.0}, led)
    c = C.record_run("T1", {"L": 60}, "train", {"sharpe": 0.5}, led)
    assert a["new_trial"] and not b["new_trial"] and c["new_trial"] and c["n_trials_total"] == 2
    assert len(json.loads(led.read_text())["runs"]) == 3


def test_full_train_stage_on_synthetic_panel(tmp_path, monkeypatch):
    P = _panel(n_days=900, seed=4)
    monkeypatch.setattr(C, "LAB2_LEDGER", tmp_path / "none.json")
    doc = R.run_stage("T1", "train", n_placebo=3, out_root=tmp_path, ledger=tmp_path / "trials.json", P=P)
    assert set(doc["configs"]) == {H.T1["config_key"](p) for p in H.T1["GRID"]}
    assert doc["decision"]["verdict"] in ("SHORTLISTED", "NO_CONFIG") and (tmp_path / "T1" / "train.md").exists()
    for e in doc["configs"].values():
        assert e["n_days"] > 0 and "sharpe" in e and e["placebo"]["n_placebo"] == 3 and "by_year" in e
    assert doc["benchmarks"]["buy_hold_ew"]["n_days"] == doc["configs"]["L30"]["n_days"]
    assert math.isfinite(doc["configs"]["L30"]["max_drawdown"])

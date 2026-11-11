"""Tests for research/lab2/o1.py: the 6-config grid, timing and the class/alive gate, placebo eligibility, the
reading and decision rules, no lookahead on real census bars (debug third), stage refusals and the debug hide."""

import json
import shutil
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import o1 as O
from conftest import make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
HERE = C.Path(__file__).resolve().parent.parent


def test_grid_is_six_distinct_trials():
    assert len(O.GRID) == 6 <= 12
    assert len({C.params_hash(p) for p in O.GRID}) == 6
    assert {(p["timing"], p["exit"]) for p in O.GRID} == {(t, e) for t in O.TIMING_GRID for e in O.EXIT_GRID}
    for p in O.GRID:
        for k, v in O.FIXED.items():
            assert p[k] == v
        assert p["stop_pct"] == O.EXITS[p["exit"]]["stop_pct"] and p["max_hold_s"] == O.EXITS[p["exit"]]["max_hold_s"]
    assert O.PRIMARY_PARAMS in O.GRID and O.config_key(O.PRIMARY_PARAMS) == "r0|r0exit"
    with pytest.raises(ValueError):
        O.make_params("t45", "r0exit")
    with pytest.raises(ValueError):
        O.make_params("t30", "trail")


def test_target_age_fixed_and_r0_random_in_window():
    assert O.target_age_s("m", "t30") == 1800.0 and O.target_age_s("m", "t60") == 3600.0
    ages = [O.target_age_s(f"MINT{i:03d}pump", "r0") for i in range(200)]
    assert all(1800.0 <= a <= 115 * 60.0 for a in ages) and len(set(ages)) > 150
    assert O.target_age_s("abc", "r0") == O.target_age_s("abc", "r0")   # seeded


def _snap(age_s: float, mint: str = "M") -> SimpleNamespace:
    return SimpleNamespace(age_s=age_s, mint=mint)


def test_strategy_gates_on_age_alive_and_class(monkeypatch):
    p = O.make_params("t30", "tight")
    calls = {"alive": True, "class": "OPERATOR"}
    monkeypatch.setattr(O, "alive", lambda s: calls["alive"])
    monkeypatch.setattr(O, "coin_class", lambda s: calls["class"])
    monkeypatch.setattr(O, "speed_of", lambda s: "instant")
    assert O.strategy(_snap(1700), p, None) is None                       # before the target age: wait
    e = O.strategy(_snap(1800), p, None)
    assert isinstance(e, C.Enter) and e.exits.stop_pct == 0.35 and e.exits.max_hold_s == 1800.0
    assert e.exits.exit_by_age_s == O.EXIT_BY_AGE_S and e.tag == "instant"
    calls["class"] = "ORGANIC"
    assert O.strategy(_snap(1800), p, None) is C.SKIP                      # wrong class: never
    calls["class"], calls["alive"] = "OPERATOR", False
    assert O.strategy(_snap(1800), p, None) is C.SKIP                      # dead coin: never
    pos = SimpleNamespace()
    assert O.strategy(_snap(5000), p, pos) is None                         # no discretionary exits


def test_placebo_eligibility(monkeypatch):
    monkeypatch.setattr(O, "alive", lambda s: True)
    monkeypatch.setattr(O, "coin_class", lambda s: "FACTORY")
    assert O.placebo_ok(_snap(1800)) is True                               # judged control: any alive coin
    assert O.placebo_class_ok(_snap(1800)) is False                        # diagnostic: OPERATOR only
    monkeypatch.setattr(O, "coin_class", lambda s: "OPERATOR")
    assert O.placebo_class_ok(_snap(1800)) is True
    assert set(O.PLACEBO_CONTROLS) == {"class_matched"}


def test_direction_reading():
    assert O.direction({"n": 10, "placebo": {"diff_ci95": (0.1, 0.2)}}) == "UNDERPOWERED"
    assert O.direction({"n": 40, "placebo": {"diff_ci95": (0.1, 0.2)}}) == "BEATS_RANDOM"
    assert O.direction({"n": 40, "placebo": {"diff_ci95": (-0.2, -0.1)}}) == "WORSE_THAN_RANDOM"
    assert O.direction({"n": 40, "placebo": {"diff_ci95": (-0.1, 0.1)}}) == "NEITHER"
    assert O.direction({"n": 40, "placebo": None}) == "NEITHER"


def _ev(n, mean, ci_lo, mw2, pdiff, p=None):
    return {"n": n, "mean": mean, "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.2), "mean_without_top2": mw2,
            "placebo": None if pdiff is None else {"mean_diff": pdiff, "diff_ci95": None},
            "params_hash": C.params_hash(p) if p else "h", "config": O.config_key(p) if p else "c", "direction": None}


def test_decide_train_top_two_rule():
    evals = {O.config_key(p): _ev(50, -0.01, -0.05, -0.02, -0.01, p) for p in O.GRID}
    assert O.decide_train(evals)["verdict"] == "NO_CONFIG"
    low = {O.config_key(p): _ev(29, 0.2, 0.1, 0.1, 0.1, p) for p in O.GRID}
    d = O.decide_train(low)
    assert d["verdict"] == "UNDERPOWERED_TRAIN" and d["shortlist"] == []
    good = dict(evals)
    a, b, c = O.make_params("r0", "tight"), O.make_params("t30", "r0exit"), O.make_params("t60", "r0exit")
    good[O.config_key(a)] = _ev(40, 0.05, 0.02, 0.03, 0.04, a)
    good[O.config_key(b)] = _ev(90, 0.04, 0.02, 0.03, 0.04, b)        # same CI low, lower mean -> 2nd
    good[O.config_key(c)] = _ev(90, 0.09, 0.01, 0.03, -0.01, c)       # fails the judged control
    d = O.decide_train(good)
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_keys"] == [O.config_key(a), O.config_key(b)]
    assert d["shortlist_hashes"] == [C.params_hash(a), C.params_hash(b)]
    assert d["primary_direction"]["config"] == "r0|r0exit"
    tie = dict(evals)
    tie[O.config_key(a)] = _ev(40, 0.05, 0.02, 0.03, 0.04, a)
    tie[O.config_key(b)] = _ev(40, 0.05, 0.02, 0.03, 0.04, b)
    assert O.decide_train(tie)["shortlist_keys"] == [O.config_key(b), O.config_key(a)]   # t30 before r0


def test_decide_val_picks_the_higher_mean_and_judges_it():
    p1, p2 = O.make_params("t30", "tight"), O.make_params("t60", "r0exit")
    d = O.decide_val({"sl1": _ev(20, 0.01, 0, 0.005, 0, p1), "sl2": _ev(20, 0.04, 0, 0.02, 0, p2)}, ["sl1", "sl2"])
    assert d["candidate_role"] == "sl2" and d["twin_role"] == "sl1" and d["verdict"] == "SELECTED"
    d = O.decide_val({"sl1": _ev(4, 0.3, 0, 0.3, 0, p1)}, ["sl1"])
    assert d["verdict"] == "UNDERPOWERED_VAL" and not d["proceed"]
    d = O.decide_val({"sl1": _ev(40, -0.01, 0, -0.02, 0, p1)}, ["sl1"])
    assert d["verdict"] == "FAIL_VAL"
    d = O.decide_val({"sl1": _ev(10, 0.02, 0, 0.01, 0, p1)}, ["sl1"])
    assert d["verdict"] == "SELECTED_UNDERPOWERED" and d["proceed"]


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    return (O.coin_class(s), O.alive(s), O.speed_of(s), O.placebo_ok(s), O.placebo_class_ok(s))


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """O1's gate (class, alive, speed) is unchanged when the coin's data after tau is garbage: real bars, census
    TRAIN third (the debug split)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(23)
    pick = [full.mints[int(i)] for i in rng.choice(len(full.mints), size=16, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (1800.0 + float(rng.uniform(0, 59)), 3600.0 + float(rng.uniform(0, 59)),
                   float(rng.uniform(4000, 6900))):
            t = cd.g + dt + C.DECISION_LAG_S
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


def test_stage_refusals(tmp_path, monkeypatch):
    out = tmp_path / "O1"
    out.mkdir()
    with pytest.raises(O.O1Refused, match="PREREG.md missing"):
        O.check_prereqs("debug", out)
    shutil.copy(HERE / "O1" / "PREREG.md", out / "PREREG.md")
    assert O.check_prereqs("debug", out)["stage"] == "debug"
    monkeypatch.setattr(C, "validation_gates", lambda split, flow=None: (True, []))
    with pytest.raises(O.O1Refused, match="no TRAIN result"):
        O.check_prereqs("val", out)
    (out / "prereg.lock").write_text(json.dumps({"sha256": "0" * 64}))
    with pytest.raises(O.O1Refused, match="PREREG.md changed"):
        O.check_prereqs("train", out)
    (out / "prereg.lock").unlink()
    (out / "train.json").write_text(json.dumps({"provisional": False, "decision": {"verdict": "NO_CONFIG"}}))
    with pytest.raises(O.O1Refused, match="TRAIN decision NO_CONFIG"):
        O.check_prereqs("val", out)
    with pytest.raises(O.O1Refused, match="already ran on complete data"):
        O.check_prereqs("train", out)
    monkeypatch.setattr(C, "validation_gates", lambda split, flow=None: (False, ["V2 failed"]))
    with pytest.raises(O.O1Refused, match="data first"):
        O.check_prereqs("train", out)


def test_debug_stage_hides_returns(tmp_path, monkeypatch):
    g, c, b = make_frames()
    ds = C.Dataset.from_frames("final_train", g, c, b, census=C.Census.empty(), sol=SOL)
    out = tmp_path / "O1"
    out.mkdir()
    shutil.copy(HERE / "O1" / "PREREG.md", out / "PREREG.md")
    doc = O.run_stage("debug", out_dir=out, ds=ds, ledger_path=tmp_path / "dbg.json", B=50, n_placebo=2)
    assert doc["debug_only"] and doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert "mean" not in e and e["returns"].startswith("hidden")
    assert (out / "debug.md").exists() and "hidden" in (out / "debug.md").read_text()
    led = json.loads((tmp_path / "dbg.json").read_text())
    assert all(r["debug"] and r["mean"] is None for r in led["runs"])

"""Tests for research/lab2/q7.py (PS1, the 'pump' suffix veto): the pre-registered grid and host pins, the flags
(SFX0, CU, NULL handling, legality), G1's class at g + 140 s, the evaluation sets, the class-stratified random veto,
the dose report, the decision rules, no lookahead (synthetic and real census bars), and the stage pipeline with every
refusal."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import V0, make_frames, real_flow_available
from conftest import VALID_ALL as VALID
from test_common import _garble

import common as C
import g1 as G1
import q7 as Q
import y5 as Y5

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
K0 = X0 * Y0
N_MIN = 186
ENV_ALL = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}


# =========================================================================== synthetic market


def coin_bars(g: int, mint_: str, pool: str, kind: str) -> pd.DataFrame:
    """Hand-built bars: 2 SOL of volume a minute (alive), the pricing reserve X moves +0.2 ('good'), -0.2 ('bad') or 0
    SOL a minute, y = k / X (token conservation exact), no wicks."""
    step = {"good": 0.2, "bad": -0.2, "flat": 0.0}[kind]
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    rows = []
    for j in range(N_MIN):
        b, s = 1.0 + max(step, 0.0), 1.0 + max(-step, 0.0)
        X1 = X + b - s
        y1 = K0 / X1
        bt, st = (y - y1, 0.0) if y1 < y else (0.0, y1 - y)
        p0, p1 = X / y, X1 / y1
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 4, "n_sells": 3, "n_dust": 0, "buy_sol": b, "sell_sol": s,
                     "buy_tok": bt, "sell_tok": st, "n_buyers": 4, "n_sellers": 3, "top5_buy_sol": b, "open": p0,
                     "high": max(p0, p1), "low": min(p0, p1), "close": p1, "x_close": X1 - V0, "y_close": y1,
                     "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j, "agent_buy_sol": 0.0, "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def market_frames(specs, seed: int = 1, t0: int = T0, spacing: int = 1200):
    """make_frames coins (all with a scanned CreateEvent), coin i shaped by specs[i]: kind (good / bad / flat),
    nosfx (mint without the 'pump' suffix), cu (True / False / None = empty signer), factory (w120 top-5 share 0.97)."""
    g, c, b = make_frames(n=len(specs), seed=seed, t0=t0, spacing=spacing, slow_every=0)
    ren, bars = {}, []
    for i, sp in enumerate(specs):
        old = f"MINT{i:03d}{seed}pump"
        ren[old] = old[:-4] + "Qx7z" if sp.get("nosfx") else old
        gi = g.index[g["mint"] == old][0]
        cu = sp.get("cu", False)
        g.loc[gi, "create_user"] = "" if cu is None else (f"SIGNER{i}" if cu else g.loc[gi, "creator"])
        if sp.get("factory"):
            ci = c.index[c["mint"] == old][0]
            c.loc[ci, "w120_top10"] = json.dumps([[f"WBIG{i}", 28.0, 0.0], [f"WX{i}", 1.0, 0.0]])
        bars.append(coin_bars(int(g.loc[gi, "g_ts"]), old, g.loc[gi, "pool"], sp.get("kind", "flat")))
    b = pd.concat(bars, ignore_index=True)
    for df in (g, c, b):
        df["mint"] = df["mint"].map(lambda m: ren.get(m, m))
    return g, c, b


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def market(split: str, t0: int, n: int, seed: int, *, signal: bool = True) -> C.Dataset:
    """``signal``: suffix-less coins fall, app coins rise. Else the suffix is unrelated to the path. Every 4th coin is
    FACTORY (both groups); CU alternates, unrelated to the path."""
    specs = []
    for i in range(n):
        bad = i % 2 == 0
        nosfx = bad if signal else ((i // 2) % 2 == 0)
        specs.append({"kind": "bad" if bad else "good", "nosfx": nosfx, "cu": (i // 3) % 2 == 0,
                      "factory": i % 4 == 1 or i % 4 == 2})
    return ds_of(market_frames(specs, seed=seed, t0=t0), split)


def trades_of(rows) -> pd.DataFrame:
    """Hand-built annotated host trades: (mint, ret_net, sfx0, cu, g1_class, instant[, split])."""
    out = []
    for i, r in enumerate(rows):
        mint, ret, s, cu, cls, inst = r[:6]
        out.append({"mint": mint, "ret_net": ret, "sfx0": s, "cu": cu, "g1_class": cls, "instant": inst,
                    "split": r[6] if len(r) > 6 else "train", "t_in": 1.0e9 + 60 * i, "t_out": 1.0e9 + 60 * i + 3600,
                    "g_ts": 1.0e9, "reason": "time"})
    return pd.DataFrame(out)


# =========================================================================== grid and hosts


def test_grid_is_the_preregistered_grid():
    keys = [Q.config_key(p) for p in Q.GRID]
    assert keys == ["R0|SFX0|ALL", "R0|SFX0|ORGANIC", "R30|SFX0|ALL", "R0|CU|ALL"]
    assert len({C.params_hash(p) for p in Q.GRID}) == len(Q.GRID) == 4
    for p in Q.GRID:
        assert p["version"] == Q.VERSION and p["host_params"] == Q.HOST_PARAMS[p["host"]]
        assert p["host_pin"] == Q.HOST_PINS[p["host"]] and p["placebo"]["draws"] == Q.PLACEBO_B
    for bad in (("R30", "CU", "ALL"), ("R0", "SFX0", "FACTORY"), ("M1", "SFX0", "ALL")):
        with pytest.raises(ValueError):
            Q.make_params(*bad)
    assert Q.params_of("R30|SFX0|ALL") == Q.GRID[2] and Q.grid_index("R0|CU|ALL") == 3


def test_hosts_are_g1_r0_and_y5_r30_and_pins_hold(monkeypatch):
    assert Q.HOST_FN["R0"] is G1.host_r0 and Q.HOST_FN["R30"] is Y5.host_r30
    assert Q.HOST_PARAMS["R0"] == G1.R0_PARAMS and Q.HOST_PARAMS["R30"] == Y5.R30_PARAMS
    assert Q.host_pin_problems() == []
    monkeypatch.setitem(Q.HOST_PARAMS, "R0", {**G1.R0_PARAMS, "stop_pct": 0.4})
    assert any("R0" in x for x in Q.host_pin_problems())


def test_fill_is_the_queue_fill():
    assert Q.FILL.exit_delay_bars == 1 and Q.FILL.entry_fill == "worst" and Q.FILL.exit_fill == "worst"
    assert set(Q.STRESS) == {"costs_x1.5"}


# =========================================================================== flags


def test_sfx0_reads_the_mint_suffix_at_any_time():
    ds = ds_of(market_frames([{"nosfx": True}, {"nosfx": False}, {}]))
    m_no, m_yes = ds.mints[0], ds.mints[1]
    assert not m_no.endswith("pump") and m_yes.endswith("pump")
    for t_off in (-3600, 0, 140, 5000):
        assert Q.sfx0(ds.asof(m_no, ds.coin(m_no).g + t_off)) is True
        assert Q.sfx0(ds.asof(m_yes, ds.coin(m_yes).g + t_off)) is False


def test_sfx0_is_case_sensitive():
    class S:
        def __init__(self, m):
            self.m = m

        def __getitem__(self, k):
            assert k == "mint"
            return self.m
    assert Q.sfx0(S("abcPUMP")) is True and Q.sfx0(S("abcpump")) is False and Q.sfx0(S("pumpX")) is True


def test_cu_flag_values_null_and_legality():
    ds = ds_of(market_frames([{"cu": True}, {"cu": False}, {"cu": None}]))
    m_t, m_f, m_n = ds.mints
    for m, want in ((m_t, True), (m_f, False), (m_n, None)):
        cd = ds.coin(m)
        assert Q.cu_flag(ds.asof(m, cd.g + 140)) is want
    cd = ds.coin(m_t)
    created = cd.row["created_ts"]
    assert created < cd.g
    early = ds.asof(m_t, created + C.DECISION_LAG_S - 1)       # tau before the CreateEvent: not yet knowable
    assert Q.cu_flag(early) is None
    assert Q.cu_flag(ds.asof(m_t, created + C.DECISION_LAG_S)) is True


def test_cu_unknown_for_unscanned_creation():
    g, c, b = make_frames(n=5, seed=3, slow_every=5)          # coin 4 is slow: has_create = 0, creator ''
    ds = ds_of((g, c, b))
    slow = [m for m in ds.mints if not ds.coin(m).row.get("has_create")]
    assert slow
    for m in slow:
        assert Q.cu_flag(ds.asof(m, ds.coin(m).g + 3600)) is None


def test_class_facts_are_g1s_classes_at_g140():
    ds = ds_of(market_frames([{"factory": True}, {}, {"factory": True, "nosfx": True}, {"cu": True}]))
    fac = Q.facts_table(ds)
    for m in ds.mints:
        s = ds.asof(m, ds.coin(m).g + Q.CLASS_T_S)
        f = G1.g1_features(s, None)
        row = fac[fac["mint"] == m].iloc[0]
        assert row["g1_class"] == G1.classify(f)["g1_class"] and row["instant"] == f["instant"]
    assert list(fac["g1_class"]) == ["FACTORY", "ORGANIC", "FACTORY", "ORGANIC"]
    assert list(fac["sfx0"]) == [False, False, True, False] and list(fac["cu"]) == [False, False, False, True]


def test_annotate_reads_flags_at_the_decision():
    ds = market("train", T0, 12, 1)
    fac = Q.facts_table(ds)
    t = C.run_trades(ds, G1.host_r0, G1.R0_PARAMS, Q.FILL)
    assert len(t) == 12
    a = Q.annotate(t, ds, fac)
    for r in a.itertuples(index=False):
        assert r.sfx0 == (not r.mint.endswith("pump"))
        assert r.g1_class == fac.set_index("mint").at[r.mint, "g1_class"]
        assert r.age_dec_s >= 30 * 60
    assert list(a.columns[-4:]) == list(Q.ANN_COLS)


# =========================================================================== evaluation sets and statistics


def test_eval_set_subset_unknown_and_csv_roundtrip(tmp_path):
    t = trades_of([("a", -0.2, True, True, "ORGANIC", True), ("b", 0.1, False, None, "ORGANIC", False),
                   ("c", -0.1, True, False, "FACTORY", True), ("d", 0.3, False, True, "FACTORY", None)])
    sub, f, unk = Q.eval_set(t, Q.make_params("R0", "SFX0", "ALL"))
    assert len(sub) == 4 and f.tolist() == [True, False, True, False] and unk == 0
    sub, f, unk = Q.eval_set(t, Q.make_params("R0", "SFX0", "ORGANIC"))
    assert sub["mint"].tolist() == ["a", "b"] and f.tolist() == [True, False]
    sub, f, unk = Q.eval_set(t, Q.make_params("R0", "CU", "ALL"))
    assert sub["mint"].tolist() == ["a", "c", "d"] and f.tolist() == [True, False, True] and unk == 1
    p = tmp_path / "t.csv"
    t.to_csv(p, index=False)
    back = pd.read_csv(p)
    for prm in Q.GRID:
        s1, f1, u1 = Q.eval_set(t, prm)
        s2, f2, u2 = Q.eval_set(back, prm)
        assert f1.tolist() == f2.tolist() and u1 == u2 and s1["mint"].tolist() == s2["mint"].tolist()


def test_tri():
    assert [Q._tri(v) for v in (True, np.True_, "True", "false", 0, 1, None, float("nan"), "x", pd.NA)] == \
        [True, True, True, False, False, True, None, None, None, None]


def test_stratified_placebo_finds_a_real_flag_inside_classes():
    rng = np.random.default_rng(0)
    n = 200
    cls = np.array(["FACTORY", "ORGANIC"] * (n // 2), object)
    r = rng.normal(0, 0.05, n) + np.where(cls == "FACTORY", -0.2, 0.0)
    f = np.zeros(n, bool)
    for c in ("FACTORY", "ORGANIC"):            # flag the worst 30 % inside each class
        idx = np.flatnonzero(cls == c)
        f[idx[np.argsort(r[idx])[: int(0.3 * len(idx))]]] = True
    pl = Q.stratified_placebo(r, f, cls, B=400)
    assert pl["p"] == pytest.approx(1 / 401) and pl["diff"] < pl["draws_q05"]
    assert pl["strata"] == {"FACTORY": {"n": 100, "n_flagged": 30}, "ORGANIC": {"n": 100, "n_flagged": 30}}


def test_stratified_placebo_sees_through_a_class_proxy():
    """A flag that is just 'FACTORY' (a worse class): raw difference strongly negative, but every same-rate random
    veto inside the classes reproduces it exactly, so p = 1 (PREREG 6, prediction P3)."""
    rng = np.random.default_rng(1)
    n = 120
    cls = np.array(["FACTORY"] * 40 + ["ORGANIC"] * 80, object)
    r = rng.normal(0, 0.05, n) + np.where(cls == "FACTORY", -0.3, 0.0)
    f = cls == "FACTORY"
    pl = Q.stratified_placebo(r, f, cls, B=300)
    assert pl["diff"] < -0.2 and pl["p"] == 1.0
    plain = Q.stratified_placebo(r, f, ["ALL"] * n, B=300)       # unstratified: the class effect looks real
    assert plain["p"] == pytest.approx(1 / 301)


def test_stratified_placebo_random_flag_and_edge_cases():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.1, 300)
    f = rng.random(300) < 0.3
    pl = Q.stratified_placebo(r, f, ["ORGANIC"] * 300, B=500, seed=3)
    assert 0.05 < pl["p"] < 0.95
    assert Q.stratified_placebo(r, np.zeros(300, bool), ["X"] * 300, B=10)["p"] is None
    assert Q.stratified_placebo(r, np.ones(300, bool), ["X"] * 300, B=10)["p"] is None
    hid = Q.stratified_placebo(r, f, ["ORGANIC"] * 300, B=10, hide=True)
    assert "p" not in hid and "diff" not in hid and hid["strata"]["ORGANIC"]["n_flagged"] == int(f.sum())
    a = Q.stratified_placebo(r, f, [None] * 300, B=50, seed=4)
    b = Q.stratified_placebo(r, f, [None] * 300, B=50, seed=4)
    assert a == b and set(a["strata"]) == {"NONE"}


def test_dose_report_cells_dose_and_interaction():
    rows = []
    vals = {(True, True): -0.40, (False, True): -0.10, (True, False): -0.15, (False, False): -0.05}
    k = 0
    for (s, i), v in vals.items():
        for j in range(12):
            rows.append((f"m{k}", v + 0.001 * j, s, False, "ORGANIC", i))
            k += 1
    rows.append(("mu", 0.5, True, False, "ORGANIC", None))
    t = trades_of(rows)
    f = t["sfx0"].to_numpy(bool)
    d = Q.dose_report(t, f, B=300)
    assert d["cells"]["sfx0|instant"]["n"] == 12 and d["cells"]["sfx0|unknown"]["n"] == 1
    assert d["dose_n"] == {"0": 12, "1": 24, "2": 12}
    assert d["gap_instant"] == pytest.approx(-0.30) and d["gap_slow"] == pytest.approx(-0.10)
    assert d["interaction"] == pytest.approx(-0.20) and d["monotone_non_increasing"] is True
    lo, hi = d["interaction_ci95"]
    assert lo <= -0.2 <= hi < 0
    hid = Q.dose_report(t, f, hide=True)
    assert set(hid) == {"cells"} and all(set(v) == {"n"} for v in hid["cells"].values())


def test_evaluate_counts_only_when_hidden_and_full_otherwise():
    rows = [(f"m{i}", (-0.3 if i % 2 else 0.2) + 0.001 * i, bool(i % 2), None if i % 7 == 0 else bool(i % 3 == 0),
             "ORGANIC" if i % 5 else "FACTORY", bool(i % 4)) for i in range(90)]
    t = trades_of(rows)
    p = Q.make_params("R0", "SFX0", "ALL")
    hid = Q.evaluate(p, t, B=200, hide=True, placebo_b=50, span_days=2.0)
    assert hid["returns"].startswith("hidden") and hid["n_flagged"] == 45 and hid["flagged_per_day"] == 22.5
    for k in ("flagged_mean", "diff", "veto_in_sample", "gated", "pnl_usd", "winning_profit_removed"):
        assert k not in hid
    assert "p" not in hid["placebo"] and all(set(v) == {"n_flagged", "n_unflagged"} for v in hid["by_class"].values())
    full = Q.evaluate(p, t, B=200, hide=False, placebo_b=100, stress_t=t)
    assert full["diff"] < -0.4 and full["diff_ci95"][1] < 0 and full["winning_profit_removed"] == 0.0
    assert full["veto_in_sample"]["verdict"] == "INCOMPLETE"          # criterion 2 needs out-of-sample trades
    assert Q._crit(full["veto_in_sample"], 1)["pass"] and Q._crit(full["veto_in_sample"], 3)["pass"]
    assert full["placebo"]["p"] <= 0.05 and full["stress_costs_x1.5"]["diff"] == pytest.approx(full["diff"])
    assert full["gated"]["n"] == 45 and full["host_censored_share"] == 0.0
    cu = Q.evaluate(Q.make_params("R0", "CU", "ALL"), t, B=200, hide=False, placebo_b=50)
    assert cu["n_unknown_flag"] == sum(1 for i in range(90) if i % 7 == 0) and "dose" not in cu


# =========================================================================== decision rules


def _ev(nf=40, nu=60, diff=-0.2, hi=-0.05, c1=True, c3=True, p=0.01, cens=0.0, fm=-0.2, um=0.0):
    crit = [] if nf < 30 or nu < 30 else [{"id": 1, "pass": c1, "value": diff, "ci95": (diff - 0.1, hi)},
                                           {"id": 3, "pass": c3, "value": 0.1}]
    return {"n_flagged": nf, "n_unflagged": nu, "diff": diff, "flagged_mean": fm, "unflagged_mean": um,
            "veto_in_sample": {"verdict": "INCOMPLETE" if crit else "UNDERPOWERED", "criteria": crit},
            "placebo": {"p": p}, "host_censored_share": cens}


def test_decide_train_qualifies_ranks_and_shortlists():
    ev = {"R0|SFX0|ALL": _ev(hi=-0.03), "R0|SFX0|ORGANIC": _ev(hi=-0.08), "R30|SFX0|ALL": _ev(hi=-0.08),
          "R0|CU|ALL": _ev(hi=-0.20, p=0.2)}
    d = Q.decide_train(ev)
    assert d["verdict"] == "SHORTLISTED" and d["shortlist"] == ["R0|SFX0|ORGANIC", "R30|SFX0|ALL"]
    assert set(d["shortlist_hashes"]) == {"PS1", "PS1.R0", "PS1.R30"}
    assert d["shortlist_hashes"]["PS1"] == [C.params_hash(Q.GRID[1]), C.params_hash(Q.GRID[2])]
    assert d["shortlist_hashes"]["PS1.R30"] == [C.params_hash(Y5.R30_PARAMS)]
    cu = next(r for r in d["rows"] if r["config"] == "R0|CU|ALL")
    assert not cu["qualifies"] and cu["checks"]["placebo"] is False
    for bad in ({"c1": False}, {"c3": False}, {"cens": 0.2}, {"nf": 29}):
        ev2 = {k: _ev(**bad) for k in ev}
        d2 = Q.decide_train(ev2)
        assert d2["verdict"] == ("UNDERPOWERED_TRAIN" if "nf" in bad else "NO_CONFIG") and d2["shortlist"] == []
    one = {k: _ev(c1=(k == "R0|CU|ALL")) for k in ev}
    d3 = Q.decide_train(one)
    assert d3["shortlist"] == ["R0|CU|ALL"] and set(d3["shortlist_hashes"]) == {"PS1", "PS1.R0"}


def test_decide_val_outcomes_and_candidate():
    assert Q.decide_val(_ev(nf=4))["verdict"] == "UNDERPOWERED_VAL"
    assert Q.decide_val(_ev(nf=40, fm=0.1, um=0.0))["verdict"] == "FAIL_VAL"
    assert Q.decide_val(_ev(nf=40, c1=False))["verdict"] == "FAIL_VAL"
    assert Q.decide_val(_ev(nf=12, nu=50))["verdict"] == "SELECTED_UNDERPOWERED"
    assert Q.decide_val(_ev(nf=40))["verdict"] == "SELECTED"
    dec = {"R0|SFX0|ALL": {**Q.decide_val(_ev(nf=12, diff=-0.5)), "diff": -0.5},
           "R30|SFX0|ALL": {**Q.decide_val(_ev(nf=40, diff=-0.1)), "diff": -0.1}}
    assert Q.pick_candidate(dec) == "R30|SFX0|ALL"                   # SELECTED beats SELECTED_UNDERPOWERED
    dec["R0|SFX0|ALL"] = {**Q.decide_val(_ev(nf=40, diff=-0.1)), "diff": -0.1}
    assert Q.pick_candidate(dec) == "R0|SFX0|ALL"                    # tie on the difference: grid order
    assert Q.pick_candidate({"R0|CU|ALL": Q.decide_val(_ev(nf=3))}) is None


def test_combine_and_extras():
    ok = [{"pass": True}]
    assert Q.combine("PASS", ok) == "PASS"
    assert Q.combine("PASS", [{"pass": None}]) == "INCOMPLETE" and Q.combine("INCOMPLETE", ok) == "INCOMPLETE"
    assert Q.combine("UNDERPOWERED", ok) == "UNDERPOWERED" and Q.combine("UNDERPOWERED", [{"pass": False}]) == "FAIL"
    assert Q.combine("FAIL", ok) == "FAIL"
    assert Q.test_extras(_ev(nf=4))[0]["pass"] is None
    assert Q.test_extras(_ev(fm=-0.1, um=0.0))[0]["pass"] is True
    assert Q.test_extras(_ev(fm=0.1, um=0.0))[0]["pass"] is False
    ce = Q.confirm_extras({"placebo": {"p": 0.2}, "host_censored_share": 0.0})
    assert [e["pass"] for e in ce] == [False, True]
    assert [e["pass"] for e in Q.confirm_extras({"placebo": {"p": None}, "host_censored_share": None})] == [None, None]


def test_final_decision_judges_the_unseen_thirds_only():
    rows = [("a", 0.5, True, False, "ORGANIC", True, "final_train"), ("b", -0.5, False, False, "ORGANIC", True, "final_train"),
            ("c", -0.3, True, False, "ORGANIC", True, "final_val"), ("d", 0.1, False, False, "ORGANIC", True, "final_val"),
            ("e", -0.2, True, False, "ORGANIC", True, "final_test"), ("f", 0.0, False, False, "ORGANIC", True, "final_test")]
    d = Q.final_decision(trades_of(rows), Q.make_params("R0", "SFX0", "ALL"))
    assert d["flagged_worse"] is True and d["n_flagged"] == 2 and d["flagged_mean"] == pytest.approx(-0.25)
    assert d["per_third"]["final_train"]["flagged_worse"] is False


# =========================================================================== structure and the CU check


def test_structure_counts_and_cu_meaning():
    specs = [{"nosfx": i % 4 == 0, "cu": True if i < 3 else (None if i == 9 else False), "factory": i % 5 == 0}
             for i in range(10)]
    fac = Q.facts_table(ds_of(market_frames(specs)))
    s = Q.structure_counts(fac)
    assert s["n_coins"] == 10 and s["sfx0"] == 3 and s["cu_known"] == 9 and s["cu_true"] == 3
    assert s["classes"] == {"ORGANIC": 8, "FACTORY": 2} and s["instant"] == {"True": 10}
    assert s["cu_by_sfx0"]["sfx0"] == {"cu_true": 1, "cu_false": 2, "cu_unknown": 0}
    cm = Q.cu_meaning(fac)
    assert cm["n_cu"] == 3 and cm["withdraw_config4"] is False and len(cm["coins"]) == 3
    assert cm["summary"]["signers_on_1_coin"] == 3 and cm["summary"]["signer_is_another_coins_creator"] == 0
    assert all(c["signer_coins"] == 1 and c["creator_coins"] == 1 for c in cm["coins"])
    none = Q.cu_meaning(fac.assign(cu=False))
    assert none["withdraw_config4"] is True                         # degenerate: < 2 % -> config 4 withdrawn


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    cd = ds.coin(m)
    out = [Q.sfx0(s), Q.cu_flag(s)]
    if t >= cd.g + Q.CLASS_T_S:
        cf = Q.class_facts(ds.asof(m, cd.g + Q.CLASS_T_S))
        out += [cf["g1_class"], cf["instant"]]
    for h in Q.HOSTS:
        out.append(repr(Q.HOST_FN[h](s, Q.HOST_PARAMS[h], None)))
    return tuple(out)


@pytest.mark.parametrize("seed", range(3))
def test_flags_and_decisions_unchanged_by_own_future_garbage(seed):
    frames = market_frames([{"kind": k, "nosfx": i % 3 == 0, "cu": i % 2 == 0, "factory": i % 4 == 0}
                            for i, k in enumerate(["good", "bad", "flat"] * 4)], seed=1)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([60, 200, 600, 1800, 2400, 4500, 7000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_cu_before_creation_ignores_garbage_signer():
    g, c, b = market_frames([{"cu": False}, {"cu": False}])
    clean = ds_of((g, c, b))
    m = clean.mints[0]
    created = clean.coin(m).row["created_ts"]
    g2 = g.copy()
    g2.loc[g2["mint"] == m, "create_user"] = "GARBAGE_SIGNER"
    dirty = ds_of((g2, c, b))
    t = created + C.DECISION_LAG_S - 1
    assert Q.cu_flag(clean.asof(m, t)) is None and Q.cu_flag(dirty.asof(m, t)) is None


def test_host_decisions_before_T_unchanged_by_future_garbage():
    frames = market_frames([{"kind": k} for k in ["good", "bad"] * 4])
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n = 0
    for m in clean.mints:
        T = clean.coin(m).g + 80 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        for h in Q.HOSTS:
            a = C.run_trades(clean, Q.HOST_FN[h], Q.HOST_PARAMS[h], Q.FILL, mints=[m])
            b = C.run_trades(dirty, Q.HOST_FN[h], Q.HOST_PARAMS[h], Q.FILL, mints=[m])
            ad = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
            assert ad == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n += len(ad)
    assert n > 0


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Flags, G1 class and host decisions unchanged when the coin's data after tau is garbage: real census bars."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(17)
    pick = [full.mints[int(i)] for i in rng.choice(len(full.mints), size=14, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(150, 600)), float(rng.uniform(1800, 4500)), float(rng.uniform(4500, 7300))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 10 and n >= 25


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Q7", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot and VAL looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# PS1 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Q.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       placebo_b=200, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Q.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def _ps1_configs(ledger):
    led = json.loads(ledger.read_text())
    return sorted(v["hypothesis"] for v in led["configs"].values() if C.hypothesis_family(v["hypothesis"]) == "PS1")


def test_train_no_config_when_the_suffix_is_noise(st):
    doc = _run("train", st, market("train", T0, 72, 1, signal=False))
    d = doc["decision"]
    assert d["verdict"] == "NO_CONFIG" and not d["shortlist_written"] and doc["overall"].startswith("NO VETO")
    assert set(doc["configs"]) == {Q.config_key(p) for p in Q.GRID} and set(doc["hosts"]) == {"R0", "R30"}
    e = doc["configs"]["R0|SFX0|ALL"]
    assert e["n_eval"] == 72 and e["n_flagged"] == 36 and e["placebo"]["p"] > 0.05
    assert doc["hosts"]["R0"]["n"] == 72 and doc["hosts"]["R0"]["horizon_exits"] == 0
    assert not (st.sl / "PS1.json").exists() and (st.out / "prereg.lock").exists()
    assert _ps1_configs(st.ledger) == ["PS1"] * 4 + ["PS1.R0", "PS1.R30"]
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(Q.Q7Refused, match="NO_CONFIG"):
            _check(stage, st, env=ENV_ALL)
    with pytest.raises(Q.Q7Refused, match="final"):
        _run("train", st, market("train", T0, 72, 1, signal=False))
    assert "Veto configs" in (st.out / "train.md").read_text()


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 16, 2)
    with pytest.raises(Q.Q7Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "PS1.json").exists()
    with pytest.raises(Q.Q7Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    for k in ENV_ALL:            # common enforces the real env flags; q7's ``env=`` drives q7's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(Q.Q7Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: four configs, the shortlist
    tr = _run("train", st, market("train", T0, 80, 1))
    d = tr["decision"]
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_written"] and 1 <= len(d["shortlist"]) <= 2
    rows = {r["config"]: r for r in d["rows"]}
    assert not rows["R0|CU|ALL"]["qualifies"]                         # CU is unrelated to the path here
    q = sorted((r for r in rows.values() if r["qualifies"]), key=lambda r: (r["ci95_hi"], r["grid_index"]))
    assert [r["config"] for r in q[:2]] == d["shortlist"]
    e1 = tr["configs"]["R0|SFX0|ALL"]
    assert e1["diff"] < -0.3 and e1["placebo"]["p"] <= 0.05 and e1["dose"]["cells"]["sfx0|instant"]["n"] == 40
    assert set(e1["by_class"]) == set(Q.CLASSES) and e1["by_class"]["FACTORY"]["n_flagged"] == 20
    assert (st.out / "prereg.lock").exists() and (st.out / "train_trades.csv").exists()
    assert _ps1_configs(st.ledger) == ["PS1"] * 4 + ["PS1.R0", "PS1.R30"]
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Q.Q7Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# PS1 test prereg\n")
    for stage in ("test", "confirm", "final"):
        with pytest.raises(Q.Q7Refused, match="no VAL result"):
            _check(stage, st, env=ENV_ALL)
    # ---- VAL: the shortlist once, one candidate
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 01:00"), 80, 2))
    assert set(va["configs"]) == set(d["shortlist"])
    cand = va["decision"]["candidate"]
    assert cand in d["shortlist"] and va["decision"]["per_config"][cand]["verdict"] == "SELECTED"
    assert va["overall"] == f"PENDING TEST ({cand})"
    with pytest.raises(Q.Q7Refused, match="VAL already ran"):
        _check("val", st)
    with pytest.raises(Q.Q7Refused, match="before TEST"):
        _check("confirm", st, env=ENV_ALL)
    # ---- TEST: locked without the judge's flag, then once
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 60, 3)
    with pytest.raises(Q.Q7Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=ENV_ALL)
    assert set(te["configs"]) == {cand} and te["hosts_run"] == [Q.params_of(cand)["host"]]
    fv = te["decision"]["formal_veto"]
    assert {c["id"] for c in fv["criteria"]} == {1, 2, 3} and te["decision"]["verdict"] == "PASS", te["decision"]
    assert te["decision"]["extras"][0]["id"] == "PS1.1"
    with pytest.raises(Q.Q7Refused, match="already ran"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Q.Q7Refused, match="one test run"):
        _check("test", st, env=ENV_ALL)                                     # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 80, 4), env=ENV_ALL)
    assert co["decision"]["verdict"] == "PASS", co["decision"]
    assert [e["id"] for e in co["decision"]["extras"]] == ["PS1.2", "PS1.3"]
    assert co["overall"] == f"PENDING FINAL ({cand})"
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 20, 5), env=ENV_ALL)
    assert fi["decision"]["flagged_worse"] is True and fi["decision"]["candidate"] == cand
    assert fi["overall"] == f"VETO ({cand})"
    with pytest.raises(Q.Q7Refused, match="already ran"):
        _check("final", st, env=ENV_ALL)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6   # the whole life of PS1: 6 entries


def test_a_failed_test_stops_confirm_and_final(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    _run("train", st, market("train", T0, 80, 1))
    _run("val", st, market("val", C.utc_ts("2026-10-05 01:00"), 80, 2))
    specs = [{"kind": "good" if i % 2 == 0 else "bad", "nosfx": i % 2 == 0, "cu": False, "factory": i % 4 == 1}
             for i in range(60)]                               # the suffix flips sign on TEST
    te = _run("test", st, ds_of(market_frames(specs, seed=3, t0=C.utc_ts("2026-10-06 13:00")), "test"), env=ENV_ALL)
    assert te["decision"]["verdict"] == "FAIL" and te["overall"].startswith("NO VETO (TEST FAIL")
    for stage in ("confirm", "final"):
        with pytest.raises(Q.Q7Refused, match="TEST verdict is FAIL"):
            _check(stage, st, env=ENV_ALL)


def test_val_failure_stops_the_hypothesis(st):
    _run("train", st, market("train", T0, 80, 1))
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 01:00"), 80, 2, signal=False))
    assert va["decision"]["candidate"] is None and va["overall"] == "NO VETO (failed VAL)"
    with pytest.raises(Q.Q7Refused, match="no candidate"):
        _check("test", st, env=ENV_ALL)


def test_data_gates_pins_and_missing_prereg_refuse(st, monkeypatch):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Q.Q7Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    monkeypatch.setitem(Q.HOST_PARAMS, "R30", {**Y5.R30_PARAMS, "max_hold_s": 1800.0})
    with pytest.raises(Q.Q7Refused, match="host pins"):
        _check("train", st)
    monkeypatch.setitem(Q.HOST_PARAMS, "R30", dict(Y5.R30_PARAMS))
    assert _check("train", st)["stage"] == "train"
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Q.Q7Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 24, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Q.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, placebo_b=50, env={})
    assert doc["decision"]["verdict"] == "DEBUG" and doc["overall"].startswith("PENDING")
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden") and e["n_eval"] > 0
        for k in ("flagged_mean", "unflagged_mean", "diff", "veto_in_sample", "gated", "pnl_usd"):
            assert k not in e
        assert "p" not in e["placebo"] and "diff" not in e["placebo"]
    for h in doc["hosts"].values():
        assert h["returns"].startswith("hidden") and "reasons" not in h and "mean" not in h and h["n"] == 24
    assert doc["cu_meaning"]["n_cu"] > 0 and doc["structure"]["sfx0"] == 12
    txt = json.dumps(doc)
    for word in ("ret_net", "exit_price", "mean_diff", "flagged_mean", "\"mean\""):
        assert word not in txt
    assert not list(st.out.glob("*_trades.csv"))
    assert not st.ledger.exists() or json.loads(st.ledger.read_text())["n_trials_total"] == 2575

"""Regression tests for the wave-2 lab review findings (one section per finding id).

Each test failed before its fix. Synthetic data only, except where a test reads the repo's own ledger."""

import gzip
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import common as C
from conftest import V0, make_frames

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
H = 3600


def _ds(split="train", frames=None, **kw):
    g, c, b = frames if frames is not None else make_frames(n=12, seed=4)
    return C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=kw.pop("sol", SOL), guard=False, **kw)


def _enter_at(age_min, exits=C.ExitSpec(max_hold_s=600), tag=""):
    def strat(snap, p, pos):
        if pos is not None:
            return None
        if snap.age_s >= 60 * age_min:
            return C.Enter(exits=exits, tag=tag)
        return None
    return strat


# =========================================================================== INIT-PRICE-NO-VIRT


def test_initial_price_includes_the_virtual_reserve():
    g, c, b = make_frames(n=4, seed=2)
    ds = _ds(frames=(g, c, b))
    m = ds.mints[0]
    cd = ds.coin(m)
    r = g[g["mint"] == m].iloc[0]
    x0, y0 = float(r["pool_quote0"]), float(r["pool_base0"])
    v = float(c.loc[c["mint"] == m, "virt_sol"].iloc[0])
    assert cd.init_X == pytest.approx(x0 + v) and cd.init_y == pytest.approx(y0)
    assert cd.k_before(0) == pytest.approx((x0 + v) * y0)
    snap = C.AsOf(cd, cd.g + 5, SOL)                      # nothing completed yet: k = 0
    assert snap.k == 0 and snap.price == pytest.approx((x0 + v) / y0)


def test_first_bar_open_and_low_are_repaired_when_b2_dropped_the_virtual_reserve():
    """B2 bar 0: open = x0 / y0 (no v) and the low mixes no-v prices; closes are (x + v) / y."""
    g, c, b = make_frames(n=4, seed=2)
    m = g["mint"].iloc[1]
    r = g[g["mint"] == m].iloc[0]
    x0, y0 = float(r["pool_quote0"]), float(r["pool_base0"])
    i0 = b.index[(b["mint"] == m) & (b["minute_idx"] == 0)][0]
    b.loc[i0, "open"] = x0 / y0                            # what B2 emits (17 % low)
    b.loc[i0, "low"] = 1.02 * x0 / y0                      # the first trade priced without v
    ds = _ds(frames=(g, c, b))
    cd = ds.coin(m)
    p_init = (x0 + V0) / y0
    assert cd.arr["o"][0] == pytest.approx(p_init)
    assert cd.arr["l"][0] >= min(p_init, cd.arr["c"][0]) * (1 - 1e-12)
    assert cd.arr["h"][0] >= max(p_init, cd.arr["c"][0]) * (1 - 1e-12)


# =========================================================================== COV-PARTIAL-HOUR


def _second_hour(cd):
    return (cd.m0 // H + 1) * H


def test_partial_pool_hour_excludes_the_coin_and_marks_the_hour_mid_run():
    g, c, b = make_frames(n=24, spacing=1200, seed=3)
    full = _ds(frames=(g, c, b))
    m = full.mints[5]
    cd = full.coin(m)
    hour = _second_hour(cd)
    pools = set(g["pool"])
    cells = {(p, h) for p in pools for h in range(T0 // H * H - 4 * H, T0 // H * H + 40 * H, H)}
    comp_ok = C.Completeness(source="test", bar_hours=frozenset(h for _, h in cells), cells=frozenset(cells),
                             errors={}, curve_hours=None, b2_fetched={}, snapshot_utc=None)
    ds_ok = _ds(frames=(g, c, b), completeness=comp_ok)
    assert m in ds_ok.mints and not ds_ok.coverage["b2_hours_midrun"]
    comp = C.Completeness(source="test", bar_hours=comp_ok.bar_hours, cells=frozenset(cells - {(cd.pool, hour)}),
                          errors={}, curve_hours=None, b2_fetched={}, snapshot_utc=None)
    ds = _ds(frames=(g, c, b), completeness=comp)
    assert m not in ds.mints
    assert dict(zip(ds.excluded["mint"], ds.excluded["exclude_reason"]))[m] == "b2_window_incomplete"
    assert C.utc_str(hour) in ds.coverage["b2_hours_midrun"]
    assert ds.coverage["complete"] is False
    assert any("mid-run" in p for p in C.coverage_problems(ds.coverage))


def test_pool_error_is_its_own_exclusion_reason():
    g, c, b = make_frames(n=12, spacing=1200, seed=3)
    pools = set(g["pool"])
    cells = {(p, h) for p in pools for h in range(T0 // H * H - 4 * H, T0 // H * H + 30 * H, H)}
    m = g["mint"].iloc[3]
    pool = g["pool"].iloc[3]
    hour = (int(g["g_ts"].iloc[3]) // 60 * 60) // H * H
    comp = C.Completeness(source="test", bar_hours=frozenset(h for _, h in cells),
                          cells=frozenset(cells - {(pool, hour)}), errors={(pool, hour): "too_large"},
                          curve_hours=None, b2_fetched={}, snapshot_utc=None)
    ds = _ds(frames=(g, c, b), completeness=comp)
    assert dict(zip(ds.excluded["mint"], ds.excluded["exclude_reason"]))[m] == "b2_pool_error"
    assert ds.coverage["excluded"].get("b2_pool_error") == 1


def _write_chunk(d: Path, t0: int, t1: int, pools, mtime: float, key: str = "k") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{t0}-{t1}-{key}.json.gz"
    with gzip.open(p, "wt") as f:
        json.dump({"kind": "b2", "t0": t0, "t1": t1, "params": {"act": [[pl, "MINT", 0] for pl in pools]},
                   "columns": [], "rows": []}, f)
    os.utime(p, (mtime, mtime))
    return p


def test_completeness_from_raw_chunks_ignores_chunks_newer_than_the_parquet(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB2_CACHE", str(tmp_path / "cache"))
    flow = tmp_path / "flow"
    raw = flow / "raw"
    h0 = T0 // H * H
    now = time.time()
    g, c, b = make_frames(n=2, seed=1, t0=h0 + 600)
    b = b[b["minute_ts"] < h0 + 3 * H]
    flow.mkdir()
    for name, df in (("graduates", g), ("b2_coins", c), ("b2_bars", b)):
        df.to_parquet(flow / f"{name}.parquet")
    for n in ("graduates", "b2_coins", "b2_bars"):
        os.utime(flow / f"{n}.parquet", (now - 100, now - 100))
    _write_chunk(raw / "b2", h0, h0 + H, ["P1", "P2"], now - 500, "a")
    _write_chunk(raw / "b2", h0 + H, h0 + H + 1800, ["P1"], now - 500, "b")          # P1: first half ...
    _write_chunk(raw / "b2", h0 + H + 1800, h0 + 2 * H, ["P1"], now - 500, "c")      # ... and second half
    _write_chunk(raw / "b2", h0 + H, h0 + H + 1800, ["P2"], now - 500, "d")          # P2: first half only
    _write_chunk(raw / "b2", h0 + H + 1800, h0 + 2 * H, ["P2"], now - 10, "e")       # fetched AFTER the snapshot
    _write_chunk(raw / "b2", h0 + 2 * H, h0 + 3 * H, ["P1"], now - 500, "f")
    (raw / "curve").mkdir(parents=True)
    for t in range(h0 - 4 * H, h0 + 3 * H, 1800):
        p = raw / "curve" / f"{t}-{t + 1800}.json.gz"
        p.write_bytes(gzip.compress(b"{}"))
        os.utime(p, (now - 500, now - 500))
    (flow / "state.json").write_text(json.dumps({"b2": {str(h0 + 2 * H): {"done": True, "done_pools": ["P1", "P2"],
                                                                         "errors": {"P2": "too_large"}}},
                                                 "curve": {}, "errors": {}}))
    comp = C.completeness_from_flow(flow)
    assert comp.source == "raw_chunks"
    assert comp.cell("P1", h0) == "ok" and comp.cell("P2", h0) == "ok"
    assert comp.cell("P1", h0 + H) == "ok"                 # two halves cover the hour
    assert comp.cell("P2", h0 + H) == "missing"            # its second half is not in the Parquet yet
    assert comp.cell("P2", h0 + 2 * H) == "error"
    assert comp.cell("P1", h0 + 5 * H) == "missing"
    assert h0 + H in comp.curve_hours and h0 + 3 * H not in comp.curve_hours


# =========================================================================== M1-HORIZON-CENSOR


def test_exit_by_age_is_a_time_exit_before_the_data_horizon(tmp_ledger):
    ds = _ds()
    strat = _enter_at(150, C.ExitSpec(max_hold_s=6 * H, exit_by_age_s=178 * 60))
    t = C.run_trades(ds, strat, {}, C.FillConfig())
    assert len(t) and (t["reason"] == "time").all()
    assert ((t["t_out"] - t["g_ts"]) <= C.N_BARS * 60).all()
    t2 = C.run_trades(ds, _enter_at(150, C.ExitSpec(max_hold_s=6 * H)), {}, C.FillConfig())
    assert (t2["reason"] == "horizon").all()
    d = C.describe(t2, B=200)
    assert d["censored_share"] == 1.0


def _pass_result(n=80, n_coins=60, mean=0.10, horizon_share=0.0, seed=0, block_means=None):
    """A TEST result that clears every PLAN 3.5 bar (unless told otherwise)."""
    rng = np.random.default_rng(seed)
    coins = [f"C{i % n_coins:03d}" for i in range(n)]
    t_in = C.utc_ts("2026-10-06 13:00") + np.arange(n) * (30 * H // n)
    r = mean + rng.normal(0, 0.02, n)
    if block_means is not None:
        blk = (t_in // C.BLOCK_S).astype(int)
        u = sorted(set(blk))
        r = np.array([block_means[u.index(b) % len(block_means)] for b in blk]) + rng.normal(0, 0.01, n)
    t = pd.DataFrame({c: [None] * n for c in C.TRADE_COLS})
    t["mint"], t["t_in"], t["t_out"], t["g_ts"] = coins, t_in, t_in + 1800, t_in - 600
    t["ret_net"], t["reason"], t["split"] = r, "time", "test"
    k = int(round(horizon_share * n))
    t.loc[: k - 1, "reason"] = "horizon" if k else "time"
    pl = t.loc[t.index.repeat(3)].reset_index().rename(columns={"index": "signal"})
    pl["ret_net"] = pl["ret_net"] - 0.2
    pl["signal_mint"] = pl["mint"]
    st = {"costs_x1.5": t.assign(ret_net=t["ret_net"] - 0.01)}
    meta = {"split": "test", "hypothesis": "H", "declarations": {}}
    val = C.Result(trades=t.assign(ret_net=t["ret_net"] * 0.5), placebo=pl.iloc[0:0], stress={}, meta={})
    return C.Result(trades=t, placebo=pl, stress=st, meta=meta), val


def test_censored_trades_block_a_pass():
    res, val = _pass_result(horizon_share=0.0)
    assert C.verdict_entry(res, val=val, final=val, B=500)["verdict"] == "PASS"
    res, val = _pass_result(horizon_share=0.25)
    v = C.verdict_entry(res, val=val, final=val, B=500)
    assert v["verdict"] == "INCOMPLETE"
    c10 = next(c for c in v["criteria"] if c["id"] == 10)
    assert c10["pass"] is False and c10["value"] == pytest.approx(0.25)


def test_m1_registers_the_simulated_rule_exit_by_g_plus_178_min():
    import m1 as M
    assert M.EXIT_BY_AGE_S == 178 * 60 and M.EXIT_BY_AGE_S < C.N_BARS * 60
    assert M.FIXED["exit_by_age_s"] == M.EXIT_BY_AGE_S
    ds = _ds()
    snap = ds.asof(ds.mints[0], ds.coin(ds.mints[0]).g + 40 * 60)
    monkey = M.entry_decision
    try:
        M.entry_decision = lambda s, p, cls=None: (True, {"floor": 0.1})
        M.m1_class_orig = M.m1_class
        M.m1_class = lambda s: "OTHER"
        e = M.strategy(snap, M.GRID[0], None)
    finally:
        M.entry_decision = monkey
        M.m1_class = M.m1_class_orig
    assert isinstance(e, C.Enter) and e.exits.exit_by_age_s == M.EXIT_BY_AGE_S


def test_m1_rug_criterion_uses_uncensored_holds_only():
    import m1 as M
    ev = lambda rug, rug_unc, cens: {"n": 70, "n_clusters": 4, "clusters": {}, "rug_rate": rug,  # noqa: E731
                                     "rug_rate_uncensored": rug_unc, "censored": cens}
    ex = M.m1_extras(ev(0.1, 0.1, 0), ev(0.1, 0.4, 30))
    assert ex[3]["pass"] is True and ex[3]["value"]["twin"] == 0.4


# =========================================================================== M1-PLACEBO-CLASS


def test_placebo_strata_match_the_signal_stratum(tmp_ledger):
    ds = _ds(frames=make_frames(n=16, seed=5, spacing=900))
    odd = lambda s: int(s.mint[4:7]) % 2  # noqa: E731
    sig = C.run_trades(ds, _enter_at(10), {}, C.FillConfig())
    pl = C.run_placebo(ds, _enter_at(10), {}, C.FillConfig(), sig, n_draws=5, seed=1, strata=odd)
    assert len(pl)
    for r in pl.itertuples():
        assert int(r.mint[4:7]) % 2 == int(r.signal_mint[4:7]) % 2
    res = C.backtest(_enter_at(10), "train", {"a": 1}, hypothesis="HSTRAT", ds=ds, n_placebo=4, placebo_strata=odd,
                     placebo_controls={"unmatched": {"eligible": None, "strata": None}})
    assert "unmatched" in res.controls and len(res.controls["unmatched"])
    for r in res.placebo.itertuples():
        assert int(r.mint[4:7]) % 2 == int(r.signal_mint[4:7]) % 2


def test_m1_placebo_is_class_matched_and_unmatched_is_reported(monkeypatch, tmp_path, tmp_ledger):
    import m1 as M
    seen = {}
    real = C.backtest

    def spy(*a, **kw):
        seen.setdefault("kw", []).append(kw)
        return real(*a, **kw)
    monkeypatch.setattr(C, "backtest", spy)
    from test_m1 import market
    out = tmp_path / "M1"
    out.mkdir()
    (out / "PREREG.md").write_text("# p\n")
    flow = tmp_path / "flow"
    flow.mkdir()
    from conftest import VALID_ALL
    (flow / "validation.json").write_text(json.dumps(VALID_ALL))
    monkeypatch.setattr(M, "model_check", lambda obs, **kw: {"decision": "PASS", "n_obs": 0, "n_coins": 0})
    doc = M.run_stage("train", out_dir=out, ds=market("train", T0, 36, 6, 1), flow=flow, ledger_path=tmp_ledger,
                      shortlist_path=tmp_path / "sl", B=200, n_placebo=2, env={}, _skip_coverage=True)
    assert all(kw.get("placebo_strata") is M.placebo_stratum for kw in seen["kw"])
    e = next(iter(doc["configs"].values()))
    assert "placebo_unmatched" in e


# =========================================================================== S1-CONTROL1-TIMING


def _cp_trades(spec, seed=0):
    rows, rng, i = [], np.random.default_rng(seed), 0
    for cp, n, mean in spec:
        for _ in range(n):
            rows.append({"mint": f"M{i:04d}", "tag": f"cp{cp}", "ret_net": mean + rng.normal(0, 0.01)})
            i += 1
    return pd.DataFrame(rows)


def test_s1_control1_difference_is_time_matched():
    import s1
    sig = _cp_trades([(15, 30, 0.10)])
    ctrl = _cp_trades([(6, 200, -0.50), (15, 40, 0.10)], seed=1)
    d = s1.matched_control_diff(sig, ctrl, B=500)
    assert d["diff"] == pytest.approx(0.0, abs=0.02)            # same t, same return: no edge from timing
    assert d["weights"] == {"cp15": 1.0}
    assert d["ci95"][0] < 0 < d["ci95"][1]
    naive = sig["ret_net"].mean() - ctrl["ret_net"].mean()
    assert naive > 0.4                                         # what the untimed control reported
    assert s1.matched_control_diff(sig, _cp_trades([(6, 50, 0.0)]), B=200)["diff"] is None   # no control at cp15


def test_s1_control1_enters_every_eligible_coin_at_every_checkpoint(monkeypatch):
    import s1
    ds = _ds(frames=make_frames(n=6, seed=2, slow_every=0))
    monkeypatch.setattr(s1, "nonflow_ok", lambda snap, f=None: True)
    ents = s1.control1_entries(ds, s1.control_params())
    per_cp = {}
    for m, t, e in ents:
        cd = ds.coin(m)
        cp = int(e.tag[2:])
        assert t <= cd.g + 60 * cp < t + 60 and (t - cd.m0 - C.GRID_OFFSET_S) % 60 == 0
        per_cp.setdefault(cp, set()).add(m)
    assert set(per_cp) == set(s1.CHECKPOINTS_MIN) and all(v == set(ds.mints) for v in per_cp.values())


def test_run_entries_forced_trades_use_the_strategy_exits(tmp_ledger):
    ds = _ds()
    m = ds.mints[0]
    cd = ds.coin(m)
    t = cd.m0 + 60 * 10 + C.GRID_OFFSET_S
    tr = C.run_entries(ds, lambda s, p, pos: None, {}, C.FillConfig(),
                       [(m, t, C.Enter(exits=C.ExitSpec(max_hold_s=300), tag="cp10"))], hypothesis="HENT")
    assert len(tr) == 1 and tr["t_dec"].iloc[0] == t and tr["tag"].iloc[0] == "cp10"
    assert not tr["is_placebo"].iloc[0] and tr["reason"].iloc[0] == "time"


# =========================================================================== NO-DAY-BLOCK-CI


def test_block_bootstrap_is_wider_when_blocks_share_shocks():
    res, val = _pass_result(n=120, n_coins=120, block_means=[0.6, 0.5, -0.4, -0.3, 0.3])
    d = C.describe(res.trades, B=2000)
    assert d["n_blocks"] >= 4 and d["ci90"][0] > 0
    assert d["ci90_block"][0] < 0 < d["ci90_block"][1]
    v = C.verdict_entry(res, val=val, final=val, B=1000)
    c3 = next(c for c in v["criteria"] if c["id"] == 3)
    assert c3["pass"] is False and set(c3["value"]) == {"coin", "block"}
    assert v["verdict"] == "FAIL"


def test_block_bootstrap_ci_needs_two_blocks():
    assert C.block_bootstrap_ci(np.ones(10), list("abcdefghij"), np.zeros(10)) is None


# =========================================================================== STOP-RULE1-STALE


def _flow_with(tmp_path, v: dict, chunk_hour: int | None = None, chunk_mtime: float | None = None) -> Path:
    flow = tmp_path / "flow"
    flow.mkdir(exist_ok=True)
    (flow / "validation.json").write_text(json.dumps(v))
    if chunk_hour is not None:
        _write_chunk(flow / "raw" / "b2", chunk_hour, chunk_hour + H, ["P"], chunk_mtime, "z")
    return flow


def test_validation_must_cover_the_split_dates(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB2_CACHE", str(tmp_path / "cache"))
    from conftest import VALID, VALID_ALL
    flow = _flow_with(tmp_path, VALID)                       # census-only record (no ranges)
    ok, bad = C.validation_gates("train", flow)
    assert not ok and any("does not cover" in b for b in bad)
    ok, _ = C.validation_gates("final_val", flow)
    assert ok
    flow = _flow_with(tmp_path, VALID_ALL)
    assert C.validation_gates("train", flow)[0] and C.validation_gates("confirm", flow)[0]
    bad_v2 = json.loads(json.dumps(VALID_ALL))
    bad_v2["ranges"][0]["V2"] = {"chain_ok": 90, "transitions": 100}
    flow = _flow_with(tmp_path, bad_v2)
    ok, bad = C.validation_gates("train", flow)
    assert not ok and any("does not cover" in b for b in bad)


def test_validation_older_than_the_data_it_covers_is_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB2_CACHE", str(tmp_path / "cache"))
    from conftest import VALID
    v = dict(VALID, generated_utc="2026-10-08 21:55:00")
    hour = C.FINAL_LO // H * H + 3 * H
    flow = _flow_with(tmp_path, v, chunk_hour=hour, chunk_mtime=C.utc_ts("2026-10-08 22:40"))
    for name in ("graduates", "b2_coins", "b2_bars"):
        (flow / f"{name}.parquet").write_bytes(b"x")
        os.utime(flow / f"{name}.parquet", (time.time(), time.time()))
    ok, bad = C.validation_gates("final_test", flow)
    assert not ok and any("predates" in b for b in bad)


def test_s1_checks_the_validation_gates(tmp_path, monkeypatch):
    import s1
    from conftest import VALID
    monkeypatch.setenv("LAB2_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("LAB2_FLOW", str(_flow_with(tmp_path, VALID)))
    monkeypatch.setattr(s1, "coverage_counts", lambda split: {
        "split": split, "usable": 10, "s1_universe": 10, "b1_covered": 10, "b1_frac": 1.0, "split_complete": True,
        "chain_hours_scanned_frac": 1.0, "days_full": 4, "days_expected": 4.0, "b1_file": True, "problems": []})
    out = s1.check_data("train")
    assert any("stop rule 1" in p for p in out["problems"])


def test_m1_g1_d1_use_split_keyed_validation(tmp_path, monkeypatch):
    import d1
    import g1
    import m1
    from conftest import VALID
    monkeypatch.setenv("LAB2_CACHE", str(tmp_path / "cache"))
    flow = _flow_with(tmp_path, VALID)
    out = tmp_path / "X"
    out.mkdir()
    (out / "PREREG.md").write_text("# p\n")
    with pytest.raises(m1.M1Refused, match="data first"):
        m1.check_prereqs("train", out, flow=flow, env={})
    m1.check_prereqs("debug", out, flow=flow, env={})          # debug: mechanics only
    with pytest.raises(g1.G1Refused, match="data first"):
        g1.check_prereqs("train", out, flow=flow, env={})
    monkeypatch.setenv("LAB2_FLOW", str(flow))
    ok, bad = d1.validation_gates("train")
    assert not ok and any("does not cover" in b for b in bad)


# =========================================================================== SOLUSD-FUTURE-PRICE


def test_sol_series_starting_after_the_coins_is_lookahead(tmp_ledger):
    g, c, b = make_frames(n=6, seed=2)
    late = C.SolUsd([[T0 + 10 * H, 1, 1, 1, 150.0, 1], [T0 + 30 * H, 1, 1, 1, 140.0, 1]])
    ds = _ds(frames=(g, c, b), sol=late)
    s = ds.coverage["sol_usd"]
    assert s["lookahead_coins"] > 0 and not s["constant_fallback"]
    assert any("SOL/USD" in p for p in C.coverage_problems(ds.coverage))
    with pytest.raises(C.DataNotReady, match="SOL/USD"):
        C.backtest(_enter_at(10), "train", {}, hypothesis="HSOL", ds=ds)
    assert C.n_trials() == 2575                                 # refused before anything was logged
    ok = _ds(frames=(g, c, b), sol=C.SolUsd([[T0 - 2 * H, 1, 1, 1, 150.0, 1], [T0 + 40 * H, 1, 1, 1, 140.0, 1]]))
    assert ok.coverage["sol_usd"]["lookahead_coins"] == 0
    assert not [p for p in C.coverage_problems(ok.coverage) if "SOL/USD" in p]


# =========================================================================== DEBUG-MEANS-LEAK


def test_debug_runs_never_store_means_or_exit_reasons(tmp_ledger):
    from types import MappingProxyType
    g, c, b = make_frames(n=8, seed=2, t0=C.FINAL_LO + 3600, slow_every=0)
    cen = C.Census(MappingProxyType({}), MappingProxyType({}), float("inf"), float("inf"), C.FINAL_LO + 86400.0,
                   C.FINAL_LO + 86400.0)
    ds = C.Dataset.from_frames("final_train", g, c, b, census=cen, sol=SOL)
    res = C.backtest(_enter_at(5, C.ExitSpec(stop_pct=0.05, max_hold_s=900)), "final_train", {}, hypothesis="DBG",
                     ds=ds)
    assert len(res.trades)
    assert all(r["mean"] is None for r in json.loads(tmp_ledger.read_text())["runs"])
    assert "reasons" not in res.summary()
    C.record_run("DBG2", {}, "final_train", {"n": 3, "mean": 0.5}, debug=True)
    assert json.loads(tmp_ledger.read_text())["runs"][-1]["mean"] is None


def test_shared_ledger_holds_no_debug_means():
    led = json.loads((Path(C.__file__).parent / "trials.json").read_text())
    assert not [r for r in led["runs"] if r.get("debug") and r.get("mean") is not None]


def test_m1_debug_report_hides_exit_reasons(tmp_path, monkeypatch, tmp_ledger):
    import m1 as M
    from test_m1 import market
    ds = market("train", T0, 36, 6, 1)
    res = C.backtest(M.strategy, "train", M.GRID[0], hypothesis="M1dbg", ds=ds, placebo=False,
                     ledger_path=None)
    ev = M.evaluate(res, ds, {}, B=100, hide=True, n_trials_total=None)
    assert "reasons" not in ev


# =========================================================================== GATING-BYPASS


def _test_ds():
    g, c, b = make_frames(n=8, t0=C.utc_ts("2026-10-06 13:00"), spacing=3000)
    return C.Dataset.from_frames("test", g, c, b, census=C.Census.empty(), sol=SOL, guard=False)


def test_env_guard_is_enforced_whatever_dataset_is_passed(tmp_ledger, monkeypatch):
    monkeypatch.delenv("LAB2_ALLOW_TEST", raising=False)
    ds = _test_ds()
    with pytest.raises(C.SplitLocked, match="LAB2_ALLOW_TEST"):
        C.backtest(_enter_at(10), "test", {}, hypothesis="HG", ds=ds)
    with pytest.raises(C.SplitLocked):
        C.run_trades(ds, _enter_at(10), {}, C.FillConfig())
    assert not json.loads(tmp_ledger.read_text() or "{}").get("runs") if tmp_ledger.exists() else True


def test_one_run_per_hypothesis_family_and_canonical_ledger(tmp_ledger, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    ds = _test_ds()
    C.backtest(_enter_at(10), "test", {}, hypothesis="HF", ds=ds, placebo=False)
    for twin in ("HF", "HF-twin", "HF.R0"):
        with pytest.raises(C.SplitLocked, match="HF"):
            C.backtest(_enter_at(10), "test", {"x": 1}, hypothesis=twin, ds=ds, placebo=False)
    with pytest.raises(C.SplitLocked, match="ledger"):
        C.backtest(_enter_at(10), "test", {}, hypothesis="HG", ds=ds, ledger_path=tmp_path / "other.json")
    with pytest.raises(C.SplitLocked):
        C.run_trades(ds, _enter_at(10), {}, C.FillConfig())              # no hypothesis: no unlogged TEST look
    C.backtest(_enter_at(10), "test", {}, hypothesis="HG", ds=ds, placebo=False)   # another family is fine


def test_one_shot_session_allows_twins_once(tmp_ledger, monkeypatch):
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    ds = _test_ds()
    with C.one_shot_session("HS", "test"):
        C.backtest(_enter_at(10), "test", {}, hypothesis="HS", ds=ds, placebo=False)
        C.backtest(_enter_at(12), "test", {}, hypothesis="HS-twin", ds=ds, placebo=False)
        t = C.run_trades(ds, _enter_at(10), {}, C.FillConfig(latency_s=5.0), hypothesis="HS")
        assert len(t)
    with pytest.raises(C.SplitLocked):
        C.backtest(_enter_at(10), "test", {}, hypothesis="HS-later", ds=ds, placebo=False)
    with pytest.raises(C.SplitLocked):
        with C.one_shot_session("HS", "test"):
            pass
    led = json.loads(tmp_ledger.read_text())
    assert len([r for r in led["runs"] if r["split"] == "test"]) == 3
    assert {r.get("session") for r in led["runs"] if r["split"] == "test"} != {None}


def test_final_consumes_its_thirds(tmp_ledger, monkeypatch):
    monkeypatch.setenv("LAB2_ALLOW_FINAL", "1")
    g, c, b = make_frames(n=6, t0=C.FINAL_LO + 3600, spacing=3000)
    dsf = C.Dataset.from_frames("final", g, c, b, census=C.Census.empty(), sol=SOL)
    C.backtest(_enter_at(10), "final", {}, hypothesis="HFIN", ds=dsf, placebo=False)
    dst = C.Dataset.from_frames("final_test", g, c, b, census=C.Census.empty(), sol=SOL)
    with pytest.raises(C.SplitLocked):
        C.backtest(_enter_at(10), "final_test", {}, hypothesis="HFIN", ds=dst, placebo=False)
    with pytest.raises(C.SplitLocked):
        with C.one_shot_session("HFIN", "final_val"):
            pass


def test_trial_identity_includes_cfg_and_mints_and_val_looks_are_counted(tmp_ledger):
    g, c, b = make_frames(n=8, t0=C.utc_ts("2026-10-05 02:00"), spacing=3000)
    ds = C.Dataset.from_frames("val", g, c, b, census=C.Census.empty(), sol=SOL, guard=False)
    C.write_shortlist("HV", [{"a": 1}])
    n0 = C.n_trials()
    C.backtest(_enter_at(10), "val", {"a": 1}, hypothesis="HV", ds=ds, placebo=False)
    C.backtest(_enter_at(10), "val", {"a": 1}, hypothesis="HV", ds=ds, placebo=False,
               cfg=C.FillConfig(entry_fill="open", exit_fill="open"))
    C.backtest(_enter_at(10), "val", {"a": 1}, hypothesis="HV", ds=ds, placebo=False, mints=ds.mints[:4])
    C.run_trades(ds, _enter_at(10), {"a": 1}, C.FillConfig(latency_s=5.0), hypothesis="HV")
    assert C.n_trials() - n0 == 4
    led = json.loads(tmp_ledger.read_text())
    assert led["val_looks"]["HV"] == 4


# =========================================================================== M1-FINAL-CONTAMINATION


def test_m1_final_criterion_excludes_the_design_third():
    import m1 as M
    t = pd.DataFrame({"split": ["final_train"] * 5 + ["final_val"] * 2 + ["final_test"] * 2,
                      "ret_net": [0.5] * 5 + [-0.1] * 4})
    d = M.final_decision(t)
    assert d["mean_positive"] is False and d["n"] == 4
    assert d["design_third"]["n"] == 5 and "detector design" in d["design_third"]["note"]
    assert M.final_decision(t.iloc[:5])["mean_positive"] is None


def test_run_placebo_on_a_guarded_split_is_a_logged_look(tmp_ledger, monkeypatch):
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    ds = _test_ds()
    sig = C._engine_trades(ds, _enter_at(10), {}, C.FillConfig())
    with pytest.raises(C.SplitLocked, match="hypothesis"):
        C.run_placebo(ds, _enter_at(10), {}, C.FillConfig(), sig, n_draws=2)
    C.run_placebo(ds, _enter_at(10), {}, C.FillConfig(), sig, n_draws=2, hypothesis="HP")
    assert [r["kind"] for r in json.loads(tmp_ledger.read_text())["runs"]] == ["run_placebo"]


def test_m1_provisional_train_refuses_sol_lookahead_before_logging(tmp_path, monkeypatch, tmp_ledger):
    import m1 as M
    from conftest import VALID_ALL
    from test_m1 import frames_with, full
    late = C.SolUsd([[T0 + 100 * H, 1, 1, 1, 150.0, 1], [T0 + 200 * H, 1, 1, 1, 140.0, 1]])
    ds = C.Dataset.from_frames("train", *frames_with({i: {"buy": full(0.3)} for i in range(4)}, n=6),
                               census=C.Census.empty(), sol=late, guard=False)
    out, flow = tmp_path / "M1", tmp_path / "flow"
    out.mkdir()
    flow.mkdir()
    (out / "PREREG.md").write_text("# p\n")
    (flow / "validation.json").write_text(json.dumps(VALID_ALL))
    with pytest.raises(M.M1Refused, match="SOL/USD"):
        M.run_stage("train", out_dir=out, ds=ds, flow=flow, ledger_path=tmp_ledger, shortlist_path=tmp_path / "sl",
                    B=100, n_placebo=1, env={}, allow_partial=True)
    assert not tmp_ledger.exists() or not json.loads(tmp_ledger.read_text())["runs"]
    assert not (out / "prereg.lock").exists()

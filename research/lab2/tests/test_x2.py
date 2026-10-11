"""Tests for research/lab2/x2.py: breadth / net-flow features on hand-built minute bars, the causal cross-sectional
reference (no other coin's future, no coin that reaches the checkpoint later), no lookahead (synthetic and real census
bars, the coin's own future and every other coin's), the entry gate, the fade exit, the dose-response gate, the
pre-registered decisions and the stage refusals."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import x2 as X
from conftest import VALID_ALL as VALID
from conftest import make_frames, real_flow_available
from test_common import _garble
from test_m1 import coin_bars, full, mint

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
N_MIN = 186


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def market_frames(t0: int, n: int, seed: int = 1, spacing: int = 90, drift: float = 0.02, inverse: bool = False,
                  overrides: dict | None = None):
    """n coins graduating every ``spacing`` s. Coin i has ``b_i = 2 + 7 i mod 23`` buyers every minute, buys 1.5 and
    sells 1.4 SOL a minute (net +0.1, alive) until minute 31, then drifts by ``drift`` x (b_i - 13) SOL a minute
    (``inverse``: the opposite sign). ``overrides`` {i: coin_bars kwargs} replaces a coin's bars."""
    g, c, _ = make_frames(n=n, seed=seed, t0=t0, spacing=spacing)
    bars = []
    for i, r in enumerate(g.itertuples()):
        if overrides and i in overrides:
            bars.append(coin_bars(int(r.g_ts), r.mint, r.pool, **overrides[i]))
            continue
        bi = 2 + (i * 7) % 23
        d = drift * ((13 - bi) if inverse else (bi - 13))
        buy, sell = full(1.5), full(1.4)
        buy[31:] = 1.5 + max(d, 0.0)
        sell[31:] = 1.5 + max(-d, 0.0)
        bars.append(coin_bars(int(r.g_ts), r.mint, r.pool, buy, sell, n_buyers=full(bi), n_sellers=full(3)))
    return g, c, pd.concat(bars, ignore_index=True)


def market(split: str, t0: int, n: int, seed: int = 1, **kw) -> C.Dataset:
    return ds_of(market_frames(t0, n, seed, **kw), split)


def b_of(i: int) -> int:
    return 2 + (i * 7) % 23


# =========================================================================== features


def test_window_stats_breadth_netflow_and_agent_removal():
    agent = np.zeros(N_MIN)
    agent[0:6] = 0.6
    spec = {"buy": full(1.0) + agent, "sell": full(0.5), "n_buyers": full(5), "n_sellers": full(2), "agent": agent}
    g, c, b = market_frames(T0, 6, overrides={0: spec})
    ci = c.index[c["mint"] == mint(0)][0]
    c.loc[ci, "agent_present"] = True
    c.loc[ci, "agent_wallet"] = "AGENT0"
    c.loc[ci, "agent_known_at"] = float(g.loc[g["mint"] == mint(0), "g_ts"].iloc[0]) + 400.0
    ds = ds_of((g, c, b))
    cd = ds.coin(mint(0))
    before = ds.asof(mint(0), cd.m0 + 6 * 60 + C.GRID_OFFSET_S)       # tau before agent_known_at: NaN, nothing removed
    assert before.tau < cd.g + 400
    w = X.window_stats(before.bars, len(before.bars), 5)
    assert w["breadth"] == pytest.approx(5.0) and w["netflow"] == pytest.approx(5 * (1.6 - 0.5))
    after = ds.asof(mint(0), cd.m0 + 8 * 60 + C.GRID_OFFSET_S)
    assert after.agent_detected and len(after.bars) == 8
    w2 = X.window_stats(after.bars, 6, 5)                              # bars 1..5: the AGENT bought in all five
    assert w2["breadth"] == pytest.approx(4.0) and w2["netflow"] == pytest.approx(5 * 0.5)
    w3 = X.window_stats(after.bars, 8, 5)                              # bars 3..7: AGENT in bars 3, 4, 5
    assert w3["breadth"] == pytest.approx((4 + 4 + 4 + 5 + 5) / 5)
    assert X.window_stats(after.bars, 4, 5) is None                    # fewer bars than the window


def test_features_only_completed_bars_and_pressure_is_netflow_over_X():
    ds = market("train", T0, 6)
    cd = ds.coin(mint(1))
    s = ds.asof(mint(1), X.checkpoint_time(cd, 30))
    f = X.features(s)
    assert s.k in (30, 31) and s.k == (s.tau - cd.m0) // 60 and f["ok"] and f["alive"]
    assert f["breadth"] == pytest.approx(b_of(1)) and f["netflow"] == pytest.approx(10 * 0.1)
    assert f["X"] == pytest.approx(84.990359 + 0.1 * s.k, rel=1e-9)
    assert f["pressure"] == pytest.approx(f["netflow"] / f["X"])


def test_checkpoint_time_is_the_engines_first_decision_at_that_age():
    ds = market("train", T0, 8)

    def enter_at(c):
        def s(snap, p, pos):
            if pos is None and snap.age_s >= 60 * c:
                return C.Enter(exits=C.ExitSpec(max_hold_s=600))
            return None
        return s
    for c in X.CHECKPOINTS_MIN:
        t = C.run_trades(ds, enter_at(c), {}, C.FillConfig())
        for r in t.itertuples(index=False):
            assert r.t_dec == X.checkpoint_time(ds.coin(r.mint), c)
        assert len(t) == len(ds)


# =========================================================================== the reference (causal by construction)


def test_reference_window_excludes_self_future_and_old_coins():
    ref = X.Reference(c_min=30, score_name="breadth", t=np.array([0.0, 100.0, 200.0, 300.0, 400.0]),
                      score=np.array([1.0, 2.0, 3.0, 99.0, 1000.0]), mint=("a", "b", "self", "d", "e"),
                      window_s=250.0)
    assert sorted(ref.pool(300.0, "self").tolist()) == [2.0, 99.0]          # (50, 300]: 100, 300; not self, not 400
    pct, n = ref.percentile(10.0, 300.0, "self")
    assert n == 2 and pct == pytest.approx(0.5)
    pct, n = ref.percentile(2.0, 300.0, "self")                              # ties count half
    assert pct == pytest.approx(0.25)
    assert ref.percentile(5.0, 299.0, "self")[1] == 1                       # the coin at 300 is still in the future


def test_build_reference_reads_each_coin_at_its_own_checkpoint_and_alive_only():
    dead = {"buy": np.r_[np.zeros(20), np.full(N_MIN - 20, 0.001)], "sell": np.r_[np.full(5, 30.0), np.zeros(N_MIN - 5)],
            "n_buyers": full(40)}
    ds = ds_of(market_frames(T0, 10, overrides={3: dead}))
    ref = X.build_reference(ds, 30)
    assert mint(3) not in ref.mint and len(ref.t) == 9                     # not alive at its checkpoint
    for t, s, m in zip(ref.t, ref.score, ref.mint):
        cd = ds.coin(m)
        assert t == X.checkpoint_time(cd, 30)
        assert s == pytest.approx(X.features(ds.asof(m, t))["breadth"])
    assert list(ref.t) == sorted(ref.t)


# =========================================================================== entry and exits


def test_entry_top_decile_after_warmup_only():
    ds = market("train", T0, 160)
    strat = X.strategy_for(ds)
    p = X.make_params(30, 30, "time")
    t = C.run_trades(ds, strat, p, X.MAIN_CFG)
    assert len(t) > 5
    ref = strat.refs[30.0]
    for r in t.itertuples(index=False):
        i = int(r.mint[4:7])
        assert b_of(i) >= 22                                                 # only the broadest buying
        pct, n = ref.percentile(float(b_of(i)), r.t_dec, r.mint)
        assert n >= X.REF_MIN and pct >= X.TOP_PCT
    early = [m for m in ds.mints if ref.percentile(0.0, X.checkpoint_time(ds.coin(m), 30), m)[1] < X.REF_MIN]
    assert early and not set(early) & set(t["mint"])                         # warm-up coins never trade


def test_top_breadth_with_net_selling_is_skipped():
    sellers = {"buy": full(1.5), "sell": full(1.6), "n_buyers": full(60), "n_sellers": full(3)}
    ds = ds_of(market_frames(T0, 160, overrides={120: sellers}))
    strat = X.strategy_for(ds)
    cd = ds.coin(mint(120))
    s = ds.asof(mint(120), X.checkpoint_time(cd, 30))
    ok, info = X.entry_decision(s, strat.refs[30.0])
    assert not ok and info["netflow"] < 0 and info["pct"] is None
    assert mint(120) not in set(C.run_trades(ds, strat, X.make_params(30, 30, "time"), X.MAIN_CFG)["mint"])
    s2 = ds.asof(mint(121), X.checkpoint_time(ds.coin(mint(121)), 30))       # b = 2 + 847 mod 23 = 20: not top
    assert not X.entry_decision(s2, strat.refs[30.0])[0]


def _pos(snap_dec, state=None, p_in=1e-6):
    return C.PositionView(mint=snap_dec.mint, t_dec=snap_dec.t, t_in=snap_dec.t + 30, entry_price=p_in, tokens=1.0,
                          sol_in=0.1, peak=p_in, bars_held=1, unrealized=0.0, exits=C.ExitSpec(),
                          state=state or {}, is_placebo=state is None)


def test_fade_exit_needs_breadth_collapse_and_net_selling_and_placebo_recomputes():
    nb = full(20)
    nb[40:] = 5
    sell = full(1.4)
    sell[40:] = 1.8
    ds = ds_of(market_frames(T0, 6, overrides={2: {"buy": full(1.5), "sell": sell, "n_buyers": nb}}))
    cd = ds.coin(mint(2))
    dec = ds.asof(mint(2), X.checkpoint_time(cd, 30))
    pf, pt = X.make_params(30, 60, "time+fade"), X.make_params(30, 60, "time")
    for state in ({"breadth": 20.0}, None):
        pos = _pos(dec, state)
        assert X.exit_decision(ds.asof(mint(2), cd.m0 + 34 * 60 + 20), pf, pos) is None   # < 5 bars after entry
        assert X.exit_decision(ds.asof(mint(2), cd.m0 + 42 * 60 + 20), pf, pos) is None   # breadth not yet halved
        ex = X.exit_decision(ds.asof(mint(2), cd.m0 + 45 * 60 + 20), pf, pos)
        assert isinstance(ex, C.Exit) and ex.reason == "fade"
        assert X.exit_decision(ds.asof(mint(2), cd.m0 + 45 * 60 + 20), pt, pos) is None
    sell2 = full(1.4)                                                         # breadth collapses, net still buying
    ds2 = ds_of(market_frames(T0, 6, overrides={2: {"buy": full(1.5), "sell": sell2, "n_buyers": nb}}))
    dec2 = ds2.asof(mint(2), X.checkpoint_time(ds2.coin(mint(2)), 30))
    assert X.exit_decision(ds2.asof(mint(2), cd.m0 + 45 * 60 + 20), pf, _pos(dec2, {"breadth": 20.0})) is None


def test_exit_spec_and_grid():
    assert len(X.GRID) == 8 and len({C.params_hash(p) for p in X.GRID}) == 8
    for p in X.GRID:
        for k, v in X.FIXED.items():
            assert p[k] == v
        es = X.exit_spec(p)
        assert es.stop_pct == 0.5 and es.max_hold_s == 60 * p["hold_min"] and es.exit_by_age_s == 178 * 60
        assert p["checkpoint_min"] + p["hold_min"] <= 120                     # the deadline never binds
    with pytest.raises(ValueError):
        X.make_params(45, 30, "time")
    assert X.MAIN_CFG.exit_delay_bars == 1 and X.MAIN_CFG.entry_fill == "worst" and X.MAIN_CFG.exit_fill == "worst"


def test_x2_class_matches_m1_rules():
    import m1
    ds = market("train", T0, 30)
    n = 0
    for m in ds.mints:
        s = ds.asof(m, X.checkpoint_time(ds.coin(m), 30))
        assert X.x2_class(s) == m1.m1_class(s)
        n += 1
    assert n == 30


# =========================================================================== no lookahead


@pytest.mark.parametrize("seed", range(3))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = market_frames(T0, 12, seed=seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(50 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([700, 1900, 2500, 3700, 5000, 7000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert X.features(clean.asof(m, t)) == X.features(dirty.asof(m, t))


def _garble_all(frames, tau, rng):
    for m in list(frames[0]["mint"]):
        frames = _garble(frames, m, tau, rng)
    return frames


@pytest.mark.parametrize("c", X.CHECKPOINTS_MIN)
def test_rank_unchanged_when_every_coin_is_garbage_after_tau(c):
    """The cross-sectional leak test: every coin's data after the target's cutoff is replaced by garbage (later
    coins entirely); the target's percentile, reference size and decision do not move."""
    frames = market_frames(T0, 90, seed=3, spacing=120)
    clean = ds_of(frames)
    rng = np.random.default_rng(7)
    targets = [m for m in clean.mints[45:] if b_of(int(m[4:7])) >= 22][:3] + clean.mints[60:62]
    assert len(targets) >= 4
    ranked = 0
    for m in targets:
        t = X.checkpoint_time(clean.coin(m), c)
        dirty = ds_of(_garble_all(frames, t - C.DECISION_LAG_S, rng))
        assert dirty.mints == clean.mints
        a = X.entry_decision(clean.asof(m, t), X.build_reference(clean, c))
        b = X.entry_decision(dirty.asof(m, t), X.build_reference(dirty, c))
        assert a == b
        ranked += a[1]["gate"] and a[1]["n_ref"] >= X.REF_MIN
        p = X.make_params(c, 30, "time")
        ta = C.run_trades(clean, X.strategy_for(clean), p, X.MAIN_CFG, mints=[m])
        tb = C.run_trades(dirty, X.strategy_for(dirty), p, X.MAIN_CFG, mints=[m])
        assert ta["t_dec"].tolist() == tb["t_dec"].tolist()
    assert ranked >= 3                                    # the rank itself was exercised, not only the gate


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Real bars (census TRAIN third, debug): features unchanged by the coin's own future garbage, and a coin's rank
    unchanged when every coin of a 120-coin slice is garbage after its cutoff."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=C.load_sol_usd())
    order = full_ds.coins.sort_values("g_ts")["mint"].tolist()
    pick = order[100:220]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=full_ds.sol)
    rng = np.random.default_rng(11)
    n = 0
    for m in list(rng.choice(clean.mints, size=10, replace=False)):
        cd = clean.coin(m)
        for dt in (float(rng.uniform(1900, 3500)), float(rng.uniform(3700, 7000))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=full_ds.sol)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert X.features(clean.asof(m, t)) == X.features(dirty.asof(m, t))
            n += 1
    assert n >= 15
    late = sorted(clean.mints, key=lambda m: clean.coin(m).g)[-25:]
    checked = 0
    for m in late[::6]:
        t = X.checkpoint_time(clean.coin(m), 30)
        dirty = C.Dataset.from_frames("final_train", *_garble_all(sub, t - C.DECISION_LAG_S, rng), census=cen,
                                      sol=full_ds.sol)
        if dirty.mints != clean.mints:
            continue
        a = X.entry_decision(clean.asof(m, t), X.build_reference(clean, 30))
        b = X.entry_decision(dirty.asof(m, t), X.build_reference(dirty, 30))
        assert a == b
        checked += 1
    assert checked >= 2


# =========================================================================== dose-response gate


def _obs(c_means: dict, per_bin=(60, 50, 40, 40), noise: float = 0.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for c, means in c_means.items():
        k = 0
        for b, (n, mu) in enumerate(zip(per_bin, means)):
            lo = X.DOSE_BINS[b]
            hi = X.DOSE_BINS[b + 1] if b + 1 < len(X.DOSE_BINS) else 1.0
            for _ in range(n):
                pct = float(rng.uniform(lo, hi - 1e-9))
                rows.append({"mint": f"M{c}_{k}", "c": c, "t": 1e9 + k, "breadth": 1.0, "pressure": 0.01,
                             "netflow": 1.0, "pct": pct, "n_ref": 60, "bin": X._bin_of(pct), "pct_pressure": 0.5,
                             "bin_pressure": 1, "cls": "OTHER", "label": mu + noise * float(rng.normal())})
                k += 1
    return pd.DataFrame(rows)


def test_dose_check_decisions():
    up, flat_top, down = (-0.1, -0.05, 0.0, 0.08), (0.0, 0.0, 0.0, 0.0), (0.1, 0.05, 0.0, -0.1)
    d = X.dose_check(_obs({30: up, 60: down}))
    assert d["decision"] == "PASS" and d["passing_checkpoints"] == [30]
    assert d["per_checkpoint"]["60"]["decision"] == "FAIL"
    assert d["per_checkpoint"]["30"]["inversions"] == 0
    assert X.dose_check(_obs({30: down, 60: flat_top}))["decision"] == "KILL"           # top - all = 0: no PASS
    one_inv = (-0.1, 0.0, -0.02, 0.08)
    assert X.dose_check(_obs({30: one_inv, 60: down}))["passing_checkpoints"] == [30]
    two_inv = (0.0, -0.1, 0.05, 0.01)
    assert X.dose_check(_obs({30: two_inv, 60: down}))["decision"] == "KILL"
    few = X.dose_check(_obs({30: up, 60: up}, per_bin=(60, 50, 40, 20)))
    assert few["decision"] == "UNDERPOWERED"
    empty_bin = X.dose_check(_obs({30: up, 60: up}, per_bin=(60, 50, 0, 40)))
    assert empty_bin["decision"] == "UNDERPOWERED"
    hid = X.dose_check(_obs({30: up, 60: up}), hide=True)
    assert hid["decision"].startswith("HIDDEN")
    for tb in hid["per_checkpoint"].values():
        assert "bin_means" not in tb and "mean_all" not in tb and "bin_means" not in tb["pressure_diagnostic"]


def test_dose_obs_label_is_a_60_minute_hold_from_the_checkpoint():
    ds = market("train", T0, 80)
    refs = X.references(ds, ("breadth", "pressure"))
    obs = X.dose_obs(ds, refs)
    assert len(obs) and obs["n_ref"].min() >= X.REF_MIN and obs["label"].notna().all()
    r = obs.iloc[len(obs) // 2]
    t = C.run_entries(ds, X.X2Strategy({}), {"exit": "time", "checkpoint_min": 0, "hold_min": 60}, X.MAIN_CFG,
                      [(r["mint"], r["t"], C.Enter(exits=C.ExitSpec(stop_pct=0.5, max_hold_s=3600,
                                                                    exit_by_age_s=X.EXIT_BY_AGE_S)))])
    assert float(t["ret_net"].iloc[0]) == pytest.approx(r["label"])
    assert float(t["t_out"].iloc[0]) - float(t["t_in"].iloc[0]) >= 3600


# =========================================================================== pre-registered decisions


def _ev(n, mean, ci_lo, mw2, pc, nf_n=None, nf_mean=None, config="c30|h30|time"):
    return {"config": config, "n": n, "n_coins": n, "mean": mean, "ci90": (ci_lo, ci_lo + 0.1),
            "mean_without_top2": mw2, "placebo": {"mean_diff": pc},
            "non_factory": {"n": n if nf_n is None else nf_n, "mean": mean if nf_mean is None else nf_mean}}


def test_decide_train_shortlists_one_config_from_passing_checkpoints():
    ev = {X.config_key(p): _ev(40, -0.01, -0.05, -0.02, -0.01, config=X.config_key(p)) for p in X.GRID}
    ev["c30|h60|time"] = _ev(40, 0.05, 0.01, 0.04, 0.02)
    ev["c30|h30|time+fade"] = _ev(40, 0.06, 0.00, 0.05, 0.03)
    ev["c60|h60|time"] = _ev(40, 0.20, 0.10, 0.15, 0.10)                     # best, but its checkpoint failed
    d = X.decide_train(ev, passing_checkpoints=[30])
    assert d["verdict"] == "SHORTLISTED" and d["candidate"] == "c30|h60|time" and len(d["shortlist"]) == 1
    assert d["shortlist"][0] == X.make_params(30, 60, "time")
    assert X.decide_train(ev, passing_checkpoints=[30, 60])["candidate"] == "c60|h60|time"
    ev2 = {k: _ev(40, 0.05, 0.01, 0.04, -0.01) for k in ev}                  # placebo diff <= 0 everywhere
    assert X.decide_train(ev2, [30, 60])["verdict"] == "NO_CONFIG"
    ev3 = {k: _ev(12, 0.05, 0.01, 0.04, 0.02) for k in ev}
    assert X.decide_train(ev3, [30, 60])["verdict"] == "UNDERPOWERED_TRAIN"


def test_decide_val_and_confirm_rules():
    assert X.decide_val(_ev(8, 0.1, 0, 0.1, 0.1))["verdict"] == "UNDERPOWERED_VAL"
    assert X.decide_val(_ev(20, 0.1, 0, 0.1, 0.1))["verdict"] == "SELECTED_UNDERPOWERED"
    assert X.decide_val(_ev(40, 0.1, 0, 0.1, 0.1))["verdict"] == "SELECTED"
    assert X.decide_val(_ev(40, 0.1, 0, -0.01, 0.1))["verdict"] == "FAIL_VAL"
    assert X.decide_val(_ev(40, 0.1, 0, 0.1, -0.01))["verdict"] == "FAIL_VAL"
    assert X.decide_val({**_ev(40, 0.1, 0, 0.1, 0.1), "placebo": None})["verdict"] == "FAIL_VAL"
    doc = {"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 70, "mean": -0.01}}}
    assert not X.confirm_allowed(doc)[0]
    assert X.confirm_allowed({"verdict": {"verdict": "UNDERPOWERED"}, "configs": {"candidate": {"n": 3, "mean": -1}}})[0]
    assert not X.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 70, "mean": 1}}})[0]


def test_x21_and_combine_verdict():
    ok8 = [True] * 8

    def base(flags, rej=(), cens=True):
        crit = [{"id": i + 1, "pass": f} for i, f in enumerate(flags)] + [{"id": 9, "pass": None},
                                                                          {"id": 10, "pass": cens}]
        return {"criteria": crit, "auto_rejections": list(rej)}
    good = X.x2_extras(_ev(70, 0.05, 0.01, 0.04, 0.07))
    assert good[0]["pass"] and X.combine_verdict(base(ok8), good) == "PASS"
    farm = X.x2_extras(_ev(70, 0.05, 0.01, 0.04, 0.07, nf_n=6, nf_mean=0.02))      # < 10 non-FACTORY trades
    assert farm[0]["pass"] is False and X.combine_verdict(base(ok8), farm) == "FAIL"
    neg = X.x2_extras(_ev(70, 0.05, 0.01, 0.04, 0.07, nf_n=30, nf_mean=-0.01))
    assert X.combine_verdict(base(ok8), neg) == "FAIL"
    assert X.combine_verdict(base(ok8, ["x"]), good) == "REJECTED"
    assert X.combine_verdict(base([False] + ok8[1:]), good) == "UNDERPOWERED"
    assert X.combine_verdict(base(ok8[:4] + [None] + ok8[5:]), good) == "INCOMPLETE"
    assert X.combine_verdict(base(ok8, cens=False), good) == "INCOMPLETE"


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "X2", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# X2 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return X.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return X.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def test_dose_kill_stops_x2(st):
    ds = market("train", T0, 500, inverse=True)            # the broadest coins drift DOWN: the rank is anti-informative
    doc = _run("train", st, ds)
    assert doc["dose"]["decision"] == "KILL"
    assert doc["decision"]["verdict"] == "KILLED_DOSE" and "configs" not in doc
    assert doc["overall"].startswith("KILLED")
    runs = json.loads(st.ledger.read_text())["runs"]
    assert [r["hypothesis"] for r in runs] == ["X2-dose"]                   # no strategy P&L was run
    assert not (st.sl / "X2.json").exists()
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(X.X2Refused, match="dose-response"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(X.X2Refused, match="final"):
        _run("train", st, ds)
    doc2 = _run("train", st, ds, rerun_reason="test: data correction")
    assert doc2["decision"]["verdict"] == "KILLED_DOSE" and list(st.out.glob("train_prev_*.json"))


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 120)
    with pytest.raises(X.X2Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "X2.json").exists()
    with pytest.raises(X.X2Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:
        monkeypatch.setenv(k, "1")
    with pytest.raises(X.X2Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: dose PASS at 30 min (the broadest coins drift up), the 30-min configs, ONE shortlisted config
    tr = _run("train", st, market("train", T0, 700))
    assert tr["dose"]["decision"] == "PASS" and 30 in tr["dose"]["passing_checkpoints"]
    assert set(tr["configs"]) == {X.config_key(p) for p in X.GRID if p["checkpoint_min"] in
                                  tr["dose"]["passing_checkpoints"]}
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert len(json.loads((st.sl / "X2.json").read_text())["configs"]) == 1
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    n_cfg = sum(1 for v in led["configs"].values() if v["hypothesis"] == "X2")
    assert n_cfg == len(tr["configs"]) and led["n_trials_total"] == 2575 + n_cfg + 1
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(X.X2Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# X2 test prereg\n")
    with pytest.raises(X.X2Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    with pytest.raises(X.X2Refused, match="before TEST"):
        _check("final", st, env=env_all)
    sl = (st.sl / "X2.json").read_text()
    (st.sl / "X2.json").unlink()
    with pytest.raises(X.X2Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "X2.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 01:00"), 450, seed=2))
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"candidate"}
    with pytest.raises(X.X2Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 300, seed=3)
    with pytest.raises(X.X2Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                       # < 60 trades: never PASS / FAIL
    assert [c["id"] for c in te["verdict"]["x2_extras"]] == ["X2.1"]
    with pytest.raises(X.X2Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(X.X2Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 900, seed=4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(X.X2Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 250, seed=5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True and fi["overall"] == "EDGE"
    with pytest.raises(X.X2Refused, match="already ran"):
        _check("final", st, env=env_all)
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] in ("test", "confirm", "final")} == {"X2"}
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(X.X2Refused, match="data first"):
        _check("train", st)
    _check("debug", st)                                                       # debug: mechanics only
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(X.X2Refused, match="pre-register"):
        _check("train", st)


def test_matched_controls_draw_only_where_x2_could_trade(st, monkeypatch):
    """Review X2-PLACEBO-NREF: the matched control is entry conditions 1-3 without the rank (PREREG 5, 10), so every
    placebo and class-matched draw has >= REF_MIN reference coins at its OWN decision time, the drawn coin excluded."""
    ds = market("train", T0, 300)
    ds.split = "final_train"
    ds.debug_only = True
    seen: list[C.Result] = []
    real = C.backtest

    def spy(*a, **k):
        r = real(*a, **k)
        seen.append(r)
        return r
    monkeypatch.setattr(C, "backtest", spy)
    X.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=6, env={})
    refs = X.references(ds)
    n_draws = 0
    for r in seen:
        ref = refs[("breadth", float(r.meta["params"]["checkpoint_min"]))]
        for draws in [r.placebo, *r.controls.values()]:
            for d in draws.itertuples(index=False):
                n_draws += 1
                assert len(ref.pool(float(d.t_dec), d.mint)) >= X.REF_MIN, (d.mint, d.t_dec)
                assert X.placebo_ok(ds.asof(d.mint, float(d.t_dec)))           # conditions 1-2 still hold
    assert n_draws > 100


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 300)
    ds.split = "final_train"
    ds.debug_only = True
    doc = X.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG" and doc["dose"]["decision"].startswith("HIDDEN")
    assert set(doc["configs"]) == {X.config_key(p) for p in X.GRID}
    for e in doc["configs"].values():
        assert "mean" not in e and "ci90" not in e and "placebo" not in e and e["returns"].startswith("hidden")
        assert "reasons" not in e and "stress" not in e and "portfolio" not in e and "non_factory" not in e
    for tb in doc["dose"]["per_checkpoint"].values():
        assert "bin_means" not in tb and "top_minus_all" not in tb
    assert doc["event_counts"]["30"]["top_decile_entries"] == doc["configs"]["c30|h30|time"]["n"] > 0
    assert all(r["debug"] and r["mean"] is None for r in json.loads(st.ledger.read_text())["runs"])
    md = (st.out / "debug.md").read_text()
    assert "hidden" in md.lower() and "%" not in md.split("## Configs")[1]

"""Tests for research/lab2/x3.py: the climax / exhaustion features and the exact reserve math on hand-built minute
bars, the depth band and the cost condition, the class and age gates, engine fills (worst entry, next-bar exits, no
horizon exits), no lookahead (synthetic and real census bars), the reversion gate (events, matched draws, labels,
decisions), the pre-registered decisions and the stage refusals."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import x3 as X
from conftest import VALID_ALL as VALID
from conftest import make_frames, real_flow_available
from test_common import _garble
from test_m1 import X0, Y0, coin_bars, full

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
N_MIN = 186
K0 = X0 * Y0


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def flows(cm: int | None, after: str = "rebound", climax_sell: float = 40.0, grow: float = 5.0, reb: float = 3.0):
    """Buy / sell SOL per minute: grow the pool for 50 min (buy ``grow``, sell 1.5), then a steady 2 / 2 SOL a minute;
    a climax minute ``cm`` sells ``climax_sell`` (buys 2), then 10 minutes of +3 SOL buying (``rebound``), +3 SOL
    selling (``decline``) or nothing (``flat``)."""
    buy, sell = np.zeros(N_MIN), np.zeros(N_MIN)
    buy[:50], sell[:50] = grow, 1.5
    buy[50:], sell[50:] = 2.0, 2.0
    if cm is not None:
        sell[cm], buy[cm] = climax_sell, 2.0
        if after == "rebound":
            buy[cm + 1:cm + 11] += reb
        elif after == "decline":
            sell[cm + 1:cm + 11] += reb
    return buy, sell


def cm_of(i: int) -> int:
    return 65 + (i * 7) % 60


def market_frames(t0: int, n: int, seed: int = 1, spacing: int = 90, after: str = "rebound",
                  overrides: dict | None = None):
    """n coins; coin i has one climax at minute cm_of(i) in a deep pool (X ~ 260 SOL, ~3,840 SOL market cap), then
    ``after``. ``overrides`` {i: kwargs for flows()} changes a coin."""
    g, c, _ = make_frames(n=n, seed=seed, t0=t0, spacing=spacing)
    bars = []
    for i, r in enumerate(g.itertuples()):
        kw = {"cm": cm_of(i), "after": after, **((overrides or {}).get(i, {}))}
        buy, sell = flows(**kw)
        bars.append(coin_bars(int(r.g_ts), r.mint, r.pool, buy, sell, n_buyers=full(4), n_sellers=full(3)))
    return g, c, pd.concat(bars, ignore_index=True)


def market(split: str, t0: int, n: int, seed: int = 1, **kw) -> C.Dataset:
    return ds_of(market_frames(t0, n, seed, **kw), split)


def one_coin(cm=70, after="rebound", seed=1, **kw):
    """A small market whose coin 0 carries the climax spec; returns (ds, mint, CoinData)."""
    ds = market("train", T0, 6, seed=seed, overrides={0: {"cm": cm, "after": after, **kw}})
    m = f"MINT000{seed}pump"
    return ds, m, ds.coin(m)


def snap_after(ds, m, j: int) -> C.AsOf:
    """The engine's decision right after bar j completed (tau = end of bar j)."""
    cd = ds.coin(m)
    return ds.asof(m, cd.bar_start(j + 1) + C.GRID_OFFSET_S)


def X_after(minute: int, cm=70, after="rebound", climax_sell=40.0, grow=5.0, reb=3.0) -> float:
    buy, sell = flows(cm, after, climax_sell, grow, reb)
    return X0 + float((buy[:minute + 1] - sell[:minute + 1]).sum())


# =========================================================================== features


def test_climax_exact_outflow_target_and_round_trip():
    ds, m, cd = one_coin(cm=70)
    s = snap_after(ds, m, 70)
    assert s.k == 71
    ci = X.climax_info(s.bars, 70)
    Xb, Xa = X_after(69), X_after(70)
    assert ci["fires"] and ci["X_before"] == pytest.approx(Xb) and ci["X_after"] == pytest.approx(Xa)
    assert ci["outflow"] == pytest.approx(38.0) and ci["outflow_frac"] == pytest.approx(38.0 / Xb)
    assert ci["drop"] == pytest.approx(1 - (Xa / Xb) ** 2, rel=1e-9)               # price = X^2 / k
    assert ci["target"] == pytest.approx(((Xa + 19.0) ** 2) / K0, rel=1e-9)         # half the outflow returns
    assert ci["base_vol"] == pytest.approx(4.0) and ci["sell_mult"] == pytest.approx(10.0)
    rt = X.round_trip_frac(s)
    k = float(s.bars.X[-1] * s.bars.y[-1])
    assert rt == pytest.approx(C.round_trip_pct(20.0 / 100.0, s.price, k, s.t) / 100.0)
    assert 0.025 < rt < 0.035
    ok, info = X.entry_decision(s, X.make_params(4, "now", 10))
    assert ok and info["tp"] == pytest.approx(((Xa + 19.0) / Xa) ** 2 - 1, rel=1e-9)
    assert info["tp_over_rt"] == pytest.approx(info["tp"] / rt) and info["bucket"] == "d1470"


def test_climax_needs_31_bars_volume_largest_minute_and_net_selling():
    ds, m, cd = one_coin(cm=70)
    s = snap_after(ds, m, 70)
    assert X.climax_info(s.bars, 30) is None and X.climax_info(s.bars, 71) is None      # c >= k: not completed
    for kw, fires in (({"climax_sell": 11.0}, False),        # < 3 x the 4 SOL median minute volume
                      ({"climax_sell": 13.0}, True)):
        ds2, m2, _ = one_coin(cm=70, **kw)
        assert X.climax_info(snap_after(ds2, m2, 70).bars, 70)["fires"] is fires
    # a bigger selling minute 10 minutes earlier: the climax is not the largest of the last half hour
    g, c, _ = make_frames(n=6, seed=1, t0=T0)
    buy, sell = flows(70)
    sell[60] = 45.0
    b = coin_bars(int(g.iloc[0]["g_ts"]), g.iloc[0]["mint"], g.iloc[0]["pool"], buy, sell)
    ds3 = ds_of((g.iloc[:1], c.iloc[:1], b))
    assert not X.climax_info(snap_after(ds3, g.iloc[0]["mint"], 70).bars, 70)["fires"]
    # net buying in the climax minute: not a climax
    buy2, sell2 = flows(70)
    buy2[70] = 45.0
    b2 = coin_bars(int(g.iloc[0]["g_ts"]), g.iloc[0]["mint"], g.iloc[0]["pool"], buy2, sell2)
    ds4 = ds_of((g.iloc[:1], c.iloc[:1], b2))
    assert not X.climax_info(snap_after(ds4, g.iloc[0]["mint"], 70).bars, 70)["fires"]


def test_rug_drop_and_liquidity_event_are_not_climaxes():
    ds, m, _ = one_coin(cm=70, climax_sell=120.0)                  # X 260 -> 142: a 70 % drop
    ci = X.climax_info(snap_after(ds, m, 70).bars, 70)
    assert ci["drop"] > X.MAX_DROP and not ci["fires"]
    g, c, _ = make_frames(n=6, seed=1, t0=T0)
    buy, sell = flows(70)
    b = coin_bars(int(g.iloc[0]["g_ts"]), g.iloc[0]["mint"], g.iloc[0]["pool"], buy, sell, y_shift={70: 0.02})
    ds2 = ds_of((g.iloc[:1], c.iloc[:1], b))
    ci2 = X.climax_info(snap_after(ds2, g.iloc[0]["mint"], 70).bars, 70)
    assert ci2["lp_event"] and not ci2["fires"]


def test_depth_band_and_cost_multiple():
    ds, m, _ = one_coin(cm=70, climax_sell=25.0)                    # tp ~ 10 %: passes m = 2, fails m = 4
    s = snap_after(ds, m, 70)
    ok2, i2 = X.entry_decision(s, X.make_params(2, "now", 10))
    ok4, i4 = X.entry_decision(s, X.make_params(4, "now", 10))
    assert ok2 and not ok4 and 2 * i2["rt"] <= i2["tp"] < 4 * i2["rt"]
    # the same climax in a shallow pool (grown to ~110 SOL only: ~690 SOL market cap) is never a deep entry
    ds2, m2, _ = one_coin(cm=70, climax_sell=12.0, grow=2.0)
    s2 = snap_after(ds2, m2, 70)
    assert s2.mcap_sol < X.DEEP_MCAP_SOL
    ok, info = X.entry_decision(s2, X.make_params(2, "now", 10))
    assert not ok and info["climax"] is None
    assert X.in_band(s2.mcap_sol, "shallow") and X.climax_info(s2.bars, 70)["fires"]
    assert X.depth_bucket(1469.9) == "shallow" and X.depth_bucket(1470) == "d1470"
    assert X.depth_bucket(3440) == "d3440" and X.depth_bucket(1e5) == "d9820"


def test_confirm_timing_needs_exhaustion():
    p = X.make_params(2, "confirm", 10)
    ds, m, _ = one_coin(cm=70, after="rebound")
    assert not X.entry_decision(snap_after(ds, m, 70), p)[0]                 # the climax is the LAST bar: wait
    ok, info = X.entry_decision(snap_after(ds, m, 71), p)
    assert ok and info["c"] == 70 and info["exhausted"]
    assert info["tp"] == pytest.approx(((X_after(70) + 19.0) / X_after(71)) ** 2 - 1, rel=1e-9)
    ds2, m2, _ = one_coin(cm=70, after="decline")                           # lower close: not exhausted
    ok2, info2 = X.entry_decision(snap_after(ds2, m2, 71), p)
    assert not ok2 and info2["exhausted"] is False
    ds3, m3, _ = one_coin(cm=70, after="decline", reb=12.0)                 # heavy selling continues
    assert not X.entry_decision(snap_after(ds3, m3, 71), p)[0]


def test_class_rules_match_m1():
    import m1 as M
    g, c, b = make_frames(n=10, seed=4)
    c.loc[0, "w120_buy_sol"] = 900.0                                         # OPERATOR
    c.loc[1, "w120_top10"] = json.dumps([["Wbig", 29.0, 0.0]])               # instant + top-5 share ~1: FACTORY
    ds = ds_of((g, c, b))
    for m in ds.mints:
        s = ds.asof(m, ds.coin(m).g + 3700)
        assert X.x3_class(s) == M.m1_class(s)
    got = {X.x3_class(ds.asof(m, ds.coin(m).g + 3700)) for m in ds.mints}
    assert {"OPERATOR", "FACTORY", "OTHER"} <= got


# =========================================================================== strategy and engine


def test_strategy_age_window_class_skip_and_exit_spec():
    p = X.make_params(2, "now", 30)
    ds, m, cd = one_coin(cm=70)
    assert X.strategy(snap_after(ds, m, 55), p, None) is None                 # before g + 60 min
    late = ds.asof(m, cd.g + X.AGE_MAX_S + 61)
    assert X.strategy(late, p, None) is C.SKIP
    e = X.strategy(snap_after(ds, m, 70), p, None)
    assert isinstance(e, C.Enter) and e.tag == "d1470"
    assert e.exits.stop_pct == X.STOP_PCT and e.exits.max_hold_s == 1800 and e.exits.exit_by_age_s == 178 * 60
    assert e.exits.take_profit_pct == pytest.approx(((X_after(70) + 19.0) / X_after(70)) ** 2 - 1, rel=1e-9)
    assert X.strategy(snap_after(ds, m, 72), p, object()) is None              # exits are mechanical only
    g, c, b = market_frames(T0, 6, overrides={0: {"cm": 70}})
    c.loc[c["mint"] == m, "w120_buy_sol"] = 900.0                             # OPERATOR: M1's coin, never X3's
    ds_op = ds_of((g, c, b))
    assert X.strategy(snap_after(ds_op, m, 70), p, None) is C.SKIP


def test_engine_entry_fill_target_exit_and_no_horizon_exit():
    ds, m, cd = one_coin(cm=70)
    for timing, j_dec in (("now", 70), ("confirm", 71)):
        p = X.make_params(2, timing, 10)
        t = C.run_trades(ds, X.strategy, p, X.MAIN_CFG, mints=[m])
        assert len(t) == 1
        r = t.iloc[0]
        assert r["t_dec"] == pytest.approx(cd.bar_start(j_dec + 1) + C.GRID_OFFSET_S)
        j_in = j_dec + 1
        assert r["entry_price"] == pytest.approx(max(cd.arr["o"][j_in], cd.arr["h"][j_in]))   # worst: landing high
        assert r["reason"] == "take_profit" and r["ret_net"] > 0
        lvl = r["entry_price"] * (1 + r["take_profit_pct"])
        j_hit = next(j for j in range(j_in, C.N_BARS) if cd.arr["h"][j] >= lvl)
        j_out = cd.bar_of(r["t_out"])
        assert j_out == j_hit + 1                                                  # next-bar exit
        assert r["exit_price"] == pytest.approx(min(cd.arr["o"][j_out], cd.arr["l"][j_out]))
    t_all = C.run_trades(market("train", T0, 40), X.strategy, X.make_params(4, "confirm", 30), X.MAIN_CFG)
    assert len(t_all) == 40 and (t_all["reason"] != "horizon").all()
    assert (t_all["t_out"] - t_all["g_ts"] <= 179 * 60).all() and (t_all["age_dec_s"] <= X.AGE_MAX_S).all()


def test_flat_after_climax_exits_on_time_and_decline_stops_next_bar():
    ds, m, cd = one_coin(cm=70, after="flat")
    t = C.run_trades(ds, X.strategy, X.make_params(2, "now", 10), X.MAIN_CFG, mints=[m])
    assert t.iloc[0]["reason"] == "time" and t.iloc[0]["ret_net"] < 0
    ds2, m2, cd2 = one_coin(cm=70, after="decline", reb=8.0)
    t2 = C.run_trades(ds2, X.strategy, X.make_params(2, "now", 30), X.MAIN_CFG, mints=[m2])
    r = t2.iloc[0]
    assert r["reason"] == "stop" and r["ret_mid"] < -X.STOP_PCT                  # gap through the stop, next bar
    stop_lvl = r["entry_price"] * (1 - X.STOP_PCT)
    j_hit = next(j for j in range(cd2.bar_of(r["t_in"]), C.N_BARS) if cd2.arr["l"][j] <= stop_lvl)
    assert cd2.bar_of(r["t_out"]) == j_hit + 1


def test_placebo_eligibility_requires_depth_but_any_depth_control_does_not():
    ds, m, cd = one_coin(cm=70)
    s = snap_after(ds, m, 80)
    assert X.placebo_ok(s) and X.placebo_any_depth(s)
    ds2, m2, _ = one_coin(cm=70, climax_sell=12.0, grow=2.0)
    s2 = snap_after(ds2, m2, 80)
    assert not X.placebo_ok(s2) and X.placebo_any_depth(s2)
    assert not X.placebo_ok(snap_after(ds, m, 40))                            # outside the age window


def test_matched_placebo_gets_its_draws_when_deep_coins_are_rare(tmp_ledger):
    shallow = {"cm": None, "grow": 2.0}
    over = {i: shallow for i in range(60) if i % 20}                     # 3 deep coins (0, 20, 40) among 60
    ds = market("train", T0, 60, overrides=over)
    p = X.make_params(2, "now", 10)
    res = X.run_config(ds, "train", p, "X3", n_placebo=20, ledger_path=tmp_ledger)
    assert len(res.trades) == 3 and res.meta["placebo_max_tries"] == X.PLACEBO_MAX_TRIES
    few = C.run_placebo(ds, X.strategy, p, X.MAIN_CFG, res.trades, 20, 0, X.placebo_ok, _internal=True)  # 200 tries
    assert len(res.placebo) == 60 > len(few)
    assert (res.placebo["mcap_in_sol"] > 0).all() and set(res.placebo["mint"]) <= set(res.trades["mint"])
    assert (res.placebo["take_profit_pct"].to_numpy() == np.repeat(res.trades["take_profit_pct"].to_numpy(), 20)).all()
    assert len(res.controls["any_depth"]) == 60
    assert set(res.controls["any_depth"]["mint"]) - set(res.trades["mint"])   # the diagnostic draws shallow coins too


# =========================================================================== no lookahead


def _feat(snap):
    out = [X.x3_class(snap), snap.alive(), X.round_trip_frac(snap), snap.mcap_sol]
    for c in (snap.k - 1, snap.k - 2):
        out.append(X.climax_info(snap.bars, c))
    for band in ("deep", "shallow"):
        for p in (X.make_params(2, "now", 10), X.make_params(4, "confirm", 30)):
            out.append(X.entry_decision(snap, p, band))
    return out


@pytest.mark.parametrize("seed", range(3))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = market_frames(T0, 10, seed=seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(80 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        i = int(m[4:7])
        t = cd.bar_start(cm_of(i) + int(rng.integers(0, 3))) + C.GRID_OFFSET_S + float(rng.choice([0, 7, 39]))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean.asof(m, t)) == _feat(dirty.asof(m, t))


def test_trades_and_placebo_entries_unchanged_by_future_garbage():
    frames = market_frames(T0, 12, seed=2)
    clean = ds_of(frames)
    rng = np.random.default_rng(5)
    p = X.make_params(2, "now", 10)
    for m in clean.mints[:6]:
        t_dec = C.run_trades(clean, X.strategy, p, X.MAIN_CFG, mints=[m])["t_dec"].tolist()
        assert len(t_dec) == 1
        dirty = ds_of(_garble(frames, m, t_dec[0] - C.DECISION_LAG_S, rng))
        assert C.run_trades(dirty, X.strategy, p, X.MAIN_CFG, mints=[m])["t_dec"].tolist() == t_dec


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Real bars (census TRAIN third, debug only): every X3 feature unchanged by the coin's own future garbage, at
    decision times inside the window, preferring coins that are deep there."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=C.load_sol_usd())
    deep = [m for m in full_ds.mints if full_ds.asof(m, full_ds.coin(m).g + 5400).mcap_sol >= X.DEEP_MCAP_SOL]
    pick = (deep[:12] + [m for m in full_ds.mints if m not in deep][:8])
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=full_ds.sol)
    rng = np.random.default_rng(13)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(3600, 5400)), float(rng.uniform(5400, 8700))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=full_ds.sol)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean.asof(m, t)) == _feat(dirty.asof(m, t))
            n += 1
    assert n >= 25


# =========================================================================== reversion gate


def test_gate_events_labels_draws_and_skip():
    ds = market("train", T0, 40)
    ev = X.gate_events(ds)
    assert len(ev) == 40 and ev["mint"].nunique() == 40                     # one climax per coin
    r = ev.iloc[3]
    cd = ds.coin(r["mint"])
    s = ds.asof(r["mint"], r["t"])
    for h in X.HOLDS_MIN:
        later = ds.asof(r["mint"], r["t"] + 60 * h)
        assert r[f"label{h}"] == pytest.approx(later.price / s.price - 1)
    assert r["t"] == pytest.approx(cd.bar_start(cm_of(int(r["mint"][4:7])) + 1) + C.GRID_OFFSET_S)
    dr = X.gate_draws(ds, ev.iloc[:5])
    assert (dr["n_draws"] == X.GATE_DRAWS).all() and dr["draw10"].notna().all()
    # skip: two climaxes 20 min apart on one coin give ONE gate event; 40 min apart give two
    for gap, n_ev in ((20, 1), (40, 2)):
        g, c, _ = make_frames(n=3, seed=1, t0=T0)
        buy, sell = flows(70)
        sell[70 + gap] = 60.0
        buy[71 + gap:81 + gap] += 3.0
        b = coin_bars(int(g.iloc[0]["g_ts"]), g.iloc[0]["mint"], g.iloc[0]["pool"], buy, sell)
        d1 = ds_of((g.iloc[:1], c.iloc[:1], b))
        assert len(X.gate_events(d1, with_labels=False)) == n_ev


def test_gate_draws_are_age_matched_and_eligible():
    ds = market("train", T0, 30, overrides={i: {"cm": 70, "grow": 2.0, "climax_sell": 12.0} for i in range(0, 30, 3)})
    ev = X.gate_events(ds)
    seen = []
    orig = X._eligible

    def spy(snap, band):
        ok = orig(snap, band)
        if ok:
            seen.append((snap.age_s, snap.mcap_sol))
        return ok
    X._eligible = spy
    try:
        X.gate_draws(ds, ev.iloc[:3])
    finally:
        X._eligible = orig
    ages = ev.iloc[:3]["age_min"].to_numpy() * 60
    assert seen and all(m >= X.DEEP_MCAP_SOL for _, m in seen)
    assert all(min(abs(a - x) for x in ages) <= C.PLACEBO_AGE_TOL_S for a, _ in seen)
    sh = X.gate_events(ds, band="shallow")
    assert len(sh) == 10 and (sh["mcap_sol"] < X.DEEP_MCAP_SOL).all()


def test_gate_check_decisions():
    up = X.gate_obs(market("train", T0, 60))
    g = X.gate_check(up, B=200)
    assert g["decision"] == "PASS" and g["passing_horizons"] == [10, 30]
    assert g["per_horizon"]["10"]["excess"] > g["per_horizon"]["10"]["mean_rt"] > 0
    down = X.gate_check(X.gate_obs(market("train", T0, 60, after="decline")), B=200)
    assert down["decision"] == "KILL" and down["passing_horizons"] == []
    few = X.gate_check(X.gate_obs(market("train", T0, 40)), B=200)
    assert few["decision"] == "UNDERPOWERED" and few["passing_horizons"] == []
    hobs = X.gate_obs(market("train", T0, 60), with_labels=False)
    assert all("label10" not in ev and "draw10" not in ev for ev in hobs.values())   # counts only
    hid = X.gate_check(hobs, hide=True)
    assert hid["decision"].startswith("HIDDEN") and "per_horizon" not in hid and "diagnostics" not in hid
    assert hid["n_events"] == 60 == hid["n_events_with_draws"] and hid["mean_draws_per_event"] == X.GATE_DRAWS


def test_gate_passes_only_the_horizon_that_beats_costs():
    # rebound for 10 min then a full give-back by minute 25: H10 passes, H30 does not
    g, c, _ = make_frames(n=60, seed=1, t0=T0, spacing=90)
    bars = []
    for i, r in enumerate(g.itertuples()):
        buy, sell = flows(cm_of(i))
        cm = cm_of(i)
        sell[cm + 12:cm + 22] += 3.0 + 3.8                                       # gives back the rebound and more
        bars.append(coin_bars(int(r.g_ts), r.mint, r.pool, buy, sell, n_buyers=full(4), n_sellers=full(3)))
    ds = ds_of((g, c, pd.concat(bars, ignore_index=True)))
    gc = X.gate_check(X.gate_obs(ds), B=200)
    assert gc["decision"] == "PASS" and gc["passing_horizons"] == [10]


# =========================================================================== pre-registered decisions


def _ev(n, mean, ci_lo, mw2, pc, n_coins=None, config="m2|now|h10"):
    return {"config": config, "n": n, "n_coins": n if n_coins is None else n_coins, "mean": mean,
            "ci90": (ci_lo, ci_lo + 0.1), "mean_without_top2": mw2, "placebo": {"mean_diff": pc}}


def test_decide_train_shortlists_one_config_from_passing_horizons():
    ev = {X.config_key(p): _ev(40, -0.01, -0.05, -0.02, -0.01, config=X.config_key(p)) for p in X.GRID}
    ev["m2|now|h10"] = _ev(40, 0.05, 0.01, 0.04, 0.02)
    ev["m4|confirm|h10"] = _ev(40, 0.06, 0.00, 0.05, 0.03)
    ev["m2|now|h30"] = _ev(40, 0.20, 0.10, 0.15, 0.10)                       # best, but its H failed the gate
    d = X.decide_train(ev, passing_horizons=[10])
    assert d["verdict"] == "SHORTLISTED" and d["candidate"] == "m2|now|h10" and len(d["shortlist"]) == 1
    assert d["shortlist"][0] == X.make_params(2, "now", 10)
    assert X.decide_train(ev, passing_horizons=[10, 30])["candidate"] == "m2|now|h30"
    ev2 = {k: _ev(40, 0.05, 0.01, 0.04, -0.01) for k in ev}                  # placebo diff <= 0 everywhere
    assert X.decide_train(ev2, [10, 30])["verdict"] == "NO_CONFIG"
    ev3 = {k: _ev(40, 0.05, 0.01, 0.04, 0.02, n_coins=15) for k in ev}       # 40 trades but 15 coins
    assert X.decide_train(ev3, [10, 30])["verdict"] == "UNDERPOWERED_TRAIN"
    ev4 = {k: _ev(40, 0.05, 0.01, -0.01, 0.02) for k in ev}                  # dies without the top 2
    assert X.decide_train(ev4, [10, 30])["verdict"] == "NO_CONFIG"


def test_decide_val_confirm_and_combine_verdict():
    assert X.decide_val(_ev(4, 0.1, 0, 0.1, 0.1))["verdict"] == "UNDERPOWERED_VAL"
    assert X.decide_val(_ev(10, 0.1, 0, 0.1, 0.1))["verdict"] == "SELECTED_UNDERPOWERED"
    assert X.decide_val(_ev(20, 0.1, 0, 0.1, 0.1))["verdict"] == "SELECTED"
    assert X.decide_val(_ev(20, 0.1, 0, -0.01, 0.1))["verdict"] == "FAIL_VAL"
    assert X.decide_val(_ev(20, 0.1, 0, 0.1, -0.01))["verdict"] == "FAIL_VAL"
    assert X.decide_val({**_ev(20, 0.1, 0, 0.1, 0.1), "placebo": None})["verdict"] == "FAIL_VAL"
    def tdoc(v, n, mean):
        return {"verdict": {"verdict": v}, "configs": {"candidate": {"n": n, "mean": mean}}}
    assert not X.confirm_allowed(tdoc("FAIL", 70, -0.01))[0]
    assert X.confirm_allowed(tdoc("UNDERPOWERED", 3, -1))[0]
    assert not X.confirm_allowed(tdoc("REJECTED", 70, 1))[0]
    ok8 = [True] * 8

    def base(flags, rej=(), cens=True):
        crit = [{"id": i + 1, "pass": f} for i, f in enumerate(flags)] + [{"id": 9, "pass": None},
                                                                          {"id": 10, "pass": cens}]
        return {"criteria": crit, "auto_rejections": list(rej)}
    assert X.combine_verdict(base(ok8)) == "PASS"
    assert X.combine_verdict(base(ok8, ["x"])) == "REJECTED"
    assert X.combine_verdict(base([False] + ok8[1:])) == "UNDERPOWERED"
    assert X.combine_verdict(base(ok8[:4] + [False] + ok8[5:])) == "FAIL"
    assert X.combine_verdict(base(ok8[:4] + [None] + ok8[5:])) == "INCOMPLETE"
    assert X.combine_verdict(base(ok8, cens=False)) == "INCOMPLETE"


def test_grid_is_eight_counted_configs_with_every_constant():
    assert len(X.GRID) == 8 and len({C.params_hash(p) for p in X.GRID}) == 8
    for p in X.GRID:
        for k in ("deep_mcap_sol", "vol_mult", "rho", "stop_pct", "age_max_s", "fill", "version"):
            assert k in p
    with pytest.raises(ValueError):
        X.make_params(3, "now", 10)
    assert X.STRESS["costs_x1.5"].exit_delay_bars == 1 and X.STRESS["same_bar_exits"].exit_delay_bars == 0


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "X3", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# X3 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return X.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return X.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def test_gate_kill_stops_x3(st):
    ds = market("train", T0, 60, after="decline")
    doc = _run("train", st, ds)
    assert doc["gate"]["decision"] == "KILL"
    assert doc["decision"]["verdict"] == "KILLED_GATE" and "configs" not in doc
    assert doc["overall"].startswith("KILLED")
    runs = json.loads(st.ledger.read_text())["runs"]
    assert [r["hypothesis"] for r in runs] == ["X3-gate"]                    # no strategy P&L was run
    assert not (st.sl / "X3.json").exists()
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(X.X3Refused, match="reversion gate"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(X.X3Refused, match="final"):
        _run("train", st, ds)
    doc2 = _run("train", st, ds, rerun_reason="test: data correction")
    assert doc2["decision"]["verdict"] == "KILLED_GATE" and list(st.out.glob("train_prev_*.json"))


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 60)
    with pytest.raises(X.X3Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "X3.json").exists()
    with pytest.raises(X.X3Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:
        monkeypatch.setenv(k, "1")
    with pytest.raises(X.X3Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: gate PASS on both horizons, all 8 configs, ONE shortlisted config
    tr = _run("train", st, market("train", T0, 70))
    assert tr["gate"]["decision"] == "PASS" and tr["gate"]["passing_horizons"] == [10, 30]
    assert set(tr["configs"]) == {X.config_key(p) for p in X.GRID}
    assert all(e["horizon_exits"] == 0 for e in tr["configs"].values())
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert len(json.loads((st.sl / "X3.json").read_text())["configs"]) == 1
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    n_cfg = sum(1 for v in led["configs"].values() if v["hypothesis"] == "X3")
    assert n_cfg == 8 and led["n_trials_total"] == 2575 + n_cfg + 1          # + the gate
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(X.X3Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# X3 test prereg\n")
    with pytest.raises(X.X3Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    with pytest.raises(X.X3Refused, match="before TEST"):
        _check("final", st, env=env_all)
    sl = (st.sl / "X3.json").read_text()
    (st.sl / "X3.json").unlink()
    with pytest.raises(X.X3Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "X3.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 01:00"), 40, seed=2))
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"candidate"}
    with pytest.raises(X.X3Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 40, seed=3)
    with pytest.raises(X.X3Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                       # < 60 trades: never PASS / FAIL
    with pytest.raises(X.X3Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(X.X3Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered, > 12 h of entries): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 160, seed=4, spacing=300), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(X.X3Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 30, seed=5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True and fi["overall"] == "EDGE"
    with pytest.raises(X.X3Refused, match="already ran"):
        _check("final", st, env=env_all)
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] in ("test", "confirm", "final")} == {"X3"}
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(X.X3Refused, match="data first"):
        _check("train", st)
    _check("debug", st)                                                       # debug: mechanics only
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(X.X3Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 40)
    ds.split = "final_train"
    ds.debug_only = True
    doc = X.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG" and doc["gate"]["decision"].startswith("HIDDEN")
    assert "per_horizon" not in doc["gate"] and "diagnostics" not in doc["gate"]
    assert set(doc["configs"]) == {X.config_key(p) for p in X.GRID}
    for e in doc["configs"].values():
        assert "mean" not in e and "ci90" not in e and "placebo" not in e and e["returns"].startswith("hidden")
        assert "reasons" not in e and "stress" not in e and "portfolio" not in e and "mean_mcap_in_sol" not in e
    assert doc["event_counts"]["gate_events_deep"]["n"] == 40 == doc["configs"]["m2|now|h10"]["n"]
    assert "label10" not in json.dumps(doc["event_counts"])
    assert all(r["debug"] and r["mean"] is None for r in json.loads(st.ledger.read_text())["runs"])
    md = (st.out / "debug.md").read_text()
    assert "hidden" in md.lower()

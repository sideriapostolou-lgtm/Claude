"""Tests for research/lab2/z1.py: the EXHAUSTED features on hand-built minute bars (exact window sums, every
condition, AGENT removal), entry and exit rules (incl. placebo recomputation), the pre-registered grid, no lookahead
(synthetic and real census bars), the decision rules and the stage refusals."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import z1 as Z
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186


# =========================================================================== fixtures


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def coin_bars(g: int, mint_: str, pool: str, buy, sell, n_buyers=None, n_sellers=None, agent=None) -> pd.DataFrame:
    """Hand-built minute bars: every SOL goes into the pricing reserve (X += buy - sell), y = k / X. A minute with no
    buy and no sell has no row (as in B2)."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    k = X * y
    rows = []
    for j in range(N_MIN):
        b, s = float(buy[j]), float(sell[j])
        if b <= 0 and s <= 0:
            continue
        X1 = X + b - s
        y1 = k / X1
        bt, st = (y - y1, 0.0) if y1 < y else (0.0, y1 - y)
        p0, p1 = X / y, X1 / y1
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 6 if b > 0 else 0, "n_sells": 3 if s > 0 else 0, "n_dust": 0,
                     "buy_sol": b, "sell_sol": s, "buy_tok": bt, "sell_tok": st,
                     "n_buyers": int(n_buyers[j]) if n_buyers is not None else int(b > 0),
                     "n_sellers": int(n_sellers[j]) if n_sellers is not None else int(s > 0),
                     "top5_buy_sol": b, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": X1 - V0, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0 if agent is None else float(agent[j]), "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0):
    """make_frames (random-walk noise coins: 3 sellers every minute, so they never show a seller decline) with coin
    i's bars replaced by coin_bars(**spec)."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0)
    for i, spec in specs.items():
        r = g[g["mint"] == mint(i, seed)].iloc[0]
        b = pd.concat([b[b["mint"] != r["mint"]], coin_bars(int(r["g_ts"]), r["mint"], r["pool"], **spec)],
                      ignore_index=True)
    return g, c, b


def ds_of(frames, split: str = "train", trades=None) -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, trades=trades, guard=False)


def full(v, n=N_MIN):
    return np.full(n, float(v))


def wave(t_end: int = 25, early=(2.0, 2.0, 5), late=(2.0, 0.5, 1), n_buyers: int = 4, after=None) -> dict:
    """Bars spec: before minute ``t_end`` (buy, sell, sellers) = ``early``; from it ``late``; ``after`` =
    {minute: (buy, sell, sellers)} overrides."""
    buy, sell, ns = full(early[0]), full(early[1]), full(early[2])
    buy[t_end:], sell[t_end:], ns[t_end:] = late
    for j, (b, s, n) in (after or {}).items():
        buy[j], sell[j], ns[j] = b, s, n
    return {"buy": buy, "sell": sell, "n_sellers": ns, "n_buyers": full(n_buyers)}


def snap_k(ds: C.Dataset, m: str, k: int) -> C.AsOf:
    """The decision on the grid at which exactly k bars have completed."""
    cd = ds.coin(m)
    return ds.asof(m, cd.bar_start(k) + C.GRID_OFFSET_S)


P = {K: Z.make_params(K, "t30") for K in Z.K_GRID}


# =========================================================================== EXHAUSTED features


def test_exhaustion_exact_window_sums_and_fires():
    ds = ds_of(frames_with({1: wave()}))
    s = snap_k(ds, mint(1), 30)                 # early half = bars 20-24 (pre), late half = 25-29 (exhausted)
    ex = Z.exhaustion(s, 10)
    assert ex["ok"] and ex["k"] == 30
    assert ex["S_E"] == pytest.approx(10.0) and ex["S_L"] == pytest.approx(2.5)
    assert ex["N_E"] == 25 and ex["N_L"] == 5
    assert ex["B_E"] == pytest.approx(10.0) and ex["B_L"] == pytest.approx(10.0)
    assert ex["share_E"] == pytest.approx(0.5) and ex["share_L"] == pytest.approx(0.2)
    assert ex["X_ref"] == pytest.approx(X0, rel=1e-9)               # flat before minute 25
    X29 = X0 + 5 * 1.5
    assert ex["ret_K"] == pytest.approx((X29 / X0) ** 2 - 1, rel=1e-9)
    assert ex["dd15"] == pytest.approx(0.0, abs=1e-12)
    assert ex["active"] and ex["decline"] and ex["share_falls"] and ex["holds"] and ex["no_dip"] and ex["fires"]


def test_k20_uses_halves_of_ten():
    ds = ds_of(frames_with({1: wave(t_end=30)}))
    ex = Z.exhaustion(snap_k(ds, mint(1), 40), 20)    # early 20-29, late 30-39
    assert ex["S_E"] == pytest.approx(20.0) and ex["S_L"] == pytest.approx(5.0)
    assert ex["N_E"] == 50 and ex["N_L"] == 10 and ex["fires"]
    ex10 = Z.exhaustion(snap_k(ds, mint(1), 40), 10)  # both halves inside the exhausted stretch: no decline
    assert not ex10["decline"] and not ex10["fires"]


def test_too_few_bars_is_not_ok():
    ds = ds_of(frames_with({1: wave()}))
    assert not Z.exhaustion(snap_k(ds, mint(1), 14), 10)["ok"]       # dd15 needs 15 bars
    assert not Z.exhaustion(snap_k(ds, mint(1), 20), 20)["ok"]       # K + 1 bars
    assert Z.exhaustion(snap_k(ds, mint(1), 21), 20)["ok"]


def test_window_boundaries():
    """The bar before the window changes X_ref and ret_K only; it is never in S_E."""
    base = wave()
    alt = {k: v.copy() for k, v in base.items()}
    alt["sell"][19] = 50.0
    alt["n_sellers"][19] = 40
    a = Z.exhaustion(snap_k(ds_of(frames_with({1: base})), mint(1), 30), 10)
    b = Z.exhaustion(snap_k(ds_of(frames_with({1: alt})), mint(1), 30), 10)
    assert a["S_E"] == b["S_E"] and a["N_E"] == b["N_E"]
    assert b["X_ref"] == pytest.approx(a["X_ref"] - 48.0) and b["ret_K"] > a["ret_K"]


def test_dying_coin_does_not_fire():
    """Both sides halve: sellers fell, but the sell share did not."""
    ds = ds_of(frames_with({1: wave(late=(1.0, 1.0, 2))}))
    ex = Z.exhaustion(snap_k(ds, mint(1), 30), 10)
    assert ex["decline"] and not ex["share_falls"] and not ex["fires"]


def test_falling_price_does_not_fire():
    """Sellers fell and the share fell, but the price over the window went down (capitulation territory, not Z1)."""
    ds = ds_of(frames_with({1: wave(early=(1.0, 4.0, 6), late=(0.8, 1.0, 1))}))
    ex = Z.exhaustion(snap_k(ds, mint(1), 30), 10)
    assert ex["active"] and ex["decline"] and ex["share_falls"] and not ex["holds"] and not ex["fires"]


def test_d1_dip_state_is_excluded():
    """A >= 25 % drawdown from the 15-bar high bars Z1 even when every flow condition holds (D1's territory)."""
    spec = wave(early=(1.0, 1.0, 5),
                after={**{j: (12.0, 0.0, 0) for j in range(10, 15)}, **{j: (0.0, 12.0, 5) for j in range(15, 20)},
                       **{j: (2.0, 2.0, 5) for j in range(20, 25)}})
    ds = ds_of(frames_with({1: spec}))
    ex = Z.exhaustion(snap_k(ds, mint(1), 30), 10)
    assert ex["active"] and ex["decline"] and ex["share_falls"] and ex["holds"]
    assert ex["dd15"] >= 0.25 and not ex["no_dip"] and not ex["fires"] and not ex["price_ok"]


def test_activity_minimums():
    ds = ds_of(frames_with({1: wave(early=(0.1, 0.1, 5), late=(0.1, 0.02, 1))}))   # 0.5 SOL < 1 % of X
    ex = Z.exhaustion(snap_k(ds, mint(1), 30), 10)
    assert ex["decline"] and not ex["active"] and not ex["fires"]
    ds = ds_of(frames_with({1: wave(early=(2.0, 2.0, 1), late=(2.0, 0.5, 0), after={24: (2.0, 2.0, 0)})}))  # 4 < 5
    ex = Z.exhaustion(snap_k(ds, mint(1), 30), 10)
    assert ex["N_E"] == pytest.approx(4.0) and not ex["active"] and not ex["fires"]


def test_decline_needs_both_sell_sol_and_sellers():
    ds = ds_of(frames_with({1: wave(late=(2.0, 0.5, 5))}))       # SOL fell, sellers did not
    assert not Z.exhaustion(snap_k(ds, mint(1), 30), 10)["decline"]
    ds = ds_of(frames_with({1: wave(late=(2.0, 2.0, 1))}))       # sellers fell, SOL did not
    assert not Z.exhaustion(snap_k(ds, mint(1), 30), 10)["decline"]


def test_agent_buys_removed_once_known():
    ag = full(0.0)
    ag[20:30] = 1.5
    spec = {**wave(), "agent": ag}
    ds = ds_of(frames_with({0: spec, 1: spec}))          # make_frames: coin 0 has a known AGENT, coin 1 none
    with_agent = Z.exhaustion(snap_k(ds, mint(0), 30), 10)
    no_agent = Z.exhaustion(snap_k(ds, mint(1), 30), 10)
    assert with_agent["B_E"] == pytest.approx(10.0 - 7.5) and with_agent["B_L"] == pytest.approx(10.0 - 7.5)
    assert no_agent["B_E"] == pytest.approx(10.0)        # the AGENT column is NaN for a coin without an AGENT


def test_stratum():
    ds = ds_of(frames_with({}))
    assert Z.stratum(snap_k(ds, mint(0), 31)) == "instant"     # make_frames: graduated 1-4 s after creation
    assert Z.stratum(snap_k(ds, mint(4), 31)) == "slow"        # creation not scanned -> NULL delay -> slow


# =========================================================================== entry and exits


def test_strategy_waits_for_age_skips_late_and_needs_alive():
    ds = ds_of(frames_with({1: wave(), 2: wave(early=(0.2, 0.2, 5), late=(0.2, 0.05, 1))}))
    p = P[10]
    s29 = snap_k(ds, mint(1), 29)
    assert Z.exhaustion(s29, 10)["fires"] and s29.age_s < Z.AGE_MIN_S and Z.strategy(s29, p, None) is None
    s31 = snap_k(ds, mint(1), 31)
    act = Z.strategy(s31, p, None)
    assert isinstance(act, C.Enter) and act.tag == "instant"
    assert act.exits.stop_pct == 0.25 and act.exits.max_hold_s == 1800 and act.exits.exit_by_age_s == 178 * 60
    assert act.state["S_E"] == pytest.approx(Z.exhaustion(s31, 10)["S_E"]) and act.state["active"]
    s125 = snap_k(ds, mint(1), 125)
    assert Z.strategy(s125, p, None) is C.SKIP
    thin = snap_k(ds, mint(2), 31)                          # fires, but $600 of volume in 15 min: not alive
    assert Z.exhaustion(thin, 10)["fires"] and not thin.alive() and Z.strategy(thin, p, None) is None


def test_one_entry_at_the_first_signal_with_worst_fill():
    ds = ds_of(frames_with({1: wave()}))
    t = C.run_trades(ds, Z.strategy, Z.make_params(10, "t30"), Z.FILL, mints=[mint(1)])
    assert len(t) == 1
    r = t.iloc[0]
    cd = ds.coin(mint(1))
    assert Z.AGE_MIN_S <= r["age_dec_s"] < Z.AGE_MIN_S + 60
    j = cd.bar_of(r["t_in"])
    assert r["entry_price"] == pytest.approx(max(cd.arr["o"][j], cd.arr["h"][j]))
    assert r["reason"] == "time" and r["t_out"] - r["t_in"] >= 1800 - 60
    t60 = C.run_trades(ds, Z.strategy, Z.make_params(10, "t60"), Z.FILL, mints=[mint(1)])
    assert t60.iloc[0]["t_out"] - t60.iloc[0]["t_in"] >= 3600 - 60


def test_stop_fills_on_the_next_bar():
    spec = wave(after={40: (0.0, 60.0, 9)})       # a dump: the stop triggers in bar 40, fills in bar 41
    ds = ds_of(frames_with({1: spec}))
    t = C.run_trades(ds, Z.strategy, Z.make_params(10, "t60"), Z.FILL, mints=[mint(1)]).iloc[0]
    cd = ds.coin(mint(1))
    assert t["reason"] == "stop" and cd.bar_of(t["t_out"]) == 41
    assert t["exit_price"] == pytest.approx(min(cd.arr["o"][41], cd.arr["l"][41]))


def test_sellers_return_exit_and_placebo_recomputes_the_reference():
    spec = wave(after={j: (2.0, 2.5, 6) for j in range(45, 50)})     # the selling wave comes back at minute 45
    ds = ds_of(frames_with({1: spec}))
    p = Z.make_params(10, "sret60")
    t = C.run_trades(ds, Z.strategy, p, Z.FILL, mints=[mint(1)]).iloc[0]
    assert t["reason"] == "signal:sellers_return"
    cd = ds.coin(mint(1))
    # reference S_E = 10 SOL (bars 20-24); bars 44-48 sell 0.5 + 4 x 2.5 = 10.5 >= 10, decided after bar 48 -> bar 49
    assert cd.bar_of(t["t_out"]) == 49
    # the same decision for a stateless (placebo) position: the reference is recomputed at its decision
    t_dec = float(t["t_dec"])
    ent = Z.strategy(ds.asof(mint(1), t_dec), p, None)
    for k in range(32, 60):
        s = snap_k(ds, mint(1), k)
        if s.t <= t_dec:
            continue
        mk = dict(mint=mint(1), t_dec=t_dec, t_in=t_dec + 30, entry_price=1.0, tokens=1.0, sol_in=1.0, peak=1.0,
                  bars_held=1, unrealized=0.0, exits=ent.exits)
        real = Z.exit_decision(s, p, C.PositionView(**mk, state=ent.state, is_placebo=False))
        plac = Z.exit_decision(s, p, C.PositionView(**mk, state={}, is_placebo=True))
        assert (real is None) == (plac is None)
    # t30 / t60 never exit on the signal
    assert Z.exit_decision(snap_k(ds, mint(1), 50), Z.make_params(10, "t60"),
                           C.PositionView(**mk, state=ent.state, is_placebo=False)) is None


def test_placebo_without_a_selling_wave_has_no_thesis_exit():
    ds = ds_of(frames_with({1: wave(early=(2.0, 0.2, 1), late=(2.0, 3.0, 9), t_end=40)}))
    p = Z.make_params(10, "sret60")
    s_dec = snap_k(ds, mint(1), 32)
    assert not Z.exhaustion(s_dec, 10)["active"]
    mk = dict(mint=mint(1), t_dec=s_dec.t, t_in=s_dec.t + 30, entry_price=1.0, tokens=1.0, sol_in=1.0, peak=1.0,
              bars_held=1, unrealized=0.0, exits=C.ExitSpec(), state={}, is_placebo=True)
    for k in range(38, 60):                          # heavy selling later: still no thesis exit (stop / time only)
        assert Z.exit_decision(snap_k(ds, mint(1), k), p, C.PositionView(**mk)) is None


def test_grid_is_the_preregistered_grid():
    assert len(Z.GRID) == 6 <= 12
    assert {Z.config_key(p) for p in Z.GRID} == {f"K{k}|{e}" for k in (10, 20) for e in ("t30", "t60", "sret60")}
    assert len({C.params_hash(p) for p in Z.GRID}) == 6
    for p in Z.GRID:
        for k, v in Z.FIXED.items():
            assert p[k] == v
        assert p["max_hold_s"] == Z.HOLD_S[p["exit"]]
    with pytest.raises(ValueError):
        Z.make_params(15, "t30")
    with pytest.raises(ValueError):
        Z.make_params(10, "t45")
    assert Z.FILL.entry_fill == "worst" and Z.FILL.exit_fill == "worst" and Z.FILL.exit_delay_bars == 1
    assert Z.STRESS["costs_x1.5"].exit_delay_bars == 1 and Z.STRESS["same_bar_exits"].exit_delay_bars == 0


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    out = []
    for K in Z.K_GRID:
        ex = Z.exhaustion(s, K)
        out.append(tuple(sorted((k, None if v is None else (round(v, 12) if isinstance(v, float) else v))
                                for k, v in ex.items())))
        out.append(Z.entry_decision(s, P[K])[0])
    return tuple(out) + (Z.stratum(s), s.alive())


def _wave_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(0, 12, 2):
        te = int(rng.integers(20, 90))
        specs[i] = wave(t_end=te, early=(float(rng.uniform(1, 3)), float(rng.uniform(1, 3)), int(rng.integers(3, 8))),
                        late=(float(rng.uniform(1, 3)), float(rng.uniform(0, 1)), int(rng.integers(0, 2))),
                        after={int(rng.integers(te + 5, 170)): (0.0, 30.0, 9)})
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _wave_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([900, 1800, 2100, 3000, 4500, 6000, 7200, 9000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _wave_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(0, 12, 2):
        m = mint(i)
        cd = clean.coin(m)
        T = cd.g + 70 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        for p in Z.GRID:
            a = C.run_trades(clean, Z.strategy, p, Z.FILL, mints=[m])
            b = C.run_trades(dirty, Z.strategy, p, Z.FILL, mints=[m])
            a_dec = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
            assert a_dec == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n_entries += len(a_dec)
    assert n_entries > 0


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Z1 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(12)
    pick = [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=16, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(1800, 3000)), float(rng.uniform(3000, 5000)), float(rng.uniform(5000, 7300))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


# =========================================================================== decision rules


def _ev(n=80, coins=70, mean=0.05, mw2=0.04, ci_lo=0.01, pc=0.03, pm=0.02, cs=0.0, cfg="K10|t30"):
    return {"config": cfg, "params_hash": "h" + cfg, "n": n, "n_coins": coins, "mean": mean, "mean_without_top2": mw2,
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.1), "censored_share": cs,
            "placebo": {"mean_diff": pc}, "controls": {"price_matched": {"mean_diff": pm}}}


def test_decide_train_qualifiers_and_rank_order():
    evals = {Z.config_key(p): _ev(cfg=Z.config_key(p), ci_lo=-0.05) for p in Z.GRID}
    evals["K20|t60"] = _ev(cfg="K20|t60", ci_lo=0.02)
    evals["K10|sret60"] = _ev(cfg="K10|sret60", ci_lo=0.03)
    evals["K10|t30"] = _ev(cfg="K10|t30", ci_lo=0.03, mean=0.06)        # tie on CI: higher mean first
    d = Z.decide_train(evals)
    assert d["verdict"] == "SHORTLISTED" and d["ranked"] == ["K10|t30", "K10|sret60"]
    assert [Z.config_key(p) for p in d["shortlist"]] == d["ranked"]
    for bad in ({"pm": -0.01}, {"pc": 0.0}, {"mw2": -0.01}, {"mean": -0.01}, {"cs": 0.2}, {"n": 59}, {"coins": 39}):
        e = {k: _ev(cfg=k, **bad) for k in evals}
        assert Z.decide_train(e)["verdict"] in ("NO_CONFIG", "UNDERPOWERED_TRAIN")
    assert Z.decide_train({k: _ev(cfg=k, mean=-0.01) for k in evals})["verdict"] == "NO_CONFIG"
    assert Z.decide_train({k: _ev(cfg=k, n=30) for k in evals})["verdict"] == "UNDERPOWERED_TRAIN"
    one = {k: _ev(cfg=k, mean=-0.01) for k in evals}
    one["K20|sret60"] = _ev(cfg="K20|sret60")
    assert Z.decide_train(one)["ranked"] == ["K20|sret60"]


def test_decide_val_is_a_filter_not_a_ranking():
    good, bad, few = _ev(n=20, mean=0.01), _ev(n=20, mean=0.30, mw2=-0.01), _ev(n=4)
    d = Z.decide_val({"rank1": good, "rank2": _ev(n=20, mean=0.5)}, ["rank1", "rank2"])
    assert d["verdict"] == "SELECTED" and d["candidate_role"] == "rank1"     # rank 1 kept although rank 2 looks better
    d = Z.decide_val({"rank1": bad, "rank2": _ev(n=8)}, ["rank1", "rank2"])
    assert d["verdict"] == "SELECTED_UNDERPOWERED" and d["candidate_role"] == "rank2"
    assert Z.decide_val({"rank1": bad, "rank2": few}, ["rank1", "rank2"])["verdict"] == "FAIL_VAL"
    assert Z.decide_val({"rank1": few}, ["rank1"])["verdict"] == "UNDERPOWERED_VAL"


def test_combine_verdict_and_confirm_rule():
    def base(**over):
        crit = [{"id": i, "pass": True} for i in range(1, 11)]
        for i, v in over.items():
            crit[int(i[1:]) - 1]["pass"] = v
        return {"criteria": crit, "auto_rejections": []}
    assert Z.combine_verdict(base(c9=None)) == "PASS"
    assert Z.combine_verdict(base(c1=False, c2=False)) == "UNDERPOWERED"
    assert Z.combine_verdict(base(c5=False)) == "FAIL"
    assert Z.combine_verdict(base(c7=None)) == "INCOMPLETE"
    assert Z.combine_verdict(base(c10=False)) == "INCOMPLETE"
    assert Z.combine_verdict({**base(), "auto_rejections": ["x"]}) == "REJECTED"
    doc = {"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": -0.02}}}
    assert not Z.confirm_allowed(doc)[0]
    doc["configs"]["candidate"] = {"n": 3, "mean": -0.02}
    assert Z.confirm_allowed(doc)[0]
    assert not Z.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 3}}})[0]


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Z1", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Z1 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Z.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Z.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_ex: int, n_noise: int, seed: int, crash: bool = False) -> C.Dataset:
    """n_ex coins whose selling wave ends at minute 25 (then the price climbs; ``crash``: dumped at minute 33) plus
    random-walk noise coins (3 sellers every minute: never exhausted)."""
    after = {33: (0.0, 80.0, 9)} if crash else None
    specs = {i: wave(after=after) for i in range(n_ex)}
    ds = ds_of(frames_with(specs, n=n_ex + n_noise, seed=seed, t0=t0), split)
    assert len(ds) >= n_ex
    return ds


def test_train_no_config_stops_z1(st):
    ds = market("train", T0, 70, 10, 1, crash=True)
    doc = _run("train", st, ds)
    assert doc["decision"]["verdict"] == "NO_CONFIG" and not doc["decision"]["shortlist_written"]
    assert doc["overall"].startswith("NO EDGE")
    assert set(doc["configs"]) == {Z.config_key(p) for p in Z.GRID}
    assert not (st.sl / "Z1.json").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z1") == 6
    assert led["n_trials_total"] == 2575 + 6
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(Z.Z1Refused, match="NO_CONFIG"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(Z.Z1Refused, match="final"):
        _run("train", st, ds)                                          # a decision on complete TRAIN is final
    doc2 = _run("train", st, ds, rerun_reason="test: data correction")
    assert doc2["decision"]["verdict"] == "NO_CONFIG" and list(st.out.glob("train_prev_*.json"))
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6      # a re-run adds no trial


def test_underpowered_train(st):
    doc = _run("train", st, market("train", T0, 20, 4, 1))
    assert doc["decision"]["verdict"] == "UNDERPOWERED_TRAIN"
    with pytest.raises(Z.Z1Refused, match="UNDERPOWERED_TRAIN"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 70, 10, 1)
    with pytest.raises(Z.Z1Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Z1.json").exists()
    with pytest.raises(Z.Z1Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; z1's ``env=`` drives z1's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(Z.Z1Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: the grid, the price-matched control, the shortlist (top 2 in rank order)
    tr = _run("train", st, market("train", T0, 70, 12, 1))
    assert set(tr["configs"]) == {Z.config_key(p) for p in Z.GRID}
    for e in tr["configs"].values():
        assert e["n"] >= 60 and set(e["controls"]) == {"price_matched", "unmatched"}
        assert e["censored_share"] == 0.0 and e["horizon_exits"] == 0
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert len(tr["decision"]["ranked"]) == 2
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z1") == 6
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Z.Z1Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Z1 test prereg\n")
    # TEST / CONFIRM / FINAL before VAL
    for stage in ("test", "confirm", "final"):
        with pytest.raises(Z.Z1Refused, match="no VAL result"):
            _check(stage, st, env=env_all)
    # VAL needs the written shortlist
    sl = (st.sl / "Z1.json").read_text()
    (st.sl / "Z1.json").unlink()
    with pytest.raises(Z.Z1Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Z1.json").write_text(sl)
    # ---- VAL: both shortlisted configs, the rank-1 candidate
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 10, 2))
    assert set(va["configs"]) == {"rank1", "rank2"}
    assert va["decision"]["verdict"] == "SELECTED" and va["decision"]["candidate_role"] == "rank1"
    assert va["decision"]["candidate_config"] == tr["decision"]["ranked"][0]
    with pytest.raises(Z.Z1Refused, match="VAL already ran"):
        _check("val", st)
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6      # VAL adds no trial
    # FINAL / CONFIRM before TEST
    with pytest.raises(Z.Z1Refused, match="before TEST"):
        _check("final", st, env=env_all)
    with pytest.raises(Z.Z1Refused, match="before TEST"):
        _check("confirm", st, env=env_all)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 30, 10, 3)
    with pytest.raises(Z.Z1Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert set(te["configs"]) == {"candidate"}
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    with pytest.raises(Z.Z1Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Z.Z1Refused, match="one test run"):
        _check("test", st, env=env_all)                                   # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 20, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(Z.Z1Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 10, 6, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(Z.Z1Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6      # the whole life of Z1: 6 trials


def test_val_failure_stops_z1(st):
    _run("train", st, market("train", T0, 70, 12, 1))
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 10, 2, crash=True))
    assert va["decision"]["verdict"] == "FAIL_VAL" and va["overall"].startswith("NO EDGE")
    with pytest.raises(Z.Z1Refused, match="FAIL_VAL"):
        _check("test", st, env={"LAB2_ALLOW_TEST": "1"})


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Z.Z1Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Z.Z1Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 36, 12, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Z.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden")
        for k in ("mean", "ci90", "placebo", "controls", "stress", "portfolio", "reasons", "by_stratum"):
            assert k not in e
    ec = doc["event_counts"]
    assert ec["coins_with_condition"]["K10"]["alive_and_fires"] >= 36
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    assert "mean" not in (st.out / "debug.md").read_text().lower().split("## configs")[1].split("## decision")[0]

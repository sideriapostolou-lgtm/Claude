"""Tests for research/lab2/y3.py: the SETUP features on hand-built minute bars (exact box statistics, every
condition, the g + 60 min window, AGENT removal), entry and exit rules (worst next-bar fills, the box stop, the
catastrophe stop on the next bar, placebo recomputation), the pre-registered grid, no lookahead (synthetic and real
census bars), the decision rules and the stage refusals."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import y3 as Y
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
BO = 85                     # breakout minute of the hand-built coins (box [65, 85) fits N = 20 inside g + 60 min)


# =========================================================================== fixtures


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def coin_bars(g: int, mint_: str, pool: str, buy, sell, n_buyers=None, n_sellers=None, top5=None,
              agent=None) -> pd.DataFrame:
    """Hand-built minute bars: every SOL goes into the pricing reserve (X += buy - sell), y = k / X. A minute with no
    buy and no sell has no row (as in B2). ``top5`` = the top-5 buyers' share of the minute's buy SOL."""
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
                     "top5_buy_sol": b * (1.0 if top5 is None else float(top5[j])), "open": p0,
                     "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": X1 - V0, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0 if agent is None else float(agent[j]), "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0):
    """make_frames (random-walk noise coins: 4 buyers a minute, wide ranges: never a Y3 setup) with coin i's bars
    replaced by coin_bars(**spec)."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0)
    for i, spec in specs.items():
        r = g[g["mint"] == mint(i, seed)].iloc[0]
        b = pd.concat([b[b["mint"] != r["mint"]], coin_bars(int(r["g_ts"]), r["mint"], r["pool"], **spec)],
                      ignore_index=True)
    return g, c, b


def ds_of(frames, split: str = "train", sol=SOL) -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=sol, guard=False)


def full(v, n=N_MIN):
    return np.full(n, float(v))


def spec(bo: int = BO, quiet_from: int = 62, after: str = "climb", bo_buy: float = 4.0, bo_sell: float = 0.2,
         bo_buyers: int = 10, bo_top5: float = 0.6, box_buyers: int = 2, quiet_amp: float = 0.5,
         over: dict | None = None) -> dict:
    """Volatile until ``quiet_from`` (X swings +-5.9 SOL a minute), a quiet box (X alternates +-``quiet_amp``), a
    breakout minute ``bo``, then ``after``: climb (net +1.2 SOL a minute), dump (-40 SOL at bo + 2, then flat) or
    flat. ``over`` = {minute: (buy, sell, n_buyers, top5)} overrides."""
    buy, sell, nb, t5 = full(0.0), full(0.0), full(3), full(1.0)
    for j in range(N_MIN):
        if j < quiet_from:
            buy[j], sell[j] = (6.0, 0.1) if j % 2 == 0 else (0.1, 6.0)
        elif j < bo:
            buy[j], sell[j], nb[j] = ((2 * quiet_amp, quiet_amp) if j % 2 == 0 else (quiet_amp, 2 * quiet_amp)) + \
                (box_buyers,)
        elif j == bo:
            buy[j], sell[j], nb[j], t5[j] = bo_buy, bo_sell, bo_buyers, bo_top5
        elif after == "climb":
            buy[j], sell[j], nb[j] = 1.5, 0.3, 6
        elif after == "dump":
            buy[j], sell[j], nb[j] = (0.0, 40.0, 0) if j == bo + 2 else (0.2, 0.2, 1)
        else:
            buy[j], sell[j], nb[j] = 0.5, 0.5, 2
    for j, (b, s, n, t) in (over or {}).items():
        buy[j], sell[j], nb[j], t5[j] = b, s, n, t
    return {"buy": buy, "sell": sell, "n_buyers": nb, "top5": t5}


def snap_k(ds: C.Dataset, m: str, k: int) -> C.AsOf:
    """The decision on the grid at which exactly k bars have completed."""
    cd = ds.coin(m)
    return ds.asof(m, cd.bar_start(k) + C.GRID_OFFSET_S)


def P(N=10, th=0.06, flow="broad"):
    return Y.make_params(N, th, flow)


# =========================================================================== SETUP features


def test_setup_exact_box_statistics_and_fires():
    ds = ds_of(frames_with({1: spec()}))
    s = Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.06)       # breakout bar 85, box 75-84
    assert s["ok"] and s["k"] == BO + 1 and s["in_window"]
    # the volatile phase ends flat (31 up / 31 down swings); in the box X alternates X0 + 0.5 (even minutes) and X0
    # (odd minutes); price = X / y = X^2 / k
    lo, hi = X0 ** 2 / (X0 * Y0), (X0 + 0.5) ** 2 / (X0 * Y0)
    assert s["box_lo"] == pytest.approx(lo, rel=1e-9) and s["box_hi"] == pytest.approx(hi, rel=1e-9)
    assert s["r_box"] == pytest.approx(((X0 + 0.5) / X0) ** 2 - 1, rel=1e-9)
    assert s["traded_frac"] == 1.0
    # bar 84 (even) closed at X0 + 0.5; the breakout bar adds 4.0 - 0.2 SOL
    assert s["ret_bo"] == pytest.approx(((X0 + 4.3) / (X0 + 0.5)) ** 2 - 1, rel=1e-9)
    assert s["nb_bo"] == 10 and s["nb_box"] == 2 and s["top5_share"] == pytest.approx(0.6)
    assert s["net_bo"] == pytest.approx(3.8)
    assert s["compressed"] and s["breakout"] and s["broad"] and s["fires_chart"] and s["fires_broad"]
    s20 = Y.setup(snap_k(ds, mint(1), BO + 1), 20, 0.06)    # box 65-84: still inside the quiet stretch
    assert s20["fires_broad"] and s20["in_window"]


def test_box_must_start_after_g_plus_60():
    ds = ds_of(frames_with({1: spec(bo=68, quiet_from=40)}))    # quiet from 40, breakout at 68
    s10 = Y.setup(snap_k(ds, mint(1), 69), 10, 0.12)         # box 58-67 starts before g + 60
    assert s10["ok"] and not s10["in_window"] and not s10["compressed"] and not s10["fires_chart"]
    assert s10["breakout"] and s10["broad"]                  # everything else holds
    ds = ds_of(frames_with({1: spec(bo=72, quiet_from=40)}))
    assert Y.setup(snap_k(ds, mint(1), 73), 10, 0.12)["fires_broad"]      # box 62-71: inside


def test_theta_separates_tight_and_loose_boxes():
    ds = ds_of(frames_with({1: spec(quiet_amp=1.5)}))       # box range ((X0 + 1.5) / X0)^2 - 1 ~ 3.6 %
    s = Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.06)
    assert s["r_box"] < 0.06 and s["compressed"]
    ds = ds_of(frames_with({1: spec(quiet_amp=3.0, bo_buy=8.0)}))     # ~7.2 % range
    s6, s12 = (Y.setup(snap_k(ds, mint(1), BO + 1), 10, th) for th in (0.06, 0.12))
    assert 0.06 < s6["r_box"] <= 0.12
    assert not s6["compressed"] and not s6["fires_broad"] and s12["compressed"] and s12["fires_broad"]


def test_frozen_box_is_not_compressed():
    """A box where most minutes have no trade has zero range by construction: needs >= 50 % traded minutes."""
    over = {j: (0.0, 0.0, 0, 1.0) for j in range(75, 81)}           # 6 of 10 box minutes without trades
    ds = ds_of(frames_with({1: spec(over=over)}))
    s = Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.06)
    assert s["traded_frac"] == pytest.approx(0.4) and not s["compressed"] and not s["fires_chart"]
    over = {j: (0.0, 0.0, 0, 1.0) for j in range(75, 80)}           # 5 of 10: exactly half is enough
    s = Y.setup(snap_k(ds_of(frames_with({1: spec(over=over)})), mint(1), BO + 1), 10, 0.06)
    assert s["traded_frac"] == pytest.approx(0.5) and s["compressed"]


def test_breakout_needs_close_above_box_and_three_percent():
    ds = ds_of(frames_with({1: spec(bo_buy=1.4)}))           # +0.7 SOL net: above the box high? ret ~1.6 %
    s = Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.06)
    assert s["compressed"] and s["ret_bo"] < 0.03 and not s["breakout"] and not s["fires_chart"]
    # a 3 %+ bar that does not clear the box high: the box's top was set by a spike earlier in the box
    over = {78: (3.0, 0.5, 2, 1.0), 79: (0.5, 3.0, 2, 1.0)}
    ds = ds_of(frames_with({1: spec(over=over, bo_buy=1.9)}))
    s = Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.12)
    assert s["ret_bo"] >= 0.03 and s["compressed"]
    assert s["box_hi"] > float(snap_k(ds, mint(1), BO + 1).bars.c[BO]) and not s["breakout"]


@pytest.mark.parametrize("kw, field", [({"bo_buyers": 4}, "nb_bo"), ({"box_buyers": 6, "bo_buyers": 11}, "nb_box"),
                                       ({"bo_top5": 0.85}, "top5_share"), ({"bo_sell": 4.5}, "net_bo")])
def test_broad_rules(kw, field):
    ds = ds_of(frames_with({1: spec(**kw)}))
    s = Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.12)
    if field == "net_bo":                     # net selling also kills the breakout (price falls on a CP pool)
        assert s["net_bo"] < 0 and not s["broad"]
        return
    assert s["compressed"] and s["breakout"] and not s["broad"] and s["fires_chart"] and not s["fires_broad"]
    if field == "nb_box":
        assert s["nb_bo"] == 11 and s["nb_box"] == 6           # 11 < 2 x 6
    ok = ds_of(frames_with({1: spec(bo_buyers=5, box_buyers=2)}))
    assert Y.setup(snap_k(ok, mint(1), BO + 1), 10, 0.12)["broad"]    # exactly 5 and >= 2 x 2: passes


def test_agent_buys_removed_once_known():
    ag = full(0.0)
    ag[BO] = 0.5
    ag[75:BO] = 0.02
    sp = {**spec(bo_buyers=5), "agent": ag}
    ds = ds_of(frames_with({0: sp, 1: sp}))                  # make_frames: coin 0 has a known AGENT, coin 1 none
    a, b = (Y.setup(snap_k(ds, mint(i), BO + 1), 10, 0.12) for i in (0, 1))
    assert a["nb_bo"] == 4 and a["nb_box"] == 1 and a["net_bo"] == pytest.approx(3.8 - 0.5) and not a["broad"]
    assert b["nb_bo"] == 5 and b["nb_box"] == 2 and b["net_bo"] == pytest.approx(3.8) and b["broad"]


def test_too_few_bars_and_stratum():
    ds = ds_of(frames_with({1: spec()}))
    assert not Y.setup(snap_k(ds, mint(1), 10), 10, 0.06)["ok"]
    assert Y.setup(snap_k(ds, mint(1), 11), 10, 0.06)["ok"]
    assert Y.stratum(snap_k(ds, mint(0), 31)) == "instant"   # make_frames: graduated 1-4 s after creation
    assert Y.stratum(snap_k(ds, mint(4), 31)) == "slow"      # creation not scanned -> NULL delay -> slow


# =========================================================================== entry and exits


def test_strategy_entry_state_age_cap_and_eligibility():
    ds = ds_of(frames_with({1: spec()}))
    p = P()
    assert Y.strategy(snap_k(ds, mint(1), BO), p, None) is None            # no breakout yet
    act = Y.strategy(snap_k(ds, mint(1), BO + 1), p, None)
    assert isinstance(act, C.Enter) and act.tag == "instant"
    assert act.exits.stop_pct == 0.25 and act.exits.max_hold_s == 1800 and act.exits.exit_by_age_s == 178 * 60
    s = Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.06)
    assert act.state["box_lo"] == pytest.approx(s["box_lo"]) and act.state["box_hi"] == pytest.approx(s["box_hi"])
    assert Y.strategy(snap_k(ds, mint(1), 131), p, None) is C.SKIP         # age > 130 min
    late = ds_of(frames_with({1: spec(bo=128, quiet_from=100)}))
    assert Y.setup(snap_k(late, mint(1), 129), 10, 0.06)["fires_broad"]
    assert snap_k(late, mint(1), 129).age_s <= Y.AGE_MAX_S and isinstance(Y.strategy(snap_k(late, mint(1), 129), p,
                                                                                       None), C.Enter)
    poor = ds_of(frames_with({1: spec()}), sol=C.SolUsd(fallback=10.0))   # mcap ~ $4.1k < $6k
    s_poor = snap_k(poor, mint(1), BO + 1)
    assert Y.setup(s_poor, 10, 0.06)["fires_broad"] and not Y.eligible(s_poor)
    assert Y.strategy(s_poor, p, None) is None


def test_chart_twin_enters_where_broad_does_not():
    ds = ds_of(frames_with({1: spec(bo_buyers=2), 2: spec()}))
    for i, want_broad in ((1, False), (2, True)):
        tb = C.run_trades(ds, Y.strategy, P(flow="broad"), Y.FILL, mints=[mint(i)])
        tc = C.run_trades(ds, Y.strategy, P(flow="chart"), Y.FILL, mints=[mint(i)])
        assert len(tb) == int(want_broad) and len(tc) == 1


def test_one_entry_with_worst_fill_and_time_exit_on_the_next_bar():
    ds = ds_of(frames_with({1: spec()}))
    t = C.run_trades(ds, Y.strategy, P(), Y.FILL, mints=[mint(1)])
    assert len(t) == 1
    r = t.iloc[0]
    cd = ds.coin(mint(1))
    j = cd.bar_of(r["t_in"])
    assert j == BO + 1 and r["entry_price"] == pytest.approx(max(cd.arr["o"][j], cd.arr["h"][j]))
    assert r["reason"] == "time"
    jo = cd.bar_of(r["t_out"])
    assert r["exit_price"] == pytest.approx(min(cd.arr["o"][jo], cd.arr["l"][jo]))
    assert 30 * 60 <= r["t_out"] - r["t_in"] <= 32 * 60 + 1


def test_box_stop_fires_on_a_close_below_the_box_and_fills_next_bar():
    over = {BO + 3: (0.0, 10.0, 0, 1.0)}                      # bar 88 closes ~ -20 % (below the box, above -25 %)
    ds = ds_of(frames_with({1: spec(after="flat", over=over)}))
    t = C.run_trades(ds, Y.strategy, P(), Y.FILL, mints=[mint(1)]).iloc[0]
    cd = ds.coin(mint(1))
    drop = cd.arr["c"][BO + 3] / t["entry_price"]
    assert 0.75 < drop < 0.80                                # below the box low, above the catastrophe stop
    assert cd.arr["c"][BO + 3] < Y.setup(snap_k(ds, mint(1), BO + 1), 10, 0.06)["box_lo"]
    assert t["reason"] == "signal:box_fail" and cd.bar_of(t["t_out"]) == BO + 4
    assert t["exit_price"] == pytest.approx(min(cd.arr["o"][BO + 4], cd.arr["l"][BO + 4]))


def test_catastrophe_stop_fills_on_the_next_bar():
    ds = ds_of(frames_with({1: spec(after="dump")}))          # -40 SOL at bar 87
    t = C.run_trades(ds, Y.strategy, P(), Y.FILL, mints=[mint(1)]).iloc[0]
    cd = ds.coin(mint(1))
    assert t["reason"] == "stop" and cd.bar_of(t["t_out"]) == BO + 3
    assert t["exit_price"] == pytest.approx(min(cd.arr["o"][BO + 3], cd.arr["l"][BO + 3]))
    assert t["ret_net"] < -0.5


def test_placebo_recomputes_the_same_box_stop():
    over = {BO + 6: (0.0, 10.0, 0, 1.0)}
    ds = ds_of(frames_with({1: spec(after="flat", over=over)}))
    p = P()
    s_dec = snap_k(ds, mint(1), BO + 1)
    ent = Y.strategy(s_dec, p, None)
    n_exit = 0
    for k in range(BO + 1, BO + 12):
        s = snap_k(ds, mint(1), k)
        mk = dict(mint=mint(1), t_dec=s_dec.t, t_in=s_dec.t + 30, entry_price=1.0, tokens=1.0, sol_in=1.0, peak=1.0,
                  bars_held=1, unrealized=0.0, exits=ent.exits)
        real = Y.exit_decision(s, p, C.PositionView(**mk, state=ent.state, is_placebo=False))
        plac = Y.exit_decision(s, p, C.PositionView(**mk, state={}, is_placebo=True))
        assert (real is None) == (plac is None)
        n_exit += real is not None
        if k <= BO + 1:
            assert real is None                             # no bar completed after the entry decision yet
    assert n_exit > 0


def test_grid_is_the_preregistered_grid():
    assert len(Y.GRID) == 8 <= 12
    assert {Y.config_key(p) for p in Y.GRID} == {f"N{n}|th{t:g}|{f}" for n in (10, 20) for t in (0.06, 0.12)
                                                 for f in ("broad", "chart")}
    assert len({C.params_hash(p) for p in Y.GRID}) == 8
    for p in Y.GRID:
        for k, v in Y.FIXED.items():
            assert p[k] == v
        tw = Y.twin_of(p)
        assert tw["flow"] == "chart" and tw["N"] == p["N"] and tw["theta"] == p["theta"]
    for bad in ((15, 0.06, "broad"), (10, 0.08, "broad"), (10, 0.06, "volume")):
        with pytest.raises(ValueError):
            Y.make_params(*bad)
    assert Y.FILL.entry_fill == "worst" and Y.FILL.exit_fill == "worst" and Y.FILL.exit_delay_bars == 1
    assert Y.STRESS["costs_x1.5"].exit_delay_bars == 1 and Y.STRESS["same_bar_exits"].exit_delay_bars == 0
    assert Y.AGE_MAX_S + 60 + Y.HOLD_S + 180 < Y.EXIT_BY_AGE_S        # the deadline never binds: no censoring


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    out = []
    for N in Y.N_GRID:
        for th in Y.THETA_GRID:
            st = Y.setup(s, N, th)
            out.append(tuple(sorted((k, None if v is None else (round(v, 12) if isinstance(v, float) else v))
                                    for k, v in st.items())))
            for f in Y.FLOW_GRID:
                out.append(Y.entry_decision(s, Y.make_params(N, th, f))[0])
    return tuple(out) + (Y.stratum(s), Y.eligible(s))


def _setup_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(0, 12, 2):
        bo = int(rng.integers(80, 125))
        specs[i] = spec(bo=bo, quiet_from=bo - int(rng.integers(12, 30)), bo_buyers=int(rng.integers(3, 12)),
                        bo_top5=float(rng.uniform(0.4, 1.0)), after=str(rng.choice(["climb", "dump", "flat"])))
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _setup_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([3000, 4300, 5100, 6000, 7000, 7800, 9000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _setup_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(0, 12, 2):
        m = mint(i)
        cd = clean.coin(m)
        T = cd.g + 110 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        for p in Y.GRID:
            a = C.run_trades(clean, Y.strategy, p, Y.FILL, mints=[m])
            b = C.run_trades(dirty, Y.strategy, p, Y.FILL, mints=[m])
            a_dec = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
            assert a_dec == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n_entries += len(a_dec)
    assert n_entries > 0


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Y3 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(13)
    pick = [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=16, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(4300, 5500)), float(rng.uniform(5500, 6700)), float(rng.uniform(6700, 7900))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


# =========================================================================== decision rules


def _ev(n=80, coins=70, mean=0.05, mw2=0.04, ci_lo=0.01, pc=0.03, pm=0.02, cs=0.0, cfg="N10|th0.06|broad"):
    return {"config": cfg, "params_hash": "h" + cfg, "n": n, "n_coins": coins, "mean": mean, "mean_without_top2": mw2,
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.1), "censored_share": cs,
            "placebo": {"mean_diff": pc}, "controls": {"compressed": {"mean_diff": pm}}}


def _evals(**kw):
    out = {}
    for p in Y.GRID:
        k = Y.config_key(p)
        out[k] = _ev(cfg=k, **kw) if p["flow"] == "broad" else _ev(cfg=k, mean=-0.02, n=150, coins=120)
    return out


def test_decide_train_qualifiers_rank_and_pair():
    ev = _evals(ci_lo=-0.05)
    ev["N20|th0.12|broad"] = _ev(cfg="N20|th0.12|broad", ci_lo=0.02)
    ev["N10|th0.12|broad"] = _ev(cfg="N10|th0.12|broad", ci_lo=0.03)
    ev["N20|th0.06|broad"] = _ev(cfg="N20|th0.06|broad", ci_lo=0.03, mean=0.06)    # tie on CI: higher mean wins
    d = Y.decide_train(ev)
    assert d["verdict"] == "SHORTLISTED" and d["candidate"] == "N20|th0.06|broad" and d["twin"] == "N20|th0.06|chart"
    assert [Y.config_key(p) for p in d["shortlist"]] == ["N20|th0.06|broad", "N20|th0.06|chart"]
    assert d["shortlist_hashes"] == [C.params_hash(p) for p in d["shortlist"]]
    assert {r["config"] for r in d["rows"]} == {Y.config_key(p) for p in Y.GRID if p["flow"] == "broad"}
    for bad in ({"pm": -0.01}, {"pc": 0.0}, {"mw2": -0.01}, {"mean": -0.01}, {"cs": 0.2}, {"n": 59}, {"coins": 39}):
        assert Y.decide_train(_evals(**bad))["verdict"] in ("NO_CONFIG", "UNDERPOWERED_TRAIN")
    # the flow rule must add to the chart twin: broad mean 0.05 vs twin 0.06 -> nothing qualifies
    ev = _evals()
    for p in Y.GRID:
        if p["flow"] == "chart":
            ev[Y.config_key(p)]["mean"] = 0.06
    assert Y.decide_train(ev)["verdict"] == "NO_CONFIG"
    assert Y.decide_train(_evals(mean=-0.01))["verdict"] == "NO_CONFIG"
    assert Y.decide_train(_evals(n=30))["verdict"] == "UNDERPOWERED_TRAIN"
    # a chart config is never the candidate, however good it looks
    ev = _evals(mean=-0.01)
    for p in Y.GRID:
        if p["flow"] == "chart":
            ev[Y.config_key(p)] = _ev(cfg=Y.config_key(p), mean=0.5, ci_lo=0.3)
    assert Y.decide_train(ev)["verdict"] == "NO_CONFIG"


def test_decide_val_and_confirm_rule():
    assert Y.decide_val(_ev(n=4))["verdict"] == "UNDERPOWERED_VAL"
    assert Y.decide_val(_ev(n=20, mean=-0.01))["verdict"] == "FAIL_VAL"
    assert Y.decide_val(_ev(n=20, mw2=-0.01))["verdict"] == "FAIL_VAL"
    assert Y.decide_val(_ev(n=8))["verdict"] == "SELECTED_UNDERPOWERED"
    assert Y.decide_val(_ev(n=15))["verdict"] == "SELECTED"
    doc = {"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": -0.02}}}
    assert not Y.confirm_allowed(doc)[0]
    doc["configs"]["candidate"] = {"n": 3, "mean": -0.02}
    assert Y.confirm_allowed(doc)[0]
    assert not Y.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 3}}})[0]


def test_combine_verdict():
    def base(**over):
        crit = [{"id": i, "pass": True} for i in range(1, 11)]
        for i, v in over.items():
            crit[int(i[1:]) - 1]["pass"] = v
        return {"criteria": crit, "auto_rejections": []}
    assert Y.combine_verdict(base(c9=None)) == "PASS"
    assert Y.combine_verdict(base(c1=False, c2=False)) == "UNDERPOWERED"
    assert Y.combine_verdict(base(c5=False)) == "FAIL"
    assert Y.combine_verdict(base(c7=None)) == "INCOMPLETE"
    assert Y.combine_verdict(base(c10=False)) == "INCOMPLETE"
    assert Y.combine_verdict({**base(), "auto_rejections": ["x"]}) == "REJECTED"


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Y3", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Y3 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Y.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Y.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_good: int, n_paint: int, n_noise: int, seed: int, crash: bool = False) -> C.Dataset:
    """n_good coins with a broad breakout that climbs (``crash``: dumped two bars later), n_paint coins with a
    narrow (2-buyer) breakout that is dumped (only the chart twin buys them), and random-walk noise coins."""
    specs = {i: spec(after="dump" if crash else "climb") for i in range(n_good)}
    specs.update({i: spec(bo_buyers=2, after="dump") for i in range(n_good, n_good + n_paint)})
    ds = ds_of(frames_with(specs, n=n_good + n_paint + n_noise, seed=seed, t0=t0), split)
    assert len(ds) >= n_good + n_paint
    return ds


def test_train_no_config_stops_y3(st):
    ds = market("train", T0, 70, 20, 8, 1, crash=True)
    doc = _run("train", st, ds)
    assert doc["decision"]["verdict"] == "NO_CONFIG" and not doc["decision"]["shortlist_written"]
    assert doc["overall"].startswith("NO EDGE")
    assert set(doc["configs"]) == {Y.config_key(p) for p in Y.GRID}
    assert not (st.sl / "Y3.json").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Y3") == 8
    assert led["n_trials_total"] == 2575 + 8
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(Y.Y3Refused, match="NO_CONFIG"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(Y.Y3Refused, match="final"):
        _run("train", st, ds)                                          # a decision on complete TRAIN is final
    doc2 = _run("train", st, ds, rerun_reason="test: data correction")
    assert doc2["decision"]["verdict"] == "NO_CONFIG" and list(st.out.glob("train_prev_*.json"))
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 8      # a re-run adds no trial


def test_underpowered_train(st):
    doc = _run("train", st, market("train", T0, 20, 5, 4, 1))
    assert doc["decision"]["verdict"] == "UNDERPOWERED_TRAIN"
    with pytest.raises(Y.Y3Refused, match="UNDERPOWERED_TRAIN"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 70, 20, 8, 1)
    with pytest.raises(Y.Y3Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Y3.json").exists()
    with pytest.raises(Y.Y3Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; y3's ``env=`` drives y3's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(Y.Y3Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: the grid, both controls, the twin rule, the pair shortlist
    tr = _run("train", st, market("train", T0, 70, 30, 10, 1))
    assert set(tr["configs"]) == {Y.config_key(p) for p in Y.GRID}
    for e in tr["configs"].values():
        assert set(e["controls"]) == {"compressed", "unmatched"}
        assert e["censored_share"] == 0.0 and e["horizon_exits"] == 0
        assert e["n"] >= (70 if e["flow"] == "broad" else 100)
    assert tr["decision"]["verdict"] == "SHORTLISTED", tr["decision"]["rows"]
    assert tr["decision"]["shortlist_written"] and tr["decision"]["candidate"].endswith("|broad")
    assert tr["decision"]["twin"] == tr["decision"]["candidate"].replace("broad", "chart")
    assert all(r["broad_minus_chart"] > 0 for r in tr["decision"]["rows"])
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Y3") == 8
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Y.Y3Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Y3 test prereg\n")
    # TEST / CONFIRM / FINAL before VAL
    for stage in ("test", "confirm", "final"):
        with pytest.raises(Y.Y3Refused, match="no VAL result"):
            _check(stage, st, env=env_all)
    # VAL needs the written shortlist
    sl = (st.sl / "Y3.json").read_text()
    (st.sl / "Y3.json").unlink()
    with pytest.raises(Y.Y3Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Y3.json").write_text(sl)
    # ---- VAL: the pair, decision on the candidate
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 4, 2))
    assert set(va["configs"]) == {"candidate", "twin"}
    assert va["configs"]["candidate"]["config"] == tr["decision"]["candidate"]
    assert va["configs"]["twin"]["config"] == tr["decision"]["twin"]
    assert va["decision"]["verdict"] == "SELECTED" and va["decision"]["broad_minus_chart"] > 0
    with pytest.raises(Y.Y3Refused, match="VAL already ran"):
        _check("val", st)
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 8      # VAL adds no trial
    # FINAL / CONFIRM before TEST
    with pytest.raises(Y.Y3Refused, match="before TEST"):
        _check("final", st, env=env_all)
    with pytest.raises(Y.Y3Refused, match="before TEST"):
        _check("confirm", st, env=env_all)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 25, 8, 4, 3)
    with pytest.raises(Y.Y3Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert set(te["configs"]) == {"candidate", "twin"}
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert te["verdict"]["broad_minus_chart"] > 0
    with pytest.raises(Y.Y3Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Y.Y3Refused, match="one test run"):
        _check("test", st, env=env_all)                                   # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 25, 10, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(Y.Y3Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 10, 4, 4, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["decision"]["twin_judged"]["n"] >= fi["decision"]["n"]
    assert fi["overall"] == "EDGE"
    with pytest.raises(Y.Y3Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 8      # the whole life of Y3: 8 trials


def test_val_failure_stops_y3(st):
    _run("train", st, market("train", T0, 70, 30, 10, 1))
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 4, 2, crash=True))
    assert va["decision"]["verdict"] == "FAIL_VAL" and va["overall"].startswith("NO EDGE")
    with pytest.raises(Y.Y3Refused, match="FAIL_VAL"):
        _check("test", st, env={"LAB2_ALLOW_TEST": "1"})


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Y.Y3Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Y.Y3Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 30, 10, 6, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Y.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden")
        for k in ("mean", "ci90", "placebo", "controls", "stress", "portfolio", "reasons", "by_stratum"):
            assert k not in e
    ec = doc["event_counts"]
    assert ec["coins_with_condition"]["N10|th0.06"]["eligible_broad"] >= 30
    assert ec["coins_with_condition"]["N10|th0.06"]["eligible_chart"] >= 40
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    assert "mean" not in (st.out / "debug.md").read_text().lower().split("## configs")[1].split("## decision")[0]

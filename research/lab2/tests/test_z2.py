"""Tests for research/lab2/z2.py: the single-trade pigeonhole bound (incl. a property test on random trade lists),
the whale-bar detector on hand-built minute bars (BOOST window, depth, dust, AGENT), entry timing and fills, the
big-seller exit (identical for placebo positions), placebo strata, no lookahead (synthetic and real census bars), the
pre-registered decision rules, the grid, and every stage refusal."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import z2 as Z
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
BG = {"buys": [0.05], "sells": [0.05]}      # background minute: one small buy, one small sell


# =========================================================================== hand-built bars


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def coin_bars(g: int, mint_: str, pool: str, minutes: dict) -> pd.DataFrame:
    """Hand-built B2 bars from explicit trade lists: ``minutes`` = {j: {"buys": [sol..], "sells": [sol..],
    "agent": sol}}. Every SOL goes into the pricing reserve (X += buy, X -= sell), y = k / X; buys first, then sells.
    A minute that is missing (or has no trade) has no row, as in B2."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    k = X * y
    rows = []
    for j in range(N_MIN):
        spec = minutes.get(j)
        if not spec or not (spec.get("buys") or spec.get("sells")):
            continue
        buys, sells = list(spec.get("buys") or []), list(spec.get("sells") or [])
        p_open, px, bt, st = X / y, [], 0.0, 0.0
        for b in buys:
            X += b
            y1 = k / X
            bt, y = bt + (y - y1), y1
            px.append(X / y)
        for s in sells:
            X -= s
            y1 = k / X
            st, y = st + (y1 - y), y1
            px.append(X / y)
        trades = buys + sells
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": len(buys), "n_sells": len(sells),
                     "n_dust": sum(1 for v in trades if v < 0.01), "buy_sol": float(sum(buys)),
                     "sell_sol": float(sum(sells)), "buy_tok": bt, "sell_tok": st,
                     "n_buyers": sum(1 for v in buys if v >= 0.01), "n_sellers": sum(1 for v in sells if v >= 0.01),
                     "top5_buy_sol": float(sum(sorted(buys)[-5:])), "open": p_open, "high": max([p_open] + px),
                     "low": min([p_open] + px), "close": X / y, "x_close": X - V0, "y_close": y, "mint": mint_,
                     "pool": pool, "g_ts": g, "minute_idx": j, "agent_buy_sol": float(spec.get("agent", 0.0)),
                     "price_repaired": 0})
    return pd.DataFrame(rows)


def background(extra: dict | None = None, n: int = N_MIN) -> dict:
    mins = {j: dict(BG) for j in range(n)}
    for j, spec in (extra or {}).items():
        mins[j] = spec
    return mins


def informed(w: int, size: float = 0.08, drift: float = 1.0, drift_min: int = 30, sign: int = 1) -> dict:
    """A whale prints alone in minute w (a single buy of ``size`` x X0), then ``drift`` SOL a minute of buying
    (sign +1) or selling (sign -1) for ``drift_min`` minutes."""
    ex = {w: {"buys": [size * X0]}}
    for j in range(w + 1, w + 1 + drift_min):
        ex[j] = {"buys": [drift, 0.05]} if sign > 0 else {"buys": [0.05], "sells": [drift]}
    return background(ex)


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0):
    """make_frames' graduates / b2_coins with every coin's bars replaced: coin i uses ``specs[i]`` (minute dict) or
    the background."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0)
    parts = []
    for r in g.itertuples(index=False):
        i = int(r.mint[4:7])
        parts.append(coin_bars(int(r.g_ts), r.mint, r.pool, specs.get(i) or background()))
    return g, c, pd.concat(parts, ignore_index=True)


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def grid_t(cd: C.CoinData, j_done: int) -> float:
    """The decision right after bar ``j_done`` completed."""
    return float(cd.m0 + 60 * (j_done + 1) + C.GRID_OFFSET_S)


def first_boost_free_bar(cd: C.CoinData) -> int:
    return int(math.ceil((cd.g + Z.BOOST_END_S - cd.m0) / 60.0))


# =========================================================================== the pigeonhole bound


def test_trade_lb_examples():
    assert Z.trade_lb(4.0, 1, 0, 0) == pytest.approx(4.0)                       # one buy: exact
    assert Z.trade_lb(3.0 + 0.002, 3, 2, 0) == pytest.approx(2.982)              # two dust buys removed
    assert Z.trade_lb(3.15, 4, 0, 0) == pytest.approx(0.7875)                    # blind spot: diluted by small buys
    assert Z.trade_lb(3.002, 3, 2, 2) == pytest.approx(3.002 / 3)                # dust may be the sells: no removal
    assert Z.trade_lb(0.005, 1, 1, 0) == pytest.approx(0.005)                    # all dust: trivial bound only
    assert Z.trade_lb(0.0, 0, 0, 0) == 0.0 and Z.trade_lb(1.0, 0, 0, 0) == 0.0


@pytest.mark.parametrize("seed", range(6))
def test_trade_lb_never_exceeds_the_true_largest_trade(seed):
    """Property: on random minutes (dust on both sides, mixed sizes) the bound is <= the real largest buy and the
    real largest sell, and equals it when the side has one trade."""
    rng = np.random.default_rng(seed)
    for _ in range(2000):
        nb, ns = int(rng.integers(0, 8)), int(rng.integers(0, 8))
        buys = [float(v) for v in np.where(rng.random(nb) < 0.4, rng.uniform(0.0001, 0.0099, nb),
                                            rng.lognormal(-1.0, 1.5, nb))]
        sells = [float(v) for v in np.where(rng.random(ns) < 0.4, rng.uniform(0.0001, 0.0099, ns),
                                             rng.lognormal(-1.0, 1.5, ns))]
        nd = sum(1 for v in buys + sells if v < 0.01)
        lb_b = Z.trade_lb(sum(buys), nb, nd, ns)
        lb_s = Z.trade_lb(sum(sells), ns, nd, nb)
        assert lb_b <= (max(buys) if buys else 0.0) + 1e-12
        assert lb_s <= (max(sells) if sells else 0.0) + 1e-12
        if nb == 1:
            assert lb_b == pytest.approx(buys[0])


# =========================================================================== the whale-bar detector


def _one(spec_minutes: dict, i: int = 2):
    fr = frames_with({i: spec_minutes})
    ds = ds_of(fr)
    return ds, ds.coin(mint(i))


def test_whale_bar_sizes_against_depth():
    ds, cd = _one(background({20: {"buys": [0.045 * X0]}}))
    s = ds.asof(cd.mint, grid_t(cd, 20))
    w3, w6 = Z.whale_bar(s, 0.03), Z.whale_bar(s, 0.06)
    assert w3["j"] == 20 and w3["lb"] == pytest.approx(0.045 * X0)
    assert w3["x_before"] == pytest.approx(float(cd.arr["X"][19]))
    assert w3["ratio"] == pytest.approx(0.045 * X0 / float(cd.arr["X"][19]))
    assert w3["is_whale"] and not w6["is_whale"]
    assert not Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 21)), 0.03)["is_whale"]     # only the LAST completed bar
    assert not Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 20) - 1.0), 0.03)["is_whale"]  # bar 20 not complete yet


def test_whale_bar_must_lift_the_reserve_net_of_the_minutes_sells():
    """review Z2-1 (z2-v2): the whale's bar must raise the pricing reserve by >= 0.5 q X_before NET of the same
    minute's sells. A whale netted out by sellers did not pay the impact it signals (PREREG 3)."""
    assert Z.VERSION == "z2-v2" and Z.FIXED["min_net_lift_q"] == Z.MIN_NET_LIFT_Q == 0.5
    ds, cd = _one(background({20: {"buys": [0.045 * X0]},
                              30: {"buys": [0.045 * X0], "sells": [0.04 * X0]},    # netted out: dX = 0.005 X0
                              40: {"buys": [0.045 * X0], "sells": [0.01 * X0]}}))  # dX = 0.035 X0
    X = cd.arr["X"]
    alone = Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 20)), 0.03)
    assert alone["is_whale"] and alone["lifts"] and alone["dx"] == pytest.approx(float(X[20] - X[19]))
    netted = Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 30)), 0.03)
    assert netted["ratio"] >= 0.03                              # the single trade is a whale ...
    assert netted["dx"] == pytest.approx(0.005 * X0) and not netted["lifts"] and not netted["is_whale"]   # ... not
    partly = Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 40)), 0.03)
    assert partly["dx"] >= 0.5 * 0.03 * partly["x_before"] and partly["lifts"] and partly["is_whale"]
    # the threshold scales with q: at q = 0.06 the size test is the binding one here
    assert not Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 40)), 0.06)["is_whale"]
    # the debug counts use the same rule: bars 20 and 40 at q = 0.03, none at q = 0.06
    ec = Z.event_counts(ds)
    assert ec["per_q"]["q0.03"]["whale_bars"] == 2 and ec["per_q"]["q0.06"]["whale_bars"] == 0


def test_whale_bar_ignores_the_boost_window_and_agent_buys():
    """Coin 3 has a detected AGENT in make_frames (known at g + 40 s), so its agent_buy_sol column is visible."""
    cd0 = ds_of(frames_with({})).coin(mint(3))
    jb = first_boost_free_bar(cd0)
    ds, cd = _one(background({jb - 1: {"buys": [10.0]}, jb + 5: {"buys": [10.0], "agent": 9.0}}), i=3)
    assert cd.m0 + 60 * (jb - 1) < cd.g + Z.BOOST_END_S <= cd.m0 + 60 * jb
    assert not Z.whale_bar(ds.asof(cd.mint, grid_t(cd, jb - 1)), 0.03)["is_whale"]     # starts inside BOOST
    w = Z.whale_bar(ds.asof(cd.mint, grid_t(cd, jb + 5)), 0.03)                        # agent SOL removed
    assert w["lb"] == pytest.approx(1.0) and not w["is_whale"]
    ds2, cd2 = _one(background({jb: {"buys": [10.0]}}), i=3)
    assert Z.whale_bar(ds2.asof(cd2.mint, grid_t(cd2, jb)), 0.06)["is_whale"]           # first bar after BOOST


def test_busy_minute_hides_the_whale_and_dust_is_removed():
    ds, cd = _one(background({20: {"buys": [5.0, 0.05, 0.05, 0.05]},
                              30: {"buys": [5.0, 0.001, 0.001, 0.001]},
                              40: {"buys": [5.0, 0.001, 0.001, 0.001], "sells": [0.05]}}))
    busy = Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 20)), 0.03)
    assert busy["lb"] == pytest.approx(5.15 / 4) and not busy["is_whale"]
    dusty = Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 30)), 0.03)            # 3 dust buys: d_min = 3 - 0 sells
    assert dusty["lb"] == pytest.approx(5.003 - 0.03) and dusty["is_whale"]
    one_sell = Z.whale_bar(ds.asof(cd.mint, grid_t(cd, 40)), 0.03)         # one dust trade might be the sell
    assert one_sell["lb"] == pytest.approx((5.003 - 0.02) / 2)


def test_depth_bucket_speed_and_stratum():
    assert Z.depth_bucket(10.0) == "X<50" and Z.depth_bucket(50.0) == "50-100" and Z.depth_bucket(100.0) == "X>=100"
    assert Z.depth_bucket(float("nan")) == "unknown"
    ds = ds_of(frames_with({}, n=10))
    for i in range(10):
        cd = ds.coin(mint(i))
        s = ds.asof(cd.mint, grid_t(cd, 30))
        slow = i % 5 == 4                                       # make_frames: every 5th coin has no creation scan
        assert Z.speed_of(s) == ("slow" if slow else "instant")
        assert Z.stratum(s) == f"{'slow' if slow else 'instant'}|50-100"


def test_placebo_eligibility():
    ds, cd = _one({j: dict(BG) for j in range(N_MIN) if j != 40})
    jb = first_boost_free_bar(cd)
    assert not Z.placebo_ok(ds.asof(cd.mint, grid_t(cd, jb - 1)))    # last bar inside the BOOST window
    assert Z.placebo_ok(ds.asof(cd.mint, grid_t(cd, jb)))
    assert not Z.placebo_ok(ds.asof(cd.mint, grid_t(cd, 40)))         # last bar had no trade


# =========================================================================== entry, fills and exits


def test_entry_lands_on_the_next_bar_at_the_worst_price():
    ds, cd = _one(informed(25))
    p = Z.make_params(0.03, 15, "time")
    t = C.run_trades(ds, Z.strategy, p, Z.FILL, mints=[cd.mint])
    assert len(t) == 1
    r = t.iloc[0]
    assert r["t_dec"] == pytest.approx(grid_t(cd, 25)) and r["t_in"] == pytest.approx(grid_t(cd, 25) + 30)
    assert r["entry_price"] == pytest.approx(max(cd.arr["o"][26], cd.arr["h"][26]))
    assert r["max_hold_s"] == 900 and r["stop_pct"] == Z.STOP_PCT and r["exit_by_age_s"] == Z.EXIT_BY_AGE_S
    assert r["tag"] == Z.stratum(ds.asof(cd.mint, grid_t(cd, 25)))
    assert r["reason"] == "time"
    # time exit: triggered in the first bar starting at t_in + 900, filled one bar later at min(open, low)
    jt = int(math.ceil((r["t_in"] + 900 - cd.m0) / 60.0))
    assert r["exit_price"] == pytest.approx(min(cd.arr["o"][jt + 1], cd.arr["l"][jt + 1]))


def test_first_whale_only_and_no_entry_after_120_min():
    ds, cd = _one(background({25: {"buys": [0.04 * X0]}, 60: {"buys": [0.2 * X0]}}))
    t3 = C.run_trades(ds, Z.strategy, Z.make_params(0.03, 15, "time"), Z.FILL, mints=[cd.mint])
    t6 = C.run_trades(ds, Z.strategy, Z.make_params(0.06, 15, "time"), Z.FILL, mints=[cd.mint])
    assert t3["t_dec"].tolist() == [grid_t(cd, 25)] and t6["t_dec"].tolist() == [grid_t(cd, 60)]
    ds2, cd2 = _one(background({125: {"buys": [0.2 * X0]}}))
    assert C.run_trades(ds2, Z.strategy, Z.make_params(0.03, 60, "time"), Z.FILL, mints=[cd2.mint]).empty


def test_deadline_binds_late_long_holds_without_censoring():
    ds, cd = _one(background({118: {"buys": [0.1 * X0]}}))
    r = C.run_trades(ds, Z.strategy, Z.make_params(0.03, 60, "time"), Z.FILL, mints=[cd.mint]).iloc[0]
    assert r["reason"] == "time" and r["t_out"] <= cd.g + 179 * 60 + 60
    assert r["t_out"] - r["t_in"] < 3600


def test_big_seller_exit_only_in_the_seller_set_and_only_after_the_decision():
    ex = {15: {"buys": [0.05], "sells": [3.0]},              # a big sell BEFORE the whale: never an exit reason
          25: {"buys": [0.08 * X0]}, 32: {"buys": [0.05], "sells": [3.0]}}
    ds, cd = _one(background(ex))
    ts = C.run_trades(ds, Z.strategy, Z.make_params(0.03, 60, "seller"), Z.FILL, mints=[cd.mint]).iloc[0]
    tt = C.run_trades(ds, Z.strategy, Z.make_params(0.03, 60, "time"), Z.FILL, mints=[cd.mint]).iloc[0]
    assert ts["reason"] == "signal:big_seller" and ts["t_out"] == pytest.approx(grid_t(cd, 32) + 30)
    assert tt["reason"] == "time"
    # threshold: 0.5 x q x X at the decision; a 3 SOL sell is above it for q = 0.03, below it for q = 0.12
    thr = Z.SELLER_FRAC * 0.03 * float(cd.arr["X"][25])
    assert thr < 3.0 < Z.SELLER_FRAC * 0.12 * float(cd.arr["X"][25])


def test_exit_rule_is_identical_for_a_stateless_placebo_position():
    ds, cd = _one(background({40: {"buys": [0.05], "sells": [2.0]}}))
    p = Z.make_params(0.03, 60, "seller")
    t_dec = grid_t(cd, 30)

    def pv(state):
        return C.PositionView(mint=cd.mint, t_dec=t_dec, t_in=t_dec + 30, entry_price=1.0, tokens=1.0, sol_in=0.2,
                              peak=1.0, bars_held=1, unrealized=0.0, exits=C.ExitSpec(), state=state,
                              is_placebo=not state)
    for j, want in ((39, None), (40, "big_seller")):
        s = ds.asof(cd.mint, grid_t(cd, j))
        a, b = Z.exit_decision(s, p, pv({})), Z.exit_decision(s, p, pv({"whale_lb": 9.0}))
        assert (a and a.reason) == want and (b and b.reason) == want
    assert Z.exit_decision(ds.asof(cd.mint, grid_t(cd, 40)), Z.make_params(0.03, 60, "time"), pv({})) is None


# =========================================================================== grid


def test_grid_is_eight_distinct_trials():
    assert len(Z.GRID) == 8 <= 12
    assert len({C.params_hash(p) for p in Z.GRID}) == 8
    assert {(p["q"], p["hold_min"], p["exit"]) for p in Z.GRID} == {
        (q, h, e) for q in (0.03, 0.06) for h in (15, 60) for e in ("time", "seller")}
    for p in Z.GRID:
        for k, v in Z.FIXED.items():
            assert p[k] == v
    assert Z.PRIMARY_PARAMS in Z.GRID and Z.config_key(Z.PRIMARY_PARAMS) == "q0.03|h60|time"
    with pytest.raises(ValueError):
        Z.make_params(0.03, 15, "trail")


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    ws = tuple(tuple(sorted((k, round(v, 12) if isinstance(v, float) else v) for k, v in Z.whale_bar(s, q).items()))
               for q in (0.01, 0.03, 0.06))
    cd = ds.coin(m)
    pv = C.PositionView(mint=m, t_dec=t - 600, t_in=t - 570, entry_price=1.0, tokens=1.0, sol_in=0.2, peak=1.0,
                        bars_held=1, unrealized=0.0, exits=C.ExitSpec(), state={}, is_placebo=True)
    ex = Z.exit_decision(s, Z.make_params(0.01, 60, "seller"), pv) if t - 600 > cd.g else None
    return ws, Z.stratum(s) if s.k else None, Z.placebo_ok(s), None if ex is None else ex.reason


def _whale_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(0, 12, 2):
        w = int(rng.integers(9, 110))
        specs[i] = informed(w, size=float(rng.uniform(0.02, 0.12)), sign=int(rng.choice([-1, 1])))
        specs[i][int(rng.integers(w + 2, w + 40))] = {"buys": [0.05], "sells": [float(rng.uniform(0.5, 4.0))]}
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _whale_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(14):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([90, 400, 500, 700, 1900, 3000, 4500, 6000, 7200, 9000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _whale_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(0, 12, 2):
        m = mint(i)
        T = clean.coin(m).g + 70 * 60
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
    """Z2 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(11)
    pick = [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=16, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(430, 1700)), float(rng.uniform(1900, 4000)), float(rng.uniform(4000, 7300))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


# =========================================================================== pre-registered decisions


def _ev(n, mean, ci_lo, mw2, pdiff, p=None, ci95=None):
    return {"n": n, "mean": mean, "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.2), "mean_without_top2": mw2,
            "placebo": None if pdiff is None else {"mean_diff": pdiff, "diff_ci95": ci95},
            "params_hash": C.params_hash(p) if p else "h", "config": Z.config_key(p) if p else "c",
            "direction": None}


def test_direction_reading():
    assert Z.direction({"n": 10, "placebo": {"diff_ci95": (0.1, 0.2)}}) == "UNDERPOWERED"
    assert Z.direction({"n": 40, "placebo": {"diff_ci95": (0.01, 0.2)}}) == "INFORMED"
    assert Z.direction({"n": 40, "placebo": {"diff_ci95": (-0.3, -0.01)}}) == "EXIT_LIQUIDITY"
    assert Z.direction({"n": 40, "placebo": {"diff_ci95": (-0.1, 0.1)}}) == "NEITHER"
    assert Z.direction({"n": 40, "placebo": None}) == "NEITHER"


def test_decide_train_top_two_rule():
    evals = {Z.config_key(p): _ev(50, -0.01, -0.05, -0.02, -0.01, p) for p in Z.GRID}
    assert Z.decide_train(evals)["verdict"] == "NO_CONFIG"
    low = {Z.config_key(p): _ev(29, 0.2, 0.1, 0.1, 0.1, p) for p in Z.GRID}
    d = Z.decide_train(low)
    assert d["verdict"] == "UNDERPOWERED_TRAIN" and d["shortlist"] == []
    good = dict(evals)
    a, b, c = Z.make_params(0.06, 60, "seller"), Z.make_params(0.03, 15, "time"), Z.make_params(0.03, 60, "time")
    good[Z.config_key(a)] = _ev(40, 0.05, 0.02, 0.03, 0.04, a)
    good[Z.config_key(b)] = _ev(90, 0.04, 0.02, 0.03, 0.04, b)        # same CI low, lower mean -> ranked 2nd
    good[Z.config_key(c)] = _ev(90, 0.09, 0.01, 0.03, -0.01, c)       # fails the matched control
    d = Z.decide_train(good)
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_keys"] == [Z.config_key(a), Z.config_key(b)]
    assert d["shortlist_hashes"] == [C.params_hash(a), C.params_hash(b)]
    assert d["primary_direction"]["config"] == "q0.03|h60|time"
    tie = dict(evals)
    tie[Z.config_key(a)] = _ev(40, 0.05, 0.02, 0.03, 0.04, a)
    tie[Z.config_key(b)] = _ev(40, 0.05, 0.02, 0.03, 0.04, b)
    assert Z.decide_train(tie)["shortlist_keys"] == [Z.config_key(b), Z.config_key(a)]   # smaller q first


def test_decide_val_picks_the_higher_mean_and_judges_it():
    p1, p2 = Z.make_params(0.03, 15, "time"), Z.make_params(0.06, 60, "time")
    d = Z.decide_val({"sl1": _ev(20, 0.01, 0, 0.005, 0, p1), "sl2": _ev(20, 0.04, 0, 0.02, 0, p2)}, ["sl1", "sl2"])
    assert d["candidate_role"] == "sl2" and d["twin_role"] == "sl1" and d["verdict"] == "SELECTED"
    assert d["candidate_hash"] == C.params_hash(p2)
    d = Z.decide_val({"sl1": _ev(8, 0.02, 0, 0.01, 0, p1), "sl2": _ev(8, 0.02, 0, 0.01, 0, p2)}, ["sl1", "sl2"])
    assert d["candidate_role"] == "sl1" and d["verdict"] == "SELECTED_UNDERPOWERED"     # tie -> TRAIN rank
    assert Z.decide_val({"sl1": _ev(4, 0.5, 0, 0.5, 0, p1)}, ["sl1"])["verdict"] == "UNDERPOWERED_VAL"
    d = Z.decide_val({"sl1": _ev(30, 0.02, 0, -0.01, 0, p1)}, ["sl1"])
    assert d["verdict"] == "FAIL_VAL" and d["twin_role"] is None and d["twin_hash"] is None


def test_combine_verdict_confirm_rule_and_final_thirds():
    def base(passes, rej=()):
        crit = [{"id": i + 1, "pass": v} for i, v in enumerate(passes)]
        return {"criteria": crit, "auto_rejections": list(rej)}
    ok = [True] * 8 + [None, True]                     # item 9 missing (FINAL not run yet), 10 ok
    assert Z.combine_verdict(base(ok)) == "PASS"
    assert Z.combine_verdict(base(ok, ["x"])) == "REJECTED"
    assert Z.combine_verdict(base([False] + ok[1:])) == "UNDERPOWERED"
    assert Z.combine_verdict(base(ok[:4] + [False] + ok[5:])) == "FAIL"
    assert Z.combine_verdict(base(ok[:6] + [None] + ok[7:])) == "INCOMPLETE"
    assert Z.combine_verdict(base(ok[:9] + [False])) == "INCOMPLETE"          # censored: never PASS
    assert Z.confirm_allowed({"verdict": {"verdict": "REJECTED"}})[0] is False
    assert Z.confirm_allowed({"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 3, "mean": -1}}})[0]
    assert not Z.confirm_allowed({"verdict": {}, "configs": {"candidate": {"n": 30, "mean": -0.01}}})[0]
    t = pd.DataFrame({"split": ["final_train", "final_val", "final_test"], "ret_net": [5.0, -0.1, 0.05]})
    d = Z.final_decision(t)
    assert d["n"] == 2 and d["mean"] == pytest.approx(-0.025) and d["mean_positive"] is False
    assert d["debug_third"]["n"] == 1


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Z2", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Z2 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Z.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Z.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_whale: int, n_noise: int, seed: int, sign: int = 1) -> C.Dataset:
    """n_whale coins with one lone whale print (8 % of X) at a spread-out minute, then 30 minutes of buying (sign +1,
    informed) or selling (sign -1, exit liquidity); n_noise background coins."""
    specs = {i: informed(10 + (i * 13) % 100, sign=sign) for i in range(n_whale)}
    ds = ds_of(frames_with(specs, n=n_whale + n_noise, seed=seed, t0=t0), split)
    # FINAL: slow coins (creation not scanned) whose upper-bound creation lies in the census window go to the
    # sealed TEST split (common.assign_split); every other split keeps every coin
    assert len(ds) == n_whale + n_noise if split != "final" else len(ds) >= 0.75 * (n_whale + n_noise)
    return ds


def test_exit_liquidity_market_reads_exit_liquidity(st):
    doc = _run("train", st, market("train", T0, 40, 12, 1, sign=-1))
    assert doc["decision"]["verdict"] == "NO_CONFIG"
    assert doc["decision"]["primary_direction"]["direction"] == "EXIT_LIQUIDITY"
    assert doc["overall"].startswith("NO EDGE")
    assert not (st.sl / "Z2.json").exists()
    with pytest.raises(Z.Z2Refused, match="NO_CONFIG"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 36, 4, 1)
    with pytest.raises(Z.Z2Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert (st.out / "prereg.lock").exists() and not (st.sl / "Z2.json").exists()   # any TRAIN run locks
    with pytest.raises(Z.Z2Refused, match="no TRAIN result"):
        _check("val", st)
    # review Z-ALL-1: the provisional run showed TRAIN returns, so PREREG.md is frozen from it on
    (st.out / "PREREG.md").write_text("# edited after the provisional run\n")
    with pytest.raises(Z.Z2Refused, match="changed"):
        _check("train", st)
    with pytest.raises(Z.Z2Refused, match="changed"):
        _run("train", st, ds, _skip_coverage=False, allow_partial=True)


def test_prelim_without_lock_still_freezes_prereg(st):
    """review Z-ALL-1: a train_prelim.json with no prereg.lock (written before the lock rule) pins its PREREG sha."""
    (st.out / "train_prelim.json").write_text(json.dumps({"stage": "train", "provisional": True,
                                                           "prereg_sha256": "0" * 64}))
    with pytest.raises(Z.Z2Refused, match="changed"):
        _check("train", st)
    (st.out / "train_prelim.json").write_text(json.dumps({"stage": "train", "provisional": True,
                                                           "prereg_sha256": Z._sha(st.out / "PREREG.md")}))
    assert _check("train", st)["prereg_locked"] is True


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:
        monkeypatch.setenv(k, "1")
    with pytest.raises(Z.Z2Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: 8 configs, informed whales -> shortlist of the top 2
    tr = _run("train", st, market("train", T0, 40, 12, 1))
    assert set(tr["configs"]) == {Z.config_key(p) for p in Z.GRID}
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert len(tr["decision"]["shortlist_keys"]) == 2
    assert tr["decision"]["primary_direction"]["direction"] == "INFORMED"
    assert all(e["censored_share"] == 0 for e in tr["configs"].values())
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z2") == 8
    assert led["n_trials_total"] == 2575 + 8
    with pytest.raises(Z.Z2Refused, match="final"):
        _run("train", st, market("train", T0, 40, 12, 1))
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Z.Z2Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Z2 test prereg\n")
    with pytest.raises(Z.Z2Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    for stage in ("confirm", "final"):
        with pytest.raises(Z.Z2Refused, match="before TEST"):
            _check(stage, st, env=env_all)
    sl = (st.sl / "Z2.json").read_text()
    (st.sl / "Z2.json").unlink()
    with pytest.raises(Z.Z2Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Z2.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 10, 2))
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"sl1", "sl2"}
    assert va["decision"]["candidate_hash"] in json.loads(sl)["hashes"]
    with pytest.raises(Z.Z2Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 30, 10, 3)
    with pytest.raises(Z.Z2Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert set(te["configs"]) == {"candidate", "twin"}
    assert te["configs"]["candidate"]["params_hash"] == va["decision"]["candidate_hash"]
    with pytest.raises(Z.Z2Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Z.Z2Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z2") == 8     # no new trials after TRAIN
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 20, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(Z.Z2Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 10, 6, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(Z.Z2Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Z.Z2Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Z.Z2Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 36, 12, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Z.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden") and e["n"] == 36
        for k in ("mean", "ci90", "placebo", "placebo_unmatched", "reasons", "stress", "portfolio", "by_stratum",
                  "direction"):
            assert k not in e
    ec = doc["event_counts"]
    assert ec["per_q"]["q0.03"]["coins_with_whale_bar"] == 36 and ec["per_q"]["q0.06"]["coins_with_whale_bar"] == 36
    assert all(r["debug"] and r["mean"] is None for r in json.loads(st.ledger.read_text())["runs"])
    assert "mean" not in (st.out / "debug.md").read_text().lower().replace("mean_", "")

"""Tests for research/lab2/x4.py: the floor distance fm, the AT_FLOOR / revival features on hand-built minute bars
(exact window sums, every condition, AGENT removal, no floor without a virtual reserve), the entry and exit rules
(worst fills, next-bar take-profit / stop, holds, deadline), the floor-matched placebo, the pre-registered grid,
no lookahead (synthetic and real census bars), the separation gate, the decision rules and the stage refusals."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import x4 as X
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
R = 45                       # default revival start (minute)


# =========================================================================== fixtures


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def path_bars(g: int, mint_: str, pool: str, buy, sell, n_buyers, n_sellers, agent=None, xr_override=None,
              floor_breaks: bool = False):
    """Hand-built minute bars: every SOL goes into the pricing reserve (X += buy - sell), y = k / X, real SOL
    x = X - v with v = V0 (``xr_override`` = {minute: x_close}). A minute without trades has no row (as in B2).
    ``floor_breaks`` lets X fall below v (a virtual-reserve change: x_close goes negative)."""
    m0 = int(g) // 60 * 60
    Xc, y = X0, Y0
    k = Xc * y
    rows = []
    for j in range(N_MIN):
        b, s = float(buy[j]), float(sell[j])
        if b <= 0 and s <= 0:
            continue
        X1 = Xc + b - s
        assert X1 > (0.0 if floor_breaks else V0), f"minute {j}: the path went below the floor"
        y1 = k / X1
        bt, st = (y - y1, 0.0) if y1 < y else (0.0, y1 - y)
        p0, p1 = Xc / y, X1 / y1
        xc = X1 - V0 if not xr_override or j not in xr_override else xr_override[j]
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": max(int(n_buyers[j]), 1) if b > 0 else 0,
                     "n_sells": max(int(n_sellers[j]), 1) if s > 0 else 0, "n_dust": 0, "buy_sol": b, "sell_sol": s,
                     "buy_tok": bt, "sell_tok": st, "n_buyers": int(n_buyers[j]), "n_sellers": int(n_sellers[j]),
                     "top5_buy_sol": b, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": xc, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0 if agent is None else float(agent[j]), "price_repaired": 0})
        Xc, y = X1, y1
    return pd.DataFrame(rows)


def floor_spec(revive_at=R, rev_len=12, rev_buy=0.15, rev_sell=0.02, rev_buyers=2, moon=True, moon_buy=4.0,
               moon_len=10, die=False, whale_at=None, churn=False, dump_to=0.5, agent=None) -> dict:
    """Buys for 5 minutes, a 10-minute dump to x_real = ``dump_to`` SOL (fm ~ 1.06), then a dead floor (one 0.02 SOL
    buy and sell every 3rd minute). ``revive_at``: a dispersed revival (``rev_buyers`` wallets buying ``rev_buy`` SOL a
    minute for ``rev_len`` minutes); ``moon``: then ``moon_buy`` SOL a minute for ``moon_len`` minutes; ``die``: the
    revival's inflow is sold back over 4 minutes. ``whale_at``: one 2 SOL single-buyer minute. ``churn``: 2 buyers
    and 2 sellers trading 0.1 SOL every minute of the floor."""
    buy, sell, nb, ns = (np.zeros(N_MIN) for _ in range(4))
    buy[0:5], nb[0:5] = 1.0, 3
    d = (X0 + 5.0 - (V0 + dump_to)) / 10.0
    sell[5:15], ns[5:15] = d, 5
    for j in range(15, N_MIN, 3):
        buy[j], sell[j], nb[j], ns[j] = 0.02, 0.02, 1, 1
    if churn:
        buy[15:], sell[15:], nb[15:], ns[15:] = 0.1, 0.1, 2, 2
    if revive_at is not None:
        r = slice(revive_at, revive_at + rev_len)
        buy[r], sell[r], nb[r], ns[r] = rev_buy, rev_sell, rev_buyers, 1
        e = revive_at + rev_len
        if moon:
            buy[e:e + moon_len], sell[e:e + moon_len], nb[e:e + moon_len], ns[e:e + moon_len] = moon_buy, 0.1, 6, 1
        if die:
            net = rev_len * (rev_buy - rev_sell)
            buy[e:e + 4], sell[e:e + 4], nb[e:e + 4], ns[e:e + 4] = 0.0, net / 4, 0, 3
    if whale_at is not None:
        buy[whale_at], sell[whale_at], nb[whale_at], ns[whale_at] = 2.0, 0.0, 1, 0
    return {"buy": buy, "sell": sell, "n_buyers": nb, "n_sellers": ns, "agent": agent}


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0):
    """make_frames (random-walk coins: X >= 20 SOL, so never AT_FLOOR) with coin i's bars replaced."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0)
    for i, spec in specs.items():
        r = g[g["mint"] == mint(i, seed)].iloc[0]
        b = pd.concat([b[b["mint"] != r["mint"]], path_bars(int(r["g_ts"]), r["mint"], r["pool"], **spec)],
                      ignore_index=True)
    return g, c, b


def ds_of(frames, split: str = "train", trades=None) -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, trades=trades, guard=False)


def snap_k(ds: C.Dataset, m: str, k: int) -> C.AsOf:
    """The decision on the grid at which exactly k bars have completed."""
    cd = ds.coin(m)
    return ds.asof(m, cd.bar_start(k) + C.GRID_OFFSET_S)


def x_after(spec: dict, k: int) -> float:
    """Pricing reserve after the first k minutes of a spec."""
    return X0 + float(spec["buy"][:k].sum() - spec["sell"][:k].sum())


P = {(s, e): X.make_params(s, e) for s in X.SIGNALS for e in X.EXIT_GRID}


# =========================================================================== floor distance and features


def test_fm_is_the_squared_reserve_ratio():
    spec = floor_spec(revive_at=None)
    ds = ds_of(frames_with({1: spec}))
    s = snap_k(ds, mint(1), 40)
    fm = X.fm_series(s.bars, 0, 40)
    for j in (0, 5, 14, 20, 39):
        Xj = float(s.bars.X[j])
        assert fm[j] == pytest.approx((Xj / V0) ** 2, rel=1e-9)
    assert fm[39] == pytest.approx(((V0 + 0.5) / V0) ** 2, rel=1e-9)       # dumped to x_real = 0.5
    # the floor price is v^2 / k: fm = price / floor price
    Xj, yj = float(s.bars.X[39]), float(s.bars.y[39])
    assert fm[39] == pytest.approx((Xj / yj) / (V0 ** 2 / (Xj * yj)), rel=1e-9)


def test_no_floor_without_a_virtual_reserve():
    spec = floor_spec(revive_at=None)
    ds = ds_of(frames_with({1: {**spec, "xr_override": {j: 1e9 for j in range(15, N_MIN)}}}))  # v = X - x < 0
    fs = X.floor_state(snap_k(ds, mint(1), 40))
    assert fs["ok"] and fs["fm_now"] is None and fs["fm_pre_med"] is None and not fs["at_floor"]
    neg = ds_of(frames_with({1: {**spec, "xr_override": {j: -1.0 for j in range(15, N_MIN)}}}))  # x < 0: impossible
    assert X.floor_state(snap_k(neg, mint(1), 40))["fm_now"] is None


def test_floor_state_exact_window_sums():
    spec = floor_spec()
    ds = ds_of(frames_with({1: spec}))
    k = R + 6                                   # window = minutes 41-50: 6 revival minutes + dead minutes 42, 45*
    fs = X.floor_state(snap_k(ds, mint(1), k))
    win = slice(k - 10, k)
    prev = slice(k - 20, k - 10)
    assert fs["ok"] and fs["k"] == k
    assert fs["BM"] == pytest.approx(spec["n_buyers"][win].sum())
    assert fs["BM_prev"] == pytest.approx(spec["n_buyers"][prev].sum())
    assert fs["peak"] == pytest.approx(spec["n_buyers"][win].max())
    assert fs["buy_w"] == pytest.approx(spec["buy"][win].sum())
    assert fs["NI"] == pytest.approx(spec["buy"][win].sum() - spec["sell"][win].sum())
    assert fs["top_min_share"] == pytest.approx(spec["buy"][win].max() / spec["buy"][win].sum())
    fm_pre = [(x_after(spec, j + 1) / V0) ** 2 for j in range(k - 30, k - 10)]
    assert fs["fm_pre_med"] == pytest.approx(float(np.median(fm_pre)), rel=1e-9)
    assert fs["fm_now"] == pytest.approx((x_after(spec, k) / V0) ** 2, rel=1e-9)
    assert fs["v"] == pytest.approx(V0, rel=1e-9) and fs["x_real"] == pytest.approx(x_after(spec, k) - V0)
    assert fs["dead_before"] and fs["cheap_now"] and fs["at_floor"] and fs["dispersed"]


def test_breadth_and_flow_fire_when_the_revival_builds():
    ds = ds_of(frames_with({1: floor_spec()}))
    first = {s: None for s in X.SIGNALS}
    for k in range(30, 80):
        fs = X.floor_state(snap_k(ds, mint(1), k))
        for s in X.SIGNALS:
            if fs["signals"][s] and first[s] is None:
                first[s] = k
    # BREADTH needs >= 12 buyer-minutes (6 revival minutes x 2 + dead buys), FLOW needs NI >= 1.0 (8 x 0.13 SOL)
    assert first["BREADTH"] == R + 6 and first["FLOW"] == R + 8 and first["BOTH"] == R + 8
    # the moon (minute R + 12 on) lifts fm above 1.5: nothing fires afterwards
    assert not any(X.floor_state(snap_k(ds, mint(1), k))["signals"]["FLOW"] for k in range(R + 14, 120))


def test_dead_floor_fires_nothing_but_is_at_floor():
    ds = ds_of(frames_with({1: floor_spec(revive_at=None)}))
    seen_floor = False
    for k in range(30, 170):
        fs = X.floor_state(snap_k(ds, mint(1), k))
        seen_floor |= fs["at_floor"]
        assert not any(fs["signals"].values())
    assert seen_floor


def test_noise_coins_are_never_at_the_floor():
    ds = ds_of(frames_with({}))                       # random walk with X >= 20 SOL: fm >= 1.29 > FM_FLOOR
    for m in ds.mints[:4]:
        for k in range(30, 170, 7):
            fs = X.floor_state(snap_k(ds, m, k))
            assert not fs["dead_before"] and not fs["at_floor"]


def test_whale_minute_is_not_a_dispersed_revival():
    """One 2 SOL single-buyer minute (Z2's territory) is excluded by the dispersion rule."""
    ds = ds_of(frames_with({1: floor_spec(revive_at=None, whale_at=50)}))
    for k in range(51, 61):
        fs = X.floor_state(snap_k(ds, mint(1), k))
        assert fs["NI"] >= 1.0 and not fs["dispersed"] and not fs["signals"]["FLOW"]


def test_steady_churn_is_not_a_breadth_revival():
    ds = ds_of(frames_with({1: floor_spec(revive_at=None, churn=True)}))
    for k in range(45, 120, 5):
        fs = X.floor_state(snap_k(ds, mint(1), k))
        assert fs["at_floor"] and fs["BM"] >= 12 and fs["peak"] >= 2
        assert not fs["signals"]["BREADTH"]               # no surge and no net inflow


def test_too_expensive_and_not_dead_before():
    # a big revival: fm passes 1.5 before FLOW's 10-minute inflow completes -> cheap_now fails
    ds = ds_of(frames_with({1: floor_spec(rev_buy=0.6, rev_sell=0.0, rev_buyers=3, moon=False)}))
    ks = [k for k in range(R + 1, R + 14) if X.floor_state(snap_k(ds, mint(1), k))["NI"] >= 1.0]
    assert ks and any(not X.floor_state(snap_k(ds, mint(1), k))["cheap_now"] for k in ks)
    # a revival right after the dump: the pre-window is not at the floor yet
    ds2 = ds_of(frames_with({1: floor_spec(revive_at=18)}))
    for k in range(24, 31):
        assert not X.floor_state(snap_k(ds2, mint(1), k))["dead_before"]


def test_flow_needs_three_buyer_minutes():
    spec = floor_spec(revive_at=None)
    for key in ("buy", "sell", "n_buyers", "n_sellers"):
        spec[key][45:55] = 0.0                           # a window with nothing but the two buys below
    spec["buy"][50], spec["n_buyers"][50] = 0.55, 1      # two single-buyer minutes of 0.55 SOL: NI >= 1, BM = 2
    spec["buy"][53], spec["n_buyers"][53] = 0.55, 1
    ds = ds_of(frames_with({1: spec}))
    fs = X.floor_state(snap_k(ds, mint(1), 55))
    assert fs["NI"] >= 1.0 and fs["dispersed"] and fs["BM"] < 3 and not fs["signals"]["FLOW"]


def test_agent_buys_are_removed_once_known():
    ag = np.zeros(N_MIN)
    ag[R:R + 12] = 0.05
    spec = floor_spec(agent=ag)
    ds = ds_of(frames_with({0: spec, 1: spec}))          # make_frames: coin 0 has a known AGENT, coin 1 none
    a = X.floor_state(snap_k(ds, mint(0), R + 8))
    b = X.floor_state(snap_k(ds, mint(1), R + 8))
    assert a["buy_w"] == pytest.approx(b["buy_w"] - 8 * 0.05)
    assert a["NI"] == pytest.approx(b["NI"] - 8 * 0.05)


def test_fast_path_agrees_with_full():
    ds = ds_of(frames_with({1: floor_spec(), 2: floor_spec(revive_at=None), 3: floor_spec(churn=True)}))
    for m in (mint(1), mint(2), mint(3), mint(4)):
        for k in range(28, 175, 3):
            s = snap_k(ds, m, k)
            a, b = X.floor_state(s), X.floor_state(s, full=False)
            assert a["at_floor"] == b["at_floor"] and a["signals"] == b["signals"]


# =========================================================================== entry, exits, placebo


def test_strategy_waits_for_age_skips_late_and_sets_exits():
    p = P[("BREADTH", "TP2X")]
    ds = ds_of(frames_with({1: floor_spec()}))
    act = X.strategy(snap_k(ds, mint(1), R + 6), p, None)
    assert isinstance(act, C.Enter) and act.tag == "instant"
    ex = act.exits
    assert ex.take_profit_pct == 1.0 and ex.max_hold_s == 3600 and ex.stop_pct == 0.60
    assert ex.exit_by_age_s == 178 * 60 and ex.trail_pct is None
    run = X.strategy(snap_k(ds, mint(1), R + 6), P[("BREADTH", "RUN")], None)
    assert run.exits.take_profit_pct is None and run.exits.max_hold_s == 5400
    assert X.strategy(snap_k(ds, mint(1), R + 6), P[("FLOW", "TP2X")], None) is None       # FLOW not yet
    assert X.strategy(snap_k(ds, mint(1), 152), p, None) is C.SKIP
    for k in range(20, 31):
        s = snap_k(ds, mint(1), k)
        if s.age_s < X.AGE_MIN_S:
            assert X.strategy(s, p, None) is None
    assert X.strategy(snap_k(ds, mint(1), R + 6), p, C.PositionView(
        mint=mint(1), t_dec=0, t_in=0, entry_price=1, tokens=1, sol_in=1, peak=1, bars_held=1, unrealized=0,
        exits=ex, state={}, is_placebo=False)) is None                                         # exits: mechanical only


def test_one_entry_worst_fill_and_take_profit_on_the_next_bar():
    ds = ds_of(frames_with({1: floor_spec()}))
    t = C.run_trades(ds, X.strategy, P[("BREADTH", "TP2X")], X.FILL, mints=[mint(1)])
    assert len(t) == 1
    r = t.iloc[0]
    cd = ds.coin(mint(1))
    j = cd.bar_of(r["t_in"])
    assert j == R + 6 and r["entry_price"] == pytest.approx(max(cd.arr["o"][j], cd.arr["h"][j]))
    assert r["reason"] == "take_profit"
    jt = next(i for i in range(j, C.N_BARS) if cd.arr["h"][i] >= 2 * r["entry_price"])
    assert cd.bar_of(r["t_out"]) == jt + 1                                       # triggered in jt, filled in jt + 1
    assert r["exit_price"] == pytest.approx(min(cd.arr["o"][jt + 1], cd.arr["l"][jt + 1]))


def test_run_holds_ninety_minutes_and_late_entries_meet_the_deadline():
    ds = ds_of(frames_with({1: floor_spec(), 2: floor_spec(revive_at=125, moon=False)}))
    r = C.run_trades(ds, X.strategy, P[("BREADTH", "RUN")], X.FILL, mints=[mint(1)]).iloc[0]
    assert r["reason"] == "time" and 5400 - 60 <= r["t_out"] - r["t_in"] <= 5400 + 120
    late = C.run_trades(ds, X.strategy, P[("BREADTH", "RUN")], X.FILL, mints=[mint(2)]).iloc[0]
    cd = ds.coin(mint(2))
    assert late["reason"] == "time" and late["t_out"] - cd.g <= 179 * 60 + 1
    assert late["t_out"] - late["t_in"] < 5400


def test_disaster_stop_fills_on_the_next_bar():
    """The -60 % stop fires only when the floor breaks (here the pricing reserve falls below v, as after a
    virtual-reserve change); it triggers in the crash bar and fills in the next one at its low."""
    spec = floor_spec(moon=False)
    e = C.run_trades(ds_of(frames_with({1: spec})), X.strategy, P[("BREADTH", "RUN")], X.FILL, mints=[mint(1)])
    j_in = ds_of(frames_with({1: spec})).coin(mint(1)).bar_of(e.iloc[0]["t_in"])
    jc = j_in + 3
    spec["sell"][jc] += x_after(spec, jc + 1) - 0.5 * V0           # X falls to v / 2: price ~ -80 %
    ds = ds_of(frames_with({1: {**spec, "floor_breaks": True}}))
    t = C.run_trades(ds, X.strategy, P[("BREADTH", "RUN")], X.FILL, mints=[mint(1)]).iloc[0]
    cd = ds.coin(mint(1))
    assert cd.bar_of(t["t_in"]) == j_in and cd.arr["l"][jc] <= 0.4 * t["entry_price"]
    assert t["reason"] == "stop" and cd.bar_of(t["t_out"]) == jc + 1
    assert t["exit_price"] == pytest.approx(min(cd.arr["o"][jc + 1], cd.arr["l"][jc + 1]))


def test_floor_bound_report():
    ds = ds_of(frames_with({1: floor_spec()}))
    t = C.run_trades(ds, X.strategy, P[("BREADTH", "TP2X")], X.FILL, mints=[mint(1)])
    fb = X.floor_bounds(ds, t)
    cd = ds.coin(mint(1))
    j = cd.bar_of(t.iloc[0]["t_in"])
    Xp, yp = float(cd.arr["X"][j - 1]), float(cd.arr["y"][j - 1])
    assert fb[0] == pytest.approx(1 - (V0 ** 2 / (Xp * yp)) / t.iloc[0]["entry_price"], rel=1e-9)
    assert 0 < fb[0] < 1 / 3


def test_placebo_draws_only_floor_coins():
    specs = {i: floor_spec() for i in range(4)}
    specs.update({i: floor_spec(revive_at=None) for i in range(4, 8)})
    ds = ds_of(frames_with(specs, n=12))
    res = C.backtest(X.strategy, "train", P[("BREADTH", "TP2X")], hypothesis="X4-test", ds=ds, cfg=X.FILL,
                     n_placebo=5, placebo_eligible=X.placebo_ok, placebo_controls=X.PLACEBO_CONTROLS, stress={},
                     ledger_path=None)
    pl = res.placebo
    assert len(res.trades) == 4 and len(pl) > 0
    for r in pl.itertuples(index=False):
        cd = ds.coin(r.mint)
        assert X.floor_state(ds.asof(r.mint, r.t_dec))["at_floor"]
        assert abs(r.age_dec_s - res.trades.iloc[int(r.signal)]["age_dec_s"]) <= C.PLACEBO_AGE_TOL_S
        assert r.take_profit_pct == 1.0 and r.max_hold_s == 3600 and cd is not None
    un = res.controls["unmatched"]
    assert len(un) and not all(X.floor_state(ds.asof(r.mint, r.t_dec))["at_floor"] for r in un.itertuples())


def test_grid_is_the_preregistered_grid():
    assert len(X.GRID) == 6 <= 12
    assert {X.config_key(p) for p in X.GRID} == {f"{s}|{e}" for s in X.SIGNALS for e in X.EXIT_GRID}
    assert len({C.params_hash(p) for p in X.GRID}) == 6
    for p in X.GRID:
        for k, v in X.FIXED.items():
            assert p[k] == v
        assert p["take_profit_pct"] == X.TP_PCT[p["exit"]] and p["max_hold_s"] == X.HOLD_S[p["exit"]]
    with pytest.raises(ValueError):
        X.make_params("WHALE", "TP2X")
    with pytest.raises(ValueError):
        X.make_params("FLOW", "TP3X")
    assert X.FILL.entry_fill == "worst" and X.FILL.exit_fill == "worst" and X.FILL.exit_delay_bars == 1
    assert all(c.exit_delay_bars == 1 for k, c in X.STRESS.items() if k != "same_bar_exits")
    assert X.STRESS["same_bar_exits"].exit_delay_bars == 0 and X.STRESS["size_10usd"].size_usd == 10.0
    assert [p["signal"] for p in X.train_configs(["FLOW"])] == ["FLOW", "FLOW"]
    assert X.train_configs([]) == []


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    fs = X.floor_state(s)
    flat = tuple(sorted((k, None if v is None else (round(v, 12) if isinstance(v, float) else v))
                        for k, v in fs.items() if k != "signals"))
    return flat + tuple(sorted(fs["signals"].items())) + tuple(
        isinstance(X.strategy(s, p, None), C.Enter) for p in X.GRID) + (X.stratum(s), X.placebo_ok(s))


def _floor_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(0, 12, 2):
        specs[i] = floor_spec(revive_at=int(rng.integers(40, 130)), rev_len=int(rng.integers(6, 15)),
                              rev_buy=float(rng.uniform(0.05, 0.3)), rev_buyers=int(rng.integers(1, 4)),
                              moon=bool(rng.random() < 0.5), die=bool(rng.random() < 0.3))
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _floor_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([1500, 1800, 2700, 3300, 4500, 6000, 7800, 9000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _floor_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(0, 12, 2):
        m = mint(i)
        cd = clean.coin(m)
        T = cd.g + 100 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        for p in X.GRID:
            a = C.run_trades(clean, X.strategy, p, X.FILL, mints=[m])
            b = C.run_trades(dirty, X.strategy, p, X.FILL, mints=[m])
            a_dec = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
            assert a_dec == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n_entries += len(a_dec)
    assert n_entries > 0


def test_separation_features_unchanged_by_future_garbage():
    """The gate's observation set and signal flags (not the label) use only data up to each decision's tau."""
    frames = _floor_frames(11)
    clean = ds_of(frames)
    rng = np.random.default_rng(3)
    m = mint(0)
    T = clean.coin(m).g + 80 * 60
    dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
    cols = ["age_min", "t", "fm_now", *X.SIGNALS, "none"]
    a = X.sep_obs(clean, [m], with_labels=False)
    b = X.sep_obs(dirty, [m], with_labels=False)
    a, b = a[a["t"] <= T][cols], b[b["t"] <= T][cols]
    assert len(a) > 0
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """X4 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
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
        for dt in (float(rng.uniform(1800, 3600)), float(rng.uniform(3600, 6000)), float(rng.uniform(6000, 9000))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


# =========================================================================== separation gate


def _obs(n_sig: int, coins_sig: int, rate_sig: float, n_none: int, rate_none: float, sig: str = "BREADTH",
         seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_sig):
        rows.append({"mint": f"S{i % coins_sig}", **{s: s == sig or (sig == "BOTH" and s != "none") for s in X.SIGNALS},
                     "none": False, "revive60": bool(rng.random() < rate_sig)})
    for i in range(n_none):
        rows.append({"mint": f"N{i % 40}", **{s: False for s in X.SIGNALS}, "none": True,
                     "revive60": bool(rng.random() < rate_none)})
    df = pd.DataFrame(rows)
    df["revive15"] = df["revive60"]
    df["max_ratio60"] = np.where(df["revive60"], 2.5, 1.0)
    return df


def test_sep_check_pass_kill_underpowered():
    d = X.sep_check(_obs(60, 30, 0.5, 400, 0.02), B=500)
    assert d["decision"] == "PASS" and d["passed"] == ["BREADTH"]
    ps = d["per_signal"]["BREADTH"]
    assert ps["powered"] and ps["passes"] and ps["diff_ci90"][0] > 0
    assert ps["diff"] == pytest.approx(ps["rate"] - d["rate_none"])
    # powered but no separation -> KILL
    assert X.sep_check(_obs(60, 30, 0.03, 400, 0.03), B=500)["decision"] == "KILL"
    # ratio bar: +5 points but less than 2x the base rate
    k = X.sep_check(_obs(200, 60, 0.30, 400, 0.22, seed=1), B=500)
    assert not k["per_signal"]["BREADTH"]["passes"]
    # too few observations or coins -> UNDERPOWERED (never KILL)
    assert X.sep_check(_obs(29, 20, 0.9, 400, 0.0), B=500)["decision"] == "UNDERPOWERED"
    assert X.sep_check(_obs(60, 14, 0.9, 400, 0.0), B=500)["decision"] == "UNDERPOWERED"
    # no no-signal observations: no base rate, cannot pass
    assert X.sep_check(_obs(60, 30, 0.9, 0, 0.0), B=500)["decision"] == "KILL"


def test_sep_check_hide_returns_counts_only():
    d = X.sep_check(_obs(60, 30, 0.5, 400, 0.02), hide=True)
    assert d["decision"].startswith("HIDDEN") and d["per_signal"]["BREADTH"] == {"n": 60, "coins": 30}
    assert "rate_none" not in d and "rate" not in d["per_signal"]["BREADTH"]


def test_boot_diff_resamples_coins():
    df = _obs(60, 30, 0.5, 400, 0.02)
    ci = X._boot_diff(df, "BREADTH", 500)
    point = df.loc[df["BREADTH"], "revive60"].mean() - df.loc[df["none"], "revive60"].mean()
    assert ci[0] < point < ci[1]
    assert X._boot_diff(df.iloc[:1], "BREADTH", 100) is None


def test_sep_obs_labels_on_synthetic_floor():
    specs = {0: floor_spec(), 1: floor_spec(moon=False, die=True), 2: floor_spec(revive_at=None)}
    ds = ds_of(frames_with(specs, n=6))
    obs = X.sep_obs(ds)
    assert set(obs["mint"]) <= {mint(0), mint(1), mint(2)}               # noise coins are never at the floor
    moon = obs[(obs["mint"] == mint(0)) & obs["BREADTH"]]
    died = obs[(obs["mint"] == mint(1)) & obs["BREADTH"]]
    dead = obs[obs["mint"] == mint(2)]
    assert len(moon) >= 1 and moon["revive60"].all()
    assert len(died) >= 1 and not died["revive60"].any()
    assert len(dead) >= 10 and dead["none"].all() and not dead["revive60"].any()
    r = moon.iloc[0]
    later = ds.asof(mint(0), r["t"] + 3600)
    snap = ds.asof(mint(0), r["t"])
    assert r["max_ratio60"] == pytest.approx(float(later.bars.c[snap.k:snap.k + 60].max()) / snap.price)
    assert obs["age_min"].max() <= 115


# =========================================================================== decision rules


def _ev(n=80, coins=80, mean=0.05, mw2=0.04, ci_lo=0.01, pc=0.03, cs=0.0, cfg="BREADTH|TP2X"):
    return {"config": cfg, "params_hash": "h" + cfg, "n": n, "n_coins": coins, "mean": mean, "mean_without_top2": mw2,
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.1), "censored_share": cs,
            "placebo": {"mean_diff": pc}}


def test_decide_train_qualifiers_and_rank_order():
    keys = [X.config_key(p) for p in X.GRID]
    evals = {k: _ev(cfg=k, ci_lo=-0.05) for k in keys}
    evals["FLOW|RUN"] = _ev(cfg="FLOW|RUN", ci_lo=0.02)
    evals["BOTH|TP2X"] = _ev(cfg="BOTH|TP2X", ci_lo=0.03)
    evals["FLOW|TP2X"] = _ev(cfg="FLOW|TP2X", ci_lo=0.03)              # tie with BOTH|TP2X: signal order decides
    d = X.decide_train(evals)
    assert d["verdict"] == "SHORTLISTED" and d["ranked"] == ["FLOW|TP2X", "BOTH|TP2X"]
    assert [X.config_key(p) for p in d["shortlist"]] == d["ranked"]
    for bad in ({"pc": 0.0}, {"mw2": -0.01}, {"mean": -0.01}, {"cs": 0.2}, {"n": 39}, {"coins": 39}):
        assert X.decide_train({k: _ev(cfg=k, **bad) for k in keys})["verdict"] in ("NO_CONFIG", "UNDERPOWERED_TRAIN")
    assert X.decide_train({k: _ev(cfg=k, mean=-0.01) for k in keys})["verdict"] == "NO_CONFIG"
    assert X.decide_train({k: _ev(cfg=k, n=20, coins=20) for k in keys})["verdict"] == "UNDERPOWERED_TRAIN"
    only_flow = {k: _ev(cfg=k) for k in keys if k.startswith("FLOW")}   # the gate passed FLOW only
    assert X.decide_train(only_flow)["ranked"] == ["FLOW|TP2X", "FLOW|RUN"]


def test_decide_val_is_a_filter_not_a_ranking():
    good, bad, few = _ev(n=20, mean=0.01), _ev(n=20, mean=0.30, mw2=-0.01), _ev(n=4)
    d = X.decide_val({"rank1": good, "rank2": _ev(n=20, mean=0.5)}, ["rank1", "rank2"])
    assert d["verdict"] == "SELECTED" and d["candidate_role"] == "rank1"
    d = X.decide_val({"rank1": bad, "rank2": _ev(n=8)}, ["rank1", "rank2"])
    assert d["verdict"] == "SELECTED_UNDERPOWERED" and d["candidate_role"] == "rank2"
    assert X.decide_val({"rank1": bad, "rank2": few}, ["rank1", "rank2"])["verdict"] == "FAIL_VAL"
    assert X.decide_val({"rank1": few}, ["rank1"])["verdict"] == "UNDERPOWERED_VAL"


def test_combine_verdict_and_confirm_rule():
    def base(**over):
        crit = [{"id": i, "pass": True} for i in range(1, 11)]
        for i, v in over.items():
            crit[int(i[1:]) - 1]["pass"] = v
        return {"criteria": crit, "auto_rejections": []}
    assert X.combine_verdict(base(c9=None)) == "PASS"
    assert X.combine_verdict(base(c1=False, c2=False)) == "UNDERPOWERED"
    assert X.combine_verdict(base(c5=False)) == "FAIL"
    assert X.combine_verdict(base(c7=None)) == "INCOMPLETE"
    assert X.combine_verdict(base(c10=False)) == "INCOMPLETE"
    assert X.combine_verdict({**base(), "auto_rejections": ["x"]}) == "REJECTED"
    doc = {"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": -0.02}}}
    assert not X.confirm_allowed(doc)[0]
    doc["configs"]["candidate"] = {"n": 3, "mean": -0.02}
    assert X.confirm_allowed(doc)[0]
    assert not X.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 3}}})[0]


def test_final_decision_judges_val_and_test_thirds_only():
    t = pd.DataFrame({"split": ["final_train"] * 3 + ["final_val", "final_test"], "ret_net": [5.0, 5, 5, -0.1, 0.05]})
    d = X.final_decision(t)
    assert d["n"] == 2 and d["mean"] == pytest.approx(-0.025) and d["mean_positive"] is False
    assert d["debug_third"]["n"] == 3


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "X4", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# X4 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return X.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return X.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_rev: int, n_dead: int, n_noise: int, seed: int, moon: bool = True) -> C.Dataset:
    """n_rev coins dumped to the floor that revive at minute 45 (``moon``: then 10 minutes of 4 SOL buys; else the
    revival dies back to the floor), n_dead coins that stay dead at the floor, and random-walk noise coins."""
    specs = {i: floor_spec(moon=moon, die=not moon) for i in range(n_rev)}
    specs.update({i: floor_spec(revive_at=None) for i in range(n_rev, n_rev + n_dead)})
    ds = ds_of(frames_with(specs, n=n_rev + n_dead + n_noise, seed=seed, t0=t0), split)
    assert len(ds) >= n_rev + n_dead - (n_rev + n_dead + n_noise) // 5   # FINAL: slow coins of a non-census day
    return ds                                                            # are sealed in TEST (common.assign_split)


def test_train_killed_by_the_separation_gate(st):
    doc = _run("train", st, market("train", T0, 45, 20, 4, 1, moon=False))
    assert doc["decision"]["verdict"] == "KILLED_SEP" and doc["separation"]["decision"] == "KILL"
    assert "configs" not in doc and doc["overall"].startswith("KILLED")
    led = json.loads(st.ledger.read_text())
    assert [v["hypothesis"] for v in led["configs"].values()] == ["X4-sep"]      # the grid never ran: 1 trial
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(X.X4Refused, match="dead"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(X.X4Refused, match="final"):
        _run("train", st, market("train", T0, 45, 20, 4, 1, moon=False))


def test_train_underpowered_gate(st):
    doc = _run("train", st, market("train", T0, 10, 10, 4, 1))
    assert doc["decision"]["verdict"] == "UNDERPOWERED_SEP" and doc["overall"].startswith("UNDERPOWERED")
    with pytest.raises(X.X4Refused, match="UNDERPOWERED_SEP"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 45, 20, 4, 1)
    with pytest.raises(X.X4Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "X4.json").exists()
    with pytest.raises(X.X4Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; x4's ``env=`` drives x4's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(X.X4Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: the gate passes, the grid of the passing signals runs, the shortlist (top 2 in rank order)
    tr = _run("train", st, market("train", T0, 45, 20, 4, 1))
    sep = tr["separation"]
    assert sep["decision"] == "PASS" and set(sep["passed"]) == set(X.SIGNALS)
    assert set(tr["configs"]) == {X.config_key(p) for p in X.GRID}
    for e in tr["configs"].values():
        assert e["n"] >= 40 and set(e["controls"]) == {"unmatched"} and e["censored_share"] == 0.0
        assert e["floor_bound"]["p50"] < 1 / 3 and e["decision_fm"]["p90"] <= X.FM_MAX
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert len(tr["decision"]["ranked"]) == 2
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sorted(v["hypothesis"] for v in led["configs"].values()) == ["X4"] * 6 + ["X4-sep"]
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(X.X4Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# X4 test prereg\n")
    for stage in ("test", "confirm", "final"):
        with pytest.raises(X.X4Refused, match="no VAL result"):
            _check(stage, st, env=env_all)
    sl = (st.sl / "X4.json").read_text()
    (st.sl / "X4.json").unlink()
    with pytest.raises(X.X4Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "X4.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 2, 2))
    assert set(va["configs"]) == {"rank1", "rank2"}
    assert va["decision"]["verdict"] == "SELECTED" and va["decision"]["candidate_role"] == "rank1"
    with pytest.raises(X.X4Refused, match="VAL already ran"):
        _check("val", st)
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 7      # VAL adds no trial
    with pytest.raises(X.X4Refused, match="before TEST"):
        _check("final", st, env=env_all)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 25, 8, 2, 3)
    with pytest.raises(X.X4Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert set(te["configs"]) == {"candidate"} and te["verdict"]["verdict"] == "UNDERPOWERED"
    with pytest.raises(X.X4Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(X.X4Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 15, 2, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 10, 4, 2, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True and fi["overall"] == "EDGE"
    with pytest.raises(X.X4Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 7      # the whole life of X4: 7 trials


def test_val_failure_stops_x4(st):
    _run("train", st, market("train", T0, 45, 20, 4, 1))
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 2, 2, moon=False))
    assert va["decision"]["verdict"] == "FAIL_VAL" and va["overall"].startswith("NO EDGE")
    with pytest.raises(X.X4Refused, match="FAIL_VAL"):
        _check("test", st, env={"LAB2_ALLOW_TEST": "1"})


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(X.X4Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(X.X4Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 20, 8, 4, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = X.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    assert doc["separation"]["decision"].startswith("HIDDEN") and "rate_none" not in doc["separation"]
    assert set(doc["configs"]) == {X.config_key(p) for p in X.GRID}
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden")
        for k in ("mean", "ci90", "placebo", "controls", "stress", "portfolio", "reasons", "by_stratum",
                  "floor_bound", "tp_hit_rate"):
            assert k not in e
    ec = doc["event_counts"]
    assert ec["coins_with_condition"]["BREADTH"] == 20 and ec["coins_with_condition"]["at_floor"] >= 28
    assert ec["v_sol_at_60min"]["p50"] == pytest.approx(V0, rel=1e-6)
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    md = (st.out / "debug.md").read_text().lower()
    assert "mean" not in md.split("## configs")[1].split("## decision")[0]

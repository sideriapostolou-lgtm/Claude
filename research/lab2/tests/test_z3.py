"""Tests for research/lab2/z3.py: the crash and single-seller features on hand-built minute bars (exact drop, ref,
pigeonhole bound, close-not-low, boundaries), the two entry modes, the post-crash state of the control, fills (worst
entry, floor-level fee tier, next-bar time / stop exits, the deadline), the pre-registered grid, no lookahead
(synthetic and real census bars), the decision rules, the predictions and the stage refusals."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import z3 as Z
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186


# =========================================================================== fixtures


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def coin_bars(g: int, mint_: str, pool: str, buy, sell, n_sellers=None, n_buyers=None) -> pd.DataFrame:
    """Hand-built minute bars: every SOL goes into the pricing reserve (X += buy - sell), y = k / X, so the close is
    X^2 / k and a minute's drop is 1 - (X_after / X_before)^2. A minute with no buy and no sell has no row (as in B2)."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    k = X * y
    rows = []
    for j in range(N_MIN):
        b, s = float(buy[j]), float(sell[j])
        if b <= 0 and s <= 0:
            continue
        X1 = X + b - s
        assert X1 > 0
        y1 = k / X1
        bt, st = (y - y1, 0.0) if y1 < y else (0.0, y1 - y)
        p0, p1 = X / y, X1 / y1
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 4 if b > 0 else 0, "n_sells": 3 if s > 0 else 0, "n_dust": 0,
                     "buy_sol": b, "sell_sol": s, "buy_tok": bt, "sell_tok": st,
                     "n_buyers": int(n_buyers[j]) if n_buyers is not None else int(b > 0) * 2,
                     "n_sellers": int(n_sellers[j]) if n_sellers is not None else int(s > 0) * 2,
                     "top5_buy_sol": b, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": X1 - V0, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0, "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def full(v, n=N_MIN):
    return np.full(n, float(v))


def path(crash_at: int | None = 20, crash_sell: float = 45.0, crash_sellers: int = 1, base=(0.5, 0.5, 2),
         after=None, from_=None) -> dict:
    """Bars spec: ``base`` (buy, sell, sellers) every minute; the crash minute sells ``crash_sell`` SOL by
    ``crash_sellers`` wallets; ``after`` = {minute: (buy, sell, sellers)} overrides; ``from_`` = (minute, (buy, sell,
    sellers)) sets every minute from ``minute`` on (before ``after``)."""
    buy, sell, ns = full(base[0]), full(base[1]), full(base[2])
    if from_ is not None:
        m, (b, s, n) = from_
        buy[m:], sell[m:], ns[m:] = b, s, n
    if crash_at is not None:
        buy[crash_at], sell[crash_at], ns[crash_at] = 0.0, crash_sell, crash_sellers
    for j, (b, s, n) in (after or {}).items():
        buy[j], sell[j], ns[j] = b, s, n
    return {"buy": buy, "sell": sell, "n_sellers": ns}


def bounce(crash_at: int = 20, **kw) -> dict:
    """Crash at ``crash_at`` (X 85 -> 40, -78 %), then 20 minutes of net buying (+1.3 SOL a minute), then flat."""
    return path(crash_at, after={j: (1.5, 0.2, 1) for j in range(crash_at + 1, crash_at + 21)}, **kw)


def second_rug(crash_at: int = 20, **kw) -> dict:
    """Crash at ``crash_at`` (X 85 -> 40), one green minute (+0.8 SOL), then a second single-wallet dump 4 minutes
    after the crash (X 40.8 -> 15.8, -85 %)."""
    return path(crash_at, after={crash_at + 1: (1.0, 0.2, 1), crash_at + 4: (0.0, 25.0, 1)}, **kw)


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0):
    """make_frames (random-walk noise coins) with coin i's bars replaced by coin_bars(**spec)."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0)
    for i, spec in specs.items():
        r = g[g["mint"] == mint(i, seed)].iloc[0]
        b = pd.concat([b[b["mint"] != r["mint"]], coin_bars(int(r["g_ts"]), r["mint"], r["pool"], **spec)],
                      ignore_index=True)
    return g, c, b


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def snap_k(ds: C.Dataset, m: str, k: int) -> C.AsOf:
    """The decision on the grid at which exactly k bars have completed."""
    cd = ds.coin(m)
    s = ds.asof(m, cd.bar_start(k) + C.GRID_OFFSET_S)
    assert s.k == k
    return s


def pv(snap: C.AsOf, **kw) -> C.PositionView:
    d = dict(mint=snap.mint, t_dec=snap.t, t_in=snap.t + 30, entry_price=1.0, tokens=1.0, sol_in=1.0, peak=1.0,
             bars_held=1, unrealized=0.0, exits=C.ExitSpec(), state={}, is_placebo=False)
    d.update(kw)
    return C.PositionView(**d)


# =========================================================================== crash features


def test_crash_exact_values_and_fires():
    ds = ds_of(frames_with({1: path(30, crash_sell=42.5)}))
    s = snap_k(ds, mint(1), 31)
    cr = Z.crash_at(s.bars, 30)
    assert cr["ok"] and cr["crash"] and cr["single"] and cr["fires"]
    assert cr["ref"] == pytest.approx(X0 / Y0, rel=1e-9)                # flat before: open = previous close
    assert cr["drop"] == pytest.approx(1 - ((X0 - 42.5) / X0) ** 2, rel=1e-9)
    assert cr["X_before"] == pytest.approx(X0, rel=1e-9)
    assert cr["big_sol"] == pytest.approx(42.5) and cr["n_sellers"] == 1
    for j in (2, 20, 29):                                                # flat minutes: no crash
        assert not Z.crash_at(s.bars, j)["crash"]
    assert Z.depth_tag(cr["drop"]) == "d70"                              # 1 - (42.49 / 84.99)^2 = 0.75
    assert Z.depth_tag(0.85) == "d80" and Z.depth_tag(0.95) == "d90" and Z.depth_tag(0.9) == "d90"


def test_drop_threshold_is_on_70_percent():
    s69 = 1 - np.sqrt(0.31)                                              # X falls to sqrt(0.31) X: drop 0.69
    s71 = 1 - np.sqrt(0.29)
    ds = ds_of(frames_with({1: path(30, crash_sell=s69 * X0), 2: path(30, crash_sell=s71 * X0)}))
    a = Z.crash_at(snap_k(ds, mint(1), 31).bars, 30)
    b = Z.crash_at(snap_k(ds, mint(2), 31).bars, 30)
    assert a["drop"] == pytest.approx(0.69, rel=1e-9) and not a["crash"] and not a["fires"]
    assert b["drop"] == pytest.approx(0.71, rel=1e-9) and b["crash"] and b["fires"]


def test_single_seller_pigeonhole_bound():
    """The same SOL spread over 4 wallets is a stampede (bound 10.6 < 0.25 X = 21.2), not a single-seller crash."""
    ds = ds_of(frames_with({1: path(30, crash_sell=42.5, crash_sellers=4), 2: path(30, crash_sell=42.5,
                                                                                    crash_sellers=2),
                            3: path(30, crash_sell=42.5, crash_sellers=0)}))
    four = Z.crash_at(snap_k(ds, mint(1), 31).bars, 30)
    assert four["crash"] and four["big_sol"] == pytest.approx(42.5 / 4) and not four["single"] and not four["fires"]
    two = Z.crash_at(snap_k(ds, mint(2), 31).bars, 30)                    # 21.25 >= 21.247: one wallet sold > 0.25 X
    assert two["big_sol"] == pytest.approx(21.25) and two["single"] and two["fires"]
    dust = Z.crash_at(snap_k(ds, mint(3), 31).bars, 30)                   # n_sellers 0 counts as 1 (never divides by 0)
    assert dust["big_sol"] == pytest.approx(42.5) and dust["fires"]


def test_crash_is_on_the_close_not_the_low():
    """A minute that wicked -80 % but closed flat (the bounce already happened inside it) is not an event."""
    g, c, b = frames_with({1: path(None)})
    m0 = int(g.loc[g["mint"] == mint(1), "g_ts"].iloc[0]) // 60 * 60
    sel = (b["mint"] == mint(1)) & (b["minute_ts"] == m0 + 60 * 30)
    b.loc[sel, "low"] = b.loc[sel, "open"] * 0.2
    s = snap_k(ds_of((g, c, b)), mint(1), 31)
    assert s.bars.l[30] == pytest.approx(0.2 * s.bars.o[30]) and not Z.crash_at(s.bars, 30)["crash"]


def test_reference_is_max_of_open_and_previous_close():
    g, c, b = frames_with({1: path(30, crash_sell=30.0)})                # drop 1 - (55 / 85)^2 = 0.58 from the open
    m0 = int(g.loc[g["mint"] == mint(1), "g_ts"].iloc[0]) // 60 * 60
    sel = (b["mint"] == mint(1)) & (b["minute_ts"] == m0 + 60 * 29)
    b.loc[sel, "close"] = b.loc[sel, "close"] * 2.0                       # previous close twice the crash bar's open
    b.loc[sel, "high"] = b.loc[sel, "close"]
    s = snap_k(ds_of((g, c, b)), mint(1), 31)
    cr = Z.crash_at(s.bars, 30)
    assert cr["ref"] == pytest.approx(float(s.bars.c[29])) and cr["drop"] == pytest.approx(1 - 0.42 / 2, abs=0.01)
    assert cr["crash"]


def test_out_of_range_bars_are_not_ok():
    ds = ds_of(frames_with({1: path(30)}))
    s = snap_k(ds, mint(1), 31)
    for j in (-1, 0, 1, 31, 40):                                         # bar 0 is partial; j >= k is not completed
        assert not Z.crash_at(s.bars, j)["ok"] and not Z.crash_at(s.bars, j)["fires"]
    assert Z.crash_arrays(s.bars, 0, 2) is None


# =========================================================================== entry modes and the strategy


def test_now_and_confirm_signals():
    ds = ds_of(frames_with({1: bounce(20), 2: path(20, after={21: (0.0, 2.0, 2)}), 3: path(20, after={21: (0.0, 0.0, 0)}),
                            4: path(20)}))
    s21 = snap_k(ds, mint(1), 21)
    assert Z.signal(s21, "now")[0] and not Z.signal(s21, "confirm")[0]
    s22 = snap_k(ds, mint(1), 22)
    ok, info = Z.signal(s22, "confirm")
    assert ok and info["green"] and info["j"] == 20 and not Z.signal(s22, "now")[0]
    assert not Z.signal(snap_k(ds, mint(1), 23), "confirm")[0]           # only right after the crash
    red = snap_k(ds, mint(2), 22)                                        # minute 21 fell further: not green
    assert not Z.signal(red, "confirm")[0] and Z.signal(red, "confirm")[1]["green"] is False
    quiet = snap_k(ds, mint(3), 22)                                      # minute 21 without trades: not green
    assert not Z.signal(quiet, "confirm")[0]
    flat = snap_k(ds, mint(4), 22)                                       # minute 21 traded flat (close = close): no
    assert not Z.signal(flat, "confirm")[0]
    with pytest.raises(ValueError):
        Z.signal(s21, "later")


def test_strategy_age_window_and_mechanical_exits():
    ds = ds_of(frames_with({1: bounce(20), 2: path(5)}))
    p = Z.make_params("now", 15)
    act = Z.strategy(snap_k(ds, mint(1), 21), p, None)
    assert isinstance(act, C.Enter) and act.tag == "d70"
    assert act.exits.stop_pct == 0.5 and act.exits.max_hold_s == 900 and act.exits.exit_by_age_s == 178 * 60
    assert act.state["j_crash"] == 20
    early = snap_k(ds, mint(2), 6)                                       # crash at minute 5: decision age < 7 min
    assert Z.signal(early, "now")[0] and early.age_s < Z.AGE_MIN_S and Z.strategy(early, p, None) is None
    assert Z.strategy(snap_k(ds, mint(1), 125), p, None) is C.SKIP
    assert Z.strategy(snap_k(ds, mint(1), 22), p, pv(snap_k(ds, mint(1), 22))) is None   # no signal exit
    t = C.run_trades(ds, Z.strategy, p, Z.FILL, mints=[mint(2)])
    assert len(t) == 0                                                   # the only crash came before g + 7 min


def test_entry_fill_floor_fee_tier_and_time_exits():
    ds = ds_of(frames_with({1: bounce(20)}))
    cd = ds.coin(mint(1))
    for hold in Z.HOLD_GRID_MIN:
        r = C.run_trades(ds, Z.strategy, Z.make_params("now", hold), Z.FILL, mints=[mint(1)]).iloc[0]
        assert r["t_dec"] == pytest.approx(cd.bar_start(21) + 20)
        j = cd.bar_of(r["t_in"])
        assert j == 21 and r["entry_price"] == pytest.approx(max(cd.arr["o"][j], cd.arr["h"][j]))
        # the floor-level top pool tier (< 420 SOL mcap) 125 bps + Ultra 10 + buffer 20, on both sides
        assert r["fee_bps_in"] == 155.0 and r["fee_bps_out"] == 155.0
        assert C.fee_bps_at(r["t_in"], r["mcap_in_sol"]) == 125.0
        assert r["reason"] == "time"
        jx = cd.bar_of(r["t_out"])
        assert jx == cd.bar_of(r["t_in"] + 60 * hold) + 2                # triggered the bar after, filled the next
        assert r["exit_price"] == pytest.approx(min(cd.arr["o"][jx], cd.arr["l"][jx]))
    rc = C.run_trades(ds, Z.strategy, Z.make_params("confirm", 5), Z.FILL, mints=[mint(1)]).iloc[0]
    assert rc["t_dec"] == pytest.approx(cd.bar_start(22) + 20) and cd.bar_of(rc["t_in"]) == 22


def test_stop_fills_on_the_next_bar_at_its_low():
    ds = ds_of(frames_with({1: second_rug(20)}))
    cd = ds.coin(mint(1))
    r = C.run_trades(ds, Z.strategy, Z.make_params("now", 60), Z.FILL, mints=[mint(1)]).iloc[0]
    assert r["reason"] == "stop" and cd.bar_of(r["t_out"]) == 25          # second rug in bar 24, filled in bar 25
    assert r["exit_price"] == pytest.approx(min(cd.arr["o"][25], cd.arr["l"][25]))
    assert r["ret_net"] < -0.6


def test_deadline_closes_before_the_data_horizon():
    ds = ds_of(frames_with({1: path(118)}))
    cd = ds.coin(mint(1))
    t = C.run_trades(ds, Z.strategy, Z.make_params("now", 60), Z.FILL, mints=[mint(1)])
    assert len(t) == 1
    r = t.iloc[0]
    assert r["age_dec_s"] <= Z.AGE_MAX_S and r["reason"] == "time"
    assert r["t_out"] <= cd.g + 179 * 60 + 60 and r["t_out"] - r["t_in"] < 3600


# =========================================================================== the control's post-crash state


def test_post_crash_state():
    bleed = path(None, from_=(2, (0.0, 1.5, 3)), after={j: (0.0, 0.0, 0) for j in range(32, N_MIN)})
    half = path(None, from_=(2, (0.0, 0.9, 3)), after={j: (0.0, 0.0, 0) for j in range(26, N_MIN)})
    ds = ds_of(frames_with({1: path(3), 2: bleed, 3: half}))
    s10 = Z.post_crash_state(snap_k(ds, mint(1), 10))
    assert s10["ok"] and s10["dd"] >= 0.7 and s10["recent_crash"] and not s10["state"]
    assert not Z.post_crash_state(snap_k(ds, mint(1), 18))["state"]       # bar 3 is still among the last 15
    s19 = Z.post_crash_state(snap_k(ds, mint(1), 19))
    assert s19["state"] and not s19["recent_crash"] and Z.placebo_ok(snap_k(ds, mint(1), 19))
    b = Z.post_crash_state(snap_k(ds, mint(2), 40))                      # a slow bleed to -78 %: no crash bar
    assert b["dd"] == pytest.approx(1 - ((X0 - 30 * 1.5) / X0) ** 2, rel=1e-6) and b["state"]
    h = Z.post_crash_state(snap_k(ds, mint(3), 40))                      # -46 %: not deep enough
    assert h["dd"] < 0.7 and not h["state"]
    assert not Z.post_crash_state(snap_k(ds, mint(1), 2))["ok"]


# =========================================================================== the grid


def test_grid_is_the_preregistered_grid():
    assert len(Z.GRID) == 6 <= 12
    assert {Z.config_key(p) for p in Z.GRID} == {f"{e}|t{h}" for e in ("now", "confirm") for h in (5, 15, 60)}
    assert len({C.params_hash(p) for p in Z.GRID}) == 6
    for p in Z.GRID:
        for k, v in Z.FIXED.items():
            assert p[k] == v
        assert p["max_hold_s"] == 60.0 * p["hold_min"]
    for bad in (("now", 10), ("later", 5), ("now", 5.5), ("now", "5")):
        with pytest.raises(ValueError):
            Z.make_params(*bad)
    assert Z.FILL.entry_fill == "worst" and Z.FILL.exit_fill == "worst" and Z.FILL.exit_delay_bars == 1
    assert set(Z.STRESS) == {"costs_x1.5", "rent_0.22", "same_bar_exits", "open_fills"}
    assert all(f.exit_delay_bars == 1 for k, f in Z.STRESS.items() if k != "same_bar_exits")
    assert Z.STRESS["open_fills"].entry_fill == "open" and Z.STRESS["costs_x1.5"].entry_fill == "worst"


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    out = [tuple(sorted(Z.crash_at(s.bars, s.k - d).items())) for d in (1, 2)]
    out += [Z.signal(s, e)[0] for e in Z.ENTRY_GRID]
    st = Z.post_crash_state(s)
    out.append(tuple(sorted((k, round(v, 12) if isinstance(v, float) else v) for k, v in st.items())))
    rt = Z.round_trip_frac(s)
    out.append(None if rt is None else round(rt, 12))
    out += [Z.strategy(s, p, None) is not None for p in Z.GRID]
    return tuple(out)


def _crash_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(0, 12, 2):
        ca = int(rng.integers(8, 110))
        sell = float(rng.uniform(35, 60))
        after = {ca + int(rng.integers(1, 30)): (0.0, float(rng.uniform(0, 20)), int(rng.integers(1, 4)))}
        if rng.random() < 0.5:
            after.update({j: (1.2, 0.2, 1) for j in range(ca + 1, ca + 8) if j not in after})
        specs[i] = path(ca, crash_sell=sell, crash_sellers=int(rng.integers(1, 3)), after=after)
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _crash_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(14):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([300, 600, 1200, 1800, 3000, 4500, 6000, 7200, 9000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _crash_frames(7)
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
    """Z3 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
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
        for dt in (float(rng.uniform(420, 1800)), float(rng.uniform(1800, 4500)), float(rng.uniform(4500, 7300))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


# =========================================================================== decision rules and predictions


def _ev(n=80, coins=80, mean=0.05, mw2=0.04, ci_lo=0.01, pc=0.03, pu=0.02, cs=0.0, cfg="now|t5", opn=None,
        pc_ci=None):
    return {"config": cfg, "params_hash": "h" + cfg, "n": n, "n_coins": coins, "mean": mean, "mean_without_top2": mw2,
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.1), "censored_share": cs,
            "placebo": {"mean_diff": pc, "diff_ci95": pc_ci}, "controls": {"unmatched": {"mean_diff": pu}},
            "stress": {"open_fills": opn}}


def test_decide_train_qualifiers_and_rank_order():
    keys = [Z.config_key(p) for p in Z.GRID]
    evals = {k: _ev(cfg=k, ci_lo=-0.05) for k in keys}
    evals["confirm|t5"] = _ev(cfg="confirm|t5", ci_lo=0.03)
    evals["now|t60"] = _ev(cfg="now|t60", ci_lo=0.03)
    evals["now|t15"] = _ev(cfg="now|t15", ci_lo=0.02, mean=0.30)
    d = Z.decide_train(evals)                       # CI tie: same mean -> shorter hold first
    assert d["verdict"] == "SHORTLISTED" and d["ranked"] == ["confirm|t5", "now|t60"]
    assert [Z.config_key(p) for p in d["shortlist"]] == d["ranked"]
    evals["now|t5"] = _ev(cfg="now|t5", ci_lo=0.03)
    assert Z.decide_train(evals)["ranked"] == ["now|t5", "confirm|t5"]           # then now before confirm
    for bad in ({"pc": 0.0}, {"pu": -0.01}, {"mw2": -0.01}, {"mean": -0.01}, {"cs": 0.2}, {"n": 59}, {"coins": 39},
                {"pc": None}):
        e = {k: _ev(cfg=k, **bad) for k in keys}
        assert Z.decide_train(e)["verdict"] in ("NO_CONFIG", "UNDERPOWERED_TRAIN")
    assert Z.decide_train({k: _ev(cfg=k, mean=-0.01) for k in keys})["verdict"] == "NO_CONFIG"
    assert Z.decide_train({k: _ev(cfg=k, n=30, coins=30) for k in keys})["verdict"] == "UNDERPOWERED_TRAIN"


def test_score_predictions():
    keys = [Z.config_key(p) for p in Z.GRID]
    neg = {k: _ev(cfg=k, mean=-0.08, opn=-0.02, pc=-0.03, pc_ci=(-0.2, -0.12)) for k in keys}
    s = Z.score_predictions(neg)
    assert all(s[p]["held"] for p in ("P1_no_config_mean_net_above_0", "P2_open_fills_below_plan_bar",
                                      "P3_control_margin_below_6pts"))
    assert s["g35_support_configs"] == sorted(keys)
    pos = dict(neg, **{"now|t5": _ev(cfg="now|t5", mean=0.01, opn=0.04, pc=0.07, pc_ci=(0.01, 0.2))})
    s = Z.score_predictions(pos)
    assert not any(s[p]["held"] for p in ("P1_no_config_mean_net_above_0", "P2_open_fills_below_plan_bar",
                                          "P3_control_margin_below_6pts"))
    assert "now|t5" not in s["g35_support_configs"]


def test_decide_val_is_a_filter_not_a_ranking():
    good, bad, few = _ev(n=20, mean=0.01), _ev(n=20, mean=0.30, mw2=-0.01), _ev(n=4)
    d = Z.decide_val({"rank1": good, "rank2": _ev(n=20, mean=0.5)}, ["rank1", "rank2"])
    assert d["verdict"] == "SELECTED" and d["candidate_role"] == "rank1"
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
    d = SimpleNamespace(out=tmp_path / "Z3", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Z3 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Z.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Z.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_sig: int, n_ctl: int, n_noise: int, seed: int, dump: bool = False) -> C.Dataset:
    """n_sig coins crashed by one wallet at minute 20 (then a 20-minute bounce, or ``dump``: a second rug 3 minutes
    later), n_ctl coins crashed at minute 3 and flat after (the drawdown-matched control's pool: post-crash state from
    minute 19, never a signal), and random-walk noise coins."""
    specs = {i: (second_rug(20) if dump else bounce(20)) for i in range(n_sig)}
    specs.update({i: path(3, base=(0.3, 0.3, 2)) for i in range(n_sig, n_sig + n_ctl)})
    ds = ds_of(frames_with(specs, n=n_sig + n_ctl + n_noise, seed=seed, t0=t0), split)
    assert len(ds) >= n_sig
    return ds


def test_train_no_config_stops_z3(st):
    ds = market("train", T0, 70, 16, 4, 1, dump=True)
    doc = _run("train", st, ds)
    assert doc["decision"]["verdict"] == "NO_CONFIG" and not doc["decision"]["shortlist_written"]
    assert doc["overall"].startswith("NO EDGE")
    assert set(doc["configs"]) == {Z.config_key(p) for p in Z.GRID}
    pr = doc["predictions"]
    assert pr["P1_no_config_mean_net_above_0"]["held"] and pr["P3_control_margin_below_6pts"]["held"]
    for e in doc["configs"].values():
        assert e["n"] >= 60 and e["mean"] < 0 and e["n_placebo"] > 0 and e["censored_share"] == 0.0
        assert set(e["cost_decomposition"]["side_bps_in"]) == {"155.0"}
    assert not (st.sl / "Z3.json").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z3") == 6
    assert led["n_trials_total"] == 2575 + 6
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(Z.Z3Refused, match="NO_CONFIG"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(Z.Z3Refused, match="final"):
        _run("train", st, ds)                                          # a decision on complete TRAIN is final
    doc2 = _run("train", st, ds, rerun_reason="test: data correction")
    assert doc2["decision"]["verdict"] == "NO_CONFIG" and list(st.out.glob("train_prev_*.json"))
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6      # a re-run adds no trial
    assert "Pre-registered predictions" in (st.out / "train.md").read_text()


def test_underpowered_train(st):
    doc = _run("train", st, market("train", T0, 20, 6, 4, 1))
    assert doc["decision"]["verdict"] == "UNDERPOWERED_TRAIN"
    with pytest.raises(Z.Z3Refused, match="UNDERPOWERED_TRAIN"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 70, 16, 4, 1)
    with pytest.raises(Z.Z3Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert (st.out / "prereg.lock").exists() and not (st.sl / "Z3.json").exists()   # any TRAIN run locks
    with pytest.raises(Z.Z3Refused, match="no TRAIN result"):
        _check("val", st)
    # review Z-ALL-1: the provisional run showed TRAIN returns, so PREREG.md is frozen from it on
    (st.out / "PREREG.md").write_text("# edited after the provisional run\n")
    with pytest.raises(Z.Z3Refused, match="changed"):
        _check("train", st)
    with pytest.raises(Z.Z3Refused, match="changed"):
        _run("train", st, ds, _skip_coverage=False, allow_partial=True)


def test_prelim_without_lock_still_freezes_prereg(st):
    """review Z-ALL-1: a train_prelim.json with no prereg.lock (written before the lock rule) pins its PREREG sha."""
    (st.out / "train_prelim.json").write_text(json.dumps({"stage": "train", "provisional": True,
                                                           "prereg_sha256": "0" * 64}))
    with pytest.raises(Z.Z3Refused, match="changed"):
        _check("train", st)
    (st.out / "train_prelim.json").write_text(json.dumps({"stage": "train", "provisional": True,
                                                           "prereg_sha256": Z._sha(st.out / "PREREG.md")}))
    assert _check("train", st)["prereg_locked"] is True


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; z3's ``env=`` drives z3's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(Z.Z3Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: the grid, both controls, the shortlist (top 2 in rank order)
    tr = _run("train", st, market("train", T0, 70, 16, 4, 1))
    assert set(tr["configs"]) == {Z.config_key(p) for p in Z.GRID}
    for e in tr["configs"].values():
        assert e["n"] >= 60 and set(e["controls"]) == {"unmatched"} and e["placebo"]["n_placebo"] > 0
        assert e["censored_share"] == 0.0 and e["horizon_exits"] == 0 and e["mean"] > 0
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert len(tr["decision"]["ranked"]) == 2
    assert not tr["predictions"]["P1_no_config_mean_net_above_0"]["held"]
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z3") == 6
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Z.Z3Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Z3 test prereg\n")
    for stage in ("test", "confirm", "final"):
        with pytest.raises(Z.Z3Refused, match="no VAL result"):
            _check(stage, st, env=env_all)
    sl = (st.sl / "Z3.json").read_text()
    (st.sl / "Z3.json").unlink()
    with pytest.raises(Z.Z3Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Z3.json").write_text(sl)
    # ---- VAL: both shortlisted configs, the rank-1 candidate
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 2, 2))
    assert set(va["configs"]) == {"rank1", "rank2"}
    assert va["decision"]["verdict"] == "SELECTED" and va["decision"]["candidate_role"] == "rank1"
    assert va["decision"]["candidate_config"] == tr["decision"]["ranked"][0]
    with pytest.raises(Z.Z3Refused, match="VAL already ran"):
        _check("val", st)
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6      # VAL adds no trial
    with pytest.raises(Z.Z3Refused, match="before TEST"):
        _check("final", st, env=env_all)
    with pytest.raises(Z.Z3Refused, match="before TEST"):
        _check("confirm", st, env=env_all)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 30, 8, 2, 3)
    with pytest.raises(Z.Z3Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert set(te["configs"]) == {"candidate"}
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    with pytest.raises(Z.Z3Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Z.Z3Refused, match="one test run"):
        _check("test", st, env=env_all)                                   # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 18, 4, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(Z.Z3Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 12, 6, 2, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(Z.Z3Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 6      # the whole life of Z3: 6 trials


def test_val_failure_stops_z3(st):
    _run("train", st, market("train", T0, 70, 16, 4, 1))
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 2, 2, dump=True))
    assert va["decision"]["verdict"] == "FAIL_VAL" and va["overall"].startswith("NO EDGE")
    with pytest.raises(Z.Z3Refused, match="FAIL_VAL"):
        _check("test", st, env={"LAB2_ALLOW_TEST": "1"})


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Z.Z3Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Z.Z3Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 30, 10, 4, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Z.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden")
        for k in ("mean", "ci90", "placebo", "controls", "stress", "portfolio", "reasons", "by_depth",
                  "cost_decomposition"):
            assert k not in e
    ec = doc["event_counts"]
    assert ec["coins_with"]["single"] == 30 and ec["coins_with"]["crash_before_age_min"] == 10
    assert ec["bars_with"]["confirm"] == 30 and ec["coins_with"]["state"] >= 10
    assert ec["first_signal_decision_state"]["fee_bps_tier"] == {"125": 30}
    assert 0.03 < ec["first_signal_decision_state"]["round_trip"]["median"] < 0.06
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    md = (st.out / "debug.md").read_text().lower()
    assert "mean" not in md.split("## configs")[1].split("## decision")[0]

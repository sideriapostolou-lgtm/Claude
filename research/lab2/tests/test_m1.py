"""Tests for research/lab2/m1.py: MECH-bar features on hand-built minute bars, the PLAN-verbatim MECH-wallet
detector on hand-built B1 trades, no lookahead (synthetic and real census bars), the model check (stop rule 5), the
pre-registered decision rules and the stage refusals."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import m1 as M
from conftest import V0, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
VALID = {"V1": {"pass": True}, "V2": {"chain_ok": 100, "transitions": 100}, "V3": {"both": 10, "coin_windows": 10},
         "V4": {"pass": True}}


# =========================================================================== fixtures


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def coin_bars(g: int, mint_: str, pool: str, buy, sell=None, n_buyers=None, n_sellers=None, agent=None,
              y_shift: dict | None = None) -> pd.DataFrame:
    """Hand-built minute bars. All SOL goes into the pricing reserve (X += buy - sell), y = k / X, so token
    conservation holds unless ``y_shift`` {minute: frac} withdraws liquidity (x and y fall by frac, outside trades).
    A minute with no buy and no sell has no row (as in B2)."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    k = X * y
    rows = []
    for j in range(N_MIN):
        b = float(buy[j])
        s = 0.0 if sell is None else float(sell[j])
        if b <= 0 and s <= 0:
            continue
        X1 = X + b - s
        y_tr = k / X1
        bt, st = (y - y_tr, 0.0) if y_tr < y else (0.0, y_tr - y)
        y1 = y_tr
        if y_shift and j in y_shift:
            X1 *= 1 - y_shift[j]
            y1 = y_tr * (1 - y_shift[j])
            k = X1 * y1
        p0, p1 = X / y, X1 / y1
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 6 if b > 0 else 0, "n_sells": 1 if s > 0 else 0, "n_dust": 0,
                     "buy_sol": b, "sell_sol": s, "buy_tok": bt, "sell_tok": st,
                     "n_buyers": int(n_buyers[j]) if n_buyers is not None else int(b > 0),
                     "n_sellers": int(n_sellers[j]) if n_sellers is not None else int(s > 0),
                     "top5_buy_sol": b, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": X1 - V0, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0 if agent is None else float(agent[j]), "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def frames_with(bots: dict, n: int = 8, seed: int = 1, t0: int = T0):
    """make_frames (random-walk 'noise' coins with 4 buyers a minute) with coin i's bars replaced by coin_bars(**spec)."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0)
    for i, spec in bots.items():
        r = g[g["mint"] == mint(i, seed)].iloc[0]
        b = pd.concat([b[b["mint"] != r["mint"]], coin_bars(int(r["g_ts"]), r["mint"], r["pool"], **spec)],
                      ignore_index=True)
    return g, c, b


def ds_of(frames, split: str = "train", trades=None) -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, trades=trades, guard=False)


def full(v, n=N_MIN):
    return np.full(n, float(v))


def snap_at(ds: C.Dataset, m: str, age_min: float) -> C.AsOf:
    cd = ds.coin(m)
    return ds.asof(m, M._grid_time(cd, cd.g + 60 * age_min))


def _set(df: pd.DataFrame, m: str, **vals) -> None:
    idx = df.index[df["mint"] == m]
    for k, v in vals.items():
        if isinstance(v, str) or v is None:
            df[k] = df[k].astype(object)
        for i in idx:
            df.at[i, k] = v


# =========================================================================== MECH-bar features


def test_pure_bot_fires_with_exact_floor_and_drift():
    fr = frames_with({2: {"buy": full(0.2)}})
    ds = ds_of(fr)
    s = snap_at(ds, mint(2), 40)
    mb = M.mech_bar(s)
    assert mb["ok"] and mb["fires"] and mb["bid_alive"]
    assert mb["floor"] == pytest.approx(0.2) and mb["cv"] == pytest.approx(0.0, abs=1e-12)
    assert mb["quiet_buyers"] == 1 and mb["spearman"] == 0.0
    X = X0 + 0.2 * s.k                                   # every completed minute added 0.2 SOL to X
    assert mb["X"] == pytest.approx(X, rel=1e-9)
    assert mb["mech_bid_h"] == pytest.approx(12.0)
    assert mb["drift_pred60"] == pytest.approx(((X + 12.0) / X) ** 2 - 1, rel=1e-9)
    assert mb["mech_age_min"] == s.k                     # the bid has run since the graduation minute


def test_too_few_bars_is_not_ok():
    ds = ds_of(frames_with({2: {"buy": full(0.2)}}))
    mb = M.mech_bar(snap_at(ds, mint(2), 20))
    assert not mb["ok"] and not mb["fires"] and mb["floor"] is None


def test_floor_needs_the_bid_in_28_of_30_minutes():
    ds0 = ds_of(frames_with({2: {"buy": full(0.2)}}))
    k = snap_at(ds0, mint(2), 40).k
    for n_gap, fires in ((2, True), (3, False)):
        buy = full(0.2)
        buy[[k - 5 - 7 * i for i in range(n_gap)]] = 0.0    # minutes with no trade at all inside the window
        mb = M.mech_bar(snap_at(ds_of(frames_with({2: {"buy": buy}})), mint(2), 40))
        assert mb["fires"] is fires
        assert mb["floor"] == (pytest.approx(0.2) if fires else 0.0)


def test_steady_crowd_is_not_mech():
    mb = M.mech_bar(snap_at(ds_of(frames_with({2: {"buy": full(0.2), "n_buyers": full(5)}})), mint(2), 40))
    assert mb["quiet_buyers"] == 5 and not mb["fires"]


def test_unsteady_flow_is_not_mech_but_steady_flow_is():
    alt = np.where(np.arange(N_MIN) % 2 == 0, 0.05, 2.0)
    # sells offset buys exactly, so the price never moves and only the steadiness test can refuse
    mb = M.mech_bar(snap_at(ds_of(frames_with({2: {"buy": alt, "sell": alt}})), mint(2), 40))
    assert mb["spearman"] == 0.0 and mb["quiet_buyers"] == 1 and mb["floor"] >= M.FLOOR_MIN_SOL
    assert mb["cv"] >= M.STEADY_MAX_CV and not mb["fires"]
    mb = M.mech_bar(snap_at(ds_of(frames_with({2: {"buy": full(1.0), "sell": full(1.0)}})), mint(2), 40))
    assert mb["fires"]


def test_price_reacting_flow_is_not_mech():
    j = np.arange(N_MIN)
    buy = np.where(j % 2 == 0, 1.0, 0.5)                 # big buys after down-minutes, small after up-minutes
    sell = np.where(j % 2 == 0, 0.0, 1.4)
    mb = M.mech_bar(snap_at(ds_of(frames_with({2: {"buy": buy, "sell": sell}})), mint(2), 40))
    assert mb["cv"] < M.STEADY_MAX_CV and mb["quiet_buyers"] == 1
    assert abs(mb["spearman"]) >= M.SPEARMAN_MAX and not mb["fires"]


def test_agent_buys_are_removed_once_the_agent_is_known():
    fr = frames_with({0: {"buy": full(0.2), "agent": full(0.2)}})    # coin 0 has an AGENT (known at g + 40)
    g, c, b = fr
    cd_g = int(g.loc[g["mint"] == mint(0), "g_ts"].iloc[0])
    c = c.copy()
    _set(c, mint(0), agent_known_at=float(cd_g + 600))
    ds = ds_of((g, c, b))
    s_early = ds.asof(mint(0), (cd_g // 60 * 60) + 120 + 20)          # tau before agent_known_at: NaN, nothing removed
    assert not s_early.agent_detected
    assert M.bid_series(s_early.bars, s_early.k).tolist() == [0.2] * s_early.k
    s = snap_at(ds, mint(0), 40)
    assert s.agent_detected
    assert M.bid_series(s.bars, s.k).max() == 0.0
    assert not M.mech_bar(s)["fires"]


def test_run_minutes_counts_back_with_two_misses():
    carry = np.array([False, False, False, True, True, True, False, True, True])
    assert M._run_minutes(carry, len(carry)) == 6
    assert M._run_minutes(np.zeros(5, bool), 5) == 0
    assert M._run_minutes(np.ones(7, bool), 7) == 7


def test_bid_alive_turns_off_after_two_empty_minutes():
    buy = full(0.2)
    ds0 = ds_of(frames_with({2: {"buy": buy}}))
    k = snap_at(ds0, mint(2), 50).k
    buy[k - 2:] = 0.0
    mb = M.mech_bar(snap_at(ds_of(frames_with({2: {"buy": buy}})), mint(2), 50))
    assert mb["fires"] and not mb["bid_alive"]


def test_precursor_dump_is_a_pigeonhole_bound():
    X50 = X0 + 0.2 * 50
    sell = np.zeros(N_MIN)
    sell[50] = 0.05 * X50
    for ns, flagged in ((1, True), (2, False)):
        n_sellers = np.zeros(N_MIN)
        n_sellers[50] = ns
        ds = ds_of(frames_with({2: {"buy": full(0.2), "sell": sell, "n_sellers": n_sellers}}))
        pr = M.precursors(snap_at(ds, mint(2), 60), j_from=40)
        assert (50 in pr["dump"]) is flagged
        assert pr["lp"] == []


def test_precursor_lp_is_a_token_conservation_break():
    ds = ds_of(frames_with({2: {"buy": full(0.2), "y_shift": {50: 0.02}}}))
    s = snap_at(ds, mint(2), 60)
    assert M.precursors(s, j_from=1)["lp"] == [50]
    assert M.precursors(s, j_from=51)["lp"] == []
    clean = snap_at(ds_of(frames_with({2: {"buy": full(0.2)}})), mint(2), 60)
    assert M.precursors(clean, j_from=1) == {"dump": [], "lp": []}


def test_class_rules_and_nulls():
    g, c, b = make_frames(n=6, seed=1)
    c = c.copy()
    _set(c, mint(0), w120_top10=json.dumps([["F1", 10, 0], ["F2", 8, 0], ["F3", 5, 0], ["F4", 2, 0], ["F5", 1, 0]]))
    _set(c, mint(1), w120_buy_sol=800.0, w120_n_buyers=12)
    _set(c, mint(4), w120_top10=json.dumps([["F1", 10, 0], ["F2", 8, 0], ["F3", 5, 0], ["F4", 2, 0], ["F5", 1, 0]]))
    _set(c, mint(3), w120_buy_sol=np.nan)
    ds = ds_of((g, c, b))
    cls = {i: M.m1_class(snap_at(ds, mint(i), 40)) for i in range(6)}
    assert cls[0] == "FACTORY"           # instant (<= 5 s), top-5 share 26/30 with the AGENT not in the list
    assert cls[1] == "OPERATOR"          # 800 SOL from 12 buyers in 2 min
    assert cls[2] == "OTHER"
    assert cls[3] is None                # NULL w120 total: never treated as 0
    assert cls[4] == "OTHER"             # creation not scanned: grad_delay NULL, lower bound 1800 s > 5 s
    s = ds.asof(mint(1), ds.coin(mint(1)).g + 200)    # no AGENT and tau < g + 420: presence undecided
    assert M.m1_class(s) is None


def test_round_trip_is_commons_cost_model():
    ds = ds_of(frames_with({2: {"buy": full(0.2)}}))
    s = snap_at(ds, mint(2), 40)
    X, y = float(s.bars.X[-1]), float(s.bars.y[-1])
    want = C.round_trip_pct(20.0 / s.sol_usd, s.price, X * y, s.t, C.CostModel()) / 100
    assert M.round_trip_frac(s) == pytest.approx(want, rel=1e-12)
    assert 0.02 < want < 0.08


@pytest.mark.parametrize("f,m1_ok,m2_ok", [(0.02, False, False), (0.04, True, False), (0.06, True, True)])
def test_entry_needs_drift_over_m_round_trips(f, m1_ok, m2_ok):
    s = snap_at(ds_of(frames_with({2: {"buy": full(f)}})), mint(2), 40)
    ok1, info = M.entry_decision(s, {"m": 1.0}, "OTHER")
    ok2, _ = M.entry_decision(s, {"m": 2.0}, "OTHER")
    assert info["fires"] and info["precursor"] is False
    assert (ok1, ok2) == (m1_ok, m2_ok)
    assert ok1 == (info["drift_over_cost"] >= 1.0) and ok2 == (info["drift_over_cost"] >= 2.0)


def test_entry_refused_with_a_precursor_in_the_window():
    X38 = X0 + 0.5 * 38
    sell, ns = np.zeros(N_MIN), np.zeros(N_MIN)
    sell[38], ns[38] = 0.05 * X38, 1
    s = snap_at(ds_of(frames_with({2: {"buy": full(0.5), "sell": sell, "n_sellers": ns}})), mint(2), 45)
    ok, info = M.entry_decision(s, {"m": 1.0}, "OTHER")
    assert info["fires"] and info["precursor"] is True and not ok


def test_strategy_skips_factory_and_waits_for_age():
    g, c, b = frames_with({0: {"buy": full(0.5)}, 2: {"buy": full(0.5)}})
    c = c.copy()
    _set(c, mint(0), w120_top10=json.dumps([["F1", 10, 0], ["F2", 8, 0], ["F3", 5, 0], ["F4", 2, 0], ["F5", 1, 0]]))
    ds = ds_of((g, c, b))
    p = M.make_params(1, "rhythm")
    assert M.strategy(snap_at(ds, mint(2), 20), p, None) is None
    assert M.strategy(snap_at(ds, mint(0), 40), p, None) is C.SKIP
    assert M.strategy(snap_at(ds, mint(2), 125), p, None) is C.SKIP
    e = M.strategy(snap_at(ds, mint(2), 40), p, None)
    assert isinstance(e, C.Enter) and e.tag == "OTHER" and e.state["floor"] == pytest.approx(0.5)
    assert e.exits.stop_pct == M.STOP_PCT and e.exits.max_hold_s == M.MAX_HOLD_S


def test_rhythm_break_exit_and_placebo_recomputes_the_floor():
    buy = full(0.5)
    buy[60:] = 0.0
    ds = ds_of(frames_with({2: {"buy": buy}}))
    p = M.make_params(1, "rhythm")
    tr = C.run_trades(ds, M.strategy, p, C.FillConfig(), mints=[mint(2)])
    assert len(tr) == 1
    r = tr.iloc[0]
    cd = ds.coin(mint(2))
    assert r["reason"] == "signal:rhythm"
    assert r["t_out"] == cd.bar_start(62) + C.GRID_OFFSET_S + 30      # decided once bars 60 and 61 were empty
    t_exit = cd.bar_start(62) + C.GRID_OFFSET_S
    for state, placebo in (({"floor": 0.5}, False), ({}, True)):
        pv = C.PositionView(mint=mint(2), t_dec=float(r["t_dec"]), t_in=float(r["t_in"]), entry_price=1.0, tokens=1.0,
                            sol_in=0.2, peak=1.0, bars_held=5, unrealized=0.0, exits=C.ExitSpec(), state=state,
                            is_placebo=placebo)
        assert M.exit_decision(ds.asof(mint(2), t_exit - 60), p, pv) is None
        ex = M.exit_decision(ds.asof(mint(2), t_exit), p, pv)
        assert isinstance(ex, C.Exit) and ex.reason == "rhythm"


def test_precursor_exit_only_in_the_rhythm_prec_set():
    X70 = X0 + 0.5 * 70
    sell, ns = np.zeros(N_MIN), np.zeros(N_MIN)
    sell[70], ns[70] = 0.045 * X70, 1
    ds = ds_of(frames_with({2: {"buy": full(0.5), "sell": sell, "n_sellers": ns}}))
    a = C.run_trades(ds, M.strategy, M.make_params(1, "rhythm+prec"), C.FillConfig(), mints=[mint(2)]).iloc[0]
    b = C.run_trades(ds, M.strategy, M.make_params(1, "rhythm"), C.FillConfig(), mints=[mint(2)]).iloc[0]
    cd = ds.coin(mint(2))
    assert a["reason"] == "signal:precursor_dump" and a["t_out"] == cd.bar_start(71) + C.GRID_OFFSET_S + 30
    assert b["reason"] == "horizon" and a["t_dec"] == b["t_dec"]


def test_grid_is_the_plan_grid():
    assert len(M.GRID) == 4 == C.VARIANT_LIMITS["M1"]
    assert len({C.params_hash(p) for p in M.GRID}) == 4
    assert {(p["m"], p["exit"]) for p in M.GRID} == {(1.0, "rhythm"), (1.0, "rhythm+prec"), (2.0, "rhythm"),
                                                     (2.0, "rhythm+prec")}
    for p in M.GRID:
        assert all(p[k] == v for k, v in M.FIXED.items())
    with pytest.raises(ValueError):
        M.make_params(1, "trail")


# =========================================================================== MECH-wallet (PLAN verbatim) on B1 trades


def _b1(g: int, m: str, rows: list[tuple]) -> pd.DataFrame:
    """rows: (ts, wallet_h, is_buy, sol, pooled). Pool reserves follow a constant product with a virtual reserve."""
    rows = sorted(rows, key=lambda r: (r[0], r[1]))
    x, v, y = 85e9, 17_584_505_289.0, 206.9e12
    out = []
    for i, (ts, w, isb, sol, pooled) in enumerate(rows):
        X = x + v
        lam = sol * 1e9
        if isb:
            tok = y * lam / (X + lam)
            x1, y1 = x + lam, y - tok
        else:
            tok = y * lam / max(X - lam, 1.0)
            x1, y1 = x - lam, y + tok
        out.append({"slot": i, "tx_idx": 0, "pix": 0, "ix": 0, "ts": int(ts), "mint": m, "venue": 1, "is_buy": isb,
                    "wallet_h": w, "usol": int(lam), "tok": int(tok), "x0": x, "y0": y, "fees": 0,
                    "virt_ksol": v / 1000.0, "src": 0, "pooled": pooled})
        x, y = x1, y1
    return pd.DataFrame(out)


def test_mech_wallet_detector_plan_rules(monkeypatch):
    g, c, b = make_frames(n=4, seed=1)
    m = mint(2)
    gts = int(g.loc[g["mint"] == m, "g_ts"].iloc[0])
    rng = np.random.default_rng(5)
    rows = []
    rows += [(gts + 300 + 30 * i, 101, True, 0.1, False) for i in range(70)]                 # MECH
    t, i = gts + 200, 0
    while t < gts + 2400:                                                                   # irregular
        rows.append((t, 102, True, float(rng.lognormal(-2, 1.0)), False))
        t += float(rng.exponential(40)) + 1
    rows += [(gts + 310 + 30 * i, 103, True, 0.1, False) for i in range(70)]                 # regular but sells
    rows += [(gts + 900 + 300 * i, 103, False, 0.5, False) for i in range(3)]
    rows += [(gts + 2 + 12 * i, 104, True, 0.6, False) for i in range(29)]                   # AGENT (BOOST)
    rows += [(gts + 305 + 30 * i, 105, True, 0.1, True) for i in range(70)]                  # pooled account
    tr = _b1(gts, m, rows)
    ds = ds_of((g, c, b), trades=tr)
    s = ds.asof(m, gts + 32 * 60)
    got = M.mech_wallets(s)
    assert [w["wallet_h"] for w in got] == [101]
    assert got[0]["n_buys"] >= M.MW_MIN_BUYS and got[0]["gap_cv"] < M.MW_MAX_GAP_CV
    monkeypatch.setattr(M, "_creator_h", lambda address: 101)                               # 101 is the CREATOR
    assert M.mech_wallets(s) == []
    assert M.mech_wallets(ds.asof(mint(1), gts + 32 * 60)) is None                          # no B1 rows: not covered
    assert M.mech_wallets(ds_of((g, c, b)).asof(m, gts + 32 * 60)) is None                   # no B1 at all


def test_mech_wallet_only_sees_trades_up_to_tau():
    g, c, b = make_frames(n=4, seed=1)
    m = mint(2)
    gts = int(g.loc[g["mint"] == m, "g_ts"].iloc[0])
    rows = [(gts + 300 + 30 * i, 101, True, 0.1, False) for i in range(70)]
    tau = gts + 32 * 60 - 20
    late = [(t, w, s, v * (50 if t > tau else 1), p) for t, w, s, v, p in rows]               # future sizes garbage
    late += [(tau + 5, 101, False, 5.0, False)]                                               # a future sell
    a = M.mech_wallets(ds_of((g, c, b), trades=_b1(gts, m, rows)).asof(m, tau + 20))
    bb = M.mech_wallets(ds_of((g, c, b), trades=_b1(gts, m, late)).asof(m, tau + 20))
    assert [w["wallet_h"] for w in a] == [w["wallet_h"] for w in bb] == [101]
    assert a[0]["buy_sol"] == pytest.approx(bb[0]["buy_sol"])


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    mb = M.mech_bar(s)
    pr = M.precursors(s, j_from=max(mb["k"] - M.W_BARS, 1))
    cls = M.m1_class(s)
    ent = tuple(M.entry_decision(s, {"m": mm}, cls)[0] for mm in M.M_GRID) if cls in M.ALLOWED_CLASSES else None
    rt = M.round_trip_frac(s)
    return (tuple(sorted((k, None if v is None else (round(v, 12) if isinstance(v, float) else v))
                         for k, v in mb.items())), json.dumps(pr), cls, ent, None if rt is None else round(rt, 12))


def _bot_frames(seed: int):
    rng = np.random.default_rng(seed)
    bots = {}
    for i in range(0, 12, 2):
        f = float(rng.uniform(0.05, 0.6))
        buy = full(f) * rng.uniform(0.9, 1.1, N_MIN)
        stop = int(rng.integers(50, 170))
        buy[stop:] = 0.0
        sell = np.zeros(N_MIN)
        ns = np.zeros(N_MIN)
        jd = int(rng.integers(35, 120))
        sell[jd], ns[jd] = 0.05 * (X0 + f * jd), 1
        bots[i] = {"buy": buy, "sell": sell, "n_sellers": ns}
    return frames_with(bots, n=12, seed=1)


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _bot_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([90, 300, 500, 1900, 2100, 3000, 4500, 6000, 7200, 9000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _bot_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(0, 12, 2):
        m = mint(i)
        cd = clean.coin(m)
        T = cd.g + 50 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        for p in M.GRID:
            a = C.run_trades(clean, M.strategy, p, C.FillConfig(), mints=[m])
            b = C.run_trades(dirty, M.strategy, p, C.FillConfig(), mints=[m])
            a_dec = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
            assert a_dec == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n_entries += len(a_dec)
    assert n_entries > 0


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """M1 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(11)
    op = [m for m in full_ds.mints if M.m1_class(snap_at(full_ds, m, 40)) == "OPERATOR"]
    pick = list(rng.choice(op, size=min(8, len(op)), replace=False))
    pick += [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=8, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(300, 1700)), float(rng.uniform(1900, 4000)), float(rng.uniform(4000, 7300))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


# =========================================================================== model check (stop rule 5)


def _obs(n_coins: int, per: int, slope: float, noise: float, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_coins):
        for a in range(per):
            x = float(rng.uniform(0.01, 0.3))
            rows.append({"mint": f"C{c}", "class": "OPERATOR", "age_min": 30 + 10 * a, "t": 1e9 + 600 * a,
                         "drift_pred60": x, "realized60": slope * x + float(rng.normal(0, noise)),
                         "rug_in_window": False, "wallet_mech": None})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("n,per,slope,noise,want", [
    (40, 4, 1.0, 0.01, "PASS"),
    (40, 4, 0.3, 0.005, "KILL"),        # slope < 0.5
    (40, 4, 1.0, 2.0, "KILL"),          # R^2 < 0.05
    (20, 9, 1.0, 0.01, "UNDERPOWERED"),  # < 30 coins
    (35, 2, 1.0, 0.01, "UNDERPOWERED"),  # < 100 observations
])
def test_model_check_decision(n, per, slope, noise, want):
    mc = M.model_check(_obs(n, per, slope, noise), B=200)
    assert mc["decision"] == want
    if want == "PASS":
        assert mc["fit"]["slope"] == pytest.approx(1.0, abs=0.05) and mc["fit"]["r2"] > 0.9
        assert mc["slope_ci95_coin"][0] < 1.0 < mc["slope_ci95_coin"][1]


def test_model_check_hidden_on_debug():
    mc = M.model_check(_obs(40, 4, 1.0, 0.01), hide=True)
    assert "fit" not in mc and mc["decision"].startswith("HIDDEN") and mc["n_obs"] == 160


def test_model_check_obs_label_is_the_next_60_minutes():
    """Pure bots: every SOL bought lands in X, so the realized 60-min change equals drift_pred60 exactly. Any
    off-by-one in the label (or a lookahead in the prediction) breaks the equality."""
    bots = {i: {"buy": full(0.1 + 0.05 * i)} for i in range(6)}
    ds = ds_of(frames_with(bots, n=8))
    obs = M.model_check_obs(ds)
    assert set(obs["mint"]) == {mint(i) for i in range(6)}
    assert (obs.groupby("mint").size() == len(M.MC_AGES_MIN)).all()
    np.testing.assert_allclose(obs["realized60"], obs["drift_pred60"], rtol=1e-9)
    assert not obs["rug_in_window"].any() and obs["wallet_mech"].isna().all()


# =========================================================================== decision rules


def _ev(n, clusters, mean, mw2, ci_lo, pc, rug=0.0):
    return {"n": n, "n_clusters": clusters, "mean": mean, "mean_without_top2": mw2, "ci90": (ci_lo, ci_lo + 0.1),
            "placebo": {"mean_diff": pc}, "rug_rate": rug,
            "clusters": {"ci90_cluster": (ci_lo, ci_lo + 0.1), "mean_without_largest": mean}}


def test_decide_train_pair_rule():
    ev = {M.config_key(p): _ev(40, 5, 0.05, 0.03, 0.01, 0.08) for p in M.GRID}
    ev[M.config_key(M.make_params(1, "rhythm+prec"))] = _ev(40, 5, 0.06, 0.04, 0.02, 0.08)
    d = M.decide_train(ev)
    assert d["verdict"] == "SHORTLISTED" and d["m_star"] == 1.0
    assert [(p["m"], p["exit"]) for p in d["shortlist"]] == [(1.0, "rhythm"), (1.0, "rhythm+prec")]
    # the rhythm-only twin's TRAIN numbers never choose anything
    ev2 = {M.config_key(p): _ev(40, 5, -0.05, -0.06, -0.1, -0.01) for p in M.GRID}
    ev2[M.config_key(M.make_params(2, "rhythm"))] = _ev(80, 9, 0.5, 0.4, 0.3, 0.5)
    assert M.decide_train(ev2)["verdict"] == "NO_CONFIG"
    ev3 = {M.config_key(p): _ev(40, 1, 0.5, 0.4, 0.3, 0.5) for p in M.GRID}     # one operator only
    d3 = M.decide_train(ev3)
    assert d3["verdict"] == "UNDERPOWERED_TRAIN" and "1 clusters" in d3["reason"] and not d3["shortlist"]


def test_decide_val_and_confirm_rules():
    assert M.decide_val({"n": 3, "mean": 0.5, "mean_without_top2": 0.4})["verdict"] == "UNDERPOWERED_VAL"
    assert M.decide_val({"n": 8, "mean": 0.05, "mean_without_top2": 0.01})["verdict"] == "SELECTED_UNDERPOWERED"
    assert M.decide_val({"n": 20, "mean": 0.05, "mean_without_top2": -0.01})["verdict"] == "FAIL_VAL"
    assert M.decide_val({"n": 20, "mean": 0.05, "mean_without_top2": 0.02})["verdict"] == "SELECTED"
    doc = lambda v, n, mean: {"verdict": {"verdict": v}, "configs": {"candidate": {"n": n, "mean": mean}}}  # noqa
    assert M.confirm_allowed(doc("UNDERPOWERED", 30, 0.01))[0]
    assert M.confirm_allowed(doc("UNDERPOWERED", 2, -0.5))[0]          # no evidence either way
    assert not M.confirm_allowed(doc("UNDERPOWERED", 30, -0.01))[0]
    assert not M.confirm_allowed(doc("REJECTED", 30, 0.2))[0]


def test_combine_verdict_ignores_missing_final_but_not_failures():
    def base(passes, rej=()):
        return {"criteria": [{"id": i + 1, "pass": p} for i, p in enumerate(passes)], "auto_rejections": list(rej)}
    ok8 = [True] * 8 + [None]
    ex = M.m1_extras(_ev(70, 4, 0.05, 0.03, 0.01, 0.1, rug=0.0), _ev(70, 4, 0.04, 0.02, 0.0, 0.1, rug=0.0))
    assert ex[3]["pass"] is None and M.combine_verdict(base(ok8), ex) == "PASS"
    assert M.combine_verdict(base(ok8, ["x"]), ex) == "REJECTED"
    assert M.combine_verdict(base([False] + ok8[1:]), ex) == "UNDERPOWERED"
    assert M.combine_verdict(base(ok8[:4] + [False] + ok8[5:]), ex) == "FAIL"
    ex_rug = M.m1_extras(_ev(70, 4, 0.05, 0.03, 0.01, 0.1, rug=0.2), _ev(70, 4, 0.04, 0.02, 0.0, 0.1, rug=0.3))
    assert ex_rug[3]["pass"] is False and M.combine_verdict(base(ok8), ex_rug) == "FAIL"
    ex_pow = M.m1_extras(_ev(70, 2, 0.05, 0.03, 0.01, 0.1), None)
    assert M.combine_verdict(base(ok8), ex_pow) == "UNDERPOWERED"


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path):
    d = SimpleNamespace(out=tmp_path / "M1", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# M1 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return M.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return M.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_bot: int, n_noise: int, seed: int, flat: bool = False) -> C.Dataset:
    """n_bot pure-bot coins (bid f_i every minute; ``flat``: sellers absorb it exactly) + noise coins."""
    bots = {}
    for i in range(n_bot):
        f = 0.3 + 0.01 * i
        bots[i] = {"buy": full(f), "sell": full(f) if flat else None}
    ds = ds_of(frames_with(bots, n=n_bot + n_noise, seed=seed, t0=t0), split)
    assert len(ds) >= n_bot
    return ds


def test_train_kill_stops_m1(st):
    ds = market("train", T0, 36, 4, 1, flat=True)       # the bid never moves the price: realized 0, slope 0
    doc = _run("train", st, ds)
    assert doc["model_check"]["decision"] == "KILL"
    assert doc["decision"]["verdict"] == "KILLED_MODEL_CHECK" and "configs" not in doc
    assert doc["overall"].startswith("KILLED")
    runs = json.loads(st.ledger.read_text())["runs"]
    assert [r["hypothesis"] for r in runs] == ["M1-modelcheck"]      # no P&L was run
    assert not (st.sl / "M1.json").exists()
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(M.M1Refused, match="stop rule 5"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(M.M1Refused, match="final"):
        _run("train", st, ds)                                          # a decision on complete TRAIN is final
    doc2 = _run("train", st, ds, rerun_reason="test: data correction")
    assert doc2["decision"]["verdict"] == "KILLED_MODEL_CHECK"
    assert list(st.out.glob("train_prev_*.json"))


def test_underpowered_model_check_halts(st):
    doc = _run("train", st, market("train", T0, 10, 4, 1))
    assert doc["decision"]["verdict"] == "UNDERPOWERED_MODEL_CHECK"
    with pytest.raises(M.M1Refused, match="UNDERPOWERED_MODEL_CHECK"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 36, 4, 1)
    with pytest.raises(M.M1Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "M1.json").exists()
    with pytest.raises(M.M1Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    with pytest.raises(M.M1Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: model check PASS (pure bots: realized == predicted), grid, shortlist of the pair
    tr = _run("train", st, market("train", T0, 36, 12, 1))
    assert tr["model_check"]["decision"] == "PASS" and tr["model_check"]["fit"]["slope"] == pytest.approx(1.0)
    assert set(tr["configs"]) == {M.config_key(p) for p in M.GRID}
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "M1") == 4
    assert led["n_trials_total"] == 2575 + 5
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(M.M1Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# M1 test prereg\n")
    # TEST / CONFIRM / FINAL before VAL
    with pytest.raises(M.M1Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    with pytest.raises(M.M1Refused, match="before TEST"):
        _check("final", st, env=env_all)
    with pytest.raises(M.M1Refused, match="before TEST"):
        _check("confirm", st, env=env_all)
    # VAL needs the written shortlist
    sl = (st.sl / "M1.json").read_text()
    (st.sl / "M1.json").unlink()
    with pytest.raises(M.M1Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "M1.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 10, 2))
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"candidate", "twin"}
    with pytest.raises(M.M1Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 30, 10, 3)
    with pytest.raises(M.M1Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert {c["id"] for c in te["verdict"]["m1_extras"]} == {"M1.1", "M1.2", "M1.3", "M1.4"}
    with pytest.raises(M.M1Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(M.M1Refused, match="one test run"):
        _check("test", st, env=env_all)                                   # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] == "test"} == {"M1", "M1-twin"}
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 20, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(M.M1Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 10, 6, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(M.M1Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(M.M1Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(M.M1Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 36, 12, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = M.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert "fit" not in doc["model_check"] and doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert "mean" not in e and "ci90" not in e and "placebo" not in e and e["returns"].startswith("hidden")
        assert "rug_hits" not in e and "rug_rate" not in e and "stress" not in e and "portfolio" not in e
    assert doc["event_counts"]["coins_detector_fires"] >= 30
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])

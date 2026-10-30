"""Tests for research/lab2/q8.py: A membership and every exclusion on hand-built B1 tapes, the MECH test against
m1.mech_wallets, no lookahead (B1 and bars garbled after tau), the entry window, the E1 cohort exit (and the placebo
cohort), the E2 close trail, the shuffled-wallet control, the pre-registered decision rules, the B1 gate and the stage
machinery end to end."""

import json
import math
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import m1 as M1
import q8 as Q
import s1
from conftest import POOLED, V0, make_frames, real_flow_available
from conftest import VALID_ALL as VALID
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
L = 1e9


def addr(i: int) -> str:
    return s1.b58encode(bytes([(i * 37 + k) % 251 + 1 for k in range(32)]))


def wh(a) -> int:
    return s1.wallet_h(a) if isinstance(a, str) else int(a)


@pytest.fixture(autouse=True)
def _fresh_cache():
    Q.clear_cache()
    yield
    Q.clear_cache()


# =========================================================================== fixtures


def calm_bars(g: int, mint: str, pool: str, drift: float = 0.0, close_fn=None, n_min: int = 186) -> pd.DataFrame:
    """Deterministic minute bars: close_j = p0 (1 + drift)^(j + 1) (or ``close_fn(j)``), reserves on X * y = k,
    5 SOL of volume a minute (alive: $7.5k / 15 min at $100, market cap ~$41k)."""
    m0 = int(g) // 60 * 60
    k = X0 * Y0
    p0 = X0 / Y0
    prev = p0
    rows = []
    for j in range(n_min):
        p = p0 * (1 + drift) ** (j + 1) if close_fn is None else close_fn(j)
        X, y = math.sqrt(k * p), math.sqrt(k / p)
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 5, "n_sells": 3, "n_dust": 0, "buy_sol": 3.0,
                     "sell_sol": 2.0, "buy_tok": 1e6, "sell_tok": 1e6, "n_buyers": 4, "n_sellers": 3,
                     "top5_buy_sol": 3.0, "open": prev, "high": max(prev, p), "low": min(prev, p), "close": p,
                     "x_close": X - V0, "y_close": y, "mint": mint, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0, "price_repaired": 0})
        prev = p
    return pd.DataFrame(rows)


def q_frames(n: int = 4, seed: int = 1, t0: int = T0, drifts=None, close_fns=None, agent_for=()):
    """B1-universe coins (created g - 600 s, creation scanned) with calm bars, real-looking creator / completer."""
    g, c, _ = make_frames(n=n, seed=seed, t0=t0, slow_every=0, agent_every=0)
    g, c = g.copy(), c.copy()
    g["c_ts"] = g["g_ts"] - 600
    g["c_slot"] = g["g_slot"] - 2000
    g["creator"] = [addr(900 + i) for i in range(n)]
    g["completer"] = [addr(800 + i) for i in range(n)]
    g["curve_top3_buy_sol"] = 30.0                 # G1 class ORGANIC (not COMPLETED)
    for i in agent_for:
        c.loc[i, "agent_present"] = True
        c.loc[i, "agent_wallet"] = addr(700 + i)
        c.loc[i, "agent_known_at"] = float(g.loc[i, "g_ts"]) + 40.0
    bars = []
    for i, r in g.iterrows():
        d = 0.0 if drifts is None else drifts[i]
        fn = None if close_fns is None else close_fns.get(i)
        bars.append(calm_bars(int(r["g_ts"]), r["mint"], r["pool"], d, fn))
    return g, c, pd.concat(bars, ignore_index=True)


def tape(mint: str, rows: list[tuple]) -> pd.DataFrame:
    """B1 pool rows from (ts, wallet, is_buy, sol[, pooled]); reserves follow a constant product on X = x + v."""
    rows = sorted(rows, key=lambda r: r[0])
    x, v, y = 85e9, V0 * 1e9, 206.9e12
    out = []
    for i, r in enumerate(rows):
        ts, w, isb, sol = r[:4]
        lam = sol * L
        X = x + v
        tok = y * lam / (X + lam) if isb else y * lam / max(X - lam, 1.0)
        out.append({"slot": 10 + i, "tx_idx": 0, "pix": 0, "ix": 0, "ts": int(ts), "mint": mint, "venue": 1,
                    "is_buy": bool(isb), "wallet_h": np.uint64(wh(w)), "usol": int(lam), "tok": int(tok), "x0": x,
                    "y0": y, "fees": 0, "virt_ksol": V0 * 1e6, "src": 0, "pooled": bool(r[4]) if len(r) > 4 else False})
        x, y = (x + lam, y - tok) if isb else (x - lam, y + tok)
    df = pd.DataFrame(out)
    df["wallet_h"] = df["wallet_h"].astype(np.uint64)
    return df


def ds_of(frames, trades=None, split="train") -> C.Dataset:
    g, c, b = frames
    return C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL, trades=trades, guard=False)


def m0_of(frames, i: int) -> tuple[str, int, int]:
    r = frames[0].iloc[i]
    return r["mint"], int(r["g_ts"]), int(r["g_ts"]) // 60 * 60


def grid_t(m0: int, minute: int) -> float:
    """Decision time on the grid: tau = m0 + 60 * minute."""
    return float(m0 + 60 * minute + C.DECISION_LAG_S)


def accumulators(M: int, wallets, start_min: int = 1, every=(2, 3, 2, 4, 3, 2, 5), n: int = 6, sol=0.15):
    rows = []
    for k, w in enumerate(wallets):
        mi = start_min + k % 2
        for j in range(n):
            rows.append((M + 60 * mi + 7 + k, w, True, sol + 0.01 * ((j + k) % 3)))
            mi += every[(j + k) % len(every)]
    return rows


# =========================================================================== A membership and exclusions


def _hand_rows(M: int, agent: str, creator: str, completer: str) -> list[tuple]:
    rows = []
    rows += [(M + 60, 1, True, 0.2), (M + 180, 1, True, 0.2), (M + 300, 1, True, 0.2)]            # R1: in A
    rows += [(M + 121, 2, True, 0.5), (M + 122, 2, True, 0.5), (M + 123, 2, True, 0.5)]           # one minute
    rows += [(M + 60 * j + 5, 3, True, 0.05) for j in (2, 4, 6)]                                  # 0.15 SOL < 0.3
    rows += [(M + 60 * j + 9, 4, True, 0.5) for j in (2, 4, 6)] + [(M + 600, 4, False, 0.1)]     # sold
    t, sizes = M + 70, (0.1, 0.9, 0.3, 0.7, 0.2, 0.8, 0.4)
    for gap, s in zip((0, 60, 300, 75, 400, 90, 500), sizes):                                     # R5: irregular
        t += gap
        rows.append((t, 5, True, s))
    rows += [(M + 1500 + 60 * j, 6, True, 0.2) for j in range(8)]                                 # MECH at tau
    rows += [(M + 300 + 60 * j, 7, True, 0.2) for j in range(7)]                                  # MECH earlier
    for w in (agent, creator, completer, POOLED):
        rows += [(M + 60 * j + 11, w, True, 0.4, w == POOLED) for j in (1, 3, 5, 7)]
    rows += [(M + 60 * j + 30, 100 + j, True, 1.0) for j in range(1, 40)]                         # one-off buyers
    return rows


def test_a_membership_share_and_every_exclusion():
    fr = q_frames(n=2, agent_for=(0,))
    m, g, M = m0_of(fr, 0)
    agent, creator, completer = addr(700), addr(900), addr(800)
    rows = _hand_rows(M, agent, creator, completer)
    tr = tape(m, rows)
    ds = ds_of(fr, tr)
    snap = ds.asof(m, grid_t(M, 51))
    assert snap.agent_detected
    f = Q.ca_features(snap)
    assert f["ok"] and f["count_A"] == 2
    assert set(f["cohort"]) == {wh(1), wh(5)}
    assert f["n_mech"] == 2                       # wallet 7 stopped before tau's window: still MECH ("ever flagged")
    buys = [r for r in rows if r[2]]
    denom = sum(r[3] for r in buys if r[1] != agent)
    a_sol = 0.6 + sum((0.1, 0.9, 0.3, 0.7, 0.2, 0.8, 0.4))
    assert f["denom"] == pytest.approx(denom) and f["share_A"] == pytest.approx(a_sol / denom)
    flagged_at_tau = {w["wallet_h"] for w in M1.mech_wallets(snap)}
    assert wh(6) in flagged_at_tau and wh(7) not in flagged_at_tau      # M1 at tau alone would miss wallet 7
    # before graduation + 3 completed minutes R1 has 2 distinct minutes only
    assert wh(1) not in Q.ca_features(ds.asof(m, grid_t(M, 4)))["cohort"]
    assert wh(1) in Q.ca_features(ds.asof(m, grid_t(M, 6)))["cohort"]
    # no B1 rows: not ok and permanent
    assert Q.ca_features(ds.asof(fr[0].iloc[1]["mint"], grid_t(M, 51)))["why"] == "no_b1"


def test_universe_needs_slow_scanned_coin_with_b1():
    fr = q_frames(n=3)
    g = fr[0].copy()
    g.loc[1, "c_ts"] = g.loc[1, "g_ts"] - 3                 # instant graduate
    g.loc[2, "has_create"] = 0                              # creation not scanned
    tr = pd.concat([tape(r["mint"], [(int(r["g_ts"]) + 100, 1, True, 0.5)]) for _, r in g.iterrows()])
    ds = ds_of((g, fr[1], fr[2]), tr)
    why = [Q.in_universe(ds.asof(mm, ds.coin(mm).g + 700))[1] for mm in g["mint"]]
    assert why == ["", "instant_or_unknown_grad_delay", "creation_not_scanned"]
    assert Q.in_universe(ds_of(fr).asof(g.loc[0, "mint"], ds.coin(g.loc[0, "mint"]).g + 700)) == (False, "no_b1")


def test_mech_flags_match_m1_at_one_cutoff():
    fr = q_frames(n=1)
    m, g, M = m0_of(fr, 0)
    rng = np.random.default_rng(3)
    rows = []
    rows += [(M + 600 + 45 * i, 11, True, 0.1) for i in range(10)]                                  # MECH
    rows += [(M + 610 + 45 * i, 12, True, float(s)) for i, s in enumerate(rng.uniform(0.01, 1, 10))]  # sizes vary
    rows += [(M + 620 + 45 * i, 13, True, 0.1) for i in range(10)] + [(M + 900, 13, False, 0.05)]    # sells 5 %
    rows += [(M + 630 + 45 * i, 14, True, 0.1) for i in range(10)] + [(M + 900, 14, False, 0.2)]     # sells 20 %
    t = M + 640
    for gap in rng.exponential(60, 10):                                                             # gaps vary
        t += int(gap) + 1
        rows.append((t, 15, True, 0.1))
    rows += [(M + 650 + 45 * i, 16, True, 0.1) for i in range(5)]                                    # only 5 buys
    rows += [(M + 600 + int(x), 200 + i, bool(i % 3), float(s))                                      # background
             for i, (x, s) in enumerate(zip(rng.uniform(0, 600, 120), rng.uniform(0.05, 2, 120)))]
    ds = ds_of(fr, tape(m, rows))
    snap = ds.asof(m, grid_t(M, 30))
    want = {w["wallet_h"] for w in M1.mech_wallets(snap)}
    r = Q._rows(snap, snap.tau)
    uw, code = np.unique(r["w"], return_inverse=True)
    got = Q.mech_flags(r["ts"], code, r["buy"], r["sol"], r["price"], range(len(uw)), np.array([int(snap.tau)]))
    assert {int(uw[c]) for c in got} == want == {wh(11), wh(13)}


# =========================================================================== no lookahead


def _acc_market(n=4, seed=2):
    fr = q_frames(n=n, seed=seed, drifts=[0.002, -0.002, 0.001, 0.0][:n])
    rng = np.random.default_rng(seed)
    tapes = []
    for i, r in fr[0].iterrows():
        M = int(r["g_ts"]) // 60 * 60
        rows = accumulators(M, [1000 * i + k for k in range(5)], n=8)
        rows += [(M + int(x), 50_000 + int(rng.integers(0, 60)), True, float(s))
                 for x, s in zip(rng.uniform(60, 7000, 300), rng.uniform(0.05, 1, 300))]
        rows += [(M + 2400 + 60 * k + 5, 1000 * i + k, False, 0.1) for k in range(2)]               # cohort sells
        tapes.append(tape(r["mint"], rows))
    return fr, pd.concat(tapes, ignore_index=True)


def _garble_b1(tr: pd.DataFrame, mint: str, tau: float, rng) -> pd.DataFrame:
    tr = tr.copy()
    fut = (tr["mint"] == mint) & (tr["ts"] > tau)
    tr.loc[fut, "usol"] = (tr.loc[fut, "usol"] * rng.uniform(0.1, 50, fut.sum())).astype(np.int64)
    tr.loc[fut, "is_buy"] = rng.random(fut.sum()) < 0.5
    tr = tr.drop(index=tr.index[fut][rng.random(fut.sum()) < 0.3])
    new = tr[tr["mint"] == mint].head(20).copy()
    new["ts"] = (tau + rng.uniform(1, 3000, len(new))).astype(np.int64)
    new["slot"] = 10**7 + np.arange(len(new))
    new["wallet_h"] = new["wallet_h"].iloc[:3].tolist() * 6 + new["wallet_h"].iloc[:2].tolist()   # members sell
    new["is_buy"] = False
    return pd.concat([tr, new], ignore_index=True)


@pytest.mark.parametrize("seed", range(3))
def test_features_unchanged_by_future_garbage(seed):
    fr, tr = _acc_market(seed=seed)
    clean = ds_of(fr, tr)
    rng = np.random.default_rng(10 + seed)
    for m in clean.mints:
        M = int(clean.coin(m).g) // 60 * 60
        for minute in (8, 15, 33, 47, 61):
            tau = M + 60 * minute
            fr_d = _garble(fr, m, tau, rng)
            dirty = ds_of(fr_d, _garble_b1(tr, m, tau, rng))
            a, b = clean.asof(m, tau + 20), dirty.asof(m, tau + 20)
            for seed_ in (None, 0):
                fa, fb = Q.ca_features(a, shuffle_seed=seed_), Q.ca_features(b, shuffle_seed=seed_)
                assert (fa["count_A"], fa["share_A"], fa["cohort"]) == (fb["count_A"], fb["share_A"], fb["cohort"])
            coh = Q.ca_features(clean.asof(m, M + 60 * 6 + 20))["cohort"]
            assert Q.cohort_max_sellers(a, coh, M + 360) == Q.cohort_max_sellers(b, coh, M + 360)


def test_decisions_before_T_unchanged_by_future_garbage():
    fr, tr = _acc_market(seed=5)
    clean = ds_of(fr, tr)
    rng = np.random.default_rng(1)
    n = 0
    for m in clean.mints:
        T = clean.coin(m).g + 45 * 60
        dirty = ds_of(_garble(fr, m, T - C.DECISION_LAG_S, rng), _garble_b1(tr, m, T - C.DECISION_LAG_S, rng))
        for p in Q.GRID[:2] + Q.SHUFFLE_GRID[:1]:
            a = C.run_trades(clean, Q.strategy, p, Q.CFG, mints=[m])
            b = C.run_trades(dirty, Q.strategy, p, Q.CFG, mints=[m])
            assert a.loc[a["t_dec"] <= T, "t_dec"].tolist() == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n += int((a["t_dec"] <= T).sum())
    assert n > 0


# =========================================================================== entry and exits


def test_entry_window_share_and_b1():
    fr = q_frames(n=4)
    tapes = []
    for i, r in fr[0].iterrows():
        M = int(r["g_ts"]) // 60 * 60
        if i == 2:
            continue                                                           # no B1 rows
        start = 70 if i == 1 else 1                                            # 3rd buy only after 60 min
        rows = accumulators(M, [10 * i + k for k in range(3)], start_min=start, every=(1, 1, 1), n=4, sol=0.2)
        if i == 3:
            rows.append((M + 90, 999, True, 100.0))                           # one big one-off buyer: share < 0.2
        tapes.append(tape(r["mint"], rows))
    ds = ds_of(fr, pd.concat(tapes, ignore_index=True))
    mints = list(fr[0]["mint"])
    t0 = C.run_trades(ds, Q.strategy, Q.make_params(3, 0.0, "E2"), Q.CFG)
    assert sorted(t0["mint"]) == sorted([mints[0], mints[3]])
    assert ((t0["age_dec_s"] >= 600) & (t0["age_dec_s"] < 660)).all()       # the first decision at age >= 10 min
    t2 = C.run_trades(ds, Q.strategy, Q.make_params(3, 0.2, "E2"), Q.CFG)
    assert list(t2["mint"]) == [mints[0]]
    t5 = C.run_trades(ds, Q.strategy, Q.make_params(5, 0.0, "E2"), Q.CFG)
    assert t5.empty                                                          # only 3 accumulators


def _cohort_ds(sell_minutes: tuple[int, int], member=True, close_fns=None):
    fr = q_frames(n=1, close_fns=close_fns)
    m, g, M = m0_of(fr, 0)
    rows = accumulators(M, [1, 2, 3], every=(1, 1, 1), n=4, sol=0.2)
    sellers = (1, 2) if member else (50, 51)
    rows += [(M + 60 * sm + 15 + k, w, False, 0.05) for k, (w, sm) in enumerate(zip(sellers, sell_minutes))]
    return ds_of(fr, tape(m, rows)), m, M


def test_e1_cohort_exit_next_bar():
    ds, m, M = _cohort_ds((30, 30))
    t = C.run_trades(ds, Q.strategy, Q.make_params(3, 0.0, "E1"), Q.CFG)
    assert len(t) == 1 and t["reason"].iloc[0] == "signal:cohort"
    assert t["t_out"].iloc[0] == M + 60 * 31 + 20 + 30                     # decided when minute 30 completed
    for case in (dict(sell_minutes=(30, 31)), dict(sell_minutes=(30, 30), member=False)):
        ds2, _, _ = _cohort_ds(**case)
        t2 = C.run_trades(ds2, Q.strategy, Q.make_params(3, 0.0, "E1"), Q.CFG)
        assert t2["reason"].iloc[0] == "time"                                 # deadline g + 118 min
        assert t2["t_out"].iloc[0] - ds2.coin(m).g <= Q.EXIT_BY_AGE_S + 120
    coh = Q.ca_features(ds.asof(m, grid_t(M, 11)))["cohort"]
    assert Q.cohort_max_sellers(ds.asof(m, M + 60 * 30 + 59 + 20), coh, M + 660) == 0   # minute not completed
    assert Q.cohort_max_sellers(ds.asof(m, grid_t(M, 31)), coh, M + 660) == 2


def test_placebo_position_recomputes_its_cohort():
    ds, m, M = _cohort_ds((30, 30))
    t_dec = grid_t(M, 20)
    pv = C.PositionView(mint=m, t_dec=t_dec, t_in=t_dec + 30, entry_price=1e-7, tokens=1.0, sol_in=0.2, peak=1e-7,
                        bars_held=1, unrealized=0.0, exits=Q.EXITS, state={}, is_placebo=True)
    p = Q.make_params(3, 0.0, "E1")
    assert Q.exit_decision(ds.asof(m, grid_t(M, 30)), p, pv) is None
    assert Q.exit_decision(ds.asof(m, grid_t(M, 31)), p, pv).reason == "cohort"
    late = C.PositionView(**{**pv.__dict__, "t_dec": grid_t(M, 40), "t_in": grid_t(M, 40) + 30})
    assert Q.exit_decision(ds.asof(m, grid_t(M, 45)), p, late) is None     # cohort sells came before its decision


def test_e2_close_trail():
    p0 = X0 / Y0
    peak = p0 * 1.01 ** 50
    fn = {0: lambda j: p0 * 1.01 ** (j + 1) if j < 50 else 0.70 * peak}
    ds, m, M = _cohort_ds((200, 200), close_fns=fn)                          # no cohort sells inside the window
    t = C.run_trades(ds, Q.strategy, Q.make_params(3, 0.0, "E2"), Q.CFG)
    assert t["reason"].iloc[0] == "signal:trail_close"
    assert t["t_out"].iloc[0] == M + 60 * 51 + 20 + 30                     # bar 50 completed -> next-bar exit
    t1 = C.run_trades(ds, Q.strategy, Q.make_params(3, 0.0, "E1"), Q.CFG)
    assert t1["reason"].iloc[0] == "time"
    snap = ds.asof(m, grid_t(M, 50))
    assert not Q.close_trail_hit(snap, M + 60 * 11 + 50)
    assert Q.close_trail_hit(ds.asof(m, grid_t(M, 51)), M + 60 * 11 + 50)


# =========================================================================== shuffled-wallet control


def test_shuffle_breaks_identity_but_keeps_flow():
    fr = q_frames(n=2)
    m, g, M = m0_of(fr, 0)
    rows = []
    for mi in range(1, 41):
        rows += [(M + 60 * mi + 3 + k, k, True, 0.1) for k in range(5)]                     # 5 repeat buyers
        rows += [(M + 60 * mi + 20 + k, 1000 + 10 * mi + k, True, 0.1) for k in range(5)]  # 200 one-off buyers
    ds = ds_of(fr, tape(m, rows))
    snap = ds.asof(m, grid_t(M, 41))
    real, sh = Q.ca_features(snap), Q.ca_features(snap, shuffle_seed=0)
    assert real["count_A"] == 5 and sh["count_A"] < 5
    assert sh["denom"] == real["denom"]
    assert Q.ca_features(snap, shuffle_seed=0) == sh                          # deterministic
    # every wallet buys every minute: a per-minute permutation maps the minute onto itself, so nothing changes
    m2, _, M2 = m0_of(fr, 1)
    rows2 = [(M2 + 60 * mi + 3 + k, k, True, 0.1) for mi in range(1, 21) for k in range(6)]
    ds2 = ds_of(fr, pd.concat([tape(m, rows), tape(m2, rows2)], ignore_index=True))
    s2 = ds2.asof(m2, grid_t(M2, 21))
    a, b = Q.ca_features(s2), Q.ca_features(s2, shuffle_seed=0)
    assert a["count_A"] == b["count_A"] == 6 and a["share_A"] == pytest.approx(b["share_A"])


# =========================================================================== grid and decisions


def test_grid_is_the_queue_grid_plus_four_shuffles():
    assert len(Q.GRID) == 8 and len(Q.SHUFFLE_GRID) == 4
    assert {(p["K"], p["X"], p["exit"]) for p in Q.GRID} == {(k, x, e) for k in (3, 5) for x in (0.0, 0.2)
                                                             for e in ("E1", "E2")}
    assert all(p["exit"] == "E2" and p["shuffle_seed"] == 0 for p in Q.SHUFFLE_GRID)
    hashes = {C.params_hash(p) for p in Q.GRID + Q.SHUFFLE_GRID}
    assert len(hashes) == 12
    for p in Q.GRID + Q.SHUFFLE_GRID:
        assert p["stop_pct"] == 0.30 and p["exit_by_age_s"] == 118 * 60 and p["version"] == Q.VERSION
    assert Q.CFG.exit_delay_bars == 1 and Q.CFG.entry_fill == "worst"


def _ev(n, coins, mean, mw2=None, ci_lo=None, pc=None):
    return {"n": n, "n_coins": coins, "mean": mean, "mean_without_top2": mean if mw2 is None else mw2,
            "ci90": None if ci_lo is None else [ci_lo, ci_lo + 0.1], "placebo": None if pc is None else {"mean_diff": pc}}


def _evals(default, overrides=None, shuffle=None):
    out = {}
    for p in Q.GRID:
        out[Q.config_key(p)] = default
    for p in Q.SHUFFLE_GRID:
        out[Q.config_key(p)] = shuffle or _ev(40, 30, -0.05)
    out.update(overrides or {})
    return out


def test_decide_train_rules():
    good = _ev(40, 30, 0.05, ci_lo=0.01, pc=0.03)
    k = lambda K, X, e: Q.config_key(Q.make_params(K, X, e))  # noqa: E731
    # every (K, X) qualifies identically: ties go to the larger K, then the larger X; candidate exit E2 on a tie
    d = Q.decide_train(_evals(good))
    assert d["verdict"] == "SHORTLISTED" and (d["K"], d["X"], d["candidate_exit"]) == (5, 0.2, "E2")
    assert d["twin"]["exit"] == "E1" and d["shuffle"]["K"] == 5 and d["shuffle"]["X"] == 0.2
    # the best CI lower bound wins, and E1 can be the candidate
    d = Q.decide_train(_evals(good, {k(3, 0.0, "E1"): _ev(40, 30, 0.08, ci_lo=0.04, pc=0.05)}))
    assert (d["K"], d["X"], d["candidate_exit"]) == (3, 0.0, "E1")
    # identity: the shuffled control beats the real rule -> that (K, X) does not qualify
    bad_id = {Q.config_key(Q.make_shuffle_params(3, 0.0)): _ev(40, 30, 0.10)}
    d = Q.decide_train(_evals(good, {k(3, 0.0, "E1"): _ev(40, 30, 0.08, ci_lo=0.04, pc=0.05), **bad_id}))
    assert (d["K"], d["X"]) != (3, 0.0)
    # vacuous identity (< 10 shuffled trades) passes
    d = Q.decide_train(_evals(good, shuffle=_ev(3, 3, 0.5)))
    assert d["verdict"] == "SHORTLISTED" and all(r["identity_vacuous"] for r in d["rows"])
    # powered but nothing good -> NO_CONFIG; nothing powered -> UNDERPOWERED_TRAIN
    assert Q.decide_train(_evals(_ev(40, 30, -0.01, ci_lo=-0.05, pc=0.01)))["verdict"] == "NO_CONFIG"
    assert Q.decide_train(_evals(_ev(29, 29, 0.2, ci_lo=0.1, pc=0.1)))["verdict"] == "UNDERPOWERED_TRAIN"
    assert Q.decide_train(_evals(_ev(40, 19, 0.2, ci_lo=0.1, pc=0.1)))["verdict"] == "UNDERPOWERED_TRAIN"
    # a placebo that beats the rule disqualifies the exit
    assert Q.decide_train(_evals(_ev(40, 30, 0.05, ci_lo=0.01, pc=-0.01)))["verdict"] == "NO_CONFIG"


def test_val_confirm_and_combine_rules():
    assert Q.decide_val(_ev(4, 4, 0.3))["verdict"] == "UNDERPOWERED_VAL"
    assert Q.decide_val(_ev(10, 10, -0.01))["verdict"] == "FAIL_VAL"
    assert Q.decide_val(_ev(10, 10, 0.05, mw2=-0.01))["verdict"] == "FAIL_VAL"
    assert Q.decide_val(_ev(10, 10, 0.05))["verdict"] == "SELECTED_UNDERPOWERED"
    assert Q.decide_val(_ev(15, 15, 0.05))["verdict"] == "SELECTED"
    ok = lambda i, v=True: {"id": i, "pass": v}  # noqa: E731
    base = {"auto_rejections": [], "criteria": [ok(i) for i in range(1, 9)] + [ok(9, None), ok(10)]}
    vac = Q.q8_extras(_ev(20, 20, 0.1), _ev(5, 5, 0.5))
    assert vac[0]["pass"] is None and Q.combine_verdict(base, vac) == "PASS"      # vacuous: non-blocking
    assert Q.combine_verdict(base, Q.q8_extras(_ev(20, 20, 0.1), _ev(20, 20, 0.2))) == "FAIL"
    assert Q.combine_verdict(base, Q.q8_extras(_ev(20, 20, 0.1), _ev(20, 20, 0.0))) == "PASS"
    assert Q.combine_verdict(base, Q.q8_extras(_ev(20, 20, None), _ev(20, 20, 0.0))) == "INCOMPLETE"
    under = {**base, "criteria": [ok(1, False)] + base["criteria"][1:]}
    assert Q.combine_verdict(under, vac) == "UNDERPOWERED"
    cens = {**base, "criteria": base["criteria"][:-1] + [ok(10, False)]}
    assert Q.combine_verdict(cens, vac) == "INCOMPLETE"
    assert Q.combine_verdict({**base, "auto_rejections": ["x"]}, vac) == "REJECTED"
    doc = lambda v, n, mean: {"verdict": {"verdict": v}, "configs": {"candidate": {"n": n, "mean": mean}}}  # noqa
    assert Q.confirm_allowed(doc("FAIL", 30, 0.01))[0] and Q.confirm_allowed(doc("FAIL", 3, -0.5))[0]
    assert not Q.confirm_allowed(doc("FAIL", 30, -0.01))[0] and not Q.confirm_allowed(doc("REJECTED", 3, 0.5))[0]


# =========================================================================== stages


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Q8", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Q8 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Q.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Q.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_up: int, n_down: int, seed: int) -> C.Dataset:
    """Up coins: 6 conviction accumulators (irregular, never sell) and a rising price. Down coins: many one-off
    buyers (no repeat buyer, so the real rule never enters; the shuffled control does) and a falling price."""
    n = n_up + n_down
    rng = np.random.default_rng(seed)
    up = set(rng.permutation(n)[:n_up].tolist())
    fr = q_frames(n=n, seed=seed, t0=t0, drifts=[0.005 if i in up else -0.004 for i in range(n)])
    tapes = []
    for i, r in fr[0].iterrows():
        M = int(r["g_ts"]) // 60 * 60
        rows = []
        if i in up:
            for k in range(6):
                t = M + 60 + int(rng.integers(0, 50))
                while t < M + 3600:
                    rows.append((t, 10_000 * i + k, True, float(rng.uniform(0.12, 0.3))))
                    t += int(rng.integers(60, 240))
            rows += [(M + 60 * mi + 30, 10_000 * i + 100 + mi, True, 0.1) for mi in range(1, 60)]
        else:
            rows += [(M + 60 * mi + 5 + 7 * k, 10_000 * i + 100 + 4 * mi + k, True, 0.2)
                     for mi in range(1, 60) for k in range(4)]
        tapes.append(tape(r["mint"], rows))
    return ds_of(fr, pd.concat(tapes, ignore_index=True), split)


def test_b1_gate_refuses_every_stage_cleanly(st, tmp_path):
    fr = q_frames(n=4)
    with pytest.raises(Q.Q8Refused, match="B1 not ready.*no B1 rows"):
        _run("train", st, ds_of(fr))
    r = fr[0].iloc[0]
    one = tape(r["mint"], [(int(r["g_ts"]) + 100, 1, True, 0.5)])
    with pytest.raises(Q.Q8Refused, match=r"B1 covers 1/4"):
        _run("train", st, ds_of(fr, one))
    assert not st.ledger.exists() or not json.loads(st.ledger.read_text())["runs"]   # nothing ran, nothing logged
    assert not (st.out / "prereg.lock").exists()
    # the FLOW path: no b1_trades.parquet
    for name, df in zip(("graduates", "b2_coins", "b2_bars"), fr):
        df.to_parquet(st.flow / f"{name}.parquet")
    cov = Q.b1_coverage("train", flow=st.flow)
    assert not cov["b1_present"] and "does not exist" in Q.b1_problems(cov)[0]


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 6, 4, 1)
    with pytest.raises(Q.Q8Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Q8.json").exists()
    with pytest.raises(Q.Q8Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; q8's ``env=`` drives q8's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(Q.Q8Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: 12 configs, identity, shortlist of the pair + the shuffled control
    tr = _run("train", st, market("train", T0, 36, 36, 1))
    assert set(tr["configs"]) == {Q.config_key(p) for p in Q.GRID + Q.SHUFFLE_GRID}
    dec = tr["decision"]
    assert dec["verdict"] == "SHORTLISTED" and dec["shortlist_written"], dec
    for row in dec["rows"]:
        assert row["identity_vacuous"] or row["identity_diff"] > 0
    assert all(e["by_class"] for e in tr["configs"].values() if e["n"])
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"].startswith("Q8")) == 12
    assert led["n_trials_total"] == 2575 + 12
    with pytest.raises(Q.Q8Refused, match="final"):
        _run("train", st, market("train", T0, 4, 4, 1))                     # a decision on complete TRAIN is final
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Q.Q8Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Q8 test prereg\n")
    with pytest.raises(Q.Q8Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    with pytest.raises(Q.Q8Refused, match="before TEST"):
        _check("confirm", st, env=env_all)
    sl = (st.sl / "Q8-shuffle.json").read_text()
    (st.sl / "Q8-shuffle.json").unlink()
    with pytest.raises(Q.Q8Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Q8-shuffle.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 20, 2))
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"candidate", "twin", "shuffle"}
    assert va["identity"]["diff"] > 0
    with pytest.raises(Q.Q8Refused, match="VAL already ran"):
        _check("val", st)
    with pytest.raises(Q.Q8Refused, match="TRAIN is closed"):
        _check("train", st, rerun_reason="x")
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 20, 20, 3)
    with pytest.raises(Q.Q8Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert [c["id"] for c in te["verdict"]["q8_extras"]] == ["Q8.1"]
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Q.Q8Refused, match="one test look"):
        _check("test", st, env=env_all)                                   # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] == "test"} == {"Q8", "Q8-shuffle"}
    assert led["n_trials_total"] == 2575 + 12                           # later stages add no trial
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 30, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(Q.Q8Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 10, 6, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 8, 8, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Q.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG" and doc["event_counts"]["universe_alive_10_60"] == 16
    for e in doc["configs"].values():
        assert "mean" not in e and "ci90" not in e and "placebo" not in e and "reasons" not in e
        assert e["returns"].startswith("hidden")
    assert sum(e["n"] for e in doc["configs"].values()) > 0
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    assert not list(st.out.glob("*_trades.csv"))


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_real_train_refuses_without_b1(tmp_path, monkeypatch, capsys):
    if (C.flow_dir() / "b1_trades.parquet").exists():
        pytest.skip("B1 exists: the refusal no longer applies")
    out = tmp_path / "Q8"
    out.mkdir()
    shutil.copy(Q.OUT_DIR / "PREREG.md", out / "PREREG.md")
    monkeypatch.setattr(Q, "OUT_DIR", out)
    monkeypatch.setattr(Q.run_stage, "__kwdefaults__", {**Q.run_stage.__kwdefaults__, "out_dir": out})
    monkeypatch.setattr(Q.check_prereqs, "__defaults__", (out,))
    assert Q.main(["--stage", "train"]) == 2
    assert "B1 not ready" in capsys.readouterr().err
    assert not (out / "prereg.lock").exists() and not (out / "train.json").exists()

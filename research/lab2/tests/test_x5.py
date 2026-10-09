"""Tests for research/lab2/x5.py (R1, the market regime gate): window and gate arithmetic on hand-built records, the
pool and coverage rules, the traded coin's exclusion, no lookahead (all data after a cutoff garbled), the gate as an
exact filter of the host, the model check, the pre-registered decision rules, and the stages end to end with every
refusal.

Scale: the window / gate arithmetic and the coverage rules are tested at the registered constants. The stage tests
shrink the time scale (N = 30 min, a 6-hour baseline, SLACK 30 min, >= 3 SV records) so a synthetic market of a few hundred coins
covers the warm-up; the stage mechanics do not depend on the time scale."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import x5 as X
from conftest import V0, VALID_ALL as VALID, real_flow_available
from test_m1 import coin_bars, full

SOL = C.SolUsd(fallback=100.0)
PERIOD = 3 * 3600                     # synthetic regimes: hot 00-03, 06-09, 12-15, 18-21 UTC; cold otherwise
LIFE_MIN = 100                        # an active synthetic coin trades for its first 100 minutes


def hot(ts: float) -> bool:
    return (int(ts) // PERIOD) % 2 == 0


# =========================================================================== a synthetic market with regimes


def _grad_row(mint: str, pool: str, g: int, i: int, delay: int = 3) -> dict:
    return {"mint": mint, "g_slot": 1000 + i, "g_ts": g, "c_slot": 900 + i, "c_ts": g - delay, "has_create": 1,
            "completer": f"COMP{i}", "rsol_complete": 85.005, "creator": f"CR{mint}", "create_user": f"CU{mint}",
            "name": f"N{i}", "symbol": f"S{mint[-9:]}", "uri": "", "is_mayhem": 0, "curve_quote_mint": "1" * 32,
            "token_program": "Tokenkeg", "vsol0": 30.0, "curve_buy_sol": 90.0, "curve_sell_sol": 5.0,
            "curve_buy_tok": 8e8, "curve_sell_tok": 1e7, "curve_n_buys": 50, "curve_n_sells": 5, "curve_n_buyers": 40,
            "curve_n_sellers": 4, "curve_top1_buy_sol": 30.0, "curve_top3_buy_sol": 60.0, "completer_sol": 10.0,
            "completer30": f"COMP{i}", "l_buy_sol": 40.0, "l_n_buyers": 12, "z_n_buyers": 2, "z_buy_tok": 1e8,
            "sn60_n_buyers": 5, "creator_buy_sol": 1.0, "first20_buy_sol": 20.0, "pool": pool, "pool_slot": 1001 + i,
            "pool_ts": g + 2, "pool_quote_mint": C.WSOL, "pool_creator": "PC", "pool_base0": 206.9e6,
            "pool_quote0": 84.990359, "n_pools": 1, "grad_delay_s": float(delay), "sol_quoted": True,   # X0 = x0 + v
            "mayhem": False}


def _coin_row(mint: str, pool: str, g: int, factory: bool = True) -> dict:
    top = [[f"WA{mint}", 20.0, 0.0], [f"WB{mint}", 8.0, 0.0]] if factory else \
        [[f"W{j}{mint}", 2.0, 0.0] for j in range(10)]
    return {"pool": pool, "mint": mint, "g_ts": g, "virt_sol": V0, "n_chunks": 4, "w_exact": True,
            "w120_buy_sol": 30.0, "w120_sell_sol": 3.0, "w120_n_buyers": 9 if factory else 40, "w120_n_sellers": 2,
            "w300_buy_sol": 50.0, "w300_sell_sol": 9.0, "w300_n_buyers": 15, "w300_n_sellers": 6,
            "w120_top10": json.dumps(top), "w300_top10": json.dumps(top), "agent_plan_rule": False,
            "agent_present": False, "agent_wallet": "", "agent_slices": 0, "agent_sol": 0.0,
            "agent_median_gap": math.nan, "agent_gap_cv": math.nan, "agent_gap_band_share": math.nan,
            "agent_first_offset_s": math.nan, "agent_known_at": math.nan,
            "w120_top5_share_ex_agent": 28.0 / 30.0 if factory else 0.33, "grad_delay_s": 3.0}


def _coin_bars(mint: str, pool: str, g: int, active: bool, drift: float, rng, noise: float = 0.8) -> list[dict]:
    """Per-minute base volume follows the CURRENT regime (2.5 SOL a side in hot minutes, 0.6 in cold ones)."""
    m0 = g // 60 * 60
    ts = m0 + 60 * np.arange(186)
    d = np.array([drift if hot(t) else -drift for t in ts])
    vbs = np.array([2.5 if hot(t) else 0.6 for t in ts])
    dX = rng.normal(d, noise)
    X_, y = 84.990359, 206.9e6
    k = X_ * y
    rows = []
    for j in range(186):
        if (not active and j > 0) or j >= LIFE_MIN:
            break                                       # dead at once, or dies after LIFE_MIN minutes
        X1 = max(X_ + float(dX[j]), 20.0)
        y1 = k / X1
        p0, p1 = X_ / y, X1 / y1
        net = X1 - X_
        vb = float(vbs[j])
        rows.append({"minute_ts": int(ts[j]), "n_buys": 5, "n_sells": 3, "n_dust": 0,
                     "buy_sol": max(net, 0.0) + vb, "sell_sol": max(-net, 0.0) + vb,
                     "buy_tok": max(y - y1, 0.0), "sell_tok": max(y1 - y, 0.0), "n_buyers": 4, "n_sellers": 3,
                     "top5_buy_sol": vb, "open": p0, "high": max(p0, p1) * 1.005, "low": min(p0, p1) * 0.995,
                     "close": p1, "x_close": X1 - V0, "y_close": y1, "mint": mint, "pool": pool, "g_ts": g,
                     "minute_idx": j, "agent_buy_sol": 0.0, "price_repaired": 0})
        X_, y = X1, y1
    return rows


def regime_market(t_start: float, t_end: float, seed: int, *, gap_hot: int = 150, gap_cold: int = 450,
                  drift: float = 0.3, p_hot: float = 0.9, p_cold: float = 0.4, tag: str = "R"):
    """Graduations every gap_hot s in hot hours and gap_cold s in cold ones; a coin is active (trades every minute)
    with p_hot / p_cold; every active coin's pricing reserve drifts +drift SOL a minute in hot hours and -drift in
    cold ones (a negative ``drift`` reverses the regime effect). FACTORY class, so M1 skips them at once."""
    rng = np.random.default_rng(seed)
    grads, coins, bars = [], [], []
    t, i = float(t_start), 0
    while t < t_end:
        g = int(t) + int(rng.integers(0, 30))
        mint, pool = f"{tag}{seed}M{i:05d}pump", f"{tag}{seed}P{i:05d}"
        grads.append(_grad_row(mint, pool, g, i))
        coins.append(_coin_row(mint, pool, g))
        active = rng.random() < (p_hot if hot(g) else p_cold)
        bars.extend(_coin_bars(mint, pool, g, active, drift, rng))
        t += gap_hot if hot(t) else gap_cold
        i += 1
    return pd.DataFrame(grads), pd.DataFrame(coins), pd.DataFrame(bars)


def ds_of(frames, split: str) -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def cat(*frames):
    return tuple(pd.concat([f[i] for f in frames], ignore_index=True) for i in range(3))


@pytest.fixture
def small(monkeypatch):
    """Shrink the time scale for stage-level tests (see the module docstring)."""
    monkeypatch.setattr(X, "WINDOW_S", 1800.0)
    monkeypatch.setattr(X, "BASE_N", 24)
    monkeypatch.setattr(X, "SLACK_S", 1800.0)
    monkeypatch.setattr(X, "SV_MIN_RECORDS", 3)              # a 30-min window of cold hours holds ~4 graduates
    monkeypatch.setattr(X, "STRESS", {"costs_x1.5": X.FILL.stressed(1.5)})


def manual_regime(S: np.ndarray, known: np.ndarray | None = None, sig: str = "GR", k0: int = 1000) -> X.Regime:
    """A Regime whose GR counts are given directly (S per hour = cnt * 3600 / N)."""
    cnt = np.asarray(S, float) * X.WINDOW_S / 3600.0
    n = len(cnt)
    kn = np.ones(n, bool) if known is None else np.asarray(known, bool)
    empty = X.Records([], [], [])
    z = np.zeros(n)
    return X.Regime(k0=k0, k1=k0 + n - 1, recs={s: empty for s in X.SIGNALS},
                    sums={s: (cnt if s == sig else z) for s in X.SIGNALS},
                    cnts={s: (cnt if s == sig else z) for s in X.SIGNALS},
                    known={s: (kn if s == sig else np.zeros(n, bool)) for s in X.SIGNALS})


# =========================================================================== grid and constants


def test_grid_is_twelve_trials_and_registered():
    assert len(X.GRID) == 9
    keys = [X.config_key(p) for p in X.GRID]
    assert len(set(keys)) == 9 and len({C.params_hash(p) for p in X.GRID}) == 9
    assert {k for k in keys if k.startswith("R0")} == {f"R0|{s}|q{q:g}" for s in X.SIGNALS for q in (0.5, 0.8)}
    assert {k for k in keys if k.startswith("M1")} == {f"M1|{s}|q0.5" for s in X.SIGNALS}
    assert len(X.GRID) + len(X.HOST_ORDER) + 1 == 12          # + 2 host baselines + the model check
    with pytest.raises(ValueError):
        X.make_params("M1", "GR", 0.8)
    with pytest.raises(ValueError):
        X.make_params("R0", "XX", 0.5)
    for p in X.GRID:                        # the host's own params travel verbatim inside every config
        assert p["host_params"] == X.HOST_PARAMS[p["x5_host"]]
        assert p["window_s"] == 7200.0 and p["baseline_n"] == 96 and p["step_s"] == 900
    assert X.R0_HOST == X.g1.R0_PARAMS and X.M1_HOST == X.m1.make_params(1.0, "rhythm+prec")
    assert X.FILL.exit_delay_bars == 1 and X.FILL.entry_fill == "worst" and X.FILL.exit_fill == "worst"


def test_history_splits_never_read_a_later_or_sealed_split():
    cen = C.Census.load() if (C.lab_data_dir() / "census.json").exists() else C.Census.empty()
    order = ["confirm", "train", "val", "test", "final_train", "final_val", "final_test"]
    own = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm"}
    for stage, hs in X.HISTORY_SPLITS.items():
        lo, hi = X.history_bounds(stage, cen)                       # contiguous (raises otherwise)
        if stage in own:
            assert max(order.index(s) for s in hs) == order.index(own[stage])
            assert hi == X.split_creation_bounds(own[stage], cen)[1]
    assert X.HISTORY_SPLITS["train"] == ("train",) and X.HISTORY_SPLITS["confirm"] == ("confirm",)
    assert "confirm" not in X.HISTORY_SPLITS["final"] and X.HISTORY_SPLITS["debug"] == ("final_train",)


# =========================================================================== windows, the gate, own-coin exclusion


def test_window_is_half_open_and_counts_exactly():
    s = 10_000.0
    r = X.Records([s - X.WINDOW_S, s - X.WINDOW_S + 1, s - 1, s, s + 1], [1, 2, 3, 4, 5], ["a", "b", "a", "c", "d"])
    sm, cn = r.window(np.array([s]))
    assert cn[0] == 3 and sm[0] == 2 + 3 + 4                       # (s - N, s]: s - N out, s in, s + 1 out
    own = r.own_window("a", np.array([s]))
    assert own[1][0] == 1 and own[0][0] == 3
    assert r.own_window("zzz", np.array([s])) is None


def test_gate_quantile_percentile_and_unknown():
    base = np.arange(1, 97, dtype=float)                           # 96 baseline points 1..96
    reg = manual_regime(np.r_[base, 60.0])
    k = reg.k1
    tau = k * X.STEP_S + 899                                       # any tau inside the current 15-min point
    st5, st8 = reg.state("GR", 0.5, tau, None), reg.state("GR", 0.8, tau, None)
    assert st5["state"] == "ON" and st5["thr"] == pytest.approx(np.quantile(base, 0.5))
    assert st8["state"] == "OFF" and st8["thr"] == pytest.approx(np.quantile(base, 0.8))
    assert st5["pct"] == pytest.approx(59.5 / 96) and st5["S"] == pytest.approx(60.0)
    assert reg.state("GR", 0.5, tau + 1, None)["state"] == "UNKNOWN"          # the next point is not computed
    assert reg.state("GR", 0.5, tau - X.STEP_S, None)["state"] == "UNKNOWN"   # its baseline starts before k0
    kn = np.ones(97, bool)
    kn[10] = False
    assert manual_regime(np.r_[base, 60.0], kn).state("GR", 0.5, tau, None)["state"] == "UNKNOWN"
    assert reg.state("AV", 0.5, tau, None)["state"] == "UNKNOWN"


def test_own_coin_is_removed_from_every_window():
    k0 = 2000
    pts = (np.arange(k0, k0 + 97) * X.STEP_S).astype(float)
    # 2 graduations of other coins in every 15 minutes, plus 40 of coin "ME" just before the last point
    ks = np.concatenate([np.repeat(pts - 1, 2), np.full(40, pts[-1] - 1)])
    ms = ["o%d" % i for i in range(2 * 97)] + ["ME"] * 40
    rec = X.Records(ks, np.ones(len(ks)), ms)
    sm, cn = rec.window(pts)
    reg = X.Regime(k0=k0, k1=k0 + 96, recs={s: rec for s in X.SIGNALS}, sums={s: sm for s in X.SIGNALS},
                   cnts={s: cn for s in X.SIGNALS}, known={s: np.ones(97, bool) for s in X.SIGNALS})
    tau = pts[-1] + 10
    assert reg.state("GR", 0.8, tau, "other")["state"] == "ON"      # 40 extra graduations make the market "hot"
    me = reg.state("GR", 0.8, tau, "ME")
    assert me["state"] == "ON" and me["S"] == pytest.approx(me["thr"])   # without ME it is exactly its baseline
    assert reg.values("GR", reg.k1, "ME")[-1] == pytest.approx(16 * 3600 / X.WINDOW_S)


# =========================================================================== pools and coverage (registered constants)


def test_coverage_masks_and_pools_follow_the_registered_rules():
    t0 = C.utc_ts("2026-10-01 00:00")
    tr = regime_market(t0, t0 + 20 * 3600, 3, gap_hot=600, gap_cold=600)
    early = regime_market(t0 - 12 * 3600, t0, 4, gap_hot=600, gap_cold=600, tag="E")    # CONFIRM-dated
    late = regime_market(C.utc_ts("2026-10-05 00:00"), C.utc_ts("2026-10-05 06:00"), 5, tag="L")   # VAL-dated
    G = pd.concat([tr[0], early[0], late[0]], ignore_index=True)
    ds = ds_of(tr, "train")
    reg = X.build_regime("train", ds, [ds], G, C.Census.empty())
    lo = C.SPLIT_BOUNDS["train"][0]
    first = {s: C.utc_ts(reg.meta["first_known_utc"][s]) for s in ("AV", "SV")}
    assert first["SV"] == lo + X.SLACK_S + X.WINDOW_S + X.SV_AGE_S                     # 08:30
    assert first["AV"] == lo + X.SLACK_S + X.WINDOW_S + C.B2_HORIZON_S                # 11:00
    # GR: structure from the earlier (CONFIRM-dated) graduates is in the pool, the VAL-dated ones are not
    gr = set(reg.recs["GR"].own)
    assert set(early[0]["mint"]) <= gr and not (set(late[0]["mint"]) & gr)
    s = reg.points()
    assert reg.known["GR"][(s >= t0 - 9 * 3600) & (s < t0)].all()     # before TRAIN: earlier graduates, s < 10-05
    # AV / SV come from the history datasets only
    assert set(reg.recs["SV"].own) == set(ds.mints) and set(reg.recs["AV"].own) <= set(ds.mints)
    # SV records are stamped g + 30 min; AV records at bar end, only for bars starting at age >= 10 min
    cd = ds.coin(ds.mints[0])
    assert reg.recs["SV"].own[cd.mint][0][0] == cd.g + X.SV_AGE_S
    av_k = reg.recs["AV"].own.get(cd.mint, (np.zeros(0),))[0]
    assert (av_k - 60 >= cd.g + X.AV_MIN_AGE_S).all()
    # a mayhem / non-SOL graduate never counts
    G2 = G.copy()
    G2.loc[G2["mint"] == tr[0]["mint"].iloc[0], "rsol_complete"] = 50.0
    reg2 = X.build_regime("train", ds, [ds], G2, C.Census.empty())
    assert tr[0]["mint"].iloc[0] not in reg2.recs["GR"].own


def test_end_of_pool_is_unknown():
    """Coins created after the pool's end are not in it, so points whose windows reach past the end are UNKNOWN."""
    t0 = C.utc_ts("2026-10-04 06:00")
    tr = regime_market(t0, C.utc_ts("2026-10-05 00:00"), 6, gap_hot=900, gap_cold=900)
    ds = ds_of(tr, "train")
    reg = X.build_regime("train", ds, [ds], tr[0], C.Census.empty())
    s = reg.points().astype(float)
    hi = C.SPLIT_BOUNDS["train"][1]
    assert not reg.known["GR"][s >= hi].any() and not reg.known["SV"][s - X.SV_AGE_S >= hi].any()
    assert not reg.known["AV"][s - X.AV_MIN_AGE_S >= hi].any()


# =========================================================================== no lookahead


def _garble_after(frames, s0: float, rng):
    """Every bar that ends after s0 and every graduate after s0 replaced by garbage; new graduates added after s0."""
    g, c, b = (x.copy() for x in frames)
    b = b.astype({k: "float64" for k in ("buy_sol", "sell_sol", "n_buyers", "n_sellers")})
    fut = b["minute_ts"] + 60 > s0
    for col in ("buy_sol", "sell_sol", "n_buyers", "n_sellers"):
        b.loc[fut, col] = rng.uniform(0, 1e4, fut.sum())
    px = rng.uniform(1e-9, 1e-3, fut.sum())
    b.loc[fut, "open"], b.loc[fut, "close"], b.loc[fut, "high"], b.loc[fut, "low"] = px, px * 2, px * 3, px / 3
    b.loc[fut, "y_close"] = rng.uniform(1e6, 1e9, fut.sum())
    b = b.drop(index=b.index[fut][rng.random(fut.sum()) < 0.3])
    extra = regime_market(s0 + 60, s0 + 4 * 3600, 99, gap_hot=60, gap_cold=60, tag="Z")
    return (pd.concat([g, extra[0]], ignore_index=True), pd.concat([c, extra[1]], ignore_index=True),
            pd.concat([b, extra[2]], ignore_index=True))


def test_regime_before_cutoff_unchanged_by_future_garbage(small):
    t0 = C.utc_ts("2026-10-01 00:00")
    fr = regime_market(t0, t0 + 24 * 3600, 7)
    ds = ds_of(fr, "train")
    reg = X.build_regime("train", ds, [ds], fr[0], C.Census.empty())
    s0 = t0 + 18 * 3600 + 7 * 60
    fg = _garble_after(fr, s0, np.random.default_rng(1))
    dsg = ds_of(fg, "train")
    regg = X.build_regime("train", dsg, [dsg], fg[0], C.Census.empty(), curve_hours=set(
        (fr[0]["g_ts"].to_numpy(np.int64) // 3600 * 3600).tolist()) | set(range(int(s0) // 3600 * 3600,
                                                                                int(s0) + 5 * 3600, 3600)))
    n_known = 0
    for tau in np.arange(t0 + 6 * 3600, s0 + 1, 300.0):
        for m in (ds.mints[0], ds.mints[len(ds) // 2], None):
            for sig in X.SIGNALS:
                a, b = reg.state(sig, 0.5, tau, m), regg.state(sig, 0.5, tau, m)
                assert a["state"] == b["state"] and a["S"] == b["S"] and a["thr"] == b["thr"], (sig, tau)
                n_known += a["state"] != "UNKNOWN"
    assert n_known > 100                                     # the comparison is not vacuous


def test_own_coin_garbage_never_moves_its_own_regime(small):
    t0 = C.utc_ts("2026-10-01 00:00")
    fr = regime_market(t0, t0 + 20 * 3600, 8)
    ds = ds_of(fr, "train")
    reg = X.build_regime("train", ds, [ds], fr[0], C.Census.empty())
    me = [m for m in ds.mints if len(reg.recs["AV"].own.get(m, ((),))[0]) > 50][-1]
    g, c, b = (x.copy() for x in fr)
    sel = b["mint"] == me
    b.loc[sel, "buy_sol"] = 1e5                                     # its own volume explodes
    b.loc[sel & (b["minute_idx"] > 0), "open"] = 1.0                 # and its price / alive state change
    dsg = ds_of((g, c, b), "train")
    regg = X.build_regime("train", dsg, [dsg], g, C.Census.empty())
    cd = ds.coin(me)
    moved = 0
    for tau in np.arange(cd.g, cd.g + 4 * 3600, 900.0):
        for sig in X.SIGNALS:
            a, z = reg.state(sig, 0.5, tau, me), regg.state(sig, 0.5, tau, me)
            assert a["state"] == z["state"] and (a["S"] is None or a["S"] == pytest.approx(z["S"]))
            o = regg.state(sig, 0.5, tau, None)
            moved += o["S"] is not None and a["S"] is not None and abs(o["S"] - a["S"]) > 1.0
    assert moved > 0                                   # for everyone else the garbage is visible (AV)


# =========================================================================== the gate is an exact filter of the host


def test_gated_r0_equals_host_trades_in_on_regime(small, tmp_ledger):
    t0 = C.utc_ts("2026-10-01 00:00")
    fr = regime_market(t0, t0 + 24 * 3600, 9)
    ds = ds_of(fr, "train")
    reg = X.build_regime("train", ds, [ds], fr[0], C.Census.empty())
    host = X._host_run("R0", "train", ds, ledger_path=tmp_ledger, shortlist_path=None)
    lab = X.label_states(reg, host.trades)
    for p in [q for q in X.GRID if q["x5_host"] == "R0"]:
        res = X._gated_run(p, "train", ds, reg, ledger_path=tmp_ledger, shortlist_path=None, n_placebo=2)
        on = lab[lab[X.state_col(p["signal"], p["q"])] == "ON"]
        got = res.trades.sort_values("mint").reset_index(drop=True)
        want = on.sort_values("mint").reset_index(drop=True)
        assert list(got["mint"]) == list(want["mint"]) and np.allclose(got["ret_net"], want["ret_net"])
        ev = X.evaluate(res, lab, B=200, hide=False, n_trials_total=None)
        assert ev["gate_consistent"] and ev["n"] == ev["host_states"].get("ON", 0)
        assert (len(res.placebo) > 0) == (len(res.trades) > 0) and set(res.stress) == {"costs_x1.5"}
        assert len(res.trades) > 0
    for sig in X.SIGNALS:
        assert (lab[X.state_col(sig, 0.5)] != "UNKNOWN").sum() > 30


def test_gated_m1_host_filters_m1_entries(small, tmp_ledger):
    """M1 fires on pure-bot coins (non-instant, so class OTHER); the gate keeps exactly the ON ones."""
    t0 = C.utc_ts("2026-10-01 00:00")
    g, c, b = regime_market(t0, t0 + 20 * 3600, 10)
    bots = g["mint"].iloc[240:292:2].tolist()          # graduated in the hot 12-15 h and the cold 15-18 h
    for m in bots:
        r = g[g["mint"] == m].iloc[0]
        g.loc[g["mint"] == m, "c_ts"] = int(r["g_ts"]) - 600
        c.loc[c["mint"] == m, "w120_top10"] = json.dumps([[f"W{j}{m}", 2.0, 0.0] for j in range(10)])
        b = pd.concat([b[b["mint"] != m], coin_bars(int(r["g_ts"]), m, r["pool"], buy=full(0.3))], ignore_index=True)
    ds = ds_of((g, c, b), "train")
    reg = X.build_regime("train", ds, [ds], g, C.Census.empty())
    host = X._host_run("M1", "train", ds, ledger_path=tmp_ledger, shortlist_path=None)
    assert len(host.trades) >= 10 and set(host.trades["mint"]) <= set(bots)
    lab = X.label_states(reg, host.trades)
    p = X.make_params("M1", "GR", 0.5)
    res = X._gated_run(p, "train", ds, reg, ledger_path=tmp_ledger, shortlist_path=None, n_placebo=2)
    ev = X.evaluate(res, lab, B=200, hide=False, n_trials_total=None)
    assert ev["gate_consistent"] and 0 < ev["n"] < len(host.trades)


# =========================================================================== model check and decision rules


def _obs(n: int, rho_sign: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.random(n)
    y = rho_sign * x + 0.1 * rng.normal(size=n)
    t = C.utc_ts("2026-10-02 00:00") + np.arange(n) * 600.0
    d = {"mint": [f"m{i}" for i in range(n)], "t": t, "age_min": 40.0, "realized60": y}
    for s in X.SIGNALS:
        d[f"pct_{s}"] = x
    return pd.DataFrame(d)


def test_model_check_rules():
    assert X.model_check(_obs(250, 1), B=100)["decision"] == "PASS"
    k = X.model_check(_obs(250, -1), B=100)
    assert k["decision"] == "KILL" and k["pass_signals"] == []
    assert X.model_check(_obs(150, 1), B=100)["decision"] == "UNDERPOWERED"
    o = _obs(250, 1)
    o["pct_GR"] = -o["pct_GR"]
    o.loc[o.index[:100], "pct_AV"] = None                                  # AV underpowered
    mc = X.model_check(o, B=100)
    assert mc["signals"]["GR"]["decision"] == "FAIL" and mc["signals"]["AV"]["decision"] == "UNDERPOWERED"
    assert mc["decision"] == "PASS" and mc["pass_signals"] == ["SV"]
    assert mc["signals"]["SV"]["rho_ci90_block"] is not None
    h = X.model_check(_obs(250, -1), hide=True)
    assert "rho" not in h["signals"]["GR"] and h["decision"] == "HIDDEN"


def _ev(p, n, coins, mean, mw2, pc, con, n_off=100, ci_lo=0.01, con_lo=0.0, cs=0.0):
    return {"config": X.config_key(p), "params_hash": C.params_hash(p), "n": n, "n_coins": coins, "mean": mean,
            "mean_without_top2": mw2, "ci90_block": (ci_lo, 0.2), "placebo": {"mean_diff": pc},
            "contrast": {"diff": con, "n_on": n, "n_off": n_off, "ci90_block": (con_lo, 0.3)}, "censored_share": cs}


def test_decide_train_edge_ranking_and_veto_fallback():
    P = {X.config_key(p): p for p in X.GRID}
    base = {k: _ev(p, 10, 10, -0.1, -0.1, -0.1, -0.1) for k, p in P.items()}
    d0 = X.decide_train(base, X.GRID)
    assert d0["verdict"] == "UNDERPOWERED_TRAIN" and not d0["shortlist"]
    ev = dict(base)
    ev["R0|GR|q0.5"] = _ev(P["R0|GR|q0.5"], 120, 100, 0.04, 0.03, 0.05, 0.10, ci_lo=0.005)
    ev["R0|SV|q0.8"] = _ev(P["R0|SV|q0.8"], 70, 60, 0.06, 0.05, 0.08, 0.15, ci_lo=0.02)
    ev["R0|AV|q0.5"] = _ev(P["R0|AV|q0.5"], 120, 100, 0.05, -0.01, 0.05, 0.10, ci_lo=0.03)   # top-2 dependent
    ev["M1|GR|q0.5"] = _ev(P["M1|GR|q0.5"], 61, 40, 0.09, 0.08, 0.1, 0.0, ci_lo=0.05)          # contrast 0
    d = X.decide_train(ev, X.GRID)
    assert d["verdict"] == "SHORTLISTED_EDGE" and d["track"] == "EDGE"
    assert d["ranked"] == ["R0|SV|q0.8", "R0|GR|q0.5"] and d["hosts"] == ["R0"]
    assert d["shortlist_hashes"] == [C.params_hash(P["R0|SV|q0.8"]), C.params_hash(P["R0|GR|q0.5"])]
    ev2 = dict(base)
    ev2["R0|AV|q0.5"] = _ev(P["R0|AV|q0.5"], 120, 100, -0.08, -0.09, 0.02, 0.07, n_off=90, con_lo=0.01)
    ev2["R0|GR|q0.5"] = _ev(P["R0|GR|q0.5"], 120, 100, -0.08, -0.09, 0.02, 0.09, n_off=90, con_lo=-0.02)
    ev2["R0|SV|q0.5"] = _ev(P["R0|SV|q0.5"], 120, 100, -0.08, -0.09, 0.02, 0.20, n_off=50, con_lo=0.1)  # < 60 OFF
    dv = X.decide_train(ev2, X.GRID)
    assert dv["verdict"] == "SHORTLISTED_VETO" and dv["ranked"] == ["R0|AV|q0.5"] and dv["track"] == "VETO"
    ev3 = dict(base)
    ev3["R0|GR|q0.5"] = _ev(P["R0|GR|q0.5"], 120, 100, -0.08, -0.09, 0.02, 0.01, n_off=90)
    assert X.decide_train(ev3, X.GRID)["verdict"] == "NO_CONFIG"


def test_decide_val_confirm_and_verdict_combination():
    good = {"config": "a", "params_hash": "h1", "n": 20, "mean": 0.05, "mean_without_top2": 0.02}
    weak = {"config": "b", "params_hash": "h2", "n": 8, "mean": 0.05, "mean_without_top2": 0.01}
    bad = {"config": "c", "params_hash": "h3", "n": 20, "mean": -0.05, "mean_without_top2": -0.06}
    d = X.decide_val({"rank1": bad, "rank2": good}, ["rank1", "rank2"], "EDGE")
    assert d["verdict"] == "SELECTED" and d["candidate_role"] == "rank2" and d["candidate_hash"] == "h1"
    assert X.decide_val({"rank1": weak}, ["rank1"], "EDGE")["verdict"] == "SELECTED_UNDERPOWERED"
    assert X.decide_val({"rank1": bad}, ["rank1"], "EDGE")["verdict"] == "FAIL_VAL"
    vok = {"verdict": "INCOMPLETE", "criteria": [{"id": 1, "pass": True}, {"id": 3, "pass": True}]}
    vbad = {"verdict": "FAIL", "criteria": [{"id": 1, "pass": False}, {"id": 3, "pass": True}]}
    sel = X.decide_val({"rank1": {**good, "veto_in_sample": vok}}, ["rank1"], "VETO")
    assert sel["verdict"] == "VETO_SELECTED" and sel["proceed"] and sel["candidate_role"] == "rank1"
    assert X.decide_val({"rank1": {**good, "veto_in_sample": vbad}}, ["rank1"], "VETO")["verdict"] == "VETO_FAIL_VAL"
    assert X.decide_val({"rank1": {**good, "veto_in_sample": {"verdict": "UNDERPOWERED"}}}, ["rank1"],
                        "VETO")["verdict"] == "VETO_UNDERPOWERED"
    # CONFIRM preconditions
    assert X.confirm_allowed({"track": "EDGE", "verdict": {"verdict": "UNDERPOWERED"},
                              "configs": {"candidate": {"n": 30, "mean": 0.01}}})[0]
    assert not X.confirm_allowed({"track": "EDGE", "verdict": {"verdict": "FAIL"},
                                  "configs": {"candidate": {"n": 30, "mean": -0.01}}})[0]
    assert X.confirm_allowed({"track": "EDGE", "verdict": {"verdict": "FAIL"},
                              "configs": {"candidate": {"n": 3, "mean": -0.5}}})[0]       # no evidence either way
    assert not X.confirm_allowed({"track": "EDGE", "verdict": {"verdict": "REJECTED"}, "configs": {}})[0]
    assert X.confirm_allowed({"track": "VETO", "verdict": {"verdict": "INCOMPLETE"}})[0]
    assert not X.confirm_allowed({"track": "VETO", "verdict": {"verdict": "FAIL"}})[0]
    # verdict combination
    def base(passes, rej=()):
        return {"auto_rejections": list(rej), "criteria": [{"id": i + 1, "pass": v} for i, v in enumerate(passes)]
                + [{"id": 9, "pass": None}, {"id": 10, "pass": True}]}
    ok8 = [True] * 8
    ex_ok = X.x5_extras({"contrast": {"diff": 0.1, "ci90_block": (0.02, 0.2), "n_on": 70, "n_off": 70},
                         "on_blocks": 8})
    assert [e["pass"] for e in ex_ok] == [True, True] and X.combine_verdict(base(ok8), ex_ok) == "PASS"
    assert X.combine_verdict(base(ok8, ["x"]), ex_ok) == "REJECTED"
    assert X.combine_verdict(base([False] + ok8[1:]), ex_ok) == "UNDERPOWERED"
    ex_blocks = X.x5_extras({"contrast": {"diff": 0.1, "ci90_block": (0.02, 0.2), "n_on": 70, "n_off": 70},
                             "on_blocks": 5})
    assert X.combine_verdict(base(ok8), ex_blocks) == "UNDERPOWERED"
    ex_ci = X.x5_extras({"contrast": {"diff": 0.1, "ci90_block": (-0.02, 0.2), "n_on": 70, "n_off": 70},
                         "on_blocks": 8})
    assert X.combine_verdict(base(ok8), ex_ci) == "FAIL"
    ex_none = X.x5_extras({"contrast": {"diff": 0.1, "ci90_block": (0.02, 0.2), "n_on": 70, "n_off": 5},
                           "on_blocks": 8})
    assert ex_none[0]["pass"] is None and X.combine_verdict(base(ok8), ex_none) == "INCOMPLETE"
    assert X.combine_verdict(base(ok8[:4] + [False] + ok8[5:]), ex_ok) == "FAIL"


def test_contrast_block_bootstrap():
    rng = np.random.default_rng(0)
    n = 400
    t = C.utc_ts("2026-10-02 00:00") + rng.uniform(0, 4 * 86400, n)
    on = rng.random(n) < 0.5
    r = np.where(on, 0.1, -0.1) + 0.05 * rng.normal(size=n)
    host = pd.DataFrame({"mint": [f"m{i}" for i in range(n)], "t_in": t, "ret_net": r})
    st = np.where(on, "ON", "OFF").astype(object)
    st[:20] = "UNKNOWN"
    c = X.contrast(host, st, B=300)
    assert c["n_unknown"] == 20 and c["n_on"] + c["n_off"] == n - 20
    assert c["diff"] == pytest.approx(0.2, abs=0.02) and c["ci90_block"][0] > 0.1
    c0 = X.contrast(host, np.where(rng.random(n) < 0.5, "ON", "OFF"), B=300)
    assert c0["ci90_block"][0] < 0 < c0["ci90_block"][1]


# =========================================================================== stages end to end


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "X5", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# X5 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, history, G, env=None, **kw):
    return X.run_stage(stage, out_dir=d.out, ds=ds, history=history, graduates=G, flow=d.flow, ledger_path=d.ledger,
                       shortlist_path=d.sl, B=200, n_placebo=2, env=env or {},
                       _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return X.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def test_train_kill_stops_x5(st, small):
    t0 = C.utc_ts("2026-10-01 00:00")
    fr = regime_market(t0, t0 + 36 * 3600, 11, drift=-0.3)        # hot markets LOSE: every signal ranks backwards
    ds = ds_of(fr, "train")
    doc = _run("train", st, ds, [ds], fr[0])
    mc = doc["model_check"]
    assert mc["decision"] == "KILL", mc
    assert all(mc["signals"][s]["n_obs"] >= X.MC_MIN_OBS and mc["signals"][s]["rho"] < 0 for s in X.SIGNALS)
    assert doc["decision"]["verdict"] == "KILLED_MODEL_CHECK" and "configs" not in doc and "hosts" not in doc
    assert doc["overall"].startswith("KILLED")
    runs = json.loads(st.ledger.read_text())["runs"]
    assert [r["hypothesis"] for r in runs] == ["X5-modelcheck"]          # no P&L was run
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(X.X5Refused, match="dead"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(X.X5Refused, match="final"):
        _run("train", st, ds, [ds], fr[0])                               # a decision on complete TRAIN is final
    assert _run("train", st, ds, [ds], fr[0], rerun_reason="test: data fix")["decision"]["verdict"] == \
        "KILLED_MODEL_CHECK"
    assert list(st.out.glob("train_prev_*.json"))


def test_underpowered_model_check_and_provisional(st, small):
    t0 = C.utc_ts("2026-10-01 00:00")
    fr = regime_market(t0, t0 + 12 * 3600, 12)
    ds = ds_of(fr, "train")
    with pytest.raises(X.X5Refused, match="incomplete"):
        _run("train", st, ds, [ds], fr[0], _skip_coverage=False)
    doc = _run("train", st, ds, [ds], fr[0], _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists()
    assert doc["decision"]["verdict"] == "UNDERPOWERED_MODEL_CHECK"
    with pytest.raises(X.X5Refused, match="no TRAIN result"):
        _check("val", st)
    doc2 = _run("train", st, ds, [ds], fr[0])
    assert doc2["decision"]["verdict"] == "UNDERPOWERED_MODEL_CHECK"
    with pytest.raises(X.X5Refused, match="UNDERPOWERED_MODEL_CHECK"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, small, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; x5's ``env=`` drives x5's own checks
        monkeypatch.setenv(k, "1")
    D = lambda s: C.utc_ts(s)                                                     # noqa: E731
    kw = {"drift": 0.6}                                  # a strong regime effect: the machinery must find it
    F_tr = regime_market(D("2026-10-01 00:00"), D("2026-10-02 12:00"), 21, **kw)
    F_va = regime_market(D("2026-10-04 16:00"), D("2026-10-05 18:00"), 22, tag="V", **kw)
    F_te = regime_market(D("2026-10-06 04:00"), C.FINAL_LO, 23, gap_hot=300, gap_cold=900, tag="T", **kw)
    F_co = regime_market(D("2026-09-20 00:00"), D("2026-09-22 12:00"), 24, gap_hot=300, gap_cold=900, tag="C", **kw)
    F_fi = regime_market(D("2026-10-07 10:00"), C.FINAL_LO + 14 * 3600, 25, gap_hot=300, gap_cold=900, tag="F", **kw)
    G = pd.concat([f[0] for f in (F_tr, F_va, F_te, F_co, F_fi)], ignore_index=True)
    with pytest.raises(X.X5Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: model check PASS, 2 hosts + 9 gated configs, the EDGE shortlist (top 2) and the host shortlist
    ds_tr = ds_of(F_tr, "train")
    tr = _run("train", st, ds_tr, [ds_tr], G)
    ps = tr["model_check"]["pass_signals"]
    assert tr["model_check"]["decision"] == "PASS" and "GR" in ps
    assert set(tr["configs"]) == {X.config_key(p) for p in X.GRID if p["signal"] in ps}   # failed signals never run
    assert set(tr["grid_run"]) == set(tr["configs"]) and set(tr["hosts"]) == {"R0", "M1"}
    assert all(e["gate_consistent"] for e in tr["configs"].values())
    assert tr["decision"]["verdict"] == "SHORTLISTED_EDGE" and tr["decision"]["shortlist_written"]
    assert len(tr["decision"]["ranked"]) == 2 and tr["decision"]["hosts"] == ["R0"]
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    assert (st.sl / "X5.json").exists() and (st.sl / "X5.host-R0.json").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if C.hypothesis_family(v["hypothesis"]) == "X5") == \
        3 + 3 * len(ps)                                     # model check + 2 hosts + 3 gated per passing signal
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(X.X5Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# X5 test prereg\n")
    for stage in ("test", "confirm", "final"):
        with pytest.raises(X.X5Refused, match="no VAL result"):
            _check(stage, st, env=env_all)
    hs = (st.sl / "X5.host-R0.json").read_text()
    (st.sl / "X5.host-R0.json").unlink()
    with pytest.raises(X.X5Refused, match="host shortlist"):
        _check("val", st)
    (st.sl / "X5.host-R0.json").write_text(hs)
    # ---- VAL (history: TRAIN-dated coins just before it + VAL)
    ds_va, pre_va = ds_of(F_va, "val"), ds_of(F_va, "train")
    va = _run("val", st, ds_va, [ds_va, pre_va], G)
    assert va["decision"]["verdict"] == "SELECTED" and va["track"] == "EDGE"
    assert set(va["configs"]) == {"rank1", "rank2"} and set(va["hosts"]) == {"R0"}
    with pytest.raises(X.X5Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_te, pre_te = ds_of(F_te, "test"), ds_of(F_te, "val")
    with pytest.raises(X.X5Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_te, [ds_te, pre_te], G)
    te = _run("test", st, ds_te, [ds_te, pre_te], G, env=env_all)
    assert te["verdict"]["track"] == "EDGE" and {c["id"] for c in te["verdict"]["edge"]["x5_extras"]} == \
        {"X5.1", "X5.2"} and te["verdict"]["veto"] is not None
    assert set(te["configs"]) == {"candidate"}
    with pytest.raises(X.X5Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(X.X5Refused, match="one test run"):
        _check("test", st, env=env_all)                                   # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] == "test"} == {"X5", "X5.host-R0"}
    # ---- CONFIRM (powered, own pool with its warm-up): the machinery CAN say PASS
    ds_co = ds_of(F_co, "confirm")
    co = _run("confirm", st, ds_co, [ds_co], G, env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    # ---- FINAL
    ds_fi, pre_fi = ds_of(F_fi, "final"), ds_of(F_fi, "test")
    fi = _run("final", st, ds_fi, [ds_fi, pre_fi], G, env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(X.X5Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(X.X5Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(X.X5Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st, small):
    t0 = C.utc_ts("2026-10-01 00:00")
    fr = regime_market(t0, t0 + 20 * 3600, 13)
    ds = ds_of(fr, "train")
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = X.run_stage("debug", out_dir=st.out, ds=ds, history=[ds], graduates=fr[0], flow=st.flow,
                      ledger_path=st.ledger, B=200, n_placebo=2, env={})
    assert doc["decision"]["verdict"] == "DEBUG" and doc["model_check"]["decision"] == "HIDDEN"
    assert all("rho" not in d for d in doc["model_check"]["signals"].values())
    for e in list(doc["configs"].values()) + list(doc["hosts"].values()):
        for k in ("mean", "ci90", "placebo", "reasons", "contrast", "stress", "portfolio", "veto_in_sample"):
            assert k not in e
        assert e["returns"].startswith("hidden")
    assert "regime_diagnostics" not in doc
    # the debug pool is the census TRAIN third alone: AV / SV never warm up, GR (structure) does
    by = {k: e for k, e in doc["configs"].items()}
    assert all(by[k]["n"] == 0 for k in by if "|AV|" in k or "|SV|" in k)
    assert by["R0|GR|q0.5"]["n"] > 0 and doc["signals_per_day"]["R0|GR|q0.5"] > 0
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    assert not (st.out / "prereg.lock").exists()


# =========================================================================== real census data (skipped without it)


@pytest.mark.skipif(not real_flow_available(), reason="FLOW tables not available")
def test_real_census_train_third_regime_pools():
    ds = C.load("final_train")
    cen = C.Census.load()
    f = C.flow_dir()
    G = C._read_parquet(f / "graduates.parquet")
    ch = C.completeness_from_flow(f, with_bar_hours=False).curve_hours
    reg = X.build_regime("debug", ds, [ds], G, cen, ch)
    lo = float(C.FINAL_LO)          # coverage starts late in the 12.5-h third; its 24-h baseline never does
    assert C.utc_ts(reg.meta["first_known_utc"]["SV"]) >= lo + X.SLACK_S + X.WINDOW_S + X.SV_AGE_S
    assert C.utc_ts(reg.meta["first_known_utc"]["AV"]) >= lo + X.SLACK_S + X.WINDOW_S + C.B2_HORIZON_S
    share = X._known_share_of_coins(ds, reg)
    assert share["GR"] > 0.5 and share["AV"] == 0 and share["SV"] == 0
    g = C._normalize_graduates(G, cen).set_index("mint")
    assert (g.loc[list(reg.recs["GR"].own), "created_for_split"] < cen.train_hi + 1).all()
    # GR before a cutoff does not change when every later graduate is removed
    s0 = float(ds.coins["g_ts"].median())
    reg_cut = X.build_regime("debug", ds, [ds], G[G["g_ts"] <= s0], cen, ch)
    for m in ds.mints[::25]:
        for tau in (ds.coin(m).g + 1800.0, ds.coin(m).g + 5400.0):
            if tau <= s0:
                assert reg.state("GR", 0.5, tau, m) == reg_cut.state("GR", 0.5, tau, m)

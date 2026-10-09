"""Tests for research/lab2/y2.py: eligibility and components (NULL never 0), the organic rank math, the causal
reference pool (no future graduate, no later split, never the coin itself), the single g + 30 min decision, the
exits, the pre-registered decision rules, the stage pipeline with every refusal, and no lookahead on real census
graduates."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import y2 as Y
from conftest import V0, make_frames, real_flow_available
from conftest import VALID_ALL as VALID
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
DELAYS = (30.0, 120.0, 240.0, 600.0, 1200.0)


# =========================================================================== fixtures


def drift_bars(g: int, mint: str, pool: str, rate: float, n: int = N_MIN, flow: float = 1.5,
               dead_from: int | None = None) -> pd.DataFrame:
    """Minute bars whose pricing reserve grows as X0 * exp(rate * minute) (price ~ exp(2 rate t)), with ``flow`` SOL
    of extra buying and selling a minute (alive). No wicks. ``dead_from``: no trade from that minute on."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    k = X * y
    rows = []
    for j in range(n):
        if dead_from is not None and j >= dead_from:
            break
        X1 = X0 * math.exp(rate * (j + 1))
        y1 = k / X1
        p0, p1 = X / y, X1 / y1
        dX = X1 - X
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 5, "n_sells": 3, "n_dust": 0,
                     "buy_sol": max(dX, 0.0) + flow, "sell_sol": max(-dX, 0.0) + flow,
                     "buy_tok": max(y - y1, 0.0), "sell_tok": max(y1 - y, 0.0), "n_buyers": 4, "n_sellers": 3,
                     "top5_buy_sol": 1.0, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": X1 - V0, "y_close": y1, "mint": mint, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0, "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def curve_of(u: float) -> dict:
    """Curve-life columns of a coin whose organic level is ``u`` in [0, 1] (every component monotone in u)."""
    return {"curve_n_buyers": float(int(10 + 300 * u)), "curve_buy_sol": 90.0,
            "curve_top3_buy_sol": 90.0 * (0.75 - 0.6 * u), "completer_sol": 30.0 * (0.9 - 0.8 * u),
            "z_buy_tok": 793.1e6 * (0.5 - 0.45 * u), "sn60_buy_sol": 90.0 * (0.4 - 0.35 * u)}


def organic_frames(n: int = 120, seed: int = 1, t0: int = T0, spacing: int = 600, rate_k: float = 0.008,
                   us=None, delays=None, rate_fn=None):
    """n non-instant graduates with complete curve columns; coin i has organic level u_i and reserve drift
    rate_k * (u_i - 0.5) per minute (the mechanism, planted), or ``rate_fn(u_i)``."""
    rate_fn = rate_fn or (lambda u: rate_k * (u - 0.5))
    g, c, _ = make_frames(n=n, seed=seed, t0=t0, spacing=spacing, n_minutes=1, slow_every=0, agent_every=0)
    rng = np.random.default_rng(seed + 100)
    us = rng.uniform(0, 1, n) if us is None else np.asarray(us, float)
    ds_ = rng.choice(DELAYS, n) if delays is None else np.asarray(delays, float)
    gts = g["g_ts"].to_numpy(np.int64)
    g["c_ts"] = gts - ds_.astype(np.int64)
    g["grad_delay_s"] = ds_
    g["has_create"] = 1
    for k in curve_of(0.0):
        g[k] = [curve_of(float(u))[k] for u in us]
    bars = [drift_bars(int(gt), m, p, rate_fn(float(u))) for gt, m, p, u in zip(gts, g["mint"], g["pool"], us)]
    return g, c, pd.concat(bars, ignore_index=True), us


def ds_of(frames, split: str = "train") -> C.Dataset:
    g, c, b = frames[:3]
    return C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL, guard=False)


def ref_of(frames, split: str = "train", hours=None) -> Y.RefPool:
    return Y.RefPool.from_frames(frames[0], split, C.Census.empty(), scanned_hours=hours)


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def _set(df: pd.DataFrame, m: str, **vals) -> None:
    idx = df.index[df["mint"] == m]
    for k, v in vals.items():
        if isinstance(v, str) or v is None:
            df[k] = df[k].astype(object)
        elif k in df and pd.api.types.is_integer_dtype(df[k]):
            df[k] = df[k].astype("float64")
        for i in idx:
            df.at[i, k] = v


def snap_dec(ds: C.Dataset, m: str) -> C.AsOf:
    return ds.asof(m, Y.decision_time(ds.coin(m)))


# =========================================================================== eligibility and components


def test_components_are_exact_and_nulls_make_coins_ineligible():
    fr = organic_frames(n=8, us=np.linspace(0, 1, 8), delays=[600.0] * 8)
    g = fr[0]
    _set(g, mint(1), c_ts=int(g.loc[1, "g_ts"]) - 3, grad_delay_s=3.0)       # instant
    _set(g, mint(2), has_create=0, c_ts=0)                                      # creation not scanned
    _set(g, mint(3), sn60_buy_sol=float("nan"))                                 # one component NULL
    _set(g, mint(4), curve_buy_sol=0.0)
    ds = ds_of(fr)
    want = {1: "instant", 2: "curve_partial", 3: "component_null", 4: "no_curve_buys"}
    for i, why in want.items():
        f = Y.coin_features(snap_dec(ds, mint(i)))
        assert not f["eligible"] and f["reason"] == why and f["comps"] is None
    f = Y.coin_features(snap_dec(ds, mint(5)))
    u = 5 / 7
    c = curve_of(u)
    assert f["eligible"] and f["reason"] is None and f["grad_delay_s"] == 600.0
    assert f["comps"] == pytest.approx((c["curve_n_buyers"], c["curve_top3_buy_sol"] / 90.0,
                                        c["completer_sol"] / 30.0, c["z_buy_tok"] / 793.1e6,
                                        c["sn60_buy_sol"] / 90.0))
    # the slow coin's curve columns are NULL in the data, never 0
    assert snap_dec(ds, mint(2)).get("curve_n_buyers") is None


def test_pe11_cell_boundaries():
    us = [0.6] * 6
    fr = organic_frames(n=6, us=us, delays=[6.0, 300.0, 301.0, 120.0, 120.0, 120.0])
    g = fr[0]
    _set(g, mint(3), curve_n_buyers=15.0)
    _set(g, mint(4), curve_n_buyers=14.0)
    _set(g, mint(5), curve_top3_buy_sol=0.6 * 90.0)                             # top-3 share exactly 0.6
    ds = ds_of(fr)
    pe = [Y.coin_features(snap_dec(ds, mint(i)))["pe11"] for i in range(6)]
    assert pe == [True, True, False, True, False, False]


def test_mayhem_and_non_sol_graduates_never_enter_the_reference_pool():
    fr = organic_frames(n=10, us=np.linspace(0, 1, 10))
    g = fr[0]
    _set(g, mint(2), rsol_complete=70.0)                                        # Mayhem by real SOL
    _set(g, mint(3), pool_quote_mint="USDC")                                    # not SOL-quoted
    ref = ref_of(fr)
    assert set(ref.mints) == {mint(i) for i in range(10)} - {mint(2), mint(3)}
    assert ref.n_read == 10


# =========================================================================== rank math


def test_composite_and_mid_rank():
    # breadth higher is organic; the four shares lower is organic. Row 0 dominates, row 2 is worst.
    S = np.array([[300, 0.1, 0.1, 0.0, 0.0], [100, 0.3, 0.4, 0.2, 0.1], [10, 0.7, 0.9, 0.5, 0.4]], float)
    q = Y.composite_scores(S)
    assert q == pytest.approx([1.0, 0.5, 0.0])
    # ties: identical rows share the mid rank
    T = np.array([[50, 0.2, 0.2, 0.1, 0.1]] * 2 + [[10, 0.9, 0.9, 0.9, 0.9]], float)
    assert Y.composite_scores(T) == pytest.approx([0.75, 0.75, 0.0])
    assert Y.mid_rank(0.5, np.array([0.1, 0.5, 0.9, 0.95])) == pytest.approx((1 + 0.5) / 4)
    assert [Y.tercile(x) for x in (None, 0.0, 1 / 3 - 1e-9, 1 / 3, 2 / 3 - 1e-9, 2 / 3, 1.0)] == \
        ["cold", "bottom", "bottom", "mid", "mid", "top", "top"]


def test_rank_orders_coins_by_their_organic_level():
    fr = organic_frames(n=140, spacing=300)
    ds, ref = ds_of(fr), ref_of(fr)
    us = fr[3]
    ranks, uu = [], []
    for i in range(80, 140):
        info = Y.assess(snap_dec(ds, mint(i)), ref)
        assert info["warm"] and info["n_ref"] >= Y.REF_MIN_COINS
        ranks.append(info["rank"])
        uu.append(us[i])
    assert pd.Series(ranks).corr(pd.Series(uu), method="spearman") > 0.95


# =========================================================================== the reference pool is causal


def test_window_is_trailing_24h_and_never_the_coin_itself():
    fr = organic_frames(n=60, spacing=1800)
    ref = ref_of(fr)
    g = fr[0].set_index("mint")["g_ts"]
    tau = float(g[mint(55)]) + 1700.0
    idx = ref.window(tau, mint(55))
    got = set(ref.mints[idx])
    want = {m for m, gt in g.items() if tau - 86400 < gt <= tau and m != mint(55)}
    assert got == want and mint(55) not in got and mint(56) not in got     # 56 graduates after tau
    assert len(got) == 47


def test_cold_when_the_pool_is_small_or_hours_are_missing():
    fr = organic_frames(n=140, spacing=300)
    ds = ds_of(fr)
    ref = ref_of(fr)
    assert Y.assess(snap_dec(ds, mint(10)), ref)["warm"] is False               # 10 earlier coins < 50
    assert Y.assess(snap_dec(ds, mint(10)), ref)["tercile"] == "cold"
    info = Y.assess(snap_dec(ds, mint(120)), ref)
    assert info["warm"] and info["coverage"] == 1.0
    tau = snap_dec(ds, mint(120)).tau
    hours = list(range(int(tau - 86400) // 3600 * 3600, int(tau) // 3600 * 3600 + 3600, 3600))
    full = Y.RefPool.from_frames(fr[0], "train", C.Census.empty(), scanned_hours=hours)
    assert full.coverage(tau) == 1.0
    holed = Y.RefPool.from_frames(fr[0], "train", C.Census.empty(), scanned_hours=hours[:5] + hours[6:])
    assert holed.coverage(tau) < Y.REF_WARM_MIN
    assert Y.assess(snap_dec(ds, mint(120)), holed)["warm"] is False


def test_pool_never_holds_coins_created_after_the_split_end():
    t_end = C.SPLIT_BOUNDS["train"][1]
    fr = organic_frames(n=60, t0=t_end - 30 * 600 + 300, spacing=600, delays=[120.0] * 60)
    g = fr[0]
    late = g.loc[g["c_ts"] >= t_end, "mint"].tolist()
    assert late
    assert not set(late) & set(ref_of(fr, "train").mints)
    assert set(late) <= set(ref_of(fr, "val").mints)


def test_rank_unchanged_by_future_graduates_and_own_future_bars():
    fr = organic_frames(n=140, spacing=300)
    ds, ref = ds_of(fr), ref_of(fr)
    rng = np.random.default_rng(5)
    for i in (90, 110, 130):
        m = mint(i)
        s = snap_dec(ds, m)
        clean = Y.assess(s, ref)
        g2 = fr[0].copy()
        fut = g2["g_ts"] > s.tau
        for k in ("curve_n_buyers", "curve_top3_buy_sol", "completer_sol", "z_buy_tok", "sn60_buy_sol"):
            g2[k] = g2[k].astype(float)
            g2.loc[fut, k] = rng.uniform(0, 1e3, int(fut.sum()))
        extra = g2[fut].copy()
        extra["mint"] = extra["mint"] + "X"
        g2 = pd.concat([g2, extra], ignore_index=True)
        ref2 = Y.RefPool.from_frames(g2, "train", C.Census.empty())
        dirty = _garble(fr[:3], m, s.tau, rng)
        ds2 = ds_of((g2[g2["mint"].isin(fr[0]["mint"])], dirty[1], dirty[2]))
        got = Y.assess(snap_dec(ds2, m), ref2)
        for k in ("eligible", "comps", "n_ref", "rank", "composite", "tercile", "pe11"):
            assert got[k] == clean[k], k
        for p in Y.TRIAL_CONFIGS:
            a = C.run_trades(ds, Y.make_strategy(ref), p, Y.FILL, mints=[m])
            b = C.run_trades(ds2, Y.make_strategy(ref2), p, Y.FILL, mints=[m])
            assert a["t_dec"].tolist() == b["t_dec"].tolist() and a["tag"].tolist() == b["tag"].tolist()


# =========================================================================== strategy, entry and exits


def test_one_decision_at_g30_selected_alive_coins_only():
    fr = organic_frames(n=160, spacing=300)
    g = fr[0]
    dead = [mint(150), mint(151)]
    b = fr[2]
    for m in dead:                                     # no trade from minute 10: not alive at g + 30
        r = g[g["mint"] == m].iloc[0]
        b = pd.concat([b[b["mint"] != m], drift_bars(int(r["g_ts"]), m, r["pool"], 0.0, dead_from=10)],
                      ignore_index=True)
        _set(g, m, **curve_of(1.0))                    # the most organic coins of the day
    ds, ref = ds_of((g, fr[1], b)), ref_of((g, fr[1], b))
    infos = {m: Y.assess(snap_dec(ds, m), ref) for m in ds.mints}
    for p in Y.TRIAL_CONFIGS:
        t = C.run_trades(ds, Y.make_strategy(ref), p, Y.FILL)
        assert len(t) > 0 and t["mint"].is_unique
        assert not set(t["mint"]) & set(dead)
        for r in t.itertuples(index=False):
            cd = ds.coin(r.mint)
            assert r.t_dec == Y.decision_time(cd) and 1800 <= r.age_dec_s < 1860
            assert Y.selected(infos[r.mint], p["selector"]) and r.tag == infos[r.mint]["tag"]
            assert r.stop_pct == Y.STOP_PCT and r.exit_by_age_s == Y.EXIT_BY_AGE_S
            assert (r.max_hold_s == Y.HOLD_X60_S) if p["exit"] == "X60" else pd.isna(r.max_hold_s)
            assert r.t_out <= cd.g + 179 * 60 + 60 and r.reason != "horizon"
        want = {m for m in ds.mints if Y.selected(infos[m], p["selector"])} - set(dead)
        assert set(t["mint"]) == want                  # every selected alive coin, nothing else
    t3 = set(C.run_trades(ds, Y.make_strategy(ref), Y.make_params("T3", "X60"), Y.FILL)["mint"])
    t5 = set(C.run_trades(ds, Y.make_strategy(ref), Y.make_params("T5", "X60"), Y.FILL)["mint"])
    assert t5 < t3


def test_exits_x60_and_h178():
    fr = organic_frames(n=140, spacing=300, us=np.full(140, 0.5), rate_k=0.0)     # flat prices: time exits
    ds, ref = ds_of(fr), ref_of(fr)
    a = C.run_trades(ds, Y.make_strategy(ref), Y.make_params("PE11", "X60"), Y.FILL)
    b = C.run_trades(ds, Y.make_strategy(ref), Y.make_params("PE11", "H178"), Y.FILL)
    assert len(a) and len(b) and set(a["reason"]) == {"time"} == set(b["reason"])
    hold = (a["t_out"] - a["t_in"]).to_numpy()
    assert (hold >= 3600).all() and (hold <= 3600 + 150).all()        # one bar of exit delay at most
    age_out = (b["t_out"] - b["g_ts"]).to_numpy()
    assert (age_out >= 178 * 60).all() and (age_out < 180 * 60).all()


def test_stop_fills_in_the_next_bar():
    fr = organic_frames(n=140, spacing=300, us=np.full(140, 0.5), rate_fn=lambda u: -0.01)   # price -2 %/min
    ds, ref = ds_of(fr), ref_of(fr)
    t = C.run_trades(ds, Y.make_strategy(ref), Y.make_params("PE11", "H178"), Y.FILL)
    assert len(t) and set(t["reason"]) == {"stop"}
    for r in t.itertuples(index=False):
        cd = ds.coin(r.mint)
        j_out = cd.bar_of(r.t_out)
        assert r.exit_price == pytest.approx(cd.arr["l"][j_out])           # worst side of the fill bar
        assert cd.arr["l"][j_out - 1] <= r.entry_price * (1 - Y.STOP_PCT)    # triggered one bar earlier


def test_grid_is_six_configs_plus_the_dose_run():
    assert len(Y.GRID) == 6 and len(Y.TRIAL_CONFIGS) == 7 <= 12
    assert {Y.config_key(p) for p in Y.GRID} == {f"{s}|{e}" for s in Y.SELECTORS for e in Y.EXIT_SETS}
    assert len({C.params_hash(p) for p in Y.TRIAL_CONFIGS}) == 7
    assert Y.DOSE_PARAMS["selector"] == "ALL" and Y.DOSE_PARAMS not in Y.GRID
    for p in Y.TRIAL_CONFIGS:
        assert p["version"] == Y.VERSION and p["ref_lookback_s"] == 86400 and p["stop_pct"] == 0.5
        assert json.loads(json.dumps(p)) == p and C.params_hash(json.loads(json.dumps(p))) == C.params_hash(p)
    with pytest.raises(ValueError):
        Y.make_params("T4", "X60")


# =========================================================================== decision rules


def _ev(n, mean, mw2, pdiff, ci_lo):
    return {"n": n, "mean": mean, "mean_without_top2": mw2, "placebo": {"mean_diff": pdiff},
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.1)}


def test_decide_train_rules():
    good = {"consistency": {"T": True, "PE11": True}}
    ev = {Y.config_key(p): _ev(40, 0.05, 0.03, 0.02, 0.01) for p in Y.GRID}
    ev["T3|H178"] = _ev(40, 0.06, 0.04, 0.02, 0.03)
    ev["PE11|X60"] = _ev(40, 0.04, 0.02, 0.02, 0.02)
    d = Y.decide_train(ev, good)
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_keys"] == ["T3|H178", "PE11|X60"]
    assert d["shortlist_hashes"] == [C.params_hash(p) for p in d["shortlist"]]
    # the mechanism check gates its own selectors only
    d = Y.decide_train(ev, {"consistency": {"T": False, "PE11": True}})
    assert d["shortlist_keys"] == ["PE11|X60", "PE11|H178"]
    assert Y.decide_train(ev, {"consistency": {"T": None, "PE11": None}})["verdict"] == "NO_CONFIG"
    for bad in (_ev(40, -0.01, 0.01, 0.02, 0.0), _ev(40, 0.05, -0.01, 0.02, 0.0), _ev(40, 0.05, 0.03, -0.01, 0.0)):
        ev2 = {k: bad for k in ev}
        assert Y.decide_train(ev2, good)["verdict"] == "NO_CONFIG"
    ev3 = {k: _ev(29, 0.05, 0.03, 0.02, 0.01) for k in ev}
    assert Y.decide_train(ev3, good)["verdict"] == "UNDERPOWERED_TRAIN"


def test_decide_val_and_confirm_rules():
    sl = [Y.make_params("T3", "H178"), Y.make_params("PE11", "X60")]
    ev = {"T3|H178": _ev(20, 0.05, 0.02, 0.0, 0.01), "PE11|X60": _ev(20, 0.04, 0.03, 0.0, 0.02)}
    d = Y.decide_val(ev, sl)
    assert d["verdict"] == "SELECTED" and d["candidate_key"] == "PE11|X60"
    assert d["candidate_hash"] == C.params_hash(sl[1])
    ev["PE11|X60"] = _ev(20, -0.01, 0.0, 0.0, -0.05)
    assert Y.decide_val(ev, sl)["candidate_key"] == "T3|H178"
    ev["T3|H178"] = _ev(8, 0.05, 0.02, 0.0, 0.01)
    assert Y.decide_val(ev, sl)["verdict"] == "SELECTED_UNDERPOWERED"
    ev["T3|H178"] = _ev(8, 0.05, -0.02, 0.0, 0.01)
    assert Y.decide_val(ev, sl)["verdict"] == "FAIL_VAL"
    assert Y.decide_val({k: _ev(4, 0.5, 0.5, 0.0, 0.1) for k in ev}, sl)["verdict"] == "UNDERPOWERED_VAL"
    assert Y.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 3}}})[0] is False
    assert Y.confirm_allowed({"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 3, "mean": -1}}})[0]
    assert not Y.confirm_allowed({"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": -0.1}}})[0]
    assert Y.confirm_allowed({"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": 0.1}}})[0]


def test_dose_and_combine_verdict():
    t = pd.DataFrame({"mint": [f"m{i}" for i in range(6)], "ret_net": [0.2, 0.1, 0.0, -0.1, -0.2, 0.3],
                      "tag": ["top|pe11", "top|rest", "mid|rest", "bottom|rest", "bottom|pe11", "cold|pe11"]})
    d = Y.dose(t, B=200, hide=False)
    assert d["by_tercile_n"] == {"top": 2, "bottom": 2, "mid": 1, "cold": 1}
    assert d["top_minus_bottom"] == pytest.approx(0.15 - (-0.15))
    assert d["pe11_minus_rest"] == pytest.approx(np.mean([0.2, -0.2, 0.3]) - np.mean([0.1, 0.0, -0.1]))
    assert d["consistency"] == {"T": True, "PE11": True}
    assert Y.mechanism_ok("T5", d) is True and Y.mechanism_ok("PE11", d) is True
    h = Y.dose(t, B=200, hide=True)
    assert "by_tercile_mean" not in h and "consistency" not in h and h["n"] == 6

    def base(passes, rej=()):
        return {"auto_rejections": list(rej), "criteria": [{"id": i + 1, "pass": v} for i, v in enumerate(passes)]}
    ok = [True] * 8 + [None, True]
    ex = [{"id": "Y2.1", "pass": True}]
    assert Y.combine_verdict(base(ok), ex) == "PASS"                      # item 9 missing never blocks
    assert Y.combine_verdict(base(ok), [{"id": "Y2.1", "pass": False}]) == "FAIL"
    assert Y.combine_verdict(base(ok), [{"id": "Y2.1", "pass": None}]) == "INCOMPLETE"
    assert Y.combine_verdict(base(ok[:9] + [False]), ex) == "INCOMPLETE"   # > 10 % censored
    assert Y.combine_verdict(base([False] + ok[1:]), ex) == "UNDERPOWERED"
    assert Y.combine_verdict(base(ok[:4] + [False] + ok[5:]), ex) == "FAIL"
    assert Y.combine_verdict(base(ok, ["x"]), ex) == "REJECTED"


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Y2", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Y2 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def market(split: str, t0: int, n: int, seed: int):
    fr = organic_frames(n=n, seed=seed, t0=t0, spacing=600)
    return ds_of(fr, split), ref_of(fr, split)


def _run(stage, d, dsref, env=None, **kw):
    ds, ref = dsref
    return Y.run_stage(stage, out_dir=d.out, ds=ds, ref=ref, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl,
                       B=200, n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Y.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:
        monkeypatch.setenv(k, "1")
    with pytest.raises(Y.Y2Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN (planted mechanism): 6 configs + ALL, shortlist
    tr = _run("train", st, market("train", T0, 180, 1))
    assert set(tr["configs"]) == {Y.config_key(p) for p in Y.GRID} | {"dose"}
    assert tr["dose"]["consistency"] == {"T": True, "PE11": True}
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert 1 <= len(tr["decision"]["shortlist_keys"]) <= 2
    assert tr["configs"]["dose"]["n_placebo"] == 0 and tr["configs"]["T3|X60"]["n_placebo"] > 0
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Y2") == 7
    assert led["n_trials_total"] == 2575 + 7
    with pytest.raises(Y.Y2Refused, match="final"):
        _run("train", st, market("train", T0, 180, 1))
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Y.Y2Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Y2 test prereg\n")
    with pytest.raises(Y.Y2Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    with pytest.raises(Y.Y2Refused, match="before TEST"):
        _check("confirm", st, env=env_all)
    sl = (st.sl / "Y2.json").read_text()
    (st.sl / "Y2.json").unlink()
    with pytest.raises(Y.Y2Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Y2.json").write_text(sl)
    # ---- VAL: the shortlisted configs only (never ALL)
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 00:30"), 120, 2))
    assert set(va["configs"]) == set(tr["decision"]["shortlist_keys"]) and "dose" not in va["configs"]
    assert va["decision"]["verdict"] == "SELECTED", va["decision"]
    cand = va["decision"]["candidate_key"]
    with pytest.raises(Y.Y2Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 100, 3)
    with pytest.raises(Y.Y2Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert set(te["configs"]) == {"candidate", "dose"} and te["verdict"]["candidate"] == cand
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert [c["id"] for c in te["verdict"]["y2_extras"]] == ["Y2.1"]
    with pytest.raises(Y.Y2Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Y.Y2Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 300, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(Y.Y2Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 120, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(Y.Y2Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_no_edge_stops_before_val(st):
    fr = organic_frames(n=180, t0=T0, spacing=600, rate_k=-0.008)          # organic coins do WORSE
    tr = _run("train", st, (ds_of(fr), ref_of(fr)))
    assert tr["dose"]["consistency"]["T"] is False
    assert tr["decision"]["verdict"] == "NO_CONFIG" and not (st.sl / "Y2.json").exists()
    assert tr["overall"].startswith("NO EDGE")
    with pytest.raises(Y.Y2Refused, match="NO_CONFIG"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    dsref = market("train", T0, 180, 1)
    with pytest.raises(Y.Y2Refused, match="incomplete"):
        _run("train", st, dsref, _skip_coverage=False)
    doc = _run("train", st, dsref, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Y2.json").exists()
    with pytest.raises(Y.Y2Refused, match="no TRAIN result"):
        _check("val", st)


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Y.Y2Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Y.Y2Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds, ref = market("train", T0, 180, 1)
    ds.split = "final_train"                      # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Y.run_stage("debug", out_dir=st.out, ds=ds, ref=ref, flow=st.flow, ledger_path=st.ledger, B=200,
                      n_placebo=2, env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert "mean" not in e and "ci90" not in e and "placebo" not in e and e["returns"].startswith("hidden")
        assert "reasons" not in e and "stress" not in e and "portfolio" not in e
    assert "by_tercile_mean" not in doc["dose"] and "consistency" not in doc["dose"]
    assert doc["event_counts"]["eligible"] == 180 and doc["event_counts"]["eligible_warm"] >= 120
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    assert all(r["mean"] is None for r in json.loads(st.ledger.read_text())["runs"])


# =========================================================================== real census graduates (debug split)


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """The organic rank of real census-TRAIN-third coins is unchanged when every graduate after tau carries garbage
    and when the coin's own data after tau is garbage; slow graduates read NULL (ineligible), never 0."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.coverage_dataset("final_train", f, cen)
    ref = Y.RefPool.from_frames(frames[0], "final_train", cen)
    rng = np.random.default_rng(7)
    infos = {m: Y.assess(snap_dec(full_ds, m), ref) for m in full_ds.mints}
    slow = [m for m, i in infos.items() if i["reason"] == "curve_partial"]
    for m in slow[:5]:
        assert snap_dec(full_ds, m).get("curve_n_buyers") is None
    warm = [m for m, i in infos.items() if i["warm"]]
    assert len(warm) >= 30
    pick = list(rng.choice(warm, size=8, replace=False))
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    compared = 0
    for m in pick:
        s = snap_dec(full_ds, m)
        g2 = frames[0].copy()
        fut = g2["g_ts"] > s.tau
        for k in ("curve_n_buyers", "curve_top3_buy_sol", "completer_sol", "z_buy_tok", "sn60_buy_sol",
                  "curve_buy_sol"):
            g2[k] = g2[k].astype(float)
            g2.loc[fut, k] = rng.uniform(0, 1e3, int(fut.sum()))
        ref2 = Y.RefPool.from_frames(g2, "final_train", cen)
        dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, s.tau, rng), census=cen, sol=SOL)
        if m not in dirty.mints:
            continue
        got = Y.assess(snap_dec(dirty, m), ref2)
        for k in ("eligible", "comps", "n_ref", "rank", "composite", "tercile", "pe11"):
            assert got[k] == infos[m][k], (m, k)
        compared += 1
    assert compared >= 5

"""Tests for research/lab2/y4.py: the level sets, the BREAK / RETEST / TOUCH definitions on arrays and on hand-built
minute bars, USD conversion, entry timing and worst fills, the level-lost exit (identical for stateless placebo
positions), the market-cap band, the event study (labels read later, statistics, predictions), no lookahead
(synthetic and real census bars), the grid, the pre-registered decision rules, and every stage refusal."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import V0, make_frames, real_flow_available
from conftest import VALID_ALL as VALID
from test_common import _garble

import common as C
import y4 as Y

SOLP = 100.0
SOL = C.SolUsd(fallback=SOLP)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
K = X0 * Y0
N_MIN = 186
GRAD_USD = X0 / Y0 * 1e9 * SOLP          # $41,078 at SOL $100


# =========================================================================== hand-built bars (USD market-cap paths)


def X_of(usd: float) -> float:
    """Pricing reserve X at which the pool (k = X0 * Y0) has a USD market cap ``usd`` at SOL $100."""
    return math.sqrt(usd / (SOLP * 1e9) * K)


def path_bars(g: int, mint_: str, pool: str, path: dict) -> pd.DataFrame:
    """B2 bars from a market-cap path: ``path`` = {j: close_usd or {"close", "high", "low"}}. A listed minute buys up to
    its high, sells down to its low, then trades to its close (an unchanged minute trades a tiny buy and sell); a
    minute that is not listed has no trade (no row)."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    rows = []
    for j in range(N_MIN):
        spec = path.get(j)
        if spec is None:
            continue
        spec = spec if isinstance(spec, dict) else {"close": spec}
        p_open, pts, buys, sells, bt, st = X / y, [], [], [], 0.0, 0.0
        for key in ("high", "low", "close"):
            if key not in spec:
                continue
            Xt = X_of(spec[key])
            if abs(Xt - X) < 1e-12:
                continue
            y1 = K / Xt
            if Xt > X:
                buys.append(Xt - X)
                bt += y - y1
            else:
                sells.append(X - Xt)
                st += y1 - y
            X, y = Xt, y1
            pts.append(X / y)
        if not buys and not sells:
            buys, sells, bt, st = [0.05], [0.05], 0.05 / (X / y), 0.05 / (X / y)
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": len(buys), "n_sells": len(sells), "n_dust": 0,
                     "buy_sol": float(sum(buys)), "sell_sol": float(sum(sells)), "buy_tok": bt, "sell_tok": st,
                     "n_buyers": len(buys), "n_sellers": len(sells), "top5_buy_sol": float(sum(buys)),
                     "open": p_open, "high": max([p_open] + pts), "low": min([p_open] + pts), "close": X / y,
                     "x_close": X - V0, "y_close": y, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0, "price_repaired": 0})
    return pd.DataFrame(rows)


def alt(j0: int, j1: int, a: float, b: float) -> dict:
    """Minutes j0..j1-1 closing alternately at a and b (USD)."""
    return {j: (a if (j - j0) % 2 == 0 else b) for j in range(j0, j1)}


def round_winner(brk: int = 30) -> dict:
    """Below $100k (88-92k) from bar 1, a clean break of $100k at ``brk`` (close $104k), a steady rise to $125k, then
    flat at $124-126k: never touches $128k (the shifted level) and never retests $100k."""
    p = {0: GRAD_USD, **alt(1, brk, 88e3, 92e3), brk: {"high": 105e3, "close": 104e3}}
    for j in range(brk + 1, brk + 16):
        p[j] = 104e3 + (j - brk) * 1.4e3
    p.update(alt(brk + 16, N_MIN, 124e3, 126e3))
    return p


def twin_loser(brk: int = 40) -> dict:
    """$116-120k from bar 1 (above $100k: no round event), a break of the shifted $128k level at ``brk`` (close $133k),
    a retest of it (low $130.5k), then a fall to $108-112k."""
    p = {0: GRAD_USD, **alt(1, brk, 116e3, 120e3), brk: {"high": 134e3, "close": 133e3}, brk + 1: 130.5e3,
         brk + 2: 110e3}
    p.update(alt(brk + 3, N_MIN, 108e3, 112e3))
    return p


def noise() -> dict:
    return {0: GRAD_USD, **alt(1, N_MIN, 40e3, 42e3)}


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0):
    g, c, _ = make_frames(n=n, seed=seed, t0=t0)
    parts = [path_bars(int(r.g_ts), r.mint, r.pool, specs.get(int(r.mint[4:7])) or noise())
             for r in g.itertuples(index=False)]
    return g, c, pd.concat(parts, ignore_index=True)


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def grid_t(cd: C.CoinData, j_done: int) -> float:
    """The decision right after bar ``j_done`` completed."""
    return float(cd.m0 + 60 * (j_done + 1) + C.GRID_OFFSET_S)


def lv(*usd) -> np.ndarray:
    return np.asarray(usd, float)


# =========================================================================== levels


def test_level_sets_are_fixed_round_and_non_round():
    assert Y.ROUND_USD == (10e3, 25e3, 50e3, 100e3, 250e3, 500e3, 1e6, 2.5e6, 5e6, 10e6)
    assert np.allclose(Y.LEVEL_SETS["shifted"], np.asarray(Y.ROUND_USD) * 1.28)
    salient = np.array([1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 7.5, 8, 9, 10])
    for L in Y.SHIFTED_USD:                      # the twin's break zone [L, 1.03 L] stays >= 5 % from salient numbers
        m = L / 10 ** math.floor(math.log10(L))
        for z in (m, m * (1 + Y.MARGIN)):
            assert np.min(np.abs(np.log(salient / z))) > math.log(1.05)
    r = np.asarray(Y.ROUND_USD)
    assert all(((r < L) & (r * 1.25 <= L)).any() and ((r > L) & (r >= L * 1.4)).any()
               for L in Y.SHIFTED_USD[:-1])      # strictly between round neighbours, far from both
    assert [Y.level_name(x) for x in (10e3, 12.8e3, 1e6, 1.28e6, 2.5e6)] == ["10k", "12.8k", "1M", "1.28M", "2.5M"]
    assert Y.level_prices("round", 100.0)[3] == pytest.approx(100e3 / 100.0 / 1e9)


# =========================================================================== events on arrays


def _c(prior, last, n_before=12):
    """closes: n_before bars at ``prior`` (bar 0 included), then ``last``."""
    return np.asarray([prior] * n_before + [last], float)


def test_break_at_margin_approach_and_highest_level():
    levels = lv(1.0, 2.0)
    tr = np.ones(13)
    assert Y.break_at(_c(0.9, 1.03), tr, 12, levels) == 0
    assert Y.break_at(_c(0.9, 1.029), tr, 12, levels) is None            # inside the margin: not clean
    assert Y.break_at(_c(1.0, 1.05), tr, 12, levels) is None             # a prior close AT the level: not below
    assert Y.break_at(_c(0.9, 2.07), tr, 12, levels) == 1                # jumped two levels: the highest
    assert Y.break_at(_c(0.9, 2.05), tr, 12, levels) == 0                # 2 x 1.03 > 2.05: only the first is clean
    c = _c(0.9, 1.1)
    c[5] = 1.2                                                           # 7 bars before: inside the window
    assert Y.break_at(c, tr, 12, levels) is None
    c = _c(0.9, 1.1)
    c[1] = 1.2                                                           # 11 bars before: outside the window
    assert Y.break_at(c, tr, 12, levels) == 0
    t0 = tr.copy()
    t0[12] = 0
    assert Y.break_at(_c(0.9, 1.1), t0, 12, levels) is None              # untraded bar
    assert Y.break_at(_c(0.9, 1.1, n_before=10), np.ones(11), 10, levels) is None   # window would use bar 0


def test_retest_first_touch_within_window_and_level_kept():
    levels = lv(1.0, 2.0)
    base = [0.9] * 12 + [1.05]                                           # break of 1.0 at bar 12
    c = np.asarray(base + [1.08, 1.06, 1.04], float)
    l = c.copy()
    l[13:15] = [1.05, 1.04]                                              # above the band (1.03)
    l[15] = 1.01                                                         # first retest: low <= 1.03, close >= 1.0
    tr = np.ones(len(c))
    assert Y.retest_at(c, l, tr, 15, levels) == (0, 12)
    assert Y.retest_at(c, l, tr, 14, levels) is None                     # bar 14 did not come back to the level
    l2 = l.copy()
    l2[14] = 1.02                                                        # an earlier retest: 15 is not the first
    assert Y.retest_at(c, l2, tr, 15, levels) is None
    assert Y.retest_at(c, l2, tr, 14, levels) == (0, 12)
    c3 = c.copy()
    c3[14] = 0.99                                                        # the level was lost in between
    assert Y.retest_at(c3, l, tr, 15, levels) is None
    c4 = np.asarray(base + [1.2] * (Y.RETEST_W + 1), float)              # retest after W bars: too late
    l4 = c4.copy()
    l4[-1] = 1.0
    assert Y.retest_at(c4, l4, np.ones(len(c4)), len(c4) - 1, levels) is None
    l4[-2] = 1.0
    assert Y.retest_at(c4, l4, np.ones(len(c4)), len(c4) - 2, levels) == (0, 12)


def test_touch_classes_and_first_contact():
    levels = lv(1.0, 2.0)
    tr = np.ones(13)
    h = np.full(13, 0.95)
    for close, cls in ((1.04, "BREAK"), (1.01, "HOLD"), (0.97, "REJECT")):
        c = _c(0.9, close)
        hh = h.copy()
        hh[12] = 1.06
        assert Y.touch_at(c, hh, tr, 12, levels) == (0, cls)
    hh = h.copy()
    hh[12], hh[6] = 1.06, 1.001                                          # touched 6 bars ago: not a first contact
    assert Y.touch_at(_c(0.9, 1.04), hh, tr, 12, levels) is None
    hh[6], hh[12] = 0.95, 2.2                                            # through both: the highest level reached
    assert Y.touch_at(_c(0.9, 1.5), hh, tr, 12, levels) == (1, "REJECT")


# =========================================================================== the strategy on hand-built coins


@pytest.fixture
def one():
    fr = frames_with({0: round_winner(), 1: twin_loser()}, n=3)
    return ds_of(fr)


def test_break_entry_lands_on_the_next_bar_at_its_high(one):
    m = mint(0)
    cd = one.coin(m)
    p = Y.make_params("break", 15, "round")
    ok, info = Y.entry_decision(one.asof(m, grid_t(cd, 30)), p)
    assert ok and info["level"] == "100k" and info["level_usd"] == 100e3 and info["event_bar"] == 30
    assert not Y.entry_decision(one.asof(m, grid_t(cd, 29)), p)[0]
    assert not Y.entry_decision(one.asof(m, grid_t(cd, 31)), p)[0]       # the break is one bar, not a state
    t = C.run_trades(one, Y.strategy, p, Y.FILL, mints=[m])
    assert len(t) == 1
    r = t.iloc[0]
    assert r.t_dec == grid_t(cd, 30) and r.tag == "100k"
    assert r.entry_price == pytest.approx(max(cd.arr["o"][31], cd.arr["h"][31]))
    trig = int(math.ceil((r.t_in + 900 - cd.m0) / 60.0))                # first bar starting at or after the deadline
    assert r.reason == "time" and cd.bar_of(r.t_out) == trig + 1         # ... filled on the NEXT bar
    assert r.exit_price == pytest.approx(min(cd.arr["o"][cd.bar_of(r.t_out)], cd.arr["l"][cd.bar_of(r.t_out)]))
    for q in (Y.make_params("break", 15, "shifted"), Y.make_params("retest", 15, "round")):
        assert len(C.run_trades(one, Y.strategy, q, Y.FILL, mints=[m])) == 0


def test_shifted_twin_breaks_and_retests_its_own_level(one):
    m = mint(1)
    cd = one.coin(m)
    t = C.run_trades(one, Y.strategy, Y.make_params("break", 60, "shifted"), Y.FILL, mints=[m])
    assert len(t) == 1 and t.iloc[0].tag == "128k" and t.iloc[0].t_dec == grid_t(cd, 40)
    assert t.iloc[0].reason == "signal:level_lost" and cd.bar_of(t.iloc[0].t_out) == 43
    t = C.run_trades(one, Y.strategy, Y.make_params("retest", 60, "shifted"), Y.FILL, mints=[m])
    assert len(t) == 1 and t.iloc[0].t_dec == grid_t(cd, 41) and t.iloc[0].tag == "128k"
    for lev in ("round",):
        for e in Y.ENTRY_GRID:
            assert len(C.run_trades(one, Y.strategy, Y.make_params(e, 60, lev), Y.FILL, mints=[m])) == 0


def test_usd_conversion_moves_the_levels():
    fr = frames_with({0: round_winner()}, n=2)
    hi_sol = C.Dataset.from_frames("train", *fr, census=C.Census.empty(), sol=C.SolUsd(fallback=120.0), guard=False)
    m = mint(0)
    cd = hi_sol.coin(m)
    # at SOL $120 the path's $104k break bar is a $124.8k market cap and the $88-92k range is $105.6-110.4k: above
    # $100k all along, so no round level is approached from below
    assert not Y.entry_decision(hi_sol.asof(m, grid_t(cd, 30)), Y.make_params("break", 15, "round"))[0]
    assert hi_sol.asof(m, grid_t(cd, 30)).mcap_usd == pytest.approx(124.8e3, rel=1e-6)


def _pv(t_dec: float, state: dict | None = None) -> C.PositionView:
    return C.PositionView(mint="x", t_dec=t_dec, t_in=t_dec + 30, entry_price=1.0, tokens=1.0, sol_in=1.0, peak=1.0,
                          bars_held=1, unrealized=0.0, exits=C.ExitSpec(), state=state or {},
                          is_placebo=state is None)


def test_level_lost_exit_is_identical_for_a_stateless_placebo_position():
    p = round_winner()
    p[32], p[33] = 98e3, 99e3                                            # the level is lost two bars after the break
    ds = ds_of(frames_with({0: p}, n=2))
    m = mint(0)
    cd = ds.coin(m)
    t_dec = grid_t(cd, 30)
    for prm in (Y.make_params("break", 60, "round"), Y.make_params("break", 15, "round")):
        for j in range(30, 60):
            snap = ds.asof(m, grid_t(cd, j))
            a = Y.exit_decision(snap, prm, _pv(t_dec, {"level_usd": 100e3}))
            b = Y.exit_decision(snap, prm, _pv(t_dec))
            assert (a is None) == (b is None) and (a is None or a.reason == b.reason == "level_lost")
            assert (a is not None) == (j in (32, 33))
    t = C.run_trades(ds, Y.strategy, Y.make_params("break", 60, "round"), Y.FILL, mints=[m])
    r = t.iloc[0]
    assert r.reason == "signal:level_lost" and cd.bar_of(r.t_out) == 33
    assert r.exit_price == pytest.approx(min(cd.arr["o"][33], cd.arr["l"][33]))
    assert Y.ref_level_usd(104e3, Y.make_params("break", 15, "round")) == 100e3
    assert Y.ref_level_usd(102e3, Y.make_params("break", 15, "round")) == 50e3     # inside the margin of 100k
    assert Y.ref_level_usd(102e3, Y.make_params("retest", 15, "round")) == 100e3
    assert Y.ref_level_usd(9e3, Y.make_params("retest", 15, "round")) is None
    assert Y.ref_level_usd(140e3, Y.make_params("break", 15, "shifted")) == 128e3


def test_ages_skip_and_deadline_never_censors():
    late = {0: GRAD_USD, **alt(1, 116, 88e3, 92e3), 116: {"high": 105e3, "close": 104e3}}
    late.update({j: 110e3 for j in range(117, N_MIN)})
    early = round_winner(brk=8)                                          # a break before age 10 min (and b - N < 1)
    ds = ds_of(frames_with({0: late, 1: early, 2: round_winner(brk=114)}, n=3))
    for p in Y.GRID:
        t = C.run_trades(ds, Y.strategy, p, Y.FILL)
        assert (t["reason"] != "horizon").all()
        assert t["mint"].isin([mint(2)]).all()                          # bar 116 is decided at age > 115 min
        assert (t["age_dec_s"] <= Y.AGE_MAX_S).all() and (t["age_dec_s"] >= Y.AGE_MIN_S).all()
    t = C.run_trades(ds, Y.strategy, Y.make_params("break", 60, "round"), Y.FILL, mints=[mint(2)])
    assert len(t) == 1 and t.iloc[0].t_out <= ds.coin(mint(2)).g + Y.EXIT_BY_AGE_S + 60


def test_band_and_placebo_eligibility(one):
    m = mint(0)
    cd = one.coin(m)
    assert Y.band(one.asof(m, grid_t(cd, 30))) == 4                      # $104k: 10k, 25k, 50k, 100k at or below
    assert Y.band(one.asof(m, grid_t(cd, 20))) == 3
    assert Y.placebo_ok(one.asof(m, grid_t(cd, 20)))
    n = mint(2)
    assert Y.band(one.asof(n, grid_t(one.coin(n), 20))) == 2 and Y.placebo_ok(one.asof(n, grid_t(one.coin(n), 20)))
    low = ds_of(frames_with({0: {0: GRAD_USD, **alt(1, N_MIN, 8e3, 9e3)}}, n=1))
    s = low.asof(mint(0), grid_t(low.coin(mint(0)), 20))                 # $8-9k: under the lowest level
    assert Y.band(s) == 0 and not Y.placebo_ok(s)


# =========================================================================== the event study


def test_scan_touch_labels_are_read_later_and_hidden_without_labels():
    p = {0: GRAD_USD, **alt(1, 50, 88e3, 92e3), 50: {"high": 101e3, "close": 95e3}}
    p.update({j: 93e3 for j in range(51, 65)})
    p.update({j: 80e3 for j in range(65, N_MIN)})
    ds = ds_of(frames_with({0: p}, n=2))
    m = mint(0)
    obs, cnt = Y.scan(ds, labels=True, mints=[m])
    r = obs[(obs["set"] == "round")]
    assert len(r) == 1 and r.iloc[0]["cls"] == "REJECT" and r.iloc[0]["level"] == "100k"
    assert r.iloc[0]["fwd15"] == pytest.approx(80 / 95 - 1, rel=1e-9)
    assert r.iloc[0]["fwd60"] == pytest.approx(80 / 95 - 1, rel=1e-9)
    assert r.iloc[0]["age_min"] == pytest.approx((grid_t(ds.coin(m), 50) - ds.coin(m).g) / 60)
    assert cnt["by_set"]["round"]["touch_bars"] == {"BREAK": 0, "HOLD": 0, "REJECT": 1}
    assert cnt["by_set"]["round"]["break_bars"] == 0
    obs0, cnt0 = Y.scan(ds, labels=False, mints=[m])
    assert obs0[["fwd15", "fwd60"]].isna().all().all() and cnt0 == cnt
    w = ds_of(frames_with({0: round_winner(), 1: twin_loser()}, n=2))
    _, c2 = Y.scan(w, labels=False)
    assert c2["by_set"]["round"]["break_by_level"] == {"100k": 1}
    assert c2["by_set"]["shifted"]["break_by_level"] == {"128k": 1}
    assert c2["by_set"]["shifted"]["retest_by_level"] == {"128k": 1}
    assert c2["by_set"]["round"]["touch_bars"]["BREAK"] == 1 and c2["by_set"]["shifted"]["touch_bars"]["BREAK"] == 1
    assert c2["first_round_break_decision_state"]["mcap_usd"]["n"] == 1


def _obs(seed: int, round_break: float, shifted_break: float, n: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        for s, mu_b in (("round", round_break), ("shifted", shifted_break)):
            for k, mu in (("BREAK", mu_b), ("REJECT", -0.02), ("HOLD", 0.0)):
                rows.append({"mint": f"m{i}", "set": s, "level": "100k", "level_usd": 1e5, "cls": k, "age_min": 30.0,
                             "t": 0.0, "mcap_usd": 1e5, "round_trip": 0.035,
                             "fwd15": mu + rng.normal(0, 0.01), "fwd60": mu + rng.normal(0, 0.01)})
    return pd.DataFrame(rows, columns=Y.ES_COLS)


def test_event_study_stats_and_predictions():
    es = Y.event_study_stats(_obs(1, 0.10, 0.0), B=500)
    rb = es["roundness"]["BREAK|h15"]
    assert rb["diff"] == pytest.approx(0.10, abs=0.01) and rb["ci95"][0] > 0.08
    rr = es["roundness"]["REJECT|h15"]
    assert rr["ci95"][0] < 0 < rr["ci95"][1]
    assert es["spread"]["round|h15"]["diff"] == pytest.approx(0.12, abs=0.01)
    assert es["spread_round_minus_shifted"]["h15"]["diff"] == pytest.approx(0.10, abs=0.01)
    assert es["cells"]["round|BREAK|h15"]["n"] == 40 and es["cells"]["round|BREAK|h15"]["coins"] == 40
    pr = Y.score_predictions(es, "NO_CONFIG")
    assert pr["P1_round_break_continues_more"]["folklore_supported"] is True
    assert pr["P2_round_reject_falls_more"]["folklore_supported"] is False
    assert pr["P3_round_break_pays_for_costs"]["folklore_supported"] is True        # +10 % > 3.5 %
    assert pr["P4_a_round_config_qualifies"]["folklore_supported"] is False
    null = Y.score_predictions(Y.event_study_stats(_obs(2, 0.0, 0.0), B=500), None)
    assert null["P1_round_break_continues_more"]["folklore_supported"] is False
    assert null["P3_round_break_pays_for_costs"]["folklore_supported"] is False
    assert null["P4_a_round_config_qualifies"]["folklore_supported"] is None
    empty = Y.event_study_stats(pd.DataFrame(columns=Y.ES_COLS))
    assert empty["n_obs"] == 0 and Y.score_predictions(empty, None)["P1_round_break_continues_more"][
        "folklore_supported"] is None


def test_joint_bootstrap_moves_a_coins_observations_together():
    # each coin has the same value in both sets: the difference is exactly 0 in every resample
    rows = [{"mint": f"m{i}", "set": s, "cls": "BREAK", "fwd15": float(i)} for i in range(30) for s in ("round", "shifted")]
    o = pd.DataFrame(rows)
    st = o["set"].to_numpy(object)
    pt, ci = Y._joint_boot(o, [(st == "round", 1.0), (st == "shifted", -1.0)], "fwd15", 300)
    assert pt == pytest.approx(0.0) and ci == pytest.approx((0.0, 0.0))
    assert Y._joint_boot(o, [(st == "nope", 1.0)], "fwd15", 10) == (None, None)


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    snap = ds.asof(m, t)
    out = [snap.k, round(snap.mcap_usd, 6), Y.band(snap)]
    for p in Y.GRID:
        ok, info = Y.entry_decision(snap, p)
        out.append((ok, info["level_usd"], info["event_bar"]))
        for back in (60.0, 300.0, 900.0):
            e = Y.exit_decision(snap, p, _pv(t - back))
            out.append(None if e is None else e.reason)
    c, h, l, tr = Y._arrays(snap)
    b = len(c) - 1
    for s in Y.LEVEL_SETS:
        lvp = Y.level_prices(s, snap.sol_usd)
        out += [Y.touch_at(c, h, tr, b, lvp), Y.break_at(c, tr, b, lvp), Y.retest_at(c, l, tr, b, lvp)]
    return tuple(out)


def _mixed_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(0, 12, 3):
        specs[i] = round_winner(brk=int(rng.integers(15, 100)))
        specs[i + 1] = twin_loser(brk=int(rng.integers(15, 100)))
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(3))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _mixed_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(14):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([400, 700, 1300, 1900, 3000, 4500, 6000, 6900, 9000])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_random_walk_features_unchanged_by_future_garbage():
    frames = make_frames(n=10, seed=4)
    clean = C.Dataset.from_frames("train", *frames, census=C.Census.empty(), sol=SOL)
    rng = np.random.default_rng(5)
    for _ in range(20):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        t = clean.coin(m).g + float(rng.uniform(600, 7000))
        dirty = C.Dataset.from_frames("train", *_garble(frames, m, t - C.DECISION_LAG_S, rng),
                                      census=C.Census.empty(), sol=SOL)
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _mixed_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(12):
        m = mint(i)
        T = clean.coin(m).g + 70 * 60
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
    """Y4 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    sol = C.load_sol_usd()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=sol)
    rng = np.random.default_rng(11)
    pick = [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=14, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=sol)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(600, 2400)), float(rng.uniform(2400, 4800)), float(rng.uniform(4800, 6900))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=sol)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 10 and n >= 25


# =========================================================================== grid and pre-registered decisions


def test_grid_is_eight_distinct_trials_with_twins():
    assert len(Y.GRID) == 8 and len({C.params_hash(p) for p in Y.GRID}) == 8
    keys = {Y.config_key(p) for p in Y.GRID}
    for p in Y.GRID:
        tw = Y.twin_of(p)
        assert Y.config_key(tw) in keys and tw["levels"] != p["levels"] and Y.twin_of(tw) == p
        assert {k: v for k, v in tw.items() if k != "levels"} == {k: v for k, v in p.items() if k != "levels"}
        assert p["max_hold_s"] == 60.0 * p["hold_min"]
    assert sum(p["levels"] == "round" for p in Y.GRID) == 4
    assert C.params_hash(Y.ES_PARAMS) not in {C.params_hash(p) for p in Y.GRID}
    for bad in (("break", 30, "round"), ("dip", 15, "round"), ("break", 15, "sol")):
        with pytest.raises(ValueError):
            Y.make_params(*bad)


def _ev(p, n, mean, ci_lo=None, mw2=None, pdiff=None, coins=None, cens=0.0):
    return {"n": n, "n_coins": coins if coins is not None else n, "mean": mean,
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.2), "mean_without_top2": mw2,
            "placebo": None if pdiff is None else {"mean_diff": pdiff}, "censored_share": cens,
            "params_hash": C.params_hash(p), "config": Y.config_key(p)}


def _evals(fill):
    return {Y.config_key(p): fill(p) for p in Y.GRID}


def test_decide_train_pair_rule():
    base = _evals(lambda p: _ev(p, 80, -0.01, -0.05, -0.02, -0.01))
    assert Y.decide_train(base)["verdict"] == "NO_CONFIG"
    low = _evals(lambda p: _ev(p, 59, 0.2, 0.1, 0.1, 0.1))
    d = Y.decide_train(low)
    assert d["verdict"] == "UNDERPOWERED_TRAIN" and d["shortlist"] == []
    a, b = Y.make_params("retest", 60, "round"), Y.make_params("break", 15, "round")
    good = dict(base)
    good[Y.config_key(a)] = _ev(a, 80, 0.05, 0.02, 0.03, 0.04)
    good[Y.config_key(b)] = _ev(b, 80, 0.06, 0.02, 0.03, 0.04)          # same CI low, higher mean -> rank 1
    d = Y.decide_train(good)
    assert d["verdict"] == "SHORTLISTED" and d["candidate"] == Y.config_key(b)
    assert d["twin"] == "break|h15|shifted"
    assert d["shortlist_hashes"] == [C.params_hash(b), C.params_hash(Y.twin_of(b))]
    # the twin must be beaten
    g2 = dict(good)
    g2["break|h15|shifted"] = _ev(Y.twin_of(b), 80, 0.07)
    assert Y.decide_train(g2)["candidate"] == Y.config_key(a)
    # an undefined twin (no trades) never qualifies the round config
    g3 = dict(good)
    g3["break|h15|shifted"] = _ev(Y.twin_of(b), 0, None)
    g3["retest|h60|shifted"] = _ev(Y.twin_of(a), 0, None)
    assert Y.decide_train(g3)["verdict"] == "NO_CONFIG"
    # censoring, matched control, coins, top-2
    for bad in (dict(cens=0.2), dict(pdiff=-0.01), dict(coins=39), dict(mw2=-0.01)):
        kw = dict(ci_lo=0.02, mw2=0.03, pdiff=0.04)
        kw.update(bad)
        g4 = dict(base)
        g4[Y.config_key(b)] = _ev(b, 80, 0.06, **kw)
        assert Y.decide_train(g4)["verdict"] == "NO_CONFIG"
    # shifted configs are never candidates
    g5 = _evals(lambda p: _ev(p, 80, 0.2 if p["levels"] == "shifted" else -0.01, 0.1, 0.1, 0.1))
    assert Y.decide_train(g5)["verdict"] == "NO_CONFIG"
    tie = dict(base)
    c1, c2 = Y.make_params("break", 60, "round"), Y.make_params("break", 15, "round")
    tie[Y.config_key(c1)] = _ev(c1, 80, 0.05, 0.02, 0.03, 0.04)
    tie[Y.config_key(c2)] = _ev(c2, 80, 0.05, 0.02, 0.03, 0.04)
    assert Y.decide_train(tie)["candidate"] == Y.config_key(c2)            # tie -> the shorter hold


def test_decide_val_combine_confirm_final():
    p = Y.make_params("break", 15, "round")
    assert Y.decide_val(_ev(p, 4, 0.5, mw2=0.5))["verdict"] == "UNDERPOWERED_VAL"
    assert Y.decide_val(_ev(p, 30, 0.02, mw2=-0.01))["verdict"] == "FAIL_VAL"
    assert Y.decide_val(_ev(p, 8, 0.02, mw2=0.01))["verdict"] == "SELECTED_UNDERPOWERED"
    assert Y.decide_val(_ev(p, 20, 0.02, mw2=0.01))["verdict"] == "SELECTED"

    def base(passes, rej=()):
        return {"criteria": [{"id": i + 1, "pass": v} for i, v in enumerate(passes)], "auto_rejections": list(rej)}
    ok = [True] * 8 + [None, True]
    assert Y.combine_verdict(base(ok)) == "PASS"
    assert Y.combine_verdict(base(ok, ["x"])) == "REJECTED"
    assert Y.combine_verdict(base([False] + ok[1:])) == "UNDERPOWERED"
    assert Y.combine_verdict(base(ok[:4] + [False] + ok[5:])) == "FAIL"
    assert Y.combine_verdict(base(ok[:6] + [None] + ok[7:])) == "INCOMPLETE"
    assert Y.combine_verdict(base(ok[:9] + [False])) == "INCOMPLETE"
    assert Y.confirm_allowed({"verdict": {"verdict": "REJECTED"}})[0] is False
    assert Y.confirm_allowed({"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 3, "mean": -1}}})[0]
    assert not Y.confirm_allowed({"verdict": {}, "configs": {"candidate": {"n": 30, "mean": -0.01}}})[0]
    t = pd.DataFrame({"split": ["final_train", "final_val", "final_test"], "ret_net": [5.0, -0.1, 0.05]})
    d = Y.final_decision(t)
    assert d["n"] == 2 and d["mean"] == pytest.approx(-0.025) and d["mean_positive"] is False
    assert d["debug_third"]["n"] == 1
    assert Y.round_minus_shifted({"mean": 0.05}, {"mean": 0.01}) == pytest.approx(0.04)
    assert Y.round_minus_shifted({"mean": 0.05}, {"mean": None}) is None


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Y4", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Y4 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Y.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Y.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_win: int, n_lose: int, n_noise: int, seed: int, flip: bool = False) -> C.Dataset:
    """n_win coins that break $100k and keep rising (round winners), n_lose that break the shifted $128k and fall
    (twin losers), n_noise flat coins. ``flip`` swaps the outcome: round breaks fall, nothing else trades."""
    specs = {}
    for i in range(n_win):
        if flip:
            p = round_winner(brk=30 + i % 5)
            b = 30 + i % 5
            p.update({j: 101e3 for j in range(b + 1, b + 3)})
            p.update(alt(b + 3, N_MIN, 104.5e3, 104e3))            # above the level, below the entry: slow bleed
            specs[i] = p
        else:
            specs[i] = round_winner(brk=30 + i % 5)
    for i in range(n_win, n_win + n_lose):
        specs[i] = twin_loser(brk=40 + i % 5)
    ds = ds_of(frames_with(specs, n=n_win + n_lose + n_noise, seed=seed, t0=t0), split)
    assert len(ds) == n_win + n_lose + n_noise if split != "final" else len(ds) >= 0.75 * (n_win + n_lose + n_noise)
    return ds


def test_no_roundness_market_reads_no_config(st):
    doc = _run("train", st, market("train", T0, 64, 10, 6, 1, flip=True))
    d = doc["decision"]
    assert d["verdict"] == "NO_CONFIG" and not (st.sl / "Y4.json").exists()
    assert doc["overall"].startswith("NO EDGE")
    assert doc["predictions"]["P4_a_round_config_qualifies"]["folklore_supported"] is False
    with pytest.raises(Y.Y4Refused, match="NO_CONFIG"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 64, 10, 2, 1)
    with pytest.raises(Y.Y4Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Y4.json").exists()
    with pytest.raises(Y.Y4Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:
        monkeypatch.setenv(k, "1")
    with pytest.raises(Y.Y4Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: event study + 8 configs; round breaks win, shifted breaks lose -> the pair is shortlisted
    tr = _run("train", st, market("train", T0, 64, 26, 4, 1))
    assert set(tr["configs"]) == {Y.config_key(p) for p in Y.GRID}
    d = tr["decision"]
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_written"], d
    assert d["candidate"].startswith("break|") and d["candidate"].endswith("|round")
    assert d["twin"] == d["candidate"].replace("round", "shifted")
    assert all(e["censored_share"] == 0 for e in tr["configs"].values() if e["n"])
    es = tr["event_study"]
    assert es["cells"]["round|BREAK|h15"]["n"] == 64 and es["cells"]["shifted|BREAK|h15"]["n"] == 26
    assert es["roundness"]["BREAK|h15"]["diff"] > 0.2
    assert tr["predictions"]["P1_round_break_continues_more"]["folklore_supported"] is True
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if C.hypothesis_family(v["hypothesis"]) == "Y4") == 9
    assert led["n_trials_total"] == 2575 + 9
    with pytest.raises(Y.Y4Refused, match="final"):
        _run("train", st, market("train", T0, 64, 26, 4, 1))
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Y.Y4Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Y4 test prereg\n")
    with pytest.raises(Y.Y4Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    for stage in ("confirm", "final"):
        with pytest.raises(Y.Y4Refused, match="VAL result|before TEST"):
            _check(stage, st, env=env_all)
    sl = (st.sl / "Y4.json").read_text()
    (st.sl / "Y4.json").unlink()
    with pytest.raises(Y.Y4Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Y4.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 2, 2))
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"candidate", "twin"}
    assert va["configs"]["candidate"]["params_hash"] in json.loads(sl)["hashes"]
    assert va["round_minus_shifted"] > 0
    with pytest.raises(Y.Y4Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 20, 8, 2, 3)
    with pytest.raises(Y.Y4Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert set(te["configs"]) == {"candidate", "twin"}
    with pytest.raises(Y.Y4Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Y.Y4Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if C.hypothesis_family(v["hypothesis"]) == "Y4") == 9
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 64, 26, 2, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(Y.Y4Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 12, 4, 2, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(Y.Y4Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Y.Y4Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Y.Y4Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 20, 8, 4, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Y.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2, env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden")
        for k in ("mean", "ci90", "placebo", "controls", "reasons", "stress", "portfolio", "by_level",
                  "cost_decomposition"):
            assert k not in e
    assert doc["configs"]["break|h15|round"]["n"] == 20 and doc["configs"]["break|h15|shifted"]["n"] == 8
    es = doc["event_study"]
    assert es["stats"].startswith("hidden") and "cells" not in es and "roundness" not in es
    assert es["touch_counts"]["round|BREAK"] == 20
    assert doc["event_counts"]["by_set"]["round"]["break_coins"] == 20
    assert all(r["debug"] and r["mean"] is None for r in json.loads(st.ledger.read_text())["runs"])
    md = (st.out / "debug.md").read_text().lower()
    assert "fwd" not in md and "roundness" not in md and "mean " not in md

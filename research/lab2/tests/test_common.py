"""Tests for research/lab2/common.py: lookahead, splits, universe, fills, costs, placebo, stats, ledger, verdicts."""

import json
import math

import numpy as np
import pandas as pd
import pytest

import common as C
from conftest import POOLED, make_frames, real_flow_available

SOL = C.SolUsd(fallback=100.0)


def _ds(frames, split="train", census=None, **kw):
    g, c, b = frames
    return C.Dataset.from_frames(split, g, c, b, census=census or C.Census.empty(), sol=SOL, **kw)


# =========================================================================== splits


def _census(**kw):
    base = dict(split_of={"CEN_T": "final_train", "CEN_V": "final_val", "CEN_X": "final_test"},
                created_ts={"CEN_T": C.FINAL_LO + 100.0, "CEN_V": C.FINAL_LO + 50_000.0, "CEN_X": C.FINAL_LO + 70_000.0},
                started_ts=C.FINAL_LO + 81_000.0, created_max_ts=C.FINAL_LO + 80_000.0,
                train_hi=C.FINAL_LO + 45_000.0, val_hi=C.FINAL_LO + 65_000.0)
    base.update(kw)
    return C.Census(**base)


@pytest.mark.parametrize("created,expected", [
    (C.utc_ts("2026-09-16") - 1, "out"),
    (C.utc_ts("2026-09-16"), "confirm"),
    (C.utc_ts("2026-10-01") - 1, "confirm"),
    (C.utc_ts("2026-10-01"), "train"),
    (C.utc_ts("2026-10-05") - 1, "train"),
    (C.utc_ts("2026-10-05"), "val"),
    (C.utc_ts("2026-10-06 12:00") - 1, "val"),
    (C.utc_ts("2026-10-06 12:00"), "test"),
    (C.FINAL_LO - 1, "test"),
])
def test_split_boundaries_exact(created, expected):
    s, c, exact = C.assign_split(float(created), created + 100.0, "X", _census())
    assert (s, c, exact) == (expected, float(created), True)


def test_split_bounds_constants():
    assert C.utc_str(C.SPLIT_BOUNDS["train"][0]) == "2026-10-01 00:00:00"
    assert C.utc_str(C.SPLIT_BOUNDS["val"][1]) == "2026-10-06 12:00:00"
    assert C.SPLIT_BOUNDS["test"][1] == C.FINAL_LO
    assert C.utc_str(C.FINAL_LO).startswith("2026-10-07 19:37")
    # contiguous, non-overlapping
    names = ["confirm", "train", "val", "test"]
    for a, b in zip(names, names[1:]):
        assert C.SPLIT_BOUNDS[a][1] == C.SPLIT_BOUNDS[b][0]


def test_split_final_rules():
    cen = _census()
    # census membership wins, with the census creation time
    assert C.assign_split(None, C.FINAL_LO + 200.0, "CEN_T", cen)[:3] == ("final_train", C.FINAL_LO + 100.0, True)
    assert C.assign_split(1.0, C.FINAL_LO + 60_000.0, "CEN_V", cen)[0] == "final_val"
    assert C.assign_split(None, C.FINAL_LO + 75_000.0, "CEN_X", cen)[0] == "final_test"
    # non-census coin created in the window that graduated after the census started -> sealed
    assert C.assign_split(C.FINAL_LO + 10.0, cen.started_ts + 5, "N1", cen)[0] == "final_test"
    # non-census exact creation before the census -> by the lab's bounds
    assert C.assign_split(C.FINAL_LO + 10.0, C.FINAL_LO + 20.0, "N2", cen)[0] == "final_train"
    assert C.assign_split(C.FINAL_LO + 50_000.0, C.FINAL_LO + 50_010.0, "N3", cen)[0] == "final_val"


def test_split_unknown_creation_uses_upper_bound():
    cen = _census()
    g = C.utc_ts("2026-10-05") + 1000.0
    s, c, exact = C.assign_split(None, g, "SLOW", cen)
    assert not exact and c == g - 1800 and s == "train"          # latest possible creation -> later split only
    s, _, _ = C.assign_split(None, C.utc_ts("2026-10-05") + 1800.0, "SLOW2", cen)
    assert s == "val"
    # unknown creation, not in the census, graduated before the census, bound inside FINAL -> created before the
    # census window -> sealed TEST
    s, _, _ = C.assign_split(None, C.FINAL_LO + 10_000.0, "SLOW3", cen)
    assert s == "test"


def test_dataset_split_membership_by_created_ts():
    g, c, b = make_frames(n=10, t0=C.utc_ts("2026-10-04 20:00"), spacing=3600, slow_every=0)
    ds_tr = C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=SOL)
    ds_va = C.Dataset.from_frames("val", g, c, b, census=C.Census.empty(), sol=SOL, _internal=True)
    assert set(ds_tr.mints).isdisjoint(ds_va.mints)
    assert all(ds_tr.coin(m).row["created_ts"] < C.SPLIT_BOUNDS["train"][1] for m in ds_tr.mints)
    assert all(ds_va.coin(m).row["created_ts"] >= C.SPLIT_BOUNDS["val"][0] for m in ds_va.mints)


# =========================================================================== guards


def test_guarded_splits_need_env(frames, monkeypatch):
    for v in ("LAB2_ALLOW_TEST", "LAB2_ALLOW_FINAL", "LAB2_ALLOW_CONFIRM", "LAB2_ALLOW_VAL"):
        monkeypatch.delenv(v, raising=False)
    g, c, b = frames
    for split in ("test", "confirm", "final", "final_val", "final_test", "val"):
        with pytest.raises(C.SplitLocked):
            C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL)
        with pytest.raises(C.SplitLocked):
            C.load(split)
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    C.Dataset.from_frames("test", g, c, b, census=C.Census.empty(), sol=SOL)
    ds = C.Dataset.from_frames("final_train", g, c, b, census=C.Census.empty(), sol=SOL)
    assert ds.debug_only and ds.coverage["debug_only"]


# =========================================================================== universe and NULLs


def test_tradeable_filter_and_reasons():
    g, c, b = make_frames(n=8, slow_every=0)
    g.loc[0, "pool_quote_mint"] = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"   # USDC
    g.loc[1, "is_mayhem"] = 1                                                     # Mayhem flag
    g.loc[2, "rsol_complete"] = 12.0                                             # derived Mayhem
    c.loc[3, "virt_sol"] = 0.0                                                   # virt-less
    c = c.drop(index=4)                                                          # no B2 row
    last_g = g.loc[5, "g_ts"]
    b = b[~((b["mint"] == g.loc[5, "mint"]) & (b["minute_ts"] >= last_g + 3600 * 2))]
    b = b[~(b["minute_ts"] // 3600 * 3600 == (last_g + 7200) // 3600 * 3600)]     # a missing chain hour
    ds = C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=SOL)
    reasons = dict(zip(ds.excluded["mint"], ds.excluded["exclude_reason"]))
    assert reasons[g.loc[0, "mint"]] == "not_sol_quoted"
    assert reasons[g.loc[1, "mint"]] == "mayhem"
    assert reasons[g.loc[2, "mint"]] == "mayhem"
    assert reasons[g.loc[3, "mint"]] == "virt_unknown"
    assert reasons[g.loc[4, "mint"]] == "no_b2_row"
    assert reasons[g.loc[5, "mint"]] == "b2_window_incomplete"
    assert ds.coverage["excluded"]["mayhem"] == 2
    assert set(ds.mints).isdisjoint(reasons)


def test_null_never_zero_for_missing_creation(ds_train):
    slow = [m for m in ds_train.mints if not ds_train.coin(m).row["has_create"]]
    fast = [m for m in ds_train.mints if ds_train.coin(m).row["has_create"]]
    assert slow and fast
    s = ds_train.asof(slow[0], ds_train.coin(slow[0]).g + 600)
    for f in ("l_buy_sol", "z_buy_tok", "sn60_n_buyers", "creator_buy_sol", "first20_buy_sol", "curve_top3_buy_sol",
              "grad_delay_s", "creator", "is_mayhem"):
        assert s[f] is None, f
    with pytest.raises(TypeError):
        _ = s["z_buy_tok"] / 793.1e6 >= 0.6
    assert s["grad_delay_lb_s"] == 1800.0 and s["curve_partial"] is True
    f = ds_train.asof(fast[0], ds_train.coin(fast[0]).g + 600)
    assert f["l_buy_sol"] == 40.0 and f["grad_delay_s"] is not None and f["grad_delay_s"] < 10


def test_census_fills_exact_creation_time(frames):
    g, c, b = frames
    slow = g[g["has_create"] == 0].iloc[0]
    cen = C.Census(split_of={}, created_ts={slow["mint"]: float(slow["g_ts"] - 5000)}, started_ts=math.inf,
                   created_max_ts=math.inf, train_hi=0.0, val_hi=0.0)
    ds = C.Dataset.from_frames("train", g, c, b, census=cen, sol=SOL)
    s = ds.asof(slow["mint"], slow["g_ts"] + 600)
    assert s["grad_delay_s"] == 5000.0 and s["created_exact"] is True
    assert s["l_buy_sol"] is None      # launch features still unobserved


# =========================================================================== as-of legality


def test_forbidden_columns_raise(ds_train):
    m = ds_train.mints[0]
    s = ds_train.asof(m, ds_train.coin(m).g + 3000)
    for f in ("n_chunks", "n_pools", "virt_sol", "w_exact", "split", "tradeable", "created_ub_ts", "in_census",
              "reply_count", "market_cap", "price_repaired"):
        with pytest.raises(C.ForbiddenFeature):
            s[f]
        with pytest.raises(C.ForbiddenFeature):
            s.get(f)
        assert f not in s.features()
    with pytest.raises(KeyError):
        s["no_such_column"]
    assert not hasattr(s.bars, "price_repaired")


def test_unknown_column_fails_closed(frames):
    g, c, b = frames
    c = c.assign(brand_new_future_col=1.0)
    ds = C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=SOL)
    m = ds.mints[0]
    s = ds.asof(m, ds.coin(m).g + 5000)
    with pytest.raises(C.ForbiddenFeature):
        s["brand_new_future_col"]
    assert "brand_new_future_col" not in s.features()


def test_w120_w300_timing(ds_train):
    m = ds_train.mints[0]
    g = ds_train.coin(m).g
    with pytest.raises(C.NotYetKnown):
        ds_train.asof(m, g + 139.9)["w120_buy_sol"]
    assert ds_train.asof(m, g + 140)["w120_buy_sol"] == 30.0
    with pytest.raises(C.NotYetKnown):
        ds_train.asof(m, g + 319)["w300_buy_sol"]
    assert ds_train.asof(m, g + 320)["w300_n_buyers"] == 15
    assert "w120_buy_sol" not in ds_train.asof(m, g + 139).features()


def test_agent_timing(ds_train):
    with_agent = [m for m in ds_train.mints if ds_train.coin(m).row["agent_present"]]
    no_agent = [m for m in ds_train.mints if not ds_train.coin(m).row["agent_present"]]
    m = with_agent[0]
    cd = ds_train.coin(m)
    ka = cd.row["agent_known_at"]
    before = ds_train.asof(m, ka + 19)        # tau = known_at - 1
    assert before.agent_detected is False and not before.agent_resolved
    for f in ("agent_present", "agent_wallet", "agent_known_at", "agent_sol", "w120_top5_share_ex_agent"):
        with pytest.raises(C.NotYetKnown):
            before[f]
    assert np.isnan(before.bars.agent_buy_sol).all()
    after = ds_train.asof(m, ka + 20)
    assert after.agent_detected and after["agent_present"] is True and after["agent_wallet"] == cd.row["agent_wallet"]
    with pytest.raises(C.NotYetKnown):       # window totals wait for the 420 s window
        after["agent_sol"]
    late = ds_train.asof(m, cd.g + C.AGENT_WINDOW_S + 20)
    assert late["agent_sol"] == 17.58 and late["w120_top5_share_ex_agent"] == 0.7
    assert np.nansum(late.bars.agent_buy_sol) > 0
    # no agent: "absent" is only decided at the end of the window
    n = no_agent[0]
    gn = ds_train.coin(n).g
    with pytest.raises(C.NotYetKnown):
        ds_train.asof(n, gn + 400)["agent_present"]
    assert ds_train.asof(n, gn + C.AGENT_WINDOW_S + 20)["agent_present"] is False
    assert ds_train.asof(n, gn + 400).non_agent_buy_sol(300) is None
    assert ds_train.asof(n, gn + 500).non_agent_buy_sol(300) is not None


def test_bars_only_completed_minutes(ds_train):
    m = ds_train.mints[1]
    cd = ds_train.coin(m)
    for k in (1, 2, 7, 60, 179):
        t = cd.m0 + 60 * k + 20                       # tau = end of bar k - 1
        s = ds_train.asof(m, t)
        assert len(s.bars) == k and s.bars.minute_ts[-1] + 60 <= s.tau
        assert len(ds_train.asof(m, t - 0.5).bars) == k - 1
        assert s.price == cd.arr["c"][k - 1]
    with pytest.raises(ValueError):
        s.bars.c[0] = 1.0                            # read-only


def test_pooled_accounts_removed_from_top_lists(ds_train):
    m = [m for m in ds_train.mints if ds_train.coin(m).row["agent_present"]][0]
    cd = ds_train.coin(m)
    s = ds_train.asof(m, cd.g + 500)
    lst = s["w120_top10"]
    assert POOLED not in [w[0] for w in lst]
    tb = s.top_buyers("w120", exclude_agent=True)
    assert cd.row["agent_wallet"] not in [w[0] for w in tb] and len(tb) == len(lst) - 1


def test_top_buyers_needs_agent_decision(frames):
    g, c, b = frames
    c = c.copy()
    c["agent_known_at"] = np.where(c["agent_present"], c["g_ts"] + 200.0, np.nan)
    ds = C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=SOL)
    m = [m for m in ds.mints if ds.coin(m).row["agent_present"]][0]
    with pytest.raises(C.NotYetKnown):
        ds.asof(m, ds.coin(m).g + 150).top_buyers("w120")
    assert ds.asof(m, ds.coin(m).g + 150).top_buyers("w120", exclude_agent=False) is not None


# =========================================================================== garbage after the cutoff


def _garble(frames, mint, tau, rng):
    """Replace every datum about ``mint`` that lies after ``tau`` with garbage (incl. new and removed rows)."""
    g, c, b = (x.copy() for x in frames)
    b = b.astype({k: "float64" for k in b.columns if pd.api.types.is_numeric_dtype(b[k]) and k not in ("minute_ts",)})
    c = c.astype({k: "float64" for k in c.columns if pd.api.types.is_integer_dtype(c[k])})
    gi = g.index[g["mint"] == mint][0]
    gts = float(g.loc[gi, "g_ts"])
    m0 = int(gts) // 60 * 60
    fut = (b["mint"] == mint) & (b["minute_ts"] + 60 > tau)
    num = ["n_buys", "n_sells", "n_dust", "buy_sol", "sell_sol", "buy_tok", "sell_tok", "n_buyers", "n_sellers",
           "top5_buy_sol", "agent_buy_sol"]
    for col in num:
        b.loc[fut, col] = rng.uniform(0, 1e4, fut.sum())
    px = rng.uniform(1e-9, 1e-3, fut.sum())
    b.loc[fut, "open"], b.loc[fut, "close"] = px, px * rng.uniform(0.5, 2, fut.sum())
    b.loc[fut, "high"], b.loc[fut, "low"] = px * 3, px / 3
    b.loc[fut, "x_close"], b.loc[fut, "y_close"] = rng.uniform(1, 1e4, fut.sum()), rng.uniform(1e6, 1e9, fut.sum())
    drop = b.index[fut][rng.random(fut.sum()) < 0.3]
    b = b.drop(index=drop)
    # new rows in future minutes that had no trades
    have = set(b.loc[b["mint"] == mint, "minute_ts"])
    new = []
    for j in range(C.N_BARS):
        ts = m0 + 60 * j
        if ts + 60 > tau and ts not in have and rng.random() < 0.5:
            row = b[b["mint"] == mint].iloc[0].to_dict()
            row.update({"minute_ts": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "y_close": 7.0,
                        "x_close": 3.0, "buy_sol": 999.0})
            new.append(row)
    if new:
        b = pd.concat([b, pd.DataFrame(new)], ignore_index=True)
    ci = c.index[c["mint"] == mint][0]
    if tau < gts + C.W120_S:
        for col in ("w120_buy_sol", "w120_sell_sol", "w120_n_buyers", "w120_n_sellers"):
            c.loc[ci, col] = rng.uniform(0, 1e4)
        c.loc[ci, "w120_top10"] = json.dumps([["GARBAGE", 1e9, 0.0]])
    if tau < gts + C.W300_S:
        for col in ("w300_buy_sol", "w300_sell_sol", "w300_n_buyers", "w300_n_sellers"):
            c.loc[ci, col] = rng.uniform(0, 1e4)
        c.loc[ci, "w300_top10"] = json.dumps([["GARBAGE", 1e9, 0.0]])
    ka = c.loc[ci, "agent_known_at"]
    present = bool(c.loc[ci, "agent_present"]) and not (isinstance(ka, float) and math.isnan(ka))
    agent_known = present and ka <= tau
    legal_win = max(gts + C.AGENT_WINDOW_S, ka) if present else gts + C.AGENT_WINDOW_S
    if tau < legal_win:   # window totals: after the 420 s window (and known_at when there is an agent)
        for col in ("agent_slices", "agent_sol", "agent_median_gap", "agent_gap_cv", "agent_gap_band_share",
                    "w120_top5_share_ex_agent"):
            c.loc[ci, col] = rng.uniform(0, 1e3)
    if not agent_known and tau < gts + C.AGENT_WINDOW_S:   # identity: at known_at, or g + 420 when absent
        c.loc[ci, "agent_wallet"] = "GARBAGE_AGENT"
        c.loc[ci, "agent_first_offset_s"] = rng.uniform(0, 400)
        if present:   # a future event stays in the future
            c.loc[ci, "agent_known_at"] = tau + rng.uniform(1, 300)
    # forbidden columns may carry anything
    c.loc[ci, "n_chunks"] = 99
    c.loc[ci, "w_exact"] = False
    g.loc[gi, "n_pools"] = 7
    return g, c, b


def _decisions(ds, mint, t_max):
    """A strategy-like reader: everything it looks at up to t_max."""
    out = []
    cd = ds.coin(mint)
    for k in range(1, C.N_BARS):
        t = cd.bar_start(k) + C.GRID_OFFSET_S
        if t > t_max:
            break
        s = ds.asof(mint, t)
        out.append((t, round(s.price, 18), s.vol_sol(900), s.ret(300), s.agent_detected, s.get("w120_buy_sol"),
                    s.non_agent_buy_sol(300)))
    return out


def _snapshot(ds, mint, t):
    s = ds.asof(mint, t)
    bars = s.bars.as_frame()
    return s.features(), bars


@pytest.mark.parametrize("seed", range(6))
def test_garbage_after_cutoff_changes_nothing_before(frames, seed):
    rng = np.random.default_rng(seed)
    clean = _ds(frames)
    for _ in range(25):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([25, 60, 100, 139, 141, 200, 330, 439, 441, 600, 1800, 5000, 10000]))
        t += float(rng.uniform(0, 59))
        tau = t - C.DECISION_LAG_S
        dirty = _ds(_garble(frames, m, tau, rng))
        f0, b0 = _snapshot(clean, m, t)
        f1, b1 = _snapshot(dirty, m, t)
        assert f0 == f1
        pd.testing.assert_frame_equal(b0, b1)
        assert _decisions(clean, m, t) == _decisions(dirty, m, t)


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_garbage_after_cutoff_real_census_train():
    """PLAN 6.6 rule 9 on real data: 200 random (mint, tau) pairs on the census TRAIN third (debug split)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    clean = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(42)
    mints = [clean.mints[int(i)] for i in rng.choice(len(clean.mints), size=40, replace=False)]
    sub = tuple(x[x["mint"].isin(mints)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for _ in range(5):
            t = cd.g + float(rng.uniform(20, 10800))
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - 20, rng), census=cen, sol=SOL)
            f0, b0 = _snapshot(clean, m, t)
            f1, b1 = _snapshot(dirty, m, t)
            assert f0 == f1
            pd.testing.assert_frame_equal(b0, b1)
            n += 1
    assert n == 200


def test_decisions_before_t_unchanged_by_future_garbage(frames):
    """Backtest-level: entries decided at or before T are identical when every bar after T - 20 is garbage."""
    rng = np.random.default_rng(3)
    clean = _ds(frames)

    def strat(snap, p, pos):
        if pos is None and snap.age_s >= 300 and snap.ret(300) > 0.0:
            return C.Enter(exits=C.ExitSpec(max_hold_s=600))
        return None

    for m in clean.mints[:8]:
        cd = clean.coin(m)
        T = cd.g + 3000
        dirty = _ds(_garble(frames, m, T - 20, rng))
        a = C.run_trades(clean, strat, {}, C.FillConfig(), mints=[m])
        b = C.run_trades(dirty, strat, {}, C.FillConfig(), mints=[m])
        a_dec = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
        b_dec = b.loc[b["t_dec"] <= T, "t_dec"].tolist()
        assert a_dec == b_dec
        if len(a) and a["t_dec"].iloc[0] <= T:
            assert len(b) and b["t_dec"].iloc[0] == a["t_dec"].iloc[0]


# =========================================================================== costs and fills


@pytest.mark.parametrize("mcap_sol", [18, 150, 419.9, 420, 1000, 1470, 5000, 50_000, 98_239, 98_240, 2e6])
def test_fee_tiers_by_date_match_costs(mcap_sol):
    ts = C.utc_ts("2026-10-03")
    assert C.fee_bps_at(ts, mcap_sol) == C.lab_costs.fee_bps(mcap_sol * 100.0, "pumpswap", 100.0)


def test_fee_schedule_before_first_schedule_raises():
    with pytest.raises(ValueError):
        C.fee_bps_at(C.utc_ts("2026-01-01"), 400)


@pytest.mark.parametrize("mcap_sol", [20, 410, 900, 3000, 40_000, 200_000])
@pytest.mark.parametrize("usd", [5.0, 20.0, 50.0])
@pytest.mark.parametrize("stress", [1.0, 1.5])
def test_cost_parity_with_lab_costs(mcap_sol, usd, stress):
    """Same k, price and fees -> identical tokens, SOL back and round-trip cost as research/lab/costs.py."""
    S = 106.0
    k = C.lab_costs.K_GRAD
    p = mcap_sol / 1e9
    model = C.CostModel().stressed(stress)
    ctx = C.lab_costs.CoinCostContext(k_sol=k)
    ts = C.utc_ts("2026-10-08")
    tok_c, _ = model.buy(usd, p * S, ctx, S)
    tok_o, br = C.simulate_buy(usd / S, p, k, ts, model)
    assert tok_o == pytest.approx(tok_c, rel=1e-10)
    usd_c, _ = model.sell(tok_c, p * S, ctx, S)
    sol_o, _ = C.simulate_sell(tok_o, p, k, ts, model)
    assert sol_o * S == pytest.approx(usd_c, rel=1e-10)
    rt_c = C.lab_costs.round_trip_cost_pct(usd, p * S * 1e9, model, S, ctx)
    rt_o = C.round_trip_pct(usd / S, p, k, ts, model)
    assert rt_o == pytest.approx(rt_c, rel=1e-9)
    assert C.network_sol(model) * S == pytest.approx(model.network_usd(S))


def test_round_trip_in_task_range():
    """A $20 round trip on a canonical pool costs 0.8-4.7 % depending on market cap (task statement)."""
    k = 84.99 * 206.9e6 * 1.2
    ts = C.utc_ts("2026-10-08")
    lo = C.round_trip_pct(20 / 106, 1e8 / 1e9 / 106 * 1e-0 * 1e-0 * 1e0 / 1e0, k, ts)   # ~$100M mcap
    hi = C.round_trip_pct(20 / 106, 30 / 1e9, k, ts)                                    # 30 SOL mcap
    assert 0.6 < lo < 1.5 and 3.0 < hi < 6.0


@pytest.mark.parametrize("mcap_sol", [20, 400, 5000])
def test_fill_simulator_monotone_in_size(mcap_sol):
    k, p, ts = 84.99 * 206.9e6, mcap_sol / 1e9, C.utc_ts("2026-10-08")
    sizes = [0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 20]
    toks = [C.simulate_buy(s, p, k, ts)[0] for s in sizes]
    avg = [s / t for s, t in zip(sizes, toks)]
    assert all(b > a for a, b in zip(toks, toks[1:]))           # more SOL -> more tokens
    assert all(b > a for a, b in zip(avg, avg[1:]))             # ... at a worse average price
    outs = [C.simulate_sell(t, p, k, ts)[0] for t in toks]
    sell_px = [o / t for o, t in zip(outs, toks)]
    assert all(b > a for a, b in zip(outs, outs[1:]))
    assert all(b < a for a, b in zip(sell_px, sell_px[1:]))
    no_net = C.CostModel(priority_sol=0.0, base_fee_lamports=0)
    rts = [C.round_trip_pct(s, p, k, ts, no_net) for s in sizes]
    assert all(b > a for a, b in zip(rts, rts[1:]))             # bigger ticket -> bigger % cost (impact)
    with_net = [C.round_trip_pct(s, p, k, ts) for s in sizes]
    assert with_net[0] > with_net[2]                            # tiny tickets: the fixed network fee dominates


def test_virtual_reserve_pricing():
    x, v, y = 67.4, 17.58, 206.9e6
    assert C.pool_price(x, v, y) == pytest.approx((x + v) / y)
    assert C.pool_price(x, v, y) > x / y * 1.25          # ignoring v under-prices a fresh pool
    X, yy = C.reserves_at_price((x + v) * y, C.pool_price(x, v, y))
    assert X == pytest.approx(x + v) and yy == pytest.approx(y)


def test_dense_bars_reserve_identity(ds_train):
    """X = close * y_close = x + v; the invariant before bar 0 is the initial pool."""
    cd = ds_train.coin(ds_train.mints[0])
    a = cd.arr
    traded = a["traded"] > 0
    assert np.allclose(a["X"][traded], a["x_real"][traded] + 17.584505289, rtol=1e-9)
    assert cd.k_before(0) == pytest.approx(84.990359 * 206.9e6)
    assert cd.k_before(5) == pytest.approx(a["X"][4] * a["y"][4])


# =========================================================================== engine on handcrafted bars


def _one_coin(prices):
    """One coin with explicit bars: prices = list of (o, h, l, c) per minute index (None = no trades)."""
    g, c, b = make_frames(n=1, slow_every=0, agent_every=0, n_minutes=1)
    gts = int(g.loc[0, "g_ts"])
    m0 = gts // 60 * 60
    rows = []
    y = 206.9e6
    for j, pr in enumerate(prices):
        if pr is None:
            continue
        o, h, l, cl = pr
        rows.append({**b.iloc[0].to_dict(), "minute_ts": m0 + 60 * j, "open": o, "high": h, "low": l, "close": cl,
                     "y_close": y, "x_close": cl * y - 17.584505289})
    for j in range(len(prices), C.N_BARS + 2):
        rows.append({**b.iloc[0].to_dict(), "minute_ts": m0 + 60 * j, "open": prices[-1][3], "high": prices[-1][3],
                     "low": prices[-1][3], "close": prices[-1][3], "y_close": y,
                     "x_close": prices[-1][3] * y - 17.584505289})
    return C.Dataset.from_frames("train", g, c, pd.DataFrame(rows), census=C.Census.empty(), sol=SOL)


P = 4e-7


def _enter_at(k_dec, exits=C.ExitSpec(), exit_at=None):
    """Enter at the decision at the end of bar k_dec - 1; optional signal exit at the end of bar exit_at - 1."""
    def strat(snap, p, pos):
        j = snap.k   # completed bars
        if pos is None:
            return C.Enter(exits=exits) if j == k_dec else None
        if exit_at is not None and j == exit_at:
            return C.Exit("x")
        return None
    return strat


def test_worst_entry_and_signal_exit_prices():
    bars = [(P, P, P, P)] * 3 + [(P, 1.3 * P, 0.9 * P, 1.1 * P)] + [(1.1 * P, 1.2 * P, 1.0 * P, 1.1 * P)] * 2 + \
           [(1.1 * P, 1.4 * P, 0.8 * P, 1.2 * P)] + [(1.2 * P, 1.2 * P, 1.2 * P, 1.2 * P)] * 3
    ds = _one_coin(bars)
    t = C.run_trades(ds, _enter_at(3, exit_at=6), {}, C.FillConfig())
    assert len(t) == 1
    r = t.iloc[0]
    assert r["entry_price"] == pytest.approx(1.3 * P)            # max(open, high) of bar 3
    assert r["exit_price"] == pytest.approx(0.8 * P)             # min(open, low) of bar 6
    assert r["reason"] == "signal:x"
    cd = ds.coin(ds.mints[0])
    assert r["t_in"] == cd.bar_start(3) + 50 and r["t_out"] == cd.bar_start(6) + 50
    t2 = C.run_trades(ds, _enter_at(3, exit_at=6), {}, C.FillConfig(entry_fill="open", exit_fill="open"))
    assert t2.iloc[0]["entry_price"] == pytest.approx(P) and t2.iloc[0]["exit_price"] == pytest.approx(1.1 * P)
    assert t2.iloc[0]["ret_net"] > r["ret_net"]
    # latency 45 s lands one bar later
    t3 = C.run_trades(ds, _enter_at(3), {}, C.FillConfig(latency_s=45))
    assert t3.iloc[0]["entry_price"] == pytest.approx(1.2 * P)


def test_stop_take_profit_time_exits():
    flat = [(P, P, P, P)] * 3
    ds = _one_coin(flat + [(P, P, P, P), (P, P, 0.7 * P, 0.75 * P)] + [(0.75 * P,) * 4] * 3)
    t = C.run_trades(ds, _enter_at(3, C.ExitSpec(stop_pct=0.2)), {}, C.FillConfig())
    assert t.iloc[0]["reason"] == "stop" and t.iloc[0]["exit_price"] == pytest.approx(0.7 * P)
    t = C.run_trades(ds, _enter_at(3, C.ExitSpec(stop_pct=0.2)), {}, C.FillConfig(exit_delay_bars=1))
    assert t.iloc[0]["reason"] == "stop" and t.iloc[0]["exit_price"] == pytest.approx(0.75 * P)
    ds = _one_coin(flat + [(P, P, P, P), (P, 1.6 * P, P, 1.55 * P), (P, 1.6 * P, P, 1.2 * P)] + [(P,) * 4] * 3)
    t = C.run_trades(ds, _enter_at(3, C.ExitSpec(take_profit_pct=0.5)), {}, C.FillConfig())
    assert t.iloc[0]["reason"] == "take_profit" and t.iloc[0]["exit_price"] == pytest.approx(1.5 * P)
    ds = _one_coin(flat + [(P, P, P, P), (P, 1.6 * P, P, 1.2 * P)] + [(P,) * 4] * 3)
    t = C.run_trades(ds, _enter_at(3, C.ExitSpec(take_profit_pct=0.5)), {}, C.FillConfig())
    assert t.iloc[0]["exit_price"] == pytest.approx(1.2 * P)    # closed below the level: body top
    ds = _one_coin(flat * 4)
    t = C.run_trades(ds, _enter_at(3, C.ExitSpec(max_hold_s=120)), {}, C.FillConfig())
    cd = ds.coin(ds.mints[0])
    assert t.iloc[0]["reason"] == "time" and t.iloc[0]["t_out"] == cd.bar_start(6)
    assert t.iloc[0]["t_out"] >= t.iloc[0]["t_in"]


def test_entry_bar_exits_knob_and_exit_after_landing():
    bars = [(P, P, P, P)] * 3 + [(P, 1.3 * P, 0.7 * P, P)] + [(P,) * 4] * 4
    ds = _one_coin(bars)
    t = C.run_trades(ds, _enter_at(3, C.ExitSpec(stop_pct=0.25)), {}, C.FillConfig())
    assert t.iloc[0]["reason"] == "stop" and t.iloc[0]["t_out"] >= t.iloc[0]["t_in"]
    t = C.run_trades(ds, _enter_at(3, C.ExitSpec(stop_pct=0.25, max_hold_s=200)), {}, C.FillConfig(entry_bar_exits=False))
    assert t.iloc[0]["reason"] == "time"


def test_one_position_per_coin_and_horizon(ds_train):
    def always(snap, p, pos):
        return C.Enter() if pos is None else None
    t = C.run_trades(ds_train, always, {}, C.FillConfig())
    assert len(t) == len(ds_train) and t["mint"].is_unique
    assert (t["reason"] == "horizon").all()
    assert (t["t_in"] > t["g_ts"]).all()           # never on the curve
    calls = []

    def skipper(snap, p, pos):
        calls.append(snap.mint)
        return C.SKIP
    assert len(C.run_trades(ds_train, skipper, {}, C.FillConfig())) == 0
    assert len(calls) == len(ds_train)


def test_ret_net_accounting():
    ds = _one_coin([(P, P, P, P)] * 10)
    cfg = C.FillConfig()
    t = C.run_trades(ds, _enter_at(3, exit_at=5), {}, cfg).iloc[0]
    cd = ds.coin(ds.mints[0])
    sol_in = 20 / 100.0
    tok, _ = C.simulate_buy(sol_in, P, cd.k_before(3), t["t_in"], cfg.cost)
    back, _ = C.simulate_sell(tok, P, cd.k_before(5), t["t_out"], cfg.cost)
    assert t["ret_net"] == pytest.approx((back - sol_in - 2 * C.network_sol(cfg.cost)) / sol_in)
    rent = C.run_trades(ds, _enter_at(3, exit_at=5), {}, C.FillConfig(rent_usd=0.22)).iloc[0]
    assert rent["ret_net"] == pytest.approx(t["ret_net"] - 0.22 / 20)
    st = C.run_trades(ds, _enter_at(3, exit_at=5), {}, cfg.stressed(1.5)).iloc[0]
    assert st["ret_net"] < t["ret_net"]


# =========================================================================== placebo


def test_placebo_matched_timing(ds_train, tmp_ledger):
    def strat(snap, p, pos):
        if pos is None:
            return C.Enter(exits=C.ExitSpec(stop_pct=0.3, max_hold_s=900), tag="sig") if snap.age_s >= 900 else None
        return None
    res = C.backtest(strat, "train", {"a": 1}, hypothesis="T_PL", ds=ds_train, n_placebo=20)
    t, pl = res.trades, res.placebo
    assert len(t) == len(ds_train)
    assert (pl.groupby("signal").size() == 20).all()
    d = np.abs(pl["age_dec_s"].to_numpy() - t["age_dec_s"].to_numpy()[pl["signal"].to_numpy()])
    assert d.max() <= C.PLACEBO_AGE_TOL_S + 1e-9
    assert (pl["stop_pct"] == 0.3).all() and (pl["max_hold_s"] == 900).all() and pl["is_placebo"].all()
    assert set(pl["reason"]) <= {"stop", "time", "horizon"}
    assert pl["mint"].nunique() > 5
    s = res.summary(B=500)
    assert s["placebo"]["n_signals_matched"] == len(t)
    # determinism
    res2 = C.backtest(strat, "train", {"a": 1}, hypothesis="T_PL", ds=ds_train, n_placebo=20)
    pd.testing.assert_frame_equal(res.placebo, res2.placebo)


def test_placebo_eligible_filter(ds_train, tmp_ledger):
    def strat(snap, p, pos):
        return C.Enter(exits=C.ExitSpec(max_hold_s=300)) if pos is None and snap.age_s >= 600 else None
    seen = []

    def elig(snap):
        seen.append(snap.mint)
        return snap.mint != ds_train.mints[0]
    res = C.backtest(strat, "train", {}, hypothesis="T_EL", ds=ds_train, n_placebo=5, placebo_eligible=elig)
    assert ds_train.mints[0] not in set(res.placebo["mint"]) and seen


# =========================================================================== statistics


def test_coin_bootstrap_ci_covers_true_mean():
    """95 % coin-bootstrap CI covers the true mean ~95 % of the time on clustered synthetic data."""
    rng = np.random.default_rng(11)
    mu, cover, reps = 0.02, 0, 300
    for r in range(reps):
        n_coins = 60
        eff = rng.normal(0, 0.10, n_coins)
        rets, coins = [], []
        for i in range(n_coins):
            k = int(rng.integers(1, 4))
            rets += list(mu + eff[i] + rng.normal(0, 0.2, k))
            coins += [f"c{i}"] * k
        lo, hi = C.coin_bootstrap_ci(np.array(rets), coins, 0.95, B=1000, seed=r)
        cover += lo <= mu <= hi
    assert 0.90 <= cover / reps <= 0.985


def test_coin_bootstrap_resamples_coins_not_trades():
    rets = np.array([1.0] * 50 + [-1.0])          # one coin with 50 identical trades, one with a single loser
    coins = ["a"] * 50 + ["b"]
    m = C.coin_bootstrap_means(rets, coins, B=4000, seed=1)
    assert (m == -1.0).mean() == pytest.approx(0.25, abs=0.03)    # both draws = coin b


def test_describe_fields():
    t = pd.DataFrame({"mint": [f"m{i}" for i in range(10)], "ret_net": [0.5, 0.4] + [0.01] * 8,
                      "t_in": np.arange(10.0), "t_out": np.arange(10.0) + 60, "reason": ["time"] * 10})
    s = C.describe(t, B=500)
    assert s["n"] == 10 and s["mean"] == pytest.approx(0.098) and s["median"] == pytest.approx(0.01)
    assert s["win_rate"] == 1.0
    assert s["mean_without_top2"] == pytest.approx(0.01)
    assert s["top_coin_share"] == pytest.approx(0.5 / 0.98)
    assert s["halves"]["first"] == pytest.approx(np.mean([0.5, 0.4, 0.01, 0.01, 0.01]))
    assert s["ci95"][0] <= s["mean"] <= s["ci95"][1]


def test_deflated_sharpe_penalises_trials():
    rng = np.random.default_rng(0)
    r = rng.normal(0.03, 0.25, 200)
    d1 = C.deflated_sharpe(r, 10)["dsr"]
    d2 = C.deflated_sharpe(r, 3000)["dsr"]
    d3 = C.deflated_sharpe(r, 300_000)["dsr"]
    assert 0 <= d3 < d2 < d1 <= 1
    strong = rng.normal(0.30, 0.25, 300)
    assert C.deflated_sharpe(strong, 3000)["dsr"] > 0.99
    noise = rng.normal(0.0, 0.25, 300)
    assert C.deflated_sharpe(noise, 3000)["dsr"] < 0.5


def test_portfolio_sim_slots_and_skips():
    t = pd.DataFrame({"mint": [f"m{i}" for i in range(7)], "ret_net": [0.1] * 7,
                      "t_in": [0, 1, 2, 3, 4, 5, 100.0], "t_out": [50, 50, 50, 50, 50, 50, 150.0]})
    p = C.portfolio_sim(t)
    assert p["taken"] == 6 and p["skipped"] == 1 and p["skipped_mints"] == ["m5"]
    assert p["final_equity"] == pytest.approx(100 + 6 * 2.0)
    loss = t.assign(ret_net=-0.5)
    p2 = C.portfolio_sim(loss)
    assert p2["final_equity"] == pytest.approx(100 - 6 * 10.0) and p2["max_dd_pct"] > 0


# =========================================================================== trials ledger, shortlists, one-run rules


def test_trial_counter_increments(tmp_ledger):
    base = C.n_trials(tmp_ledger)
    assert base == 2575
    a = C.record_run("S1", {"th": 0.1}, "train", {"n": 10, "mean": 0.01}, tmp_ledger)
    assert a["new_trial"] and a["n_trials_total"] == base + 1
    b = C.record_run("S1", {"th": 0.1}, "train", None, tmp_ledger)
    assert not b["new_trial"] and b["n_trials_total"] == base + 1        # same config, no new trial
    C.record_run("S1", {"th": 0.25}, "train", None, tmp_ledger)
    C.record_run("D1", {"th": 0.1}, "train", None, tmp_ledger)
    assert C.n_trials(tmp_ledger) == base + 3
    C.record_run("S1", {"th": 0.9}, "final_train", None, tmp_ledger, debug=True)
    assert C.n_trials(tmp_ledger) == base + 3                            # debug runs never count
    led = json.loads(tmp_ledger.read_text())
    assert led["n_trials_total"] == base + 3 and len(led["runs"]) == 5


def test_backtest_records_every_grid_point(ds_train, tmp_ledger):
    def strat(snap, p, pos):
        return C.Enter(exits=C.ExitSpec(max_hold_s=300)) if pos is None and snap.age_s >= p["age"] else None
    n0 = C.n_trials()
    for age in (300, 600, 900):
        r = C.backtest(strat, "train", {"age": age}, hypothesis="GRID", ds=ds_train, placebo=False)
        assert r.meta["n_trials_total"] == n0 + (age // 300)
    assert C.n_trials() == n0 + 3


def test_variant_limit_flag(tmp_ledger):
    for i in range(4):
        r = C.record_run("H1", {"i": i}, "train", None, tmp_ledger)
    assert r["over_variant_limit"]


def test_val_needs_shortlist_and_freezes_it(frames, tmp_ledger, monkeypatch, tmp_path):
    g, c, b = make_frames(n=10, t0=C.utc_ts("2026-10-05 01:00"), spacing=3000)
    ds = C.Dataset.from_frames("val", g, c, b, census=C.Census.empty(), sol=SOL, _internal=True)
    strat = _enter_at(10)
    with pytest.raises(C.SplitLocked):
        C.backtest(strat, "val", {"a": 1}, hypothesis="S1", ds=ds)
    with pytest.raises(ValueError):
        C.write_shortlist("S1", [{"a": 1}, {"a": 2}, {"a": 3}])
    C.write_shortlist("S1", [{"a": 1}, {"a": 2}])
    C.backtest(strat, "val", {"a": 1}, hypothesis="S1", ds=ds, placebo=False)
    with pytest.raises(C.SplitLocked):
        C.backtest(strat, "val", {"a": 3}, hypothesis="S1", ds=ds)          # not shortlisted
    with pytest.raises(C.SplitLocked):
        C.write_shortlist("S1", [{"a": 3}])                                 # frozen after the first VAL run
    p = C.shortlist_dir() / "S1.json"
    doc = json.loads(p.read_text())
    doc["note"] = "edited later"
    p.write_text(json.dumps(doc))
    with pytest.raises(C.SplitLocked):
        C.backtest(strat, "val", {"a": 2}, hypothesis="S1", ds=ds)          # shortlist changed after VAL


def test_test_split_runs_once(tmp_ledger, monkeypatch):
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    g, c, b = make_frames(n=8, t0=C.utc_ts("2026-10-06 13:00"), spacing=3000)
    ds = C.Dataset.from_frames("test", g, c, b, census=C.Census.empty(), sol=SOL)
    strat = _enter_at(10, C.ExitSpec(max_hold_s=600))
    r = C.backtest(strat, "test", {"a": 1}, hypothesis="D1", ds=ds, n_placebo=3)
    assert "costs_x1.5" in r.stress and len(r.stress["costs_x1.5"]) == len(r.trades)
    assert (r.stress["costs_x1.5"]["ret_net"].to_numpy() < r.trades["ret_net"].to_numpy()).all()
    with pytest.raises(C.SplitLocked):
        C.backtest(strat, "test", {"a": 1}, hypothesis="D1", ds=ds)
    C.backtest(strat, "test", {"a": 1}, hypothesis="M1", ds=ds, placebo=False)     # another hypothesis is fine


def test_debug_split_hides_returns(frames, tmp_ledger):
    g, c, b = frames
    ds = C.Dataset.from_frames("final_train", g, c, b, census=C.Census.empty(), sol=SOL)
    # synthetic frames are in October-02; relabel the dataset's split for the engine
    assert ds.debug_only
    res = C.backtest(_enter_at(5, C.ExitSpec(max_hold_s=300)), "final_train", {}, hypothesis="DBG", ds=ds)
    s = res.summary()
    assert "mean" not in s and s["debug_only"]
    assert C.n_trials() == 2575


# =========================================================================== verdicts


def _result(rets, n_coins=None, t_in=None, placebo_shift=0.0, stress_shift=-0.01, split="test", decl=None):
    n = len(rets)
    coins = [f"c{i % (n_coins or n)}" for i in range(n)]
    t_in = np.arange(n, dtype=float) * 600 if t_in is None else t_in
    t = pd.DataFrame({"mint": coins, "ret_net": rets, "t_in": t_in, "t_out": t_in + 300, "g_ts": t_in - 600,
                      "reason": ["time"] * n})
    pl = pd.concat([t.assign(signal=np.arange(n), ret_net=np.asarray(rets) - placebo_shift)] * 2, ignore_index=True)
    st = {"costs_x1.5": t.assign(ret_net=np.asarray(rets) + stress_shift)}
    return C.Result(trades=t, placebo=pl, stress=st, meta={"split": split, "hypothesis": "H", "params": {},
                                                           "declarations": decl or {}})


def test_verdict_underpowered_pass_fail():
    rng = np.random.default_rng(5)
    small = _result(rng.normal(0.10, 0.05, 30))
    assert C.verdict_entry(small, B=500)["verdict"] == "UNDERPOWERED"
    few_coins = _result(rng.normal(0.10, 0.05, 80), n_coins=20)
    assert C.verdict_entry(few_coins, B=500)["verdict"] == "UNDERPOWERED"
    good = rng.normal(0.08, 0.10, 100)
    v = C.verdict_entry(_result(good, placebo_shift=0.10), val=_result(good, split="val"),
                        final=_result(good, split="final"), B=500)
    assert v["verdict"] == "PASS", v
    v = C.verdict_entry(_result(good, placebo_shift=0.10), B=500)
    assert v["verdict"] == "INCOMPLETE"                     # VAL sign / FINAL missing
    weak = rng.normal(0.01, 0.30, 100)
    v = C.verdict_entry(_result(weak, placebo_shift=0.10), val=_result(weak), final=_result(weak), B=500)
    assert v["verdict"] == "FAIL"
    no_ctrl = C.verdict_entry(_result(good, placebo_shift=0.02), val=_result(good), final=_result(good), B=500)
    assert no_ctrl["verdict"] == "FAIL" and not no_ctrl["criteria"][4]["pass"]


def test_auto_rejections():
    rets = np.array([3.0, 2.0] + [-0.05] * 98)
    v = C.verdict_entry(_result(rets, placebo_shift=0.5), B=300)
    assert v["verdict"] == "REJECTED" and "top 2" in v["auto_rejections"][0]
    r = _result(np.full(100, 0.05), decl={"uses_wallet_reputation": True})
    assert any("wallets" in x for x in C.auto_rejections(r))
    r = _result(np.full(100, 0.05), decl={"uses_organic_flow": True, "organic_excludes": ["AGENT", "DUST"]})
    assert any("organic" in x for x in C.auto_rejections(r))
    r = _result(np.full(100, 0.05), decl={"uses_organic_flow": True,
                                         "organic_excludes": ["AGENT", "BOT", "WASH", "DUST", "MECH"]})
    assert not C.auto_rejections(r)
    r = _result(np.full(100, 0.05))
    r.trades.loc[0, "t_in"] = r.trades.loc[0, "g_ts"] - 1
    assert any("curve phase" in x for x in C.auto_rejections(r))


def test_verdict_veto():
    rng = np.random.default_rng(2)
    n = 200
    host = pd.DataFrame({"mint": [f"c{i}" for i in range(n)], "ret_net": rng.normal(0.0, 0.1, n)})
    flagged = np.zeros(n, bool)
    flagged[:60] = True
    host.loc[flagged, "ret_net"] -= 0.3
    host.loc[flagged & (np.arange(n) % 10 == 0), "ret_net"] = 0.01
    v = C.verdict_veto(host, flagged, oos_host=host, oos_flagged=flagged, B=1000)
    assert v["verdict"] == "PASS", v
    assert C.verdict_veto(host.iloc[:40], flagged[:40])["verdict"] == "UNDERPOWERED"


# =========================================================================== real data (skipped when absent)


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_real_census_train_loads_with_coverage():
    ds = C.load("final_train")
    cov = ds.coverage
    assert ds.debug_only and cov["usable"] == len(ds) > 300
    assert set(cov["excluded"]) <= {"mayhem", "not_sol_quoted", "virt_unknown", "no_b2_row", "b2_window_incomplete",
                                    "truncated"}
    cd = ds.coin(ds.mints[0])
    assert cd.arr["X"][0] > 0 and np.all(np.isfinite(cd.arr["c"]))
    # initial pool price equals the first bar's open (X0 = pool_quote0, y0 = pool_base0)
    firsts = [ds.coin(m) for m in ds.mints[:100]]
    ok = [abs(c.arr["o"][0] / (c.init_X / c.init_y) - 1) < 1e-3 for c in firsts if c.arr["traded"][0]]
    assert np.mean(ok) > 0.95


# =========================================================================== helpers added for the hypothesis builders


def test_top_share_excludes_pooled_and_agent(ds_train):
    m = [m for m in ds_train.mints if ds_train.coin(m).row["agent_present"]][0]
    s = ds_train.asof(m, ds_train.coin(m).g + 500)
    # stored top list: pooled 9, Wa 5, AGENT 4, Wc 1; w120_buy_sol = 30
    assert s.top_share("w120", 5) == pytest.approx((5 + 1) / (30 - 4))
    assert s.top_share("w120", 1, exclude_agent=False) == pytest.approx(5 / 30)


def test_b1_trades_asof_and_garbage(frames):
    g, c, b = frames
    m, gts = g.loc[0, "mint"], int(g.loc[0, "g_ts"])
    n = 300
    tr = pd.DataFrame({"slot": np.arange(n), "tx_idx": 0, "pix": 0, "ix": 0, "ts": gts + np.arange(n) * 7,
                       "mint": m, "venue": 1, "is_buy": True, "wallet_h": np.arange(n), "usol": 10**8, "tok": 10**9,
                       "x0": 85 * 10**9, "y0": 2 * 10**14, "fees": 10**6, "virt_ksol": 17584505, "src": 0})
    ds = C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=SOL, trades=tr)
    t = gts + 500.0
    s = ds.asof(m, t)
    assert len(s.trades) and (s.trades["ts"] <= t - 20).all() and s.trades["ts"].max() > t - 30
    tr2 = tr.copy()
    late = tr2["ts"] > t - 20
    tr2.loc[late, "usol"] = 777
    tr2 = pd.concat([tr2, tr2[late].assign(slot=tr2["slot"][late] + 0.5)], ignore_index=True)
    ds2 = C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=SOL, trades=tr2)
    pd.testing.assert_frame_equal(s.trades.reset_index(drop=True), ds2.asof(m, t).trades.reset_index(drop=True),
                                  check_dtype=False)
    assert ds.asof(g.loc[1, "mint"], t).trades is None or len(ds.asof(g.loc[1, "mint"], t).trades) == 0

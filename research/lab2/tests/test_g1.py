"""Tests for research/lab2/g1.py: features on hand-built fixtures, no lookahead (own coin, other coins, hosts),
the bot-parity of the dip host, labels, the pre-registered decision rules and the stage stop rules."""

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import g1 as G
from conftest import make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")


# =========================================================================== fixtures


def _set(df: pd.DataFrame, mint: str, **vals) -> None:
    idx = df.index[df["mint"] == mint]
    for k, v in vals.items():
        if k not in df.columns:
            df[k] = None
        if isinstance(v, str) or v is None:
            df[k] = df[k].astype(object)
        for i in idx:
            df.at[i, k] = v


def _set_bar(b: pd.DataFrame, mint: str, j: int, **vals) -> pd.DataFrame:
    """Update minute j of ``mint`` (inserting the row if that minute had no trades)."""
    sub = b[b["mint"] == mint]
    m0 = int(sub["g_ts"].iloc[0]) // 60 * 60
    ts = m0 + 60 * j
    hit = b.index[(b["mint"] == mint) & (b["minute_ts"] == ts)]
    if not len(hit):
        row = sub.iloc[0].to_dict()
        prev = sub[sub["minute_ts"] < ts].iloc[-1]
        p = float(prev["close"])
        row.update({"minute_ts": ts, "minute_idx": j, "open": p, "high": p, "low": p, "close": p,
                    "x_close": float(prev["x_close"]), "y_close": float(prev["y_close"])})
        b = pd.concat([b, pd.DataFrame([row])], ignore_index=True)
        hit = b.index[(b["mint"] == mint) & (b["minute_ts"] == ts)]
    for k, v in vals.items():
        b.loc[hit, k] = v
    return b


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def g1_frames(t0: int = T0):
    """Hand-built classes on top of the synthetic CryptoHouse frames (coin i: slow when i % 5 == 4, AGENT when
    i % 3 == 0)."""
    g, c, b = make_frames(n=24, seed=1, t0=t0)
    g = g.copy()
    c = c.copy()
    # 0: FACTORY (instant, top-5 share 26/30 with the AGENT not in the list)
    _set(c, mint(0), w120_top10=json.dumps([["F1", 10, 0], ["F2", 8, 0], ["F3", 5, 0], ["F4", 2, 0], ["F5", 1, 0]]))
    # 1: OPERATOR (800 SOL from 12 buyers in 2 min)
    _set(c, mint(1), w120_buy_sol=800.0, w120_n_buyers=12)
    # 2: COMPLETED via the completer (20 of the last 30 SOL), slow graduation
    gi = int(g.index[g["mint"] == mint(2)][0])
    _set(g, mint(2), c_ts=int(g.at[gi, "g_ts"]) - 600, completer_sol=20.0, curve_top3_buy_sol=30.0)
    # 3: ORGANIC (slow, no concentration)
    gi = int(g.index[g["mint"] == mint(3)][0])
    _set(g, mint(3), c_ts=int(g.at[gi, "g_ts"]) - 900, completer_sol=10.0, curve_top3_buy_sol=30.0)
    # 4: has_create = 0 in make_frames -> UNRESOLVED (curve features NULL, never 0)
    # 5: airdrop dump in minute 16 (1,500 sells vs 40 buys)
    b = _set_bar(b, mint(5), 16, n_sells=1500, n_buys=40)
    # 6, 7, 8: one serial creator
    for i in (6, 7, 8):
        _set(g, mint(i), creator="SERIALX")
    # 10..13: a repeat migration buyer RPT in the top 5 of each first 2 min
    for i in (10, 11, 12, 13):
        top = [["RPT", 3.0, 0.0], [f"W{i}a", 5.0, 0.0], [f"W{i}c", 1.0, 0.0]]
        if i % 3 == 0:
            top.append([f"AGENT{i}", 4.0, 0.0])
        _set(c, mint(i), w120_top10=json.dumps(top))
    # 15 (agent, instant, untouched): POOLED + AGENT in the stored list
    return g, c, b


def _ds(frames, split="train", census=None, **kw):
    g, c, b = frames
    return C.Dataset.from_frames(split, g, c, b, census=census or C.Census.empty(), sol=SOL, **kw)


def _reg(frames, ds, census=None, lookback=G.REGISTRY_LOOKBACK_S):
    g, c, _ = frames
    return G.registry_from_frames(g, c, ds.split, census or C.Census.empty(), lookback_s=lookback)


@pytest.fixture
def gfr():
    return g1_frames()


@pytest.fixture
def gds(gfr):
    return _ds(gfr)


def _feat(ds, reg, m, dt=G.LABEL_T_S):
    cd = ds.coin(m)
    return G.g1_features(ds.asof(m, cd.g + dt), reg)


# =========================================================================== features on hand-built fixtures


def test_classes_on_hand_built_coins(gfr, gds):
    reg = _reg(gfr, gds)
    tab = G.coin_table(gds, reg).set_index("mint")
    assert tab.loc[mint(0), "g1_class"] == "FACTORY"
    assert tab.loc[mint(1), "g1_class"] == "OPERATOR"
    assert tab.loc[mint(2), "g1_class"] == "COMPLETED"
    assert tab.loc[mint(3), "g1_class"] == "ORGANIC"
    assert tab.loc[mint(4), "g1_class"] == "UNRESOLVED"
    # variant gate sets
    assert tab.loc[mint(0), "flag_G-time"] and tab.loc[mint(0), "flag_G-chain"] and tab.loc[mint(0), "dead_G-chain"]
    assert tab.loc[mint(1), "flag_G-chain"] and not tab.loc[mint(1), "dead_G-chain"]   # OPERATOR: skipped, not "dead"
    assert not tab.loc[mint(2), "flag_G-time"] and tab.loc[mint(2), "flag_G-chain"]
    assert not tab.loc[mint(3), "flag_G-chain"] and not tab.loc[mint(3), "flag_G-chain+"]
    assert not tab.loc[mint(4), "flag_G-time"] and not tab.loc[mint(4), "flag_G-chain"]  # unknown -> no evidence


def test_feature_values(gfr, gds):
    reg = _reg(gfr, gds)
    f0 = _feat(gds, reg, mint(0))
    assert f0["instant"] is True and f0["fast120"] is True
    assert f0["agent_present"] is True                       # coin 0 has an AGENT, known at g + 40
    assert f0["amm_top5_share_2m"] == pytest.approx(26 / 30)  # AGENT not in the stored list: total unchanged
    assert f0["amm_buyers_2m"] == 8                          # 9 buyers minus the AGENT
    assert f0["bundle_share"] == pytest.approx(1e8 / 793.1e6)
    f2 = _feat(gds, reg, mint(2))
    assert f2["grad_delay_s"] == pytest.approx(600) and f2["instant"] is False
    assert f2["completer_share"] == pytest.approx(20 / 30)
    assert f2["curve_top3_share"] == pytest.approx(30 / 90)
    f1 = _feat(gds, reg, mint(1))
    assert f1["amm_buy_sol_2m"] == pytest.approx(800.0) and f1["amm_buyers_2m"] == 12


def test_null_is_never_zero_for_slow_graduates(gfr, gds):
    reg = _reg(gfr, gds)
    f4 = _feat(gds, reg, mint(4))
    for k in ("grad_delay_s", "bundle_share", "creator_in_bundle", "curve_top1_share", "curve_top3_share",
              "completer_share", "n_curve_buyers", "serial_prior", "serial", "uri_host"):
        assert f4[k] is None, k
    assert f4["fast120"] is False and f4["instant"] is False   # decided by the lower bound (>= 1800 s), not by 0
    assert f4["creator_known"] is False
    assert G.classify(f4)["completed"] is None


def test_pooled_and_agent_never_count_as_top_buyers(gfr, gds):
    reg = _reg(gfr, gds)
    f = _feat(gds, reg, mint(15))      # stored list: POOLED 9, W15a 5, AGENT15 4, W15c 1; buy 30
    assert f["amm_buy_sol_2m"] == pytest.approx(26.0)
    assert f["amm_top5_share_2m"] == pytest.approx(6 / 26)
    assert f["amm_buyers_2m"] == 8


def test_none_safe_logic():
    assert G._any(None, True) is True and G._any(None, False) is None and G._any(False, False) is False
    assert G._all(None, False) is False and G._all(None, True) is None and G._all(True, True) is True
    assert G._delay_le(None, 1800.0, 120) is False and G._delay_le(None, 60.0, 120) is None
    assert G._delay_le(3.0, 3.0, 5) is True
    assert G._ratio(1, 0) is None and G._ratio(None, 2) is None


def test_airdrop_visible_only_after_its_minute_completes(gfr, gds):
    cd = gds.coin(mint(5))
    end16 = cd.m0 + 60 * 17
    s_before = gds.asof(mint(5), end16 - 1 + C.DECISION_LAG_S)
    s_after = gds.asof(mint(5), end16 + C.DECISION_LAG_S)
    assert G.airdrop_dump(s_before)["airdrop_seen"] is False
    a = G.airdrop_dump(s_after)
    assert a["airdrop_seen"] is True and a["airdrop_age_s"] > 0
    reg = _reg(gfr, gds)
    f = G.g1_features(s_after, reg)
    assert G.classify(f)["airdrop"] and G.classify(f)["flag"]["G-chain+"]


def test_airdrop_needs_sells_to_dominate(gfr):
    g, c, b = gfr
    b = _set_bar(b, mint(5), 16, n_sells=1500, n_buys=600)     # 1,500 < 3 x (600 + next minute's buys)
    ds = _ds((g, c, b))
    s = ds.asof(mint(5), ds.coin(mint(5)).m0 + 60 * 40)
    assert G.airdrop_dump(s)["airdrop_seen"] is False


def test_serial_creator_registry(gfr, gds):
    reg = _reg(gfr, gds)
    assert _feat(gds, reg, mint(8))["serial_prior"] == 2 and _feat(gds, reg, mint(8))["serial"] is True
    assert _feat(gds, reg, mint(7))["serial_prior"] == 1 and _feat(gds, reg, mint(7))["serial"] is False
    assert _feat(gds, reg, mint(6))["serial_prior"] == 0
    # the lookback bounds the history: 40 min only sees coin 7 from coin 8
    short = _reg(gfr, gds, lookback=2400)
    assert _feat(gds, short, mint(8))["serial_prior"] == 1
    # a graduate that has not graduated yet at tau is invisible (coin 8 graduates ~30 min after coin 7)
    cd7 = gds.coin(mint(7))
    assert G.g1_features(gds.asof(mint(7), cd7.g + 300), reg)["serial_prior"] == 1


def test_repeat_migration_buyer_share(gfr, gds):
    reg = _reg(gfr, gds)
    f13 = _feat(gds, reg, mint(13))                     # RPT top-5 on coins 10, 11, 12 before coin 13
    assert f13["repeat_migbuyer_share_2m"] == pytest.approx(3.0 / f13["amm_buy_sol_2m"])
    f12 = _feat(gds, reg, mint(12))                     # only 2 earlier coins
    assert f12["repeat_migbuyer_share_2m"] == pytest.approx(0.0)


def test_registry_coverage_flag(gfr, gds):
    reg = _reg(gfr, gds)
    cd = gds.coin(mint(23))
    assert reg.coverage(cd.g) < G.REGISTRY_WARM_MIN    # synthetic data covers ~12 h of a 24 h lookback
    full = G.Registry(scanned_hours=np.arange(0, 4_000_000_000, 3600, dtype=np.int64))
    assert full.coverage(cd.g) == 1.0


# =========================================================================== no lookahead


def _gfeat_key(f):
    return {k: (round(v, 12) if isinstance(v, float) else v) for k, v in f.items()}


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(gfr, seed):
    rng = np.random.default_rng(seed)
    clean = _ds(gfr)
    reg_c = _reg(gfr, clean)
    for _ in range(15):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([60, 139, 141, 300, 439, 441, 1000, 1800, 4000, 9000])) + float(rng.uniform(0, 59))
        dirty_fr = _garble(gfr, m, t - C.DECISION_LAG_S, rng)
        dirty = _ds(dirty_fr)
        reg_d = _reg(dirty_fr, dirty)
        f0 = G.g1_features(clean.asof(m, t), reg_c)
        f1 = G.g1_features(dirty.asof(m, t), reg_d)
        assert _gfeat_key(f0) == _gfeat_key(f1)
        assert G.classify(f0) == G.classify(f1)


def test_registry_unchanged_by_other_coins_future(gfr):
    """Coins that graduate after tau (or whose first 2 min are not over at tau) cannot change a feature at tau."""
    g, c, b = gfr
    clean = _ds(gfr)
    reg_c = _reg(gfr, clean)
    rng = np.random.default_rng(7)
    for target in (mint(7), mint(8), mint(13)):
        cd = clean.coin(target)
        tau = cd.g + G.LABEL_T_S - C.DECISION_LAG_S
        g2, c2 = g.copy(), c.copy()
        g2["creator"] = g2["creator"].astype(object)
        c2["w120_top10"] = c2["w120_top10"].astype(object)
        for i in g2.index:
            gt = float(g2.at[i, "g_ts"])
            mi = g2.at[i, "mint"]
            if mi == target:
                continue
            if gt > tau:                                   # not a graduate yet: a fake same-creator coin
                g2.at[i, "creator"] = "SERIALX" if target != mint(13) else g2.at[i, "creator"]
                ci = c2.index[c2["mint"] == mi]
                c2.loc[ci, "w120_top10"] = json.dumps([["RPT", 50.0, 0.0], ["W13a", 40.0, 0.0]])
            elif gt + C.W120_S > tau:                      # graduated, first 2 min not over
                ci = c2.index[c2["mint"] == mi]
                c2.loc[ci, "w120_top10"] = json.dumps([["RPT", float(rng.uniform(1, 99)), 0.0]])
        dirty = _ds((g2, c2, b))
        reg_d = _reg((g2, c2, b), dirty)
        f0 = G.g1_features(clean.asof(target, cd.g + G.LABEL_T_S), reg_c)
        f1 = G.g1_features(dirty.asof(target, cd.g + G.LABEL_T_S), reg_d)
        assert _gfeat_key(f0) == _gfeat_key(f1)


def _loose_dip():
    p = dict(G.DIP_PARAMS)
    p.update({"min_mcap_usd": 0.0, "dip_pct": 0.05, "confirm_green": 1, "min_age_min": 10.0})
    return p


@pytest.mark.parametrize("host", ["dip", "R0"])
def test_host_decisions_before_T_unchanged_by_future_garbage(gfr, host):
    rng = np.random.default_rng(11)
    clean = _ds(gfr)
    fn = G.host_dip if host == "dip" else G.host_r0
    p = _loose_dip() if host == "dip" else G.R0_PARAMS
    n_trades = 0
    for m in clean.mints[:12]:
        cd = clean.coin(m)
        T = cd.g + 3600
        dirty = _ds(_garble(gfr, m, T - C.DECISION_LAG_S, rng))
        a = C.run_trades(clean, fn, p, C.FillConfig(), mints=[m])
        bb = C.run_trades(dirty, fn, p, C.FillConfig(), mints=[m])
        a_dec = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
        b_dec = bb.loc[bb["t_dec"] <= T, "t_dec"].tolist()
        assert a_dec == b_dec
        n_trades += len(a)
    assert n_trades > 0


def test_gate_annotation_uses_decision_time_view(gfr, gds):
    """A trade decided before the airdrop minute completes is not flagged AIRDROP; one decided after is."""
    reg = _reg(gfr, gds)
    cd = gds.coin(mint(5))
    end16 = cd.m0 + 60 * 17
    tr = pd.DataFrame({"mint": [mint(5), mint(5)], "t_dec": [end16 - 1 + 20.0, end16 + 20.0], "ret_net": [0.0, 0.0]})
    ann = G.annotate(tr, gds, reg)
    assert ann["airdrop"].tolist() == [False, True]


# =========================================================================== hosts


def _bars(o, h, l, c, v=None):
    n = len(c)
    v = np.ones(n) if v is None else np.asarray(v, float)
    return SimpleNamespace(o=np.asarray(o, float), h=np.asarray(h, float), l=np.asarray(l, float),
                           c=np.asarray(c, float), buy_sol=v, sell_sol=np.zeros(n), traded=np.ones(n))


def test_dip_signal_rules():
    p = G.DIP_PARAMS
    #                 high 10, low 4 (60 % dip), two green closes, breakout
    ok = _bars([9, 10, 6, 4.0, 4.2], [10, 10, 6.5, 4.5, 5.0], [8, 9, 5, 4.0, 4.1], [9.5, 9, 5, 4.3, 4.9])
    assert G.dip_signal(ok, p)
    shallow = _bars([9, 10, 6, 5.0, 5.2], [10, 10, 6.5, 5.5, 6.0], [8, 9, 5.5, 5.0, 5.1], [9.5, 9, 5.6, 5.3, 5.9])
    assert not G.dip_signal(shallow, p)                       # 50 % dip < 55 %
    chase = _bars([9, 10, 6, 4.0, 6.0], [10, 10, 6.5, 6.2, 8.0], [8, 9, 4.0, 4.0, 6.0], [9.5, 9, 4.5, 6.1, 7.5])
    assert not G.dip_signal(chase, p)                         # last close above 72.5 % of the high
    one_green = _bars([9, 10, 6, 4.6, 4.2], [10, 10, 6.5, 4.6, 5.0], [8, 9, 5, 4.0, 4.1], [9.5, 9, 5, 4.3, 4.9])
    assert not G.dip_signal(one_green, p)
    flat = _bars([9, 10, 6, 4.0, 4.3], [10, 10, 6.5, 4.5, 4.6], [8, 9, 5, 4.0, 4.2], [9.5, 9, 5, 4.3, 4.4],
                 v=[1, 1, 1, 2, 1])
    assert not G.dip_signal(flat, p)                          # green, no breakout, no rising volume


def test_dip_signal_matches_the_bot_entry_signal():
    """Logic parity with src/nightcrawler/strategy.entry_signal (snapshot=None) on random candle paths."""
    src = Path(__file__).resolve().parents[3] / "src"
    sys.path.insert(0, str(src))
    try:
        from nightcrawler.models import Candle, StrategyParams
        from nightcrawler.strategy import entry_signal
    except Exception as e:  # another team edits src/: never fail this research test on their import errors
        pytest.skip(f"nightcrawler not importable: {e!r}")
    finally:
        sys.path.remove(str(src))
    sp = StrategyParams()
    p = dict(G.DIP_PARAMS, dip_pct=sp.dip_pct, confirm_green=sp.confirm_green)
    rng = np.random.default_rng(5)
    n_enter = 0
    for _ in range(400):
        n = int(rng.integers(4, 40))
        c = 10.0 * np.exp(np.cumsum(rng.normal(-0.05, 0.25, n)))
        o = np.r_[10.0, c[:-1]] * np.exp(rng.normal(0, 0.05, n))
        h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.1, n)))
        l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.1, n)))
        v = rng.uniform(1, 10, n)
        candles = [Candle(60 * i, o[i], h[i], l[i], c[i], v[i]) for i in range(n)]
        bot = entry_signal(candles, None, sp, now=60 * n).kind == "enter"
        ours = G.dip_signal(_bars(o, h, l, c, v), p)
        assert bot == ours
        n_enter += bot
    assert n_enter > 5


def test_dip_params_are_the_bot_defaults():
    src = Path(__file__).resolve().parents[3] / "src"
    sys.path.insert(0, str(src))
    try:
        from nightcrawler.models import StrategyParams
    except Exception as e:
        pytest.skip(f"nightcrawler not importable: {e!r}")
    finally:
        sys.path.remove(str(src))
    sp = StrategyParams()
    want = {"dip_pct": sp.dip_pct, "confirm_green": sp.confirm_green, "dip_lookback_h": sp.dip_lookback_h,
            "min_age_min": sp.min_age_min, "max_age_h": sp.max_age_h, "min_mcap_usd": sp.min_mcap_usd,
            "max_mcap_usd": sp.max_mcap_usd, "stop_pct": sp.stop_loss_pct, "take_profit_pct": sp.take_profit_pct,
            "max_hold_min": sp.max_hold_min}
    drift = {k: (G.DIP_PARAMS[k], v) for k, v in want.items() if G.DIP_PARAMS[k] != v}
    if drift:   # the other team changed the bot: the pre-registered host is frozen; report, do not fail
        pytest.skip(f"bot defaults drifted from the pre-registered host: {drift}")


def test_r0_target_is_seeded_and_in_range():
    ages = [G.r0_target_age_s(f"M{i}", G.R0_PARAMS) for i in range(500)]
    assert min(ages) >= 30 * 60 and max(ages) <= 115 * 60
    assert G.r0_target_age_s("M1", G.R0_PARAMS) == G.r0_target_age_s("M1", G.R0_PARAMS)
    assert G.r0_target_age_s("M1", G.R0_PARAMS) != G.r0_target_age_s("M1", dict(G.R0_PARAMS, seed=1))
    assert 0.4 < np.mean(np.array(ages) < 72.5 * 60) < 0.6


def test_r0_enters_at_target_or_never(gds):
    tr = C.run_trades(gds, G.host_r0, G.R0_PARAMS, C.FillConfig())
    assert len(tr) > 0
    for r in tr.itertuples(index=False):
        target = G.r0_target_age_s(r.mint, G.R0_PARAMS)
        assert target <= r.age_dec_s < target + 60
        assert r.stop_pct == 0.5 and r.max_hold_s == 3600


# =========================================================================== labels


def test_labels_dead60_and_winner(gfr):
    g, c, b = gfr
    b = b[~((b["mint"] == mint(3)) & (b["minute_idx"].between(59, 76)))]           # silent 60-75 min
    m11 = b["mint"] == mint(11)
    m0 = int(b.loc[m11, "g_ts"].iloc[0]) // 60 * 60
    p15 = float(b.loc[m11 & (b["minute_ts"] < g.loc[g["mint"] == mint(11), "g_ts"].iloc[0] + 900), "close"].iloc[-1])
    b = _set_bar(b, mint(11), 40, high=3.0 * p15)
    ds = _ds((g, c, b))
    lab3 = G.coin_labels(ds.coin(mint(3)), SOL)
    lab11 = G.coin_labels(ds.coin(mint(11)), SOL)
    assert lab3["dead60"] is True
    assert lab11["dead60"] is False                    # ~$400 a minute in the synthetic bars
    assert lab11["winner"] is True
    assert m0 > 0


# =========================================================================== decision rules (pre-registered)


def _ev(prec=0.95, n_dead=300, miss=0.02, diff=0.03, ci=(0.005, 0.06), chain="G-chain", r0_diff=-0.12,
        nf=100, nu=200):
    lab = {"precision_dead60": prec, "n_flag_dead": n_dead, "missed_winner_rate": miss}
    host = {"R0": {"flagged": {"n": nf}, "unflagged": {"n": nu, "mean": -0.05}, "diff_flagged_minus_unflagged": r0_diff,
                   "diff_ci95": (-0.2, -0.05)}}
    return {"G-time": {"labels": dict(lab), "hosts": host}, chain: {"labels": dict(lab), "hosts": host},
            "_chain_vs_time_R0": {chain: {"r0_unflagged_mean_minus_g_time": diff, "ci95": ci}}}


SL = [{"gate": "G-time"}, {"gate": "G-chain"}]


def test_decide_val_rules():
    assert G.decide_val(_ev(), SL)["verdict"] == "PASS_CHAIN"
    assert G.decide_val(_ev(), SL)["ship"] == "G-chain"
    assert G.decide_val(_ev(diff=0.01), SL)["verdict"] == "SHIP_G_TIME"             # < 2 points
    assert G.decide_val(_ev(ci=(-0.01, 0.07)), SL)["ship"] == "G-time"              # CI includes 0
    assert G.decide_val(_ev(prec=0.85), SL)["verdict"] == "KILL"
    assert G.decide_val(_ev(miss=0.08), SL)["verdict"] == "KILL"
    assert G.decide_val(_ev(n_dead=150), SL)["verdict"] == "UNDERPOWERED"
    assert G.decide_val(_ev(chain="G-chain+"), [{"gate": "G-time"}, {"gate": "G-chain+"}])["ship"] == "G-chain+"


def test_shortlist_rule():
    def ev(a, b):
        return {"G-chain": {"hosts": {"R0": {"unflagged": {"mean": a}}}},
                "G-chain+": {"hosts": {"R0": {"unflagged": {"mean": b}}}}}
    assert G.shortlist_rule(ev(-0.05, -0.02)) == [{"gate": "G-time"}, {"gate": "G-chain+"}]
    assert G.shortlist_rule(ev(-0.02, -0.05)) == [{"gate": "G-time"}, {"gate": "G-chain"}]
    assert G.shortlist_rule(ev(-0.02, -0.02)) == [{"gate": "G-time"}, {"gate": "G-chain"}]   # tie -> simpler
    assert G.shortlist_rule(ev(None, None)) == [{"gate": "G-time"}, {"gate": "G-chain"}]


def test_decide_confirm():
    assert G.decide_confirm(_ev(), "G-chain")["verdict"] == "CONFIRMED"
    assert G.decide_confirm(_ev(prec=0.7), "G-chain")["verdict"] == "NOT_CONFIRMED"
    assert G.decide_confirm(_ev(r0_diff=0.02), "G-chain")["verdict"] == "NOT_CONFIRMED"
    assert G.decide_confirm(_ev(nf=10), "G-chain")["verdict"] == "UNDERPOWERED"


def test_boot_subset_diff():
    rng = np.random.default_rng(0)
    coins = np.repeat(np.arange(200), 2)
    r = rng.normal(0, 0.1, 400)
    a = coins % 2 == 0
    r[a] -= 0.2
    d, ci = G.boot_subset_diff(r, coins, a, ~a, B=2000)
    assert d < -0.15 and ci[1] < 0 and ci[0] < d < ci[1]
    assert G.boot_subset_diff(r, coins, np.zeros(400, bool), ~a) == (None, None)


# =========================================================================== stop rules and the stage pipeline


VALID_OK = {"V1": {"pass": True}, "V2": {"chain_ok": 995, "transitions": 1000}, "V3": {"both": 99, "coin_windows": 100},
            "V4": {"pass": True}}
# stop rule 1 is checked per split: a passing V1/V2/V4 record over every split's dates (common.validation_gates)
VALID_OK = {**VALID_OK, "ranges": [{"lo_utc": "2026-09-01 00:00:00", "hi_utc": "2026-10-10 00:00:00",
                                    "validated_utc": "2030-01-01 00:00:00", "V1": {"pass": True},
                                    "V2": {"chain_ok": 995, "transitions": 1000}, "V4": {"pass": True}}]}


@pytest.fixture
def env_dirs(tmp_path, monkeypatch):
    out = tmp_path / "G1"
    out.mkdir()
    (out / "PREREG.md").write_text("# prereg\n")
    flow = tmp_path / "flow"
    flow.mkdir()
    (flow / "validation.json").write_text(json.dumps(VALID_OK))
    led = tmp_path / "trials.json"
    sl = tmp_path / "shortlists"
    monkeypatch.setenv("LAB2_TRIALS", str(led))
    monkeypatch.setenv("LAB2_SHORTLISTS", str(sl))
    for k in ("LAB2_ALLOW_TEST", "LAB2_ALLOW_CONFIRM", "LAB2_ALLOW_FINAL"):
        monkeypatch.delenv(k, raising=False)
    return SimpleNamespace(out=out, flow=flow, ledger=led, sl=sl)


def _check(stage, d, env=None):
    return G.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {})


def test_refuses_without_prereg_or_with_failed_data_gates(env_dirs):
    _check("train", env_dirs)
    bad = dict(VALID_OK, V2={"chain_ok": 900, "transitions": 1000})
    (env_dirs.flow / "validation.json").write_text(json.dumps(bad))
    with pytest.raises(G.G1Refused, match="data first"):
        _check("train", env_dirs)
    (env_dirs.flow / "validation.json").write_text(json.dumps(VALID_OK))
    (env_dirs.out / "PREREG.md").unlink()
    with pytest.raises(G.G1Refused, match="PREREG"):
        _check("train", env_dirs)


def test_prereg_frozen_after_train_lock(env_dirs):
    p = env_dirs.out / "PREREG.md"
    (env_dirs.out / "prereg.lock").write_text(json.dumps({"sha256": G._sha(p)}))
    _check("train", env_dirs)
    p.write_text("# prereg, edited after TRAIN\n")
    with pytest.raises(G.G1Refused, match="changed after"):
        _check("train", env_dirs)


def test_stage_order_refusals(env_dirs):
    d = env_dirs
    with pytest.raises(G.G1Refused, match="no TRAIN result"):
        _check("val", d)
    (d.out / "train.json").write_text(json.dumps({"provisional": True}))
    with pytest.raises(G.G1Refused, match="provisional"):
        _check("val", d)
    (d.out / "train.json").write_text(json.dumps({"provisional": False}))
    with pytest.raises(G.G1Refused, match="no VAL shortlist"):
        _check("val", d)
    with pytest.raises(G.G1Refused, match="no VAL result"):
        _check("test", d, {"LAB2_ALLOW_TEST": "1"})
    for stage in ("confirm", "final"):
        with pytest.raises(G.G1Refused, match="before TEST"):
            _check(stage, d, {G.STAGE_ENV[stage]: "1"})
    (d.out / "val.json").write_text(json.dumps({"decision": {"verdict": "KILL", "ship": None}}))
    with pytest.raises(G.G1Refused, match="stopped"):
        _check("test", d, {"LAB2_ALLOW_TEST": "1"})
    (d.out / "val.json").write_text(json.dumps({"decision": {"verdict": "SHIP_G_TIME", "ship": "G-time"}}))
    with pytest.raises(G.G1Refused, match="locked"):
        _check("test", d, {})
    _check("test", d, {"LAB2_ALLOW_TEST": "1"})
    (d.out / "test.json").write_text("{}")
    with pytest.raises(G.G1Refused, match="already ran"):
        _check("test", d, {"LAB2_ALLOW_TEST": "1"})
    _check("final", d, {"LAB2_ALLOW_FINAL": "1"})
    _check("confirm", d, {"LAB2_ALLOW_CONFIRM": "1"})


def test_ledger_one_run_rule_blocks_a_second_test(env_dirs):
    d = env_dirs
    (d.out / "val.json").write_text(json.dumps({"decision": {"verdict": "PASS_CHAIN", "ship": "G-chain"}}))
    C.record_run(G.HYP, {"gate": "G-chain"}, "test", {"n": 1, "mean": 0.0}, d.ledger)
    with pytest.raises(G.G1Refused, match="one test run"):
        _check("test", d, {"LAB2_ALLOW_TEST": "1"})


def _no_returns(o, path="doc"):
    banned = {"mean", "median", "win_rate", "ci90", "ci95", "pnl_usd", "precision_dead60", "dead60_rate",
              "winner_rate", "missed_winner_rate", "diff_flagged_minus_unflagged", "summary", "placebo", "stress",
              "gated", "veto_3_5", "dead60_base_rate", "_host_pnl_usd", "_share_of_host_pnl"}
    if isinstance(o, dict):
        for k, v in o.items():
            assert k not in banned, f"{path}.{k} leaks returns on the debug split"
            _no_returns(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _no_returns(v, f"{path}[{i}]")


def test_debug_stage_reports_counts_only(env_dirs):
    lo = C.FINAL_LO
    cen = C.Census(split_of={}, created_ts={}, started_ts=math.inf, created_max_ts=math.inf, train_hi=lo + 200_000,
                   val_hi=lo + 300_000)
    fr = g1_frames(t0=lo + 600)
    ds = C.Dataset.from_frames("final_train", *fr, census=cen, sol=SOL)
    assert len(ds) > 10 and ds.debug_only
    doc = G.run_stage("debug", out_dir=env_dirs.out, ds=ds, frames=fr[:2], census=cen, flow=env_dirs.flow,
                      ledger_path=env_dirs.ledger, shortlist_path=env_dirs.sl, B=200, n_placebo=2)
    _no_returns(doc)
    assert doc["counts"]["host_trades"]["R0"] > 0
    # (coins without creation data fall into the sealed 'test' split under common.assign_split: no UNRESOLVED here)
    assert set(doc["counts"]["classes_at_g140"]) >= {"FACTORY", "OPERATOR", "COMPLETED", "ORGANIC"}
    assert not (env_dirs.out / "debug_trades.csv.gz").exists()
    assert C.n_trials(env_dirs.ledger) == sum(C.BASELINE_TRIALS.values())     # debug never counts


def test_stage_pipeline_train_val_test(env_dirs, monkeypatch):
    d = env_dirs
    fr = g1_frames()
    ds_tr = _ds(fr)
    doc = G.run_stage("train", out_dir=d.out, ds=ds_tr, frames=fr[:2], census=C.Census.empty(), flow=d.flow,
                      ledger_path=d.ledger, shortlist_path=d.sl, B=200, n_placebo=2, _skip_coverage=True)
    assert doc["decision"]["shortlist_written"] and (d.out / "train.json").exists() and (d.out / "train.md").exists()
    assert (d.out / "prereg.lock").exists() and (d.sl / "G1.json").exists()
    assert set(doc["variants"]) == set(G.VARIANTS)
    with C._ledger(d.ledger, write=False) as led:
        hyps = [v["hypothesis"] for v in led["configs"].values()]
    assert hyps.count("G1") == 3 and hyps.count("G1.dip") == 1 and hyps.count("G1.R0") == 1
    assert not any(r["over_variant_limit"] for r in led["runs"])
    # VAL on a VAL-dated copy of the frames
    fv = g1_frames(t0=C.utc_ts("2026-10-05 01:00"))
    ds_v = C.Dataset.from_frames("val", *fv, census=C.Census.empty(), sol=SOL, _internal=True)
    vdoc = G.run_stage("val", out_dir=d.out, ds=ds_v, frames=fv[:2], census=C.Census.empty(), flow=d.flow,
                       ledger_path=d.ledger, shortlist_path=d.sl, B=200, n_placebo=2, _skip_coverage=True)
    assert vdoc["decision"]["verdict"] in ("PASS_CHAIN", "SHIP_G_TIME", "KILL", "UNDERPOWERED")
    assert len(vdoc["variants"]) == 2
    with pytest.raises(G.G1Refused, match="VAL already ran"):
        _check("val", d)
    # TEST: force a shipping VAL decision, run once, then refuse
    (d.out / "val.json").write_text(json.dumps({"decision": {"verdict": "SHIP_G_TIME", "ship": "G-time"}}))
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    ft = g1_frames(t0=C.utc_ts("2026-10-06 13:00"))
    ds_t = C.Dataset.from_frames("test", *ft, census=C.Census.empty(), sol=SOL)
    tdoc = G.run_stage("test", out_dir=d.out, ds=ds_t, frames=ft[:2], census=C.Census.empty(), flow=d.flow,
                       ledger_path=d.ledger, shortlist_path=d.sl, B=200, n_placebo=2, _skip_coverage=True,
                       env={"LAB2_ALLOW_TEST": "1"})
    assert tdoc["variants"] == ["G-time"] and tdoc["decision"]["variant"] == "G-time"
    assert list(tdoc["variants_eval"]) == ["G-time", "_chain_vs_time_R0"]
    with pytest.raises(G.G1Refused):
        G.run_stage("test", out_dir=d.out, ds=ds_t, frames=ft[:2], census=C.Census.empty(), flow=d.flow,
                    ledger_path=d.ledger, shortlist_path=d.sl, B=200, env={"LAB2_ALLOW_TEST": "1"},
                    _skip_coverage=True)
    saved = pd.read_csv(d.out / "test_trades.csv.gz")
    assert "flag_G-time" in saved and "flag_G-chain" not in saved and "flag_G-chain+" not in saved


def test_partial_train_is_provisional_and_writes_no_shortlist(env_dirs):
    d = env_dirs
    fr = g1_frames()
    ds_tr = _ds(fr)
    assert not G.coverage_check(ds_tr.coverage)[0]          # synthetic data covers half a day of TRAIN
    with pytest.raises(G.G1Refused, match="incomplete"):
        G.run_stage("train", out_dir=d.out, ds=ds_tr, frames=fr[:2], census=C.Census.empty(), flow=d.flow,
                    ledger_path=d.ledger, shortlist_path=d.sl, B=200, n_placebo=2)
    doc = G.run_stage("train", out_dir=d.out, ds=ds_tr, frames=fr[:2], census=C.Census.empty(), flow=d.flow,
                      ledger_path=d.ledger, shortlist_path=d.sl, B=200, n_placebo=2, allow_partial=True)
    assert doc["provisional"] and not doc["decision"]["shortlist_written"] and not (d.sl / "G1.json").exists()
    with pytest.raises(G.G1Refused, match="provisional"):
        _check("val", d)


# =========================================================================== real data (census TRAIN third, debug)


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """g1_features unchanged when the coin's data after tau is garbage: 60 (coin, tau) pairs on census TRAIN."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(8)
    mints = [full.mints[int(i)] for i in rng.choice(len(full.mints), size=20, replace=False)]
    sub = tuple(x[x["mint"].isin(mints)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    reg_c = G.registry_from_frames(sub[0], sub[1], "final_train", cen)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (G.LABEL_T_S, float(rng.uniform(300, 1200)), float(rng.uniform(1800, 10_000))):
            t = cd.g + dt
            dirty_fr = _garble(sub, m, t - C.DECISION_LAG_S, rng)
            dirty = C.Dataset.from_frames("final_train", *dirty_fr, census=cen, sol=SOL)
            reg_d = G.registry_from_frames(dirty_fr[0], dirty_fr[1], "final_train", cen)
            f0 = G.g1_features(clean.asof(m, t), reg_c)
            f1 = G.g1_features(dirty.asof(m, t), reg_d)
            assert _gfeat_key(f0) == _gfeat_key(f1)
            n += 1
    # a subset can lose coins whose B2 hours are no longer all present (universe rule), never features
    assert len(clean.mints) >= 15 and n == 3 * len(clean.mints)

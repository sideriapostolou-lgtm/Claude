"""Tests for research/lab2/q2.py (queue item q2, CC1): the key function, the structural registry (cluster, pos, OG,
copies, the pool bound), arm B's causal event timing, the event-time placebo, no lookahead (synthetic and real
census-third structure: garbage bars after T and renamed / new graduates after T change no pos, no OG, no event and
no decision at tau <= T), the arm A veto with its random-veto control, the arm C dose reading, the pre-registered
decision rules and every stage refusal, end to end for a spillover market and a copy-order market."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import g1
import q2 as Q
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00") + 5
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
ENV_ALL = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
W60, W150 = 3600.0, 9000.0


# =========================================================================== synthetic markets


def letters(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


def market_frames(coins: list[dict], seed: int = 0):
    """Graduates / b2_coins / b2_bars for hand-specified coins: {g, creator (None = creation not scanned), name,
    symbol, phases [(start minute, per-minute log drift)] or drift, quiet (start, end) minutes of ~zero volume,
    mayhem}. Prices move along X * y = k with a bar in every minute."""
    g0, c0, _ = make_frames(n=1, seed=seed, slow_every=0, agent_every=0)
    tg, tc = g0.iloc[0].to_dict(), c0.iloc[0].to_dict()
    grads, cs, bars = [], [], []
    k = X0 * Y0
    for i, s in enumerate(coins):
        mint, pool = f"Q{i:04d}{seed}pump", f"QP{i:04d}{seed}"
        g = int(s["g"])
        cr = s.get("creator", f"CR{i}")
        r = dict(tg)
        r.update(mint=mint, pool=pool, g_ts=g, g_slot=10_000 + i, pool_ts=g + 2, pool_slot=10_001 + i)
        if cr is None:
            r.update(has_create=0, c_ts=0, c_slot=0, creator="", create_user="", symbol="", name="", vsol0=0.0,
                     grad_delay_s=float(g))
        else:
            r.update(has_create=1, c_ts=g - 3, c_slot=9_000 + i, creator=cr, create_user=cr,
                     symbol=s.get("symbol", f"S{i}"), name=s.get("name", f"Cn{letters(i)}"), grad_delay_s=3.0)
        if s.get("mayhem"):
            r.update(is_mayhem=1)
        grads.append(r)
        cc = dict(tc)
        cc.update(mint=mint, pool=pool, g_ts=g)
        cs.append(cc)
        phases = sorted(s.get("phases") or [(0, float(s.get("drift", 0.0)))])
        q_lo, q_hi = s.get("quiet", (None, None))
        m0 = g // 60 * 60
        lp = math.log(X0 / Y0)
        for j in range(N_MIN):
            lp0 = lp
            lp += [d for st, d in phases if st <= j][-1]
            p0, p1 = math.exp(lp0), math.exp(lp)
            X1, y1 = math.sqrt(k * p1), math.sqrt(k / p1)
            quiet = q_lo is not None and q_lo <= j < q_hi
            vb, vs = (0.001, 0.001) if quiet else (2.0, 1.0)
            bars.append({"minute_ts": m0 + 60 * j, "n_buys": 5, "n_sells": 3, "n_dust": 0, "buy_sol": vb,
                         "sell_sol": vs, "buy_tok": 1e6, "sell_tok": 1e6, "n_buyers": 4, "n_sellers": 3,
                         "top5_buy_sol": 2.0, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                         "x_close": X1 - V0, "y_close": y1, "mint": mint, "pool": pool, "g_ts": g, "minute_idx": j,
                         "agent_buy_sol": 0.0, "price_repaired": 0})
    return pd.DataFrame(grads), pd.DataFrame(cs), pd.DataFrame(bars)


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def mint_of(i: int, seed: int = 0) -> str:
    return f"Q{i:04d}{seed}pump"


def reg_of(frames, ds=None, hi=math.inf) -> Q.Registry:
    rows = Q.structure_rows_from_frames(frames[0], C.Census.empty(), hi)
    return Q.build_registry(ds, rows)


SPILL_OG = [(0, -0.002), (39, 0.02), (59, -0.004)]     # flat-ish, a 20-minute run right after the copy's event


def spill_market(t0: int, n_pairs: int, n_fill: int, prefix: str = "A", mode: str = "spill",
                 stagger: int = 600) -> list[dict]:
    """``n_pairs`` originals, each with ONE copy (same symbol, other name and creator) graduating 31 min later; the
    OG is quiet (not alive) until the copy graduates. ``spill``: the OG runs right after the copy's event;
    ``flat``: it keeps falling. Copies are flat; fillers (solo) fall."""
    out = []
    for i in range(n_pairs):
        g = t0 + i * stagger
        og = SPILL_OG if mode == "spill" else [(0, -0.004)]
        out.append({"g": g, "creator": f"{prefix}A{i}", "symbol": f"OG{prefix}{i}", "name": f"Og{prefix}{letters(i)}",
                    "phases": og, "quiet": (3, 31)})
        out.append({"g": g + 31 * 60 + 7, "creator": f"{prefix}B{i}", "symbol": f"$og{prefix.lower()}{i}",
                    "name": f"Cp{prefix}{letters(i)}", "drift": 0.0})
    for i in range(n_fill):
        out.append({"g": t0 + 137 + i * stagger, "creator": f"{prefix}F{i}", "symbol": f"F{prefix}{i}",
                    "name": f"Fill{prefix}{letters(i)}", "drift": -0.005})
    return out


def family_market(t0: int, n_fam: int, prefix: str = "A", stagger: int = 1800) -> list[dict]:
    """``n_fam`` families of 4 graduates with one symbol, 5 minutes apart (pos 0, 1, 2, 3): the original rises, the
    copies fall. Copies graduate before the OG is 30 min old, so arm B never trades here."""
    out = []
    for f in range(n_fam):
        for kk in range(4):
            out.append({"g": t0 + f * stagger + kk * 300, "creator": f"{prefix}C{f}_{kk}", "symbol": f"FM{prefix}{f}",
                        "name": f"Fam{prefix}{letters(f * 4 + kk)}", "drift": 0.004 if kk == 0 else -0.01})
    return out


# =========================================================================== grid and constants


def test_grid_is_preregistered_and_small():
    assert len(Q.GRID_B) == 4 and Q.P_GRID == (1, 3)
    keys = [Q.config_key(p) for p in Q.GRID_B]
    assert keys == ["B|W60|hold60", "B|W60|deadline", "B|W150|hold60", "B|W150|deadline"]
    assert len({C.params_hash(p) for p in Q.GRID_B}) == 4
    for p in Q.GRID_B:
        for k, v in Q.KEY_DEF.items():
            assert p[k] == v
        assert p["window_s"] == p["window_min"] * 60.0 and p["exit_by_age_s"] == 178 * 60.0
        assert (p["hold_s"] == 3600.0) == (p["exit"] == "hold60")
    # 4 arm-B configs + 2 vetoes + 1 dose run + the R0 host run = 8 trials <= 12 (PREREG 7)
    assert len(Q.GRID_B) + len(Q.P_GRID) + 1 + 1 == 8
    assert Q.R0_PIN == C.params_hash(g1.R0_PARAMS) and not Q.host_problems()
    assert all(Q.HOST_PARAMS[k] == v for k, v in g1.R0_PARAMS.items())
    assert Q.FILL.exit_delay_bars == 1 and Q.FILL.entry_fill == "worst" and Q.FILL.exit_fill == "worst"
    assert Q.EVENT_DELAY_S == 420.0 and Q.OG_MIN_AGE_S == 1800.0 and Q.LOOKBACK_S == 7 * 86400
    with pytest.raises(ValueError):
        Q.make_params(90, "hold60")
    with pytest.raises(ValueError):
        Q.make_params(60, "trail")
    with pytest.raises(ValueError):
        Q.veto_params(2)
    e60, edl = Q.exits_of(Q.make_params(60, "hold60")), Q.exits_of(Q.make_params(150, "deadline"))
    assert e60 == C.ExitSpec(stop_pct=0.5, max_hold_s=3600.0, exit_by_age_s=10680.0)
    assert edl == C.ExitSpec(stop_pct=0.5, max_hold_s=None, exit_by_age_s=10680.0)


# =========================================================================== keys


@pytest.mark.parametrize("s,want", [
    ("$PEPE", "pepe"), ("pepe", "pepe"), ("ＰＥＰＥ", "pepe"), ("Pepe Coin", "pepecoin"), ("Pokémon", "pokemon"),
    ("🐸", None), ("", None), ("   ", None), (None, None), (float("nan"), None), ("龙虾", "龙虾"), ("GROK-4", "grok4"),
    ("Ünïcödé!", "unicode"),
])
def test_key_of(s, want):
    assert Q.key_of(s) == want


def test_pos_bin():
    assert [Q.pos_bin(x) for x in (0, 1, 2, 3, 9, None, float("nan"))] == ["0", "1", "2", "3+", "3+", "unknown",
                                                                          "unknown"]


# =========================================================================== registry


def _named():
    D = 86400
    coins = [{"g": T0, "creator": "A", "symbol": "PEPE", "name": "Pepe One"},                 # 0 the original
             {"g": T0 + 600, "creator": "B", "symbol": "$pepe", "name": "Other"},              # 1 symbol copy
             {"g": T0 + 1200, "creator": "A", "symbol": "XYZ", "name": "Pepe One"},            # 2 name copy, same creator
             {"g": T0 + 1800, "creator": "C", "symbol": "PEPE", "name": "pepe one"},           # 3 both
             {"g": T0 + 900, "creator": "M", "symbol": "PEPE", "name": "Mayhem P", "mayhem": True},  # 4 structure only
             {"g": T0 + 1800 + 7 * D, "creator": "D", "symbol": "PEPE", "name": "Late"},       # 5 exactly 7 d after 3
             {"g": T0 + 2000, "creator": None},                                                # 6 creation not scanned
             {"g": T0 + 1800 + 8 * D, "creator": "E", "symbol": "PEPE", "name": "Later"}]      # 7 8 d after 3
    fr = market_frames(coins)
    return fr, ds_of(fr)


def test_cluster_pos_og_and_copies():
    fr, ds = _named()
    reg = reg_of(fr, ds)
    m = [mint_of(i) for i in range(8)]
    assert m[4] in reg.grads and m[4] not in ds.mints                     # Mayhem: structure only
    assert reg.pos(m[0]) == 0 and reg.og(m[0]) is None
    c1 = reg.cluster(m[1])
    assert c1["pos"] == 1 and c1["og"] == m[0] and c1["link"] == "symbol"
    c2 = reg.cluster(m[2])                                                # same creator still counts (a copy)
    assert c2["pos"] == 1 and c2["og"] == m[0] and c2["link"] == "name"
    c3 = reg.cluster(m[3])
    assert c3["pos"] == 4 and c3["og"] == m[0] and c3["link"] == "both"
    assert set(c3["members"]) == {m[0], m[1], m[2], m[4]}
    # 7-day window: [g - 7 d, g) -> coin 3 (exactly 7 d earlier) is in; nothing else is
    c5 = reg.cluster(m[5])
    assert c5["pos"] == 1 and c5["og"] == m[3]
    assert reg.pos(m[7]) == 1 and reg.og(m[7]) == m[5]
    assert reg.pos(m[6]) is None and reg.cluster(m[6]) is None and not reg.keyed(m[6])   # NULL is never 0
    assert [x for _, x in reg.copies(m[0])] == [m[1], m[4], m[2], m[3]]
    assert [x for _, x in reg.copies(m[3])] == [m[5]] and reg.copies(m[1]) == []
    assert list(reg.copy_times(m[0], 900.0)) == [T0 + 600.0, T0 + 900.0]
    later = reg.later_same_key(m[0])
    assert list(later) == sorted([T0 + 600.0, T0 + 900.0, T0 + 1200.0, T0 + 1800.0, T0 + 1800.0 + 7 * 86400,
                                  T0 + 1800.0 + 8 * 86400])


def test_pool_bound_and_lookback_coverage():
    fr, ds = _named()
    hi = float(C._normalize_graduates(fr[0], C.Census.empty()).loc[3, "created_for_split"]) + 1
    reg = reg_of(fr, ds, hi=hi)                                           # coins created after coin 3 are not in it
    assert mint_of(5) not in reg.grads and mint_of(7) not in reg.grads and mint_of(3) in reg.grads
    assert reg.copies(mint_of(3)) == []
    cov = reg.lookback_cov(T0 + 1800)
    assert 0 < cov < 0.05                                                 # 1 scanned hour (T0's) of 168
    full = Q.Registry.from_rows([], scanned_hours=range(0, 2_000_000_000, 3600))
    assert full.lookback_cov(T0) == 1.0 and Q.Registry.from_rows([]).lookback_cov(T0) is None


# =========================================================================== arm B strategy


def _pair(lag_s: float, og_quiet=None, og_drift=0.0):
    coins = [{"g": T0, "creator": "A", "symbol": "OGX", "name": "Og X", "drift": og_drift,
              **({"quiet": og_quiet} if og_quiet else {})},
             {"g": T0 + lag_s, "creator": "B", "symbol": "ogx", "name": "Cp X", "drift": 0.0},
             {"g": T0 + lag_s + 900, "creator": "C", "symbol": "OGX", "name": "Cp Y", "drift": 0.0}]
    fr = market_frames(coins)
    ds = ds_of(fr)
    return ds, reg_of(fr, ds)


def test_event_decision_timing():
    ds, reg = _pair(40 * 60 + 13)
    strat = Q.make_strategy(reg)
    o, cd = mint_of(0), ds.coin(mint_of(0))
    g_m = T0 + 40 * 60 + 13
    t_m = Q.grid_time_from(cd, g_m + Q.EVENT_DELAY_S)
    assert t_m - 60 < g_m + 420 <= t_m
    p60 = Q.make_params(60, "hold60")
    assert strat(ds.asof(o, t_m - 60), p60, None) is None                # before the event's decision
    e = strat(ds.asof(o, t_m), p60, None)
    assert isinstance(e, C.Enter) and e.tag == "copy1" and e.exits == Q.exits_of(p60)
    assert e.state["copy"] == mint_of(1) and e.state["lag_s"] == pytest.approx(g_m - cd.g)
    assert strat(ds.asof(o, t_m + 60), p60, None) is None                # the event passed; the next copy may come
    t_m2 = Q.grid_time_from(cd, g_m + 900 + Q.EVENT_DELAY_S)
    e2 = strat(ds.asof(o, t_m2), p60, None)
    assert isinstance(e2, C.Enter) and e2.tag == "copy2+" and e2.state["copy"] == mint_of(2)
    assert strat(ds.asof(o, cd.g + 3600 + 480 + 60), p60, None) is C.SKIP  # past W + 8 min: nothing can come due
    # the copy is never itself traded by arm B (it is not an OG); the second copy's OG is coin 0, not coin 1
    assert strat(ds.asof(mint_of(1), Q.grid_time_from(ds.coin(mint_of(1)), g_m + 1800)), p60, None) is C.SKIP
    pv = C.PositionView(mint=o, t_dec=0.0, t_in=0.0, entry_price=1.0, tokens=1.0, sol_in=0.2, peak=1.0, bars_held=1,
                        unrealized=0.0, exits=Q.exits_of(p60), state={}, is_placebo=True)
    assert strat(ds.asof(o, t_m), p60, pv) is None                       # exits are mechanical only


def test_event_needs_og_age_alive_and_window():
    # copy 10 min after the OG: decision at ~17-18 min, OG younger than 30 min -> no entry from that event
    ds, reg = _pair(600)
    strat = Q.make_strategy(reg)
    cd = ds.coin(mint_of(0))
    t_m = Q.grid_time_from(cd, T0 + 600 + 420)
    assert strat(ds.asof(mint_of(0), t_m), Q.make_params(60, "hold60"), None) is None
    # the second copy (25 min) decides at ~32 min: the OG is old enough now
    t2 = Q.grid_time_from(cd, T0 + 1500 + 420)
    assert isinstance(strat(ds.asof(mint_of(0), t2), Q.make_params(60, "hold60"), None), C.Enter)
    # lag 70 min > W = 60 min: never, but W = 150 trades it
    ds, reg = _pair(70 * 60)
    strat = Q.make_strategy(reg)
    t_m = Q.grid_time_from(ds.coin(mint_of(0)), T0 + 4200 + 420)
    assert strat(ds.asof(mint_of(0), t_m), Q.make_params(60, "hold60"), None) is C.SKIP
    assert isinstance(strat(ds.asof(mint_of(0), t_m), Q.make_params(150, "hold60"), None), C.Enter)
    # the OG is not alive at the event (quiet) -> this event passes
    ds, reg = _pair(40 * 60, og_quiet=(0, 120))
    strat = Q.make_strategy(reg)
    t_m = Q.grid_time_from(ds.coin(mint_of(0)), T0 + 2400 + 420)
    assert strat(ds.asof(mint_of(0), t_m), Q.make_params(60, "hold60"), None) is None


def test_backtest_and_event_placebo():
    fr = market_frames(spill_market(T0, 6, 6))
    ds = ds_of(fr)
    reg = reg_of(fr, ds)
    cls = Q.g1_classes(ds)
    p = Q.make_params(150, "hold60")
    strat = Q.make_strategy(reg)
    res = C.backtest(strat, "train", p, hypothesis="Q2-unit", ds=ds, cfg=Q.FILL, n_placebo=3,
                     placebo_eligible=Q.placebo_alive, placebo_strata=Q.make_stratum(cls), ledger_path=None,
                     declarations=Q.DECL)
    t = res.trades
    ogs = {mint_of(2 * i) for i in range(6)}
    assert len(t) == 6 and set(t["mint"]) == ogs and set(t["tag"]) == {"copy1"}
    for r in t.itertuples(index=False):                                    # decided exactly at the copy's event
        cd = ds.coin(r.mint)
        g_m = cd.g + 31 * 60 + 7
        assert r.t_dec == Q.grid_time_from(cd, g_m + 420) and r.age_dec_s >= Q.OG_MIN_AGE_S
    assert (t["reason"] == "time").all() and not C.auto_rejections(res)
    for r in res.placebo.itertuples(index=False):
        assert cls[r.mint] == cls[r.signal_mint]
    ann = Q.annotate_b(t, ds, reg, cls, p["window_s"])
    assert (ann["og_pos"] == 0).all() and (ann["lag_s"] == 31 * 60 + 7).all() and (ann["copy_link"] == "symbol").all()
    ents = Q.event_placebo_entries(ds, reg, t, p)
    assert ents and len(ents) <= Q.EV_DRAWS * len(t)
    for m, tt, e in ents:
        cd = ds.coin(m)
        later = reg.later_same_key(m)
        assert (tt - C.GRID_OFFSET_S - cd.m0) % 60 == 0
        assert Q.OG_MIN_AGE_S <= tt - cd.g <= p["window_s"] + 480 and ds.asof(m, tt).alive()
        assert not ((later > tt - Q.QUIET_S) & (later <= tt)).any() and e.exits == Q.exits_of(p)
    assert ents == Q.event_placebo_entries(ds, reg, t, p)                   # seeded
    ev = C.run_entries(ds, strat, p, Q.FILL, ents)
    cmp = Q.event_compare(t, ev, B=300, hide=False)
    assert cmp["n_matched"] == 6 and not cmp["computable"] and cmp["mean_diff"] > 0.2
    assert set(Q.event_compare(t, ev, B=300, hide=True)) == {"n_signals", "n_matched", "n_placebo", "computable"}
    # W = 60: the only quiet ages (30-31 min, before the copy) are not alive -> nothing to compare with
    p60 = Q.make_params(60, "hold60")
    assert Q.event_placebo_entries(ds, reg, C.run_trades(ds, strat, p60, Q.FILL), p60) == []


# =========================================================================== no lookahead


def _structure_answers(reg: Q.Registry, mints, T: float) -> dict:
    out = {}
    for m in mints:
        gr = reg.grads.get(m)
        if gr is None or gr.g > T:
            continue
        cl = reg.cluster(m)
        out[m] = (None if cl is None else (cl["pos"], cl["og"], cl["link"]),
                  tuple((g, x) for g, x in reg.copies(m) if g + Q.EVENT_DELAY_S <= T))
    return out


@pytest.mark.parametrize("seed", range(3))
def test_registry_and_decisions_unchanged_by_the_future(seed):
    rng = np.random.default_rng(seed)
    coins = spill_market(T0, 5, 3, prefix="L") + family_market(T0 + 400, 4, prefix="M", stagger=2400)
    for c in coins:
        c["phases"] = [(0, float(rng.normal(0, 0.01)))]
        c.pop("quiet", None)
    frames = market_frames(coins, seed=seed)
    clean = ds_of(frames)
    T = T0 + int(rng.integers(5000, 8000))
    dirty = frames
    for m in clean.mints:
        dirty = _garble(dirty, m, T - C.DECISION_LAG_S, rng)
    g2 = dirty[0].copy()
    fut = g2["g_ts"] > T - C.DECISION_LAG_S                 # future graduates: their structure is future too
    g2.loc[fut, "symbol"] = "OGL0"                           # renamed into existing clusters -- in the future
    g2.loc[fut, "name"] = "FamMa"
    dirty = (g2, dirty[1], dirty[2])
    dirty_ds = ds_of(dirty)
    assert set(dirty_ds.mints) == set(clean.mints)
    reg_c, reg_d = reg_of(frames, clean), reg_of(dirty, dirty_ds)
    a, d = _structure_answers(reg_c, clean.mints, T), _structure_answers(reg_d, clean.mints, T)
    assert a == d and any(v[0] and v[0][0] > 0 for v in a.values())
    assert any(v[1] for v in a.values())                    # some copy event before T is checked
    strat_c, strat_d = Q.make_strategy(reg_c), Q.make_strategy(reg_d)
    for p in Q.GRID_B:
        tc = C.run_trades(clean, strat_c, p, Q.FILL)
        td = C.run_trades(dirty_ds, strat_d, p, Q.FILL)
        assert sorted(tc.loc[tc["t_dec"] <= T, ["mint", "t_dec", "tag"]].itertuples(index=False)) == \
            sorted(td.loc[td["t_dec"] <= T, ["mint", "t_dec", "tag"]].itertuples(index=False))
    for fn, hp in ((g1.host_r0, Q.HOST_PARAMS), (Q.host_r30, Q.DOSE_PARAMS)):
        hc = C.run_trades(clean, fn, hp, Q.FILL)
        hd = C.run_trades(dirty_ds, fn, hp, Q.FILL)
        hc, hd = hc[hc["t_dec"] <= T], hd[hd["t_dec"] <= T]
        ac = Q.annotate_hosts(hc, reg_c, Q.g1_classes(clean))
        ad = Q.annotate_hosts(hd, reg_d, Q.g1_classes(dirty_ds))
        assert sorted(zip(hc["mint"], hc["t_dec"], ac["pos"].fillna(-1), ac["g1_class"])) == \
            sorted(zip(hd["mint"], hd["t_dec"], ad["pos"].fillna(-1), ad["g1_class"]))


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_structure():
    """Real graduates (structure only, the census TRAIN third's pool): renaming every graduate after T into the most
    common keys changes no pos, OG or copy event known at T. No price or outcome is read."""
    gr = pd.read_parquet(C.flow_dir() / "graduates.parquet")
    cen = C.Census.load()
    hi = float(cen.train_hi) + 1.0
    rows = Q.structure_rows_from_frames(gr, cen, hi)
    if len(rows) < 200:
        pytest.skip("too few graduates in this snapshot")
    reg_c = Q.Registry.from_rows(rows)
    gs = sorted(r["g"] for r in rows)
    top_sym = max(reg_c.by_sym, key=lambda k: len(reg_c.by_sym[k][1]))
    n_checked = 0
    for T in (gs[len(gs) // 2] + 900.0, gs[(3 * len(gs)) // 4] + 300.0):
        dirty = [dict(r, symbol=top_sym, name=top_sym) if r["g"] > T - C.DECISION_LAG_S else r for r in rows]
        reg_d = Q.Registry.from_rows(dirty)
        mints = [r["mint"] for r in rows if r["g"] <= T][-400:]
        a, d = _structure_answers(reg_c, mints, T), _structure_answers(reg_d, mints, T)
        assert a == d
        n_checked += len(a)
    assert n_checked > 0


# =========================================================================== veto, random veto, dose


def _host(n_f, n_u, f_ret, u_ret, n_unknown=0, seed=0, pos_f=3):
    rng = np.random.default_rng(seed)
    rows = [{"mint": f"f{i}", "ret_net": f_ret + rng.normal(0, 0.02), "pos": pos_f, "g1_class": "FACTORY" if i % 2
             else "ORGANIC", "lookback_full": True, "link": "symbol"} for i in range(n_f)]
    rows += [{"mint": f"u{i}", "ret_net": u_ret + rng.normal(0, 0.02), "pos": 0, "g1_class": "ORGANIC",
              "lookback_full": i % 3 != 0, "link": None} for i in range(n_u)]
    rows += [{"mint": f"x{i}", "ret_net": 5.0, "pos": None, "g1_class": "ORGANIC", "lookback_full": None,
              "link": None} for i in range(n_unknown)]
    t = pd.DataFrame(rows)
    t["pos"] = t["pos"].astype(float)
    return t


def test_veto_eval():
    v = Q.veto_eval(_host(40, 40, -0.30, 0.05, n_unknown=7), 1, B=500, hide=False,
                    oos=_host(20, 20, -0.30, 0.05, seed=1))
    assert v["n_flagged"] == 40 and v["n_unflagged"] == 40 and v["n_unknown"] == 7      # NULL pos: never in the verdict
    assert v["verdict"]["verdict"] == "PASS" and v["n_oos"] == 40
    assert v["flagged_mean"] == pytest.approx(-0.30, abs=0.02) and set(v["by_g1"]) == {"FACTORY", "ORGANIC"}
    assert v["random_veto"]["p_random"] < 0.01 and v["random_veto"]["p_within_g1"] < 0.01
    assert set(v["by_lookback"]) == {"full", "partial"}
    v3 = Q.veto_eval(_host(40, 40, -0.30, 0.05, pos_f=2), 3, B=200, hide=False)
    assert v3["n_flagged"] == 0 and v3["verdict"]["verdict"] == "UNDERPOWERED"
    h = Q.veto_eval(_host(40, 40, -0.3, 0.05), 1, B=200, hide=True)
    assert "verdict" not in h and "flagged_mean" not in h and "random_veto" not in h and h["n_flagged"] == 40
    conf = Q.veto_eval(_host(40, 40, -0.30, 0.05), 1, B=500, hide=False, oos_is_self=True)
    assert {c["id"] for c in conf["verdict"]["criteria"]} == {1, 2, 3}
    assert Q.veto_eval(_host(40, 40, 0.30, 0.05), 1, B=500, hide=False)["verdict"]["verdict"] == "FAIL"
    st = _host(40, 40, -0.40, 0.0)
    vs = Q.veto_eval(_host(40, 40, -0.30, 0.05), 1, B=200, hide=False, stress_host=st)
    assert vs["stress_costs_x1.5"]["flagged_mean"] == pytest.approx(-0.40, abs=0.02)
    empty = Q.veto_eval(Q._empty_host(), 1, B=200, hide=False, oos=_host(20, 20, -0.3, 0.05))
    assert empty["verdict"]["verdict"] == "UNDERPOWERED"


def test_random_veto_within_class():
    # the flag is exactly the FACTORY class: all of its "value" is G1's -> within-class p is uninformative (no
    # within-class reshuffle can move a flag), across-class p is tiny
    r = np.array([-0.3] * 30 + [0.05] * 30)
    f = np.array([True] * 30 + [False] * 30)
    cls = ["FACTORY"] * 30 + ["ORGANIC"] * 30
    rv = Q.random_veto(r, f, cls, n=500)
    assert rv["p_random"] < 0.01 and rv["p_within_g1"] == 1.0
    assert Q.random_veto(r, np.zeros(60, bool), cls) is None


def _dose_trades(means, n=35, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for b, mu in zip(Q.POS_BINS, means):
        for i in range(n):
            rows.append({"mint": f"{b}_{i}", "ret_net": mu + rng.normal(0, 0.05), "pos_bin": b,
                         "g1_class": "ORGANIC" if i % 2 else "FACTORY", "lookback_full": True})
    rows.append({"mint": "u", "ret_net": 9.0, "pos_bin": "unknown", "g1_class": "ORGANIC", "lookback_full": None})
    return pd.DataFrame(rows)


def test_dose_eval():
    d = Q.dose_eval(_dose_trades((0.1, 0.0, -0.1, -0.2)), B=300, hide=False)
    assert d["reading"] == "NEGATIVE" and d["spearman"] < -0.5 and d["spearman_ci95"][1] < 0
    assert d["counts"]["unknown"] == 1 and d["by_bin"]["0"]["n"] == 35 and set(d["counts_by_g1"]) == {"FACTORY",
                                                                                                     "ORGANIC"}
    assert Q.dose_eval(_dose_trades((0.0, 0.0, 0.0, 0.0)), B=300, hide=False)["reading"] == "NONE"
    assert Q.dose_eval(_dose_trades((0.1, 0.0, -0.1, -0.2), n=20), B=300, hide=False)["reading"] == "UNDERPOWERED"
    h = Q.dose_eval(_dose_trades((0.1, 0.0, -0.1, -0.2)), B=300, hide=True)
    assert set(h) == {"n", "counts", "counts_by_g1"}


# =========================================================================== decision rules


def _ev(n, mean, w2, pc, ci_lo, ev_diff=0.05, matched=12, wbc=None):
    return {"n": n, "mean": mean, "mean_without_top2": w2, "placebo": {"mean_diff": pc}, "ci90": (ci_lo, ci_lo + 0.1),
            "event_placebo": {"mean_diff": ev_diff, "n_matched": matched, "computable": matched >= Q.EV_MIN_MATCHED},
            "creators": {"mean_without_best_creator": mean if wbc is None else wbc}}


def _ve(nf, nu, diff, ci_hi, removed=0.0):
    crit = [{"id": 1, "pass": bool(diff <= -0.10 and ci_hi < 0), "value": diff, "ci95": (diff - 0.1, ci_hi)},
            {"id": 3, "pass": bool(removed < 0.25), "value": removed}]
    return {"n_flagged": nf, "n_unflagged": nu, "flagged_mean": -0.2, "unflagged_mean": -0.2 - diff,
            "verdict": {"verdict": "INCOMPLETE", "criteria": crit}}


def _vetoes(**kw):
    out = {P: _ve(10, 10, 0.0, 0.1) for P in Q.P_GRID}
    for k, v in kw.items():
        out[int(k[1:])] = v
    return out


def test_decide_train_both_branches():
    ev = {Q.config_key(p): _ev(40, 0.05, 0.03, 0.02, 0.01) for p in Q.GRID_B}
    ev["B|W150|deadline"] = _ev(40, 0.04, 0.03, 0.02, 0.02)
    d = Q.decide_train(ev, _vetoes())
    assert d["verdict"] == "SHORTLISTED" and d["branches"] == ["entry"] and d["entry"]["chosen"] == "B|W150|deadline"
    assert d["shortlist"][Q.HYP] == [Q.make_params(150, "deadline")] and d["shortlist"][Q.HYP_HOST] == []
    assert d["shortlist"][Q.HYP_DOSE] == [Q.DOSE_PARAMS]
    tie = Q.decide_train({Q.config_key(p): _ev(40, 0.05, 0.03, 0.02, 0.01) for p in Q.GRID_B}, _vetoes())
    assert tie["entry"]["chosen"] == "B|W60|hold60"                       # ties: W = 60, then hold60
    # the event-time placebo is part of the TRAIN bar: not computable or not beaten -> no entry
    for bad_ev in ({"ev_diff": -0.01}, {"matched": 9}, {"pc": -0.01}, {"w2": -0.01}):
        kw = dict(n=40, mean=0.05, w2=0.03, pc=0.02, ci_lo=0.01)
        kw.update({k: v for k, v in bad_ev.items() if k in kw})
        rows = {Q.config_key(p): _ev(**kw, **{k: v for k, v in bad_ev.items() if k not in kw}) for p in Q.GRID_B}
        assert Q.decide_train(rows, _vetoes())["verdict"] == "NO_CONFIG"
    # VETO only: criteria 1 AND 3; the lower CI upper bound; ties -> P = 3
    bad = {Q.config_key(p): _ev(40, -0.05, -0.03, 0.02, -0.1) for p in Q.GRID_B}
    d2 = Q.decide_train(bad, _vetoes(P1=_ve(40, 40, -0.2, -0.05), P3=_ve(40, 40, -0.15, -0.01)))
    assert d2["branches"] == ["veto"] and d2["veto"]["P"] == 1 and d2["shortlist"][Q.HYP] == []
    assert d2["shortlist"][Q.HYP_HOST] == [Q.HOST_PARAMS] and d2["shortlist"][Q.HYP_DOSE] == [Q.DOSE_PARAMS]
    d3 = Q.decide_train(bad, _vetoes(P1=_ve(40, 40, -0.2, -0.05), P3=_ve(40, 40, -0.2, -0.05)))
    assert d3["veto"]["P"] == 3
    d4 = Q.decide_train(bad, _vetoes(P1=_ve(40, 40, -0.2, -0.05, removed=0.3)))
    assert d4["verdict"] == "NO_CONFIG"                                    # criterion 3 fails on TRAIN
    both = Q.decide_train(ev, _vetoes(P3=_ve(40, 40, -0.15, -0.01)))
    assert both["branches"] == ["entry", "veto"]
    small = {Q.config_key(p): _ev(29, 0.05, 0.03, 0.02, 0.01) for p in Q.GRID_B}
    assert Q.decide_train(small, _vetoes())["verdict"] == "UNDERPOWERED_TRAIN"
    assert Q.decide_train(small, _vetoes(P1=_ve(40, 40, -0.05, 0.02)))["verdict"] == "NO_CONFIG"


def test_decide_val_both_branches():
    assert Q.decide_val({"n": 4, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "UNDERPOWERED_VAL"
    assert Q.decide_val({"n": 20, "mean": -0.1, "mean_without_top2": 0.1})["verdict"] == "FAIL_VAL"
    assert Q.decide_val({"n": 10, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "SELECTED_UNDERPOWERED"
    assert Q.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "SELECTED"
    ve = lambda nf, nu, fm, um, c1=None: {"n_flagged": nf, "n_unflagged": nu, "flagged_mean": fm,   # noqa: E731
                                          "unflagged_mean": um, "verdict": {"criteria": [c1] if c1 else []}}
    assert Q.decide_val_veto(ve(3, 40, -0.3, 0.0))["verdict"] == "UNDERPOWERED_VAL"
    assert Q.decide_val_veto(ve(20, 40, 0.1, 0.0))["verdict"] == "FAIL_VAL"
    assert Q.decide_val_veto(ve(20, 40, -0.1, 0.0))["verdict"] == "SELECTED_UNDERPOWERED"
    assert Q.decide_val_veto(ve(40, 40, -0.3, 0.0, {"id": 1, "pass": True}))["verdict"] == "SELECTED"
    assert Q.decide_val_veto(ve(40, 40, -0.05, 0.0, {"id": 1, "pass": False}))["verdict"] == "FAIL_VAL"


def test_extras_and_combine():
    def base(passes, rej=()):
        return {"auto_rejections": list(rej), "criteria": [{"id": i + 1, "pass": v} for i, v in enumerate(passes)]}
    ok = [True] * 10
    ex = Q.q2_extras(_ev(70, 0.05, 0.03, 0.1, 0.01))
    assert [e["id"] for e in ex] == ["Q2.1", "Q2.2"] and all(e["pass"] for e in ex)
    assert Q.combine_verdict(base(ok), ex) == "PASS"
    assert Q.combine_verdict(base(ok, ["x"]), ex) == "REJECTED"
    assert Q.combine_verdict(base([False] + ok[1:]), ex) == "UNDERPOWERED"
    assert Q.combine_verdict(base(ok[:4] + [False] + ok[5:]), ex) == "FAIL"
    assert Q.combine_verdict(base(ok[:9] + [False]), ex) == "INCOMPLETE"          # > 10 % censored
    assert Q.combine_verdict(base(ok), Q.q2_extras(_ev(70, 0.05, 0.03, 0.1, 0.01, ev_diff=-0.01))) == "FAIL"
    assert Q.combine_verdict(base(ok), Q.q2_extras(_ev(70, 0.05, 0.03, 0.1, 0.01, matched=9))) == "INCOMPLETE"
    assert Q.combine_verdict(base(ok), Q.q2_extras(_ev(70, 0.05, 0.03, 0.1, 0.01, wbc=-0.01))) == "FAIL"


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Q2", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Q2 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Q.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=3, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Q.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def spill(split, t0, n_pairs, n_fill, prefix, seed, mode="spill", stagger=600):
    return ds_of(market_frames(spill_market(t0, n_pairs, n_fill, prefix, mode, stagger), seed=seed), split)


def fam(split, t0, n_fam, prefix, seed, stagger=1800):
    return ds_of(market_frames(family_market(t0, n_fam, prefix, stagger), seed=seed), split)


def test_debug_stage_hides_returns(st):
    ds = spill("train", T0, 12, 8, "D", 9)
    ds.split, ds.debug_only = "final_train", True
    doc = Q.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        for k in ("mean", "ci90", "placebo", "reasons", "stress", "portfolio", "creators", "diagnostics"):
            assert k not in e
        assert e["returns"].startswith("hidden") and "mean_diff" not in e["event_placebo"]
    for v in doc["veto"].values():
        assert "verdict" not in v and "flagged_mean" not in v and "random_veto" not in v and "by_g1" not in v
    assert set(doc["dose"]) == {"n", "counts", "counts_by_g1"}
    ec = doc["event_counts"]
    assert ec["pos_bins"]["0"] == 20 and ec["pos_bins"]["1"] == 12 and ec["og_with_copy_in_W"] == {"60min": 12,
                                                                                                    "150min": 12}
    assert ec["first_copy_lag"]["30-60min"] == 12
    assert doc["configs"]["B|W150|hold60"]["n"] == 12 and doc["configs"]["B|W60|hold60"]["n"] == 12
    assert doc["configs"]["B|W60|hold60"]["event_placebo"]["n_matched"] == 0
    assert doc["configs"]["B|W150|hold60"]["event_placebo"]["n_matched"] == 12
    led = json.loads(st.ledger.read_text())
    assert led["runs"] and all(r["debug"] for r in led["runs"]) and not led["configs"]
    assert (st.out / "debug.md").exists() and not list(st.out.glob("*_trades.csv"))
    md = (st.out / "debug.md").read_text()
    assert "hidden" in md and "%" not in md.split("## Arm B")[1].split("## Decision")[0]


def test_provisional_train_never_unlocks_val(st):
    ds = spill("train", T0, 36, 24, "A", 1)
    with pytest.raises(Q.Q2Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Q2.json").exists()
    with pytest.raises(Q.Q2Refused, match="no TRAIN result"):
        _check("val", st)


def test_spillover_pipeline_and_every_refusal(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    with pytest.raises(Q.Q2Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: the OG runs right after its copy's event; W = 60 has no quiet alive time to compare with
    ds_tr = spill("train", T0, 36, 24, "A", 1)
    tr = _run("train", st, ds_tr)
    assert set(tr["configs"]) == {Q.config_key(p) for p in Q.GRID_B}
    dec = tr["decision"]
    assert dec["verdict"] == "SHORTLISTED" and dec["branches"] == ["entry"], dec
    assert dec["entry"]["chosen"] == "B|W150|hold60" and dec["shortlist_written"]
    rows = {r["config"]: r for r in dec["entry_rows"]}
    assert rows["B|W60|hold60"]["event_matched"] == 0 and not rows["B|W60|hold60"]["qualifies"]
    assert rows["B|W150|hold60"]["event_diff"] > 0.1 and rows["B|W150|hold60"]["placebo_diff"] > 0
    assert set(tr["veto"]) == {"1", "3"} and tr["veto"]["1"]["verdict"]["verdict"] == "FAIL"
    assert tr["dose"]["reading"] == "UNDERPOWERED"
    led = json.loads(st.ledger.read_text())
    hyps = sorted(v["hypothesis"] for v in led["configs"].values())
    assert hyps == sorted(["Q2"] * 4 + ["Q2-host", "Q2-dose"] + ["Q2-veto"] * 2)
    assert led["n_trials_total"] == 2575 + 8
    assert any(r["kind"] == "run_entries" for r in led["runs"])         # the event-time placebo: no new trial
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    assert tr["overall"].startswith("ENTRY: PENDING VAL; VETO: NO VETO")
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Q.Q2Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Q2 test prereg\n")
    with pytest.raises(Q.Q2Refused, match="no VAL result"):
        _check("test", st, env=ENV_ALL)
    with pytest.raises(Q.Q2Refused, match="before TEST"):
        _check("final", st, env=ENV_ALL)
    with pytest.raises(Q.Q2Refused, match="before TEST"):
        _check("confirm", st, env=ENV_ALL)
    sl = (st.sl / "Q2-dose.json").read_text()
    (st.sl / "Q2-dose.json").unlink()
    with pytest.raises(Q.Q2Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Q2-dose.json").write_text(sl)
    with pytest.raises(Q.Q2Refused, match="already ran"):
        _run("train", st, ds_tr)
    # ---- VAL
    va = _run("val", st, spill("val", C.utc_ts("2026-10-05 02:00") + 5, 16, 8, "B", 2))
    assert set(va["configs"]) == {"candidate"} and va["decision"]["entry"]["verdict"] == "SELECTED"
    assert va["decision"]["veto"] is None and va["dose"]["n"] > 0 and va["configs"]["candidate"]["n"] == 16
    with pytest.raises(Q.Q2Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_te = spill("test", C.utc_ts("2026-10-06 13:00") + 5, 8, 6, "C", 3)
    with pytest.raises(Q.Q2Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_te)
    te = _run("test", st, ds_te, env=ENV_ALL)
    assert te["decision"]["entry"]["verdict"] == "UNDERPOWERED"          # < 60 trades: never PASS / FAIL
    assert {c["id"] for c in te["decision"]["entry"]["q2_extras"]} == {"Q2.1", "Q2.2"}
    with pytest.raises(Q.Q2Refused, match="already ran"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Q.Q2Refused, match="one test run"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] == "test"} == {"Q2", "Q2-dose"}
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, spill("confirm", C.utc_ts("2026-09-20 00:00") + 5, 70, 30, "E", 4), env=ENV_ALL)
    assert co["decision"]["entry"]["verdict"] == "PASS", co["decision"]["entry"]
    assert co["overall"].startswith("ENTRY: PENDING FINAL")
    # ---- FINAL
    fi = _run("final", st, spill("final", C.FINAL_LO + 3600 + 5, 8, 6, "F", 5), env=ENV_ALL)
    assert fi["decision"]["entry"]["n"] > 0 and fi["decision"]["entry"]["mean_positive"] is True
    assert fi["decision"]["veto"] is None and fi["overall"].startswith("ENTRY: EDGE")
    with pytest.raises(Q.Q2Refused, match="already ran"):
        _check("final", st, env=ENV_ALL)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_copy_order_veto_pipeline(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    ds_tr = fam("train", T0, 32, "A", 1)
    tr = _run("train", st, ds_tr)
    dec = tr["decision"]
    assert dec["verdict"] == "SHORTLISTED" and dec["branches"] == ["veto"] and dec["veto"]["P"] == 1, dec
    assert all(r["n"] == 0 for r in dec["entry_rows"])                   # copies come before the OG is 30 min old
    assert not (st.sl / "Q2.json").exists() and (st.sl / "Q2-host.json").exists()
    v1 = tr["veto"]["1"]
    assert v1["n_flagged"] == 3 * v1["n_unflagged"] and v1["flagged_mean"] < v1["unflagged_mean"] - 0.10
    assert v1["random_veto"]["p_random"] < 0.01
    assert tr["dose"]["reading"] == "NEGATIVE" and tr["dose"]["counts"] == {"0": 32, "1": 32, "2": 32, "3+": 32}
    assert "DOSE: NEGATIVE (train)" in tr["overall"]
    va = _run("val", st, fam("val", C.utc_ts("2026-10-05 02:00") + 5, 12, "B", 2))
    assert set(va["configs"]) == set() and va["decision"]["entry"] is None
    assert va["decision"]["veto"]["verdict"] == "SELECTED_UNDERPOWERED"   # 36 flagged, 12 unflagged
    te = _run("test", st, fam("test", C.utc_ts("2026-10-06 13:00") + 5, 8, "C", 3), env=ENV_ALL)
    assert te["decision"]["entry"] is None and te["veto"]["n_oos"] == 32
    assert te["decision"]["veto"]["verdict"]["verdict"] == "UNDERPOWERED"   # VAL in sample has 12 unflagged
    co = _run("confirm", st, fam("confirm", C.utc_ts("2026-09-20 00:00") + 5, 32, "E", 4), env=ENV_ALL)
    assert co["decision"]["veto"]["verdict"]["verdict"] == "PASS" and co["decision"]["entry"] is None
    fi = _run("final", st, fam("final", C.FINAL_LO + 3600 + 5, 6, "F", 5), env=ENV_ALL)
    assert fi["decision"]["veto"]["flagged_worse"] is True and fi["decision"]["entry"] is None
    assert fi["overall"].startswith("ENTRY: NO EDGE (did not qualify on TRAIN); VETO: VETO")


def test_dead_branches_refuse_later_stages(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    _run("train", st, spill("train", T0, 36, 24, "A", 1))
    va = _run("val", st, spill("val", C.utc_ts("2026-10-05 02:00") + 5, 16, 8, "B", 2, mode="flat"))
    assert va["decision"]["entry"]["verdict"] == "FAIL_VAL" and not va["decision"]["proceed"]
    with pytest.raises(Q.Q2Refused, match="no live branch"):
        _check("test", st, env=ENV_ALL)
    assert va["overall"].startswith("ENTRY: NO EDGE (failed VAL)")


def test_nothing_qualifies_stops_q2(st):
    flat = [{"g": T0 + 900 * i, "creator": f"F{i}", "symbol": f"FL{i}", "name": f"Flat {letters(i)}zz", "drift": 0.0}
            for i in range(20)]
    tr = _run("train", st, ds_of(market_frames(flat, seed=3)))
    assert tr["decision"]["verdict"] == "UNDERPOWERED_TRAIN" and tr["overall"].startswith("UNDERPOWERED (TRAIN)")
    with pytest.raises(Q.Q2Refused, match="UNDERPOWERED_TRAIN"):
        _check("val", st)


def test_data_gates_prereg_and_host_pin_refuse(st, monkeypatch):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Q.Q2Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    monkeypatch.setattr(Q, "R0_PIN", "000000000000")
    with pytest.raises(Q.Q2Refused, match="R0 host changed"):
        _check("train", st)
    monkeypatch.undo()
    monkeypatch.setenv("LAB2_TRIALS", str(st.ledger))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Q.Q2Refused, match="pre-register"):
        _check("train", st)


def test_pool_hi_never_reaches_a_later_split():
    cen = C.Census.empty()
    assert Q.pool_hi("train", cen) == C.SPLIT_BOUNDS["train"][1]
    assert Q.pool_hi("val", cen) == C.SPLIT_BOUNDS["val"][1]
    assert Q.pool_hi("confirm", cen) == C.SPLIT_BOUNDS["confirm"][1]
    assert Q.pool_hi("debug", cen) == cen.train_hi + 1
    assert Q.pool_hi("final", cen) == math.inf

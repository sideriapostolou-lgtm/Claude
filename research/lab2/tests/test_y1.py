"""Tests for research/lab2/y1.py: the deployer registry (shared-key rules, causal records), the strategy's entry
logic, no lookahead (synthetic and real census bars: garbage after T changes no registry answer and no decision at
tau <= T), the persistence gate, the veto, the pre-registered decision rules and every stage refusal."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import y1 as Y
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
ENV_ALL = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}


# =========================================================================== synthetic markets


def market_frames(coins: list[dict], seed: int = 0):
    """Graduates / b2_coins / b2_bars for hand-specified coins: {g, creator (None = creation not scanned), signer,
    symbol, drift (per-minute log price change from g), jump_at (minute) and jump (log change) optional}. Prices
    move along X * y = k with a bar in every minute."""
    g0, c0, _ = make_frames(n=1, seed=seed, slow_every=0, agent_every=0)
    tg, tc = g0.iloc[0].to_dict(), c0.iloc[0].to_dict()
    grads, cs, bars = [], [], []
    k = X0 * Y0
    for i, s in enumerate(coins):
        mint, pool = f"Y{i:04d}{seed}pump", f"YP{i:04d}{seed}"
        g = int(s["g"])
        cr = s.get("creator")
        r = dict(tg)
        r.update(mint=mint, pool=pool, g_ts=g, g_slot=10_000 + i, pool_ts=g + 2, pool_slot=10_001 + i)
        if cr is None:
            r.update(has_create=0, c_ts=0, c_slot=0, creator="", create_user="", symbol="", name="", vsol0=0.0,
                     grad_delay_s=float(g))
        else:
            r.update(has_create=1, c_ts=g - 3, c_slot=9_000 + i, creator=cr, create_user=s.get("signer", cr),
                     symbol=s.get("symbol", f"SYM{i}"), name=f"N{i}", grad_delay_s=3.0)
        grads.append(r)
        cc = dict(tc)
        cc.update(mint=mint, pool=pool, g_ts=g)
        cs.append(cc)
        m0 = g // 60 * 60
        lp = math.log(X0 / Y0)
        for j in range(N_MIN):
            lp0 = lp
            lp += float(s.get("drift", 0.0))
            if s.get("jump_at") == j:
                lp += float(s["jump"])
            p0, p1 = math.exp(lp0), math.exp(lp)
            X1, y1 = math.sqrt(k * p1), math.sqrt(k / p1)
            bars.append({"minute_ts": m0 + 60 * j, "n_buys": 5, "n_sells": 3, "n_dust": 0, "buy_sol": 2.0,
                         "sell_sol": 1.0, "buy_tok": 1e6, "sell_tok": 1e6, "n_buyers": 4, "n_sellers": 3,
                         "top5_buy_sol": 2.0, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                         "x_close": X1 - V0, "y_close": y1, "mint": mint, "pool": pool, "g_ts": g, "minute_idx": j,
                         "agent_buy_sol": 0.0, "price_repaired": 0})
    return pd.DataFrame(grads), pd.DataFrame(cs), pd.DataFrame(bars)


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def mint_of(i: int, seed: int = 0) -> str:
    return f"Y{i:04d}{seed}pump"


def creators_market(t0: int, n_good: int, n_bad: int, per: int, prefix: str = "A", gap: int = 7200,
                    stagger: int = 300, drift: float = 0.01, n_new: int = 6) -> list[dict]:
    """Good deployers' coins rise ``drift`` per minute after g, bad ones fall; each deployer launches ``per`` coins
    ``gap`` seconds apart. Plus ``n_new`` one-off coins (new creators)."""
    out = []
    for ci in range(n_good + n_bad):
        good = ci < n_good
        for kk in range(per):
            out.append({"g": t0 + ci * stagger + kk * gap, "creator": f"{prefix}CR{ci}", "symbol": f"{prefix}SY{ci}",
                        "drift": drift if good else -drift})
    for j in range(n_new):
        out.append({"g": t0 + 137 * j + 50, "creator": f"{prefix}NEW{j}", "symbol": f"{prefix}NS{j}", "drift": 0.0})
    return out


def grid_t(ds: C.Dataset, m: str, age_s: float) -> float:
    return Y.grid_time_from(ds.coin(m), ds.coin(m).g + age_s)


def registry(ds: C.Dataset, frames=None, history=()) -> Y.Registry:
    rows = Y.deployer_rows_from_frames(frames[0], C.Census.empty(), -math.inf, math.inf) if frames is not None else None
    return Y.build_registry([ds, *history], rows)


# =========================================================================== grid and constants


def test_grid_is_preregistered_and_small():
    assert len(Y.GRID_GOOD) == 4 and len(Y.GRID_HOST) == 2
    keys = [Y.config_key(p) for p in Y.GRID]
    assert len(set(keys)) == 6 and len({C.params_hash(p) for p in Y.GRID}) == 6
    for p in Y.GRID:
        for k, v in Y.FIXED.items():
            assert p[k] == v
    # 4 GOOD + 2 HOST + 2 veto + 1 persistence = 9 trials <= 12
    assert len(Y.GRID) + len(Y.GRID_HOST) + 1 == 9
    assert Y.HISTORY_SPLITS["train"] == ("train",)            # CONFIRM never feeds a TRAIN decision
    assert "confirm" not in Y.HISTORY_SPLITS["val"] + Y.HISTORY_SPLITS["test"] + Y.HISTORY_SPLITS["final"]
    assert Y.E_AGE_S == 420.0
    with pytest.raises(ValueError):
        Y.make_params("good", "T30", 0.05)


# =========================================================================== deployers: shared-key rules


def test_shared_rules_are_causal():
    rows = [{"mint": "a", "g": 100.0, "creator": "A", "signer": "A"},
            {"mint": "b", "g": 200.0, "creator": "B", "signer": "L"},      # L signs for B: L is a launch service
            {"mint": "l", "g": 50.0, "creator": "L", "signer": "L"},
            {"mint": "m1", "g": 300.0, "creator": "M", "signer": "M"},
            {"mint": "m2", "g": 400.0, "creator": "M", "signer": "S2"},    # a second signer under key M
            {"mint": "n", "g": 10.0, "creator": None, "signer": None}]
    rows += [{"mint": f"f{i}", "g": 1000.0 + 60 * i, "creator": "F", "signer": "F"} for i in range(Y.SHARED_MAX_24H)]
    d = Y.Deployers.from_rows(rows, pooled={"P"})
    assert d.shared("A", 1e9) is None and d.shared("B", 1e9) is None
    assert d.shared("L", 199.0) is None and d.shared("L", 200.0) == "signs_for_others"
    assert d.shared("M", 399.0) is None and d.shared("M", 400.0) == "multi_signer"
    last = 1000.0 + 60 * (Y.SHARED_MAX_24H - 1)
    assert d.shared("F", last - 1) is None and d.shared("F", last) == "factory_volume"
    assert d.shared("F", last + Y.SHARED_WINDOW_S + 61) is None           # the 24 h window moved on
    assert d.shared("P", 0.0) == "pooled"
    assert d.n_coins == len(rows)


# =========================================================================== records: labels of OTHER coins, causal


def _three_coin_market():
    coins = [{"g": T0, "creator": "X", "drift": 0.01},
             {"g": T0 + 1200, "creator": "X", "drift": -0.02},
             {"g": T0 + 7200, "creator": "X", "drift": 0.0},
             {"g": T0 + 7300, "creator": "Z", "drift": 0.0},
             {"g": T0 + 7400, "creator": None, "drift": 0.0}]
    fr = market_frames(coins)
    return fr, ds_of(fr)


def test_prior_label_is_the_post_boost_30_minute_mid_change():
    _, ds = _three_coin_market()
    m = mint_of(0)
    p = Y.prior_of(ds, m)
    cd = ds.coin(m)
    assert p.t_ref >= cd.g + Y.E_AGE_S and p.t_ref - 60 < cd.g + Y.E_AGE_S
    assert (p.t_ref - C.GRID_OFFSET_S - cd.m0) % 60 == 0
    assert p.t_end == p.t_ref + Y.H_REC_S
    assert p.ret == pytest.approx(ds.asof(m, p.t_end).price / ds.asof(m, p.t_ref).price - 1)
    assert p.ret == pytest.approx(math.exp(0.01 * 30) - 1, rel=1e-9)     # 30 completed minutes of +1 % drift


def test_record_counts_only_resolved_earlier_coins_never_itself():
    fr, ds = _three_coin_market()
    reg = registry(ds, fr)
    p0, p1 = Y.prior_of(ds, mint_of(0)), Y.prior_of(ds, mint_of(1))
    m2 = mint_of(2)
    # coin 2 at its first post-BOOST decision: both earlier coins resolved long ago
    st = reg.state(ds.asof(m2, grid_t(ds, m2, Y.E_AGE_S)))
    assert st["status"] == "eligible" and st["n_earlier"] == 2 and st["n_resolved"] == 2
    assert st["record_mean"] == pytest.approx((p0.ret + p1.ret) / 2)
    # coin 1 (g0 + 20 min): coin 0 resolves at its t_end; coin 2 is LATER and never counts
    m1 = mint_of(1)
    t_before = p0.t_end - 60
    assert reg.state(ds.asof(m1, t_before))["status"] == "pending"
    st1 = reg.state(ds.asof(m1, p0.t_end))
    assert st1["status"] == "eligible" and st1["n_earlier"] == 1 and st1["record_mean"] == pytest.approx(p0.ret)
    # coin 0 has no earlier coin: new; another creator: new; NULL creator: unknown
    assert reg.state(ds.asof(mint_of(0), grid_t(ds, mint_of(0), 600)))["status"] == "new"
    assert reg.state(ds.asof(mint_of(3), grid_t(ds, mint_of(3), 600)))["status"] == "new"
    assert reg.state(ds.asof(mint_of(4), grid_t(ds, mint_of(4), 600)))["status"] == "unknown"
    # the traded mint never scores itself, whatever t
    q = reg.records.query("X", ds.coin(m2).g + 1, m2, 1e12)
    assert q["n_earlier"] == 2


def test_record_mean_uses_the_most_recent_three():
    coins = [{"g": T0 + 3600 * i, "creator": "X", "drift": d} for i, d in enumerate((0.02, 0.01, 0.0, -0.01, 0.0))]
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = registry(ds, fr)
    rets = [Y.prior_of(ds, mint_of(i)).ret for i in range(4)]
    st = reg.state(ds.asof(mint_of(4), grid_t(ds, mint_of(4), Y.E_AGE_S)))
    assert st["n_resolved"] == 4 and st["record_mean"] == pytest.approx(np.mean(rets[1:]))


# =========================================================================== strategy


def test_strategy_entry_logic():
    coins = [{"g": T0, "creator": "G", "drift": 0.01},              # 0 good record source
             {"g": T0 + 7200, "creator": "G", "drift": 0.0},        # 1 eligible, good record
             {"g": T0 + 100, "creator": "B", "drift": -0.01},       # 2 bad record source
             {"g": T0 + 7300, "creator": "B", "drift": 0.0},        # 3 eligible, bad record
             {"g": T0 + 7400, "creator": "N", "drift": 0.0},        # 4 new creator
             {"g": T0 + 7500, "creator": None, "drift": 0.0},       # 5 creation not scanned
             {"g": T0 + 7600, "creator": "W", "drift": 0.0},        # 6 W's earlier coin is still pending ...
             {"g": T0 + 7600 - 600, "creator": "W", "drift": 0.004}]  # 7 ... (graduated 10 min earlier)
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = registry(ds, fr)
    strat = Y.make_strategy(reg)
    good0, good10 = Y.make_params("good", "T30", 0.0), Y.make_params("good", "T30", 0.10)
    host = Y.make_params("host", "T60")
    at = lambda i, a: ds.asof(mint_of(i), grid_t(ds, mint_of(i), a))     # noqa: E731
    assert strat(at(1, 300), good0, None) is None                         # BOOST still running
    e = strat(at(1, Y.E_AGE_S), good0, None)
    assert isinstance(e, C.Enter) and e.tag == "good" and e.exits.max_hold_s == 1800 and e.exits.stop_pct == 0.5
    assert e.exits.exit_by_age_s == Y.EXIT_BY_AGE_S
    assert isinstance(strat(at(1, Y.E_AGE_S), good10, None), C.Enter)     # record +35 % >= 10 %
    assert strat(at(3, Y.E_AGE_S), good0, None) is C.SKIP                 # bad record, every earlier coin resolved
    eh = strat(at(3, Y.E_AGE_S), host, None)
    assert isinstance(eh, C.Enter) and eh.tag == "bad" and eh.exits.max_hold_s == 3600
    assert strat(at(4, Y.E_AGE_S), good0, None) is C.SKIP                 # new
    assert strat(at(5, Y.E_AGE_S), good0, None) is C.SKIP                 # unknown (NULL never 0)
    assert strat(at(6, Y.E_AGE_S), good0, None) is None                   # pending: wait
    p7 = Y.prior_of(ds, mint_of(7))
    e6 = strat(ds.asof(mint_of(6), p7.t_end), good0, None)
    assert isinstance(e6, C.Enter) and e6.state["record_mean"] == pytest.approx(p7.ret)
    assert strat(at(1, Y.E_AGE_MAX_S + 60), good0, None) is C.SKIP        # window over
    pv = C.PositionView(mint=mint_of(1), t_dec=0.0, t_in=0.0, entry_price=1.0, tokens=1.0, sol_in=0.2, peak=1.0,
                        bars_held=1, unrealized=0.0, exits=C.ExitSpec(), state={}, is_placebo=True)
    assert strat(at(1, 900), good0, pv) is None                           # exits are mechanical only


def test_shared_creator_is_skipped():
    coins = [{"g": T0, "creator": "K", "drift": 0.01}, {"g": T0 + 7200, "creator": "K", "drift": 0.0},
             {"g": T0 + 100, "creator": "Q", "signer": "K", "drift": 0.0}]     # K signs for Q: K is a service
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = registry(ds, fr)
    st = reg.state(ds.asof(mint_of(1), grid_t(ds, mint_of(1), Y.E_AGE_S)))
    assert st["status"] == "shared" and st["reason"] == "signs_for_others"
    assert Y.make_strategy(reg)(ds.asof(mint_of(1), grid_t(ds, mint_of(1), Y.E_AGE_S)),
                                Y.make_params("host", "T30"), None) is C.SKIP


def test_backtest_trades_and_eligible_placebo():
    fr = market_frames(creators_market(T0, 6, 6, 3))
    ds = ds_of(fr)
    reg = registry(ds, fr)
    res = C.backtest(Y.make_strategy(reg), "train", Y.make_params("good", "T30", 0.0), hypothesis="Y1-unit", ds=ds,
                     n_placebo=5, placebo_eligible=Y.placebo_eligible, placebo_strata=Y.make_stratum(reg),
                     ledger_path=None, declarations=Y.DECL)
    t = res.trades
    assert len(t) == 12 and set(t["tag"]) == {"good"}                     # 6 good deployers x 2 later coins
    assert (t["reason"] == "time").all() and (t["age_dec_s"] >= Y.E_AGE_S).all()
    assert ((t["t_out"] - t["t_in"]) >= 1800).all()
    stratum = Y.make_stratum(reg)
    for r in res.placebo.itertuples(index=False):                         # every draw is an eligible coin
        assert stratum(ds.asof(r.mint, r.t_dec)) == "eligible" and r.age_dec_s >= Y.E_AGE_S
    assert len(res.placebo) > 0 and not C.auto_rejections(res)


# =========================================================================== no lookahead


def _decision_states(ds, reg, T):
    out = {}
    for m in ds.mints:
        cd = ds.coin(m)
        t = Y.grid_time_from(cd, cd.g + Y.E_AGE_S)
        while t <= T and t - cd.g <= Y.E_AGE_MAX_S:
            st = reg.state(ds.asof(m, t))
            out[(m, t)] = (st["status"], st.get("reason"), st.get("n_resolved"),
                           None if st.get("record_mean") is None else round(st["record_mean"], 12))
            t += 60.0
    return out


@pytest.mark.parametrize("seed", range(3))
def test_registry_and_decisions_unchanged_by_future_garbage(seed):
    rng = np.random.default_rng(seed)
    coins = creators_market(T0, 4, 4, 3, gap=2400, stagger=420, n_new=3)
    for c in coins:
        c["drift"] = float(rng.normal(0, 0.01))
    frames = market_frames(coins, seed=seed)
    clean = ds_of(frames)
    reg_c = registry(clean, frames)
    T = T0 + int(rng.integers(3000, 6000))
    g, c, b = frames
    dirty = (g, c, b)
    for m in clean.mints:
        dirty = _garble(dirty, m, T - C.DECISION_LAG_S, rng)
    g2 = dirty[0].copy()
    fut = g2["g_ts"] > T - C.DECISION_LAG_S                 # future graduates: their structure is future too
    g2.loc[fut, "create_user"] = "ACR0"                     # ACR0 would turn 'signs_for_others' -- in the future
    g2.loc[fut & (g2.index % 2 == 0), "creator"] = "ACR1"   # extra future coins of ACR1 -- in the future
    dirty = (g2, dirty[1], dirty[2])
    dirty_ds = ds_of(dirty)
    assert set(dirty_ds.mints) == set(clean.mints)
    reg_d = registry(dirty_ds, dirty)
    a, d = _decision_states(clean, reg_c, T), _decision_states(dirty_ds, reg_d, T)
    assert a == d and sum(1 for v in a.values() if v[0] == "eligible") > 0
    strat_c, strat_d = Y.make_strategy(reg_c), Y.make_strategy(reg_d)
    for p in Y.GRID:
        tc = C.run_trades(clean, strat_c, p, C.FillConfig())
        td = C.run_trades(dirty_ds, strat_d, p, C.FillConfig())
        assert sorted(tc.loc[tc["t_dec"] <= T, ["mint", "t_dec", "tag"]].itertuples(index=False)) == \
            sorted(td.loc[td["t_dec"] <= T, ["mint", "t_dec", "tag"]].itertuples(index=False))


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Registry answers on real census-TRAIN-third coins of repeat creators are unchanged when every coin's data
    after T is garbage (debug third: no outcome is printed)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    cr = full.coins["creator"].astype(object)
    rep = cr[cr.notna() & (cr != "")].value_counts()
    pick = list(full.coins.loc[full.coins["creator"].isin(rep[rep >= 2].index), "mint"])
    if len(pick) < 6:
        pytest.skip("too few repeat creators in this snapshot")
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    rows = Y.deployer_rows_from_frames(sub[0], cen, -math.inf, math.inf)
    reg_c = Y.build_registry([clean], rows)
    rng = np.random.default_rng(5)
    gs = sorted(clean.coins["g_ts"])
    n_checked = 0
    for T in (gs[len(gs) // 3] + 3000.0, gs[2 * len(gs) // 3] + 2000.0):
        dirty = sub
        for m in clean.mints:
            dirty = _garble(dirty, m, T - C.DECISION_LAG_S, rng)
        dds = C.Dataset.from_frames("final_train", *dirty, census=cen, sol=SOL)
        keep = [m for m in clean.mints if m in dds.mints]
        reg_d = Y.build_registry([dds], rows)
        a = {k: v for k, v in _decision_states(clean, reg_c, T).items() if k[0] in keep}
        d = {k: v for k, v in _decision_states(dds, reg_d, T).items() if k[0] in keep}
        assert a == d
        n_checked += len(a)
    assert n_checked > 0


# =========================================================================== persistence gate, clusters, veto


def _obs(n, rho_sign=1.0, n_cl=None, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, n)
    y = rho_sign * x + rng.normal(0, 0.3, n)
    n_cl = n_cl or n
    return pd.DataFrame({"mint": [f"m{i}" for i in range(n)], "score": x, "label": y, "t_e": 1e9 + 1e5 + np.arange(n),
                         "creator": [f"c{i % n_cl}" for i in range(n)]}), {f"m{i}": f"c{i % n_cl}" for i in range(n)}


@pytest.mark.parametrize("n,sign,n_cl,want", [(100, 1.0, None, "PASS"), (100, -1.0, None, "KILL"),
                                              (40, 1.0, None, "UNDERPOWERED"), (100, 1.0, 10, "UNDERPOWERED")])
def test_persistence_gate_decisions(n, sign, n_cl, want):
    obs, cl = _obs(n, sign, n_cl)
    pg = Y.persistence_gate(obs, cl, first_g=1e9, B=300)
    assert pg["decision"] == want
    if want == "PASS":
        assert pg["rho"] > 0.5 and pg["rho_ci90_cluster"][0] > 0 and pg["n_warmup"] == 0


def test_persistence_gate_hidden_on_debug():
    obs, cl = _obs(100)
    pg = Y.persistence_gate(obs, cl, first_g=None, hide=True)
    assert pg["decision"].startswith("HIDDEN") and "rho" not in pg and "diagnostics" not in pg
    assert pg["n_obs"] == 100


def test_cluster_map_links_creator_and_symbol():
    coins = [{"g": T0, "creator": "A", "symbol": "foo"}, {"g": T0 + 60, "creator": "A", "symbol": "bar"},
             {"g": T0 + 120, "creator": "B", "symbol": "FOO"}, {"g": T0 + 180, "creator": "C", "symbol": "baz"},
             {"g": T0 + 240, "creator": None}]
    ds = ds_of(market_frames(coins))
    cl = Y.cluster_map([ds])
    assert cl[mint_of(0)] == cl[mint_of(1)] == cl[mint_of(2)]
    assert len({cl[mint_of(0)], cl[mint_of(3)], cl[mint_of(4)]}) == 3


def _host(n_good, n_bad, good_ret, bad_ret, seed=0):
    rng = np.random.default_rng(seed)
    rows = [{"mint": f"g{i}", "ret_net": good_ret + rng.normal(0, 0.02), "tag": "good"} for i in range(n_good)]
    rows += [{"mint": f"b{i}", "ret_net": bad_ret + rng.normal(0, 0.02), "tag": "bad"} for i in range(n_bad)]
    return pd.DataFrame(rows)


def test_veto_eval():
    v = Y.veto_eval(_host(40, 40, 0.05, -0.30), B=500, hide=False, oos=_host(20, 20, 0.05, -0.30, 1))
    assert v["n_flagged"] == 40 and v["verdict"]["verdict"] == "PASS"
    assert v["flagged_mean"] < v["unflagged_mean"]
    assert Y.veto_eval(_host(10, 5, 0.05, -0.3), B=200, hide=False)["verdict"]["verdict"] == "UNDERPOWERED"
    h = Y.veto_eval(_host(40, 40, 0.05, -0.3), B=200, hide=True)
    assert "verdict" not in h and "flagged_mean" not in h and h["n_flagged"] == 40
    conf = Y.veto_eval(_host(40, 40, 0.05, -0.30), B=500, hide=False, oos_is_self=True)
    assert {c["id"] for c in conf["verdict"]["criteria"]} == {1, 2, 3}


# =========================================================================== decision rules


def _ev(n, cl, mean, w2, pc, ci_lo):
    return {"n": n, "n_clusters": cl, "mean": mean, "mean_without_top2": w2, "placebo": {"mean_diff": pc},
            "clusters": {"ci90_cluster": (ci_lo, ci_lo + 0.1), "mean_without_largest": mean}}


def test_decide_train_rule():
    ev = {Y.config_key(p): _ev(40, 12, 0.05, 0.03, 0.02, 0.01) for p in Y.GRID_GOOD}
    ev[Y.config_key(Y.make_params("good", "T60", 0.10))] = _ev(40, 12, 0.04, 0.03, 0.02, 0.02)
    d = Y.decide_train(ev)
    assert d["verdict"] == "SHORTLISTED" and d["chosen"] == "good|th0.1|T60"
    assert d["shortlist"][Y.HYP][0] == Y.make_params("good", "T60", 0.10)
    assert d["shortlist"][Y.HYP_HOST][0] == Y.make_params("host", "T60")
    tie = Y.decide_train({Y.config_key(p): _ev(40, 12, 0.05, 0.03, 0.02, 0.01) for p in Y.GRID_GOOD})
    assert tie["chosen"] == "good|th0.1|T30"                             # ties: theta 0.10, then T30
    bad = {Y.config_key(p): _ev(40, 12, 0.05, 0.03, -0.01, 0.01) for p in Y.GRID_GOOD}
    assert Y.decide_train(bad)["verdict"] == "NO_CONFIG"
    small = {Y.config_key(p): _ev(29, 12, 0.05, 0.03, 0.02, 0.01) for p in Y.GRID_GOOD}
    assert Y.decide_train(small)["verdict"] == "UNDERPOWERED_TRAIN"
    few_cl = {Y.config_key(p): _ev(40, 9, 0.05, 0.03, 0.02, 0.01) for p in Y.GRID_GOOD}
    assert Y.decide_train(few_cl)["verdict"] == "UNDERPOWERED_TRAIN"


def test_decide_val_confirm_and_combine():
    assert Y.decide_val({"n": 4, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "UNDERPOWERED_VAL"
    assert Y.decide_val({"n": 20, "mean": -0.1, "mean_without_top2": 0.1})["verdict"] == "FAIL_VAL"
    assert Y.decide_val({"n": 10, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "SELECTED_UNDERPOWERED"
    assert Y.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "SELECTED"
    assert Y.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 9, "mean": 1}}})[0] is False
    assert Y.confirm_allowed({"verdict": {}, "configs": {"candidate": {"n": 9, "mean": -0.1}}})[0] is False
    assert Y.confirm_allowed({"verdict": {}, "configs": {"candidate": {"n": 3, "mean": -0.1}}})[0] is True

    def base(passes, rej=()):
        return {"auto_rejections": list(rej), "criteria": [{"id": i + 1, "pass": v} for i, v in enumerate(passes)]}
    ok = [True] * 10
    ex = Y.y1_extras(_ev(70, 12, 0.05, 0.03, 0.1, 0.01))
    assert Y.combine_verdict(base(ok), ex) == "PASS"
    assert Y.combine_verdict(base(ok, ["x"]), ex) == "REJECTED"
    assert Y.combine_verdict(base([False] + ok[1:]), ex) == "UNDERPOWERED"
    assert Y.combine_verdict(base(ok[:4] + [False] + ok[5:]), ex) == "FAIL"
    assert Y.combine_verdict(base(ok[:9] + [False]), ex) == "INCOMPLETE"          # > 10 % censored
    assert Y.combine_verdict(base(ok), Y.y1_extras(_ev(70, 9, 0.05, 0.03, 0.1, 0.01))) == "UNDERPOWERED"
    assert Y.combine_verdict(base(ok), Y.y1_extras(_ev(70, 12, 0.05, 0.03, 0.1, -0.01))) == "FAIL"


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Y1", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Y1 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, history=None, **kw):
    return Y.run_stage(stage, out_dir=d.out, ds=ds, history=history, flow=d.flow, ledger_path=d.ledger,
                       shortlist_path=d.sl, B=200, n_placebo=3, env=env or {},
                       _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Y.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def mk(split, t0, n_good, n_bad, per, prefix, seed, drift=0.01):
    return ds_of(market_frames(creators_market(t0, n_good, n_bad, per, prefix=prefix, drift=drift), seed=seed), split)


def test_debug_stage_hides_returns(st):
    ds = mk("train", T0, 8, 8, 3, "D", 9)
    ds.split, ds.debug_only = "final_train", True
    doc = Y.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG" and doc["persistence"]["decision"].startswith("HIDDEN")
    assert "rho" not in doc["persistence"]
    for e in doc["configs"].values():
        assert "mean" not in e and "ci90" not in e and "placebo" not in e and "reasons" not in e
        assert "stress" not in e and "portfolio" not in e and e["returns"].startswith("hidden")
    for v in doc["veto"].values():
        assert "verdict" not in v and "flagged_mean" not in v
    assert doc["event_counts"]["eligible_in_window"] == 32
    assert doc["configs"]["host|T30"]["n"] == 32
    led = json.loads(st.ledger.read_text())
    assert led["runs"] and all(r["debug"] for r in led["runs"]) and not led["configs"]
    assert (st.out / "debug.md").exists() and not list(st.out.glob("*_trades.csv"))


def test_train_kill_stops_y1(st):
    # records do NOT persist: a deployer's coins alternate up / down, so the record predicts the opposite
    coins = []
    for ci in range(30):
        for kk in range(4):
            coins.append({"g": T0 + ci * 300 + kk * 7200, "creator": f"K{ci}", "symbol": f"KS{ci}",
                          "drift": 0.01 if (kk + ci) % 2 == 0 else -0.01})
    doc = _run("train", st, ds_of(market_frames(coins, seed=3)))
    assert doc["persistence"]["decision"] == "KILL" and doc["decision"]["verdict"] == "KILLED_PERSISTENCE"
    assert "configs" not in doc and doc["overall"].startswith("KILLED")
    assert [r["hypothesis"] for r in json.loads(st.ledger.read_text())["runs"]] == ["Y1-persist"]
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(Y.Y1Refused, match="persistence"):
            _check(stage, st, env=ENV_ALL)
    with pytest.raises(Y.Y1Refused, match="final"):
        _run("train", st, ds_of(market_frames(coins, seed=3)))


def test_underpowered_persistence_halts(st):
    doc = _run("train", st, mk("train", T0, 5, 5, 3, "U", 4))           # 20 observations < 60
    assert doc["decision"]["verdict"] == "UNDERPOWERED_PERSISTENCE"
    with pytest.raises(Y.Y1Refused, match="UNDERPOWERED_PERSISTENCE"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = mk("train", T0, 15, 15, 4, "A", 1)
    with pytest.raises(Y.Y1Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Y1.json").exists()
    with pytest.raises(Y.Y1Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    with pytest.raises(Y.Y1Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: persistence PASS (records persist exactly), grid, shortlists
    ds_tr = mk("train", T0, 15, 15, 4, "A", 1)
    tr = _run("train", st, ds_tr)
    assert tr["persistence"]["decision"] == "PASS" and tr["persistence"]["n_obs"] == 90
    assert set(tr["configs"]) == {Y.config_key(p) for p in Y.GRID}
    assert tr["configs"]["host|T30"]["tags"] == {"good": 45, "bad": 45}
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert set(tr["veto"]) == {"host|T30", "host|T60"}
    assert tr["veto"]["host|T30"]["verdict"]["verdict"] in ("PASS", "INCOMPLETE")   # no out-of-sample on TRAIN
    led = json.loads(st.ledger.read_text())
    hyps = [v["hypothesis"] for v in led["configs"].values()]
    assert sorted(hyps) == sorted(["Y1"] * 4 + ["Y1-host"] * 2 + ["Y1-veto"] * 2 + ["Y1-persist"])
    assert led["n_trials_total"] == 2575 + 9
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Y.Y1Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Y1 test prereg\n")
    with pytest.raises(Y.Y1Refused, match="no VAL result"):
        _check("test", st, env=ENV_ALL)
    with pytest.raises(Y.Y1Refused, match="before TEST"):
        _check("final", st, env=ENV_ALL)
    with pytest.raises(Y.Y1Refused, match="before TEST"):
        _check("confirm", st, env=ENV_ALL)
    sl = (st.sl / "Y1-host.json").read_text()
    (st.sl / "Y1-host.json").unlink()
    with pytest.raises(Y.Y1Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Y1-host.json").write_text(sl)
    # ---- VAL: the same deployers continue; their first VAL coins are scored by TRAIN records (history)
    ds_va = mk("val", C.utc_ts("2026-10-05 02:00"), 15, 15, 2, "A", 2)   # same deployers, new mints
    va = _run("val", st, ds_va, history=[ds_tr])
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"candidate", "host"}
    assert va["configs"]["candidate"]["n"] == 30                          # 15 good deployers x 2 VAL coins
    assert va["history"]["splits"] == ["val", "train"]
    with pytest.raises(Y.Y1Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_te = mk("test", C.utc_ts("2026-10-06 13:00"), 5, 5, 3, "T", 3)
    with pytest.raises(Y.Y1Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_te, history=[ds_tr, ds_va])
    te = _run("test", st, ds_te, env=ENV_ALL, history=[ds_tr, ds_va])
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert {c["id"] for c in te["verdict"]["y1_extras"]} == {"Y1.1", "Y1.2", "Y1.3"}
    assert te["veto"]["n_host"] == 66 and te["veto"]["n_oos"] == 20 and "verdict" in te["veto"]   # VAL in-sample, TEST oos
    with pytest.raises(Y.Y1Refused, match="already ran"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Y.Y1Refused, match="one test run"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] == "test"} == {"Y1", "Y1-host"}
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, mk("confirm", C.utc_ts("2026-09-20 00:00"), 35, 35, 3, "C", 4), env=ENV_ALL)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["veto"]["verdict"]["verdict"] == "PASS"
    assert co["overall"] == "PENDING FINAL"
    # ---- FINAL
    fi = _run("final", st, mk("final", C.FINAL_LO + 3600, 6, 6, 3, "F", 5), env=ENV_ALL)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(Y.Y1Refused, match="already ran"):
        _check("final", st, env=ENV_ALL)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Y.Y1Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Y.Y1Refused, match="pre-register"):
        _check("train", st)


def test_history_bounds_never_reach_a_later_split():
    cen = C.Census.empty()
    lo, hi = Y._hist_bounds("train", cen)
    assert lo == C.SPLIT_BOUNDS["train"][0] and hi == C.SPLIT_BOUNDS["train"][1]
    lo, hi = Y._hist_bounds("val", cen)
    assert lo == C.SPLIT_BOUNDS["train"][0] and hi == C.SPLIT_BOUNDS["val"][1]
    lo, hi = Y._hist_bounds("confirm", cen)
    assert lo == C.SPLIT_BOUNDS["confirm"][0] and hi == C.SPLIT_BOUNDS["confirm"][1]
    lo, hi = Y._hist_bounds("debug", cen)
    assert lo == C.FINAL_LO and hi == cen.train_hi + 1

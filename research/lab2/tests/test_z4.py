"""Tests for research/lab2/z4.py: the theme tokenizer, the cross-coin theme registry (members, causal records, heat),
the strategy's single decision, no lookahead (synthetic and real census bars: garbage after T and renamed / new
graduates after T change no registry answer and no decision at tau <= T), the exhaustion veto, the pre-registered
decision rules of both branches and every stage refusal, end to end for a momentum market and an exhaustion market."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import z4 as Z
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
ENV_ALL = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
H3, H12 = 3 * 3600.0, 12 * 3600.0


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
    symbol, phases [(start minute, per-minute log drift)] or drift, quiet_from (minute: volume dries up), mayhem}.
    Prices move along X * y = k with a bar in every minute."""
    g0, c0, _ = make_frames(n=1, seed=seed, slow_every=0, agent_every=0)
    tg, tc = g0.iloc[0].to_dict(), c0.iloc[0].to_dict()
    grads, cs, bars = [], [], []
    k = X0 * Y0
    for i, s in enumerate(coins):
        mint, pool = f"Z{i:04d}{seed}pump", f"ZP{i:04d}{seed}"
        g = int(s["g"])
        cr = s.get("creator")
        r = dict(tg)
        r.update(mint=mint, pool=pool, g_ts=g, g_slot=10_000 + i, pool_ts=g + 2, pool_slot=10_001 + i)
        if cr is None:
            r.update(has_create=0, c_ts=0, c_slot=0, creator="", create_user="", symbol="", name="", vsol0=0.0,
                     grad_delay_s=float(g))
        else:
            dl = int(s.get("delay", 3))
            r.update(has_create=1, c_ts=g - dl, c_slot=9_000 + i, creator=cr, create_user=cr,
                     symbol=s.get("symbol", f"S{i}"), name=s.get("name", f"Cn{letters(i)}"), grad_delay_s=float(dl))
        if s.get("mayhem"):
            r.update(is_mayhem=1)
        grads.append(r)
        cc = dict(tc)
        cc.update(mint=mint, pool=pool, g_ts=g)
        cs.append(cc)
        phases = sorted(s.get("phases") or [(0, float(s.get("drift", 0.0)))])
        m0 = g // 60 * 60
        lp = math.log(X0 / Y0)
        for j in range(N_MIN):
            lp0 = lp
            lp += [d for st, d in phases if st <= j][-1]
            p0, p1 = math.exp(lp0), math.exp(lp)
            X1, y1 = math.sqrt(k * p1), math.sqrt(k / p1)
            quiet = s.get("quiet_from") is not None and j >= s["quiet_from"]
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
    return f"Z{i:04d}{seed}pump"


def theme_market(t0: int, n_hot: int, n_cold: int, per: int = 5, prefix: str = "A", mode: str = "mom",
                 gap: int = 3600, stagger: int = 137, d: float = 0.01) -> list[dict]:
    """Themes of ``per`` members ``gap`` seconds apart, every member from its own creator. ``mom``: a hot theme's
    members rise all along (records > +25 %, and the next member rises after g + 30); cold ones fall. ``exh``: the
    record window (minutes 7-37) shows the theme's sign, then from minute 38 every member reverses (hot themes'
    new members fall: exhaustion)."""
    out = []
    for ti in range(n_hot + n_cold):
        s = 1.0 if ti < n_hot else -1.0
        word = f"Zq{prefix.lower()}{letters(ti)}"            # never an English (stop) word
        for kk in range(per):
            ph = [(0, s * d)] if mode == "mom" else [(0, s * d), (38, -s * d)]
            out.append({"g": t0 + ti * stagger + kk * gap, "creator": f"{prefix}CR{ti}_{kk}",
                        "name": f"{word} Cn{prefix.lower()}{letters(ti * per + kk)}", "symbol": f"S{prefix}{ti}x{kk}",
                        "phases": ph})
    return out


def dec_t(ds: C.Dataset, m: str) -> float:
    cd = ds.coin(m)
    return Z.grid_time_from(cd, cd.g + Z.DEC_AGE_S)


def registry(ds: C.Dataset, frames=None, history=()) -> Z.Registry:
    rows = Z.structure_rows_from_frames(frames[0], C.Census.empty(), -math.inf, math.inf) if frames is not None else None
    return Z.build_registry([ds, *history], rows)


# =========================================================================== grid and constants


def test_grid_is_preregistered_and_small():
    assert len(Z.GRID_MOM) == 4 and len(Z.GRID_HOST) == 2
    keys = [Z.config_key(p) for p in Z.GRID]
    assert len(set(keys)) == 6 and len({C.params_hash(p) for p in Z.GRID}) == 6
    for p in Z.GRID:
        for k, v in Z.FIXED.items():
            assert p[k] == v
        assert p["lookback_s"] == p["lookback_h"] * 3600.0
    # 4 MOM + 2 HOST + 2 veto evaluations = 8 trials <= 12
    assert len(Z.GRID) + len(Z.GRID_HOST) == 8
    assert Z.HISTORY_SPLITS["train"] == ("train",)            # CONFIRM never feeds a TRAIN decision
    assert "confirm" not in Z.HISTORY_SPLITS["val"] + Z.HISTORY_SPLITS["test"] + Z.HISTORY_SPLITS["final"]
    assert Z.HOT_THETA == min(Z.THETA_GRID) and Z.DEC_AGE_S == 1800.0
    assert Z.FILL.exit_delay_bars == 1 and Z.FILL.entry_fill == "worst" and Z.FILL.exit_fill == "worst"
    with pytest.raises(ValueError):
        Z.make_params("mom", 3, 0.5)
    with pytest.raises(ValueError):
        Z.make_params("host", 6)


# =========================================================================== tokens


@pytest.mark.parametrize("name,symbol,want", [
    ("Claude Cat", "CLAUDE", {"claude", "cat"}),
    ("ClaudeCat", "", {"claudecat", "claude", "cat"}),
    ("GROK4 Heavy", "GROK4", {"grok4", "grok", "heavy"}),
    ("The Official Coin", "SOL", set()),                       # stop words only
    ("Pokémon", None, {"pokemon"}),                            # accents fold
    ("ＣＬＡＵＤＥ", None, {"claude"}),                          # full-width letters fold
    ("🐸 frog 🐸", "$FROG", {"frog"}),                          # emoji and $ separate
    ("AI Dog", "AI", {"dog"}),                                 # ASCII tokens need >= 3 characters
    ("龙虾", "龙虾", {"龙虾"}),                                    # CJK tokens need >= 2 characters
    ("2026 420", "69", set()),                                 # numbers alone are no theme
    ("JSONParser", None, {"jsonparser", "json", "parser"}),
    (None, None, set()), ("", "  ", set()),
])
def test_theme_tokens(name, symbol, want):
    assert Z.theme_tokens(name, symbol) == frozenset(want)


def test_symbol_norm():
    assert Z.symbol_norm("$CLAUDE") == Z.symbol_norm("claude") == "claude"
    assert Z.symbol_norm("") is None and Z.symbol_norm(None) is None and Z.symbol_norm("🐸") is None


# =========================================================================== members, records, heat


def _named_market():
    coins = [{"g": T0, "creator": "P", "name": "Claude One", "drift": 0.01},                 # 0 prior, rises
             {"g": T0 + 600, "creator": "Q", "name": "Claude Two", "drift": -0.01},          # 1 prior, falls
             {"g": T0 + 7200, "creator": "R", "name": "Claude Three", "drift": 0.0},         # 2 the coin decided
             {"g": T0 + 7000, "creator": "R", "name": "Claude Same", "drift": 0.02},         # 3 same creator as 2
             {"g": T0 + 7300, "creator": "S", "name": "Unrelated", "drift": 0.0},            # 4 no shared token
             {"g": T0 + 7400, "creator": None, "drift": 0.0},                                # 5 creation not scanned
             {"g": T0 + 7100, "creator": "M", "name": "Claude Mayhem", "drift": 0.0, "mayhem": True},  # 6 structure only
             {"g": T0 - 4 * 3600, "creator": "O", "name": "Claude Old", "drift": 0.05}]     # 7 outside 3 h, inside 12 h
    fr = market_frames(coins)
    return fr, ds_of(fr)


def test_record_is_the_post_boost_30_minute_mid_change():
    _, ds = _named_market()
    m = mint_of(0)
    p = Z.prior_of(ds, m)
    cd = ds.coin(m)
    assert p.t_ref >= cd.g + Z.REF_AGE_S and p.t_ref - 60 < cd.g + Z.REF_AGE_S
    assert (p.t_ref - C.GRID_OFFSET_S - cd.m0) % 60 == 0 and p.t_end == p.t_ref + Z.H_REC_S
    assert p.ret == pytest.approx(ds.asof(m, p.t_end).price / ds.asof(m, p.t_ref).price - 1)
    assert p.ret == pytest.approx(math.exp(0.01 * 30) - 1, rel=1e-9)


def test_members_exclude_same_creator_other_themes_and_the_future():
    fr, ds = _named_market()
    reg = registry(ds, fr)
    m2 = mint_of(2)
    t = dec_t(ds, m2)
    st3 = reg.state(ds.asof(m2, t), H3)
    p0, p1 = Z.prior_of(ds, mint_of(0)), Z.prior_of(ds, mint_of(1))
    # members in [t - 3 h, g): coins 0, 1 (other creators) and 6 (Mayhem: structure only); not 3 (same creator R),
    # not 7 (older than 3 h), not 4 (no shared token)
    assert st3["status"] == "eligible" and st3["k"] == 3 and st3["key"] == "claude"
    assert st3["n_resolved"] == 2 and st3["heat"] == pytest.approx((p0.ret + p1.ret) / 2)
    st12 = reg.state(ds.asof(m2, t), H12)
    p7 = Z.prior_of(ds, mint_of(7))
    assert st12["k"] == 4 and st12["n_resolved"] == 3
    assert st12["heat"] == pytest.approx((p7.ret + p0.ret + p1.ret) / 3)
    # the structural pool starts with coin 7 (g0 - 4 h): a 12 h lookback is truncated (warm-up), a 3 h one is not
    assert st12["warmup"] is True and st3["warmup"] is False
    # coin 3 (creator R, g0 + 7000 s) sees 0 and 1; never coin 2 or the Mayhem coin 6 (both graduated later)
    st_3 = reg.state(ds.asof(mint_of(3), dec_t(ds, mint_of(3))), H3)
    assert st_3["k"] == 2
    # statuses: no shared token -> solo; NULL creator -> unknown; first coin of a theme -> solo
    assert reg.state(ds.asof(mint_of(4), dec_t(ds, mint_of(4))), H3)["status"] == "solo"
    assert reg.state(ds.asof(mint_of(5), dec_t(ds, mint_of(5))), H3)["status"] == "unknown"
    assert reg.state(ds.asof(mint_of(7), dec_t(ds, mint_of(7))), H12)["status"] == "solo"


def test_pending_until_the_record_resolves():
    coins = [{"g": T0, "creator": "A", "name": "Moo Deng", "drift": 0.01},
             {"g": T0 + 60, "creator": "B", "name": "Moo Two", "drift": 0.0}]
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = registry(ds, fr)
    p0 = Z.prior_of(ds, mint_of(0))
    m1 = mint_of(1)
    assert reg.state(ds.asof(m1, p0.t_end - 60), H3)["status"] == "pending"
    st = reg.state(ds.asof(m1, p0.t_end), H3)
    assert st["status"] == "eligible" and st["heat"] == pytest.approx(p0.ret)


def test_heat_uses_the_three_most_recent_resolved():
    drifts = (0.03, 0.01, 0.0, -0.01, 0.0)
    coins = [{"g": T0 + 1800 * i, "creator": f"C{i}", "name": "Gemini Thing", "drift": dd}
             for i, dd in enumerate(drifts)]
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = registry(ds, fr)
    rets = [Z.prior_of(ds, mint_of(i)).ret for i in range(4)]
    st = reg.state(ds.asof(mint_of(4), dec_t(ds, mint_of(4))), H3)
    assert st["n_resolved"] == 4 and st["heat"] == pytest.approx(np.mean(rets[1:]))


def test_crowding_and_exact_clone():
    coins = [{"g": T0 + 600 * i, "creator": f"K{i}", "name": f"Oil {letters(i)}xx", "symbol": "OIL" if i == 0 else f"O{i}",
              "drift": 0.0} for i in range(4)]
    coins.append({"g": T0 + 6000, "creator": "K9", "name": "Oil Last", "symbol": "$oil", "drift": 0.0})
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = registry(ds, fr)
    st = reg.state(ds.asof(mint_of(4), dec_t(ds, mint_of(4))), H3)
    assert st["k"] == 4 and st["exact_clone"] is True and Z.tag_of(st).endswith("crowd")


def test_market_heat_is_the_same_construction_without_the_theme_link():
    """review Z4-1: heat is a theme-filtered sample of recent graduates' outcomes, so MOM is also compared with the
    3 most recent resolved NON-member graduates (g_p in [t - N, g), known creator != own, t_end <= t) at the same t."""
    coins = [{"g": T0, "creator": "P", "name": "Claude One", "drift": 0.01},          # 0 member
             {"g": T0 + 3300, "creator": "Q", "name": "Claude Two", "drift": -0.01},  # 1 member, most recent resolved
             {"g": T0 + 7200, "creator": "R", "name": "Claude Three", "drift": 0.0},  # 2 the coin decided
             {"g": T0 + 1200, "creator": "U", "name": "Banana", "drift": 0.02},       # 3 non-member
             {"g": T0 + 1800, "creator": "V", "name": "Mango", "drift": 0.0},         # 4 non-member
             {"g": T0 + 2400, "creator": "W", "name": "Kiwi", "drift": 0.01},         # 5 non-member
             {"g": T0 + 3000, "creator": "R", "name": "Apple", "drift": 0.03},        # 6 own creator: out
             {"g": T0 + 3600, "creator": None, "drift": 0.03},                        # 7 creator unknown: out
             {"g": T0 + 6900, "creator": "X", "name": "Pear", "drift": 0.03},         # 8 unresolved at t: out
             {"g": T0 + 300, "creator": "Y", "name": "Grape", "drift": 0.03},         # 9 older than the 3 kept
             {"g": T0 + 7300, "creator": "Z", "name": "Lime", "drift": 0.03}]         # 10 graduated after g: out
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = registry(ds, fr)
    snap = ds.asof(mint_of(2), dec_t(ds, mint_of(2)))
    assert reg.state(snap, H3)["status"] == "eligible"
    ms = reg.market_state(snap, H3)
    r = {i: Z.prior_of(ds, mint_of(i)).ret for i in (3, 4, 5)}
    assert ms["n"] == 3 and ms["market_heat"] == pytest.approx(np.mean(list(r.values())))      # ~ +39 %
    assert reg.market_state(ds.asof(mint_of(7), dec_t(ds, mint_of(7))), H3)["market_heat"] is None   # own creator NULL
    ok25 = Z.market_heat_ok(reg, H3, 0.25)
    assert ok25(snap) and not Z.market_heat_ok(reg, H3, 1.0)(snap)
    assert not ok25(ds.asof(mint_of(4), dec_t(ds, mint_of(4))))                 # not an eligible theme member
    ctl = Z.placebo_controls(reg, Z.make_params("mom", 3, 0.25))
    assert set(ctl) == {"unmatched", "market_heat"} and ctl["market_heat"]["strata"] is None
    assert set(Z.placebo_controls(reg, Z.make_params("host", 3))) == {"unmatched"}
    assert "market-heat" in Z.FIXED["placebo"]


# =========================================================================== strategy


def test_strategy_single_decision():
    coins = [{"g": T0, "creator": "A", "name": "Hot Thing", "drift": 0.02},       # 0 hot record (+82 %)
             {"g": T0 + 3600, "creator": "B", "name": "Hot Again", "drift": 0.0},  # 1 hot member
             {"g": T0, "creator": "C", "name": "Cold Thing", "drift": -0.01},     # 2 cold record
             {"g": T0 + 3600, "creator": "D", "name": "Cold Again", "drift": 0.0},  # 3 cold member
             {"g": T0 + 3600, "creator": "E", "name": "Hot Quiet", "drift": 0.0, "quiet_from": 10},  # 4 not alive
             {"g": T0 + 3600, "creator": "F", "name": "Lonely", "drift": 0.0}]    # 5 solo
    fr = market_frames(coins)
    ds = ds_of(fr)
    strat = Z.make_strategy(registry(ds, fr))
    mom25, mom100 = Z.make_params("mom", 3, 0.25), Z.make_params("mom", 3, 1.0)
    host = Z.make_params("host", 3)
    at = lambda i, dt=0.0: ds.asof(mint_of(i), dec_t(ds, mint_of(i)) + dt)     # noqa: E731
    assert strat(at(1, -60), mom25, None) is None                              # before g + 30 min
    e = strat(at(1), mom25, None)
    assert isinstance(e, C.Enter) and e.tag == "hot|few" and e.exits == Z.EXITS
    assert e.exits.stop_pct == 0.5 and e.exits.max_hold_s == 3600 and e.exits.exit_by_age_s == Z.EXIT_BY_AGE_S
    assert strat(at(1), mom100, None) is C.SKIP                                # record +82 % < +100 %
    assert strat(at(3), mom25, None) is C.SKIP
    eh = strat(at(3), host, None)
    assert isinstance(eh, C.Enter) and eh.tag == "cold|few"
    assert strat(at(4), host, None) is C.SKIP                                  # not alive
    assert strat(at(5), host, None) is C.SKIP                                  # solo
    pv = C.PositionView(mint=mint_of(1), t_dec=0.0, t_in=0.0, entry_price=1.0, tokens=1.0, sol_in=0.2, peak=1.0,
                        bars_held=1, unrealized=0.0, exits=Z.EXITS, state={}, is_placebo=True)
    assert strat(at(1, 600), mom25, pv) is None                                # exits are mechanical only


def test_backtest_one_decision_and_member_placebo():
    fr = market_frames(theme_market(T0, 6, 6, per=4))
    ds = ds_of(fr)
    reg = registry(ds, fr)
    p = Z.make_params("mom", 3, 0.25)
    res = C.backtest(Z.make_strategy(reg), "train", p, hypothesis="Z4-unit", ds=ds, cfg=Z.FILL, n_placebo=5,
                     placebo_eligible=Z.placebo_eligible, placebo_strata=Z.make_stratum(reg, p["lookback_s"]),
                     ledger_path=None, declarations=Z.DECL)
    t = res.trades
    assert len(t) == 18 and set(t["tag"]) == {"hot|few"}                       # 6 hot themes x 3 later members
    assert (t["age_dec_s"] >= Z.DEC_AGE_S).all() and (t["age_dec_s"] < Z.DEC_AGE_S + 60).all()
    assert (t["reason"] == "time").all() and ((t["t_out"] - t["t_in"]) >= 3600).all()
    stratum = Z.make_stratum(reg, p["lookback_s"])
    for r in res.placebo.itertuples(index=False):                             # every draw is an eligible member
        assert stratum(ds.asof(r.mint, r.t_dec)) == "eligible"
    assert len(res.placebo) > 0 and not C.auto_rejections(res)
    info = Z.trade_info(t, ds, reg, p["lookback_s"])
    assert len(info) == len(t) and info["key"].nunique() == 6 and (info["heat"] >= 0.25).all()


# =========================================================================== no lookahead


def _decision_states(ds, reg, T):
    out = {}
    for m in ds.mints:
        t = dec_t(ds, m)
        if t > T:
            continue
        for n in (H3, H12):
            st = reg.state(ds.asof(m, t), n)
            mk_ = reg.market_state(ds.asof(m, t), n)
            out[(m, n)] = (st["status"], st.get("k"), st.get("key"), st.get("n_resolved"),
                           None if st.get("heat") is None else round(st["heat"], 12),
                           mk_["n"], None if mk_["market_heat"] is None else round(mk_["market_heat"], 12))
    return out


@pytest.mark.parametrize("seed", range(3))
def test_registry_and_decisions_unchanged_by_future_garbage(seed):
    rng = np.random.default_rng(seed)
    coins = theme_market(T0, 3, 3, per=5, gap=1500, stagger=400)
    for c in coins:
        c["phases"] = [(0, float(rng.normal(0, 0.01)))]
    frames = market_frames(coins, seed=seed)
    clean = ds_of(frames)
    reg_c = registry(clean, frames)
    T = T0 + int(rng.integers(5000, 7000))
    dirty = frames
    for m in clean.mints:
        dirty = _garble(dirty, m, T - C.DECISION_LAG_S, rng)
    g2 = dirty[0].copy()
    fut = g2["g_ts"] > T - C.DECISION_LAG_S                 # future graduates: their structure is future too
    g2.loc[fut, "name"] = "Zqaa Zqab Zqac Zqad Zqae Zqaf"   # renamed into every theme -- in the future
    g2.loc[fut, "creator"] = "ZZZ"
    dirty = (g2, dirty[1], dirty[2])
    dirty_ds = ds_of(dirty)
    assert set(dirty_ds.mints) == set(clean.mints)
    reg_d = registry(dirty_ds, dirty)
    a, d = _decision_states(clean, reg_c, T), _decision_states(dirty_ds, reg_d, T)
    assert a == d and sum(1 for v in a.values() if v[0] == "eligible") > 0
    strat_c, strat_d = Z.make_strategy(reg_c), Z.make_strategy(reg_d)
    for p in Z.GRID:
        tc = C.run_trades(clean, strat_c, p, Z.FILL)
        td = C.run_trades(dirty_ds, strat_d, p, Z.FILL)
        assert sorted(tc.loc[tc["t_dec"] <= T, ["mint", "t_dec", "tag"]].itertuples(index=False)) == \
            sorted(td.loc[td["t_dec"] <= T, ["mint", "t_dec", "tag"]].itertuples(index=False))


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Registry answers on real census-TRAIN-third coins are unchanged when every coin's data after T is garbage
    (debug third: no outcome is printed)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    pick = list(full.mints[: min(160, len(full))])
    if len(pick) < 20:
        pytest.skip("too few census coins in this snapshot")
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    rows = Z.structure_rows_from_frames(sub[0], cen, -math.inf, math.inf)
    reg_c = Z.build_registry([clean], rows)
    rng = np.random.default_rng(5)
    gs = sorted(clean.coins["g_ts"])
    n_checked = 0
    for T in (gs[len(gs) // 2] + 2500.0, gs[-1] + 1000.0):
        dirty = sub
        for m in clean.mints:
            dirty = _garble(dirty, m, T - C.DECISION_LAG_S, rng)
        dds = C.Dataset.from_frames("final_train", *dirty, census=cen, sol=SOL)
        keep = [m for m in clean.mints if m in dds.mints]
        reg_d = Z.build_registry([dds], rows)
        a = {k: v for k, v in _decision_states(clean, reg_c, T).items() if k[0] in keep}
        d = {k: v for k, v in _decision_states(dds, reg_d, T).items() if k[0] in keep}
        assert a == d
        n_checked += len(a)
    assert n_checked > 0


# =========================================================================== veto and decision rules


def _host(n_hot, n_cold, hot_ret, cold_ret, seed=0):
    rng = np.random.default_rng(seed)
    rows = [{"mint": f"h{i}", "ret_net": hot_ret + rng.normal(0, 0.02), "tag": "hot|crowd" if i % 2 else "hot|few"}
            for i in range(n_hot)]
    rows += [{"mint": f"c{i}", "ret_net": cold_ret + rng.normal(0, 0.02), "tag": "cold|few"} for i in range(n_cold)]
    return pd.DataFrame(rows)


def test_veto_eval():
    v = Z.veto_eval(_host(40, 40, -0.30, 0.05), B=500, hide=False, oos=_host(20, 20, -0.30, 0.05, 1))
    assert v["n_flagged"] == 40 and v["verdict"]["verdict"] == "PASS"
    assert v["flagged_mean"] < v["unflagged_mean"] and set(v["by_crowding"]) == {"few", "crowd"}
    assert Z.veto_eval(_host(10, 5, -0.3, 0.05), B=200, hide=False)["verdict"]["verdict"] == "UNDERPOWERED"
    h = Z.veto_eval(_host(40, 40, -0.3, 0.05), B=200, hide=True)
    assert "verdict" not in h and "flagged_mean" not in h and h["n_flagged"] == 40
    conf = Z.veto_eval(_host(40, 40, -0.30, 0.05), B=500, hide=False, oos_is_self=True)
    assert {c["id"] for c in conf["verdict"]["criteria"]} == {1, 2, 3}
    mom_like = Z.veto_eval(_host(40, 40, 0.30, 0.05), B=500, hide=False)     # momentum: flagged better
    assert mom_like["verdict"]["verdict"] == "FAIL"


def _ev(n, keys, mean, w2, pc, ci_lo, npk=6, wbk=None):
    return {"n": n, "n_keys": keys, "mean": mean, "mean_without_top2": w2, "placebo": {"mean_diff": pc},
            "keys": {"ci90_key": (ci_lo, ci_lo + 0.1), "mean_without_best_key": mean if wbk is None else wbk,
                     "n_profitable_keys": npk}}


def _ve(nf, nu, diff, ci_hi):
    crit = [{"id": 1, "pass": bool(diff <= -0.10 and ci_hi < 0), "value": diff, "ci95": (diff - 0.1, ci_hi)}]
    return {"n_flagged": nf, "n_unflagged": nu, "flagged_mean": -0.2, "unflagged_mean": -0.2 - diff,
            "verdict": {"verdict": "INCOMPLETE", "criteria": crit}}


def _vetoes(**kw):
    out = {Z.config_key(Z.make_params("host", n)): _ve(10, 10, 0.0, 0.1) for n in Z.N_GRID_H}
    for n, v in kw.items():
        out[Z.config_key(Z.make_params("host", int(n[1:])))] = v
    return out


def test_decide_train_both_branches():
    ev = {Z.config_key(p): _ev(40, 12, 0.05, 0.03, 0.02, 0.01) for p in Z.GRID_MOM}
    ev[Z.config_key(Z.make_params("mom", 12, 1.0))] = _ev(40, 12, 0.04, 0.03, 0.02, 0.02)
    d = Z.decide_train(ev, _vetoes())
    assert d["verdict"] == "SHORTLISTED" and d["branches"] == ["mom"] and d["mom"]["chosen"] == "mom|N12h|th1"
    assert d["shortlist"][Z.HYP] == [Z.make_params("mom", 12, 1.0)]
    assert d["shortlist"][Z.HYP_HOST] == [Z.make_params("host", 12)]
    tie = Z.decide_train({Z.config_key(p): _ev(40, 12, 0.05, 0.03, 0.02, 0.01) for p in Z.GRID_MOM}, _vetoes())
    assert tie["mom"]["chosen"] == "mom|N3h|th1"                                  # ties: theta 1.0, then N = 3 h
    # EXH only: MOM fails its placebo bar; the N = 12 h veto is clearer (lower CI upper bound)
    bad = {Z.config_key(p): _ev(40, 12, 0.05, 0.03, -0.01, 0.01) for p in Z.GRID_MOM}
    d2 = Z.decide_train(bad, _vetoes(N3=_ve(40, 40, -0.15, -0.01), N12=_ve(40, 40, -0.2, -0.05)))
    assert d2["branches"] == ["exh"] and d2["exh"]["lookback_h"] == 12 and d2["mom"] is None
    assert d2["shortlist"][Z.HYP] == [] and d2["shortlist"][Z.HYP_HOST] == [Z.make_params("host", 12)]
    # both branches, different N: two host configs
    d3 = Z.decide_train(ev, _vetoes(N3=_ve(40, 40, -0.15, -0.01)))
    assert d3["branches"] == ["mom", "exh"]
    assert d3["shortlist"][Z.HYP_HOST] == [Z.make_params("host", 12), Z.make_params("host", 3)]
    # nothing
    assert Z.decide_train(bad, _vetoes())["verdict"] == "NO_CONFIG"
    small = {Z.config_key(p): _ev(29, 12, 0.05, 0.03, 0.02, 0.01) for p in Z.GRID_MOM}
    assert Z.decide_train(small, _vetoes())["verdict"] == "UNDERPOWERED_TRAIN"
    few_keys = {Z.config_key(p): _ev(40, 9, 0.05, 0.03, 0.02, 0.01) for p in Z.GRID_MOM}
    assert Z.decide_train(few_keys, _vetoes())["verdict"] == "UNDERPOWERED_TRAIN"
    assert Z.decide_train(small, _vetoes(N3=_ve(40, 40, -0.05, 0.02)))["verdict"] == "NO_CONFIG"   # powered veto


def test_decide_val_both_branches():
    assert Z.decide_val({"n": 4, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "UNDERPOWERED_VAL"
    assert Z.decide_val({"n": 20, "mean": -0.1, "mean_without_top2": 0.1})["verdict"] == "FAIL_VAL"
    assert Z.decide_val({"n": 10, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "SELECTED_UNDERPOWERED"
    assert Z.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": 0.1})["verdict"] == "SELECTED"
    ve = lambda nf, nu, fm, um, c1=None: {"n_flagged": nf, "n_unflagged": nu, "flagged_mean": fm,   # noqa: E731
                                          "unflagged_mean": um, "verdict": {"criteria": [c1] if c1 else []}}
    assert Z.decide_val_exh(ve(3, 40, -0.3, 0.0))["verdict"] == "UNDERPOWERED_VAL"
    assert Z.decide_val_exh(ve(20, 40, 0.1, 0.0))["verdict"] == "FAIL_VAL"
    assert Z.decide_val_exh(ve(20, 40, -0.1, 0.0))["verdict"] == "SELECTED_UNDERPOWERED"
    assert Z.decide_val_exh(ve(40, 40, -0.3, 0.0, {"id": 1, "pass": True}))["verdict"] == "SELECTED"
    assert Z.decide_val_exh(ve(40, 40, -0.05, 0.0, {"id": 1, "pass": False}))["verdict"] == "FAIL_VAL"


def test_extras_and_combine():
    def base(passes, rej=()):
        return {"auto_rejections": list(rej), "criteria": [{"id": i + 1, "pass": v} for i, v in enumerate(passes)]}
    ok = [True] * 10
    ex = Z.z4_extras(_ev(70, 12, 0.05, 0.03, 0.1, 0.01))
    assert [e["id"] for e in ex] == ["Z4.1", "Z4.2", "Z4.3", "Z4.4"] and all(e["pass"] for e in ex)
    assert Z.combine_verdict(base(ok), ex) == "PASS"
    assert Z.combine_verdict(base(ok, ["x"]), ex) == "REJECTED"
    assert Z.combine_verdict(base([False] + ok[1:]), ex) == "UNDERPOWERED"
    assert Z.combine_verdict(base(ok[:4] + [False] + ok[5:]), ex) == "FAIL"
    assert Z.combine_verdict(base(ok[:9] + [False]), ex) == "INCOMPLETE"          # > 10 % censored
    assert Z.combine_verdict(base(ok), Z.z4_extras(_ev(70, 9, 0.05, 0.03, 0.1, 0.01))) == "UNDERPOWERED"
    assert Z.combine_verdict(base(ok), Z.z4_extras(_ev(70, 12, 0.05, 0.03, 0.1, -0.01))) == "FAIL"
    assert Z.combine_verdict(base(ok), Z.z4_extras(_ev(70, 12, 0.05, 0.03, 0.1, 0.01, wbk=-0.01))) == "FAIL"
    assert Z.combine_verdict(base(ok), Z.z4_extras(_ev(70, 12, 0.05, 0.03, 0.1, 0.01, npk=4))) == "FAIL"


def test_key_stats():
    t = pd.DataFrame({"ret_net": [0.5, 0.4, -0.1, 0.1, 0.2, -0.3], "mint": list("abcdef")})
    ks = Z._key_stats(t, ["k1", "k1", "k2", "k3", "k3", "k4"], B=300)
    assert ks["n_keys"] == 4 and ks["best_key"]["key"] == "k1" and ks["n_profitable_keys"] == 2
    assert ks["mean_without_best_key"] == pytest.approx(np.mean([-0.1, 0.1, 0.2, -0.3]))
    assert ks["ci90_key"] is not None


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Z4", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Z4 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, history=None, **kw):
    return Z.run_stage(stage, out_dir=d.out, ds=ds, history=history, flow=d.flow, ledger_path=d.ledger,
                       shortlist_path=d.sl, B=200, n_placebo=3, env=env or {},
                       _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Z.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def mk(split, t0, n_hot, n_cold, prefix, seed, mode="mom", per=5, stagger=137):
    return ds_of(market_frames(theme_market(t0, n_hot, n_cold, per=per, prefix=prefix, mode=mode, stagger=stagger),
                               seed=seed), split)


def test_debug_stage_hides_returns(st):
    ds = mk("train", T0, 6, 6, "D", 9)
    ds.split, ds.debug_only = "final_train", True
    doc = Z.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        for k in ("mean", "ci90", "placebo", "reasons", "stress", "portfolio", "keys", "diagnostics"):
            assert k not in e
        assert e["returns"].startswith("hidden")
    for v in doc["veto"].values():
        assert "verdict" not in v and "flagged_mean" not in v and "by_crowding" not in v
    ec = doc["event_counts"]["by_N"]["3h"]
    assert ec["host_entries"] == 48 and ec["mom_th0.25_entries"] == 24 and ec["mom_th1_entries"] == 0
    assert doc["configs"]["host|N3h"]["n"] == 48 and doc["configs"]["mom|N3h|th0.25"]["n"] == 24
    led = json.loads(st.ledger.read_text())
    assert led["runs"] and all(r["debug"] for r in led["runs"]) and not led["configs"]
    assert (st.out / "debug.md").exists() and not list(st.out.glob("*_trades.csv"))
    md = (st.out / "debug.md").read_text()
    assert "hidden" in md and "%" not in md.split("## Configs")[1].split("## Decision")[0].replace("% ", "")


def test_provisional_train_never_unlocks_val(st):
    ds = mk("train", T0, 12, 12, "A", 1)
    with pytest.raises(Z.Z4Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert (st.out / "prereg.lock").exists() and not (st.sl / "Z4.json").exists()   # any TRAIN run locks
    with pytest.raises(Z.Z4Refused, match="no TRAIN result"):
        _check("val", st)
    # review Z-ALL-1: the provisional run showed TRAIN returns, so PREREG.md is frozen from it on
    (st.out / "PREREG.md").write_text("# edited after the provisional run\n")
    with pytest.raises(Z.Z4Refused, match="changed"):
        _check("train", st)
    with pytest.raises(Z.Z4Refused, match="changed"):
        _run("train", st, ds, _skip_coverage=False, allow_partial=True)


def test_prelim_without_lock_still_freezes_prereg(st):
    """review Z-ALL-1: a train_prelim.json with no prereg.lock (written before the lock rule) pins its PREREG sha."""
    (st.out / "train_prelim.json").write_text(json.dumps({"stage": "train", "provisional": True,
                                                           "prereg_sha256": "0" * 64}))
    with pytest.raises(Z.Z4Refused, match="changed"):
        _check("train", st)
    (st.out / "train_prelim.json").write_text(json.dumps({"stage": "train", "provisional": True,
                                                           "prereg_sha256": Z._sha(st.out / "PREREG.md")}))
    assert _check("train", st)["prereg_locked"] is True


def test_momentum_pipeline_and_every_refusal(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    with pytest.raises(Z.Z4Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: MOM qualifies (hot themes keep rising), EXH does not (hot is better, not worse)
    ds_tr = mk("train", T0, 12, 12, "A", 1)
    tr = _run("train", st, ds_tr)
    assert set(tr["configs"]) == {Z.config_key(p) for p in Z.GRID}
    assert tr["configs"]["host|N3h"]["tags"] == {"hot|few": 48, "cold|few": 48}
    dec = tr["decision"]
    assert dec["verdict"] == "SHORTLISTED" and dec["branches"] == ["mom"] and dec["mom"]["chosen"] == "mom|N3h|th0.25"
    assert dec["shortlist_written"] and set(tr["veto"]) == {"host|N3h", "host|N12h"}
    assert tr["veto"]["host|N3h"]["verdict"]["verdict"] == "FAIL"
    assert tr["configs"]["mom|N3h|th0.25"]["placebo"]["mean_diff"] > 0.06
    assert "placebo_market_heat" in tr["configs"]["mom|N3h|th0.25"]
    assert "placebo_market_heat" not in tr["configs"]["host|N3h"]
    led = json.loads(st.ledger.read_text())
    hyps = [v["hypothesis"] for v in led["configs"].values()]
    assert sorted(hyps) == sorted(["Z4"] * 4 + ["Z4-host"] * 2 + ["Z4-exh"] * 2)
    assert led["n_trials_total"] == 2575 + 8
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    assert tr["overall"].startswith("MOM: PENDING VAL; EXH: NO VETO")
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Z.Z4Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Z4 test prereg\n")
    with pytest.raises(Z.Z4Refused, match="no VAL result"):
        _check("test", st, env=ENV_ALL)
    with pytest.raises(Z.Z4Refused, match="before TEST"):
        _check("final", st, env=ENV_ALL)
    with pytest.raises(Z.Z4Refused, match="before TEST"):
        _check("confirm", st, env=ENV_ALL)
    sl = (st.sl / "Z4-host.json").read_text()
    (st.sl / "Z4-host.json").unlink()
    with pytest.raises(Z.Z4Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Z4-host.json").write_text(sl)
    with pytest.raises(Z.Z4Refused, match="already ran"):
        _run("train", st, ds_tr)
    # ---- VAL
    ds_va = mk("val", C.utc_ts("2026-10-05 02:00"), 6, 6, "B", 2)
    va = _run("val", st, ds_va, history=[ds_tr])
    assert set(va["configs"]) == {"candidate", "host_3h"} and va["history"]["splits"] == ["val", "train"]
    assert va["decision"]["mom"]["verdict"] == "SELECTED" and va["decision"]["exh"] is None
    assert va["configs"]["candidate"]["n"] == 24
    with pytest.raises(Z.Z4Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    ds_te = mk("test", C.utc_ts("2026-10-06 13:00"), 4, 4, "C", 3)
    with pytest.raises(Z.Z4Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_te, history=[ds_tr, ds_va])
    te = _run("test", st, ds_te, env=ENV_ALL, history=[ds_tr, ds_va])
    assert te["decision"]["mom"]["verdict"] == "UNDERPOWERED"            # < 60 trades: never PASS / FAIL
    assert {c["id"] for c in te["decision"]["mom"]["z4_extras"]} == {"Z4.1", "Z4.2", "Z4.3", "Z4.4"}
    with pytest.raises(Z.Z4Refused, match="already ran"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Z.Z4Refused, match="one test run"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] == "test"} == {"Z4", "Z4-host"}
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, mk("confirm", C.utc_ts("2026-09-20 00:00"), 20, 20, "E", 4, stagger=1200), env=ENV_ALL)
    assert co["decision"]["mom"]["verdict"] == "PASS", co["decision"]["mom"]
    assert co["overall"].startswith("MOM: PENDING FINAL")
    # ---- FINAL
    fi = _run("final", st, mk("final", C.FINAL_LO + 3600, 6, 6, "F", 5), env=ENV_ALL)
    assert fi["decision"]["mom"]["n"] > 0 and fi["decision"]["mom"]["mean_positive"] is True
    assert fi["decision"]["exh"] is None and fi["overall"].startswith("MOM: EDGE")
    with pytest.raises(Z.Z4Refused, match="already ran"):
        _check("final", st, env=ENV_ALL)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_exhaustion_pipeline(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    ds_tr = mk("train", T0, 8, 8, "A", 1, mode="exh")
    tr = _run("train", st, ds_tr)
    dec = tr["decision"]
    assert dec["verdict"] == "SHORTLISTED" and dec["branches"] == ["exh"] and dec["exh"]["lookback_h"] == 3
    assert dec["shortlist"][Z.HYP] == [] and not (st.sl / "Z4.json").exists() and (st.sl / "Z4-host.json").exists()
    assert tr["veto"]["host|N3h"]["flagged_mean"] < tr["veto"]["host|N3h"]["unflagged_mean"] - 0.10
    ds_va = mk("val", C.utc_ts("2026-10-05 02:00"), 8, 8, "B", 2, mode="exh")
    va = _run("val", st, ds_va, history=[ds_tr])
    assert set(va["configs"]) == {"host_3h"} and va["decision"]["mom"] is None
    assert va["decision"]["exh"]["verdict"] == "SELECTED"
    ds_te = mk("test", C.utc_ts("2026-10-06 13:00"), 4, 4, "C", 3, mode="exh")
    te = _run("test", st, ds_te, env=ENV_ALL, history=[ds_tr, ds_va])
    assert te["decision"]["mom"] is None and te["veto"]["n_oos"] == 32
    assert te["decision"]["exh"]["verdict"]["verdict"] == "PASS"         # VAL in sample, TEST out of sample
    co = _run("confirm", st, mk("confirm", C.utc_ts("2026-09-20 00:00"), 8, 8, "E", 4, mode="exh"), env=ENV_ALL)
    assert co["decision"]["exh"]["verdict"]["verdict"] == "PASS" and co["decision"]["mom"] is None
    fi = _run("final", st, mk("final", C.FINAL_LO + 3600, 4, 4, "F", 5, mode="exh"), env=ENV_ALL)
    assert fi["decision"]["exh"]["flagged_worse"] is True and fi["decision"]["mom"] is None
    assert fi["overall"] == "MOM: NO EDGE (did not qualify on TRAIN); EXH: VETO"


def test_dead_branches_refuse_later_stages(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    ds_tr = mk("train", T0, 12, 12, "A", 1)
    _run("train", st, ds_tr)
    # VAL where momentum has turned: the candidate loses -> FAIL_VAL; no live branch for TEST
    ds_va = mk("val", C.utc_ts("2026-10-05 02:00"), 6, 6, "B", 2, mode="exh")
    va = _run("val", st, ds_va, history=[ds_tr])
    assert va["decision"]["mom"]["verdict"] == "FAIL_VAL" and not va["decision"]["proceed"]
    with pytest.raises(Z.Z4Refused, match="no live branch"):
        _check("test", st, env=ENV_ALL)
    assert va["overall"].startswith("MOM: NO EDGE (failed VAL)")


def test_nothing_qualifies_stops_z4(st):
    flat = [{"g": T0 + 900 * i, "creator": f"F{i}", "name": f"Flat {letters(i)}zz", "drift": 0.0} for i in range(20)]
    tr = _run("train", st, ds_of(market_frames(flat, seed=3)))
    assert tr["decision"]["verdict"] == "UNDERPOWERED_TRAIN" and tr["overall"] == "UNDERPOWERED (TRAIN)"
    with pytest.raises(Z.Z4Refused, match="UNDERPOWERED_TRAIN"):
        _check("val", st)


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Z.Z4Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Z.Z4Refused, match="pre-register"):
        _check("train", st)


def test_history_bounds_never_reach_a_later_split():
    cen = C.Census.empty()
    lo, hi = Z._hist_bounds("train", cen)
    assert lo == C.SPLIT_BOUNDS["train"][0] and hi == C.SPLIT_BOUNDS["train"][1]
    lo, hi = Z._hist_bounds("val", cen)
    assert lo == C.SPLIT_BOUNDS["train"][0] and hi == C.SPLIT_BOUNDS["val"][1]
    lo, hi = Z._hist_bounds("confirm", cen)
    assert lo == C.SPLIT_BOUNDS["confirm"][0] and hi == C.SPLIT_BOUNDS["confirm"][1]
    lo, hi = Z._hist_bounds("debug", cen)
    assert lo == C.FINAL_LO and hi == cen.train_hi + 1

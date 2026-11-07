"""Tests for research/lab2/x6.py: the BOOST-end bar and the BOOST-time baseline on hand-built minute bars (exact
rates, AGENT removal, every universe exclusion), the takeover conditions one by one, the single decision per coin and
K, worst fills and next-bar exits, the fade exit and its placebo reference, the pre-registered grid, the class rule
(identical to M1's), no lookahead (synthetic and real census bars), the separation gate, the decision rules and the
stage refusals."""

import json
from types import SimpleNamespace
from typing import Iterable

import numpy as np
import pandas as pd
import pytest

import common as C
import m1
import x6 as X
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
P = {(k, e): X.make_params(k, e) for k in X.K_GRID for e in X.EXIT_GRID}


# =========================================================================== fixtures


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def path_bars(g: int, mint_: str, pool: str, org, sell, nb, ns, agent):
    """Hand-built minute bars: every SOL goes into the pricing reserve (X += org + agent - sell), y = k / X. ``nb`` =
    non-AGENT buyers; the AGENT adds one buyer in a minute where it bought >= 0.01 SOL (as B2 counts it). A minute
    without trades has no row (as in B2)."""
    m0 = int(g) // 60 * 60
    Xc, y = X0, Y0
    k = Xc * y
    rows = []
    for j in range(N_MIN):
        a, b, s = float(agent[j]), float(org[j]) + float(agent[j]), float(sell[j])
        if b <= 0 and s <= 0:
            continue
        X1 = Xc + b - s
        assert X1 > 1.0, f"minute {j}: the path drained the pool"
        y1 = k / X1
        bt, st = (y - y1, 0.0) if y1 < y else (0.0, y1 - y)
        p0, p1 = Xc / y, X1 / y1
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": max(int(nb[j]), 1) if b > 0 else 0,
                     "n_sells": max(int(ns[j]), 1) if s > 0 else 0, "n_dust": 0, "buy_sol": b, "sell_sol": s,
                     "buy_tok": bt, "sell_tok": st, "n_buyers": int(nb[j]) + (1 if a >= 0.01 else 0),
                     "n_sellers": int(ns[j]), "top5_buy_sol": b, "open": p0, "high": max(p0, p1), "low": min(p0, p1),
                     "close": p1, "x_close": X1 - V0, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g,
                     "minute_idx": j, "agent_buy_sol": a, "price_repaired": 0})
        Xc, y = X1, y1
    return pd.DataFrame(rows)


def spec(kind: str = "take", j_b: int = 5, base_org: float = 1.0, base_nb: int = 4, post_org: float | None = None,
         post_sell: float | None = None, post_nb: int | None = None, post_len: int = 14, after: str = "moon",
         moon_buy: float = 4.0, whale_at: int | None = None, burst: bool = False, agent_sol: float = 3.0) -> dict:
    """A slow graduate: a 3-minute migration burst, the AGENT buying ``agent_sol`` SOL a minute in bars 0 .. j_b,
    BOOST-time non-AGENT buying ``base_org`` SOL a minute from ``base_nb`` buyers (bars 3 .. j_b), then ``post_len``
    post-BOOST minutes, then ``after`` (moon: ``moon_buy`` SOL a minute for 40 min; die: heavy selling; flat).

    kinds: take (post 4.5 SOL/min from 6 buyers, net +), die (0.2 SOL/min, net -), thin (net + but one buyer a minute).
    ``whale_at``: one post minute with 30 SOL from one buyer; ``burst``: all post buying in its first 2 minutes."""
    dflt = {"take": (4.5, 3.5, 6), "die": (0.2, 1.0, 2), "thin": (2.0, 1.5, 1)}[kind]
    post_org = dflt[0] if post_org is None else post_org
    post_sell = dflt[1] if post_sell is None else post_sell
    post_nb = dflt[2] if post_nb is None else post_nb
    org, sell, nb, ns, agent = (np.zeros(N_MIN) for _ in range(5))
    org[0:3], sell[0:3], nb[0:3], ns[0:3] = 6.0, 1.0, 10, 3
    agent[0:j_b + 1] = agent_sol
    org[3:j_b + 1], sell[3:j_b + 1], nb[3:j_b + 1], ns[3:j_b + 1] = base_org, 0.5, base_nb, 2
    lo, hi = j_b + 1, j_b + 1 + post_len
    org[lo:hi], sell[lo:hi], nb[lo:hi], ns[lo:hi] = post_org, post_sell, post_nb, 3
    if burst:
        tot = post_org * 5
        org[lo:hi], nb[lo:hi] = 0.1, post_nb
        org[lo:lo + 2] = tot / 2
        sell[lo:hi] = 0.05
    if whale_at is not None:
        org[whale_at], nb[whale_at], sell[whale_at] = 30.0, 1, 0.0
    tail = slice(hi + 40, N_MIN)
    if after == "moon":
        org[hi:hi + 40], sell[hi:hi + 40], nb[hi:hi + 40], ns[hi:hi + 40] = moon_buy, 0.5, 8, 2
    elif after == "die":
        org[hi:hi + 40], sell[hi:hi + 40], nb[hi:hi + 40], ns[hi:hi + 40] = 0.1, 0.0, 1, 0
        sell[hi:hi + 15], ns[hi:hi + 15] = 2.5, 5
    else:
        org[hi:hi + 40], sell[hi:hi + 40], nb[hi:hi + 40], ns[hi:hi + 40] = 0.3, 0.3, 2, 2
    org[tail], sell[tail], nb[tail], ns[tail] = 0.05, 0.05, 1, 1
    return {"org": org, "sell": sell, "nb": nb, "ns": ns, "agent": agent}


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0, instant: Iterable = (),
                operator: Iterable = (), no_agent: Iterable = ()):
    """make_frames (no AGENT anywhere: those coins are never in X6's universe) with coin i made a slow graduate whose
    AGENT was detected at g + 40 s and whose bars follow ``specs[i]``."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0, agent_every=0)
    for i, sp in specs.items():
        m = mint(i, seed)
        gi = g.index[g["mint"] == m][0]
        ci = c.index[c["mint"] == m][0]
        gts = int(g.loc[gi, "g_ts"])
        delay = 3 if i in instant else 3600
        g.loc[gi, "has_create"] = 1
        g.loc[gi, "c_ts"] = gts - delay
        g.loc[gi, "c_slot"] = 900 + i
        g.loc[gi, "grad_delay_s"] = float(delay)
        for col, v in (("creator", f"CREATOR{i}"), ("create_user", f"CU{i}"), ("name", f"N{i}"), ("symbol", f"S{i}")):
            g.loc[gi, col] = v
        if i not in no_agent:
            c.loc[ci, "agent_present"] = True
            c.loc[ci, "agent_wallet"] = f"AGENT{i}"
            c.loc[ci, "agent_known_at"] = float(gts + 40)
            c.loc[ci, "agent_slices"] = 29
            c.loc[ci, "agent_sol"] = 17.58
        top = [[f"W{i}a", 5.0, 0.0], [f"AGENT{i}", 4.0, 0.0], [f"W{i}c", 1.0, 0.0]]
        if i in operator:
            c.loc[ci, "w120_buy_sol"] = 900.0
            c.loc[ci, "w120_n_buyers"] = 12
        c.loc[ci, "w120_top10"] = json.dumps(top)
        sp_ = dict(sp)
        if i in no_agent:
            sp_["agent"] = np.zeros(N_MIN)
        b = pd.concat([b[b["mint"] != m], path_bars(gts, m, str(g.loc[gi, "pool"]), **sp_)], ignore_index=True)
    return g, c, b


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def snap_k(ds: C.Dataset, m: str, k: int) -> C.AsOf:
    """The decision on the grid at which exactly k bars have completed."""
    cd = ds.coin(m)
    return ds.asof(m, cd.bar_start(k) + C.GRID_OFFSET_S)


# =========================================================================== BOOST end and baseline


def test_window_end_bar_is_the_last_bar_starting_before_g_plus_420():
    m0 = C.utc_ts("2026-10-02 00:00")
    assert X.window_end_bar(m0) == 6                 # bar 7 starts exactly at g + 420: not before it
    for s in (1, 30, 59):
        assert X.window_end_bar(m0 + s) == 7
    for s in (0, 1, 30, 59):                         # bar j_w starts before g + 420 and ends at or after it
        jw = X.window_end_bar(m0 + s)
        assert m0 + 60 * jw < m0 + s + C.AGENT_WINDOW_S <= m0 + 60 * (jw + 1)


def test_boost_state_exact_baseline_and_readiness():
    ds = ds_of(frames_with({1: spec(j_b=5, base_org=1.2, base_nb=4, agent_sol=3.0)}))
    m = mint(1)
    jw = X.window_end_bar(ds.coin(m).g)
    early = X.boost_state(snap_k(ds, m, jw))
    assert not early["ready"] and early["boost"] is None
    bs = X.boost_state(snap_k(ds, m, jw + 1))
    assert bs["ready"] and bs["boost"] and bs["reason"] is None and bs["j_b"] == 5 and bs["n_base"] == 3
    assert bs["r_org_B"] == pytest.approx(1.2) and bs["r_tot_B"] == pytest.approx(4.2)
    assert bs["nb_B"] == pytest.approx(4.0)         # the AGENT's buyer slot is removed in every BOOST minute
    assert bs["agent_sol_B"] == pytest.approx(9.0)
    later = X.boost_state(snap_k(ds, m, 40))
    assert {k: later[k] for k in ("j_b", "r_org_B", "nb_B")} == {k: bs[k] for k in ("j_b", "r_org_B", "nb_B")}


def test_agent_buys_after_the_window_never_move_boost_end():
    sp = spec(j_b=5)
    sp["agent"][9] = 2.0                             # an AGENT-wallet buy in bar 9 (after g + 420 s)
    ds = ds_of(frames_with({1: sp}))
    assert X.boost_state(snap_k(ds, mint(1), 20))["j_b"] == 5


def test_universe_exclusions():
    specs = {i: spec() for i in range(6)}
    specs[3] = spec(j_b=3)                           # BOOST ended in bar 3: one baseline bar
    ds = ds_of(frames_with(specs, n=8, instant=[1], operator=[2], no_agent=[4]))
    why = {i: X.universe_reason(snap_k(ds, mint(i), 9)) for i in range(6)}
    assert why == {0: None, 1: "instant", 2: "class_OPERATOR", 3: "short_boost", 4: "no_agent", 5: None}
    # noise coins of make_frames: no AGENT (agent_every=0); instant ones are excluded first
    for i in (6, 7):
        assert X.universe_reason(snap_k(ds, mint(i), 9)) in ("instant", "no_agent")
    assert X.universe_reason(snap_k(ds, mint(0), 5)) == "not_ready"
    # an AGENT whose bars carry no SOL
    sp = spec()
    sp["agent"][:] = 0.0
    ds2 = ds_of(frames_with({0: sp}))
    assert X.universe_reason(snap_k(ds2, mint(0), 9)) == "no_agent_bar"


def test_class_rule_is_m1s():
    g, c, b = make_frames(n=30, seed=4)             # instant, slow and AGENT coins mixed
    ci = c.index[:5]
    c.loc[ci, "w120_buy_sol"] = 900.0               # some operator candidates
    c.loc[ci[:2], "w120_n_buyers"] = 40
    c.loc[c.index[5:9], "w120_top5_share_ex_agent"] = 0.95
    ds = ds_of((g, c, b))
    seen = set()
    for m in ds.mints:
        cd = ds.coin(m)
        for dt in (100, 300, 500, 900):
            s = ds.asof(m, cd.g + dt)
            assert X.x6_class(s) == m1.m1_class(s)
            seen.add(X.x6_class(s))
    assert {"OPERATOR", "OTHER", None} <= seen


def test_flow_stats_exact_and_agent_removed():
    ds = ds_of(frames_with({1: spec(j_b=5)}))
    s = snap_k(ds, mint(1), 30)
    st = X.flow_stats(s.bars, 3, 6)                 # BOOST bars: org 1.0, AGENT 3.0, sell 0.5, 4 + 1 buyers
    assert st == {"n": 3, "r_org": pytest.approx(1.0), "r_tot": pytest.approx(4.0), "net": pytest.approx(1.5),
                  "nb": pytest.approx(4.0), "top": pytest.approx(1 / 3)}
    pw = X.flow_stats(s.bars, 6, 11)
    assert pw["r_org"] == pytest.approx(4.5) and pw["net"] == pytest.approx(5.0) and pw["nb"] == pytest.approx(6.0)
    assert X.flow_stats(s.bars, 5, 5)["r_org"] is None


# =========================================================================== takeover conditions


def _ev(sp: dict, K: int = 5, i: int = 1, **fk) -> dict:
    ds = ds_of(frames_with({i: sp}, **fk))
    bs = X.boost_state(snap_k(ds, mint(i), 9))
    return X.takeover_eval(snap_k(ds, mint(i), X.decision_bar(bs, K)), K)


def test_takeover_and_replace_levels():
    for K in X.K_GRID:
        ev = _ev(spec("take"), K)
        assert ev["ok"] and ev["due"] and ev["k_dec"] == 5 + 1 + K
        assert ev["TAKEOVER"] == {"CONSTANT": True, "REPLACE": True} and not ev["DIES"] and not ev["MIDDLE"]
        assert ev["r_P"] == pytest.approx(4.5) and ev["ratio"] == pytest.approx(4.5) and ev["nb_P"] == pytest.approx(6)
    # 2 SOL/min from 6 buyers: holds the non-AGENT rate (1.0) but does not replace the AGENT (4.0 in total)
    ev = _ev(spec("take", post_org=2.0, post_sell=1.5))
    assert ev["TAKEOVER"] == {"CONSTANT": True, "REPLACE": False}
    assert ev["conds"]["rate_CONSTANT"] and not ev["conds"]["rate_REPLACE"]


def test_dies_middle_and_momentum():
    ev = _ev(spec("die"))
    assert ev["DIES"] and not any(ev["TAKEOVER"].values()) and not ev["MIDDLE"] and not ev["momentum"]
    thin = _ev(spec("thin"))
    assert not thin["conds"]["breadth"] and thin["conds"]["absorb"] and thin["MIDDLE"] and thin["momentum"]


@pytest.mark.parametrize("sp, failing", [
    (spec("take", post_org=0.9, base_org=0.5, post_sell=0.5), "size"),           # holds the rate, but < 1 SOL/min
    (spec("take", post_sell=5.0), "absorb"),                                     # net selling
    (spec("take", post_nb=2), "breadth"),                                        # fewer than 3 buyers a minute
    (spec("take", base_nb=8), "breadth"),                                        # breadth fell from 8 to 6
    (spec("take", whale_at=7), "dispersed"),                                     # one whale minute
    (spec("take", post_org=0.8, base_org=1.0, post_sell=0.5), "rate_CONSTANT"),  # non-AGENT rate fell
])
def test_each_condition_can_veto(sp, failing):
    ev = _ev(sp)
    assert not ev["conds"][failing] and not ev["TAKEOVER"]["CONSTANT"]


def test_burst_then_die_fails_the_last_half():
    ev = _ev(spec("take", burst=True, post_org=2.4), K=10)
    assert ev["r_P"] >= ev["r_org_B"] and ev["r_last"] < ev["r_org_B"]
    assert not ev["conds"]["rate_CONSTANT"] and not ev["TAKEOVER"]["CONSTANT"]


def test_not_due_before_the_window_completes():
    ds = ds_of(frames_with({1: spec()}))
    ev = X.takeover_eval(snap_k(ds, mint(1), 9), 5)
    assert not ev["ok"] and not ev["due"] and ev["k_dec"] == 11


# =========================================================================== strategy, fills, exits


def test_strategy_waits_decides_once_and_skips():
    ds = ds_of(frames_with({1: spec("take"), 2: spec("die")}))
    p = P[(5, "hold30")]
    assert X.strategy(snap_k(ds, mint(1), 6), p, None) is None            # BOOST not known to be over
    assert X.strategy(snap_k(ds, mint(1), 10), p, None) is None           # window not complete
    e = X.strategy(snap_k(ds, mint(1), 11), p, None)
    assert isinstance(e, C.Enter) and e.tag == "CONSTANT" and e.state["r_P"] == pytest.approx(4.5)
    assert e.exits == C.ExitSpec(stop_pct=0.30, max_hold_s=1800.0, exit_by_age_s=178 * 60.0)
    assert X.strategy(snap_k(ds, mint(1), 12), p, None) is C.SKIP         # the decision passed
    assert X.strategy(snap_k(ds, mint(2), 11), p, None) is C.SKIP         # DIES: never traded
    assert X.strategy(snap_k(ds, mint(5), 9), p, None) is C.SKIP          # no AGENT: out of the universe
    assert X.strategy(ds.asof(mint(1), ds.coin(mint(1)).g + 1600), p, None) is C.SKIP   # past g + 25 min


def test_one_entry_worst_fill_and_time_exit():
    ds = ds_of(frames_with({1: spec("take")}))
    cd = ds.coin(mint(1))
    for K in X.K_GRID:
        t = C.run_trades(ds, X.strategy, P[(K, "hold30")], X.FILL, mints=[mint(1)])
        assert len(t) == 1
        r = t.iloc[0]
        kd = 5 + 1 + K
        assert r["t_dec"] == cd.bar_start(kd) + C.GRID_OFFSET_S
        j = cd.bar_of(r["t_in"])
        assert j == kd and r["entry_price"] == pytest.approx(max(cd.arr["o"][j], cd.arr["h"][j]))
        assert r["reason"] == "time" and 30 <= (r["t_out"] - r["t_in"]) / 60 <= 32.5


def test_fade_exit_fills_on_the_next_bar():
    ds = ds_of(frames_with({1: spec("take", after="die", post_len=8)}))
    cd = ds.coin(mint(1))
    fade = C.run_trades(ds, X.strategy, P[(5, "fade60")], X.FILL, mints=[mint(1)]).iloc[0]
    hold = C.run_trades(ds, X.strategy, P[(5, "hold30")], X.FILL, mints=[mint(1)]).iloc[0]
    assert fade["reason"] == "signal:fade" and hold["reason"] in ("time", "stop")
    j = cd.bar_of(fade["t_out"])
    assert fade["exit_price"] == pytest.approx(min(cd.arr["o"][j], cd.arr["l"][j]))
    # entry bar 11; the dump starts at bar 14; the decision after bar 15 sees bars 13-15 -> a signal exit lands in 16
    assert j == 16 and fade["t_out"] < hold["t_out"]


def test_stop_fills_on_the_next_bar_at_the_low():
    sp = spec("take", after="flat")
    sp["sell"][12], sp["ns"][12] = 60.0, 1                 # a rug in bar 12, after the entry bar 11
    ds = ds_of(frames_with({1: sp}))
    cd = ds.coin(mint(1))
    r = C.run_trades(ds, X.strategy, P[(5, "hold30")], X.FILL, mints=[mint(1)]).iloc[0]
    assert r["reason"] == "stop" and cd.bar_of(r["t_out"]) == 13
    assert r["exit_price"] == pytest.approx(min(cd.arr["o"][13], cd.arr["l"][13]))
    assert r["ret_net"] < -0.30


def test_placebo_position_recomputes_its_reference():
    ds = ds_of(frames_with({1: spec("take", after="die", post_len=8)}))
    cd = ds.coin(mint(1))
    p = P[(5, "fade60")]
    t_dec = cd.bar_start(11) + C.GRID_OFFSET_S

    def pv(state):
        return C.PositionView(mint=mint(1), t_dec=t_dec, t_in=t_dec + 30, entry_price=1.0, tokens=1.0, sol_in=0.1,
                              peak=1.0, bars_held=1, unrealized=0.0, exits=X.exit_spec(p), state=state,
                              is_placebo=not state)
    for k in range(12, 30):
        s = snap_k(ds, mint(1), k)
        assert (X.exit_decision(s, p, pv({})) is None) == (X.exit_decision(s, p, pv({"r_P": 4.5})) is None)
    assert X.exit_decision(snap_k(ds, mint(1), 13), p, pv({})) is None      # < 3 bars after the decision
    assert isinstance(X.exit_decision(snap_k(ds, mint(1), 17), p, pv({})), C.Exit)
    assert X.exit_decision(snap_k(ds, mint(1), 17), P[(5, "hold30")], pv({})) is None


def test_placebo_and_momentum_eligibility():
    ds = ds_of(frames_with({1: spec("take"), 2: spec("die"), 3: spec("thin")}, instant=[3]))
    s = {i: snap_k(ds, mint(i), 11) for i in (1, 2, 3, 5)}
    assert X.placebo_ok(s[1]) and X.placebo_ok(s[2]) and not X.placebo_ok(s[3]) and not X.placebo_ok(s[5])
    mom = X.momentum_ok(5)
    assert mom(s[1]) and not mom(s[2])
    assert not X.placebo_ok(snap_k(ds, mint(1), 6))                         # BOOST not over yet
    pc = X.placebo_controls(P[(10, "hold30")])
    assert set(pc) == {"momentum", "unmatched"} and pc["momentum"]["eligible"].__name__ == "momentum_K10"


def test_grid_is_the_preregistered_grid():
    assert len(X.GRID) == 4 <= 12
    keys = [X.config_key(p) for p in X.GRID]
    assert keys == ["K5|hold30", "K5|fade60", "K10|hold30", "K10|fade60"]
    assert len({C.params_hash(p) for p in X.GRID}) == 4
    for p in X.GRID:
        assert p["version"] == "x6-v1" and p["max_hold_s"] == X.HOLD_S[p["exit"]] and p["level"] == "CONSTANT"
        assert {k: p[k] for k in X.FIXED} == X.FIXED
    with pytest.raises(ValueError):
        X.make_params(7, "hold30")
    with pytest.raises(ValueError):
        X.make_params(5, "hold45")
    assert [X.config_key(p) for p in X.train_configs([10])] == keys[2:]


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    bs = X.boost_state(s)
    out = [tuple(sorted((k, v) for k, v in bs.items())), X.universe_reason(s, bs), X.placebo_ok(s),
           X.momentum_ok(5)(s), X.momentum_ok(10)(s)]
    for K in X.K_GRID:
        ev = X.takeover_eval(s, K, bs)
        out.append(tuple(sorted((k, json.dumps(v, sort_keys=True, default=str)) for k, v in ev.items())))
    out += [repr(X.strategy(s, p, None)) for p in X.GRID]
    return tuple(out)


def _mixed_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(10):
        kind = ["take", "die", "thin"][int(rng.integers(3))]
        specs[i] = spec(kind, j_b=int(rng.integers(4, 7)), base_org=float(rng.uniform(0.3, 2.0)),
                        base_nb=int(rng.integers(2, 7)), post_len=int(rng.integers(6, 15)),
                        after=["moon", "die", "flat"][int(rng.integers(3))])
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _mixed_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(14):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([300, 450, 600, 700, 800, 1000, 1200, 1500])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _mixed_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(10):
        m = mint(i)
        T = clean.coin(m).g + 20 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        for p in X.GRID:
            a = C.run_trades(clean, X.strategy, p, X.FILL, mints=[m])
            b = C.run_trades(dirty, X.strategy, p, X.FILL, mints=[m])
            assert a.loc[a["t_dec"] <= T, "t_dec"].tolist() == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n_entries += int((a["t_dec"] <= T).sum())
    assert n_entries > 0


def test_separation_features_unchanged_by_future_garbage():
    """The gate's observations and group flags (not the label) use only data up to each decision's tau."""
    frames = _mixed_frames(11)
    clean = ds_of(frames)
    rng = np.random.default_rng(3)
    cols = ["mint", "K", "t", "j_b", "r_org_B", "r_P", "nb_P", "net_P", "TAKEOVER", "REPLACE", "DIES", "MIDDLE",
            "momentum"]
    for i in range(10):
        m = mint(i)
        T = clean.coin(m).g + 18 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        a, b = X.sep_obs(clean, [m], with_labels=False), X.sep_obs(dirty, [m], with_labels=False)
        a, b = a[a["t"] <= T][cols], b[b["t"] <= T][cols]
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """X6 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(12)
    pick = [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=16, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(420, 700)), float(rng.uniform(700, 1100)), float(rng.uniform(1100, 1500))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


# =========================================================================== separation gate


def _obs(n_to: int, m_to: float, n_d: int, m_d: float, K: int = 5, n_mid: int = 10, sd: float = 0.05,
         seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for grp, n, mu in (("TAKEOVER", n_to, m_to), ("DIES", n_d, m_d), ("MIDDLE", n_mid, 0.0)):
        for i in range(n):
            rows.append({"mint": f"{grp}{i}", "K": K, "TAKEOVER": grp == "TAKEOVER", "REPLACE": False,
                         "DIES": grp == "DIES", "MIDDLE": grp == "MIDDLE", "momentum": False,
                         "fwd30": float(mu + sd * rng.standard_normal())})
    return pd.DataFrame(rows)


def test_sep_check_pass_kill_underpowered():
    d = X.sep_check(_obs(40, 0.10, 40, -0.10), B=500)
    assert d["decision"] == "PASS" and d["passed"] == [5]
    k5 = d["per_K"]["5"]
    assert k5["powered"] and k5["passes"] and k5["diff_ci90"][0] > 0
    assert k5["diff"] == pytest.approx(k5["means"]["TAKEOVER"] - k5["means"]["DIES"])
    assert d["per_K"]["10"]["n"] == 0 and not d["per_K"]["10"]["powered"]
    assert X.sep_check(_obs(40, 0.02, 40, 0.0), B=500)["decision"] == "KILL"           # diff < 5 points
    assert X.sep_check(_obs(40, -0.02, 40, -0.20), B=500)["decision"] == "KILL"         # TAKEOVER mean <= 0
    noisy = X.sep_check(_obs(40, 0.06, 40, 0.0, sd=0.6, seed=2), B=500)                # CI includes 0
    assert noisy["decision"] == "KILL" and not noisy["per_K"]["5"]["passes"]
    assert X.sep_check(_obs(29, 0.5, 40, -0.5), B=500)["decision"] == "UNDERPOWERED"
    assert X.sep_check(_obs(40, 0.5, 29, -0.5), B=500)["decision"] == "UNDERPOWERED"
    both = X.sep_check(pd.concat([_obs(40, 0.1, 40, -0.1), _obs(40, 0.0, 40, 0.0, K=10, seed=1)]), B=500)
    assert both["decision"] == "PASS" and both["passed"] == [5]


def test_sep_check_hide_returns_counts_only():
    d = X.sep_check(_obs(40, 0.10, 40, -0.10), hide=True)
    assert d["decision"].startswith("HIDDEN")
    assert d["per_K"]["5"] == {"n": 90, "n_TAKEOVER": 40, "n_REPLACE": 0, "n_DIES": 40, "n_MIDDLE": 10,
                               "n_momentum": 0}


def test_boot_diff_brackets_the_point_estimate():
    a, b = np.linspace(0, 0.2, 40), np.linspace(-0.2, 0.0, 35)
    lo, hi = X._boot_diff(a, b, 1000)
    assert lo < a.mean() - b.mean() < hi
    assert X._boot_diff(a[:1], b, 100) is None


def test_sep_obs_groups_and_labels_on_synthetic_coins():
    ds = ds_of(frames_with({0: spec("take"), 1: spec("die", after="die"), 2: spec("thin", after="die")}, n=6))
    obs = X.sep_obs(ds)
    assert set(obs["mint"]) == {mint(0), mint(1), mint(2)} and set(obs["K"]) == set(X.K_GRID)
    by = obs.set_index(["mint", "K"])
    for K in X.K_GRID:
        assert by.loc[(mint(0), K), "TAKEOVER"] and by.loc[(mint(0), K), "fwd30"] > 0.2
        assert by.loc[(mint(1), K), "DIES"] and by.loc[(mint(1), K), "fwd30"] < 0
        assert by.loc[(mint(2), K), "MIDDLE"] and by.loc[(mint(2), K), "momentum"]
    r = obs.iloc[0]
    snap, later = ds.asof(r["mint"], r["t"]), ds.asof(r["mint"], r["t"] + 1800)
    assert r["fwd30"] == pytest.approx(later.price / snap.price - 1.0) and later.k - snap.k == 30
    assert obs["age_min"].max() <= 25


# =========================================================================== decision rules


def _evd(n=80, coins=80, mean=0.05, mw2=0.04, ci_lo=0.01, pc=0.03, mc=0.02, cs=0.0, cfg="K5|hold30"):
    return {"config": cfg, "params_hash": "h" + cfg, "n": n, "n_coins": coins, "mean": mean, "mean_without_top2": mw2,
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.1), "censored_share": cs,
            "placebo": {"mean_diff": pc}, "controls": {"momentum": {"mean_diff": mc}}}


def test_decide_train_qualifiers_and_rank_order():
    keys = [X.config_key(p) for p in X.GRID]
    evals = {k: _evd(cfg=k, ci_lo=-0.05) for k in keys}
    evals["K10|fade60"] = _evd(cfg="K10|fade60", ci_lo=0.02)
    evals["K10|hold30"] = _evd(cfg="K10|hold30", ci_lo=0.03)
    evals["K5|fade60"] = _evd(cfg="K5|fade60", ci_lo=0.03)                     # tie: grid order decides
    d = X.decide_train(evals)
    assert d["verdict"] == "SHORTLISTED" and d["ranked"] == ["K5|fade60", "K10|hold30"]
    assert [X.config_key(p) for p in d["shortlist"]] == d["ranked"]
    assert d["shortlist_hashes"] == [C.params_hash(p) for p in d["shortlist"]]
    for bad in ({"pc": 0.0}, {"mc": 0.0}, {"mc": None}, {"mw2": -0.01}, {"mean": -0.01}, {"cs": 0.2}, {"n": 29},
                {"coins": 29}):
        assert X.decide_train({k: _evd(cfg=k, **bad) for k in keys})["verdict"] in ("NO_CONFIG", "UNDERPOWERED_TRAIN")
    assert X.decide_train({k: _evd(cfg=k, mc=-0.01) for k in keys})["verdict"] == "NO_CONFIG"
    assert X.decide_train({k: _evd(cfg=k, n=20, coins=20) for k in keys})["verdict"] == "UNDERPOWERED_TRAIN"


def test_decide_val_is_a_filter_not_a_ranking():
    good, bad, few = _evd(n=20, mean=0.01), _evd(n=20, mean=0.30, mw2=-0.01), _evd(n=4)
    d = X.decide_val({"rank1": good, "rank2": _evd(n=20, mean=0.5)}, ["rank1", "rank2"])
    assert d["verdict"] == "SELECTED" and d["candidate_role"] == "rank1"
    d = X.decide_val({"rank1": bad, "rank2": _evd(n=8)}, ["rank1", "rank2"])
    assert d["verdict"] == "SELECTED_UNDERPOWERED" and d["candidate_role"] == "rank2"
    assert X.decide_val({"rank1": bad, "rank2": few}, ["rank1", "rank2"])["verdict"] == "FAIL_VAL"
    assert X.decide_val({"rank1": few}, ["rank1"])["verdict"] == "UNDERPOWERED_VAL"


def test_combine_verdict_x6_extra_and_confirm_rule():
    def base(**over):
        crit = [{"id": i, "pass": True} for i in range(1, 11)]
        for i, v in over.items():
            crit[int(i[1:]) - 1]["pass"] = v
        return {"criteria": crit, "auto_rejections": []}
    ok, bad, none = (X.x6_extras(_evd(mc=v)) for v in (0.01, -0.01, None))
    assert X.combine_verdict(base(c9=None), ok) == "PASS"
    assert X.combine_verdict(base(), bad) == "FAIL"
    assert X.combine_verdict(base(), none) == "INCOMPLETE"
    assert X.combine_verdict(base(c1=False, c2=False), bad) == "UNDERPOWERED"
    assert X.combine_verdict(base(c5=False), ok) == "FAIL"
    assert X.combine_verdict(base(c7=None), ok) == "INCOMPLETE"
    assert X.combine_verdict(base(c10=False), ok) == "INCOMPLETE"
    assert X.combine_verdict({**base(), "auto_rejections": ["x"]}, ok) == "REJECTED"
    doc = {"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": -0.02}}}
    assert not X.confirm_allowed(doc)[0]
    doc["configs"]["candidate"] = {"n": 3, "mean": -0.02}
    assert X.confirm_allowed(doc)[0]
    assert not X.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 3}}})[0]


def test_final_decision_judges_val_and_test_thirds_only():
    t = pd.DataFrame({"split": ["final_train"] * 3 + ["final_val", "final_test"], "ret_net": [5.0, 5, 5, -0.1, 0.05]})
    d = X.final_decision(t)
    assert d["n"] == 2 and d["mean"] == pytest.approx(-0.025) and d["mean_positive"] is False
    assert d["debug_third"]["n"] == 3


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "X6", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# X6 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return X.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return X.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, t0: int, n_take: int, n_die: int, n_thin: int, seed: int, moon: bool = True,
           n_noise: int = 2) -> C.Dataset:
    """n_take takeover coins (then a moon, or with ``moon=False`` a dump), n_die flow-dies coins and n_thin
    momentum-but-thin coins (both dump afterwards), plus no-AGENT noise coins. Sizes jitter per coin."""
    rng = np.random.default_rng(seed)
    specs, i = {}, 0
    for kind, n in (("take", n_take), ("die", n_die), ("thin", n_thin)):
        for _ in range(n):
            after = ("moon" if moon else "die") if kind == "take" else "die"
            specs[i] = spec(kind, j_b=int(rng.integers(4, 7)), base_org=float(rng.uniform(0.6, 1.2)), after=after,
                            moon_buy=float(rng.uniform(3.0, 5.0)))
            i += 1
    return ds_of(frames_with(specs, n=i + n_noise, seed=seed, t0=t0), split)


def test_train_killed_by_the_separation_gate(st):
    doc = _run("train", st, market("train", T0, 35, 32, 4, 1, moon=False))
    assert doc["decision"]["verdict"] == "KILLED_SEP" and doc["separation"]["decision"] == "KILL"
    assert "configs" not in doc and doc["overall"].startswith("KILLED")
    led = json.loads(st.ledger.read_text())
    assert [v["hypothesis"] for v in led["configs"].values()] == ["X6-sep"]      # the grid never ran: 1 trial
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(X.X6Refused, match="dead"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(X.X6Refused, match="final"):
        _run("train", st, market("train", T0, 35, 32, 4, 1, moon=False))


def test_train_underpowered_gate(st):
    doc = _run("train", st, market("train", T0, 10, 10, 2, 1))
    assert doc["decision"]["verdict"] == "UNDERPOWERED_SEP" and doc["overall"].startswith("UNDERPOWERED")
    with pytest.raises(X.X6Refused, match="UNDERPOWERED_SEP"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 35, 32, 4, 1)
    with pytest.raises(X.X6Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "X6.json").exists()
    with pytest.raises(X.X6Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; x6's ``env=`` drives x6's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(X.X6Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: the gate passes for both K, the whole grid runs, the shortlist (top 2 in rank order)
    tr = _run("train", st, market("train", T0, 35, 32, 6, 1))
    sep = tr["separation"]
    assert sep["decision"] == "PASS" and sep["passed"] == [5, 10]
    assert set(tr["configs"]) == {X.config_key(p) for p in X.GRID}
    for e in tr["configs"].values():
        assert e["n"] == 35 and set(e["controls"]) == {"momentum", "unmatched"} and e["censored_share"] == 0.0
        assert e["placebo"]["mean_diff"] > 0 and e["controls"]["momentum"]["mean_diff"] > 0
        assert e["decision_age_min"]["p90"] <= 25
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert len(tr["decision"]["ranked"]) == 2
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sorted(v["hypothesis"] for v in led["configs"].values()) == ["X6"] * 4 + ["X6-sep"]
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(X.X6Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# X6 test prereg\n")
    for stage in ("test", "confirm", "final"):
        with pytest.raises(X.X6Refused, match="no VAL result"):
            _check(stage, st, env=env_all)
    sl = (st.sl / "X6.json").read_text()
    (st.sl / "X6.json").unlink()
    with pytest.raises(X.X6Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "X6.json").write_text(sl)
    # ---- VAL
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 18, 8, 3, 2))
    assert set(va["configs"]) == {"rank1", "rank2"}
    assert va["decision"]["verdict"] == "SELECTED" and va["decision"]["candidate_role"] == "rank1"
    with pytest.raises(X.X6Refused, match="VAL already ran"):
        _check("val", st)
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 5      # VAL adds no trial
    with pytest.raises(X.X6Refused, match="before TEST"):
        _check("final", st, env=env_all)
    # ---- TEST: locked without the judge's flag, then once only
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 20, 6, 2, 3)
    with pytest.raises(X.X6Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert set(te["configs"]) == {"candidate"} and te["verdict"]["verdict"] == "UNDERPOWERED"
    with pytest.raises(X.X6Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(X.X6Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 66, 16, 8, 4), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["verdict"]["x6_extras"][0]["pass"] is True and co["overall"] == "PENDING FINAL"
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 10, 4, 2, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True and fi["overall"] == "EDGE"
    with pytest.raises(X.X6Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 5      # the whole life of X6: 5 trials


def test_val_failure_stops_x6(st):
    _run("train", st, market("train", T0, 35, 32, 6, 1))
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 18, 8, 3, 2, moon=False))
    assert va["decision"]["verdict"] == "FAIL_VAL" and va["overall"].startswith("NO EDGE")
    with pytest.raises(X.X6Refused, match="FAIL_VAL"):
        _check("test", st, env={"LAB2_ALLOW_TEST": "1"})


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(X.X6Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(X.X6Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 12, 8, 4, 1)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = X.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    sp = doc["separation"]
    assert sp["decision"].startswith("HIDDEN") and sp["per_K"]["5"]["n_TAKEOVER"] == 12
    assert all("means" not in d and "diff" not in d for d in sp["per_K"].values())
    assert set(doc["configs"]) == {X.config_key(p) for p in X.GRID}
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden") and e["n"] == 12
        for k in ("mean", "ci90", "placebo", "controls", "stress", "portfolio", "reasons"):
            assert k not in e
    ec = doc["event_counts"]
    assert ec["universe_funnel"]["in_universe"] == 24
    assert ec["per_K"]["5"]["TAKEOVER_CONSTANT"] == 12 and ec["per_K"]["10"]["DIES"] == 8
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
    md = (st.out / "debug.md").read_text().lower()
    assert "mean" not in md.split("## configs")[1].split("## decision")[0]

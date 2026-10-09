"""Tests for research/lab2/z5.py: the exact round trip and its tier thresholds, the tier guard, the host pins (R0 is
G1's R0 decision for decision; M1 is m1-v1), the veto (filtered trades are an exact subset of the host's), the
decomposition and guard pairing on hand-built trades, no lookahead (synthetic and real census bars), the decision
rules, the predictions, the host-first rule and the stage refusals."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import z5 as Z
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
K0 = X0 * Y0
N_MIN = 186
ENV_ALL = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}


# =========================================================================== fixtures


def mint(i: int, seed: int = 1) -> str:
    return f"MINT{i:03d}{seed}pump"


def coin_bars(g: int, mint_: str, pool: str, buy, sell, n_buyers=None, n_sellers=None) -> pd.DataFrame:
    """Hand-built minute bars: every SOL goes into the pricing reserve (X += buy - sell), y = k / X (token conservation
    exact), so the close is X^2 / k. No wicks (high / low = the body)."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    rows = []
    for j in range(N_MIN):
        b, s = float(buy[j]), float(sell[j])
        if b <= 0 and s <= 0:
            continue
        X1 = X + b - s
        assert X1 > 0
        y1 = K0 / X1
        bt, st = (y - y1, 0.0) if y1 < y else (0.0, y1 - y)
        p0, p1 = X / y, X1 / y1
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 4 if b > 0 else 0, "n_sells": 3 if s > 0 else 0, "n_dust": 0,
                     "buy_sol": b, "sell_sol": s, "buy_tok": bt, "sell_tok": st,
                     "n_buyers": int(n_buyers[j]) if n_buyers is not None else 4 * int(b > 0),
                     "n_sellers": int(n_sellers[j]) if n_sellers is not None else 3 * int(s > 0),
                     "top5_buy_sol": b, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": X1 - V0, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0, "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def full(v, n=N_MIN):
    return np.full(n, float(v))


def deep(x_to: float = 170.0, drift: float = 0.6, nb: int = 4) -> dict:
    """Ramp the pricing reserve from 85 to ``x_to`` SOL in 20 minutes, then net ``drift`` SOL a minute (buy 1.1).
    x_to 170 -> market cap ~1,650-2,950 SOL over ages 20-115 min (115 / 110-bps tiers, rt ~3.15-3.30 %);
    x_to 300 -> ~5,100+ SOL (100-bps tier, rt < 3.00 %). ``nb`` buyers a minute (M1 never fires at 4)."""
    buy, sell = full(1.1), full(1.1 - drift)
    buy[:20] = (x_to - X0) / 20.0 + 0.5
    sell[:20] = 0.5
    return {"buy": buy, "sell": sell, "n_buyers": full(nb), "n_sellers": full(1)}


def shallow(drift: float = -0.3, nb: int = 4) -> dict:
    """Stay near graduation depth (X ~85 -> 50 SOL by 115 min: 125-bps tier, rt ~3.7-4.0 %), alive (1.3 SOL a minute)."""
    return {"buy": full(0.5), "sell": full(0.5 - drift), "n_buyers": full(nb), "n_sellers": full(1)}


def frames_with(specs: dict, n: int = 8, seed: int = 1, t0: int = T0):
    """make_frames (random-walk noise coins) with coin i's bars replaced by coin_bars(**spec)."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0)
    for i, spec in specs.items():
        r = g[g["mint"] == mint(i, seed)].iloc[0]
        b = pd.concat([b[b["mint"] != r["mint"]], coin_bars(int(r["g_ts"]), r["mint"], r["pool"], **spec)],
                      ignore_index=True)
    return g, c, b


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def snap_k(ds: C.Dataset, m: str, k: int) -> C.AsOf:
    cd = ds.coin(m)
    s = ds.asof(m, cd.bar_start(k) + C.GRID_OFFSET_S)
    assert s.k == k
    return s


def pv(snap: C.AsOf, **kw) -> C.PositionView:
    d = dict(mint=snap.mint, t_dec=snap.t - 120, t_in=snap.t - 90, entry_price=snap.price, tokens=1.0, sol_in=1.0,
             peak=snap.price, bars_held=2, unrealized=0.0, exits=C.ExitSpec(), state={}, is_placebo=False)
    d.update(kw)
    return C.PositionView(**d)


def P(host, c=None, guard=False):
    return Z.make_params(host, c, guard)


def market(split: str, t0: int, n_deep: int, n_shallow: int, n_noise: int, seed: int, deep_drift: float = 0.6,
           deep_x: float = 170.0, m1_bid: bool = False) -> C.Dataset:
    """n_deep coins ramped to X = ``deep_x`` (the cheap tiers) that then move ``deep_drift`` SOL a minute, n_shallow
    coins at graduation depth that bleed, and random-walk noise coins. ``m1_bid``: one buyer a minute (a steady
    MECH-bar bid M1 rides). Slow coins of a FINAL market fall in TEST (unknown creation), so FINAL holds fewer coins."""
    nb = 1 if m1_bid else 4
    specs = {i: deep(deep_x, deep_drift, nb) for i in range(n_deep)}
    specs.update({i: shallow(nb=nb) for i in range(n_deep, n_deep + n_shallow)})
    ds = ds_of(frames_with(specs, n=n_deep + n_shallow + n_noise, seed=seed, t0=t0), split)
    assert len(ds) >= 0.75 * (n_deep + n_shallow + n_noise)
    return ds


# =========================================================================== the cost and the thresholds


@pytest.mark.parametrize("sol_usd", [100.0, 116.1, 140.0])
def test_thresholds_are_the_tier_boundaries(sol_usd):
    """PREREG 2: c = 3.40 % separates 1,469 from 1,470 SOL and c = 3.00 % separates 4,419 from 4,420 SOL."""
    ts = C.utc_ts("2026-10-03")

    def rt(m):
        return C.round_trip_pct(20 / sol_usd, m / 1e9, K0, ts) / 100
    assert rt(1469) > 0.034 > rt(1470)
    assert rt(4419) > 0.030 > rt(4420)
    assert rt(411) == pytest.approx(0.037, abs=0.0006) and rt(52) > 0.042
    assert C.fee_bps_at(ts, 1469) == 120 and C.fee_bps_at(ts, 1470) == 115 and C.fee_bps_at(ts, 4420) == 100


def test_round_trip_frac_is_commons_cost_at_the_last_close():
    ds = ds_of(frames_with({1: deep(), 2: shallow()}))
    for i in (1, 2):
        s = snap_k(ds, mint(i), 40)
        X, y = float(s.bars.X[-1]), float(s.bars.y[-1])
        want = C.round_trip_pct(20 / 100.0, X / y, X * y, s.t) / 100
        assert Z.round_trip_frac(s) == pytest.approx(want, rel=1e-12)
        assert s.price == pytest.approx(X / y, rel=1e-12)
    assert Z.round_trip_frac(snap_k(ds, mint(1), 40)) < 0.034 < Z.round_trip_frac(snap_k(ds, mint(2), 40))
    s0 = ds.asof(mint(1), ds.coin(mint(1)).bar_start(0) + C.GRID_OFFSET_S)
    assert s0.k == 0 and Z.round_trip_frac(s0) is None


def test_guard_level_and_arm():
    ts = C.utc_ts("2026-10-03")
    assert Z.tier_boundaries(ts)[:6] == [420.0, 1470.0, 2460.0, 3440.0, 4420.0, 9820.0]
    assert Z.guard_level(430, ts) is None                     # 430 / 1.05 < 420: no boundary far enough below
    assert Z.guard_level(441.0, ts) == 420.0                  # exactly 5 % above
    assert Z.guard_level(1500, ts) == 420.0                   # 1,470 is within 5 %: guard the next one down
    assert Z.guard_level(1600, ts) == 1470.0
    assert Z.guard_level(2700, ts) == 2460.0
    assert Z.guard_level(5000, ts) == 4420.0 and Z.guard_level(0, ts) is None


def test_guard_exit_uses_the_tier_the_buy_paid():
    ds = ds_of(frames_with({1: deep()}))
    s = snap_k(ds, mint(1), 40)
    m = s.mcap_sol                                               # X = 182 after bar 39: ~1,880 SOL (115-bps tier)
    assert 1470 * 1.02 < m < 2460
    assert Z.guard_exit(s, pv(s, entry_price=1600 / 1e9)) is None          # G = 1,470: the close is above 1.02 G
    ex = Z.guard_exit(s, pv(s, entry_price=2700 / 1e9))                    # bought in the 110 tier: G = 2,460 > close
    assert ex is not None and ex.reason == "tier_guard"
    assert Z.guard_exit(s, pv(s, entry_price=400 / 1e9)) is None           # no boundary 5 % below a 400-SOL buy


def test_guard_exit_exact_boundary_cases(monkeypatch):
    """With a single synthetic boundary B the rule is exactly: fire iff close mcap < 1.02 B."""
    ds = ds_of(frames_with({1: deep()}))
    s = snap_k(ds, mint(1), 40)
    m = s.mcap_sol
    for B, fire in ((m / 1.02 * 1.001, True), (m / 1.02 * 0.999, False)):
        monkeypatch.setattr(C, "fee_schedule_at", lambda ts, B=B: ((B, 125), (float("inf"), 30)))
        ex = Z.guard_exit(s, pv(s, entry_price=B * 1.06 / 1e9))
        assert (ex is not None) == fire, (B, m)
        if fire:
            assert ex.reason == "tier_guard"


# =========================================================================== hosts and the grid


def test_grid_is_the_preregistered_grid():
    assert len(Z.GRID) == 8 <= 12
    assert [Z.config_key(p) for p in Z.GRID] == [
        "R0|c-none|hx", "R0|c3.40|hx", "R0|c3.00|hx", "R0|c3.40|guard",
        "M1|c-none|hx", "M1|c3.40|hx", "M1|c3.00|hx", "M1|c3.40|guard"]
    assert len({C.params_hash(p) for p in Z.GRID}) == 8
    for p in Z.GRID:
        for k, v in Z.FIXED.items():
            assert p[k] == v
        assert p["host_params"] == dict(Z.HOST_PARAMS[p["host"]])
        assert Z.config_key(Z.baseline_of(p)) == f"{p['host']}|c-none|hx"
    for bad in (("R0", 0.032, False), ("X3", None, False), ("R0", None, True), ("M1", 0.030, True)):
        with pytest.raises(ValueError):
            Z.make_params(*bad)
    assert Z.FILL.entry_fill == "worst" and Z.FILL.exit_fill == "worst" and Z.FILL.exit_delay_bars == 1
    assert set(Z.STRESS) == {"costs_x1.5", "rent_0.22", "same_bar_exits", "open_fills"}
    assert all(f.exit_delay_bars == 1 for k, f in Z.STRESS.items() if k != "same_bar_exits")
    # JSON round trip (the shortlist) keeps every hash
    for p in Z.GRID:
        assert C.params_hash(json.loads(json.dumps(p))) == C.params_hash(p)


def test_host_pins_hold_and_a_changed_host_refuses(monkeypatch, tmp_path):
    import g1
    import m1
    assert Z.host_pin_problems() == []
    assert Z.R0_PARAMS == g1.R0_PARAMS and C.params_hash(g1.R0_PARAMS) == Z.R0_PIN
    assert m1.VERSION == Z.M1_VERSION_PIN and Z.M1_PARAMS == m1.make_params(1.0, "rhythm+prec")
    out = tmp_path / "Z5"
    out.mkdir()
    (out / "PREREG.md").write_text("# z5\n")
    monkeypatch.setattr(m1, "VERSION", "m1-v2")
    with pytest.raises(Z.Z5Refused, match="hosts changed"):
        Z.check_prereqs("debug", out, flow=tmp_path, env={})


def test_r0_is_g1_r0_decision_for_decision():
    import g1
    ds = ds_of(frames_with({1: deep(), 2: shallow(), 3: deep(300.0)}, n=12))
    n_enter = 0
    for m in ds.mints:
        cd = ds.coin(m)
        assert Z.r0_target_age_s(m, Z.R0_PARAMS) == g1.r0_target_age_s(m, g1.R0_PARAMS)
        for j in range(1, C.N_BARS):
            s = ds.asof(m, cd.bar_start(j) + C.GRID_OFFSET_S)
            a, b = Z.host_r0(s, Z.R0_PARAMS, None), g1.host_r0(s, g1.R0_PARAMS, None)
            assert type(a) is type(b) and a == b
            n_enter += isinstance(a, C.Enter)
    assert n_enter > 0
    ta = C.run_trades(ds, Z.strategy, P("R0"), Z.FILL)
    tb = C.run_trades(ds, g1.host_r0, g1.R0_PARAMS, Z.FILL)
    pd.testing.assert_frame_equal(ta, tb)


# =========================================================================== the veto: an exact subset of the host


def test_strategy_vetoes_expensive_entries_with_skip():
    ds = ds_of(frames_with({1: deep(), 2: shallow()}))
    for i, kept in ((1, True), (2, False)):
        m = mint(i)
        cd = ds.coin(m)
        j = next(j for j in range(1, C.N_BARS)
                 if isinstance(Z.host_r0(ds.asof(m, cd.bar_start(j) + 20), Z.R0_PARAMS, None), C.Enter))
        s = ds.asof(m, cd.bar_start(j) + 20)
        assert isinstance(Z.strategy(s, P("R0"), None), C.Enter)
        act = Z.strategy(s, P("R0", 0.034), None)
        assert (isinstance(act, C.Enter) if kept else act is C.SKIP)
        assert Z.strategy(s, P("R0", 0.030), None) is C.SKIP          # not in the 100-bps tier
        before = ds.asof(m, cd.bar_start(j - 1) + 20)                   # before the host's own decision: untouched
        assert Z.strategy(before, P("R0", 0.034), None) is None


def test_unknown_round_trip_vetoes(monkeypatch):
    ds = ds_of(frames_with({1: deep()}))
    m = mint(1)
    cd = ds.coin(m)
    j = next(j for j in range(1, C.N_BARS)
             if isinstance(Z.host_r0(ds.asof(m, cd.bar_start(j) + 20), Z.R0_PARAMS, None), C.Enter))
    s = ds.asof(m, cd.bar_start(j) + 20)
    monkeypatch.setattr(Z, "round_trip_frac", lambda snap, cost=None: None)
    assert Z.strategy(s, P("R0", 0.034), None) is C.SKIP


@pytest.mark.parametrize("host", ["R0", "M1"])
def test_filtered_trades_are_an_exact_subset_of_the_host(host):
    ds = market("train", T0, 8, 6, 2, 1, m1_bid=True)
    base = C.run_trades(ds, Z.strategy, P(host), Z.FILL)
    assert len(base) >= 8
    rt_b = Z.decision_state(ds, base)["rt_dec"].to_numpy(float)
    assert (rt_b > 0.034).any() and (rt_b <= 0.034).any()
    for c in Z.C_GRID:
        f = C.run_trades(ds, Z.strategy, P(host, c), Z.FILL)
        keep = rt_b <= c
        assert len(f) == int(keep.sum())
        pd.testing.assert_frame_equal(f.reset_index(drop=True), base[keep].reset_index(drop=True), check_dtype=False)
        if len(f):
            assert (Z.decision_state(ds, f)["rt_dec"] <= c).all()
    g = C.run_trades(ds, Z.strategy, P(host, 0.034, True), Z.FILL)
    h = C.run_trades(ds, Z.strategy, P(host, 0.034), Z.FILL)
    assert Z._keys(g) == Z._keys(h)                                   # the guard changes exits only
    assert (g["entry_price"].to_numpy() == h["entry_price"].to_numpy()).all()


def test_guard_sells_a_coin_falling_toward_its_tier_boundary():
    """A deep coin bought at ~1,700 SOL that then bleeds: the guard sells near 1.02 x 1,470 SOL, the host exit later."""
    spec = deep()
    spec["sell"][25:] = 2.0                                     # net -0.9 SOL a minute from minute 25
    ds = ds_of(frames_with({1: spec}, n=4))
    m = mint(1)
    hp = dict(Z.R0_PARAMS)
    cd = ds.coin(m)
    # force an R0 entry at minute 26 through the engine's control path (same exits, no randomness)
    t_dec = cd.bar_start(26) + C.GRID_OFFSET_S
    order = C.Enter(exits=C.ExitSpec(stop_pct=hp["stop_pct"], max_hold_s=hp["max_hold_s"]), tag="R0")
    g = C.run_entries(ds, Z.strategy, P("R0", 0.034, True), Z.FILL, [(m, t_dec, order)])
    h = C.run_entries(ds, Z.strategy, P("R0", 0.034), Z.FILL, [(m, t_dec, order)])
    assert len(g) == len(h) == 1
    gr, hr = g.iloc[0], h.iloc[0]
    G = Z.guard_level(gr["entry_price"] * 1e9, gr["t_in"])
    assert G == 1470.0 and gr["reason"] == "signal:tier_guard"
    assert gr["t_out"] < hr["t_out"]
    assert gr["exit_price"] * 1e9 >= G * 0.98                  # sold around the boundary, not after the fall
    assert gr["fee_bps_out"] <= hr["fee_bps_out"]


# =========================================================================== decomposition (hand-built trades)


def _tr(rows):
    """rows: (mint, t_dec, ret_mid, ret_net, fee_out, reason, entry_mcap, exit_mcap)."""
    out = []
    for m, td, mid, net, fo, rs, mi, mo in rows:
        out.append({"mint": m, "split": "train", "g_ts": 0.0, "t_dec": td, "t_in": td + 30, "t_out": td + 600,
                    "age_in_s": 0.0, "age_dec_s": 0.0, "entry_price": mi / 1e9, "exit_price": mo / 1e9,
                    "mcap_in_sol": mi, "sol_in": 0.2, "sol_out": 0.2, "ret_net": net, "ret_mid": mid,
                    "reason": rs, "tag": "R0", "bars_held": 3, "fee_bps_in": 145.0, "fee_bps_out": fo,
                    "is_placebo": False, "stop_pct": 0.5, "take_profit_pct": None, "trail_pct": None,
                    "max_hold_s": 3600.0, "exit_by_age_s": None})
    return pd.DataFrame(out, columns=list(C.TRADE_COLS))


class _DS:
    """Duck-typed dataset for decision_state: every mint quotes the same pool."""

    def __init__(self, ds, m):
        self._ds, self._m = ds, m

    def asof(self, mint_, t):
        return self._ds.asof(self._m, t)


def test_decompose_is_exact():
    ds = ds_of(frames_with({1: deep()}, n=3))
    cd = ds.coin(mint(1))
    t = [cd.bar_start(40) + 20 + 60 * i for i in range(4)]
    b = _tr([("A", t[0], 0.10, 0.06, 150, "time", 2000, 2000), ("B", t[1], -0.20, -0.24, 155, "time", 500, 400),
             ("C", t[2], 0.00, -0.035, 150, "time", 1800, 1700), ("D", t[3], -0.05, -0.09, 155, "time", 600, 600)])
    f = b.iloc[[0, 2]].reset_index(drop=True)
    d = Z.decompose(_DS(ds, mint(1)), f, b, B=200)
    assert d["subset_of_host"] and d["kept_share"] == 0.5
    gross, net = np.array([0.10, -0.20, 0.0, -0.05]), np.array([0.06, -0.24, -0.035, -0.09])
    cr = 1 - (1 + net) / (1 + gross)
    np.testing.assert_allclose(Z.cost_rate(b), cr)
    assert d["host"]["net"] == pytest.approx(net.mean()) and d["host"]["cost_rate"] == pytest.approx(cr.mean())
    assert d["cost_saving"] == pytest.approx(cr.mean() - cr[[0, 2]].mean())
    assert d["selection"] == pytest.approx(gross[[0, 2]].mean() - gross.mean())
    assert d["net_gain"] == pytest.approx(net[[0, 2]].mean() - net.mean())
    assert d["cost_alone_counterfactual"] == pytest.approx((1 + gross.mean()) * (1 - cr[[0, 2]].mean()) - 1)
    assert d["cost_alone_flips_host"] is False and d["attribution"] == "selection, not cost"
    # a winner pays more in gross - net than a loser at the SAME cost rate: the rate is the unconfounded measure
    w = _tr([("W", t[0], 0.40, 1.40 * 0.97 - 1, 150, "time", 2000, 2800),
             ("L", t[1], -0.30, 0.70 * 0.97 - 1, 150, "time", 2000, 1400)])
    np.testing.assert_allclose(Z.cost_rate(w), [0.03, 0.03])
    assert (w["ret_mid"] - w["ret_net"]).iloc[0] > (w["ret_mid"] - w["ret_net"]).iloc[1]
    assert d["vetoed"]["n"] == 2 and d["vetoed"]["net"] == pytest.approx(np.mean([-0.24, -0.09]))
    assert d["veto_view"]["verdict"] == "UNDERPOWERED"            # < 30 flagged trades
    assert d["ex_ante_rt"]["saving"] == pytest.approx(0.0, abs=0.003)  # same pool quoted at nearby minutes
    assert Z.attribution_label(-0.01, 0.002) == "cost" and Z.attribution_label(0.01, 0.02) == "host already positive"
    assert Z.attribution_label(None, 0.1) is None
    e = Z.decompose(_DS(ds, mint(1)), f.iloc[0:0], b.iloc[0:0])
    assert e == {"n_host": 0, "n_filtered": 0}


def test_guard_pair_is_exact():
    t = [T0 + 1000.0, T0 + 2000.0, T0 + 3000.0]
    h = _tr([("A", t[0], 0.0, -0.04, 155, "time", 1600, 1400), ("B", t[1], 0.1, 0.06, 150, "time", 2000, 2200),
             ("C", t[2], 0.0, -0.04, 150, "time", 1600, 1600)])
    g = _tr([("A", t[0], -0.06, -0.0995, 150, "signal:tier_guard", 1600, 1490),
             ("B", t[1], 0.1, 0.06, 150, "time", 2000, 2200), ("C", t[2], 0.0, -0.04, 150, "time", 1600, 1600)])
    gp = Z.guard_pair(g, h)
    assert gp["n_matched"] == 3 and gp["guard_exit_share"] == pytest.approx(1 / 3)
    assert gp["exit_fee_saving"] == pytest.approx(5 / 1e4 / 3) and gp["exit_fee_saving_when_fired"] == pytest.approx(5e-4)
    assert gp["net_diff"] == pytest.approx((-0.0995 + 0.04) / 3)
    assert gp["guard_sale_at_or_above_boundary"] == 1.0          # sold at 1,490 >= G = 1,470


def test_cluster_stats_removes_the_largest_operator_cluster():
    t = _tr([("A", T0 + 60, 0.5, 0.45, 150, "time", 9e4, 9e4), ("B", T0 + 120, 0.4, 0.35, 150, "time", 9e4, 9e4),
             ("C", T0 + 180, -0.1, -0.13, 150, "time", 500, 450), ("D", T0 + 240, -0.2, -0.23, 150, "time", 500, 400)])
    s = Z.cluster_stats(t, {"A": "op", "B": "op", "C": "c", "D": "d"})
    assert s["n_clusters"] == 3 and s["largest_cluster_trades"] == 2 and s["largest_cluster_share"] == 0.5
    assert s["mean_without_largest_cluster"] == pytest.approx(np.mean([-0.13, -0.23]))
    h = Z.cluster_stats(t, {"A": "op", "B": "op", "C": "c", "D": "d"}, hide=True)
    assert "mean_without_largest_cluster" not in h and h["largest_cluster_trades"] == 2
    single = Z.cluster_stats(t, {})                         # every coin its own cluster: drop the most profitable
    assert single["largest_cluster_trades"] == 1
    assert single["mean_without_largest_cluster"] == pytest.approx(np.mean([0.35, -0.13, -0.23]))
    assert Z.cluster_stats(t.iloc[0:0], {})["mean_without_largest_cluster"] is None
    assert Z.cluster_stats(t, None) == {"n_clusters": None}


# =========================================================================== no lookahead


def _feat(ds: C.Dataset, m: str, t: float) -> tuple:
    s = ds.asof(m, t)
    rt = Z.round_trip_frac(s)
    out = [None if rt is None else round(rt, 12), round(s.mcap_sol, 6) if s.k else None]
    out += [repr(Z.strategy(s, p, None)) for p in Z.GRID]
    if s.k:
        out.append(repr(Z.guard_exit(s, pv(s, entry_price=s.price * 1.3))))
    return tuple(out)


def _mixed_frames(seed: int):
    rng = np.random.default_rng(seed)
    specs = {}
    for i in range(0, 12):
        r = rng.random()
        specs[i] = deep(float(rng.uniform(150, 320)), float(rng.uniform(-0.5, 0.8)), int(rng.integers(1, 5))) \
            if r < 0.6 else shallow(float(rng.uniform(-0.4, 0.2)), int(rng.integers(1, 5)))
    return frames_with(specs, n=12, seed=1)


@pytest.mark.parametrize("seed", range(3))
def test_features_unchanged_by_own_future_garbage(seed):
    frames = _mixed_frames(seed)
    clean = ds_of(frames)
    rng = np.random.default_rng(100 + seed)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = cd.g + float(rng.choice([600, 1800, 2400, 3000, 4500, 6000, 7200])) + float(rng.uniform(0, 59))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        assert _feat(clean, m, t) == _feat(dirty, m, t)


def test_entry_decisions_before_T_unchanged_by_future_garbage():
    frames = _mixed_frames(7)
    clean = ds_of(frames)
    rng = np.random.default_rng(9)
    n_entries = 0
    for i in range(0, 12, 2):
        m = mint(i)
        T = clean.coin(m).g + 80 * 60
        dirty = ds_of(_garble(frames, m, T - C.DECISION_LAG_S, rng))
        for p in Z.GRID:
            a = C.run_trades(clean, Z.strategy, p, Z.FILL, mints=[m])
            b = C.run_trades(dirty, Z.strategy, p, Z.FILL, mints=[m])
            a_dec = a.loc[a["t_dec"] <= T, "t_dec"].tolist()
            assert a_dec == b.loc[b["t_dec"] <= T, "t_dec"].tolist()
            n_entries += len(a_dec)
    assert n_entries > 0


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Z5 features unchanged when the coin's data after tau is garbage: real bars, census TRAIN third (debug)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(17)
    pick = [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=14, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for dt in (float(rng.uniform(600, 1800)), float(rng.uniform(1800, 4500)), float(rng.uniform(4500, 7300))):
            t = cd.g + dt
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
                continue
            assert _feat(clean, m, t) == _feat(dirty, m, t)
            n += 1
    assert len(clean.mints) >= 10 and n >= 25


# =========================================================================== decision rules and predictions


def _ev(p, n=80, coins=80, mean=0.05, mw2=0.04, ci_lo=0.01, pc=0.03, cs=0.0, clusters=40, pc_ci=None, mwc=0.04):
    return {"config": Z.config_key(p), "params_hash": C.params_hash(p), "host": p["host"], "c": p["c"],
            "guard": p["guard"], "n": n, "n_coins": coins, "n_clusters": clusters, "mean": mean,
            "mean_without_top2": mw2, "mean_without_largest_cluster": mwc,
            "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.1), "censored_share": cs,
            "placebo": {"mean_diff": pc, "diff_ci95": pc_ci}}


def _evals(**over):
    """Baselines at -6 %; filtered configs at +5 % unless overridden by config key."""
    ev = {}
    for p in Z.GRID:
        k = Z.config_key(p)
        base = dict(mean=-0.06, mw2=-0.07, ci_lo=-0.1, mwc=-0.06)
        if p["c"] is not None:
            base = {}
        base.update(over.get(k, {}))
        ev[k] = _ev(p, **base)
    return ev


def test_decide_train_qualifiers_pair_and_rank():
    d = Z.decide_train(_evals(**{"R0|c3.00|hx": {"ci_lo": 0.03}, "M1|c3.40|hx": {"ci_lo": 0.03, "mean": 0.20}}))
    assert d["verdict"] == "SHORTLISTED" and d["candidate"] == "M1|c3.40|hx" and d["twin"] == "M1|c-none|hx"
    assert [Z.config_key(p) for p in d["shortlist"]] == ["M1|c-none|hx", "M1|c3.40|hx"]
    d = Z.decide_train(_evals(**{"R0|c3.00|hx": {"ci_lo": 0.03}, "M1|c3.40|hx": {"ci_lo": 0.03}}))
    assert d["candidate"] == "R0|c3.00|hx"                       # tie on CI and mean: grid order
    assert d["shortlist_hashes"] == [C.params_hash(P("R0")), C.params_hash(P("R0", 0.030))]
    for bad in ({"pc": 0.0}, {"mw2": -0.01}, {"mean": -0.01}, {"cs": 0.2}, {"n": 59}, {"coins": 39}, {"pc": None},
                {"mwc": -0.01}, {"mwc": None}):
        assert Z.decide_train(_evals(**{Z.config_key(p): bad for p in Z.GRID if p["c"] is not None}))["verdict"] \
            in ("NO_CONFIG", "UNDERPOWERED_TRAIN")
    # the filter must add: a filtered config below its own host never qualifies
    hi_base = {"R0|c-none|hx": {"mean": 0.08, "mw2": 0.07, "ci_lo": 0.02}, "M1|c-none|hx": {"mean": 0.08}}
    assert Z.decide_train(_evals(**hi_base))["verdict"] == "NO_CONFIG"
    # M1 host needs >= 3 operator clusters to be powered
    only_m1 = {Z.config_key(p): ({"clusters": 2} if p["host"] == "M1" else {"n": 10}) for p in Z.GRID if p["c"]}
    d = Z.decide_train(_evals(**only_m1))
    assert d["verdict"] == "UNDERPOWERED_TRAIN" and not any(r["powered"] for r in d["rows"])
    assert Z.decide_train(_evals(**{Z.config_key(p): {"mean": -0.01} for p in Z.GRID if p["c"]}))["verdict"] \
        == "NO_CONFIG"


def test_decide_val_needs_the_filter_to_beat_its_twin():
    good = {"n": 20, "mean": 0.02, "mean_without_top2": 0.01}
    assert Z.decide_val(good, {"mean": -0.05})["verdict"] == "SELECTED"
    assert Z.decide_val(good, {"mean": 0.03})["verdict"] == "FAIL_VAL"
    assert Z.decide_val({**good, "n": 8}, {"mean": -0.05})["verdict"] == "SELECTED_UNDERPOWERED"
    assert Z.decide_val({**good, "n": 4}, {"mean": -0.05})["verdict"] == "UNDERPOWERED_VAL"
    assert Z.decide_val({**good, "mean_without_top2": -0.01}, None)["verdict"] == "FAIL_VAL"
    assert Z.decide_val({**good, "mean": -0.01}, None)["proceed"] is False


def test_combine_verdict_extras_and_confirm_rule():
    def base(**over):
        crit = [{"id": i, "pass": True} for i in range(1, 11)]
        for i, v in over.items():
            crit[int(i[1:]) - 1]["pass"] = v
        return {"criteria": crit, "auto_rejections": []}
    r0c, r0t = {"host": "R0", "mean": 0.05, "mean_without_largest_cluster": 0.03}, {"mean": -0.04}
    ex = Z.z5_extras(r0c, r0t, {"cost_saving": 0.006, "attribution": "selection, not cost"})
    assert [e["id"] for e in ex] == ["Z5.1", "Z5.2", "Z5.3", "Z5.4"] and ex[0]["pass"] is True
    assert Z.combine_verdict(base(c9=None), ex) == "PASS"
    assert Z.combine_verdict(base(c1=False, c2=False), ex) == "UNDERPOWERED"
    assert Z.combine_verdict(base(c5=False), ex) == "FAIL"
    assert Z.combine_verdict(base(c7=None), ex) == "INCOMPLETE"
    assert Z.combine_verdict(base(c10=False), ex) == "INCOMPLETE"
    assert Z.combine_verdict({**base(), "auto_rejections": ["x"]}, ex) == "REJECTED"
    assert Z.combine_verdict(base(), Z.z5_extras(r0c, {"mean": 0.06}, None)) == "FAIL"        # the filter did not add
    assert Z.combine_verdict(base(), Z.z5_extras(r0c, None, None)) == "INCOMPLETE"             # no twin
    assert Z.combine_verdict(base(), Z.z5_extras({**r0c, "mean_without_largest_cluster": -0.01}, r0t, None)) == "FAIL"
    assert Z.combine_verdict(base(), Z.z5_extras({**r0c, "mean_without_largest_cluster": None}, r0t, None)) \
        == "INCOMPLETE"
    m1c = {"host": "M1", "mean": 0.05, "n_clusters": 2, "mean_without_largest_cluster": 0.02}
    assert Z.combine_verdict(base(), Z.z5_extras(m1c, r0t, None)) == "UNDERPOWERED"
    assert Z.combine_verdict(base(), Z.z5_extras({**m1c, "n_clusters": 3}, r0t, None)) == "PASS"
    doc = {"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": -0.02}}}
    assert not Z.confirm_allowed(doc)[0]
    doc["configs"]["candidate"] = {"n": 3, "mean": -0.02}
    assert Z.confirm_allowed(doc)[0]
    assert not Z.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 3}}})[0]


def test_score_predictions():
    neg = _evals(**{Z.config_key(p): {"mean": -0.05} for p in Z.GRID if p["c"]})
    neg["R0|c-none|hx"]["placebo"]["diff_ci95"] = (-0.02, 0.02)
    dec = {k: {"cost_saving": 0.005, "cost_alone_counterfactual": -0.05,
               "guard_vs_host_exit": {"exit_fee_saving": 0.0003} if k.endswith("guard") else None}
           for k in neg if "c-none" not in k}
    s = Z.score_predictions(neg, dec)
    for key in ("P0_r0_baseline_control_ci_contains_0", "P1_no_filtered_config_mean_net_above_0",
                "P2_cost_saving_below_1.5_points", "P3_cost_alone_flips_no_host",
                "P4_guard_exit_fee_saving_below_0.1_point"):
        assert s[key]["held"] is True, key
    assert set(s["P4_guard_exit_fee_saving_below_0.1_point"]["values"]) == {"R0|c3.40|guard", "M1|c3.40|guard"}
    pos = dict(neg, **{"R0|c3.40|hx": _ev(P("R0", 0.034), mean=0.02)})
    dec2 = dict(dec, **{"R0|c3.40|hx": {"cost_saving": 0.02, "cost_alone_counterfactual": 0.01}})
    s = Z.score_predictions(pos, dec2)
    assert not s["P1_no_filtered_config_mean_net_above_0"]["held"]
    assert not s["P2_cost_saving_below_1.5_points"]["held"] and not s["P3_cost_alone_flips_no_host"]["held"]


# =========================================================================== the host-first rule


def _write(d, name, doc):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(doc))


def test_m1_blocker_host_first_rule(tmp_path):
    m1o, led = tmp_path / "M1", tmp_path / "trials.json"
    assert "not finished TRAIN" in Z.m1_blocker("val", led, m1o)
    _write(m1o, "train.json", {"provisional": True})
    assert "not finished TRAIN" in Z.m1_blocker("test", led, m1o)
    _write(m1o, "train.json", {"decision": {"verdict": "UNDERPOWERED_TRAIN"}})
    for st in ("val", "test", "confirm", "final"):
        assert Z.m1_blocker(st, led, m1o) is None                # M1 stopped at TRAIN: nothing to protect
    _write(m1o, "train.json", {"decision": {"verdict": "SHORTLISTED"}})
    assert "VAL" in Z.m1_blocker("val", led, m1o) and "VAL" in Z.m1_blocker("test", led, m1o)
    _write(m1o, "val.json", {"decision": {"verdict": "FAIL_VAL"}})
    assert Z.m1_blocker("test", led, m1o) is None and Z.m1_blocker("final", led, m1o) is None
    _write(m1o, "val.json", {"decision": {"verdict": "SELECTED"}})
    assert "TEST" in Z.m1_blocker("test", led, m1o) and "TEST" in Z.m1_blocker("confirm", led, m1o)
    _write(m1o, "test.json", {"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 40, "mean": -0.05}}})
    assert Z.m1_blocker("confirm", led, m1o) is None              # M1 will never spend CONFIRM
    assert "FINAL" in Z.m1_blocker("final", led, m1o)             # but M1 still runs FINAL after TEST
    with C._ledger(led) as L:                                     # M1 had its FINAL look: Z5 may follow
        L.setdefault("one_shot_sessions", []).append({"family": "M1", "split_group": "final", "split": "final",
                                                      "session": "s", "opened_utc": "x"})
    assert Z.m1_blocker("final", led, m1o) is None


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Z5", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists", m1=tmp_path / "M1")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Z5 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, **kw):
    return Z.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, m1_out=d.m1, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Z.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {},
                           m1_out=d.m1, **kw)


def test_train_no_config_when_the_cheap_coins_fall(st):
    doc = _run("train", st, market("train", T0, 66, 24, 4, 1, deep_drift=-0.5, deep_x=260.0))
    assert doc["decision"]["verdict"] == "NO_CONFIG" and not doc["decision"]["shortlist_written"]
    assert doc["overall"].startswith("NO EDGE")
    assert set(doc["configs"]) == {Z.config_key(p) for p in Z.GRID}
    r = doc["configs"]["R0|c3.40|hx"]
    assert r["n"] >= 60 and r["mean"] < 0 and r["n_placebo"] > 0 and r["censored_share"] == 0.0
    assert set(doc["decomposition"]) == {Z.config_key(p) for p in Z.GRID if p["c"] is not None}
    dc = doc["decomposition"]["R0|c3.40|hx"]
    assert dc["subset_of_host"] and 0 < dc["kept_share"] < 1 and dc["cost_saving"] > 0
    assert dc["ex_ante_rt"]["saving"] > 0
    assert doc["decomposition"]["R0|c3.40|guard"]["guard_vs_host_exit"]["n_matched"] == r["n"]
    assert doc["configs"]["M1|c-none|hx"]["n"] == 0                 # 4 buyers a minute: no MECH-bar bid
    assert doc["predictions"]["P1_no_filtered_config_mean_net_above_0"]["held"]
    assert not (st.sl / "Z5.json").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z5") == 8
    assert led["n_trials_total"] == 2575 + 8
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(Z.Z5Refused, match="NO_CONFIG"):
            _check(stage, st, env=ENV_ALL)
    with pytest.raises(Z.Z5Refused, match="final"):
        _run("train", st, market("train", T0, 66, 24, 4, 1, deep_drift=-0.5, deep_x=260.0))
    assert "Decomposition" in (st.out / "train.md").read_text()


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", T0, 20, 6, 2, 1)
    with pytest.raises(Z.Z5Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Z5.json").exists()
    with pytest.raises(Z.Z5Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    for k in ENV_ALL:            # common enforces the real env flags; z5's ``env=`` drives z5's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(Z.Z5Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: the grid, the decomposition, the pair shortlist
    tr = _run("train", st, market("train", T0, 66, 24, 4, 1))
    d = tr["decision"]
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_written"] and d["candidate"].startswith("R0|c3.")
    assert d["twin"] == "R0|c-none|hx"
    dc = tr["decomposition"][d["candidate"]]
    assert dc["net_gain"] > 0 and dc["selection"] > 0 and dc["cost_saving"] > 0 and dc["subset_of_host"]
    assert (st.out / "prereg.lock").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Z5") == 8
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Z.Z5Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Z5 test prereg\n")
    for stage in ("test", "confirm", "final"):
        with pytest.raises(Z.Z5Refused, match="no VAL result"):
            _check(stage, st, env=ENV_ALL)
    # ---- VAL: the pair once
    va = _run("val", st, market("val", C.utc_ts("2026-10-05 02:00"), 20, 8, 2, 2))
    assert set(va["configs"]) == {"candidate", "twin"}
    assert va["decision"]["verdict"] == "SELECTED" and va["decision"]["twin_mean"] < va["decision"]["mean"]
    assert set(va["decomposition"]) == {"candidate"}
    with pytest.raises(Z.Z5Refused, match="VAL already ran"):
        _check("val", st)
    with pytest.raises(Z.Z5Refused, match="before TEST"):
        _check("confirm", st, env=ENV_ALL)
    # ---- TEST: locked without the judge's flag, then once
    ds_test = market("test", C.utc_ts("2026-10-06 13:00"), 30, 8, 2, 3)
    with pytest.raises(Z.Z5Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=ENV_ALL)
    assert set(te["configs"]) == {"candidate", "twin"}
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                       # < 60 trades: never PASS / FAIL
    assert [e["id"] for e in te["verdict"]["z5_extras"]] == ["Z5.1", "Z5.2", "Z5.3", "Z5.4"]
    with pytest.raises(Z.Z5Refused, match="already ran"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Z.Z5Refused, match="one test run"):
        _check("test", st, env=ENV_ALL)                                     # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", C.utc_ts("2026-09-20 00:00"), 70, 18, 4, 4), env=ENV_ALL)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 12, 6, 2, 5), env=ENV_ALL)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True and "twin_judged" in fi["decision"]
    assert fi["overall"].startswith("EDGE (")
    with pytest.raises(Z.Z5Refused, match="already ran"):
        _check("final", st, env=ENV_ALL)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name
    assert json.loads(st.ledger.read_text())["n_trials_total"] == 2575 + 8   # the whole life of Z5: 8 trials


def test_m1_candidate_obeys_the_host_first_rule(st):
    """A shortlist whose candidate is the M1 host: VAL refuses until M1 had its own VAL look (or stopped)."""
    (st.out / "train.json").write_text(json.dumps({"stage": "train", "decision": {
        "verdict": "SHORTLISTED", "shortlist_hashes": [C.params_hash(P("M1")), C.params_hash(P("M1", 0.034))]}}))
    C.write_shortlist("Z5", [P("M1"), P("M1", 0.034)], path=st.sl, ledger_path=st.ledger)
    with pytest.raises(Z.Z5Refused, match="host-first"):
        _check("val", st)
    _write(st.m1, "train.json", {"decision": {"verdict": "SHORTLISTED"}})
    with pytest.raises(Z.Z5Refused, match="host-first"):
        _check("val", st)
    _write(st.m1, "train.json", {"decision": {"verdict": "NO_CONFIG"}})
    assert _check("val", st)["stage"] == "val"


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Z.Z5Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Z.Z5Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", T0, 20, 8, 2, 1, m1_bid=True)
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Z.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2,
                      env={})
    assert doc["decision"]["verdict"] == "DEBUG" and "decomposition" not in doc and "predictions" not in doc
    for e in doc["configs"].values():
        assert e["returns"].startswith("hidden")
        for k in ("mean", "ci90", "placebo", "controls", "stress", "portfolio", "reasons", "by_tag",
                  "cost_decomposition"):
            assert k not in e
        assert "decision_rt" in e and "n_controls" in e and "largest_cluster_trades" in e
        assert "mean_without_largest_cluster" not in e
    ec = doc["event_counts"]
    assert set(ec) == {"R0", "M1"}
    for h, e in ec.items():
        assert e["host_entries"] > 0, h
        for v in e["by_c"].values():
            assert v["subset_of_host"] is True and v["filtered_trades"] == v["quoted_kept"]
        assert e["guard_same_entries"] is True
    txt = json.dumps(doc)
    for word in ("ret_net", "ret_mid", "exit_price", "mean_diff", "tier_guard\""):
        assert word not in txt
    assert not list(st.out.glob("*_trades.csv"))
    assert not st.ledger.exists() or json.loads(st.ledger.read_text())["n_trials_total"] == 2575

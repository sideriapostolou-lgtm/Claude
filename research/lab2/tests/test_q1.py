"""Tests for research/lab2/q1.py: early-buyer lists (AGENT / pooled / suspect-PDA removal), the RUG label, the causal
registry (strictly past, resolved, never the traded mint), the ubiquity filter, k and the veto, the batch view table
against the scalar rule, R0 decisions against the engine, no lookahead (synthetic and real census bars: garbage after T
and rewritten not-yet-known lists change no answer at tau <= T), the label-permuted placebo, the kill gate, every
pre-registered decision rule, and the stages end to end (a dump-cluster market that the veto must catch, a null
market the kill gate must kill) with every refusal."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import g1 as G1
import q1 as Q
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=300.0)
T0 = C.utc_ts("2026-10-02 00:00")
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
DROP = math.log(0.15) / 30.0          # a RUG coin loses 85 % over the 30-bar label window
ENV_ALL = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
P_N3 = Q.make_params("w300", 3, 0.6, 1)


# =========================================================================== synthetic markets


def market_frames(coins: list[dict], seed: int = 0):
    """Graduates / b2_coins / b2_bars for hand-specified coins: {g, w300 [(wallet, buy)] or None (NULL list), w120
    (default: the first 4 of w300), agent (wallet, optional), phases [(start minute, per-minute log drift)]}. Prices
    move along X * y = k with a bar in every minute and constant volume (alive at SOL $300)."""
    g0, c0, _ = make_frames(n=1, seed=seed, slow_every=0, agent_every=0)
    tg, tc = g0.iloc[0].to_dict(), c0.iloc[0].to_dict()
    grads, cs, bars = [], [], []
    k = X0 * Y0
    for i, s in enumerate(coins):
        mint, pool = f"Q{i:04d}{seed}pump", f"QP{i:04d}{seed}"
        g = int(s["g"])
        r = dict(tg)
        r.update(mint=mint, pool=pool, g_ts=g, g_slot=10_000 + i, pool_ts=g + 2, pool_slot=10_001 + i, has_create=1,
                 c_ts=g - 3, c_slot=9_000 + i, creator=f"CR{i}", create_user=f"CR{i}", name=f"N{i}", symbol=f"S{i}",
                 grad_delay_s=3.0)
        grads.append(r)
        w300 = s.get("w300")
        w120 = s.get("w120", None if w300 is None else w300[:4])
        enc = (lambda lst: None if lst is None else json.dumps([[w, float(b), 0.0] for w, b in lst]))
        ag = s.get("agent")
        cc = dict(tc)
        cc.update(mint=mint, pool=pool, g_ts=g, w300_top10=enc(w300), w120_top10=enc(w120),
                  agent_present=bool(ag), agent_wallet=ag or "", agent_known_at=float(g + 40) if ag else math.nan,
                  agent_first_offset_s=2.0 if ag else math.nan)
        cs.append(cc)
        phases = sorted(s.get("phases") or [(0, 0.0)])
        m0 = g // 60 * 60
        lp = math.log(X0 / Y0)
        for j in range(N_MIN):
            lp0 = lp
            lp += [d for st, d in phases if st <= j][-1]
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
    return f"Q{i:04d}{seed}pump"


RUG = [(0, 0.0), (7, DROP), (38, -0.004)]       # rugs in its label window, keeps bleeding after
RUG_THEN_UP = [(0, 0.0), (7, DROP), (38, 0.002)]  # rugs, then behaves like a clean coin (null market)
CLEAN = [(0, 0.0), (38, 0.002)]


def dump_market(t0: int, n: int, prefix: str = "A", spacing: int = 360, pool: int = 36, null: bool = False,
                dw: str = "DW", sw: str = "SW") -> list[dict]:
    """Alternating cluster / clean coins. Cluster coin c carries dump wallets DW[3c..3c+2 mod pool] (they rug in the
    label window and, unless ``null``, keep falling); clean coin c carries reused wallets SW[3c..3c+2 mod pool] (never
    rug, rise). Every coin also carries its own unique wallets and the BUSY wallet (in every list: ubiquitous). Each
    DW / SW wallet sits in 1 list per 12 coins of its type (< 5 % of the trailing day's lists)."""
    out = []
    for i in range(n):
        c = i // 2
        cluster = i % 2 == 0
        base = dw if cluster else sw
        rot = [f"{base}{(3 * c + j) % pool}" for j in range(3)]
        lst = [(rot[0], 6.0), (rot[1], 5.0), (rot[2], 4.0), (f"{prefix}U{i}a", 2.0), ("BUSY", 1.5), (f"{prefix}U{i}b", 1.0)]
        out.append({"g": t0 + i * spacing + (i * 7) % 50, "w300": lst,
                    "phases": (RUG_THEN_UP if null else RUG) if cluster else CLEAN, "cluster": cluster})
    return out


# =========================================================================== grid and constants


def test_grid_is_preregistered_and_small():
    assert len(Q.GRID_W300) == 8
    keys = [Q.config_key(p) for p in Q.GRID_W300]
    assert len(set(keys)) == 8 and len({C.params_hash(p) for p in Q.GRID_W300}) == 8
    assert keys[0] == "w300|N3|D0.6|K1" and keys[-1] == "w300|N5|D0.8|K3"
    for p in Q.GRID_W300:
        for k, v in Q.FIXED.items():
            assert p[k] == v
    # 8 w300 + 1 w120 + host + gate = 11 ledger trials <= 12
    assert len(Q.GRID_W300) + 1 + 1 + 1 == 11
    assert Q.HISTORY_SPLITS["train"] == ("train",)
    assert "confirm" not in Q.HISTORY_SPLITS["val"] + Q.HISTORY_SPLITS["test"] + Q.HISTORY_SPLITS["final"]
    assert Q.FILL.exit_delay_bars == 1 and Q.FILL.entry_fill == "worst" and Q.FILL.exit_fill == "worst"
    assert C.params_hash(G1.R0_PARAMS) == Q.R0_PIN and not Q.host_pin_problems()
    assert Q.FIXED["host_params_hash"] == C.params_hash(Q.R0_PARAMS)
    assert (Q.GATE_WINDOW, Q.GATE_N, Q.GATE_D) == ("w300", min(Q.N_GRID), min(Q.D_GRID))
    with pytest.raises(ValueError):
        Q.make_params("w300", 4, 0.6, 1)
    with pytest.raises(ValueError):
        Q.make_params("w60", 3, 0.6, 1)


def test_pin_change_refuses(tmp_path, monkeypatch):
    out = tmp_path / "Q1"
    out.mkdir()
    (out / "PREREG.md").write_text("# test\n")
    monkeypatch.setattr(G1, "R0_PARAMS", {**G1.R0_PARAMS, "stop_pct": 0.4})
    with pytest.raises(Q.Q1Refused, match="R0 host changed"):
        Q.check_prereqs("debug", out)


# =========================================================================== lists, labels, registry


def test_appearance_list_removes_agent_pooled_pda_and_non_buyers():
    lst = [("AGX", 9.0), (next(iter(C.POOLED_ACCOUNTS)), 8.0),
           (next(iter(C.SUSPECT_PDA_ACCOUNTS)), 7.0), ("W1", 5.0), ("W2", 0.0), ("W1", 1.0), ("W3", 2.0)]
    fr = market_frames([{"g": T0, "w300": lst, "agent": "AGX"}, {"g": T0 + 60, "w300": None}])
    ds = ds_of(fr)
    m = mint_of(0)
    cd = ds.coin(m)
    assert Q.appearance_list(ds.asof(m, cd.g + 200), "w300") is None            # list not legal yet (g + 300)
    assert Q.appearance_list(ds.asof(m, cd.g + 330), "w300") == ("W1", "W3")    # AGENT known at g + 40: removed
    assert Q.appearance_list(ds.asof(m, cd.g + 330), "w120") == ("W1",)          # w120 = first 4 entries
    assert Q.appearance_list(ds.asof(mint_of(1), cd.g + 3600), "w300") is None  # NULL list stays NULL
    row = Q.structure_row(cd, SOL)
    assert row["w300"] == ("W1", "W3") and row["g"] == cd.g


def test_rug_label_window_and_threshold():
    fr = market_frames([{"g": T0, "w300": [("A", 1.0)], "phases": RUG},
                        {"g": T0 + 47, "w300": [("A", 1.0)], "phases": [(0, 0.0), (7, math.log(0.5) / 30)]}])
    ds = ds_of(fr)
    for i in (0, 1):
        m = mint_of(i)
        cd = ds.coin(m)
        lab = Q.rug_label(ds, m)
        assert lab.t_ref >= cd.g + Q.REF_AGE_S and lab.t_ref - 60 < cd.g + Q.REF_AGE_S
        assert (lab.t_ref - C.GRID_OFFSET_S - cd.m0) % 60 == 0
        assert lab.t_lab == lab.t_ref + Q.RUG_H_S + C.DECISION_LAG_S
        assert lab.ret == pytest.approx(ds.asof(m, lab.t_lab).price / ds.asof(m, lab.t_ref).price - 1)
    assert Q.rug_label(ds, mint_of(0)).rug is True and Q.rug_label(ds, mint_of(0)).ret == pytest.approx(-0.85, abs=1e-9)
    assert Q.rug_label(ds, mint_of(1)).rug is False                              # -50 % is not a rug


def test_registry_entries_are_strictly_past_resolved_and_never_the_traded_mint():
    coins = [{"g": T0, "w300": [("X", 3.0), ("Y", 1.0)], "phases": RUG},          # 0 rug
             {"g": T0 + 600, "w300": [("X", 3.0)], "phases": CLEAN},              # 1 no rug
             {"g": T0 + 5000, "w300": [("X", 3.0)], "phases": RUG},               # 2 the coin decided
             {"g": T0 + 5600, "w300": [("X", 3.0)], "phases": RUG}]               # 3 graduates after 2
    fr = market_frames(coins)
    ds = ds_of(fr)
    reg = Q.build_registry([ds])
    labs = {i: Q.rug_label(ds, mint_of(i)) for i in range(4)}
    g2 = ds.coin(mint_of(2)).g
    # before coin 0's label window closed: nothing usable
    assert reg.record("X", "w300", labs[0].t_lab - 60, g2, mint_of(2)) == (0, None)
    n, d = reg.record("X", "w300", labs[0].t_lab, g2, mint_of(2))
    assert (n, d) == (1, 1.0)
    # later: coins 0 and 1 (d = 0.5); coin 2 itself never; coin 3 (graduated after 2) never, even once resolved
    t_late = labs[3].t_lab + 600
    assert reg.record("X", "w300", t_late, g2, mint_of(2)) == (2, 0.5)
    assert reg.record("X", "w300", t_late, ds.coin(mint_of(3)).g + 1, "other") == (4, 0.75)
    assert reg.record("Y", "w300", t_late, g2, mint_of(2)) == (1, 1.0)
    assert reg.record("Z", "w300", t_late, g2, mint_of(2)) == (0, None)
    st = reg.stats()
    assert st["labelled_coins"] == 4 and st["w300"]["wallets"] == 2 and st["w300"]["entries"] == 5
    assert "rug" not in json.dumps(st)


def test_ubiquity_share_floor_lookback_and_own_coin():
    rows = [{"mint": f"m{i}", "g": float(T0 + 100 * i), "w300": ("BUSY", f"u{i}") + (("TWO",) if i in (3, 7) else ()),
             "w120": None} for i in range(40)]
    rows.append({"mint": "old", "g": float(T0 - 2 * 86400), "w300": ("OLD",), "w120": None})
    u = Q.Ubiquity.from_rows(rows)
    tau = T0 + 100 * 39 + Q.LIST_KNOWN_S
    assert u.n_lists("w300", tau) == 40 and u.n_lists("w120", tau) == 0
    assert u.ubiquitous(["BUSY", "u5", "TWO", "OLD", "nobody"], "w300", tau) == {"BUSY", "TWO"}   # 2 >= 5 % of 40
    # the coin itself is left out of the count and the denominator: TWO in 2 lists, one of them the own coin
    assert u.n_lists("w300", tau, "m7") == 39
    assert u.ubiquitous(["TWO"], "w300", tau, "m7") == set()
    # a list counts only from g + 420 s: at tau just below that, the last coin's list is not known yet
    assert u.n_lists("w300", tau - 1) == 39
    # 24 h lookback: OLD is out of the window
    assert u.ubiquitous(["OLD"], "w300", T0 - 2 * 86400 + 1000) == set()      # one list only: floor of 2


def test_k_veto_and_view_table_agree():
    fr = market_frames(dump_market(T0, 120))
    ds = ds_of(fr)
    reg = Q.build_registry([ds])
    rows = Q.r0_decisions(ds)
    vt = Q.build_views(ds, reg, rows)
    rng = np.random.default_rng(3)
    for y in (reg.y, rng.integers(0, 2, len(reg.y)).astype(float)):
        for p in Q.GRID_W300 + [Q.make_params("w120", 3, 0.6, 1)]:
            k_batch = vt.k(p["window"], y, p["n_min"], p["d_min"])
            for i, (m, t) in enumerate(rows):
                view = Q.coin_view(ds.asof(m, t), reg, p["window"])
                assert Q.k_of_view(view, y, p["n_min"], p["d_min"]) == int(k_batch[i])
                assert Q.veto_fires(ds.asof(m, t), reg, p, y) == bool(vt.flags(p, y)[i])
    # BUSY is in every list: always removed by the ubiquity filter (>= 2 lists and >= 5 % of them)
    assert all(vt.n_ubiq["w300"][i] >= 1 for i in range(len(rows)))
    # a dump wallet sits in 1 cluster coin of 12: from cluster coin 36 (coin 72) on it has 3 resolved earlier rugs, so
    # the coin carries k = 3 dump wallets; before that k = 0; clean coins (reused SW wallets, never rug) k = 0
    k = vt.k("w300", reg.y, 3, 0.6)
    idx = [int(m[1:5]) for m, _ in rows]
    assert all(k[r] == (3 if (i % 2 == 0 and i >= 72) else 0) for r, i in enumerate(idx))
    assert sum(1 for i in idx if i % 2 == 0 and i >= 72) >= 20


def test_null_list_never_fires():
    coins = [{"g": T0 + 600 * i, "w300": [("D", 2.0)], "phases": RUG} for i in range(5)]
    coins.append({"g": T0 + 3600, "w300": None, "phases": RUG})
    ds = ds_of(market_frames(coins))
    reg = Q.build_registry([ds])
    m = mint_of(5)
    snap = ds.asof(m, ds.coin(m).g + 100 * 60 + 20)
    assert Q.coin_view(snap, reg, "w300")["known"] is False
    assert Q.k_of_view(Q.coin_view(snap, reg, "w300"), reg.y, 3, 0.6) is None and not Q.veto_fires(snap, reg, P_N3)
    vt = Q.build_views(ds, reg, [(m, snap.t)])
    assert np.isnan(vt.k("w300", reg.y, 3, 0.6)[0]) and not vt.flags(P_N3, reg.y)[0]


def test_permuted_labels_stay_inside_6h_blocks():
    ds = ds_of(market_frames(dump_market(T0, 120)))
    reg = Q.build_registry([ds])
    p0, p1 = reg.permuted_labels(0), reg.permuted_labels(1)
    for b in np.unique(reg.block):
        ix = reg.block == b
        assert p0[ix].sum() == reg.y[ix].sum() and p1[ix].sum() == reg.y[ix].sum()
    assert not np.array_equal(p0, reg.y) and not np.array_equal(p0, p1)
    assert np.array_equal(reg.permuted_labels(0), p0)


# =========================================================================== host


def test_r0_decisions_match_the_engine_and_the_deadline_is_registered():
    ds = ds_of(market_frames(dump_market(T0, 60)))
    dec = Q.r0_decisions(ds)
    t = C.run_trades(ds, Q.host_r0, Q.R0_PARAMS, Q.FILL)
    assert [(m, float(x)) for m, x in zip(t["mint"], t["t_dec"])] == dec and len(dec) > 40
    assert (t["exit_by_age_s"] == Q.EXIT_BY_AGE_S).all() and (t["stop_pct"] == 0.5).all()
    assert (t["max_hold_s"] == 3600).all() and (t["reason"] != "horizon").all()
    m, x = dec[0]
    snap = ds.asof(m, x)
    assert snap.age_s >= G1.r0_target_age_s(m, Q.R0_PARAMS) and snap.age_s - 60 < G1.r0_target_age_s(m, Q.R0_PARAMS)
    assert G1.host_r0(snap, Q.R0_PARAMS, None).exits.exit_by_age_s is None   # g1's own host is unchanged


# =========================================================================== no lookahead


def _answers(ds, reg, rows):
    vt = Q.build_views(ds, reg, rows)
    out = {}
    for i, (m, t) in enumerate(rows):
        for w in Q.WINDOWS:
            v = Q.coin_view(ds.asof(m, t), reg, w)
            out[(m, w, "L")] = (v["known"], tuple(v["wallets"]), v["n_ubiq"], tuple(len(ix) for ix in v["idx"]))
        for p in Q.GRID_W300 + [Q.make_params("w120", 5, 0.8, 3)]:
            out[(m, Q.config_key(p))] = (float(vt.k(p["window"], reg.y, p["n_min"], p["d_min"])[i]),
                                         bool(vt.flags(p, reg.y)[i]))
    return out


def _poison_future(frames, T):
    """Adversarial garbage on top of ``_garble``: every price after tau = T - 20 crashes to ~0 (so every label whose
    window is still open at T becomes a RUG: clean coins' reused wallets would turn into dump wallets), and every list
    not yet known at tau (g + 420 > tau) is rewritten to hold every dump and reused wallet (so a count that read those
    lists would make them ubiquitous)."""
    g, c, b = (x.copy() for x in frames)
    tau = T - C.DECISION_LAG_S
    fut = b["minute_ts"] + 60 > tau
    for col in ("open", "high", "low", "close"):
        b.loc[fut, col] = 1e-12
    gts = dict(zip(g["mint"], g["g_ts"]))
    unknown = c["mint"].map(lambda m: gts[m] + Q.LIST_KNOWN_S > tau)
    big = json.dumps([[f"{p}{j}", 9.0, 0.0] for p in ("DW", "SW") for j in range(36)] + [["BUSY", 8.0, 0.0]])
    for col in ("w300_top10", "w120_top10"):
        c.loc[unknown, col] = big
    return g, c, b


@pytest.mark.parametrize("seed", range(3))
def test_registry_and_vetoes_unchanged_by_future_garbage(seed):
    rng = np.random.default_rng(seed)
    frames = market_frames(dump_market(T0, 100), seed=seed)
    clean = ds_of(frames)
    reg_c = Q.build_registry([clean])
    T = T0 + int(rng.integers(9.5 * 3600, 11.5 * 3600))
    rows = [(m, t) for m, t in Q.r0_decisions(clean) if t <= T]
    dirty = frames
    for m in clean.mints:
        dirty = _garble(dirty, m, T - C.DECISION_LAG_S, rng)
    dirty = _poison_future(dirty, T)
    dds = ds_of(dirty)
    assert set(dds.mints) == set(clean.mints)
    reg_d = Q.build_registry([dds])
    a, d = _answers(clean, reg_c, rows), _answers(dds, reg_d, rows)
    assert a == d
    assert sum(1 for k, v in a.items() if len(k) == 2 and v[1]) > 0           # some vetoes fire before T
    # labels resolved by T are identical; later ones may differ (they are never read before T)
    lc = {m: Q.rug_label(clean, m) for m in clean.mints}
    ld = {m: Q.rug_label(dds, m) for m in dds.mints}
    for m, lab in lc.items():
        if lab is not None and lab.t_lab <= T:
            assert ld[m] is not None and ld[m].rug == lab.rug and ld[m].ret == pytest.approx(lab.ret)


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """k / L / ubiquity answers for real census-TRAIN-third coins at their R0 decisions are unchanged when every
    coin's data after T is garbage (debug third: no outcome is printed)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=C.load_sol_usd())
    pick = list(full.mints[: min(160, len(full))])
    if len(pick) < 20:
        pytest.skip("too few census coins in this snapshot")
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    sol = C.load_sol_usd()
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=sol)
    rows_s = Q.structure_rows_from_frames(sub[0], sub[1], cen, -math.inf, math.inf)
    reg_c = Q.build_registry([clean], rows_s)
    rng = np.random.default_rng(5)
    gs = sorted(clean.coins["g_ts"])
    n_checked = 0
    for T in (gs[len(gs) // 2] + 2500.0, gs[-1] + 1000.0):
        rows = [(m, t) for m, t in Q.r0_decisions(clean) if t <= T]
        dirty = sub
        for m in clean.mints:
            dirty = _garble(dirty, m, T - C.DECISION_LAG_S, rng)
        dirty = _poison_future(dirty, T)
        dds = C.Dataset.from_frames("final_train", *dirty, census=cen, sol=sol)
        rows = [(m, t) for m, t in rows if m in dds.mints]
        rows_d = Q.structure_rows_from_frames(dirty[0], dirty[1], cen, -math.inf, math.inf)
        reg_d = Q.build_registry([dds], rows_d)
        assert _answers(clean, reg_c, rows) == _answers(dds, reg_d, rows)
        n_checked += len(rows)
    assert n_checked > 0


# =========================================================================== statistics, gate, decisions


def _host(nf, nu, f_ret, u_ret, seed=0, key="w300|N3|D0.6|K1", win_frac=0.0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(nf + nu):
        fl = i < nf
        r = (f_ret if fl else u_ret) + rng.normal(0, 0.02)
        rows.append({"mint": f"m{seed}_{i}", "ret_net": r, f"flag_{key}": fl, "known_w300": True,
                     "warmup": i % 10 == 0, "g1_class": "ORGANIC" if i % 3 else "FACTORY", "t_in": T0 + 60 * i})
    return pd.DataFrame(rows)


def test_boot_diff_and_perm_stats():
    r = np.array([-0.3] * 20 + [0.1] * 20)
    a = np.array([True] * 20 + [False] * 20)
    d, ci = Q.boot_diff(r, [f"c{i}" for i in range(40)], a, ~a, 0.9, 500)
    assert d == pytest.approx(-0.4) and ci[1] < 0
    assert Q.boot_diff(r, ["c"] * 40, a, ~a)[1] is None
    perms = [np.roll(a, s) for s in range(1, 21)]
    ps = Q.perm_stats(r, d, perms)
    assert ps["n_valid"] == 20 and ps["mean_gap"] > d + 0.05 and ps["pass"] is True
    same = Q.perm_stats(r, d, [a] * 20)
    assert same["pass"] is False and same["share_le_real"] == 1.0
    assert Q.perm_stats(r, d, [np.zeros(40, bool)])["pass"] is False          # no valid permutation
    assert Q.perm_stats(r, None, perms)["pass"] is None


def test_veto_eval_hides_on_debug_and_reports_everything_else():
    t = _host(40, 40, -0.3, 0.05)
    key = "w300|N3|D0.6|K1"
    h = Q.veto_eval(t, key, B=200, hide=True)
    assert h["n_flagged"] == 40 and "verdict" not in h and "flagged_mean" not in h and "gap" not in h
    perms = [np.random.default_rng(s).permutation(t[f"flag_{key}"].to_numpy()) for s in range(20)]
    v = Q.veto_eval(t, key, B=500, hide=False, perms=perms, oos=_host(20, 20, -0.3, 0.05, 1))
    assert v["verdict"]["verdict"] == "PASS" and v["perm"]["pass"] is True and v["gap"] < -0.3
    assert v["ci95"][1] < 0 and v["random_veto"]["p_le_real"] == 0.0 and v["organic"]["n_flagged"] > 0
    assert set(v["by_class"]) == {"ORGANIC", "FACTORY"} and v["without_warmup"]["n"] == 72
    assert v["oos"]["n_flagged"] == 20
    conf = Q.veto_eval(t, key, B=500, hide=False, oos_is_self=True)
    assert {c["id"] for c in conf["verdict"]["criteria"]} == {1, 2, 3}
    assert Q.veto_eval(_host(10, 40, -0.3, 0.05), key, B=200, hide=False)["verdict"]["verdict"] == "UNDERPOWERED"
    assert Q.veto_eval(_host(40, 40, 0.3, 0.05), key, B=200, hide=False)["verdict"]["verdict"] == "FAIL"


def _obs(n1, n0, d1, d0, seed=0):
    rng = np.random.default_rng(seed)
    rows = [{"mint": f"a{i}", "t_dec": T0 + i, "k": 1 + i % 4, "bucket": "1-2" if 1 + i % 4 <= 2 else ">=3",
             "fwd60": d1 + rng.normal(0, 0.03), "warmup": i < 5, "g1_class": "ORGANIC"} for i in range(n1)]
    rows += [{"mint": f"b{i}", "t_dec": T0 + i, "k": 0, "bucket": "0", "fwd60": d0 + rng.normal(0, 0.03),
              "warmup": i < 5, "g1_class": "OPERATOR"} for i in range(n0)]
    return pd.DataFrame(rows)


def test_gate_decision():
    assert Q.gate_decision(_obs(40, 60, -0.2, 0.0), B=500)["decision"] == "PASS"
    assert Q.gate_decision(_obs(40, 60, -0.02, 0.0), B=500)["decision"] == "KILL"   # not 5 points worse
    assert Q.gate_decision(_obs(40, 60, 0.1, 0.0), B=500)["decision"] == "KILL"
    assert Q.gate_decision(_obs(29, 60, -0.2, 0.0), B=500)["decision"] == "UNDERPOWERED"
    assert Q.gate_decision(_obs(40, 29, -0.2, 0.0), B=500)["decision"] == "UNDERPOWERED"
    h = Q.gate_decision(_obs(40, 60, -0.2, 0.0), B=500, hide=True)
    assert h["decision"].startswith("HIDDEN") and "delta" not in h and "diagnostics" not in h
    assert h["buckets"] == {"0": 60, "1-2": 20, ">=3": 20}
    d = Q.gate_decision(_obs(40, 60, -0.2, 0.0), B=500)
    assert set(d["diagnostics"]["mean_by_bucket"]) == {"0", "1-2", ">=3"}
    assert d["diagnostics"]["delta_by_class"]["ORGANIC"] is None             # one bucket only in that class


def _row(key, nf=40, nu=40, ci_hi=-0.2, c1=True, c3=True, perm=True):
    return {"config": key, "powered": nf >= 30 and nu >= 30, "n_flagged": nf, "n_unflagged": nu, "gap": -0.3,
            "ci95_hi": ci_hi, "crit1": c1, "crit3": c3, "perm_ok": perm, "perm_mean_gap": 0.0,
            "qualifies": bool(nf >= 30 and nu >= 30 and c1 and c3 and perm)}


def test_train_best_and_decide_train():
    keys = [Q.config_key(p) for p in Q.GRID_W300]
    rows = [_row(k, ci_hi=-0.1) for k in keys]
    rows[5] = _row(keys[5], ci_hi=-0.3)
    best, why = Q.train_best(rows)
    assert best == Q._parse_key(keys[5])[1:] and why.startswith("qualifying")
    tie, _ = Q.train_best([_row(k, ci_hi=-0.1) for k in keys])
    assert tie == (5, 0.8, 3)                                                  # ties -> higher N, D, K
    nq = [_row(k, ci_hi=-0.1, perm=False) for k in keys]
    nq[2] = _row(keys[2], ci_hi=-0.5, perm=False)
    assert Q.train_best(nq)[0] == Q._parse_key(keys[2])[1:]                  # powered, none qualifies
    assert Q.train_best([_row(k, nf=10) for k in keys]) == (Q.DEFAULT_BEST, "no config powered: the most inclusive config")
    k120 = Q.config_key(Q.make_params("w120", *best))
    d = Q.decide_train(rows, best, _row(k120))
    assert d["verdict"] == "SHORTLISTED" and [Q.config_key(p) for p in d["shortlist"]["Q1"]] == [keys[5], k120]
    assert d["shortlist"]["Q1.R0"] == [Q.R0_PARAMS] and len(d["rows"]) == 9
    d2 = Q.decide_train(rows, best, _row(k120, c1=False))
    assert [Q.config_key(p) for p in d2["shortlist"]["Q1"]] == [keys[5]]
    bad = [_row(k, perm=False) for k in keys]
    d3 = Q.decide_train(bad, best, _row(k120))
    assert [Q.config_key(p) for p in d3["shortlist"]["Q1"]] == [k120]          # w120 alone
    assert Q.decide_train(bad, best, _row(k120, perm=False))["verdict"] == "NO_CONFIG"
    small = [_row(k, nf=5) for k in keys]
    assert Q.decide_train(small, Q.DEFAULT_BEST, _row("w120|N3|D0.6|K1", nf=5))["verdict"] == "UNDERPOWERED_TRAIN"


def _ve(nf, nu, fm, um, c1=None):
    return {"n_flagged": nf, "n_unflagged": nu, "flagged_mean": fm, "unflagged_mean": um,
            "verdict": {"criteria": [{"id": 1, "pass": c1}] if c1 is not None else []}}


def test_decide_val_test_confirm():
    assert Q.decide_val_one(_ve(3, 40, -0.3, 0.0))["verdict"] == "UNDERPOWERED_VAL"
    assert Q.decide_val_one(_ve(20, 40, 0.1, 0.0))["verdict"] == "FAIL_VAL"
    assert Q.decide_val_one(_ve(20, 40, -0.1, 0.0))["verdict"] == "SELECTED_UNDERPOWERED"
    assert Q.decide_val_one(_ve(40, 40, -0.3, 0.0, True))["verdict"] == "SELECTED"
    assert Q.decide_val_one(_ve(40, 40, -0.05, 0.0, False))["verdict"] == "FAIL_VAL"
    d = Q.decide_val({"a": _ve(20, 40, 0.1, 0.0), "b": _ve(20, 40, -0.1, 0.0)}, ["a", "b"])
    assert d["candidate"] == "b" and d["proceed"] and d["verdict"] == "SELECTED_UNDERPOWERED"
    d = Q.decide_val({"a": _ve(40, 40, -0.3, 0.0, True), "b": _ve(40, 40, -0.3, 0.0, True)}, ["a", "b"])
    assert d["candidate"] == "a"                                              # shortlist order: w300 first
    d = Q.decide_val({"a": _ve(3, 40, -0.3, 0.0)}, ["a"])
    assert not d["proceed"] and d["verdict"] == "UNDERPOWERED_VAL"
    t = lambda v, nf, fm, um: {"verdict": {"verdict": v}, "oos": {"n_flagged": nf, "flagged_mean": fm,  # noqa: E731
                                                                  "unflagged_mean": um, "gap": None}}
    assert Q.decide_test(t("PASS", 10, -0.2, 0.0))["verdict"] == "PASS"
    assert Q.decide_test(t("PASS", 10, 0.1, 0.0))["verdict"] == "FAIL"        # Q1.T: sign reversed on TEST
    assert Q.decide_test(t("PASS", 3, 0.1, 0.0))["verdict"] == "PASS"         # < 5 flagged: no sign test
    assert Q.decide_test(t("UNDERPOWERED", 10, -0.2, 0.0))["verdict"] == "UNDERPOWERED"
    assert Q.decide_test(t("FAIL", 10, -0.2, 0.0))["verdict"] == "FAIL"
    c = lambda v, p: {"verdict": {"verdict": v}, "perm": {"pass": p}}         # noqa: E731
    assert Q.decide_confirm(c("PASS", True))["verdict"] == "PASS"
    assert Q.decide_confirm(c("PASS", False))["verdict"] == "FAIL"
    assert Q.decide_confirm(c("UNDERPOWERED", True))["verdict"] == "UNDERPOWERED"
    assert Q.decide_confirm(c("INCOMPLETE", True))["verdict"] == "INCOMPLETE"


def test_final_decision_judges_the_unseen_thirds():
    key = "w300|N3|D0.6|K1"
    t = pd.DataFrame({"mint": list("abcdef"), "split": ["final_train"] * 2 + ["final_val"] * 2 + ["final_test"] * 2,
                      "ret_net": [0.5, -0.5, -0.3, 0.1, -0.2, 0.2], f"flag_{key}": [False, True, True, False, True, False]})
    d = Q.final_decision(t, key)
    assert d["n_flagged"] == 2 and d["flagged_mean"] == pytest.approx(-0.25) and d["flagged_worse"] is True
    assert set(d["per_third"]) == {"final_train", "final_val", "final_test"}


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Q1", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Q1 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, env=None, history=None, **kw):
    return Q.run_stage(stage, out_dir=d.out, ds=ds, history=history, flow=d.flow, ledger_path=d.ledger,
                       shortlist_path=d.sl, B=300, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Q.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def mk(split, t0, n, prefix, seed, null=False):
    return ds_of(market_frames(dump_market(t0, n, prefix=prefix, null=null), seed=seed), split)


def test_debug_stage_hides_returns(st):
    ds = mk("train", T0, 120, "D", 9)
    ds.split, ds.debug_only = "final_train", True
    doc = Q.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, env={})
    assert doc["decision"]["verdict"] == "DEBUG" and doc["gate"]["decision"].startswith("HIDDEN")
    assert "delta" not in doc["gate"] and doc["host"]["returns"].startswith("hidden")
    assert len(doc["configs"]) == 9 and "w120|N3|D0.6|K1" in doc["configs"]          # w120 at the fixed default
    for e in doc["configs"].values():
        for k in ("gap", "flagged_mean", "verdict", "perm", "random_veto", "by_class", "organic"):
            assert k not in e
    ec = doc["event_counts"]
    assert ec["r0_entries"] == doc["configs"]["w300|N3|D0.6|K1"]["n_host"] > 0
    assert ec["flags"]["w300|N3|D0.6|K1"]["n_flagged"] > 0
    led = json.loads(st.ledger.read_text())
    assert led["runs"] and all(r["debug"] for r in led["runs"]) and not led["configs"]
    assert (st.out / "debug.md").exists() and not list(st.out.glob("*_trades.csv"))
    assert "rug" not in json.dumps(doc["registry"]).lower()


def test_provisional_train_never_unlocks_val(st):
    ds = mk("train", T0, 120, "A", 1)
    with pytest.raises(Q.Q1Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Q1.json").exists()
    with pytest.raises(Q.Q1Refused, match="no TRAIN result"):
        _check("val", st)


def test_dump_cluster_pipeline_and_every_refusal(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    with pytest.raises(Q.Q1Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: gate PASS, the veto qualifies (labels beat the permuted registry), w120 too
    ds_tr = mk("train", T0, 240, "A", 1)
    tr = _run("train", st, ds_tr)
    assert tr["gate"]["decision"] == "PASS" and tr["gate"]["delta"] < -0.2
    dec = tr["decision"]
    assert dec["verdict"] == "SHORTLISTED" and dec["shortlist_written"], dec
    keys = [Q.config_key(p) for p in dec["shortlist"]["Q1"]]
    assert len(keys) == 2 and keys[0].startswith("w300") and keys[1].startswith("w120")
    e = tr["configs"][keys[0]]
    assert e["verdict"]["verdict"] in ("INCOMPLETE", "PASS") and e["gap"] < -0.2 and e["perm"]["pass"] is True
    assert e["n_flagged"] >= 30 and e["winning_profit_removed"] == 0.0
    led = json.loads(st.ledger.read_text())
    hyps = sorted(v["hypothesis"] for v in led["configs"].values())
    assert hyps == sorted(["Q1"] * 9 + ["Q1.R0", "Q1-gate"]) and led["n_trials_total"] == 2575 + 11
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists() and tr["overall"] == "PENDING VAL"
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Q.Q1Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Q1 test prereg\n")
    with pytest.raises(Q.Q1Refused, match="no VAL result"):
        _check("test", st, env=ENV_ALL)
    sl = (st.sl / "Q1.R0.json").read_text()
    (st.sl / "Q1.R0.json").unlink()
    with pytest.raises(Q.Q1Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Q1.R0.json").write_text(sl)
    with pytest.raises(Q.Q1Refused, match="already ran"):
        _run("train", st, ds_tr)
    # ---- VAL
    ds_va = mk("val", C.utc_ts("2026-10-05 02:00"), 160, "B", 2)
    va = _run("val", st, ds_va, history=[ds_tr])
    assert va["history_splits"] == ["val", "train"] and set(va["configs"]) == set(keys)
    assert va["decision"]["verdict"] == "SELECTED" and va["decision"]["candidate"] == keys[0]
    with pytest.raises(Q.Q1Refused, match="VAL already ran"):
        _check("val", st)
    with pytest.raises(Q.Q1Refused, match="before TEST"):
        _check("confirm", st, env=ENV_ALL)
    with pytest.raises(Q.Q1Refused, match="before TEST"):
        _check("final", st, env=ENV_ALL)
    # ---- TEST: locked without the judge's flag, then once only
    ds_te = mk("test", C.utc_ts("2026-10-06 13:00"), 80, "C", 3)
    with pytest.raises(Q.Q1Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_te, history=[ds_tr, ds_va])
    te = _run("test", st, ds_te, env=ENV_ALL, history=[ds_tr, ds_va])
    assert te["decision"]["verdict"] == "PASS" and te["decision"]["q1_t_sign_on_test"] is True, te["decision"]
    assert te["configs"]["candidate_vs_val"]["oos"]["n_host"] == te["configs"][keys[0]]["n_host"]
    with pytest.raises(Q.Q1Refused, match="already ran"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Q.Q1Refused, match="one test run"):
        _check("test", st, env=ENV_ALL)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    led = json.loads(st.ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"] if r["split"] == "test"} == {"Q1", "Q1.R0"}
    # ---- CONFIRM (powered, its own history): the machinery CAN say PASS
    co = _run("confirm", st, mk("confirm", C.utc_ts("2026-09-20 00:00"), 240, "E", 4), env=ENV_ALL)
    assert co["history_splits"] == ["confirm"] and co["decision"]["verdict"] == "PASS", co["decision"]
    assert co["overall"] == "PENDING FINAL"
    # ---- FINAL
    fi = _run("final", st, mk("final", C.FINAL_LO + 3600, 120, "F", 5), env=ENV_ALL)
    assert fi["decision"]["flagged_worse"] is True and fi["overall"] == "VETO"
    with pytest.raises(Q.Q1Refused, match="already ran"):
        _check("final", st, env=ENV_ALL)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_null_market_is_killed_by_the_gate(st, monkeypatch):
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    tr = _run("train", st, mk("train", T0, 240, "A", 1, null=True))
    assert tr["gate"]["decision"] == "KILL" and tr["decision"]["verdict"] == "KILLED_GATE"
    assert "configs" not in tr and tr["overall"].startswith("KILLED")
    led = json.loads(st.ledger.read_text())
    assert [v["hypothesis"] for v in led["configs"].values()] == ["Q1-gate"]     # host and grid never ran
    with pytest.raises(Q.Q1Refused, match="dead"):
        _check("val", st)


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Q.Q1Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Q.Q1Refused, match="pre-register"):
        _check("train", st)


def test_history_bounds_never_reach_a_later_split():
    cen = C.Census.empty()
    assert Q._hist_bounds("train", cen) == (C.SPLIT_BOUNDS["train"][0], C.SPLIT_BOUNDS["train"][1])
    assert Q._hist_bounds("val", cen) == (C.SPLIT_BOUNDS["train"][0], C.SPLIT_BOUNDS["val"][1])
    assert Q._hist_bounds("confirm", cen) == (C.SPLIT_BOUNDS["confirm"][0], C.SPLIT_BOUNDS["confirm"][1])
    lo, hi = Q._hist_bounds("debug", cen)
    assert lo == C.FINAL_LO and hi == cen.train_hi + 1

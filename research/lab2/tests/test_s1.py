"""Tests for research/lab2/s1.py: feature correctness on hand-built B1 fixtures, roles and their timing, NULL rules,
no-lookahead invariance (features and decisions), the dose-response gate and selection rules, exits, trial counting,
and the stage machinery (prerequisite refusals, stop rule 3)."""

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import common as C
import s1
from conftest import POOLED, make_frames

SOL = C.SolUsd(fallback=100.0)
T0 = C.utc_ts("2026-10-02 00:00")
M = 1_000_000          # raw units per whole token
L = 1_000_000_000      # lamports per SOL


def addr(i: int) -> str:
    return s1.b58encode(bytes([(i * 37 + k) % 251 + 1 for k in range(32)]))


def wh(a) -> int:
    return s1.wallet_h(a) if isinstance(a, str) else int(a)


@pytest.fixture(autouse=True)
def _fresh_cache():
    s1.clear_cache()
    yield
    s1.clear_cache()


# =========================================================================== fixtures


def s1_frames(n: int = 3, t0: int = T0, delay: int = 600, seed: int = 1):
    """make_frames graduates turned into non-instant graduates (created g - delay) with a real-looking creator."""
    g, c, b = make_frames(n=n, seed=seed, t0=t0, slow_every=0, agent_every=0)
    g = g.copy()
    g["c_ts"] = g["g_ts"] - delay
    g["c_slot"] = g["g_slot"] - 2000
    g["creator"] = [addr(900 + i) for i in range(len(g))]
    g["curve_top3_buy_sol"] = 30.0
    g["curve_buy_sol"] = 90.0
    g["curve_n_buyers"] = 40
    return g, c, b


class Tape:
    """Builds B1 rows (chain order = insertion order within a second)."""

    def __init__(self, mint: str, c_ts: int, c_slot: int) -> None:
        self.mint, self.c_ts, self.c_slot, self.rows = mint, c_ts, c_slot, []

    def add(self, ts, venue, buy, w, sol, tok, x0=None, y0=None, fees=0.0, virt=17.584505289, slot=None):
        if x0 is None:
            x0 = 85 * L if venue == 1 else 31 * L
        if y0 is None:
            y0 = 200_000_000 * M if venue == 1 else 1_000_000_000 * M
        self.rows.append({"slot": slot if slot is not None else self.c_slot + 1 + 2 * (int(ts) - self.c_ts),
                          "tx_idx": len(self.rows), "pix": 0, "ix": 0, "ts": int(ts), "venue": venue,
                          "is_buy": int(buy), "wallet_h": np.uint64(wh(w)), "usol": int(round(sol * L)),
                          "tok": int(round(tok * M)), "x0": int(x0), "y0": int(y0), "fees": int(round(fees * L)),
                          "virt_ksol": int(virt * L // 1000) if venue == 1 else 0, "mint": self.mint, "src": 0})
        return self

    def frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.rows).sort_values(["slot", "tx_idx"], kind="stable").reset_index(drop=True)
        df["wallet_h"] = df["wallet_h"].astype(np.uint64)
        return df


# wallets of the hand-built coin
CREATOR = addr(900)
BUNDLE, SN1, L1, L2, COMP = addr(1), addr(2), addr(3), addr(4), addr(5)
EARLY = [addr(10 + i) for i in range(17)]
AGENT, BOT, WASH, MECH, T_ORPH = addr(40), addr(41), addr(42), addr(43), addr(44)
ORG = [addr(60 + i) for i in range(13)]       # ORG[0] = ORG1, ORG[1..11] = ORG2..ORG12


def hand_tape(g_ts: int, mint: str, c_ts: int, c_slot: int) -> Tape:
    """The documented fixture coin (see each expected value in test_hand_features)."""
    G = g_ts
    t = Tape(mint, c_ts, c_slot)
    # ---- curve: creation slot (creator + bundle), sniper by time, 17 early buyers (first-20 rule), band buyers
    t.add(c_ts, 0, True, CREATOR, 1.0, 50e6, x0=30 * L, slot=c_slot)
    t.add(c_ts, 0, True, BUNDLE, 2.0, 80e6, x0=31 * L, slot=c_slot)
    t.add(c_ts + 30, 0, True, SN1, 1.0, 30e6, x0=33 * L)
    for k, w in enumerate(EARLY):
        t.add(c_ts + 61 + k, 0, True, w, 0.5, 10e6, x0=34 * L)
    t.add(c_ts + 300, 0, True, L1, 20.25, 100e6, x0=80 * L, fees=0.25)    # real 50 -> 70: band 15 SOL
    t.add(c_ts + 400, 0, True, L2, 10.125, 40e6, x0=100 * L, fees=0.125)  # real 70 -> 80: band 10
    t.add(G, 0, True, COMP, 5.0625, 20e6, x0=110 * L, fees=0.0625)        # real 80 -> 85: band 5
    # ---- pool
    for k in range(30):
        t.add(G + 2 + 12 * k, 1, True, AGENT, 0.586, 1e6)
    t.add(G + 60, 1, False, CREATOR, 10.0, 50e6)
    t.add(G + 90, 1, False, BUNDLE, 8.0, 40e6)
    t.add(G + 120, 1, True, ORG[0], 1.0, 5e6)
    t.add(G + 200, 1, False, SN1, 6.0, 30e6)
    for k, w in enumerate(EARLY):
        t.add(G + 250 + k, 1, False, w, 2.0, 10e6)
    t.add(G + 310, 1, False, T_ORPH, 1.0, 5e6)                            # never bought: TRANSFEREE
    t.add(G + 400, 1, False, L1, 12.0, 60e6)
    t.add(G + 500, 1, True, BOT, 0.5, 2e6)
    t.add(G + 503, 1, False, BOT, 0.49, 2e6)
    t.add(G + 520, 1, True, BOT, 0.5, 2e6)
    t.add(G + 524, 1, False, BOT, 0.49, 2e6)
    t.add(G + 600, 1, True, WASH, 0.6, 3e6)
    t.add(G + 640, 1, False, WASH, 0.58, 2.9e6)
    for k in range(8):
        t.add(G + 700 + 60 * k, 1, True, MECH, 0.2, 1e6)
    for k in range(1, 12):
        t.add(G + 880 + 20 * k, 1, True, ORG[k], 0.5, 2.5e6)
    t.add(G + 1000, 1, True, POOLED, 2.0, 10e6)
    t.add(G + 1100, 1, False, POOLED, 1.5, 17e6)                          # pooled orphan: must be ignored
    t.add(G + 1150, 1, False, ORG[0], 0.3, 2e6)
    t.add(G + 1200, 1, False, BUNDLE, 7.0, 40e6)
    return t


def hand_ds(split="train", t0=T0, extra=None, tape_fn=hand_tape, frames=None):
    g, c, b = frames if frames is not None else s1_frames(t0=t0)
    r = g.iloc[0]
    tape = tape_fn(int(r["g_ts"]), r["mint"], int(r["c_ts"]), int(r["c_slot"]))
    if extra:
        extra(tape, int(r["g_ts"]))
    tr = tape.frame()
    ds = C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL, trades=tr, guard=False)
    return ds, r["mint"], int(r["g_ts"]), tr


# =========================================================================== hashing


def test_cityhash_matches_clickhouse_pairs():
    pairs = [(9740399439260290013, "168Q2pG7tYAoNXLQcA7yJufVzrUnZr85W5eYTBfp5eB"),
             (13548937726806623243, "14Bzxa1JbhAcCgY5qDk5ubuHVq98ecGCxzWgnCKpVRYG")]
    for h, a in pairs:
        assert s1.wallet_h(a) == h
    assert s1.b58decode(s1.b58encode(bytes(range(1, 33)))) == bytes(range(1, 33))


def test_cityhash_all_real_pairs_on_disk():
    p = C.flow_dir() / "dev" / "test_b1.json"
    if not p.exists():
        pytest.skip("B1 dev query result not on disk")
    d = json.loads(p.read_text())
    i = d["columns"].index("wallet_dict")
    pairs = [(h, a) for r in d["rows"] for h, a in r[i]]
    assert len(pairs) > 100 and all(s1.wallet_h(a) == h for h, a in pairs)


# =========================================================================== feature correctness (hand-built)


def test_hand_features_exact():
    ds, m, G, _ = hand_ds()
    f = s1.s1_features(ds.asof(m, G + 1200))       # tau = G + 1180
    assert f["ok"] and f["why"] == ""
    # insiders: creator 50 + bundle 80 + sniper 30 + 17 early x 10 (first-20 rule) + completer L1 100 = 430M at peak;
    # at tau: bundle 40 (its last 40 sell is at G + 1200 > tau) + L1 40 = 80M; the orphan seller holds < 0
    assert f["insider_peak"] == pytest.approx(430e6)
    assert f["insider_hold"] == pytest.approx(80e6)
    assert f["insider_rem"] == pytest.approx(80 / 430)
    assert f["n_bundle"] == 2 and f["n_snipers"] == 20 and f["n_transferees"] == 1
    assert f["n_insiders"] == 2 + 18 + 1 + 1      # creator + bundle, SN1 + 17 early, completer L1, orphan seller
    # organic window (G + 580, G + 1180]: ORG2..ORG12 buy 11 x 0.5; ORG1 sells 0.3; WASH/MECH/BOT/POOLED excluded
    assert f["org_net10"] == pytest.approx(5.5 - 0.3)
    assert f["org_buyers10"] == 11
    assert f["orphan_share10"] == 0.0                # the pooled account's orphan sell is ignored
    assert f["creator_sold10"] == 0.0 and f["creator_sold_frac"] == pytest.approx(1.0)
    assert f["completer_pos_frac"] == pytest.approx(0.4)
    assert f["boost_absorb"] == pytest.approx(1.0)  # only ORG1's buy is organic flow in [G, G + 300]
    b_agent = 25 * 0.586                             # slices at G + 2 + 12k <= G + 300 -> k = 0..24
    assert f["insider_into_boost"] == pytest.approx((10 + 8 + 6 + 17 * 2) / b_agent)
    assert f["n_bot"] == 1 and f["n_wash"] == 2 and f["n_mech"] == 1
    assert f["agent_detected"] and f["agent_slices"] == 30 and f["agent_known_at"] == G + 38
    assert f["g1_class"] == "ORGANIC"
    assert f["completer_share"] == pytest.approx(15 / 30)
    assert f["amm_buy_sol_2m"] == pytest.approx(1.0) and f["amm_buyers_2m"] == 1


def test_hand_features_at_g_plus_400():
    ds, m, G, _ = hand_ds()
    f = s1.s1_features(ds.asof(m, G + 420))       # tau = G + 400, window (G - 200, G + 400]
    sells = 50 + 40 + 30 + 170 + 5 + 60            # L1's 60M sell at G + 400 is <= tau
    assert f["orphan_share10"] == pytest.approx(5 / sells)
    assert f["creator_sold10"] == pytest.approx(1.0)
    assert f["insider_hold"] == pytest.approx(40e6 + 40e6)   # bundle 80 - 40; L1 100 - 60 (sold at G + 400 <= tau)
    assert f["n_bot"] == 0 and f["n_mech"] == 0


def test_role_timing_agent_bot_transferee():
    ds, m, G, _ = hand_ds()
    early = s1.s1_features(ds.asof(m, G + 50))      # tau = G + 30: 3 agent slices
    assert early["agent_detected"] is False
    assert s1.s1_features(ds.asof(m, G + 58))["agent_detected"] is True   # 4th slice at G + 38
    assert s1.s1_features(ds.asof(m, G + 320))["n_transferees"] == 0      # orphan sell at G + 310 > tau = G + 300
    assert s1.s1_features(ds.asof(m, G + 331))["n_transferees"] == 1
    assert s1.s1_features(ds.asof(m, G + 530))["n_bot"] == 0              # 2 trades only
    assert s1.s1_features(ds.asof(m, G + 545))["n_bot"] == 1
    # before g + 120 the G1 class is unknown: not ok, not permanent
    f = s1.s1_features(ds.asof(m, G + 100))
    assert not f["ok"] and f["g1_class"] is None and not f["permanent"]


def test_tau_override_equals_direct_asof():
    ds, m, G, _ = hand_ds()
    late = ds.asof(m, G + 1500)
    direct = s1.s1_features(ds.asof(m, G + 420))
    s1.clear_cache()
    via = s1.s1_features(late, tau=G + 400)
    assert via == direct
    assert s1.s1_features(ds.asof(m, G + 420), tau=G + 9999)["tau"] == G + 400   # never later than the snapshot


def test_g1_classes_operator_and_completed():
    def operator(t, G):
        for k in range(10):
            t.add(G + 5 + k, 1, True, addr(200 + k), 60.0, 1e6)          # 600 SOL from 10 buyers in 2 min
    ds, m, G, _ = hand_ds(extra=operator)
    assert s1.s1_features(ds.asof(m, G + 1200))["g1_class"] == "OPERATOR"

    g, c, b = s1_frames()
    g.loc[0, "curve_top3_buy_sol"] = 80.0                                  # top-3 share 0.89 -> COMPLETED
    ds, m, G, _ = hand_ds(frames=(g, c, b))
    assert s1.s1_features(ds.asof(m, G + 1200))["g1_class"] == "COMPLETED"


def test_null_rules_never_zero():
    g, c, b = s1_frames()
    g.loc[0, "has_create"] = 0                                             # creation not scanned
    ds, m, G, _ = hand_ds(frames=(g, c, b))
    f = s1.s1_features(ds.asof(m, G + 1200))
    assert not f["ok"] and f["why"] == "creation_not_scanned" and f["permanent"]
    assert "insider_rem" not in f
    # a coin without B1 rows
    ds, m, G, _ = hand_ds()
    other = [x for x in ds.mints if x != m][0]
    f = s1.s1_features(ds.asof(other, ds.coin(other).g + 1200))
    assert f["why"] == "no_b1" and f["permanent"]
    # g1 NULL input -> class NULL (never defaulted to ORGANIC)
    g, c, b = s1_frames()
    g.loc[0, "curve_buy_sol"] = np.nan
    ds, m, G, _ = hand_ds(frames=(g, c, b))
    f = s1.s1_features(ds.asof(m, G + 1200))
    assert f["g1_class"] is None and not f["ok"] and f["permanent"]
    # instant graduate
    ds, m, G, _ = hand_ds(frames=s1_frames(delay=3))
    assert s1.s1_features(ds.asof(m, G + 1200))["why"] == "instant_or_unknown_grad_delay"


def test_truncation_and_horizon(monkeypatch):
    ds, m, G, tr = hand_ds()
    monkeypatch.setattr(s1, "B1_MAX_TRADES", 60)
    f = s1.s1_features(ds.asof(m, G + 1200))
    assert f["why"] == "b1_truncated" and f["permanent"]
    assert s1.s1_features(ds.asof(m, G + 200))["ok"] in (True, False)     # short prefix still computable
    monkeypatch.setattr(s1, "B1_MAX_TRADES", 20000)
    f = s1.s1_features(ds.asof(m, G + s1.B1_HORIZON_S + 20))
    assert f["why"] == "beyond_b1_horizon" and f["permanent"]


def test_creator_without_trades_and_pooled_exclusion():
    def no_creator(g_ts, mint, c_ts, c_slot):
        t = hand_tape(g_ts, mint, c_ts, c_slot)
        t.rows = [r for r in t.rows if r["wallet_h"] != np.uint64(s1.wallet_h(CREATOR))]
        return t
    ds, m, G, _ = hand_ds(tape_fn=no_creator)
    f = s1.s1_features(ds.asof(m, G + 1200))
    assert f["creator_peak"] == 0 and f["creator_sold10"] == 0.0 and not f["creator_traded"]
    assert s1.pooled_hashes() and s1.wallet_h(POOLED) in s1.pooled_hashes()


# =========================================================================== no lookahead


def _garble_trades(tr: pd.DataFrame, mint: str, tau: float, rng) -> pd.DataFrame:
    tr = tr.copy()
    fut = (tr["mint"] == mint) & (tr["ts"] > tau)
    tr.loc[fut, "usol"] = rng.integers(1, 10**12, fut.sum())
    tr.loc[fut, "tok"] = rng.integers(1, 10**15, fut.sum())
    tr.loc[fut, "wallet_h"] = rng.integers(1, 2**62, fut.sum()).astype(np.uint64)
    tr.loc[fut, "is_buy"] = rng.integers(0, 2, fut.sum())
    drop = tr.index[fut][rng.random(fut.sum()) < 0.3]
    tr = tr.drop(index=drop)
    last = tr[tr["mint"] == mint].iloc[-1]
    new = [dict(last, ts=int(tau) + int(rng.integers(1, 3000)), slot=int(last["slot"]) + 10 + i,
                usol=int(rng.integers(1, 10**12)), wallet_h=np.uint64(rng.integers(1, 2**62))) for i in range(25)]
    tr = pd.concat([tr, pd.DataFrame(new)], ignore_index=True)
    tr["wallet_h"] = tr["wallet_h"].astype(np.uint64)
    return tr


def _garble_bars(b: pd.DataFrame, mint: str, tau: float, rng) -> pd.DataFrame:
    b = b.astype({k: "float64" for k in ("buy_sol", "sell_sol", "n_buyers", "n_buys", "open", "close", "high", "low")})
    fut = (b["mint"] == mint) & (b["minute_ts"] + 60 > tau)
    for col in ("buy_sol", "sell_sol", "n_buyers", "n_buys"):
        b.loc[fut, col] = rng.uniform(0, 1e4, fut.sum())
    px = rng.uniform(1e-9, 1e-3, fut.sum())
    b.loc[fut, "open"], b.loc[fut, "close"], b.loc[fut, "high"], b.loc[fut, "low"] = px, px * 2, px * 3, px / 3
    return b


def _same(a: dict, b: dict) -> bool:
    if a.keys() != b.keys():
        return False
    for k in a:
        x, y = a[k], b[k]
        if isinstance(x, float) and isinstance(y, float) and math.isnan(x) and math.isnan(y):
            continue
        if x != y:
            return False
    return True


@pytest.mark.parametrize("seed", range(3))
def test_features_unchanged_by_future_garbage_hand(seed):
    rng = np.random.default_rng(seed)
    g, c, b = s1_frames()
    ds, m, G, tr = hand_ds(frames=(g, c, b))
    for t in (G + 130, G + 345, G + 420, G + 645, G + 1200, G + 1530, G + 5000):
        tau = t - C.DECISION_LAG_S
        f0 = s1.s1_features(ds.asof(m, t))
        nf0 = s1.nonflow_ok(ds.asof(m, t)) if f0["ok"] else None
        s1.clear_cache()
        dirty = C.Dataset.from_frames("train", g, c, _garble_bars(b, m, tau, rng), census=C.Census.empty(), sol=SOL,
                                      trades=_garble_trades(tr, m, tau, rng), guard=False)
        f1 = s1.s1_features(dirty.asof(m, t))
        assert _same(f0, f1), t
        if f0["ok"]:
            assert s1.nonflow_ok(dirty.asof(m, t)) == nf0


def synth_ds(n=10, seed=3, t0=T0, split="train", max_per_minute=10):
    g, c, b = s1_frames(n=n, seed=seed, t0=t0)
    ds0 = C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL, guard=False)
    tr = s1.synth_b1(ds0, ds0.mints, seed=seed, max_per_minute=max_per_minute)
    ds = C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL, trades=tr, guard=False)
    return ds, (g, c, b), tr


def test_features_unchanged_by_future_garbage_random_pairs():
    """PLAN 6.6 rule 9 for S1: random (coin, tau) pairs on synthetic B1; every trade/bar after tau is garbage."""
    rng = np.random.default_rng(11)
    ds, (g, c, b), tr = synth_ds(n=8)
    n = 0
    for m in ds.mints:
        cd = ds.coin(m)
        for _ in range(5):
            t = cd.g + float(rng.uniform(30, 7300))
            tau = t - C.DECISION_LAG_S
            f0 = s1.s1_features(ds.asof(m, t))
            s1.clear_cache()
            dirty = C.Dataset.from_frames("train", g, c, _garble_bars(b, m, tau, rng), census=C.Census.empty(),
                                          sol=SOL, trades=_garble_trades(tr, m, tau, rng), guard=False)
            assert _same(f0, s1.s1_features(dirty.asof(m, t)))
            n += 1
    assert n == 40


@pytest.mark.skipif(not (C.flow_dir() / "b2_bars.parquet").exists(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train_bars():
    """Real census TRAIN third bars/graduates + synthetic B1: 40 random (coin, tau) pairs, garbage after tau."""
    rng = np.random.default_rng(42)
    g, c, b = s1._read_flow()
    cen = C.Census.load()
    ds0 = C.Dataset.from_frames("final_train", g, c, b, census=cen, sol=SOL, guard=False)
    uni = list(ds0.coins.loc[s1.universe_mask(ds0.coins), "mint"])
    mints = [uni[int(i)] for i in rng.choice(len(uni), size=8, replace=False)]
    sub = tuple(x[x["mint"].isin(mints)] for x in (g, c, b))
    ds0 = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL, guard=False)
    tr = s1.synth_b1(ds0, mints, seed=4, max_per_minute=10)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL, trades=tr, guard=False)
    n = 0
    for m in mints:
        cd = clean.coin(m)
        for _ in range(5):
            t = cd.g + float(rng.uniform(300, 7300))
            tau = t - C.DECISION_LAG_S
            f0 = s1.s1_features(clean.asof(m, t))
            nf0 = s1.nonflow_ok(clean.asof(m, t), f0) if f0["ok"] else None
            s1.clear_cache()
            g2, c2, b2 = sub
            dirty = C.Dataset.from_frames("final_train", g2, c2, _garble_bars(b2, m, tau, rng), census=cen, sol=SOL,
                                          trades=_garble_trades(tr, m, tau, rng), guard=False)
            f1 = s1.s1_features(dirty.asof(m, t))
            assert _same(f0, f1)
            if f0["ok"]:
                assert s1.nonflow_ok(dirty.asof(m, t), f1) == nf0
            n += 1
    assert n == 40


def test_decisions_before_T_unchanged_by_future_garbage():
    rng = np.random.default_rng(5)
    ds, (g, c, b), tr = synth_ds(n=6)
    p = dict(s1.grid_params()[-1])         # rem 0.25, buy 20, absorb no
    p["theta_buy"] = 1
    for m in ds.mints:
        cd = ds.coin(m)
        T = cd.g + 1500
        dirty = C.Dataset.from_frames("train", g, c, _garble_bars(b, m, T - 20, rng), census=C.Census.empty(),
                                      sol=SOL, trades=_garble_trades(tr, m, T - 20, rng), guard=False)
        s1.clear_cache()
        a = C.run_trades(ds, s1.s1_strategy, p, C.FillConfig(), mints=[m])
        s1.clear_cache()
        d = C.run_trades(dirty, s1.s1_strategy, p, C.FillConfig(), mints=[m])
        assert a.loc[a["t_dec"] <= T, "t_dec"].tolist() == d.loc[d["t_dec"] <= T, "t_dec"].tolist()


def test_only_asof_reads():
    """s1.py never touches Dataset/CoinData internals in feature or strategy code."""
    src = Path(s1.__file__).read_text()
    feat = src[src.index("def s1_features"):src.index("# =========================================================================== params")]
    for bad in ("._cd", ".coin(", ".arr[", "ds.coins", ".row["):
        assert bad not in feat, bad


# =========================================================================== strategies and exits


def test_checkpoint_mapping_rounds_down():
    ds, m, G, _ = hand_ds()
    cd = ds.coin(m)
    hits = {}
    for k in range(1, C.N_BARS):
        t = cd.bar_start(k) + C.GRID_OFFSET_S
        cp = s1.checkpoint_at(ds.asof(m, t), s1.CHECKPOINTS_MIN)
        if cp is not None:
            hits[cp] = t
    assert sorted(hits) == list(s1.CHECKPOINTS_MIN)
    for cp, t in hits.items():
        assert t <= G + 60 * cp < t + 60


def test_entry_conditions_and_none_never_pass():
    f = {"g1_class": "ORGANIC", "completer_pos_frac": 0.0, "insider_rem": 0.05, "org_net10": 1.0, "org_buyers10": 12,
         "orphan_share10": 0.0, "creator_sold10": 0.0, "boost_absorb": 2.0}
    p = s1.grid_params()[0]                       # rem 0.10, buy 10, absorb yes
    assert s1._flow_entry_ok(f, p)
    for k, bad in (("insider_rem", None), ("insider_rem", 0.2), ("org_net10", 0.0), ("org_buyers10", 9),
                   ("orphan_share10", 0.15), ("creator_sold10", 0.2), ("boost_absorb", None), ("boost_absorb", 0.0)):
        assert not s1._flow_entry_ok({**f, k: bad}, p), k
    assert s1._flow_entry_ok({**f, "boost_absorb": None}, {**p, "absorb_req": False})
    assert not s1._flow_entry_ok({**f, "g1_class": "COMPLETED", "completer_pos_frac": 0.11}, p)
    assert not s1._flow_entry_ok({**f, "g1_class": "COMPLETED", "completer_pos_frac": None}, p)


def _pos(t_dec):
    return C.PositionView(mint="x", t_dec=t_dec, t_in=t_dec + 30, entry_price=1.0, tokens=1.0, sol_in=0.2, peak=1.0,
                          bars_held=1, unrealized=0.0, exits=C.ExitSpec(), state={}, is_placebo=True)


def test_flow_exits():
    P = s1.BASE_PARAMS

    def org_dump(t, G):
        for k in range(1, 5):
            t.add(G + 1500 + k, 1, False, ORG[k], 0.5, 2.5e6)
    ds, m, G, _ = hand_ds(extra=org_dump)
    assert s1.flow_exit(ds.asof(m, G + 1480), P, _pos(G + 1300)) is None
    assert s1.flow_exit(ds.asof(m, G + 1530), P, _pos(G + 1300)).reason == "org_net5"

    def regrow(t, G):
        t.add(G + 1500, 1, True, L1, 0.3, 25e6)          # an insider re-accumulates 25M > 2 % of supply
    ds, m, G, _ = hand_ds(extra=regrow)
    assert s1.flow_exit(ds.asof(m, G + 1530), P, _pos(G + 1300)).reason == "insider_grow"

    def creator_holds(g_ts, mint, c_ts, c_slot):
        t = hand_tape(g_ts, mint, c_ts, c_slot)
        t.rows = [r for r in t.rows if not (r["wallet_h"] == np.uint64(s1.wallet_h(CREATOR)) and r["venue"] == 1)]
        t.add(g_ts + 1500, 1, False, CREATOR, 1.0, 11e6)  # 22 % of its 50M peak, after entry
        return t
    ds, m, G, _ = hand_ds(tape_fn=creator_holds)
    assert s1.flow_exit(ds.asof(m, G + 1530), P, _pos(G + 1300)).reason == "creator_sells"
    # beyond the B1 horizon: mechanical exits only
    assert s1.flow_exit(ds.asof(m, G + s1.B1_HORIZON_S + 60), P, _pos(G + 1300)) is None


def test_strategy_end_to_end_one_entry_per_coin_and_placebo_exits(tmp_ledger):
    ds, _, _ = synth_ds(n=10)
    p = dict(s1.grid_params()[-1])
    p["theta_buy"] = 1
    res = C.backtest(s1.s1_strategy, "train", p, hypothesis="S1-test", ds=ds, n_placebo=3,
                     placebo_eligible=s1.placebo_eligible)
    t = res.trades
    assert t["mint"].is_unique
    assert set(t["tag"]) <= {f"cp{c}" for c in s1.CHECKPOINTS_MIN}
    assert len(res.placebo) == 0 or set(res.placebo["reason"]) <= {"trail", "time", "horizon", "stop",
        "signal:org_net5", "signal:orphan10", "signal:creator_sells", "signal:insider_grow"}


# =========================================================================== gate and selection rules


def _gate_trades(means, n_per=20, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for q, mu in enumerate(means):
        for i in range(n_per):
            rem = (q + rng.uniform(0.01, 0.99)) / 5
            rows.append({"mint": f"m{q}_{i}", "tag": f"rem={rem:.9f}", "t_dec": 1000.0 + i,
                         "ret_net": mu + rng.normal(0, 0.01)})
    return pd.DataFrame(rows)


def test_gate_quintiles_and_verdicts():
    good = s1.gate_quintiles(_gate_trades([0.10, 0.05, 0.06, 0.0, -0.05]), B=500)   # one inversion (Q2 < Q3)
    assert [q["n"] for q in good["quintiles"]] == [20] * 5 and good["inversions"] == 1
    assert good["q1_minus_q5"] == pytest.approx(0.15, abs=0.01)
    bad = s1.gate_quintiles(_gate_trades([0.0, 0.05, 0.0, 0.06, 0.02]), B=500)
    assert bad["inversions"] == 2
    assert s1.gate_verdict_train({10: good, 30: good})["status"] == "PASS"
    assert s1.gate_verdict_train({10: good, 30: bad})["status"] == "GATE_FAIL"
    small = s1.gate_quintiles(_gate_trades([0.1] * 5, n_per=10), B=200)
    assert s1.gate_verdict_train({10: good, 30: small})["status"] == "GATE_UNDERPOWERED"
    assert s1.gate_verdict_val({10: good, 30: good})["status"] == "PASS"
    flat = s1.gate_quintiles(_gate_trades([0.03, 0.02, 0.02, 0.01, 0.0]), B=200)
    assert s1.gate_verdict_val({10: good, 30: flat})["status"] == "GATE_VAL_FAIL"
    hidden = s1.gate_quintiles(_gate_trades([0.1] * 5), reveal=False, B=200)
    assert hidden["q1_minus_q5"] == "hidden" and all(q["mean"] == "hidden" for q in hidden["quintiles"])


def test_shortlist_and_val_selection_rules():
    P = s1.grid_params()
    row = lambda i, **kw: {"params": P[i], "n": 40, "n_coins": 35, "mean": 0.05, "mean_without_top2": 0.03,  # noqa: E731
                           "ci90": [0.01, 0.09], "control1_diff": 0.07, "placebo_diff": 0.02, **kw}
    r = s1.shortlist_rule([row(0, ci90=[0.02, 0.1]), row(1), row(2, ci90=[0.03, 0.1]), row(3, control1_diff=0.05)])
    assert r["status"] == "SHORTLISTED" and r["shortlist"] == [P[2], P[0]]
    assert s1.shortlist_rule([row(0, mean=-0.01), row(1, placebo_diff=-0.1)])["status"] == "NO_CONFIG"
    assert s1.shortlist_rule([row(0, n=10), row(1, n_coins=5)])["status"] == "UNDERPOWERED_TRAIN"
    v = lambda **kw: {"params": P[0], "n": 20, "mean": 0.05, "ci90": [0.0, 0.1], "control1_diff": 0.07, **kw}  # noqa: E731
    assert s1.val_selection([v()])["status"] == "SELECTED"
    assert s1.val_selection([v(n=10), v(n=3)])["status"] == "UNDERPOWERED_VAL"
    assert s1.val_selection([v(mean=-0.01), v(n=3)])["status"] == "FAIL_VAL"


def test_grid_is_exactly_8_distinct_trials_within_limit():
    hs = {C.params_hash(p) for p in s1.grid_params()}
    assert len(hs) == 8 == C.VARIANT_LIMITS["S1"]
    assert C.params_hash(s1.control_params()) not in hs
    assert len({C.params_hash(s1.gate_params(c)) for c in s1.GATE_CHECKPOINTS_MIN}) == 2


# =========================================================================== stage machinery


@pytest.fixture
def stage_env(tmp_path, monkeypatch, tmp_ledger):
    d = tmp_path / "S1"
    d.mkdir()
    shutil.copy(Path(s1.__file__).parent / "S1" / "PREREG.md", d / "PREREG.md")
    monkeypatch.setenv("LAB2_S1_DIR", str(d))
    for k in ("LAB2_ALLOW_TEST", "LAB2_ALLOW_CONFIRM", "LAB2_ALLOW_FINAL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(s1, "check_data", lambda split, allow_partial=False: {
        "split": split, "problems": [], "split_complete": True, "b1_covered": 10, "s1_universe": 10})
    sets = {"train": T0, "val": C.utc_ts("2026-10-05 01:00"), "test": C.utc_ts("2026-10-06 13:00")}
    cache = {}

    def loader(split):
        if split not in cache:
            cache[split] = synth_ds(n=10, seed=7, t0=sets[split], split=split)[0]
        return cache[split]
    monkeypatch.setattr(s1, "load_split", loader)
    monkeypatch.setattr(s1, "GATE_MIN_COINS", {"train": 1, "val": 1})
    return d


def test_stop_rule_gate_fail_kills_s1_before_grid(stage_env, monkeypatch, tmp_ledger):
    monkeypatch.setattr(s1, "gate_verdict_train", lambda stats: {"status": "GATE_FAIL", "per_checkpoint": {}})
    out = s1.stage_train()
    assert out["status"] == "GATE_FAIL" and "grid" not in out
    led = json.loads(tmp_ledger.read_text())
    assert {r["hypothesis"] for r in led["runs"]} == {"S1-gate"}          # the entry grid never ran
    assert not (C.shortlist_dir() / "S1.json").exists()
    assert (stage_env / "train.json").exists() and (stage_env / "prereg.lock").exists()
    with pytest.raises(s1.StageRefused, match="SHORTLISTED"):
        s1.stage_val()
    assert s1.overall_verdict()["verdict"] == "NO EDGE"


def test_train_runs_grid_counts_trials_and_val_needs_shortlist(stage_env, monkeypatch, tmp_ledger):
    monkeypatch.setattr(s1, "gate_verdict_train", lambda stats: {"status": "PASS", "per_checkpoint": {}})
    before = C.n_trials(tmp_ledger)
    out = s1.stage_train()
    assert C.n_trials(tmp_ledger) - before == 8 + 2 + 1
    led = json.loads(tmp_ledger.read_text())
    assert not any(r["over_variant_limit"] for r in led["runs"])
    assert out["status"] in ("SHORTLISTED", "NO_CONFIG", "UNDERPOWERED_TRAIN")
    if out["status"] != "SHORTLISTED":
        with pytest.raises(s1.StageRefused):
            s1.stage_val()


def test_val_test_final_sequence_and_refusals(stage_env, monkeypatch, tmp_ledger):
    P = s1.grid_params()
    monkeypatch.setattr(s1, "gate_verdict_train", lambda stats: {"status": "PASS", "per_checkpoint": {}})
    monkeypatch.setattr(s1, "shortlist_rule", lambda rows: {"status": "SHORTLISTED", "shortlist": [P[7], P[5]],
                                                             "ranked": []})
    with pytest.raises(s1.StageRefused, match="no official TRAIN run"):
        s1.stage_test()
    s1.stage_train()
    assert (C.shortlist_dir() / "S1.json").exists()
    with pytest.raises(s1.StageRefused, match="TEST needs VAL"):
        s1.stage_test()
    with pytest.raises(s1.StageRefused, match="never FINAL before TEST"):
        s1.stage_final()
    monkeypatch.setattr(s1, "gate_verdict_val", lambda stats: {"status": "PASS", "per_checkpoint": {}})
    monkeypatch.setattr(s1, "val_selection", lambda rows: {"status": "SELECTED", "selected": P[7]})
    out = s1.stage_val()
    assert out["status"] == "SELECTED"
    with pytest.raises(s1.StageRefused, match="VAL already ran"):
        s1.stage_val()
    with pytest.raises(s1.StageRefused, match="TRAIN is closed"):
        s1.stage_train()
    with pytest.raises(s1.StageRefused, match="LAB2_ALLOW_TEST"):
        s1.stage_test()
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    t = s1.stage_test()
    assert t["verdict_entry"]["verdict"] in ("UNDERPOWERED", "FAIL", "REJECTED", "INCOMPLETE", "PASS")
    assert (stage_env / "test.json").exists() and (stage_env / "test_trades.parquet").exists()
    with pytest.raises(s1.StageRefused, match="one TEST run"):
        s1.stage_test()
    with pytest.raises(s1.StageRefused, match="LAB2_ALLOW_FINAL"):
        s1.stage_final()


def test_train_kill_is_not_rerolled(stage_env, monkeypatch):
    monkeypatch.setattr(s1, "gate_verdict_train", lambda stats: {"status": "GATE_FAIL", "per_checkpoint": {}})
    s1.stage_train()
    with pytest.raises(s1.StageRefused, match="not re-rolled"):
        s1.stage_train()
    out = s1.stage_train(rerun_reason="re-consolidated parquet (audit fix 1)")
    assert out["rerun_reason"] and list(stage_env.glob("train_prev_*.json"))


def test_prereg_change_after_lock_refuses(stage_env, monkeypatch):
    monkeypatch.setattr(s1, "gate_verdict_train", lambda stats: {"status": "GATE_FAIL", "per_checkpoint": {}})
    s1.stage_train()
    (stage_env / "PREREG.md").write_text((stage_env / "PREREG.md").read_text() + "\nedited\n")
    with pytest.raises(s1.StageRefused, match="changed"):
        s1.prerequisites("val")
    with pytest.raises(s1.StageRefused, match="changed"):
        s1.stage_train()


def test_train_refuses_without_b1(tmp_path, monkeypatch, tmp_ledger):
    monkeypatch.setenv("LAB2_S1_DIR", str(tmp_path))
    (tmp_path / "PREREG.md").write_text("x")
    monkeypatch.setattr(s1, "coverage_counts", lambda split: {
        "split": split, "usable": 0, "s1_universe": 0, "b1_covered": 0, "b1_frac": 0.0, "split_complete": False,
        "chain_hours_scanned_frac": 0.0, "days_full": 0, "days_expected": 4.0, "b1_file": False})
    with pytest.raises(s1.StageRefused, match="P4"):
        s1.stage_train()
    assert not (tmp_path / "prereg.lock").exists() and not (tmp_path / "train.json").exists()


def test_cli_refusal_exit_code(tmp_path, monkeypatch, tmp_ledger, capsys):
    monkeypatch.setenv("LAB2_S1_DIR", str(tmp_path))
    assert s1.main(["--stage", "val"]) == 2
    assert "REFUSED" in capsys.readouterr().err

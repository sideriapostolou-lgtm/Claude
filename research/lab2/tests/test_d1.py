"""D1 tests: feature correctness on hand-built tapes, no lookahead, the stop rule, stage prerequisites."""

import json
import math
import shutil

import numpy as np
import pandas as pd
import pytest

from conftest import LAB2, POOLED, V0, make_frames

import common as C  # noqa: E402
import d1  # noqa: E402

SOL = C.SolUsd(fallback=100.0)
X0_LAMP, Y0_RAW = 85 * 10**9, 206_900_000 * 10**6       # constant pool reserves (lamports, raw token units)
CX0, CY0 = 30 * 10**9, 1_073_000_000 * 10**6           # curve virtual reserves


def addr(i: int) -> str:
    return d1.b58encode(bytes([i]) * 32)


CREATOR, COMPLETER, AGENT = addr(1), addr(2), addr(3)
H_CREATOR, H_COMPLETER, H_AGENT, H_POOLED = (d1.wallet_h(a) for a in (CREATOR, COMPLETER, AGENT, POOLED))


@pytest.fixture(autouse=True)
def _fresh_cache():
    d1.clear_cache()
    yield
    d1.clear_cache()


class Tape:
    """B1-shaped rows. ``frame()`` orders them by time (insertion order breaks ties) and assigns slots that are
    monotonic in time; an explicit slot (curve creation slot) is kept as given."""

    def __init__(self, mint: str) -> None:
        self.mint, self.rows = mint, []

    def add(self, ts, wallet, buy, sol, tok_m, venue=1, slot=None):
        self.rows.append({"slot": slot, "pix": 0, "ix": 0, "ts": int(ts),
                          "mint": self.mint, "venue": venue, "is_buy": bool(buy), "wallet_h": int(wallet),
                          "usol": int(round(sol * 1e9)), "tok": int(round(tok_m * 1e12)),
                          "x0": X0_LAMP if venue == 1 else CX0, "y0": Y0_RAW if venue == 1 else CY0,
                          "fees": 0, "virt_ksol": int(V0 * 1e6) if venue == 1 else 0, "src": 0,
                          "seq": len(self.rows)})

    def frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.rows).sort_values(["ts", "seq"], kind="stable").reset_index(drop=True)
        slots, last = [], 0
        for s in df["slot"]:
            if s is None or (isinstance(s, float) and math.isnan(s)):
                s = max(last + 1, 1000)
            assert s >= last, "explicit slots must be monotonic in time"
            slots.append(int(s))
            last = int(s)
        df["slot"] = np.asarray(slots, np.int64)
        df["tx_idx"] = np.arange(len(df))
        df["wallet_h"] = df["wallet_h"].astype(np.uint64)
        return df.drop(columns=["seq"])


def crafted_bars(mint, pool, g, prices, vol=10.0, agent_sol=2.4):
    """Minute bars on X * y = const following ``prices`` (one close per minute; the last one repeats)."""
    k = 84.990359 * 206.9e6
    m0 = int(g) // 60 * 60
    rows, prev = [], 84.990359 / 206.9e6
    for j in range(186):
        p = prices[min(j, len(prices) - 1)]
        X, y = math.sqrt(k * p), math.sqrt(k / p)
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 6, "n_sells": 6, "n_dust": 0, "buy_sol": vol / 2,
                     "sell_sol": vol / 2, "buy_tok": vol / 2 / p, "sell_tok": vol / 2 / p, "n_buyers": 5,
                     "n_sellers": 5, "top5_buy_sol": vol / 2, "open": prev, "high": max(prev, p) * 1.01,
                     "low": min(prev, p) * 0.99, "close": p, "x_close": X - V0, "y_close": y, "mint": mint,
                     "pool": pool, "g_ts": g, "minute_idx": j, "agent_buy_sol": agent_sol if j < 6 else 0.0,
                     "price_repaired": 0})
        prev = p
    return pd.DataFrame(rows)


def dip_prices():
    p0 = 84.990359 / 206.9e6
    up = [p0 * (1 + 0.2 * j) for j in range(6)]                 # minute 5: 2 x p0
    down = [2 * p0 - (0.7 * p0) * (j / 5) for j in range(1, 6)]  # minutes 6-10: down to 1.3 x p0
    return up + down + [1.3 * p0]


def hand_frames(n=4, tape_fn=None, delay=900, **over):
    """Coin 0: a slow ORGANIC graduate (created g - delay) with real-looking wallets and a crafted dip path."""
    g, c, b = make_frames(n=n, seed=7, slow_every=0, agent_every=1)
    g, c = g.copy(), c.copy()
    gts = int(g.loc[0, "g_ts"])
    m, pool = g.loc[0, "mint"], g.loc[0, "pool"]
    g.loc[0, ["c_ts", "c_slot", "creator", "completer30", "completer_sol", "curve_top3_buy_sol", "curve_buy_sol",
              "curve_n_buyers"]] = [gts - delay, 500, CREATOR, COMPLETER, 10.0, 30.0, 90.0, 40]
    for k, v in over.items():
        g.loc[0, k] = v
    c.loc[0, "agent_wallet"] = AGENT
    c.loc[0, "w120_top10"] = json.dumps([[POOLED, 9.0, 0.0], ["Wa", 5.0, 0.0], [AGENT, 4.0, 0.0]])
    b = pd.concat([b[b["mint"] != m], crafted_bars(m, pool, gts, dip_prices())], ignore_index=True)
    tr = None
    if tape_fn is not None:
        tape = Tape(m)
        tape_fn(tape, gts, gts - delay)
        tr = tape.frame()
    return g, c, b, tr, m, gts


def build(g, c, b, tr, split="train"):
    return C.Dataset.from_frames(split, g, c, b, census=C.Census.empty(), sol=SOL, trades=tr, guard=False)


# wallet ids used by the hand tape (plain ints; only the creator / completer / agent / pooled are real hashes)
BU, SN, L1, BOT, WASH, MECH, ORPH = 101, 102, 301, 601, 701, 801, 901
E = [200 + i for i in range(1, 18)]
O = [400 + i for i in range(1, 13)]
N1, N2 = 501, 502


def tape_common(t: Tape, G: int, Cr: int, kind: str = "cap"):
    t.add(Cr, H_CREATOR, True, 1.0, 50, venue=0, slot=500)
    t.add(Cr, BU, True, 1.0, 40, venue=0, slot=500)
    t.add(Cr + 30, SN, True, 0.5, 20, venue=0, slot=510)
    for i, w in enumerate(E):
        t.add(Cr + 100 + i, w, True, 0.5, 10, venue=0, slot=600 + i)
    t.add(Cr + 400, L1, True, 2.0, 30, venue=0, slot=700)
    t.add(G - 5, H_COMPLETER, True, 5.0, 30, venue=0, slot=800)
    for k in range(4):
        t.add(G + 2 + 12 * k, H_AGENT, True, 0.6, 1)
    for i, w in enumerate(O):
        t.add(G + 120 + 5 * i, w, True, 1.0, 2)
    if kind == "cap":                      # insiders distribute early, then late holders capitulate
        t.add(G + 300, H_CREATOR, False, 10.0, 50)
        t.add(G + 310, BU, False, 8.0, 40)
        for i, w in enumerate(E):
            t.add(G + 320 + i, w, False, 1.0, 10)
        t.add(G + 340, SN, False, 2.0, 20)
        t.add(G + 350, H_COMPLETER, False, 5.0, 25)
    for k in range(7):
        t.add(G + 700 + 60 * k, MECH, True, 0.3, 0.6)
    t.add(G + 800, ORPH, False, 0.5, 3)
    t.add(G + 900, BOT, True, 0.2, 0.4)
    t.add(G + 905, BOT, False, 0.2, 0.4)
    t.add(G + 910, BOT, True, 0.2, 0.4)
    t.add(G + 915, BOT, False, 0.2, 0.4)
    t.add(G + 930, WASH, True, 1.0, 2)
    t.add(G + 950, WASH, False, 0.99, 2)
    if kind == "cap":
        for i in range(8):
            t.add(G + 1030 + 10 * i, O[i], False, 0.6, 2)
    else:                                  # distribution: early insiders sell at 4x their cost
        for i in range(5):
            t.add(G + 1030 + 10 * i, E[i], False, 2.0, 10)
        t.add(G + 1090, O[0], False, 0.6, 2)
    t.add(G + 1100, BOT, True, 0.2, 0.4)
    t.add(G + 1110, WASH, True, 0.3, 0.6)
    t.add(G + 1120, H_POOLED, True, 1.0, 2)
    t.add(G + 1130, H_AGENT, True, 0.6, 1)
    for i in range(4):
        t.add(G + 1140 + i, O[8 + i], True, 0.5, 1)
    t.add(G + 1145, N1, True, 0.5, 1)
    t.add(G + 1146, N2, True, 0.5, 1)
    if kind == "cap":
        t.add(G + 1150, H_COMPLETER, False, 0.3, 1)


# =========================================================================== hashing


def test_cityhash_matches_clickhouse_pairs():
    pairs = [(9740399439260290013, "168Q2pG7tYAoNXLQcA7yJufVzrUnZr85W5eYTBfp5eB"),
             (13548937726806623243, "14Bzxa1JbhAcCgY5qDk5ubuHVq98ecGCxzWgnCKpVRYG")]
    for h, a in pairs:
        assert d1.wallet_h(a) == h
    assert d1.b58decode(d1.b58encode(bytes(range(1, 33)))) == bytes(range(1, 33))
    assert d1.wallet_h("not-base58-0OIl") is None and d1.wallet_h("") is None and d1.wallet_h(None) is None


def test_cityhash_all_real_pairs_on_disk():
    p = C.flow_dir() / "dev" / "test_b1.json"
    if not p.exists():
        pytest.skip("B1 dev query result not on disk")
    d = json.loads(p.read_text())
    i = d["columns"].index("wallet_dict")
    pairs = [(h, a) for r in d["rows"] for h, a in r[i]]       # hash pairs only: no prices or returns are read
    assert len(pairs) > 100 and all(d1.wallet_h(a) == h for h, a in pairs)


# =========================================================================== feature correctness (hand-built)


def test_hand_features_cap_exact():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    f = d1.flow_features(ds.asof(m, G + 1220))                # tau = G + 1200: window (G + 1020, G + 1200]
    assert f["ok"]
    assert f["n_bundle"] == 2 and f["n_snipers"] == 20 and f["n_transferees"] == 1
    assert f["n_insiders"] == 22                              # CR, BU, SN, 17 early, COMPLETER, orphan seller
    assert f["n_bots"] == 1 and f["n_wash"] == 2 and f["n_mech"] == 1   # BOT's quick round trip is also WASH
    assert f["sell_sol3"] == pytest.approx(5.1)
    assert f["insider_sell_sol3"] == pytest.approx(0.3)
    assert f["ins_sell_share3"] == pytest.approx(0.3 / 5.1)
    assert f["sopr3"] == pytest.approx(5.1 / (8.0 + 5.0 * 5 / 30 / 5))   # completer basis 0.8333 / 5M per 1M
    assert f["n_sellers3"] == 9
    assert f["full_exit_share3"] == pytest.approx(4.8 / 5.1)
    assert f["insider_peak_tok"] == pytest.approx(310e6)
    assert f["insider_hold_tok"] == pytest.approx(4e6)
    assert f["insider_rem"] == pytest.approx(4 / 310)
    assert f["org_buyers3"] == 6                              # O9-O12, N1, N2; BOT/WASH/POOLED/AGENT/MECH excluded
    assert f["agent_tok"] == pytest.approx(5e6)
    assert d1.classify(f, "strict") == "CAP" and d1.classify(f, "loose") == "CAP"


def test_hand_features_dist_exact():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "dist"))
    ds = build(g, c, b, tr)
    f = d1.flow_features(ds.asof(m, G + 1220))
    assert f["sell_sol3"] == pytest.approx(10.6)
    assert f["ins_sell_share3"] == pytest.approx(10.0 / 10.6)
    assert f["sopr3"] == pytest.approx(10.6 / (5 * 0.5 + 1.0))
    assert f["n_sellers3"] == 6
    assert f["insider_rem"] == pytest.approx(260 / 310)
    assert d1.classify(f, "strict") == "DIST"


def test_exit_features_exact():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    f = d1.flow_features(ds.asof(m, G + 1220), tau_entry=G + 1000)
    assert f["org_net5"] == pytest.approx((4 * 0.5 + 2 * 0.5) - 8 * 0.6)    # (G + 900, G + 1200]
    assert f["orphan_share10"] == pytest.approx(3 / (3 + 0.4 + 0.4 + 2 + 16 + 1))
    assert f["creator_sold_after"] == pytest.approx(0.0)
    assert f["insider_growth"] == pytest.approx(-1e6 / 1e9)
    pv = C.PositionView(mint=m, t_dec=G + 1020, t_in=G + 1050, entry_price=1.0, tokens=1.0, sol_in=0.1, peak=1.0,
                        bars_held=3, unrealized=0.0, exits=C.ExitSpec(), state={}, is_placebo=True)
    assert d1._flow_exit(ds.asof(m, G + 1220), pv).reason == "org_net5"


def test_no_sells_is_null_never_cap():
    def tape(t, G, Cr):
        t.add(Cr, H_CREATOR, True, 1.0, 50, venue=0, slot=500)
        t.add(G + 100, 401, True, 1.0, 2)
    g, c, b, tr, m, G = hand_frames(tape_fn=tape)
    f = d1.flow_features(build(g, c, b, tr).asof(m, G + 1220))
    assert f["sopr3"] is None and f["ins_sell_share3"] is None and f["n_sellers3"] == 0
    assert d1.classify(f, "strict") == "MIXED" and d1.classify(f, "loose") == "MIXED"
    assert d1.classify(None) == "NA" and d1.classify({"ok": False}) == "NA"


def test_orphan_only_sells_are_infinite_sopr_and_insider():
    def tape(t, G, Cr):
        t.add(Cr, H_CREATOR, True, 1.0, 50, venue=0, slot=500)
        t.add(G + 1100, ORPH, False, 0.5, 3)
    g, c, b, tr, m, G = hand_frames(tape_fn=tape)
    f = d1.flow_features(build(g, c, b, tr).asof(m, G + 1220))
    assert math.isinf(f["sopr3"]) and f["ins_sell_share3"] == 1.0
    assert d1.classify(f) == "DIST"


def test_ledger_incremental_and_views_match_fresh_builds():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    taus = [G + 400, G + 820, G + 1100, G + 1220, G + 1000, G + 500]   # extend, then views of a longer ledger
    inc = [d1.flow_features(ds.asof(m, t)) for t in taus]
    fresh = []
    for t in taus:
        d1.clear_cache()
        fresh.append(d1.flow_features(ds.asof(m, t)))
    assert inc == fresh


def test_pooled_flag_from_trades_is_respected():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    tr = tr.assign(pooled=tr["wallet_h"] == np.uint64(401))           # O1 flagged pooled by wallet_dict
    f = d1.flow_features(build(g, c, b, tr).asof(m, G + 1220))
    assert f["n_sellers3"] == 8 and f["sell_sol3"] == pytest.approx(4.5)


# =========================================================================== E1, G1, universe


def test_e1_event_on_crafted_dip():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    cd = ds.coin(m)
    p0 = 84.990359 / 206.9e6
    t = cd.bar_start(15) + 20                       # tau = end of bar 14: window bars 0-14 hold the 2 x p0 high
    e = d1.e1_check(ds.asof(m, t))
    assert e["event"] and e["dd15"] == pytest.approx(1 - 1.3 / (2 * 1.01), rel=1e-9)
    assert e["vol_usd15"] == pytest.approx(15 * 10.0 * 100.0)
    s = ds.asof(m, t)
    burned = sum(2.4 / q for q in dip_prices()[:6])     # agent SOL x tokens per SOL of each minute's buys
    k = s.bars.X[-1] * s.bars.y[-1]
    assert d1.p_floor(s) == pytest.approx(k / (1e9 - burned) ** 2)
    late = d1.e1_check(ds.asof(m, cd.bar_start(25) + 20))    # the high left the 15-min window
    assert not late["event"] and late["nonflow_ok"]
    young = d1.e1_check(ds.asof(m, cd.bar_start(9) + 20))
    assert not young["event"] and not young["nonflow_ok"]   # age < 10 min


def test_g1_chain_classes_and_universe():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    s = ds.asof(m, G + 700)
    assert d1.g1_chain(s)["class"] == "ORGANIC" and d1.universe(s) == (True, "")
    with pytest.raises(C.NotYetKnown):
        d1.g1_chain(ds.asof(m, G + 100))
    # COMPLETED: one wallet bought >= 60 % of the last 30 SOL
    g2 = g.copy()
    g2.loc[0, "completer_sol"] = 20.0
    assert d1.universe(build(g2, c, b, tr).asof(m, G + 700)) == (False, "g1_completed")
    # instant graduate, missing creation, no B1, OPERATOR
    g3 = g.copy()
    g3.loc[0, "c_ts"] = G - 3
    assert d1.universe(build(g3, c, b, tr).asof(m, G + 700)) == (False, "instant")
    g4 = g.copy()
    g4.loc[0, "has_create"] = 0
    assert d1.universe(build(g4, c, b, tr).asof(m, G + 700))[1] == "no_creation_data"
    assert d1.universe(build(g, c, b, None).asof(m, G + 700)) == (False, "no_b1")
    c5 = c.copy()
    c5.loc[0, ["w120_buy_sol", "w120_n_buyers"]] = [900.0, 12]
    assert d1.universe(build(g, c5, b, tr).asof(m, G + 700)) == (False, "g1_operator")


def test_null_curve_inputs_are_unresolved_not_zero():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    g2 = g.copy()
    g2["curve_n_buyers"] = g2["curve_n_buyers"].astype(float)
    g2.loc[0, "curve_n_buyers"] = np.nan
    assert d1.g1_chain(build(g2, c, b, tr).asof(m, G + 700))["class"] == "UNRESOLVED"


# =========================================================================== the strategy


def test_strategy_enters_at_first_cap_event_and_dist_event():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    t1 = C.run_trades(ds, d1.d1_strategy, d1.variant_params("V1"), C.FillConfig(), mints=[m])
    assert len(t1) == 1 and t1.loc[0, "tag"] == "CAP"
    tau = t1.loc[0, "t_dec"] - 20
    assert G + 1145 <= tau < G + 1210                 # the only grid minute where every CAP condition holds
    assert t1.loc[0, "max_hold_s"] == 1800 and t1.loc[0, "stop_pct"] == 0.15 and t1.loc[0, "take_profit_pct"] == 0.25
    t2 = C.run_trades(ds, d1.d1_strategy, d1.event_params("DIST", 30), C.FillConfig(), mints=[m])
    assert len(t2) == 1 and t2.loc[0, "tag"] == "DIST"
    assert G + 800 <= t2.loc[0, "t_dec"] - 20 < G + 860   # the orphan sell at G + 800 is a transferee sell
    assert t2.loc[0, "max_hold_s"] == 1800 and pd.isna(t2.loc[0, "stop_pct"])
    t3 = C.run_trades(ds, d1.d1_strategy, d1.event_params("ALL", 15), C.FillConfig(), mints=[m])
    assert len(t3) == 1 and t3.loc[0, "t_dec"] - 20 - G >= d1.E1_MIN_AGE_S
    others = [x for x in ds.mints if x != m]          # no B1 rows -> skipped
    assert len(C.run_trades(ds, d1.d1_strategy, d1.variant_params("V1"), C.FillConfig(), mints=others)) == 0


def test_strategy_never_enters_after_b1_window_or_at_trade_cap(monkeypatch):
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    s = ds.asof(m, G + d1.B1_HORIZON_S + 100)
    assert d1.flow_features(s)["why"] == "beyond_b1_window"
    assert d1.d1_strategy(s, d1.variant_params("V1"), None) is C.SKIP
    monkeypatch.setattr(d1, "B1_MAX_TRADES", 30)
    f = d1.flow_features(ds.asof(m, G + 1220))
    assert f == {"ok": False, "why": "b1_trade_cap"}


def test_s1_exit_set_fires_flow_exit():
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    p = d1.variant_params("V3")

    def strat(snap, params, pos):            # forced entry at G + 1000, then D1's own exit logic
        if pos is None:
            return C.Enter(exits=d1.exit_spec(p)) if snap.tau >= G + 960 else None
        return d1.d1_strategy(snap, p, pos)
    t = C.run_trades(ds, strat, p, C.FillConfig(), mints=[m])
    assert len(t) == 1 and t.loc[0, "reason"].startswith("signal:")
    assert t.loc[0, "trail_pct"] == 0.30 and t.loc[0, "max_hold_s"] == 5400


def test_train_grid_is_the_preregistered_one():
    grid = d1.train_grid()
    assert len(grid) == 18
    assert sum(h == d1.HYP for h, _ in grid) == 3 <= C.VARIANT_LIMITS["D1"]
    assert len({C.params_hash(p) for _, p in grid}) == 18
    assert all(p["version"] == d1.VERSION for _, p in grid)
    assert {(p["event_class"], p["hold_min"]) for h, p in grid if h == d1.HYP_EVENT} == \
        {(cl, hm) for cl in ("CAP", "CAP_LOOSE", "DIST", "MIXED", "ALL") for hm in (15, 30, 60)}
    prereg = (LAB2 / "D1" / "PREREG.md").read_text()
    for v, (cap, ex) in d1.VARIANTS.items():
        assert f"| {v} | CAP | {cap} | `{ex}` |" in prereg


# =========================================================================== no lookahead


def random_tape(rng, mint, G, Cr, n_min=130, rate=5.0, insiders_exit=False, loss_bias=1.0):
    """Random B1 tape with consistent wallet positions: sells are a fraction of what the wallet holds, priced at
    its average cost x ``loss_bias`` x noise; 5 % of sells are orphan sells by fresh wallets. ``insiders_exit``:
    every curve buyer sells out at 6x its cost at G + 500-700 s (a distribution phase), so later dips can be
    capitulation."""
    t = Tape(mint)
    pos: dict[int, float] = {}
    cost: dict[int, float] = {}

    def buy(ts, w, sol, tok, **kw):
        t.add(ts, w, True, sol, tok, **kw)
        pos[w], cost[w] = pos.get(w, 0.0) + tok, cost.get(w, 0.0) + sol

    def sell(ts, w, frac, mult):
        q = pos[w] * frac
        sol = cost[w] * frac * mult
        if sol < 0.011 or q <= 0:
            return
        t.add(ts, w, False, sol, q)
        pos[w] -= q
        cost[w] -= cost[w] * frac

    buy(Cr, H_CREATOR, 1.0, 40, venue=0, slot=500)
    buy(Cr, 11, 1.2, 40, venue=0, slot=500)
    for i in range(30):
        buy(Cr + 5 + i * max((G - Cr - 20) // 31, 1), 1000 + i, float(rng.uniform(0.2, 2)), float(rng.uniform(5, 20)),
            venue=0, slot=510 + i)
    buy(G - 3, H_COMPLETER, 4.0, 25, venue=0, slot=600)
    insiders = [H_CREATOR, 11, H_COMPLETER] + [1000 + i for i in range(30)]
    if insiders_exit:
        for k, w in enumerate(insiders):
            sell(G + 500 + 6 * k, w, 1.0, 6.0)
    for k in range(25):
        t.add(G + 2 + 12 * k, H_AGENT, True, 0.6, 1)
    for j in range(n_min):
        for ts in np.sort(rng.uniform(G + 60 * j, G + 60 * (j + 1), int(rng.poisson(rate)))):
            held = [w for w, q in pos.items() if q > 0.05 and not (insiders_exit and w in insiders)]
            r = rng.random()
            if r < 0.45 or not held:
                w = int(rng.choice(held)) if held and rng.random() < 0.3 else int(2000 + rng.integers(0, 400))
                sol = float(rng.uniform(0.05, 2))
                buy(ts, w, sol, sol / float(rng.uniform(0.3, 0.5)))
            elif r < 0.95:
                sell(ts, int(rng.choice(held)), float(rng.uniform(0.3, 1.0)), loss_bias * float(rng.uniform(0.6, 1.4)))
            else:
                t.add(ts, int(5000 + rng.integers(0, 1000)), False, 0.3, 2.0)    # orphan
            if rng.random() < 0.02:
                t.add(ts + 0.5, H_POOLED, bool(rng.random() < 0.5), 0.5, 1.0)
    return t.frame()


def random_frames(seed=0, n=6, t0=None, **tape_kw):
    rng = np.random.default_rng(seed)
    g, c, b = make_frames(n=n, seed=seed + 11, slow_every=0, agent_every=1, t0=t0)
    g, c = g.copy(), c.copy()
    tapes = []
    for i in range(n):
        G, mint = int(g.loc[i, "g_ts"]), g.loc[i, "mint"]
        Cr = G - int(rng.integers(300, 3000))
        g.loc[i, ["c_ts", "c_slot", "creator", "completer30", "completer_sol", "curve_top3_buy_sol",
                  "curve_buy_sol", "curve_n_buyers"]] = [Cr, 500, CREATOR, COMPLETER, 8.0, 25.0, 90.0, 40]
        c.loc[i, "agent_wallet"] = AGENT
        c.loc[i, "w120_top10"] = json.dumps([[POOLED, 9.0, 0.0], ["Wa", 5.0, 0.0], [AGENT, 4.0, 0.0]])
        tapes.append(random_tape(rng, mint, G, Cr, **tape_kw))
    return g, c, b, pd.concat(tapes, ignore_index=True)


def garble_after(g, c, b, tr, mint, tau, rng):
    """Every trade and bar of ``mint`` after tau becomes garbage (values changed, rows added and removed)."""
    tr = tr.copy()
    late = (tr["mint"] == mint) & (tr["ts"] > tau)
    tr.loc[late, "usol"] = rng.integers(10**7, 10**11, late.sum())
    tr.loc[late, "tok"] = rng.integers(10**9, 10**14, late.sum())
    tr.loc[late, "is_buy"] = rng.random(late.sum()) < 0.5
    tr.loc[late, "wallet_h"] = rng.integers(1, 10**6, late.sum()).astype(np.uint64)
    drop = tr.index[late][rng.random(late.sum()) < 0.3]
    extra = tr[late].head(20).copy()
    extra["slot"] += 1
    extra["tx_idx"] += 10_000
    extra["wallet_h"] = np.uint64(H_CREATOR)
    tr = pd.concat([tr.drop(index=drop), extra], ignore_index=True)
    b = b.astype({k: "float64" for k in b.columns if pd.api.types.is_numeric_dtype(b[k]) and k != "minute_ts"})
    fut = (b["mint"] == mint) & (b["minute_ts"] + 60 > tau)
    for col in ("buy_sol", "sell_sol", "n_sellers", "n_buyers", "agent_buy_sol"):
        b.loc[fut, col] = rng.uniform(0, 1e3, fut.sum())
    px = rng.uniform(1e-9, 1e-5, fut.sum())
    b.loc[fut, "open"], b.loc[fut, "close"], b.loc[fut, "high"], b.loc[fut, "low"] = px, px * 2, px * 3, px / 3
    b.loc[fut, "y_close"] = rng.uniform(1e6, 1e9, fut.sum())
    return g, c, b, tr


@pytest.mark.parametrize("seed", range(4))
def test_features_unchanged_by_garbage_after_tau(seed):
    rng = np.random.default_rng(100 + seed)
    g, c, b, tr = random_frames(seed)
    clean = build(g, c, b, tr)
    for _ in range(12):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        G = clean.coin(m).g
        t = G + float(rng.uniform(600, 7000))
        tau = t - C.DECISION_LAG_S
        dirty = build(*garble_after(g, c, b, tr, m, tau, rng))
        d1.clear_cache()
        f0 = d1.flow_features(clean.asof(m, t), tau_entry=tau - 400)
        e0, u0 = d1.e1_check(clean.asof(m, t)), d1.universe(clean.asof(m, t))
        d1.clear_cache()
        f1 = d1.flow_features(dirty.asof(m, t), tau_entry=tau - 400)
        e1, u1 = d1.e1_check(dirty.asof(m, t)), d1.universe(dirty.asof(m, t))
        assert f0 == f1 and e0 == e1 and u0 == u1
        assert f0["ok"] and f0["n_trades"] > 0


def test_decisions_before_T_unchanged_by_future_garbage():
    rng = np.random.default_rng(5)
    g, c, b, tr = random_frames(3, n=6)
    clean = build(g, c, b, tr)
    for p in (d1.variant_params("V3"), d1.event_params("ALL", 15), d1.event_params("MIXED", 60)):
        for m in clean.mints[:4]:
            T = clean.coin(m).g + float(rng.uniform(700, 3000))
            dirty = build(*garble_after(g, c, b, tr, m, T - C.DECISION_LAG_S, rng))
            d1.clear_cache()
            a = C.run_trades(clean, d1.d1_strategy, p, C.FillConfig(), mints=[m])
            d1.clear_cache()
            z = C.run_trades(dirty, d1.d1_strategy, p, C.FillConfig(), mints=[m])
            a_in = a.loc[a["t_dec"] <= T, ["t_dec", "tag"]].values.tolist()
            z_in = z.loc[z["t_dec"] <= T, ["t_dec", "tag"]].values.tolist()
            assert a_in == z_in
            # an exit decided before T is identical too
            done = a[(a["t_dec"] <= T) & (a["t_out"] + C.DECISION_LAG_S <= T - 60)]
            if len(done):
                assert z.loc[0, "t_out"] == done.iloc[0]["t_out"] and z.loc[0, "reason"] == done.iloc[0]["reason"]


# =========================================================================== the stop rule and selection


def _trades(means, n, coins=None, seed=0, sd=0.05):
    rng = np.random.default_rng(seed)
    coins = coins or n
    return pd.DataFrame({"mint": [f"M{i % coins}" for i in range(n)], "ret_net": rng.normal(means, sd, n),
                         "t_in": np.arange(n, dtype=float)})


@pytest.mark.parametrize("cap,dist,status", [(0.10, -0.02, "PASS"), (0.05, -0.02, "WEAK"), (0.02, 0.0, "KILL"),
                                             (-0.10, 0.05, "KILL")])
def test_stop_rule_statuses(cap, dist, status):
    r = d1.stop_rule(_trades(cap, 60, seed=1), _trades(dist, 50, seed=2), B=2000)
    assert r["status"] == status
    assert r["cap_minus_dist"] == pytest.approx(r["mean_a"] - r["mean_b"])


def test_stop_rule_underpowered_and_ci_needed():
    assert d1.stop_rule(_trades(0.3, 19), _trades(0.0, 50), B=500)["status"] == "UNDERPOWERED"
    assert d1.stop_rule(_trades(0.3, 50), _trades(0.0, 5), B=500)["status"] == "UNDERPOWERED"
    noisy = d1.stop_rule(_trades(0.12, 25, sd=1.5, seed=3), _trades(0.0, 25, sd=1.5, seed=4), B=2000)
    assert noisy["status"] in ("WEAK", "KILL")          # >= 10 points is not enough when the CI includes 0


def test_diff_ci_resamples_coins_jointly():
    a = _trades(0.1, 40, coins=4, seed=1, sd=0.3)
    b = _trades(0.0, 40, coins=40, seed=2, sd=0.3)
    wide = d1.diff_ci(a, b, B=2000)
    narrow = d1.diff_ci(_trades(0.1, 40, coins=40, seed=1, sd=0.3), b, B=2000)
    assert wide["ci95"][1] - wide["ci95"][0] > narrow["ci95"][1] - narrow["ci95"][0]


def test_shortlist_rule():
    rows = {"V1": {"n": 40, "n_coins": 30, "mean": 0.01}, "V2": {"n": 80, "n_coins": 50, "mean": 0.02},
            "V3": {"n": 29, "n_coins": 29, "mean": 0.5}}
    sl = d1.shortlist_rule(rows)
    assert sl["status"] == "SHORTLISTED" and sl["variants"] == ["V2", "V1"]
    assert sl["event_configs"][0]["event_class"] == "CAP_LOOSE" and sl["event_configs"][1]["event_class"] == "DIST"
    assert all(p["hold_min"] == 30 for p in sl["event_configs"])
    none = d1.shortlist_rule({v: {"n": 3, "n_coins": 3, "mean": 1.0} for v in d1.VARIANTS})
    assert none["status"] == "SHORTLISTED_UNDERPOWERED" and none["variants"] == ["V1", "V2"]
    assert none["event_configs"][0]["event_class"] == "CAP"


def test_val_select_and_verdict():
    gate_ok = {"status": "WEAK"}
    rows = {"V1": {"n": 20, "mean": -0.01}, "V2": {"n": 30, "mean": 0.02}}
    assert d1.val_select(rows, ["V1", "V2"], gate_ok)["selected"] == "V2"
    assert d1.val_select({"V1": {"n": 3, "mean": 0.5}}, ["V1"], gate_ok)["selected"] == "V1"
    assert d1.val_select(rows, ["V1", "V2"], {"status": "KILL"})["status"] == "KILLED"
    assert d1.d1_verdict({"verdict": "PASS"}, {"status": "PASS"})["verdict"] == "PASS"
    assert d1.d1_verdict({"verdict": "PASS"}, {"status": "WEAK"})["verdict"] == "FAIL"
    assert d1.d1_verdict({"verdict": "PASS"}, {"status": "UNDERPOWERED"})["verdict"] == "INCOMPLETE"
    assert d1.d1_verdict({"verdict": "UNDERPOWERED"}, {"status": "PASS"})["verdict"] == "UNDERPOWERED"
    assert d1.d1_verdict({"verdict": "PASS"}, {"status": "PASS"}, confirm={"mean": -0.01})["verdict"] == "FAIL"


# =========================================================================== stage prerequisites and the CLI


@pytest.fixture
def lab(tmp_path, monkeypatch):
    dd = tmp_path / "D1"
    dd.mkdir()
    shutil.copy(LAB2 / "D1" / "PREREG.md", dd / "PREREG.md")
    monkeypatch.setenv("LAB2_D1_DIR", str(dd))
    monkeypatch.setenv("LAB2_TRIALS", str(tmp_path / "trials.json"))
    monkeypatch.setenv("LAB2_SHORTLISTS", str(tmp_path / "shortlists"))
    for k in ("LAB2_ALLOW_TEST", "LAB2_ALLOW_CONFIRM", "LAB2_ALLOW_FINAL"):
        monkeypatch.delenv(k, raising=False)
    return dd


def _refused(stage, match):
    with pytest.raises(d1.StageRefused, match=match):
        d1.prerequisites(stage)


def test_prerequisites_chain(lab, monkeypatch):
    (lab / "PREREG.md").rename(lab / "x.md")
    _refused("train", "PREREG")
    (lab / "x.md").rename(lab / "PREREG.md")
    d1.prerequisites("train")
    _refused("val", "no TRAIN run yet")
    d1._lock_prereg()
    (lab / "train.json").write_text(json.dumps({"status": "PARTIAL"}))
    _refused("val", "shortlist")
    (lab / "train.json").write_text(json.dumps({"status": "SHORTLISTED"}))
    _refused("val", "no written VAL shortlist")
    C.write_shortlist(d1.HYP, [d1.variant_params("V1")])
    C.write_shortlist(d1.HYP_EVENT, [d1.event_params("CAP", 30), d1.event_params("DIST", 30)])
    d1.prerequisites("val")
    _refused("test", "VAL run first")
    _refused("final", "never FINAL before TEST")
    _refused("confirm", "TEST run first")
    (lab / "val.json").write_text(json.dumps({"status": "KILLED"}))
    _refused("val", "already ran on VAL")
    _refused("train", "TRAIN is closed")
    _refused("test", "does not go to TEST")
    (lab / "val.json").write_text(json.dumps({"status": "SELECTED"}))
    _refused("test", "LAB2_ALLOW_TEST")
    monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
    d1.prerequisites("test")
    (lab / "test.json").write_text("{}")
    _refused("test", "one TEST run")
    with open(lab / "PREREG.md", "a") as fh:
        fh.write("\nedited after the lock\n")
    _refused("val", "changed after the first TRAIN run")
    _refused("test", "changed after the first TRAIN run")


def test_cli_exit_code_2_on_refusal(lab, capsys):
    (lab / "PREREG.md").unlink()
    assert d1.main(["--stage", "train"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_data_not_ready_refuses(lab, monkeypatch):
    monkeypatch.setattr(d1, "b1_coverage", lambda s: {"coverage_complete": False, "b1_file": False, "frac": 0.0,
                                                      "with_b1": 0, "b1_eligible": 10, "days_full": 0,
                                                      "days_expected": 4, "chain_hours_scanned_frac": 0.1})
    with pytest.raises(d1.StageRefused, match="P4"):
        d1.check_data("train")
    cov = d1.check_data("train", allow_partial=True)
    assert len(cov["problems"]) >= 2


def test_stages_end_to_end_on_synthetic_data(lab, monkeypatch):
    """train -> val -> test -> confirm/final refusals, on small synthetic splits (mechanics, not results)."""
    kw = {"rate": 14.0, "insiders_exit": True, "loss_bias": 0.5}
    splits = {"train": random_frames(21, n=10, t0=C.utc_ts("2026-10-02 00:00"), **kw),
              "val": random_frames(22, n=8, t0=C.utc_ts("2026-10-05 02:00"), **kw),
              "test": random_frames(23, n=8, t0=C.utc_ts("2026-10-06 14:00"), **kw)}
    monkeypatch.setattr(d1, "load_split", lambda s: build(*splits[s], split=s))
    monkeypatch.setattr(d1, "check_data", lambda s, allow_partial=False: {"split": s, "problems": []})
    monkeypatch.setattr(d1, "fill_sensitivity", lambda ds, p, reveal=True: {})
    tr = d1.stage_train()
    assert tr["status"] in ("SHORTLISTED", "SHORTLISTED_UNDERPOWERED")
    assert (lab / "train.json").exists() and (lab / "train.md").exists() and (lab / "prereg.lock").exists()
    assert len(tr["events"]) == 15 and set(tr["variants"]) == set(d1.VARIANTS)
    assert tr["events"]["CAP@30"]["n"] > 0 and tr["events"]["DIST@30"]["n"] > 0   # both classes occur
    assert tr["variants"]["V2"]["n"] >= tr["variants"]["V1"]["n"] > 0             # loose CAP fires at least as often
    assert C.n_trials() == sum(C.BASELINE_TRIALS.values()) + 18
    d1.stage_train()                                    # a re-run adds no trial
    assert C.n_trials() == sum(C.BASELINE_TRIALS.values()) + 18
    with pytest.raises(d1.StageRefused):
        d1.stage_test()
    v = d1.stage_val()
    assert v["status"] in ("SELECTED", "KILLED") and v["gate"]["status"] in ("PASS", "WEAK", "KILL", "UNDERPOWERED")
    with pytest.raises(d1.StageRefused, match="TRAIN is closed"):
        d1.stage_train()
    with pytest.raises(d1.StageRefused):
        d1.stage_val()
    if v["status"] == "SELECTED":
        monkeypatch.setenv("LAB2_ALLOW_TEST", "1")
        out = d1.stage_test()
        assert out["d1_verdict"]["verdict"] in ("PASS", "FAIL", "UNDERPOWERED", "INCOMPLETE", "REJECTED")
        assert (lab / "test.json").exists() and (lab / "test_trades.parquet").exists() or out["summary"]["n"] == 0
        with pytest.raises(d1.StageRefused, match="one TEST run"):
            d1.stage_test()

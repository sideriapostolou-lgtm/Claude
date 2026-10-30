"""B1 for the backfill phase P4b: the fetch selection IS the S1 universe (the S1 and D1 coverage denominators),
windows [c_ts, g_ts + 7200), counts only, in the format the backfill reads; S1 and D1 run without the old
20,000-trade cap and refuse tau >= g + 7200 (B1 holds ts < g + 7200)."""

import importlib.util
import json
import sys

import numpy as np
import pytest

import b1_select
import common as C
import d1
import s1
from conftest import LAB2, make_frames

SOL = C.SolUsd(fallback=100.0)


@pytest.fixture(autouse=True)
def _fresh_caches():
    s1.clear_cache()
    d1.clear_cache()
    yield
    s1.clear_cache()
    d1.clear_cache()


def _flow_b1c():
    name = "flow_b1c_for_lab2_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, LAB2.parent / "flow" / "b1c.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod            # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


def sel_frames():
    """make_frames coins: every 4th one has no CreateEvent (slow_every), the rest are instant (c = g - 1..4 s).
    Half of the instant ones become real non-instant graduates (created g - 900); one of those is Mayhem."""
    g, c, b = make_frames(n=12, seed=4, slow_every=4, agent_every=0)
    g = g.copy()
    fast = list(g.index[g["has_create"] == 1])
    for k, i in enumerate(fast):
        if k % 2 == 0:
            g.loc[i, "c_ts"] = g.loc[i, "g_ts"] - 900
    g.loc[fast[2], "is_mayhem"] = 1
    return g, c, b


def test_selection_is_the_s1_universe_and_the_d1_denominator():
    g, c, b = sel_frames()
    doc = b1_select.select_from_frames(g, c, b, splits=("train",), census=C.Census.empty(), sol=SOL)
    sp = doc["train"]
    ds = C.Dataset.from_frames("train", g, c, b, census=C.Census.empty(), sol=SOL, guard=False)
    co = ds.coins
    s1_uni = co[s1.universe_mask(co)]
    d1_elig = co[(~co["curve_partial"].astype(bool)) & (co["grad_delay_s"].fillna(-1) > d1.G1_INSTANT_MAX_DELAY_S)]
    mints = [x[0] for x in sp["coins"]]
    assert set(mints) == set(s1_uni["mint"]) == set(d1_elig["mint"])
    assert len(mints) == sp["s1_universe"] == 4            # 5 created g - 900, one of them Mayhem
    for m, pool, lo, hi in sp["coins"]:
        r = g[g["mint"] == m].iloc[0]
        assert (pool, lo, hi) == (r["pool"], int(r["c_ts"]), int(r["g_ts"]) + 7200)
        assert isinstance(lo, int) and isinstance(hi, int)
    assert sp["usable"] == len(co)
    assert sp["not_in_universe"] == {"creation_not_scanned": 3, "instant_or_unknown_grad_delay": 4}
    assert sp["usable"] == 11 and sp["graduates_in_split"] == 12
    assert sp["not_usable"] == {"mayhem": 1}
    # counts and windows only: nothing price- or return-like leaves this module
    assert set(sp) == {"bounds_utc", "graduates_in_split", "usable", "not_usable", "s1_universe", "not_in_universe",
                       "window_hours", "coins"}


def test_selection_file_round_trips_into_the_backfill(tmp_path):
    g, c, b = sel_frames()
    sp = b1_select.select_from_frames(g, c, b, splits=("train", "val"), census=C.Census.empty(), sol=SOL)
    p = tmp_path / "b1_select.json"
    b1_select.write({"version": b1_select.VERSION, "snapshot": {"graduates.parquet_mtime": 0.0}, "splits": sp}, p)
    sel = _flow_b1c().load_selection(p)
    assert [c_.mint for c_ in sel["train"]] == [x[0] for x in sorted(sp["train"]["coins"], key=lambda x: (x[2], x[0]))]
    assert sel["val"] == [] and all(c_.split == "train" and c_.hi - c_.lo > 7200 for c_ in sel["train"])
    assert not list(tmp_path.glob(".*.tmp"))


def test_s1_has_no_trade_cap_and_stops_at_the_b1_horizon():
    from test_s1 import hand_ds
    assert s1.B1_MAX_TRADES is None
    ds, m, G, tr = hand_ds()
    assert s1.s1_features(ds.asof(m, G + 1200))["why"] != "b1_truncated"
    f = s1.s1_features(ds.asof(m, G + s1.B1_HORIZON_S + 20))        # tau = g + 7200 exactly
    assert f["why"] == "beyond_b1_horizon" and f["permanent"]


def test_d1_has_no_trade_cap_and_refuses_tau_at_g_plus_7200():
    from test_d1 import build, hand_frames, tape_common
    assert d1.B1_MAX_TRADES is None
    g, c, b, tr, m, G = hand_frames(tape_fn=lambda t, G, Cr: tape_common(t, G, Cr, "cap"))
    ds = build(g, c, b, tr)
    assert d1.flow_features(ds.asof(m, G + d1.B1_HORIZON_S + 20)) == {"ok": False, "why": "beyond_b1_window"}
    f = d1.flow_features(ds.asof(m, G + d1.B1_HORIZON_S + 19))       # tau = g + 7199: still inside B1
    assert f is not None and f.get("why") != "beyond_b1_window"
    f = d1.flow_features(ds.asof(m, G + 1220))
    assert f.get("why") != "b1_trade_cap"
    assert d1.placebo_eligible(ds.asof(m, G + 1220)) in (True, False)


def test_b1c_schema_has_every_column_s1_and_d1_read():
    import inspect
    import re
    srcs = [inspect.getsource(s1._build_prefix), inspect.getsource(s1._fingerprint), inspect.getsource(d1._Ledger),
            inspect.getsource(d1._checksums)]
    used = set().union(*(re.findall(r'tr\["(\w+)"\]', x) for x in srcs))
    flow_cols = set(_flow_b1c().TRADE_COLUMNS) | {"mint", "src"}
    assert {"ts", "venue", "is_buy", "usol", "tok", "wallet_h", "slot", "x0", "y0", "virt_ksol"} <= used
    assert used - {"pooled"} <= flow_cols, used - flow_cols   # pooled: added by common.load from wallet_dict only

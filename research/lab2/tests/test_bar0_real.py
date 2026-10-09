"""Bar 0 and the initial pool price against the first REAL pool trades (fixture: real rows, not synthetic).

``fixtures/bar0_real.json.gz`` holds 103 lab-tradeable coins of the unguarded splits (train, final_train): their real
graduates / b2_coins rows, B2 bars 0-4, and the pool's first trade as recorded by CryptoHouse raw rows (exact pre-trade
reserves x0, y0 and the event's virtual reserve v) and / or swap-api (``priceSol`` = the exact post-trade price).
Provenance and selection are in the fixture's ``source`` block.

Ground truth these tests pin down: ``graduates.pool_quote0`` is the PRICING reserve X0 = x0 + v (real 67.406 + virtual
17.585 = 84.990 SOL); the pool opens at pool_quote0 / pool_base0, and B2's bar 0 (open, high, low, close) equals the
real trades. Adding ``virt_sol`` to pool_quote0 (finding INIT-PRICE-NO-VIRT, reverted) opened bar 0 ~20.7 % high.
"""

import gzip
import json
import math
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

import common as C

FIX = Path(__file__).resolve().parent / "fixtures" / "bar0_real.json.gz"
SOL = C.SolUsd(fallback=100.0)
CH_TOL = 1e-6      # CryptoHouse rows give the exact pre-trade reserves
SW_TOL = 1e-4      # swap-api: pre-trade price implied by constant product (the LP fee left in the pool is ignored)


@pytest.fixture(scope="module")
def real():
    with gzip.open(FIX, "rt") as fh:
        coins = json.load(fh)["coins"]
    g = pd.DataFrame([x["graduate"] for x in coins])
    c = pd.DataFrame([x["b2_coin"] for x in coins])
    b = pd.DataFrame([r for x in coins for r in x["b2_bars"]])
    hours = set()
    for gt in g["g_ts"]:
        hours |= set(C._hours_needed(float(gt)))
    # the fixture keeps bars 0-4 only: declare every needed hour complete (hour-level rule)
    comp = C.Completeness(source="test", bar_hours=frozenset(hours), cells=None, errors={}, curve_hours=None,
                          b2_fetched={}, snapshot_utc=None)
    # census coins keep their lab third (research/lab/splits.json is not needed: the fixture records it)
    census = C.Census(split_of=MappingProxyType({x["mint"]: x["split"] for x in coins if x["split"].startswith("final_")}),
                      created_ts=MappingProxyType({}), started_ts=math.inf, created_max_ts=math.inf,
                      train_hi=float(C.FINAL_LO), val_hi=float(C.FINAL_LO))
    cds = {}
    for split in ("train", "final_train"):
        ds = C.Dataset.from_frames(split, g, c, b, census=census, sol=SOL, guard=False, completeness=comp)
        cds.update({m: ds.coin(m) for m in ds.mints})
    return {x["mint"]: x for x in coins}, cds


def _pre(fx):
    """(pre-trade price of the pool's first trade, tolerance, first-trade ts)."""
    ft = fx["first_trade"]
    if "ch" in ft:
        return ft["ch"]["pre"], CH_TOL, ft["ch"]["ts"]
    return ft["sw"]["implied_pre"], SW_TOL, ft["sw"]["ts"]


def _minute(fx):
    ft = fx["first_trade"]
    for k in ("ch", "sw"):
        if k in ft and ft[k].get("minute"):
            return ft[k]["minute"]
    return None


def test_fixture_loads_through_the_public_dataset(real):
    fx, cds = real
    assert len(fx) >= 100 and len(cds) >= 0.95 * len(fx)
    assert sum("ch" in x["first_trade"] for x in fx.values()) >= 80
    assert sum("sw" in x["first_trade"] for x in fx.values()) >= 80


def test_pool_quote0_already_includes_the_virtual_reserve(real):
    fx, _ = real
    rows = [x for x in fx.values() if "ch" in x["first_trade"]]
    assert len(rows) >= 80
    for x in rows:
        ch, gr = x["first_trade"]["ch"], x["graduate"]
        assert ch["y0"] == pytest.approx(gr["pool_base0"], rel=CH_TOL)            # it IS the pool's first trade
        assert ch["x0_real"] + ch["v"] == pytest.approx(gr["pool_quote0"], rel=CH_TOL)
        assert ch["x0_real"] / gr["pool_quote0"] == pytest.approx(0.7931, abs=2e-3)  # 67.406 / 84.990
        assert ch["v"] == pytest.approx(x["b2_coin"]["virt_sol"], rel=1e-3)
        # what INIT-PRICE-NO-VIRT used as the opening price is ~20.7 % above the real pre-trade price
        assert (gr["pool_quote0"] + x["b2_coin"]["virt_sol"]) / gr["pool_base0"] / ch["pre"] > 1.15


def test_initial_price_and_invariant_are_the_real_pool_state(real):
    fx, cds = real
    for m, cd in cds.items():
        gr = fx[m]["graduate"]
        pre, tol, _ = _pre(fx[m])
        assert cd.init_X == pytest.approx(gr["pool_quote0"], rel=1e-12)
        assert cd.init_y == pytest.approx(gr["pool_base0"], rel=1e-12)
        assert cd.k_before(0) == pytest.approx(gr["pool_quote0"] * gr["pool_base0"], rel=1e-12)
        snap = C.AsOf(cd, cd.m0 + 60 + C.DECISION_LAG_S - 1, SOL)                  # bar 0 not complete yet
        assert snap.k == 0
        assert snap.price == pytest.approx(pre, rel=tol)


def test_bar0_open_is_the_price_before_the_first_real_trade(real):
    fx, cds = real
    for m, cd in cds.items():
        pre, tol, ts = _pre(fx[m])
        j = cd.bar_of(ts)
        assert 0 <= j < 3 and cd.arr["traded"][j]
        assert cd.arr["o"][j] == pytest.approx(pre, rel=tol), m
        assert all(cd.arr["c"][i] == pytest.approx(pre, rel=tol) for i in range(j))   # frozen at the initial price


def test_bar0_high_low_close_are_the_real_trade_extremes(real):
    """B2 high / low / close are the minute's post-trade extremes; the lab's bar range also spans the open (the price
    before the first trade), so high = max(real high, open) and low = min(real low, open)."""
    fx, cds = real
    n = n_wick = 0
    for m, cd in cds.items():
        mn = _minute(fx[m])
        if mn is None:
            continue
        pre, tol, ts = _pre(fx[m])
        j = cd.bar_of(ts)
        assert cd.arr["h"][j] == pytest.approx(max(mn["hi"], pre), rel=tol), m
        assert cd.arr["l"][j] == pytest.approx(min(mn["lo"], pre), rel=tol), m
        assert cd.arr["c"][j] == pytest.approx(mn["close"], rel=CH_TOL), m
        n += 1
        n_wick += cd.arr["l"][j] < min(cd.arr["o"][j], cd.arr["c"][j]) * (1 - 1e-9)
    assert n >= 60
    assert n_wick >= 1          # real lower wicks survive (the reverted code cut bar 0's low to the body)


def test_first_real_trade_follows_the_initial_invariant(real):
    """Fills price bar 0 with k = pool_quote0 * pool_base0: the first real trade's post-trade state lies on that
    curve (k only grows, by the LP fee left in the pool)."""
    fx, cds = real
    n = 0
    for m, cd in cds.items():
        sw = fx[m]["first_trade"].get("sw")
        if sw is None:
            continue
        y1 = cd.init_y + (-1.0 if sw["type"] == "buy" else 1.0) * sw["base_amount"]
        k_after = sw["price_sol"] * y1 * y1
        assert 1.0 - 1e-6 <= k_after / cd.k_before(0) < 1.003, m
        n += 1
    assert n >= 60


def test_ret_and_max_high_reaching_back_to_g_use_the_real_opening(real):
    fx, cds = real
    for m, cd in cds.items():
        pre, tol, _ = _pre(fx[m])
        snap = C.AsOf(cd, cd.m0 + 4 * 60 + C.DECISION_LAG_S, SOL)                  # bars 0-3 completed
        assert snap.k == 4
        assert snap.ret(3600) == pytest.approx(cd.arr["c"][3] / pre - 1.0, rel=tol, abs=tol)
        b2 = [r for r in fx[m]["b2_bars"] if r["minute_idx"] < 4]
        assert snap.max_high(3600) == pytest.approx(max([r["high"] for r in b2] + [pre]), rel=tol)

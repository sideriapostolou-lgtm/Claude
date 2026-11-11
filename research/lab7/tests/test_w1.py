"""Tests for research/lab7/W1/run.py (PLAN §10): the market builder, the entry windows and the fair alignment (no
lookahead), the side-to-Pinnacle mapping, the grid, and one hand-made W1 round trip through core.simulate. The last
test checks the real universe against lab 6's matched-game count (structure only; skipped without the data)."""

import importlib.util
import json
import math
import sys
from pathlib import Path

import core as C
import numpy as np
import pandas as pd
import pytest

LAB7 = Path(__file__).resolve().parents[1]


def _load_w1():
    if "lab7_w1_run" in sys.modules:
        return sys.modules["lab7_w1_run"]
    spec = importlib.util.spec_from_file_location("lab7_w1_run", LAB7 / "W1" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lab7_w1_run"] = mod
    spec.loader.exec_module(mod)
    return mod


W1 = _load_w1()
T0 = 1_785_000_000.0  # inside TRAIN
COMMENCE = T0 + 30 * 3600.0


def test_grid_is_the_plans():
    cells = W1.grid()
    sel = [c for c in cells if c.selectable]
    ref = [c for c in cells if not c.selectable]
    assert len(sel) == 54 and len(ref) == 3 and len({c.key for c in cells}) == 57
    assert all(c.exits.fair_exit and c.exits.hold_s is None and not c.exits.hold_to_settlement for c in sel)
    assert all(c.exits.hold_to_settlement for c in ref)
    assert {c.m for c in cells} == {0.02, 0.03, 0.05}
    assert {c.exits.tp for c in sel} == {0.02, 0.03, 0.05} and {c.exits.sl for c in sel} == {0.03, 0.05, None}
    assert "m0.03|tp0.05|slnone|tcutoff|maker" in {c.key for c in sel}
    assert {c.key for c in ref} == {"hold|m0.02", "hold|m0.03", "hold|m0.05"}


def test_windows_are_merged_and_clipped_to_the_last_24h_before_the_cutoff():
    cutoff = COMMENCE - 600  # Polymarket's start ten minutes before Pinnacle's commence
    snaps = np.array([COMMENCE - 30 * 3600, COMMENCE - 24.2 * 3600, COMMENCE - 6 * 3600, COMMENCE - 5.8 * 3600,
                      COMMENCE - 900, COMMENCE, COMMENCE + 60])
    w = W1.merge_windows(snaps, COMMENCE, cutoff)
    assert w == (
        (COMMENCE - 24 * 3600, COMMENCE - 24.2 * 3600 + 1800),  # clipped at commence - 24 h
        (COMMENCE - 6 * 3600, COMMENCE - 5.8 * 3600 + 1800),  # two overlapping snapshots, one interval
        (COMMENCE - 900, cutoff),  # clipped at the cutoff; snapshots at or after commence give nothing
    )
    assert all(b > a for a, b in w) and all(w[i][1] < w[i + 1][0] for i in range(len(w) - 1))


def test_fair_uses_only_the_last_snapshot_at_or_before_the_print():
    snaps = np.array([T0, T0 + 600, T0 + 5000])
    fs = np.array([[0.40, 0.45, 0.60], [0.60, 0.55, 0.40]])
    cutoff = T0 + 6000
    ts = np.array([T0 - 1, T0, T0 + 599, T0 + 600, T0 + 600 + 1800, T0 + 600 + 1801, T0 + 5999, T0 + 6000])
    f = W1.fair_matrix(ts, snaps, fs, commence=T0 + 7000, cutoff=cutoff)
    exp0 = [math.nan, 0.40, 0.40, 0.45, 0.45, math.nan, 0.60, math.nan]
    np.testing.assert_allclose(f[0], exp0, equal_nan=True)  # before the first snapshot, stale, at the cutoff: NaN
    np.testing.assert_allclose(f[1], [math.nan if math.isnan(v) else 1 - v for v in exp0], equal_nan=True)
    later = fs.copy()
    later[:, 2] = [0.99, 0.01]  # change a LATER snapshot: earlier prints must not move
    g = W1.fair_matrix(ts, snaps, later, commence=T0 + 7000, cutoff=cutoff)
    np.testing.assert_allclose(g[:, :6], f[:, :6], equal_nan=True)
    h = W1.fair_matrix(ts, snaps, fs, commence=T0 + 5000, cutoff=cutoff)  # a snapshot at commence is not usable
    assert math.isnan(h[0, 6])


def _line(home, away, draw=None):
    fair = {"home": np.array(home), "away": np.array(away),
            "draw": np.array(draw if draw is not None else [math.nan] * len(home))}
    return W1.L6.EventLine(snap_ts=np.arange(len(home), dtype=float), fair={"mult": fair, "power": fair},
                           overround=np.zeros(len(home)))


def test_sides_map_to_pinnacle_by_role():
    line = _line([0.6, 0.7], [0.4, 0.3])
    two = pd.DataFrame({"o": [1, 0], "result": ["team", "team"], "yes": [True, True]})
    np.testing.assert_allclose(W1.market_fair_snap(line, two, a_is_home=True), [[0.6, 0.7], [0.4, 0.3]])
    np.testing.assert_allclose(W1.market_fair_snap(line, two, a_is_home=False), [[0.4, 0.3], [0.6, 0.7]])
    soc = _line([0.5], [0.2], [0.3])
    draw = pd.DataFrame({"o": [0, 1], "result": ["draw", "draw"], "yes": [True, False]})
    np.testing.assert_allclose(W1.market_fair_snap(soc, draw, a_is_home=True), [[0.3], [0.7]])
    away = pd.DataFrame({"o": [0, 1], "result": ["away", "away"], "yes": [True, False]})
    np.testing.assert_allclose(W1.market_fair_snap(soc, away, a_is_home=False), [[0.5], [0.5]])  # A is away


def _spec(**kw):
    args = dict(id="m1", game_id="g1", league="mlb", kind="2way", split="train", question="A vs. B", rate_com=0.05,
                payout=(1.0, 0.0), closed_time=COMMENCE + 4 * 3600, commence=COMMENCE, cutoff=COMMENCE - 60,
                windows=W1.merge_windows(np.array([COMMENCE - 3600]), COMMENCE, COMMENCE - 60),
                snap_ts=np.array([COMMENCE - 3600]), fair_snap=np.array([[0.55], [0.45]]), close_fair=(0.55, 0.45))
    args.update(kw)
    return W1.Spec(**args)


def test_market_builder_follows_the_plan():
    s = _spec()
    t = C.Tape.from_prints([(COMMENCE - 3500, 0, "BUY", 0.50, 100), (COMMENCE + 100, 0, "SELL", 0.9, 100)])
    mk = W1.make_market(s, t)
    assert mk.end_mode == "last_before" and mk.end_t == s.cutoff and mk.entry_deadline == s.cutoff
    assert mk.hard_end == s.closed_time and mk.settle_t == s.closed_time and mk.payout == (1.0, 0.0)
    assert mk.band == (0.15, 0.85) and mk.event == "g1" and mk.split == "train"
    assert mk.entry_windows == ((COMMENCE - 3600, COMMENCE - 1800),)
    assert mk.fair[0, 0] == pytest.approx(0.55) and math.isnan(mk.fair[0, 1])  # after the cutoff: no fair


def test_a_w1_round_trip_takes_profit_at_the_fair_and_otherwise_sells_before_the_start():
    s = _spec()
    a = COMMENCE - 3500
    rows = [
        (a, 0, "BUY", 0.50, 100),  # signal: buyable 0 at .50, fair .55 (gap .05)
        (a + 12, 0, "BUY", 0.51, 100),  # entry fill (first buyable >= 10 s later) at .51
        (a + 100, 0, "BUY", 0.55, 100),  # reaches the fair (.55) before entry + tp (.56): fair-cap trigger
        (a + 115, 0, "SELL", 0.54, 100),  # the taker sell fills at the next sellable print >= trigger + 10 s
        (s.cutoff - 30, 0, "SELL", 0.53, 100),
        (s.cutoff + 30, 0, "SELL", 0.20, 100),
    ]
    mk = W1.make_market(s, C.Tape.from_prints(rows))
    sig = C.gap_signals(mk.tape, mk.fair, 0.05)
    assert sig[0] == 0 and sig[1] == -1  # .51 is only .04 below the fair
    trips, missed = C.walk(mk, sig, C.Exits(tp=0.05, sl=0.03, fair_exit=True))
    assert missed == 0 and len(trips) == 1
    t = trips[0]
    assert t["p_entry"] == pytest.approx(0.51) and t["reason"] == "fair" and t["p_exit"] == pytest.approx(0.54)
    rows2 = rows[:2] + rows[4:]  # no move: the time stop sells at the last sellable print before the cutoff
    mk2 = W1.make_market(s, C.Tape.from_prints(rows2))
    trips2, _ = C.walk(mk2, C.gap_signals(mk2.tape, mk2.fair, 0.05), C.Exits(tp=0.05, fair_exit=True))
    assert trips2[0]["reason"] == "time" and trips2[0]["t_exit"] == s.cutoff - 30 and not trips2[0]["late_stop"]
    trips3, _ = C.walk(mk2, C.gap_signals(mk2.tape, mk2.fair, 0.05), C.Exits(hold_to_settlement=True))
    assert trips3[0]["reason"] == "settle" and trips3[0]["p_exit"] == 1.0


def test_signals_outside_the_windows_are_never_taken():
    s = _spec()
    rows = [(COMMENCE - 1700, 0, "BUY", 0.40, 100), (COMMENCE - 1600, 0, "BUY", 0.40, 100)]  # after the window
    mk = W1.make_market(s, C.Tape.from_prints(rows))
    assert np.isnan(mk.fair).all()  # the only snapshot is more than 30 min old: no fair, no signal
    trips, missed = C.walk(mk, C.gap_signals(mk.tape, mk.fair, 0.02), C.Exits(tp=0.02, fair_exit=True))
    assert trips == [] and missed == 0


@pytest.mark.skipif(not (W1.LAB6_DATA / "matches.parquet").exists() or not (C.LAB4_DATA / "markets.parquet").exists(),
                    reason="lab 6 / lab 4 data not present")
def test_universe_is_lab6s_matched_games():
    g, sides, pin, _ = W1.load_matched()
    inv = json.loads((W1.LAB6_DATA / "inventory.json").read_text())
    assert len(g) == inv["matched_games"] == 5476
    assert g["split"].value_counts().to_dict() == {k: v for k, v in inv["matched_by_split"].items()}
    assert set(sides["game_id"]) <= set(g["game_id"])

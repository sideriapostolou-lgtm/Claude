"""Tests for research/lab7/W2/run.py (PLAN §10): the market builder, the entry windows and time stops, the fair
alignment (lab 5's q_event at the print's own second, never a later candle), the fixed grid, the universe filter, the
signal's invariants on a walked synthetic market, and the trip encoding. Synthetic spot and tapes only: no return."""

import importlib.util
import json
import sys
from pathlib import Path

import core as C
import numpy as np
import pandas as pd
import pytest

LAB7 = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lab7_w2_run", LAB7 / "W2" / "run.py")
W = importlib.util.module_from_spec(_spec)
sys.modules["lab7_w2_run"] = W
_spec.loader.exec_module(W)
L5C = W.L5C

T0 = 1_785_000_000  # 2026-07-25 17:20:00 UTC: a 5-minute boundary inside TRAIN
BASE = T0 - 3 * 3600
SPOT_END = T0 + 2 * 3600


def spot(seed=0, bump_from=None, bump=0.0):
    """A synthetic 1 s Binance series from BASE to SPOT_END; candles OPENING at or after ``bump_from`` are scaled by
    (1 + bump) (a different future)."""
    rng = np.random.default_rng(seed)
    n = SPOT_END - BASE
    close = 60_000.0 * np.exp(np.cumsum(rng.normal(0.0, 1e-4, n)))
    ts = np.arange(BASE, SPOT_END)
    if bump_from is not None:
        close = np.where(ts >= bump_from, close * (1.0 + bump), close)
    opn = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame({"ts": ts, "open": opn, "high": np.maximum(opn, close), "low": np.minimum(opn, close), "close": close})
    return L5C.Spot.from_frame("BTCUSDT", df, base=BASE)


def window_row(sub="5m", twap=0.0, winner=0, closed_after=60.0, ref_shift=0.0, sp=None, mid="w1"):
    dur = {"5m": 300, "15m": 900, "1h": 3600}[sub]
    t_final = T0 + dur
    if sub == "1h":
        c = {"symbol": "BTCUSDT", "question": "q", "source": "binance", "kind": "window", "sub": "1h", "t0": float(T0),
             "event_outcome": 0, "t_final": float(t_final), "ref_known": float(T0 + 1), "twap_s": 0.0,
             "ref_rule": "open_t0", "strict": False}
    else:
        sp = sp or spot()
        ref = float(sp.close_of(T0 - 1)) * (1.0 + ref_shift)
        c = {"symbol": "BTCUSDT", "question": "q", "source": "chainlink", "kind": "window", "sub": sub, "t0": float(T0),
             "event_outcome": 0, "t_final": float(t_final), "ref_known": float(T0), "twap_s": float(twap),
             "ref_rule": "chainlink", "ref_value": ref, "strict": False}
    return {"id": mid, "contract": json.dumps(c), "winner": winner, "closed_time": t_final + closed_after,
            "end_date": float(t_final), "rate": 0.07, "split": "train", "symbol": "BTCUSDT", "sub": sub, "kind": "window"}


def synthetic_tape(t_from, t_to, step=2, p=0.50):
    rows = []
    for k, t in enumerate(range(int(t_from), int(t_to), step)):
        side = ("BUY", "SELL")[k % 2]
        rows.append((float(t), k % 2, side, p, 100.0))
    return C.Tape.from_prints(rows)


# --- the market builder ---------------------------------------------------------------------------------------------


def test_market_builder_5m_window():
    sp = spot()
    r = window_row("5m", sp=sp)
    mk = W.build_market(r, sp, 7.5e-5, tape=synthetic_tape(T0 - 100, T0 + 330))
    t_final = T0 + 300
    assert mk.entry_windows == ((float(T0), t_final - 60.0),)
    assert mk.entry_deadline == mk.end_t == t_final - 60.0
    assert mk.end_mode == "next"
    assert mk.hard_end == t_final and mk.settle_t == t_final + 60.0
    assert mk.payout == (1.0, 0.0)
    assert mk.band == (0.10, 0.90) and mk.rate_com == 0.07
    assert mk.event == "W:2026-07-25T17" and mk.split == "train"
    assert mk.info["sub"] == "5m"


def test_market_builder_15m_and_1h_time_stops():
    sp = spot()
    mk15 = W.build_market(window_row("15m", sp=sp), sp, 7.5e-5, tape=synthetic_tape(T0, T0 + 900))
    assert mk15.end_t == T0 + 900 - 60.0
    mk1h = W.build_market(window_row("1h", winner=1), sp, 7.5e-5, tape=synthetic_tape(T0, T0 + 3600, step=10))
    assert mk1h.entry_windows == ((float(T0 + 1), T0 + 3600 - 300.0),)
    assert mk1h.end_t == mk1h.entry_deadline == T0 + 3600 - 300.0
    assert mk1h.payout == (0.0, 1.0)


def test_hard_end_is_the_close_when_the_market_closed_before_the_window_end():
    sp = spot()
    mk = W.build_market(window_row("5m", closed_after=-30.0, sp=sp), sp, 7.5e-5, tape=synthetic_tape(T0, T0 + 300))
    assert mk.hard_end == T0 + 270.0 and mk.settle_t == T0 + 270.0


def test_a_tape_with_fewer_than_50_fills_is_skipped():
    sp = spot()
    short = synthetic_tape(T0, T0 + 98)  # 49 prints
    assert len(short) == 49
    assert W.build_market(window_row("5m", sp=sp), sp, 7.5e-5, tape=short) is None


# --- the fair ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sub,twap", [("5m", 0.0), ("5m", 60.0), ("15m", 30.0), ("1h", 0.0)])
def test_fair_is_lab5_q_event_at_the_print_second(sub, twap):
    sp = spot()
    r = window_row(sub, twap=twap, sp=sp)
    dur = {"5m": 300, "15m": 900, "1h": 3600}[sub]
    tape = synthetic_tape(T0 - 60, T0 + dur + 20)
    mk = W.build_market(r, sp, 7.5e-5, tape=tape)
    m5 = W.L5R.to_market(r)
    q = L5C.q_event(m5, sp, tape.ts.astype(np.int64), 3600, 7.5e-5)
    np.testing.assert_array_equal(mk.fair[0], q)
    ok = np.isfinite(mk.fair[0])
    np.testing.assert_allclose(mk.fair[1][ok], 1.0 - mk.fair[0][ok])
    ref_known = json.loads(r["contract"])["ref_known"]
    assert np.isnan(mk.fair[0][tape.ts < ref_known]).all()
    assert np.isnan(mk.fair[0][tape.ts >= T0 + dur]).all()
    assert np.isfinite(mk.fair[0][(tape.ts >= ref_known) & (tape.ts < T0 + dur)]).all()


@pytest.mark.parametrize("sub,twap", [("5m", 0.0), ("5m", 60.0), ("15m", 30.0), ("1h", 0.0)])
def test_fair_never_reads_a_candle_that_closed_after_the_print(sub, twap):
    dur = {"5m": 300, "15m": 900, "1h": 3600}[sub]
    cut = T0 + dur - 45  # inside the TWAP averaging window for the TWAP cases
    base_sp = spot()
    r = window_row(sub, twap=twap, sp=base_sp)
    tape = synthetic_tape(T0, T0 + dur, step=1)
    f_a = W.build_market(r, base_sp, 7.5e-5, tape=tape).fair
    other = spot(bump_from=cut, bump=0.01)  # the same past, a different future from candle `cut` on
    f_b = W.build_market(r, other, 7.5e-5, tape=tape).fair
    known = tape.ts <= cut  # the candle opening at `cut` closes at cut + 1: unknown at a print stamped `cut`
    np.testing.assert_array_equal(f_a[:, known], f_b[:, known])
    later = (tape.ts > cut) & np.isfinite(f_a[0])
    assert later.any() and not np.allclose(f_a[0][later], f_b[0][later])  # the test has power


# --- the grid and the universe ------------------------------------------------------------------------------------------


def test_the_grid_is_plan_section_5_w2():
    cells = W.all_cells()
    sel = [c for c in cells if c.selectable]
    ref = [c for c in cells if not c.selectable]
    assert len(sel) == 54 and len(ref) == 3 and len({c.key for c in cells}) == 57
    for c in sel:
        e = c.exits
        assert e.fair_exit and e.hold_s is None and not e.hold_to_settlement
        assert e.tp in (0.03, 0.05, 0.08) and e.sl in (0.05, 0.10, None) and e.tp_mode in ("taker", "maker")
        assert c.m in (0.03, 0.05, 0.08)
        assert c.key == W.cell_key(c.m, e.tp, e.sl, e.tp_mode)
    assert {c.key for c in ref} == {"hold|m0.03", "hold|m0.05", "hold|m0.08"}
    assert all(c.exits.hold_to_settlement for c in ref)
    assert W.cell_key(0.05, 0.08, None, "maker") == "m0.05|tp0.08|slnone|tend|maker"


def test_universe_keeps_only_5m_15m_1h_windows_of_the_split():
    rows = []
    for i, (kind, sub, split, sym) in enumerate(
        [("window", "5m", "train", "BTCUSDT"), ("window", "15m", "train", "ETHUSDT"), ("window", "1h", "train", "SOLUSDT"),
         ("window", "4h", "train", "BTCUSDT"), ("window", "1d", "train", "BTCUSDT"), ("terminal", "above", "train", "BTCUSDT"),
         ("window", "5m", "val", "BTCUSDT"), ("window", "5m", "train", "DOGEUSDT")]
    ):
        rows.append({"id": str(i), "kind": kind, "sub": sub, "split": split, "symbol": sym, "n_outcomes": 2, "winner": 0})
    rows.append({"id": "9", "kind": "window", "sub": "5m", "split": "train", "symbol": "BTCUSDT", "n_outcomes": 2, "winner": -1})
    u = W.universe(pd.DataFrame(rows), "train")
    assert sorted(u["id"]) == ["0", "1", "2"]


# --- signals and walking --------------------------------------------------------------------------------------------------


def test_walked_trips_respect_windows_band_gap_and_latency():
    sp = spot(seed=3)
    r = window_row("5m", ref_shift=-0.002, sp=sp)  # Up is likely: fair well above the 0.50 prints
    tape = synthetic_tape(T0 - 60, T0 + 300, step=1, p=0.50)
    mk = W.build_market(r, sp, 7.5e-5, tape=tape)
    f, missed = W.market_trips(mk, list(W.CELLS.values()))
    assert len(f) > 0
    for key, g in f.groupby("cell"):
        m = W.CELLS[key].m
        assert (g["fair_sig"] - g["p_signal"] >= m - 1e-9).all()
        assert ((g["t_signal"] >= T0) & (g["t_signal"] < T0 + 240)).all()
        assert ((g["p_signal"] >= 0.10 - 1e-9) & (g["p_signal"] <= 0.90 + 1e-9)).all()
        assert (g["t_entry"] >= g["t_signal"] + 10).all() and (g["t_entry"] < T0 + 240).all()
        assert (g["t_exit"] >= g["t_entry"]).all()
        taker_exits = g[g["exit_leg"] == "taker"]
        assert (taker_exits["t_exit"] < T0 + 300).all()  # hard_end = the window end
        # the fair columns are the fair known at the signal print's and the fill print's seconds
        i_s = np.searchsorted(tape.ts, g["t_signal"].to_numpy(), side="left")
        np.testing.assert_array_equal(g["fair_sig"].to_numpy(), mk.fair[g["o"].to_numpy(dtype=int), i_s])


def test_encode_decode_round_trip():
    sp = spot(seed=3)
    r = window_row("5m", ref_shift=-0.002, sp=sp)
    mk = W.build_market(r, sp, 7.5e-5, tape=synthetic_tape(T0 - 60, T0 + 300, step=1))
    f, _ = W.market_trips(mk, list(W.CELLS.values()))
    arr = W.encode(f)
    arr["mi"] = np.zeros(len(f), dtype=np.int32)
    meta = pd.DataFrame({"id": [mk.id], "event": [mk.event], "sub": ["5m"], "symbol": ["BTCUSDT"]})
    g = W.decode(arr, np.ones(len(f), dtype=bool), meta, "train")
    pd.testing.assert_frame_equal(g.reset_index(drop=True), f[C.TRIP_COLUMNS + W.EXTRA_COLUMNS].reset_index(drop=True),
                                  check_dtype=False)

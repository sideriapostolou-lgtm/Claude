"""Tests for research/lab7/W4/run.py (PLAN §10): the grid, the market end (min(endDate, closedTime)), the market
builder (window ``[first print + y, market end)``, entry deadline and time stop at the end, held to settlement after
it), the side labels, a hand-made momentum and fade round trip through core, the trip encoding (decode(encode) =
core's trip frame), signals and exits that never read past the decision, the placebo staying inside the window, the
universe on the real data (structure only; skipped without the data), and the whole TRAIN pipeline on a synthetic
universe."""

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


def _load_w4():
    if "lab7_w4_run" in sys.modules:
        return sys.modules["lab7_w4_run"]
    spec = importlib.util.spec_from_file_location("lab7_w4_run", LAB7 / "W4" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lab7_w4_run"] = mod
    spec.loader.exec_module(mod)
    return mod


W4 = _load_w4()
T0 = 1_785_000_000.0  # inside TRAIN
END = T0 + 10 * 86400.0
CLOSED = END + 3600.0


def row(**kw):
    r = {"id": "m1", "event_slug": "highest-temperature-in-nyc-on-july-25", "question": "Will it be 90F?",
         "family": "weather", "end": END, "end_date": END, "close_kind": W4.SCHEDULED, "closed_time": CLOSED,
         "winner_index": 0, "rate": 0.05, "side0": "yes", "side1": "no", "neg_risk": True, "split": "train"}
    r.update(kw)
    return r


def tape(*rows):
    return C.Tape.from_prints(rows)


def test_grid_is_the_plans():
    cells = W4.grid()
    sel = [c for c in cells if c.selectable]
    ref = [c for c in cells if not c.selectable]
    assert len(sel) == 192 and len(ref) == 8 and len({c.key for c in cells}) == 200
    assert {c.entry.direction for c in cells} == {"mom", "fade"}
    assert {c.entry.x for c in cells} == {0.05, 0.10} and {c.entry.y_min for c in cells} == {60, 240}
    assert {c.exits.tp for c in sel} == {0.03, 0.05, 0.10} and {c.exits.sl for c in sel} == {0.05, 0.10}
    assert {c.exits.hold_s for c in sel} == {86400.0, None} and {c.exits.tp_mode for c in sel} == {"taker", "maker"}
    assert not any(c.exits.fair_exit for c in cells)
    assert all(c.exits.hold_to_settlement for c in ref)
    keys = {c.key for c in cells}
    assert "mom|x0.05|y60m|tp0.03|sl0.05|t24h|taker" in keys
    assert "fade|x0.1|y240m|tp0.1|sl0.1|tend|maker" in keys
    assert "hold|fade|x0.1|y240m" in keys
    assert W4.BAND == (0.15, 0.85) and W4.K_PRINTS == 10 and W4.MIN_FILLS == 50
    assert W4.FAMILIES == ("politics", "culture", "economics", "weather", "mentions", "tech", "finance")


def test_market_end_is_the_earlier_of_end_date_and_closed_time():
    assert W4.market_end(100.0, 200.0) == 100.0
    assert W4.market_end(300.0, 200.0) == 200.0
    assert W4.market_end(float("nan"), 200.0) == 200.0
    assert W4.market_end(None, 200.0) == 200.0
    assert W4.market_end(0.0, 200.0) == 200.0


def test_market_builder_window_starts_y_after_the_first_print():
    t = tape((T0, 0, "BUY", 0.5, 10), (T0 + 10, 0, "BUY", 0.5, 10))
    mk = W4.make_market(row(), t, 3600.0)
    assert mk.entry_windows == ((T0 + 3600.0, END),)
    assert mk.entry_deadline == END and mk.end_t == END and mk.end_mode == "settle"
    assert mk.hard_end == CLOSED and mk.settle_t == CLOSED and mk.payout == (1.0, 0.0) and mk.band == (0.15, 0.85)
    assert mk.fair is None and mk.event == "highest-temperature-in-nyc-on-july-25" and mk.rate_com == 0.05
    assert W4.make_market(row(winner_index=1), t, 3600.0).payout == (0.0, 1.0)
    assert W4.make_market(row(end=T0 + 3000), t, 3600.0).entry_windows == ()  # ends before first print + y


def _rise_rows(top=0.46):
    """Thirteen flat prints at .40 every 5 min (T0 .. T0 + 3600), then one at ``top`` at T0 + 3700: the reference
    is the print at T0 (the last at or before T0 + 100), with 13 prints after it."""
    return [(T0 + 300 * j, 0, "BUY", 0.40, 10) for j in range(13)] + [(T0 + 3700, 0, "BUY", top, 10)]


def test_momentum_round_trip_takes_profit_at_the_next_bid():
    rows = _rise_rows() + [
        (T0 + 3705, 0, "SELL", 0.45, 100),  # a bid print 5 s after the signal: never a buy for outcome 0
        (T0 + 3712, 0, "BUY", 0.47, 100),  # entry: first buyable for 0 at >= signal + 10 s
        (T0 + 3800, 0, "BUY", 0.50, 100),  # 0.47 + 0.03 reached: the taker take profit triggers
        (T0 + 3805, 0, "SELL", 0.49, 100),  # 5 s later: too early for the sell
        (T0 + 3811, 0, "SELL", 0.495, 100),  # the exit
    ]
    t = tape(*rows)
    cell = W4.CELLS["mom|x0.05|y60m|tp0.03|sl0.05|t24h|taker"]
    trips, missed = W4.market_trips(row(), t, [cell])
    tr = trips[cell.key]
    assert missed == {} and len(tr) == 1
    rt = tr[0]
    assert rt["o"] == 0 and rt["t_signal"] == T0 + 3700 and rt["t_entry"] == T0 + 3712
    assert rt["p_entry"] == pytest.approx(0.47) and rt["reason"] == "tp" and rt["t_exit"] == T0 + 3811
    sh = 20 / 0.47
    fee = sh * C.US_RATE * (0.47 * 0.53 + 0.495 * 0.505)
    assert rt["pnl_us"] == pytest.approx(sh * 0.495 - 20 - fee)
    fade = W4.CELLS["fade|x0.05|y60m|tp0.03|sl0.05|t24h|taker"]
    rt = W4.market_trips(row(), t, [fade])[0][fade.key][0]
    assert rt["o"] == 1 and rt["t_entry"] == T0 + 3805 and rt["p_entry"] == pytest.approx(0.51)  # 1 - the bid


def test_ten_prints_are_needed_since_the_reference():
    few = [(T0, 0, "BUY", 0.40, 10)] + [(T0 + 3000 + 50 * j, 0, "BUY", 0.40, 10) for j in range(8)]
    few += [(T0 + 3700, 0, "BUY", 0.46, 10), (T0 + 3712, 0, "BUY", 0.46, 10),  # 9 then 10 prints after T0
            (T0 + 3730, 0, "BUY", 0.46, 10)]  # the entry of the signal at T0 + 3712
    cell = W4.CELLS["mom|x0.05|y60m|tp0.03|sl0.05|tend|taker"]
    trips, _ = W4.market_trips(row(), tape(*few), [cell])
    assert [x["t_signal"] for x in trips[cell.key]] == [T0 + 3712]  # T0 + 3700 has only 9 prints since T0


def test_no_signal_before_first_print_plus_y_and_no_entry_at_or_after_the_end():
    early = [(T0 + 60 * j, 0, "BUY", 0.40 + 0.01 * j, 10) for j in range(12)]  # a rise inside the first hour
    cell = W4.CELLS["mom|x0.05|y60m|tp0.03|sl0.05|tend|taker"]
    trips, _ = W4.market_trips(row(), tape(*early), [cell])
    assert cell.key not in trips
    end = T0 + 3800.0
    rows = _rise_rows() + [(end + 5, 0, "BUY", 0.47, 10)]  # the only buyable print after the signal is past the end
    trips, missed = W4.market_trips(row(end=end), tape(*rows), [cell])
    assert cell.key not in trips and missed.get(cell.key) == 1


def test_a_24h_stop_after_the_end_holds_to_settlement():
    end = T0 + 3700 + 7200.0
    rows = _rise_rows() + [(T0 + 3712, 0, "BUY", 0.47, 100), (T0 + 9000, 0, "SELL", 0.46, 100),
                           (end + 600, 0, "SELL", 0.99, 100)]
    cell = W4.CELLS["mom|x0.05|y60m|tp0.1|sl0.1|t24h|taker"]
    trips, _ = W4.market_trips(row(end=end, winner_index=0), tape(*rows), [cell])
    rt = trips[cell.key][0]
    assert rt["reason"] == "settle" and rt["p_exit"] == 1.0 and rt["t_exit"] == CLOSED  # 24 h would pass the end
    ref = W4.CELLS["hold|mom|x0.05|y60m"]
    rt = W4.market_trips(row(end=end, winner_index=1), tape(*rows), [ref])[0][ref.key][0]
    assert rt["reason"] == "settle" and rt["p_exit"] == 0.0


def test_a_24h_stop_inside_the_market_sells_at_the_next_bid():
    rows = _rise_rows() + [(T0 + 3712, 0, "BUY", 0.47, 100), (T0 + 3712 + 86400 + 5, 0, "SELL", 0.44, 100),
                           (T0 + 3712 + 86400 + 11, 0, "SELL", 0.45, 100)]
    cell = W4.CELLS["mom|x0.05|y60m|tp0.1|sl0.1|t24h|taker"]
    rt = W4.market_trips(row(), tape(*rows), [cell])[0][cell.key][0]
    assert rt["reason"] == "time" and rt["t_exit"] == T0 + 3712 + 86400 + 11 and rt["p_exit"] == pytest.approx(0.45)


def test_side_labels():
    assert W4.side_labels('["Yes", "No"]') == ("yes", "no")
    assert W4.side_labels('["No", "Yes"]') == ("no", "yes")
    assert W4.side_labels('["Up", "Down"]') == ("up", "down")
    assert W4.side_labels('["Anthropic", "OpenAI"]') == ("name1", "name2")
    assert W4.side_labels(None) == ("name1", "name2")


def _random_tape(seed, n=1500):
    """About a day of prints (10-120 s apart), a random walk around 0.5."""
    rng = np.random.default_rng(seed)
    ts = T0 + np.cumsum(rng.integers(10, 120, n)).astype(float)
    p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.012, n)), 0.05, 0.95)
    oi = rng.integers(0, 2, n)
    side = np.where(rng.random(n) < 0.5, "BUY", "SELL")
    price = np.where(oi == 0, p, 1 - p)
    return tape(*zip(ts, oi, side, np.round(price, 3), rng.uniform(5, 200, n), strict=True))


def test_encode_decode_rebuilds_cores_trip_frame():
    t = _random_tape(4)
    r = row(end=float(t.ts[-1]) - 100, closed_time=float(t.ts[-1]) + 10)
    u = pd.DataFrame([r])
    cells = [c for c in W4.grid() if c.entry.key == "mom|x0.05|y60m"][:6] + [W4.CELLS["hold|mom|x0.05|y60m"]]
    trips, _ = W4.market_trips(r, t, cells)
    assert trips, "the random tape should trade"
    for key, tr in trips.items():
        arr = W4.encode(tr, W4.CELL_CODE[key])
        arr["mi"] = np.zeros(len(tr), dtype=np.int32)
        got = W4.decode(arr, np.ones(len(tr), dtype=bool), u)
        want = C.trips_frame(tr).sort_values(["t_entry", "id"], kind="stable").reset_index(drop=True)
        pd.testing.assert_frame_equal(got[C.TRIP_COLUMNS], want, check_dtype=False, rtol=1e-12, atol=1e-12)
        assert set(got["side"]) <= {"yes", "no"} and (got["family"] == "weather").all()
        assert ((got["to_end_h"] - (r["end"] - got["t_entry"]) / 3600.0).abs() < 1e-9).all()


def test_trips_never_read_past_their_exit_and_signals_never_read_the_future():
    t = _random_tape(5)
    r = row(end=float(t.ts[-1]) - 100, closed_time=float(t.ts[-1]) + 10)
    cell = W4.CELLS["fade|x0.05|y60m|tp0.05|sl0.05|t24h|taker"]
    trips, _ = W4.market_trips(r, t, [cell])
    tr = [x for x in trips[cell.key] if x["exit_leg"] != "settle"]
    assert len(tr) >= 3
    for x in tr[:5]:
        cut = t.until(x["t_exit"])
        mk = W4.make_market(r, cut, cell.entry.y_s)
        again = C.simulate(mk, x["o"], x["t_signal"], cell.exits)
        assert again["t_exit"] == x["t_exit"] and again["p_exit"] == x["p_exit"] and again["reason"] == x["reason"]
    full = C.swing_signals(t, 0.05, 3600, 10, "fade")
    for k in range(50, len(t), 97):
        assert (C.swing_signals(C.Tape(t.ts[:k], t.p0[:k], t.buy0[:k], t.size[:k]), 0.05, 3600, 10, "fade")
                == full[:k]).all()


def test_placebo_counterparts_stay_in_the_window():
    t = _random_tape(6)
    r = row(end=float(t.ts[-1]) - 100, closed_time=float(t.ts[-1]) + 10)
    cell = W4.CELLS["mom|x0.05|y240m|tp0.05|sl0.05|t24h|maker"]
    mk = W4.make_market(r, t, cell.entry.y_s)
    m = C.placebo_matrix(mk, 3, cell.exits, draws=20, rng=np.random.default_rng(1))
    assert m.shape == (20, 3) and np.isfinite(m).mean() > 0.9
    times = C._draw_times(mk.entry_windows, np.random.default_rng(2), 500)
    assert (times >= float(t.ts[0]) + 240 * 60).all() and (times < r["end"]).all()


DATA = C.LAB4_DATA / "markets.parquet"


@pytest.mark.skipif(not DATA.exists(), reason="lab 4 markets not cached")
def test_universe_on_the_real_data_is_the_plans():
    """Structure only (no tape, no return): PLAN §3's 3,122 TRAIN and 1,457 VAL markets in the seven families."""
    for split, n in (("train", 3122), ("val", 1457)):
        u = W4.universe(split)
        assert len(u) == n and u["id"].is_unique
        assert set(u["family"]) <= set(W4.FAMILIES)
        assert (u["end"] <= u["closed_time"]).all() and (u["end"] > 0).all()
        lo, hi = C.split_bounds(split)
        assert ((u["closed_time"] >= lo) & (u["closed_time"] < hi)).all()
        assert set(u["winner_index"]) <= {0, 1} and set(u["rate"]) <= {0.04, 0.05}
        early = u["close_kind"] == W4.EARLY
        assert (u.loc[early, "closed_time"] < u.loc[early, "end_date"] - 3600).all()
    with pytest.raises(PermissionError):
        W4.universe("test")


def test_run_stage_end_to_end_on_a_synthetic_universe(monkeypatch, tmp_path):
    """The whole TRAIN pipeline on three random markets: every cell is reported and recorded once, files are
    written, and the placebo readings are attached."""
    tapes = {"a": _random_tape(11), "b": _random_tape(12), "c": _random_tape(13)}
    rows = [row(id=k, event_slug=f"ev-{k}", end=float(t.ts[-1]) - 100, closed_time=float(t.ts[-1]) + 10,
                close_kind=W4.EARLY if k == "c" else W4.SCHEDULED, winner_index=int(k == "b"),
                family="politics" if k == "a" else "weather")
            for k, t in tapes.items()]
    u = pd.DataFrame(rows)
    monkeypatch.setattr(W4, "universe", lambda split: u.copy())
    monkeypatch.setattr(C, "load_tape", lambda mid, trades_dir=None, min_fills=0: tapes.get(str(mid)))
    monkeypatch.setattr(W4, "HERE", tmp_path)
    monkeypatch.setattr(W4, "OUT_DIR", tmp_path / "out")
    (tmp_path / "PREREG.md").write_text("test prereg\n")
    monkeypatch.setattr(W4, "PREREG", tmp_path / "PREREG.md")
    ledger: list = []
    monkeypatch.setattr(C, "record_runs", lambda entries, ledger_path=None: ledger.extend(entries) or len(ledger))
    doc = W4.run_stage("train", B=50, workers=1)
    assert doc["verdict"] in ("NO_EDGE_TRAIN", "TRAIN_SELECTED")
    assert len(doc["cells"]) == 200 and [c["cell"] for c in doc["cells"]] == list(W4.CELLS)
    assert len(ledger) == 200 and {e["kind"] for e in ledger} == {"selectable", "reference"}
    assert all(e["prereg_sha256"] == C.prereg_sha256(tmp_path / "PREREG.md") for e in ledger)
    traded = [c for c in doc["cells"] if c["summary"]["n"]]
    assert traded and all(c["extra"]["by_family"] for c in traded)
    assert all(set(c["extra"]["by_family"]) <= {"politics", "weather"} for c in traded)
    assert all(c["summary"]["n_events"] <= 3 for c in doc["cells"])
    md = (tmp_path / "train.md").read_text()
    assert md.count("\n| `") >= 200 and "Decision:" in md.splitlines()[2]
    assert json.loads((tmp_path / "train.json").read_text())["n_trials_total"] == 200
    assert doc["placebo_readings"] and all(doc["cells"][W4.CELL_CODE[k]]["placebo"] for k in doc["placebo_readings"])
    assert math.isfinite(doc["coverage"]["walk_s"])

"""Tests for research/lab7/W3/run.py (PLAN §10): the grid, the market builder (in-play window ``[start + y, end)``,
entry deadline and time stop at the end, held to settlement after it), the side labels, a hand-made momentum and
fade round trip through core, the trip encoding (decode(encode) = core's trip frame), signals and entries that never
read past the decision, the placebo staying in play, and the universe mirror against lab 4 P6 on the real data
(structure only; skipped without the data)."""

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import core as C
import numpy as np
import pandas as pd
import pytest

LAB7 = Path(__file__).resolve().parents[1]


def _load_w3():
    if "lab7_w3_run" in sys.modules:
        return sys.modules["lab7_w3_run"]
    spec = importlib.util.spec_from_file_location("lab7_w3_run", LAB7 / "W3" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lab7_w3_run"] = mod
    spec.loader.exec_module(mod)
    return mod


W3 = _load_w3()
T0 = 1_785_000_000.0  # inside TRAIN
START = T0
END = T0 + 3 * 3600.0
CLOSED = END + 1800.0


def row(**kw):
    r = {"id": "m1", "event_slug": "atp-a-b-2026-07-25", "question": "A vs B", "sport": "tennis", "league": "atp",
         "start": START, "end": END, "end_kind": W3.WHISTLE, "closed_time": CLOSED, "winner_index": 0, "rate": 0.05,
         "family": "sports", "side0": "team1", "side1": "team2", "split": "train"}
    r.update(kw)
    return r


def tape(*rows):
    return C.Tape.from_prints(rows)


def test_grid_is_the_plans():
    cells = W3.grid()
    sel = [c for c in cells if c.selectable]
    ref = [c for c in cells if not c.selectable]
    assert len(sel) == 288 and len(ref) == 8 and len({c.key for c in cells}) == 296
    assert {c.entry.direction for c in cells} == {"mom", "fade"}
    assert {c.entry.x for c in cells} == {0.05, 0.10} and {c.entry.y_min for c in cells} == {2, 5}
    assert {c.exits.tp for c in sel} == {0.03, 0.05, 0.10} and {c.exits.sl for c in sel} == {0.05, 0.10}
    assert {c.exits.hold_s for c in sel} == {900.0, 2700.0, None} and {c.exits.tp_mode for c in sel} == {"taker", "maker"}
    assert not any(c.exits.fair_exit for c in cells)
    assert all(c.exits.hold_to_settlement for c in ref)
    keys = {c.key for c in cells}
    assert "mom|x0.05|y2m|tp0.03|sl0.05|t15m|taker" in keys
    assert "fade|x0.1|y5m|tp0.1|sl0.1|tend|maker" in keys
    assert "hold|fade|x0.1|y5m" in keys
    assert W3.BAND == (0.20, 0.80) and W3.K_PRINTS == 5


def test_market_builder_is_in_play_only():
    t = tape((START - 600, 0, "BUY", 0.5, 10), (START + 10, 0, "BUY", 0.5, 10))
    mk = W3.make_market(row(), t, 120.0)
    assert mk.entry_windows == ((START + 120.0, END),)
    assert mk.entry_deadline == END and mk.end_t == END and mk.end_mode == "settle"
    assert mk.hard_end == CLOSED and mk.settle_t == CLOSED and mk.payout == (1.0, 0.0) and mk.band == (0.20, 0.80)
    assert mk.fair is None and mk.event == "atp-a-b-2026-07-25" and mk.rate_com == 0.05
    assert W3.make_market(row(winner_index=1), t, 120.0).payout == (0.0, 1.0)
    short = W3.make_market(row(end=START + 100), t, 120.0)
    assert short.entry_windows == ()  # a game shorter than the lookback has no window


def _momentum_rows(top=0.47):
    """Outcome 0 rises .40 -> top over 120 s (the reference at START + 200, 6 prints after it): the signal print is
    the one at START + 320."""
    return [(START + 200 + 20 * i, 0, "BUY", 0.40 + (top - 0.40) * i / 6, 10) for i in range(7)]


def test_momentum_round_trip_takes_profit_at_the_next_bid():
    rows = _momentum_rows() + [
        (START + 325, 0, "SELL", 0.46, 100),  # a bid print 5 s after the signal: never an entry, never a trigger
        (START + 332, 0, "BUY", 0.48, 100),  # entry: first buyable for 0 at >= signal + 10 s
        (START + 420, 0, "BUY", 0.51, 100),  # 0.48 + 0.03 reached: the taker take profit triggers
        (START + 425, 0, "SELL", 0.50, 100),  # 5 s later: too early for the sell
        (START + 431, 0, "SELL", 0.505, 100),  # the exit
    ]
    t = tape(*rows)
    cell = W3.CELLS["mom|x0.05|y2m|tp0.03|sl0.05|t15m|taker"]
    trips, missed = W3.market_trips(row(), t, [cell])
    tr = trips[cell.key]
    assert missed == {} and len(tr) == 1
    rt = tr[0]
    assert rt["o"] == 0 and rt["t_signal"] == START + 320 and rt["t_entry"] == START + 332
    assert rt["p_entry"] == pytest.approx(0.48) and rt["reason"] == "tp" and rt["t_exit"] == START + 431
    sh = 20 / 0.48
    fee = sh * C.US_RATE * (0.48 * 0.52 + 0.505 * 0.495)
    assert rt["pnl_us"] == pytest.approx(sh * 0.505 - 20 - fee)
    fade = W3.CELLS["fade|x0.05|y2m|tp0.03|sl0.05|t15m|taker"]
    trips, _ = W3.market_trips(row(), t, [fade])
    assert trips[fade.key][0]["o"] == 1  # fade buys the faller: outcome 1, at 1 - the print price


def test_no_signal_before_start_plus_y_and_no_entry_at_or_after_the_end():
    early = [(START - 100 + 20 * i, 0, "BUY", 0.40 + 0.02 * i, 10) for i in range(7)]  # a pre-game move
    cell = W3.CELLS["mom|x0.05|y2m|tp0.03|sl0.05|tend|taker"]
    trips, _ = W3.market_trips(row(), tape(*early, (START + 200, 0, "BUY", 0.52, 10)), [cell])
    assert cell.key not in trips  # the signal prints are before start + y
    late = [(END - 150 + 20 * i, 0, "BUY", 0.40 + 0.02 * i, 10) for i in range(7)]  # signal at END - 30
    after = (END + 5, 0, "BUY", 0.55, 10)  # only buyable print after the signal is past the end
    trips, missed = W3.market_trips(row(), tape(*late, after), [cell])
    assert cell.key not in trips and missed.get(cell.key) == 1


def test_a_hold_stop_after_the_end_holds_to_settlement():
    rows = [(END - 420 + 20 * i, 0, "BUY", 0.40 + 0.07 * i / 6, 10) for i in range(7)]  # .40 -> .47, signal END - 300
    rows += [(END - 280, 0, "BUY", 0.47, 100), (END - 100, 0, "SELL", 0.46, 100), (END + 600, 0, "SELL", 0.99, 100)]
    cell = W3.CELLS["mom|x0.05|y2m|tp0.1|sl0.1|t45m|taker"]
    trips, _ = W3.market_trips(row(winner_index=0), tape(*rows), [cell])
    rt = trips[cell.key][0]
    assert rt["reason"] == "settle" and rt["p_exit"] == 1.0 and rt["t_exit"] == CLOSED  # 45 min would pass the end
    ref = W3.CELLS["hold|mom|x0.05|y2m"]
    rt = W3.market_trips(row(winner_index=1), tape(*rows), [ref])[0][ref.key][0]
    assert rt["reason"] == "settle" and rt["p_exit"] == 0.0


def test_side_labels():
    assert W3.side_labels('["Yes", "No"]') == ("yes", "no")
    assert W3.side_labels('["No", "Yes"]') == ("no", "yes")
    assert W3.side_labels('["Mets", "Braves"]') == ("team1", "team2")
    assert W3.side_labels(None) == ("team1", "team2")


def _random_tape(seed, n=1500):
    rng = np.random.default_rng(seed)
    ts = START + np.cumsum(rng.integers(1, 15, n)).astype(float)
    p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.012, n)), 0.05, 0.95)
    oi = rng.integers(0, 2, n)
    side = np.where(rng.random(n) < 0.5, "BUY", "SELL")
    price = np.where(oi == 0, p, 1 - p)
    return tape(*zip(ts, oi, side, np.round(price, 3), rng.uniform(5, 200, n), strict=True))


def test_encode_decode_rebuilds_cores_trip_frame():
    t = _random_tape(4)
    r = row(end=float(t.ts[-1]) - 100)
    u = pd.DataFrame([r])
    cells = [c for c in W3.grid() if c.entry.key == "mom|x0.05|y2m"][:6] + [W3.CELLS["hold|mom|x0.05|y2m"]]
    trips, _ = W3.market_trips(r, t, cells)
    assert trips, "the random tape should trade"
    for key, tr in trips.items():
        arr = W3.encode(tr, W3.CELL_CODE[key])
        arr["mi"] = np.zeros(len(tr), dtype=np.int32)
        got = W3.decode(arr, np.ones(len(tr), dtype=bool), u)
        want = C.trips_frame(tr).sort_values(["t_entry", "id"], kind="stable").reset_index(drop=True)
        pd.testing.assert_frame_equal(got[C.TRIP_COLUMNS], want, check_dtype=False, rtol=1e-12, atol=1e-12)
        assert set(got["side"]) <= {"team1", "team2"} and (got["sport"] == "tennis").all()


def test_trips_never_read_past_their_exit_and_signals_never_read_the_future():
    t = _random_tape(5)
    r = row(end=float(t.ts[-1]) - 100, closed_time=float(t.ts[-1]) + 10)
    cell = W3.CELLS["fade|x0.05|y2m|tp0.05|sl0.05|t15m|taker"]
    trips, _ = W3.market_trips(r, t, [cell])
    tr = [x for x in trips[cell.key] if x["exit_leg"] != "settle"]
    assert len(tr) >= 3
    for x in tr[:5]:
        cut = t.until(x["t_exit"])
        mk = W3.make_market(r, cut, cell.entry.y_s)
        again = C.simulate(mk, x["o"], x["t_signal"], cell.exits)
        assert again["t_exit"] == x["t_exit"] and again["p_exit"] == x["p_exit"] and again["reason"] == x["reason"]
    full = C.swing_signals(t, 0.05, 120, 5, "fade")
    for k in range(50, len(t), 97):
        assert (C.swing_signals(C.Tape(t.ts[:k], t.p0[:k], t.buy0[:k], t.size[:k]), 0.05, 120, 5, "fade")
                == full[:k]).all()


def test_placebo_counterparts_stay_in_play():
    t = _random_tape(6)
    r = row(end=float(t.ts[-1]) - 100)
    cell = W3.CELLS["mom|x0.05|y5m|tp0.05|sl0.05|t15m|maker"]
    mk = W3.make_market(r, t, cell.entry.y_s)
    m = C.placebo_matrix(mk, 3, cell.exits, draws=20, rng=np.random.default_rng(1))
    assert m.shape == (20, 3) and np.isfinite(m).mean() > 0.9
    rng = np.random.default_rng(2)
    times = C._draw_times(mk.entry_windows, rng, 500)
    assert (times >= START + 300).all() and (times < r["end"]).all()


DATA = C.LAB4_DATA / "p6_meta.parquet"


@pytest.mark.skipif(not DATA.exists(), reason="lab 4 P6 metadata not cached")
def test_universe_mirrors_lab4_p6():
    """Structure only: W3's mirrored universe = P6's own with_game_facts / is_universe minus sport 'other'."""
    code = (
        "import sys, json; sys.path.insert(0, 'research/lab4/P6'); sys.path.insert(0, 'research/lab4');"
        "import core as L4, p6, pandas as pd; from pathlib import Path;"
        f"S = Path({str(C.LAB4_DATA)!r}); m = pd.read_parquet(S / 'markets.parquet'); meta = p6.load_meta(S);"
        "g = p6.with_game_facts(L4.Dataset.eligible(m, 'train'), meta); g = g[p6.is_universe(g) & (g.sport != 'other')];"
        "print(json.dumps({'ids': sorted(g.id.astype(str)), 'end': {str(i): float(e) for i, e in zip(g.id, g.end)},"
        "'kind': {str(i): str(k) for i, k in zip(g.id, g.end_kind)}}))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=LAB7.parents[1], capture_output=True, text=True, check=True)
    p6 = json.loads(out.stdout)
    u = W3.universe("train")
    assert sorted(u["id"].astype(str)) == p6["ids"]
    assert all(math.isclose(float(e), p6["end"][str(i)]) for i, e in zip(u["id"], u["end"], strict=True))
    assert all(str(k) == p6["kind"][str(i)] for i, k in zip(u["id"], u["end_kind"], strict=True))
    assert (u["end_kind"] == W3.WHISTLE).sum() == 4392  # PLAN §3: about 4,390 TRAIN markets with a recorded end


def test_run_stage_end_to_end_on_a_synthetic_universe(monkeypatch, tmp_path):
    """The whole TRAIN pipeline on three random markets (two with a recorded end, one without): every cell is
    reported and recorded once, the fallback-end market never enters the deciding readings, files are written."""
    tapes = {"a": _random_tape(11), "b": _random_tape(12), "c": _random_tape(13)}
    rows = [row(id=k, event_slug=f"ev-{k}", end=float(t.ts[-1]) - 100, closed_time=float(t.ts[-1]) + 10,
                end_kind=W3.FALLBACK if k == "c" else W3.WHISTLE, winner_index=int(k == "b"))
            for k, t in tapes.items()]
    u = pd.DataFrame(rows)
    monkeypatch.setattr(W3, "universe", lambda split: u.copy())
    monkeypatch.setattr(C, "load_tape", lambda mid, trades_dir=None, min_fills=0: tapes.get(str(mid)))
    monkeypatch.setattr(W3, "HERE", tmp_path)
    monkeypatch.setattr(W3, "OUT_DIR", tmp_path / "out")
    (tmp_path / "PREREG.md").write_text("test prereg\n")
    monkeypatch.setattr(W3, "PREREG", tmp_path / "PREREG.md")
    ledger: list = []
    monkeypatch.setattr(C, "record_runs", lambda entries, ledger_path=None: ledger.extend(entries) or len(ledger))
    doc = W3.run_stage("train", B=50, workers=1)
    assert doc["verdict"] in ("NO_EDGE_TRAIN", "TRAIN_SELECTED")
    assert len(doc["cells"]) == 296 and [c["cell"] for c in doc["cells"]] == list(W3.CELLS)
    assert len(ledger) == 296 and {e["kind"] for e in ledger} == {"selectable", "reference"}
    assert all(e["prereg_sha256"] == C.prereg_sha256(tmp_path / "PREREG.md") for e in ledger)
    traded = [c for c in doc["cells"] if c["summary"]["n"]]
    assert traded and all(c["extra"]["by_sport"] for c in traded)
    assert all(set(c["extra"]["by_side4"]) <= {"team1", "team2"} for c in traded)
    assert any(c["fallback"]["n"] for c in doc["cells"])  # market c is read apart ...
    assert all(c["summary"]["n_events"] <= 2 for c in doc["cells"])  # ... and never decides
    md = (tmp_path / "train.md").read_text()
    assert md.count("\n| `") >= 296 and "Decision:" in md.splitlines()[2]
    assert json.loads((tmp_path / "train.json").read_text())["n_trials_total"] == 296
    assert doc["placebo_readings"] and all(doc["cells"][W3.CELL_CODE[k]]["placebo"] for k in doc["placebo_readings"])


def test_an_interrupted_placebo_resumes_from_the_walk_checkpoint(monkeypatch, tmp_path):
    tapes = {"a": _random_tape(21), "b": _random_tape(22)}
    rows = [row(id=k, event_slug=f"ev-{k}", end=float(t.ts[-1]) - 100, closed_time=float(t.ts[-1]) + 10)
            for k, t in tapes.items()]
    u = pd.DataFrame(rows)
    monkeypatch.setattr(W3, "universe", lambda split: u.copy())
    monkeypatch.setattr(C, "load_tape", lambda mid, trades_dir=None, min_fills=0: tapes.get(str(mid)))
    monkeypatch.setattr(W3, "HERE", tmp_path)
    monkeypatch.setattr(W3, "OUT_DIR", tmp_path / "out")
    (tmp_path / "PREREG.md").write_text("test prereg\n")
    monkeypatch.setattr(W3, "PREREG", tmp_path / "PREREG.md")
    monkeypatch.setattr(C, "record_runs", lambda entries, ledger_path=None: len(entries))
    fresh = W3.run_stage("train", B=50, workers=1)
    assert not (tmp_path / "out" / "walk_train.pkl").exists()  # removed after a finished stage
    real_pass = W3.placebo_pass

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(W3, "placebo_pass", boom)
    with pytest.raises(KeyboardInterrupt):
        W3.run_stage("train", B=50, workers=1)
    assert (tmp_path / "out" / "walk_train.pkl").exists()
    monkeypatch.setattr(W3, "placebo_pass", real_pass)
    walked = []
    monkeypatch.setattr(W3, "evaluate", lambda *a, **k: walked.append(1) or (_ for _ in ()).throw(AssertionError))
    again = W3.run_stage("train", B=50, workers=1)  # no walk: the checkpoint carries it
    assert not walked and again["coverage"].get("walk_from_checkpoint")
    strip = lambda d: [{k: v for k, v in c.items()} for c in d["cells"]]  # noqa: E731
    assert json.dumps(strip(again), sort_keys=True, default=str) == json.dumps(strip(fresh), sort_keys=True, default=str)

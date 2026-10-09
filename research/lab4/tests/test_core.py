"""Tests for research/lab4/core.py and run.py on synthetic markets and tapes: fee families and the fee formula,
dataset filtering (binary, single winner, split bounds, min fills), the cell rule (first hit, latency fill,
missed, control), the readings and the calibration placebo, the TEST gate, the ledger count, and the stages."""

import json
import os
from datetime import UTC, datetime

import core as C
import numpy as np
import pandas as pd
import pytest
import run as R

DAY = 86400


def _ts(date: str) -> float:
    return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


def test_fee_families_and_formula():
    assert (
        C.fee_family("sports_fees_v3", True) == "sports"
        and C.fee_rate("sports_fees_v3", True) == 0.05
    )
    assert (
        C.fee_rate("crypto_fees_v2", True) == 0.07
        and C.fee_rate("politics_fees", True) == 0.04
    )
    assert C.fee_rate("zero_fees", True) == 0.0 and C.fee_rate("anything", False) == 0.0
    assert (
        C.fee_rate("mystery_fees", True) == C.UNKNOWN_RATE
        and C.fee_rate(None, True) == C.UNKNOWN_RATE
    )
    assert C.taker_fee(100, 0.98, 0.05) == pytest.approx(100 * 0.05 * 0.98 * 0.02)


def _write_universe(out, n_train=130, n_val=120, upsets=0.01, seed=0, late_only=False):
    """Markets whose winner trades at 0.5 until the last hour, then ramps to 0.98 and prints 0.99 after the end.
    A share ``upsets`` of markets have the 0.98 side LOSE (the tail)."""
    rng = np.random.default_rng(seed)
    (out / "trades").mkdir(parents=True, exist_ok=True)
    rows = []
    mid = 0
    for split, n in (("train", n_train), ("val", n_val)):
        lo, hi = C.split_bounds(split)
        for k in range(n):
            mid += 1
            closed = lo + (k + 0.5) * (hi - lo) / n
            fav = int(rng.integers(0, 2))  # the outcome that looks certain
            upset = rng.random() < upsets
            winner = 1 - fav if upset else fav
            fee_type = "sports_fees_v3" if k % 3 else "crypto_fees_v2"
            rows.append(
                {
                    "id": str(mid),
                    "condition_id": f"0x{mid:x}",
                    "question": f"M{mid}",
                    "slug": f"m{mid}",
                    "event_slug": "e",
                    "event_title": "E",
                    "outcomes": '["Yes","No"]',
                    "outcome_prices": "[1,0]" if winner == 0 else "[0,1]",
                    "token_ids": '["a","b"]',
                    "n_outcomes": 2,
                    "winner_index": winner,
                    "closed_time": closed,
                    "end_date": closed,
                    "start_date": closed - 7 * DAY,
                    "volume": 50_000.0,
                    "liquidity": 0.0,
                    "fees_enabled": True,
                    "taker_base_fee": 1000,
                    "maker_base_fee": 0,
                    "fee_type": fee_type,
                    "neg_risk": False,
                    "resolution_status": "resolved",
                    "resolved_by": "0x",
                }
            )
            ts, px, oi = [], [], []
            for s in range(
                -6 * 3600, -3600, 300
            ):  # six hours of 0.5 on the favourite's token
                ts.append(closed + s), px.append(0.5), oi.append(fav)
            for s in range(-3600, -1200, 60):  # the ramp 0.90 -> 0.98 in the last hour
                (
                    ts.append(closed + s),
                    px.append(0.90 + 0.08 * (s + 3600) / 2400),
                    oi.append(fav),
                )
            for s in range(
                -1200, 0, 30
            ):  # the post-event 0.99 prints, half on the other token at 0.01
                (
                    ts.append(closed + s),
                    px.append(0.99 if s % 60 else 0.01),
                    oi.append(fav if s % 60 else 1 - fav),
                )
            n_fills = len(ts)
            pd.DataFrame(
                {
                    "ts": ts,
                    "price": px,
                    "size": [10.0] * n_fills,
                    "side": ["BUY"] * n_fills,
                    "outcome_index": oi,
                    "asset": ["a"] * n_fills,
                    "tx": [f"0x{i}" for i in range(n_fills)],
                }
            ).to_parquet(out / "trades" / f"{mid}.parquet", index=False)
    # a market that is not binary, one with a split resolution, one with too few fills
    extra = [
        dict(rows[0], id="x1", n_outcomes=3),
        dict(rows[0], id="x2", winner_index=-1),
        dict(rows[0], id="x3"),
    ]
    rows += extra
    pd.DataFrame(
        {
            "ts": [rows[0]["closed_time"] - 60],
            "price": [0.98],
            "size": [1.0],
            "side": ["BUY"],
            "outcome_index": [0],
            "asset": ["a"],
            "tx": ["0x"],
        }
    ).to_parquet(out / "trades" / "x3.parquet", index=False)
    pd.DataFrame(rows).to_parquet(out / "markets.parquet", index=False)
    return mid


def test_dataset_filters_and_split_bounds(tmp_path):
    n = _write_universe(tmp_path, n_train=20, n_val=10)
    ds = C.Dataset.load("train", tmp_path)
    assert len(ds.markets) == 20 and set(ds.markets["family"]) == {"sports", "crypto"}
    assert not set(ds.markets["id"]) & {"x1", "x2", "x3"}
    lo, hi = C.split_bounds("train")
    assert (ds.markets["closed_time"] >= lo).all() and (
        ds.markets["closed_time"] < hi
    ).all()
    tape = ds.tapes[ds.markets["id"].iloc[0]]
    assert (
        list(tape.columns) == ["ts", "p0", "size"]
        and tape["ts"].is_monotonic_increasing
    )
    assert len(C.Dataset.load("val", tmp_path).markets) == 10 and n == 30
    assert len(ds.families("sports")) + len(ds.families("crypto")) == 20


def test_test_split_is_gated(monkeypatch):
    monkeypatch.delenv("LAB4_ALLOW_TEST", raising=False)
    with pytest.raises(PermissionError):
        C.check_split_allowed("test")
    monkeypatch.setenv("LAB4_ALLOW_TEST", "1")
    C.check_split_allowed("test")


def test_cell_trades_first_hit_latency_and_control(tmp_path):
    _write_universe(tmp_path, n_train=30, n_val=0, upsets=0.0)
    ds = C.Dataset.load("train", tmp_path)
    tr = C.cell_trades(ds, 0.95, 1.0, "all")
    assert len(tr) == 30 and not tr["missed"].any() and tr["won"].all()
    assert (tr["p_signal"] >= 0.95).all() and (
        tr["p_exec"] >= tr["p_signal"] - 1e-9
    ).all()  # the ramp rises
    assert (tr["t_exec"] - tr["t_signal"] >= C.LATENCY_S).all() and (
        tr["lock_h"] > 0
    ).all()
    one = tr.iloc[0]
    assert one["net"] == pytest.approx((20 / one["p_exec"] - one["fee_usd"] - 20) / 20)
    # a 0.99 signal exists only after the event; with H = 10 minutes nothing before -20 min qualifies at 0.995
    assert len(C.cell_trades(ds, 0.995, 1.0, "all")) == 0
    # the window cuts the signal: six hours at 0.5 only
    assert (
        len(C.cell_trades(ds, 0.95, 1.0 / 60.0, "all")) == 30
    )  # 0.99 prints in the last minute
    assert (
        len(C.cell_trades(ds, 0.95, 1.0, "sports"))
        + len(C.cell_trades(ds, 0.95, 1.0, "crypto"))
        == 30
    )
    ctrl = C.cell_trades(ds, 0.95, 1.0, "all", control=True)
    assert (
        len(ctrl) == 30 and not ctrl["won"].any() and (ctrl["net"] < -1.0).all()
    )  # longshots lose + fee
    # latency with no fill inside the window: missed
    ds2 = C.Dataset(
        "train",
        ds.markets.iloc[:1].copy(),
        {ds.markets["id"].iloc[0]: ds.tapes[ds.markets["id"].iloc[0]].iloc[:1]},
    )
    m = ds2.markets.iloc[0]
    ds2.tapes[m["id"]] = pd.DataFrame(
        {
            "ts": [m["closed_time"] - 1800],
            "p0": [0.98 if m["winner_index"] == 0 else 0.02],
            "size": [1.0],
        }
    )
    missed = C.cell_trades(ds2, 0.95, 1.0, "all")
    assert (
        len(missed) == 1
        and bool(missed["missed"].iloc[0])
        and missed["net"].iloc[0] is None
        or np.isnan(missed["net"].iloc[0])
    )


def test_summarize_placebo_and_qualifies(tmp_path):
    _write_universe(tmp_path, n_train=130, n_val=0, upsets=0.0)
    ds = C.Dataset.load("train", tmp_path)
    tr = C.cell_trades(ds, 0.95, 1.0, "all")
    s = C.summarize(tr, "train", B=300)
    assert (
        s["n"] == 130
        and s["win_rate"] == 1.0
        and s["mean_net"] > 0
        and s["ci95"][0] > 0
    )
    assert s["calibration_gap"] == pytest.approx(1.0 - s["mean_p_exec"])
    assert (
        s["longest_losing_streak"] == 0
        and s["daily"]["n_days"] >= 40
        and s["daily"]["total_usd"] > 0
    )
    assert set(s["by_family"]) == {"sports", "crypto"} and s["trades_per_day"] > 2
    assert C.qualifies(s) and not C.qualifies({**s, "n": 50})
    p = C.calibration_placebo(tr, draws=400)
    assert (
        p["draws"] == 400 and p["mean"] < s["mean_net"] and p["real_percentile"] >= 95.0
    )
    # with upsets the tail shows up
    _write_universe(tmp_path / "u", n_train=130, n_val=0, upsets=0.3, seed=2)
    su = C.summarize(
        C.cell_trades(C.Dataset.load("train", tmp_path / "u"), 0.95, 1.0, "all"),
        "train",
        B=200,
    )
    assert (
        su["win_rate"] < 0.9
        and su["worst_pnl_usd"] < -19
        and su["longest_losing_streak"] >= 1
        and not C.qualifies(su)
    )
    empty = C.summarize(C.cell_trades(ds, 0.999, 1.0, "all"), "train")
    assert empty["n"] == 0 and empty["mean_net"] is None and not C.qualifies(empty)


def test_ledger_counts_across_labs(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "LEDGER", tmp_path / "trials.json")
    sib = tmp_path / "lab2.json"
    sib.write_text(json.dumps([{"a": 1}, {"a": 2}]))
    monkeypatch.setattr(C, "SIBLING_LEDGERS", (sib, tmp_path / "missing.json"))
    assert C.trials_count() == 2
    assert (
        C.record_run({"lab": "lab4", "cell": "x"}) == 3
        and C.record_run({"lab": "lab4", "cell": "y"}) == 4
    )


def test_stages_train_val_and_gated_test(tmp_path, monkeypatch):
    _write_universe(
        tmp_path / "d", n_train=165, n_val=165, upsets=0.0
    )  # ~110 sports markets per split
    here = tmp_path / "lab"
    here.mkdir()
    (here / "PLAN.md").write_text("plan\n")
    monkeypatch.setattr(R, "PLAN", here / "PLAN.md")
    monkeypatch.setattr(C, "LEDGER", here / "trials.json")
    monkeypatch.setattr(C, "SIBLING_LEDGERS", ())
    monkeypatch.delenv("LAB4_ALLOW_TEST", raising=False)
    res = R.run_stage(
        "train", hyps=["P2", "C1"], out_dir=tmp_path / "d", B=100, here=here
    )
    assert res["P2"]["decision"].startswith("SELECTED") and res["P2"]["selected"][
        "key"
    ].startswith("theta")
    assert res["C1"]["selected"] is None and "CONTROL" in res["C1"]["decision"]
    assert (here / "P2" / "train.md").exists() and "| cell |" in (
        here / "P2" / "train.md"
    ).read_text()
    assert len(json.loads((here / "trials.json").read_text())) == 12 + 12
    val = R.run_stage(
        "val", hyps=["P2", "P1"], out_dir=tmp_path / "d", B=100, here=here
    )
    assert (
        val["P2"]["decision"].startswith("SELECTED")
        and val["P2"]["cells"][0]["placebo"]["real_percentile"] >= 95
    )
    assert val["P1"]["decision"].startswith(
        "NOT RUN"
    )  # P1 has no TRAIN file in this run
    with pytest.raises(PermissionError):
        R.run_stage("test", hyps=["P2"], out_dir=tmp_path / "d", B=100, here=here)
    assert "| P2 |" in (here / "RESULTS.md").read_text()
    os.environ.pop("LAB4_ALLOW_TEST", None)

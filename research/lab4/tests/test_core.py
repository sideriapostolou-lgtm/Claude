"""Tests for research/lab4/core.py and run.py on synthetic markets and tapes (Amendment 3 semantics): fee families
and the fee formula, dataset filtering and coverage, the cell rule (buyable prints only, endDate windows, H = inf,
latency fill, missed, control), the readings (event bootstrap, losses, rule-of-three worst case, bid-side share),
the calibration placebo, the TEST gate, the ledger upsert and cross-lab count, and the stages."""

import json
import os

import core as C
import numpy as np
import pandas as pd
import pytest
import run as R

DAY = 86400


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


def _write_universe(
    out, n_train=130, n_val=120, upset_every=0, seed=0, sell_prints=False
):
    """Markets whose favourite trades at 0.5 until the last hour, then ramps 0.90 -> 0.98 (BUY prints on the
    favourite's token: buyable) and prints 0.99 after the end. Every ``upset_every``-th market has the favourite
    LOSE. ``sell_prints``: the ramp is printed as SELLs on the favourite's token (bid-side: not buyable).
    ``end_date`` equals ``closed_time`` and every pair of markets shares an event."""
    rng = np.random.default_rng(seed)
    (out / "trades").mkdir(parents=True, exist_ok=True)
    rows = []
    mid = 0
    for split, n in (("train", n_train), ("val", n_val)):
        lo, hi = C.split_bounds(split)
        for k in range(n):
            mid += 1
            closed = lo + (k + 0.5) * (hi - lo) / n
            fav = int(rng.integers(0, 2))
            upset = upset_every > 0 and k % upset_every == upset_every - 1
            winner = 1 - fav if upset else fav
            fee_type = "sports_fees_v3" if k % 3 else "crypto_fees_v2"
            rows.append(
                {
                    "id": str(mid),
                    "condition_id": f"0x{mid:x}",
                    "question": f"M{mid}",
                    "slug": f"m{mid}",
                    "event_slug": f"ev{mid // 2}",
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
            ts, px, oi, side = [], [], [], []
            for s_ in range(-6 * 3600, -3600, 300):
                (
                    ts.append(closed + s_),
                    px.append(0.5),
                    oi.append(fav),
                    side.append("BUY"),
                )
            for s_ in range(-3600, -1200, 60):
                (
                    ts.append(closed + s_),
                    px.append(0.90 + 0.08 * (s_ + 3600) / 2400),
                    oi.append(fav),
                )
                side.append("SELL" if sell_prints else "BUY")
            for s_ in range(-1200, 0, 30):
                (
                    ts.append(closed + s_),
                    px.append(0.99 if s_ % 60 else 0.01),
                    oi.append(fav if s_ % 60 else 1 - fav),
                )
                side.append("BUY")
            n_fills = len(ts)
            pd.DataFrame(
                {
                    "ts": ts,
                    "price": px,
                    "size": [10.0] * n_fills,
                    "side": side,
                    "outcome_index": oi,
                    "asset": ["a"] * n_fills,
                    "tx": [f"0x{i}" for i in range(n_fills)],
                }
            ).to_parquet(out / "trades" / f"{mid}.parquet", index=False)
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


def test_dataset_filters_split_bounds_and_coverage(tmp_path):
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
        list(tape.columns) == ["ts", "p0", "buy0", "size"]
        and tape["ts"].is_monotonic_increasing
    )
    assert ds.coverage == {"eligible": 21, "with_tape": 21, "share": 1.0}
    assert len(C.Dataset.load("val", tmp_path).markets) == 10 and n == 30
    assert len(ds.families("sports")) + len(ds.families("crypto")) == 20
    (tmp_path / "trades" / "1.parquet").unlink()
    assert C.Dataset.load("train", tmp_path).coverage == {
        "eligible": 21,
        "with_tape": 20,
        "share": 20 / 21,
    }


def test_test_split_is_gated(monkeypatch):
    monkeypatch.delenv("LAB4_ALLOW_TEST", raising=False)
    with pytest.raises(PermissionError):
        C.check_split_allowed("test")
    monkeypatch.setenv("LAB4_ALLOW_TEST", "1")
    C.check_split_allowed("test")


def test_cell_trades_buyable_window_latency_inf_and_control(tmp_path):
    _write_universe(tmp_path, n_train=30, n_val=0)
    ds = C.Dataset.load("train", tmp_path)
    tr = C.cell_trades(ds, 0.95, 1.0, "all")
    assert len(tr) == 30 and not tr["missed"].any() and tr["won"].all()
    assert (tr["p_signal"] >= 0.95).all() and (
        tr["p_signal"] < 0.99
    ).all()  # the ramp, not the post-event 0.99s
    assert (tr["p_exec"] >= tr["p_signal"] - 1e-9).all() and (
        tr["t_exec"] - tr["t_signal"] >= C.LATENCY_S
    ).all()
    assert (tr["lock_h"] > 0).all() and not tr["old_rule_bid_side"].any()
    one = tr.iloc[0]
    assert one["net"] == pytest.approx((20 / one["p_exec"] - one["fee_usd"] - 20) / 20)
    assert len(C.cell_trades(ds, 0.995, 1.0, "all")) == 0
    assert (
        len(C.cell_trades(ds, 0.95, 1.0, "sports"))
        + len(C.cell_trades(ds, 0.95, 1.0, "crypto"))
        == 30
    )
    inf = C.cell_trades(ds, 0.95, C.INF, "all")
    assert len(inf) == 30 and (inf["t_exec"] < inf["closed_time"]).all()
    ctrl = C.cell_trades(
        ds, 0.95, C.INF, "all", control=True
    )  # the longshot at <= 0.05, buyable prints only
    assert len(ctrl) == 30 and not ctrl["won"].any() and (ctrl["net"] < -1.0).all()
    mkt = ds.markets.iloc[:1].copy()
    m = mkt.iloc[0]
    tape = pd.DataFrame(
        {
            "ts": [m["closed_time"] - 1800],
            "p0": [0.98 if m["winner_index"] == 0 else 0.02],
            "buy0": [m["winner_index"] == 0],
            "size": [1.0],
        }
    )
    missed = C.cell_trades(
        C.Dataset("train", mkt, {m["id"]: tape}, ds.coverage), 0.95, 1.0, "all"
    )
    assert (
        len(missed) == 1
        and bool(missed["missed"].iloc[0])
        and pd.isna(missed["net"].iloc[0])
    )


def test_bid_side_prints_are_not_buyable(tmp_path):
    """Amendment 3: a SELL print on the favourite's token is a bid, not an ask."""
    _write_universe(tmp_path, n_train=12, n_val=0, sell_prints=True)
    ds = C.Dataset.load("train", tmp_path)
    tr = C.cell_trades(ds, 0.95, 1.0, "all")
    assert len(tr) == 12 and np.allclose(
        tr["p_signal"], 0.99
    )  # only the post-event BUY prints
    m = ds.markets.iloc[0]
    w = int(m["winner_index"])
    tape = pd.DataFrame(
        {
            "ts": [
                m["closed_time"] - 3000,
                m["closed_time"] - 2000,
                m["closed_time"] - 1000,
            ],
            "p0": [0.97, 0.97, 0.98] if w == 0 else [0.03, 0.03, 0.02],
            "buy0": [False, False, True] if w == 0 else [True, True, False],
            "size": [1, 1, 1],
        }
    )
    ds2 = C.Dataset("train", ds.markets.iloc[:1].copy(), {m["id"]: tape}, ds.coverage)
    tr2 = C.cell_trades(ds2, 0.95, 1.0, "all")
    assert (
        len(tr2) == 1
        and tr2["t_signal"].iloc[0] == m["closed_time"] - 1000
        and bool(tr2["missed"].iloc[0])
    )
    tape3 = pd.DataFrame(
        {
            "ts": [
                m["closed_time"] - 3000,
                m["closed_time"] - 2980,
                m["closed_time"] - 2900,
            ],
            "p0": [0.97, 0.97, 0.975] if w == 0 else [0.03, 0.03, 0.025],
            "buy0": [True, False, True] if w == 0 else [False, True, False],
            "size": [1, 1, 1],
        }
    )
    tr3 = C.cell_trades(
        C.Dataset("train", ds.markets.iloc[:1].copy(), {m["id"]: tape3}, ds.coverage),
        0.95,
        1.0,
        "all",
    )
    assert (
        len(tr3) == 1
        and not bool(tr3["missed"].iloc[0])
        and tr3["p_exec"].iloc[0] == pytest.approx(0.975)
    )
    assert bool(
        tr3["old_rule_bid_side"].iloc[0]
    )  # the side-blind rule would have filled at the bid print


def test_summarize_placebo_and_qualifies(tmp_path):
    _write_universe(tmp_path, n_train=130, n_val=0)
    ds = C.Dataset.load("train", tmp_path)
    tr = C.cell_trades(ds, 0.95, 1.0, "all")
    s = C.summarize(tr, "train", B=300)
    assert (
        s["n"] == 130
        and s["win_rate"] == 1.0
        and s["mean_net"] > 0
        and s["ci95"][0] > 0
    )
    assert s["losses"] == 0 and s["n_events"] == 66 and s["bid_side_share"] == 0.0
    assert s["calibration_gap"] == pytest.approx(1.0 - s["mean_p_exec"])
    assert (
        s["longest_losing_streak"] == 0
        and s["daily"]["n_days"] >= 40
        and s["daily"]["total_usd"] > 0
    )
    assert set(s["by_family"]) == {"sports", "crypto"} and s["trades_per_day"] > 2
    assert not C.qualifies(
        s
    )  # Amendment 3: no observed loss -> cannot qualify, whatever the CI
    assert s["worst_case_net"] == pytest.approx((1 - 3 / 130) * s["mean_net"] - 3 / 130)
    p = C.calibration_placebo(tr, draws=400)
    assert (
        p["draws"] == 400 and p["mean"] < s["mean_net"] and p["real_percentile"] >= 95.0
    )
    _write_universe(tmp_path / "big", n_train=750, n_val=0, upset_every=150, seed=2)
    sb = C.summarize(
        C.cell_trades(C.Dataset.load("train", tmp_path / "big"), 0.95, 1.0, "all"),
        "train",
        B=200,
    )
    assert (
        sb["losses"] == 5
        and sb["mean_net"] > 0
        and sb["ci95"][0] > 0
        and C.qualifies(sb)
    )
    _write_universe(tmp_path / "u", n_train=130, n_val=0, upset_every=3, seed=2)
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


def test_event_bootstrap_groups_events():
    values = np.array([1.0, 1.0, -1.0, -1.0])
    one_event_each = C.event_bootstrap_ci(values, np.array(["a", "b", "c", "d"]), B=500)
    paired = C.event_bootstrap_ci(values, np.array(["a", "a", "b", "b"]), B=500)
    assert (
        paired[0] <= one_event_each[0] and paired[1] >= one_event_each[1]
    )  # fewer independent draws: wider


def test_ledger_counts_across_labs_and_upserts(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "LEDGER", tmp_path / "trials.json")
    sib = tmp_path / "lab2.json"
    sib.write_text(json.dumps({"runs": [1, 2], "n_trials_total": 2767}))
    sib3 = tmp_path / "lab3.json"
    sib3.write_text(json.dumps({"configs": {}, "runs": [1, 2, 3]}))
    monkeypatch.setattr(C, "SIBLING_LEDGERS", (sib, sib3, tmp_path / "missing.json"))
    assert C.trials_count() == 2770
    e = {"lab": "lab4", "hyp": "P1", "cell": "x", "split": "train", "stage": "train"}
    assert C.record_run(e) == 2771 and C.record_run({**e, "cell": "y"}) == 2772
    assert C.record_run(e) == 2772  # a re-run replaces its own entry


def test_stages_train_val_and_gated_test(tmp_path, monkeypatch):
    _write_universe(tmp_path / "d", n_train=750, n_val=750, upset_every=149)
    here = tmp_path / "lab"
    here.mkdir()
    (here / "PLAN.md").write_text("plan\n")
    monkeypatch.setattr(R, "PLAN", here / "PLAN.md")
    monkeypatch.setattr(C, "LEDGER", here / "trials.json")
    monkeypatch.setattr(C, "SIBLING_LEDGERS", ())
    monkeypatch.delenv("LAB4_ALLOW_TEST", raising=False)
    monkeypatch.delenv("LAB4_ALLOW_PARTIAL", raising=False)
    res = R.run_stage(
        "train", hyps=["P2", "P4", "C1"], out_dir=tmp_path / "d", B=100, here=here
    )
    assert res["P4"]["decision"].startswith("SELECTED") and res["P4"]["selected"][
        "key"
    ].startswith("theta")
    assert res["P2"]["decision"].startswith("SELECTED") and res["P2"]["selected"][
        "key"
    ].endswith("|Hinf")
    assert res["C1"]["selected"] is None and "CONTROL" in res["C1"]["decision"]
    assert res["P4"]["coverage"]["share"] == 1.0
    md = (here / "P2" / "train.md").read_text()
    assert "oracle-timed" in md and "Tape coverage" in md and "| cell |" in md
    assert len(json.loads((here / "trials.json").read_text())) == 15 + 15 + 15
    R.run_stage("train", hyps=["P4"], out_dir=tmp_path / "d", B=100, here=here)
    assert (
        len(json.loads((here / "trials.json").read_text())) == 45
    )  # a re-run does not inflate the ledger
    val = R.run_stage(
        "val", hyps=["P4", "P1"], out_dir=tmp_path / "d", B=100, here=here
    )
    assert (
        val["P4"]["decision"].startswith("SELECTED")
        and val["P4"]["cells"][0]["placebo"]["real_percentile"] >= 95
    )
    assert val["P1"]["decision"].startswith("NOT RUN")
    with pytest.raises(PermissionError):
        R.run_stage("test", hyps=["P4"], out_dir=tmp_path / "d", B=100, here=here)
    assert "| P4 |" in (here / "RESULTS.md").read_text()
    (tmp_path / "d" / "trades" / "1.parquet").unlink()
    with pytest.raises(RuntimeError, match="incomplete"):
        R.run_stage("train", hyps=["P4"], out_dir=tmp_path / "d", B=50, here=here)
    monkeypatch.setenv("LAB4_ALLOW_PARTIAL", "1")
    partial = R.run_stage("train", hyps=["P4"], out_dir=tmp_path / "d", B=50, here=here)
    assert (
        partial["P4"]["coverage"]["with_tape"] == 750
    )  # 751 eligible incl. the thin x3
    os.environ.pop("LAB4_ALLOW_TEST", None)

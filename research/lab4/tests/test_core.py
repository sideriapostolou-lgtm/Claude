"""Tests for research/lab4/core.py and run.py on synthetic markets and tapes (Amendment 3 semantics): fee families
and the fee formula, dataset filtering and coverage, the cell rule (buyable prints only, endDate windows, H = inf,
latency fill, missed, control), the readings (event bootstrap, losses, rule-of-three worst case, bid-side share),
the calibration placebo, the TEST gate, the ledger upsert and cross-lab count, and the stages. Amendment 4: the
P5 resting-bid fill model on a tiny hand-written tape (strictly-below prints only, the size condition, both fee
assumptions, the window end) and the P5 stage (60 cells, fee0 reported only, feeT selectable)."""

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
    out, n_train=130, n_val=120, upset_every=0, seed=0, sell_prints=False, dips=False
):
    """Markets whose favourite trades at 0.5 until the last hour, then ramps 0.90 -> 0.98 (BUY prints on the
    favourite's token: buyable) and prints 0.99 after the end. Every ``upset_every``-th market has the favourite
    LOSE. ``sell_prints``: the ramp is printed as SELLs on the favourite's token (bid-side: not buyable).
    ``dips``: 1000 s before the end a seller hits the favourite's bid at 0.90 for 60 shares (a print strictly below
    any P5 bid of the ramp, with enough size to fill a $20 order). ``end_date`` equals ``closed_time`` and every
    pair of markets shares an event."""
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
            sizes = [10.0] * len(ts)
            if dips:
                ts.append(closed - 1000), px.append(0.90), oi.append(fav)
                side.append("SELL"), sizes.append(60.0)
            n_fills = len(ts)
            pd.DataFrame(
                {
                    "ts": ts,
                    "price": px,
                    "size": sizes,
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


def _bid_dataset(ds, tape_rows, winner=None):
    """One TRAIN market of ``ds`` with a hand-written tape: rows of (seconds before close, price of the favourite,
    buyable for the favourite, size); the favourite is outcome 0 unless ``winner`` says otherwise."""
    mkt = ds.markets.iloc[:1].copy()
    mkt["winner_index"] = 0 if winner is None else winner
    m = mkt.iloc[0]
    tape = pd.DataFrame(
        {
            "ts": [m["closed_time"] + s_ for s_, *_ in tape_rows],
            "p0": [p for _, p, *_ in tape_rows],
            "buy0": [b for _, _, b, _ in tape_rows],
            "size": [float(z) for *_, z in tape_rows],
        }
    )
    return C.Dataset("train", mkt, {m["id"]: tape}, ds.coverage), m


def test_bid_trades_fill_model_on_tiny_tape(tmp_path):
    """Amendment 4: the bid rests at the last bid-side print of the previous 600 s (never above ask - tick); a print
    at exactly the bid never fills; a strictly-below print fills once the bid-side size at or below the bid covers
    20 / b shares; fee0 pays nothing, feeT the taker fee; nothing fills after the window ends."""
    _write_universe(tmp_path, n_train=2, n_val=0)
    ds = C.Dataset.load("train", tmp_path)
    rows = [
        (-3700, 0.955, False, 5),  # a seller hit the bid at 0.955 (too old: 700 s before the signal)
        (-3100, 0.960, False, 5),  # a seller hit the bid at 0.960 (100 s before the signal: the reference)
        (-3000, 0.970, True, 5),  # the signal: a buyer lifted the ask at 0.97
        (-2900, 0.960, False, 5),  # exactly at our bid: never a fill (queue unknown)
        (-2800, 0.965, True, 100),  # an ask-side print below nothing: not a seller
        (-2700, 0.959, False, 10),  # strictly below 0.960: size so far 5 + 10 = 15 < 20.83 shares
        (-2600, 0.955, False, 10),  # strictly below: 25 >= 20.83 -> the fill, at 0.960
        (-2500, 0.950, False, 100),  # later and lower: irrelevant once filled
    ]
    ds1, m = _bid_dataset(ds, rows)
    tr = C.bid_trades(ds1, 0.95, 1.0, offset_ticks=0, fee_mult=1.0)
    assert len(tr) == 1 and not bool(tr["missed"].iloc[0])
    one = tr.iloc[0]
    assert one["p_signal"] == pytest.approx(0.97) and one["p_bid"] == pytest.approx(
        0.960
    )
    assert one["p_exec"] == pytest.approx(0.960) and one["t_exec"] == m[
        "closed_time"
    ] - 2600
    assert one["wait_s"] == pytest.approx(400 - 10) and bool(one["won"])
    shares = 20 / 0.96
    assert one["fee_usd"] == pytest.approx(C.taker_fee(shares, 0.96, m["rate"]))
    assert one["net"] == pytest.approx((shares - one["fee_usd"] - 20) / 20)
    assert not bool(one["size_blocked"]) and not bool(one["old_rule_bid_side"])
    free = C.bid_trades(ds1, 0.95, 1.0, offset_ticks=0, fee_mult=0.0).iloc[0]
    assert free["fee_usd"] == 0.0 and free["net"] == pytest.approx((shares - 20) / 20)
    assert free["net"] > one["net"]
    # one tick below: the bid is 0.959; prints strictly below it total 10 + 100 >= 20.85 -> fills at the 0.950 print
    low = C.bid_trades(ds1, 0.95, 1.0, offset_ticks=1).iloc[0]
    assert low["p_bid"] == pytest.approx(0.959) and low["t_exec"] == m["closed_time"] - 2500
    # the size condition: with the 0.950 print gone, 10 shares strictly below 0.959 never cover the order
    ds2, _ = _bid_dataset(ds, rows[:-1])
    blocked = C.bid_trades(ds2, 0.95, 1.0, offset_ticks=1).iloc[0]
    assert bool(blocked["missed"]) and bool(blocked["size_blocked"])
    assert pd.isna(blocked["net"]) and pd.isna(blocked["p_exec"])
    # no bid-side print in the previous 600 s: the bid is the ask minus one tick (0.969), and a reference above the
    # ask is capped there
    ds3, _ = _bid_dataset(ds, [rows[2], (-2000, 0.968, False, 50)])
    cap = C.bid_trades(ds3, 0.95, 1.0).iloc[0]
    assert cap["p_bid"] == pytest.approx(0.969) and not bool(cap["missed"])
    ds4, _ = _bid_dataset(ds, [(-3100, 0.985, False, 5), rows[2], (-2000, 0.968, False, 50)])
    assert C.bid_trades(ds4, 0.95, 1.0).iloc[0]["p_bid"] == pytest.approx(0.969)
    # a seller after the window's end cannot fill: the bid was cancelled
    ds5, _ = _bid_dataset(ds, [rows[1], rows[2], (+100, 0.900, False, 50)])
    late = C.bid_trades(ds5, 0.95, 1.0).iloc[0]
    assert bool(late["missed"]) and not bool(late["size_blocked"])
    # a lost market: the bid fills on the way down and the fill settles at zero
    ds6, _ = _bid_dataset(ds, rows, winner=1)
    lost = C.bid_trades(ds6, 0.95, 1.0).iloc[0]
    assert not bool(lost["won"]) and lost["pnl_usd"] == pytest.approx(
        -20 - lost["fee_usd"]
    )
    # no signal in the window, no row; the maker readings on an empty frame
    assert len(C.bid_trades(ds1, 0.995, 1.0)) == 0
    assert C.maker_extra(C.bid_trades(ds1, 0.995, 1.0))["fill_rate"] is None
    ex = C.maker_extra(pd.concat([tr, blocked.to_frame().T], ignore_index=True))
    assert ex["signals"] == 2 and ex["fill_rate"] == 0.5 and ex["size_blocked"] == 1
    assert ex["improvement"] == pytest.approx(0.01) and ex["wait_s_median"] == 390.0


def test_stage_train_p5_cells_fees_and_tags(tmp_path, monkeypatch):
    """The P5 grid is 60 cells (3 theta x 5 H x 2 offsets x 2 fees); fee0 cells are tagged and never selected; the
    synthetic dip fills every bid at the ramp's bid; without dips nothing fills and no cell can qualify."""
    _write_universe(tmp_path / "d", n_train=750, n_val=0, upset_every=149, dips=True)
    here = tmp_path / "lab"
    here.mkdir()
    (here / "PLAN.md").write_text("plan\n")
    monkeypatch.setattr(R, "PLAN", here / "PLAN.md")
    monkeypatch.setattr(C, "LEDGER", here / "trials.json")
    monkeypatch.setattr(C, "SIBLING_LEDGERS", ())
    monkeypatch.delenv("LAB4_ALLOW_PARTIAL", raising=False)
    res = R.run_stage("train", hyps=["P5"], out_dir=tmp_path / "d", B=100, here=here)
    doc = res["P5"]
    assert len(doc["cells"]) == 60 and len(json.loads((here / "trials.json").read_text())) == 60
    keys = [c["key"] for c in doc["cells"]]
    assert "theta0.97|H1|b-0|feeT" in keys and "theta0.99|Hinf|b-1|fee0" in keys
    assert doc["decision"].startswith("SELECTED") and doc["selected"]["fee"] == "feeT"
    assert doc["selected"]["key"].endswith("|feeT") and "offset" in doc["selected"]
    by_key = {c["key"]: c for c in doc["cells"]}
    a, b = by_key["theta0.95|H1|b-0|feeT"], by_key["theta0.95|H1|b-0|fee0"]
    assert a["summary"]["n"] == b["summary"]["n"] == 750
    assert a["maker"]["fill_rate"] == 1.0 and a["maker"]["size_blocked"] == 0
    assert b["summary"]["mean_net"] > a["summary"]["mean_net"]  # the fee-free upper bound sits above
    assert a["summary"]["mean_p_exec"] == pytest.approx(0.949)  # the ramp's 0.95 ask, one tick under
    assert by_key["theta0.95|H1|b-1|feeT"]["summary"]["mean_p_exec"] == pytest.approx(0.948)
    assert R.reported_only("P5", b) == "fee-free upper bound, not selectable"
    assert R.reported_only("P5", a) is None and R.reported_only("P1", a) is None
    md = (here / "P5" / "train.md").read_text()
    assert "fee-free upper bound" in md and "| n/a |" in md and "bids posted" in md
    assert "Amendments 1-4" in md and "P5 (Amendment 4)" in md
    assert "| P5 |" in (here / "RESULTS.md").read_text()
    # the same universe without the dip: a bid under the ask never meets a seller
    _write_universe(tmp_path / "q", n_train=120, n_val=0)
    quiet = R.evaluate(
        C.Dataset.load("train", tmp_path / "q"), "P5", cells=[(0.95, 1.0, 0, "feeT")], B=50
    )[0]
    assert quiet["summary"]["n"] == 0 and quiet["summary"]["missed"] == 120
    assert quiet["maker"]["fill_rate"] == 0.0 and not C.qualifies(quiet["summary"])
    assert R._spec(doc["selected"]) == (
        doc["selected"]["theta"],
        doc["selected"]["hours"],
        doc["selected"]["offset"],
        "feeT",
    )
    assert R._spec({"theta": 0.97, "hours": 1.0}) == (0.97, 1.0)


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

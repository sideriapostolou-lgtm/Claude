"""Tests for research/lab2/q11.py (the value of speed): the tape's state reconstruction, one simulated trade on
controlled tapes (costs only, a doubling, censoring, the tip), the summary's frontier and value-of-speed readings."""

import numpy as np
import pandas as pd
import pytest

import q11 as Q

X0, Y0 = 84.990359056, 206.9e6
G = 1_790_000_000.0


def _tape(times, prices, buy_tok=1000.0):
    """Pool trades at ``times`` (seconds after G) whose BEFORE-state has the given prices (SOL per token) on the
    constant-product curve through the initial state."""
    k = X0 * Y0
    rows = []
    for t, p in zip(times, prices, strict=True):
        X = (k * p) ** 0.5
        y = X / p
        rows.append(
            {
                "ts": int(G + t),
                "slot": int(t * 2),
                "tx_idx": 0,
                "ix": 0,
                "venue": 1,
                "is_buy": 1,
                "x0": int(X * 1e9) - 17_584_505 * 1000,
                "virt_ksol": 17_584_505,
                "y0": int(y * 1e6),
                "tok": int(buy_tok * 1e6),
                "usol": 0,
                "fees": 0,
                "wallet_h": 0,
                "mint": "M",
                "src": 0,
                "pix": 0,
            }
        )
    rows.append({**rows[-1], "venue": 0, "ts": int(G - 300)})  # a curve trade that must be ignored
    df = pd.DataFrame(rows)
    return Q.Tape.from_trades(df, X0, Y0)


def test_tape_states_before_between_and_after():
    p0 = X0 / Y0
    tape = _tape([1, 10, 100], [p0, 2 * p0, 2 * p0])
    assert len(tape.ts) == 3 and tape.end == G + 100
    assert tape.state_at(G + 0.5) == (pytest.approx(tape.X[0]), pytest.approx(tape.y[0]))  # before the first trade
    X, y = tape.state_at(G + 5)  # between trades 1 and 2
    assert X / y == pytest.approx(2 * p0, rel=1e-9)
    Xa, ya = tape.state_at(G + 500)  # after the last: its after-state
    assert ya == pytest.approx(tape.y[2] - tape.tok[2]) and Xa * ya == pytest.approx(tape.X[2] * tape.y[2])
    empty = Q.Tape.from_trades(
        pd.DataFrame(columns=["ts", "slot", "tx_idx", "ix", "venue", "is_buy", "x0", "virt_ksol", "y0", "tok"]), X0, Y0
    )
    assert empty.state_at(G) == (X0, Y0) and empty.end == float("-inf")


def test_trade_costs_only_on_a_flat_tape():
    p0 = X0 / Y0
    tape = _tape([1, 30, 60, 120, 400], [p0] * 5)
    r = Q.simulate_trade(tape, G, 1, 60, 0.0, 100.0)
    assert r is not None and -0.05 < r["ret_net"] < 0 and r["ret_mid"] == pytest.approx(0.0)  # 1.25 % tier x2 + fees
    assert r["t_in"] == G + 1 and r["t_out"] == G + 61 and r["sol_in"] == pytest.approx(0.2)
    r_tip = Q.simulate_trade(tape, G, 1, 60, 0.01, 100.0)
    assert r_tip["ret_net"] == pytest.approx(r["ret_net"] - 0.01 / 0.2)  # the tip is paid from the ticket
    r_slip = Q.simulate_trade(tape, G, 1, 60, 0.0, 100.0, slip_s=1.0)
    assert r_slip["t_in"] == G + 2 and r_slip["t_out"] == G + 62


def test_trade_captures_a_doubling_only_when_fast_enough():
    p0 = X0 / Y0
    tape = _tape([1, 20, 40, 60, 120, 400, 2000], [p0, p0, 2 * p0, 2 * p0, 2 * p0, 2 * p0, 2 * p0])
    fast = Q.simulate_trade(tape, G, 1, 60, 0.001, 100.0)  # in at p0, out at 2 p0
    slow = Q.simulate_trade(tape, G, 60, 60, 0.001, 100.0)  # in and out at 2 p0
    assert fast["ret_mid"] == pytest.approx(1.0) and 0.9 < fast["ret_net"] < 1.0
    assert slow["ret_mid"] == pytest.approx(0.0) and -0.05 < slow["ret_net"] < 0
    assert Q.simulate_trade(tape, G, 900, 1800, 0.001, 100.0) is None  # exit past the tape: censored
    assert Q.simulate_trade(tape, G, 1, 1800, 0.001, 100.0) is not None


def test_summary_frontier_and_value_of_speed():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(60):
        m = f"M{i}"
        for slip in (0.0, 1.0):
            for L in Q.LATS:
                for H in Q.HOLDS:
                    for tip in Q.TIPS:
                        # an edge that decays with latency: +30 % at 1 s, gone by 60 s; noise 10 %
                        mean = 0.30 * max(0.0, 1 - L / 60.0) - 0.02
                        rows.append(
                            {
                                "mint": m,
                                "cls": "OPERATOR" if i % 2 else "FACTORY",
                                "censored": H == 1800 and L == 900,
                                "L": L,
                                "H": H,
                                "tip": tip,
                                "slip_s": slip,
                                "ret_net": mean + rng.normal(0, 0.10),
                                "ret_mid": mean,
                                "mcap_in_sol": 500.0,
                            }
                        )
    df = pd.DataFrame(rows)
    s = Q.summarize(df, B=300)
    assert s["n_coins"] == 60 and s["frontier"]["H60"] in (20, 30)  # positive with CI > 0 up to ~30 s
    v = s["value_of_speed"]["H60"]
    assert v["n"] == 60 and 0.2 < v["mean_diff_1s_vs_60s"] < 0.4 and v["ci95"][0] > 0
    assert s["cells"]["tip0.001|slip0|L900|H1800"]["n"] == 0 or s["cells"]["tip0.001|slip0|L900|H1800"]["censored"] >= 0
    assert set(s["by_class"]) == {"OPERATOR", "FACTORY"}
    hidden = Q.summarize(df, hide=True)
    assert hidden["returns"].startswith("hidden") and "cells" in hidden and hidden["counts"]["L1|H5"] == 60


def test_render_md_has_tables(tmp_path):
    doc = {
        "stage": "train",
        "split": "train",
        "utc": "x",
        "runtime_s": 1,
        "prereg_sha256": "abcdef123456789",
        "n_trials_total": 5,
        "summary": Q.summarize(
            pd.DataFrame(
                [
                    {
                        "mint": "a",
                        "cls": "X",
                        "censored": False,
                        "L": L,
                        "H": H,
                        "tip": t,
                        "slip_s": sl,
                        "ret_net": -0.01,
                        "ret_mid": 0.0,
                        "mcap_in_sol": 400.0,
                    }
                    for L in Q.LATS
                    for H in Q.HOLDS
                    for t in Q.TIPS
                    for sl in (0.0, 1.0)
                ]
            ),
            B=50,
        ),
    }
    md = Q.render_md(doc)
    assert "value of speed" in md and "| L \\ H |" in md and "Edge frontier" in md

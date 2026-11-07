"""Offline feature helpers: AGENT detection, B2 merging, price repair (real B2 rows from 2026-10-08)."""
import pytest

import features as F


def _cands(row):
    return F.merge_agent_candidates([row["agent_cands"]])


def test_agent_detected_on_real_pool(ch_events):
    row = ch_events["b2_rows"][0]
    a = F.detect_agent(_cands(row), row["g_ts"])
    assert a is not None
    assert 11 <= a["median_gap"] <= 13 and a["gap_band_share"] >= 0.6
    assert a["n_slices"] >= 10
    assert 0.3 < a["sol"] / a["n_slices"] < 1.0       # ~0.5-0.7 SOL slices
    # knowable only from its 4th buy (PLAN 3.2 role timing)
    assert a["known_at"] == a["buy_ts"][3] and a["known_at"] > row["g_ts"]


def test_no_agent_on_pool_without_candidates(ch_events):
    row = ch_events["b2_rows"][1]
    assert F.detect_agent(_cands(row), row["g_ts"]) is None


def test_agent_rules_synthetic():
    g = 1000
    ts = [g + 3 + 12 * i for i in range(25)]
    cands = {"A": {"ts": ts, "sol": [0.7] * 25, "sells": 0},
             "B": {"ts": ts, "sol": [5.0] * 25, "sells": 1},                    # sells: never AGENT
             "C": {"ts": [g + 1, g + 2, g + 40, g + 41], "sol": [1] * 4, "sells": 0}}   # irregular
    a = F.detect_agent(cands, g)
    assert a["wallet"] == "A" and a["n_slices"] == 25 and a["sol"] == pytest.approx(17.5)
    # buys outside [g, g+330) do not count
    late = {"A": {"ts": [g + 400 + 12 * i for i in range(6)], "sol": [1] * 6, "sells": 0}}
    assert F.detect_agent(late, g) is None
    # 3 buys are not enough
    assert F.detect_agent({"A": {"ts": ts[:3], "sol": [1] * 3, "sells": 0}}, g) is None


def test_robust_rule_tolerates_a_skipped_slice():
    g = 0
    ts = [2 + 12 * i for i in range(27)]
    del ts[5]                      # one missed slice -> a 24 s gap
    del ts[15]
    cands = {"A": {"ts": ts, "sol": [0.65] * len(ts), "sells": 0}}
    assert F.detect_agent(cands, g, rule="plan") is None     # CV ~0.24 fails PLAN's 0.15
    a = F.detect_agent(cands, g)
    assert a and a["n_slices"] == 25 and a["gap_band_share"] > 0.9


def test_merge_agent_candidates_across_chunks():
    m = F.merge_agent_candidates([[("w", [30, 18], [0.5, 0.6], 0)], [("w", [42, 54], [0.7, 0.4], 0)]])
    assert m["w"]["ts"] == [18, 30, 42, 54] and m["w"]["sol"] == [0.6, 0.5, 0.7, 0.4]


def test_merge_b2_and_repair(ch_events):
    row = dict(ch_events["b2_rows"][0])
    m = F.merge_b2([row])
    assert m["bars"] and m["bars"] == sorted(m["bars"], key=lambda b: b["minute_ts"])
    # simulate a chunk without buys (virt unknown => price computed as x / y)
    b = m["bars"][-1]
    broken = dict(b, close=b["x_close"] / b["y_close"])
    fixed = F.repair_prices([broken], row["virt_sol"])[0]
    assert fixed["close"] == pytest.approx((b["x_close"] + row["virt_sol"]) / b["y_close"])
    assert fixed.get("price_repaired") == 1


def test_top_share_excludes_agent():
    top = [["a", 50.0, 0], ["agent", 10.0, 0], ["b", 20.0, 0]]
    assert F.top_share(top, 100.0, k=5) == pytest.approx(0.8)
    assert F.top_share(top, 100.0, k=5, exclude="agent") == pytest.approx(70 / 90)


def test_b2_minute_arrays_dense_and_carried(ch_events):
    row = ch_events["b2_rows"][0]
    bars = F.bars_to_dicts(row["bars"])
    arr = F.b2_minute_arrays(bars, row["g_ts"], n_minutes=181)
    assert len(arr["close"]) == 181 and arr["minute_ts"][0] == (row["g_ts"] // 60) * 60
    first = (bars[0]["minute_ts"] - arr["minute_ts"][0]) // 60
    assert arr["close"][first] == bars[0]["close"]
    # after the last bar the price is carried forward and flows are zero
    last = (bars[-1]["minute_ts"] - arr["minute_ts"][0]) // 60
    if last + 1 < 181:
        assert arr["close"][last + 1] == bars[-1]["close"] and arr["n_buys"][last + 1] == 0
    assert sum(arr["n_buys"]) == sum(b["n_buys"] for b in bars if 0 <= (b["minute_ts"] - arr["minute_ts"][0]) // 60 < 181)

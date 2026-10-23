"""Tests for research/lab5/core.py and run.py: the fair-value math on known cases, the no-lookahead alignment of spot,
variance and running extremes, fees and settlement, contract parsing, lab 4's bar unchanged, the entry rule and a
tiny hand-made tape end to end (catalogue row -> worker -> cell summary)."""

import importlib.util
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import core as C
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

HERE = Path(__file__).resolve().parents[1]


def _ts(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp())


def _spot_frame(t0: int, prices: np.ndarray) -> pd.DataFrame:
    n = len(prices)
    return pd.DataFrame(
        {"ts": t0 + np.arange(n), "open": prices, "high": prices, "low": prices, "close": prices}
    )


# ----------------------------------------------------------------------------------------- fair value


def test_terminal_known_values():
    # s = 100, k = 110, V = 0.01: P(above) = Phi((ln(100/110) - 0.005) / 0.1)
    p = C.p_terminal(np.array([100.0]), 110.0, 110.0, "above", np.array([0.01]))[0]
    assert p == pytest.approx(norm.cdf((math.log(100 / 110) - 0.005) / 0.1), rel=1e-9)
    assert p == pytest.approx(0.1579, abs=5e-4)
    # at the money the zero-drift lognormal gives slightly under one half
    atm = C.p_terminal(np.array([100.0]), 100.0, 100.0, "above", np.array([0.04]))[0]
    assert atm == pytest.approx(norm.cdf(-0.1), rel=1e-9) and atm < 0.5
    # below = 1 - above; between = above(lo) - above(hi); deep in the money ~ 1
    below = C.p_terminal(np.array([100.0]), 110.0, 110.0, "below", np.array([0.01]))[0]
    assert below == pytest.approx(1 - p)
    lo, hi = 95.0, 105.0
    between = C.p_terminal(np.array([100.0]), lo, hi, "between", np.array([0.01]))[0]
    a_lo = C.p_terminal(np.array([100.0]), lo, lo, "above", np.array([0.01]))[0]
    a_hi = C.p_terminal(np.array([100.0]), hi, hi, "above", np.array([0.01]))[0]
    assert between == pytest.approx(a_lo - a_hi)
    assert C.p_terminal(np.array([200.0]), 100.0, 100.0, "above", np.array([1e-4]))[0] > 0.999999


def test_terminal_is_a_martingale_price():
    """Zero drift: E[S_T] = s under the model, so P(above k) integrates to the call-price identity at k -> 0."""
    rng = np.random.default_rng(0)
    V = 0.09
    x = 100.0 * np.exp(rng.normal(-V / 2, math.sqrt(V), 400_000))
    assert x.mean() == pytest.approx(100.0, rel=3e-3)
    p = C.p_terminal(np.array([100.0]), 105.0, 105.0, "above", np.array([V]))[0]
    assert p == pytest.approx((x > 105.0).mean(), abs=3e-3)


def test_touch_reflection_and_monte_carlo():
    s, b, V = 100.0, 103.0, 0.0009  # 3 % barrier, 3 % sd over the horizon
    p = C.p_touch(np.array([s]), b, True, np.array([V]), np.array([s]))[0]
    sd = math.sqrt(V)
    assert p == pytest.approx(2 * (1 - norm.cdf(math.log(b / s) / sd)))
    rng = np.random.default_rng(1)
    steps, paths = 2000, 20_000
    inc = rng.normal(0.0, sd / math.sqrt(steps), (paths, steps))
    mx = np.exp(np.maximum.accumulate(np.cumsum(inc, axis=1), axis=1)[:, -1]) * s
    assert p == pytest.approx((mx >= b).mean(), abs=0.02)  # discrete monitoring touches slightly less often
    # already touched in the period -> certain; dip mirrors reach
    assert C.p_touch(np.array([s]), b, True, np.array([V]), np.array([103.5]))[0] == 1.0
    pd_ = C.p_touch(np.array([s]), 97.0, False, np.array([V]), np.array([s]))[0]
    assert pd_ == pytest.approx(2 * norm.cdf(-math.log(100 / 97) / sd))


def test_twap_moments_monte_carlo():
    """Var of the average of a Brownian path over l seconds after a g-second gap = v (l^2 g + l^3/3) / L^2 (x s^2)."""
    s, v, L, T = 100.0, 1e-6, 60.0, 300.0
    rng = np.random.default_rng(2)
    for t, known in ((100.0, 0.0), (270.0, 30 * 100.0)):  # before the averaging window; inside it (30 s known)
        mean, var = C.twap_moments(np.array([t]), T, L, np.array([s]), np.array([known]), np.array([v]))
        a = max(t, T - L)
        g, l_rem = a - t, T - a
        n = 2000
        dt = 1.0
        w_gap = rng.normal(0, math.sqrt(v * g), n) if g > 0 else np.zeros(n)
        path = w_gap[:, None] + np.cumsum(rng.normal(0, math.sqrt(v * dt), (n, int(l_rem))), axis=1)
        f = known / L + s * (1 + path).sum(axis=1) * dt / L
        assert mean[0] == pytest.approx(f.mean(), rel=1e-3)
        assert var[0] == pytest.approx(f.var(), rel=0.12)
    # L = 0 is the spot case
    m0, v0 = C.twap_moments(np.array([100.0]), 300.0, 0.0, np.array([s]), np.array([0.0]), np.array([v]))
    assert m0[0] == s and v0[0] == pytest.approx(s * s * v * 200.0)


def test_window_probability_edges():
    assert C.p_window(np.array([101.0]), np.array([0.0]), 100.0)[0] == 1.0
    assert C.p_window(np.array([100.0]), np.array([0.0]), 100.0)[0] == 1.0  # >= : a tie is Up
    assert C.p_window(np.array([100.0]), np.array([0.0]), 100.0, strict=True)[0] == 0.0
    assert C.p_window(np.array([100.0]), np.array([4.0]), 100.0)[0] == pytest.approx(0.5)


# ----------------------------------------------------------------------------------------- no lookahead


def test_spot_alignment_never_reads_the_future():
    base = C.SPOT_BASE
    prices = np.full(3600, 100.0)
    jump = 1800  # the candle opening at base + 1800 trades at 200 (closes at base + 1801)
    prices[jump:] = 200.0
    sp = C.Spot.from_frame("X", _spot_frame(base, prices), base=base, end=base + 3600)
    assert sp.price_at(base + jump)[()] == 100.0  # the jump candle has not closed yet
    assert sp.price_at(base + jump + 1)[()] == 200.0
    # the 1-minute return that contains the jump ends at base + 1860; before that the variance cannot see it
    assert sp.var_per_s(base + 1859, 600)[()] == 0.0
    assert sp.var_per_s(base + 1860, 600)[()] > 0.0
    # running extreme over [p0, t) excludes candles opening at or after t
    ext = sp.running_extreme(base + 60, np.array([base + jump, base + jump + 1]), True)
    assert list(ext) == [100.0, 200.0]


def test_model_uses_lagged_spot_only():
    """A print at ts sees spot as of ts - LAG_S: a jump between the decision time and the print is invisible."""
    base = C.SPOT_BASE
    t_noon = base + 2 * 86400 + 16 * 3600
    n = t_noon + 120 - base
    prices = np.full(n, 100.0)
    rng = np.random.default_rng(3)
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0, 1e-4, n)))
    ts_print = t_noon - 3600
    prices[ts_print - base - 5 :] *= 1.5  # a 50 % jump 5 s before the print (after the decision time ts - 10)
    sp = C.Spot.from_frame("BTCUSDT", _spot_frame(base, prices), base=base, end=base + n)
    m = C.Market("x", {"kind": "terminal", "op": "above", "k_lo": 120.0, "k_hi": 120.0, "t_final": t_noon + 60.0, "event_outcome": 0, "symbol": "BTCUSDT"}, 0, t_noon + 600.0, t_noon, 0.07, "c", "train")
    q_lag = C.q_event(m, sp, np.array([ts_print - C.LAG_S]), 86400)[0]
    q_now = C.q_event(m, sp, np.array([ts_print]), 86400)[0]
    assert q_lag < 0.01 and q_now > 0.99  # only the unlagged read sees the jump
    tape = pd.DataFrame({"ts": [ts_print], "p0": [0.5], "buy0": [True], "size": [10.0]})
    cand = C.market_candidates(m, tape, sp, [86400])
    assert cand["q86400"].iat[0] == pytest.approx(q_lag)


def test_chainlink_window_scales_binance_by_the_open_basis():
    base = C.SPOT_BASE
    t0 = base + 3 * 86400
    n = t0 + 600 - base
    prices = np.full(n, 100.0)
    prices[t0 - base + 100 :] = 100.2  # Binance is up 0.2 % from 100 s into the window
    sp = C.Spot.from_frame("BTCUSDT", _spot_frame(base, prices), base=base, end=base + n)
    sp.cum_r2[:] = np.arange(len(sp.cum_r2)) * 1e-8  # 1e-8 per minute, so the variance is defined
    sp.cum_n[:] = np.arange(len(sp.cum_n))
    contract = {
        "kind": "window",
        "sub": "5m",
        "t0": float(t0),
        "t_final": float(t0 + 300),
        "ref_known": float(t0),
        "twap_s": 0.0,
        "ref_rule": "chainlink",
        "ref_value": 50_000.0,  # Chainlink's own scale: 500 x Binance
        "strict": False,
        "event_outcome": 0,
        "symbol": "BTCUSDT",
    }
    m = C.Market("w", contract, 0, t0 + 400.0, t0 + 300.0, 0.07, "c", "train")
    q = C.q_event(m, sp, np.array([t0 + 50, t0 + 200]), 3600)
    assert q[0] == pytest.approx(0.5, abs=0.01)  # flat so far: a coin flip
    assert q[1] > 0.9  # up 0.2 % with 100 s left at a tiny variance: Up is near certain
    assert np.isnan(C.q_event(m, sp, np.array([t0 - 5]), 3600)[0])  # before the open: undefined
    # basis noise widens a Chainlink window, never a Binance one (it settles on the data the model reads)
    assert C.q_event(m, sp, np.array([t0 + 200]), 3600, basis_sd=0.01)[0] < q[1]
    binance = {**contract, "ref_rule": "open_t0", "ref_known": float(t0 + 1)}
    mb = C.Market("b", binance, 0, t0 + 400.0, t0 + 300.0, 0.07, "c", "train")
    q0 = C.q_event(mb, sp, np.array([t0 + 200]), 3600)[0]
    assert C.q_event(mb, sp, np.array([t0 + 200]), 3600, basis_sd=0.01)[0] == q0 > 0.9


# ----------------------------------------------------------------------------------------- fees, settlement, bar


def test_fee_and_settlement():
    assert C.fee_rate("crypto_fees_v2", True) == 0.07 and C.fee_rate("crypto_fees_v2", False) == 0.0
    assert C.fee_rate("mystery", True) == C.UNKNOWN_RATE
    m = C.Market("x", {}, winner=0, closed_time=0.0, end_date=0.0, rate=0.07, cluster="c", split="train")
    s = C.settle(m, 0, 0.6)
    shares = 20 / 0.6
    fee = shares * 0.07 * 0.6 * 0.4
    assert s["won"] and s["fee_usd"] == pytest.approx(fee)
    assert s["pnl_usd"] == pytest.approx(shares - fee - 20) and s["net"] == pytest.approx((shares - fee - 20) / 20)
    lost = C.settle(m, 1, 0.6)
    assert not lost["won"] and lost["pnl_usd"] == pytest.approx(-fee - 20)
    assert C.settle(m, 0, 0.6, rate=C.US_RATE)["fee_usd"] == pytest.approx(shares * 0.0695 * 0.24)


def _lab4_core():
    import sys

    spec = importlib.util.spec_from_file_location("lab4_core", HERE.parent / "lab4" / "core.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lab4_core"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def test_qualifies_is_lab4s_bar():
    lab4 = _lab4_core()
    cases = [
        {"n": 150, "mean_net": 0.01, "ci95": [0.001, 0.02], "losses": 10, "worst_case_net": -0.1},
        {"n": 99, "mean_net": 0.01, "ci95": [0.001, 0.02], "losses": 10, "worst_case_net": 0.0},
        {"n": 150, "mean_net": 0.01, "ci95": [-0.001, 0.02], "losses": 10, "worst_case_net": 0.0},
        {"n": 150, "mean_net": 0.01, "ci95": [0.001, 0.02], "losses": 0, "worst_case_net": 0.005},
        {"n": 400, "mean_net": 0.02, "ci95": [0.01, 0.03], "losses": 3, "worst_case_net": 0.004},
        {"n": 400, "mean_net": 0.02, "ci95": [0.01, 0.03], "losses": 3, "worst_case_net": -0.001},
        {"n": 150, "mean_net": None, "ci95": [None, None], "losses": 0, "worst_case_net": None},
    ]
    for c in cases:
        assert C.qualifies(c) == lab4.qualifies(c)


def test_test_split_is_gated(monkeypatch):
    monkeypatch.delenv("LAB5_ALLOW_TEST", raising=False)
    with pytest.raises(PermissionError):
        C.check_split_allowed("test")
    C.check_split_allowed("val")


def test_ledger_upsert_and_cross_lab_count(tmp_path, monkeypatch):
    ledger = tmp_path / "trials.json"
    monkeypatch.setattr(C, "SIBLING_LEDGERS", ())
    e = {"lab": "lab5", "hyp": "S1", "cell": "a", "split": "train", "stage": "train"}
    assert C.record_run(e, ledger) == 1
    assert C.record_run({**e, "n": 5}, ledger) == 1  # same key: replaced, not added
    assert C.record_run({**e, "cell": "b"}, ledger) == 2


# ----------------------------------------------------------------------------------------- parsing


def _row(q, desc="... Binance ...", src="https://www.binance.com/en/trade/BTC_USDT", outcomes='["Yes", "No"]', end="2026-08-23T16:00:00", **kw):
    return {"question": q, "description": desc, "resolution_source": src, "outcomes": outcomes, "end_date": float(_ts(end)), **kw}


def test_parse_terminal_and_touch():
    c = C.parse_market(_row("Will the price of Bitcoin be above $74,000 on August 23?"))
    assert c["kind"] == "terminal" and c["op"] == "above" and c["k_lo"] == 74000.0 and c["symbol"] == "BTCUSDT"
    assert c["t_final"] == _ts("2026-08-23T16:01:00")  # the close of the 1-minute candle opening at noon ET
    c = C.parse_market(_row("Will the price of Ethereum be between $1,800 and $1,900 on August 12?", end="2026-08-12T16:00:00"))
    assert (c["op"], c["k_lo"], c["k_hi"], c["symbol"]) == ("between", 1800.0, 1900.0, "ETHUSDT")
    c = C.parse_market(_row("Will the price of Bitcoin be less than $68,000 on September 20?", end="2026-09-20T16:00:00"))
    assert c["op"] == "below"
    c = C.parse_market(_row("Will the price of Bitcoin be greater than $78,000 on August 26?", end="2026-08-26T16:00:00"))
    assert c["op"] == "above"
    c = C.parse_market(_row("Bitcoin above 81,400 on September 18, 11PM ET?", end="2026-09-19T03:00:00"))
    assert c["kind"] == "terminal" and c["t_final"] == _ts("2026-09-19T03:00:00") and c["k_lo"] == 81400.0
    c = C.parse_market(_row("Will Ethereum reach $2,050 on August 19?", end="2026-08-20T04:00:00"))
    assert c["kind"] == "touch" and c["op"] == "up" and (c["p0"], c["p1"]) == (_ts("2026-08-19T04:00:00"), _ts("2026-08-20T04:00:00"))
    c = C.parse_market(_row("Will Bitcoin dip to $52,000 July 27-August 2?", end="2026-08-03T04:00:00"))
    assert c["op"] == "down" and (c["p0"], c["p1"]) == (_ts("2026-07-27T04:00:00"), _ts("2026-08-03T04:00:00"))
    c = C.parse_market(_row("Will XRP dip to $1.40 in August?", end="2026-09-01T04:00:00"))
    assert c["barrier"] == 1.40 and c["symbol"] == "XRPUSDT" and (c["p0"], c["p1"]) == (_ts("2026-08-01T04:00:00"), _ts("2026-09-01T04:00:00"))
    assert C.parse_market(_row("Will Nansen launch a token by September 30, 2026?"))["kind"] is None
    assert C.parse_market(_row("Will the price of Bitcoin be above $74,000 on August 23?", desc="Chainlink", src="x"))["kind"] is None


def test_parse_windows():
    chain = "This market will resolve ... Chainlink ... TWAP"
    base = {"outcomes": '["Up", "Down"]'}
    c = C.parse_market(
        {**base, "question": "Bitcoin Up or Down - August 19, 3:10PM-3:15PM ET", "description": chain, "resolution_source": "https://data.chain.link/streams/btc-usd-twap-60s-streams", "end_date": float(_ts("2026-08-19T19:15:00")), "event_start": float(_ts("2026-08-19T19:10:00")), "twap_s": None, "price_to_beat": 80000.0}
    )
    assert c["kind"] == "window" and c["sub"] == "5m" and c["twap_s"] == 60.0 and c["ref_value"] == 80000.0 and c["ref_known"] == _ts("2026-08-19T19:10:00")
    c = C.parse_market(
        {**base, "question": "Bitcoin Up or Down - July 24, 8:00PM-8:15PM ET", "description": "Chainlink BTC/USD data stream", "resolution_source": "https://data.chain.link/streams/btc-usd", "end_date": float(_ts("2026-07-25T00:15:00")), "event_start": float(_ts("2026-07-25T00:00:00")), "twap_s": None, "price_to_beat": 65000.0}
    )
    assert c["sub"] == "15m" and c["twap_s"] == 0.0
    assert C.parse_market({**base, "question": "Bitcoin Up or Down - July 24, 8:00PM-8:15PM ET", "description": "Chainlink", "resolution_source": "https://data.chain.link/streams/btc-usd", "end_date": float(_ts("2026-07-25T00:15:00")), "event_start": float(_ts("2026-07-25T00:00:00")), "twap_s": None, "price_to_beat": None})["kind"] is None
    c = C.parse_market(
        {**base, "question": "Bitcoin Up or Down - August 18, 12AM ET", "description": "Binance BTC/USDT 1 hour candle", "resolution_source": "https://www.binance.com/en/trade/BTC_USDT", "end_date": float(_ts("2026-08-18T05:00:00")), "event_start": float(_ts("2026-08-18T04:00:00"))}
    )
    assert (c["sub"], c["ref_rule"], c["ref_known"], c["t_final"]) == ("1h", "open_t0", _ts("2026-08-18T04:00:01"), _ts("2026-08-18T05:00:00"))
    c = C.parse_market(
        {**base, "question": "Bitcoin Up or Down on August 19?", "description": "Binance 1 minute candle", "resolution_source": "https://www.binance.com/en/trade/BTC_USDT", "end_date": float(_ts("2026-08-19T16:00:00")), "event_start": float(_ts("2026-08-18T16:00:00"))}
    )
    assert (c["sub"], c["strict"], c["ref_known"], c["t_final"]) == ("1d", True, _ts("2026-08-18T16:01:00"), _ts("2026-08-19T16:01:00"))


# ----------------------------------------------------------------------------------------- entry rule


def test_first_entry_needs_edge_beyond_margin_after_costs():
    cand = pd.DataFrame(
        {
            "ts": [1, 2, 3],
            "side": [0, 1, 0],
            "p_print": [0.50, 0.50, 0.50],
            "p_x": [0.51, 0.51, 0.51],
            "fee_ps": [0.0175, 0.0175, 0.0175],
            "tau": [9e3, 9e3, 9e3],
            "q": [0.55, 0.60, 0.70],
        }
    )
    mask = np.array([True, True, True])
    # edges: 0.0225, 0.0725, 0.1725
    assert C.first_entries(cand, mask, "q", 0.02) == 0
    assert C.first_entries(cand, mask, "q", 0.05) == 1
    assert C.first_entries(cand, mask, "q", 0.10) == 2
    assert C.first_entries(cand, np.array([False, False, True]), "q", 0.02) == 2
    assert C.first_entries(cand, mask, "q", 0.20) is None


def test_latency_exec_takes_the_next_print_for_the_same_side():
    cand = pd.DataFrame({"ts": [100, 105, 112, 115, 900], "side": [0, 0, 1, 0, 0], "p_x": [0.5, 0.5, 0.5, 0.6, 0.7]})
    assert C.latency_exec(cand, 0) == 3  # 112 is the other side; 115 is >= 110
    assert C.latency_exec(cand, 3) is None  # 900 is beyond 600 s


# ----------------------------------------------------------------------------------------- end to end


def test_tiny_tape_end_to_end(tmp_path, monkeypatch):
    """A hand-made 'above $100 at noon' market: spot sits at 110 with a small variance, the Yes side prints at 0.50
    nine hours before noon (inside 'near'), at 0.60 two days before (inside 'far'), and the Yes side wins. The
    specialist must buy the first qualifying 'near' print at 0.51 and the 'far' one at 0.61, settle them, and the
    summaries must carry the numbers."""
    import data as D
    import run as R

    base = C.SPOT_BASE
    noon = _ts("2026-07-10T16:00:00")
    n = noon + 3600 - base
    rng = np.random.default_rng(4)
    prices = 110.0 * np.exp(np.cumsum(rng.normal(0, 2e-5, n)))
    spot = C.Spot.from_frame("BTCUSDT", _spot_frame(base, prices), base=base, end=base + n)
    lab4 = tmp_path / "lab4"
    (lab4 / "trades").mkdir(parents=True)
    t_far, t_near = noon - 2 * 86400, noon - 9 * 3600
    trades = pd.DataFrame(
        {
            # 8 days out (outside both windows), 'far', a SELL on Yes (bid side: not buyable for Yes, buyable for No
            # at 0.45 where the model says No is ~0: never bought), 'near', then 59 prints at 0.97
            "ts": [noon - 8 * 86400, t_far, t_near - 30, t_near] + [t_near + 60 * k for k in range(1, 60)],
            "price": [0.4, 0.6, 0.55, 0.5] + [0.97] * 59,
            "size": [10.0] * 63,
            "side": ["BUY", "BUY", "SELL", "BUY"] + ["BUY"] * 59,
            "outcome_index": [0] * 63,
            "asset": ["a"] * 63,
            "tx": [f"t{i}" for i in range(63)],
        }
    )
    trades.to_parquet(lab4 / "trades" / "m1.parquet", index=False)
    monkeypatch.setattr(D, "LAB4", lab4)
    contract = C.parse_market(_row("Will the price of Bitcoin be above $100 on July 10?", end="2026-07-10T16:00:00"))
    row = {
        "id": "m1",
        "kind": "terminal",
        "contract": json.dumps(contract),
        "winner": 0,
        "closed_time": float(noon + 300),
        "end_date": float(noon),
        "rate": 0.07,
        "split": "train",
    }
    res = R.run_markets([row], {"BTCUSDT": spot}, lag_s=10, bsd=0.0, procs=1)
    t = pd.DataFrame(res[0]["trades"])
    near = t[t["cell"] == "m0.02|near|vol1d"].iloc[0]
    assert near["t_entry"] == t_near and near["p_x"] == pytest.approx(0.51) and near["won"]
    shares = 20 / 0.51
    assert near["pnl_usd"] == pytest.approx(shares - shares * 0.07 * 0.51 * 0.49 - 20)
    assert near["lat_net"] == pytest.approx(C.settle(C.Market("m1", contract, 0, 0, 0, 0.07, "c", "train"), 0, 0.98)["net"])
    far = t[t["cell"] == "m0.02|far|vol1d"].iloc[0]
    assert far["t_entry"] == t_far and far["p_x"] == pytest.approx(0.61)  # the 8-day print is outside 'far'
    assert set(t["side"]) == {0}  # the bid-side print never made the specialist buy No
    s = C.summarize(t[t["cell"] == "m0.02|near|vol1d"], "train", B=200)
    assert s["n"] == 1 and s["losses"] == 0 and s["win_rate"] == 1.0 and s["mean_net"] == pytest.approx(near["net"])
    assert not C.qualifies(s)  # one bet, no loss: never qualifies

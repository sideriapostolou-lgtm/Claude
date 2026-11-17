"""Harness invariants (offline, synthetic data only)."""

import json
import random

import numpy as np
import pytest

import harness as H
from costs import CostModel, SolUsd
from harness import Buy, Coin, Exits, Sell, SimConfig, Strategy

T0 = 1_790_000_000 // 60 * 60
SOL = SolUsd()  # constant fallback price, no files


def walk(n=400, seed=1, p0=5e-5, vol=0.04):
    rng = random.Random(seed)
    rows, p = [], p0
    for i in range(n):
        o = p
        c = max(o * (1 + rng.gauss(0, vol)), 1e-9)
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        low = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        rows.append([T0 + 60 * i, o, h, low, c, rng.uniform(0, 5000)])
        p = c
    return rows


def bars(*ohlc, start=T0):
    return [[start + 60 * i, o, h, low, c, 100.0] for i, (o, h, low, c) in enumerate(ohlc)]


class Busy(Strategy):
    """Uses lots of history; trades often; sets/moves exits; sells on signals."""

    name = "busy"

    def on_candle(self, i, view, position):
        if i < 10:
            return None
        hi = float(view.h[-30:].max())
        mv = float(view.v[-10:].mean())
        last = view.bar()
        if position is None:
            if last.c < hi * 0.9 and last.v > mv * 0.5:
                return Buy(exits=Exits(stop_pct=0.1, take_profit_pct=0.15, tp_fraction=0.5, trail_pct=0.08,
                                       max_hold_s=1800))
            return None
        if position.unrealized_pct > 0.05:
            return H.SetExits(Exits(stop_price=position.entry_price, trail_pct=0.05))
        if last.c < view.c[-5]:
            return Sell(0.5)
        return None


def _fills(res, upto_ts):
    return [(f.ts, f.side, f.mid, f.reason) for t in res.trades for f in t.fills
            if f.ts <= upto_ts and f.reason != "end_of_data"]


# --------------------------------------------------------------------------- lookahead


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_mutating_future_never_changes_past(seed):
    rows = walk(400, seed)
    base = H.run_per_coin(Busy, [Coin.from_rows(rows)], sol=SOL, keep_decisions=True)
    assert base.trades, "the test strategy must trade"
    rng = random.Random(seed + 100)
    for cut in (50, 137, 260, 398):
        mutated = [list(r) for r in rows[:cut + 1]]
        for r in rows[cut + 1:]:  # garbage future + extra appended bars
            p = rng.uniform(1e-7, 1e-3)
            mutated.append([r[0], p, p * 3, p / 3, p * rng.uniform(0.3, 3), rng.uniform(0, 1e6)])
        for k in range(50):
            mutated.append([rows[-1][0] + 60 * (k + 1), 1e-6, 1e-6, 1e-6, 1e-6, 0.0])
        res = H.run_per_coin(Busy, [Coin.from_rows(mutated)], sol=SOL, keep_decisions=True)
        d0 = [d for d in base.decisions["TEST"] if d[0] <= cut]
        d1 = [d for d in res.decisions["TEST"] if d[0] <= cut]
        assert d0 == d1
        assert _fills(base, rows[cut][0]) == _fills(res, rows[cut][0])


def test_audit_lookahead_clean_and_catches_cheater():
    coins = [Coin.from_rows(walk(300, s), mint=f"C{s}") for s in range(3)]
    assert H.audit_lookahead(Busy, coins, cuts_per_coin=4, sol=SOL) == []

    class Cheater(Strategy):
        def on_candle(self, i, view, position):
            fut = view._coin.c  # reaching around the read-only view
            if position is None and i + 3 < len(fut) and fut[i + 3] > view.c[-1] * 1.05:
                return Buy(exits=Exits(max_hold_s=180))
            return None

    assert H.audit_lookahead(Cheater, coins, cuts_per_coin=6, sol=SOL)


def test_view_is_read_only_and_bounded():
    coin = Coin.from_rows(walk(50))
    v = H.View(coin, 9, {}, SOL)
    assert len(v.c) == 10 and len(v.ts) == 10 and v.now == coin.ts[9] + 60
    with pytest.raises(IndexError):
        v.bar(10)
    with pytest.raises(IndexError):
        v.bar(-11)
    assert v.bar(-1).ts == coin.ts[9]
    with pytest.raises(ValueError):
        v.c[0] = 1.0
    with pytest.raises(ValueError):
        coin.c[0] = 1.0


def test_graduation_hidden_and_entries_refused_before_it():
    rows = walk(60)
    grad = rows[20][0] + 30  # graduates inside bar 20
    seen = {}

    class Eager(Strategy):
        def on_candle(self, i, view, position):
            seen[i] = (view.graduated, view.graduated_ts)
            return Buy(exits=Exits(max_hold_s=60)) if position is None else None

    res = H.run_per_coin(Eager, [Coin.from_rows(rows, graduated_ts=grad)], SimConfig(cooldown_s=0), sol=SOL)
    assert seen[19] == (False, None)
    assert seen[20] == (True, grad)  # close of bar 20 is after graduation
    assert min(t.entry_ts for t in res.trades) == rows[21][0]  # first fill: open of bar 21


def test_entry_fills_at_next_open_with_costs():
    rows = bars((1.0, 1.0, 1.0, 1.0), (2.0, 2.0, 2.0, 2.0), (3.0, 3.0, 3.0, 3.0), (3.0, 3.0, 3.0, 3.0))
    rows = [[r[0], *(x * 1e-5 for x in r[1:5]), r[5]] for r in rows]

    class Once(Strategy):
        def on_candle(self, i, view, position):
            return Buy() if i == 0 else None

    res = H.run_per_coin(Once, [Coin.from_rows(rows)], SimConfig(fixed_usd=20), sol=SOL)
    t = res.trades[0]
    assert t.entry_ts == rows[1][0] and t.entry_mid == pytest.approx(2e-5)
    assert t.tokens < 20 / 2e-5  # fees + impact
    assert t.exit_reason == "end_of_data"


# --------------------------------------------------------------------------- intrabar


def _one_trade(rows, exits, wick="touch", cfg=None):
    class Once(Strategy):
        def on_candle(self, i, view, position):
            return Buy(exits=exits) if i == 0 else None

    cfg = cfg or SimConfig(cost=CostModel(ultra_bps=0, mev_bps=0, fee_mult=0, impact_mult=1e-9, priority_sol=0,
                                          base_fee_lamports=0), wick_fill=wick)
    res = H.run_per_coin(Once, [Coin.from_rows(rows)], cfg, sol=SOL)
    return res.trades[0]


def test_stop_beats_take_profit_in_same_bar():
    rows = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 13, 8, 12), (12, 12, 12, 12))
    t = _one_trade(rows, Exits(stop_pct=0.1, take_profit_pct=0.2))
    assert t.exit_reason == "stop" and t.fills[-1].mid == pytest.approx(9.0)


def test_gap_through_stop_fills_at_open():
    rows = bars((10, 10, 10, 10), (10, 10, 10, 10), (7, 7.5, 6, 7), (7, 7, 7, 7))
    t = _one_trade(rows, Exits(stop_pct=0.1))
    assert t.exit_reason == "stop_gap" and t.fills[-1].mid == pytest.approx(7.0)


def test_wick_fill_modes():
    rows = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 10, 5, 9.8), (10, 10, 10, 10))
    assert _one_trade(rows, Exits(stop_pct=0.1), "touch").fills[-1].mid == pytest.approx(9.0)
    assert _one_trade(rows, Exits(stop_pct=0.1), "half").fills[-1].mid == pytest.approx(7.0)
    assert _one_trade(rows, Exits(stop_pct=0.1), "worst").fills[-1].mid == pytest.approx(5.0)
    up = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 20, 10, 10.5), (10, 10, 10, 10))
    assert _one_trade(up, Exits(take_profit_pct=0.5), "touch").fills[-1].mid == pytest.approx(15.0)
    assert _one_trade(up, Exits(take_profit_pct=0.5), "half").fills[-1].mid == pytest.approx(12.75)
    sustained = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 20, 10, 16), (10, 10, 10, 10))
    assert _one_trade(sustained, Exits(take_profit_pct=0.5), "half").fills[-1].mid == pytest.approx(15.0)


def test_trailing_uses_previous_peaks_only():
    # bar 2 makes a new high 20 and dips to 17.5: trail 10 % from the NEW peak (18) would fire,
    # from the previous peak (10 -> 9) it must not.
    rows = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 20, 9.5, 19), (19, 19.5, 18.5, 19), (19, 19, 17, 17))
    t = _one_trade(rows, Exits(trail_pct=0.1))
    assert t.fills[-1].ts == rows[4][0] and t.exit_reason == "trail"
    assert t.fills[-1].mid == pytest.approx(18.0)  # 20 * 0.9 (touch)


def test_partial_tp_then_trail_same_bar_uses_previous_peak():
    rows = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 13, 8.9, 12.5), (12, 12, 12, 12))
    t = _one_trade(rows, Exits(take_profit_pct=0.2, tp_fraction=0.5, trail_pct=0.1))
    reasons = [f.reason for f in t.fills]
    assert reasons == ["entry", "take_profit_partial", "trail"]
    assert t.fills[2].mid == pytest.approx(9.0)  # previous peak 10 * 0.9, not 13 * 0.9


def test_time_stop_at_open():
    rows = bars(*[(10, 10, 10, 10)] * 8)
    t = _one_trade(rows, Exits(max_hold_s=180))
    assert t.exit_reason == "time_stop" and t.fills[-1].ts == rows[1][0] + 180


def test_fill_bar_can_stop_out():
    rows = bars((10, 10, 10, 10), (10, 10, 8, 9), (9, 9, 9, 9))
    t = _one_trade(rows, Exits(stop_pct=0.1))
    assert t.exit_reason == "stop" and t.fills[-1].ts == rows[1][0]


# --------------------------------------------------------------------------- portfolio


class AlwaysBuy(Strategy):
    def on_candle(self, i, view, position):
        return Buy(exits=Exits(max_hold_s=600)) if position is None else None


def test_portfolio_max_concurrent_and_sizing():
    coins = [Coin.from_rows(bars(*[(1e-5, 1e-5, 1e-5, 1e-5)] * 30), mint=f"M{k}") for k in range(6)]
    res = H.run_portfolio(AlwaysBuy, coins, SimConfig(cooldown_s=1e9), sol=SOL)
    first = [t for t in res.trades if t.entry_ts == coins[0].ts[1]]
    assert len(first) == 3  # max 3 concurrent
    assert all(t.size_usd == pytest.approx(20.0) for t in first)  # 20 % of $100
    assert res.rejected.get("max_concurrent", 0) > 0
    assert len({t.mint for t in res.trades}) == len(res.trades)  # cooldown: one trade per coin here


def test_portfolio_size_clamps():
    assert H.size_position_usd(100, 0.2, 5, 25) == pytest.approx(20)
    assert H.size_position_usd(1000, 0.2, 5, 25) == pytest.approx(25)
    assert H.size_position_usd(20, 0.2, 5, 25) == 0.0  # $4 < $5 minimum -> skip
    coins = [Coin.from_rows(bars(*[(1e-5, 1e-5, 1e-5, 1e-5)] * 30), mint="BIG")]
    res = H.run_portfolio(AlwaysBuy, coins, SimConfig(start_usd=1000, cooldown_s=1e9), sol=SOL)
    assert res.trades[0].size_usd == pytest.approx(25)
    res = H.run_portfolio(AlwaysBuy, coins, SimConfig(start_usd=20, cooldown_s=1e9), sol=SOL)
    assert res.trades == [] and res.rejected.get("cash")


def test_portfolio_cooldown():
    coin = Coin.from_rows(bars(*[(1e-5, 1e-5, 1e-5, 1e-5)] * 120), mint="CD")

    class Quick(Strategy):
        def on_candle(self, i, view, position):
            return Buy(exits=Exits(max_hold_s=120)) if position is None else None

    res = H.run_portfolio(Quick, [coin], SimConfig(cooldown_s=1800), sol=SOL)
    entries = [t.entry_ts for t in res.trades]
    exits = [t.exit_ts for t in res.trades]
    assert len(entries) >= 2
    for prev_exit, nxt in zip(exits, entries[1:]):
        assert nxt - prev_exit >= 1800


def test_portfolio_priority_and_equity_accounting():
    coins = [Coin.from_rows(bars(*[(1e-5, 1e-5, 1e-5, 1e-5)] * 20), mint=f"P{k}") for k in range(5)]

    class Pri(Strategy):
        def on_coin_start(self, meta):
            self.p = int(meta["mint"][1:])

        def on_candle(self, i, view, position):
            return Buy(priority=self.p, exits=Exits(max_hold_s=300)) if position is None and i == 0 else None

    res = H.run_portfolio(Pri, coins, SimConfig(), sol=SOL)
    assert sorted(t.mint for t in res.trades) == ["P2", "P3", "P4"]
    # flat prices: equity only loses costs; final equity == start + sum(pnl)
    m = res.metrics(bootstrap=0)
    assert m["final_equity_usd"] == pytest.approx(100 + sum(t.pnl_usd for t in res.trades), abs=1e-6)
    assert m["final_equity_usd"] < 100


# --------------------------------------------------------------------------- split guard


def test_split_guard(tmp_path, monkeypatch):
    p = tmp_path / "splits.json"
    p.write_text(json.dumps({"train": ["A"], "validation": ["B"], "test": ["C"]}))
    monkeypatch.delenv("LAB_ALLOW_TEST", raising=False)
    assert H.load_split("train", p) == ["A"]
    with pytest.raises(H.TestSplitLocked):
        H.load_split("test", p)
    coin = Coin.from_rows(walk(20), mint="C")
    with pytest.raises(H.TestSplitLocked):
        H.guard_coins([coin], p)
    H.guard_coins([Coin.from_rows(walk(20), mint="A")], p)
    monkeypatch.setenv("LAB_ALLOW_TEST", "1")
    assert H.load_split("test", p) == ["C"]
    H.guard_coins([coin], p)


def test_runners_refuse_test_coins(monkeypatch, tmp_path):
    p = tmp_path / "splits.json"
    p.write_text(json.dumps({"train": [], "validation": [], "test": ["LOCKED"]}))
    monkeypatch.setattr(H, "SPLITS", p)
    monkeypatch.setattr(H, "_test_mints", lambda path=p: {"LOCKED"})
    monkeypatch.delenv("LAB_ALLOW_TEST", raising=False)
    coin = Coin.from_rows(walk(20), mint="LOCKED")
    with pytest.raises(H.TestSplitLocked):
        H.run_per_coin(AlwaysBuy, [coin], sol=SOL)
    with pytest.raises(H.TestSplitLocked):
        H.run_portfolio(AlwaysBuy, [coin], sol=SOL)


def test_metrics_bootstrap_and_concentration():
    rows = walk(300, 5)
    coins = [Coin.from_rows(walk(300, s), mint=f"Z{s}") for s in range(8)]
    res = H.run_per_coin(Busy, coins, sol=SOL)
    m = res.metrics(bootstrap=500)
    assert m["trades"] == len(res.trades) > 0
    lo, hi = m["exp_ci95_pct"]
    assert lo <= m["avg_ret_pct"] <= hi
    assert set(m["by_hour_utc"]) <= set(range(24))
    assert np.isfinite(m["costs_usd"]) and rows


def test_trail_after_tp_only_arms_after_partial():
    # without a partial the 10 % trail must stay off even though the low is 20 % under the peak
    rows = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 11, 8.5, 9), (9, 9, 9, 9))
    t = _one_trade(rows, Exits(take_profit_pct=0.5, tp_fraction=0.5, trail_pct=0.1, trail_after_tp=True))
    assert t.exit_reason == "end_of_data"
    rows = bars((10, 10, 10, 10), (10, 10, 10, 10), (10, 16, 8.5, 15), (15, 15, 15, 15))
    t = _one_trade(rows, Exits(take_profit_pct=0.5, tp_fraction=0.5, trail_pct=0.1, trail_after_tp=True))
    assert [f.reason for f in t.fills] == ["entry", "take_profit_partial", "trail"]

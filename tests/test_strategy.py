"""strategy.py: pure dip-rebound entry, exits, levels - and proof of NO lookahead."""

from __future__ import annotations

import copy
import random

import pytest

from nightcrawler.models import Candle, MarketSnapshot, Position, RadarSignal, StrategyParams
from nightcrawler.strategy import (
    ExitLevels,
    closed_candles,
    entry_signal,
    exit_levels,
    exit_signal,
    rolling_high,
)

T0 = 1_791_151_200  # 2026-10-04T22:00:00Z, a minute boundary
P = StrategyParams()


def candle(i: int, o: float, c: float, *, h: float | None = None, low: float | None = None, v: float = 100.0,
           t0: int = T0) -> Candle:
    return Candle(t0 + 60 * i, o, h if h is not None else max(o, c) * 1.001,
                  low if low is not None else min(o, c) * 0.999, c, v)


def path(closes: list[float], volumes: list[float] | None = None, t0: int = T0) -> list[Candle]:
    """1m candles whose opens chain from the previous close."""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(candle(i, prev, c, v=(volumes[i] if volumes else 100.0), t0=t0))
        prev = c
    return out


def close_time(candles: list[Candle]) -> float:
    """``now`` right when the last candle closes."""
    return candles[-1].ts + 60


# pump to 1.0, dump to 0.30 (70 % dip), then two green breakout candles to 0.36
SETUP = [0.4, 0.7, 1.0, 0.8, 0.6, 0.45, 0.35, 0.30, 0.31, 0.33, 0.36]


def setup_candles() -> list[Candle]:
    return path(SETUP)


# --------------------------------------------------------------------------- helpers


def test_closed_candles_uses_close_time_boundary() -> None:
    cs = path([1, 2, 3])
    assert closed_candles(cs, cs[2].ts + 60) == cs  # last one closes exactly now
    assert closed_candles(cs, cs[2].ts + 59) == cs[:2]  # still open
    assert closed_candles(cs, cs[0].ts) == []


def test_rolling_high_window_ties_and_index() -> None:
    cs = [candle(0, 1, 1, h=5), candle(1, 1, 1, h=3), candle(2, 1, 1, h=5), candle(3, 1, 1, h=2)]
    now = cs[-1].ts + 60
    assert rolling_high(cs, now, 1.0) == (5, 0)  # first occurrence wins
    assert rolling_high(cs, now, (now - cs[1].ts) / 3600) == (5, 2)  # candle 0 is outside the lookback
    assert rolling_high(cs, now + 10 * 3600, 1.0) is None


# --------------------------------------------------------------------------- entry


def test_entry_signal_fires_on_confirmed_dip_rebound() -> None:
    cs = setup_candles()
    sig = entry_signal(cs, None, P, close_time(cs))
    assert sig.kind == "enter", sig.reason
    assert sig.reason.startswith("dip-rebound")
    m = sig.metrics
    assert m["high"] == pytest.approx(1.0 * 1.001)
    assert m["dip"] == pytest.approx(1 - (0.30 * 0.999) / (1.0 * 1.001))
    assert m["green_run"] == 3 and m["last_close"] == 0.36 and m["candles_used"] == len(cs)
    assert set(m) >= {"high", "high_ts", "low", "low_ts", "dip", "last_close", "last_ts", "green_run", "ratio_m5"}
    assert 0 < sig.confidence <= 1


def test_entry_needs_enough_closed_candles() -> None:
    cs = path([1.0, 0.3, 0.32])
    sig = entry_signal(cs, None, P, close_time(cs))
    assert sig.kind == "none" and sig.reason.startswith("insufficient data")


def test_entry_rejects_shallow_dip() -> None:
    cs = path([1.0, 0.8, 0.6, 0.62, 0.65])  # 40 % dip
    sig = entry_signal(cs, None, P, close_time(cs))
    assert sig.kind == "none" and sig.reason.startswith("dip ") and "required 55.0%" in sig.reason


def test_entry_rejects_chasing_a_full_rebound() -> None:
    cs = path([1.0, 0.4, 0.3, 0.5, 0.8])  # dip 70 % but back to 0.8 (> 1.0 * (1 - 0.275))
    sig = entry_signal(cs, None, P, close_time(cs))
    assert sig.kind == "none" and sig.reason.startswith("chasing")


def test_entry_requires_green_confirmation() -> None:
    cs = path(SETUP[:-1] + [0.32])  # last candle red
    sig = entry_signal(cs, None, P, close_time(cs))
    assert sig.kind == "none" and sig.reason.startswith("buyers not back")


def test_entry_requires_breakout_or_rising_volume() -> None:
    base = path(SETUP[:-2])
    last_two = [candle(len(base), 0.31, 0.33, h=0.40, v=500), candle(len(base) + 1, 0.33, 0.34, h=0.35, v=400)]
    cs = base + last_two  # green, but close 0.34 < prior high 0.40 and volume falling
    sig = entry_signal(cs, None, P, close_time(cs))
    assert sig.kind == "none" and "no close above prior high" in sig.reason
    cs[-1] = candle(len(base) + 1, 0.33, 0.34, h=0.35, v=600)  # volume now rising
    assert entry_signal(cs, None, P, close_time(cs)).kind == "enter"


def test_entry_snapshot_ratio_gate() -> None:
    cs = setup_candles()
    now = close_time(cs)

    def snap(buys: int, sells: int) -> MarketSnapshot:
        return MarketSnapshot(mint="m", ts=now, price_usd=0.36, mcap_usd=None, liquidity_usd=None,
                              buys_m5=buys, sells_m5=sells)

    weak = entry_signal(cs, snap(10, 10), P, now)
    assert weak.kind == "none" and weak.reason == "buy/sell ratio 1.00 < 1.20"
    quiet = entry_signal(cs, snap(0, 0), P, now)
    assert quiet.kind == "none" and quiet.reason == "buy/sell ratio n/a < 1.20"
    strong = entry_signal(cs, snap(30, 10), P, now)
    assert strong.kind == "enter" and strong.metrics["ratio_m5"] == 3.0
    assert strong.confidence > entry_signal(cs, None, P, now).confidence


def test_entry_ignores_highs_older_than_lookback() -> None:
    old_high = [candle(0, 1.0, 1.0, h=10.0)]  # 10x higher, 7 h before the setup
    cs = old_high + path(SETUP, t0=T0 + 7 * 3600)
    sig = entry_signal(cs, None, P, close_time(cs))
    assert sig.kind == "enter" and sig.metrics["high"] == pytest.approx(1.001)


def test_entry_ignores_the_open_candle() -> None:
    cs = setup_candles()
    now = close_time(cs) + 30  # 30 s into the next (still open) candle
    crashing_open_candle = candle(len(cs), 0.36, 0.01, low=0.001, v=1e9)
    assert entry_signal(cs + [crashing_open_candle], None, P, now) == entry_signal(cs, None, P, now)


def test_entry_is_pure_and_does_not_mutate_inputs() -> None:
    cs = setup_candles()
    before = copy.deepcopy(cs)
    first = entry_signal(cs, None, P, close_time(cs))
    assert entry_signal(cs, None, P, close_time(cs)) == first
    assert cs == before


# --------------------------------------------------------------------------- NO LOOKAHEAD


def random_walk(n: int, seed: int) -> list[Candle]:
    """Seeded pump-dump-rebound-ish random walk with fat moves so entries actually fire."""
    rng = random.Random(seed)
    price, out = 1.0, []
    for i in range(n):
        o = price
        price = max(1e-6, price * (1 + rng.gauss(0, 0.08)))
        hi = max(o, price) * (1 + abs(rng.gauss(0, 0.03)))
        lo = min(o, price) * (1 - abs(rng.gauss(0, 0.03)))
        out.append(Candle(T0 + 60 * i, o, hi, lo, price, rng.uniform(10, 1000)))
    return out


def garbage_future(after_ts: int, n: int, seed: int) -> list[Candle]:
    """Arbitrary candles starting at ``after_ts`` (open or not yet started at decision time)."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        o, c = rng.uniform(1e-6, 100), rng.uniform(1e-6, 100)
        out.append(Candle(after_ts + 60 * i, o, max(o, c) * 3, min(o, c) / 3, c, rng.uniform(0, 1e7)))
    return out


@pytest.mark.parametrize("seed", range(6))
def test_entry_decisions_never_change_when_future_candles_are_appended(seed: int) -> None:
    series = random_walk(400, seed)
    entries = 0
    for k in range(5, len(series)):
        now = series[k - 1].ts + 60  # candle k-1 just closed; candle k (if any) is open
        past = series[:k]
        expected = entry_signal(past, None, P, now)
        entries += expected.kind == "enter"
        for future in (series[k:], garbage_future(series[k - 1].ts + 60, 50, seed * 1000 + k)):
            assert entry_signal(past + future, None, P, now) == expected, f"lookahead at k={k}"
        # mid-candle decision time: the open candle k must also be invisible
        mid = now + 45
        assert entry_signal(series[:k + 1], None, P, mid) == entry_signal(past, None, P, mid)
    assert entries > 0  # the property was exercised on real 'enter' decisions too


@pytest.mark.parametrize("seed", range(4))
def test_exit_decisions_never_change_when_future_candles_are_appended(seed: int) -> None:
    series = random_walk(300, seed)
    pos = Position(id="p", mint="m", symbol="X", pool=None, opened_at=float(series[20].ts), token_decimals=6,
                   entry_price_usd=series[20].o, peak_price_usd=series[20].o)
    for k in range(21, len(series)):
        now = series[k - 1].ts + 60
        price_now = series[k].o
        expected = exit_signal(pos, series[:k], price_now, P, now)
        got = exit_signal(pos, series[:k] + garbage_future(series[k].ts, 30, k), price_now, P, now)
        assert got == expected, f"lookahead at k={k}"


# --------------------------------------------------------------------------- exits


def position(entry: float = 1.0, *, peak: float = 0.0, partial: bool = False, opened_at: float = T0) -> Position:
    return Position(id="pos1", mint="m", symbol="X", pool=None, opened_at=opened_at, token_decimals=6,
                    entry_price_usd=entry, peak_price_usd=peak or entry, partial_taken=partial)


def radar(flagged: bool, reasons: list[str] | None = None, error: str | None = None) -> RadarSignal:
    return RadarSignal(mint="m", window_min=15, flagged=flagged, reasons=reasons or [], error=error)


def test_exit_levels_before_and_after_partial() -> None:
    lv = exit_levels(position(2.0), P)
    assert isinstance(lv, ExitLevels)
    assert lv.stop == pytest.approx(1.64) and lv.take_profit == pytest.approx(2.8)
    assert lv.trail is None and lv.time_stop_ts == T0 + 120 * 60
    after = exit_levels(position(2.0, peak=3.0, partial=True), P)
    assert after.take_profit is None and after.trail == pytest.approx(3.0 * 0.85)
    assert exit_levels(position(2.0, peak=1.0, partial=True), P).trail == pytest.approx(2.0 * 0.85)


def test_exit_order_radar_first() -> None:
    sig = exit_signal(position(), [], 0.5, P, T0 + 60, radar(True, ["creator sold $900"]))
    assert sig.kind == "exit" and sig.reason == "radar: creator sold $900" and sig.fraction == 1.0
    assert exit_signal(position(), [], 1.0, P, T0 + 60, radar(True)).reason == "radar: flagged"


def test_radar_error_alone_is_not_an_exit_trigger() -> None:
    sig = exit_signal(position(), [], 1.0, P, T0 + 60, radar(False, error="source down"))
    assert sig.kind == "none" and sig.reason == "hold"


def test_exit_stop_loss_beats_time_stop() -> None:
    late = T0 + 121 * 60
    assert exit_signal(position(), [], 0.82, P, late).reason == "stop_loss"
    assert exit_signal(position(), [], 0.83, P, late).reason == "time_stop"
    assert exit_signal(position(), [], 0.83, P, T0 + 119 * 60).reason == "hold"


def test_exit_time_stop_beats_take_profit() -> None:
    assert exit_signal(position(), [], 1.5, P, T0 + 120 * 60).reason == "time_stop"


def test_partial_take_profit_once_then_trailing_stop() -> None:
    tp = exit_signal(position(), [], 1.40, P, T0 + 600)
    assert tp.kind == "exit" and tp.reason == "take_profit_partial" and tp.fraction == P.partial_tp_fraction
    taken = position(peak=1.6, partial=True)
    assert exit_signal(taken, [], 1.45, P, T0 + 600).reason == "hold"  # no second partial; 1.45 > 1.6*0.85
    trail = exit_signal(taken, [], 1.36, P, T0 + 600)
    assert trail.reason == "trailing_stop" and trail.fraction == 1.0


def test_trailing_stop_is_inactive_before_the_partial() -> None:
    assert exit_signal(position(peak=1.35), [], 1.0, P, T0 + 600).reason == "hold"


def test_exit_peak_uses_closed_candles_since_open_only() -> None:
    before_open = candle(-1, 1.0, 1.0, h=9.0)  # opened before the position: ignored
    after = [candle(0, 1.0, 1.2, h=1.7), candle(1, 1.2, 1.3, h=1.3)]
    still_open = candle(2, 1.3, 1.3, h=5.0)  # not closed at now: ignored
    now = after[-1].ts + 60 + 10
    sig = exit_signal(position(partial=True), [before_open, *after, still_open], 1.3, P, now)
    assert sig.metrics["peak_price_usd"] == pytest.approx(1.7)
    assert sig.reason == "trailing_stop"  # 1.3 <= 1.7 * 0.85
    assert sig.metrics["pnl_pct"] == pytest.approx(30.0) and sig.metrics["held_min"] == pytest.approx(2 + 10 / 60)


def test_exit_signal_does_not_mutate_position() -> None:
    pos = position()
    exit_signal(pos, [candle(0, 1.0, 1.2, h=1.3)], 1.25, P, T0 + 120)
    assert pos.peak_price_usd == 1.0


def test_exit_requires_entry_price() -> None:
    with pytest.raises(ValueError, match="no entry price"):
        exit_signal(position(entry=0.0), [], 1.0, P, T0)

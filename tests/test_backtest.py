"""backtest.py: next-open fills, pessimistic intrabar exits, costs, sizing, no lookahead, samples."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from nightcrawler import risk
from nightcrawler.backtest import (
    BacktestResult,
    Backtester,
    CostModel,
    SweepResult,
    aggregate_metrics,
    format_table,
    load_series,
)
from nightcrawler.clock import iso_utc
from nightcrawler.models import Candle, Signal, StrategyParams
from nightcrawler.strategy import entry_signal

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
T0 = 1_791_151_200  # 2026-10-04T22:00:00Z
P = StrategyParams()
FREE = CostModel(0.0, 0.0, 0.0)
META = {"coin": "TEST", "mint": "MintTest", "created_utc": iso_utc(T0 - 2 * 3600)}  # 2 h old: in the universe
# pump to 1.0, dump to 0.30, two green breakout closes -> entry signal at the close of candle 9
SETUP = [0.4, 0.7, 1.0, 0.8, 0.6, 0.45, 0.35, 0.30, 0.31, 0.33]
SIGNAL_INDEX = len(SETUP) - 1
HIGGS_NIGHT = (1_791_151_200, 1_791_180_000)  # 2026-10-04 22:00 -> 2026-10-05 06:00 UTC
HOOKI_NIGHT = (1_791_237_600, 1_791_270_000)  # 2026-10-05 22:00 -> 2026-10-06 07:00 UTC


def series(after: list[tuple[float, float, float, float]]) -> list[Candle]:
    """SETUP candles (opens chain from closes) then explicit (o, h, l, c) candles from index 10."""
    out, prev = [], SETUP[0]
    for i, c in enumerate(SETUP):
        out.append(Candle(T0 + 60 * i, prev, max(prev, c) * 1.001, min(prev, c) * 0.999, c, 100.0))
        prev = c
    for j, (o, h, low, c) in enumerate(after):
        out.append(Candle(T0 + 60 * (len(SETUP) + j), o, h, low, c, 100.0))
    return out


def flat(price: float, n: int) -> list[tuple[float, float, float, float]]:
    return [(price, price, price, price)] * n


def only_trade(result: BacktestResult):
    assert len(result.trades) == 1, result.trades
    return result.trades[0]


# --------------------------------------------------------------------------- costs & sizing


def test_cost_model_math() -> None:
    cm = CostModel()
    assert cm.cost_bps(1000) == pytest.approx(250)
    assert cm.buy_fill(1.0, 20) == pytest.approx(1.0103)
    assert cm.sell_fill(1.0, 2000) == pytest.approx(0.96)
    assert cm.sell_fill(1.0, 1e6) == 0.0  # absurd size: never a negative price


def test_sizing_delegates_to_risk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def spy(*args: float) -> float:
        calls.append(args)
        return 7.0

    monkeypatch.setattr(risk, "size_position_usd", spy)
    assert Backtester(P, position_pct=0.3, min_position_usd=5, max_position_usd=40).size_usd(50.0) == 7.0
    assert calls == [(50.0, 0.3, 5, 40)]


def test_from_settings_mirrors_the_live_bot(make_settings) -> None:
    bt = Backtester.from_settings(make_settings(PAPER_START_USD=250, POSITION_PCT=0.1, DIP_PCT=0.6,
                                                MAX_POSITION_USD=40))
    assert bt.start_usd == 250 and bt.position_pct == 0.1 and bt.max_position_usd == 40
    assert bt.min_position_usd == 5.0 and bt.params.dip_pct == 0.6 and bt.cost_model == CostModel()


def test_sizing_matches_risk_math() -> None:
    assert Backtester(P).size_usd(100.0) == pytest.approx(20.0)
    assert Backtester(P).size_usd(1000.0) == pytest.approx(25.0)  # MAX_POSITION_USD
    assert Backtester(P).size_usd(20.0) == 0.0  # 4 < MIN_POSITION_USD: skip, never round up
    assert Backtester(P, position_pct=1.0).size_usd(10.0) == pytest.approx(9.95)  # keeps the network fee


# --------------------------------------------------------------------------- fills


def test_entry_fills_at_next_candle_open_with_costs() -> None:
    candles = series([(0.33, 0.335, 0.329, 0.334)] + flat(0.334, 5))
    result = Backtester(P).run(candles, META)
    t = only_trade(result)
    assert t.entry_ts == candles[SIGNAL_INDEX + 1].ts
    assert t.entry_price == pytest.approx(0.33 * (1 + (100 + 150 * 20 / 1000) / 1e4))
    assert t.size_usd == pytest.approx(20.0)
    assert t.exit_reason == "end_of_data" and t.exit_ts == candles[-1].ts
    assert t.signal_metrics["dip"] > P.dip_pct
    assert result.metrics["net_pnl_usd"] == pytest.approx(t.pnl_usd, abs=1e-4)  # metrics are rounded to 4 dp
    assert result.equity_curve[-1][1] == pytest.approx(100 + t.pnl_usd)


def test_no_fill_without_a_next_candle() -> None:
    assert Backtester(P).run(series([]), META).trades == []


def test_stop_beats_take_profit_inside_one_candle() -> None:
    t = only_trade(Backtester(P, FREE).run(series([(0.33, 0.50, 0.25, 0.40)] + flat(0.4, 3)), META))
    assert t.exit_reason == "stop_loss" and not t.partial_taken
    assert t.exit_price == pytest.approx(0.33 * 0.82)


def test_fill_candle_itself_can_stop_out() -> None:
    t = only_trade(Backtester(P, FREE).run(series([(0.33, 0.33, 0.20, 0.21)]), META))
    assert t.exit_reason == "stop_loss" and t.exit_ts == t.entry_ts


def test_gap_below_stop_exits_at_the_open() -> None:
    t = only_trade(Backtester(P, FREE).run(series([(0.33, 0.335, 0.33, 0.333), (0.20, 0.25, 0.19, 0.24)]), META))
    assert t.exit_reason == "stop_loss" and t.exit_price == pytest.approx(0.20)


def test_partial_take_profit_then_trailing_stop() -> None:
    after = [(0.33, 0.34, 0.33, 0.34),  # peak 0.34
             (0.34, 0.50, 0.34, 0.48),  # TP 0.462 hit: sell half; trail (prev peak 0.34) = 0.289 not hit
             (0.48, 0.48, 0.40, 0.41)]  # peak now 0.50 -> trail 0.425 hit
    # the optimistic legacy fill model (peak from wicks); the default model: see the review-fix tests
    t = only_trade(Backtester(P, CostModel(0.0, 0.0, 0.0, **LEGACY_FILLS)).run(series(after), META))
    assert t.partial_taken and t.exit_reason == "trailing_stop"
    assert t.exit_price == pytest.approx((0.33 * 1.4 + 0.50 * 0.85) / 2)
    assert t.pnl_usd == pytest.approx(20 / 0.33 * ((0.462 + 0.425) / 2 - 0.33))


def test_trailing_gap_exits_at_the_open() -> None:
    after = [(0.33, 0.50, 0.33, 0.48), (0.30, 0.31, 0.29, 0.30)]  # partial at 0.462, then gap under trail
    t = only_trade(Backtester(P, FREE).run(series(after), META))
    assert t.exit_reason == "trailing_stop" and t.exit_price == pytest.approx((0.462 + 0.30) / 2)


def test_time_stop_at_the_open_of_the_first_candle_past_max_hold() -> None:
    candles = series(flat(0.33, 130))
    t = only_trade(Backtester(P, FREE).run(candles, META))
    assert t.exit_reason == "time_stop"
    assert t.exit_ts == t.entry_ts + P.max_hold_min * 60
    assert t.pnl_usd == pytest.approx(0.0)


def test_costs_are_charged_on_both_sides() -> None:
    t = only_trade(Backtester(P).run(series(flat(0.33, 3)), META))
    # flat price: the whole loss is costs (2 x ~1.03 % + 2 x $0.05)
    assert t.pnl_usd == pytest.approx(-t.fees_usd)
    assert 0.40 < t.fees_usd < 0.55


def test_equity_is_conserved() -> None:
    candles, meta = load_series(SAMPLES / "hooki_1m.json")
    result = Backtester(P).run(candles, meta)
    assert result.metrics["net_pnl_usd"] == pytest.approx(sum(t.pnl_usd for t in result.trades), abs=1e-3)


# --------------------------------------------------------------------------- universe, window, cooldown


def test_universe_filter_age_and_mcap() -> None:
    candles = series(flat(0.33, 5))
    too_young = {**META, "created_utc": iso_utc(T0)}  # 10 min old at the signal
    assert Backtester(P).run(candles, too_young).trades == []
    too_big = {**META, "supply": 1e8}  # 0.33 * 1e8 = $33M > MAX_MCAP_USD
    assert Backtester(P).run(candles, too_big).trades == []
    in_window = {**META, "supply": 1e6}  # $330K
    assert len(Backtester(P).run(candles, in_window).trades) == 1


def test_trade_window_limits_entries_but_not_exits() -> None:
    candles, meta = load_series(SAMPLES / "higgs_1m.json")
    start, end = HIGGS_NIGHT
    result = Backtester(P).run(candles, meta, trade_from=start, trade_until=end)
    assert result.trades
    for t in result.trades:
        assert start <= t.entry_ts <= end  # decided at now in [start, end), filled at the next open
    assert result.span["first_ts"] == start - 60  # first marked candle closes at the window start
    assert result.span["trade_from"] == start and result.span["trade_until"] == end


def test_cooldown_between_trades() -> None:
    candles, meta = load_series(SAMPLES / "higgs_1m.json")
    trades = Backtester(P).run(candles, meta).trades
    assert len(trades) >= 2
    for prev, nxt in zip(trades, trades[1:], strict=False):
        assert nxt.entry_ts >= prev.exit_ts + P.cooldown_min * 60


# --------------------------------------------------------------------------- NO LOOKAHEAD


@pytest.mark.parametrize("fname", ["higgs_1m.json", "hooki_1m.json"])
def test_backtest_has_no_lookahead(fname: str) -> None:
    """Replace everything after a cut with garbage: every trade finished before the cut is identical."""
    candles, meta = load_series(SAMPLES / fname)
    bt = Backtester(P)
    full = bt.run(candles, meta).trades
    for cut in (len(candles) // 3, len(candles) // 2, 2 * len(candles) // 3):
        cut_ts = candles[cut].ts
        garbage = [Candle(c.ts, 1e-9, 1.0, 1e-12, 0.5, 1e9) for c in candles[cut:]]
        altered = bt.run(candles[:cut] + garbage, meta).trades
        before = [t for t in full if t.exit_ts < cut_ts]
        assert before, "cut too early to prove anything"
        assert [t for t in altered if t.exit_ts < cut_ts] == before


# --------------------------------------------------------------------------- files


def write(path: Path, doc: object) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_load_series_sorts_dedupes_and_strips_candles(tmp_path: Path) -> None:
    rows = [[120, 1, 1, 1, 1, 0], [60, 2, 2, 2, 2], [120, 3, 3, 3, 3, 5]]
    candles, meta = load_series(write(tmp_path / "abc.json", {"mint": "M", "candles": rows}))
    assert [c.ts for c in candles] == [60, 120] and candles[1].c == 3 and candles[0].v == 0.0
    assert meta == {"mint": "M", "coin": "abc"}


@pytest.mark.parametrize("doc,match", [
    ({"candles": []}, "no candles"),
    ({"coin": "X"}, "candles"),
    ([1, 2], "candles"),
    ({"candles": [[60, "x", 1, 1, 1]]}, "bad candle row 0"),
    ({"candles": [[60, 1, 1]]}, "bad candle row 0"),
    ({"candles": [[60, 1, float("nan"), 1, 1]]}, "non-finite"),
])
def test_load_series_rejects_invalid_files(tmp_path: Path, doc: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_series(write(tmp_path / "bad.json", doc))


def test_load_series_rejects_non_json(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_series(path)


def test_run_many_aggregates_and_skips_bad_files(tmp_path: Path) -> None:
    bad = write(tmp_path / "empty.json", {"coin": "DEAD", "candles": []})
    results, agg = Backtester(P).run_many([SAMPLES / "higgs_1m.json", SAMPLES / "hooki_1m.json", bad])
    assert [r.coin for r in results] == ["HIGGS", "HOOKI"]
    assert agg["series"] == 2 and agg["series_skipped"] == 1
    assert agg["trades"] == sum(len(r.trades) for r in results)
    assert agg["net_pnl_usd"] == pytest.approx(sum(r.metrics["net_pnl_usd"] for r in results), abs=1e-3)
    assert agg["total_return_pct"] == pytest.approx(agg["net_pnl_usd"] / 200 * 100, abs=1e-3)
    assert agg["max_drawdown_pct"] == max(r.metrics["max_drawdown_pct"] for r in results)


def test_aggregate_of_nothing() -> None:
    agg = aggregate_metrics([], 100.0)
    assert agg["trades"] == 0 and agg["win_rate_pct"] is None and agg["total_return_pct"] == 0.0


def test_metrics_are_json_safe_and_complete() -> None:
    candles, meta = load_series(SAMPLES / "higgs_1m.json")
    result = Backtester(P).run(candles, meta)
    expected = {"trades", "wins", "losses", "win_rate_pct", "total_return_pct", "net_pnl_usd", "avg_trade_pct",
                "median_trade_pct", "max_drawdown_pct", "profit_factor", "fees_usd", "exposure_pct",
                "best_trade_pct", "worst_trade_pct"}
    assert expected <= set(result.metrics)
    doc = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert "equity_curve" not in doc and doc["cost_model"]["fee_bps_per_side"] == 100.0
    assert "equity_curve" in result.to_dict(include_equity_curve=True)
    assert all(not isinstance(v, float) or math.isfinite(v) for v in result.metrics.values())


def test_format_table_has_rows_total_and_dashes() -> None:
    results, agg = Backtester(P).run_many([SAMPLES / "higgs_1m.json"])
    empty = Backtester(P).run(series([]), META)
    table = format_table([*results, empty], agg)
    lines = table.splitlines()
    assert lines[0].startswith("series") and "return%" in lines[0]
    assert lines[2].startswith("HIGGS") and lines[-1].startswith("TOTAL")
    assert "-" in lines[3].split()  # TEST had no trades -> undefined metrics shown as '-'
    assert len({len(line) for line in lines}) == 1  # fixed width


# --------------------------------------------------------------------------- sweep


def test_sweep_splits_by_launch_time_and_reports_out_of_sample() -> None:
    paths = [SAMPLES / "hooki_1m.json", SAMPLES / "higgs_1m.json"]  # deliberately unsorted
    grid = {"dip_pct": [0.5, 0.6], "stop_loss_pct": [0.1, 0.18]}
    result = Backtester(P).sweep(grid, paths, train_frac=0.5)
    assert isinstance(result, SweepResult)
    assert result.train_coins == ["HIGGS"] and result.test_coins == ["HOOKI"]  # HIGGS launched first
    assert len(result.rows) == 4
    for row in result.rows:
        assert {"dip_pct", "stop_loss_pct", "train", "test"} <= set(row)
        assert row["train"]["series"] == 1 and row["test"]["series"] == 1
    best = max(result.rows, key=lambda r: (r["train"]["total_return_pct"], -r["train"]["trades"]))
    assert result.best_params == {"dip_pct": best["dip_pct"], "stop_loss_pct": best["stop_loss_pct"]}


def test_sweep_validation() -> None:
    with pytest.raises(ValueError, match="at least 2 series"):
        Backtester(P).sweep({"dip_pct": [0.5]}, [SAMPLES / "higgs_1m.json"])
    with pytest.raises(ValueError, match="unknown strategy params"):
        Backtester(P).sweep({"dip": [0.5]}, [SAMPLES / "higgs_1m.json", SAMPLES / "hooki_1m.json"])


# --------------------------------------------------------------------------- the real nights


@pytest.mark.parametrize("fname,night", [("higgs_1m.json", HIGGS_NIGHT), ("hooki_1m.json", HOOKI_NIGHT)])
def test_samples_run_end_to_end(fname: str, night: tuple[int, int]) -> None:
    candles, meta = load_series(SAMPLES / fname)
    result = Backtester(P).run(candles, meta, trade_from=night[0], trade_until=night[1])
    assert result.trades and result.metrics["fees_usd"] > 0
    assert all(t.size_usd <= 25.0 for t in result.trades)
    # the curve ends on the realized equity, even when the last exit happens after the window
    assert result.equity_curve[-1][1] == pytest.approx(100 + result.metrics["net_pnl_usd"], abs=1e-3)


def test_published_sample_results_reproduce() -> None:
    """docs/backtests/samples.json must match a fresh run (regenerate it if the strategy changes)."""
    doc = json.loads((ROOT / "docs" / "backtests" / "samples.json").read_text(encoding="utf-8"))
    run = next(r for r in doc["runs"] if r["id"] == "default_100")
    for entry in run["series"]:
        candles, meta = load_series(ROOT / entry["file"])
        result = Backtester(P).run(candles, meta, trade_from=entry["trade_from"], trade_until=entry["trade_until"])
        assert result.metrics["trades"] == entry["metrics"]["trades"]
        assert result.metrics["net_pnl_usd"] == pytest.approx(entry["metrics"]["net_pnl_usd"], abs=0.05)


# --------------------------------------------------------------------------- review fixes


LEGACY_FILLS = {"stop_fill": "level", "tp_needs_close": False, "peak_from": "high"}


def test_a_stop_candle_closing_far_below_the_stop_fills_at_the_close() -> None:
    """A poller sees the price every few seconds, not the exact stop level: when the candle CLOSES
    below the stop, booking the stop level is optimistic."""
    after = [(0.33, 0.335, 0.20, 0.21)]  # stop 0.2706; low 0.20; close 0.21
    t = only_trade(Backtester(P, FREE).run(series(after + flat(0.21, 3)), META))
    assert t.exit_reason == "stop_loss" and t.exit_price == pytest.approx(0.21)
    legacy = only_trade(Backtester(P, CostModel(0.0, 0.0, 0.0, **LEGACY_FILLS)).run(
        series(after + flat(0.21, 3)), META))
    assert legacy.exit_price == pytest.approx(0.33 * 0.82)
    above = only_trade(Backtester(P, FREE).run(series([(0.33, 0.335, 0.25, 0.30)] + flat(0.30, 3)), META))
    assert above.exit_price == pytest.approx(0.33 * 0.82)  # closed back above the stop: the stop level


def test_a_one_minute_wick_through_the_take_profit_is_not_a_fill() -> None:
    wick = [(0.33, 0.47, 0.33, 0.34)] + flat(0.34, 3)  # TP 0.462 touched only by the wick
    t = only_trade(Backtester(P, FREE).run(series(wick), META))
    assert not t.partial_taken
    held = [(0.33, 0.47, 0.33, 0.465)] + flat(0.465, 3)  # closed above the TP: it held
    assert only_trade(Backtester(P, FREE).run(series(held), META)).partial_taken
    assert only_trade(Backtester(P, CostModel(0.0, 0.0, 0.0, **LEGACY_FILLS)).run(series(wick), META)).partial_taken


def test_the_trailing_peak_follows_closes_not_wicks() -> None:
    after = [(0.33, 0.34, 0.33, 0.34),
             (0.34, 0.50, 0.34, 0.48),  # partial at 0.462 (closed above); peak 0.48 (close), not the 0.50 wick
             (0.48, 0.48, 0.40, 0.41)]  # trail 0.408 hit
    t = only_trade(Backtester(P, FREE).run(series(after), META))
    assert t.partial_taken and t.exit_reason == "trailing_stop"
    assert t.exit_price == pytest.approx((0.462 + 0.48 * 0.85) / 2)
    assert Backtester(P, FREE).run(series(after), META).cost_model["peak_from"] == "close"


def test_missing_minutes_are_filled_like_the_live_candle_client() -> None:
    """GeckoTerminal's client inserts flat zero-volume candles for missing minutes, which breaks a
    green run; the backtester must see the same series."""
    candles = series(flat(0.33, 3))
    gapped = candles[:SIGNAL_INDEX] + [Candle(c.ts + 60, c.o, c.h, c.l, c.c, c.v) for c in candles[SIGNAL_INDEX:]]
    assert len(Backtester(P, FREE).run(candles, META).trades) == 1
    assert Backtester(P, FREE).run(gapped, META).trades == []  # the flat filler candle is not green


def test_the_backtest_universe_can_mirror_the_live_watch_window() -> None:
    """Live watches a fresh launch from maturity (MIN_AGE_MIN) for WATCHLIST_TTL_H only."""
    candles = series(flat(0.33, 5))
    old = {**META, "created_utc": iso_utc(T0 - 10 * 3600)}  # 10 h old at the setup
    assert len(Backtester(P, FREE).run(candles, old).trades) == 1  # default: any age (a coin that keeps trending)
    assert Backtester(P, FREE, watch_ttl_h=6.0).run(candles, old).trades == []
    assert len(Backtester(P, FREE, watch_ttl_h=6.0).run(candles, META).trades) == 1  # 2 h old: watched
    # the prefilter's mcap window is applied once at maturity: a token too small then was never watched
    tiny_then = {**META, "created_utc": iso_utc(T0 - 61 * 60), "supply": 1e6}
    rows = [Candle(T0 - 60, 0.01, 0.01, 0.01, 0.01, 1.0)] + candles  # $10K mcap at maturity (T0 - 60)
    assert len(Backtester(P, FREE).run(rows, tiny_then).trades) == 1  # $330K at the setup: inside the window
    assert Backtester(P, FREE, watch_ttl_h=6.0).run(rows, tiny_then).trades == []


def test_from_settings_mirrors_the_live_watch_window(make_settings) -> None:
    assert Backtester.from_settings(make_settings(WATCHLIST_TTL_H=4)).watch_ttl_h == 4.0
    assert Backtester.from_settings(make_settings(), any_age=True).watch_ttl_h is None


# --------------------------------------------------------------------------- learning hooks (docs/LEARNING.md §4.2)


def _sample_runs(bt: Backtester) -> list[dict]:
    out = []
    for fname in ("higgs_1m.json", "hooki_1m.json"):
        candles, meta = load_series(SAMPLES / fname)
        out.append(bt.run(candles, meta).to_dict(include_equity_curve=True))
    for after in ([(0.33, 0.50, 0.33, 0.48), (0.48, 0.48, 0.40, 0.41)], flat(0.33, 130), [(0.33, 0.33, 0.2, 0.21)]):
        out.append(bt.run(series(after), META).to_dict(include_equity_curve=True))
    return out


def test_hooks_default_to_none_and_change_nothing() -> None:
    plain = Backtester(P)
    assert (plain.cost_fn, plain.decide_at, plain.entry_delay_s, plain.entry_fn) == (None, None, None, None)
    explicit = Backtester(P, cost_fn=None, decide_at=None, entry_delay_s=None, entry_fn=None)
    runs = _sample_runs(plain)
    assert sum(len(r["trades"]) for r in runs) >= 5
    assert _sample_runs(explicit) == runs


def test_identity_hooks_reproduce_the_default_run() -> None:
    cm = CostModel()

    def same_costs(side: str, price: float, size_usd: float) -> float:
        return cm.buy_fill(price, size_usd) if side == "buy" else cm.sell_fill(price, size_usd)

    hooked = Backtester(P, cost_fn=same_costs, decide_at=lambda now: now, entry_fn=entry_signal)
    assert _sample_runs(hooked) == _sample_runs(Backtester(P))


def test_decide_at_moves_or_skips_decisions() -> None:
    candles = series([(0.33, 0.335, 0.329, 0.334)] + flat(0.334, 5))
    assert Backtester(P, FREE, decide_at=lambda now: None).run(candles, META).trades == []
    seen: list[float] = []

    def later(now: float) -> float:
        seen.append(now)
        return now + 70  # decided 70 s after the candle closed: the entry lands in the candle after next

    t = only_trade(Backtester(P, FREE, decide_at=later).run(candles, META))
    assert t.entry_ts == candles[SIGNAL_INDEX + 2].ts and t.entry_price == pytest.approx(candles[SIGNAL_INDEX + 2].o)
    assert seen[0] == candles[0].ts + 60  # asked once per closed candle while flat


def test_entry_delay_fills_at_the_worse_of_the_landing_open_and_the_decision_close() -> None:
    signal_close = SETUP[-1]
    up = series([(0.33, 0.34, 0.33, 0.335), (0.336, 0.34, 0.335, 0.338)] + flat(0.338, 3))
    t = only_trade(Backtester(P, FREE, entry_delay_s=65).run(up, META))
    assert t.entry_ts == up[SIGNAL_INDEX + 2].ts  # decided at the signal close, landing 65 s later
    assert t.entry_price == pytest.approx(0.336)  # landing open above the decision close
    down = series([(0.33, 0.33, 0.32, 0.325), (0.32, 0.325, 0.31, 0.32)] + flat(0.32, 3))
    t = only_trade(Backtester(P, FREE, entry_delay_s=65).run(down, META))
    assert t.entry_price == pytest.approx(signal_close)  # never below the price the strategy decided on
    assert Backtester(P, FREE, entry_delay_s=65).run(series([(0.33, 0.33, 0.33, 0.33)]), META).trades == []


def test_a_cost_hook_can_refuse_an_entry_and_prices_both_sides() -> None:
    candles = series(flat(0.33, 5))
    refuse = Backtester(P, FREE, cost_fn=lambda side, price, size: math.inf if side == "buy" else price)
    assert refuse.run(candles, META).trades == []
    calls: list[tuple[str, float, float]] = []

    def two_pct(side: str, price: float, size_usd: float) -> float:
        calls.append((side, price, size_usd))
        return price * (1.02 if side == "buy" else 0.98)

    t = only_trade(Backtester(P, FREE, cost_fn=two_pct).run(candles, META))
    assert t.entry_price == pytest.approx(0.33 * 1.02) and t.exit_price == pytest.approx(0.33 * 0.98)
    assert [c[0] for c in calls] == ["buy", "sell"] and calls[0][2] == pytest.approx(20.0)


def test_an_entry_hook_replaces_the_signal() -> None:
    candles = series(flat(0.33, 40))
    when = candles[20].ts

    def at_a_time(window, snapshot, params, now):
        kind = "enter" if now >= when else "none"
        return Signal(kind=kind, reason="placebo", confidence=0.0, metrics={"last_ts": window[-1].ts})

    trades = Backtester(P, FREE, entry_fn=at_a_time).run(candles, META).trades
    # the candle before ``when`` closes AT ``when``: decided then, filled at the next open
    assert trades[0].entry_ts == when and trades[0].signal_metrics == {"last_ts": when - 60}

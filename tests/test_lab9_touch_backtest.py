"""Fake archive checks: causal TRAIN diagnostics must never become fill claims."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
# Research is a source-tree namespace, deliberately absent from the app package.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("lab9_touch_backtest", ROOT / "research/lab9/touch_backtest.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def market(*, month: int = 1, result: str = "no", early: bool = False) -> dict[str, Any]:
    name = datetime(2026, month, 31 if month in (1, 7) else 30)
    end = (name + timedelta(days=1)).replace(hour=5 if month == 1 else 4, tzinfo=UTC) - timedelta(seconds=1)
    return {
        "ticker": f"KXBTCMAXMON-BTC-26{name.strftime('%b').upper()}31-12000",
        "status": "finalized", "result": result,
        "rules_primary": f"If the price of BTC through 11:59 PM ET on {name.strftime('%b %d, %Y')} is above $120, then Yes.",
        "rules_secondary": "Every minute uses cumulative dataset trimmed values.",
        "expected_expiration_time": end.isoformat(), "occurrence_datetime": end.isoformat(),
        "open_time": name.replace(day=1, tzinfo=UTC).isoformat(),
        "close_time": (name.replace(day=25, tzinfo=UTC) if early else end).isoformat(),
        "floor_strike": 120, "strike_type": "greater",
    }


def trade(ticker: str, **extra: Any) -> dict[str, Any]:
    return {"ticker": ticker, "trade_id": "a", "created_time": "2026-01-20T12:00:15Z",
            "no_price_dollars": "0.9700", "yes_price_dollars": "0.0300", "count_fp": "2.00",
            "is_block_trade": False, "taker_outcome_side": "yes", "taker_book_side": "bid",
            **extra}


def archive(tmp_path: Path, markets: list[dict[str, Any]], rows: list[dict[str, Any]]) -> Path:
    data = {"cutoff_unix": int(datetime(2026, 10, 12, tzinfo=UTC).timestamp()),
            "series": {series: {"live_markets": [], "historical_markets": []} for series in module.SERIES}}
    data["series"][module.SERIES[0]]["historical_markets"] = markets
    (tmp_path / "inventory.json").write_text(json.dumps(data))
    manifest: dict[str, Any] = {"complete": True, "markets": {}}
    (tmp_path / "trades").mkdir()
    for m in markets:
        selected = [row for row in rows if row["ticker"] == m["ticker"]]
        path = tmp_path / "trades" / (m["ticker"] + ".jsonl")
        path.write_text("".join(json.dumps(row) + "\n" for row in selected))
        manifest["markets"][m["ticker"]] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "trades": len(selected)}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def candles() -> dict[str, Any]:
    last = int(module.timestamp("2026-01-20T11:00:00Z"))
    result = {}
    for i in range(721):
        at = last - (720 - i) * 3600
        close = 100 * math.exp(.005 * math.sin(i))
        result[at] = module.Candle(at, close, close, close, close, 1)
    return {"BTC": result}


def test_scheduled_end_keeps_early_resolved_loser_in_its_original_month() -> None:
    source = market(result="yes", early=True)
    end, month = module.scheduled_end(source)
    assert month == "2026-01"
    assert datetime.fromtimestamp(end, UTC).month == 2
    assert end > module.timestamp(source["close_time"])


@pytest.mark.parametrize("edit", [
    {"expected_expiration_time": "2026-01-25T00:00:00Z"},
    {"occurrence_datetime": "2026-02-02T04:59:59Z"},
    {"rules_primary": "Above 120 in January"},
])
def test_missing_or_disagreeing_rules_endpoint_is_not_guessed(edit: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        module.scheduled_end(market() | edit)


@pytest.mark.parametrize(("days", "bucket"), [(0, "[0,1)"), (1, "[1,7]"), (7, "[1,7]"), (7.01, "(7,14]"), (14, "(7,14]"), (21, "(14,21]"), (31, "(21,31]"), (31.1, "outside")])
def test_exact_days_bucket_edges(days: float, bucket: str) -> None:
    assert module.days_bucket(days) == bucket


@pytest.mark.parametrize(("z", "bucket"), [(0, "[0,1.5)"), (1.5, "[1.5,2)"), (2, "[2,3)"), (3, "[3,4)"), (4, "[4,infinity)"), (-1, "unsafe_or_unknown")])
def test_exact_z_bucket_edges(z: float, bucket: str) -> None:
    assert module.z_bucket(z) == bucket


def test_price_direction_is_never_inverted_or_guessed_from_legacy_field() -> None:
    assert module.no_role({"taker_outcome_side": "yes", "taker_book_side": "bid"}) == "NO_maker_direction"
    assert module.no_role({"taker_outcome_side": "no", "taker_book_side": "ask"}) == "NO_taker_direction"
    assert module.no_role({"taker_side": "yes"}) == "unknown"
    assert module.no_role({"taker_outcome_side": "yes", "taker_book_side": "ask"}) == "unknown"
    assert module.no_role({"taker_outcome_side": "yes", "taker_book_side": "bid", "taker_side": "no"}) == "unknown"


def test_direct_contemporary_unit_fee_uses_two_explicit_rounding_steps() -> None:
    assert module.direct_unit_taker_fee(Decimal(".97")) == Decimal(".0021")
    assert module.direct_unit_taker_fee(Decimal(".99")) == Decimal(".0007")
    assert module.direct_unit_taker_fee(Decimal(".9655")) >= Decimal(".07") * Decimal(".9655") * Decimal(".0345")
    with pytest.raises(ValueError):
        module.direct_unit_taker_fee(Decimal("NaN"))


def test_multiple_correlated_prints_are_not_independent_markets_or_pnl() -> None:
    cell = module.Cell()
    cell.add("a", "2026-01", Decimal(".97"), Decimal(10), True)
    cell.add("a", "2026-01", Decimal(".99"), Decimal(2), True)
    cell.add("b", "2026-01", Decimal(".98"), Decimal(".50"), False)
    report = cell.report()
    assert report["prints"] == 3
    assert report["distinct_markets"] == 2
    assert report["market_win_rate"] == .5
    assert report["print_win_rate"] == 2 / 3
    assert report["unit_sensitivity_prints_ge1_contract"] == 2
    assert Decimal(report["mean_unit_gross_payoff_at_print"]) == Decimal(".02")
    assert report["execution_qualified_pnl"] is None


def test_early_loser_is_described_but_no_strategy_passes(tmp_path: Path) -> None:
    m = market(result="yes", early=True)
    result = module.analyze(archive(tmp_path, [m], [trade(m["ticker"])]), candles())
    assert result["counts"]["TRAIN_descriptive_prints"] == 1
    assert result["cells"][0]["NO_losing_markets"] == 1
    assert Decimal(result["cells"][0]["mean_unit_payoff_after_contemporary_taker_stress"]) == Decimal("-.9721")
    assert result["practice_build_gate_passed"] is False
    assert result["candidate_selected"] is None
    assert result["strategy_returns_computed"] is False
    assert result["execution_qualified_pnl"] is None
    assert result["no_fill_scenario_pnl"] == "0"
    assert result["no_fill_scenario_is_proven_execution"] is False


def test_held_out_print_files_are_never_opened_even_if_corrupt(tmp_path: Path) -> None:
    train, val, test = market(), market(month=4), market(month=7)
    path = archive(tmp_path, [train, val, test], [trade(train["ticker"])])
    for held_out in (val, test):
        (path / "trades" / (held_out["ticker"] + ".jsonl")).write_text("DO NOT READ")
    result = module.analyze(path, candles())
    assert result["VAL_prints_read"] == result["TEST_prints_read"] == 0
    assert result["VAL_outcomes_evaluated"] == result["TEST_outcomes_evaluated"] == 0
    assert result["counts"]["TRAIN_all_prints"] == 1
    assert all(row["split"] == "TRAIN" for row in result["months"])


def test_missing_hours_and_missing_months_never_become_zero_profit(tmp_path: Path) -> None:
    m = market()
    result = module.analyze(archive(tmp_path, [m], [trade(m["ticker"])]), {})
    assert result["cells"] == []
    assert result["counts"]["TRAIN_missing_feature_missing_latest_closed_hour"] == 1
    missing = result["months"][0]
    assert missing["month"] == "2025-10"
    assert missing["coverage_status"] == "no_markets_returned"
    assert missing["execution_qualified_pnl"] is None
    assert missing["mean_unit_gross_payoff_at_print"] is None


def test_checksum_tampering_fails_instead_of_inventing_missing_data(tmp_path: Path) -> None:
    m = market()
    path = archive(tmp_path, [m], [trade(m["ticker"])])
    (path / "trades" / (m["ticker"] + ".jsonl")).write_text("[]\n")
    with pytest.raises(ValueError, match="checksum"):
        module.analyze(path, candles())


def test_future_or_duplicate_trade_identity_is_rejected(tmp_path: Path) -> None:
    m = market()
    path = archive(tmp_path, [m], [trade(m["ticker"]), trade(m["ticker"])])
    with pytest.raises(ValueError, match="duplicate"):
        module.analyze(path, candles())


def test_block_trades_and_unknown_block_status_are_not_book_evidence(tmp_path: Path) -> None:
    m = market()
    path = archive(tmp_path, [m], [trade(m["ticker"], is_block_trade=True)])
    result = module.analyze(path, candles())
    assert result["counts"]["TRAIN_block_or_unknown_prints_excluded"] == 1
    assert result["cells"] == []


def test_zero_print_market_remains_in_census(tmp_path: Path) -> None:
    m = market()
    result = module.analyze(archive(tmp_path, [m], []), candles())
    assert result["counts"]["TRAIN_zero_print_markets"] == 1
    assert result["months"][3]["census_markets"] == 1
    assert result["months"][3]["execution_qualified_pnl"] is None


def test_conflicting_and_whole_period_rules_remain_separate() -> None:
    assert module.rule_cohort({"rules_secondary": "is above the threshold"}, "MIN") == "primary_below_secondary_above_conflict"
    assert module.rule_cohort({"rules_secondary": "calculating the final average"}, "MAX") == "whole_period_final_trim_not_verified_touch"
    assert module.rule_cohort({"rules_secondary": "cumulative dataset"}, "MAX") == "cumulative_trim_conflicts_with_minute_terms"


def test_prices_do_not_schedule_decisions_and_hour_features_are_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = market()
    path = archive(tmp_path, [m], [
        trade(m["ticker"], created_time="2026-01-20T12:00:04Z"),
        trade(m["ticker"], trade_id="b", created_time="2026-01-20T12:00:05Z"),
        trade(m["ticker"], trade_id="c", created_time="2026-01-20T12:50:00Z"),
    ])
    decisions = []

    def feature(_candles: Any, at: float) -> dict[str, Any]:
        decisions.append(at)
        return {"eligible": True, "spot": 100, "sigma_annual": .3}

    monkeypatch.setattr(module, "features_at", feature)
    result = module.analyze(path, {})
    assert decisions == [module.timestamp("2026-01-20T11:00:05Z"), module.timestamp("2026-01-20T12:00:05Z")]
    assert result["counts"]["TRAIN_descriptive_prints"] == 3
    assert result["train_markets"][0]["all_source_prints"] == 3


def test_safe_side_is_signed_and_beyond_barrier_prints_are_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = market()
    path = archive(tmp_path, [m], [trade(m["ticker"])])
    monkeypatch.setattr(module, "features_at", lambda *_: {"eligible": True, "spot": 130, "sigma_annual": .3})
    result = module.analyze(path, {})
    assert result["counts"]["TRAIN_wrong_safe_side_or_expired_prints"] == 1
    assert result["cells"] == []

"""No-network tests for weather observation provenance and quote counterfactuals."""
from __future__ import annotations

import json

import pytest

from nightcrawler.weatherwatch_model import (
    WeatherwatchModel,
    observation_kills,
    weather_fee,
)

START = 1_791_849_600.0  # An arbitrary UTC day; tests use explicit market periods.


def market(**changes):
    return {"market_id": "kalshi:HIGH", "venue": "kalshi", "venue_id": "HIGH",
        "kind": "high", "station": "KNYC", "station_verified": True,
        "period_start": START, "period_end": START + 86400, "date": "2026-10-13",
        "source_verified": True, "source_qualified": False, "period_verified": False,
        "fee_verified": True, "fee_type": "quadratic", "fee_multiplier": 1,
        "fee_model": "kalshi_direct", "fee_precision": .0001,
        "settlement_source": "TWC", "strike_type": "between", "floor": 60, "cap": 61,
        **changes}


def observation(at, *, source="nws", valid=None, **changes):
    valid = at - 1 if valid is None else valid
    return {"station": "KNYC", "source": source, "received_at": at, "valid_at": valid,
        "observation_id": f"{source}:{valid}", "independent_id": f"metar:KNYC:{valid}",
        "quality": "accepted", "lower_f": 61.01, "upper_f": 61.19,
        "resolution_s": None, "independent_1m": False, **changes}


def book(at, **changes):
    return {"market_id": "kalshi:HIGH", "venue": "kalshi", "valid": True,
        "complete": True, "source": "websocket", "exchange_at": at - .01,
        "received_at": at, "no_bids": [[.95, 50]], "no_asks": [[.97, 10]], **changes}


def model(**market_changes):
    result = WeatherwatchModel(START)
    result.ingest("market", market(**market_changes), START)
    return result


def confirmed(**market_changes):
    result = model(**market_changes)
    result.ingest("observation", observation(START + 10), START + 10)
    result.ingest("observation", observation(START + 70), START + 70)
    return result


def enter(result):
    result.ingest("book", book(START + 71), START + 71)
    result.ingest("book", book(START + 71.3), START + 71.3)
    return result.locks["kalshi:HIGH"]["scenarios"]["0.97"]


@pytest.mark.parametrize(("kind", "strike", "floor", "cap", "lower", "upper", "killed"), [
    ("high", "between", 60, 61, 61, 61.18, False),
    ("high", "between", 60, 61, 61.01, 61.19, True),
    ("high", "less", None, 61, 61, 61.18, True),
    ("high", "greater", 61, None, 90, 91, False),
    ("low", "between", 60, 61, 59.82, 60, False),
    ("low", "between", 60, 61, 59.81, 59.99, True),
    ("low", "greater", 60, None, 59.82, 60, True),
    ("low", "less", None, 61, -20, -19, False),
])
def test_precision_and_strict_bounds(kind, strike, floor, cap, lower, upper, killed):
    assert observation_kills(market(kind=kind, strike_type=strike, floor=floor, cap=cap),
                             {"lower_f": lower, "upper_f": upper}) is killed


def test_first_observation_starts_capture_but_is_not_a_lock():
    result = model()
    actions = result.ingest("observation", observation(START + 10), START + 10)
    assert actions == [{"kind": "watch_request", "market_id": "kalshi:HIGH", "venue": "kalshi",
                        "until": START + 610, "first_candidate_at": START + 10,
                        "signal_id": f"kalshi:HIGH:{START + 10}"}]
    assert result.locks["kalshi:HIGH"]["confirmed_at"] is None
    assert result.summary(START + 10)["qualified_locks"] == 0


def test_same_metar_across_sources_cannot_confirm():
    result = model()
    result.ingest("observation", observation(START + 10), START + 10)
    result.ingest("observation", observation(START + 20, source="awc", valid=START + 9), START + 20)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] is None
    result.ingest("observation", observation(START + 70), START + 70)
    lock = result.locks["kalshi:HIGH"]
    assert lock["confirmed_at"] == START + 70
    assert lock["confirmation_delay_s"] == 60
    assert lock["capture_until"] == START + 670
    assert lock["classification"] == "confirmed_observation_proxy"
    assert lock["qualified_lock"] is False
    assert lock["source_qualified"] is False


def test_genuine_independent_minute_can_confirm_equal_valid_time():
    result = model()
    result.ingest("observation", observation(START + 10), START + 10)
    result.ingest("observation", observation(START + 11, source="asos_minute", valid=START + 9,
        independent_id="minute:independent-sensor:9", independent_1m=True, resolution_s=60), START + 11)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] == START + 11


def test_nonqualifying_and_suspect_readings_break_confirmation_chain():
    result = model()
    for at, extra in [(10, {}), (20, {"quality": "suspect"}), (30, {}),
                      (40, {"lower_f": 60}), (50, {})]:
        result.ingest("observation", observation(START + at, **extra), START + at)
        assert result.locks["kalshi:HIGH"]["confirmed_at"] is None
    result.ingest("observation", observation(START + 60), START + 60)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] == START + 60


@pytest.mark.parametrize("changes", [{"station": "KLGA"}, {"quality": "suspect"},
    {"quality": "unknown"}, {"valid": START - 1}, {"valid": START + 100},
    {"lower_f": None}, {"lower_f": float("nan")}])
def test_bad_wrong_station_or_outside_day_readings_cannot_start(changes):
    result = model()
    result.ingest("observation", observation(START + 10, **changes), START + 10)
    assert not result.locks


def test_missing_station_and_climate_period_block_signal():
    for changes in ({"station_verified": False}, {"period_start": None}, {"period_end": None}):
        result = model(**changes)
        result.ingest("observation", observation(START + 10), START + 10)
        assert not result.locks


def test_startup_old_reading_is_explicitly_left_censored():
    result = WeatherwatchModel(START + 100)
    result.ingest("market", market(), START + 100)
    result.ingest("observation", observation(START + 101, valid=START + 60), START + 101)
    assert result.locks["kalshi:HIGH"]["left_censored_initial_reading"] is True
    assert result.locks["kalshi:HIGH"]["coverage_partial"] is True


def test_first_seen_survives_restore_and_duplicate_does_not_change_latency():
    result = model()
    item = observation(START + 10)
    result.ingest("observation", item, START + 10)
    restored = WeatherwatchModel.restore(json.loads(json.dumps(result.state())), START + 20)
    restored.ingest("observation", {**item, "received_at": START + 21}, START + 21)
    day = restored.summary(START + 21)["today"]
    assert day["sources"]["nws"]["readings"] == 1
    assert day["sources"]["nws"]["median"] is None
    assert day["sources"]["nws"]["bootstrap_median_s"] == 1
    assert restored.started_at == START
    assert restored.locks["kalshi:HIGH"]["first_candidate_at"] == START + 10
    assert restored.locks["kalshi:HIGH"]["last_valid_at"] is None
    assert restored.summary(START + 21)["restarts"] == 1


def test_source_receipts_have_separate_first_seen_latency():
    result = model()
    result.ingest("observation", observation(START + 10, valid=START + 5), START + 10)
    result.ingest("observation", observation(START + 20, source="awc", valid=START + 5), START + 20)
    sources = result.summary(START + 20)["today"]["sources"]
    assert sources["nws"]["bootstrap_median_s"] == 5
    assert sources["awc"]["bootstrap_median_s"] == 15


def test_quote_at_confirmation_waits_for_new_receipt_after_delay():
    result = confirmed()
    result.ingest("book", book(START + 71), START + 71)
    row = result.locks["kalshi:HIGH"]["scenarios"]["0.97"]
    assert row["status"] == "checking_quote_persistence"
    result.ingest("book", book(START + 71.1), START + 71.1)
    assert "entry_price" not in row
    result.tick(START + 71.5)
    # The 71.1 receipt is later but predates the planned 71.25 send point.
    # It must not be represented as a fresh post-delay fill check.
    assert "entry_price" not in row
    result.ingest("book", book(START + 71.6), START + 71.6)
    assert row["entry_price"] == .97
    assert row["entry_fee_usd"] == .0021
    assert row["execution_proven"] is False
    assert row["maker_fill_proven"] is False


def test_disappeared_quote_does_not_fill():
    result = confirmed()
    result.ingest("book", book(START + 71), START + 71)
    result.ingest("book", book(START + 71.3, no_asks=[[.98, 10]]), START + 71.3)
    scenarios = result.locks["kalshi:HIGH"]["scenarios"]
    assert scenarios["0.97"]["status"] == "quote_disappeared_after_delay"
    assert "entry_price" not in scenarios["0.98"]  # price moved above original97c intent


@pytest.mark.parametrize("changes", [{"received_at": START + 65}, {"exchange_at": START + 65},
    {"exchange_at": START + 75}, {"exchange_at": None}, {"complete": False},
    {"valid": False}, {"no_bids": [[.98, 10]]},
    {"source": "rest", "requested_at": START + 65}])
def test_invalid_stale_future_or_crossed_book_is_not_assessed(changes):
    result = confirmed()
    result.ingest("book", book(START + 71, **changes), START + 71)
    assert "assessed_at" not in result.locks["kalshi:HIGH"]["scenarios"]["0.97"]


def test_observed_small_size_cannot_create_one_contract():
    result = confirmed()
    result.ingest("book", book(START + 71, no_asks=[[.97, .5]]), START + 71)
    row = result.locks["kalshi:HIGH"]["scenarios"]["0.97"]
    assert row["depth_at_threshold"] == .5
    assert row["status"] == "no_single_level_contract_at_assessment"


def test_exit_needs_bid_persistence_and_taker_fee_not_fictional_maker_fill():
    result = confirmed()
    row = enter(result)
    result.ingest("book", book(START + 72, no_bids=[[.99, 10]], no_asks=[[.995, 10]]), START + 72)
    assert "exit_price" not in row
    result.ingest("book", book(START + 72.3, no_bids=[[.99, 10]], no_asks=[[.995, 10]]), START + 72.3)
    assert row["exit_price"] == .99
    assert row["exit_fee_usd"] == .0007
    assert row["conditional_exit_pnl_usd"] == .0172
    assert "not_resting_fill" in row["exit_method"]


def test_actual_settlement_drives_hold_and_disagreement_with_proxy():
    result = confirmed()
    row = enter(result)
    for bad in ({"result": "no", "final": False}, {"result": "no", "venue": "polymarket_us"}):
        result.ingest("settlement", {"market_id": "kalshi:HIGH", "venue": "kalshi",
            "final": True, **bad}, START + 75)
        assert "conditional_hold_pnl_usd" not in row
    result.ingest("settlement", {"market_id": "kalshi:HIGH", "venue": "kalshi",
        "result": "yes", "final": True}, START + 80)
    assert row["conditional_hold_pnl_usd"] == -.9721
    assert result.summary(START + 80)["today"]["settlement_disagreements"] == ["kalshi:HIGH"]
    result.ingest("settlement", {"market_id": "kalshi:HIGH", "venue": "kalshi",
        "result": "no", "final": True}, START + 81)
    assert "conditional_hold_pnl_usd" not in row
    assert result.locks["kalshi:HIGH"]["settlement_conflict"] is True


def test_cli_disagreement_separate_from_venue_settlement_and_ignores_wrong_station():
    result = confirmed()
    report = {"date": "2026-10-13", "station": "KLGA", "high_f": 60,
              "final": True, "quality": "accepted"}
    result.ingest("cli", report, START + 80)
    assert result.summary(START + 80)["today"]["cli_disagreements"] == []
    result.ingest("cli", {**report, "station": "KNYC"}, START + 81)
    assert result.summary(START + 81)["today"]["cli_disagreements"] == ["kalshi:HIGH"]
    assert "settlement_result" not in result.locks["kalshi:HIGH"]


def test_overlap_scenarios_separate_and_no_cents_per_day_promised():
    result = confirmed()
    enter(result)
    result.ingest("settlement", {"market_id": "kalshi:HIGH", "venue": "kalshi",
        "result": "no", "final": True}, START + 80)
    summary = result.summary(START + 3 * 86400)
    day = next(iter(summary["reports"].values()))
    assert summary["qualified_cents_per_day"] is None
    assert summary["scenarios_overlap"] is True
    assert summary["actual_order_latency_s"] is None
    assert summary["real_orders"] is False
    scenarios = day["conditional_scenarios"]["kalshi"]
    assert scenarios["0.97"]["conditional_hold_pnl_usd"] == .0279
    assert scenarios["0.98"]["conditional_hold_pnl_usd"] == .0279
    assert "total_pnl" not in day
    assert scenarios["0.97"]["qualified_pnl_usd"] is None


def test_capture_repeats_original_timestamp_and_marks_stale_unknown():
    result = confirmed()
    result.ingest("book", book(START + 71), START + 71)
    samples = result.tick(START + 72)
    assert samples[0]["book"]["received_at"] == START + 71
    assert samples[0]["book_fresh"] is True
    assert result.tick(START + 72.5) == []
    stale = result.tick(START + 76)
    assert stale[0]["book_fresh"] is False
    assert result.locks["kalshi:HIGH"]["coverage_partial"] is True
    assert result.tick(START + 1000) == []


def test_gap_restart_and_clock_regression_never_replay_entry_quote():
    result = confirmed()
    result.ingest("book", book(START + 71), START + 71)
    result.ingest("gap", {"reason": "websocket sequence"}, START + 71.1)
    result.ingest("book", book(START + 71.4), START + 71.4)
    row = result.locks["kalshi:HIGH"]["scenarios"]["0.97"]
    assert row["status"] == "unknown_after_gap"
    assert "entry_price" not in row
    result.ingest("book", book(START + 69), START + 69)
    assert not result.books


def test_rain_complete_intervals_and_two_distinct_readings():
    result = model(kind="rain", cap=.01, floor=0)
    def rain(at, left, right, amount, **changes):
        return observation(at, valid=right, interval_start=left, interval_end=right,
            amount_lower=amount, amount_upper=amount, interval_complete=True, **changes)
    result.ingest("observation", rain(START + 3601, START, START + 3600, .02), START + 3601)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] is None
    result.ingest("observation", rain(START + 7201, START + 3600, START + 7200, .02), START + 7201)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] == START + 7201


@pytest.mark.parametrize("extra", [{"trace": True}, {"interval_complete": False},
    {"amount_lower": None}, {"interval_start": START - 3600}])
def test_trace_unknown_or_other_day_precipitation_cannot_lock(extra):
    result = model(kind="rain", cap=.01, floor=0)
    data = observation(START + 3601, valid=START + 3600, interval_start=START,
        interval_end=START + 3600, amount_lower=.02, amount_upper=.02,
        interval_complete=True)
    result.ingest("observation", {**data, **extra}, START + 3601)
    assert not result.locks


@pytest.mark.parametrize(("venue", "price", "expected"), [
    ("kalshi", .97, .0021), ("kalshi", .98, .0014), ("kalshi", .99, .0007),
    ("polymarket_us", .97, 0), ("polymarket_us", .5, .02),
    ("invalid", .97, None), ("kalshi", float("nan"), None), ("kalshi", 1, None),
])
def test_documented_one_fill_fee_precision(venue, price, expected):
    assert weather_fee(venue, price) == expected


def test_no_private_or_trading_imports():
    import ast
    from pathlib import Path

    import nightcrawler.weatherwatch_model as module
    tree = ast.parse(Path(module.__file__).read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(any(word in name for word in ("client", "live", "broker", "requests", "socket")) for name in imports)
    assert "order" not in {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


@pytest.mark.parametrize("changes", [
    {"exchange_at": START + 71.1},
    {"source": "rest", "requested_at": START + 71.1},
])
def test_post_delay_receipt_with_pre_delay_source_evidence_cannot_fill(changes):
    result = confirmed()
    result.ingest("book", book(START + 71), START + 71)
    result.ingest("book", book(START + 71.5, **changes), START + 71.5)
    assert "entry_price" not in result.locks["kalshi:HIGH"]["scenarios"]["0.97"]


@pytest.mark.parametrize("changes", [{"fee_verified": False}, {"fee_multiplier": 2},
                                      {"fee_type": "unknown"}, {"fee_precision": .01}])
def test_unknown_or_changed_fee_schedule_prevents_counterfactual_entry(changes):
    result = confirmed(**changes)
    row = enter(result)
    assert row["status"] == "unknown_fee"
    assert "entry_price" not in row


def test_rejected_capture_cannot_report_quote_entry_from_unwatched_socket():
    result = confirmed()
    result.ingest("weather_watch_rejected", {"market_id": "kalshi:HIGH", "reason": "capacity"}, START + 70)
    row = enter(result)
    assert row["status"] == "unknown_watch_rejected"
    assert "entry_price" not in row
    assert result.locks["kalshi:HIGH"]["watch_rejected"] == "capacity"


def test_rain_yes_uses_yes_quotes_and_actual_yes_settlement():
    result = model(kind="rain", strike_type="greater", floor=.01, cap=None)
    for hour, amount in ((1, .02), (2, .02)):
        at = START + hour * 3600
        data = observation(at + 1, valid=at, interval_start=at - 3600, interval_end=at,
                           amount_lower=amount, amount_upper=amount, interval_complete=True)
        result.ingest("weather_observation", data, at + 1)
    lock = result.locks["kalshi:HIGH"]
    assert lock["side"] == "yes"
    for at in (START + 7202, START + 7202.3):
        result.ingest("weather_book", book(at, no_asks=[[.03, 10]], no_bids=[[.01, 10]],
            yes_asks=[[.97, 10]], yes_bids=[[.95, 10]]), at)
    row = lock["scenarios"]["0.97"]
    assert row["entry_price"] == .97
    assert row["side"] == "yes"
    result.ingest("weather_settlement", {"market_id": "kalshi:HIGH", "venue": "kalshi",
        "result": "yes", "final": True}, START + 8000)
    assert row["conditional_hold_pnl_usd"] == .0279
    assert result.summary(START + 8000)["today"]["settlement_disagreements"] == []


def test_explicit_exclusive_and_inclusive_bounds_override_defaults():
    assert observation_kills(market(cap_inclusive=False), {"lower_f": 61, "upper_f": 61.1})
    assert not observation_kills(market(strike_type="less", cap_inclusive=True),
                                 {"lower_f": 61, "upper_f": 61.1})
    assert observation_kills(market(kind="low", floor_inclusive=False), {"lower_f": 59.9, "upper_f": 60})
    assert not observation_kills(market(kind="low", strike_type="greater", floor_inclusive=True),
                                 {"lower_f": 59.9, "upper_f": 60})


def test_cli_adapter_aliases_and_trace_do_not_invent_comparisons():
    result = confirmed()
    result.ingest("weather_cli", {"climate_day": "2026-10-13", "station": "KNYC",
        "maximum_f": 60, "final_report": True, "quality": "accepted", "report_id": "daily1"}, START + 80)
    report = result.summary(START + 80)["today"]
    assert report["cli_reports"] == 1
    assert report["cli_comparisons"] == 1
    assert report["cli_disagreements"] == ["kalshi:HIGH"]


def test_trade_reconnect_duplicates_are_not_counted_twice():
    result = confirmed()
    for at in (START + 80, START + 81):
        result.ingest("weather_trade", {"market_id": "kalshi:HIGH", "venue": "kalshi", "trade_id": "x"}, at)
    assert result.summary(START + 81)["today"]["trade_prints"] == 1


def test_post_bootstrap_latency_excludes_initial_cached_reading():
    result = model()
    result.ingest("observation", observation(START + 100, valid=START + 1), START + 100)
    result.ingest("observation", observation(START + 110, valid=START + 107), START + 110)
    source = result.summary(START + 110)["today"]["sources"]["nws"]
    assert source["readings"] == 2
    assert source["bootstrap_readings"] == 1
    assert source["bootstrap_median_s"] == 99
    assert source["median"] == 3
    assert source["latency_samples"] == 1


def test_void_settlement_remains_unknown_without_actual_refund_evidence():
    result = confirmed()
    row = enter(result)
    result.ingest("weather_settlement", {"market_id": "kalshi:HIGH", "venue": "kalshi",
        "result": "void", "final": True}, START + 80)
    assert result.locks["kalshi:HIGH"]["settlement_result"] == "void"
    assert "conditional_hold_pnl_usd" not in row


def test_healthy_discovery_and_websocket_status_preserve_confirmation():
    result = model()
    result.ingest("observation", observation(START + 10), START + 10)
    result.ingest("weather_venue_status", {"venue": "kalshi", "kind": "discovery", "all_series_checked": True}, START + 11)
    result.ingest("weather_venue_status", {"venue": "kalshi", "ws_connected": True, "ws_status": "market_websocket"}, START + 12)
    result.ingest("observation", observation(START + 70), START + 70)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] == START + 70


def test_unavailable_unrelated_source_does_not_destroy_other_books():
    result = confirmed()
    result.ingest("book", book(START + 71), START + 71)
    result.ingest("weather_source_status", {"source": "asos_1minute", "status": "unavailable"}, START + 71.1)
    result.ingest("book", book(START + 71.3), START + 71.3)
    assert result.locks["kalshi:HIGH"]["scenarios"]["0.97"]["entry_price"] == .97


def test_qc_revision_preserves_firstseen_latency_but_revokes_future_assessments():
    result = model()
    initial = observation(START + 10, revision_id="accepted")
    result.ingest("observation", initial, START + 10)
    result.ingest("observation", observation(START + 70), START + 70)
    revised = {**initial, "received_at": START + 70.5, "revision_id": "suspect", "quality": "suspect"}
    result.ingest("observation", revised, START + 70.5)
    row = enter(result)
    assert "entry_price" not in row
    assert row["signal_revoked"] is True
    assert result.locks["kalshi:HIGH"]["classification"] == "revoked_observation_proxy"
    assert result.locks["kalshi:HIGH"]["first_candidate_at"] == START + 10
    assert result.summary(START + 72)["today"]["sources"]["nws"]["readings"] == 2


def test_runtime_restart_payload_invalidates_all_market_books_and_chains():
    result = model()
    result.ingest("observation", observation(START + 10), START + 10)
    result.ingest("book", book(START + 11), START + 11)
    result.ingest("weather_gap", {"source": "runtime", "reason": "restart"}, START + 12)
    assert not result.books
    assert result.locks["kalshi:HIGH"]["last_valid_at"] is None
    assert result.restarts == 1
    result.ingest("observation", observation(START + 70), START + 70)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] is None


def test_market_scoped_gap_does_not_invalidate_unrelated_candidate():
    result = model()
    result.ingest("market", market(market_id="kalshi:OTHER", cap=60), START)
    result.ingest("observation", observation(START + 10), START + 10)
    result.ingest("weather_gap", {"market_id": "kalshi:OTHER", "reason": "capacity"}, START + 11)
    assert result.locks["kalshi:HIGH"]["last_valid_at"] == START + 9
    assert result.locks["kalshi:OTHER"]["last_valid_at"] is None


def test_explicit_unsupported_market_never_becomes_candidate():
    result = model(supported=False, unsupported_reason="rule_date_mismatch")
    result.ingest("observation", observation(START + 10), START + 10)
    assert not result.locks


def test_integer_f_observation_proxy_uses_conservative_rounded_bounds():
    less = market(strike_type="less", cap=68, cap_inclusive=True, temperature_precision="integer_f_proxy")
    assert not observation_kills(less, {"lower_f": 68.3, "upper_f": 68.5})
    assert observation_kills(less, {"lower_f": 68.6, "upper_f": 68.8})
    greater = market(kind="low", strike_type="greater", floor=68, floor_inclusive=True,
                     temperature_precision="integer_f_proxy")
    assert not observation_kills(greater, {"lower_f": 67.5, "upper_f": 67.7})
    assert observation_kills(greater, {"lower_f": 67.2, "upper_f": 67.4})


def test_same_cli_product_corrected_content_is_compared_again():
    result = confirmed()
    report = {"climate_day": "2026-10-13", "station": "KNYC", "maximum_f": 62,
        "final_report": True, "quality": "accepted", "report_id": "daily1", "revision_id": "version1"}
    result.ingest("weather_cli", report, START + 80)
    assert not result.summary(START + 80)["today"]["cli_disagreements"]
    result.ingest("weather_cli", {**report, "maximum_f": 60, "revision_id": "version2"}, START + 81)
    day = result.summary(START + 81)["today"]
    assert day["cli_disagreements"] == ["kalshi:HIGH"]
    assert day["cli_reports"] == 2
    assert day["cli_comparisons"] == 1


def test_rule_station_change_does_not_combine_two_different_stations():
    result = model()
    result.ingest("observation", observation(START + 10), START + 10)
    result.ingest("weather_market", market(station="KMDW"), START + 11)
    result.ingest("observation", observation(START + 70, station="KMDW"), START + 70)
    row = enter(result)
    assert "entry_price" not in row
    assert result.locks["kalshi:HIGH"]["assessment_blocked_reason"] == "market_rules_changed"


def test_real_metar_53_minute_cadence_uses_in_day_interval_lower_bound():
    result = model(kind="rain", strike_type="greater", floor=0, cap=None)
    # 00:53 accumulation includes yesterday and cannot establish today's rain.
    for valid in (START + 53 * 60, START + 113 * 60, START + 173 * 60):
        data = observation(valid + 10, valid=valid, interval_start=valid - 3600,
            interval_end=valid, amount_lower=.005, amount_upper=.015, interval_complete=True)
        result.ingest("observation", data, valid + 10)
        if valid == START + 53 * 60:
            assert not result.locks
    lock = result.locks["kalshi:HIGH"]
    assert lock["confirmed_at"] == START + 173 * 60 + 10
    assert lock["side"] == "yes"
    assert lock["rain_day_total_known"] is False
    assert lock["rain_lower_bound_method"] == "maximum_single_complete_in_day_interval"


def test_overlapping_rain_intervals_are_not_summed_to_cross_threshold():
    result = model(kind="rain", strike_type="greater", floor=.015, cap=None)
    for valid in (START + 4000, START + 4060):
        data = observation(valid + 1, valid=valid, interval_start=valid - 3600,
            interval_end=valid, amount_lower=.01, amount_upper=.01, interval_complete=True)
        result.ingest("observation", data, valid + 1)
    assert not result.locks


def test_dry_interval_does_not_supply_second_rain_confirmation():
    result = model(kind="rain", strike_type="greater", floor=0, cap=None)
    for valid, amount in ((START + 4000, .01), (START + 7600, 0)):
        data = observation(valid + 1, valid=valid, interval_start=valid - 3600,
            interval_end=valid, amount_lower=amount, amount_upper=amount, interval_complete=True)
        result.ingest("observation", data, valid + 1)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] is None


@pytest.mark.parametrize("batch_flag", ["left_censored", "initial_snapshot"])
def test_every_initial_madis_lookback_row_is_censored_from_live_arrival_latency(batch_flag):
    result = model()
    for index, valid in enumerate((START + 60, START + 360, START + 660)):
        received = START + 1000 + index * .01
        data = observation(received, source="madis_hfm", valid=valid,
            resolution_s=300, independent_1m=False, **{batch_flag: True})
        result.ingest("weather_observation", data, received + .001)
    source = result.summary(START + 1001)["today"]["sources"]["madis_hfm"]
    assert source["readings"] == 3
    assert source["bootstrap_readings"] == 3
    assert source["latency_samples"] == 0
    assert source["median"] is None
    assert source["p95"] is None
    lock = result.locks["kalshi:HIGH"]
    assert lock["left_censored_initial_reading"] is True
    assert lock["first_candidate_at"] == START + 1000
    assert lock["first_valid_at"] == START + 60
    assert lock["confirmed_at"] == START + 1000.011
    assert lock["classification"] == "confirmed_observation_proxy"
    # A later record first observed after bootstrap contributes a real receipt
    # lag, still not a claim about its original public publication timestamp.
    result.ingest("weather_observation", observation(START + 1202, source="madis_hfm",
        valid=START + 1200, resolution_s=300, independent_1m=False), START + 1202)
    source = result.summary(START + 1202)["today"]["sources"]["madis_hfm"]
    assert source["readings"] == 4
    assert source["bootstrap_readings"] == 3
    assert source["latency_samples"] == 1
    assert source["median"] == 2


def test_madis_five_minute_record_is_not_independent_one_minute_confirmation():
    result = model()
    result.ingest("weather_observation", observation(START + 10, valid=START + 9), START + 10)
    result.ingest("weather_observation", observation(START + 11, source="madis_hfm",
        valid=START + 9, independent_id="madis:five-minute:9", resolution_s=300,
        independent_1m=False), START + 11)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] is None


def test_temperature_only_madis_does_not_interrupt_hourly_wet_rain_chain():
    result = model(kind="rain", strike_type="greater", floor=0, cap=None)
    first_valid = START + 6780
    def wet(valid):
        return observation(valid + 1, valid=valid, interval_start=valid - 3600,
            interval_end=valid, amount_lower=.005, amount_upper=.015, interval_complete=True,
            precipitation_status="measured", precipitation_quality="accepted")
    result.ingest("weather_observation", wet(first_valid), first_valid + 1)
    for valid in range(int(first_valid + 300), int(first_valid + 3600), 300):
        result.ingest("weather_observation", observation(valid + 1, source="madis_hfm", valid=valid,
            resolution_s=300, independent_1m=False, precipitation_status="not_requested",
            interval_complete=False, precipitation_quality="unknown", quality="suspect"), valid + 1)
    lock = result.locks["kalshi:HIGH"]
    assert lock["last_valid_at"] == first_valid
    assert lock["confirmed_at"] is None
    result.ingest("weather_observation", wet(first_valid + 3600), first_valid + 3601)
    assert lock["confirmed_at"] == first_valid + 3601
    assert lock["side"] == "yes"


@pytest.mark.parametrize("changes", [
    {"precipitation_status": "missing", "interval_complete": False},
    {"precipitation_status": "measured", "precipitation_quality": "suspect"},
    {"precipitation_status": "trace", "trace": True},
])
def test_actual_missing_or_suspect_rain_reading_breaks_confirmation_chain(changes):
    result = model(kind="rain", strike_type="greater", floor=0, cap=None)
    for valid, extra in ((START + 6780, {}), (START + 7080, changes), (START + 10380, {})):
        data = observation(valid + 1, valid=valid, interval_start=valid - 3600,
            interval_end=valid, amount_lower=.005, amount_upper=.015, interval_complete=True,
            precipitation_status="measured", precipitation_quality="accepted")
        result.ingest("weather_observation", {**data, **extra}, valid + 1)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] is None


def test_explicit_rain_only_record_does_not_break_temperature_confirmation():
    result = model()
    result.ingest("weather_observation", observation(START + 10), START + 10)
    result.ingest("weather_observation", observation(START + 20, source="rain_only",
        temperature_status="not_requested", lower_f=None, upper_f=None, quality="unknown"), START + 20)
    result.ingest("weather_observation", observation(START + 70), START + 70)
    assert result.locks["kalshi:HIGH"]["confirmed_at"] == START + 70


@pytest.mark.parametrize("source", ["nws", "madis_hfm"])
@pytest.mark.parametrize("failed_stations", [["KNYC"], ["KNYC", "KMDW"]])
def test_adapter_station_array_failure_only_invalidates_affected_cities(source, failed_stations):
    result = WeatherwatchModel(START)
    stations = ("KNYC", "KMDW", "KMIA")
    for station in stations:
        identity = f"kalshi:{station}"
        result.ingest("weather_market", market(market_id=identity, station=station), START)
    for station in stations:
        result.ingest("weather_observation", observation(START + 10, source=source, station=station), START + 10)
        result.ingest("weather_book", book(START + 10, market_id=f"kalshi:{station}"), START + 10)
    result.ingest("weather_source_status", {"source": source, "status": "error",
        "stations": failed_stations, "reason": "public_request_failed", "received_at": START + 11}, START + 11)
    for station in stations:
        identity = f"kalshi:{station}"
        if station in failed_stations:
            assert result.locks[identity]["last_valid_at"] is None
            assert identity not in result.books
        else:
            assert result.locks[identity]["last_valid_at"] == START + 9
            assert identity in result.books
    for station in stations:
        result.ingest("weather_observation", observation(START + 70, source=source, station=station), START + 70)
        assert (result.locks[f"kalshi:{station}"]["confirmed_at"] is not None) == (station not in failed_stations)

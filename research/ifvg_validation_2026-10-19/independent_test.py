"""Independent, specification-derived synthetic checks; no historical price reads."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import run_study
from simulator import Bar, simulate_day

NY = ZoneInfo("America/New_York")
DAY = date(2026, 6, 15)


def stamp(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY).astimezone(
        UTC
    )


def fixture(day=DAY):
    """Reference bounds 90/110; deliberately flat observed prices around 100."""
    rows = {}
    for start, end, high, low in [
        (stamp(20, day=day - timedelta(days=1)), stamp(0, day=day), 110, 90),
        (stamp(2, day=day), stamp(5, day=day), 110, 90),
        (stamp(9, 18, day=day), stamp(11, 31, day=day), 100, 100),
    ]:
        while start < end:
            rows[start] = Bar(start, 100, high, low, 100)
            start += timedelta(minutes=1)
    return rows


def put(rows, hour, minute, o, h, low, c, day=DAY):
    t = stamp(hour, minute, day)
    rows[t] = Bar(t, o, h, low, c)


def short_setup(day=DAY):
    rows = fixture(day)
    put(rows, 9, 27, 98, 99, 97, 98, day)
    put(rows, 9, 28, 102, 104, 98, 102, day)
    put(rows, 9, 29, 104, 106, 103, 105, day)
    put(rows, 9, 30, 105, 111, 98, 98, day)
    return rows


def run(rows, day=DAY, fee=Decimal("1.00"), friction=1, **kw):
    return simulate_day(
        list(rows.values()), day, fee_per_side=fee, friction_ticks=friction, **kw
    )


def trade(result):
    assert result["decision"] == "TRADE", result
    assert result["trade"] is not None, result
    return result["trade"]


def utc_text_equal(actual, expected):
    assert datetime.fromisoformat(actual) == expected


def test_self_confirm_enters_next_open_and_exact_net_accounting():
    t = trade(run(short_setup()))
    utc_text_equal(t["entry_timestamp"], stamp(9, 31))
    assert (t["direction"], t["entry_ticks"], t["stop_ticks"], t["target_ticks"]) == (
        "SHORT", 99, 112, 73
    )
    assert (t["exit_ticks"], t["exit_reason"], t["gross_ticks"]) == (101, "TIME", -2)
    assert Decimal(t["gross_usd"]) == -1
    assert Decimal(t["fees_usd"]) == 2
    assert Decimal(t["net_usd"]) == -3


def test_reflection_preserves_long_short_pnl():
    rows = short_setup()
    reflected = {
        ts: Bar(ts, 200 - b.open, 200 - b.low, 200 - b.high, 200 - b.close)
        for ts, b in rows.items()
    }
    short = trade(run(rows))
    long = trade(run(reflected))
    assert long["direction"] == "LONG"
    assert (long["entry_ticks"], long["stop_ticks"], long["target_ticks"]) == (101, 88, 127)
    assert short["net_usd"] == long["net_usd"]


@pytest.mark.parametrize("fee", [Decimal("0.50"), Decimal("1.00"), Decimal("1.50")])
@pytest.mark.parametrize("friction", [1, 2, 4])
def test_all_nine_friction_fee_scenarios_have_exact_accounting(fee, friction):
    t = trade(run(short_setup(), fee=fee, friction=friction))
    assert t["entry_ticks"] == 100 - friction
    assert t["exit_ticks"] == 100 + friction
    assert Decimal(t["net_usd"]) == -Decimal(friction) - 2 * fee


def test_integer_fee_means_cents():
    assert run(short_setup(), fee=100) == run(short_setup(), fee=Decimal("1.00"))


def test_target_touch_is_not_fill_but_trade_through_is():
    touched = short_setup()
    put(touched, 9, 32, 100, 100, 73, 100)
    assert trade(run(touched))["exit_reason"] == "TIME"
    put(touched, 9, 32, 100, 100, 72, 100)
    t = trade(run(touched))
    assert (t["exit_reason"], t["exit_ticks"], t["gross_ticks"]) == ("TARGET", 73, 26)
    assert Decimal(t["net_usd"]) == 11


def test_opening_target_fills_before_subsequent_stop_extreme():
    rows = short_setup()
    put(rows, 9, 32, 72, 120, 70, 100)
    t = trade(run(rows))
    assert (t["exit_reason"], t["exit_ticks"], t["ambiguous"]) == ("TARGET", 73, False)


def test_opening_stop_gap_uses_worse_open_plus_friction():
    rows = short_setup()
    put(rows, 9, 32, 120, 125, 70, 100)
    t = trade(run(rows))
    assert (t["exit_reason"], t["exit_ticks"], t["ambiguous"]) == ("STOP", 121, False)
    assert Decimal(t["net_usd"]) == -13


def test_intrabar_both_exits_are_stop_first_and_ambiguous():
    rows = short_setup()
    put(rows, 9, 32, 100, 112, 72, 100)
    t = trade(run(rows))
    assert (t["exit_reason"], t["exit_ticks"], t["ambiguous"]) == ("STOP", 113, True)


@pytest.mark.parametrize("opening,expected_reason,expected_ticks", [
    (100, "TIME", 101), (112, "STOP", 113), (72, "TARGET", 73), (73, "TIME", 74)
])
def test_time_exit_open_precedence_ignores_later_extrema(opening, expected_reason, expected_ticks):
    rows = short_setup()
    put(rows, 11, 30, opening, 125, 70, 100)
    t = trade(run(rows))
    assert (t["exit_reason"], t["exit_ticks"]) == (expected_reason, expected_ticks)
    assert not t["ambiguous"]


def test_entry_bar_extrema_can_exit_but_confirmation_extrema_cannot():
    rows = short_setup()
    # Sweep high is necessarily below the frozen stop; low may cross the eventual target.
    put(rows, 9, 30, 105, 111, 90, 98)
    put(rows, 9, 31, 100, 112, 100, 100)
    t = trade(run(rows))
    assert t["exit_reason"] == "STOP"
    utc_text_equal(t["exit_timestamp"], stamp(9, 31))


def test_entry_at_stop_is_rejected_without_trade():
    rows = short_setup()
    put(rows, 9, 31, 112, 112, 100, 100)
    result = run(rows)
    assert result["decision"] == "REJECTED", result
    assert result["trade"] is None


def test_first_attempt_without_gap_prevents_later_valid_attempt():
    rows = fixture()
    put(rows, 9, 30, 100, 111, 100, 100)
    put(rows, 9, 37, 98, 99, 97, 98)
    put(rows, 9, 38, 102, 104, 98, 102)
    put(rows, 9, 39, 104, 106, 103, 105)
    put(rows, 9, 40, 105, 111, 98, 98)
    result = run(rows)
    assert result["decision"] == "REJECTED", result
    assert result["trade"] is None


def test_both_sweep_directions_reject_even_when_gap_inverts():
    rows = short_setup()
    put(rows, 9, 30, 105, 111, 89, 98)
    result = run(rows)
    assert result["decision"] == "REJECTED", result
    assert result["trade"] is None


@pytest.mark.parametrize("removed", [(20, 0, -1), (2, 0, 0), (9, 18, 0), (9, 30, 0),
                                     (9, 31, 0), (9, 32, 0), (11, 30, 0)])
def test_required_holes_never_become_zero_or_closed_result(removed):
    rows = short_setup()
    hour, minute, offset = removed
    del rows[stamp(hour, minute, DAY + timedelta(days=offset))]
    result = run(rows)
    assert result["decision"] == "UNRESOLVED", result
    assert result["net_usd"] is None


def test_missing_post_exit_bar_does_not_erase_known_loss():
    rows = short_setup()
    put(rows, 9, 32, 120, 125, 100, 100)
    del rows[stamp(9, 33)]
    t = trade(run(rows))
    assert t["exit_reason"] == "STOP"
    assert Decimal(t["net_usd"]) == -13


def test_missing_observation_before_later_sweep_is_unresolved():
    rows = fixture()
    del rows[stamp(9, 31)]
    put(rows, 9, 37, 98, 99, 97, 98)
    put(rows, 9, 38, 102, 104, 98, 102)
    put(rows, 9, 39, 104, 106, 103, 105)
    put(rows, 9, 40, 105, 111, 98, 98)
    result = run(rows)
    assert result["decision"] == "UNRESOLVED", result
    assert result["net_usd"] is None


def test_no_trade_requires_complete_observation_only():
    rows = fixture()
    del rows[stamp(11, 30)]
    assert run(rows)["decision"] == "NO_TRADE"
    del rows[stamp(10, 30)]
    assert run(rows)["decision"] == "UNRESOLVED"


@pytest.mark.parametrize("day,utc_hour", [(date(2026, 3, 6), 14), (date(2026, 3, 9), 13),
                                         (date(2026, 10, 30), 13), (date(2026, 11, 2), 14)])
def test_new_york_dst_and_sunday_reference(day, utc_hour):
    t = trade(run(short_setup(day), day=day))
    expected = datetime(day.year, day.month, day.day, utc_hour, 31, tzinfo=UTC)
    utc_text_equal(t["entry_timestamp"], expected)


def test_epoch_minutes_are_same_bars():
    rows = short_setup()
    epochs = {
        ts: Bar(int(ts.timestamp()) // 60, b.open, b.high, b.low, b.close)
        for ts, b in rows.items()
    }
    assert run(rows) == run(epochs)


def test_newest_inverted_gap_is_filtered_before_older_valid_gap_selection():
    rows = fixture()
    for minute, o, h, low, c in [
        (22, 94, 95, 93, 94), (23, 97, 100, 94, 98), (24, 101, 105, 99, 101),
        (25, 102, 105, 99, 102), (26, 104, 108, 99, 104), (27, 108, 109, 107, 108),
        (28, 104, 108, 104, 104), (29, 104, 106, 100, 104), (30, 105, 111, 94, 94),
    ]:
        put(rows, 9, minute, o, h, low, c)
    result = run(rows)
    trade(result)
    gap = result["attempt"]["gap"]
    assert (gap["lower_ticks"], gap["upper_ticks"]) == (95, 99)
    utc_text_equal(gap["c_timestamp"], stamp(9, 24))


def test_first_inversion_after_equal_boundary_close_is_used():
    rows = short_setup()
    put(rows, 9, 30, 105, 111, 98, 100)
    put(rows, 9, 31, 100, 110, 98, 99)
    put(rows, 9, 32, 100, 115, 98, 98)
    result = run(rows)
    t = trade(result)
    utc_text_equal(result["attempt"]["confirmation_timestamp"], stamp(9, 32))
    utc_text_equal(t["entry_timestamp"], stamp(9, 33))
    assert t["stop_ticks"] == 116


@pytest.mark.parametrize("offset,decision", [(10, "TRADE"), (11, "REJECTED")])
def test_tenth_confirmation_included_and_eleventh_excluded(offset, decision):
    rows = short_setup()
    put(rows, 9, 30, 105, 111, 98, 100)
    put(rows, 9, 30 + offset, 100, 100, 98, 98)
    result = run(rows)
    assert result["decision"] == decision, result
    if decision == "TRADE":
        utc_text_equal(result["trade"]["entry_timestamp"], stamp(9, 41))


def test_opposite_sweep_rejection_precedes_simultaneous_confirmation():
    rows = short_setup()
    put(rows, 9, 30, 105, 111, 98, 100)
    put(rows, 9, 31, 100, 100, 89, 98)
    result = run(rows)
    assert result["decision"] == "REJECTED", result
    assert result["reason"] == "OPPOSITE_SWEEP"
    assert result["trade"] is None


def test_missing_intervening_confirmation_slot_is_unresolved():
    rows = short_setup()
    put(rows, 9, 30, 105, 111, 98, 100)
    del rows[stamp(9, 31)]
    put(rows, 9, 32, 100, 100, 98, 98)
    result = run(rows)
    assert result["decision"] == "UNRESOLVED", result
    assert result["net_usd"] is None


@pytest.mark.parametrize("age,decision", [(10, "TRADE"), (11, "REJECTED")])
def test_gap_age_is_scheduled_slots_and_ten_is_inclusive(age, decision):
    rows = fixture()
    # Extend exactly the two older bars needed by the 11-slot fixture.
    c_minute = 30 - age
    put(rows, 9, c_minute - 2, 94, 95, 93, 94)
    put(rows, 9, c_minute - 1, 98, 101, 94, 98)
    put(rows, 9, c_minute, 100, 101, 99, 100)
    put(rows, 9, 30, 100, 111, 94, 94)
    result = run(rows)
    assert result["decision"] == decision, result
    if decision == "TRADE":
        utc_text_equal(result["attempt"]["gap"]["c_timestamp"], stamp(9, c_minute))


@pytest.mark.parametrize("minute,decision", [(58, "TRADE"), (59, "REJECTED")])
def test_entry_must_be_strictly_before_eleven(minute, decision):
    rows = fixture()
    put(rows, 10, minute - 3, 98, 99, 97, 98)
    put(rows, 10, minute - 2, 102, 104, 98, 102)
    put(rows, 10, minute - 1, 104, 106, 103, 105)
    put(rows, 10, minute, 105, 111, 98, 98)
    result = run(rows)
    assert result["decision"] == decision, result
    if decision == "TRADE":
        utc_text_equal(result["trade"]["entry_timestamp"], stamp(10, 59))


def test_later_price_mutations_cannot_change_closed_trade():
    rows = short_setup()
    put(rows, 9, 32, 100, 112, 100, 100)
    first = run(rows)
    for ts in list(rows):
        if ts > stamp(9, 32):
            rows[ts] = Bar(ts, 200, 300, 50, 150)
    assert first == run(rows)


@pytest.mark.parametrize("status,decision", [
    ("CLOSED", "EXCLUDED"), ("SHORTENED", "EXCLUDED"),
    ("UNKNOWN", "UNRESOLVED"), ("INCOMPLETE", "UNRESOLVED"),
])
def test_calendar_attestation_never_invented_from_weekday(status, decision):
    result = run({}, calendar_status=status)
    assert result["decision"] == decision
    if decision == "UNRESOLVED":
        assert result["net_usd"] is None


def test_duplicate_minutes_are_not_silently_overwritten():
    rows = list(short_setup().values())
    with pytest.raises(ValueError, match="duplicate"):
        simulate_day(rows + [rows[0]], DAY, Decimal("1.00"), 1)


@pytest.mark.parametrize("opening,high,expected_basis,interval_end", [
    (100, 112, "INTRABAR_INTERVAL", stamp(9, 33)),
    (120, 125, "OPEN", None),
])
def test_exit_time_metadata_does_not_claim_exact_intrabar_execution(
    opening, high, expected_basis, interval_end
):
    rows = short_setup()
    put(rows, 9, 32, opening, high, 100, 100)
    t = trade(run(rows))
    utc_text_equal(t["exit_timestamp"], stamp(9, 32))
    assert t["exit_time_basis"] == expected_basis
    if interval_end is None:
        assert t["exit_interval_end"] is None
    else:
        utc_text_equal(t["exit_interval_end"], interval_end)


def test_runner_summary_drawdown_loss_runs_and_profit_concentration():
    outcomes = [Decimal(90), Decimal(-100), Decimal(-5), Decimal(20)]
    days = [
        {"session_date": str(index), "decision": "TRADE", "net_usd": str(net),
         "trade": {"net_usd": str(net), "gross_usd": str(net + 2), "fees_usd": "2",
                   "risk_ticks": 10, "ambiguous": index == 1}}
        for index, net in enumerate(outcomes)
    ]
    summary = run_study.summarize(days)
    assert summary["period_trading_net_usd"] == "5.00"
    assert summary["known_closed_gross_after_friction_usd"] == "13.00"
    assert summary["known_closed_fees_usd"] == "8.00"
    assert summary["session_end_max_drawdown_usd"] == "105.00"
    assert summary["net_without_best_day_usd"] == "-85.00"
    assert summary["longest_known_closed_loss_streak"] == 2
    assert summary["ambiguous_closed_trades"] == 1


def test_runner_refuses_existing_output_before_reading_any_input(tmp_path):
    output = tmp_path / "result.json"
    output.write_text("preserved previous result")
    with pytest.raises(ValueError, match="overwrite"):
        run_study.run(tmp_path / "no-data", tmp_path / "no-manifest", output)
    assert output.read_text() == "preserved previous result"


def test_runner_rejects_unqualified_manifest_before_data_access(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="frozen exploratory protocol"):
        run_study.run(tmp_path / "no-data", manifest, tmp_path / "output.json")
    assert not (tmp_path / "output.json").exists()


def test_runner_requires_all_frozen_source_hashes_before_data_access(tmp_path):
    import json

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "study_kind": run_study.KIND, "data_sha256": run_study.CSV_SHA,
        "early_dates": run_study.EARLY, "later_dates": run_study.LATER,
        "actual_contract_verified": False, "actual_costs_verified": False,
        "live_execution_enabled": False, "source_sha256": {},
    }))
    with pytest.raises(ValueError, match="incomplete frozen source manifest"):
        run_study.run(tmp_path / "no-data", manifest, tmp_path / "output.json")
    assert not (tmp_path / "output.json").exists()


def test_runner_changed_source_fails_before_data_access(tmp_path):
    import json

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "study_kind": run_study.KIND, "data_sha256": run_study.CSV_SHA,
        "early_dates": run_study.EARLY, "later_dates": run_study.LATER,
        "actual_contract_verified": False, "actual_costs_verified": False,
        "live_execution_enabled": False,
        "source_sha256": dict.fromkeys([
            "simulator.py", "run_study.py", "EVALUATION.md",
            "../ifvg_intake_2026-10-19/V1_RULES.md",
        ], "0" * 64),
    }))
    with pytest.raises(ValueError, match="source changed after freeze"):
        run_study.run(tmp_path / "no-data", manifest, tmp_path / "output.json")
    assert not (tmp_path / "output.json").exists()

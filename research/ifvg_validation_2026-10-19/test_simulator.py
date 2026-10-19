"""Synthetic regression fixtures only: no feed, broker, application or TEST data."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulator import COST_SCENARIOS, Bar, simulate_day

NY = ZoneInfo("America/New_York")
DAY = date(2026, 10, 19)
MINUTE = timedelta(minutes=1)


def stamp(clock: str, day: date = DAY) -> datetime:
    hour, minute = map(int, clock.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def fixture(day: date = DAY, signal: bool = True) -> dict[datetime, Bar]:
    data = {}
    intervals = [
        (stamp("20:00", day - timedelta(days=1)), stamp("00:00", day), True),
        (stamp("02:00", day), stamp("05:00", day), True),
        (stamp("09:18", day), stamp("11:31", day), False),
    ]
    for start, end, reference in intervals:
        while start < end:
            data[start] = Bar(start, 100, 110 if reference else 105,
                              90 if reference else 95, 100)
            start += MINUTE
    if signal:
        put(data, "09:27", 100, 102, 98, 100, day)
        put(data, "09:28", 103, 104, 101, 103, day)
        put(data, "09:29", 105, 108, 104, 106, day)
        put(data, "09:30", 106, 112, 99, 101, day)
    return data


def put(data: dict, clock: str, open_: int, high: int, low: int, close: int,
        day: date = DAY) -> None:
    when = stamp(clock, day)
    data[when] = Bar(when, open_, high, low, close)


def mirror(data: dict[datetime, Bar]) -> dict[datetime, Bar]:
    return {when: Bar(when, 200 - bar.open, 200 - bar.low,
                     200 - bar.high, 200 - bar.close) for when, bar in data.items()}


def simulate(data: dict, **kwargs) -> dict:
    return simulate_day(data.values(), DAY, **kwargs)


class SimulationTests(unittest.TestCase):
    def test_short_and_long_stop_target_symmetry(self):
        for long in (False, True):
            for target in (False, True):
                with self.subTest(long=long, target=target):
                    data = fixture()
                    if target:
                        put(data, "09:32", 100, 101, 67, 70)
                    else:
                        put(data, "09:32", 100, 114, 95, 110)
                    result = simulate(mirror(data) if long else data)
                    trade = result["trade"]
                    self.assertEqual(result["decision"], "TRADE")
                    self.assertEqual(trade["direction"], "LONG" if long else "SHORT")
                    self.assertEqual(trade["entry_ticks"], 102 if long else 98)
                    self.assertEqual(trade["stop_ticks"], 87 if long else 113)
                    self.assertEqual(trade["target_ticks"], 132 if long else 68)
                    self.assertEqual(result["gross_usd"], "15.00" if target else "-8.50")
                    self.assertEqual(result["fees_usd"], "2.00")
                    self.assertEqual(result["net_usd"], "13.00" if target else "-10.50")

    def test_no_sweep_requires_all_observation_but_no_outcomes(self):
        data = fixture(signal=False)
        data = {when: bar for when, bar in data.items() if when < stamp("11:00")}
        result = simulate(data)
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertEqual(result["coverage"]["phases"]["observation"]["required_count"], 90)
        self.assertEqual(result["net_usd"], "0.00")

    def test_touches_do_not_sweep_and_equal_reference_close_reclaims(self):
        data = fixture(signal=False)
        put(data, "09:30", 100, 110, 90, 100)
        self.assertEqual(simulate(data)["decision"], "NO_TRADE")
        data = fixture()
        put(data, "09:30", 106, 112, 100, 110)
        put(data, "09:31", 100, 105, 95, 101)
        result = simulate(data)
        self.assertEqual(result["attempt"]["sweep_timestamp"], iso(stamp("09:30")))
        self.assertEqual(result["attempt"]["confirmation_timestamp"], iso(stamp("09:31")))

    def test_both_direction_sweep_is_single_rejected_attempt(self):
        data = fixture()
        put(data, "09:30", 100, 112, 88, 100)
        result = simulate(data)
        self.assertEqual(result["reason"], "BOTH_DIRECTION_SWEEP")
        self.assertTrue(result["ambiguous"])
        self.assertEqual(len(result["attempt"]["swept_levels"]), 4)
        self.assertIsNone(result["trade"])

    def test_first_attempt_rejection_never_tries_later_signal(self):
        data = fixture(signal=False)
        put(data, "09:30", 100, 112, 95, 100)
        put(data, "09:40", 100, 102, 98, 100)
        put(data, "09:41", 103, 104, 101, 103)
        put(data, "09:42", 105, 108, 104, 106)
        put(data, "09:43", 106, 112, 99, 101)
        result = simulate(data)
        self.assertEqual(result["reason"], "NO_ELIGIBLE_GAP")
        self.assertEqual(result["attempt"]["sweep_timestamp"], iso(stamp("09:30")))

    def test_previously_inverted_latest_gap_does_not_hide_older_eligible_gap(self):
        data = fixture(signal=False)
        put(data, "09:22", 99, 100, 98, 99)
        put(data, "09:24", 105, 106, 104, 105)
        put(data, "09:25", 105, 106, 104, 105)
        put(data, "09:26", 106, 108, 105, 106)
        put(data, "09:27", 109, 110, 108, 109)
        put(data, "09:28", 105, 109, 104, 105)
        put(data, "09:29", 104, 105, 102, 104)
        put(data, "09:30", 104, 112, 98, 99)
        result = simulate(data)
        self.assertEqual(result["attempt"]["gap"]["c_timestamp"], iso(stamp("09:24")))
        self.assertEqual(result["attempt"]["gap"]["lower_ticks"], 100)
        self.assertEqual(result["attempt"]["confirmation_timestamp"], iso(stamp("09:30")))

    def test_gap_age_tenth_allowed_eleventh_excluded(self):
        for age, accepted in ((10, True), (11, False)):
            with self.subTest(age=age):
                data = fixture(signal=False)
                c = stamp("09:30") - age * MINUTE
                data[c - 2 * MINUTE] = Bar(c - 2 * MINUTE, 100, 101, 99, 100)
                data[c] = Bar(c, 103, 104, 102, 103)
                current = c + MINUTE
                while current < stamp("09:30"):
                    data[current] = replace(data[current], close=101)
                    current += MINUTE
                put(data, "09:30", 100, 112, 98, 100)
                result = simulate(data)
                self.assertEqual(result["attempt"]["gap"] is not None, accepted)

    def test_one_tick_gap_valid_equal_boundary_no_gap(self):
        for low, accepted in ((103, True), (102, False)):
            with self.subTest(low=low):
                data = fixture()
                put(data, "09:28", 100, 105, 95, 100)
                put(data, "09:29", low + 1, 108, low, low + 1)
                result = simulate(data)
                self.assertEqual(result["attempt"]["gap"] is not None, accepted)

    def test_equal_inversion_boundary_and_wick_wait_for_first_strict_close(self):
        data = fixture()
        put(data, "09:30", 106, 112, 99, 102)
        put(data, "09:31", 102, 110, 90, 102)
        put(data, "09:32", 102, 111, 99, 101)
        put(data, "09:33", 100, 120, 90, 110)
        result = simulate(data)
        trade = result["trade"]
        self.assertEqual(result["attempt"]["confirmation_timestamp"], iso(stamp("09:32")))
        self.assertEqual(trade["entry_timestamp"], iso(stamp("09:33")))
        self.assertEqual(trade["stop_ticks"], 113)
        self.assertEqual(trade["exit_reason"], "STOP")

    def test_confirmation_tenth_allowed_eleventh_rejected(self):
        for offset, accepted in ((10, True), (11, False)):
            with self.subTest(offset=offset):
                data = fixture()
                put(data, "09:30", 106, 112, 99, 103)
                for minute in range(31, 42):
                    put(data, f"09:{minute}", 103, 105, 102, 103)
                when = stamp("09:30") + offset * MINUTE
                data[when] = Bar(when, 103, 105, 99, 101)
                result = simulate(data)
                self.assertEqual(result["trade"] is not None, accepted)
                if not accepted:
                    self.assertEqual(result["reason"], "NO_INVERSION")

    def test_opposite_sweep_checked_before_confirmation(self):
        for long in (False, True):
            data = fixture()
            put(data, "09:30", 106, 112, 99, 103)
            put(data, "09:31", 100, 105, 89, 101)
            result = simulate(mirror(data) if long else data)
            self.assertEqual(result["reason"], "OPPOSITE_SWEEP")
            self.assertIsNone(result["trade"])

    def test_most_adverse_confirmation_extreme_freezes_structural_stop(self):
        data = fixture()
        put(data, "09:30", 106, 112, 99, 103)
        put(data, "09:31", 103, 116, 100, 103)
        put(data, "09:32", 103, 114, 99, 101)
        result = simulate(data)
        self.assertEqual(result["trade"]["stop_ticks"], 117)
        self.assertEqual(result["trade"]["entry_timestamp"], iso(stamp("09:33")))

    def test_entry_open_at_or_beyond_stop_rejected_nearby_valid_open_retained(self):
        for long in (False, True):
            for open_ in (113, 114, 112, 111):
                with self.subTest(long=long, open=open_):
                    data = fixture()
                    put(data, "09:31", open_, 115, 100, 110)
                    result = simulate(mirror(data) if long else data)
                    if open_ >= 113:
                        self.assertEqual(result["reason"], "ENTRY_AT_OR_BEYOND_STOP")
                        self.assertIsNone(result["trade"])
                    else:
                        # Adverse friction expands distance to the structural stop.
                        self.assertEqual(result["decision"], "TRADE")
                        self.assertEqual(result["trade"]["risk_ticks"], 115 - open_)

    def test_entries_must_precede_eleven(self):
        for sweep_clock, expected in (("10:58", "TRADE"), ("10:59", "REJECTED")):
            with self.subTest(sweep=sweep_clock):
                data = fixture(signal=False)
                sweep = stamp(sweep_clock)
                for offset, values in ((-3, (100, 102, 98, 100)),
                                       (-2, (103, 104, 101, 103)),
                                       (-1, (105, 108, 104, 106)),
                                       (0, (106, 112, 99, 101))):
                    when = sweep + offset * MINUTE
                    data[when] = Bar(when, *values)
                result = simulate(data)
                self.assertEqual(result["decision"], expected)
                if expected == "TRADE":
                    self.assertEqual(result["trade"]["entry_timestamp"], iso(stamp("10:59")))
                else:
                    self.assertEqual(result["reason"], "ENTRY_CUTOFF")

    def test_stop_first_ambiguity_and_target_touch_not_fill(self):
        data = fixture()
        put(data, "09:32", 100, 114, 67, 100)
        result = simulate(data)
        self.assertEqual(result["trade"]["exit_reason"], "STOP")
        self.assertTrue(result["ambiguous"])
        put(data, "09:32", 100, 105, 68, 100)
        result = simulate(data)
        self.assertEqual(result["trade"]["exit_reason"], "TIME")
        self.assertFalse(result["ambiguous"])
        put(data, "09:33", 100, 105, 67, 100)
        self.assertEqual(simulate(data)["trade"]["exit_reason"], "TARGET")

    def test_opening_stop_gap_worse_than_stop_plus_friction(self):
        for long in (False, True):
            data = fixture()
            put(data, "09:32", 120, 125, 65, 100)
            result = simulate(mirror(data) if long else data)
            trade = result["trade"]
            self.assertEqual(trade["exit_ticks"], 78 if long else 122)
            self.assertEqual(trade["gross_ticks"], -24)
            self.assertFalse(result["ambiguous"])

    def test_intrabar_exit_time_is_interval_opening_exit_time_is_open(self):
        data = fixture()
        put(data, "09:32", 100, 114, 95, 110)
        trade = simulate(data)["trade"]
        self.assertEqual(trade["exit_timestamp"], iso(stamp("09:32")))
        self.assertEqual(trade["exit_time_basis"], "INTRABAR_INTERVAL")
        self.assertEqual(trade["exit_interval_end"], iso(stamp("09:33")))
        put(data, "09:32", 120, 125, 95, 110)
        trade = simulate(data)["trade"]
        self.assertEqual(trade["exit_time_basis"], "OPEN")
        self.assertIsNone(trade["exit_interval_end"])

    def test_opening_target_gap_has_no_improvement_and_precedes_later_stop(self):
        for long in (False, True):
            data = fixture()
            put(data, "09:32", 60, 120, 55, 100)
            result = simulate(mirror(data) if long else data)
            self.assertEqual(result["trade"]["exit_reason"], "TARGET")
            self.assertEqual(result["trade"]["exit_ticks"], 132 if long else 68)
            self.assertFalse(result["ambiguous"])

    def test_eleven_thirty_open_only_and_resting_exits_have_priority(self):
        for open_, reason, short_exit in ((100, "TIME", 102), (120, "STOP", 122),
                                           (67, "TARGET", 68), (68, "TIME", 70)):
            for long in (False, True):
                with self.subTest(open=open_, long=long):
                    data = fixture()
                    put(data, "11:30", open_, 200, 1, 100)
                    result = simulate(mirror(data) if long else data)
                    trade = result["trade"]
                    self.assertEqual(trade["exit_reason"], reason)
                    self.assertEqual(trade["exit_ticks"], 200 - short_exit if long else short_exit)
                    self.assertFalse(result["ambiguous"])

    def test_all_nine_cost_scenarios_exact_target_net(self):
        self.assertEqual(len(COST_SCENARIOS), 9)
        for case in COST_SCENARIOS:
            with self.subTest(case=case):
                data = fixture()
                put(data, "09:32", 60, 61, 1, 10)
                result = simulate(data, fee_per_side=case["fee_per_side_cents"],
                                  friction_ticks=case["friction_ticks"])
                risk = 113 - (100 - case["friction_ticks"])
                gross = Decimal(risk)
                self.assertEqual(Decimal(result["gross_usd"]), gross)
                self.assertEqual(Decimal(result["net_usd"]),
                                 gross - Decimal(case["fee_per_side_cents"]) / 50)
                json.dumps(result, allow_nan=False)

    def test_missing_each_required_phase_unresolved_not_zero(self):
        for clock, day, reason in (
            ("23:59", DAY - timedelta(days=1), "MISSING_REFERENCE"),
            ("00:00", DAY, None),  # excluded end boundary
            ("02:00", DAY, "MISSING_REFERENCE"),
            ("04:59", DAY, "MISSING_REFERENCE"),
            ("09:18", DAY, "MISSING_PRE_GAP"),
            ("09:30", DAY, "MISSING_OBSERVATION"),
            ("09:31", DAY, "MISSING_ENTRY"),
            ("09:32", DAY, "MISSING_OUTCOME"),
            ("11:30", DAY, "MISSING_OUTCOME"),
        ):
            with self.subTest(clock=clock, day=day):
                data = fixture()
                missing = stamp(clock, day)
                data.pop(missing, None)
                result = simulate(data)
                if reason is None:
                    self.assertEqual(result["decision"], "TRADE")
                    continue
                self.assertEqual(result["decision"], "UNRESOLVED")
                self.assertEqual(result["reason"], reason)
                self.assertIn(iso(missing), result["required_missing"])
                self.assertIsNone(result["gross_usd"])
                self.assertIsNone(result["net_usd"])

    def test_missing_observation_before_later_signal_cannot_resume(self):
        data = fixture(signal=False)
        del data[stamp("09:31")]
        put(data, "09:33", 100, 112, 95, 100)
        result = simulate(data)
        self.assertEqual(result["reason"], "MISSING_OBSERVATION")
        self.assertIsNone(result["attempt"])

    def test_missing_confirmation_cannot_resume_at_later_inversion(self):
        data = fixture()
        put(data, "09:30", 106, 112, 99, 103)
        del data[stamp("09:31")]
        result = simulate(data)
        self.assertEqual(result["reason"], "MISSING_CONFIRMATION")
        self.assertIsNone(result["trade"])

    def test_missing_outcome_before_observed_later_stop_cannot_infer_loss(self):
        data = fixture()
        del data[stamp("09:32")]
        put(data, "09:33", 100, 120, 90, 110)
        result = simulate(data)
        self.assertEqual(result["reason"], "MISSING_OUTCOME")
        self.assertIsNone(result["trade"]["exit_reason"])

    def test_closed_loss_and_rejected_attempt_do_not_need_later_coverage(self):
        data = fixture()
        put(data, "09:32", 100, 114, 95, 110)
        data = {when: bar for when, bar in data.items() if when <= stamp("09:32")}
        result = simulate(data)
        self.assertEqual(result["net_usd"], "-10.50")
        self.assertTrue(result["coverage"]["complete"])
        data = fixture(signal=False)
        put(data, "09:30", 100, 112, 95, 100)
        data = {when: bar for when, bar in data.items() if when <= stamp("09:30")}
        self.assertEqual(simulate(data)["reason"], "NO_ELIGIBLE_GAP")

    def test_causality_later_prices_or_rows_do_not_change_known_decision(self):
        data = fixture()
        put(data, "09:32", 100, 114, 95, 110)
        expected = simulate(data)
        for when in list(data):
            if when > stamp("09:32"):
                data[when] = Bar(when, 1000, 2000, 0, 1500)
        self.assertEqual(simulate(data), expected)
        data = {when: bar for when, bar in data.items() if when <= stamp("09:32")}
        self.assertEqual(simulate(data), expected)

    def test_calendar_exclusions_and_unknown(self):
        for status, decision in (("CLOSED", "EXCLUDED"), ("SHORTENED", "EXCLUDED"),
                                 ("UNKNOWN", "UNRESOLVED"), ("INCOMPLETE", "UNRESOLVED")):
            result = simulate_day([], DAY, calendar_status=status)
            self.assertEqual(result["decision"], decision)
            self.assertEqual(result["coverage"]["required_count"], 0)
        with self.assertRaises(ValueError):
            simulate_day([], DAY, calendar_status="ASSUMED_REGULAR")

    def test_dst_prior_calendar_day_and_reference_boundaries(self):
        for day, utc_hour in ((date(2026, 3, 6), 14), (date(2026, 3, 9), 13),
                              (date(2026, 10, 30), 13), (date(2026, 11, 2), 14)):
            with self.subTest(day=day):
                data = fixture(day)
                result = simulate_day(data.values(), day.isoformat())
                self.assertEqual(result["attempt"]["sweep_timestamp"],
                                 iso(stamp("09:30", day)))
                self.assertEqual(stamp("09:30", day).hour, utc_hour)
                phases = result["coverage"]["phases"]
                self.assertEqual(phases["asian_reference"]["required_count"], 240)
                self.assertEqual(phases["london_reference"]["required_count"], 180)
                self.assertEqual(result["reference_levels"]["ASIAN_HIGH"], 110)
        data = fixture()
        put(data, "00:00", 100, 9000, 0, 100)
        put(data, "05:00", 100, 9000, 0, 100)
        result = simulate(data)
        self.assertEqual(result["reference_levels"]["ASIAN_HIGH"], 110)
        self.assertEqual(result["reference_levels"]["LONDON_LOW"], 90)

    def test_multiple_same_side_levels_logged_and_prior_crosses_allowed(self):
        data = fixture()
        put(data, "09:20", 100, 111, 95, 111)  # cross, without reclaim
        result = simulate(data)
        self.assertEqual(result["attempt"]["swept_levels"], ["ASIAN_HIGH", "LONDON_HIGH"])
        self.assertEqual(result["attempt"]["sweep_timestamp"], iso(stamp("09:30")))

    def test_epoch_minutes_and_unsorted_rows_identical(self):
        data = fixture()
        expected = simulate(data)
        epoch_rows = [replace(bar, timestamp=int(when.timestamp()) // 60)
                      for when, bar in reversed(list(data.items()))]
        self.assertEqual(simulate_day(epoch_rows, DAY), expected)
        self.assertEqual(simulate(data, fee_per_side=Decimal("1.00")), expected)

    def test_duplicate_unaligned_naive_non_utc_and_invalid_ohlc_rejected(self):
        valid = next(iter(fixture().values()))
        for bad in (
            replace(valid, timestamp=valid.timestamp.replace(tzinfo=None)),
            replace(valid, timestamp=valid.timestamp.astimezone(NY)),
            replace(valid, timestamp=valid.timestamp + timedelta(seconds=1)),
            replace(valid, open=111), replace(valid, low=101),
            replace(valid, close=100.0), replace(valid, high=True),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                simulate_day([bad], DAY)
        with self.assertRaises(ValueError):
            simulate_day([valid, valid], DAY)
        for timestamp in (True, "2026-10-19T13:30:00Z", 1.5):
            with self.subTest(timestamp=timestamp), self.assertRaises(TypeError):
                simulate_day([replace(valid, timestamp=timestamp)], DAY)

    def test_cost_scenario_validation_is_frozen_and_no_float_rounding(self):
        for fee in (0, 51, -100, True, 1.0, Decimal("NaN"), Decimal("Infinity")):
            with self.subTest(fee=fee), self.assertRaises(ValueError):
                simulate_day([], DAY, fee_per_side=fee)
        for friction in (0, 3, -1, True, 1.0):
            with self.subTest(friction=friction), self.assertRaises(ValueError):
                simulate_day([], DAY, friction_ticks=friction)


if __name__ == "__main__":
    unittest.main()

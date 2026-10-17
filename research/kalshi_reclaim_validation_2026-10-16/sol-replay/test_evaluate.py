"""Fake research-screen boundaries; no historical observations."""

import unittest

from evaluate import combine, screen


def healthy():
    return {
        "net_known_pnl": "2",
        "known_filled_windows": 30,
        "distinct_filled_open_days": list(range(7)),
        "unknown_entered_outcomes": 0,
        "unknown_attempted_entries": 0,
        "all_attempt_lower_pnl": "2",
        "all_attempt_upper_pnl": "2",
    }


class ScreenTests(unittest.TestCase):
    def test_all_requirements(self):
        self.assertEqual(
            screen(healthy(), healthy())["verdict"], "POSITIVE_RESEARCH_SCREEN"
        )

    def test_each_requirement_independently_blocks(self):
        for field, value in (
            ("net_known_pnl", "0"),
            ("known_filled_windows", 29),
            ("distinct_filled_open_days", list(range(6))),
            ("unknown_entered_outcomes", 1),
        ):
            p = healthy()
            p[field] = value
            self.assertEqual(screen(p, healthy())["verdict"], "INSUFFICIENT", field)

    def test_bad_confirmation_never_hidden_by_pooling(self):
        c = healthy()
        c["net_known_pnl"] = "-1"
        c["all_attempt_upper_pnl"] = "-1"
        self.assertEqual(screen(healthy(), c)["verdict"], "NEGATIVE_TESTED_PROXY")

    def test_unknown_entries_need_both_bounds_positive(self):
        for field in ("pooled", "confirmation"):
            p, c = healthy(), healthy()
            p["unknown_attempted_entries"] = 1
            (p if field == "pooled" else c)["all_attempt_lower_pnl"] = "0"
            self.assertEqual(screen(p, c)["verdict"], "INSUFFICIENT")
        p = healthy()
        p["unknown_attempted_entries"] = 1
        self.assertEqual(screen(p, healthy())["verdict"], "POSITIVE_RESEARCH_SCREEN")

    def test_empty_is_insufficient_and_denominators_retained(self):
        r = combine([], [])
        self.assertEqual(r["research_screen"]["verdict"], "INSUFFICIENT")
        self.assertEqual(r["pooled"]["planned_windows"], 864)
        self.assertEqual(r["confirmation"]["metadata_missing_windows"], 288)

    def test_overlap_or_wrong_partition_rejected(self):
        row = {
            "ticker": "fake",
            "open_ms": 1,
            "cell": "1000ms_current_targets",
            "delay_ms": 1000,
            "open_day_utc": "2026-10-04",
        }
        with self.assertRaises(ValueError):
            combine([row], [row])
        with self.assertRaises(ValueError):
            combine([], [row])
        with self.assertRaises(ValueError):
            combine([row, row], [])
        for cell, delay in (("1000ms_both_70", 1000), ("3000ms_current_targets", 3000)):
            with self.assertRaises(ValueError):
                combine([{**row, "cell": cell, "delay_ms": delay}], [])


if __name__ == "__main__":
    unittest.main()

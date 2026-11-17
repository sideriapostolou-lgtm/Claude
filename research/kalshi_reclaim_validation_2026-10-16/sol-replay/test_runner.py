"""Own fake-only ingestion/aggregation checks; no network or historical files."""

from __future__ import annotations

import csv
import gzip
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from replay import Market
from run_partition import bootstrap, epoch_ms, read_quotes, summarize


def row(
    stamp: int,
    pnl: str | None = "0",
    entered: bool = False,
    known: bool = True,
    status: str = "no_signal",
    low: str | None = None,
    high: str | None = None,
) -> dict:
    return {
        "ticker": f"KXBTC15M-FAKE-{stamp}",
        "open_ms": stamp,
        "open_day_utc": "2026-10-03",
        "pnl": pnl,
        "entered": entered,
        "attempted": entered or status == "unknown_entry",
        "known": known,
        "status": status,
        "lower_pnl": low if low is not None else pnl,
        "upper_pnl": high if high is not None else pnl,
        "fees": "0.01",
        "entry_fee": "0.01" if entered else "0",
    }


class AggregationTests(unittest.TestCase):
    def test_unknown_entry_loss_is_not_omitted(self) -> None:
        result = summarize(
            [
                row(1, ".20", True),
                row(2, None, False, False, "unknown_entry", "-.61", "1"),
            ],
            2,
            ["2026-10-03"],
        )
        self.assertEqual(result["net_known_pnl"], "0.20")
        self.assertEqual(result["all_attempt_lower_pnl"], "-0.41")
        self.assertEqual(result["unknown_attempted_entries"], 1)
        self.assertEqual(result["known_completed_trades"], 1)

    def test_entered_unknown_keeps_denominator_and_bounds(self) -> None:
        result = summarize(
            [row(1, None, True, False, "unobservable_exit_arrival", "-.51", ".49")],
            1,
            ["2026-10-03"],
        )
        self.assertEqual(result["unknown_entered_outcomes"], 1)
        self.assertEqual(result["known_filled_windows"], 1)
        self.assertEqual(result["known_completed_trades"], 0)
        self.assertEqual(D(result["all_attempt_lower_pnl"]), D("-.51"))

    def test_missing_metadata_does_not_shrink_planned_rate(self) -> None:
        result = summarize([row(1, ".20", True)], 4, ["2026-10-03"])
        self.assertEqual(result["metadata_missing_windows"], 3)
        self.assertEqual(D(result["net_known_pnl_per_planned_window"]), D(".05"))

    def test_absent_days_remain_in_bootstrap_denominator(self) -> None:
        result = summarize([row(1, ".20", True)], 192, ["2026-10-03", "2026-10-04"])
        self.assertEqual(result["daily_known_pnl_window_open_utc"]["2026-10-04"], "0")
        self.assertEqual(result["day_block_known_pnl_interval"]["days"], 2)

    def test_drawdown_sorts_market_time_and_keeps_loss(self) -> None:
        result = summarize(
            [row(3, ".60", True), row(1, ".30", True), row(2, "-.50", True)],
            3,
            ["2026-10-03"],
        )
        self.assertEqual(result["negative_trades"], 1)
        self.assertEqual(result["known_only_peak_to_trough_drawdown"], "0.50")
        self.assertEqual(result["worst_known_trade"]["pnl"], "-.50")

    def test_empty_no_fills_does_not_mean_success(self) -> None:
        result = summarize([], 96, ["2026-10-03"])
        self.assertIsNone(result["observed_snapshot_fill_rate"])
        self.assertIsNone(result["worst_known_trade"])
        self.assertEqual(result["known_completed_trades"], 0)

    def test_invalid_universe_denominator_rejected(self) -> None:
        with self.assertRaises(ValueError):
            summarize([row(1)], 0, ["2026-10-03"])

    def test_day_block_bootstrap_constant_is_exact(self) -> None:
        a = bootstrap([D(".20")])
        self.assertEqual(D(a["lower"]), D(".20"))
        self.assertEqual(D(a["upper"]), D(".20"))
        self.assertEqual(a, bootstrap([D(".20")]))

    def test_timezone_offset_preserves_instant(self) -> None:
        self.assertEqual(
            epoch_ms("2026-10-03T00:00:00Z"), epoch_ms("2026-10-02T17:00:00-07:00")
        )


class QuoteIngestionTests(unittest.TestCase):
    def test_invalid_frames_and_reversed_clocks_are_retained(self) -> None:
        market = Market("KXBTC15M-FAKE", 0, 900000, D("80000"))
        fields = [
            "ts_ms",
            "ticker",
            "yes_bid",
            "yes_ask",
            "yes_bid_qty",
            "yes_ask_qty",
            "no_bid",
            "no_ask",
            "no_bid_qty",
            "no_ask_qty",
        ]
        values = [
            {
                "ts_ms": 2,
                "ticker": market.ticker,
                "yes_bid": ".49",
                "yes_ask": ".50",
                "yes_bid_qty": "2",
                "yes_ask_qty": "2",
                "no_bid": ".50",
                "no_ask": ".51",
                "no_bid_qty": "2",
                "no_ask_qty": "2",
            }
        ]
        values += [{**values[0], "ts_ms": 1, "yes_ask_qty": "-1"}]
        values += [{**values[0], "ts_ms": 1}]
        values += [{**values[0], "ts_ms": 3, "no_bid": ".60"}]
        values += [{**values[0], "ts_ms": 4, "no_bid_qty": "3"}]
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "fake.csv.gz"
            with gzip.open(file, "wt", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(values)
            quotes, quality = read_quotes(file, {market.ticker: market})
        self.assertEqual([x.ts_ms for x in quotes[market.ticker]], [2, 1, 1, 3, 4])
        self.assertIsNone(quotes[market.ticker][1].yes_ask)
        self.assertEqual(quality["invalid_price_or_size_rows"], 3)
        self.assertEqual(quality["contradictory_complement_price_rows"], 1)
        self.assertEqual(quality["contradictory_complement_size_rows"], 1)
        self.assertEqual(quality["reversed_timestamp_rows"], 1)
        self.assertEqual(quality["duplicate_timestamp_rows"], 1)


if __name__ == "__main__":
    unittest.main()

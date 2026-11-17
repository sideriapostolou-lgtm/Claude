"""Independent loader/runner checks using exclusively generated fake inputs."""

import contextlib
import csv
import gzip
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from decimal import Decimal as D
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "sol-replay"))
import run_partition as runner
from replay import LaneRule, Side

YES = LaneRule(
    "RECLAIM_70",
    Side.YES,
    D(".15"),
    D(".30"),
    D(".35"),
    D(".55"),
    D(".35"),
    D(".55"),
    D(-20),
    D(20),
    D(-150),
    D(-50),
    D(".70"),
)
NO = LaneRule(
    "NO_RECLAIM_80",
    Side.NO,
    D(".35"),
    D(".40"),
    D(".50"),
    D(".70"),
    D(".50"),
    D(".70"),
    D(-75),
    D(-25),
    None,
    None,
    D(".80"),
)


def write(path, value):
    path.write_text(json.dumps(value) + "\n")


def fields(op, hi, lo, cl):
    return dict(
        zip(
            ("open_dollars", "high_dollars", "low_dollars", "close_dollars"),
            (op, hi, lo, cl),
        )
    )


def fake_dataset(directory):
    root = pathlib.Path(directory)
    data = root / "root-data" / "dev"
    data.mkdir(parents=True)
    t = runner.epoch_ms("2026-10-03T12:00:00Z")
    ticker = "KXBTC15M-SYNTHETIC"
    write(
        data / "markets_all.json",
        [
            {
                "ticker": ticker,
                "open_time": "2026-10-03T12:00:00Z",
                "close_time": "2026-10-03T12:15:00Z",
                "floor_strike": "10000",
                "result": "no",
                "settlement_ts": "2026-10-03T12:15:05Z",
            }
        ],
    )
    bars = []
    for k in range(1, 16):
        ask = (
            fields(".40", ".45", ".20", ".40")
            if k <= 5
            else fields(".40", ".50", ".40", ".50")
        )
        bars.append(
            {
                "end_period_ts": (t + k * 60000) // 1000,
                "yes_ask": ask,
                "yes_bid": fields(".39", ".44", ".19", ".39"),
            }
        )
    write(
        data / "candles_fake.json",
        {"markets": [{"market_ticker": ticker, "candlesticks": bars}]},
    )
    btc = []
    for k in range(480):
        btc.append(
            [
                (t - 28800000 + k * 60000) // 1000,
                "10100",
                "10100",
                "10100",
                "10100",
                "1",
            ]
        )
    for k in range(5):
        btc.append([(t + k * 60000) // 1000, "10000", "10000", "10000", "10000", "1"])
    write(data / "coinbase_normalized.json", btc)
    rows = []
    for offset, bid, ask in [
        (361000, ".49", ".50"),
        (362000, ".49", ".50"),
        (363000, ".49", ".50"),
        (364000, ".49", ".50"),
        (400000, ".70", ".71"),
        (401000, ".71", ".72"),
        (402000, ".71", ".72"),
        (403000, ".72", ".73"),
    ]:
        rows.append(
            {
                "ts_ms": str(t + offset),
                "ticker": ticker,
                "yes_bid": bid,
                "yes_ask": ask,
                "yes_bid_qty": "5",
                "yes_ask_qty": "5",
                "no_bid": str(1 - D(ask)),
                "no_ask": str(1 - D(bid)),
                "no_bid_qty": "5",
                "no_ask_qty": "5",
            }
        )
    with gzip.open(data / "book_2026-10-03.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (data / "settle_2026-10-03.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "result"])
        w.writeheader()
        w.writerow({"ticker": ticker, "result": "no"})
    write(
        data / "markets_2026-10-03_0.json",
        {"markets": json.loads((data / "markets_all.json").read_text()), "cursor": ""},
    )
    write(data / "coinbase_0_1.json", btc)
    for f in list(data.iterdir()):
        if f.name in ("markets_all.json", "coinbase_normalized.json"):
            continue
        raw = f.read_bytes()
        write(
            f.with_name(f.name + ".receipt.json"),
            {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "url": "synthetic-fixture-only",
            },
        )
    write(root / "cards.json", {})
    return root, data


class IndependentRunnerChecks(unittest.TestCase):
    def test_full_six_cells_same_entries_preserve_settlement_loss(self):
        with tempfile.TemporaryDirectory() as d:
            root, data = fake_dataset(d)
            argv = [
                "run_partition.py",
                "--partition",
                "dev",
                "--data-root",
                str(root / "root-data"),
                "--cards",
                str(root / "cards.json"),
                "--out",
                str(root / "output"),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(runner, "current_rules", return_value=(YES, NO)),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                runner.main()
            result = json.loads((root / "output/dev_results.json").read_text())
            rows = [
                json.loads(x)
                for x in (root / "output/dev_windows.jsonl").read_text().splitlines()
            ]
        self.assertEqual(len(result["cells"]), 6)
        self.assertEqual(len(rows), 6)
        self.assertEqual(result["planned_windows"], 96)
        bycell = {r["cell"]: r for r in rows}
        for delay in (1000, 3000):
            cohort = [r for r in rows if r["delay_ms"] == delay]
            self.assertEqual(len({r["entry_ms"] for r in cohort}), 1)
            self.assertTrue(all(r["entered"] for r in cohort))
            self.assertEqual(
                D(bycell[f"{delay}ms_hold_settlement"]["pnl"]), D("-.5175")
            )
            self.assertGreater(D(bycell[f"{delay}ms_current_targets"]["pnl"]), 0)
        self.assertNotEqual(
            bycell["1000ms_current_targets"]["entry_ms"],
            bycell["3000ms_current_targets"]["entry_ms"],
        )
        self.assertEqual(
            result["cells"]["1000ms_current_targets"]["metadata_missing_windows"], 95
        )

    def test_partial_known_pnl_does_not_erase_unknown_entry_lower_bound(self):
        rows = [
            {
                "ticker": "KXBTC15M-A",
                "open_ms": 1,
                "open_day_utc": "2026-10-03",
                "status": "known",
                "known": True,
                "entered": True,
                "attempted": True,
                "pnl": ".2",
                "lower_pnl": ".2",
                "upper_pnl": ".2",
                "fees": ".01",
            },
            {
                "ticker": "KXBTC15M-B",
                "open_ms": 2,
                "open_day_utc": "2026-10-03",
                "status": "unknown_entry",
                "known": False,
                "entered": False,
                "attempted": True,
                "pnl": None,
                "lower_pnl": "-.5674",
                "upper_pnl": "1",
                "fees": None,
            },
        ]
        out = runner.summarize(rows, 96, ["2026-10-03"])
        self.assertEqual(D(out["all_attempt_lower_pnl"]), D("-.3674"))
        self.assertEqual(out["unknown_attempted_entries"], 1)
        self.assertEqual(out["metadata_missing_windows"], 94)


if __name__ == "__main__":
    unittest.main()

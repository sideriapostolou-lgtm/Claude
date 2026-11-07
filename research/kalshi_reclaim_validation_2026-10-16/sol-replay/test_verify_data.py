"""Synthetic integrity checks; no actual market records."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_data import verify_dataset


class IdentityTests(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        raw = {
            "markets": [
                {
                    "ticker": "KXBTC15M-FAKE",
                    "open_time": "2026-10-03T00:00:00Z",
                    "close_time": "2026-10-03T00:15:00Z",
                }
            ]
        }
        for name, value in (
            ("markets_2026-10-03_0.json", raw),
            ("coinbase_0_1.json", []),
        ):
            data = json.dumps(value).encode()
            (root / name).write_bytes(data)
            (root / (name + ".receipt.json")).write_text(
                json.dumps(
                    {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                )
            )
        (root / "markets_all.json").write_text(json.dumps(raw["markets"]))
        (root / "coinbase_normalized.json").write_text("[]")

    def test_exact_derivation_and_missing_minutes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = verify_dataset(root, "2026-10-03", "2026-10-04")
        self.assertEqual(result["verified_receipts"], 2)
        self.assertEqual(len(result["missing_btc_minute_starts"]), 1920)

    def test_corrupt_raw_or_missing_receipt_rejected(self):
        for missing in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                if missing:
                    (root / "coinbase_0_1.json.receipt.json").unlink()
                else:
                    (root / "coinbase_0_1.json").write_text("[0]")
                with self.assertRaises(ValueError):
                    verify_dataset(root, "2026-10-03", "2026-10-04")

    def test_corrupt_either_normalization_rejected(self):
        for filename in ("markets_all.json", "coinbase_normalized.json"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                (root / filename).write_text("[123]")
                with self.assertRaises(ValueError):
                    verify_dataset(root, "2026-10-03", "2026-10-04")


if __name__ == "__main__":
    unittest.main()

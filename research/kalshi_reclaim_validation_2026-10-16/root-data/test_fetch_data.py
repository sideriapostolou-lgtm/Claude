"""Synthetic collector checks: temporary files, fake responses, no network/data.

Imports only our independent collector. It never invokes its historical main loop.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Self
from unittest.mock import Mock, patch

import fetch_data

URL = "https://example.invalid/public-input"


class FakeResponse:
    def __init__(self, raw: bytes, status: int = 200) -> None:
        self.raw = raw
        self.status = status
        self.read_limits: list[int] = []

    def read(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        return self.raw[:limit]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class GetterTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="fake-reclaim-collector-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.getter = fetch_data.Getter(self.root)
        self.network: Mock = self.enterContext(
            patch.object(
                fetch_data.urllib.request,
                "urlopen",
                side_effect=AssertionError("unmocked request forbidden"),
            )
        )
        self.enterContext(patch.object(fetch_data.time, "sleep"))
        self.enterContext(
            patch.object(fetch_data.time, "monotonic", return_value=100.0)
        )

    def cache(self, raw: bytes = b"fake") -> tuple[Path, Path]:
        target = self.root / "item"
        receipt = self.root / "item.receipt.json"
        target.write_bytes(raw)
        receipt.write_text(
            json.dumps({"url": URL, "sha256": hashlib.sha256(raw).hexdigest()})
        )
        return target, receipt

    def response(self, raw: bytes) -> FakeResponse:
        response = FakeResponse(raw)
        self.network.side_effect = None
        self.network.return_value = response
        return response

    def test_matching_cache_never_requests_network(self) -> None:
        self.cache()
        self.assertEqual(self.getter.get(URL, "item"), b"fake")
        self.network.assert_not_called()

    def test_cache_url_identity_mismatch_is_fatal(self) -> None:
        self.cache()
        with self.assertRaisesRegex(ValueError, "Cached input identity mismatch"):
            self.getter.get(URL + "?different", "item")
        self.network.assert_not_called()

    def test_cache_payload_tamper_is_fatal(self) -> None:
        target, _ = self.cache()
        target.write_bytes(b"altered fake bytes")
        with self.assertRaisesRegex(ValueError, "Cached input identity mismatch"):
            self.getter.get(URL, "item")
        self.network.assert_not_called()

    def test_cache_receipt_digest_mismatch_is_fatal(self) -> None:
        _, receipt = self.cache()
        receipt.write_text(json.dumps({"url": URL, "sha256": "0" * 64}))
        with self.assertRaisesRegex(ValueError, "Cached input identity mismatch"):
            self.getter.get(URL, "item")
        self.network.assert_not_called()

    def test_cache_release_digest_mismatch_is_fatal(self) -> None:
        self.cache()
        with self.assertRaisesRegex(ValueError, "Cached input identity mismatch"):
            self.getter.get(URL, "item", digest="0" * 64)
        self.network.assert_not_called()

    def test_new_response_reads_only_bound_plus_sentinel(self) -> None:
        response = self.response(b"12345")
        with self.assertRaisesRegex(ValueError, "exceeded declared byte bound"):
            self.getter.get(URL, "item", max_bytes=4)
        self.assertEqual(response.read_limits, [5])
        self.assertFalse((self.root / "item").exists())
        self.assertFalse((self.root / "item.receipt.json").exists())

    def test_exact_byte_bound_writes_verified_public_get_receipt(self) -> None:
        self.response(b"1234")
        digest = hashlib.sha256(b"1234").hexdigest()
        self.assertEqual(
            self.getter.get(URL, "item", max_bytes=4, digest=digest), b"1234"
        )
        saved = json.loads((self.root / "item.receipt.json").read_text())
        self.assertEqual(saved["bytes"], 4)
        self.assertEqual(saved["sha256"], digest)
        self.assertEqual(saved["method"], "GET")
        self.assertIs(saved["public_no_auth"], True)

    def test_cached_response_obeys_current_byte_bound(self) -> None:
        self.cache(b"12345")
        with self.assertRaisesRegex(ValueError, "byte bound"):
            self.getter.get(URL, "item", max_bytes=4)
        self.network.assert_not_called()

    def test_request_is_get_only_with_no_auth_cookie_or_body(self) -> None:
        self.response(b"{}")
        self.getter.get(URL, "item")
        request = self.network.call_args.args[0]
        self.assertEqual(request.full_url, URL)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(set(headers), {"user-agent", "accept"})
        self.assertNotIn("authorization", headers)
        self.assertNotIn("cookie", headers)
        self.assertEqual(self.network.call_args.kwargs, {"timeout": 25})

    def test_new_release_digest_mismatch_leaves_no_cache(self) -> None:
        self.response(b"fake")
        with self.assertRaisesRegex(ValueError, "Release SHA256 mismatch"):
            self.getter.get(URL, "item", digest="0" * 64)
        self.assertFalse((self.root / "item").exists())
        self.assertFalse((self.root / "item.receipt.json").exists())

    def test_retry_is_bounded_and_preserves_failure_receipts(self) -> None:
        error = urllib.error.HTTPError(
            URL, 503, "fake unavailable", Message(), io.BytesIO()
        )
        self.network.side_effect = error
        with self.assertRaises(urllib.error.HTTPError):
            self.getter.get(URL, "item")
        self.assertEqual(self.network.call_count, 3)
        errors = [
            json.loads(row)
            for row in (self.root / "http_errors.jsonl").read_text().splitlines()
        ]
        self.assertEqual([row["attempt"] for row in errors], [1, 2, 3])
        self.assertEqual([row["status"] for row in errors], [503, 503, 503])

    def test_retry_after_over_sixty_seconds_stops_instead_of_blocking(self) -> None:
        headers = Message()
        headers["Retry-After"] = "61"
        self.network.side_effect = urllib.error.HTTPError(
            URL, 429, "fake rate limit", headers, io.BytesIO()
        )
        with self.assertRaisesRegex(RuntimeError, ">60s wait"):
            self.getter.get(URL, "item")
        self.assertEqual(self.network.call_count, 1)


class ConfirmationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="fake-reclaim-freeze-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / "root-data"
        self.base.mkdir()
        self.enterContext(patch.object(fetch_data, "BASE", self.base))
        self.network: Mock = self.enterContext(
            patch.object(
                fetch_data.urllib.request,
                "urlopen",
                side_effect=AssertionError("network forbidden in gate tests"),
            )
        )

    def gate(self, **overrides: object) -> None:
        code = self.root / "fake_replay.py"
        code.write_bytes(b"synthetic implementation bytes\n")
        saved = {
            "independent_review_approved": True,
            "tests_passed": True,
            "files": [
                {
                    "path": code.name,
                    "sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
                }
            ],
            **overrides,
        }
        (self.root / "CONFIRMATION_FREEZE.json").write_text(json.dumps(saved))

    def test_absent_gate_keeps_confirmation_sealed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no reviewed code/test freeze"):
            fetch_data.ensure_confirmation_gate()
        self.network.assert_not_called()

    def test_review_false_keeps_confirmation_sealed(self) -> None:
        self.gate(independent_review_approved=False)
        with self.assertRaisesRegex(RuntimeError, "review/tests incomplete"):
            fetch_data.ensure_confirmation_gate()

    def test_tests_false_keeps_confirmation_sealed(self) -> None:
        self.gate(tests_passed=False)
        with self.assertRaisesRegex(RuntimeError, "review/tests incomplete"):
            fetch_data.ensure_confirmation_gate()

    def test_changed_implementation_keeps_confirmation_sealed(self) -> None:
        self.gate()
        (self.root / "fake_replay.py").write_bytes(b"changed synthetic bytes\n")
        with self.assertRaisesRegex(RuntimeError, "implementation bytes changed"):
            fetch_data.ensure_confirmation_gate()

    def test_missing_frozen_file_cannot_pass_gate(self) -> None:
        self.gate()
        (self.root / "fake_replay.py").unlink()
        with self.assertRaises(FileNotFoundError):
            fetch_data.ensure_confirmation_gate()

    def test_matching_frozen_bytes_pass_gate_without_network(self) -> None:
        self.gate()
        fetch_data.ensure_confirmation_gate()
        self.network.assert_not_called()

    def test_confirmation_main_checks_gate_before_io_or_getter(self) -> None:
        with patch("sys.argv", ["fetch_data.py", "--partition", "confirmation"]):
            with patch.object(fetch_data, "Getter") as getter:
                with self.assertRaisesRegex(RuntimeError, "Confirmation sealed"):
                    fetch_data.main()
        getter.assert_not_called()
        self.network.assert_not_called()


if __name__ == "__main__":
    unittest.main()

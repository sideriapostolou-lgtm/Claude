"""Saved public metadata only: no network, real credentials or held-out outcomes."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from kalshi_recorder_fixtures import Clock
from test_kalshi_recorder import recorder, venue

from nightcrawler import kalshi_recorder_evidence as evidence

START = datetime(2026, 10, 14, 15, tzinfo=UTC).timestamp()
NAME = "coverage-2026-10-14T15.json"


def manifest() -> dict[str, Any]:
    return {
        "schema": 1, "from": START, "to": START + 3600, "partial": False,
        "read_only": True, "order_capability": False, "session": "a" * 32, "commit": "b" * 40,
        "session_started_at": START + 120,
        "coverage": {"minutes_sampled": 60, "btc15m_minutes": 59, "btc15m_fresh_minutes": 58,
                     "candidate_book_fresh_share": 0.98, "trade_covered_to": START + 3599},
        "storage": {"used_bytes": 4200, "cap_bytes": 4608 * 1024 * 1024, "level": 0, "deleted_segments": 0},
        "lanes": {"books": {"requests": 60, "ok": 59, "429": 1, "errors": 0,
                            "rtt_ms": {"p50": 30, "p95": 50, "p99": 100}}},
        "trade_receive_lag_s": {"p50": 1, "p95": 2, "p99": 3},
        "gaps": [{"gap_lane": "spot", "from": START + 4, "to": START + 10, "cause": "spot_reconnected"}],
        "segments": [{"lane": "spot", "records": 600, "gz_bytes": 3000, "first_at": START + 1,
                      "last_at": START + 3599, "path": "not-used.jsonl.gz", "sha256": "c" * 64},
                     {"lane": "spot", "records": 120, "gz_bytes": 1000, "first_at": START + 10,
                      "last_at": START + 600, "path": "also-not-read.jsonl.gz"}],
    }


def saved(tmp_path: Path, value: Any = None, *, name: str = NAME) -> tuple[Path, bytes]:
    directory = tmp_path / "manifests"
    directory.mkdir(exist_ok=True)
    body = json.dumps(manifest() if value is None else value).encode()
    (directory / name).write_bytes(body)
    return tmp_path, body


def reports(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(record.getMessage().split(" ", 1)[1]) for record in caplog.records
            if record.getMessage().startswith("kalshi_recorder_evidence ")]


def test_saved_report_reads_manifest_bytes_and_labels_its_limits(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    root, body = saved(tmp_path)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_manifest(root, NAME, now=START + 3700, source="saved_hourly_manifest")
    report = reports(caplog)[0]
    assert report["status"] == "available" and report["manifest_sha256"] == hashlib.sha256(body).hexdigest()
    assert report["sealed_lanes"]["spot"] == {
        "segments": 2, "record_envelopes": 720, "gz_bytes": 4000,
        "first_append_at": START + 1, "last_append_at": START + 3599}
    assert report["sealed_only"] and not report["segment_hashes_reverified"]
    assert not report["coverage_certified"] and not report["per_venue_spot_ticks_verified"]
    assert not report["rows_and_test_outcomes_read"]
    assert report["coverage"]["backfill_jobs_pending"] is None
    assert report["gaps"] == {"records": 1, "open_ended_records": 0, "by_lane": {"spot": 1},
                              "by_cause": {"spot_reconnected": 1}}
    assert report["session_started_at"] == START + 120
    assert report["rest_lanes"]["books"]["429"] == 1


def test_extra_fields_and_untrusted_strings_are_not_printed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    raw = manifest()
    marker = "unrelated-private-value-that-must-not-leave"
    raw.update(extra=marker, host=marker, session=marker, commit=marker)
    raw["coverage"]["unexpected"] = marker
    raw["storage"]["path"] = marker
    raw["lanes"][marker] = {"extra": marker}
    raw["lanes"]["books"]["extra"] = marker
    raw["segments"][0].update(path=marker, extra=marker)
    raw["gaps"].append({"gap_lane": marker, "cause": marker, "extra": marker})
    root, _ = saved(tmp_path, raw)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_previous_hour(root, START + 3600)
    assert marker not in caplog.text
    report = reports(caplog)[0]
    assert report["status"] == "available" and report["session"] is None and report["commit"] is None
    assert report["gaps"]["by_lane"] == {"spot": 1, "other": 1}
    assert report["gaps"]["by_cause"] == {"spot_reconnected": 1, "other": 1}


def test_startup_reads_only_the_fixed_previous_full_hour(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    root, _ = saved(tmp_path)
    (root / "manifests" / "coverage-2026-10-14T16.json").write_text("not the previous hour")
    opened: list[str] = []
    real_open = evidence.os.open

    def capture(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        opened.append(str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(evidence.os, "open", capture)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_previous_hour(root, START + 5400)
    assert opened == [str(root / "manifests"), NAME]
    assert reports(caplog)[0]["source"] == "previous_hour_startup"
    assert reports(caplog)[0]["period"]["from"] == START


@pytest.mark.parametrize("kind,reason", [("missing", "missing"), ("oversize", "too_large"),
                                       ("malformed", "malformed"), ("list", "malformed_manifest"),
                                       ("wrong_hour", "malformed_period"), ("partial", "malformed_period"),
                                       ("negative_records", "malformed_segment_counts")])
def test_bad_metadata_is_reported_without_raising(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                                kind: str, reason: str) -> None:
    root, _ = saved(tmp_path)
    path = root / "manifests" / NAME
    if kind == "missing":
        path.unlink()
    elif kind == "oversize":
        path.write_bytes(b" " * (evidence.MAX_MANIFEST_BYTES + 1))
    elif kind == "malformed":
        path.write_bytes(b'{"broken":')
    elif kind == "list":
        path.write_text("[]")
    else:
        raw = manifest()
        if kind == "wrong_hour":
            raw["from"] = START - 3600
        elif kind == "partial":
            raw["partial"] = True
        else:
            raw["segments"][0]["records"] = -1
        path.write_text(json.dumps(raw))
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_manifest(root, NAME, now=START + 3700, source="saved_hourly_manifest")
    assert reports(caplog)[0]["status"] == "unavailable" and reports(caplog)[0]["reason"] == reason


def test_read_failure_hides_exception_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         caplog: pytest.LogCaptureFixture) -> None:
    def denied(*args: Any, **kwargs: Any) -> int:
        raise PermissionError("private-message-not-for-logs")

    monkeypatch.setattr(evidence.os, "open", denied)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_previous_hour(tmp_path, START + 3600)
    assert reports(caplog)[0]["reason"] == "unreadable"
    assert "private-message-not-for-logs" not in caplog.text


@pytest.mark.parametrize("redirect_directory", [False, True])
def test_symlinks_cannot_redirect_manifest_reads(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                                redirect_directory: bool) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / NAME).write_text("must not be read")
    root = tmp_path / "data"
    root.mkdir()
    if redirect_directory:
        (root / "manifests").symlink_to(outside, target_is_directory=True)
    else:
        (root / "manifests").mkdir()
        (root / "manifests" / NAME).symlink_to(outside / NAME)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_previous_hour(root, START + 3600)
    assert reports(caplog)[0]["status"] == "unavailable"
    assert reports(caplog)[0]["reason"] == "unreadable"


def test_named_pipe_does_not_block(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    directory = tmp_path / "manifests"
    directory.mkdir()
    os.mkfifo(directory / NAME)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_previous_hour(tmp_path, START + 3600)
    assert reports(caplog)[0]["reason"] == "not_regular"


def test_logging_failure_does_not_stop_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError("broken log sink")

    monkeypatch.setattr(evidence.log, "info", broken)
    evidence.report_previous_hour(tmp_path, START + 3600)


def test_output_bound_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                  caplog: pytest.LogCaptureFixture) -> None:
    root, _ = saved(tmp_path)
    monkeypatch.setattr(evidence, "MAX_LOG_BYTES", 256)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        evidence.report_previous_hour(root, START + 3600)
    assert reports(caplog)[0]["reason"] == "report_limit"
    assert len(caplog.records[0].getMessage().encode()) < 256


def test_real_manifest_write_is_read_back_before_counters_are_cleared(tmp_path: Path,
                                                                   caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock(START + 1)
    box = recorder(tmp_path, venue(), clock)
    box.store.append("spot", "spot_trades", {"venue": "coinbase", "rows": []}, START + 2)
    box.minutes.update(minutes=59, btc15m_minutes=59, btc15m_fresh_minutes=58)
    box.gap("spot", START + 2, START + 3, "spot_reconnected")
    clock.at = START + 3600
    box.store.seal_hour(clock.at)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        path = box.write_manifest(START, START + 3600)
    report = reports(caplog)[0]
    assert report["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["sealed_lanes"]["spot"]["record_envelopes"] == 1
    assert report["coverage"]["btc15m_fresh_minutes"] == 58
    assert report["gaps"]["by_lane"] == {"spot": 1}
    assert box.minutes == {} and box.gaps_this_hour == []
    box.close()


def test_run_reports_missing_prior_manifest_without_preventing_shutdown(tmp_path: Path,
                                                                      caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock(START + 4000)
    box = recorder(tmp_path, venue(), clock)
    stop = threading.Event()
    stop.set()
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        box.run(stop)
    receipts = reports(caplog)
    assert receipts[0]["source"] == "previous_hour_startup" and receipts[0]["reason"] == "missing"
    assert receipts[-1]["source"] == "saved_partial_manifest"
    assert receipts[-1]["period"]["partial"] is True
    assert "kalshi_recorder_stopped" in caplog.text

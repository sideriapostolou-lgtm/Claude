"""Bounded saved-manifest log receipts, never raw records or research outcomes.

The fingerprint and sealed-index counters do not verify gzip payloads, complete
windows, per-venue spot ticks or trading results.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .kalshi_recorder_store import LANE_CLASS

log = logging.getLogger("nightcrawler.kalshi_recorder")
MAX_MANIFEST_BYTES = 512 * 1024
MAX_LOG_BYTES = 8 * 1024
_NAME = re.compile(r"coverage-(\d{4}-\d{2}-\d{2}T\d{2})(?:-[0-9a-f]{8}-partial)?\.json")
Source = Literal["previous_hour_startup", "saved_hourly_manifest", "saved_partial_manifest"]
GAP_CAUSES = frozenset({"spot_reconnected", "restart_partial_segment_recovered", "recorder_not_running",
                        "downtime_too_long_to_backfill", "lane_stale_recovered", "retry_after_hold",
                        "clock_moved_backwards", "storage_cap_paused", "storage_soft_cap_shed_btc15m_and_spot",
                        "storage_ok", "lane_stale", "book_unreadable", "backfill_page_cap",
                        "btc15m_metadata_unavailable", "events_pagination_incomplete", "market_row_unreadable",
                        "series_ticker_unusable", "settlement_not_seen_45_days"})


class MetadataError(ValueError):
    """A fixed failure code, never an arbitrary file value or exception message."""


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _obj(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _hex(value: Any, length: int) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) else None


def _read(root: Path, filename: str) -> bytes:
    if not _NAME.fullmatch(filename):
        raise MetadataError("invalid_name")
    directory = os.open(root / "manifests", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise MetadataError("not_regular")
        if info.st_size > MAX_MANIFEST_BYTES:
            raise MetadataError("too_large")
        body = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(body) > MAX_MANIFEST_BYTES:
        raise MetadataError("too_large")
    return body


def _segments(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise MetadataError("malformed_segments")
    result: dict[str, Any] = {}
    for row in rows:
        item = _obj(row)
        lane = item.get("lane")
        if not isinstance(lane, str) or lane not in LANE_CLASS:
            continue
        records, size = _count(item.get("records")), _count(item.get("gz_bytes"))
        first, last = _number(item.get("first_at")), _number(item.get("last_at"))
        if records is None or size is None or first is None or last is None or first > last:
            raise MetadataError("malformed_segment_counts")
        summary = result.setdefault(lane, {"segments": 0, "record_envelopes": 0, "gz_bytes": 0,
                                           "first_append_at": first, "last_append_at": last})
        summary["segments"] += 1
        summary["record_envelopes"] += records
        summary["gz_bytes"] += size
        summary["first_append_at"] = min(summary["first_append_at"], first)
        summary["last_append_at"] = max(summary["last_append_at"], last)
    return result


def _gaps(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise MetadataError("malformed_gaps")
    lanes: dict[str, int] = {}
    causes: dict[str, int] = {}
    open_ends = 0
    for row in rows:
        item = _obj(row)
        lane = item.get("gap_lane")
        name = lane if isinstance(lane, str) and lane in {*LANE_CLASS, "all", "btc15m"} else "other"
        lanes[name] = lanes.get(name, 0) + 1
        cause = item.get("cause")
        label = cause if isinstance(cause, str) and cause in GAP_CAUSES else "other"
        causes[label] = causes.get(label, 0) + 1
        open_ends += item.get("to") is None
    return {"records": len(rows), "open_ended_records": open_ends, "by_lane": lanes, "by_cause": causes}


def project_manifest(body: bytes, filename: str) -> dict[str, Any]:
    """Only explicit numeric/boolean metadata and validated identifiers leave this function."""
    if len(body) > MAX_MANIFEST_BYTES:
        raise MetadataError("too_large")
    value = json.loads(body)
    if (not isinstance(value, dict) or value.get("schema") != 1 or value.get("read_only") is not True
            or value.get("order_capability") is not False):
        raise MetadataError("malformed_manifest")
    match = _NAME.fullmatch(filename)
    if match is None:
        raise MetadataError("invalid_name")
    start = datetime.strptime(match[1], "%Y-%m-%dT%H").replace(tzinfo=UTC).timestamp()
    end, partial = _number(value.get("to")), value.get("partial")
    if (value.get("from") != start or end is None or end < start or not isinstance(partial, bool)
            or partial != filename.endswith("-partial.json") or (not partial and end != start + 3600)):
        raise MetadataError("malformed_period")
    coverage, storage = _obj(value.get("coverage")), _obj(value.get("storage"))
    rest: dict[str, Any] = {}
    for lane, raw in _obj(value.get("lanes")).items():
        if lane not in {"books", "trades", "backfill", "btc15m_meta", "discovery", "sweep", "settlement", "fees", "other"}:
            continue
        item = _obj(raw)
        rest[lane] = {name: _count(item.get(name)) for name in ("requests", "ok", "429", "errors")}
        rest[lane]["rtt_ms"] = {name: _number(_obj(item.get("rtt_ms")).get(name)) for name in ("p50", "p95", "p99")}
    return {
        "manifest_sha256": hashlib.sha256(body).hexdigest(),
        "period": {"from": start, "to": end, "partial": partial},
        "session": _hex(value.get("session"), 32), "commit": _hex(value.get("commit"), 40),
        "session_started_at": _number(value.get("session_started_at")),
        "read_only": True, "order_capability": False,
        "sealed_only": True, "segment_hashes_reverified": False,
        "segment_hash_basis": "index_metadata_computed_at_seal_not_rechecked",
        "rows_and_test_outcomes_read": False,
        "sealed_lanes": _segments(value.get("segments")),
        "coverage": {name: _number(coverage.get(name)) for name in (
            "minutes_sampled", "candidate_book_fresh_share", "trade_tape_minutes", "btc15m_minutes",
            "btc15m_fresh_minutes", "trade_covered_to", "backfill_jobs_pending")},
        "gaps": _gaps(value.get("gaps")),
        "storage": {name: _count(storage.get(name)) for name in ("used_bytes", "cap_bytes", "level", "deleted_segments")},
        "rest_lanes": rest,
        "trade_receive_lag_s": {name: _number(_obj(value.get("trade_receive_lag_s")).get(name))
                                for name in ("p50", "p95", "p99")},
        "coverage_certified": False, "per_venue_spot_ticks_verified": False,
    }


def report_manifest(root: Path, filename: str, *, now: float, source: Source) -> None:
    """Log one bounded saved-manifest receipt; failure never interrupts public capture."""
    report: dict[str, Any] = {"schema": 1, "source": source, "observed_at": _number(now)}
    try:
        report.update(project_manifest(_read(root, filename), filename))
        report["status"] = "available"
    except FileNotFoundError:
        report.update(status="unavailable", reason="missing")
    except MetadataError as exc:
        report.update(status="unavailable", reason=str(exc))
    except OSError:
        report.update(status="unavailable", reason="unreadable")
    except (ValueError, TypeError, RecursionError, OverflowError):
        report.update(status="unavailable", reason="malformed")
    try:
        message = json.dumps(report, separators=(",", ":"), sort_keys=True, allow_nan=False)
        if len(message.encode("utf-8")) > MAX_LOG_BYTES:
            message = json.dumps({"schema": 1, "source": source, "status": "unavailable", "reason": "report_limit"})
        log.info("kalshi_recorder_evidence %s", message)
    except Exception:  # noqa: BLE001, S110 - optional log evidence must never stop the recorder
        pass


def report_previous_hour(root: Path, now: float) -> None:
    hour = datetime.fromtimestamp(math.floor(now / 3600) * 3600 - 3600, UTC).strftime("%Y-%m-%dT%H")
    report_manifest(root, f"coverage-{hour}.json", now=now, source="previous_hour_startup")

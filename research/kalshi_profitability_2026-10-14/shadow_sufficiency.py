"""Read exported metadata only; never load trade rows, prices, outcomes, keys or TEST data.

This diagnoses missing evidence for a shadow study. It does not calculate returns
or certify execution coverage from metadata alone. Inputs are optional JSON objects
from the arena page block, recorder `status`, and recorder `verify` commands.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

MAX_BYTES = 256 * 1024


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def object_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def read_metadata(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Metadata exceeds the 256 KiB limit; do not pass raw tape")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Expected a metadata object, not a trade or outcome list")
    return value


def assess(arena: dict[str, Any], recorder: dict[str, Any], verify: dict[str, Any]) -> dict[str, Any]:
    """Emit allowlisted numeric/boolean metadata only, even if an input contains other fields."""
    arena = object_value(arena.get("kalshi_arena", arena))
    town, feed = object_value(arena.get("town")), object_value(arena.get("feed"))
    valid, void = number(town.get("windows")), number(town.get("void_windows"))
    coverage = valid / (valid + void) if valid is not None and void is not None and valid + void > 0 else None
    dropped, late = number(feed.get("dropped")), number(feed.get("late"))
    by_lane, status = object_value(recorder.get("bytes_by_lane")), object_value(recorder.get("status"))
    spot_bytes = number(by_lane.get("spot"))
    hashes_verified = verify.get("ok") is True and verify.get("mismatched") == []
    segments = number(verify.get("segments"))
    problems: list[str] = []
    if not arena:
        problems.append("arena_metadata_missing")
    if valid is None or valid == 0:
        problems.append("no_verified_complete_arena_windows")
    if coverage is None or coverage < 0.95:
        problems.append("arena_lifetime_coverage_below_95pct_or_unknown")
    if dropped is None or dropped > 0 or late is None or late > 0:
        problems.append("arena_feed_drops_or_lateness_need_window_level_audit")
    if not recorder:
        problems.append("recorder_metadata_missing")
    if status.get("read_only") is not True or status.get("order_capability") is not False:
        problems.append("recorder_read_only_receipt_missing")
    if number(status.get("storage_level")) != 0:
        problems.append("recorder_storage_shed_paused_or_unknown")
    if spot_bytes is None or spot_bytes <= 0:
        problems.append("no_sealed_spot_bytes_verified")
    if not hashes_verified or segments is None or segments <= 0:
        problems.append("retained_segment_hashes_unverified_or_empty")
    return {
        "scope": "metadata_only_no_profit_or_test_outcomes_read",
        "verdict": "INSUFFICIENT_EVIDENCE" if problems else "METADATA_CHECKS_ONLY",
        "profitability_established": False,
        "ready_for_comparison": False,
        "arena": {"complete_windows": valid, "void_windows": void, "lifetime_coverage_share": coverage,
                  "dropped_events": dropped, "late_events": late},
        "recorder": {"sealed_spot_bytes": spot_bytes, "segments": segments,
                     "retained_segment_hashes_verified": hashes_verified},
        "problems": problems,
        "still_required": ["frozen_activation_and_code_hash", "future_common_window_coverage",
                           "per_venue_spot_rows_and_timestamps", "causal_quote_and_print_alignment",
                           "queue_and_cancel_latency_model", "fee_and_settlement_terms"],
        "caveats": ["Lifetime arena counters do not establish coverage of a new cohort.",
                    "Sealed bytes prove neither per-venue completeness nor timely quotes.",
                    "Hashes prove retained-file integrity, not absence of missing data."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, help="Exported kalshi_arena page block or page object")
    parser.add_argument("--recorder-status", type=Path, help="Recorder status CLI JSON, including bytes_by_lane")
    parser.add_argument("--recorder-verify", type=Path, help="Recorder verify CLI JSON")
    args = parser.parse_args()
    try:
        report = assess(read_metadata(args.arena), read_metadata(args.recorder_status),
                        read_metadata(args.recorder_verify))
    except (OSError, ValueError, TypeError):
        parser.exit(2, "Cannot read bounded JSON metadata; no input contents were printed.\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The practice speed desk's opt-in arena fields: every default keeps today's behaviour exactly."""

from __future__ import annotations

import json
from typing import Any

from speeddesk_golden import FIXTURE, coverage, run

from nightcrawler.speeddesk_model import SpeedConfig

# What the pinned run must exercise, so the golden comparison means something.
COVERED = ("speeddesk_take:take", "speeddesk_fill:take", "speeddesk_rest:rest", "speeddesk_fill:rest",
           "speeddesk_cancel:reprice", "speeddesk_cancel:take_available", "speeddesk_cancel:ask_moved",
           "speeddesk_cancel:venue_feed_gap", "speeddesk_skip:maker_would_cross", "reason:balancing_only",
           "reason:starter_pending", "reason:window_budget", "reason:cutoff", "reason:day_stop", "settlement:")


def _first_difference(actual: dict[str, Any], expected: dict[str, Any]) -> str:
    for index, (got, want) in enumerate(zip(actual["events"], expected["events"], strict=False)):
        if got != want:
            return f"event {index}: {got} != {want}"
    if len(actual["events"]) != len(expected["events"]):
        return f"{len(actual['events'])} events, pinned {len(expected['events'])}"
    keys = [key for key in expected["state"] if actual["state"].get(key) != expected["state"][key]]
    return f"state differs in {keys}"


def test_default_config_reproduces_the_pinned_run() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = run(SpeedConfig())
    counts = coverage(actual)
    assert all(counts.get(key) for key in COVERED), sorted(counts)
    assert actual == expected, _first_difference(actual, expected)

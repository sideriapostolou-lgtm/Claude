"""Probability evidence is optional, bounded and never promoted into money or live controls."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fakes import load_fixture

from nightcrawler import pagestate

PROTOCOL = "kalshi-online-calibration-v1-h300-g5-b10-prior20"


def learning(**changes: Any) -> dict[str, Any]:
    return {"mode": "observe_only", "enabled": True, "live_application": False,
            "profitability_proven": False, "protocol": PROTOCOL, "source_fingerprint": "a" * 64,
            "history_protocol": PROTOCOL, "history_source_fingerprint": "a" * 64,
            "forecast_horizon_s": 300, "grace_s": 5, "bins": 10, "pending": 1,
            "forecasts": 3, "scored": 2, "unknown": 4, "brier_baseline": 0.4,
            "brier_shadow": 0.5, "error": None, **changes}


def page(make_settings: Any, raw: Any, *, include: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    case = load_fixture("kalshi_arena_page")["cases"]["fresh_with_candidate"]
    panel = copy.deepcopy(case["kalshi_arena"])
    if include:
        panel["learning"] = raw
    settings = make_settings(KALSHI_ARENA_ENABLED=True)
    path: Path = settings.data_dir / "kalshi_arena" / "panel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(panel))
    return pagestate.kalshi_arena_block(settings, case["generated_at"]), case["kalshi_arena"]


def test_learning_is_optional_and_does_not_change_any_existing_arena_field(make_settings: Any) -> None:
    block, old = page(make_settings, learning())
    assert {key: value for key, value in block.items() if key != "learning"} == old
    report = block["learning"]
    assert report["mode"] == "observe_only" and report["enabled"]
    assert report["live_application"] is False and report["profitability_proven"] is False
    assert report["brier_baseline"] == 0.4 and report["brier_shadow"] == 0.5
    assert report["unknown"] == 4
    assert "not certified" in report["coverage"]
    block, old = page(make_settings, None, include=False)
    assert block == old and "learning" not in block


def test_no_scored_observations_means_unknown_score_not_zero(make_settings: Any) -> None:
    block, _ = page(make_settings, learning(forecasts=1, scored=0, brier_baseline=None, brier_shadow=None))
    assert block["learning"]["brier_baseline"] is None
    assert block["learning"]["brier_shadow"] is None


@pytest.mark.parametrize("changes", [
    {"mode": "live"}, {"live_application": True}, {"profitability_proven": True},
    {"enabled": "true"}, {"protocol": "future-unknown-model"}, {"source_fingerprint": "z" * 64},
    {"forecast_horizon_s": 301}, {"grace_s": 6}, {"bins": 9}, {"scored": 4},
    {"pending": -1}, {"forecasts": True}, {"unknown": float("nan")},
    {"brier_baseline": -0.1}, {"brier_shadow": 1.01}, {"brier_shadow": float("inf")},
    {"brier_baseline": True}, {"brier_baseline": 10**400},
    {"history_source_fingerprint": "b" * 64}, {"history_protocol": "old"},
    {"history_source_fingerprint": "bad"},
    {"scored": 0, "brier_baseline": 0.0, "brier_shadow": None},
])
def test_invalid_learning_is_unknown_without_hiding_the_existing_town(make_settings: Any,
                                                                      changes: dict[str, Any]) -> None:
    block, old = page(make_settings, learning(**changes))
    assert block["learning"] is None
    assert {key: value for key, value in block.items() if key != "learning"} == old


def test_untrusted_extra_fields_never_enter_the_page_and_errors_are_redacted(make_settings: Any) -> None:
    raw = learning(enabled=False, error="sk-" + "a" * 40 + " " + "bad" * 200,
                   cash_usd=999999, pnl_usd=1000, promotion=True, payload={"nested": "private"})
    block, old = page(make_settings, raw)
    report = block["learning"]
    assert report["enabled"] is False and len(report["error"]) <= 160
    assert "sk-" + "a" * 40 not in json.dumps(report)
    assert not {"cash_usd", "pnl_usd", "promotion", "payload"} & report.keys()
    assert {key: value for key, value in block.items() if key != "learning"} == old


def test_disabled_history_keeps_its_identity_and_is_not_relabeled_as_current(make_settings: Any) -> None:
    old_protocol = "kalshi-online-calibration-v0"
    raw = learning(enabled=False, error="source_or_protocol_mismatch",
                   history_protocol=old_protocol, history_source_fingerprint="b" * 64)
    block, _ = page(make_settings, raw)
    report = block["learning"]
    assert report["protocol"] == PROTOCOL and report["history_protocol"] == old_protocol
    assert report["source_fingerprint"] != report["history_source_fingerprint"]
    assert report["scored"] == 2 and report["brier_shadow"] == 0.5
    raw["history_protocol"] = "sk-" + "a" * 40
    block, _ = page(make_settings, raw)
    assert block["learning"]["history_protocol"] == "unrecognized_history_protocol"


def test_exclusion_breakdown_preserves_unknowns_and_rejects_inconsistent_counts(make_settings: Any) -> None:
    reasons = dict.fromkeys(("startup_inside", "late", "invalid", "pregap", "terms_changed", "missing_label",
                             "outcome_known", "invalid_label", "capacity"), 0)
    reasons["startup_inside"], reasons["missing_label"] = 1, 3
    block, _ = page(make_settings, learning(exclusions=reasons))
    assert block["learning"]["exclusions"] == reasons
    reasons["missing_label"] = 2
    block, old = page(make_settings, learning(exclusions=reasons))
    assert block["learning"] is None
    assert {key: value for key, value in block.items() if key != "learning"} == old

"""Probability-only evidence stays separate from V1, simulated money and live authority."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fakes import load_fixture

from nightcrawler import pagestate

PROTOCOL = "kalshi-probability-calibration-v2-h300-g5-b10-prior20"
V1 = "kalshi-online-calibration-v1-h300-g5-b10-prior20"


def report(**changes: Any) -> dict[str, Any]:
    return {"mode": "observe_only", "enabled": True, "live_application": False,
            "profitability_proven": False, "protocol": PROTOCOL, "source_fingerprint": "a" * 64,
            "history_protocol": PROTOCOL, "history_source_fingerprint": "a" * 64,
            "forecast_horizon_s": 300, "grace_s": 5, "bins": 10, "pending": 1,
            "forecasts": 2, "scored": 1, "unknown": 0, "brier_baseline": 0.25,
            "brier_shadow": 0.25, "error": None, **changes}


def page(make_settings: Any, raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    case = load_fixture("kalshi_arena_page")["cases"]["fresh_with_candidate"]
    panel = copy.deepcopy(case["kalshi_arena"])
    panel["learning_probability"] = raw
    panel["learning"] = report(protocol=V1, history_protocol=V1, forecasts=0, scored=0,
                               pending=0, brier_baseline=None, brier_shadow=None)
    settings = make_settings(KALSHI_ARENA_ENABLED=True)
    path: Path = settings.data_dir / "kalshi_arena" / "panel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(panel))
    return pagestate.kalshi_arena_block(settings, case["generated_at"]), case["kalshi_arena"]


def test_two_observers_never_share_counts_or_change_existing_money(make_settings: Any) -> None:
    block, old = page(make_settings, report())
    assert {k: v for k, v in block.items() if k not in {"learning", "learning_probability"}} == old
    assert block["learning"]["protocol"] == V1
    assert block["learning"]["scored"] == 0
    assert block["learning"]["brier_baseline"] is None
    evidence = block["learning_probability"]
    assert evidence["protocol"] == PROTOCOL and evidence["scored"] == 1
    assert evidence["brier_baseline"] == 0.25
    assert not evidence["live_application"] and not evidence["profitability_proven"]
    assert "current probability inputs" in evidence["coverage"]


@pytest.mark.parametrize("change", [
    {"protocol": V1}, {"history_protocol": V1}, {"live_application": True},
    {"profitability_proven": True}, {"mode": "live"}, {"enabled": "yes"},
    {"source_fingerprint": "bad"}, {"history_source_fingerprint": "b" * 64},
    {"scored": 3}, {"forecasts": True}, {"brier_baseline": float("nan")},
    {"scored": 0, "brier_baseline": 0.0, "brier_shadow": None},
])
def test_invalid_probability_evidence_does_not_hide_v1_or_town(make_settings: Any,
                                                              change: dict[str, Any]) -> None:
    block, old = page(make_settings, report(**change))
    assert block["learning_probability"] is None
    assert block["learning"]["enabled"] and block["learning"]["scored"] == 0
    assert {k: v for k, v in block.items() if k not in {"learning", "learning_probability"}} == old


def test_probability_protocol_cannot_be_substituted_for_v1() -> None:
    assert pagestate._kalshi_learning_view(report()) is None
    assert pagestate._kalshi_learning_view(report(protocol=V1, history_protocol=V1),
                                         probability_only=True) is None


def test_unknown_scores_and_disabled_history_remain_unknown_and_separate(make_settings: Any) -> None:
    block, _ = page(make_settings, report(scored=0, brier_baseline=None, brier_shadow=None))
    assert block["learning_probability"]["brier_shadow"] is None
    raw = report(enabled=False, history_protocol="kalshi-probability-calibration-v0",
                 history_source_fingerprint="b" * 64, error="source_or_protocol_mismatch")
    block, _ = page(make_settings, raw)
    assert block["learning_probability"]["history_protocol"] == raw["history_protocol"]
    assert block["learning_probability"]["source_fingerprint"] != raw["history_source_fingerprint"]


def test_untrusted_extras_never_become_profit_or_controls(make_settings: Any) -> None:
    marker = "credential-" + "private" * 12
    block, _ = page(make_settings, report(enabled=False, error=marker, cash_usd=100,
                                         pnl_usd=999, promotion=True, secret=marker))
    evidence = block["learning_probability"]
    assert marker not in json.dumps(block)
    assert evidence["error"] == "learning_error"
    assert not {"cash_usd", "pnl_usd", "promotion", "secret"} & evidence.keys()


def test_input_exclusions_and_fixed_errors_are_kept_only_in_the_new_protocol(make_settings: Any) -> None:
    reasons = dict.fromkeys(("startup_inside", "late", "invalid", "pregap", "terms_changed", "missing_label",
                             "outcome_known", "invalid_label", "capacity", "invalid_batch", "invalid_strike"), 0)
    reasons["invalid_batch"], reasons["invalid_strike"] = 1, 2
    raw = report(enabled=False, error="raw_stream_invalid", unknown=3, exclusions=reasons)
    block, _ = page(make_settings, raw)
    assert block["learning_probability"]["exclusions"] == reasons
    assert block["learning_probability"]["error"] == "raw_stream_invalid"
    assert pagestate._kalshi_learning_view({**raw, "protocol": V1, "history_protocol": V1}) is None
    raw["exclusions"]["invalid_batch"] = 2
    block, _ = page(make_settings, raw)
    assert block["learning_probability"] is None
    assert block["learning"]["enabled"]

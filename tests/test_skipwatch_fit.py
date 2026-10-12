"""Prospective research tests use generated, clearly synthetic local journals."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from nightcrawler import skipwatch_fit as fit


def opportunity(at=10.25, *, side="up", fair=.5, **changes):
    return {"at": at, "observed_at": at, "window": "market-a", "side": side,
            "window_start": 0, "window_end": 300, "fair": fair,
            "bid": .4, "ask": .45, "bid_depth": 100, "ask_depth": 100, "bid_top_size": 30,
            "move_1s": 0, "move_5s": 0, "move_30s": 0, "prior_up": 0, "prior_down": 0,
            "imbalance": 0, "coverage": dict.fromkeys(("bitcoin", "book", "wallet", "trades"), True), **changes}


def wallet(at=11, observed=13, *, identity="fill-a", action="buy", **changes):
    return {"fill_id": identity, "market_id": "market-a", "exchange_at": at,
            "observed_at": observed, "side": "up", "action": action, "price": .4, "size": 24, **changes}


def journal(directory: Path, events, *, anchor=0):
    directory.mkdir(parents=True, exist_ok=True)
    previous = "0" * 64
    path = directory / "1970-01-01.jsonl"
    with path.open("w") as source:
        for sequence, (kind, payload, observed) in enumerate(sorted(events, key=lambda item: item[2]), 1):
            row = {"schema": 1, "seq": sequence, "kind": kind, "session_started_at": anchor,
                   "at": payload.get("at", payload.get("exchange_at", observed)),
                   "observed_at": observed, "payload": payload, "prev_hash": previous}
            previous = hashlib.sha256(fit._canonical(row)).hexdigest()
            row["hash"] = previous
            source.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def covered(seconds=100):
    return [("coverage", {"at": second, "wallet": True}, second) for second in range(seconds)]


def test_public_feed_schema_and_next_complete_second_labels_are_supported(tmp_path):
    events = covered() + [("opportunity", opportunity(), 10.25),
                          ("opportunity", opportunity(11.25), 11.25),
                          ("wallet_fill", wallet(), 13)]
    journal(tmp_path, events)
    with fit.Tape(tmp_path, 0, 100) as tape:
        rows = list(tape.opportunities(0, 100, Counter()))
    assert len(rows) == 2
    assert rows[0][1].quantity == 24 and rows[1][1].quantity == 0
    assert rows[0][0]["at"] < 11  # feature receipt precedes the entire target timestamp second


def test_fill_features_cannot_leak_into_opportunity_prediction(tmp_path):
    events = covered() + [("opportunity", opportunity(fair=.3), 10.25),
                          ("wallet_fill", wallet(), 13),
                          ("wallet_observation", {"fair": .99, "at": 11, "price": .01}, 15)]
    journal(tmp_path, events)
    with fit.Tape(tmp_path, 0, 100) as tape:
        result = fit.analyze(tape, "fit", 0, 100, fit.candidates())
    assert result["positive"] == 1
    assert all(score["fn"] == 1 and score["tp"] == 0 for score in result["scores"].values())


@pytest.mark.parametrize("failure", ["noncausal", "missing_feature", "wallet_gap", "explicit_gap", "late_fill"])
def test_bad_features_or_target_coverage_are_exclusions_not_negative_examples(tmp_path, failure):
    row = opportunity()
    events = covered()
    if failure == "noncausal":
        row["observed_at"] = 11
    elif failure == "missing_feature":
        row["fair"] = None
    elif failure == "wallet_gap":
        events[15] = ("coverage", {"at": 15, "wallet": False}, 15)
    elif failure == "explicit_gap":
        events.append(("gap", {"source": "wallet", "from": 14.1, "to": 14.2}, 14.2))
    else:
        events.append(("wallet_fill", wallet(observed=50), 50))
    events.append(("opportunity", row, 10.25))
    journal(tmp_path, events)
    with fit.Tape(tmp_path, 0, 100) as tape:
        excluded = Counter()
        assert list(tape.opportunities(0, 100, excluded)) == []
    assert sum(value for key, value in excluded.items() if key != "raw") == 1


def test_duplicate_rows_and_same_second_samples_do_not_inflate_recall(tmp_path):
    events = covered() + [("opportunity", opportunity(fair=.3), 10.25),
                          ("opportunity", opportunity(10.5, fair=.9), 10.5),
                          ("wallet_fill", wallet(), 13), ("wallet_fill", wallet(observed=14), 14)]
    journal(tmp_path, events)
    with fit.Tape(tmp_path, 0, 100) as tape:
        result = fit.analyze(tape, "fit", 0, 100, fit.candidates())
    assert result["rows"] == result["positive"] == 1
    assert result["median_positive_bin_size"] == 24
    assert result["exclusions"]["duplicate_second"] == 1
    assert all(score["tp"] == 0 for score in result["scores"].values())


def test_predict_all_baseline_reports_false_positives_and_candidate_precision_recall(tmp_path):
    events = covered()
    for index in range(10):
        at = 10.25 + index
        events.append(("opportunity", opportunity(at, fair=.5 if index % 2 else .3), at))
        if index % 2:
            events.append(("wallet_fill", wallet(at=11 + index, observed=13 + index, identity=str(index)), 13 + index))
    journal(tmp_path, events)
    with fit.Tape(tmp_path, 0, 100) as tape:
        result = fit.analyze(tape, "fit", 0, 100, fit.candidates(), prevalence=.5, size_estimate=20)
    score = result["scores"]["ask:0.02:30"]
    assert score["precision"] == score["recall"] == score["f1"] == 1
    assert result["baselines"]["always"]["precision"] == .5
    assert result["baselines"]["always"]["recall"] == 1
    assert result["sizing_mae_positive_bins"] == 4
    assert result["observed_quiet_fraction"] == .5
    assert result["fee_coverage"] is None and result["net_profit_usd"] is None


def test_fixed_grid_uses_best_level_not_five_level_depth_and_only_24_candidates():
    rules = fit.candidates()
    assert len(rules) == len({rule["id"] for rule in rules}) == 24
    rule = next(rule for rule in rules if rule["id"] == "bid_trend_depth:0.02:30")
    assert not fit.predicts(rule, opportunity(bid_top_size=1, bid_depth=10000))
    assert fit.predicts(rule, opportunity(bid_top_size=25))
    assert not fit.predicts(rule, opportunity(move_5s=-.001))


@pytest.mark.parametrize("corruption", ["hash", "partial", "sequence", "anchor"])
def test_corrupt_or_truncated_source_is_blocked_before_freeze(tmp_path, corruption):
    path = journal(tmp_path, covered())
    if corruption == "partial":
        with path.open("a") as source:
            source.write('{"seq":')
    else:
        lines = path.read_text().splitlines()
        row = json.loads(lines[4])
        if corruption == "hash":
            row["payload"]["wallet"] = False
        elif corruption == "sequence":
            row["seq"] = 999
        else:
            row["session_started_at"] = 1
        lines[4] = json.dumps(row)
        path.write_text("\n".join(lines) + "\n")
    result = fit.run_due(tmp_path, 48 * 3600, 0)
    assert result["status"] == "research_blocked"
    assert not (tmp_path / "research" / "frozen.json").exists()


def test_pending_and_insufficient_training_never_spend_test_or_invent_profit(tmp_path):
    pending = fit.run_due(tmp_path, 100, 0)
    assert pending["status"] == "collecting_train" and pending["summary"]["precision"] is None
    journal(tmp_path, covered() + [("opportunity", opportunity(), 10.25)])
    result = fit.run_due(tmp_path, 72 * 3600, 0)
    assert result["status"] == "insufficient_training" and result["holdout_status"] == "unread"
    assert not (tmp_path / "research" / "test.json").exists()
    assert result["live_promotion"] is False
    assert "feature_coverage_below_80pct" in result["fit"]["insufficient"]
    assert "not the wallet's exact private algorithm" in (tmp_path / "research" / "RULES.md").read_text()


def test_training_freeze_ignores_all_holdout_economic_content(tmp_path):
    base = covered() + [("opportunity", opportunity(), 10.25), ("wallet_fill", wallet(), 13)]
    outputs = []
    for index, price in enumerate((.01, .99)):
        directory = tmp_path / str(index)
        events = base + [("wallet_fill", wallet(at=48 * 3600 + 1, observed=48 * 3600 + 2, price=price), 48 * 3600 + 2)]
        journal(directory, events)
        outputs.append(fit.freeze(directory, 48 * 3600 + 60, 0))
    assert outputs[0] == outputs[1]
    assert outputs[0]["freeze_late_seconds"] == 60
    assert outputs[0]["stages_read"] == ["fit", "validation"]


def short_protocol(monkeypatch):
    # Test-only accelerated clocks/minimums exercise the exact state machine;
    # production constants remain 36/48/72 hours with full evidence thresholds.
    monkeypatch.setattr(fit, "FIT_HOURS", 120 / 3600)
    monkeypatch.setattr(fit, "TRAIN_HOURS", 240 / 3600)
    monkeypatch.setattr(fit, "TEST_HOURS", 360 / 3600)
    protocol = copy.deepcopy(fit.PROTOCOL)
    for name in ("fit", "validation", "test"):
        protocol["min_rows"][name] = 10
        protocol["min_positive"][name] = 5
        protocol["min_windows"][name] = 1
    monkeypatch.setattr(fit, "PROTOCOL", protocol)


def qualified_events():
    events = covered(361)
    for second in range(360):
        for side in ("up", "down"):
            positive = second % 2 == 0 and side == "up"
            start = (second // 300) * 300
            window = f"market-{start}"
            row = opportunity(second + .25, side=side, fair=.5 if positive else .3,
                              window=window, window_start=start, window_end=start + 300)
            events.append(("opportunity", row, second + .25))
            if positive:
                item = wallet(at=second + 1, observed=second + 2, identity=str(second), market_id=window)
                events.append(("wallet_fill", item, second + 2))
    return events


def test_frozen_choice_precedes_one_look_test_and_is_not_refitted(tmp_path, monkeypatch):
    short_protocol(monkeypatch)
    path = journal(tmp_path, qualified_events())
    frozen = fit.run_due(tmp_path, 240, 0)
    assert frozen["status"] == "frozen"
    assert not (tmp_path / "research" / "test.json").exists()
    trained_bytes = (tmp_path / "research" / "frozen.json").read_bytes()
    tested = fit.run_due(tmp_path, 360, 0)
    assert tested["status"] == "predictive_pattern_only"
    assert tested["test"]["scores"][tested["candidate"]["id"]]["precision"] == 1
    assert tested["summary"]["stage"] == "held_out"
    saved = (tmp_path / "research" / "test.json").read_bytes()
    path.write_text("changed source after the one-look result\n")
    again = fit.run_due(tmp_path, 400, 0)
    assert again["status"] == "predictive_pattern_only"
    assert (tmp_path / "research" / "test.json").read_bytes() == saved
    assert (tmp_path / "research" / "frozen.json").read_bytes() == trained_bytes


def test_test_cannot_run_without_freeze_or_before_third_period_finishes(tmp_path, monkeypatch):
    short_protocol(monkeypatch)
    journal(tmp_path, qualified_events())
    with pytest.raises(fit.ResearchDataError, match="frozen"):
        fit.evaluate(tmp_path, 360, 0)
    fit.freeze(tmp_path, 240, 0)
    with pytest.raises(fit.ResearchDataError, match="not complete"):
        fit.evaluate(tmp_path, 359, 0)


def test_protocol_change_does_not_silently_reselect_a_frozen_rule(tmp_path, monkeypatch):
    journal(tmp_path, covered())
    fit.freeze(tmp_path, 48 * 3600, 0)
    monkeypatch.setattr(fit, "PLAN_HASH", "different-research-protocol")
    result = fit.run_due(tmp_path, 48 * 3600, 0)
    assert result["status"] == "research_blocked" and not result["live_promotion"]


def test_lossless_compressed_batches_produce_identical_research_inputs(tmp_path):
    from nightcrawler.skipwatch_journal import ObservationJournal

    events = covered() + [("opportunity", opportunity(), 10.25), ("wallet_fill", wallet(), 13)]
    plain, compressed = tmp_path / "plain", tmp_path / "compressed"
    journal(plain, events)
    compressed.mkdir()
    writer = ObservationJournal(compressed)
    try:
        for kind, payload, observed in sorted(events, key=lambda item: item[2]):
            writer.append(kind, payload, payload.get("at", payload.get("exchange_at", observed)), observed, 0)
        writer.flush(0)
        writer.seal()
    finally:
        writer.close()
    assert list(compressed.glob("*.jsonl.gz"))
    with fit.Tape(plain, 0, 100) as first, fit.Tape(compressed, 0, 100) as second:
        assert first.digest.hexdigest() == second.digest.hexdigest()
        assert fit.analyze(first, "fit", 0, 100, fit.candidates()) == fit.analyze(second, "fit", 0, 100, fit.candidates())


def test_saved_research_artifact_cannot_be_silently_changed(tmp_path):
    journal(tmp_path, covered())
    fit.freeze(tmp_path, 48 * 3600, 0)
    path = tmp_path / "research" / "frozen.json"
    artifact = json.loads(path.read_text())
    artifact["candidate"]["edge"] = .99
    path.write_text(json.dumps(artifact))
    assert fit.run_due(tmp_path, 72 * 3600, 0)["status"] == "research_blocked"


def test_packaged_cli_returns_small_pending_status_without_source_or_network(tmp_path):
    completed = subprocess.run([sys.executable, "-m", "nightcrawler.skipwatch_fit", "--data-dir", str(tmp_path),
                                "--now", "100", "--session-started-at", "0"],
                               capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["status"] == "collecting_train" and result["summary"]["precision"] is None
    assert result["freeze_due_at"] == 48 * 3600 and result["test_due_at"] == 72 * 3600
    assert len(completed.stdout) < 2000 and completed.stderr == ""


def test_integrity_failure_is_persisted_and_never_repeats_the_expensive_scan(tmp_path, monkeypatch):
    path = journal(tmp_path, covered())
    with path.open("a") as source:
        source.write("truncated")
    first = fit.run_due(tmp_path, 48 * 3600, 0)
    assert first["status"] == "research_blocked"
    assert (tmp_path / "research" / "blocked.json").exists()

    def no_read(*args, **kwargs):
        pytest.fail("A blocked phase reread the source archive")

    monkeypatch.setattr(fit, "Tape", no_read)
    second = fit.run_due(tmp_path, 72 * 3600, 0)
    assert second["status"] == "research_blocked" and second["phase"] == "train_freeze"


def test_unknown_public_outcome_excludes_both_labels_instead_of_false_negatives(tmp_path):
    events = covered() + [("opportunity", opportunity(), 10.25),
                          ("opportunity", opportunity(side="down"), 10.25),
                          ("wallet_fill", wallet(side="unknown"), 13)]
    journal(tmp_path, events)
    with fit.Tape(tmp_path, 0, 100) as tape:
        exclusions = Counter()
        assert list(tape.opportunities(0, 100, exclusions)) == []
        assert exclusions["late_or_ambiguous_label"] == 2

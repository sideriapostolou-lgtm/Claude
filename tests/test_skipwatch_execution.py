"""Synthetic execution/proxy research evidence, with no account or network calls."""

from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest
from test_skipwatch_fit import journal, opportunity, wallet

from nightcrawler import skipwatch_execution as execution
from nightcrawler.skipwatch_fit import ResearchDataError


def prediction(identity, at=10, price=.45, side="up", window="market-a"):
    return execution.Prediction(identity, window, side, price, at)


def label(identity, at=11, price=.45, side="up", print_id=None, **changes):
    return execution.FillLabel(identity, "market-a", side, price, at, print_id or identity, **changes)


def recorded_pair(*, at=10.25, issued=10.3, changes=None):
    recorder = execution.PredictionRecorder(0)
    up = opportunity(at, side="up", **(changes or {}))
    down = opportunity(at, side="down", fair=.4)
    assert recorder.observe(up, seq=1, issued_at=issued, monotonic_ns=1, clock_id="synthetic") == []
    batches = recorder.observe(down, seq=2, issued_at=issued, monotonic_ns=2, clock_id="synthetic")
    return recorder, up, down, batches


def test_recorder_commits_one_side_per_candidate_and_keeps_baselines_separate():
    _, _, _, batches = recorded_pair()
    assert len(batches) == 1
    batch = batches[0]
    assert batch["scope"] == "unqualified_public_event_shadow"
    assert batch["qualified_epoch_started_at"] is None
    assert batch["causal_execution_timing_verified"] is False
    assert batch["feature_prefix_seq"] == 2
    predictions = batch["predictions"]
    regular = [row for row in predictions if not row["candidate_id"].startswith("baseline:")]
    assert len({row["candidate_id"] for row in regular}) == len(regular)
    assert all(row["side"] == "up" for row in regular)
    assert len({row["prediction_id"] for row in predictions}) == len(predictions)
    dense = [row for row in predictions if row["candidate_id"] == "baseline:dense_both_sides"]
    assert {row["side"] for row in dense} == {"up", "down"}


@pytest.mark.parametrize("changes", [
    {"fair": None}, {"observed_at": 11}, {"bid": .7}, {"move_5s": None},
    {"coverage": {"bitcoin": True, "book": True, "wallet": False, "trades": True}},
    {"bitcoin_venues": {"kraken": {"received_at": 11}}},
])
def test_missing_future_or_uncovered_features_cannot_issue_predictions(changes):
    _, _, _, batches = recorded_pair(changes=changes)
    assert batches == []


def test_stale_features_and_unequal_snapshot_times_do_not_combine():
    _, _, _, batches = recorded_pair(issued=12)
    assert batches == []
    recorder = execution.PredictionRecorder(0)
    recorder.observe(opportunity(10.1), seq=1, issued_at=10.2, monotonic_ns=1, clock_id="clock")
    assert recorder.observe(opportunity(10.2, side="down"), seq=2,
                            issued_at=10.3, monotonic_ns=2, clock_id="clock") == []


def test_earliest_same_second_feature_is_used_without_better_quote_selection():
    recorder = execution.PredictionRecorder(0)
    first = opportunity(fair=.3)
    recorder.observe(first, seq=1, issued_at=10.3, monotonic_ns=1, clock_id="clock")
    recorder.observe(opportunity(fair=.99), seq=2, issued_at=10.3, monotonic_ns=2, clock_id="clock")
    batches = recorder.observe(opportunity(side="down", fair=.3), seq=3,
                               issued_at=10.3, monotonic_ns=3, clock_id="clock")
    assert batches
    assert all(row["candidate_id"].startswith("baseline:") for row in batches[0]["predictions"])


def test_replay_preserves_shadow_origin_and_prevents_duplicate_predictions():
    recorder, up, down, batches = recorded_pair()
    restored = execution.PredictionRecorder(0)
    restored.restore("execution_prediction_batch", batches[0])
    assert restored.started_at == recorder.started_at
    for side, row in enumerate((up, down), 10):
        assert restored.observe(row, seq=side, issued_at=10.5, monotonic_ns=side, clock_id="new-clock") == []
    wrong = execution.PredictionRecorder(1)
    with pytest.raises(ResearchDataError, match="origin"):
        wrong.restore("execution_prediction_batch", batches[0])


def test_one_prediction_cannot_claim_multiple_source_fill_fragments():
    report = execution.score([prediction("p")], [label("a"), label("b", at=11.1)])
    assert report["source_fill_rows"] == 2
    assert report["public_event_proxy"]["hits"] == 1
    assert report["public_event_proxy"]["recall_all_observed_fills"] == .5
    assert report["strict"]["recall_upper_bound"] == .5
    assert report["strict_gate_passed"] is report["live_promotion"] is False


def test_unlinked_rows_remain_in_all_fill_denominator_and_upper_bounds_have_unit_capacity():
    report = execution.score([prediction("p")], [label("a"), execution.FillLabel("unknown", "market-a", "up", .45)])
    assert report["public_event_proxy"]["linkage_coverage"] == .5
    assert report["public_event_proxy"]["recall_identifiable_subset"] == 1
    assert report["public_event_proxy"]["recall_all_observed_fills"] == .5
    assert report["strict"]["recall_lower_bound"] == 0
    assert report["strict"]["recall_upper_bound"] == .5


def test_reusing_same_print_for_two_wallet_rows_makes_both_associations_ambiguous():
    report = execution.score([prediction("a"), prediction("b", at=10.5)],
                             [label("a", print_id="same-print"), label("b", print_id="same-print")])
    assert report["public_event_proxy"]["hits"] == 0
    assert report["public_event_proxy"]["identified_fill_rows"] == 0


def test_false_predictions_and_wrong_sides_cannot_hide_behind_recall():
    report = execution.score([prediction("correct"), prediction("spam", at=10.5), prediction("wrong", side="down")],
                             [label("fill")])
    assert report["public_event_proxy"]["recall_all_observed_fills"] == 1
    assert report["public_event_proxy"]["precision_all_predictions"] == pytest.approx(1/3)
    assert report["strict"]["confirmed_false_positives_lower_bound"] == 2
    assert report["anti_spam_passed"] is False


@pytest.mark.parametrize("at,price,expected", [(11, .45, 0), (12, .45, 0), (5.999, .45, 0),
                                               (6, .45, 1), (10, .47, 1), (10, .4701, 0)])
def test_public_proxy_uses_pre_event_five_second_and_two_cent_limits(at, price, expected):
    report = execution.score([prediction("p", at=at, price=price)], [label("f", at=11)])
    assert report["public_event_proxy"]["hits"] == expected


def test_augmenting_paths_avoid_greedy_under_count_without_reusing_rows():
    report = execution.score([prediction("a", price=.5), prediction("b", at=10.5, price=.51)],
                             [label("x", price=.5), label("y", price=.48)])
    assert report["public_event_proxy"]["hits"] == 2
    assert set(map(tuple, report["public_event_proxy"]["assignments"])) == {("a", "y"), ("b", "x")}


def test_arbitrary_execution_claim_cannot_qualify_unknown_clock_evidence():
    fill = label("f", execution_low=11, execution_high=11.001,
                 timing_evidence_hash="someone-said-execution", settled_identity_verified=True)
    report = execution.score([prediction("p")], [fill])
    assert report["public_event_proxy"]["hits"] == 1
    assert report["strict"]["hits"] == 0
    assert report["timing_validated"] is report["strict_gate_passed"] is False


def test_future_qualified_interval_still_requires_prediction_before_earliest_execution(monkeypatch):
    monkeypatch.setattr(execution, "QUALIFIED_EXECUTION_TIMING", frozenset({"synthetic-reviewed-evidence"}))
    good = label("good", execution_low=10.5, execution_high=11,
                 timing_evidence_hash="synthetic-reviewed-evidence", settled_identity_verified=True)
    ambiguous = label("clock-overlap", execution_low=9.9, execution_high=10.5,
                      timing_evidence_hash="synthetic-reviewed-evidence", settled_identity_verified=True)
    report = execution.score([prediction("p")], [good, ambiguous])
    assert report["strict"]["hits"] == 1
    assert report["strict_gate_passed"] is False  # No qualified epoch or held-out gate exists yet.


def journal_fixture(tmp_path, *, corrupt_prefix=False):
    _, up, down, batches = recorded_pair()
    batch = batches[0]
    if corrupt_prefix:
        batch["feature_evidence"][0]["hash"] = "changed"
    fill = wallet(at=14, observed=15, slug="btc-updown-5m-0", price=.45, identity="fill")
    observation = {"fill_id": "fill", "window_start": 0, "confidence": "inferred",
                   "match_method": "transaction_token_price_size", "candidate_evidence": [
                       {"trade_id": "print", "at": 11, "price": .45, "size": 24}]}
    journal(tmp_path, [("opportunity", up, 10.25), ("opportunity", down, 10.25),
                       ("execution_prediction_batch", batch, 10.3), ("wallet_fill", fill, 15),
                       ("wallet_observation", observation, 16)])


def test_journal_proxy_audit_validates_feature_evidence_and_reports_anti_spam_baselines(tmp_path):
    journal_fixture(tmp_path)
    report = execution.score_journal(tmp_path, cohort_start=0, cohort_end=300, candidate_id="ask:0.02:30")
    assert report["public_event_proxy"]["hits"] == 1
    assert report["held_out"] is report["strict_gate_passed"] is False
    assert report["eligible_decision_bins"] == 1 and report["expected_decision_bins"] == 300
    assert report["baselines"]["baseline:never"]["predictions"] == 0
    assert report["baselines"]["baseline:dense_both_sides"]["public_event_proxy"]["precision_all_predictions"] == .5


def test_journal_rejects_missing_or_changed_feature_prefix(tmp_path):
    journal_fixture(tmp_path, corrupt_prefix=True)
    with pytest.raises(ResearchDataError, match="feature evidence"):
        execution.score_journal(tmp_path, cohort_start=0, cohort_end=300, candidate_id="ask:0.02:30")


def test_unknown_market_membership_cannot_create_confirmed_false_positives(tmp_path):
    _, up, down, batches = recorded_pair()
    unknown = wallet(identity="scope-unknown", at=14, observed=15, slug="")
    journal(tmp_path, [("opportunity", up, 10.25), ("opportunity", down, 10.25),
                       ("execution_prediction_batch", batches[0], 10.3), ("wallet_fill", unknown, 15)])
    report = execution.score_journal(tmp_path, cohort_start=0, cohort_end=300, candidate_id="ask:0.02:30")
    assert report["source_scope_unknown_fill_rows"] == 1
    assert report["all_source_fills_denominator"] is False
    assert report["source_fill_rows_upper_bound"] == 1
    assert report["strict"]["confirmed_false_positives_lower_bound"] == 0
    assert report["public_event_proxy"]["recall_all_observed_fills"] is None


def test_sell_and_unknown_actions_are_in_the_owner_all_fill_target_denominator():
    report = execution.score([prediction("p")], [label("buy"), label("sell", action="sell"),
                                                 label("missing-action", action="unknown")])
    assert report["source_fill_rows"] == 3
    assert report["source_actions"] == {"buy": 1, "sell": 1, "unknown": 1}
    assert report["public_event_proxy"]["recall_all_observed_fills"] == pytest.approx(1/3)
    sell_only = execution.score([prediction("p")], [label("sell", action="sell")])
    assert sell_only["strict"]["recall_upper_bound"] == 0
    assert sell_only["public_event_proxy"]["hits"] == 0


def test_wallet_sell_is_not_silently_filtered_from_journal_cohort(tmp_path):
    sell = wallet(identity="sell", action="SELL", slug="btc-updown-5m-0")
    journal(tmp_path, [("wallet_fill", sell, 13)])
    report = execution.score_journal(tmp_path, cohort_start=0, cohort_end=300, candidate_id="ask:0.02:30")
    assert report["source_fill_rows"] == 1 and report["source_actions"] == {"sell": 1}


def test_explicit_cli_proxy_report_cannot_unpause_default_fitting(tmp_path):
    journal_fixture(tmp_path)
    command = [sys.executable, "-m", "nightcrawler.skipwatch_fit", "--data-dir", str(tmp_path),
               "--session-started-at", "0", "--now", "400"]
    completed = subprocess.run([*command, "--execution-score", "--cohort-start", "0", "--cohort-end", "300"],
                               text=True, capture_output=True, check=True)
    status = json.loads(completed.stdout)
    assert status["status"] == "awaiting_verified_execution_time"
    assert status["strict_gate_passed"] is status["live_promotion"] is False
    artifact = json.loads(next((tmp_path / "research" / "execution").glob("proxy-*.json")).read_text())
    assert artifact["public_event_proxy"]["hits"] == 1 and artifact["held_out"] is False
    again = json.loads(subprocess.run(command, text=True, capture_output=True, check=True).stdout)
    assert again["status"] == "awaiting_verified_execution_time"
    assert again["automatic_verdict_scheduled"] is False
    assert not (tmp_path / "research" / "frozen.json").exists()


def test_mutated_or_repeated_identities_do_not_inflate_statistics():
    with pytest.raises(ResearchDataError, match="not unique"):
        execution.score([prediction("p"), prediction("p")], [label("f")])
    with pytest.raises(ResearchDataError, match="not unique"):
        execution.score([prediction("p")], [label("f"), label("f")])
    invalid = copy.copy(label("f", price=float("nan")))
    with pytest.raises(ResearchDataError, match="Nonfinite"):
        execution.score([], [invalid])

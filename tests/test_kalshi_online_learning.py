from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

import pytest

from nightcrawler.kalshi_online_learning import (
    MAX_PENDING,
    MAX_RECENT,
    OnlineLearning,
    fair_up,
)
from nightcrawler.speeddesk_model import Window


def window(start: float = 1000) -> Window:
    return Window(f"KXBTC15M-{int(start)}", start, start + 900, 100, venue="kalshi")


def advance(learner: OnlineLearning, w: Window, now: float, **kw: Any) -> None:
    learner.discover([w], now)
    learner.advance([w], kw.get("spot", 100), kw.get("sigma", .001), kw.get("bitcoin_at", now),
                    kw.get("outcomes", {}), now, kw.get("degraded", {}))


def ready() -> tuple[OnlineLearning, Window]:
    learner, w = OnlineLearning(900), window()
    advance(learner, w, 900)
    return learner, w


def test_frozen_prequential_score_then_update_includes_untraded() -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    f = copy.deepcopy(learner.pending[w.slug]["forecast"])
    assert f["p"] == fair_up(100, 100, .001, 600, settles_on_average=True)
    assert f["q"] == f["p"] == .5 and f["n"] == 0
    advance(learner, w, 1900, outcomes={w.slug: True})
    assert learner.counts["scored"] == 1
    assert learner.brier_p == learner.brier_q == .25
    assert learner.recent[-1]["forecast"] == f
    later = window(2000)
    advance(learner, later, 1950)
    advance(learner, later, 2300)
    assert learner.pending[later.slug]["forecast"]["q"] == 11 / 21
    advance(learner, later, 2400)
    assert learner.counts["forecasts"] == 2


@pytest.mark.parametrize("elapsed,expected", [(299, 0), (300, 1), (305, 1), (305.001, 0)])
def test_actual_clock_horizon_grace(elapsed: float, expected: int) -> None:
    learner, w = ready()
    advance(learner, w, w.start + elapsed)
    assert learner.counts["forecasts"] == expected
    if elapsed > 305:
        assert learner.counts["late"] == learner.counts["unknown"] == 1


@pytest.mark.parametrize("changes", [{"spot": float("nan")}, {"sigma": -.1}, {"bitcoin_at": 1296.9},
                                     {"bitcoin_at": 1300.1}, {"spot": 0}])
def test_invalid_first_due_input_final_no_later_cherry_pick(changes: dict[str, Any]) -> None:
    learner, w = ready()
    advance(learner, w, 1300, **changes)
    advance(learner, w, 1301)
    assert learner.counts["forecasts"] == 0
    assert learner.counts["unknown"] == learner.counts["invalid"] == 1


def test_zero_sigma_is_supported_and_probability_one_bin_is_bounded() -> None:
    learner, w = ready()
    advance(learner, w, 1300, sigma=0, spot=101)
    assert learner.pending[w.slug]["forecast"]["p"] == 1
    assert learner.pending[w.slug]["forecast"]["bin"] == 9


def test_startup_inside_early_outcome_same_frame_and_late_discovery() -> None:
    w = window()
    learner = OnlineLearning(1100)
    advance(learner, w, 1100)
    assert learner.counts["startup_inside"] == 1
    learner, w = ready()
    advance(learner, w, 1300, outcomes={w.slug: False})
    assert learner.counts["forecasts"] == 0 and learner.counts["outcome_known"] == 1


def test_gap_before_forecast_unknown_but_gap_after_preserves_frozen_score() -> None:
    learner, w = ready()
    learner.gap([w.slug], True, True, 1100)
    advance(learner, w, 1300)
    assert learner.counts["pregap"] == 1
    learner, w = ready()
    advance(learner, w, 1300)
    learner.gap([w.slug], False, True, 1400)
    advance(learner, w, 1900, outcomes={w.slug: False}, degraded={w.slug: "feed_late"})
    assert learner.counts["scored"] == 1 and learner.brier_q == .25
    assert learner.recent[-1]["post_gaps"] == ["explicit_feed_gap"]


def test_terms_and_known_strike_changes_explicit_unknown() -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    advance(learner, replace(w, start_price=101), 1400)
    assert learner.counts["terms_changed"] == 1
    advance(learner, w, 1900, outcomes={w.slug: True})
    assert learner.counts["scored"] == 0


def test_missing_opening_completed_before_forecast_only() -> None:
    learner, w = OnlineLearning(900), replace(window(), start_price=None)
    advance(learner, w, 900)
    w = replace(w, start_price=100, venue_start_price=100.1)
    advance(learner, w, 1000)
    advance(learner, w, 1300)
    f = learner.pending[w.slug]["forecast"]
    assert f["opening"] == 100 and f["venue_start_price"] == 100.1


def test_out_of_order_labels_not_settlement_highwater_and_duplicates_conflicts() -> None:
    learner, one = ready()
    two = window(1900)
    learner.discover([two], 900)
    advance(learner, one, 1300)
    advance(learner, two, 2200)
    learner.labels_received([(two.slug, True)], 2800)
    learner.labels_received([(one.slug, False)], 2801)
    learner.labels_received([(one.slug, False)], 2802)
    learner.advance([one, two], 100, .001, 2802, {}, 2802, {})
    assert learner.counts["scored"] == 2
    learner.labels_received([(one.slug, True)], 2803)
    assert learner.counts["scored"] == 2 and not learner.enabled


def test_original_wire_non_boolean_cannot_become_true_outcome() -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    learner.labels_received([(w.slug, "no")], 1900)
    advance(learner, w, 1900, outcomes={w.slug: True})
    assert learner.counts["scored"] == 0 and learner.counts["invalid_label"] == 1


def test_missing_label_timeout_unknown_and_no_reconstruction() -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    advance(learner, w, 9101)
    assert learner.counts["missing_label"] == 1 and learner.counts["scored"] == 0
    learner.labels_received([(w.slug, False)], 9200)
    advance(learner, w, 9200)
    assert learner.counts["forecasts"] == 1 and learner.counts["scored"] == 0


def test_restart_pending_survives_and_same_label_exactly_once() -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    raw = json.loads(json.dumps(learner.state()))
    restarted = OnlineLearning(1500)
    restarted.restore(raw, 1500)
    advance(restarted, w, 1900, outcomes={w.slug: False})
    again = OnlineLearning(1950)
    again.restore(json.loads(json.dumps(restarted.state())), 1950)
    advance(again, w, 1950, outcomes={w.slug: False})
    assert again.counts["scored"] == again.counts["forecasts"] == 1


@pytest.mark.parametrize("field,value", [("protocol", "old"), ("source_fingerprint", "0" * 64)])
def test_mismatch_disables_preserves_counts(field: str, value: str) -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    raw = copy.deepcopy(learner.state()); raw[field] = value
    other = OnlineLearning(1400)
    other.restore(raw, 1400)
    assert not other.enabled and other.counts["forecasts"] == 1
    assert w.slug in other.pending and other.error == "source_or_protocol_mismatch"


@pytest.mark.parametrize("raw", [{}, {"pending": []}, {"counts": float("nan")}, [1, 2]])
def test_malformed_optional_restore_is_contained(raw: Any) -> None:
    other = OnlineLearning(900)
    other.restore(raw, 900)
    assert not other.enabled and other.error == "malformed_optional_learning_state"


def test_size_capacity_and_monotonic_admission_dedup() -> None:
    learner = OnlineLearning(0)
    for i in range(200):
        w = window(1000 + i * 900)
        learner.discover([w], 0)
    assert len(learner.pending) == MAX_PENDING
    assert len(json.dumps(learner.state())) < 30000
    learner, w = ready()
    for i in range(150):
        w = window(1000 + i * 900)
        learner.discover([w], w.start - 1)
        advance(learner, w, w.start + 300)
        advance(learner, w, w.end, outcomes={w.slug: bool(i % 2)})
    assert len(learner.recent) == len(learner.labels) == MAX_RECENT
    learner.discover([window()], 200000)
    assert learner.counts["forecasts"] == learner.counts["scored"] == 150
    assert len(json.dumps(learner.state())) < 60000


def test_no_network_account_or_order_dependencies() -> None:
    import ast
    import inspect

    import nightcrawler.kalshi_online_learning as module
    tree = ast.parse(inspect.getsource(module))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and any(part in name for part in ("client", "broker", "config", "ledger", "live"))
                   for name in imports)
    assert module.OnlineLearning(900).panel()["live_application"] is False


@pytest.mark.parametrize("field,value", [("q", .9), ("p", .3), ("bin", 0), ("bitcoin_at", 0),
                                        ("protocol", "bad"), ("n", -1)])
def test_malformed_frozen_prediction_disables_only_learning(field: str, value: Any) -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    raw = copy.deepcopy(learner.state())
    raw["pending"][w.slug]["forecast"][field] = value
    other = OnlineLearning(1400)
    other.restore(raw, 1400)
    assert not other.enabled and other.restore_rejected


def test_status_logs_are_structured_and_errors_fixed_codes(caplog: Any) -> None:
    learner, _ = ready()
    learner.disable("untrusted arbitrary text")
    assert learner.panel()["error"] == "optional_learning_method_failed"
    import logging
    with caplog.at_level(logging.INFO):
        learner.status(900)
    payload = json.loads(caplog.records[-1].message.split(" ", 1)[1])
    assert payload["mode"] == "observe_only" and payload["live_application"] is False
    assert payload["profitability_proven"] is False
    assert len(payload["source_fingerprint"]) == 64


@pytest.mark.parametrize("restart_at,forecasted", [(950, True), (1001, False), (1301, False), (1306, False)])
def test_restart_unforecasted_started_window_never_reconstructed(restart_at: float, forecasted: bool) -> None:
    learner, w = ready()
    state = copy.deepcopy(learner.state())
    other = OnlineLearning(restart_at)
    other.restore(state, restart_at)
    advance(other, w, max(restart_at, 1301))
    assert bool(other.counts["forecasts"]) is forecasted
    if not forecasted:
        assert other.counts["startup_inside"] == other.counts["unknown"] == 1


def test_mismatch_retains_history_identity_through_two_checkpoints() -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    state = copy.deepcopy(learner.state())
    state["source_fingerprint"] = "0" * 64
    for now in (1400, 1500):
        other = OnlineLearning(now)
        other.restore(state, now)
        assert not other.enabled and other.counts["forecasts"] == 1
        assert other.panel()["history_source_fingerprint"] == "0" * 64
        assert other.panel()["source_fingerprint"] != "0" * 64
        state = json.loads(json.dumps(other.state()))
        assert state["source_fingerprint"] == "0" * 64


@pytest.mark.parametrize("n,wins", [(10, 5), (1, 0), (1, 1)])
def test_restored_prediction_cannot_claim_unobserved_bin_history(n: int, wins: int) -> None:
    learner, w = ready()
    advance(learner, w, 1300)
    raw = copy.deepcopy(learner.state()); f = raw["pending"][w.slug]["forecast"]
    f["n"], f["wins"] = n, wins
    f["q"] = (wins + 20 * f["p"]) / (n + 20)
    other = OnlineLearning(1400); other.restore(raw, 1400)
    assert not other.enabled and other.restore_rejected


def test_restart_keeps_frozen_prediction_with_explicit_coverage_gap() -> None:
    learner, w = ready(); advance(learner, w, 1300)
    other = OnlineLearning(1400); other.restore(copy.deepcopy(learner.state()), 1400)
    assert other.pending[w.slug]["post_gaps"] == ["child_restart_gap"]
    advance(other, w, 1900, outcomes={w.slug: False})
    assert other.counts["scored"] == 1
    assert other.recent[-1]["post_gaps"] == ["child_restart_gap"]


@pytest.mark.parametrize("received,scored", [(9099, True), (9100, True), (9100.001, False)])
def test_label_deadline_uses_actual_receipt_not_processing_order(received: float, scored: bool) -> None:
    learner, w = ready(); advance(learner, w, 1300)
    learner.labels_received([(w.slug, False)], received)
    # A timely queued original label may be processed later; a late receipt cannot.
    advance(learner, w, 10000)
    assert bool(learner.counts["scored"]) is scored
    assert learner.counts["missing_label"] == int(not scored)


@pytest.mark.parametrize("first_outcome,altered_wins", [(True, 0), (False, 1)])
def test_restore_checks_bin_wins_and_losses_not_just_total_n(first_outcome: bool, altered_wins: int) -> None:
    learner, w = ready(); advance(learner, w, 1300)
    advance(learner, w, 1900, outcomes={w.slug: first_outcome})
    next_window = window(2000); advance(learner, next_window, 1950); advance(learner, next_window, 2300)
    raw = copy.deepcopy(learner.state()); f = raw["pending"][next_window.slug]["forecast"]
    f["wins"] = altered_wins; f["q"] = (altered_wins + 20 * f["p"]) / (f["n"] + 20)
    other = OnlineLearning(2400); other.restore(raw, 2400)
    assert not other.enabled and other.restore_rejected


@pytest.mark.parametrize("changes", [{"start_price": 101}, {"end": 1901}, {"venue": "other"}])
def test_restart_after_end_still_checks_terms_of_existing_pending(changes: dict[str, Any]) -> None:
    learner, w = ready(); advance(learner, w, 1300)
    restored = OnlineLearning(2000); restored.restore(copy.deepcopy(learner.state()), 2000)
    changed = replace(w, **changes)
    advance(restored, changed, 2100, outcomes={w.slug: False})
    assert restored.counts["terms_changed"] == 1 and restored.counts["scored"] == 0


def test_invalid_label_clock_cannot_poison_optional_checkpoint() -> None:
    learner, w = ready(); advance(learner, w, 1300)
    learner.labels_received([(w.slug, False)], float("nan"))
    assert not learner.enabled
    json.dumps(learner.state(), allow_nan=False)


def test_panel_has_fixed_exclusion_reason_counts() -> None:
    learner, w = ready(); advance(learner, w, 1306)
    exclusions = learner.panel()["exclusions"]
    assert exclusions["late"] == 1
    assert set(exclusions) == {"startup_inside", "late", "invalid", "pregap", "terms_changed",
                               "missing_label", "outcome_known", "invalid_label", "capacity"}

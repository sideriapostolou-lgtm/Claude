"""Prospective V2 conditional forecasts; synthetic inputs, no venue clients."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

import pytest

from nightcrawler import kalshi_probability_learning as probability
from nightcrawler.kalshi_probability_learning import ProbabilityLearning
from nightcrawler.speeddesk_model import Window


def window(start: float = 1000) -> Window:
    return Window(f"KXBTC15M-{int(start)}", start, start + 900, 100, venue_start_price=100,
                  fee_rounding="kalshi", venue="kalshi")


def batch(learner: ProbabilityLearning, at: float, *, seq: int | None = None,
          dropped: int = 0, source_at: float | None = None) -> None:
    learner.batch(("batch", seq if seq is not None else (learner.batch_seq or 0) + 1,
                   at if source_at is None else source_at, dropped, 0, []), at)
    learner.batch_complete()


def setup(w: Window | None = None) -> tuple[ProbabilityLearning, Window]:
    w = w or window()
    learner = ProbabilityLearning(900)
    learner.discover([w], 900)
    return learner, w


def predict(learner: ProbabilityLearning, w: Window, at: float = 1300, **values: Any) -> None:
    batch(learner, at)
    learner.advance([w], values.get("spot", 100), values.get("sigma", .001),
                    values.get("bitcoin_at", at), at)


def test_separate_identity_fixed_slot_and_score_before_train() -> None:
    learner, w = setup()
    predict(learner, w)
    frozen = copy.deepcopy(learner.pending[w.slug]["forecast"])
    assert frozen["p"] == frozen["q"] == .5 and frozen["n"] == 0
    assert frozen["protocol"] == "kalshi-probability-calibration-v2-h300-g5-b10-prior20"
    assert frozen["batch_at"] == 1300 and frozen["venue_start_price"] == frozen["opening"] == 100
    learner.labels_received([(w.slug, True)], 1900)
    learner.advance([w], 100, .001, 1900, 1900)
    assert learner.counts["scored"] == learner.bin_n[5] == learner.bin_wins[5] == 1
    assert learner.brier_p == learner.brier_q == .25
    next_w = window(2000)
    learner.discover([next_w], 1950)
    predict(learner, next_w, 2300)
    next_f = learner.pending[next_w.slug]["forecast"]
    assert next_f["n"] == next_f["wins"] == 1 and next_f["q"] == 11 / 21
    assert learner.recent[-1]["forecast"] == frozen


@pytest.mark.parametrize("elapsed,reason", [(299, None), (300, "forecast"), (305, "forecast"), (305.001, "late")])
def test_exact_first_attempt_boundaries(elapsed: float, reason: str | None) -> None:
    learner, w = setup()
    predict(learner, w, 1000 + elapsed)
    assert learner.counts["forecasts"] == int(reason == "forecast")
    assert learner.counts["late"] == int(reason == "late")
    if reason is None:
        assert learner.pending[w.slug]["forecast"] is None


@pytest.mark.parametrize("key,value", [("spot", None), ("spot", -1), ("spot", float("nan")),
    ("spot", True), ("sigma", None), ("sigma", -1), ("sigma", float("inf")),
    ("bitcoin_at", 1296.999), ("bitcoin_at", 1300.001), ("bitcoin_at", True)])
def test_invalid_current_input_uses_first_attempt_without_retry(key: str, value: Any) -> None:
    learner, w = setup()
    predict(learner, w, **{key: value})
    predict(learner, w, 1301)
    assert learner.counts["invalid"] == 1 and learner.counts["forecasts"] == 0


@pytest.mark.parametrize("source_at,expected", [(1297, 1), (1300, 1), (1296.999, 0), (1300.001, 0)])
def test_batch_source_age_independent_of_fresh_bitcoin(source_at: float, expected: int) -> None:
    learner, w = setup()
    batch(learner, 1300, source_at=source_at)
    learner.advance([w], 100, 0, 1297, 1300)
    assert learner.counts["forecasts"] == expected
    assert learner.counts["invalid_batch"] == 1 - expected


def test_absent_or_uncompleted_batch_cannot_certify_forecast() -> None:
    for staged in (False, True):
        learner, w = setup()
        if staged:
            learner.batch(("batch", 1, 1300, 0, 0, []), 1300)
        learner.advance([w], 100, 0, 1300, 1300)
        assert learner.counts["invalid_batch"] == 1


@pytest.mark.parametrize("changes", [{"venue_start_price": None}, {"start_price": 99}, {"venue_start_price": 101}])
def test_verified_strike_must_equal_model_opening(changes: dict[str, Any]) -> None:
    learner, w = setup(replace(window(), **changes))
    predict(learner, w)
    assert learner.counts["invalid_strike"] == 1


def test_missing_strike_can_complete_once_before_fixed_forecast() -> None:
    learner, w = setup(replace(window(), start_price=None, venue_start_price=None))
    w = replace(w, start_price=100, venue_start_price=100)
    predict(learner, w)
    assert learner.counts["forecasts"] == 1


@pytest.mark.parametrize("after_forecast", [False, True])
def test_terms_changes_exclude_before_raw_label_consumption(after_forecast: bool) -> None:
    learner, w = setup()
    if after_forecast:
        predict(learner, w)
    changed = replace(w, maker_coefficient=.01)
    learner.labels_received([(w.slug, True)], 1900)
    learner.advance([changed], 100, 0, 1900, 1900)
    assert learner.counts["terms_changed"] == 1 and learner.counts["scored"] == 0


@pytest.mark.parametrize("drop_at,expected", [(950, 1), (1000, 0), (1100, 0)])
def test_raw_drop_replays_occurrence_without_sticky_prestart_contamination(drop_at: float, expected: int) -> None:
    learner = ProbabilityLearning(900)
    batch(learner, drop_at, dropped=1)
    # Metadata was known before start even if no simulator window was active.
    learner.discover([window()], 950 if drop_at == 950 else drop_at)
    if drop_at >= 1000:
        # For chronology test independently admit before the observed drop.
        learner, w = setup()
        batch(learner, drop_at, dropped=1)
    else:
        w = window()
    batch(learner, 1300, dropped=1)
    learner.advance([w], 100, 0, 1300, 1300)
    assert learner.counts["forecasts"] == expected
    assert learner.counts["pregap"] == 1 - expected


@pytest.mark.parametrize("seq,dropped", [(True, 0), (1.0, 0), (0, 0), (1, True), (1, -1), (1, 1.5)])
def test_raw_integer_integrity_excludes_bool(seq: Any, dropped: Any) -> None:
    learner, _ = setup()
    learner.batch(("batch", seq, 1000, dropped, 0, []), 1000)
    assert learner.error == "raw_stream_invalid"


def test_missing_raw_sequence_causes_pregap_and_duplicate_disables() -> None:
    learner, w = setup()
    batch(learner, 1000, seq=1)
    batch(learner, 1100, seq=3)
    predict(learner, w)
    assert learner.counts["pregap"] == 1
    learner.batch(("batch", 4, 1300, 0, 0, []), 1300)
    assert learner.error == "raw_stream_invalid"  # previous predict consumed seq4


@pytest.mark.parametrize("label_at,reason", [(1200, "outcome_known"), (1899.99, "outcome_known"),
                                            (9100.01, "missing_label")])
def test_early_or_expired_raw_label_never_scores(label_at: float, reason: str) -> None:
    learner, w = setup()
    if label_at >= 1300:
        predict(learner, w)
    learner.labels_received([(w.slug, True)], label_at)
    learner.advance([w], 100, 0, label_at, label_at)
    assert learner.counts[reason] == 1 and learner.counts["scored"] == 0


@pytest.mark.parametrize("label", [1, 0, "yes", "no", None, [], {}])
def test_raw_label_truthiness_is_never_a_boolean(label: Any) -> None:
    learner, w = setup()
    predict(learner, w)
    learner.labels_received([(w.slug, label)], 1900)
    learner.advance([w], 100, 0, 1900, 1900)
    assert learner.counts["invalid_label"] == 1 and learner.counts["scored"] == 0


def test_conflicting_label_after_score_preserves_history_and_disables_future() -> None:
    learner, w = setup()
    predict(learner, w)
    learner.labels_received([(w.slug, True)], 1900)
    learner.advance([w], 100, 0, 1900, 1900)
    learner.labels_received([(w.slug, True)], 1901)
    learner.labels_received([(w.slug, False)], 1902)
    assert learner.counts["scored"] == learner.counts["label_conflict"] == 1
    assert learner.bin_wins[5] == 1 and learner.brier_q == .25
    assert learner.error == "conflicting_or_invalid_final_label"


def test_timeout_inclusive_and_out_of_order_independent_labels() -> None:
    learner, first = setup()
    predict(learner, first)
    second = window(2000)
    learner.discover([second], 1950)
    predict(learner, second, 2300)
    learner.labels_received([(second.slug, False)], 2900)
    learner.advance([first, second], 100, 0, 2900, 2900)
    learner.labels_received([(first.slug, True)], 9100)
    learner.advance([first, second], 100, 0, 9100, 9100)
    assert learner.counts["scored"] == 2
    assert learner.bin_wins[5] == 1 and learner.brier_p == .5


def test_restore_frozen_forecast_without_hindsight_and_fail_unforecast_restart() -> None:
    learner, w = setup()
    predict(learner, w)
    saved = learner.state()
    restored = ProbabilityLearning(1400)
    restored.restore(saved, 1400)
    assert restored.enabled and restored.pending[w.slug]["forecast"] == saved["pending"][w.slug]["forecast"]
    assert restored.pending[w.slug]["post_gaps"] == ["child_restart_gap"]
    assert restored.batch_at is None
    restored.labels_received([(w.slug, False)], 1900)
    restored.advance([w], 100, 0, 1900, 1900)
    assert restored.counts["scored"] == 1
    learner, _ = setup()
    restored = ProbabilityLearning(1100)
    restored.restore(learner.state(), 1100)
    assert restored.counts["startup_inside"] == 1 and not restored.pending


def test_source_mismatch_preserves_valid_old_counts_without_migration() -> None:
    learner, w = setup()
    predict(learner, w)
    saved = learner.state()
    saved["source_fingerprint"] = "a" * 64
    saved["pending"][w.slug]["forecast"]["source_fingerprint"] = "a" * 64
    restored = ProbabilityLearning(1400)
    restored.restore(saved, 1400)
    assert restored.error == "source_or_protocol_mismatch" and restored.counts["forecasts"] == 1
    assert restored.history_source == "a" * 64 and restored.source != restored.history_source


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(bin_n=[True] * 10),
    lambda s: s.update(recent=[{"bad": "receipt"}]),
    lambda s: s.update(labels={"x": {"outcome": True, "received_at": float("nan")}}),
    lambda s: s["pending"][window().slug]["forecast"].update(q=.9),
    lambda s: s["pending"][window().slug]["forecast"].update(batch_at=1400),
    lambda s: s["pending"][window().slug].update(opening=99),
    lambda s: s["counts"].update(unknown=1),
    lambda s: s.update(restore_rejected="false"),
])
def test_restore_fails_closed_without_partially_committing(mutation: Any) -> None:
    learner, w = setup()
    predict(learner, w)
    saved = learner.state()
    mutation(saved)
    restored = ProbabilityLearning(1400)
    restored.restore(saved, 1400)
    assert restored.error == "malformed_optional_learning_state"
    assert restored.counts["forecasts"] == 0 and restored.restore_rejected


def test_bounded_history_labels_and_json_state() -> None:
    learner = ProbabilityLearning(0)
    for i in range(100):
        w = window(1000 + 1800 * i)
        learner.discover([w], w.start - 100)
        predict(learner, w, w.start + 300)
        learner.labels_received([(w.slug, bool(i % 2))], w.end)
        learner.advance([w], 100, .001, w.end, w.end)
    assert len(learner.recent) == len(learner.labels) == 64 and len(learner.pending) == 0
    assert learner.counts["scored"] == 100
    saved = json.loads(json.dumps(learner.state(), allow_nan=False))
    restored = ProbabilityLearning(learner.last_at)
    restored.restore(saved, learner.last_at)
    assert restored.enabled and restored.counts == learner.counts
    assert len(json.dumps(saved)) < 100000


def test_logging_failure_never_retries_forecast_or_loses_score(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic log sink")
    monkeypatch.setattr(probability.log, "info", broken)
    learner, w = setup()
    predict(learner, w)
    predict(learner, w, 1301)
    learner.labels_received([(w.slug, False)], 1900)
    learner.advance([w], 100, 0, 1900, 1900)
    assert learner.enabled and learner.counts["forecasts"] == learner.counts["scored"] == 1


def test_initial_missing_frame_excludes_active_window_but_not_prestart_discovery() -> None:
    learner, w = setup()
    batch(learner, 1100, seq=2)
    predict(learner, w)
    assert learner.counts["pregap"] == 1
    learner, w = setup()
    batch(learner, 950, seq=2)
    predict(learner, w)
    assert learner.counts["forecasts"] == 1


def test_postforecast_raw_gap_annotation_survives_restore_and_score() -> None:
    learner, w = setup()
    predict(learner, w)
    batch(learner, 1400, seq=4, dropped=1)
    assert learner.pending[w.slug]["post_gaps"] == ["raw_stream_gap"]
    restored = ProbabilityLearning(1500)
    restored.restore(learner.state(), 1500)
    assert restored.enabled and restored.pending[w.slug]["post_gaps"] == ["raw_stream_gap", "child_restart_gap"]
    restored.labels_received([(w.slug, True)], 1900)
    restored.advance([w], 100, 0, 1900, 1900)
    assert restored.counts["scored"] == 1
    again = ProbabilityLearning(1900)
    again.restore(restored.state(), 1900)
    assert again.enabled and again.recent[-1]["post_gaps"] == ["raw_stream_gap", "child_restart_gap"]


def test_input_and_pending_capacities_are_bounded() -> None:
    learner = ProbabilityLearning(0)
    learner.discover([window(1000 + 900 * i) for i in range(33)], 100)
    assert len(learner.pending) == 32 and learner.counts["capacity"] == 1
    learner.labels_received([("x", True)] * 4097, 100)
    assert learner.error == "label_input_capacity"
    learner = ProbabilityLearning(0)
    learner.discover([window()] * 4097, 100)
    assert learner.error == "window_input_capacity"


def test_missing_label_and_reversed_clock_exclusions_are_explicit() -> None:
    learner, w = setup()
    predict(learner, w)
    learner.advance([w], 100, 0, 9100.001, 9100.001)
    assert learner.counts["missing_label"] == 1
    learner.advance([w], 100, 0, 9000, 9000)
    assert learner.error == "clock_invalid_or_reversed"


def test_every_shared_dependency_changes_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path
    original = Path.read_bytes
    baseline = probability.fingerprint()
    for target in probability.SOURCE_FILES:
        def changed(path: Path, name: str = target) -> bytes:
            content = original(path)
            return content + b"\n# synthetic dependency change" if path.name == name else content
        monkeypatch.setattr(Path, "read_bytes", changed)
        assert probability.fingerprint() != baseline
    monkeypatch.setattr(Path, "read_bytes", original)


def test_fingerprint_failure_disables_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> str:
        raise RuntimeError("synthetic unavailable identity")
    monkeypatch.setattr(probability, "fingerprint", broken)
    learner = ProbabilityLearning(900)
    assert learner.error == "source_fingerprint_unavailable"


@pytest.mark.parametrize("mutation", [
    lambda s: s["pending"][window().slug].update(pregap="raw_stream_gap"),
    lambda s: s["recent"].append({"window": window().slug, "status": "unknown", "reason": "missing_label",
                                "forecast": None, "post_gaps": []}),
])
def test_restore_rejects_impossible_admission_and_terminal_pending_overlap(mutation: Any) -> None:
    learner, w = setup()
    predict(learner, w)
    saved = learner.state()
    mutation(saved)
    restored = ProbabilityLearning(1400)
    restored.restore(saved, 1400)
    assert restored.error == "malformed_optional_learning_state" and restored.counts["forecasts"] == 0


@pytest.mark.parametrize("mutation", [
    lambda s: s["recent"].append(copy.deepcopy(s["recent"][0])),
    lambda s: s["counts"].update(forecasts=0),
    lambda s: (s["counts"].update(unknown=0, missing_label=0)),
])
def test_restore_retained_terminal_receipts_require_unique_identity_and_count_support(mutation: Any) -> None:
    learner, w = setup()
    predict(learner, w)
    learner.advance([w], 100, 0, 9101, 9101)
    saved = learner.state()
    mutation(saved)
    restored = ProbabilityLearning(9101)
    restored.restore(saved, 9101)
    assert restored.error == "malformed_optional_learning_state"

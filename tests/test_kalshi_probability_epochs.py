"""Real child-only epoch transitions with synthetic inputs, files and source IDs."""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_kalshi_probability_arena import admit, forecast, receive, setup, tick
from test_kalshi_probability_learning import predict, window

from nightcrawler import kalshi_probability_epochs as epochs
from nightcrawler import kalshi_probability_learning as probability
from nightcrawler.kalshi_arena import KalshiArena
from nightcrawler.kalshi_probability_epochs import (
    EPOCHS,
    LEGACY,
    MARKER,
    ProbabilityEpochs,
)
from nightcrawler.kalshi_probability_learning import ProbabilityLearning
from nightcrawler.pagestate import _kalshi_probability_epochs_view

A, B = "a" * 64, "b" * 64


def host(monkeypatch: pytest.MonkeyPatch, source: str, now: float) -> ProbabilityEpochs:
    monkeypatch.setattr(probability, "fingerprint", lambda: source)
    return ProbabilityEpochs(ProbabilityLearning(now), now)


def saved(value: ProbabilityEpochs) -> dict[str, Any]:
    legacy, envelope = value.checkpoint()
    return {LEGACY: legacy, EPOCHS: envelope, MARKER: epochs.SCHEMA}


def history(monkeypatch: pytest.MonkeyPatch, *, pending: bool = False) -> dict[str, Any]:
    monkeypatch.setattr(probability, "fingerprint", lambda: A)
    learner = ProbabilityLearning(0)
    for index in range(5):
        w = window(1000 + index * 1000)
        learner.discover([w], w.start - 1)
        predict(learner, w, w.start + 300)
        learner.labels_received([(w.slug, bool(index % 2))], w.end)
        learner.advance([w], 100, .001, w.end, w.end)
    w = window(6000)
    learner.discover([w], 5999)
    learner.advance([w], 100, .001, 6310, 6310)
    if pending:
        w = window(7000)
        learner.discover([w], 6999)
        predict(learner, w, 7300)
    return learner.state()


def test_import_freezes_exact_five_scores_one_unknown_and_pending_before_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = history(monkeypatch, pending=True)
    original = copy.deepcopy(raw)
    value = host(monkeypatch, B, 9000)
    value.restore({LEGACY: raw}, 9000)
    state = saved(value)
    assert raw == original == state[LEGACY] == state[EPOCHS]["archived"][0]["state"]
    assert state[EPOCHS]["archived"][0]["state"]["last_at"] == 7300
    assert value.active.enabled and value.active.source == B
    assert not any(value.active.counts.values()) and not any(value.active.bin_n)
    assert value.active.brier_p == value.active.brier_q == 0
    assert value.active.watermark == -1 and not value.active.pending and not value.active.labels
    assert value.active.batch_seq is value.active.batch_at is value.active.raw_gap_at is None
    assert value.active.panel()["brier_baseline"] is None
    value.active.labels_received([(window(7000).slug, True)], 9001)
    value.active.advance([], 100, .001, 9001, 9001)
    assert saved(value)[EPOCHS]["archived"][0]["state"] == original
    panel = value.panel()
    assert panel["active_ordinal"] == 1 and panel["archived"][0]["scored"] == 5
    assert panel["archived"][0]["unknown"] == panel["archived"][0]["pending"] == 1
    assert _kalshi_probability_epochs_view(panel) == panel
    assert "state" not in panel["archived"][0]


@pytest.mark.parametrize("disabled,rejected,error", [
    (False, False, "source_or_protocol_mismatch"),
    (False, False, "raw_stream_invalid"),
    (False, False, "conflicting_or_invalid_final_label"),
    (True, True, None), (False, True, "source_or_protocol_mismatch"), (False, False, None),
])
def test_original_fatal_status_is_never_hidden_by_current_source_mismatch(
        monkeypatch: pytest.MonkeyPatch, disabled: bool, rejected: bool, error: str | None) -> None:
    raw = history(monkeypatch)
    raw.update(enabled=disabled, restore_rejected=rejected, error=error)
    value = host(monkeypatch, B, 9000)
    value.restore({LEGACY: raw}, 9000)
    allowed = not disabled and not rejected and error == "source_or_protocol_mismatch"
    assert value.active.enabled is allowed
    state = saved(value)
    assert state[LEGACY] == raw
    if allowed:
        assert state[EPOCHS]["archived"][0]["state"] == raw
    else:
        assert value.error == "epoch_history_disabled" and value.current_panel() is None
        assert state[EPOCHS]["active"]["state"] == raw
        assert value.panel()["retained_active"]["scored"] == 5
        retry = host(monkeypatch, B, 9001)
        retry.restore(state, 9001)
        assert not retry.active.enabled and saved(retry) == state


@pytest.mark.parametrize("raw", [{}, {LEGACY: None}, {LEGACY: {}}, {EPOCHS: None}])
def test_loaded_missing_null_and_malformed_are_not_fresh_bootstrap(monkeypatch: pytest.MonkeyPatch, raw: Any) -> None:
    value = host(monkeypatch, B, 9000)
    assert value.active.enabled  # only the genuinely absent-file path may bootstrap
    value.restore(raw, 9000)
    assert not value.active.enabled and value.current_panel() is None
    assert value.error == ("epoch_history_missing" if not raw else "epoch_state_invalid")
    json.dumps(saved(value), allow_nan=False)


def test_same_source_restart_preserves_training_and_strict_restart_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = history(monkeypatch, pending=True)
    value = host(monkeypatch, A, 7400)
    value.restore({LEGACY: raw}, 7400)
    state = saved(value)
    assert state[LEGACY] == raw and state[EPOCHS]["active"]["ordinal"] == 0
    assert value.active.counts == raw["counts"] and value.active.bin_n == raw["bin_n"]
    assert value.active.pending[window(7000).slug]["post_gaps"] == ["child_restart_gap"]
    assert state[EPOCHS]["active"]["state"]["last_at"] == 7400
    restarted = host(monkeypatch, A, 7500)
    restarted.restore(state, 7500)
    assert restarted.active.started_at == 7500 and restarted.error is None
    assert saved(restarted)[EPOCHS]["active"]["opened_at"] == 7400
    assert not saved(restarted)[EPOCHS]["archived"]
    w = window(7600)
    restarted.active.discover([w], 7600)
    assert restarted.active.counts["startup_inside"] == raw["counts"]["startup_inside"] + 1


def test_rollback_a_b_a_creates_new_ordinal_without_resurrecting_a(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = history(monkeypatch, pending=True)
    first = host(monkeypatch, A, 7400)
    first.restore({LEGACY: raw}, 7400)
    initial = saved(first)
    second = host(monkeypatch, B, 8000)
    second.restore(initial, 8000)
    middle = saved(second)
    third = host(monkeypatch, A, 9000)
    third.restore(middle, 9000)
    final = saved(third)
    assert final[LEGACY] == raw
    assert [row["ordinal"] for row in final[EPOCHS]["archived"]] == [0, 1]
    assert final[EPOCHS]["archived"][0]["state"] == initial[EPOCHS]["active"]["state"]
    assert final[EPOCHS]["archived"][1]["state"] == middle[EPOCHS]["active"]["state"]
    assert final[EPOCHS]["active"]["ordinal"] == 2
    assert third.active.enabled and third.active.source == A
    assert not any(third.active.counts.values()) and not any(third.active.bin_n) and not third.active.pending


def test_archive_count_limit_refuses_atomically_and_remains_latched(monkeypatch: pytest.MonkeyPatch) -> None:
    value = host(monkeypatch, A, 9000)
    for index in range(1, 5):
        state = saved(value)
        value = host(monkeypatch, f"{index:064x}", 9000 + index)
        value.restore(state, 9000 + index)
        assert value.error is None
    before = saved(value)
    refused = host(monkeypatch, B, 9010)
    refused.restore(before, 9010)
    after = saved(refused)
    assert refused.error == "epoch_capacity" and not refused.active.enabled
    assert after[LEGACY] == before[LEGACY]
    assert after[EPOCHS] == {**before[EPOCHS], "error": "epoch_capacity"}
    assert len(after[EPOCHS]["archived"]) == 4
    retry = host(monkeypatch, B, 9020)
    retry.restore(after, 9020)
    assert saved(retry) == after and retry.current_panel() is None


def test_joint_byte_limit_reserves_latch_and_counts_duplicated_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    value = host(monkeypatch, A, 9000)
    before = saved(value)
    reserved = {**before[EPOCHS], "error": max(epochs.HOST_ERRORS, key=len)}
    boundary = len(epochs.encoded({LEGACY: before[LEGACY], EPOCHS: reserved, MARKER: epochs.SCHEMA}))
    monkeypatch.setattr(epochs, "MAX_BYTES", boundary)
    assert saved(value) == before  # exact reserved boundary fits
    changed = host(monkeypatch, B, 9010)
    changed.restore(before, 9010)
    assert changed.error == "epoch_capacity"
    after = saved(changed)
    assert after[EPOCHS] == {**before[EPOCHS], "error": "epoch_capacity"}
    assert len(epochs.encoded(after)) <= boundary
    retry = host(monkeypatch, B, 9020)
    retry.restore(after, 9020)
    assert saved(retry) == after


@pytest.mark.parametrize("corruption", ["null", "missing_active", "legacy_digest", "state_digest", "ordinal",
                                         "source", "protocol", "time", "counts", "truncated", "extra"])
def test_authoritative_envelope_corruption_never_falls_back_to_legacy(
        monkeypatch: pytest.MonkeyPatch, corruption: str) -> None:
    value = host(monkeypatch, A, 9000)
    state = saved(value)
    newer = host(monkeypatch, B, 9010)
    newer.restore(state, 9010)
    state = saved(newer)
    raw = state[EPOCHS]
    if corruption == "null":
        state[EPOCHS] = None
    elif corruption == "missing_active":
        del raw["active"]
    elif corruption == "legacy_digest":
        raw["legacy_sha256"] = "0" * 64
    elif corruption == "state_digest":
        raw["archived"][0]["state"]["last_at"] -= 1
    elif corruption == "ordinal":
        raw["active"]["ordinal"] = 0
    elif corruption == "source":
        raw["active"]["source_fingerprint"] = A
    elif corruption == "protocol":
        raw["active"]["protocol"] = "unrecognized"
    elif corruption == "time":
        raw["archived"][0]["closed_at"] = 8000
    elif corruption == "counts":
        raw["active"]["state"]["counts"]["scored"] = -1
    elif corruption == "truncated":
        raw["archived"] = []
    else:
        raw["extra"] = "private untrusted string"
    restored = host(monkeypatch, B, 9020)
    restored.restore(state, 9020)
    assert not restored.active.enabled and restored.current_panel() is None
    assert saved(restored)[LEGACY] == state[LEGACY]
    blocked = saved(restored)[EPOCHS]
    assert blocked["active"] is None and blocked["error"] == "epoch_state_invalid"
    assert "private" not in json.dumps(restored.panel())


def test_unknown_prediction_protocol_requires_discrete_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = host(monkeypatch, A, 9000).active.state()
    raw["protocol"] = "some-future-calibration-v3"
    value = host(monkeypatch, B, 9010)
    value.restore({LEGACY: raw}, 9010)
    assert value.error == "epoch_protocol_unsupported" and not value.active.enabled
    assert saved(value)[LEGACY] == raw
    assert value.current_panel() is None
    assert "some-future" not in json.dumps(value.panel())


@pytest.mark.parametrize("unsafe", ["nan", "cycle", "oversize"])
def test_unsafe_raw_cannot_poison_optional_serialization(monkeypatch: pytest.MonkeyPatch, unsafe: str) -> None:
    raw = host(monkeypatch, A, 9000).active.state()
    if unsafe == "nan":
        raw["last_at"] = float("nan")
    elif unsafe == "cycle":
        raw["pending"]["self"] = raw
    else:
        raw["extra"] = "x" * (epochs.MAX_STATE_BYTES + 1)
    value = host(monkeypatch, B, 9010)
    value.restore({LEGACY: raw}, 9010)
    assert not value.active.enabled and saved(value) == {LEGACY: None, EPOCHS: None, MARKER: epochs.SCHEMA}
    json.dumps(saved(value), allow_nan=False)


def test_runtime_optional_corruption_retains_last_safe_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    value = host(monkeypatch, A, 9000)
    before = saved(value)
    value.active.counts["forecasts"] = float("nan")
    after = saved(value)
    assert after[EPOCHS] == {**before[EPOCHS], "error": "epoch_method_failed"}
    assert not value.active.enabled
    json.dumps(after, allow_nan=False)


def test_arena_real_restart_preserves_legacy_and_v1_residents_and_write_order(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    from nightcrawler import kalshi_arena as arena
    town, view, clock = setup(tmp_path)
    w = admit(town, view, clock)
    forecast(town, view, clock)
    receive(town, view, clock, 1900, [("o", [(w.slug, True)])])
    tick(town, view, clock, 1900)
    original = town.state(1900)
    # Synthetic legacy checkpoint exactly represents the previous producer format.
    original[LEGACY] = original.pop(EPOCHS)["active"]["state"]
    del original[MARKER]
    town.path.write_text(json.dumps(original))
    monkeypatch.setattr(probability, "fingerprint", lambda: B)
    clock[0] = 2000
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    state = restored.state(2000)
    assert state[LEGACY] == original[LEGACY] == state[EPOCHS]["archived"][0]["state"]
    assert restored.learning_probability.enabled and restored.learning_probability.counts["scored"] == 0
    assert state["learning"] == {**original["learning"], "last_at": 2000}
    for key in ("residents", "town", "events", "feed"):
        assert state[key] == original[key]
    writes: list[tuple[str, bool]] = []
    original_write = arena._write

    def record(path: Path, text: str, *, durable: bool = False) -> None:
        writes.append((path.name, durable))
        original_write(path, text, durable=durable)

    monkeypatch.setattr(arena, "_write", record)
    restored._save(2000)
    assert writes == [("state.json", True), ("panel.json", False)]
    panel = json.loads(restored.panel_path.read_text())
    assert panel[LEGACY]["scored"] == 0
    assert panel[EPOCHS]["archived"][0]["scored"] == 1
    assert _kalshi_probability_epochs_view(panel[EPOCHS]) == panel[EPOCHS]


def test_lineage_page_allowlist_rejects_untrusted_strings_and_raw_states(monkeypatch: pytest.MonkeyPatch) -> None:
    value = host(monkeypatch, B, 9000)
    value.restore({LEGACY: history(monkeypatch)}, 9000)
    panel = value.panel()
    panel["private"] = panel["archived"][0]["private"] = "untrusted-private"
    panel["archived"][0]["state"] = {"arbitrary": "untrusted-private"}
    assert "untrusted-private" not in json.dumps(_kalshi_probability_epochs_view(panel))
    panel["archived"][0]["protocol"] = "untrusted-private"
    assert _kalshi_probability_epochs_view(panel) is None


def test_epoch_host_is_a_real_fingerprint_dependency() -> None:
    assert "kalshi_probability_epochs.py" in probability.SOURCE_FILES


@pytest.mark.parametrize("corruption", ["null", "digest", "state", "missing_active", "missing_marker"])
def test_malformed_active_preserves_all_valid_archives_and_stays_blocked(
        monkeypatch: pytest.MonkeyPatch, corruption: str) -> None:
    value = host(monkeypatch, A, 9000)
    for index in range(1, 4):
        prior = saved(value)
        value = host(monkeypatch, f"{index:064x}", 9000 + index)
        value.restore(prior, 9000 + index)
    prior = saved(value)
    archives = copy.deepcopy(prior[EPOCHS]["archived"])
    if corruption == "null":
        prior[EPOCHS]["active"] = None
    elif corruption == "digest":
        prior[EPOCHS]["active"]["state_sha256"] = "0" * 64
    elif corruption == "missing_active":
        del prior[EPOCHS]["active"]
    elif corruption == "missing_marker":
        del prior[MARKER]
    else:
        prior[EPOCHS]["active"]["state"]["last_at"] = float("nan")
    restored = host(monkeypatch, B, 9010)
    restored.restore(prior, 9010)
    blocked = saved(restored)
    assert blocked[EPOCHS]["active"] is None
    assert blocked[EPOCHS]["archived"] == archives and blocked[LEGACY] == prior[LEGACY]
    assert restored.current_panel() is None and not restored.active.enabled
    assert _kalshi_probability_epochs_view(restored.panel()) == restored.panel()
    restarted = host(monkeypatch, B, 9020)
    restarted.restore(blocked, 9020)
    assert saved(restarted) == blocked
    json.dumps(blocked, allow_nan=False)


def test_corrupt_middle_archive_retains_only_proven_contiguous_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    value = host(monkeypatch, A, 9000)
    for index in range(1, 4):
        prior = saved(value)
        value = host(monkeypatch, f"{index:064x}", 9000 + index)
        value.restore(prior, 9000 + index)
    prior = saved(value)
    retained = copy.deepcopy(prior[EPOCHS]["archived"][:1])
    prior[EPOCHS]["archived"][1]["state_sha256"] = "0" * 64
    value = host(monkeypatch, B, 9010)
    value.restore(prior, 9010)
    blocked = saved(value)
    assert blocked[EPOCHS]["archived"] == retained and blocked[EPOCHS]["active"] is None
    restarted = host(monkeypatch, B, 9020)
    restarted.restore(blocked, 9020)
    assert saved(restarted) == blocked


def test_host_construction_failure_disables_orphan_observer_and_preserves_arena(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    from nightcrawler import kalshi_arena as arena

    def broken(*args: Any) -> None:
        raise RuntimeError("synthetic host construction failure")

    monkeypatch.setattr(arena, "ProbabilityEpochs", broken)
    town, view, clock = setup(tmp_path)
    assert not town.learning_probability.enabled and town.learning.enabled
    admit(town, view, clock)
    forecast(town, view, clock)
    assert town.learning_probability.counts["forecasts"] == 0
    town._save(1300)
    assert len(town.residents) == 2
    assert json.loads(town.path.read_text())[EPOCHS] is None


@pytest.mark.parametrize("method", ["restore", "checkpoint", "current_panel", "panel", "status"])
def test_host_method_failure_cannot_reset_arena_or_break_saves(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    town, view, clock = setup(tmp_path)
    before = town.state(900)

    def broken(*args: Any) -> None:
        raise RuntimeError("synthetic host method failure")

    if method == "restore":
        town.directory.mkdir(parents=True, exist_ok=True)
        town.path.write_text(json.dumps(before))
        monkeypatch.setattr(ProbabilityEpochs, method, broken)
        town = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    else:
        monkeypatch.setattr(town._probability_epochs, method, broken)
        if method == "status":
            town._probability_epoch_call("status", 900)
    town._save(900)
    after = json.loads(town.path.read_text())
    panel = json.loads(town.panel_path.read_text())
    if method == "checkpoint":
        assert after[EPOCHS]["active"] == before[EPOCHS]["active"]
    for key in ("learning", "residents", "town", "events", "feed"):
        assert after[key] == before[key]
    assert not town.learning_probability.enabled and town.learning.enabled
    assert not list(town.directory.glob("state.json.bad-*"))
    assert panel.get(LEGACY) is None


def fill_dense(learner: ProbabilityLearning, base: int) -> None:
    """Maximum retained actual receipts, labels and frozen pending forecasts."""
    for index in range(probability.MAX_RECENT):
        w = window(base + 1000 + index * 1000)
        w = replace(w, slug=w.slug.ljust(128, "x"))
        learner.discover([w], w.start - 1)
        predict(learner, w, w.start + 300)
        learner.labels_received([(w.slug, bool(index % 2))], w.end)
        learner.advance([w], 100, .001, w.end, w.end)
    pending = [window(base + 65000 + index) for index in range(probability.MAX_PENDING)]
    pending = [replace(w, slug=w.slug.ljust(128, "x")) for w in pending]
    learner.discover(pending, base + 64950)
    for w in pending:
        predict(learner, w, w.start + 300)
    assert len(learner.pending) == probability.MAX_PENDING
    assert len(learner.labels) == len(learner.recent) == probability.MAX_RECENT


def dense_host(monkeypatch: pytest.MonkeyPatch, current_source: str) -> ProbabilityEpochs:
    value = host(monkeypatch, A, 0)
    fill_dense(value.active, 0)
    for index in range(1, 5):
        prior = {LEGACY: value.active.state()} if index == 1 else saved(value)
        source = current_source if index == 4 else f"{index:064x}"
        value = host(monkeypatch, source, index * 100000)
        value.restore(prior, index * 100000)
        fill_dense(value.active, index * 100000)
    return value


def test_maximum_retained_history_is_bounded_json_and_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    value = dense_host(monkeypatch, B)
    state = saved(value)
    assert len(state[EPOCHS]["archived"]) == 4
    assert len(epochs.encoded(state)) <= epochs.MAX_BYTES
    for record in [*state[EPOCHS]["archived"], state[EPOCHS]["active"]]:
        assert len(epochs.encoded(record["state"])) <= epochs.MAX_STATE_BYTES
        assert record["state"]["counts"]["forecasts"] == 96
        assert record["state"]["counts"]["scored"] == 64
    assert len(epochs.encoded(value.panel())) < 256 * 1024
    assert _kalshi_probability_epochs_view(value.panel()) == value.panel()


def test_one_startup_lineage_receipt_separates_archived_scores_from_current(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    town, view, clock = setup(tmp_path)
    state = town.state(900)
    state.pop(EPOCHS)
    del state[MARKER]
    state[LEGACY] = history(monkeypatch)
    town.directory.mkdir(parents=True, exist_ok=True)
    town.path.write_text(json.dumps(state))
    clock[0] = 9000
    monkeypatch.setattr(probability, "fingerprint", lambda: B)
    caplog.set_level(logging.INFO, logger="nightcrawler.kalshi_probability_epochs")
    # The fixture town has its own startup; measure this restored instance only.
    caplog.clear()
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    restored._save(9000)
    restored.step(9000)
    receipts = [r.message for r in caplog.records if r.message.startswith("kalshi_probability_epoch_status ")]
    assert len(receipts) == 1
    payload = json.loads(receipts[0].split(" ", 1)[1])
    assert payload["at"] == 9000
    assert payload["enabled"] and payload["current"]["scored"] == payload["current"]["forecasts"] == 0
    assert payload["current"]["brier_baseline"] is None
    assert payload["active_ordinal"] == 1 and payload["archived"][0]["scored"] == 5
    assert payload["legacy_sha256"] == epochs.digest(state[LEGACY])
    assert not {"state", "pending", "labels", "recent"} & payload.keys()
    assert "KXBTC15M" not in receipts[0]


@pytest.mark.parametrize("missing", [EPOCHS, MARKER])
def test_independently_missing_new_lineage_field_never_reimports_frozen_legacy(
        monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    value = host(monkeypatch, B, 9000)
    value.restore({LEGACY: history(monkeypatch)}, 9000)
    state = saved(value)
    del state[missing]
    restarted = host(monkeypatch, B, 9010)
    restarted.restore(state, 9010)
    assert restarted.error == "epoch_state_invalid" and restarted.current_panel() is None
    assert not restarted.active.enabled and saved(restarted)[LEGACY] == state[LEGACY]


def test_real_arena_page_separates_old_scores_from_fresh_epoch(make_settings: Any,
        monkeypatch: pytest.MonkeyPatch) -> None:
    from nightcrawler import pagestate
    settings = make_settings(KALSHI_ARENA_ENABLED=True)
    town, view, clock = setup(settings.data_dir)
    raw = town.state(900)
    del raw[EPOCHS]
    del raw[MARKER]
    raw[LEGACY] = history(monkeypatch)
    town.directory.mkdir(parents=True, exist_ok=True)
    town.path.write_text(json.dumps(raw))
    clock[0] = 9000
    monkeypatch.setattr(probability, "fingerprint", lambda: B)
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    restored._save(9000)
    block = pagestate.kalshi_arena_block(settings, 9000)
    assert block[LEGACY]["scored"] == 0 and block[LEGACY]["brier_baseline"] is None
    assert block[EPOCHS]["archived"][0]["scored"] == 5
    assert block[EPOCHS]["archived"][0]["source_fingerprint"] == A
    assert block[LEGACY]["source_fingerprint"] == block[LEGACY]["history_source_fingerprint"] == B
    assert block["learning"] is not None and block["population"] == 2


def test_validation_cannot_emit_phantom_unknown_receipts_but_real_restart_emits_once(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    value = host(monkeypatch, A, 900)
    w = window(1000)
    value.active.discover([w], 900)
    value.active.batch(("batch", 1, 1100, 0, 0, []), 1100)
    value.active.batch_complete()
    caplog.set_level(logging.INFO, logger="nightcrawler.kalshi_probability_learning")
    state = saved(value)
    assert saved(value) == state
    assert value.active.counts["unknown"] == 0 and w.slug in value.active.pending
    assert not [r for r in caplog.records if r.message.startswith("kalshi_probability_learning_unknown ")]
    restarted = host(monkeypatch, A, 1100)
    restarted.restore(state, 1100)
    assert restarted.active.counts["startup_inside"] == restarted.active.counts["unknown"] == 1
    receipts = [r for r in caplog.records if r.message.startswith("kalshi_probability_learning_unknown ")]
    assert len(receipts) == 1
    saved(restarted)
    assert len([r for r in caplog.records if r.message.startswith("kalshi_probability_learning_unknown ")]) == 1

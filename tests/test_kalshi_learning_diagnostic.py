"""Bounded, observation-only child input causes: synthetic clocks and frames, no network."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import kalshi_arena as module
from nightcrawler.kalshi_arena import (
    ArenaConfig,
    KalshiArena,
    WireView,
    book_wire,
    trade_wire,
    window_wire,
)
from nightcrawler.kalshi_online_learning import MAX_PENDING, MAX_RECENT, fingerprint
from nightcrawler.speeddesk_model import Book, Trade, Window


def setup(path: Path) -> tuple[KalshiArena, WireView, list[float]]:
    clock = [900.0]
    view = WireView()
    view.bitcoin_price, view.sigma = 100, .001
    arena = KalshiArena(ArenaConfig(path, population=2), lambda: view, clock=lambda: clock[0], cpu=lambda: 0.0)
    return arena, view, clock


def window(start: float = 1000) -> Window:
    return Window(f"KXBTC15M-{int(start)}", start, start + 900, 100, venue="kalshi")


def tick(arena: KalshiArena, view: WireView, clock: list[float], at: float) -> None:
    clock[0] = view.bitcoin_at = at
    arena.step(at)


def events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    prefix = "kalshi_learning_input_diagnostic "
    return [json.loads(r.message[len(prefix):]) for r in caplog.records if r.message.startswith(prefix)]


def ready(path: Path) -> tuple[KalshiArena, WireView, list[float], Window]:
    arena, view, clock = setup(path)
    w = window()
    view.windows = (w,)
    tick(arena, view, clock, 900)
    return arena, view, clock, w


@pytest.mark.parametrize("selected,stream,coinbase", [(True, True, True), (False, False, True),
                                                      (False, True, False), (True, False, False)])
def test_effective_gap_flags_recovery_and_single_actual_receipt(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, selected: bool, stream: bool, coinbase: bool,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    clock[0] = 1100
    arena.receive(("batch", 1, 1098, 0, 0, [("g", [w.slug] if selected else [], stream, coinbase)]), view)
    tick(arena, view, clock, 1101)
    arena.feed_gap((), True, True)
    tick(arena, view, clock, 1200)
    tick(arena, view, clock, 1300)
    tick(arena, view, clock, 1301)
    row, = events(caplog)
    assert row["disposition"] == "unknown" and row["reason"] == arena.learning.recent[-1]["reason"] == "pregap"
    assert row["feed_ok"] is True and row["feed_status"] == [True, True]
    cause = row["first_effective_cause"]
    assert cause == row["last_effective_cause"]
    assert cause["flags"]["explicit_slug"] == selected
    assert cause["flags"]["trade_stream_false"] == (not stream)
    assert cause["flags"]["coinbase_false"] == (not coinbase)
    assert cause["parent_frame_sent_at"] == 1098
    assert cause["child_receive_at"] == 1100 and cause["child_apply_at"] == 1101
    assert cause["frame_transit_s"] == 2 and cause["child_wait_s"] == 1
    assert cause["producer_event_time"] is None
    assert cause["producer_timing"] == "unavailable_on_gap_wire"
    assert row["counter_delta"] == {"forecasts": 0, "unknown": 1, "scored": 0}
    assert row["arena_source_sha256"] == hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    assert row["source_fingerprint"] == fingerprint()
    assert row["deployment_id"] is None and row["deployment_sha"] is None
    assert len(row["instance"]) == 24


@pytest.mark.parametrize("recover", [False, True])
def test_prestart_feed_flag_has_no_effective_row_cause(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, recover: bool,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, _ = ready(tmp_path)
    arena.feed_gap((), False, False)
    tick(arena, view, clock, 950)
    if recover:
        arena.feed_gap((), True, True)
    tick(arena, view, clock, 1300)
    row, = events(caplog)
    assert row["first_effective_cause"] is row["last_effective_cause"] is None
    assert row["disposition"] == ("forecast" if recover else "unknown")
    assert row["reason"] == (None if recover else "pregap")
    assert row["pending"]["stored_pregap"] is None


def test_multiple_queued_frames_cross_start_and_first_last_keep_own_context(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    clock[0] = 950
    arena.receive(("batch", 5, 949, 0, 0, [("g", [w.slug], True, True)]), view)
    clock[0] = 960
    arena.receive(("batch", 6, 959, 0, 0, [("g", [], False, False)]), view)
    tick(arena, view, clock, 1100)
    tick(arena, view, clock, 1300)
    row, = events(caplog)
    first, last = row["first_effective_cause"], row["last_effective_cause"]
    assert first["frame_sequence"] == 5 and first["child_receive_at"] == 950
    assert first["child_apply_at"] == 1100 and first["child_wait_s"] == 150
    assert last["frame_sequence"] == 6 and last["child_receive_at"] == 960
    assert last["child_apply_at"] == 1100 and last["child_wait_s"] == 140
    assert first["flags"]["explicit_slug"] and last["flags"]["coinbase_false"]


@pytest.mark.parametrize("sent", [float("nan"), float("inf"), 1101, -1e308])
def test_invalid_reversed_frame_clocks_stay_unknown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, sent: float,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    clock[0] = 1100
    arena.receive(("batch", 1, sent, 0, 0, [("g", [w.slug], True, True)]), view)
    tick(arena, view, clock, 1100)
    tick(arena, view, clock, 1300)
    cause = events(caplog)[0]["first_effective_cause"]
    assert cause["frame_transit_s"] is None and cause["timing"] == "unknown_or_reversed"
    assert cause["producer_event_time"] is None


@pytest.mark.parametrize("kind", ["book", "trade"])
def test_late_book_trade_and_postforecast_causes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, kind: str,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    clock[0] = 1100
    record = (book_wire(Book(w.slug, "up", (), (), 1090, "fake")) if kind == "book" else
              trade_wire(Trade(w.slug, "up", .5, 1, 1080, "fake", received_at=1090)))
    arena.receive(("batch", 1, 1099, 0, 0, [record]), view)
    tick(arena, view, clock, 1102)
    tick(arena, view, clock, 1300)
    cause = events(caplog)[0]["first_effective_cause"]
    assert cause["flags"][f"late_{kind}"]
    assert cause["data_at"] == 1090 and cause["data_age_s"] == 12
    assert cause["data_clock"] == ("book_at_parent_receipt" if kind == "book" else "trade_received_at")
    assert cause["frame_sequence"] == 1
    assert arena.learning.counts["pregap"] == 1


@pytest.mark.parametrize("window_first", [False, True])
def test_missing_ladder_same_frame_announcement(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, window_first: bool,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock = setup(tmp_path)
    w = window()
    clock[0] = 1000
    missing = ("b", w.slug, "up", None, None, 1000, "fake", None, "fake", None)
    announce = ("w", [window_wire(w)])
    arena.receive(("batch", 1, 999, 0, 0, [announce, missing] if window_first else [missing, announce]), view)
    tick(arena, view, clock, 1300)
    assert events(caplog)[0]["first_effective_cause"]["flags"]["missing_ladder"]


@pytest.mark.parametrize("sequence,drop", [(3, 0), (2, 1), (3, 1)])
def test_drop_flags_preserve_simultaneous_conditions(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, sequence: int, drop: int,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, _ = ready(tmp_path)
    clock[0] = 1100
    arena.receive(("batch", 1, 1099, 0, 0, []), view)
    arena.receive(("batch", sequence, 1099, drop, 0, []), view)
    tick(arena, view, clock, 1300)
    flags = events(caplog)[0]["first_effective_cause"]["flags"]
    assert flags["sequence_discontinuity"] == (sequence != 2)
    assert flags["drop_counter_increased"] == bool(drop)


@pytest.mark.parametrize("drop_at", [950, 1000])
def test_replayed_original_drop_keeps_original_clock_and_context(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, drop_at: float,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock = setup(tmp_path)
    clock[0] = drop_at
    arena.receive(("batch", 4, drop_at - 1, 1, 0, []), view)
    view.windows = (window(),)
    tick(arena, view, clock, 1000)
    tick(arena, view, clock, 1300)
    cause = events(caplog)[0]["first_effective_cause"]
    if drop_at < 1000:
        assert cause is None
    else:
        assert cause["effective_at"] == drop_at and cause["child_receive_at"] == drop_at
        assert cause["child_apply_at"] == 1000 and cause["frame_sequence"] == 4
        assert cause["flags"]["replayed_drop"] and cause["flags"]["drop_counter_increased"]


@pytest.mark.parametrize("case", ["late", "early_label", "terms", "invalid"])
def test_disposition_comes_from_actual_receipt_including_early_termination(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, case: str,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    at = 1306 if case == "late" else 1100 if case in ("early_label", "terms") else 1300
    if case == "early_label":
        view.outcomes = {w.slug: False}
    elif case == "terms":
        view.windows = (replace(w, start_price=101),)
    elif case == "invalid":
        view.sigma = -.001
    tick(arena, view, clock, at)
    row, = events(caplog)
    assert row["reason"] == arena.learning.recent[-1]["reason"]
    assert row["disposition"] == arena.learning.recent[-1]["status"]
    assert row["observation"] == ("terminated_before_advance" if case == "terms" else
                                  "late_first_pass" if case == "late" else
                                  "terminated_before_due" if case == "early_label" else "due")


def test_forecast_then_postforecast_gap_and_out_of_order_labels_emit_once_each(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    second = window(2000)
    view.windows = (w, second)
    tick(arena, view, clock, 900)
    tick(arena, view, clock, 1300)
    arena.feed_gap((w.slug,), False, False)
    tick(arena, view, clock, 1400)
    arena.feed_gap((), True, True)
    tick(arena, view, clock, 2300)
    view.outcomes = {second.slug: False}
    tick(arena, view, clock, 2900)
    view.outcomes[w.slug] = True
    tick(arena, view, clock, 2901)
    assert arena.learning.counts["scored"] == 2
    rows = events(caplog)
    assert len(rows) == 2 and all(r["disposition"] == "forecast" for r in rows)
    assert all(r["first_effective_cause"] is None for r in rows)
    assert arena._diagnostic is not None and not arena._diagnostic.pending


def test_restore_only_new_termination_no_historical_backfill(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    arena.learning.pending[w.slug]["pregap"] = "feed_late"
    arena._save(1000)
    caplog.clear()
    clock[0] = 1100
    restored = KalshiArena(arena.config, lambda: view, clock=lambda: clock[0], cpu=lambda: 0.0)
    row, = events(caplog)
    assert row["observation"] == "restart_history_unavailable"
    assert row["reason"] == "startup_inside" and row["first_effective_cause"] is None
    assert row["pending"]["stored_pregap"] == "feed_late"
    restored._save(1100)
    caplog.clear()
    again = KalshiArena(arena.config, lambda: view, clock=lambda: clock[0], cpu=lambda: 0.0)
    tick(again, view, clock, 1300)
    assert not events(caplog)


def test_full_recent_retention_simultaneous_removals_and_resource_bound(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock = setup(tmp_path)
    windows = tuple(window(1000 + n) for n in range(MAX_PENDING))
    view.windows = windows
    tick(arena, view, clock, 900)
    arena.learning.recent = [{"window": f"old-{n}", "status": "unknown", "reason": "late"}
                             for n in range(MAX_RECENT)]
    for w in windows:
        arena._degrade(w.slug, "feed_dropped")  # still prestart; no effective cause
    clock[0] = 1100
    arena.receive(("batch", 1, 1099, 1, 0, []), view)
    assert arena._diagnostic is not None and len(arena._diagnostic.pending) == MAX_PENDING
    tick(arena, view, clock, 1400)
    rows = events(caplog)
    assert len(rows) == MAX_PENDING and len({r["window"] for r in rows}) == MAX_PENDING
    assert all(r["reason"] == "late" for r in rows)
    assert not arena._diagnostic.pending
    assert max(len(json.dumps(r, separators=(",", ":"))) for r in rows) < 5000


@pytest.mark.parametrize("broken", [False, True])
def test_enabled_disabled_and_diagnostic_exceptions_preserve_every_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken: bool,
) -> None:
    left, lv, lc, w = ready(tmp_path / "on")
    right, rv, rc, _ = ready(tmp_path / "off")
    right._diagnostic = None
    right.town_id = left.town_id
    saves: list[list[tuple[float, bool]]] = [[], []]
    original_write = module._write

    def track(path: Path, text: str, *, durable: bool = False) -> None:
        saves[0 if "on" in path.parts else 1].append((lc[0], durable))
        original_write(path, text, durable=durable)

    monkeypatch.setattr(module, "_write", track)
    if broken:
        def fail(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("synthetic observer failure")
        monkeypatch.setattr(module._LearningDiagnostic, "cause", fail)
        monkeypatch.setattr(module._LearningDiagnostic, "after", fail)
    for at in (950, 1000, 1100, 1300, 1400, 1900):
        for town, view, clock in ((left, lv, lc), (right, rv, rc)):
            clock[0] = at
            if at == 1000:
                town.receive(("batch", 1, 999, 1, 0, [("g", [w.slug], False, False)]), view)
            if at == 1100:
                town.feed_book(Book(w.slug, "up", (), (), 1090, "fake"))
                town.feed_gap((), True, True)
            if at == 1900:
                view.outcomes = {w.slug: True}
            tick(town, view, clock, at)
    assert left.state(1900) == right.state(1900)
    assert left.panel(1900) == right.panel(1900)
    assert left.learning.state() == right.learning.state()
    assert left.path.read_bytes() == right.path.read_bytes()
    assert saves[0] == saves[1]
    assert left.learning.source == right.learning.source == fingerprint()
    assert left.inbox == right.inbox


def test_logging_failure_is_isolated_from_learner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arena, view, clock, _ = ready(tmp_path)
    original = module.log.info

    def fail(message: str, *args: Any, **kwargs: Any) -> None:
        if message.startswith("kalshi_learning_input_diagnostic"):
            raise RuntimeError("synthetic logging failure")
        original(message, *args, **kwargs)

    monkeypatch.setattr(module.log, "info", fail)
    tick(arena, view, clock, 1300)
    assert arena.learning.enabled and arena.learning.counts["forecasts"] == 1


@pytest.mark.parametrize("pregap", [False, True])
def test_restored_future_window_keeps_prospective_diagnostic_and_unknown_history(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, pregap: bool,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    arena.learning.counts["unknown"] = arena.learning.counts["late"] = 10
    arena.learning.pending[w.slug]["pregap"] = "feed_late" if pregap else None
    arena._save(900)
    caplog.clear()
    clock[0] = 950
    restored = KalshiArena(arena.config, lambda: view, clock=lambda: clock[0], cpu=lambda: 0.0)
    assert not events(caplog)
    if pregap:
        restored.feed_gap((w.slug,), True, True)
    tick(restored, view, clock, 1100)
    tick(restored, view, clock, 1300)
    row, = events(caplog)
    assert row["observation"] == "due" and row["reason"] == ("pregap" if pregap else None)
    assert row["disposition"] == ("unknown" if pregap else "forecast")
    assert row["cause_history"] == "restart_history_unavailable"
    if pregap:
        assert row["first_effective_cause"]["flags"]["explicit_slug"]
    else:
        assert row["first_effective_cause"] is None
    assert restored.learning.counts["unknown"] == 10 + int(pregap)


def test_restore_delta_excludes_historical_counts_and_frozen_slots(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, first = ready(tmp_path)
    second = window(2000)
    view.windows = (first, second)
    tick(arena, view, clock, 900)
    tick(arena, view, clock, 1300)
    arena.learning.counts["unknown"] = arena.learning.counts["late"] = 20
    arena._save(1300)
    caplog.clear()
    clock[0] = 2100
    restored = KalshiArena(arena.config, lambda: view, clock=lambda: clock[0], cpu=lambda: 0.0)
    row, = events(caplog)
    assert row["window"] == second.slug and row["reason"] == "startup_inside"
    assert row["counter_delta"] == {"forecasts": 0, "unknown": 1, "scored": 0}
    view.outcomes = {first.slug: False}
    tick(restored, view, clock, 2100)
    assert len(events(caplog)) == 1 and restored.learning.counts["scored"] == 1


def test_reversed_drop_does_not_move_original_max_context(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock = setup(tmp_path)
    clock[0] = 1000
    arena.receive(("batch", 1, 999, 1, 0, []), view)
    clock[0] = 950
    arena.receive(("batch", 3, 949, 2, 0, []), view)
    view.windows = (window(),)
    tick(arena, view, clock, 1000)
    tick(arena, view, clock, 1300)
    cause = events(caplog)[0]["first_effective_cause"]
    assert cause["effective_at"] == 1000 and cause["frame_sequence"] == 1
    assert not cause["flags"]["sequence_discontinuity"] and cause["flags"]["drop_counter_increased"]


def test_frame_context_cleared_after_original_receive_and_drain_exceptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    arena, view, clock, _ = ready(tmp_path)
    with pytest.raises(ValueError, match="unexpected Kalshi arena record"):
        arena.receive(("batch", 1, 999, 0, 0, [("bad",)]), view)
    assert arena._diagnostic_frame is None
    arena.feed_gap((), True, True)
    assert arena.inbox[-1][-1] is None
    arena.inbox.clear()
    clock[0] = 1100
    arena.receive(("batch", 2, 1099, 0, 0, [("g", [], True, True)]), view)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic original drain failure")

    monkeypatch.setattr(arena, "_gap", fail)
    with pytest.raises(RuntimeError, match="original drain"):
        arena._drain(1100)
    assert arena._diagnostic_frame is None


def test_lateness_uses_original_drain_check_and_preserves_second_effective_clock(tmp_path: Path) -> None:
    arena, _view, _, w = ready(tmp_path)
    arena.feed_book(Book(w.slug, "up", (), (), 1090, "fake"))
    readings = iter((1100.0, 1102.0))
    arena.clock = lambda: next(readings)
    arena._drain(1100)
    assert arena._diagnostic is not None
    cause = arena._diagnostic.pending[w.slug]["first"]
    assert cause["effective_at"] == 1102 and cause["child_apply_at"] == 1102
    assert cause["data_checked_at"] == 1100 and cause["data_age_s"] == 10


def test_observation_memory_pruned_across_many_new_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    arena, view, clock = setup(tmp_path)
    monkeypatch.setattr(arena, "_save", lambda now: None)
    monkeypatch.setattr(arena, "_status", lambda now: None)
    assert arena._diagnostic is not None
    for n in range(150):
        start = 1000 + n * 900
        w = window(start)
        view.windows = (w,)
        tick(arena, view, clock, start - 50)
        arena.feed_gap((w.slug,), False, False)
        tick(arena, view, clock, start + 1)
        assert len(arena._diagnostic.pending) <= 1
        tick(arena, view, clock, start + 300)
        assert not arena._diagnostic.pending
    assert arena.learning.counts["unknown"] == 150
    assert len(arena.learning.recent) == MAX_RECENT


def test_diagnostic_construction_failure_is_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.read_bytes

    def fail(path: Path) -> bytes:
        if path == Path(module.__file__):
            raise OSError("synthetic source read failure")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail)
    arena, view, clock, _ = ready(tmp_path)
    assert arena._diagnostic is None
    tick(arena, view, clock, 1300)
    assert arena.learning.enabled and arena.learning.counts["forecasts"] == 1


@pytest.mark.parametrize("at", [1300, 1306])
def test_terms_termination_at_or_past_horizon_has_no_advance_slot_observation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, at: float,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    view.windows = (replace(w, start_price=101),)
    tick(arena, view, clock, at)
    row, = events(caplog)
    assert row["learner_method"] == "discover"
    assert all(value is None for value in row["input_facts"].values())
    assert row["observation"] == "terminated_before_advance"
    assert row["pending"]["elapsed_s"] == at - w.start
    assert row["reason"] == arena.learning.recent[-1]["reason"] == "terms_changed"
    assert row["disposition"] == "unknown"
    assert arena.learning.counts["forecasts"] == 0



def test_restore_never_backfills_prior_same_slug_receipt_in_accepted_checkpoint(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    arena, view, clock, w = ready(tmp_path)
    # V1 accepts retained recent dicts without enforcing disjointness from pending.
    arena.learning.recent = [{"window": w.slug, "status": "unknown", "reason": "startup_inside"}]
    arena.learning.counts["unknown"] = arena.learning.counts["startup_inside"] = 1
    arena._save(900)
    caplog.clear()
    clock[0] = 1100
    restored = KalshiArena(arena.config, lambda: view, clock=lambda: clock[0], cpu=lambda: 0.0)
    assert restored.learning.enabled and restored.learning.counts["startup_inside"] == 2
    row, = events(caplog)
    assert row["window"] == w.slug and row["reason"] == "startup_inside"
    assert row["counter_delta"] == {"forecasts": 0, "unknown": 1, "scored": 0}



@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("failure", ["log_before_write", "log_after_write", "before_hook", "after_hook"])
def test_slot_failure_recovery_never_backfills_scores_or_repeats_written_slots(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
    count: int, failure: str,
) -> None:
    caplog.set_level(logging.INFO, logger=module.log.name)
    left, lv, lc = setup(tmp_path / "enabled")
    right, rv, rc = setup(tmp_path / "disabled")
    right._diagnostic = None
    right.town_id = left.town_id
    windows = tuple(window(1000 + n) for n in range(count))
    lv.windows = rv.windows = windows
    tick(left, lv, lc, 900)
    tick(right, rv, rc, 900)
    saves: list[list[tuple[float, bool]]] = [[], []]
    original_write = module._write

    def track(path: Path, text: str, *, durable: bool = False) -> None:
        index = 0 if "enabled" in path.parts else 1
        saves[index].append(((lc if index == 0 else rc)[0], durable))
        original_write(path, text, durable=durable)

    monkeypatch.setattr(module, "_write", track)
    original_log = module.log.info
    diagnostic = left._diagnostic
    assert diagnostic is not None
    original_before, original_after = diagnostic.before, diagnostic.after
    attempts = []

    def failed_log(message: str, *args: Any, **kwargs: Any) -> None:
        if message.startswith("kalshi_learning_input_diagnostic"):
            attempts.append(args[0])
            if len(attempts) == 1:
                if failure == "log_after_write":
                    original_log(message, *args, **kwargs)
                raise RuntimeError("synthetic first diagnostic handler failure")
        original_log(message, *args, **kwargs)

    def failed_hook(*args: Any, **kwargs: Any) -> Any:
        if args[1] == "advance":
            raise RuntimeError("synthetic slot observation hook failure")
        return (original_before if failure == "before_hook" else original_after)(*args, **kwargs)

    if failure.startswith("log_"):
        monkeypatch.setattr(module.log, "info", failed_log)
    else:
        monkeypatch.setattr(diagnostic, "before" if failure == "before_hook" else "after", failed_hook)
    at = 1300 + count
    tick(left, lv, lc, at)
    tick(right, rv, rc, at)
    if failure.startswith("log_"):
        assert len(attempts) == count  # first logging failure does not suppress the second slot
        assert all(diagnostic.pending[w.slug]["emitted"] for w in windows)
    observed_slots = list(events(caplog))
    assert len(observed_slots) == (count - 1 if failure == "log_before_write" else
                                   count if failure == "log_after_write" else 0)
    monkeypatch.setattr(module.log, "info", original_log)
    monkeypatch.setattr(diagnostic, "before", original_before)
    monkeypatch.setattr(diagnostic, "after", original_after)
    lv.outcomes = rv.outcomes = {w.slug: True for w in windows}
    tick(left, lv, lc, 1900 + count)
    tick(right, rv, rc, 1900 + count)
    assert events(caplog) == observed_slots
    assert all(row["disposition"] == "forecast" and row["observation"] == "due"
               and row["pending"]["forecast_none"] for row in observed_slots)
    assert len({row["window"] for row in observed_slots}) == len(observed_slots)
    assert left.learning.enabled and left.learning.counts["forecasts"] == left.learning.counts["scored"] == count
    assert left.state(1900 + count) == right.state(1900 + count)
    assert left.panel(1900 + count) == right.panel(1900 + count)
    assert left.path.read_bytes() == right.path.read_bytes()
    assert saves[0] == saves[1]
    assert not diagnostic.pending

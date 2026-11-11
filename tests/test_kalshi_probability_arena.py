"""Child-only V2 integration and isolation from existing V1/residents."""
from __future__ import annotations

import ast
import copy
import inspect
import json
from dataclasses import astuple, replace
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.kalshi_arena import ArenaConfig, ArenaLink, KalshiArena, WireView
from nightcrawler.kalshi_probability_learning import ProbabilityLearning
from nightcrawler.speeddesk_model import Window


def setup(path: Path) -> tuple[KalshiArena, WireView, list[float]]:
    clock = [900.0]
    view = WireView()
    town = KalshiArena(ArenaConfig(path, population=2), lambda: view, clock=lambda: clock[0])
    return town, view, clock


def window() -> Window:
    return Window("KXBTC15M-one", 1000, 1900, 100, venue_start_price=100, venue="kalshi")


def receive(town: KalshiArena, view: WireView, clock: list[float], at: float,
            records: list[Any] | None = None, *, dropped: int = 0, source_at: float | None = None) -> None:
    clock[0] = at
    town.receive(("batch", (town.link_seq or 0) + 1, at if source_at is None else source_at,
                  dropped, 0, records or []), view)


def tick(town: KalshiArena, view: WireView, clock: list[float], at: float) -> None:
    clock[0] = at
    town.step(at)


def admit(town: KalshiArena, view: WireView, clock: list[float]) -> Window:
    w = window()
    receive(town, view, clock, 900, [("w", [astuple(w)]), ("m", 100, 900, .001)])
    tick(town, view, clock, 900)
    return w


def forecast(town: KalshiArena, view: WireView, clock: list[float]) -> None:
    receive(town, view, clock, 1300, [("m", 100, 1300, .001)])
    tick(town, view, clock, 1300)


def test_quiet_maker_gap_excludes_v1_but_qualified_v2_forecasts_and_scores(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = admit(town, view, clock)
    receive(town, view, clock, 1100, [("g", (w.slug,), False, False)])
    tick(town, view, clock, 1100)
    forecast(town, view, clock)
    assert town.learning.counts["pregap"] == 1 and town.learning.counts["forecasts"] == 0
    assert town.learning_probability.counts["forecasts"] == 1
    receive(town, view, clock, 1900, [("o", [(w.slug, False)])])
    tick(town, view, clock, 1900)
    assert town.learning_probability.counts["scored"] == 1
    assert town.learning_probability.brier_q == .25
    assert town.panel(1900)["learning_probability"]["mode"] == "observe_only"
    assert town.learning.counts["scored"] == 0


@pytest.mark.parametrize("records", [[("g", (), True, False)], [("g", ("other",), False, True)]])
def test_socket_status_is_not_probability_input_with_still_fresh_accepted_tick(tmp_path: Path, records: list[Any]) -> None:
    town, view, clock = setup(tmp_path)
    admit(town, view, clock)
    receive(town, view, clock, 1300, [("m", 100, 1297, 0), *records])
    tick(town, view, clock, 1300)
    assert town.learning_probability.counts["forecasts"] == 1


@pytest.mark.parametrize("records", [[("m", 100, 1296.999, .001)], [("m", 100, 1300, None)]])
def test_real_missing_probability_input_still_excludes(tmp_path: Path, records: list[Any]) -> None:
    town, view, clock = setup(tmp_path)
    admit(town, view, clock)
    receive(town, view, clock, 1300, records)
    tick(town, view, clock, 1300)
    assert town.learning_probability.counts["invalid"] == 1


@pytest.mark.parametrize("at,expected", [(950, 1), (1000, 0), (1100, 0)])
def test_raw_drop_integrity_preserves_observed_time(tmp_path: Path, at: float, expected: int) -> None:
    town, view, clock = setup(tmp_path)
    w = admit(town, view, clock)
    receive(town, view, clock, at, dropped=1)
    tick(town, view, clock, max(at, 1000))
    receive(town, view, clock, 1300, [("m", 100, 1300, .001)], dropped=1)
    tick(town, view, clock, 1300)
    assert town.learning_probability.counts["forecasts"] == expected
    assert town.learning_probability.counts["pregap"] == 1 - expected
    assert w.slug in town.learning_probability.pending if expected else w.slug not in town.learning_probability.pending


def test_prestart_drop_before_first_metadata_record_does_not_poison_future_window(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    receive(town, view, clock, 950, dropped=1)
    receive(town, view, clock, 960, [("w", [astuple(window())])], dropped=1)
    receive(town, view, clock, 1300, [("m", 100, 1300, .001)], dropped=1)
    tick(town, view, clock, 1300)
    assert town.learning_probability.counts["forecasts"] == 1


def test_failed_partial_batch_cannot_supply_freshness(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    admit(town, view, clock)
    prior = town.learning_probability.batch_at
    with pytest.raises(ValueError):
        receive(town, view, clock, 1300, [("m", 100, 1300, .001), ("unrecognized",)])
    assert town.learning_probability.batch_at == prior
    assert town.learning_probability.error == "raw_stream_invalid"
    assert town.learning.enabled and len(town.residents) == 2


@pytest.mark.parametrize("seq,dropped", [(True, 0), (2, True), (2.0, 0)])
def test_raw_headers_validated_before_legacy_integer_coercion(tmp_path: Path, seq: Any, dropped: Any) -> None:
    town, view, clock = setup(tmp_path)
    admit(town, view, clock)
    clock[0] = 1100
    town.receive(("batch", seq, 1100, dropped, 0, []), view)
    assert town.learning_probability.error == "raw_stream_invalid"


def test_raw_invalid_outcome_cannot_become_legacy_truthy_score(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = admit(town, view, clock)
    forecast(town, view, clock)
    receive(town, view, clock, 1900, [("o", [(w.slug, "no")])])
    assert view.outcomes[w.slug] is True
    tick(town, view, clock, 1900)
    assert town.learning_probability.counts["invalid_label"] == 1
    assert town.learning_probability.counts["scored"] == 0


def test_terms_checked_before_same_batch_outcome_and_checkpoint(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = admit(town, view, clock)
    forecast(town, view, clock)
    receive(town, view, clock, 1900, [("o", [(w.slug, True)]),
            ("w", [astuple(replace(w, venue_start_price=101, start_price=101))])])
    town._save(1900)
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    assert restored.learning_probability.counts["terms_changed"] == 1
    assert restored.learning_probability.counts["scored"] == 0


def test_frozen_v2_survives_restart_and_does_not_migrate_v1(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = admit(town, view, clock)
    forecast(town, view, clock)
    town._save(1300)
    frozen = copy.deepcopy(town.learning_probability.pending[w.slug]["forecast"])
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    assert restored.learning_probability.pending[w.slug]["forecast"] == frozen
    receive(restored, view, clock, 1900, [("o", [(w.slug, True)])])
    tick(restored, view, clock, 1900)
    assert restored.learning_probability.counts["scored"] == 1
    saved = restored.state(1900)
    del saved["learning_probability"]
    del saved["learning_probability_epochs"]
    restored.path.write_text(json.dumps(saved))
    fresh = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    # A loaded checkpoint with missing probability history is not a fresh install.
    assert not fresh.learning_probability.enabled
    assert fresh.panel(1900)["learning_probability"] is None
    assert fresh.learning.state() == restored.learning.state()


@pytest.mark.parametrize("optional", [None, {"bad": "optional"}, 42])
def test_malformed_optional_v2_does_not_reset_v1_residents_or_counts(tmp_path: Path, optional: Any) -> None:
    town, view, clock = setup(tmp_path)
    saved = town.state(900)
    saved["learning_probability"] = optional
    expected = copy.deepcopy(saved)
    town.directory.mkdir(parents=True, exist_ok=True)
    town.path.write_text(json.dumps(saved))
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    assert restored.learning_probability.error == "malformed_optional_learning_state"
    assert restored.learning.state() == expected["learning"]
    assert [r.row for r in restored.residents.values()] == expected["residents"]
    assert not list(town.directory.glob("state.json.bad-*"))


def test_optional_callback_exceptions_and_absent_parent_interface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    town, view, clock = setup(tmp_path)
    assert "learning_probability" not in inspect.getsource(ArenaLink)
    tree = ast.parse(inspect.getsource(ProbabilityLearning))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs.intersection({"create_order", "cancel_order", "reserve_intent", "settings"})
    def broken(*args: Any) -> None:
        raise RuntimeError("synthetic observer")
    monkeypatch.setattr(town.learning_probability, "advance", broken)
    admit(town, view, clock)
    assert town.learning_probability.error == "optional_learning_method_failed"
    assert town.learning.enabled and len(town.residents) == 2
    town._save(900)


def test_v2_enabled_disabled_has_identical_v1_resident_and_save_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import nightcrawler.kalshi_arena as arena
    writes: list[tuple[str, bool]] = []
    original = arena._write
    def record(path: Path, text: str, *, durable: bool = False) -> None:
        writes.append((path.name, durable))
        original(path, text, durable=durable)
    monkeypatch.setattr(arena, "_write", record)
    left, lv, lc = setup(tmp_path / "left")
    right, rv, rc = setup(tmp_path / "right")
    right.learning_probability.disable("optional_learning_method_failed")
    for town, view, clock in ((left, lv, lc), (right, rv, rc)):
        w = admit(town, view, clock)
        receive(town, view, clock, 1100, [("g", (w.slug,), False, False)])
        tick(town, view, clock, 1100)
        forecast(town, view, clock)
        receive(town, view, clock, 1900, [("o", [(w.slug, True)])])
        tick(town, view, clock, 1900)
    a, b = left.state(1900), right.state(1900)
    for key in ("learning", "residents", "town", "events", "feed"):
        assert a[key] == b[key]
    assert writes[:len(writes) // 2] == writes[len(writes) // 2:]
    assert left.learning_probability.counts["scored"] == 1
    assert right.learning_probability.counts["scored"] == 0


def test_constructor_failure_does_not_prevent_v1_residents_or_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import nightcrawler.kalshi_arena as arena
    def broken(*args: Any) -> None:
        raise RuntimeError("synthetic unavailable observer")
    monkeypatch.setattr(arena, "ProbabilityLearning", broken)
    town, view, clock = setup(tmp_path)
    assert town.learning_probability is None and town.learning.enabled and len(town.residents) == 2
    admit(town, view, clock)
    forecast(town, view, clock)
    town._save(1300)
    assert json.loads(town.path.read_text())["learning_probability"] is None


def test_unreadable_arena_state_disables_v2_without_extra_reset_semantics(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    town.directory.mkdir(parents=True, exist_ok=True)
    town.path.write_text("not json")
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    assert restored.learning_probability.error == restored.learning.error == "arena_state_unreadable"
    assert len(restored.residents) == 2

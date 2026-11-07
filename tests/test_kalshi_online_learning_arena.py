from __future__ import annotations

import ast
import copy
import inspect
import json
from pathlib import Path

from nightcrawler.kalshi_arena import ArenaConfig, ArenaLink, KalshiArena, WireView
from nightcrawler.kalshi_online_learning import OnlineLearning
from nightcrawler.speeddesk_model import Window


def setup(path: Path) -> tuple[KalshiArena, WireView, list[float]]:
    clock = [900.0]
    view = WireView()
    town = KalshiArena(ArenaConfig(path, population=2), lambda: view, clock=lambda: clock[0])
    return town, view, clock


def tick(town: KalshiArena, view: WireView, clock: list[float], at: float) -> None:
    clock[0] = at
    view.bitcoin_at = at
    town.step(at)


def test_child_learns_untraded_and_survives_arena_void_and_restart(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = Window("KXBTC15M-one", 1000, 1900, 100, venue="kalshi")
    view.windows = (w,); view.bitcoin_price = 100; view.sigma = .001
    tick(town, view, clock, 900)
    tick(town, view, clock, 1300)
    town.feed_gap((w.slug,), False, False)
    tick(town, view, clock, 1400)
    town._save(1400)
    frozen = copy.deepcopy(town.learning.pending[w.slug]["forecast"])
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    assert restored.learning.pending[w.slug]["forecast"] == frozen
    view.outcomes = {w.slug: False}
    tick(restored, view, clock, 1900)
    assert restored.learning.counts["scored"] == 1
    assert restored.learning.brier_q == .25
    assert restored.learning.recent[-1]["post_gaps"]
    assert not restored.windows  # ordinary arena window deletion does not erase forecast


def test_wire_label_validation_before_legacy_bool_coercion(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = Window("KXBTC15M-one", 1000, 1900, 100, venue="kalshi")
    view.windows = (w,); view.bitcoin_price = 100; view.sigma = .001
    tick(town, view, clock, 900); tick(town, view, clock, 1300)
    clock[0] = 1900
    town.receive(("batch", 1, 1900, 0, 1, [("o", [(w.slug, "no")])]), view)
    assert view.outcomes[w.slug] is True  # existing arena behavior is unchanged
    tick(town, view, clock, 1900)
    assert town.learning.counts["scored"] == 0
    assert town.learning.counts["invalid_label"] == 1


def test_same_frame_changed_terms_and_label_does_not_train_stale_prediction(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = Window("KXBTC15M-one", 1000, 1900, 100, venue="kalshi")
    view.windows = (w,); view.bitcoin_price = 100; view.sigma = .001
    tick(town, view, clock, 900); tick(town, view, clock, 1300)
    clock[0] = 1900
    view.windows = (Window(w.slug, 1000, 1900, 101, venue="kalshi"),)
    town.receive(("batch", 1, 1900, 0, 1, [("o", [(w.slug, False)])]), view)
    assert town.learning.counts["scored"] == 0
    tick(town, view, clock, 1900)
    assert town.learning.counts["scored"] == 0
    assert town.learning.counts["terms_changed"] == 1


def test_malformed_optional_state_does_not_reset_residents_or_money(tmp_path: Path) -> None:
    town, _, clock = setup(tmp_path)
    saved = town.state(clock[0]); expected = copy.deepcopy(saved["residents"])
    saved["learning"] = {"bad": "optional"}
    town.directory.mkdir(parents=True, exist_ok=True)
    town.path.write_text(json.dumps(saved))
    restored = KalshiArena(town.config, WireView, clock=lambda: clock[0])
    assert not restored.learning.enabled
    assert [r.row for r in restored.residents.values()] == expected
    assert not list(town.directory.glob("state.json.bad-*"))


def test_unreadable_whole_arena_disables_learning_explicitly(tmp_path: Path) -> None:
    town, _, clock = setup(tmp_path)
    town.directory.mkdir(parents=True, exist_ok=True); town.path.write_text("not json")
    restored = KalshiArena(town.config, WireView, clock=lambda: clock[0])
    assert restored.learning.error == "arena_state_unreadable"
    assert len(restored.residents) == 2


def test_learner_failure_is_isolated_and_existing_parent_class_has_no_hook(tmp_path: Path) -> None:
    town, _, _ = setup(tmp_path)
    assert town._learning_call("missing_method") is None
    assert town.learning.error == "optional_learning_method_failed"
    assert "learning" not in inspect.getsource(ArenaLink)
    tree = ast.parse(inspect.getsource(OnlineLearning))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names.intersection({"create_order", "cancel_order", "reserve_intent", "limits", "settings"})


def test_raw_invalid_unknown_label_cannot_later_become_boolean_and_bounds() -> None:
    learner = OnlineLearning(900)
    learner.labels_received([("KXBTC15M-one", "no")], 900)
    w = Window("KXBTC15M-one", 1000, 1900, 100, venue="kalshi")
    learner.discover([w], 900)
    learner.advance([w], 100, 0, 1300, {w.slug: True}, 1300, {})
    assert learner.counts["forecasts"] == learner.counts["scored"] == 0
    assert learner.counts["invalid_label"] == 1
    for i in range(200):
        learner.labels_received([(f"unknown-{i}", "no")], 1300)
    assert len(learner.labels) == 64


def test_learning_enabled_disabled_produce_identical_resident_state(tmp_path: Path) -> None:
    left, lv, lc = setup(tmp_path / "left")
    right, rv, rc = setup(tmp_path / "right")
    right.learning.disable("optional_learning_method_failed")
    w = Window("KXBTC15M-one", 1000, 1900, 100, venue="kalshi")
    for view in (lv, rv):
        view.windows = (w,); view.bitcoin_price = 100; view.sigma = .001
    for at in (900, 1000, 1300, 1500):
        tick(left, lv, lc, at); tick(right, rv, rc, at)
    lv.outcomes = rv.outcomes = {w.slug: False}
    tick(left, lv, lc, 1900); tick(right, rv, rc, 1900)
    assert left.state(1900)["residents"] == right.state(1900)["residents"]
    assert left.state(1900)["town"] == right.state(1900)["town"]
    assert left.state(1900)["events"] == right.state(1900)["events"]
    assert left.learning.counts["scored"] == 1 and right.learning.counts["scored"] == 0


def test_cached_label_checkpoint_checks_terms_before_arena_step(tmp_path: Path) -> None:
    from dataclasses import astuple, replace
    town, view, clock = setup(tmp_path)
    w = Window("KXBTC15M-one", 1000, 1900, 100, venue="kalshi")
    view.windows = (w,); view.bitcoin_price = 100; view.sigma = .001
    tick(town, view, clock, 900); tick(town, view, clock, 1300)
    clock[0] = 1900
    town.receive(("batch", 1, 1900, 0, 1,
                  [("w", [astuple(replace(w, start_price=101))]), ("o", [(w.slug, False)])]), view)
    assert town.learning.counts["terms_changed"] == 1
    town._save(1900)
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    tick(restored, view, clock, 1900)
    assert restored.learning.counts["scored"] == 0


def test_invalid_copied_terms_cannot_poison_arena_checkpoint(tmp_path: Path) -> None:
    from dataclasses import replace
    town, _, _ = setup(tmp_path)
    w = Window("KXBTC15M-nan", 1000, 1900, 100, venue="kalshi")
    for i, changes in enumerate(({"start_price": float("nan")}, {"maker_coefficient": float("inf")},
                                 {"fee_rounding": "untrusted"}, {"tick_size": float("nan")})):
        candidate = replace(w, slug=f"KXBTC15M-invalid-{i}", start=1000 + i * 900,
                            end=1900 + i * 900, **changes)
        town.learning.discover([candidate], 900)
    assert not town.learning.pending
    assert town.learning.counts["invalid"] == 4
    town._save(900)
    assert json.loads(town.path.read_text())["learning"]["counts"]["invalid"] == 4

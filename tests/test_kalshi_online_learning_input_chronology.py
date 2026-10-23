"""Actual child chronology; synthetic inputs, no clients or venue data."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.kalshi_arena import ArenaConfig, KalshiArena, WireView, window_wire
from nightcrawler.speeddesk_model import Book, Trade, Window


def setup(path: Path) -> tuple[KalshiArena, WireView, list[float]]:
    clock = [900.0]
    view = WireView()
    view.bitcoin_price, view.sigma = 100, .001
    town = KalshiArena(ArenaConfig(path, population=2), lambda: view, clock=lambda: clock[0])
    return town, view, clock


def window(start: float = 1000) -> Window:
    return Window(f"KXBTC15M-{int(start)}", start, start + 900, 100, venue="kalshi")


def tick(town: KalshiArena, view: WireView, clock: list[float], now: float) -> None:
    clock[0] = view.bitcoin_at = now
    town.step(now)


def late(town: KalshiArena, w: Window, now: float, kind: str) -> None:
    if kind == "book":
        town.feed_book(Book(w.slug, "up", (), (), now - 10, "synthetic"))
    else:
        town.feed_trade(Trade(w.slug, "up", .5, 1, now - 10, str(now), received_at=now - 10))


@pytest.mark.parametrize("kind", ["book", "trade"])
@pytest.mark.parametrize("times,expected", [([950], 1), ([1100], 0), ([950, 1100], 0)])
def test_only_active_late_data_excludes_forecast(
    tmp_path: Path, kind: str, times: list[float], expected: int,
) -> None:
    town, view, clock = setup(tmp_path)
    w = window(); view.windows = (w,)
    tick(town, view, clock, 900)
    for now in times:
        late(town, w, now, kind)
        tick(town, view, clock, now)
    assert town.degraded == {w.slug: "feed_late"}  # practice history stays sticky
    tick(town, view, clock, 1300)
    assert town.learning.counts["forecasts"] == expected
    assert town.learning.counts["pregap"] == 1 - expected
    if not expected:
        assert town.learning.recent[-1]["forecast"] is None
    view.outcomes = {w.slug: False}
    tick(town, view, clock, 1900)
    assert town.town["void_feed"] == 1  # future practice history still voids practice
    assert town.learning.counts["scored"] == expected


@pytest.mark.parametrize("report", ["counter", "sequence"])
@pytest.mark.parametrize("absent", [False, True])
def test_global_drop_reaches_admitted_windows_outside_practice_map(
    tmp_path: Path, report: str, absent: bool,
) -> None:
    town, view, clock = setup(tmp_path)
    w = window(); view.windows = (w,)
    tick(town, view, clock, 900)
    if absent:
        town.windows.pop(w.slug)
        town.skipped.append(w.slug)
    clock[0] = 1100
    town.receive(("batch", 1, 1100, 0, 0, []), view)
    seq, dropped = (2, 1) if report == "counter" else (3, 0)
    town.receive(("batch", seq, 1100, dropped, 0, []), view)
    assert town.learning.pending[w.slug]["pregap"] == "feed_dropped"
    tick(town, view, clock, 1300)
    assert town.learning.counts["pregap"] == 1
    assert town.learning.counts["forecasts"] == 0


@pytest.mark.parametrize("drop_at,expected", [(950, 1), (1000, 0)])
@pytest.mark.parametrize("wire_announcement", [True, False])
def test_new_admission_replays_drop_occurrence_not_later_pass_time(
    tmp_path: Path, drop_at: float, expected: int, wire_announcement: bool,
) -> None:
    town, view, clock = setup(tmp_path)
    w = window()
    clock[0] = drop_at
    records = [("w", [window_wire(w)])] if wire_announcement else []
    town.receive(("batch", 1, drop_at, 1, 0, records), view)
    if not wire_announcement:
        view.windows = (w,)
    tick(town, view, clock, 1000)
    assert town.degraded == ({w.slug: "feed_dropped"} if not expected else {})
    tick(town, view, clock, 1300)
    assert town.learning.counts["forecasts"] == expected
    assert town.learning.counts["pregap"] == 1 - expected


@pytest.mark.parametrize("gap", ["selected", "stream", "coinbase"])
def test_v1_explicit_active_gap_stays_permanent_after_recovery(tmp_path: Path, gap: str) -> None:
    town, view, clock = setup(tmp_path)
    w = window(); view.windows = (w,)
    tick(town, view, clock, 900)
    town.feed_gap((w.slug,) if gap == "selected" else (), gap != "stream", gap != "coinbase")
    tick(town, view, clock, 1100)
    town.feed_gap((), True, True)
    tick(town, view, clock, 1200)
    tick(town, view, clock, 1300)
    assert town.learning.counts["pregap"] == 1
    assert town.learning.counts["forecasts"] == 0


def test_postforecast_drop_absent_practice_window_survives_restart_and_multiple_labels(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    first, second = window(), window(2000)
    view.windows = (first, second)
    tick(town, view, clock, 900)
    tick(town, view, clock, 1300)
    # Deliberately withhold first label to test out-of-order labels after both forecasts.
    tick(town, view, clock, 2300)
    frozen = {slug: copy.deepcopy(row["forecast"]) for slug, row in town.learning.pending.items()}
    town.windows.clear()
    town.skipped.extend((first.slug, second.slug))
    clock[0] = 2400
    town.receive(("batch", 1, 2400, 1, 0, []), view)
    for row in town.learning.pending.values():
        assert row["post_gaps"] == ["feed_dropped"]
    town._save(2400)
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    for row in restored.learning.pending.values():
        assert row["post_gaps"] == ["feed_dropped", "child_restart_gap"]
    clock[0] = 2900
    records: list[Any] = [("o", [(second.slug, False)]), ("o", [(first.slug, True)])]
    restored.receive(("batch", 1, 2900, 0, 0, records), view)
    tick(restored, view, clock, 2900)
    assert restored.learning.counts["scored"] == 2
    assert sum(restored.learning.bin_n) == 2
    for receipt in restored.learning.recent:
        assert receipt["forecast"] == frozen[receipt["window"]]
        assert receipt["post_gaps"] == ["feed_dropped", "child_restart_gap"]
    tick(restored, view, clock, 2901)
    assert restored.learning.counts["scored"] == 2


def test_restart_does_not_reconstruct_unforecasted_active_window(tmp_path: Path) -> None:
    town, view, clock = setup(tmp_path)
    w = window(); view.windows = (w,)
    tick(town, view, clock, 900)
    town._save(900)
    clock[0] = 1100
    restored = KalshiArena(town.config, lambda: view, clock=lambda: clock[0])
    tick(restored, view, clock, 1300)
    assert restored.learning.counts["startup_inside"] == 1
    assert restored.learning.counts["forecasts"] == 0


@pytest.mark.parametrize("window_first", [False, True])
def test_missing_ladder_at_start_same_frame_new_window_is_not_silently_ignored(
    tmp_path: Path, window_first: bool,
) -> None:
    town, view, clock = setup(tmp_path)
    w = window()
    clock[0] = 1000
    announcement = ("w", [window_wire(w)])
    # Keeping an absent ladder is an explicit reader-integrity failure.
    missing = ("b", w.slug, "up", None, None, 1000, "synthetic", None, "fake", None)
    records = [announcement, missing] if window_first else [missing, announcement]
    town.receive(("batch", 1, 1000, 0, 0, records), view)
    tick(town, view, clock, 1300)
    assert town.learning.counts["pregap"] == 1
    assert town.learning.counts["forecasts"] == 0


def test_optional_chronology_hooks_leave_practice_results_and_save_cadence_identical(tmp_path: Path) -> None:
    left, lv, lc = setup(tmp_path / "enabled")
    right, rv, rc = setup(tmp_path / "disabled")
    right.town_id = left.town_id  # independent fresh towns otherwise generate random identities
    right.learning.disable("optional_learning_method_failed")
    w = window()
    saves: list[list[float]] = [[], []]
    for index, (town, view) in enumerate(((left, lv), (right, rv))):
        view.windows = (w,)
        original_save = town._save

        def track(now: float, save: Any = original_save, recorded: list[float] = saves[index]) -> None:
            recorded.append(now)
            save(now)

        town._save = track  # type: ignore[method-assign]
    for at in (900, 950, 1000, 1300, 1400, 1900):
        for town, view, clock in ((left, lv, lc), (right, rv, rc)):
            if at == 950:
                late(town, w, at, "book")
            if at == 1400:
                town.feed_gap((w.slug,), False, False)
            if at == 1900:
                view.outcomes = {w.slug: False}
            tick(town, view, clock, at)
    lstate, rstate = left.state(1900), right.state(1900)
    lstate.pop("learning"); rstate.pop("learning")
    assert lstate == rstate
    assert saves[0] == saves[1]
    assert left.degraded == right.degraded
    assert left.learning.counts["scored"] == 1
    assert right.learning.counts["scored"] == 0

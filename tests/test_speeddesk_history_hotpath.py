"""Retained practice history must not multiply callback work or change fill receipts."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
import speeddesk_golden

from nightcrawler.speeddesk_model import PracticeDesk, Settlement, SpeedConfig, Window


class CountedHistory(list[Settlement]):
    visited = 0

    def __iter__(self) -> Iterator[Settlement]:
        for item in super().__iter__():
            self.visited += 1
            yield item


def history(desk: PracticeDesk, *, closed: int, unresolved: int, before: float) -> None:
    for index in range(closed + unresolved):
        end = before - (closed + unresolved - index) * 900
        slug = f"history-{index}"
        desk.add_window(Window(slug, end - 900, end, 100, maker_coefficient=0))
        if index < closed:
            assert desk.settle(slug, True, before) is not None


@pytest.mark.parametrize("method", ["advance", "evaluate"])
def test_mixed_history_is_scanned_a_bounded_number_of_times(method: str) -> None:
    desk = PracticeDesk()
    history(desk, closed=173, unresolved=226, before=1_791_475_200.0)
    now = 1_791_475_200.0
    desk.add_window(Window("current", now - 10, now + 890, 100))
    desk.add_window(Window("future", now + 900, now + 1800, 100))
    counted = CountedHistory(desk.closed)
    desk.closed = counted

    assert getattr(desk, method)(now) == []

    # Every unsettled historical window previously rescanned all 173 settlements.
    # Count work rather than impose a hardware-dependent timing threshold.
    assert counted.visited <= 3 * len(counted)
    assert desk.last_reason["history-398"] == "cutoff"
    assert desk.last_reason["current"] == "bitcoin_stale"
    assert desk.last_reason["future"] == "not_started"


def test_new_settlement_between_passes_is_seen_without_a_cached_membership() -> None:
    desk = PracticeDesk()
    now = 1_791_475_200.0
    history(desk, closed=3, unresolved=2, before=now)
    window = desk.windows["history-4"]
    assert desk.blocked(window, now) == "cutoff"
    desk.advance(now)
    assert desk.settle(window.slug, False, now) is not None
    desk.last_reason.pop(window.slug, None)

    desk.advance(now)
    desk.evaluate(now)

    assert window.slug not in desk.last_reason
    assert desk.blocked(window, now) == "settled"
    # Public callers retain settled-first semantics even with contradictory times.
    assert desk.blocked(replace(window, start=now + 1, end=now + 901), now) == "settled"
    desk.forget(window.slug)
    desk.add_window(replace(window, start=now + 1, end=now + 901))
    assert desk.blocked(desk.windows[window.slug], now) == "not_started"


class MixedHistoryDesk(PracticeDesk):
    def __init__(self, config: SpeedConfig) -> None:
        super().__init__(config)
        history(self, closed=8, unresolved=12, before=speeddesk_golden.T0 - 86400)


class RepeatedCheckDesk(MixedHistoryDesk):
    """The prior callback semantics: repeat the settled check for each candidate."""

    def _blocked_unsettled(self, window: Window, now: float) -> str:
        if any(item.window == window.slug for item in self.closed):
            return "settled"
        return super()._blocked_unsettled(window, now)


def test_mixed_history_preserves_baseline_receipts_and_complete_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # This replay exercises queue consumption, partial fills, ask disappearance,
    # reprices, settlement, cutoff and day stop with unresolved older windows present.
    monkeypatch.setattr(speeddesk_golden, "PracticeDesk", RepeatedCheckDesk)
    baseline = speeddesk_golden.run(SpeedConfig())
    monkeypatch.setattr(speeddesk_golden, "PracticeDesk", MixedHistoryDesk)
    actual = speeddesk_golden.run(SpeedConfig())

    assert actual == baseline
    counts = speeddesk_golden.coverage(actual)
    assert counts["speeddesk_fill:take"] > 0
    assert counts["speeddesk_fill:rest"] > 0
    assert counts["speeddesk_cancel:ask_moved"] > 0
    assert counts["settlement:"] > 0

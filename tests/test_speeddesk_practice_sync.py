"""Crash review minor (2026-10-13): the practice ledger commits with synchronous=NORMAL since speed step 2.

On a fresh volume a host failure before the first write-ahead-log checkpoint could lose the practice state while
the unsynced display copy survived; the "Practice receipt ledger missing beside existing report" check would then
stop SpeedRunner, which also builds the real-money companion, from starting or cancelling. The first save on a
fresh ledger is synced; the rest stay unsynced.
"""

from __future__ import annotations

from pathlib import Path

from test_speeddesk_snapshot_cache import make_runner

from nightcrawler.clock import FakeClock


def test_only_the_first_practice_save_on_a_fresh_ledger_is_synced(tmp_path: Path) -> None:
    clock = FakeClock(1_791_917_600.0)
    runner = make_runner(tmp_path, clock)
    calls: list[bool] = []
    original = runner.ledger.set_synchronous

    def spy(full: bool) -> None:
        calls.append(full)
        original(full)

    runner.ledger.set_synchronous = spy  # type: ignore[method-assign]
    try:
        runner.checkpoint(clock.now())
        assert calls == [True, False] and runner.ledger.get_kv("speeddesk_state") is not None
        clock.advance(5)
        runner.checkpoint(clock.now())
        assert calls == [True, False]  # later saves are not synced
    finally:
        runner.close()
    restarted = make_runner(tmp_path, clock)  # an existing ledger: no synced first save again
    calls.clear()
    restarted.ledger.set_synchronous = spy  # type: ignore[method-assign]
    try:
        restarted.checkpoint(clock.now())
        assert calls == []
    finally:
        restarted.close()

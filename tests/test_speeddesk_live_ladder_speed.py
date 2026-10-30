"""The speed and loss-plan fixes on top of the earned-growth ladder (rebased onto the deploy branch, 2026-10-13).

Bug 1's worst-case stop math uses each window's rung for the open and daily checks and the configured lifetime stop
at every rung; the one-row pre-send journal (speed step 2) still saves a new ladder stop and the status line at once;
and rung 0 is the owner's floor: "Go back to 10 that will be our low minimum resting number".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_speeddesk_live import make_desk
from test_speeddesk_live_ladder import BASE, LADDER_CAPS, at_rung

from nightcrawler.config import Settings
from nightcrawler.speeddesk_live import STATE_KEY
from nightcrawler.speeddesk_live_ladder import Ladder, limits_view
from nightcrawler.speeddesk_live_model import ActualFill
from nightcrawler.speeddesk_model import utc_day


def test_rung_zero_is_the_owners_ten_dollar_floor() -> None:
    """The configured defaults (Railway sets the same) are rung 0: $10 a window, $20 open, $6 day, $10 total, clip 5.
    Every demotion ends there and no rung is below it."""
    settings = Settings()
    assert (settings.speeddesk_kalshi_window_usd, settings.speeddesk_kalshi_open_usd,
            settings.speeddesk_kalshi_day_stop_usd, settings.speeddesk_kalshi_total_stop_usd,
            settings.speeddesk_kalshi_clip) == (10, 20, 6, 10, 5)
    ladder = Ladder(BASE)
    assert limits_view(ladder.limits_at_rung(0)) == {"window_usd": 10, "open_usd": 20, "day_stop_usd": 6,
                                                     "clip": 5, "total_stop_usd": 10}
    assert all(ladder.limits_at_rung(rung).window_usd >= 10 for rung in range(-3, ladder.top + 1))


def test_a_balancing_bid_uses_its_rungs_day_stop_and_the_fixed_lifetime_stop() -> None:
    """At rung 1 ($15 a window, $30 open, $9 day) after a $5.10 loss today: a resting first buy of 5 Down at $0.42
    fits (5.10 + 2.10 < 9; refused at rung 0's $6), and the 5-contract balancing bid at $0.57 adds nothing to the
    worst case. The old arithmetic (+ its $2.85) would pass neither the $9 day stop nor the $10 lifetime stop."""
    book, _ladder, window = at_rung(1)
    limits = book.limits_for(window.slug)
    assert (limits.window_usd, limits.open_usd, limits.day_loss_usd) == (15, 30, 9)
    now = window.start + 10
    book.day_pnl[utc_day(now)] = book.realized_pnl = -5.1
    assert book.can_buy(window.slug, "down", "rest", .42, 5, now) == ""
    first = book.reserve_intent(window.slug, "down", "rest", .42, 5, now, "nc-speed-first", .45)
    book.mark_submitted(first.client_order_id, "order-first")
    book.record_fill(ActualFill("fill-first", "order-first", first.client_order_id, window.slug, "down", .42, 5,
                                round(5 * (first.unit_reserve - .42), 6), now))
    at_risk = book.at_risk_usd
    assert at_risk == pytest.approx(2.10)
    assert 5.1 + at_risk + 5 * .57 >= limits.day_loss_usd and 5.1 + at_risk + 5 * .57 >= book.limits.total_loss_usd
    assert book.can_buy(window.slug, "up", "rest", .57, 5, now + 1) == ""
    book.reserve_intent(window.slug, "up", "rest", .57, 5, now + 1, "nc-speed-balance", .6)
    assert book.at_risk_usd == pytest.approx(at_risk)  # filling it can only shrink the loss
    # A risk-adding order still counts in full against the rung's day stop (5.10 + 2.10 + 2.10 >= 9), and the
    # lifetime stop is the configured $10 at every rung.
    assert book.can_buy(window.slug, "down", "rest", .42, 5, now + 2) == "day_stop"
    assert book.limits.total_loss_usd == 10 and limits.total_loss_usd == 10


def test_a_new_ladder_stop_is_saved_at_once(tmp_path: Path) -> None:
    """A promotion waits 24 h after any stop; with full saves at most once a second, a stop the ladder notes is
    still written at once (the next heartbeat), not left for a crash to forget."""
    desk, _, clock = make_desk(tmp_path, caps=LADDER_CAPS)
    try:
        desk.checkpoint()
        saved = desk.ledger.get_kv(STATE_KEY)
        assert saved["ladder"]["last_stop_at"] is None
        clock.advance(.1)  # well inside SAVE_EVERY_S
        desk.ladder.note_stop(clock.now())
        assert desk._must_save_now()
        desk._heartbeat()
        assert desk.ledger.get_kv(STATE_KEY)["ladder"]["last_stop_at"] == clock.now()
        # The same stop noted again a moment later waits for the ordinary one-second save.
        clock.advance(.1)
        desk.ladder.note_stop(clock.now())
        assert not desk._must_save_now()
    finally:
        desk.close()

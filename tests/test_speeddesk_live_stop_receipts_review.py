"""Stop receipts survive early exits and distinguish a new stop after an owner reset. Fake accounts only."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

import pytest
from test_speeddesk_live import make_desk
from test_speeddesk_live_pull import CAPS

from nightcrawler.config import Secret
from nightcrawler.speeddesk_live import STATE_KEY, KalshiLiveDesk
from nightcrawler.speeddesk_model import utc_day

Stop = Literal["total", "day"]


def near_stop(desk: KalshiLiveDesk, stop: Stop) -> None:
    # Change the counted-from anchor to represent a depleted budget while preserving a self-consistent
    # fake settlement ledger. This is test-only setup, never a production reset or a real variable change.
    if stop == "total":
        desk.book.stop_anchor = desk.book.realized_pnl + 9.9421
    else:
        day = utc_day(desk.clock())
        desk.book.day_anchor[day] = desk.book.day_pnl.get(day, 0) + 5.9421


def stop_receipts(desk: KalshiLiveDesk, stop: Stop) -> list[dict[str, Any]]:
    return [receipt.payload for receipt in desk.ledger.iter_receipts()
            if receipt.kind == "speeddesk_live_stop" and receipt.payload.get("stop") == stop]


@pytest.mark.parametrize("stop", ["total", "day"])
@pytest.mark.parametrize("exit_path", ["backoff", "paper", "account_error"])
def test_early_exit_persists_each_new_stop_with_one_receipt_across_restart(
    tmp_path: Path, stop: Stop, exit_path: str,
) -> None:
    mode = "paper" if exit_path == "paper" else "live"
    desk, account, clock = make_desk(tmp_path, caps=CAPS, mode=mode)
    try:
        near_stop(desk, stop)
        if exit_path == "backoff":
            desk.retry_at = clock.now() + 10
        elif exit_path == "account_error":
            account.balance_error = ValueError("review account read failed")
        else:
            desk.client_factory = lambda: pytest.fail("paper mode constructed an account client")
        asyncio.run(desk.step())
        assert not account.creates
        assert desk.book.halted if stop == "total" else desk.book.day_latched(clock.now())
        assert len(stop_receipts(desk, stop)) == 1
        saved = desk.ledger.get_kv(STATE_KEY)["book"]
        assert saved["halted"] if stop == "total" else saved["day_stop_day"] == utc_day(clock.now())
    finally:
        desk.close()
    again, account, clock = make_desk(tmp_path, caps=CAPS, mode=mode)
    try:
        assert again.book.halted if stop == "total" else again.book.day_latched(clock.now())
        assert len(stop_receipts(again, stop)) == 1
        again._heartbeat()
        assert len(stop_receipts(again, stop)) == 1
        assert not account.creates
    finally:
        again.close()


@pytest.mark.parametrize("stop", ["total", "day"])
def test_a_new_loss_immediately_after_startup_reset_has_its_own_stop_receipt(tmp_path: Path, stop: Stop) -> None:
    desk, _, _ = make_desk(tmp_path, caps=CAPS)
    try:
        near_stop(desk, stop)
        desk._heartbeat()
        assert len(stop_receipts(desk, stop)) == 1
    finally:
        desk.close()
    reset_key = "speeddesk_kalshi_resume_token" if stop == "total" else "speeddesk_kalshi_day_reset_token"
    reset = {reset_key: Secret("review-owner-reset-after-stop")}
    resumed, account, clock = make_desk(tmp_path, caps=CAPS, extra=reset)
    try:
        assert not resumed.book.halted if stop == "total" else not resumed.book.day_latched(clock.now())
        assert resumed.stop_state == (False, False)
        near_stop(resumed, stop)  # a later settled loss before the first ordinary successful trading step
        resumed._heartbeat()
        assert len(stop_receipts(resumed, stop)) == 2
        assert resumed.book.halted if stop == "total" else resumed.book.day_latched(clock.now())
        assert not account.creates
    finally:
        resumed.close()
    again, _, clock = make_desk(tmp_path, caps=CAPS, extra=reset)
    try:
        # The same owner value cannot clear the second stop, and startup must not manufacture a third receipt.
        assert again.book.halted if stop == "total" else again.book.day_latched(clock.now())
        assert len(stop_receipts(again, stop)) == 2
    finally:
        again.close()

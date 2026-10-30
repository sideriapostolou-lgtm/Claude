"""Independent combined-feed regressions: reconnect gaps must not rewind spot or renew its age."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_speeddesk_coinbase_skew import Timed, at_trade, match, runner_with_feeds

from nightcrawler.clock import FakeClock
from nightcrawler.config import Settings
from nightcrawler.speeddesk_feeds import COINBASE_EXCHANGE_WS, COINBASE_WS, LiveFeeds

STAMP = 1_791_917_623.5
ISO = "2026-10-13T18:53:43.500000Z"


def batch(*messages: str) -> str:
    return json.dumps({"channel": "market_trades", "events": [
        event for message in messages for event in json.loads(message)["events"]]})


@pytest.mark.parametrize("newer_in_batch", [False, True])
def test_unseen_older_trade_with_same_stamp_cannot_rewind_price_or_refresh_receipt(
    tmp_path: Path, newer_in_batch: bool,
) -> None:
    """Both Exchange subscriptions miss 101; the delayed backup brings it after 102, optionally with 103."""
    clock = FakeClock(STAMP - 1)
    backup = [at_trade(102, ISO, "83005.00"), at_trade(101, ISO, "83000.00")]
    if newer_in_batch:
        backup.append(at_trade(103, ISO, "83006.00"))
    sockets = {
        COINBASE_EXCHANGE_WS: [Timed([(STAMP + .02, match(102, ISO, "83005.00"))], clock),
                              Timed([(STAMP + .021, match(102, ISO, "83005.00"))], clock)],
        COINBASE_WS: [Timed([(STAMP + .08, batch(*backup))], clock)],
    }
    runner, delivered = runner_with_feeds(tmp_path, clock, sockets)
    try:
        expected_prices = [83005, 83006] if newer_in_batch else [83005]
        assert [price for price, _at, _received in delivered] == expected_prices
        assert runner.live_snapshot().bitcoin_price == expected_prices[-1]
        assert runner.desk.tape.revision == len(expected_prices)
        assert runner.tick_receipt is not None
        assert runner.tick_receipt.received_at == delivered[-1][2]
        if not newer_in_batch:
            assert runner.tick_receipt.received_at < STAMP + .08
    finally:
        runner.close()


def test_refused_future_copy_does_not_advance_equal_stamp_trade_order(tmp_path: Path) -> None:
    """102 is too far ahead on Exchange. A valid backup batch must still deliver both 101 and 102 in order."""
    clock = FakeClock(STAMP - 1)
    sockets = {
        COINBASE_EXCHANGE_WS: [Timed([(STAMP - .30, match(102, ISO, "83005.00"))], clock),
                              Timed([(STAMP - .29, match(102, ISO, "83005.00"))], clock)],
        COINBASE_WS: [Timed([(STAMP - .20, batch(at_trade(102, ISO, "83005.00"),
                                              at_trade(101, ISO, "83000.00")))], clock)],
    }
    runner, delivered = runner_with_feeds(tmp_path, clock, sockets)
    try:
        assert [price for price, _at, _received in delivered] == [83000, 83005]
        assert runner.live_snapshot().bitcoin_price == 83005
    finally:
        runner.close()


def test_late_older_stamp_cannot_replace_same_stamp_ordering_watermark() -> None:
    """Interleaved old batches must not let the next same-stamp older trade evade the tie check."""
    feed = LiveFeeds(Settings(), on_tick=lambda *_: None, on_book=lambda _: None,
                     on_trade=lambda _: None, on_windows=lambda _: None, on_status=lambda _: None)
    assert feed._first_delivery(102, STAMP)
    assert feed._first_delivery(99, STAMP - 1)  # BitcoinTape independently refuses an older timestamp
    assert not feed._first_delivery(101, STAMP)
    assert feed._first_delivery(103, STAMP)
    assert not feed._first_delivery(103, STAMP)


def test_unknown_trade_ids_keep_the_existing_timestamp_only_behavior() -> None:
    feed = LiveFeeds(Settings(), on_tick=lambda *_: None, on_book=lambda _: None,
                     on_trade=lambda _: None, on_windows=lambda _: None, on_status=lambda _: None)
    assert feed._first_delivery(None, STAMP)
    assert feed._first_delivery(102, STAMP)
    assert feed._first_delivery(None, STAMP)
    assert not feed._first_delivery(101, STAMP)

"""Speed plan step 4: Coinbase Exchange matches lead, Advanced Trade backs up, each trade counts once.

The fixtures are real messages recorded at the same time on 2026-10-13 from 18:53:43 UTC: the Exchange feed's
``matches`` and ``heartbeat`` channels and Advanced Trade's ``market_trades`` and ``heartbeats``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Self

import pytest
from test_speeddesk_live import TICKER, make_desk

from nightcrawler.clock import FakeClock
from nightcrawler.config import Settings
from nightcrawler.speeddesk_feeds import (
    COINBASE_EXCHANGE_WS,
    COINBASE_FEEDS,
    COINBASE_WS,
    LiveFeeds,
    advanced_trade_ticks,
    coinbase_ticks,
    exchange_ticks,
    timestamp,
)
from nightcrawler.speeddesk_metrics import TickReceipt, fresh_window_slugs, tick_timings
from nightcrawler.speeddesk_model import (
    FUTURE_SKEW_S,
    PracticeDesk,
    SpeedConfig,
    Window,
)

FIXTURES = Path(__file__).parent / "fixtures"


def recorded(name: str) -> list[dict[str, Any]]:
    path = FIXTURES / f"coinbase_{name}_20261013.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def messages(name: str) -> list[dict[str, Any]]:
    return [json.loads(row["message"]) for row in recorded(name)]


def test_exchange_parser_reads_each_recorded_match_and_skips_the_replayed_last_match() -> None:
    rows = messages("exchange_matches")
    assert {row["type"] for row in rows} == {"subscriptions", "last_match", "match", "heartbeat"}
    for row in rows:
        ticks = exchange_ticks(row)
        if row["type"] == "match":
            assert ticks == [(float(row["price"]), timestamp(row["time"]), row["trade_id"])]
        else:
            assert ticks == []  # last_match repeats a trade from before the subscription
    ids = [tick[2] for row in rows for tick in exchange_ticks(row)]
    assert len(ids) == 50 and ids == sorted(set(ids))


def test_advanced_trade_parser_skips_the_snapshot_replayed_on_every_connect() -> None:
    rows = messages("advanced_trades")
    snapshot = next(row for row in rows if row.get("channel") == "market_trades")
    assert snapshot["events"][0]["type"] == "snapshot" and advanced_trade_ticks(snapshot) == []
    updates = [row for row in rows if row.get("channel") == "market_trades" and row is not snapshot]
    assert updates and all(event["type"] == "update" for row in updates for event in row["events"])
    for row in updates:
        ticks = advanced_trade_ticks(row)
        trades = [trade for event in row["events"] for trade in event["trades"]]
        assert sorted(tick[2] for tick in ticks) == sorted(int(trade["trade_id"]) for trade in trades)
        assert [tick[1] for tick in ticks] == sorted(tick[1] for tick in ticks)  # oldest first
        assert coinbase_ticks(row) == [(price, at) for price, at, _ in ticks]
    assert all(advanced_trade_ticks(row) == [] for row in rows if row.get("channel") in ("heartbeats", "subscriptions"))


def test_both_recordings_share_trade_ids_and_prices() -> None:
    exchange = {tick[2]: tick for row in messages("exchange_matches") for tick in exchange_ticks(row)}
    advanced = {tick[2]: tick for row in messages("advanced_trades") for tick in advanced_trade_ticks(row)}
    shared = exchange.keys() & advanced.keys()
    assert len(shared) >= 30
    assert all(exchange[key][:2] == advanced[key][:2] for key in shared)  # same price, same exchange time


class Replay:
    """A websocket that replays recorded messages, then stays open (or closes when ``then`` is "close")."""

    def __init__(self, rows: list[str], then: str = "open") -> None:
        self.rows, self.then = list(rows), then
        self.sent: list[dict[str, Any]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        await asyncio.sleep(0)  # let the other connections interleave
        if self.rows:
            return self.rows.pop(0)
        if self.then == "close":
            raise ConnectionError("closed")
        await asyncio.Future()
        raise AssertionError("unreachable")


class Received(Replay):
    """Replays recorded rows, moving the shared clock to each row's recorded local receipt time first (the feed
    refuses a trade stamped more than FUTURE_SKEW_S after its receipt, as every desk does)."""

    def __init__(self, rows: list[dict[str, Any]], clock: FakeClock, then: str = "open") -> None:
        super().__init__([row["message"] for row in rows], then)
        self.times = [row["received_at"] for row in rows]
        self.clock = clock

    async def recv(self) -> str:
        if self.rows and self.times:
            at = self.times.pop(0)
            if at > self.clock.now():
                self.clock.set(at)
        return await super().recv()


def run_coinbase(connect: Any, rounds: int = 400, clock: FakeClock | None = None
                 ) -> tuple[list[tuple[float, float, float]], list[dict[str, Any]]]:
    ticks: list[tuple[float, float, float]] = []
    statuses: list[dict[str, Any]] = []
    clock = clock or FakeClock(1_791_917_623.0)
    feed = LiveFeeds(Settings(), on_tick=lambda *args: ticks.append(args), on_book=lambda _: None,
                     on_trade=lambda _: None, on_windows=lambda _: None, on_status=statuses.append,
                     clock=clock.now, coinbase_connect=connect)

    async def scenario() -> None:
        task = asyncio.create_task(feed._coinbase())
        for _ in range(rounds):
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    return ticks, statuses


def test_each_recorded_trade_reaches_the_desk_once_from_whichever_feed_brings_it_first() -> None:
    clock = FakeClock(1_791_917_623.0)
    exchange_rows, advanced_rows = recorded("exchange_matches"), recorded("advanced_trades")
    sockets: dict[str, list[Replay]] = {COINBASE_EXCHANGE_WS: [Received(exchange_rows, clock),
                                                               Received(exchange_rows, clock)],
                                        COINBASE_WS: [Received(advanced_rows, clock)]}
    ticks, statuses = run_coinbase(lambda url, **_kwargs: sockets[url].pop(0), clock=clock)
    expected = ({tick[2] for row in messages("exchange_matches") for tick in exchange_ticks(row)}
                | {tick[2] for row in messages("advanced_trades") for tick in advanced_trade_ticks(row)})
    assert len(ticks) == len(expected)  # two Exchange copies and Advanced Trade's: one delivery per trade id
    assert statuses[-1]["coinbase"] == "connected"
    assert statuses[-1]["coinbase_feeds"] == {name: "connected" for name, _url in COINBASE_FEEDS}


def test_the_backup_keeps_ticks_flowing_when_both_exchange_connections_fail() -> None:
    clock = FakeClock(1_791_917_623.0)
    advanced_rows = recorded("advanced_trades")

    def connect(url: str, **_kwargs: Any) -> Replay:
        if url == COINBASE_EXCHANGE_WS:
            raise OSError("exchange feed unreachable")
        return Received(advanced_rows, clock)

    ticks, statuses = run_coinbase(connect, clock=clock)
    assert len(ticks) == len({tick[2] for row in messages("advanced_trades") for tick in advanced_trade_ticks(row)})
    assert statuses[-1]["coinbase"] == "connected"
    assert statuses[-1]["coinbase_feeds"] == {"exchange_a": "disconnected", "exchange_b": "disconnected",
                                              "advanced_trade": "connected"}


def test_bitcoin_data_reads_disconnected_only_when_every_connection_is_down() -> None:
    exchange_rows = [row["message"] for row in recorded("exchange_matches")][:5]

    def connect(url: str, **_kwargs: Any) -> Replay:
        if url == COINBASE_WS:
            raise OSError("backup unreachable")
        return Replay(exchange_rows, then="close")

    _, statuses = run_coinbase(connect, rounds=60)
    assert any(status["coinbase"] == "connected" for status in statuses)
    assert statuses[-1]["coinbase"] == "disconnected"  # both Exchange replays closed and the backup is down
    assert set(statuses[-1]["coinbase_feeds"].values()) == {"disconnected"}


def test_a_tick_stamped_a_few_ms_after_local_receipt_is_accepted_everywhere(tmp_path: Path) -> None:
    """On Railway's clock most Exchange ticks arrive "before" their stamps; they used to be dropped."""
    desk, _, clock = make_desk(tmp_path)
    try:
        now = clock.now()
        before = desk.twin.tape.revision
        desk.on_tick(80010, now + .005, now)  # 5 ms ahead
        assert desk.twin.tape.revision == before + 1 and desk.twin.tape.price == 80010
        desk.on_tick(80020, now + FUTURE_SKEW_S + .05, now)  # further ahead than any clock difference: refused
        assert desk.twin.tape.price == 80010
        window = desk.book.windows[TICKER]
        snapshot = desk.snapshot()
        future = type(snapshot)(snapshot.windows, snapshot.books, 80010, now + .005, snapshot.sigma,
                                snapshot.maker_windows)
        assert desk._feed_reason(window, future, now) == ""
        assert desk._feed_reason(window, future, now + 3.1) == "Bitcoin feed stale"  # the stale cancel still fires
    finally:
        desk.close()


def test_practice_desk_and_metrics_accept_the_same_bounded_skew() -> None:
    model = PracticeDesk(SpeedConfig())
    model.add_window(Window("btc15m", 1000, 1900, 100))
    model.tick_btc(100, 1010.005)
    assert model.blocked(model.windows["btc15m"], 1010) != "bitcoin_stale"
    assert model.blocked(model.windows["btc15m"], 1010.005 - FUTURE_SKEW_S - .01) == "bitcoin_stale"
    timings = tick_timings(TickReceipt(1010.005, 1010.0, 50.0), 50.002)
    assert timings["btc_exchange_to_decision"] == (0.0, "ok") and timings["btc_receipt_to_decision"][1] == "ok"
    assert tick_timings(TickReceipt(1011.0, 1010.0, 50.0), 50.1)["btc_exchange_to_decision"] == (None, "invalid")
    assert fresh_window_slugs([], {}, 1010.005, set(), 1010.0) == set()  # no window, but not refused as stale


@pytest.mark.parametrize(("delay", "accepted"), [(-.005, True), (-.3, False), (.5, True), (3.5, False)])
def test_the_runner_judges_bitcoin_freshness_with_the_same_bound(tmp_path: Path, delay: float,
                                                                 accepted: bool) -> None:
    """``delay`` is local receipt minus the exchange stamp: negative when the stamp is ahead of our clock."""
    import threading

    from test_speeddesk_snapshot_cache import Companion, Feeds

    from nightcrawler.speeddesk import SpeedRunner

    clock = FakeClock(1000.0)
    runner = SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock, feed_factory=Feeds,
                         live_factory=Companion)
    try:
        runner.on_tick(80000, 1000 - delay, 1000)
        assert (runner.desk.tape.price == 80000) is accepted
    finally:
        runner.close()

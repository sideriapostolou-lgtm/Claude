"""Generated keys and fake frames only: market authentication never enables orders."""

from __future__ import annotations

import asyncio
import base64
import json
import random
import threading
from collections import deque
from dataclasses import replace
from typing import Any, Self

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fakes import FakeClock
from test_speeddesk_kalshi import SERIES, START, TICKER, book, market, trade
from test_speeddesk_venues import make

from nightcrawler import speeddesk_kalshi_client
from nightcrawler.config import Secret, Settings
from nightcrawler.speeddesk_kalshi import KalshiFeeds, parse_trades, parse_window
from nightcrawler.speeddesk_kalshi_ws import (
    PATH,
    URL,
    KalshiMarketWS,
    MarketDataGap,
    MarketHandshake,
    MarketState,
)
from nightcrawler.speeddesk_model import Level, Window

NEXT = "KXBTC15M-26OCT121500-00"


def settings() -> tuple[Settings, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    return Settings(kalshi_key_id=Secret("throwaway-test-key"), kalshi_private_key=Secret(pem)), key


def ack(channel: str = "orderbook_delta", sid: int = 7) -> dict[str, Any]:
    return {"type": "subscribed", "id": 1 if channel == "orderbook_delta" else 2,
            "msg": {"channel": channel, "sid": sid}}


def snapshot(*, seq: int = 2, ticker: str = TICKER, at: float = START + 1) -> dict[str, Any]:
    return {"type": "orderbook_snapshot", "sid": 7, "seq": seq, "sending_ts_ms": int(at * 1000),
            "msg": {"market_ticker": ticker, "market_id": "public-market-uuid",
                    "yes_dollars_fp": [["0.4000", "2.50"], ["0.3900", "3.00"]],
                    "no_dollars_fp": [["0.4100", "4.00"], ["0.4200", "5.00"]]}}


def delta(*, seq: int = 3, at: float = START + 1.1) -> dict[str, Any]:
    return {"type": "orderbook_delta", "sid": 7, "seq": seq, "sending_ts_ms": int(at * 1000),
            "msg": {"market_ticker": TICKER, "market_id": "public-market-uuid", "side": "no",
                    "price_dollars": "0.4100", "delta_fp": "-1.25", "ts_ms": int(at * 1000)}}


def print_frame(*, seq: int = 1, at: float = START + 1.2, side: str = "no") -> dict[str, Any]:
    return {"type": "trade", "sid": 9, "seq": seq, "sending_ts_ms": int(at * 1000),
            "msg": {"market_ticker": TICKER, "trade_id": "print-1", "count_fp": "1.25",
                    "yes_price_dollars": "0.40", "no_price_dollars": "0.60",
                    "taker_side": side, "taker_outcome_side": side,
                    "taker_book_side": "ask" if side == "no" else "bid", "is_block_trade": False,
                    "ts_ms": int(at * 1000)}}


def state(*, with_snapshot: bool = True) -> MarketState:
    result = MarketState(frozenset((TICKER, NEXT)))
    result.apply(ack(), START + 1)
    result.apply(ack("trade", 9), START + 1)
    if with_snapshot:
        result.apply(snapshot(seq=1), START + 1)
        warmup = delta(seq=2, at=START + 1)
        warmup["msg"]["delta_fp"] = "0.00"
        result.apply(warmup, START + 1)
    return result


def test_handshake_is_exact_ed25519_market_get_and_never_instantiates_order_client(monkeypatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Market reader must not construct the account/order client")

    monkeypatch.setattr(speeddesk_kalshi_client, "KalshiClient", forbidden)
    config, private = settings()
    assert config.speeddesk_kalshi_mode == "paper"
    headers = MarketHandshake(config).headers(START + 1.234)
    assert headers["KALSHI-ACCESS-KEY"] == "throwaway-test-key"
    stamp = headers["KALSHI-ACCESS-TIMESTAMP"]
    private.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
                               (stamp + "GET" + PATH).encode())
    assert PATH == "/trade-api/ws/v2"


def test_market_signer_requires_both_keys_and_ed25519() -> None:
    with pytest.raises(ValueError, match="credentials_missing"):
        MarketHandshake(Settings())
    config, _ = settings()
    with pytest.raises(ValueError):
        MarketHandshake(replace(config, kalshi_private_key=Secret("not a private key")))


def test_yes_scale_snapshot_and_no_delta_are_converted_back_to_outcome_prices() -> None:
    reader = state(with_snapshot=False)
    assert reader.apply(snapshot(), START + 1) == ((), ())
    (up, down), _ = reader.apply(delta(), START + 1.1)
    assert (up.bids[0].price, up.asks[0].price, down.bids[0].price, down.asks[0].price) == (0.4, 0.41, 0.59, 0.6)
    assert up.at == up.exchange_at == START + 1.1
    assert up.source == "websocket"
    assert up.asks[0].size == down.bids[0].size == 2.75
    assert up.sequence == "kalshi-ws:7:3"
    raw = delta(seq=4, at=START + 1.2)
    raw["msg"]["delta_fp"] = "-2.75"
    (up, _), _ = reader.apply(raw, START + 1.2)
    assert up.asks[0].price == 0.42


def test_missing_empty_side_is_valid_but_deltas_require_that_markets_snapshot() -> None:
    reader = state(with_snapshot=False)
    with pytest.raises(MarketDataGap, match="snapshot_required"):
        reader.apply(delta(seq=1), START + 1.1)
    reader = state(with_snapshot=False)
    raw = snapshot()
    del raw["msg"]["no_dollars_fp"]
    assert reader.apply(raw, START + 1) == ((), ())
    change = delta()
    change["msg"].update(side="yes", price_dollars="0.40", delta_fp="1.00")
    (up, down), _ = reader.apply(change, START + 1.1)
    assert not up.asks and not down.bids


@pytest.mark.parametrize("seq", [2, 4, 99, True, None])
def test_gap_duplicate_and_out_of_order_sequence_never_apply_depth(seq: Any) -> None:
    reader = state()
    raw = delta()
    raw["seq"] = seq
    with pytest.raises(MarketDataGap, match="sequence_gap"):
        reader.apply(raw, START + 1.1)
    assert reader.depth[TICKER]["no"][0.59] == 4


def test_sequence_is_per_subscription_not_per_market_or_shared_between_channels() -> None:
    reader = state()
    reader.apply(snapshot(seq=3, ticker=NEXT), START + 1)
    reader.apply(print_frame(seq=80), START + 1.2)
    reader.apply(delta(seq=4, at=START + 1.2), START + 1.2)
    assert reader.sequences == {7: 4, 9: 80}


@pytest.mark.parametrize("change", ["unknown_sid", "wrong_channel", "wrong_market", "no_ack", "private_channel"])
def test_unknown_subscription_market_or_private_payload_fails_closed(change: str) -> None:
    reader = state()
    raw = delta()
    if change == "unknown_sid":
        raw["sid"] = 100
    elif change == "wrong_channel":
        raw["sid"] = 9
    elif change == "wrong_market":
        raw["msg"]["market_ticker"] = "KXETH15M-26OCT121445-45"
    elif change == "no_ack":
        reader = MarketState(frozenset((TICKER,)))
    else:
        raw = ack("fill", 10)
    with pytest.raises(MarketDataGap):
        reader.apply(raw, START + 1.1)


@pytest.mark.parametrize("change", ["old_send_time", "future_send_time", "old_event_time",
                                    "negative_depth", "fractional_milliqty", "crossed"])
def test_backlog_missing_times_and_invalid_depth_invalidate_instead_of_refreshing(change: str) -> None:
    reader = state()
    raw = delta()
    if change == "old_send_time":
        raw["sending_ts_ms"] = int((START - 4) * 1000)
    elif change == "future_send_time":
        raw["sending_ts_ms"] = int((START + 2) * 1000)
    elif change == "old_event_time":
        raw["msg"]["ts_ms"] = int((START - 4) * 1000)
    elif change == "negative_depth":
        raw["msg"]["delta_fp"] = "-100"
    elif change == "fractional_milliqty":
        raw["msg"]["delta_fp"] = "0.001"
    else:
        raw["msg"].update(side="yes", price_dollars="0.50", delta_fp="1.00")
    with pytest.raises(MarketDataGap):
        reader.apply(raw, START + 1.1)


@pytest.mark.parametrize("side", ["yes", "no"])
def test_prints_have_actual_size_timestamp_direction_and_rest_dedup_identity(side: str) -> None:
    reader = state()
    _, (up, down) = reader.apply(print_frame(side=side), START + 1.2)
    rest = trade(direction=side)
    rest.update(count_fp="1.25", created_time="2026-10-12T18:30:01.200Z")
    assert {up, down} == set(parse_trades([rest], TICKER, START + 1.2))
    assert up.aggressor == ("buy" if side == "yes" else "sell")
    assert down.aggressor == ("sell" if side == "yes" else "buy")


@pytest.mark.parametrize("field,value", [("taker_book_side", "bid"), ("taker_side", "yes"),
                                         ("is_block_trade", None), ("trade_id", ""),
                                         ("ts_ms", int((START - 5) * 1000)), ("count_fp", "0.001")])
def test_ambiguous_or_old_print_cannot_fill_a_queue(field: str, value: Any) -> None:
    raw = print_frame()
    raw["msg"][field] = value
    with pytest.raises(MarketDataGap):
        state().apply(raw, START + 1.2)


def test_block_trade_does_not_enable_makers_or_create_a_print() -> None:
    raw = print_frame()
    raw["msg"]["is_block_trade"] = True
    reader = state()
    assert reader.apply(raw, START + 1.2) == ((), ())
    assert not reader.trade_at


def test_optional_send_timestamp_snapshot_seeds_depth_without_making_it_tradable() -> None:
    reader = state(with_snapshot=False)
    raw = snapshot()
    del raw["sending_ts_ms"]
    assert reader.apply(raw, START + 1) == ((), ())
    assert reader.depth[TICKER]["no"][0.59] == 4
    assert TICKER in reader.unproven and not reader.book_at and not reader.exchange_at
    change = delta(at=START + 1.25)
    del change["sending_ts_ms"]
    (up, down), _ = reader.apply(change, START + 1.3)
    assert up.exchange_at == down.exchange_at == START + 1.25  # Actual exchange event, not receipt.
    assert up.at == START + 1.3 and up.asks[0].size == 2.75
    assert not reader.unproven


def test_timestamped_trade_works_without_optional_send_timestamp() -> None:
    raw = print_frame()
    del raw["sending_ts_ms"]
    _, (up, down) = state().apply(raw, START + 1.4)
    assert up.at == down.at == START + 1.2
    assert up.received_at == down.received_at == START + 1.4


def test_missing_all_delta_timestamps_revokes_book_without_receiver_stamping() -> None:
    reader = state()
    raw = delta()
    del raw["sending_ts_ms"], raw["msg"]["ts_ms"]
    assert reader.apply(raw, START + 1.1) == ((), ())
    assert not reader.book_at and not reader.exchange_at and reader.unproven == {TICKER}


def test_stale_source_delta_cannot_hide_behind_missing_optional_send_timestamp() -> None:
    raw = delta()
    del raw["sending_ts_ms"]
    raw["msg"]["ts_ms"] = int((START - 5) * 1000)
    with pytest.raises(MarketDataGap, match="timestamp_missing_or_stale"):
        state().apply(raw, START + 1.1)


def test_snapshot_publication_and_delta_engine_clocks_never_create_false_reversal_or_ioc_proof() -> None:
    reader = state(with_snapshot=False)
    # A hypothetical IOC becomes eligible at .250. Publication after .250
    # does not prove that a snapshot was captured or a change occurred then.
    assert reader.apply(snapshot(at=START + 1.3), START + 1.31) == ((), ())
    change = delta(at=START + 1.2)
    change["sending_ts_ms"] = int((START + 1.4) * 1000)
    (up, down), _ = reader.apply(change, START + 1.41)
    assert up.exchange_at == down.exchange_at == START + 1.2
    assert up.exchange_at < START + 1.25  # Remains ineligible for this IOC.
    assert up.at > START + 1.25
    later = delta(seq=4, at=START + 1.5)
    later["msg"]["delta_fp"] = "1.25"
    (up, _), _ = reader.apply(later, START + 1.51)
    assert up.exchange_at == START + 1.5


def test_delta_publication_without_engine_timestamp_is_not_liquidity_confirmation() -> None:
    reader = state()
    change = delta()
    del change["msg"]["ts_ms"]
    assert reader.apply(change, START + 1.1) == ((), ())
    assert not reader.book_at and not reader.exchange_at and reader.unproven == {TICKER}


def test_incremental_depth_matches_complete_rebuild_on_every_insert_change_and_delete() -> None:
    reader = state()
    expected = {"yes": {0.4: 2.5, 0.39: 3.0}, "no": {0.59: 4.0, 0.58: 5.0}}
    randomizer = random.Random(1042)
    for sequence in range(3, 503):
        side = randomizer.choice(("yes", "no"))
        price = round(0.1 + 0.01 * randomizer.randrange(29), 2)
        old = expected[side].get(price, 0.0)
        change = -old if old and randomizer.random() < 0.4 else 0.25
        new = round(old + change, 2)
        if new:
            expected[side][price] = new
        else:
            expected[side].pop(price, None)
        frame = delta(seq=sequence, at=START + 1.2)
        frame["msg"].update(side=side, price_dollars=str(price if side == "yes" else round(1 - price, 8)),
                            delta_fp=str(change))
        (up, down), _ = reader.apply(frame, START + 1.2)
        yes = tuple(Level(p, q) for p, q in sorted(expected["yes"].items(), reverse=True))
        no = tuple(Level(p, q) for p, q in sorted(expected["no"].items(), reverse=True))
        assert up.bids == yes and down.bids == no
        assert up.asks == tuple(Level(round(1 - level.price, 8), level.size) for level in no)
        assert down.asks == tuple(Level(round(1 - level.price, 8), level.size) for level in yes)
        assert up.sequence == down.sequence == f"kalshi-ws:7:{sequence}"


def test_cached_levels_do_not_mutate_previously_published_books() -> None:
    reader = state()
    (before_up, before_down), _ = reader.apply(delta(), START + 1.1)
    (after_up, after_down), _ = reader.apply(delta(seq=4, at=START + 1.2), START + 1.2)
    assert before_up.asks[0].size == before_down.bids[0].size == 2.75
    assert after_up.asks[0].size == after_down.bids[0].size == 1.5
    assert before_up.bids is after_up.bids and before_down.asks is after_down.asks


def test_staleness_and_disconnect_revoke_per_window_permission_without_heartbeat_refresh() -> None:
    clock, statuses = FakeClock(START + 1.2), []
    config, _ = settings()
    ws = KalshiMarketWS(config, tickers=lambda: frozenset((TICKER, NEXT)), on_book=lambda _: None,
                       on_trade=lambda _: None, on_status=statuses.append, clock=clock.now)
    ws.connected, ws.state = True, state()
    ws.state.apply(print_frame(), clock.now())
    ws._report()
    assert statuses[-1]["ws_maker_windows"] == [TICKER]
    assert NEXT not in ws.fresh_books()
    clock.advance(3)
    ws._report()
    assert statuses[-1]["gap_windows"] == [TICKER]
    assert not statuses[-1]["ws_books"] and not statuses[-1]["ws_maker_windows"]


class FakeSocket:
    def __init__(self, frames: list[dict[str, Any]], stop: threading.Event, statuses: list[dict[str, Any]],
                 *, stop_on_close: bool = True) -> None:
        self.frames = deque(frames)
        self.sent: list[dict[str, Any]] = []
        self.stop, self.statuses = stop, statuses
        self.closed = False
        self.stop_on_close = stop_on_close

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        assert self.statuses[-1]["ws_connected"] is False
        assert TICKER in self.statuses[-1]["gap_windows"]
        self.closed = True
        if self.stop_on_close:
            self.stop.set()

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self.frames:
            raise ConnectionError("fake connection lost")
        return json.dumps(self.frames.popleft())


def test_fake_connection_subscribes_only_market_channels_and_invalidates_before_close(monkeypatch) -> None:
    config, _ = settings()
    statuses: list[dict[str, Any]] = []
    stop, books, prints = threading.Event(), [], []
    socket = FakeSocket([ack(), ack("trade", 9), snapshot(), delta(), print_frame(), delta(seq=99)], stop, statuses)
    calls: list[tuple[str, dict[str, Any]]] = []

    def factory(url: str, **kwargs: Any) -> FakeSocket:
        calls.append((url, kwargs))
        return socket

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("An account/order client was accessed")

    monkeypatch.setattr(speeddesk_kalshi_client, "KalshiClient", forbidden)
    reader = KalshiMarketWS(config, tickers=lambda: frozenset((TICKER, NEXT)), on_book=books.append,
                           on_trade=prints.append, on_status=statuses.append, clock=lambda: START + 1.2,
                           ws_connect=factory)
    asyncio.run(reader.run(stop))
    assert calls[0][0] == URL
    assert calls[0][1]["max_queue"] == 16
    assert calls[0][1]["logger"].disabled  # Library DEBUG cannot leak auth headers.
    assert [item["params"]["channels"] for item in socket.sent] == [["orderbook_delta"], ["trade"]]
    assert socket.sent[0]["params"]["use_yes_price"] is True
    assert all(item["params"]["market_tickers"] == sorted((TICKER, NEXT)) for item in socket.sent)
    assert len(books) == len(prints) == 2
    assert socket.closed and not reader.state.depth


def test_reconnect_requires_new_snapshot_and_accepts_reset_subscription_sequences() -> None:
    config, _ = settings()
    stop, statuses, books = threading.Event(), [], []
    first = FakeSocket([ack(), snapshot(), delta(), delta(seq=99)], stop, statuses, stop_on_close=False)
    second = FakeSocket([ack(), ack("trade", 9), snapshot(), delta(), print_frame()], stop, statuses)
    sockets = deque((first, second))

    def factory(*args: Any, **kwargs: Any) -> FakeSocket:
        return sockets.popleft()

    reader = KalshiMarketWS(config, tickers=lambda: frozenset((TICKER,)), on_book=books.append,
                           on_trade=lambda _: None, on_status=statuses.append, clock=lambda: START + 1.2,
                           ws_connect=factory)
    asyncio.run(reader.run(stop))
    assert first.closed and second.closed and not sockets
    assert len(books) == 4
    assert any(item["gap_windows"] == [TICKER] for item in statuses)


def test_connection_without_optional_send_times_runs_on_fresh_delta_and_trade_times(caplog) -> None:
    config, _ = settings()
    stop, statuses, books, prints = threading.Event(), [], [], []
    initial, change, execution = snapshot(), delta(), print_frame()
    for frame in (initial, change, execution):
        del frame["sending_ts_ms"]
    socket = FakeSocket([ack(), ack("trade", 9), initial, change, execution], stop, statuses)
    reader = KalshiMarketWS(config, tickers=lambda: frozenset((TICKER,)), on_book=books.append,
                           on_trade=prints.append, on_status=statuses.append, clock=lambda: START + 1.2,
                           ws_connect=lambda *args, **kwargs: socket)
    with caplog.at_level("INFO", logger="nightcrawler.speeddesk_kalshi_ws"):
        asyncio.run(reader.run(stop))
    assert len(books) == len(prints) == 2  # Snapshot did not itself claim freshness.
    assert all(row.exchange_at == START + 1.1 for row in books)
    assert any(row["ws_maker_windows"] == [TICKER] for row in statuses)
    assert sum("missing_book_source_timestamp" in row.message for row in caplog.records) == 1


def adapter(config: Settings, clock: FakeClock, get: Any, **callbacks: Any) -> KalshiFeeds:
    return KalshiFeeds(config, clock=clock.now, rest_get=get,
                       on_tick=lambda *_: None, on_book=callbacks.get("on_book", lambda _: None),
                       on_trade=callbacks.get("on_trade", lambda _: None),
                       on_windows=lambda _: None, on_status=callbacks.get("on_status", lambda _: None))


@pytest.mark.parametrize("mode", ["no_keys", "disabled"])
def test_no_key_or_disabled_websocket_keeps_public_rest_working(mode: str) -> None:
    config = Settings() if mode == "no_keys" else replace(settings()[0], speeddesk_kalshi_ws_enabled=False)
    clock, calls = FakeClock(START + 1), []

    def get(path: str) -> Any:
        calls.append(path)
        return book()

    feed = adapter(config, clock, get)
    window = parse_window(market(), SERIES, clock.now())
    assert window is not None
    feed.windows[TICKER] = window
    assert feed._ws is None
    assert asyncio.run(feed.poll_book())
    assert calls == [f"/markets/{TICKER}/orderbook"]


def test_rest_fallback_keeps_two_hz_limit_and_matching_prices_still_reset_queue() -> None:
    config, _ = settings()
    clock, events, calls = FakeClock(START + 1.2), [], []

    def get(path: str) -> Any:
        calls.append(path)
        return book()

    feed = adapter(config, clock, get, on_book=lambda value: events.append(("book", value)),
                   on_status=lambda value: events.append(("status", value)))
    window = parse_window(market(), SERIES, clock.now())
    assert window is not None and feed._ws is not None
    feed.windows[TICKER] = window
    feed._ws.connected, feed._ws.state = True, state()
    (up, down), _ = state().apply(delta(), START + 1.1)
    feed._ws_book(up)
    feed._ws_book(down)
    assert not asyncio.run(feed.poll_book())  # Fresh WS suppresses REST entirely.
    clock.advance(3)
    assert asyncio.run(feed.poll_book())
    clock.advance(0.49)
    assert not asyncio.run(feed.poll_book())
    clock.advance(0.01)
    assert asyncio.run(feed.poll_book())
    assert len(calls) == 2
    gap = next(index for index, item in enumerate(events) if item[0] == "status" and item[1]["gap_windows"])
    assert events[gap + 1][0] == "book" and events[gap + 1][1].source == "rest"
    assert events[gap + 1][1].requested_at == START + 4.2


def test_composite_explicit_gap_before_first_trade_and_per_window_permission(monkeypatch) -> None:
    feeds, statuses = make(monkeypatch)
    us, kalshi = feeds.adapters["polymarket_us"], feeds.adapters["kalshi"]
    us.windows["us"] = Window("us", 0, 900)
    kalshi.windows[TICKER], kalshi.windows[NEXT] = Window(TICKER, 0, 900), Window(NEXT, 900, 1800)
    us.callbacks["on_status"]({"coinbase": "connected", "trade_stream": True})
    kalshi.callbacks["on_status"]({"trade_stream": False, "gap_windows": [TICKER]})
    assert statuses[-1]["gap_windows"] == [TICKER]
    assert statuses[-1]["trade_stream"]
    kalshi.callbacks["on_status"]({"trade_stream": True, "maker_windows": [TICKER]})
    assert feeds.maker_windows() == {"us", TICKER}


def test_inflight_rest_response_cannot_overwrite_newer_websocket_snapshot() -> None:
    config, _ = settings()
    clock, received = FakeClock(START + 1), []

    def get(path: str) -> Any:
        assert feed._ws is not None
        clock.advance(0.2)
        feed._ws.connected = True
        feed._ws.state = state(with_snapshot=False)
        feed._ws.state.apply(snapshot(at=clock.now()), clock.now())
        fresh, _ = feed._ws.state.apply(delta(at=clock.now()), clock.now())
        for item in fresh:
            feed._ws_book(item)
        return book()

    feed = adapter(config, clock, get, on_book=received.append)
    window = parse_window(market(), SERIES, clock.now())
    assert window is not None
    feed.windows[TICKER] = window
    assert asyncio.run(feed.poll_book())
    assert len(received) == 2 and all(item.source == "websocket" for item in received)


def test_inflight_rest_cannot_restore_book_after_metadata_invalidation() -> None:
    clock, received = FakeClock(START + 1), []

    def get(path: str) -> Any:
        feed.windows.clear()
        return book()

    feed = adapter(Settings(), clock, get, on_book=received.append)
    window = parse_window(market(), SERIES, clock.now())
    assert window is not None
    feed.windows[TICKER] = window
    assert asyncio.run(feed.poll_book())
    assert received == []


def test_a_few_milliseconds_of_clock_difference_neither_drops_the_book_nor_dates_it_in_the_future() -> None:
    # From Virginia, Kalshi is about a millisecond away, so its send and engine
    # times often read 0-7 ms ahead of our clock (seen 2026-10-12 23:50 UTC).
    reader = state()
    ahead = START + 1.1 + .007
    books, _ = reader.apply(delta(seq=3, at=ahead), START + 1.1)
    assert books and all(book.exchange_at == START + 1.1 for book in books)
    _, prints = reader.apply(print_frame(at=START + 1.2 + .005), START + 1.2)
    assert prints and all(print_.at == START + 1.2 for print_ in prints)
    with pytest.raises(MarketDataGap):
        reader.apply(delta(seq=4, at=START + 1.3 + .5), START + 1.3)

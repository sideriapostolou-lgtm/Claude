"""Public BTC readers and causal research features: no keys or trading client."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Self

import pytest

from nightcrawler.skipwatch_bitcoin import (
    GEMINI,
    KRAKEN,
    SOURCES,
    BitcoinFeedError,
    BitcoinObservations,
    PublicBitcoinFeeds,
    gemini_ticks,
    kraken_ticks,
)
from nightcrawler.skipwatch_feeds import SkipwatchFeeds
from nightcrawler.skipwatch_model import SkipwatchModel

NOW = 1_791_840_000.0


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z")


def kraken(identity: int = 10, **changes: Any) -> dict[str, Any]:
    return {"channel": "trade", "type": "update", "data": [
        {"symbol": "BTC/USD", "side": "buy", "price": 60_000, "qty": .001,
         "trade_id": identity, "timestamp": iso(NOW - .01), **changes}]}


def gemini(identity: int = 50, **changes: Any) -> dict[str, Any]:
    return {"E": int(NOW * 1e9) - 1_000_000, "s": "btcusd", "t": identity,
            "p": "60001.12000", "q": "0.00003000", "m": False, **changes}


def feeds() -> tuple[PublicBitcoinFeeds, list[Any]]:
    events: list[Any] = []
    return PublicBitcoinFeeds(on_event=lambda *event: events.append(event), receipt_clock_id="process-1",
                              clock=lambda: NOW, monotonic_ns=lambda: 100), events


def tick(source: str = "coinbase", at: float = NOW, **changes: Any) -> dict[str, Any]:
    return {"source": source, "symbol": "BTC-USD", "base": "BTC", "quote": "USD",
            "price": 60_000, "quantity": .001, "trade_id": f"id-{at}",
            "exchange_at": at - .01, "received_at": at, "received_monotonic_ns": int(at * 1e9),
            "receipt_clock_id": "process-1", "connection_generation": 1,
            "snapshot": False, "continuity_valid": True, **changes}


def observations() -> BitcoinObservations:
    model = BitcoinObservations()
    model.ingest("bitcoin_feature_epoch", {"version": 1}, NOW - 40)
    for source in SOURCES:
        model.ingest("bitcoin_exchange_health", {"source": source, "status": "connected"}, NOW - 40)
    return model


def test_kraken_batch_preserves_every_actual_trade_and_source_clocks() -> None:
    frame = kraken()
    frame["data"].append(kraken(11, side="sell", qty=.02)["data"][0])
    result = kraken_ticks(frame, NOW, 12345, "clock-id", 2)
    assert [row["trade_id"] for row in result] == ["10", "11"]
    assert [row["quantity"] for row in result] == [.001, .02]
    assert result[1]["aggressor"] == "sell"
    assert result[0]["exchange_timestamp_raw"] == iso(NOW - .01)
    assert result[0]["received_monotonic_ns"] == 12345
    assert result[0]["exchange_at"] != result[0]["received_at"]
    assert result[0]["receipt_clock_id"] == "clock-id"
    assert result[0]["connection_generation"] == 2


@pytest.mark.parametrize("changes", [
    {"symbol": "BTC/USDT"}, {"trade_id": None}, {"trade_id": True}, {"timestamp": "bad"},
    {"price": "NaN"}, {"qty": 0}, {"side": "unknown"},
])
def test_kraken_rejects_unverified_symbols_ids_times_and_amounts(changes: Any) -> None:
    with pytest.raises(BitcoinFeedError):
        kraken_ticks(kraken(**changes), NOW, 100, "clock-id", 1)


def test_kraken_historical_snapshot_is_never_prospective() -> None:
    frame = {**kraken(), "type": "snapshot"}
    with pytest.raises(BitcoinFeedError, match="historical_snapshot"):
        kraken_ticks(frame, NOW, 100, "clock-id", 1)


def test_kraken_identity_jump_is_explicit_gap_and_genuine_print_retained() -> None:
    feed, events = feeds()
    feed.message("kraken", kraken(10), NOW, 100)
    feed.message("kraken", kraken(10), NOW, 100)  # Duplicate identity, not another print.
    with pytest.raises(BitcoinFeedError, match="trade_id_discontinuity"):
        feed.message("kraken", kraken(12), NOW, 101)
    rows = [payload for kind, payload, _ in events if kind == "bitcoin_exchange_tick"]
    assert [row["trade_id"] for row in rows] == ["10", "12"]
    assert rows[-1]["continuity_valid"] is False
    assert any(payload["reason"] == "trade_id_discontinuity" for kind, payload, _ in events
               if kind == "bitcoin_exchange_health")


def test_gemini_real_ids_need_not_be_contiguous_and_raw_nanoseconds_survive() -> None:
    feed, events = feeds()
    exact_ns = int(NOW * 1e9) + 123456789
    feed.message("gemini", gemini(50, E=exact_ns), NOW + .2, 101)
    feed.message("gemini", gemini(57, m=True), NOW + .2, 102)
    rows = [payload for kind, payload, _ in events if kind == "bitcoin_exchange_tick"]
    assert len(rows) == 2 and rows[0]["exchange_timestamp_raw"] == str(exact_ns)
    assert rows[0]["sequence_available"] is False and rows[0]["sequence"] is None
    assert rows[0]["aggressor"] == "buy" and rows[1]["aggressor"] == "sell"
    assert all(row["continuity_valid"] for row in rows)


@pytest.mark.parametrize("changes", [
    {"s": "btcusdt"}, {"E": None}, {"t": False}, {"p": "inf"}, {"q": "0"}, {"m": "false"},
])
def test_gemini_rejects_unverified_trade_frames(changes: Any) -> None:
    with pytest.raises(BitcoinFeedError):
        gemini_ticks(gemini(**changes), NOW, 100, "clock-id", 1)


def test_acknowledgements_and_heartbeats_never_invent_ticks() -> None:
    feed, events = feeds()
    feed.message("kraken", {"channel": "status", "data": [{"system": "online"}]}, NOW, 100)
    feed.message("kraken", {"method": "subscribe", "success": True, "req_id": 1,
                            "result": {"channel": "trade", "symbol": "BTC/USD", "snapshot": False}}, NOW, 101)
    feed.message("kraken", {"channel": "heartbeat"}, NOW, 102)
    feed.message("gemini", {"id": 1, "status": 200}, NOW, 103)
    assert not any(kind == "bitcoin_exchange_tick" for kind, _, _ in events)
    assert all(payload["status"] == "subscribed" for _, payload, _ in events)
    with pytest.raises(BitcoinFeedError, match="exchange_not_online"):
        feed.message("kraken", {"channel": "status", "data": [{"system": "maintenance"}]}, NOW, 104)
    with pytest.raises(BitcoinFeedError, match="subscription_rejected"):
        feed.message("gemini", {"id": 1, "status": 401}, NOW, 105)


def test_both_anonymous_readers_send_only_exact_public_subscription() -> None:
    async def exercise() -> None:
        events: list[Any] = []
        connections: list[Any] = []

        class Socket:
            def __init__(self, source: str) -> None:
                self.frame = kraken() if source == "kraken" else gemini()
                self.sent: list[Any] = []

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

            async def send(self, raw: str) -> None:
                self.sent.append(json.loads(raw))

            async def recv(self) -> str:
                if self.frame:
                    frame, self.frame = self.frame, {}
                    return json.dumps(frame)
                await asyncio.Future()
                raise AssertionError("Unreachable")

        def connector(source: str) -> Any:
            def connect(url: str, **kwargs: Any) -> Socket:
                assert "additional_headers" not in kwargs and "Authorization" not in str(kwargs)
                socket = Socket(source)
                connections.append((url, socket))
                return socket
            return connect

        feed = PublicBitcoinFeeds(on_event=lambda *event: events.append(event), receipt_clock_id="test",
                                  clock=lambda: NOW, monotonic_ns=lambda: 100,
                                  connectors={source: connector(source) for source in ("kraken", "gemini")})
        task = asyncio.create_task(feed.run())
        for _ in range(20):
            if len([event for event in events if event[0] == "bitcoin_exchange_tick"]) == 2:
                break
            await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert {url for url, _ in connections} == {KRAKEN, GEMINI}
        assert connections[0][1].sent == [{"method": "subscribe", "params": {
            "channel": "trade", "symbol": ["BTC/USD"], "snapshot": False}, "req_id": 1}]
        assert connections[1][1].sent == [{"id": 1, "method": "subscribe", "params": ["btcusd@trade"]}]
        assert len([event for event in events if event[0] == "bitcoin_exchange_tick"]) == 2
        assert len([event for event in events if event[1].get("status") == "stopped"]) == 2

    asyncio.run(exercise())


def test_restricted_endpoint_records_block_and_never_retries_or_bypasses() -> None:
    async def exercise() -> None:
        calls: list[str] = []
        events: list[Any] = []

        class Blocked(Exception):
            response = SimpleNamespace(status_code=451)

        def connector(url: str, **kwargs: Any) -> Any:
            calls.append(url)
            raise Blocked()

        feed = PublicBitcoinFeeds(on_event=lambda *event: events.append(event), receipt_clock_id="test",
                                  connectors={"gemini": connector})
        task = asyncio.create_task(feed._source("gemini"))
        await asyncio.sleep(.01)
        assert calls == [GEMINI]
        assert events[-1][1]["status"] == "blocked"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())


@pytest.mark.parametrize("retry", ["37", iso(NOW + 40)])
def test_rate_limits_respect_retry_after_without_immediate_reconnect(monkeypatch: Any, retry: str) -> None:
    from email.utils import format_datetime

    import nightcrawler.skipwatch_bitcoin as module

    if retry != "37":
        retry = format_datetime(datetime.fromtimestamp(NOW + 40, UTC), usegmt=True)
    delays: list[float] = []

    class Limited(Exception):
        response = SimpleNamespace(status_code=429, headers={"Retry-After": retry})

    def connector(url: str, **kwargs: Any) -> Any:
        raise Limited()

    async def sleep(delay: float) -> None:
        delays.append(delay)
        raise asyncio.CancelledError()

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    feed = PublicBitcoinFeeds(on_event=lambda *_: None, receipt_clock_id="test", clock=lambda: NOW,
                              connectors={"kraken": connector})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(feed._source("kraken"))
    assert delays == [37 if retry == "37" else 40]


def test_transport_ping_confirms_liveness_without_fake_trade(monkeypatch: Any) -> None:
    import nightcrawler.skipwatch_bitcoin as module

    events: list[Any] = []
    waits = 0
    pings = 0

    class Socket:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def send(self, raw: str) -> None:
            pass

        async def recv(self) -> str:
            raise AssertionError("Fake wait_for handles this coroutine")

        async def ping(self) -> Any:
            nonlocal pings
            pings += 1
            return asyncio.get_running_loop().create_future()

    async def wait_for(awaitable: Any, timeout: float) -> Any:
        nonlocal waits
        waits += 1
        if hasattr(awaitable, "close"):
            awaitable.close()
        if waits == 1:
            raise TimeoutError()
        if waits == 2:
            awaitable.cancel()
            return None
        raise asyncio.CancelledError()

    monkeypatch.setattr(module.asyncio, "wait_for", wait_for)
    feed = PublicBitcoinFeeds(on_event=lambda *event: events.append(event), receipt_clock_id="test",
                              connectors={"gemini": lambda *args, **kwargs: Socket()})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(feed._source("gemini"))
    assert pings == 1 and not any(event[0] == "bitcoin_exchange_tick" for event in events)
    assert events[-1][1]["status"] == "subscribed"


def test_causal_receipt_features_do_not_see_future_ticks_or_future_health() -> None:
    model = observations()
    for at, price in ((NOW - 31, 60_000), (NOW - 6, 60_100), (NOW - 2, 60_200), (NOW, 60_300), (NOW + 1, 99_999)):
        model.ingest("bitcoin_tick", tick(at=at, price=price), at)
    model.ingest("bitcoin_exchange_health", {"source": "coinbase", "status": "gap"}, NOW + 1)
    feature = model.features(NOW)["coinbase"]
    assert feature["price"] == 60_300 and feature["fresh"] is True
    assert feature["received_at"] <= NOW and feature["move_30s"] is not None
    assert feature["move_1s"] > 0 and feature["move_5s"] > 0
    assert model.features(NOW + 1)["coinbase"]["fresh"] is False
    assert model.features(NOW - 41)["coinbase"]["price"] is None


def test_dispatch_delay_never_replaces_receipt_or_hides_future_source_time() -> None:
    model = observations()
    model.ingest("bitcoin_tick", tick(exchange_at=NOW + .1), NOW + .2)
    before_dispatch = model.features(NOW + .15)["coinbase"]
    assert before_dispatch["price"] is None
    feature = model.features(NOW + .2)["coinbase"]
    assert feature["received_at"] == NOW and feature["observed_at"] == NOW + .2
    assert feature["fresh"] is False
    assert feature["apparent_source_age_ms"] == pytest.approx(-100, abs=.001)
    assert feature["receipt_age_ms"] == pytest.approx(200, abs=.001)


def test_dispatch_jitter_does_not_masquerade_as_receipt_clock_step() -> None:
    model = observations()
    model.ingest("bitcoin_tick", tick(at=NOW - 1), NOW - .9)
    model.ingest("bitcoin_tick", tick(), NOW + .5)
    assert model.features(NOW + .5)["coinbase"]["fresh"] is True
    assert model.features(NOW + .5)["coinbase"]["move_1s"] is not None


def test_out_of_order_source_clock_is_visible_and_not_eligible() -> None:
    model = observations()
    model.ingest("bitcoin_tick", tick(at=NOW - 1), NOW - 1)
    model.ingest("bitcoin_tick", tick(exchange_at=NOW - 1.1), NOW)
    assert model.features(NOW)["coinbase"]["price"] == 60_000
    assert model.features(NOW)["coinbase"]["fresh"] is False
    assert model.features(NOW)["coinbase"]["move_1s"] is None


def test_return_cannot_bridge_intermediate_future_clock_trade_even_after_health_recovers() -> None:
    model = observations()
    model.ingest("bitcoin_tick", tick(at=NOW - 6), NOW - 6)
    model.ingest("bitcoin_tick", tick(at=NOW - 3, exchange_at=NOW - 2.9), NOW - 3)
    model.ingest("health", {"source": "coinbase", "status": "connected"}, NOW - 1)
    model.ingest("bitcoin_tick", tick(), NOW)
    feature = model.features(NOW)["coinbase"]
    assert feature["fresh"] is True
    assert feature["move_5s"] is None


@pytest.mark.parametrize("changes", [
    {"snapshot": True}, {"trade_id": None}, {"quote": "USDT"}, {"quantity": None},
    {"exchange_at": NOW - 3.01}, {"exchange_at": NOW + .001},
    {"continuity_valid": False}, {"received_monotonic_ns": None}, {"receipt_clock_id": None},
])
def test_missing_or_unverified_coverage_is_not_fresh(changes: Any) -> None:
    model = observations()
    model.ingest("bitcoin_tick", tick(**changes), NOW)
    assert model.features(NOW)["coinbase"]["fresh"] is False
    assert model.features(NOW)["coinbase"]["move_1s"] is None


@pytest.mark.parametrize("boundary", ["gap", "reconnect", "new_process", "clock_jump"])
def test_return_features_never_bridge_gaps_restarts_or_clock_jumps(boundary: str) -> None:
    model = observations()
    model.ingest("bitcoin_tick", tick(at=NOW - 2), NOW - 2)
    changes: dict[str, Any] = {"price": 60_100}
    if boundary == "gap":
        model.ingest("gap", {"reason": "restart"}, NOW - 1)
        model.ingest("health", {"source": "coinbase", "status": "connected"}, NOW - .5)
    elif boundary == "reconnect":
        changes["connection_generation"] = 2
    elif boundary == "new_process":
        changes["receipt_clock_id"] = "new-process"
    else:
        changes["received_monotonic_ns"] = int((NOW - 1) * 1e9)
    model.ingest("bitcoin_tick", tick(**changes), NOW)
    feature = model.features(NOW)["coinbase"]
    assert feature["move_1s"] is None
    if boundary == "clock_jump":
        assert feature["fresh"] is False


@pytest.mark.parametrize("source", ["clob", "wallet", "gamma", "clob_book"])
def test_unrelated_public_source_gaps_do_not_disconnect_bitcoin_sources(source: str) -> None:
    model = observations()
    for venue in SOURCES:
        model.ingest("bitcoin_exchange_tick", tick(venue, at=NOW - 1), NOW - 1)
    model.ingest("gap", {"source": source, "reason": "unrelated_gap"}, NOW - .5)
    assert all(row["fresh"] for row in model.features(NOW).values())


@pytest.mark.parametrize("source", ["runtime", "storage", "clock", "kraken"])
def test_runtime_gaps_invalidate_every_source_but_venue_gaps_only_one(source: str) -> None:
    model = observations()
    for venue in SOURCES:
        model.ingest("bitcoin_exchange_tick", tick(venue, at=NOW - 1), NOW - 1)
    model.ingest("gap", {"source": source, "reason": "test_gap"}, NOW - .5)
    features = model.features(NOW)
    assert features["kraken"]["fresh"] is False
    if source == "kraken":
        assert features["coinbase"]["fresh"] is True and features["gemini"]["fresh"] is True
    else:
        assert not any(row["fresh"] for row in features.values())


def test_old_journals_new_epoch_replay_and_financial_tape_separation() -> None:
    model = SkipwatchModel(NOW - 500)
    model.ingest("bitcoin_tick", {"price": 60_000, "exchange_at": NOW - 20}, NOW - 20)
    assert model.bitcoin_summary(NOW)["feature_epoch_started_at"] is None
    assert not any(row["fresh"] for row in model.features("window", "up", NOW)["bitcoin_venues"].values())
    model.ingest("bitcoin_feature_epoch", {"version": 1}, NOW - 10)
    model.ingest("bitcoin_feature_epoch", {"version": 1}, NOW)
    model.ingest("bitcoin_exchange_health", {"source": "gemini", "status": "connected"}, NOW - 1)
    model.ingest("bitcoin_exchange_tick", tick("gemini", price=99_999), NOW)
    assert model.features("window", "up", NOW)["btc_price"] == 60_000
    assert model.features("window", "up", NOW)["bitcoin_venues"]["gemini"]["price"] == 99_999
    assert model.bitcoin_summary(NOW)["feature_epoch_started_at"] == NOW - 10
    assert model.started_at == NOW - 500
    assert model.bitcoin_summary(NOW)["leadership_status"] == "not_established"


def test_bounded_diagnostics_count_genuine_distinct_receipts_and_do_not_claim_full_day() -> None:
    model = observations()
    model.ingest("bitcoin_tick", tick(), NOW)
    model.ingest("bitcoin_tick", tick(), NOW + 1)  # Replayed exchange identity.
    model.ingest("bitcoin_tick", tick(trade_id="snapshot", snapshot=True), NOW + 1)
    summary = model.summary(NOW)
    day = datetime.fromtimestamp(NOW, UTC).date().isoformat()
    assert summary["daily_observed_ticks"][day]["coinbase"] == 1
    assert summary["daily_counts_are_partial"] is True
    assert summary["venues"]["coinbase"]["age_samples"] == 1
    assert model.summary(NOW + 121)["venues"]["coinbase"]["age_samples"] == 0
    assert model.summary(NOW + 121)["venues"]["coinbase"]["fresh"] is False


def test_coinbase_existing_event_gains_actual_identity_and_unchanged_receipt_clocks() -> None:
    events: list[Any] = []
    feed = SkipwatchFeeds(on_event=lambda *event: events.append(event), clock=lambda: NOW)
    feed.coinbase_message({"channel": "market_trades", "sequence_num": 0, "events": [
        {"type": "update", "trades": [{"product_id": "BTC-USD", "trade_id": "real-99",
         "size": "0.01", "price": "60000", "time": iso(NOW - .01)}]}]}, NOW, 123456)
    row = events[0][1]
    assert row["trade_id"] == "real-99" and row["quantity"] == .01
    assert row["received_monotonic_ns"] == 123456 and row["received_at"] == NOW
    assert row["exchange_at"] == NOW - .01 and events[0][0] == "bitcoin_tick"
    assert row["receipt_clock_id"] == feed.bitcoin_feeds.clock_id


def test_skipwatch_run_launches_public_readers_and_records_actual_feature_epoch(monkeypatch: Any) -> None:
    import threading

    async def exercise() -> None:
        events: list[Any] = []
        started: list[str] = []
        stop = threading.Event()
        feed = SkipwatchFeeds(on_event=lambda *event: events.append(event), clock=lambda: NOW)

        async def dormant() -> None:
            await asyncio.Future()

        async def bitcoin() -> None:
            started.append("bitcoin")
            stop.set()
            await asyncio.Future()

        for name in ("_wallet_loop", "_discovery_loop", "_clob_loop", "_coinbase_loop"):
            monkeypatch.setattr(feed, name, dormant)
        monkeypatch.setattr(feed.bitcoin_feeds, "run", bitcoin)
        await feed.run(stop)
        epochs = [event for event in events if event[0] == "bitcoin_feature_epoch"]
        assert len(epochs) == 1 and epochs[0][2] == NOW and started == ["bitcoin"]
        assert epochs[0][1]["sources"] == list(SOURCES)

    asyncio.run(exercise())

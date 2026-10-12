"""Public observer contracts use fake transports and never account credentials."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import nightcrawler.skipwatch_feeds as module
from nightcrawler.clock import FakeClock
from nightcrawler.skipwatch_feeds import (
    CLOB_WS,
    COINBASE_WS,
    DATA,
    WALLET,
    SkipwatchFeeds,
    parse_market,
    parse_wallet_fill,
)

START = 1_791_836_400
SLUG = f"btc-updown-5m-{START}"


def market(**changes: Any) -> dict[str, Any]:
    return {"slug": SLUG, "conditionId": "condition-1",
            "eventStartTime": datetime.fromtimestamp(START, UTC).isoformat(),
            "endDate": datetime.fromtimestamp(START + 300, UTC).isoformat(),
            "startDate": "2026-10-11T20:28:27Z", "outcomes": '["Up","Down"]',
            "clobTokenIds": '["up-token","down-token"]', "active": True, "closed": False,
            "acceptingOrders": True, "orderPriceMinTickSize": 0.01, "orderMinSize": 5,
            "description": "Chainlink BTC/USD TWAP60s; greater than or equal resolves Up.",
            "resolutionSource": "https://data.chain.link/streams/btc-usd-twap-60s-streams",
            "feeSchedule": {"rate": 0.07, "exponent": 1, "takerOnly": True, "rebateRate": 0.2}, **changes}


def wallet(**changes: Any) -> dict[str, Any]:
    return {"proxy_wallet": WALLET, "condition_id": "condition-1", "token_id": "up-token",
            "side": "BUY", "outcome": "Up", "price": 0.4, "size": 10,
            "timestamp": START + 1, "slug": SLUG, "transaction_hash": "transaction-1", **changes}


def page(rows: list[Any], cursor: Any = None) -> dict[str, Any]:
    return {"data": rows, "pagination": {"next_cursor": cursor, "has_more": cursor is not None,
                                           "limit": 500, "offset": 0}}


class Get:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str) -> Any:
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("Unexpected public request")
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def feed(get: Any = None, *, start: float = START + 100, **kwargs: Any) -> tuple[SkipwatchFeeds, list[Any], FakeClock]:
    events: list[Any] = []
    clock = FakeClock(start)
    f = SkipwatchFeeds(on_event=lambda kind, payload, at: events.append((kind, payload, at)),
                      clock=clock.now, rest_get=get, **kwargs)
    f.markets = {"condition-1": parse_market(market(), SLUG)}
    f.tokens = {"up-token": ("condition-1", "up"), "down-token": ("condition-1", "down")}
    return f, events, clock


def book(token: str = "up-token", **changes: Any) -> dict[str, Any]:
    return {"event_type": "book", "market": "condition-1", "asset_id": token,
            "timestamp": str((START + 10) * 1000), "hash": "public-book-hash",
            "bids": [{"price": "0.4", "size": "8"}],
            "asks": [{"price": "0.6", "size": "7"}], **changes}


def delta(**changes: Any) -> dict[str, Any]:
    change = {"asset_id": "up-token", "side": "BUY", "price": "0.4", "size": "3",
              "hash": "next-hash", "best_bid": "0.4", "best_ask": "0.6", **changes}
    return {"event_type": "price_change", "market": "condition-1",
            "timestamp": str((START + 11) * 1000), "price_changes": [change]}


def test_gamma_uses_real_window_start_not_listing_date_and_preserves_rules() -> None:
    parsed = parse_market(market(), SLUG)
    assert parsed["start"] == START and parsed["end"] == START + 300
    assert parsed["up_token"] == "up-token" and parsed["down_token"] == "down-token"
    assert "Chainlink" in parsed["rules"] and "twap" in parsed["resolution_source"]
    assert parsed["coinbase_is_resolution_source"] is False
    assert parsed["fee_schedule"]["rate"] == 0.07


@pytest.mark.parametrize("changes", [
    {"eventStartTime": None}, {"endDate": "2026-10-12T20:26:00Z"},
    {"slug": "other"}, {"outcomes": '["Yes","No"]'},
    {"clobTokenIds": '["same","same"]'}, {"description": ""},
])
def test_unverified_market_metadata_is_rejected(changes: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_market(market(**changes), SLUG)


def test_wallet_rows_never_invent_maker_role_execution_ms_or_fee() -> None:
    row = parse_wallet_fill(wallet(price=0.7700000307, size=0.001))
    assert row["price"] == 0.7700000307 and row["size"] == 0.001
    assert row["maker_taker"] == "unknown" and row["timestamp_precision_s"] == 1
    assert "fee" not in row and row["action"] == "buy"
    assert row["transaction_hash"] == "transaction-1"


@pytest.mark.parametrize("changes", [
    {"proxy_wallet": "someone-else"}, {"side": "CANCEL"}, {"price": float("nan")},
    {"size": 0}, {"timestamp": START + 0.5}, {"transaction_hash": ""},
])
def test_invalid_wallet_data_is_not_silently_normalized(changes: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_wallet_fill(wallet(**changes))


def test_wallet_v2_maker_inclusion_pagination_duplicate_multiplicity_and_watermark() -> None:
    getter = Get(page([wallet(), wallet()], "next"), page([wallet(transaction_hash="transaction-2")]),
                 page([wallet(), wallet(), wallet(transaction_hash="transaction-2")]))
    f, events, _ = feed(getter)
    asyncio.run(f.poll_wallet())
    fills = [payload for kind, payload, _ in events if kind == "wallet_fill"]
    assert len(fills) == 3 and len({item["fill_id"] for item in fills}) == 3
    assert fills[0]["fill_id"].endswith(":1") and fills[1]["fill_id"].endswith(":2")
    for url in getter.urls:
        assert url.startswith(DATA + "?")
        query = parse_qs(urlsplit(url).query)
        assert query["taker_only"] == ["false"] and query["user"] == [WALLET]
        assert query["filter_type"] == ["TOKENS"] and query["filter_amount"] == ["1e-09"]
        assert query["limit"] == ["500"] and query["start"] == [str(START - 500)]
    assert parse_qs(urlsplit(getter.urls[1]).query)["cursor"] == ["next"]
    assert f.wallet_watermark == START + 100
    asyncio.run(f.poll_wallet())
    assert len([event for event in events if event[0] == "wallet_fill"]) == 3


@pytest.mark.parametrize("responses", [
    [page([wallet()], "next"), requests.Timeout("timeout")],
    [page([wallet()], "loop"), page([], "loop")],
    [{"data": [wallet()]}], [page([wallet(timestamp=START + 101)])],
])
def test_failed_or_invalid_pages_never_advance_watermark_or_emit_partial_fills(responses: Any) -> None:
    f, events, clock = feed(Get(*responses), wallet_since=START + 80)
    with pytest.raises((ValueError, requests.RequestException)):
        asyncio.run(f.poll_wallet())
    assert f.wallet_watermark == START + 80 and not any(kind == "wallet_fill" for kind, _, _ in events)
    assert clock.now() == START + 100


def test_wallet_resume_fetches_overlap_but_received_time_stays_new() -> None:
    getter = Get(page([wallet(timestamp=START - 100)]))
    f, events, clock = feed(getter, wallet_since=START - 50)
    asyncio.run(f.poll_wallet())
    query = parse_qs(urlsplit(getter.urls[0]).query)
    assert query["start"] == [str(START - 650)]
    fill = next(event for event in events if event[0] == "wallet_fill")
    assert fill[2] == clock.now() and fill[1]["exchange_at"] < fill[2]


def test_late_enrichment_does_not_change_public_fill_identity() -> None:
    getter = Get(page([wallet(slug="", outcome="")]), page([wallet()]))
    f, events, _ = feed(getter)
    asyncio.run(f.poll_wallet())
    asyncio.run(f.poll_wallet())
    assert len([event for event in events if event[0] == "wallet_fill"]) == 1


def test_contradictory_pagination_never_claims_complete_poll() -> None:
    raw = page([wallet()])
    raw["pagination"]["has_more"] = True
    f, events, _ = feed(Get(raw))
    with pytest.raises(ValueError, match="Contradictory"):
        asyncio.run(f.poll_wallet())
    assert not any(kind == "wallet_fill" for kind, _, _ in events)


def test_page_bound_is_explicit_gap_not_silent_truncation(monkeypatch: Any) -> None:
    monkeypatch.setattr(module, "MAX_PAGES", 2)
    f, events, _ = feed(Get(page([wallet()], "one"), page([], "two")), wallet_since=START + 80)
    with pytest.raises(ValueError, match="pagination incomplete"):
        asyncio.run(f.poll_wallet())
    assert f.wallet_watermark == START + 80
    assert not any(kind == "wallet_fill" for kind, _, _ in events)


def test_construction_never_accesses_any_credential_setting() -> None:
    class PublicSettings:
        skipwatch_poll_s = 2.5

        def __getattr__(self, name: str) -> Any:
            raise AssertionError("Observer must not access credential or account settings")

    observer = SkipwatchFeeds(PublicSettings(), on_event=lambda *args: None, rest_get=Get())
    assert observer.poll_s == 2.5


def test_discovery_subscribes_only_current_and_next_outcome_tokens() -> None:
    next_slug = f"btc-updown-5m-{START + 300}"
    next_market = market(slug=next_slug, conditionId="condition-2", clobTokenIds='["next-up","next-down"]',
                         eventStartTime=datetime.fromtimestamp(START + 300, UTC).isoformat(),
                         endDate=datetime.fromtimestamp(START + 600, UTC).isoformat())
    getter = Get(market(), next_market)
    f, _, _ = feed(getter)
    asyncio.run(f.discover())
    assert {url.rsplit("/", 1)[1] for url in getter.urls} == {SLUG, next_slug}
    assert set(f.tokens) == {"up-token", "down-token", "next-up", "next-down"}


def test_clob_snapshot_then_delta_replaces_quantity_and_delete_zero() -> None:
    f, events, _ = feed()
    f.clob_message([book(), book("down-token")])
    f.clob_message(delta())
    f.clob_message(delta(size="0", best_bid="0"))
    snapshots = [payload for kind, payload, _ in events if kind == "book_snapshot"]
    updates = [payload for kind, payload, _ in events if kind == "book_deltas"]
    assert snapshots[0]["bids"] == [[0.4, 8]]
    assert snapshots[0]["book_depth_complete"] is True
    assert updates[0]["updates"][0]["changes"][0]["size"] == 3  # Absolute size, not +3.
    assert updates[1]["updates"][0]["changes"][0]["size"] == 0
    assert f.books["up-token"]["bids"] == {}
    assert updates[0]["updates"][0]["changes"][0]["book_side"] == "bid"
    assert set(updates[0]["updates"][0]["changes"][0]) == {"book_side", "price", "size"}
    assert "bids" not in updates[0] and "bids" not in updates[0]["updates"][0]
    assert updates[0]["book_view"] == "deltas" and updates[0]["book_depth_complete"] is False
    assert updates[0]["sequence_available"] is False


def test_no_delta_can_create_book_before_snapshot_or_after_reconnect() -> None:
    f, events, _ = feed()
    f.clob_message(delta())
    assert not f.books
    assert next(payload for kind, payload, _ in events if kind == "book_deltas")["updates"][0]["valid"] is False
    f.clob_message(book())
    f.reset_books("disconnect")
    f.clob_message(delta())
    assert not f.books
    assert all(not payload["updates"][0]["valid"] for kind, payload, _ in events if kind == "book_deltas")
    assert any(kind == "health" and payload["status"] == "gap" for kind, payload, _ in events)


def test_changes_for_both_tokens_remain_one_complete_wire_frame() -> None:
    f, events, _ = feed()
    f.clob_message([book(), book("down-token")])
    raw = delta()
    raw["price_changes"].append({"asset_id": "down-token", "side": "SELL", "price": "0.6", "size": "2"})
    f.clob_message(raw)
    grouped = [payload for kind, payload, _ in events if kind == "book_deltas"]
    assert len(grouped) == 1 and len(grouped[0]["updates"]) == 2
    assert {row["token_id"] for row in grouped[0]["updates"]} == {"up-token", "down-token"}
    assert f.books["down-token"]["asks"] == {0.6: 2}


@pytest.mark.parametrize("bad", [
    book(market="different-market"), book(timestamp=str((START + 200) * 1000)),
    book(bids=[{"price": "0.8", "size": "2"}]),
    book(asks=[{"price": "0.6", "size": "2"}] * 1001),
    book(bids=[{"price": "0.3", "size": "2"}, {"price": "0.3", "size": "3"}]),
    delta(side="UNKNOWN"), delta(size="NaN"),
])
def test_invalid_clob_events_fail_visibly(bad: Any) -> None:
    f, _, _ = feed()
    with pytest.raises((ValueError, TypeError)):
        f.clob_message(bad)


def test_retrograde_delta_and_crossed_book_do_not_mutate_last_good_book() -> None:
    f, _, _ = feed()
    f.clob_message(book())
    retrograde = delta()
    retrograde["timestamp"] = str(START * 1000)
    with pytest.raises(ValueError):
        f.clob_message(retrograde)
    assert f.books["up-token"]["bids"] == {0.4: 8}


def test_redundant_bbo_is_checked_before_omitting_and_mismatch_reports_gap() -> None:
    f, events, _ = feed()
    f.clob_message(book())
    f.clob_message(delta(best_bid="0.5"))
    assert any(kind == "health" and data.get("reason") == "bbo_mismatch" for kind, data, _ in events)
    update = next(data for kind, data, _ in events if kind == "book_deltas")["updates"][0]
    assert update["valid"] is False and update["changes"][0]["best_bid"] == 0.5
    # A subsequent apparently consistent top of book does not prove lost depth.
    f.clob_message(delta())
    assert f.books["up-token"]["valid"] is False
    f.clob_message(book(timestamp=str((START + 12) * 1000)))
    assert f.books["up-token"]["valid"] is True


def test_transient_locked_delta_is_recorded_invalid_without_losing_connection() -> None:
    f, events, _ = feed()
    f.clob_message(book())
    f.clob_message(delta(price="0.6", best_bid="0.6", best_ask="0.7"))
    assert f.books["up-token"]["bids"][0.6] == 3
    assert f.books["up-token"]["valid"] is False
    assert any(kind == "book_deltas" for kind, _, _ in events)
    assert not any(kind == "health" and data["source"] == "clob" and data["status"] == "gap"
                   for kind, data, _ in events)


def test_public_trade_hash_stays_stable_across_reconnect_and_retains_transaction() -> None:
    f, events, _ = feed()
    trade = {"event_type": "last_trade_price", "market": "condition-1", "asset_id": "up-token",
             "price": "0.42", "size": "0.5", "side": "SELL", "timestamp": str((START + 11) * 1000),
             "transaction_hash": "public-transaction"}
    f.clob_message(trade)
    f.reset_books("reconnect")
    f.clob_message(trade)
    prints = [payload for kind, payload, _ in events if kind == "public_trade"]
    assert prints[0]["trade_id"] == prints[1]["trade_id"]
    assert prints[0]["transaction_hash"] == "public-transaction"
    assert prints[0]["identity_exact"] is False and prints[0]["aggressor"] == "sell"


def test_coinbase_sequence_is_global_across_heartbeats_and_subscriptions() -> None:
    f, events, clock = feed()
    for seq, channel in enumerate(("subscriptions", "heartbeats", "market_trades", "heartbeats")):
        message = {"channel": channel, "sequence_num": seq, "events": [{"trades": [
            {"product_id": "BTC-USD", "price": "64000", "time": datetime.fromtimestamp(START + 10, UTC).isoformat()}]}]}
        f.coinbase_message(message, clock.now())
    ticks = [payload for kind, payload, _ in events if kind == "bitcoin_tick"]
    assert len(ticks) == 1 and ticks[0]["sequence"] == 2
    with pytest.raises(ValueError, match="Coinbase sequence gap"):
        f.coinbase_message({"channel": "heartbeats", "sequence_num": 5}, clock.now())


@pytest.mark.parametrize("retry_after", ["600", "Mon, 12 Oct 2026 20:40:00 GMT"])
def test_public_429_respects_retry_after_without_cap_or_immediate_retry(retry_after: str) -> None:
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = retry_after
    error = requests.HTTPError(response=response)
    getter = Get(error)
    f, events, clock = feed(getter)
    with pytest.raises(requests.HTTPError):
        asyncio.run(f._request(DATA + "?limit=1"))
    assert len(getter.urls) == 1
    assert f._backoff_until["data-api.polymarket.com"] >= clock.now() + 600
    assert events[-1][1]["status"] == "rate_limited"


def test_only_fixed_public_rest_hosts_are_callable() -> None:
    f, _, _ = feed(Get())
    with pytest.raises(ValueError, match="Only public"):
        asyncio.run(f._request("https://api.elections.kalshi.com/trade-api/v2/portfolio/orders"))


class Socket:
    def __init__(self, messages: list[Any], stop: threading.Event | None = None) -> None:
        self.messages, self.sent, self.stop = list(messages), [], stop

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if self.messages:
            return json.dumps(self.messages.pop(0))
        if self.stop:
            self.stop.set()
        await asyncio.Future()
        raise AssertionError("unreachable")


def test_run_uses_only_public_sockets_and_cancels_cleanly() -> None:
    async def exercise() -> tuple[list[Any], list[str], list[str]]:
        stop = threading.Event()
        cb = Socket([{"channel": "heartbeats", "sequence_num": 0}], stop)
        clob = Socket([[book(), book("down-token")]])
        opened: list[str] = []

        def connect(url: str, **kwargs: Any) -> Socket:
            opened.append(url)
            assert "additional_headers" not in kwargs and "extra_headers" not in kwargs
            return cb if url == COINBASE_WS else clob

        f, events, _ = feed(Get(page([])), coinbase_connect=connect, clob_connect=connect)

        async def no_discovery() -> None:
            await asyncio.Future()

        f._discovery_loop = no_discovery  # type: ignore[method-assign]
        await asyncio.wait_for(f.run(stop), 2)
        assert not f.books
        return events, opened, clob.sent

    events, opened, sent = asyncio.run(exercise())
    assert set(opened) == {COINBASE_WS, CLOB_WS}
    assert json.loads(sent[0]) == {"assets_ids": ["down-token", "up-token"], "type": "market"}
    assert any(kind == "health" and payload["status"] == "stopped" for kind, payload, _ in events)


def test_removing_every_subscription_invalidates_before_socket_close() -> None:
    async def exercise() -> None:
        f, events, _ = feed()
        closed = asyncio.Event()

        class RemovingSocket(Socket):
            async def recv(self) -> str:
                if self.messages:
                    return await super().recv()
                f.tokens.clear()
                return "PONG"

            async def __aexit__(self, *args: object) -> None:
                assert not f.books
                assert f._health_status["clob"][0] == "gap"
                closed.set()

        socket = RemovingSocket([[book(), book("down-token")]])
        f._clob_connect = lambda *args, **kwargs: socket
        task = asyncio.create_task(f._clob_loop())
        await asyncio.wait_for(closed.wait(), 1)
        assert any(kind == "book_snapshot" for kind, _, _ in events)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())

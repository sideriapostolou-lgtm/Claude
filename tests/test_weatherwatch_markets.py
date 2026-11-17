"""Fake-only rules, complementary depth, capture clocks and read-only boundaries."""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, ClassVar

import pytest

from nightcrawler.config import Settings
from nightcrawler.speeddesk_kalshi_ws import MarketDataGap
from nightcrawler.speeddesk_model import Book, Level, Trade
from nightcrawler.weatherwatch_markets import (
    MarketFeeds,
    PublicGET,
    WeatherState,
    kalshi_book,
    kalshi_market,
    settlement,
    us_market,
)


def family() -> dict[str, Any]:
    return {"ticker": "KXHIGHNY", "frequency": "daily", "fee_type": "quadratic", "fee_multiplier": 1}


def market(**changes: Any) -> dict[str, Any]:
    return {"ticker": "KXHIGHNY-26OCT12-B69.5", "event_ticker": "KXHIGHNY-26OCT12",
            "rules_primary": "Maximum temperature at New York City (CLINYC) for Oct 12, 2026 according to The Weather Company.",
            "strike_type": "between", "floor_strike": 69, "cap_strike": 70,
            "status": "active", **changes}


def us(**changes: Any) -> dict[str, Any]:
    return {"slug": "tc-temp-nychigh-2026-10-12-gte69lt70f",
            "description": "Will the highest temperature recorded at Central Park (KNYC) in New York City for 2026-10-12 as reported by the National Weather Service's Climatological Report (Daily) be between 69F and 70F?",
            "feeCoefficient": 0.0695, "comboEnabled": False, **changes}


def parsed() -> dict[str, Any]:
    value = kalshi_market(market(), family(), 100)
    assert value is not None
    return value


def feeds(*, clock: Any = lambda: 100.0, get: Any = None, cap: int = 256) -> tuple[MarketFeeds, list[Any]]:
    events: list[Any] = []
    result = MarketFeeds(lambda *args: events.append(args), threading.Event(), settings=Settings(),
                         clock=clock, rest_get=get, max_active_watches=cap)
    result._market(parsed())
    return result, events


def test_rule_station_and_source_never_substitute_other_venue() -> None:
    value = parsed()
    assert value["station"] == "KNYC"
    assert value["station"] != "KLGA"
    assert value["station_rule"] == "CLINYC"
    assert value["settlement_source"] == "The Weather Company"
    assert value["source_qualified"] is False
    assert value["period_verified"] is False
    assert value["supported"] is True
    assert value["fee_verified"] is True


@pytest.mark.parametrize("rules", ["Temperature in NYC", "At (CLINYC) and (CLIMDW)", "At (CLIZZZ)"])
def test_ambiguous_or_unmapped_rule_station_is_uncovered(rules: str) -> None:
    value = kalshi_market(market(rules_primary=rules), family(), 0)
    assert value is not None and value["station_verified"] is False
    assert value["supported"] is False


def test_international_explicit_station_retained_without_fabricated_day() -> None:
    value = kalshi_market(market(rules_primary="Temperature at London (EGLL) according to The Weather Company"), family(), 0)
    assert value is not None and value["station"] == "EGLL"
    assert value["period_start"] is None and value["supported"] is False


def test_non_daily_and_unparsed_event_are_explicit() -> None:
    value = kalshi_market(market(event_ticker="KXHIGHNY-OCT"), {**family(), "frequency": "monthly"}, 0)
    assert value is not None and value["date"] is None
    assert "non_daily" in value["unsupported_reason"]


def test_fee_override_cannot_inherit_standard_fee() -> None:
    value = kalshi_market(market(fee_multiplier=2), family(), 0)
    assert value is not None and value["fee_verified"] is False


def test_us_rules_override_misleading_slug_inclusivity() -> None:
    value = us_market(us(), 0)
    assert value is not None and value["station"] == "KNYC"
    assert value["floor"] == 69 and value["cap"] == 70 and value["cap_inclusive"] is True
    value = us_market(us(slug="tc-temp-nychigh-2026-10-12-lt69f",
        description=us()["description"].replace("between 69F and 70F", "less than or equal to 68F")), 0)
    assert value is not None and value["cap"] == 68 and value["cap_inclusive"] is True


@pytest.mark.parametrize("text", ["Highest temperature in Miami", "Miami Executive Airport (KTMB)", "Miami International Airport"])
def test_us_own_station_requires_explicit_matching_icao(text: str) -> None:
    value = us_market(us(slug="tc-temp-miahigh-2026-10-12-lt86f", description=text), 0)
    assert value is not None and value["station_verified"] is False


def test_us_date_and_rules_must_agree() -> None:
    value = us_market(us(description=us()["description"].replace("2026-10-12", "2026-10-11")), 0)
    assert value is not None and value["supported"] is False
    assert us_market(us(slug="tc-temp-sjc-dec-lt40"), 0) is None


def test_complementary_asks_are_opposite_bids_not_own_bids() -> None:
    raw = {"orderbook_fp": {"yes_dollars": [["0.03", "12"], ["0.02", "20"]], "no_dollars": [["0.96", "9"]]}}
    book = kalshi_book(raw, "KXHIGHNY-26OCT12-T69", 101, 100)
    assert book is not None
    assert book["no_asks"] == [[0.97, 12], [0.98, 20]]
    assert book["no_bids"] == [[0.96, 9]]
    assert book["yes_asks"] == [[0.04, 9]]
    assert book["received_at"] == 101 and book["requested_at"] == 100
    assert book["exchange_at"] is None and book["post_delay_proven"] is False


def test_crossed_duplicate_or_nonfinite_depth_fails_closed() -> None:
    assert kalshi_book({"orderbook_fp": {"yes_dollars": [["NaN", 1]], "no_dollars": []}}, "X", 1, 0) is None
    assert kalshi_book({"orderbook_fp": {"yes_dollars": [[.03, 1], [.03, 2]], "no_dollars": []}}, "X", 1, 0) is None
    value = kalshi_book({"orderbook_fp": {"yes_dollars": [[.04, 1]], "no_dollars": [[.97, 1]]}}, "X", 1, 0)
    assert value is not None and value["valid"] is False


def test_initial_ws_snapshot_recorded_but_not_execution_fresh() -> None:
    snapshots: list[Any] = []
    state = WeatherState(frozenset({"KXHIGHNY-26OCT12-T69"}), snapshots.append)
    state.apply({"id": 1, "type": "subscribed", "msg": {"sid": 1, "channel": "orderbook_delta"}}, 100)
    books, _ = state.apply({"type": "orderbook_snapshot", "sid": 1, "seq": 1,
        "msg": {"market_ticker": "KXHIGHNY-26OCT12-T69", "yes_dollars_fp": [["0.03", "10"]],
                "no_dollars_fp": [["0.04", "20"]]}}, 100)
    assert books == () and len(snapshots) == 1
    assert snapshots[0]["no_asks"] == [[.97, 10]]
    assert snapshots[0]["no_bids"] == [[.96, 20]]
    assert snapshots[0]["exchange_at"] is None and snapshots[0]["sequence_verified"] is True
    with pytest.raises(MarketDataGap, match="sequence_gap"):
        state.apply({"type": "orderbook_delta", "sid": 1, "seq": 3, "msg": {}}, 101)
    assert len(snapshots) == 1


def test_capture_capacity_and_persisted_settlement_obligations() -> None:
    feed, events = feeds(cap=1)
    key = parsed()["market_id"]
    assert feed.watch({"market_id": key, "until": 700}) is True
    other = {**parsed(), "market_id": "kalshi:other", "venue_id": "other"}
    feed._market(other)
    assert feed.watch({"market_id": "kalshi:other", "until": 700}) is False
    assert events[-1][1]["reason"] == "market_watch_capacity"
    restored, _ = feeds(clock=lambda: 800)
    restored.restore(feed.markets, feed.watches)
    assert key not in restored.watches
    assert restored._pending_settlements[key] == 700  # Settlement is separate from captures.
    assert restored.watch({"market_id": "missing", "until": 900}) is False


def test_same_ws_sequence_and_disconnect_required() -> None:
    feed, events = feeds()
    key, ticker = parsed()["market_id"], parsed()["venue_id"]
    feed.watch({"market_id": key, "until": 200})
    feed._ws_book(Book(ticker, "up", (Level(.03, 2),), (Level(.04, 4),), 100, "a", 100))
    feed._ws_book(Book(ticker, "down", (Level(.96, 4),), (Level(.97, 2),), 100, "b", 100))
    assert key not in feed.books
    feed._ws_book(Book(ticker, "down", (Level(.96, 4),), (Level(.97, 2),), 100, "a", 100))
    assert feed.books[key]["no_asks"] == [[.97, 2]]
    feed._ws_status({"gap_windows": [ticker], "ws_status": "sequence_gap"})
    assert key not in feed.books
    assert any(e[0] == "weather_book" and e[1]["valid"] is False for e in events)


def test_tape_emits_one_actual_trade_not_two_outcomes_or_last_trade_quote() -> None:
    feed, events = feeds()
    key, ticker = parsed()["market_id"], parsed()["venue_id"]
    feed.watch({"market_id": key, "until": 200})
    feed._ws_trade(Trade(ticker, "up", .03, 3, 99, "id:up", "sell", 100))
    feed._ws_trade(Trade(ticker, "down", .97, 3, 99, "id:down", "buy", 100))
    prints = [e[1] for e in events if e[0] == "weather_trade"]
    assert len(prints) == 1 and prints[0]["taker_side"] == "no"
    assert prints[0]["exchange_at"] == 99 and prints[0]["received_at"] == 100


def test_only_final_identity_matched_settlements_count() -> None:
    value = parsed()
    raw = {"market": {"ticker": value["venue_id"], "status": "settled", "result": "no",
                      "settlement_value_dollars": "0.0000", "expiration_value": "72"}}
    result = settlement(raw, value, 100)
    assert result is not None and result["final"] is True and result["source_value"] == 72
    raw["market"]["settlement_value_dollars"] = "0.5"
    assert settlement(raw, value, 100) is None
    pm = us_market(us(), 0)
    assert pm is not None
    assert settlement({"settlement": 0}, pm, 100) is None
    result = settlement({"slug": pm["venue_id"], "settlement": 0}, pm, 100)
    assert result is not None and result["final"] is True


@pytest.mark.parametrize("venue,path", [
    ("kalshi", "/portfolio/orders"), ("kalshi", "/portfolio/balance"),
    ("polymarket_us", "/v1/orders"), ("polymarket_us", "/v1/account/balances"),
    ("kalshi", "/markets/X/../portfolio/orders"), ("polymarket_us", "/v1/markets/not-weather/book"),
])
def test_public_transport_cannot_reach_account_or_order_endpoints(venue: str, path: str) -> None:
    with pytest.raises(ValueError, match="not_allowed"):
        PublicGET()(venue, path)


def test_discovery_lists_uncovered_and_no_open_series_without_assumed_station() -> None:
    def get(venue: str, path: str) -> Any:
        assert venue == "kalshi"
        if path.startswith("/series?"):
            return {"series": [family(), {"ticker": "KXRAIND", "frequency": "daily"}, {"ticker": "KXBTC15M"}]}
        if "series_ticker=KXHIGHNY" in path:
            return {"markets": [market()], "cursor": ""}
        return {"markets": [], "cursor": ""}
    feed, events = feeds(get=get)
    # Advancing fake clock avoids real sleep and any external transport.
    times = iter(range(100, 1000, 2))
    feed.clock = lambda: next(times)
    asyncio.run(feed.discover_kalshi())
    status = events[-1][1]
    assert status["series_found"] == 2 and status["no_open_markets"] == ["KXRAIND"]
    assert feed.stations[0]["station"] == "KNYC"


def test_public_us_tape_unavailability_not_reported_as_zero_prints() -> None:
    feed, events = feeds(get=lambda venue, path: {"markets": [us()]})
    asyncio.run(feed.discover_us())
    status = events[-1][1]
    assert status["trade_tape"] == "unavailable_public_gateway"
    assert status["per_market_second_resolution_guaranteed"] is False
    assert not any(e[0] == "weather_trade" for e in events)


def test_rest_book_keeps_real_transport_and_request_clock() -> None:
    clock = [100.0]
    def get(venue: str, path: str) -> Any:
        clock[0] = 100.5
        return {"orderbook_fp": {"yes_dollars": [[.03, 2]], "no_dollars": [[.96, 3]]}}
    feed, _ = feeds(clock=lambda: clock[0], get=get)
    key = parsed()["market_id"]
    asyncio.run(feed.poll_book(key))
    assert feed.books[key]["requested_at"] == 100
    assert feed.books[key]["received_at"] == 100.5
    assert feed.books[key]["exchange_at"] is None


def test_429_cooldown_is_shared_and_retry_after_not_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests
    class Response:
        status_code = 429
        headers: ClassVar[dict[str, str]] = {"Retry-After": "120"}
        def raise_for_status(self) -> None:
            raise requests.HTTPError("rate limited")
        def close(self) -> None:
            pass
    calls: list[Any] = []
    def get(*args: Any, **kwargs: Any) -> Response:
        calls.append((args, kwargs))
        return Response()
    monkeypatch.setattr(requests, "get", get)
    client = PublicGET(clock=lambda: 100)
    with pytest.raises(requests.HTTPError):
        client("kalshi", "/series")
    with pytest.raises(RuntimeError, match="cooldown"):
        client("kalshi", "/markets")
    assert len(calls) == 1 and client._next["kalshi"] == 220
    assert calls[0][1]["allow_redirects"] is False
    assert "Authorization" not in json.dumps(calls[0][1]["headers"])


def test_rule_day_conflict_is_uncovered_not_a_different_day_lock() -> None:
    value = kalshi_market(market(rules_primary=market()["rules_primary"].replace("Oct 12", "Oct 13")), family(), 0)
    assert value is not None and value["supported"] is False
    assert "rule_date" in value["unsupported_reason"]


def test_restored_discovery_never_creates_capture_or_settlement_obligation() -> None:
    feed, _ = feeds()
    feed.restore({parsed()["market_id"]: parsed()})
    assert feed.watches == {} and feed._pending_settlements == {}


def test_rain_exact_cli_and_secondary_source_kept() -> None:
    value = kalshi_market({"ticker": "KXRAIN-26OCT13-TTN", "event_ticker": "KXRAIN-26OCT13",
        "rules_primary": "If total precipitation at CLITTN in Trenton in Oct 13, 2026 is strictly greater than 0 inches, then Yes.",
        "rules_secondary": "The official value is reported by the Weather Company. Trace amounts count as 0.",
        "strike_type": "greater", "floor_strike": 0},
        {"ticker": "KXRAIN", "frequency": "daily", "fee_type": "quadratic", "fee_multiplier": 1}, 0)
    assert value is not None and value["supported"] is True
    assert value["station"] == "KTTN" and value["kind"] == "rain" and value["floor"] == 0
    assert value["settlement_source"] == "The Weather Company" and value["source_qualified"] is False


def test_restore_cannot_bypass_active_capture_capacity() -> None:
    feed, events = feeds(cap=1)
    a = parsed()
    b = {**a, "market_id": "kalshi:other", "venue_id": "other"}
    feed.restore({a["market_id"]: a, b["market_id"]: b}, {a["market_id"]: 200, b["market_id"]: 200})
    assert len(feed.watches) == 1 and len(feed._pending_settlements) == 2
    assert events[-1][1]["reason"] == "restored_market_watch_capacity"


def test_capture_samples_do_not_refresh_original_book_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    feed, events = feeds()
    key = parsed()["market_id"]
    feed.watch({"market_id": key, "until": 200})
    feed.books[key] = {"market_id": key, "venue": "kalshi", "received_at": 90,
                       "exchange_at": 89, "valid": True, "complete": True}
    async def pause(_: float) -> None:
        feed._stop.set()
    monkeypatch.setattr(asyncio, "sleep", pause)
    asyncio.run(feed._samples())
    sample = events[-1][1]
    assert sample["sample_only"] is True and sample["sampled_at"] == 100
    assert sample["received_at"] == 90 and sample["exchange_at"] == 89


def test_public_response_byte_cap_closes_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests
    class Response:
        status_code = 200
        closed = False
        def raise_for_status(self) -> None:
            pass
        def iter_content(self, size: int) -> Any:
            for _ in range(9):
                yield b" " * 1_000_000
        def close(self) -> None:
            self.closed = True
    response = Response()
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)
    with pytest.raises(ValueError, match="response_limit"):
        PublicGET(clock=lambda: 100)("kalshi", "/series")
    assert response.closed


def test_chicago_rain_uses_ohare_when_its_own_rule_says_cliord() -> None:
    value = kalshi_market({"ticker": "KXRAIN-26OCT13-ORD", "event_ticker": "KXRAIN-26OCT13",
        "rules_primary": "Total precipitation at CLIORD in Chicago in Oct 13, 2026 is greater than 0 inches.",
        "strike_type": "greater", "floor_strike": 0}, {"ticker": "KXRAIN", "frequency": "daily"}, 0)
    assert value is not None and value["station"] == "KORD" and value["supported"] is True
    assert value["station"] != "KMDW"

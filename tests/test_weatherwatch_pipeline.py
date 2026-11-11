"""Actual public parsers through the durable runner and page; fake transports only."""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from typing import Any

import pytest

from nightcrawler.config import Settings
from nightcrawler.pagestate import weatherwatch_panel
from nightcrawler.skipwatch_journal import iter_records
from nightcrawler.weatherwatch import WeatherwatchRunner
from nightcrawler.weatherwatch_markets import (
    MarketFeeds,
    WeatherState,
    kalshi_market,
    settlement,
    us_market,
)
from nightcrawler.weatherwatch_observations import HttpReply, ObservationFeeds

DAY = "2026-10-12"
DAY_START = datetime(2026, 10, 12, 5, tzinfo=UTC).timestamp()  # KNYC standard-time proxy from actual rules parser.


class Pipeline:
    def __init__(self, directory, *, start: float = DAY_START) -> None:
        self.now = start
        self.settings = Settings(data_dir=directory)
        self.stop = threading.Event()
        self.runner = WeatherwatchRunner(self.settings, self.stop, clock=lambda: self.now)
        self.market_reply: Any = None
        self.observation_reply: HttpReply | None = None
        self.feeds = MarketFeeds(self.runner.on_event, self.stop, settings=self.settings,
            clock=lambda: self.now, receipt_clock_id="pipeline-test", rest_get=self.market_get)
        self.runner.markets = self.feeds
        self.observations = ObservationFeeds(self.runner.on_event, self.stop, lambda: self.feeds.stations,
            clock=lambda: self.now, receipt_clock_id="pipeline-test", http_get=self.observation_get)

    def market_get(self, venue: str, path: str) -> Any:
        assert venue in {"kalshi", "polymarket_us"} and "portfolio" not in path
        return self.market_reply

    def observation_get(self, url: str) -> HttpReply:
        assert url.startswith(("https://api.weather.gov/", "https://aviationweather.gov/",
                               "https://madis-data.ncep.noaa.gov/madisPublic1/"))
        assert self.observation_reply is not None
        return self.observation_reply

    def add_market(self, kind: str = "high", *, venue: str = "kalshi") -> dict[str, Any]:
        if venue == "kalshi":
            series = {"ticker": {"high": "KXHIGHNY", "low": "KXLOWTNY", "rain": "KXRAINNY"}[kind],
                      "frequency": "daily", "fee_type": "quadratic", "fee_multiplier": 1}
            raw = {"ticker": series["ticker"] + "-26OCT12-T70", "event_ticker": series["ticker"] + "-26OCT12",
                   "rules_primary": "Measurement at New York City (CLINYC) on Oct 12, 2026 according to The Weather Company.",
                   "strike_type": "greater" if kind == "rain" else "between",
                   "floor_strike": .01 if kind == "rain" else 60,
                   "cap_strike": None if kind == "rain" else 70, "status": "active"}
            market = kalshi_market(raw, series, self.now)
        else:
            market = us_market({"slug": "tc-temp-nychigh-2026-10-12-gte60lt70f",
                "description": "Will the highest temperature recorded at Central Park (KNYC) in New York City "
                    "for 2026-10-12 as reported by the National Weather Service's Climatological Report (Daily) "
                    "be between 60F and 70F?", "feeCoefficient": .0695, "comboEnabled": False}, self.now)
        assert market is not None and market["supported"]
        assert market["period_start"] == DAY_START
        self.feeds._market(market)
        self.feeds._stations()
        self.runner.drain()
        return market

    def reading(self, valid: float, *, celsius: int = 22, rain: str = "P0010", source: str = "aviationweather",
                suspect: bool = False) -> None:
        self.now = valid + 10
        stamp = datetime.fromtimestamp(valid, UTC)
        raw = f"METAR KNYC {stamp:%d%H%M}Z AUTO 22005KT 10SM CLR {celsius:02}/10 A2992 RMK AO2 "
        raw += f"T0{celsius * 10:03}0100 {rain}" + (" $" if suspect else "")
        if source == "aviationweather":
            body: Any = [{"icaoId": "KNYC", "rawOb": raw, "obsTime": valid, "temp": celsius,
                          "metarType": "METAR"}]
        else:
            body = {"properties": {"stationId": "KNYC", "timestamp": stamp.isoformat(), "rawMessage": raw,
                "temperature": {"unitCode": "wmoUnit:degC", "value": celsius, "qualityControl": "V"},
                "precipitationLastHour": {"qualityControl": "V"}}}
        self.observation_reply = HttpReply(200, {}, json.dumps(body).encode(), self.now - .1, self.now,
                                          int(self.now * 1e9) - 100_000_000, int(self.now * 1e9))
        self.observations.poll_once(source, self.observations.stations())
        self.runner.drain()

    def ws(self, market: dict[str, Any], *, side: str = "no") -> tuple[WeatherState, int]:
        state = WeatherState(frozenset({market["venue_id"]}), self.feeds._snapshot)
        state.apply({"id": 1, "type": "subscribed", "msg": {"sid": 7, "channel": "orderbook_delta"}}, self.now)
        # WS requests use_yes_price=true. The NO side is quoted on the YES scale.
        yes_bid, no_ask_on_yes_scale = ("0.03", "0.04") if side == "no" else ("0.96", "0.97")
        self.frame(state, {"type": "orderbook_snapshot", "sid": 7, "seq": 1,
            "msg": {"market_ticker": market["venue_id"], "yes_dollars_fp": [[yes_bid, "5"]],
                    "no_dollars_fp": [[no_ask_on_yes_scale, "9"]]}})
        return state, 1

    def frame(self, state: WeatherState, frame: dict[str, Any]) -> None:
        books, trades = state.apply(frame, self.now)
        for book in books:
            self.feeds._ws_book(book)
        for trade in trades:
            self.feeds._ws_trade(trade)
        self.runner.drain()

    def delta(self, state: WeatherState, market: dict[str, Any], seq: int, *, side: str = "no",
              delta: str = "0.00") -> None:
        self.frame(state, {"type": "orderbook_delta", "sid": 7, "seq": seq,
            "msg": {"market_ticker": market["venue_id"], "side": "yes", "price_dollars": ".03" if side == "no" else ".96",
                    "delta_fp": delta, "ts_ms": int(self.now * 1000)}})

    def finish(self, market: dict[str, Any], result: str) -> dict[str, Any]:
        self.now = market["period_end"] + 10
        raw = ({"market": {"ticker": market["venue_id"], "status": "settled", "result": result,
                           "settlement_value_dollars": "1" if result == "yes" else "0"}}
               if market["venue"] == "kalshi" else {"slug": market["venue_id"], "settlement": 1 if result == "yes" else 0})
        parsed = settlement(raw, market, self.now)
        assert parsed is not None
        self.feeds.emit("weather_settlement", parsed)
        self.runner.drain()
        self.runner.checkpoint()
        panel = weatherwatch_panel(self.settings, self.now)
        assert panel is not None
        return panel

    def close(self) -> None:
        self.runner.close()


@pytest.mark.parametrize("kind,celsius,result,pnl", [("high", 22, "no", .0279), ("low", 10, "yes", -.9721)])
def test_temperature_actual_parsers_confirm_only_distinct_readings_then_book_and_settle(tmp_path, kind, celsius, result, pnl):
    pipe = Pipeline(tmp_path)
    try:
        market = pipe.add_market(kind)
        valid = DAY_START + 3600
        pipe.reading(valid, celsius=celsius)
        lock = pipe.runner.model.locks[market["market_id"]]
        assert lock["confirmed_at"] is None and lock["side"] == "no"
        assert market["market_id"] in pipe.feeds.watches
        pipe.reading(valid, celsius=celsius, source="nws")  # Same METAR echoed by another gateway.
        assert lock["confirmed_at"] is None
        pipe.reading(valid + 60, celsius=celsius)
        assert lock["confirmed_at"] == pipe.now and not lock["qualified_lock"]
        state, sequence = pipe.ws(market)
        scenario = lock["scenarios"]["0.97"]
        assert "entry_cost_usd" not in scenario  # Snapshot lacks exchange capture time.
        pipe.now += .01
        pipe.delta(state, market, sequence + 1)
        assert scenario["status"] == "checking_quote_persistence"
        pipe.now += .30
        pipe.delta(state, market, sequence + 2)
        assert scenario["entry_cost_usd"] == pytest.approx(.9721)
        assert scenario["depth_at_threshold"] == 5
        assert not scenario["execution_proven"]
        # One exchange execution is emitted as two complementary outcomes by
        # the shared WS parser; the weather tape must count it exactly once.
        state.apply({"id": 2, "type": "subscribed", "msg": {"sid": 9, "channel": "trade"}}, pipe.now)
        for sequence in (1, 2):
            pipe.frame(state, {"type": "trade", "sid": 9, "seq": sequence,
                "msg": {"market_ticker": market["venue_id"], "trade_id": "same-public-print",
                    "count_fp": "2.00", "yes_price_dollars": "0.03", "no_price_dollars": "0.97",
                    "taker_side": "no", "taker_outcome_side": "no", "taker_book_side": "ask",
                    "is_block_trade": False, "ts_ms": int(pipe.now * 1000)}})
        assert pipe.runner.model.daily_report(DAY)["trade_prints"] == 1
        panel = pipe.finish(market, result)
        displayed = panel["reports"][DAY]["conditional_scenarios"]["kalshi"]["0.97"]
        assert displayed["conditional_entries"] == displayed["settled_entries"] == 1
        assert displayed["conditional_hold_pnl_usd"] == pytest.approx(pnl)
        assert panel["today"]["settlement_disagreements"] == (1 if result == "yes" else None)
        assert displayed["qualified_pnl_usd"] is None and panel["qualified_cents_per_day"] is None
        raw_rows = list(iter_records(pipe.runner.directory))
        reading = next(row for row in raw_rows if row["kind"] == "weather_observation")
        assert reading["payload"]["received_at"] == valid + 10
        assert reading["payload"]["valid_at"] == valid
        assert sum(row["kind"] == "confirmed_proxy" for row in raw_rows) == 1
    finally:
        pipe.close()


@pytest.mark.parametrize("first_valid_offset", [3600, 6780])
def test_rain_actual_hourly_metars_produce_yes_with_verified_positive_in_day_evidence(tmp_path, first_valid_offset):
    pipe = Pipeline(tmp_path)
    try:
        market = pipe.add_market("rain")
        pipe.reading(DAY_START + first_valid_offset)
        lock = pipe.runner.model.locks[market["market_id"]]
        assert lock["side"] == "yes" and lock["confirmed_at"] is None
        pipe.reading(DAY_START + first_valid_offset + 3600)
        assert lock["confirmed_at"] == pipe.now
        state, sequence = pipe.ws(market, side="yes")
        pipe.now += .01
        pipe.delta(state, market, sequence + 1, side="yes")
        pipe.now += .30
        pipe.delta(state, market, sequence + 2, side="yes")
        assert lock["scenarios"]["0.97"]["entry_price"] == .97
        panel = pipe.finish(market, "yes")
        assert panel["reports"][DAY]["conditional_scenarios"]["kalshi"]["0.97"]["conditional_hold_pnl_usd"] == .0279
    finally:
        pipe.close()


def test_midnight_straddling_rain_and_suspect_temperature_never_gain_confirmed_proxy(tmp_path):
    pipe = Pipeline(tmp_path)
    try:
        rain, high = pipe.add_market("rain"), pipe.add_market("high")
        pipe.reading(DAY_START + 600, suspect=True)
        pipe.reading(DAY_START + 1200, suspect=True)
        assert rain["market_id"] not in pipe.runner.model.locks and high["market_id"] not in pipe.runner.model.locks
        pipe.reading(DAY_START + 1800)
        pipe.reading(DAY_START + 1860)
        assert rain["market_id"] not in pipe.runner.model.locks
        assert pipe.runner.model.locks[high["market_id"]]["confirmed_at"] == pipe.now
    finally:
        pipe.close()


def test_disappearing_timestamped_depth_and_real_losing_settlement_stay_honest(tmp_path):
    pipe = Pipeline(tmp_path)
    try:
        market = pipe.add_market()
        pipe.reading(DAY_START + 3600)
        pipe.reading(DAY_START + 3660)
        state, sequence = pipe.ws(market)
        pipe.now += .01
        pipe.delta(state, market, sequence + 1)
        pipe.now += .30
        pipe.delta(state, market, sequence + 2, delta="-5")
        scenario = pipe.runner.model.locks[market["market_id"]]["scenarios"]["0.97"]
        assert scenario["status"] == "quote_disappeared_after_delay" and "entry_cost_usd" not in scenario
        panel = pipe.finish(market, "yes")
        displayed = panel["reports"][DAY]["conditional_scenarios"]["kalshi"]["0.97"]
        assert displayed["conditional_entries"] == 0 and displayed["conditional_hold_pnl_usd"] is None
        assert panel["today"]["settlement_disagreements"] == 1
    finally:
        pipe.close()


def test_us_gateway_actual_book_parser_preserves_venue_and_fee_scope(tmp_path):
    pipe = Pipeline(tmp_path)
    try:
        market = pipe.add_market(venue="polymarket_us")
        pipe.reading(DAY_START + 3600)
        pipe.reading(DAY_START + 3660)
        pipe.market_reply = {"marketData": {"marketSlug": market["venue_id"], "state": "MARKET_STATE_OPEN",
            "bids": [{"px": {"value": "0.03"}, "qty": "5"}],
            "offers": [{"px": {"value": "0.04"}, "qty": "9"}],
            "transactTime": datetime.fromtimestamp(pipe.now, UTC).isoformat()}}
        asyncio.run(pipe.feeds.poll_book(market["market_id"]))
        pipe.runner.drain()
        pipe.now += .30
        pipe.market_reply["marketData"]["transactTime"] = datetime.fromtimestamp(pipe.now, UTC).isoformat()
        asyncio.run(pipe.feeds.poll_book(market["market_id"]))
        pipe.runner.drain()
        scenario = pipe.runner.model.locks[market["market_id"]]["scenarios"]["0.97"]
        assert scenario["entry_cost_usd"] == .97  # Verified one-contract US fee rounds to zero cents.
        panel = pipe.finish(market, "no")
        assert panel["reports"][DAY]["conditional_scenarios"]["polymarket_us"]["0.97"]["conditional_hold_pnl_usd"] == .03
        assert panel["reports"][DAY]["conditional_scenarios"]["kalshi"]["0.97"]["conditional_entries"] == 0
        assert not panel["real_orders_available"]
    finally:
        pipe.close()


def test_rest_quote_sale_needs_a_second_fresh_bid_and_charges_both_legs(tmp_path):
    pipe = Pipeline(tmp_path)
    try:
        market = pipe.add_market()
        pipe.reading(DAY_START + 3600)
        pipe.reading(DAY_START + 3660)
        pipe.market_reply = {"orderbook_fp": {"yes_dollars": [["0.03", "5"]], "no_dollars": [["0.96", "9"]]}}
        asyncio.run(pipe.feeds.poll_book(market["market_id"]))
        pipe.runner.drain()
        pipe.now += 1.1
        asyncio.run(pipe.feeds.poll_book(market["market_id"]))
        pipe.runner.drain()
        scenario = pipe.runner.model.locks[market["market_id"]]["scenarios"]["0.97"]
        assert scenario["entry_cost_usd"] == pytest.approx(.9721)
        pipe.market_reply = {"orderbook_fp": {"yes_dollars": [["0.005", "5"]], "no_dollars": [["0.99", "9"]]}}
        pipe.now += 1.1
        asyncio.run(pipe.feeds.poll_book(market["market_id"]))
        pipe.runner.drain()
        assert "conditional_exit_pnl_usd" not in scenario
        pipe.now += 1.1
        asyncio.run(pipe.feeds.poll_book(market["market_id"]))
        pipe.runner.drain()
        assert scenario["exit_fee_usd"] == pytest.approx(.0007)
        assert scenario["conditional_exit_pnl_usd"] == pytest.approx(.0172)
        assert scenario["exit_method"] == "quote_persistence_taker_bid_not_resting_fill"
        pipe.runner.checkpoint()
        panel = weatherwatch_panel(pipe.settings, pipe.now)
        displayed = panel["today"]["conditional_scenarios"]["kalshi"]["0.97"]
        assert displayed["conditional_exit_pnl_usd"] == .0172 and displayed["pending_hold_entries"] == 1
    finally:
        pipe.close()


def test_adapter_capacity_callback_is_drained_without_recursive_model_mutation(tmp_path):
    pipe = Pipeline(tmp_path)
    try:
        pipe.feeds.max_active_watches = 1
        first = pipe.add_market()
        second = pipe.add_market(venue="polymarket_us")
        pipe.reading(DAY_START + 3600)
        assert first["market_id"] in pipe.feeds.watches and second["market_id"] not in pipe.feeds.watches
        assert pipe.runner.capacity_skips == 1
        refused = pipe.runner.model.locks[second["market_id"]]
        assert refused["watch_rejected"] == "capture_capacity_or_unsupported"
        pipe.runner.checkpoint()
        panel = weatherwatch_panel(pipe.settings, pipe.now)
        assert panel["capacity_skips"] == 1 and panel["today"]["gaps"] > 0
        assert not pipe.runner.paused
    finally:
        pipe.close()


def test_madis_five_minute_parser_confirms_a_new_reading_without_claiming_one_minute(tmp_path):
    pipe = Pipeline(tmp_path)
    try:
        market = pipe.add_market()
        valid = DAY_START + 3600
        pipe.reading(valid)
        lock = pipe.runner.model.locks[market["market_id"]]
        for offset in (0, 300):
            pipe.now = valid + offset + 10
            stamp = datetime.fromtimestamp(valid + offset, UTC)
            xml = ('<mesonet><record provider="ASOS-HFM" shef_id="KNYC" var="V-T" '
                   f'ObTime="{stamp:%Y-%m-%dT%H:%M}" data_value="295.14999" '
                   'QCD="V" QCR="0" QCA="1"/></mesonet>')
            pipe.observation_reply = HttpReply(200, {}, xml.encode(), pipe.now - .1, pipe.now,
                                               int(pipe.now * 1e9) - 100_000_000, int(pipe.now * 1e9))
            pipe.observations.poll_madis("KNYC")
            pipe.runner.drain()
            if offset == 0:
                assert lock["confirmed_at"] is None  # Same valid time as the METAR is still one reading.
            else:
                assert lock["confirmed_at"] == pipe.now
        pipe.runner.checkpoint()
        panel = weatherwatch_panel(pipe.settings, pipe.now)
        source = panel["sources"]["madis_hfm"]
        assert source["readings"] == 2 and source["bootstrap_readings"] == 1 and source["latency_samples"] == 1
        assert source["median_latency_s"] == 10
        records = [row["payload"] for row in iter_records(pipe.runner.directory)
                   if row["kind"] == "weather_observation" and row["payload"]["source"] == "madis_hfm"]
        assert len(records) == 2
        assert all(row["resolution_s"] == 300 and row["independent_1m"] is False for row in records)
        assert not panel["real_orders_available"] and panel["qualified_cents_per_day"] is None
    finally:
        pipe.close()

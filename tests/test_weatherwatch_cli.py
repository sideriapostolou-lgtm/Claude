"""Official climate text fixtures: no network and no settlement assumptions."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from nightcrawler.weatherwatch_cli import parse_cli
from nightcrawler.weatherwatch_observations import HttpReply, ObservationFeeds

PRODUCT = "12345678-1234-1234-1234-123456789abc"
NOW = datetime(2026, 10, 12, 7, tzinfo=UTC).timestamp()
TEXT = """
000
CDUS41 KOKX 120622
CLINYC

CLIMATE REPORT
NATIONAL WEATHER SERVICE NEW YORK, NY
222 AM EDT MON OCT 12 2026

...THE CENTRAL PARK NY CLIMATE SUMMARY FOR OCTOBER 11 2026...

WEATHER ITEM OBSERVED TIME RECORD YEAR NORMAL
TEMPERATURE (F)
 YESTERDAY
  MAXIMUM         60    741 AM  85    1949 66 -6 64
  MINIMUM         54   1159 PM  34    1964 53  1 58
  AVERAGE         57
PRECIPITATION (IN)
  YESTERDAY        1.84          3.06 2002 0.14 1.70 0.09
  MONTH TO DATE    1.99
SNOWFALL (IN)
  YESTERDAY        0.0
DEGREE DAYS
 COOLING
 YESTERDAY 0

THE CENTRAL PARK NY CLIMATE NORMALS FOR TODAY
 MAXIMUM TEMPERATURE (F) 66 86 1928
T INDICATES TRACE AMOUNT.
MM INDICATES MISSING.
$$
"""


def body(text: str = TEXT, **overrides: Any) -> dict[str, Any]:
    return {"id": PRODUCT, "productCode": "CLI", "issuanceTime": "2026-10-12T06:22:00+00:00",
            "productText": text, **overrides}


def response(payload: Any = None, status: int = 200, **headers: str) -> HttpReply:
    return HttpReply(status, headers, json.dumps(payload).encode(), NOW - 1, NOW, 10, 20)


def parse(text: str = TEXT, **overrides: Any) -> dict[str, Any]:
    event = parse_cli(body(text, **overrides), "KNYC", "CLINYC", response(), "clock-domain")
    assert event is not None
    return event


def test_complete_cli_uses_climate_date_not_issue_date_and_exact_station() -> None:
    event = parse()
    assert event["climate_day"] == "2026-10-11"
    assert event["station"] == "KNYC"
    assert event["station_rule"] == "CLINYC"
    assert event["issued_at"] == datetime(2026, 10, 12, 6, 22, tzinfo=UTC).timestamp()
    assert event["maximum_f"] == 60
    assert event["minimum_f"] == 54
    assert event["precipitation_in"] == 1.84
    assert event["precipitation_trace"] is False
    assert event["final_report"] is True
    assert event["contract_settlement"] is False
    assert event["quality"] == "accepted"
    assert event["receipt_clock_id"] == "clock-domain"


def test_partial_afternoon_and_preliminary_products_are_never_final() -> None:
    partial = TEXT.replace("YESTERDAY", "TODAY").replace("WEATHER ITEM", "VALID TODAY AS OF 0400 PM LOCAL TIME.\nWEATHER ITEM")
    assert parse(partial)["final_report"] is False
    assert parse(TEXT.replace("CLIMATE REPORT", "PRELIMINARY CLIMATE REPORT"))["final_report"] is False


def test_yesterday_heading_required_even_if_summary_date_is_old() -> None:
    assert parse(TEXT.replace("YESTERDAY", "TODAY"))["final_report"] is False


def test_corrected_report_has_independent_revision_and_explicit_correction() -> None:
    original = parse()
    corrected = parse(TEXT.replace("CLIMATE REPORT", "CLIMATE REPORT...CORRECTED").replace("60    741", "61    741"))
    assert corrected["corrected"] is True
    assert corrected["revision_id"] != original["revision_id"]
    assert corrected["maximum_f"] == 61
    assert corrected["finality_scope"] == "published_complete_daily_report_can_be_corrected_later"


@pytest.mark.parametrize("text", [TEXT.replace("CLINYC", "CLILGA"), TEXT.replace("CLINYC", "CLINYC\nCLILGA"),
                                   TEXT.replace("CLINYC\n", "\n") + "\nCLINYC"])
def test_wrong_or_ambiguous_station_header_cannot_be_used(text: str) -> None:
    assert parse_cli(body(text), "KNYC", "CLINYC", response(), "clock") is None


def test_cli_trace_and_missing_amounts_do_not_become_zero() -> None:
    trace = parse(TEXT.replace("1.84          3.06", "T             3.06"))
    missing = parse(TEXT.replace("1.84          3.06", "MM            3.06"))
    assert trace["precipitation_trace"] is True
    assert trace["precipitation_in"] is None
    assert missing["precipitation_in"] is None
    assert missing["precipitation_trace"] is False


@pytest.mark.parametrize("replacement", ["MM", "-200", "53"])
def test_missing_out_of_range_and_inverted_extrema_are_not_comparable(replacement: str) -> None:
    event = parse(TEXT.replace("60    741", replacement + "    741"))
    assert event["maximum_f"] is None
    assert event["minimum_f"] is None
    assert event["quality"] == "suspect"


def test_record_marker_does_not_break_temperature() -> None:
    assert parse(TEXT.replace("60    741", "60R   741"))["maximum_f"] == 60


@pytest.mark.parametrize("overrides", [{"productCode": "RER"}, {"id": "../../bad"},
                                       {"issuanceTime": "2026-10-12T06:22:00"},
                                       {"productText": TEXT.replace("OCTOBER 11", "OCTOBER 32")}])
def test_invalid_metadata_is_rejected(overrides: dict[str, Any]) -> None:
    assert parse_cli(body(**overrides), "KNYC", "CLINYC", response(), "clock") is None


def test_future_issuance_or_clock_reversal_cannot_be_final() -> None:
    assert parse(issuanceTime="2026-10-13T06:22:00+00:00")["final_report"] is False
    event = parse_cli(body(), "KNYC", "CLINYC", replace(response(), requested_at=NOW + 10), "clock")
    assert event is not None and event["final_report"] is False


def test_precip_section_can_omit_snowfall_but_not_use_degree_day_number() -> None:
    assert parse(TEXT.replace("SNOWFALL (IN)\n  YESTERDAY        0.0\n", ""))["precipitation_in"] == 1.84
    assert parse(TEXT.replace("PRECIPITATION (IN)", "PRECIPITATION UNKNOWN"))["precipitation_in"] is None


def test_cli_collection_requires_verified_rules_and_exact_tokens() -> None:
    feeds = ObservationFeeds(lambda kind, payload, at: None, threading.Event(), lambda: [
        {"station": "KNYC", "station_rule": "CLINYC", "station_verified": True},
        {"station": "KMDW", "station_rule": "CLIMDW", "station_verified": False},
        {"station": "KNYC", "station_rule": "Central Park", "station_verified": True},
    ])
    assert feeds.cli_stations() == [("KNYC", "CLINYC")]


def test_index_does_not_emit_a_cli_report_and_only_valid_ids_are_followed() -> None:
    events: list[dict[str, Any]] = []
    urls: list[str] = []

    def get(url: str) -> HttpReply:
        urls.append(url)
        return response({"@graph": [{"id": PRODUCT, "productCode": "CLI"},
                                     {"id": "../../bad", "productCode": "CLI"},
                                     {"id": PRODUCT, "productCode": "CLI"}]})

    feeds = ObservationFeeds(lambda kind, payload, at: events.append({"kind": kind, **payload}),
                             threading.Event(), http_get=get)
    delay, ids = feeds.poll_cli("KNYC", "CLINYC")
    assert delay >= 300
    assert ids == [PRODUCT]
    assert urls == ["https://api.weather.gov/products/types/CLI/locations/NYC"]
    assert all(event["kind"] == "weather_source_status" for event in events)


def test_official_product_emits_separate_cli_event_not_venue_settlement() -> None:
    events: list[dict[str, Any]] = []
    feeds = ObservationFeeds(lambda kind, payload, at: events.append({"kind": kind, **payload}),
                             threading.Event(), http_get=lambda url: response(body()))
    delay, ids = feeds.poll_cli("KNYC", "CLINYC", PRODUCT)
    assert delay >= 3600 and ids == []
    assert events[0]["kind"] == "weather_cli"
    assert events[0]["contract_settlement"] is False


def test_wrong_product_id_or_unparsed_body_cannot_claim_successful_comparison() -> None:
    events: list[dict[str, Any]] = []
    feeds = ObservationFeeds(lambda kind, payload, at: events.append({"kind": kind, **payload}),
                             threading.Event(), http_get=lambda url: response(body(id="87654321-1234-1234-1234-123456789abc")))
    feeds.poll_cli("KNYC", "CLINYC", PRODUCT)
    assert len(events) == 1
    assert events[0]["status"] == "unparsed"


def test_cli_429_stops_observation_requests_for_same_origin() -> None:
    calls: list[str] = []

    def get(url: str) -> HttpReply:
        calls.append(url)
        return response(status=429, **{"Retry-After": "3600"})

    feeds = ObservationFeeds(lambda kind, payload, at: None, threading.Event(), http_get=get,
                             monotonic_ns=lambda: 100)
    assert feeds.poll_cli("KNYC", "CLINYC")[0] == 3600
    assert feeds.poll_once("nws", ["KMDW"]) == 3600
    assert len(calls) == 1

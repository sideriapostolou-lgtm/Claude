"""Public five-minute MADIS HFM is never presented as independent one-minute OMO."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from nightcrawler.weatherwatch_madis import madis_url, parse_madis
from nightcrawler.weatherwatch_observations import HttpReply, ObservationFeeds

NOW = datetime(2026, 10, 12, 23, tzinfo=UTC).timestamp()
XML = '<mesonet><record var="V-T" shef_id="KMDW" ObTime="2026-10-12T22:55" provider="ASOS-HFM" data_value="302.149994" QCD="V" QCA="123" QCR="0" /></mesonet>'


def response(text: str = XML, status: int = 200, **headers: str) -> HttpReply:
    return HttpReply(status, headers, text.encode(), NOW - 1, NOW, 10, 20)


def parse(text: str = XML, *, left_censored: bool = True) -> list[dict[str, Any]]:
    return parse_madis(text, "KMDW", response(), "clock", left_censored=left_censored)


def test_documented_query_is_single_station_all_records_and_exact_provider() -> None:
    parts = urlsplit(madis_url("KMDW"))
    args = parse_qs(parts.query)
    assert parts.hostname == "madis-data.ncep.noaa.gov"
    assert args["stanam"] == ["KMDW"]
    assert args["stasel"] == ["1"]  # Zero would silently request all stations.
    assert args["recwin"] == ["4"]  # Three would return only latest report.
    assert args["pvd"] == ["ASOS-HFM"]
    assert args["minbck"] == ["-30"]
    assert args["qcsel"] == ["0"]  # Bad QC must remain visible in the evidence.
    with pytest.raises(ValueError):
        madis_url("KMDW&stasel=0")


def test_kelvin_float_serialization_is_not_six_decimal_precision() -> None:
    event = parse()[0]
    assert event["temperature_c"] == pytest.approx(28.999994)
    assert event["raw_temperature_kelvin"] == "302.149994"
    assert event["temperature_precision_c"] == 1
    assert event["lower_f"] == pytest.approx(83.2982)
    assert event["upper_f"] == pytest.approx(85.1018)
    assert event["resolution_s"] == 300
    assert event["independent_1m"] is False
    assert event["quality"] == "accepted"
    assert event["left_censored"] is True
    assert event["publication_at"] is None
    assert event["data_latency_s"] == 300
    assert event["receipt_clock_id"] == "clock"
    assert event["climate_day"] is None
    assert event["interval_complete"] is False
    assert 'provider="ASOS-HFM"' in event["raw_record_xml"]


def test_all_initial_lookback_rows_are_censored_not_just_the_oldest() -> None:
    record = XML.removeprefix("<mesonet>").removesuffix("</mesonet>")
    events = parse("<mesonet>" + record.replace("22:55", "22:50") + record + "</mesonet>")
    assert len(events) == 2 and all(event["left_censored"] for event in events)
    assert events[0]["received_at"] == events[1]["received_at"] == NOW
    assert events[0]["valid_at"] != events[1]["valid_at"]


@pytest.mark.parametrize("old,new", [("KMDW", "KORD"), ("ASOS-HFM", "ASOS"), ("V-T", "V-TD"),
                                     ("302.149994", "-99999"), ("302.149994", "NaN"),
                                     ("2026-10-12T22:55", "2026-10-12 22:55")])
def test_wrong_station_provider_variable_and_missing_values_never_confirm(old: str, new: str) -> None:
    assert parse(XML.replace(old, new)) == []


@pytest.mark.parametrize("old,new", [('QCD="V"', 'QCD="Q"'), ('QCD="V"', 'QCD="X"'),
                                     ('QCD="V"', 'QCD="B"'), ('QCR="0"', 'QCR="33"')])
def test_failed_provider_qc_is_suspect(old: str, new: str) -> None:
    event = parse(XML.replace(old, new))[0]
    assert event["quality"] == "suspect"
    assert "provider_temperature_qc_suspect" in event["quality_flags"]


def test_unknown_qc_or_unexplained_precision_cannot_be_accepted() -> None:
    assert parse(XML.replace('QCD="V"', 'QCD="Z"'))[0]["quality"] == "unknown"
    fractional = parse(XML.replace("302.149994", "302.449994"))[0]
    assert fractional["quality"] == "unknown"
    assert fractional["lower_f"] is None
    assert fractional["temperature_precision_c"] is None


def test_reading_identity_is_stable_across_qc_revision_but_revision_identity_changes() -> None:
    first, revised = parse()[0], parse(XML.replace('QCD="V"', 'QCD="Q"'))[0]
    assert first["observation_id"] == revised["observation_id"]
    assert first["revision_id"] != revised["revision_id"]
    changed_value = parse(XML.replace("302.149994", "298.149994"))[0]
    assert first["observation_id"] == changed_value["observation_id"]
    assert first["revision_id"] != changed_value["revision_id"]


def test_future_and_local_reversed_clocks_fail_closed() -> None:
    assert parse(XML.replace("22:55", "23:55"))[0]["quality"] == "suspect"
    event = parse_madis(XML, "KMDW", replace(response(), request_monotonic_ns=30), "clock", left_censored=False)[0]
    assert event["quality"] == "suspect"
    assert event["data_latency_s"] is None


@pytest.mark.parametrize("text", ["not XML", '<!DOCTYPE mesonet><mesonet/>', '<!ENTITY x "bad"><mesonet/>',
                                    "<other/>", " " * 500001])
def test_invalid_unbounded_or_entity_xml_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse(text)


def test_poll_persists_raw_xml_and_censors_only_first_successful_batch() -> None:
    events: list[dict[str, Any]] = []
    feeds = ObservationFeeds(lambda kind, payload, at: events.append({"kind": kind, **payload}),
                             threading.Event(), http_get=lambda url: response())
    assert feeds.poll_madis("KMDW") == 60
    assert feeds.poll_madis("KMDW") == 60
    documents = [row for row in events if row["kind"] == "weather_source_document"]
    readings = [row for row in events if row["kind"] == "weather_observation"]
    assert len(documents) == 2 and documents[0]["raw_xml"] == XML
    assert readings[0]["left_censored"] is True
    assert readings[1]["left_censored"] is False
    assert readings[0]["observation_id"] == readings[1]["observation_id"]
    assert "raw_xml" not in events[-1]  # Full document stays out of panel health.


def test_long_retry_after_blocks_other_stations_and_cache_lifetime_is_respected() -> None:
    calls: list[str] = []

    def get(url: str) -> HttpReply:
        calls.append(url)
        return response(status=429, **{"Retry-After": "7200"})

    feeds = ObservationFeeds(lambda kind, payload, at: None, threading.Event(), http_get=get, monotonic_ns=lambda: 100)
    assert feeds.poll_madis("KMDW") == 7200
    assert feeds.poll_madis("KNYC") == 7200
    assert len(calls) == 1
    feeds = ObservationFeeds(lambda kind, payload, at: None, threading.Event(),
                             http_get=lambda url: response(**{"Cache-Control": "max-age=600"}))
    assert feeds.poll_madis("KMDW") == 600


def test_shutdown_and_missing_station_do_not_fake_observations() -> None:
    stop = threading.Event()
    stop.set()

    def fail(url: str) -> HttpReply:
        pytest.fail("request after stop")

    feeds = ObservationFeeds(lambda kind, payload, at: None, stop, http_get=fail)
    assert feeds.poll_madis("KMDW") == 60
    events: list[dict[str, Any]] = []
    feeds = ObservationFeeds(lambda kind, payload, at: events.append({"kind": kind, **payload}),
                             threading.Event(), http_get=lambda url: response("<mesonet/>"))
    feeds.poll_madis("KMDW")
    assert not any(row["kind"] == "weather_observation" for row in events)
    assert events[-1]["status"] == "no_observation"


@pytest.mark.parametrize("text", [" " * 200_001, '<mesonet><!--' + '"' * 150_000 + '--></mesonet>'])
def test_raw_document_over_journal_budget_is_not_emitted(text: str) -> None:
    events: list[dict[str, Any]] = []
    feeds = ObservationFeeds(lambda kind, payload, at: events.append({"kind": kind, **payload}),
                             threading.Event(), http_get=lambda url: response(text))
    feeds.poll_madis("KMDW")
    assert len(events) == 1 and events[0]["kind"] == "weather_source_status"
    assert events[0]["status"] == "error"

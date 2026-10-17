"""Fake-only observation precision, provenance, source isolation and rate tests."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, ClassVar, Self

import pytest
import requests

from nightcrawler import weatherwatch_observations as obs

VALID = datetime(2026, 10, 12, 12, 53, tzinfo=UTC).timestamp()
RAW = "METAR KMDW 121253Z AUTO 22005KT 10SM CLR 21/15 A2992 RMK AO2 T02060150 P0001"


def collect(events: list[dict[str, Any]]) -> Any:
    return lambda kind, payload, at: events.append({"kind": kind, **payload})

def reply(body: Any = None, *, status: int = 200, headers: dict[str, str] | None = None) -> obs.HttpReply:
    return obs.HttpReply(status, headers or {}, json.dumps(body).encode(), VALID + 59, VALID + 60,
                         1_000_000_000, 2_000_000_000)


def awc(raw: str = RAW, **overrides: Any) -> dict[str, Any]:
    return {"icaoId": "KMDW", "rawOb": raw, "obsTime": VALID, "temp": 20.6,
            "receiptTime": "2026-10-12T12:53:12.125Z", "reportTime": "2026-10-12T13:00:00Z",
            "metarType": "METAR", "qcField": 4, **overrides}


def nws(raw: str = RAW, *, qc: str = "V", rain_qc: str = "V") -> dict[str, Any]:
    return {"properties": {"stationId": "KMDW", "timestamp": "2026-10-12T12:53:00Z",
                            "rawMessage": raw, "temperature": {"unitCode": "wmoUnit:degC",
                                                                     "value": 20.6, "qualityControl": qc},
                            "precipitationLastHour": {"qualityControl": rain_qc}}}


def parsed_awc(raw: str = RAW, **overrides: Any) -> dict[str, Any]:
    return obs.parse_awc([awc(raw, **overrides)], {"KMDW"}, reply(), "clock-test")[0]


def test_precision_is_bound_from_actual_current_t_group() -> None:
    event = parsed_awc()
    assert event["temperature_c"] == 20.6
    assert event["temperature_precision_c"] == 0.1
    assert event["lower_f"] == pytest.approx(68.99)
    assert event["upper_f"] == pytest.approx(69.17)
    assert event["temperature_precision"] == "metar_current_t_group"


def test_whole_celsius_keeps_wider_bounds_without_precise_t_group() -> None:
    event = parsed_awc(RAW.replace(" T02060150", ""), temp=21)
    assert event["temperature_precision_c"] == 1
    assert event["lower_f"] == pytest.approx(68.9)
    assert event["upper_f"] == pytest.approx(70.7)


@pytest.mark.parametrize("raw,expected", [
    ("KMDW 121253Z M02/M03 RMK T10171030", -1.7),
    ("KMDW 121253Z M02/M03", -2),
    ("KMDW 121253Z 00/00 RMK T10001000", 0),
    ("KMDW 121253Z 21/15 RMK T0206////", 20.6),
])
def test_negative_zero_missing_dewpoint_and_rounded_temperatures(raw: str, expected: float) -> None:
    assert obs.temperature_bounds(raw)["temperature_c"] == expected


@pytest.mark.parametrize("raw", [
    "KMDW 121253Z ///// RMK 10206 20201",  # Six-hour extremes are not current temperature.
    "KMDW 121253Z 21/15 RMK T02060150 T02100150",
    "KMDW 121253Z 21/15 22/15",
    "KMDW 121253Z 99/15",
])
def test_missing_ambiguous_and_invalid_temperatures_have_no_bounds(raw: str) -> None:
    assert obs.temperature_bounds(raw)["lower_f"] is None


def test_three_distinct_source_times_are_never_substituted() -> None:
    event = parsed_awc()
    assert event["valid_at"] == VALID
    assert event["provider_received_at"] == VALID + 12.125
    assert event["provider_report_at"] == VALID + 420
    assert event["received_at"] == VALID + 60
    assert event["requested_at"] == VALID + 59
    assert event["data_latency_s"] == 60
    assert event["publication_at"] is None
    assert event["receipt_monotonic_ns"] == 2_000_000_000
    assert event["receipt_clock_id"] == "clock-test"
    assert event["resolution_s"] is None
    assert event["independent_1m"] is False
    assert event["climate_day"] is None
    assert event["final_settlement_source"] is False


def test_same_metar_from_two_sources_cannot_be_two_independent_readings() -> None:
    first = parsed_awc()
    second = obs.parse_nws(nws(), "KMDW", reply(), "clock-test")[0]
    assert first["observation_id"] != second["observation_id"]
    assert first["independent_id"] == second["independent_id"]


def test_same_reading_identity_survives_provider_metadata_revision_and_new_receipt() -> None:
    first = parsed_awc()
    second = parsed_awc(receiptTime="2026-10-12T12:53:20Z", qcField=0)
    third = obs.parse_awc([awc()], {"KMDW"}, replace(reply(), received_at=VALID + 120), "new-clock")[0]
    assert first["observation_id"] == second["observation_id"] == third["observation_id"]
    assert first["revision_id"] != second["revision_id"]
    assert third["received_at"] == VALID + 120  # Durable runner retains original first receipt.
    corrected = parsed_awc(RAW.replace("T02060150", "T01860150"), temp=18.6)
    assert first["observation_id"] == corrected["observation_id"]
    assert first["revision_id"] != corrected["revision_id"]


@pytest.mark.parametrize("raw,flag", [
    (RAW + " $", "maintenance_indicator"),
    (RAW.replace("METAR KMDW", "METAR COR KMDW"), "corrected_report"),
    (RAW.replace("KMDW", "KORD"), "station_mismatch"),
    (RAW.replace("121253Z", "111253Z"), "report_time_mismatch"),
    (RAW.replace("121253Z", "126353Z"), "report_time_mismatch"),
    (RAW + " NIL", "missing_report"),
])
def test_flagged_or_mismatched_reports_cannot_confirm(raw: str, flag: str) -> None:
    event = parsed_awc(raw)
    assert event["quality"] == "suspect"
    assert flag in event["quality_flags"]


@pytest.mark.parametrize("qc", ["Q", "X", "B"])
def test_known_failed_nws_temperature_qc_is_suspect(qc: str) -> None:
    event = obs.parse_nws(nws(qc=qc), "KMDW", reply(), "clock")[0]
    assert event["quality"] == "suspect"
    assert event["provider_quality"] == "suspect"


def test_unknown_provider_qc_is_retained_not_claimed_verified() -> None:
    event = parsed_awc(qcField=14)
    assert event["provider_quality"] == "unknown"
    assert event["provider_qc_field"] == 14
    assert event["quality_scope"] == "raw_report_checks_not_sensor_certification"
    assert obs.parse_nws(nws(qc="Z"), "KMDW", reply(), "clock")[0]["provider_quality"] == "unknown"


@pytest.mark.parametrize("bad_reply,flag", [
    (replace(reply(), received_at=VALID - 1), "future_observation_clock"),
    (replace(reply(), requested_at=VALID + 70), "local_clock_reversed"),
    (replace(reply(), request_monotonic_ns=3_000_000_000), "local_clock_reversed"),
])
def test_clock_anomalies_are_ineligible_and_latency_unknown(bad_reply: obs.HttpReply, flag: str) -> None:
    event = obs.parse_awc([awc()], {"KMDW"}, bad_reply, "clock")[0]
    assert event["quality"] == "suspect"
    assert event["data_latency_s"] is None
    assert flag in event["quality_flags"]


def test_provider_and_raw_temperature_disagreement_is_suspect() -> None:
    event = parsed_awc(temp=25)
    assert event["quality"] == "suspect"
    assert "provider_temperature_conflicts_with_raw" in event["quality_flags"]


def test_other_station_unparseable_or_unzoned_times_are_ignored() -> None:
    assert obs.parse_awc([awc(icaoId="KORD")], {"KMDW"}, reply(), "clock") == []
    assert obs.parse_awc([awc(obsTime=True)], {"KMDW"}, reply(), "clock") == []
    assert obs.parse_awc([awc(rawOb=None)], {"KMDW"}, reply(), "clock") == []
    wrong = nws()
    wrong["properties"]["timestamp"] = "2026-10-12T12:53:00"
    assert obs.parse_nws(wrong, "KMDW", reply(), "clock") == []
    wrong = nws()
    wrong["properties"]["stationId"] = "KORD"
    assert obs.parse_nws(wrong, "KMDW", reply(), "clock") == []


def test_nws_station_url_is_accepted_only_for_exact_documented_origin() -> None:
    body = nws()
    body["properties"].pop("stationId")
    body["properties"]["station"] = "https://api.weather.gov/stations/KMDW"
    assert len(obs.parse_nws(body, "KMDW", reply(), "clock")) == 1
    body["properties"]["station"] = "https://example.com/stations/KMDW"
    assert obs.parse_nws(body, "KMDW", reply(), "clock") == []


def test_hourly_precipitation_retains_interval_units_and_rounding() -> None:
    event = parsed_awc()
    assert event["interval_start"] == VALID - 3600
    assert event["interval_end"] == VALID
    assert event["amount_lower"] == .005
    assert event["amount_upper"] == .015
    assert event["amount_units"] == "inches"
    assert event["interval_complete"] is True
    assert event["trace"] is False


def test_trace_and_missing_rain_are_not_counted_as_zero_or_measurable_positive() -> None:
    trace = parsed_awc(RAW.replace("P0001", "P0000"))
    assert trace["trace"] is True
    assert trace["amount_lower"] == 0
    assert trace["amount_upper"] == .005
    for raw in [RAW.replace(" P0001", ""), RAW.replace("P0001", "P////"), RAW + " PNO", RAW + " P0002"]:
        missing = parsed_awc(raw)
        assert missing["amount_lower"] is None
        assert missing["interval_complete"] is False
        assert missing["trace"] is None


@pytest.mark.parametrize("raw,kind", [(RAW.replace("METAR", "SPECI"), "SPECI"), (RAW, "SPECI")])
def test_speci_cannot_claim_full_hour_even_without_prefix(raw: str, kind: str) -> None:
    assert parsed_awc(raw, metarType=kind)["interval_complete"] is False


@pytest.mark.parametrize("qc", ["Q", "X", "B"])
def test_bad_nws_rain_qc_cannot_confirm_rain(qc: str) -> None:
    event = obs.parse_nws(nws(rain_qc=qc), "KMDW", reply(), "clock")[0]
    assert event["interval_complete"] is False
    assert event["precipitation_quality"] == "suspect"
    assert "provider_precipitation_qc_suspect" in event["quality_flags"]


def test_cache_headers_age_dates_and_expires_are_respected() -> None:
    assert obs.cache_delay({"Cache-Control": "public, max-age=300, s-maxage=300"}, VALID) == 300
    assert obs.cache_delay({"Cache-Control": "max-age=60", "Age": "20"}, VALID) == 40
    assert obs.cache_delay({"Cache-Control": "max-age=60", "Date": "Mon, 12 Oct 2026 12:52:30 GMT"}, VALID) == 30
    assert obs.cache_delay({"Expires": "Mon, 12 Oct 2026 12:54:00 GMT"}, VALID) == 60
    assert obs.cache_delay({"Cache-Control": "max-age=0"}, VALID) == 5


def test_retry_after_never_truncates_long_delays() -> None:
    assert obs.retry_after({"Retry-After": "7200"}, VALID) == 7200
    assert obs.retry_after({"Retry-After": "Tue, 13 Oct 2026 12:53:00 GMT"}, VALID) == 86400
    assert obs.retry_after({"Retry-After": "nonsense"}, VALID) == 60


def test_only_verified_exact_station_specs_are_queried() -> None:
    feeds = obs.ObservationFeeds(lambda kind, payload, at: None, threading.Event(), lambda: [
        {"station": "KMDW", "station_verified": True},
        {"station": "KMDW", "station_verified": True},
        {"station": "KNYC", "station_verified": False},
        {"station": "KORD"}, {"station": "KMDW/../../evil", "station_verified": True},
        {"station": "Central Park", "station_verified": True},
    ])
    assert feeds.stations() == ["KMDW"]


def test_poll_batches_only_public_gets_and_preserves_cache_floor() -> None:
    urls: list[str] = []
    events: list[dict[str, Any]] = []

    def get(url: str) -> obs.HttpReply:
        urls.append(url)
        return reply([awc()], headers={"Cache-Control": "max-age=60"})

    feeds = obs.ObservationFeeds(collect(events), threading.Event(), http_get=get, receipt_clock_id="process-id")
    assert feeds.poll_once("aviationweather", ["KMDW", "KNYC"]) == 60
    assert urls == ["https://aviationweather.gov/api/data/metar?ids=KMDW%2CKNYC&format=json"]
    assert events[0]["kind"] == "weather_observation"
    assert events[-1]["missing_stations"] == ["KNYC"]
    assert events[-1]["mode"] == "read_only"
    assert "key" not in urls[0].lower()


def test_429_blocks_other_stations_on_same_origin_but_not_other_origin() -> None:
    calls: list[str] = []
    events: list[dict[str, Any]] = []

    def get(url: str) -> obs.HttpReply:
        calls.append(url)
        return reply(status=429, headers={"Retry-After": "7200"})

    feeds = obs.ObservationFeeds(collect(events), threading.Event(), http_get=get, monotonic_ns=lambda: 100)
    assert feeds.poll_once("nws", ["KMDW"]) == 7200
    assert feeds.poll_once("nws", ["KNYC"]) == 7200
    assert len(calls) == 1
    feeds.poll_once("aviationweather", ["KNYC"])
    assert len(calls) == 2
    assert events[0]["reason"] == "retry_after_honored"


@pytest.mark.parametrize("status", [403, 404, 451])
def test_unavailable_sources_are_reported_without_workarounds(status: int) -> None:
    events: list[dict[str, Any]] = []
    feeds = obs.ObservationFeeds(collect(events), threading.Event(), http_get=lambda url: reply(status=status))
    assert feeds.poll_once("nws", ["KMDW"]) >= 3600
    assert events[-1]["status"] == "unavailable"
    assert events[-1]["reason"] == f"http_{status}_no_workaround"


def test_failure_backoff_never_logs_exception_details_or_fakes_readings() -> None:
    events: list[dict[str, Any]] = []

    def fail(url: str) -> obs.HttpReply:
        raise requests.Timeout("never-log-this-detail")

    feeds = obs.ObservationFeeds(collect(events), threading.Event(), http_get=fail)
    assert feeds.poll_once("nws", ["KMDW"]) == 10
    assert feeds.poll_once("nws", ["KMDW"]) == 20
    assert all(event["kind"] == "weather_source_status" for event in events)
    assert "never-log" not in json.dumps(events)


def test_shutdown_prevents_request_and_invalid_station_is_not_interpolated() -> None:
    def fail(url: str) -> obs.HttpReply:
        pytest.fail("unexpected request")

    stop = threading.Event()
    feeds = obs.ObservationFeeds(lambda kind, payload, at: None, stop, http_get=fail)
    with pytest.raises(ValueError, match="unvalidated_weather_station"):
        feeds.poll_once("nws", ["KMDW?secret=value"])
    stop.set()
    feeds.poll_once("nws", ["KMDW"])


def test_no_archival_one_minute_feed_is_claimed_live() -> None:
    stop = threading.Event()
    stop.set()
    events: list[dict[str, Any]] = []
    feeds = obs.ObservationFeeds(collect(events), stop)
    asyncio.run(feeds.run())
    assert len(events) == 1
    assert events[0]["source"] == "asos_1minute"
    assert events[0]["status"] == "unavailable"
    assert events[0]["archive_is_live_confirmation"] is False


def test_http_transport_is_get_only_no_redirects_and_captures_before_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"Cache-Control": "max-age=60"}

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def iter_content(self, size: int) -> Any:
            yield b"[]"

    calls: list[dict[str, Any]] = []

    def get(url: str, **kwargs: Any) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(obs.requests, "get", get)
    clock = iter([100.0, 102.0])
    mono = iter([100, 101, 102])
    feeds = obs.ObservationFeeds(lambda kind, payload, at: None, threading.Event(), clock=lambda: next(clock),
                                 monotonic_ns=lambda: next(mono))
    got = feeds._get(obs.AWC)
    assert got.requested_at == 100
    assert got.received_at == 102
    assert got.body == b"[]"
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["stream"] is True
    assert "Authorization" not in calls[0]["headers"]

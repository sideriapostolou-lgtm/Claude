"""Public weather receipts for the read-only lock stopwatch; no order clients.

Stations must come from verified contract rules, never a city-name lookup here.
The clocks describe when this process received a report, not when its publisher
first made it public. The runner journals/deduplicates observation IDs durably.

Provider documentation checked 2026-10-12:
* https://aviationweather.gov/data/api/ (100 requests/minute; METAR cache 1/min)
* https://aviationweather.gov/data/schema/openapi.yaml
* https://www.weather.gov/documentation/services-web-api (undisclosed limit;
  cache-friendly; upstream MADIS QC can delay observations by 20 minutes)
* https://madis.ncep.noaa.gov/madis_sfc_qc_notes.shtml (QC descriptors)
* https://mesonet.agron.iastate.edu/request/asos/1min.phtml (NCEI archive,
  available only through yesterday in the probe; not a verified live feed).
* https://madis.ncep.noaa.gov/madis_OMO.shtml (public 1-minute OMO data,
  processed every five minutes). Its public guest XML viewer's ASOS-HFM probe
  returned only five-minute KMDW observations; native 1-minute access has not
  yet been verified. That limitation is not a claim that OMO data do not exist.

Current probes returned max-age=60 from AWC and max-age=300 from NWS. We honor
cache lifetimes and Retry-After, use no cache-busting query, and never silently
call an archival minute value a live independent confirmation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Any
from urllib.parse import urlencode

import requests

from .weatherwatch_cli import CLI_TOKEN, PRODUCT_ID, parse_cli
from .weatherwatch_madis import madis_url, parse_madis

NWS = "https://api.weather.gov"
AWC = "https://aviationweather.gov/api/data/metar"
USER_AGENT = "nightcrawler-weatherwatch/1.0 (public read-only weather latency research)"
STATION = re.compile(r"[A-Z][A-Z0-9]{3}\Z")
TG = re.compile(r"T([01])(\d{3})(?:[01]\d{3}|////)\Z")
BODY_TEMP = re.compile(r"(M?\d{2})/(?:M?\d{2}|//)\Z")
RAW_TIME = re.compile(r"(\d{2})(\d{2})(\d{2})Z\Z")
PRECIP = re.compile(r"P(\d{4})\Z")
MIN_POLL_SECONDS = 5.0
MAX_BODY_BYTES = 2_000_000


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return _number(value)
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.timestamp() if dt.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _qc(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) <= 16 else None


def _header_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def retry_after(headers: dict[str, str], now: float, default: float = 60.0) -> float:
    """Never shorten a provider cooldown, including a long HTTP-date delay."""
    normalized = {k.lower(): v for k, v in headers.items()}
    raw = normalized.get("retry-after", "")
    number = _number(raw)
    if number is not None and number >= 0:
        return max(MIN_POLL_SECONDS, number)
    at = _header_time(raw)
    return max(MIN_POLL_SECONDS, at - now) if at is not None else default


def cache_delay(headers: dict[str, str], now: float) -> float:
    normalized = {k.lower(): v for k, v in headers.items()}
    control = normalized.get("cache-control", "").lower()
    found = re.search(r"(?:^|,)\s*max-age\s*=\s*\"?(\d+)", control)
    age = max(0.0, _number(normalized.get("age")) or 0.0)
    date = _header_time(normalized.get("date"))
    if date is not None:
        age = max(age, max(0.0, now - date))
    if found:
        return max(MIN_POLL_SECONDS, float(found.group(1)) - age)
    expires = _header_time(normalized.get("expires"))
    return max(MIN_POLL_SECONDS, expires - now) if expires else MIN_POLL_SECONDS


@dataclass(frozen=True)
class HttpReply:
    status: int
    headers: dict[str, str]
    body: bytes
    requested_at: float
    received_at: float
    request_monotonic_ns: int
    receipt_monotonic_ns: int


def _raw_parts(raw: str, station: str, valid_at: float) -> tuple[list[str], list[str]]:
    words = raw.strip().rstrip("=").split()
    flags: list[str] = []
    header = words[:5]
    # A station token elsewhere in remarks does not authenticate the report.
    station_index = next((i for i, value in enumerate(header) if value == station), None)
    if station_index is None or any(x not in {"METAR", "SPECI", "COR"}
                                    for x in header[:station_index]):
        flags.append("station_mismatch")
    stamp = next((RAW_TIME.fullmatch(word) for word in header
                  if RAW_TIME.fullmatch(word)), None)
    try:
        dt = datetime.fromtimestamp(valid_at, UTC)
        if stamp is None or tuple(map(int, stamp.groups())) != (dt.day, dt.hour, dt.minute):
            flags.append("report_time_mismatch")
    except (ValueError, OverflowError, OSError):
        flags.append("report_time_invalid")
    if "$" in words:
        flags.append("maintenance_indicator")
    if "COR" in header:
        flags.append("corrected_report")
    if "NIL" in words:
        flags.append("missing_report")
    return words, flags


def temperature_bounds(raw: str) -> dict[str, Any]:
    """Preserve reported Celsius precision instead of treating rounded F as exact."""
    words = raw.strip().rstrip("=").split()
    try:
        remark_index = words.index("RMK")
    except ValueError:
        remark_index = len(words)
    tgroups = [TG.fullmatch(word) for word in words[remark_index + 1:]
               if TG.fullmatch(word)]
    value: Decimal | None = None
    quantum: Decimal | None = None
    precision = "unknown"
    if len(tgroups) == 1 and tgroups[0] is not None:
        sign, magnitude = tgroups[0].groups()
        value = Decimal(magnitude) / 10 * (-1 if sign == "1" else 1)
        quantum, precision = Decimal("0.1"), "metar_current_t_group"
    elif not tgroups:
        matches = [BODY_TEMP.fullmatch(word) for word in words[:remark_index]
                   if BODY_TEMP.fullmatch(word)]
        if len(matches) == 1 and matches[0] is not None:
            text = matches[0].group(1)
            value = Decimal(text.replace("M", "-"))
            quantum, precision = Decimal(1), "metar_whole_celsius"
    if value is None or quantum is None or not Decimal(-100) <= value <= Decimal(70):
        return {"temperature_c": None, "lower_f": None, "upper_f": None,
                "temperature_precision_c": None, "temperature_precision": "unknown"}
    lower, upper = value - quantum / 2, value + quantum / 2
    return {"temperature_c": float(value), "temperature_precision_c": float(quantum),
            "temperature_precision": precision, "temperature_lower_c": float(lower),
            "temperature_upper_c": float(upper), "lower_f": float(lower * 9 / 5 + 32),
            "upper_f": float(upper * 9 / 5 + 32), "temperature_bounds_inclusive": True}


def precipitation(raw: str, valid_at: float) -> dict[str, Any]:
    """One-hour P group only. Absent, trace and measured zero are not synonyms.

    The bounds concern the reported amount, not sensor error. A SPECI may not
    establish a full rolling hour, and no interval spanning a climate boundary
    can be silently assigned to one climate date by the model.
    """
    words = raw.strip().rstrip("=").split()
    remarks = words[words.index("RMK") + 1:] if "RMK" in words else []
    groups = [PRECIP.fullmatch(word) for word in remarks if PRECIP.fullmatch(word)]
    missing = {"interval_start": None, "interval_end": None, "amount_lower": None,
               "amount_upper": None, "amount_units": "inches", "interval_complete": False,
               "precipitation_status": "missing", "trace": None,
               "precipitation_period": "unknown"}
    if "PNO" in remarks or len(groups) != 1 or groups[0] is None:
        return missing
    amount = Decimal(groups[0].group(1)) / 100
    trace = amount == 0
    return {"interval_start": valid_at - 3600, "interval_end": valid_at,
            "amount_lower": float(max(Decimal(0), amount - Decimal("0.005"))),
            "amount_upper": float(amount + Decimal("0.005")), "amount_units": "inches",
            "interval_complete": "SPECI" not in words[:2],
            "precipitation_status": "trace" if trace else "measured",
            "precipitation_period": "reported_rolling_hour", "trace": trace,
            "reported_precipitation_in": float(amount), "precipitation_bounds_inclusive": True}


def _observation(source: str, station: str, valid_at: float, raw: str, reply: HttpReply,
                 clock_id: str, provider: dict[str, Any]) -> dict[str, Any]:
    _, flags = _raw_parts(raw, station, valid_at)
    bounds = temperature_bounds(raw)
    rain = precipitation(raw, valid_at)
    if valid_at > reply.received_at:
        flags.append("future_observation_clock")
    if reply.received_at < reply.requested_at or reply.receipt_monotonic_ns < reply.request_monotonic_ns:
        flags.append("local_clock_reversed")
    qc = provider.get("temperature_quality_control")
    if qc in {"Q", "X", "B"}:
        flags.append("provider_temperature_qc_suspect")
    quality = "suspect" if flags else "accepted"
    # AWC's numeric qcField has no bit definitions in the current OpenAPI.
    # Preserve it, but don't promote unknown provider QC to a passed QC test.
    provider_quality = ("accepted" if qc in {"V", "S", "C", "G"} else
                        "suspect" if qc in {"Q", "X", "B"} else "unknown")
    if bounds["temperature_c"] is None:
        quality = "unknown" if not flags else "suspect"
    reported_c = _number(provider.get("provider_temperature_c"))
    if (reported_c is not None and bounds["temperature_c"] is not None
            and not bounds["temperature_lower_c"] - 1e-8 <= reported_c <= bounds["temperature_upper_c"] + 1e-8):
        flags.append("provider_temperature_conflicts_with_raw")
        quality = "suspect"
    if provider.get("provider_precipitation_quality_control") in {"Q", "X", "B"}:
        flags.append("provider_precipitation_qc_suspect")
        rain["interval_complete"] = False
    if provider.get("provider_metar_type") == "SPECI":
        rain["interval_complete"] = False
    rain["precipitation_quality"] = ("suspect" if flags else "accepted"
                                      if rain["interval_complete"] else "unknown")
    identity = hashlib.sha256(json.dumps([source, station, valid_at],
                                        separators=(",", ":")).encode()).hexdigest()
    revision = hashlib.sha256(json.dumps([identity, raw, provider], sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    latency = reply.received_at - valid_at
    return {"kind": "weather_observation", "source": source, "station": station,
            "valid_at": valid_at, "requested_at": reply.requested_at, "received_at": reply.received_at,
            "request_monotonic_ns": reply.request_monotonic_ns,
            "receipt_monotonic_ns": reply.receipt_monotonic_ns, "receipt_clock_id": clock_id,
            "observation_id": source + ":" + identity,
            "revision_id": source + ":" + revision,
            "independent_id": f"metar:{station}:{valid_at:.0f}",
            "raw_report": raw, "quality": quality, "quality_flags": flags,
            "quality_scope": "raw_report_checks_not_sensor_certification",
            "provider_quality": provider_quality, "resolution_s": None, "independent_1m": False,
            "data_latency_s": latency if latency >= 0 and "local_clock_reversed" not in flags else None,
            "latency_scope": "observation_valid_time_to_local_response_body_receipt",
            "publication_at": None, "climate_day": None, "final_settlement_source": False,
            **bounds, **rain, **provider}


def parse_awc(body: Any, stations: set[str], reply: HttpReply, clock_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in body if isinstance(body, list) else []:
        if not isinstance(row, dict) or row.get("icaoId") not in stations:
            continue
        station, valid_at, raw = row["icaoId"], _timestamp(row.get("obsTime")), row.get("rawOb")
        if valid_at is None or valid_at <= 0 or not isinstance(raw, str) or len(raw) > 4096:
            continue
        out.append(_observation("aviationweather", station, valid_at, raw, reply, clock_id,
                                {"provider_received_at": _timestamp(row.get("receiptTime")),
                                 "provider_report_at": _timestamp(row.get("reportTime")),
                                 "provider_temperature_c": _number(row.get("temp")),
                                 "temperature_quality_control": None,
                                 "provider_qc_field": _number(row.get("qcField")),
                                 "provider_metar_type": _qc(row.get("metarType"))}))
    return out


def parse_nws(body: Any, station: str, reply: HttpReply, clock_id: str) -> list[dict[str, Any]]:
    props = body.get("properties") if isinstance(body, dict) else None
    if not isinstance(props, dict):
        return []
    identity = props.get("stationId")
    if identity is None:
        identity = str(props.get("station") or "").removeprefix(NWS + "/stations/")
    valid_at, raw = _timestamp(props.get("timestamp")), props.get("rawMessage")
    if identity != station or valid_at is None or valid_at <= 0 or not isinstance(raw, str) or len(raw) > 4096:
        return []
    temperature = props.get("temperature")
    temperature = temperature if isinstance(temperature, dict) else {}
    value = _number(temperature.get("value")) if temperature.get("unitCode") == "wmoUnit:degC" else None
    return [_observation("nws", station, valid_at, raw, reply, clock_id,
                         {"provider_received_at": None, "provider_report_at": None,
                          "provider_temperature_c": value,
                          "temperature_quality_control": _qc(temperature.get("qualityControl")),
                          "provider_precipitation_quality_control": (
                              _qc(props.get("precipitationLastHour", {}).get("qualityControl"))
                              if isinstance(props.get("precipitationLastHour"), dict) else None)})]


class ObservationFeeds:
    """At most three in-flight public GETs; no credentials, orders or city mapping.

    ``station_provider`` returns contract-discovery dicts with station and
    station_verified=True. The emit callback must journal before applying its
    durable source-ID watermark. Repeated GET responses intentionally retain
    their new receipts; only that durable model decides the first receipt.
    """

    def __init__(self, emit: Callable[[str, dict[str, Any], float], None], stop: threading.Event,
                 station_provider: Callable[[], list[dict[str, Any]]] | None = None, *,
                 clock: Callable[[], float] = time.time,
                 monotonic_ns: Callable[[], int] = time.monotonic_ns,
                 receipt_clock_id: str = "weatherwatch_process",
                 http_get: Callable[[str], HttpReply] | None = None) -> None:
        self.emit, self.stop, self.station_provider = emit, stop, station_provider
        self.clock, self.monotonic_ns, self.clock_id = clock, monotonic_ns, receipt_clock_id
        self.http_get = http_get or self._get
        self.failures: dict[str, int] = {}
        self.source_cooldown: dict[str, float] = {}
        self._nws_lock = asyncio.Lock()
        self._nws_next_ns = 0
        self._madis_bootstrapped: set[str] = set()

    def _emit(self, event: dict[str, Any]) -> None:
        payload = {key: value for key, value in event.items() if key != "kind"}
        received = event.get("received_at")
        self.emit(event["kind"], payload, float(received if received is not None else self.clock()))

    def _get(self, url: str) -> HttpReply:
        requested_at, start_ns = self.clock(), self.monotonic_ns()
        with requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json,application/json"},
                          timeout=(5, 10), allow_redirects=False, stream=True) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                if (self.monotonic_ns() - start_ns) / 1e9 > 20:
                    raise ValueError("weather_response_deadline")
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise ValueError("weather_response_too_large")
                chunks.append(chunk)
            received_at, end_ns = self.clock(), self.monotonic_ns()
            return HttpReply(response.status_code, dict(response.headers), b"".join(chunks),
                             requested_at, received_at, start_ns, end_ns)

    def stations(self) -> list[str]:
        rows = self.station_provider() if self.station_provider else []
        return sorted({row["station"] for row in rows if isinstance(row, dict)
                       and row.get("station_verified") is True
                       and isinstance(row.get("station"), str) and STATION.fullmatch(row["station"])})

    def poll_once(self, source: str, stations: list[str]) -> float:
        """One bounded request, returning the minimum delay before its next poll."""
        if self.stop.is_set() or not stations:
            return MIN_POLL_SECONDS
        cooldown = self.source_cooldown.get(source, 0) - self.monotonic_ns() / 1e9
        if cooldown > 0:
            return cooldown
        if any(not STATION.fullmatch(station) for station in stations):
            raise ValueError("unvalidated_weather_station")
        if source == "nws" and len(stations) == 1:
            url = NWS + f"/stations/{stations[0]}/observations/latest"
        elif source == "aviationweather" and len(stations) <= 64:
            url = AWC + "?" + urlencode({"ids": ",".join(stations), "format": "json"})
        else:
            raise ValueError("invalid_weather_poll")
        failure_key = source + ":" + ",".join(stations)
        status: dict[str, Any] = {"kind": "weather_source_status", "source": source,
                                  "stations": stations, "mode": "read_only", "requested_url": url}
        try:
            reply = self.http_get(url)
            status.update({"requested_at": reply.requested_at, "received_at": reply.received_at,
                           "request_monotonic_ns": reply.request_monotonic_ns,
                           "receipt_monotonic_ns": reply.receipt_monotonic_ns,
                           "receipt_clock_id": self.clock_id, "http_status": reply.status,
                           "cache_control": {k.lower(): v for k, v in reply.headers.items()}.get("cache-control")})
            if reply.status == 429:
                delay = retry_after(reply.headers, reply.received_at)
                self.source_cooldown[source] = self.monotonic_ns() / 1e9 + delay
                status.update(status="rate_limited", reason="retry_after_honored")
            elif reply.status in {403, 404, 451}:
                delay = max(3600.0, retry_after(reply.headers, reply.received_at))
                if reply.status in {403, 451}:
                    self.source_cooldown[source] = self.monotonic_ns() / 1e9 + delay
                status.update(status="unavailable", reason=f"http_{reply.status}_no_workaround")
            elif reply.status not in {200, 204}:
                self.failures[failure_key] = self.failures.get(failure_key, 0) + 1
                delay = max(retry_after(reply.headers, reply.received_at),
                            min(900.0, 5.0 * 2 ** min(8, self.failures[failure_key])))
                status.update(status="error", reason=f"http_{reply.status}")
            else:
                self.failures.pop(failure_key, None)
                body = json.loads(reply.body) if reply.status == 200 else None
                events = (parse_nws(body, stations[0], reply, self.clock_id) if source == "nws"
                          else parse_awc(body, set(stations), reply, self.clock_id))
                for event in events:
                    self._emit(event)
                observed = {event["station"] for event in events}
                delay = cache_delay(reply.headers, reply.received_at)
                status.update(status="ok" if observed else "no_observation", observations=len(events),
                              missing_stations=sorted(set(stations) - observed))
        except (requests.RequestException, ValueError, TypeError, OSError):
            self.failures[failure_key] = self.failures.get(failure_key, 0) + 1
            delay = min(900.0, 5.0 * 2 ** min(8, self.failures[failure_key]))
            # No exception text: network libraries can include surprising request details.
            status.update(status="error", reason="public_weather_request_failed", received_at=self.clock())
        status["next_poll_after_s"] = delay
        self._emit(status)
        return delay

    def cli_stations(self) -> list[tuple[str, str]]:
        rows = self.station_provider() if self.station_provider else []
        return sorted({(row["station"], row["station_rule"]) for row in rows
                       if isinstance(row, dict) and row.get("station_verified") is True
                       and isinstance(row.get("station"), str) and STATION.fullmatch(row["station"])
                       and isinstance(row.get("station_rule"), str) and CLI_TOKEN.fullmatch(row["station_rule"])})

    def poll_madis(self, station: str) -> float:
        url = madis_url(station)
        cooldown = self.source_cooldown.get("madis_hfm", 0) - self.monotonic_ns() / 1e9
        if self.stop.is_set() or cooldown > 0:
            return max(60.0, cooldown)
        status: dict[str, Any] = {"kind": "weather_source_status", "source": "madis_hfm",
                                  "stations": [station], "mode": "read_only", "requested_url": url,
                                  "resolution_s": 300, "independent_1m": False,
                                  "poll_floor_s": 60, "documented_rate_limit": None,
                                  "poll_policy": "bounded_conservative_sampling_not_verified_fastest_possible"}
        try:
            reply = self.http_get(url)
            status.update(requested_at=reply.requested_at, received_at=reply.received_at, http_status=reply.status)
            delay = max(60.0, cache_delay(reply.headers, reply.received_at))
            if reply.status in {429, 403, 451}:
                delay = max(delay, retry_after(reply.headers, reply.received_at),
                            3600.0 if reply.status != 429 else 0)
                self.source_cooldown["madis_hfm"] = self.monotonic_ns() / 1e9 + delay
                status.update(status="rate_limited" if reply.status == 429 else "unavailable",
                              reason="retry_after_honored" if reply.status == 429 else f"http_{reply.status}_no_workaround")
            elif reply.status != 200:
                delay = max(delay, retry_after(reply.headers, reply.received_at))
                status.update(status="unavailable", reason=f"http_{reply.status}")
            else:
                if len(reply.body) > 200_000:
                    raise ValueError("madis_document_exceeds_journal_budget")
                text = reply.body.decode("utf-8")
                if len(json.dumps(text).encode()) > 200_000:
                    raise ValueError("madis_document_exceeds_journal_budget")
                events = parse_madis(text, station, reply, self.clock_id,
                                     left_censored=station not in self._madis_bootstrapped)
                # Raw response evidence is journal-only, separate from the panel's health record.
                self._emit({"kind": "weather_source_document", "source": "madis_hfm", "station": station,
                            "requested_at": reply.requested_at, "received_at": reply.received_at,
                            "receipt_monotonic_ns": reply.receipt_monotonic_ns,
                            "request_monotonic_ns": reply.request_monotonic_ns, "receipt_clock_id": self.clock_id,
                            "requested_url": url, "raw_xml": text})
                for event in events:
                    self._emit(event)
                if events:
                    self._madis_bootstrapped.add(station)
                status.update(status="ok" if events else "no_observation", observations=len(events))
        except (requests.RequestException, ValueError, TypeError, OSError):
            delay = 60.0
            status.update(status="error", reason="public_madis_request_failed", received_at=self.clock())
        status["next_poll_after_s"] = delay
        self._emit(status)
        return delay

    def poll_cli(self, station: str, station_rule: str, product_id: str | None = None) -> tuple[float, list[str]]:
        """Read an official CLI index or a product; never treat an index as a report."""
        if not STATION.fullmatch(station) or not CLI_TOKEN.fullmatch(station_rule):
            raise ValueError("unvalidated_cli_station")
        if product_id is not None and not PRODUCT_ID.fullmatch(product_id):
            raise ValueError("unvalidated_cli_product")
        cooldown = self.source_cooldown.get("nws", 0) - self.monotonic_ns() / 1e9
        if self.stop.is_set() or cooldown > 0:
            return max(MIN_POLL_SECONDS, cooldown), []
        url = (NWS + "/products/" + product_id if product_id else
               NWS + "/products/types/CLI/locations/" + station_rule[3:])
        status: dict[str, Any] = {"kind": "weather_source_status", "source": "nws_cli",
                                  "stations": [station], "station_rule": station_rule,
                                  "mode": "read_only", "requested_url": url}
        ids: list[str] = []
        try:
            response = self.http_get(url)
            status.update(requested_at=response.requested_at, received_at=response.received_at,
                          http_status=response.status, receipt_clock_id=self.clock_id,
                          request_monotonic_ns=response.request_monotonic_ns,
                          receipt_monotonic_ns=response.receipt_monotonic_ns)
            delay = max(300.0 if product_id is None else 3600.0,
                        cache_delay(response.headers, response.received_at))
            if response.status == 429:
                delay = retry_after(response.headers, response.received_at)
                self.source_cooldown["nws"] = self.monotonic_ns() / 1e9 + delay
                status.update(status="rate_limited", reason="retry_after_honored")
            elif response.status in {403, 404, 451}:
                delay = max(3600.0, retry_after(response.headers, response.received_at))
                if response.status in {403, 451}:
                    self.source_cooldown["nws"] = self.monotonic_ns() / 1e9 + delay
                status.update(status="unavailable", reason=f"http_{response.status}_no_workaround")
            elif response.status != 200:
                delay = max(delay, retry_after(response.headers, response.received_at))
                status.update(status="error", reason=f"http_{response.status}")
            else:
                body = json.loads(response.body)
                if product_id:
                    event = parse_cli(body, station, station_rule, response, self.clock_id)
                    if event is not None and event["report_id"] == product_id:
                        self._emit(event)
                        status.update(status="ok", observations=1)
                    else:
                        status.update(status="unparsed", reason="exact_cli_station_or_format_not_verified")
                else:
                    rows = body.get("@graph") if isinstance(body, dict) else None
                    rows = rows if isinstance(rows, list) else []
                    for row in rows:
                        if (isinstance(row, dict) and row.get("productCode") == "CLI"
                                and isinstance(row.get("id"), str) and PRODUCT_ID.fullmatch(row["id"])
                                and row["id"] not in ids):
                            ids.append(row["id"])
                    status.update(status="index_only" if ids else "no_reports", product_count=len(ids),
                                  index_truncated=len(ids) > 64)
                    ids = ids[:64]
        except (requests.RequestException, ValueError, TypeError, OSError):
            delay = 300.0
            status.update(status="error", reason="public_cli_request_failed", received_at=self.clock())
        status["next_poll_after_s"] = delay
        self._emit(status)
        return delay, ids

    async def _nws_call(self, function: Callable[[], Any]) -> Any:
        # CLI and observations share one request slot/rate budget on api.weather.gov.
        async with self._nws_lock:
            wait = (self._nws_next_ns - self.monotonic_ns()) / 1e9
            if wait > 0:
                await asyncio.sleep(wait)
            result = await asyncio.to_thread(function)
            self._nws_next_ns = self.monotonic_ns() + 1_000_000_000
            return result

    async def _cli_loop(self) -> None:
        indices: dict[tuple[str, str], float] = {}
        products: dict[tuple[str, str, str], float] = {}
        while not self.stop.is_set():
            stations = self.cli_stations()
            now = self.monotonic_ns() / 1e9
            index = next((key for key in stations if indices.get(key, 0) <= now), None)
            product = next((key for key, due in products.items() if due <= now), None)
            if index:
                delay, ids = await self._nws_call(partial(self.poll_cli, *index))
                indices[index] = self.monotonic_ns() / 1e9 + delay
                for identity in ids:
                    products.setdefault((*index, identity), 0)
                if ids:
                    products = {key: due for key, due in products.items()
                                if key[:2] != index or key[2] in ids}
            elif product:
                delay, _ = await self._nws_call(partial(self.poll_cli, *product))
                products[product] = self.monotonic_ns() / 1e9 + delay
            indices = {key: due for key, due in indices.items() if key in stations}
            products = {key: due for key, due in products.items() if key[:2] in stations}
            await asyncio.sleep(1)

    async def _loop(self, source: str) -> None:
        due: dict[tuple[str, ...], float] = {}
        while not self.stop.is_set():
            stations = self.stations()
            width = 64 if source == "aviationweather" else 1
            batches = [tuple(stations[i:i + width]) for i in range(0, len(stations), width)]
            now = self.monotonic_ns() / 1e9
            ready = next((batch for batch in batches if due.get(batch, 0) <= now), None)
            if ready:
                if source == "nws":
                    delay = await self._nws_call(partial(self.poll_once, source, list(ready)))
                elif source == "madis_hfm":
                    delay = await asyncio.to_thread(self.poll_madis, ready[0])
                else:
                    delay = await asyncio.to_thread(self.poll_once, source, list(ready))
                due[ready] = self.monotonic_ns() / 1e9 + delay
            due = {batch: deadline for batch, deadline in due.items() if batch in batches}
            # Each origin gets <=60 requests/min, below AWC's documented100.
            # Cache and Retry-After delays are additionally applied per request.
            await asyncio.sleep(1)

    async def run(self, station_provider: Callable[[], list[dict[str, Any]]] | None = None) -> None:
        if station_provider is not None:
            self.station_provider = station_provider
        self._emit({"kind": "weather_source_status", "source": "asos_1minute", "status": "unavailable",
                   "reason": "no_verified_public_realtime_one_minute_feed", "received_at": self.clock(),
                   "archive_url": "https://mesonet.agron.iastate.edu/request/asos/1min.phtml",
                   "public_omo_documentation": "https://madis.ncep.noaa.gov/madis_OMO.shtml",
                   "public_guest_hfm_capability": "five_minute_observations_only_in_verified_probe",
                   "archive_is_live_confirmation": False, "independent_1m": False})
        await asyncio.gather(self._loop("nws"), self._loop("aviationweather"), self._cli_loop(),
                             self._loop("madis_hfm"))

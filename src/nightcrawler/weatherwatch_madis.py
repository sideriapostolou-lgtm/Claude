"""Public MADIS guest ASOS-HFM observations, verified at five-minute cadence.

The guest form documents station/provider selection and recwin=4 (all records):
https://madis-data.ncep.noaa.gov/public/sfcdumpguest.shtml
https://madis-data.ncep.noaa.gov/timeSelection.html
https://madis-data.ncep.noaa.gov/providerSelection.html

Surface variable notes document Kelvin and whole-C primary temperature, distinct
from tenths-C remark variables: https://madis.ncep.noaa.gov/sfc_OMO_variable_list.shtml
That doesn't establish access to native 1-minute OMO through this guest viewer.
The 2026-10-12 exact-KMDW probe returned only 5-minute ASOS-HFM records.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

if TYPE_CHECKING:
    from .weatherwatch_observations import HttpReply

MADIS = "https://madis-data.ncep.noaa.gov/madisPublic1/cgi-bin/madisXmlPublicDir"


def madis_url(station: str) -> str:
    if not re.fullmatch(r"[A-Z][A-Z0-9]{3}", station):
        raise ValueError("invalid_madis_station")
    return MADIS + "?" + urlencode({"rdr": "", "time": "0", "minbck": "-30", "minfwd": "0",
                                    "recwin": "4", "timefilter": "0", "dfltrsel": "3",
                                    "stanam": station, "stasel": "1", "pvdrsel": "1", "pvd": "ASOS-HFM",
                                    "varsel": "2", "qctype": "0", "qcsel": "0", "xml": "1", "csvmiss": "0"})


def parse_madis(text: str, station: str, reply: HttpReply, clock_id: str, *,
                left_censored: bool) -> list[dict[str, Any]]:
    if len(text) > 500_000 or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("invalid_madis_xml")
    try:
        document = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("invalid_madis_xml") from exc
    if document.tag != "mesonet":
        raise ValueError("invalid_madis_document")
    out: list[dict[str, Any]] = []
    for record in document.findall("record"):
        row = record.attrib
        if row.get("provider") != "ASOS-HFM" or row.get("shef_id") != station or row.get("var") != "V-T":
            continue
        raw_time = row.get("ObTime", "")
        try:
            # MADIS explicitly documents these otherwise unzoned API times as UTC.
            if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", raw_time):
                continue
            valid = datetime.strptime(raw_time, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC).timestamp()
            kelvin = Decimal(row.get("data_value", ""))
            if not kelvin.is_finite():
                continue
            celsius = kelvin - Decimal("273.15")
            if not Decimal(-100) <= celsius <= Decimal(70):
                continue
        except (ValueError, InvalidOperation, OverflowError):
            continue
        flags: list[str] = []
        qc, rejected = row.get("QCD"), row.get("QCR")
        quality = "accepted" if qc in {"V", "S", "C", "G"} and rejected == "0" else "unknown"
        if qc in {"Q", "X", "B"} or (rejected is not None and rejected != "0"):
            quality = "suspect"
            flags.append("provider_temperature_qc_suspect")
        if valid > reply.received_at:
            quality = "suspect"
            flags.append("future_observation_clock")
        if reply.received_at < reply.requested_at or reply.receipt_monotonic_ns < reply.request_monotonic_ns:
            quality = "suspect"
            flags.append("local_clock_reversed")
        # Primary whole-C measurement and float32 Kelvin serialization are not
        # six-decimal temperature precision. Unexplained fractional-C data fail
        # closed instead of inferring their precision from the printed number.
        whole_c = celsius.to_integral_value()
        precision_known = abs(celsius - whole_c) <= Decimal("0.0001")
        if not precision_known:
            flags.append("undocumented_temperature_precision")
            quality = "unknown" if quality == "accepted" else quality
        lower = whole_c - Decimal("0.501")
        upper = whole_c + Decimal("0.501")
        identity = hashlib.sha256(json.dumps([station, raw_time, "V-T"],
                                            separators=(",", ":")).encode()).hexdigest()
        revision = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        out.append({"kind": "weather_observation", "source": "madis_hfm", "station": station,
                    "valid_at": valid, "requested_at": reply.requested_at, "received_at": reply.received_at,
                    "request_monotonic_ns": reply.request_monotonic_ns,
                    "receipt_monotonic_ns": reply.receipt_monotonic_ns, "receipt_clock_id": clock_id,
                    "observation_id": "madis_hfm:" + identity, "revision_id": "madis_hfm:" + revision,
                    "independent_id": f"metar:{station}:{valid:.0f}",
                    "resolution_s": 300, "independent_1m": False, "left_censored": left_censored,
                    "raw_record_xml": ET.tostring(record, encoding="unicode"),
                    "raw_temperature_kelvin": row["data_value"], "temperature_c": float(celsius),
                    "temperature_precision_c": 1.0 if precision_known else None,
                    "temperature_precision": "madis_primary_whole_celsius" if precision_known else "unknown",
                    "temperature_serialization_slack_c": .001,
                    "lower_f": float(lower * 9 / 5 + 32) if precision_known else None,
                    "upper_f": float(upper * 9 / 5 + 32) if precision_known else None,
                    "quality": quality, "quality_flags": flags,
                    "quality_scope": "MADIS_QCD_and_QCR_plus_primary_temperature_precision",
                    "provider_quality": quality, "provider_qcd": qc, "provider_qcr": rejected,
                    "provider_qca": row.get("QCA"), "provider_received_at": None, "publication_at": None,
                    "data_latency_s": reply.received_at - valid if not flags else None,
                    "latency_scope": "observation_valid_time_to_local_response_body_receipt",
                    "climate_day": None, "final_settlement_source": False,
                    "amount_lower": None, "amount_upper": None, "interval_complete": False,
                    "precipitation_status": "not_requested", "trace": None})
    return sorted(out, key=lambda event: (event["valid_at"], event["observation_id"]))

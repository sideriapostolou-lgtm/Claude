"""Conservative parser for exact-station official NWS daily climate products.

CLI values are an independent comparison, never a substitute for a contract's
TWC settlement. Product issuance time is not its climate date. Afternoon reports
marked VALID TODAY AS OF remain partial; corrections retain distinct revisions.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .weatherwatch_observations import HttpReply

CLI_TOKEN = re.compile(r"CLI[A-Z0-9]{3}\Z")
PRODUCT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
MONTHS = {name: i for i, name in enumerate(("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
                                         "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"), 1)}


def _number(value: str) -> float | None:
    # R marks a record, not an extra decimal digit. MM and trace remain unknown.
    if not re.fullmatch(r"-?\d+(?:\.\d+)?R?", value):
        return None
    return float(value.rstrip("R"))


def _section(text: str, title: str, end: str) -> str:
    match = re.search(r"^\s*" + re.escape(title) + r"\s*$", text, re.MULTILINE)
    if match is None:
        return ""
    tail = text[match.end():]
    stop = re.search(r"^\s*" + re.escape(end) + r"\s*$", tail, re.MULTILINE)
    return tail[:stop.start()] if stop else ""


def parse_cli(body: Any, station: str, station_rule: str, reply: HttpReply,
              clock_id: str) -> dict[str, Any] | None:
    if not isinstance(body, dict) or not CLI_TOKEN.fullmatch(station_rule):
        return None
    product_id, text = body.get("id"), body.get("productText")
    if (body.get("productCode") != "CLI" or not isinstance(product_id, str)
            or not PRODUCT_ID.fullmatch(product_id) or not isinstance(text, str) or len(text) > 100_000):
        return None
    # The exact product token must be its own header line, not a station mentioned
    # later in narrative text. No city-name/airport substitution is performed.
    headers = text.splitlines()[:12]
    tokens = [line.strip() for line in headers if CLI_TOKEN.fullmatch(line.strip())]
    if tokens != [station_rule]:
        return None
    match = re.search(r"CLIMATE SUMMARY FOR\s+([A-Z]+)\s+(\d{1,2})\s+(\d{4})\.{3}", text)
    if not match or match.group(1) not in MONTHS:
        return None
    try:
        day = datetime(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2)), tzinfo=UTC).date()
        issued = datetime.fromisoformat(body["issuanceTime"])
        if issued.tzinfo is None:
            return None
    except (ValueError, KeyError, TypeError, OverflowError):
        return None
    temperature = _section(text, "TEMPERATURE (F)", "PRECIPITATION (IN)")
    rain = _section(text, "PRECIPITATION (IN)", "SNOWFALL (IN)")
    # Some offices omit the snowfall section and go directly to degree days.
    if not rain:
        rain = _section(text, "PRECIPITATION (IN)", "DEGREE DAYS")
    highs = re.findall(r"^\s*MAXIMUM\s+(\S+)", temperature, re.MULTILINE)
    lows = re.findall(r"^\s*MINIMUM\s+(\S+)", temperature, re.MULTILINE)
    precip = re.findall(r"^\s*(?:TODAY|YESTERDAY)\s+(\S+)", rain, re.MULTILINE)
    high = _number(highs[0]) if len(highs) == 1 else None
    low = _number(lows[0]) if len(lows) == 1 else None
    amount = _number(precip[0]) if len(precip) == 1 else None
    trace = (precip[0] == "T") if len(precip) == 1 else None
    flags: list[str] = []
    if high is None or low is None or high < low or not (-150 <= low <= high <= 150):
        flags.append("missing_or_invalid_temperature_extrema")
        high = low = None
    if amount is not None and not 0 <= amount <= 100:
        amount = None
        flags.append("invalid_precipitation")
    if (issued.timestamp() > reply.received_at or reply.received_at < reply.requested_at
            or reply.receipt_monotonic_ns < reply.request_monotonic_ns):
        flags.append("clock_anomaly")
    partial = "VALID TODAY AS OF" in text or "PRELIMINARY" in text.upper()
    # The explicit YESTERDAY observation heading supplies completion evidence;
    # a date that merely differs from the UTC issuance date does not.
    completed = (not partial and bool(re.search(r"^\s*YESTERDAY\s*$", temperature, re.MULTILINE))
                 and day <= issued.astimezone(UTC).date())
    correction = bool(re.search(r"\b(?:CORRECTED|CORRECTION)\b", text.upper()))
    revision = hashlib.sha256(text.encode()).hexdigest()
    return {"kind": "weather_cli", "source": "nws_cli", "station": station,
            "station_rule": station_rule, "climate_day": day.isoformat(),
            "maximum_f": high, "minimum_f": low, "precipitation_in": amount,
            "precipitation_trace": trace, "precipitation_raw": precip[0] if len(precip) == 1 else None,
            "final_report": completed and "clock_anomaly" not in flags,
            "report_status": "completed_daily_report" if completed else "partial_or_unproved_completion",
            "finality_scope": "published_complete_daily_report_can_be_corrected_later",
            "quality": "suspect" if flags else "accepted", "quality_flags": flags,
            "corrected": correction, "report_id": product_id, "revision_id": revision,
            "source_url": "https://api.weather.gov/products/" + product_id,
            "issued_at": issued.timestamp(), "requested_at": reply.requested_at,
            "received_at": reply.received_at, "request_monotonic_ns": reply.request_monotonic_ns,
            "receipt_monotonic_ns": reply.receipt_monotonic_ns, "receipt_clock_id": clock_id,
            "raw_text": text, "contract_settlement": False}

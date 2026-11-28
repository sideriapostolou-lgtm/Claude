"""Weather stopwatch market readers: public GETs and market-only Kalshi WS.

No account client, order endpoint, simulation fill or money switch exists here.
Rules are retained verbatim. A named CLI station does not make a TWC contract a
NWS lock. US market streaming requires authentication (2026-10-12 docs); this
public-gateway reader therefore reports its trade tape as unavailable.
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
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from .config import Settings
from .speeddesk_feeds import parse_books as us_books
from .speeddesk_feeds import timestamp
from .speeddesk_kalshi_ws import KalshiMarketWS, MarketState
from .speeddesk_model import Book, Trade

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
US = "https://gateway.polymarket.us"
PREFIXES = ("KXHIGH", "KXLOWT", "KXRAIN")
US_CITIES = {"nyc": ("CLINYC", "Central Park"), "mdw": ("CLIMDW", "Midway"),
             "mia": ("CLIMIA", "Miami"), "lax": ("CLILAX", "Los Angeles"),
             "sfo": ("CLISFO", "San Francisco")}
# Explicit CLI identifiers only. Never infer a station from a city/series suffix.
# The station metadata source is included with each descriptor for audit.
CLI_STATIONS = {
    "CLINYC": ("KNYC", "America/New_York"), "CLIMDW": ("KMDW", "America/Chicago"),
    "CLIMIA": ("KMIA", "America/New_York"), "CLILAX": ("KLAX", "America/Los_Angeles"),
    "CLIAUS": ("KAUS", "America/Chicago"), "CLIDEN": ("KDEN", "America/Denver"),
    "CLIHOU": ("KHOU", "America/Chicago"), "CLIDFW": ("KDFW", "America/Chicago"),
    "CLIATL": ("KATL", "America/New_York"), "CLISEA": ("KSEA", "America/Los_Angeles"),
    "CLISFO": ("KSFO", "America/Los_Angeles"), "CLIBOS": ("KBOS", "America/New_York"),
    "CLIPHL": ("KPHL", "America/New_York"), "CLIDCA": ("KDCA", "America/New_York"),
    "CLIEWR": ("KEWR", "America/New_York"), "CLIPHX": ("KPHX", "America/Phoenix"),
    "CLISAN": ("KSAN", "America/Los_Angeles"), "CLISAT": ("KSAT", "America/Chicago"),
    "CLILAS": ("KLAS", "America/Los_Angeles"), "CLIMSP": ("KMSP", "America/Chicago"),
    "CLIMSY": ("KMSY", "America/Chicago"), "CLIOKC": ("KOKC", "America/Chicago"),
    "CLISDF": ("KSDF", "America/New_York"), "CLITTN": ("KTTN", "America/New_York"),
    # Additional daily-rain rule stations checked against NWS metadata 2026-10-12.
    "CLITPA": ("KTPA", "America/New_York"),
    "CLISTL": ("KSTL", "America/Chicago"),
    "CLISGF": ("KSGF", "America/Chicago"),
    "CLIPVD": ("KPVD", "America/New_York"),
    "CLIPIT": ("KPIT", "America/New_York"),
    "CLIMKE": ("KMKE", "America/Chicago"),
    "CLILEX": ("KLEX", "America/New_York"),
    "CLIIND": ("KIND", "America/Indiana/Indianapolis"),
    "CLICMH": ("KCMH", "America/New_York"),
    "CLICLL": ("KCLL", "America/Chicago"),
    "CLIORD": ("KORD", "America/Chicago"),
    "CLIABQ": ("KABQ", "America/Denver"),
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _station(rules: str) -> tuple[str | None, str | None, str | None]:
    tokens = set(re.findall(r"\bCLI[A-Z0-9]{3}\b", rules))
    if len(tokens) == 1:
        token = next(iter(tokens))
        known = CLI_STATIONS.get(token)
        return (known[0], token, known[1]) if known else (None, token, None)
    # International markets sometimes explicitly identify a four-letter ICAO
    # station. Retain its identity; no climate-day offset is inferred.
    codes = set(re.findall(r"\(([A-Z]{4})\)", rules))
    if not tokens and len(codes) == 1:
        code = next(iter(codes))
        return code, code, None
    return None, None, None


def _source(rules: str) -> str | None:
    lowered = rules.lower()
    if "weather company" in lowered or "weather channel" in lowered:
        return "The Weather Company"
    if "national weather service" in lowered or "nws" in lowered:
        return "NWS CLI"
    return None


def _bounds(day: str | None, zone: str | None) -> tuple[float | None, float | None]:
    """Labeled standard-time observation proxy, never asserted source convention."""
    if not day or not zone:
        return None, None
    try:
        date = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
        offset = datetime(date.year, 1, 1, tzinfo=ZoneInfo(zone)).utcoffset()
        if offset is None:
            return None, None
        start = (date - offset).timestamp()
        return start, start + 86400
    except (ValueError, OverflowError):
        return None, None


def kalshi_market(raw: Any, series: Any, received_at: float) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(series, dict):
        return None
    ticker, family = raw.get("ticker"), series.get("ticker")
    if (not isinstance(ticker, str) or not isinstance(family, str)
            or not family.startswith(PREFIXES) or not ticker.startswith(family + "-")):
        return None
    primary = str(raw.get("rules_primary") or "")
    secondary = str(raw.get("rules_secondary") or "")
    rules = primary + "\n" + secondary
    station, rule_station, zone = _station(primary)
    source = _source(primary) or _source(secondary)
    day = None
    event = str(raw.get("event_ticker") or "")
    try:
        day = datetime.strptime(event.removeprefix(family + "-"), "%y%b%d").strftime("%Y-%m-%d")
    except ValueError:
        pass
    start, end = _bounds(day, zone)
    kind = "rain" if family.startswith("KXRAIN") else "low" if family.startswith("KXLOWT") else "high"
    daily = series.get("frequency") == "daily" and day is not None
    strike = raw.get("strike_type")
    floor, cap = _number(raw.get("floor_strike")), _number(raw.get("cap_strike"))
    reasons = []
    dates: set[str] = set()
    for found in re.findall(r"\b([A-Z][a-z]{2,8} \d{1,2}, \d{4})\b", primary):
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                dates.add(datetime.strptime(found, fmt).strftime("%Y-%m-%d"))
                break
            except ValueError:
                continue
    if daily and dates != {day}:
        reasons.append("rule_date_missing_or_conflicting")
    if not station:
        reasons.append("rule_station_unmapped_or_ambiguous")
    if not daily:
        reasons.append("non_daily_or_unparsed_climate_day")
    if start is None:
        reasons.append("climate_day_proxy_unavailable")
    if strike not in ("less", "greater", "between"):
        reasons.append("unsupported_strike")
    source_reason = "twc_is_not_cli_lock" if source == "The Weather Company" else "source_day_and_revision_rules_unverified"
    return {"venue": "kalshi", "market_id": "kalshi:" + ticker, "venue_id": ticker,
            "series": family, "station": station, "station_rule": rule_station,
            "station_verified": station is not None, "station_evidence":
            "https://api.weather.gov/stations/" + station if station and station.startswith("K") else None,
            "kind": kind, "date": day, "period_start": start, "period_end": end,
            "period_verified": False, "period_basis": "local_standard_time_proxy" if start else "unknown",
            "strike_type": strike, "floor": floor, "cap": cap,
            "floor_inclusive": strike == "between", "cap_inclusive": strike == "between",
            "settlement_source": source, "source_verified": source is not None,
            "source_qualified": False, "qualification_reason": source_reason,
            "supported": not reasons, "unsupported_reason": ";".join(reasons) or None,
            "rules_primary": primary, "rules_secondary": secondary,
            "rules_sha256": hashlib.sha256(rules.encode()).hexdigest(),
            "rules_url": KALSHI + "/markets/" + ticker,
            "contract_url": series.get("contract_terms_url"), "settlement_sources": series.get("settlement_sources", []),
            "fee_model": "kalshi_direct", "fee_precision": 0.0001,
            "fee_type": series.get("fee_type"), "fee_multiplier": _number(series.get("fee_multiplier")),
            "fee_verified": series.get("fee_type") == "quadratic" and _number(series.get("fee_multiplier")) == 1
                and not any("fee" in key for key in raw),
            "status": raw.get("status"), "close_at": timestamp(raw.get("close_time")),
            "discovered_at": received_at}


def us_market(raw: Any, received_at: float) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    slug = raw.get("slug")
    if not isinstance(slug, str):
        return None
    match = re.fullmatch(r"tc-temp-(nyc|mdw|mia|lax|sfo)high-(\d{4}-\d{2}-\d{2})-(.+)", slug)
    if match is None:
        return None
    city, day, _ = match.groups()
    description = str(raw.get("description") or "")
    token, _ = US_CITIES[city]
    station, zone = CLI_STATIONS[token]
    # Require this venue's explicit station, not a city-name resemblance.
    station_ok = _station(description)[0] == station
    floor = cap = None
    strike = None
    below = re.search(r"be less than or equal to (-?\d+(?:\.\d+)?)F\?", description)
    above = re.search(r"be greater than or equal to (-?\d+(?:\.\d+)?)F\?", description)
    between = re.search(r"be between (-?\d+(?:\.\d+)?)F and (-?\d+(?:\.\d+)?)F\?", description)
    # Slugs have misleading 'lt' spellings for inclusive upper boundaries.
    # Contract prose is the evidence; verify its climate date as well.
    if f"for {day} " in description:
        if below:
            strike, cap = "less", float(below[1])
        elif above:
            strike, floor = "greater", float(above[1])
        elif between:
            strike, floor, cap = "between", float(between[1]), float(between[2])
    start, end = _bounds(day, zone)
    source = _source(description)
    return {"venue": "polymarket_us", "market_id": "polymarket_us:" + slug, "venue_id": slug,
            "series": "tc-temp-" + city + "high", "station": station if station_ok else None,
            "station_rule": token if station_ok else None, "station_verified": station_ok,
            "station_evidence": US + "/v1/market/slug/" + slug,
            "kind": "high", "date": day, "period_start": start, "period_end": end,
            "period_verified": False, "period_basis": "local_standard_time_proxy",
            "temperature_precision": "integer_f_proxy",
            "temperature_precision_verified": False,
            "strike_type": strike, "floor": floor, "cap": cap,
            "floor_inclusive": True, "cap_inclusive": True,
            "settlement_source": source, "source_verified": source is not None,
            "source_qualified": False, "qualification_reason": "source_day_and_revision_rules_unverified",
            "supported": bool(station_ok and strike and start is not None),
            "unsupported_reason": None if station_ok and strike else "own_rule_station_or_bracket_unverified",
            "rules_primary": description, "rules_secondary": "",
            "rules_sha256": hashlib.sha256(description.encode()).hexdigest(),
            "rules_url": US + "/v1/market/slug/" + slug,
            "fee_model": "polymarket_us", "fee_coefficient": _number(raw.get("feeCoefficient")),
            "fee_verified": _number(raw.get("feeCoefficient")) == 0.0695 and raw.get("comboEnabled") is False,
            "status": raw.get("status"), "close_at": timestamp(raw.get("endDate")),
            "discovered_at": received_at}


def kalshi_book(raw: Any, ticker: str, received_at: float, requested_at: float) -> dict[str, Any] | None:
    data = raw.get("orderbook_fp") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return None
    sides: dict[str, list[list[float]]] = {}
    for side in ("yes", "no"):
        levels = data.get(side + "_dollars")
        if not isinstance(levels, list):
            return None
        prices: dict[float, float] = {}
        for row in levels:
            if not isinstance(row, list) or len(row) != 2:
                return None
            price, size = _number(row[0]), _number(row[1])
            if price is None or size is None or not 0 < price < 1 or size < 0 or price in prices:
                return None
            prices[price] = size
        sides[side] = [[p, s] for p, s in sorted(prices.items(), reverse=True) if s > 0]
    valid = not (sides["yes"] and sides["no"] and sides["yes"][0][0] + sides["no"][0][0] >= 1)
    return {"venue": "kalshi", "market_id": "kalshi:" + ticker,
            "yes_bids": sides["yes"], "no_bids": sides["no"],
            "yes_asks": [[round(1 - p, 8), s] for p, s in sides["no"]],
            "no_asks": [[round(1 - p, 8), s] for p, s in sides["yes"]],
            "received_at": received_at, "requested_at": requested_at, "exchange_at": None,
            "source": "rest", "valid": valid, "complete": True,
            "sequence": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
            "sequence_verified": False, "post_delay_proven": False}


def settlement(raw: Any, market: dict[str, Any], now: float) -> dict[str, Any] | None:
    if market["venue"] == "kalshi":
        value = raw.get("market") if isinstance(raw, dict) else None
        if not isinstance(value, dict) or value.get("ticker") != market["venue_id"]:
            return None
        if value.get("status") != "settled" or value.get("result") not in ("yes", "no"):
            return None
        payout = _number(value.get("settlement_value_dollars"))
        if payout != (1 if value["result"] == "yes" else 0):
            return None
        result = value["result"]
        source_value = _number(value.get("expiration_value"))
    else:
        if not isinstance(raw, dict) or raw.get("slug") != market["venue_id"]:
            return None
        payout = _number(raw.get("settlement"))
        if payout not in (0, 1):
            return None
        result, source_value = "yes" if payout else "no", None
    return {"venue": market["venue"], "market_id": market["market_id"], "result": result,
            "yes_payout": payout, "source_value": source_value, "source": market.get("settlement_source"),
            "received_at": now, "final": True, "rules_sha256": market.get("rules_sha256")}


class PublicGET:
    """Allowlisted public GET-only transport; 429 cooldown spans all venue reads."""
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self._locks = {"kalshi": threading.Lock(), "polymarket_us": threading.Lock()}
        self._next = {"kalshi": 0.0, "polymarket_us": 0.0}

    def __call__(self, venue: str, path: str) -> Any:
        patterns = (r"/series(?:\?.*)?", r"/markets(?:\?.*)?", r"/markets/[A-Z0-9.-]+(?:/orderbook)?(?:\?.*)?") if venue == "kalshi" else (
            r"/v1/markets\?.*", r"/v1/markets/tc-temp-[a-z0-9-]+/(?:book|settlement)")
        if not any(re.fullmatch(pattern, path) for pattern in patterns):
            raise ValueError("weather_public_path_not_allowed")
        with self._locks[venue]:
            delay = self._next[venue] - self.clock()
            if delay > 0:
                raise RuntimeError("weather_public_cooldown")
            self._next[venue] = self.clock() + (1.0 if venue == "kalshi" else 0.25)
            response = requests.get((KALSHI if venue == "kalshi" else US) + path,
                                    timeout=(3, 5), stream=True, allow_redirects=False,
                                    headers={"User-Agent": "nightcrawler-weather-stopwatch/1"})
            try:
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "")
                    wait = _number(retry)
                    if wait is None:
                        try:
                            wait = parsedate_to_datetime(retry).timestamp() - self.clock()
                        except (ValueError, TypeError, OverflowError):
                            wait = 60
                    self._next[venue] = self.clock() + max(60, wait if math.isfinite(wait) else 60)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("weather_public_non_200")
                parts, length, began = [], 0, time.monotonic()
                for part in response.iter_content(65536):
                    length += len(part)
                    if length > 8_000_000 or time.monotonic() - began > 10:
                        raise ValueError("weather_public_response_limit")
                    parts.append(part)
                return json.loads(b"".join(parts))
            finally:
                response.close()


class WeatherState(MarketState):
    """Keep sequence-validated snapshot arrival evidence, even without source time."""
    def __init__(self, tickers: frozenset[str], snapshot: Callable[[dict[str, Any]], None]) -> None:
        super().__init__(tickers)
        self.snapshot = snapshot

    def apply(self, raw: Any, now: float) -> tuple[tuple[Book, ...], tuple[Trade, ...]]:
        books, trades = super().apply(raw, now)
        if raw.get("type") in ("orderbook_snapshot", "orderbook_delta") and not books:
            ticker = raw["msg"]["market_ticker"]
            if ticker in self.depth:
                data = {side + "_dollars": [[p, s] for p, s in self.depth[ticker][side].items()]
                        for side in ("yes", "no")}
                value = kalshi_book({"orderbook_fp": data}, ticker, now, now)
                if value is not None:
                    value.update(source="websocket", requested_at=None, sequence_verified=True,
                                 sequence=f"kalshi-ws:{raw['sid']}:{raw['seq']}",
                                 evidence="snapshot_or_delta_without_source_time")
                    self.snapshot(value)
        return books, trades


class WeatherWS(KalshiMarketWS):
    def __init__(self, *args: Any, on_snapshot: Callable[[dict[str, Any]], None], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._on_snapshot = on_snapshot

    async def _session(self, ws: Any, tickers: frozenset[str], stop: threading.Event) -> None:
        self.state = WeatherState(tickers, self._on_snapshot)
        await super()._session(ws, tickers, stop)


class MarketFeeds:
    """Independent discovery, market WS, and honest timed public-depth captures."""
    def __init__(self, emit: Callable[[str, dict[str, Any], float], None], stop: threading.Event, *,
                 settings: Settings | None = None, clock: Callable[[], float] = time.time,
                 receipt_clock_id: str = "weather-market-process", discovery_s: float = 600,
                 max_active_watches: int = 256, rest_get: Callable[[str, str], Any] | None = None,
                 ws_connect: Callable[..., Any] | None = None) -> None:
        settings = settings or Settings.from_env()
        self.clock = clock
        def deliver(kind: str, payload: dict[str, Any]) -> None:
            # Parser delivery clock, not an invented exchange or first-byte clock.
            payload = {**payload, "adapter_monotonic_ns": time.monotonic_ns(),
                       "receipt_clock_id": receipt_clock_id}
            emit(kind, payload, self.clock())
        self.emit = deliver
        self.receipt_clock_id = receipt_clock_id
        self.discovery_s = max(120.0, discovery_s)
        self.max_active_watches = max(1, max_active_watches)
        self.get = rest_get or PublicGET(clock=clock)
        self.markets: dict[str, dict[str, Any]] = {}
        self.stations: list[dict[str, Any]] = []
        self.watches: dict[str, float] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self._settled: set[str] = set()
        self._pending_settlements: dict[str, float] = {}
        self._settlement_seen: dict[str, dict[str, Any]] = {}
        self._book_sides: dict[str, dict[str, Book]] = {}
        self._ws_has_keys = bool(settings.kalshi_key_id and settings.kalshi_private_key)
        self.ws = WeatherWS(settings, on_snapshot=self._snapshot, tickers=self._tickers, on_book=self._ws_book,
                                on_trade=self._ws_trade, on_status=self._ws_status,
                                clock=clock, ws_connect=ws_connect)
        self._rest_last: dict[str, float] = {}
        self._request_lock = {"kalshi": asyncio.Lock(), "polymarket_us": asyncio.Lock()}
        self._next_request = {"kalshi": 0.0, "polymarket_us": 0.0}
        self._stop = stop

    def restore(self, markets: dict[str, Any], watches: dict[str, Any] | None = None) -> None:
        for key, value in markets.items():
            if isinstance(value, dict) and value.get("market_id") == key and value.get("venue") in ("kalshi", "polymarket_us"):
                self.markets[key] = dict(value)

        for key, until in (watches or {}).items():
            value = _number(until)
            if key in self.markets and value is not None and value >= 0:
                self._pending_settlements[key] = value
                if value > self.clock():
                    if sum(end > self.clock() for end in self.watches.values()) < self.max_active_watches:
                        self.watches[key] = min(value, self.clock() + 600)
                    else:
                        self.emit("weather_gap", {"reason": "restored_market_watch_capacity", "market_id": key,
                                  "at": self.clock()})
        self._expire()
        self._stations()

    def watch(self, request: dict[str, Any]) -> bool:
        key, until = request.get("market_id"), _number(request.get("until"))
        now = self.clock()
        if key not in self.markets or until is None or until <= now:
            return False
        active = sum(end > now for end in self.watches.values())
        if self.watches.get(key, 0) <= now and active >= self.max_active_watches:
            self.emit("weather_gap", {"reason": "market_watch_capacity", "market_id": key, "at": now})
            return False
        self.watches[key] = max(self.watches.get(key, 0), min(until, now + 600))
        self._pending_settlements[key] = self.watches[key]
        self._expire()
        return True

    def _expire(self) -> None:
        now = self.clock()
        for key, until in list(self.watches.items()):
            if until <= now:
                self.watches.pop(key, None)
                self.books.pop(key, None)
                self._book_sides.pop(key, None)
        for key, until in list(self._pending_settlements.items()):
            if until < now - 7 * 86400:
                if key not in self._settled:
                    self.emit("weather_gap", {"reason": "settlement_retention_expired", "market_id": key, "at": now})
                self._pending_settlements.pop(key, None)
                self._settlement_seen.pop(key, None)
        for key, row in list(self.markets.items()):
            ended = _number(row.get("period_end"))
            if ended is not None and ended < now - 8 * 86400 and key not in self._pending_settlements:
                self.markets.pop(key, None)
                self.books.pop(key, None)
                self._book_sides.pop(key, None)
                self._rest_last.pop(key, None)
                self._settled.discard(key)

    def _tickers(self) -> frozenset[str]:
        # Subscribe before a lock, otherwise subscription latency hides its first book.
        now = self.clock()
        return frozenset(str(row["venue_id"]) for row in self.markets.values()
                         if row.get("venue") == "kalshi" and row.get("supported")
                         and (_number(row.get("period_start")) or math.inf) <= now
                         and (_number(row.get("period_end")) or -math.inf) + 600 > now)

    def _stations(self) -> None:
        unique: dict[str, dict[str, Any]] = {}
        for value in self.markets.values():
            station = value.get("station")
            if isinstance(station, str) and value.get("station_verified"):
                unique.setdefault(station, {key: value.get(key) for key in
                    ("station", "station_rule", "station_verified", "station_evidence", "venue", "series")})
        self.stations = list(unique.values())

    async def _get(self, venue: str, path: str, started: list[float] | None = None) -> Any:
        async with self._request_lock[venue]:
            delay = self._next_request[venue] - self.clock()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request[venue] = self.clock() + (1.02 if venue == "kalshi" else 0.26)
            if started is not None:
                started.append(self.clock())
            return await asyncio.to_thread(self.get, venue, path)

    async def _pages(self, venue: str, path: str, query: dict[str, Any], field: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _ in range(50):
            reply = await self._get(venue, path + "?" + urlencode(query))
            if not isinstance(reply, dict) or not isinstance(reply.get(field), list):
                raise TypeError("weather_metadata_schema")
            page = reply[field]
            if not all(isinstance(row, dict) for row in page):
                raise TypeError("weather_metadata_schema")
            rows.extend(page)
            if venue == "polymarket_us":
                if len(page) < int(query["limit"]):
                    return rows
                signature = hashlib.sha256(json.dumps(page, sort_keys=True).encode()).hexdigest()
                if signature in seen:
                    raise ValueError("weather_metadata_repeated_page")
                seen.add(signature)
                query["offset"] = int(query.get("offset", 0)) + len(page)
            else:
                cursor = reply.get("cursor")
                if not cursor:
                    return rows
                if not isinstance(cursor, str) or cursor in seen:
                    raise ValueError("weather_metadata_cursor")
                seen.add(cursor)
                query["cursor"] = cursor
        raise ValueError("weather_metadata_truncated")

    def _market(self, value: dict[str, Any]) -> None:
        self.markets[value["market_id"]] = value
        self.emit("weather_market", value)

    async def discover_kalshi(self) -> None:
        series = await self._pages("kalshi", "/series", {"category": "Climate and Weather"}, "series")
        relevant = [row for row in series if str(row.get("ticker", "")).startswith(PREFIXES)]
        covered, empty, failed = [], [], []
        for family in relevant:
            if self._stop.is_set():
                return
            name = family["ticker"]
            try:
                rows = await self._pages("kalshi", "/markets", {"series_ticker": name, "status": "open", "limit": 1000}, "markets")
                if not rows:
                    empty.append(name)
                for row in rows:
                    parsed = kalshi_market(row, family, self.clock())
                    if parsed:
                        self._market(parsed)
                covered.append(name)
                self._stations()  # Observations start during the broad inventory sweep.
            except Exception as exc:  # noqa: BLE001 — never echo remote payloads/headers.
                failed.append({"series": name, "reason": type(exc).__name__})
        self.emit("weather_venue_status", {"venue": "kalshi", "kind": "discovery", "at": self.clock(),
                  "series_found": len(relevant), "series_checked": covered, "no_open_markets": empty,
                  "failed": failed, "all_series_checked": not failed,
                  "uncovered_markets": [{"market_id": row["market_id"], "reason": row["unsupported_reason"]}
                                        for row in self.markets.values() if row["venue"] == "kalshi" and not row["supported"]]})

    async def discover_us(self) -> None:
        rows = await self._pages("polymarket_us", "/v1/markets",
                                 {"limit": 100, "offset": 0, "closed": "false", "categories": "climate"}, "markets")
        for row in rows:
            value = us_market(row, self.clock())
            if value:
                self._market(value)
        self._stations()
        self.emit("weather_venue_status", {"venue": "polymarket_us", "kind": "discovery", "at": self.clock(),
                  "market_count": sum(row["venue"] == "polymarket_us" for row in self.markets.values()),
                  "trade_tape": "unavailable_public_gateway", "book_transport": "public_rest",
                  "aggregate_poll_limit_hz": 4, "per_market_second_resolution_guaranteed": False})

    def _snapshot(self, value: dict[str, Any]) -> None:
        key = value["market_id"]
        self.books[key] = value
        if self.watches.get(key, 0) > self.clock():
            self.emit("weather_book", value)

    def _ws_book(self, book: Book) -> None:
        key = "kalshi:" + book.window
        self._book_sides.setdefault(key, {})[book.side] = book
        sides = self._book_sides[key]
        if not all(side in sides and sides[side].sequence == book.sequence for side in ("up", "down")):
            return
        payload: dict[str, Any] = {"market_id": key, "venue": "kalshi", "source": "websocket",
                   "exchange_at": book.exchange_at, "received_at": book.at,
                   "requested_at": None, "sequence": book.sequence, "sequence_verified": True,
                   "valid": True, "complete": True, "post_delay_proven": book.exchange_at is not None}
        for label, side in (("yes", "up"), ("no", "down")):
            payload[label + "_bids"] = [[x.price, x.size] for x in sides[side].bids]
            payload[label + "_asks"] = [[x.price, x.size] for x in sides[side].asks]
        self.books[key] = payload
        if self.watches.get(key, 0) > self.clock():
            self.emit("weather_book", payload)

    def _ws_trade(self, trade: Trade) -> None:
        key = "kalshi:" + trade.window
        if trade.side != "up" or self.watches.get(key, 0) <= self.clock():
            return
        self.emit("weather_trade", {"market_id": key, "venue": "kalshi", "trade_id": trade.trade_id,
                  "yes_price": trade.price, "no_price": round(1 - trade.price, 8), "size": trade.size,
                  "taker_side": "yes" if trade.aggressor == "buy" else "no",
                  "exchange_at": trade.at, "received_at": trade.received_at, "source": "websocket"})

    def _ws_status(self, value: dict[str, Any]) -> None:
        for ticker in value.get("gap_windows", []):
            key = "kalshi:" + ticker
            old = self.books.pop(key, None)
            self._book_sides.pop(key, None)
            if old is not None:
                self.emit("weather_book", {**old, "valid": False, "complete": False,
                          "gap_at": self.clock(), "reason": value.get("ws_status")})
        self.emit("weather_venue_status", {"venue": "kalshi", "kind": "websocket", "at": self.clock(), **value})

    async def poll_book(self, key: str) -> None:
        market = self.markets[key]
        venue, identity = market["venue"], market["venue_id"]
        started: list[float] = []
        raw = await self._get(venue, "/markets/" + identity + "/orderbook" if venue == "kalshi" else "/v1/markets/" + identity + "/book", started)
        requested, now = started[0], self.clock()
        payload = kalshi_book(raw, identity, now, requested) if venue == "kalshi" else None
        if venue == "polymarket_us":
            parsed = us_books(raw, now, source="rest")
            if len(parsed) == 2 and all(book.window == identity for book in parsed):
                payload = {"venue": venue, "market_id": key, "received_at": now, "requested_at": requested,
                           "exchange_at": parsed[0].exchange_at, "source": "rest", "sequence": parsed[0].sequence,
                           "sequence_verified": False, "valid": True, "complete": True, "post_delay_proven": False}
                for name, book in zip(("yes", "no"), parsed, strict=True):
                    payload[name + "_bids"] = [[x.price, x.size] for x in book.bids]
                    payload[name + "_asks"] = [[x.price, x.size] for x in book.asks]
        if payload is None:
            self.books.pop(key, None)
            self.emit("weather_book", {"venue": venue, "market_id": key, "valid": False, "complete": False,
                                      "received_at": now, "reason": "public_book_invalid"})
            return
        previous = self._rest_last.get(key)
        payload["poll_interval_seconds"] = now - previous if previous is not None else None
        self._rest_last[key] = now
        self.books[key] = payload
        self.emit("weather_book", payload)

    async def _captures(self, venue: str) -> None:
        while not self._stop.is_set():
            active = [key for key, until in self.watches.items() if until > self.clock() and self.markets.get(key, {}).get("venue") == venue]
            for key in sorted(active, key=lambda item: self._rest_last.get(item, 0)):
                if venue == "kalshi" and self.markets[key]["venue_id"] in self.ws.fresh_books():
                    continue
                try:
                    await self.poll_book(key)
                except Exception as exc:  # noqa: BLE001
                    self.books.pop(key, None)
                    self.emit("weather_book", {"venue": venue, "market_id": key, "valid": False, "complete": False,
                              "received_at": self.clock(), "reason": type(exc).__name__})
            await asyncio.sleep(0.25)

    async def _samples(self) -> None:
        while not self._stop.is_set():
            now = self.clock()
            self._expire()
            for key, until in list(self.watches.items()):
                if until <= now:
                    continue
                saved = self.books.get(key)
                if saved is not None:
                    self.emit("weather_book", {**saved, "sampled_at": now, "sample_only": True})
                else:
                    self.emit("weather_book", {"market_id": key, "venue": self.markets[key]["venue"],
                              "sampled_at": now, "valid": False, "complete": False, "reason": "book_not_observed"})
            await asyncio.sleep(1)

    async def _settlements(self) -> None:
        while not self._stop.is_set():
            for key in list(self._pending_settlements):
                market = self.markets[key]
                end = _number(market.get("period_end"))
                if end is None or self.clock() < end:
                    continue
                try:
                    venue, identity = market["venue"], market["venue_id"]
                    raw = await self._get(venue, "/markets/" + identity if venue == "kalshi" else "/v1/markets/" + identity + "/settlement")
                    value = settlement(raw, market, self.clock())
                    if value:
                        comparable = {k: v for k, v in value.items() if k != "received_at"}
                        previous = self._settlement_seen.get(key)
                        self._settled.add(key)
                        if comparable != previous:
                            self._settlement_seen[key] = comparable
                            self.emit("weather_settlement", {**value, "revision": previous is not None,
                                      "previous_result": previous.get("result") if previous else None})
                except Exception as exc:  # noqa: BLE001
                    self.emit("weather_venue_status", {"venue": market["venue"], "kind": "settlement_unknown",
                              "market_id": key, "at": self.clock(), "reason": type(exc).__name__})
            await asyncio.sleep(300)

    async def _discover(self, venue: str) -> None:
        while not self._stop.is_set():
            try:
                await (self.discover_kalshi() if venue == "kalshi" else self.discover_us())
            except Exception as exc:  # noqa: BLE001
                self.emit("weather_venue_status", {"venue": venue, "kind": "discovery_failed", "at": self.clock(), "reason": type(exc).__name__})
            await asyncio.sleep(self.discovery_s)

    async def run(self) -> None:
        stop = self._stop
        tasks = [asyncio.create_task(self._discover(venue)) for venue in ("kalshi", "polymarket_us")]
        tasks += [asyncio.create_task(self._captures(venue)) for venue in ("kalshi", "polymarket_us")]
        tasks += [asyncio.create_task(self._samples()), asyncio.create_task(self._settlements())]
        if self._ws_has_keys:
            tasks.append(asyncio.create_task(self.ws.run(stop)))
        else:
            self.emit("weather_venue_status", {"venue": "kalshi", "kind": "websocket", "at": self.clock(),
                      "ws_connected": False, "reason": "credentials_missing_public_rest_only", "trade_tape": "unavailable"})
        try:
            while not stop.is_set():
                for task in tasks:
                    if task.done():
                        task.result()
                await asyncio.sleep(0.2)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

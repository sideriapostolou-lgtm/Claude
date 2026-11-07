"""Public-only weather observation-time/print study; never an executable-fill backtest.

Run: python research/lab9/weather_window.py --output /tmp/lab9-weather
Frozen cohort and assumptions: WEATHER_PLAN.md. No credentials or order endpoints.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = {
    "KXHIGHNY": ("NYC", "CLINYC", -5),
    "KXHIGHCHI": ("MDW", "CLIMDW", -6),
    "KXHIGHMIA": ("MIA", "CLIMIA", -5),
    "KXHIGHLAX": ("LAX", "CLILAX", -8),
    "KXHIGHAUS": ("AUS", "CLIAUS", -6),
    "KXHIGHDEN": ("DEN", "CLIDEN", -7),
}
START = date(2026, 10, 5)
END = date(2026, 10, 11)
TG = re.compile(r"(?:^|\s)T([01])(\d{3})(?:[01]\d{3}|////)(?=\s|$)")


def stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(UTC)


def dec(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite number")
    return result


def conservative_temperature(metar: str, station: str) -> tuple[Decimal, int] | None:
    """Current T-group, with reported 0.1C interval; not proof of final climate value."""
    words = metar.split()
    if not words or words[0] not in (station, "K" + station):
        return None
    found = TG.search(metar)
    if found is None:
        return None
    celsius = dec(found[2]) / 10 * (-1 if found[1] == "1" else 1)
    fahrenheit = celsius * Decimal("1.8") + 32
    lower_f = (celsius - Decimal("0.05")) * Decimal("1.8") + 32
    # Integer-rounding proxy; contracts using full-precision TWC remain unverified.
    lower_integer = int((lower_f + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
    return fahrenheit, lower_integer


def parse_observations(body: str, station: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    for row in csv.DictReader(io.StringIO(body)):
        raw = row.get("metar", "")
        try:
            at = datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        except (KeyError, ValueError):
            exclusions["invalid_time"] += 1
            continue
        if row.get("station") not in (station, "K" + station):
            exclusions["wrong_station"] += 1
            continue
        value = conservative_temperature(raw, station)
        if value is None:
            exclusions["missing_or_invalid_current_t_group"] += 1
            continue
        key = (at.isoformat(), raw)
        if key in seen:
            exclusions["duplicate"] += 1
            continue
        seen.add(key)
        rows.append({"at": at.isoformat(), "fahrenheit": str(value[0]),
                     "lower_integer_f": value[1], "correction": " COR " in f" {raw} ",
                     "metar": raw, "availability_at": None})
    return sorted(rows, key=lambda x: x["at"]), dict(exclusions)


def market_day(market: dict[str, Any]) -> date:
    return datetime.strptime(market["event_ticker"].split("-")[-1], "%y%b%d").date()


def no_proxy(market: dict[str, Any], observed_floor: int) -> bool:
    kind = market.get("strike_type")
    cap = market.get("cap_strike")
    if cap is None:
        return False
    if kind == "between":
        return dec(observed_floor) > dec(cap)
    if kind == "less":
        return dec(observed_floor) >= dec(cap)
    return False


def first_proxy(market: dict[str, Any], observations: list[dict[str, Any]],
                offset: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    day = market_day(market)
    start = datetime.combine(day, datetime.min.time(), UTC) - timedelta(hours=offset)
    end = start + timedelta(days=1)
    within = [row for row in observations if start <= stamp(row["at"]) < end]
    found = next((row for row in within if no_proxy(market, row["lower_integer_f"])), None)
    return found, within


def trade_value(row: dict[str, Any]) -> tuple[datetime, Decimal, Decimal, str]:
    yes = dec(row["yes_price_dollars"])
    no = dec(row["no_price_dollars"]) if row.get("no_price_dollars") is not None else 1 - yes
    size = dec(row["count_fp"])
    if yes < 0 or no < 0 or yes > 1 or no > 1 or yes + no != 1 or size <= 0:
        raise ValueError("invalid price or size")
    role = row.get("taker_side")
    return stamp(row["created_time"]), no, size, role if role in ("yes", "no") else "unknown"


def summarize_prints(rows: list[dict[str, Any]], proxy_at: datetime,
                     arrival_seconds: int = 0) -> dict[str, Any]:
    """Keep negative, end-boundary and duplicate prints out. No inferred fills."""
    accepted: list[tuple[Decimal, Decimal, str]] = []
    observed_prints: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    excluded: Counter[str] = Counter()
    minutes: dict[str, Decimal] = {"0_60": Decimal(0), "60_120": Decimal(0), "120_180": Decimal(0)}
    for row in rows:
        identity = row.get("trade_id")
        if not isinstance(identity, str) or not identity:
            excluded["missing_trade_id"] += 1
            continue
        payload = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if identity in seen:
            if seen[identity] != payload:
                raise ValueError("conflicting duplicate trade_id")
            excluded["duplicate_trade_id"] += 1
            continue
        seen[identity] = payload
        try:
            at, price, size, role = trade_value(row)
        except (KeyError, ValueError, InvalidOperation):
            excluded["invalid_trade"] += 1
            continue
        delay = (at - proxy_at).total_seconds()
        if not arrival_seconds <= delay < 180:
            excluded["outside_interval"] += 1
            continue
        accepted.append((price, size, role))
        observed_prints.append({"trade_id": identity, "delay_seconds": delay,
            "no_price": str(price), "contracts": str(size), "taker_side": role})
        minute = "0_60" if delay < 60 else "60_120" if delay < 120 else "120_180"
        minutes[minute] += size
    total = sum((size for _, size, _ in accepted), Decimal(0))
    cost = sum((price * size for price, size, _ in accepted), Decimal(0))
    target = [(p, s, r) for p, s, r in accepted if Decimal("0.97") <= p <= Decimal("0.98")]
    return {
        "prints": len(accepted), "contracts": str(total),
        "weighted_no_price": str(cost / total) if total else None,
        "min_no_price": str(min(p for p, _, _ in accepted)) if accepted else None,
        "max_no_price": str(max(p for p, _, _ in accepted)) if accepted else None,
        "contracts_at_97": str(sum((s for p, s, _ in accepted if p == Decimal("0.97")), Decimal(0))),
        "contracts_at_98": str(sum((s for p, s, _ in accepted if p == Decimal("0.98")), Decimal(0))),
        "target_contracts": str(sum((s for _, s, _ in target), Decimal(0))),
        "below_97_contracts": str(sum((s for p, s, _ in accepted if p < Decimal("0.97")), Decimal(0))),
        "above_98_contracts": str(sum((s for p, s, _ in accepted if p > Decimal("0.98")), Decimal(0))),
        "target_no_taker_contracts": str(sum((s for _, s, r in target if r == "no"), Decimal(0))),
        "target_yes_taker_contracts": str(sum((s for _, s, r in target if r == "yes"), Decimal(0))),
        "target_unknown_taker_contracts": str(sum((s for _, s, r in target if r == "unknown"), Decimal(0))),
        "minute_contracts": {key: str(value) for key, value in minutes.items()},
        "excluded": dict(excluded), "observed_prints": observed_prints,
        "achievable_fills": None, "achievable_pnl": None,
    }


class PublicClient:
    """GET only, content-addressed raw cache, bounded retries and shared public rate budget."""

    def __init__(self, output: Path) -> None:
        self.output = output
        self.raw = output / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.previous_request = 0.0

    def _wait(self) -> None:
        with Path("/tmp/lab9-kalshi-rate.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            clock = Path("/tmp/lab9-kalshi-last-request")
            previous = float(clock.read_text()) if clock.exists() else 0.0
            delay = max(previous + 0.51, self.previous_request + 1.01) - time.time()
            if delay > 0:
                time.sleep(delay)
            self.previous_request = time.time()
            clock.write_text(str(self.previous_request))

    def get(self, url: str, params: list[tuple[str, Any]] | None = None) -> str:
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        identity = hashlib.sha256(full.encode()).hexdigest()
        body_path = self.raw / f"{identity}.body"
        meta_path = self.raw / f"{identity}.json"
        if body_path.exists() and meta_path.exists():
            cached = body_path.read_bytes()
            metadata = json.loads(meta_path.read_text())
            if (metadata.get("url") != full or metadata.get("status") != 200
                    or metadata.get("sha256") != hashlib.sha256(cached).hexdigest()):
                raise ValueError("raw cache integrity mismatch")
            return cached.decode()
        for attempt in range(4):
            if url.startswith(BASE):
                self._wait()
            began = datetime.now(UTC).isoformat()
            request = urllib.request.Request(full, headers={"User-Agent": "nightcrawler-public-research/1"})
            try:
                with urllib.request.urlopen(request, timeout=100) as response:
                    body = response.read()
                body_path.write_bytes(body)
                meta_path.write_text(json.dumps({"url": full, "started_at": began,
                    "received_at": datetime.now(UTC).isoformat(), "status": 200,
                    "sha256": hashlib.sha256(body).hexdigest()}, indent=2))
                return body.decode()
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise
                retry = exc.headers.get("Retry-After", "")
                try:
                    requested_delay = float(retry)
                except ValueError:
                    try:
                        requested_delay = parsedate_to_datetime(retry).timestamp() - time.time()
                    except (TypeError, ValueError):
                        requested_delay = 0.0
                wait = max(2.0 ** (attempt + 1), requested_delay)
                if not math.isfinite(wait) or wait > 60:
                    # Stop this query instead of violating a long server cooldown.
                    raise
                time.sleep(wait)
        raise RuntimeError("retry loop exhausted")

    def pages(self, path: str, params: dict[str, Any], field: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursors: set[str] = set()
        query = dict(params)
        for _ in range(1000):
            data = json.loads(self.get(BASE + path, list(query.items())))
            page = data[field]
            if not isinstance(page, list):
                raise TypeError("invalid paginated response")
            rows.extend(page)
            cursor = data.get("cursor")
            if not cursor:
                return rows
            if cursor in cursors:
                raise ValueError("repeated pagination cursor")
            cursors.add(cursor)
            query["cursor"] = cursor
        raise ValueError("pagination incomplete")


def write_tables(result: dict[str, Any], output: Path) -> None:
    """Portable city/day zeros and per-print evidence; no hypothetical-fill column."""
    days = [START + timedelta(days=offset) for offset in range((END - START).days + 1)]
    columns = ["series", "day", "markets", "proxy_markets", "complete_trade_windows",
               "proxy_contradictions", "prints", "contracts", "target_contracts",
               "target_no_taker_contracts", "target_yes_taker_contracts"]
    with (output / "weather_daily.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for series in SERIES:
            for day in days:
                rows = [r for r in result["markets"] if r["series"] == series and r["day"] == str(day)]
                scored = [r["stresses"]["0"] for r in rows if "0" in r["stresses"]]
                summary: dict[str, Any] = {"series": series, "day": str(day), "markets": len(rows),
                    "proxy_markets": sum(bool(r["proxy"]) for r in rows),
                    "complete_trade_windows": len(scored),
                    "proxy_contradictions": sum(bool(r["contradiction"]) for r in rows)}
                for column in columns[6:]:
                    summary[column] = str(sum((dec(row[column]) for row in scored), Decimal(0)))
                writer.writerow(summary)
    columns = ["series", "day", "ticker", "proxy_observation_at", "trade_id", "delay_seconds",
               "no_price", "contracts", "taker_side"]
    with (output / "weather_prints.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for market in result["markets"]:
            for trade in market["stresses"].get("0", {}).get("observed_prints", []):
                writer.writerow({"series": market["series"], "day": market["day"],
                    "ticker": market["ticker"], "proxy_observation_at": market["proxy"]["at"], **trade})


def run(output: Path) -> None:
    client = PublicClient(output)
    result: dict[str, Any] = {"plan_sha256": hashlib.sha256(
        Path(__file__).with_name("WEATHER_PLAN.md").read_bytes()).hexdigest(),
        "start": str(START), "end": str(END), "series": {}, "markets": [],
        "verdict": "MEASURE_ONLY: observation-time proxy; fills/availability unverified"}
    for series, (station, climate, offset) in SERIES.items():
        series_row: dict[str, Any] = {}
        result["series"][series] = series_row
        try:
            info = json.loads(client.get(BASE + "/series/" + series))["series"]
            series_row["settlement_sources"] = info.get("settlement_sources")
            series_row["contract_terms_url"] = info.get("contract_terms_url")
            markets = client.pages("/markets", {"series_ticker": series, "status": "settled", "limit": 1000}, "markets")
            markets = [m for m in markets if START <= market_day(m) <= END]
            series_row["markets"] = len(markets)
            params: list[tuple[str, Any]] = [("station", station), ("data", "tmpf"), ("data", "metar"),
                ("year1", 2026), ("month1", 10), ("day1", 4), ("year2", 2026), ("month2", 10), ("day2", 13),
                ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"),
                ("direct", "no"), ("report_type", 3), ("report_type", 4)]
            obs, skipped = parse_observations(client.get(
                "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py", params), station)
            series_row.update({"valid_t_group_observations": len(obs), "observation_exclusions": skipped})
            for market in markets:
                proxy, day_obs = first_proxy(market, obs, offset)
                rules = market.get("rules_primary", "")
                value = market.get("expiration_value")
                maximum = max((dec(row["fahrenheit"]) for row in day_obs), default=None)
                minimum_max = max((row["lower_integer_f"] for row in day_obs), default=None)
                row = {"series": series, "ticker": market["ticker"], "day": str(market_day(market)),
                    "rules_primary": rules, "rules_secondary": market.get("rules_secondary"),
                    "station_token_in_rules": climate in rules, "climate_station": climate,
                    "standard_day_boundary_proven": False,
                    "settlement_source": "TWC" if "Weather Company" in rules else "NWS" if "National Weather Service" in rules else "unknown",
                    "expiration_value": value, "result": market.get("result"), "day_observations": len(day_obs),
                    "metar_max_f": str(maximum) if maximum is not None else None,
                    "conservative_max_integer_f": minimum_max,
                    "metar_max_above_expiration": maximum > dec(value) if maximum is not None and value else None,
                    "conservative_max_above_expiration": minimum_max > dec(value) if minimum_max is not None and value else None,
                    "proxy": proxy, "contradiction": market.get("result") != "no" if proxy else None,
                    "trade_coverage": "not_requested_no_proxy", "stresses": {}}
                if proxy:
                    at = stamp(proxy["at"])
                    try:
                        trades = client.pages("/markets/trades", {"ticker": market["ticker"], "limit": 1000,
                            "min_ts": math.floor(at.timestamp()) - 60,
                            "max_ts": math.ceil(at.timestamp()) + 180}, "trades")
                        wrong = [trade for trade in trades if trade.get("ticker") != market["ticker"]]
                        if wrong:
                            raise ValueError("wrong ticker in public trade page")
                        row["trade_coverage"] = "cursor_exhausted"
                        row["stresses"] = {str(delay): summarize_prints(trades, at, delay) for delay in (0, 30, 60, 120)}
                    except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
                        row["trade_coverage"] = "error:" + type(exc).__name__
                result["markets"].append(row)
                (output / "summary.json").write_text(json.dumps(result, indent=2))
            print(series, "markets", len(markets), "observations", len(obs),
                  "proxy_markets", sum(1 for row in result["markets"] if row["series"] == series and row["proxy"]), flush=True)
        except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
            series_row["error"] = type(exc).__name__
            print(series, "error", type(exc).__name__, flush=True)
        (output / "summary.json").write_text(json.dumps(result, indent=2))

    write_tables(result, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)

"""Public Coinbase hourly evidence; causal spot/volatility, never touch proof.

Run with --directory outside git. The returned feature is a historical OHLC
proxy: availability is conservatively assumed at candle end + five seconds,
not proven by a historical publication/receipt timestamp. Missing candles are
never filled and no return spans a missing hour. CF Benchmarks touch history is
a separate input which this module does not provide.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

HOUR = 3600
RETURNS = 30 * 24
DELAY = 5
ORIGIN = "https://api.exchange.coinbase.com"
PRODUCTS = {"BTC-USD", "ETH-USD"}


@dataclass(frozen=True)
class Candle:
    start: int
    low: float
    high: float
    open: float
    close: float
    volume: float

    @property
    def available_at(self) -> int:
        return self.start + HOUR + DELAY


def number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("Boolean is not an OHLC number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite OHLC number")
    return result


def parse_rows(payload: Any) -> dict[int, Candle]:
    if not isinstance(payload, list):
        raise TypeError("Coinbase candles must be an array")
    rows: dict[int, Candle] = {}
    for raw in payload:
        if not isinstance(raw, list) or len(raw) != 6:
            raise ValueError("Coinbase candle must contain six fields")
        start, low, high, opened, close, volume = map(number, raw)
        if start < 0 or start % HOUR or min(low, high, opened, close) <= 0 or volume < 0:
            raise ValueError("Invalid candle hour, price or volume")
        if low > min(opened, close) or high < max(opened, close):
            raise ValueError("OHLC range is inconsistent")
        candle = Candle(int(start), low, high, opened, close, volume)
        if candle.start in rows and rows[candle.start] != candle:
            raise ValueError("Conflicting duplicate Coinbase candle")
        rows[candle.start] = candle
    return rows


def validate_url(url: str, product: str) -> None:
    if product not in PRODUCTS:
        raise ValueError("Only public BTC-USD and ETH-USD candles are allowed")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "api.exchange.coinbase.com"
            or parsed.path != f"/products/{product}/candles" or parsed.fragment):
        raise ValueError("Unexpected public Coinbase candle endpoint")
    if parse_qs(parsed.query).get("granularity") != [str(HOUR)]:
        raise ValueError("Candle evidence must request hourly granularity")


def load_envelopes(paths: Iterable[Path], *, product: str) -> dict[int, Candle]:
    """Load recorded public responses; never accept a candle still open at fetch."""
    combined: dict[int, Candle] = {}
    for path in sorted(paths):
        envelope = json.loads(path.read_text())
        validate_url(envelope["url"], product)
        requested, received = number(envelope["requested_at"]), number(envelope["received_at"])
        if requested > received:
            raise ValueError("Response receipt precedes request")
        for start, candle in parse_rows(envelope["response"]).items():
            if candle.available_at > requested:
                continue
            if start in combined and combined[start] != candle:
                raise ValueError("Conflicting candles across public responses")
            combined[start] = candle
    return combined


def features_at(candles: Mapping[int, Candle], decision_at: float) -> dict[str, Any]:
    """Latest assumed-published close and exactly 720 adjacent hourly returns.

    sigma_hour is the population standard deviation of log close/close returns.
    No exchange index or prior-barrier eligibility is implied by this feature.
    """
    decision = number(decision_at)
    last = math.floor((decision - DELAY) / HOUR) * HOUR - HOUR
    result: dict[str, Any] = {
        "eligible": False, "reason": "missing_latest_closed_hour", "returns": 0,
        "spot": None, "close_start": last, "available_at": last + HOUR + DELAY,
        "sigma_hour": None, "sigma_annual": None,
        "availability": "assumed_candle_end_plus_5s", "touch_history_verified": False,
    }
    if last not in candles:
        return result
    result["spot"] = candles[last].close
    selected = [candles.get(start) for start in range(last - RETURNS * HOUR, last + 1, HOUR)]
    if any(candle is None for candle in selected):
        result["reason"] = "incomplete_720_adjacent_hour_returns"
        result["returns"] = sum(a is not None and b is not None for a, b in pairwise(selected))
        return result
    closes = [candle.close for candle in selected if candle is not None]
    changes = [math.log(b / a) for a, b in pairwise(closes)]
    sigma = statistics.pstdev(changes)
    result.update(returns=len(changes), sigma_hour=sigma, sigma_annual=sigma * math.sqrt(24 * 365))
    if sigma <= 0:
        result["reason"] = "zero_realized_volatility"
        return result
    result.update(eligible=True, reason="available_spot_proxy_only")
    return result


def coverage(candles: Mapping[int, Candle], start: int, end: int) -> dict[str, Any]:
    if start % HOUR or end % HOUR or start >= end:
        raise ValueError("Coverage bounds must be increasing hour boundaries")
    expected = list(range(start, end, HOUR))
    missing = [hour for hour in expected if hour not in candles]
    available = [hour for hour in expected if hour in candles]
    longest, run = 0, 0
    for hour in expected:
        run = 0 if hour in candles else run + 1
        longest = max(longest, run)
    return {"start": start, "end_exclusive": end, "expected_hours": len(expected),
            "observed_hours": len(available), "missing_hours": len(missing),
            "longest_missing_run_hours": longest, "first_start": min(available, default=None),
            "last_start": max(available, default=None), "missing_starts": missing,
            "complete_hourly_grid": not missing, "touch_history_verified": False}


def retry_delay(header: str | None, now: float, attempt: int) -> float:
    fallback = float(2 ** attempt)
    if header is None:
        return fallback
    try:
        delay = number(header)
    except (ValueError, TypeError):
        try:
            parsed = parsedate_to_datetime(header)
            if parsed.tzinfo is None:
                raise ValueError("Retry-After date lacks timezone")
            delay = parsed.timestamp() - now
        except (ValueError, TypeError, OverflowError):
            return fallback
    return max(delay, fallback)


class PublicReader:
    def __init__(self, session: Any = None, clock: Any = time.time, sleep: Any = time.sleep):
        self.session = session or requests.Session()
        self.clock, self.sleep = clock, sleep
        self.requests = 0
        self.retries = 0

    def fetch(self, product: str, start: int, end: int) -> dict[str, Any]:
        if product not in PRODUCTS or start % HOUR or end % HOUR or not 0 < end - start <= 299 * HOUR:
            raise ValueError("Public hourly request must cover 1..299 whole hours")
        url = f"{ORIGIN}/products/{product}/candles"
        params = {"start": iso(start), "end": iso(end), "granularity": str(HOUR)}
        for attempt in range(6):
            requested = self.clock()
            response = self.session.get(url, params=params, timeout=40, allow_redirects=False)
            received = self.clock()
            self.requests += 1
            if response.status_code == 429 or 500 <= response.status_code < 600:
                self.retries += 1
                delay = retry_delay(response.headers.get("Retry-After"), received, attempt)
                if delay > 60:
                    raise ValueError("Long Retry-After: stop collection and resume after the required wait")
                self.sleep(delay)
                continue
            if response.status_code != 200:
                raise ValueError(f"Public Coinbase HTTP {response.status_code}")
            payload = response.json()
            parse_rows(payload)
            response_url = requests.Request("GET", url, params=params).prepare().url
            self.sleep(.35)
            return {"url": response_url, "requested_at": requested,
                    "received_at": received, "response": payload}
        raise ValueError("Coinbase public retry budget exhausted")


def iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def collect(directory: Path, product: str, start: int, end: int,
            *, reader: PublicReader | None = None) -> dict[str, Any]:
    if start % HOUR or end % HOUR or start >= end:
        raise ValueError("Collection bounds must be increasing hour boundaries")
    api = reader or PublicReader()
    paths = []
    for left in range(start, end, 299 * HOUR):
        right = min(end, left + 299 * HOUR)
        path = directory / product / f"{left}-{right}.json"
        if not path.exists():
            atomic_json(path, api.fetch(product, left, right))
        envelope = json.loads(path.read_text())
        validate_url(envelope["url"], product)
        params = parse_qs(urlparse(envelope["url"]).query)
        if params.get("start") != [iso(left)] or params.get("end") != [iso(right)]:
            raise ValueError("Cached public response has different requested bounds")
        paths.append(path)
    candles = load_envelopes(paths, product=product)
    report = coverage(candles, start, end)
    report.update(product=product, source="Coinbase Exchange public hourly candles",
                  requests_this_run=api.requests, retries_this_run=api.retries,
                  availability="assumed_candle_end_plus_5s",
                  files=[{"name": str(path.relative_to(directory)),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths])
    atomic_json(directory / product / "coverage.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", default="2024-12-01")
    parser.add_argument("--end", default="2026-10-01")
    parser.add_argument("--products", nargs="+", choices=sorted(PRODUCTS), default=sorted(PRODUCTS))
    args = parser.parse_args()
    start = int(datetime.fromisoformat(args.start).replace(tzinfo=UTC).timestamp())
    end = int(datetime.fromisoformat(args.end).replace(tzinfo=UTC).timestamp())
    for product in args.products:
        report = collect(args.directory, product, start, end)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in {"files", "missing_starts"}}, sort_keys=True))


if __name__ == "__main__":
    main()

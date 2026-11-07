"""Public-only monthly crypto market/print archive; no simulated fills or returns.

Run with ``python research/lab9/kalshi_touch_data.py --output /tmp/lab9-kalshi-touch``.
Both storage tiers are exhausted, raw strings/fields are preserved, and a fixed capture
cutoff excludes later prints. Existing successful pages are verified before reuse.
The shared flock coordinates requests with the weather collector in this session.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Event
from typing import Any

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
MONTHLY = ("KXBTCMAXMON", "KXBTCMINMON", "KXETHMAXMON", "KXETHMINMON")
ANNUAL = ("KXBTCMAXY", "KXBTCMINY", "KXETHMAXY")
RATE_LOCK = Path("/tmp/lab9-kalshi-rate.lock")
RATE_LAST = Path("/tmp/lab9-kalshi-last-request")
Json = dict[str, Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, path)


def rate_limit() -> None:
    """At most two starts/second across cooperating processes on this host."""
    with RATE_LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        last = float(RATE_LAST.read_text()) if RATE_LAST.exists() else 0.0
        delay = max(0.0, last + 0.55 - time.time())
        if delay:
            time.sleep(delay)
        RATE_LAST.write_text(str(time.time()))


def retry_delay(header: str, now: float) -> float:
    """Honor numeric and HTTP-date server advice; never shorten a requested wait."""
    try:
        seconds = float(header)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(header).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            return 0.0
    return max(0.0, seconds)


def trade_time(row: Json) -> float:
    value = datetime.fromisoformat(row["created_time"])
    if value.tzinfo is None:
        raise ValueError("Trade timestamp has no timezone")
    return value.timestamp()


def public_path(path: str) -> bool:
    """Credentials and account/order endpoints cannot enter this collector."""
    return path in {
        "/historical/cutoff", "/markets", "/historical/markets",
        "/markets/trades", "/historical/trades", "/events", "/events/fee_changes",
        "/series/fee_changes",
    } or path in {f"/series/{ticker}" for ticker in MONTHLY + ANNUAL}


class PublicArchive:
    def __init__(
        self, output: Path, *, get: Callable[..., Any] | None = None,
        wait: Callable[[], None] = rate_limit, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.get = get or requests.get
        self.wait = wait
        self.sleep = sleep
        self.halted = Event()

    def request(self, path: str, params: Json, *, refresh: bool = False) -> Json:
        if not public_path(path):
            raise ValueError("Only allowlisted public GET endpoints are permitted")
        identity = json.dumps([path, params], sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256(identity.encode()).hexdigest()
        target = self.output / "pages" / f"{key}.json"
        if refresh:
            target = target.with_name(f"{key}.{time.time_ns()}.json")
        if target.exists():
            saved = json.loads(target.read_text())
            raw = saved["body"]
            if saved["request"] != identity or hashlib.sha256(raw.encode()).hexdigest() != saved["sha256"]:
                raise ValueError("Cached page checksum/request mismatch")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise TypeError("Expected JSON object")
            return result
        for attempt in range(6):
            pause = self.output / "retry_after.json"
            if pause.exists() and json.loads(pause.read_text())["resume_not_before_unix"] > time.time():
                raise RuntimeError("Collector is still inside server Retry-After interval")
            if self.halted.is_set():
                raise RuntimeError("Collector paused after server Retry-After")
            self.wait()
            if self.halted.is_set():
                raise RuntimeError("Collector paused after server Retry-After")
            requested_at = utc_now()
            try:
                reply = self.get(BASE + path, params=params, timeout=40, allow_redirects=False)
            except requests.RequestException as exc:
                self._journal(path, params, attempt, requested_at, utc_now(), None, type(exc).__name__)
                if attempt == 5:
                    raise
                self.sleep(min(30, 2 ** attempt))
                continue
            received_at = utc_now()
            self._journal(path, params, attempt, requested_at, received_at, reply.status_code, None)
            if reply.status_code == 429 or reply.status_code >= 500:
                if attempt == 5:
                    reply.raise_for_status()
                header = reply.headers.get("Retry-After", "")
                delay = max(float(2 ** attempt), retry_delay(header, time.time()))
                if delay > 60:
                    self.halted.set()
                    dump(self.output / "retry_after.json", {"resume_not_before_unix": time.time() + delay})
                    raise RuntimeError("Server Retry-After exceeds 60 seconds; stop and resume after its deadline")
                self.sleep(delay)
                continue
            if reply.status_code != 200:
                raise ValueError(f"Public GET {path} returned HTTP {reply.status_code}")
            raw = reply.text
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise TypeError("Expected JSON object")
            dump(target, {
                "request": identity, "requested_at": requested_at, "received_at": received_at,
                "captured_at": received_at, "body": raw,
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            })
            return result
        raise RuntimeError("Public request exhausted retries")

    def _journal(self, path: str, params: Json, attempt: int, requested_at: str, received_at: str, status: int | None, error: str | None) -> None:
        with (self.output / "requests.jsonl").open("a") as stream:
            stream.write(json.dumps({"path": path, "params": params, "attempt": attempt,
                                     "requested_at": requested_at, "received_at": received_at,
                                     "status": status, "error": error}) + "\n")

    def pages(self, path: str, params: Json, collection: str) -> tuple[list[Json], int]:
        rows: list[Json] = []
        cursor = ""
        seen: set[str] = set()
        count = 0
        while True:
            query = dict(params)
            if cursor:
                query["cursor"] = cursor
            body = self.request(path, query)
            values = body.get(collection)
            if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
                raise ValueError(f"Missing/malformed {collection}")
            rows.extend(values)
            count += 1
            next_cursor = body.get("cursor")
            if not isinstance(next_cursor, str):
                raise TypeError("Missing/malformed cursor")
            cursor = next_cursor
            if not cursor:
                return rows, count
            if cursor in seen:
                raise ValueError("Repeated cursor; incomplete archive")
            seen.add(cursor)


def merge_trades(groups: list[list[Json]]) -> tuple[list[Json], int]:
    """Only exact duplicate trade IDs collapse; conflicting observations abort."""
    trades: dict[str, Json] = {}
    duplicate = 0
    for rows in groups:
        for row in rows:
            key = row.get("trade_id")
            if not isinstance(key, str) or not key:
                raise ValueError("Missing trade ID")
            if key in trades:
                if row != trades[key]:
                    raise ValueError("Conflicting copies of a trade ID")
                duplicate += 1
            trades[key] = row
    return sorted(trades.values(), key=lambda row: (trade_time(row), row["trade_id"])), duplicate


def inventory(archive: PublicArchive) -> Json:
    path = archive.output / "inventory.json"
    if path.exists():
        return json.loads(path.read_text())
    result: Json = {"captured_at": utc_now(), "cutoff_unix": int(time.time()), "series": {}, "annual": {}}
    result["archive_cutoff"] = archive.request("/historical/cutoff", {})
    for ticker in MONTHLY + ANNUAL:
        data: Json = {"definition": archive.request(f"/series/{ticker}", {})}
        data["fee_changes"] = archive.request("/series/fee_changes", {"series_ticker": ticker, "show_historical": "true"})
        data["live_markets"], data["live_market_pages"] = archive.pages("/markets", {"series_ticker": ticker, "limit": 1000}, "markets")
        data["historical_markets"], data["historical_market_pages"] = archive.pages("/historical/markets", {"series_ticker": ticker, "limit": 1000}, "markets")
        data["events"], data["event_pages"] = archive.pages("/events", {"series_ticker": ticker, "limit": 200}, "events")
        data["event_fee_changes"] = {}
        for event in data["events"]:
            event_ticker = event["event_ticker"]
            rows, pages = archive.pages("/events/fee_changes", {"event_ticker": event_ticker, "limit": 1000}, "event_fee_changes")
            data["event_fee_changes"][event_ticker] = {"rows": rows, "pages": pages}
        result["series" if ticker in MONTHLY else "annual"][ticker] = data
        dump(archive.output / "inventory.partial.json", result)
        print(json.dumps({"series": ticker, "live": len(data["live_markets"]), "historical": len(data["historical_markets"]), "events": len(data["events"])}), flush=True)
    dump(path, result)
    return result


def collect_market(archive: PublicArchive, series: str, ticker: str, cutoff: int) -> tuple[str, Json]:
    groups = []
    page_counts = {}
    for route in ("/markets/trades", "/historical/trades"):
        rows, pages = archive.pages(route, {"ticker": ticker, "limit": 1000, "max_ts": cutoff}, "trades")
        if any(row.get("ticker") != ticker for row in rows):
            raise ValueError("Trade endpoint ignored ticker filter")
        if any(trade_time(row) > cutoff for row in rows):
            raise ValueError("Trade endpoint ignored frozen capture cutoff")
        groups.append(rows)
        page_counts[route] = pages
    merged, duplicates = merge_trades(groups)
    target = archive.output / "trades" / f"{ticker}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in merged))
    summary = {"series": series, "trades": len(merged), "duplicates": duplicates,
               "pages": page_counts, "first": merged[0]["created_time"] if merged else None,
               "last": merged[-1]["created_time"] if merged else None,
               "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    return ticker, summary


def collect(archive: PublicArchive, *, inventory_only: bool = False, workers: int = 1) -> Json:
    if not 1 <= workers <= 4:
        raise ValueError("Use one to four workers, sharing the same global rate limit")
    data = inventory(archive)
    manifest: Json = {"inventory_captured_at": data["captured_at"], "cutoff_unix": data["cutoff_unix"], "markets": {}, "complete": False}
    if inventory_only:
        return manifest
    jobs = []
    for series, record in data["series"].items():
        # Keep every raw metadata version above, but collect each finalized ticker once.
        markets = {row["ticker"]: row for row in record["historical_markets"] + record["live_markets"]}
        for ticker, market in sorted(markets.items()):
            if market.get("status") != "finalized" or market.get("result") not in {"yes", "no"}:
                continue
            jobs.append((series, ticker))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(collect_market, archive, series, ticker, data["cutoff_unix"]) for series, ticker in jobs]
        for future in futures:
            ticker, summary = future.result()
            manifest["markets"][ticker] = summary
            dump(archive.output / "manifest.json", manifest)
            print(json.dumps({"ticker": ticker, **summary}), flush=True)
    manifest["complete"] = True
    manifest["final_archive_cutoff"] = archive.request("/historical/cutoff", {}, refresh=True)
    manifest["archive_cutoff_changed"] = manifest["final_archive_cutoff"] != data["archive_cutoff"]
    manifest["snapshot_atomic"] = False
    manifest["completed_at"] = utc_now()
    dump(archive.output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/lab9-kalshi-touch"))
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--workers", type=int, default=1, choices=range(1, 5))
    args = parser.parse_args()
    collect(PublicArchive(args.output), inventory_only=args.inventory_only, workers=args.workers)


if __name__ == "__main__":
    main()

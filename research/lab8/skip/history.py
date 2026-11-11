"""Reproducible PUBLIC Polymarket wallet-history download; no credentials.

python research/lab8/skip/history.py pull --directory /tmp/skip-history
python research/lab8/skip/history.py summarize --directory /tmp/skip-history

Raw compressed response pages and manifests stay outside git. A fixed cutoff
and keyset cursors bound the walk; they do not promise an immutable server-side
snapshot or independently prove the index covers every Polygon event.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Callable, Iterator
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

WALLET = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
BASE = "https://data-api.polymarket.com/v2/"
ALLOWED = {"activity", "trades", "user-pnl", "value", "positions", "activity/combos", "positions/combos"}
IDENTITY = ("proxy_wallet", "timestamp", "type", "side", "token_id", "condition_id",
            "size", "usdc_size", "price", "transaction_hash")


def packed(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(packed(value))
    temporary.replace(path)


class PublicReader:
    def __init__(self, *, session: Any = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, spacing: float = 1.0) -> None:
        self.session = session or requests.Session()
        self.clock, self.sleep, self.spacing = clock, sleep, spacing
        self.last_request: float | None = None
        self.retries: list[dict[str, Any]] = []

    def get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        if endpoint not in ALLOWED or params.get("user") != WALLET:
            raise ValueError("Only the fixed public wallet and public endpoints are allowed")
        url = BASE + endpoint + "?" + urlencode(params)
        for attempt in range(7):
            if self.last_request is not None:
                self.sleep(max(0.0, self.spacing - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            try:
                response = self.session.get(url, timeout=(3.05, 30), allow_redirects=False)
                status = response.status_code
                if status not in {429, 500, 502, 503, 504}:
                    if status != 200:
                        raise ValueError(f"Public history HTTP status {status}")
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("Public history response is not an object")
                    return {"requested_at": self.last_request, "received_at": self.clock(),
                            "url": url, "response": payload}
                delay = min(60.0, 2.0 ** attempt)
                retry = response.headers.get("Retry-After")
                if retry:
                    try:
                        delay = max(delay, float(retry))
                    except ValueError:
                        delay = max(delay, parsedate_to_datetime(retry).timestamp() - self.clock())
                reason = f"http_{status}"
            except (requests.Timeout, requests.ConnectionError):
                delay, reason = min(60.0, 2.0 ** attempt), "transport"
            self.retries.append({"at": self.clock(), "endpoint": endpoint, "reason": reason,
                                 "wait_s": delay, "attempt": attempt + 1})
            self.sleep(max(0.0, delay))
        raise RuntimeError("Public history retries exhausted; coverage is incomplete")


def validate_page(payload: dict[str, Any], *, expected_offset: int) -> tuple[list[dict[str, Any]], str | None]:
    rows, pagination = payload.get("data"), payload.get("pagination")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Malformed history rows")
    if not isinstance(pagination, dict) or type(pagination.get("has_more")) is not bool:
        raise ValueError("Missing exact pagination status")
    if pagination.get("offset") != expected_offset or type(pagination.get("limit")) is not int:
        raise ValueError("Pagination offset or limit changed")
    if len(rows) > pagination["limit"] or pagination["limit"] <= 0:
        raise ValueError("Invalid page size")
    cursor = pagination.get("next_cursor")
    if pagination["has_more"]:
        if not isinstance(cursor, str) or not cursor or not rows:
            raise ValueError("Continuation requires rows and a cursor")
    elif cursor is not None:
        raise ValueError("Terminal page contradicts cursor")
    for row in rows:
        if row.get("proxy_wallet", "").lower() != WALLET:
            raise ValueError("History row belongs to a different wallet")
    return rows, cursor


def walk(reader: PublicReader, directory: Path, name: str, endpoint: str,
         params: dict[str, Any], *, max_pages: int | None = None) -> dict[str, Any]:
    target = directory / name
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["endpoint"] != endpoint or manifest["params"] != params:
            raise ValueError("Resume parameters differ from frozen history request")
        # Validate all completed pages before trusting their resume cursor.
        for _ in iter_pages(target):
            pass
    else:
        manifest = {"version": 1, "endpoint": endpoint, "params": params,
                    "started_at": reader.clock(), "complete": False, "rows": 0,
                    "next_cursor": None, "pages": [], "retries": [],
                    "coverage": "available public index; no independent on-chain completeness proof"}
    if manifest["complete"]:
        return manifest
    cursors = {page["next_cursor"] for page in manifest["pages"] if page["next_cursor"]}
    try:
        while max_pages is None or len(manifest["pages"]) < max_pages:
            query = dict(params)
            if manifest["next_cursor"]:
                query["cursor"] = manifest["next_cursor"]
            envelope = reader.get(endpoint, query)
            rows, cursor = validate_page(envelope["response"], expected_offset=manifest["rows"])
            if cursor and cursor in cursors:
                raise ValueError("Cursor loop; refusing duplicated page accounting")
            stamps = [row["timestamp"] for row in rows if "timestamp" in row]
            if stamps and (any(type(stamp) is not int for stamp in stamps)
                           or min(stamps) < params.get("start", 0)
                           or max(stamps) > params.get("end", math.inf)):
                raise ValueError("History timestamp lies outside frozen request")
            body = packed(envelope)
            filename = f"page-{len(manifest['pages']):06d}.json.gz"
            temp = target / (filename + ".tmp")
            with gzip.open(temp, "wb", compresslevel=6) as stream:
                stream.write(body)
            temp.replace(target / filename)
            manifest["pages"].append({"file": filename, "sha256": digest(body), "rows": len(rows),
                                      "first_at": min(stamps) if stamps else None,
                                      "last_at": max(stamps) if stamps else None,
                                      "next_cursor": cursor, "received_at": envelope["received_at"]})
            manifest["rows"] += len(rows)
            manifest["next_cursor"] = cursor
            manifest["complete"] = cursor is None
            manifest["updated_at"] = reader.clock()
            manifest["retries"] = list(reader.retries)
            manifest.pop("error", None)
            atomic_json(manifest_path, manifest)
            if len(manifest["pages"]) % 25 == 0 or manifest["complete"]:
                print(json.dumps({"stream": name, "pages": len(manifest["pages"]),
                                  "rows": manifest["rows"], "complete": manifest["complete"]}), flush=True)
            if manifest["complete"]:
                break
            cursors.add(cursor)
    except Exception as error:
        manifest["error"] = type(error).__name__
        manifest["updated_at"] = reader.clock()
        manifest["retries"] = list(reader.retries)
        atomic_json(manifest_path, manifest)
        raise
    return manifest


def iter_pages(target: Path) -> Iterator[dict[str, Any]]:
    manifest = json.loads((target / "manifest.json").read_text())
    offset, previous_cursor = 0, None
    seen_cursors: set[str] = set()
    for page in manifest["pages"]:
        with gzip.open(target / page["file"], "rb") as stream:
            raw = stream.read()
        if digest(raw) != page["sha256"]:
            raise ValueError("History page digest mismatch")
        envelope = json.loads(raw)
        expected = {key: [str(value)] for key, value in manifest["params"].items()}
        if previous_cursor:
            expected["cursor"] = [previous_cursor]
        url = urlsplit(envelope["url"])
        if (url.scheme != "https" or url.netloc != "data-api.polymarket.com"
                or url.path != "/v2/" + manifest["endpoint"] or parse_qs(url.query) != expected):
            raise ValueError("History cursor chain or frozen request changed")
        rows, cursor = validate_page(envelope["response"], expected_offset=offset)
        if len(rows) != page["rows"] or cursor != page["next_cursor"]:
            raise ValueError("History manifest disagrees with page")
        if cursor and cursor in seen_cursors:
            raise ValueError("Saved cursor loop")
        if cursor:
            seen_cursors.add(cursor)
        previous_cursor = cursor
        offset += len(rows)
        yield envelope
    if offset != manifest["rows"]:
        raise ValueError("History manifest row count mismatch")
    if (manifest["next_cursor"] != previous_cursor
            or manifest["complete"] != bool(manifest["pages"] and previous_cursor is None)):
        raise ValueError("History manifest completion or resume cursor mismatch")


def iter_rows(target: Path) -> Iterator[dict[str, Any]]:
    """Stable economic identity + ordinal preserves indistinguishable real fills.

    A completed page is consumed exactly once. Never collapse identical rows:
    the public API lacks a unique per-wallet fill/log ID, and real fills can have
    identical economics. Mutable Gamma/profile enrichment is not identity.
    """
    seen: Counter[str] = Counter()
    for envelope in iter_pages(target):
        for row in envelope["response"]["data"]:
            key = digest(packed({field: row.get(field) for field in IDENTITY}))
            ordinal = seen[key]
            seen[key] += 1
            yield {**row, "history_row_id": f"{key}:{ordinal}"}


def pull(directory: Path, *, only: str | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    setup = directory / "request.json"
    if setup.exists():
        request = json.loads(setup.read_text())
    else:
        request = {"wallet": WALLET, "cutoff": int(time.time()), "created_at": time.time(),
                   "source": "https://data-api.polymarket.com/v2/openapi.json"}
        atomic_json(setup, request)
    reader = PublicReader()
    shared = {"user": WALLET, "start": 1, "end": request["cutoff"], "limit": 1000}
    specs = {
        "activity": ("activity", {**shared, "sort_direction": "ASC", "exclude_deposits_withdrawals": "false"}),
        "tips": ("activity", {**shared, "sort_direction": "ASC", "type": "TIP"}),
        "trades": ("trades", {**shared, "taker_only": "false", "filter_type": "TOKENS", "filter_amount": "0.000000001"}),
        "taker_trades": ("trades", {**shared, "taker_only": "true", "filter_type": "TOKENS", "filter_amount": "0.000000001"}),
    }
    if only in (None, "aggregates"):
        for name, endpoint, params in [
            ("pnl-daily", "user-pnl", {"user": WALLET, "interval": "max", "fidelity": "1d"}),
            ("value", "value", {"user": WALLET}),
        ]:
            path = directory / (name + ".json")
            if not path.exists():
                atomic_json(path, reader.get(endpoint, params))
    for name, (endpoint, params) in specs.items():
        if only is None or only == name:
            walk(reader, directory, name, endpoint, params)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pull", "summarize"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--only", choices=["activity", "tips", "trades", "taker_trades", "aggregates"])
    args = parser.parse_args()
    if args.command == "pull":
        pull(args.directory, only=args.only)
    else:
        from history_analysis import summarize
        summary = summarize(args.directory)
        atomic_json(args.directory / "summary.json", summary)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

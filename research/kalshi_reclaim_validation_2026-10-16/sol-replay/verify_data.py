"""Verify public download receipts and derived files against their raw inputs."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any


def verify_dataset(data: Path, start_text: str, end_text: str) -> dict[str, Any]:
    start = int(
        dt.datetime.fromisoformat(start_text)
        .replace(tzinfo=dt.timezone.utc)
        .timestamp()
    )
    end = int(
        dt.datetime.fromisoformat(end_text).replace(tzinfo=dt.timezone.utc).timestamp()
    )
    receipts = {}
    for file in sorted(data.glob("*.receipt.json")):
        rawfile = file.with_name(file.name.removesuffix(".receipt.json"))
        receipt = json.loads(file.read_text())
        raw = rawfile.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if receipt.get("sha256") != digest or receipt.get("bytes") != len(raw):
            raise ValueError("Raw input receipt mismatch: " + rawfile.name)
        receipts[rawfile.name] = digest
    for pattern in (
        "book_*.csv.gz",
        "settle_*.csv",
        "candles_*.json",
        "coinbase_*_*.json",
        "markets_????-??-??_*.json",
    ):
        for rawfile in data.glob(pattern):
            if rawfile.name.endswith(".receipt.json"):
                continue
            if rawfile.name not in receipts:
                raise ValueError("Missing raw input receipt: " + rawfile.name)
    selected = []
    for day in range(start, end, 86400):
        date = dt.datetime.fromtimestamp(day, dt.timezone.utc).date().isoformat()
        raw_markets = []
        for rawfile in sorted(data.glob(f"markets_{date}_*.json")):
            if rawfile.name.endswith(".receipt.json"):
                continue
            raw_markets.extend(json.loads(rawfile.read_text())["markets"])
        for row in raw_markets:
            opened = int(
                dt.datetime.fromisoformat(
                    row["open_time"].replace("Z", "+00:00")
                ).timestamp()
            )
            closed = int(
                dt.datetime.fromisoformat(
                    row["close_time"].replace("Z", "+00:00")
                ).timestamp()
            )
            if (
                day <= opened
                and closed <= day + 86400
                and closed - opened == 900
                and row["ticker"].startswith("KXBTC15M-")
            ):
                selected.append(row)
    saved_markets = json.loads((data / "markets_all.json").read_text())
    if selected != saved_markets:
        raise ValueError(
            "Normalized market metadata not derived from received raw responses"
        )
    candles: dict[int, Any] = {}
    for file in sorted(data.glob("coinbase_*_*.json")):
        if file.name.endswith(".receipt.json"):
            continue
        for row in json.loads(file.read_text()):
            stamp = int(row[0])
            if stamp >= end:
                raise ValueError("Future-period Bitcoin row")
            if start - 8 * 3600 <= stamp < end:
                if stamp in candles and candles[stamp] != row:
                    raise ValueError("Conflicting raw Bitcoin bars")
                candles[stamp] = row
    normalized = [candles[k] for k in sorted(candles)]
    if normalized != json.loads((data / "coinbase_normalized.json").read_text()):
        raise ValueError("Normalized Bitcoin not derived from received raw responses")
    expected = set(range(start - 8 * 3600, end, 60))
    return {
        "verified_receipts": len(receipts),
        "market_normalization_verified": True,
        "bitcoin_normalization_verified": True,
        "missing_btc_minute_starts": sorted(expected - set(candles)),
        "raw_sha256": receipts,
    }

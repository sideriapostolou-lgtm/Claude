"""Bounded public GET-only collector for the declared offline reclaim experiment."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
UTC = dt.timezone.utc
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
RELEASE_PATH = BASE.parent / "RELEASE_METADATA.json"
PERIODS = {
    "dev": ("2026-10-03", "2026-10-04"),
    "val": ("2026-10-04", "2026-10-10"),
    "confirmation": ("2026-10-10", "2026-10-13"),
}


def epoch(date: str) -> int:
    return int(dt.datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp())


def iso(value: int) -> str:
    return dt.datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


class Getter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_call = 0.0

    def get(
        self,
        url: str,
        name: str,
        max_bytes: int = 8 * 1024 * 1024,
        digest: str | None = None,
    ) -> bytes:
        target = self.root / name
        receipt = target.with_name(target.name + ".receipt.json")
        if target.exists() and receipt.exists():
            raw = target.read_bytes()
            if len(raw) > max_bytes:
                raise ValueError(
                    "Cached response exceeded declared byte bound: " + name
                )
            saved = json.loads(receipt.read_text())
            actual = hashlib.sha256(raw).hexdigest()
            if (
                saved["url"] != url
                or saved["sha256"] != actual
                or (digest and actual != digest)
            ):
                raise ValueError("Cached input identity mismatch: " + name)
            return raw
        for attempt in range(3):
            time.sleep(max(0.0, 0.55 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            started = dt.datetime.now(UTC).isoformat()
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "ReadOnlyReclaimResearch/1.0",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=25) as response:
                    raw = response.read(max_bytes + 1)
                    status = response.status
                if len(raw) > max_bytes:
                    raise ValueError("Response exceeded declared byte bound: " + name)
                actual = hashlib.sha256(raw).hexdigest()
                if digest and actual != digest:
                    raise ValueError("Release SHA256 mismatch: " + name)
                meta = {
                    "url": url,
                    "method": "GET",
                    "started_utc": started,
                    "retrieved_utc": dt.datetime.now(UTC).isoformat(),
                    "status": status,
                    "bytes": len(raw),
                    "sha256": actual,
                    "public_no_auth": True,
                }
                target.write_bytes(raw)
                receipt.write_text(json.dumps(meta, indent=2) + "\n")
                return raw
            except urllib.error.HTTPError as exc:
                with (self.root / "http_errors.jsonl").open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "url": url,
                                "status": exc.code,
                                "attempt": attempt + 1,
                                "utc": dt.datetime.now(UTC).isoformat(),
                            }
                        )
                        + "\n"
                    )
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                retry = exc.headers.get("Retry-After", "")
                delay = (
                    float(retry)
                    if retry.replace(".", "", 1).isdigit()
                    else float(2 ** (attempt + 1))
                )
                if delay > 60:
                    raise RuntimeError(
                        "Server requests >60s wait; stop and resume later"
                    ) from exc
                time.sleep(delay)
        raise RuntimeError("Unreachable retry exhaustion")

    def json(self, url: str, name: str) -> Any:
        return json.loads(self.get(url, name))


def query(path: str, params: dict[str, object]) -> str:
    return path + "?" + urllib.parse.urlencode(params)


def ensure_confirmation_gate() -> None:
    gate = BASE.parent / "CONFIRMATION_FREEZE.json"
    if not gate.exists():
        raise RuntimeError("Confirmation sealed: no reviewed code/test freeze receipt")
    saved = json.loads(gate.read_text())
    if not saved.get("independent_review_approved") or not saved.get("tests_passed"):
        raise RuntimeError("Confirmation sealed: review/tests incomplete")
    for item in saved["files"]:
        file = BASE.parent / item["path"]
        if hashlib.sha256(file.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Confirmation sealed: implementation bytes changed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition", choices=PERIODS, required=True)
    args = parser.parse_args()
    if args.partition == "confirmation":
        ensure_confirmation_gate()
    start_text, end_text = PERIODS[args.partition]
    start, end = epoch(start_text), epoch(end_text)
    out = BASE / args.partition
    get = Getter(out)
    release = json.loads(RELEASE_PATH.read_text())
    assets = {x["name"]: x for x in release["assets"]}
    all_markets: list[dict[str, Any]] = []
    for day in range(start, end, 86400):
        date = iso(day)[:10]
        for filename in (f"book_{date}.csv.gz", f"settle_{date}.csv"):
            if args.partition == "dev":
                original = RELEASE_PATH.parent / filename
                if original.exists():
                    import shutil

                    shutil.copyfile(original, out / filename)
                    source_receipts = json.loads(
                        (RELEASE_PATH.parent / "download_receipts.json").read_text()
                    )
                    # Copy only the bytes; create our own identity receipt from published metadata.
                    raw = (out / filename).read_bytes()
                    asset = assets[filename]
                    digest = asset.get("digest", "").removeprefix("sha256:")
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise ValueError("Development asset digest mismatch")
                    (out / (filename + ".receipt.json")).write_text(
                        json.dumps(
                            {
                                "url": asset["browser_download_url"],
                                "sha256": digest,
                                "bytes": len(raw),
                                "source": "Prior bounded development download; no new download",
                                "prior_download_receipts_present": bool(
                                    source_receipts
                                ),
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                    continue
            asset = assets.get(filename)
            if not asset:
                raise RuntimeError("Declared asset absent: " + filename)
            get.get(
                asset["browser_download_url"],
                filename,
                max_bytes=10 * 1024 * 1024,
                digest=asset["digest"].removeprefix("sha256:"),
            )
        markets: list[dict[str, Any]] = []
        cursor = ""
        for page in range(10):
            params: dict[str, object] = {
                "series_ticker": "KXBTC15M",
                "min_close_ts": day + 1,
                "max_close_ts": day + 86400,
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor
            data = get.json(
                query(KALSHI + "/markets", params), f"markets_{date}_{page}.json"
            )
            markets.extend(data["markets"])
            cursor = data.get("cursor", "")
            if not cursor:
                break
        if cursor:
            raise RuntimeError("Market pagination exceeded bound")
        selected = []
        for market in markets:
            opened = int(
                dt.datetime.fromisoformat(
                    market["open_time"].replace("Z", "+00:00")
                ).timestamp()
            )
            closed = int(
                dt.datetime.fromisoformat(
                    market["close_time"].replace("Z", "+00:00")
                ).timestamp()
            )
            if (
                day <= opened
                and closed <= day + 86400
                and closed - opened == 900
                and market["ticker"].startswith("KXBTC15M-")
            ):
                selected.append(market)
        if len({x["ticker"] for x in selected}) != len(selected):
            raise RuntimeError("Duplicate official market metadata")
        (out / f"markets_selected_{date}.json").write_text(
            json.dumps(selected, indent=2) + "\n"
        )
        tickers = sorted(x["ticker"] for x in selected)
        metadata_by_ticker = {x["ticker"]: x for x in selected}
        for batch in range(0, len(tickers), 20):
            batch_tickers = tickers[batch : batch + 20]
            first = min(
                int(
                    dt.datetime.fromisoformat(
                        metadata_by_ticker[t]["open_time"].replace("Z", "+00:00")
                    ).timestamp()
                )
                for t in batch_tickers
            )
            last = max(
                int(
                    dt.datetime.fromisoformat(
                        metadata_by_ticker[t]["close_time"].replace("Z", "+00:00")
                    ).timestamp()
                )
                for t in batch_tickers
            )
            if len(batch_tickers) * (last - first) // 60 > 10000:
                raise RuntimeError(
                    "Bounded batch would exceed documented aggregate candle cap"
                )
            params = {
                "market_tickers": ",".join(batch_tickers),
                "start_ts": first + 1,
                "end_ts": last,
                "period_interval": 1,
                "include_latest_before_start": "false",
            }
            get.json(
                query(KALSHI + "/markets/candlesticks", params),
                f"candles_{date}_{batch // 20}.json",
            )
        all_markets.extend(selected)
        print(
            json.dumps(
                {
                    "partition": args.partition,
                    "day_utc": date,
                    "official_markets": len(selected),
                    "stage": "public_metadata_candles_cached",
                }
            ),
            flush=True,
        )
    candles: dict[int, list[Any]] = {}
    for a in range(start - 8 * 3600, end, 240 * 60):
        b = min(a + 240 * 60, end)
        params = {"start": iso(a), "end": iso(b - 1), "granularity": 60}
        data = get.json(query(COINBASE, params), f"coinbase_{a}_{b}.json")
        if not isinstance(data, list):
            raise ValueError("Unexpected Coinbase response")
        for row in data:
            stamp = int(row[0])
            if stamp >= end:
                raise RuntimeError(
                    "Unexpected future-period Coinbase row; quarantine and disclose exposure"
                )
            if start - 8 * 3600 <= stamp < end:
                if stamp in candles and candles[stamp] != row:
                    raise RuntimeError("Conflicting Coinbase historical bar revision")
                candles[stamp] = row
    (out / "coinbase_normalized.json").write_text(
        json.dumps([candles[k] for k in sorted(candles)]) + "\n"
    )
    (out / "markets_all.json").write_text(json.dumps(all_markets, indent=2) + "\n")
    print(
        json.dumps(
            {
                "partition": args.partition,
                "official_markets": len(all_markets),
                "coinbase_1m_bars": len(candles),
                "expected_1m_bars": (end - start + 8 * 3600) // 60,
                "finished_utc": dt.datetime.now(UTC).isoformat(),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

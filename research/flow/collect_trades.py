"""Polite, resumable collector of early-life trade history for pump.fun graduates.

pump.fun's swap API pages trades newest-first with a cursor of the form
``<slotIndexId>-<timestamp_ms>``. The timestamp part alone positions the cursor,
so any time window can be fetched by starting at the window's end and paging
backwards until the window's start. Windows are fetched oldest-first so that the
launch-period trades (snipers, bundles, the dev's own buys) are always complete
even when a coin's later windows hit the page cap.

Cloudflare limits this endpoint to roughly 20 requests per minute per IP, so the
collector stays well below that and honours ``Retry-After``.

Usage::

    python research/flow/collect_trades.py CENSUS_JSON OUT_DIR [--rpm 12] [--windows 0-1,1-2] [--max-pages 10]
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import random
import time
from pathlib import Path

import requests

TRADES_URL = "https://swap-api.pump.fun/v2/coins/{mint}/trades"
PAGE_LIMIT = 100
# (start, end) offsets from coin creation, in minutes, fetched in this order.
# Pages run newest-first, so a capped window loses its EARLIEST trades; keep
# windows short enough that the page cap is rarely reached.
DEFAULT_WINDOWS = "0-1,1-2"
DEFAULT_MAX_PAGES = 10
KEEP_FIELDS = (
    "slotIndexId", "tx", "timestamp", "userAddress", "type", "program",
    "priceUsd", "priceSol", "amountUsd", "amountSol", "baseAmount",
)

log = logging.getLogger("collect_trades")


class Throttle:
    """Spaces requests evenly to stay under a requests-per-minute budget."""

    def __init__(self, rpm: float) -> None:
        self.interval = 60.0 / rpm
        self.next_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self.next_at:
            time.sleep(self.next_at - now)
        self.next_at = max(now, self.next_at) + self.interval


def parse_ts_ms(iso: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def fetch_page(session: requests.Session, throttle: Throttle, mint: str, cursor: str) -> dict:
    """GET one page, retrying on 429/5xx with Retry-After or exponential backoff."""
    backoff = 10.0
    for _ in range(8):
        throttle.wait()
        try:
            resp = session.get(
                TRADES_URL.format(mint=mint),
                params={"limit": PAGE_LIMIT, "cursor": cursor},
                timeout=30,
            )
        except requests.RequestException as exc:
            log.warning("network error on %s: %s", mint, exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) + 1 if retry_after and retry_after.isdigit() else backoff
            log.info("HTTP %s on %s, sleeping %.0fs", resp.status_code, mint, delay)
            time.sleep(delay)
            backoff = min(backoff * 2, 120)
            continue
        raise RuntimeError(f"HTTP {resp.status_code} for {mint}: {resp.text[:200]}")
    raise RuntimeError(f"gave up on {mint} after repeated throttling")


def fetch_window(session, throttle, mint: str, start_ms: int, end_ms: int, max_pages: int) -> tuple[list[dict], bool]:
    """Fetch trades with start_ms <= ts < end_ms. Returns (trades, complete)."""
    cursor = f"0000000000000000000000-{end_ms}"
    trades: list[dict] = []
    for _ in range(max_pages):
        page = fetch_page(session, throttle, mint, cursor)
        batch = page.get("trades") or []
        for trade in batch:
            ts = parse_ts_ms(trade["timestamp"])
            if ts < start_ms:
                return trades, True
            if ts < end_ms:
                trades.append({k: trade.get(k) for k in KEEP_FIELDS} | {"ts_ms": ts})
        pagination = page.get("pagination") or {}
        if not batch or not pagination.get("hasMore"):
            return trades, True
        cursor = pagination["nextCursor"]
    return trades, False


def collect_coin(session, throttle, coin: dict, out_dir: Path, windows_min: list[tuple[float, float]], max_pages: int) -> dict:
    mint = coin["mint"]
    created_ms = int(coin["created_timestamp"])
    windows = []
    all_trades: list[dict] = []
    for start_min, end_min in windows_min:
        start_ms = created_ms + int(start_min * 60_000)
        end_ms = created_ms + int(end_min * 60_000)
        if end_ms > time.time() * 1000:
            end_ms = int(time.time() * 1000)
        if end_ms <= start_ms:
            break
        trades, complete = fetch_window(session, throttle, mint, start_ms, end_ms, max_pages)
        all_trades.extend(trades)
        windows.append({"start_min": start_min, "end_min": end_min, "trades": len(trades), "complete": complete})
    all_trades.sort(key=lambda t: (t["ts_ms"], t.get("slotIndexId") or ""))
    record = {
        "mint": mint,
        "symbol": coin.get("symbol"),
        "creator": coin.get("creator"),
        "created_ms": created_ms,
        "fetched_at": int(time.time()),
        "windows": windows,
        "trades": all_trades,
    }
    tmp = out_dir / f"{mint}.json.gz.tmp"
    with gzip.open(tmp, "wt") as fh:
        json.dump(record, fh, separators=(",", ":"))
    tmp.rename(out_dir / f"{mint}.json.gz")
    return {"mint": mint, "trades": len(all_trades), "windows": windows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("census")
    parser.add_argument("out_dir")
    parser.add_argument("--rpm", type=float, default=12.0)
    parser.add_argument("--max-coins", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--windows", default=DEFAULT_WINDOWS,
                        help="comma-separated start-end minute offsets from creation, e.g. 0-1,1-2")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="page cap per window")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    census = json.loads(Path(args.census).read_text())
    coins = census["coins"] if isinstance(census, dict) else census
    order = sorted(coins, key=lambda c: c["mint"])
    random.Random(args.seed).shuffle(order)  # unbiased sample at any stopping point

    session = requests.Session()
    session.headers["User-Agent"] = "nightcrawler-research/0.1"
    throttle = Throttle(args.rpm)
    windows_min = [tuple(float(x) for x in w.split("-")) for w in args.windows.split(",")]
    done = 0
    for coin in order:
        if args.max_coins and done >= args.max_coins:
            break
        if (out_dir / f"{coin['mint']}.json.gz").exists():
            done += 1
            continue
        try:
            summary = collect_coin(session, throttle, coin, out_dir, windows_min, args.max_pages)
            done += 1
            log.info("[%d] %s %s trades=%d windows=%s", done, coin.get("symbol"), coin["mint"],
                     summary["trades"], [(w["end_min"], w["trades"], w["complete"]) for w in summary["windows"]])
        except Exception as exc:  # keep going; one bad coin must not stop the run
            log.error("failed %s: %s", coin["mint"], exc)


if __name__ == "__main__":
    main()

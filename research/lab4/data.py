"""Lab 4 data: resolved Polymarket markets and their per-trade tapes before resolution (public APIs, no key).

Research only. The live bot never reads this. Two public endpoints, both verified from this environment on
2026-10-09:

* Gamma ``GET https://gamma-api.polymarket.com/markets/keyset?closed=true&order=closedTime&ascending=false
  &volume_num_min=V&limit=100&after_cursor=C`` lists closed markets newest-resolved first (``closedTime`` is
  monotone across pages; the response is ``{"markets": [...], "next_cursor": "..."}``), with the final
  ``outcomePrices`` (``["1","0"]`` style), the CLOB token ids, volume and the fee flags (``feesEnabled``,
  ``takerBaseFee``, ``makerBaseFee``, ``feeType``). ``limit`` is capped at 100; the plain ``/markets`` endpoint
  rejects ``offset`` > 2000, hence the keyset cursor.
* Data API ``GET https://data-api.polymarket.com/trades?market=<conditionId>&start=S&end=E&limit=10000&offset=K``
  returns the fills of a market newest first, ``limit`` up to 10,000 and ``offset`` at most 10,000; ``start`` /
  ``end`` are unix seconds. The CLOB's ``prices-history`` is EMPTY for resolved markets, so the tape is the only
  public price path of a market that has already resolved. A window that comes back full is split in half until
  it fits (down to :data:`MIN_WINDOW_S`), and overlapping rows are dropped on (tx, asset, ts, price, size, side).

Layout (``$SCRATCH/lab4`` by default; only a small manifest is mirrored to ``research/lab4/data/``)::

    markets.parquet          one row per resolved market (see :func:`market_row`)
    trades/<market id>.parquet   ts, price, size, side, outcome_index, asset, tx  (the last LOOKBACK days + 1 h)
    manifest.json            per market: rows, first / last trade, fetched_at; plus the run arguments

CLI::

    python research/lab4/data.py --since 2026-09-01 --until 2026-10-01 --min-volume 20000 --lookback-days 14
    python research/lab4/data.py --since 2026-07-01 --list-only                 # one listing, then workers:
    python research/lab4/data.py --since 2026-07-01 --until 2026-08-16 --from-list
    python research/lab4/data.py --status
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

API_GAMMA = "https://gamma-api.polymarket.com"
API_DATA = "https://data-api.polymarket.com"
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD",
        "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad",
    )
)
OUT = Path(os.environ.get("LAB4_DATA", str(SCRATCH / "lab4")))
HERE = Path(__file__).resolve().parent

PAGE = 100  # Gamma's cap
TRADES_LIMIT = 10_000  # Data API's cap per request
TRADES_MAX_OFFSET = 10_000
MIN_WINDOW_S = 60  # never split a trade window below one minute (a minute with > 20k fills is kept truncated)
SLEEP_S = 0.35  # ~3 requests / s, well under both APIs' public limits
TRADE_COLUMNS = ["ts", "price", "size", "side", "outcome_index", "asset", "tx"]
UA = {
    "User-Agent": "nightcrawler-research/lab4 (+https://github.com/sideriapostolou-lgtm/Claude)"
}


def _get(url: str, params: dict[str, Any], tries: int = 6) -> Any:
    """GET JSON with backoff; a 429 waits longer. Raises after ``tries`` failures."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60)
            if r.status_code == 429:
                time.sleep(5.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (
            requests.RequestException,
            ValueError,
        ) as e:  # transport / bad JSON: retry with backoff
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {tries} tries: {last}")


def parse_time(value: Any) -> float | None:
    """Gamma timestamps come as ISO (``2026-08-08T20:27:18Z``) or ``2026-08-08 20:27:18+00``; unix seconds UTC."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) >= 3 and text[-3] in "+-" and text[-2:].isdigit():
        text = text + ":00"  # "+00" -> "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = pd.Timestamp(value).to_pydatetime()
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


def market_row(m: dict[str, Any]) -> dict[str, Any]:
    """Flatten one Gamma market. ``winner_index`` is the outcome whose final price is 1 (-1 = no single winner)."""
    outcomes = _json_list(m.get("outcomes"))
    prices = [
        float(p)
        for p in _json_list(m.get("outcomePrices"))
        if str(p).replace(".", "", 1).isdigit()
    ]
    winners = [i for i, p in enumerate(prices) if p >= 0.999]
    events = m.get("events") or [{}]
    event = events[0] if isinstance(events, list) and events else {}
    return {
        "id": str(m.get("id")),
        "condition_id": m.get("conditionId"),
        "question": m.get("question"),
        "slug": m.get("slug"),
        "event_slug": event.get("slug"),
        "event_title": event.get("title"),
        "outcomes": json.dumps(outcomes),
        "outcome_prices": json.dumps(prices),
        "token_ids": json.dumps(_json_list(m.get("clobTokenIds"))),
        "n_outcomes": len(outcomes),
        "winner_index": winners[0] if len(winners) == 1 else -1,
        "closed_time": parse_time(m.get("closedTime")),
        "end_date": parse_time(m.get("endDate")),
        "start_date": parse_time(m.get("startDate")),
        "volume": float(m.get("volumeNum") or 0.0),
        "liquidity": float(m.get("liquidityNum") or 0.0),
        "fees_enabled": bool(m.get("feesEnabled")),
        "taker_base_fee": int(m.get("takerBaseFee") or 0),
        "maker_base_fee": int(m.get("makerBaseFee") or 0),
        "fee_type": m.get("feeType"),
        "neg_risk": bool(m.get("negRisk")),
        "resolution_status": m.get("umaResolutionStatus"),
        "resolved_by": m.get("resolvedBy"),
    }


def list_resolved(
    since: datetime,
    until: datetime,
    min_volume: float = 0.0,
    max_pages: int | None = None,
) -> pd.DataFrame:
    """Resolved markets with ``since <= closedTime <= until`` and volume >= ``min_volume``, newest first."""
    since_ts, until_ts = since.timestamp(), until.timestamp()
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    pages, stop = 0, False
    while not stop:
        params: dict[str, Any] = {
            "limit": PAGE,
            "closed": "true",
            "order": "closedTime",
            "ascending": "false",
            "volume_num_min": min_volume,
        }
        if cursor:
            params["after_cursor"] = cursor
        reply = _get(f"{API_GAMMA}/markets/keyset", params)
        page = reply.get("markets") if isinstance(reply, dict) else None
        if not isinstance(page, list) or not page:
            break
        cursor = reply.get("next_cursor") or None
        for m in page:
            ct = parse_time(m.get("closedTime"))
            if ct is None:
                continue
            if ct > until_ts:
                continue
            if ct < since_ts:
                stop = True
                break
            rows.append(market_row(m))
        pages += 1
        if cursor is None or (max_pages is not None and pages >= max_pages):
            break
        time.sleep(SLEEP_S)
    df = pd.DataFrame(rows, columns=list(market_row({}).keys()))
    if df.empty:
        return df
    keep = (
        (df["resolution_status"] == "resolved")
        & (df["volume"] >= min_volume)
        & df["closed_time"].notna()
    )
    return (
        df[keep]
        .drop_duplicates("id")
        .sort_values("closed_time", ascending=False)
        .reset_index(drop=True)
    )


def _trades_window(condition_id: str, start: int, end: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in (0, TRADES_MAX_OFFSET):
        page = _get(
            f"{API_DATA}/trades",
            {
                "market": condition_id,
                "limit": TRADES_LIMIT,
                "offset": offset,
                "start": start,
                "end": end,
            },
        )
        if not isinstance(page, list):
            break
        rows.extend(page)
        if len(page) < TRADES_LIMIT:
            break
        time.sleep(SLEEP_S)
    return rows


def fetch_trades(condition_id: str, start: int, end: int) -> pd.DataFrame:
    """Every fill of a market in ``[start, end]`` (unix s), splitting windows that come back full."""
    out: list[dict[str, Any]] = []
    stack = [(int(start), int(end))]
    while stack:
        s, e = stack.pop()
        rows = _trades_window(condition_id, s, e)
        if len(rows) >= 2 * TRADES_LIMIT and e - s > MIN_WINDOW_S:
            mid = (s + e) // 2
            stack.append((s, mid))
            stack.append(
                (mid, e)
            )  # one second of overlap; duplicates are dropped below
            continue
        out.extend(rows)
        time.sleep(SLEEP_S)
    if not out:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    df = pd.DataFrame(
        {
            "ts": [int(t.get("timestamp") or 0) for t in out],
            "price": [float(t.get("price") or 0.0) for t in out],
            "size": [float(t.get("size") or 0.0) for t in out],
            "side": [str(t.get("side") or "") for t in out],
            "outcome_index": [
                int(t.get("outcomeIndex") if t.get("outcomeIndex") is not None else -1)
                for t in out
            ],
            "asset": [str(t.get("asset") or "") for t in out],
            "tx": [str(t.get("transactionHash") or "") for t in out],
        }
    )
    df = df.drop_duplicates(["tx", "asset", "ts", "price", "size", "side"])
    return df.sort_values(["ts", "tx"]).reset_index(drop=True)


def _merge_markets(out: Path, fresh: pd.DataFrame) -> pd.DataFrame:
    path = out / "markets.parquet"
    if path.exists():
        old = pd.read_parquet(path)
        fresh = pd.concat([old, fresh], ignore_index=True).drop_duplicates(
            "id", keep="last"
        )
    fresh = fresh.sort_values("closed_time", ascending=False).reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    fresh.to_parquet(path, index=False)
    return fresh


def run(
    since: datetime,
    until: datetime,
    min_volume: float = 20_000.0,
    lookback_days: float = 14.0,
    max_markets: int | None = None,
    out: Path = OUT,
    max_pages: int | None = None,
    list_only: bool = False,
    from_list: bool = False,
    oldest_first: bool = True,
) -> dict[str, Any]:
    """List the resolved markets in the window (or take them from ``markets.parquet`` with ``from_list``), then
    fetch each one's tape for the last ``lookback_days`` before resolution (plus one hour after), oldest first so
    the TRAIN split completes first. Resumable: markets already in the manifest are not fetched again.
    ``list_only`` writes the market list and returns (so several fetch workers can share one listing)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "trades").mkdir(exist_ok=True)
    man_path = out / "manifest.json"
    manifest: dict[str, Any] = (
        json.loads(man_path.read_text()) if man_path.exists() else {"markets": {}}
    )
    manifest.setdefault("markets", {})
    if from_list:
        markets = pd.read_parquet(out / "markets.parquet")
        lo, hi = since.timestamp(), until.timestamp()
        in_window = (
            (markets["closed_time"] >= lo)
            & (markets["closed_time"] <= hi)
            & (markets["volume"] >= min_volume)
        )
        listed = markets[in_window]
    else:
        listed = list_resolved(since, until, min_volume=min_volume, max_pages=max_pages)
        markets = _merge_markets(out, listed)
    listed = listed.sort_values("closed_time", ascending=oldest_first)
    if list_only:
        print(
            f"lab4 data: listed {len(listed)} resolved markets in window; {len(markets)} in markets.parquet",
            flush=True,
        )
        return {"markets_listed": len(markets), "markets_in_window": len(listed)}
    todo = [
        r for r in listed.itertuples(index=False) if r.id not in manifest["markets"]
    ]
    if max_markets is not None:
        todo = todo[:max_markets]
    print(
        f"lab4 data: {len(listed)} resolved markets in window, {len(todo)} to fetch",
        flush=True,
    )
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        start = int(r.closed_time - lookback_days * 86400)
        end = int(r.closed_time + 3600)
        trades = fetch_trades(r.condition_id, start, end)
        trades.to_parquet(out / "trades" / f"{r.id}.parquet", index=False)
        if man_path.exists():  # another worker may have written: merge before saving
            try:
                manifest["markets"].update(
                    json.loads(man_path.read_text()).get("markets", {})
                )
            except ValueError:
                pass
        manifest["markets"][r.id] = {
            "condition_id": r.condition_id,
            "rows": len(trades),
            "first_ts": int(trades["ts"].min()) if len(trades) else None,
            "last_ts": int(trades["ts"].max()) if len(trades) else None,
            "closed_time": int(r.closed_time),
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        if i % 10 == 0 or i == len(todo):
            manifest["run"] = {
                "since": since.isoformat(),
                "until": until.isoformat(),
                "min_volume": min_volume,
                "lookback_days": lookback_days,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            man_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
            print(
                f"  {i}/{len(todo)} markets, {len(trades)} fills for {r.question[:50]!r}, {time.time() - t0:.0f}s",
                flush=True,
            )
    man_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    summary = {
        "markets_listed": len(markets),
        "markets_with_tapes": len(manifest["markets"]),
        "fills": int(sum(v["rows"] for v in manifest["markets"].values())),
        "run": manifest.get("run"),
    }
    (HERE / "data").mkdir(exist_ok=True)
    (HERE / "data" / "manifest.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n"
    )
    return summary


def status(out: Path = OUT) -> None:
    man_path = out / "manifest.json"
    if not man_path.exists():
        print("lab4 data: nothing fetched yet")
        return
    manifest = json.loads(man_path.read_text())
    ms = manifest.get("markets", {})
    fills = sum(v["rows"] for v in ms.values())
    print(
        f"lab4 data: {len(ms)} markets with tapes, {fills:,} fills; run {manifest.get('run')}"
    )
    path = out / "markets.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        span = (
            datetime.fromtimestamp(df["closed_time"].min(), UTC).date(),
            datetime.fromtimestamp(df["closed_time"].max(), UTC).date(),
        )
        print(
            f"  markets.parquet: {len(df)} resolved markets, closed {span[0]} .. {span[1]}, "
            f"fees on for {int(df['fees_enabled'].sum())}, volume median ${df['volume'].median():,.0f}"
        )


def _date(s: str) -> datetime:
    return (
        datetime.fromisoformat(s).replace(tzinfo=UTC)
        if "T" in s
        else datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", type=_date, help="closedTime >= this UTC date")
    ap.add_argument(
        "--until",
        type=_date,
        default=datetime.now(UTC),
        help="closedTime <= this (default now)",
    )
    ap.add_argument("--min-volume", type=float, default=20_000.0)
    ap.add_argument("--lookback-days", type=float, default=14.0)
    ap.add_argument("--max-markets", type=int, default=None)
    ap.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Gamma pages to scan (100 markets each)",
    )
    ap.add_argument(
        "--list-only", action="store_true", help="write markets.parquet and stop"
    )
    ap.add_argument(
        "--from-list",
        action="store_true",
        help="skip the listing; fetch the markets.parquet rows in the window",
    )
    ap.add_argument(
        "--newest-first",
        action="store_true",
        help="fetch newest markets first (default oldest first)",
    )
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        status()
        return 0
    if a.since is None:
        ap.error("--since is required")
    summary = run(
        a.since,
        a.until,
        a.min_volume,
        a.lookback_days,
        a.max_markets,
        max_pages=a.max_pages,
        list_only=a.list_only,
        from_list=a.from_list,
        oldest_first=not a.newest_first,
    )
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

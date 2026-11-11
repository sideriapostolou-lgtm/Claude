"""Lab 5 data: the crypto price markets of lab 4's cache, their rules, and Binance 1-second spot klines (public, no key).

Research only. The live bot never reads this. Three sources, all verified from this environment on 2026-10-09:

* **Lab 4's cache** (``$SCRATCH/lab4``, built by ``research/lab4/data.py``): ``markets.parquet`` (every resolved
  Polymarket market with closedTime from 2026-07-01 and volume >= $20,000) and ``trades/<id>.parquet`` (the fill
  tape of the last 14 days before resolution). Lab 5 reads it as is; nothing here re-fetches tapes.
* **Gamma** ``GET https://gamma-api.polymarket.com/markets?id=A&id=B&...&closed=true`` (up to 50 ids a call) gives
  each crypto market's full object: the rule text (``description``), ``resolutionSource``, ``eventStartTime``,
  ``cryptoMarketConfig`` (``twapLookbackSeconds`` for the Chainlink TWAP windows), ``orderPriceMinTickSize`` and
  the event's ``eventMetadata`` (``priceToBeat`` and ``finalPrice`` of the up-or-down windows: the resolution
  source's own start and end values). Saved as ``rules.parquet``.
* **Binance spot 1-second klines** from the public archive ``https://data.binance.vision/data/spot/daily/klines/
  <SYM>/1s/<SYM>-1s-<YYYY-MM-DD>.zip`` (sha256 in the ``.CHECKSUM`` file next to it; open time in MICROseconds
  since 2025). Binance BTC/USDT, ETH/USDT, SOL/USDT and XRP/USDT are the resolution source of the threshold,
  range, touch, hourly and daily up-or-down markets; the 5-minute, 15-minute and 4-hour windows resolve on
  Chainlink and Binance is the proxy there (the basis is measured against ``priceToBeat`` / ``finalPrice``).
  ``api.binance.com`` answers HTTP 451 from this environment; the archive does not. Saved per day as
  ``spot/<SYM>/<YYYY-MM-DD>.parquet`` with ``ts`` (open time, unix s), ``open``, ``high``, ``low``, ``close``.

Layout (``$SCRATCH/lab5`` by default; only ``manifest.json`` is mirrored to ``research/lab5/data/``; the cache is
~1 GB and stays out of git). Rebuild::

    python research/lab5/data.py --rules                       # Gamma rules of lab 4's crypto markets (~1 min)
    python research/lab5/data.py --spot --since 2026-06-01 --until 2026-10-08   # 4 symbols x 130 days (~1 GB)
    python research/lab5/data.py --status
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

API_GAMMA = "https://gamma-api.polymarket.com"
ARCHIVE = "https://data.binance.vision/data/spot/daily/klines"
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD",
        "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad",
    )
)
LAB4 = Path(os.environ.get("LAB4_DATA", str(SCRATCH / "lab4")))
OUT = Path(os.environ.get("LAB5_DATA", str(SCRATCH / "lab5")))
HERE = Path(__file__).resolve().parent

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
IDS_PER_CALL = 50
SLEEP_S = 0.35
UA = {
    "User-Agent": "nightcrawler-research/lab5 (+https://github.com/sideriapostolou-lgtm/Claude)"
}
RULE_COLUMNS = [
    "id",
    "description",
    "resolution_source",
    "event_start",
    "twap_s",
    "crypto_cfg",
    "tick",
    "price_to_beat",
    "final_price",
    "series_slug",
    "fee_schedule",
]


def _get(url: str, params: Any = None, tries: int = 6, as_json: bool = True) -> Any:
    """GET with backoff (429 waits long, 5xx and transport errors retry). Raises after ``tries``."""
    last = "no response"
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=120)
            if r.status_code == 429:
                last = "HTTP 429"
                time.sleep(10.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(3.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json() if as_json else r.content
        except (requests.RequestException, ValueError) as e:
            last = repr(e)
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {tries} tries: {last}")


def parse_time(value: Any) -> float | None:
    """ISO ``2026-08-08T20:27:18Z`` (or ``... +00``) -> unix seconds UTC; None when absent or unparseable."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    elif len(text) >= 3 and text[-3] in "+-" and text[-2:].isdigit():
        text = text + ":00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def rule_row(mk: dict[str, Any]) -> dict[str, Any]:
    """One Gamma market object -> the rule fields lab 5 needs (see the module docstring)."""
    events = mk.get("events") or [{}]
    ev = events[0] if isinstance(events, list) and events else {}
    meta = ev.get("eventMetadata") or {}
    cfg = mk.get("cryptoMarketConfig") or {}
    twap = cfg.get("twapLookbackSeconds") if cfg.get("twapEnabled") else None
    return {
        "id": str(mk.get("id")),
        "description": mk.get("description") or "",
        "resolution_source": mk.get("resolutionSource") or ev.get("resolutionSource") or "",
        "event_start": parse_time(mk.get("eventStartTime") or ev.get("startTime")),
        "twap_s": float(twap) if twap is not None else None,
        "crypto_cfg": json.dumps(cfg) if cfg else "",
        "tick": _num(mk.get("orderPriceMinTickSize")),
        "price_to_beat": _num(meta.get("priceToBeat")) if isinstance(meta, dict) else None,
        "final_price": _num(meta.get("finalPrice")) if isinstance(meta, dict) else None,
        "series_slug": ev.get("seriesSlug") or "",
        "fee_schedule": json.dumps(mk.get("feeSchedule") or {}),
    }


def crypto_ids(lab4: Path = LAB4) -> list[str]:
    """Lab 4's markets whose Gamma fee family is crypto (the venue's own category for these markets)."""
    m = pd.read_parquet(lab4 / "markets.parquet", columns=["id", "fee_type"])
    return m[m["fee_type"].fillna("").str.startswith("crypto")]["id"].astype(str).tolist()


def fetch_rules(out: Path = OUT, lab4: Path = LAB4) -> pd.DataFrame:
    """Gamma rule fields for every crypto-family market of lab 4 (resumable: rows already saved are kept)."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / "rules.parquet"
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=RULE_COLUMNS)
    todo = sorted(set(crypto_ids(lab4)) - set(have["id"].astype(str)))
    rows: list[dict[str, Any]] = []
    for k in range(0, len(todo), IDS_PER_CALL):
        batch = todo[k : k + IDS_PER_CALL]
        reply = _get(
            f"{API_GAMMA}/markets",
            [("id", i) for i in batch] + [("closed", "true"), ("limit", IDS_PER_CALL)],
        )
        rows.extend(rule_row(mk) for mk in (reply if isinstance(reply, list) else []))
        if (k // IDS_PER_CALL) % 50 == 0:
            print(f"  rules {k + len(batch)}/{len(todo)}", flush=True)
        time.sleep(SLEEP_S)
    fresh = pd.DataFrame(rows, columns=RULE_COLUMNS)
    df = pd.concat([have, fresh], ignore_index=True).drop_duplicates("id", keep="last")
    df.to_parquet(path, index=False)
    return df


def parse_klines(raw: bytes) -> pd.DataFrame:
    """A Binance archive kline CSV (zipped) -> ts (open time, unix s), open, high, low, close. Open times are in
    microseconds since 2025 and in milliseconds before; both are accepted."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f, header=None, usecols=[0, 1, 2, 3, 4])
    df.columns = ["t", "open", "high", "low", "close"]
    if len(df) and not str(df["t"].iloc[0]).isdigit():  # a header row
        df = df.iloc[1:].astype({"t": "int64", "open": float, "high": float, "low": float, "close": float})
    t = df["t"].astype("int64")
    scale = 1_000_000 if int(t.iloc[0]) > 10**14 else 1_000
    return pd.DataFrame(
        {
            "ts": (t // scale).astype("int64"),
            "open": df["open"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "close": df["close"].astype(float),
        }
    ).sort_values("ts").reset_index(drop=True)


def fetch_spot_day(symbol: str, day: str, out: Path = OUT) -> dict[str, Any]:
    """Download, checksum and save one symbol-day of 1 s klines; a day already saved is skipped."""
    path = out / "spot" / symbol / f"{day}.parquet"
    if path.exists():
        return {"symbol": symbol, "day": day, "rows": None, "status": "cached"}
    url = f"{ARCHIVE}/{symbol}/1s/{symbol}-1s-{day}.zip"
    raw = _get(url, as_json=False)
    check = _get(url + ".CHECKSUM", as_json=False).decode().split()[0]
    digest = hashlib.sha256(raw).hexdigest()
    if digest != check:
        raise RuntimeError(f"{symbol} {day}: sha256 {digest[:12]} != published {check[:12]}")
    df = parse_klines(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
    return {"symbol": symbol, "day": day, "rows": len(df), "status": "fetched"}


def fetch_spot(
    since: datetime, until: datetime, symbols: tuple[str, ...] = SYMBOLS, out: Path = OUT, workers: int = 4
) -> list[dict[str, Any]]:
    days = []
    d = since
    while d <= until:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    jobs = [(s, day) for s in symbols for day in days]
    done: list[dict[str, Any]] = []
    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(lambda j: fetch_spot_day(j[0], j[1], out), jobs), 1):
            done.append(r)
            if i % 40 == 0 or i == len(jobs):
                print(f"  spot {i}/{len(jobs)} ({r['symbol']} {r['day']} {r['status']})", flush=True)
    return done


def load_spot(symbol: str, start: float, end: float, out: Path = OUT) -> pd.DataFrame:
    """1 s klines of ``symbol`` whose open time lies in [start, end) (unix s), from the per-day files."""
    d0 = datetime.fromtimestamp(start, UTC).date()
    d1 = datetime.fromtimestamp(end, UTC).date()
    parts = []
    d = d0
    while d <= d1:
        p = out / "spot" / symbol / f"{d:%Y-%m-%d}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
        d += timedelta(days=1)
    if not parts:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close"])
    df = pd.concat(parts, ignore_index=True)
    return df[(df["ts"] >= start) & (df["ts"] < end)].reset_index(drop=True)


def write_manifest(out: Path = OUT) -> dict[str, Any]:
    spot: dict[str, Any] = {}
    for sym_dir in sorted((out / "spot").glob("*")):
        files = sorted(p.stem for p in sym_dir.glob("*.parquet"))
        spot[sym_dir.name] = {"days": len(files), "first": files[0] if files else None, "last": files[-1] if files else None}
    rules = out / "rules.parquet"
    summary = {
        "rules_rows": int(len(pd.read_parquet(rules, columns=["id"]))) if rules.exists() else 0,
        "spot": spot,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (HERE / "data").mkdir(exist_ok=True)
    (HERE / "data" / "manifest.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    return summary


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rules", action="store_true", help="fetch Gamma rules of lab 4's crypto markets")
    ap.add_argument("--spot", action="store_true", help="fetch Binance 1 s klines")
    ap.add_argument("--since", type=_date, default=_date("2026-06-01"))
    ap.add_argument("--until", type=_date, default=_date("2026-10-08"))
    ap.add_argument("--symbols", nargs="*", default=list(SYMBOLS))
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if a.rules:
        df = fetch_rules()
        print(f"lab5 rules: {len(df)} markets", flush=True)
    if a.spot:
        fetch_spot(a.since, a.until, tuple(a.symbols))
    print(json.dumps(write_manifest(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Lab 3 data: public OHLCV candles for liquid crypto majors from the Coinbase Exchange public API (no key).

Research only. The live bot never reads this; it trades through Jupiter on Solana. The universe is the set of coins
that have a USD market on Coinbase (clean, long, free history) AND trade on Solana through Jupiter with real
liquidity (SOL itself, cbBTC / wETH for BTC / ETH, and the Solana-ecosystem majors), so a passing strategy has a live
path without new accounts.

Layout (``$SCRATCH/lab3`` by default, mirrored to ``research/lab3/data/`` only as a small manifest)::

    candles_1d.parquet     asset, ts (UTC bar open, s), open, high, low, close, volume (base units), src
    candles_1h.parquet     same, hourly, from HOURLY_SINCE
    manifest.json          per asset: first / last bar, rows, fetched_at, gaps

Coinbase: ``GET /products/{id}/candles?granularity=G&start=ISO&end=ISO`` returns at most 300 rows
``[time, low, high, open, close, volume]`` newest first; public limit ~10 req/s (we stay at ~4/s). Windows before
a listing return []. A missing bar means no trade in that interval (thin coins): kept as a gap, never filled here.

CLI::

    python research/lab3/data.py --granularity 1d                 # daily, every asset, from 2015-01-01
    python research/lab3/data.py --granularity 1h                 # hourly from HOURLY_SINCE
    python research/lab3/data.py --granularity 1d --assets SOL BTC
    python research/lab3/data.py --status
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

API = "https://api.exchange.coinbase.com"
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD", "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad"
    )
)
OUT = Path(os.environ.get("LAB3_DATA", str(SCRATCH / "lab3")))
HERE = Path(__file__).resolve().parent

# Coinbase product -> (Solana mint symbol as Jupiter lists it, note). BTC and ETH trade on Solana as cbBTC and wETH.
UNIVERSE: dict[str, tuple[str, str]] = {
    "SOL": ("SOL", "native"),
    "BTC": ("cbBTC", "Coinbase wrapped BTC on Solana"),
    "ETH": ("wETH", "Wormhole / Portal ETH on Solana"),
    "JUP": ("JUP", "Jupiter"),
    "BONK": ("Bonk", "Bonk"),
    "WIF": ("$WIF", "dogwifhat"),
    "JTO": ("JTO", "Jito"),
    "PYTH": ("PYTH", "Pyth"),
    "RAY": ("RAY", "Raydium"),
    "HNT": ("HNT", "Helium"),
    "RENDER": ("RENDER", "Render"),
    "W": ("W", "Wormhole"),
    "ORCA": ("ORCA", "Orca"),
    "POPCAT": ("POPCAT", "Popcat"),
    "DRIFT": ("DRIFT", "Drift"),
    "TNSR": ("TNSR", "Tensor"),
    "KMNO": ("KMNO", "Kamino"),
    "IO": ("IO", "io.net"),
    "PENGU": ("PENGU", "Pudgy Penguins"),
    "TRUMP": ("TRUMP", "Official Trump"),
    "FARTCOIN": ("Fartcoin", "Fartcoin"),
    "MOODENG": ("MOODENG", "Moo Deng"),
    "PNUT": ("Pnut", "Peanut the Squirrel"),
    "ME": ("ME", "Magic Eden"),
    "GRASS": ("GRASS", "Grass"),
    "MNDE": ("MNDE", "Marinade"),
    "SHDW": ("SHDW", "GenesysGo Shadow"),
    "HONEY": ("HONEY", "Hivemapper"),
}
GRAN = {"1d": 86400, "1h": 3600}
DAILY_SINCE = datetime(2015, 1, 1, tzinfo=timezone.utc)
HOURLY_SINCE = datetime(2023, 1, 1, tzinfo=timezone.utc)
MAX_ROWS = 300
SLEEP_S = 0.25  # ~4 requests / s, well under the public limit


def _get(url: str, params: dict, tries: int = 5) -> list:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30, headers={"User-Agent": "nightcrawler-lab3/0.1"})
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 (transport: retry with backoff)
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"coinbase {url} {params}: {last}")


def fetch_product(product: str, granularity_s: int, since: datetime, until: datetime) -> pd.DataFrame:
    """Every candle of ``product`` in [since, until) at ``granularity_s``, oldest first."""
    rows: list[list] = []
    step = timedelta(seconds=granularity_s * MAX_ROWS)
    t = since
    empty_streak = 0
    while t < until:
        e = min(t + step, until)
        data = _get(
            f"{API}/products/{product}/candles",
            {"granularity": granularity_s, "start": t.isoformat(), "end": e.isoformat()},
        )
        if data:
            rows.extend(data)
            empty_streak = 0
        else:
            empty_streak += 1
        t = e
        time.sleep(SLEEP_S)
    if not rows:
        return pd.DataFrame(columns=["ts", "low", "high", "open", "close", "volume"])
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    for c in ("low", "high", "open", "close", "volume"):
        df[c] = df[c].astype(float)
    df["ts"] = df["ts"].astype("int64")
    return df


def _gaps(ts: pd.Series, granularity_s: int) -> int:
    if len(ts) < 2:
        return 0
    d = ts.diff().dropna()
    return int(((d // granularity_s) - 1).clip(lower=0).sum())


def run(granularity: str, assets: list[str] | None = None, out: Path = OUT) -> dict:
    g = GRAN[granularity]
    since = DAILY_SINCE if granularity == "1d" else HOURLY_SINCE
    until = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if granularity == "1d":
        until = until.replace(hour=0)  # only completed UTC days
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"candles_{granularity}.parquet"
    man_path = out / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    todo = assets or list(UNIVERSE)
    frames = [have[~have["asset"].isin(todo)]] if len(have) else []
    for a in todo:
        product = f"{a}-USD"
        t0 = time.time()
        prev = have[have["asset"] == a] if len(have) else pd.DataFrame()
        start = since
        if len(prev):  # incremental: refetch the last 2 bars for safety
            start = datetime.fromtimestamp(int(prev["ts"].max()) - 2 * g, tz=timezone.utc)
        df = fetch_product(product, g, start, until)
        df.insert(0, "asset", a)
        df["src"] = "coinbase"
        merged = (
            pd.concat([prev, df]).drop_duplicates(["asset", "ts"], keep="last").sort_values("ts") if len(prev) else df
        )
        frames.append(merged)
        manifest.setdefault(a, {})[granularity] = {
            "rows": int(len(merged)),
            "first_utc": None
            if not len(merged)
            else datetime.fromtimestamp(int(merged["ts"].min()), tz=timezone.utc).isoformat(),
            "last_utc": None
            if not len(merged)
            else datetime.fromtimestamp(int(merged["ts"].max()), tz=timezone.utc).isoformat(),
            "gaps": _gaps(merged["ts"], g) if len(merged) else 0,
            "fetched_at": until.isoformat(),
            "seconds": round(time.time() - t0, 1),
            "jupiter_symbol": UNIVERSE[a][0],
        }
        print(
            f"{a:9s} {granularity}: {len(merged):6d} rows, first {manifest[a][granularity]['first_utc']}, gaps {manifest[a][granularity]['gaps']}",
            flush=True,
        )
        all_df = pd.concat(frames, ignore_index=True)
        all_df.to_parquet(path, index=False)  # checkpoint after every asset
        man_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def status(out: Path = OUT) -> None:
    man_path = out / "manifest.json"
    if not man_path.exists():
        print("no data yet")
        return
    m = json.loads(man_path.read_text())
    for a, d in sorted(m.items()):
        for gname, v in d.items():
            print(
                f"{a:9s} {gname}: {v['rows']:6d} rows  {str(v['first_utc'])[:10]} -> {str(v['last_utc'])[:10]}  gaps {v['gaps']}"
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--granularity", choices=list(GRAN), default="1d")
    ap.add_argument("--assets", nargs="*", default=None)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    if a.status:
        status(Path(a.out))
        return 0
    run(a.granularity, a.assets, Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Lab 4 P6 (Amendment 5): the game facts lab 4's market cache did not keep, from Gamma (public, no key).

lab 4's ``markets.parquet`` has no game start time and no market type. Gamma's ``/markets`` carries both for sports
markets: ``gameStartTime`` (the scheduled start the venues show; the Polymarket US event's ``startTime`` that the desk
reads is the same field) and ``sportsMarketType`` (``moneyline``, ``spreads``, ``totals``, ``child_moneyline`` ...),
plus the rules text (``description``) and the market's event as embedded by Gamma: ``startTime``,
``finishedTimestamp`` (when the game ended: the desk stops buying a game once its period reads final), ``score``,
``period`` and ``seriesSlug``. This module fetches them for the binary, single-winner markets of the lab's
three splits whose event is a sport by :mod:`sports` (or whose fee family is sports), 100 ids per request with a
pause between requests, and writes ``$LAB4_DATA/p6_meta.parquet``. Run once; a re-run only fetches the ids missing.

    python research/lab4/P6/meta.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import core as C
from sports import sport_of

import data as D

API = "https://gamma-api.polymarket.com/markets"
BATCH = 100
SLEEP_S = 0.5
OUT = D.OUT / "p6_meta.parquet"
COLUMNS = [
    "id",
    "game_start",
    "game_start_raw",
    "sports_market_type",
    "optic_market",
    "description",
    "automatically_resolved",
    "event_start",
    "event_finished",
    "event_score",
    "event_period",
    "event_series",
    "fetched",
]


def targets(markets: pd.DataFrame) -> pd.DataFrame:
    lo, _ = C.split_bounds("train")
    _, hi = C.split_bounds("test")
    m = markets[
        (markets["n_outcomes"] == 2)
        & markets["winner_index"].isin([0, 1])
        & (markets["closed_time"] >= lo)
        & (markets["closed_time"] < hi)
    ].copy()
    fam = [
        C.fee_family(t, bool(e))
        for t, e in zip(m["fee_type"], m["fees_enabled"], strict=True)
    ]
    sport = [sport_of(s) for s in m["event_slug"]]
    keep = [
        (s != "other") or (f in ("sports", "zero"))
        for s, f in zip(sport, fam, strict=True)
    ]
    return m[keep]


def _row(x: dict[str, Any]) -> dict[str, Any]:
    meta = x.get("marketMetadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = {}
    raw = x.get("gameStartTime")
    evs = x.get("events") or []
    ev = evs[0] if evs and isinstance(evs[0], dict) else {}
    return {
        "id": str(x.get("id")),
        "game_start": D.parse_time(
            raw.replace(" ", "T") if isinstance(raw, str) else raw
        ),
        "game_start_raw": raw,
        "sports_market_type": x.get("sportsMarketType"),
        "optic_market": meta.get("opticOddsMarketId")
        if isinstance(meta, dict)
        else None,
        "description": x.get("description"),
        "automatically_resolved": x.get("automaticallyResolved"),
        "event_start": D.parse_time(ev.get("startTime")),
        "event_finished": D.parse_time(ev.get("finishedTimestamp")),
        "event_score": ev.get("score"),
        "event_period": ev.get("period"),
        "event_series": ev.get("seriesSlug"),
        "fetched": True,
    }


def fetch(ids: list[str]) -> list[dict[str, Any]]:
    params: list[tuple[str, Any]] = [("id", i) for i in ids] + [
        ("closed", "true"),
        ("limit", len(ids)),
    ]
    for attempt in range(6):
        try:
            r = requests.get(API, params=params, headers=D.UA, timeout=60)
            if r.status_code == 429:
                time.sleep(10.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return [_row(x) for x in r.json()]
        except requests.RequestException:
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"Gamma did not answer for a batch of {len(ids)} ids")


def main() -> int:
    markets = pd.read_parquet(D.OUT / "markets.parquet")
    want = targets(markets)["id"].astype(str).tolist()
    have = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=COLUMNS)
    done = set(have["id"].astype(str))
    todo = [i for i in want if i not in done]
    print(f"targets {len(want)}, cached {len(done)}, to fetch {len(todo)}", flush=True)
    rows: list[dict[str, Any]] = []
    for k in range(0, len(todo), BATCH):
        ids = todo[k : k + BATCH]
        got = fetch(ids)
        seen = {g["id"] for g in got}
        rows += got + [
            {**{c: None for c in COLUMNS}, "id": i, "fetched": False}
            for i in ids
            if i not in seen
        ]
        if (k // BATCH) % 25 == 0:
            print(f"  {k + len(ids)} / {len(todo)}", flush=True)
            out = pd.concat(
                [have, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True
            )
            out.to_parquet(OUT, index=False)
        time.sleep(SLEEP_S)
    out = pd.concat([have, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
    out = out.drop_duplicates("id", keep="last")
    out.to_parquet(OUT, index=False)
    print(
        f"wrote {OUT} rows {len(out)}; with game start {int(out['game_start'].notna().sum())}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

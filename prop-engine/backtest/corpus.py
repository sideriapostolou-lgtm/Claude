"""MLB play-by-play corpus puller.

Downloads schedules + play-by-play for date ranges, extracts one compact row
per plate appearance, and caches per-date CSVs under data/corpus/mlb/.
These records feed the empirical fits (inning factors, PA-per-inning by slot,
park factors) and the walk-forward backtest.

Usage:
    python -m backtest.corpus 2026-03-20 2026-07-06
"""
from __future__ import annotations

import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = "https://statsapi.mlb.com/api/v1"
ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus" / "mlb"

PLAY_FIELDS = ["gamePk", "inning", "half", "event_type", "batter_id", "pitcher_id",
               "bat_team_id", "at_bat_index"]
GAME_FIELDS = ["gamePk", "date", "venue_id", "venue_name", "home_id", "away_id",
               "home_sp_id", "away_sp_id"]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "prop-engine-corpus"})
    return s


def fetch_date(s: requests.Session, day: str) -> tuple[list[dict], list[dict]]:
    """Return (game_rows, play_rows) for all completed regular-season games on a date."""
    sched = s.get(f"{BASE}/schedule",
                  params={"sportId": 1, "date": day, "hydrate": "probablePitcher"},
                  timeout=30).json()
    games = [g for d in sched.get("dates", []) for g in d.get("games", [])
             if g.get("gameType") == "R" and g["status"]["abstractGameState"] == "Final"]
    game_rows, play_rows = [], []
    for g in games:
        pk = g["gamePk"]
        try:
            pbp = s.get(f"{BASE}/game/{pk}/playByPlay", timeout=30).json()
        except Exception:
            continue
        home_id = g["teams"]["home"]["team"]["id"]
        away_id = g["teams"]["away"]["team"]["id"]
        game_rows.append({
            "gamePk": pk, "date": day,
            "venue_id": g.get("venue", {}).get("id", ""),
            "venue_name": g.get("venue", {}).get("name", ""),
            "home_id": home_id, "away_id": away_id,
            "home_sp_id": (g["teams"]["home"].get("probablePitcher") or {}).get("id", ""),
            "away_sp_id": (g["teams"]["away"].get("probablePitcher") or {}).get("id", ""),
        })
        for p in pbp.get("allPlays", []):
            about, result, matchup = p.get("about", {}), p.get("result", {}), p.get("matchup", {})
            half = about.get("halfInning", "")
            play_rows.append({
                "gamePk": pk,
                "inning": about.get("inning", ""),
                "half": half,
                "event_type": result.get("eventType", ""),
                "batter_id": (matchup.get("batter") or {}).get("id", ""),
                "pitcher_id": (matchup.get("pitcher") or {}).get("id", ""),
                "bat_team_id": away_id if half == "top" else home_id,
                "at_bat_index": about.get("atBatIndex", ""),
            })
    return game_rows, play_rows


def pull_range(start: str, end: str, workers: int = 12) -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]
    todo = [d for d in days if not (CORPUS_DIR / f"plays_{d}.csv").exists()]
    print(f"corpus pull {start}..{end}: {len(days)} days, {len(todo)} to fetch", flush=True)
    s = _session()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_date, s, d): d for d in todo}
        for fut in as_completed(futs):
            day = futs[fut]
            try:
                game_rows, play_rows = fut.result()
            except Exception as e:
                print(f"  {day}: FAILED {e}", flush=True)
                continue
            for name, rows, fields in (("games", game_rows, GAME_FIELDS),
                                        ("plays", play_rows, PLAY_FIELDS)):
                with open(CORPUS_DIR / f"{name}_{day}.csv", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=fields)
                    w.writeheader()
                    w.writerows(rows)
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(todo)} days done (latest {day}: {len(game_rows)} games)", flush=True)
    print(f"corpus pull complete: {done}/{len(todo)} newly fetched", flush=True)


if __name__ == "__main__":
    pull_range(sys.argv[1], sys.argv[2])

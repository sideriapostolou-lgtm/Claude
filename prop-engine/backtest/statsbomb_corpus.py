"""StatsBomb open-data shot corpus puller (La Liga, Messi era).

Hits the raw open-data JSON directly (lighter than statsbombpy's flattening),
extracts every shot with x/y + outcome, and per-match Messi minutes.
Caches to data/corpus/statsbomb/shots.csv and messi_minutes.csv.

Usage:
    python -m backtest.statsbomb_corpus
"""
from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

RAW = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
LA_LIGA = 11
MESSI = "Lionel Andrés Messi Cuccittini"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "corpus" / "statsbomb"

SHOT_FIELDS = ["match_id", "season", "match_date", "player", "team", "period", "minute",
               "x", "y", "outcome", "shot_type", "statsbomb_xg"]
MIN_FIELDS = ["match_id", "season", "match_date", "started", "minute_on", "minute_off",
              "match_minutes", "messi_minutes"]


def _get(s: requests.Session, url: str):
    r = s.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def process_match(s: requests.Session, match: dict, season: str):
    mid = match["match_id"]
    events = _get(s, f"{RAW}/events/{mid}.json")
    shots, match_len = [], 0.0
    started, min_on, min_off = False, None, None
    for ev in events:
        t = ev.get("type", {}).get("name")
        clock = ev.get("minute", 0) + ev.get("second", 0) / 60.0
        if ev.get("period", 0) <= 4:
            match_len = max(match_len, clock)
        if t == "Starting XI":
            lineup = ev.get("tactics", {}).get("lineup", [])
            if any(p.get("player", {}).get("name") == MESSI for p in lineup):
                started = True
        elif t == "Substitution":
            if ev.get("player", {}).get("name") == MESSI:
                min_off = clock
            elif ev.get("substitution", {}).get("replacement", {}).get("name") == MESSI:
                min_on = clock
        elif t == "Shot":
            loc = ev.get("location") or [None, None]
            shot = ev.get("shot", {})
            shots.append({
                "match_id": mid, "season": season, "match_date": match.get("match_date", ""),
                "player": ev.get("player", {}).get("name", ""),
                "team": ev.get("team", {}).get("name", ""),
                "period": ev.get("period", ""), "minute": ev.get("minute", ""),
                "x": loc[0], "y": loc[1],
                "outcome": shot.get("outcome", {}).get("name", ""),
                "shot_type": shot.get("type", {}).get("name", ""),
                "statsbomb_xg": shot.get("statsbomb_xg", ""),
            })
    if started:
        messi_min = (min_off if min_off is not None else match_len)
    elif min_on is not None:
        messi_min = match_len - min_on
    else:
        messi_min = 0.0
    minutes_row = {"match_id": mid, "season": season, "match_date": match.get("match_date", ""),
                   "started": int(started),
                   "minute_on": round(min_on, 2) if min_on is not None else "",
                   "minute_off": round(min_off, 2) if min_off is not None else "",
                   "match_minutes": round(match_len, 2),
                   "messi_minutes": round(max(messi_min, 0.0), 2)}
    return shots, minutes_row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shots_path = OUT_DIR / "shots.csv"
    mins_path = OUT_DIR / "messi_minutes.csv"
    if shots_path.exists() and mins_path.exists():
        print("statsbomb corpus already cached", flush=True)
        return
    s = requests.Session()
    comps = _get(s, f"{RAW}/competitions.json")
    seasons = [(c["season_id"], c["season_name"]) for c in comps
               if c["competition_id"] == LA_LIGA and c["season_name"] != "1973/1974"]
    all_matches = []
    for sid, sname in seasons:
        for m in _get(s, f"{RAW}/matches/{LA_LIGA}/{sid}.json"):
            all_matches.append((m, sname))
    print(f"statsbomb: {len(seasons)} seasons, {len(all_matches)} matches", flush=True)

    all_shots, all_mins, done = [], [], 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(process_match, s, m, sn): (m["match_id"], sn) for m, sn in all_matches}
        for fut in as_completed(futs):
            mid, sn = futs[fut]
            try:
                shots, mins = fut.result()
            except Exception as e:
                print(f"  match {mid}: FAILED {e}", flush=True)
                continue
            all_shots.extend(shots)
            all_mins.append(mins)
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(all_matches)} matches done", flush=True)

    for path, rows, fields in ((shots_path, all_shots, SHOT_FIELDS), (mins_path, all_mins, MIN_FIELDS)):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    print(f"statsbomb corpus complete: {len(all_shots)} shots, {len(all_mins)} match-minutes rows", flush=True)


if __name__ == "__main__":
    main()

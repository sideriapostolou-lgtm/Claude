"""Fit empirical model factors from the PBP corpus.

Replaces every v0 prior with data:
  - inning_hr_factor: HR-per-PA by inning relative to league (why HRs skew
    early: top of order guaranteed in inning 1, starters tire mid-game)
  - exp_pa: mean plate appearances per (half, inning) per game — unplayed
    halves (bottom 9 with home lead, no extras) count as zero, so the
    "inning may not happen" effect is priced in automatically
  - slot_occupancy: P(lineup slot s gets >=1 PA in inning i) — what makes
    player-level inning props possible
  - starter_pa_share: fraction of PAs in inning i faced by the starting
    pitcher (for starter/bullpen blending)
  - park_factor: venue HR/PA vs league, regressed with pseudo-counts

Output cached to data/fits.json. Usage: python -m backtest.fit_factors
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus" / "mlb"
FITS_PATH = ROOT / "data" / "fits.json"

PARK_PSEUDO_PA = 5000  # league-average PAs added to each venue before ratio


def load_corpus(before: str | None = None):
    """Load the corpus, optionally only days strictly before an ISO date."""
    games, plays_by_game = {}, defaultdict(list)
    for f in sorted(CORPUS_DIR.glob("games_*.csv")):
        if before and f.stem.replace("games_", "") >= before:
            continue
        for r in csv.DictReader(open(f)):
            games[int(r["gamePk"])] = r
    for f in sorted(CORPUS_DIR.glob("plays_*.csv")):
        if before and f.stem.replace("plays_", "") >= before:
            continue
        for r in csv.DictReader(open(f)):
            plays_by_game[int(r["gamePk"])].append(r)
    return games, plays_by_game


def fit(games: dict, plays_by_game: dict) -> dict:
    n_games = len(games)
    pa_by_inning = defaultdict(int)          # (half, inning) -> PAs
    hr_by_inning = defaultdict(int)
    slot_games = defaultdict(set)            # (half, inning, slot) -> {(gamePk, team)}
    slot_pa = defaultdict(int)               # slot -> total PAs (per team-game basis)
    starter_pa = defaultdict(int)            # inning -> PAs faced by starter
    total_pa_inning = defaultdict(int)       # inning -> PAs (for starter share)
    venue_pa = defaultdict(int)
    venue_hr = defaultdict(int)
    total_pa = total_hr = 0

    for pk, plays in plays_by_game.items():
        g = games.get(pk)
        if g is None:
            continue
        venue = g["venue_name"]
        plays.sort(key=lambda r: int(r["at_bat_index"] or 0))
        # per-team PA sequence -> lineup slot
        seq = defaultdict(int)
        # starter = pitcher of the first PA of each half
        starter = {}
        for r in plays:
            half, inning = r["half"], int(r["inning"] or 0)
            if inning < 1:
                continue
            team = r["bat_team_id"]
            slot = seq[team] % 9 + 1
            seq[team] += 1
            is_hr = r["event_type"] == "home_run"
            total_pa += 1
            total_hr += is_hr
            key_inn = min(inning, 12)
            pa_by_inning[(half, key_inn)] += 1
            hr_by_inning[(half, key_inn)] += is_hr
            slot_games[(half, key_inn, slot)].add((pk, team))
            slot_pa[slot] += 1
            venue_pa[venue] += 1
            venue_hr[venue] += is_hr
            if half not in starter:
                starter[half] = r["pitcher_id"]
            total_pa_inning[key_inn] += 1
            if r["pitcher_id"] == starter[half]:
                starter_pa[key_inn] += 1

    league_hr_pa = total_hr / total_pa
    innings = list(range(1, 13))

    exp_pa = {h: {i: pa_by_inning[(h, i)] / n_games for i in innings}
              for h in ("top", "bottom")}
    inning_hr_factor = {}
    for i in innings:
        pa = pa_by_inning[("top", i)] + pa_by_inning[("bottom", i)]
        hr = hr_by_inning[("top", i)] + hr_by_inning[("bottom", i)]
        # regress thin innings (extras) toward 1.0 with 20k pseudo-PAs
        rate = (hr + 20000 * league_hr_pa) / (pa + 20000)
        inning_hr_factor[i] = rate / league_hr_pa

    slot_occupancy = {h: {i: [len(slot_games[(h, i, s)]) / n_games for s in range(1, 10)]
                          for i in innings} for h in ("top", "bottom")}

    starter_share = {i: (starter_pa[i] / total_pa_inning[i]) if total_pa_inning[i] else 0.0
                     for i in innings}

    # mean PAs per game per lineup slot (over team-games; 2 per game)
    pa_per_slot = {s: slot_pa[s] / (2 * n_games) for s in range(1, 10)}

    park_factor = {}
    for venue, pa in venue_pa.items():
        rate = (venue_hr[venue] + PARK_PSEUDO_PA * league_hr_pa) / (pa + PARK_PSEUDO_PA)
        park_factor[venue] = rate / league_hr_pa

    return {
        "n_games": n_games,
        "total_pa": total_pa,
        "total_hr": total_hr,
        "league_hr_pa": league_hr_pa,
        "exp_pa": exp_pa,
        "inning_hr_factor": inning_hr_factor,
        "slot_occupancy": slot_occupancy,
        "starter_pa_share": starter_share,
        "pa_per_slot": pa_per_slot,
        "park_factor": park_factor,
        "pa_by_inning": {f"{h}_{i}": pa_by_inning[(h, i)] for h in ("top", "bottom") for i in innings},
        "hr_by_inning": {f"{h}_{i}": hr_by_inning[(h, i)] for h in ("top", "bottom") for i in innings},
    }


def main():
    import sys
    before = sys.argv[1] if len(sys.argv) > 1 else None
    out = FITS_PATH if before is None else ROOT / "data" / f"fits_before_{before}.json"
    games, plays = load_corpus(before)
    fits = fit(games, plays)
    out.write_text(json.dumps(fits, indent=1))
    print(f"fit on {fits['n_games']} games, {fits['total_pa']} PAs, {fits['total_hr']} HRs")
    print(f"league HR/PA: {fits['league_hr_pa']:.5f}")
    print("inning_hr_factor:", {i: round(f, 3) for i, f in list(fits['inning_hr_factor'].items())[:9]})
    print("exp_pa top:     ", {i: round(v, 2) for i, v in list(fits['exp_pa']['top'].items())[:9]})
    print("exp_pa bottom:  ", {i: round(v, 2) for i, v in list(fits['exp_pa']['bottom'].items())[:9]})
    print("starter share:  ", {i: round(v, 2) for i, v in list(fits['starter_pa_share'].items())[:9]})
    print("slot occ top inning 1:", [round(p, 2) for p in fits['slot_occupancy']['top'][1]])
    print("slot occ top inning 3:", [round(p, 2) for p in fits['slot_occupancy']['top'][3]])


if __name__ == "__main__":
    main()

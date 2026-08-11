"""Soccer coordinate_event pricing — goal-from-distance props.

Model, all from StatsBomb open data (backtest/statsbomb_corpus.py):
  1. conversion(distance): league-wide goal probability by shot distance,
     Gaussian-kernel smoothed (their xG is a shortcut for this; we fit it
     directly from outcomes). Penalties excluded — a 12-yard penalty is not
     a "shot from 12 yards" in the betting sense.
  2. player shot volume in the distance band per 90 minutes.
  3. player-vs-league conversion blend in the band (regressed, 50-shot prior).

P(goal from D +/- tol yards in a match)
  = 1 - exp(-(shots_per90_in_band x minutes/90 x conv_band))

StatsBomb pitch is 120x80 units ~= yards; goal center is (120, 40).
"""
from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .base import PriceResult

ROOT = Path(__file__).resolve().parent.parent
SB_DIR = ROOT / "data" / "corpus" / "statsbomb"

GOAL = (120.0, 40.0)
KERNEL_BW = 2.0          # yards, for conversion smoothing
CONV_PRIOR_SHOTS = 50    # league shots blended into player band conversion
MESSI = "Lionel Andrés Messi Cuccittini"


def shot_distance(x: float, y: float) -> float:
    return math.hypot(GOAL[0] - x, GOAL[1] - y)


@lru_cache(maxsize=1)
def load_shots() -> list[dict]:
    shots = []
    with open(SB_DIR / "shots.csv") as f:
        for r in csv.DictReader(f):
            if not r["x"] or not r["y"]:
                continue
            shots.append({
                "player": r["player"],
                "dist": shot_distance(float(r["x"]), float(r["y"])),
                "goal": r["outcome"] == "Goal",
                "penalty": r["shot_type"] == "Penalty",
                "match_id": r["match_id"],
            })
    return shots


@lru_cache(maxsize=1)
def messi_minutes() -> float:
    total = 0.0
    with open(SB_DIR / "messi_minutes.csv") as f:
        for r in csv.DictReader(f):
            total += float(r["messi_minutes"] or 0)
    return total


def league_conversion_at(dist: float, shots: Optional[list] = None) -> tuple[float, float]:
    """Kernel-smoothed P(goal | shot at distance). Returns (rate, eff_n)."""
    shots = shots if shots is not None else load_shots()
    num = den = 0.0
    for s in shots:
        if s["penalty"]:
            continue
        w = math.exp(-0.5 * ((s["dist"] - dist) / KERNEL_BW) ** 2)
        den += w
        num += w * s["goal"]
    if den == 0:
        return 0.0, 0.0
    return num / den, den


def band_stats(player: str, dist: float, tol: float, at_least: bool = False):
    """Player shots/goals in band, league conversion in band."""
    shots = load_shots()

    def in_band(d: float) -> bool:
        return d >= dist if at_least else abs(d - dist) <= tol

    p_shots = p_goals = 0
    l_shots = l_goals = 0
    for s in shots:
        if s["penalty"]:
            continue
        if in_band(s["dist"]):
            l_shots += 1
            l_goals += s["goal"]
            if s["player"] == player:
                p_shots += 1
                p_goals += s["goal"]
    return p_shots, p_goals, l_shots, l_goals


def price_coordinate_goal(spec, minutes: float = 90.0,
                          player_name: Optional[str] = None) -> PriceResult:
    c = spec.constraints
    dist = c.distance_yards
    tol = c.tolerance or 0.5
    at_least = c.comparator == "at_least"
    player = player_name or (MESSI if "messi" in (spec.player or "").lower() else spec.player)

    p_shots, p_goals, l_shots, l_goals = band_stats(player, dist, tol, at_least)
    total_min = messi_minutes() if player == MESSI else None
    if total_min is None or total_min <= 0:
        return PriceResult(fair_prob=0.0, model_variance=1.0, rel_sd=1.0,
                           inputs_used={"error": f"no minutes data for {player}"})

    shots_per90 = p_shots / (total_min / 90.0)
    if at_least:
        league_conv = (l_goals / l_shots) if l_shots else 0.0
        eff_n = l_shots
    else:
        league_conv, eff_n = league_conversion_at(dist)
    conv = (p_goals + CONV_PRIOR_SHOTS * league_conv) / (p_shots + CONV_PRIOR_SHOTS)

    lam = shots_per90 * (minutes / 90.0) * conv
    p = 1.0 - math.exp(-lam)

    rel_var = (1.0 / max(p_shots, 2)            # shot-volume sampling
               + 1.0 / max(p_goals + CONV_PRIOR_SHOTS * league_conv, 2)
               + 0.01)                           # era/team-context drift
    return PriceResult(
        fair_prob=p, model_variance=(p * math.sqrt(rel_var)) ** 2,
        rel_sd=math.sqrt(rel_var),
        inputs_used={
            "player": player,
            "band": f">= {dist} yds" if at_least else f"{dist} +/- {tol} yds",
            "player_shots_in_band": p_shots,
            "player_goals_in_band": p_goals,
            "league_shots_in_band": l_shots,
            "league_conv_in_band": round(league_conv, 4),
            "blended_conv": round(conv, 4),
            "shots_per90_in_band": round(shots_per90, 4),
            "minutes_assumed": minutes,
            "career_minutes": round(total_min),
            "lambda": round(lam, 5),
        })

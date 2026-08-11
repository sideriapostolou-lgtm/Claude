"""Soccer grading from StatsBomb/Opta event feeds.

grade(spec, events, player_name) checks shot location + outcome against the
distance band. events: list of StatsBomb event dicts (raw open-data format).
"""
from __future__ import annotations

import math
from typing import Optional

GOAL = (120.0, 40.0)


def _distance(loc) -> float:
    return math.hypot(GOAL[0] - loc[0], GOAL[1] - loc[1])


def grade(spec, events: list[dict], player_name: Optional[str] = None) -> dict:
    c = spec.constraints
    player = player_name or spec.player

    goals = []
    for ev in events:
        if ev.get("type", {}).get("name") != "Shot":
            continue
        shot = ev.get("shot", {})
        if shot.get("outcome", {}).get("name") != "Goal":
            continue
        if player and ev.get("player", {}).get("name") != player:
            continue
        loc = ev.get("location")
        if not loc:
            continue
        d = _distance(loc)
        if c.distance_yards is not None:
            if c.comparator == "at_least":
                if d < c.distance_yards:
                    continue
            else:
                tol = c.tolerance or 0.5
                if abs(d - c.distance_yards) > tol:
                    continue
        goals.append({"player": ev.get("player", {}).get("name"),
                      "minute": ev.get("minute"),
                      "distance_yards": round(d, 2),
                      "location": loc})

    if goals:
        return {"result": "win", "evidence": {"goals": goals}}
    band = (f">= {c.distance_yards} yds" if c.comparator == "at_least"
            else f"{c.distance_yards} +/- {c.tolerance or 0.5} yds"
            ) if c.distance_yards is not None else "any distance"
    return {"result": "loss",
            "evidence": {"reason": f"no qualifying goal ({band})"
                         + (f" by {player}" if player else "")}}

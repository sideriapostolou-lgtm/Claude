"""Deterministic post-validation of parsed PropSpecs.

The LLM (or rule parser) proposes; this module disposes. Checks run against
live MLB Stats API data unless a prefetched context is supplied (tests /
backtest use canned contexts so validation is hermetic).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import requests

from .propspec import ParseResult, PropSpec

BASE = "https://statsapi.mlb.com/api/v1"

# StatsBomb pitch is 120x80; max plausible goal distance ~ 100+ yards but
# anything beyond 60 is effectively a punt — reject as out of field bounds.
MAX_SHOT_DISTANCE_YARDS = 90.0


@dataclass
class ValidationContext:
    """Prefetched data so validation can run offline."""
    schedule_teams: dict[int, str] = field(default_factory=dict)  # team_id -> name
    games: list[dict] = field(default_factory=list)               # schedule game dicts
    rosters: dict[str, int] = field(default_factory=dict)         # player name -> id
    player_team: dict[str, int] = field(default_factory=dict)     # player name -> team_id


def fetch_context(day: Optional[str] = None) -> ValidationContext:
    day = day or date.today().isoformat()
    s = requests.Session()
    sched = s.get(f"{BASE}/schedule", params={"sportId": 1, "date": day}, timeout=20).json()
    games = [g for d in sched.get("dates", []) for g in d.get("games", [])
             if g.get("gameType") == "R"]
    teams = {}
    for g in games:
        for side in ("away", "home"):
            t = g["teams"][side]["team"]
            teams[t["id"]] = t["name"]
    ctx = ValidationContext(schedule_teams=teams, games=games)
    for team_id in teams:
        try:
            roster = s.get(f"{BASE}/teams/{team_id}/roster", timeout=20).json()
            for entry in roster.get("roster", []):
                name = entry["person"]["fullName"].lower()
                ctx.rosters[name] = entry["person"]["id"]
                ctx.player_team[name] = team_id
        except Exception:
            continue
    return ctx


def resolve_game(spec: PropSpec, ctx: ValidationContext) -> Optional[dict]:
    """Match spec.game_ref/team against today's schedule; returns the game dict."""
    needle = None
    if spec.game_ref and spec.game_ref.gamePk:
        for g in ctx.games:
            if g["gamePk"] == spec.game_ref.gamePk:
                return g
        return None
    if spec.game_ref and spec.game_ref.description:
        needle = spec.game_ref.description.lower()
    elif spec.team:
        needle = spec.team.lower()
    if needle is None:
        return None
    for g in ctx.games:
        names = (g["teams"]["away"]["team"]["name"] + " @ " +
                 g["teams"]["home"]["team"]["name"]).lower()
        if all(part.strip() in names for part in needle.split("@")):
            return g
    return None


def validate(result: ParseResult, ctx: Optional[ValidationContext] = None) -> ParseResult:
    """Apply hard gates. Returns the (possibly rejected) ParseResult."""
    if result.status != "ok":
        return result

    specs = result.legs if result.legs else ([result.spec] if result.spec else [])
    for spec in specs:
        # Gradeability is a hard gate — no source, no market.
        if not spec.gradeable or spec.grading_source is None:
            return ParseResult(status="rejected",
                               reason="This prop has no official grading source, so it can't be offered.")

        c = spec.constraints
        if c.inning is not None:
            if c.inning < 1:
                return ParseResult(status="rejected", reason="Innings start at 1.")
            if c.inning > 9 and "extra_innings" not in spec.flags:
                spec.flags.append("extra_innings")
        if c.by_inning is not None and not (1 <= c.by_inning <= 12):
            return ParseResult(status="rejected", reason="'By inning' must be between 1 and 12.")
        if c.distance_yards is not None:
            if c.distance_yards <= 0 or c.distance_yards > MAX_SHOT_DISTANCE_YARDS:
                return ParseResult(
                    status="rejected",
                    reason=f"Shot distance must be between 0 and {MAX_SHOT_DISTANCE_YARDS:.0f} yards.")
        if c.count is not None and c.count < 1:
            return ParseResult(status="rejected", reason="Count must be at least 1.")

        if ctx is not None and spec.sport == "MLB":
            # Game must exist on the slate if one is referenced
            if (spec.game_ref and spec.game_ref.description) or spec.team:
                game = resolve_game(spec, ctx)
                if game is None:
                    return ParseResult(
                        status="rejected",
                        reason="That game isn't on today's schedule — check the matchup.")
                if spec.game_ref is None:
                    spec.game_ref = None
                else:
                    spec.game_ref.gamePk = game["gamePk"]
            # Player must be on an active roster
            if spec.player and ctx.rosters and spec.player.lower() not in ctx.rosters:
                return ParseResult(
                    status="rejected",
                    reason=f"{spec.player} isn't on an active roster for today's slate.")
    return result

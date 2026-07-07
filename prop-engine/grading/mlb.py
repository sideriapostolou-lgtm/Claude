"""MLB grading from official play-by-play.

Deterministic and auditable: every settlement stores the exact plays that
decided it as evidence.

grade(spec, pbp, game_meta) -> {"result": "win"|"loss"|"void", "evidence": {...}}
  pbp: the /game/{gamePk}/playByPlay JSON
  game_meta: {"away_id": int, "home_id": int} to map halves to teams
"""
from __future__ import annotations

from typing import Optional

HIT_EVENTS = {"single", "double", "triple", "home_run"}
K_EVENTS = {"strikeout", "strikeout_double_play"}


def _play_summary(p: dict) -> dict:
    return {
        "inning": p["about"]["inning"],
        "half": p["about"]["halfInning"],
        "event": p["result"].get("eventType"),
        "batter": p["matchup"]["batter"]["fullName"],
        "pitcher": p["matchup"]["pitcher"]["fullName"],
        "description": p["result"].get("description", ""),
    }


def _bat_team(p: dict, game_meta: dict) -> int:
    return game_meta["away_id"] if p["about"]["halfInning"] == "top" else game_meta["home_id"]


def _matches_scope(p: dict, spec, game_meta: dict, team_id: Optional[int],
                   player_id: Optional[int]) -> bool:
    if spec.scope == "team" and team_id is not None:
        if _bat_team(p, game_meta) != team_id:
            return False
    if spec.scope == "player" and player_id is not None:
        if p["matchup"]["batter"]["id"] != player_id:
            return False
    return True


def grade(spec, pbp: dict, game_meta: dict, team_id: Optional[int] = None,
          player_id: Optional[int] = None) -> dict:
    plays = pbp.get("allPlays", [])
    if not plays:
        return {"result": "void", "evidence": {"reason": "no play-by-play available"}}
    c = spec.constraints

    if spec.market_family == "inning_event":
        target = [p for p in plays
                  if p["result"].get("eventType") == spec.event
                  and p["about"]["inning"] == c.inning
                  and (c.half is None or p["about"]["halfInning"] == c.half)
                  and _matches_scope(p, spec, game_meta, team_id, player_id)]
        max_inning = max(p["about"]["inning"] for p in plays)
        if c.inning > max_inning:
            return {"result": "void",
                    "evidence": {"reason": f"inning {c.inning} was never played",
                                 "innings_played": max_inning}}
        if target:
            return {"result": "win", "evidence": {"plays": [_play_summary(p) for p in target]}}
        return {"result": "loss",
                "evidence": {"reason": f"no {spec.event} in inning {c.inning}"
                             + (f" ({c.half})" if c.half else "")}}

    if spec.market_family in ("count_event", "player_event"):
        if spec.event == "hit":
            event_set = HIT_EVENTS
            batting_side = True
        elif spec.event == "strikeout":
            event_set = K_EVENTS
            batting_side = False  # Ks credited to the pitching side
        elif spec.event == "home_run":
            event_set = {"home_run"}
            batting_side = True
        elif spec.event == "pitching_appearance":
            appeared = any(p["matchup"]["pitcher"]["id"] == player_id for p in plays)
            return {"result": "win" if appeared else "loss",
                    "evidence": {"pitched": appeared}}
        else:
            return {"result": "void", "evidence": {"reason": f"ungradeable event {spec.event}"}}

        matched = []
        for p in plays:
            if p["result"].get("eventType") not in event_set:
                continue
            if c.by_inning is not None and p["about"]["inning"] > c.by_inning:
                continue
            if batting_side:
                if not _matches_scope(p, spec, game_meta, team_id, player_id):
                    continue
            else:
                # strikeouts: match the pitching team / named pitcher
                if spec.scope == "team" and team_id is not None:
                    if _bat_team(p, game_meta) == team_id:
                        continue
                if spec.scope == "player" and player_id is not None:
                    if p["matchup"]["pitcher"]["id"] != player_id:
                        continue
            matched.append(p)

        n = len(matched)
        k = c.count if c.count is not None else 1
        cmp_ = c.comparator or "at_least"
        won = (n >= k) if cmp_ == "at_least" else (n == k) if cmp_ == "exactly" else (n <= k)
        return {"result": "win" if won else "loss",
                "evidence": {"count": n, "needed": f"{cmp_} {k}",
                             "plays": [_play_summary(p) for p in matched[:20]]}}

    return {"result": "void", "evidence": {"reason": f"unsupported family {spec.market_family}"}}

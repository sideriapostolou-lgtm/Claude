"""Deterministic rule-based parser.

Fallback when no Anthropic credentials are available, and the regression
baseline for parser tests. Covers the same utterance space as the LLM
few-shots: inning events, player events, distance props, count props, slang,
compounds, rejections, and ambiguity.
"""
from __future__ import annotations

import re
from typing import Optional

from .propspec import Clarification, Constraints, GameRef, ParseResult, PropSpec

HR_WORDS = r"(?:home\s*run|hr|homer(?:s)?|bomb|tater|dinger|jack|moonshot|goes\s+yard|go\s+yard|yard)"

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6,
    "7th": 7, "8th": 8, "9th": 9, "10th": 10, "11th": 11, "12th": 12,
}

MLB_TEAMS = {
    "yankees": "New York Yankees", "astros": "Houston Astros",
    "dodgers": "Los Angeles Dodgers", "nationals": "Washington Nationals",
    "red sox": "Boston Red Sox", "mets": "New York Mets",
    "braves": "Atlanta Braves", "cubs": "Chicago Cubs",
    "phillies": "Philadelphia Phillies", "padres": "San Diego Padres",
    "mariners": "Seattle Mariners", "orioles": "Baltimore Orioles",
    "rangers": "Texas Rangers", "twins": "Minnesota Twins",
    "guardians": "Cleveland Guardians", "brewers": "Milwaukee Brewers",
    "royals": "Kansas City Royals", "tigers": "Detroit Tigers",
    "giants": "San Francisco Giants", "diamondbacks": "Arizona Diamondbacks",
    "rays": "Tampa Bay Rays", "blue jays": "Toronto Blue Jays",
    "reds": "Cincinnati Reds", "pirates": "Pittsburgh Pirates",
    "cardinals": "St. Louis Cardinals", "rockies": "Colorado Rockies",
    "marlins": "Miami Marlins", "angels": "Los Angeles Angels",
    "white sox": "Chicago White Sox", "athletics": "Athletics",
}

KNOWN_PLAYERS = {
    "judge": "Aaron Judge", "aaron judge": "Aaron Judge",
    "ohtani": "Shohei Ohtani", "shohei ohtani": "Shohei Ohtani",
    "messi": "Lionel Messi", "lionel messi": "Lionel Messi",
    "soto": "Juan Soto", "juan soto": "Juan Soto",
}

UNGRADEABLE_PATTERNS = [
    (r"almost\s+scor", "Can't verify 'almost scored' from event data — try 'shot on target from 25+ yards'."),
    (r"break(?:s)?\s+(?:their|his|a)\s+bat", "Official play-by-play doesn't record broken bats, so this can't be graded."),
    (r"crowd|boo(?:s|ing)?\b|cheer", "Crowd reactions aren't in any official data feed, so this can't be graded."),
    (r"looks?\s+dominant|plays?\s+well|great\s+game", "Subjective outcomes can't be graded from official data — try a countable stat like '7+ strikeouts'."),
    (r"commentator|announcer", "What commentators say isn't in any official data feed, so this can't be graded."),
]


def _find_inning(text: str) -> tuple[Optional[int], Optional[str]]:
    half = None
    if re.search(r"\btop\s+of\b", text):
        half = "top"
    elif re.search(r"\bbottom\s+of\b", text):
        half = "bottom"
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)?\s+inning", text)
    if m:
        return int(m.group(1)), half
    m = re.search(r"inning\s+(\d+)\b", text)
    if m:
        return int(m.group(1)), half
    for word, num in ORDINALS.items():
        if re.search(rf"\b{word}\b", text):
            return num, half
    return None, half


def _find_team(text: str) -> Optional[str]:
    for key, name in MLB_TEAMS.items():
        if re.search(rf"\b{key}\b", text):
            return name
    return None


def _find_player(text: str) -> Optional[str]:
    for key in sorted(KNOWN_PLAYERS, key=len, reverse=True):
        if re.search(rf"\b{key}\b", text):
            return KNOWN_PLAYERS[key]
    return None


def _find_matchup(text: str) -> Optional[str]:
    m = re.search(r"([a-z .]+?)\s*@\s*([a-z .]+)", text)
    if m:
        away = _find_team(m.group(1)) or m.group(1).strip().title()
        home = _find_team(m.group(2)) or m.group(2).strip().title()
        return f"{away} @ {home}"
    return None


def parse_with_rules(utterance: str) -> ParseResult:
    text = utterance.lower().strip()

    # Hard gate: ungradeable
    for pattern, reason in UNGRADEABLE_PATTERNS:
        if re.search(pattern, text):
            return ParseResult(status="rejected", reason=reason)

    player = _find_player(text)
    team = _find_team(text)
    matchup = _find_matchup(text)
    game_ref = GameRef(description=matchup) if matchup else (
        GameRef(description=team) if team and re.search(r"\bgame\b", text) else None)

    # Soccer coordinate props (Messi-style distance goals)
    if re.search(r"\bgoal\b|\bscore(?:s)?\b", text) and (player == "Lionel Messi" or "yard" in text):
        dist = re.search(r"(?:exactly\s+)?(\d+(?:\.\d+)?)\s*(?:\+\s*)?yard", text)
        if dist:
            d = float(dist.group(1))
            exactly = "exactly" in text
            at_least = bool(re.search(r"(\d+)\s*\+\s*yard|outside|from\s+distance|or\s+more", text)) and not exactly
            constraints = Constraints(
                distance_yards=d,
                tolerance=0.5 if exactly else None,
                comparator="exactly" if exactly else ("at_least" if at_least else "exactly"),
            )
            if constraints.comparator == "exactly" and constraints.tolerance is None:
                constraints.tolerance = 0.5
            return ParseResult(status="ok", spec=PropSpec(
                sport="soccer", market_family="coordinate_event", event="goal",
                scope="player" if player else "either_team", player=player,
                constraints=constraints, grading_source="statsbomb"))
        if player:
            return ParseResult(status="ok", spec=PropSpec(
                sport="soccer", market_family="player_event", event="goal",
                scope="player", player=player, grading_source="statsbomb"))

    # Compound: "X AND Y"
    if re.search(r"\bpitch(?:es)?\b.*\band\b.*(homer|home\s*run|hr)\b", text) and player:
        legs = [
            PropSpec(sport="MLB", market_family="player_event", event="pitching_appearance",
                     scope="player", player=player, grading_source="mlb_pbp"),
            PropSpec(sport="MLB", market_family="player_event", event="home_run",
                     scope="player", player=player, grading_source="mlb_pbp"),
        ]
        return ParseResult(status="ok", legs=legs)

    # Count events: "2+ hits", "8+ strikeouts", "5+ Ks by the 4th"
    count_m = re.search(r"(\d+)\s*\+?\s*(hit|strikeout|k)s?\b", text)
    if not count_m:
        count_m = re.search(r"(strikes?\s+out)\s+(\d+)\s*\+", text)
        if count_m:
            count_m = re.match(r"(?P<n>\d+)\s*(?P<ev>strikeout)", f"{count_m.group(2)} strikeout")
    if count_m:
        n = int(count_m.group(1))
        ev_raw = count_m.group(2)
        event = {"hit": "hit", "strikeout": "strikeout", "k": "strikeout"}[ev_raw]
        at_least = "+" in text or "at least" in text or "or more" in text
        by_inning = None
        by_m = re.search(r"by\s+(?:the\s+)?(?:inning\s+)?(\d+)(?:st|nd|rd|th)?", text)
        if by_m:
            by_inning = int(by_m.group(1))
        else:
            for word, num in ORDINALS.items():
                if re.search(rf"by\s+the\s+{word}\b", text):
                    by_inning = num
                    break
        return ParseResult(status="ok", spec=PropSpec(
            sport="MLB", market_family="count_event", event=event,
            scope="player" if player else ("team" if team else "either_team"),
            player=player, team=team, game_ref=game_ref,
            constraints=Constraints(count=n,
                                    comparator="at_least" if at_least else "exactly",
                                    by_inning=by_inning),
            grading_source="mlb_pbp"))

    # Home run props
    if re.search(HR_WORDS, text):
        inning, half = _find_inning(text)
        # Ambiguity: "early" with no inning
        if inning is None and re.search(r"\bearly\b", text):
            base = dict(sport="MLB", event="home_run",
                        scope="player" if player else "either_team",
                        player=player, grading_source="mlb_pbp")
            return ParseResult(status="clarification_needed", clarifications=[
                Clarification(label="HR in innings 1-3",
                              spec=PropSpec(market_family="inning_event",
                                            constraints=Constraints(by_inning=3), **base)),
                Clarification(label="HR in the 1st inning",
                              spec=PropSpec(market_family="inning_event",
                                            constraints=Constraints(inning=1), **base)),
                Clarification(label="HR anytime",
                              spec=PropSpec(market_family="player_event", **base)),
            ])
        if inning is not None:
            flags = ["extra_innings"] if inning >= 10 else []
            return ParseResult(status="ok", spec=PropSpec(
                sport="MLB", market_family="inning_event", event="home_run",
                scope="player" if player else ("team" if team else "either_team"),
                player=player, team=team, game_ref=game_ref,
                constraints=Constraints(inning=inning, half=half),
                grading_source="mlb_pbp", flags=flags))
        # anytime HR
        return ParseResult(status="ok", spec=PropSpec(
            sport="MLB", market_family="player_event" if player else "inning_event",
            event="home_run",
            scope="player" if player else ("team" if team else "either_team"),
            player=player, team=team, game_ref=game_ref,
            grading_source="mlb_pbp"))

    return ParseResult(
        status="rejected",
        reason="Couldn't map that to a gradeable market — try something like 'home run in the 3rd inning' or 'Judge 2+ hits'.")

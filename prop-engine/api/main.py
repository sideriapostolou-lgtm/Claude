"""Prop Engine API (FastAPI).

POST /parse   {utterance}          -> ParseResult (spec | clarification | rejection)
POST /price   {spec}               -> fair price + risk-adjusted quote
POST /quote   {utterance, user_id} -> parse + price in one call (the consumer endpoint)
POST /grade   {prop_id}            -> settlement with play-level evidence
GET  /markets/today                -> auto-generated board (games x innings x HR)

Run: uvicorn api.main:app --reload
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engine.base import GameInfo
from engine.inning_hr import load_fits
from engine.odds import american
from engine.pricing import price as price_spec
from engine.rates import LiveRates
from engine.risk import QUOTE_TTL_SECONDS, RiskEngine
from parser import parse as parse_utterance
from parser.propspec import Constraints, PropSpec
from parser.validate import ValidationContext, fetch_context, resolve_game

BASE = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Prop Engine", version="1.0")


class Store:
    """Per-process context: rates, schedule, quote/prop registry."""

    def __init__(self):
        self.day: Optional[str] = None
        self.rates: Optional[LiveRates] = None
        self.ctx: Optional[ValidationContext] = None
        self.games: dict[int, GameInfo] = {}
        self.props: dict[str, dict] = {}  # prop_id -> {"spec", "gamePk"}
        self.risk = RiskEngine()

    def refresh(self):
        today = date.today().isoformat()
        if self.day == today and self.rates is not None:
            return
        self.day = today
        self.rates = LiveRates(SEASON)
        self.ctx = fetch_context(today)
        s = requests.Session()
        sched = s.get(f"{BASE}/schedule",
                      params={"sportId": 1, "date": today,
                              "hydrate": "probablePitcher,team,lineups"},
                      timeout=30).json()
        self.games = {}
        for d in sched.get("dates", []):
            for g in d.get("games", []):
                if g.get("gameType") != "R":
                    continue
                lineups = {}
                lu = g.get("lineups") or {}
                for side_key in ("awayPlayers", "homePlayers"):
                    for slot, p in enumerate(lu.get(side_key) or [], start=1):
                        lineups[p["id"]] = slot
                self.games[g["gamePk"]] = GameInfo(
                    gamePk=g["gamePk"],
                    away_id=g["teams"]["away"]["team"]["id"],
                    home_id=g["teams"]["home"]["team"]["id"],
                    away_name=g["teams"]["away"]["team"]["name"],
                    home_name=g["teams"]["home"]["team"]["name"],
                    venue_name=g.get("venue", {}).get("name", ""),
                    away_sp_id=(g["teams"]["away"].get("probablePitcher") or {}).get("id"),
                    home_sp_id=(g["teams"]["home"].get("probablePitcher") or {}).get("id"),
                    lineups=lineups)


store = Store()


class ParseIn(BaseModel):
    utterance: str


class QuoteIn(BaseModel):
    utterance: str
    user_id: Optional[str] = None


class GradeIn(BaseModel):
    prop_id: str


def _match_game(spec: PropSpec) -> Optional[GameInfo]:
    game = resolve_game(spec, store.ctx) if store.ctx else None
    if game is not None:
        return store.games.get(game["gamePk"])
    if spec.sport == "MLB" and spec.player and store.ctx:
        team_id = store.ctx.player_team.get(spec.player.lower())
        if team_id is not None:
            for gi in store.games.values():
                if team_id in (gi.away_id, gi.home_id):
                    if spec.team is None:
                        spec.team = store.ctx.schedule_teams.get(team_id)
                    return gi
    if spec.sport == "MLB" and store.games:
        return None  # unanchored: caller ranks all games and picks the best
    return None


def _best_game(spec: PropSpec) -> Optional[GameInfo]:
    """For unanchored props, price every slate game and take the hottest."""
    best, best_p = None, -1.0
    for gi in store.games.values():
        try:
            r = price_spec(spec, game=gi, rates=store.rates)
        except Exception:
            continue
        if r.fair_prob > best_p:
            best, best_p = gi, r.fair_prob
    return best


def _price_and_quote(spec: PropSpec, user_id: Optional[str] = None) -> dict:
    game = None
    player_id = None
    player_slot = None
    if spec.sport == "MLB":
        game = _match_game(spec) or _best_game(spec)
        if game is None:
            raise HTTPException(422, "No MLB game on today's slate matches this prop.")
        if spec.player and store.ctx:
            player_id = store.ctx.rosters.get(spec.player.lower())
            if player_id is None:
                raise HTTPException(422, f"{spec.player} not found on an active roster.")
            if player_id not in game.lineups:
                from engine.rates import modal_slots_from_corpus
                player_slot = modal_slots_from_corpus("2026").get(player_id)
    result = price_spec(spec, game=game, rates=store.rates, player_id=player_id,
                        player_slot=player_slot)
    quote = store.risk.quote(spec, result, user_id=user_id,
                             game_pk=game.gamePk if game else None)
    store.props[spec.prop_id] = {"spec": spec, "gamePk": game.gamePk if game else None,
                                 "player_id": player_id}
    return {
        "prop_id": spec.prop_id,
        "spec": spec.model_dump(exclude_none=True),
        "game": f"{game.away_name} @ {game.home_name}" if game else None,
        "fair_prob": round(result.fair_prob, 5),
        "fair_odds": american(result.fair_prob),
        "book_odds": quote.book_odds,
        "book_prob": round(quote.book_prob, 5),
        "tier": quote.tier,
        "max_stake": quote.max_stake,
        "rel_sd": round(result.rel_sd, 4),
        "inputs_used": result.inputs_used,
        "flags": quote.flags,
        "expires_at": quote.expires_at,
        "quote_ttl_seconds": QUOTE_TTL_SECONDS,
    }


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.post("/parse")
def parse_endpoint(body: ParseIn):
    store.refresh()
    return parse_utterance(body.utterance, ctx=store.ctx).model_dump(exclude_none=True)


@app.post("/price")
def price_endpoint(spec: PropSpec):
    store.refresh()
    return _price_and_quote(spec)


@app.post("/quote")
def quote_endpoint(body: QuoteIn):
    store.refresh()
    result = parse_utterance(body.utterance, ctx=store.ctx)
    if result.status == "rejected":
        return {"status": "rejected", "reason": result.reason}
    if result.status == "clarification_needed":
        return {"status": "clarification_needed",
                "clarifications": [
                    {"label": c.label, "spec": c.spec.model_dump(exclude_none=True)}
                    for c in result.clarifications]}
    if result.legs:
        return {"status": "compound",
                "legs": [_price_and_quote(leg, body.user_id) for leg in result.legs]}
    return {"status": "ok", "parsed": result.spec.model_dump(exclude_none=True)} \
        | _price_and_quote(result.spec, body.user_id)


@app.post("/grade")
def grade_endpoint(body: GradeIn):
    entry = store.props.get(body.prop_id)
    if entry is None:
        raise HTTPException(404, "unknown prop_id")
    spec: PropSpec = entry["spec"]
    if spec.sport != "MLB":
        raise HTTPException(422, "post-game grading via API is MLB-only in v1")
    game_pk = entry["gamePk"]
    pbp = requests.get(f"{BASE}/game/{game_pk}/playByPlay", timeout=30).json()
    gi = store.games.get(game_pk)
    from grading.mlb import grade
    team_id = None
    if spec.team and gi:
        team_id = gi.home_id if spec.team.lower() in gi.home_name.lower() else gi.away_id
    settlement = grade(spec, pbp, {"away_id": gi.away_id, "home_id": gi.home_id},
                       team_id=team_id, player_id=entry.get("player_id"))
    return {"prop_id": body.prop_id, **settlement}


@app.get("/markets/today")
def markets_today():
    store.refresh()
    fits = load_fits()
    board = []
    for gi in store.games.values():
        game_row = {"gamePk": gi.gamePk, "matchup": f"{gi.away_name} @ {gi.home_name}",
                    "venue": gi.venue_name, "markets": []}
        for inning in range(1, 10):
            spec = PropSpec(sport="MLB", market_family="inning_event", event="home_run",
                            scope="either_team", constraints=Constraints(inning=inning),
                            grading_source="mlb_pbp")
            r = price_spec(spec, game=gi, rates=store.rates, fits=fits)
            q = store.risk.quote(spec, r, game_pk=gi.gamePk)
            game_row["markets"].append({
                "label": f"HR in inning {inning}",
                "fair_prob": round(r.fair_prob, 4),
                "book_odds": q.book_odds, "tier": q.tier})
        board.append(game_row)
    return {"date": store.day, "generated_at": time.time(), "board": board}

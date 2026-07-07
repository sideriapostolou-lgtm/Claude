"""PropSpec — the universal prop schema.

Every prop in the system is one of these. Hard rule: if a spec cannot be
graded from an official data feed, it never reaches pricing.
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Sport = Literal["MLB", "soccer"]
MarketFamily = Literal["inning_event", "player_event", "coordinate_event", "count_event"]
Scope = Literal["either_team", "team", "player"]
GradingSource = Literal["mlb_pbp", "statsbomb", "opta"]


class GameRef(BaseModel):
    provider: str = "mlb"
    gamePk: Optional[int] = None
    description: Optional[str] = None  # e.g. "Astros @ Nationals"


class Constraints(BaseModel):
    inning: Optional[int] = None
    half: Optional[Literal["top", "bottom"]] = None
    distance_yards: Optional[float] = None
    tolerance: Optional[float] = None
    count: Optional[int] = None
    comparator: Optional[Literal["at_least", "exactly", "at_most"]] = None
    by_inning: Optional[int] = None  # for "5+ Ks by inning 4"


class PropSpec(BaseModel):
    prop_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sport: Sport
    market_family: MarketFamily
    event: str  # home_run | goal | strikeout | hit | ...
    scope: Scope
    team: Optional[str] = None
    player: Optional[str] = None
    game_ref: Optional[GameRef] = None
    constraints: Constraints = Field(default_factory=Constraints)
    gradeable: bool = True
    grading_source: Optional[GradingSource] = None
    flags: list[str] = Field(default_factory=list)  # e.g. ["extra_innings"]

    @model_validator(mode="after")
    def _gradeable_needs_source(self) -> "PropSpec":
        if self.gradeable and self.grading_source is None:
            self.grading_source = "mlb_pbp" if self.sport == "MLB" else "statsbomb"
        return self


class Clarification(BaseModel):
    """Tap-to-pick interpretation offered when an utterance is ambiguous."""
    label: str
    spec: PropSpec


class ParseResult(BaseModel):
    status: Literal["ok", "clarification_needed", "rejected"]
    spec: Optional[PropSpec] = None
    clarifications: list[Clarification] = Field(default_factory=list)
    reason: Optional[str] = None  # human-readable rejection reason
    legs: list[PropSpec] = Field(default_factory=list)  # compound props split into legs

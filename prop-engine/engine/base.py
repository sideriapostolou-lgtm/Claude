"""Shared engine types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GameInfo:
    """Pregame context for one MLB game."""
    gamePk: int
    away_id: int
    home_id: int
    away_name: str
    home_name: str
    venue_name: str = ""
    away_sp_id: Optional[int] = None
    home_sp_id: Optional[int] = None
    lineups: dict[int, int] = field(default_factory=dict)  # player_id -> slot 1-9


@dataclass
class PriceResult:
    fair_prob: float
    model_variance: float           # approximate variance of fair_prob
    rel_sd: float                   # relative sd of the estimate (risk tiering input)
    inputs_used: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"fair_prob": round(self.fair_prob, 5),
                "model_variance": self.model_variance,
                "rel_sd": round(self.rel_sd, 4),
                "inputs_used": self.inputs_used}

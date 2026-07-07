"""Pricing router: dispatch a PropSpec to its market-family model.

Every family exposes price(spec, ...) -> PriceResult{fair_prob, model_variance,
rel_sd, inputs_used}.
"""
from __future__ import annotations

from typing import Optional

from .base import GameInfo, PriceResult
from .coordinate import price_coordinate_goal
from .count_event import price_count_event
from .inning_hr import load_fits, price_inning_hr


def price(spec, game: Optional[GameInfo] = None, rates=None,
          player_id: Optional[int] = None, player_slot: Optional[int] = None,
          fits: Optional[dict] = None) -> PriceResult:
    fits = fits or load_fits()

    if spec.market_family == "coordinate_event":
        return price_coordinate_goal(spec)

    if spec.market_family == "inning_event":
        if game is None or rates is None:
            raise ValueError("inning_event pricing requires game info and rates")
        # "HR by inning N" (from clarifications) -> sum innings 1..N
        if spec.constraints.inning is None and spec.constraints.by_inning:
            import copy
            import math
            total_lam = 0.0
            rel = 0.0
            for i in range(1, spec.constraints.by_inning + 1):
                s = copy.deepcopy(spec)
                s.constraints.inning = i
                s.constraints.by_inning = None
                r = price_inning_hr(s, game, rates, fits, player_id, player_slot)
                lam_i = -math.log(max(1.0 - r.fair_prob, 1e-9))
                total_lam += lam_i
                rel = max(rel, r.rel_sd)
            p = 1.0 - math.exp(-total_lam)
            return PriceResult(fair_prob=p, model_variance=(p * rel) ** 2, rel_sd=rel,
                               inputs_used={"by_inning": spec.constraints.by_inning})
        return price_inning_hr(spec, game, rates, fits, player_id, player_slot)

    if spec.market_family == "count_event":
        if rates is None:
            raise ValueError("count_event pricing requires rates")
        return price_count_event(spec, game, rates, player_id, fits, player_slot)

    if spec.market_family == "player_event":
        # anytime props are count events with count=1 at_least
        if rates is None:
            raise ValueError("player_event pricing requires rates")
        import copy
        s = copy.deepcopy(spec)
        s.constraints.count = 1
        s.constraints.comparator = "at_least"
        return price_count_event(s, game, rates, player_id, fits, player_slot)

    raise ValueError(f"unknown market_family: {spec.market_family}")

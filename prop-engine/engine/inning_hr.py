"""MLB inning_event pricing v1.

lambda(side, inning) = teamHR_perPA x expPA(half, inning) x inningFactor(inning)
                       x parkFactor(venue) x pitcherBlend(inning)

All factors fit empirically from the 2024-2026 PBP corpus (backtest/fit_factors.py):
  - expPA includes unplayed halves (bottom 9, extras) as zeros, so "the inning
    may never happen" is priced in
  - pitcherBlend(i) = share(i) x starterFactor + (1 - share(i)) x bullpenFactor,
    where share(i) is the empirical fraction of inning-i PAs faced by the starter
  - player props use P(player gets a PA in inning | lineup slot) from the same
    corpus; lineups from the schedule hydrate when posted, slot prior otherwise

P = 1 - exp(-lambda)  (Poisson on HR intensity).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .base import GameInfo, PriceResult

ROOT = Path(__file__).resolve().parent.parent
FITS_PATH = ROOT / "data" / "fits.json"


@lru_cache(maxsize=1)
def load_fits() -> dict:
    return json.loads(FITS_PATH.read_text())


def _lambda_side(inning: int, half: str, bat_team: int, opp_sp: Optional[int],
                 opp_team: int, venue: str, rates, fits) -> tuple[float, dict, float]:
    """Poisson HR intensity for one batting side in one inning.

    Returns (lambda, inputs, rel_var) where rel_var is the relative variance
    of the estimate from finite samples.
    """
    i = str(min(inning, 12))
    team_rate, team_hr = rates.team_hr_pa(bat_team)
    exp_pa = fits["exp_pa"][half].get(i, 0.0)
    inning_f = fits["inning_hr_factor"].get(i, 1.0)
    park = fits["park_factor"].get(venue, 1.0)
    share = fits["starter_pa_share"].get(i, 0.0)
    sp_factor, sp_n = rates.pitcher_hr_factor(opp_sp)
    bullpen = getattr(rates, "team_bullpen_hr_factor", lambda _tid: 1.0)(opp_team)
    blend = share * sp_factor + (1.0 - share) * bullpen

    lam = team_rate * exp_pa * inning_f * park * blend

    hr_inning = fits["hr_by_inning"].get(f"top_{i}", 0) + fits["hr_by_inning"].get(f"bottom_{i}", 0)
    rel_var = (1.0 / max(team_hr, 4.0)
               + 1.0 / max(hr_inning, 25.0)
               + (share ** 2) / max(sp_n * rates.league_hr_pa, 4.0)
               + 0.002)  # park factor + residual model risk
    inputs = {"team_hr_pa": round(team_rate, 5), "exp_pa": round(exp_pa, 3),
              "inning_factor": round(inning_f, 3), "park_factor": round(park, 3),
              "starter_share": round(share, 3), "starter_factor": round(sp_factor, 3),
              "bullpen_factor": round(bullpen, 3)}
    return lam, inputs, rel_var


def price_inning_hr(spec, game: GameInfo, rates, fits: Optional[dict] = None,
                    player_id: Optional[int] = None,
                    player_slot: Optional[int] = None) -> PriceResult:
    fits = fits or load_fits()
    inning = spec.constraints.inning
    half = spec.constraints.half

    sides = []  # (half, bat_team, opp_sp, opp_team)
    away = ("top", game.away_id, game.home_sp_id, game.home_id)
    home = ("bottom", game.home_id, game.away_sp_id, game.away_id)
    if spec.scope == "either_team":
        sides = [away, home] if half is None else ([away] if half == "top" else [home])
    elif spec.scope == "team":
        team_l = (spec.team or "").lower()
        if team_l and team_l in game.home_name.lower():
            sides = [home]
        else:
            sides = [away]
    elif spec.scope == "player":
        if player_id is None:
            raise ValueError("player-scope inning props require a resolved player_id")
        return _price_player_inning_hr(spec, game, rates, fits, player_id, player_slot)

    total_lam, rel_var, inputs = 0.0, 0.0, {}
    for h, bat, opp_sp, opp in sides:
        lam, inp, rv = _lambda_side(inning, h, bat, opp_sp, opp,
                                    game.venue_name, rates, fits)
        total_lam += lam
        rel_var += rv * (lam ** 2)
        inputs[h] = inp | {"lambda": round(lam, 5)}
    # combine relative variances weighted by lambda contribution
    rel_var = rel_var / (total_lam ** 2) if total_lam > 0 else 1.0

    p = 1.0 - math.exp(-total_lam)
    return PriceResult(fair_prob=p, model_variance=(p * math.sqrt(rel_var)) ** 2,
                       rel_sd=math.sqrt(rel_var),
                       inputs_used={"lambda_total": round(total_lam, 5)} | inputs)


def _price_player_inning_hr(spec, game: GameInfo, rates, fits: dict,
                            player_id: int, player_slot: Optional[int]) -> PriceResult:
    """P(player HRs in inning i) ~= P(PA in inning i | slot) x P(HR | PA)."""
    inning = str(min(spec.constraints.inning, 12))
    slot = player_slot or game.lineups.get(player_id) or 4  # slot prior: middle order
    slot_source = ("lineup" if player_id in game.lineups
                   else ("given" if player_slot else "prior"))

    # batting half: home bats bottom; caller passes the player's team via
    # spec.team when known, otherwise default to the away half
    team_l = (spec.team or "").lower()
    half = "bottom" if team_l and team_l in game.home_name.lower() else "top"
    bat_team = game.home_id if half == "bottom" else game.away_id
    opp_sp = game.away_sp_id if half == "bottom" else game.home_sp_id
    opp_team = game.away_id if half == "bottom" else game.home_id

    occ = fits["slot_occupancy"][half][inning][slot - 1]
    hr_pa, n_eff = rates.player_hr_pa(player_id)
    inning_f = fits["inning_hr_factor"].get(inning, 1.0)
    park = fits["park_factor"].get(game.venue_name, 1.0)
    share = fits["starter_pa_share"].get(inning, 0.0)
    sp_factor, sp_n = rates.pitcher_hr_factor(opp_sp)
    bullpen = getattr(rates, "team_bullpen_hr_factor", lambda _tid: 1.0)(opp_team)
    blend = share * sp_factor + (1.0 - share) * bullpen

    p = occ * hr_pa * inning_f * park * blend
    rel_var = (1.0 / max(n_eff * rates.league_hr_pa, 6.0)
               + 1.0 / 200.0                     # slot occupancy sample
               + (share ** 2) / max(sp_n * rates.league_hr_pa, 4.0)
               + (0.02 if slot_source == "prior" else 0.002))
    return PriceResult(
        fair_prob=p, model_variance=(p * math.sqrt(rel_var)) ** 2,
        rel_sd=math.sqrt(rel_var),
        inputs_used={"slot": slot, "slot_source": slot_source,
                     "p_pa_in_inning": round(occ, 3),
                     "player_hr_pa": round(hr_pa, 5),
                     "inning_factor": round(inning_f, 3),
                     "park_factor": round(park, 3),
                     "pitcher_blend": round(blend, 3)})

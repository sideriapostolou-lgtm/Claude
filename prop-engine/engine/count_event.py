"""count_event pricing — Poisson/binomial compositions over the same rate inputs.

Covers e.g. "Judge 2+ hits", "8+ strikeouts for Ohtani", "5+ team Ks by inning 4".
"""
from __future__ import annotations

import math
from typing import Optional

from .base import GameInfo, PriceResult
from .inning_hr import load_fits


def _binom_tail(n_frac: float, p: float, k: int, comparator: str) -> float:
    """P(X cmp k) for X ~ Binomial with fractional expected trials.

    Mixes floor(n) and ceil(n) binomials by the fractional part so expected
    trials match the empirical PA count.
    """
    def tail(n: int) -> float:
        probs = [math.comb(n, x) * p ** x * (1 - p) ** (n - x) for x in range(n + 1)]
        if comparator == "at_least":
            return sum(probs[k:]) if k <= n else 0.0
        if comparator == "exactly":
            return probs[k] if k <= n else 0.0
        return sum(probs[:min(k, n) + 1])  # at_most
    lo, hi = math.floor(n_frac), math.ceil(n_frac)
    if lo == hi:
        return tail(lo)
    frac = n_frac - lo
    return (1 - frac) * tail(lo) + frac * tail(hi)


def _poisson_tail(lam: float, k: int, comparator: str) -> float:
    probs = [math.exp(-lam) * lam ** x / math.factorial(x) for x in range(max(k + 1, 40))]
    if comparator == "at_least":
        return 1.0 - sum(probs[:k])
    if comparator == "exactly":
        return probs[k]
    return sum(probs[:k + 1])


def price_count_event(spec, game: Optional[GameInfo], rates,
                      player_id: Optional[int] = None,
                      fits: Optional[dict] = None,
                      player_slot: Optional[int] = None) -> PriceResult:
    fits = fits or load_fits()
    c = spec.constraints
    k = c.count
    comparator = c.comparator or "at_least"

    if spec.event == "hit" and spec.scope == "player":
        if player_id is None:
            raise ValueError("player count props require a resolved player_id")
        rate, n_eff = rates.player_hit_pa(player_id)
        slot = player_slot or (game.lineups.get(player_id) if game else None) or 4
        exp_pa = fits["pa_per_slot"][str(slot)]
        p = _binom_tail(exp_pa, rate, k, comparator)
        rel_var = 1.0 / max(n_eff * rate, 10.0) + 0.005
        inputs = {"player_hit_pa": round(rate, 4), "exp_pa": round(exp_pa, 2),
                  "slot": slot, "model": "binomial"}

    elif spec.event == "strikeout":
        # Ks recorded BY the named pitcher/team's pitching staff
        by_inning = c.by_inning or 9
        exp_bf = sum(fits["exp_pa"]["top"][str(i)] + fits["exp_pa"]["bottom"][str(i)]
                     for i in range(1, by_inning + 1)) / 2.0  # one side bats each half
        if spec.scope == "player":
            if player_id is None:
                raise ValueError("player count props require a resolved player_id")
            rate, n_eff = rates.pitcher_k_pa(player_id)
            # cap batters faced by the starter's empirical share through by_inning
            share = sum(fits["starter_pa_share"][str(i)] for i in range(1, by_inning + 1)) / by_inning
            exp_bf *= share
        else:
            sp_id = None
            if game is not None:
                team_l = (spec.team or "").lower()
                sp_id = (game.home_sp_id if team_l and team_l in game.home_name.lower()
                         else game.away_sp_id)
            rate, n_eff = rates.pitcher_k_pa(sp_id)
        lam = rate * exp_bf
        p = _poisson_tail(lam, k, comparator)
        rel_var = 1.0 / max(n_eff * rate, 10.0) + 0.008
        inputs = {"k_pa": round(rate, 4), "exp_bf": round(exp_bf, 2),
                  "lambda": round(lam, 3), "model": "poisson"}

    elif spec.event == "home_run":
        if spec.scope == "player" and player_id is not None:
            rate, n_eff = rates.player_hr_pa(player_id)
            slot = player_slot or (game.lineups.get(player_id) if game else None) or 4
            exp_pa = fits["pa_per_slot"][str(slot)]
        else:
            bat_team = None
            if game is not None:
                team_l = (spec.team or "").lower()
                bat_team = (game.home_id if team_l and team_l in game.home_name.lower()
                            else game.away_id)
            rate, hr_n = rates.team_hr_pa(bat_team) if bat_team else (rates.league_hr_pa, 100)
            n_eff = max(hr_n, 1) / max(rates.league_hr_pa, 1e-6)
            exp_pa = sum(fits["exp_pa"]["top"][str(i)] for i in range(1, 10))
        lam = rate * exp_pa
        p = _poisson_tail(lam, k or 1, comparator)
        rel_var = 1.0 / max(n_eff * rates.league_hr_pa, 6.0) + 0.005
        inputs = {"hr_pa": round(rate, 5), "exp_pa": round(exp_pa, 2),
                  "lambda": round(lam, 4), "model": "poisson"}

    else:
        raise ValueError(f"count_event not implemented for event={spec.event} scope={spec.scope}")

    return PriceResult(fair_prob=p, model_variance=(p * math.sqrt(rel_var)) ** 2,
                       rel_sd=math.sqrt(rel_var), inputs_used=inputs)

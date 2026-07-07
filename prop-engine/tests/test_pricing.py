"""Pricing tests — hermetic (FakeRates, cached fits, no network)."""
import math

import pytest

from engine.base import GameInfo
from engine.coordinate import price_coordinate_goal, shot_distance
from engine.count_event import _binom_tail, _poisson_tail, price_count_event
from engine.inning_hr import load_fits, price_inning_hr
from engine.odds import american, implied_from_american
from engine.pricing import price
from parser.propspec import Constraints, PropSpec


class FakeRates:
    league_hr_pa = 0.030

    def team_hr_pa(self, team_id):
        return 0.032, 100.0

    def pitcher_hr_factor(self, pitcher_id):
        return (1.2, 500.0) if pitcher_id == 99 else (1.0, 300.0)

    def player_hr_pa(self, player_id):
        return 0.05, 600.0

    def player_hit_pa(self, player_id):
        return 0.25, 500.0

    def pitcher_k_pa(self, pitcher_id):
        return 0.28, 700.0


GAME = GameInfo(gamePk=1, away_id=10, home_id=20, away_name="Houston Astros",
                home_name="Washington Nationals", venue_name="Nationals Park",
                away_sp_id=7, home_sp_id=8)


def spec_inning(inning, scope="either_team", **kw):
    return PropSpec(sport="MLB", market_family="inning_event", event="home_run",
                    scope=scope, constraints=Constraints(inning=inning), **kw)


def test_fits_exist_and_sane():
    fits = load_fits()
    assert fits["n_games"] > 2500
    assert 0.02 < fits["league_hr_pa"] < 0.04
    # inning 1 must be hottest of 1-3 (top of order guaranteed)
    f = fits["inning_hr_factor"]
    assert f["1"] > f["2"]
    # bottom 9 has far fewer PAs than bottom 8 (home team often doesn't bat)
    assert fits["exp_pa"]["bottom"]["9"] < 0.7 * fits["exp_pa"]["bottom"]["8"]
    # starter fades: share monotonically non-increasing innings 1..9
    shares = [fits["starter_pa_share"][str(i)] for i in range(1, 10)]
    assert all(a >= b for a, b in zip(shares, shares[1:]))


def test_inning_hr_probability_range():
    r = price_inning_hr(spec_inning(3), GAME, FakeRates())
    assert 0.10 < r.fair_prob < 0.45
    assert r.model_variance > 0
    assert r.rel_sd > 0


def test_inning9_cheaper_than_inning1():
    r1 = price_inning_hr(spec_inning(1), GAME, FakeRates())
    r9 = price_inning_hr(spec_inning(9), GAME, FakeRates())
    assert r9.fair_prob < r1.fair_prob  # fewer PAs (bottom often skipped) + cooler innings


def test_team_scope_lower_than_either():
    re = price_inning_hr(spec_inning(3), GAME, FakeRates())
    rt = price_inning_hr(spec_inning(3, scope="team", team="Houston Astros"), GAME, FakeRates())
    assert rt.fair_prob < re.fair_prob


def test_half_constraint_halves_roughly():
    re = price_inning_hr(spec_inning(3), GAME, FakeRates())
    spec = spec_inning(3)
    spec.constraints.half = "top"
    rh = price_inning_hr(spec, GAME, FakeRates())
    assert 0.3 * re.fair_prob < rh.fair_prob < 0.7 * re.fair_prob


def test_pitcher_factor_moves_price():
    hot = GameInfo(**{**GAME.__dict__, "home_sp_id": 99})  # HR-prone opposing starter
    spec = spec_inning(2)
    spec.constraints.half = "top"  # away bats vs home starter
    base = price_inning_hr(spec, GAME, FakeRates())
    juiced = price_inning_hr(spec, hot, FakeRates())
    assert juiced.fair_prob > base.fair_prob


def test_player_inning_prop_uses_slot_occupancy():
    spec = spec_inning(1, scope="player", team="Houston Astros")
    spec.player = "Test Player"
    r_slot1 = price_inning_hr(spec, GAME, FakeRates(), player_id=555, player_slot=1)
    r_slot9 = price_inning_hr(spec, GAME, FakeRates(), player_id=555, player_slot=9)
    assert r_slot1.fair_prob > 5 * r_slot9.fair_prob  # leadoff always bats in inning 1
    assert r_slot1.inputs_used["p_pa_in_inning"] > 0.99  # leadoff ~always bats inning 1


def test_player_scope_requires_player_id():
    spec = spec_inning(3, scope="player")
    with pytest.raises(ValueError):
        price_inning_hr(spec, GAME, FakeRates())


# ---- count events -----------------------------------------------------------

def test_binom_tail_matches_closed_form():
    # P(X>=1) for n=4, p=0.25 = 1 - 0.75^4
    assert _binom_tail(4.0, 0.25, 1, "at_least") == pytest.approx(1 - 0.75 ** 4)


def test_poisson_tail():
    assert _poisson_tail(2.0, 1, "at_least") == pytest.approx(1 - math.exp(-2))


def test_player_hits_2plus():
    spec = PropSpec(sport="MLB", market_family="count_event", event="hit",
                    scope="player", player="X",
                    constraints=Constraints(count=2, comparator="at_least"))
    r = price_count_event(spec, GAME, FakeRates(), player_id=1, player_slot=2)
    assert 0.15 < r.fair_prob < 0.50


def test_team_ks_by_inning4():
    spec = PropSpec(sport="MLB", market_family="count_event", event="strikeout",
                    scope="team", team="Houston Astros",
                    constraints=Constraints(count=5, comparator="at_least", by_inning=4))
    r = price_count_event(spec, GAME, FakeRates())
    assert 0.05 < r.fair_prob < 0.75
    assert r.inputs_used["exp_bf"] < 20  # only ~4 innings of batters


def test_anytime_hr_via_router():
    spec = PropSpec(sport="MLB", market_family="player_event", event="home_run",
                    scope="player", player="X")
    r = price(spec, game=GAME, rates=FakeRates(), player_id=1)
    # 5% HR/PA x ~4.35 PA -> ~20%
    assert 0.12 < r.fair_prob < 0.30


# ---- coordinate events ------------------------------------------------------

def test_shot_distance():
    assert shot_distance(120, 40) == 0
    assert shot_distance(108, 40) == pytest.approx(12.0)


def test_messi_29_yarder():
    spec = PropSpec(sport="soccer", market_family="coordinate_event", event="goal",
                    scope="player", player="Lionel Messi",
                    constraints=Constraints(distance_yards=29, tolerance=0.5,
                                            comparator="exactly"))
    r = price_coordinate_goal(spec)
    assert 0.0005 < r.fair_prob < 0.02  # a longshot, but not impossible
    assert r.inputs_used["player_shots_in_band"] > 20
    assert r.inputs_used["career_minutes"] > 30000


def test_messi_25plus_more_likely_than_exact_29():
    exact = PropSpec(sport="soccer", market_family="coordinate_event", event="goal",
                     scope="player", player="Lionel Messi",
                     constraints=Constraints(distance_yards=29, tolerance=0.5,
                                             comparator="exactly"))
    broad = PropSpec(sport="soccer", market_family="coordinate_event", event="goal",
                     scope="player", player="Lionel Messi",
                     constraints=Constraints(distance_yards=25, comparator="at_least"))
    assert price_coordinate_goal(broad).fair_prob > 3 * price_coordinate_goal(exact).fair_prob


# ---- odds -------------------------------------------------------------------

def test_american_round_trip():
    for prob in (0.05, 0.25, 0.5, 0.75, 0.9):
        assert implied_from_american(american(prob)) == pytest.approx(prob, abs=0.01)


def test_american_never_exceeds_cap():
    assert american(0.999) == american(0.985)

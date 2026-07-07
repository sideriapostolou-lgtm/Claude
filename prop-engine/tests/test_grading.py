"""Grading tests against canned fixtures (real PBP + synthetic soccer events)."""
import json
from pathlib import Path

import pytest

from grading.mlb import grade as grade_mlb
from grading.soccer import grade as grade_soccer
from parser.propspec import Constraints, PropSpec

FIXTURES = Path(__file__).parent / "fixtures"
# Game 824089 (2026-07-06, PHI @ KC): HRs in bottom 1 (Maile), bottom 2 (Perez),
# bottom 4 (Thomas), bottom 5 (Tolbert). away=143 PHI, home=118 KC.
PBP = json.loads((FIXTURES / "pbp_824089.json").read_text())
META = {"away_id": 143, "home_id": 118}


def inning_spec(inning, scope="either_team", half=None, **kw):
    return PropSpec(sport="MLB", market_family="inning_event", event="home_run",
                    scope=scope, constraints=Constraints(inning=inning, half=half), **kw)


def test_win_with_play_evidence():
    r = grade_mlb(inning_spec(1), PBP, META)
    assert r["result"] == "win"
    play = r["evidence"]["plays"][0]
    assert play["batter"] == "Luke Maile"
    assert play["inning"] == 1 and play["half"] == "bottom"
    assert play["event"] == "home_run"


def test_loss_when_no_hr_in_inning():
    assert grade_mlb(inning_spec(3), PBP, META)["result"] == "loss"


def test_half_constraint():
    assert grade_mlb(inning_spec(1, half="bottom"), PBP, META)["result"] == "win"
    assert grade_mlb(inning_spec(1, half="top"), PBP, META)["result"] == "loss"


def test_team_scope():
    # all 4 HRs were by the home team (KC)
    win = grade_mlb(inning_spec(2, scope="team", team="Kansas City Royals"),
                    PBP, META, team_id=118)
    loss = grade_mlb(inning_spec(2, scope="team", team="Philadelphia Phillies"),
                     PBP, META, team_id=143)
    assert win["result"] == "win"
    assert loss["result"] == "loss"


def test_void_when_inning_never_played():
    r = grade_mlb(inning_spec(12), PBP, META)
    assert r["result"] == "void"
    assert "never played" in r["evidence"]["reason"]


def test_player_count_event():
    # Salvador Perez homered in inning 2 -> 1+ HR wins for him
    spec = PropSpec(sport="MLB", market_family="count_event", event="home_run",
                    scope="player", player="Salvador Perez",
                    constraints=Constraints(count=1, comparator="at_least"))
    pid = next(p["matchup"]["batter"]["id"] for p in PBP["allPlays"]
               if p["matchup"]["batter"]["fullName"] == "Salvador Perez")
    assert grade_mlb(spec, PBP, META, player_id=pid)["result"] == "win"
    spec2 = spec.model_copy(deep=True)
    spec2.constraints.count = 2
    assert grade_mlb(spec2, PBP, META, player_id=pid)["result"] == "loss"


def test_count_by_inning_gate():
    # HRs through inning 2: exactly 2 (Maile inn 1, Perez inn 2)
    spec = PropSpec(sport="MLB", market_family="count_event", event="home_run",
                    scope="either_team",
                    constraints=Constraints(count=3, comparator="at_least", by_inning=2))
    assert grade_mlb(spec, PBP, META)["result"] == "loss"
    spec.constraints.count = 2
    assert grade_mlb(spec, PBP, META)["result"] == "win"


def test_void_on_empty_pbp():
    assert grade_mlb(inning_spec(1), {"allPlays": []}, META)["result"] == "void"


# ---- soccer -----------------------------------------------------------------

def shot_event(player, x, y, outcome="Goal", minute=30):
    return {"type": {"name": "Shot"}, "minute": minute,
            "player": {"name": player}, "location": [x, y],
            "shot": {"outcome": {"name": outcome}}}


MESSI = "Lionel Andrés Messi Cuccittini"


def coord_spec(dist, tol=0.5, comparator="exactly"):
    return PropSpec(sport="soccer", market_family="coordinate_event", event="goal",
                    scope="player", player=MESSI,
                    constraints=Constraints(distance_yards=dist, tolerance=tol,
                                            comparator=comparator))


def test_soccer_win_exact_band():
    # goal from exactly 29 yds: x = 120-29, y = 40
    events = [shot_event(MESSI, 91.0, 40.0)]
    r = grade_soccer(coord_spec(29), events)
    assert r["result"] == "win"
    assert r["evidence"]["goals"][0]["distance_yards"] == pytest.approx(29.0)


def test_soccer_loss_outside_band():
    events = [shot_event(MESSI, 95.0, 40.0)]  # 25 yds
    assert grade_soccer(coord_spec(29), events)["result"] == "loss"


def test_soccer_loss_not_a_goal():
    events = [shot_event(MESSI, 91.0, 40.0, outcome="Saved")]
    assert grade_soccer(coord_spec(29), events)["result"] == "loss"


def test_soccer_loss_wrong_player():
    events = [shot_event("Luis Suárez", 91.0, 40.0)]
    assert grade_soccer(coord_spec(29), events)["result"] == "loss"


def test_soccer_at_least_comparator():
    events = [shot_event(MESSI, 85.0, 40.0)]  # 35 yds
    assert grade_soccer(coord_spec(25, comparator="at_least"), events)["result"] == "win"
    assert grade_soccer(coord_spec(40, comparator="at_least"), events)["result"] == "loss"

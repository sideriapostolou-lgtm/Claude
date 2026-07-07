"""Parser tests: 30 utterances -> expected specs, including adversarial cases.

Run against the deterministic rule parser (use_llm=False) so tests are
hermetic; the LLM parser conforms to the same ParseResult contract.
"""
import pytest

from parser import parse
from parser.propspec import PropSpec
from parser.validate import ValidationContext, validate


def p(utterance):
    return parse(utterance, use_llm=False)


# ---- inning events (incl. slang) -------------------------------------------

@pytest.mark.parametrize("utt,inning,half", [
    ("third inning home run", 3, None),
    ("home run in the 3rd inning", 3, None),
    ("HR in inning 7", 7, None),
    ("bomb in the top of the 5th", 5, "top"),
    ("tater in the bottom of the ninth", 9, "bottom"),
    ("dinger in the 2nd", 2, None),
    ("jack in the 4th inning", 4, None),
    ("moonshot in the first", 1, None),
    ("home run in the eighth", 8, None),
])
def test_inning_hr(utt, inning, half):
    r = p(utt)
    assert r.status == "ok"
    s = r.spec
    assert s.market_family == "inning_event"
    assert s.event == "home_run"
    assert s.constraints.inning == inning
    assert s.constraints.half == half
    assert s.gradeable and s.grading_source == "mlb_pbp"


def test_team_scoped_inning_hr():
    r = p("Yankees tater in the 1st")
    assert r.status == "ok"
    assert r.spec.scope == "team"
    assert r.spec.team == "New York Yankees"
    assert r.spec.constraints.inning == 1


def test_matchup_reference():
    r = p("Astros @ Nationals, jack in the 3rd")
    assert r.status == "ok"
    assert "Astros" in r.spec.game_ref.description


def test_extra_innings_flagged_but_valid():
    r = p("HR in the 10th inning")
    assert r.status == "ok"
    assert "extra_innings" in r.spec.flags


def test_inning_12_flagged():
    r = p("home run in the 12th inning")
    assert r.status == "ok"
    assert "extra_innings" in r.spec.flags


# ---- player events ----------------------------------------------------------

def test_player_anytime_hr():
    r = p("Aaron Judge homers tonight")
    assert r.status == "ok"
    assert r.spec.market_family == "player_event"
    assert r.spec.player == "Aaron Judge"
    assert r.spec.scope == "player"


def test_player_slang_hr():
    r = p("Ohtani goes yard in the 6th")
    assert r.status == "ok"
    assert r.spec.player == "Shohei Ohtani"
    assert r.spec.constraints.inning == 6


# ---- count events -----------------------------------------------------------

def test_player_hits_count():
    r = p("Judge 2+ hits")
    s = r.spec
    assert s.market_family == "count_event"
    assert s.event == "hit"
    assert s.constraints.count == 2
    assert s.constraints.comparator == "at_least"


def test_team_ks_by_inning():
    r = p("5+ strikeouts by the Astros by the 4th")
    s = r.spec
    assert s.event == "strikeout"
    assert s.constraints.count == 5
    assert s.constraints.by_inning == 4
    assert s.team == "Houston Astros"


def test_soto_hits():
    r = p("Soto 3+ hits")
    assert r.spec.player == "Juan Soto"
    assert r.spec.constraints.count == 3


# ---- coordinate events ------------------------------------------------------

def test_messi_exact_distance():
    r = p("Messi to score from exactly 29 yards")
    s = r.spec
    assert s.sport == "soccer"
    assert s.market_family == "coordinate_event"
    assert s.player == "Lionel Messi"
    assert s.constraints.distance_yards == 29
    assert s.constraints.tolerance == 0.5
    assert s.grading_source == "statsbomb"


def test_messi_at_least_distance():
    r = p("Messi goal from 25+ yards")
    assert r.spec.constraints.comparator == "at_least"
    assert r.spec.constraints.distance_yards == 25


def test_messi_anytime():
    r = p("Messi to score")
    assert r.status == "ok"
    assert r.spec.market_family == "player_event"


# ---- compound ---------------------------------------------------------------

def test_compound_split_into_legs():
    r = p("Ohtani to pitch AND homer")
    assert r.status == "ok"
    assert r.spec is None
    assert len(r.legs) == 2
    assert {leg.event for leg in r.legs} == {"pitching_appearance", "home_run"}
    assert all(leg.player == "Shohei Ohtani" for leg in r.legs)


# ---- ambiguity --------------------------------------------------------------

def test_ambiguous_early_offers_clarifications():
    r = p("Judge goes yard early")
    assert r.status == "clarification_needed"
    assert 2 <= len(r.clarifications) <= 3
    assert all(c.spec.player == "Aaron Judge" for c in r.clarifications)


# ---- rejections: the integrity gate -----------------------------------------

@pytest.mark.parametrize("utt", [
    "Messi almost scores from distance",
    "someone breaks their bat in the 2nd",
    "the crowd boos in the 7th",
    "Ohtani looks dominant tonight",
    "the announcer says 'unbelievable'",
])
def test_ungradeable_rejected_with_reason(utt):
    r = p(utt)
    assert r.status == "rejected"
    assert r.reason and len(r.reason) > 10


def test_gibberish_rejected():
    r = p("purple monkey dishwasher")
    assert r.status == "rejected"


# ---- deterministic validation gates ----------------------------------------

def test_validate_rejects_inning_zero():
    r = p("third inning home run")
    r.spec.constraints.inning = 0
    assert validate(r).status == "rejected"


def test_validate_rejects_absurd_distance():
    r = p("Messi to score from exactly 29 yards")
    r.spec.constraints.distance_yards = 200.0
    assert validate(r).status == "rejected"


def test_validate_rejects_ungradeable_spec():
    from parser.propspec import ParseResult
    spec = PropSpec(sport="MLB", market_family="inning_event", event="home_run",
                    scope="either_team", gradeable=False)
    spec.grading_source = None
    spec.gradeable = False
    r = validate(ParseResult(status="ok", spec=spec))
    assert r.status == "rejected"


def test_validate_game_must_be_on_schedule():
    ctx = ValidationContext(games=[{
        "gamePk": 1, "teams": {
            "away": {"team": {"id": 1, "name": "Houston Astros"}},
            "home": {"team": {"id": 2, "name": "Washington Nationals"}}}}])
    ok = p("Astros @ Nationals, jack in the 3rd")
    assert validate(ok, ctx).status == "ok"
    bad = p("Yankees tater in the 1st")  # Yankees not on this slate
    assert validate(bad, ctx).status == "rejected"


def test_validate_player_must_be_on_roster():
    ctx = ValidationContext(rosters={"shohei ohtani": 660271})
    r = p("Aaron Judge homers tonight")
    assert validate(r, ctx).status == "rejected"
    r2 = p("Ohtani goes yard in the 6th")
    assert validate(r2, ctx).status == "ok"

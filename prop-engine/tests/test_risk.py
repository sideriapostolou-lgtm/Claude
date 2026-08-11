"""Risk engine tests: tiering, margins, caps, velocity flags, quote logging."""
import json

import pytest

from engine.base import PriceResult
from engine.odds import MAX_IMPLIED
from engine.risk import TIERS, RiskEngine
from parser.propspec import Constraints, PropSpec


def spec(family="inning_event", **ckw):
    return PropSpec(sport="MLB", market_family=family, event="home_run",
                    scope="either_team", constraints=Constraints(**ckw))


def pr(fair=0.22, rel_sd=0.2):
    return PriceResult(fair_prob=fair, model_variance=(fair * rel_sd) ** 2, rel_sd=rel_sd)


@pytest.fixture
def risk(tmp_path):
    return RiskEngine(quote_log=tmp_path / "quotes.jsonl")


def test_tier_a_liquid_low_variance(risk):
    s = spec(family="player_event")
    assert risk.classify_tier(s, pr(rel_sd=0.10)) == "A"


def test_tier_b_standard_exotic(risk):
    assert risk.classify_tier(spec(inning=3), pr(rel_sd=0.22)) == "B"


def test_tier_c_weird_constraint(risk):
    s = spec(family="coordinate_event", distance_yards=29, tolerance=0.5)
    assert risk.classify_tier(s, pr(fair=0.004, rel_sd=0.2)) == "C"


def test_tier_c_high_variance(risk):
    assert risk.classify_tier(spec(inning=3), pr(rel_sd=0.6)) == "C"


def test_tier_c_extra_innings(risk):
    s = spec(inning=10)
    s.flags.append("extra_innings")
    assert risk.classify_tier(s, pr(rel_sd=0.2)) == "C"


def test_margin_applied_by_tier(risk):
    s = spec(inning=3)
    price = pr(fair=0.20, rel_sd=0.22)
    q = risk.quote(s, price)
    assert q.tier == "B"
    assert q.book_prob == pytest.approx(0.20 * TIERS["B"]["margin"])
    assert q.max_stake == TIERS["B"]["max_stake"]


def test_never_above_985_implied(risk):
    q = risk.quote(spec(inning=3), pr(fair=0.97, rel_sd=0.1))
    assert q.book_prob <= MAX_IMPLIED


def test_exposure_cap(risk):
    s = spec(inning=3)
    risk.record_bet(game_pk=1, potential_payout=4990)
    q = risk.quote(s, pr(), game_pk=1)
    assert q.max_stake <= 10.0
    risk.record_bet(game_pk=1, potential_payout=100)
    q2 = risk.quote(s, pr(), game_pk=1)
    assert q2.max_stake == 0.0
    assert "exposure_cap_reached" in q2.flags


def test_velocity_flag(risk):
    s = spec(inning=3)
    for _ in range(6):
        q = risk.quote(s, pr(), user_id="sharp_carl")
    assert "velocity_flag" in q.flags
    assert q.max_stake <= 10.0


def test_every_quote_logged(risk, tmp_path):
    risk.quote(spec(inning=3), pr(), user_id="u1", game_pk=42)
    risk.quote(spec(inning=4), pr(), user_id="u2", game_pk=42)
    lines = (tmp_path / "quotes.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert {"quote_id", "fair_prob", "book_prob", "tier", "rel_sd"} <= rec.keys()


def test_quote_expiry_set(risk):
    import time
    q = risk.quote(spec(inning=3), pr())
    assert 80 < q.expires_at - time.time() <= 91

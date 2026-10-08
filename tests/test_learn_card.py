"""learning_card_state(settings, now): the dashboard's learning card (docs/LEARNING.md §9). Pure read,
never raises, every key always present, 60 s cache, never creates learn.db."""

from __future__ import annotations

import json

import pytest

from nightcrawler.learn import card
from nightcrawler.learn.card import EMPTY_KEYS, learning_card_state
from nightcrawler.learn.store import LearnStore, db_path, learn_dir
from nightcrawler.learn.variants import make_spec, register_seeds
from nightcrawler.models import StrategyParams

NOW = 1_791_475_200.0  # 2026-10-08T16:00Z
DAY = 86400.0


@pytest.fixture(autouse=True)
def _no_cache():
    card.clear_cache()
    yield
    card.clear_cache()


def check_shape(state: dict) -> None:
    assert set(EMPTY_KEYS) <= set(state)
    json.dumps(state, allow_nan=False)  # JSON-native, no NaN
    for key in ("data", "budget", "live", "paper_variant"):
        assert isinstance(state[key], dict)
    assert isinstance(state["top"], list) and isinstance(state["events"], list)


def test_no_learn_db_yet_means_collecting_day_1(settings) -> None:
    state = learning_card_state(settings, NOW)
    check_shape(state)
    assert state["state"] == "collecting" and state["headline"] == "Collecting data, day 1"
    assert state["champion"] is None and state["top"] == [] and state["live"]["ready"] is False
    assert not learn_dir(settings.data_dir).exists()  # reading never creates anything


def test_learning_off(make_settings) -> None:
    state = learning_card_state(make_settings(LEARN_ENABLED=False), NOW)
    check_shape(state)
    assert state["state"] == "off" and "off" in state["headline"].lower()


def test_collecting_counts_days_since_the_first_coin(settings) -> None:
    with LearnStore(db_path(settings.data_dir)) as store:
        store.add_coin("M1", created_ts=NOW - 2.5 * DAY, first_seen_ts=NOW - 2.5 * DAY, day="2026-10-06")
        store.add_coin("M2", created_ts=NOW - 1.2 * DAY, first_seen_ts=NOW - 1.2 * DAY, day="2026-10-07")
        store.set_coin_status("M2", "closed")
    state = learning_card_state(settings, NOW)
    check_shape(state)
    assert state["headline"] == "Collecting data, day 3"
    assert state["data"]["coins_yesterday"] == 1 and state["data"]["coins_total"] == 2
    assert state["data"]["completeness_pct"] == 100.0


def test_practice_shows_the_top_three_by_proof_and_the_placebo(settings) -> None:
    anchor = StrategyParams()
    with LearnStore(db_path(settings.data_dir)) as store:
        register_seeds(store, anchor, NOW - 9 * DAY)
        rows = store.variants()
        for i, v in enumerate(rows):
            control = v["family"] == "placebo"
            store.put_scoreboard("2026-10-08", v["hash"], {
                "n": 40 + i, "mean": -0.048 if control else 0.01 * i, "log_e": 0.5 * i, "proof": 0.1 * i,
                "eta_trades": None if control else 300.0, "status": "testing", "name": v["name"],
                "family": v["family"], "control": control}, NOW - 600)
    state = learning_card_state(settings, NOW)
    check_shape(state)
    assert state["state"] == "practice" and "nothing has proven an edge" in state["headline"]
    assert len(state["top"]) == 3 and [t["proof"] for t in state["top"]] == sorted(
        (t["proof"] for t in state["top"]), reverse=True)
    assert all(len(t["hash12"]) == 12 and t["name"] for t in state["top"])
    placebo_n = 40 + next(i for i, v in enumerate(rows) if v["family"] == "placebo")
    assert state["placebo"]["n"] == placebo_n and state["placebo"]["mean_pct"] == pytest.approx(-4.8)
    assert state["placebo"]["ok"] is True  # losing, as it should
    assert state["budget"]["registrations_this_week"] == 0 and state["budget"]["trials_total"] == 2800
    assert state["updated_at"] == NOW - 600
    assert [e["text"] for e in state["events"]][:1] and all(e["seq"] is None for e in state["events"])


def test_a_placebo_that_wins_is_flagged(settings) -> None:
    spec = make_spec("placebo", {}, StrategyParams())
    with LearnStore(db_path(settings.data_dir)) as store:
        store.put_scoreboard("2026-10-08", spec.hash, {"n": 300, "mean": 0.02, "log_e": 0.0, "proof": 0.0,
                                                       "status": "testing", "name": spec.name, "family": "placebo",
                                                       "control": True}, NOW)
    assert learning_card_state(settings, NOW)["placebo"]["ok"] is False


def test_a_broken_learn_db_never_raises(settings) -> None:
    path = db_path(settings.data_dir)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a sqlite file at all" * 100)
    state = learning_card_state(settings, NOW)
    check_shape(state)
    assert state["state"] == "unavailable"


def test_never_raises_even_on_a_bad_settings_object() -> None:
    state = learning_card_state(object(), NOW)
    check_shape(state)


def test_the_state_is_cached_for_60_seconds(settings) -> None:
    first = learning_card_state(settings, NOW)
    with LearnStore(db_path(settings.data_dir)) as store:
        store.add_coin("M1", created_ts=NOW - 3 * DAY, first_seen_ts=NOW - 3 * DAY, day="2026-10-05")
    assert learning_card_state(settings, NOW + 59) == first
    assert learning_card_state(settings, NOW + 61)["headline"] == "Collecting data, day 4"

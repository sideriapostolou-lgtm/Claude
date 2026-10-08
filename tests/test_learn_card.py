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
    for key in ("stats", "budget", "live", "paper_variant"):
        assert isinstance(state[key], dict)
    assert isinstance(state["top"], list) and isinstance(state["events"], list)
    # what the one-page dashboard reads (pagestate.learning_card): plain strings and a variants list
    assert isinstance(state["headline"], str) and state["headline"] and isinstance(state["state"], str)
    assert isinstance(state["data"], str) and state["data_line"] == state["data"]
    assert isinstance(state["variants"], list)
    for v in state["variants"]:
        assert isinstance(v["name"], str) and v["name"] and isinstance(v["n"], int) and v["n"] >= 0
        assert v["avg"] is None or isinstance(v["avg"], float)
        assert isinstance(v["proof"], float) and 0.0 <= v["proof"] <= 1.0


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
    assert state["stats"]["coins_yesterday"] == 1 and state["stats"]["coins_total"] == 2
    assert state["stats"]["completeness_pct"] == 100.0 and state["stats"]["days"] == 2
    assert state["data"].startswith("Data: 2 coins taped · 2 days · ") and " GB of 3 GB" in state["data"]


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
    assert state["state"] == "practice" and state["headline"] == "Practice: promotions start in phase 2"
    assert "No idea has proven an edge yet" in state["subline"]
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


def test_the_variants_line_up_the_top_three_then_the_placebo(settings) -> None:
    anchor = StrategyParams()
    with LearnStore(db_path(settings.data_dir)) as store:
        register_seeds(store, anchor, NOW - 9 * DAY)
        for i, v in enumerate(store.variants()):
            control = v["family"] == "placebo"
            store.put_scoreboard("2026-10-08", v["hash"], {
                "n": 10 * (i + 1), "mean": -0.064 if control else 0.012 * i, "log_e": 0.1 * i,
                "proof": 0.0 if control else 0.05 * i, "status": "testing", "name": v["name"],
                "family": v["family"], "control": control}, NOW - 60)
    state = learning_card_state(settings, NOW)
    check_shape(state)
    names = [v["name"] for v in state["variants"]]
    assert len(names) == 4 and names[-1] == "random entry (control)" and state["variants"][-1]["control"]
    assert names[:3] == [t["name"] for t in state["top"]]
    first = state["variants"][0]
    assert (first["n"], first["avg"], first["proof"]) == (state["top"][0]["n"], state["top"][0]["mean_pct"],
                                                         state["top"][0]["proof"])
    assert state["variants"][-1]["avg"] == pytest.approx(-6.4)  # percent per trade, like the page shows it


def test_every_string_is_scrubbed_of_secrets_and_control_characters(make_settings) -> None:
    token = "dash-token-very-secret-0123"
    settings = make_settings(DASHBOARD_TOKEN=token)
    spec = make_spec("dip_rebound", {"dip_pct": 0.6}, StrategyParams())
    with LearnStore(db_path(settings.data_dir)) as store:
        store.add_variant(spec.hash, family="dip_rebound", params=spec.params, source="seed", alpha=0.005,
                          threshold=200.0, promotable=True, name=f"dip {token}\x1b[31m\n<b>x</b>" + "y" * 500,
                          now=NOW - DAY)
        store.put_scoreboard("2026-10-08", spec.hash, {"n": 12, "mean": 0.01, "log_e": 0.1, "proof": 0.02,
                                                       "status": "testing", "name": f"dip {token}\x07",
                                                       "family": "dip_rebound", "control": False}, NOW - 60)
    state = learning_card_state(settings, NOW)
    check_shape(state)
    text = json.dumps(state)
    assert token not in text and "[REDACTED]" in text
    strings = []

    def walk(value) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(state)
    assert all(ch.isprintable() for text in strings for ch in text)
    assert all(len(text) <= card.TEXT_MAX for text in strings)


def test_the_empty_state_is_well_formed_for_the_page(settings) -> None:
    state = learning_card_state(settings, NOW)
    check_shape(state)
    assert (state["state"], state["headline"], state["variants"]) == ("collecting", "Collecting data, day 1", [])
    assert state["data"] == "Data: 0 coins taped · 0 days · 0.000 GB of 3 GB"

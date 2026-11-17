"""Report cards (docs/EXPERIENCE.md §5, §9, §11 ``test_cards_null_and_power``, ``test_alpha_ledger``,
``test_broker_paper``).

* NULL: every vs-chance card is labelled "Skill shown" in at most 1 % + 3 SE of 500 runs - a random veto at the same
  rate (Cocoon, Jev), random entries (Strategy), a random-time radar on a DOWN-DRIFTING tape (Radar).
* POWER: a planted effect reaches "Skill shown" in >= 80 % of runs. With one block per judged day and y = metric / 2
  in [-1, 1] (§5.1), the always-valid band needs on the order of Σ log(1 + 0.7 y) >= log(2 / α) + log 6, so the days
  needed are long; the tests pin how many (see ``POWER_DAYS``).
* α LEDGER: on null data with 10 member-version changes, P(ever "Skill shown") <= 1 %.
* Broker on paper is always "Not measured"; "Skill shown" never appears with a band crossing the baseline; only
  forward rows of coins created after t0 with ready labels count.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.experience import cards, playbook, stats, texts
from nightcrawler.experience.constants import MEMBERS, MIN_DAYS
from nightcrawler.learn import evidence as ev

RUNS = 500
#: 1 % + 3 standard errors of a 1 % rate over RUNS runs.
NULL_MAX = math.floor(RUNS * (0.01 + 3 * math.sqrt(0.01 * 0.99 / RUNS)))
DAY0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
MEMBER_KEYS = {"kind", "label", "chip", "line", "graded", "days", "practised", "metrics", "exam", "trend",
               "version_line", "independent", "lessons", "coverage", "budget_left"}
METRIC_KEYS = {"name", "value", "lo", "hi", "baseline", "unit", "text"}
STATE_KEYS = {"source", "headline", "bars_line", "money_line", "caveat", "team", "members", "loss_types_week",
              "lessons", "playbook"}
TEAM_KEYS = {"graded", "days", "practised", "practised_window", "skills_shown", "skills_measurable", "collecting",
             "not_measured", "updated_at"}


def day(i: int) -> str:
    return (DAY0 + timedelta(days=i)).strftime("%Y-%m-%d")


def clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def random_coin(rng: random.Random, bad_share: float = 0.25) -> tuple[float, bool]:
    """x of a random entry and whether the coin was bad (rugs lose ~ -90 %, the rest bleed costs)."""
    bad = rng.random() < bad_share
    return (clip(rng.gauss(-0.85, 0.1)) if bad else clip(rng.gauss(-0.03, 0.25))), bad


def r_rows(rng: random.Random, days: int, per_day: int, block: Any = None, tag: str = "") -> list[dict[str, Any]]:
    """R-host journal rows; ``block(x, bad, rng)`` decides the Cocoon verdict (default: a random 15 % veto)."""
    rows = []
    for d in range(days):
        for i in range(per_day):
            x, bad = random_coin(rng)
            fail = block(x, bad, rng) if block else rng.random() < 0.15
            rows.append({"mint": f"{tag}M{d}-{i}", "source": "forward", "host": "R", "day": day(d),
                         "operator": f"op{rng.randrange(10_000)}", "created_ts": 1.0, "t_dec": 100.0,
                         "cocoon": "fail" if fail else "pass", "cocoon_ts": 50.0,
                         "cocoon_rules": ["top10"] if fail else [], "x": x, "crash50": bad, "dead": False})
    return rows


def label_counts(make: Any, runs: int = RUNS) -> dict[str, int]:
    out: dict[str, int] = {}
    for run in range(runs):
        label = make(random.Random(run))["label"]
        out[label] = out.get(label, 0) + 1
    return out


# --------------------------------------------------------------------------- schema


def test_every_card_and_the_state_have_exactly_the_frozen_keys() -> None:
    state = cards.empty_state()
    assert set(state) == STATE_KEYS and state["source"] == "missing"
    assert set(state["team"]) == TEAM_KEYS and state["team"]["skills_measurable"] == 4
    assert set(state["members"]) == {m for m, _, _ in MEMBERS}
    assert state["caveat"] == "Avoiding losses is not the same as making money."
    assert state["money_line"] == "Making money: not shown yet — holding cash."
    for member, card in state["members"].items():
        assert set(card) == MEMBER_KEYS, member
        assert card["chip"] == texts.chip_word(member, card["label"])
    rng = random.Random(1)
    built = [cards.cocoon_card(r_rows(rng, 8, 40)), cards.coach_card([-0.05] * 300, [True] * 80 + [False] * 20),
             cards.receipts_card({"chain": True}), cards.broker_card([{"ts": 12.0, "decision_ts": 10.0}]),
             cards.risk_card([]), cards.crawler_card([]), cards.radar_card([]), cards.jev_card([]),
             cards.strategy_card([], [])]
    for card in built:
        assert set(card) == MEMBER_KEYS
        assert len(card["metrics"]) <= 3 and all(set(m) == METRIC_KEYS for m in card["metrics"])
        assert all(m["unit"] in ("pp", "share", "ratio", "count", "s") for m in card["metrics"])


def test_labels_follow_the_order_of_section_5_1() -> None:
    lab = stats.chance_label
    assert lab(measured=False, enough=True, lo=0.1, hi=0.2, stable_ok=True) == "not_measured"
    assert lab(measured=True, enough=False, lo=0.1, hi=0.2, stable_ok=True) == "not_enough"
    assert lab(measured=True, enough=True, lo=-0.3, hi=-0.1, stable_ok=True) == "worse"
    assert lab(measured=True, enough=True, lo=0.01, hi=0.2, stable_ok=True) == "skilled"
    assert lab(measured=True, enough=True, lo=0.01, hi=0.2, stable_ok=False) == "no_skill_yet"  # the veto
    assert lab(measured=True, enough=True, lo=-0.01, hi=0.2, stable_ok=True) == "no_skill_yet"
    bar = stats.bar_label
    assert bar(measured=True, enough=True, lo=0.91, hi=0.99, bar=0.9) == "meets_bar"
    assert bar(measured=True, enough=True, lo=0.80, hi=0.89, bar=0.9) == "below_bar"
    assert bar(measured=True, enough=True, lo=0.85, hi=0.95, bar=0.9) == "not_enough"  # a bar card keeps collecting
    assert bar(measured=True, enough=True, lo=0.1, hi=0.4, bar=0.5, higher_is_better=False) == "meets_bar"
    assert bar(measured=True, enough=True, lo=0.6, hi=0.9, bar=0.5, higher_is_better=False) == "below_bar"


def test_a_source_that_exists_but_has_nothing_graded_is_collecting() -> None:
    assert cards.cocoon_card([])["label"] == "not_enough"
    assert cards.jev_card([], cards.CardContext(source_ready=False))["label"] == "not_measured"
    team = cards.team_summary({"cocoon": cards.cocoon_card([]), "strategy": cards.strategy_card([], []),
                               "radar": cards.radar_card([]),
                               "judge": cards.jev_card([], cards.CardContext(source_ready=False)),
                               "crawler": cards.crawler_card([]), "broker": cards.broker_card([]),
                               "risk": cards.risk_card([])},
                              graded=0, days=0, practised=450, practised_days=1)
    assert team["headline"] == [
        "Practice record: 0 new coins graded over 0 days; 450 past coins practised (1 day, first 3 hours after "
        "graduation only).",
        "Skills shown (99% check): 0 of 4. Still collecting: 3 (Cocoon, Strategy, Radar); Jev is off."]
    assert team["bars_line"] == "Bars: Crawler collecting · Broker not measured on paper · Risk collecting."
    assert team["team"]["not_measured"] == ["judge"] and team["team"]["collecting"] == 3


# --------------------------------------------------------------------------- forward-only and as-of


def test_only_forward_rows_after_t0_with_ready_labels_count() -> None:
    rows = r_rows(random.Random(2), 10, 40)
    base = cards.cocoon_card(rows)
    history = [{**r, "source": "history", "split": "train"} for r in rows]
    assert cards.cocoon_card(history)["label"] == "not_enough" and cards.cocoon_card(history)["graded"] == 0
    early = [{**r, "created_ts": 0.5} for r in rows]
    assert cards.cocoon_card(rows + early, cards.CardContext(t0=0.9))["graded"] == base["graded"]
    late = [{**r, "label_ready_ts": 1e12} for r in rows]
    assert cards.cocoon_card(rows + late, cards.CardContext(now=1e9))["graded"] == base["graded"]


def test_a_verdict_decided_after_the_entry_counts_as_unchecked() -> None:
    rows = r_rows(random.Random(3), 10, 40)
    late = [{**r, "cocoon_ts": r["t_dec"] + 1} for r in rows[:100]]
    card = cards.cocoon_card(late + rows[100:])
    assert card["graded"] == len(rows) - 100
    assert card["coverage"].startswith(f"Checked {round(100 * (len(rows) - 100) / len(rows))}% of graded coins")


# --------------------------------------------------------------------------- null: no false "Skill shown"


def test_null_cocoon_random_veto_at_the_same_rate() -> None:
    counts = label_counts(lambda rng: cards.cocoon_card(r_rows(rng, 21, 40)))
    assert counts.get("skilled", 0) <= NULL_MAX and counts.get("worse", 0) <= NULL_MAX, counts
    assert counts.get("no_skill_yet", 0) > RUNS / 2  # the card had enough data to label


def s_rows(rng: random.Random, days: int, per_day: int, *, edge: float = 0.0, jev_no: float = 0.0,
           controls_per_day: int = 40) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """S trades and R controls on the same coins' universe: random entries (``edge`` adds to every S trade)."""
    trades, controls = [], []
    for d in range(days):
        for i in range(controls_per_day):
            x, _ = random_coin(rng, 0.1)
            controls.append({"mint": f"R{d}-{i}", "source": "forward", "host": "R", "day": day(d), "crawler_ok": True,
                             "speed": rng.choice(("fast", "slow")), "first_seen_ts": 0.0,
                             "t_in": rng.uniform(3600, 6 * 3600), "x": x, "operator": f"o{rng.randrange(9999)}"})
        for i in range(per_day):
            x, _ = random_coin(rng, 0.1)
            no = rng.random() < jev_no
            trades.append({"mint": f"S{d}-{i}", "source": "forward", "host": "S", "day": day(d),
                           "speed": rng.choice(("fast", "slow")), "first_seen_ts": 0.0,
                           "t_in": rng.uniform(3600, 6 * 3600), "x": clip(x + edge),
                           "operator": f"s{rng.randrange(9999)}", "jev": "no" if no else "yes", "cocoon": "pass",
                           "radar_pre": "pass"})
    return trades, controls


def test_null_strategy_random_entries() -> None:
    def run(rng: random.Random) -> dict[str, Any]:
        trades, controls = s_rows(rng, 21, 6)
        return cards.strategy_card(trades, controls)
    counts = label_counts(run)
    assert counts.get("skilled", 0) <= NULL_MAX and counts.get("worse", 0) <= NULL_MAX, counts
    assert counts.get("no_skill_yet", 0) > RUNS / 2


def test_null_jev_random_no_at_the_same_rate() -> None:
    counts = label_counts(lambda rng: cards.jev_card(s_rows(rng, 21, 10, jev_no=0.3, controls_per_day=0)[0]))
    assert counts.get("skilled", 0) <= NULL_MAX and counts.get("worse", 0) <= NULL_MAX, counts
    assert counts.get("no_skill_yet", 0) > RUNS / 2


def drifting_positions(rng: random.Random, days: int, per_day: int, *, lead_s: float | None = None,
                       drift_per_h: float = -0.08) -> list[dict[str, Any]]:
    """Paper positions on a DOWN-DRIFTING tape (log price falls ``drift_per_h`` an hour plus noise) held 2 h.
    The Radar exits 40 % of them at a time drawn from its own delay distribution; with ``lead_s`` it instead exits
    crashing positions ``lead_s`` before a -60 % crash."""
    hold = 7200.0
    delays = [rng.uniform(0, hold) for _ in range(200)]
    out = []
    for d in range(days):
        for i in range(per_day):
            crash_at = rng.uniform(600, hold) if lead_s is not None and rng.random() < 0.3 else None
            noise: dict[float, float] = {}

            def price(t: float, noise: dict[float, float] = noise, crash_at: float | None = crash_at) -> float:
                if t not in noise:
                    noise[t] = rng.gauss(0, 0.15 * math.sqrt(t / hold))
                drop = math.log(0.4) if crash_at is not None and t >= crash_at else 0.0
                return math.exp(drift_per_h * t / 3600 + noise[t] + drop)

            mint = f"P{d}-{i}"
            tau = cards.placebo_tau(mint, 0.0, delays)
            assert tau is not None
            row = {"mint": mint, "source": "paper", "host": "S", "day": day(d), "operator": f"p{rng.randrange(9999)}",
                   "t_in": 0.0, "x": 0.0, "x_hold": clip(price(hold) - 1), "x_placebo": clip(price(tau) - 1),
                   "crash50": crash_at is not None, "t_crash": crash_at}
            if lead_s is not None and crash_at is not None:
                t_exit = max(0.0, crash_at - lead_s)
                row.update(radar_exit=True, radar_exit_ts=t_exit, x_radar=clip(price(t_exit) - 1))
            elif lead_s is None and rng.random() < 0.4:
                t_exit = delays[rng.randrange(len(delays))]
                row.update(radar_exit=True, radar_exit_ts=t_exit, x_radar=clip(price(t_exit) - 1))
            out.append(row)
    return out


def test_null_radar_random_times_on_a_down_drifting_tape() -> None:
    counts = label_counts(lambda rng: cards.radar_card(drifting_positions(rng, 21, 6)))
    assert counts.get("skilled", 0) <= NULL_MAX and counts.get("worse", 0) <= NULL_MAX, counts
    assert counts.get("no_skill_yet", 0) > RUNS / 2


def test_without_placebo_exits_a_down_drift_alone_would_look_like_skill() -> None:
    """Why DS is netted against placebo exits (A4): raw DS of random-time exits is clearly positive on the drift."""
    rng = random.Random(4)
    positions = drifting_positions(rng, 60, 6)
    raw = [p["x_radar"] - p["x_hold"] for p in positions if p.get("radar_exit")]
    net = cards.radar_card(positions)["metrics"][0]["value"]
    assert sum(raw) / len(raw) > 0.04 and abs(net) < 100 * 0.03


# --------------------------------------------------------------------------- power: planted effects are found

#: Days of forward data at which a planted effect reaches "Skill shown" in >= 80 % of runs with one block per judged
#: day (measured: the Cocoon veto, VV ~ +8 pp, crosses at ~260 days; the +8 pp entry edge at ~320; a Radar saving
#: ~ +45 pp per exit at ~120). The card MINIMUMS (7 days, 60 trades, ...) are far below this: the always-valid band
#: on [-1, 1]-bounded day blocks, not the minimum, is what makes "Skill shown" slow (docs/EXPERIENCE.md §12.2).
POWER_DAYS = {"cocoon": 300, "strategy": 360, "radar": 150}
POWER_RUNS = 25


def _power(make: Any) -> float:
    return sum(make(random.Random(1000 + run))["label"] == "skilled" for run in range(POWER_RUNS)) / POWER_RUNS


def test_power_cocoon_a_veto_removing_half_of_the_bad_coins() -> None:
    def veto(x: float, bad: bool, rng: random.Random) -> bool:
        return rng.random() < (0.5 if bad else 0.05)
    assert _power(lambda rng: cards.cocoon_card(r_rows(rng, POWER_DAYS["cocoon"], 20, veto))) >= 0.8


def test_power_strategy_a_plus_8_pp_entry_edge() -> None:
    def run(rng: random.Random) -> dict[str, Any]:
        trades, controls = s_rows(rng, POWER_DAYS["strategy"], 5, edge=0.08)
        return cards.strategy_card(trades, controls)
    assert _power(run) >= 0.8


def test_power_radar_exits_that_lead_crashes() -> None:
    assert _power(lambda rng: cards.radar_card(drifting_positions(rng, POWER_DAYS["radar"], 6, lead_s=300))) >= 0.8


# --------------------------------------------------------------------------- the α ledger


def _outbox(rows: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [{"id": i, "event": e, "payload": p, "receipt_seq": i, "receipt_ts": 1000.0 + i}
            for i, (e, p) in enumerate(rows, start=1)]


def test_alpha_v_spends_at_most_two_percent_per_member() -> None:
    assert stats.alpha_v(1) == pytest.approx(0.01) and stats.alpha_v(2) == pytest.approx(0.02 / 6)
    assert math.fsum(stats.alpha_v(v) for v in range(1, 10_000)) < 0.02
    assert stats.check_pct(0.01) == "99" and stats.check_pct(stats.alpha_v(2)) == "99.6"
    with pytest.raises(ValueError):
        stats.alpha_v(0)


def test_the_ledger_folds_receipted_rows_first_per_key() -> None:
    rows = _outbox([("member_version", {"member": "cocoon", "hash": "h1"}),
                    ("skill_claim", {"member": "cocoon", "version": 1, "metric": "VV", "alpha": 0.01}),
                    ("member_version", {"member": "cocoon", "hash": "h1"}),  # duplicate key: ignored
                    ("skill_claim", {"member": "cocoon", "version": 1, "metric": "VV", "alpha": 0.01}),
                    ("skill_claim", {"member": "cocoon", "version": 2, "metric": "VV", "alpha": 0.5}),  # no v2 yet
                    ("member_version", {"member": "cocoon", "hash": "h2"}),
                    ("skill_claim", {"member": "cocoon", "version": 2, "metric": "VV", "alpha": 0.5}),  # dup key
                    ("member_version", {"member": "radar", "hash": "r1"})])
    rows.append({"id": 99, "event": "skill_claim", "payload": {"member": "radar", "version": 1, "alpha": 0.01},
                 "receipt_seq": None, "receipt_ts": None})  # not receipted: does not count
    ledger = stats.alpha_ledger(rows)
    cocoon = ledger["cocoon"]
    assert [v["hash"] for v in cocoon["versions"]] == ["h1", "h2"] and cocoon["versions"][0]["t0"] == 1001.0
    assert cocoon["versions"][0]["claim"]["t0"] == 1002.0 and cocoon["versions"][1]["claim"] is None
    assert cocoon["spent"] == pytest.approx(0.01) and cocoon["left"] == pytest.approx(0.01)
    assert cocoon["invalid"] == 1 and cocoon["current"]["hash"] == "h2"
    assert ledger["radar"]["spent"] == 0.0 and ledger["radar"]["versions"][0]["claim"] is None
    # version 2 of the Cocoon has no valid claim yet: none of its evidence counts
    assert stats.claim_scope(cocoon) is None and stats.claim_scope(None) is None
    claimed = stats.alpha_ledger(rows[:2])["cocoon"]
    assert stats.claim_scope(claimed) == (pytest.approx(0.01), 1002.0)


def test_null_with_ten_version_changes_rarely_ever_shows_skill() -> None:
    """P(ever "Skill shown") over a member's lifetime <= 1 %: every version is checked after EVERY block with its own
    α_v from the ledger. ``e_crossed`` is a necessary condition of the band clearing 0, so counting it is an upper
    bound on the label."""
    events = []
    for v in range(1, 11):
        events += [("member_version", {"member": "strategy", "hash": f"h{v}"}),
                   ("skill_claim", {"member": "strategy", "version": v, "metric": "EE", "alpha": stats.alpha_v(v)})]
    alphas = [v["claim"]["alpha"] for v in stats.alpha_ledger(_outbox(events))["strategy"]["versions"]]
    assert len(alphas) == 10
    ever = 0
    for run in range(RUNS):
        rng = random.Random(run)
        crossed = False
        for alpha in alphas:
            logw, threshold = ev.start(), math.log(2.0 / alpha)
            for _ in range(60):
                logw = ev.step_up(logw, clip(rng.gauss(0.0, 0.25)))
                if ev.logmeanexp(logw) >= threshold:
                    crossed = True
                    break
            if crossed:
                break
        ever += crossed
    assert ever <= NULL_MAX


def test_a_skilled_label_implies_the_e_value_crossed() -> None:
    rng = random.Random(5)
    for _ in range(300):
        ys = [clip(rng.gauss(rng.uniform(-0.2, 0.4), 0.2)) for _ in range(rng.randint(2, 40))]
        lo, hi = stats.band(ys, 0.01)
        if stats.chance_label(measured=True, enough=True, lo=lo, hi=hi, stable_ok=True) == "skilled":
            assert stats.e_crossed(ys, 0.01)
        assert lo <= hi


# --------------------------------------------------------------------------- Broker, bars and self-checks


def test_broker_on_paper_is_never_measured_whatever_the_numbers() -> None:
    fills = [{"ts": 10.0 + i, "decision_ts": 0.0} for i in range(100)]
    perfect = [{"x": -0.05, "day": day(i % 20), "mint": f"F{i}", "operator": f"o{i}"} for i in range(500)]
    card = cards.broker_card(fills, shortfalls=perfect)
    assert card["label"] == "not_measured" and card["chip"] == "Not measured on paper"
    assert card["metrics"][0]["value"] == pytest.approx(59.5) and "cannot be measured on paper" in card["line"]
    live = cards.broker_card(fills, cards.CardContext(paper=False), shortfalls=perfect)
    assert live["label"] in ("meets_bar", "not_enough") and live["chip"] != "Not measured on paper"


def test_crawler_coverage_meets_or_misses_the_bar() -> None:
    def coins(seen_share: float, days: int = 40, per_day: int = 40) -> list[dict[str, Any]]:
        rng = random.Random(6)
        return [{"mint": f"C{d}-{i}", "source": "forward", "day": day(d), "eligible_ts": 0.0,
                 "seen_ts": 60.0 if rng.random() < seen_share else None} for d in range(days) for i in range(per_day)]
    assert cards.crawler_card(coins(0.3))["label"] == "below_bar"
    assert cards.crawler_card(coins(1.0, days=MIN_DAYS - 1))["label"] == "not_enough"
    # a bar near the top of the range is slow to clear: even perfect coverage needs ~95 daily blocks
    assert cards.crawler_card(coins(1.0, days=80))["label"] == "not_enough"
    assert cards.crawler_card(coins(1.0, days=120))["label"] == "meets_bar"


def test_risk_stays_collecting_and_shows_the_rug_hit_and_trades() -> None:
    trades = [{"mint": f"T{i}", "source": "paper", "day": day(i), "x": -0.9, "x_raw": -0.95, "size_usd": 20.0,
               "equity_usd": 100.0, "crash50": True, "t_crash": 10.0, "t_out": 20.0} for i in range(10)]
    card = cards.risk_card(trades, daily_limit_pct=0.2,
                           equity_days=[{"start_equity": 100.0, "end_equity": 75.0}, {"start_equity": 75.0,
                                                                                      "end_equity": 74.0}])
    assert card["label"] == "not_enough" and card["chip"] == "Collecting"
    assert card["metrics"][0]["value"] == pytest.approx(0.19) and card["metrics"][1]["value"] == pytest.approx(0.25)
    assert card["metrics"][2]["value"] == 10 and "One rug costs about 19% of the money" in card["line"]


def test_self_checks_are_never_green() -> None:
    assert cards.coach_card([], [])["label"] == "not_built"
    passing = cards.coach_card([-0.06] * 300, [True] * 80 + [False] * 20)
    assert passing["label"] == "checks_pass" and texts.chip_tone(passing["label"]) == "grey"
    assert "keeps losing, as it should" in passing["line"]
    kind_sim = cards.coach_card([0.01] * 300, [])
    assert kind_sim["label"] == "check_failed" and "not losing as it should" in kind_sim["line"]
    assert cards.receipts_card({"chain": True, "pack": None})["label"] == "checks_pass"
    failed = cards.receipts_card({"chain": False})
    assert failed["label"] == "check_failed" and texts.chip_tone("check_failed") == "red"


# --------------------------------------------------------------------------- words follow the band


def test_skill_shown_never_appears_with_a_band_crossing_the_baseline() -> None:
    labels = set()
    for seed in range(40):
        rng = random.Random(seed)
        strength = rng.choice((0.0, 0.5, 0.95))
        days = rng.choice((5, 30, 120, 320))
        rows = r_rows(rng, days, 20, lambda x, bad, r, s=strength: r.random() < (s if bad else 0.05))
        card = cards.cocoon_card(rows)
        labels.add(card["label"])
        shown = "skill shown" in (card["line"] + card["chip"]).lower()
        primary = card["metrics"][0]
        assert shown == (card["label"] == "skilled")
        assert (texts.chip_tone(card["label"]) == "green") == shown
        if shown:
            assert primary["lo"] > 0 and primary["value"] > 0
        for text in [card["line"], card["coverage"], card["chip"], *(m["text"] + m["name"] for m in card["metrics"])]:
            assert texts.lint(text) == [], text
    assert {"skilled", "no_skill_yet", "not_enough"} <= labels


# --------------------------------------------------------------------------- the playbook counts (§7.1, §9)


def test_the_playbook_registry_loads_folds_and_counts(tmp_path: Path) -> None:
    assert playbook.load_entries(tmp_path / "missing.json") == []
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert playbook.load_entries(broken) == []
    registry = tmp_path / "playbook.json"
    registry.write_text(json.dumps({"entries": [
        {"id": "G02", "status": "in_bot_contradicted"}, {"id": "G07", "status": "in_bot_unsupported"},
        {"id": "G22", "status": "fix_engineering"}, {"id": "G15", "status": "candidate"},
        {"id": "G24", "status": "made-up"}, {"status": "candidate"}]}), encoding="utf-8")
    entries = playbook.load_entries(registry)
    assert [e["id"] for e in entries] == ["G02", "G07", "G22", "G15", "G24"] and entries[-1]["status"] == "candidate"
    events = _outbox([("filter_register", {"filter_id": "f1", "rule": "G15"}),
                      ("filter_register", {"filter_id": "f2", "rule": "G24"}),
                      ("filter_register", {"filter_id": "f3", "rule": "G07"}),  # in the bot: stays in the bot
                      ("filter_verdict", {"filter_id": "f1", "rule": "G15", "verdict": "kept"}),
                      ("filter_verdict", {"filter_id": "f1", "rule": "G15", "verdict": "dropped"}),  # same key
                      ("filter_register", {"filter_id": "f9", "rule": "G99"})])  # unknown rule: ignored
    statuses = playbook.fold_statuses(entries, events)
    assert statuses == {"G02": "in_bot_contradicted", "G07": "in_bot_unsupported", "G22": "fix_engineering",
                        "G15": "validated", "G24": "testing"}
    assert playbook.counts(statuses) == {"validated": 1, "rejected": 0, "in_bot_contradicted": 1,
                                         "in_bot_unsupported": 1, "testing": 1, "false_keep_bound": "1 in 10"}
    assert texts.say("playbook", validated_n=0, rejected_n=0, contradicted_n=6, unsupported_n=5) == (
        "Rules tested and kept: 0 · tested and dropped: 0 · in the bot, contradicted by our data: 6 · in the bot, "
        "untested: 5")
    assert texts.say("kept", k_n=1) == "Rules tested and kept: 1 (at most 1 in 10 expected to be a false keep)"


def test_e_lond_levels_keep_the_family_budget() -> None:
    assert playbook.elond_alpha(1, 0) == pytest.approx(0.05)
    assert playbook.elond_alpha(2, 1) == pytest.approx(0.1 / 6 * 2)
    assert math.fsum(playbook.elond_alpha(j, 0) for j in range(1, 100_000)) < 0.1
    with pytest.raises(ValueError):
        playbook.elond_alpha(0, 0)

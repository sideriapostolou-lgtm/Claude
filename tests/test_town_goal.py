"""The town's goal (nightcrawler.towngoal, /api/page town.goal and plain.goal): the owner's goal for the team, real
money only, never a cost, never a path to any desk. The honesty rules as tests: H1 a goal never a cost; H2 only real
money moves anything; H3 never summed; H4 pretend money never powers the town; H5 no path to a desk; H6 careful words;
H7 no invented number; H9 the desk's UTC day; H10 labels only; H12 display only; H13 not events; H14 a whole day's
bill; H15 the setting never stops the bot; H16 the reserve is never progress. The states are tests/goal_states.py's."""

from __future__ import annotations

import ast
import copy
import json
import logging
import math
import random
import re
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import NOW, page_script, seed
from test_page_polymarket import desk_state, save

from nightcrawler import pagestate, polydesk, towngoal
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from tests import goal_states as GS
from tests.test_polydesk import NOW as DESK_NOW
from tests.test_polydesk import _market
from tests.test_polydesk_live import (  # noqa: F401 - the gateway fixture
    FakeExchange,
    FakeLedger,
    _live_settings,
    gw,
)

SRC = Path(pagestate.__file__).resolve().parent
AT = GS.SNAPSHOT_AT
MINUS = "−"
#: the words that may never be said of the target (a goal is not a cost), and the careless ones (H1, H6)
_COST_WORDS = re.compile(r"\b(?:costs?|bills?|rent|owes?|needs?|must|survives?|upkeep)\b|keep[a-z ]* alive", re.IGNORECASE)
_BANNED = re.compile(r"win it back|make it back|double (?:down|up)|\ball in\b|jackpot|\bluck(?:y)?\b|gambl|hurry|"
                     r"need to win|must win|push harder|bet more|deadline|skilled|genius|expert", re.IGNORECASE)
_NEGATED_ONLY = (("chase", re.compile(r"\b(?:don't|doesn't|never|not) chase\b", re.IGNORECASE)),
                 ("bigger bet", re.compile(r"\bnot bigger bets?\b", re.IGNORECASE)),
                 ("raise the", re.compile(r"\bdon't raise the\b", re.IGNORECASE)))
_CALM = ("same rule", "same size", "same limits", "don't raise", "limits don't move")


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The page the screenshot harness's server builds (tests/test_page.py's seeded two days)."""
    tmp = tmp_path_factory.mktemp("goal-base")
    settings = Settings.from_env({"DATA_DIR": str(tmp)})
    with Ledger(tmp / "nc.db", clock=FakeClock(NOW)) as ledger:
        seed(ledger)
        return pagestate.build_page_state(ledger, settings, NOW)


@pytest.fixture(scope="module")
def states(base: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: GS.apply_state(base, name, AT) for name in GS.STATES}


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=FakeClock(NOW)) as led:
        yield led


def _strings(value: Any) -> Iterator[str]:
    """Every sentence-bearing string (the bare figures target_text and bill_text are values, not sentences)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in ("target_text", "bill_text"):
                yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _sentences(text: str) -> list[str]:
    return [s for part in text.split(" · ") for s in re.split(r"(?<=[.!?])\s+", part) if s.strip()]


def _target_re(target: str) -> re.Pattern[str]:
    return re.compile(re.escape(target) + r"(?![.,]?\d)")


def _recompute(page: dict[str, Any], name: str, settings: Settings | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    live_days, pnls = GS.state_books(name, AT)
    return pagestate.town_goal_block(settings or GS.state_settings(name), page, AT, live_days=live_days, today_pnls=pnls)


def _inputs(page: dict[str, Any], name: str, **over: Any) -> dict[str, Any]:
    live_days, pnls = GS.state_books(name, AT)
    inp = pagestate.goal_inputs(GS.state_settings(name), page, AT, live_days=live_days, today_pnls=pnls)
    inp.update(over)
    return inp


def _goal(inp: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    goal = towngoal.town_goal(inp, whole=pagestate._limit)
    return goal, towngoal.goal_words(goal, inp, dollars=pagestate._dollars, signed=pagestate._signed,
                                     limit=pagestate._limit)


# --------------------------------------------------------------------------- the setting


def test_the_goal_setting_is_read_leniently_and_never_stops_the_bot(tmp_path: Path,
                                                                     caplog: pytest.LogCaptureFixture) -> None:
    """H15: a text setting, read by towngoal.parse_goal: a typo shows 100 and logs town_goal_bad, never refuses boot."""
    expect = {"$100": (100.0, True), "100": (100.0, True), "1,000": (1000.0, True), " $250.50 ": (250.5, True),
              "abc": (100.0, False), "0": (100.0, False), "-5": (100.0, False), "1e12": (100.0, False),
              "": (100.0, False), "2,000,000": (100.0, False)}
    with caplog.at_level(logging.WARNING, logger="nightcrawler.towngoal"):
        for raw, want in expect.items():
            settings = Settings.from_env({"DATA_DIR": str(tmp_path), "TOWN_GOAL_USD": raw})  # never raises
            assert settings.town_goal_usd in (raw.strip(), "100")  # (an empty variable is the default)
            assert towngoal.parse_goal(raw) == want, raw
    bad = [r.getMessage() for r in caplog.records if "town_goal_bad" in r.getMessage()]
    assert bad and all("using=100.0" in m for m in bad)
    assert Settings.from_env({"DATA_DIR": str(tmp_path)}).town_goal_usd == "100"
    row = {r["env"]: r for r in Settings.describe()}["TOWN_GOAL_USD"]
    assert row["unit"] == "text" and row["help"].startswith("DISPLAY ONLY") and "no desk reads it" in row["help"]
    assert towngoal.parse_goal(None) == (100.0, False) and towngoal.parse_goal(100) == (100.0, False)  # text only


# --------------------------------------------------------------------------- today's snapshot


def test_todays_snapshot_reads_as_designed(states: dict[str, dict[str, Any]]) -> None:
    """The live snapshot of 2026-10-10 20:28 UTC (the daily stop after 83 real bets, 78 won; cash $42.43)."""
    page = states["stopped_today"]
    g, w = page["town"]["goal"], page["plain"]["goal"]
    assert g["label"] == "The team's goal (real money only)" and g["target_usd"] == 100.0 and g["target_ok"] is True
    assert g["is_cost"] is False and g["counts"] == "real money only"
    assert (g["day"], g["day_start"], g["day_end"]) == ("2026-10-10", 1_791_590_400.0, 1_791_676_800.0)
    assert g["day_n"] == 2 and g["real_on"] is True and g["real_today_usd"] == -3.11
    assert g["parts"] == [{"id": "polymarket", "label": "Polymarket desk (real money)", "today_usd": -3.11, "settled": 83,
                           "won": 78}]
    assert g["peak_today_usd"] is not None and g["peak_today_usd"] > 0.17  # it rose over the bill before the losses
    assert g["bill_per_day_usd"] == 0.1667 and g["bill_covered_by_real"] is False and g["bill_share_real"] == 0.0
    assert g["power"] == "backup" and g["progress"] == {"lit": 0, "of": 8}
    assert [r["id"] for r in g["rungs"]] == ["zero", "bill", "one", "ten", "goal", "great", "double", "triple"]
    assert [r["name"] for r in g["rungs"]] == ["Above zero", "Covers the bill", "$1 a day", "$10 a day",
                                               "The goal: $100 a day", "Great day: $150", "Double the goal: $200",
                                               "Triple the goal: $300"]
    assert [r["usd"] for r in g["rungs"]] == [0.01, 0.1667, 1.0, 10.0, 100.0, 150.0, 200.0, 300.0]
    assert [r["lit"] for r in g["rungs"]] == [False] * 8
    assert [r["reached"] for r in g["rungs"]] == [True, True] + [False] * 6  # the embers of earlier today
    assert [r["above_goal"] for r in g["rungs"]] == [False] * 5 + [True] * 3
    assert g["tier"] == {"id": "below", "rank": -1, "name": "Below zero"}
    assert g["next"] == {"id": "zero", "name": "Above zero", "usd": 0.01, "gap_usd": 3.12} and g["beyond_usd"] is None
    assert g["floor"] == {"day_loss_usd": 3.11, "day_max_usd": 3.0, "hit": True}
    assert g["lifeline"] == {"lost_usd": 4.89, "max_usd": 10.0, "left_usd": 5.11, "segments_lit": 5}
    assert g["reserve"]["cash_usd"] == pytest.approx(42.43, abs=0.005)
    assert g["reach"] == {"win_max_per_bet_usd": 0.03, "best_case_today_usd": 2.49, "loss_min_per_bet_usd": 0.97}
    assert g["mood"] == "stand_down" and g["stand_down"] == "day"
    assert g["days"] == [{"day": "2026-10-09", "real_usd": -1.78, "settled": 8, "won": 6, "bill_covered": False,
                          "goal_met": False}]
    assert g["streaks"] == {"up": 0, "bill": 0, "goal": 0} and g["best_day"] is None
    assert g["road"] == [{"id": "lab", "done": False}, {"id": "record", "done": False}, {"id": "owner", "done": None}]
    p = g["practice"]
    assert p["label"] == "Practice (pretend money)" and p["counts_toward_goal"] is False
    assert p["solana_today_usd"] == -5.26 and p["polymarket_today_usd"] == -5.26 and p["trend_today_usd"] == pytest.approx(-0.53)
    assert p["crew_road"]["total"] == 5 and all(set(s) == {"label", "done"} for s in p["crew_road"]["steps"])
    # the words
    assert w["label"] == "The team's goal" and w["strip_label"] == "Goal $100/day" and w["target_text"] == "$100"
    assert w["strip_figure"] == f"{MINUS}$3.11 real today" and w["strip_figure_short"] == f"{MINUS}$3.11 real"
    assert w["strip"] == f"Goal $100/day · {MINUS}$3.11 real today" and w["today"] == f"{MINUS}$3.11 real money today"
    assert w["strip_label_short"] == "Goal $100"
    assert w["aria"] == ("The owner's goal: $100 a day in real money. Today: down $3.11, real money. " + w["ember_line"]
                         + " Tap for details.")
    # a stand-down names no next light (no bet can reach one before the stop lifts): the rings start again at midnight
    assert "stopped at the daily limit" in w["line"] and "Next light" not in w["line"]
    assert w["line"].endswith("Rules first: we don't chase a loss. The rings start again at midnight UTC.")
    # the embers in words: reached earlier today (the receipts' running high), not lit now
    assert w["ember_line"] == (f"Earlier today real money was up to +$0.47; it is {MINUS}$3.11 now. Amber rings: reached "
                               "earlier today, not lit now. Only what real money holds now lights a ring.")
    assert g["peak_today_usd"] == 0.47
    assert w["bill_line"] == ("The town's bill: $0.17 a day to run (hosting and the AI judge, real costs). Today the owner "
                              "pays it: the town runs on the owner's backup power.")
    assert w["plaque_line"] == "today: paid by the owner"
    assert w["power_line"] == ("The owner's backup generator is running: real money has not covered today's $0.17 bill "
                               "yet.")
    # what the stop does (no new bet; the bets already open settled past it), never "$3.11 used of $3"
    assert w["floor_line"] == ("Today's real loss stop is $3: it ended new real bets for today, and with the bets already "
                               "open settled, today's real loss is $3.11.")
    assert w["lifeline_line"] == ("Real money stops for good after $10 lost in total: $4.89 lost so far, $5.11 of room "
                                  "left.")
    assert w["reserve_line"].startswith("Real cash at Polymarket: $42.43 (the owner's deposits plus the results;")
    assert w["reach_line"] == ("Even if all 83 of today's real bets had won, they could have made at most $2.49: a win "
                               "pays at most $0.03 a bet (one contract a bet), while a loss costs the whole price, $0.97 "
                               "or more. Reaching the $100 goal takes a proven edge, not bigger bets.")
    assert w["streak_line"] == "Day 2 on real money. In a row (closed days, UTC): up 0, bill covered 0, goal met 0."
    assert w["day_lines"] == [f"Fri 9 Oct (UTC): {MINUS}$1.78, 6 of 8 bets won"] and w["best_line"] is None
    assert w["road_lines"][1] == ("2. Its real record is judged winning by the risk manager: not yet (still learning on "
                                  "the rule in use now: 0 of 30 events needed before judging).")
    assert w["postcard"] == (f"Goal $100/day (the owner's, real money only) · {MINUS}$3.11 real today · the town's bill "
                             "$0.17/day")
    assert w["result"] == {"day": "2026-10-09", "title": "Day 1 closed · Fri 9 Oct (the desk's day, UTC)",
                           "figure": f"{MINUS}$1.78 real money",
                           "line": f"Real money that day: {MINUS}$1.78, 6 of 8 bets won. Bill covered: no. Goal: not met.",
                           "streak": "In a row now: up 0, bill covered 0, goal met 0."}
    assert w["lines"]["voss"].startswith(f"Real money today: {MINUS}$3.11, 78 of 83 bets won. The daily stop ended my day,"
                                         " and I don't chase it back.")
    assert "({local_reset} your time)" in w["lines"]["voss"]
    assert w["lines"]["rook"] == ("The $3 daily stop ended new real bets for today; with the bets already open settled, "
                                  "today's loss is $3.11. $5.11 left before real money stops for good. Rules first, goal "
                                  "second.")
    assert w["lines"]["mote"] == ("Each real settlement is also sealed in the tamper-proof records (5 records in all), and "
                                  "the check found nothing edited.")
    assert w["practice_line"] == (f"Practice (pretend money) never counts toward the goal or powers the town: the Solana "
                                  f"bot today {MINUS}$5.26 (pretend), Polymarket practice today {MINUS}$5.26 (pretend), "
                                  f"the trend desk's last day {MINUS}$0.53 (pretend).")
    assert [b["who"] for b in w["programmes"]["check_in"]] == ["tower", "power", "voss", "rook", "voss", "mote"]
    assert [b["who"] for b in w["programmes"]["tour"]] == ["tower", "bill", "power", "vault", "board", "yard", "voss",
                                                           "rook", "pip", "nyx", "jet", "mote"]
    tower = w["programmes"]["tour"][0]["text"]
    assert tower == w["line"] + " " + w["ember_line"] == w["programmes"]["check_in"][0]["text"]
    assert all(b["tag"] in (towngoal.REAL_TAG, towngoal.PRETEND_TAG) for b in w["programmes"]["tour"])
    assert {b["who"]: b["tag"] for b in w["programmes"]["tour"]}["yard"] == "PRACTICE · PRETEND MONEY"
    json.dumps(page, allow_nan=False)


# --------------------------------------------------------------------------- the rungs, the embers, the mood


def test_rungs_light_by_real_cents_and_go_dark_again(states: dict[str, dict[str, Any]]) -> None:
    page = states["tiny"]

    def lit(today: float) -> list[str]:
        real = dict(page["money"]["polymarket"]["real"], today_usd=today)
        g, _ = _goal(_inputs(page, "tiny", real=real, today_pnls=None))
        return [r["id"] for r in g["rungs"] if r["lit"]]

    assert lit(0.004) == [] and lit(0.009) == ["zero"] and lit(0.01) == ["zero"]  # by the cent, as the page shows it
    assert lit(0.16) == ["zero"] and lit(0.17) == ["zero", "bill"] and lit(0.995) == ["zero", "bill"]
    assert lit(1.0) == ["zero", "bill", "one"] and lit(299.99) == ["zero", "bill", "one", "ten", "goal", "great", "double"]
    assert lit(300.0) == list(towngoal.RUNG_ORDER) and lit(-0.5) == [] and lit(0.17)[-1] == "bill"  # dark again
    g, _ = _goal(_inputs(page, "tiny", real=dict(page["money"]["polymarket"]["real"], today_usd=0.0)))
    assert g["tier"] == {"id": "even", "rank": 0, "name": "Even"} and g["next"]["id"] == "zero"
    g, w = _goal(_inputs(page, "tiny", real=dict(page["money"]["polymarket"]["real"], today_usd=420.0)))
    assert g["tier"]["id"] == "triple" and g["tier"]["rank"] == 8 and g["next"] is None and g["beyond_usd"] == 320.0
    assert "$320.00 past it" in w["line"] and "Next light" not in w["line"]
    # a target the rungs follow; a bill under a cent has no rung of its own
    g, _ = _goal(_inputs(page, "tiny", target=(150.0, True), bill=0.005))
    assert [r["name"] for r in g["rungs"]] == ["Above zero", "$1.50 a day", "$15 a day", "The goal: $150 a day",
                                               "Great day: $225", "Double the goal: $300", "Triple the goal: $450"]


def test_embers_come_from_todays_real_receipts_or_not_at_all(ledger: Ledger, settings: Settings) -> None:
    """D4: the running high of today's real settlements, in their order, only when they add up to today's figure."""
    seed(ledger)
    today = datetime.fromtimestamp(NOW, UTC).strftime("%Y-%m-%d")
    pnls = [0.03, 0.03, 0.02, 0.03, 0.03, 0.03, 0.02, -0.97, 0.02]  # up to +0.19 (over the bill), then a loss
    for i, p in enumerate(pnls):
        ledger.append_receipt("polydesk_settled", {"slug": f"s{i}", "pnl_usd": p}, ts=NOW - 3000 + i)
    ledger.append_receipt("polydesk_settled", {"slug": "old", "pnl_usd": 5.0}, ts=NOW - 86_400)  # yesterday's: not today's
    st = desk_state(real_open=0, live_today={"pnl_usd": sum(pnls), "settled": len(pnls), "won": 8})
    st["mode"] = "live"
    save(settings, st)
    page = pagestate.build_page_state(ledger, settings, NOW)
    g = page["town"]["goal"]
    assert g["real_today_usd"] == round(sum(pnls), 2) and g["peak_today_usd"] == 0.19
    assert [r["id"] for r in g["rungs"] if r["reached"]] == ["zero", "bill"] and not any(r["lit"] for r in g["rungs"])
    assert today in g["day"]
    # receipts that do not add up to the desk's own figure (one missing): no embers at all
    st["live_days"][today]["pnl_usd"] = sum(pnls) + 0.5
    st["live_pnl_total_usd"] += 0.5
    save(settings, st)
    g = pagestate.build_page_state(ledger, settings, NOW)["town"]["goal"]
    assert g["peak_today_usd"] is None and not any(r["reached"] for r in g["rungs"] if not r["lit"])


def test_mood_precedence(states: dict[str, dict[str, Any]]) -> None:
    page = states["bill"]
    caps = page["team"]["members"][[m["id"] for m in page["team"]["members"]].index("risk")]["risk_wall"]["real_caps"]

    def mood(**over: Any) -> str:
        g, _ = _goal(_inputs(page, "bill", **over))
        return str(g["mood"])

    real = page["money"]["polymarket"]["real"]
    assert mood() == "own_power" and mood(real=dict(real, today_usd=0.1)) == "climb"
    assert mood(real=dict(real, today_usd=100.0)) == "goal"
    assert mood(paused_kind="full", real=dict(real, today_usd=100.0)) == "waiting"
    assert mood(paused_kind="room") == "waiting" and mood(paused_kind="day", real=dict(real, today_usd=150.0)) == "stand_down"
    assert mood(paused_kind="risk") == "stand_down"
    assert mood(real_on=False, paused_kind="risk") == "off"
    spent = dict(caps, total_loss_usd=10.0, total_max_usd=10.0)
    assert mood(real_on=False, caps=spent) == "stopped_for_good" and mood(caps=spent) == "stopped_for_good"
    assert mood(reported=False) == "unknown" and mood(real=None) == "unknown"
    g, w = _goal(_inputs(page, "bill", real=None))
    assert g["tier"]["id"] == "unknown" and g["real_today_usd"] is None and g["power"] is None
    assert w["strip_figure"] == "real money: not known yet" and w["plaque_line"] == "today: not known yet"
    # real money not reported today: nothing is covered, whatever the book's figure (the strip says "not known yet")
    g, w = _goal(_inputs(page, "bill", reported=False))
    assert g["real_today_usd"] == 0.21 and g["mood"] == "unknown"
    assert g["bill_covered_by_real"] is None and g["bill_share_real"] is None and g["power"] is None
    assert "covered" not in w["bill_line"] and w["plaque_line"] == "today: not known yet" and w["power_line"] is None


# --------------------------------------------------------------------------- real money only (H1-H4, H14, H16)


def test_the_goal_is_a_goal_never_a_cost(ledger: Ledger, tmp_path: Path, states: dict[str, dict[str, Any]]) -> None:
    """H1: is_cost is false; the town's costs are the same whatever the goal; a sentence that holds the target is about
    the goal and never calls it a cost, a bill, an upkeep or something to survive (except "not a cost")."""
    seed(ledger)
    pages = {}
    for raw in ("1", "1000000"):
        settings = Settings.from_env({"DATA_DIR": str(tmp_path), "TOWN_GOAL_USD": raw})
        pages[raw] = pagestate.build_page_state(ledger, settings, NOW)
    for key in ("cost_per_day_usd", "cost_today_usd", "cost_since_start_usd", "line", "covered_today",
                "covered_since_start", "income_today_usd", "label"):
        assert pages["1"]["town"][key] == pages["1000000"]["town"][key], key
    for raw, page in pages.items():
        g, w = page["town"]["goal"], page["plain"]["goal"]
        assert g["is_cost"] is False and w["target_text"] in ("$1", "$1,000,000")
        assert not _target_re(w["target_text"]).search(page["town"]["line"])
    checked = 0
    for name in GS.STATES:
        for raw in ("100", "1", "1000000"):
            settings = Settings.from_env({"DATA_DIR": str(tmp_path), "TOWN_GOAL_USD": raw, **GS.STATES[name]["env"]})
            _, w = _recompute(copy.deepcopy(states[name]), name, settings)
            target = _target_re(w["target_text"])
            for text in _strings(w):
                for s in _sentences(text):
                    if not target.search(s):
                        continue
                    checked += 1
                    assert re.search(r"\bgoal\b", s, re.IGNORECASE), (raw, s)
                    assert "not a cost" in s or not _COST_WORDS.search(s), (raw, s)
    assert checked > 100


def _randomize_pretend(page: dict[str, Any], r: random.Random) -> dict[str, Any]:
    """Every pretend input at random: the Solana bot's paper money, the Polymarket paper book, the trend desk, the
    practice trades (not the real shelf) and the practice words."""
    p = copy.deepcopy(page)
    v = lambda: round(r.uniform(-5000, 5000), 2)
    p["money"]["today"] = {"usd": v(), "pct": r.uniform(-50, 50)}
    p["money"]["since_start"] = {"usd": v(), "pct": r.uniform(-50, 50)}
    paper = p["money"]["polymarket"]["paper"]
    paper.update({"today_usd": v(), "since_start_usd": v(), "open": r.randint(0, 40), "settled_today": r.randint(0, 99),
                  "won_today": r.randint(0, 99), "settled_total": r.randint(0, 999), "won_total": r.randint(0, 999)})
    if p["money"].get("trend"):
        p["money"]["trend"].update({"today_usd": v(), "since_start_usd": v(), "equity_usd": v(), "hold_since_start_usd": v()})
    t = p["trades"]
    t["closed"] = [{"coin": f"C{r.randint(0, 999)}", "opened_at": NOW - 900, "closed_at": NOW - 60, "pnl_usd": v(),
                    "pnl_pct": r.uniform(-90, 90), "result": r.choice(["won", "lost", "even"]),
                    "why": r.choice(["Stop-loss: cut the loss", "Took profit", "Sold", "Time limit reached"])}
                   for _ in range(r.randint(0, 4))]
    t["summary"].update({"won": r.randint(0, 99), "lost": r.randint(0, 99), "even": r.randint(0, 9),
                         "total": r.randint(0, 200), "order": "".join(r.choice("WLE") for _ in range(9)),
                         "result": f"up ${r.uniform(0, 99):.2f} since start"})
    p["plain"]["pretend"] = {"label": "Practice (pretend money)", "line": f"Practice (pretend money): x{r.random()}",
                             "body": f"x{r.random()}"}
    return p


def _real_only(goal: dict[str, Any], words: dict[str, Any]) -> str:
    g = {k: v for k, v in goal.items() if k != "practice"}
    w = {k: v for k, v in words.items() if k not in ("practice_line", "crew_road_line")}
    w["lines"] = {k: v for k, v in words["lines"].items() if k not in ("pip", "nyx", "jet")}
    w["programmes"] = {"check_in": words["programmes"]["check_in"],
                       "tour": [b for b in words["programmes"]["tour"] if b["who"] not in ("yard", "pip", "nyx", "jet")]}
    return json.dumps([g, w], sort_keys=True)


def test_only_real_money_moves_the_goal(states: dict[str, dict[str, Any]]) -> None:
    """H2: 200 seeds of random pretend money change nothing of the goal but its practice parts."""
    names = list(GS.STATES)
    base_cache = {name: _real_only(*_recompute(states[name], name)) for name in names}
    for seed_ in range(200):
        r = random.Random(seed_)
        name = names[seed_ % len(names)]
        page = _randomize_pretend(states[name], r)
        assert _real_only(*_recompute(page, name)) == base_cache[name], (seed_, name)


def test_real_and_pretend_are_never_summed(states: dict[str, dict[str, Any]]) -> None:
    """H3: real money today is the real book's figure to the cent; a distinctive pretend figure appears only in the
    practice line, each one marked pretend; practice never counts toward the goal."""
    for name, page in states.items():
        g = page["town"]["goal"]
        assert g["practice"]["counts_toward_goal"] is False, name
        real = page["money"]["polymarket"]["real"]
        if real is not None:
            assert g["real_today_usd"] == round(real["today_usd"], 2), name
    page = states["practice_only"]
    w = page["plain"]["goal"]
    holders = [text for text in _strings(w) if "777.77" in text]
    assert holders and all(text == w["practice_line"] or text in [b["text"] for b in w["programmes"]["tour"]]
                           for text in holders)
    for clause in re.findall(r"[+−]\$[\d,.]+[^,.]*", w["practice_line"]):
        assert clause.rstrip().endswith("(pretend)"), clause
    assert page["town"]["goal"]["real_today_usd"] is None


def test_pretend_money_never_powers_the_town(states: dict[str, dict[str, Any]]) -> None:
    """H4: practice up $777.77 and no real book: not "own" power, not covered, no gold, the tower off."""
    for name in ("practice_only", "off"):
        g = states[name]["town"]["goal"]
        assert g["power"] != "own" and g["bill_covered_by_real"] is not True, name
        assert g["bill_share_real"] in (None, 0.0) and g["tier"]["id"] in ("off", "unknown"), name
        assert not any(r["lit"] or r["reached"] for r in g["rungs"]), name
    page = copy.deepcopy(states["practice_only"])
    page["money"]["today"]["usd"] = 1000.0
    g, _ = _recompute(page, "practice_only")
    assert g["power"] == "backup" and g["bill_covered_by_real"] is None and g["real_today_usd"] is None


def test_the_bill_is_a_whole_days_bill(states: dict[str, dict[str, Any]]) -> None:
    """H14: today's real money against the whole day's bill (never the part of the day gone by)."""
    page = states["tiny"]
    bill = page["town"]["cost_per_day_usd"]
    page = copy.deepcopy(page)
    page["town"]["cost_today_usd"] = 0.0001  # the prorated cost is never used
    real = page["money"]["polymarket"]["real"]
    g, w = _goal(_inputs(page, "tiny", real=dict(real, today_usd=bill - 0.01)))
    assert g["power"] == "backup" and g["bill_covered_by_real"] is False and g["bill_per_day_usd"] == round(bill, 4)
    assert w["plaque_line"] == "today: paid by the owner"
    g, w = _goal(_inputs(page, "tiny", real=dict(real, today_usd=bill)))
    assert g["power"] == "own" and g["bill_covered_by_real"] is True and g["bill_share_real"] == 1.0
    assert w["bill_line"].endswith("Real money covered it today.") and w["plaque_line"] == "today: covered by real money"
    g, w = _goal(_inputs(page, "tiny", bill=0.0))
    assert g["power"] is None and g["bill_covered_by_real"] is None and w["bill_line"] == "The town has no hosting bill right now."
    assert "no hosting bill" in w["honest"] and "bill" not in w["postcard"]


def test_the_reserve_is_shown_never_counted(states: dict[str, dict[str, Any]]) -> None:
    """H16: the venue's cash (the owner's deposits plus results) changes only the reserve and its line."""
    for name in ("stopped_today", "off", "met"):
        page = states[name]
        g0, w0 = _recompute(page, name)
        for cash in (0.0, 25.0, 9999.99):
            p = copy.deepcopy(page)
            p["money"]["polymarket"]["real"]["cash_usd"] = cash
            g, w = _recompute(p, name)
            assert g["reserve"]["cash_usd"] == cash and pagestate._dollars(cash) in w["reserve_line"]
            assert {k: v for k, v in g.items() if k != "reserve"} == {k: v for k, v in g0.items() if k != "reserve"}
            assert {k: v for k, v in w.items() if k not in ("reserve_line", "programmes")} == \
                {k: v for k, v in w0.items() if k not in ("reserve_line", "programmes")}
            # the tour's vault beat says the reserve too: nothing else in the programmes moves
            vault = [b for b in w["programmes"]["tour"] if b["who"] == "vault"]
            assert w["reserve_line"] in vault[0]["text"]
            assert ([b for b in w["programmes"]["tour"] if b["who"] != "vault"], w["programmes"]["check_in"]) == \
                ([b for b in w0["programmes"]["tour"] if b["who"] != "vault"], w0["programmes"]["check_in"])


# --------------------------------------------------------------------------- the days and the day


def _book(**days: tuple[float, int, int]) -> dict[str, dict[str, Any]]:
    return {day: {"pnl_usd": p, "settled": s, "won": w} for day, (p, s, w) in days.items()}


def test_days_streaks_and_best_day_come_from_the_desks_own_day_book(states: dict[str, dict[str, Any]]) -> None:
    page = states["bill"]
    real = page["money"]["polymarket"]["real"]
    book = _book(**{"2026-10-10": (0.21, 8, 8), "2026-10-09": (120.0, 40, 40), "2026-10-08": (0.5, 3, 3),
                    "2026-10-06": (2.0, 5, 5), "2026-10-05": (-1.0, 2, 1)})
    since = sum(d["pnl_usd"] for d in book.values())
    g, w = _goal(_inputs(page, "bill", live_days=book, real=dict(real, since_start_usd=since)))
    assert [d["day"] for d in g["days"]] == ["2026-10-09", "2026-10-08", "2026-10-06", "2026-10-05"]  # closed, newest first
    assert g["days"][0] == {"day": "2026-10-09", "real_usd": 120.0, "settled": 40, "won": 40, "bill_covered": True,
                            "goal_met": True}
    # a calendar day without a real settlement (the 7th) breaks every streak; the goal's streak ends on the 8th
    assert g["streaks"] == {"up": 2, "bill": 2, "goal": 1} and g["day_n"] == 6
    assert g["best_day"] == {"day": "2026-10-09", "real_usd": 120.0}
    assert w["best_line"] == "Best real day so far: +$120.00 on Fri 9 Oct (UTC)."
    assert w["day_lines"][1] == "Thu 8 Oct (UTC): +$0.50, 3 of 3 bets won"
    assert w["result"]["line"] == "Real money that day: +$120.00, 40 of 40 bets won. Bill covered: yes. Goal: met."
    # the book must agree with the money card to the cent, or there is no history at all
    g, w = _goal(_inputs(page, "bill", live_days=book, real=dict(real, since_start_usd=since + 0.02)))
    assert g["days"] is None and g["streaks"] is None and g["best_day"] is None and w["result"] is None
    assert w["streak_line"] == "Day 6 on real money. History not available."
    g, _ = _goal(_inputs(page, "bill", live_days=book, real=dict(real, since_start_usd=since, today_usd=0.5)))
    assert g["days"] is None  # today's row disagrees with today's figure
    # a best day only when one was up
    down = _book(**{"2026-10-10": (0.21, 8, 8), "2026-10-09": (-0.4, 2, 1)})
    g, w = _goal(_inputs(page, "bill", live_days=down, real=dict(real, since_start_usd=-0.19)))
    assert g["best_day"] is None and w["best_line"] is None and g["streaks"] == {"up": 0, "bill": 0, "goal": 0}
    # yesterday on real money without a settlement: the closing card says so
    gap = _book(**{"2026-10-10": (0.21, 8, 8), "2026-10-08": (0.4, 2, 2)})
    _, w = _goal(_inputs(page, "bill", live_days=gap, real=dict(real, since_start_usd=0.61)))
    assert w["result"]["line"] == "No real bet finished that day." and w["result"]["day"] == "2026-10-09"
    _, w = _goal(_inputs(page, "bill", live_days=None))
    assert w["result"] is None


@pytest.mark.parametrize("clock", ["2026-10-10T23:59:59", "2026-10-11T00:00:01"])
def test_the_day_is_the_desks_utc_day(states: dict[str, dict[str, Any]], clock: str) -> None:
    """H9: the goal's day is the desk's own (its daily stop's), reset at the next UTC midnight."""
    now = datetime.fromisoformat(clock).replace(tzinfo=UTC).timestamp()
    page = states["tiny"]
    inp = pagestate.goal_inputs(GS.state_settings("tiny"), page, now, live_days=None, today_pnls=None)
    g, w = _goal(inp)
    assert g["day"] == polydesk._day(now) and g["day_start"] == now - now % 86_400
    assert g["day_end"] == g["day_start"] + 86_400 and datetime.fromtimestamp(g["day_end"], UTC).hour == 0
    assert all("(the desk's day, UTC)" in (w["result"] or {}).get("title", "(the desk's day, UTC)") for _ in [0])


def test_the_reach_is_an_upper_bound_from_the_desks_settings(states: dict[str, dict[str, Any]]) -> None:
    for name in ("stopped_today", "tiny", "bill", "met", "double"):
        page, s = states[name], GS.state_settings(name)
        g, w = page["town"]["goal"], page["plain"]["goal"]
        per = round(s.polydesk_live_contracts * (1 - s.polydesk_theta), 2)
        assert g["reach"]["win_max_per_bet_usd"] == per
        assert g["reach"]["best_case_today_usd"] == round(g["parts"][0]["settled"] * per, 2)
        assert g["real_today_usd"] <= g["reach"]["best_case_today_usd"] + 1e-9, name  # never more than at most
        assert "at most" in w["reach_line"] and "not bigger bets" in w["reach_line"]
    page = states["met"]
    assert "(100 contracts a bet)" in page["plain"]["goal"]["reach_line"]
    assert page["plain"]["goal"]["lines"]["rook"].startswith("The goal is $100 a day. My limits don't move for it: 100 "
                                                             "contracts a bet, $1,000 in bets at once")
    for name in ("off", "practice_only"):
        assert states[name]["town"]["goal"]["reach"] is None and states[name]["plain"]["goal"]["reach_line"] is None


def test_the_reach_says_what_the_bets_did_and_what_a_loss_costs(states: dict[str, dict[str, Any]]) -> None:
    """The reach never says "even if they had won" when they all did; it names the loss side (a loss costs the whole
    price, the rule's price or more: why 78 of 83 won can be a loss); at the goal it never says "reaching the goal"."""
    want = {
        "stopped_today": "Even if all 83 of today's real bets had won, they could have made at most $2.49:",
        "losing": "Even if today's one real bet had won, it could have made at most $0.03:",
        "tiny": "Today's one real bet won: $0.03 is the most it could make, since",
        "bill": "All 8 of today's real bets won: $0.24 is the most they could make, since",
        "met": "All 36 of today's real bets won: $108.00 is the most they could make, since",
        "double": "All 75 of today's real bets won: $225.00 is the most they could make, since",
    }
    for name, start in want.items():
        g, w = states[name]["town"]["goal"], states[name]["plain"]["goal"]
        line = w["reach_line"]
        assert line.startswith(start), (name, line)
        per = "100 contracts a bet" if name in ("met", "double") else "one contract a bet"
        loss = pagestate._dollars(g["reach"]["loss_min_per_bet_usd"])
        assert f"a win pays at most {pagestate._dollars(g['reach']['win_max_per_bet_usd'])} a bet ({per}), while a loss " \
               f"costs the whole price, {loss} or more." in line, (name, line)
        settled, won = g["parts"][0]["settled"], g["parts"][0]["won"]
        assert ("Even if" in line) is (won < settled), name
        if g["mood"] == "goal":
            assert line.endswith(" More than this takes a proven edge, not bigger bets.") and "Reaching" not in line
        else:
            assert line.endswith(" Reaching the $100 goal takes a proven edge, not bigger bets."), (name, line)
    s = GS.state_settings("stopped_today")
    assert states["stopped_today"]["town"]["goal"]["reach"]["loss_min_per_bet_usd"] == round(
        s.polydesk_live_contracts * s.polydesk_theta, 2)  # (the rule buys at its price or above)


def test_the_road_never_pastes_the_risk_managers_statistics(states: dict[str, dict[str, Any]]) -> None:
    """Road step 2 says the risk manager's count on the rule in use now, never its statistics clause."""
    page = states["stopped_today"]
    cases = {
        "losing": ("31 events (40 settled), 9 lost, −$4.20 in all; even at best −$0.003 an event (95 % sure)",
                   "not yet (losing on the rule in use now: 31 events (40 settled), 9 lost, −$4.20 in all)."),
        "unclear": ("44 events (51 settled), 3 lost, +$0.12 in all; at worst −$0.004 an event (95 % sure)",
                    "not yet (not proven yet on the rule in use now: 44 events (51 settled), 3 lost, +$0.12 in all)."),
        "winning": ("120 events (130 settled), 4 lost, +$2.10 in all; at worst $0.003 an event (99 % sure)", "done."),
    }
    for verdict, (reason, tail) in cases.items():
        _, w = _goal(_inputs(page, "stopped_today", guard_real={"verdict": verdict, "reason": reason},
                             **({"rule_lab_passed": True} if verdict == "winning" else {})))
        line = w["road_lines"][1]
        assert line == "2. Its real record is judged winning by the risk manager: " + tail, line
        for stat in ("sure", "at worst", "even at best", ";"):
            assert stat not in line, (verdict, stat)


def test_the_power_line_says_who_keeps_the_lights_on(states: dict[str, dict[str, Any]]) -> None:
    """The owner's backup generator while real money has not covered the bill; open stalls and gold lights once it
    has; nothing when the bill is not known or there is none. Pretend money never turns it off."""
    for name in ("stopped_today", "tiny", "losing", "off", "practice_only"):
        assert states[name]["plain"]["goal"]["power_line"] == ("The owner's backup generator is running: real money "
                                                               "has not covered today's $0.17 bill yet."), name
    for name in ("bill", "met", "double"):
        assert states[name]["plain"]["goal"]["power_line"] == ("Real money covered today's $0.17 bill: the generator "
                                                               "is off, the lights are gold and the stalls are open."), name
        assert [b["who"] for b in states[name]["plain"]["goal"]["programmes"]["tour"]][2] == "promenade", name
    page = states["tiny"]
    _, w = _goal(_inputs(page, "tiny", bill=0.0))
    assert w["power_line"] is None and "power" not in [b["who"] for b in w["programmes"]["tour"]]
    p = copy.deepcopy(states["practice_only"])
    p["money"]["today"]["usd"] = 99999.0
    _, w = _recompute(p, "practice_only")
    assert w["power_line"].startswith("The owner's backup generator is running")


def test_the_day_stop_says_what_it_does(states: dict[str, dict[str, Any]]) -> None:
    """The daily stop ends new real bets; a loss past it is the bets already open settling, said so; under it, the
    plain used-of line."""
    page = states["stopped_today"]
    caps = next(m for m in page["team"]["members"] if m["id"] == "risk")["risk_wall"]["real_caps"]
    _, w = _goal(_inputs(page, "stopped_today", caps=dict(caps, day_loss_usd=3.0)))
    assert w["floor_line"] == "Today's real loss stop is $3: it ended new real bets for today, at $3.00 lost."
    assert w["lines"]["rook"].startswith("The $3 daily stop ended new real bets for today, at $3.00 lost. ")
    _, w = _goal(_inputs(states["losing"], "losing"))
    assert w["floor_line"] == "Today's real loss stop: $0.97 used of $3."
    for name in GS.STATES:  # (never "used of" past the limit, never "the limit is" under a loss over it)
        w = states[name]["plain"]["goal"]
        assert "(the limit is" not in json.dumps(w), name


def test_the_road_shows_labels_only(states: dict[str, dict[str, Any]]) -> None:
    """H10: the crew's road is the checklist's labels and ticks, never a reason, an address, KEYS_ROTATED_ON, Railway or
    a token, and never its security steps (the keys replaced, the dashboard locked: the world is the page the owner
    shows friends); the count of steps done still counts them, and the line says they are not listed."""
    from nightcrawler.readiness import CHECK_LABELS

    page = copy.deepcopy(states["stopped_today"])
    page["ready"]["items"][2]["reason"] = "Wallet AfRc…5c8W is empty — send it SOL first."
    page["ready"]["items"][3]["reason"] = "Replace the keys you pasted in chat, then set KEYS_ROTATED_ON in Railway."
    secret = "dash-token-correct-horse-battery-staple"
    g, w = _recompute(page, "stopped_today")
    road = g["practice"]["crew_road"]
    counted = page["ready"]["items"][:5]
    assert [s["label"] for s in road["steps"]] == [i["label"] for i in counted if i["id"] not in ("keys", "locked")]
    assert road["total"] == 5 and road["done"] == page["ready"]["done"]  # (the count still counts every step)
    text = json.dumps([g, w], ensure_ascii=False)
    for bad in ("AfRc", "KEYS_ROTATED_ON", "Railway", secret, "send it SOL", "reason", CHECK_LABELS["keys"],
                CHECK_LABELS["locked"], "Keys shared", "Dashboard locked", "password"):
        assert bad not in text, bad
    for name in GS.STATES:  # (every state's goal, both blocks)
        both = json.dumps([states[name]["town"]["goal"], states[name]["plain"]["goal"]], ensure_ascii=False)
        assert CHECK_LABELS["keys"] not in both and CHECK_LABELS["locked"] not in both, name
    assert w["crew_road_line"] == (f"Road to real money for the Solana bot: {road['done']} of 5 steps done (the "
                                   "security steps are not listed here).")
    # the security steps done: still unlisted, still counted
    for item in page["ready"]["items"]:
        if item["id"] in ("keys", "locked"):
            item["done"] = True
    page["ready"]["done"] = 2
    g, w = _recompute(page, "stopped_today")
    assert g["practice"]["crew_road"]["done"] == 2 and len(g["practice"]["crew_road"]["steps"]) == 3
    assert "Keys shared" not in json.dumps([g, w], ensure_ascii=False)


# --------------------------------------------------------------------------- careful words, true numbers


def test_every_goal_sentence_is_careful(tmp_path: Path, states: dict[str, dict[str, Any]]) -> None:
    """H6: no gambler's words; "chase", "bigger bets" and "raise the stakes" only negated; the desks' own lines in the
    climb, on own power and at the goal keep the same rule and size; a stand-down puts the rules first; a sentence with
    a count of bets won carries a dollar figure."""
    pages = dict(states)
    page = states["tiny"]
    real = page["money"]["polymarket"]["real"]
    for mood_name, over in (("climb0", {"real": dict(real, settled_today=0, won_today=0, today_usd=0.0)}),
                            ("risk", {"paused_kind": "risk", "paused": "Paused by the risk manager since 07:40 UTC."}),
                            ("waiting", {"paused_kind": "full", "paused": "Waiting: $9.70 is already in open bets."}),
                            ("own", {"real": dict(real, today_usd=0.5)})):
        g, w = _goal(_inputs(page, "tiny", **over))
        pages[mood_name] = {"town": {"goal": g}, "plain": {"goal": w}}
    for name, p in pages.items():
        g, w = p["town"]["goal"], p["plain"]["goal"]
        for text in _strings(w):
            for s in _sentences(text):
                assert not _BANNED.search(s), (name, s)
                for word, ok in _NEGATED_ONLY:
                    if word in s.lower():
                        assert ok.search(s), (name, s)
                if re.search(r"\b\d+ (?:of \d+ )?(?:finished )?(?:bets? )?won\b", s):
                    assert "$" in s, (name, s)
        for who in ("voss", "rook"):
            line = w["lines"][who]
            if g["mood"] in ("climb", "own_power", "goal") and line:
                assert any(c in line.lower() for c in _CALM), (name, who, line)
            if g["mood"] == "stand_down" and line:
                assert "don't chase" in line or "Rules first" in line, (name, who, line)
        if g["mood"] == "stand_down":
            assert "don't chase" in w["line"] or "Rules first" in w["line"]


def _figures(text: str) -> list[str]:
    return re.findall(r"[+−]?\$\d[\d,]*(?:\.\d+)?", text)


def _formats(value: float) -> set[str]:
    return {pagestate._dollars(value), pagestate._signed(value), pagestate._limit(value), f"${abs(value):,.2f}"}


def _numbers(value: Any) -> Iterator[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)) and math.isfinite(value):
        yield float(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, list):
        for v in value:
            yield from _numbers(v)


def test_no_number_is_invented_and_missing_says_not_known_yet(states: dict[str, dict[str, Any]]) -> None:
    """H7: every dollar figure in plain.goal is a page figure or one town.goal derived from them, formatted the page's
    way; a figure that is not known says so and is never $0.00."""
    for name, page in states.items():
        g, w = page["town"]["goal"], page["plain"]["goal"]
        caps = next(m for m in page["team"]["members"] if m["id"] == "risk")["risk_wall"]["real_caps"]
        s = GS.state_settings(name)
        allowed: set[str] = set()
        page_numbers = _numbers({k: v for k, v in page.items() if k != "plain"})
        for v in [*_numbers(g), *page_numbers, *_numbers(caps or {}),
                  s.polydesk_live_max_open_usd, s.polydesk_live_daily_loss_usd, s.polydesk_live_total_loss_usd,
                  page["town"]["cost_per_day_usd"]]:
            allowed |= {f.lstrip("+−") for f in _formats(v)}
        quoted = " ".join([page["money"]["polymarket"]["guard"]["real"]["reason"] if page["money"]["polymarket"]["guard"]["real"]
                           else ""])
        for text in _strings(w):
            if text in quoted:
                continue
            for fig in _figures(text.replace(quoted, "")):
                assert fig.lstrip("+−") in allowed, (name, fig, text)
    # not known: words, never a zero
    page = states["tiny"]
    g, w = _goal(_inputs(page, "tiny", real=None, caps=None))  # (no real book: no caps either)
    assert w["strip_figure"] == "real money: not known yet" and w["today"] is None
    assert "not known yet" in w["line"] and "$0.00" not in " ".join(_strings(w)).replace("so far $0.00", "")
    g, w = _goal(_inputs(page, "tiny", reported=False))
    assert w["strip_figure"] == "real money: not known yet" and g["tier"]["id"] == "unknown"


# --------------------------------------------------------------------------- no path to any desk (H5), display only (H12)


def test_the_goal_reaches_no_desk(ledger: Ledger, tmp_path: Path) -> None:
    """H5: towngoal imports the standard library only; only config, pagestate and towngoal name the goal; the page is
    the same at any goal but for the goal's own two blocks."""
    tree = ast.parse((SRC / "towngoal.py").read_text(encoding="utf-8"))
    imported = {(n.module or "") if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])}
    stdlib = {"__future__", "logging", "math", "re", "collections.abc", "datetime", "typing"}
    assert imported and imported <= stdlib, imported
    named = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
                   if re.search(r"town_goal|towngoal|TOWN_GOAL", p.read_text(encoding="utf-8")))
    assert named == ["config.py", "pagestate.py", "towngoal.py"], named
    for desk in ("polydesk.py", "deskguard.py", "risk.py", "engine.py", "strategy.py", "trenddesk.py", "cocoon.py",
                 "radar.py", "crawler.py", "judge.py", "polymarket_us.py", "withdraw.py", "botwallet.py"):
        assert desk not in named
    seed(ledger)
    pages = []
    for raw in ("1", "1000000"):
        settings = Settings.from_env({"DATA_DIR": str(tmp_path), "TOWN_GOAL_USD": raw})
        page = pagestate.build_page_state(ledger, settings, NOW)
        assert page["town"].pop("goal") is not None and page["plain"].pop("goal") is not None
        pages.append(json.dumps(page, sort_keys=True))
    assert pages[0] == pages[1]


def test_a_live_desk_round_is_the_same_whatever_the_goal(gw: Any, tmp_path: Path) -> None:  # noqa: F811
    """H5 (d): one live round on the fake venue sends the same orders and writes the same receipts and state."""
    gw.markets = [_market("w1", "climate", 1800), _market("n1", "crypto", 1800)]
    gw.events = []
    gw.quotes = {"w1": (0.96, 0.975), "n1": (0.50, 0.52)}
    runs = []
    for raw in ("1", "1000000"):
        ledger, ex = FakeLedger(), FakeExchange(cash=25.0)
        desk = polydesk.PolyDesk(_live_settings(tmp_path / raw, TOWN_GOAL_USD=raw), ledger=ledger, client_factory=ex)
        desk.poll(DESK_NOW)
        runs.append(json.dumps([ex.orders, ledger.receipts, desk.state], sort_keys=True, default=str))
    assert runs[0] == runs[1] and '"w1"' in runs[0]


def test_the_goal_writes_nothing(ledger: Ledger, settings: Settings, states: dict[str, dict[str, Any]]) -> None:
    """H12: the goal's functions are pure; building a page leaves the receipts, the data dir and the desk's file as
    they were."""
    page = states["stopped_today"]
    inp = _inputs(page, "stopped_today")
    before = copy.deepcopy(inp)
    a, b = _goal(inp), _goal(inp)
    assert a == b and inp == before
    seed(ledger)
    st = desk_state(real_open=0, live_today={"pnl_usd": -0.97, "settled": 1, "won": 0})
    st["mode"] = "live"
    save(settings, st)
    path = polydesk.state_path(settings)
    data = settings.data_dir
    stamp = {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in data.rglob("*") if p.is_file() and "nc.db" not in p.name}
    count, text = len(ledger.receipts(after_seq=0, limit=100_000)), path.read_bytes()
    for _ in range(2):
        pagestate.build_page_state(ledger, settings, NOW)
    assert len(ledger.receipts(after_seq=0, limit=100_000)) == count and path.read_bytes() == text
    assert {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in data.rglob("*") if p.is_file()
            and "nc.db" not in p.name} == stamp


def test_goal_words_are_not_events(states: dict[str, dict[str, Any]]) -> None:
    """H13: the goal's words are never in the ticker, the replays, the bubbles or "right now"."""
    for page in states.values():
        plain = page["plain"]
        goal_text = set(_strings(plain["goal"]))
        events = [*(i["text"] for i in plain["ticker"]), *(i["what"] for i in plain["finished"]),
                  *(s["text"] for s in plain["said"].values()), *plain["now"]]
        assert not goal_text & set(events)
        assert not any("goal" in e.lower() and "$100" in e for e in events)


def test_a_goal_failure_leaves_the_page_whole(ledger: Ledger, settings: Settings, monkeypatch: pytest.MonkeyPatch,
                                              caplog: pytest.LogCaptureFixture) -> None:
    seed(ledger)
    good = pagestate.build_page_state(ledger, settings, NOW)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(towngoal, "town_goal", broken)
    with caplog.at_level(logging.WARNING):
        page = pagestate.build_page_state(ledger, settings, NOW)
    assert page["town"]["goal"] is None and page["plain"]["goal"] is None
    assert any("town_goal_failed error=RuntimeError" in r.getMessage() for r in caplog.records)
    for key in ("money", "team", "trades", "ready", "receipts"):
        assert page[key] == good[key], key
    assert {k: v for k, v in page["town"].items() if k != "goal"} == {k: v for k, v in good["town"].items() if k != "goal"}


# --------------------------------------------------------------------------- the 2D page


_DOM = r"""
const nodes = {};
function mk(tag) { return { tag: tag, className: "", kids: [], textContent: "", style: {}, append: function (k) { this.kids.push(k); },
  replaceChildren: function () { this.kids = Array.prototype.slice.call(arguments); } }; }
const document = { createElement: mk, getElementById: function (id) { return nodes[id] || (nodes[id] = mk("div")); } };
function text(n) { return typeof n === "string" ? n : n ? (n.textContent || "") + n.kids.map(text).join(" ") : ""; }
const MINUS = "−";
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_2d_town_card_never_says_covered_for_pretend(settings: Settings, states: dict[str, dict[str, Any]],
                                                          tmp_path: Path) -> None:
    """H4 on the 2D page: the Solana bar's "covered" only while the town's label is real money; the real Polymarket line
    says it from the goal's real figure; the help says practice never counts."""
    script = page_script(settings)
    parts = []
    for name in ("const \\$ =", "function el\\(", "function put\\(", "const isNum =", "const sign =", "const tone =",
                 "function usd\\(", "function track\\(", "function renderTown\\(", "function renderGoal\\("):
        start = re.search(r"\n  " + name, script)
        assert start is not None, name
        end = re.search(r"\n  (?:function |const |let |// -)", script[start.end():])
        parts.append(script[start.start():start.end() + (end.start() if end else 0)])
    run = []
    for state in ("stopped_today", "bill", "practice_only"):
        page = copy.deepcopy(states[state])
        page["town"]["covered_today"] = True  # the trap: the pretend Solana bar "covered" by pretend money
        page["town"]["covered_since_start"] = True
        run.append(page)
    js = _DOM + "\n".join(parts) + f"""
let last = null; const out = [];
{json.dumps(run)}.forEach(function (s) {{ last = s; renderTown(s.town); renderGoal(s.plain.goal);
  out.push({{ bars: text(nodes["town-bars"]), desks: text(nodes["town-desks"]), goal: text(nodes["town-goal"]) }}); }});
const real = JSON.parse(JSON.stringify({json.dumps(run[1])})); real.town.label = "Real money"; last = real; renderTown(real.town);
out.push({{ bars: text(nodes["town-bars"]) }});
console.log(JSON.stringify(out));
"""
    (tmp_path / "t.js").write_text(js, encoding="utf-8")
    res = subprocess.run(["node", str(tmp_path / "t.js")], capture_output=True, text=True, timeout=60, check=False)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    for shot in out[:3]:
        assert "covered" not in shot["bars"], shot["bars"]  # pretend money covers nothing
    assert "not covered by real money today" in out[0]["desks"] and "covered by real money today" in out[1]["desks"]
    assert "not covered" not in out[1]["desks"] and "covered" not in out[2]["desks"]
    assert "The owner's goal for the team: $100 a day in real money." in out[0]["goal"] and "not a cost" in out[0]["goal"]
    assert "covered" in out[3]["bars"]  # a Solana bar of real money may say it
    html = pagestate.__name__ and __import__("nightcrawler.page", fromlist=["render_page_html"]).render_page_html(settings)
    assert "To keep the town alive" not in html and "Practice money never counts." in html and 'id="town-goal"' in html

"""The screen in plain words (``/api/page.plain``, nightcrawler.pagestate.plain_words) and the main page's "In plain
words" card (the 3D world's bar and guide: tests/test_world3d.py). Fixed templates filled with the data's own numbers
only; "real money" only where the data says live (and still said while a real bet is open after real betting
stopped); pretend money always says "pretend"; a gain only as "up $X since start (real money)"; the lab's verdict
beside every real-money panel, worded for whether the rule bets real money now; no figure of one kind of money ever
added to another; the badge and the title never say "paper" while real money is on; text-only insertion and the CSP
hashes in step."""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import re
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import (  # noqa: F401 - shared fixture
    JARGON,
    MEMBER_IDS,
    NOW,
    live_settings,
    no_learning_module,
    page_script,
    seed,
)
from test_page_deskguard import SINCE, paused_state
from test_page_polymarket import YESTERDAY, desk_state, position, save
from test_world3d import _js_body, _node

from nightcrawler import polydesk, trenddesk
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.ledger import Ledger
from nightcrawler.office3d import CAST3D
from nightcrawler.page import MEMBERS, PAGE_CSP, render_page_html
from nightcrawler.pagestate import (
    GLOSSARY,
    PLAIN_ABOUT,
    PLAIN_HEADLINE_MAX,
    PLAIN_JOBS,
    PLAIN_MEMBER_JOBS,
    PRETEND_LABEL,
    REAL_LABEL,
    RESEARCH_LINE,
    VERDICT_NO_EDGE,
    VERDICT_NO_EDGE_OFF,
    build_page_state,
    plain_event,
)

KEY = {"POLYMARKET_US_KEY_ID": "0000-key", "POLYMARKET_US_SECRET_KEY": "c2VjcmV0"}
LIVE_DESK = {"POLYDESK_MODE": "live", "POLYDESK_LIVE_CONFIRM": LIVE_CONFIRM_PHRASE, **KEY}
LIMITS = ("Hard limits: one contract (under $1) per bet, at most $10 in bets at once, stops for the day after losing "
          "$3, stops for good after losing $10.")
HOW_LIVE = ("How it bets: it buys YES at 97¢ or more on questions that look almost decided. A right answer pays $1, so "
            "a win makes at most 3¢ a contract and a loss costs the whole price.")
#: Why real money skips sports, from lab 4's history verdicts (polydesk.SPORT_HISTORY) only.
SPORTS_LINE = ("No real money on sports: in history (3,070 past bets like these, 104 lost: 3.4% against the 2.9% the "
               "prices said) no sport proved it pays. Tennis and esports favourites lost more often than their prices "
               "said; table tennis, e-soccer, ice hockey and boxing/MMA have no history, American football too little; "
               "soccer, baseball, basketball and cricket are unproven. Practice bets keep watching them.")
ON = "Real money is on only for Voss's small Polymarket bets; the rest is pretend money."
OFF = "No real money is being bet right now: everything is practice with pretend money."
#: The desk on paper with one real contract still open at the venue (desk_state()).
STILL_OPEN = "Real money is off for new bets, but $0.97 is still in 1 open bet; the rest is pretend."


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def owner_state(**kw: Any) -> dict[str, Any]:
    """The owner's desk on 2026-10-10: real money on, $20.38 cash at the venue, one real contract open ($0.95), and a
    real record of 8 finished bets, 6 won, -$1.78; the paper book as in test_page_polymarket."""
    kw.setdefault("balance", {"cash": 20.38, "buying_power": 20.38, "at": NOW - 60})
    kw.setdefault("venue", {"positions": 1, "contracts": 1.0, "cost_usd": 0.95, "value_usd": 0.96, "at": NOW - 60})
    st = desk_state(**kw)
    st["mode"] = "live"
    st["positions"] = {k: v for k, v in st["positions"].items() if not v["live"]}
    st["positions"]["real0"] = position("real0", live=True, cost_usd=0.95)
    st["live_days"] = {YESTERDAY: {"pnl_usd": -1.78, "settled": 8, "won": 6}, **{
        day: rec for day, rec in st["live_days"].items() if day != YESTERDAY}}
    st["live_pnl_total_usd"] = sum(float(d["pnl_usd"]) for d in st["live_days"].values())
    st["events"] = [
        {"ts": NOW - 30, "text": "REAL buy: Will it rain in Athens today? · 1 contract at 0.950 ($0.95, weather)",
         "tone": "good"},
        {"ts": NOW - 400, "text": "Settled: Will x happen? · lost -20.03 $ (paper)", "tone": "bad"},
    ]
    return st


def halted_state() -> dict[str, Any]:
    """The $10 total-loss stop fired: the desk switched itself back to paper for good, one real bet still open."""
    st = owner_state()
    st["mode"], st["live_halted"] = "paper", True
    st["live_days"] = {YESTERDAY: {"pnl_usd": -10.20, "settled": 14, "won": 4}}
    st["live_pnl_total_usd"] = -10.20
    st["live_status"] = ("Total loss cap reached (-10.20 $): the desk switched itself back to paper for good; only the "
                         "owner can switch it live again.")
    return st


def plain(ledger: Ledger, settings: Settings) -> dict[str, Any]:
    result: dict[str, Any] = build_page_state(ledger, settings, NOW)["plain"]
    json.dumps(result, allow_nan=False)
    return result


def texts(block: Any) -> list[str]:
    """Every string in a block (the sentences a viewer reads)."""
    if isinstance(block, str):
        return [block]
    if isinstance(block, dict):
        return [t for v in block.values() for t in texts(v)]
    if isinstance(block, list):
        return [t for v in block for t in texts(v)]
    return []


# --------------------------------------------------------------------------- the block: real money on, with a bet open


def test_real_money_on_with_a_position_in_plain_words(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # the Solana bot: paper, down $5.50 since start
    save(settings, owner_state())
    p = plain(ledger, settings)
    assert p["about"] == PLAIN_ABOUT == ("Nightcrawler is a bot: a computer program that finds trades and bets and "
                                         "places them by itself, day and night.")
    assert p["headline"] == ON and len(p["headline"]) <= PLAIN_HEADLINE_MAX == 90  # two lines at most on a phone
    real = p["real"]
    assert real == {
        "label": REAL_LABEL, "on": True, "reported": True, "paused": None, "paused_kind": None,
        "at_risk_usd": pytest.approx(0.95), "open_bets": 1, "cash_usd": pytest.approx(20.38),
        "result": "down $1.78 since start",  # winning 6 of 8 and still down: the box says the result, big
        "line": "Real money: $20.38 cash at Polymarket and $0.95 in 1 open bet; down $1.78 since start, 6 of 8 "
                "finished bets won.",
        "how": HOW_LIVE, "limits": LIMITS, "verdict": VERDICT_NO_EDGE, "research": RESEARCH_LINE,
        "sports_line": SPORTS_LINE, "skips_line": "Nothing skipped yet today."}
    assert real["verdict"] == ("This rule did not pass our tests for a real edge (proof that it wins over many bets), "
                               "so it trades only tiny real amounts with hard limits.")
    assert RESEARCH_LINE == "No strategy tested so far has passed our lab's test for a real edge."
    assert p["pretend"]["label"] == PRETEND_LABEL == "Practice (pretend money)"
    # each practice book since start, like the others (today's change beside it); the body without its label
    assert p["pretend"]["line"].startswith("Practice (pretend money): the Solana bot is down $5.50 since start; "
                                           "Polymarket practice bets are down $1,331.35 since start (−$1,345.53 "
                                           "today); the trend desk ")
    assert p["pretend"]["body"] == p["pretend"]["line"].replace("Practice (pretend money): the", "The")
    # what just happened: the freshest events, the desk's real buy first, in plain words with its age
    assert p["now"][0] == "Voss: real-money bet: $0.95 on YES · Will it rain in Athens today? · just now"
    assert len(p["now"]) == 3 and all(re.match(r"^(Pip|Nyx|Rook|Jet|Mote|Voss): ", line) for line in p["now"])
    assert not any(line.startswith("Mote: sealed record") for line in p["now"])  # the receipts' log is not news
    voss = next(t for t in p["team"] if t["id"] == "voss")
    assert voss["latest"] == "real-money bet: $0.95 on YES · Will it rain in Athens today?"
    assert voss["latest_ts"] == NOW - 30 and voss["latest_ago"] == "just now"
    assert p["said"]["predict"] == {"ts": NOW - 30, "text": voss["latest"]}  # the world's bubble for that event


def test_a_real_gain_is_only_ever_up_x_since_start_real_money(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    st = owner_state()
    st["live_days"] = {YESTERDAY: {"pnl_usd": 0.50, "settled": 2, "won": 2}}
    st["live_pnl_total_usd"] = 0.50
    save(settings, st)
    real = plain(ledger, settings)["real"]
    assert real["line"] == ("Real money: $20.38 cash at Polymarket and $0.95 in 1 open bet; up $0.50 since start (real "
                            "money), 2 of 2 finished bets won.")
    assert real["result"] == "up $0.50 since start (real money)"
    for word in ("profit", "winning", "earn", "gain"):
        assert word not in real["line"].lower() and word not in real["result"].lower(), word


def test_no_finished_real_bet_and_no_cash_read_say_so(ledger: Ledger, settings: Settings) -> None:
    st = owner_state(balance=None)
    st["live_days"], st["live_pnl_total_usd"], st["positions"] = {}, 0.0, {}
    save(settings, st)
    real = plain(ledger, settings)["real"]
    assert real["on"] is True and real["at_risk_usd"] == 0.0 and real["open_bets"] == 0
    assert real["result"] is None  # no result before a real bet has finished
    assert real["line"] == "Real money: cash at Polymarket not read yet and no open bets; no bet has finished yet."


# --------------------------------------------------------------------------- real money on, but paused or stopped


def test_real_money_paused_by_the_risk_manager(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    st = paused_state()
    st["mode"] = "live"
    save(settings, st)
    p = plain(ledger, settings)
    assert p["real"]["on"] is True and p["real"]["paused_kind"] == "risk"
    assert p["real"]["paused"] == (f"Paused by the risk manager since {SINCE}: the rule's practice record was losing "
                                   "money, so it places no new real bets.")
    assert p["headline"] == "Real money is on for Voss's Polymarket bets but paused now; the rest is pretend money."
    assert len(p["headline"]) <= PLAIN_HEADLINE_MAX
    assert "(paused by the risk manager)" in p["pretend"]["line"]
    assert p["real"]["limits"] == LIMITS and p["real"]["verdict"] == VERDICT_NO_EDGE  # the verdict stays beside it


def test_real_buys_alone_paused_say_the_real_record(ledger: Ledger, settings: Settings) -> None:
    st = paused_state(real=[-0.98] * 12, paused_real=True, paper_paused=False)
    st["mode"] = "live"
    save(settings, st)
    real = plain(ledger, settings)["real"]
    assert real["paused_kind"] == "risk"
    assert real["paused"] == (f"Paused by the risk manager since {SINCE}: its real-money record was losing money, so "
                              "it places no new real bets.")


def test_the_days_loss_limit_and_a_full_book_stop_new_real_bets(ledger: Ledger, settings: Settings) -> None:
    save(settings, owner_state(live_today={"pnl_usd": -3.10, "settled": 4, "won": 1}))
    p = plain(ledger, settings)
    assert p["real"]["paused_kind"] == "day" and p["real"]["paused"] == (
        "Stopped for today: it lost $3.10 today and the daily limit is $3. It can bet again after midnight UTC.")
    assert p["headline"] == "Real money is on for Voss's Polymarket bets but stopped for today; the rest is pretend."
    st = owner_state()
    st["positions"] = {f"real{i}": position(f"real{i}", live=True, cost_usd=0.97) for i in range(10)}
    save(settings, st)
    p = plain(ledger, settings)
    real = p["real"]
    assert real["at_risk_usd"] == pytest.approx(9.70) and real["open_bets"] == 10
    # a full book is waiting at its cap, not a pause: the headline says the limit, never "paused"
    assert real["paused_kind"] == "full" and real["paused"] == (
        "Waiting: $9.70 is already in open bets and the most allowed at once is $10; it bets again when one finishes.")
    assert p["headline"] == "Real money is on for Voss's Polymarket bets, at its $10 limit; the rest is pretend."
    assert "paused" not in p["headline"] and len(p["headline"]) <= PLAIN_HEADLINE_MAX


# --------------------------------------------------------------------------- real money off


def test_real_money_off_with_a_book_left_at_the_venue(ledger: Ledger, settings: Settings) -> None:
    """The desk on paper while one real contract is still open: never "no real money is being bet" while real money
    is out in a bet, and the verdict never says the rule trades real amounts while it does not."""
    seed(ledger)
    save(settings, desk_state())  # the desk on paper: one real contract and the venue's cash still there
    p = plain(ledger, settings)
    assert p["headline"] == STILL_OPEN and len(STILL_OPEN) <= PLAIN_HEADLINE_MAX
    assert p["real"]["on"] is False and p["real"]["paused"] is None and p["real"]["open_bets"] == 1
    assert p["real"]["line"] == ("Real money is off. Still at Polymarket: $16.27 cash and $0.97 in 1 open bet; up "
                                 "$0.50 since start (real money), 2 of 2 finished bets won.")
    assert p["real"]["result"] == "up $0.50 since start (real money)"
    assert p["real"]["limits"] == LIMITS and p["real"]["verdict"] == VERDICT_NO_EDGE_OFF == (
        "This rule did not pass our tests for a real edge (proof that it wins over many bets); it places no new "
        "real-money bets now.")
    assert "trades only tiny real amounts" not in json.dumps(p)


def test_the_total_loss_stop_with_a_real_bet_still_open(ledger: Ledger,
                                                         make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(**LIVE_DESK)
    save(settings, halted_state())
    p = plain(ledger, settings)
    real = p["real"]
    assert real["on"] is False and real["open_bets"] == 1 and real["at_risk_usd"] == pytest.approx(0.95)
    assert p["headline"] == "Real money is off for new bets, but $0.95 is still in 1 open bet; the rest is pretend."
    assert real["line"] == ("Real money is off: Total loss cap reached (-10.20 $): the desk switched itself back to "
                            "paper for good; only the owner can switch it live again. Still at Polymarket: $20.38 cash "
                            "and $0.95 in 1 open bet; down $10.20 since start, 4 of 14 finished bets won.")
    assert real["result"] == "down $10.20 since start" and real["verdict"] == VERDICT_NO_EDGE_OFF


def test_many_open_real_bets_keep_the_headline_short(ledger: Ledger, settings: Settings) -> None:
    st = desk_state(real_open=0)
    st["positions"].update({f"real{i}": position(f"real{i}", live=True, cost_usd=95.0) for i in range(12)})
    save(settings, st)
    headline = plain(ledger, settings)["headline"]
    assert headline == "Real money is off for new bets, but $1,140.00 is still in 12 open bets."
    assert len(headline) <= PLAIN_HEADLINE_MAX


def test_real_money_off_says_the_desks_own_reason_when_live_was_asked_for(
        ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(**LIVE_DESK)
    st = desk_state(real_open=0, balance=None, venue=None)
    st["live_days"], st["live_pnl_total_usd"] = {}, 0.0
    st["live_status"] = "Polymarket rejected the API key (401): make a new key in the app and put it in Railway; staying on paper."
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["polymarket"]["status"] == st["live_status"]
    p = state["plain"]
    real = p["real"]
    assert real["on"] is False and real["reported"] is True and real["line"] == (
        "Real money is off: Polymarket rejected the API key (401): make a new key in the app and put it in Railway; "
        "staying on paper.")
    assert real["verdict"] == VERDICT_NO_EDGE_OFF and p["headline"] == OFF


def test_live_asked_but_the_desk_has_not_reported_says_so(ledger: Ledger,
                                                          make_settings: Callable[..., Settings]) -> None:
    """POLYDESK_MODE=live and no desk state yet (a missing file reads as an empty paper one): the page cannot know
    whether real money is on, so it never says "everything is practice"."""
    settings = make_settings(**LIVE_DESK)
    assert not polydesk.state_path(settings).exists()
    p = plain(ledger, settings)
    real = p["real"]
    assert real["reported"] is False and real["on"] is False
    assert real["line"] == ("Real money: no report yet from Voss's Polymarket bets, so this page cannot say if any is "
                            "at stake there.")
    assert p["headline"] == "Real money: no report yet from Voss's Polymarket bets; the rest is pretend money."
    assert "everything is practice" not in json.dumps(p)
    # paper mode with the same missing file: nothing was asked, so off is known
    assert plain(ledger, make_settings())["real"]["reported"] is True


def test_a_live_solana_bot_beside_a_silent_desk(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    """Real money is on (the bot itself runs live) while the desk has not reported: neither "everything else is
    practice" nor a grey "no report" over the Solana bot's real money."""
    p = plain(ledger, live_settings(make_settings, **LIVE_DESK))
    real = p["real"]
    assert real["on"] is True and real["reported"] is False
    assert p["headline"] == "Real money is on for the Solana bot; no report yet from Voss's Polymarket bets."
    assert real["line"].startswith("Real money: no report yet from Voss's Polymarket bets") and (
        "The Solana bot trades real money: " in real["line"])
    assert "everything else is practice" not in json.dumps(p)


def test_no_desk_no_real_money_and_no_verdict(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    seed(ledger)
    p = plain(ledger, settings)
    assert p["headline"] == OFF and p["real"]["line"] == "Real money is off: everything is practice with pretend money."
    assert p["real"]["limits"] is None and p["real"]["verdict"] is None and p["real"]["at_risk_usd"] is None
    assert p["real"]["how"] is None and p["real"]["result"] is None
    assert p["pretend"]["line"] == "Practice (pretend money): the Solana bot is down $5.50 since start."


def test_the_trend_desk_starts_tonight(ledger: Ledger, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    today = datetime.fromtimestamp(NOW, UTC).strftime("%Y-%m-%d")
    real_panel = trenddesk.panel_state

    def started_today(s: Settings, now: float) -> dict[str, Any]:
        return {**real_panel(s, now), "as_of": None, "started": today}

    monkeypatch.setattr(trenddesk, "panel_state", started_today)
    assert plain(ledger, settings)["pretend"]["line"].endswith("; the trend desk starts tonight (midnight UTC).")


# --------------------------------------------------------------------------- no events at all


def test_no_events_gives_no_news_and_quiet_characters(ledger: Ledger, settings: Settings) -> None:
    p = plain(ledger, settings)  # an empty ledger: nothing has happened yet
    assert p["now"] == [] and p["said"] == {}
    assert [t["id"] for t in p["team"]] == list(PLAIN_JOBS) == ["pip", "nyx", "rook", "jet", "mote", "voss"]
    for t in p["team"]:
        assert t["latest"] is None and t["latest_ts"] is None and t["latest_ago"] is None
        assert t["status_word"] == "waiting"  # the engine has not started: every member waits
    assert p["pretend"]["line"].startswith("Practice (pretend money): the Solana bot has no money check yet")


def test_old_events_are_not_right_now(ledger: Ledger, settings: Settings) -> None:
    st = owner_state()
    st["events"] = [{"ts": NOW - 7 * 3600, "text": "Settled: Will y happen? · won +0.25 $ (paper)", "tone": "good"}]
    save(settings, st)
    p = plain(ledger, settings)
    assert p["now"] == []  # older than six hours: not "right now"
    voss = next(t for t in p["team"] if t["id"] == "voss")
    assert voss["latest"] == "a practice bet (pretend money) won $0.25 · Will y happen?"
    assert voss["latest_ago"] == "7 h 00 min ago"  # the character's latest still says how old it is


# --------------------------------------------------------------------------- the team, the glossary


def test_the_team_says_which_money_each_one_handles(ledger: Ledger, settings: Settings) -> None:
    """Real money only for the desk while it is live; the Solana bot's parts pretend while it is paper; the
    receipts no money at all."""
    seed(ledger)
    save(settings, owner_state())
    team = plain(ledger, settings)["team"]
    assert [t["plain_role"] for t in team] == [
        "Pip finds new crypto coins for the Solana bot (pretend money)",
        "Nyx checks each coin for scams and waits for the buy signal (pretend money)",
        "Rook keeps each coin trade small and stops losses (pretend money)",
        "Jet places the Solana bot's trades (pretend money)",
        "Mote keeps the tamper-proof records",
        "Voss bets on yes/no questions at Polymarket (real money) and asks the AI judge about coins"]
    for t in team:
        assert t["name"] == CAST3D[t["id"]]["name"] and t["members"] == CAST3D[t["id"]]["members"]
        assert t["plain_role"] == f"{t['name']} {t['job']}" and t["status_word"] in ("working", "waiting", "idle", "stuck")
    assert sorted(m for t in team for m in t["members"]) == sorted(MEMBER_IDS)  # every member, once
    save(settings, desk_state())  # the desk on paper: Voss bets pretend money
    voss = next(t for t in plain(ledger, settings)["team"] if t["id"] == "voss")
    assert voss["job"] == "bets on yes/no questions at Polymarket (pretend money) and asks the AI judge about coins"


def test_a_live_solana_bot_makes_its_parts_real_money(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    team = {t["id"]: t["job"] for t in plain(ledger, live_settings(make_settings))["team"]}
    assert team["pip"].endswith("(real money)") and team["jet"] == "places the Solana bot's trades (real money)"
    assert team["voss"].startswith("bets on yes/no questions at Polymarket (pretend money)")  # the desk: no state
    assert "money" not in team["mote"]


def test_each_member_has_its_own_job_for_the_bubbles(ledger: Ledger, settings: Settings) -> None:
    jobs = plain(ledger, settings)["jobs"]
    assert jobs == {mid: PLAIN_MEMBER_JOBS[mid] for mid, _, _ in MEMBERS} and set(jobs) == set(MEMBER_IDS)
    # an AI-judge verdict is the judge's, never the prediction-market desk's (Voss plays both)
    assert jobs["judge"] == "asks the AI judge about each coin"
    assert jobs["predict"] == "bets on yes/no questions at Polymarket"
    assert jobs["strategy"] == "waits for the buy signal" and jobs["radar"] == "checks for danger right before a buy"


def test_a_blocked_member_makes_its_character_stuck(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    ledger.set_kv("engine.heartbeat", NOW - 3600)  # the engine went silent: every member is blocked
    team = plain(ledger, settings)["team"]
    assert {t["status_word"] for t in team if t["id"] != "voss"} == {"stuck"}


def test_the_glossary_covers_the_words_still_on_screen() -> None:
    words = [w for w, _ in GLOSSARY]
    assert 8 <= len(words) <= 13
    for needed in ("Real money", "Pretend money (paper)", "Settled", "The desk", "The risk manager", "Receipts",
                   "The vault", "Trend desk", "Polymarket", "A real edge", "Contract", "Prediction market"):
        assert needed in words, needed
    assert not [m for _, m in GLOSSARY if re.search(r"\d+\.\d\d", m)]  # fixed text: no figure in it
    means = dict(GLOSSARY)
    # never more than the bot can back: the receipts make a change show, the limits are settings checked per bet
    assert means["Receipts"].endswith("so any later change would show.") and "nothing can be" not in means["Receipts"]
    assert means["Hard limits"].startswith("Caps in the bot's settings, checked before every bet")
    assert "written into the code" not in means["Hard limits"]


# --------------------------------------------------------------------------- honesty


def test_real_and_pretend_money_are_never_added_together(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    save(settings, owner_state())
    state = build_page_state(ledger, settings, NOW)
    pm, money = state["money"]["polymarket"], state["money"]
    figures = [money["since_start"]["usd"], money["today"]["usd"], pm["paper"]["today_usd"],
               pm["paper"]["since_start_usd"], pm["real"]["since_start_usd"], pm["real"]["cash_usd"],
               pm["real"]["at_risk_usd"], pm["real"]["cost_usd"]]
    trend = money.get("trend")
    if trend is not None:
        figures += [trend["since_start_usd"], trend["equity_usd"]]
    shown = {round(abs(f), 2) for f in figures}
    body = json.dumps(state["plain"], ensure_ascii=False)
    for a, b in itertools.combinations(figures, 2):
        total = round(abs(a + b), 2)
        if total in shown or total < 0.01:
            continue  # a sum that equals a figure shown on its own is no evidence either way
        for text in (f"{total:,.2f}", f"{total:.2f}"):
            assert text not in body, (a, b, text)


def test_pretend_always_says_pretend_and_real_only_where_the_data_says_live(ledger: Ledger,
                                                                           settings: Settings) -> None:
    seed(ledger)
    save(settings, desk_state())  # paper desk (one real contract still open at the venue)
    p = plain(ledger, settings)
    assert "pretend" in p["pretend"]["line"] and p["pretend"]["line"].startswith("Practice (pretend money): ")
    assert not re.search(r"Real money(?! is off)", p["real"]["line"])  # off: never "Real money:" as if it were on
    assert not re.search(r"real money is on", p["headline"], re.IGNORECASE)
    for sentence in [p["headline"], p["about"], *texts(p["real"]), *texts(p["pretend"]),
                     *[t["plain_role"] for t in p["team"]], *texts(p["jobs"]), *texts(p["glossary"])]:
        assert not JARGON.search(sentence), sentence


def test_the_events_in_plain_words() -> None:
    cases = [
        ("predict", "Paper buy: Will BTC close above $120k? · long at 0.975 · $20 (crypto)",
         "practice bet (pretend money): $20 on YES · Will BTC close above $120k?"),
        ("predict", "Paper buy: Will it snow? · short at 0.981 · $20 (weather)",
         "practice bet (pretend money): $20 on NO · Will it snow?"),
        ("predict", "REAL buy: Will it rain? · 1 contract at 0.950 ($0.95, weather)", "real-money bet: $0.95 on YES · Will it rain?"),
        ("predict", "Settled: Will x happen? · lost -20.03 $ (paper)", "a practice bet (pretend money) lost $20.03 · Will x happen?"),
        ("predict", "Settled: Will y happen? · won +0.02 $ (real)", "a real-money bet won $0.02 · Will y happen?"),
        ("predict", "No fill at 0.975: Will z happen? (order cancelled)",
         "a real-money order found no seller and was cancelled · Will z happen?"),
        ("predict", "Order rejected by the venue (400): Will q?", "Polymarket refused a real-money order · Will q?"),
        ("predict", "Lesson: weather markets settle late", "Lesson: weather markets settle late"),
        ("crawler", "NEWEST · 61 min old · worth $210k · found on Jupiter", "found a new coin: NEWEST (61 min old)"),
        ("cocoon", "REJECT SECOND · Top 10 wallets hold too much: top-10 own 45%",
         "threw out SECOND: Top 10 wallets hold too much: top-10 own 45%"),
        ("cocoon", "PASS NEWEST · passed (0 warnings)", "NEWEST passed the scam check"),
        ("radar", "CLEAR AAA · 3 big trades, sells $0 in 5 min", "checked AAA right before buying: all clear"),
        ("judge", "NO 70% · JUDGED · creator selling", "the AI judge said no to JUDGED: creator selling"),
        ("broker", "BUY HIGGS for 0.1000 SOL at $0.002 · price moved 1.50% · fees 0.10% + 0.000300 SOL network",
         "bought HIGGS for 0.1000 SOL (pretend money)"),
        ("strategy", "Trend desk: BTC closed above its 50-day average -> in (paper)",
         "Trend desk: BTC closed above its 50-day average -> in (pretend money)"),
        ("receipts", "#3 decision: now watching NEWEST · 0a1b2c3d",
         "sealed record #3 in the tamper-proof log (decision: now watching NEWEST)"),
    ]
    for member, text, expected in cases:
        assert plain_event(member, text) == expected, text
    assert plain_event("broker", "SELL HIGGS for 0.1200 SOL at $0.003 · price moved 1%", live=True) == (
        "sold HIGGS for 0.1200 SOL (real money)")
    assert len(plain_event("predict", "Lesson: " + "x" * 400)) == 110  # clipped


def test_the_desks_own_stops_in_plain_words() -> None:
    """The polydesk and risk-manager texts that matter most for real money, each by a fixed template."""
    cases = [
        ("Daily loss cap reached: no more real buys today.",
         "hit today's loss limit: no more real-money bets until midnight UTC"),
        ("Total loss cap reached: real trading stopped, back to paper.",
         "hit the total loss limit: real money is off for good, practice only"),
        ("Risk manager paused the desk: 60 events (60 settled), 6 lost, -$98.40 in all",
         "the risk manager paused the desk: its record is losing (60 events (60 settled), 6 lost, -$98.40 in all)"),
        ("Risk manager paused real buys: 12 events (12 settled), 12 lost, -$11.76 in all",
         "the risk manager paused real buys: its record is losing (12 events (12 settled), 12 lost, -$11.76 in all)"),
        ("Paper book full (40 open): no new paper buys until some settle.",
         "the practice book is full: no new pretend bets until some finish"),
        (("Paper book full (10 open, the most until the rule's paper record is winning): no new paper buys until "
          "some settle."), "the practice book is full: no new pretend bets until some finish"),
    ]
    for text, expected in cases:
        assert plain_event("predict", text) == expected, text
        assert "paper" not in plain_event("predict", text).lower()


def test_a_standalone_paper_is_said_pretend_but_a_ticker_stays() -> None:
    assert plain_event("predict", "Lesson: paper buys at 0.99 lose") == "Lesson: pretend buys at 0.99 lose"
    assert plain_event("strategy", "Paper desk idle") == "Pretend desk idle"
    assert plain_event("strategy", "WATCH PAPER · a coin called PAPER") == "WATCH PAPER · a coin called PAPER"
    assert plain_event("strategy", "newspaper rally") == "newspaper rally"  # (a word inside another stays)


def test_the_crawler_template_takes_only_a_candidate_row() -> None:
    """A crawler text that is not a coin row is shown as written, never as "found a new coin"."""
    assert plain_event("crawler", "Scanner error: feed down") == "Scanner error: feed down"
    assert plain_event("crawler", "WIF") == "found a new coin: WIF"  # a bare symbol: the row with nothing known yet
    assert plain_event("crawler", "WIF · worth $2.1k · found on Jupiter") == "found a new coin: WIF"
    assert plain_event("crawler", "WIF · found on Jupiter, Pump") == "found a new coin: WIF"
    assert plain_event("crawler", "WIF · 3.5 h old") == "found a new coin: WIF (3.5 h old)"


# --------------------------------------------------------------------------- the desk's positions: the real one first


def test_the_desk_lists_its_real_money_positions_first(settings: Settings) -> None:
    """The 3D board shows the first three: a real bet must never fall off behind newer pretend ones."""
    st = desk_state(paper_open=4, real_open=0)
    for i, key in enumerate(st["positions"]):
        st["positions"][key]["t_in"] = NOW - 60 + i  # the pretend ones are newer
    st["positions"]["real0"] = {**position("real0", live=True, cost_usd=0.95), "t_in": NOW - 3600}
    save(settings, st)
    rows = polydesk.panel_state(settings, NOW)["positions"]
    assert [r["live"] for r in rows] == [True, False, False, False, False]
    assert [r["t_in"] for r in rows[1:]] == sorted((r["t_in"] for r in rows[1:]), reverse=True)  # newest first


# --------------------------------------------------------------------------- the main page: the card, text only


def test_the_page_puts_the_plain_card_first_and_inserts_it_as_text(settings: Settings) -> None:
    html = render_page_html(settings)
    ids = re.findall(r'<section class="card" id="([a-z]+)"', html)
    assert ids[:2] == ["plain", "money"]
    card = html[html.index('<section class="card" id="plain">'):html.index('<section class="card" id="money">')]
    for part in ('id="plain-about"', 'id="plain-headline"', 'id="plain-real"', 'id="plain-pretend"', ">Right now<",
                 'id="plain-now"', ">Who is who<", 'id="plain-team"', '<a href="world">Watch them in 3D</a>',
                 ">What the words mean<", 'id="plain-words"'):
        assert part in card, part
    assert card.index('id="plain-about"') < card.index('id="plain-headline"')  # what the app is, first
    script = page_script(settings)
    assert "function renderPlain(p)" in script and "renderPlain(s.plain);\n    renderMoney(s.money," in script
    assert "if (!p || !p.real || !p.pretend) return;" in script  # older data without the block: no error
    body = script[script.index("function renderPlain(p)"):script.index("// ---------------------------------------------------------------- A. money")]
    assert "r.label" in body and "p.pretend.label" in body and '"Real money"' not in script  # labels from the data
    for key in ("p.about", "r.line", "r.how", "r.limits", "r.verdict", "r.paused", "r.result", "p.now"):
        assert key in body, key
    assert 'r.limits ? el("p", "meta", r.limits)' in body  # "can I lose a lot?": as big as the line itself
    assert 'r.result ? el("span", "big", r.result)' in body  # the result as big as the money at risk
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink
    assert script.count(".replaceChildren(") == 1  # every fill goes through put()
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', body)
    assert not [s for s in strings if " " in s and JARGON.search(s)]
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)
    for text, directive in ((script, "script-src"), (style, "style-src")):
        digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}';" in PAGE_CSP


def test_the_page_never_says_paper_before_the_data_and_names_the_links(settings: Settings,
                                                                     make_settings: Callable[..., Settings]) -> None:
    html = render_page_html(settings)
    head = html[html.index('<header class="top">'):html.index("</header>")]
    assert '<b class="mode" id="mode" hidden></b>' in head and "PAPER" not in head
    assert "<title>nightcrawler</title>" in html and "· paper" not in html
    assert ">Watch the team (3D)</a>" in head and ">Pictures</a>" in head and ">3D<" not in head and ">Office<" not in head
    live = render_page_html(live_settings(make_settings))  # the bot itself live: real money is on, whatever the desks
    assert '<b class="mode live" id="mode">REAL MONEY ON</b>' in live and "<title>nightcrawler · real money on</title>" in live
    script = page_script(settings)
    assert "mode.textContent = s.mode" not in script and "words.badge" in script
    assert 'document.title = "nightcrawler" + (words ? " · " + words.title : "");' in script
    # the Solana bot's money card: its own title, "Pretend:" before the big figure, the cast's names on the team
    assert '<h2>Solana bot <small id="money-label">Paper money (pretend)</small></h2>' in html
    assert 'el("span", "hero-tag", live ? "Real: " : "Pretend: ")' in script
    assert 'renderMoney(s.money, s.mode === "LIVE");' in script
    assert '" · played by " + ch.name' in script and "renderTeam(s.team, s.experience, s.plain);" in script


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_badge_follows_the_plain_words_never_paper(ledger: Ledger, settings: Settings,
                                                       make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    """With the desk live the badge says REAL MONEY ON (red), with a real bet left open after it stopped it stays red,
    and never a bare PAPER; the badge words come from the page's own fixed list, chosen by plain.real."""
    seed(ledger)
    reals = {}
    for name, st in (("live", owner_state()), ("still_open", desk_state())):
        save(settings, st)
        reals[name] = plain(ledger, settings)["real"]
    save(settings, desk_state(real_open=0, venue=None, balance=None))
    reals["paper"] = plain(ledger, settings)["real"]
    reals["silent"] = plain(ledger, make_settings(**LIVE_DESK, DATA_DIR=str(tmp_path / "empty")))["real"]
    words = _js_body(page_script(settings), "  function moneyWords(r) {")
    out = _node(f"{words}\nconst reals = {json.dumps(reals)};\nconst o = {{}};\n"
                "for (const k of Object.keys(reals)) o[k] = moneyWords(reals[k]);\no.none = moneyWords(null);\n"
                "console.log(JSON.stringify(o));", tmp_path)
    assert out["live"] == {"badge": "REAL MONEY ON", "live": True, "title": "real money on"}
    assert out["still_open"] == {"badge": "REAL BETS STILL OPEN", "live": True, "title": "real bets still open"}
    assert out["paper"] == {"badge": "PRETEND MONEY", "live": False, "title": "pretend money"}
    assert out["silent"]["badge"] == "REAL MONEY: NO REPORT YET" and out["none"] is None
    assert not [k for k, v in out.items() if v and "PAPER" in v["badge"]]

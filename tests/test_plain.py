"""The screen in plain words (``/api/page.plain``, nightcrawler.pagestate.plain_words) and the main page's "In plain
words" card (the 3D world's bar and guide: tests/test_world3d.py). Fixed templates filled with the data's own numbers
only; "real money" only where the data says live; pretend money always says "pretend"; a gain only as "up $X since
start (real money)"; the lab's verdict beside every real-money panel; no figure of one kind of money ever added to
another; text-only insertion and the CSP hashes in step."""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import re
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
    no_learning_module,
    page_script,
    seed,
)
from test_page_deskguard import SINCE, paused_state
from test_page_polymarket import YESTERDAY, desk_state, position, save

from nightcrawler import trenddesk
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.ledger import Ledger
from nightcrawler.office3d import CAST3D
from nightcrawler.page import PAGE_CSP, render_page_html
from nightcrawler.pagestate import (
    GLOSSARY,
    PLAIN_JOBS,
    PRETEND_LABEL,
    REAL_LABEL,
    RESEARCH_LINE,
    VERDICT_NO_EDGE,
    build_page_state,
    plain_event,
)

KEY = {"POLYMARKET_US_KEY_ID": "0000-key", "POLYMARKET_US_SECRET_KEY": "c2VjcmV0"}
LIMITS = ("Hard limits: one contract (under $1) per bet, at most $10 in bets at once, stops for the day after losing "
          "$3, stops for good after losing $10.")
ON = "Real money is on for one small desk; everything else is practice with pretend money."
OFF = "No real money is being bet right now: every desk is practising with pretend money."


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
    assert p["headline"] == ON and len(p["headline"]) <= 90  # two lines at most on a 390 px phone
    real = p["real"]
    assert real == {
        "label": REAL_LABEL, "on": True, "paused": None, "at_risk_usd": pytest.approx(0.95), "open_bets": 1,
        "cash_usd": pytest.approx(20.38),
        "line": "Real money: $20.38 cash at Polymarket and $0.95 in 1 open bet; down $1.78 since start, 6 of 8 "
                "finished bets won.",
        "limits": LIMITS, "verdict": VERDICT_NO_EDGE, "research": RESEARCH_LINE}
    assert real["verdict"] == ("This rule did not pass our tests for a real edge, so it trades only tiny real amounts "
                               "with hard limits.")
    assert RESEARCH_LINE == "No strategy tested so far has passed our lab's test for a real edge."
    assert p["pretend"]["label"] == PRETEND_LABEL == "Practice (pretend money)"
    assert p["pretend"]["line"].startswith("Practice (pretend money): the Solana bot is down $5.50 since start; the "
                                           "Polymarket practice book is down $1,345.53 today; the trend desk ")
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
    line = plain(ledger, settings)["real"]["line"]
    assert line == ("Real money: $20.38 cash at Polymarket and $0.95 in 1 open bet; up $0.50 since start (real money), "
                    "2 of 2 finished bets won.")
    for word in ("profit", "winning", "earn", "gain"):
        assert word not in line.lower(), word


def test_no_finished_real_bet_and_no_cash_read_say_so(ledger: Ledger, settings: Settings) -> None:
    st = owner_state(balance=None)
    st["live_days"], st["live_pnl_total_usd"], st["positions"] = {}, 0.0, {}
    save(settings, st)
    real = plain(ledger, settings)["real"]
    assert real["on"] is True and real["at_risk_usd"] == 0.0 and real["open_bets"] == 0
    assert real["line"] == "Real money: cash at Polymarket not read yet and no open bets; no bet has finished yet."


# --------------------------------------------------------------------------- real money on, but paused or stopped


def test_real_money_paused_by_the_risk_manager(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    st = paused_state()
    st["mode"] = "live"
    save(settings, st)
    p = plain(ledger, settings)
    assert p["real"]["on"] is True
    assert p["real"]["paused"] == (f"Paused by the risk manager since {SINCE}: the rule's practice record was losing "
                                   "money, so it places no new real bets.")
    assert p["headline"] == "Real money is on for one small desk but paused right now; the rest is pretend money."
    assert len(p["headline"]) <= 90
    assert "(paused by the risk manager)" in p["pretend"]["line"]
    assert p["real"]["limits"] == LIMITS and p["real"]["verdict"] == VERDICT_NO_EDGE  # the verdict stays beside it


def test_real_buys_alone_paused_say_the_real_record(ledger: Ledger, settings: Settings) -> None:
    st = paused_state(real=[-0.98] * 12, paused_real=True, paper_paused=False)
    st["mode"] = "live"
    save(settings, st)
    paused = plain(ledger, settings)["real"]["paused"]
    assert paused == (f"Paused by the risk manager since {SINCE}: its real-money record was losing money, so it places "
                      "no new real bets.")


def test_the_days_loss_limit_and_a_full_book_stop_new_real_bets(ledger: Ledger, settings: Settings) -> None:
    save(settings, owner_state(live_today={"pnl_usd": -3.10, "settled": 4, "won": 1}))
    assert plain(ledger, settings)["real"]["paused"] == (
        "Stopped for today: it lost $3.10 today and the daily limit is $3. It can bet again after midnight UTC.")
    st = owner_state()
    st["positions"] = {f"real{i}": position(f"real{i}", live=True, cost_usd=0.97) for i in range(10)}
    save(settings, st)
    real = plain(ledger, settings)["real"]
    assert real["at_risk_usd"] == pytest.approx(9.70) and real["open_bets"] == 10
    assert real["paused"] == ("Waiting: $9.70 is already in open bets and the most allowed at once is $10; it bets "
                              "again when one finishes.")


# --------------------------------------------------------------------------- real money off


def test_real_money_off_with_a_book_left_at_the_venue(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    save(settings, desk_state())  # the desk on paper: one real contract and the venue's cash still there
    p = plain(ledger, settings)
    assert p["headline"] == OFF and p["real"]["on"] is False and p["real"]["paused"] is None
    assert p["real"]["line"] == ("Real money is off. Still at Polymarket: $16.27 cash and $0.97 in 1 open bet; up "
                                 "$0.50 since start (real money), 2 of 2 finished bets won.")
    assert p["real"]["limits"] == LIMITS and p["real"]["verdict"] == VERDICT_NO_EDGE


def test_real_money_off_says_the_desks_own_reason_when_live_was_asked_for(
        ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(POLYDESK_MODE="live", POLYDESK_LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, **KEY)
    st = desk_state(real_open=0, balance=None, venue=None)
    st["live_days"], st["live_pnl_total_usd"] = {}, 0.0
    st["live_status"] = "Polymarket rejected the API key (401): make a new key in the app and put it in Railway; staying on paper."
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["polymarket"]["status"] == st["live_status"]
    real = state["plain"]["real"]
    assert real["on"] is False and real["line"] == (
        "Real money is off: Polymarket rejected the API key (401): make a new key in the app and put it in Railway; "
        "staying on paper.")


def test_no_desk_no_real_money_and_no_verdict(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    seed(ledger)
    p = plain(ledger, settings)
    assert p["headline"] == OFF and p["real"]["line"] == "Real money is off: every desk is practising with pretend money."
    assert p["real"]["limits"] is None and p["real"]["verdict"] is None and p["real"]["at_risk_usd"] is None
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


def test_the_team_is_the_cast_with_fixed_plain_jobs(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    team = plain(ledger, settings)["team"]
    assert {t["plain_role"] for t in team} == {
        "Pip finds new coins", "Nyx checks each coin for scams", "Rook keeps every bet small and stops losses",
        "Jet places the trades", "Mote keeps the tamper-proof records", "Voss runs the prediction-market desk"}
    for t in team:
        assert t["name"] == CAST3D[t["id"]]["name"] and t["members"] == CAST3D[t["id"]]["members"]
        assert t["plain_role"] == f"{t['name']} {t['job']}" and t["status_word"] in ("working", "waiting", "idle", "stuck")
    assert sorted(m for t in team for m in t["members"]) == sorted(MEMBER_IDS)  # every member, once


def test_a_blocked_member_makes_its_character_stuck(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    ledger.set_kv("engine.heartbeat", NOW - 3600)  # the engine went silent: every member is blocked
    team = plain(ledger, settings)["team"]
    assert {t["status_word"] for t in team if t["id"] != "voss"} == {"stuck"}


def test_the_glossary_covers_the_words_still_on_screen() -> None:
    words = [w for w, _ in GLOSSARY]
    assert 8 <= len(words) <= 10
    for needed in ("Real money", "Pretend money (paper)", "Settled", "The desk", "The risk manager", "Receipts",
                   "The vault", "Trend desk", "Polymarket"):
        assert needed in words, needed
    assert not [m for _, m in GLOSSARY if re.search(r"\d+\.\d\d", m)]  # fixed text: no figure in it


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
    save(settings, desk_state())  # paper desk
    p = plain(ledger, settings)
    assert "pretend" in p["pretend"]["line"] and p["pretend"]["line"].startswith("Practice (pretend money): ")
    assert not re.search(r"Real money(?! is off)", p["real"]["line"])  # off: never "Real money:" as if it were on
    assert not re.search(r"\breal money\b", p["headline"].replace("No real money", ""), re.IGNORECASE)
    for sentence in [p["headline"], *texts(p["real"]), *texts(p["pretend"]), *[t["plain_role"] for t in p["team"]],
                     *texts(p["glossary"])]:
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


# --------------------------------------------------------------------------- the main page: the card, text only


def test_the_page_puts_the_plain_card_first_and_inserts_it_as_text(settings: Settings) -> None:
    html = render_page_html(settings)
    ids = re.findall(r'<section class="card" id="([a-z]+)"', html)
    assert ids[:2] == ["plain", "money"]
    card = html[html.index('<section class="card" id="plain">'):html.index('<section class="card" id="money">')]
    for part in ('id="plain-headline"', 'id="plain-real"', 'id="plain-pretend"', ">Right now<", 'id="plain-now"',
                 ">Who is who<", 'id="plain-team"', ">What the words mean<", 'id="plain-words"'):
        assert part in card, part
    script = page_script(settings)
    assert "function renderPlain(p)" in script and "renderPlain(s.plain);\n    renderMoney(s.money);" in script
    assert "if (!p || !p.real || !p.pretend) return;" in script  # older data without the block: no error
    body = script[script.index("function renderPlain(p)"):script.index("// ---------------------------------------------------------------- A. money")]
    assert "r.label" in body and "p.pretend.label" in body and '"Real money"' not in script  # labels from the data
    assert "r.line" in body and "r.limits" in body and "r.verdict" in body and "r.paused" in body and "p.now" in body
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink
    assert script.count(".replaceChildren(") == 1  # every fill goes through put()
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', body)
    assert not [s for s in strings if " " in s and JARGON.search(s)]
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)
    for text, directive in ((script, "script-src"), (style, "style-src")):
        digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}';" in PAGE_CSP

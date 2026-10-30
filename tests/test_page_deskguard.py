"""The risk manager on the team room and the one page: the risk member lists each desk's verdict (Polymarket paper,
and Polymarket real once it has a record), the desk's own panel leads with a pause (since when), the stats say
"paused since <time>; now <verdict>", ``money.polymarket.guard`` is typed, the town's lines say "paused by the risk
manager" while paused (the real buys alone too), and the page renders the verdict line and the tag as text only
(the CSP hashes follow the edit)."""

from __future__ import annotations

import base64
import hashlib
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
    NOW,
    no_learning_module,
    page_script,
    seed,
)
from test_page_polymarket import desk_state, save

from nightcrawler import deskguard, polydesk
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.page import PAGE_CSP, render_page_html
from nightcrawler.pagestate import build_page_state, polymarket_desk
from nightcrawler.teamroom import build_team_state

LOSING = ([0.40] * 9 + [-20.0]) * 6  # 60 settled, 6 lost, -$98.40: losing
RULE = polydesk.rule_id(Settings.from_env({}))  # the default settings' rule
#: The losing record's reason, as the desk words it (each settlement its own event, $20 at risk each).
REASON = "60 events (60 settled), 6 lost, -$98.40 in all; even at best -1.54 % of the stake an event (95 % sure)"
PAUSED_AT = NOW - 300
SINCE = datetime.fromtimestamp(PAUSED_AT, UTC).strftime("%H:%M UTC")


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def _record(pnls: list[float], stake: float) -> dict[str, Any]:
    return {"settled": len(pnls), "won": sum(x > 0 for x in pnls), "pnl_usd": sum(pnls), "pnls": list(pnls),
            "costs": [stake] * len(pnls), "keys": [f"k{i}" for i in range(len(pnls))]}


def paused_state(*, real: list[float] | None = None, paused_real: bool = False, paper_paused: bool = True,
                 **kw: Any) -> dict[str, Any]:
    """The 2026-10-09 desk state with the current rule's paper record losing and the desk paused by the guard."""
    st = desk_state(**kw)
    rec: dict[str, Any] = {"paper": _record(LOSING, 20.0)}
    if real is not None:
        rec["real"] = _record(real, 0.98)
    st["by_rule"] = {RULE: rec}
    if paper_paused:
        st["paused"] = {"at": PAUSED_AT, "reason": REASON, "rule": RULE}
    if paused_real:
        st["paused_real"] = {"at": PAUSED_AT, "reason": "real reason", "rule": RULE}
    st["events"] = [{"ts": PAUSED_AT, "text": f"Risk manager paused the desk: {REASON}", "tone": "bad"},
                    {"ts": NOW - 400, "text": "Settled: Will x happen? · lost -20.03 $ (paper)", "tone": "bad"},
                    {"ts": NOW - 500, "text": "No longer clears the risk manager's bar: the paper record is losing now",
                     "tone": "neutral"}]
    return st


def team(ledger: Ledger, settings: Settings) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in build_team_state(ledger, settings, NOW)["panels"]}


def stat(panel: dict[str, Any], label: str) -> Any:
    return next(s["value"] for s in panel["stats"] if s["label"] == label)


# --------------------------------------------------------------------------- the team room


def test_the_risk_member_lists_each_desks_verdict(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    assert polydesk.rule_id(settings) == RULE
    assert deskguard.judge(LOSING, groups=[f"k{i}" for i in range(60)], stakes=[20.0] * 60).reason == REASON
    risk = team(ledger, settings)["risk"]  # no desk file yet: the paper desk is still learning, nothing paused
    assert risk["desks"] == [{"desk": "Polymarket paper", "verdict": "learning", "phrase": "still learning",
                              "reason": "0 of 30 events needed before judging; so far $0.00, 0 lost",
                              "paused": False, "since": None,
                              "line": "Risk manager (paper, still learning): 0 of 30 events needed before judging; "
                                      "so far $0.00, 0 lost."}]
    assert stat(risk, "Polymarket paper") == "still learning" and "Paused" not in risk["doing"]
    save(settings, paused_state())
    by = team(ledger, settings)
    risk = by["risk"]
    assert [(d["desk"], d["verdict"], d["paused"], d["since"]) for d in risk["desks"]] == [
        ("Polymarket paper", "losing", True, SINCE)]
    assert risk["desks"][0]["line"] == f"Paused by the risk manager since {SINCE} (paper buys stopped): {REASON}."
    assert stat(risk, "Polymarket paper") == f"paused since {SINCE}; now losing"
    assert risk["doing"].endswith(" Paused Polymarket paper buys: the record was losing.")
    texts = [e["text"] for e in risk["events"]]
    assert any(t.startswith("Risk manager paused the desk: 60 events") for t in texts)
    assert any(t.startswith("No longer clears the risk manager's bar") for t in texts)  # the flag's events too
    assert not any(t.startswith("Settled:") for t in texts)  # only the risk manager's own events
    assert risk["status"] != "blocked"  # pausing a losing desk is the risk member doing its job
    predict = by["predict"]
    assert predict["doing"].startswith(f"Paused by the risk manager since {SINCE}: no new paper buys, the record was "
                                       "losing. ")
    assert stat(predict, "Risk manager (paper)") == f"paused since {SINCE}; now losing"
    assert predict["guard"]["paper"]["paused"] is True
    for panel in (risk, predict):
        assert len(panel["doing"]) <= 160 and not JARGON.search(panel["doing"])
    json.dumps(build_team_state(ledger, settings, NOW), allow_nan=False)


def test_the_stat_and_the_line_say_what_the_record_says_now(ledger: Ledger, settings: Settings) -> None:
    """A pause sticks while open positions keep settling: the record may read "not proven" later. The stat and the
    line say when the pause began, what the record said then, and what it says now; they never disagree."""
    seed(ledger)
    st = paused_state()
    st["by_rule"][RULE]["paper"] = _record(LOSING + [0.5] * 60, 20.0)  # 60 more wins since the pause
    save(settings, st)
    risk = team(ledger, settings)["risk"]
    now_reason = risk["desks"][0]["reason"]
    assert risk["desks"][0]["verdict"] == "unclear" and now_reason.startswith("120 events (120 settled), 6 lost")
    assert stat(risk, "Polymarket paper") == f"paused since {SINCE}; now not proven yet"
    assert risk["desks"][0]["line"] == (f"Paused by the risk manager since {SINCE} (paper buys stopped; then: {REASON}); "
                                        f"the paper record now: {now_reason}.")
    assert "losing" not in stat(risk, "Polymarket paper").split("now ")[1]


def test_the_real_book_joins_the_list_once_it_has_a_record(ledger: Ledger, settings: Settings,
                                                           make_settings: Callable[..., Settings]) -> None:
    seed(ledger)
    save(settings, paused_state(real=[-0.98] * 3, paused_real=True))
    risk = team(ledger, settings)["risk"]
    assert [(d["desk"], d["verdict"], d["paused"]) for d in risk["desks"]] == [
        ("Polymarket paper", "losing", True), ("Polymarket real", "learning", True)]
    assert stat(risk, "Polymarket real") == f"paused since {SINCE}; now still learning"
    assert risk["desks"][1]["line"] == (f"Paused by the risk manager since {SINCE} (real buys stopped; then: real "
                                        "reason); the real record now: 3 of 30 events needed before judging; so far "
                                        "-$2.94, 3 lost.")
    assert risk["doing"].endswith(" Paused Polymarket paper and Polymarket real buys: the record was losing.")
    off = make_settings(POLYDESK_ENABLED=False)
    save(off, paused_state())
    assert team(ledger, off)["risk"]["desks"] == []  # the desk is off: nothing to judge


def test_the_desks_pause_line_names_the_buys_its_mode_makes(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    st = paused_state()
    st["mode"] = "live"  # live: a losing paper record stops the real buys
    save(settings, st)
    predict = team(ledger, settings)["predict"]
    assert predict["doing"].startswith(f"Paused by the risk manager since {SINCE}: no new real buys, the record was "
                                       "losing. ")
    assert predict["guard"]["real"]["paused"] is True
    save(settings, paused_state(real=[-0.98] * 3, paused_real=True, paper_paused=False))
    predict = team(ledger, settings)["predict"]  # paper mode, only the real book paused: paper buys go on
    assert not predict["doing"].startswith("Paused")
    assert stat(predict, "Risk manager (real)") == f"paused since {SINCE}; now still learning"


# --------------------------------------------------------------------------- the page's data


def test_money_polymarket_carries_the_guard_and_the_town_says_paused(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    save(settings, desk_state())  # nothing paused: the guard is there, the town line says nothing of it
    state = build_page_state(ledger, settings, NOW)
    guard = state["money"]["polymarket"]["guard"]
    assert guard == {"verdict": "learning", "reason": "0 of 30 events needed before judging; so far $0.00, 0 lost",
                     "paused": False, "since": None,
                     "line": "Risk manager (paper, still learning): 0 of 30 events needed before judging; so far "
                             "$0.00, 0 lost.",
                     "on": True, "candidate": False, "real": None}
    assert "risk manager" not in state["town"]["line"] and "risk manager" not in state["town"]["polymarket"]["paper"]["line"]
    save(settings, paused_state())
    state = build_page_state(ledger, settings, NOW)
    guard = state["money"]["polymarket"]["guard"]
    assert guard["verdict"] == "losing" and guard["paused"] is True and guard["real"] is None
    assert guard["reason"] == REASON and guard["since"] == SINCE
    assert guard["line"] == f"Paused by the risk manager since {SINCE} (paper buys stopped): {REASON}."
    town = state["town"]
    assert town["polymarket"]["paper"]["line"].endswith(", 2 open; paused by the risk manager")
    assert "The Polymarket desk is paused by the risk manager: its rule's record was losing money." in town["line"]
    assert town["line"].index("paused by the risk manager") < town["line"].index("Polymarket real money")
    # the real book's own pause on its own line
    save(settings, paused_state(real=[-0.98] * 3, paused_real=True))
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["polymarket"]["guard"]["real"]["paused"] is True
    assert state["town"]["polymarket"]["real"]["line"].endswith("; real buys paused by the risk manager")
    for text in (town["line"], town["polymarket"]["paper"]["line"], guard["line"]):
        assert not JARGON.search(text), text
    json.dumps(state, allow_nan=False)


def test_a_pause_of_the_real_buys_alone_is_shown_and_said(ledger: Ledger, settings: Settings) -> None:
    """Live, the real record losing and the paper one not: the money card's guard says the real buys are paused,
    and the town has a sentence for it (the page's tag reads the same fields)."""
    seed(ledger)
    st = paused_state(real=[-0.98] * 3, paused_real=True, paper_paused=False)
    st["mode"] = "live"
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    guard = state["money"]["polymarket"]["guard"]
    assert guard["paused"] is False and guard["real"]["paused"] is True and guard["real"]["since"] == SINCE
    line = state["town"]["line"]
    assert ("The Polymarket desk's real buys are paused by the risk manager: its real record was losing money."
            in line)
    assert "The Polymarket desk is paused" not in line
    assert state["town"]["polymarket"]["paper"]["line"].endswith(" open")  # paper buys are not paused
    assert not JARGON.search(line)


def test_the_guard_block_is_typed_not_trusted(settings: Settings, make_settings: Callable[..., Settings]) -> None:
    st = desk_state()
    save(settings, st)
    assert polymarket_desk(settings, NOW)["guard"]["verdict"] == "learning"
    off = make_settings(POLYDESK_GUARD="off")
    save(off, paused_state())
    g = polymarket_desk(off, NOW)["guard"]
    assert g["on"] is False and g["paused"] is False and g["verdict"] == "losing" and g["since"] is None
    assert g["line"].startswith("Risk manager off (the owner's switch); the paper record is losing: ")
    from nightcrawler import pagestate

    assert pagestate._desk_guard({"paper": {"verdict": "<b>won</b>", "paused": "yes"}}) is None  # an unknown verdict
    junk = pagestate._desk_guard({"paper": {"verdict": "losing", "paused": "yes", "reason": 7, "line": "x" * 999,
                                            "paused_since": "12:00 UTC"},
                                  "real": {"verdict": "nope"}, "on": "maybe", "candidate": "x"})
    assert junk == {"verdict": "losing", "reason": "7", "paused": False, "since": None, "line": "x" * 479 + "…",
                    "on": True, "candidate": False, "real": None}
    since = pagestate._desk_guard({"paper": {"verdict": "losing", "paused": True, "paused_since": 5}})
    assert since is not None and since["paused"] is True and since["since"] is None  # not a string: not shown
    assert pagestate._desk_guard(None) is None and pagestate._desk_guard({"paper": None}) is None


# --------------------------------------------------------------------------- the page itself


def test_the_page_shows_the_verdict_line_and_the_tag_as_text_only(settings: Settings) -> None:
    html = render_page_html(settings)
    script = page_script(settings)
    assert "const g = pm.guard" in script and '[g, g.real].filter((v) => v && v.line)' in script
    assert 'el("p", "meta", v.line)' in script and "...verdicts" in script
    # the tag: the desk's buys paused, or only the real ones
    assert 'g.paused ? "paused by the risk manager"' in script
    assert 'g.real && g.real.paused ? "real buys paused by the risk manager"' in script
    assert 'pausedTag ? el("span", "tag", pausedTag) : null' in script
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink
    assert script.count(".replaceChildren(") == 1  # every fill still goes through put()
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)
    for text, directive in ((script, "script-src"), (style, "style-src")):  # the CSP hashes follow the edit
        digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}';" in PAGE_CSP
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', script)
    assert not [s for s in strings if " " in s and JARGON.search(s)]

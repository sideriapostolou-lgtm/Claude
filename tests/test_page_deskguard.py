"""The risk manager on the team room and the one page: the risk member lists each desk's verdict (Polymarket paper,
and Polymarket real once it has a record), the desk's own panel leads with a pause, ``money.polymarket.guard`` is
typed, the town's lines say "paused by the risk manager" while paused, and the page renders the verdict line as
text only (the CSP hashes follow the edit)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable, Iterator
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

from nightcrawler import polydesk
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.page import PAGE_CSP, render_page_html
from nightcrawler.pagestate import build_page_state, polymarket_desk
from nightcrawler.teamroom import build_team_state

LOSING = ([0.40] * 9 + [-20.0]) * 6  # 60 settled, 6 lost, -$98.40: losing


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def paused_state(*, real: list[float] | None = None, paused_real: bool = False, **kw: Any) -> dict[str, Any]:
    """The 2026-10-09 desk state with the current rule's paper record losing and the desk paused by the guard."""
    st = desk_state(**kw)
    rec: dict[str, Any] = {"paper": {"settled": 60, "won": 54, "pnl_usd": sum(LOSING), "pnls": list(LOSING)}}
    if real is not None:
        rec["real"] = {"settled": len(real), "won": sum(x > 0 for x in real), "pnl_usd": sum(real), "pnls": real}
    st["by_rule"] = {polydesk.RULE_VERSION: rec}
    reason = "60 settled, 6 lost, -$98.40 in all; even at best -$0.31 a settlement (95 % sure)"
    st["paused"] = {"at": NOW - 300, "reason": reason, "rule": polydesk.RULE_VERSION}
    if paused_real:
        st["paused_real"] = {"at": NOW - 300, "reason": "real reason", "rule": polydesk.RULE_VERSION}
    st["events"] = [{"ts": NOW - 300, "text": f"Risk manager paused the desk: {reason}", "tone": "bad"},
                    {"ts": NOW - 400, "text": "Settled: Will x happen? · lost -20.03 $ (paper)", "tone": "bad"}]
    return st


def team(ledger: Ledger, settings: Settings) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in build_team_state(ledger, settings, NOW)["panels"]}


def stat(panel: dict[str, Any], label: str) -> Any:
    return next(s["value"] for s in panel["stats"] if s["label"] == label)


# --------------------------------------------------------------------------- the team room


def test_the_risk_member_lists_each_desks_verdict(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    risk = team(ledger, settings)["risk"]  # no desk file yet: the paper desk is still learning, nothing paused
    assert risk["desks"] == [{"desk": "Polymarket paper", "verdict": "learning", "phrase": "still learning",
                              "reason": "0 of 30 settlements needed before judging; so far $0.00, 0 lost",
                              "paused": False, "line": "Risk manager (paper, still learning): 0 of 30 settlements "
                                                       "needed before judging; so far $0.00, 0 lost."}]
    assert stat(risk, "Polymarket paper") == "still learning" and "Paused" not in risk["doing"]
    save(settings, paused_state())
    by = team(ledger, settings)
    risk = by["risk"]
    assert [(d["desk"], d["verdict"], d["paused"]) for d in risk["desks"]] == [("Polymarket paper", "losing", True)]
    assert risk["desks"][0]["line"].startswith("Paused by the risk manager (paper buys stopped): 60 settled, 6 lost")
    assert stat(risk, "Polymarket paper") == "losing, paused"
    assert risk["doing"].endswith(" Paused Polymarket paper buys: the record loses money.")
    assert any(e["text"].startswith("Risk manager paused the desk: 60 settled") and e["tone"] == "bad"
               for e in risk["events"])
    assert not any(e["text"].startswith("Settled:") for e in risk["events"])  # only the risk manager's own events
    assert risk["status"] != "blocked"  # pausing a losing desk is the risk member doing its job
    predict = by["predict"]
    assert predict["doing"].startswith("Paused by the risk manager: no new paper buys, the record loses money. ")
    assert stat(predict, "Risk manager (paper)") == "losing, paused" and predict["guard"]["paper"]["paused"] is True
    for panel in (risk, predict):
        assert len(panel["doing"]) <= 160 and not JARGON.search(panel["doing"])
    json.dumps(build_team_state(ledger, settings, NOW), allow_nan=False)


def test_the_real_book_joins_the_list_once_it_has_a_record(ledger: Ledger, settings: Settings,
                                                           make_settings: Callable[..., Settings]) -> None:
    seed(ledger)
    save(settings, paused_state(real=[-0.98] * 3, paused_real=True))
    risk = team(ledger, settings)["risk"]
    assert [(d["desk"], d["verdict"], d["paused"]) for d in risk["desks"]] == [
        ("Polymarket paper", "losing", True), ("Polymarket real", "learning", True)]
    assert stat(risk, "Polymarket real") == "still learning, paused"
    assert risk["doing"].endswith(" Paused Polymarket paper and Polymarket real buys: the record loses money.")
    off = make_settings(POLYDESK_ENABLED=False)
    save(off, paused_state())
    assert team(ledger, off)["risk"]["desks"] == []  # the desk is off: nothing to judge


def test_the_desks_pause_line_names_the_buys_its_mode_makes(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    st = paused_state()
    st["mode"] = "live"  # live: a losing paper record stops the real buys
    save(settings, st)
    predict = team(ledger, settings)["predict"]
    assert predict["doing"].startswith("Paused by the risk manager: no new real buys, the record loses money. ")
    assert predict["guard"]["real"]["paused"] is True
    st = paused_state(real=[-0.98] * 3, paused_real=True)
    st["paused"] = None  # paper mode, only the real book paused: paper buys go on, nothing to lead with
    save(settings, st)
    predict = team(ledger, settings)["predict"]
    assert not predict["doing"].startswith("Paused") and stat(predict, "Risk manager (real)") == "still learning, paused"


# --------------------------------------------------------------------------- the page's data


def test_money_polymarket_carries_the_guard_and_the_town_says_paused(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    save(settings, desk_state())  # nothing paused: the guard is there, the town line says nothing of it
    state = build_page_state(ledger, settings, NOW)
    guard = state["money"]["polymarket"]["guard"]
    assert guard == {"verdict": "learning", "reason": "0 of 30 settlements needed before judging; so far $0.00, 0 lost",
                     "paused": False, "line": "Risk manager (paper, still learning): 0 of 30 settlements needed "
                                              "before judging; so far $0.00, 0 lost.",
                     "on": True, "candidate": False, "real": None}
    assert "risk manager" not in state["town"]["line"] and "risk manager" not in state["town"]["polymarket"]["paper"]["line"]
    save(settings, paused_state())
    state = build_page_state(ledger, settings, NOW)
    guard = state["money"]["polymarket"]["guard"]
    assert guard["verdict"] == "losing" and guard["paused"] is True and guard["real"] is None
    assert guard["reason"] == "60 settled, 6 lost, -$98.40 in all; even at best -$0.31 a settlement (95 % sure)"
    assert guard["line"] == f"Paused by the risk manager (paper buys stopped): {guard['reason']}."
    town = state["town"]
    assert town["polymarket"]["paper"]["line"].endswith(", 2 open; paused by the risk manager")
    assert ("The Polymarket desk is paused by the risk manager: its rule's record loses money." in town["line"])
    assert town["line"].index("paused by the risk manager") < town["line"].index("Polymarket real money")
    # the real book's own pause on its own line
    save(settings, paused_state(real=[-0.98] * 3, paused_real=True))
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["polymarket"]["guard"]["real"]["paused"] is True
    assert state["town"]["polymarket"]["real"]["line"].endswith("; real buys paused by the risk manager")
    for text in (town["line"], town["polymarket"]["paper"]["line"], guard["line"]):
        assert not JARGON.search(text), text
    json.dumps(state, allow_nan=False)


def test_the_guard_block_is_typed_not_trusted(settings: Settings, make_settings: Callable[..., Settings]) -> None:
    st = desk_state()
    save(settings, st)
    assert polymarket_desk(settings, NOW)["guard"]["verdict"] == "learning"
    off = make_settings(POLYDESK_GUARD="off")
    save(off, paused_state())
    g = polymarket_desk(off, NOW)["guard"]
    assert g["on"] is False and g["paused"] is False and g["verdict"] == "losing"
    assert g["line"].startswith("Risk manager off (the owner's switch); the paper record is losing: ")
    from nightcrawler import pagestate

    assert pagestate._desk_guard({"paper": {"verdict": "<b>won</b>", "paused": "yes"}}) is None  # an unknown verdict
    junk = pagestate._desk_guard({"paper": {"verdict": "losing", "paused": "yes", "reason": 7, "line": "x" * 999},
                                  "real": {"verdict": "nope"}, "on": "maybe", "candidate": "x"})
    assert junk == {"verdict": "losing", "reason": "7", "paused": False, "line": "x" * 319 + "…", "on": True,
                    "candidate": False, "real": None}
    assert pagestate._desk_guard(None) is None and pagestate._desk_guard({"paper": None}) is None


# --------------------------------------------------------------------------- the page itself


def test_the_page_shows_the_verdict_line_as_text_only(settings: Settings) -> None:
    html = render_page_html(settings)
    script = page_script(settings)
    assert "const g = pm.guard" in script and '[g, g.real].filter((v) => v && v.line)' in script
    assert 'el("p", "meta", v.line)' in script and '"paused by the risk manager"' in script
    assert "...verdicts" in script and "g && g.paused ?" in script
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink
    assert script.count(".replaceChildren(") == 1  # every fill still goes through put()
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)
    for text, directive in ((script, "script-src"), (style, "style-src")):  # the CSP hashes follow the edit
        digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}';" in PAGE_CSP
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', script)
    assert not [s for s in strings if " " in s and JARGON.search(s)]

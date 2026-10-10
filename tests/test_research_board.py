"""The research board (nightcrawler.research_board): a FIXED copy of what the labs found, checked here against the
research files in the repository (the module itself reads nothing: ``research/`` is not in the Docker image), and
carried by ``/api/page`` as ``research``."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import FakeClock

from nightcrawler import research_board
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.pagestate import build_page_state
from nightcrawler.research_board import LABS, RULE, VERDICTS, research_state

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_791_475_200.0
ROWS = {str(row["lab"]): row for row in LABS}

#: What each lab's own result file says (the words the row restates), checked verbatim.
EVIDENCE = {
    "Lab 1": ("**Verdict: NO WINNER.**", "None of the strategies made money on coins it had never seen",
              "Judged 2026-10-08", "**2,575 strategy settings**", "172 coins"),
    "Lab 2": ("as of 2026-10-09", "Nothing passed.", "the market drifts about -20% per trade for an outside buyer"),
    "Lab 3": ("## 2026-10-09 12:35-12:37 UTC: T3 trend following on the majors only (BTC, ETH, SOL)",
              "**FAIL on the pre-registered bar**", 'recorded as "promising, under-powered", not as an edge',
              "The verdict stands\n  as FAIL"),
    "Lab 4": tuple(f"| {h} |" for h in ("P1", "P2", "P3", "P4", "P5", "P6")) + (
        "NO EDGE on TRAIN (no cell qualifies)", "NO SPORT ALLOWED on TRAIN (no sport shows proof)", "Paper only."),
    "Lab 5": tuple(f"| {h} |" for h in ("S1", "S2", "S3")) + ("NO EDGE on TRAIN (no cell qualifies)",
                                                              "NOT RUN: TRAIN shortlisted no cell", "Paper only."),
    "Lab 6": ("| H1 |", "NO EDGE on TRAIN (no selectable cell qualifies)", "5,476 matched games", "Paper only."),
}
#: Where each result file states its own verdict: the row's verdict word must be in that phrase, word for word.
VERDICT_IN_FILE = {
    "Lab 1": "**Verdict: NO WINNER.**",
    "Lab 2": "| X5 market regime gate | TRAIN | NO EDGE | nothing qualified |",
    "Lab 3": "The verdict stands\n  as FAIL",
    "Lab 4": "| P1 | near-certain, all markets | NO EDGE on TRAIN (no cell qualifies) |",
    "Lab 5": "| S1 | threshold / range at a Binance close (above, below, between) | NO EDGE on TRAIN (no cell qualifies) |",
    "Lab 6": "NO EDGE on TRAIN (no selectable cell qualifies)",
}
#: The plain words' facts, each beside the phrase of the result file that says it (the board shows ``plain``).
PLAIN_FACTS = {
    "Lab 1": (("Every finalist lost money", "**Every finalist lost money.**"),
              ("172 coins it had never seen", "### What happened on the final exam (172 unseen coins)")),
    "Lab 2": (("Nothing passed", "Nothing passed."),
              ("an outside buyer of a fresh coin lost about 20% a trade",
               "the market drifts about -20% per trade for an outside buyer")),
    "Lab 3": (("Failed its bar", "**FAIL on the pre-registered bar**"),
              ("it beat holding the coins", "trend following on the majors beat holding them"),
              ("its lead over random timing could be luck",
               "the gap to random timing with the same\n  exposure is not statistically separable from luck"),
              ("Promising, not an edge", 'recorded as "promising, under-powered", not as an edge')),
    "Lab 4": (("No version passed on past markets", "NO EDGE on TRAIN (no cell qualifies)"),
              ("no sport did either", "NO SPORT ALLOWED on TRAIN (no sport shows proof)")),
    "Lab 5": (("No version passed on past markets", "NO EDGE on TRAIN (no cell qualifies)"),
              ("none was tried on newer data", "NOT RUN: TRAIN shortlisted no cell")),
    "Lab 6": (("No version passed", "NO EDGE on TRAIN (no selectable cell qualifies)"),
              ("5,476 past games", "5,476 matched games")),
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _trials(lab: str) -> object:
    return json.loads(_read(f"research/{lab}/trials.json"))


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def test_the_table_is_fixed_plain_and_well_formed() -> None:
    assert [row["lab"] for row in LABS] == ["Lab 1", "Lab 2", "Lab 3", "Lab 4", "Lab 5", "Lab 6"]
    for row in LABS:
        assert row["verdict"] in VERDICTS, row["lab"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row["date"])), row["lab"]
        assert isinstance(row["trials"], int) and row["trials"] > 0
        for key in ("question", "reading", "plain"):
            text = str(row[key])
            assert text and not re.search(r"[<>&]", text), (row["lab"], key)  # inserted as text only, never markup
            assert len(text) <= 130, (row["lab"], key)
        # the plain words are for a newcomer: no researcher's shorthand (hypothesis ids, splits, cells, sma50)
        assert not re.search(r"\b(?:[PSHTXVR]\d|TRAIN|VAL|TEST|cell|sma\d+|hypothes)", str(row["plain"])), row["lab"]
        assert (ROOT / str(row["source"])).is_file(), row["source"]
    state = research_state()
    assert set(state) == {"labs", "trials_total", "as_of", "rule"} and state["rule"] == RULE
    assert [set(lab) for lab in state["labs"]] == [{"lab", "question", "verdict", "date", "reading", "plain",
                                                    "trials"}] * 6
    assert state["trials_total"] == sum(row["trials"] for row in LABS) == 3005  # lab 4's P6 added 28 (2026-10-10)
    assert state["as_of"] == "2026-10-10"
    assert research_state() == state  # pure
    json.dumps(state, allow_nan=False)
    assert "PASS" not in {row["verdict"] for row in LABS}  # no rule has passed its lab (RULE_LAB_PASSED stays False)


def test_the_rule_under_the_board_is_true_of_the_table_and_never_a_real_money_claim() -> None:
    """RULE is the one sentence the board says under the table: true of the table itself (no row passed), never a
    policy about real money (the Polymarket desk bets real money, a small capped test, with lab 4's NO EDGE rule:
    the page says so in its own data, plain.real.verdict)."""
    assert RULE == "no rule has passed its lab yet" and all(row["verdict"] != "PASS" for row in LABS)
    assert "real" not in RULE and "money" not in RULE
    for rel in ("src/nightcrawler/research_board.py", "src/nightcrawler/pagestate.py", "src/nightcrawler/world3d.py"):
        assert "no edge gets real money" not in _read(rel), rel


def test_the_module_never_reads_the_research_files() -> None:
    """The copy is fixed: no file, path or JSON reading in the module (the image has no research/ to read)."""
    source = inspect.getsource(research_board)
    for banned in ("open(", "read_text", "Path(", "import json", "import os", "glob("):
        assert banned not in source, banned


@pytest.mark.parametrize("lab", sorted(EVIDENCE))
def test_each_row_restates_its_result_file(lab: str) -> None:
    row = ROWS[lab]
    text = _read(str(row["source"]))
    for phrase in EVIDENCE[lab]:
        assert phrase in text, (lab, phrase)
    # the verdict word is the file's own, word for word, where the file states its verdict
    assert VERDICT_IN_FILE[lab] in text and row["verdict"] in VERDICT_IN_FILE[lab], (lab, row["verdict"])
    assert "PASS" not in re.sub(r"PASSED weakly|passed|Pass", "", text).replace("PASS_", ""), lab
    if lab == "Lab 3":  # a direction, not an edge: FAIL, said first in the reading
        assert row["verdict"] == "FAIL" and str(row["reading"]).startswith("Failed its pre-registered bar")
    # each fact of the plain words is in the file
    for fragment, phrase in PLAIN_FACTS[lab]:
        assert fragment in str(row["plain"]), (lab, fragment)
        assert phrase in text, (lab, phrase)
    assert str(row["date"]) in text or lab in ("Lab 4", "Lab 5", "Lab 6"), lab  # labs 4-6: dated by their ledgers


def test_the_counted_trials_and_dates_are_the_ledgers() -> None:
    # lab 1: the judge's report counts the logged strategy settings; lab 2's ledger records the same baseline
    lab2 = _trials("lab2")
    assert isinstance(lab2, dict) and lab2["baseline"]["lab_wave1_logged_configs"] == ROWS["Lab 1"]["trials"] == 2575
    assert len(lab2["configs"]) == ROWS["Lab 2"]["trials"]  # every distinct (hypothesis, params) is one trial
    lab3 = _trials("lab3")
    assert isinstance(lab3, dict) and len(lab3["configs"]) == ROWS["Lab 3"]["trials"]
    assert {c["hypothesis"] for c in lab3["configs"].values()} == {"T1", "T2", "T3", "V1", "X1", "R1"}
    assert sum(c["hypothesis"] == "T3" for c in lab3["configs"].values()) == 5  # T3: 5 counted trials (PLAN 4)
    assert max(c["first_utc"][:10] for c in lab3["configs"].values()) == ROWS["Lab 3"]["date"]
    for lab, hyps in (("lab4", {"P1", "P2", "P3", "P4", "P5", "P6", "C1"}), ("lab5", {"S1", "S2", "S3"}), ("lab6", {"H1"})):
        cells = _trials(lab)
        row = ROWS["Lab " + lab[3:]]
        assert isinstance(cells, list) and len(cells) == row["trials"], lab  # every evaluated cell is a trial
        assert {c["hyp"] for c in cells} == hyps and {c["split"] for c in cells} == {"train"}, lab
        assert max(c["utc"][:10] for c in cells) == row["date"], lab


def test_api_page_carries_the_research_block(ledger: Ledger, settings: Settings) -> None:
    state = build_page_state(ledger, settings, NOW)
    assert state["research"] == research_state()
    assert state["research"]["labs"][2]["verdict"] == "FAIL" and state["research"]["trials_total"] == 3005
    assert all(lab["verdict"] != "PASS" for lab in state["research"]["labs"])

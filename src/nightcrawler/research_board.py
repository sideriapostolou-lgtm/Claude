"""What the research labs found, as a FIXED table the page can show (owner: O6; ``/api/page`` -> ``research``).

The labs' verdicts are facts recorded in the repository (``research/lab*/RESULTS*.md`` and each lab's trial ledger
``trials.json``), but ``research/`` is not shipped in the Docker image (the image copies ``src/`` only), so this module
carries a small fixed copy: one row per lab with the question in plain words, the verdict word, the date of the
verdict, a one-line reading and the lab's counted trials. Nothing here is computed or read from disk at run time;
``tests/test_research_board.py`` reads the research files and checks that every row still matches them (the verdict
words, the dates, the counted trials), so the table cannot drift from the record without a failing test.

Verdict words (:data:`VERDICTS`): ``NO EDGE`` (nothing qualified, or every finalist lost out of sample), ``PROMISING``
(a consistent direction that failed its pre-registered evidence bar: lab 3's T3), ``PASS`` (a rule passed its lab:
none has). The rule the labs enforce, and the page repeats, is :data:`RULE`: no edge gets real money.

``trials`` is the lab's own ledger count: lab 1's logged strategy settings (the judge's report), lab 2's distinct
``(hypothesis, params)`` configs, lab 3's configs, labs 4-6's evaluated cells (controls included: every evaluated cell
is a counted trial for the deflated Sharpe ratio). ``trials_total`` is their sum.
"""

from __future__ import annotations

from typing import Any

__all__ = ["LABS", "RULE", "VERDICTS", "research_state"]

#: The verdict words a row may carry (the page colours them: red, amber, green).
VERDICTS: tuple[str, ...] = ("NO EDGE", "PROMISING", "PASS")
#: The labs' rule, repeated under the board.
RULE = "no edge gets real money"

#: One row per lab, in lab order. ``source`` names the file in the repository the row restates.
LABS: tuple[dict[str, Any], ...] = (
    {"lab": "Lab 1", "question": "Can any memecoin entry rule make money on coins it has never seen?",
     "verdict": "NO EDGE", "date": "2026-10-08",
     "reading": "No winner: every finalist lost money on the final exam of 172 unseen coins",
     "trials": 2575, "source": "research/lab/RESULTS.md"},
    {"lab": "Lab 2", "question": "Do trade-flow and wallet signals on fresh pump.fun coins give an entry edge?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "Nothing passed: every hypothesis killed, no edge or under-powered; the market drifts about "
                "-20% a trade for an outside buyer",
     "trials": 192, "source": "research/lab2/RESULTS_WAVE2.md"},
    {"lab": "Lab 3", "question": "Does a 50-day trend rule on BTC, ETH and SOL beat holding them?",
     "verdict": "PROMISING", "date": "2026-10-09",
     "reading": "sma50 on the majors beat holding in every period but failed the pre-registered bar: promising, "
                "under-powered, not an edge",
     "trials": 24, "source": "research/lab3/RESULTS.md"},
    {"lab": "Lab 4", "question": "Does buying near-certain outcomes at 97-99c on prediction markets pay after fees?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "P1-P5: no cell qualifies on TRAIN; paper only",
     "trials": 126, "source": "research/lab4/RESULTS.md"},
    {"lab": "Lab 5", "question": "Can a crypto price-market specialist (fair value from spot and volatility) beat "
                                 "Polymarket's prices?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "S1-S3: no cell qualifies on TRAIN; VAL not run",
     "trials": 36, "source": "research/lab5/RESULTS.md"},
    {"lab": "Lab 6", "question": "Do Polymarket game prices sit far enough below Pinnacle's no-vig line to buy?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "H1: no selectable cell qualifies on TRAIN over 5,476 matched games",
     "trials": 24, "source": "research/lab6/RESULTS.md"},
)


def research_state() -> dict[str, Any]:
    """``/api/page``'s ``research`` block: ``{labs: [{lab, question, verdict, date, reading, trials}], trials_total,
    as_of, rule}``. Fixed (no disk, no network): the same answer every call. ``as_of`` is the newest verdict date."""
    labs = [{key: row[key] for key in ("lab", "question", "verdict", "date", "reading", "trials")} for row in LABS]
    return {"labs": labs, "trials_total": sum(int(row["trials"]) for row in LABS),
            "as_of": max(str(row["date"]) for row in LABS), "rule": RULE}

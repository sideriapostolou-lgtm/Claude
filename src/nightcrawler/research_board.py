"""What the research labs found, as a FIXED table the page can show (owner: O6; ``/api/page`` -> ``research``).

The labs' verdicts are facts recorded in the repository (``research/lab*/RESULTS*.md`` and each lab's trial ledger
``trials.json``), but ``research/`` is not shipped in the Docker image (the image copies ``src/`` only), so this module
carries a small fixed copy: one row per lab with the question in plain words, the verdict word, the date of the
verdict, the record's own one-line reading, the same in plain words for a newcomer (``plain``, what the 3D world's
board shows) and the lab's counted trials. Nothing here is computed or read from disk at run time;
``tests/test_research_board.py`` reads the research files and checks that every row still matches them (the verdict
words, the plain words' facts, the dates, the counted trials), so the table cannot drift from the record without a
failing test.

Verdict words (:data:`VERDICTS`) are each lab's own: ``NO WINNER`` (lab 1's judge: every finalist lost out of
sample), ``NO EDGE`` (nothing qualified), ``FAIL`` (lab 3's T3: a consistent direction that failed its pre-registered
evidence bar, recorded as "promising, under-powered", not as an edge), ``PASS`` (a rule passed its lab: none has).
:data:`RULE` is the one sentence the board says under the table, and it is true of the table itself: no rule has
passed its lab. It is NOT a policy about real money: the Polymarket desk's real bets (a small, capped test the owner
chose, on lab 4's rule) are said by the page's own data (``plain.real.verdict``), never by this module.

``trials`` is the lab's own ledger count: lab 1's logged strategy settings (the judge's report), lab 2's distinct
``(hypothesis, params)`` configs, lab 3's configs, labs 4-6's evaluated cells (controls included: every evaluated cell
is a counted trial for the deflated Sharpe ratio). ``trials_total`` is their sum.
"""

from __future__ import annotations

from typing import Any

__all__ = ["LABS", "RULE", "VERDICTS", "research_state"]

#: The verdict words a row may carry, each a lab's own (the page colours them: slate, slate, slate, green).
VERDICTS: tuple[str, ...] = ("NO WINNER", "NO EDGE", "FAIL", "PASS")
#: The board's sentence under the table: true while no row says PASS (the test keeps it so).
RULE = "no rule has passed its lab yet"

#: One row per lab, in lab order. ``source`` names the file in the repository the row restates.
LABS: tuple[dict[str, Any], ...] = (
    {"lab": "Lab 1", "question": "Can any memecoin entry rule make money on coins it has never seen?",
     "verdict": "NO WINNER", "date": "2026-10-08",
     "reading": "No winner: every finalist lost money on the final exam of 172 unseen coins",
     "plain": "Every finalist lost money on 172 coins it had never seen.",
     "trials": 2575, "source": "research/lab/RESULTS.md"},
    {"lab": "Lab 2", "question": "Do trade-flow and wallet signals on fresh pump.fun coins give an entry edge?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "Nothing passed: every hypothesis killed, no edge or under-powered; the market drifts about "
                "-20% a trade for an outside buyer",
     "plain": "Nothing passed: an outside buyer of a fresh coin lost about 20% a trade.",
     "trials": 192, "source": "research/lab2/RESULTS_WAVE2.md"},
    {"lab": "Lab 3", "question": "Does a 50-day trend rule on BTC, ETH and SOL beat holding them?",
     "verdict": "FAIL", "date": "2026-10-09",
     "reading": "Failed its pre-registered bar; promising, under-powered, not an edge: sma50 on the majors beat "
                "holding in every period",
     "plain": "Failed its bar: it beat holding the coins, but its lead over random timing could be luck. "
              "Promising, not an edge.",
     "trials": 24, "source": "research/lab3/RESULTS.md"},
    {"lab": "Lab 4", "question": "Does buying near-certain outcomes at 97-99c on prediction markets pay after fees?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "P1-P5: no cell qualifies on TRAIN; paper only",
     "plain": "No version passed on past markets: it was not shown to pay after fees.",
     "trials": 126, "source": "research/lab4/RESULTS.md"},
    {"lab": "Lab 5", "question": "Can a crypto specialist (fair value from spot and volatility) beat Polymarket's "
                                 "prices?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "S1-S3: no cell qualifies on TRAIN; VAL not run",
     "plain": "No version passed on past markets, so none was tried on newer data.",
     "trials": 36, "source": "research/lab5/RESULTS.md"},
    {"lab": "Lab 6", "question": "Do Polymarket game prices sit far enough below Pinnacle's no-vig line to buy?",
     "verdict": "NO EDGE", "date": "2026-10-09",
     "reading": "H1: no selectable cell qualifies on TRAIN over 5,476 matched games",
     "plain": "No version passed over 5,476 past games.",
     "trials": 24, "source": "research/lab6/RESULTS.md"},
)


def research_state() -> dict[str, Any]:
    """``/api/page``'s ``research`` block: ``{labs: [{lab, question, verdict, date, reading, plain, trials}],
    trials_total, as_of, rule}``. Fixed (no disk, no network): the same answer every call. ``as_of`` is the newest
    verdict date."""
    keys = ("lab", "question", "verdict", "date", "reading", "plain", "trials")
    labs = [{key: row[key] for key in keys} for row in LABS]
    return {"labs": labs, "trials_total": sum(int(row["trials"]) for row in LABS),
            "as_of": max(str(row["date"]) for row in LABS), "rule": RULE}

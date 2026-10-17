#!/usr/bin/env python3
"""Generate the playbook (docs/EXPERIENCE.md §7.1) from the grounded craft rules: Python 3 standard library only.

    python3 scripts/gen_playbook.py            # write src/nightcrawler/experience/playbook.json
    python3 scripts/gen_playbook.py --check    # exit 1 if the committed file is out of date

The source is docs/EXPERIENCE_GROUNDED.md: its tables hold the 91 craft rules merged into 62 rows (G01-G62). Each
row becomes one entry; N4 item 9 (the bot's default dip-rebound strategy, which is folklore in the bot but has no
G row) is added as entry ``N4.9``. The file changes only when GROUNDED does: never edit it by hand.

What is PARSED from each table row: ``ids`` (the merged rule ids), ``section``, ``owners`` (the ``[Owner]`` tag,
as the page's member ids; "Jev" is the ``judge``), ``rule`` (the grounded rule, markdown removed), ``grounded``
(the bold status codes: AI already implemented, P partial, M missing, C contradicted by our data, U untestable),
``rule_in_bot`` (yes | partial | no, from those codes), ``where`` (where in the code today), ``refs`` (what
already covers it) and ``priority`` (the first of P0-P3 in the priority cell).

What is WRITTEN DOWN here, per row, because a table cell is not plain words: ``name`` (what the entry tracks;
for an ``in_bot_*`` status, the behaviour the bot has today), ``evidence`` (one line) and ``track`` (E, F, P, R
or M; see :data:`TRACKS`). A row without them is refused, so a new GROUNDED row can never slip in silently.

``status`` is the INITIAL registry status of §7.1. The explicit ones come from §7.1 and §7.2 (contradicted,
unsupported, correctness fixes, under test); every other row follows its priority: P0 a correctness fix, P1
queued, P2 waiting for data when its priority names D3 or D4 (else a candidate), P3 parked. Later statuses
(lab verdicts, forward tests) arrive as receipted events and packs, never as edits to this file. The playbook is
static data for the page and the experience team: nothing that trades reads it.

Exit codes: 0 written (or up to date with ``--check``), 1 out of date, 2 a source problem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "EXPERIENCE_GROUNDED.md"
OUT = ROOT / "src" / "nightcrawler" / "experience" / "playbook.json"
SCHEMA = 1
COLUMNS = 8  # #, IDs, grounded rule [owner], status, where in code today, already covered by, data + as-of, priority

#: The registry statuses of docs/EXPERIENCE.md §7.1, in plain words for the page.
STATUSES = {
    "in_bot_contradicted": "in the bot, contradicted by our data",
    "in_bot_unsupported": "in the bot, untested",
    "fix_engineering": "a correctness fix, waiting for a reviewed change",
    "candidate": "an idea, not tested yet",
    "queued": "next in line for a test",
    "testing": "being tested",
    "validated": "tested and kept",
    "rejected": "tested and dropped",
    "blocked_data": "waiting for data",
    "parked": "parked: low value for now",
}
#: Which kind of change an entry would be (§7.2-§7.4). Only a human-reviewed pull request ever changes the bot.
TRACKS = {
    "E": "a correctness or universe fix, by a reviewed change",
    "F": "a loss-avoiding filter, veto or exit",
    "P": "an entry that could make money: the strict exam first",
    "R": "risk and sizing: human-reviewed code only, never learnable",
    "M": "how the team is measured",
}
#: The [Owner] tags of GROUNDED, as the page's member ids.
OWNERS = {"Cocoon": "cocoon", "Broker": "broker", "Crawler": "crawler", "Strategy": "strategy", "Radar": "radar",
          "Coach": "coach", "Risk": "risk", "Jev": "judge"}
#: Initial statuses fixed by docs/EXPERIENCE.md §7.1 (N4 with item 1 split in two) and §7.2 (Track E).
STATUS_OVERRIDES = {
    # contradicted: hard fails on graduates, address serial launchers, stop fills at the stop price,
    # 20% sizing with a daily limit that is not a bound, the 20-30 trades go-live text, the default dip-rebound
    "G02": "in_bot_contradicted", "G06": "in_bot_contradicted", "G22": "in_bot_contradicted",
    "G38": "in_bot_contradicted", "G39": "in_bot_contradicted", "N4.9": "in_bot_contradicted",
    # unsupported: concentration caps, creator-watch, paintable confirmation, socials in Jev's prompt, sell half
    "G07": "in_bot_unsupported", "G20": "in_bot_unsupported", "G15": "in_bot_unsupported",
    "G09": "in_bot_unsupported", "G30": "in_bot_unsupported",
    # Track E and the separate P0 safety pull requests (§7.2, §11)
    "G01": "fix_engineering", "G12": "fix_engineering", "G23": "fix_engineering", "G33": "fix_engineering",
    "G40": "fix_engineering",
    # registered in the lab: hypothesis G1 (its classes and its airdrop sign)
    "G04": "testing", "G14": "testing",
}
#: Plain words written down per row: (name, one-line evidence, track).
WORDS: dict[str, tuple[str, str, str]] = {
    "G01": ("Skip Mayhem coins",
            "No Mayhem check in the bot; 410 of 1,783 graduates (23%) were Mayhem coins no test covered", "E"),
    "G02": ("Hard fails on token authorities, extensions and pool lock",
            "Genuine graduates pass them every time (1,542 of 1,548; 100 of 100 by RPC): they carry no information",
            "F"),
    "G03": ("Measure and exit on the coin's main pool",
            "13 of 1,783 graduates had a second pool; a second venue once cut the round trip to 0.40%", "E"),
    "G04": ("Class each graduate: factory, operator, completed, organic",
            "Lab hypothesis G1 is registered; 450 census coins: 183 factory, 34 operator, 19 completed, 193 organic",
            "F"),
    "G05": ("Wait until a repeat completer has sold out",
            "Needs wallet trade data that is not downloaded yet; 24.8% of slower graduates had a completer", "P"),
    "G06": ("Serial-launcher check by creator address",
            "Only 7 of 1,145 creators launched twice; the launch counter counts platforms, not people", "F"),
    "G07": ("Holder concentration caps as a rug shield",
            "Airdrops spread 0.036% over 2,200 wallets and farm rugs came from 9-13% holders (9 rugs)", "F"),
    "G08": ("Grade every rug-filter and radar veto",
            "Rejections are taped with rule ids, but no veto has been graded against its shadow outcome", "M"),
    "G09": ("Jev weighs socials and paid promotion",
            "Jev's prompt asks it to; untested, and they count only if a test shows +5 points over chance", "F"),
    "G10": ("Veto coins held by wallets with a rug habit",
            "Needs wallet position data: 0 coins downloaded so far", "F"),
    "G11": ("Never buy because a famous wallet bought",
            "No such trigger exists in the bot; no dated wallet lists exist to test a crowding veto", "F"),
    "G12": ("Measure coin age from graduation, not creation",
            "A slow graduate can be bought at graduation; random entries at 0-30 min lost 10.0% vs 6.9% at 2-6 h",
            "E"),
    "G13": ("Enter once insiders' cheap supply is spent (S1)",
            "Lab hypothesis S1 is written but waits for wallet trade data; it ran on synthetic data only", "P"),
    "G14": ("Refuse coins with free airdropped supply",
            "Tested inside lab hypothesis G1 as a sell burst; one factory dump came 16 min after creation", "F"),
    "G15": ("Buy confirmation on raw volume and buy/sell counts",
            "Dust bots paint both (dust share 0.80 on instant clones vs 0.09 on slow coins); the rule is untested",
            "F"),
    "G16": ("Count real buyers, not raw trades",
            "Factories run a median 341 trades a minute, so raw counts mislead; waits for lab data", "F"),
    "G17": ("No entry right after a big creator sale",
            "Rare in the bot's window: 0 of 9 farm rugs came from the creator", "F"),
    "G18": ("Refuse coins bought up by brand-new wallets",
            "Needs per-wallet history queries that are not written yet", "F"),
    "G19": ("Know our speed from decision to fill",
            "Never measured; lab replays 1-5 s apart were identical, so speed is probably not the weak point", "M"),
    "G20": ("Creator-watch as a rug alarm",
            "0 of 9 rugs came from the creator (too few to grade); a dump of 2,200 small sells is invisible to it",
            "F"),
    "G21": ("A danger exit must come before the crash",
            "Every radar flag exits today; farm rugs were one swap and a factory dump was over in 26 s", "F"),
    "G22": ("Stop-loss fills at the stop price in the simulators",
            "Rug stops booked at -51% to -59% really filled at -84% to -97% (36 swap windows, 9 rugs)", "E"),
    "G23": ("Size for the -90% gap, not the -18% stop",
            "At 20% sizing one rug costs about 19% of the money, not the 3.6% the stop implies", "R"),
    "G24": ("Test a wide crash stop plus a time stop",
            "7-8 of 10 test trades of the dip strategies ended at the -18% stop", "F"),
    "G25": ("Confirm ordinary stops on a closed candle",
            "Stops fire on a touch of the 10 s price; testing it needs trade-by-trade data", "F"),
    "G26": ("Set the longest hold from the crash risk by age",
            "Instant coins were stopped out 43% of the time at 0-30 min, 8% at 30-120 min, 1.2% at 2-6 h", "F"),
    "G27": ("Exit stale trades that never moved",
            "7,631 of 9,434 random trades ended at the time limit, median -5.1%: about the trading costs", "F"),
    "G28": ("A fixed target instead of a trailing stop",
            "On real swaps every +40% target filled at about +26%", "F"),
    "G29": ("Sell into bursts of real buying", "Exploratory: nothing measured yet", "F"),
    "G30": ("Sell half at +40%",
            "In the bot but never tested against a full exit or no partial; worth about 0.5 points either way", "F"),
    "G31": ("Exit when real buying collapses",
            "Part of lab hypothesis S1's exits; waits for lab data", "F"),
    "G32": ("Exit when the dip's low breaks",
            "The dip's low is computed at entry and never used at exit", "F"),
    "G33": ("Get out when the price feed goes blind",
            "A missing price leaves only the 2-hour time limit, and the blind state coincides with rugs", "E"),
    "G34": ("A server-side -50% stop", "Live only; the share of unwatched gaps is not measured yet", "R"),
    "G35": ("Sell in one swap; alert on a bad route",
            "Exits are one swap already; the re-quote and the alert are missing", "E"),
    "G36": ("Grade exits against random exit times",
            "No placebo exits yet; random entries with our exits lost 6.4% a trade", "M"),
    "G37": ("Stand down when the meme market breaks",
            "Results by hour swing from -59% to +26% with no pattern that holds across days", "R"),
    "G38": ("20% sizing with a daily limit that is not a bound",
            "In simulation the 1-in-10 worst day loses 41-43% against a nominal 20% limit", "R"),
    "G39": ("Go live after 20-30 good paper trades",
            "A strategy with no real advantage passes that test about half the time at 30 trades", "R"),
    "G40": ("Get the token-account deposit back",
            "About 1.1 points of every $20 round trip go to a deposit that is never refunded", "E"),
    "G41": ("One open trade per operator family",
            "All 12 test trades of one strategy came from the same farm", "R"),
    "G42": ("Cap the entry price impact near 0.75%",
            "At $100k and up a $20 trade moves the price about 0.1-0.3%, so the cap rarely binds", "R"),
    "G43": ("Step live size up slowly", "Only matters once something shows a real advantage", "R"),
    "G44": ("Sweep gains above about $125 to the owner",
            "Today the $150 wallet cap stops the bot once it does well", "R"),
    "G45": ("Judge decay on per-trade returns",
            "At 20% sizing even a real +3% strategy hits a 30% drawdown in simulation", "M"),
    "G46": ("No tilt or streak sizing",
            "After 3 losses the next trade averaged -6.7% vs -6.5% overall (one day of data)", "R"),
    "G47": ("Jev's no-votes must catch more than chance", "Never graded: vetoed coins are not followed up", "F"),
    "G48": ("Clean the trade data before any wallet rule",
            "Mostly done in research; a few exclusion lists and checks are still missing", "M"),
    "G49": ("Trip wires on protocol constants",
            "PumpSwap events grew 8 bytes on Oct 3; only one constant is checked today", "M"),
    "G50": ("A post-mortem for every trade",
            "Not built yet; the parts of each result must add up to the trade", "M"),
    "G51": ("Call a loss a mistake only against matched trades",
            "Re-entry after a stop looked 4.6 points worse raw but 0.4 [-1.8, +1.1] matched: it was coin age", "M"),
    "G52": ("Hunt for bugs after an unusually bad loss",
            "Every material error the lab audits found so far was a pipeline error", "M"),
    "G53": ("Count independent situations, not raw reps",
            "16 random entries in one coin are worth about 5.4 independent ones", "M"),
    "G54": ("Practise only where the pattern holds day to day",
            "The farm's crash share moved from 22-24% to 33% between splits", "M"),
    "G55": ("Grade decisions by expected value, never by one result",
            "A rule with no advantage still comes out ahead on 79% of single trades", "M"),
    "G56": ("Seal a numeric plan before each entry",
            "A simple per-situation forecast of stop-outs scored 0.19 over no forecast, but was miscalibrated", "M"),
    "G57": ("Sealed exams for every skill claim",
            "One strategy made +14% in practice, -5.4% on its exam and -17.7% on real swaps", "M"),
    "G58": ("One report card per member against a random stand-in",
            "Being built: a card says no measurable skill until its band clears chance", "M"),
    "G59": ("Score each fill by its shortfall",
            "Entry drift averaged +0.2% at 2 s; rug stop losses are a rug problem, not an execution one", "M"),
    "G60": ("Measure which new coins the crawler sees",
            "The bot watches at most 15 of about 1,200 graduates a day; coverage is not measured", "M"),
    "G61": ("State rug odds as probabilities", "Pass or fail only today", "M"),
    "G62": ("Spend practice on the weakest situations",
            "Random entries 0-30 min after an instant graduation lost 15.7% (a situation the bot never trades)",
            "M"),
}
#: N4 item 9: the bot's default strategy is folklore our data contradicts, and has no G row of its own.
DEFAULT_STRATEGY = {
    "id": "N4.9", "ids": [], "section": "Folklore already inside the bot", "owners": ["strategy"],
    "name": "The default dip-rebound strategy",
    "evidence": "It lost on every split and every stress test; its one exam trade lost 22.1%",
    "track": "P", "priority": None, "grounded": [],
    "where": "strategy.entry_signal (dip-rebound); DIP_PCT and the other strategy Settings",
    "refs": "RESULTS F1 (the dip strategies); the lab1 judge's one TEST trade",
}
_ROW = re.compile(r"^\| (G\d\d) \|")
_CODE = re.compile(r"(?<![\w-])(AI|P|M|C|U)(?![\w-])")
_PRIORITY = re.compile(r"\bP([0-3])\b")


def _plain(cell: str) -> str:
    """Markdown removed: bold markers and backticks."""
    return re.sub(r"\s+", " ", cell.replace("**", "").replace("`", "")).strip()


def _codes(cell: str) -> list[str]:
    """The status codes named in the cell's bold segments, in order, without repeats."""
    out: list[str] = []
    for segment in re.findall(r"\*\*(.+?)\*\*", cell):
        for code in _CODE.findall(segment):
            if code not in out:
                out.append(code)
    return out


def _in_bot(codes: list[str]) -> str:
    kinds = {c for c in codes if c in ("AI", "P", "M")}
    if kinds == {"AI"}:
        return "yes"
    if kinds == {"M"} or not kinds:
        return "no"
    return "partial"


def _status(rid: str, priority: str | None, priority_cell: str) -> str:
    if rid in STATUS_OVERRIDES:
        return STATUS_OVERRIDES[rid]
    if priority == "P0":
        return "fix_engineering"
    if priority == "P1":
        return "queued"
    if priority == "P2":
        return "blocked_data" if re.search(r"\bD[34]\b", priority_cell) else "candidate"
    return "parked"


def _rows(text: str) -> list[tuple[str, list[str]]]:
    """``(section, cells)`` for every table row G01-G62, in order."""
    rows, section = [], ""
    for line in text.splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
        if not _ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) != COLUMNS:
            raise ValueError(f"{cells[0]}: {len(cells)} columns, expected {COLUMNS}")
        rows.append((section, cells))
    return rows


def _entry(section: str, cells: list[str]) -> dict[str, object]:
    rid, ids, rule, status_cell, where, refs, _data, priority_cell = cells
    tag = re.match(r"\[([^\]]+)\]\s*", rule)
    if tag is None:
        raise ValueError(f"{rid}: the rule has no [Owner] tag")
    try:
        owners = [OWNERS[name.strip()] for name in tag.group(1).split("/")]
    except KeyError as exc:
        raise ValueError(f"{rid}: unknown owner {exc}") from None
    name, evidence, track = WORDS[rid]
    first_bold = re.findall(r"\*\*(.+?)\*\*", priority_cell)
    found = _PRIORITY.search(first_bold[0] if first_bold else priority_cell)
    priority = f"P{found.group(1)}" if found else None
    codes = _codes(status_cell)
    return {
        "id": rid, "ids": [i.strip() for i in ids.split(",")], "section": section, "name": name,
        "owner": owners[0], "owners": owners, "status": _status(rid, priority, priority_cell), "track": track,
        "priority": priority, "grounded": codes, "rule_in_bot": _in_bot(codes), "evidence": evidence,
        "rule": _plain(rule[tag.end():]), "where": _plain(where), "refs": _plain(refs),
    }


def _default_strategy(text: str) -> dict[str, object]:
    item = re.search(r"^9\. (\*\*The default dip-rebound itself\.\*\*.*(?:\n {3}\S.*)*)", text, flags=re.M)
    if item is None:
        raise ValueError("N4.9: GROUNDED no longer lists the default dip-rebound (N4 item 9)")
    entry = dict(DEFAULT_STRATEGY)
    entry.update(owner="strategy", status=STATUS_OVERRIDES["N4.9"], rule_in_bot="yes", rule=_plain(item.group(1)))
    keys = ("id", "ids", "section", "name", "owner", "owners", "status", "track", "priority", "grounded",
            "rule_in_bot", "evidence", "rule", "where", "refs")
    return {k: entry[k] for k in keys}


def build(text: str) -> dict[str, object]:
    """The playbook for GROUNDED's ``text``. Raises ValueError on a row it cannot place."""
    rows = _rows(text)
    found = [cells[0] for _, cells in rows]
    expected = sorted(WORDS)
    if found != expected:
        missing, extra = sorted(set(expected) - set(found)), sorted(set(found) - set(expected))
        raise ValueError(f"GROUNDED rows differ from the written-down words: missing {missing}, new {extra} "
                         "(write each new row's name, evidence and track in scripts/gen_playbook.py)")
    rules = [_entry(section, cells) for section, cells in rows] + [_default_strategy(text)]
    for r in rules:
        if r["status"] not in STATUSES or r["track"] not in TRACKS:
            raise ValueError(f"{r['id']}: unknown status or track")
    return {
        "schema": SCHEMA, "generated_by": "scripts/gen_playbook.py", "source": "docs/EXPERIENCE_GROUNDED.md",
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "statuses": STATUSES, "tracks": TRACKS, "rules": rules,
    }


def render(playbook: dict[str, object]) -> str:
    return json.dumps(playbook, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--source", type=Path, default=SOURCE, help="the grounded rules (markdown)")
    parser.add_argument("--out", type=Path, default=OUT, help="the playbook to write or check")
    parser.add_argument("--check", action="store_true", help="exit 1 if --out differs from a fresh generation")
    args = parser.parse_args(argv)
    try:
        fresh = render(build(args.source.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != fresh:
            print(f"{args.out} is out of date: run python3 scripts/gen_playbook.py")
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(fresh, encoding="utf-8")
    print(f"wrote {args.out}: {len(json.loads(fresh)['rules'])} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())

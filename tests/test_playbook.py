"""The playbook (docs/EXPERIENCE.md §7.1): ``src/nightcrawler/experience/playbook.json`` is GENERATED from
docs/EXPERIENCE_GROUNDED.md by ``scripts/gen_playbook.py``, one entry per grounded row G01-G62 plus the bot's
default strategy (N4 item 9), with the initial statuses of §7.1. It is static data: nothing that trades reads it."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from nightcrawler.page import MEMBERS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gen_playbook.py"
SOURCE = ROOT / "docs" / "EXPERIENCE_GROUNDED.md"
PLAYBOOK = ROOT / "src" / "nightcrawler" / "experience" / "playbook.json"
STATUSES = {"in_bot_contradicted", "in_bot_unsupported", "fix_engineering", "candidate", "queued", "testing",
            "validated", "rejected", "blocked_data", "parked"}
ENTRY_KEYS = {"id", "ids", "section", "name", "owner", "owners", "status", "track", "priority", "grounded",
              "rule_in_bot", "evidence", "rule", "where", "refs"}
#: docs/EXPERIENCE.md §8.4: never in an owner-facing string (word boundaries, any case).
BANNED = re.compile(r"\b(?:expert|pro|master|level|xp|rank|elite|guaranteed|smart money|win rate|winning streak|"
                    r"profitable|profit|studied|experienced|edge|learned|money added|proven|beats|improving|"
                    r"improved)\b", re.IGNORECASE)
#: The one-page dashboard's plain-words rule (tests/test_page.py).
JARGON = re.compile(r"\b(?:bps|lamports?|mint|slippage|mcap|prefilter|kv|ledger)\b", re.IGNORECASE)


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_playbook", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen() -> ModuleType:
    return load_script()


@pytest.fixture(scope="module")
def book() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PLAYBOOK.read_text(encoding="utf-8"))
    return data


def by_id(book: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in book["rules"]}


def run(*args: object) -> subprocess.CompletedProcess[str]:
    """Standard library only (``-I -S``): the generator must not need nightcrawler or site-packages."""
    return subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), *map(str, args)], capture_output=True,
                          text=True, timeout=60)


# --------------------------------------------------------------------------- generated, never hand-edited


def test_the_committed_playbook_is_exactly_what_the_generator_makes(gen: ModuleType) -> None:
    """Hand edits are impossible to keep: the file must equal a fresh generation from GROUNDED, byte for byte."""
    assert PLAYBOOK.read_text(encoding="utf-8") == gen.render(gen.build(SOURCE.read_text(encoding="utf-8")))
    result = run("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fails_when_grounded_changes_and_the_playbook_was_not_regenerated(tmp_path: Path) -> None:
    source = tmp_path / "grounded.md"
    source.write_text(SOURCE.read_text(encoding="utf-8").replace("Skip Mayhem coins", "Skip Mayhem-ish coins"),
                      encoding="utf-8")
    out = tmp_path / "playbook.json"
    out.write_text(PLAYBOOK.read_text(encoding="utf-8"), encoding="utf-8")
    stale = run("--source", source, "--out", out, "--check")
    assert stale.returncode == 1 and "out of date" in stale.stdout + stale.stderr
    fresh = run("--source", source, "--out", out)
    assert fresh.returncode == 0, fresh.stderr
    assert run("--source", source, "--out", out, "--check").returncode == 0
    regenerated = json.loads(out.read_text(encoding="utf-8"))
    assert "Skip Mayhem-ish coins" in by_id(regenerated)["G01"]["rule"]
    assert regenerated["source_sha256"] != json.loads(PLAYBOOK.read_text(encoding="utf-8"))["source_sha256"]


def test_a_grounded_row_without_plain_words_is_refused(gen: ModuleType) -> None:
    """A new GROUNDED row needs its plain-words name and evidence written down first: never a silent gap."""
    text = SOURCE.read_text(encoding="utf-8")
    g62 = next(line for line in text.splitlines() if line.startswith("| G62 |"))
    with pytest.raises(ValueError, match="G63"):
        gen.build(text.replace(g62, g62 + "\n" + g62.replace("| G62 |", "| G63 |")))
    with pytest.raises(ValueError, match="G62"):
        gen.build(text.replace(g62 + "\n", ""))
    with pytest.raises(ValueError, match="columns"):
        gen.build(text.replace(g62, g62.replace(" | [Coach]", " ; [Coach]")))


def test_the_generator_uses_only_the_standard_library() -> None:
    imported = set(re.findall(r"^(?:from|import) ([a-z_]+)", SCRIPT.read_text(encoding="utf-8"), flags=re.M))
    assert imported and all(name in sys.stdlib_module_names or name == "__future__" for name in imported), imported
    assert "nightcrawler" not in imported


# --------------------------------------------------------------------------- one entry per grounded row


def test_one_entry_per_grounded_row_plus_the_default_strategy(book: dict[str, Any]) -> None:
    ids = [r["id"] for r in book["rules"]]
    assert ids == [f"G{n:02d}" for n in range(1, 63)] + ["N4.9"]
    assert sum(len(r["ids"]) for r in book["rules"]) == 91  # the 91 craft rules, merged into 62 rows
    assert book["schema"] == 1 and book["source"] == "docs/EXPERIENCE_GROUNDED.md"
    assert book["generated_by"] == "scripts/gen_playbook.py" and re.fullmatch(r"[0-9a-f]{64}", book["source_sha256"])
    assert set(book["statuses"]) == STATUSES and set(book["tracks"]) == {"E", "F", "P", "R", "M"}
    for r in book["rules"]:
        assert set(r) == ENTRY_KEYS, r["id"]
        assert r["status"] in STATUSES and r["track"] in book["tracks"], r["id"]
        assert r["rule"] and r["where"] and r["evidence"] and r["name"], r["id"]


def test_fields_are_parsed_from_the_grounded_table(book: dict[str, Any]) -> None:
    rules = by_id(book)
    g01 = rules["G01"]
    assert (g01["ids"], g01["section"], g01["owner"], g01["owners"]) == (
        ["RA-02"], "Safety and universe", "cocoon", ["cocoon"])
    assert (g01["grounded"], g01["rule_in_bot"], g01["priority"]) == (["M"], "no", "P0")
    assert g01["rule"].startswith("Skip Mayhem coins: CreateEvent or bonding-curve flag")
    assert "[Cocoon]" not in g01["rule"] and "**" not in g01["rule"] and "`" not in g01["where"]
    assert rules["G04"]["owners"] == ["crawler", "strategy"] and rules["G04"]["ids"] == ["PE-11", "RA-03", "RA-04"]
    assert rules["G07"]["grounded"] == ["AI", "C"] and rules["G07"]["rule_in_bot"] == "yes"
    assert rules["G20"]["grounded"] == ["P", "M", "C"] and rules["G20"]["rule_in_bot"] == "partial"
    assert rules["G24"]["grounded"] == ["M", "AI"] and rules["G24"]["rule_in_bot"] == "partial"
    assert rules["G09"]["owner"] == "judge" and rules["G47"]["owner"] == "judge"  # "[Jev]" is the judge member
    assert rules["G12"]["priority"] == "P0" and rules["G25"]["priority"] == "P2"  # the first priority named
    assert rules["N4.9"]["rule"].startswith("The default dip-rebound itself.")
    assert rules["N4.9"]["section"] == "Folklore already inside the bot" and rules["N4.9"]["grounded"] == []


def test_owners_are_members_of_the_team(book: dict[str, Any]) -> None:
    team = {mid for mid, _, _ in MEMBERS}
    for r in book["rules"]:
        assert r["owner"] == r["owners"][0] and set(r["owners"]) <= team, r["id"]


# --------------------------------------------------------------------------- initial statuses (§7.1)


def test_initial_statuses_follow_experience_section_7_1(book: dict[str, Any]) -> None:
    status = {r["id"]: r["status"] for r in book["rules"]}
    by_status: dict[str, set[str]] = {}
    for rid, s in status.items():
        by_status.setdefault(s, set()).add(rid)
    # contradicted: the hard fails on graduates, the address serial-launcher rule, stop fills at the stop price,
    # the 20-30 trades go-live text, 20% sizing with a daily limit that is not a bound, the default dip-rebound
    assert by_status["in_bot_contradicted"] == {"G02", "G06", "G22", "G39", "G38", "N4.9"}
    # unsupported: concentration caps, creator-watch, paintable confirmation, socials in Jev's prompt, sell half
    assert by_status["in_bot_unsupported"] == {"G07", "G20", "G15", "G09", "G30"}
    assert "validated" not in by_status and "rejected" not in by_status  # nothing has passed or failed yet
    assert {"G01", "G12", "G33", "G40", "G23"} <= by_status["fix_engineering"]  # Track E and the P0 safety PRs
    assert by_status["testing"] == {"G04", "G14"}  # lab hypothesis G1 (and its airdrop sign)
    assert {"G05", "G13", "G21"} <= by_status["blocked_data"]  # wallet-level data not downloaded yet
    for r in book["rules"]:
        if r["status"] == "parked":
            assert r["priority"] == "P3", r["id"]
        if r["status"] == "blocked_data":
            assert r["priority"] == "P2", r["id"]
    assert Counter(status.values())["in_bot_contradicted"] == 6


def test_the_experience_core_reads_the_generated_registry(book: dict[str, Any]) -> None:
    """``experience.playbook`` (T3) loads this file (T7) as generated: every rule with its status, and the §7.1
    counts the Coach row shows."""
    from nightcrawler.experience import playbook

    entries = playbook.load_entries()
    assert {e["id"]: e["status"] for e in entries} == {r["id"]: r["status"] for r in book["rules"]}
    assert len(entries) == len(book["rules"]) == 63
    counts = playbook.counts(playbook.fold_statuses(entries))
    assert (counts["in_bot_contradicted"], counts["in_bot_unsupported"], counts["validated"]) == (6, 5, 0)


def test_risk_rules_are_never_a_learnable_track(book: dict[str, Any]) -> None:
    """Risk limits are human-reviewed code only (§7.4): every risk-owned entry is on track R or a reviewed fix."""
    for r in book["rules"]:
        if r["owner"] == "risk":
            assert r["track"] in {"R", "E"}, r["id"]
    assert "never learnable" in book["tracks"]["R"]


# --------------------------------------------------------------------------- plain words


def test_owner_facing_words_pass_the_lint(book: dict[str, Any]) -> None:
    texts = [*book["statuses"].values(), *book["tracks"].values()]
    for r in book["rules"]:
        assert len(r["name"]) <= 60 and len(r["evidence"]) <= 160, r["id"]
        texts += [r["name"], r["evidence"]]
    for text in texts:
        assert not BANNED.search(text), text
        assert not JARGON.search(text), text
        assert "win rate" not in text.lower()
    assert "win_rate" not in PLAYBOOK.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- static data, never a trading input


def test_nothing_that_trades_reads_the_playbook() -> None:
    """A status in the playbook can never turn trading on: no trading module mentions it."""
    src = ROOT / "src" / "nightcrawler"
    trading = [src / f"{name}.py" for name in ("engine", "strategy", "risk", "cocoon", "radar", "crawler", "judge",
                                               "config", "cli", "readiness")]
    trading += sorted((src / "broker").glob("*.py"))
    for path in trading:
        text = path.read_text(encoding="utf-8")
        assert "playbook" not in text and "nightcrawler.experience" not in text, path.name

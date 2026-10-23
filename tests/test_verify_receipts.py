"""scripts/verify_receipts.py: the dependency-free verifier anyone can run on a receipts export."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import FakeClock

from nightcrawler.ledger import Ledger
from nightcrawler.models import Decision, Fill, Verdict

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_receipts.py"
NOW = 1_791_475_200.0  # 2026-10-08T16:00:00Z
GENESIS = "0" * 64


def run(*args: object) -> subprocess.CompletedProcess[str]:
    """``python -I -S``: isolated, no site-packages - only the standard library is importable."""
    return subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), *map(str, args)], capture_output=True,
                          text=True, timeout=60)


@pytest.fixture
def export(tmp_path: Path, fake_clock: FakeClock) -> tuple[Path, int, str]:
    """A real export written by the ledger: boot, decision (with a verdict), fill and notes with
    floats, unicode and an integer above 2**53 (the values other JSON encoders write differently)."""
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as ledger:
        ledger.append_receipt("boot", {"version": "0.1.0", "mode": "paper", "settings": {"position_pct": 0.2}})
        verdict = Verdict(decision="yes", confidence=0.71, reasons=["buyers back ✓"], model="claude-opus-5-5",
                          latency_ms=812, cost_usd=0.00123, source="claude")
        ledger.record_decision(Decision(ts=NOW + 1.2345, mint="HiGGSmint", action="enter", reason="dip 61.0%",
                                        inputs={"dip": 0.61, "tiny": 1e-05, "big": 12345678901234567890},
                                        verdict=verdict, symbol="猫\U0001f680"))
        ledger.record_fill(Fill(id="f1", mode="paper", side="buy", mint="HiGGSmint", sol_lamports=100_000_000,
                                token_amount=5_000_000_000, token_decimals=6, price_usd=0.004, sol_usd=200.0,
                                fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=1.5, signature=None,
                                request_id="r1", ts=NOW + 2))
        ledger.append_receipt("note", {"event": "shutdown", "start_usd": 100.0})
        ledger.append_receipt("note", {"event": "x", "n": 5})
        path = tmp_path / "receipts.jsonl"
        assert ledger.export_receipts(path) == 5
        seq, head = ledger.head()
    return path, seq, head


def rows_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_rows(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows)
    path.write_text(text, encoding="utf-8")


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def relink(rows: list[dict], start: int) -> None:
    """Recompute body/hash of rows[start:] and re-chain them: what a forger with the file would do."""
    prev = rows[start - 1]["hash"] if start else GENESIS
    for r in rows[start:]:
        r["prev_hash"] = prev
        r["body"] = canonical({k: r[k] for k in ("seq", "ts", "kind", "payload")})
        r["hash"] = prev = hashlib.sha256((prev + r["body"]).encode()).hexdigest()


def test_verifies_a_real_export_with_the_standard_library_only(export: tuple[Path, int, str]) -> None:
    path, seq, head = export
    result = run(path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(f"OK: {seq} receipts, chain intact")
    assert f"head seq {seq} hash {head}" in result.stdout


def test_an_empty_export_is_an_intact_empty_chain(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    result = run(empty)
    assert result.returncode == 0 and result.stdout.startswith("OK: 0 receipts")
    assert run(empty, "--head", "a" * 64).returncode == 1  # nothing was ever published from it


def test_a_published_head_must_be_in_the_chain(export: tuple[Path, int, str]) -> None:
    path, seq, head = export
    assert run(path, "--head", head).returncode == 0
    earlier = rows_of(path)[1]["hash"]  # a head hash posted after receipt #2
    ok = run(path, "--head", earlier)
    assert ok.returncode == 0 and "published head found at seq 2" in ok.stdout
    missing = run(path, "--head", "f" * 64)
    assert missing.returncode == 1 and "not in this chain" in missing.stdout


def _edit_body(rows: list[dict]) -> None:
    rows[2]["body"] = rows[2]["body"].replace("100000000", "900000000")


def _edit_shown_payload(rows: list[dict]) -> None:
    rows[2]["payload"]["sol_lamports"] = 900_000_000  # body (what was hashed) left alone


def _drop(rows: list[dict]) -> None:
    del rows[2]


def _swap(rows: list[dict]) -> None:
    rows[2], rows[3] = rows[3], rows[2]


def _prev_hash(rows: list[dict]) -> None:
    rows[2]["prev_hash"] = rows[0]["hash"]


def _forge_one(rows: list[dict]) -> None:
    rows[2]["payload"]["sol_lamports"] = 900_000_000
    relink(rows[:3], 2)  # seq 3 is self-consistent, but seq 4 still points at the old hash


def _non_canonical_body(rows: list[dict]) -> None:
    body = json.loads(rows[2]["body"])
    rows[2]["body"] = json.dumps(body, sort_keys=True)  # spaces: not the canonical text
    rows[2]["hash"] = hashlib.sha256((rows[2]["prev_hash"] + rows[2]["body"]).encode()).hexdigest()
    rows[3]["prev_hash"] = rows[2]["hash"]
    relink(rows, 3)


def _seq_in_body(rows: list[dict]) -> None:
    body = json.loads(rows[2]["body"])
    body["seq"] = 9  # the hashed seq disagrees with the line's position in the chain
    rows[2]["body"] = canonical(body)
    rows[2]["hash"] = hashlib.sha256((rows[2]["prev_hash"] + rows[2]["body"]).encode()).hexdigest()
    rows[3]["prev_hash"] = rows[2]["hash"]
    relink(rows, 3)


@pytest.mark.parametrize(("tamper", "bad_seq", "why"), [
    (_edit_body, 3, "hash mismatch"),
    (_edit_shown_payload, 3, "differs from the hashed body"),
    (_drop, 3, "expected seq 3"),
    (_swap, 3, "expected seq 3"),
    (_prev_hash, 3, "prev_hash"),
    (_forge_one, 4, "prev_hash"),
    (_non_canonical_body, 3, "not canonical"),
    (_seq_in_body, 3, "expected seq 3, found 9"),
])
def test_tampering_is_caught_at_the_first_bad_receipt(export: tuple[Path, int, str],
                                                      tamper: Callable[[list[dict]], None], bad_seq: int,
                                                      why: str) -> None:
    path, _, _ = export
    rows = rows_of(path)
    tamper(rows)
    write_rows(path, rows)
    result = run(path)
    assert result.returncode == 1, result.stdout
    assert f"BROKEN at seq {bad_seq}" in result.stdout and why in result.stdout, result.stdout


def test_a_fully_reforged_chain_verifies_but_misses_the_published_head(export: tuple[Path, int, str]) -> None:
    """Why the head hash gets published: a forger can rebuild every later link, but not the old head."""
    path, _, head = export
    rows = rows_of(path)
    rows[2]["payload"]["sol_lamports"] = 900_000_000
    relink(rows, 2)
    write_rows(path, rows)
    assert run(path).returncode == 0
    result = run(path, "--head", head)
    assert result.returncode == 1 and "not in this chain" in result.stdout


def test_garbage_lines_and_missing_files(tmp_path: Path, export: tuple[Path, int, str]) -> None:
    path, _, _ = export
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], "{not json", *lines[1:]]) + "\n", encoding="utf-8")
    result = run(path)
    assert result.returncode == 1 and "line 2" in result.stdout and "not JSON" in result.stdout
    missing = run(tmp_path / "nope.jsonl")
    assert missing.returncode == 2 and "cannot read" in missing.stderr


def test_the_script_imports_only_the_standard_library() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names}
    modules |= {node.module.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    assert modules and modules <= set(sys.stdlib_module_names), modules - set(sys.stdlib_module_names)
    assert not any("nightcrawler" in m for m in modules)

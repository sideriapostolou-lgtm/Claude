"""Import boundaries of the learning loop (docs/LEARNING.md S4), checked on the source AST:

* learner modules (everything in ``nightcrawler/learn`` except the recorder) import none of
  ``broker``, ``wallet``, ``risk``, ``judge``, ``http`` or ``sources`` (nor ``requests``): the learner is
  a pure function of the tape bytes, the code and the constants, and can neither trade nor call out;
* the recorder imports, from nightcrawler, only ``http``, ``sources`` and ``learn.{tape,store}``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import nightcrawler.learn

LEARN = Path(nightcrawler.learn.__file__).parent
FORBIDDEN = ("nightcrawler.broker", "nightcrawler.wallet", "nightcrawler.risk", "nightcrawler.judge",
             "nightcrawler.http", "nightcrawler.sources", "requests")
RECORDER_ALLOWED = ("nightcrawler.http", "nightcrawler.sources", "nightcrawler.learn.tape", "nightcrawler.learn.store")


def imports(path: Path) -> set[str]:
    """Every module a file imports, ``from nightcrawler import risk`` counted as ``nightcrawler.risk``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative imports hide the boundary"
            module = node.module or ""
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def _under(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


LEARNER_FILES = sorted(p for p in LEARN.rglob("*.py") if p.name != "recorder.py")


def test_the_package_has_the_phase_1_modules() -> None:
    names = {p.relative_to(LEARN).as_posix() for p in LEARN.rglob("*.py")}
    assert {"__init__.py", "store.py", "tape.py", "recorder.py", "variants.py", "replay.py", "evidence.py",
            "card.py", "gate.py", "families/dip_rebound.py", "families/placebo.py"} <= names


@pytest.mark.parametrize("path", LEARNER_FILES, ids=lambda p: p.relative_to(LEARN).as_posix())
def test_learner_modules_cannot_trade_or_call_out(path: Path) -> None:
    bad = sorted(name for name in imports(path) if _under(name, FORBIDDEN))
    assert not bad, f"{path.name} imports {bad}"


def test_the_recorder_imports_only_http_sources_tape_and_store() -> None:
    ours = {name for name in imports(LEARN / "recorder.py") if _under(name, ("nightcrawler",))}
    # ``from nightcrawler.learn.tape import X`` also yields ``nightcrawler.learn.tape.X``: still inside tape
    bad = sorted(name for name in ours if not _under(name, RECORDER_ALLOWED))
    assert not bad, f"recorder imports {bad}"
    assert _under("nightcrawler.http", RECORDER_ALLOWED) and any(_under(n, ("nightcrawler.sources",)) for n in ours)


def test_the_checker_sees_every_import_style(tmp_path) -> None:
    probe = tmp_path / "probe.py"
    lines = ["import nightcrawler.risk", "from nightcrawler import judge", "from nightcrawler.broker import paper",
             "import requests as r", "from nightcrawler.sources.pumpfun import PumpFunClient",
             "from nightcrawler import http as transport"]
    for line in lines:
        probe.write_text(line + "\n", encoding="utf-8")
        assert any(_under(name, FORBIDDEN) for name in imports(probe)), line
    probe.write_text("from nightcrawler import strategy, hashing\nimport math\n", encoding="utf-8")
    assert not any(_under(name, FORBIDDEN) for name in imports(probe))

"""Import boundaries of the learning loop (docs/LEARNING.md S4), checked on the source AST:

* learner modules (everything in ``nightcrawler/learn`` except the recorder) import none of
  ``broker``, ``wallet``, ``risk``, ``judge``, ``http`` or ``sources`` (nor ``requests``): the learner is
  a pure function of the tape bytes, the code and the constants, and can neither trade nor call out;
* the recorder imports, from nightcrawler, only ``http``, ``sources`` and ``learn.{tape,store}``;
* experience modules (``nightcrawler/experience``, docs/EXPERIENCE.md X2) import none of those either, nor
  ``ledger``, ``engine``, ``crawler``, ``cocoon``, ``radar`` or ``dashboard``: experience grades members from the
  verdicts the engine tapes and can never trade; learn never imports experience.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

import nightcrawler.experience
import nightcrawler.learn

LEARN = Path(nightcrawler.learn.__file__).parent
EXPERIENCE = Path(nightcrawler.experience.__file__).parent
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


#: What the learner PROCESS may never load, directly or through another module (S4): no way to trade, sign,
#: write the ledger or call out. ``nightcrawler.sources`` itself is allowed for its pure ``_parse`` helpers
#: (the backtester parses timestamps with them), never a client. ``nightcrawler.risk`` comes in only through
#: the backtester's PURE sizing function, shared with live trading on purpose (``test_backtest.py`` pins it);
#: the risk STATE lives in the ledger, which the process never loads.
PROCESS_FORBIDDEN = ("nightcrawler.broker", "nightcrawler.wallet", "nightcrawler.judge", "nightcrawler.http",
                     "nightcrawler.ledger", "nightcrawler.engine", "nightcrawler.dashboard", "nightcrawler.crawler",
                     "nightcrawler.cocoon", "nightcrawler.radar", "requests", "urllib3", "solders", "anthropic")
PROCESS_SOURCES_ALLOWED = ("nightcrawler.sources", "nightcrawler.sources._parse")


def test_the_learner_process_never_loads_a_trading_or_network_module(make_settings) -> None:
    """The child the engine starts, run for real: ``-X importtime`` lists every module it imported."""
    import subprocess

    from nightcrawler.learn.job import learner_command, learner_env

    cmd = learner_command(os.getpid(), 60.0)
    cmd[1:1] = ["-X", "importtime"]
    done = subprocess.run(cmd, env=learner_env(make_settings()), timeout=120, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True)
    assert done.returncode == 0 and "learner ok" in done.stdout, done.stderr[-2000:]
    loaded = {line.rsplit("|", 1)[-1].strip() for line in done.stderr.splitlines() if line.startswith("import time:")}
    assert "nightcrawler.learn.job" in loaded and "nightcrawler.backtest" in loaded
    bad = sorted(m for m in loaded if _under(m, PROCESS_FORBIDDEN)
                 or (_under(m, ("nightcrawler.sources",)) and m not in PROCESS_SOURCES_ALLOWED))
    assert not bad, f"the learner process loads {bad}"


# --------------------------------------------------------------------------- experience (docs/EXPERIENCE.md X2)

EXPERIENCE_FORBIDDEN = (*FORBIDDEN, "nightcrawler.ledger", "nightcrawler.engine", "nightcrawler.crawler",
                        "nightcrawler.cocoon", "nightcrawler.radar", "nightcrawler.dashboard")
EXPERIENCE_FILES = sorted(EXPERIENCE.rglob("*.py"))


def test_the_experience_package_has_the_phase_1_core() -> None:
    names = {p.relative_to(EXPERIENCE).as_posix() for p in EXPERIENCE_FILES}
    assert {"__init__.py", "constants.py", "texts.py", "stats.py", "attribution.py", "losses.py", "features.py",
            "cards.py", "playbook.py"} <= names
    assert (LEARN / "labels.py").exists()


@pytest.mark.parametrize("path", EXPERIENCE_FILES, ids=lambda p: p.relative_to(EXPERIENCE).as_posix())
def test_experience_modules_cannot_trade_or_call_out(path: Path) -> None:
    bad = sorted(name for name in imports(path) if _under(name, EXPERIENCE_FORBIDDEN))
    assert not bad, f"{path.name} imports {bad}"


@pytest.mark.parametrize("path", sorted(LEARN.rglob("*.py")), ids=lambda p: p.relative_to(LEARN).as_posix())
def test_learn_never_imports_experience(path: Path) -> None:
    bad = sorted(name for name in imports(path) if _under(name, ("nightcrawler.experience",)))
    assert not bad, f"{path.name} imports {bad}"


def test_the_checker_sees_experience_specific_imports(tmp_path) -> None:
    probe = tmp_path / "probe.py"
    for line in ("from nightcrawler import cocoon", "import nightcrawler.engine", "from nightcrawler.ledger import X",
                 "from nightcrawler.radar import Radar", "from nightcrawler import dashboard, crawler"):
        probe.write_text(line + "\n", encoding="utf-8")
        assert any(_under(name, EXPERIENCE_FORBIDDEN) for name in imports(probe)), line
    probe.write_text("from nightcrawler.learn import labels, evidence\nfrom nightcrawler import models\n",
                     encoding="utf-8")
    assert not any(_under(name, EXPERIENCE_FORBIDDEN) for name in imports(probe))


def test_importing_experience_loads_no_trading_or_network_module() -> None:
    """The modules really loaded (``-X importtime``) when every experience module is imported."""
    import subprocess

    modules = ", ".join(f"nightcrawler.experience.{p.stem}" for p in EXPERIENCE_FILES if p.stem != "__init__")
    src = str(EXPERIENCE.parents[1])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (src, os.environ.get("PYTHONPATH"))))}
    done = subprocess.run([sys.executable, "-X", "importtime", "-c", f"import {modules}"], env=env, timeout=120,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    loaded = {line.rsplit("|", 1)[-1].strip() for line in done.stderr.splitlines() if line.startswith("import time:")}
    assert "nightcrawler.experience.cards" in loaded and "nightcrawler.learn.labels" in loaded
    bad = sorted(m for m in loaded if _under(m, (*PROCESS_FORBIDDEN, *EXPERIENCE_FORBIDDEN)))
    assert not bad, f"importing experience loads {bad}"

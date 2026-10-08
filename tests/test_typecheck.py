"""mypy stays clean on src/ with the ``[tool.mypy]`` settings in pyproject.toml (skipped without mypy)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mypy", reason="mypy is in the dev extra")

ROOT = Path(__file__).resolve().parents[1]


def test_mypy_reports_no_errors_on_src() -> None:
    result = subprocess.run([sys.executable, "-m", "mypy", "--config-file", str(ROOT / "pyproject.toml")],
                            cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Success: no issues found" in result.stdout

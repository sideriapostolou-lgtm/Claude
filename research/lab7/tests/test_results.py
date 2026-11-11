"""research/lab7/results.py: RESULTS.md is rendered from the result files, never by hand (PLAN.md §9)."""

from __future__ import annotations

import json
from pathlib import Path

import results


def _cell(key: str, mean: float, lo: float, *, selectable: bool = True, passes: bool = False,
          gross: float | None = None) -> dict:
    c = {
        "cell": key,
        "selectable": selectable,
        "bar": {"passes": passes, "checks": {}},
        "summary": {"n": 200, "mean_net_us": mean, "ci95": [lo, mean + 0.01], "win_rate": 0.4,
                    "breakeven_win_rate": 0.6},
    }
    if gross is not None:
        c["extra"] = {"gross_mean": gross}
    return c


def _write(base: Path, hyp: str, name: str, payload: dict | str) -> None:
    (base / hyp).mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (base / hyp / name).write_text(text)


def test_no_edge_everywhere(tmp_path: Path) -> None:
    for hyp in results.HYPS:
        train = {"verdict": "NO_EDGE_TRAIN", "selected": None,
                 "cells": [_cell("a|tp0.05", -0.05, -0.06, gross=-0.01), _cell("b|tp0.03", -0.04, -0.07),
                           _cell("hold|a", 0.02, -0.03, selectable=False)]}
        if hyp == "W1":  # W1 names its code inside a decision line instead of a verdict field
            train = {"decision": "NO EDGE on TRAIN (NO_EDGE_TRAIN): no selectable cell passes", **train}
            del train["verdict"]
        _write(tmp_path, hyp, "train.json", train)
    _write(tmp_path, "W1", "SKEPTIC.md", "# review\n\n**Verdict: the NO EDGE result\nstands.** More text.\n")
    (tmp_path / "trials.json").write_text(json.dumps([{"lab": "lab7", "hyp": "W1", "split": "train", "passes": False}]))
    out = results.render(tmp_path, trials_total=1234)
    w1 = next(line for line in out.splitlines() if line.startswith("| W1 |"))
    assert "NO EDGE on TRAIN: 0 of 2 selectable cells pass" in w1
    assert "NOT RUN: TRAIN selected no cell" in w1 and "NOT RUN: no VAL pass" in w1
    assert "the NO EDGE result stands." in w1  # the bold verdict, joined across its line break
    w2 = next(line for line in out.splitlines() if line.startswith("| W2 |"))
    assert w2.endswith("| no review yet |")
    assert "on the live desk** (only a TEST pass confirmed by its skeptic counts): **none**." in out
    assert "`a\\|tp0.05`" in out  # best by CI95 lower bound, pipes escaped for the markdown table
    assert "1 lab 7 rows" in out and "**1,234**" in out


def test_stage_columns_and_ready_line(tmp_path: Path) -> None:
    cells = [_cell("a|tp0.05", 0.03, 0.01, passes=True)]
    _write(tmp_path, "W1", "train.json", {"verdict": "SELECTED_ON_VAL", "selected": "a|tp0.05", "cells": cells})
    _write(tmp_path, "W1", "val.json", {"verdict": "SELECTED_ON_VAL", "cells": cells})
    _write(tmp_path, "W1", "test.json", {"verdict": "PASS_TEST", "cells": cells})
    _write(tmp_path, "W2", "train.json", {"verdict": "SELECTED_ON_VAL", "selected": "a|tp0.05", "cells": cells})
    _write(tmp_path, "W2", "val.json", {"verdict": "FAIL_VAL", "cells": cells})
    out = results.render(tmp_path)
    w1 = next(line for line in out.splitlines() if line.startswith("| W1 |"))
    assert "selected `a\\|tp0.05`" in w1 and "| passed VAL | PASS on TEST |" in w1
    w2 = next(line for line in out.splitlines() if line.startswith("| W2 |"))
    assert "| FAIL on VAL | NOT RUN: no VAL pass (TEST never read) |" in w2
    assert "W1 (TEST pass; needs its skeptic's confirmation" in out
    assert "| W3 | " in out and "| not run | - | - | no review yet |" in out


def test_in_band_reading(tmp_path: Path) -> None:
    assert results.in_band_reading(tmp_path / "missing.json") is None
    diag = {"best": "a", "cells": {"a": {"in_band": {"n": 1500, "mean": -0.08, "ci95": [-0.09, -0.07],
                                                    "gross_mean": -0.02}}},
            "summary": {"cells": 192, "in_band_mean_positive": 0, "in_band_gross_positive": 0,
                        "max_in_band_mean": -0.08, "out_band_trips": 10, "trips": 100}}
    path = tmp_path / "train_diag.json"
    path.write_text(json.dumps(diag))
    line = results.in_band_reading(path)
    assert line is not None
    assert "0 of 192 cells have a mean > 0" in line and "n 1,500, mean -0.0800" in line and "10 of 100" in line

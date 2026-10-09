"""Lab 4 stages: TRAIN (grid, select one cell per hypothesis), VAL (the selected cell + calibration placebo), TEST
(one look). Writes ``research/lab4/<HYP>/<stage>.json`` and ``.md`` and refreshes ``RESULTS.md``.

CLI::

    python research/lab4/run.py --stage train            # every hypothesis
    python research/lab4/run.py --stage val --hyp P2
    LAB4_ALLOW_TEST=1 python research/lab4/run.py --stage test --hyp P2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import core as C

import data as D

HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"

HYPOTHESES: dict[str, dict[str, Any]] = {
    "P1": {
        "title": "near-certain, all markets",
        "families": "all",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [1.0, 6.0, 24.0, 168.0],
        "control": False,
        "selectable": True,
    },
    "P2": {
        "title": "late-game sports",
        "families": "sports",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [0.25, 0.5, 1.0, 2.0],
        "control": False,
        "selectable": True,
    },
    "P3": {
        "title": "crypto up/down, last minutes",
        "families": "crypto",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [1.0 / 60.0, 5.0 / 60.0],
        "control": False,
        "selectable": True,
    },
    "P4": {
        "title": "non-sports grind (the owner's venue)",
        "families": "nonsports",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [1.0, 6.0, 24.0, 168.0],
        "control": False,
        "selectable": True,
    },
    "C1": {
        "title": "control: longshots (the other side)",
        "families": "all",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [1.0, 6.0, 24.0, 168.0],
        "control": True,
        "selectable": False,
    },
}
MIN_N = 100
PLACEBO_PCT = 95.0


def prereg_sha256() -> str:
    return hashlib.sha256(PLAN.read_bytes()).hexdigest()


def cell_key(theta: float, hours: float) -> str:
    return f"theta{theta:g}|H{hours:g}"


def evaluate(
    ds: C.Dataset,
    hyp: str,
    cells: list[tuple[float, float]] | None = None,
    B: int = C.BOOTSTRAP_B,
    placebo: bool = False,
) -> list[dict[str, Any]]:
    h = HYPOTHESES[hyp]
    grid = (
        cells
        if cells is not None
        else [(t, H) for t in h["thetas"] for H in h["hours"]]
    )
    out = []
    for theta, hours in grid:
        trades = C.cell_trades(ds, theta, hours, h["families"], control=h["control"])
        s = C.summarize(trades, ds.split, B=B)
        cell = {
            "key": cell_key(theta, hours),
            "theta": theta,
            "hours": hours,
            "summary": s,
        }
        if placebo:
            cell["placebo"] = C.calibration_placebo(trades, draws=B)
        out.append(cell)
    return out


def decide_train(cells: list[dict[str, Any]], hyp: str) -> dict[str, Any] | None:
    if not HYPOTHESES[hyp]["selectable"]:
        return None
    ok = [c for c in cells if C.qualifies(c["summary"], MIN_N)]
    if not ok:
        return None
    best = max(ok, key=lambda c: c["summary"]["mean_net"])
    return {"key": best["key"], "theta": best["theta"], "hours": best["hours"]}


def decide_holdout(cell: dict[str, Any]) -> str:
    s, p = cell["summary"], cell.get("placebo") or {}
    beats_placebo = (
        p.get("real_percentile") is not None and p["real_percentile"] >= PLACEBO_PCT
    )
    return "SELECTED" if C.qualifies(s, MIN_N) and beats_placebo else "FAIL"


def _fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _md(hyp: str, stage: str, doc: dict[str, Any]) -> str:
    h = HYPOTHESES[hyp]
    lines = [
        f"# {hyp} {h['title']}: {stage.upper()} ({doc['split']}, lab4-v1)",
        "",
        f"Run {doc['utc']}; PLAN.md sha256 {doc['prereg_sha256'][:12]}; markets in split {doc['n_markets']} "
        f"(families: {doc['families']}); trials so far across labs 2-4: {doc['n_trials_total']}.",
        "",
    ]
    lines.append(
        "| cell | n | missed | /day | win rate | mean p | gap | mean net | CI95 | $/trade | worst $ | streak | lock h | daily Sharpe | DD $ |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in doc["cells"]:
        s = c["summary"]
        ci = s["ci95"]
        lines.append(
            f"| {c['key']} | {s['n']} | {s['missed']} | {_fmt(s['trades_per_day'], 2)} | {_fmt(s['win_rate'])} | "
            f"{_fmt(s['mean_p_exec'])} | {_fmt(s['calibration_gap'])} | {_fmt(s['mean_net'], 4)} | "
            f"[{_fmt(ci[0], 4)}, {_fmt(ci[1], 4)}] | {_fmt(s['mean_pnl_usd'], 2)} | {_fmt(s['worst_pnl_usd'], 2)} | "
            f"{s['longest_losing_streak']} | {_fmt(s['lock_h_median'], 2)} | {_fmt(s['daily']['sharpe'], 2)} | "
            f"{_fmt(s['daily']['max_drawdown_usd'], 2)} |"
        )
        if c.get("placebo"):
            p = c["placebo"]
            lines.append(
                f"|  placebo (calibrated) | | | | | | | mean {_fmt(p['mean'], 4)}, p95 {_fmt(p['p95'], 4)}; "
                f"real at percentile {_fmt(p['real_percentile'], 1)} | | | | | | | |"
            )
    lines.append("")
    lines.append(f"**Decision:** {doc['decision']}")
    if doc.get("selected"):
        lines.append(f"Selected cell: `{doc['selected']['key']}`.")
    lines.append("")
    lines.append(
        "Readings per PLAN §4. 'gap' = win rate minus mean execution price (the gross edge before fees); "
        "'net' = profit per $1 at risk after the venue's taker fee; one trade per market per cell, $20 "
        "tickets, 10 s latency. Nothing here is a live trade."
    )
    return "\n".join(lines) + "\n"


def run_stage(
    stage: str,
    hyps: list[str] | None = None,
    out_dir: Path = D.OUT,
    B: int = C.BOOTSTRAP_B,
    here: Path = HERE,
) -> dict[str, Any]:
    split = stage
    C.check_split_allowed(split)
    ds = C.Dataset.load(split, out_dir)
    results: dict[str, Any] = {}
    for hyp in hyps or list(HYPOTHESES):
        hdir = here / hyp
        hdir.mkdir(exist_ok=True)
        selected = None
        if stage == "train":
            cells = evaluate(ds, hyp, B=B)
            selected = decide_train(cells, hyp)
            if not HYPOTHESES[hyp]["selectable"]:
                decision = "CONTROL (not selectable): reported only"
            else:
                decision = (
                    f"SELECTED {selected['key']} for VAL"
                    if selected
                    else "NO EDGE on TRAIN (no cell qualifies)"
                )
        else:
            prev_name = "train" if stage == "val" else "val"
            prev_path = hdir / f"{prev_name}.json"
            prev = json.loads(prev_path.read_text()) if prev_path.exists() else None
            if (
                not prev
                or not prev.get("selected")
                or (
                    stage == "test"
                    and not str(prev.get("decision", "")).startswith("SELECTED")
                )
            ):
                doc = {
                    "hyp": hyp,
                    "stage": stage,
                    "split": split,
                    "utc": datetime.now(UTC).isoformat(timespec="seconds"),
                    "decision": f"NOT RUN: {prev_name.upper()} did not select a cell",
                    "cells": [],
                    "selected": None,
                    "prereg_sha256": prereg_sha256(),
                    "n_markets": len(ds.markets),
                    "families": ds.markets["family"].value_counts().to_dict(),
                    "n_trials_total": C.trials_count(),
                }
                (hdir / f"{stage}.json").write_text(
                    json.dumps(doc, indent=1, sort_keys=True) + "\n"
                )
                (hdir / f"{stage}.md").write_text(_md(hyp, stage, doc))
                results[hyp] = doc
                continue
            sel = prev["selected"]
            cells = evaluate(
                ds, hyp, cells=[(sel["theta"], sel["hours"])], B=B, placebo=True
            )
            verdict = decide_holdout(cells[0])
            selected = sel if verdict == "SELECTED" else None
            decision = (
                (
                    f"SELECTED {sel['key']} for TEST"
                    if verdict == "SELECTED"
                    else f"FAIL on {split.upper()}"
                )
                if stage == "val"
                else (
                    f"PASS on TEST ({sel['key']})"
                    if verdict == "SELECTED"
                    else f"FAIL on TEST ({sel['key']})"
                )
            )
        n_total = 0
        for c in cells:
            n_total = C.record_run(
                {
                    "lab": "lab4",
                    "hyp": hyp,
                    "cell": c["key"],
                    "split": split,
                    "stage": stage,
                    "n": c["summary"]["n"],
                    "mean_net": c["summary"]["mean_net"],
                    "kind": "cell",
                }
            )
        doc = {
            "hyp": hyp,
            "stage": stage,
            "split": split,
            "utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "decision": decision,
            "cells": cells,
            "selected": selected,
            "prereg_sha256": prereg_sha256(),
            "n_markets": len(ds.markets),
            "families": ds.markets["family"].value_counts().to_dict(),
            "n_trials_total": n_total,
        }
        (hdir / f"{stage}.json").write_text(
            json.dumps(doc, indent=1, sort_keys=True) + "\n"
        )
        (hdir / f"{stage}.md").write_text(_md(hyp, stage, doc))
        results[hyp] = doc
        print(f"{hyp} {stage}: {decision}", flush=True)
    _results_md(here)
    return results


def _results_md(here: Path = HERE) -> None:
    rows = [
        "# Lab 4 results (prediction markets, the near-certain grind)",
        "",
        "| hyp | title | TRAIN | VAL | TEST |",
        "|---|---|---|---|---|",
    ]
    for hyp, h in HYPOTHESES.items():
        cells = []
        for stage in ("train", "val", "test"):
            p = here / hyp / f"{stage}.json"
            cells.append(json.loads(p.read_text())["decision"] if p.exists() else "-")
        rows.append(f"| {hyp} | {h['title']} | {cells[0]} | {cells[1]} | {cells[2]} |")
    rows += [
        "",
        "Decisions per research/lab4/PLAN.md; per-stage tables in each hypothesis folder. Paper only.",
        "",
    ]
    (here / "RESULTS.md").write_text("\n".join(rows))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lab 4 stages")
    ap.add_argument("--stage", choices=["train", "val", "test"], required=True)
    ap.add_argument("--hyp", nargs="*", default=None)
    ap.add_argument("--B", type=int, default=C.BOOTSTRAP_B)
    a = ap.parse_args(argv)
    run_stage(a.stage, a.hyp, B=a.B)
    return 0


if __name__ == "__main__":
    sys.exit(main())

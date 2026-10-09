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
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import core as C

import data as D

HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"

INF = C.INF
HYPOTHESES: dict[str, dict[str, Any]] = {
    "P1": {
        "title": "near-certain, all markets",
        "families": "all",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [1.0, 6.0, 24.0, 168.0, INF],
        "control": False,
        "selectable": True,
    },
    "P2": {
        "title": "late-game sports",
        "families": "sports",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [0.25, 0.5, 1.0, 2.0, INF],
        "control": False,
        "selectable": True,
        "selectable_hours": [INF],
    },  # Amendment 3: windowed sports cells are oracle-timed, reported only
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
        "hours": [1.0, 6.0, 24.0, 168.0, INF],
        "control": False,
        "selectable": True,
    },
    "P5": {
        "title": "patient bid: rest at the bid, fill only when a seller sweeps through",
        "families": "all",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [1.0, 6.0, 24.0, 168.0, INF],
        "control": False,
        "selectable": True,
        "maker": True,
        "offsets": [0, 1],
        "fees": {"fee0": 0.0, "feeT": 1.0},
        "selectable_fees": ["feeT"],
    },  # Amendment 4: fee0 (maker pays nothing) is the fee-free upper bound, reported only; feeT selects
    "C1": {
        "title": "control: longshots (the other side)",
        "families": "all",
        "thetas": [0.95, 0.97, 0.99],
        "hours": [1.0, 6.0, 24.0, 168.0, INF],
        "control": True,
        "selectable": False,
    },
}
MIN_N = 100
PLACEBO_PCT = 95.0
PLAN_VERSION = "lab4-v1 + Amendments 1-4"


def prereg_sha256() -> str:
    return hashlib.sha256(PLAN.read_bytes()).hexdigest()


def cell_key(
    theta: float, hours: float, offset: int | None = None, fee: str | None = None
) -> str:
    key = f"theta{theta:g}|H{'inf' if hours == INF else f'{hours:g}'}"
    if offset is not None:
        key += f"|b-{offset}"
    if fee is not None:
        key += f"|{fee}"
    return key


def oracle_timed(hyp: str, hours: float) -> bool:
    """A windowed sports cell is anchored on an endDate that is a deadline, not the final whistle (Amendment 3)."""
    sel = HYPOTHESES[hyp].get("selectable_hours")
    return sel is not None and hours not in sel


def reported_only(hyp: str, cell: dict[str, Any]) -> str | None:
    """Why a cell is reported but never selected: a windowed sports cell is oracle-timed (Amendment 3); a P5 cell
    at the documented zero maker fee is the fee-free upper bound (Amendment 4). None = selectable."""
    if oracle_timed(hyp, cell["hours"]):
        return "oracle-timed, not selectable"
    sel = HYPOTHESES[hyp].get("selectable_fees")
    if sel is not None and cell.get("fee") not in sel:
        return "fee-free upper bound, not selectable"
    return None


def _spec(sel: dict[str, Any]) -> tuple[Any, ...]:
    """A selected cell as the grid tuple evaluate() takes: (theta, hours) or, for a maker cell, + (offset, fee)."""
    if "fee" in sel:
        return (sel["theta"], sel["hours"], sel["offset"], sel["fee"])
    return (sel["theta"], sel["hours"])


def evaluate(
    ds: C.Dataset,
    hyp: str,
    cells: list[tuple[Any, ...]] | None = None,
    B: int = C.BOOTSTRAP_B,
    placebo: bool = False,
) -> list[dict[str, Any]]:
    h = HYPOTHESES[hyp]
    maker = bool(h.get("maker"))
    if cells is not None:
        grid = cells
    elif maker:
        grid = [
            (t, H, k, fee)
            for t in h["thetas"]
            for H in h["hours"]
            for k in h["offsets"]
            for fee in h["fees"]
        ]
    else:
        grid = [(t, H) for t in h["thetas"] for H in h["hours"]]
    out = []
    for spec in grid:
        theta, hours = float(spec[0]), float(spec[1])
        if maker:
            offset, fee = int(spec[2]), str(spec[3])
            trades = C.bid_trades(
                ds, theta, hours, offset, h["fees"][fee], h["families"]
            )
            cell = {
                "key": cell_key(theta, hours, offset, fee),
                "theta": theta,
                "hours": hours,
                "offset": offset,
                "fee": fee,
                "summary": C.summarize(trades, ds.split, B=B),
                "maker": C.maker_extra(trades),
            }
        else:
            trades = C.cell_trades(
                ds, theta, hours, h["families"], control=h["control"]
            )
            cell = {
                "key": cell_key(theta, hours),
                "theta": theta,
                "hours": hours,
                "summary": C.summarize(trades, ds.split, B=B),
            }
        if placebo:
            cell["placebo"] = C.calibration_placebo(trades, draws=B)
        out.append(cell)
    return out


def decide_train(cells: list[dict[str, Any]], hyp: str) -> dict[str, Any] | None:
    if not HYPOTHESES[hyp]["selectable"]:
        return None
    ok = [
        c
        for c in cells
        if C.qualifies(c["summary"], MIN_N) and reported_only(hyp, c) is None
    ]
    if not ok:
        return None
    best = max(ok, key=lambda c: c["summary"]["mean_net"])
    sel = {"key": best["key"], "theta": best["theta"], "hours": best["hours"]}
    if "fee" in best:
        sel.update({"offset": best["offset"], "fee": best["fee"]})
    return sel


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
        f"# {hyp} {h['title']}: {stage.upper()} ({doc['split']}, {PLAN_VERSION})",
        "",
        f"Run {doc['utc']}; PLAN.md sha256 {doc['prereg_sha256'][:12]}; markets in split {doc['n_markets']} "
        f"(families: {doc['families']}); trials so far across labs 2-4: {doc['n_trials_total']}.",
        "",
    ]
    cov = doc.get("coverage") or {}
    if cov:
        lines += [
            f"Tape coverage: {cov.get('with_tape')} of {cov.get('eligible')} eligible markets "
            f"({100 * float(cov.get('share') or 0):.1f} %).",
            "",
        ]
    maker = bool(h.get("maker"))
    head = (
        "| cell | n | events | missed | /day | win rate | losses | mean p | gap | mean net | CI95 (events) | "
        "worst case (rule of 3) | bid-side share (old rule) | $/trade | worst $ | streak | lock h | "
        "daily Sharpe | DD $ |"
    )
    extra_cols = (
        " bids posted | fill rate | mean ask seen | wait s (median) | size-blocked |"
        if maker
        else ""
    )
    lines.append(head + extra_cols)
    lines.append("|" + "---|" * (19 + (5 if maker else 0)))
    for c in doc["cells"]:
        s = c["summary"]
        ci = s["ci95"]
        why = reported_only(hyp, c)
        tag = f" ({why})" if why else ""
        mk = c.get("maker") or {}
        extra = (
            f" {mk.get('signals', '-')} | {_fmt(mk.get('fill_rate'))} | {_fmt(mk.get('mean_p_signal'))} | "
            f"{_fmt(mk.get('wait_s_median'), 0)} | {mk.get('size_blocked', '-')} |"
            if maker
            else ""
        )
        lines.append(
            f"| {c['key']}{tag} | {s['n']} | {s.get('n_events', '-')} | {s['missed']} | {_fmt(s['trades_per_day'], 2)} | "
            f"{_fmt(s['win_rate'])} | {s.get('losses', '-')} | {_fmt(s['mean_p_exec'])} | {_fmt(s['calibration_gap'])} | "
            f"{_fmt(s['mean_net'], 4)} | [{_fmt(ci[0], 4)}, {_fmt(ci[1], 4)}] | {_fmt(s.get('worst_case_net'), 4)} | "
            f"{'n/a' if maker else _fmt(s.get('bid_side_share'))} | {_fmt(s['mean_pnl_usd'], 2)} | "
            f"{_fmt(s['worst_pnl_usd'], 2)} | "
            f"{s['longest_losing_streak']} | {_fmt(s['lock_h_median'], 2)} | {_fmt(s['daily']['sharpe'], 2)} | "
            f"{_fmt(s['daily']['max_drawdown_usd'], 2)} |" + extra
        )
        if c.get("placebo"):
            p = c["placebo"]
            lines.append(
                f"|  placebo (calibrated) | | | | | | | | | mean {_fmt(p['mean'], 4)}, p95 {_fmt(p['p95'], 4)}; "
                f"real at percentile {_fmt(p['real_percentile'], 1)} | | | | | | | | | |"
                + (" | | | | |" if maker else "")
            )
    lines.append("")
    lines.append(f"**Decision:** {doc['decision']}")
    if doc.get("selected"):
        lines.append(f"Selected cell: `{doc['selected']['key']}`.")
    lines.append("")
    lines.append(
        "Readings per PLAN §4 and Amendment 3. 'gap' = win rate minus mean execution price (the gross edge "
        "before fees); 'net' = profit per $1 at risk after the venue's taker fee; one trade per market per "
        "cell, $20 tickets, 10 s latency, buyable prints only; CI by event bootstrap; 'worst case' = "
        "(1 - 3/n) x mean win - 3/n; 'bid-side share' = how often the old side-blind rule would have filled "
        "at a price no buyer could get. Nothing here is a live trade."
    )
    if maker:
        lines.append("")
        lines.append(
            "P5 (Amendment 4): the bid rests from 10 s after the signal until the window ends; 'missed' = posted and "
            "never filled (fill rate = n / bids posted); a fill needs a later bid-side print STRICTLY below the "
            "resting price (the tape has no depth, so a print at exactly the bid never fills us) with enough "
            "bid-side size at or below it to cover the order ('size-blocked' = bids that saw such a print but never "
            "enough size); 'mean p' is the price paid at the bid, 'mean ask seen' the ask P1 would have lifted; "
            "fee0 = maker pays nothing (the venue's schedule, reported as the upper bound), feeT = maker pays the "
            "taker fee (the stress case; the only selectable cells); the bid-side-share column does not apply."
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
    cov = ds.coverage
    if cov.get("share", 1.0) < 1.0 and os.environ.get("LAB4_ALLOW_PARTIAL") != "1":
        raise RuntimeError(
            f"{split.upper()} tapes incomplete: {cov['with_tape']} of {cov['eligible']} eligible markets have a tape "
            "(Amendment 3 refuses a partial run; set LAB4_ALLOW_PARTIAL=1 for a labelled dry run)"
        )
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
                    "coverage": ds.coverage,
                    "n_trials_total": C.trials_count(),
                }
                (hdir / f"{stage}.json").write_text(
                    json.dumps(doc, indent=1, sort_keys=True) + "\n"
                )
                (hdir / f"{stage}.md").write_text(_md(hyp, stage, doc))
                results[hyp] = doc
                continue
            sel = prev["selected"]
            cells = evaluate(ds, hyp, cells=[_spec(sel)], B=B, placebo=True)
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
            "coverage": ds.coverage,
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

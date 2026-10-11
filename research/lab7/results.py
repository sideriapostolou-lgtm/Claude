"""Lab 7: render research/lab7/RESULTS.md from the per-hypothesis result files (PLAN.md §9: never by hand).

For each hypothesis it reads ``<W>/train.json``, ``<W>/val.json`` and ``<W>/test.json`` when they exist, the
verdict line of ``<W>/SKEPTIC.md`` (the adversarial review), and the lab 7 rows of ``trials.json``. It writes the
lab table (hyp, title, TRAIN, VAL, TEST, skeptic), the TRAIN numbers behind it, and the one line that matters
for the live desk: which strategy, if any, is ready for pretend-money trading. Only a TEST pass counts, and only
once its skeptic has confirmed it.

CLI (from the repo root)::

    python research/lab7/results.py

Research only, paper only. It reads result files; it computes no return and adds no trial.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
HYPS = ("W1", "W2", "W3", "W4")
TITLES = {  # PLAN.md §5 headings
    "W1": "sports before the game: buy below Pinnacle's no-vig fair, sell before the start",
    "W2": "crypto up / down windows: buy below the Binance-spot fair, sell before the window ends",
    "W3": "sports during the game: follow or fade sharp price swings",
    "W4": "politics, culture, weather, economics and the rest: follow or fade swings over hours",
}
VERDICTS = ("NO_EDGE_TRAIN", "FAIL_VAL", "SELECTED_ON_VAL", "PASS_TEST", "FAIL_TEST")
VERDICT_WORDS = {
    "NO_EDGE_TRAIN": "NO EDGE on TRAIN",
    "FAIL_VAL": "FAIL on VAL",
    "SELECTED_ON_VAL": "passed VAL",
    "PASS_TEST": "PASS on TEST",
    "FAIL_TEST": "FAIL on TEST",
}


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.exists() else None


def verdict_of(result: dict[str, Any]) -> str:
    """The plan's verdict code: the file's ``verdict`` field, else the code named in its ``decision`` line."""
    v = result.get("verdict")
    if v in VERDICTS:
        return str(v)
    m = re.search("|".join(VERDICTS), str(result.get("decision", "")))
    return m.group(0) if m else "UNKNOWN"


def skeptic_verdict(path: Path) -> str:
    """The bold ``**Verdict: ...**`` sentence of a SKEPTIC.md, or a note that no review exists."""
    if not path.exists():
        return "no review yet"
    m = re.search(r"\*\*Verdict:\s*(.+?)\*\*", path.read_text(), flags=re.DOTALL)
    return " ".join(m.group(1).split()) if m else "review present, no verdict line"


def _esc(text: str) -> str:
    return text.replace("|", "\\|")


def _f(x: float | None, nd: int = 4) -> str:
    return "-" if x is None else f"{x:+.{nd}f}"


def cell_stats(result: dict[str, Any]) -> dict[str, Any]:
    """Counts over the selectable cells, the best one by CI95 lower bound (PLAN §7's order), the references."""
    cells = result["cells"]
    sel = [c for c in cells if c.get("selectable")]
    ref = [c for c in cells if not c.get("selectable")]
    means = [c["summary"]["mean_net_us"] for c in sel]
    gross = [c["extra"]["gross_mean"] for c in sel if (c.get("extra") or {}).get("gross_mean") is not None]
    best = max(sel, key=lambda c: (c["summary"]["ci95"][0], c["summary"]["mean_net_us"], c["cell"])) if sel else None
    ref_means = [c["summary"]["mean_net_us"] for c in ref]
    return {
        "n_sel": len(sel),
        "n_ref": len(ref),
        "n_pass": sum(bool(c["bar"]["passes"]) for c in sel),
        "n_pos": sum(m > 0 for m in means),
        "mean_lo": min(means) if means else None,
        "mean_hi": max(means) if means else None,
        "n_gross": len(gross),
        "n_gross_pos": sum(g > 0 for g in gross),
        "best": best,
        "ref_lo": min(ref_means) if ref_means else None,
        "ref_hi": max(ref_means) if ref_means else None,
    }


def in_band_reading(path: Path) -> str | None:
    """One line from a post-hoc ``train_diag.json`` that re-reads every cell on entries filled inside the price band
    (W4's format), or None when the file is absent or has no such reading."""
    diag = _load(path)
    summ = (diag or {}).get("summary") or {}
    if "in_band_mean_positive" not in summ:
        return None
    best = (diag.get("cells") or {}).get(diag.get("best"), {}).get("in_band") or {}
    line = (
        f"keeping only entries filled inside the price band, {summ['in_band_mean_positive']} of {summ['cells']} "
        f"cells have a mean > 0 and {summ.get('in_band_gross_positive', '-')} a before-fee mean > 0 "
        f"(best in-band mean {_f(summ.get('max_in_band_mean'))})"
    )
    if best:
        line += (
            f"; the best cell above, in band: n {best['n']:,}, mean {_f(best['mean'])} "
            f"[{_f(best['ci95'][0])}, {_f(best['ci95'][1])}], before fee {_f(best.get('gross_mean'))}"
        )
    return line + (
        f". The full-sample numbers include {summ.get('out_band_trips', 0):,} of {summ.get('trips', 0):,} trades "
        "filled outside the band; the plan fills a whole $20 order at one print's price whatever its size, so some of "
        "those fills could not have happened (W4/SKEPTIC.md)."
    )


def _train_text(result: dict[str, Any] | None, st: dict[str, Any] | None) -> str:
    if result is None or st is None:
        return "not run"
    v = verdict_of(result)
    text = f"{VERDICT_WORDS.get(v, v)}: {st['n_pass']} of {st['n_sel']} selectable cells pass"
    if result.get("selected"):
        sel = result["selected"]
        text += f"; selected `{_esc(sel if isinstance(sel, str) else sel.get('cell', '?'))}`"
    return text


def _stage_text(stage: str, result: dict[str, Any] | None, before: str | None) -> str:
    """VAL or TEST column: the stage's own verdict if it ran, else why it did not."""
    if result is not None:
        v = verdict_of(result)
        return VERDICT_WORDS.get(v, v)
    if before in (None, "not run"):
        return "-"
    if stage == "val":
        return "NOT RUN: TRAIN selected no cell" if before == "NO_EDGE_TRAIN" else "pending"
    if before in ("NO_EDGE_TRAIN", "FAIL_VAL"):
        return "NOT RUN: no VAL pass (TEST never read)"
    return "pending (one look, after review)"


def render(here: Path = HERE, trials_total: int | None = None) -> str:
    rows: list[str] = [
        "# Lab 7 results (in-and-out trading: buy cheap, take a small profit, cut losses fast)",
        "",
        "| hyp | title | TRAIN | VAL | TEST | skeptic |",
        "|---|---|---|---|---|---|",
    ]
    numbers: list[str] = []
    diags: list[str] = []
    ready: list[str] = []
    for hyp in HYPS:
        d = here / hyp
        train, val, test = (_load(d / f"{s}.json") for s in ("train", "val", "test"))
        st = cell_stats(train) if train else None
        v_train = verdict_of(train) if train else None
        v_val = verdict_of(val) if val else None
        v_test = verdict_of(test) if test else None
        skeptic = skeptic_verdict(d / "SKEPTIC.md")
        rows.append(
            f"| {hyp} | {TITLES[hyp]} | {_train_text(train, st)} | {_stage_text('val', val, v_train)} | "
            f"{_stage_text('test', test, v_val if val else v_train)} | {skeptic} |"
        )
        diag_line = in_band_reading(d / "train_diag.json")
        if diag_line:
            diags.append(f"- {hyp}: {diag_line}")
        if v_test == "PASS_TEST":
            ready.append(
                f"{hyp} (TEST pass; needs its skeptic's confirmation of the TEST result before the paper desk)"
            )
        if st and st["best"] is not None:
            b = st["best"]
            s = b["summary"]
            gross = (b.get("extra") or {}).get("gross_mean")
            gross_txt = _f(gross) if gross is not None else "not recorded"
            gross_count = f"{st['n_gross_pos']} of {st['n_gross']}" if st["n_gross"] else "not recorded"
            numbers.append(
                f"| {hyp} | {st['n_sel']} | {st['n_pass']} | {st['n_pos']} | "
                f"{_f(st['mean_lo'])} to {_f(st['mean_hi'])} | "
                f"{gross_count} | `{_esc(b['cell'])}` | {s['n']:,} | "
                f"{s['win_rate'] * 100:.0f} % / {s['breakeven_win_rate'] * 100:.0f} % | {_f(s['mean_net_us'])} | "
                f"[{_f(s['ci95'][0])}, {_f(s['ci95'][1])}] | {gross_txt} | "
                f"{st['n_ref']}: {_f(st['ref_lo'])} to {_f(st['ref_hi'])} |"
            )
    rows += [
        "",
        "**Ready for pretend-money trading on the live desk** (only a TEST pass confirmed by its skeptic counts): "
        + ("; ".join(ready) if ready else "**none**."),
        "",
        "## TRAIN numbers behind the table",
        "",
        (
            "Mean net is per $1 at risk ($20 a trade) after the Polymarket US taker fee (0.0695 x p x (1 - p) on every "
            "taker buy and sell); CI95 is the event-bootstrap range; `before fee` is the best cell's mean with every "
            "fee removed. Win rate = trades that made money after the fee; break-even = the win rate its average win "
            "and loss needed. References = the first entry per market held to settlement (reported only, never "
            "selectable)."
        ),
        "",
        (
            "| hyp | selectable cells | pass | mean > 0 | mean range | before-fee mean > 0 | best cell (CI95 lower) | "
            "trades | win / break-even | mean | CI95 | before fee | references: n, mean range |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *numbers,
    ]
    if diags:
        rows += [
            "",
            "Post-hoc readings (written after TRAIN was read; they decide nothing and add no trial):",
            "",
            *diags,
        ]
    ledger = _load(here / "trials.json")
    if isinstance(ledger, list):
        lab7 = [r for r in ledger if r.get("lab", "lab7") == "lab7"]
        by = Counter((r.get("hyp"), r.get("split")) for r in lab7)
        passes = sum(bool(r.get("passes")) for r in lab7)
        order = sorted(by.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))
        parts = ", ".join(f"{h} {sp} {n}" for (h, sp), n in order)
        rows += ["", f"Trials: {len(lab7)} lab 7 rows in `trials.json` ({parts}); {passes} pass."]
    if trials_total is not None:
        rows.append(f"Trials across labs 2-7: **{trials_total:,}**.")
    rows += [
        "",
        (
            "Decisions per research/lab7/PLAN.md (lab7-v1) and each `<W>/PREREG.md`; tables in `<W>/train.md`; "
            "adversarial reviews in `<W>/SKEPTIC.md`; the plain reading in READING.md. Generated by "
            "`research/lab7/results.py`. Paper only."
        ),
        "",
    ]
    return "\n".join(rows)


def main() -> None:
    import sys

    sys.path.insert(0, str(HERE))
    import core  # lab 7's core: the cross-lab trial count (it loads lab 4's core under its own name)

    (HERE / "RESULTS.md").write_text(render(HERE, core.trials_count()))
    print(HERE / "RESULTS.md")


if __name__ == "__main__":
    main()

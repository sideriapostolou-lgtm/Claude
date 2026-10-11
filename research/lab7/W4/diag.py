"""Lab 7 W4, POST-HOC reading (written after the TRAIN result was read; it decides nothing and adds no trial).

The TRAIN report showed a few round trips with gains far above a $20 ticket (one SPY "opens up or down" market
gave +$13,699 on one trip). They come from PLAN §4's entry convention: the entry fills at the first buyable print up
to 600 s after the signal, at THAT print's price, for the whole $20, whatever the print's size. When the price
collapses between the signal (inside the 0.15-0.85 band) and the fill, the fill can sit at 0.001: $20 then buys
20,000 contracts off a 40-contract print, and a stray bid later sells them all. This script re-walks every TRAIN cell
(all already in the ledger) and measures how much of each cell's result comes from entries filled outside the band,
then reads each cell again on the in-band entries only. It writes ``W4/train_diag.json`` and ``W4/train_diag.md``.

    python research/lab7/W4/diag.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import core as C  # noqa: E402

_spec = importlib.util.spec_from_file_location("lab7_w4_run", HERE / "run.py")
W4 = importlib.util.module_from_spec(_spec)
sys.modules["lab7_w4_run"] = W4
_spec.loader.exec_module(W4)

SPLIT = "train"
LO, HI = W4.BAND


def _mean_ci(f: pd.DataFrame, col: str = "net_us") -> dict:
    if not len(f):
        return {"n": 0, "mean": None, "ci95": [None, None]}
    v = f[col].to_numpy(dtype=float)
    ci = C.event_bootstrap_ci(v, f["event"].astype(str).to_numpy())
    return {"n": len(f), "mean": float(v.mean()), "ci95": [ci[0], ci[1]]}


def cell_diag(f: pd.DataFrame) -> dict:
    out_band = ((f["p_entry"] < LO - C.EPS) | (f["p_entry"] > HI + C.EPS)).to_numpy()
    jump = (f["p_entry"] - f["p_signal"]).abs().to_numpy() > 0.10
    inb = f[~out_band]
    gross = (inb["pnl_us"] + inb["fee_us"]) / C.TICKET_USD
    s_in = C.summarize(inb[C.TRIP_COLUMNS], SPLIT) if len(inb) else {"n": 0}
    chk = C.bar_checks(s_in) if len(inb) else {}
    return {
        "n": len(f),
        "mean_net_us": float(f["net_us"].mean()) if len(f) else None,
        "total_usd": float(f["pnl_us"].sum()),
        "out_band": {"n": int(out_band.sum()), "share": float(out_band.mean()) if len(f) else None,
                     "total_usd": float(f.loc[out_band, "pnl_us"].sum()),
                     "below": int((f["p_entry"] < LO - C.EPS).sum()), "above": int((f["p_entry"] > HI + C.EPS).sum())},
        "jump_over_10c": {"n": int(jump.sum()), "total_usd": float(f.loc[jump, "pnl_us"].sum())},
        "max_trip_usd": float(f["pnl_us"].max()) if len(f) else None,
        "trips_over_100usd": int((f["pnl_us"] > 100).sum()),
        "in_band": {**_mean_ci(inb), "gross_mean": float(gross.mean()) if len(inb) else None,
                    "stress_mean": float(inb["net_stress"].mean()) if len(inb) else None,
                    "win_rate": float((inb["net_us"] > 0).mean()) if len(inb) else None,
                    "checks_1_5": chk, "passes_1_5": bool(chk) and all(chk.values()),
                    "max_trip_usd": float(inb["pnl_us"].max()) if len(inb) else None},
    }


def main() -> int:
    train = json.loads((HERE / "train.json").read_text())
    counted = {r["cell"] for r in json.loads(C.LEDGER.read_text()) if r.get("hyp") == "W4" and r.get("split") == SPLIT}
    assert set(W4.CELLS) <= counted, "a post-hoc reading may only re-read cells already in the ledger"
    want = {c["cell"]: c["summary"] for c in train["cells"]}
    u = W4.universe(SPLIT)
    groups: dict[str, list[str]] = {}
    for key in W4.CELLS:
        groups.setdefault(W4.CELLS[key].entry.key, []).append(key)
    cells: dict[str, dict] = {}
    best_top: list[dict] = []
    for ekey, keys in groups.items():
        arr, _, _ = W4.evaluate(u, keys)
        for key in keys:
            f = W4.decode(arr, arr["cell"] == W4.CELL_CODE[key], u)
            d = cell_diag(f)
            assert d["n"] == want[key]["n"], f"re-walk differs from train.json for {key}"
            if d["n"]:
                assert math.isclose(d["mean_net_us"], want[key]["mean_net_us"], rel_tol=1e-9, abs_tol=1e-12)
            cells[key] = d
            if key == train["best"]:
                top = f.sort_values("pnl_us", ascending=False).head(8)
                best_top = [{"id": r.id, "event": r.event, "t_signal": r.t_signal, "p_signal": r.p_signal,
                             "p_entry": r.p_entry, "entry_print_size": r.entry_print_size, "shares": r.shares,
                             "p_exit": r.p_exit, "reason": r.reason, "pnl_us": r.pnl_us}
                            for r in top.itertuples(index=False)]
        del arr
        print(f"W4 diag: {ekey} re-walked", flush=True)
    sel = [k for k in W4.CELLS if W4.CELLS[k].selectable and cells[k]["n"]]
    doc = {
        "hyp": "W4", "split": SPLIT, "kind": "post-hoc reading (decides nothing, adds no trial)",
        "plan_sha256": C.prereg_sha256(C.PLAN), "prereg_sha256": C.prereg_sha256(W4.PREREG),
        "best": train["best"], "best_top_trips": best_top, "cells": cells,
        "summary": {
            "cells": len(sel),
            "cells_with_out_band_entries": sum(1 for k in sel if cells[k]["out_band"]["n"]),
            "out_band_trips": int(sum(cells[k]["out_band"]["n"] for k in sel)),
            "trips": int(sum(cells[k]["n"] for k in sel)),
            "in_band_mean_positive": sum(1 for k in sel if (cells[k]["in_band"]["mean"] or -1) > 0),
            "in_band_ci_lower_positive": sum(1 for k in sel if (cells[k]["in_band"]["ci95"][0] or -1) > 0),
            "in_band_gross_positive": sum(1 for k in sel if (cells[k]["in_band"]["gross_mean"] or -1) > 0),
            "in_band_pass_1_5": sum(1 for k in sel if cells[k]["in_band"]["passes_1_5"]),
            "max_in_band_mean": max((cells[k]["in_band"]["mean"] for k in sel), default=None),
            "in_band_not_above_full": sum(1 for k in sel if cells[k]["in_band"]["mean"] is not None
                                          and cells[k]["in_band"]["mean"] <= cells[k]["mean_net_us"] + 1e-12),
        },
    }
    (HERE / "train_diag.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    (HERE / "train_diag.md").write_text(render(doc))
    print(json.dumps(doc["summary"]), flush=True)
    return 0


def _f(v, nd=4):
    return "-" if v is None or (isinstance(v, float) and not math.isfinite(v)) else (f"{v:.{nd}f}" if isinstance(v, float)
                                                                                     else str(v))


def render(doc: dict) -> str:
    s = doc["summary"]
    lines = ["# Lab 7 W4, TRAIN: entries filled outside the band (post-hoc reading)", "",
             "Written by `W4/diag.py` AFTER the TRAIN result was read. It re-walks the 200 TRAIN cells already in the "
             "ledger (the re-walk reproduces `train.json` exactly), decides nothing and adds no trial. The TRAIN "
             "verdict stays NO_EDGE_TRAIN.", "",
             "## What it shows", "",
             f"- Of {s['trips']:,} round trips over {s['cells']} selectable cells, {s['out_band_trips']:,} "
             f"({100 * s['out_band_trips'] / max(s['trips'], 1):.2f} %) filled their entry OUTSIDE the 0.15-0.85 band, "
             "because the price moved between the signal print and the first buyable print up to 10 minutes later "
             "(PLAN §4 fills at that print's price, for the whole $20, whatever its size).",
             "- A fill near 0.001 buys about 20,000 contracts with $20, and a later stray bid sells them all: one such "
             "trip made +$13,699 in TRAIN. A loss is capped at the $20 ticket plus fees, a gain is not, so these fills "
             "add a long right tail (most of them still lose: a fill at 0.05 that settles at 0 loses the ticket, a "
             "fill above 0.85 has little room to win).",
             f"- On the in-band entries only, {s['in_band_mean_positive']} of {s['cells']} cells have a positive mean "
             f"after the US fee, {s['in_band_ci_lower_positive']} a CI95 lower bound above zero, "
             f"{s['in_band_gross_positive']} a positive mean before any fee; {s['in_band_pass_1_5']} clear the bar's "
             f"conditions 1-5. The highest in-band mean is {_f(s['max_in_band_mean'])} per $.",
             f"- Without them, {s['in_band_not_above_full']} of {s['cells']} cells read the same or worse and the "
             "others read better, but every in-band mean stays below zero, so the NO EDGE verdict does not rest on "
             "these fills.",
             "- For the architect: the same convention applies to W1-W3. A fill whose price is far from the signal "
             "(or outside the band) at a print much smaller than our contracts is a fill that could not happen at "
             "size; a cap (fill only inside the band, or only up to the print's size) would be a plan amendment.", "",
             f"## The best TRAIN cell's largest trips (`{doc['best']}`)", "",
             "| market | event | p signal | p entry | entry print size | contracts | p exit | exit | P&L $ |",
             "|---|---|---|---|---|---|---|---|---|"]
    for t in doc["best_top_trips"]:
        lines.append(f"| {t['id']} | {t['event']} | {_f(t['p_signal'], 3)} | {_f(t['p_entry'], 3)} | "
                     f"{_f(t['entry_print_size'], 1)} | {_f(t['shares'], 0)} | {_f(t['p_exit'], 3)} | {t['reason']} | "
                     f"{_f(t['pnl_us'], 2)} |")
    lines += ["", "## Every cell", "",
              "`out` = entries filled outside 0.15-0.85 (n and their total $); `in-band` = the cell read again "
              "without them (mean net per $ under the US fee, event-bootstrap CI95, before any fee, stress).", "",
              "| cell | n | mean net | total $ | out n | out $ | max trip $ | in-band n | in-band mean | in-band CI95 | "
              "in-band gross | in-band stress | in-band max trip $ | in-band 1-5 |",
              "|" + "---|" * 14]
    for k, c in doc["cells"].items():
        ib = c["in_band"]
        ci = ib["ci95"]
        lines.append(f"| `{k.replace('|', chr(92) + '|')}` | {c['n']} | {_f(c['mean_net_us'])} | {_f(c['total_usd'], 0)} | "
                     f"{c['out_band']['n']} | {_f(c['out_band']['total_usd'], 0)} | {_f(c['max_trip_usd'], 0)} | "
                     f"{ib['n']} | {_f(ib['mean'])} | [{_f(ci[0])}, {_f(ci[1])}] | {_f(ib['gross_mean'])} | "
                     f"{_f(ib['stress_mean'])} | {_f(ib['max_trip_usd'], 0)} | {'yes' if ib['passes_1_5'] else 'no'} |")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    if sys.argv[1:] == ["--render"]:  # rewrite train_diag.md from train_diag.json only
        (HERE / "train_diag.md").write_text(render(json.loads((HERE / "train_diag.json").read_text())))
        sys.exit(0)
    sys.exit(main())

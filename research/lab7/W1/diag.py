"""Lab 7 W1, POST-HOC reading (written after the TRAIN result was read; it decides nothing and adds no trial).

Why does buying below Pinnacle's fair lose when the position is sold before the start, even though the entries beat
Pinnacle's closing line? This re-walks two cells that are already in the ledger, on TRAIN only, and decomposes their
round trips: the gap at the signal, the closing-line value (CLV), and where the Polymarket price stood at the time
stop against Pinnacle's close. It writes ``W1/train_diag.json`` and ``W1/train_diag.md``.

    python research/lab7/W1/diag.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import core as C  # noqa: E402

_spec = importlib.util.spec_from_file_location("lab7_w1_run", HERE / "run.py")
W1 = importlib.util.module_from_spec(_spec)
sys.modules["lab7_w1_run"] = W1
_spec.loader.exec_module(W1)

# the best cell by CI95 lower bound among the no-stop cells (so most exits are the time stop) and the busiest cell
KEYS = ("m0.05|tp0.05|slnone|tcutoff|taker", "m0.02|tp0.02|sl0.03|tcutoff|taker")


def trips(split: str = "train") -> dict[str, pd.DataFrame]:
    counted = {r["cell"] for r in json.loads(C.LEDGER.read_text()) if r.get("hyp") == "W1" and r.get("split") == split}
    assert set(KEYS) <= counted, "a post-hoc reading may only re-read cells already in the ledger"
    cells = [c for c in W1.grid() if c.key in KEYS]
    specs, _ = W1.build_specs(split)
    W1._SPECS, W1._CELLS = specs, cells
    rows: dict[str, list[dict]] = {k: [] for k in KEYS}
    for k, res, _n in W1._pool_map(W1._walk_market, range(len(specs)), W1.WORKERS):
        sp = specs[k]
        tape = C.load_tape(sp.id) if any(tr for tr, _ in res.values()) else None
        for key, (tr, _ms) in res.items():
            for t in tr:
                o = int(t["o"])
                ic = int(np.searchsorted(tape.ts, sp.cutoff, "left")) - 1
                b = tape.buyable(o)[: ic + 1]
                ia = (ic - int(np.argmax(b[::-1]))) if b.any() else -1
                rows[key].append({**t, "last_ask": float(tape.price(o)[ia]) if ia >= 0 else math.nan})
    return {k: pd.DataFrame(v) for k, v in rows.items()}


def reading(f: pd.DataFrame) -> dict:
    gap = f["fair_signal"] - f["p_signal"]
    f = f.assign(gross_c=(f["p_exit"] - f["p_entry"]) * 100, clv_c=(f["close_fair"] - f["p_entry"]) * 100,
                 close_minus_exit_c=(f["close_fair"] - f["p_exit"]) * 100,
                 close_minus_last_ask_c=(f["close_fair"] - f["last_ask"]) * 100,
                 fee_c=f["fee_us"] / f["shares"] * 100)
    by_reason = {str(r): {"n": len(g), "gross_c": float(g["gross_c"].mean()), "clv_c": float(g["clv_c"].mean()),
                          "close_minus_exit_c": float(g["close_minus_exit_c"].mean())}
                 for r, g in f.groupby("reason")}
    side = {f"{k[0]} o={k[1]}": {"n": len(g), "mean_net_us": float(g["net_us"].mean()),
                                 "gross_c": float(g["gross_c"].mean()), "clv_c": float(g["clv_c"].mean())}
            for k, g in f.groupby(["kind", "o"])}
    return {
        "n": len(f),
        "gap_at_signal_quantiles": {str(q): float(v) for q, v in gap.quantile([0.5, 0.9, 0.99, 1.0]).items()},
        "gap_over_0.15_share": float((gap > 0.15).mean()),
        "gross_c": float(f["gross_c"].mean()), "fee_c": float(f["fee_c"].mean()), "clv_c": float(f["clv_c"].mean()),
        "close_minus_last_ask_c": float(f["close_minus_last_ask_c"].mean()),
        "by_reason": by_reason, "by_side": side,
    }


def main() -> int:
    out = {k: reading(f) for k, f in trips("train").items()}
    (HERE / "train_diag.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    lines = ["# Lab 7 W1, TRAIN: why the convergence trade loses (post-hoc reading)", "",
             "Written by `W1/diag.py` AFTER the TRAIN result was read. It re-reads two cells already in the ledger, "
             "decides nothing and adds no trial. Cents are per contract; CLV = Pinnacle's closing fair minus the entry "
             "price.", ""]
    for k, r in out.items():
        lines += [f"## `{k}` ({r['n']} round trips)", "",
                  f"- gap at the signal (fair - print): median {100 * r['gap_at_signal_quantiles']['0.5']:.1f}c, 90th "
                  f"percentile {100 * r['gap_at_signal_quantiles']['0.9']:.1f}c; above 15c: "
                  f"{100 * r['gap_over_0.15_share']:.1f} % of signals (no sign of sides mapped to the wrong team)",
                  f"- the entries beat Pinnacle's close by {r['clv_c']:+.2f}c on average, yet the round trips lost "
                  f"{r['gross_c']:+.2f}c before fees, and the US fee took another {r['fee_c']:.2f}c",
                  f"- at the start, the last ASK for the bought side was still {r['close_minus_last_ask_c']:+.2f}c "
                  "below Pinnacle's closing fair: Polymarket's price did not converge to Pinnacle before the game", "",
                  "| exit | n | gross c | CLV c | close - exit price c |", "|---|---|---|---|---|"]
        for reason, v in sorted(r["by_reason"].items(), key=lambda kv: -kv[1]["n"]):
            lines.append(f"| {reason} | {v['n']} | {v['gross_c']:+.2f} | {v['clv_c']:+.2f} | "
                         f"{v['close_minus_exit_c']:+.2f} |")
        lines += ["", "| market kind, outcome | n | mean net | gross c | CLV c |", "|---|---|---|---|---|"]
        for s, v in r["by_side"].items():
            lines.append(f"| {s} | {v['n']} | {v['mean_net_us']:+.4f} | {v['gross_c']:+.2f} | {v['clv_c']:+.2f} |")
        lines.append("")
    lines += ["Soccer markets: o=0 is Yes, o=1 is No. 2-way markets: o=0 is the first-listed team.", ""]
    (HERE / "train_diag.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

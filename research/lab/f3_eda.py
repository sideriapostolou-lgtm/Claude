"""F3 lifecycle: exploratory event study on TRAIN only (every cut is logged and counted as a look).

For each coin and each check time T (minutes after the graduation bar), features use bars <= i only;
the forward GROSS return is open[i+1] -> close[i+1+H] (no costs). Descriptive; feeds hypotheses only.

    python research/lab/f3_eda.py checkpoints
    python research/lab/f3_eda.py count
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from harness import LAB, load_coins  # noqa: E402

OUT = LAB / "f3"
OUT.mkdir(parents=True, exist_ok=True)
LOG = OUT / "eda_log.jsonl"


def grad_index(c) -> int:
    return int(np.searchsorted(c.ts + c.dur, c.graduated_ts, side="left"))


def log(cut: str, rows: dict) -> None:
    with LOG.open("a") as fh:
        fh.write(json.dumps({"cut": cut, **rows}, default=float) + "\n")


def fwd(c, i: int, h: int) -> tuple[float, float] | None:
    """gross return open[i+1] -> close[i+1+h], and min low / entry over the window."""
    if i + 1 + h >= c.n:
        return None
    e = c.o[i + 1]
    return c.c[i + 1 + h] / e - 1, c.l[i + 1:i + 2 + h].min() / e - 1


def summarize(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    a = np.asarray(xs)
    return {"n": len(a), "mean": round(100 * a.mean(), 2), "median": round(100 * np.median(a), 2),
            "win": round(100 * (a > 0).mean(), 1), "p10": round(100 * np.percentile(a, 10), 1),
            "p90": round(100 * np.percentile(a, 90), 1)}


def features(c, g: int, i: int) -> dict:
    s = slice(g, i + 1)
    peak = c.h[s].max()
    gc = c.c[g]
    v15 = c.v[max(g, i - 14):i + 1].sum()
    v60 = c.v[max(g, i - 59):i + 1].sum()
    first15 = c.v[g:g + 15].sum()
    w = slice(max(g, i - 29), i + 1)
    rng30 = c.h[w].max() / max(c.l[w].min(), 1e-18)
    return {"rel_peak": c.c[i] / peak, "rel_grad": c.c[i] / gc, "v15": v15, "v60": v60,
            "decay": v15 / max(first15, 1.0), "rng30": rng30, "mcap": c.c[i] * c.supply,
            "instant": (c.graduated_ts - c.created_ts) < 5}


def checkpoints(split: str = "train") -> None:
    cs = load_coins(split=split)
    T_list = [15, 30, 60, 120, 240]
    H = 60
    for T in T_list:
        groups: dict[str, list[float]] = {}
        for c in cs:
            g = grad_index(c)
            i = g + T
            r = fwd(c, i, H)
            if r is None:
                continue
            f = features(c, g, i)
            alive = f["v15"] >= 1500 and f["mcap"] >= 6000
            key_alive = "alive" if alive else "dead"
            groups.setdefault(f"all", []).append(r[0])
            groups.setdefault(key_alive, []).append(r[0])
            if alive:
                kind = "inst" if f["instant"] else "org"
                groups.setdefault(f"alive_{kind}", []).append(r[0])
                rp = "rp<0.3" if f["rel_peak"] < 0.3 else "rp0.3-0.7" if f["rel_peak"] < 0.7 else "rp>=0.7"
                groups.setdefault(f"alive_{rp}", []).append(r[0])
                rc = "rng30<1.3" if f["rng30"] < 1.3 else "rng30<2" if f["rng30"] < 2 else "rng30>=2"
                groups.setdefault(f"alive_{rc}", []).append(r[0])
                dc = "decay<0.1" if f["decay"] < 0.1 else "decay<0.5" if f["decay"] < 0.5 else "decay>=0.5"
                groups.setdefault(f"alive_{dc}", []).append(r[0])
        rows = {k: summarize(v) for k, v in sorted(groups.items())}
        log(f"checkpoint T={T} H={H} split={split}", {"groups": rows})
        print(f"--- T={T}min after grad, gross fwd {H}min (open[i+1] -> close[i+1+H])")
        for k, v in rows.items():
            print(f"   {k:16s} {v}")


def count() -> None:
    n_cuts, n_groups = 0, 0
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        r = json.loads(line)
        n_cuts += 1
        n_groups += len(r.get("groups", {})) or 1
    print({"eda_cuts": n_cuts, "eda_groups_looked_at": n_groups})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "checkpoints"
    {"checkpoints": checkpoints, "count": count}[cmd]()

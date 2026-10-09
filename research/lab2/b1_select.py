"""B1 fetch selection for the backfill phase P4b (research/flow/backfill.py): the S1 universe of each split.

Research only. Counts and coin windows only: no prices, no returns, nothing a strategy could tune on.

S1 universe = common.py usable (SOL-quoted, not Mayhem, virtual reserve known, B2 window [g, g + 180 min)
COMPLETELY consolidated under :func:`common.completeness_from_flow`) AND creation scanned (``curve_partial`` False)
AND ``created_exact`` AND ``grad_delay_s > 5`` (:func:`s1.universe_mask`). D1's universe (G1-chain ORGANIC) lies
inside it, and both modules' B1 coverage gates use exactly this denominator (``s1.coverage_counts``,
``d1.b1_coverage``). Every filter is a graduation-time fact (or our collection status), so the selection is causal.

Window per coin: [c_ts, g_ts + 7200) = S1's checkpoints g + 6 ... g + 120 min and D1's decisions tau in
[g + 600, g + 7180] with flow exits read up to g + 7200 (both refuse tau >= g + 7200).

Writes ``FLOW/b1_select.json``::

    {"splits": {"train": {"coins": [[mint, pool, lo, hi], ...], "usable": n, "s1_universe": n, ...}, ...},
     "snapshot": {"graduates.parquet_mtime": ...}, ...}

Re-run it after every consolidation (newly usable coins appear once their B2 window is complete)::

    python research/lab2/b1_select.py [--flow DIR] [--splits train,val,test]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import common as C  # noqa: E402
import s1 as S1  # noqa: E402

VERSION = "b1-select-v1"
B1_HORIZON_S = S1.B1_HORIZON_S           # 7200: S1 / D1 read B1 rows with ts < g + 7200
DEFAULT_SPLITS = ("train", "val", "test", "confirm", "final_train", "final_val", "final_test")
TABLES = ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet")


def select_split(ds: C.Dataset) -> dict:
    """Counts + coin windows of the S1 universe of one Dataset (no prices, no returns)."""
    co = ds.coins
    if len(co):
        mask = S1.universe_mask(co)
        uni = co[mask].sort_values(["created_ts", "mint"])
        gd = pd.to_numeric(co["grad_delay_s"], errors="coerce")
        no_create = co["curve_partial"].astype(bool) | ~co["created_exact"].astype(bool)
        instant = ~no_create & ~(gd > S1.FACTORY_DELAY_S)
    else:
        uni, no_create, instant = co, pd.Series(dtype=bool), pd.Series(dtype=bool)
    coins = [[str(r.mint), str(r.pool), int(r.created_ts), int(r.g_ts) + B1_HORIZON_S]
             for r in uni.itertuples(index=False)]
    excl = ds.excluded["exclude_reason"].value_counts().to_dict() if len(ds.excluded) else {}
    lo, hi = C.SPLIT_BOUNDS.get(ds.split, (None, None))
    return {
        "bounds_utc": [C.utc_str(lo), C.utc_str(hi)] if lo is not None else None,
        "graduates_in_split": int(len(co) + len(ds.excluded)),
        "usable": int(len(co)),
        "not_usable": {str(k): int(v) for k, v in sorted(excl.items())},
        "s1_universe": len(coins),
        "not_in_universe": {"creation_not_scanned": int(no_create.sum()),
                            "instant_or_unknown_grad_delay": int(instant.sum())},
        "window_hours": round(sum(h - lo_ for _m, _p, lo_, h in coins) / 3600, 1),
        "coins": coins,
    }


def select_from_frames(g: pd.DataFrame, c: pd.DataFrame, b: pd.DataFrame, splits=DEFAULT_SPLITS,
                       census: C.Census | None = None, sol=None, completeness: C.Completeness | None = None) -> dict:
    census = census if census is not None else C.Census.load()
    sol = sol or C.load_sol_usd()
    out = {}
    for split in splits:
        ds = C.Dataset.from_frames(split, g, c, b, census=census, sol=sol, guard=False, completeness=completeness)
        out[split] = select_split(ds)
    return out


def select(flow: Path | None = None, splits=DEFAULT_SPLITS) -> dict:
    """The selection document for the real FLOW tables (raw-chunk completeness, as common.load uses)."""
    f = Path(flow or C.flow_dir())
    for _ in range(3):
        stamp = [(f / n).stat().st_mtime for n in TABLES]
        g, c, b = (C._read_parquet(f / n) for n in TABLES)
        comp = C.completeness_from_flow(f)
        if stamp == [(f / n).stat().st_mtime for n in TABLES]:
            break
    sp = select_from_frames(g, c, b, splits=splits, completeness=comp)
    return {
        "version": VERSION, "written_utc": C.utc_str(time.time()), "flow": str(f),
        "rule": "S1 universe: common usable (B2 window complete under completeness_from_flow) & creation scanned & "
                "created_exact & grad_delay_s > 5; window [c_ts, g_ts + 7200)",
        "snapshot": {f"{n}_mtime": s for n, s in zip(TABLES, stamp)} | {"completeness_snapshot_utc": comp.snapshot_utc},
        "splits": sp,
    }


def write(doc: dict, path: Path) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")))
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--flow", default=None)
    ap.add_argument("--splits", default=",".join(DEFAULT_SPLITS))
    ap.add_argument("--out", default=None, help="default FLOW/b1_select.json")
    args = ap.parse_args(argv)
    f = Path(args.flow or C.flow_dir())
    doc = select(f, tuple(s.strip() for s in args.splits.split(",") if s.strip()))
    write(doc, Path(args.out) if args.out else f / "b1_select.json")
    print(json.dumps({s: {k: v for k, v in d.items() if k != "coins"} for s, d in doc["splits"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

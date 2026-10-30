"""K1 deliberation driver: fill the decision cache for ONE desk config on ONE split, so the three configs can run in
parallel processes (one per config) and ``k1.py --stage <split>`` afterwards scores from the cache with zero API
calls. Pure cache filling: no returns are read, no stage file is written, nothing is scored here.

    ANTHROPIC_API_KEY=... python research/lab2/k1_deliberate.py --split train --config panel --budget-usd 9
    python research/lab2/k1_deliberate.py --split train --config panel --status      # cached / needed, no API

Resumable: a re-run skips every cached decision. Refuses TEST without LAB2_ALLOW_TEST=1 (the one-look rule is
about reading outcomes, but the deliberation pass reads the split's bars, so the same flag is required).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import desk_core as D  # noqa: E402
import k1 as K  # noqa: E402


def _subset(ds: C.Dataset, mints: list[str]) -> C.Dataset:
    """A Dataset view over ``mints`` only (same coins objects, same split, same coverage)."""
    import copy

    sub = copy.copy(ds)
    keep = set(mints)
    sub.coins = ds.coins[ds.coins["mint"].isin(keep)].reset_index(drop=True)
    if getattr(ds, "_cd", None) is not None:
        sub._cd = {m: cd for m, cd in ds._cd.items() if m in keep}
    return sub


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=("train", "val", "test"), required=True)
    ap.add_argument("--config", choices=tuple(D.CONFIGS), required=True)
    ap.add_argument("--budget-usd", type=float, required=True)
    ap.add_argument("--status", action="store_true", help="count cached vs needed decisions and exit (no API)")
    ap.add_argument("--shard", default=None,
                    help="i/n: only coins with index %% n == i (parallel workers share the cache)")
    a = ap.parse_args(argv)
    if a.split == "test" and os.environ.get("LAB2_ALLOW_TEST") != "1":
        print("REFUSED: TEST deliberation needs LAB2_ALLOW_TEST=1 (the judge must have read VAL)", file=sys.stderr)
        return 2
    ds = C.load(a.split, _internal=(a.split == "val"))
    if a.shard:
        i, n = (int(x) for x in a.shard.split("/"))
        keep = [m for k, m in enumerate(ds.mints) if k % n == i]
        ds = ds.subset(keep) if hasattr(ds, "subset") else _subset(ds, keep)
    if a.status:
        out = K.deliberate_split(ds, [a.config], None, D.Budget(max_usd=0.0), K.CACHE)
        print(json.dumps({"split": a.split, "config": a.config, **{k: v for k, v in out.items() if k != "buys"}}))
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("REFUSED: ANTHROPIC_API_KEY is not set in the environment", file=sys.stderr)
        return 2
    client = D.RealDeskClient()
    budget = D.Budget(max_usd=a.budget_usd)
    t0 = time.time()
    before = K.CACHE.count(a.config)
    try:
        out = K.deliberate_split(ds, [a.config], client, budget, K.CACHE)
    except D.BudgetExceeded as e:
        print(f"BUDGET: {e}; {K.CACHE.count(a.config) - before} new decisions cached in {time.time() - t0:.0f} s; "
              f"re-run to resume", file=sys.stderr)
        return 3
    out["new_cached"] = K.CACHE.count(a.config) - before
    out["seconds"] = round(time.time() - t0)
    print(json.dumps({"split": a.split, "config": a.config, **out}))
    return 0 if out["undecided"] == 0 else 4


if __name__ == "__main__":
    sys.exit(main())

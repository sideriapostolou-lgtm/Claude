"""Lifetime volume of the other BTC families (family_volume.py output).

usage: python -I analyze_families.py FAMILY_VOLUME.jsonl OUT.json
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

rows = [json.loads(x) for x in open(sys.argv[1])]


def q(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    pick = lambda p: round(xs[min(len(xs) - 1, int(p * len(xs)))], 2)  # noqa: E731
    return {"p10": pick(0.1), "median": pick(0.5), "p90": pick(0.9), "max": round(xs[-1], 2),
            "mean": round(sum(xs) / len(xs), 2)}


fam = defaultdict(lambda: {"events": set(), "markets": 0, "traded": 0, "m_notional": [], "ev_notional": defaultdict(float),
                           "fees": set(), "ticks": set(), "minq": set()})
for r in rows:
    f = fam[r["family"]]
    f["events"].add(r["event"])
    f["markets"] += 1
    b = r.get("book") or {}
    n = float(b.get("notional") or 0)
    s = float(b.get("shares") or 0)
    f["traded"] += 1 if s > 0 else 0
    f["m_notional"].append(n)
    f["ev_notional"][r["event"]] += n
    f["fees"].add(r.get("fee"))
    f["ticks"].add(r.get("tick"))
    f["minq"].add(r.get("min_qty"))
out = {}
for k, f in fam.items():
    out[k] = {"events": len(f["events"]), "markets": f["markets"], "markets_traded": f["traded"],
              "per_market_notional_usd": q(f["m_notional"]), "per_event_notional_usd": q(list(f["ev_notional"].values())),
              "feeCoefficient": sorted(x for x in f["fees"] if x is not None), "tick": sorted(x for x in f["ticks"] if x),
              "minimumTradeQty": sorted(x for x in f["minq"] if x)}
Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
for k, v in out.items():
    print(k, json.dumps(v))

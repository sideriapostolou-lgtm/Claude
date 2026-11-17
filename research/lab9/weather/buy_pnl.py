"""Hold-to-resolution PnL of each BUY fill (shares x payout - cost), using the real resolution; grouped by price bin,
local hour and lock class. Ignores later sells (so it is the value of the entry decision itself)."""
import json, sys, collections
from pathlib import Path
RAW = Path(__file__).parent / "raw"
R = json.load(open(RAW / "pm_resolutions.json"))
def run(label):
    d = json.load(open(RAW / f"lock_{label}.json"))
    by = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
    for x in d:
        r = R.get(x.get("cid"))
        if not r or x["outcome"] not in r["outcomes"]: continue
        pay = r["payout"][r["outcomes"].index(x["outcome"])]
        sh = x["usdc"] / x["price"] if x["price"] > 0 else 0
        pnl = sh * pay - x["usdc"]
        p = x["price"]
        pb = "<0.02" if p < 0.02 else "0.02-0.05" if p < 0.05 else "0.05-0.10" if p < 0.10 else "0.10-0.25" if p < 0.25 else "0.25-0.50" if p < 0.5 else "0.50-0.90" if p < 0.9 else ">=0.90"
        for key in (("ALL",), ("price", pb), ("cls", x["cls"]), ("hour", "pre" if x["local_hrs"] < 0 else f"{int(x['local_hrs']//6)*6:02d}h")):
            b = by[key]; b[0] += 1; b[1] += x["usdc"]; b[2] += pnl; b[3] += pay > 0.5
    print(f"{label}: key, fills, usdc, hold-PnL, PnL/usdc, win rate")
    for k in sorted(by, key=str):
        n, u, pnl, w = by[k]
        print(f"  {str(k):28s} {n:6d} {u:10.0f} {pnl:10.0f} {pnl/u if u else 0:7.3f} {w/n:6.3f}")
if __name__ == "__main__":
    run(sys.argv[1])

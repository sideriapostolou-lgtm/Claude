"""Fetch /markets/{slug}/book from the PUBLIC gateway (no key) for a target list, ~3 req/s, keep only stats + top of
book (the full ladder is not needed). Resumable: rows already in the output file are skipped."""

import json
import sys
import time
from pathlib import Path

import requests

GATEWAY = "https://gateway.polymarket.us/v1"
UA = {"User-Agent": "nightcrawler-research/venue-map (public market data)"}
targets = json.load(open(sys.argv[1]))["all"]
out = Path(sys.argv[2])
done = {}
if out.exists():
    for line in out.read_text().splitlines():
        row = json.loads(line)
        done[row["slug"]] = row
fh = out.open("a")
n = 0
for slug in targets:
    if slug in done:
        continue
    row = {"slug": slug, "fetched": time.time()}
    for attempt in range(4):
        try:
            r = requests.get(f"{GATEWAY}/markets/{slug}/book", headers=UA, timeout=30)
        except requests.RequestException as e:
            row["error"] = type(e).__name__
            time.sleep(2.0 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            row["error"] = f"HTTP {r.status_code}"
            time.sleep(3.0 * (attempt + 1))
            continue
        if r.status_code != 200:
            row["error"] = f"HTTP {r.status_code}"
            break
        md = (r.json() or {}).get("marketData") or {}
        bids, offers = md.get("bids") or [], md.get("offers") or []
        row.pop("error", None)
        row.update(
            {
                "state": md.get("state"),
                "stats": md.get("stats"),
                "n_bids": len(bids),
                "n_offers": len(offers),
                "bid": bids[0] if bids else None,
                "offer": offers[0] if offers else None,
                "bid_qty_total": sum(float(b.get("qty") or 0) for b in bids),
                "offer_qty_total": sum(float(o.get("qty") or 0) for o in offers),
            }
        )
        break
    fh.write(json.dumps(row) + "\n")
    fh.flush()
    n += 1
    if n % 100 == 0:
        print(n, flush=True)
    time.sleep(0.33)
print("done", n)

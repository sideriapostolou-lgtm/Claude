"""Polymarket US daily-high temperature markets: list open + recently closed, BBO and lifetime shares traded (public gateway)."""
import json, time, urllib.request, urllib.parse, sys
from pathlib import Path
RAW = Path(__file__).parent / "raw"
G = "https://gateway.polymarket.us/v1"
def get(path, params=None):
    url = G + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=30) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(3 * (i + 1)); continue
            if e.code == 404: return None
            time.sleep(1)
        except Exception: time.sleep(1)
    return None
out = []
for closed in ("false", "true"):
    for page in range(30):
        d = get("/markets", {"limit": 100, "offset": page * 100, "closed": closed, "categories": "climate"})
        ms = (d or {}).get("markets") or []
        out += [m for m in ms if m["slug"].startswith("tc-temp-")]
        if len(ms) < 100: break
        time.sleep(0.4)
json.dump(out, open(RAW / "pmus_temp_markets.json", "w"))
import collections
fam = collections.Counter(m["slug"].split("-")[2] for m in out)
print(len(out), fam)
print("dates:", min(m["slug"][-20:] for m in out), max(m["endDate"] for m in out), min(m["endDate"] for m in out))
rows = []
for m in [m for m in out if not m.get("closed")][:60]:
    b = get(f"/markets/{m['slug']}/bbo"); time.sleep(0.35)
    md = (b or {}).get("marketData", b) or {}
    rows.append((m["slug"], md.get("bestBid"), md.get("bestAsk"), md.get("bidShares"), md.get("askShares"), md.get("sharesTraded"), md.get("lastTradePx")))
for r in rows: print(r)
json.dump(rows, open(RAW / "pmus_temp_bbo_now.json", "w"))

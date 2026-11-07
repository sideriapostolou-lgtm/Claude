"""Who buys an already-decided weather bucket LATE (30+ min after the deciding observation) on Polymarket, and at
what price? Sample: markets the speed bots bought as LOCKED_WIN; public /trades per market (read-only)."""
import json, time, random, collections, statistics as st, urllib.request, urllib.parse, sys
from pathlib import Path
RAW = Path(__file__).parent / "raw"
def get(url, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=40) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(5 * (i + 1)); continue
            if e.code in (400, 404): return []
            time.sleep(2)
        except Exception: time.sleep(2)
    return None
locks = {}
for lab in ("HighTempTation", "Weatherstappen"):
    for x in json.load(open(RAW / f"lock_{lab}.json")):
        if x["cls"] != "LOCKED_WIN" or not x.get("cid"): continue
        k = (x["cid"], x["outcome"])
        locks[k] = min(locks.get(k, 1e18), x["ts"])  # earliest speed-bot buy ~ when the lock became public
random.seed(9)
keys = random.sample(sorted(locks), min(int(sys.argv[1]) if len(sys.argv) > 1 else 250, len(locks)))
rows = []
for i, (cid, outc) in enumerate(keys):
    t0 = locks[(cid, outc)]
    off = 0
    while off < 4000:
        d = get("https://data-api.polymarket.com/trades?" + urllib.parse.urlencode({"market": cid, "limit": 500, "offset": off, "takerOnly": "false"}))
        time.sleep(0.4)
        if not d: break
        for x in d:
            if x["side"] == "BUY" and x["outcome"] == outc:
                rows.append({"cid": cid, "wallet": x["proxyWallet"], "name": x.get("name") or x.get("pseudonym"), "price": x["price"], "size": x["size"],
                             "delay_min": (x["timestamp"] - t0) / 60})
        if len(d) < 500: break
        off += 500
    if i % 50 == 0: print(i, len(rows), file=sys.stderr, flush=True)
json.dump(rows, open(RAW / "slow_buyers_rows.json", "w"))
late = [r for r in rows if r["delay_min"] >= 30]
print("buys of the decided side:", len(rows), " of which 30+ min after lock:", len(late))
for lo, hi in ((-1e9, 0), (0, 5), (5, 30), (30, 120), (120, 1e9)):
    s = [r for r in rows if lo <= r["delay_min"] < hi]
    if s: print(f"  delay {lo:>6}-{hi:<6} min: fills {len(s):5d} shares {sum(r['size'] for r in s):9.0f}  median price {st.median(r['price'] for r in s):.3f}  share<=0.98 {sum(r['price']<=0.98 for r in s)/len(s):.2f}")
by = collections.defaultdict(lambda: {"mk": set(), "sh": 0.0, "px": [], "name": None})
for r in late:
    b = by[r["wallet"]]; b["mk"].add(r["cid"]); b["sh"] += r["size"]; b["px"].append(r["price"]); b["name"] = r["name"]
top = sorted(by.items(), key=lambda kv: -len(kv[1]["mk"]))[:20]
print("wallets buying the decided side 30+ min late (markets in sample, shares, median price):")
for w, b in top: print(" ", w, (b["name"] or "")[:20], len(b["mk"]), round(b["sh"]), round(st.median(b["px"]), 3))

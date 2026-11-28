"""Full public activity history for one wallet (data-api /activity, paged by time), read-only."""
import json, time, urllib.request, urllib.parse, sys
from pathlib import Path
OUT = Path(__file__).parent / "raw" / "activity"; OUT.mkdir(parents=True, exist_ok=True)
D = "https://data-api.polymarket.com/activity"
def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lab9-research"})
            with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(5 + 5 * i); continue
            if e.code == 400: return []
            time.sleep(2 + i)
        except Exception: time.sleep(2 + i)
    return None
def fetch(wallet, start=0, pace=0.4):
    f = OUT / f"{wallet}.json"
    seen = {}; t0 = start; end = int(time.time()) + 3600
    while True:
        q = urllib.parse.urlencode({"user": wallet, "limit": 500, "start": t0, "end": end, "sortBy": "TIMESTAMP", "sortDirection": "ASC"})
        d = get(f"{D}?{q}")
        time.sleep(pace)
        if not d: break
        n0 = len(seen)
        for x in d:
            k = (x["transactionHash"], x.get("asset"), x.get("type"), x.get("size"), x.get("side"), x.get("timestamp"))
            seen[k] = x
        last = d[-1]["timestamp"]
        if len(d) < 500: break
        if len(seen) == n0:  # >500 rows with the same timestamp: page with offset inside that second
            off = 500
            while True:
                q = urllib.parse.urlencode({"user": wallet, "limit": 500, "offset": off, "start": last, "end": last, "sortBy": "TIMESTAMP", "sortDirection": "ASC"})
                dd = get(f"{D}?{q}"); time.sleep(pace)
                if not dd: break
                for x in dd: seen[(x["transactionHash"], x.get("asset"), x.get("type"), x.get("size"), x.get("side"), x.get("timestamp"))] = x
                if len(dd) < 500: break
                off += 500
            last += 1
        t0 = last
        print(wallet[:10], len(seen), time.strftime("%Y-%m-%d", time.gmtime(last)), file=sys.stderr, flush=True)
    rows = sorted(seen.values(), key=lambda x: x["timestamp"])
    json.dump(rows, open(f, "w"))
    return len(rows)
if __name__ == "__main__":
    for w in sys.argv[1:]:
        print(w, fetch(w), flush=True)

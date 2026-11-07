"""Fetch closed positions (public data-api) for a pool of wallets; keep all rows, tag weather ones (read-only)."""
import json, time, urllib.request, urllib.parse, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
OUT = Path(__file__).parent / "raw" / "closed"
OUT.mkdir(parents=True, exist_ok=True)
D = "https://data-api.polymarket.com"
_lock = threading.Lock(); _last = [0.0]

def get(url, tries=6):
    for i in range(tries):
        with _lock:  # global pacing: <= ~4 req/s
            wait = 0.25 - (time.time() - _last[0])
            if wait > 0: time.sleep(wait)
            _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lab9-research"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(5 + 5 * i); continue
            if e.code in (400, 404): return []
            time.sleep(2 + i)
        except Exception:
            time.sleep(2 + i)
    return None

def fetch(wallet):
    f = OUT / f"{wallet}.json"
    if f.exists(): return wallet, "cached"
    rows = {}
    hit_cap = False
    for direction in ("DESC", "ASC"):
        off = 0
        new_in_dir = 0
        while True:
            q = urllib.parse.urlencode({"user": wallet, "limit": 50, "offset": off, "sortBy": "TIMESTAMP", "sortDirection": direction})
            d = get(f"{D}/closed-positions?{q}")
            if d is None or not isinstance(d, list) or not d:
                if off > 0 and direction == "DESC": hit_cap = True
                break
            before = len(rows)
            for x in d: rows[(x["asset"])] = x
            new_in_dir += len(rows) - before
            if direction == "ASC" and len(rows) == before: break  # overlapped DESC
            if len(d) < 50:
                if direction == "DESC": hit_cap = False
                break
            off += 50
            if direction == "DESC": hit_cap = True
        if direction == "DESC" and not hit_cap: break
    json.dump(list(rows.values()), open(f, "w"))
    return wallet, len(rows)

if __name__ == "__main__":
    wallets = [w.strip() for w in open(sys.argv[1]) if w.strip()]
    with ThreadPoolExecutor(3) as ex:
        for w, n in ex.map(fetch, wallets):
            print(w, n, flush=True)

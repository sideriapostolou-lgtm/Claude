"""Stage A: for every wallet on the pulled boards, fetch (1) the daily cumulative P&L series from
user-pnl-api and (2) the newest 500 activity rows from data-api. Read-only, keyless, public.

One worker thread per host, ~3 requests/s per host, backoff on 429. Resumable (skips files present).
Output: raw/pnl/<wallet>.json, raw/act/<wallet>.json
"""
import json
import sys
import threading
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
RAW = HERE / "raw"
PNL = RAW / "pnl"
ACT = RAW / "act"
PNL.mkdir(parents=True, exist_ok=True)
ACT.mkdir(parents=True, exist_ok=True)


def fetch(sess, url, params, gap=0.33):
    for attempt in range(8):
        try:
            r = sess.get(url, params=params, timeout=40)
        except requests.RequestException as e:
            print("net", e, file=sys.stderr)
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(6 * (attempt + 1))
            continue
        time.sleep(gap)
        if r.status_code != 200:
            return {"_status": r.status_code, "_text": r.text[:300]}
        return r.json()
    return {"_status": 429}


def wallets():
    b = json.loads((RAW / "boards.json").read_text())
    seen = []
    for rows in b.values():
        for r in rows:
            w = r["proxyWallet"].lower()
            if w not in seen:
                seen.append(w)
    return seen


def worker(kind, ws):
    sess = requests.Session()
    done = 0
    for w in ws:
        if kind == "pnl":
            f = PNL / f"{w}.json"
            if f.exists():
                continue
            d = fetch(sess, "https://user-pnl-api.polymarket.com/user-pnl",
                      {"user_address": w, "interval": "all", "fidelity": "1d"})
        else:
            f = ACT / f"{w}.json"
            if f.exists():
                continue
            d = fetch(sess, "https://data-api.polymarket.com/activity", {"user": w, "limit": 500})
        f.write_text(json.dumps(d))
        done += 1
        if done % 100 == 0:
            print(kind, done, file=sys.stderr, flush=True)


def main():
    ws = wallets()
    print("wallets", len(ws), file=sys.stderr)
    ts = [threading.Thread(target=worker, args=(k, ws)) for k in ("pnl", "act")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    print("done", file=sys.stderr)


if __name__ == "__main__":
    main()

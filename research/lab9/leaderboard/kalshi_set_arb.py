"""Live check (public, keyless): is there a complete-set arbitrage on Kalshi multi-bracket events right now?
For each open event in the given series: sum of best YES asks across all brackets (a full set pays exactly $1),
and sum of best NO asks (pays N-1). Kalshi taker fee per contract ~ ceil-per-order of 0.07*p*(1-p).
Usage: python3 kalshi_set_arb.py [SERIES ...]   (default: the live KXHIGH* series + KXBTC/KXETH range)
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

K = "https://api.elections.kalshi.com/trade-api/v2"
S = requests.Session()
RAW = Path(__file__).parent / "raw"


def get(url, **p):
    for a in range(5):
        r = S.get(url, params=p, timeout=30)
        if r.status_code == 429:
            time.sleep(2 * (a + 1))
            continue
        time.sleep(0.22)
        return r.json() if r.status_code == 200 else {}
    return {}


def main(series):
    rows = []
    for ser in series:
        ms = get(f"{K}/markets", series_ticker=ser, status="open", limit=200).get("markets", [])
        ev = defaultdict(list)
        for m in ms:
            ev[m["event_ticker"]].append(m)
        for et, mm in ev.items():
            yes_asks, no_asks, ok = [], [], True
            for m in mm:
                ob = (get(f"{K}/markets/{m['ticker']}/orderbook").get("orderbook_fp") or {})
                yb = [float(p) for p, q in (ob.get("yes_dollars") or [])]
                nb = [float(p) for p, q in (ob.get("no_dollars") or [])]
                # YES ask = 1 - best NO bid ; NO ask = 1 - best YES bid
                if not nb or not yb:
                    ok = False
                yes_asks.append(1 - max(nb) if nb else 1.0)
                no_asks.append(1 - max(yb) if yb else 1.0)
            fee = lambda p: 0.07 * p * (1 - p)  # noqa: E731
            sy = sum(yes_asks)
            sn = sum(no_asks)
            rows.append({"event": et, "n": len(mm), "sum_yes_ask": round(sy, 3),
                         "sum_yes_ask_plus_fee": round(sy + sum(fee(p) for p in yes_asks), 3),
                         "sum_no_ask": round(sn, 3), "no_set_payout": len(mm) - 1,
                         "sum_no_ask_plus_fee": round(sn + sum(fee(p) for p in no_asks), 3), "all_two_sided": ok})
    for r in sorted(rows, key=lambda r: r["sum_yes_ask_plus_fee"]):
        print(r)
    (RAW / "kalshi_set_arb.json").write_text(json.dumps(rows, indent=1))
    lt = [r for r in rows if r["sum_yes_ask_plus_fee"] < 1 or r["sum_no_ask_plus_fee"] < r["no_set_payout"]]
    print(f"{len(rows)} events checked; {len(lt)} with a full-set cost below payout after modelled fees")


if __name__ == "__main__":
    default = ["KXHIGHNY", "KXHIGHCHI", "KXHIGHMIA", "KXHIGHLAX", "KXHIGHAUS", "KXHIGHDEN", "KXHIGHPHIL",
               "KXHIGHTHOU", "KXHIGHTBOS", "KXHIGHTATL", "KXHIGHTDAL", "KXHIGHTDC", "KXHIGHTSFO", "KXHIGHTSEA"]
    main(sys.argv[1:] or default)

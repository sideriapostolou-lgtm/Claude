"""Live check (public, keyless): Kalshi crypto one-touch ladders priced against the same z model the
Polymarket ladder sellers appear to use. For each open strike: spot (Coinbase), 30d realized vol, days left,
z, one-touch fair NO, best NO ask (= 1 - best YES bid) and its size, and the cents of model edge.
"""
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from ladder_rule import ncdf  # noqa: E402

K = "https://api.elections.kalshi.com/trade-api/v2"
S = requests.Session()


def get(url, **p):
    for a in range(5):
        r = S.get(url, params=p, timeout=30)
        if r.status_code == 429:
            time.sleep(2 * (a + 1))
            continue
        time.sleep(0.25)
        return r.json()
    return {}


def spot_vol(product):
    c = S.get(f"https://api.exchange.coinbase.com/products/{product}/candles", params={"granularity": 3600},
              timeout=30).json()
    closes = [x[4] for x in sorted(c)]
    r = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    m = sum(r) / len(r)
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / len(r))
    return closes[-1], sd * math.sqrt(24 * 365)  # last 300 hours (~12.5 days) of hourly closes


def main():
    out = []
    sv = {"BTC": spot_vol("BTC-USD"), "ETH": spot_vol("ETH-USD")}
    for ser, coin, kind in (("KXBTCMAXMON", "BTC", "max"), ("KXETHMAXMON", "ETH", "max"), ("KXETHMINMON", "ETH", "min"),
                            ("KXBTCMAXY", "BTC", "max"), ("KXBTCMINY", "BTC", "min"), ("KXETHMAXY", "ETH", "max"),
                            ("KXBTCMINMON", "BTC", "min")):
        ms = get(f"{K}/markets", series_ticker=ser, status="open", limit=200).get("markets", [])
        s, vol = sv[coin]
        for m in ms:
            k = m.get("floor_strike") or m.get("cap_strike")
            if not k:
                continue
            end = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp()
            T = max((end - time.time()) / (365 * 86400), 1e-6)
            z = abs(math.log(float(k) / s)) / (vol * math.sqrt(T))
            fair_no = 1 - min(1, 2 * ncdf(-z))
            ob = get(f"{K}/markets/{m['ticker']}/orderbook").get("orderbook_fp") or {}
            yes_bids = ob.get("yes_dollars") or []
            best_yes_bid = max((float(p) for p, q in yes_bids), default=0.0)
            yes_bid_sz = sum(float(q) for p, q in yes_bids if float(p) == best_yes_bid) if yes_bids else 0
            no_ask = 1 - best_yes_bid if yes_bids else None
            out.append((ser, m["ticker"], float(k), round(T * 365, 1), round(z, 2), round(fair_no, 4),
                        no_ask, yes_bid_sz, round((fair_no - no_ask) * 100, 2) if no_ask else None,
                        float(m.get("volume_fp") or 0)))
    print(f"spot/vol (12.5d hourly): BTC {sv['BTC'][0]:.0f} {sv['BTC'][1]:.2f}  ETH {sv['ETH'][0]:.1f} {sv['ETH'][1]:.2f}")
    print("series ticker strike days z fairNO bestNOask size(at ask) edge_c volume")
    for row in sorted(out, key=lambda r: (r[0], r[2])):
        print(*row)
    (Path(__file__).parent / "raw" / "kalshi_touch_now.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()

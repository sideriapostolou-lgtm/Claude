"""Hourly BTC-USD / ETH-USD closes from Coinbase public candles (keyless), cached to raw/spot_<p>.json.
Usage: python3 spot.py BTC-USD 2025-01-01 2026-10-12
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAW = Path(__file__).parent / "raw"


def pull(product, start, end):
    f = RAW / f"spot_{product}.json"
    data = json.loads(f.read_text()) if f.exists() else {}
    t0 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    t1 = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp())
    sess = requests.Session()
    step = 300 * 3600
    t = t0
    while t < t1:
        if f"w{t}" in data:
            t += step
            continue
        for attempt in range(6):
            r = sess.get(f"https://api.exchange.coinbase.com/products/{product}/candles",
                         params={"granularity": 3600, "start": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                                 "end": datetime.fromtimestamp(min(t + step, t1), timezone.utc).isoformat()},
                         timeout=30)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            break
        for row in r.json() if r.status_code == 200 else []:
            data[str(row[0])] = row[4]  # close
        if r.status_code == 200:
            data[f"w{t}"] = 1
        t += step
        time.sleep(0.35)
    f.write_text(json.dumps(data))
    print(product, len(data))


if __name__ == "__main__":
    pull(sys.argv[1], sys.argv[2], sys.argv[3])

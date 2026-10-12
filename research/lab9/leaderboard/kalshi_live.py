"""Which Kalshi series in the owner's open categories have OPEN markets now (public, keyless).
Output: raw/kalshi_live.json {ticker: {title, category, frequency, open_markets, settlement_sources, sample}}
"""
import json
import time
from pathlib import Path

import requests

K = "https://api.elections.kalshi.com/trade-api/v2"
RAW = Path(__file__).parent / "raw"
CATS = {"Climate and Weather", "Crypto", "Commodities", "Financials", "Economics"}


def main():
    series = json.loads((RAW / "kalshi_series.json").read_text())["series"]
    pick = [s for s in series if s.get("category") in CATS and s.get("frequency") in
            ("daily", "hourly", "fifteen_min", "weekly")]
    out = {}
    sess = requests.Session()
    for s in pick:
        for attempt in range(5):
            r = sess.get(f"{K}/markets", params={"series_ticker": s["ticker"], "status": "open", "limit": 200},
                         timeout=30)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            break
        time.sleep(0.25)
        ms = r.json().get("markets", []) if r.status_code == 200 else []
        if not ms:
            continue
        vol = sum(float(m.get("volume_24h") or m.get("volume_24h_fp") or 0) for m in ms)
        out[s["ticker"]] = {
            "title": s["title"], "category": s["category"], "frequency": s["frequency"],
            "open_markets": len(ms), "vol24h_contracts": vol,
            "settlement_sources": s.get("settlement_sources"),
            "sample": ms[0].get("title") or ms[0].get("subtitle"),
            "close_time": ms[0].get("close_time"),
        }
    (RAW / "kalshi_live.json").write_text(json.dumps(out, indent=1))
    print(len(pick), "series checked;", len(out), "with open markets")


if __name__ == "__main__":
    main()

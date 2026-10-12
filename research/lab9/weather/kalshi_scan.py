"""Lab 9 weather scout: list Kalshi Climate & Weather series and today's open-market liquidity (public keyless API, read-only)."""
import json, sys, time, urllib.request, urllib.parse
from pathlib import Path
BASE = "https://api.elections.kalshi.com/trade-api/v2"
OUT = Path(__file__).parent / "raw"
OUT.mkdir(exist_ok=True)

def get(path, params=None, tries=5):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lab9-research"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + 2 * i); continue
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None

def main():
    series = json.load(open(OUT / "kalshi_series_climate.json"))["series"]
    rows = []
    for s in series:
        t = s["ticker"]
        if s.get("frequency") not in ("daily", "hourly", "weekly"):
            continue
        d = get("/markets", {"series_ticker": t, "status": "open", "limit": 200})
        time.sleep(0.6)
        mk = (d or {}).get("markets", [])
        if not mk:
            rows.append({"series": t, "title": s.get("title"), "freq": s.get("frequency"), "open": 0})
            continue
        f=lambda m,k: float(m.get(k) or 0)
        vol24 = sum(f(m,"volume_24h_fp") for m in mk)
        vol = sum(f(m,"volume_fp") for m in mk)
        oi = sum(f(m,"open_interest_fp") for m in mk)
        rules = mk[0].get("rules_primary")
        events = sorted({m.get("event_ticker") for m in mk})
        rows.append({"series": t, "title": s.get("title"), "freq": s.get("frequency"), "open": len(mk),
                     "events": events[:4], "vol24h": vol24, "vol": vol, "oi": oi,
                     "src": [x.get("name") for x in (s.get("settlement_sources") or [])],
                     "fee_type": s.get("fee_type"), "fee_mult": s.get("fee_multiplier"), "rules": rules})
    rows.sort(key=lambda r: -(r.get("vol24h") or 0))
    json.dump(rows, open(OUT / "kalshi_open_liquidity.json", "w"), indent=1)
    for r in rows:
        if r["open"]:
            print(f"{r['series']:18s} {r['freq']:7s} open={r['open']:3d} vol24h={r['vol24h']:>10.0f} vol={r['vol']:>10.0f} oi={r['oi']:>9.0f} {r['src']} fee={r.get('fee_type')}/{r.get('fee_mult')} | {r['title']} | {r['events'][:2]}")
main()

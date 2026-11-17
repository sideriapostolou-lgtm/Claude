"""Polymarket (international, public) weather-category leaderboard: ALL/MONTH/WEEK by PNL and VOL (read-only)."""
import json, time, urllib.request, urllib.parse, sys
from pathlib import Path
OUT = Path(__file__).parent / "raw"
D = "https://data-api.polymarket.com/v1/leaderboard"

def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lab9-research"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(3 + 3 * i); continue
            print("HTTP", e.code, url, file=sys.stderr); return None
        except Exception as ex:
            time.sleep(1 + i)
    return None

res = {}
for period in ("ALL", "MONTH", "WEEK", "DAY"):
    for order in ("PNL", "VOL"):
        rows = []
        for off in range(0, 1000, 50):
            q = urllib.parse.urlencode({"category": "WEATHER", "timePeriod": period, "orderBy": order, "limit": 50, "offset": off})
            d = get(f"{D}?{q}")
            if not d: break
            rows += d
            if len(d) < 50: break
            time.sleep(0.3)
        res[f"{period}_{order}"] = rows
        print(period, order, len(rows), file=sys.stderr)
json.dump(res, open(OUT / "pm_weather_leaderboard.json", "w"), indent=0)

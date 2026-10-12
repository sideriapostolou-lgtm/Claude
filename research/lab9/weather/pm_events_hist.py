"""Page Polymarket gamma weather events by 5-day endDate windows back to 2024-06 (read-only, public)."""
import json, time, urllib.request, urllib.parse, sys, datetime as dt
from pathlib import Path
OUT = Path(__file__).parent / "raw"
G = "https://gamma-api.polymarket.com"
def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lab9-research"})
            with urllib.request.urlopen(req, timeout=40) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(3 + 3 * i); continue
            time.sleep(1 + i)
        except Exception: time.sleep(1 + i)
    return None
allev = {e["id"]: e for e in json.load(open(OUT / "pm_weather_events.json"))}
end = dt.date(2026, 9, 23); start = dt.date(2024, 6, 1)
d1 = end
while d1 > start:
    d0 = d1 - dt.timedelta(days=3)
    off = 0
    while True:
        q = urllib.parse.urlencode({"tag_slug": "weather", "limit": 100, "offset": off,
            "end_date_min": d0.isoformat() + "T00:00:00Z", "end_date_max": d1.isoformat() + "T00:00:00Z"})
        d = get(f"{G}/events?{q}")
        if not d: break
        for e in d:
            for m in e.get("markets", []):  # keep only fields we need to save space
                for k in ("description", "image", "icon", "clobRewards", "umaResolutionStatuses"): m.pop(k, None)
            allev[e["id"]] = e
        off += len(d)
        if len(d) < 100: break
        time.sleep(0.3)
    print(d0, off, len(allev), file=sys.stderr, flush=True)
    d1 = d0
    time.sleep(0.3)
json.dump(list(allev.values()), open(OUT / "pm_weather_events_all.json", "w"))
print(len(allev))

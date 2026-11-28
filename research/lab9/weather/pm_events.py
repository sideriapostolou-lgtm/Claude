"""Page through Polymarket (international, public) gamma events tagged 'weather' and save them (read-only)."""
import json, time, urllib.request, urllib.parse, sys
from pathlib import Path
OUT = Path(__file__).parent / "raw"
G = "https://gamma-api.polymarket.com"

def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lab9-research"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(3 + 3 * i); continue
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None

def main():
    allev = {}
    for closed in ("true", "false"):
        off = 0
        while True:
            q = urllib.parse.urlencode({"tag_slug": "weather", "closed": closed, "limit": 100, "offset": off,
                                        "order": "endDate", "ascending": "false"})
            d = get(f"{G}/events?{q}")
            if not d: break
            for e in d:
                allev[e["id"]] = e
            off += len(d)
            print(closed, off, len(allev), d[-1].get("endDate"), file=sys.stderr)
            if len(d) < 100: break
            time.sleep(0.3)
    json.dump(list(allev.values()), open(OUT / "pm_weather_events.json", "w"))
    print(len(allev))
main()

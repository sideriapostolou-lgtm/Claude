"""LowTempTation-style 'peak passed' buys: Yes on the bucket holding the running max, mid-afternoon, mid price.
For each such buy: minutes since the last METAR, how far the latest METAR is below the running max, and the bucket's
Yes trade prices on Polymarket in the next 5/15/30/60/120 minutes (does the mispricing last long enough for a slow bot?)."""
import json, sys, time, collections, statistics as st, datetime as dt, urllib.request, urllib.parse
from zoneinfo import ZoneInfo
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cities import CITIES
from lockcheck import iem, to_unit
RAW = Path(__file__).parent / "raw"
lab = sys.argv[1] if len(sys.argv) > 1 else "LowTempTation"
d = json.load(open(RAW / f"lock_{lab}.json"))
sel = [x for x in d if x["cls"] == "OPEN" and x["kind"] == "highest" and x["outcome"] == "Yes" and 0.2 < x["price"] < 0.9]
print(len(sel), "peak-passed style buys")
def get(url):
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=40) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(5 * (i + 1)); continue
            return []
        except Exception: time.sleep(2)
    return []
obs_cache = {}
out = []
seen = set()
for x in sel:
    if x["cid"] in seen: continue
    seen.add(x["cid"])
    stn = CITIES[x["city"]][0]
    if stn not in obs_cache: obs_cache[stn] = iem(stn, dt.date(2026, 7, 31), dt.date(2026, 10, 12))
    t = dt.datetime.fromtimestamp(x["ts"], dt.timezone.utc)
    tz = ZoneInfo(CITIES[x["city"]][1])
    lt = t.astimezone(tz); day0 = dt.datetime(lt.year, lt.month, lt.day, tzinfo=tz).astimezone(dt.timezone.utc)
    seen_obs = [(ot, to_unit(v, x["unit"])) for ot, v in obs_cache[stn] if day0 <= ot <= t]
    if not seen_obs: continue
    last_t, last_v = seen_obs[-1]; mx = max(v for _, v in seen_obs)
    tr = get("https://data-api.polymarket.com/trades?" + urllib.parse.urlencode({"market": x["cid"], "limit": 500, "takerOnly": "false"}))
    time.sleep(0.4)
    yes = [(y["timestamp"], y["price"] if y["outcome"] == "Yes" else 1 - y["price"]) for y in tr]
    win = {}
    for lo, hi in ((0, 5), (5, 15), (15, 30), (30, 60), (60, 120), (120, 240)):
        ps = [p for ts, p in yes if lo * 60 <= ts - x["ts"] < hi * 60]
        win[f"{lo}-{hi}m"] = round(st.median(ps), 3) if ps else None
    out.append({"city": x["city"], "price": round(x["price"], 3), "local_h": round(x["local_hrs"], 2), "mins_since_obs": round((t - last_t).total_seconds() / 60, 1),
                "drop_from_max": mx - last_v, "won": x["won_by_obs"], **win})
for r in out: print(r)
json.dump(out, open(RAW / f"nowcast_probe_{lab}.json", "w"))
print("median minutes since last METAR:", st.median(r["mins_since_obs"] for r in out), " drop from max:", collections.Counter(r["drop_from_max"] for r in out))
for k in ("0-5m", "5-15m", "15-30m", "30-60m", "60-120m", "120-240m"):
    v = [r[k] for r in out if r[k] is not None]
    if v: print(k, "median Yes price", st.median(v), "n", len(v))

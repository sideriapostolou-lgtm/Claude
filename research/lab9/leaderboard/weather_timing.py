"""For weather wallets: which cities, and when (local time, relative to the market's date) they buy.
Usage: python3 weather_timing.py <wallet> [...]   (needs raw/b/<wallet>/act_newest.json + act_slices.json)
"""
import json
import re
import statistics as st
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAW = Path(__file__).parent / "raw" / "b"
TZ = {
    "nyc": "America/New_York", "new-york": "America/New_York", "atlanta": "America/New_York",
    "miami": "America/New_York", "boston": "America/New_York", "philadelphia": "America/New_York",
    "washington": "America/New_York", "dc": "America/New_York", "chicago": "America/Chicago",
    "houston": "America/Chicago", "dallas": "America/Chicago", "austin": "America/Chicago",
    "san-antonio": "America/Chicago", "new-orleans": "America/Chicago", "minneapolis": "America/Chicago",
    "oklahoma-city": "America/Chicago", "denver": "America/Denver", "phoenix": "America/Phoenix",
    "los-angeles": "America/Los_Angeles", "la": "America/Los_Angeles", "san-francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles", "las-vegas": "America/Los_Angeles", "toronto": "America/Toronto",
    "london": "Europe/London", "paris": "Europe/Paris", "madrid": "Europe/Madrid", "milan": "Europe/Rome",
    "munich": "Europe/Berlin", "berlin": "Europe/Berlin", "amsterdam": "Europe/Amsterdam",
    "istanbul": "Europe/Istanbul", "ankara": "Europe/Istanbul", "tel-aviv": "Asia/Jerusalem",
    "seoul": "Asia/Seoul", "tokyo": "Asia/Tokyo", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai",
    "wuhan": "Asia/Shanghai", "chongqing": "Asia/Shanghai", "shenzhen": "Asia/Shanghai",
    "hong-kong": "Asia/Hong_Kong", "singapore": "Asia/Singapore", "taipei": "Asia/Taipei",
    "lucknow": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata",
    "buenos-aires": "America/Argentina/Buenos_Aires", "sao-paulo": "America/Sao_Paulo",
    "mexico-city": "America/Mexico_City", "cape-town": "Africa/Johannesburg", "wellington": "Pacific/Auckland",
    "sydney": "Australia/Sydney", "dubai": "Asia/Dubai", "jakarta": "Asia/Jakarta", "manila": "Asia/Manila",
    "moscow": "Europe/Moscow", "warsaw": "Europe/Warsaw", "lagos": "Africa/Lagos", "kuala-lumpur": "Asia/Kuala_Lumpur",
}
US = {"nyc", "new-york", "atlanta", "miami", "boston", "philadelphia", "washington", "dc", "chicago", "houston",
      "dallas", "austin", "san-antonio", "new-orleans", "minneapolis", "oklahoma-city", "denver", "phoenix",
      "los-angeles", "la", "san-francisco", "seattle", "las-vegas"}
# Kalshi series with OPEN markets (2026-10-12) for daily highs
KALSHI_HIGH = {"los-angeles", "miami", "nyc", "chicago", "austin", "houston", "boston", "atlanta", "philadelphia",
               "minneapolis", "dallas", "washington", "dc", "phoenix", "san-francisco", "denver", "oklahoma-city",
               "new-orleans", "seattle", "las-vegas", "san-antonio"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
PAT = re.compile(r"(highest|lowest)-temperature-in-([a-z-]+?)-on-([a-z]+)-(\d+)(?:-(\d{4}))?")


def parse(slug):
    m = PAT.search(slug or "")
    if not m:
        return None
    kind, city, mon, day, yr = m.groups()
    if mon not in MONTHS:
        return None
    return kind, city, MONTHS[mon], int(day), int(yr) if yr else None


def main(ws):
    for w in ws:
        d = RAW / w.lower()
        rows = json.loads((d / "act_newest.json").read_text())
        for v in json.loads((d / "act_slices.json").read_text()).values():
            rows += v
        seen = set()
        cities, kinds, hours_after_start, local_hour, usd_by_bucket = Counter(), Counter(), [], Counter(), Counter()
        n = 0
        for r in rows:
            if r.get("type") != "TRADE" or r.get("side") != "BUY":
                continue
            key = (r.get("transactionHash"), r.get("asset"), r.get("size"))
            if key in seen:
                continue
            seen.add(key)
            p = parse(r.get("slug") or r.get("eventSlug"))
            if not p:
                continue
            kind, city, mo, dy, yr = p
            tz = TZ.get(city)
            usd = float(r.get("usdcSize") or 0)
            cities[city] += usd
            kinds[kind] += usd
            n += 1
            if not tz:
                continue
            t = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).astimezone(ZoneInfo(tz))
            y = yr or t.year
            start = datetime(y, mo, dy, tzinfo=ZoneInfo(tz))
            h = (t - start).total_seconds() / 3600  # hours after local midnight of the market's date
            hours_after_start.append(h)
            b = ("before day" if h < 0 else "00-10h" if h < 10 else "10-14h" if h < 14 else "14-18h" if h < 18
                 else "18-24h" if h < 24 else "after day end")
            usd_by_bucket[b] += usd
            local_hour[t.hour] += 1
        tot = sum(cities.values()) or 1
        us = sum(v for k, v in cities.items() if k in US) / tot
        ks = sum(v for k, v in cities.items() if k in KALSHI_HIGH) / tot
        tb = sum(usd_by_bucket.values()) or 1
        print(f"== {w}  buys {n}  US-city share {us:.2f}  Kalshi-live-city share {ks:.2f}  kinds {dict(kinds)}")
        print("   top cities $share:", {k: round(v / tot, 2) for k, v in cities.most_common(10)})
        print("   $ by time vs market's local day:", {k: round(v / tb, 2) for k, v in
                                                    sorted(usd_by_bucket.items())})
        if hours_after_start:
            q = sorted(hours_after_start)
            print(f"   hours after local midnight of market date q10/50/90: {q[len(q) // 10]:.1f} / "
                  f"{st.median(q):.1f} / {q[9 * len(q) // 10]:.1f}")


if __name__ == "__main__":
    main(sys.argv[1:])

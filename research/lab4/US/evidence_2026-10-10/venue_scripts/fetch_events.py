"""Fetch the PUBLIC Polymarket US gateway's sports events (no key), gently (<= 2 req/s), raw pages to disk.

Two listings:
  desk   - exactly the desk's live_sports_markets query: startDateMin = now - 12 h, startDateMax = now + 5 min, 5 pages max
  window - the same window widened to now + 24 h (live now + scheduled in the next day), up to 40 pages
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

GATEWAY = "https://gateway.polymarket.us/v1"
UA = {"User-Agent": "nightcrawler-research/venue-map (public market data)"}
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
now = time.time()
iso = lambda t: datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def get(params):
    for attempt in range(4):
        r = requests.get(f"{GATEWAY}/events", params=params, headers=UA, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(3.0 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("gateway failed")


def listing(name, start_min, start_max, pages):
    total = 0
    for page in range(pages):
        params = {
            "limit": 100,
            "offset": page * 100,
            "closed": "false",
            "categories": "sports",
            "startDateMin": iso(start_min),
            "startDateMax": iso(start_max),
        }
        reply = get(params)
        evs = reply.get("events") or []
        (OUT / f"{name}_{page:02d}.json").write_text(json.dumps({"params": params, "fetched": time.time(), "events": evs}))
        total += len(evs)
        print(name, page, len(evs), flush=True)
        time.sleep(0.6)
        if len(evs) < 100:
            break
    return total


meta = {"now": now, "now_iso": iso(now)}
meta["desk_events"] = listing("desk", now - 12 * 3600, now + 300, 5)
meta["window_events"] = listing("window", now - 12 * 3600, now + 24 * 3600, 40)
(OUT / "meta.json").write_text(json.dumps(meta))
print(meta)

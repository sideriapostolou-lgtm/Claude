"""Per crypto series: first / last event (by endDate), and the event count (binary search on offset, limit=1).

usage: python -I series_census.py OUT.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

SERIES = {
    101: "btc", 281: "mag7", 374: "btc-hit-monthly", 375: "btc-updown-15m", 376: "btc-range-hourly",
    377: "btc-strike-hourly", 378: "btc-updown-1h", 379: "btc-strike-daily", 380: "btc-range-daily",
    381: "btc-strike-weekly", 382: "btc-range-weekly", 387: "btc-updown-5m", 388: "btc-updown-4h",
    434: "btc-updown-1d", 435: "btc-hit-weekly",
}


def one(sid, offset, direction="asc"):
    r = gw.get("/events", {"seriesId": sid, "limit": 1, "offset": offset, "orderBy": "endDate",
                           "orderDirection": direction})
    evs = r.get("events") or []
    return evs[0] if evs else None


def brief(e):
    if not e:
        return None
    ms = e.get("markets") or []
    return {"slug": e.get("slug"), "title": e.get("title"), "seriesSlug": e.get("seriesSlug"),
            "createdAt": e.get("createdAt"), "startDate": e.get("startDate"), "endDate": e.get("endDate"),
            "closed": e.get("closed"), "n_markets": len(ms)}


out = {}
for sid, name in SERIES.items():
    first = one(sid, 0, "asc")
    last = one(sid, 0, "desc")
    # check the filter really applied
    ok = bool(first) and first.get("seriesSlug") == name
    lo, hi = 0, 1
    if ok:
        while one(sid, hi, "asc"):
            lo, hi = hi, hi * 2
            if hi > 20000:
                break
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if one(sid, mid, "asc"):
                lo = mid
            else:
                hi = mid
    out[name] = {"series_id": sid, "filter_ok": ok, "count": (lo + 1) if ok else None,
                 "first": brief(first), "last": brief(last)}
    print(name, json.dumps(out[name])[:400], flush=True)
Path(sys.argv[1]).write_text(json.dumps(out, indent=1))

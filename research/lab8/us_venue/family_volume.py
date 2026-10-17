"""Lifetime volume (/book stats) of recently expired markets in the other BTC families (public gateway, read only).

usage: python -I family_volume.py OUT.jsonl
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

gw.MIN_GAP = 0.3
out = Path(sys.argv[1])
end_h = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)
slugs = []  # (family, event slug)
for k in range(1, 49):  # 15m windows ending in the last 12 h
    t = end_h - timedelta(minutes=15 * k)
    slugs.append(("updown-15m", f"btc-updown-15m-{t:%Y-%m-%d-%H%M}z"))
for k in range(1, 49):
    t = end_h - timedelta(hours=k)
    slugs.append(("updown-1h", f"btc-updown-1h-{t:%Y-%m-%d-%H%M}z"))
for d in range(5, 12):
    t = datetime(2026, 10, d, 21, 0, tzinfo=UTC)
    slugs.append(("updown-1d", f"btc-updown-1d-{t - timedelta(days=1):%Y-%m-%d-%H%M}z"))
    slugs.append(("above-daily", f"btc-above-day-{t:%Y-%m-%d}"))
    slugs.append(("range-daily", f"btc-range-day-{t:%Y-%m-%d}"))
slugs.append(("above-weekly", "btc-above-wk-2026-10-09"))
slugs.append(("range-weekly", "btc-range-wk-2026-10-09"))
slugs.append(("hit-weekly", "btc-hit-h-w-2026-10-09"))
slugs.append(("hit-weekly", "btc-hit-l-w-2026-10-09"))
for k in (1, 7, 13, 19):
    t = end_h - timedelta(hours=k)
    slugs.append(("range-hourly", f"btc-range-hr-{t:%Y-%m-%d-%H%M}z"))


def book(m):
    try:
        md = gw.get(f"/markets/{m['slug']}/book").get("marketData") or {}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)[:100]}
    st = md.get("stats") or {}
    return {"state": md.get("state"), "shares": st.get("sharesTraded"),
            "notional": (st.get("notionalTraded") or {}).get("value"),
            "open_t": st.get("openSetTime"), "last_t": st.get("lastTradeSetTime")}


fh = out.open("a")
pool = ThreadPoolExecutor(2)
for fam, slug in slugs:
    try:
        e = gw.get(f"/events/slug/{slug}").get("event")
    except Exception as ex:  # noqa: BLE001
        print("missing", slug, repr(ex)[:60], flush=True)
        continue
    ms = e.get("markets") or []
    res = list(pool.map(book, ms))
    for m, b in zip(ms, res):
        apt = m.get("assetPriceTerms") or {}
        fh.write(json.dumps({"family": fam, "event": slug, "slug": m["slug"], "title": m.get("title"),
                             "status": m.get("status"), "createdAt": m.get("createdAt"),
                             "endDate": e.get("endDate"), "fee": m.get("feeCoefficient"),
                             "tick": m.get("orderPriceMinTickSize"), "min_qty": m.get("minimumTradeQty"),
                             "strike": (apt.get("strike") or {}).get("value"),
                             "lo": (apt.get("rangeLower") or {}).get("value"),
                             "hi": (apt.get("rangeUpper") or {}).get("value"),
                             "settle_value": (apt.get("settlementPrice") or {}).get("value"),
                             "ptb": (apt.get("priceToBeat") or {}).get("value"), "book": b}) + "\n")
    fh.flush()
    print(fam, slug, len(ms), flush=True)
print("done")

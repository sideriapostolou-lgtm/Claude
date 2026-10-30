"""Live recorder for the hourly BTC "above" ladder (public gateway, no key, read only).

Every minute in the last 30 minutes of each hour (every 5 minutes before that): BRTI from /v1/asset-prices/history,
then /book for every strike of the current hour's ladder within +-WIDTH of spot. Full ladders kept (both sides).

usage: python -I live_recorder.py OUT.jsonl STOP_ISO [WIDTH] [PERIOD_S]  (PERIOD_S: cadence in the last 30 min, default 60)
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

gw.MIN_GAP = 0.12
out = Path(sys.argv[1])
stop = datetime.fromisoformat(sys.argv[2]).timestamp()
WIDTH = float(sys.argv[3]) if len(sys.argv) > 3 else 0.04
PERIOD = float(sys.argv[4]) if len(sys.argv) > 4 else 60.0
ladders: dict[str, list] = {}


def ladder(end: datetime):
    slug = f"btc-above-hr-{end:%Y-%m-%d-%H%M}z"
    if slug not in ladders:
        e = gw.get(f"/events/slug/{slug}").get("event") or {}
        ladders[slug] = [(m["slug"], float(m["assetPriceTerms"]["strike"]["value"]), m.get("feeCoefficient"),
                          m.get("orderPriceMinTickSize"), m.get("minimumTradeQty"))
                         for m in e.get("markets") or [] if (m.get("assetPriceTerms") or {}).get("strike")]
    return slug, ladders[slug]


def spot():
    now = int(time.time())
    r = gw.get("/asset-prices/history", {"assets": "crypto:btc", "from": now - 8, "to": now,
                                          "bucket": "ASSET_PRICE_BUCKET_1S"})
    c = (r.get("series") or [{}])[0].get("candles") or []
    c = [x for x in c if x.get("tickCount")]
    return (float(c[-1]["close"]), c[-1]["timestamp"]) if c else (None, None)


def book(slug):
    try:
        md = gw.get(f"/markets/{slug}/book").get("marketData") or {}
    except Exception as e:  # noqa: BLE001
        return {"slug": slug, "error": repr(e)[:120]}
    st = md.get("stats") or {}
    return {"slug": slug, "state": md.get("state"), "t": md.get("transactTime"),
            "bids": [(b["px"]["value"], b["qty"]) for b in md.get("bids") or []],
            "offers": [(o["px"]["value"], o["qty"]) for o in md.get("offers") or []],
            "shares": st.get("sharesTraded"), "notional": (st.get("notionalTraded") or {}).get("value"),
            "last": (st.get("lastTradePx") or {}).get("value"), "last_t": st.get("lastTradeSetTime")}


fh = out.open("a")
pool = ThreadPoolExecutor(3)
while time.time() < stop:
    t0 = time.time()
    now = datetime.now(UTC)
    end = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    left = (end - now).total_seconds()
    if left > 1800 and now.minute % 5:
        time.sleep(max(1.0, 60 - (time.time() % 60)))
        continue
    try:
        s, s_ts = spot()
        slug, lad = ladder(end)
        pick = [x for x in lad if s and abs(x[1] / s - 1) <= WIDTH]
        books = list(pool.map(book, [x[0] for x in pick]))
        s2, s2_ts = spot()
        row = {"ts": t0, "iso": now.isoformat(), "event": slug, "secs_left": left, "spot": s, "spot_ts": s_ts,
               "spot_after": s2, "spot_after_ts": s2_ts, "n_ladder": len(lad), "period_s": PERIOD,
               "strikes": {x[0]: x[1] for x in pick}, "meta": {x[0]: x[2:] for x in pick[:1]}, "books": books}
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        print(now.isoformat(), slug, round(left), s, len(books), round(time.time() - t0, 1), flush=True)
    except Exception as e:  # noqa: BLE001
        print("ERR", now.isoformat(), repr(e)[:200], flush=True)
    time.sleep(max(1.0, PERIOD - (time.time() - t0)))
print("stopped")

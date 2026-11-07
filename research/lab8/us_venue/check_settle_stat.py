"""Which reading of the gateway's 1 s BRTI series reproduces published priceToBeat / settlementPrice?

For N up/down-15m windows: (a) close of the 1 s candle at T-1, (b) mean of the 60 closes [T-60, T-1] (the docs' recipe),
(c) mean of the 60 closes [T-59, T].
usage: python -I check_settle_stat.py OUT.json
"""

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

random.seed(8)
start = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)
slots = [start + timedelta(minutes=15 * k) for k in range(int((datetime(2026, 10, 12, 13, 0, tzinfo=UTC) - start)
                                                              .total_seconds() // 900))]
rows = []
for t in sorted(random.sample(slots, 26)):
    slug = f"btc-updown-15m-{t:%Y-%m-%d-%H%M}z"
    try:
        e = gw.get(f"/events/slug/{slug}").get("event") or {}
    except Exception as ex:  # noqa: BLE001
        print("skip", slug, repr(ex)[:60])
        continue
    m = (e.get("markets") or [{}])[0]
    apt = m.get("assetPriceTerms") or {}
    for label, iso, val in (("priceToBeat", apt.get("windowStart"), apt.get("priceToBeat")),
                            ("settlementPrice", apt.get("windowEnd"), apt.get("settlementPrice"))):
        if not iso or not val:
            continue
        T = int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
        r = gw.get("/asset-prices/history", {"assets": "crypto:btc", "from": T - 60, "to": T,
                                              "bucket": "ASSET_PRICE_BUCKET_1S"})
        c = {x["timestamp"]: float(x["close"]) for x in (r.get("series") or [{}])[0].get("candles") or []}
        a = c.get(T - 1)
        b = [c[k] for k in range(T - 60, T) if k in c]
        cc = [c[k] for k in range(T - 59, T + 1) if k in c]
        rows.append({"slug": slug, "which": label, "T": iso, "published": float(val["value"]),
                     "close_T-1": a, "mean_[T-60,T-1]": round(sum(b) / len(b), 2) if len(b) == 60 else None,
                     "mean_[T-59,T]": round(sum(cc) / len(cc), 2) if len(cc) == 60 else None})
        print(rows[-1], flush=True)
Path(sys.argv[1]).write_text(json.dumps(rows, indent=1))
n = len(rows)
for k in ("close_T-1", "mean_[T-60,T-1]", "mean_[T-59,T]"):
    hit = sum(1 for r in rows if r[k] is not None and abs(r[k] - r["published"]) < 0.005)
    print(k, f"{hit}/{n} exact")

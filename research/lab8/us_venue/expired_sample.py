"""Expired hourly BTC "above" ladders on Polymarket US (public gateway, no key, read only).

For each hour END in [FIRST, LAST] (UTC): /events/slug/btc-above-hr-...; every strike: /markets/{slug}/book (lifetime
stats) and /price-history (book-derived Yes / No display prices, ~1 minute, from the event's listing hour to its end).
Resumable (jsonl, one row per market).

usage: python -I expired_sample.py OUTDIR FIRST_ISO LAST_ISO
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

gw.MIN_GAP = 0.1
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
first = datetime.fromisoformat(sys.argv[2])
last = datetime.fromisoformat(sys.argv[3])
ev_file = out / "events.jsonl"
mk_file = out / "markets.jsonl"
done_ev = {json.loads(x)["slug"] for x in ev_file.read_text().splitlines()} if ev_file.exists() else set()
done_mk = {json.loads(x)["slug"] for x in mk_file.read_text().splitlines()} if mk_file.exists() else set()
evf = ev_file.open("a")
mkf = mk_file.open("a")


def ts(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def market_row(m, t0, t1):
    slug = m["slug"]
    apt = m.get("assetPriceTerms") or {}
    row = {"slug": slug, "strike": float(apt["strike"]["value"]),
           "settle_value": float((apt.get("settlementPrice") or {}).get("value") or "nan"),
           "status": m.get("status"), "createdAt": m.get("createdAt"), "m_startDate": m.get("startDate"),
           "fee": m.get("feeCoefficient"), "tick": m.get("orderPriceMinTickSize"),
           "min_qty": m.get("minimumTradeQty"), "outcomePrices": m.get("outcomePrices")}
    try:
        md = gw.get(f"/markets/{slug}/book").get("marketData") or {}
        st = md.get("stats") or {}
        v = lambda k: (st.get(k) or {}).get("value") if isinstance(st.get(k), dict) else st.get(k)  # noqa: E731
        row["book"] = {"state": md.get("state"), "shares": st.get("sharesTraded"), "notional": v("notionalTraded"),
                       "open": v("openPx"), "high": v("highPx"), "low": v("lowPx"), "close": v("closePx"),
                       "last": v("lastTradePx"), "settle": v("settlementPx"), "open_t": st.get("openSetTime"),
                       "last_t": st.get("lastTradeSetTime"), "low_t": st.get("lowSetTime"),
                       "high_t": st.get("highSetTime"), "n_bids": len(md.get("bids") or []),
                       "n_offers": len(md.get("offers") or [])}
    except Exception as e:  # noqa: BLE001
        row["book_error"] = repr(e)[:150]
    try:
        ph = gw.get("/price-history", {"symbol": slug, "timestamp.startTimestamp": t0,
                                       "timestamp.endTimestamp": t1, "fidelity": 1})
        row["ph"] = [(p.get("timestamp"), p.get("longPrice"), p.get("shortPrice")) for p in ph.get("history") or []]
    except Exception as e:  # noqa: BLE001
        row["ph_error"] = repr(e)[:150]
    return row


pool = ThreadPoolExecutor(6)
t = first
while t <= last:
    slug = f"btc-above-hr-{t:%Y-%m-%d-%H%M}z"
    try:
        e = gw.get(f"/events/slug/{slug}").get("event")
    except Exception as ex:  # noqa: BLE001
        e = None
        print("no event", slug, repr(ex)[:80], flush=True)
    if e:
        ms = [m for m in e.get("markets") or [] if (m.get("assetPriceTerms") or {}).get("strike")]
        if slug not in done_ev:
            evf.write(json.dumps({"slug": slug, "createdAt": e.get("createdAt"), "startDate": e.get("startDate"),
                                  "endDate": e.get("endDate"), "closed": e.get("closed"), "n_markets": len(ms),
                                  "title": e.get("title"), "description": (ms[0].get("description") if ms else None)})
                      + "\n")
            evf.flush()
        t0 = ts(e["startDate"]) - 3 * 3600  # catch anything before the listing hour too
        t1 = ts(e["endDate"]) + 120
        todo = [m for m in ms if m["slug"] not in done_mk]
        for row in pool.map(lambda m: market_row(m, t0, t1), todo):
            row["event"] = slug
            mkf.write(json.dumps(row) + "\n")
        mkf.flush()
        print(slug, len(ms), "fetched", len(todo), flush=True)
    t += timedelta(hours=1)
print("done")

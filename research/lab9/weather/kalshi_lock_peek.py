"""Interim view: for Kalshi brackets locked by METAR, the locked side's traded prices around the lock time."""
import json, sys, datetime as dt, collections, statistics as st
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import kalshi_lock as k
series = sys.argv[1]; days = int(sys.argv[2]) if len(sys.argv) > 2 else 21
stn, off = k.SERIES[series]
end = dt.date(2026, 10, 11); start = end - dt.timedelta(days=days - 1)
ms = json.load(open(k.KD / f"{series}_markets.json"))
obs = k.iem(stn, start - dt.timedelta(days=1), end + dt.timedelta(days=2))
bins = collections.defaultdict(lambda: [0.0, 0.0, 0])
for m in ms:
    f = k.KD / "trades" / f"{m['ticker']}.json"
    if not f.exists(): continue
    d = dt.datetime.strptime(m["event_ticker"].split("-")[-1], "%y%b%d").date()
    w0 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=off); w1 = w0 + dt.timedelta(days=1)
    run = None; lock_t = side = None
    for t, v in obs:
        if not (w0 <= t < w1): continue
        run = v if run is None else max(run, v)
        s = k.lock_side(m, run)
        if s: lock_t, side = t, s; break
    if not side: continue
    tr = json.load(open(f))
    for x in tr:
        tt = dt.datetime.fromisoformat(x["created_time"].replace("Z", "+00:00"))
        yp = float(x.get("yes_price_dollars") or 0); pl = yp if side == "yes" else 1 - yp
        mins = (tt - lock_t).total_seconds() / 60
        b = "0-2m" if mins < 2 else "2-5m" if mins < 5 else "5-15m" if mins < 15 else "15-60m" if mins < 60 else "1-3h" if mins < 180 else ">3h"
        c = float(x.get("count_fp") or 0)
        bins[b][0] += c; bins[b][1] += c * pl; bins[b][2] += (pl <= 0.97) * c
    print(m["ticker"], side, "lock", lock_t.strftime("%m-%d %H:%M"), "trades", len(tr), "min locked-side price after lock", min((1 - float(x['yes_price_dollars']) if side == 'no' else float(x['yes_price_dollars'])) for x in tr) if tr else None)
for b in ["0-2m", "2-5m", "5-15m", "15-60m", "1-3h", ">3h"]:
    c, cp, c97 = bins[b]
    if c: print(f"{b:7s} contracts={c:9.0f} avg locked-side price={cp/c:.4f} contracts at <=0.97: {c97:.0f}")

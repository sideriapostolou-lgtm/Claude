"""Interim/complete summary of KXRAIN post-lock trading from caches only (no network)."""
import json, re, sys, collections, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import kalshi_lock as kl
from kalshi_rain import STN_TZ, precip_obs
end = dt.date(2026, 10, 11); start = end - dt.timedelta(days=6)
ms = json.load(open(kl.KD / "KXRAIN_markets.json"))
BINS = [(-1, 0, "-1..0m"), (0, 5, "0-5m"), (5, 15, "5-15m"), (15, 60, "15-60m"), (60, 180, "1-3h"), (180, 1e9, ">3h")]
tot = {b[2]: collections.defaultdict(float) for b in BINS}; n = viol = 0; per = []
for m in ms:
    mm = re.search(r"at CLI([A-Z]{3})", m.get("rules_primary") or "")
    try: d = dt.datetime.strptime(m["event_ticker"].split("-")[1], "%y%b%d").date()
    except (ValueError, IndexError): continue
    if not mm or not (start <= d <= end) or STN_TZ.get(mm.group(1)) is None: continue
    f = kl.KD / "trades" / f"{m['ticker']}.json"
    if not f.exists(): continue
    off = STN_TZ[mm.group(1)]
    obs = precip_obs(mm.group(1), start - dt.timedelta(days=1), end + dt.timedelta(days=2))
    w0 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=off); w1 = w0 + dt.timedelta(days=1)
    lock_t = next((t for t, v in obs if w0 <= t < w1 and v >= 0.01), None)
    if not lock_t: continue
    n += 1; viol += m.get("result") != "yes"
    c97 = 0
    for x in json.load(open(f)):
        tt = dt.datetime.fromisoformat(x["created_time"].replace("Z", "+00:00")); mins = (tt - lock_t).total_seconds() / 60
        if mins < -1: continue
        p = float(x.get("yes_price_dollars") or 0); c = float(x.get("count_fp") or 0)
        for lo, hi, name in BINS:
            if lo <= mins < hi:
                b = tot[name]; b["c"] += c; b["cp"] += c * p; b["c97"] += c * (p <= 0.97); b["c90"] += c * (p <= 0.90)
                b["edge97"] += c * (1 - p) * (p <= 0.97); b["taker_yes"] += c * (x.get("taker_side") == "yes")
        if mins >= 15 and p <= 0.97: c97 += c
    per.append((m["ticker"], lock_t.strftime("%m-%d %H:%MZ"), round(c97)))
print(f"locked-Yes rain markets with trades: {n}, violations: {viol}")
for lo, hi, name in BINS:
    b = tot[name]
    if b["c"]: print(f"{name:7s} contracts {b['c']:9.0f} avg Yes px {b['cp']/b['c']:.3f}  at<=0.97 {b['c97']:8.0f}  at<=0.90 {b['c90']:8.0f}  edge$<=0.97 {b['edge97']:7.0f}  taker bought Yes {b['taker_yes']/b['c']:.2f}")
for p in sorted(per, key=lambda r: -r[2])[:10]: print("  ", p)

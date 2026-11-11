"""Summary over every Kalshi daily-high series cached so far: after the METAR-based lock, contracts and prices of the
decided side by delay bin, taker side, and the edge left for a slow trader. Reads raw/kalshi caches only."""
import json, sys, datetime as dt, collections, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import kalshi_lock as k
end = dt.date(2026, 10, 11); start = end - dt.timedelta(days=20)
BINS = [(-1, 0, "-1..0m"), (0, 2, "0-2m"), (2, 5, "2-5m"), (5, 15, "5-15m"), (15, 60, "15-60m"), (60, 180, "1-3h"), (180, 1e9, ">3h")]
tot = {b[2]: collections.defaultdict(float) for b in BINS}
per_series = collections.defaultdict(lambda: collections.defaultdict(float))
viol = 0; nlock = 0; nmk = 0; obs_above = 0; days = set()
for series, (stn, off) in k.SERIES.items():
    f = k.KD / f"{series}_markets.json"
    if not f.exists(): continue
    ms = json.load(open(f)); obs = k.iem(stn, start - dt.timedelta(days=1), end + dt.timedelta(days=2))
    done_any = False
    for m in ms:
        try: d = dt.datetime.strptime(m["event_ticker"].split("-")[-1], "%y%b%d").date()
        except ValueError: continue
        if not (start <= d <= end): continue
        w0 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=off); w1 = w0 + dt.timedelta(days=1)
        day = [(t, v) for t, v in obs if w0 <= t < w1]
        if len(day) < 18: continue
        run = None; lock_t = side = None
        for t, v in day:
            run = v if run is None else max(run, v)
            s = k.lock_side(m, run)
            if s: lock_t, side = t, s; break
        fpath = k.KD / "trades" / f"{m['ticker']}.json"
        if not side: continue
        if not fpath.exists(): continue
        done_any = True; nlock += 1; days.add((series, d))
        if m.get("result") and m["result"] != side: viol += 1
        for x in json.load(open(fpath)):
            tt = dt.datetime.fromisoformat(x["created_time"].replace("Z", "+00:00"))
            mins = (tt - lock_t).total_seconds() / 60
            if mins < -1: continue
            yp = float(x.get("yes_price_dollars") or 0); pl = yp if side == "yes" else 1 - yp
            c = float(x.get("count_fp") or 0)
            # taker bought the decided side? (taker_side is yes/no)
            taker_decided = (x.get("taker_side") == side)
            for lo, hi, name in BINS:
                if lo <= mins < hi:
                    b = tot[name]; b["c"] += c; b["cp"] += c * pl; b["c97"] += c * (pl <= 0.97); b["edge97"] += c * (1 - pl) * (pl <= 0.97)
                    b["c99"] += c * (abs(pl - 0.99) < 1e-6); b["taker_decided_c"] += c * taker_decided
                    ps = per_series[series]; ps[name + "_c"] += c; ps[name + "_c97"] += c * (pl <= 0.97)
    if done_any: per_series[series]["locked_markets"] = sum(1 for _ in [0])
print(f"series with data: {len([s for s in per_series])}, locked brackets with trades: {nlock}, event-days: {len(days)}, violations (lock contradicted settlement): {viol}")
print(f"{'delay':8s} {'contracts':>10s} {'avg px':>7s} {'at<=0.97':>9s} {'edge$<=0.97':>11s} {'at 0.99':>9s} {'taker bought decided':>20s}")
for lo, hi, name in BINS:
    b = tot[name]
    if b["c"]: print(f"{name:8s} {b['c']:10.0f} {b['cp']/b['c']:7.4f} {b['c97']:9.0f} {b['edge97']:11.0f} {b['c99']:9.0f} {b['taker_decided_c']/b['c']:20.2f}")
for s, ps in per_series.items():
    print(s, {kk: round(v) for kk, v in ps.items() if kk.endswith("c97") or kk in (">3h_c", "1-3h_c")})

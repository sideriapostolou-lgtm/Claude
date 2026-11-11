"""Kalshi daily highs, evening check: at 19:00 and 22:00 local STANDARD time, the METAR running max M is known to
anyone; the official CLI max is M (about 4 days in 10) or M+1/M+2 (the CLI uses the continuous sensor, hourly METARs
miss the peak). How does the market price the bracket holding M and its neighbours, and what really settled?
Hourly candlesticks (public keyless) for the brackets around M; read-only."""
import json, sys, time, collections, datetime as dt, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import kalshi_lock as k
RAW = Path(__file__).parent / "raw"; CD = k.KD / "candles"; CD.mkdir(exist_ok=True)
def candles(series, ticker, t0, t1):
    f = CD / f"{ticker}.json"
    if f.exists(): return json.load(open(f))
    d = k.kget(f"/series/{series}/markets/{ticker}/candlesticks", {"start_ts": int(t0), "end_ts": int(t1), "period_interval": 60})
    c = (d or {}).get("candlesticks", [])
    json.dump(c, open(f, "w")); return c
def br(m):
    s = m["strike_type"]
    if s == "less": return (-999, int(round(m["cap_strike"])) - 1)
    if s == "greater": return (int(round(m["floor_strike"])) + 1, 999)
    return (int(round(m["floor_strike"])), int(round(m["cap_strike"])))
rows = []
end = dt.date(2026, 10, 11); start = end - dt.timedelta(days=20)
for series in sys.argv[1:] or ["KXHIGHNY", "KXHIGHCHI", "KXHIGHMIA", "KXHIGHLAX", "KXHIGHAUS", "KXHIGHDEN"]:
    stn, off = k.SERIES[series]
    ms = json.load(open(k.KD / f"{series}_markets.json"))
    obs = k.iem(stn, start - dt.timedelta(days=1), end + dt.timedelta(days=2))
    ev = collections.defaultdict(list)
    for m in ms: ev[m["event_ticker"]].append(m)
    for e, mk in ev.items():
        try: d = dt.datetime.strptime(e.split("-")[-1], "%y%b%d").date()
        except ValueError: continue
        if not (start <= d <= end): continue
        w0 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=off)
        try: cli = float(mk[0]["expiration_value"])
        except (TypeError, ValueError): continue
        for hh in (19, 22):
            T = w0 + dt.timedelta(hours=hh)
            seen = [v for t, v in obs if w0 <= t <= T]
            if len(seen) < 12: continue
            M = max(seen)
            for m in mk:
                lo, hi = br(m)
                if not (lo <= M + 2 and hi >= M - 1): continue  # brackets that could still hold the CLI max
                c = candles(series, m["ticker"], w0.timestamp(), (w0 + dt.timedelta(hours=26)).timestamp())
                at = [x for x in c if x["end_period_ts"] == int(T.timestamp())]
                if not at: continue
                x = at[0]
                ask = float(x["yes_ask"]["close_dollars"] or 0); bid = float(x["yes_bid"]["close_dollars"] or 0)
                pos = "holds M" if lo <= M <= hi else ("above M" if lo > M else "below M")
                upper = (M == hi)  # M is the top degree of its bracket -> a +1 CLI moves to the next bracket
                rows.append({"series": series, "date": d.isoformat(), "hh": hh, "M": M, "cli": cli, "ticker": m["ticker"], "lo": lo, "hi": hi,
                             "pos": pos, "M_is_top_of_bracket": upper, "ask": ask, "bid": bid, "won": m.get("result") == "yes"})
    print(series, len(rows), flush=True)
json.dump(rows, open(RAW / "kalshi_evening_rows.json", "w"))
# calibration
g = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
for r in rows:
    if r["ask"] <= 0 or r["ask"] >= 1: continue
    holder_top = None
    key = (r["hh"], r["pos"], "M top of its bracket" if r["pos"] == "holds M" and r["M_is_top_of_bracket"] else ("M bottom" if r["pos"] == "holds M" else ""),)
    b = g[key]; b[0] += 1; b[1] += r["won"]; b[2] += r["ask"]; b[3] += (r["won"] - r["ask"])
for kk in sorted(g):
    n, w, a, pnl = g[kk]
    print(kk, f"n={n} win={w/n:.3f} avg_ask={a/n:.3f} pnl_per_contract_if_bought_at_ask={pnl/n:+.3f}")

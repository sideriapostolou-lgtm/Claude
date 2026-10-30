"""Kalshi daily-high brackets: after the observed running max has already decided a bracket (a "lock"),
how much traded, at what price, and how long after the deciding observation? Public keyless API + IEM METARs.

Lock rules (CLI day = local STANDARD time midnight..midnight; whole-degree METAR readings only):
  between [floor,cap]: No is certain once running max > cap.   less (cap): No certain once running max >= cap.
  greater (floor): Yes is certain once running max > floor.
Sanity check: the final observed max must be <= Kalshi's settled value (expiration_value); any case where a
"lock" contradicts the real result is counted as a VIOLATION.
"""
import json, sys, time, csv, io, collections, statistics as st, datetime as dt, urllib.request, urllib.parse
from pathlib import Path
RAW = Path(__file__).parent / "raw"; KD = RAW / "kalshi"; KD.mkdir(exist_ok=True); IEM = RAW / "iem"
BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = {  # series: (IEM station of the CLI site, LST offset hours)
    "KXHIGHNY": ("NYC", -5), "KXHIGHCHI": ("MDW", -6), "KXHIGHMIA": ("MIA", -5), "KXHIGHLAX": ("LAX", -8),
    "KXHIGHAUS": ("AUS", -6), "KXHIGHDEN": ("DEN", -7), "KXHIGHTHOU": ("HOU", -6), "KXHIGHTATL": ("ATL", -5),
    "KXHIGHTBOS": ("BOS", -5), "KXHIGHPHIL": ("PHL", -5), "KXHIGHTDC": ("DCA", -5), "KXHIGHTSEA": ("SEA", -8),
    "KXHIGHTSFO": ("SFO", -8), "KXHIGHTDAL": ("DFW", -6), "KXHIGHTPHX": ("PHX", -7), "KXHIGHTMIN": ("MSP", -6),
}
_last = [0.0]
def kget(path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for i in range(10):
        w = 1.1 - (time.time() - _last[0])
        if w > 0: time.sleep(w)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(min(60, 4 * (i + 1))); continue
            if e.code == 404: return None
            time.sleep(3)
        except Exception:
            time.sleep(3)
    return None

def settled_markets(series, since):
    f = KD / f"{series}_markets.json"
    if f.exists(): return json.load(open(f))
    out, cur = [], None
    while True:
        p = {"series_ticker": series, "status": "settled", "limit": 1000}
        if cur: p["cursor"] = cur
        d = kget("/markets", p)
        if not d: break
        out += d.get("markets", [])
        cur = d.get("cursor")
        oldest = min((m["close_time"] for m in d.get("markets", [])), default="9999")
        if not cur or oldest < since: break
    json.dump(out, open(f, "w"))
    return out

def trades(ticker, min_ts=None):
    f = KD / "trades" / f"{ticker}.json"; f.parent.mkdir(exist_ok=True)
    if f.exists(): return json.load(open(f))
    out, cur = [], None
    while True:
        p = {"ticker": ticker, "limit": 1000}
        if min_ts: p["min_ts"] = int(min_ts)
        if cur: p["cursor"] = cur
        d = kget("/markets/trades", p)
        if not d: break
        out += d.get("trades", [])
        cur = d.get("cursor")
        if not cur: break
    json.dump(out, open(f, "w"))
    return out

def iem(station, d0, d1):
    f = IEM / f"{station}_{d0}_{d1}.csv"
    if not f.exists():
        q = [("station", station), ("data", "tmpf"), ("year1", d0.year), ("month1", d0.month), ("day1", d0.day),
             ("year2", d1.year), ("month2", d1.month), ("day2", d1.day), ("tz", "Etc/UTC"), ("format", "onlycomma"),
             ("latlon", "no"), ("missing", "M"), ("direct", "no"), ("report_type", 3), ("report_type", 4)]
        url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=120) as r:
            f.write_bytes(r.read())
        time.sleep(1)
    obs = []
    for row in csv.DictReader(io.StringIO(f.read_text())):
        v = row.get("tmpf")
        if v in (None, "M", ""): continue
        v = float(v)
        if abs(v - round(v)) > 0.05: continue  # keep only whole-degree F readings (T-group), avoid C->F ambiguity
        obs.append((dt.datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc), round(v)))
    return sorted(obs)

def lock_side(m, runmax):
    s, fl, cp = m.get("strike_type"), m.get("floor_strike"), m.get("cap_strike")
    if s == "between" and runmax > cp: return "no"
    if s == "less" and runmax >= cp: return "no"
    if s == "greater" and runmax > fl: return "yes"
    return None

def run(days=21, end=dt.date(2026, 10, 11)):
    start = end - dt.timedelta(days=days - 1)
    D = [2, 5, 15, 30, 60, 120]
    agg = {s: collections.defaultdict(float) for s in SERIES}
    rows = []
    for series, (stn, off) in SERIES.items():
        ms = settled_markets(series, (start - dt.timedelta(days=2)).isoformat())
        if not ms: print(series, "no markets", flush=True); continue
        obs = iem(stn, start - dt.timedelta(days=1), end + dt.timedelta(days=2))
        byev = collections.defaultdict(list)
        for m in ms: byev[m["event_ticker"]].append(m)
        for ev, mk in byev.items():
            # event date from close_time - (close is 00:00 local next day + ...); use the ticker date YYMONDD
            code = ev.split("-")[-1]
            try: d = dt.datetime.strptime(code, "%y%b%d").date()
            except ValueError: continue
            if not (start <= d <= end): continue
            w0 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=off)
            w1 = w0 + dt.timedelta(days=1)
            day = [(t, v) for t, v in obs if w0 <= t < w1]
            if len(day) < 18: continue
            final = max(v for _, v in day)
            for m in mk:
                ev_val = m.get("expiration_value")
                try: ev_val = float(ev_val)
                except (TypeError, ValueError): ev_val = None
                runmax, lock_t, side = None, None, None
                for t, v in day:
                    runmax = v if runmax is None else max(runmax, v)
                    s = lock_side(m, runmax)
                    if s: lock_t, side = t, s; break
                agg[series]["markets"] += 1
                if ev_val is not None and final > ev_val: agg[series]["obs_above_settle"] += 1
                if not side: continue
                agg[series]["locked"] += 1
                if m.get("result") and m["result"] != side: agg[series]["VIOLATION"] += 1; print("VIOLATION", m["ticker"], side, m["result"], final, ev_val, flush=True)
                tr = trades(m["ticker"], lock_t.timestamp() - 60)
                for x in tr:
                    tt = dt.datetime.fromisoformat(x["created_time"].replace("Z", "+00:00"))
                    if tt < lock_t: continue
                    yp = float(x.get("yes_price_dollars") or x.get("yes_price", 0) / 100)
                    pl = yp if side == "yes" else 1 - yp
                    c = float(x.get("count_fp") or x.get("count") or 0)
                    mins = (tt - lock_t).total_seconds() / 60
                    rows.append({"series": series, "ticker": m["ticker"], "side": side, "p": round(pl, 4), "count": c, "mins": mins,
                                 "taker": x.get("taker_side"), "lock_t": lock_t.isoformat(), "t": x["created_time"]})
                    for dd in D:
                        if mins >= dd:
                            for th in (0.95, 0.97, 0.98):
                                if pl <= th + 1e-9:
                                    agg[series][f"c_le{th}_after{dd}m"] += c
                                    agg[series][f"edge_le{th}_after{dd}m"] += c * (1 - pl)
        print(series, dict((k, round(v)) for k, v in agg[series].items() if k in ("markets", "locked", "VIOLATION", "obs_above_settle", "c_le0.97_after5m", "c_le0.97_after30m", "edge_le0.97_after30m")), flush=True)
    json.dump({"agg": agg, "start": start.isoformat(), "end": end.isoformat()}, open(RAW / "kalshi_lock_agg.json", "w"), indent=1)
    json.dump(rows, open(RAW / "kalshi_lock_rows.json", "w"))

if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 21)

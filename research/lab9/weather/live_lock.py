"""Live check (read-only): today's Kalshi + Polymarket US daily-high brackets already decided by observed METAR max
(CLI day in local standard time), and the price at which the decided side can be bought right now."""
import json, sys, time, csv, io, math, datetime as dt, urllib.request, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import kalshi_lock as kl
from xvenue_snapshot import get, pm_bracket, k_bracket, kfee, pfee, CITY
RAW = Path(__file__).parent / "raw"
def obs_today(station, d, off):
    q = [("station", station), ("data", "tmpf"), ("year1", d.year), ("month1", d.month), ("day1", d.day),
         ("year2", (d + dt.timedelta(days=2)).year), ("month2", (d + dt.timedelta(days=2)).month), ("day2", (d + dt.timedelta(days=2)).day),
         ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"), ("direct", "no"), ("report_type", 3), ("report_type", 4)]
    url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" + urllib.parse.urlencode(q)
    txt = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=60).read().decode()
    w0 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=off); w1 = w0 + dt.timedelta(days=1)
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        if r["tmpf"] in ("M", ""): continue
        v = float(r["tmpf"]); t = dt.datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        if abs(v - round(v)) <= 0.05 and w0 <= t < w1: out.append((t, round(v)))
    return out
def main(dstr):
    d = dt.date.fromisoformat(dstr); code = d.strftime("%y%b%d").upper()
    pm = {m["slug"]: m for m in json.load(open(RAW / "pmus_temp_markets.json")) if m["slug"].startswith("tc-temp-") and dstr in m["slug"]}
    inv = {v: k for k, v in CITY.items()}
    now = dt.datetime.now(dt.timezone.utc)
    for series, (stn, off) in kl.SERIES.items():
        ob = obs_today(stn, d, off); time.sleep(0.8)
        if not ob: continue
        run = max(v for _, v in ob); last_t = max(t for t, _ in ob)
        km = get(f"{kl.BASE}/markets?" + urllib.parse.urlencode({"event_ticker": f"{series}-{code}", "limit": 50})); time.sleep(1.2)
        for m in (km or {}).get("markets", []):
            side = kl.lock_side(m, run)
            if not side: continue
            ya, yb = float(m.get("yes_ask_dollars") or 0), float(m.get("yes_bid_dollars") or 0)
            ask_locked = ya if side == "yes" else 1 - yb  # price to buy the decided side now
            line = f"{series:11s} {m['ticker']:24s} decided={side:3s} obs_max={run} (last obs {last_t:%H:%M}Z)  Kalshi ask for decided side={ask_locked:.2f}"
            city = inv.get(series)
            if city:
                br = k_bracket(m)
                for slug, p in pm.items():
                    if slug.startswith(f"tc-temp-{city}-{dstr}") and pm_bracket(slug) == br:
                        b = get(f"https://gateway.polymarket.us/v1/markets/{slug}/bbo"); time.sleep(0.4)
                        md = (b or {}).get("marketData", b) or {}
                        num = lambda q: float(q["value"]) if isinstance(q, dict) and q.get("value") else None
                        pa, pb_ = num(md.get("bestAsk")), num(md.get("bestBid"))
                        pmask = pa if side == "yes" else (1 - pb_ if pb_ else None)
                        line += f" | PM US ask for decided side={pmask}"
            print(line, flush=True)
    print("checked at", now.isoformat())
if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat())

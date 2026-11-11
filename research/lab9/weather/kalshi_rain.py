"""Kalshi KXRAIN ("will it rain in <city> today", Yes if CLI precipitation > 0): once a METAR in the CLI day reports
measurable precipitation (>= 0.01 in), Yes is decided. How much traded afterwards, at what Yes price, how late?
Public keyless Kalshi API + IEM METAR archive. Read-only."""
import json, re, sys, time, csv, io, collections, datetime as dt, urllib.request, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import kalshi_lock as kl
RAW = Path(__file__).parent / "raw"; KD = kl.KD; IEM = kl.IEM
OFF = {"ET": -5, "CT": -6, "MT": -7, "PT": -8}
STN_TZ = {  # CLI site -> LST offset (hours)
    "NYC": -5, "TTN": -5, "BOS": -5, "PHL": -5, "DCA": -5, "ATL": -5, "MIA": -5, "CMH": -5, "SDF": -5, "EWR": -5, "BWI": -5, "CLT": -5, "DTW": -5, "PIT": -5, "RDU": -5, "TPA": -5, "JAX": -5, "ORL": -5, "MCO": -5,
    "MDW": -6, "ORD": -6, "AUS": -6, "HOU": -6, "IAH": -6, "DFW": -6, "MSP": -6, "MSY": -6, "SAT": -6, "OKC": -6, "STL": -6, "MCI": -6, "BNA": -6, "MEM": -6, "MKE": -6, "DSM": -6,
    "DEN": -7, "PHX": -7, "SLC": -7, "ABQ": -7,
    "LAX": -8, "SFO": -8, "SEA": -8, "LAS": -8, "SAN": -8, "PDX": -8, "SJC": -8, "SMF": -8,
}
def precip_obs(station, d0, d1):
    f = IEM / f"P_{station}_{d0}_{d1}.csv"
    if not f.exists():
        q = [("station", station), ("data", "p01i"), ("year1", d0.year), ("month1", d0.month), ("day1", d0.day),
             ("year2", d1.year), ("month2", d1.month), ("day2", d1.day), ("tz", "Etc/UTC"), ("format", "onlycomma"),
             ("latlon", "no"), ("missing", "M"), ("trace", "0.0001"), ("direct", "no"), ("report_type", 3), ("report_type", 4)]
        url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=120) as r: f.write_bytes(r.read())
        time.sleep(1)
    out = []
    for row in csv.DictReader(io.StringIO(f.read_text())):
        v = row.get("p01i")
        if v in (None, "M", ""): continue
        out.append((dt.datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc), float(v)))
    return sorted(out)
def run(days=10, end=dt.date(2026, 10, 11)):
    start = end - dt.timedelta(days=days - 1)
    ms = kl.settled_markets("KXRAIN", (start - dt.timedelta(days=2)).isoformat())
    agg = collections.defaultdict(float); rows = []
    for m in ms:
        mm = re.search(r"at CLI([A-Z]{3})", m.get("rules_primary") or "")
        ev = m["event_ticker"].split("-")[1] if "-" in m["event_ticker"] else ""
        try: d = dt.datetime.strptime(ev, "%y%b%d").date()
        except ValueError: continue
        if not mm or not (start <= d <= end): continue
        stn = mm.group(1); off = STN_TZ.get(stn)
        if off is None: agg["unknown_station"] += 1; continue
        obs = precip_obs(stn, start - dt.timedelta(days=1), end + dt.timedelta(days=2))
        w0 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=off); w1 = w0 + dt.timedelta(days=1)
        lock_t = next((t for t, v in obs if w0 <= t < w1 and v >= 0.01), None)
        agg["markets"] += 1
        if not lock_t: continue
        agg["locked_yes"] += 1
        if m.get("result") and m["result"] != "yes": agg["VIOLATION"] += 1; print("VIOLATION", m["ticker"], lock_t, flush=True)
        tr = kl.trades(m["ticker"], lock_t.timestamp() - 60)
        for x in tr:
            tt = dt.datetime.fromisoformat(x["created_time"].replace("Z", "+00:00"))
            if tt < lock_t: continue
            p = float(x.get("yes_price_dollars") or 0); c = float(x.get("count_fp") or 0); mins = (tt - lock_t).total_seconds() / 60
            rows.append({"ticker": m["ticker"], "p": p, "count": c, "mins": mins, "taker": x.get("taker_side")})
            for dd in (5, 15, 30, 60, 120):
                if mins >= dd and p <= 0.97: agg[f"c_le0.97_after{dd}m"] += c; agg[f"edge_le0.97_after{dd}m"] += c * (1 - p)
                if mins >= dd and p <= 0.95: agg[f"c_le0.95_after{dd}m"] += c
    print({k: round(v) for k, v in agg.items()})
    json.dump({"agg": agg, "start": start.isoformat(), "end": end.isoformat()}, open(RAW / "kalshi_rain_agg.json", "w"), indent=1)
    json.dump(rows, open(RAW / "kalshi_rain_rows.json", "w"))
if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 10)

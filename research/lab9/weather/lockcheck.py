"""Was each weather BUY already decided by observations at the moment of the trade?

For every BUY of a Polymarket temperature bucket, take the station's METAR/SPECI observations (Iowa Environmental
Mesonet public archive) from local midnight of the event day up to the trade time, and classify the bought outcome:
LOCKED_WIN (the running max/min already rules the bucket out/in for good), LOCKED_LOSS, or OPEN (still depends on
the rest of the day). Also compares the final observed max/min with the market's real resolution as a sanity check.
Read-only, public data only.
"""
import json, re, sys, csv, io, time, collections, statistics as st, datetime as dt, urllib.request, urllib.parse
from zoneinfo import ZoneInfo
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cities import CITIES
from timing import parse
RAW = Path(__file__).parent / "raw"; IEM = RAW / "iem"; IEM.mkdir(exist_ok=True)
BUCKET = re.compile(r" be (?:between )?(-?\d+)(?:-(-?\d+))?°([CF])( or higher| or above| or below| or lower)?")

def bucket(title):
    m = BUCKET.search(title or "")
    if not m: return None
    a, b, unit, tail = m.groups()
    lo, hi = int(a), int(b) if b else int(a)
    if tail and ("higher" in tail or "above" in tail): hi = 10**6
    if tail and ("below" in tail or "lower" in tail): lo = -10**6
    return lo, hi, unit

def iem(station, d0, d1):
    """Hourly+special obs (UTC) for station between dates; cached per station/month range."""
    sid = station[1:] if station.startswith("K") and len(station) == 4 else station
    f = IEM / f"{station}_{d0}_{d1}.csv"
    if not f.exists():
        q = [("station", sid), ("data", "tmpf"), ("year1", d0.year), ("month1", d0.month), ("day1", d0.day),
             ("year2", d1.year), ("month2", d1.month), ("day2", d1.day), ("tz", "Etc/UTC"), ("format", "onlycomma"),
             ("latlon", "no"), ("missing", "M"), ("trace", "T"), ("direct", "no"), ("report_type", 3), ("report_type", 4)]
        url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?" + urllib.parse.urlencode(q)
        for i in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lab9-research"}), timeout=120) as r:
                    f.write_bytes(r.read()); break
            except Exception as e:
                time.sleep(5 + 5 * i)
        time.sleep(1.0)
    obs = []
    for row in csv.DictReader(io.StringIO(f.read_text())):
        if row.get("tmpf") in (None, "M", ""): continue
        t = dt.datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        obs.append((t, float(row["tmpf"])))
    obs.sort()
    return obs

def to_unit(tmpf, unit):
    return round(tmpf) if unit == "F" else round((tmpf - 32) * 5 / 9)

def classify(kind, outcome, lo, hi, run):
    """run = running max (highest) or min (lowest) so far, in market unit. Returns LOCKED_WIN / LOCKED_LOSS / OPEN."""
    yes_dead = (run > hi) if kind == "highest" else (run < lo)  # bucket already passed
    yes_sure = False  # a running extreme can only make the Yes certain at day end, never mid-day (except open-ended buckets)
    if kind == "highest" and hi >= 10**6 and run >= lo: yes_sure = True   # "X or higher" already reached
    if kind == "lowest" and lo <= -10**6 and run <= hi: yes_sure = True   # "X or below" already reached
    if yes_dead: return "LOCKED_WIN" if outcome == "No" else "LOCKED_LOSS"
    if yes_sure: return "LOCKED_WIN" if outcome == "Yes" else "LOCKED_LOSS"
    return "OPEN"

def main(wallet, d0s, d1s, label=None):
    d0, d1 = dt.date.fromisoformat(d0s), dt.date.fromisoformat(d1s)
    a = json.load(open(RAW / "activity" / f"{wallet}.json"))
    buys = []
    for x in a:
        if x["type"] != "TRADE" or x["side"] != "BUY": continue
        p = parse(x); b = bucket(x.get("title"))
        if not p or not b or not (d0 <= p["date"] <= d1): continue
        if CITIES[p["city"]][0] == "HKO": continue  # Hong Kong Observatory is not a METAR station
        x.update(p); x["lo"], x["hi"], x["unit"] = b
        buys.append(x)
    stations = sorted({CITIES[x["city"]][0] for x in buys})
    obs = {s: iem(s, d0 - dt.timedelta(days=1), d1 + dt.timedelta(days=2)) for s in stations}
    res = collections.Counter(); usd = collections.Counter(); lag = []; detail = []
    for x in buys:
        st_, tzn = CITIES[x["city"]][0], CITIES[x["city"]][1]
        tz = ZoneInfo(tzn)
        day0 = dt.datetime(x["date"].year, x["date"].month, x["date"].day, tzinfo=tz).astimezone(dt.timezone.utc)
        day1 = day0 + dt.timedelta(days=1)
        t = dt.datetime.fromtimestamp(x["timestamp"], dt.timezone.utc)
        day_obs = [(ot, to_unit(v, x["unit"])) for ot, v in obs[st_] if day0 <= ot < day1]
        if not day_obs: res["NO_OBS"] += 1; continue
        seen = [(ot, v) for ot, v in day_obs if ot <= t]
        run = None
        if not seen:
            cls = "OPEN_PREDAY" if t < day0 else "OPEN"
        else:
            run = max(v for _, v in seen) if x["kind"] == "highest" else min(v for _, v in seen)
            cls = classify(x["kind"], x["outcome"], x["lo"], x["hi"], run)
            if cls == "LOCKED_WIN":  # when did it lock?
                r = None
                for ot, v in seen:
                    r = v if r is None else (max(r, v) if x["kind"] == "highest" else min(r, v))
                    if classify(x["kind"], x["outcome"], x["lo"], x["hi"], r) == "LOCKED_WIN":
                        lag.append((t - ot).total_seconds() / 60); break
        final = max(v for _, v in day_obs) if x["kind"] == "highest" else min(v for _, v in day_obs)
        final_cls = classify(x["kind"], x["outcome"], x["lo"], x["hi"], final)
        # Yes on a bucket that the final value sits inside is a win at day end
        inside = x["lo"] <= final <= x["hi"]
        won_by_obs = (inside and x["outcome"] == "Yes") or (not inside and x["outcome"] == "No")
        res[cls] += 1; usd[cls] += x["usdcSize"]
        detail.append({"cls": cls, "price": x["price"], "usdc": x["usdcSize"], "won_by_obs": won_by_obs, "local_hrs": x["local_hrs"],
                       "city": x["city"], "kind": x["kind"], "outcome": x["outcome"], "title": x["title"], "ts": x["timestamp"],
                       "lo": x["lo"], "hi": x["hi"], "unit": x["unit"], "run": run, "final": final, "cid": x["conditionId"]})
    tot = sum(usd.values())
    print(f"{label or wallet}: buys {len(buys)} in {d0}..{d1}, stations {len(stations)}")
    for k in sorted(res): print(f"  {k:12s} n={res[k]:5d}  usdc={usd[k]:10.0f}  share_usdc={usd[k]/tot if tot else 0:.3f}")
    if lag:
        print("  minutes from locking observation to buy: quantiles", [round(q, 1) for q in st.quantiles(lag, n=10)], "n", len(lag))
    for k in ("LOCKED_WIN", "OPEN", "OPEN_PREDAY"):
        ds = [d for d in detail if d["cls"] == k]
        if ds:
            wr = sum(d["won_by_obs"] for d in ds) / len(ds)
            print(f"  {k}: median price {st.median(d['price'] for d in ds):.3f}, win rate by obs {wr:.3f}, n {len(ds)}")
    json.dump(detail, open(RAW / f"lock_{(label or wallet)[:24]}.json", "w"))

if __name__ == "__main__":
    main(*sys.argv[1:])

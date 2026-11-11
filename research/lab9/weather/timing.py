"""Entry timing and price profile of a wallet's weather trades (local time of the event city), from public activity."""
import json, re, sys, collections, statistics as st, datetime as dt
from zoneinfo import ZoneInfo
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cities import CITIES
RAW = Path(__file__).parent / "raw"
MONTHS = {m: i for i, m in enumerate(["january","february","march","april","may","june","july","august","september","october","november","december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())}); MONTHS["sept"] = 9
SLUG = re.compile(r"(highest|lowest)-temperature-in-(.+?)-on-([a-z]+)-(\d+)(?:-(\d{4}))?")

def parse(x):
    m = SLUG.match(x.get("eventSlug") or "")
    if not m: return None
    kind, city, mon, day, yr = m.groups()
    if city not in CITIES or mon not in MONTHS: return None
    ts = x["timestamp"]
    yr = int(yr) if yr else dt.datetime.fromtimestamp(ts, dt.timezone.utc).year
    d = dt.date(yr, MONTHS[mon], int(day))
    tz = ZoneInfo(CITIES[city][1])
    t = dt.datetime.fromtimestamp(ts, dt.timezone.utc).astimezone(tz)
    hrs = (t - dt.datetime(d.year, d.month, d.day, tzinfo=tz)).total_seconds() / 3600  # hours since local midnight of event day
    return {"kind": kind, "city": city, "date": d, "local_hrs": hrs}

def profile(wallet):
    a = json.load(open(RAW / "activity" / f"{wallet}.json"))
    tr = [x for x in a if x["type"] == "TRADE"]
    out = collections.defaultdict(list)
    for x in tr:
        p = parse(x)
        if not p: continue
        x.update(p); out[x["side"]].append(x)
    for side in ("BUY", "SELL"):
        xs = out[side]
        if not xs: continue
        hrs = [x["local_hrs"] for x in xs]
        print(f"== {side}: n={len(xs)} usdc={sum(x['usdcSize'] for x in xs):.0f} median usdc={st.median(x['usdcSize'] for x in xs):.1f}")
        hb = collections.Counter(int(h // 3) * 3 if -48 < h < 48 else (99 if h >= 48 else -99) for h in hrs)
        print("  local hour of event day (3h bins, <0 = day before):", sorted(hb.items()))
        pb = collections.Counter(round(x["price"], 2) for x in xs)
        prices = [x["price"] for x in xs]
        print("  price quantiles:", [round(q, 3) for q in st.quantiles(prices, n=10)])
        print("  outcome:", collections.Counter(x["outcome"] for x in xs).most_common(4), " kind:", collections.Counter(x["kind"] for x in xs))
        print("  top prices:", pb.most_common(8))
    return out

if __name__ == "__main__":
    profile(sys.argv[1])

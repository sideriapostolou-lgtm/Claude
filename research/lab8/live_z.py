"""z at entry of the desk's real Bitcoin buys (Coinbase 1m candles, 60-minute RMS vol)."""
import json, math, re, sys, time
from datetime import datetime, timezone
import requests
src = json.load(open(sys.argv[1]))
pat = re.compile(r"kind=trade slug=(cpc-\S+) qty=([\d.]+) price=([\d.]+) .* time=(\S+)")
buys = {}
for e in src["deploy"]:
    m = pat.search(e["message"])
    if not m: continue
    slug, qty, price, t = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)
    ts = datetime.fromisoformat(t.replace("Z", "+00:00")[:26] + "+00:00" if "." in t else t.replace("Z", "+00:00")).timestamp()
    k = (slug, round(ts))
    b = buys.setdefault(slug, {"ts": ts, "qty": 0.0, "price": price, "keys": set()})
    if k not in b["keys"]:
        b["keys"].add(k); b["qty"] += qty
print(len(buys), "bets")
def candles(t_end):
    r = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                     params={"granularity": 60, "start": datetime.fromtimestamp(t_end - 90*60, timezone.utc).isoformat(),
                             "end": datetime.fromtimestamp(t_end + 60, timezone.utc).isoformat()}, timeout=20)
    r.raise_for_status(); time.sleep(0.4)
    return sorted((float(c[0]), float(c[3]), float(c[4])) for c in r.json())
A = re.compile(r"^cpc-btc-above-hr-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})z-(\d+)$")
U = re.compile(r"^cpc-btc-updown-(15m|1h)-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})z$")
out = []
for slug, b in sorted(buys.items(), key=lambda kv: kv[1]["ts"]):
    t = b["ts"]
    if m := A.match(slug):
        day = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        end = day + int(m.group(2))*3600 + int(m.group(3))*60; line = float(m.group(4)); start = None
    elif m := U.match(slug):
        day = datetime.strptime(m.group(2), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        start = day + int(m.group(3))*3600 + int(m.group(4))*60; end = start + (900 if m.group(1) == "15m" else 3600); line = None
    else:
        continue
    cs = candles(t)
    done = [(ts, o, c) for ts, o, c in cs if ts + 60 <= t]
    if len(done) < 61: continue
    closes = [c for _, _, c in done][-61:]
    rets = [math.log(closes[i+1]/closes[i]) for i in range(60)]
    sig = math.sqrt(sum(r*r for r in rets)/60)
    spot = done[-1][2]
    if line is None:
        if start < cs[0][0]:
            cs2 = candles(start + 60); line = next((o for ts, o, c in cs2 if int(ts) == int(start)), None)
        else:
            line = next((o for ts, o, c in cs if int(ts) == int(start)), None)
    if not line: continue
    mins = (end - t) / 60
    z = math.log(spot / line) / (sig * math.sqrt(mins))
    out.append((slug, datetime.fromtimestamp(t, timezone.utc).strftime("%m-%d %H:%M"), b["price"], b["qty"], round(mins, 1), round(z, 2)))
for o in out: print(*o)
zs = [o[5] for o in out]
print("n", len(out), "z>=4:", sum(z >= 4 for z in zs), "z<4:", sum(z < 4 for z in zs))
import statistics
far = [o for o in out if o[5] >= 4]; near = [o for o in out if o[5] < 4]
for name, g in (("far", far), ("near", near)):
    if g: print(name, "avg price", round(statistics.mean(o[2] for o in g), 4), "n", len(g), "min z", min(o[5] for o in g))

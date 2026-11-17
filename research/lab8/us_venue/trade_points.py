"""Trade points (open/low/high/last prints of each expired market) by distance at the print, near-certain side.
usage: python -I trade_points.py EXPIRED_DIR OUT.json"""
import json, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402
d = Path(sys.argv[1])
mk = [json.loads(x) for x in open(d / "markets.jsonl")]
ev = {json.loads(x)["slug"]: json.loads(x) for x in open(d / "events.jsonl")}
ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
ends = sorted(ts(e["endDate"]) for e in ev.values())
t0, t1 = int(ends[0]) - 4 * 3600, int(ends[-1]) + 60
raw = {}
t = t0
while t < t1:
    r = gw.get("/asset-prices/history", {"assets": "crypto:btc", "from": t, "to": min(t + 3500 * 60, t1), "bucket": "ASSET_PRICE_BUCKET_1M"})
    for c in (r.get("series") or [{}])[0].get("candles") or []:
        if c.get("tickCount"):
            raw[c["timestamp"]] = float(c["close"])
    t += 3500 * 60
seen = set()
pts = []
for m in mk:
    b = m.get("book") or {}
    E = ts(ev[m["event"]]["endDate"]); K = m["strike"]; sv = m["settle_value"]
    for pk, tk in (("open", "open_t"), ("low", "low_t"), ("high", "high_t"), ("last", "last_t")):
        px, tt = b.get(pk), b.get(tk)
        if px is None or not tt or (m["slug"], tt) in seen:
            continue
        seen.add((m["slug"], tt))  # one print counted once even if it is open and low at once
        S = raw.get(int(ts(tt) // 60 * 60))
        if not S:
            continue
        dp = (S / K - 1) * 100; px = float(px)
        side_px, won = (px, sv >= K) if dp >= 0 else (round(1 - px, 4), sv < K)
        pts.append((abs(dp), side_px, won, (E - ts(tt)) / 60))
bands = [(0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 99)]
out = {}
for lo, hi in bands:
    xs = [p for p in pts if lo <= p[0] < hi and 0.95 <= p[1] <= 0.99 + 1e-9 and p[3] <= 60]
    out[f"{lo}-{hi}%"] = {"prints": len(xs), "won": sum(1 for p in xs if p[2]), "lost": sum(1 for p in xs if not p[2]),
                         "mean_price": round(sum(p[1] for p in xs) / len(xs), 4) if xs else None}
allx = [p for p in pts if 0.95 <= p[1] <= 0.99 + 1e-9 and p[3] <= 60]
out["all"] = {"prints": len(allx), "won": sum(1 for p in allx if p[2]), "lost": sum(1 for p in allx if not p[2]),
              "mean_price": round(sum(p[1] for p in allx) / len(allx), 4)}
out["distinct_prints_total"] = len(pts)
Path(sys.argv[2]).write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))

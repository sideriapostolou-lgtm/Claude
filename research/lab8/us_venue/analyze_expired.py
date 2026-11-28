"""Analyse the expired hourly BTC above ladders (expired_sample.py output).

usage: python -I analyze_expired.py EXPIRED_DIR OUT.json
"""

import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

d = Path(sys.argv[1])
mk = [json.loads(x) for x in open(d / "markets.jsonl")]
ev = {json.loads(x)["slug"]: json.loads(x) for x in open(d / "events.jsonl")}


def ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def q(xs, ps=(0.1, 0.25, 0.5, 0.75, 0.9, 0.99)):
    xs = sorted(xs)
    if not xs:
        return {}
    return {str(p): round(xs[min(len(xs) - 1, int(p * len(xs)))], 2) for p in ps} | {"max": round(xs[-1], 2),
                                                                                    "mean": round(sum(xs) / len(xs), 2)}


# BRTI minute closes (value at each minute boundary) covering the sample
ends = sorted(ts(e["endDate"]) for e in ev.values())
t0, t1 = int(ends[0]) - 4 * 3600, int(ends[-1]) + 60
brti = {}
t = t0
while t < t1:
    r = gw.get("/asset-prices/history", {"assets": "crypto:btc", "from": t, "to": min(t + 3500 * 60, t1),
                                          "bucket": "ASSET_PRICE_BUCKET_1M"})
    for c in (r.get("series") or [{}])[0].get("candles") or []:
        if c.get("tickCount"):
            brti[c["timestamp"]] = float(c["close"])
    t += 3500 * 60


def spot_at(x):
    m = int(x // 60 * 60)
    return brti.get(m) or brti.get(m - 60)


rows = [m for m in mk if "book" in m]
out = {"events": len(ev), "markets": len(mk), "markets_with_book": len(rows),
       "first_event": min(ev), "last_event": max(ev)}
sh = [float(m["book"]["shares"] or 0) for m in rows]
no = [float(m["book"]["notional"] or 0) for m in rows]
out["per_market_shares"] = q(sh)
out["per_market_notional_usd"] = q(no)
out["share_markets_never_traded"] = round(sum(1 for s in sh if s == 0) / len(sh), 4)
traded = [(float(m["book"]["shares"]), float(m["book"]["notional"] or 0)) for m in rows if float(m["book"]["shares"] or 0) > 0]
out["traded_markets"] = len(traded)
out["per_traded_market_shares"] = q([a for a, _ in traded])
out["per_traded_market_notional_usd"] = q([b for _, b in traded])
by_ev = defaultdict(lambda: [0.0, 0.0, 0, 0])
for m in rows:
    e = by_ev[m["event"]]
    e[0] += float(m["book"]["shares"] or 0)
    e[1] += float(m["book"]["notional"] or 0)
    e[2] += 1
    e[3] += 1 if float(m["book"]["shares"] or 0) > 0 else 0
out["per_event_notional_usd"] = q([v[1] for v in by_ev.values()])
out["per_event_shares"] = q([v[0] for v in by_ev.values()])
out["per_event_strikes_listed"] = q([v[2] for v in by_ev.values()])
out["per_event_strikes_traded"] = q([v[3] for v in by_ev.values()])
out["total_notional_usd"] = round(sum(v[1] for v in by_ev.values()), 2)

# by distance of the strike from the SETTLEMENT value
BANDS = [(0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 99)]
bd = defaultdict(lambda: {"n": 0, "traded": 0, "notional": 0.0, "shares": 0.0})
for m in rows:
    sv = m["settle_value"]
    if not sv or math.isnan(sv):
        continue
    p = abs(m["strike"] / sv - 1) * 100
    k = next(f"{lo}-{hi}%" for lo, hi in BANDS if lo <= p < hi)
    b = bd[k]
    b["n"] += 1
    s = float(m["book"]["shares"] or 0)
    b["traded"] += 1 if s > 0 else 0
    b["shares"] += s
    b["notional"] += float(m["book"]["notional"] or 0)
out["by_distance_from_settlement"] = {k: {**v, "notional": round(v["notional"], 2), "shares": round(v["shares"], 2),
                                          "share_traded": round(v["traded"] / v["n"], 3)}
                                      for k, v in sorted(bd.items(), key=lambda kv: float(kv[0].split("-")[0]))}

# when trading starts / ends relative to expiry
first_min = []
last_min = []
for m in rows:
    E = ts(ev[m["event"]]["endDate"])
    if m["book"].get("open_t"):
        first_min.append((E - ts(m["book"]["open_t"])) / 60)
    if m["book"].get("last_t"):
        last_min.append((E - ts(m["book"]["last_t"])) / 60)
out["minutes_before_expiry_first_trade"] = q(first_min, (0.01, 0.1, 0.5, 0.9, 0.99))
out["minutes_before_expiry_last_trade"] = q(last_min, (0.01, 0.1, 0.5, 0.9, 0.99))

# trade points (open / low / high / last) with the BRTI distance at that minute
pts = []
for m in rows:
    E = ts(ev[m["event"]]["endDate"])
    K = m["strike"]
    sv = m["settle_value"]
    yes_won = sv >= K
    for lab_, pk, tk in (("open", "open", "open_t"), ("low", "low", "low_t"), ("high", "high", "high_t"),
                         ("last", "last", "last_t")):
        px, tt = m["book"].get(pk), m["book"].get(tk)
        if px is None or not tt:
            continue
        S = spot_at(ts(tt))
        if not S:
            continue
        dpc = (S / K - 1) * 100
        px = float(px)
        # the near-certain side at that moment and the price paid for it by whoever bought it
        if dpc >= 0:
            side, side_px, won = "YES", px, yes_won
        else:
            side, side_px, won = "NO", round(1 - px, 4), not yes_won
        pts.append({"slug": m["slug"], "point": lab_, "min_left": round((E - ts(tt)) / 60, 1), "d_pct": round(dpc, 3),
                    "side": side, "side_px": side_px, "won": won})
far_hi = [p for p in pts if abs(p["d_pct"]) >= 1.0 and 0.95 <= p["side_px"] <= 0.99 and p["min_left"] <= 60]
out["trade_points"] = len(pts)
out["far_points_at_0.95_0.99_last_hour"] = {
    "points": len(far_hi), "markets": len({p["slug"] for p in far_hi}),
    "won": sum(1 for p in far_hi if p["won"]), "lost": sum(1 for p in far_hi if not p["won"]),
    "by_side": {s: sum(1 for p in far_hi if p["side"] == s) for s in ("YES", "NO")},
    "min_left_quantiles": q([p["min_left"] for p in far_hi], (0.1, 0.5, 0.9)),
    "lost_detail": [p for p in far_hi if not p["won"]][:20]}
near_hi = [p for p in pts if abs(p["d_pct"]) < 1.0 and 0.95 <= p["side_px"] <= 0.99 and p["min_left"] <= 60]
out["near_points_at_0.95_0.99_last_hour"] = {"points": len(near_hi), "won": sum(1 for p in near_hi if p["won"]),
                                             "lost": sum(1 for p in near_hi if not p["won"])}
# settlement check: published value vs BRTI minute close at expiry
chk = []
for e in ev.values():
    E = int(ts(e["endDate"]))
    sv = next((m["settle_value"] for m in mk if m["event"] == e["slug"]), None)
    r1 = gw.get("/asset-prices/history", {"assets": "crypto:btc", "from": E - 3, "to": E - 1,
                                          "bucket": "ASSET_PRICE_BUCKET_1S"})
    c1 = {c["timestamp"]: float(c["close"]) for c in (r1.get("series") or [{}])[0].get("candles") or []}
    b = c1.get(E - 1)
    if sv and b:
        chk.append(abs(sv - b))
out["settle_vs_brti_1s_close_at_T-1"] = {"n": len(chk), "exact": sum(1 for c in chk if c < 0.005), "max_abs": max(chk) if chk else None}
# price-history coverage
out["markets_with_price_history_points"] = sum(1 for m in mk if m.get("ph"))
# ladder geometry
geo = defaultdict(list)
for m in mk:
    geo[m["event"]].append(m["strike"])
sp = defaultdict(int)
for ks in geo.values():
    ks = sorted(ks)
    for a, b in zip(ks, ks[1:]):
        sp[round(b - a)] += 1
out["strike_spacing_counts"] = dict(sp)
out["ladder_width_pct_of_settle"] = q([
    (max(ks) - min(ks)) / next(m["settle_value"] for m in mk if m["event"] == e) * 100 for e, ks in geo.items()])
created_lead = [(ts(e["endDate"]) - ts(e["createdAt"])) / 3600 for e in ev.values()]
out["hours_created_before_expiry"] = q(created_lead, (0.0, 0.5, 1.0))
Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
print(json.dumps({k: v for k, v in out.items()}, indent=1)[:9000])

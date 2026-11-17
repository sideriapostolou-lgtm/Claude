"""Analyse the live recorder (hourly BTC above ladders, last 30 minutes of each hour).

Near-certain side of a strike K at spot S: YES when S >= K, else NO. Its asks: YES = the book's offers; NO = 1 - each
YES bid (buying NO = selling YES into a bid). Depth at 0.95-0.99 = contracts offered at those prices.
Distance: d = S / K - 1 (in %), and z = |ln(S/K)| / (sigma_1s * sqrt(seconds left)), sigma from the BRTI 1-minute
closes of the 24 h before the event's expiry hour began (gateway /v1/asset-prices/history).

usage: python -I analyze_live.py BOOKS.jsonl OUT.json
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

rows = [json.loads(x) for x in open(sys.argv[1])]
_sig = {}


def sigma_1s(end_ts):
    """Per-second vol from BRTI 1-minute log returns over the 24 h ending one hour before expiry."""
    key = end_ts
    if key not in _sig:
        t1 = end_ts - 3600
        r = gw.get("/asset-prices/history", {"assets": "crypto:btc", "from": t1 - 86400, "to": t1,
                                              "bucket": "ASSET_PRICE_BUCKET_1M"})
        c = [float(x["close"]) for x in (r.get("series") or [{}])[0].get("candles") or [] if x.get("tickCount")]
        lr = [math.log(b / a) for a, b in zip(c, c[1:])]
        var = sum(x * x for x in lr) / max(1, len(lr))
        _sig[key] = math.sqrt(var / 60.0)
    return _sig[key]


def end_ts_of(event):
    from datetime import UTC, datetime
    d = event.split("btc-above-hr-")[1][:-1]  # YYYY-MM-DD-HHMM
    return int(datetime.strptime(d, "%Y-%m-%d-%H%M").replace(tzinfo=UTC).timestamp())


BANDS = [(0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 99)]


def band(p):
    for lo, hi in BANDS:
        if lo <= p < hi:
            return f"{lo}-{hi}%" if hi < 99 else f">={lo}%"
    return "?"


snap_rows = []  # one per (snapshot, strike)


def sh_now(b):
    return float(b.get("shares") or 0)

prev_shares = {}
for r in rows:
    if r["secs_left"] > 1800 or not r.get("spot"):
        continue
    S = r["spot"]
    E = end_ts_of(r["event"])
    sig = sigma_1s(E)
    for b in r["books"]:
        if "error" in b:
            continue
        K = r["strikes"][b["slug"]]
        d = S / K - 1
        side = "YES" if S >= K else "NO"
        if side == "YES":
            asks = [(float(p), float(q)) for p, q in b["offers"]]
        else:
            asks = [(round(1 - float(p), 4), float(q)) for p, q in b["bids"]]
        best = min((p for p, _ in asks), default=None)
        depth = sum(q for p, q in asks if 0.95 - 1e-9 <= p <= 0.99 + 1e-9)
        depth_le99 = sum(q for p, q in asks if p <= 0.99 + 1e-9)
        z = abs(math.log(S / K)) / (sig * math.sqrt(max(r["secs_left"], 1)))
        sh = float(b.get("shares") or 0)
        dsh = sh - prev_shares.get(b["slug"], sh)
        prev_shares[b["slug"]] = sh
        # the live desk's own test (polydesk._qualifies): YES side, bid and ask within 0.03, ask >= 0.97, traded,
        # last print >= 0.94
        ybids = [float(p) for p, _ in b["bids"]]
        yasks = [float(p) for p, _ in b["offers"]]
        ybb, yba = (max(ybids) if ybids else None), (min(yasks) if yasks else None)
        lastp = float(b["last"]) if b.get("last") else None
        desk_ok = (ybb is not None and yba is not None and yba - ybb <= 0.03 + 1e-9 and yba >= 0.97 - 1e-9
                   and sh_now(b) > 0 and lastp is not None and lastp >= 0.94 - 1e-9)
        snap_rows.append({"desk_ok": desk_ok, "event": r["event"], "iso": r["iso"], "secs_left": r["secs_left"], "slug": b["slug"],
                          "K": K, "S": S, "d_pct": d * 100, "z": z, "side": side, "best_ask": best,
                          "depth_95_99": depth, "depth_le99": depth_le99, "shares": sh, "d_shares": dsh,
                          "last": b.get("last"), "state": b.get("state")})

out = {"snapshots": len({(x["event"], x["iso"]) for x in snap_rows}), "events": sorted({x["event"] for x in snap_rows})}

# A. per distance band: share of (snapshot, strike) with a near-certain ask <= 0.99, and depth
agg = defaultdict(lambda: {"n": 0, "ask_le99": 0, "ask_95_99": 0, "depth_sum": 0.0, "depth_list": []})
for x in snap_rows:
    k = band(abs(x["d_pct"]))
    a = agg[k]
    a["n"] += 1
    if x["best_ask"] is not None and x["best_ask"] <= 0.99 + 1e-9:
        a["ask_le99"] += 1
    if x["depth_95_99"] > 0:
        a["ask_95_99"] += 1
        a["depth_list"].append(x["depth_95_99"])
    a["depth_sum"] += x["depth_95_99"]
tab = {}
for k, a in agg.items():
    dl = sorted(a["depth_list"])
    tab[k] = {"strike_snapshots": a["n"], "with_ask_le_0.99": a["ask_le99"], "with_depth_0.95_0.99": a["ask_95_99"],
              "median_depth_when_any": dl[len(dl) // 2] if dl else 0, "max_depth": dl[-1] if dl else 0,
              "mean_depth_per_strike_minute": round(a["depth_sum"] / a["n"], 2)}
out["by_distance_band"] = dict(sorted(tab.items(), key=lambda kv: float(kv[0].split("-")[0].strip(">=%"))))

# B. per event: far (>= 1 %) strikes ever offering the near-certain side at <= 0.99 in the last 30 min
per_ev = {}
for ev in out["events"]:
    xs = [x for x in snap_rows if x["event"] == ev]
    far = [x for x in xs if abs(x["d_pct"]) >= 1.0]
    far_ok = [x for x in far if x["best_ask"] is not None and x["best_ask"] <= 0.99 + 1e-9]
    strikes = sorted({x["K"] for x in far_ok})
    by_min = defaultdict(set)
    for x in far_ok:
        by_min[x["iso"]].add(x["K"])
    per_ev[ev] = {
        "minutes": len({x["iso"] for x in xs}),
        "strikes_recorded": len({x["K"] for x in xs}),
        "far_strike_snapshots": len(far),
        "far_strike_snapshots_with_ask_le_0.99": len(far_ok),
        "distinct_far_strikes_with_ask_le_0.99": len(strikes),
        "max_simultaneous": max((len(v) for v in by_min.values()), default=0),
        "far_strikes_detail": [
            {"K": K, "minutes": sum(1 for x in far_ok if x["K"] == K),
             "best_ask_min": min(x["best_ask"] for x in far_ok if x["K"] == K),
             "max_depth_le_0.99": max(x["depth_le99"] for x in far_ok if x["K"] == K),
             "d_pct_range": [round(min(x["d_pct"] for x in far_ok if x["K"] == K), 2),
                             round(max(x["d_pct"] for x in far_ok if x["K"] == K), 2)],
             "z_range": [round(min(x["z"] for x in far_ok if x["K"] == K), 1),
                         round(max(x["z"] for x in far_ok if x["K"] == K), 1)],
             "side": far_ok[[x["K"] for x in far_ok].index(K)]["side"]}
            for K in strikes],
        "cadence_s": sorted({round(r.get("period_s", 60)) for r in rows if r["event"] == ev}),
        "far_trades": [{"iso": x["iso"][11:19], "K": x["K"], "d_pct_at_next_snapshot": round(x["d_pct"], 2),
                        "contracts": round(x["d_shares"], 2), "last_yes_px": x["last"],
                        "sure_side_px": (float(x["last"]) if x["side"] == "YES" else round(1 - float(x["last"]), 2))
                        if x["last"] else None, "side": x["side"]} for x in far if x["d_shares"] > 0],
        "far_contracts_traded_last30": round(sum(x["d_shares"] for x in far if x["d_shares"] > 0), 2),
        "all_contracts_traded_last30": round(sum(x["d_shares"] for x in xs if x["d_shares"] > 0), 2),
    }
out["per_event"] = per_ev

# C. z (vol units) bands for the near-certain side: asks <= 0.99, depth at 0.95-0.99, the desk's test
ZB = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 7), (7, 10), (10, 1e9)]
zb = defaultdict(lambda: {"strike_snapshots": 0, "with_ask_le_0.99": 0, "depth_list": [], "desk_would_buy": 0,
                          "far_1pct": 0})
for x in snap_rows:
    lo, hi = next(b for b in ZB if b[0] <= x["z"] < b[1])
    a = zb[f"{lo}-{hi}" if hi < 1e9 else f">={lo}"]
    a["strike_snapshots"] += 1
    a["far_1pct"] += 1 if abs(x["d_pct"]) >= 1 else 0
    if x["best_ask"] is not None and x["best_ask"] <= 0.99 + 1e-9:
        a["with_ask_le_0.99"] += 1
        a["depth_list"].append(x["depth_95_99"])
    a["desk_would_buy"] += 1 if x["desk_ok"] else 0
out["by_z"] = {}
for lo, hi in ZB:
    k = f"{lo}-{hi}" if hi < 1e9 else f">={lo}"
    a = zb.get(k)
    if not a:
        continue
    dl = sorted(a.pop("depth_list"))
    a["median_depth_95_99_when_ask"] = dl[len(dl) // 2] if dl else 0
    a["max_depth_95_99"] = dl[-1] if dl else 0
    out["by_z"][k] = a
# D. the desk's own test by distance band
db = defaultdict(lambda: [0, 0])
for x in snap_rows:
    k = band(abs(x["d_pct"]))
    db[k][0] += 1
    db[k][1] += 1 if x["desk_ok"] else 0
out["desk_rule_by_band"] = {k: {"strike_snapshots": v[0], "desk_would_buy": v[1]} for k, v in db.items()}
# E. per-strike table (strikes 0.25-3 % from spot on average over the last 30 min)
per_strike = []
for ev in out["events"]:
    xs = [x for x in snap_rows if x["event"] == ev]
    for K in sorted({x["K"] for x in xs}):
        ys = [x for x in xs if x["K"] == K]
        md = sum(x["d_pct"] for x in ys) / len(ys)
        if not 0.25 <= abs(md) <= 3.0:
            continue
        dep = sorted(x["depth_95_99"] for x in ys)
        per_strike.append({"event": ev, "K": K, "minutes": len(ys), "mean_d_pct": round(md, 2),
                           "side": "YES" if md > 0 else "NO",
                           "minutes_ask_le_0.99": sum(1 for x in ys if x["best_ask"] is not None and x["best_ask"] <= 0.99 + 1e-9),
                           "median_depth_95_99": dep[len(dep) // 2], "max_depth_95_99": dep[-1],
                           "best_ask_min": min((x["best_ask"] for x in ys if x["best_ask"] is not None), default=None),
                           "traded_last30": round(sum(x["d_shares"] for x in ys if x["d_shares"] > 0), 2)})
out["per_strike"] = per_strike
out["sigma_1s"] = {str(k): v for k, v in _sig.items()}
out["sigma_1h_pct"] = {str(k): round(v * math.sqrt(3600) * 100, 3) for k, v in _sig.items()}
Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
print(json.dumps({k: v for k, v in out.items() if k != "per_event"}, indent=1))
for ev, v in per_ev.items():
    print(ev, {k: v[k] for k in v if k != "far_strikes_detail"})
    for d in v["far_strikes_detail"]:
        print("   ", d)

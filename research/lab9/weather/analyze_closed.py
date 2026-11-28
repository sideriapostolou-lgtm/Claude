"""Per-wallet weather record from public closed positions: PnL, ROI, win rate, daily drawdown, entry-price mix, cities."""
import json, sys, re, statistics as st, collections, datetime as dt
from pathlib import Path
RAW = Path(__file__).parent / "raw"
WX = re.compile(r"\btemperature\b|\bprecipitation\b|\brain\b|\brainfall\b|\bsnow(?:fall)?\b|\bhurricanes?\b|\btornado(?:es)?\b|\bhottest\b|\bwhere will it rain\b", re.I)
KALSHI_SAME = {"miami", "los-angeles", "austin", "houston", "atlanta", "seattle", "san-francisco"}  # same station both venues
KALSHI_DIFF = {"nyc", "chicago", "denver", "dallas"}  # city on Kalshi but different station

def city_of(slug):
    m = re.match(r"(?:highest|lowest)-temperature-in-(.+?)-on-", slug or "")
    return m.group(1) if m else None

def load_lb():
    lb = json.load(open(RAW / "pm_weather_leaderboard.json"))
    names = {}
    for k, rows in lb.items():
        for x in rows: names.setdefault(x["proxyWallet"], {})[k] = x
    return names

def analyze(wallet, rows, lbinfo):
    wx0 = [r for r in rows if WX.search((r.get("title") or "") + " " + (r.get("eventSlug") or "").replace("-", " "))]
    if not wx0: return None
    # net both legs of a market (split/merge accounting moves PnL between the Yes and No rows)
    agg = {}
    for r in wx0:
        a = agg.setdefault(r["conditionId"], {"conditionId": r["conditionId"], "title": r["title"], "eventSlug": r.get("eventSlug"),
                                             "realizedPnl": 0.0, "timestamp": 0, "legs": []})
        a["realizedPnl"] += r["realizedPnl"]; a["timestamp"] = max(a["timestamp"], r["timestamp"]); a["legs"].append(r)
    for a in agg.values():
        main = max(a["legs"], key=lambda r: r["avgPrice"] * r["totalBought"])  # leg with the larger cost basis
        a["avgPrice"] = main["avgPrice"]; a["totalBought"] = main["totalBought"]; a["outcome"] = main.get("outcome")
        a["two_legs"] = len(a["legs"]) > 1
    wx = list(agg.values())
    pnl = sum(r["realizedPnl"] for r in wx)
    cost = sum(r["avgPrice"] * r["totalBought"] for r in wx)
    wins = sum(1 for r in wx if r["realizedPnl"] > 0)
    days = collections.defaultdict(float); months = collections.defaultdict(float)
    for r in wx:
        d = dt.datetime.fromtimestamp(r["timestamp"], dt.timezone.utc).date()
        days[d] += r["realizedPnl"]; months[d.strftime("%Y-%m")] += r["realizedPnl"]
    ds = sorted(days)
    cum = peak = mdd = 0.0
    for d in ds:
        cum += days[d]; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    # weekly
    weeks = collections.defaultdict(float)
    for d in ds: weeks[d.isocalendar()[:2]] += days[d]
    prices = [r["avgPrice"] for r in wx]
    costs = [r["avgPrice"] * r["totalBought"] for r in wx]
    cities = collections.Counter(city_of(r.get("eventSlug")) for r in wx)
    pnl_city = collections.defaultdict(float)
    for r in wx: pnl_city[city_of(r.get("eventSlug"))] += r["realizedPnl"]
    no_share = sum(1 for r in wx if r.get("outcome") == "No") / len(wx)
    hi = sum(1 for p in prices if p >= 0.9) / len(prices); lo = sum(1 for p in prices if p <= 0.1) / len(prices)
    # pnl by entry price bucket
    pb = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
    for r in wx:
        b = min(9, int(r["avgPrice"] * 10)); pb[b][0] += 1; pb[b][1] += r["realizedPnl"]; pb[b][2] += r["avgPrice"] * r["totalBought"]; pb[b][3] += r["realizedPnl"] > 0
    same = sum(v for c, v in pnl_city.items() if c in KALSHI_SAME)
    name = next((v.get("userName") for v in lbinfo.values()), "") if lbinfo else ""
    return {
        "wallet": wallet, "name": name, "n_all": len(rows), "n_wx": len(wx), "share_wx": len(wx0) / len(rows), "share_two_legs": round(sum(a["two_legs"] for a in wx) / len(wx), 3),
        "events": len({r.get("eventSlug") for r in wx}),
        "first": ds[0].isoformat(), "last": ds[-1].isoformat(), "active_days": len(ds),
        "span_days": (ds[-1] - ds[0]).days + 1,
        "pnl": round(pnl), "cost": round(cost), "roi": pnl / cost if cost else None,
        "win_rate": wins / len(wx), "pos_days": sum(1 for d in ds if days[d] > 0) / len(ds),
        "pos_weeks": sum(1 for w in weeks.values() if w > 0) / len(weeks), "n_weeks": len(weeks),
        "max_dd": round(mdd), "worst_day": round(min(days.values())), "best_day": round(max(days.values())),
        "med_cost": round(st.median(costs), 2), "mean_cost": round(st.mean(costs), 2), "med_price": round(st.median(prices), 3),
        "share_price_ge_0.9": round(hi, 3), "share_price_le_0.1": round(lo, 3), "share_no": round(no_share, 3),
        "months": {k: round(v) for k, v in sorted(months.items())},
        "top_cities": cities.most_common(8),
        "pnl_kalshi_same_station_cities": round(same),
        "price_buckets": {f"{b/10:.1f}": {"n": v[0], "pnl": round(v[1]), "cost": round(v[2]), "win": round(v[3] / v[0], 3)} for b, v in sorted(pb.items())},
        "lb_all_pnl": (lbinfo or {}).get("ALL_PNL", {}).get("pnl"), "lb_month_pnl": (lbinfo or {}).get("MONTH_PNL", {}).get("pnl"),
    }

if __name__ == "__main__":
    lb = load_lb()
    out = []
    for f in sorted((RAW / "closed").glob("*.json")):
        w = f.stem
        try: rows = json.load(open(f))
        except Exception: continue
        a = analyze(w, rows, lb.get(w))
        if a: out.append(a)
    out.sort(key=lambda a: -a["pnl"])
    json.dump(out, open(RAW / "closed_summary.json", "w"), indent=1, default=str)
    print(f"{'name':20s} {'nwx':>6} {'ev':>5} {'first':10} {'last':10} {'days':>4} {'pnl':>8} {'roi':>6} {'win':>5} {'+day':>5} {'+wk':>5} {'mdd':>7} {'medC':>7} {'medP':>5} {'>=.9':>5} {'<=.1':>5} {'No':>5} {'same':>7}")
    for a in out:
        print(f"{(a['name'] or a['wallet'][:10])[:20]:20s} {a['n_wx']:6d} {a['events']:5d} {a['first']} {a['last']} {a['active_days']:4d} {a['pnl']:8d} {a['roi'] or 0:6.3f} {a['win_rate']:5.2f} {a['pos_days']:5.2f} {a['pos_weeks']:5.2f} {a['max_dd']:7d} {a['med_cost']:7.1f} {a['med_price']:5.2f} {a['share_price_ge_0.9']:5.2f} {a['share_price_le_0.1']:5.2f} {a['share_no']:5.2f} {a['pnl_kalshi_same_station_cities']:7d}")

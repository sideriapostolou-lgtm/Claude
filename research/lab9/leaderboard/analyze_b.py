"""Stage B analysis for one or more wallets pulled by stage_b.py. Prints a profile and writes
raw/b/<wallet>/profile.json.
"""
import json
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from classify import classify  # noqa: E402

RAW = Path(__file__).parent / "raw" / "b"


def fam(r):
    return classify(r.get("slug"), r.get("eventSlug"), r.get("title"))


def mix(rows):
    c = Counter()
    for r in rows:
        if r.get("type", "TRADE") == "TRADE":
            c[fam(r)] += float(r.get("usdcSize") or (float(r.get("size", 0)) * float(r.get("price", 0))))
    tot = sum(c.values()) or 1
    return {k: round(v / tot, 2) for k, v in c.most_common(4)}


def window_end(slug):
    m = re.search(r"-updown-(5m|15m|4h|1h)-(\d{9,11})", slug or "")
    if not m:
        return None
    return int(m.group(2)) + {"5m": 300, "15m": 900, "4h": 14400, "1h": 3600}[m.group(1)]


def profile(w):
    d = RAW / w
    newest = json.loads((d / "act_newest.json").read_text())
    slices = json.loads((d / "act_slices.json").read_text())
    taker = json.loads((d / "trades_taker.json").read_text())
    allf = json.loads((d / "trades_all.json").read_text())
    closed = json.loads((d / "closed.json").read_text())
    openp = json.loads((d / "open.json").read_text())
    trades = [r for r in newest if r.get("type") == "TRADE"]
    types = Counter(r.get("type") for r in newest)
    P = {"wallet": w, "name": (newest[0].get("name") if newest else "")}
    ts = [r["timestamp"] for r in trades]
    P["newest_span_h"] = round((max(ts) - min(ts)) / 3600, 1) if ts else 0
    P["newest_trades"] = len(trades)
    P["types"] = dict(types)
    P["mix_newest"] = mix(trades)
    P["mix_slices"] = {k: mix(v) for k, v in slices.items()}
    P["slice_dates"] = {k: (min(r["timestamp"] for r in v), max(r["timestamp"] for r in v)) if v else None
                        for k, v in slices.items()}
    # maker share within the all-fills window
    if allf:
        t0, t1 = min(r["timestamp"] for r in allf), max(r["timestamp"] for r in allf)
        tk_in = [r for r in taker if t0 <= r["timestamp"] <= t1]
        covered = bool(taker) and min(r["timestamp"] for r in taker) <= t0
        P["taker_frac"] = round(len(tk_in) / len(allf), 3) if covered else None
        P["allfills_window_h"] = round((t1 - t0) / 3600, 2)
    usd = [float(r.get("usdcSize") or 0) for r in trades]
    P["median_fill_usd"] = round(st.median(usd), 2) if usd else None
    P["p90_fill_usd"] = round(sorted(usd)[int(0.9 * len(usd))], 2) if usd else None
    buys = [r for r in trades if r.get("side") == "BUY"]
    sells = [r for r in trades if r.get("side") == "SELL"]
    P["sell_frac"] = round(len(sells) / max(1, len(trades)), 3)
    pb = Counter()
    for r in buys:
        p = float(r.get("price") or 0)
        pb["<0.10" if p < .1 else "0.10-0.30" if p < .3 else "0.30-0.50" if p < .5 else "0.50-0.70" if p < .7
           else "0.70-0.90" if p < .9 else "0.90-0.97" if p < .97 else ">=0.97"] += float(r.get("usdcSize") or 0)
    tot = sum(pb.values()) or 1
    P["buy_price_usd_share"] = {k: round(v / tot, 2) for k, v in sorted(pb.items())}
    # per-market two-sidedness
    mk = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # cond -> outcomeIndex -> [shares, usd]
    mslug, mfills, mlead = {}, Counter(), defaultdict(list)
    for r in buys:
        c = r.get("conditionId")
        mk[c][r.get("outcomeIndex")][0] += float(r.get("size") or 0)
        mk[c][r.get("outcomeIndex")][1] += float(r.get("usdcSize") or 0)
        mslug[c] = r.get("slug")
        mfills[c] += 1
        e = window_end(r.get("slug"))
        if e:
            mlead[c].append(e - r["timestamp"])
    both, pair_costs, imbal, per_mkt_usd = 0, [], [], []
    for c, o in mk.items():
        per_mkt_usd.append(sum(v[1] for v in o.values()))
        if len(o) >= 2:
            both += 1
            (s0, u0), (s1, u1) = list(o.values())[:2]
            if s0 > 0 and s1 > 0:
                pair_costs.append(u0 / s0 + u1 / s1)
                imbal.append(abs(s0 - s1) / max(s0, s1))
    P["markets_newest"] = len(mk)
    P["both_sides_frac"] = round(both / max(1, len(mk)), 3)
    P["median_pair_cost"] = round(st.median(pair_costs), 4) if pair_costs else None
    P["pair_cost_lt1_frac"] = round(sum(1 for x in pair_costs if x < 1) / len(pair_costs), 3) if pair_costs else None
    P["median_imbalance"] = round(st.median(imbal), 3) if imbal else None
    P["median_usd_per_market"] = round(st.median(per_mkt_usd), 2) if per_mkt_usd else None
    leads = [x for v in mlead.values() for x in v]
    if leads:
        q = sorted(leads)
        P["window_lead_s_q10_50_90"] = (q[int(.1 * len(q))], q[len(q) // 2], q[int(.9 * len(q))])
        P["frac_fills_last_60s"] = round(sum(1 for x in leads if x <= 60) / len(leads), 3)
    # closed + unredeemed losers
    cp = [float(x.get("realizedPnl") or 0) for x in closed]
    losers_open = [x for x in openp if float(x.get("curPrice") or 0) == 0 and x.get("redeemable")]
    lo_pnl = [float(x.get("cashPnl") or 0) for x in losers_open]
    allp = cp + lo_pnl
    P["closed_n"] = len(closed)
    if closed:
        P["closed_span"] = (min(x["timestamp"] for x in closed), max(x["timestamp"] for x in closed))
    P["unredeemed_losers_n"] = len(losers_open)
    P["win_rate_closed_only"] = round(sum(1 for x in cp if x > 0) / len(cp), 3) if cp else None
    P["win_rate_incl_unredeemed"] = round(sum(1 for x in allp if x > 0) / len(allp), 3) if allp else None
    P["sum_pnl_closed"] = round(sum(cp), 0)
    P["sum_pnl_unredeemed_losers"] = round(sum(lo_pnl), 0)
    P["median_pnl_per_market"] = round(st.median(allp), 2) if allp else None
    P["worst_market"] = round(min(allp), 0) if allp else None
    P["best_market"] = round(max(allp), 0) if allp else None
    fam_pnl = defaultdict(lambda: [0, 0.0, 0])
    for x in closed:
        f = classify(x.get("slug"), x.get("eventSlug"), x.get("title"))
        fam_pnl[f][0] += 1
        fam_pnl[f][1] += float(x.get("realizedPnl") or 0)
        fam_pnl[f][2] += float(x.get("realizedPnl") or 0) > 0
    P["closed_by_family"] = {k: (v[0], round(v[1]), round(v[2] / v[0], 2)) for k, v in
                             sorted(fam_pnl.items(), key=lambda kv: -kv[1][0])}
    avgp = [float(x.get("avgPrice") or 0) for x in closed]
    P["closed_median_avgPrice"] = round(st.median(avgp), 3) if avgp else None
    (d / "profile.json").write_text(json.dumps(P, indent=1, default=str))
    return P


if __name__ == "__main__":
    for w in sys.argv[1:]:
        print(json.dumps(profile(w.lower()), indent=1, default=str))

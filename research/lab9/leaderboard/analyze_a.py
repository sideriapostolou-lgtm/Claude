"""Stage A analysis: one row per wallet from the daily P&L series + newest-500 activity sample.

Output: stage_a.csv (all wallets) and prints the shortlist (twin-able markets, long steady record).
"""
import csv
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from classify import TWIN, classify  # noqa: E402

HERE = Path(__file__).parent
RAW = HERE / "raw"
DAY = 86400


def boards_index():
    b = json.loads((RAW / "boards.json").read_text())
    idx = defaultdict(dict)
    for key, rows in b.items():
        for r in rows:
            w = r["proxyWallet"].lower()
            idx[w]["name"] = r.get("userName") or w
            idx[w][key] = (int(r["rank"]), r["pnl"], r["vol"])
    return idx


def pnl_stats(series):
    if not isinstance(series, list) or len(series) < 2:
        return {}
    s = sorted(series, key=lambda x: x["t"])
    p = [x["p"] for x in s]
    t = [x["t"] for x in s]
    diffs = [p[i] - p[i - 1] for i in range(1, len(p))]
    nz = [d for d in diffs if abs(d) > 1e-6]
    peak, mdd, mdd_peak = p[0], 0.0, p[0]
    for v in p:
        if v > peak:
            peak = v
        if peak - v > mdd:
            mdd, mdd_peak = peak - v, peak
    total = p[-1] - p[0]
    gains = sorted([d for d in diffs if d > 0], reverse=True)
    top5 = sum(gains[:5])
    # weekly
    weeks = defaultdict(float)
    for i in range(1, len(p)):
        weeks[t[i] // (7 * DAY)] += diffs[i - 1]
    wk = list(weeks.values())
    last = p[-1]

    def back(days):
        cut = t[-1] - days * DAY
        prev = [v for tt, v in zip(t, p) if tt <= cut]
        return last - (prev[-1] if prev else p[0])

    mean = st.mean(diffs) if diffs else 0
    sd = st.pstdev(diffs) if len(diffs) > 1 else 0
    return {
        "first_day": s[0]["t"], "last_day": s[-1]["t"], "days": len(p),
        "active_days": len(nz), "pnl_total": last, "pnl_span": total,
        "mdd": mdd, "mdd_frac_of_peak": (mdd / mdd_peak) if mdd_peak > 0 else None,
        "up_day_frac": (sum(1 for d in nz if d > 0) / len(nz)) if nz else None,
        "up_week_frac": (sum(1 for d in wk if d > 0) / len(wk)) if wk else None,
        "top5_day_share": (top5 / total) if total > 0 else None,
        "best_day": max(diffs) if diffs else 0, "worst_day": min(diffs) if diffs else 0,
        "pnl_30d": back(30), "pnl_90d": back(90), "pnl_180d": back(180),
        "daily_sharpe": (mean / sd * (365 ** 0.5)) if sd > 0 else None,
    }


def act_stats(rows):
    if not isinstance(rows, list):
        return {}
    trades = [r for r in rows if r.get("type") == "TRADE"]
    types = Counter(r.get("type") for r in rows)
    fam_n, fam_usd = Counter(), Counter()
    for r in trades:
        f = classify(r.get("slug"), r.get("eventSlug"), r.get("title"))
        fam_n[f] += 1
        fam_usd[f] += float(r.get("usdcSize") or 0)
    usd = [float(r.get("usdcSize") or 0) for r in trades]
    ts = [r["timestamp"] for r in rows if r.get("timestamp")]
    tot_usd = sum(usd) or 1
    twin_usd = sum(v for k, v in fam_usd.items() if k in TWIN and k != "sports")
    sports_usd = fam_usd.get("sports", 0)
    sells = sum(1 for r in trades if r.get("side") == "SELL")
    buys = sum(1 for r in trades if r.get("side") == "BUY")
    prices = [float(r.get("price") or 0) for r in trades if r.get("side") == "BUY"]
    markets = len({r.get("conditionId") for r in trades})
    span_h = (max(ts) - min(ts)) / 3600 if ts else 0
    top_fam = fam_usd.most_common(1)[0][0] if fam_usd else ""
    return {
        "n_rows": len(rows), "n_trades": len(trades), "n_markets_sample": markets,
        "sample_span_h": span_h, "trades_per_day": (len(trades) / (span_h / 24)) if span_h > 0 else None,
        "median_trade_usd": st.median(usd) if usd else None, "mean_trade_usd": st.mean(usd) if usd else None,
        "sell_frac": sells / max(1, buys + sells), "redeem_n": types.get("REDEEM", 0),
        "merge_n": types.get("MERGE", 0), "split_n": types.get("SPLIT", 0),
        "maker_rebate_n": types.get("MAKER_REBATE", 0) + types.get("REWARD", 0),
        "median_buy_price": st.median(prices) if prices else None,
        "top_family": top_fam, "top_family_share": fam_usd[top_fam] / tot_usd if top_fam else 0,
        "twin_share_usd": twin_usd / tot_usd, "sports_share_usd": sports_usd / tot_usd,
        "family_mix": ";".join(f"{k}:{v / tot_usd:.2f}" for k, v in fam_usd.most_common(4)),
    }


def main():
    idx = boards_index()
    out = []
    for w, meta in idx.items():
        pf, af = RAW / "pnl" / f"{w}.json", RAW / "act" / f"{w}.json"
        if not pf.exists() or not af.exists():
            continue
        row = {"wallet": w, "name": meta["name"],
               "boards": ",".join(f"{k}#{v[0]}" for k, v in meta.items() if k != "name")}
        row.update(pnl_stats(json.loads(pf.read_text())))
        row.update(act_stats(json.loads(af.read_text())))
        out.append(row)
    keys = sorted({k for r in out for k in r}, key=lambda k: (k not in ("wallet", "name", "boards"), k))
    with open(HERE / "stage_a.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        wr.writerows(out)
    print("rows", len(out))


if __name__ == "__main__":
    main()

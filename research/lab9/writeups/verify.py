"""Verify public claims about Polymarket wallets with keyless public endpoints (read-only).

For each wallet: daily PnL series (user-pnl-api), recent trade activity (data-api /activity),
and a market-structure profile of those trades (what it buys, at what price, how long before the end).
Raw responses are cached under raw/. Usage: python3 -I verify.py name=0xwallet [name=0xwallet ...]
"""
import json
import re
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "lab9-writeups-research/1.0 (read-only)"


def get(url, params, tries=6):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 + 2 * i)
            continue
        if r.status_code == 429:
            time.sleep(5 + 5 * i)
            continue
        if r.status_code >= 500:
            time.sleep(2 + 2 * i)
            continue
        time.sleep(0.35)
        return r.json() if r.status_code == 200 else None
    return None


def cached(name, fn):
    f = RAW / name
    if f.exists():
        return json.loads(f.read_text())
    d = fn()
    f.write_text(json.dumps(d))
    return d


def pnl_series(w):
    return cached(f"pnl_{w}.json", lambda: get("https://user-pnl-api.polymarket.com/user-pnl",
                                               {"user_address": w, "interval": "all", "fidelity": "1d"}))


def activity(w, pages=8):
    def fetch():
        rows = []
        for p in range(pages):
            d = get("https://data-api.polymarket.com/activity",
                    {"user": w, "limit": 500, "offset": 500 * p})
            if not d:
                break
            rows += d
            if len(d) < 500:
                break
        return rows
    return cached(f"act_{w}.json", fetch)


def cat_of(title):
    t = (title or "").lower()
    if re.search(r"temperature|°f|°c|precipitation|rainfall|snow|hurricane|weather", t):
        return "weather"
    if re.search(r"bitcoin|ethereum|solana|\bxrp\b|\bbtc\b|\beth\b|dogecoin|crypto", t):
        return "crypto"
    if re.search(r"\bcpi\b|inflation|fed |federal reserve|interest rate|unemployment|payroll|jobs|gdp|bps|rate cut|rate hike", t):
        return "econ"
    if re.search(r"s&p|nasdaq|dow |stock|close above|gold|silver|oil|wti|crude|treasury|yield|\(.*\) (up|down)", t):
        return "finance"
    if re.search(r" vs\.? | o/u|spread|win the|match|game \d|map \d|nba|nfl|mlb|nhl|ufc|premier league|fc ", t):
        return "sports"
    return "other"


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def end_of(slug):
    """End date encoded in a Polymarket slug like ...-on-march-28-2026-16c -> UTC timestamp of the day's end."""
    m = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)-(\d{1,2})-(\d{4})", slug or "")
    if not m:
        return None
    try:
        d = datetime(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)), 23, 59, tzinfo=timezone.utc)
    except ValueError:
        return None
    return d.timestamp()


def city_of(title):
    m = re.search(r"temperature in ([A-Za-z .'-]+?) (?:be|on)\b", title or "")
    return m.group(1).strip() if m else None


def record(series):
    if not series:
        return {}
    pts = [(p["t"], p["p"]) for p in series]
    pts.sort()
    peak, mdd = -1e18, 0.0
    for _, v in pts:
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    months = defaultdict(float)
    prev = 0.0
    days = []
    for t, v in pts:
        months[datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m")] += v - prev
        days.append(v - prev)
        prev = v
    last_t, last_v = pts[-1]

    def back(nd):
        cut = last_t - nd * 86400
        older = [v for t, v in pts if t <= cut]
        return last_v - (older[-1] if older else 0.0)
    active = [d for d in days if abs(d) > 1e-6]
    return {
        "first": datetime.fromtimestamp(pts[0][0], timezone.utc).strftime("%Y-%m-%d"),
        "last": datetime.fromtimestamp(last_t, timezone.utc).strftime("%Y-%m-%d"),
        "pnl_total": round(last_v), "peak": round(peak), "mdd": round(mdd),
        "pnl_30d": round(back(30)), "pnl_90d": round(back(90)), "pnl_180d": round(back(180)),
        "months_up": f"{sum(1 for v in months.values() if v > 0)}/{len(months)}",
        "worst_month": round(min(months.values())), "worst_day": round(min(days)), "best_day": round(max(days)),
        "up_day_frac": round(sum(1 for d in active if d > 0) / len(active), 2) if active else None,
        "months": {k: round(v) for k, v in sorted(months.items())},
    }


def profile(rows):
    tr = [r for r in rows if r.get("type") == "TRADE"]
    if not tr:
        return {"n_rows": len(rows), "types": dict(Counter(r.get("type") for r in rows))}
    ts = [r["timestamp"] for r in tr]
    cats = Counter()
    usd_by_cat = Counter()
    for r in tr:
        c = cat_of(r.get("title"))
        cats[c] += 1
        usd_by_cat[c] += float(r.get("usdcSize") or 0)
    buys = [r for r in tr if r.get("side") == "BUY"]
    wx = [r for r in buys if cat_of(r.get("title")) == "weather"]
    pb = Counter()
    for r in buys:
        p = float(r["price"])
        b = "<.02" if p < .02 else "<.10" if p < .10 else "<.30" if p < .30 else "<.70" if p < .70 else "<.90" if p < .90 else "<.97" if p < .97 else ">=.97"
        pb[b] += 1
    lead = []
    for r in buys:
        e = end_of(r.get("slug"))
        if e:
            lead.append((e - r["timestamp"]) / 3600)
    out = {
        "n_trades": len(tr), "span_days": round((max(ts) - min(ts)) / 86400, 1),
        "from": datetime.fromtimestamp(min(ts), timezone.utc).strftime("%Y-%m-%d"),
        "to": datetime.fromtimestamp(max(ts), timezone.utc).strftime("%Y-%m-%d"),
        "types": dict(Counter(r.get("type") for r in rows)),
        "cat_trades": dict(cats.most_common()), "cat_usd": {k: round(v) for k, v in usd_by_cat.most_common()},
        "sell_frac": round(sum(1 for r in tr if r.get("side") == "SELL") / len(tr), 2),
        "buy_price_buckets": dict(sorted(pb.items())),
        "median_buy_price": round(st.median(float(r["price"]) for r in buys), 3) if buys else None,
        "median_trade_usd": round(st.median(float(r.get("usdcSize") or 0) for r in tr), 2),
        "mean_trade_usd": round(st.mean(float(r.get("usdcSize") or 0) for r in tr), 2),
        "outcome_yes_frac_buys": round(sum(1 for r in buys if r.get("outcome") == "Yes") / len(buys), 2) if buys else None,
        "median_lead_h_to_slugdate_end": round(st.median(lead), 1) if lead else None,
        "trades_per_day": round(len(tr) / max(1e-9, (max(ts) - min(ts)) / 86400), 1),
    }
    if wx:
        out["weather_cities_top"] = dict(Counter(city_of(r.get("title")) for r in wx).most_common(12))
        out["weather_yes_frac"] = round(sum(1 for r in wx if r.get("outcome") == "Yes") / len(wx), 2)
        out["weather_median_price"] = round(st.median(float(r["price"]) for r in wx), 3)
    return out


def main(args):
    res = {}
    for a in args:
        name, w = a.split("=")
        w = w.lower()
        rec = record(pnl_series(w))
        prof = profile(activity(w))
        res[name] = {"wallet": w, "record": rec, "profile": prof}
        m = rec.get("months", {})
        print(f"\n### {name} {w}")
        print({k: v for k, v in rec.items() if k != "months"})
        print("months:", " ".join(f"{k[2:]}:{v}" for k, v in m.items()))
        print(json.dumps(prof))
    out = HERE / "verified.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    old.update(res)
    out.write_text(json.dumps(old, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])

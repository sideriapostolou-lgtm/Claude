"""Per-market record of a Polymarket wallet from data-api /closed-positions (includes losers). Read-only.

Usage: python3 -I closed.py name=0xwallet [max_pages]
Prints: markets, win rate, PnL by month, by entry-price bucket, by city (weather), by side, concentration.
"""
import json
import re
import statistics as st
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
S = requests.Session()
S.headers["User-Agent"] = "lab9-writeups-research/1.0 (read-only)"


def get(params):
    for i in range(6):
        try:
            r = S.get("https://data-api.polymarket.com/closed-positions", params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 + 2 * i)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(4 + 4 * i)
            continue
        time.sleep(0.3)
        return r.json() if r.status_code == 200 else []
    return []


def pull(w, max_pages):
    f = RAW / f"closed_{w}.json"
    if f.exists():
        return json.loads(f.read_text())
    rows = []
    for p in range(max_pages):
        d = get({"user": w, "limit": 50, "offset": 50 * p, "sortBy": "TIMESTAMP", "sortDirection": "DESC"})
        if not d:
            break
        rows += d
        if len(d) < 50:
            break
    f.write_text(json.dumps(rows))
    return rows


def city(t):
    m = re.search(r"temperature in ([A-Za-z .'-]+?) (?:be|on)\b", t or "")
    return m.group(1).strip() if m else ("hurricane" if re.search(r"hurricane|peak at category", t or "", re.I) else "non-temp")


def bucket(p):
    for hi, lab in [(.02, "<.02"), (.05, "<.05"), (.10, "<.10"), (.30, "<.30"), (.50, "<.50"), (.70, "<.70"), (.90, "<.90"), (.97, "<.97")]:
        if p < hi:
            return lab
    return ">=.97"


def kind(t):
    t = t or ""
    if re.search(r"or below", t):
        return "low-edge"
    if re.search(r"or higher|or above", t):
        return "high-edge"
    if re.search(r"between", t):
        return "range"
    if re.search(r"be -?\d+°[CF] on", t):
        return "exact1deg"
    return "other"


def summarize(name, rows):
    if not rows:
        print(name, "no rows")
        return {}
    by = lambda key: defaultdict(lambda: [0, 0, 0.0, 0.0])  # noqa: E731
    groups = {k: by(k) for k in ("month", "bucket", "city", "side", "kind")}
    pnls = []
    for r in rows:
        pnl = float(r.get("realizedPnl") or 0)
        cost = float(r.get("avgPrice") or 0) * float(r.get("totalBought") or 0)
        pnls.append(pnl)
        ts = r.get("timestamp") or 0
        keys = {"month": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m"),
                "bucket": bucket(float(r.get("avgPrice") or 0)), "city": city(r.get("title")),
                "side": r.get("outcome"), "kind": kind(r.get("title"))}
        for g, k in keys.items():
            a = groups[g][k]
            a[0] += 1
            a[1] += 1 if pnl > 0 else 0
            a[2] += pnl
            a[3] += cost
    tot = sum(pnls)
    srt = sorted(pnls, reverse=True)
    out = {"n": len(rows), "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 3), "pnl": round(tot),
           "top10_share": round(sum(srt[:10]) / tot, 2) if tot > 0 else None,
           "median_cost": round(st.median(float(r.get("avgPrice") or 0) * float(r.get("totalBought") or 0) for r in rows), 2),
           "from": datetime.fromtimestamp(min(r.get("timestamp") or 0 for r in rows), timezone.utc).strftime("%Y-%m-%d"),
           "to": datetime.fromtimestamp(max(r.get("timestamp") or 0 for r in rows), timezone.utc).strftime("%Y-%m-%d")}
    print(f"\n### {name}: {out}")
    for g in ("month", "bucket", "kind", "side", "city"):
        items = sorted(groups[g].items(), key=(lambda x: x[0]) if g in ("month", "bucket") else (lambda x: -x[1][0]))
        if g == "city":
            items = items[:15]
        print(f"  by {g}: " + "; ".join(f"{k} n={v[0]} win={v[1] / v[0]:.0%} pnl={v[2]:.0f} ret={v[2] / v[3] if v[3] else 0:+.0%}"
                                        for k, v in items))
    out["groups"] = {g: {k: v for k, v in d.items()} for g, d in groups.items()}
    return out


def main(args):
    max_pages = int(args[1]) if len(args) > 1 else 200
    name, w = args[0].split("=")
    res = summarize(name, pull(w.lower(), max_pages))
    f = HERE / "closed_summary.json"
    old = json.loads(f.read_text()) if f.exists() else {}
    old[name] = res
    f.write_text(json.dumps(old, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])

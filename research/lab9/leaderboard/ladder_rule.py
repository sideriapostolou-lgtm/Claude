"""Infer the rule of a crypto 'what price will X hit' ladder trader from public fills.

For each BUY in a BTC/ETH touch ladder (gamma event markets with groupItemTitle '↑ 150,000' / '↓ 80,000'):
  spot at the fill (Coinbase hourly close), strike distance (log), days to the market end,
  trailing 30-day realized vol (hourly closes, annualized), z = |ln(K/S)| / (vol*sqrt(T)),
  one-touch fair NO = 1 - 2*N(-z) (driftless reflection principle), price paid, outcome (resolved?).
Prints the distribution of z / price / days for the wallet's NO buys and the realized win rate by z bucket.
Usage: python3 ladder_rule.py <wallet> [...]
"""
import bisect
import json
import math
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from time_to_end import event, ts  # noqa: E402

HERE = Path(__file__).parent


def load_spot(p):
    d = json.loads((HERE / "raw" / f"spot_{p}.json").read_text())
    pts = sorted((int(k), float(v)) for k, v in d.items() if not k.startswith("w") and v is not None)
    return [t for t, _ in pts], [v for _, v in pts]


SPOT = {"BTC": load_spot("BTC-USD"), "ETH": load_spot("ETH-USD")}


def spot_at(coin, t):
    T, V = SPOT[coin]
    i = bisect.bisect_right(T, t) - 1
    return V[i] if 0 <= i < len(V) and t - T[i] < 7200 else None


def vol_at(coin, t, days=30):
    T, V = SPOT[coin]
    j = bisect.bisect_right(T, t)
    i = bisect.bisect_left(T, t - days * 86400)
    xs = V[i:j]
    if len(xs) < 100:
        return None
    r = [math.log(b / a) for a, b in zip(xs, xs[1:])]
    return st.pstdev(r) * math.sqrt(24 * 365)


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def strike(title):
    m = re.search(r"([↑↓])\s*\$?([\d,.]+)\s*(k?)", title or "")
    if not m:
        return None, None
    k = float(m.group(2).replace(",", ""))
    if m.group(3) == "k":
        k *= 1000
    return ("up" if m.group(1) == "↑" else "down"), k


def outcome_no_won(m):
    try:
        prices = json.loads(m.get("outcomePrices") or "[]")
        outs = json.loads(m.get("outcomes") or "[]")
    except (TypeError, ValueError):
        return None
    if not m.get("closed") or len(prices) != 2:
        return None
    pz = dict(zip(outs, [float(x) for x in prices]))
    if pz.get("No", 0) > 0.99:
        return True
    if pz.get("Yes", 0) > 0.99:
        return False
    return None


def main(ws):
    for w in ws:
        d = HERE / "raw" / "b" / w.lower()
        rows = json.loads((d / "act_newest.json").read_text())
        for v in json.loads((d / "act_slices.json").read_text()).values():
            rows += v
        seen, recs = set(), []
        for r in rows:
            if r.get("type") != "TRADE" or r.get("side") != "BUY":
                continue
            es = r.get("eventSlug") or ""
            if "hit" not in es or not re.search(r"(bitcoin|ethereum)", es):
                continue
            key = (r.get("transactionHash"), r.get("asset"), r.get("size"))
            if key in seen:
                continue
            seen.add(key)
            coin = "BTC" if "bitcoin" in es else "ETH"
            e = event(es)
            mk = {m.get("conditionId"): m for m in e.get("markets", []) or []}
            m = mk.get(r.get("conditionId"))
            if not m:
                continue
            direction, k = strike(m.get("groupItemTitle") or m.get("question"))
            end = ts(m.get("endDate"))
            s = spot_at(coin, r["timestamp"])
            vol = vol_at(coin, r["timestamp"])
            if not (direction and k and end and s and vol):
                continue
            T = max((end - r["timestamp"]) / (365 * 86400), 1e-6)
            dist = math.log(k / s)
            z = abs(dist) / (vol * math.sqrt(T))
            fair_no = 1 - min(1.0, 2 * ncdf(-z))
            side_no = (r.get("outcome") == "No")
            recs.append({
                "no": side_no, "price": float(r.get("price") or 0), "usd": float(r.get("usdcSize") or 0),
                "days": T * 365, "dist_pct": dist * 100, "dir": direction, "z": z, "vol": vol,
                "fair": fair_no if side_no else 1 - fair_no, "no_won": outcome_no_won(m), "cond": m.get("conditionId"),
            })
        no = [x for x in recs if x["no"]]
        yes = [x for x in recs if not x["no"]]
        print(f"== {w}  ladder buys {len(recs)}  NO {len(no)}  YES {len(yes)}")
        for lab, xs in (("NO", no), ("YES", yes)):
            if not xs:
                continue
            q = lambda key: [round(v, 2) for v in (lambda s: (s[len(s) // 10], st.median(s), s[9 * len(s) // 10]))(sorted(x[key] for x in xs))]  # noqa: E731
            usd = sum(x["usd"] for x in xs) or 1
            edge = sum((x["fair"] - x["price"]) * x["usd"] for x in xs) / usd
            print(f"   {lab}: price q10/50/90 {q('price')}  days {q('days')}  |dist%| "
                  f"{[round(abs(v), 1) for v in q('dist_pct')]}  z {q('z')}  vol {q('vol')}  "
                  f"$-wtd (fair-price) {edge:+.3f}  dir {dict((k, sum(1 for x in xs if x['dir'] == k)) for k in ('up', 'down'))}")
            # realized by z bucket (unique markets)
            bym = defaultdict(list)
            for x in xs:
                bym[x["cond"]].append(x)
            buckets = defaultdict(lambda: [0, 0, 0.0])
            for c, v in bym.items():
                won = v[0]["no_won"]
                if won is None:
                    continue
                won = won if lab == "NO" else not won
                zb = min(v, key=lambda x: x["z"])["z"]
                b = "<1.5" if zb < 1.5 else "1.5-2" if zb < 2 else "2-2.5" if zb < 2.5 else "2.5-3" if zb < 3 else ">=3"
                buckets[b][0] += 1
                buckets[b][1] += won
                buckets[b][2] += st.mean(x["price"] for x in v)
            print("   resolved markets by min-z: " + "  ".join(
                f"{b}: {n} mkts win {w_ / n:.3f} avgPx {p / n:.3f}" for b, (n, w_, p) in sorted(buckets.items())))


if __name__ == "__main__":
    main(sys.argv[1:])

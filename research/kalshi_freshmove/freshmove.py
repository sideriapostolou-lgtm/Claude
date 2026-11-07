"""H-K (declared 2026-10-13 13:10 UTC, before any result): the dangerously-skip-permissions trigger on Kalshi.

On Polymarket the wallet's money comes from taking the side Binance BTC just moved toward, 1-3 s after the move.
Question: after a fresh Binance move on a KXBTC15M window, are Kalshi taker buys of that side profitable after
Kalshi's full fee 0.07 p(1-p), and how fast must one be?

Fresh move at second s: dF = fair_up(s) - fair_up(s-2) >= theta (Up) or <= -theta (Down), theta in {0.02, 0.04}.
fair_up = Phi(ln(S/K) / (sigma sqrt(t))) with S = Binance close minus the window's basis (Binance 60 s mean before
the open minus Kalshi's strike, known at the open), sigma per second from the trailing hour of 1 s log returns,
t = seconds to close; only s in [open + 20, close - 180]. Overlapping events within 5 s of an earlier one in the
same direction are dropped.
Execution proxy at latency L in {0, 0.5, 1, 2, 3} s: the first Kalshi taker print buying that side in
(s + L, s + L + 1]; its price is what was offered then. Value: (a) the 60 s markout, the median YES price of all
prints in [tau + 55, tau + 65] (converted to the side bought), minus price and fee; (b) settlement (won - price -
fee). Placebo: every taker print of either side. Statistics are clustered by window.
"""
import csv, gzip, json, math, statistics, sys
from datetime import datetime
from pathlib import Path

PAIR, BTC = Path(sys.argv[1]), Path(sys.argv[2])
LAT = (0.0, 0.5, 1.0, 2.0, 3.0)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fee(p):
    return 0.07 * p * (1 - p)


btc = {}
with gzip.open(BTC, "rt") as f:
    r = csv.reader(f)
    next(r)
    for row in r:
        btc[int(row[0])] = float(row[4])
markets = {m["ticker"]: m for m in json.load(open(PAIR / "markets.json"))}


def sigma_at(s, cache={}):
    h = s // 300
    if h not in cache:
        rets = [math.log(btc[t] / btc[t - 1]) for t in range(s - 3600, s) if t in btc and t - 1 in btc]
        cache[h] = statistics.pstdev(rets) if len(rets) > 1800 else None
    return cache[h]


def window_events(m, prints):
    o, c, K = ts(m["open_time"]), ts(m["close_time"]), float(m["floor_strike"])
    pre = [btc[t] for t in range(int(o) - 60, int(o)) if t in btc]
    if len(pre) < 50:
        return None
    basis = statistics.mean(pre) - K
    def fair(s):
        S, sig = btc.get(s), sigma_at(s)
        if S is None or not sig:
            return None
        return phi(math.log((S - basis) / K) / (sig * math.sqrt(max(1.0, c - s))))
    events = []
    last = {1: -1e9, -1: -1e9}
    for s in range(int(o) + 20, int(c) - 180):
        f0, f2 = fair(s), fair(s - 2)
        if f0 is None or f2 is None:
            continue
        d = f0 - f2
        for theta in (0.02, 0.04):
            if abs(d) >= theta:
                side = 1 if d > 0 else -1
                if theta == 0.02:
                    if s - last[side] < 5:
                        break
                    last[side] = s
                events.append((s, side, theta, f0))
    return events


def analyse(windows):
    out = {}
    placebo = []
    for tk, m in windows:
        rows = json.load(open(PAIR / f"{tk}.json"))
        prints = sorted((ts(t), float(p), float(n), side) for t, p, n, side, _ in rows)
        times = [p[0] for p in prints]
        up_won = m["result"] == "yes"
        ev = window_events(m, prints)
        if ev is None:
            continue
        import bisect
        def value_yes(tau):
            i, j = bisect.bisect_left(times, tau + 55), bisect.bisect_right(times, tau + 65)
            seg = [prints[k][1] for k in range(i, j)]
            return statistics.median(seg) if seg else None
        for k in range(0, len(prints), 25):  # placebo sample
            t0, p, n, sd = prints[k]
            v = value_yes(t0)
            if v is None or t0 > ts(m["close_time"]) - 180:
                continue
            price = p if sd == "yes" else 1 - p
            val = v if sd == "yes" else 1 - v
            won = up_won if sd == "yes" else not up_won
            placebo.append((tk, val - price - fee(price), (1.0 if won else 0.0) - price - fee(price)))
        for s, side, theta, f0 in ev:
            want = "yes" if side == 1 else "no"
            for L in LAT:
                i = bisect.bisect_right(times, s + L)
                j = bisect.bisect_right(times, s + L + 1)
                hit = next((prints[k] for k in range(i, j) if prints[k][3] == want), None)
                if hit is None:
                    continue
                t0, p, n, sd = hit
                price = p if want == "yes" else 1 - p
                v = value_yes(t0)
                if v is None:
                    continue
                val = v if want == "yes" else 1 - v
                won = up_won if want == "yes" else not up_won
                out.setdefault((theta, L), []).append(
                    (tk, val - price - fee(price), (1.0 if won else 0.0) - price - fee(price)))
    return out, placebo


def clustered(rows, idx):
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r[idx])
    means = [statistics.mean(v) for v in by.values()]
    allv = [r[idx] for r in rows]
    mu = statistics.mean(allv)
    se = statistics.pstdev(means) / math.sqrt(len(means)) if len(means) > 1 else float("nan")
    return mu, (statistics.mean(means) / se if se else float("nan")), len(by)


if __name__ == "__main__":
    wins = sorted(((p.stem, markets[p.stem]) for p in PAIR.glob("KXBTC15M-*.json")
                   if p.stem in markets and markets[p.stem].get("result") in ("yes", "no")
                   and markets[p.stem].get("floor_strike")), key=lambda x: x[1]["open_time"])
    print("windows", len(wins), wins[0][0], "->", wins[-1][0])
    out, placebo = analyse(wins)
    mu, t, nw = clustered(placebo, 1)
    mu2, t2, _ = clustered(placebo, 2)
    print(f"PLACEBO all taker prints: n={len(placebo)} markout60 {mu:+.4f} (t {t:.2f}) | settle {mu2:+.4f} (t {t2:.2f})")
    for (theta, L), rows in sorted(out.items()):
        mu, t, nw = clustered(rows, 1)
        mu2, t2, _ = clustered(rows, 2)
        print(f"theta={theta} L={L}s: n={len(rows)} windows={nw} markout60 {mu:+.4f} (t {t:.2f}) | settle {mu2:+.4f} (t {t2:.2f})")

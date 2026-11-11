"""Kalshi public (keyless) social leaderboards and profiles for the owner's open categories. Read-only.

Endpoints found by reading the error bodies of https://api.elections.kalshi.com/v1/social/*:
  leaderboard?metric_name=projected_pnl&time_period=<p>&limit=<n>&category=<Kalshi category>
  profile?nickname=<n>            profile/metrics?nickname=<n>   (pnl, dollars_traded in 1e-4 USD units)
  trades?nickname=<n>             profile/holdings?nickname=<n>&limit=<n>   (often visibility_state=hidden)
Leaderboards are opt-in, so they show only traders who chose to appear.
"""
import json
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw" / "kalshi"
RAW.mkdir(parents=True, exist_ok=True)
B = "https://api.elections.kalshi.com/v1/social"
S = requests.Session()
S.headers["User-Agent"] = "lab9-writeups-research/1.0 (read-only)"
CATS = ["Climate and Weather", "Crypto", "Financials", "Economics", "Commodities"]
PERIODS = ["all_time", "yearly"]  # monthly/weekly/daily are accepted but return empty lists


def get(path, params):
    for i in range(6):
        try:
            r = S.get(f"{B}/{path}", params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 + 2 * i)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(4 + 4 * i)
            continue
        time.sleep(0.4)
        try:
            return r.json()
        except ValueError:
            return {"_status": r.status_code, "_text": r.text[:200]}
    return None


def boards(limit):
    out = {}
    for c in CATS:
        for p in PERIODS:
            d = get("leaderboard", {"metric_name": "projected_pnl", "time_period": p, "limit": limit, "category": c})
            out[f"{c}|{p}"] = (d or {}).get("rank_list", [])
            print(c, p, len(out[f"{c}|{p}"]), file=sys.stderr)
    (RAW / "boards.json").write_text(json.dumps(out, indent=1))
    return out


def profiles(names):
    res = {}
    for n in names:
        prof = get("profile", {"nickname": n}) or {}
        met = get("profile/metrics", {"nickname": n}) or {}
        tr = get("trades", {"nickname": n}) or {}
        ho = get("profile/holdings", {"nickname": n, "limit": 50}) or {}
        res[n] = {"profile": prof.get("social_profile"), "metrics": met.get("metrics"),
                  "trades_visibility": tr.get("visibility_state"), "n_trades_public": len(tr.get("trades") or []),
                  "holdings_visibility": ho.get("visibility_state"), "n_holdings_public": len(ho.get("holdings") or []),
                  "trades": tr.get("trades"), "holdings": ho.get("holdings")}
    (RAW / "profiles.json").write_text(json.dumps(res, indent=1))
    return res


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    f = RAW / "boards.json"
    b = json.loads(f.read_text()) if f.exists() else boards(limit)
    # consistency: in how many of the 4 windows each name appears, per category
    rows = []
    for c in CATS:
        seen = {}
        for p in PERIODS:
            for r in b[f"{c}|{p}"]:
                seen.setdefault(r["nickname"], {})[p] = (r["rank"], round(r["value"]))
        for n, v in seen.items():
            rows.append((c, n, len(v), v))
    rows.sort(key=lambda x: (-x[2], -(x[3].get("all_time", (0, 0))[1])))
    keep = [r for r in rows if r[2] >= 2]
    for c, n, k, v in keep:
        print(f"{c:20s} {n:24s} windows={k} {v}")
    names = sorted({n for _, n, _, _ in keep})
    pr = profiles(names)
    for n in names:
        m = pr[n]["metrics"] or {}
        p = pr[n]["profile"] or {}
        pnl = (m.get("pnl") or 0) / 1e4
        dt = (m.get("dollars_traded") or 0) / 1e4
        print(f"{n:24s} joined={p.get('joined_at')} top={p.get('top_categories')} pnl=${pnl:,.0f} traded=${dt:,.0f} "
              f"edge={pnl / dt if dt else 0:.3%} markets={m.get('num_markets_traded')} trades={pr[n]['trades_visibility']}:"
              f"{pr[n]['n_trades_public']} holdings={pr[n]['holdings_visibility']}:{pr[n]['n_holdings_public']}")


if __name__ == "__main__":
    main()

"""Cash-flow ledger of a wallet's Polymarket weather markets from public /activity + gamma resolutions.

Per market: PnL = -buys + sells + redeems + merges - splits (+ unredeemed winning shares x payout). Assigned to the
market's end date. Rewards/rebates reported separately. Gives the record (PnL, bets, win rate, drawdown, months)."""
import json, sys, re, collections, statistics as st, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from timing import parse
RAW = Path(__file__).parent / "raw"
RES = None
def res():
    global RES
    if RES is None: RES = json.load(open(RAW / "pm_resolutions.json"))
    return RES

def ledger(wallet, verbose=True):
    a = json.load(open(RAW / "activity" / f"{wallet}.json"))
    R = res()
    mk = {}
    other = collections.Counter(); bonus = 0.0
    for x in a:
        t = x["type"]; cid = x.get("conditionId") or ""
        if t in ("REWARD", "MAKER_REBATE", "TAKER_REBATE", "REFERRAL_REWARD", "YIELD"):
            bonus += x.get("usdcSize") or 0; continue
        if cid not in R: other[t] += 1; continue
        m = mk.setdefault(cid, {"cash": 0.0, "sh": collections.defaultdict(float), "redeemed": False, "buy_usd": 0.0,
                                "buys": [], "first_ts": x["timestamp"], "title": x.get("title"), "slug": x.get("eventSlug")})
        u = x.get("usdcSize") or 0.0; s = x.get("size") or 0.0; oi = x.get("outcomeIndex")
        if t == "TRADE":
            if x["side"] == "BUY":
                m["cash"] -= u; m["sh"][oi] += s; m["buy_usd"] += u; m["buys"].append((x["price"], u, x["timestamp"], x.get("outcome")))
            else:
                m["cash"] += u; m["sh"][oi] -= s
        elif t == "REDEEM": m["cash"] += u; m["redeemed"] = True
        elif t == "SPLIT": m["cash"] -= u; m["sh"][0] += s; m["sh"][1] += s
        elif t == "MERGE": m["cash"] += u; m["sh"][0] -= s; m["sh"][1] -= s
        else: other["in_mkt_" + t] += 1
    rows = []
    for cid, m in mk.items():
        r = R[cid]
        pnl = m["cash"]
        if not m["redeemed"]:
            for oi, sh in m["sh"].items():
                if sh > 0.01 and oi is not None and oi < len(r["payout"]): pnl += sh * r["payout"][oi]
        end = (r.get("end") or "")[:10]
        rows.append({"cid": cid, "pnl": pnl, "buy_usd": m["buy_usd"], "end": end, "title": m["title"], "slug": m["slug"],
                     "buys": m["buys"], "first_ts": m["first_ts"]})
    rows = [r for r in rows if r["end"] and r["buy_usd"] > 0]
    if not rows: return None
    days = collections.defaultdict(float); months = collections.defaultdict(float); ndays = collections.Counter()
    for r in rows: days[r["end"]] += r["pnl"]; months[r["end"][:7]] += r["pnl"]
    cum = peak = mdd = 0.0
    for d in sorted(days): cum += days[d]; peak = max(peak, cum); mdd = max(mdd, peak - cum)
    weeks = collections.defaultdict(float)
    for d, v in days.items(): weeks[dt.date.fromisoformat(d).isocalendar()[:2]] += v
    tot = sum(r["pnl"] for r in rows); bought = sum(r["buy_usd"] for r in rows)
    wins = sum(r["pnl"] > 0 for r in rows)
    vw_price = sum(p * u for r in rows for p, u, *_ in r["buys"]) / max(1e-9, sum(u for r in rows for _, u, *_ in r["buys"]))
    out = {"wallet": wallet, "markets": len(rows), "events": len({r["slug"] for r in rows}), "first": min(days), "last": max(days),
           "active_days": len(days), "pnl": round(tot), "bought_usd": round(bought), "pnl_per_$bought": round(tot / bought, 4) if bought else None,
           "win_rate_markets": round(wins / len(rows), 3), "pos_days": round(sum(v > 0 for v in days.values()) / len(days), 3),
           "pos_weeks": round(sum(v > 0 for v in weeks.values()) / len(weeks), 3), "weeks": len(weeks),
           "max_dd": round(mdd), "worst_day": round(min(days.values())), "best_day": round(max(days.values())),
           "median_buy_usd_per_market": round(st.median(r["buy_usd"] for r in rows), 2),
           "vw_buy_price": round(vw_price, 3), "rewards_rebates": round(bonus),
           "months": {k: round(v) for k, v in sorted(months.items())}, "unmatched_types": dict(other)}
    if verbose: print(json.dumps(out))
    return out, rows

if __name__ == "__main__":
    for w in sys.argv[1:]:
        r = ledger(w)

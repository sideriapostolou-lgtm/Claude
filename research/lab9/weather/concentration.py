"""How much of a wallet's weather PnL comes from its few biggest wins (lottery dependence), plus last-90-day record."""
import sys, json, statistics as st, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ledger import ledger
for w in sys.argv[1:]:
    r = ledger(w, verbose=False)
    if not r: continue
    s, rows = r
    tot = sum(x["pnl"] for x in rows)
    srt = sorted(rows, key=lambda x: -x["pnl"])
    top10 = sum(x["pnl"] for x in srt[:10]); top1p = sum(x["pnl"] for x in srt[:max(1, len(rows) // 100)])
    cut = (dt.date(2026, 10, 12) - dt.timedelta(days=90)).isoformat()
    last = [x for x in rows if x["end"] >= cut]
    lp = sum(x["pnl"] for x in last); lb = sum(x["buy_usd"] for x in last)
    print(f"{w[:10]} markets={len(rows)} pnl={tot:.0f} top10={top10:.0f} ({top10/tot if tot else 0:.2f}) top1%={top1p:.0f} ({top1p/tot if tot else 0:.2f}) "
          f"pnl_ex_top10={tot-top10:.0f} | last90d markets={len(last)} pnl={lp:.0f} bought={lb:.0f} pnl/$={lp/lb if lb else 0:.3f}")
    for x in srt[:3]: print("     top:", round(x["pnl"]), x["title"][:80], x["end"])

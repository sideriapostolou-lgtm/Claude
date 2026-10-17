"""Compact long-run record per wallet from the cash-flow ledger: days, weeks, worst week, losing-day streak, last 30/90 days."""
import sys, collections, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ledger import ledger
for w in sys.argv[1:]:
    s, rows = ledger(w, verbose=False)
    rows = [r for r in rows if r["end"] <= "2026-10-12"]
    days = collections.defaultdict(float)
    for r in rows: days[r["end"]] += r["pnl"]
    ds = sorted(days); weeks = collections.defaultdict(float)
    for d in ds: weeks[dt.date.fromisoformat(d).isocalendar()[:2]] += days[d]
    streak = best = 0
    for d in ds:
        streak = streak + 1 if days[d] < 0 else 0; best = max(best, streak)
    def window(n):
        cut = (dt.date(2026, 10, 12) - dt.timedelta(days=n)).isoformat()
        rr = [r for r in rows if r["end"] > cut]
        return len(rr), round(sum(r["pnl"] for r in rr)), round(sum(r["buy_usd"] for r in rr))
    print(w[:12], "markets", len(rows), "pnl", round(sum(days.values())), "days", len(ds), ds[0], "->", ds[-1],
          "avg/day", round(sum(days.values()) / len(ds)), "worst week", round(min(weeks.values())), "neg weeks", sum(v < 0 for v in weeks.values()), "/", len(weeks),
          "max losing-day streak", best, "| last30d (mk,pnl,bought)", window(30), "last90d", window(90))

"""Compact summary of stage-B profiles (+ stage-A P&L stats). Usage: python3 summ_b.py [wallet ...]"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze_b import profile  # noqa: E402

HERE = Path(__file__).parent
A = {r["wallet"]: r for r in csv.DictReader(open(HERE / "stage_a.csv"))}


def f(x, n=0):
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def main(ws):
    if not ws:
        ws = [p.name for p in (HERE / "raw" / "b").iterdir() if (p / "open.json").exists()]
    for w in ws:
        w = w.lower()
        P = profile(w)
        a = A.get(w, {})
        print(f"== {P['name'][:40]}  {w}")
        print(f"   PnL ${f(a.get('pnl_total'))}  active {a.get('first_active')}..{a.get('last_active')} "
              f"({f(a.get('active_span_days'))}d)  maxDD ${f(a.get('mdd'))}  upDays {f(a.get('up_day_frac'), 2)} "
              f"upWeeks {f(a.get('up_week_frac'), 2)}  months {a.get('months_up')}/{a.get('months_active')} up  "
              f"worstMonth ${f(a.get('worst_month'))}  top5dayShare {f(a.get('top5_day_share'), 2)}  "
              f"30d ${f(a.get('pnl_30d'))} 90d ${f(a.get('pnl_90d'))}")
        print(f"   mix now {P['mix_newest']}  slices " +
              " | ".join(f"{k}d:{list(v)[:2]}" for k, v in P["mix_slices"].items()))
        print(f"   newest {P['newest_trades']} trades/{P['newest_span_h']}h  types {P['types']}  takerFrac {P.get('taker_frac')} "
              f"medFill ${P['median_fill_usd']} p90 ${P['p90_fill_usd']}  sellFrac {P['sell_frac']}  $/mkt {P['median_usd_per_market']}")
        print(f"   buyPrice$ {P['buy_price_usd_share']}")
        print(f"   bothSides {P['both_sides_frac']} pairCost {P['median_pair_cost']} (<1: {P['pair_cost_lt1_frac']}) "
              f"imbal {P['median_imbalance']}  leadS {P.get('window_lead_s_q10_50_90')} last60s {P.get('frac_fills_last_60s')}")
        print(f"   closed {P['closed_n']} win {P['win_rate_closed_only']} (incl unredeemed {P['win_rate_incl_unredeemed']}, "
              f"{P['unredeemed_losers_n']} open losers ${P['sum_pnl_unredeemed_losers']})  sumClosed ${P['sum_pnl_closed']} "
              f"medPnL/mkt {P['median_pnl_per_market']} worst {P['worst_market']} best {P['best_market']} "
              f"medAvgPrice {P['closed_median_avgPrice']}")
        print(f"   closedByFam {P['closed_by_family']}")


if __name__ == "__main__":
    main(sys.argv[1:])

"""Markdown tables for RESULTS.md from the judge's JSON outputs (LAB/judge/*.json).

    python research/lab/judge/report_tables.py > /tmp/tables.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from harness import LAB  # noqa: E402

J = LAB / "judge"
VARIANTS = [("base", "Base (default costs)"), ("costs_x1.5", "Costs x1.5"), ("costs_x2", "Costs x2"),
            ("latency_+1bar", "+1 candle latency"), ("wick_worst", "Worst-case wick fills"),
            ("rug_aware_fills", "Rug-aware stop fills"), ("without_best_coin", "Without the best coin"),
            ("first_half", "First half of split"), ("second_half", "Second half of split")]
SHORT = {"S4_vol_dip_wideband_10k": "F1-S4", "S1_vol_dip_fixed": "F1-S1",
         "F4_farm_climb_gbt_tp30_sl15_h15_q98": "F4-#1 (q98)", "F4_farm_climb_gbt_tp30_sl15_h15_q99": "F4-#2 (q99)"}


def f(v, d=1, pct=False):
    if v is None:
        return "–"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(f(x, d) for x in v) + "]"
    s = f"{v:+.{d}f}" if pct else f"{v:.{d}f}"
    return s


def main_table(res: dict) -> str:
    rows = ["| Finalist | Trades (coins) | Win % | Avg / trade | Median | 95% CI (coin bootstrap) | "
            "Bonferroni CI | p (one-sided) | p Holm (m=4) | p Bonferroni (all configs) | $100 portfolio | Max DD | "
            "Exits |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in res["finalists"].items():
        pc, pf, bt = r["base"]["per_coin"], r["base"]["portfolio"], r["bootstrap"]
        p, ph, pb = bt.get("p_one_sided"), r.get("p_holm"), r.get("p_bonferroni_all_configs")
        rows.append(
            f"| {SHORT.get(n, n)} | {pc['trades']} ({pc['coins_traded']}) | {f(pc['win_rate_pct'], 0)} | "
            f"{f(pc['avg_ret_pct'], 1, True)}% | {f(pc['median_ret_pct'], 1, True)}% | {f(bt.get('ci95_pct'))} | "
            f"{f(bt.get('ci_bonf_pct'))} | {'–' if p is None else f'{p:.3f}'} | "
            f"{'–' if ph is None else f'{ph:.3f}'} | {'–' if pb is None else f'{pb:.2f}'} | "
            f"{f(pf['total_return_pct'], 1, True)}% | {f(pf['max_drawdown_pct'], 1)}% | {pc['exit_reasons']} |")
    return "\n".join(rows)


def robust_table(res: dict) -> str:
    names = list(res["finalists"])
    head = "| Check | " + " | ".join(SHORT.get(n, n) for n in names) + " |"
    rows = [head, "|---|" + "---|" * len(names)]
    for key, label in VARIANTS:
        cells = []
        for n in names:
            r = res["finalists"][n].get(key)
            if not r:
                cells.append("–")
                continue
            pc, pf = r["per_coin"], r["portfolio"]
            cells.append(f"{pc['trades']} tr, {f(pc['avg_ret_pct'], 1, True)}% / "
                         f"{f(pf['total_return_pct'], 1, True)}%")
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    rows.append("| P&L without best / top-3 coins ($, per-coin) | " + " | ".join(
        f"{f(res['finalists'][n]['base']['per_coin']['pnl_without_best_coin_usd'], 2)} / "
        f"{f(res['finalists'][n]['base']['per_coin']['pnl_without_top3_usd'], 2)}" for n in names) + " |")
    rows.append("| Lookahead audit on these coins | " + " | ".join(
        "clean" if not res["finalists"][n]["audit_lookahead"] else f"{len(res['finalists'][n]['audit_lookahead'])} problems"
        for n in names) + " |")
    return "\n".join(rows)


def gates_table(res: dict) -> str:
    names = list(res["finalists"])
    keys = list(next(iter(res["finalists"].values()))["gates"])
    rows = ["| Gate | " + " | ".join(SHORT.get(n, n) for n in names) + " |", "|---|" + "---|" * len(names)]
    for k in keys:
        rows.append(f"| {k} | " + " | ".join("pass" if res["finalists"][n]["gates"][k] else "**FAIL**"
                                             for n in names) + " |")
    rows.append("| **WINNER** | " + " | ".join("YES" if res["finalists"][n]["winner"] else "no" for n in names) + " |")
    return "\n".join(rows)


def baseline_table(res: dict) -> str:
    rows = ["| Baseline | Trades | Win % | Avg / trade | Median | 95% CI | $100 portfolio | Max DD |",
            "|---|---|---|---|---|---|---|---|"]
    for k, b in res["baselines"].items():
        pc, pf = b["per_coin"], b["portfolio"]
        rows.append(f"| {k} | {pc['trades']} | {f(pc['win_rate_pct'], 0)} | {f(pc['avg_ret_pct'], 1, True)}% | "
                    f"{f(pc['median_ret_pct'], 1, True)}% | {f(pc['exp_ci95_pct'])} | "
                    f"{f(pf['total_return_pct'], 1, True)}% | {f(pf['max_drawdown_pct'], 1)}% |")
    return "\n".join(rows)


def trades_table(res: dict, name: str) -> str:
    rows = ["| Coin | Entry (UTC) | Min after grad | Exit | Hold (min) | Net return |", "|---|---|---|---|---|---|"]
    import time
    for t in res["finalists"][name]["trades_per_coin"]:
        rows.append(f"| {t['symbol']} | {time.strftime('%H:%M', time.gmtime(t['entry_ts']))} | "
                    f"{t['min_after_grad']} | {t['exit_reason']} | {t['hold_min']} | {t['ret_pct']:+.1f}% |")
    return "\n".join(rows)


if __name__ == "__main__":
    for fname in ("test_results.json", "validation_dryrun.json"):
        p = J / fname
        if not p.exists():
            continue
        res = json.loads(p.read_text())
        print(f"\n## {fname} ({res['split']}, {res['n_coins']} coins)\n")
        print(main_table(res), "\n")
        print(robust_table(res), "\n")
        print(gates_table(res), "\n")
        print(baseline_table(res), "\n")
        for n in res["finalists"]:
            print(f"\n### trades {n}\n")
            print(trades_table(res, n))

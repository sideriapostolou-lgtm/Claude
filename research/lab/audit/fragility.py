"""Fragility of finalist F4-#1 (q98) on VALIDATION, TEST and both pooled (auditor; no harness import).

* by UTC hour of entry, by entry market-cap band, without the top-5 coins;
* entries delayed by 1 and 2 extra minutes (fill at the open of bar i+2 / i+3);
* a 30 % chance of missing each entry (latency / competition), Monte Carlo;
* fill / cost bounds: optimistic "touch" stop fills, rug-aware fills, zero costs, live-measured costs;
* a simple chronological $100 portfolio (20 % of equity, $5-$25, max 3 open, one per coin) for every
  variant, checked against the judge's harness portfolio on the base run.

    python research/lab/audit/fragility.py  -> LAB/audit/fragility.json
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_f4 as I  # noqa: E402


def coin_boot_ci(trades: list[dict], b: int = 4000, seed: int = 7) -> list[float] | None:
    by: dict[str, list[float]] = {}
    for t in trades:
        by.setdefault(t["mint"], []).append(t["ret_pct"])
    g = list(by.values())
    if len(g) < 2:
        return None
    rng = np.random.default_rng(seed)
    sums, lens = np.array([sum(x) for x in g]), np.array([len(x) for x in g])
    idx = rng.integers(0, len(g), size=(b, len(g)))
    m = sums[idx].sum(1) / lens[idx].sum(1)
    return [round(float(np.quantile(m, 0.025)), 2), round(float(np.quantile(m, 0.975)), 2)]


def portfolio(trades: list[dict], start: float = 100.0, pct: float = 0.20, lo: float = 5.0, hi: float = 25.0,
              max_open: int = 3) -> dict:
    """Chronological compounding; P&L of a trade = size x its per-$20 net return (costs ~ proportional)."""
    eq, open_, peak, dd = start, [], start, 0.0
    taken = 0
    for t in sorted(trades, key=lambda t: t["entry_ts"]):
        for o in [o for o in open_ if o[0] <= t["entry_ts"]]:
            eq += o[1]
            open_.remove(o)
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100)
        if len(open_) >= max_open:
            continue
        size = min(eq * pct, hi)
        if size < lo:
            continue
        open_.append((t["exit_ts"], size * t["ret_pct"] / 100))
        taken += 1
    for o in sorted(open_):
        eq += o[1]
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100)
    return {"return_pct": round(eq - start, 2) if start == 100 else round((eq / start - 1) * 100, 2),
            "max_dd_pct": round(dd, 1), "trades": taken}


def stats(trades: list[dict]) -> dict:
    r = [t["ret_pct"] for t in trades]
    if not r:
        return {"trades": 0}
    return {"trades": len(r), "win_pct": round(100 * np.mean([x > 0 for x in r]), 1), "mean_pct": round(float(np.mean(r)), 2),
            "ci95": coin_boot_ci(trades), "pnl_usd_at_20": round(sum(t["pnl_usd"] for t in trades), 2),
            "portfolio": portfolio(trades)}


def band(mc: float) -> str:
    for hi, lab in ((450e3, "<$450k"), (550e3, "$450-550k"), (650e3, "$550-650k"), (750e3, "$650-750k")):
        if mc < hi:
            return lab
    return ">=$750k"


def run_all() -> dict:
    out: dict = {}
    live = json.loads((I.OUT / "live_costs.json").read_text())
    rows = live["rows"]
    rt_mean = float(np.mean([r["measured_rt_pct"] for r in rows]))
    rt_min = float(min(r["measured_rt_pct"] for r in rows))
    model_rt = float(np.mean([r["model_rt_pct_no_mev_no_network"] for r in rows]))
    variants = {
        "base": dict(),
        "delay_+1min": dict(delay=2),
        "delay_+2min": dict(delay=3),
        "touch_stop_fills (optimistic bound)": dict(wick="touch"),
        "rug_aware_fills": dict(rug_aware=True),
        "zero_costs (gross)": dict(costs=I.Costs(mult=0.0)),
        # measured: per-side fee chosen so the model round trip (no MEV, no network) equals the mean live
        # measurement; MEV buffer dropped, network kept
        "live_measured_costs_mean": dict(costs=None, rt=rt_mean),
        "live_measured_costs_cheapest": dict(costs=None, rt=rt_min),
    }
    for split in ("validation", "test"):
        res = {}
        for name, kw in variants.items():
            kw = dict(kw)
            if "rt" in kw:
                rt = kw.pop("rt")
                # impact part of the round trip at this size/mcap is ~ model_rt - 2*(1.00+0.10)
                impact_rt = max(model_rt - 2 * (1.00 + I.ULTRA_PCT), 0.0)
                kw["costs"] = I.Costs(side_pct_override=max((rt - impact_rt) / 2, 0.0))
            r = I.run(split, 0.98, **kw)
            res[name] = [t for t in r["trades"] if "ret_pct" in t]
        out[split] = res
    report: dict = {"live_rt_mean_pct": round(rt_mean, 3), "live_rt_min_pct": round(rt_min, 3),
                    "model_rt_pct_same_coins": round(model_rt, 3)}
    for scope in ("validation", "test", "pooled"):
        tr = {k: (out["validation"][k] + out["test"][k]) if scope == "pooled" else out[scope][k] for k in variants}
        rep = {k: stats(v) for k, v in tr.items()}
        base = tr["base"]
        by_hour: dict[int, list] = {}
        by_band: dict[str, list] = {}
        for t in base:
            by_hour.setdefault(int(t["entry_ts"] // 3600 % 24), []).append(t)
            by_band.setdefault(band(t["entry_mcap_usd"]), []).append(t)
        rep["by_hour_utc"] = {h: {"trades": len(v), "mean_pct": round(float(np.mean([t["ret_pct"] for t in v])), 2)}
                              for h, v in sorted(by_hour.items())}
        rep["by_entry_mcap"] = {b: {"trades": len(v), "mean_pct": round(float(np.mean([t["ret_pct"] for t in v])), 2)}
                                for b, v in sorted(by_band.items())}
        pnl: dict[str, float] = {}
        for t in base:
            pnl[t["mint"]] = pnl.get(t["mint"], 0.0) + t["pnl_usd"]
        top5 = set(sorted(pnl, key=pnl.get, reverse=True)[:5])
        rep["without_top5_coins"] = stats([t for t in base if t["mint"] not in top5])
        # 30 % chance of missing each entry
        rng = random.Random(2026)
        means, ports, pos = [], [], 0
        for _ in range(10_000):
            kept = [t for t in base if rng.random() >= 0.30]
            if not kept:
                continue
            m = float(np.mean([t["ret_pct"] for t in kept]))
            means.append(m)
            ports.append(portfolio(kept)["return_pct"])
            pos += m > 0
        rep["miss_30pct_of_entries"] = {
            "draws": len(means), "mean_of_means_pct": round(float(np.mean(means)), 2),
            "p05_p50_p95_mean_pct": [round(float(np.quantile(means, q)), 2) for q in (0.05, 0.5, 0.95)],
            "share_of_draws_mean_positive": round(pos / len(means), 3),
            "portfolio_p05_p50_p95_pct": [round(float(np.quantile(ports, q)), 2) for q in (0.05, 0.5, 0.95)]}
        report[scope] = rep
    (I.OUT / "fragility.json").write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    rep = run_all()
    for scope in ("validation", "test", "pooled"):
        print(f"== {scope}")
        for k, v in rep[scope].items():
            print(f"  {k}: {json.dumps(v)}")

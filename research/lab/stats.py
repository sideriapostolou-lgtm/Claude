"""Descriptive dataset statistics for DATASET.md (uses outcome information - NEVER a strategy input).

    python research/lab/stats.py [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from costs import K_GRAD, SolUsd  # noqa: E402
from harness import LAB, SPLITS, in_default_universe  # noqa: E402

ACTIVE_USD_PER_MIN = 100.0  # a minute "counts" when at least $100 traded


def q(vals, ps=(0.1, 0.25, 0.5, 0.75, 0.9, 0.99)):
    vals = sorted(vals)
    if not vals:
        return {}
    return {f"p{int(p * 100)}": round(vals[min(len(vals) - 1, int(p * (len(vals) - 1) + 0.5))], 3) for p in ps}


def main() -> dict:
    cen = json.loads((LAB / "census.json").read_text())
    docs = [json.loads(p.read_text()) for p in sorted((LAB / "coins").glob("*.json"))]
    sol = SolUsd.from_lab()
    splits = json.loads(SPLITS.read_text())
    split_of = {m: s for s in ("train", "validation", "test") for m in splits[s]}
    out: dict = {
        "census_utc": cen["census_started_utc"],
        "created_range_utc": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(cen["created_min_ts"])),
                              time.strftime("%Y-%m-%d %H:%M", time.gmtime(cen["created_max_ts"]))],
        "coins": len(docs),
        "sources": Counter(d["coverage"]["source"] for d in docs),
        "complete_from_creation": sum(d["coverage"]["complete_from_creation"] for d in docs),
        "quote": Counter("SOL" if d["launch"]["quote_is_sol"] else "other" for d in docs),
        "mayhem": sum(bool(d["launch"]["mayhem"]) for d in docs),
        "bars": sum(d["coverage"]["n_candles"] for d in docs),
        "synthetic_bars": sum(d["coverage"]["n_synthetic"] for d in docs),
    }
    uni = [d for d in docs if in_default_universe(d)]
    out["default_universe"] = len(uni)
    out["default_universe_by_split"] = Counter(split_of.get(d["mint"], "?") for d in uni)
    census_end = cen["census_finished_ts"]
    grad_delay, peak_mult, end_mult, t_peak, alive, floor, vol_1h = [], [], [], [], [], 0, []
    died = {"1h": [0, 0], "6h": [0, 0]}
    instant = 0
    for d in uni:
        g = d["graduated_ts"]
        bars = d["candles"]
        grad_delay.append((g - d["created_ts"]) / 60)
        instant += (g - d["created_ts"]) <= 5
        j = next((k for k, r in enumerate(bars) if r[0] + 60 > g), None)
        if j is None:
            continue
        p0 = bars[j][4]
        post = bars[j + 1:]
        if post:
            hi = max(post, key=lambda r: r[2])
            peak_mult.append(hi[2] / p0)
            t_peak.append((hi[0] - g) / 60)
            end_mult.append(post[-1][4] / p0)
        last_active = max((r[0] for r in bars if r[5] >= ACTIVE_USD_PER_MIN), default=bars[0][0])
        observed = census_end - g
        for label, h in (("1h", 3600), ("6h", 6 * 3600)):
            if observed >= h + 1800:  # need the horizon plus 30 min to call it dead
                died[label][1] += 1
                died[label][0] += (last_active - g) <= h
        vol_1h.append(sum(r[5] for r in bars if g <= r[0] < g + 3600))
        last = bars[-1]
        mcap_sol = last[4] * d["supply"] / sol.at(last[0])
        floor += mcap_sol < 1.5 * K_GRAD / 1e9  # whole supply back in the pool -> ~17.6 SOL
        alive.append(observed / 3600)
    out.update({
        "instant_graduation_le_5s": instant,
        "graduation_delay_min": q(grad_delay),
        "died_within_1h": {"dead": died["1h"][0], "of": died["1h"][1],
                           "pct": round(100 * died["1h"][0] / max(died["1h"][1], 1), 1)},
        "died_within_6h": {"dead": died["6h"][0], "of": died["6h"][1],
                           "pct": round(100 * died["6h"][0] / max(died["6h"][1], 1), 1)},
        "death_rule": f"no minute with >= ${ACTIVE_USD_PER_MIN:.0f} volume after graduation + horizon",
        "peak_multiple_after_graduation_close": q(peak_mult),
        "share_peak_ge_2x": round(100 * sum(m >= 2 for m in peak_mult) / len(peak_mult), 1),
        "share_peak_ge_10x": round(100 * sum(m >= 10 for m in peak_mult) / len(peak_mult), 1),
        "share_peak_lt_1_1x": round(100 * sum(m < 1.1 for m in peak_mult) / len(peak_mult), 1),
        "minutes_to_peak": q(t_peak),
        "end_multiple_at_census": q(end_mult),
        "share_end_below_0_1x": round(100 * sum(m < 0.1 for m in end_mult) / len(end_mult), 1),
        "share_at_floor_mcap_at_census": round(100 * floor / len(uni), 1),
        "volume_usd_first_hour": q(vol_1h),
        "hours_observed_after_graduation": q(alive),
    })
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    res = main()
    print(json.dumps(res, indent=1, default=str))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str))

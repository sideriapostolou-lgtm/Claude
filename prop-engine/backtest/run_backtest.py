"""Walk-forward backtest — the binding doctrine.

Same pricing code path as live (engine.pricing.price / price_inning_hr), fed
only data available pregame:
  - structural factors (inning shape, exp PA, park, starter share) fitted on
    2024-2025 seasons ONLY (data/fits_before_2026-01-01.json)
  - team/pitcher rates accumulate day by day: game on day D is priced with
    counts through D-1, then D's plays are ingested

For every game in the window we price "HR in inning N" for N = 1..9, grade
against the actual play-by-play, and report calibration (predicted buckets vs
realized), Brier score, and book P&L at $10 flat per market at our posted
(margined) odds.

Usage: python -m backtest.run_backtest 2026-05-01 2026-07-06
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.base import GameInfo  # noqa: E402
from engine.inning_hr import price_inning_hr  # noqa: E402
from engine.odds import MAX_IMPLIED, american  # noqa: E402
from engine.rates import (PITCHER_FACTOR_CLAMP, PITCHER_PRIOR_PA, _regress)  # noqa: E402
from engine.risk import TIERS, RiskEngine  # noqa: E402
from parser.propspec import Constraints, PropSpec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus" / "mlb"
REPORTS_DIR = ROOT / "backtest" / "reports"


class IncrementalRates:
    """Day-by-day accumulating rates. Interface matches engine.rates.Rates.

    v1.1: splits bullpen (non-starter) HR rates per pitching team and carries
    hr_drift, a trailing realized-vs-predicted recalibration multiplier set by
    the runner (default 1.0).
    """

    def __init__(self):
        self._team = defaultdict(lambda: [0, 0])
        self._pitcher = defaultdict(lambda: [0, 0])
        self._bullpen = defaultdict(lambda: [0, 0])
        self._total = [0, 0]
        self.league_hr_pa = 0.030
        self.hr_drift = 1.0

    def ingest_day(self, day: str):
        f = CORPUS_DIR / f"plays_{day}.csv"
        if not f.exists():
            return
        gf = CORPUS_DIR / f"games_{day}.csv"
        game_sides = {r["gamePk"]: (r["away_id"], r["home_id"])
                      for r in csv.DictReader(open(gf))} if gf.exists() else {}
        starter: dict[tuple, str] = {}
        for r in csv.DictReader(open(f)):
            is_hr = r["event_type"] == "home_run"
            self._team[r["bat_team_id"]][0] += is_hr
            self._team[r["bat_team_id"]][1] += 1
            self._pitcher[r["pitcher_id"]][0] += is_hr
            self._pitcher[r["pitcher_id"]][1] += 1
            self._total[0] += is_hr
            self._total[1] += 1
            sides = game_sides.get(r["gamePk"])
            if sides:
                pitch_team = sides[1] if r["half"] == "top" else sides[0]
                half_key = (r["gamePk"], r["half"])
                if half_key not in starter:
                    starter[half_key] = r["pitcher_id"]
                if r["pitcher_id"] != starter[half_key]:
                    self._bullpen[pitch_team][0] += is_hr
                    self._bullpen[pitch_team][1] += 1
        if self._total[1] > 5000:
            self.league_hr_pa = self._total[0] / self._total[1]

    def team_bullpen_hr_factor(self, team_id) -> float:
        hr, bf = self._bullpen.get(str(team_id), (0, 0))
        rate, _ = _regress(hr, bf, self.league_hr_pa, PITCHER_PRIOR_PA)
        lo, hi = PITCHER_FACTOR_CLAMP
        return min(max(rate / self.league_hr_pa, lo), hi)

    def team_hr_pa(self, team_id) -> tuple[float, float]:
        hr, pa = self._team.get(str(team_id), (0, 0))
        if pa < 200:
            return self.league_hr_pa, float(max(hr, 1))
        return hr / pa, float(hr)

    def pitcher_hr_factor(self, pitcher_id) -> tuple[float, float]:
        if pitcher_id in (None, ""):
            return 1.0, 0.0
        hr, bf = self._pitcher.get(str(pitcher_id), (0, 0))
        rate, n = _regress(hr, bf, self.league_hr_pa, PITCHER_PRIOR_PA)
        lo, hi = PITCHER_FACTOR_CLAMP
        return min(max(rate / self.league_hr_pa, lo), hi), n


def run(start: str, end: str) -> dict:
    fits_path = ROOT / "data" / "fits_before_2026-01-01.json"
    if not fits_path.exists():
        raise SystemExit("run `python -m backtest.fit_factors 2026-01-01` first")
    fits = json.loads(fits_path.read_text())

    # warm up rates on all 2026 days before the window
    rates = IncrementalRates()
    days = sorted(f.stem.replace("plays_", "") for f in CORPUS_DIR.glob("plays_2026-*.csv"))
    warm = [d for d in days if d < start]
    window = [d for d in days if start <= d <= end]
    for d in warm:
        rates.ingest_day(d)

    risk = RiskEngine(quote_log=REPORTS_DIR / "backtest_quotes.jsonl")
    records = []
    # Platt recalibration fitted on trailing settled markets (walk-forward)
    from engine.calibration import PlattScaler
    CAL_WINDOW_DAYS = 45
    daily_pairs: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for day in window:
        hist = sorted(d for d in daily_pairs if d < day)[-CAL_WINDOW_DAYS:]
        scaler = PlattScaler().fit([pr for d in hist for pr in daily_pairs[d]])
        games = {int(r["gamePk"]): r
                 for r in csv.DictReader(open(CORPUS_DIR / f"games_{day}.csv"))}
        plays_by_game = defaultdict(list)
        for r in csv.DictReader(open(CORPUS_DIR / f"plays_{day}.csv")):
            plays_by_game[int(r["gamePk"])].append(r)

        for pk, g in games.items():
            plays = plays_by_game.get(pk, [])
            if not plays:
                continue
            gi = GameInfo(
                gamePk=pk, away_id=int(g["away_id"]), home_id=int(g["home_id"]),
                away_name="", home_name="", venue_name=g["venue_name"],
                away_sp_id=int(g["away_sp_id"]) if g["away_sp_id"] else None,
                home_sp_id=int(g["home_sp_id"]) if g["home_sp_id"] else None)
            hr_innings = {int(r["inning"]) for r in plays if r["event_type"] == "home_run"}
            max_inning = max(int(r["inning"]) for r in plays)

            for inning in range(1, 10):
                spec = PropSpec(sport="MLB", market_family="inning_event",
                                event="home_run", scope="either_team",
                                constraints=Constraints(inning=inning),
                                grading_source="mlb_pbp")
                pr = price_inning_hr(spec, gi, rates, fits)
                raw_p = pr.fair_prob
                cal_p = scaler.apply(raw_p)
                if inning > max_inning:
                    outcome = None  # void — inning never played
                else:
                    outcome = 1 if inning in hr_innings else 0
                tier = risk.classify_tier(spec, pr)
                book_prob = min(cal_p * TIERS[tier]["margin"], MAX_IMPLIED)
                records.append({"day": day, "gamePk": pk, "inning": inning,
                                "fair_prob": cal_p, "raw_prob": raw_p,
                                "book_prob": book_prob,
                                "tier": tier, "outcome": outcome})
                if outcome is not None:
                    # calibration always learns from RAW predictions
                    daily_pairs[day].append((raw_p, outcome))
        rates.ingest_day(day)  # only after pricing: walk-forward

    return summarize(records, start, end)


def summarize(records: list[dict], start: str, end: str) -> dict:
    settled = [r for r in records if r["outcome"] is not None]
    n = len(settled)
    brier = sum((r["fair_prob"] - r["outcome"]) ** 2 for r in settled) / n
    base_rate = sum(r["outcome"] for r in settled) / n
    brier_ref = base_rate * (1 - base_rate)  # climatology Brier

    # calibration buckets
    buckets = defaultdict(lambda: [0, 0, 0.0])
    for r in settled:
        b = min(int(r["fair_prob"] * 20), 19)  # 5% buckets
        buckets[b][0] += 1
        buckets[b][1] += r["outcome"]
        buckets[b][2] += r["fair_prob"]
    calibration = []
    for b in sorted(buckets):
        cnt, wins, psum = buckets[b]
        calibration.append({"bucket": f"{b*5}-{b*5+5}%", "n": cnt,
                            "predicted": round(psum / cnt, 4),
                            "realized": round(wins / cnt, 4)})

    # book P&L: bettor stakes $10 on YES at our posted odds
    pnl = 0.0
    stake = 10.0
    for r in settled:
        dec = 1.0 / r["book_prob"]
        pnl += stake if r["outcome"] == 0 else -stake * (dec - 1.0)
    handle = stake * n
    voids = len(records) - n

    report = {
        "window": f"{start}..{end}",
        "markets_priced": len(records),
        "settled": n, "voided": voids,
        "base_rate": round(base_rate, 4),
        "brier_score": round(brier, 5),
        "brier_climatology": round(brier_ref, 5),
        "brier_skill_score": round(1 - brier / brier_ref, 4),
        "book_pnl_usd": round(pnl, 2),
        "handle_usd": round(handle, 2),
        "hold_pct": round(100 * pnl / handle, 2),
        "calibration": calibration,
    }
    return report


def main():
    start, end = sys.argv[1], sys.argv[2]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = run(start, end)
    out = REPORTS_DIR / f"calibration_{start}_{end}.json"
    out.write_text(json.dumps(report, indent=1))

    lines = [f"# Backtest calibration report {report['window']}", "",
             f"- markets priced: {report['markets_priced']} "
             f"(settled {report['settled']}, void {report['voided']})",
             f"- base rate (HR in a given inning): {report['base_rate']:.3f}",
             f"- Brier score: {report['brier_score']:.5f} "
             f"(climatology {report['brier_climatology']:.5f}, "
             f"skill {report['brier_skill_score']:+.3f})",
             f"- book P&L at $10 flat: ${report['book_pnl_usd']:.2f} on "
             f"${report['handle_usd']:.0f} handle = {report['hold_pct']:.2f}% hold", "",
             "| bucket | n | predicted | realized |", "|---|---|---|---|"]
    for c in report["calibration"]:
        lines.append(f"| {c['bucket']} | {c['n']} | {c['predicted']:.3f} | {c['realized']:.3f} |")
    (REPORTS_DIR / f"calibration_{start}_{end}.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "calibration"}, indent=1))
    for c in report["calibration"]:
        print(f"  {c['bucket']:>8}  n={c['n']:<6} pred={c['predicted']:.3f}  real={c['realized']:.3f}")


if __name__ == "__main__":
    main()

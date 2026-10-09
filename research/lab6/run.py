"""Lab 6 stages (research/lab6/PLAN.md): INVENTORY (what can be matched), TRAIN (the H1 grid, a shortlist of at
most two cells, the H2 diagnostic), VAL (the shortlist, placebo, selection), TEST (one look at the selected cell,
refused without ``LAB6_ALLOW_TEST=1``). Writes ``research/lab6/<HYP>/<stage>.json`` and ``.md``, ``INVENTORY.md``
and ``RESULTS.md``.

CLI::

    python research/lab6/run.py --inventory
    python research/lab6/run.py --stage train
    python research/lab6/run.py --stage val
    LAB6_ALLOW_TEST=1 python research/lab6/run.py --stage test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import core as C
import pandas as pd

import data as D

HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
PLAN_VERSION = "lab6-v1"
PLACEBO_PCT = 95.0
H1_TITLE = "buy the Polymarket side priced below Pinnacle's no-vig fair by more than a margin"
H2_TITLE = "closing-line value: does the entry price beat Pinnacle's last pre-game line (diagnostic)"


def check_split_allowed(split: str) -> None:
    if split == "test" and os.environ.get("LAB6_ALLOW_TEST") != "1":
        raise PermissionError("TEST is a one-look split: set LAB6_ALLOW_TEST=1 to read it (PLAN §4)")


def prereg_sha256() -> str:
    return hashlib.sha256(PLAN.read_bytes()).hexdigest() if PLAN.exists() else "-"


def cell_key(method: str, window_h: float, margin: float) -> str:
    return f"{method}|W{window_h:g}h|m{margin:g}"


# --- loading ---------------------------------------------------------------------------------------------------------


def load_matched(data_dir: Path = D.DATA, lab4: Path = D.LAB4_DATA) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(matched games with Polymarket and Pinnacle fields, their sides, the Pinnacle table)."""
    games, sides = C.build_games(pd.read_parquet(lab4 / "markets.parquet"),
                                 pd.read_parquet(data_dir / "gamma_meta.parquet"))
    act = D.active_games(games, pd.read_parquet(data_dir / "pregame.parquet"))
    matches = pd.read_parquet(data_dir / "matches.parquet")
    g = act.drop(columns=["sport_keys"]).merge(matches, on="game_id")
    g["sport_keys"] = [json.dumps([k]) for k in g["sport_key"]]
    pin = pd.read_parquet(data_dir / "pinnacle.parquet")
    return g, sides[sides["game_id"].isin(g["game_id"])], pin


def universe(split: str, data_dir: Path = D.DATA, lab4: Path = D.LAB4_DATA) -> C.Universe:
    check_split_allowed(split)
    g, sides, pin = load_matched(data_dir, lab4)
    g = g[g["split"] == split].reset_index(drop=True)
    sides = sides[sides["game_id"].isin(g["game_id"])].reset_index(drop=True)
    lines = C.event_lines(pin[pin["event_id"].isin(g["event_id"])])
    tapes = {}
    for mid in sides["market_id"].astype(str).unique():
        t = D.load_tape(mid, lab4)
        if t is not None:
            tapes[mid] = t
    return C.Universe(split, g, sides, lines, tapes)


# --- inventory (PLAN §1) -------------------------------------------------------------------------------------------


def inventory(data_dir: Path = D.DATA, lab4: Path = D.LAB4_DATA, here: Path = HERE,
              ledger: Path = D.LEDGER) -> dict[str, Any]:
    markets = pd.read_parquet(lab4 / "markets.parquet")
    sports = markets[markets["fee_type"].fillna("").str.startswith("sports")]
    games, sides = C.build_games(markets, pd.read_parquet(data_dir / "gamma_meta.parquet"))
    pre = pd.read_parquet(data_dir / "pregame.parquet")
    covered = games[games["sport_keys"] != "[]"].merge(pre, on="game_id", how="left")
    act = D.active_games(games, pre)
    matches = pd.read_parquet(data_dir / "matches.parquet")
    fails = pd.read_parquet(data_dir / "match_failures.parquet")
    pin = pd.read_parquet(data_dir / "pinnacle.parquet")
    matched = act.merge(matches, on="game_id")
    by_league = (
        games.assign(covered=games["sport_keys"] != "[]")
        .groupby("league")
        .agg(games=("game_id", "size"), covered=("covered", "sum"), clean=("clean", "sum"))
        .join(act.groupby("league").size().rename("active"))
        .join(matched.groupby("league").size().rename("matched"))
        .fillna(0)
        .astype(int)
        .sort_values("games", ascending=False)
    )
    doc = {
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "lab4_sports_markets": len(sports),
        "lab4_sports_events": int(sports["event_slug"].nunique()),
        "game_moneyline_markets": int(sides["market_id"].nunique()),
        "games": len(games),
        "games_2way": int((games["kind"] == "2way").sum()),
        "games_3way": int((games["kind"] == "3way").sum()),
        "games_clean": int(games["clean"].sum()),
        "covered_games": len(covered),
        "covered_with_prints_24h": int((covered["prints_24h"] > 0).sum()),
        "active_games": len(act),
        "matched_games": len(matched),
        "match_rate": len(matched) / len(act) if len(act) else None,
        "matched_by_split": matched["split"].value_counts(dropna=False).to_dict(),
        "matched_clean": int(matched["clean"].sum()),
        "matched_dt_start_abs_median_min": float(matched["dt_start_s"].abs().median() / 60.0) if len(matched) else None,
        "failures_by_reason": fails["reason"].value_counts().to_dict(),
        "pinnacle_rows": len(pin),
        "pinnacle_events": int(pin["event_id"].nunique()),
        "pinnacle_snapshots": int(pin[["sport_key", "snap_ts"]].drop_duplicates().shape[0]),
        "credits": D.Ledger(ledger).status(),
        "first_close": datetime.fromtimestamp(float(games["closed_time"].min()), UTC).date().isoformat(),
        "last_close": datetime.fromtimestamp(float(games["closed_time"].max()), UTC).date().isoformat(),
    }
    doc["verdict_data"] = "OK" if len(matched) >= 500 else "NO_DATA"
    lines = [
        "# Lab 6 inventory: Polymarket sports game moneylines and their Pinnacle match",
        "",
        f"Written by `run.py --inventory` {doc['utc']}. Source: lab 4's cache (markets closed {doc['first_close']} "
        f"-> {doc['last_close']}, volume >= $20k, tapes = the last 14 days before resolution).",
        "",
        f"- lab 4 sports markets: {doc['lab4_sports_markets']:,} in {doc['lab4_sports_events']:,} events",
        f"- game moneyline markets (2-way `A vs. B`, or soccer `Will X win on <date>?` / `... end in a draw?`): "
        f"{doc['game_moneyline_markets']:,} in {doc['games']:,} games ({doc['games_2way']:,} 2-way, "
        f"{doc['games_3way']:,} soccer 3-way); every market resolved cleanly (one winner) in {doc['games_clean']:,} games "
        f"(the rest have a 50/50 split resolution, settled at 0.5)",
        f"- in a league The Odds API covers with Pinnacle (PLAN §1 table): {doc['covered_games']:,} games; with at least "
        f"one print in the 24 h before the scheduled start: {doc['covered_with_prints_24h']:,}",
        f"- active (scheduled start known, a tape for every market, prints before the start): {doc['active_games']:,}",
        f"- **matched to a Pinnacle event: {doc['matched_games']:,} ({100 * (doc['match_rate'] or 0):.1f} %)**; by "
        f"split {doc['matched_by_split']}; median |Pinnacle commence - Polymarket gameStartTime| "
        f"{doc['matched_dt_start_abs_median_min']:.1f} min",
        f"- Pinnacle table: {doc['pinnacle_rows']:,} rows, {doc['pinnacle_events']:,} events, "
        f"{doc['pinnacle_snapshots']:,} (sport, snapshot) pairs",
        f"- data verdict: **{doc['verdict_data']}** (the bar: at least 500 matched games with prints)",
        "",
        "Failures (active games not matched), by reason:",
        "",
    ]
    for reason, n in doc["failures_by_reason"].items():
        lines.append(f"- {reason}: {n}")
    lines += ["", "Examples of failures:", "", "| game | league | reason | Polymarket teams | best Pinnacle candidate |",
              "|---|---|---|---|---|"]
    ex = fails[fails["game_id"].isin(act["game_id"])].groupby("reason", group_keys=False).head(6)
    for f in ex.itertuples(index=False):
        cand = f"{f.best_home} vs {f.best_away} (sim {f.sim})" if isinstance(f.best_home, str) else "-"
        teams = f"{f.team_a} / {f.team_b}" if isinstance(f.team_a, str) else "-"
        lines.append(f"| {f.game_id} | {f.league} | {f.reason} | {teams} | {cand} |")
    lines += ["", "By league (games = game moneylines in lab 4's cache):", "",
              "| league | games | covered | clean | active | matched |", "|---|---|---|---|---|---|"]
    for lg, r in by_league.iterrows():
        if r["games"] >= 5 or r["matched"] > 0:
            lines.append(f"| {lg} | {r['games']} | {r['covered']} | {r['clean']} | {r['active']} | {r['matched']} |")
    lines.append("")
    (here / "INVENTORY.md").write_text("\n".join(lines))
    (data_dir / "inventory.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    return doc


# --- stages ----------------------------------------------------------------------------------------------------------


def evaluate(u: C.Universe, cells: list[tuple[str, float, float]], B: int, placebo: bool = False,
             robustness: bool = False) -> list[dict[str, Any]]:
    cands = {m: C.all_candidates(u, m, max(C.WINDOWS_H) * 3600.0) for m in sorted({c[0] for c in cells})}
    out = []
    for method, window_h, margin in cells:
        bets = C.cell_bets(cands[method], u.games, window_h, margin)
        cell: dict[str, Any] = {
            "key": cell_key(method, window_h, margin),
            "method": method,
            "window_h": window_h,
            "margin": margin,
            "selectable": method in C.SELECTABLE_METHODS,
            "summary": C.summarize(bets, u.split, B=B),
        }
        if placebo:
            cell["placebo"] = C.calibration_placebo(bets, draws=B)
        if robustness:
            lat = C.latency_exec(bets, u)
            cell["latency"] = C.summarize(lat[~lat["missed"].astype(bool)].reset_index(drop=True), u.split, B=B) \
                if len(lat) else None
            if lat is not None and len(lat):
                cell["latency"]["missed"] = int(lat["missed"].astype(bool).sum())
        out.append(cell)
    return out


def coverage(u: C.Universe) -> dict[str, Any]:
    """Share of the split's matched games with at least one candidate print (a usable snapshot and a big
    enough buyable print) in each entry window, before any margin."""
    c = C.all_candidates(u, "mult", max(C.WINDOWS_H) * 3600.0)
    out = {"games": len(u.games)}
    if c.empty:
        return {**out, **{f"W{w:g}h": 0 for w in C.WINDOWS_H}}
    c = c.join(u.games.set_index("game_id")["commence"], on="game_id")
    for w in C.WINDOWS_H:
        out[f"W{w:g}h"] = int(c[c["t"] >= c["commence"] - w * 3600.0]["game_id"].nunique())
    return out


def decide_train(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ok = [c for c in cells if c["selectable"] and C.qualifies(c["summary"])]
    ok.sort(key=lambda c: c["summary"]["mean_net"], reverse=True)
    return [{"key": c["key"], "method": c["method"], "window_h": c["window_h"], "margin": c["margin"],
             "train_mean_net": c["summary"]["mean_net"]} for c in ok[: C.SHORTLIST]]


def decide_holdout(cell: dict[str, Any]) -> bool:
    p = cell.get("placebo") or {}
    beats = p.get("real_percentile") is not None and p["real_percentile"] >= PLACEBO_PCT
    return bool(C.qualifies(cell["summary"]) and beats)


def _fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _h1_md(stage: str, doc: dict[str, Any]) -> str:
    lines = [
        f"# H1 {H1_TITLE}: {stage.upper()} ({doc['split']}, {PLAN_VERSION})",
        "",
        f"Run {doc['utc']}; PLAN.md sha256 {doc['prereg_sha256'][:12]}; matched games in split {doc['n_games']}; "
        f"trials so far across labs 2-6: {doc['n_trials_total']}.",
        "",
    ]
    cov = doc.get("coverage")
    if cov:
        lines += [f"Coverage (games with at least one usable print, before any margin): "
                  f"{', '.join(f'{k} {v}' for k, v in cov.items() if k != 'games')} of {cov['games']} games.", ""]
    lines += [
        "| cell | n | /day | win rate | mean price | mean fair | mean edge | model net | mean net | CI95 (events) | "
        "$/ticket | total $ | CLV (pts) | CLV CI95 | beat close | daily Sharpe | DD $ |",
        "|" + "---|" * 17,
    ]
    for c in doc["cells"]:
        s = c["summary"]
        tag = "" if c["selectable"] else " (alternative method, reported only)"
        clv = s.get("clv") or {}
        lines.append(
            f"| {c['key']}{tag} | {s['n']} | {_fmt(s['trades_per_day'], 2)} | {_fmt(s['win_rate'])} | "
            f"{_fmt(s['mean_p_exec'])} | {_fmt(s.get('mean_fair'))} | {_fmt(s.get('mean_edge'))} | "
            f"{_fmt(s.get('model_net'), 4)} | {_fmt(s['mean_net'], 4)} | [{_fmt(s['ci95'][0], 4)}, {_fmt(s['ci95'][1], 4)}] | "
            f"{_fmt(s['mean_pnl_usd'], 2)} | {_fmt(s['daily']['total_usd'], 0)} | {_fmt(clv.get('mean'), 4)} | "
            f"[{_fmt((clv.get('ci95') or [None, None])[0], 4)}, {_fmt((clv.get('ci95') or [None, None])[1], 4)}] | "
            f"{_fmt(clv.get('beat_share'))} | {_fmt(s['daily']['sharpe'], 2)} | {_fmt(s['daily']['max_drawdown_usd'], 0)} |"
        )
        if c.get("placebo"):
            p = c["placebo"]
            lines.append(f"|  placebo (calibrated at the price paid) | | | | | | | | mean {_fmt(p['mean'], 4)}, "
                         f"p95 {_fmt(p['p95'], 4)}; real at percentile {_fmt(p['real_percentile'], 1)} | | | | | | | | |")
        if c.get("latency"):
            lt = c["latency"]
            lines.append(f"|  robustness: lab 4 fill (next buyable print >= 10 s later, no tick) | {lt['n']} "
                         f"(missed {lt.get('missed', '-')}) | | {_fmt(lt['win_rate'])} | {_fmt(lt['mean_p_exec'])} | | | | "
                         f"{_fmt(lt['mean_net'], 4)} | [{_fmt(lt['ci95'][0], 4)}, {_fmt(lt['ci95'][1], 4)}] | | | | | | | |")
    lines += ["", f"**Decision:** {doc['decision']}", ""]
    if doc.get("shortlist"):
        lines.append("Shortlist: " + ", ".join(f"`{s['key']}`" for s in doc["shortlist"]) + ".")
    if doc.get("selected"):
        lines.append(f"Selected cell: `{doc['selected']['key']}`.")
    best = [c for c in doc["cells"] if c["selectable"] and c["summary"]["n"]]
    if best:
        lines += ["", "By league, the selectable cell with the most bets:", "",
                  "| league | n | win rate | mean price | mean net | total $ |", "|---|---|---|---|---|---|"]
        top = max(best, key=lambda c: c["summary"]["n"])
        for lg, r in sorted(top["summary"]["by_league"].items(), key=lambda kv: -kv[1]["n"]):
            lines.append(f"| {lg} | {r['n']} | {_fmt(r['win_rate'])} | {_fmt(r['mean_p_exec'])} | "
                         f"{_fmt(r['mean_net'], 4)} | {_fmt(r['total_usd'], 0)} |")
    lines += [
        "",
        "Readings per PLAN §5. One bet per game (the earliest print whose price + one tick + the taker fee is below the "
        "fair by more than the margin), $20 tickets, settled at the market's final price; 'mean edge' = fair - price - "
        "fee per share at entry; 'model net' = what the bets would earn if Pinnacle's fair were exactly right; 'mean "
        "net' = realised profit per $1 at risk; CI by event bootstrap; CLV = Pinnacle's closing fair - price paid "
        "(probability points). Nothing here is a live trade.",
    ]
    return "\n".join(lines) + "\n"


def _h2_md(stage: str, doc: dict[str, Any]) -> str:
    lines = [
        f"# H2 {H2_TITLE}: {stage.upper()} ({doc['split']}, {PLAN_VERSION})",
        "",
        f"Run {doc['utc']}. No-skill baseline (PLAN §3, H2): every side of every matched game bought at the first "
        "buyable print (big enough for the ticket) once the window opens, at print + one tick; CLV = Pinnacle's closing "
        "no-vig fair (multiplicative) - price paid. The strategy's own CLV is in H1's table.",
        "",
        "| window | sides | games | mean CLV (pts) | CLV CI95 | beat close | mean abs gap | mean net | net CI95 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for w, r in doc["baseline"].items():
        if not r.get("n"):
            lines.append(f"| {w} | 0 | | | | | | | |")
            continue
        lines.append(f"| {w} | {r['n']} | {r['games']} | {_fmt(r['mean_clv'], 4)} | [{_fmt(r['clv_ci95'][0], 4)}, "
                     f"{_fmt(r['clv_ci95'][1], 4)}] | {_fmt(r['beat_share'])} | {_fmt(r['mean_abs_gap'], 4)} | "
                     f"{_fmt(r['mean_net'], 4)} | [{_fmt(r['net_ci95'][0], 4)}, {_fmt(r['net_ci95'][1], 4)}] |")
    lines += ["", "Diagnostic only: H2 selects nothing and decides nothing.", ""]
    return "\n".join(lines)


def _write(hyp: str, stage: str, doc: dict[str, Any], md: str, here: Path) -> None:
    d = here / hyp
    d.mkdir(exist_ok=True)
    (d / f"{stage}.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    (d / f"{stage}.md").write_text(md)


def run_stage(stage: str, B: int = C.L4.BOOTSTRAP_B, here: Path = HERE, data_dir: Path = D.DATA,
              lab4: Path = D.LAB4_DATA, ledger: Path | None = None) -> dict[str, Any]:
    split = stage
    check_split_allowed(split)
    u = universe(split, data_dir, lab4)
    base = {"split": split, "utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "prereg_sha256": prereg_sha256(), "n_games": len(u.games),
            "leagues": u.games["league"].value_counts().to_dict()}
    if stage == "train":
        grid = [(m, w, mg) for m in C.METHODS for w in C.WINDOWS_H for mg in C.MARGINS]
        cells = evaluate(u, grid, B)
        shortlist = decide_train(cells)
        if shortlist:
            rob = evaluate(u, [(s["method"], s["window_h"], s["margin"]) for s in shortlist], B, robustness=True)
            by_key = {c["key"]: c for c in rob}
            for c in cells:
                if c["key"] in by_key:
                    c["latency"] = by_key[c["key"]].get("latency")
        decision = (f"SHORTLIST {', '.join(s['key'] for s in shortlist)} for VAL" if shortlist
                    else "NO EDGE on TRAIN (no selectable cell qualifies)")
        doc = {**base, "stage": stage, "cells": cells, "shortlist": shortlist, "selected": None,
               "decision": decision, "coverage": coverage(u)}
    else:
        prev = json.loads((here / "H1" / ("train.json" if stage == "val" else "val.json")).read_text())
        todo = prev.get("shortlist") if stage == "val" else ([prev["selected"]] if prev.get("selected") else [])
        if not todo:
            doc = {**base, "stage": stage, "cells": [], "shortlist": [], "selected": None,
                   "decision": f"NOT RUN: {'TRAIN shortlisted' if stage == 'val' else 'VAL selected'} no cell"}
            cells = []
        else:
            cells = evaluate(u, [(s["method"], s["window_h"], s["margin"]) for s in todo], B, placebo=True,
                             robustness=True)
            passed = [(c, s) for c, s in zip(cells, todo, strict=True) if decide_holdout(c)]
            if stage == "val":
                # PLAN §4: among shortlisted cells that pass VAL, the higher TRAIN mean wins (VAL ranks nothing)
                passed.sort(key=lambda cs: cs[1]["train_mean_net"], reverse=True)
                sel = passed[0][1] if passed else None
                decision = f"SELECTED {sel['key']} for TEST" if sel else "FAIL on VAL (no shortlisted cell passes)"
            else:
                sel = todo[0] if passed else None
                decision = f"PASS on TEST ({todo[0]['key']})" if passed else f"FAIL on TEST ({todo[0]['key']})"
            doc = {**base, "stage": stage, "cells": cells, "shortlist": todo, "selected": sel, "decision": decision}
    n_total = C.trials_count()
    for c in cells:
        n_total = C.record_run({"lab": "lab6", "hyp": "H1", "cell": c["key"], "split": split, "stage": stage,
                                "n": c["summary"]["n"], "mean_net": c["summary"]["mean_net"], "kind": "cell"},
                               ledger)
    doc["n_trials_total"] = n_total
    _write("H1", stage, doc, _h1_md(stage, doc), here)
    h2 = {**base, "stage": stage,
          "baseline": {f"W{w:g}h": C.baseline_reading(C.clv_baseline(u, "mult", w), B) for w in C.WINDOWS_H}}
    _write("H2", stage, h2, _h2_md(stage, h2), here)
    results_md(here)
    print(f"H1 {stage}: {doc['decision']}", flush=True)
    return {"H1": doc, "H2": h2}


def results_md(here: Path = HERE) -> None:
    rows = ["# Lab 6 results (the sports specialist: Polymarket moneylines vs Pinnacle's no-vig line)", "",
            "| hyp | title | TRAIN | VAL | TEST |", "|---|---|---|---|---|"]
    for hyp, title in (("H1", H1_TITLE), ("H2", H2_TITLE)):
        cells = []
        for stage in ("train", "val", "test"):
            p = here / hyp / f"{stage}.json"
            if not p.exists():
                cells.append("-")
                continue
            d = json.loads(p.read_text())
            if hyp == "H1":
                cells.append(d["decision"])
            else:
                b = d["baseline"].get("W1h") or {}
                cells.append(f"diagnostic: W1h mean CLV {_fmt(b.get('mean_clv'), 4)} over {b.get('n', 0)} sides"
                             if b.get("n") else "diagnostic: no sides")
        rows.append(f"| {hyp} | {title} | {cells[0]} | {cells[1]} | {cells[2]} |")
    inv = here / "data" / "inventory.json"
    if inv.exists():
        d = json.loads(inv.read_text())
        rows += ["", f"Data: {d['matched_games']:,} matched games ({d['verdict_data']}); credits used "
                     f"{(d.get('credits') or {}).get('spent')} of {(d.get('credits') or {}).get('cap')}."]
    rows += ["", "Decisions per research/lab6/PLAN.md; tables in H1/ and H2/; inventory in INVENTORY.md. Paper only.",
             ""]
    (here / "RESULTS.md").write_text("\n".join(rows))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lab 6 stages")
    ap.add_argument("--stage", choices=["train", "val", "test"], default=None)
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--B", type=int, default=C.L4.BOOTSTRAP_B)
    a = ap.parse_args(argv)
    if a.inventory:
        doc = inventory()
        print(json.dumps({k: doc[k] for k in ("matched_games", "match_rate", "matched_by_split", "verdict_data")},
                         default=str))
        results_md()
    if a.stage:
        run_stage(a.stage, B=a.B)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Lab 7 W1: sports pre-game convergence to Pinnacle (research/lab7/PLAN.md §5 W1; implementation details in
research/lab7/W1/PREREG.md, written before any return was computed).

The specialist buys a Polymarket game-winner side whose buyable print sits at least ``m`` below Pinnacle's no-vig
fair (lab 6's multiplicative fair from the last snapshot at or before the print, at most 30 minutes old, strictly
before the start), then trades OUT before the game: a take profit at ``entry + tp`` capped by the fair, an optional
stop at ``entry - sl``, and a time stop at the cutoff (the earlier of Pinnacle's commence and Polymarket's
gameStartTime), selling at the last sellable print before it. Everything about execution, fees, readings, the bar,
the placebo and the ledger is research/lab7/core.py, unchanged.

CLI (from the repo root)::

    python research/lab7/W1/run.py --structure            # universe counts only, no return
    python research/lab7/W1/run.py --stage train
    python research/lab7/W1/run.py --stage val            # only if TRAIN selected a cell
    LAB7_ALLOW_TEST=1 python research/lab7/W1/run.py --stage test   # once, only if VAL passed

Research only, paper only. No network, no key: lab 6's Pinnacle table is read from research/lab6/data/.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import multiprocessing as mp
import os
import sys
import time
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB7 = HERE.parent
sys.path.insert(0, str(LAB7))
import core as C  # noqa: E402  (research/lab7/core.py)


def _load(name: str, path: Path) -> Any:
    """Lab 6's engine under its own module name: lab 6's data.py / run.py do ``import core``, which would collide
    with lab 7's ``core``, so they are not imported; the two small loaders they hold are mirrored below."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L6 = _load("lab6_core", LAB7.parent / "lab6" / "core.py")
LAB6_DATA = Path(os.environ.get("LAB6_DATA", str(LAB7.parent / "lab6" / "data")))
PREREG = HERE / "PREREG.md"
OUT_DIR = C.OUT / "W1"

HYP = "W1"
TITLE = "sports pre-game convergence to Pinnacle (buy below the no-vig fair, trade out before the start)"
MARGINS = (0.02, 0.03, 0.05)
TPS = (0.02, 0.03, 0.05)
SLS: tuple[float | None, ...] = (0.03, 0.05, None)
TP_MODES = ("taker", "maker")
BAND = (0.15, 0.85)
LOOKBACK_S = 24 * 3600.0  # entry windows start at commence - 24 h
STALENESS_S = float(L6.STALENESS_S)  # 30 min (lab 6)
METHOD = "mult"  # lab 6's declared no-vig method
WORKERS = int(os.environ.get("LAB7_WORKERS", "4"))


# --------------------------------------------------------------------------------------------- cells


@dataclass(frozen=True)
class Cell:
    key: str
    m: float
    exits: C.Exits
    selectable: bool


def _g(v: float | None) -> str:
    return "none" if v is None else f"{v:g}"


def cell_key(m: float, tp: float, sl: float | None, mode: str) -> str:
    return f"m{m:g}|tp{tp:g}|sl{_g(sl)}|tcutoff|{mode}"


def ref_key(m: float) -> str:
    return f"hold|m{m:g}"


def grid() -> list[Cell]:
    """PLAN §5 W1: 54 selectable cells (m x tp x sl x variant, fair cap on, time stop at the cutoff) and 3
    reference cells (the first entry per market held to settlement)."""
    cells = [
        Cell(cell_key(m, tp, sl, mode), m, C.Exits(tp=tp, sl=sl, tp_mode=mode, fair_exit=True), True)
        for m in MARGINS for tp in TPS for sl in SLS for mode in TP_MODES
    ]
    cells += [Cell(ref_key(m), m, C.Exits(hold_to_settlement=True), False) for m in MARGINS]
    return cells


# --------------------------------------------------------------------------------------------- universe


def load_matched(lab6_data: Path = LAB6_DATA, lab4: Path = C.LAB4_DATA) -> tuple[pd.DataFrame, pd.DataFrame,
                                                                                  pd.DataFrame, pd.DataFrame]:
    """Lab 6's matched games (research/lab6/run.py ``load_matched`` with lab 6 data.py's ``active_games``, mirrored
    line for line): (games, their sides, the Pinnacle table, lab 4's markets table)."""
    markets = pd.read_parquet(lab4 / "markets.parquet")
    games, sides = L6.build_games(markets, pd.read_parquet(lab6_data / "gamma_meta.parquet"))
    pre = pd.read_parquet(lab6_data / "pregame.parquet")
    g = games[games["sport_keys"] != "[]"].merge(pre, on="game_id", how="left")
    keep = g["game_start"].notna() & (g["tapes"] == g["markets"]) & (g["prints_24h"] > 0)
    act = g[keep].reset_index(drop=True)
    matches = pd.read_parquet(lab6_data / "matches.parquet")
    g = act.drop(columns=["sport_keys"]).merge(matches, on="game_id")
    pin = pd.read_parquet(lab6_data / "pinnacle.parquet")
    return g, sides[sides["game_id"].isin(g["game_id"])], pin, markets


def merge_windows(snap_ts: np.ndarray, commence: float, cutoff: float, lookback_s: float = LOOKBACK_S,
                  staleness_s: float = STALENESS_S) -> tuple[tuple[float, float], ...]:
    """PLAN §5 W1 entry windows: the union over snapshots (strictly before commence) of ``[snap, snap + 30 min)``,
    inside ``[commence - 24 h, cutoff)``, merged into disjoint intervals (the placebo draws uniformly over them, so
    an overlap must not count twice)."""
    lo = commence - lookback_s
    iv = sorted((max(float(s), lo), min(float(s) + staleness_s, cutoff)) for s in snap_ts if float(s) < commence)
    out: list[list[float]] = []
    for a, b in iv:
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return tuple((a, b) for a, b in out)


def fair_matrix(ts: np.ndarray, snap_ts: np.ndarray, fair_snap: np.ndarray, commence: float,
                cutoff: float) -> np.ndarray:
    """``fair[o, i]``: outcome o's no-vig fair from the last snapshot at or BEFORE print i, strictly before commence
    and at most 30 min old (lab 6 ``snapshot_index``); NaN otherwise and at or after the cutoff (no position is
    watched past the cutoff, so that NaN changes no trade)."""
    out = np.full((2, len(ts)), np.nan)
    if len(ts) == 0 or len(snap_ts) == 0:
        return out
    j = L6.snapshot_index(snap_ts, ts, commence, STALENESS_S)
    ok = (j >= 0) & (ts < cutoff)
    out[:, ok] = fair_snap[:, j[ok]]
    return out


def market_fair_snap(line: Any, sides: pd.DataFrame, a_is_home: bool) -> np.ndarray:
    """(2, n_snapshots): each outcome's fair per Pinnacle snapshot, by lab 6's ``side_fair``. A 2-way market's
    outcome 0 is Polymarket's team A (``team_is_a``), mapped to Pinnacle's home or away by ``a_is_home``; a soccer
    market's outcome 0 is Yes (its result's probability) and outcome 1 is No (one minus it)."""
    fs = []
    for r in sides.sort_values("o").itertuples(index=False):
        team_is_a = (int(r.o) == 0) if r.result == "team" else None
        fs.append(L6.side_fair(line, METHOD, r.result, bool(r.yes), a_is_home, team_is_a))
    return np.vstack(fs).astype(float)


@dataclass
class Spec:
    """Everything about one Polymarket market except its tape (workers load the tape)."""

    id: str
    game_id: str
    league: str
    kind: str
    split: str
    question: str
    rate_com: float
    payout: tuple[float, float]
    closed_time: float
    commence: float
    cutoff: float
    windows: tuple[tuple[float, float], ...]
    snap_ts: np.ndarray
    fair_snap: np.ndarray  # (2, n_snapshots)
    close_fair: tuple[float, float]


def build_specs(split: str, lab6_data: Path = LAB6_DATA, lab4: Path = C.LAB4_DATA) -> tuple[list[Spec], dict]:
    """The split's W1 markets (lab 6's split of the GAME). Returns (specs, structure counts)."""
    C.check_split_allowed(split)
    g, sides, pin, markets = load_matched(lab6_data, lab4)
    g = g[g["split"] == split].reset_index(drop=True)
    sides = sides[sides["game_id"].isin(g["game_id"])]
    lines = L6.event_lines(pin[pin["event_id"].isin(g["event_id"])])
    closed = dict(zip(markets["id"].astype(str), markets["closed_time"].astype(float), strict=True))
    sides_by_market = {mid: s.sort_values("o") for mid, s in sides.groupby("market_id")}
    specs: list[Spec] = []
    counts = {"games": len(g), "games_without_line": 0, "markets": 0, "markets_bad_sides": 0,
              "markets_without_windows": 0}
    for game in g.itertuples(index=False):
        line = lines.get(str(game.event_id))
        if line is None:
            counts["games_without_line"] += 1
            continue
        commence = float(game.commence)
        cutoff = min(commence, float(game.game_start)) if not math.isnan(game.game_start) else commence
        windows = merge_windows(line.snap_ts, commence, cutoff)
        ci = L6.closing_index(line.snap_ts, cutoff)
        for mid in sorted(sides[sides["game_id"] == game.game_id]["market_id"].astype(str).unique()):
            s = sides_by_market[mid]
            if list(s["o"]) != [0, 1]:
                counts["markets_bad_sides"] += 1
                continue
            counts["markets"] += 1
            if not windows:
                counts["markets_without_windows"] += 1
            fair_snap = market_fair_snap(line, s, bool(game.a_is_home))
            specs.append(Spec(
                id=mid, game_id=str(game.game_id), league=str(game.league), kind=str(game.kind), split=split,
                question=str(game.question), rate_com=float(s["rate"].iloc[0]),
                payout=(float(s["final"].iloc[0]), float(s["final"].iloc[1])), closed_time=closed[mid],
                commence=commence, cutoff=cutoff, windows=windows, snap_ts=line.snap_ts, fair_snap=fair_snap,
                close_fair=(float(fair_snap[0, ci]), float(fair_snap[1, ci])) if ci >= 0 else (math.nan, math.nan),
            ))
    return specs, counts


def make_market(spec: Spec, tape: C.Tape) -> C.Market:
    """PLAN §5 W1: time stop at the cutoff in mode ``last_before``, entry deadline = the cutoff, hard end and
    settlement = the market's closedTime, payout = each outcome's final price, band 0.15-0.85."""
    return C.Market(
        id=spec.id, event=spec.game_id, split=spec.split, tape=tape, rate_com=spec.rate_com, payout=spec.payout,
        settle_t=spec.closed_time, hard_end=spec.closed_time, entry_windows=spec.windows,
        entry_deadline=spec.cutoff, end_t=spec.cutoff, end_mode="last_before",
        fair=fair_matrix(tape.ts, spec.snap_ts, spec.fair_snap, spec.commence, spec.cutoff), band=BAND,
        info={"league": spec.league, "kind": spec.kind},
    )


# --------------------------------------------------------------------------------------------- workers

_SPECS: list[Spec] = []
_CELLS: list[Cell] = []


def _trip_extras(rt: dict[str, Any], spec: Spec, mk: C.Market) -> dict[str, Any]:
    o = int(rt["o"])
    i_sig = int(np.searchsorted(mk.tape.ts, rt["t_signal"], side="left"))
    f_sig = float(mk.fair[o, i_sig]) if mk.fair is not None and i_sig < len(mk.tape) else math.nan
    return {**rt, "league": spec.league, "kind": spec.kind, "fair_signal": f_sig,
            "close_fair": spec.close_fair[o], "cutoff": spec.cutoff}


def _walk_market(k: int) -> tuple[int, dict[str, tuple[list[dict[str, Any]], int]], int]:
    spec = _SPECS[k]
    tape = C.load_tape(spec.id)
    if tape is None or len(tape) == 0:
        return k, {}, 0
    mk = make_market(spec, tape)
    sigs = {m: C.gap_signals(tape, mk.fair, m) for m in MARGINS}
    out: dict[str, tuple[list[dict[str, Any]], int]] = {}
    for cell in _CELLS:
        trips, missed = C.walk(mk, sigs[cell.m], cell.exits)
        if trips or missed:
            out[cell.key] = ([_trip_extras(t, spec, mk) for t in trips], missed)
    return k, out, len(tape)


def _placebo_market(job: tuple[int, list[tuple[str, int]]]) -> tuple[int, dict[str, np.ndarray]]:
    k, todo = job
    spec = _SPECS[k]
    tape = C.load_tape(spec.id)
    by_key = {c.key: c for c in _CELLS}
    mk = make_market(spec, tape)
    out = {}
    for key, n in todo:
        seed = [C.placebo_seed(HYP, key, spec.split), zlib.crc32(spec.id.encode())]
        out[key] = C.placebo_matrix(mk, n, by_key[key].exits, rng=np.random.default_rng(seed))
    return k, out


def _pool_map(fn, items, workers: int = WORKERS):
    if workers <= 1:
        for it in items:
            yield fn(it)
        return
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        yield from pool.imap_unordered(fn, items, chunksize=4)


# --------------------------------------------------------------------------------------------- readings


def extra_readings(f: pd.DataFrame, B: int = C.BOOTSTRAP_B) -> dict[str, Any]:
    """PREREG §5 readings beyond core.summarize: by league and kind, closing-line value of the entries, the gross
    (no-fee) mean, the gap at the signal, the entry slippage, the trips whose entry print covered our contracts,
    and how long before the cutoff the time stops sold."""
    if len(f) == 0:
        return {}
    ev = f["event"].astype(str).to_numpy()
    gross = ((f["pnl_us"] + f["fee_us"]) / C.TICKET_USD).to_numpy(dtype=float)
    clv = (f["close_fair"] - f["p_entry"]).to_numpy(dtype=float)
    has = np.isfinite(clv)
    big = (f["entry_print_size"] >= f["shares"]).to_numpy()
    tstop = f[(f["reason"] == "time") & (~f["late_stop"].astype(bool))]
    by = {}
    for col in ("league", "kind"):
        rows = {}
        for k, g in f.groupby(col):
            rows[str(k)] = {"n": len(g), "events": int(g["event"].nunique()), "win_rate": float((g["net_us"] > 0).mean()),
                            "mean_net_us": float(g["net_us"].mean()), "total_usd": float(g["pnl_us"].sum())}
        by[col] = dict(sorted(rows.items(), key=lambda kv: -kv[1]["n"]))
    return {
        "gross_mean": float(gross.mean()),
        "gross_ci95": list(C.event_bootstrap_ci(gross, ev, B=B)),
        "clv": {"n": int(has.sum()), "mean": float(clv[has].mean()) if has.any() else None,
                "ci95": list(C.event_bootstrap_ci(clv[has], ev[has], B=B)) if has.any() else [None, None],
                "beat_share": float((clv[has] > 0).mean()) if has.any() else None},
        "gap_at_signal": float((f["fair_signal"] - f["p_signal"]).mean()),
        "entry_slippage": float((f["p_entry"] - f["p_signal"]).mean()),
        "big_entry": {"n": int(big.sum()), "mean_net_us": float(f.loc[big, "net_us"].mean()) if big.any() else None},
        "time_stop_lead_min_median": float(((tstop["cutoff"] - tstop["t_exit"]) / 60.0).median()) if len(tstop) else None,
        "by_league": by["league"],
        "by_kind": by["kind"],
    }


# --------------------------------------------------------------------------------------------- stages


def evaluate(split: str, cells: list[Cell], placebo_keys: set[str] | None, B: int = C.BOOTSTRAP_B,
             workers: int = WORKERS, keep_trips: set[str] | None = None) -> tuple[list[dict[str, Any]], dict]:
    """Walk every cell over the split's markets (one tape in memory per worker), then the random-entry placebo for
    the cells in ``placebo_keys`` (None = the cells that clear PLAN §7 conditions 1-5)."""
    global _SPECS, _CELLS
    t0 = time.time()
    specs, counts = build_specs(split)
    _SPECS, _CELLS = specs, cells
    trips: dict[str, list[dict[str, Any]]] = {c.key: [] for c in cells}
    missed: dict[str, int] = {c.key: 0 for c in cells}
    per_market_n: dict[str, dict[int, int]] = {c.key: {} for c in cells}
    prints = loaded = 0
    for k, res, n_prints in _pool_map(_walk_market, range(len(specs)), workers):
        loaded += n_prints > 0
        prints += n_prints
        for key, (tr, ms) in res.items():
            trips[key].extend(tr)
            missed[key] += ms
            if tr:
                per_market_n[key][k] = len(tr)
    counts.update({"tapes_loaded": int(loaded), "prints": int(prints), "walk_s": round(time.time() - t0, 1)})
    out = []
    for c in cells:
        f = C.trips_frame(trips[c.key])
        extra_cols = pd.DataFrame(trips[c.key], columns=["league", "kind", "fair_signal", "close_fair", "cutoff"])
        f = pd.concat([f, extra_cols], axis=1) if len(f) else f.assign(
            league=[], kind=[], fair_signal=[], close_fair=[], cutoff=[])
        s = C.summarize(f, split, missed[c.key], B=B)
        out.append({"cell": c.key, "selectable": c.selectable, "m": c.m, "exits": c.exits.__dict__, "summary": s,
                    "checks": C.bar_checks(s), "extra": extra_readings(f, B), "_frame": f})
    want = {c["cell"] for c in out if all(c["checks"].values())} if placebo_keys is None else set(placebo_keys)
    t1 = time.time()
    jobs: dict[int, list[tuple[str, int]]] = {}
    for key in sorted(want):
        for k, n in per_market_n[key].items():
            jobs.setdefault(k, []).append((key, n))
    blocks: dict[str, list[np.ndarray]] = {key: [] for key in want}
    for _, res in _pool_map(_placebo_market, sorted(jobs.items()), workers):
        for key, mat in res.items():
            blocks[key].append(mat)
    for c in out:
        s = c["summary"]
        c["placebo"] = (C.placebo_reading(blocks[c["cell"]], s["mean_net_us"]) if c["cell"] in want
                        and s["mean_net_us"] is not None else None)
        c["bar"] = C.bar(s, c["placebo"])
        if keep_trips and c["cell"] in keep_trips and len(c["_frame"]):
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            safe = c["cell"].replace("|", "_")
            c["_frame"].to_parquet(OUT_DIR / f"{split}_{safe}.parquet", index=False, compression="zstd")
        del c["_frame"]
    counts["placebo_s"] = round(time.time() - t1, 1)
    counts["placebo_cells"] = len(want)
    return out, counts


def _fmt(v: Any, nd: int = 4) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _ledger_rows(cells: list[dict[str, Any]], split: str, stage: str) -> list[dict[str, Any]]:
    plan, prereg = C.prereg_sha256(C.PLAN), C.prereg_sha256(PREREG)
    return [{"hyp": HYP, "cell": c["cell"], "split": split, "stage": stage,
             "kind": "selectable" if c["selectable"] else "reference", "n": c["summary"]["n"],
             "mean_net_us": c["summary"]["mean_net_us"], "ci95": c["summary"]["ci95"],
             "mean_net_stress": c["summary"]["mean_net_stress"], "passes": bool(c["bar"]["passes"]),
             "plan_sha256": plan, "prereg_sha256": prereg} for c in cells]


def write_md(stage: str, doc: dict[str, Any]) -> str:
    cells = doc["cells"]
    lines = [f"# Lab 7 W1, {TITLE}: {stage.upper()}", ""]
    lines += [f"**Decision: {doc['decision']}**", "", doc["plain"], ""]
    lines += [
        f"Run {doc['utc']} on split `{doc['split']}`. PLAN.md sha256 `{doc['plan_sha256'][:12]}`, PREREG.md sha256 "
        f"`{doc['prereg_sha256'][:12]}`. Universe: {doc['counts']['games']} matched games, "
        f"{doc['counts']['markets']} markets, {doc['counts']['tapes_loaded']} tapes, {doc['counts']['prints']:,} prints. "
        f"Trials across labs 2-7 after this run: **{doc['n_trials_total']}**.", "",
    ]
    if doc.get("best"):
        b = doc["best"]
        s, r, x = b["summary"], b["summary"]["risk"], b["extra"]
        lines += [f"## Best selectable cell by CI95 lower bound: `{b['cell']}`", "",
                  f"- {s['n']} round trips in {s['n_events']} games, {s['missed']} missed entries, "
                  f"{_fmt(s['trips_per_day'], 2)} per day; win rate {_fmt(s['win_rate'], 3)}",
                  f"- mean net per $ (US fee) {_fmt(s['mean_net_us'])}, CI95 [{_fmt(s['ci95'][0])}, "
                  f"{_fmt(s['ci95'][1])}]; polymarket.com fee {_fmt(s['mean_net_com'])}; stress {_fmt(s['mean_net_stress'])}; "
                  f"before any fee {_fmt(x.get('gross_mean'))}",
                  f"- wins average {_fmt(s['win_cents'], 2)}c per contract, losses {_fmt(s['loss_cents'], 2)}c: break-even "
                  f"win rate {_fmt(s['breakeven_win_rate'], 3)}; mean entry price {_fmt(s['mean_p_entry'], 3)}; "
                  f"exit mix {json.dumps({k: round(v, 3) for k, v in s['exit_mix'].items()})}",
                  f"- placebo (random entry, same exits): "
                  + (f"mean {_fmt(b['placebo']['mean'])}, p95 {_fmt(b['placebo']['p95'])}, real at percentile "
                     f"{_fmt(b['placebo']['real_percentile'], 1)}, drop share {_fmt(b['placebo']['drop_share'], 3)}"
                     if b.get("placebo") else "not computed"),
                  f"- closing-line value of the entries: mean {_fmt((x.get('clv') or {}).get('mean'))} "
                  f"(CI95 [{_fmt(((x.get('clv') or {}).get('ci95') or [None, None])[0])}, "
                  f"{_fmt(((x.get('clv') or {}).get('ci95') or [None, None])[1])}], beat the close "
                  f"{_fmt((x.get('clv') or {}).get('beat_share'), 3)})",
                  f"- risk book: max {r['max_open']} positions open at once (${r['capital_usd']:.0f} locked); max drawdown "
                  f"${_fmt(r['max_drawdown_usd'], 2)}; worst day ${_fmt(r['worst_day_usd'], 2)}, best day "
                  f"${_fmt(r['best_day_usd'], 2)}; daily Sharpe {_fmt(r['sharpe_daily'], 2)}; longest losing streak "
                  f"{r['longest_losing_streak']}; worst trip ${_fmt(r['worst_trip_usd'], 2)}; $10 daily loss stop: "
                  f"{r['daily_stop']['n']} trips kept, {r['daily_stop']['skipped']} skipped on "
                  f"{r['daily_stop']['days_stopped']} days, total ${_fmt(r['daily_stop']['total_usd'], 2)}", ""]
        lines += ["By league (best cell):", "", "| league | n | games | win rate | mean net | total $ |",
                  "|---|---|---|---|---|---|"]
        for lg, v in list(x.get("by_league", {}).items())[:25]:
            lines.append(f"| {lg} | {v['n']} | {v['events']} | {_fmt(v['win_rate'], 3)} | {_fmt(v['mean_net_us'])} | "
                         f"{_fmt(v['total_usd'], 0)} |")
        lines.append("")
    lines += ["## Every cell", "",
              "Mean net is per $1 at risk ($20 tickets) under the Polymarket US fee unless named; CI95 by game "
              "bootstrap. `gross` = before any fee. Checks: n, mean, CI lower, stress, loss guards, placebo "
              "(`-` = not computed).", "",
              "| cell | n | games | missed | /day | win | mean net | CI95 | com | stress | gross | BE win | win c | "
              "loss c | entry | exits | CLV | max open | DD $ | worst day $ | Sharpe | placebo p95 | checks | pass |",
              "|" + "---|" * 24]
    for c in cells:
        s, x, r = c["summary"], c["extra"], c["summary"]["risk"]
        mix = " ".join(f"{k}:{v:.2f}" for k, v in s.get("exit_mix", {}).items())
        chk = "".join("Y" if c["bar"]["checks"][k] else ("-" if k == "placebo" and not c.get("placebo") else "n")
                      for k in ("n", "mean", "ci_lower", "stress", "loss_guards", "placebo"))
        tag = "" if c["selectable"] else " (ref)"
        lines.append(
            f"| `{c['cell']}`{tag} | {s['n']} | {s.get('n_events', 0)} | {s['missed']} | {_fmt(s['trips_per_day'], 2)} | "
            f"{_fmt(s['win_rate'], 3)} | {_fmt(s['mean_net_us'])} | [{_fmt(s['ci95'][0])}, {_fmt(s['ci95'][1])}] | "
            f"{_fmt(s['mean_net_com'])} | {_fmt(s['mean_net_stress'])} | {_fmt(x.get('gross_mean'))} | "
            f"{_fmt(s['breakeven_win_rate'], 3)} | {_fmt(s['win_cents'], 2)} | {_fmt(s['loss_cents'], 2)} | "
            f"{_fmt(s['mean_p_entry'], 3)} | {mix} | {_fmt((x.get('clv') or {}).get('mean'))} | {r['max_open']} | "
            f"{_fmt(r['max_drawdown_usd'], 0)} | {_fmt(r['worst_day_usd'], 0)} | {_fmt(r['sharpe_daily'], 2)} | "
            f"{_fmt((c.get('placebo') or {}).get('p95'))} | {chk} | {'PASS' if c['bar']['passes'] else 'no'} |")
    lines += ["", "Columns: `BE win` = the win rate the cell's own average win and loss sizes need to break even; "
              "`win c` / `loss c` = cents per contract on wins / losses after the US fee; `entry` = mean entry price; "
              "`exits` = share of exits by reason (tp, fair = the fair cap, sl, time = the last sellable print before "
              "the start, settle and `x->settle` = no bid found, held to the end); CLV = Pinnacle's closing fair minus "
              "the entry price (probability points).", "",
              "Paper only. Nothing here is a live trade; a pass would only mean 'ready for pretend-money trading on "
              "the live desk'.", ""]
    return "\n".join(lines)


def plain_words(doc: dict[str, Any]) -> str:
    sel, best = doc.get("selected"), doc.get("best")
    if best is None:
        return "No round trip happened."
    s = best["summary"]
    x = best["extra"]
    head = (f"The best rule ({best['cell']}) made {s['n']} trades in {s['n_events']} games; it won "
            f"{100 * (s['win_rate'] or 0):.0f} % of them but needed {100 * (s['breakeven_win_rate'] or 0):.0f} % "
            f"to break even, and kept {100 * (s['mean_net_us'] or 0):+.1f} cents per dollar after the Polymarket US fee "
            f"({100 * (x.get('gross_mean') or 0):+.1f} cents before any fee).")
    if sel:
        return head + " It cleared every check on this split, including the random-entry placebo."
    return head + " No rule cleared the bar, so this desk does not get a rule from this split."


def run_stage(stage: str, B: int = C.BOOTSTRAP_B, workers: int = WORKERS) -> dict[str, Any]:
    split = stage
    C.check_split_allowed(split)
    if stage == "test":
        C.first_test_look(HERE / "test.json")
    if not PREREG.exists():
        raise RuntimeError("W1/PREREG.md must exist (and be final) before any return is computed")
    all_cells = grid()
    if stage == "train":
        cells, placebo_keys, keep = all_cells, {c.key for c in all_cells if c.selectable}, None
    else:
        prev = json.loads((HERE / ("train.json" if stage == "val" else "val.json")).read_text())
        key = (prev.get("selected") or {}).get("cell")
        if not key or (stage == "test" and not prev.get("passes")):
            raise RuntimeError(f"{stage.upper()} is not run: the previous stage selected or passed no cell")
        cells = [c for c in all_cells if c.key == key]
        placebo_keys, keep = {key}, {key}
    res, counts = evaluate(split, cells, placebo_keys, B=B, workers=workers, keep_trips=keep)
    sel_pool = [{"cell": c["cell"], "selectable": c["selectable"], "summary": c["summary"], "bar": c["bar"]}
                for c in res]
    if stage == "train":
        chosen = C.select_one(sel_pool)
        decision = (f"SELECTED `{chosen['cell']}` for VAL" if chosen else
                    "NO EDGE on TRAIN (NO_EDGE_TRAIN): no selectable cell passes the bar; VAL and TEST are not run")
        passes = chosen is not None
    else:
        c0 = res[0]
        passes = bool(c0["bar"]["passes"])
        chosen = sel_pool[0] if passes else None
        verdict = {"val": ("SELECTED_ON_VAL", "FAIL_VAL"), "test": ("PASS_TEST", "FAIL_TEST")}[stage]
        decision = f"{verdict[0] if passes else verdict[1]}: `{c0['cell']}` {'passes' if passes else 'fails'} the bar"
    sel_full = next((c for c in res if chosen and c["cell"] == chosen["cell"]), None)
    pool = [c for c in res if c["selectable"] and c["summary"]["n"]]
    best = sel_full or (max(pool, key=lambda c: (c["summary"]["ci95"][0], c["summary"]["mean_net_us"]))
                        if pool else None)
    if chosen is not None and stage == "train":
        # PLAN §9: per-trade file of the selected cell (re-walked once, small)
        evaluate(split, [c for c in all_cells if c.key == chosen["cell"]], set(), B=200, workers=workers,
                 keep_trips={chosen["cell"]})
    n_total = C.record_runs(_ledger_rows(res, split, stage))
    doc = {"hyp": HYP, "stage": stage, "split": split, "utc": datetime.now(UTC).isoformat(timespec="seconds"),
           "plan_sha256": C.prereg_sha256(C.PLAN), "prereg_sha256": C.prereg_sha256(PREREG), "counts": counts,
           "decision": decision, "passes": passes, "selected": sel_full, "best": best, "cells": res,
           "n_trials_total": n_total}
    doc["plain"] = plain_words(doc)
    (HERE / f"{stage}.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    (HERE / f"{stage}.md").write_text(write_md(stage, doc))
    print(f"W1 {stage}: {decision}", flush=True)
    return doc


def structure(split: str) -> dict[str, Any]:
    """Universe counts only (no signal, no return): games, markets, windows, snapshot coverage."""
    specs, counts = build_specs(split)
    win_h = [sum(b - a for a, b in s.windows) / 3600.0 for s in specs]
    counts.update({
        "window_hours_median": float(np.median(win_h)) if win_h else None,
        "leagues": pd.Series([s.league for s in specs]).value_counts().head(15).to_dict(),
        "kinds": pd.Series([s.kind for s in specs]).value_counts().to_dict(),
        "with_close_fair": int(sum(math.isfinite(s.close_fair[0]) for s in specs)),
    })
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lab 7 W1")
    ap.add_argument("--stage", choices=["train", "val", "test"])
    ap.add_argument("--structure", choices=["train", "val", "test"])
    ap.add_argument("--B", type=int, default=C.BOOTSTRAP_B)
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    if a.structure:
        print(json.dumps(structure(a.structure), indent=1, default=str))
    if a.stage:
        run_stage(a.stage, B=a.B, workers=a.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())

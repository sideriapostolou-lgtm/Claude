"""Lab 7 W3: sports in-play swings, price action only (research/lab7/PLAN.md §5 W3; implementation details in
research/lab7/W3/PREREG.md, written before any W3 return was computed).

The specialist watches a game-winner market while the game is in play. When outcome 0's price has moved by at least
``x`` over the last ``y`` minutes (with at least 5 prints since), it buys the outcome that rose (MOMENTUM) or the one
that fell (FADE), then trades OUT: a take profit at ``entry + tp`` (taker, or a resting maker sell), a stop at
``entry - sl``, and a time stop 15 or 45 minutes after the entry, or at the game's recorded end (then held to
settlement). Everything about execution, fees, readings, the bar, the placebo and the ledger is
research/lab7/core.py, unchanged.

Universe: lab 4 P6's game-winner (moneyline) markets with a known start; only games with a recorded end
(Gamma's finishedTimestamp) decide; games P6 had to time with its fallback end are read apart.

CLI (from the repo root)::

    python research/lab7/W3/run.py --structure train        # universe counts only, no return
    python research/lab7/W3/run.py --stage train
    python research/lab7/W3/run.py --stage val              # only if TRAIN selected a cell
    LAB7_ALLOW_TEST=1 python research/lab7/W3/run.py --stage test   # once, only if VAL passed

Research only, paper only. No network, no key.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import multiprocessing as mp
import os
import pickle
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
if str(LAB7) not in sys.path:
    sys.path.insert(0, str(LAB7))
import core as C


def _load(name: str, path: Path) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Lab 4 P6's sport map (pure, imports nothing). P6's p6.py itself is not imported: it does ``import core`` (lab 4's),
# which would collide with lab 7's ``core``; its three small universe helpers are mirrored below and a test checks
# the mirror against P6 on the real data (tests/test_w3.py).
SP = _load("lab4_p6_sports", LAB7.parent / "lab4" / "P6" / "sports.py")
L4 = C.L4
PREREG = HERE / "PREREG.md"
OUT_DIR = C.OUT / "W3"

HYP = "W3"
TITLE = "sports in-play swings, price action only (momentum and fade)"
PLAN_VERSION = "lab7-v1"
DIRS = ("mom", "fade")
XS = (0.05, 0.10)
YS_MIN = (2, 5)
TPS = (0.03, 0.05, 0.10)
SLS = (0.05, 0.10)
STOPS: tuple[tuple[str, float | None], ...] = (("15m", 900.0), ("45m", 2700.0), ("end", None))
TP_MODES = ("taker", "maker")
K_PRINTS = 5
BAND = (0.20, 0.80)
MIN_FILLS = 50
WINNER_TYPES = ("moneyline",)
WORKERS = int(os.environ.get("LAB7_WORKERS", "4"))
PLACEBO_READING_TOP = 6
WALK_VERSION = 1  # bump when the walk or its readings change (invalidates a checkpoint)
PLACEBO_BUDGET = 40_000_000  # PREREG §7: counterparts (draws x real trips) for the reading-only placebos

# Lab 4 P6 (PLAN Amendment 5 (b)), mirrored: the fallback end = closedTime - L for a game without a valid recorded end.
FALLBACK_LAG_MIN: dict[str, float] = {
    "tennis": 38.0,
    "baseball": 20.0,
    "basketball": 42.0,
    "soccer": 172.0,
    "cricket": 238.0,
    "american football": 94.0,
}
FALLBACK_LAG_DEFAULT_MIN = 139.0
WHISTLE, FALLBACK = "final whistle", "fallback end"


# --------------------------------------------------------------------------------------------- cells


@dataclass(frozen=True)
class Entry:
    direction: str
    x: float
    y_min: int

    @property
    def key(self) -> str:
        return f"{self.direction}|x{self.x:g}|y{self.y_min:g}m"

    @property
    def y_s(self) -> float:
        return 60.0 * self.y_min


@dataclass(frozen=True)
class Cell:
    key: str
    entry: Entry
    exits: C.Exits
    selectable: bool
    stop: str


def entries() -> list[Entry]:
    return [Entry(d, x, y) for d in DIRS for x in XS for y in YS_MIN]


def cell_key(e: Entry, tp: float, sl: float, stop: str, mode: str) -> str:
    return f"{e.key}|tp{tp:g}|sl{sl:g}|t{stop}|{mode}"


def ref_key(e: Entry) -> str:
    return f"hold|{e.key}"


def grid() -> list[Cell]:
    """PLAN §5 W3: 288 selectable cells (direction x x x y x tp x sl x time stop x variant) and 8 reference cells
    (the first entry per market of each entry rule, held to settlement)."""
    cells = [
        Cell(cell_key(e, tp, sl, stop, mode), e, C.Exits(tp=tp, sl=sl, tp_mode=mode, hold_s=hold), True, stop)
        for e in entries() for tp in TPS for sl in SLS for stop, hold in STOPS for mode in TP_MODES
    ]
    cells += [Cell(ref_key(e), e, C.Exits(hold_to_settlement=True), False, "settle") for e in entries()]
    return cells


CELLS: dict[str, Cell] = {c.key: c for c in grid()}
CELL_CODE: dict[str, int] = {k: i for i, k in enumerate(CELLS)}


# --------------------------------------------------------------------------------------------- universe


def load_meta(lab4: Path = C.LAB4_DATA) -> pd.DataFrame:
    """P6 ``load_meta``, mirrored: Gamma's game facts, fetched rows only, one per id."""
    meta = pd.read_parquet(Path(lab4) / "p6_meta.parquet")
    meta = meta[meta["fetched"].astype(bool)].drop_duplicates("id", keep="last")
    meta["id"] = meta["id"].astype(str)
    return meta


def with_game_facts(markets: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """P6 ``with_game_facts``, mirrored line for line: sport, league, start (event startTime, else gameStartTime),
    end (finishedTimestamp when start < end <= closedTime, else closedTime - the sport's lag) and its kind."""
    cols = ["id", "sports_market_type", "game_start", "event_start", "event_finished", "event_score", "description"]
    m = markets.merge(meta[cols], on="id", how="inner")
    m["sport"] = [SP.sport_of(s) for s in m["event_slug"]]
    m["league"] = [SP.league_of(s) for s in m["event_slug"]]
    m["start"] = m["event_start"].where(m["event_start"].notna(), m["game_start"])
    m["finished"] = m["event_finished"]
    valid = (
        m["finished"].notna()
        & m["start"].notna()
        & (m["finished"] > m["start"])
        & (m["finished"] <= m["closed_time"])
    )
    lag = m["sport"].map(lambda sp: FALLBACK_LAG_MIN.get(sp, FALLBACK_LAG_DEFAULT_MIN)) * 60.0
    m["end"] = m["finished"].where(valid, m["closed_time"] - lag)
    m["end_kind"] = np.where(valid, WHISTLE, FALLBACK)
    return m


def is_universe(m: pd.DataFrame) -> pd.Series:
    """P6 ``is_universe``, mirrored: game winners with a start and an end after it."""
    return m["sports_market_type"].isin(WINNER_TYPES) & m["start"].notna() & (m["end"] > m["start"])


def side_labels(outcomes_json: Any) -> tuple[str, str]:
    """The name of each outcome's side for the side breakdown: ('yes', 'no') in a Yes/No market (in its listed
    order), else ('team1', 'team2') for the listed-first and listed-second team."""
    try:
        outs = [str(o).strip().lower() for o in json.loads(outcomes_json)]
    except (TypeError, ValueError):
        outs = []
    if outs == ["yes", "no"]:
        return ("yes", "no")
    if outs == ["no", "yes"]:
        return ("no", "yes")
    return ("team1", "team2")


def universe(split: str, lab4: Path = C.LAB4_DATA) -> pd.DataFrame:
    """PLAN §5 W3 / PREREG §1: the split's binary single-winner markets (lab 4's eligibility, split by closedTime)
    that P6 calls game winners with a known start, of a sport other than 'other'. The >= 50 fills rule is applied
    when the tape is loaded. One row per market, ordered by closedTime then id."""
    C.check_split_allowed(split)
    markets = pd.read_parquet(Path(lab4) / "markets.parquet")
    m = with_game_facts(L4.Dataset.eligible(markets, split), load_meta(lab4))
    m = m[is_universe(m) & (m["sport"] != "other")].copy()
    m["rate"] = [L4.fee_rate(t, bool(e)) for t, e in zip(m["fee_type"], m["fees_enabled"], strict=True)]
    m["family"] = [L4.fee_family(t, bool(e)) for t, e in zip(m["fee_type"], m["fees_enabled"], strict=True)]
    sides = [side_labels(o) for o in m["outcomes"]]
    m["side0"] = [s[0] for s in sides]
    m["side1"] = [s[1] for s in sides]
    m["split"] = split
    keep = ["id", "event_slug", "question", "sport", "league", "start", "end", "end_kind", "closed_time",
            "winner_index", "rate", "family", "side0", "side1", "split"]
    return m[keep].sort_values(["closed_time", "id"], kind="stable").reset_index(drop=True)


def make_market(row: dict[str, Any], tape: C.Tape, y_s: float) -> C.Market:
    """PLAN §5 W3: entry window ``[start + y, end)``; entry deadline = end_t = the end (recorded or fallback); mode
    'settle' (a position still open at the end, or whose hold_s stop would fall after it, is held to settlement);
    hard end and settlement = closedTime; payout from lab 4's winner; band 0.20-0.80; no fair."""
    start, end, closed = float(row["start"]), float(row["end"]), float(row["closed_time"])
    w = int(row["winner_index"])
    windows = ((start + y_s, end),) if end > start + y_s else ()
    return C.Market(
        id=str(row["id"]), event=str(row["event_slug"]), split=str(row["split"]), tape=tape,
        rate_com=float(row["rate"]), payout=(1.0, 0.0) if w == 0 else (0.0, 1.0), settle_t=closed,
        hard_end=closed, entry_windows=windows, entry_deadline=end, end_t=end, end_mode="settle", fair=None,
        band=BAND, info={"sport": row["sport"], "end_kind": row["end_kind"]},
    )


# --------------------------------------------------------------------------------------------- trips, compactly

REASONS = ("tp", "fair", "sl", "time", "settle", "tp->settle", "fair->settle", "sl->settle", "time->settle")
LEGS = ("taker", "maker", "settle")
STORED = ("o", "t_signal", "p_signal", "t_entry", "p_entry", "entry_print_size", "t_trigger", "t_exit", "p_exit",
          "late_stop", "fee_us", "fee_com", "fee_stress", "pnl_us", "pnl_com", "pnl_stress")
META_COLUMNS = ["sport", "league", "end_kind", "end", "start", "side", "side_ab"]


def encode(trips: list[dict[str, Any]], code: int) -> dict[str, np.ndarray]:
    """One cell's trips in one market as numeric arrays; :func:`decode` rebuilds core's trip frame exactly
    (``shares = ticket / p_entry``, ``hold_s = t_exit - t_entry`` and ``net = pnl / ticket`` are core's own
    formulas)."""
    out = {c: np.array([float(t[c]) for t in trips], dtype=float) for c in STORED}
    out["reason"] = np.array([REASONS.index(t["reason"]) for t in trips], dtype=np.int8)
    out["exit_leg"] = np.array([LEGS.index(t["exit_leg"]) for t in trips], dtype=np.int8)
    out["cell"] = np.full(len(trips), code, dtype=np.int16)
    return out


def decode(arr: dict[str, np.ndarray], mask: np.ndarray, u: pd.DataFrame) -> pd.DataFrame:
    """The trips of ``mask`` as core's trip frame (``core.TRIP_COLUMNS``) plus W3's columns (:data:`META_COLUMNS`),
    ordered by entry time then market id. ``u``: the universe, indexed by ``arr['mi']``."""
    mi = arr["mi"][mask]
    f = pd.DataFrame({c: arr[c][mask] for c in STORED})
    f["o"] = f["o"].astype(int)
    f["late_stop"] = f["late_stop"].astype(bool)
    f["id"] = u["id"].astype(str).to_numpy()[mi]
    f["event"] = u["event_slug"].astype(str).to_numpy()[mi]
    f["split"] = u["split"].to_numpy()[mi]
    f["shares"] = C.TICKET_USD / f["p_entry"]
    f["hold_s"] = f["t_exit"] - f["t_entry"]
    for s in C.FEE_SCHEMES:
        f[f"net_{s}"] = f[f"pnl_{s}"] / C.TICKET_USD
    f["reason"] = np.asarray(REASONS, dtype=object)[arr["reason"][mask]]
    f["exit_leg"] = np.asarray(LEGS, dtype=object)[arr["exit_leg"][mask]]
    f["day"] = pd.to_datetime(f["t_exit"], unit="s", utc=True).dt.strftime("%Y-%m-%d").to_numpy()
    for c in ("sport", "league", "end_kind", "end", "start"):
        f[c] = u[c].to_numpy()[mi]
    s0, s1 = u["side0"].to_numpy()[mi], u["side1"].to_numpy()[mi]
    f["side"] = np.where(f["o"].to_numpy() == 0, s0, s1)
    f["side_ab"] = np.where(np.isin(f["side"], ("yes", "team1")), "A: Yes / first-listed", "B: No / second-listed")
    f = f[C.TRIP_COLUMNS + META_COLUMNS]
    return f.sort_values(["t_entry", "id"], kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------------------------- workers

_U: list[dict[str, Any]] = []
_CTX: dict[str, Any] = {}


def market_trips(row: dict[str, Any], tape: C.Tape, cells: list[Cell]) -> tuple[dict[str, list], dict[str, int]]:
    """Every requested cell's round trips in one market: one Market per lookback y (its entry window), the swing
    signal once per entry rule, every exit rule walked on it."""
    by_entry: dict[Entry, list[Cell]] = {}
    for c in cells:
        by_entry.setdefault(c.entry, []).append(c)
    markets = {y: make_market(row, tape, 60.0 * y) for y in sorted({e.y_min for e in by_entry})}
    trips: dict[str, list] = {}
    missed: dict[str, int] = {}
    for e, group in by_entry.items():
        mk = markets[e.y_min]
        if not mk.entry_windows:
            continue
        sig = C.swing_signals(tape, e.x, e.y_s, K_PRINTS, e.direction)
        for c in group:
            tr, ms = C.walk(mk, sig, c.exits)
            if tr:
                trips[c.key] = tr
            if ms:
                missed[c.key] = int(ms)
    return trips, missed


def _work(k: int) -> dict[str, Any]:
    row = _U[k]
    tape = C.load_tape(str(row["id"]), min_fills=MIN_FILLS)
    if tape is None:
        return {"k": k, "skip": True, "arr": None, "missed": {}, "n_prints": 0}
    cells = [CELLS[key] for key in _CTX["cells"]]
    trips, missed = market_trips(row, tape, cells)
    parts = [encode(tr, CELL_CODE[key]) for key, tr in trips.items()]
    arr = {c: np.concatenate([p[c] for p in parts]) for c in parts[0]} if parts else None
    return {"k": k, "skip": False, "arr": arr, "missed": missed, "n_prints": len(tape)}


def _placebo_work(task: tuple[int, dict[str, int]]) -> tuple[int, dict[str, np.ndarray]]:
    """The random-entry placebo for one market and every requested cell: ``core.placebo_matrix`` with a generator
    seeded by (``core.placebo_seed('W3', cell, split)``, crc32 of the market id), so the draw does not depend on the
    worker or the order (PREREG §7)."""
    k, need = task
    row = _U[k]
    tape = C.load_tape(str(row["id"]), min_fills=MIN_FILLS)
    out: dict[str, np.ndarray] = {}
    if tape is None:
        return k, out
    for key, n in need.items():
        cell = CELLS[key]
        mk = make_market(row, tape, cell.entry.y_s)
        seed = [C.placebo_seed(HYP, key, str(row["split"])), zlib.crc32(str(row["id"]).encode())]
        out[key] = C.placebo_matrix(mk, int(n), cell.exits, rng=np.random.default_rng(seed))
    return k, out


def _pool_map(fn: Any, items: list[Any], workers: int, chunksize: int = 8) -> list[Any]:
    if workers <= 1:
        return [fn(x) for x in items]
    with mp.get_context("fork").Pool(workers) as pool:
        return list(pool.imap(fn, items, chunksize=chunksize))


def evaluate(u: pd.DataFrame, cell_keys: list[str], workers: int = WORKERS) -> tuple[dict[str, np.ndarray],
                                                                                      dict[str, dict[str, int]], dict]:
    """Every market of the universe through every requested cell (one tape in memory per worker). Returns the
    encoded trips with ``mi`` (the row of ``u``), missed entries per cell and end kind, and coverage counts."""
    global _U
    _U = u.to_dict("records")
    _CTX.clear()
    _CTX["cells"] = list(cell_keys)
    t0 = time.time()
    res = _pool_map(_work, list(range(len(_U))), workers)
    parts = [r for r in res if r["arr"] is not None]
    keys = [*STORED, "reason", "exit_leg", "cell"]
    if parts:
        arr = {c: np.concatenate([r["arr"][c] for r in parts]) for c in keys}
        arr["mi"] = np.concatenate([np.full(len(r["arr"]["cell"]), r["k"], dtype=np.int32) for r in parts])
    else:
        arr = {c: np.zeros(0) for c in keys} | {"cell": np.zeros(0, dtype=np.int16), "mi": np.zeros(0, dtype=np.int32),
                                                "reason": np.zeros(0, dtype=np.int8),
                                                "exit_leg": np.zeros(0, dtype=np.int8)}
    missed: dict[str, dict[str, int]] = {WHISTLE: {}, FALLBACK: {}}
    for r in res:
        kind = _U[r["k"]]["end_kind"]
        for key, v in r["missed"].items():
            missed[kind][key] = missed[kind].get(key, 0) + v
    ok = [r for r in res if not r["skip"]]
    cov: dict[str, Any] = {"markets": len(_U), "evaluated": len(ok), "skipped_few_fills": len(_U) - len(ok),
                           "prints": int(sum(r["n_prints"] for r in ok)), "walk_s": round(time.time() - t0, 1)}
    for kind in (WHISTLE, FALLBACK):
        ks = [r for r in ok if _U[r["k"]]["end_kind"] == kind]
        cov[kind] = {"markets": len(ks), "events": len({_U[r["k"]]["event_slug"] for r in ks}),
                     "by_sport": pd.Series([_U[r["k"]]["sport"] for r in ks], dtype=object).value_counts().to_dict()}
    return arr, missed, cov


def market_counts(arr: dict[str, np.ndarray], key: str, mask: np.ndarray) -> dict[int, int]:
    """Real round trips per market (row of the universe) of one cell, within ``mask``."""
    mi = arr["mi"][mask & (arr["cell"] == CELL_CODE[key])]
    return {int(i): int(n) for i, n in zip(*np.unique(mi, return_counts=True), strict=True)}


def placebo_pass(counts: dict[str, dict[int, int]], keys: list[str],
                 workers: int = WORKERS) -> dict[str, list[np.ndarray]]:
    """One pass over the markets with deciding trips in any of ``keys``: each market gets as many counterparts per
    draw as it has real round trips in the cell (PLAN §7). ``counts``: per cell, deciding trips per market."""
    need: dict[int, dict[str, int]] = {}
    for key in keys:
        for i, n in counts.get(key, {}).items():
            need.setdefault(int(i), {})[key] = int(n)
    res = _pool_map(_placebo_work, sorted(need.items()), workers, chunksize=4)
    blocks: dict[str, list[np.ndarray]] = {k: [] for k in keys}
    for _, out in res:
        for key, mat in out.items():
            blocks[key].append(mat)
    return blocks


# --------------------------------------------------------------------------------------------- readings


def _group(f: pd.DataFrame, col: str) -> dict[str, Any]:
    out = {}
    for k, g in f.groupby(col):
        net = g["net_us"].to_numpy(dtype=float)
        out[str(k)] = {"n": len(g), "events": int(g["event"].nunique()), "win_rate": float((net > 0).mean()),
                       "mean_net_us": float(net.mean()), "total_usd": float(g["pnl_us"].sum())}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["n"]))


def lite(f: pd.DataFrame, B: int = C.BOOTSTRAP_B) -> dict[str, Any]:
    """A short reading (the fallback-end breakdown and the subsets): n, events, win rate, mean net (US) with its
    event-bootstrap CI95, stress mean, total $."""
    if len(f) == 0:
        return {"n": 0, "events": 0, "win_rate": None, "mean_net_us": None, "ci95": [None, None],
                "mean_net_stress": None, "total_usd": 0.0}
    net = f["net_us"].to_numpy(dtype=float)
    ci = C.event_bootstrap_ci(net, f["event"].astype(str).to_numpy(), B=B)
    return {"n": len(f), "events": int(f["event"].nunique()), "win_rate": float((net > 0).mean()),
            "mean_net_us": float(net.mean()), "ci95": [ci[0], ci[1]],
            "mean_net_stress": float(f["net_stress"].mean()), "total_usd": float(f["pnl_us"].sum())}


def extra_readings(f: pd.DataFrame, B: int = C.BOOTSTRAP_B) -> dict[str, Any]:
    """PREREG §6 readings beyond core.summarize (readings only, never a selector): the gross mean (before any fee)
    with its CI95, the entry slippage, the big-entry subset, the exits filled after the recorded end, the share of
    P&L from the ten biggest events, and the breakdowns by sport, league and side bought."""
    if len(f) == 0:
        return {}
    ev = f["event"].astype(str).to_numpy()
    gross = ((f["pnl_us"] + f["fee_us"]) / C.TICKET_USD).to_numpy(dtype=float)
    big = (f["entry_print_size"] >= f["shares"]).to_numpy()
    after = (f["t_exit"] >= f["end"]).to_numpy() & (f["exit_leg"] != "settle").to_numpy()
    by_ev = f.groupby("event")["pnl_us"].sum()
    tot_abs = float(by_ev.abs().sum())
    top10 = by_ev.reindex(by_ev.abs().sort_values(ascending=False).index[:10])
    return {
        "gross_mean": float(gross.mean()),
        "gross_ci95": list(C.event_bootstrap_ci(gross, ev, B=B)),
        "entry_slippage": float((f["p_entry"] - f["p_signal"]).mean()),
        "entry_delay_s_median": float((f["t_entry"] - f["t_signal"]).median()),
        "big_entry": lite(f[big], B=B),
        "exit_after_end": {"n": int(after.sum()), "share": float(after.mean()),
                           "mean_net_us": float(f.loc[after, "net_us"].mean()) if after.any() else None},
        "top10_events_usd": float(top10.sum()),
        "top10_events_abs_share": float(top10.abs().sum() / tot_abs) if tot_abs > 0 else None,
        "by_sport": _group(f, "sport"),
        "by_side": _group(f, "side_ab"),
        "by_side4": _group(f, "side"),
        "by_league": dict(list(_group(f, "league").items())[:20]),
    }


def cell_result(cell: Cell, f: pd.DataFrame, fb: pd.DataFrame, missed: int, split: str,
                B: int = C.BOOTSTRAP_B) -> dict[str, Any]:
    s = C.summarize(f[C.TRIP_COLUMNS], split, missed=missed, B=B)
    return {
        "cell": cell.key,
        "selectable": cell.selectable,
        "entry": cell.entry.key,
        "exits": {k: v for k, v in cell.exits.__dict__.items()},
        "summary": s,
        "checks": C.bar_checks(s),
        "markets_traded": int(f["id"].nunique()) if len(f) else 0,
        "extra": extra_readings(f, B),
        "fallback": lite(fb, B=B),
    }


def mirror_readings(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PREREG §6: momentum and fade with the same x, y and exits trade opposite sides of the same moves. Their gross
    means side by side (if one is +g, the other should sit near -g: a check that the simulator has no free money)."""
    by = {r["cell"]: r for r in results}
    rows = []
    for key, r in by.items():
        if not key.startswith("mom|"):
            continue
        twin = by.get("fade|" + key[len("mom|"):])
        if twin is None:
            continue
        rows.append({"cell": key[len("mom|"):], "mom_n": r["summary"]["n"], "fade_n": twin["summary"]["n"],
                     "mom_gross": (r.get("extra") or {}).get("gross_mean"),
                     "fade_gross": (twin.get("extra") or {}).get("gross_mean"),
                     "mom_net": r["summary"]["mean_net_us"], "fade_net": twin["summary"]["mean_net_us"]})
    return rows


# --------------------------------------------------------------------------------------------- stages


def placebo_plan(results: list[dict[str, Any]], stage: str) -> tuple[list[str], list[str], dict[str, Any]]:
    """PREREG §7: the placebo for every selectable cell clearing PLAN §7 conditions 1-5 (it decides); as readings on
    TRAIN, the six best selectable cells by CI95 lower bound, taken in rank order while the reading-only
    counterparts stay within the budget; on VAL / TEST, the cell under test."""
    required = [r["cell"] for r in results if r["selectable"] and all(r["checks"].values())]
    reading: list[str] = []
    info: dict[str, Any] = {"budget": PLACEBO_BUDGET, "skipped_for_budget": []}
    if stage == "train":
        ranked = sorted((r for r in results if r["selectable"] and r["summary"]["n"]),
                        key=lambda r: (-r["summary"]["ci95"][0], -r["summary"]["mean_net_us"], r["cell"]))
        cost = 0
        for r in ranked[:PLACEBO_READING_TOP]:
            if r["cell"] in required:
                continue
            c = C.PLACEBO_DRAWS * r["summary"]["n"]
            if cost + c > PLACEBO_BUDGET:
                info["skipped_for_budget"].append(r["cell"])
                continue
            cost += c
            reading.append(r["cell"])
        info["reading_counterparts"] = int(cost)
    else:
        reading = [r["cell"] for r in results if r["cell"] not in required and r["summary"]["n"]]
    return required, reading, info


def _ledger_rows(results: list[dict[str, Any]], split: str, stage: str) -> list[dict[str, Any]]:
    plan, prereg = C.prereg_sha256(C.PLAN), C.prereg_sha256(PREREG)
    return [{"hyp": HYP, "cell": r["cell"], "split": split, "stage": stage,
             "kind": "selectable" if r["selectable"] else "reference", "n": r["summary"]["n"],
             "mean_net_us": r["summary"]["mean_net_us"], "ci95": r["summary"]["ci95"],
             "mean_net_stress": r["summary"]["mean_net_stress"], "passes": bool(r["passes"]),
             "plan_sha256": plan, "prereg_sha256": prereg} for r in results]


def save_trips(frame: pd.DataFrame, split: str, key: str) -> str | None:
    """PLAN §9: per-trade files only for the selected, VAL and TEST cells (zstd parquet outside git)."""
    if not len(frame):
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{split}_{key.replace('|', '_')}.parquet"
    frame.to_parquet(path, index=False, compression="zstd")
    return str(path)


def run_stage(stage: str, B: int = C.BOOTSTRAP_B, workers: int = WORKERS) -> dict[str, Any]:
    split = stage
    C.check_split_allowed(split)
    out_json = HERE / f"{stage}.json"
    if stage == "test":
        C.first_test_look(out_json)
    if not PREREG.exists():
        raise RuntimeError("W3/PREREG.md must exist (and be final) before any return is computed (PLAN §10)")
    if stage == "train":
        keys = list(CELLS)
    else:
        prev = json.loads((HERE / ("train.json" if stage == "val" else "val.json")).read_text())
        sel = prev.get("selected")
        if not sel or (stage == "test" and prev.get("verdict") != "SELECTED_ON_VAL"):
            raise RuntimeError(f"{stage.upper()} is not run: the previous stage selected or passed no cell")
        keys = [sel]
    u = universe(split)
    kinds = u["end_kind"].to_numpy()
    # PREREG §8 (memory): the grid is walked one entry rule at a time (its 36 exit cells and its reference); each
    # pass keeps only the cells' readings and their per-market trip counts (for the placebo)
    groups: dict[str, list[str]] = {}
    for key in keys:
        groups.setdefault(CELLS[key].entry.key, []).append(key)
    results: list[dict[str, Any]] = []
    counts: dict[str, dict[int, int]] = {}
    missed_fb: dict[str, int] = {}
    cov: dict[str, Any] = {}
    walk_s = read_s = 0.0
    # engineering only: the walk's readings are checkpointed (outside git) so an interrupted placebo does not force
    # a second walk; a checkpoint is used only for the same split, cells, core.py, PLAN.md and PREREG.md
    ckpt_sig = {"split": split, "keys": keys, "core": C.prereg_sha256(LAB7 / "core.py"),
                "plan": C.prereg_sha256(C.PLAN), "prereg": C.prereg_sha256(PREREG), "walk": WALK_VERSION}
    ckpt = OUT_DIR / f"walk_{split}.pkl"
    if ckpt.exists():
        saved = pickle.loads(ckpt.read_bytes())
        if saved.get("sig") == ckpt_sig:
            results, counts, missed_fb, cov = saved["results"], saved["counts"], saved["missed_fb"], saved["cov"]
            cov["walk_from_checkpoint"] = True
            groups = {}
            print(f"W3 {stage}: walk readings loaded from {ckpt}", flush=True)
    for ekey, gkeys in groups.items():
        arr, missed, cov_g = evaluate(u, gkeys, workers)
        walk_s += cov_g["walk_s"]
        cov = cov or cov_g
        decide = kinds[arr["mi"]] == WHISTLE if len(arr["mi"]) else np.zeros(0, dtype=bool)
        t0 = time.time()
        for key in gkeys:
            in_cell = arr["cell"] == CELL_CODE[key]
            f = decode(arr, in_cell & decide, u)
            fb = decode(arr, in_cell & ~decide, u)
            results.append(cell_result(CELLS[key], f, fb, missed[WHISTLE].get(key, 0), split, B))
            counts[key] = market_counts(arr, key, decide)
        missed_fb.update(missed[FALLBACK])
        read_s += time.time() - t0
        del arr
        print(f"W3 {stage}: entry rule {ekey} walked ({len(gkeys)} cells)", flush=True)
    results.sort(key=lambda r: CELL_CODE[r["cell"]])
    if not cov.get("walk_from_checkpoint"):
        cov["walk_s"], cov["readings_s"] = round(walk_s, 1), round(read_s, 1)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        ckpt.write_bytes(pickle.dumps({"sig": ckpt_sig, "results": results, "counts": counts,
                                       "missed_fb": missed_fb, "cov": cov}))
    required, reading, pinfo = placebo_plan(results, stage)
    t1 = time.time()
    blocks = placebo_pass(counts, required + reading, workers)
    cov["placebo_s"] = round(time.time() - t1, 1)
    for r in results:
        key = r["cell"]
        if key in blocks and r["summary"]["mean_net_us"] is not None:
            r["placebo"] = C.placebo_reading(blocks[key], r["summary"]["mean_net_us"])
            r["placebo_why"] = "bar (conditions 1-5 pass)" if key in required else "reading"
        else:
            r["placebo"] = None
        # PLAN §7: the placebo cannot rescue a cell failing conditions 1-5 (core.bar needs all six), so a reading
        # placebo only fills in the sixth check of a cell that fails anyway
        r["bar"] = C.bar(r["summary"], r["placebo"])
        r["passes"] = bool(r["bar"]["passes"]) and r["selectable"]
    if stage == "train":
        chosen = C.select_one(results)
        verdict = "TRAIN_SELECTED" if chosen else "NO_EDGE_TRAIN"
        sel_key = chosen["cell"] if chosen else None
    else:
        r0 = results[0]
        sel_key = r0["cell"] if r0["passes"] else None
        verdict = {"val": ("SELECTED_ON_VAL", "FAIL_VAL"), "test": ("PASS_TEST", "FAIL_TEST")}[stage][
            0 if r0["passes"] else 1]
    n_total = C.record_runs(_ledger_rows(results, split, stage))
    pool = [r for r in results if r["selectable"] and r["summary"]["n"]]
    best = (next(r for r in results if r["cell"] == sel_key) if sel_key else
            (min(pool, key=lambda r: (-r["summary"]["ci95"][0], -r["summary"]["mean_net_us"], r["cell"]))
             if pool else None))
    trips_file = None
    keep_key = sel_key or (results[0]["cell"] if stage != "train" else None)
    if keep_key:  # re-walked (deterministic): the per-group trips were not kept
        arr, _, _ = evaluate(u, [keep_key], workers)
        keep = kinds[arr["mi"]] == WHISTLE if len(arr["mi"]) else np.zeros(0, dtype=bool)
        trips_file = save_trips(decode(arr, keep, u), split, keep_key)
        del arr
    doc = {
        "hyp": HYP, "title": TITLE, "stage": stage, "split": split, "plan_version": PLAN_VERSION,
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "plan_sha256": C.prereg_sha256(C.PLAN), "prereg_sha256": C.prereg_sha256(PREREG),
        "verdict": verdict, "selected": sel_key, "passes": sel_key is not None, "best": best["cell"] if best else None,
        "coverage": cov, "placebo_required": required, "placebo_readings": reading, "placebo_info": pinfo,
        "mirror": mirror_readings(results) if stage == "train" else [],
        "cells": results, "n_trials_total": n_total, "trips_file": trips_file,
        "missed_fallback": missed_fb,
    }
    out_json.write_text(json.dumps(doc, indent=1, sort_keys=True, default=_jsonable) + "\n")
    (HERE / f"{stage}.md").write_text(render_md(doc))
    ckpt.unlink(missing_ok=True)
    print(f"W3 {stage}: {verdict} {sel_key or ''} (trials across labs 2-7: {n_total})", flush=True)
    return doc


def _jsonable(v: Any) -> Any:
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return str(v)


# --------------------------------------------------------------------------------------------- report


def _f(v: Any, nd: int = 4) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _pct(v: Any, nd: int = 1) -> str:
    return "-" if v is None else f"{100.0 * float(v):.{nd}f} %"


def _ci(ci: Any, nd: int = 4) -> str:
    ci = ci or [None, None]
    return f"[{_f(ci[0], nd)}, {_f(ci[1], nd)}]"


def _esc(key: str) -> str:
    return key.replace("|", "\\|")


def plain_words(doc: dict[str, Any]) -> list[str]:
    cells = doc["cells"]
    sel = [c for c in cells if c["selectable"]]
    with_n = [c for c in sel if c["summary"]["n"]]
    best = next((c for c in cells if c["cell"] == doc.get("best")), None)
    pos = sum(1 for c in with_n if (c["summary"]["mean_net_us"] or 0) > 0)
    gpos = sum(1 for c in with_n if ((c.get("extra") or {}).get("gross_mean") or 0) > 0)
    out = ["## In plain words", ""]
    v = doc["verdict"]
    if doc["stage"] == "train":
        if v == "NO_EDGE_TRAIN":
            out.append(f"- **No edge on TRAIN.** None of the {len(sel)} in-play rules passed the bar, so this desk gets "
                       "no rule and VAL and TEST are not run.")
        else:
            out.append(f"- **One rule passed TRAIN:** `{doc['selected']}`. It now has to pass VAL, unchanged, before "
                       "anyone believes it.")
        out.append(f"- {pos} of {len(with_n)} rules made money on average after the Polymarket US fee; {gpos} made money "
                   "before any fee. A rule that only wins before the fee cannot pay the venue.")
    else:
        out.append(f"- **{v}** for `{(cells[0] if cells else {}).get('cell')}` on {doc['stage'].upper()}.")
    if best:
        s, x = best["summary"], best.get("extra") or {}
        r = s["risk"]
        out.append(
            f"- The best rule by the cautious measure (`{best['cell']}`) made {s['n']} trades in {s['n_events']} games "
            f"({_f(s['trips_per_day'], 1)} a day). It won {_pct(s['win_rate'], 0)} of them; with its average win "
            f"({_f(s['win_cents'], 2)}c per contract) and loss ({_f(s['loss_cents'], 2)}c) it needed "
            f"{_pct(s['breakeven_win_rate'], 0)} to break even. It kept {100 * (s['mean_net_us'] or 0):+.2f} cents per "
            f"dollar after the fee ({100 * (x.get('gross_mean') or 0):+.2f} before any fee).")
        out.append(
            f"- Its risk book: at most {r['max_open']} trades open at once (${r['capital_usd']:.0f} tied up), a worst "
            f"day of ${_f(r['worst_day_usd'], 2)}, a deepest dip of ${_f(r['max_drawdown_usd'], 2)} from its best "
            f"point, and a longest run of {r['longest_losing_streak']} losing trades in a row. With a $10 daily loss "
            f"stop it would have kept {r['daily_stop']['n']} trades and finished at ${_f(r['daily_stop']['total_usd'], 2)}.")
        pl = best.get("placebo")
        if pl:
            out.append(f"- Random entries with the same exits averaged {100 * (pl['mean'] or 0):+.2f} cents per dollar "
                       f"(95th percentile {100 * (pl['p95'] or 0):+.2f}); the rule sits at percentile "
                       f"{_f(pl['real_percentile'], 0)} of them.")
    out.append("- The owner's 50c-to-55c idea needs to be right far more often than a coin flip, because each buy "
               "and each sell costs about 1.7c near 50c. This page measures whether watching in-play price swings "
               "gives that skill. Paper only: nothing here is a live trade.")
    out.append("")
    return out


def _row(c: dict[str, Any]) -> str:
    s, x, r = c["summary"], c.get("extra") or {}, c["summary"]["risk"]
    fb = c.get("fallback") or {}
    mix = " ".join(f"{k}:{v:.2f}" for k, v in s.get("exit_mix", {}).items())
    chk = "".join("Y" if c["bar"]["checks"][k] else ("-" if k == "placebo" and not c.get("placebo") else "n")
                  for k in ("n", "mean", "ci_lower", "stress", "loss_guards", "placebo"))
    tag = "" if c["selectable"] else " (ref)"
    return (
        f"| `{_esc(c['cell'])}`{tag} | {s['n']} | {s.get('n_events', 0)} | {s['missed']} | {_f(s['trips_per_day'], 1)} | "
        f"{_f(s['win_rate'], 3)} | {_f(s['mean_net_us'])} | {_ci(s['ci95'])} | {_f(s['mean_net_com'])} | "
        f"{_f(s['mean_net_stress'])} | {_f(x.get('gross_mean'))} | {_f(s['breakeven_win_rate'], 3)} | "
        f"{_f(s['win_cents'], 2)} | {_f(s['loss_cents'], 2)} | {_f(s['mean_p_entry'], 3)} | {mix} | "
        f"{_f(s['hold_min_median'], 1)} | {r['max_open']} | {_f(r['max_drawdown_usd'], 0)} | "
        f"{_f(r['worst_day_usd'], 0)} | {_f(r['sharpe_daily'], 2)} | {fb.get('n', 0)} | {_f(fb.get('mean_net_us'))} | "
        f"{_f((c.get('placebo') or {}).get('p95'))} | {chk} | {'PASS' if c.get('passes') else 'no'} |")


def _cell_detail(c: dict[str, Any], title: str) -> list[str]:
    s, x, r = c["summary"], c.get("extra") or {}, c["summary"]["risk"]
    pl = c.get("placebo")
    fb = c.get("fallback") or {}
    be = x.get("big_entry") or {}
    ae = x.get("exit_after_end") or {}
    lines = [f"## {title}: `{c['cell']}`", "",
             f"- {s['n']} round trips in {s['n_events']} games ({c.get('markets_traded', 0)} markets), {s['missed']} "
             f"missed entries, {_f(s['trips_per_day'], 2)} per day; win rate {_pct(s['win_rate'])}",
             f"- mean net per $ (US fee) {_f(s['mean_net_us'])}, CI95 {_ci(s['ci95'])}; polymarket.com fee "
             f"{_f(s['mean_net_com'])}; stress {_f(s['mean_net_stress'])}; before any fee {_f(x.get('gross_mean'))} "
             f"(CI95 {_ci(x.get('gross_ci95'))}); rule-of-three worst case {_f(s['worst_case_net'])}",
             f"- wins average {_f(s['win_cents'], 2)}c per contract, losses {_f(s['loss_cents'], 2)}c: break-even win "
             f"rate {_pct(s['breakeven_win_rate'])}; mean entry price {_f(s['mean_p_entry'], 3)}; entry slippage "
             f"(fill - signal print) {_f(x.get('entry_slippage'))}; median entry delay "
             f"{_f(x.get('entry_delay_s_median'), 0)} s; entries whose print was smaller than our contracts "
             f"{_pct(s['small_entry_share'])}",
             f"- exit mix {json.dumps({k: round(v, 3) for k, v in s['exit_mix'].items()})}; median hold "
             f"{_f(s['hold_min_median'], 1)} min; exits filled after the recorded end {ae.get('n', 0)} "
             f"({_pct(ae.get('share'))}, mean net {_f(ae.get('mean_net_us'))})",
             f"- big entries only (the entry print alone covered our contracts): n {be.get('n', 0)}, mean net "
             f"{_f(be.get('mean_net_us'))}, CI95 {_ci(be.get('ci95'))}",
             f"- the ten games with the largest P&L carry {_pct(x.get('top10_events_abs_share'))} of the absolute "
             f"P&L (net ${_f(x.get('top10_events_usd'), 2)})",
             "- placebo (random entry time and side, same exits): "
             + (f"mean {_f(pl['mean'])}, p95 {_f(pl['p95'])}, real at percentile {_f(pl['real_percentile'], 1)}, drop "
                f"share {_f(pl['drop_share'], 3)} ({c.get('placebo_why')})" if pl else "not computed"),
             f"- games without a recorded end (fallback end; never decide): n {fb.get('n', 0)} in "
             f"{fb.get('events', 0)} games, mean net {_f(fb.get('mean_net_us'))}, CI95 {_ci(fb.get('ci95'))}",
             f"- **risk book:** max {r['max_open']} positions open at once (${r['capital_usd']:.0f} locked); max "
             f"drawdown ${_f(r['max_drawdown_usd'], 2)}; worst day ${_f(r['worst_day_usd'], 2)}, best day "
             f"${_f(r['best_day_usd'], 2)} ({r['days_with_exits']} days with exits); daily Sharpe "
             f"{_f(r['sharpe_daily'], 2)}; longest losing streak {r['longest_losing_streak']}; worst trip "
             f"${_f(r['worst_trip_usd'], 2)}; $10 daily loss stop: {r['daily_stop']['n']} trips kept, "
             f"{r['daily_stop']['skipped']} skipped on {r['daily_stop']['days_stopped']} days, mean net "
             f"{_f(r['daily_stop']['mean_net'])}, total ${_f(r['daily_stop']['total_usd'], 2)}",
             f"- checks: {json.dumps(c['bar']['checks'])}", ""]
    for name, key in (("sport", "by_sport"), ("side bought", "by_side"), ("side (detail)", "by_side4"),
                      ("league (top 20 by n)", "by_league")):
        rows = x.get(key) or {}
        if not rows:
            continue
        lines += [f"By {name}:", "", "| group | n | games | win rate | mean net (US) | total $ |", "|---|---|---|---|---|---|"]
        for k, v in rows.items():
            lines.append(f"| {k} | {v['n']} | {v['events']} | {_f(v['win_rate'], 3)} | {_f(v['mean_net_us'])} | "
                         f"{_f(v['total_usd'], 0)} |")
        lines.append("")
    return lines


def render_md(doc: dict[str, Any]) -> str:
    cov = doc["coverage"]
    w, fbk = cov.get(WHISTLE, {}), cov.get(FALLBACK, {})
    head = {"NO_EDGE_TRAIN": "NO EDGE on TRAIN (NO_EDGE_TRAIN): no selectable cell passes the bar; VAL and TEST are "
                             "not run",
            "TRAIN_SELECTED": f"SELECTED `{doc['selected']}` on TRAIN for VAL"}.get(doc["verdict"], doc["verdict"])
    lines = [f"# Lab 7 W3, {doc['title']}: {doc['stage'].upper()}", "", f"**Decision: {head}**", ""]
    lines += plain_words(doc)
    lines += [
        f"Run {doc['utc']} on split `{doc['split']}` ({doc['plan_version']}). PLAN.md sha256 `{doc['plan_sha256'][:12]}`, "
        f"W3/PREREG.md sha256 `{doc['prereg_sha256'][:12]}`. Universe: {cov['markets']} game-winner markets, "
        f"{cov['evaluated']} with >= 50 fills ({cov['prints']:,} prints). Deciding (recorded end): {w.get('markets')} "
        f"markets in {w.get('events')} games; read apart (fallback end): {fbk.get('markets')} markets in "
        f"{fbk.get('events')} games. Walk {cov.get('walk_s')} s, placebo {cov.get('placebo_s')} s. Trials across "
        f"labs 2-7 after this run: **{doc['n_trials_total']}**.", "",
        f"Deciding markets by sport: {json.dumps(w.get('by_sport', {}))}. Fallback-end markets by sport: "
        f"{json.dumps(fbk.get('by_sport', {}))}.", "",
        f"Placebo: decided for {len(doc['placebo_required'])} cell(s) clearing conditions 1-5; computed as a reading "
        f"for {len(doc['placebo_readings'])} more ({json.dumps(doc.get('placebo_info', {}))}).", "",
    ]
    by = {c["cell"]: c for c in doc["cells"]}
    if doc.get("selected"):
        lines += _cell_detail(by[doc["selected"]], "Selected cell")
    elif doc.get("best"):
        lines += _cell_detail(by[doc["best"]], "Best selectable cell by CI95 lower bound (did not pass)")
    others = [k for k in doc.get("placebo_readings", []) if k != doc.get("best")]
    if others:
        lines += ["## Placebo readings on the other top cells", "",
                  "| cell | n | mean net | placebo mean | placebo p95 | real percentile |", "|---|---|---|---|---|---|"]
        for k in others:
            c = by[k]
            pl = c.get("placebo") or {}
            lines.append(f"| `{_esc(k)}` | {c['summary']['n']} | {_f(c['summary']['mean_net_us'])} | {_f(pl.get('mean'))} | "
                         f"{_f(pl.get('p95'))} | {_f(pl.get('real_percentile'), 1)} |")
        lines.append("")
    refs = [c for c in doc["cells"] if not c["selectable"]]
    if refs:
        lines += ["## Reference cells: the first entry per market held to settlement (reported only)", "",
                  "Would holding to the final whistle have done better than trading out?", "",
                  "| entry rule | n | games | win rate | mean net (US) | CI95 | before fee | mean entry |",
                  "|---|---|---|---|---|---|---|---|"]
        for c in refs:
            s, x = c["summary"], c.get("extra") or {}
            lines.append(f"| `{_esc(c['cell'])}` | {s['n']} | {s.get('n_events', 0)} | {_f(s['win_rate'], 3)} | "
                         f"{_f(s['mean_net_us'])} | {_ci(s['ci95'])} | {_f(x.get('gross_mean'))} | "
                         f"{_f(s['mean_p_entry'], 3)} |")
        lines.append("")
    if doc.get("mirror"):
        lines += ["## Mirror check: momentum vs fade on the same moves (before any fee)", "",
                  "Momentum buys the riser, fade buys the faller, on the same signals. With no skill and no free money "
                  "in the simulator, one's gross gain is roughly the other's gross loss.", "",
                  "| x, y and exits | mom n | fade n | mom gross | fade gross | mom net | fade net |",
                  "|---|---|---|---|---|---|---|"]
        for m in doc["mirror"]:
            lines.append(f"| `{_esc(m['cell'])}` | {m['mom_n']} | {m['fade_n']} | {_f(m['mom_gross'])} | "
                         f"{_f(m['fade_gross'])} | {_f(m['mom_net'])} | {_f(m['fade_net'])} |")
        lines.append("")
    lines += ["## Every cell (games with a recorded end decide)", "",
              "Mean net is per $1 at risk ($20 tickets) under the Polymarket US fee unless named; CI95 by game "
              "bootstrap. Checks, in order: n >= 100, mean > 0, CI95 lower > 0, stress > 0, loss guards, placebo "
              "(`-` = not computed). `fb` = the same cell on games without a recorded end (read apart, never "
              "decides).", "",
              "| cell | n | games | missed | /day | win | mean net | CI95 | com | stress | gross | BE win | win c | "
              "loss c | entry | exits | hold min | max open | DD $ | worst day $ | Sharpe | fb n | fb mean | "
              "placebo p95 | checks | pass |",
              "|" + "---|" * 26]
    lines += [_row(c) for c in doc["cells"]]
    lines += ["",
              "Columns: `BE win` = the win rate the cell's own average win and loss sizes need to break even; `win c` / "
              "`loss c` = cents per contract on wins / losses after the US fee; `entry` = mean entry price; `exits` = "
              "share of exits by reason (tp = take profit, sl = stop, time = the 15 / 45 min time stop, settle = held "
              "to settlement at the game's end, `x->settle` = a triggered exit that found no bid before the market "
              "closed); `hold min` = median minutes from entry to exit; `DD $` = max drawdown of realized P&L; "
              "Sharpe = daily, over every day of the split.", "",
              "Execution (PLAN §4, core.py): the signal is read at a print; the entry fills at the first buy print "
              "for that outcome at least 10 s later (within 10 min, before the end); a take profit or stop fires on "
              "a print at or through its level and sells at the first sell print 10 s later, at that print's price; "
              "a maker take profit fills at its limit only when a buyer trades through it. Fees: Polymarket US "
              "0.0695 x contracts x p x (1 - p) on each taker leg. History is polymarket.com's tape. Paper only; a "
              "pass would only mean 'ready for pretend-money trading on the live desk', never real money.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------- structure


def structure(split: str) -> dict[str, Any]:
    """Universe counts only (no signal, no return)."""
    u = universe(split)
    out: dict[str, Any] = {"markets": len(u), "events": int(u["event_slug"].nunique())}
    for kind in (WHISTLE, FALLBACK):
        g = u[u["end_kind"] == kind]
        dur = (g["end"] - g["start"]) / 60.0
        out[kind] = {"markets": len(g), "events": int(g["event_slug"].nunique()),
                     "by_sport": g["sport"].value_counts().to_dict(),
                     "in_play_min_quantiles": {str(q): round(float(dur.quantile(q)), 1) for q in (0.1, 0.5, 0.9)}
                     if len(g) else {}}
    out["sides"] = (u["side0"] + "/" + u["side1"]).value_counts().to_dict()
    out["rates"] = {str(k): int(v) for k, v in u["rate"].value_counts().items()}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lab 7 W3")
    ap.add_argument("--stage", choices=["train", "val", "test"])
    ap.add_argument("--structure", choices=["train", "val", "test"])
    ap.add_argument("--render", choices=["train", "val", "test"], help="rewrite <stage>.md from <stage>.json only")
    ap.add_argument("--B", type=int, default=C.BOOTSTRAP_B)
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    if a.structure:
        print(json.dumps(structure(a.structure), indent=1, default=str))
    if a.render:
        doc = json.loads((HERE / f"{a.render}.json").read_text())
        (HERE / f"{a.render}.md").write_text(render_md(doc))
    if a.stage:
        run_stage(a.stage, B=a.B, workers=a.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())

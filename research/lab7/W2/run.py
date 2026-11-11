"""Lab 7 W2: crypto up / down windows, convergence to Binance spot (research/lab7/PLAN.md §5 W2; W2/PREREG.md).

The specialist: in a Bitcoin (or ETH / SOL / XRP) "Up or Down" window of 5 minutes, 15 minutes or 1 hour, it buys
the side whose print price is at least ``m`` below lab 5's fair value from Binance spot, takes profit at
``entry + tp`` or at the fair (whichever is lower), cuts the loss at ``entry - sl`` and sells at the window's time
stop (60 s before a 5m / 15m window ends, 300 s before a 1h window ends). Every execution rule is lab 7's shared
simulator (``research/lab7/core.py``); this file only builds the markets, the fair value and the signal, walks the
fixed grid and writes the result files.

* Universe: lab 5's catalogue and universe (``research/lab5/run.py``), window contracts of kind 5m / 15m / 1h on
  BTC / ETH / SOL / XRP, >= 50 fills (lab 7 ``core.load_tape``).
* Fair: ``fair[0, i]`` = lab 5's ``q_event`` probability of Up decided at print i's own second (spot from 1 s candles
  closed by then, 1 h realized variance, Chainlink basis sigma_b from ``research/lab5/structure.json``);
  ``fair[1, i] = 1 - fair[0, i]``.
* Grid: m {0.03, 0.05, 0.08} x tp {0.03, 0.05, 0.08} (fair cap on) x sl {0.05, 0.10, none} x {taker, maker} = 54
  selectable cells, plus 3 reference cells (the first entry per market held to settlement).

CLI (from the repo root)::

    python research/lab7/W2/run.py --stage train
    python research/lab7/W2/run.py --stage val
    LAB7_ALLOW_TEST=1 python research/lab7/W2/run.py --stage test
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import multiprocessing as mp
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
LAB5 = LAB7.parent / "lab5"
if str(LAB7) not in sys.path:
    sys.path.insert(0, str(LAB7))

import core as C  # noqa: E402  (lab 7's shared simulator)


def _load_lab5() -> tuple[Any, Any]:
    """Lab 5's core and run modules under their own names (``lab5_core``, ``lab5_run``): lab 5's run.py does
    ``import core as C`` and ``import data as D``, so those names point at lab 5's files only while it loads; lab 7's
    ``core`` is restored afterwards."""
    if "lab5_run" in sys.modules and "lab5_core" in sys.modules:
        return sys.modules["lab5_core"], sys.modules["lab5_run"]
    saved = {k: sys.modules.get(k) for k in ("core", "data")}
    mods: dict[str, Any] = {}
    try:
        for name, alias in (("core", "lab5_core"), ("data", "lab5_data")):
            spec = importlib.util.spec_from_file_location(alias, LAB5 / f"{name}.py")
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[alias] = mod  # dataclasses resolve their module through sys.modules
            spec.loader.exec_module(mod)
            mods[name] = mod
        sys.modules["core"], sys.modules["data"] = mods["core"], mods["data"]
        spec = importlib.util.spec_from_file_location("lab5_run", LAB5 / "run.py")
        assert spec is not None and spec.loader is not None
        run = importlib.util.module_from_spec(spec)
        sys.modules["lab5_run"] = run
        spec.loader.exec_module(run)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mods["core"], run


L5C, L5R = _load_lab5()

HYP = "W2"
TITLE = "crypto up / down windows: convergence to Binance spot"
PLAN_VERSION = "lab7-v1"
PREREG = HERE / "PREREG.md"
STRUCTURE = LAB5 / "structure.json"
SUBS: dict[str, float] = {"5m": 60.0, "15m": 60.0, "1h": 300.0}  # PLAN §5 W2: time stop = window end minus this
BAND = (0.10, 0.90)
MARGINS = (0.03, 0.05, 0.08)
TPS = (0.03, 0.05, 0.08)
SLS: tuple[float | None, ...] = (0.05, 0.10, None)
TP_MODES = ("taker", "maker")
VOL_S = 3600  # lab 5 S2's primary realized-variance window
RATE_COM = 0.07  # polymarket.com's crypto family rate
MIN_FILLS = 50
PLACEBO_READING_TOP = 1  # PREREG §6: a placebo reading for the best selectable cell by CI95 lower bound (TRAIN)
EXTRA_COLUMNS = ["cell", "sub", "symbol", "fair_sig", "fair_fill"]
REASONS = ("tp", "fair", "sl", "time", "settle", "tp->settle", "fair->settle", "sl->settle", "time->settle")
LEGS = ("taker", "maker", "settle")
NUM_COLUMNS = [
    "o", "t_signal", "p_signal", "t_entry", "p_entry", "shares", "entry_print_size", "t_trigger", "t_exit", "p_exit",
    "late_stop", "hold_s", "fee_us", "fee_com", "fee_stress", "pnl_us", "pnl_com", "pnl_stress", "net_us", "net_com",
    "net_stress", "fair_sig", "fair_fill",
]


# --------------------------------------------------------------------------------------------- cells


def _g(x: float) -> str:
    return f"{x:g}"


def cell_key(m: float, tp: float, sl: float | None, mode: str) -> str:
    return f"m{_g(m)}|tp{_g(tp)}|sl{'none' if sl is None else _g(sl)}|tend|{mode}"


def ref_key(m: float) -> str:
    return f"hold|m{_g(m)}"


@dataclass(frozen=True)
class Cell:
    key: str
    m: float
    exits: C.Exits
    selectable: bool


def all_cells() -> list[Cell]:
    """PLAN §5 W2: 54 selectable cells (m x tp x sl x variant, fair cap on, the window's time stop) + 3 references."""
    out = [
        Cell(cell_key(m, tp, sl, mode), m, C.Exits(tp=tp, sl=sl, tp_mode=mode, fair_exit=True), True)
        for m in MARGINS
        for tp in TPS
        for sl in SLS
        for mode in TP_MODES
    ]
    out += [Cell(ref_key(m), m, C.Exits(hold_to_settlement=True), False) for m in MARGINS]
    return out


CELLS = {c.key: c for c in all_cells()}


# --------------------------------------------------------------------------------------------- universe and markets


def sigma_b() -> float:
    """The Chainlink basis noise lab 5 measured on TRAIN (research/lab5/structure.json), fixed for every split."""
    return float(json.loads(STRUCTURE.read_text())["basis"]["sigma_b"])


def universe(cat: pd.DataFrame, split: str) -> pd.DataFrame:
    """Lab 5's universe (binary, one winner, a parsed contract on BTC / ETH / SOL / XRP, the split), window contracts
    of kind 5m / 15m / 1h. The >= 50 fills rule is applied when the tape is read."""
    u = L5R.universe(cat, split)
    return u[(u["kind"] == "window") & u["sub"].isin(list(SUBS))].reset_index(drop=True)


def fair_of(m5: Any, spot: Any, tape: C.Tape, basis_sd: float) -> np.ndarray:
    """``fair[o, i]``: lab 5's model probability of outcome o decided at print i's own (integer) second, from spot
    candles closed by then (``q_event`` reads the close of the candle opening at ``t - 1`` and the minutes that ended
    by ``t``); NaN where lab 5's model is undefined (before the reference is public, at or after the window end)."""
    t = np.floor(tape.ts).astype(np.int64)
    q = L5C.q_event(m5, spot, t, VOL_S, basis_sd)
    q0 = q if int(m5.contract["event_outcome"]) == 0 else 1.0 - q
    return np.vstack([q0, 1.0 - q0])


def build_market(row: dict[str, Any], spot: Any, basis_sd: float, tape: C.Tape | None = None) -> C.Market | None:
    """One window as lab 7's ``Market`` (PLAN §5 W2, PREREG §2). None when the tape is missing or has < 50 fills."""
    m5 = L5R.to_market(row)
    c = m5.contract
    if tape is None:
        tape = C.load_tape(m5.id, min_fills=MIN_FILLS)
    elif len(tape) < MIN_FILLS:
        tape = None
    if tape is None:
        return None
    t_final = float(c["t_final"])
    stop = t_final - SUBS[c["sub"]]
    return C.Market(
        id=str(m5.id),
        event=m5.cluster,  # lab 5's cluster: the UTC hour of the window end
        split=C.split_of(m5.closed_time),
        tape=tape,
        rate_com=RATE_COM,
        payout=(1.0, 0.0) if int(m5.winner) == 0 else (0.0, 1.0),
        settle_t=float(m5.closed_time),
        hard_end=min(t_final, float(m5.closed_time)),
        entry_windows=((float(c["ref_known"]), stop),),
        entry_deadline=stop,
        end_t=stop,
        end_mode="next",
        fair=fair_of(m5, spot, tape, basis_sd),
        band=BAND,
        info={"sub": c["sub"], "symbol": c["symbol"], "source": c["source"], "t_final": t_final},
    )


def market_trips(mk: C.Market, cells: list[Cell]) -> tuple[pd.DataFrame, dict[str, int]]:
    """Every cell's round trips in one market (signals once per margin, every exit rule walked on them), with the
    readings' extra columns: the fair at the signal print and at the entry fill (both known at those seconds)."""
    sigs = {m: C.gap_signals(mk.tape, mk.fair, m) for m in sorted({c.m for c in cells})}
    frames, missed = [], {}
    ts = mk.tape.ts
    for cell in cells:
        trips, miss = C.walk(mk, sigs[cell.m], cell.exits)
        missed[cell.key] = int(miss)
        if not trips:
            continue
        f = C.trips_frame(trips)
        o = f["o"].to_numpy(dtype=int)
        i_sig = np.searchsorted(ts, f["t_signal"].to_numpy(dtype=float), side="left")
        i_ent = np.searchsorted(ts, f["t_entry"].to_numpy(dtype=float), side="left")
        f["cell"] = cell.key
        f["sub"] = mk.info["sub"]
        f["symbol"] = mk.info["symbol"]
        f["fair_sig"] = mk.fair[o, i_sig]
        f["fair_fill"] = mk.fair[o, i_ent]
        frames.append(f)
    empty = pd.DataFrame(columns=C.TRIP_COLUMNS + EXTRA_COLUMNS)
    return (pd.concat(frames, ignore_index=True) if frames else empty), missed


# --------------------------------------------------------------------------------------------- workers

_SPOTS: dict[str, Any] = {}
_CTX: dict[str, Any] = {}


def _init(ctx: dict[str, Any]) -> None:
    _CTX.update(ctx)


CELL_CODE = {k: i for i, k in enumerate(CELLS)}


def encode(f: pd.DataFrame) -> dict[str, np.ndarray]:
    """A market's trips as numeric arrays (memory: ~4 million round trips on TRAIN); :func:`decode` inverts it."""
    out = {c: f[c].to_numpy(dtype=float) for c in NUM_COLUMNS}
    out["cell"] = f["cell"].map(CELL_CODE).to_numpy(dtype=np.int16)
    out["reason"] = f["reason"].map({r: i for i, r in enumerate(REASONS)}).to_numpy(dtype=np.int8)
    out["exit_leg"] = f["exit_leg"].map({r: i for i, r in enumerate(LEGS)}).to_numpy(dtype=np.int8)
    return out


def decode(arr: dict[str, np.ndarray], mask: np.ndarray, meta: pd.DataFrame, split: str) -> pd.DataFrame:
    """The trips of ``mask`` as lab 7's trip frame (``core.TRIP_COLUMNS``) plus W2's extra columns. ``meta``: one
    row per market index (id, event, sub, symbol)."""
    mi = arr["mi"][mask]
    f = pd.DataFrame({c: arr[c][mask] for c in NUM_COLUMNS})
    f["o"] = f["o"].astype(int)
    f["late_stop"] = f["late_stop"].astype(bool)
    f["id"] = meta["id"].to_numpy()[mi]
    f["event"] = meta["event"].to_numpy()[mi]
    f["split"] = split
    f["reason"] = np.asarray(REASONS, dtype=object)[arr["reason"][mask]]
    f["exit_leg"] = np.asarray(LEGS, dtype=object)[arr["exit_leg"][mask]]
    f["day"] = pd.to_datetime(f["t_exit"], unit="s", utc=True).dt.strftime("%Y-%m-%d").to_numpy()
    f["cell"] = np.asarray(list(CELLS), dtype=object)[arr["cell"][mask]]
    f["sub"] = meta["sub"].to_numpy()[mi]
    f["symbol"] = meta["symbol"].to_numpy()[mi]
    return f[C.TRIP_COLUMNS + EXTRA_COLUMNS]


def _work(row: dict[str, Any]) -> dict[str, Any]:
    c = json.loads(row["contract"])
    mk = build_market(row, _SPOTS[c["symbol"]], _CTX["basis_sd"])
    if mk is None:
        return {"id": row["id"], "skip": "fewer than 50 fills", "arr": None, "missed": {}}
    cells = [CELLS[k] for k in _CTX["cells"]]
    trips, missed = market_trips(mk, cells)
    return {"id": row["id"], "event": mk.event, "skip": None, "arr": encode(trips) if len(trips) else None,
            "missed": missed, "n_prints": len(mk.tape), "late_close": bool(mk.hard_end < mk.end_t)}


def _placebo_work(task: tuple[dict[str, Any], dict[str, int]]) -> dict[str, np.ndarray]:
    """The random-entry placebo for one market and every requested cell: ``core.placebo_matrix`` with a generator
    seeded by (``core.placebo_seed(W2, cell, split)``, crc32 of the market id) so the draw does not depend on the
    worker or the order (PREREG §6)."""
    row, need = task
    c = json.loads(row["contract"])
    mk = build_market(row, _SPOTS[c["symbol"]], _CTX["basis_sd"])
    out: dict[str, np.ndarray] = {}
    if mk is None:
        return out
    for key, n in need.items():
        seed = [C.placebo_seed(HYP, key, _CTX["split"]), zlib.crc32(str(row["id"]).encode())]
        rng = np.random.default_rng(seed)
        out[key] = C.placebo_matrix(mk, int(n), CELLS[key].exits, rng=rng)
    return out


def _pool_map(fn: Any, items: list[Any], procs: int, chunksize: int = 16) -> list[Any]:
    if procs <= 1:
        return [fn(x) for x in items]
    with mp.get_context("fork").Pool(procs, initializer=_init, initargs=(dict(_CTX),)) as pool:
        return list(pool.imap(fn, items, chunksize=chunksize))


def load_context(split: str, cell_keys: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """The split's universe and the spot arrays (loaded ONCE, before forking; PLAN §10)."""
    C.check_split_allowed(split)
    cat = L5R.catalogue()
    u = universe(cat, split)
    _SPOTS.clear()
    _SPOTS.update(L5R.load_spots(sorted(u["symbol"].dropna().unique())))
    _CTX.clear()
    _CTX.update({"basis_sd": sigma_b(), "cells": list(cell_keys), "split": split})
    rates = u["rate"].value_counts().to_dict()
    return u, {"rates": {str(k): int(v) for k, v in rates.items()}}


def evaluate(u: pd.DataFrame, procs: int) -> tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, int], dict[str, Any]]:
    """Every market of the universe through every requested cell. Returns the encoded trips (with ``mi``, the market
    index into ``meta``), ``meta`` (id, event, sub, symbol per market index), missed entries per cell, coverage."""
    rows = u.to_dict("records")
    t0 = time.time()
    res = _pool_map(_work, rows, procs)
    sub_by_id = dict(zip(u["id"].astype(str), u["sub"], strict=True))
    sym_by_id = dict(zip(u["id"].astype(str), u["symbol"], strict=True))
    with_trips = [r for r in res if r["arr"] is not None]
    meta = pd.DataFrame(
        {
            "id": [str(r["id"]) for r in with_trips],
            "event": [r["event"] for r in with_trips],
            "sub": [sub_by_id[str(r["id"])] for r in with_trips],
            "symbol": [sym_by_id[str(r["id"])] for r in with_trips],
        }
    )
    keys = [*NUM_COLUMNS, "cell", "reason", "exit_leg"]
    if with_trips:
        arr = {k: np.concatenate([r["arr"][k] for r in with_trips]) for k in keys}
        arr["mi"] = np.concatenate([np.full(len(r["arr"]["cell"]), i, dtype=np.int32) for i, r in enumerate(with_trips)])
    else:
        arr = {k: np.zeros(0) for k in keys} | {"cell": np.zeros(0, dtype=np.int16), "mi": np.zeros(0, dtype=np.int32)}
    missed: dict[str, int] = {}
    for r in res:
        for k, v in r["missed"].items():
            missed[k] = missed.get(k, 0) + v
    ok = [r for r in res if r["skip"] is None]
    sub_of = dict(zip(u["id"].astype(str), u["sub"], strict=True))
    cov = {
        "markets": len(rows),
        "evaluated": len(ok),
        "skipped_few_fills": len(rows) - len(ok),
        "by_sub": {s: int(sum(1 for r in ok if sub_of[str(r["id"])] == s)) for s in SUBS},
        "by_symbol": {str(k): int(v) for k, v in u[u["id"].astype(str).isin({str(r["id"]) for r in ok})]["symbol"].value_counts().items()},
        "closed_before_time_stop": int(sum(1 for r in ok if r.get("late_close"))),
        "prints_median": float(np.median([r["n_prints"] for r in ok])) if ok else None,
        "seconds": round(time.time() - t0, 1),
    }
    return arr, meta, missed, cov


def placebo_pass(
    u: pd.DataFrame, arr: dict[str, np.ndarray], meta: pd.DataFrame, keys: list[str], procs: int
) -> dict[str, list[np.ndarray]]:
    """One pass over the markets with trips in any of ``keys``; each market's tape is built once. Each market gets
    as many counterparts per draw as it has real round trips in the cell (PLAN §7)."""
    if not keys:
        return {}
    by_id: dict[str, dict[str, int]] = {}
    ids = meta["id"].to_numpy()
    for key in keys:
        mi = arr["mi"][arr["cell"] == CELL_CODE[key]]
        for i, n in zip(*np.unique(mi, return_counts=True), strict=True):
            by_id.setdefault(str(ids[i]), {})[key] = int(n)
    rows = [r for r in u.to_dict("records") if str(r["id"]) in by_id]
    tasks = [(r, by_id[str(r["id"])]) for r in rows]
    res = _pool_map(_placebo_work, tasks, procs, chunksize=8)
    blocks: dict[str, list[np.ndarray]] = {k: [] for k in keys}
    for r in res:
        for k, mat in r.items():
            blocks[k].append(mat)
    return blocks


# --------------------------------------------------------------------------------------------- readings


def breakdown(ct: pd.DataFrame, col: str) -> dict[str, Any]:
    out = {}
    for k, g in ct.groupby(col):
        net = g["net_us"].to_numpy(dtype=float)
        out[str(k)] = {"n": int(len(g)), "win_rate": float((net > 0).mean()), "mean_net_us": float(net.mean()),
                       "total_usd": float(g["pnl_us"].sum())}
    return out


def entry_readings(ct: pd.DataFrame, m: float) -> dict[str, Any]:
    """PREREG §7: how much of the gap survives the 10 s lag. Gap at the signal (fair - signal print), slippage
    (entry fill - signal print), gap left at the fill (fair known at the fill's second - entry price)."""
    if len(ct) == 0:
        return {}
    gs = (ct["fair_sig"] - ct["p_signal"]).astype(float)
    sl = (ct["p_entry"] - ct["p_signal"]).astype(float)
    gf = (ct["fair_fill"] - ct["p_entry"]).astype(float)
    return {
        "gap_at_signal": float(gs.mean()),
        "slippage": float(sl.mean()),
        "gap_at_fill": float(gf.mean()),
        "share_gap_still_m": float((gf >= m - C.EPS).mean()),
        "share_fill_above_fair": float((gf < 0).mean()),
    }


def cell_result(cell: Cell, ct: pd.DataFrame, missed: int, split: str, B: int) -> dict[str, Any]:
    ct = ct.sort_values(["t_entry", "id"], kind="stable").reset_index(drop=True)
    s = C.summarize(ct[C.TRIP_COLUMNS], split, missed=missed, B=B)
    return {
        "cell": cell.key,
        "selectable": cell.selectable,
        "summary": s,
        "checks": C.bar_checks(s),
        "markets_traded": int(ct["id"].nunique()) if len(ct) else 0,
        "by_sub": breakdown(ct, "sub") if len(ct) else {},
        "by_symbol": breakdown(ct, "symbol") if len(ct) else {},
        "entry": entry_readings(ct, cell.m),
    }


def _fmt(v: Any, nd: int = 4) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _pct(v: Any, nd: int = 1) -> str:
    return "-" if v is None else f"{100.0 * float(v):.{nd}f} %"


def _mix(mix: dict[str, float]) -> str:
    return ", ".join(f"{k} {100 * v:.0f}" for k, v in sorted(mix.items(), key=lambda kv: -kv[1])) or "-"


# --------------------------------------------------------------------------------------------- stages


def sha(path: Path) -> str:
    return C.prereg_sha256(path)


def run_stage(stage: str, B: int = C.BOOTSTRAP_B, procs: int = 4) -> dict[str, Any]:
    split = stage
    C.check_split_allowed(split)
    out_json = HERE / f"{stage}.json"
    if stage == "test":
        C.first_test_look(out_json)
    if not PREREG.exists():
        raise RuntimeError("W2/PREREG.md must exist (and be final) before any return is computed (PLAN §10)")
    if stage == "train":
        keys = list(CELLS)
    else:
        prev = json.loads((HERE / ("train.json" if stage == "val" else "val.json")).read_text())
        sel = prev.get("selected")
        if not sel or (stage == "test" and prev.get("verdict") != "SELECTED_ON_VAL"):
            raise RuntimeError(f"{stage.upper()} is not run: the previous stage selected no cell")
        keys = [sel]
    u, ctx_info = load_context(split, keys)
    arr, meta, missed, cov = evaluate(u, procs)
    cov["fee_rates_in_catalogue"] = ctx_info["rates"]
    results = []
    for key in keys:
        cell = CELLS[key]
        ct = decode(arr, arr["cell"] == CELL_CODE[key], meta, split)
        results.append(cell_result(cell, ct, missed.get(key, 0), split, B))
    # PLAN §7: the placebo for every selectable cell that clears conditions 1-5; PREREG §6 readings: the 3 best
    # selectable cells by CI95 lower bound and the 3 reference cells (TRAIN); VAL / TEST: the cell under test.
    required = [r["cell"] for r in results if r["selectable"] and all(r["checks"].values())]
    reading: list[str] = []
    if stage == "train":
        sel_cells = [r for r in results if r["selectable"] and r["summary"]["ci95"][0] is not None]
        top = sorted(sel_cells, key=lambda r: (-r["summary"]["ci95"][0], -r["summary"]["mean_net_us"], r["cell"]))
        reading = [r["cell"] for r in top[:PLACEBO_READING_TOP] if r["cell"] not in required]
        reading += [r["cell"] for r in results if not r["selectable"] and r["summary"]["n"] > 0]
    else:
        reading = [r["cell"] for r in results if r["cell"] not in required and r["summary"]["n"] > 0]
    t0 = time.time()
    blocks = placebo_pass(u, arr, meta, required + reading, procs)
    cov["placebo_seconds"] = round(time.time() - t0, 1)
    for r in results:
        key = r["cell"]
        if key in blocks:
            r["placebo"] = C.placebo_reading(blocks[key], r["summary"]["mean_net_us"])
            r["placebo_why"] = "bar (conditions 1-5 pass)" if key in required else "reading"
        else:
            r["placebo"] = None
        b = C.bar(r["summary"], r["placebo"] if key in required or stage != "train" else None)
        r["bar"] = b
        r["passes"] = bool(b["passes"]) and r["selectable"]
    selected = C.select_one(results) if stage == "train" else None
    if stage == "train":
        verdict = "TRAIN_SELECTED" if selected else "NO_EDGE_TRAIN"
        sel_key = selected["cell"] if selected else None
    else:
        r0 = results[0]
        sel_key = r0["cell"] if r0["passes"] else None
        if stage == "val":
            verdict = "SELECTED_ON_VAL" if r0["passes"] else "FAIL_VAL"
        else:
            verdict = "PASS_TEST" if r0["passes"] else "FAIL_TEST"
    plan_sha, prereg_sha = sha(C.PLAN), sha(PREREG)
    entries = [
        {
            "hyp": HYP,
            "cell": r["cell"],
            "split": split,
            "stage": stage,
            "kind": "selectable" if r["selectable"] else "reference",
            "n": r["summary"]["n"],
            "mean_net_us": r["summary"]["mean_net_us"],
            "ci95": r["summary"]["ci95"],
            "mean_net_stress": r["summary"]["mean_net_stress"],
            "passes": r["passes"],
            "plan_sha256": plan_sha,
            "prereg_sha256": prereg_sha,
        }
        for r in results
    ]
    n_total = C.record_runs(entries)
    doc = {
        "hyp": HYP,
        "title": TITLE,
        "stage": stage,
        "split": split,
        "plan_version": PLAN_VERSION,
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "verdict": verdict,
        "selected": sel_key,
        "cells": results,
        "coverage": cov,
        "sigma_b": sigma_b(),
        "vol_window_s": VOL_S,
        "band": list(BAND),
        "plan_sha256": plan_sha,
        "prereg_sha256": prereg_sha,
        "n_trials_total": n_total,
        "placebo_required": required,
        "placebo_readings": reading,
    }
    if sel_key is not None:
        C.OUT.mkdir(parents=True, exist_ok=True)
        safe = sel_key.replace("|", "_")
        tr = decode(arr, arr["cell"] == CELL_CODE[sel_key], meta, split)
        tr.to_parquet(C.OUT / f"W2_{stage}_{safe}.parquet", index=False, compression="zstd")
        doc["trades_file"] = str(C.OUT / f"W2_{stage}_{safe}.parquet")
    out_json.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    (HERE / f"{stage}.md").write_text(render_md(doc))
    print(f"W2 {stage}: {verdict} {sel_key or ''} (trials across labs 2-7: {n_total})", flush=True)
    return doc


# --------------------------------------------------------------------------------------------- report


def plain_words(doc: dict[str, Any]) -> list[str]:
    stage, verdict = doc["stage"], doc["verdict"]
    cells = doc["cells"]
    sel = [c for c in cells if c["selectable"]]
    with_n = [c for c in sel if c["summary"]["n"] > 0]
    best = max(with_n, key=lambda c: c["summary"]["ci95"][0]) if with_n else None
    pos = sum(1 for c in with_n if (c["summary"]["mean_net_us"] or 0) > 0)
    lines = []
    if stage == "train":
        if verdict == "NO_EDGE_TRAIN":
            lines.append(
                f"**NO EDGE on TRAIN.** None of the {len(sel)} rules passed the bar, so VAL and TEST are not run for W2. "
                f"{pos} of {len(with_n)} rules made money on average after the Polymarket US fee, before asking whether "
                "that was luck."
            )
        else:
            lines.append(f"**TRAIN selected `{doc['selected']}`.** It goes to VAL unchanged.")
    elif stage == "val":
        lines.append(f"**{verdict}** for `{cells[0]['cell']}`.")
    else:
        lines.append(f"**{verdict}** for `{cells[0]['cell']}`.")
    if best is not None:
        s = best["summary"]
        lines.append(
            f"The rule with the best worst-case reading, `{best['cell']}`, traded {s['n']} times "
            f"({s['trips_per_day']:.1f} a day), won {_pct(s['win_rate'])} of them and made {_fmt(s['mean_net_us'])} per "
            f"dollar on average (95 % range {_fmt(s['ci95'][0])} to {_fmt(s['ci95'][1])}); a winner kept "
            f"{_fmt(s['win_cents'], 2)}c per contract and a loser lost {_fmt(s['loss_cents'], 2)}c, so it had to win "
            f"{_pct(s['breakeven_win_rate'])} of the time to break even."
        )
    return lines


def render_md(doc: dict[str, Any]) -> str:
    cov = doc["coverage"]
    cells = doc["cells"]
    L = [
        f"# W2 {doc['title']}: {doc['stage'].upper()} ({doc['split']}, {doc['plan_version']})",
        "",
        *plain_words(doc),
        "",
        f"Verdict: **{doc['verdict']}**" + (f"; selected `{doc['selected']}`." if doc["selected"] else "."),
        "",
        f"Run {doc['utc']}. PLAN.md sha256 `{doc['plan_sha256'][:12]}`, W2/PREREG.md sha256 `{doc['prereg_sha256'][:12]}`. "
        f"Windows in the split: {cov['markets']} (evaluated {cov['evaluated']}, skipped with < 50 fills "
        f"{cov['skipped_few_fills']}; by length {cov['by_sub']}; by symbol {cov['by_symbol']}; closed before the time "
        f"stop {cov['closed_before_time_stop']}; median prints {cov['prints_median']}). Fair: lab 5 `q_event`, 1 h "
        f"variance, Chainlink basis sd {doc['sigma_b']:.6g}; price band {doc['band']}. Trials so far across labs 2-7: "
        f"**{doc['n_trials_total']}**.",
        "",
        "Every round trip is $20, entered as a taker at a real buyable print >= 10 s after the signal, and closed by a "
        "take profit (taker: next bid print >= 10 s after the trigger; maker: resting sell filled only by a "
        "trade-through), a stop (next bid print >= 10 s after the trigger), or the window's time stop. 'net' is profit "
        "per $1 at risk after the Polymarket US taker fee (0.0695 x p x (1 - p) per contract per taker leg; the selector).",
        "",
        "## Every cell",
        "",
        "| cell | n | events | missed | /day | win rate | mean net (US) | CI95 (events) | net com | net stress | "
        "rule-of-3 worst | exit mix % | median hold min | win c | loss c | break-even win | mean entry | small-print share | "
        "bar n/mean/CI/stress/guards/placebo | passes |",
        "|" + "---|" * 20,
    ]
    for c in cells:
        s, ck = c["summary"], c["bar"]["checks"]
        flags = "/".join("Y" if ck[k] else "n" for k in ("n", "mean", "ci_lower", "stress", "loss_guards", "placebo"))
        name = c["cell"] + ("" if c["selectable"] else " (reference)")
        L.append(
            f"| `{name}` | {s['n']} | {s.get('n_events', 0)} | {s['missed']} | {_fmt(s['trips_per_day'], 1)} | "
            f"{_pct(s['win_rate'])} | {_fmt(s['mean_net_us'])} | [{_fmt(s['ci95'][0])}, {_fmt(s['ci95'][1])}] | "
            f"{_fmt(s['mean_net_com'])} | {_fmt(s['mean_net_stress'])} | {_fmt(s['worst_case_net'])} | {_mix(s['exit_mix'])} | "
            f"{_fmt(s['hold_min_median'], 1)} | {_fmt(s['win_cents'], 2)} | {_fmt(s['loss_cents'], 2)} | "
            f"{_pct(s['breakeven_win_rate'])} | {_fmt(s['mean_p_entry'], 3)} | {_pct(s['small_entry_share'])} | {flags} | "
            f"{'PASS' if c['passes'] else '-'} |"
        )
    pl = [c for c in cells if c.get("placebo")]
    L += ["", "## Random-entry placebo (PLAN §7)", ""]
    if pl:
        L += ["| cell | why | draws | placebo mean | placebo p95 | real mean | real percentile | drop share | real > p95 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for c in pl:
            p = c["placebo"]
            beats = p["p95"] is not None and c["summary"]["mean_net_us"] is not None and c["summary"]["mean_net_us"] > p["p95"]
            L.append(
                f"| `{c['cell']}` | {c.get('placebo_why', '')} | {p['draws']} | {_fmt(p['mean'])} | {_fmt(p['p95'])} | "
                f"{_fmt(c['summary']['mean_net_us'])} | {_fmt(p['real_percentile'], 1)} | {_pct(p['drop_share'])} | "
                f"{'yes' if beats else 'no'} |"
            )
    else:
        L.append("No placebo computed.")
    L += [
        "",
        "## Risk book (PLAN §6; a reading, never a selector)",
        "",
        "| cell | total $ | max open | capital $ | $10 daily stop: n / mean net / total $ / days fired | max drawdown $ | "
        "worst day $ | best day $ | daily Sharpe | longest losing streak | worst trip $ |",
        "|" + "---|" * 11,
    ]
    for c in cells:
        s = c["summary"]
        r = s["risk"]
        ds = r["daily_stop"]
        L.append(
            f"| `{c['cell']}` | {_fmt(s['total_usd'], 2)} | {r['max_open']} | {_fmt(r['capital_usd'], 0)} | "
            f"{ds['n']} / {_fmt(ds['mean_net'])} / {_fmt(ds['total_usd'], 2)} / {ds['days_stopped']} | "
            f"{_fmt(r['max_drawdown_usd'], 2)} | {_fmt(r['worst_day_usd'], 2)} | {_fmt(r['best_day_usd'], 2)} | "
            f"{_fmt(r['sharpe_daily'], 2)} | {r['longest_losing_streak']} | {_fmt(r['worst_trip_usd'], 2)} |"
        )
    L += [
        "",
        "## Entry readings (PREREG §7): how much of the gap survives the 10 s lag",
        "",
        "| cell | markets traded | mean gap at signal | mean slippage (fill - signal print) | mean gap left at fill | "
        "fills with gap still >= m | fills above the fair |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in cells:
        e = c.get("entry") or {}
        L.append(
            f"| `{c['cell']}` | {c['markets_traded']} | {_fmt(e.get('gap_at_signal'))} | {_fmt(e.get('slippage'))} | "
            f"{_fmt(e.get('gap_at_fill'))} | {_pct(e.get('share_gap_still_m'))} | {_pct(e.get('share_fill_above_fair'))} |"
        )
    for col, title in (("by_sub", "window length"), ("by_symbol", "symbol")):
        keys = sorted({k for c in cells for k in c[col]})
        L += ["", f"## By {title} (breakdown, never a selector): n / win rate / mean net (US) / total $", "",
              "| cell | " + " | ".join(keys) + " |", "|" + "---|" * (len(keys) + 1)]
        for c in cells:
            vals = []
            for k in keys:
                v = c[col].get(k)
                vals.append("-" if not v else f"{v['n']} / {_pct(v['win_rate'], 0)} / {_fmt(v['mean_net_us'])} / {_fmt(v['total_usd'], 0)}")
            L.append(f"| `{c['cell']}` | " + " | ".join(vals) + " |")
    L += [
        "",
        "Cell key: `m<margin>|tp<take profit>|sl<stop or none>|tend|<taker or maker take profit>`; `tend` = the "
        "window's time stop (60 s before a 5m / 15m window ends, 300 s before a 1h window ends). `hold|m<margin>`: the "
        "first entry per window held to settlement (reported, never selectable). Events for the CI: the UTC hour of the "
        "window end (lab 5's cluster). Exit reasons: tp, fair (the take profit capped at the fair value), sl, time, "
        "settle, and `->settle` when a triggered exit found no bid before the window ended. Paper only; nothing here is "
        "a live trade.",
        "",
    ]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lab 7 W2 stages")
    ap.add_argument("--stage", choices=["train", "val", "test"], required=True)
    ap.add_argument("--B", type=int, default=C.BOOTSTRAP_B)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args(argv)
    run_stage(a.stage, B=a.B, procs=a.procs)
    return 0


if __name__ == "__main__":
    sys.exit(main())

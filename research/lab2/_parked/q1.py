"""Q1 (idea-mill queue q1, DC1): veto R0 entries whose early pool buyers are "dump-cluster" wallets.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Q1/PREREG.md``.

Mechanism
---------
Extraction operators reuse the same wallets as early pool buyers across coins. A wallet that sat in the early top-10
of several EARLIER coins that rugged (RUG = the mid fell >= 80 % over the first post-BOOST half hour) marks the same
playbook; Q1 vetoes the fixed random host R0 (``g1.host_r0``) on coins where >= K such wallets bought early. Busy
wallets (in >= 5 % of the trailing day's lists) are removed first: reuse alone is everywhere, so the rug LABEL is the
signal, and a label-permuted registry is the control that separates "rug history" from "busy wallet".

No lookahead
------------
* Every FEATURE is read through :class:`common.AsOf` (tau = t - 20 s): the early-buyer lists (``w300_top10`` /
  ``w120_top10``, AGENT and pooled / suspect-PDA accounts removed) of the coin being decided and of every structural
  graduate (read at g + 420 s), the G1 class at g + 140 s.
* A registry entry (wallet, earlier coin p) counts at decision t only when p's RUG label window had closed
  (t_lab(p) <= t, all its bars ended before tau), g_p < g_c, and p is not the traded mint (PLAN 6.6 rules 1-2).
  Labels are outcomes, read only through that rule.
* History splits run forward in time (:data:`HISTORY_SPLITS`); CONFIRM never feeds TRAIN.

CLI::

    python research/lab2/q1.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/q1.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/q1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/q1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/q1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/q1.py --stage final
    python research/lab2/q1.py --stage val --check             # prerequisites only

Each stage writes ``Q1/<stage>.json`` and ``Q1/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
VAL without the shortlists, nothing after a kill-gate KILL, TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL
before TEST, PLAN 8 data gates, PREREG frozen after the first official TRAIN run, the pinned R0 host).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import g1 as G1  # noqa: E402

VERSION = "q1-v1"
OUT_DIR = HERE / "Q1"
HYP, HYP_R0, HYP_GATE = "Q1", "Q1.R0", "Q1-gate"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
# PREREG 2.1: RUG labels come only from splits earlier in time and already open at the stage
HISTORY_SPLITS = {"debug": ("final_train",), "train": ("train",), "val": ("train", "val"),
                  "test": ("train", "val", "test"), "confirm": ("confirm",),
                  "final": ("train", "val", "test", "final_train", "final_val", "final_test")}

# =========================================================================== pre-registered constants (PREREG 3-8)
WINDOWS = ("w300", "w120")
LIST_KNOWN_S = float(C.AGENT_WINDOW_S)   # a coin's list is read at tau = g + 420 s (legal, AGENT decided)
EXCLUDED_ACCOUNTS = frozenset(C.POOLED_ACCOUNTS | C.SUSPECT_PDA_ACCOUNTS)
UBIQ_LOOKBACK_S = 86_400.0               # UBIQUITOUS(tau): lists of graduates with g in (tau - 24 h, tau - 420 s]
UBIQ_SHARE = 0.05                        # ... in >= 5 % of them
UBIQ_MIN_LISTS = 2                       # ... and in >= 2 of them (a single list is never "ubiquitous")
REF_AGE_S = float(C.AGENT_WINDOW_S)      # t_ref = first grid time >= g + 420 s (post-BOOST)
RUG_H_S = 1800.0                         # RUG window: t_ref -> t_ref + 30 min
RUG_MULT = 0.20                          # RUG = mid(t_ref + 30 min) <= 0.20 x mid(t_ref)
N_GRID = (3, 5)
D_GRID = (0.6, 0.8)
K_GRID = (1, 3)
D_TOL = 1e-12
# kill gate (PREREG 6)
GATE_WINDOW, GATE_N, GATE_D = "w300", 3, 0.6
GATE_H_S = 3600.0
GATE_MARGIN = -0.05
GATE_LEVEL = 0.90
GATE_MIN = 30
GATE_B = 4000
# controls (PREREG 8)
PERM_N = 20
PERM_BLOCK_S = float(C.BLOCK_S)          # 6-hour blocks of g_p
PERM_MARGIN = 0.05
RANDOM_VETO_DRAWS = 200
# verdict bars
VETO_MIN = int(C.PLAN_MIN["veto_val_flagged"])   # 30 flagged and 30 unflagged
VAL_MIN_SIGN = 5
TEST_MIN_SIGN = 5
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
WARMUP_S = 86_400.0
FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"
# host (PREREG 4) and fills (PREREG 5)
EXIT_BY_AGE_S = 178 * 60.0
SIZE_USD = 20.0
FILL = C.FillConfig(size_usd=SIZE_USD, exit_delay_bars=1)   # worst fills; triggered exits fill in the next bar
STRESS = {"costs_x1.5": FILL.stressed(1.5)}
R0_PIN = "27a79bc60126"                  # == C.params_hash(g1.R0_PARAMS) when this file was written
R0_PARAMS = {**G1.R0_PARAMS, "exit_by_age_s": EXIT_BY_AGE_S, "version": VERSION,
             "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stops, next-bar exits"}

FIXED = {
    "version": VERSION, "host": HYP_R0, "host_params_hash": C.params_hash(R0_PARAMS), "list_known_s": LIST_KNOWN_S,
    "lists": "AsOf.top_buyers(W, exclude_agent=True) at g + 420 s, minus pooled / suspect-PDA accounts, buy SOL > 0",
    "excluded_accounts": sorted(EXCLUDED_ACCOUNTS), "ubiq_lookback_s": UBIQ_LOOKBACK_S, "ubiq_share": UBIQ_SHARE,
    "ubiq_min_lists": UBIQ_MIN_LISTS, "ref_age_s": REF_AGE_S, "rug_h_s": RUG_H_S, "rug_mult": RUG_MULT,
    "label_time": "t_lab = t_ref + 30 min + 20 s; usable at t when t_lab <= t, g_p < g_c, p != mint",
    "history_splits": {k: list(v) for k, v in HISTORY_SPLITS.items()},
    "perm": {"n": PERM_N, "block_s": PERM_BLOCK_S, "margin": PERM_MARGIN}, "veto_min": VETO_MIN,
    "fill": R0_PARAMS["fill"], "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD,
}


def make_params(window: str, n_min: int, d_min: float, k_min: int) -> dict:
    if window not in WINDOWS or n_min not in N_GRID or d_min not in D_GRID or k_min not in K_GRID:
        raise ValueError(f"({window}, N={n_min}, D={d_min}, K={k_min}) is not in the pre-registered grid")
    return {**FIXED, "window": window, "n_min": int(n_min), "d_min": float(d_min), "k_min": int(k_min)}


GRID_W300 = [make_params("w300", n, d, k) for n in N_GRID for d in D_GRID for k in K_GRID]
DEFAULT_BEST = (3, 0.6, 1)               # PREREG 9.4: the most inclusive config when nothing is powered
GATE_PARAMS = {"version": VERSION, "test": "kill_gate", "window": GATE_WINDOW, "n_min": GATE_N, "d_min": GATE_D,
               "h_s": GATE_H_S, "margin": GATE_MARGIN, "level": GATE_LEVEL, "min_obs": GATE_MIN, "fixed": FIXED}
DECL = {"uses_wallet_reputation": True, "reputation_excludes_traded_coin": True, "uses_organic_flow": False,
        "uses_truncated_windows": False, "uses_current_state_fields": False,
        "note": "the reputation is a wallet's mean RUG label over OTHER, earlier, resolved coins"}
DECL_HOST = {"uses_wallet_reputation": False, "uses_organic_flow": False, "uses_current_state_fields": False}


class Q1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['window']}|N{p['n_min']}|D{p['d_min']:g}|K{p['k_min']}"


def host_pin_problems() -> list[str]:
    h = C.params_hash(G1.R0_PARAMS)
    return [] if h == R0_PIN else [f"g1.R0_PARAMS hash {h} != pinned {R0_PIN}: the R0 host changed (new Q1 version)"]


# =========================================================================== host (PREREG 4)


def host_r0(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """``g1.host_r0`` with the shared registered deadline g + 178 min added to its exits (never binds for R0)."""
    e = G1.host_r0(snap, p, pos)
    if isinstance(e, C.Enter):
        return dataclasses.replace(e, exits=dataclasses.replace(e.exits, exit_by_age_s=float(p["exit_by_age_s"])))
    return e


def grid_time_from(cd: C.CoinData, t_min: float) -> float:
    """The first decision-grid time (minute boundary + 20 s) at or after ``t_min``."""
    j = math.ceil((t_min - C.GRID_OFFSET_S - cd.m0) / 60.0 - 1e-9)
    return float(cd.m0 + 60 * j + C.GRID_OFFSET_S)


def r0_decisions(ds: C.Dataset, p: Mapping[str, Any] = R0_PARAMS) -> list[tuple[str, float]]:
    """(mint, t_dec) of every coin where the host ENTERS: its first grid decision at or after the seeded age, alive,
    with room to enter (exactly the engine's rule; checked against the backtest in the tests). No returns read."""
    out = []
    for m in ds.mints:
        cd = ds.coin(m)
        t = max(grid_time_from(cd, cd.g + G1.r0_target_age_s(m, p)), float(cd.bar_start(1) + C.GRID_OFFSET_S))
        if cd.bar_of(t + FILL.latency_s) >= C.N_BARS - 1:
            continue
        if isinstance(host_r0(ds.asof(m, t), p, None), C.Enter):
            out.append((m, t))
    return out


# =========================================================================== lists, ubiquity (structure only)


def appearance_list(snap: C.AsOf, window: str) -> tuple[str, ...] | None:
    """The coin's early-buyer list ``window`` as of snap.tau: AGENT, pooled and suspect-PDA accounts removed, buyers
    with buy SOL > 0 only, duplicates removed. None while the list or AGENT presence is not knowable, or NULL."""
    try:
        lst = snap.top_buyers(window, exclude_agent=True)
    except C.NotYetKnown:
        return None
    if lst is None:
        return None
    out, seen = [], set()
    for w in lst:
        if not w:
            continue
        addr = "" if w[0] is None else str(w[0])
        try:
            b = float(w[1]) if len(w) > 1 and w[1] is not None else 0.0
        except (TypeError, ValueError):
            b = 0.0
        if not addr or addr in EXCLUDED_ACCOUNTS or addr in seen or not b > 0:
            continue
        seen.add(addr)
        out.append(addr)
    return tuple(out)


def structure_row(cd: C.CoinData, sol: C.SolUsd | None = None) -> dict:
    """Both lists of one graduate, read through AsOf at tau = g + 420 s."""
    s = C.AsOf(cd, cd.g + LIST_KNOWN_S + C.DECISION_LAG_S, sol)
    return {"mint": cd.mint, "g": float(cd.g), **{w: appearance_list(s, w) for w in WINDOWS}}


def structure_rows_from_frames(graduates: pd.DataFrame, b2_coins: pd.DataFrame, census: C.Census, lo: float,
                               hi: float) -> list[dict]:
    """Structural pool (PREREG 2.2): every graduate with a b2_coins row (any quote / Mayhem) created in [lo, hi)."""
    g = C._normalize_graduates(graduates, census)
    g = g[(g["created_for_split"] >= lo) & (g["created_for_split"] < hi)]
    b2c = b2_coins.drop(columns=[c for c in ("g_ts", "grad_delay_s", "sol_quoted", "mayhem") if c in b2_coins])
    m = g.merge(b2c, on=["mint", "pool"], how="inner")
    pooled = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
    empty = pd.DataFrame(columns=["minute_ts", "open", "high", "low", "close", "x_close", "y_close"])
    return [structure_row(C._make_coin(r, empty, None, pooled)) for r in m.to_dict("records")]


def structure_rows_from_datasets(datasets: Iterable[C.Dataset]) -> list[dict]:
    return [structure_row(ds.coin(m), ds.sol) for ds in datasets for m in ds.mints]


@dataclass
class Ubiquity:
    """window -> (sorted g of graduates with a known list, wallet -> sorted g of the lists it is in); own lists for
    leaving the decided coin out. A list counts at tau only when g + 420 s <= tau and g > tau - 24 h."""

    by_window: dict[str, tuple[np.ndarray, dict[str, np.ndarray]]]
    own: dict[str, tuple[float, dict[str, frozenset | None]]]
    n_coins: int = 0
    first_g: float | None = None

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> "Ubiquity":
        seen: dict[str, Mapping[str, Any]] = {}
        for r in rows:
            seen.setdefault(str(r["mint"]), r)
        by_window = {}
        for w in WINDOWS:
            allg, per = [], {}
            for r in seen.values():
                lst = r.get(w)
                if lst is None:
                    continue
                allg.append(float(r["g"]))
                for a in set(lst):
                    per.setdefault(a, []).append(float(r["g"]))
            by_window[w] = (np.sort(np.asarray(allg, float)), {a: np.sort(np.asarray(v, float)) for a, v in per.items()})
        own = {m: (float(r["g"]), {w: (None if r.get(w) is None else frozenset(r[w])) for w in WINDOWS})
               for m, r in seen.items()}
        first = min((float(r["g"]) for r in seen.values()), default=None)
        return cls(by_window=by_window, own=own, n_coins=len(seen), first_g=first)

    def _bounds(self, tau: float) -> tuple[float, float]:
        return tau - UBIQ_LOOKBACK_S, tau - LIST_KNOWN_S

    def n_lists(self, window: str, tau: float, mint: str | None = None) -> int:
        lo, hi = self._bounds(tau)
        allg = self.by_window[window][0]
        n = int(np.searchsorted(allg, hi, side="right") - np.searchsorted(allg, lo, side="right"))
        own = self.own.get(mint) if mint is not None else None
        if own is not None and lo < own[0] <= hi and own[1].get(window) is not None:
            n -= 1
        return n

    def ubiquitous(self, wallets: Iterable[str], window: str, tau: float, mint: str | None = None) -> set[str]:
        """The wallets of ``wallets`` that are UBIQUITOUS(tau, window), the coin ``mint`` left out (PREREG 3)."""
        lo, hi = self._bounds(tau)
        per = self.by_window[window][1]
        n = self.n_lists(window, tau, mint)
        need = max(float(UBIQ_MIN_LISTS), UBIQ_SHARE * n)
        own = self.own.get(mint) if mint is not None else None
        own_in = own is not None and lo < own[0] <= hi and own[1].get(window) is not None
        out = set()
        for a in wallets:
            gs = per.get(a)
            if gs is None:
                continue
            c = int(np.searchsorted(gs, hi, side="right") - np.searchsorted(gs, lo, side="right"))
            if own_in and a in own[1][window]:
                c -= 1
            if c >= need:
                out.add(a)
        return out


# =========================================================================== RUG labels and the registry


@dataclass(frozen=True)
class Label:
    """The RUG label of one history graduate (an OUTCOME of that coin, used only as history for later coins)."""

    mint: str
    g: float
    t_ref: float
    t_lab: float
    rug: bool
    ret: float


def label_window(cd: C.CoinData) -> tuple[float, float]:
    t_ref = grid_time_from(cd, cd.g + REF_AGE_S)
    return t_ref, t_ref + RUG_H_S + C.DECISION_LAG_S


def rug_label(ds: C.Dataset, mint: str) -> Label | None:
    """RUG(p) through AsOf at t_ref and t_lab (PREREG 3); None when the window leaves the data or a price is bad."""
    cd = ds.coin(mint)
    t_ref, t_lab = label_window(cd)
    if t_lab - C.DECISION_LAG_S > cd.m0 + 60 * C.N_BARS:
        return None
    p0, p1 = ds.asof(mint, t_ref).price, ds.asof(mint, t_lab).price
    if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and p1 > 0):
        return None
    return Label(mint=mint, g=float(cd.g), t_ref=t_ref, t_lab=t_lab, rug=bool(p1 <= RUG_MULT * p0),
                 ret=float(p1 / p0 - 1.0))


@dataclass
class Registry:
    """Labelled history coins (arrays indexed by coin) and, per list variant, wallet -> coin indices; plus the
    structural ubiquity table. ``y`` holds the RUG labels: never print it on the debug split."""

    coins: pd.DataFrame
    g: np.ndarray
    t_lab: np.ndarray
    mint: np.ndarray
    y: np.ndarray
    block: np.ndarray
    entries: dict[str, dict[str, np.ndarray]]
    ubiq: Ubiquity
    t0: float

    def usable_idx(self, wallet: str, window: str, t: float, g_c: float, mint_c: str) -> np.ndarray:
        """Indices of the wallet's entries usable at decision time t for coin (g_c, mint_c) (PREREG 3 / 11)."""
        idx = self.entries[window].get(wallet)
        if idx is None or not len(idx):
            return np.zeros(0, np.int64)
        ok = (self.t_lab[idx] <= t) & (self.g[idx] < g_c) & (self.mint[idx] != mint_c)
        return idx[ok]

    def record(self, wallet: str, window: str, t: float, g_c: float, mint_c: str,
               y: np.ndarray | None = None) -> tuple[int, float | None]:
        """(n_w, d_w) as of decision t."""
        idx = self.usable_idx(wallet, window, t, g_c, mint_c)
        if not len(idx):
            return 0, None
        yy = self.y if y is None else y
        return int(len(idx)), float(yy[idx].mean())

    def is_warmup(self, t: float) -> bool:
        return bool(t < self.t0 + WARMUP_S)

    def permuted_labels(self, seed: int) -> np.ndarray:
        """RUG labels permuted across labelled coins inside each 6-hour block of g_p (PREREG 8.2)."""
        rng = np.random.default_rng(seed)
        out = self.y.copy()
        for b in np.unique(self.block):
            ix = np.flatnonzero(self.block == b)
            out[ix] = self.y[ix][rng.permutation(len(ix))]
        return out

    def stats(self) -> dict:
        """Counts only (no labels)."""
        out: dict[str, Any] = {"history_coins": int(len(self.coins)), "labelled_coins": int(len(self.y)),
                               "by_split": {str(k): int(v) for k, v in self.coins["split"].value_counts().items()}
                               if len(self.coins) else {},
                               "history_start_utc": C.utc_str(self.t0) if math.isfinite(self.t0) else None,
                               "structure_coins": self.ubiq.n_coins,
                               "structure_with_list": {w: int(len(self.ubiq.by_window[w][0])) for w in WINDOWS}}
        for w in WINDOWS:
            n_ent = np.array([len(v) for v in self.entries[w].values()], int)
            out[w] = {"wallets": int(len(n_ent)), "entries": int(n_ent.sum()) if len(n_ent) else 0,
                      **{f"wallets_ge{n}_entries": int((n_ent >= n).sum()) for n in N_GRID},
                      "max_entries_one_wallet": int(n_ent.max()) if len(n_ent) else 0}
        return out


def build_registry(history: Sequence[C.Dataset], structure_rows: Iterable[Mapping[str, Any]] | None = None) -> Registry:
    """RUG labels and list entries from the usable coins of ``history``; ubiquity from ``structure_rows`` (production:
    every graduate of the structural pool) or, without them, from the history datasets' usable coins."""
    rows = list(structure_rows) if structure_rows is not None else structure_rows_from_datasets(history)
    recs, ent = [], {w: {} for w in WINDOWS}
    seen: set[str] = set()
    t0 = math.inf
    for ds in history:
        for m in ds.mints:
            if m in seen:
                continue
            seen.add(m)
            cd = ds.coin(m)
            t0 = min(t0, cd.g)
            lab = rug_label(ds, m)
            if lab is None:
                continue
            st = structure_row(cd, ds.sol)
            i = len(recs)
            recs.append({"mint": m, "split": cd.split, "g": lab.g, "t_ref": lab.t_ref, "t_lab": lab.t_lab,
                         "rug": lab.rug, **{f"n_{w}": (None if st[w] is None else len(st[w])) for w in WINDOWS}})
            for w in WINDOWS:
                for a in st[w] or ():
                    ent[w].setdefault(a, []).append(i)
    cols = ["mint", "split", "g", "t_ref", "t_lab", "rug"] + [f"n_{w}" for w in WINDOWS]
    coins = pd.DataFrame(recs, columns=cols)
    g = coins["g"].to_numpy(float) if len(coins) else np.zeros(0)
    t_lab = coins["t_lab"].to_numpy(float) if len(coins) else np.zeros(0)
    entries = {w: {a: np.asarray(sorted(ix, key=lambda i: (t_lab[i], i)), np.int64) for a, ix in d.items()}
               for w, d in ent.items()}
    return Registry(coins=coins, g=g, t_lab=t_lab, mint=coins["mint"].to_numpy(object) if len(coins) else np.zeros(0, object),
                    y=coins["rug"].to_numpy(float) if len(coins) else np.zeros(0),
                    block=(g // PERM_BLOCK_S).astype(np.int64), entries=entries, ubiq=Ubiquity.from_rows(rows), t0=t0)


# =========================================================================== features at the decision


def coin_view(snap: C.AsOf, reg: Registry, window: str) -> dict:
    """L(c, tau, W) and each wallet's usable registry entries at snap (PREREG 3). ``known`` False = NULL list."""
    raw = appearance_list(snap, window)
    if raw is None:
        return {"known": False, "n_list": None, "n_ubiq": None, "wallets": [], "idx": []}
    ub = reg.ubiq.ubiquitous(raw, window, snap.tau, snap.mint)
    L = [a for a in raw if a not in ub]
    idx = [reg.usable_idx(a, window, snap.t, snap.g, snap.mint) for a in L]
    return {"known": True, "n_list": len(raw), "n_ubiq": len(ub), "wallets": L, "idx": idx}


def k_of_view(view: Mapping[str, Any], y: np.ndarray, n_min: int, d_min: float) -> int | None:
    """k = number of DUMP wallets (n_w >= N, d_w >= D) in the view; None for a NULL list."""
    if not view["known"]:
        return None
    k = 0
    for ix in view["idx"]:
        if len(ix) >= n_min and float(y[ix].mean()) >= d_min - D_TOL:
            k += 1
    return k


def veto_fires(snap: C.AsOf, reg: Registry, p: Mapping[str, Any], y: np.ndarray | None = None) -> bool:
    """The live rule: k(c, tau, W) >= K. A NULL list never fires."""
    k = k_of_view(coin_view(snap, reg, p["window"]), reg.y if y is None else y, int(p["n_min"]), float(p["d_min"]))
    return k is not None and k >= int(p["k_min"])


@dataclass
class ViewTable:
    """Views of many (mint, t) rows in flat arrays per window, so k for any (N, D, labels) is a few bincounts."""

    n: int
    known: dict[str, np.ndarray]
    n_list: dict[str, np.ndarray]
    n_ubiq: dict[str, np.ndarray]
    n_L: dict[str, np.ndarray]
    pair_row: dict[str, np.ndarray]
    flat_pair: dict[str, np.ndarray]
    flat_coin: dict[str, np.ndarray]

    def k(self, window: str, y: np.ndarray, n_min: int, d_min: float) -> np.ndarray:
        """k per row (NaN for a NULL list)."""
        pr, fp, fc = self.pair_row[window], self.flat_pair[window], self.flat_coin[window]
        n_pairs = len(pr)
        cnt = np.bincount(fp, minlength=n_pairs).astype(float)
        s = np.bincount(fp, weights=y[fc] if len(fc) else np.zeros(0), minlength=n_pairs)
        with np.errstate(invalid="ignore", divide="ignore"):
            d = np.where(cnt > 0, s / np.maximum(cnt, 1.0), np.nan)
        dump = (cnt >= n_min) & (d >= d_min - D_TOL)
        k = np.bincount(pr, weights=dump.astype(float), minlength=self.n).astype(float)
        k[~self.known[window]] = np.nan
        return k

    def flags(self, p: Mapping[str, Any], y: np.ndarray) -> np.ndarray:
        k = self.k(p["window"], y, int(p["n_min"]), float(p["d_min"]))
        return np.where(np.isnan(k), False, k >= int(p["k_min"]))


def build_views(ds: C.Dataset, reg: Registry, rows: Sequence[tuple[str, float]],
                windows: Sequence[str] = WINDOWS) -> ViewTable:
    n = len(rows)
    known, nl, nu, nL, prow, fpair, fcoin = ({w: None for w in windows} for _ in range(7))
    for w in windows:
        kn = np.zeros(n, bool)
        a_nl, a_nu, a_nL = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
        pr, fp, fc = [], [], []
        for i, (m, t) in enumerate(rows):
            v = coin_view(ds.asof(m, float(t)), reg, w)
            if not v["known"]:
                continue
            kn[i] = True
            a_nl[i], a_nu[i], a_nL[i] = v["n_list"], v["n_ubiq"], len(v["wallets"])
            for ix in v["idx"]:
                pid = len(pr)
                pr.append(i)
                fp.extend([pid] * len(ix))
                fc.extend(ix.tolist())
        known[w], nl[w], nu[w], nL[w] = kn, a_nl, a_nu, a_nL
        prow[w], fpair[w], fcoin[w] = (np.asarray(pr, np.int64), np.asarray(fp, np.int64), np.asarray(fc, np.int64))
    return ViewTable(n=n, known=known, n_list=nl, n_ubiq=nu, n_L=nL, pair_row=prow, flat_pair=fpair, flat_coin=fcoin)


def g1_class_of(ds: C.Dataset, mint: str) -> str:
    cd = ds.coin(mint)
    return str(G1.classify(G1.g1_features(ds.asof(mint, cd.g + G1.LABEL_T_S)))["g1_class"])


def annotate(trades: pd.DataFrame, ds: C.Dataset, reg: Registry, configs: Sequence[Mapping[str, Any]],
             views: ViewTable | None = None) -> tuple[pd.DataFrame, ViewTable]:
    """Host trades + the veto's view AT THE DECISION TIME: G1 class, warm-up, list counts, k and flag per config."""
    rows = list(zip(trades["mint"].astype(str), trades["t_dec"].astype(float))) if len(trades) else []
    views = views or build_views(ds, reg, rows)
    t = trades.copy()
    t["g1_class"] = [g1_class_of(ds, m) for m, _ in rows]
    t["warmup"] = [reg.is_warmup(x) for _, x in rows]
    for w in WINDOWS:
        t[f"known_{w}"] = views.known[w]
        t[f"n_list_{w}"], t[f"n_ubiq_{w}"], t[f"n_L_{w}"] = views.n_list[w], views.n_ubiq[w], views.n_L[w]
    for p in configs:
        add_config(t, views, reg, p)
    return t, views


def add_config(t: pd.DataFrame, views: ViewTable, reg: Registry, p: Mapping[str, Any]) -> None:
    key = config_key(p)
    t[f"k_{key}"] = views.k(p["window"], reg.y, int(p["n_min"]), float(p["d_min"]))
    t[f"flag_{key}"] = views.flags(p, reg.y)


def perm_flags(views: ViewTable, reg: Registry, p: Mapping[str, Any]) -> list[np.ndarray]:
    return [views.flags(p, reg.permuted_labels(s)) for s in range(PERM_N)]


# =========================================================================== statistics


def boot_diff(r: np.ndarray, coins: Sequence[Any], a: np.ndarray, b: np.ndarray, level: float = 0.95,
              B: int = 4000, seed: int = 0) -> tuple[float | None, tuple[float, float] | None]:
    """mean(r | a) - mean(r | b) with a coin-cluster bootstrap CI at ``level``."""
    r = np.asarray(r, float)
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    if not a.any() or not b.any():
        return None, None
    diff = float(r[a].mean() - r[b].mean())
    codes, _ = pd.factorize(pd.Series(list(coins)))
    n = int(codes.max()) + 1
    if n < 2:
        return diff, None
    sa = np.bincount(codes, weights=r * a, minlength=n)
    ca = np.bincount(codes, weights=a.astype(float), minlength=n)
    sb = np.bincount(codes, weights=r * b, minlength=n)
    cb = np.bincount(codes, weights=b.astype(float), minlength=n)
    rng = np.random.default_rng(seed)
    out = []
    step = max(1, int(2_000_000 // n))
    for s in range(0, B, step):
        idx = rng.integers(0, n, size=(min(B, s + step) - s, n))
        na, nb = ca[idx].sum(1), cb[idx].sum(1)
        ok = (na > 0) & (nb > 0)
        out.append(sa[idx].sum(1)[ok] / na[ok] - sb[idx].sum(1)[ok] / nb[ok])
    d = np.concatenate(out) if out else np.zeros(0)
    if not len(d):
        return diff, None
    q = (1.0 - level) / 2.0
    return diff, (float(np.quantile(d, q)), float(np.quantile(d, 1.0 - q)))


def _gap(r: np.ndarray, f: np.ndarray) -> float | None:
    f = np.asarray(f, bool)
    if not f.any() or f.all():
        return None
    return float(r[f].mean() - r[~f].mean())


def perm_stats(r: np.ndarray, real: float | None, flags: Sequence[np.ndarray]) -> dict:
    gaps = [g for g in (_gap(r, f) for f in flags) if g is not None]
    pm = float(np.mean(gaps)) if gaps else None
    ok = None if real is None else bool(pm is not None and real <= pm - PERM_MARGIN)
    return {"n_valid": len(gaps), "mean_gap": pm, "flagged_mean_count": float(np.mean([f.sum() for f in flags]))
            if len(flags) else None, "share_le_real": None if real is None or not gaps else
            float(np.mean([g <= real for g in gaps])), "margin": PERM_MARGIN, "pass": ok}


def random_veto(r: np.ndarray, coins: np.ndarray, nf: int, real: float | None, seed: int = 0) -> dict:
    """PREREG 8.1: the same number of trades flagged at random (diagnostic)."""
    n = len(r)
    if real is None or nf <= 0 or nf >= n:
        return {"draws": 0, "p_le_real": None}
    rng = np.random.default_rng(seed)
    gaps = []
    for _ in range(RANDOM_VETO_DRAWS):
        f = np.zeros(n, bool)
        f[rng.choice(n, nf, replace=False)] = True
        gaps.append(float(r[f].mean() - r[~f].mean()))
    return {"draws": RANDOM_VETO_DRAWS, "p_le_real": float(np.mean(np.asarray(gaps) <= real)),
            "random_gap_q05": float(np.quantile(gaps, 0.05))}


def _mean(x: np.ndarray) -> float | None:
    return float(np.mean(x)) if len(x) else None


def veto_eval(t: pd.DataFrame, key: str, *, B: int, hide: bool, perms: Sequence[np.ndarray] | None = None,
              oos: pd.DataFrame | None = None, oos_is_self: bool = False, stress: pd.DataFrame | None = None) -> dict:
    """The veto ``key`` on annotated host trades ``t`` (PREREG 9-10). ``oos`` = out-of-sample host trades carrying the
    same flag column (criterion 2); ``oos_is_self`` (CONFIRM) uses the same never-searched trades for every
    criterion. Debug (``hide``): counts only."""
    fcol = f"flag_{key}"
    f = t[fcol].to_numpy(bool) if len(t) else np.zeros(0, bool)
    window = key.split("|")[0]
    known = t[f"known_{window}"].to_numpy(bool) if len(t) else np.zeros(0, bool)
    out: dict[str, Any] = {"config": key, "n_host": int(len(t)), "n_flagged": int(f.sum()), "n_unflagged": int((~f).sum()),
                           "n_null_list": int((~known).sum()), "n_flagged_warmup": int((f & t["warmup"].to_numpy(bool)).sum())
                           if len(t) else 0}
    if len(t):
        out["flagged_by_class"] = {str(k): int(v) for k, v in t.loc[f, "g1_class"].value_counts().items()}
    if hide:
        return out
    r = t["ret_net"].to_numpy(float) if len(t) else np.zeros(0)
    coins = t["mint"].to_numpy(object) if len(t) else np.zeros(0, object)
    gap = _gap(r, f)
    out.update({"flagged_mean": _mean(r[f]), "unflagged_mean": _mean(r[~f]), "gap": gap,
                "pnl_usd": {"host": float(r.sum() * SIZE_USD), "vetoed_host": float(r[~f].sum() * SIZE_USD)}})
    of = None
    if oos_is_self:
        oos, of = t, f
    elif oos is not None:
        of = oos[fcol].to_numpy(bool) if len(oos) else np.zeros(0, bool)
        ro = oos["ret_net"].to_numpy(float) if len(oos) else np.zeros(0)
        out["oos"] = {"n_host": int(len(oos)), "n_flagged": int(of.sum()), "flagged_mean": _mean(ro[of]),
                      "unflagged_mean": _mean(ro[~of]), "gap": _gap(ro, of)}
    out["verdict"] = C.verdict_veto(t, f, oos_host=oos, oos_flagged=of, B=B) if len(t) else \
        {"verdict": "UNDERPOWERED", "n_flagged": 0, "n_unflagged": 0, "criteria": []}
    c1 = next((c for c in out["verdict"].get("criteria", []) if c.get("id") == 1), None)
    out["ci95"] = (c1 or {}).get("ci95")
    if perms is not None:
        out["perm"] = perm_stats(r, gap, perms)
    out["random_veto"] = random_veto(r, coins, int(f.sum()), gap)
    if len(t):
        warm = t["warmup"].to_numpy(bool)
        d_w, ci_w = boot_diff(r[~warm], coins[~warm], f[~warm], ~f[~warm], 0.95, min(B, 2000)) if (~warm).any() \
            else (None, None)
        out["without_warmup"] = {"n": int((~warm).sum()), "n_flagged": int((f & ~warm).sum()), "gap": d_w, "ci95": ci_w}
        cls = t["g1_class"].astype(str).to_numpy(object)
        out["by_class"] = {c: {"n_flagged": int((f & (cls == c)).sum()), "n_unflagged": int((~f & (cls == c)).sum()),
                               "flagged_mean": _mean(r[f & (cls == c)]), "unflagged_mean": _mean(r[~f & (cls == c)])}
                           for c in sorted(set(cls))}
        org = cls == "ORGANIC"
        d_o, ci_o = boot_diff(r[org], coins[org], f[org], ~f[org], 0.95, min(B, 2000)) if org.any() else (None, None)
        out["organic"] = {"n": int(org.sum()), "n_flagged": int((f & org).sum()), "gap": d_o, "ci95": ci_o}
        wins = r[r > 0].sum()
        out["winning_profit_removed"] = float(r[f & (r > 0)].sum() / wins) if wins > 0 else None
    if stress is not None and len(stress) and len(t):
        fm = dict(zip(t["mint"].astype(str), f))
        sf = np.array([bool(fm.get(str(m), False)) for m in stress["mint"]], bool)
        out["stress_costs_x1.5_gap"] = _gap(stress["ret_net"].to_numpy(float), sf)
    return out


def _crit(ve: Mapping[str, Any], cid: int) -> dict | None:
    for c in ((ve.get("verdict") or {}).get("criteria") or []):
        if c.get("id") == cid:
            return c
    return None


# =========================================================================== kill gate (PREREG 6)


def gate_obs(ds: C.Dataset, reg: Registry, decisions: Sequence[tuple[str, float]] | None = None,
             views: ViewTable | None = None) -> pd.DataFrame:
    """R0 decision coins with a known w300 list: k at the gate registry and the 60-min forward mid change (LABEL)."""
    decisions = list(decisions if decisions is not None else r0_decisions(ds))
    views = views or build_views(ds, reg, decisions, windows=(GATE_WINDOW,))
    k = views.k(GATE_WINDOW, reg.y, GATE_N, GATE_D)
    rows = []
    for i, (m, t) in enumerate(decisions):
        if np.isnan(k[i]):
            continue
        cd = ds.coin(m)
        if t + GATE_H_S - C.DECISION_LAG_S > cd.m0 + 60 * C.N_BARS:
            continue
        p0, p1 = ds.asof(m, t).price, ds.asof(m, t + GATE_H_S).price
        if not (p0 > 0 and p1 > 0 and np.isfinite(p0) and np.isfinite(p1)):
            continue
        kk = int(k[i])
        rows.append({"mint": m, "t_dec": float(t), "k": kk, "bucket": "0" if kk == 0 else ("1-2" if kk <= 2 else ">=3"),
                     "fwd60": float(p1 / p0 - 1.0), "warmup": reg.is_warmup(t), "g1_class": g1_class_of(ds, m)})
    return pd.DataFrame(rows, columns=["mint", "t_dec", "k", "bucket", "fwd60", "warmup", "g1_class"])


def gate_decision(obs: pd.DataFrame, B: int = GATE_B, hide: bool = False) -> dict:
    """PREREG 6: PASS / KILL / UNDERPOWERED. ``hide`` (debug split) returns counts only."""
    n = int(len(obs))
    has = obs["k"].to_numpy(float) >= 1 if n else np.zeros(0, bool)
    out: dict[str, Any] = {"n_obs": n, "n_k_ge1": int(has.sum()), "n_k0": int((~has).sum()),
                           "buckets": {str(k): int(v) for k, v in obs["bucket"].value_counts().items()} if n else {},
                           "n_warmup": int(obs["warmup"].sum()) if n else 0,
                           "need": {"min_each_side": GATE_MIN, "delta_le": GATE_MARGIN,
                                    f"ci{int(GATE_LEVEL * 100)}_hi": "< 0"}}
    if hide:
        out["decision"] = "HIDDEN (debug split: no outcome statistics)"
        return out
    r = obs["fwd60"].to_numpy(float) if n else np.zeros(0)
    coins = obs["mint"].to_numpy(object) if n else np.zeros(0, object)
    d, ci = boot_diff(r, coins, has, ~has, GATE_LEVEL, B) if n else (None, None)
    out.update(delta=d, ci=ci)
    if out["n_k_ge1"] < GATE_MIN or out["n_k0"] < GATE_MIN:
        out["decision"] = "UNDERPOWERED"
    elif d is not None and ci is not None and d <= GATE_MARGIN and ci[1] < 0:
        out["decision"] = "PASS"
    else:
        out["decision"] = "KILL"
    diag: dict[str, Any] = {"mean_by_bucket": {b: float(g["fwd60"].mean()) for b, g in obs.groupby("bucket")}}
    nw = ~obs["warmup"].to_numpy(bool)
    if nw.any():
        diag["delta_without_warmup"] = boot_diff(r[nw], coins[nw], has[nw], ~has[nw], GATE_LEVEL, min(B, 2000))[0]
    cls = obs["g1_class"].astype(str).to_numpy(object)
    diag["delta_by_class"] = {c: _gap_or_none(r[cls == c], has[cls == c]) for c in sorted(set(cls))}
    out["diagnostics"] = diag
    return out


def _gap_or_none(r: np.ndarray, f: np.ndarray) -> float | None:
    return _gap(r, f) if len(r) else None


# =========================================================================== pre-registered decisions (PREREG 9)


def train_row(ve: Mapping[str, Any]) -> dict:
    c1, c3 = _crit(ve, 1), _crit(ve, 3)
    powered = ve["n_flagged"] >= VETO_MIN and ve["n_unflagged"] >= VETO_MIN
    perm_ok = (ve.get("perm") or {}).get("pass") is True
    ci = ve.get("ci95")
    q = bool(powered and c1 and c1["pass"] and c3 and c3["pass"] and perm_ok)
    return {"config": ve["config"], "powered": powered, "qualifies": q, "n_flagged": ve["n_flagged"],
            "n_unflagged": ve["n_unflagged"], "gap": ve.get("gap"), "ci95_hi": ci[1] if ci else None,
            "crit1": None if c1 is None else c1["pass"], "crit3": None if c3 is None else c3["pass"],
            "perm_ok": (ve.get("perm") or {}).get("pass"), "perm_mean_gap": (ve.get("perm") or {}).get("mean_gap")}


def _parse_key(key: str) -> tuple[str, int, float, int]:
    w, n, d, k = key.split("|")
    return w, int(n[1:]), float(d[1:]), int(k[1:])


def train_best(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[int, float, int], str]:
    """PREREG 9.4: the w300 (N, D, K) for the w120 variant, and why."""
    def order(r):
        _, n, d, k = _parse_key(r["config"])
        return (r["ci95_hi"] if r["ci95_hi"] is not None else math.inf, -n, -d, -k)
    q = [r for r in rows if r["qualifies"]]
    if q:
        r = sorted(q, key=order)[0]
        return _parse_key(r["config"])[1:], "qualifying config with the lowest CI upper bound"
    pw = [r for r in rows if r["powered"] and r["ci95_hi"] is not None]
    if pw:
        r = sorted(pw, key=order)[0]
        return _parse_key(r["config"])[1:], "no config qualifies: the powered config with the lowest CI upper bound"
    return DEFAULT_BEST, "no config powered: the most inclusive config"


def decide_train(rows_w300: Sequence[Mapping[str, Any]], best: tuple[int, float, int],
                 row_w120: Mapping[str, Any]) -> dict:
    p_best = make_params("w300", *best)
    best_row = next(r for r in rows_w300 if r["config"] == config_key(p_best))
    sl = []
    if best_row["qualifies"]:
        sl.append(p_best)
    if row_w120["qualifies"]:
        sl.append(make_params("w120", *best))
    dec: dict[str, Any] = {"rows": list(rows_w300) + [dict(row_w120)], "best": config_key(p_best),
                           "w120_config": row_w120["config"]}
    if sl:
        dec.update(verdict="SHORTLISTED", shortlist={HYP: sl, HYP_R0: [R0_PARAMS]},
                   shortlist_hashes={HYP: [C.params_hash(p) for p in sl], HYP_R0: [C.params_hash(R0_PARAMS)]})
        return dec
    if any(r["powered"] for r in rows_w300) or row_w120["powered"]:
        dec.update(verdict="NO_CONFIG", reason="powered vetoes failed criterion 1 / 3 or the label-permuted placebo")
    else:
        dec.update(verdict="UNDERPOWERED_TRAIN",
                   reason=f"no config reached {VETO_MIN} flagged and {VETO_MIN} unflagged R0 trades (max flagged: "
                          f"{max([r['n_flagged'] for r in rows_w300] + [row_w120['n_flagged']])})")
    dec.update(shortlist={}, shortlist_hashes={})
    return dec


def decide_val_one(ve: Mapping[str, Any]) -> dict:
    nf, nu = ve["n_flagged"], ve["n_unflagged"]
    fm, um = ve.get("flagged_mean"), ve.get("unflagged_mean")
    if nf < VAL_MIN_SIGN or fm is None or um is None:
        v = "UNDERPOWERED_VAL"
    elif fm >= um:
        v = "FAIL_VAL"
    elif nf < VETO_MIN or nu < VETO_MIN:
        v = "SELECTED_UNDERPOWERED"
    else:
        c1 = _crit(ve, 1)
        v = "SELECTED" if (c1 and c1["pass"]) else "FAIL_VAL"
    return {"verdict": v, "n_flagged": nf, "n_unflagged": nu, "flagged_mean": fm, "unflagged_mean": um,
            "proceed": v in PROCEED_VAL}


def decide_val(vetoes: Mapping[str, Mapping[str, Any]], order: Sequence[str]) -> dict:
    per = {k: decide_val_one(vetoes[k]) for k in order}
    cand = next((k for k in order if per[k]["proceed"]), None)
    v = per[cand]["verdict"] if cand else (per[order[0]]["verdict"] if order else "UNDERPOWERED_VAL")
    return {"verdict": v, "per_config": per, "candidate": cand, "proceed": cand is not None}


def decide_test(ve: Mapping[str, Any]) -> dict:
    """verdict_veto (VAL in sample, TEST out of sample) + Q1.T: the sign must hold on TEST with >= 5 flagged."""
    base = (ve.get("verdict") or {}).get("verdict")
    o = ve.get("oos") or {}
    sign = None
    if o.get("n_flagged", 0) >= TEST_MIN_SIGN and o.get("flagged_mean") is not None and o.get("unflagged_mean") is not None:
        sign = bool(o["flagged_mean"] < o["unflagged_mean"])
    v = "FAIL" if (base == "FAIL" or sign is False) else base
    return {"verdict": v, "verdict_veto": base, "q1_t_sign_on_test": sign, "test_n_flagged": o.get("n_flagged"),
            "test_gap": o.get("gap")}


def decide_confirm(ve: Mapping[str, Any]) -> dict:
    base = (ve.get("verdict") or {}).get("verdict")
    perm_ok = (ve.get("perm") or {}).get("pass")
    if base == "UNDERPOWERED":
        v = "UNDERPOWERED"
    elif base == "PASS" and perm_ok is True:
        v = "PASS"
    elif base == "FAIL" or perm_ok is False:
        v = "FAIL"
    else:
        v = "INCOMPLETE"
    return {"verdict": v, "verdict_veto": base, "perm_ok": perm_ok}


def final_decision(t: pd.DataFrame, key: str) -> dict:
    """Criterion 9 on the census thirds Q1 never looked at; the debug third is reported apart."""
    def cell(x):
        f = x[f"flag_{key}"].to_numpy(bool) if len(x) else np.zeros(0, bool)
        r = x["ret_net"].to_numpy(float) if len(x) else np.zeros(0)
        return {"n_flagged": int(f.sum()), "n_unflagged": int((~f).sum()), "flagged_mean": _mean(r[f]),
                "unflagged_mean": _mean(r[~f])}
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    j = cell(judged)
    fw = None if j["flagged_mean"] is None or j["unflagged_mean"] is None else bool(j["flagged_mean"] < j["unflagged_mean"])
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), **j, "flagged_worse": fw,
            "per_third": {s: cell(g) for s, g in t.groupby("split")} if len(t) else {},
            "design_third_note": "final_train was the debug third: reported, not judged"}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2) and the common data-contract problems."""
    if not cov.get("usable"):
        return False, ["no usable coins: the backfill has not reached this split yet"]
    notes = []
    if cov.get("chain_hours_scanned_frac", 0) < 0.999:
        notes.append(f"only {cov.get('chain_hours_scanned_frac', 0):.1%} of chain hours scanned")
    for d in cov.get("days", []):
        if d["curve_hours"] < d["hours_in_split"] or d["b2_hours"] < d["hours_in_split"]:
            notes.append(f"{d['day']}: curve {d['curve_hours']}/{d['hours_in_split']} h, "
                         f"B2 {d['b2_hours']}/{d['hours_in_split']} h")
    notes += C.coverage_problems(cov)
    return not notes, notes


def _runs(ledger_path: Path | None) -> list[dict]:
    with C._ledger(ledger_path, write=False) as led:
        return list(led.get("runs", []))


def _shortlist(h: str, shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{h}.json")


def candidate_params(out_dir: Path) -> dict | None:
    va = _read_json(Path(out_dir) / "val.json") or {}
    return (va.get("decision") or {}).get("candidate_params")


def stage_configs(stage: str, out_dir: Path = OUT_DIR, shortlist_path: Path | None = None) -> list[dict]:
    """The veto configs the stage evaluates (TRAIN / debug: the 8 w300 configs; w120 is added in-run)."""
    if stage in ("debug", "train"):
        return list(GRID_W300)
    if stage == "val":
        sl = _shortlist(HYP, shortlist_path)
        return list(sl["configs"]) if sl and sl.get("configs") else []
    c = candidate_params(out_dir)
    return [c] if c else []


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Q1Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Q1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Q1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Q1Refused("PREREG.md changed after the first official TRAIN run; record changes in Q1/AMENDMENTS.md "
                        "as a new version instead")
    pins = host_pin_problems()
    if pins:
        raise Q1Refused("; ".join(pins))
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Q1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Q1Refused("TRAIN already ran on complete data (Q1/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Q1Refused("no TRAIN result (Q1/train.json): run --stage train first")
    if train.get("provisional"):
        raise Q1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    dec = train.get("decision") or {}
    if dec.get("verdict") == "KILLED_GATE":
        raise Q1Refused("Q1 is dead: the kill gate failed on TRAIN (dump-cluster wallets do not predict a worse hour)")
    if dec.get("verdict") != "SHORTLISTED":
        raise Q1Refused(f"TRAIN decision {dec.get('verdict')}: Q1 stopped before VAL")
    want = dec.get("shortlist_hashes") or {}
    for h in (HYP, HYP_R0):
        sl = _shortlist(h, shortlist_path)
        if not sl:
            raise Q1Refused(f"no VAL shortlist for {h} (written by a complete --stage train)")
        if sorted(sl.get("hashes", [])) != sorted(want.get(h, [])):
            raise Q1Refused(f"the {h} shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Q1Refused("VAL already ran (Q1/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise Q1Refused("no VAL result (Q1/val.json): TEST needs a VAL decision first")
    vd = val.get("decision") or {}
    if not vd.get("proceed"):
        raise Q1Refused(f"VAL decision {vd.get('verdict')}: no candidate, Q1 stopped (PLAN 8 rule 7 input)")
    cand = vd.get("candidate_params")
    if not cand or C.params_hash(cand) not in want.get(HYP, []):
        raise Q1Refused("the VAL candidate is not in the Q1 shortlist")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Q1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm" and ((test or {}).get("decision") or {}).get("verdict") == "FAIL":
        raise Q1Refused("the TEST veto decision is FAIL: CONFIRM is not spent")
    if (out_dir / f"{stage}.json").exists():
        raise Q1Refused(f"{stage.upper()} already ran (Q1/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) == C.split_group(split)
           and not r.get("debug") for r in _runs(ledger_path)):
        raise Q1Refused(f"Q1 already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Q1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    return info


# =========================================================================== stage runner


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        x = float(o)
        return None if math.isnan(x) or math.isinf(x) else x
    if isinstance(o, frozenset):
        return sorted(o)
    if o is pd.NA:
        return None
    return o


def _coverage_counts(split: str, flow: Path | None, census: C.Census | None) -> dict:
    if split == "final":
        return {s: C.coverage_dataset(s, flow, census).coverage for s in C.FINAL_SPLITS}
    return C.coverage_dataset(split, flow, census).coverage


def _span_days(ds: C.Dataset) -> float:
    c = ds.coins["created_for_split"] if len(ds) else pd.Series(dtype=float)
    if ds.split in C.SPLIT_BOUNDS and ds.coverage.get("complete"):
        lo, hi = C.SPLIT_BOUNDS[ds.split]
        return (hi - lo) / 86400.0
    return max((float(c.max()) - float(c.min())) / 86400.0, 1e-9) if len(c) else float("nan")


def _hist_bounds(stage: str, census: C.Census) -> tuple[float, float]:
    """[first history split start, stage split end): the structural pool's creation range (PREREG 2.2)."""
    lo = math.inf
    for s in HISTORY_SPLITS[stage]:
        lo = min(lo, float(C.SPLIT_BOUNDS[s][0]) if s in C.SPLIT_BOUNDS else float(C.FINAL_LO))
    split = STAGE_SPLIT[stage]
    if split in C.SPLIT_BOUNDS:
        hi = float(C.SPLIT_BOUNDS[split][1])
    elif split == "final_train":
        hi = float(census.train_hi) + 1.0
    else:
        hi = math.inf
    return lo, hi


def history_datasets(stage: str, ds: C.Dataset, flow: Path | None, census: C.Census | None,
                     history: Sequence[C.Dataset] | None = None) -> list[C.Dataset]:
    """The stage's own dataset plus the other history splits (PREREG 2.1), read for RUG labels only through the
    counts-level loader (never handed to a strategy); each is earlier in time and already open at this stage."""
    if history is not None:
        return [ds] + list(history)
    own = set(C.FINAL_SPLITS) if ds.split == "final" else {ds.split}
    out = [ds]
    for s in HISTORY_SPLITS[stage]:
        if s not in own:
            out.append(C.coverage_dataset(s, flow, census))
    return out


def _check_history(ds: C.Dataset, hist: Sequence[C.Dataset]) -> None:
    for h in hist:
        if h is ds:
            continue
        ok, notes = coverage_check(h.coverage)
        if not ok:
            raise Q1Refused(f"history split {h.split} incomplete: " + "; ".join(notes[:6]))
        try:
            C.check_sol_coverage(h)
        except C.DataNotReady as e:
            raise Q1Refused(f"history split {h.split}: {e}") from e


def event_counts(ds: C.Dataset, decisions: Sequence[tuple[str, float]], views: ViewTable, reg: Registry,
                 configs: Sequence[Mapping[str, Any]], span_days: float) -> dict:
    """Counts only (no prices, no returns, no label values): R0 decisions, list sizes, ubiquity, flags per config."""
    per_day = (lambda x: x / span_days if span_days == span_days and span_days > 0 else None)
    out: dict[str, Any] = {"coins": len(ds), "r0_entries": len(decisions), "r0_entries_per_day": per_day(len(decisions)),
                           "r0_warmup": int(sum(reg.is_warmup(t) for _, t in decisions))}
    for w in WINDOWS:
        kn = views.known[w]
        out[w] = {"known_list": int(kn.sum()),
                  "mean_list_size": _mean(views.n_list[w][kn]), "mean_ubiq_removed": _mean(views.n_ubiq[w][kn]),
                  "with_ubiq_removed": int((views.n_ubiq[w][kn] > 0).sum()),
                  "mean_L_size": _mean(views.n_L[w][kn])}
        for n in N_GRID:
            # wallets of L with >= n usable entries (label-free: counts of resolved appearances only)
            pr, fp = views.pair_row[w], views.flat_pair[w]
            cnt = np.bincount(fp, minlength=len(pr)) if len(pr) else np.zeros(0, int)
            rows_with = np.unique(pr[cnt >= n]) if len(pr) else np.zeros(0, int)
            out[w][f"entries_with_wallet_n_ge{n}"] = int(len(rows_with))
    out["flags"] = {config_key(p): {"n_flagged": int(views.flags(p, reg.y).sum()),
                                    "per_day": per_day(int(views.flags(p, reg.y).sum()))} for p in configs}
    return out


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, history: Sequence[C.Dataset] | None = None,
              structure_rows: Sequence[Mapping[str, Any]] | None = None, census: C.Census | None = None,
              flow: Path | None = None, ledger_path: Path | None = None, shortlist_path: Path | None = None,
              B: int = 4000, env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Q1/<stage>.json + .md (``ds`` / ``history`` / ``structure_rows`` injection
    is for tests: without ``structure_rows`` an injected run builds the ubiquity table from the history)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "q1_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Q1Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise Q1Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for p in configs):
        raise Q1Refused("no configs to run (shortlist or VAL candidate missing)")
    host_p = R0_PARAMS

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                C._check_run_allowed(HYP_R0, host_p, split, ledger_path, shortlist_path)
                for p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Q1Refused(str(e)) from e
        if stage == "train" and not provisional:
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time())}, indent=1))
            if rerun_reason and (out_dir / "train.json").exists():
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for name in ("train.json", "train.md", "train_trades.csv"):
                    p = out_dir / name
                    if p.exists():
                        p.rename(out_dir / name.replace("train", f"train_prev_{stamp}", 1))
        cen = census if census is not None else (C.Census.load() if ds is None else C.Census.empty())
        injected = ds is not None
        if ds is None:
            ds = C.load(split, flow=flow, census=cen, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        hist = history_datasets(stage, ds, flow, cen, history if history is not None else ([] if injected else None))
        if not (debug or _skip_coverage or injected):
            _check_history(ds, hist)
        rows = structure_rows
        if rows is None and not injected:
            lo, hi = _hist_bounds(stage, cen)
            f = Path(flow or C.flow_dir())
            rows = structure_rows_from_frames(C._read_parquet(f / "graduates.parquet"),
                                              C._read_parquet(f / "b2_coins.parquet"), cen, lo, hi)
        reg = build_registry(hist, rows)
        span = _span_days(ds)
        decisions = r0_decisions(ds, host_p)
        views = build_views(ds, reg, decisions)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "q1_py_sha256": _sha(Path(__file__)),
                               "rerun_reason": rerun_reason, "coverage": cov, "n_coins": len(ds), "span_days": span,
                               "history_splits": [h.split for h in hist], "registry": reg.stats(),
                               "host_params_hash": C.params_hash(host_p)}
        # ---- kill gate (PREREG 6): TRAIN (and debug, hidden), before any P&L
        if stage in ("train", "debug"):
            obs = gate_obs(ds, reg, decisions, views)
            gate = gate_decision(obs, B=min(B, GATE_B), hide=debug)
            gate["trial"] = C.record_run(HYP_GATE, GATE_PARAMS, split, {"n": gate["n_obs"], "mean": None},
                                         ledger_path, debug=debug)
            doc["gate"] = gate
            if not debug and gate["decision"] != "PASS":
                v = "KILLED_GATE" if gate["decision"] == "KILL" else "UNDERPOWERED_GATE"
                doc["decision"] = {"verdict": v, "shortlist_written": False,
                                   "note": "PREREG 6: the kill gate precedes any P&L; the host and the grid were not run"}
                return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
        # ---- the host (PREREG 4), one run
        res = C.backtest(host_r0, split, host_p, hypothesis=HYP_R0, ds=ds, cfg=FILL, placebo=False,
                         stress={} if debug else STRESS, declarations=DECL_HOST, ledger_path=ledger_path,
                         shortlist_path=shortlist_path)
        ht = res.trades
        if [(m, float(t)) for m, t in zip(ht["mint"], ht["t_dec"])] != [(m, float(t)) for m, t in decisions]:
            raise AssertionError("r0_decisions disagrees with the host backtest (engine rule changed?)")
        trades, _ = annotate(ht, ds, reg, configs, views)
        doc["host"] = host_report(res, hide=debug, B=B)
        doc["event_counts"] = event_counts(ds, decisions, views, reg, configs, span)
        stress = res.stress.get("costs_x1.5")
        evals: dict[str, dict] = {}
        need_perm = stage in ("train", "debug", "val", "test", "confirm")
        for p in configs:
            key = config_key(p)
            evals[key] = veto_eval(trades, key, B=B, hide=debug,
                                   perms=perm_flags(views, reg, p) if (need_perm and not debug) else None,
                                   oos_is_self=(stage == "confirm"), stress=stress)
        if stage in ("train", "debug"):
            rows_w300 = [train_row(evals[config_key(p)]) for p in configs] if not debug else []
            best, why = (train_best(rows_w300) if not debug else (DEFAULT_BEST, "debug: the fixed default, no outcome read"))
            p120 = make_params("w120", *best)
            add_config(trades, views, reg, p120)
            k120 = config_key(p120)
            evals[k120] = veto_eval(trades, k120, B=B, hide=debug, perms=None if debug else perm_flags(views, reg, p120),
                                    stress=stress)
            doc["event_counts"]["flags"][k120] = {"n_flagged": int(trades[f"flag_{k120}"].sum())}
            doc["train_best"] = {"nkd": list(best), "why": why}
            configs_run = list(configs) + [p120]
        else:
            configs_run = list(configs)
        # ---- out-of-sample comparisons
        if stage == "test":
            key = config_key(configs[0])
            val_t = _read_trades(out_dir, "val")
            if val_t is None or f"flag_{key}" not in val_t:
                raise Q1Refused("VAL trades with the candidate's flags are missing (Q1/val_trades.csv)")
            evals["candidate_vs_val"] = veto_eval(val_t, key, B=B, hide=False, oos=trades)
        # ---- trials: one per veto config (the vetoed host's mean is its summary); debug never counts
        doc["trials"] = {}
        for p in configs_run:
            key = config_key(p)
            f = trades[f"flag_{key}"].to_numpy(bool) if len(trades) else np.zeros(0, bool)
            kept = trades.loc[~f, "ret_net"].to_numpy(float) if len(trades) else np.zeros(0)
            doc["trials"][key] = C.record_run(HYP, p, split, {"n": int(len(trades)), "mean": _mean(kept)}, ledger_path,
                                              debug=debug)
        doc["trials"]["host"] = {k: res.meta.get(k) for k in ("config", "new_trial", "hypothesis_configs")}
        doc["configs"] = {k: v for k, v in evals.items()}
        if not debug:
            _write_trades(out_dir, stage, provisional, trades)
        # ---- decisions
        if debug:
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns, labels and the gate "
                                                           "statistic hidden; w120 run at the fixed default"}
        elif stage == "train":
            row120 = train_row(evals[config_key(make_params("w120", *best))])
            dec = decide_train(rows_w300, best, row120)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                for h in (HYP, HYP_R0):
                    C.write_shortlist(h, dec["shortlist"][h], path=shortlist_path, ledger_path=ledger_path,
                                      note=f"{VERSION}: PREREG 9 TRAIN rule")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            dec = decide_val(evals, [config_key(p) for p in configs])
            dec["candidate_params"] = next((p for p in configs if config_key(p) == dec["candidate"]), None)
            doc["decision"] = dec
        elif stage == "test":
            dec = decide_test(evals["candidate_vs_val"])
            dec["candidate"] = config_key(configs[0])
            doc["decision"] = dec
        elif stage == "confirm":
            dec = decide_confirm(evals[config_key(configs[0])])
            dec["candidate"] = config_key(configs[0])
            doc["decision"] = dec
        elif stage == "final":
            dec = final_decision(trades, config_key(configs[0]))
            dec["candidate"] = config_key(configs[0])
            doc["decision"] = dec
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"q1 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise Q1Refused(str(e)) from e


def host_report(res: C.Result, *, hide: bool, B: int) -> dict:
    t = res.trades
    out: dict[str, Any] = {"hypothesis": res.meta["hypothesis"], "config": res.meta.get("config"), "n": int(len(t)),
                           "n_coins": int(t["mint"].nunique()) if len(t) else 0,
                           "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
                           "auto_rejections_3_6": C.auto_rejections(res)}
    if hide:
        out["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return out
    d = C.describe(t, B=min(B, 2000))
    out.update({k: d.get(k) for k in ("mean", "median", "win_rate", "ci95", "ci90_block", "censored_share",
                                      "mean_without_top2", "reasons", "mean_hold_min")})
    out["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    return out


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, trades: pd.DataFrame) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if not p.exists():
        return None
    t = pd.read_csv(p)
    for c in t.columns:
        if c.startswith("flag_") or c.startswith("known_") or c == "warmup":
            t[c] = t[c].astype(str).str.lower().isin(["true", "1", "1.0"])
    return t


def _finish(doc: dict, out_dir: Path, stage: str, provisional: bool, t0: float, ledger_path: Path | None) -> dict:
    doc["runtime_s"] = round(time.time() - t0, 1)
    doc["n_trials_total"] = C.n_trials(ledger_path)
    doc["overall"] = overall_verdict(out_dir, pending=doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = stage + ("_prelim" if provisional else "")
    doc = _jsonable(doc)
    (out_dir / f"{name}.json").write_text(json.dumps(doc, indent=1, sort_keys=False))
    (out_dir / f"{name}.md").write_text(render_md(doc))
    return doc


def overall_verdict(out_dir: Path, pending: Mapping[str, Any] | None = None) -> str:
    """The hypothesis-level status from every stage written so far (``pending`` = the stage being written)."""
    def doc(s):
        if pending is not None and pending.get("stage") == s and not pending.get("provisional"):
            return pending
        return _read_json(Path(out_dir) / f"{s}.json")

    tr = doc("train")
    if not tr or tr.get("provisional"):
        return "PENDING (no official TRAIN run)"
    tv = (tr.get("decision") or {}).get("verdict")
    if tv == "KILLED_GATE":
        return "KILLED (kill gate: dump-cluster wallets do not predict a worse next hour)"
    if tv == "UNDERPOWERED_GATE":
        return "UNDERPOWERED (kill gate: too few R0 coins with a dump-cluster wallet)"
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)"
    if tv == "NO_CONFIG":
        return "NO VETO (nothing qualified on TRAIN)"
    va = doc("val")
    if not va:
        return "PENDING VAL"
    vd = va.get("decision") or {}
    if not vd.get("proceed"):
        return "UNDERPOWERED (VAL)" if vd.get("verdict") == "UNDERPOWERED_VAL" else "NO VETO (failed VAL)"
    te = doc("test")
    if not te:
        return "PENDING TEST"
    if (te.get("decision") or {}).get("verdict") == "FAIL":
        return "NO VETO (TEST veto FAIL)"
    co = doc("confirm")
    if not co:
        return "PENDING CONFIRM"
    cv = (co.get("decision") or {}).get("verdict")
    if cv == "UNDERPOWERED":
        return "UNDERPOWERED (CONFIRM)"
    if cv != "PASS":
        return f"NO VETO (CONFIRM {cv})"
    fi = doc("final")
    if not fi:
        return "PENDING FINAL"
    return "VETO" if (fi.get("decision") or {}).get("flagged_worse") else "NO VETO (FINAL flagged not worse)"


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    rg = doc.get("registry") or {}
    L = [f"# Q1 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days; "
         f"history: {doc.get('history_splits')}.",
         f"- **Registry (counts):** {rg.get('history_coins')} history coins, {rg.get('labelled_coins')} labelled; "
         f"structural pool {rg.get('structure_coins')} graduates (with a list: {rg.get('structure_with_list')}); "
         f"w300 {rg.get('w300')}; w120 {rg.get('w120')}.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Q1 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, RUG labels and the gate "
              "statistic are hidden and no parameter was chosen here.**", ""]
    g = doc.get("gate")
    if g:
        L += ["## Kill gate (PREREG 6)", "",
              f"- Observations (R0 coins with a known w300 list): {g['n_obs']}; k ≥ 1: {g['n_k_ge1']}, k = 0: "
              f"{g['n_k0']} (need ≥ {GATE_MIN} each); buckets {g.get('buckets')}; warm-up {g.get('n_warmup')}.",
              f"- Decision: **{g['decision']}**."]
        if g.get("delta") is not None:
            L.append(f"- Δ = {_pct(g['delta'])}, {int(GATE_LEVEL * 100)}% CI {_ci(g.get('ci'))} (need Δ ≤ "
                     f"{_pct(GATE_MARGIN)} and CI upper < 0). Diagnostics: {g.get('diagnostics')}.")
        L.append("")
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (no returns)", "",
              f"- R0 entries: {ec['r0_entries']} ({ec.get('r0_entries_per_day') or 0:.1f}/day; warm-up "
              f"{ec.get('r0_warmup')}).",
              f"- w300: {ec.get('w300')}.", f"- w120: {ec.get('w120')}.",
              f"- Flags per config: {ec.get('flags')}.", ""]
    h = doc.get("host") or {}
    if h and not doc.get("debug_only"):
        L += ["## Host Q1.R0", "", f"- n {h.get('n')}, mean {_pct(h.get('mean'))}, 95% CI {_ci(h.get('ci95'))}, "
              f"censored {h.get('censored_share')}, costs ×1.5 {h.get('stress')}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Veto configs", ""]
        if doc.get("debug_only"):
            L += ["| config | host trades | flagged | unflagged | NULL list | flagged warm-up | flagged by G1 class |",
                  "|---|---:|---:|---:|---:|---:|---|"]
            for k, e in cf.items():
                L.append(f"| {k} | {e['n_host']} | {e['n_flagged']} | {e['n_unflagged']} | {e['n_null_list']} | "
                         f"{e['n_flagged_warmup']} | {e.get('flagged_by_class')} |")
        else:
            L += ["| config | flagged / unflagged | flagged mean | unflagged mean | gap [95% CI] | perm mean gap | "
                  "perm ok | won removed | verdict_veto | organic gap | w/o warm-up | costs ×1.5 gap |",
                  "|---|---|---:|---:|---|---:|---|---:|---|---:|---:|---:|"]
            for k, e in cf.items():
                pm = e.get("perm") or {}
                L.append(f"| {k} | {e['n_flagged']} / {e['n_unflagged']} | {_pct(e.get('flagged_mean'))} | "
                         f"{_pct(e.get('unflagged_mean'))} | {_pct(e.get('gap'))} {_ci(e.get('ci95'))} | "
                         f"{_pct(pm.get('mean_gap'))} | {pm.get('pass')} | {_pct(e.get('winning_profit_removed'))} | "
                         f"{(e.get('verdict') or {}).get('verdict')} | {_pct((e.get('organic') or {}).get('gap'))} | "
                         f"{_pct((e.get('without_warmup') or {}).get('gap'))} | "
                         f"{_pct(e.get('stress_costs_x1.5_gap'))} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    if doc.get("train_best"):
        L.append(f"- TRAIN-best (N, D, K) for w120: {doc['train_best']}.")
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: flagged {r['n_flagged']} / unflagged {r['n_unflagged']}, gap {_pct(r['gap'])}, "
                 f"CI upper {_pct(r['ci95_hi'])}, crit1 {r['crit1']}, crit3 {r['crit3']}, perm ok {r['perm_ok']}, "
                 f"qualifies {r['qualifies']}.")
    for key in ("shortlist_written", "candidate", "reason", "note", "q1_t_sign_on_test", "perm_ok", "flagged_worse"):
        if key in dec:
            L.append(f"- {key}: {dec[key]}")
    if dec.get("per_config"):
        L.append(f"- Per config: {dec['per_config']}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Q1 dump-cluster early-wallet veto (idea-mill q1): pre-registered stages; "
                                             "see research/lab2/Q1/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third: mechanics and counts only")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and exit")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial data")
    ap.add_argument("--rerun-reason", help="TRAIN only: re-run an official TRAIN after a data correction")
    ap.add_argument("--B", type=int, default=4000, help="bootstrap draws")
    a = ap.parse_args(argv)
    if not a.stage and not a.debug:
        ap.error("--stage or --debug is required")
    stage = "debug" if a.debug else a.stage
    try:
        if a.check:
            print(json.dumps(check_prereqs(stage, rerun_reason=a.rerun_reason), indent=1))
            return 0
        doc = run_stage(stage, allow_partial=a.allow_partial, rerun_reason=a.rerun_reason, B=a.B)
    except Q1Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

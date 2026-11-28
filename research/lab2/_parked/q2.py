"""Q2 (idea-mill queue item q2, CC1): copycat order and original spillover.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Q2/PREREG.md``.

Three arms on one STRUCTURAL registry (names, symbols, creators, graduation times; never another coin's outcome):

* ``key(s)``: NFKD-folded, case-folded alphanumerics of a coin's symbol and of its name (NULL when empty).
* ``cluster(c)``: pool graduates p != c with g_c - 7 d <= g_p < g_c matching c's symbol key OR name key;
  ``pos(c)`` = |cluster(c)| (NULL when c has no key); ``OG(c)`` = its earliest member; ``copies(o)`` = graduates whose
  OG is o. The pool is every graduate created before the end of the split being run (g1's registry rule).
* **Arm A** (``Q2-veto`` on the R0 host ``Q2-host`` = ``g1.host_r0`` verbatim): skip an R0 entry if pos >= P,
  P in {1, 3}; PLAN 3.5 veto bar via ``common.verdict_veto``; random veto at the same rate (and within G1 class).
* **Arm B** (``Q2``): when a copy m of o graduates, decide at the first grid time >= g_m + 420 s; buy o if alive and
  aged >= 30 min and g_m - g_o <= W (W in {60, 150} min); -50 % stop + 60 min hold or the g_o + 178 min deadline.
  Controls: G1-class-matched random entry (judged), unmatched (reported), event-time placebo (the same OG at quiet
  times, judged).
* **Arm C** (``Q2-dose`` on the R30 host): R30 returns by pos bin {0, 1, 2, >= 3} and G1 class; Spearman dose
  statistic. Reported, never decides.

Every FEATURE of the traded coin is read through :class:`common.AsOf` (cutoff tau = t - 20 s); the registry reads
other graduates' names through AsOf at g + 20 s (z4's structural-pool reader, with g1's pool bound).

CLI::

    python research/lab2/q2.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/q2.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/q2.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/q2.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/q2.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/q2.py --stage final
    python research/lab2/q2.py --stage val --check             # prerequisites only

Each stage writes ``Q2/<stage>.json`` and ``Q2/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlists, TEST / CONFIRM / FINAL once each and only for live branches, never CONFIRM or
FINAL before TEST, PLAN 8 data gates V1-V4, PREREG frozen after the first official TRAIN run, the R0 host pinned).
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
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import g1  # noqa: E402  (the R0 host verbatim, and the G1 class at g + 140 s)

VERSION = "q2-v1"
OUT_DIR = HERE / "Q2"
HYP, HYP_HOST, HYP_VETO, HYP_DOSE = "Q2", "Q2-host", "Q2-veto", "Q2-dose"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
BRANCHES = ("entry", "veto")
ROLE_HOST, ROLE_DOSE, ROLE_CAND = "host_R0", "dose_R30", "candidate"

# =========================================================================== pre-registered constants (PREREG 2-9)
LOOKBACK_S = 7 * 86_400.0           # cluster lookback: 7 days before g_c
EVENT_DELAY_S = float(C.AGENT_WINDOW_S)   # arm B decides at the first grid time >= g_m + 420 s (after m's BOOST)
OG_MIN_AGE_S = 1800.0               # arm B: the OG must be aged >= 30 min at the decision
W_GRID_MIN = (60, 150)              # arm B: g_m - g_OG <= W minutes
EXIT_GRID = ("hold60", "deadline")
P_GRID = (1, 3)                     # arm A: veto if pos >= P
STOP_PCT = 0.50
HOLD_S = 3600.0
EXIT_BY_AGE_S = 178 * 60.0          # registered deadline inside the B2 window
R30_AGE_S = 1800.0
ALIVE_VOL_USD_15M, ALIVE_MCAP_USD = 1500.0, 6000.0
POS_BINS = ("0", "1", "2", "3+")
QUIET_S = 3600.0                    # event-time placebo: no copy graduated in the previous 60 min
EV_DRAWS = 5                        # event-time placebo draws per signal
EV_MIN_MATCHED = 10                 # the event-time comparison needs >= 10 matched signals
LAG_SPLIT_S = 1800.0                # diagnostic: copy within 30 min of the OG or later
LOOKBACK_FULL = 0.99                # diagnostic: >= 99 % of the 168 lookback hours scanned
RANDOM_VETO_DRAWS = 2000
DOSE_B = 2000
G1_CLASS_AGE_S = float(g1.LABEL_T_S)   # 140 s: the G1 class is read at g + 140 s (tau = g + 120 s)
R0_PIN = "27a79bc60126"             # == C.params_hash(g1.R0_PARAMS) when this file was written
# selection and verdict bars
TRAIN_MIN_TRADES = 30
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
VETO_MIN = int(C.PLAN_MIN["veto_val_flagged"])        # 30 flagged and 30 unflagged
DOSE_MIN_BIN = 30
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                                  # PLAN 3.5 item 2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"

FILL = C.FillConfig(exit_delay_bars=1)  # worst fills; every triggered exit fills in the next bar
FILL_DESC = "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits"
STRESS_B = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
            "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0)}
STRESS_HOST = {"costs_x1.5": FILL.stressed(1.5)}

KEY_DEF = {
    "version": VERSION, "lookback_s": LOOKBACK_S,
    "key": "NFKD, drop combining marks, casefold, keep str.isalnum() characters; empty -> NULL; symbol and name",
    "match": "same-field equality of non-NULL symbol keys OR name keys; no cross-field matching",
    "cluster": "pool graduates p != c with g_c - lookback <= g_p < g_c that match c; pos = |cluster|; OG = earliest",
    "pool": "every graduate (any quote, Mayhem included) created before the end of the split being run",
}


def make_params(w_min: int, exit_rule: str) -> dict:
    """Arm B config (PREREG 5)."""
    if w_min not in W_GRID_MIN:
        raise ValueError(f"window {w_min!r} min not in {W_GRID_MIN}")
    if exit_rule not in EXIT_GRID:
        raise ValueError(f"exit {exit_rule!r} not in {EXIT_GRID}")
    return {**KEY_DEF, "arm": "B", "window_min": int(w_min), "window_s": float(w_min) * 60.0, "exit": exit_rule,
            "event_delay_s": EVENT_DELAY_S, "og_min_age_s": OG_MIN_AGE_S, "stop_pct": STOP_PCT,
            "hold_s": HOLD_S if exit_rule == "hold60" else None, "exit_by_age_s": EXIT_BY_AGE_S,
            "alive": "AsOf.alive() defaults", "fill": FILL_DESC,
            "placebo": "alive, decision age +-120 s, same G1 class at g + 140 s; unmatched control reported",
            "event_placebo": {"draws": EV_DRAWS, "quiet_s": QUIET_S, "min_matched": EV_MIN_MATCHED,
                              "ages": "[og_min_age_s, window_s + event_delay_s + 60]"}}


GRID_B = [make_params(w, e) for w in W_GRID_MIN for e in EXIT_GRID]
HOST_PARAMS = {**g1.R0_PARAMS, "q2_version": VERSION, "q2_role": "R0 host of arm A (g1.host_r0 verbatim)",
               "fill": FILL_DESC}
DOSE_PARAMS = {**KEY_DEF, "arm": "C", "host": "R30", "rule": "alive at the first decision >= g + 30 min, else never",
               "age_s": R30_AGE_S, "alive_vol_usd_15m": ALIVE_VOL_USD_15M, "alive_mcap_usd": ALIVE_MCAP_USD,
               "stop_pct": STOP_PCT, "max_hold_s": HOLD_S, "exit_by_age_s": EXIT_BY_AGE_S, "fill": FILL_DESC,
               "bins": list(POS_BINS), "statistic": "Spearman(bin, ret_net), coin-bootstrap 95 % CI",
               "min_bin": DOSE_MIN_BIN, "decides": False}


def veto_params(P: int) -> dict:
    if P not in P_GRID:
        raise ValueError(f"P {P!r} not in {P_GRID}")
    return {**KEY_DEF, "arm": "A", "test": "veto", "flag": f"pos >= {P}", "P": int(P), "host": HOST_PARAMS,
            "population": "R0 trades with known pos", "random_veto_draws": RANDOM_VETO_DRAWS}


DECL = {"uses_wallet_reputation": False, "uses_organic_flow": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False,
        "note": "a structural registry (names, order, timing of other graduates); no other coin's outcome is read"}


class Q2Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"B|W{int(p['window_min'])}|{p['exit']}"


def exits_of(p: Mapping[str, Any]) -> C.ExitSpec:
    return C.ExitSpec(stop_pct=float(p["stop_pct"]), max_hold_s=p.get("hold_s"), exit_by_age_s=float(p["exit_by_age_s"]))


# =========================================================================== small helpers


def _nz(v: Any) -> Any:
    """NULL-like -> None (empty strings and NaN included); NULL is never a value."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def key_of(s: Any) -> str | None:
    """PREREG 2.2: NFKD, combining marks dropped, case-folded, alphanumerics only; empty -> None."""
    s = _nz(s)
    if s is None:
        return None
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch)).casefold()
    k = "".join(ch for ch in folded if ch.isalnum())
    return k or None


def pos_bin(pos: Any) -> str:
    if pos is None or (isinstance(pos, float) and math.isnan(pos)):
        return "unknown"
    p = int(pos)
    return POS_BINS[min(p, 3)]


def grid_time_from(cd: C.CoinData, t_min: float) -> float:
    """The first decision-grid time (minute boundary + 20 s) at or after ``t_min``."""
    j = math.ceil((t_min - C.GRID_OFFSET_S - cd.m0) / 60.0 - 1e-9)
    return float(cd.m0 + 60 * j + C.GRID_OFFSET_S)


def _rank_avg(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    sx = x[order]
    r = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman rank correlation (ties averaged); None when undefined (< 3 pairs or a constant series)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 3:
        return None
    ra, rb = _rank_avg(a), _rank_avg(b)
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return None
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))


# =========================================================================== the structural registry (PREREG 2)


@dataclass(frozen=True)
class Grad:
    mint: str
    g: float
    creator: str | None
    sym: str | None
    name: str | None


@dataclass
class Registry:
    """Structure only: every pool graduate's keys and graduation time. Queries see g_p < g_c only (PREREG 11)."""

    grads: dict[str, Grad]
    by_sym: dict[str, tuple[np.ndarray, list[str]]]
    by_name: dict[str, tuple[np.ndarray, list[str]]]
    lookback_s: float = LOOKBACK_S
    scanned_hours: frozenset | None = None
    first_g: float | None = None
    _cl: dict = field(default_factory=dict, repr=False)
    _copies: dict | None = field(default=None, repr=False)
    _later: dict = field(default_factory=dict, repr=False)
    _ctimes: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]], lookback_s: float = LOOKBACK_S,
                  scanned_hours: Iterable[int] | None = None) -> "Registry":
        grads: dict[str, Grad] = {}
        for r in rows:
            m = str(r["mint"])
            if m in grads:
                continue
            cr = _nz(r.get("creator"))
            grads[m] = Grad(mint=m, g=float(r["g"]), creator=None if cr is None else str(cr),
                            sym=key_of(r.get("symbol")), name=key_of(r.get("name")))
        by_s: dict[str, list[Grad]] = defaultdict(list)
        by_n: dict[str, list[Grad]] = defaultdict(list)
        for gr in grads.values():
            if gr.sym is not None:
                by_s[gr.sym].append(gr)
            if gr.name is not None:
                by_n[gr.name].append(gr)

        def pack(d):
            out = {}
            for k, lst in d.items():
                lst.sort(key=lambda x: (x.g, x.mint))
                out[k] = (np.array([x.g for x in lst], float), [x.mint for x in lst])
            return out
        first = min((gr.g for gr in grads.values()), default=None)
        sh = frozenset(int(h) for h in scanned_hours) if scanned_hours is not None else None
        return cls(grads=grads, by_sym=pack(by_s), by_name=pack(by_n), lookback_s=float(lookback_s),
                   scanned_hours=sh, first_g=first)

    # ------------------------------------------------------------------ per-coin structure
    def keyed(self, mint: str) -> bool:
        gr = self.grads.get(mint)
        return gr is not None and (gr.sym is not None or gr.name is not None)

    def cluster(self, mint: str) -> dict | None:
        """{pos, og, g_og, link, members} for a keyed pool graduate; None when ``mint`` is unknown or unkeyed."""
        if mint in self._cl:
            return self._cl[mint]
        gr = self.grads.get(mint)
        if gr is None or (gr.sym is None and gr.name is None):
            self._cl[mint] = None
            return None
        lo, hi = gr.g - self.lookback_s, gr.g
        via: dict[str, set] = {}
        for k, table, lab in ((gr.sym, self.by_sym, "symbol"), (gr.name, self.by_name, "name")):
            if k is None or k not in table:
                continue
            gs, ms = table[k]
            a, b = int(np.searchsorted(gs, lo, side="left")), int(np.searchsorted(gs, hi, side="left"))
            for m in ms[a:b]:
                if m != mint:
                    via.setdefault(m, set()).add(lab)
        if not via:
            out = {"pos": 0, "og": None, "g_og": None, "link": None, "members": ()}
        else:
            mem = sorted(via, key=lambda m: (self.grads[m].g, m))
            labs = set().union(*via.values())
            link = "both" if len(labs) == 2 else next(iter(labs))
            out = {"pos": len(mem), "og": mem[0], "g_og": self.grads[mem[0]].g, "link": link, "members": tuple(mem),
                   "og_link": "both" if len(via[mem[0]]) == 2 else next(iter(via[mem[0]]))}
        self._cl[mint] = out
        return out

    def pos(self, mint: str) -> int | None:
        cl = self.cluster(mint)
        return None if cl is None else int(cl["pos"])

    def og(self, mint: str) -> str | None:
        cl = self.cluster(mint)
        return None if cl is None else cl["og"]

    def lookback_cov(self, g: float) -> float | None:
        """Share of the 168 whole hours before g's hour that were scanned (None without a scan record)."""
        if self.scanned_hours is None:
            return None
        n_h = int(self.lookback_s // 3600)
        hi = int(g) // 3600 * 3600
        want = range(hi - 3600 * n_h, hi, 3600)
        return float(sum(1 for h in want if h in self.scanned_hours) / max(n_h, 1))

    # ------------------------------------------------------------------ arm B events
    def copies(self, o: str) -> list[tuple[float, str]]:
        """[(g_m, m)] of the pool graduates whose OG is ``o``, sorted by g_m."""
        if self._copies is None:
            d: dict[str, list[tuple[float, str]]] = defaultdict(list)
            for m, gr in self.grads.items():
                cl = self.cluster(m)
                if cl is not None and cl["og"] is not None:
                    d[cl["og"]].append((gr.g, m))
            for v in d.values():
                v.sort()
            self._copies = dict(d)
        return self._copies.get(o, [])

    def copy_times(self, o: str, window_s: float) -> np.ndarray:
        """Graduation times of o's copies with lag <= window (structure; counts and diagnostics only)."""
        ck = (o, float(window_s))
        if ck not in self._ctimes:
            gr = self.grads.get(o)
            self._ctimes[ck] = (np.zeros(0) if gr is None else
                                np.array([g for g, _ in self.copies(o) if g - gr.g <= window_s], float))
        return self._ctimes[ck]

    def due_event(self, o: str, t: float, window_s: float) -> tuple[float, str] | None:
        """The earliest copy of ``o`` (lag <= window) whose decision time is grid time ``t``: g_m + 420 <= t < g_m + 480."""
        gr = self.grads.get(o)
        if gr is None:
            return None
        for g_m, m in self.copies(o):
            if g_m - gr.g <= window_s and g_m + EVENT_DELAY_S <= t < g_m + EVENT_DELAY_S + 60.0:
                return g_m, m
        return None

    def later_same_key(self, o: str) -> np.ndarray:
        """Graduation times of every pool graduate after ``o`` that matches it (event-time placebo quiet rule)."""
        if o in self._later:
            return self._later[o]
        gr = self.grads.get(o)
        out: set[tuple[float, str]] = set()
        if gr is not None:
            for k, table in ((gr.sym, self.by_sym), (gr.name, self.by_name)):
                if k is None or k not in table:
                    continue
                gs, ms = table[k]
                a = int(np.searchsorted(gs, gr.g, side="right"))
                out.update((float(gs[i]), ms[i]) for i in range(a, len(ms)) if ms[i] != o)
        arr = np.array(sorted(g for g, _ in out), float)
        self._later[o] = arr
        return arr


def _structure_of(cd: C.CoinData, sol: C.SolUsd | None = None) -> dict:
    """(name, symbol, creator) read through AsOf at g + 20 s (all legal from creation or g)."""
    s = C.AsOf(cd, cd.g + C.DECISION_LAG_S, sol)
    return {"mint": cd.mint, "g": cd.g, "creator": _nz(s.get("creator")), "name": _nz(s.get("name")),
            "symbol": _nz(s.get("symbol"))}


def structure_rows_from_frames(graduates: pd.DataFrame, census: C.Census, hi: float) -> list[dict]:
    """PREREG 2.1 pool: every graduate (any quote, Mayhem included) created before ``hi``."""
    g = C._normalize_graduates(graduates, census)
    g = g[g["created_for_split"] < hi]
    pooled = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
    empty = pd.DataFrame(columns=["minute_ts", "open", "high", "low", "close", "x_close", "y_close"])
    return [_structure_of(C._make_coin(r, empty, None, pooled)) for r in g.to_dict("records")]


def build_registry(ds: C.Dataset, structure_rows: Iterable[Mapping[str, Any]] | None = None,
                   scanned_hours: Iterable[int] | None = None) -> Registry:
    """Registry from ``structure_rows`` (production: the stage's pool) or, without them, from ``ds``'s own coins."""
    rows = (list(structure_rows) if structure_rows is not None
            else [_structure_of(ds.coin(m), ds.sol) for m in ds.mints])
    if scanned_hours is None:
        scanned_hours = {int(r["g"]) // 3600 * 3600 for r in rows}
    return Registry.from_rows(rows, LOOKBACK_S, scanned_hours)


# =========================================================================== G1 class (PREREG 3)


def g1_classes(ds: C.Dataset) -> dict[str, str]:
    """mint -> G1 class at g + 140 s (tau = g + 120 s), through AsOf."""
    out = {}
    for m in ds.mints:
        cd = ds.coin(m)
        out[m] = g1.classify(g1.g1_features(ds.asof(m, cd.g + G1_CLASS_AGE_S), None))["g1_class"]
    return out


# =========================================================================== strategies, placebos


def host_r30(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """R30 (arm C host): at the first decision >= g + 30 min, enter if alive, else never trade the coin."""
    if pos is not None:
        return None
    if snap.age_s < p["age_s"]:
        return None
    if snap.alive(p["alive_vol_usd_15m"], p["alive_mcap_usd"]):
        return C.Enter(exits=C.ExitSpec(stop_pct=p["stop_pct"], max_hold_s=p["max_hold_s"],
                                        exit_by_age_s=p["exit_by_age_s"]), tag="R30")
    return C.SKIP


def make_strategy(reg: Registry):
    """Arm B for common.backtest: buy the OG at the decision of a copy's graduation event (PREREG 5)."""

    def q2_strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
        if pos is not None:
            return None                                   # exits are mechanical only
        w = float(p["window_s"])
        # due = a copy m with g_m + 420 <= t < g_m + 480 (so g_m <= tau - 400: already graduated and known)
        due = reg.due_event(snap.mint, snap.t, w)
        if due is not None and snap.age_s >= OG_MIN_AGE_S and snap.alive():
            g_m, m = due
            first = reg.copies(snap.mint)[0][1] == m      # o's first copy (earlier than m, so also known)
            return C.Enter(exits=exits_of(p), tag="copy1" if first else "copy2+",
                           state={"copy": m, "lag_s": g_m - snap.g})
        if snap.age_s >= w + EVENT_DELAY_S + 60.0:
            return C.SKIP                                 # g_m <= g_o + W: no event can come due any more
        return None

    return q2_strategy


def placebo_alive(snap: C.AsOf) -> bool:
    return snap.alive()


def make_stratum(cls_map: Mapping[str, str]):
    def g1_class(snap: C.AsOf) -> str | None:
        """The matched placebo draws coins of the signal's G1 class (at g + 140 s)."""
        return cls_map.get(snap.mint)
    return g1_class


PLACEBO_CONTROLS = {"unmatched": {"eligible": placebo_alive, "strata": None}}


def event_placebo_entries(ds: C.Dataset, reg: Registry, trades: pd.DataFrame, p: Mapping[str, Any],
                          seed: int = 0) -> list[tuple[str, float, C.Enter]]:
    """PREREG 8: per signal (o, t), up to 5 random grid times t' of the same coin with age in [30 min, W + 8 min],
    o alive at t', and no graduate matching o (after g_o) in (t' - 60 min, t']."""
    out: list[tuple[str, float, C.Enter]] = []
    ex = exits_of(p)
    hi_age = float(p["window_s"]) + EVENT_DELAY_S + 60.0
    for si, r in enumerate(trades.itertuples(index=False)):
        o = r.mint
        cd = ds.coin(o)
        later = reg.later_same_key(o)
        cands = []
        for k in range(1, C.N_BARS):
            t = float(cd.m0 + 60 * k + C.GRID_OFFSET_S)
            age = t - cd.g
            if age < OG_MIN_AGE_S or age > hi_age:
                continue
            if cd.bar_of(t + FILL.latency_s) >= C.N_BARS - 1:
                continue
            if len(later) and bool(((later > t - QUIET_S) & (later <= t)).any()):
                continue
            if not ds.asof(o, t).alive():
                continue
            cands.append(t)
        if not cands:
            continue
        rng = np.random.default_rng([seed, int(p["window_min"]), EXIT_GRID.index(p["exit"]), si])
        pick = rng.choice(np.array(cands), size=min(EV_DRAWS, len(cands)), replace=False)
        out.extend((o, float(t), C.Enter(exits=ex, tag="event_placebo")) for t in sorted(pick))
    return out


def event_compare(trades: pd.DataFrame, ev: pd.DataFrame, B: int, hide: bool) -> dict:
    """Signal return minus the mean of its own event-time placebo returns (one signal per OG coin per config)."""
    n_sig = int(len(trades))
    pm = ev.groupby("mint")["ret_net"].mean() if len(ev) else pd.Series(dtype=float)
    have = trades["mint"].isin(pm.index).to_numpy(bool) if n_sig else np.zeros(0, bool)
    out: dict[str, Any] = {"n_signals": n_sig, "n_matched": int(have.sum()), "n_placebo": int(len(ev)),
                           "computable": bool(have.sum() >= EV_MIN_MATCHED)}
    if hide:
        return out
    if have.any():
        mints = trades.loc[have, "mint"].to_numpy(object)
        d = trades.loc[have, "ret_net"].to_numpy(float) - pm.reindex(mints).to_numpy(float)
        out.update({"placebo_mean": float(ev["ret_net"].mean()), "mean_diff": float(d.mean()),
                    "diff_ci95": C.coin_bootstrap_ci(d, mints, 0.95, B)})
    else:
        out.update({"placebo_mean": None, "mean_diff": None, "diff_ci95": None})
    return out


# =========================================================================== trade annotations (structure only)


def annotate_hosts(trades: pd.DataFrame, reg: Registry, cls_map: Mapping[str, str]) -> pd.DataFrame:
    """pos, bin, link, G1 class and lookback coverage of each host trade's coin (all fixed at g + 140 s)."""
    rows = []
    for r in trades.itertuples(index=False):
        cl = reg.cluster(r.mint)
        cov = reg.lookback_cov(float(r.g_ts))
        rows.append({"pos": None if cl is None else int(cl["pos"]), "pos_bin": pos_bin(None if cl is None else cl["pos"]),
                     "link": None if cl is None else cl["link"], "g1_class": cls_map.get(r.mint),
                     "lookback_full": None if cov is None else bool(cov >= LOOKBACK_FULL)})
    return pd.DataFrame(rows, columns=["pos", "pos_bin", "link", "g1_class", "lookback_full"], index=trades.index)


def annotate_b(trades: pd.DataFrame, ds: C.Dataset, reg: Registry, cls_map: Mapping[str, str],
               window_s: float) -> pd.DataFrame:
    """Per arm-B trade: the copy that triggered it, lag, OG's own pos, link, G1 class and creator (at t_dec)."""
    rows = []
    for r in trades.itertuples(index=False):
        due = reg.due_event(r.mint, float(r.t_dec), window_s)
        g_m, m = due if due is not None else (None, None)
        cm = reg.cluster(m) if m is not None else None
        own = reg.pos(r.mint)
        cr = _nz(ds.asof(r.mint, float(r.t_dec)).get("creator"))
        rows.append({"copy": m, "lag_s": None if g_m is None else g_m - float(r.g_ts),
                     "og_pos": own, "copy_link": None if cm is None else cm.get("og_link"),
                     "g1_class": cls_map.get(r.mint), "creator": cr if cr is not None else f"m:{r.mint}"})
    return pd.DataFrame(rows, columns=["copy", "lag_s", "og_pos", "copy_link", "g1_class", "creator"],
                        index=trades.index)


# =========================================================================== scans (counts only)


def event_counts(ds: C.Dataset, reg: Registry, cls_map: Mapping[str, str], span_days: float) -> dict:
    """Structure counts on the split's usable coins (no prices, no returns)."""
    per_day = (lambda x: x / span_days if span_days == span_days and span_days > 0 else None)
    bins = {b: 0 for b in POS_BINS + ("unknown",)}
    by_cls: dict[str, dict[str, int]] = defaultdict(lambda: {b: 0 for b in POS_BINS + ("unknown",)})
    links: dict[str, int] = defaultdict(int)
    full = n_cov = 0
    og_any = {w: 0 for w in W_GRID_MIN}
    pairs = {w: 0 for w in W_GRID_MIN}
    first_lag = {"<=7min": 0, "7-30min": 0, "30-60min": 0, "60-150min": 0, ">150min": 0}
    for m in ds.mints:
        cl = reg.cluster(m)
        b = pos_bin(None if cl is None else cl["pos"])
        bins[b] += 1
        by_cls[str(cls_map.get(m))][b] += 1
        if cl is not None and cl["pos"] > 0:
            links[str(cl["link"])] += 1
        cov = reg.lookback_cov(ds.coin(m).g)
        if cov is not None:
            n_cov += 1
            full += int(cov >= LOOKBACK_FULL)
        cps = reg.copies(m)
        g_o = ds.coin(m).g
        for w in W_GRID_MIN:
            k = sum(1 for g, _ in cps if g - g_o <= w * 60.0)
            pairs[w] += k
            og_any[w] += int(k > 0)
        if cps:
            lag = (cps[0][0] - g_o) / 60.0
            lab = ("<=7min" if lag <= 7 else "7-30min" if lag <= 30 else "30-60min" if lag <= 60
                   else "60-150min" if lag <= 150 else ">150min")
            first_lag[lab] += 1
    n_pool = len(reg.grads)
    keyed = sum(1 for gr in reg.grads.values() if gr.sym is not None or gr.name is not None)
    return {"coins": len(ds), "pos_bins": bins, "pos_bins_by_g1": {k: dict(v) for k, v in sorted(by_cls.items())},
            "link_of_copies": dict(links), "lookback_full": full, "lookback_known": n_cov,
            "og_with_copy_in_W": {f"{w}min": og_any[w] for w in W_GRID_MIN},
            "og_with_copy_in_W_per_day": {f"{w}min": per_day(og_any[w]) for w in W_GRID_MIN},
            "copy_events_in_W": {f"{w}min": pairs[w] for w in W_GRID_MIN},
            "first_copy_lag": first_lag,
            "pool": {"graduates": n_pool, "keyed": keyed, "null_keys": n_pool - keyed,
                     "symbol_keys": len(reg.by_sym), "name_keys": len(reg.by_name),
                     "first_g_utc": C.utc_str(reg.first_g)}}


# =========================================================================== evaluation


def _means_by(t: pd.DataFrame, labels: Sequence[Any]) -> dict:
    if not len(t):
        return {}
    s = pd.Series(t["ret_net"].to_numpy(float)).groupby(np.asarray([str(x) for x in labels], object))
    return {str(k): {"n": int(len(g)), "mean": float(g.mean())} for k, g in s}


def _counts_by(labels: Sequence[Any]) -> dict:
    return {str(k): int(v) for k, v in pd.Series([str(x) for x in labels]).value_counts().sort_index().items()}


def _creator_stats(t: pd.DataFrame, creators: Sequence[Any], B: int) -> dict:
    if not len(t):
        return {"n_creators": 0, "ci90_creator": None, "best_creator": None, "mean_without_best_creator": None}
    r = t["ret_net"].to_numpy(float)
    k = np.asarray(list(creators), object)
    prof = pd.Series(r).groupby(k).sum()
    best = sorted(prof.index, key=lambda x: (-float(prof[x]), str(x)))[0]
    rest = r[k != best]
    return {"n_creators": int(len(prof)), "ci90_creator": C.coin_bootstrap_ci(r, k, 0.90, B),
            "best_creator": {"trades": int((k == best).sum()), "profit": float(prof[best])},
            "mean_without_best_creator": float(rest.mean()) if len(rest) else None}


def evaluate_b(res: C.Result, info: pd.DataFrame, evc: Mapping[str, Any], *, B: int, hide: bool,
               n_trials_total: int | None) -> dict:
    """Per arm-B config report. Debug split: counts only."""
    t = res.trades
    p = res.meta["params"]
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "tags": t["tag"].value_counts().to_dict() if len(t) else {},
            "by_g1_counts": _counts_by(info["g1_class"]) if len(t) else {},
            "n_creators": int(info["creator"].nunique()) if len(t) else 0,
            "n_placebo": int(len(res.placebo)),
            "placebo_draws_per_signal": float(len(res.placebo) / len(t)) if len(t) else None,
            "event_placebo": dict(evc), "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "ci90_block", "ci95_block",
                                        "n_blocks", "censored_share", "top_coin_share", "top3_coin_share",
                                        "mean_without_top2", "halves", "mean_hold_min", "deflated_sharpe")})
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    pu = res.controls.get("unmatched") if res.controls else None
    base["placebo_unmatched"] = C.placebo_compare(t, pu, B=B) if pu is not None and len(pu) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["creators"] = _creator_stats(t, info["creator"], B)
    if len(t):
        lag = info["lag_s"].astype(float)
        base["diagnostics"] = {
            "by_tag": _means_by(t, t["tag"]),
            "by_lag": _means_by(t, np.where(lag <= LAG_SPLIT_S, "lag<=30min", "lag>30min")),
            "by_og_pos": _means_by(t, [_og_pos_label(x) for x in info["og_pos"]]),
            "by_link": _means_by(t, info["copy_link"]),
            "by_g1": _means_by(t, info["g1_class"]),
        }
    else:
        base["diagnostics"] = {}
    return base


def _og_pos_label(x: Any) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "unknown"
    return "og_pos=0" if int(x) == 0 else "og_pos>=1"


def _known(t: pd.DataFrame) -> np.ndarray:
    return t["pos"].notna().to_numpy(bool) if len(t) else np.zeros(0, bool)


def _flags(t: pd.DataFrame, P: int) -> np.ndarray:
    return (t["pos"].astype(float).to_numpy() >= P) if len(t) else np.zeros(0, bool)


def random_veto(r: np.ndarray, f: np.ndarray, classes: Sequence[Any], n: int = RANDOM_VETO_DRAWS,
                seed: int = 0) -> dict | None:
    """PREREG 8: the observed flagged - unflagged difference against random relabelings with the same flagged count
    (all trades, and within G1 class). p = share of random vetoes at least as good (difference <= observed)."""
    r, f = np.asarray(r, float), np.asarray(f, bool)
    nf = int(f.sum())
    if nf == 0 or nf == len(f):
        return None
    obs = float(r[f].mean() - r[~f].mean())
    cls = np.asarray([str(c) for c in classes], object)
    groups = [np.where(cls == c)[0] for c in sorted(set(cls.tolist()))]
    rng = np.random.default_rng(seed)
    null, null_c = np.empty(n), np.empty(n)
    for i in range(n):
        pf = rng.permutation(f)
        null[i] = r[pf].mean() - r[~pf].mean()
        fc = f.copy()
        for idx in groups:
            fc[idx] = rng.permutation(f[idx])
        null_c[i] = r[fc].mean() - r[~fc].mean()
    return {"diff": obs, "p_random": float((null <= obs).mean()), "p_within_g1": float((null_c <= obs).mean()),
            "null_mean": float(null.mean()), "null_within_g1_mean": float(null_c.mean()), "draws": n}


def _split_means(r: np.ndarray, f: np.ndarray, sel: np.ndarray) -> dict:
    return {"n_flagged": int((f & sel).sum()), "n_unflagged": int((~f & sel).sum()),
            "flagged_mean": float(r[f & sel].mean()) if (f & sel).any() else None,
            "unflagged_mean": float(r[~f & sel].mean()) if (~f & sel).any() else None}


def veto_eval(host: pd.DataFrame, P: int, *, B: int, hide: bool, oos: pd.DataFrame | None = None,
              oos_is_self: bool = False, stress_host: pd.DataFrame | None = None) -> dict:
    """Arm A on annotated R0 trades (PREREG 4): flagged = pos >= P over the known-pos trades. ``oos`` = out-of-sample
    host trades (criterion 2); ``oos_is_self`` (CONFIRM) uses the same never-searched trades for every criterion."""
    k = _known(host)
    h = host[k].reset_index(drop=True) if len(host) else host
    f = _flags(h, P)
    out: dict[str, Any] = {"flag": f"pos >= {P}", "P": int(P), "n_host": int(len(host)), "n_unknown": int((~k).sum()),
                           "n_flagged": int(f.sum()), "n_unflagged": int((~f).sum()),
                           "by_g1_counts": ({str(c): {"n_flagged": int((f & (h["g1_class"] == c).to_numpy()).sum()),
                                                      "n_unflagged": int((~f & (h["g1_class"] == c).to_numpy()).sum())}
                                             for c in sorted(set(h["g1_class"].astype(str)))} if len(h) else {})}
    if hide:
        return out
    r = h["ret_net"].to_numpy(float) if len(h) else np.zeros(0)
    out["flagged_mean"] = float(r[f].mean()) if f.any() else None
    out["unflagged_mean"] = float(r[~f].mean()) if (~f).any() else None
    if len(h):
        cls = h["g1_class"].astype(str).to_numpy(object)
        out["by_g1"] = {c: _split_means(r, f, cls == c) for c in sorted(set(cls.tolist()))}
        lk = h["lookback_full"].map({True: "full", False: "partial"}).fillna("unknown").to_numpy(object)
        out["by_lookback"] = {c: _split_means(r, f, lk == c) for c in sorted(set(lk.tolist()))}
        out["random_veto"] = random_veto(r, f, cls)
        if stress_host is not None and len(stress_host):
            sr = stress_host.set_index("mint")["ret_net"].reindex(h["mint"]).to_numpy(float)
            ok = np.isfinite(sr)
            out["stress_costs_x1.5"] = _split_means(sr[ok], f[ok], np.ones(int(ok.sum()), bool))
    if oos_is_self:
        oos = host
    oo, of = None, None
    if oos is not None:
        ko = _known(oos)
        oo = oos[ko].reset_index(drop=True) if len(oos) else oos
        of = _flags(oo, P)
        if not oos_is_self:
            out["n_oos"], out["n_oos_flagged"] = int(len(oo)), int(of.sum())
    out["verdict"] = C.verdict_veto(h, f, oos_host=oo, oos_flagged=of, B=B) if len(h) else \
        {"verdict": "UNDERPOWERED", "n_flagged": 0, "n_unflagged": 0, "criteria": []}
    return out


def _veto_crit(ve: Mapping[str, Any], cid: int) -> dict | None:
    for c in ((ve.get("verdict") or {}).get("criteria") or []):
        if c.get("id") == cid:
            return c
    return None


def dose_eval(t: pd.DataFrame, *, B: int, hide: bool) -> dict:
    """Arm C (PREREG 6) on annotated R30 trades: per pos bin and G1 class; Spearman(bin, ret) with a coin CI."""
    bins = t["pos_bin"].astype(str).to_numpy(object) if len(t) else np.zeros(0, object)
    cls = t["g1_class"].astype(str).to_numpy(object) if len(t) else np.zeros(0, object)
    out: dict[str, Any] = {"n": int(len(t)), "counts": _counts_by(bins) if len(t) else {},
                           "counts_by_g1": {c: _counts_by(bins[cls == c]) for c in sorted(set(cls.tolist()))}}
    if hide:
        return out
    r = t["ret_net"].to_numpy(float) if len(t) else np.zeros(0)
    out["by_bin"] = {}
    for b in POS_BINS + ("unknown",):
        sel = bins == b
        if sel.any():
            out["by_bin"][b] = {"n": int(sel.sum()), "mean": float(r[sel].mean()),
                                "ci95": C.coin_bootstrap_ci(r[sel], t["mint"].to_numpy(object)[sel], 0.95, B)}
    out["by_g1_bin"] = {c: _means_by(t[cls == c], bins[cls == c]) for c in sorted(set(cls.tolist()))}
    lk = t["lookback_full"].map({True: "full", False: "partial"}).fillna("unknown").to_numpy(object) if len(t) else bins
    out["by_lookback_bin"] = {c: _means_by(t[lk == c], bins[lk == c]) for c in sorted(set(lk.tolist()))}
    known = bins != "unknown"
    x = np.array([POS_BINS.index(b) for b in bins[known]], float)
    y = r[known]
    rho = spearman(x, y)
    ci = None
    if rho is not None:
        rng = np.random.default_rng(0)
        mints = t["mint"].to_numpy(object)[known]
        codes, _ = pd.factorize(pd.Series(list(mints)))
        ncoin = int(codes.max()) + 1
        members = [np.where(codes == i)[0] for i in range(ncoin)]
        vals = []
        for _ in range(DOSE_B):
            pick = rng.integers(0, ncoin, ncoin)
            idx = np.concatenate([members[i] for i in pick])
            v = spearman(x[idx], y[idx])
            if v is not None:
                vals.append(v)
        if vals:
            ci = (float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975)))
    n0, n3 = int((bins == "0").sum()), int((bins == "3+").sum())
    if n0 < DOSE_MIN_BIN or n3 < DOSE_MIN_BIN:
        reading = "UNDERPOWERED"
    elif ci is not None and ci[1] < 0:
        reading = "NEGATIVE"
    else:
        reading = "NONE"
    out.update({"spearman": rho, "spearman_ci95": ci, "reading": reading, "n_bin0": n0, "n_bin3": n3})
    return out


def q2_extras(ev: Mapping[str, Any]) -> list[dict]:
    """TEST / CONFIRM extras for arm B (PREREG 9): Q2.1 event-time placebo, Q2.2 mean without the best creator."""
    e = ev.get("event_placebo") or {}
    md = e.get("mean_diff")
    comp = bool(e.get("computable"))
    out = [{"id": "Q2.1", "name": f"beats the event-time placebo (>= {EV_MIN_MATCHED} matched signals, mean_diff > 0)",
            "pass": None if not comp or md is None else bool(md > 0),
            "value": {"n_matched": e.get("n_matched"), "mean_diff": md, "ci95": e.get("diff_ci95")}}]
    mw = (ev.get("creators") or {}).get("mean_without_best_creator")
    out.append({"id": "Q2.2", "name": "mean > 0 without the most profitable OG creator",
                "pass": None if mw is None else bool(mw > 0), "value": mw})
    return out


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 + 10 (common.verdict_entry) and the Q2 extras. Item 9 (FINAL) is judged after FINAL."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1):
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or any(e["pass"] is False for e in extras):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(e["pass"] is None for e in extras):
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def decide_train(evals: Mapping[str, Mapping[str, Any]], vetoes: Mapping[int, Mapping[str, Any]]) -> dict:
    """PREREG 9 TRAIN. ENTRY: qualify arm-B configs, pick the highest coin 90 % CI lower bound. VETO: the P whose
    powered TRAIN veto passes criteria 1 and 3, lower CI upper bound first. Shortlists: Q2 = [entry choice],
    Q2-host = [R0] (veto branch), Q2-dose = [R30] (either branch)."""
    rows = []
    for p in GRID_B:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        evp = e.get("event_placebo") or {}
        powered = e["n"] >= TRAIN_MIN_TRADES
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0
                and bool(evp.get("computable")) and evp.get("mean_diff") is not None and evp["mean_diff"] > 0)
        ci = e.get("ci90")
        rows.append({"config": config_key(p), "window_min": p["window_min"], "exit": p["exit"], "powered": powered,
                     "qualifies": bool(good), "n": e["n"], "mean": e.get("mean"),
                     "ci90_lo": ci[0] if ci else None, "placebo_diff": pc,
                     "event_diff": evp.get("mean_diff"), "event_matched": evp.get("n_matched")})
    vrows = []
    for P in P_GRID:
        ve = vetoes[P]
        powered = ve["n_flagged"] >= VETO_MIN and ve["n_unflagged"] >= VETO_MIN
        c1, c3 = _veto_crit(ve, 1), _veto_crit(ve, 3)
        ci = (c1 or {}).get("ci95")
        vrows.append({"P": P, "powered": powered,
                      "qualifies": bool(powered and c1 and c1["pass"] and c3 and c3["pass"]),
                      "n_flagged": ve["n_flagged"], "n_unflagged": ve["n_unflagged"],
                      "flagged_mean": ve.get("flagged_mean"), "unflagged_mean": ve.get("unflagged_mean"),
                      "diff": (c1 or {}).get("value"), "ci95_hi": ci[1] if ci else None,
                      "removed_win_share": (c3 or {}).get("value")})
    dec: dict[str, Any] = {"entry_rows": rows, "veto_rows": vrows, "branches": [], "entry": None, "veto": None}
    q = [r for r in rows if r["qualifies"]]
    if q:
        best = sorted(q, key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"],
                                        W_GRID_MIN.index(r["window_min"]), EXIT_GRID.index(r["exit"])))[0]
        dec["entry"] = {"chosen": best["config"], "window_min": best["window_min"], "exit": best["exit"]}
        dec["branches"].append("entry")
    qv = [r for r in vrows if r["qualifies"]]
    if qv:
        best = sorted(qv, key=lambda r: (r["ci95_hi"], -r["P"]))[0]
        dec["veto"] = {"P": best["P"]}
        dec["branches"].append("veto")
    if dec["branches"]:
        sl = {HYP: [make_params(dec["entry"]["window_min"], dec["entry"]["exit"])] if dec["entry"] else [],
              HYP_HOST: [HOST_PARAMS] if dec["veto"] else [], HYP_DOSE: [DOSE_PARAMS]}
        dec["verdict"] = "SHORTLISTED"
        dec["shortlist"] = sl
        dec["shortlist_hashes"] = {h: [C.params_hash(p) for p in v] for h, v in sl.items()}
        return dec
    if any(r["powered"] for r in rows) or any(r["powered"] for r in vrows):
        dec["verdict"], dec["reason"] = "NO_CONFIG", "powered arm-B configs / vetoes failed their TRAIN bars"
    else:
        dec["verdict"] = "UNDERPOWERED_TRAIN"
        dec["reason"] = (f"no arm-B config reached {TRAIN_MIN_TRADES} trades (best {max(r['n'] for r in rows)}) and no "
                         f"veto had >= {VETO_MIN} flagged and unflagged trades")
    dec["shortlist"], dec["shortlist_hashes"] = {}, {}
    return dec


def decide_val(ev_cand: Mapping[str, Any]) -> dict:
    n = ev_cand["n"]
    mean, mw2 = ev_cand.get("mean"), ev_cand.get("mean_without_top2")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "proceed": v in PROCEED_VAL}


def decide_val_veto(ve: Mapping[str, Any]) -> dict:
    nf, nu = ve["n_flagged"], ve["n_unflagged"]
    fm, um = ve.get("flagged_mean"), ve.get("unflagged_mean")
    if nf < VAL_MIN_SIGN or fm is None or um is None:
        v = "UNDERPOWERED_VAL"
    elif fm >= um:
        v = "FAIL_VAL"
    elif nf < VETO_MIN or nu < VETO_MIN:
        v = "SELECTED_UNDERPOWERED"
    else:
        c1 = _veto_crit(ve, 1)
        v = "SELECTED" if (c1 and c1["pass"]) else "FAIL_VAL"
    return {"verdict": v, "n_flagged": nf, "n_unflagged": nu, "flagged_mean": fm, "unflagged_mean": um,
            "proceed": v in PROCEED_VAL}


def entry_alive_after_test(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """CONFIRM is spent on ENTRY when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    m = (test_doc.get("decision") or {}).get("entry")
    if not m:
        return False, "ENTRY did not run on TEST"
    if m.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    c = (test_doc.get("configs") or {}).get(ROLE_CAND) or {}
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: ENTRY failed TEST"


def veto_alive_after_test(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    e = (test_doc.get("decision") or {}).get("veto")
    if not e:
        return False, "VETO did not run on TEST"
    v = (e.get("verdict") or {}).get("verdict")
    return (v != "FAIL", "ok" if v != "FAIL" else "the TEST veto verdict is FAIL")


def final_entry(t: pd.DataFrame) -> dict:
    """ENTRY: PLAN 3.5 item 9 on the census thirds Q2 never looked at; the debug third is reported apart."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    design = t[t["split"] == FINAL_DESIGN] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "design_third": {"n": int(len(design)), "mean": float(design["ret_net"].mean()) if len(design) else None,
                             "note": "census TRAIN third: the debug third, not judged"}}


def final_veto(t: pd.DataFrame, P: int) -> dict:
    """VETO on FINAL: flagged mean < unflagged mean on the judged thirds (known-pos R0 trades)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    judged = judged[_known(judged)] if len(judged) else judged
    f = _flags(judged, P)
    r = judged["ret_net"].to_numpy(float) if len(judged) else np.zeros(0)
    fm = float(r[f].mean()) if f.any() else None
    um = float(r[~f].mean()) if (~f).any() else None
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "P": int(P), "n_flagged": int(f.sum()),
            "n_unflagged": int((~f).sum()), "flagged_mean": fm, "unflagged_mean": um,
            "flagged_worse": None if fm is None or um is None else bool(fm < um)}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def host_problems() -> list[str]:
    """The R0 host must be the pinned g1.R0_PARAMS (PREREG 3)."""
    h = C.params_hash(g1.R0_PARAMS)
    return [] if h == R0_PIN else [f"g1.R0_PARAMS hash {h} != pinned {R0_PIN}: the R0 host changed"]


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


def live_branches(out_dir: Path, stage: str) -> dict[str, str | None]:
    """branch -> None when it may run at ``stage``, else the reason it stopped (from the docs written before it)."""
    out_dir = Path(out_dir)
    tr = _read_json(out_dir / "train.json")
    if not tr or tr.get("provisional") or (tr.get("decision") or {}).get("verdict") != "SHORTLISTED":
        return {b: "no SHORTLISTED official TRAIN" for b in BRANCHES}
    live: dict[str, str | None] = {b: (None if b in tr["decision"].get("branches", []) else
                                       "did not qualify on TRAIN") for b in BRANCHES}
    if stage == "val":
        return live
    va = _read_json(out_dir / "val.json")
    for b in BRANCHES:
        if live[b] is None:
            d = ((va or {}).get("decision") or {}).get(b)
            if not va:
                live[b] = "no VAL result"
            elif not d or not d.get("proceed"):
                live[b] = f"VAL decision {(d or {}).get('verdict')}"
    if stage == "test":
        return live
    te = _read_json(out_dir / "test.json")
    for b, fn in (("entry", entry_alive_after_test), ("veto", veto_alive_after_test)):
        if live[b] is None:
            if not te:
                live[b] = "no TEST result"
            else:
                ok, why = fn(te)
                live[b] = None if ok else why
    if stage == "confirm":
        return live
    co = _read_json(out_dir / "confirm.json")
    if co:
        de, dv = (co.get("decision") or {}).get("entry"), (co.get("decision") or {}).get("veto")
        if live["entry"] is None and (de or {}).get("verdict") != "PASS":
            live["entry"] = f"CONFIRM {(de or {}).get('verdict')}"
        if live["veto"] is None and ((dv or {}).get("verdict") or {}).get("verdict") != "PASS":
            live["veto"] = f"CONFIRM veto {((dv or {}).get('verdict') or {}).get('verdict')}"
    return live


def stage_configs(stage: str, out_dir: Path = OUT_DIR, shortlist_path: Path | None = None) -> list[tuple[str, str, dict]]:
    """[(role, hypothesis, params)] the stage runs (later stages: the live branches' shortlisted configs)."""
    if stage in ("debug", "train"):
        return ([(config_key(p), HYP, p) for p in GRID_B]
                + [(ROLE_HOST, HYP_HOST, HOST_PARAMS), (ROLE_DOSE, HYP_DOSE, DOSE_PARAMS)])
    live = live_branches(out_dir, stage)
    if all(v is not None for v in live.values()):
        return []
    out: list[tuple[str, str, dict]] = []
    sl_b, sl_h, sl_d = (_shortlist(h, shortlist_path) for h in (HYP, HYP_HOST, HYP_DOSE))
    if live["entry"] is None:
        out.append((ROLE_CAND, HYP, (sl_b or {}).get("configs", [None])[0]))
    if live["veto"] is None:
        out.append((ROLE_HOST, HYP_HOST, (sl_h or {}).get("configs", [None])[0]))
    out.append((ROLE_DOSE, HYP_DOSE, (sl_d or {}).get("configs", [None])[0]))
    return out


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Q2Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Q2Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Q2Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Q2Refused("PREREG.md changed after the first official TRAIN run; record changes in Q2/AMENDMENTS.md "
                        "as a new version instead")
    hp = host_problems()
    if hp:
        raise Q2Refused("; ".join(hp))
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Q2Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Q2Refused("TRAIN already ran on complete data (Q2/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Q2Refused("no TRAIN result (Q2/train.json): run --stage train first")
    if train.get("provisional"):
        raise Q2Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    dec = train.get("decision") or {}
    if dec.get("verdict") != "SHORTLISTED":
        raise Q2Refused(f"TRAIN decision {dec.get('verdict')}: Q2 stopped before VAL")
    want = dec.get("shortlist_hashes") or {}
    for h in (HYP, HYP_HOST, HYP_DOSE):
        if not want.get(h):
            continue
        sl = _shortlist(h, shortlist_path)
        if not sl:
            raise Q2Refused(f"no VAL shortlist for {h} (written by a complete --stage train)")
        if sorted(sl.get("hashes", [])) != sorted(want.get(h, [])):
            raise Q2Refused(f"the {h} shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Q2Refused("VAL already ran (Q2/val.json exists): VAL is evaluated once")
        info["live_branches"] = live_branches(out_dir, "val")
        return info
    if stage == "test" and not (out_dir / "val.json").exists():
        raise Q2Refused("no VAL result (Q2/val.json): TEST needs a VAL decision first")
    if stage in ("confirm", "final") and not (out_dir / "test.json").exists():
        raise Q2Refused(f"never {stage.upper()} before TEST: run --stage test first")
    live = live_branches(out_dir, stage)
    if all(v is not None for v in live.values()):
        raise Q2Refused(f"no live branch for {stage.upper()}: " + "; ".join(f"{b}: {v}" for b, v in live.items()))
    if (out_dir / f"{stage}.json").exists():
        raise Q2Refused(f"{stage.upper()} already ran (Q2/{stage}.json exists): one run per hypothesis")
    for h in (HYP, HYP_HOST, HYP_VETO, HYP_DOSE):
        if any(r.get("hypothesis") == h and C.split_group(r.get("split", "")) == C.split_group(split)
               and not r.get("debug") for r in _runs(ledger_path)):
            raise Q2Refused(f"{h} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Q2Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    info["live_branches"] = live
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


def pool_hi(stage: str, census: C.Census) -> float:
    """PREREG 2.1: the structural pool holds graduates created before the end of the split being run."""
    split = STAGE_SPLIT[stage]
    if split in C.SPLIT_BOUNDS:
        return float(C.SPLIT_BOUNDS[split][1])
    if split == "final_train":
        return float(census.train_hi) + 1.0
    return math.inf


def _scanned_hours(flow: Path | None) -> frozenset | None:
    """Curve hours of the snapshot (PREREG 2.4); None -> the registry falls back to hours holding a graduate."""
    try:
        h = C.completeness_from_flow(flow, with_bar_hours=False).curve_hours
    except OSError:
        return None
    return h or None


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, structure_rows: Sequence[Mapping[str, Any]] | None = None,
              census: C.Census | None = None, flow: Path | None = None, ledger_path: Path | None = None,
              shortlist_path: Path | None = None, B: int = 10_000, n_placebo: int = 20,
              env: Mapping[str, str] | None = None, _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Q2/<stage>.json + .md (``ds`` / ``structure_rows`` injection is for tests:
    without ``structure_rows`` an injected run builds the pool from the dataset's own coins)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "q2_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Q2Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise Q2Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise Q2Refused("no configs to run (shortlist missing or malformed, or no live branch)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Q2Refused(str(e)) from e
        if stage == "train" and not provisional:
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time())}, indent=1))
            if rerun_reason and (out_dir / "train.json").exists():
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    p = out_dir / f"train.{ext}"
                    if p.exists():
                        p.rename(out_dir / f"train_prev_{stamp}.{ext}")
        cen = census if census is not None else (C.Census.load() if ds is None else C.Census.empty())
        injected = ds is not None
        if ds is None:
            ds = C.load(split, flow=flow, census=cen, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        rows = structure_rows
        scanned = None
        if rows is None and not injected:
            f = Path(flow or C.flow_dir())
            rows = structure_rows_from_frames(C._read_parquet(f / "graduates.parquet"), cen, pool_hi(stage, cen))
            scanned = _scanned_hours(f)
        reg = build_registry(ds, rows, scanned)
        cls_map = g1_classes(ds)
        span = _span_days(ds)
        doc: dict[str, Any] = {"hypothesis": HYP, "queue_item": "q2 / CC1", "version": VERSION, "stage": stage,
                               "split": split, "utc": C.utc_str(time.time()), "provisional": provisional,
                               "debug_only": debug, "prereg_sha256": info["prereg_sha256"],
                               "rerun_reason": rerun_reason, "coverage": cov, "n_coins": len(ds), "span_days": span,
                               "live_branches": info.get("live_branches"),
                               "code": {"g1_sha256": _sha(Path(g1.__file__)),
                                        "common_sha256": _sha(Path(C.__file__))},
                               "event_counts": event_counts(ds, reg, cls_map, span)}
        strategy = make_strategy(reg)
        stratum = make_stratum(cls_map)
        results: dict[str, C.Result] = {}
        annots: dict[str, pd.DataFrame] = {}
        evcs: dict[str, dict] = {}
        ev_trades: dict[str, pd.DataFrame] = {}
        for role, h, p in configs:
            if h == HYP:
                results[role] = C.backtest(strategy, split, p, hypothesis=h, ds=ds, cfg=FILL, placebo=True,
                                           n_placebo=n_placebo, placebo_eligible=placebo_alive,
                                           placebo_strata=stratum, placebo_controls=PLACEBO_CONTROLS, stress=STRESS_B,
                                           declarations=DECL, ledger_path=ledger_path, shortlist_path=shortlist_path)
                t = results[role].trades
                annots[role] = annotate_b(t, ds, reg, cls_map, float(p["window_s"]))
                entries = event_placebo_entries(ds, reg, t, p)
                ev = (C.run_entries(ds, strategy, p, FILL, entries, hypothesis=h, ledger_path=ledger_path,
                                    shortlist_path=shortlist_path) if entries else C._frame([]))
                ev_trades[role] = ev
                evcs[role] = event_compare(t, ev, B=min(B, 4000), hide=debug)
            else:
                fn = g1.host_r0 if h == HYP_HOST else host_r30
                results[role] = C.backtest(fn, split, p, hypothesis=h, ds=ds, cfg=FILL, placebo=False,
                                           stress=STRESS_HOST, declarations=DECL, ledger_path=ledger_path,
                                           shortlist_path=shortlist_path)
                annots[role] = annotate_hosts(results[role].trades, reg, cls_map)
        n_tr = C.n_trials(ledger_path)
        doc["configs"] = {role: evaluate_b(results[role], annots[role], evcs[role], B=B, hide=debug,
                                           n_trials_total=n_tr)
                          for role, h, _ in configs if h == HYP}
        if debug:
            doc["entries_per_day"] = {k: (e["n"] / span if span == span and span > 0 else None)
                                      for k, e in doc["configs"].items()}
        else:
            _write_trades(out_dir, stage, provisional, results, annots)
        host_t = (pd.concat([results[ROLE_HOST].trades, annots[ROLE_HOST]], axis=1) if ROLE_HOST in results else None)
        host_s = results[ROLE_HOST].stress.get("costs_x1.5") if ROLE_HOST in results else None
        if ROLE_DOSE in results:
            dose_t = pd.concat([results[ROLE_DOSE].trades, annots[ROLE_DOSE]], axis=1)
            doc["dose"] = dose_eval(dose_t, B=min(B, 4000), hide=debug)
        dec_tr = ((_read_json(out_dir / "train.json") or {}).get("decision") or {}) if stage not in ("train", "debug") \
            else {}
        p_star = (dec_tr.get("veto") or {}).get("P")
        live = info.get("live_branches") or {}
        # ---- arm A: the copy-order veto on R0 (PREREG 4)
        if stage in ("train", "debug"):
            doc["veto"] = {}
            for P in P_GRID:
                ve = veto_eval(host_t, P, B=min(B, 4000), hide=debug, stress_host=host_s)
                ve["trial"] = C.record_run(HYP_VETO, veto_params(P), split, {"n": ve["n_flagged"] + ve["n_unflagged"],
                                                                             "mean": None}, ledger_path, debug=debug)
                doc["veto"][P] = ve
        elif live.get("veto") is None and p_star is not None and host_t is not None:
            if stage == "val":
                doc["veto"] = veto_eval(host_t, p_star, B=min(B, 4000), hide=False, stress_host=host_s)
            elif stage == "test":
                val_host = _read_trades(out_dir, "val", ROLE_HOST)
                doc["veto"] = veto_eval(val_host if val_host is not None else _empty_host(), p_star, B=min(B, 4000),
                                        hide=False, oos=host_t)
            elif stage == "confirm":
                doc["veto"] = veto_eval(host_t, p_star, B=min(B, 4000), hide=False, oos_is_self=True,
                                        stress_host=host_s)
            if "veto" in doc:
                doc["veto"]["trial"] = C.record_run(HYP_VETO, veto_params(p_star), split,
                                                    {"n": len(host_t), "mean": None}, ledger_path)
        # ---- decisions
        if debug:
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(doc["configs"], doc["veto"])
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                for h in (HYP, HYP_HOST, HYP_DOSE):
                    if dec["shortlist"].get(h):
                        C.write_shortlist(h, dec["shortlist"][h], path=shortlist_path, ledger_path=ledger_path,
                                          note=f"{VERSION}: PREREG 9 rule, branches {dec['branches']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            de = decide_val(doc["configs"][ROLE_CAND]) if ROLE_CAND in doc["configs"] else None
            dv = decide_val_veto(doc["veto"]) if "veto" in doc else None
            doc["decision"] = {"verdict": "VAL", "entry": de, "veto": dv,
                               "proceed": bool((de or {}).get("proceed") or (dv or {}).get("proceed"))}
        elif stage in ("test", "confirm"):
            de = None
            if ROLE_CAND in results:
                val_t = _read_trades(out_dir, "val", ROLE_CAND)
                val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
                base = C.verdict_entry(results[ROLE_CAND], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
                extras = q2_extras(doc["configs"][ROLE_CAND])
                de = {"verdict": combine_verdict(base, extras), "base": base, "q2_extras": extras}
            dv = doc.get("veto")
            doc["decision"] = {"verdict": f"ENTRY {(de or {}).get('verdict')}; VETO "
                                          f"{((dv or {}).get('verdict') or {}).get('verdict')}", "entry": de, "veto": dv}
        elif stage == "final":
            de = final_entry(results[ROLE_CAND].trades) if ROLE_CAND in results else None
            dv = final_veto(host_t, p_star) if (live.get("veto") is None and p_star is not None
                                               and host_t is not None) else None
            doc["decision"] = {"verdict": "REPORTED", "entry": de, "veto": dv}
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"q2 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise Q2Refused(str(e)) from e


def _empty_host() -> pd.DataFrame:
    return C._frame([], extra=("pos", "pos_bin", "link", "g1_class", "lookback_full"))


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result],
                  annots: Mapping[str, pd.DataFrame]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for role, r in results.items():
        t = pd.concat([r.trades, annots[role]], axis=1).reset_index(drop=True)
        frames.append(t.assign(role=role, hypothesis=r.meta["hypothesis"], params_hash=C.params_hash(r.meta["params"])))
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if not p.exists():
        return None
    t = pd.read_csv(p)
    t = t[t["role"] == role].reset_index(drop=True)
    if "pos" in t:
        t["pos"] = t["pos"].astype(float)
    if "lookback_full" in t:
        t["lookback_full"] = t["lookback_full"].map({True: True, False: False, "True": True, "False": False})
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
    """The hypothesis-level status per branch from every stage written so far (``pending`` = the stage being
    written), plus the latest arm-C dose reading."""
    def doc(s):
        if pending is not None and pending.get("stage") == s and not pending.get("provisional"):
            return pending
        return _read_json(Path(out_dir) / f"{s}.json")

    dose = None
    for s in ("final", "confirm", "test", "val", "train"):
        d = doc(s)
        if d and (d.get("dose") or {}).get("reading"):
            dose = f"{d['dose']['reading']} ({s})"
            break
    tail = f"; DOSE: {dose}" if dose else ""
    tr = doc("train")
    if not tr or tr.get("provisional"):
        return "PENDING (no official TRAIN run)"
    dec = tr.get("decision") or {}
    tv = dec.get("verdict")
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)" + tail
    if tv == "NO_CONFIG":
        return "NO EDGE (nothing qualified on TRAIN: neither the spillover entry nor the copy-order veto)" + tail
    out = []
    for b, good, bad in (("entry", "EDGE", "NO EDGE"), ("veto", "VETO", "NO VETO")):
        lab = b.upper()
        if b not in dec.get("branches", []):
            out.append(f"{lab}: {bad} (did not qualify on TRAIN)")
            continue
        va = doc("val")
        if not va:
            out.append(f"{lab}: PENDING VAL")
            continue
        vv = ((va.get("decision") or {}).get(b) or {}).get("verdict")
        if vv == "FAIL_VAL":
            out.append(f"{lab}: {bad} (failed VAL)")
            continue
        if vv == "UNDERPOWERED_VAL" or vv is None:
            out.append(f"{lab}: UNDERPOWERED (VAL)")
            continue
        te = doc("test")
        if not te:
            out.append(f"{lab}: PENDING TEST")
            continue
        ok, why = (entry_alive_after_test if b == "entry" else veto_alive_after_test)(te)
        if not ok:
            out.append(f"{lab}: {bad} ({why})")
            continue
        co = doc("confirm")
        if not co:
            out.append(f"{lab}: PENDING CONFIRM")
            continue
        d = (co.get("decision") or {}).get(b) or {}
        cv = d.get("verdict") if b == "entry" else (d.get("verdict") or {}).get("verdict")
        if cv == "UNDERPOWERED":
            out.append(f"{lab}: UNDERPOWERED (CONFIRM)")
            continue
        if cv != "PASS":
            out.append(f"{lab}: {bad} (CONFIRM {cv})")
            continue
        fi = doc("final")
        if not fi:
            out.append(f"{lab}: PENDING FINAL")
            continue
        fd = (fi.get("decision") or {}).get(b) or {}
        ok_final = fd.get("mean_positive") if b == "entry" else fd.get("flagged_worse")
        out.append(f"{lab}: {good}" if ok_final else f"{lab}: {bad} (FINAL)")
    return "; ".join(out) + tail


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def _num(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{float(x):.{nd}f}"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [f"# Q2 (CC1) {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Q2 status:** {doc.get('overall')}.", ""]
    if doc.get("live_branches"):
        L += [f"- **Live branches at this stage:** {doc['live_branches']} (None = live).", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and placebo "
              "outcomes are hidden, and no parameter was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        pl = ec.get("pool") or {}
        L += ["## Structure (counts only)", "",
              f"- Pool: {pl.get('graduates')} graduates ({pl.get('keyed')} with a key, {pl.get('null_keys')} NULL); "
              f"{pl.get('symbol_keys')} symbol keys, {pl.get('name_keys')} name keys; first graduation "
              f"{pl.get('first_g_utc')} UTC.",
              f"- Usable coins by pos bin: {ec['pos_bins']}; full 7-day lookback: {ec['lookback_full']} of "
              f"{ec['lookback_known']}.",
              f"- Pos bins by G1 class: {ec['pos_bins_by_g1']}.",
              f"- Link of coins with pos ≥ 1: {ec['link_of_copies']}.",
              f"- OG coins with ≥ 1 copy inside W: {ec['og_with_copy_in_W']} (per day "
              f"{ {k: _num(v) for k, v in ec['og_with_copy_in_W_per_day'].items()} }); copy events inside W: "
              f"{ec['copy_events_in_W']}.",
              f"- Lag of an OG's first copy: {ec['first_copy_lag']}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Arm B: original spillover", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | creators | tags | by G1 class | placebo draws/signal | event placebo matched / "
                  "draws | horizon exits | entries/day |", "|---|---:|---:|---|---|---:|---|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                evp = e.get("event_placebo") or {}
                L.append(f"| {e['config']} | {e['n']} | {e['n_creators']} | {e['tags']} | {e['by_g1_counts']} | "
                         f"{_num(e.get('placebo_draws_per_signal'))} | {evp.get('n_matched')} / {evp.get('n_placebo')} | "
                         f"{e['horizon_exits']} | {_num(epd)} |")
        else:
            L += ["| role | config | n | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (G1 class) | "
                  "placebo diff (unmatched) | event-time diff [95% CI] (matched) | w/o best creator | costs ×1.5 |",
                  "|---|---|---:|---:|---|---|---:|---:|---:|---|---:|---:|"]
            for k, e in cf.items():
                pc = (e.get("placebo") or {}).get("mean_diff")
                pu = (e.get("placebo_unmatched") or {}).get("mean_diff")
                evp = e.get("event_placebo") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {_pct(e.get('mean'))} | {_ci(e.get('ci90'))} | "
                         f"{_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | {_pct(pc)} | {_pct(pu)} | "
                         f"{_pct(evp.get('mean_diff'))} {_ci(evp.get('diff_ci95'))} ({evp.get('n_matched')}) | "
                         f"{_pct((e.get('creators') or {}).get('mean_without_best_creator'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} |")
            L.append("")
            for k, e in cf.items():
                L.append(f"- {k} diagnostics: {e.get('diagnostics')}.")
        L.append("")
    ve = doc.get("veto")
    if ve:
        L += ["## Arm A: copy-order veto on R0", ""]
        items = ve.items() if "flag" not in ve else [(ve.get("P"), ve)]
        for k, v in items:
            line = (f"- P = {k} ({v['flag']}): R0 trades {v['n_host']} ({v['n_unknown']} with NULL pos), flagged "
                    f"{v['n_flagged']}, unflagged {v['n_unflagged']}; by G1 class {v.get('by_g1_counts')}")
            if "verdict" in v:
                rv = v.get("random_veto") or {}
                line += (f"; flagged mean {_pct(v.get('flagged_mean'))}, unflagged mean {_pct(v.get('unflagged_mean'))}; "
                         f"random veto p {_num(rv.get('p_random'), 3)}, within G1 class p "
                         f"{_num(rv.get('p_within_g1'), 3)}; by G1 {v.get('by_g1')}; by lookback {v.get('by_lookback')}; "
                         f"verdict **{v['verdict'].get('verdict')}** ({v['verdict'].get('criteria')})")
            L.append(line + ".")
        L.append("")
    do = doc.get("dose")
    if do:
        L += ["## Arm C: dose-response on R30 (never decides)", "",
              f"- R30 trades {do['n']}; by pos bin {do['counts']}; by G1 class {do['counts_by_g1']}."]
        if "reading" in do:
            L.append(f"- Spearman(bin, ret) {_num(do.get('spearman'), 3)} [95% CI {do.get('spearman_ci95')}]: "
                     f"**{do['reading']}**; by bin "
                     f"{ {b: (v['n'], _pct(v['mean'])) for b, v in (do.get('by_bin') or {}).items()} }.")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("entry_rows") or []:
        L.append(f"- ENTRY {r['config']}: n {r['n']}, mean {_pct(r['mean'])}, 90% CI low {_pct(r['ci90_lo'])}, "
                 f"placebo diff {_pct(r['placebo_diff'])}, event-time diff {_pct(r['event_diff'])} "
                 f"({r['event_matched']} matched), qualifies {r['qualifies']}.")
    for r in dec.get("veto_rows") or []:
        L.append(f"- VETO P = {r['P']}: flagged {r['n_flagged']}, unflagged {r['n_unflagged']}, flagged "
                 f"{_pct(r['flagged_mean'])} vs unflagged {_pct(r['unflagged_mean'])}, CI95 hi {_pct(r['ci95_hi'])}, "
                 f"removed win share {_num(r['removed_win_share'], 3)}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlists written: {dec['shortlist_written']} (branches {dec.get('branches')}).")
    if st not in ("train", "debug"):
        for b in BRANCHES:
            d = dec.get(b) if isinstance(dec.get(b), dict) else None
            if not d:
                continue
            if "base" in d:
                L.append(f"- ENTRY verdict **{d['verdict']}**:")
                for c in d["base"]["criteria"]:
                    L.append(f"  - PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
                for c in d.get("q2_extras", []):
                    L.append(f"  - {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
                if d["base"].get("auto_rejections"):
                    L.append(f"  - Auto-rejections: {d['base']['auto_rejections']}.")
                L.append("  - PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
            elif "flag" in d:
                L.append(f"- VETO verdict **{(d.get('verdict') or {}).get('verdict')}** "
                         f"(criteria {(d.get('verdict') or {}).get('criteria')}).")
            else:
                L.append(f"- {b.upper()}: {d}.")
    for key in ("reason", "note"):
        if dec.get(key):
            L.append(f"- {dec[key]}")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Q2 (CC1) copycat order veto and original spillover entry: "
                                             "pre-registered stages; see research/lab2/Q2/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third: mechanics and counts only")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and exit")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial data")
    ap.add_argument("--rerun-reason", help="TRAIN only: re-run an official TRAIN after a data correction")
    ap.add_argument("--B", type=int, default=10_000, help="bootstrap draws")
    ap.add_argument("--n-placebo", type=int, default=20)
    a = ap.parse_args(argv)
    if not a.stage and not a.debug:
        ap.error("--stage or --debug is required")
    stage = "debug" if a.debug else a.stage
    try:
        if a.check:
            print(json.dumps(check_prereqs(stage, rerun_reason=a.rerun_reason), indent=1))
            return 0
        doc = run_stage(stage, allow_partial=a.allow_partial, rerun_reason=a.rerun_reason, B=a.B,
                        n_placebo=a.n_placebo)
    except Q2Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

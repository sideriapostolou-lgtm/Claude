"""Y1: creator reputation -- buy post-BOOST only when the coin's deployer has a good as-of record.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Y1/PREREG.md``.

Mechanism (PREREG 1): a deployer runs the same playbook on every coin. An operator that pays for post-migration support
pays for it on each coin; a rug farm dumps each coin. If coin outcomes correlate within a deployer, the deployer's
as-of record (the post-BOOST 30-minute path of its EARLIER graduates, resolved before the decision) sorts the next
coin. Y1 enters post-BOOST only on good-record deployers (``Y1``), and tests "avoid bad-record deployers" as a VETO on
a host that enters every repeat deployer (``Y1-host``), never as a standalone entry.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s). The registry is cross-coin:

* **Deployers** (structure only): who deployed what (``creator``, ``create_user``), read through AsOf at g + 20 s of
  each graduate and used only at tau >= that graduate's g. It decides which creator keys are SHARED (launchpad
  signers, multi-signer fee keys, pooled accounts, factory-volume keys): those coins are skipped.
* **Records** (outcomes of OTHER coins): r(p) = AsOf(p, t_end).price / AsOf(p, t_ref).price - 1 for an earlier usable
  graduate p of the same creator, t_ref = first grid time >= g_p + 420 s, t_end = t_ref + 30 min. It counts at
  decision t only when t_end <= t (every bar it reads ended before tau) and g_p < g of the traded coin; never the
  traded mint. History splits per stage are fixed (:data:`HISTORY_SPLITS`): a stage never reads a later or a sealed
  split's outcomes.

Persistence gate (stop rule, TRAIN, before any P&L): Spearman(record mean, the coin's own next-30-minute mid change)
over eligible coins; KILL when rho <= 0 or the deployer-cluster bootstrap 90 % CI lower bound <= 0.

Fixed path (PREREG 9, review Y1-2): when the gate PASSes but no GOOD config is powered on TRAIN (the expected
outcome), GOOD(0) / T30 and its host -- fixed a priori, never chosen from TRAIN returns -- run VAL and TEST once each,
reported only, and CONFIRM (the only split that can power Y1) is the judged look. Fills: worst minute-bar fills with
next-bar stops and time exits (``FILL``); same-bar exits are a stress run.

CLI::

    python research/lab2/y1.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/y1.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/y1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/y1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/y1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/y1.py --stage final
    python research/lab2/y1.py --stage val --check             # prerequisites only

Each stage writes ``Y1/<stage>.json`` and ``Y1/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlists, nothing after a persistence KILL, TEST / CONFIRM / FINAL once each, never
CONFIRM or FINAL before TEST, PLAN 8 data gates V1-V4, PREREG frozen after the first official TRAIN run).
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

VERSION = "y1-v1"
OUT_DIR = HERE / "Y1"
HYP, HYP_HOST, HYP_VETO, HYP_PERSIST = "Y1", "Y1-host", "Y1-veto", "Y1-persist"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
# PREREG 2.1: outcome records come only from splits earlier in time and already open at the stage
HISTORY_SPLITS = {"debug": ("final_train",), "train": ("train",), "val": ("train", "val"),
                  "test": ("train", "val", "test"), "confirm": ("confirm",),
                  "final": ("train", "val", "test", "final_train", "final_val", "final_test")}

# =========================================================================== pre-registered constants (PREREG 2-8)
E_AGE_S = float(C.AGENT_WINDOW_S)   # 420 s: entries and record references start post-BOOST (last slice <= g + 353 s)
E_AGE_MAX_S = 3600.0                # entry window ends at age 60 min
H_REC_S = 1800.0                    # a record is the 30-minute mid change after the post-BOOST reference
REC_K = 3                           # record mean over the most recent 3 resolved earlier graduates
SHARED_MAX_24H = 24                 # >= 24 graduates under one key in 24 h: a deployment service
SHARED_WINDOW_S = 86_400.0
STOP_PCT = 0.50                     # catastrophe stop
EXIT_HOLD_S = {"T30": 1800.0, "T60": 3600.0}
EXIT_BY_AGE_S = 178 * 60.0          # registered deadline inside the B2 window (never binds: 60 + 60 min max)
THETA_GRID = (0.0, 0.10)
EXIT_GRID = ("T30", "T60")
# PREREG 9 fixed path (review Y1-2): when no GOOD config is powered on TRAIN, this config (and HOST with its exit) goes
# on, chosen a priori, never from TRAIN returns: theta = 0 is the veto flag's complement, T30 the record's horizon
FIXED_THETA, FIXED_EXIT = 0.0, "T30"
WARMUP_S = 86_400.0                 # diagnostic: decisions within 24 h of the first history graduation
# persistence gate (stop rule)
PG_MIN_OBS, PG_MIN_CLUSTERS, PG_B = 60, 20, 2000
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_CLUSTERS = 30, 10
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                       # PLAN 3.5 item 2
PASS_MIN_TRADES, PASS_MIN_CLUSTERS = 60, 10
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
SHORTLISTED = ("SHORTLISTED", "SHORTLISTED_FIXED")   # TRAIN decisions that write the shortlists
SIZE_USD = 20.0

FIXED = {
    "version": VERSION, "e_age_s": E_AGE_S, "e_age_max_s": E_AGE_MAX_S, "h_rec_s": H_REC_S, "rec_k": REC_K,
    "record": "mid change t_ref -> t_ref + 30 min, t_ref = first grid time >= g + 420 s; usable earlier graduates "
              "of the same creator, resolved (t_end <= t), g_p < g",
    "shared_rules": ["pooled", "signs_for_others", "multi_signer>=2", f"factory_volume>={SHARED_MAX_24H}/24h"],
    "history_splits": {k: list(v) for k, v in HISTORY_SPLITS.items()}, "stop_pct": STOP_PCT,
    "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD, "placebo": "eligible-stratum (repeat deployer, resolved)",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def make_params(rule: str, exit_set: str, theta: float | None = None) -> dict:
    if exit_set not in EXIT_GRID:
        raise ValueError(f"exit set {exit_set!r} not in {EXIT_GRID}")
    if rule == "good":
        if theta not in THETA_GRID:
            raise ValueError(f"theta {theta!r} not in {THETA_GRID}")
        return {**FIXED, "rule": "good", "theta": float(theta), "exit": exit_set}
    if rule == "host":
        return {**FIXED, "rule": "host", "exit": exit_set}
    raise ValueError(f"unknown rule {rule!r}")


GRID_GOOD = [make_params("good", e, th) for th in THETA_GRID for e in EXIT_GRID]
GRID_HOST = [make_params("host", e) for e in EXIT_GRID]
GRID = GRID_GOOD + GRID_HOST
VETO_RULE = "record_mean < 0 at the host entry (the complement of GOOD(0))"


def veto_params(exit_set: str) -> dict:
    return {"version": VERSION, "test": "veto", "flag": VETO_RULE, "host": make_params("host", exit_set)}


PERSIST_PARAMS = {"version": VERSION, "test": "persistence", "stat": "spearman(record_mean, next 30-min mid change)",
                  "min_obs": PG_MIN_OBS, "min_clusters": PG_MIN_CLUSTERS, "ci": "deployer-cluster bootstrap 90%",
                  "fixed": FIXED}
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "no_entry_bar_exits": dataclasses.replace(FILL, entry_bar_exits=False),
          "same_bar_exits": C.FillConfig()}   # the harness's same-bar exits: a stress run only (review Y1-1)
DECL = {"uses_wallet_reputation": True, "reputation_excludes_traded_coin": True, "uses_organic_flow": False,
        "uses_truncated_windows": False, "uses_current_state_fields": False}


class Y1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"good|th{p['theta']:g}|{p['exit']}" if p["rule"] == "good" else f"host|{p['exit']}"


def hyp_of(p: Mapping[str, Any]) -> str:
    return HYP if p["rule"] == "good" else HYP_HOST


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


# =========================================================================== the registry (cross-coin, causal)


@dataclass
class Deployers:
    """Structure only: who deployed which graduate. ``creator -> (g sorted, signers)``, ``signer -> (g, creators)``.
    A query at tau sees graduates with g <= tau only."""

    creator_ev: dict[str, tuple[np.ndarray, tuple[str, ...]]] = field(default_factory=dict)
    signer_ev: dict[str, tuple[np.ndarray, tuple[str, ...]]] = field(default_factory=dict)
    pooled: frozenset = frozenset()
    n_coins: int = 0

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]], pooled: Iterable[str] | None = None) -> "Deployers":
        cre: dict[str, list] = defaultdict(list)
        sig: dict[str, list] = defaultdict(list)
        seen: set[str] = set()
        for r in rows:
            if r["mint"] in seen:
                continue
            seen.add(r["mint"])
            c, u = _nz(r.get("creator")), _nz(r.get("signer"))
            if c is None:
                continue
            cre[str(c)].append((float(r["g"]), "" if u is None else str(u)))
            if u is not None:
                sig[str(u)].append((float(r["g"]), str(c)))

        def pack(d):
            out = {}
            for k, ev in d.items():
                ev.sort()
                out[k] = (np.array([e[0] for e in ev], float), tuple(e[1] for e in ev))
            return out
        pool = frozenset(pooled) if pooled is not None else frozenset(set(C.POOLED_ACCOUNTS) | C._pooled_from_file())
        return cls(creator_ev=pack(cre), signer_ev=pack(sig), pooled=pool, n_coins=len(seen))

    def shared(self, creator: str, tau: float) -> str | None:
        """Why ``creator`` is a shared deployer key as of ``tau`` (PREREG 2.2), or None."""
        if creator in self.pooled:
            return "pooled"
        ev = self.signer_ev.get(creator)
        if ev is not None:
            ts, crs = ev
            hi = int(np.searchsorted(ts, tau, side="right"))
            if any(c != creator for c in crs[:hi]):
                return "signs_for_others"
        ev = self.creator_ev.get(creator)
        if ev is not None:
            ts, sg = ev
            hi = int(np.searchsorted(ts, tau, side="right"))
            if len({s for s in sg[:hi] if s}) >= 2:
                return "multi_signer"
            lo = int(np.searchsorted(ts, tau - SHARED_WINDOW_S, side="right"))
            if hi - lo >= SHARED_MAX_24H:
                return "factory_volume"
        return None


@dataclass(frozen=True)
class Prior:
    """The outcome record of one graduate (a LABEL of that coin, used only as history for later coins)."""

    mint: str
    g: float
    t_ref: float
    t_end: float
    ret: float


def record_window(cd: C.CoinData) -> tuple[float, float]:
    t_ref = grid_time_from(cd, cd.g + E_AGE_S)
    return t_ref, t_ref + H_REC_S


def prior_of(ds: C.Dataset, mint: str) -> Prior | None:
    """r(p) through AsOf at t_ref and t_end (PREREG 2.3); None when the window leaves the data or a price is bad."""
    cd = ds.coin(mint)
    t_ref, t_end = record_window(cd)
    if t_end - C.DECISION_LAG_S > cd.m0 + 60 * C.N_BARS:
        return None
    p0, p1 = ds.asof(mint, t_ref).price, ds.asof(mint, t_end).price
    if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and p1 > 0):
        return None
    return Prior(mint=mint, g=cd.g, t_ref=t_ref, t_end=t_end, ret=float(p1 / p0 - 1.0))


def _creator_at_g(cd: C.CoinData, sol: C.SolUsd | None = None) -> tuple[Any, Any, Any]:
    """(creator, signer, symbol) read through AsOf at g + 20 s (all legal from creation or g)."""
    s = C.AsOf(cd, cd.g + C.DECISION_LAG_S, sol)
    return _nz(s.get("creator")), _nz(s.get("create_user")), _nz(s.get("symbol"))


@dataclass
class Records:
    """creator -> its usable graduates' records, sorted by g."""

    by_creator: dict[str, list[Prior]] = field(default_factory=dict)
    n_coins: int = 0
    n_priors: int = 0
    first_g: float | None = None

    @classmethod
    def from_datasets(cls, datasets: Iterable[C.Dataset]) -> "Records":
        by: dict[str, list[Prior]] = defaultdict(list)
        seen: set[str] = set()
        first, n_p = None, 0
        for ds in datasets:
            for m in ds.mints:
                if m in seen:
                    continue
                seen.add(m)
                cd = ds.coin(m)
                first = cd.g if first is None else min(first, cd.g)
                cr = _creator_at_g(cd, ds.sol)[0]
                if cr is None:
                    continue
                p = prior_of(ds, m)
                if p is None:
                    continue
                by[str(cr)].append(p)
                n_p += 1
        for v in by.values():
            v.sort(key=lambda p: (p.g, p.mint))
        return cls(by_creator=dict(by), n_coins=len(seen), n_priors=n_p, first_g=first)

    def query(self, creator: str, g_cur: float, mint: str, t: float) -> dict:
        """Earlier graduates (g_p < g_cur, never ``mint``) and those resolved by decision time ``t``."""
        lst = self.by_creator.get(creator, ())
        earlier = [p for p in lst if p.g < g_cur and p.mint != mint]
        res = [p for p in earlier if p.t_end <= t]
        last = res[-REC_K:]
        return {"n_earlier": len(earlier), "n_resolved": len(res),
                "record_mean": float(np.mean([p.ret for p in last])) if last else None,
                "record_rets": [p.ret for p in last]}


@dataclass
class Registry:
    deployers: Deployers
    records: Records

    def state(self, snap: C.AsOf) -> dict:
        """status: unknown | shared | new | pending | eligible (PREREG 3)."""
        cr = _nz(snap.get("creator"))
        if cr is None:
            return {"status": "unknown"}
        cr = str(cr)
        why = self.deployers.shared(cr, snap.tau)
        if why:
            return {"status": "shared", "reason": why, "creator": cr}
        q = self.records.query(cr, snap.g, snap.mint, snap.t)
        st = "new" if q["n_earlier"] == 0 else ("pending" if q["n_resolved"] == 0 else "eligible")
        return {"status": st, "creator": cr, **q}


def deployer_rows_from_frames(graduates: pd.DataFrame, census: C.Census, lo: float, hi: float) -> list[dict]:
    """Structural pool (PREREG 2.1): every graduate (any quote / Mayhem) created in [lo, hi), read through AsOf."""
    g = C._normalize_graduates(graduates, census)
    g = g[(g["created_for_split"] >= lo) & (g["created_for_split"] < hi)]
    pooled = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
    empty = pd.DataFrame(columns=["minute_ts", "open", "high", "low", "close", "x_close", "y_close"])
    rows = []
    for r in g.to_dict("records"):
        cd = C._make_coin(r, empty, None, pooled)
        cr, u, _ = _creator_at_g(cd)
        rows.append({"mint": cd.mint, "g": cd.g, "creator": cr, "signer": u})
    return rows


def deployer_rows_from_datasets(datasets: Iterable[C.Dataset]) -> list[dict]:
    rows = []
    for ds in datasets:
        for m in ds.mints:
            cd = ds.coin(m)
            cr, u, _ = _creator_at_g(cd, ds.sol)
            rows.append({"mint": m, "g": cd.g, "creator": cr, "signer": u})
    return rows


def build_registry(history: Sequence[C.Dataset], structure_rows: Iterable[Mapping[str, Any]] | None = None) -> Registry:
    """Records from the history datasets; deployer structure from ``structure_rows`` (production: every graduate of
    the structural pool) or, without them, from the history datasets' usable coins."""
    rows = list(structure_rows) if structure_rows is not None else deployer_rows_from_datasets(history)
    return Registry(deployers=Deployers.from_rows(rows), records=Records.from_datasets(history))


# =========================================================================== strategy, placebo


def exit_spec(name: str) -> C.ExitSpec:
    return C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=EXIT_HOLD_S[name], exit_by_age_s=EXIT_BY_AGE_S)


def make_strategy(reg: Registry):
    """The Y1 strategy for common.backtest (one entry per coin; exits are mechanical)."""

    def y1_strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
        if pos is not None:
            return None
        if snap.age_s < E_AGE_S:
            return None
        if snap.age_s > E_AGE_MAX_S:
            return C.SKIP
        st = reg.state(snap)
        s = st["status"]
        if s in ("unknown", "shared", "new"):
            return C.SKIP                 # static: no earlier graduate can appear, a NULL never becomes known here
        if s == "pending":
            return None
        rec = float(st["record_mean"])
        if p["rule"] == "host" or rec >= float(p["theta"]):
            return C.Enter(exits=exit_spec(p["exit"]), tag="bad" if rec < 0 else "good",
                           state={"record_mean": rec, "n_resolved": st["n_resolved"]})
        if st["n_resolved"] >= st["n_earlier"]:
            return C.SKIP                 # every earlier graduate resolved and the record is below theta
        return None

    return y1_strategy


def placebo_eligible(snap: C.AsOf) -> bool:
    """Placebo entries are post-BOOST like the signals."""
    return snap.age_s >= E_AGE_S


def make_stratum(reg: Registry):
    def eligible_stratum(snap: C.AsOf) -> str:
        """The judged placebo draws only repeat-deployer coins with a resolved record at the draw's own time."""
        return "eligible" if snap.age_s >= E_AGE_S and reg.state(snap)["status"] == "eligible" else "other"
    return eligible_stratum


PLACEBO_CONTROLS = {"unmatched": {"eligible": placebo_eligible, "strata": None}}


# =========================================================================== scans, persistence gate, clusters


def scan_coins(ds: C.Dataset, reg: Registry, with_label: bool = False) -> pd.DataFrame:
    """Per coin: status at its first post-BOOST decision and its first eligible decision t_e in the entry window.
    ``with_label`` adds the LABEL (its own mid change over the next 30 min, read through AsOf at t_e + 30 min)."""
    rows = []
    for m in ds.mints:
        cd = ds.coin(m)
        t = grid_time_from(cd, cd.g + E_AGE_S)
        first = None
        row: dict[str, Any] = {"mint": m, "g": cd.g}
        while t - cd.g <= E_AGE_MAX_S:
            snap = ds.asof(m, t)
            st = reg.state(snap)
            if first is None:
                first = st
                row.update(first_status=st["status"], shared_reason=st.get("reason"), creator=st.get("creator"))
            if st["status"] in ("unknown", "shared", "new"):
                break
            if st["status"] == "eligible":
                row.update(t_e=t, age_e_min=(t - cd.g) / 60.0, score=st["record_mean"], n_resolved=st["n_resolved"])
                if with_label:
                    later = ds.asof(m, t + H_REC_S)
                    row["label"] = later.price / snap.price - 1.0
                break
            t += 60.0
        rows.append(row)
    cols = ["mint", "g", "first_status", "shared_reason", "creator", "t_e", "age_e_min", "score", "n_resolved"]
    if with_label:
        cols.append("label")
    return pd.DataFrame(rows).reindex(columns=cols)


def persistence_gate(obs: pd.DataFrame, clusters: Mapping[str, str], *, first_g: float | None, B: int = PG_B,
                     hide: bool = False, seed: int = 0) -> dict:
    """Stop rule (PREREG 8). ``obs`` rows with a score and a label. ``hide`` (debug): counts only."""
    o = obs.dropna(subset=["score"]).reset_index(drop=True)
    cl = o["mint"].map(clusters).fillna(o["mint"]).to_numpy(object) if len(o) else np.zeros(0, object)
    out: dict[str, Any] = {"n_obs": int(len(o)), "n_clusters": int(len(set(cl.tolist()))),
                           "n_creators": int(o["creator"].nunique()) if len(o) else 0,
                           "need": {"obs": PG_MIN_OBS, "clusters": PG_MIN_CLUSTERS}}
    if first_g is not None and len(o):
        out["n_warmup"] = int((o["t_e"] - first_g < WARMUP_S).sum())
    if hide:
        out["decision"] = "HIDDEN (debug split: no outcome statistics)"
        return out
    x, y = o["score"].to_numpy(float), o["label"].to_numpy(float) if len(o) else np.zeros(0)
    rho = spearman(x, y) if len(o) else None
    out["rho"] = rho
    ci = None
    if len(o) >= 3 and len(set(cl.tolist())) >= 2:
        codes, uniq = pd.factorize(pd.Series(cl))
        groups = [np.flatnonzero(codes == i) for i in range(len(uniq))]
        rng = np.random.default_rng(seed)
        bs = []
        for _ in range(B):
            idx = np.concatenate([groups[i] for i in rng.integers(0, len(uniq), len(uniq))])
            r = spearman(x[idx], y[idx])
            if r is not None:
                bs.append(r)
        if len(bs) >= 10:
            ci = (float(np.quantile(bs, 0.05)), float(np.quantile(bs, 0.95)))
    out["rho_ci90_cluster"] = ci
    if out["n_obs"] < PG_MIN_OBS or out["n_clusters"] < PG_MIN_CLUSTERS:
        out["decision"] = "UNDERPOWERED"
    elif rho is None or rho <= 0 or ci is None or ci[0] <= 0:
        out["decision"] = "KILL"
    else:
        out["decision"] = "PASS"
    pos, neg = o[o["score"] >= 0], o[o["score"] < 0]
    nw = o[o["t_e"] - first_g >= WARMUP_S] if first_g is not None else o
    out["diagnostics"] = {
        "label_mean_record_ge0": float(pos["label"].mean()) if len(pos) else None, "n_record_ge0": int(len(pos)),
        "label_mean_record_lt0": float(neg["label"].mean()) if len(neg) else None, "n_record_lt0": int(len(neg)),
        "rho_without_warmup": spearman(nw["score"], nw["label"]) if len(nw) else None, "n_without_warmup": int(len(nw)),
    }
    return out


def cluster_map(datasets: Sequence[C.Dataset]) -> dict[str, str]:
    """Deployer clusters (PREREG 11): connected components of coins sharing a creator or an upper-cased symbol (a
    grouping for the bootstrap, never a feature). Coins without either are their own cluster."""
    parent: dict[str, str] = {}

    def find(a: str) -> str:
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    mints = []
    for ds in datasets:
        for m in ds.mints:
            node = "m:" + m
            find(node)
            mints.append(m)
            cr, _, sy = _creator_at_g(ds.coin(m), ds.sol)
            if cr is not None:
                union(node, "c:" + str(cr))
            if sy is not None and str(sy).strip():
                union(node, "s:" + str(sy).strip().upper())
    return {m: find("m:" + m) for m in mints}


# =========================================================================== evaluation


def _cluster_stats(t: pd.DataFrame, clusters: Mapping[str, str], B: int) -> dict:
    if not len(t):
        return {"n_clusters": 0, "ci90_cluster": None, "largest_cluster": None, "mean_without_largest": None}
    cl = t["mint"].map(clusters).fillna(t["mint"]).to_numpy(object)
    r = t["ret_net"].to_numpy(float)
    vc = pd.Series(cl).value_counts()
    prof = pd.Series(r).groupby(cl).sum()
    big = sorted(vc.index, key=lambda c: (-int(vc[c]), -float(prof[c]), str(c)))[0]
    rest = r[cl != big]
    return {"n_clusters": int(len(vc)), "ci90_cluster": C.coin_bootstrap_ci(r, cl, 0.90, B),
            "largest_cluster": {"id": str(big), "trades": int(vc[big]), "share_of_trades": float(vc[big] / len(r))},
            "mean_without_largest": float(rest.mean()) if len(rest) else None}


def evaluate(res: C.Result, clusters: Mapping[str, str], *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. Debug split: status and eligibility counts only (review Y1-3). A HOST config enters every
    eligible coin, so its n / coins / clusters / placebo draws / horizon exits are eligibility counts. Trade tags and
    every GOOD-config count are hidden: a tag is the sign of a record (the post-BOOST mid change of an earlier coin of
    the debug third) and a GOOD(theta) count is the number of records >= theta."""
    t = res.trades
    p = res.meta["params"]
    cens = (t["reason"] == "horizon").to_numpy(bool) if len(t) else np.zeros(0, bool)
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide and p["rule"] != "host":
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        base["counts"] = "hidden on the debug split (a GOOD count is the number of records >= theta: a return sign)"
        return base
    base.update({"n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
                 "n_clusters": int(pd.Series(t["mint"].map(clusters)).nunique()) if len(t) else 0,
                 "entry_age_min_median": float(t["age_dec_s"].median() / 60.0) if len(t) else None,
                 "n_placebo": int(len(res.placebo)),
                 "placebo_draws_per_signal": float(len(res.placebo) / len(t)) if len(t) else None,
                 "horizon_exits": int(cens.sum())})
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["tags"] = t["tag"].value_counts().to_dict() if len(t) else {}
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
    base["clusters"] = _cluster_stats(t, clusters, B)
    base["by_tag"] = {k: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for k, g in t.groupby("tag")} \
        if len(t) else {}
    return base


def veto_eval(host: pd.DataFrame, *, B: int, hide: bool, oos: pd.DataFrame | None = None,
              oos_is_self: bool = False) -> dict:
    """The bad-record veto on host trades (PREREG 6): flagged = tag 'bad'. ``oos`` = out-of-sample host trades
    (criterion 2); ``oos_is_self`` (CONFIRM) uses the same never-searched trades for every criterion."""
    f = (host["tag"] == "bad").to_numpy(bool) if len(host) else np.zeros(0, bool)
    out: dict[str, Any] = {"flag": VETO_RULE, "n_host": int(len(host))}
    if hide:            # review Y1-3: flagged / unflagged counts are record signs (returns) of the debug third
        out["flags"] = "hidden on the debug split (a flag is the sign of an earlier coin's record)"
        return out
    out.update(n_flagged=int(f.sum()), n_unflagged=int((~f).sum()))
    r = host["ret_net"].to_numpy(float) if len(host) else np.zeros(0)
    out["flagged_mean"] = float(r[f].mean()) if f.any() else None
    out["unflagged_mean"] = float(r[~f].mean()) if (~f).any() else None
    if oos_is_self:
        oos = host
    of = None if oos is None else (oos["tag"] == "bad").to_numpy(bool)
    if oos is not None and not oos_is_self:
        out["n_oos"], out["n_oos_flagged"] = int(len(oos)), int(of.sum())
    out["verdict"] = C.verdict_veto(host, f, oos_host=oos, oos_flagged=of, B=B) if len(host) else \
        {"verdict": "UNDERPOWERED", "n_flagged": 0, "n_unflagged": 0, "criteria": []}
    return out


def y1_extras(ev: Mapping[str, Any]) -> list[dict]:
    cl = ev.get("clusters") or {}
    out = [{"id": "Y1.1", "name": f"power: >= {PASS_MIN_TRADES} trades from >= {PASS_MIN_CLUSTERS} deployer clusters",
            "pass": bool(ev["n"] >= PASS_MIN_TRADES and ev["n_clusters"] >= PASS_MIN_CLUSTERS),
            "value": {"n": ev["n"], "clusters": ev["n_clusters"]}}]
    ci = cl.get("ci90_cluster")
    out.append({"id": "Y1.2", "name": "90% CI lower bound > 0 resampling deployer clusters",
                "pass": None if not ci else bool(ci[0] > 0), "value": ci})
    mw = cl.get("mean_without_largest")
    out.append({"id": "Y1.3", "name": "mean > 0 without the largest deployer cluster",
                "pass": None if mw is None else bool(mw > 0), "value": mw})
    return out


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 + 10 (common.verdict_entry) and the Y1 extras. Item 9 (FINAL) is judged after FINAL."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1) or extras[0]["pass"] is False:
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or any(e["pass"] is False for e in extras[1:]):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(e["pass"] is None for e in extras[1:]):
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def _shortlist_doc(verdict: str, cand: dict, rows: list[dict], **extra) -> dict:
    host = make_params("host", cand["exit"])
    return {"verdict": verdict, "chosen": config_key(cand), "rows": rows, **extra,
            "shortlist": {HYP: [cand], HYP_HOST: [host]},
            "shortlist_hashes": {HYP: [C.params_hash(cand)], HYP_HOST: [C.params_hash(host)]}}


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 9 TRAIN: qualify GOOD configs; pick the highest deployer-cluster 90 % CI lower bound; shortlist it and
    HOST with the same exit (for the veto). When no GOOD config is powered (the expected TRAIN outcome, PREREG 14) the
    pre-registered FIXED path shortlists GOOD(FIXED_THETA) / FIXED_EXIT and its host without reading TRAIN returns;
    VAL and TEST are then reported only and CONFIRM is the judged look (review Y1-2). Only reached after the
    persistence gate PASSed."""
    rows = []
    for p in GRID_GOOD:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_clusters"] >= TRAIN_MIN_CLUSTERS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0)
        ci = (e.get("clusters") or {}).get("ci90_cluster")
        rows.append({"config": config_key(p), "theta": p["theta"], "exit": p["exit"], "powered": powered,
                     "qualifies": bool(good), "n": e["n"], "clusters": e["n_clusters"], "mean": e.get("mean"),
                     "ci90_cluster_lo": ci[0] if ci else None, "placebo_diff": pc})
    q = [r for r in rows if r["qualifies"]]
    if q:
        best = sorted(q, key=lambda r: (-(r["ci90_cluster_lo"] if r["ci90_cluster_lo"] is not None else -math.inf),
                                        -r["mean"], -r["theta"], EXIT_GRID.index(r["exit"])))[0]
        return _shortlist_doc("SHORTLISTED", make_params("good", best["exit"], best["theta"]), rows, path="selected")
    if any(r["powered"] for r in rows):
        return {"verdict": "NO_CONFIG", "reason": "a powered GOOD config failed the mean / top-2 / matched-control bars",
                "rows": rows, "shortlist": {}, "shortlist_hashes": {}}
    why = (f"no GOOD config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_CLUSTERS} deployer clusters "
           f"(best: {max(r['n'] for r in rows)} trades, {max(r['clusters'] for r in rows)} clusters): the "
           f"pre-registered fixed path (PREREG 9) carries GOOD(theta={FIXED_THETA:g}) / {FIXED_EXIT}, chosen a priori, "
           f"to one judged CONFIRM look; VAL and TEST are reported only")
    return _shortlist_doc("SHORTLISTED_FIXED", make_params("good", FIXED_EXIT, FIXED_THETA), rows, path="fixed",
                          reason=why)


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


def confirm_allowed(test_doc: Mapping[str, Any], fixed: bool = False) -> tuple[bool, str]:
    """CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence). On the fixed path
    (PREREG 9) TEST is reported only: just a REJECTED (structural, PLAN 3.6) stops CONFIRM."""
    v = (test_doc.get("verdict") or {})
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    if fixed:
        return True, "ok (fixed path: TEST reported only)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Y1 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds Y1 never looked at; the debug third is reported apart."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    design = t[t["split"] == FINAL_DESIGN] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "design_third": {"n": int(len(design)), "mean": float(design["ret_net"].mean()) if len(design) else None,
                             "note": "census TRAIN third: the debug third, not judged"}}


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


def stage_configs(stage: str, shortlist_path: Path | None = None) -> list[tuple[str, str, dict]]:
    """[(role, hypothesis, params)] the stage runs."""
    if stage in ("debug", "train"):
        return [(config_key(p), hyp_of(p), p) for p in GRID]
    sl, slh = _shortlist(HYP, shortlist_path), _shortlist(HYP_HOST, shortlist_path)
    if not sl or not slh:
        return []
    return [("candidate", HYP, sl["configs"][0]), ("host", HYP_HOST, slh["configs"][0])]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Y1Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Y1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Y1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Y1Refused("PREREG.md changed after the first official TRAIN run; record changes in Y1/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Y1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Y1Refused("TRAIN already ran on complete data (Y1/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Y1Refused("no TRAIN result (Y1/train.json): run --stage train first")
    if train.get("provisional"):
        raise Y1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_PERSISTENCE":
        raise Y1Refused("Y1 is dead: the persistence gate failed on TRAIN (stop rule)")
    if tv not in SHORTLISTED:
        raise Y1Refused(f"TRAIN decision {tv}: Y1 stopped before VAL")
    fixed = tv == "SHORTLISTED_FIXED"
    info["path"] = "fixed" if fixed else "selected"
    want = train["decision"].get("shortlist_hashes") or {}
    for h in (HYP, HYP_HOST):
        sl = _shortlist(h, shortlist_path)
        if not sl:
            raise Y1Refused(f"no VAL shortlist for {h} (written by a complete --stage train)")
        if sorted(sl.get("hashes", [])) != sorted(want.get(h, [])):
            raise Y1Refused(f"the {h} shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Y1Refused("VAL already ran (Y1/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise Y1Refused("no VAL result (Y1/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL and not fixed:           # the fixed path reports VAL, never stops on it
            raise Y1Refused(f"VAL decision {vv}: Y1 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Y1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok2, why = confirm_allowed(test, fixed=fixed)
        if not ok2:
            raise Y1Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Y1Refused(f"{stage.upper()} already ran (Y1/{stage}.json exists): one run per hypothesis")
    for h in (HYP, HYP_HOST):
        if any(r.get("hypothesis") == h and C.split_group(r.get("split", "")) == C.split_group(split)
               and not r.get("debug") for r in _runs(ledger_path)):
            raise Y1Refused(f"{h} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Y1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def _hist_bounds(stage: str, census: C.Census) -> tuple[float, float]:
    """[first history split start, stage split end): the structural pool's creation range (PREREG 2.1)."""
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
    """The stage's own dataset plus the other history splits (PREREG 2.1). Other splits are read for their OUTCOME
    records only, through a counts-level loader (never handed to a strategy); each is earlier in time and already
    open at this stage (enforced by check_prereqs' order: VAL before TEST, TEST before FINAL)."""
    if history is not None:
        return [ds] + list(history)
    own = set(C.FINAL_SPLITS) if ds.split == "final" else {ds.split}
    out = [ds]
    for s in HISTORY_SPLITS[stage]:
        if s not in own:
            out.append(C.coverage_dataset(s, flow, census))
    return out


def event_counts(scan: pd.DataFrame, span_days: float) -> dict:
    """Counts only (no prices, no returns)."""
    fs = scan["first_status"].fillna("none")
    elig = scan["t_e"].notna()
    out = {"coins": int(len(scan)), "first_status": {str(k): int(v) for k, v in fs.value_counts().items()},
           "shared_reasons": {str(k): int(v) for k, v in scan["shared_reason"].dropna().value_counts().items()},
           "eligible_in_window": int(elig.sum()),
           "eligible_creators": int(scan.loc[elig, "creator"].nunique()),
           "eligible_age_min_median": float(scan.loc[elig, "age_e_min"].median()) if elig.any() else None,
           "eligible_n_resolved": {str(int(k)): int(v) for k, v in
                                   scan.loc[elig, "n_resolved"].value_counts().sort_index().items()}}
    out["eligible_per_day"] = out["eligible_in_window"] / span_days if span_days == span_days and span_days > 0 else None
    return out


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, history: Sequence[C.Dataset] | None = None,
              structure_rows: Sequence[Mapping[str, Any]] | None = None, census: C.Census | None = None,
              flow: Path | None = None, ledger_path: Path | None = None, shortlist_path: Path | None = None,
              B: int = 10_000, n_placebo: int = 20, env: Mapping[str, str] | None = None,
              _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Y1/<stage>.json + .md (``ds`` / ``history`` / ``structure_rows``
    injection is for tests: without ``structure_rows`` an injected run builds the deployer structure from the
    history datasets)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "y1_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Y1Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise Y1Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise Y1Refused("no configs to run (shortlist missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Y1Refused(str(e)) from e
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
        # an injected dataset (tests) never pulls real history from FLOW: its history is what the caller passes
        hist = history_datasets(stage, ds, flow, cen, history if history is not None else ([] if injected else None))
        rows = structure_rows
        if rows is None and not injected:
            lo, hi = _hist_bounds(stage, cen)
            f = Path(flow or C.flow_dir())
            rows = deployer_rows_from_frames(C._read_parquet(f / "graduates.parquet"), cen, lo, hi)
        reg = build_registry(hist, rows)
        clusters = cluster_map(hist)
        span = _span_days(ds)
        scan = scan_coins(ds, reg, with_label=(stage in ("train", "debug")) and not debug)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "n_coins": len(ds), "span_days": span,
                               "history": {"splits": [h.split for h in hist], "coins": reg.records.n_coins,
                                           "records": reg.records.n_priors,
                                           "creators_with_records": len(reg.records.by_creator),
                                           "structure_coins": reg.deployers.n_coins,
                                           "first_history_g_utc": C.utc_str(reg.records.first_g)},
                               "event_counts": event_counts(scan, span)}
        # ---- persistence gate (TRAIN: before any P&L; debug: counts only)
        if stage in ("train", "debug"):
            obs = scan[scan["t_e"].notna()]
            pg = persistence_gate(obs, clusters, first_g=reg.records.first_g, B=min(B, PG_B), hide=debug)
            pg["trial"] = C.record_run(HYP_PERSIST, PERSIST_PARAMS, split, {"n": pg["n_obs"], "mean": None},
                                       ledger_path, debug=debug)
            doc["persistence"] = pg
            if not debug and pg["decision"] != "PASS":
                v = "KILLED_PERSISTENCE" if pg["decision"] == "KILL" else "UNDERPOWERED_PERSISTENCE"
                doc["decision"] = {"verdict": v, "shortlist_written": False,
                                   "note": "the persistence gate precedes any P&L; the grid was not run"}
                return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
        strategy = make_strategy(reg)
        stratum = make_stratum(reg)
        results: dict[str, C.Result] = {}
        for role, h, p in configs:
            results[role] = C.backtest(strategy, split, p, hypothesis=h, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_eligible, placebo_strata=stratum,
                                       placebo_controls=PLACEBO_CONTROLS, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, clusters, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if debug:
            doc["entries_per_day"] = {k: (e["n"] / span if "n" in e and span == span and span > 0 else None)
                                      for k, e in evals.items()}
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        # ---- the bad-record veto (PREREG 6)
        if stage in ("train", "debug"):
            doc["veto"] = {}
            for p in GRID_HOST:
                k = config_key(p)
                ve = veto_eval(results[k].trades, B=min(B, 4000), hide=debug)
                ve["trial"] = C.record_run(HYP_VETO, veto_params(p["exit"]), split,
                                           {"n": ve["n_host"], "mean": None}, ledger_path, debug=debug)
                doc["veto"][k] = ve
        elif stage == "val":
            doc["veto"] = veto_eval(results["host"].trades, B=min(B, 4000), hide=False)
        elif stage == "test":
            val_host = _read_trades(out_dir, "val", "host")
            doc["veto"] = veto_eval(val_host if val_host is not None else C._frame([]), B=min(B, 4000), hide=False,
                                    oos=results["host"].trades)
        elif stage == "confirm":
            doc["veto"] = veto_eval(results["host"].trades, B=min(B, 4000), hide=False, oos_is_self=True)
        # ---- decisions
        if debug:
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] in SHORTLISTED and not provisional:
                for h in (HYP, HYP_HOST):
                    C.write_shortlist(h, dec["shortlist"][h], path=shortlist_path, ledger_path=ledger_path,
                                      note=f"{VERSION}: PREREG 9 {dec['path']} path, chosen {dec['chosen']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            doc["decision"] = decide_val(evals["candidate"])
            if info.get("path") == "fixed":
                doc["decision"]["note"] = "fixed path (PREREG 9): VAL is reported only and never stops Y1"
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", "candidate")
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = y1_extras(evals["candidate"])
            doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "y1_extras": extras}
            if stage == "test" and info.get("path") == "fixed":
                doc["verdict"]["note"] = "fixed path (PREREG 9): TEST is reported only; CONFIRM is the judged look"
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
            doc["host_final"] = final_decision(results["host"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"y1 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise Y1Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"]), hypothesis=r.meta["hypothesis"])
              for role, r in results.items()]
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if not p.exists():
        return None
    t = pd.read_csv(p)
    return t[t["role"] == role].reset_index(drop=True)


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
    if tv == "KILLED_PERSISTENCE":
        return "KILLED (creator quality does not persist on TRAIN)"
    if tv == "UNDERPOWERED_PERSISTENCE":
        return "UNDERPOWERED (too few eligible repeat-deployer coins for the persistence gate on TRAIN)"
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)"
    if tv == "NO_CONFIG":
        return "NO EDGE (nothing qualified on TRAIN)"
    fixed = tv == "SHORTLISTED_FIXED"               # VAL and TEST are reported only on the fixed path
    va = doc("val")
    if not va:
        return "PENDING VAL"
    vv = (va.get("decision") or {}).get("verdict")
    if vv == "FAIL_VAL" and not fixed:
        return "NO EDGE (failed VAL; PLAN 8 rule 7 input)"
    if vv == "UNDERPOWERED_VAL" and not fixed:
        return "UNDERPOWERED (VAL)"
    te = doc("test")
    if not te:
        return "PENDING TEST"
    ok, why = confirm_allowed(te, fixed=fixed)
    if not ok:
        return f"NO EDGE ({why})"
    co = doc("confirm")
    if not co:
        return "PENDING CONFIRM"
    cv = (co.get("verdict") or {}).get("verdict")
    if cv == "UNDERPOWERED":
        return "UNDERPOWERED (CONFIRM)"
    if cv != "PASS":
        return f"NO EDGE (CONFIRM {cv})"
    fi = doc("final")
    if not fi:
        return "PENDING FINAL"
    return "EDGE" if (fi.get("decision") or {}).get("mean_positive") else "NO EDGE (FINAL mean <= 0)"


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    h = doc.get("history") or {}
    L = [f"# Y1 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **History** (outcome records): splits {h.get('splits')}; {h.get('coins')} coins, {h.get('records')} "
         f"records from {h.get('creators_with_records')} creators; structural pool {h.get('structure_coins')} "
         f"graduates; first history graduation {h.get('first_history_g_utc')} UTC.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Y1 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter "
              "was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        epd = ec.get("eligible_per_day")
        age = ec.get("eligible_age_min_median")
        epd_s = "n/a" if epd is None else f"{epd:.1f}"
        age_s = "n/a" if age is None else f"{age:.1f}"
        L += ["## Event counts (no returns)", "",
              f"- Status at the first post-BOOST decision: {ec['first_status']}; shared keys by rule: "
              f"{ec['shared_reasons'] or '{}'}.",
              f"- Coins eligible inside the entry window (repeat deployer, ≥ 1 resolved record): "
              f"{ec['eligible_in_window']} ({epd_s} per day) from {ec['eligible_creators']} creators; median eligible "
              f"age {age_s} min; resolved records at eligibility: {ec['eligible_n_resolved']}.", ""]
    pg = doc.get("persistence")
    if pg:
        L += ["## Persistence gate (stop rule, PREREG 8)", "",
              f"- Observations: {pg['n_obs']} from {pg.get('n_creators')} creators in {pg['n_clusters']} deployer "
              f"clusters (need ≥ {PG_MIN_OBS} and ≥ {PG_MIN_CLUSTERS}); warm-up observations: {pg.get('n_warmup')}.",
              f"- Decision: **{pg['decision']}**."]
        if "rho" in pg:
            L.append(f"- Spearman ρ(record, next 30 min) = {pg['rho']}; deployer-cluster 90% CI "
                     f"{pg.get('rho_ci90_cluster')}; diagnostics {pg.get('diagnostics')}.")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | clusters | placebo draws/signal | horizon exits | entries/day |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                if "n" not in e:          # GOOD configs: their counts are record signs (review Y1-3)
                    L.append(f"| {e['config']} | hidden | hidden | hidden | hidden | hidden | hidden |")
                    continue
                epd = (doc.get("entries_per_day") or {}).get(k)
                pds = e.get("placebo_draws_per_signal")
                pds_s = "n/a" if pds is None else f"{pds:.1f}"
                epd_s = "n/a" if epd is None else f"{epd:.1f}"
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['n_clusters']} | "
                         f"{pds_s} | {e['horizon_exits']} | {epd_s} |")
            L += ["", "GOOD-config counts, trade tags and veto flags are hidden on the debug split: each is the sign "
                  "of an earlier coin's record (review Y1-3)."]
        else:
            L += ["| role | config | n | clusters | mean | 90% CI coin | 90% CI 6-h block | 90% CI cluster | w/o top 2 | "
                  "placebo diff (eligible) | placebo diff (unmatched) | costs ×1.5 |",
                  "|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|"]
            for k, e in cf.items():
                cl = e.get("clusters") or {}
                pc = (e.get("placebo") or {}).get("mean_diff")
                pu = (e.get("placebo_unmatched") or {}).get("mean_diff")
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_clusters']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_ci(cl.get('ci90_cluster'))} | "
                         f"{_pct(e.get('mean_without_top2'))} | {_pct(pc)} | {_pct(pu)} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} |")
        L.append("")
    ve = doc.get("veto")
    if ve:
        L += ["## Bad-record veto (PREREG 6)", ""]
        items = ve.items() if "flag" not in ve else [("host", ve)]
        for k, v in items:
            line = (f"- {k}: host trades {v['n_host']}, flagged {v['n_flagged']}, unflagged {v['n_unflagged']}"
                    if "n_flagged" in v else f"- {k}: host trades {v['n_host']}; flags hidden on the debug split")
            if "verdict" in v:
                line += (f"; flagged mean {_pct(v.get('flagged_mean'))}, unflagged mean {_pct(v.get('unflagged_mean'))}; "
                         f"verdict **{v['verdict'].get('verdict')}**")
            L.append(line + ".")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, clusters {r['clusters']}, mean {_pct(r['mean'])}, 90% CI cluster low "
                 f"{_pct(r['ci90_cluster_lo'])}, placebo diff {_pct(r['placebo_diff'])}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlists written: {dec['shortlist_written']}"
                 + (f" (chosen {dec['chosen']} + its host)" if dec.get("chosen") else "") + ".")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("y1_extras", []):
            L.append(f"- {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    for key in ("reason", "note"):
        if dec.get(key):
            L.append(f"- {dec[key]}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Y1 creator reputation: pre-registered stages; see research/lab2/Y1/PREREG.md")
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
    except Y1Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

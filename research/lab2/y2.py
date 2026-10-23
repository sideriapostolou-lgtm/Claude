"""Y2: buy the graduates whose curve was filled organically (curve-phase organic share).

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Y2/PREREG.md``.

Mechanism
---------
Who bought the 793.1M curve tokens decides who holds cheap inventory at graduation. Insider-filled curves (creation
bundle, 60-s snipers, one whale finishing the last 30 SOL, three wallets paying most of the SOL) leave a few wallets
with most of the float at a low cost, which they distribute after migration. Organically filled curves spread the
float over many small buyers who paid near the graduation price. Y2 ranks non-instant graduates by how organic their
curve was, against the graduates of the trailing 24 h, and buys the top group at g + 30 min if the coin is alive.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s). Curve-life columns are legal at g;
``z_*`` / ``sn60_*`` at min(created + 120 s, g); NULL stays None (a NULL makes the coin ineligible, never 0). The
reference pool reads every other graduate through AsOf at its own g (tau = g), keeps only graduates with
g in (tau - 24 h, tau] that were created before the end of the split being run, and never the coin itself.

Selectors (PREREG 5): T3 = top tercile of the organic rank, T5 = top quintile, PE11 = the craft-rule PE-11 "fast
organic" cell (5 s < grad delay <= 300 s, >= 15 curve buyers, top-3 share < 0.6). ALL = every eligible alive coin
(the dose-response diagnostic, never shortlisted). Exits (PREREG 6): X60 = -50 % stop + 60 min; H178 = -50 % stop +
sell at g + 178 min. Fills: common.FillConfig(exit_delay_bars=1) -- worst minute-bar fills, exits in the next bar.

CLI::

    python research/lab2/y2.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/y2.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/y2.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/y2.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/y2.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/y2.py --stage final
    python research/lab2/y2.py --stage val --check             # prerequisites only

Each stage writes ``Y2/<stage>.json`` and ``Y2/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlist, TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL before TEST, PLAN 8
data gates V1-V4, the reference pool's 24 h before the split start scanned, PREREG frozen after the first official
TRAIN run).
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

VERSION = "y2-v1"
OUT_DIR = HERE / "Y2"
HYP = "Y2"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 3-7)
INSTANT_MAX_DELAY_S = 5.0        # grad delay <= 5 s: one creator buy filled the curve (no organic side)
CURVE_SUPPLY_TOK = 793.1e6       # tokens sold by a pump.fun curve
COMPLETER_WINDOW_SOL = 30.0      # the last 30 SOL of the curve (PLAN COMPLETER)
COMPONENTS = ("breadth", "top3_share", "completer_share", "bundle_share", "sniper_share")
ORGANIC_HIGH = (True, False, False, False, False)   # the organic side of each component
REF_LOOKBACK_S = 86400.0         # reference pool: graduates of the trailing 24 h (one daily cycle)
REF_MIN_COINS = 50               # fewer reference coins -> the rank is cold (never entered by T3 / T5)
REF_WARM_MIN = 0.99              # share of the lookback's clock hours fully scanned for graduates
TOP_TERCILE, BOTTOM_TERCILE, TOP_QUINTILE = 2.0 / 3.0, 1.0 / 3.0, 0.8
PE11_MIN_DELAY_S, PE11_MAX_DELAY_S = 5.0, 300.0      # PE-11 "fast organic": 5 s - 5 min
PE11_MIN_BUYERS, PE11_MAX_TOP3 = 15, 0.6             # >= 15 curve buyers, top-3 share < 0.6
ENTRY_AGE_S = 1800.0             # one decision: the first grid time at age >= 30 min
STOP_PCT = 0.50                  # catastrophe stop (PLAN X1 exit 6)
HOLD_X60_S = 3600.0
EXIT_BY_AGE_S = 178 * 60.0       # registered deadline: sell no later than g + 178 min (fills by g + 179, inside B2)
SIZE_USD = 20.0
SELECTORS = ("T3", "T5", "PE11")
EXIT_SETS = ("X60", "H178")
DOSE_SELECTOR, DOSE_EXIT = "ALL", "H178"
# selection and verdict bars
TRAIN_MIN_TRADES = 30
SHORTLIST_MAX = 2
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03             # PLAN 3.5 default
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FILL = C.FillConfig(exit_delay_bars=1)                # worst fills; every triggered exit fills in the next bar
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": C.FillConfig()}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}

FIXED = {
    "version": VERSION, "components": list(COMPONENTS), "organic_high": list(ORGANIC_HIGH),
    "instant_max_delay_s": INSTANT_MAX_DELAY_S, "curve_supply_tok": CURVE_SUPPLY_TOK,
    "completer_window_sol": COMPLETER_WINDOW_SOL, "ref_lookback_s": REF_LOOKBACK_S, "ref_min_coins": REF_MIN_COINS,
    "ref_warm_min": REF_WARM_MIN, "top_tercile": TOP_TERCILE, "top_quintile": TOP_QUINTILE,
    "pe11": {"min_delay_s": PE11_MIN_DELAY_S, "max_delay_s": PE11_MAX_DELAY_S, "min_buyers": PE11_MIN_BUYERS,
             "max_top3": PE11_MAX_TOP3},
    "entry_age_s": ENTRY_AGE_S, "alive": "AsOf.alive(): 15-min USD volume >= 1500 and mcap >= 6000 USD",
    "stop_pct": STOP_PCT, "hold_x60_s": HOLD_X60_S, "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD,
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stops, exits in the next bar",
    "placebo": "eligible and alive, +-120 s, 20 draws",
}


def make_params(selector: str, exit_set: str) -> dict:
    if selector not in SELECTORS + (DOSE_SELECTOR,):
        raise ValueError(f"selector {selector!r} not in {SELECTORS + (DOSE_SELECTOR,)}")
    if exit_set not in EXIT_SETS:
        raise ValueError(f"exit set {exit_set!r} not in {EXIT_SETS}")
    return {**FIXED, "selector": selector, "exit": exit_set}


GRID = [make_params(s, e) for s in SELECTORS for e in EXIT_SETS]
DOSE_PARAMS = make_params(DOSE_SELECTOR, DOSE_EXIT)
TRIAL_CONFIGS = GRID + [DOSE_PARAMS]


class Y2Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['selector']}|{p['exit']}"


# =========================================================================== features (AsOf only)


def _truthy(v: Any) -> bool | None:
    return None if v is None else bool(v)


def coin_features(snap: C.AsOf) -> dict:
    """Eligibility (PREREG 3) and the five components (PREREG 4) as of ``snap``.

    -> {eligible, reason, grad_delay_s, comps (5-tuple, raw values), top3_share, n_buyers, pe11}."""
    out: dict[str, Any] = {"eligible": False, "reason": None, "grad_delay_s": None, "comps": None,
                           "top3_share": None, "n_buyers": None, "pe11": False}
    if _truthy(snap.get("sol_quoted")) is not True or _truthy(snap.get("mayhem")) is not False:
        out["reason"] = "not_tradeable"
        return out
    if _truthy(snap.get("curve_partial")) is not False:
        out["reason"] = "curve_partial"          # creation not scanned: curve-life columns are NULL
        return out
    d = snap.get("grad_delay_s")
    if d is None:
        out["reason"] = "delay_null"
        return out
    out["grad_delay_s"] = float(d)
    if d <= INSTANT_MAX_DELAY_S:
        out["reason"] = "instant"
        return out
    keys = ("curve_n_buyers", "curve_top3_buy_sol", "curve_buy_sol", "completer_sol", "z_buy_tok", "sn60_buy_sol")
    v = {k: snap.get(k) for k in keys}
    if any(x is None for x in v.values()):
        out["reason"] = "component_null"
        return out
    cb = float(v["curve_buy_sol"])
    if not cb > 0:
        out["reason"] = "no_curve_buys"
        return out
    top3 = float(v["curve_top3_buy_sol"]) / cb
    comps = (float(v["curve_n_buyers"]), top3, float(v["completer_sol"]) / COMPLETER_WINDOW_SOL,
             float(v["z_buy_tok"]) / CURVE_SUPPLY_TOK, float(v["sn60_buy_sol"]) / cb)
    if not all(math.isfinite(x) for x in comps):
        out["reason"] = "component_null"
        return out
    out.update(eligible=True, comps=comps, top3_share=top3, n_buyers=float(v["curve_n_buyers"]),
               pe11=bool(PE11_MIN_DELAY_S < d <= PE11_MAX_DELAY_S and comps[0] >= PE11_MIN_BUYERS
                         and top3 < PE11_MAX_TOP3))
    return out


def composite_scores(S: np.ndarray) -> np.ndarray:
    """Equal-weight mean of the five oriented mid-rank percentiles of every row of ``S`` among the OTHER rows:
    p = (#worse + 1/2 #tied) / (n - 1). Higher = more organic."""
    S = np.asarray(S, float)
    n = len(S)
    if n < 2:
        return np.full(n, 0.5)
    P = np.empty_like(S)
    for k, high in enumerate(ORGANIC_HIGH):
        o = S[:, k] if high else -S[:, k]
        r = pd.Series(o).rank(method="average").to_numpy(float)     # 1..n, ties averaged
        P[:, k] = (r - 1.0) / (n - 1.0)
    return P.mean(axis=1)


def mid_rank(x: float, ref: np.ndarray) -> float:
    ref = np.asarray(ref, float)
    return float(((ref < x).sum() + 0.5 * (ref == x).sum()) / len(ref))


def tercile(rank: float | None) -> str:
    if rank is None:
        return "cold"
    if rank >= TOP_TERCILE:
        return "top"
    if rank < BOTTOM_TERCILE:
        return "bottom"
    return "mid"


def _split_hi(split: str, census: C.Census) -> float:
    """Creation-time end of a split: the reference pool never holds a coin created later (G1's registry rule)."""
    if split in C.SPLIT_BOUNDS:
        return float(C.SPLIT_BOUNDS[split][1])
    if split == "final_train":
        return float(census.train_hi) + 1.0
    if split == "final_val":
        return float(census.val_hi) + 1.0
    return math.inf


@dataclass
class RefPool:
    """Eligible graduates' components, each read through AsOf at its own g; queried causally at tau."""

    g: np.ndarray
    mints: np.ndarray
    comps: np.ndarray
    scanned_hours: np.ndarray | None          # None = assume every hour scanned (synthetic frames only)
    n_read: int = 0
    coverage_source: str = "none"
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_coins(cls, coins: Iterable[C.CoinData], scanned_hours: Iterable[int] | None,
                   coverage_source: str = "given") -> "RefPool":
        rows = []
        n = 0
        for cd in coins:
            n += 1
            f = coin_features(C.AsOf(cd, cd.g + C.DECISION_LAG_S))       # tau = g: legal from graduation
            if f["eligible"]:
                rows.append((float(cd.g), str(cd.mint), f["comps"]))
        rows.sort(key=lambda r: (r[0], r[1]))
        hrs = None if scanned_hours is None else np.array(sorted({int(h) for h in scanned_hours}), np.int64)
        return cls(g=np.array([r[0] for r in rows], float), mints=np.array([r[1] for r in rows], object),
                   comps=np.array([r[2] for r in rows], float).reshape(len(rows), len(COMPONENTS)),
                   scanned_hours=hrs, n_read=n, coverage_source=coverage_source)

    @classmethod
    def from_frames(cls, graduates: pd.DataFrame, split: str, census: C.Census,
                    scanned_hours: Iterable[int] | None = None, g_min: float | None = None,
                    g_max: float | None = None, coverage_source: str = "given") -> "RefPool":
        """Pool = every graduate created before the end of ``split`` (any quote / Mayhem flag: the eligibility
        read at g drops them), restricted to g in [g_min, g_max] (bookkeeping only: wider ones are never queried)."""
        g = C._normalize_graduates(graduates, census)
        keep = g["created_for_split"] < _split_hi(split, census)
        if g_min is not None:
            keep &= g["g_ts"] >= g_min
        if g_max is not None:
            keep &= g["g_ts"] <= g_max
        pooled = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
        empty = pd.DataFrame(columns=["minute_ts", "open", "high", "low", "close", "x_close", "y_close"])
        coins = (C._make_coin(r, empty, None, pooled) for r in g[keep].to_dict("records"))
        return cls.from_coins(coins, scanned_hours, coverage_source)

    def __len__(self) -> int:
        return len(self.g)

    def coverage(self, tau: float) -> float:
        """Share of the clock hours overlapping (tau - 24 h, tau] that are fully scanned for graduates."""
        if self.scanned_hours is None:
            return 1.0
        lo = int(math.floor((tau - REF_LOOKBACK_S) / 3600.0)) * 3600
        hi = int(math.floor(tau / 3600.0)) * 3600
        want = np.arange(lo, hi + 3600, 3600, dtype=np.int64)
        return float(np.isin(want, self.scanned_hours).mean())

    def window(self, tau: float, mint: str) -> np.ndarray:
        """Indices of pool coins with g in (tau - 24 h, tau], the coin itself excluded."""
        lo = int(np.searchsorted(self.g, tau - REF_LOOKBACK_S, side="right"))
        hi = int(np.searchsorted(self.g, tau, side="right"))
        idx = np.arange(lo, hi)
        return idx[self.mints[idx] != mint] if len(idx) else idx

    def rank(self, comps: Sequence[float], tau: float, mint: str) -> dict:
        """Organic rank of a coin with components ``comps`` at ``tau`` (PREREG 4). None when cold."""
        idx = self.window(tau, mint)
        cov = self.coverage(tau)
        out = {"n_ref": int(len(idx)), "coverage": cov, "warm": bool(len(idx) >= REF_MIN_COINS and cov >= REF_WARM_MIN),
               "rank": None, "composite": None}
        if not out["warm"]:
            return out
        S = np.vstack([self.comps[idx], np.asarray(comps, float)[None, :]])
        q = composite_scores(S)
        out["composite"] = float(q[-1])
        out["rank"] = mid_rank(q[-1], q[:-1])
        return out


def assess(snap: C.AsOf, ref: RefPool) -> dict:
    """Everything the entry needs at ``snap`` (cached per (mint, tau) on the pool)."""
    key = (snap.mint, round(snap.tau, 3))
    hit = ref._cache.get(key)
    if hit is not None:
        return hit
    f = coin_features(snap)
    info = dict(f, n_ref=None, coverage=None, warm=False, rank=None, composite=None)
    if f["eligible"]:
        info.update(ref.rank(f["comps"], snap.tau, snap.mint))
    info["tercile"] = tercile(info["rank"])
    info["top_quintile"] = info["rank"] is not None and info["rank"] >= TOP_QUINTILE
    info["tag"] = f"{info['tercile']}|{'pe11' if info['pe11'] else 'rest'}"
    ref._cache[key] = info
    return info


def selected(info: Mapping[str, Any], selector: str) -> bool:
    if not info.get("eligible"):
        return False
    if selector == "T3":
        return bool(info["warm"] and info["rank"] is not None and info["rank"] >= TOP_TERCILE)
    if selector == "T5":
        return bool(info["warm"] and info["rank"] is not None and info["rank"] >= TOP_QUINTILE)
    if selector == "PE11":
        return bool(info["pe11"])
    if selector == DOSE_SELECTOR:
        return True
    raise ValueError(f"unknown selector {selector!r}")


def exit_spec(exit_set: str) -> C.ExitSpec:
    if exit_set == "X60":
        return C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=HOLD_X60_S, exit_by_age_s=EXIT_BY_AGE_S)
    if exit_set == "H178":
        return C.ExitSpec(stop_pct=STOP_PCT, exit_by_age_s=EXIT_BY_AGE_S)
    raise ValueError(f"unknown exit set {exit_set!r}")


def decision_time(cd: C.CoinData) -> float:
    """The first decision-grid time (minute boundary + 20 s) at age >= 30 min: Y2's only decision."""
    j = math.ceil((cd.g + ENTRY_AGE_S - C.GRID_OFFSET_S - cd.m0) / 60.0)
    return float(cd.m0 + 60 * j + C.GRID_OFFSET_S)


def make_strategy(ref: RefPool):
    """The Y2 strategy for common.backtest: one decision per coin at g + 30 min; exits are mechanical."""

    def y2_strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
        if pos is not None:
            return None
        if snap.age_s < ENTRY_AGE_S:
            return None
        if snap.age_s >= ENTRY_AGE_S + 60.0:
            return C.SKIP                         # the decision time has passed: never enter late
        info = assess(snap, ref)
        if not selected(info, p["selector"]):
            return C.SKIP
        if not snap.alive():
            return C.SKIP
        return C.Enter(exits=exit_spec(p["exit"]), tag=info["tag"],
                       state={"rank": info["rank"], "pe11": info["pe11"]})

    return y2_strategy


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched control universe: eligible (non-instant, curve features complete) and alive."""
    return bool(coin_features(snap)["eligible"]) and snap.alive()


def alive_ok(snap: C.AsOf) -> bool:
    return snap.alive()


PLACEBO_CONTROLS = {"unmatched": {"eligible": alive_ok, "strata": None}}


def scanned_curve_hours(flow: Path | None = None, graduates: pd.DataFrame | None = None) -> tuple[set, str]:
    """Clock hours fully scanned for graduates: the raw curve chunks, else (no raw chunks) the hours holding one."""
    f = Path(flow or C.flow_dir())
    if (f / "raw" / "curve").exists():
        return set(C.completeness_from_flow(f, with_bar_hours=False).curve_hours), "raw_curve_chunks"
    if graduates is None:
        graduates = C._read_parquet(f / "graduates.parquet")
    hours = set((graduates["g_ts"].to_numpy(np.int64) // 3600 * 3600).tolist()) if len(graduates) else set()
    return hours, "hours_holding_a_graduate"


def lookback_hours(split: str) -> np.ndarray:
    """The clock hours of [split start - 24 h, split start): the reference window of the split's first decisions
    (PREREG 4 cold rule). Empty for splits without fixed bounds (the census thirds)."""
    if split not in C.SPLIT_BOUNDS:
        return np.zeros(0, np.int64)
    lo = float(C.SPLIT_BOUNDS[split][0])
    a = int(math.floor((lo - REF_LOOKBACK_S) / 3600.0)) * 3600
    b = int(math.ceil(lo / 3600.0)) * 3600
    return np.arange(a, b, 3600, dtype=np.int64)


def ref_lookback_problems(split: str, scanned_hours: Iterable[int] | None) -> list[str]:
    """PREREG 8 (review Y2-1): every curve hour in the 24 h before the split start must be scanned. Otherwise T3 / T5
    are cold (never enter) on the split's first day while PE11 and ALL, which never read the pool, still trade: the
    selectors' time mix would differ. ``scanned_hours`` None = every hour scanned (synthetic pools only)."""
    want = lookback_hours(split)
    if scanned_hours is None or not len(want):
        return []
    have = np.isin(want, np.fromiter((int(h) for h in scanned_hours), np.int64))
    if have.all():
        return []
    return [f"reference-pool lookback: curve {int(have.sum())}/{len(want)} h scanned in "
            f"[{C.utc_str(want[0])}, {C.utc_str(want[-1] + 3600)}) UTC (T3 / T5 would be cold on the split's first "
            f"day); backfill those hours first"]


def ref_pool_for(ds: C.Dataset, *, flow: Path | None = None, census: C.Census | None = None,
                 graduates: pd.DataFrame | None = None) -> RefPool:
    """The reference pool of a real split: graduates.parquet, scanned curve hours from the raw chunks."""
    f = Path(flow or C.flow_dir())
    census = census if census is not None else C.Census.load()
    if graduates is None:
        graduates = C._read_parquet(f / "graduates.parquet")
    hours, src = scanned_curve_hours(f, graduates)
    g_min = float(ds.coins["g_ts"].min()) - REF_LOOKBACK_S - 3600.0 if len(ds) else None
    g_max = float(ds.coins["g_ts"].max()) + ENTRY_AGE_S + 3600.0 if len(ds) else None
    return RefPool.from_frames(graduates, ds.split, census, scanned_hours=hours, g_min=g_min, g_max=g_max,
                               coverage_source=src)


# =========================================================================== counts (no outcomes)


def event_counts(ds: C.Dataset, ref: RefPool) -> dict:
    """Counts only (no prices, no returns): eligibility, warmth, terciles, selectors and aliveness at the decision."""
    reasons: dict[str, int] = {}
    n_el = n_warm = n_alive = 0
    terc: dict[str, int] = {}
    sel_alive = {s: 0 for s in SELECTORS + (DOSE_SELECTOR,)}
    sel_any = {s: 0 for s in SELECTORS}
    n_ref = []
    for m in ds.mints:
        cd = ds.coin(m)
        snap = ds.asof(m, decision_time(cd))
        info = assess(snap, ref)
        if not info["eligible"]:
            reasons[str(info["reason"])] = reasons.get(str(info["reason"]), 0) + 1
            continue
        n_el += 1
        n_ref.append(info["n_ref"])
        n_warm += int(info["warm"])
        terc[info["tercile"]] = terc.get(info["tercile"], 0) + 1
        alive = snap.alive()
        n_alive += int(alive)
        for s in SELECTORS:
            if selected(info, s):
                sel_any[s] += 1
                sel_alive[s] += int(alive)
        sel_alive[DOSE_SELECTOR] += int(alive)
    return {"usable": len(ds), "ineligible": reasons, "eligible": n_el, "eligible_warm": n_warm,
            "eligible_alive": n_alive, "terciles": terc, "selector_coins": sel_any, "selector_alive": sel_alive,
            "n_ref_median": float(np.median(n_ref)) if n_ref else None,
            "n_ref_min": int(min(n_ref)) if n_ref else None, "ref_pool_size": len(ref),
            "ref_graduates_read": ref.n_read, "ref_coverage_source": ref.coverage_source}


# =========================================================================== evaluation


def _parts(t: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    sp = t["tag"].astype(str).str.split("|")
    return sp.str[0], sp.str[1] == "pe11"


def _diff_ci(a: np.ndarray, b: np.ndarray, B: int, seed: int = 0) -> tuple[float, float] | None:
    """95 % bootstrap CI of mean(a) - mean(b), resampling each group's coins (one trade per coin)."""
    if len(a) < 2 or len(b) < 2:
        return None
    rng = np.random.default_rng(seed)
    d = rng.choice(a, (B, len(a))).mean(1) - rng.choice(b, (B, len(b))).mean(1)
    return float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))


def dose(t: pd.DataFrame, *, B: int, hide: bool) -> dict:
    """Dose-response of the ALL run: trades by tercile and PE11 flag; on non-debug splits their means, top - bottom
    and PE11 - rest with bootstrap CIs, and the mechanism-consistency flags of PREREG 9."""
    if not len(t):
        return {"n": 0, "by_tercile_n": {}, "pe11_n": 0, "rest_n": 0, "consistency": {"T": None, "PE11": None}}
    terc, pe = _parts(t)
    out: dict[str, Any] = {"n": int(len(t)), "by_tercile_n": terc.value_counts().to_dict(),
                           "pe11_n": int(pe.sum()), "rest_n": int((~pe).sum())}
    if hide:
        out["returns"] = "hidden on the debug split"
        return out
    r = t["ret_net"].to_numpy(float)
    out["by_tercile_mean"] = {k: float(r[(terc == k).to_numpy()].mean()) for k in terc.unique()}
    top, bot = r[(terc == "top").to_numpy()], r[(terc == "bottom").to_numpy()]
    tmb = float(top.mean() - bot.mean()) if len(top) and len(bot) else None
    pr, rest = r[pe.to_numpy()], r[(~pe).to_numpy()]
    pmr = float(pr.mean() - rest.mean()) if len(pr) and len(rest) else None
    out.update(top_minus_bottom=tmb, top_minus_bottom_ci95=_diff_ci(top, bot, B),
               pe11_minus_rest=pmr, pe11_minus_rest_ci95=_diff_ci(pr, rest, B),
               consistency={"T": None if tmb is None else bool(tmb > 0),
                            "PE11": None if pmr is None else bool(pmr > 0)})
    return out


def mechanism_ok(selector: str, dose_doc: Mapping[str, Any] | None) -> bool | None:
    """PREREG 9: T3 / T5 need top tercile > bottom tercile in ALL; PE11 needs the PE11 cell > the rest."""
    c = (dose_doc or {}).get("consistency") or {}
    return c.get("PE11") if selector == "PE11" else c.get("T")


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (never returns, exit reasons or stress)."""
    t = res.trades
    terc = _parts(t)[0] if len(t) else pd.Series(dtype=object)
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)),
            "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_tercile_n": terc.value_counts().to_dict() if len(t) else {}, "n_placebo": int(len(res.placebo)),
            "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
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
    return base


# =========================================================================== pre-registered decisions


def decide_train(evals: Mapping[str, Mapping[str, Any]], dose_doc: Mapping[str, Any] | None) -> dict:
    """PREREG 9 TRAIN rule: qualify (n >= 30, mean > 0, mean w/o top 2 > 0, matched-control diff > 0, mechanism
    consistent in ALL); shortlist <= 2 by the coin-bootstrap 90 % CI lower bound (ties: mean, grid order)."""
    rows = []
    for order, p in enumerate(GRID):
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        mech = mechanism_ok(p["selector"], dose_doc)
        powered = e["n"] >= TRAIN_MIN_TRADES
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and mech is True)
        ci = e.get("ci90")
        rows.append({"config": config_key(p), "order": order, "powered": powered, "qualifies": bool(good),
                     "n": e["n"], "mean": e.get("mean"), "mean_without_top2": e.get("mean_without_top2"),
                     "ci90_lo": ci[0] if ci else None, "placebo_diff": pc, "mechanism_consistent": mech})
    q = sorted((r for r in rows if r["qualifies"]), key=lambda r: (-r["ci90_lo"], -r["mean"], r["order"]))
    if q:
        sl = [GRID[r["order"]] for r in q[:SHORTLIST_MAX]]
        return {"verdict": "SHORTLISTED", "rows": rows, "shortlist": sl,
                "shortlist_keys": [config_key(p) for p in sl], "shortlist_hashes": [C.params_hash(p) for p in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / matched-control / mechanism bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = f"no config reached {TRAIN_MIN_TRADES} trades (best: {max(r['n'] for r in rows)})"
    return {"verdict": v, "reason": why, "rows": rows, "shortlist": [], "shortlist_keys": [], "shortlist_hashes": []}


def decide_val(evals: Mapping[str, Mapping[str, Any]], shortlist: Sequence[Mapping[str, Any]]) -> dict:
    """PREREG 9 VAL rule: a shortlisted config passes with n >= 5, mean > 0, mean w/o top 2 > 0; the candidate is
    the passing one with the higher VAL 90 % CI lower bound (ties: TRAIN order)."""
    rows = []
    for order, p in enumerate(shortlist):
        e = evals[config_key(p)]
        n, mean, mw2 = e["n"], e.get("mean"), e.get("mean_without_top2")
        ci = e.get("ci90")
        ok = n >= VAL_MIN_SIGN and mean is not None and mean > 0 and mw2 is not None and mw2 > 0
        rows.append({"config": config_key(p), "order": order, "n": n, "mean": mean, "mean_without_top2": mw2,
                     "ci90_lo": ci[0] if ci else None, "passes": bool(ok)})
    passing = sorted((r for r in rows if r["passes"]),
                     key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), r["order"]))
    if all(r["n"] < VAL_MIN_SIGN for r in rows):
        return {"verdict": "UNDERPOWERED_VAL", "rows": rows, "candidate": None, "proceed": False}
    if not passing:
        return {"verdict": "FAIL_VAL", "rows": rows, "candidate": None, "proceed": False}
    best = passing[0]
    v = "SELECTED" if best["n"] >= VAL_MIN_TRADES else "SELECTED_UNDERPOWERED"
    cand = dict(shortlist[best["order"]])
    return {"verdict": v, "rows": rows, "candidate": cand, "candidate_key": config_key(cand),
            "candidate_hash": C.params_hash(cand), "proceed": True}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 9: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Y2 failed TEST, CONFIRM not spent"


def y2_extras(candidate: Mapping[str, Any], dose_doc: Mapping[str, Any] | None) -> list[dict]:
    mech = mechanism_ok(candidate["selector"], dose_doc)
    val = (dose_doc or {}).get("pe11_minus_rest" if candidate["selector"] == "PE11" else "top_minus_bottom")
    return [{"id": "Y2.1", "name": "mechanism consistent in ALL on this split "
                                   "(T3/T5: top tercile > bottom tercile; PE11: cell > rest)",
             "pass": mech, "value": val}]


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 and 10 (common.verdict_entry) + Y2.1. Item 9 (FINAL mean > 0) is judged in the overall
    verdict once FINAL ran, so a missing FINAL never makes TEST / CONFIRM 'INCOMPLETE'."""
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


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds Y2 never looked at (the TRAIN third was the debug split)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "debug_third": {"n": int(len(dbg)), "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
                            "note": "census TRAIN third: Y2's debug split (PREREG 12), not judged"}}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2) and <= 5 % of tradeable coins missing B2 data."""
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


def _shortlist(shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{HYP}.json")


def stage_configs(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[tuple[str, dict]]:
    """[(role, params)] the stage runs. TRAIN / debug: the 6 configs + ALL ('dose'); VAL: the shortlist;
    TEST / CONFIRM / FINAL: the VAL candidate + ALL."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID] + [("dose", DOSE_PARAMS)]
    sl = _shortlist(shortlist_path)
    if not sl:
        return []
    if stage == "val":
        return [(config_key(c), c) for c in sl["configs"]]
    val = _read_json(Path(out_dir) / "val.json") or {}
    cand = (val.get("decision") or {}).get("candidate")
    if not cand:
        return []
    return [("candidate", cand), ("dose", DOSE_PARAMS)]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Y2Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Y2Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Y2Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Y2Refused("PREREG.md changed after the first official TRAIN run; record changes in Y2/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Y2Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Y2Refused("TRAIN already ran on complete data (Y2/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Y2Refused("no TRAIN result (Y2/train.json): run --stage train first")
    if train.get("provisional"):
        raise Y2Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Y2Refused(f"TRAIN decision {tv}: Y2 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Y2Refused("no VAL shortlist for Y2 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise Y2Refused("the Y2 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Y2Refused("VAL already ran (Y2/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise Y2Refused("no VAL result (Y2/val.json): TEST needs a VAL decision first")
        vd = val.get("decision") or {}
        if vd.get("verdict") not in PROCEED_VAL:
            raise Y2Refused(f"VAL decision {vd.get('verdict')}: Y2 stopped (PLAN 8 rule 7 input); TEST is not spent")
        if vd.get("candidate_hash") not in sl.get("hashes", []):
            raise Y2Refused("the VAL candidate is not in the frozen shortlist")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Y2Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok, why = confirm_allowed(test)
        if not ok:
            raise Y2Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Y2Refused(f"{stage.upper()} already ran (Y2/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP
           and C.split_group(r.get("split", "")) == C.split_group(split) and not r.get("debug")
           for r in _runs(ledger_path)):
        raise Y2Refused(f"{HYP} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Y2Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"]), hypothesis=r.meta["hypothesis"])
              for role, r in results.items()]
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, config: str) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if not p.exists():
        return None
    t = pd.read_csv(p)
    return t[t["config"] == config].reset_index(drop=True)


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, ref: RefPool | None = None, census: C.Census | None = None,
              flow: Path | None = None, ledger_path: Path | None = None, shortlist_path: Path | None = None,
              B: int = 10_000, n_placebo: int = 20, env: Mapping[str, str] | None = None,
              _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Y2/<stage>.json + .md (``ds`` / ``ref`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "y2_debug_trials.json"   # debug runs never reach the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    lookback = None
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        # the reference pool's 24 h before the split start (review Y2-1); an injected pool (tests) brings its hours
        hrs = ref.scanned_hours if ref is not None else scanned_curve_hours(flow)[0]
        lookback = {"hours": len(lookback_hours(split)), "problems": ref_lookback_problems(split, hrs)}
        if lookback["problems"]:
            ok, notes = False, list(notes) + lookback["problems"]
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Y2Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise Y2Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Y2Refused("no configs to run (shortlist or VAL candidate missing)")

    def _execute(ds: C.Dataset | None, ref: RefPool | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Y2Refused(str(e)) from e
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
        if ds is None:
            ds = C.load(split, flow=flow, census=census, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        if ref is None:
            ref = ref_pool_for(ds, flow=flow, census=census)
        strategy = make_strategy(ref)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "ref_lookback": lookback, "n_coins": len(ds),
                               "span_days": _span_days(ds), "event_counts": event_counts(ds, ref)}
        results: dict[str, C.Result] = {}
        for role, p in configs:
            is_dose = p["selector"] == DOSE_SELECTOR
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=not is_dose,
                                       n_placebo=n_placebo, placebo_eligible=placebo_ok,
                                       placebo_controls=None if is_dose else PLACEBO_CONTROLS,
                                       stress={} if is_dose else STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        dose_doc = dose(results["dose"].trades, B=min(B, 5000), hide=debug) if "dose" in results else None
        doc["dose"] = dose_doc
        doc["n_trials_total"] = n_tr
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals, dose_doc)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 9 rule, {dec['shortlist_keys']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            sl = _shortlist(shortlist_path) or {}
            doc["decision"] = decide_val(evals, sl.get("configs") or [])
        elif stage in ("test", "confirm"):
            cand = dict(configs[0][1])
            val_t = _read_trades(out_dir, "val", config_key(cand))
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = y2_extras(cand, dose_doc)
            doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "y2_extras": extras,
                              "candidate": config_key(cand)}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"y2 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:
            return _execute(ds, ref)
    except C.SplitLocked as e:
        raise Y2Refused(str(e)) from e


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
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)"
    if tv == "NO_CONFIG":
        return "NO EDGE (nothing qualified on TRAIN)"
    va = doc("val")
    if not va:
        return "PENDING VAL"
    vv = (va.get("decision") or {}).get("verdict")
    if vv == "FAIL_VAL":
        return "NO EDGE (failed VAL; PLAN 8 rule 7 input)"
    if vv == "UNDERPOWERED_VAL":
        return "UNDERPOWERED (VAL)"
    te = doc("test")
    if not te:
        return "PENDING TEST"
    ok, why = confirm_allowed(te)
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
    ec = doc.get("event_counts") or {}
    L = [f"# Y2 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Y2 status:** {doc.get('overall')}.", ""]
    lb = doc.get("ref_lookback")
    if lb:
        txt = "; ".join(lb["problems"]) if lb["problems"] else f"all {lb['hours']} curve hours scanned"
        L.insert(-2, f"- **Reference-pool lookback** (24 h before the split start, PREREG 8): {txt}.")
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter "
              "was chosen here.**", ""]
    if ec:
        L += ["## Universe at the decision (g + 30 min; counts only)", "",
              f"- Usable {ec['usable']}; eligible {ec['eligible']} (ineligible by reason: {ec['ineligible']}).",
              f"- Eligible with a warm rank: {ec['eligible_warm']}; terciles {ec['terciles']}; reference pool "
              f"median {ec['n_ref_median']} coins (min {ec['n_ref_min']}); pool {ec['ref_pool_size']} eligible of "
              f"{ec['ref_graduates_read']} graduates read; hour coverage from {ec['ref_coverage_source']}.",
              f"- Eligible and alive: {ec['eligible_alive']}. Selector coins {ec['selector_coins']}; selected and "
              f"alive {ec['selector_alive']}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| role | config | trades | coins | terciles | placebo trades | horizon exits | entries/day |",
                  "|---|---|---:|---:|---|---:|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {e['by_tercile_n']} | "
                         f"{e['n_placebo']} | {e['horizon_exits']} | {'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | mean | median | 90% CI coin | 90% CI 6-h block | w/o top 2 | "
                  "placebo diff (eligible) | placebo diff (unmatched) | costs ×1.5 | same-bar exits |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                pc = (e.get("placebo") or {}).get("mean_diff")
                pu = (e.get("placebo_unmatched") or {}).get("mean_diff")
                s = e.get("stress") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {_pct(e.get('mean'))} | {_pct(e.get('median'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct(pc)} | {_pct(pu)} | {_pct(s.get('costs_x1.5'))} | {_pct(s.get('same_bar_exits'))} |")
        L.append("")
    dd = doc.get("dose")
    if dd:
        L += ["## Dose-response (ALL, H178)", "", f"- Trades by tercile: {dd.get('by_tercile_n')}; PE11 "
              f"{dd.get('pe11_n')}, rest {dd.get('rest_n')}."]
        if "by_tercile_mean" in dd:
            L.append(f"- Mean by tercile: { {k: _pct(v) for k, v in dd['by_tercile_mean'].items()} }; top − bottom "
                     f"{_pct(dd.get('top_minus_bottom'))} {_ci(dd.get('top_minus_bottom_ci95'))}; PE11 − rest "
                     f"{_pct(dd.get('pe11_minus_rest'))} {_ci(dd.get('pe11_minus_rest_ci95'))}; consistency "
                     f"{dd.get('consistency')}.")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, mean {_pct(r.get('mean'))}, w/o top 2 "
                 f"{_pct(r.get('mean_without_top2'))}, 90% CI low {_pct(r.get('ci90_lo'))}"
                 + (f", placebo diff {_pct(r.get('placebo_diff'))}, mechanism {r.get('mechanism_consistent')}, "
                    f"qualifies {r.get('qualifies')}" if "qualifies" in r else f", passes {r.get('passes')}") + ".")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} {dec.get('shortlist_keys') or ''}.")
    if dec.get("candidate_key"):
        L.append(f"- TEST candidate: {dec['candidate_key']}.")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("y2_extras", []):
            L.append(f"- {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    if dec.get("reason"):
        L.append(f"- Reason: {dec['reason']}.")
    if dec.get("note"):
        L.append(f"- {dec['note']}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Y2 curve-phase organic share: pre-registered stages; "
                                             "see research/lab2/Y2/PREREG.md")
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
    except Y2Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

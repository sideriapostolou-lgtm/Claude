"""X1 (wave-2 sweep, designer x1): follow early holders whose earlier picks paid a follower ("smart-money follow").

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/X1/PREREG.md``.
The ledger name ``X1`` is the sweep's designer id, not PLAN 4.1's fill engine.

Mechanism
---------
Some wallets that buy a fresh PumpSwap pool in its first 5 minutes, and still hold at g + 5 min, may pick coins that
keep rising. X1 keeps an as-of REGISTRY of those wallets: for every eligible earlier coin it simulates the trade a
follower would have taken (the "base follow trade": entry at the first grid time after the BOOST window, -30 % stop,
sold at g + 60 min, worst fills, next-bar exits) and, once that trade has RESOLVED, credits its log return to the
coin's early holders. A wallet's skill is its shrunk mean (PLAN 6.6 rule 3). X1 buys a coin at its first post-BOOST
decision when one of its early holders is reputable (n >= N_MIN resolved picks, skill > theta), with the same exits.

No lookahead
------------
* Every FEATURE is read through :class:`common.AsOf` (tau = t - 20 s): the early-holder list (``w300_top10``, legal
  from g + 300 s) and the AGENT exclusion (legal once AGENT presence is decided, tau >= g + 420 s) at the coin's own
  decision time; class and ``alive`` at the same time.
* A registry entry (wallet, coin, label) is usable at tau only when the coin's base follow trade had RESOLVED (the
  end of the bar its exit filled in) at or before tau, and never for the coin being decided (PLAN 6.6 rules 1-2).
  Labels are outcomes: they are read only through that resolution rule.
* The registry runs forward through the splits (:data:`HISTORY_SPLITS`): a stage reads only splits that are earlier
  in time and already had their look.

CLI::

    python research/lab2/x1.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/x1.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/x1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/x1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/x1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/x1.py --stage final
    python research/lab2/x1.py --stage val --check             # prerequisites only

Each stage writes ``X1/<stage>.json`` and ``X1/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
VAL without the shortlist, nothing after a persistence-gate KILL, TEST / CONFIRM / FINAL once each, never CONFIRM or
FINAL before TEST, PLAN 8 data gates, PREREG frozen after the first official TRAIN run).
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
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

VERSION = "x1-v1"
OUT_DIR = HERE / "X1"
HYP, HYP_GATE = "X1", "X1-persist"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
# PREREG 9: the registry pool of each stage = eligible coins of these splits (earlier in time, already looked at)
HISTORY_SPLITS = {"debug": ("final_train",), "train": ("train",), "val": ("train", "val"),
                  "test": ("train", "val", "test"), "confirm": ("confirm",), "final": ("train", "val", "test", "final")}

# =========================================================================== pre-registered constants (PREREG 3-8)
DECISION_AFTER_S = float(C.AGENT_WINDOW_S)   # first decision with tau >= g + 420 s: BOOST over, AGENT decided
EARLY_WINDOW = "w300"                        # B2 top-10 pool buyers of [g, g + 300 s)
HOLD_FRAC = 0.5                              # an early holder sold <= 50 % of its window buy SOL in the window
# classes (PLAN 4.2 rules; FACTORY and OPERATOR are excluded: factory dumps, and OPERATOR coins belong to M1)
OPERATOR_MIN_BUY_SOL = 500.0
OPERATOR_MAX_BUYERS = 30
FACTORY_MAX_DELAY_S = 5.0
FACTORY_MIN_TOP5 = 0.85
ALLOWED_CLASSES = ("OTHER",)
# exits (fixed, not searched) and fills
STOP_PCT = 0.30
EXIT_BY_AGE_S = 3600.0
SIZE_USD = 20.0
CFG = C.FillConfig(size_usd=SIZE_USD, exit_delay_bars=1)      # worst fills, stops / time exits fill one bar later
EXITS = C.ExitSpec(stop_pct=STOP_PCT, exit_by_age_s=EXIT_BY_AGE_S)
# registry
LABEL_FLOOR = 0.01           # label = log(max(1 + ret_net, 0.01))
SHRINK_K = 10.0              # skill = mean label * n / (n + 10)
WARMUP_S = 86400.0           # decisions within 24 h of the first history graduation are flagged (PLAN 6.6 rule 8)
# the grid
THETA_GRID = (0.0, 0.10)
NMIN_GRID = (3, 6)
# persistence gate (stop rule, TRAIN, before any P&L)
N_GATE = 3
GATE_MIN_OBS = 200
GATE_MIN_RHO = 0.10
GATE_MAX_P = 0.01
GATE_BLOCK_B = 2000
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_LEADS = 30, 3
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                         # PLAN 3.5 default
PASS_MIN_LEADS = 5
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
CONTROL = "known_not_reputable"

FIXED = {
    "version": VERSION, "decision_after_s": DECISION_AFTER_S, "early_window": EARLY_WINDOW, "hold_frac": HOLD_FRAC,
    "classes": list(ALLOWED_CLASSES), "operator_min_buy_sol": OPERATOR_MIN_BUY_SOL,
    "operator_max_buyers": OPERATOR_MAX_BUYERS, "factory_max_delay_s": FACTORY_MAX_DELAY_S,
    "factory_min_top5": FACTORY_MIN_TOP5, "alive": "common.AsOf.alive() defaults", "stop_pct": STOP_PCT,
    "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD, "label_floor": LABEL_FLOOR, "shrink_k": SHRINK_K,
    "fill": "FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar exits, next-bar exit fills",
    "placebo": "eligible coins, age +-120 s",
}


def make_params(theta: float, n_min: int) -> dict:
    if theta not in THETA_GRID or n_min not in NMIN_GRID:
        raise ValueError(f"(theta={theta}, n_min={n_min}) is not in the pre-registered grid")
    return {**FIXED, "theta": float(theta), "n_min": int(n_min)}


GRID = [make_params(th, n) for th in THETA_GRID for n in NMIN_GRID]
GATE_PARAMS = {"version": VERSION, "test": "persistence_gate", "n_gate": N_GATE, "min_obs": GATE_MIN_OBS,
               "min_rho": GATE_MIN_RHO, "max_p": GATE_MAX_P, "fixed": FIXED}
STRESS = {"costs_x1.5": CFG.stressed(1.5), "rent_0.22": dataclasses.replace(CFG, rent_usd=0.22),
          "same_bar_exits": C.FillConfig(size_usd=SIZE_USD)}
DECL = {"uses_wallet_reputation": True, "reputation_excludes_traded_coin": True, "uses_organic_flow": False,
        "uses_truncated_windows": False, "uses_current_state_fields": False}


class X1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"th{p['theta']:g}|n{p['n_min']}"


# =========================================================================== features (AsOf only)


def decision_index(cd: C.CoinData) -> int:
    """k_d = ceil((g + 420 - m0) / 60): the first grid decision t = m0 + 60 k + 20 with tau = t - 20 >= g + 420 s."""
    k = int(math.ceil((cd.g + DECISION_AFTER_S - cd.m0) / 60.0))
    while cd.m0 + 60 * k < cd.g + DECISION_AFTER_S:
        k += 1
    while k > 0 and cd.m0 + 60 * (k - 1) >= cd.g + DECISION_AFTER_S:
        k -= 1
    return k


def decision_time(cd: C.CoinData) -> float:
    return float(cd.bar_start(decision_index(cd)) + C.GRID_OFFSET_S)


def x1_class(snap: C.AsOf) -> str | None:
    """PLAN 4.2 rules X1 needs, in PLAN order: OPERATOR, FACTORY, else OTHER. None when an input is NULL or not yet
    knowable (a NULL never passes and is never 0). Same rules as M1 PREREG 3, re-implemented here on purpose."""
    buy, nby = snap.get("w120_buy_sol"), snap.get("w120_n_buyers")
    if buy is None or nby is None or not snap.agent_resolved:
        return None
    ag_sol, ag_n = 0.0, 0
    if snap.agent_detected:
        aw = snap.get("agent_wallet")
        ag_sol = sum(float(w[1]) for w in (snap.get("w120_top10") or ()) if w[0] == aw)
        ag_n = 1
    if buy - ag_sol >= OPERATOR_MIN_BUY_SOL and nby - ag_n <= OPERATOR_MAX_BUYERS:
        return "OPERATOR"
    d = snap.get("grad_delay_s")
    if d is None:
        lb = snap.get("grad_delay_lb_s")
        if lb is None:
            return None
        return "OTHER" if lb > FACTORY_MAX_DELAY_S else None
    if d <= FACTORY_MAX_DELAY_S:
        sh = snap.top_share("w120", 5, exclude_agent=True)
        if sh is None:
            return None
        if sh >= FACTORY_MIN_TOP5:
            return "FACTORY"
    return "OTHER"


def eligible(snap: C.AsOf) -> bool:
    """PREREG 3: class OTHER and alive (>= $1.5k volume over 15 min, market cap >= $6k)."""
    return x1_class(snap) in ALLOWED_CLASSES and snap.alive()


def early_holders(snap: C.AsOf) -> tuple[str, ...] | None:
    """Wallets of the coin's w300 top-10 that bought (> 0 SOL) and still hold (window sell SOL <= HOLD_FRAC x buy SOL),
    pooled accounts and the AGENT removed. None while the list or AGENT presence is not yet knowable."""
    try:
        lst = snap.top_buyers(EARLY_WINDOW, exclude_agent=True)
    except C.NotYetKnown:
        return None
    if lst is None:
        return None
    out, seen = [], set()
    for w in lst:   # pooled accounts (incl. pooled_accounts.json) were already dropped when the coin was loaded
        addr, b, s = str(w[0]), float(w[1] or 0.0), float(w[2] or 0.0)
        if not addr or addr in C.POOLED_ACCOUNTS or addr in seen or b <= 0 or s > HOLD_FRAC * b:
            continue
        seen.add(addr)
        out.append(addr)
    return tuple(out)


# =========================================================================== the registry (cross-coin, causal)


def _no_signal_exit(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    return None


def base_follow_trade(cd: C.CoinData, sol: C.SolUsd, cfg: C.FillConfig = CFG) -> dict | None:
    """The trade a follower takes on ``cd``: entry decided at the coin's t_d, exits of PREREG 6, fills ``cfg``.
    Returns the engine's trade record plus ``resolve_ts`` (end of the bar in which the exit filled)."""
    k = decision_index(cd)
    r = C._simulate_coin(cd, sol, cfg, _no_signal_exit, {}, forced=(k, C.Enter(exits=EXITS, tag="base")),
                         forced_is_placebo=False)
    if r is None:
        return None
    j_out = min(cd.bar_of(float(r["t_out"])), C.N_BARS - 1)
    r["resolve_ts"] = float(cd.bar_start(j_out) + 60)
    return r


def label_of(ret_net: float) -> float:
    return float(math.log(max(1.0 + float(ret_net), LABEL_FLOOR)))


@dataclass
class Registry:
    """Eligible history coins with their base-follow-trade labels, and per-wallet entries sorted by resolution time.

    ``coins``: mint, split, g, t_d, eligible, n_holders, label, ret_net, resolve_ts (labels: never print them on the
    debug split). ``wallets``: wallet -> (resolve times sorted, labels, mints)."""

    coins: pd.DataFrame
    wallets: dict
    t0: float

    def record(self, wallet: str, tau: float, exclude_mint: str) -> tuple[int, float | None]:
        """(n, mean label) of the wallet's entries RESOLVED at or before tau, the coin ``exclude_mint`` left out."""
        ev = self.wallets.get(wallet)
        if ev is None:
            return 0, None
        ts, ys, ms = ev
        hi = int(np.searchsorted(ts, tau, side="right"))
        if hi == 0:
            return 0, None
        keep = ms[:hi] != exclude_mint
        n = int(keep.sum())
        if n == 0:
            return 0, None
        return n, float(ys[:hi][keep].mean())

    def skill(self, wallet: str, tau: float, exclude_mint: str) -> tuple[int, float | None]:
        """(n, shrunk skill = mean label x n / (n + SHRINK_K)) as of tau (PLAN 6.6 rules 1-3)."""
        n, m = self.record(wallet, tau, exclude_mint)
        return n, (None if m is None else m * n / (n + SHRINK_K))

    def is_warmup(self, t: float) -> bool:
        return bool(t < self.t0 + WARMUP_S)

    def stats(self) -> dict:
        """Counts only (no labels)."""
        c = self.coins
        n_ent = {w: len(v[0]) for w, v in self.wallets.items()}
        vals = np.array(list(n_ent.values()), int) if n_ent else np.zeros(0, int)
        return {"history_coins": int(len(c)), "eligible_coins": int(c["eligible"].sum()) if len(c) else 0,
                "labelled_coins": int(c["label"].notna().sum()) if len(c) else 0,
                "by_split": {str(k): int(v) for k, v in c["split"].value_counts().items()} if len(c) else {},
                "wallets": int(len(vals)), "entries": int(vals.sum()),
                "wallets_ge3_entries": int((vals >= 3).sum()), "wallets_ge6_entries": int((vals >= 6).sum()),
                "max_entries_one_wallet": int(vals.max()) if len(vals) else 0,
                "history_start_utc": C.utc_str(self.t0) if math.isfinite(self.t0) else None}


def build_registry(datasets: Sequence[C.Dataset], cfg: C.FillConfig = CFG) -> Registry:
    """Registry from the usable coins of ``datasets`` (the stage's history splits). A coin enters only when it was
    ELIGIBLE at its own t_d; its label is its base follow trade; its early holders are read at t_d."""
    rows, ev = [], {}
    seen: set[str] = set()
    t0 = math.inf
    for ds in datasets:
        for m in ds.mints:
            if m in seen:
                continue
            seen.add(m)
            cd = ds.coin(m)
            t0 = min(t0, cd.g)
            t_d = decision_time(cd)
            snap = C.AsOf(cd, t_d, ds.sol)
            ok = eligible(snap)
            hold = early_holders(snap) if ok else None
            row = {"mint": m, "split": cd.split, "g": cd.g, "t_d": t_d, "eligible": bool(ok),
                   "n_holders": None if hold is None else len(hold), "label": None, "ret_net": None,
                   "resolve_ts": None}
            if ok:
                tr = base_follow_trade(cd, ds.sol, cfg)
                if tr is not None:
                    if tr["resolve_ts"] < t_d + 60:
                        raise AssertionError(f"{m}: label resolves before its own decision")
                    y = label_of(tr["ret_net"])
                    row.update(label=y, ret_net=float(tr["ret_net"]), resolve_ts=tr["resolve_ts"])
                    for w in hold or ():
                        ev.setdefault(w, []).append((tr["resolve_ts"], y, m))
            rows.append(row)
    wallets = {}
    for w, lst in ev.items():
        lst.sort(key=lambda e: (e[0], e[2]))
        wallets[w] = (np.array([e[0] for e in lst], float), np.array([e[1] for e in lst], float),
                      np.array([e[2] for e in lst], object))
    cols = ["mint", "split", "g", "t_d", "eligible", "n_holders", "label", "ret_net", "resolve_ts"]
    return Registry(coins=pd.DataFrame(rows, columns=cols), wallets=wallets, t0=t0)


def holder_scores(snap: C.AsOf, reg: Registry) -> list[dict]:
    """[{wallet, n, skill}] for the coin's early holders as of snap.tau (empty when none are knowable)."""
    out = []
    for w in early_holders(snap) or ():
        n, s = reg.skill(w, snap.tau, snap.mint)
        out.append({"wallet": w, "n": n, "skill": s})
    return out


def signal(snap: C.AsOf, reg: Registry, p: Mapping[str, Any]) -> dict:
    """PREREG 5 at the decision: eligible and >= 1 reputable early holder (n >= n_min, skill > theta)."""
    out = {"eligible": eligible(snap), "n_holders": 0, "n_known": 0, "n_reputable": 0, "lead": None,
           "lead_skill": None, "lead_n": None, "enter": False}
    if not out["eligible"]:
        return out
    hs = holder_scores(snap, reg)
    known = [h for h in hs if h["n"] >= int(p["n_min"]) and h["skill"] is not None]
    rep = [h for h in known if h["skill"] > float(p["theta"])]
    out.update(n_holders=len(hs), n_known=len(known), n_reputable=len(rep))
    if rep:
        lead = min(rep, key=lambda h: (-h["skill"], -h["n"], h["wallet"]))
        out.update(lead=lead["wallet"], lead_skill=lead["skill"], lead_n=lead["n"], enter=True)
    return out


def make_strategy(reg: Registry):
    """The X1 strategy for common.backtest (one decision per coin, mechanical exits only)."""
    def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
        if pos is not None:
            return None
        if snap.tau < snap.g + DECISION_AFTER_S:
            return None
        sig = signal(snap, reg, p)
        if not sig["enter"]:
            return C.SKIP
        return C.Enter(exits=EXITS, tag=str(sig["lead"]),
                       state={"lead": sig["lead"], "lead_skill": sig["lead_skill"], "lead_n": sig["lead_n"]})
    return strategy


def placebo_ok(snap: C.AsOf) -> bool:
    """Matched random control universe (PLAN 3.4 'same eligible coins')."""
    return eligible(snap)


def make_control(reg: Registry, p: Mapping[str, Any]):
    """Known-not-reputable control (X1.4): eligible, >= 1 early holder known under n_min, none reputable."""
    def ok(snap: C.AsOf) -> bool:
        if not eligible(snap):
            return False
        hs = holder_scores(snap, reg)
        known = [h for h in hs if h["n"] >= int(p["n_min"]) and h["skill"] is not None]
        return bool(known) and not any(h["skill"] > float(p["theta"]) for h in known)
    return ok


# =========================================================================== persistence gate (stop rule)


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman rank correlation (ties averaged); None when undefined (< 3 pairs or a constant series)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return None
    rx = pd.Series(x).rank(method="average").to_numpy(float)
    ry = pd.Series(y).rank(method="average").to_numpy(float)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def block_boot_rho(x: np.ndarray, y: np.ndarray, blocks: np.ndarray, B: int, seed: int = 0) -> np.ndarray | None:
    """Two-level bootstrap of Spearman rho: resample 6-hour blocks, then coins inside each drawn block."""
    groups = [np.flatnonzero(blocks == b) for b in np.unique(blocks)]
    if len(groups) < 2:
        return None
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(B):
        idx = np.concatenate([groups[i][rng.integers(0, len(groups[i]), len(groups[i]))]
                              for i in rng.integers(0, len(groups), len(groups))])
        r = spearman(x[idx], y[idx])
        if r is not None:
            out.append(r)
    return np.array(out) if len(out) >= 10 else None


def gate_obs(ds: C.Dataset, reg: Registry) -> pd.DataFrame:
    """Eligible coins of ``ds`` at their t_d: the as-of score (best skill of holders known at N_GATE) and the LABEL
    (their base follow trade, an outcome read from the registry table)."""
    lab = reg.coins.set_index("mint") if len(reg.coins) else None
    rows = []
    for m in ds.mints:
        if lab is None or m not in lab.index or not bool(lab.at[m, "eligible"]) or pd.isna(lab.at[m, "label"]):
            continue
        cd = ds.coin(m)
        t_d = decision_time(cd)
        snap = ds.asof(m, t_d)
        hs = holder_scores(snap, reg)
        known = [h for h in hs if h["n"] >= N_GATE and h["skill"] is not None]
        best = min(known, key=lambda h: (-h["skill"], -h["n"], h["wallet"])) if known else None
        n_rep0 = sum(1 for h in known if h["skill"] > 0)
        rows.append({"mint": m, "t_d": t_d, "label": float(lab.at[m, "label"]), "n_holders": len(hs),
                     "n_known": len(known), "rep": None if best is None else best["skill"],
                     "best_wallet": None if best is None else best["wallet"],
                     "group": "unknown" if not known else ("reputable" if n_rep0 else "known_not_reputable"),
                     "warmup": reg.is_warmup(t_d)})
    cols = ["mint", "t_d", "label", "n_holders", "n_known", "rep", "best_wallet", "group", "warmup"]
    return pd.DataFrame(rows, columns=cols)


def gate_decision(obs: pd.DataFrame, B: int = GATE_BLOCK_B, hide: bool = False) -> dict:
    """PREREG 8: PASS / KILL / UNDERPOWERED. ``hide`` (debug split) returns counts only."""
    o = obs[obs["rep"].notna()] if len(obs) else obs
    n = int(len(o))
    out: dict[str, Any] = {"n_eligible": int(len(obs)), "n_obs": n,
                           "groups": obs["group"].value_counts().to_dict() if len(obs) else {},
                           "n_score_wallets": int(o["best_wallet"].nunique()) if n else 0,
                           "n_warmup_obs": int(o["warmup"].sum()) if n else 0,
                           "need": {"obs": GATE_MIN_OBS, "rho": GATE_MIN_RHO, "p_one_sided": GATE_MAX_P,
                                    "block_ci90_low": "> 0"}}
    if hide:
        out["decision"] = "HIDDEN (debug split: no outcome statistics)"
        return out
    x, y = o["rep"].to_numpy(float), o["label"].to_numpy(float)
    rho = spearman(x, y) if n else None
    p = None if rho is None else float(1.0 - NormalDist().cdf(rho * math.sqrt(max(n - 1, 1))))
    boot = block_boot_rho(x, y, (o["t_d"].to_numpy(float) // C.BLOCK_S).astype(np.int64), B) if n >= 3 else None
    ci = None if boot is None else (float(np.quantile(boot, 0.05)), float(np.quantile(boot, 0.95)))
    out.update(rho=rho, p_one_sided=p, ci90_block=ci)
    if n < GATE_MIN_OBS or ci is None:
        out["decision"] = "UNDERPOWERED"
    elif rho is None or rho < GATE_MIN_RHO or p >= GATE_MAX_P or ci[0] <= 0:
        out["decision"] = "KILL"
    else:
        out["decision"] = "PASS"
    diag: dict[str, Any] = {"label_mean_by_group": {g: float(v["label"].mean()) for g, v in obs.groupby("group")}}
    if n >= 3:
        terc = pd.qcut(pd.Series(x).rank(method="first"), 3, labels=["low", "mid", "high"])
        diag["label_mean_by_rep_tercile"] = {str(k): float(v) for k, v in pd.Series(y).groupby(terc.to_numpy(),
                                                                                             observed=True).mean().items()}
        nw = o[~o["warmup"].astype(bool)]
        diag["rho_without_warmup"] = spearman(nw["rep"], nw["label"]) if len(nw) >= 3 else None
    out["diagnostics"] = diag
    return out


# =========================================================================== evaluation


def _lead_stats(t: pd.DataFrame, B: int) -> dict:
    if not len(t):
        return {"n_leads": 0, "ci90_lead": None, "top_lead": None, "mean_without_top_lead": None}
    lead = t["tag"].astype(str).to_numpy(object)
    r = t["ret_net"].to_numpy(float)
    vc = pd.Series(lead).value_counts()
    prof = pd.Series(r).groupby(lead).sum()
    top = min(vc.index, key=lambda w: (-int(vc[w]), -float(prof[w]), str(w)))
    rest = r[lead != top]
    return {"n_leads": int(len(vc)), "ci90_lead": C.coin_bootstrap_ci(r, lead, 0.90, B),
            "top_lead": {"wallet": str(top), "trades": int(vc[top]), "share_of_trades": float(vc[top] / len(r))},
            "mean_without_top_lead": float(rest.mean()) if len(rest) else None}


def evaluate(res: C.Result, reg: Registry, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (never returns, exit reasons or stress)."""
    t = res.trades
    warm = np.array([reg.is_warmup(float(x)) for x in t["t_dec"]], bool) if len(t) else np.zeros(0, bool)
    ctrl = res.controls.get(CONTROL) if res.controls else None
    base = {"config": config_key(res.meta["params"]), "params_hash": C.params_hash(res.meta["params"]),
            "hypothesis": res.meta["hypothesis"], "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "n_leads": int(t["tag"].nunique()) if len(t) else 0, "n_placebo": int(len(res.placebo)),
            "n_control": int(len(ctrl)) if ctrl is not None else 0, "n_warmup": int(warm.sum()),
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
    base["control"] = C.placebo_compare(t, ctrl, B=B) if ctrl is not None and len(ctrl) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["leads"] = _lead_stats(t, B)
    base["warmup"] = {"n_warmup": int(warm.sum()),
                      "mean_without_warmup": float(t.loc[~warm, "ret_net"].mean()) if (~warm).any() else None}
    return base


def x1_extras(ev: Mapping[str, Any]) -> list[dict]:
    """PREREG 9 TEST extras: one wallet's luck must not carry the result."""
    ld = ev.get("leads") or {}
    nl = ev.get("n_leads", 0)
    ci = ld.get("ci90_lead")
    mw = ld.get("mean_without_top_lead")
    cdiff = (ev.get("control") or {}).get("mean_diff")
    return [
        {"id": "X1.1", "name": f"power: >= {PASS_MIN_LEADS} distinct lead wallets", "pass": bool(nl >= PASS_MIN_LEADS),
         "value": nl, "blocking": True},
        {"id": "X1.2", "name": "90% CI lower bound > 0 resampling lead wallets", "pass": None if not ci else bool(ci[0] > 0),
         "value": ci, "blocking": True},
        {"id": "X1.3", "name": "mean > 0 without the most frequent lead wallet",
         "pass": None if mw is None else bool(mw > 0), "value": mw, "blocking": True},
        {"id": "X1.4", "name": "beats the known-not-reputable control (diagnostic)",
         "pass": None if cdiff is None else bool(cdiff > 0), "value": cdiff, "blocking": False},
    ]


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 + 10 (from common.verdict_entry) and the blocking X1 extras. Item 9 (FINAL) is judged in the
    overall verdict."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1) or extras[0]["pass"] is False:
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    blocking = [e for e in extras[1:] if e.get("blocking", True)]
    if any(v is False for v in rest) or any(e["pass"] is False for e in blocking):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(e["pass"] is None for e in blocking):
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 9 TRAIN: qualifying configs; the shortlist is the single best by the coin-bootstrap 90 % CI low."""
    rows = []
    for p in GRID:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        ci = e.get("ci90")
        powered = e["n"] >= TRAIN_MIN_TRADES
        good = (powered and e.get("n_leads", 0) >= TRAIN_MIN_LEADS and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0 and ci is not None)
        rows.append({"theta": p["theta"], "n_min": p["n_min"], "config": config_key(p), "powered": powered,
                     "qualifies": bool(good), "n": e["n"], "n_leads": e.get("n_leads", 0), "mean": e.get("mean"),
                     "ci90_lo": ci[0] if ci else None, "placebo_diff": pc})
    q = [r for r in rows if r["qualifies"]]
    if q:
        best = min(q, key=lambda r: (-r["ci90_lo"], -r["mean"], -r["theta"], -r["n_min"]))
        sl = [make_params(best["theta"], best["n_min"])]
        return {"verdict": "SHORTLISTED", "best": best["config"], "rows": rows, "shortlist": sl,
                "shortlist_hashes": [C.params_hash(x) for x in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the leads / mean / top-2 / matched-control bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = f"no config reached {TRAIN_MIN_TRADES} trades (best: {max(r['n'] for r in rows)})"
    return {"verdict": v, "reason": why, "rows": rows, "shortlist": [], "shortlist_hashes": []}


def decide_val(ev: Mapping[str, Any]) -> dict:
    n = ev["n"]
    mean, mw2 = ev.get("mean"), ev.get("mean_without_top2")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "proceed": v in PROCEED_VAL}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: X1 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds X1 never looked at (the TRAIN third debugged the code)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    design = t[t["split"] == FINAL_DESIGN] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "design_third": {"n": int(len(design)), "mean": float(design["ret_net"].mean()) if len(design) else None,
                             "note": "census TRAIN third: used to debug the code, not judged"}}


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
        return [(config_key(p), HYP, p) for p in GRID]
    sl = _shortlist(HYP, shortlist_path)
    if not sl or not sl.get("configs"):
        return []
    return [("candidate", HYP, sl["configs"][0])]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`X1Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise X1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise X1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise X1Refused("PREREG.md changed after the first official TRAIN run; record changes in X1/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise X1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise X1Refused("TRAIN already ran on complete data (X1/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise X1Refused("no TRAIN result (X1/train.json): run --stage train first")
    if train.get("provisional"):
        raise X1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv == "KILLED_GATE":
        raise X1Refused("X1 is dead: the persistence gate failed on TRAIN (wallet skill does not persist)")
    if tv != "SHORTLISTED":
        raise X1Refused(f"TRAIN decision {tv}: X1 stopped before VAL")
    sl = _shortlist(HYP, shortlist_path)
    if not sl:
        raise X1Refused("no VAL shortlist for X1 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise X1Refused("the X1 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise X1Refused("VAL already ran (X1/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise X1Refused("no VAL result (X1/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise X1Refused(f"VAL decision {vv}: X1 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise X1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok2, why = confirm_allowed(test)
        if not ok2:
            raise X1Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise X1Refused(f"{stage.upper()} already ran (X1/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) == C.split_group(split)
           and not r.get("debug") for r in _runs(ledger_path)):
        raise X1Refused(f"X1 already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise X1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def history_datasets(stage: str, ds: C.Dataset, flow: Path | None, census: C.Census | None) -> list[C.Dataset]:
    """PREREG 9 history splits: the traded dataset itself plus earlier splits read without a guard (never traded)."""
    out = []
    for s in HISTORY_SPLITS[stage]:
        out.append(ds if s == ds.split else C.coverage_dataset(s, flow, census))
    return out


def _check_history(stage: str, ds: C.Dataset, hist: Sequence[C.Dataset]) -> None:
    for h in hist:
        if h is ds:
            continue
        covs = [h.coverage]
        for cv in covs:
            ok, notes = coverage_check(cv)
            if not ok:
                raise X1Refused(f"history split {h.split} incomplete: " + "; ".join(notes[:6]))
        try:
            C.check_sol_coverage(h)
        except C.DataNotReady as e:
            raise X1Refused(f"history split {h.split}: {e}") from e


def event_counts(ds: C.Dataset, reg: Registry) -> dict:
    """Counts only (no prices, no returns): classes, eligibility, holders and known holders at the decision."""
    n_cls: dict[str, int] = {}
    n_el = n_hold = 0
    known = {n: 0 for n in NMIN_GRID}
    holders_total = 0
    for m in ds.mints:
        cd = ds.coin(m)
        snap = ds.asof(m, decision_time(cd))
        cls = x1_class(snap)
        n_cls[str(cls)] = n_cls.get(str(cls), 0) + 1
        if not eligible(snap):
            continue
        n_el += 1
        hs = holder_scores(snap, reg)
        holders_total += len(hs)
        n_hold += bool(hs)
        for n in NMIN_GRID:
            known[n] += any(h["n"] >= n for h in hs)
    return {"coins": len(ds), "class_at_decision": n_cls, "eligible": n_el, "eligible_with_holder": n_hold,
            "holders_per_eligible_coin": holders_total / n_el if n_el else None,
            "eligible_with_known_holder": {f"n{k}": v for k, v in known.items()}}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, history: Sequence[C.Dataset] | None = None, census: C.Census | None = None,
              flow: Path | None = None, ledger_path: Path | None = None, shortlist_path: Path | None = None,
              B: int = 10_000, n_placebo: int = 20, env: Mapping[str, str] | None = None,
              _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write X1/<stage>.json + .md (``ds`` / ``history`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "x1_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise X1Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise X1Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise X1Refused("no configs to run (shortlist missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise X1Refused(str(e)) from e
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
        hist = list(history) if history is not None else history_datasets(stage, ds, flow, census)
        if not (debug or _skip_coverage):
            _check_history(stage, ds, hist)
        reg = build_registry(hist)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "n_coins": len(ds), "span_days": _span_days(ds),
                               "history_splits": [h.split for h in hist], "registry": reg.stats()}
        if stage in ("train", "debug"):
            obs = gate_obs(ds, reg)
            gate = gate_decision(obs, B=min(B, GATE_BLOCK_B), hide=debug)
            gate["trial"] = C.record_run(HYP_GATE, GATE_PARAMS, split, {"n": gate["n_obs"], "mean": None}, ledger_path,
                                         debug=debug)
            doc["gate"] = gate
            if debug:
                doc["event_counts"] = event_counts(ds, reg)
            elif gate["decision"] != "PASS":
                v = "KILLED_GATE" if gate["decision"] == "KILL" else "UNDERPOWERED_GATE"
                doc["decision"] = {"verdict": v, "shortlist_written": False,
                                   "note": "PREREG 8: the persistence gate precedes any P&L; the grid was not run"}
                return _finish(doc, out_dir, stage, provisional, t0, ledger_path)
        strat = make_strategy(reg)
        results: dict[str, C.Result] = {}
        for role, h, p in configs:
            results[role] = C.backtest(strat, split, p, hypothesis=h, ds=ds, cfg=CFG, placebo=True, n_placebo=n_placebo,
                                       placebo_eligible=placebo_ok, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path,
                                       placebo_controls={CONTROL: {"eligible": make_control(reg, p), "strata": None}})
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, reg, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {k: (e["n"] / days if math.isfinite(days) and days > 0 else None) for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 9 best qualifying config {dec['best']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            doc["decision"] = decide_val(evals["candidate"])
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val")
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = x1_extras(evals["candidate"])
            doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "x1_extras": extras}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"x1 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise X1Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.assign(role=role, config=config_key(r.meta["params"]), hypothesis=r.meta["hypothesis"])
              for role, r in results.items()]
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str = "candidate") -> pd.DataFrame | None:
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
    if tv == "KILLED_GATE":
        return "KILLED (persistence gate: wallet skill does not persist)"
    if tv == "UNDERPOWERED_GATE":
        return "UNDERPOWERED (too few coins with known early holders for the persistence gate)"
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
    rg = doc.get("registry") or {}
    L = [f"# X1 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days; "
         f"registry history: {doc.get('history_splits')}.",
         f"- **Registry (counts):** {rg.get('history_coins')} history coins, {rg.get('eligible_coins')} eligible "
         f"({rg.get('labelled_coins')} with a resolved base trade); {rg.get('wallets')} early-holder wallets, "
         f"{rg.get('entries')} entries; wallets with ≥ 3 / ≥ 6 entries: {rg.get('wallets_ge3_entries')} / "
         f"{rg.get('wallets_ge6_entries')}; most entries for one wallet: {rg.get('max_entries_one_wallet')}.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall X1 status:** {doc.get('overall')}.", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, labels, skills and the gate "
              "statistic are hidden and no parameter was chosen here.**", ""]
    g = doc.get("gate")
    if g:
        L += ["## Persistence gate (PREREG 8)", "",
              f"- Eligible coins: {g['n_eligible']}; observations (≥ 1 early holder known at n ≥ {N_GATE}): {g['n_obs']} "
              f"(need ≥ {GATE_MIN_OBS}); groups {g.get('groups')}; distinct scoring wallets {g.get('n_score_wallets')}; "
              f"warm-up observations {g.get('n_warmup_obs')}.",
              f"- Decision: **{g['decision']}**."]
        if g.get("rho") is not None:
            L.append(f"- Spearman ρ = {g['rho']:+.4f}, one-sided p = {g['p_one_sided']:.4g}, 6-h block 90% CI "
                     f"{g.get('ci90_block')} (need ρ ≥ {GATE_MIN_RHO}, p < {GATE_MAX_P}, CI low > 0).")
        if g.get("diagnostics"):
            L.append(f"- Diagnostics (never decisive): {g['diagnostics']}.")
        L.append("")
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts at the decision (no returns)", "",
              f"- Classes: {ec['class_at_decision']}; eligible {ec['eligible']}; with ≥ 1 early holder "
              f"{ec['eligible_with_holder']} (holders per eligible coin {ec['holders_per_eligible_coin']}); with a known "
              f"holder: {ec['eligible_with_known_holder']}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | lead wallets | warm-up trades | placebo trades | control trades | "
                  "horizon exits | entries/day |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['n_leads']} | {e['n_warmup']} | "
                         f"{e['n_placebo']} | {e['n_control']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} |")
        else:
            L += ["| role | config | n | leads | mean | 90% CI coin | 90% CI 6-h block | 90% CI lead | w/o top 2 | "
                  "w/o top lead | placebo diff | control diff | costs ×1.5 | w/o warm-up |",
                  "|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ld = e.get("leads") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_leads']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_ci(ld.get('ci90_lead'))} | "
                         f"{_pct(e.get('mean_without_top2'))} | {_pct(ld.get('mean_without_top_lead'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('control') or {}).get('mean_diff'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} | "
                         f"{_pct((e.get('warmup') or {}).get('mean_without_warmup'))} |")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, leads {r['n_leads']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, placebo diff {_pct(r['placebo_diff'])}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']}"
                 + (f" ({dec['best']})" if dec.get("best") else "") + ".")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("x1_extras", []):
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
    ap = argparse.ArgumentParser(description="X1 smart-money follow (wave-2 sweep): pre-registered stages; see "
                                             "research/lab2/X1/PREREG.md")
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
    except X1Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

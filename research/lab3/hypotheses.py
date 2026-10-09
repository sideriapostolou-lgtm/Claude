"""Lab 3 hypotheses (PLAN 4, FIXED grids). Each entry: ``HYP``, ``GRID`` (list of params), ``config_key(p)``,
``signal(P, p) -> DataFrame`` of target positions in [0, 1] (date x asset) using bars up to each date's close.

Signals are long / flat (no shorts). NaN closes (no trade that day) propagate as "hold the previous target".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

import core as C

HERE = Path(__file__).resolve().parent


def _ffill_signal(sig: pd.DataFrame, P: C.Panel) -> pd.DataFrame:
    """A day without a bar keeps the previous target; before the first bar the target is 0."""
    return sig.where(P.close.notna()).ffill().fillna(0.0).clip(0.0, 1.0)


# --------------------------------------------------------------------------- T1 time-series momentum


def t1_signal(P: C.Panel, p: Mapping[str, Any]) -> pd.DataFrame:
    """Long when the L-day return > 0 (vote variant: >= 2 of 3 lookbacks positive)."""
    c = P.close
    if p.get("vote"):
        votes = sum((c / c.shift(L) - 1.0 > 0).astype(float) for L in p["vote"])
        sig = (votes >= 2).astype(float)
    else:
        sig = (c / c.shift(int(p["L"])) - 1.0 > 0).astype(float)
    return _ffill_signal(sig, P)


T1 = {
    "HYP": "T1",
    "name": "time-series momentum (long/flat)",
    "GRID": [{"L": L} for L in (30, 60, 90, 180, 365)] + [{"vote": [60, 120, 240]}],
    "config_key": lambda p: f"L{p['L']}" if "L" in p else "vote60-120-240",
    "signal": t1_signal,
}


# --------------------------------------------------------------------------- T2 moving average / Donchian breakout


def t2_signal(P: C.Panel, p: Mapping[str, Any]) -> pd.DataFrame:
    c = P.close
    if p["kind"] == "sma":
        sig = (c > c.rolling(int(p["N"])).mean()).astype(float)
        return _ffill_signal(sig, P)
    # Donchian: enter on a close at a new N-day high, exit on a close at a new N/2-day low (state machine)
    N = int(p["N"])
    hi = P.close.rolling(N).max().shift(1)
    lo = P.close.rolling(max(2, N // 2)).min().shift(1)
    enter = (c >= hi).to_numpy()
    exit_ = (c <= lo).to_numpy()
    out = np.zeros(c.shape, float)
    state = np.zeros(c.shape[1], float)
    valid = c.notna().to_numpy()
    for i in range(c.shape[0]):
        row_valid = valid[i]
        state = np.where(row_valid & exit_[i], 0.0, state)
        state = np.where(row_valid & enter[i] & ~exit_[i], 1.0, state)
        out[i] = state
    return _ffill_signal(pd.DataFrame(out, index=c.index, columns=c.columns), P)


T2 = {
    "HYP": "T2",
    "name": "moving-average / Donchian breakout (long/flat)",
    "GRID": [{"kind": "sma", "N": N} for N in (50, 100, 200)] + [{"kind": "donchian", "N": N} for N in (55, 100)],
    "config_key": lambda p: f"{p['kind']}{p['N']}",
    "signal": t2_signal,
}


# --------------------------------------------------------------------------- V1 volatility-targeting overlay


def _train_best(hyp: str) -> dict | None:
    """The TRAIN shortlist's first config of another hypothesis (read-only; None before its TRAIN ran)."""
    p = HERE / hyp / "train.json"
    if not p.exists():
        return None
    doc = json.loads(p.read_text())
    sl = (doc.get("decision") or {}).get("shortlist") or []
    return sl[0] if sl else None


def v1_signal(P: C.Panel, p: Mapping[str, Any]) -> pd.DataFrame:
    base_mod = {"T1": T1, "T2": T2}[p["base"]]
    base_params = p.get("base_params") or _train_best(p["base"])
    if base_params is None:
        raise C.Refused(f"V1 needs {p['base']}'s TRAIN shortlist first")
    base = base_mod["signal"](P, base_params)
    lr = np.log(P.close / P.close.shift(1))
    vol = lr.rolling(20).std() * np.sqrt(C.DAYS_PER_YEAR)
    scale = (float(p["target_vol"]) / vol).clip(upper=1.0).fillna(0.0)
    return _ffill_signal(base * scale, P)


V1 = {
    "HYP": "V1",
    "name": "volatility targeting overlay on the TRAIN-best trend signal",
    "GRID": [{"base": b, "target_vol": tv} for b in ("T1", "T2") for tv in (0.40, 0.60)],
    "config_key": lambda p: f"{p['base']}-best|vol{int(round(p['target_vol'] * 100))}",
    "signal": v1_signal,
}


# --------------------------------------------------------------------------- X1 cross-sectional momentum


def x1_signal(P: C.Panel, p: Mapping[str, Any]) -> pd.DataFrame:
    """Weekly (Mondays): rank by the 90-day return, hold the top k with a positive own return; else cash."""
    c = P.close
    mom = c / c.shift(90) - 1.0
    k = int(p["k"])
    U = C.universe_mask(P)
    out = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    rebalance = pd.Series(c.index.dayofweek == 0, index=c.index)
    cur = pd.Series(0.0, index=c.columns)
    for t in c.index:
        if rebalance[t]:
            row = mom.loc[t].where(U.loc[t]).dropna()
            row = row[row > 0].sort_values(ascending=False).head(k)
            cur = pd.Series(0.0, index=c.columns)
            if len(row):
                cur[row.index] = 1.0
        out.loc[t] = cur
    return _ffill_signal(out, P)


X1 = {
    "HYP": "X1",
    "name": "cross-sectional momentum (weekly top-k with positive own momentum)",
    "GRID": [{"k": 3}, {"k": 5}],
    "config_key": lambda p: f"top{p['k']}",
    "signal": x1_signal,
}


# --------------------------------------------------------------------------- R1 short-term mean reversion


def r1_signal(P: C.Panel, p: Mapping[str, Any]) -> pd.DataFrame:
    """Buy at a close below the prior 5-day low (optionally only above the 200-day SMA); exit at the first close
    above the 5-day SMA or after 5 days."""
    c = P.close
    low5 = c.rolling(5).min().shift(1)
    sma5 = c.rolling(5).mean()
    trend_ok = (
        (c > c.rolling(200).mean()) if p.get("trend_filter") else pd.DataFrame(True, index=c.index, columns=c.columns)
    )
    enter = ((c < low5) & trend_ok).to_numpy()
    exit_ = (c > sma5).to_numpy()
    valid = c.notna().to_numpy()
    out = np.zeros(c.shape, float)
    state = np.zeros(c.shape[1], float)
    age = np.zeros(c.shape[1], int)
    for i in range(c.shape[0]):
        v = valid[i]
        age = np.where(state > 0, age + 1, 0)
        leave = v & (state > 0) & (exit_[i] | (age >= 5))
        state = np.where(leave, 0.0, state)
        start = v & (state == 0) & enter[i] & ~leave
        state = np.where(start, 1.0, state)
        age = np.where(start, 0, age)
        out[i] = state
    return _ffill_signal(pd.DataFrame(out, index=c.index, columns=c.columns), P)


R1 = {
    "HYP": "R1",
    "name": "short-term mean reversion (5-day low entry)",
    "GRID": [{"trend_filter": True}, {"trend_filter": False}],
    "config_key": lambda p: "trend200" if p["trend_filter"] else "no-filter",
    "signal": r1_signal,
}

REGISTRY = {h["HYP"]: h for h in (T1, T2, V1, X1, R1)}

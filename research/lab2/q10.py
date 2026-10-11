"""Q10 (LP1): be the house. Deposit $20 of liquidity into a busy, fresh PumpSwap pool and collect the 20 bps LP fee
while carrying half the token's exposure; the lab scores the position like any other trade (worst fills, next-bar
exits, costs, matched random control, counted trials).

Research only (wave-2 lab, idea-mill item q10). Nothing here is wired into the bot: the bot has no deposit /
withdraw path and Jupiter cannot provide one. Pre-registration and the protocol gate (G0):
``research/lab2/Q10/PREREG.md``.

Mechanics (PREREG 1, 3): PumpSwap prices on the effective quote reserve ``X = x_real + v`` (``v`` = the +17.585 SOL
migration boost minus protocol / creator fees waiting in the vault); LP tokens claim the REAL vault pro rata, so an
LP's SOL value is ``s * (q + X)`` with ``q = x_real - waiting fees`` and share ``s``. LP fees stay in the pool (they
are liquidity) and so accrue to ``s``; protocol and creator fees never do. The boost levers the LP's downside.

CLI::

    python research/lab2/q10.py --debug                        # census TRAIN third: counts only
    python research/lab2/q10.py --stage train
    python research/lab2/q10.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/q10.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/q10.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/q10.py --stage final
    python research/lab2/q10.py --stage val --check            # prerequisites only
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
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
from nightcrawler.flow import pumpswap_fee_components  # noqa: E402

VERSION = "q10-v1"
OUT_DIR = HERE / "Q10"
HYP = "Q10"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {
    "debug": "final_train",
    "train": "train",
    "val": "val",
    "test": "test",
    "confirm": "confirm",
    "final": "final",
}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 2-4)
ENTRY_MIN_AGE_S = 600.0  # first decision at or after g + 10 min
ALIVE_VOL_USD_15M = 1500.0  # PLAN R0 alive rule
ALIVE_MCAP_USD = 6000.0
MIN_MCAP_SOL = 420.0  # the 20 bps LP tier starts here (2 bps below)
MAX_ABS_R15 = 0.20  # |15-min return| <= 20 %
QUIET_MULT = 1.0  # exit when 30-min volume < 1 x x_real (no volume, no fees)
QUIET_WINDOW_BARS = 30
EXIT_BY_AGE_S = 178 * 60.0  # registered deadline
SIZE_USD = 20.0
N_TX = 4  # buy, deposit, withdraw, sell
M_GRID = (6, 3)  # V15 >= M x x_real (tie-break: M6 first)
D_GRID = (0.7, 0.5, None)  # stop at D x entry price; None = deadline / quiet only
BUDGET_TRIALS = 8  # PLAN 3.4
# selection and verdict bars
TRAIN_MIN_TRADES = 30
DIRECTION_MIN_N = 30
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FILL = C.FillConfig(exit_delay_bars=1)  # worst fills, next-bar exits (PLAN 3.3, craft rule G22)
STRESS = {
    "costs_x1.5": FILL.stressed(1.5),
    "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
    "same_bar_exits": C.FillConfig(),
    "no_entry_bar_exits": dataclasses.replace(FILL, entry_bar_exits=False),
}
DECL = {
    "uses_organic_flow": False,
    "uses_wallet_reputation": False,
    "uses_truncated_windows": False,
    "uses_current_state_fields": False,
    "position_kind": "lp",
}

FIXED = {
    "version": VERSION,
    "kind": "lp",
    "entry_min_age_s": ENTRY_MIN_AGE_S,
    "alive_vol_usd_15m": ALIVE_VOL_USD_15M,
    "alive_mcap_usd": ALIVE_MCAP_USD,
    "min_mcap_sol": MIN_MCAP_SOL,
    "max_abs_r15": MAX_ABS_R15,
    "quiet_mult": QUIET_MULT,
    "quiet_window_bars": QUIET_WINDOW_BARS,
    "exit_by_age_s": EXIT_BY_AGE_S,
    "size_usd": SIZE_USD,
    "n_tx": N_TX,
    "value": "s * (q + X), q = x_real - max(0, v_ref - v); LP fees accrue, protocol/creator fees do not",
    "placebo": "matched-timing LP deposit in a random alive coin with mcap >= 420 SOL (20 draws per signal)",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar exits, next-bar exits",
}


def make_params(M: int, D: float | None) -> dict:
    if M not in M_GRID or D not in D_GRID:
        raise ValueError(f"config M={M} D={D} not in the PREREG grid")
    return {**FIXED, "M": int(M), "D": (None if D is None else float(D))}


def config_key(p: Mapping[str, Any]) -> str:
    return f"M{int(p['M'])}|" + ("deadline" if p.get("D") is None else f"D{p['D']}")


GRID = [make_params(M, D) for M in M_GRID for D in D_GRID]
CONFIG_ORDER = tuple(config_key(p) for p in GRID)
PRIMARY_PARAMS = make_params(6, 0.7)


class Q10Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing."""


# =========================================================================== eligibility (as-of)


def alive(snap: C.AsOf) -> bool:
    return bool(snap.alive(ALIVE_VOL_USD_15M, ALIVE_MCAP_USD))


def _vol_ratio(snap: C.AsOf) -> float:
    """15-min buy + sell SOL over the real SOL depth, completed bars only (NaN when unknown)."""
    b, k = snap.bars, snap.k
    if k < 1:
        return float("nan")
    xr = float(b.x_real[k - 1])
    if not math.isfinite(xr) or xr <= 0:
        return float("nan")
    lo = max(0, k - 15)
    v15 = float(np.nansum(b.buy_sol[lo:k]) + np.nansum(b.sell_sol[lo:k]))
    return v15 / xr


def control_ok(snap: C.AsOf) -> bool:
    """The matched control's universe: alive, in the 20 bps tier, old enough (PREREG 5)."""
    if snap.age_s < ENTRY_MIN_AGE_S or not alive(snap):
        return False
    return bool(snap.mcap_sol >= MIN_MCAP_SOL)


def eligible(snap: C.AsOf, p: Mapping[str, Any]) -> bool:
    """PREREG 2: alive, mcap >= 420 SOL, |R15| <= 20 %, V15 >= M x x_real."""
    if not control_ok(snap):
        return False
    r15 = snap.ret(900)
    if r15 is None or not math.isfinite(float(r15)) or abs(float(r15)) > MAX_ABS_R15:
        return False
    vr = _vol_ratio(snap)
    return bool(math.isfinite(vr) and vr >= float(p["M"]))


# =========================================================================== the LP position (PREREG 3)


def simulate_lp(
    cd: C.CoinData, t_dec: float, cfg: C.FillConfig, sol_usd: float, D: float | None, size_usd: float = SIZE_USD
) -> dict | None:
    """One LP position decided at ``t_dec``: deposit at t_dec + latency, hold, exit per PREREG 3. Returns a trade
    row (common.TRADE_COLS + LP extras) or None when the position cannot be opened."""
    a = cd.arr
    o, h, lo_, c = a["o"], a["h"], a["l"], a["c"]
    X, xr, y, bsol, ssol = a["X"], a["x_real"], a["y"], a["buy_sol"], a["sell_sol"]
    N = C.N_BARS
    t_in = t_dec + cfg.latency_s
    jf = cd.bar_of(t_in)
    if jf < 1 or jf >= N - 1:
        return None
    p_in = float(max(o[jf], h[jf])) if cfg.entry_fill == "worst" else float(o[jf])
    X0, xr0, y0 = float(X[jf - 1]), float(xr[jf - 1]), float(y[jf - 1])
    if not all(math.isfinite(v) for v in (p_in, X0, xr0, y0)) or p_in <= 0 or xr0 <= 0 or y0 <= 0 or X0 <= 0:
        return None
    v_ref = X0 - xr0
    k0 = cd.k_before(jf)
    S = size_usd / sol_usd
    net = C.network_sol(cfg.cost)
    rent = cfg.rent_usd / sol_usd
    ratio = xr0 / X0  # SOL the vault wants per SOL of token value
    T = S / (1.0 + ratio)  # token leg (SOL spent)
    tokens, br_in = C.simulate_buy(T, p_in, k0, t_in, cfg.cost)
    if tokens <= 0:
        return None
    x_d = tokens * xr0 / y0  # SOL leg at the vault ratio
    cash = S - T - x_d  # SOL that could not be deposited (>= 0 by construction)
    s = tokens / y0
    # the 50/50 hold on the same entry (no fees, no leverage): half SOL, half token bought with the same costs
    tok_h, _ = C.simulate_buy(S / 2.0, p_in, k0, t_in, cfg.cost)
    stop_lvl = None if D is None else D * p_in
    pend: tuple[int, str] | None = None
    fee_income = 0.0
    for i in range(jf, N):
        if pend is None:
            trig = None
            if stop_lvl is not None and (i > jf or cfg.entry_bar_exits) and float(lo_[i]) <= stop_lvl:
                trig = "stop"
            if trig is None and i > jf:
                w0 = max(0, i - QUIET_WINDOW_BARS + 1)
                vol30 = float(np.nansum(bsol[w0 : i + 1]) + np.nansum(ssol[w0 : i + 1]))
                xri = float(xr[i])
                if math.isfinite(xri) and xri > 0 and vol30 < QUIET_MULT * xri:
                    trig = "quiet"
            if trig is None and cd.bar_start(i) >= cd.g + EXIT_BY_AGE_S:
                trig = "deadline"
            if trig is not None:
                pend = (min(i + cfg.exit_delay_bars, N - 1), trig)
        # fee income accrued over bar i (estimate for the decomposition; the real accrual sits inside x_real)
        mc = float(c[i]) * C.TOKEN_SUPPLY if math.isfinite(float(c[i])) else 0.0
        vol_i = float(np.nan_to_num(bsol[i]) + np.nan_to_num(ssol[i]))
        fee_income += s * pumpswap_fee_components(mc)[0] / 1e4 * vol_i
        if (pend is not None and i == pend[0]) or i == N - 1:
            reason = pend[1] if pend is not None and i == pend[0] else "horizon"
            e = i
            p_out = float(min(o[e], lo_[e])) if cfg.exit_fill == "worst" else float(o[e])
            if not math.isfinite(p_out) or p_out <= 0:
                p_out = float(c[e - 1]) if math.isfinite(float(c[e - 1])) and float(c[e - 1]) > 0 else p_in
            Xe, xre, ye = float(X[e - 1]), float(xr[e - 1]), float(y[e - 1])
            if not all(math.isfinite(v) for v in (Xe, xre, ye)) or ye <= 0:
                Xe, xre, ye = X0, xr0, y0
            v_e = Xe - xre
            q = max(0.0, xre - max(0.0, v_ref - v_e))
            t_out = float(cd.bar_start(e) + (59 if reason == "horizon" else 30))
            t_out = max(t_out, t_in)
            ke = cd.k_before(e)
            sell_out, br_out = C.simulate_sell(s * ye, p_out, ke, t_out, cfg.cost)
            sol_out = cash + s * q + sell_out - N_TX * net - rent
            ret = (sol_out - S) / S
            sell_h, _ = C.simulate_sell(tok_h, p_out, ke, t_out, cfg.cost)
            ret_5050 = (S / 2.0 + sell_h - 2 * net - rent - S) / S
            return {
                "mint": cd.mint,
                "split": cd.split,
                "g_ts": cd.g,
                "t_dec": t_dec,
                "t_in": t_in,
                "t_out": t_out,
                "age_in_s": t_in - cd.g,
                "age_dec_s": t_dec - cd.g,
                "entry_price": p_in,
                "exit_price": p_out,
                "mcap_in_sol": p_in * C.TOKEN_SUPPLY,
                "sol_in": S,
                "sol_out": sol_out,
                "ret_net": ret,
                "ret_mid": p_out / p_in - 1.0,
                "reason": reason,
                "tag": "lp",
                "bars_held": e - jf + 1,
                "fee_bps_in": br_in["fee_bps"],
                "fee_bps_out": br_out["fee_bps"],
                "is_placebo": False,
                "stop_pct": None if D is None else 1.0 - D,
                "take_profit_pct": None,
                "trail_pct": None,
                "max_hold_s": None,
                "exit_by_age_s": EXIT_BY_AGE_S,
                "lp_share": s,
                "v_ref": v_ref,
                "v_exit": v_e,
                "cash_sol": cash,
                "fee_income_sol": fee_income,
                "fee_income_ret": fee_income / S,
                "ret_5050": ret_5050,
                "sol_usd": sol_usd,
            }
    return None


LP_EXTRA = (
    "lp_share",
    "v_ref",
    "v_exit",
    "cash_sol",
    "fee_income_sol",
    "fee_income_ret",
    "ret_5050",
    "sol_usd",
    "vol_ratio_in",
    "r15_in",
)


def _decisions(cd: C.CoinData) -> range:
    """Bars j whose end is a decision time at or after g + ENTRY_MIN_AGE_S with room to land and hold."""
    j0 = max(0, cd.bar_of(cd.g + ENTRY_MIN_AGE_S - C.GRID_OFFSET_S) - 1)
    return range(j0, C.N_BARS - 3)


def _decision_time(cd: C.CoinData, j: int) -> float:
    return float(cd.bar_start(j + 1) + C.GRID_OFFSET_S)


def first_decision_time(cd: C.CoinData) -> float:
    """The first grid decision time (minute boundary + GRID_OFFSET_S) with age >= ENTRY_MIN_AGE_S."""
    j = math.ceil((cd.g + ENTRY_MIN_AGE_S - C.GRID_OFFSET_S - cd.m0) / 60.0)
    return float(cd.m0 + 60.0 * j + C.GRID_OFFSET_S)


def lp_trades(ds: C.Dataset, p: Mapping[str, Any], cfg: C.FillConfig) -> pd.DataFrame:
    """One LP position per coin at its first qualifying decision (PREREG 2-3)."""
    rows = []
    for m in ds.mints:
        cd = ds.coin(m)
        for j in _decisions(cd):
            t = _decision_time(cd, j)
            if t > cd.g + EXIT_BY_AGE_S - 120.0:
                break
            snap = ds.asof(m, t)
            if snap.age_s < ENTRY_MIN_AGE_S:
                continue
            if not eligible(snap, p):
                continue
            row = simulate_lp(cd, t, cfg, snap.sol_usd, p["D"])
            if row is not None:
                row["vol_ratio_in"] = _vol_ratio(snap)
                row["r15_in"] = float(snap.ret(900))
                rows.append(row)
            break
    return C._frame(rows, extra=LP_EXTRA)


def lp_placebo(
    ds: C.Dataset,
    p: Mapping[str, Any],
    cfg: C.FillConfig,
    signals: pd.DataFrame,
    n_draws: int = 20,
    seed: int = 0,
    max_tries: int = 200,
) -> pd.DataFrame:
    """PREREG 5: for each signal, ``n_draws`` LP deposits in random coins that pass ``control_ok`` at a decision
    age within +-120 s of the signal's; same exits and costs."""
    rng = np.random.default_rng(seed)
    mints = list(ds.mints)
    rows = []
    for si, sig in signals.reset_index(drop=True).iterrows():
        got = tries = 0
        while got < n_draws and tries < max_tries:
            tries += 1
            m = mints[int(rng.integers(len(mints)))]
            if m == sig["mint"]:
                continue
            cd = ds.coin(m)
            age = float(sig["age_dec_s"]) + float(rng.uniform(-120.0, 120.0))
            j = cd.bar_of(cd.g + age - C.GRID_OFFSET_S) - 1
            if j < 0 or j >= C.N_BARS - 3:
                continue
            t = _decision_time(cd, j)
            if t > cd.g + EXIT_BY_AGE_S - 120.0:
                continue
            snap = ds.asof(m, t)
            if snap.age_s < ENTRY_MIN_AGE_S or not control_ok(snap):
                continue
            row = simulate_lp(cd, t, cfg, snap.sol_usd, p["D"])
            if row is None:
                continue
            row.update(
                {
                    "is_placebo": True,
                    "signal": si,
                    "signal_mint": sig["mint"],
                    "vol_ratio_in": _vol_ratio(snap),
                    "r15_in": float(snap.ret(900)) if snap.ret(900) is not None else float("nan"),
                }
            )
            rows.append(row)
            got += 1
    return C._frame(rows, extra=LP_EXTRA + ("signal", "signal_mint"))


def lp_backtest(
    ds: C.Dataset,
    p: Mapping[str, Any],
    cfg: C.FillConfig,
    *,
    n_placebo: int = 20,
    seed: int = 0,
    stress: Mapping[str, C.FillConfig] | None = None,
    ledger_path: Path | None = None,
    shortlist_path: Path | None = None,
) -> C.Result:
    """The LP analogue of common.backtest: trades, matched placebo, stress runs, one ledger entry."""
    params = dict(p)
    split = ds.split
    debug = split in C.DEBUG_SPLITS
    if not debug:
        C._check_split_env(split)
        C._check_run_allowed(HYP, params, split, ledger_path, shortlist_path)
        C.check_sol_coverage(ds)
    trades = lp_trades(ds, params, cfg)
    pl = (
        lp_placebo(ds, params, cfg, trades, n_placebo, seed)
        if len(trades)
        else C._frame([], extra=LP_EXTRA + ("signal", "signal_mint"))
    )
    st = {k: lp_trades(ds, params, c) for k, c in (stress or {}).items()}
    meta = {
        "hypothesis": HYP,
        "params": params,
        "split": split,
        "debug_only": debug,
        "cfg": {
            "size_usd": cfg.size_usd,
            "latency_s": cfg.latency_s,
            "entry_fill": cfg.entry_fill,
            "exit_fill": cfg.exit_fill,
            "rent_usd": cfg.rent_usd,
            "entry_bar_exits": cfg.entry_bar_exits,
            "exit_delay_bars": cfg.exit_delay_bars,
            "cost": dataclasses.asdict(cfg.cost),
        },
        "n_coins": len(ds),
        "coverage_underpowered": ds.coverage.get("underpowered"),
        "declarations": dict(DECL),
        "seed": seed,
        "utc": C.utc_str(time.time()),
    }
    rets = trades["ret_net"].to_numpy(float)
    info = C.record_run(
        HYP,
        params,
        split,
        {"n": int(len(rets)), "mean": float(rets.mean()) if len(rets) else None},
        ledger_path,
        debug=debug,
        cfg=cfg,
        kind="lp",
    )
    meta.update(info)
    return C.Result(trades=trades, placebo=pl, stress=st, meta=meta)


# =========================================================================== evaluation


def direction(ev: Mapping[str, Any]) -> str:
    """PREREG 4: BEATS_RANDOM / WORSE_THAN_RANDOM / NEITHER from the judged control's diff 95 % CI."""
    if ev.get("n", 0) < DIRECTION_MIN_N:
        return "UNDERPOWERED"
    ci = (ev.get("placebo") or {}).get("diff_ci95")
    if not ci:
        return "NEITHER"
    if ci[0] > 0:
        return "BEATS_RANDOM"
    if ci[1] < 0:
        return "WORSE_THAN_RANDOM"
    return "NEITHER"


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, strata, placebo n, horizon exits)."""
    t = res.trades
    cens = (t["reason"] == "horizon").to_numpy(bool) if len(t) else np.zeros(0, bool)
    base = {
        "config": config_key(res.meta["params"]),
        "params_hash": C.params_hash(res.meta["params"]),
        "hypothesis": res.meta["hypothesis"],
        "n": int(len(t)),
        "n_coins": int(t["mint"].nunique()) if len(t) else 0,
        "by_stratum_n": t["tag"].value_counts().to_dict() if len(t) else {},
        "n_placebo": int(len(res.placebo)),
        "horizon_exits": int(cens.sum()),
        "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")},
    }
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update(
        {
            k: d.get(k)
            for k in (
                "mean",
                "median",
                "win_rate",
                "sd",
                "ci90",
                "ci95",
                "ci90_block",
                "ci95_block",
                "n_blocks",
                "censored_share",
                "top_coin_share",
                "top3_coin_share",
                "mean_without_top2",
                "halves",
                "mean_hold_min",
                "deflated_sharpe",
            )
        }
    )
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["lp"] = lp_decomposition(t, B=B)
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_stratum"] = (
        {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("tag")} if len(t) else {}
    )
    base["direction"] = direction(base)
    return base


def lp_decomposition(t: pd.DataFrame, B: int = 2000) -> dict:
    """PREREG 5 same-entry comparisons: the token's mid return, the 50/50 hold without fees, the estimated LP fee
    income and the LP-minus-50/50 gap (fees minus boost leverage) with a coin-bootstrap 95 % CI."""
    if not len(t):
        return {
            "ret_mid_mean": None,
            "ret_5050_mean": None,
            "fee_income_ret_mean": None,
            "lp_minus_5050": None,
            "lp_minus_5050_ci95": None,
        }
    gap = t["ret_net"].to_numpy(float) - t["ret_5050"].to_numpy(float)
    return {
        "ret_mid_mean": float(t["ret_mid"].mean()),
        "ret_5050_mean": float(t["ret_5050"].mean()),
        "fee_income_ret_mean": float(t["fee_income_ret"].mean()),
        "lp_minus_5050": float(gap.mean()),
        "lp_minus_5050_ci95": C.coin_bootstrap_ci(gap, t["mint"].to_numpy(object), 0.95, B),
        "mean_vol_ratio_in": float(t["vol_ratio_in"].mean()),
        "mean_bars_held": float(t["bars_held"].mean()),
    }


def combine_verdict(base: Mapping[str, Any]) -> str:
    """PLAN 3.5 items 1-8 + 10 from common.verdict_entry. Item 9 (FINAL mean > 0) is judged in the overall verdict
    once FINAL ran, so a missing FINAL never makes TEST / CONFIRM 'INCOMPLETE'."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1):
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True:
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def params_of(key: str) -> dict:
    """Inverse of :func:`config_key`."""
    m, d = key.split("|")
    return make_params(int(m[1:]), None if d == "deadline" else float(d[1:]))


def _rank_key(r: Mapping[str, Any]) -> tuple:
    return (-r["ci90_lo"], -r["mean"], CONFIG_ORDER.index(r["config"]))


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 6 TRAIN: qualify (n >= 30, mean > 0, mean w/o top 2 > 0, judged-control diff > 0); rank by the coin
    90 % CI lower bound, then mean, then the PREREG tie-break order (M6 first; D0.7, D0.5, deadline); shortlist =
    the top 2."""
    rows = []
    for p in GRID:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        powered = e["n"] >= TRAIN_MIN_TRADES
        ci = e.get("ci90")
        good = (
            powered
            and e.get("mean") is not None
            and e["mean"] > 0
            and e.get("mean_without_top2") is not None
            and e["mean_without_top2"] > 0
            and pc is not None
            and pc > 0
            and ci is not None
        )
        rows.append(
            {
                "config": config_key(p),
                "powered": powered,
                "qualifies": bool(good),
                "n": e["n"],
                "mean": e.get("mean"),
                "ci90_lo": ci[0] if ci else None,
                "placebo_diff": pc,
                "direction": e.get("direction"),
            }
        )
    prim = evals.get(config_key(PRIMARY_PARAMS), {})
    out = {
        "rows": rows,
        "primary_direction": {"config": config_key(PRIMARY_PARAMS), "direction": prim.get("direction")},
    }
    q = sorted([r for r in rows if r["qualifies"]], key=_rank_key)
    if q:
        top = q[:2]
        sl = [params_of(r["config"]) for r in top]
        return {
            **out,
            "verdict": "SHORTLISTED",
            "shortlist": sl,
            "shortlist_hashes": [C.params_hash(p) for p in sl],
            "shortlist_keys": [config_key(p) for p in sl],
        }
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / judged-control bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = f"no config reached >= {TRAIN_MIN_TRADES} trades (best: {max(r['n'] for r in rows)})"
    return {**out, "verdict": v, "reason": why, "shortlist": [], "shortlist_hashes": [], "shortlist_keys": []}


def decide_val(evals: Mapping[str, Mapping[str, Any]], roles: list[str]) -> dict:
    """PREREG 9 VAL: candidate = the shortlisted config with the higher VAL mean (ties: TRAIN rank = role order);
    the decision is on the candidate only."""

    def m(r):
        v = evals[r].get("mean")
        return -math.inf if v is None else v

    cand = sorted(roles, key=lambda r: (-m(r), roles.index(r)))[0]
    twin = next((r for r in roles if r != cand), None)
    e = evals[cand]
    n, mean, mw2 = e["n"], e.get("mean"), e.get("mean_without_top2")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {
        "verdict": v,
        "candidate_role": cand,
        "twin_role": twin,
        "candidate_hash": e["params_hash"],
        "twin_hash": evals[twin]["params_hash"] if twin else None,
        "candidate_config": e["config"],
        "n": n,
        "mean": mean,
        "mean_without_top2": mw2,
        "proceed": v in PROCEED_VAL,
    }


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 9: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Q10 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds Q10 never touched; the debug third is reported apart."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {
        "verdict": "REPORTED",
        "judged_on": list(FINAL_JUDGED),
        "n": int(len(judged)),
        "mean": float(judged["ret_net"].mean()) if len(judged) else None,
        "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0),
        "per_third": per,
        "debug_third": {
            "n": int(len(dbg)),
            "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
            "note": "census TRAIN third: hosted the debug run (PREREG 13), not judged",
        },
    }


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2), no mid-run hour, <= 5 % tradeable coins missing B2,
    SOL/USD covering the split."""
    if not cov.get("usable"):
        return False, ["no usable coins: the backfill has not reached this split yet"]
    notes = []
    if cov.get("chain_hours_scanned_frac", 0) < 0.999:
        notes.append(f"only {cov.get('chain_hours_scanned_frac', 0):.1%} of chain hours scanned")
    for d in cov.get("days", []):
        if d["curve_hours"] < d["hours_in_split"] or d["b2_hours"] < d["hours_in_split"]:
            notes.append(
                f"{d['day']}: curve {d['curve_hours']}/{d['hours_in_split']} h, "
                f"B2 {d['b2_hours']}/{d['hours_in_split']} h"
            )
    notes += C.coverage_problems(cov)
    return not notes, notes


def _runs(ledger_path: Path | None) -> list[dict]:
    with C._ledger(ledger_path, write=False) as led:
        return list(led.get("runs", []))


def _shortlist(shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{HYP}.json")


def stage_configs(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[tuple[str, dict]]:
    """[(role, params)] the stage runs. VAL: the shortlist in TRAIN rank order (roles sl1, sl2). TEST / CONFIRM /
    FINAL: the VAL candidate and its twin."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID]
    sl = _shortlist(shortlist_path)
    if not sl:
        return []
    cfgs = list(sl.get("configs") or [])
    if stage == "val":
        return [(f"sl{i + 1}", c) for i, c in enumerate(cfgs)]
    dec = (_read_json(Path(out_dir) / "val.json") or {}).get("decision") or {}
    by_hash = {C.params_hash(c): c for c in cfgs}
    out = [("candidate", by_hash.get(dec.get("candidate_hash")))]
    if dec.get("twin_hash"):
        out.append(("twin", by_hash.get(dec["twin_hash"])))
    return out


def check_prereqs(
    stage: str,
    out_dir: Path = OUT_DIR,
    *,
    flow: Path | None = None,
    ledger_path: Path | None = None,
    shortlist_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    rerun_reason: str | None = None,
) -> dict:
    """Raise :class:`Q10Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Q10Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Q10Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    # The first TRAIN run of ANY kind freezes PREREG.md: a provisional run shows TRAIN returns too. A train_prelim.json
    # without a lock (written before that rule) pins the sha it recorded.
    frozen = (lock or {}).get("sha256") or (_read_json(out_dir / "train_prelim.json") or {}).get("prereg_sha256")
    if frozen and frozen != _sha(prereg):
        raise Q10Refused(
            "PREREG.md changed after the first TRAIN run (provisional runs included); record changes in "
            "Q10/AMENDMENTS.md as a new version instead"
        )
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Q10Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {
        "stage": stage,
        "prereg_sha256": _sha(prereg),
        "prereg_locked": bool(frozen),
        "data_gates": {"ok": ok, "problems": bad},
    }
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Q10Refused(
                "TRAIN already ran on complete data (Q10/train.json); its decision is final. A re-run needs "
                "--rerun-reason naming the data correction that justifies it"
            )
        return info
    if not train:
        raise Q10Refused("no TRAIN result (Q10/train.json): run --stage train first")
    if train.get("provisional"):
        raise Q10Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Q10Refused(f"TRAIN decision {tv}: Q10 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Q10Refused("no VAL shortlist for Q10 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise Q10Refused("the Q10 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Q10Refused("VAL already ran (Q10/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise Q10Refused("no VAL result (Q10/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise Q10Refused(f"VAL decision {vv}: Q10 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Q10Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok2, why = confirm_allowed(test)
        if not ok2:
            raise Q10Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Q10Refused(f"{stage.upper()} already ran (Q10/{stage}.json exists): one run per hypothesis")
    grp = C.split_group(split)
    if any(
        C.hypothesis_family(r.get("hypothesis", "")) == HYP
        and C.split_group(r.get("split", "")) == grp
        and not r.get("debug")
        for r in _runs(ledger_path)
    ):
        raise Q10Refused(f"{HYP} already had its one {grp} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Q10Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def event_counts(ds: C.Dataset) -> dict:
    """Counts only (no prices, no returns): the universe at the first decision (g + 10 min)."""
    out = {
        "coins": len(ds),
        "alive_at_10min": 0,
        "mcap_ge_420_at_10min": 0,
        "r15_ok_at_10min": 0,
        "vol_ratio_ge": {str(m): 0 for m in M_GRID},
    }
    for m in ds.mints:
        cd = ds.coin(m)
        t = first_decision_time(cd)
        if t > cd.m0 + 60 * (C.N_BARS - 3):
            continue
        snap = ds.asof(m, t)
        if not alive(snap):
            continue
        out["alive_at_10min"] += 1
        if snap.mcap_sol >= MIN_MCAP_SOL:
            out["mcap_ge_420_at_10min"] += 1
        r15 = snap.ret(900)
        if r15 is not None and math.isfinite(float(r15)) and abs(float(r15)) <= MAX_ABS_R15:
            out["r15_ok_at_10min"] += 1
        vr = _vol_ratio(snap)
        for M in M_GRID:
            if math.isfinite(vr) and vr >= M:
                out["vol_ratio_ge"][str(M)] += 1
    return out


def run_stage(
    stage: str,
    *,
    out_dir: Path = OUT_DIR,
    allow_partial: bool = False,
    rerun_reason: str | None = None,
    ds: C.Dataset | None = None,
    census: C.Census | None = None,
    flow: Path | None = None,
    ledger_path: Path | None = None,
    shortlist_path: Path | None = None,
    B: int = 10_000,
    n_placebo: int = 20,
    env: Mapping[str, str] | None = None,
    _skip_coverage: bool = False,
) -> dict:
    """Run one stage end to end and write Q10/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(
        stage,
        out_dir,
        flow=flow,
        ledger_path=ledger_path,
        shortlist_path=shortlist_path,
        env=env,
        rerun_reason=rerun_reason,
    )
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "q10_debug_trials.json"  # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Q10Refused(
                    f"{split} data incomplete: "
                    + "; ".join(notes[:6])
                    + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else "")
                )
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise Q10Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Q10Refused("no configs to run (shortlist or VAL decision missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:  # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Q10Refused(str(e)) from e
        if stage == "train":
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():  # the first TRAIN run, provisional or not, locks PREREG
                (out_dir / "prereg.lock").write_text(
                    json.dumps(
                        {
                            "sha256": info["prereg_sha256"],
                            "locked_utc": C.utc_str(time.time()),
                            "locked_by": "provisional TRAIN" if provisional else "TRAIN",
                        },
                        indent=1,
                    )
                )
            if not provisional and rerun_reason and (out_dir / "train.json").exists():
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    p = out_dir / f"train.{ext}"
                    if p.exists():
                        p.rename(out_dir / f"train_prev_{stamp}.{ext}")
        if ds is None:
            ds = C.load(split, flow=flow, census=census, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        doc: dict[str, Any] = {
            "hypothesis": HYP,
            "version": VERSION,
            "stage": stage,
            "split": split,
            "utc": C.utc_str(time.time()),
            "provisional": provisional,
            "debug_only": debug,
            "prereg_sha256": info["prereg_sha256"],
            "rerun_reason": rerun_reason,
            "coverage": cov,
            "n_coins": len(ds),
            "span_days": _span_days(ds),
        }
        if debug:
            doc["event_counts"] = event_counts(ds)
        results: dict[str, C.Result] = {}
        for role, p in configs:
            results[role] = lp_backtest(
                ds, p, FILL, n_placebo=n_placebo, stress=STRESS, ledger_path=ledger_path, shortlist_path=shortlist_path
            )
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {
                k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()
            }
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(
                    HYP,
                    dec["shortlist"],
                    path=shortlist_path,
                    ledger_path=ledger_path,
                    note=f"{VERSION}: PREREG 9 top-2 rule: {dec['shortlist_keys']}",
                )
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            doc["decision"] = decide_val(evals, [r for r, _ in configs])
        elif stage in ("test", "confirm"):
            val_dec = (_read_json(out_dir / "val.json") or {}).get("decision") or {}
            val_t = _read_trades(out_dir, "val", val_dec.get("candidate_role"))
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            doc["verdict"] = {"verdict": combine_verdict(base), "base": base}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (
        C.one_shot_session(HYP, split, ledger_path, note=f"q10 --stage {stage}")
        if split in C.ONE_RUN_SPLITS
        else contextlib.nullcontext()
    )
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise Q10Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [
        r.trades.assign(role=role, config=config_key(r.meta["params"]), params_hash=C.params_hash(r.meta["params"]))
        for role, r in results.items()
    ]
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str | None) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if role is None or not p.exists():
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


def _r1(x: Any) -> str:
    return "n/a" if x is None else f"{float(x):.1f}"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [
        f"# Q10 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}",
        "",
        f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
        f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
        f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
        f"- **Overall Q10 status:** {doc.get('overall')}.",
        "",
    ]
    if doc.get("debug_only"):
        L += [
            "**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and placebo "
            "outcomes are hidden, and no parameter was chosen here.**",
            "",
        ]
    ec = doc.get("event_counts")
    if ec:
        L += [
            "## Event counts (no returns)",
            "",
            f"- Coins: {ec['coins']}; alive at g+10 min: {ec['alive_at_10min']}; "
            f"of which mcap >= 420 SOL: {ec['mcap_ge_420_at_10min']}; |R15| <= 20 %: {ec['r15_ok_at_10min']}; "
            f"V15 / x_real >= M: {ec['vol_ratio_ge']}.",
            "",
        ]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += [
                "| config | trades | coins | strata | placebo trades | horizon exits | entries/day |",
                "|---|---:|---:|---|---:|---:|---:|",
            ]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(
                    f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_stratum_n']} | {e['n_placebo']} | "
                    f"{e['horizon_exits']} | {'n/a' if epd is None else f'{epd:.1f}'} |"
                )
        else:
            L += [
                "| role | config | n | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (matched) | "
                "diff 95% CI | LP − 50/50 hold | costs ×1.5 | direction |",
                "|---|---|---:|---:|---|---|---:|---:|---|---:|---:|---|",
            ]
            for k, e in cf.items():
                pl = e.get("placebo") or {}
                pu = (e.get("lp") or {}).get("lp_minus_5050")
                L.append(
                    f"| {k} | {e['config']} | {e['n']} | {_pct(e.get('mean'))} | {_ci(e.get('ci90'))} | "
                    f"{_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | {_pct(pl.get('mean_diff'))} | "
                    f"{_ci(pl.get('diff_ci95'))} | {_pct(pu)} | {_pct((e.get('stress') or {}).get('costs_x1.5'))} | "
                    f"{e.get('direction')} |"
                )
        L.append("")
        if not doc.get("debug_only"):
            L += [
                "## LP decomposition (same entries)",
                "",
                "| role | token mid return | 50/50 hold, no fees | est. LP fee income | LP − 50/50 | gap 95% CI | "
                "mean V15/x_real | mean bars held | exit reasons |",
                "|---|---:|---:|---:|---:|---|---:|---:|---|",
            ]
            for k, e in cf.items():
                lp = e.get("lp") or {}
                L.append(
                    f"| {k} | {_pct(lp.get('ret_mid_mean'))} | {_pct(lp.get('ret_5050_mean'))} | "
                    f"{_pct(lp.get('fee_income_ret_mean'))} | {_pct(lp.get('lp_minus_5050'))} | "
                    f"{_ci(lp.get('lp_minus_5050_ci95'))} | {_r1(lp.get('mean_vol_ratio_in'))} | "
                    f"{_r1(lp.get('mean_bars_held'))} | {e.get('reasons')} |"
                )
            L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(
            f"- {r['config']}: n {r['n']}, mean {_pct(r['mean'])}, 90% CI low {_pct(r['ci90_lo'])}, placebo diff "
            f"{_pct(r['placebo_diff'])}, direction {r['direction']}, qualifies {r['qualifies']}."
        )
    if dec.get("primary_direction"):
        L.append(f"- Primary direction reading (PREREG 8): {dec['primary_direction']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} {dec.get('shortlist_keys')}.")
    if dec.get("candidate_role"):
        L.append(
            f"- VAL candidate: {dec['candidate_role']} ({dec.get('candidate_config')}); twin {dec.get('twin_role')}."
        )
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
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
    ap = argparse.ArgumentParser(
        description="Q10 LP1 (be the house): pre-registered stages; see research/lab2/Q10/PREREG.md"
    )
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
        doc = run_stage(
            stage,
            allow_partial=a.allow_partial,
            rerun_reason=a.rerun_reason,
            B=a.B,
            n_placebo=a.n_placebo,
        )
    except Q10Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(
        f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
        f"overall: {doc.get('overall')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

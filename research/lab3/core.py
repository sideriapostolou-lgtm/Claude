"""Lab 3 core: daily panel, walk-forward splits, long/flat portfolio engine with costs, metrics, exposure-matched
placebo, trial ledger. Pre-registration: ``research/lab3/PLAN.md`` (sections 2-5 are implemented here, FIXED).

Conventions. A *signal* is ``f(P, params) -> DataFrame`` of target positions in [0, 1], indexed by UTC date with one
column per asset, where the value at date ``t`` may use every bar up to and including ``t``'s close. The engine
lags it one bar (held on ``t + 1``), charges turnover, equal-weights the assets in the universe that day, and
scores the portfolio's daily close-to-close returns on the requested split only (warm-up may read earlier bars,
outcomes never do).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD", "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad"
    )
)
DATA = Path(os.environ.get("LAB3_DATA", str(SCRATCH / "lab3")))
LEDGER = HERE / "trials.json"
LAB2_LEDGER = HERE.parent / "lab2" / "trials.json"

# =========================================================================== PLAN 2-3 (FIXED)
SPLITS: dict[str, tuple[str, str | None]] = {
    "train": ("2015-01-01", "2025-01-01"),
    "val": ("2025-01-01", "2026-01-01"),
    "test": ("2026-01-01", None),
}
ONE_LOOK = {"test": "LAB3_ALLOW_TEST"}
COST_BPS_SIDE = 25.0  # Jupiter route fee + Ultra + spread, one side, per unit of turnover
STRESS_BPS_SIDE = 50.0
NETWORK_USD = 0.02  # per swap
CAPITAL_USD = 100.0  # the sleeve the network fee is measured against
REBAL_MIN = 0.05  # ignore target changes smaller than 5 % of the sleeve
MIN_HISTORY = 200  # completed daily bars before an asset enters the universe
MIN_VOL_USD_30D = 1_000_000  # 30-day median USD volume
DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class Costs:
    bps_side: float = COST_BPS_SIDE
    network_usd: float = NETWORK_USD
    capital_usd: float = CAPITAL_USD
    rebal_min: float = REBAL_MIN

    def stressed(self, factor: float = 2.0) -> "Costs":
        return dataclasses.replace(self, bps_side=self.bps_side * factor, network_usd=self.network_usd * factor)


# =========================================================================== data


@dataclass
class Panel:
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume_usd: pd.DataFrame

    @property
    def assets(self) -> list[str]:
        return list(self.close.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index


def load_daily(path: Path | None = None, assets: list[str] | None = None) -> pd.DataFrame:
    p = Path(path) if path else DATA / "candles_1d.parquet"
    df = pd.read_parquet(p)
    if assets:
        df = df[df["asset"].isin(assets)]
    df = df.sort_values(["asset", "ts"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.normalize()
    return df


def panel(df: pd.DataFrame) -> Panel:
    """Wide frames (date x asset) on the union calendar; a missing bar stays NaN (no trade that day)."""

    def wide(col: str) -> pd.DataFrame:
        return df.pivot_table(index="date", columns="asset", values=col, aggfunc="last").sort_index()

    close = wide("close")
    vol = wide("volume") * close
    return Panel(open=wide("open"), high=wide("high"), low=wide("low"), close=close, volume_usd=vol)


def universe_mask(P: Panel, min_history: int = MIN_HISTORY, min_vol_usd: float = MIN_VOL_USD_30D) -> pd.DataFrame:
    """PLAN 1: an asset is in the universe on date t when it has >= min_history completed bars before t and its
    30-day median USD volume (ending at t) is >= min_vol_usd. Decided from data up to t's close."""
    have = P.close.notna().cumsum()
    hist_ok = have.shift(1).fillna(0) >= min_history
    vol_ok = P.volume_usd.rolling(30, min_periods=20).median() >= min_vol_usd
    return (hist_ok & vol_ok & P.close.notna()).astype(bool)


def split_mask(index: pd.DatetimeIndex, split: str) -> np.ndarray:
    lo, hi = SPLITS[split]
    m = index >= pd.Timestamp(lo, tz="UTC")
    if hi is not None:
        m &= index < pd.Timestamp(hi, tz="UTC")
    return np.asarray(m)


# =========================================================================== engine


@dataclass
class Run:
    ret: pd.Series  # portfolio daily simple return (after costs), split dates only
    gross: pd.Series  # before costs
    exposure: pd.Series  # sum of weights x positions held that day
    turnover: pd.Series  # sum |delta position| x weight that day
    cost: pd.Series  # cost fraction charged that day
    held: pd.DataFrame  # positions held per asset (lagged, after the rebalance filter)
    n_universe: pd.Series

    def equity(self) -> pd.Series:
        return (1.0 + self.ret).cumprod()


def _held_positions(target: pd.DataFrame, rebal_min: float) -> pd.DataFrame:
    """Lag the target one bar and apply the rebalance filter per asset (hold the old position when the change is
    small). Vectorised where positions are binary; a small Python loop otherwise."""
    tgt = target.shift(1).fillna(0.0).to_numpy(float)
    out = np.zeros_like(tgt)
    cur = np.zeros(tgt.shape[1])
    for i in range(tgt.shape[0]):
        row = tgt[i]
        move = np.abs(row - cur) > rebal_min
        cur = np.where(move, row, cur)
        out[i] = cur
    return pd.DataFrame(out, index=target.index, columns=target.columns)


def backtest(
    P: Panel, target: pd.DataFrame, split: str, costs: Costs | None = None, universe: pd.DataFrame | None = None
) -> Run:
    """PLAN 3: equal weight across the universe, each asset at its own held position, close-to-close returns,
    turnover costs (bps + network fee per swap on the sleeve). Returns the split's daily series."""
    costs = costs if costs is not None else Costs()
    U = universe if universe is not None else universe_mask(P)
    target = target.reindex(index=P.dates, columns=P.assets).fillna(0.0).clip(0.0, 1.0)
    target = target.where(U, 0.0)  # out of the universe: flat
    held = _held_positions(target, costs.rebal_min)
    r = P.close.pct_change(fill_method=None).fillna(0.0)  # a missing bar: 0 return (no trade)
    U_held = U.shift(1).fillna(False).astype(bool)  # the universe known at the decision close
    n_u = U_held.sum(axis=1).replace(0, np.nan)
    w = U_held.astype(float).div(n_u, axis=0).fillna(0.0)  # equal weight across the universe
    gross = (w * held * r).sum(axis=1)
    d_pos = held.diff().fillna(held)  # the first day's position is a trade
    turnover = (w * d_pos.abs()).sum(axis=1)
    n_swaps = (d_pos.abs() > 1e-12).sum(axis=1)
    cost = turnover * costs.bps_side / 1e4 + n_swaps * costs.network_usd / costs.capital_usd
    ret = gross - cost
    m = split_mask(P.dates, split)
    sel = lambda s: s[m]  # noqa: E731
    return Run(
        ret=sel(ret),
        gross=sel(gross),
        exposure=sel((w * held).sum(axis=1)),
        turnover=sel(turnover),
        cost=sel(cost),
        held=held[m],
        n_universe=sel(U_held.sum(axis=1)),
    )


# =========================================================================== metrics


def max_drawdown(ret: pd.Series) -> float:
    eq = (1.0 + ret).cumprod()
    return float((eq / eq.cummax() - 1.0).min()) if len(eq) else 0.0


def describe(
    ret: pd.Series, exposure: pd.Series | None = None, turnover: pd.Series | None = None, cost: pd.Series | None = None
) -> dict[str, Any]:
    r = ret.to_numpy(float)
    n = len(r)
    if n < 2:
        return {"n_days": n, "cagr": None, "sharpe": None}
    lr = np.log1p(np.clip(r, -0.999, None))
    mu, sd = float(lr.mean()), float(lr.std(ddof=1))
    years = n / DAYS_PER_YEAR
    out: dict[str, Any] = {
        "n_days": n,
        "years": round(years, 3),
        "cagr": float(math.exp(mu * DAYS_PER_YEAR) - 1.0),
        "total_return": float(np.prod(1.0 + r) - 1.0),
        "vol_ann": float(sd * math.sqrt(DAYS_PER_YEAR)),
        "sharpe": float(mu / sd * math.sqrt(DAYS_PER_YEAR)) if sd > 0 else None,
        "max_drawdown": max_drawdown(ret),
        "best_day": float(r.max()),
        "worst_day": float(r.min()),
        "share_positive_days": float((r > 0).mean()),
    }
    out["calmar"] = (out["cagr"] / abs(out["max_drawdown"])) if out["max_drawdown"] < 0 else None
    if exposure is not None:
        out["exposure"] = float(exposure.mean())
    if turnover is not None:
        out["turnover_per_year"] = float(turnover.sum() / years) if years > 0 else None
    if cost is not None:
        out["cost_drag_per_year"] = float(cost.sum() / years) if years > 0 else None
    return out


def block_bootstrap_ci(
    x: np.ndarray, block: int = 30, B: int = 5000, level: float = 0.95, seed: int = 0
) -> tuple[float, float] | None:
    """CI of the mean of a daily series by resampling contiguous blocks (monthly by default)."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2 * block:
        return None
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(B, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(B, -1)[:, :n]
    means = x[idx].mean(axis=1)
    a = (1 - level) / 2
    return float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


# =========================================================================== exposure-matched placebo (PLAN 4)


def _runs_mean_length(pos: np.ndarray) -> float:
    """Average length of a non-zero run in a position series (the strategy's typical holding period)."""
    on = pos > 0
    if not on.any():
        return 1.0
    edges = np.diff(np.concatenate([[0], on.astype(int), [0]]))
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
    return float(np.mean(ends - starts)) if len(starts) else 1.0


def shuffle_positions(target: pd.DataFrame, universe: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Per asset, block-shuffle the target series inside the asset's universe days: same exposure, same block
    length (the strategy's mean holding period), random timing."""
    rng = np.random.default_rng(seed)
    out = target.copy()
    for a in target.columns:
        u = universe[a].to_numpy(bool)
        pos = target[a].to_numpy(float).copy()
        idx = np.where(u)[0]
        if len(idx) < 10:
            continue
        seq = pos[idx]
        blk = max(1, int(round(_runs_mean_length(seq))))
        nb = int(math.ceil(len(seq) / blk))
        blocks = [seq[i * blk : (i + 1) * blk] for i in range(nb)]
        order = rng.permutation(len(blocks))
        shuffled = np.concatenate([blocks[i] for i in order])[: len(seq)]
        pos[idx] = shuffled
        out[a] = pos
    return out


def placebo_runs(
    P: Panel, target: pd.DataFrame, split: str, costs: Costs, universe: pd.DataFrame, n: int = 200, seed: int = 0
) -> list[Run]:
    return [backtest(P, shuffle_positions(target, universe, seed + i), split, costs, universe) for i in range(n)]


def placebo_compare(run: Run, placebos: list[Run], B: int = 5000) -> dict[str, Any]:
    """Strategy vs its exposure-matched random twins: Sharpe rank (p-value), mean excess daily return vs the
    placebo average path with a monthly block-bootstrap CI."""
    if not placebos:
        return {"n_placebo": 0}
    sh = describe(run.ret)["sharpe"]
    psh = np.array([describe(p.ret)["sharpe"] or 0.0 for p in placebos], float)
    avg = pd.concat([p.ret for p in placebos], axis=1).mean(axis=1)
    excess = (run.ret - avg).to_numpy(float)
    return {
        "n_placebo": len(placebos),
        "placebo_sharpe_mean": float(psh.mean()),
        "placebo_sharpe_p90": float(np.quantile(psh, 0.9)),
        "sharpe_p_value": float((psh >= (sh if sh is not None else -np.inf)).mean()),
        "excess_daily_mean": float(excess.mean()),
        "excess_ann": float(excess.mean() * DAYS_PER_YEAR),
        "excess_ci95": block_bootstrap_ci(excess, B=B),
        "placebo_cagr_mean": float(np.mean([describe(p.ret)["cagr"] or 0.0 for p in placebos])),
        "placebo_mdd_mean": float(np.mean([describe(p.ret)["max_drawdown"] for p in placebos])),
    }


# =========================================================================== benchmarks


def buy_and_hold(P: Panel, universe: pd.DataFrame, assets: list[str] | None = None) -> pd.DataFrame:
    t = pd.DataFrame(1.0, index=P.dates, columns=P.assets)
    if assets:
        t.loc[:, [a for a in P.assets if a not in assets]] = 0.0
    return t.where(universe, 0.0)


# =========================================================================== ledger (counted trials)


def params_hash(params: Mapping[str, Any] | None) -> str:
    return hashlib.sha256(json.dumps(params or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _read_ledger(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"configs": {}, "runs": []}


def record_run(
    hypothesis: str, params: Mapping[str, Any], split: str, summary: Mapping[str, Any], path: Path | None = None
) -> dict:
    path = Path(path) if path else LEDGER
    led = _read_ledger(path)
    cid = f"{hypothesis}|{params_hash(params)}"
    new = cid not in led["configs"]
    if new:
        led["configs"][cid] = {
            "hypothesis": hypothesis,
            "params": dict(params),
            "first_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
    led["runs"].append(
        {
            "config": cid,
            "split": split,
            "utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            **{k: summary.get(k) for k in ("sharpe", "cagr", "max_drawdown", "n_days")},
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(led, indent=1, sort_keys=True, default=str))
    return {
        "config": cid,
        "new_trial": new,
        "n_trials_lab3": len(led["configs"]),
        "n_trials_total": n_trials_total(path),
    }


def n_trials_total(path: Path | None = None) -> int:
    """Program-wide trial count for the deflated Sharpe: lab 2's configs + lab 3's."""
    n = len(_read_ledger(Path(path) if path else LEDGER)["configs"])
    try:
        n += len(json.loads(LAB2_LEDGER.read_text()).get("configs", {}))
    except (OSError, ValueError):
        pass
    return n


def deflated_sharpe(ret: pd.Series, n_trials: int) -> dict[str, Any]:
    """Bailey & Lopez de Prado (2014) on daily log returns, annualised SR reported next to the probability."""
    from statistics import NormalDist

    r = np.log1p(np.clip(ret.to_numpy(float), -0.999, None))
    T = len(r)
    if T < 30 or r.std(ddof=1) == 0:
        return {"dsr": None, "n_trials": n_trials, "T": T}
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=0)
    skew, kurt = float((z**3).mean()), float((z**4).mean())
    N = max(int(n_trials), 2)
    nd, gam = NormalDist(), 0.5772156649
    sr0 = math.sqrt(1.0 / (T - 1)) * ((1 - gam) * nd.inv_cdf(1 - 1 / N) + gam * nd.inv_cdf(1 - 1 / (N * math.e)))
    den = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    dsr = nd.cdf((sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(den, 1e-12)))
    return {"dsr": float(dsr), "sr_daily": float(sr), "sr0_daily": float(sr0), "n_trials": N, "T": T}


# =========================================================================== guards


class Refused(RuntimeError):
    pass


def check_split_allowed(hypothesis: str, split: str, out_dir: Path, env: Mapping[str, str] | None = None) -> None:
    """TEST is one look per hypothesis: needs the env flag and no previous test.json."""
    env = os.environ if env is None else env
    flag = ONE_LOOK.get(split)
    if flag and env.get(flag) != "1":
        raise Refused(f"{split} is a one-look split: set {flag}=1 deliberately (the judge must have read VAL)")
    if flag and (Path(out_dir) / f"{split}.json").exists():
        raise Refused(f"{hypothesis} already spent its {split} look: {Path(out_dir) / (split + '.json')}")


SignalFn = Callable[[Panel, Mapping[str, Any]], pd.DataFrame]

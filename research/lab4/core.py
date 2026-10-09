"""Lab 4 engine: the "near-certain grind" on resolved Polymarket tapes (research/lab4/PLAN.md, version lab4-v1).

Pure functions over the parquet files written by :mod:`data`. Nothing here talks to the network or to the bot.

* :func:`fee_rate` / :func:`taker_fee`: polymarket.com taker fee ``shares x rate x p x (1 - p)`` by fee family
  (PLAN Amendment 1); unknown families pay the most expensive rate.
* :class:`Dataset`: the markets of one split (binary, single winner, >= MIN_FILLS fills) and their tapes, with every
  fill expressed as a price of outcome 0 (a fill on outcome 1 at q is outcome 0 at 1 - q).
* :func:`cell_trades`: one trade per market for a cell (theta, H, families, control): the first fill at or above
  theta within the last H hours before resolution, executed at the first fill LATENCY_S later, held to resolution.
* :func:`summarize`: the pre-registered readings with a market bootstrap; :func:`calibration_placebo`: outcomes
  redrawn as Bernoulli(p_exec).
* :func:`record_run`: the trial ledger shared in count with labs 2 and 3.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "trials.json"
SIBLING_LEDGERS = (
    HERE.parent / "lab2" / "trials.json",
    HERE.parent / "lab3" / "trials.json",
)

# PLAN §1: splits on closedTime (UTC), half-open [start, end).
SPLITS: dict[str, tuple[str, str]] = {
    "train": ("2026-07-01", "2026-08-16"),
    "val": ("2026-08-16", "2026-09-16"),
    "test": ("2026-09-16", "2026-10-09"),
}
MIN_FILLS = 50
TICKET_USD = 20.0
LATENCY_S = 10
EXEC_WINDOW_S = 600
MAX_PRICE = 0.999  # a fill at 1.0 cannot be bought
BOOTSTRAP_B = 2000

# PLAN Amendment 1: taker rate by Gamma feeType family.
FEE_RATES: dict[str, float] = {
    "crypto": 0.07,
    "sports": 0.05,
    "culture": 0.05,
    "economics": 0.05,
    "weather": 0.05,
    "politics": 0.04,
    "finance": 0.04,
    "mentions": 0.04,
    "tech": 0.04,
    "geopolitics": 0.0,
    "zero": 0.0,
}
UNKNOWN_RATE = 0.07
FAMILIES = {
    "sports": ("sports",),
    "crypto": ("crypto",),
    "all": (),
}


def fee_family(fee_type: str | None, fees_enabled: bool) -> str:
    """The fee family of a market: 'none' when fees are off, else the first word of its feeType ('sports_fees_v3'
    -> 'sports'); 'unknown' for a market with fees on and no recognisable type."""
    if not fees_enabled:
        return "none"
    if not fee_type:
        return "unknown"
    head = str(fee_type).split("_")[0].lower()
    return head if head in FEE_RATES else "unknown"


def fee_rate(fee_type: str | None, fees_enabled: bool) -> float:
    fam = fee_family(fee_type, fees_enabled)
    if fam == "none":
        return 0.0
    return FEE_RATES.get(fam, UNKNOWN_RATE)


def taker_fee(shares: float, price: float, rate: float) -> float:
    return float(shares) * rate * float(price) * (1.0 - float(price))


def check_split_allowed(split: str) -> None:
    if split == "test" and os.environ.get("LAB4_ALLOW_TEST") != "1":
        raise PermissionError(
            "TEST is a one-look split: set LAB4_ALLOW_TEST=1 to read it (PLAN §1)"
        )


def split_bounds(split: str) -> tuple[float, float]:
    a, b = SPLITS[split]
    f = lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
    return f(a), f(b)


@dataclass
class Dataset:
    split: str
    markets: (
        pd.DataFrame
    )  # id, closed_time, winner_index, family, rate, volume, question, event_slug
    tapes: dict[str, pd.DataFrame] = field(
        default_factory=dict
    )  # id -> ts, p0 (price of outcome 0), size

    @classmethod
    def load(cls, split: str, out_dir: Path, min_fills: int = MIN_FILLS) -> Dataset:
        check_split_allowed(split)
        lo, hi = split_bounds(split)
        markets = pd.read_parquet(out_dir / "markets.parquet")
        keep = (
            (markets["n_outcomes"] == 2)
            & markets["winner_index"].isin([0, 1])
            & (markets["closed_time"] >= lo)
            & (markets["closed_time"] < hi)
        )
        markets = markets[keep].copy()
        markets["family"] = [
            fee_family(t, bool(e))
            for t, e in zip(markets["fee_type"], markets["fees_enabled"], strict=True)
        ]
        markets["rate"] = [
            fee_rate(t, bool(e))
            for t, e in zip(markets["fee_type"], markets["fees_enabled"], strict=True)
        ]
        tapes: dict[str, pd.DataFrame] = {}
        kept_ids = []
        for r in markets.itertuples(index=False):
            path = out_dir / "trades" / f"{r.id}.parquet"
            if not path.exists():
                continue
            t = pd.read_parquet(path)
            t = t[
                (t["ts"] > 0)
                & (t["price"] > 0)
                & (t["price"] < 1)
                & t["outcome_index"].isin([0, 1])
            ]
            if len(t) < min_fills:
                continue
            p0 = np.where(
                t["outcome_index"].to_numpy() == 0,
                t["price"].to_numpy(),
                1.0 - t["price"].to_numpy(),
            )
            tapes[r.id] = (
                pd.DataFrame(
                    {"ts": t["ts"].to_numpy(), "p0": p0, "size": t["size"].to_numpy()}
                )
                .sort_values("ts")
                .reset_index(drop=True)
            )
            kept_ids.append(r.id)
        markets = (
            markets[markets["id"].isin(kept_ids)]
            .sort_values("closed_time")
            .reset_index(drop=True)
        )
        return cls(split, markets, tapes)

    def families(self, name: str) -> pd.DataFrame:
        heads = FAMILIES[name]
        return (
            self.markets
            if not heads
            else self.markets[self.markets["family"].isin(heads)]
        )


def cell_trades(
    ds: Dataset,
    theta: float,
    hours: float,
    families: str = "all",
    control: bool = False,
    ticket: float = TICKET_USD,
    latency_s: int = LATENCY_S,
) -> pd.DataFrame:
    """One trade per market: buy the outcome whose price first reaches ``theta`` (control: ``1 - theta`` from
    below, the longshot) within the last ``hours`` before resolution, at the first fill ``latency_s`` later."""
    rows: list[dict[str, Any]] = []
    for m in ds.families(families).itertuples(index=False):
        tape = ds.tapes[m.id]
        ts = tape["ts"].to_numpy()
        p0 = tape["p0"].to_numpy()
        start = m.closed_time - hours * 3600.0
        window = (ts >= start) & (ts < m.closed_time)
        if not window.any():
            continue
        if control:
            hit0, hit1 = p0 <= 1.0 - theta, (1.0 - p0) <= 1.0 - theta
        else:
            hit0, hit1 = p0 >= theta, (1.0 - p0) >= theta
        cand = window & (hit0 | hit1)
        if not cand.any():
            continue
        i = int(np.argmax(cand))  # the first qualifying fill
        outcome = 0 if hit0[i] else 1
        p_signal = p0[i] if outcome == 0 else 1.0 - p0[i]
        t_signal = ts[i]
        j = int(np.searchsorted(ts, t_signal + latency_s, side="left"))
        row = {
            "id": m.id,
            "family": m.family,
            "question": m.question,
            "closed_time": float(m.closed_time),
            "outcome": outcome,
            "t_signal": float(t_signal),
            "p_signal": float(p_signal),
            "day": datetime.fromtimestamp(float(m.closed_time), UTC).strftime(
                "%Y-%m-%d"
            ),
        }
        if j >= len(ts) or ts[j] - t_signal > EXEC_WINDOW_S or ts[j] >= m.closed_time:
            rows.append(
                {
                    **row,
                    "missed": True,
                    "t_exec": None,
                    "p_exec": None,
                    "won": None,
                    "net": None,
                    "fee_usd": None,
                    "pnl_usd": None,
                    "lock_h": None,
                }
            )
            continue
        p_exec = float(p0[j] if outcome == 0 else 1.0 - p0[j])
        p_exec = min(p_exec, MAX_PRICE)
        if p_exec <= 0.0:
            continue
        shares = ticket / p_exec
        fee = taker_fee(shares, p_exec, m.rate)
        won = int(m.winner_index) == outcome
        payout = shares if won else 0.0
        pnl = payout - fee - ticket
        rows.append(
            {
                **row,
                "missed": False,
                "t_exec": float(ts[j]),
                "p_exec": p_exec,
                "won": bool(won),
                "net": pnl / ticket,
                "fee_usd": fee,
                "pnl_usd": pnl,
                "lock_h": (m.closed_time - float(ts[j])) / 3600.0,
            }
        )
    cols = [
        "id",
        "family",
        "question",
        "closed_time",
        "outcome",
        "t_signal",
        "p_signal",
        "day",
        "missed",
        "t_exec",
        "p_exec",
        "won",
        "net",
        "fee_usd",
        "pnl_usd",
        "lock_h",
    ]
    return pd.DataFrame(rows, columns=cols)


def market_bootstrap_ci(
    values: np.ndarray, B: int = BOOTSTRAP_B, seed: int = 0
) -> tuple[float, float]:
    """95 % interval of the mean under resampling of the trades (one trade per market, so markets)."""
    if len(values) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(B, len(values)))
    means = values[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def _longest_losing_streak(won: np.ndarray) -> int:
    best = cur = 0
    for w in won:
        cur = 0 if w else cur + 1
        best = max(best, cur)
    return int(best)


def summarize(trades: pd.DataFrame, split: str, B: int = BOOTSTRAP_B) -> dict[str, Any]:
    """PLAN §4 readings for one cell."""
    lo, hi = split_bounds(split)
    days = max(1.0, (hi - lo) / 86400.0)
    filled = trades[~trades["missed"].astype(bool)] if len(trades) else trades
    out: dict[str, Any] = {
        "n": len(filled),
        "missed": int(len(trades) - len(filled)),
        "trades_per_day": len(filled) / days,
    }
    if len(filled) == 0:
        return {
            **out,
            "win_rate": None,
            "mean_p_exec": None,
            "calibration_gap": None,
            "mean_net": None,
            "ci95": [None, None],
            "mean_pnl_usd": None,
            "worst_pnl_usd": None,
            "longest_losing_streak": 0,
            "lock_h_mean": None,
            "lock_h_median": None,
            "daily": {
                "n_days": 0,
                "sharpe": None,
                "max_drawdown_usd": None,
                "total_usd": 0.0,
            },
            "by_family": {},
        }
    f = filled.sort_values("t_exec")
    net = f["net"].to_numpy(dtype=float)
    won = f["won"].to_numpy(dtype=bool)
    ci = market_bootstrap_ci(net, B=B)
    daily = f.groupby("day")["pnl_usd"].sum().sort_index()
    cum = daily.cumsum()
    dd = float((cum - cum.cummax()).min()) if len(cum) else 0.0
    sharpe = (
        float(daily.mean() / daily.std(ddof=1) * np.sqrt(365.0))
        if len(daily) > 1 and daily.std(ddof=1) > 0
        else None
    )
    by_family = {}
    for fam, g in f.groupby("family"):
        by_family[str(fam)] = {
            "n": len(g),
            "win_rate": float(g["won"].mean()),
            "mean_p_exec": float(g["p_exec"].mean()),
            "mean_net": float(g["net"].mean()),
            "total_usd": float(g["pnl_usd"].sum()),
        }
    return {
        **out,
        "win_rate": float(won.mean()),
        "mean_p_exec": float(f["p_exec"].mean()),
        "calibration_gap": float(won.mean() - f["p_exec"].mean()),
        "mean_net": float(net.mean()),
        "ci95": [ci[0], ci[1]],
        "mean_pnl_usd": float(f["pnl_usd"].mean()),
        "worst_pnl_usd": float(f["pnl_usd"].min()),
        "longest_losing_streak": _longest_losing_streak(won),
        "lock_h_mean": float(f["lock_h"].mean()),
        "lock_h_median": float(f["lock_h"].median()),
        "daily": {
            "n_days": len(daily),
            "sharpe": sharpe,
            "max_drawdown_usd": dd,
            "total_usd": float(daily.sum()),
        },
        "by_family": by_family,
    }


def calibration_placebo(
    trades: pd.DataFrame, draws: int = BOOTSTRAP_B, seed: int = 1
) -> dict[str, Any]:
    """Outcomes redrawn as Bernoulli(p_exec): the distribution of mean net return if the market were perfectly
    calibrated (no edge, only fees). Reports the real mean's percentile in it."""
    filled = trades[~trades["missed"].astype(bool)]
    if len(filled) == 0:
        return {"draws": 0, "p95": None, "mean": None, "real_percentile": None}
    p = filled["p_exec"].to_numpy(dtype=float)
    fee = filled["fee_usd"].to_numpy(dtype=float)
    ticket = TICKET_USD
    shares = ticket / p
    rng = np.random.default_rng(seed)
    wins = rng.random((draws, len(p))) < p
    pnl = np.where(wins, shares, 0.0) - fee - ticket
    means = pnl.mean(axis=1) / ticket
    real = float(filled["net"].mean())
    return {
        "draws": draws,
        "p95": float(np.percentile(means, 95)),
        "mean": float(means.mean()),
        "real_percentile": float((means < real).mean() * 100.0),
    }


def qualifies(s: dict[str, Any], min_n: int = 100) -> bool:
    return (
        s["n"] >= min_n
        and s["mean_net"] is not None
        and s["ci95"][0] is not None
        and s["ci95"][0] > 0
        and s["mean_net"] > 0
    )


def trials_count() -> int:
    n = 0
    for path in (*SIBLING_LEDGERS, LEDGER):
        if path.exists():
            try:
                doc = json.loads(path.read_text())
            except ValueError:
                continue
            n += len(doc) if isinstance(doc, list) else len(doc.get("trials", []))
    return n


def record_run(entry: dict[str, Any]) -> int:
    """Append one trial to research/lab4/trials.json; returns the running count across labs 2, 3 and 4."""
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    ledger.append(
        {
            **entry,
            "utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "t": time.time(),
        }
    )
    LEDGER.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")
    return trials_count()

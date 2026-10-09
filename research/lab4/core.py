"""Lab 4 engine: the "near-certain grind" on resolved Polymarket tapes (research/lab4/PLAN.md, lab4-v1 + Amendments
1-3).

Pure functions over the parquet files written by :mod:`data`. Nothing here talks to the network or to the bot.

* :func:`fee_rate` / :func:`taker_fee`: polymarket.com taker fee ``shares x rate x p x (1 - p)`` by fee family
  (Amendment 1); unknown families pay the most expensive rate.
* :class:`Dataset`: the markets of one split (binary, single winner, >= MIN_FILLS fills) and their tapes. Every
  fill is kept with its taker side and expressed as a price of outcome 0 (a fill on outcome 1 at q is outcome 0 at
  1 - q) plus ``buy0``: whether that print was BUYABLE for outcome 0 (a BUY on token 0 or a SELL on token 1), per
  Amendment 3.
* :func:`cell_trades`: one trade per market for a cell (theta, H, families, control): the first buyable print at or
  above theta for an outcome inside the window ``[endDate - H, endDate)`` (``H = inf``: anywhere before resolution),
  executed at the first buyable print for the same outcome LATENCY_S later, held to resolution.
* :func:`summarize`: the pre-registered readings with an event bootstrap, the rule-of-three worst case and the
  share of trades the old (side-blind) rule would have filled at a bid-side print; :func:`calibration_placebo`.
* :func:`record_run`: the trial ledger (one entry per hypothesis, cell, split and stage), shared in count with
  labs 2 and 3.
"""

from __future__ import annotations

import json
import math
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
INF = math.inf

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
    "nonsports": (
        "crypto",
        "politics",
        "culture",
        "finance",
        "economics",
        "weather",
        "mentions",
        "tech",
        "geopolitics",
        "none",
        "unknown",
    ),
    "all": (),
}


def fee_family(fee_type: str | None, fees_enabled: bool) -> str:
    """'none' when fees are off, else the first word of feeType ('sports_fees_v3' -> 'sports'); 'unknown' otherwise."""
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

    def f(s: str) -> float:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()

    return f(a), f(b)


@dataclass
class Dataset:
    split: str
    markets: pd.DataFrame  # id, closed_time, end_date, winner_index, family, rate, volume, question, event_slug
    tapes: dict[str, pd.DataFrame] = field(
        default_factory=dict
    )  # id -> ts, p0, buy0, size
    coverage: dict[str, Any] = field(default_factory=dict)  # eligible, with_tape, share

    @classmethod
    def eligible(cls, markets: pd.DataFrame, split: str) -> pd.DataFrame:
        lo, hi = split_bounds(split)
        keep = (
            (markets["n_outcomes"] == 2)
            & markets["winner_index"].isin([0, 1])
            & (markets["closed_time"] >= lo)
            & (markets["closed_time"] < hi)
        )
        return markets[keep].copy()

    @classmethod
    def load(cls, split: str, out_dir: Path, min_fills: int = MIN_FILLS) -> Dataset:
        check_split_allowed(split)
        markets = cls.eligible(pd.read_parquet(out_dir / "markets.parquet"), split)
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
        with_tape = 0
        for r in markets.itertuples(index=False):
            path = out_dir / "trades" / f"{r.id}.parquet"
            if not path.exists():
                continue
            with_tape += 1
            t = pd.read_parquet(path)
            t = t[
                (t["ts"] > 0)
                & (t["price"] > 0)
                & (t["price"] < 1)
                & t["outcome_index"].isin([0, 1])
            ]
            if len(t) < min_fills:
                continue
            oi = t["outcome_index"].to_numpy()
            side = (
                t["side"].astype(str).str.upper().to_numpy()
                if "side" in t
                else np.array(["BUY"] * len(t))
            )
            p0 = np.where(oi == 0, t["price"].to_numpy(), 1.0 - t["price"].to_numpy())
            buy0 = ((oi == 0) & (side == "BUY")) | ((oi == 1) & (side == "SELL"))
            tapes[r.id] = (
                pd.DataFrame(
                    {
                        "ts": t["ts"].to_numpy(),
                        "p0": p0,
                        "buy0": buy0,
                        "size": t["size"].to_numpy(),
                    }
                )
                .sort_values("ts")
                .reset_index(drop=True)
            )
            kept_ids.append(r.id)
        coverage = {
            "eligible": len(markets),
            "with_tape": int(with_tape),
            "share": (with_tape / len(markets)) if len(markets) else 1.0,
        }
        markets = (
            markets[markets["id"].isin(kept_ids)]
            .sort_values("closed_time")
            .reset_index(drop=True)
        )
        return cls(split, markets, tapes, coverage)

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
    """One trade per market (Amendment 3): the first BUYABLE print at or above ``theta`` for an outcome (control:
    at or below ``1 - theta``, the longshot) inside ``[endDate - hours, endDate)`` (``hours = inf``: any print
    before resolution), executed at the first buyable print for the same outcome ``latency_s`` later."""
    rows: list[dict[str, Any]] = []
    windowed = math.isfinite(hours)
    for m in ds.families(families).itertuples(index=False):
        tape = ds.tapes[m.id]
        ts = tape["ts"].to_numpy()
        p0 = tape["p0"].to_numpy()
        buy0 = tape["buy0"].to_numpy()
        closed = float(m.closed_time)
        end_date = (
            float(m.end_date)
            if m.end_date is not None and not pd.isna(m.end_date)
            else closed
        )
        if windowed:
            end_bound = min(end_date, closed)
            window = (ts >= end_date - hours * 3600.0) & (ts < end_bound)
        else:
            end_bound = closed
            window = ts < closed
        if not window.any():
            continue
        p1 = 1.0 - p0
        if control:
            hit0, hit1 = buy0 & (p0 <= 1.0 - theta), (~buy0) & (p1 <= 1.0 - theta)
        else:
            hit0, hit1 = buy0 & (p0 >= theta), (~buy0) & (p1 >= theta)
        cand = window & (hit0 | hit1)
        if not cand.any():
            continue
        i = int(np.argmax(cand))
        outcome = 0 if hit0[i] else 1
        buyable = buy0 if outcome == 0 else ~buy0
        price_o = p0 if outcome == 0 else p1
        t_signal = float(ts[i])
        row = {
            "id": m.id,
            "event": m.event_slug,
            "family": m.family,
            "question": m.question,
            "closed_time": closed,
            "end_date": end_date,
            "outcome": outcome,
            "t_signal": t_signal,
            "p_signal": float(price_o[i]),
            "day": datetime.fromtimestamp(closed, UTC).strftime("%Y-%m-%d"),
        }
        j0 = int(np.searchsorted(ts, t_signal + latency_s, side="left"))
        # the old (side-blind) rule's execution print, for the transparency column
        old_bid_side = bool(
            j0 < len(ts)
            and ts[j0] - t_signal <= EXEC_WINDOW_S
            and ts[j0] < end_bound
            and not buyable[j0]
        )
        j = j0
        while (
            j < len(ts)
            and ts[j] - t_signal <= EXEC_WINDOW_S
            and ts[j] < end_bound
            and not buyable[j]
        ):
            j += 1
        if j >= len(ts) or ts[j] - t_signal > EXEC_WINDOW_S or ts[j] >= end_bound:
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
                    "old_rule_bid_side": old_bid_side,
                }
            )
            continue
        p_exec = min(float(price_o[j]), MAX_PRICE)
        if p_exec <= 0.0:
            continue
        shares = ticket / p_exec
        fee = taker_fee(shares, p_exec, m.rate)
        won = int(m.winner_index) == outcome
        pnl = (shares if won else 0.0) - fee - ticket
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
                "lock_h": (closed - float(ts[j])) / 3600.0,
                "old_rule_bid_side": old_bid_side,
            }
        )
    cols = [
        "id",
        "event",
        "family",
        "question",
        "closed_time",
        "end_date",
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
        "old_rule_bid_side",
    ]
    return pd.DataFrame(rows, columns=cols)


def event_bootstrap_ci(
    values: np.ndarray, groups: np.ndarray, B: int = BOOTSTRAP_B, seed: int = 0
) -> tuple[float, float]:
    """95 % interval of the mean under resampling of EVENTS (Amendment 3): a multi-market event is one draw."""
    if len(values) == 0:
        return (float("nan"), float("nan"))
    keys, inv = np.unique(groups.astype(str), return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(keys))
    counts = np.bincount(inv, minlength=len(keys)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(B, len(keys)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def _longest_losing_streak(won: np.ndarray) -> int:
    best = cur = 0
    for w in won:
        cur = 0 if w else cur + 1
        best = max(best, cur)
    return int(best)


def summarize(trades: pd.DataFrame, split: str, B: int = BOOTSTRAP_B) -> dict[str, Any]:
    """PLAN §4 readings for one cell, plus Amendment 3's losses, worst case, events and bid-side share."""
    lo, hi = split_bounds(split)
    days = max(1.0, (hi - lo) / 86400.0)
    filled = trades[~trades["missed"].astype(bool)] if len(trades) else trades
    out: dict[str, Any] = {
        "n": len(filled),
        "missed": int(len(trades) - len(filled)),
        "trades_per_day": len(filled) / days,
        "bid_side_share": float(trades["old_rule_bid_side"].astype(bool).mean())
        if len(trades)
        else None,
    }
    if len(filled) == 0:
        return {
            **out,
            "n_events": 0,
            "losses": 0,
            "win_rate": None,
            "mean_p_exec": None,
            "calibration_gap": None,
            "mean_net": None,
            "ci95": [None, None],
            "worst_case_net": None,
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
    groups = f["event"].fillna(f["id"]).to_numpy()
    ci = event_bootstrap_ci(net, groups, B=B)
    n = len(f)
    losses = int((~won).sum())
    mean_win = float(net[won].mean()) if won.any() else 0.0
    worst_case = (
        (1.0 - 3.0 / n) * mean_win - 3.0 / n
    )  # the rule of three: a 95 % upper bound on an unseen loss rate
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
        "n_events": len(np.unique(groups.astype(str))),
        "losses": losses,
        "win_rate": float(won.mean()),
        "mean_p_exec": float(f["p_exec"].mean()),
        "calibration_gap": float(won.mean() - f["p_exec"].mean()),
        "mean_net": float(net.mean()),
        "ci95": [ci[0], ci[1]],
        "worst_case_net": float(worst_case),
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
    """Outcomes redrawn as Bernoulli(p_exec): mean net return under perfect calibration (no edge, only fees)."""
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
    """PLAN §3 + Amendment 3: n >= min_n, mean > 0, CI lower bound > 0, at least one observed loss, and with fewer
    than five losses the rule-of-three worst case must still be positive."""
    if s["n"] < min_n or s["mean_net"] is None or s["ci95"][0] is None:
        return False
    if not (s["mean_net"] > 0 and s["ci95"][0] > 0):
        return False
    losses = int(s.get("losses") or 0)
    if losses < 1:
        return False
    if losses < 5 and not (
        s.get("worst_case_net") is not None and s["worst_case_net"] > 0
    ):
        return False
    return True


def _ledger_size(doc: Any) -> int:
    if isinstance(doc, list):
        return len(doc)
    if isinstance(doc, dict):
        if isinstance(doc.get("n_trials_total"), int):
            return int(doc["n_trials_total"])
        for key in ("trials", "runs"):
            if isinstance(doc.get(key), list):
                return len(doc[key])
    return 0


def trials_count() -> int:
    n = 0
    for path in (*SIBLING_LEDGERS, LEDGER):
        if path.exists():
            try:
                n += _ledger_size(json.loads(path.read_text()))
            except ValueError:
                continue
    return n


def record_run(entry: dict[str, Any]) -> int:
    """Upsert one trial in research/lab4/trials.json, keyed on (lab, hyp, cell, split, stage) so a re-run replaces
    its own entry; returns the running count across labs 2, 3 and 4."""
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    key = tuple(entry.get(k) for k in ("lab", "hyp", "cell", "split", "stage"))
    ledger = [
        e
        for e in ledger
        if tuple(e.get(k) for k in ("lab", "hyp", "cell", "split", "stage")) != key
    ]
    ledger.append(
        {
            **entry,
            "utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "t": time.time(),
        }
    )
    LEDGER.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")
    return trials_count()

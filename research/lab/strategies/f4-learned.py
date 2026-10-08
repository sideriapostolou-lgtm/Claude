"""F4 - learned entry filter for freshly graduated pump.fun coins.

A harness ``Strategy`` that enters when a model's probability that the trade wins exceeds a
threshold and then exits with a fixed stop / take-profit / time stop:

* **Features** (:func:`feature_matrix`, :data:`FEATURES`): strictly causal OHLCV features at each
  bar CLOSE - returns over 1/5/15/60 bars, drawdown from rolling and post-graduation highs, rebound
  from rolling lows, USD-volume levels and ratios, realized volatility, candle-body stats, worst
  1-bar drop, zero-volume minutes, age since creation and graduation, graduation delay, market cap
  and distance from the graduation-level market cap, plus launch flags fixed at creation.
  Row ``i`` of the matrix depends on bars ``0..i`` only (verified by tests: the matrix of a
  truncated coin equals the prefix of the full matrix).
* **Gate** (:func:`gate_mask`): the bars that can be scored at all - graduated, at most
  ``max_age_min`` after graduation, at least ``min_vol10_usd`` traded over the last 10 bars and a
  market cap above ``min_mcap_sol`` SOL (not sitting at the ~17.6 SOL floor).
* **Label** (built in ``f4_learned_search.py``, never available to the strategy): the net-of-costs
  return of exactly this trade - buy $20 at the open of bar i+1, stop ``sl``, take-profit ``tp``,
  time stop ``hold_min`` - simulated with the harness's pessimistic intrabar rules; y = return > 0.
* **Models**: L2 logistic regression or a shallow, heavily regularized gradient-boosted tree
  ensemble (scikit-learn), trained on TRAIN coins only with coin-grouped, time-blocked folds. The
  scorer averages the fold models, so out-of-fold TRAIN scores and VALIDATION scores come from the
  same kind of model.

Two ways to score a bar, which must give identical decisions (tests check this):

* ``ModelScorer`` - computes the feature row from ``view`` (bars 0..i) and runs the models. This is
  what a live bot would do and what ``audit_lookahead`` exercises.
* ``TableScorer`` - looks up probabilities precomputed per coin with the same causal features
  (fast; used for the parameter search). Only valid together with the prefix test above.
"""

from __future__ import annotations

import functools
import math
import pickle
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

_LAB = Path(__file__).resolve().parents[1]
if str(_LAB) not in sys.path:
    sys.path.insert(0, str(_LAB))

from harness import Buy, Exits, Strategy  # noqa: E402

GRAD_LEVEL_SOL = 411.0  # market cap (SOL) of a fresh SOL-paired graduate: 84.99 SOL / 206.9M tokens x 1e9
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

FEATURES: tuple[str, ...] = (
    # returns
    "r1", "r5", "r15", "r60",
    # drawdown / rebound
    "dd_hi15", "dd_hi60", "dd_hi_grad", "reb_lo15", "reb_lo60",
    # volume
    "lv1", "lv5", "lv60", "lv_grad", "vratio_5_60", "vratio_1_15",
    # volatility
    "rv15", "rv60", "worst_drop15",
    # candle bodies
    "body", "upper_wick", "lower_wick", "body5", "green15",
    # activity
    "zero15", "zero60",
    # time
    "age_min_log", "since_grad_log", "grad_delay_log", "since_high_log",
    # level
    "mcap_log10", "dist_grad_level", "rel_grad_close", "peak_rel_grad",
    # launch flags (fixed at creation)
    "has_twitter", "has_website", "has_telegram", "desc_len_log", "cashback", "token2022",
)
FIDX = {f: k for k, f in enumerate(FEATURES)}


# =========================================================================== causal features


def _lag(a: np.ndarray, k: int) -> np.ndarray:
    """a[i-k], with a[0] for i < k (prefix-stable)."""
    out = np.empty_like(a)
    if k >= len(a):
        out[:] = a[0]
        return out
    out[k:] = a[:-k]
    out[:k] = a[0]
    return out


def _roll(a: np.ndarray, w: int, fn: str, pad: float | None = None) -> np.ndarray:
    """Trailing window statistic over a[i-w+1..i]; the front is padded with ``pad`` (default a[0])."""
    p = a[0] if pad is None else pad
    x = np.concatenate([np.full(w - 1, p, dtype=float), a.astype(float)])
    win = sliding_window_view(x, w)
    if fn == "max":
        return win.max(axis=1)
    if fn == "min":
        return win.min(axis=1)
    if fn == "sum":
        return win.sum(axis=1)
    if fn == "std":
        return win.std(axis=1)
    raise ValueError(fn)


def graduation_index(ts: np.ndarray, dur: np.ndarray, graduated_ts: float) -> int:
    """First bar whose CLOSE is at or after graduation (== harness ``view.graduated``)."""
    idx = np.nonzero(ts + dur >= graduated_ts)[0]
    return int(idx[0]) if len(idx) else len(ts)


def feature_matrix(ts: np.ndarray, o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,  # noqa: E741
                   v: np.ndarray, dur: np.ndarray, created_ts: float, graduated_ts: float,
                   sol_now: np.ndarray, launch: Mapping[str, Any]) -> np.ndarray:
    """(n, len(FEATURES)) matrix; row i uses bars 0..i only (and sol_now[i], launch flags).

    Rows before the graduation bar hold NaN in graduation-relative columns (never scored)."""
    n = len(c)
    ts = np.asarray(ts, dtype=float)
    dur = np.asarray(dur, dtype=float)
    o, h, l, c, v = (np.asarray(a, dtype=float) for a in (o, h, l, c, v))  # noqa: E741
    tiny = 1e-18
    lc = np.log(np.maximum(c, tiny))
    lh = np.log(np.maximum(h, tiny))
    ll = np.log(np.maximum(l, tiny))
    F = np.full((n, len(FEATURES)), np.nan)

    def put(name: str, arr: np.ndarray | float) -> None:
        F[:, FIDX[name]] = arr

    r1 = lc - _lag(lc, 1)
    put("r1", r1)
    put("r5", lc - _lag(lc, 5))
    put("r15", lc - _lag(lc, 15))
    put("r60", lc - _lag(lc, 60))
    put("dd_hi15", lc - _roll(lh, 15, "max"))
    put("dd_hi60", lc - _roll(lh, 60, "max"))
    put("reb_lo15", lc - _roll(ll, 15, "min"))
    put("reb_lo60", lc - _roll(ll, 60, "min"))

    v5 = _roll(v, 5, "sum", 0.0)
    v15 = _roll(v, 15, "sum", 0.0)
    v60 = _roll(v, 60, "sum", 0.0)
    put("lv1", np.log1p(v))
    put("lv5", np.log1p(v5))
    put("lv60", np.log1p(v60))
    put("vratio_5_60", np.log((v5 / 5 + 1.0) / (v60 / 60 + 1.0)))
    put("vratio_1_15", np.log((v + 1.0) / (v15 / 15 + 1.0)))

    r1z = r1.copy()
    r1z[0] = 0.0
    put("rv15", _roll(r1z, 15, "std", 0.0))
    put("rv60", _roll(r1z, 60, "std", 0.0))
    drop = ll - _lag(lc, 1)
    drop[0] = 0.0
    put("worst_drop15", np.minimum(_roll(drop, 15, "min", 0.0), 0.0))

    rng = h - l
    safe = np.where(rng > 0, rng, 1.0)
    body = np.where(rng > 0, (c - o) / safe, 0.0)
    put("body", body)
    put("upper_wick", np.where(rng > 0, (h - np.maximum(o, c)) / safe, 0.0))
    put("lower_wick", np.where(rng > 0, (np.minimum(o, c) - l) / safe, 0.0))
    put("body5", _roll(body, 5, "sum", 0.0) / 5)
    put("green15", _roll((c > o).astype(float), 15, "sum", 0.0) / 15)
    put("zero15", _roll((v <= 0).astype(float), 15, "sum", 0.0) / 15)
    put("zero60", _roll((v <= 0).astype(float), 60, "sum", 0.0) / 60)

    now = ts + dur
    put("age_min_log", np.log1p(np.maximum(now - created_ts, 0.0) / 60))
    put("grad_delay_log", math.log1p(max(graduated_ts - created_ts, 0.0)))
    sol = np.asarray(sol_now, dtype=float)
    mcap = c * 1e9
    put("mcap_log10", np.log10(np.maximum(mcap, 1e-9)))
    put("dist_grad_level", np.log(np.maximum(mcap / sol, tiny) / GRAD_LEVEL_SOL))

    gi = graduation_index(ts, dur, graduated_ts)
    if gi < n:
        idx = np.arange(n)
        put("since_grad_log", np.where(idx >= gi, np.log1p(np.maximum(now - graduated_ts, 0.0) / 60), np.nan))
        hs = np.where(idx >= gi, lh, -np.inf)
        cm = np.maximum.accumulate(hs)
        post = idx >= gi
        last_hi = np.maximum.accumulate(np.where(post & (hs >= cm), idx, -1))
        put("dd_hi_grad", np.where(post, lc - cm, np.nan))
        put("since_high_log", np.where(post, np.log1p(idx - last_hi), np.nan))
        put("rel_grad_close", np.where(post, lc - lc[gi], np.nan))
        put("peak_rel_grad", np.where(post, cm - lc[gi], np.nan))
        vg = np.where(post, v, 0.0)
        put("lv_grad", np.where(post, np.log1p(np.cumsum(vg)), np.nan))

    lf = launch or {}
    put("has_twitter", float(bool(lf.get("has_twitter"))))
    put("has_website", float(bool(lf.get("has_website"))))
    put("has_telegram", float(bool(lf.get("has_telegram"))))
    put("desc_len_log", math.log1p(float(lf.get("description_len") or 0)))
    put("cashback", float(bool(lf.get("is_cashback_enabled"))))
    put("token2022", float(lf.get("token_program") == TOKEN_2022))
    return F


def coin_features(coin: Any, sol: Any) -> np.ndarray:
    """Feature matrix of a harness ``Coin`` (full arrays; row i is causal - see tests)."""
    sol_now = np.array([sol.at(float(t + d)) for t, d in zip(coin.ts, coin.dur)])
    return feature_matrix(coin.ts, coin.o, coin.h, coin.l, coin.c, coin.v, coin.dur, coin.created_ts,
                          coin.graduated_ts, sol_now, coin.launch)


def view_features(view: Any) -> np.ndarray:
    """Feature row at the close of bar i from the view only (bars 0..i, public SOL price now)."""
    n = view.n
    sol_now = np.full(n, view.sol_usd)
    gts = view.graduated_ts
    F = feature_matrix(view.ts, view.o, view.h, view.l, view.c, view.v, view.dur, view.meta["created_ts"],
                       gts if gts is not None else math.inf, sol_now, view.meta.get("launch") or {})
    return F[-1]


# =========================================================================== gate


@dataclass(frozen=True)
class Gate:
    max_age_min: float = 360.0  # minutes since graduation
    min_vol10_usd: float = 1_000.0  # USD volume over the last 10 closed bars
    min_mcap_sol: float = 30.0  # above the ~17.6 SOL dumped floor


def gate_mask(F: np.ndarray, v10: np.ndarray, gate: Gate) -> np.ndarray:
    """Bars that can be scored: graduated (since_grad_log not NaN), young enough, alive, not floored."""
    sg = F[:, FIDX["since_grad_log"]]
    with np.errstate(invalid="ignore"):
        since_min = np.expm1(sg)
        mcap_sol = np.exp(F[:, FIDX["dist_grad_level"]]) * GRAD_LEVEL_SOL
        return (~np.isnan(sg)) & (since_min <= gate.max_age_min) & (v10 >= gate.min_vol10_usd) \
            & (mcap_sol >= gate.min_mcap_sol)


def vol10(v: np.ndarray) -> np.ndarray:
    return _roll(np.asarray(v, dtype=float), 10, "sum", 0.0)


# =========================================================================== scorers


class FoldEnsemble:
    """Average of sklearn classifiers (fold models) over the FEATURES columns given by ``cols``."""

    def __init__(self, models: Sequence[Any], cols: Sequence[int], kind: str, meta: Mapping[str, Any] | None = None):
        self.models = list(models)
        self.cols = list(cols)
        self.kind = kind  # "logit" | "gbt" | "gbt_reg"
        self.meta = dict(meta or {})

    def score(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(X)[:, self.cols]
        if self.kind == "gbt_reg":
            return np.mean([m.predict(X) for m in self.models], axis=0)
        return np.mean([m.predict_proba(X)[:, 1] for m in self.models], axis=0)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(self))

    @staticmethod
    def load(path: Path) -> "FoldEnsemble":
        return pickle.loads(Path(path).read_bytes())


class ModelScorer:
    """Live-style scoring: features from the view, gate, then the model (read-only, shared OK)."""

    def __init__(self, model: FoldEnsemble, gate: Gate) -> None:
        self.model = model
        self.gate = gate

    def __call__(self, i: int, view: Any) -> float | None:
        row = view_features(view)
        v10 = float(np.sum(view.v[-10:]))
        if not gate_mask(row[None, :], np.array([v10]), self.gate)[0]:
            return None
        return float(self.model.score(row[None, :])[0])


class TableScorer:
    """Precomputed per-coin scores (NaN = gate closed). Built from the SAME causal features."""

    def __init__(self, table: Mapping[str, np.ndarray]) -> None:
        self.table = table

    def __call__(self, i: int, view: Any) -> float | None:
        arr = self.table.get(view.meta["mint"])
        if arr is None or i >= len(arr):
            return None
        x = float(arr[i])
        return None if math.isnan(x) else x


# =========================================================================== strategy


@dataclass(frozen=True)
class F4Params:
    threshold: float = 0.5  # enter when score > threshold
    tp: float = 0.30  # take-profit (relative to the fill mid)
    sl: float = 0.20  # stop (relative to the fill mid)
    hold_min: float = 30.0  # time stop
    max_entries: int = 1  # Buy signals per coin
    max_age_min: float = 360.0  # gate (also used as horizon)
    min_vol10_usd: float = 1_000.0
    min_mcap_sol: float = 30.0

    @property
    def gate(self) -> Gate:
        return Gate(self.max_age_min, self.min_vol10_usd, self.min_mcap_sol)


class F4Learned(Strategy):
    """Enter when ``scorer(i, view) > threshold``; fixed stop / take-profit / time stop."""

    name = "f4_learned"

    def __init__(self, params: F4Params, scorer: Any, name: str | None = None) -> None:
        self.p = params
        self.scorer = scorer
        if name:
            self.name = name
        self.horizon_s = (params.max_age_min + 1) * 60.0

    def on_coin_start(self, meta: Mapping[str, Any]) -> None:
        self.attempts = 0  # Buy signals sent for this coin (a signal the portfolio rejects is used up)

    def on_candle(self, i: int, view: Any, position: Any) -> Any:
        if position is not None or self.attempts >= self.p.max_entries or not view.graduated:
            return None
        s = self.scorer(i, view)
        if s is None or not s > self.p.threshold:
            return None
        p = self.p
        self.attempts += 1
        return Buy(exits=Exits(stop_pct=p.sl, take_profit_pct=p.tp, max_hold_s=p.hold_min * 60.0),
                   priority=s, tag=f"p={s:.3f}")


def factory(params: F4Params, scorer: Any, name: str | None = None):
    """Zero-arg factory for the harness runners."""
    return functools.partial(F4Learned, params, scorer, name)


def params_dict(p: F4Params) -> dict:
    return asdict(p)

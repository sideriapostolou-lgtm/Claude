"""Pure statistics of the learning loop (docs/LEARNING.md §5.1). Standard library only, no IO.

Observations are per-(variant, coin) net returns clipped to ``[-1, 1]`` (:func:`clip`).

Betting e-processes with a FIXED grid of bets (:data:`LAMBDAS`, part of ``sim_hash``), mixed with
equal weights; ``logw`` holds one running log-wealth per bet:

* :func:`step_up`     H0: E[x] <= m  (promotion, m = 0):    w += log1p(l / (1 + m) * (x - m))
* :func:`step_down`   H0: E[x] >= m  (futility m = +0.02, drift m = 0): w += log1p(l / (1 - m) * (m - x))
* :func:`step_paired` H0: E[d] <= 0, d = x_A - x_B in [-2, 2]: w += log1p(l / 2 * d)

``log E = logmeanexp(logw)`` is an e-value at every trade: P(sup_t E_t >= 1/alpha) <= alpha (Ville),
so it may be checked after EVERY trade. The product form makes it independent of the ORDER of the
observations. Derived values (display and sizing only; they never grant anything):

* :func:`lower_bound` - always-valid ``LB(alpha) = inf{m in [-1, 1] : E_t(m) < 1/alpha}`` (bisection;
  E_t(m) falls as m rises); callers keep the running maximum (``score(prev_lb=...)``).
* :func:`proof` - ``clip(log E / log threshold, 0, 1)``.
* :func:`eta_trades` - ``max(0, log thr - log E) / (mean^2 / (2 sd^2))``, only for a positive mean.
* :func:`cusum_step` - ``S = max(0, S + (ref - x))`` with ``ref = -1 %`` (decay detection).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

from nightcrawler.learn.gate import CUSUM_REF, FUTILITY_M

__all__ = [
    "LAMBDAS",
    "clip",
    "start",
    "logmeanexp",
    "step_up",
    "step_down",
    "step_paired",
    "log_e_up",
    "log_e_down",
    "lower_bound",
    "proof",
    "eta_trades",
    "cusum_step",
    "score",
]

#: Fixed forever (inside sim_hash): the bets mixed by every e-process.
LAMBDAS: tuple[float, ...] = (0.05, 0.10, 0.20, 0.35, 0.50, 0.70)
_EDGE = 1e-9  # keeps 1 + m and 1 - m away from 0 in the lower-bound search


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def start() -> list[float]:
    """Log-wealth of every bet before the first observation (E = 1)."""
    return [0.0] * len(LAMBDAS)


def logmeanexp(values: Sequence[float]) -> float:
    top = max(values)
    if math.isinf(top):
        return top
    return top + math.log(sum(math.exp(v - top) for v in values) / len(values))


def step_up(logw: Sequence[float], x: float, m: float = 0.0) -> list[float]:
    """One observation of the e-process for H0: E[x] <= m."""
    scale = (x - m) / (1.0 + m)
    return [w + math.log1p(lam * scale) for w, lam in zip(logw, LAMBDAS, strict=True)]


def step_down(logw: Sequence[float], x: float, m: float) -> list[float]:
    """One observation of the e-process for H0: E[x] >= m."""
    scale = (m - x) / (1.0 - m)
    return [w + math.log1p(lam * scale) for w, lam in zip(logw, LAMBDAS, strict=True)]


def step_paired(logw: Sequence[float], d: float) -> list[float]:
    """One paired difference d = x_A - x_B in [-2, 2] for H0: E[d] <= 0."""
    return [w + math.log1p(lam / 2.0 * d) for w, lam in zip(logw, LAMBDAS, strict=True)]


def log_e_up(xs: Iterable[float], m: float = 0.0) -> float:
    """log E of H0: E[x] <= m after all of ``xs`` (0.0 for none)."""
    logw = start()
    for x in xs:
        logw = step_up(logw, x, m)
    return logmeanexp(logw)


def log_e_down(xs: Iterable[float], m: float) -> float:
    """log E of H0: E[x] >= m after all of ``xs`` (0.0 for none)."""
    logw = start()
    for x in xs:
        logw = step_down(logw, x, m)
    return logmeanexp(logw)


def lower_bound(xs: Sequence[float], alpha: float, tol: float = 1e-4) -> float:
    """Always-valid lower confidence bound on the mean of ``xs`` (see the module docstring)."""
    log_thr = math.log(1.0 / alpha)
    lo, hi = -1.0 + _EDGE, 1.0 - _EDGE
    if not xs or log_e_up(xs, lo) < log_thr:
        return -1.0
    if log_e_up(xs, hi) >= log_thr:
        return 1.0
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if log_e_up(xs, mid) >= log_thr:
            lo = mid
        else:
            hi = mid
    return lo


def proof(log_e: float, threshold: float) -> float:
    """Share of the way to the threshold on the log scale, in [0, 1]."""
    return clip(log_e / math.log(threshold), 0.0, 1.0)


def eta_trades(log_e: float, threshold: float, mean: float | None, sd: float | None) -> float | None:
    """Expected trades still needed to reach ``threshold`` at the observed mean/sd (None unless mean > 0)."""
    if mean is None or sd is None or mean <= 0 or sd <= 0:
        return None
    return max(0.0, math.log(threshold) - log_e) / (mean * mean / (2.0 * sd * sd))


def cusum_step(s: float, x: float, ref: float = CUSUM_REF) -> float:
    return max(0.0, s + (ref - x))


def score(xs: Sequence[float], *, threshold: float, alpha: float, prev_lb: float | None = None) -> dict[str, Any]:
    """Scoreboard numbers for one variant's ordered evidence ``xs`` (already clipped)."""
    n = len(xs)
    total = math.fsum(xs)
    total2 = math.fsum(x * x for x in xs)
    mean = total / n if n else None
    sd = math.sqrt(max(0.0, (total2 - n * mean * mean) / (n - 1))) if n > 1 and mean is not None else None
    log_e = log_e_up(xs)
    cusum = 0.0
    for x in xs:
        cusum = cusum_step(cusum, x)
    lb = lower_bound(xs, alpha)
    if prev_lb is not None:
        lb = max(lb, prev_lb)
    return {"n": n, "sum_x": total, "sum_x2": total2, "mean": mean, "sd": sd, "log_e": log_e,
            "log_e_fut": log_e_down(xs, FUTILITY_M), "lb": lb, "cusum": cusum,
            "proof": proof(log_e, threshold), "eta_trades": eta_trades(log_e, threshold, mean, sd)}

"""Post-model probability recalibration (Platt scaling).

The backtest showed the raw model's reliability curve has slope < 1: low
predictions under-shoot reality and high ones over-shoot. A global multiplier
can't fix a slope, so we recalibrate in log-odds space:

    p' = sigmoid(a + b * logit(p))

fitted by Newton-Raphson on trailing settled markets. Walk-forward safe: the
backtest fits on markets settled strictly before the pricing day; live would
fit on the settled quote log the same way.
"""
from __future__ import annotations

import math

MIN_SAMPLES = 500
B_CLAMP = (0.5, 2.0)
A_CLAMP = (-1.5, 1.5)


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class PlattScaler:
    def __init__(self, a: float = 0.0, b: float = 1.0):
        self.a = a
        self.b = b
        self.n_fit = 0

    @property
    def is_identity(self) -> bool:
        return self.a == 0.0 and self.b == 1.0

    def apply(self, p: float) -> float:
        return _sigmoid(self.a + self.b * _logit(p))

    def fit(self, pairs: list[tuple[float, int]], iters: int = 25) -> "PlattScaler":
        """Fit (a, b) on (raw_prob, outcome) pairs. Identity if underpowered."""
        self.n_fit = len(pairs)
        if self.n_fit < MIN_SAMPLES:
            self.a, self.b = 0.0, 1.0
            return self
        zs = [_logit(p) for p, _ in pairs]
        ys = [y for _, y in pairs]
        a, b = 0.0, 1.0
        for _ in range(iters):
            g_a = g_b = 0.0
            h_aa = h_ab = h_bb = 0.0
            for z, y in zip(zs, ys):
                mu = _sigmoid(a + b * z)
                w = mu * (1 - mu)
                r = mu - y
                g_a += r
                g_b += r * z
                h_aa += w
                h_ab += w * z
                h_bb += w * z * z
            det = h_aa * h_bb - h_ab * h_ab
            if det < 1e-9:
                break
            da = (h_bb * g_a - h_ab * g_b) / det
            db = (h_aa * g_b - h_ab * g_a) / det
            a -= da
            b -= db
            if abs(da) < 1e-8 and abs(db) < 1e-8:
                break
        self.a = min(max(a, A_CLAMP[0]), A_CLAMP[1])
        self.b = min(max(b, B_CLAMP[0]), B_CLAMP[1])
        return self

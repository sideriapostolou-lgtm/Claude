"""F1 exploratory event study (TRAIN only): which dip/rebound features relate to forward returns?

Not a strategy and not a backtest - a descriptive scan used to design the parameter grid.
For every post-graduation bar i it computes causal features (bars 0..i only) and the gross
forward mid return from the open of bar i+1 (the harness fill price) to the close h bars later.

    python research/lab/strategies/f1_explore.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from harness import load_coins  # noqa: E402

OUT = Path("/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/lab/f1")


def events(coin, horizons=(15, 30, 60)):
    ts, o, h, l, c, v = coin.ts, coin.o, coin.h, coin.l, coin.c, coin.v
    n = coin.n
    g = int(np.searchsorted(ts, coin.graduated_ts, side="right") - 1)
    g = max(g, 0)
    rows = []
    H, iH, L = -1.0, -1, np.inf
    for i in range(g, n - 1):
        if ts[i] + 60 < coin.graduated_ts:
            continue
        if h[i] > H:
            H, iH, L = float(h[i]), i, np.inf
        elif l[i] < L:
            L = float(l[i])
        if iH < 0 or L == np.inf or i - g < 2:
            continue
        dd = 1 - L / H
        reb = c[i] / L
        lo = max(0, i - 29)
        med = float(np.median(v[lo:i])) if i > lo else 0.0
        mean30 = float(v[lo:i].mean()) if i > lo else 0.0
        vol10 = float(v[max(0, i - 9):i + 1].sum())
        age = (ts[i] + 60 - coin.graduated_ts) / 60
        row = [age, dd, reb, float(c[i] > o[i]), float(c[i] > h[i - 1]), v[i] / (mean30 + 1e-9), vol10,
               c[i] * 1e9, i - iH, float(v[i])]
        e = o[i + 1]
        for hz in horizons:
            j = min(i + hz, n - 1)
            row.append(c[j] / e - 1)
            row.append(l[i + 1:j + 1].min() / e - 1)
            row.append(h[i + 1:j + 1].max() / e - 1)
        rows.append(row)
    return rows


COLS = ["age", "dd", "reb", "green", "brk", "vratio", "vol10", "mcap", "since_high", "v"] + [
    f"{k}{hz}" for hz in (15, 30, 60) for k in ("r", "mae", "mfe")]


def main():
    coins = load_coins(split="train")
    all_rows = []
    for cn in coins:
        for r in events(cn):
            all_rows.append(r)
    X = np.asarray(all_rows)
    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "explore_train.npy", X)
    print(X.shape)
    return X


if __name__ == "__main__":
    main()

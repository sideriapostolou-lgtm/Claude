# X1 val: cross-sectional momentum (weekly top-k with positive own momentum)

- Split `val` ('2025-01-01', '2026-01-01'); written 2026-10-09 12:33:29 UTC; runtime 27.7 s; trials so far 128 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| top5 | -1.31 | -35.5% | -44.3% | 0.31 | 8.0 | +3.4% | -1.21 | -1.41 | -0.94 | 0.78 | -12.7% | [-0.168%, +0.093%]/day | 0.00 |
| top3 | -1.29 | -26.8% | -33.5% | 0.20 | 6.3 | +2.8% | -1.18 | -1.41 | -0.79 | 0.85 | -9.9% | [-0.131%, +0.068%]/day | 0.00 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | -1.27 | -67.2% | -70.2% |
| sol_only | -0.48 | -34.1% | -59.8% |
| btc_only | -0.15 | -6.3% | -32.1% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- top5: {'2025': -0.3548}
- top3: {'2025': -0.2675}

## Decision

- **FAIL_VAL**
- candidate: top3
- twin: ['top5']
- val_sharpe: -1.2913272191472
- note: the judge reads VAL before any TEST look

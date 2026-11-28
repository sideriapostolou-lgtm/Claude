# V1 val: volatility targeting overlay on the TRAIN-best trend signal

- Split `val` ('2025-01-01', '2026-01-01'); written 2026-10-09 12:33:53 UTC; runtime 23.7 s; trials so far 128 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| T2-best|vol40 | -1.00 | -15.0% | -23.0% | 0.17 | 11.9 | +9.7% | -0.40 | -1.59 | -1.52 | 0.15 | +9.4% | [-0.038%, +0.081%]/day | 0.00 |
| T2-best|vol60 | -0.99 | -20.3% | -30.5% | 0.23 | 16.3 | +10.8% | -0.52 | -1.47 | -1.44 | 0.20 | +11.6% | [-0.055%, +0.108%]/day | 0.00 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | -1.27 | -67.2% | -70.2% |
| sol_only | -0.48 | -34.1% | -59.8% |
| btc_only | -0.15 | -6.3% | -32.1% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- T2-best|vol40: {'2025': -0.1496}
- T2-best|vol60: {'2025': -0.2026}

## Decision

- **FAIL_VAL**
- candidate: T2-best|vol60
- twin: ['T2-best|vol40']
- val_sharpe: -0.993737701285341
- note: the judge reads VAL before any TEST look

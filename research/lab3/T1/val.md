# T1 val: time-series momentum (long/flat)

- Split `val` ('2025-01-01', '2026-01-01'); written 2026-10-09 12:32:35 UTC; runtime 26.1 s; trials so far 128 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| L30 | -0.88 | -29.0% | -45.2% | 0.34 | 29.9 | +13.2% | -0.54 | -1.21 | -1.48 | 0.07 | +24.8% | [-0.068%, +0.191%]/day | 0.00 |
| L60 | -0.99 | -32.6% | -38.4% | 0.37 | 18.5 | +8.1% | -0.79 | -1.20 | -1.28 | 0.28 | +12.4% | [-0.116%, +0.152%]/day | 0.00 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | -1.27 | -67.2% | -70.2% |
| sol_only | -0.48 | -34.1% | -59.8% |
| btc_only | -0.15 | -6.3% | -32.1% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- L30: {'2025': -0.2901}
- L60: {'2025': -0.3258}

## Decision

- **FAIL_VAL**
- candidate: L30
- twin: ['L60']
- val_sharpe: -0.8763314599632033
- note: the judge reads VAL before any TEST look

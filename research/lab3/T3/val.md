# T3 val: trend following on the majors only (BTC, ETH, SOL)

- Split `val` ('2025-01-01', '2026-01-01'); written 2026-10-09 12:36:44 UTC; runtime 17.8 s; trials so far 133 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| sma50 | 0.67 | +25.9% | -19.3% | 0.43 | 18.0 | +5.6% | 0.83 | 0.51 | -0.31 | 0.03 | +33.5% | [-0.017%, +0.224%]/day | 0.02 |
| tsmom30 | 0.44 | +16.2% | -20.2% | 0.42 | 26.0 | +8.1% | 0.67 | 0.20 | -0.39 | 0.07 | +28.6% | [-0.029%, +0.218%]/day | 0.01 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | -0.24 | -14.2% | -48.5% |
| sol_only | -0.48 | -34.1% | -59.8% |
| btc_only | -0.15 | -6.3% | -32.1% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- sma50: {'2025': 0.2589}
- tsmom30: {'2025': 0.1618}

## Decision

- **SELECTED**
- candidate: sma50
- twin: ['tsmom30']
- val_sharpe: 0.6714329217502699
- note: the judge reads VAL before any TEST look

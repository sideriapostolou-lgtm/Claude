# T2 val: moving-average / Donchian breakout (long/flat)

- Split `val` ('2025-01-01', '2026-01-01'); written 2026-10-09 12:33:01 UTC; runtime 25.6 s; trials so far 128 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| sma50 | -1.21 | -35.0% | -44.2% | 0.33 | 23.4 | +10.3% | -0.92 | -1.50 | -1.40 | 0.37 | +9.1% | [-0.107%, +0.141%]/day | 0.00 |
| donchian55 | -0.82 | -21.2% | -31.3% | 0.24 | 5.6 | +2.4% | -0.73 | -0.90 | -1.06 | 0.28 | +7.4% | [-0.066%, +0.097%]/day | 0.00 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | -1.27 | -67.2% | -70.2% |
| sol_only | -0.48 | -34.1% | -59.8% |
| btc_only | -0.15 | -6.3% | -32.1% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- sma50: {'2025': -0.35}
- donchian55: {'2025': -0.2124}

## Decision

- **FAIL_VAL**
- candidate: donchian55
- twin: ['sma50']
- val_sharpe: -0.8155872981530468
- note: the judge reads VAL before any TEST look

# T3 test: trend following on the majors only (BTC, ETH, SOL)

- Split `test` ('2026-01-01', None); written 2026-10-09 12:37:22 UTC; runtime 8.9 s; trials so far 133 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| sma50 | 0.22 | +7.5% | -27.7% | 0.54 | 22.4 | +7.0% | 0.42 | 0.01 | -0.43 | 0.17 | +21.9% | [-0.096%, +0.249%]/day | 0.01 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | -0.24 | -12.2% | -49.8% |
| sol_only | -0.24 | -13.9% | -57.6% |
| btc_only | -0.14 | -6.3% | -39.6% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- sma50: {'2026': 0.0571}

## Decision

- **FAIL**
- criteria: {'sharpe_gt_0': True, 'placebo_excess_ci95_lo_gt_0': False, 'mdd_better_than_buy_hold': True}
- note: a PASS never funds real money by itself (PLAN 5)

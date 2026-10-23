# X1 train: cross-sectional momentum (weekly top-k with positive own momentum)

- Split `train` ('2015-01-01', '2025-01-01'); written 2026-10-09 12:30:11 UTC; runtime 30.0 s; trials so far 122 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| top3 | 1.02 | +81.4% | -63.3% | 0.55 | 5.2 | +1.6% | 1.05 | 0.99 | 0.65 | 0.07 | +34.6% | [+0.023%, +0.168%]/day | 0.70 |
| top5 | 1.05 | +85.3% | -63.3% | 0.56 | 5.0 | +1.6% | 1.08 | 1.02 | 0.67 | 0.04 | +32.6% | [+0.018%, +0.161%]/day | 0.72 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | 0.81 | +87.8% | -88.0% |
| sol_only | 0.02 | +1.1% | -94.3% |
| btc_only | 0.85 | +78.7% | -83.8% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- top3: {'2015': 0.0, '2016': 1.155, '2017': 31.0384, '2018': -0.4154, '2019': 0.9168, '2020': 0.7107, '2021': 1.3208, '2022': -0.4116, '2023': 0.7232, '2024': -0.0995}
- top5: {'2015': 0.0, '2016': 1.155, '2017': 31.0384, '2018': -0.4154, '2019': 0.9168, '2020': 0.7107, '2021': 1.3208, '2022': -0.4116, '2023': 0.6565, '2024': 0.1404}

## Decision

- **SHORTLISTED**
- top3: Sharpe 1.02, CAGR +81.4%, DD -63.3%, qualifies True []
- top5: Sharpe 1.05, CAGR +85.3%, DD -63.3%, qualifies True []
- shortlist_keys: ['top5', 'top3']

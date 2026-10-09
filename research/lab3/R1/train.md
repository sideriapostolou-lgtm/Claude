# R1 train: short-term mean reversion (5-day low entry)

- Split `train` ('2015-01-01', '2025-01-01'); written 2026-10-09 12:30:38 UTC; runtime 26.5 s; trials so far 124 (lab 2 + lab 3).

| config | Sharpe | CAGR | max DD | exposure | turnover/yr | cost/yr | gross Sharpe | stress x2 | placebo Sharpe | p | excess/yr vs placebo | CI95 | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| trend200 | -0.21 | -6.2% | -56.6% | 0.15 | 34.3 | +10.3% | 0.13 | -0.55 | -0.22 | 0.51 | +0.6% | [-0.033%, +0.037%]/day | 0.00 |
| no-filter | -0.37 | -15.3% | -84.8% | 0.27 | 60.6 | +18.4% | 0.04 | -0.77 | -0.18 | 0.76 | -6.3% | [-0.062%, +0.028%]/day | 0.00 |

## Benchmarks (same split, same costs)

| benchmark | Sharpe | CAGR | max DD |
|---|---:|---:|---:|
| buy_hold_ew | 0.81 | +87.8% | -88.0% |
| sol_only | 0.02 | +1.1% | -94.3% |
| btc_only | 0.85 | +78.7% | -83.8% |
| cash | 0.00 | +0.0% | +0.0% |

## By year

- trend200: {'2015': 0.0, '2016': 0.0241, '2017': 0.0525, '2018': -0.2999, '2019': -0.0069, '2020': 0.1665, '2021': 0.0584, '2022': -0.1917, '2023': 0.0008, '2024': -0.2683}
- no-filter: {'2015': 0.0, '2016': 0.0241, '2017': 0.0525, '2018': -0.6009, '2019': 0.0138, '2020': 0.0593, '2021': 0.2531, '2022': -0.5207, '2023': 0.0909, '2024': -0.3126}

## Decision

- **NO_CONFIG**
- trend200: Sharpe -0.21, CAGR -6.2%, DD -56.6%, qualifies False ['sharpe -0.21 <= 0.5', 'sharpe <= buy-and-hold', 'excess vs exposure-matched placebo CI95 not above 0']
- no-filter: Sharpe -0.37, CAGR -15.3%, DD -84.8%, qualifies False ['sharpe -0.37 <= 0.5', 'sharpe <= buy-and-hold', 'excess vs exposure-matched placebo CI95 not above 0']
- shortlist_keys: []

# Z3 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:03:00 UTC; runtime 58.1 s; PREREG sha256 `6b228b67cb91`; trials in the ledger: 2575.
- **Overall Z3 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Event counts (no outcomes)

- Coins 450; decision minutes at ages 7-120 min: 50864.

| condition | coins | bars |
|---|---:|---:|
| crash | 252 | 363 |
| single | 3 | 3 |
| confirm | 1 | 1 |
| state | 403 | 35261 |
| crash_before_age_min | 106 | 128 |
| stampede (crash failing the single-seller bound) | | 360 |

- Single-seller crash depth (bars): {'d70': 1, 'd80': 1, 'd90': 1}.
- Sellers in the crash minute: single-seller median 1.00 (IQR 1.00-1.50, n 3); stampede median 686.50 (IQR 66.75-1555.50, n 360).
- Signal coins per day: 5.8.
- At each coin's first `now` signal (decision-time state, no later price):
  - crash depth median 87% (IQR 80%-91%, n 3); pricing reserve X after the crash median 17.8 SOL (IQR 17.8 SOL-19.2 SOL, n 3); market cap median $2,074 (IQR $2,065-$2,409, n 3);
  - fee tier (bps, one side): {'125': 3}; $20 round trip median 5.13% (IQR 5.02%-5.13%, n 3); at costs × 1.5 median 7.59% (IQR 7.42%-7.59%, n 3).

## Configs

| config | trades | coins | depth tags | entry age (min) | placebo trades | controls | horizon exits | entries/day |
|---|---:|---:|---|---|---:|---|---:|---:|
| now|t5 | 3 | 3 | {'d70': 1, 'd90': 1, 'd80': 1} | {'7-15': 2, '15-30': 0, '30-60': 0, '60-121': 1} | 57 | {'unmatched': 60} | 0 | 5.8 |
| now|t15 | 3 | 3 | {'d70': 1, 'd90': 1, 'd80': 1} | {'7-15': 2, '15-30': 0, '30-60': 0, '60-121': 1} | 57 | {'unmatched': 60} | 0 | 5.8 |
| now|t60 | 3 | 3 | {'d70': 1, 'd90': 1, 'd80': 1} | {'7-15': 2, '15-30': 0, '30-60': 0, '60-121': 1} | 57 | {'unmatched': 60} | 0 | 5.8 |
| confirm|t5 | 1 | 1 | {'d90': 1} | {'7-15': 1, '15-30': 0, '30-60': 0, '60-121': 0} | 15 | {'unmatched': 20} | 0 | 1.9 |
| confirm|t15 | 1 | 1 | {'d90': 1} | {'7-15': 1, '15-30': 0, '30-60': 0, '60-121': 0} | 15 | {'unmatched': 20} | 0 | 1.9 |
| confirm|t60 | 1 | 1 | {'d90': 1} | {'7-15': 1, '15-30': 0, '30-60': 0, '60-121': 0} | 15 | {'unmatched': 20} | 0 | 1.9 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden

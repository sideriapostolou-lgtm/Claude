# Z1 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 02:40:21 UTC; runtime 26.1 s; PREREG sha256 `b36f1fc1afea`; trials in the ledger: 2575.
- **Overall Z1 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Event counts (no returns)

- Coins 450 (strata {'instant': 277, 'slow': 173}); decision minutes at ages 30-120: 40514.

| K | condition | coins | coin-minutes |
|---|---|---:|---:|
| K10 | alive | 142 | 8391 |
| K10 | active | 166 | 6479 |
| K10 | decline | 420 | 27473 |
| K10 | share_falls | 218 | 5465 |
| K10 | holds | 450 | 29341 |
| K10 | no_dip | 450 | 36503 |
| K10 | fires | 42 | 113 |
| K10 | alive_and_fires | 31 | 82 |
| K20 | alive | 142 | 8391 |
| K20 | active | 261 | 8216 |
| K20 | decline | 417 | 25967 |
| K20 | share_falls | 256 | 6168 |
| K20 | holds | 440 | 25318 |
| K20 | no_dip | 450 | 36503 |
| K20 | fires | 47 | 128 |
| K20 | alive_and_fires | 30 | 81 |

## Configs

| config | trades | coins | strata | entry age (min) | placebo trades | controls | horizon exits | entries/day |
|---|---:|---:|---|---|---:|---|---:|---:|
| K10|t30 | 31 | 31 | {'slow': 27, 'instant': 4} | {'30-45': 8, '45-60': 7, '60-90': 10, '90-121': 6} | 532 | {'price_matched': 234, 'unmatched': 620} | 0 | 59.6 |
| K10|t60 | 31 | 31 | {'slow': 27, 'instant': 4} | {'30-45': 8, '45-60': 7, '60-90': 10, '90-121': 6} | 532 | {'price_matched': 234, 'unmatched': 620} | 0 | 59.6 |
| K10|sret60 | 31 | 31 | {'slow': 27, 'instant': 4} | {'30-45': 8, '45-60': 7, '60-90': 10, '90-121': 6} | 532 | {'price_matched': 234, 'unmatched': 620} | 0 | 59.6 |
| K20|t30 | 30 | 30 | {'slow': 25, 'instant': 5} | {'30-45': 8, '45-60': 3, '60-90': 12, '90-121': 7} | 528 | {'price_matched': 230, 'unmatched': 600} | 0 | 57.7 |
| K20|t60 | 30 | 30 | {'slow': 25, 'instant': 5} | {'30-45': 8, '45-60': 3, '60-90': 12, '90-121': 7} | 528 | {'price_matched': 230, 'unmatched': 600} | 0 | 57.7 |
| K20|sret60 | 30 | 30 | {'slow': 25, 'instant': 5} | {'30-45': 8, '45-60': 3, '60-90': 12, '90-121': 7} | 528 | {'price_matched': 230, 'unmatched': 600} | 0 | 57.7 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden

# Y3 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:03:03 UTC; runtime 70.0 s; PREREG sha256 `99013ccd2ac8`; trials in the ledger: 2575.
- **Overall Y3 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Event counts (no returns)

- Coins 450 (strata {'instant': 277, 'slow': 173}); decision minutes at ages 70-130: 27014; coins ELIGIBLE (mcap ≥ $6k) at some such decision: 102.

| box | condition | coins | coin-minutes |
|---|---|---:|---:|
| N10|th0.06 | in_window | 450 | 26400 |
| N10|th0.06 | compressed | 76 | 2298 |
| N10|th0.06 | breakout | 58 | 181 |
| N10|th0.06 | broad | 32 | 79 |
| N10|th0.06 | fires_chart | 11 | 13 |
| N10|th0.06 | fires_broad | 0 | 0 |
| N10|th0.06 | eligible_chart | 8 | 10 |
| N10|th0.06 | eligible_broad | 0 | 0 |
| N10|th0.12 | in_window | 450 | 26400 |
| N10|th0.12 | compressed | 87 | 2615 |
| N10|th0.12 | breakout | 58 | 181 |
| N10|th0.12 | broad | 32 | 79 |
| N10|th0.12 | fires_chart | 17 | 24 |
| N10|th0.12 | fires_broad | 1 | 1 |
| N10|th0.12 | eligible_chart | 14 | 19 |
| N10|th0.12 | eligible_broad | 1 | 1 |
| N20|th0.06 | in_window | 450 | 21900 |
| N20|th0.06 | compressed | 46 | 1645 |
| N20|th0.06 | breakout | 39 | 84 |
| N20|th0.06 | broad | 24 | 50 |
| N20|th0.06 | fires_chart | 1 | 1 |
| N20|th0.06 | fires_broad | 0 | 0 |
| N20|th0.06 | eligible_chart | 1 | 1 |
| N20|th0.06 | eligible_broad | 0 | 0 |
| N20|th0.12 | in_window | 450 | 21900 |
| N20|th0.12 | compressed | 60 | 1771 |
| N20|th0.12 | breakout | 39 | 84 |
| N20|th0.12 | broad | 24 | 50 |
| N20|th0.12 | fires_chart | 7 | 8 |
| N20|th0.12 | fires_broad | 1 | 1 |
| N20|th0.12 | eligible_chart | 6 | 7 |
| N20|th0.12 | eligible_broad | 1 | 1 |

## Configs

| config | trades | coins | strata | entry age (min) | placebo trades | controls | horizon exits | entries/day |
|---|---:|---:|---|---|---:|---|---:|---:|
| N10|th0.06|broad | 0 | 0 | {} | {'70-90': 0, '90-110': 0, '110-131': 0} | 0 | {} | 0 | 0.0 |
| N10|th0.06|chart | 8 | 8 | {'slow': 7, 'instant': 1} | {'70-90': 4, '90-110': 2, '110-131': 2} | 152 | {'compressed': 21, 'unmatched': 160} | 0 | 15.4 |
| N10|th0.12|broad | 1 | 1 | {'slow': 1} | {'70-90': 0, '90-110': 1, '110-131': 0} | 20 | {'compressed': 3, 'unmatched': 20} | 0 | 1.9 |
| N10|th0.12|chart | 14 | 14 | {'slow': 12, 'instant': 2} | {'70-90': 6, '90-110': 4, '110-131': 4} | 265 | {'compressed': 57, 'unmatched': 280} | 0 | 26.9 |
| N20|th0.06|broad | 0 | 0 | {} | {'70-90': 0, '90-110': 0, '110-131': 0} | 0 | {} | 0 | 0.0 |
| N20|th0.06|chart | 1 | 1 | {'slow': 1} | {'70-90': 0, '90-110': 1, '110-131': 0} | 20 | {'compressed': 0, 'unmatched': 20} | 0 | 1.9 |
| N20|th0.12|broad | 1 | 1 | {'slow': 1} | {'70-90': 0, '90-110': 1, '110-131': 0} | 20 | {'compressed': 0, 'unmatched': 20} | 0 | 1.9 |
| N20|th0.12|chart | 6 | 6 | {'slow': 6} | {'70-90': 2, '90-110': 3, '110-131': 1} | 111 | {'compressed': 2, 'unmatched': 120} | 0 | 11.5 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden

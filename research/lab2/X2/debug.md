# X2 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days; reference sizes (alive coins at their checkpoint): {'breadth@30': 137, 'breadth@60': 102, 'pressure@30': 137, 'pressure@60': 102}.
- **Written:** 2026-10-09 02:42:57 UTC; runtime 7.5 s; PREREG sha256 `05c364e47993`; trials in the ledger: 2575.
- **Overall X2 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and bin means are hidden, and no parameter was chosen here.**

## Dose-response gate (PREREG 8)

- Decision: **HIDDEN (debug split: no outcome statistics)**; passing checkpoints: [].

| checkpoint | obs | coins per bin [0-.5, .5-.8, .8-.9, .9-1] | bin means | top − all | inversions | decision | pressure-rank bin means (diagnostic) |
|---|---:|---|---|---:|---:|---|---|
| 30 min | 60 | [25, 18, 9, 8] | hidden | n/a | n/a | UNDERPOWERED | hidden |
| 60 min | 30 | [15, 9, 4, 2] | hidden | n/a | n/a | UNDERPOWERED | hidden |

## Event counts (features only, no returns)

| checkpoint | coins with a window | alive | alive & net flow > 0 | warm-up skips (< 30 refs) | top-decile entries | entries by class | n_ref p10/p50/p90 | breadth of alive p10/p50/p90/max | Spearman(pressure, 10-min return) |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| 30 min | 450 | 137 | 96 | 36 | 8 | {'OTHER': 7, 'FACTORY': 1} | 17.5/32.0/43.5 | 2.2/16.0/62.2/227.9 | 0.961 |
| 60 min | 450 | 102 | 73 | 43 | 2 | {'FACTORY': 1, 'OTHER': 1} | 16.0/25.0/36.0 | 2.0/7.7/33.5/132.7 | 0.980 |

## Configs

| config | trades | coins | classes | placebo trades | horizon exits | entries/day |
|---|---:|---:|---|---:|---:|---:|
| c30|h30|time | 8 | 8 | {'OTHER': 7, 'FACTORY': 1} | 160 | 0 | 15.4 |
| c30|h30|time+fade | 8 | 8 | {'OTHER': 7, 'FACTORY': 1} | 160 | 0 | 15.4 |
| c30|h60|time | 8 | 8 | {'OTHER': 7, 'FACTORY': 1} | 160 | 0 | 15.4 |
| c30|h60|time+fade | 8 | 8 | {'OTHER': 7, 'FACTORY': 1} | 160 | 0 | 15.4 |
| c60|h30|time | 2 | 2 | {'FACTORY': 1, 'OTHER': 1} | 40 | 0 | 3.8 |
| c60|h30|time+fade | 2 | 2 | {'FACTORY': 1, 'OTHER': 1} | 40 | 0 | 3.8 |
| c60|h60|time | 2 | 2 | {'FACTORY': 1, 'OTHER': 1} | 40 | 0 | 3.8 |
| c60|h60|time+fade | 2 | 2 | {'FACTORY': 1, 'OTHER': 1} | 40 | 0 | 3.8 |

## Decision

- **DEBUG**.
- mechanics only; returns hidden

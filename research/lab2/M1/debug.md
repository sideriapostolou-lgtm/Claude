# M1 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days; allowed-class coins {'OTHER': 233, 'OPERATOR': 34} in 32 operator clusters (OPERATOR coins: 1 clusters).
- **Written:** 2026-10-09 00:28:06 UTC; runtime 72.7 s; PREREG sha256 `4ed7d99edcf1`; trials in the ledger: 2575.
- **Overall M1 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Model check (PLAN 8 stop rule 5)

- Observations: 131 from 24 coins in 1 operator clusters (need ≥ 100 and ≥ 30 coins); by class: {'OPERATOR': 131}.
- Decision: **HIDDEN (debug split: no outcome statistics)**.

## Event counts (no returns)

- Classes at age 31 min: {'FACTORY': 183, 'OTHER': 233, 'OPERATOR': 34}.
- Coins where MECH-bar fires at any age in [30, 120] min: 26; with bid alive and mech_age ≥ 10: 25; meeting every entry condition: {'m1': 24, 'm2': 20}.

## Configs

| config | trades | coins | classes | exit reasons | placebo trades | horizon exits | entries/day |
|---|---:|---:|---|---|---:|---:|---:|
| m1|rhythm | 24 | 24 | {'OPERATOR': 24} | {'horizon': 20, 'stop': 4} | 480 | 20 | 46.1 |
| m1|rhythm+prec | 24 | 24 | {'OPERATOR': 24} | {'horizon': 20, 'stop': 4} | 480 | 20 | 46.1 |
| m2|rhythm | 20 | 20 | {'OPERATOR': 20} | {'horizon': 16, 'stop': 4} | 400 | 16 | 38.4 |
| m2|rhythm+prec | 20 | 20 | {'OPERATOR': 20} | {'horizon': 16, 'stop': 4} | 400 | 16 | 38.4 |

## Decision

- **DEBUG**.
- mechanics only; returns hidden

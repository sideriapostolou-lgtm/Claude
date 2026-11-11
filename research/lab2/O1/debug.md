# O1 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 05:26:59 UTC; runtime 7.2 s; PREREG sha256 `2dd0e80d7419`; trials in the ledger: 2575.
- **Overall O1 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and placebo outcomes are hidden, and no parameter was chosen here.**

## Event counts (no returns)

- Coins: 450; G1 class at g + 140 s: {'FACTORY': 183, 'ORGANIC': 193, 'COMPLETED': 19, 'UNRESOLVED': 21, 'OPERATOR': 34}.

| timing | alive at the decision | alive and OPERATOR (entered) | speed |
|---|---:|---:|---|
| t30 | 138 | 30 | {'instant': 30} |
| t60 | 102 | 30 | {'instant': 30} |
| r0 | 94 | 29 | {'instant': 29} |

## Configs

| config | trades | coins | strata | placebo trades | horizon exits | entries/day |
|---|---:|---:|---|---:|---:|---:|
| t30|r0exit | 30 | 30 | {'instant': 30} | 600 | 0 | 57.7 |
| t30|tight | 30 | 30 | {'instant': 30} | 600 | 0 | 57.7 |
| t60|r0exit | 30 | 30 | {'instant': 30} | 600 | 0 | 57.7 |
| t60|tight | 30 | 30 | {'instant': 30} | 600 | 0 | 57.7 |
| r0|r0exit | 29 | 29 | {'instant': 29} | 580 | 0 | 55.7 |
| r0|tight | 29 | 29 | {'instant': 29} | 580 | 0 | 55.7 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden

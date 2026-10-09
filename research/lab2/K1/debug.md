# K1 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 07:17:52 UTC; runtime 5.2 s; PREREG sha256 `dfa4e0703202`; trials in the ledger: 2575.
- **Overall K1 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and placebo outcomes are hidden, and no parameter was chosen here.**

## Event counts (no returns)

- Coins: 450; alive at the decision time: 137; deliberation: {'coins': 450, 'alive_at_decision': 137, 'decided': 411, 'undecided': 0, 'new_calls': 411, 'spent_usd': 0.5425}.

| config | decisions cached | buys |
|---|---:|---:|
| panel | 137 | 30 |
| solo-sonnet | 137 | 30 |
| solo-haiku | 137 | 30 |

## Configs

| config | trades | coins | strata | placebo trades | horizon exits | entries/day |
|---|---:|---:|---|---:|---:|---:|
| panel | 30 | 30 | {'OPERATOR': 30} | 600 | 0 | 57.7 |
| solo-sonnet | 30 | 30 | {'OPERATOR': 30} | 600 | 0 | 57.7 |
| solo-haiku | 30 | 30 | {'OPERATOR': 30} | 600 | 0 | 57.7 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden

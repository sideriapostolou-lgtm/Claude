# Q10 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 10:59:32 UTC; runtime 29.3 s; PREREG sha256 `dbcfe323c075`; trials in the ledger: 2575.
- **Overall Q10 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and placebo outcomes are hidden, and no parameter was chosen here.**

## Event counts (no returns)

- Coins: 450; alive at g+10 min: 8; of which mcap >= 420 SOL: 7; |R15| <= 20 %: 0; V15 / x_real >= M: {'6': 2, '3': 2}.

## Configs

| config | trades | coins | strata | placebo trades | horizon exits | entries/day |
|---|---:|---:|---|---:|---:|---:|
| M6|D0.7 | 50 | 50 | {'lp': 50} | 1000 | 0 | 96.1 |
| M6|D0.5 | 50 | 50 | {'lp': 50} | 1000 | 0 | 96.1 |
| M6|deadline | 50 | 50 | {'lp': 50} | 1000 | 0 | 96.1 |
| M3|D0.7 | 58 | 58 | {'lp': 58} | 1160 | 0 | 111.5 |
| M3|D0.5 | 58 | 58 | {'lp': 58} | 1160 | 0 | 111.5 |
| M3|deadline | 58 | 58 | {'lp': 58} | 1160 | 0 | 111.5 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden

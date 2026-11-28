# X1 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days; registry history: ['final_train'].
- **Registry (counts):** 450 history coins, 145 eligible (145 with a resolved base trade); 552 early-holder wallets, 613 entries; wallets with ≥ 3 / ≥ 6 entries: 10 / 1; most entries for one wallet: 6.
- **Written:** 2026-10-09 04:25:05 UTC; runtime 4.5 s; PREREG sha256 `e86be4529995`; trials in the ledger: 2575.
- **Overall X1 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, labels, skills and the gate statistic are hidden and no parameter was chosen here.**

## Persistence gate (PREREG 8)

- Eligible coins: 145; observations (≥ 1 early holder known at n ≥ 3): 5 (need ≥ 200); holder known at n ≥ 3 / unknown: 5 / 140 (outcome-free split only); warm-up observations 5.
- Decision: **HIDDEN (debug split: no outcome statistics)**.

## Event counts at the decision (no returns)

- Classes: {'FACTORY': 183, 'OTHER': 233, 'OPERATOR': 34}; eligible 145; with ≥ 1 early holder 136 (holders per eligible coin 4.227586206896552); with a known holder: {'n3': 5, 'n6': 0}.

## Configs

**Every count in this table is label-dependent** (review X1-DEBUG-LABELS): a coin is a signal, or a control draw, only when earlier coins' resolved labels made one of its holders reputable (or not), so these counts carry the sign of earlier outcomes. Mechanics only; no parameter is chosen from them.

| config | trades | coins | lead wallets | warm-up trades | placebo trades | control trades | horizon exits | entries/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| th0|n3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 |
| th0|n6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 |
| th0.1|n3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 |
| th0.1|n6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 |

## Decision

- **DEBUG**.
- mechanics only; returns hidden

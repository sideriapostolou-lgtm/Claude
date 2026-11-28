# X4 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 04:44:49 UTC; runtime 19.5 s; PREREG sha256 `88edb8ed8df8`; trials in the ledger: 2585.
- **Overall X4 status:** UNDERPOWERED (too few floor signals for the separation gate on TRAIN).

## Separation gate (PREREG 9)

- AT_FLOOR observations: 28596 from 1881 coins; with no signal: 28593 (need ≥ 30 signal observations from ≥ 15 coins).
- Decision: **UNDERPOWERED**.

- No-signal revival rate (2× within 60 min): +0.0%; 1.5×: +0.1%.

| signal | obs | coins | revive 2× | diff vs none | 90% CI (coin) | revive 1.5× | passes |
|---|---:|---:|---:|---:|---|---:|---|
| BREADTH | 3 | 3 | +0.0% | -0.0% | [-0.0, +0.0] | +0.0% | False |
| FLOW | 2 | 2 | +0.0% | -0.0% | [-0.0, +0.0] | +0.0% | False |
| BOTH | 2 | 2 | +0.0% | -0.0% | [-0.0, +0.0] | +0.0% | False |

## Decision

- **UNDERPOWERED_SEP**.
- Shortlist written: False (rank order None).
- PREREG 9: the separation gate precedes any P&L; the grid was not run

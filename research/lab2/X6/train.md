# X6 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 04:45:11 UTC; runtime 15.8 s; PREREG sha256 `6f28eb52bb60`; trials in the ledger: 2586.
- **Overall X6 status:** KILLED (takeover does not separate from flow-dies: PREREG 7).

## Separation gate (PREREG 7)

- Observations: 1792 from 965 coins (need ≥ 30 TAKEOVER and ≥ 30 DIES coins per K).
- Decision: **KILL**.

| K | TAKEOVER n | DIES n | mean TAKEOVER | mean DIES | diff | 90% CI | median TAKEOVER | median DIES | passes |
|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| 5 | 92 | 391 | -30.1% | -21.4% | -8.7% | [-27.0, +11.6] | -69.5% | -42.0% | False |
| 10 | 85 | 455 | -20.5% | -24.0% | +3.5% | [-11.1, +18.5] | -46.5% | -38.5% | False |

## Decision

- **KILLED_SEP**.
- Shortlist written: False (rank order None).
- PREREG 7: the separation gate precedes any P&L; the grid was not run

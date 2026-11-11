# M1 train (PROVISIONAL: partial data)

- **Split:** `train`; usable coins: 144; span: 0.13 days; allowed-class coins {'OTHER': 94, 'OPERATOR': 9} in 17 operator clusters (OPERATOR coins: 2 clusters).
- **Written:** 2026-10-09 00:31:01 UTC; runtime 1.4 s; PREREG sha256 `ab926cd86b3a`; trials in the ledger: 2576.
- **Overall M1 status:** PENDING (no official TRAIN run).

## Model check (PLAN 8 stop rule 5)

- Observations: 18 from 4 coins in 2 operator clusters (need ≥ 100 and ≥ 30 coins); by class: {'OPERATOR': 18}.
- Decision: **UNDERPOWERED**.
- OLS realized60 = +0.0530 + -0.325 × drift_pred60; R² = 0.1431 (need slope ≥ 0.5, R² ≥ 0.05); slope 95% CI by coin [-0.4632558616535648, -0.0760570023385508].

## Decision

- **UNDERPOWERED_MODEL_CHECK**.
- Shortlist written: False.
- PLAN 4.5: the model check precedes any P&L; the grid was not run

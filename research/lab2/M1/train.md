# M1 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days; allowed-class coins {'OTHER': 2240, 'OPERATOR': 287} in 151 operator clusters (OPERATOR coins: 2 clusters).
- **Written:** 2026-10-09 04:43:41 UTC; runtime 17.3 s; PREREG sha256 `82f216607166`; trials in the ledger: 2582.
- **Overall M1 status:** KILLED (model check failed: PLAN 8 stop rule 5).

## Model check (PLAN 8 stop rule 5)

- Observations: 874 from 173 coins in 3 operator clusters (need ≥ 100 and ≥ 30 coins); by class: {'OPERATOR': 868, 'OTHER': 6}.
- Decision: **KILL**.
- OLS realized60 = +0.0099 + -0.023 × drift_pred60; R² = 0.0105 (need slope ≥ 0.5, R² ≥ 0.05); slope 95% CI by coin [-0.05603832852889084, 0.7800905863136136].

## Decision

- **KILLED_MODEL_CHECK**.
- Shortlist written: False.
- PLAN 4.5: the model check precedes any P&L; the grid was not run

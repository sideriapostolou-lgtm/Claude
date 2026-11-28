# X1 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days; registry history: ['train'].
- **Registry (counts):** 3863 history coins, 1492 eligible (1492 with a resolved base trade); 4658 early-holder wallets, 6275 entries; wallets with ≥ 3 / ≥ 6 entries: 322 / 65; most entries for one wallet: 42.
- **Written:** 2026-10-09 04:44:16 UTC; runtime 16.1 s; PREREG sha256 `e86be4529995`; trials in the ledger: 2583.
- **Overall X1 status:** KILLED (persistence gate: wallet skill does not persist).

## Persistence gate (PREREG 8)

- Eligible coins: 1492; observations (≥ 1 early holder known at n ≥ 3): 405 (need ≥ 200); groups {'unknown': 1087, 'known_not_reputable': 396, 'reputable': 9}; distinct scoring wallets 134; warm-up observations 57.
- Decision: **KILL**.
- Spearman ρ = -0.0126, one-sided p = 0.5997, 6-h block 90% CI [-0.13732378084212196, 0.09887548827486341] (need ρ ≥ 0.1, p < 0.01, CI low > 0).
- Diagnostics (never decisive): {'label_mean_by_group': {'known_not_reputable': -0.7575554171007066, 'reputable': -0.5965144107336376, 'unknown': -1.0806574708057686}, 'label_mean_by_rep_tercile': {'high': -0.7233402501782473, 'low': -0.8532853997400438, 'mid': -0.685304534292691}, 'rho_without_warmup': -0.021138039844123237}.

## Decision

- **KILLED_GATE**.
- Shortlist written: False.
- PREREG 8: the persistence gate precedes any P&L; the grid was not run

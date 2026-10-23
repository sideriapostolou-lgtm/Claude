# X3 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 04:44:31 UTC; runtime 17.7 s; PREREG sha256 `6210e5a6a39b`; trials in the ledger: 2584.
- **Overall X3 status:** UNDERPOWERED (too few deep-pool climaxes for the reversion gate on TRAIN).

## Reversion gate (PREREG 8)

- Deep `now` events (m = 2): 19 from 19 coins (with matched draws: 19, mean draws per event 20.0); need ≥ 50 and ≥ 30 coins; by depth bucket {'d1470': 12, 'd3440': 7}.
- Diagnostics: deep `confirm` events 5, shallow (100-1,470 SOL) events 173.
- Decision: **UNDERPOWERED**; passing horizons: [].
- H = 10 min: excess -3.38% (95% CI by coin [-21.8, +15.0]) vs mean rt +3.16%; events -7.75%, draws -4.37%; pass False.
- H = 30 min: excess -7.66% (95% CI by coin [-29.7, +13.4]) vs mean rt +3.16%; events -13.84%, draws -6.18%; pass False.
- Diagnostic bucket_d1470: H10: -8.98% vs rt +3.26% (n 12); H30: -24.74% vs rt +3.26% (n 12).
- Diagnostic bucket_d3440: H10: +6.22% vs rt +2.98% (n 7); H30: +21.61% vs rt +2.98% (n 7).
- Diagnostic deep_confirm: H10: -2.37% vs rt +3.24% (n 5); H30: -10.45% vs rt +3.24% (n 5).
- Diagnostic shallow: H10: +2.28% vs rt +3.78% (n 173); H30: +4.14% vs rt +3.78% (n 173).

## Decision

- **UNDERPOWERED_GATE**.
- Shortlist written: False.
- PREREG 8: the reversion gate precedes any strategy P&L; the grid was not run

# X5 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 05:18:22 UTC; runtime 35.2 s; PREREG sha256 `8b8bce32d761`; trials in the ledger: 2636.
- **Overall X5 status:** NO EDGE (nothing qualified on TRAIN).

## Regime coverage (counts)

- Grid ['2026-09-29 23:45:00', '2026-10-05 03:15:00'] (495 points of 15 min). GR pool: tradeable graduates created before 2026-10-05 00:00:00. AV/SV pool: 3863 usable coins of ['train'] created in ['2026-10-01 00:00:00', '2026-10-05 00:00:00'].
- Records: {'GR': 4209, 'AV': 197394, 'SV': 3863}; known grid points: {'GR': 404, 'AV': 341, 'SV': 352}; first known point: {'GR': '2026-09-30 19:00:00', 'AV': '2026-10-01 11:00:00', 'SV': '2026-10-01 08:30:00'}.
- Share of the split's coins with a known regime at g + 60 min (current point and its 24-h baseline): {'GR': 0.817, 'AV': 0.646, 'SV': 0.667}.

## Model check (stop rule, PREREG 7)

- Coins alive at their R0 decision: 914 (need ≥ 200 observations with a known state per signal).
- GR: 739 observations; ρ = -0.0353, 6-h block 90% CI [-0.1084590291476918, 0.058201926108901916]; **FAIL**.
- AV: 581 observations; ρ = -0.0892, 6-h block 90% CI [-0.16140910361359057, 0.019139516166272318]; **FAIL**.
- SV: 601 observations; ρ = 0.008, 6-h block 90% CI [-0.08298277843776938, 0.11639466147331477]; **PASS**.
- Decision: **PASS**; signals in the grid: ['SV'].

## Regime diagnostics (never decisive)

- Persistence over 2 h: {'GR': {'n': 50, 'spearman': 0.6786031870065256}, 'AV': {'n': 42, 'spearman': 0.3096183453528888}, 'SV': {'n': 43, 'spearman': 0.40352665760459133}}.
- Rank correlations: {'GR~AV': {'n': 340, 'spearman': 0.5884687053733709}, 'GR~SV': {'n': 350, 'spearman': -0.36596115156710957}, 'AV~SV': {'n': 341, 'spearman': 0.024784851357781947}}.

## Hosts (ungated)

- R0: n 914, mean -20.4%, 90% CI coin [-23.5, -17.1], 6-h block [-24.9, -15.9], w/o top 2 -21.5%.

## Gated configs

| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | contrast ON−OFF [6-h block 90% CI] | n OFF | costs ×1.5 |
|---|---|---:|---:|---:|---|---|---:|---:|---|---:|---:|
| R0|SV|q0.5 | R0|SV|q0.5 | 248 | 248 | -21.4% | [-26.7, -15.7] | [-28.5, -12.8] | -23.5% | -1.2% | -3.9% [-15.4, +8.2] | 353 | -22.6% |
| R0|SV|q0.8 | R0|SV|q0.8 | 97 | 97 | -24.7% | [-32.0, -17.4] | [-34.6, -14.2] | -27.9% | -3.8% | -6.8% [-18.7, +5.5] | 504 | -25.9% |

## Decision

- **NO_CONFIG**.
- R0|SV|q0.5: n 248, mean -21.4%, block CI low -28.5%, placebo diff -1.2%, contrast -3.9%; EDGE False, VETO False.
- R0|SV|q0.8: n 97, mean -24.7%, block CI low -34.6%, placebo diff -3.8%, contrast -6.8%; EDGE False, VETO False.
- Shortlist written: False .
- powered configs failed the EDGE bars and no contrast reached the VETO bar

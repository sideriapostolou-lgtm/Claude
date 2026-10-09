# Y1 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **History** (outcome records): splits ['train']; 3863 coins, 3628 records from 3441 creators; structural pool 5435 graduates; first history graduation 2026-10-01 00:01:23 UTC.
- **Written:** 2026-10-09 08:48:31 UTC; runtime 39.1 s; PREREG sha256 `15301aa0ed49`; trials in the ledger: 2671.
- **Overall Y1 status:** NO EDGE (nothing qualified on TRAIN).

## Event counts (no returns)

- Status at the first post-BOOST decision: {'new': 3427, 'unknown': 235, 'eligible': 113, 'shared': 66, 'pending': 22}; shared keys by rule: {'signs_for_others': 64, 'multi_signer': 2}.
- Coins eligible inside the entry window (repeat deployer, ≥ 1 resolved record): 135 (33.8 per day) from 108 creators; median eligible age 7.5 min; resolved records at eligibility: {'1': 110, '2': 20, '3': 3, '4': 2}.

## Persistence gate (stop rule, PREREG 8)

- Observations: 135 from 108 creators in 53 deployer clusters (need ≥ 60 and ≥ 20); warm-up observations: 20.
- Decision: **PASS**.
- Spearman ρ(record, next 30 min) = 0.16593441299607126; deployer-cluster 90% CI [0.007380661551046836, 0.28910145752793964]; diagnostics {'label_mean_record_ge0': -0.285711828797345, 'n_record_ge0': 49, 'label_mean_record_lt0': -0.3731159233025995, 'n_record_lt0': 86, 'rho_without_warmup': 0.16627212398238767, 'n_without_warmup': 115}.

## Configs

| role | config | n | clusters | mean | 90% CI coin | 90% CI 6-h block | 90% CI cluster | w/o top 2 | placebo diff (eligible) | placebo diff (unmatched) | costs ×1.5 |
|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|
| good|th0|T30 | good|th0|T30 | 49 | 16 | -29.8% | [-40.9, -18.4] | [-44.1, -16.3] | [-55.6, -22.1] | -34.3% | +5.4% | +2.7% | -30.8% |
| good|th0|T60 | good|th0|T60 | 49 | 16 | -26.7% | [-39.0, -13.9] | [-42.3, -11.3] | [-51.5, -18.9] | -33.1% | +8.6% | +15.4% | -27.7% |
| good|th0.1|T30 | good|th0.1|T30 | 20 | 11 | -56.3% | [-67.4, -44.8] | [-68.6, -42.1] | [-66.7, -42.7] | -62.0% | -11.3% | -16.6% | -57.2% |
| good|th0.1|T60 | good|th0.1|T60 | 20 | 11 | -50.8% | [-65.3, -34.6] | [-66.5, -30.4] | [-64.5, -29.0] | -60.7% | -5.1% | -2.1% | -51.9% |
| host|T30 | host|T30 | 135 | 53 | -38.5% | [-46.1, -30.5] | [-48.9, -27.9] | [-50.2, -30.5] | -41.7% | -2.0% | -6.4% | -39.6% |
| host|T60 | host|T60 | 135 | 53 | -41.6% | [-48.9, -34.2] | [-50.8, -32.3] | [-54.3, -33.3] | -44.6% | -3.7% | -2.6% | -42.7% |

## Bad-record veto (PREREG 6)

- host|T30: host trades 135, flagged 86, unflagged 49; flagged mean -43.5%, unflagged mean -29.8%; verdict **FAIL**.
- host|T60: host trades 135, flagged 86, unflagged 49; flagged mean -50.1%, unflagged mean -26.7%; verdict **FAIL**.

## Decision

- **NO_CONFIG**.
- good|th0|T30: n 49, clusters 16, mean -29.8%, 90% CI cluster low -55.6%, placebo diff +5.4%, qualifies False.
- good|th0|T60: n 49, clusters 16, mean -26.7%, 90% CI cluster low -51.5%, placebo diff +8.6%, qualifies False.
- good|th0.1|T30: n 20, clusters 11, mean -56.3%, 90% CI cluster low -66.7%, placebo diff -11.3%, qualifies False.
- good|th0.1|T60: n 20, clusters 11, mean -50.8%, 90% CI cluster low -64.5%, placebo diff -5.1%, qualifies False.
- Shortlists written: False.
- a powered GOOD config failed the mean / top-2 / matched-control bars

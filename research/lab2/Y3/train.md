# Y3 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 04:45:35 UTC; runtime 492.6 s; PREREG sha256 `734f3bbb96e6`; trials in the ledger: 2594.
- **Overall Y3 status:** UNDERPOWERED (TRAIN).

## Configs

| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | compressed diff | unmatched diff | costs ×1.5 | censored |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| N10|th0.06|broad | N10|th0.06|broad | 8 | 8 | +2.7% | [-25.2, +47.9] | [-25.4, +49.5] | -23.8% | +14.3% | -8.1% | +11.8% | +0.9% | +0% |
| N10|th0.06|chart | N10|th0.06|chart | 82 | 82 | -5.3% | [-10.7, +0.7] | [-12.9, +3.3] | -9.2% | +7.1% | -3.0% | +5.3% | -7.1% | +0% |
| N10|th0.12|broad | N10|th0.12|broad | 26 | 26 | -17.7% | [-29.7, -2.6] | [-33.1, +2.4] | -27.0% | -4.5% | -7.1% | -5.8% | -19.3% | +0% |
| N10|th0.12|chart | N10|th0.12|chart | 183 | 183 | -9.1% | [-12.9, -5.2] | [-14.7, -3.3] | -11.0% | +2.4% | -5.8% | +1.1% | -10.9% | +0% |
| N20|th0.06|broad | N20|th0.06|broad | 1 | 1 | -4.2% | n/a | n/a | n/a | +6.1% | +10.3% | +11.9% | -5.7% | +0% |
| N20|th0.06|chart | N20|th0.06|chart | 15 | 15 | -8.3% | [-12.0, -4.8] | [-12.6, -3.7] | -10.0% | +3.5% | -0.6% | +2.0% | -9.8% | +0% |
| N20|th0.12|broad | N20|th0.12|broad | 3 | 3 | -27.0% | [-41.8, -12.2] | [-41.8, -12.2] | -48.6% | -15.0% | -18.9% | -13.8% | -28.3% | +0% |
| N20|th0.12|chart | N20|th0.12|chart | 37 | 37 | -5.4% | [-9.8, -0.9] | [-11.0, +0.1] | -7.6% | +6.4% | +1.8% | +6.2% | -7.1% | +0% |

## Decision

- **UNDERPOWERED_TRAIN**.
- N10|th0.06|broad: n 8, coins 8, mean +2.7%, 90% CI low -25.2%, placebo diff +14.3%, compressed diff -8.1%, broad − chart +8.0%, qualifies False.
- N10|th0.12|broad: n 26, coins 26, mean -17.7%, 90% CI low -29.7%, placebo diff -4.5%, compressed diff -7.1%, broad − chart -8.6%, qualifies False.
- N20|th0.06|broad: n 1, coins 1, mean -4.2%, 90% CI low n/a, placebo diff +6.1%, compressed diff +10.3%, broad − chart +4.1%, qualifies False.
- N20|th0.12|broad: n 3, coins 3, mean -27.0%, 90% CI low -41.8%, placebo diff -15.0%, compressed diff -18.9%, broad − chart -21.6%, qualifies False.
- Shortlist written: False (candidate None, twin None).
- Reason: no broad config reached >= 60 trades from >= 40 coins (best: 26 trades, 26 coins).

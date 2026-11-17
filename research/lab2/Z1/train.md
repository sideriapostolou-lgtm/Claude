# Z1 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 05:00:19 UTC; runtime 193.7 s; PREREG sha256 `50e4c4b9919e`; trials in the ledger: 2609.
- **Overall Z1 status:** NO EDGE (nothing qualified on TRAIN).

## Configs

| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | price-matched diff | unmatched diff | costs ×1.5 | censored |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| K10|t30 | K10|t30 | 377 | 377 | -17.2% | [-20.3, -14.0] | [-21.4, -12.9] | -18.4% | +1.2% | +0.1% | +0.8% | -18.8% | +0% |
| K10|t60 | K10|t60 | 377 | 377 | -16.9% | [-20.8, -12.7] | [-22.3, -10.6] | -18.7% | +3.1% | +1.7% | +3.7% | -18.5% | +0% |
| K10|sret60 | K10|sret60 | 377 | 377 | -15.9% | [-18.3, -13.4] | [-19.8, -11.8] | -16.5% | +1.6% | +0.5% | -0.7% | -17.5% | +0% |
| K20|t30 | K20|t30 | 360 | 360 | -16.4% | [-22.5, -7.7] | [-23.4, -5.3] | -21.1% | +2.7% | +1.8% | +1.3% | -18.0% | +0% |
| K20|t60 | K20|t60 | 360 | 360 | -16.5% | [-23.5, -6.6] | [-25.1, -3.6] | -22.2% | +3.8% | +2.4% | +3.9% | -18.0% | +0% |
| K20|sret60 | K20|sret60 | 360 | 360 | -20.1% | [-23.1, -17.0] | [-24.3, -15.9] | -21.2% | -1.2% | -1.4% | -3.0% | -21.6% | +0% |

## Decision

- **NO_CONFIG**.
- K10|t30: n 377, coins 377, mean -17.2%, 90% CI low -20.3%, placebo diff +1.2%, price-matched diff +0.1%, qualifies False.
- K10|t60: n 377, coins 377, mean -16.9%, 90% CI low -20.8%, placebo diff +3.1%, price-matched diff +1.7%, qualifies False.
- K10|sret60: n 377, coins 377, mean -15.9%, 90% CI low -18.3%, placebo diff +1.6%, price-matched diff +0.5%, qualifies False.
- K20|t30: n 360, coins 360, mean -16.4%, 90% CI low -22.5%, placebo diff +2.7%, price-matched diff +1.8%, qualifies False.
- K20|t60: n 360, coins 360, mean -16.5%, 90% CI low -23.5%, placebo diff +3.8%, price-matched diff +2.4%, qualifies False.
- K20|sret60: n 360, coins 360, mean -20.1%, 90% CI low -23.1%, placebo diff -1.2%, price-matched diff -1.4%, qualifies False.
- Shortlist written: False (rank order []).
- Reason: a powered config failed the mean / top-2 / matched-control / censoring bars.

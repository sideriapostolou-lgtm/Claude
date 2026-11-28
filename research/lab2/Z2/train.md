# Z2 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 05:03:34 UTC; runtime 178.7 s; PREREG sha256 `e672fd0e1edc`; trials in the ledger: 2617.
- **Overall Z2 status:** NO EDGE (nothing qualified on TRAIN).

## Configs

| role | config | n | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (matched) | diff 95% CI | placebo diff (unmatched) | costs ×1.5 | direction |
|---|---|---:|---:|---|---|---:|---:|---|---:|---:|---|
| q0.03|h15|time | q0.03|h15|time | 333 | -17.3% | [-19.2, -15.3] | [-19.7, -14.7] | -17.9% | -3.7% | [-6.1, -1.2] | -0.4% | -19.1% | EXIT_LIQUIDITY |
| q0.03|h15|seller | q0.03|h15|seller | 333 | -15.5% | [-17.1, -13.8] | [-17.6, -13.3] | -15.9% | -2.6% | [-4.6, -0.6] | +0.9% | -17.4% | EXIT_LIQUIDITY |
| q0.03|h60|time | q0.03|h60|time | 333 | -21.4% | [-23.7, -19.0] | [-24.4, -18.3] | -22.4% | -4.5% | [-7.4, -1.4] | +2.5% | -23.2% | EXIT_LIQUIDITY |
| q0.03|h60|seller | q0.03|h60|seller | 333 | -16.2% | [-18.0, -14.3] | [-18.3, -14.0] | -16.9% | -1.9% | [-4.3, +0.8] | +6.7% | -18.1% | NEITHER |
| q0.06|h15|time | q0.06|h15|time | 63 | -19.6% | [-26.2, -12.8] | [-28.0, -10.6] | -23.0% | -6.2% | [-14.3, +2.7] | -3.5% | -21.4% | NEITHER |
| q0.06|h15|seller | q0.06|h15|seller | 63 | -22.8% | [-28.1, -17.8] | [-31.3, -15.3] | -24.1% | -9.9% | [-16.5, -3.7] | -6.7% | -24.5% | EXIT_LIQUIDITY |
| q0.06|h60|time | q0.06|h60|time | 63 | -27.8% | [-33.2, -22.6] | [-35.6, -20.1] | -29.8% | -10.8% | [-17.5, -4.1] | -6.0% | -29.4% | EXIT_LIQUIDITY |
| q0.06|h60|seller | q0.06|h60|seller | 63 | -26.6% | [-31.7, -21.5] | [-34.5, -19.2] | -28.0% | -11.0% | [-17.2, -4.8] | -5.1% | -28.2% | EXIT_LIQUIDITY |

## Decision

- **NO_CONFIG**.
- q0.03|h15|time: n 333, mean -17.3%, 90% CI low -19.2%, placebo diff -3.7%, direction EXIT_LIQUIDITY, qualifies False.
- q0.03|h15|seller: n 333, mean -15.5%, 90% CI low -17.1%, placebo diff -2.6%, direction EXIT_LIQUIDITY, qualifies False.
- q0.03|h60|time: n 333, mean -21.4%, 90% CI low -23.7%, placebo diff -4.5%, direction EXIT_LIQUIDITY, qualifies False.
- q0.03|h60|seller: n 333, mean -16.2%, 90% CI low -18.0%, placebo diff -1.9%, direction NEITHER, qualifies False.
- q0.06|h15|time: n 63, mean -19.6%, 90% CI low -26.2%, placebo diff -6.2%, direction NEITHER, qualifies False.
- q0.06|h15|seller: n 63, mean -22.8%, 90% CI low -28.1%, placebo diff -9.9%, direction EXIT_LIQUIDITY, qualifies False.
- q0.06|h60|time: n 63, mean -27.8%, 90% CI low -33.2%, placebo diff -10.8%, direction EXIT_LIQUIDITY, qualifies False.
- q0.06|h60|seller: n 63, mean -26.6%, 90% CI low -31.7%, placebo diff -11.0%, direction EXIT_LIQUIDITY, qualifies False.
- Primary direction reading (PREREG 8): {'config': 'q0.03|h60|time', 'direction': 'EXIT_LIQUIDITY'}.
- Shortlist written: False [].
- a powered config failed the mean / top-2 / matched-control bars

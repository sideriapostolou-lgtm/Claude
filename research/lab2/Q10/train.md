# Q10 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 11:03:36 UTC; runtime 215.8 s; PREREG sha256 `dbcfe323c075`; trials in the ledger: 2684.
- **Overall Q10 status:** NO EDGE (nothing qualified on TRAIN).

## Configs

| role | config | n | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (matched) | diff 95% CI | LP − 50/50 hold | costs ×1.5 | direction |
|---|---|---:|---:|---|---|---:|---:|---|---:|---:|---|
| M6|D0.7 | M6|D0.7 | 540 | -27.8% | [-30.2, -25.4] | [-30.6, -24.9] | -28.6% | -2.3% | [-5.2, +0.8] | -8.6% | -28.5% | NEITHER |
| M6|D0.5 | M6|D0.5 | 540 | -36.0% | [-38.9, -32.9] | [-39.6, -32.3] | -36.9% | -6.7% | [-10.3, -2.8] | -14.0% | -36.6% | WORSE_THAN_RANDOM |
| M6|deadline | M6|deadline | 540 | -48.2% | [-51.8, -44.3] | [-52.9, -43.2] | -49.3% | -12.5% | [-16.9, -7.7] | -23.8% | -48.7% | WORSE_THAN_RANDOM |
| M3|D0.7 | M3|D0.7 | 599 | -28.2% | [-30.5, -25.8] | [-31.0, -25.2] | -28.8% | -3.4% | [-6.2, -0.5] | -9.0% | -28.9% | WORSE_THAN_RANDOM |
| M3|D0.5 | M3|D0.5 | 599 | -36.4% | [-39.2, -33.5] | [-39.7, -32.9] | -37.2% | -7.7% | [-11.1, -4.3] | -14.1% | -37.0% | WORSE_THAN_RANDOM |
| M3|deadline | M3|deadline | 599 | -48.0% | [-51.4, -44.5] | [-52.5, -43.3] | -49.0% | -13.0% | [-17.1, -8.7] | -23.4% | -48.5% | WORSE_THAN_RANDOM |

## LP decomposition (same entries)

| role | token mid return | 50/50 hold, no fees | est. LP fee income | LP − 50/50 | gap 95% CI | mean V15/x_real | mean bars held | exit reasons |
|---|---:|---:|---:|---:|---|---:|---:|---|
| M6|D0.7 | -36.0% | -19.2% | +0.8% | -8.6% | [-9.8, -7.5] | 24.0 | 20.2 | {'stop': 496, 'quiet': 23, 'deadline': 21} |
| M6|D0.5 | -41.7% | -22.0% | +1.5% | -14.0% | [-15.5, -12.7] | 24.0 | 35.9 | {'stop': 458, 'deadline': 51, 'quiet': 31} |
| M6|deadline | -46.8% | -24.4% | +2.0% | -23.8% | [-25.8, -22.0] | 24.0 | 99.6 | {'quiet': 384, 'deadline': 156} |
| M3|D0.7 | -35.9% | -19.1% | +0.8% | -9.0% | [-10.2, -7.9] | 22.0 | 20.9 | {'stop': 545, 'quiet': 29, 'deadline': 25} |
| M3|D0.5 | -42.2% | -22.2% | +1.4% | -14.1% | [-15.5, -12.8] | 22.0 | 36.2 | {'stop': 502, 'deadline': 58, 'quiet': 39} |
| M3|deadline | -47.1% | -24.6% | +1.8% | -23.4% | [-25.3, -21.7] | 22.0 | 97.4 | {'quiet': 431, 'deadline': 168} |

## Decision

- **NO_CONFIG**.
- M6|D0.7: n 540, mean -27.8%, 90% CI low -30.2%, placebo diff -2.3%, direction NEITHER, qualifies False.
- M6|D0.5: n 540, mean -36.0%, 90% CI low -38.9%, placebo diff -6.7%, direction WORSE_THAN_RANDOM, qualifies False.
- M6|deadline: n 540, mean -48.2%, 90% CI low -51.8%, placebo diff -12.5%, direction WORSE_THAN_RANDOM, qualifies False.
- M3|D0.7: n 599, mean -28.2%, 90% CI low -30.5%, placebo diff -3.4%, direction WORSE_THAN_RANDOM, qualifies False.
- M3|D0.5: n 599, mean -36.4%, 90% CI low -39.2%, placebo diff -7.7%, direction WORSE_THAN_RANDOM, qualifies False.
- M3|deadline: n 599, mean -48.0%, 90% CI low -51.4%, placebo diff -13.0%, direction WORSE_THAN_RANDOM, qualifies False.
- Primary direction reading (PREREG 8): {'config': 'M6|D0.7', 'direction': 'NEITHER'}.
- Shortlist written: False [].
- a powered config failed the mean / top-2 / judged-control bars

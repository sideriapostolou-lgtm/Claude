# O1 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 05:29:12 UTC; runtime 58.8 s; PREREG sha256 `2dd0e80d7419`; trials in the ledger: 2642.
- **Overall O1 status:** PENDING VAL.

## Configs

| role | config | n | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (matched) | diff 95% CI | placebo diff (class-matched) | costs ×1.5 | direction |
|---|---|---:|---:|---|---|---:|---:|---|---:|---:|---|
| t30|r0exit | t30|r0exit | 237 | -0.7% | [-3.2, +1.6] | [-4.9, +2.7] | -1.3% | +33.4% | [+29.7, +36.7] | +0.3% | -1.6% | BEATS_RANDOM |
| t30|tight | t30|tight | 237 | -2.8% | [-5.1, -0.7] | [-6.8, +0.4] | -3.2% | +23.8% | [+20.6, +26.6] | +0.2% | -3.6% | BEATS_RANDOM |
| t60|r0exit | t60|r0exit | 231 | -0.7% | [-3.1, +1.6] | [-3.5, +1.9] | -1.1% | +20.0% | [+16.8, +23.0] | +0.3% | -1.5% | BEATS_RANDOM |
| t60|tight | t60|tight | 231 | +0.4% | [-0.5, +1.3] | [-0.9, +1.4] | +0.1% | +17.6% | [+15.8, +19.1] | +0.2% | -0.5% | BEATS_RANDOM |
| r0|r0exit | r0|r0exit | 233 | -2.9% | [-5.9, -0.1] | [-7.4, +0.7] | -3.5% | +16.7% | [+12.7, +20.4] | -1.8% | -3.8% | BEATS_RANDOM |
| r0|tight | r0|tight | 233 | -3.0% | [-5.5, -0.8] | [-7.1, +0.1] | -3.6% | +12.7% | [+9.5, +15.6] | -1.4% | -3.9% | BEATS_RANDOM |

## Decision

- **SHORTLISTED**.
- t30|r0exit: n 237, mean -0.7%, 90% CI low -3.2%, placebo diff +33.4%, direction BEATS_RANDOM, qualifies False.
- t30|tight: n 237, mean -2.8%, 90% CI low -5.1%, placebo diff +23.8%, direction BEATS_RANDOM, qualifies False.
- t60|r0exit: n 231, mean -0.7%, 90% CI low -3.1%, placebo diff +20.0%, direction BEATS_RANDOM, qualifies False.
- t60|tight: n 231, mean +0.4%, 90% CI low -0.5%, placebo diff +17.6%, direction BEATS_RANDOM, qualifies True.
- r0|r0exit: n 233, mean -2.9%, 90% CI low -5.9%, placebo diff +16.7%, direction BEATS_RANDOM, qualifies False.
- r0|tight: n 233, mean -3.0%, 90% CI low -5.5%, placebo diff +12.7%, direction BEATS_RANDOM, qualifies False.
- Primary direction reading (PREREG 8): {'config': 'r0|r0exit', 'direction': 'BEATS_RANDOM'}.
- Shortlist written: True ['t60|tight'].

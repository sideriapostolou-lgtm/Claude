# Z3 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 05:06:34 UTC; runtime 610.9 s; PREREG sha256 `9bc331c76ffd`; trials in the ledger: 2623.
- **Overall Z3 status:** UNDERPOWERED (TRAIN).

## Configs

| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | drawdown-matched diff | unmatched diff | costs ×1.5 | open fills | gross move | cost | censored |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| now|t5 | now|t5 | 51 | 51 | -5.2% | [-5.4, -5.0] | [-5.5, -4.9] | -5.3% | +11.4% | +11.6% | -7.6% | -5.1% | -0.1% | +5.1% | +0% |
| now|t15 | now|t15 | 51 | 51 | -5.0% | [-5.3, -4.7] | [-5.4, -4.6] | -5.2% | +14.1% | +14.5% | -7.4% | -4.9% | +0.1% | +5.1% | +0% |
| now|t60 | now|t60 | 51 | 51 | -4.9% | [-5.2, -4.6] | [-5.4, -4.5] | -5.1% | +17.8% | +23.9% | -7.4% | -4.8% | +0.1% | +5.1% | +0% |
| confirm|t5 | confirm|t5 | 11 | 11 | -5.1% | [-5.2, -5.0] | [-5.2, -5.0] | -5.1% | +17.0% | +10.8% | -7.5% | -4.9% | -0.1% | +5.0% | +0% |
| confirm|t15 | confirm|t15 | 11 | 11 | -5.1% | [-5.2, -5.0] | [-5.2, -5.0] | -5.1% | +17.1% | +16.0% | -7.5% | -4.9% | -0.0% | +5.0% | +0% |
| confirm|t60 | confirm|t60 | 11 | 11 | -5.1% | [-5.2, -4.9] | [-5.2, -4.9] | -5.1% | +19.8% | +28.7% | -7.5% | -4.9% | -0.0% | +5.0% | +0% |

## Pre-registered predictions (PREREG 7; reports, never decisive)

- P1_no_config_mean_net_above_0: held = True.
- P2_open_fills_below_plan_bar: held = True.
- P3_control_margin_below_6pts: held = False.
- Configs supporting craft rule G35 (control diff 95% CI below −10 points): none.

## Decision

- **UNDERPOWERED_TRAIN**.
- now|t5: n 51, coins 51, mean -5.2%, 90% CI low -5.4%, drawdown-matched diff +11.4%, unmatched diff +11.6%, qualifies False.
- now|t15: n 51, coins 51, mean -5.0%, 90% CI low -5.3%, drawdown-matched diff +14.1%, unmatched diff +14.5%, qualifies False.
- now|t60: n 51, coins 51, mean -4.9%, 90% CI low -5.2%, drawdown-matched diff +17.8%, unmatched diff +23.9%, qualifies False.
- confirm|t5: n 11, coins 11, mean -5.1%, 90% CI low -5.2%, drawdown-matched diff +17.0%, unmatched diff +10.8%, qualifies False.
- confirm|t15: n 11, coins 11, mean -5.1%, 90% CI low -5.2%, drawdown-matched diff +17.1%, unmatched diff +16.0%, qualifies False.
- confirm|t60: n 11, coins 11, mean -5.1%, 90% CI low -5.2%, drawdown-matched diff +19.8%, unmatched diff +28.7%, qualifies False.
- Shortlist written: False (rank order []).
- Reason: no config reached >= 60 trades from >= 40 coins (best: 51 trades, 51 coins).

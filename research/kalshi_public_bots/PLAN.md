# Public Kalshi bot evidence audit

Started 2026-10-13. Read-only discovery and rule reconstruction; no strategy deployment or orders.

## Scope frozen before performance analysis

1. Find Kalshi-native public bots with inspectable source, first-party methodology, or public trade records.
2. Pin code revisions and distinguish source behavior from README/marketing descriptions.
3. Separate venue-authenticated public information, author-published ledgers, simulated signal scoring,
   hypothetical backtests and unsupported claims. Public code is not proof of profitable live operation.
4. Check whether Kalshi public/social data can identify a trader, observe their actual fills and reconstruct
   inventory/P&L. Respect hidden profiles and authentication boundaries; no private endpoint probing.
5. Reconstruct entries, exits, sizing, fees, queue assumptions, risk controls and missing implementation.
6. Rank candidates for additional measurement, not for live funding. Include negative findings and uncertainty.

This is an exploratory source audit, not a backtest or parameter fit. No TRAIN/VAL/TEST outcomes will be
selected or opened in this session. Any future strategy test needs a separate frozen cohort, fee/execution
model, parameter budget and TRAIN -> VAL -> one TEST plan before observing those outcomes. Historical
performance observed here cannot later become an untouched TEST set.

No keys, authenticated trading calls, paid services or third-party code execution. Read source text only;
any independent arithmetic checks use our own minimal calculations. Do not change the app or trading desks.

Deliverables: sourced report, revision-pinned strategy notes and an honest recommendation for the next
measurable experiment. A new research candidate does not inherit the existing Bitcoin desk's money authority.

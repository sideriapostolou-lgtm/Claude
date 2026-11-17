# Extreme-payout crypto: exploratory strategy design

Started 2026-10-13 UTC at the owner's request. Research and a complete build specification only. No
production orders, account settings, existing strategies or money limits change in this task.

Before inspecting performance outcomes, freeze this scope:

1. Verify Kalshi's current BTC/ETH/SOL/XRP 15-minute contract rules, settlement sources, tie/rounding,
   price/quantity grids, public books/trades, fee rounding and exit mechanics from primary sources.
2. Take a bounded contemporaneous public metadata/book sample (at most 40 reads in the delegated sample).
   This describes executable quotes at collection, not a backtest or a representative return estimate.
3. Explain advertised 133x/455x/909x payoffs using explicit units, fees, quantities and depth. Separate
   possible settlement payout, realized sale proceeds, marked value and profit.
4. Design a candidate signal, entry/exit state machine, accounting and risk envelope. All numerical
   thresholds are initial research choices, not discovered profitable rules or live authorizations.
5. Specify fresh chronological TRAIN -> VAL -> one TEST, realistic latency/queue simulation, rare-event
   uncertainty, correlated losses, capacity and adverse selection before any claim of edge.
6. Audit the existing desk for compatibility; preserve its buys-only behavior and current controls.

No winner-selected backtest, historical outcome fitting, paid datasets, restricted data bypass, downloaded
third-party executable, or account credentials. An observed historical or exploratory sample cannot later
be called untouched TEST. A future recorder/replay implementation must freeze its exact cohort, sample
size, model/parameter budget and evaluation horizon before looking at held-out outcomes.

Deliverables: sourced verdict and complete research/build specification, evidence snapshot, reproducible
arithmetic, and a WORKLOG entry. Any later live experiment requires this strategy's own explicit amounts;
the existing Bitcoin desk's authority does not transfer to it.

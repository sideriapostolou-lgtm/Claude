# Kalshi cash by exchange index

October 16, 2026 correction. Aggregate account cash is not a promise that a Bitcoin
order can be funded on its matching engine. Cash is not trading profit.

## Evidence and contract

The rejected `KXBTC15M-26OCT160945-45` window's public market response was independently
read at approximately **6:59 AM PDT**. It returned HTTP 200 and `exchange_index: 2`.
The deployed client correctly routes orders by ticker with `exchange_index: -1`,
but its earlier cash check used the aggregate primary-account balance. These are
different scopes.

The [exchange-sharding guide](https://docs.kalshi.com/getting_started/exchange_sharding)
explains that API traders must fund the relevant exchange index; the automatic cash
movement used by Kalshi's app does not imply the same behavior for API orders.
This identifies a code defect and a plausible account-specific explanation. The
actual account's per-index cash distribution has **not** been read or verified.

The [balance endpoint](https://docs.kalshi.com/api-reference/portfolio/get-balance)
uses integer cents for legacy `balance`, USD strings for `balance_dollars`, and USD
strings for each `balance_breakdown[].balance`. Omission of the exchange filter
aggregates indexes. A missing breakdown or index is not documented as funded or
zero. Its last-update timestamp is not the time the response was received.

The [subaccount-balances endpoint](https://docs.kalshi.com/api-reference/portfolio/get-all-subaccount-balances)
explicitly identifies each row's subaccount, exchange index and USD cash. The bot's
order subaccount is zero. Cash assigned to another subaccount cannot fund it.
Cash evidence still needs local outstanding-order and fee reservations; an HTTP 200
balance response is not proof of venue acceptance or the absence of account holds.

## Release scope and verification

The correction preserves the market's index, gates orders with cash from the
primary subaccount on that index, and retains a refusal cooldown through successful
account reads and restarts. Final checks and exact deployment evidence are recorded
in the [release report](../research/kalshi_shard_cash_2026-10-16/REPORT.md).

Both ordinary buys and balancing locks reserve fees and all outstanding bot orders.
Uncertain or cancellation-pending orders remain reserved. Actual fills after the
cash snapshot reduce available cash until the next successful balance refresh.
Unknown routing or missing balances stop new buys. Foreign resting orders also
block new buys conservatively; the bot does not cancel the owner's orders.

A definite `insufficient_balance` refusal delays new creates for 60 seconds, then
120, 240 and at most 300 seconds on consecutive refusals. Successful account reads
do not erase this pause. An acknowledged eligible order resets escalation. Account
reconciliation and cancellation continue during the pause. The rejection and pause
are checkpointed together before a restart can release the refused reservation.

The status distinguishes `cash_total_usd` from `shard_funding` and shows
`create_funding_cooldown`. Paper startup does not construct a trading client merely
to populate these fields, so unavailable cash remains explicitly unknown.

The production desk was externally switched back to paper at **6:38 AM PDT**.
Codex independently observed `PRACTICE` at **6:58:16 AM PDT**, source `27539273`,
deployment `07e8627b`. Current UTC-day P&L was **-$5.1277**, cumulative settled P&L
**-$24.6195**, with the $10/window, $20 open, $6 daily and existing $10 total-loss
allowance retained. The fresh paper process had no authenticated cash reading.
No successful fills or profitability are inferred from these observations.

## Cash movement remains separate

No transfer or standing allocation change is part of this software correction.
[Intra-account transfers](https://docs.kalshi.com/api-reference/portfolio/intra-account-transfer)
and [target balance allocation](https://docs.kalshi.com/api-reference/portfolio/set-target-balance-allocation)
move real funds. Transfer creation uses **centicents**, whereas the transfer-status
response uses USD; an accepted asynchronous request is not completed funding.
Automatic allocation continues rebalancing and is a financial setting.

The owner must arrange any funding change in Kalshi. Before calling the incident
resolved, obtain exact primary-account/index cash evidence and, after any owner
activation, verify actual order behavior separately. Existing loss history,
limits, stop/resume controls, Polymarket behavior and the sealed research TEST
remain unchanged. This repair does not establish a profitable trading strategy.

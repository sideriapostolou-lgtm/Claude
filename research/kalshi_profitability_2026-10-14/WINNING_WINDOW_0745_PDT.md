# The owner's October 14, 7:45 AM Pacific winning card

Checked read-only on 2026-10-14 around 08:55 AM PDT (15:55 UTC).
The screenshot shows BTC Down, target $81,897.35, cost $3.62, payout $6.00 and
profit $2.38 (+65.78%). It is one closed-position card, not an account win rate.

Kalshi's public market endpoint returned HTTP 200 for
`KXBTC15M-26OCT141045-45`: floor strike 81897.35, opened 14:30 UTC,
closed 14:45 UTC, result `no`. This matches the target, side and close time.
Connected Railway logs contain this window's real bot fills and settlement.

| Venue fill time (PDT) | Side | Contracts | Price | Role | Fee |
| --- | --- | ---: | ---: | --- | ---: |
| 07:30:29.227 AM | Down | 5 | $0.36 | maker | $0 |
| 07:37:56.352 AM | Up | 5 | $0.33 | maker | $0 |
| 07:40:10.450 AM | Up | 3 | $0.16 | maker | $0 |
| 07:40:54.304 AM | Down | 5 | $0.67 | maker | $0 |
| 07:41:46.426 AM | Up | 2 | $0.16 | taker / lock | $0.0189 |

These are venue fill timestamps from the logged `at` field, not log-arrival times.
Some fills appeared in Railway logs seconds later; this table does not establish
fast discovery or order execution. Four maker fill records account for 18 of 20
contracts, and the final two-contract lock was a taker fill.

The actual maker decisions used a fair-value discount: Down at $0.36 against
modeled fair 0.396232; Up at $0.33 against 0.362111; Up at $0.16 against
0.198176; Down at $0.67 against 0.700156. The final lock completed the remaining
two Up contracts. This describes one realized path, not a fitted profitable rule.

The settlement receipt, logged 07:45:10.802 AM PDT, records:

- 10 Up and 10 Down contracts accumulated;
- $7.60 purchase cost plus $0.0189 fees = **$7.6189 total cost**;
- $10 combined payout / paired credit;
- **+$2.3811 locked-pair P&L**, directional P&L zero within floating-point rounding.

Average combined cost was $0.76189 per completed pair. Once both sides were
actually filled, the pairs produced the recorded profit whichever side settled.
Before completion, the unpaired contracts still carried directional risk.

The screenshot's rounded $2.38 profit matches this receipt. Its $3.62/$6 display
does not equal the full accumulated ledger's $7.6189/$10 gross figures. Netting
or the venue's presentation may account for that; cash-credit transactions were
not fetched, so this note does not claim to reconcile those display components.

This is evidence that the existing pair-completion behavior worked in this window.
It predates the proposed processing fix, which has not been deployed.
It is not evidence of a 100% win rate or a reason to extrapolate the +65.78% display
return to all invested capital. Keep every losing and incomplete window in the
evaluation. The prior completed UTC day's real settled P&L remains -$11.0074.
No trading rule, order, variable, cap or deployment was changed for this check.

Sources: owner screenshot; public
`GET https://api.elections.kalshi.com/trade-api/v2/markets/KXBTC15M-26OCT141045-45`;
Railway bot runtime logs queried 14:30-14:55 UTC, 277 returned rows, exact top-level
`speeddesk_live_fill`, `speeddesk_live_order` and `speeddesk_live_settlement` events.
The query was below its 500-row cap. Embedded repetitions in status snapshots were
excluded from fill counts.

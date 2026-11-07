# Independent receipt arithmetic: J0shusmc/Kalshi-BTC

**Result: internally reconciled, publisher-hosted receipt-shaped evidence of +$78.134 after $16.271 fees over 31 markets. This is stronger evidence than the paper ledgers, but it is not an independently authenticated complete account or proof of a currently profitable strategy.**

Source pin: `d5a55bf10c02ddc2b429eec78b1fd847fa1b6760`.
[Published ledger](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_trade_log.json).
The source file downloaded by Sol has SHA256 `d0d3f6176bcb1a23d93616fa0a53965634129d1613dc69281d8b894bcbea8df6`. Root's reformatted copy hashes differently but parsed JSON is exactly equal. This review independently parsed the original using Decimal and its own script; it did not execute/import the bot or reuse Sol's arithmetic script.

## Reconciliation

- 84 fill rows; **84 distinct fill IDs**, 56 distinct order IDs, 31 distinct market tickers.
- 31 settlement rows; all distinct. Every fill ticker has a settlement, and every settlement ticker has fills in this file.
- For **each of all31 markets**, fill-derived YES count, NO count, YES cost, NO cost and fees **exactly equal** the corresponding settlement fields. Zero mismatches across155 field comparisons.
- Payout derived from counts on the winning side totals **$853.00**; total YES+NO acquisition cost **$758.595000**; total fees **$16.271000**; net **+$78.134000**.
- 24 positive and7 negative market P&Ls. Sample includes40maker fill rows and44taker rows, not a pure maker strategy.
- Earliest fill: August27,2026 23:48:20.924022Z; latest September16 16:24:46.145582Z. `kalshi_synced_at` September17 23:54:03.653079Z. These dates are a bounded historical record, not evidence of activity continuing to today.

Correct interpretation matters. Recorded `book_side=bid,outcome_side=yes` and `book_side=ask,outcome_side=no` are opposite economic exposures; a local sale of a YES position may appear as buying the complement. The relevant fill cost is quantity times its **outcome-side** price. We confirmed this treatment against all settlement-side totals. Do not mechanically treat every raw `action=sell` as selling the recorded NO exposure.

For example, first market has5NO at59c and5YES at0.1c, total cost$2.955, fee$0.0851 and winning-side count5, giving+$1.9599. Its raw `revenue` field is0: that field alone omits prior matched-pair netting cashflows and is not a standalone lifetime payout measure. Winning-side count minus both costs and fee is algebraically equivalent to matched-pair credits plus residual winning exposure, under these records. This is an internally consistent accounting reconstruction, not an audit of bank cash receipts.

**Fee semantics:** the sum of fill `fee_cost` within each ticker equals settlement `fee_cost` exactly. These are the same charges summarized twice, **not additive charges**. Use either set once. No invented current fee formula or blanket one-cent fee was imposed.

## Strategy attribution is local and mixed

The local buy records matched by order ID give one strategy tag per settlement ticker. These tags are not exchange-provided strategy IDs.

| Local tag | Markets | Net after recorded fees |
|---|---:|---:|
| PULLBACK_99 |18|−$1.646900|
| NO_RECLAIM_80 |2|+$6.014300|
| BTC_FADE_90 |8|+$32.050000|
| RECLAIM_70 |3|+$41.716600|

Keep the losing18-market family. The3-market RECLAIM_70 slice supplies53.39% of total net; one tiny favorable slice cannot validate a general current rule. Raw quantities include fractions and prices include subcent values, so integer-only reconstruction would lose information. Current implementation changes and retired strategies must be audited separately from this historical attribution; this arithmetic review does not certify live/backtest parity.

## Coverage and authenticity limits

[Source API reads](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L482) request `/portfolio/fills` and `/portfolio/settlements` with `limit=1000`, without cursor pagination. [Sync logic](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1040) filters BTC15M and replaces stored arrays with fetched rows. Even though this file has fewer than1000 BTC rows, non-BTC account records could consume the page. This does not prove truncation happened; it prevents a completeness claim. No API response cursor, raw response envelope, authenticated account balance/cashflow, deposit/withdrawal record or independent venue access was checked.

One pending sell order remains in the publisher log although its September10 market is settled; active_positions is empty. That is evidence that local state can be stale, not proof of current open exposure. Four clearly marked paper trades were excluded from all above numbers.89local trade records and32entered-signal keys were not treated as84verified fills. Public GitHub JSON with receipt-like identifiers can still be edited by its publisher; independent arithmetic cannot establish authenticity or account ownership.

The reported$81.22 elsewhere differs from the exact bounded receipt result by$3.086. This review does not resolve that outside figure and does not replace it silently. Account-wide return, ROI, bankroll adequacy, uptime and executable future profitability remain unknown.

Suggested owner wording: “The strongest public lead we found publishes84fill records and31settlements that reconcile internally to+$78.13 after$16.27fees. We independently checked that arithmetic. We have not authenticated the account, established a complete history, or shown that its current strategy repeats the result.”

Reproduction: own `independent_receipt_audit.py`; all31 market-level comparison results in [independent arithmetic](J0SHUSMC_INDEPENDENT_RECHECK.json). No account calls, trades, sealed TEST, third-party execution or repository mutation.

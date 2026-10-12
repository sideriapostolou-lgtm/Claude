# Public history audit: collection in progress

Public proxy wallet: `0xc53375ff94e96100f2b30a4b5775db35218d69a9`
(`dangerously-skip-permissions`). Initial public reads: 2026-10-12 21:33 UTC.
This is an accounting/history audit, not strategy training or a tradable backtest.

The $100 starting-bankroll claim is **not verified**. An ascending public activity
request with `start=1` and `exclude_deposits_withdrawals=false` first returned a
**$4,000 DEPOSIT on 2026-07-17 14:00:46 UTC**, followed by a first trade at
14:16:18 UTC. These are the earliest rows returned by that API query, not yet
proof of the wallet's first on-chain funding or its owner's complete bankroll.
Full API pagination is in progress. An independent public Polygon audit now
confirms the $4,000 receipt: the official Deposit Wallet Factory created this
wallet at **2026-07-17 13:58:39 UTC** (block 90394481); the funding transaction
at block 90394566 routes 4,000 USDC.e through the official collateral onramp and
mints 4,000 pUSD to the wallet. Archived pUSD balances are zero immediately
before that deposit and 4,000 immediately after it. This supports a $4,000
observed-wallet opening balance, not a verified $100 start or a person's whole
bankroll. The first trade receipt confirms 84 shares at 53c: $44.52 plus $1.4647
fee, or $45.9847 total cash debit.

Independent funding evidence and limitations: `/tmp/skipwatch-chain-audit/FUNDING.md`;
reproduce the public receipt reads with `history_chain.py`. The deposit receipt is
`0x57477a6c5ad1ce33f8b3b66067be8b94555c53e3314c997b21e4288769ceac13`.
The audit did not scan all Polygon genesis history: public RPC log queries are
limited to 10,000-block ranges, and explorer challenge pages were not bypassed.
It does not establish other wallets, earlier destroyed contracts, all assets or
the ultimate source of this capital. Token transfers and collateral wrapping
remain funding, never trading profit.

The [official Data API v2 schema](https://data-api.polymarket.com/v2/openapi.json)
exposes materially different P&L columns. Its latest returned daily-series point,
**2026-10-12 20:46:21 UTC**, reports:

| Official field | USDC | Meaning |
|---|---:|---|
| `trade_pnl` | 281,602.16 | Compatibility chart series, with fee charges added back |
| `fees` | -183,856.59 | Cumulative fee disclosure |
| `realized_pnl` | 97,666.87 | Realized position result |
| `unrealized_pnl` | 78.71 | Marked open-position result |
| `position_pnl` | 97,745.58 | Realized plus unrealized position result |
| `wallet_income` | 41,514.04 | Maker/taker rebates and other credited income |
| `economic_pnl` | 139,259.61 | Position result plus wallet income |

The social-post figure around $279,000 is compatible with the chart's gross-trade
series, but its provenance is not established. It must not be called verified
after-fee economic profit. **Do not subtract the disclosed fees again** from
`position_pnl` or `economic_pnl`. Funding is separate from profit. The P&L
response's deposits/withdrawals/cashflow fields are null, which means uncovered,
not zero. Its 88 cumulative points have daily historical source fidelity;
requesting a finer output grid cannot create intraday evidence.

**Reconciliation is unresolved:** the completed activity walk reports materially
more credited rebates than the P&L series. The series' `wallet_income` stays flat
on every day from September 12 through October 12, while activity reports daily
credits; August 25 also disagrees. The discrepancy is approximately $56,000 and
cannot be explained by the differing fifty-minute request cutoffs. Selected
public rebate receipts are being checked independently. The $139,259.61 above
is therefore an official field value, **not independently reconciled all-income
profit**. The same limitation applies to risk statistics derived from that curve.

Initial evidence is saved outside git in `/tmp/skipwatch-history-initial/`:
`activity-first.json`, `trade-recent.json`, `pnl-daily.json`, `value.json`.
These small probes do **not** establish complete history, daily cash balances,
intraday drawdown, complete fee attribution, maker share, or returns achievable
with a $100 account. The initial portfolio-value response is a holdings mark,
not cash or the whole bankroll.

Full-history collection will freeze a request cutoff, follow every official
cursor, retain raw pages and their digests, report retries and coverage limits,
and separately account for transfers, trading and income. No real orders,
private account reads, credentials or production settings are used.

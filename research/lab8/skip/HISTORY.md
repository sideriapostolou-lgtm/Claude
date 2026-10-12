# Public wallet history audit — 2026-10-12

Wallet: `0xc53375ff94e96100f2b30a4b5775db35218d69a9`
(`dangerously-skip-permissions`). This is a public accounting/history audit, not
strategy training, a tradable backtest, or evidence of returns available to us.

The available public API history is fully paginated through **2026-10-12
21:37:01 UTC**. It contains **535,592 fills** beginning **2026-07-17 14:16:18
UTC**. The first indexed funding is independently confirmed as **$4,000**, not
$100. The official chart's **$281,602.16** is a compatibility trade series;
its reported economic P&L is **$139,259.61**, but that figure does **not** reconcile
with independently observed income. Credited activity income exceeds the
provider aggregate by **$55,985.3012**. A separate cash reconciliation leaves
**$3.771930 unexplained** after one extra TIP-associated debit. Therefore this
audit does not certify a precise all-income net profit, an exact worst day,
or any expected return for a $100 account.

## Coverage and accounting boundaries

The [official Data API v2 schema](https://data-api.polymarket.com/v2/openapi.json)
and [migration guide](https://docs.polymarket.com/migrate/data-api-v1-to-v2.md)
define the current public endpoints. Each query fixes the same wallet and end
timestamp, starts at `1`, and follows every cursor to its terminal response.
No market filter restricts this history. Requests are spaced by at least one
second, with bounded retries and respectful numeric/HTTP-date `Retry-After`
handling. These four walks required no retries or rate-limit responses.

| Public stream | Pages | Rows | Terminal cursor reached |
|---|---:|---:|---|
| Activity, funding explicitly included | 559 | 558,293 | Yes |
| TIP, explicitly requested because default activity omits it | 1 | 1 | Yes |
| All trades, `taker_only=false` | 536 | 535,592 | Yes |
| Taker trades, `taker_only=true` | 304 | 303,703 | Yes |
| Historical pUSD balances plus actual block headers | 88 points | 88 | Yes |

The activity trade rows and independent all-trades stream match exactly as an
economic multiset: **zero unmatched rows in either direction**. Every taker row
belongs to that all-trades multiset. Pagination retains identical-row
multiplicity; a wallet trade lacks a unique public per-fill log ID, so blindly
collapsing identical economics could erase real fills. No extra identical
activity trade rows were found in this capture. Profile/Gamma enrichment is
excluded from economic identity. Saved-page digests, frozen query parameters,
URL cursor chains, row counts and final completion state are checked on replay.

Trades explicitly request a tiny positive token filter (`0.000000001`) to avoid
the endpoint's default 0.01 floor. Completeness means all rows returned by these
queries at the recorded capture, not an independent proof that the indexer
exposes every chain event, eventual correction or smaller-than-filter amount.
The historical P&L was captured separately; its final point is **20:46:21 UTC**.
The later 50 minutes 40 seconds of activity are kept separate from comparisons
with that point: 178 fills, $2,477.196636 purchases and $2,424.615562 redemptions.
A holdings-value response is not cash or whole-bankroll value.

Official wallet activity/trade timestamps are **block timestamps**, not
verified order-decision or CLOB execution times. These data cannot establish
historical quote availability, latency, queue position, canceled/unfilled orders
or a causal entry trigger. No historical fitting is authorized by this audit.

## Funding and the $100 claim

The official Deposit Wallet Factory created this wallet at **2026-07-17
13:58:39 UTC**, block **90394481**. First indexed funding follows at **14:00:46
UTC**, block **90394566**. Its independently retrieved receipt routes 4,000
bridged USDC.e through the official collateral onramp and mints **4,000 pUSD**
to the wallet. Archived pUSD is zero immediately before that deposit and 4,000
immediately after it; bridged USDC.e and native USDC are zero at those checks.
The source wallet's initial observed funding is therefore $4,000. This neither
establishes its owner's whole bankroll nor disproves a $100 start elsewhere.

The first trade, **14:16:18 UTC**, independently debits **$45.984700**: 84 shares
at $0.53 ($44.52) plus $1.4647 fee. The activity cash value includes that fee;
adding it again would double count it. Wrapping/minting cash collateral,
deposits, withdrawals and position redemptions remain distinct from profit.

Full indexed funding comprises **two deposits totaling $4,218.52** and
**16 withdrawals totaling $173,843.00**. All 18 amounts were independently
matched to successful pUSD receipt transfers. The separate $2.15 outgoing TIP
receipt debits $2.235780 in total; the additional **$0.085780** is an observed
cash outflow whose purpose is not established here.

A complete Polygon genesis transfer scan was not performed. The public RPC
limits log reads to 10,000-block ranges; roughly 9,040 ranges per filter would
be needed to reach the first deposit from genesis. Explorer challenge pages
were not bypassed. Factory/code and archived-balance evidence support the stated
opening, but do not enumerate all assets, earlier destroyed contracts, other
wallets/chains or ultimate capital sources. API funding is fully paginated;
all-chain economic completeness remains unproved.

## P&L, credited income and cash do not fully reconcile

At **2026-10-12 20:46:21 UTC**, official source block **95421794**:

| Official cumulative field | USD-equivalent | Interpretation |
|---|---:|---|
| `trade_pnl` | 281,602.163902 | Compatibility chart series, fee charges added back |
| `fees` | -183,856.588530 | Fee disclosure; not another deduction below |
| `realized_pnl` | 97,666.867780 | Provider's realized position result |
| `unrealized_pnl` | 78.707592 | Provider's marked open-position result |
| `position_pnl` | 97,745.575372 | Realized plus unrealized position result |
| `wallet_income` | 41,514.036300 | Provider's credited-income aggregate |
| `economic_pnl` | 139,259.611672 | Position result plus reported wallet income |

The schema defines `trade_pnl` as `position_pnl - realized_lp_pnl +
fees_charged - fees_refunded`; it is not the after-fee economic figure. The
social figure around $279,000 is compatible with that chart, but the post's
provenance is not established. Do not subtract disclosed fees again from
position/economic P&L. Deposits, withdrawals and cashflow fields in this P&L
response are **null**, not zero.

Through that same endpoint timestamp, the separate activity ledger reports:

| Income type | Activity credits | Provider P&L component |
|---|---:|---:|
| Maker rebates | 11,320.406100 | 7,557.058200 |
| Taker rebates | 85,134.588600 | 32,929.434600 |
| Rewards | 1,044.342800 | 1,027.543500 |
| Total | **97,499.337500** | **41,514.036300** |
| Difference | **55,985.301200** | Unreconciled |

The provider's wallet-income curve is flat on August 25 and every day from
September 12 through October 12 despite indexed credits. Three representative
credits were independently confirmed as incoming pUSD receipt transfers:
September 12 **$2,456.2378**, October 9 **$3,392.7149**, and October 12
**$94.2202**. This establishes real credits absent from the aggregate; it does
not validate every income receipt individually or justify an invented reason
for the provider discrepancy.

At the exact latest source block, the archived pUSD cash balance is
**$26,458.900105**. Its actual block header timestamp exactly matches the
20:46:21 series timestamp. API cashflow through that timestamp reconstructs
**$26,462.757815**: trading cash $98,590.050315, external funding including the
reported TIP -$169,626.630000, and credited income $97,499.337500. This exceeds
the chain balance by **$3.857710**. Accounting for the TIP's extra $0.085780 debit
leaves **$3.771930 unresolved**. Coarse block-second timestamps do not resolve
same-second transaction ordering; the residual is not assigned to that or any
other explanation without evidence.

Trading cashflow and the provider position curve also differ. Simply adding
the missing $55,985.3012 to the provider's economic P&L would imply precision
this reconciliation does not support. The archived cash is one public wallet's
pUSD at a stated block, not current cash, the owner's cash, a portfolio mark,
or a whole-bankroll balance.

## Daily record and risk limits

[HISTORY_daily.csv](HISTORY_daily.csv) contains all **88 observations**: provider
realized and unrealized P&L changes, marked economic changes, fees, activity
cash by category, source block, verified archived pUSD cash, both timestamps,
and reconciliation residuals. Amounts are differences of cumulative official
fields; fees are disclosed once. Funding is kept separate from trading cash.
The daily file preserves the unadjusted API residual; the additional
TIP-associated debit and remaining residual are explained above.

Daily-grid timestamps are not always their underlying block timestamps. The
July 29 point references a block **86,401 seconds earlier**; the August 24
point is **19,416 seconds earlier**; the September 12 point is 2,402 seconds
earlier. Other lags range from seconds to minutes. Consequently
`complete_grid_day=true` identifies a full reported grid interval, **not a
certified exact UTC-day return**. Historical cash is measured at the actual
block header, and its cashflow comparison uses that block's time. The first
inception interval and current partial day are labeled separately.

The unreconciled provider curve has 86 full daily-grid intervals: **75 positive,
10 negative and one flat**. Its worst full reported grid interval is
**September 21, -$965.687955**. Its largest daily-grid drawdown is
**$1,735.634788**. The current October 12 partial grid interval is
**-$1,303.666552**, excluded from the full-day comparison. These are properties
of the unreconciled provider curve; missing credits and source-clock staleness
prevent certifying them as actual net worst-day or drawdown results.
**Intraday equity drawdown, complete bankroll risk, and exact daily net P&L
remain unknown.** The verified cash series alone cannot provide those because
funding movements, positions and income timing affect cash independently.

## Observed behavior and scaling

All 535,592 indexed fills are BUY rows: **517,089 BTC five-minute fills** and
**18,503 ETH five-minute fills**, across **24,225 distinct market conditions**.
The ETH activity spans August 26 to September 10; a latest-page BTC-only sample
would miss that episode. There are 22,486 redemption rows. Other activity is
85 maker rebates, 86 taker rebates, 26 rewards, the two deposits, 16 withdrawals
and one opt-in TIP. No observed SELL rows does not establish that no orders
were submitted or canceled outside these fills.

Official taker-only pagination reconciles to **303,703 taker fills (56.70%)**;
the remaining **231,889 (43.30%)** are maker fills by the documented cohort
complement. These are fill-count shares, not volume, resting-order fill rates,
or inferred roles from public trade direction. Both cohorts are significant.
Monthly taker fill share rises from 43.61% in partial July to 54.08% in August,
55.94% in September and 64.97% in partial October.

Across all markets, median fill size is **20 shares**, 90th percentile **72.83**,
and maximum **200**. Median reported purchase cash is **$8.30** per fill;
90th percentile **$38.19**, maximum **$181.26**.

For **21,306 closed BTC five-minute windows** (the current incomplete window is
excluded), **18,866 (88.55%)** buy both outcomes. Median purchase cash per window
is **$237.79**, 90th percentile **$892.89**, maximum **$3,844.66**. Median fills
per window are **17**, 90th percentile 57, maximum 212. Median share imbalance,
`abs(up-down)/(up+down)`, is **21.46%**: buying both outcomes does not imply a
balanced or locked position.

| BTC month | Traded windows | Both outcomes | Median purchase cash/window | Median fills/window | Median share imbalance |
|---|---:|---:|---:|---:|---:|
| July, partial | 2,699 | 67.32% | $85.60 | 5 | 53.35% |
| August | 7,583 | 86.56% | $176.38 | 14 | 22.68% |
| September | 8,006 | 95.07% | $360.98 | 24 | 17.85% |
| October, partial | 3,018 | 95.23% | $397.49 | 26 | 17.65% |

For windows buying both outcomes, the sum of each outcome's weighted-average
reported purchase cash per share has median **$0.996575**, and is below $1 in
**51.60%** of windows. October's median is **$1.016883**, with only **41.37%**
below $1. These purchase-cost statistics include reported purchase cash and
precede later rebates. They are not a reconstructed locked-pair profit series,
proof of queue-accessible arbitrage, or a per-window allocation of income.
Scaling, more balanced buying and the changing maker/taker mixture are observed
behavior changes; they do not identify a private code change or its cause.

## What is supported at a $100 size

The observed wallet starts with $4,000 and scales materially. **15,965 of 21,306**
closed BTC windows spend over $100 on purchases; its largest single fill exceeds
$100. A $100 account cannot reproduce these observed purchase sizes unchanged.
That gross cash requirement is not identical to maximum risk or margin needed
under every possible position-management scheme.

No credible dollars-per-day forecast or return percentage at $100 follows from
this history. Linear scaling ignores queue priority, fragmented fills, fee
rounding, rebate eligibility, latency, changing balance between sides and
available liquidity. Public fills reveal neither missed orders nor the signal
before an execution. Polymarket international five-minute behavior also does
not establish performance on Kalshi fifteen-minute markets. Practical transfer
requires prospective observations and honest venue-specific simulation, with
funding, rebates, realized results and marked exposure accounted separately.

## Reproduction, artifacts and checksums

Implementation: `history.py` (fixed public pagination and replay),
`history_analysis.py` (Decimal cash accounting and cohort/window summaries),
`history_balances.py` (historical pUSD plus block headers), and `history_chain.py`
(narrow public Polygon receipt/state reads). No credentials, private account
APIs, order clients, real orders or production settings are used.

```bash
python research/lab8/skip/history.py pull --directory /tmp/skipwatch-history-repro
python research/lab8/skip/history_balances.py \
  --pnl /tmp/skipwatch-history-repro/pnl-daily.json \
  --directory /tmp/skipwatch-history-repro/balances
python research/lab8/skip/history.py summarize --directory /tmp/skipwatch-history-repro
```

A fresh directory chooses a new request cutoff; replaying the saved directory
preserves this audit's cutoff. Live public data may be corrected later. The
raw capture remains outside git in `/tmp/skipwatch-history-20261012/`: frozen
`request.json`, four stream directories with gzipped raw pages and manifests,
`pnl-daily.json`, `value.json`, `balances/`, `summary.json` and `daily.csv`.
Each raw page preserves URL, request/receipt time, response and its manifest
digest. The small daily CSV is checked into this research folder; large public
raw files are local session artifacts and require deliberate retention if the
workspace is replaced.

| Artifact | SHA256 |
|---|---|
| Activity manifest | `4cf8f8cdac48d79c9d84bc90da4405393d03c055f981fae66ddc094a60b5010f` |
| All-trades manifest | `3f8deb75d4b095651ba2cfd1677b55ef8c7f41c13a6279859ddfe0d26e896879` |
| Taker-trades manifest | `5bbf8b9deaf781663d9977502e21bb848582e74ec79014a8e4144ac4daf4aa0b` |
| TIP manifest | `b884665355d2eac14619d50d1f5d4e627c7b25e1594b8ca4f08e85f32bf6cf93` |
| Original P&L response envelope | `04e249a55a95d64b8ed6e1c215a0cf171cbb911360be41047539a5c840d3fa91` |
| All 88 archived cash points | `5fa8a823948ce2dd61472bc68675fbbf1e66a0483acabc764897f5443d338da9` |

Independent chain evidence is under `/tmp/skipwatch-chain-audit/`:
`FUNDING.md`, `repro/`, `funding-all/reconciliation.json`,
`REBATE_RECONCILIATION.md`, `rebates/`, and `sourcepoint-header/`.
The funding and rebate memos contain request manifests, transaction identities,
limitations and response digests. Contract identities come from the
[official contracts reference](https://docs.polymarket.com/resources/contracts.md).
Public RPC: `https://polygon.drpc.org`.

Key independently checked transactions:

- Opening deposit: `0x57477a6c5ad1ce33f8b3b66067be8b94555c53e3314c997b21e4288769ceac13`.
- First trade: `0xb6d7b711d2fe4ffe267decea2cf590fa68fa9960294540f869fb289078cdcfba`.
- September 12 rebate: `0x1e19fff34f917aca81bdecc1a6727ae662e316b5bd8c8f9faa521f865e8de20d`.
- October 9 rebate: `0xbaecd939fbb038ec113835cec9486e9a0fedb098eb5f541695c8c9395e52f5d2`.
- October 12 rebate: `0x4fcc24d28e467ef0d042d48187066a5182d7b7481f51e46df8c130cc815b716d`.
- TIP and its additional debit: `0x37614ef652350fcb772cf82aca297fedab5eda75671819c6d0e50cdcd1a80fa7`.

Research validation covers pagination/resume integrity, retries, duplicate-row
multiplicity, cash-versus-funding classification, nullable P&L and fee treatment,
TIP integration, cohort reconciliation, historical cash timing and constrained
public chain reads. Remaining accounting gaps are explicit findings, not passed
off as resolved by a successful test suite.

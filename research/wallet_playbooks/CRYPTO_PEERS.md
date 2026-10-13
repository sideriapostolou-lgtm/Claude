# Five public wallets: fresh reconstruction, October 13, 2026

I made 25 public requests at approximately 18:57–18:59 UTC: two pages of 500 all-fills rows, two pages of 500 taker-only rows, and the daily P&L chart for each of five predetermined wallets. Exact URLs, timestamps and hashes are in `evidence/crypto_peers/requests.json`; raw responses and calculated summaries are alongside. Larger JSON responses are stored losslessly as `.json.gz`. No orders or account access. The exploratory plan preceded collection (`evidence/crypto_peers/plan.json`).

## Limits of these measurements

Chart amounts are the provider's displayed cumulative P&L at October 13, 18:00 UTC. They are not independently reconciled cash, returns on bankroll or proof of no external hedges. Funding and rebates were not reconstructed here.

The API's live offset pagination shifted between requests. I removed exact repeats across pages (mo-money: 3; GoodFallen: 35; DB5: 2), while retaining within-page multiplicity (rwo has one unresolved repeated identity). Taker fractions use multiset matches on transaction hash, asset, direction, size, price and timestamp. The taker pages span the corresponding all-fills samples. Maker fraction is inferred from API membership, not private order receipts; the fetches are not atomic.

A covered window has its nominal open and close strictly inside the sample's timestamp range. This removes boundary windows, but cannot prove all pre-open inventory is included. Pair cost sums the two buy VWAPs in a covered window without sampled sells: before fees and rebates, not achieved net profit. Imbalance is `abs(up-down)/(up+down)`, unlike the older scout's larger-side denominator. Public timestamps are not actual exchange decision timestamps. No millisecond reaction is established.

## Observed facts

| Wallet | Displayed P&L | Fresh signature |
|---|---:|---|
| ce25 `0xce25e214d5cfe4f459cf67f08df581885aae7fdc` | $699,742.80 | 1,000 fills, October 13 14:18–18:49 UTC. All buys; 95.3% taker; median 12 shares at 46c. Both sides in 89/126 covered windows; median pair VWAP 93.52c, 60/89 pairs under $1; median both-side imbalance 12.73%. Median 4 fills and $19.46 buy cost per covered window. Last-minute fills: 2.83%. |
| mo-money `0x32ed2e546b187ca15e2841edc82b22c713cf8ec3` | $504,405.16 | 997 fills, October 13 09:38–18:51. All buys; 15.05% taker, about 84.95% maker. BTC 5m is 52.9% of notional, BTC 15m 25.7%. Both sides in 64/129 covered windows; median pair 99.35c, 34/64 under $1; median both-side imbalance 7.74%. Median 3 fills and $82.85/window. Last-minute fills: 15.02%. |
| GoodFallen `0x0ca4e9d27ff826a109ecbf74754fb66b93f277a6` | $167,725.08 | 965 fills, October 13 17:27–18:52. All buys, all BTC 5m, 77.10% taker. Both sides in 16/16 covered windows; median 25 shares at 49c, 43 fills and $449.52 buy cost/window. Median pair 99.70c; only 8/16 under $1. Median imbalance 6.71%. Last-minute fills: 3.97%. |
| DB5 `0xdb5ad26b68d77ae966d29e7180147272ab7a3965` | $194,434.38 | 998 fills, October 12 21:44–October 13 18:50. Sells are 43.89%; takers 47.70%. 90 markets, with both buys and sells in 41. Terminal above-strikes are 74.35% of notional, bands 11.36%, touches 14.14%. Buy dollars are 52.56% YES and 47.44% NO; 76.18% of buy dollars paid at least 90c, despite a count-median buy price of 22c. |
| rwo `0xd189664c5308903476f9f079820431e4fd7d06f4` | $775,327.06 | Latest 1,000 rows stretch from August 9 through October 9, not today's active trades. 24.6% taker and 0.2% sells. Both sides in 71/101 covered windows; median pair 100.68c, 32/71 under $1. Chart September change: -$215.38; October through 13: +$5.00. |

## Concrete playbook hypotheses

### GoodFallen: the closest fresh skip-bot peer

**Best guess:** repeatedly estimate BTC's short-window probability, buy whichever side is cheap relative to that estimate, and tilt purchases toward the side with less inventory. Take fleeting bargains aggressively, while leaving some maker bids. Most accumulation occurs before the final minute; hold the acquired positions rather than selling them. The repeated 25-share median is a fill-size signature, not proof of a 25-share order setting.

Confidence is medium for this strategy family and low for exact triggers. All 16 covered windows contain both sides, and inventory is fairly balanced. But eight have combined side VWAPs at or above $1 before fees. That excludes a guaranteed profitable whole-window portfolio at these aggregate costs; it does not identify costs of specific matched lots. If its displayed profits are economically real, directional timing, rebates or other accounting matter too.

**Distinguishing test:** does he buy the newly favored side after an exchange BTC move but before the CLOB reprices, then buy the opposite side on a reversal? Compare this against a plain inventory-adjusted maker using receipt-timed feeds and sequenced books. Block timestamps cannot answer the speed question. Fragmented fills could also make a few orders appear to be dozens of independent decisions.

### ce25: a sparse taker accumulator across several cryptocurrencies

**Best guess:** a fair-value or momentum signal across BTC, ETH, SOL and XRP, with opportunistic pairing after relative probabilities change. It buys small repeated clips, often both sides, and mostly avoids the last minute. Today's 95.3% taker share is materially different from the old scout's approximately 64%; do not treat that old ratio as a permanent rule.

Its 70.6% both-side rate and 93.52c median pair support opportunistic pair formation, but 29.4% one-sided windows and 32.6% pairs at or above $1 contradict pure arbitrage. Confidence is medium for the family, low for the exact model.

**Distinguishing test:** compare a standardized distance-to-strike plus 1/5/30-second returns model against the same model with opposite-side acquisition cost. Does prior inventory improve predictions? Compare assets to distinguish individual fair-value models from a common momentum factor. Freeze causal timing before fitting.

**Counterevidence:** chart gains fell from $212,120 in May to $65,575 in September; October through 13 adds $8,746, a partial month. Today's median sampled cost of about $19/window cannot alone explain the historical $699k. Turnover, funding, prior sizes, rebates and the whole ledger remain necessary.

### mo-money: predominantly passive fair-value pricing

**Best guess:** rest buy quotes across related crypto expiries, reprice them around a probability estimate, and tilt those quotes for inventory. Capture spread when other traders cross the quotes, with residual directional exposure and possible rebates. Confidence is medium for the family, low for the unobserved cancel policy and quote grid.

Approximately 85% maker fills and a 99.35c pair median fit this explanation. But about half of covered windows are one-sided, and nearly half of the paired windows cost at least $1, so a mandatory under-$1 pair rule is inadequate.

**Distinguishing test:** estimate post-fill markouts at 1/5/30 seconds and settlement using true execution timing. Do maker fills come from temporarily mispriced liquidity, or are they adversely selected with rebates making up the loss? Public fills cannot show unfilled orders or our hypothetical queue position. The selected winner's $504k chart is not proof a copy can earn it.

### DB5: trade an implied probability surface across ladders

**Best guess:** fit a common BTC/ETH terminal-price distribution and quote above-strikes and between-strike bands against it. Buy cheap probabilities, sell rich ones, and hedge some correlated exposure across strikes. Confidence is medium for this family and low for the exact advantage.

With matching expiry, settlement source and boundary rules, `P(a<S<=b)=P(S>a)-P(S>b)` gives a consistency relation. Touch contracts require a separate path-dependent model; never apply terminal-price identities to them. The observed mix of buys, sells, YES and NO contradicts a simple NO-only hold strategy.

**Distinguishing test:** estimate a smooth common distribution from neighboring contracts, excluding the target fill, and test whether purchases and sales follow residual signs after fees. Compare against a trend-following alternative. Prior inventory is needed to classify exits. Its June chart lost $3,620 and worst daily change was about -$14,897, so this is not riskless arbitrage.

### rwo: a historical success and a useful decay control

The historical pattern resembles passive balanced crypto accumulation, with roughly 75% makers. But the last fill is October 9; September lost $215 and October is nearly flat. Ranking it as an active winner using its $775k lifetime headline would be misleading. Its sampled pair median above $1 also contradicts a simple cheap-pair explanation.

Investigate when it stopped participating and whether that coincided with changed fees or competition. Inactivity alone does not identify the cause.

## Public sources

For wallet W, the exact expanded links are preserved in `evidence/crypto_peers/requests.json`:

- `https://data-api.polymarket.com/trades?user=W&takerOnly=false&limit=500&offset=0`
- `https://data-api.polymarket.com/trades?user=W&takerOnly=true&limit=500&offset=0`
- `https://user-pnl-api.polymarket.com/user-pnl?user_address=W&interval=all&fidelity=1d`
- `https://polymarket.com/profile/W`

Earlier scout references: `research/lab9/scouts.json`, `leaderboard/stage_a.csv` and `leaderboard/final_records.json`. Current bounded observations differ from some older samples; report the observation window instead of treating either as a lifetime statistic.

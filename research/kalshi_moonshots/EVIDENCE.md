# Primary-source checks and bounded public sample

Checked 2026-10-13 UTC. Public GETs and official documentation only; no credentials, authenticated
subscriptions, orders or paid data. [Snapshot](public_sample.json) and [arithmetic](arithmetic.json).
This is schema/liquidity research, not a backtest. No sampled settlement outcomes were scored.

## Current contract facts

Public metadata for `KXBTC15M`, `KXETH15M`, `KXSOL15M`, `KXXRP15M`, sampled markets ending
`-26OCT131000-00` (13:45–14:00 UTC):

| Series | CF index | Settlement value precision |
|---|---|---:|
| BTC | BRTI | 2 decimal USD |
| ETH | ETHUSDRTI, feed identifier ETHUSD_RTI | 2 decimals |
| SOL | SOLUSDRTI, feed identifier SOLUSD_RTI | 4 decimals |
| XRP | XRPUSDRTI, feed identifier XRPUSD_RTI | 4 decimals |

The final-minute mean is compared with the pre-opening-minute mean; ties pay YES. Read the exact strike
from each contract. `close_time` and lifecycle state control tradability, not expected settlement or the
later expiration timestamp. All sampled markets permit early closure. Source example:
[BTC market](https://api.elections.kalshi.com/trade-api/v2/markets/KXBTC15M-26OCT131000-00),
[contract terms](https://assets.kalshi.com/contract_terms/CRYPTO.pdf).

Current price bands: $0–.10 in $.001 increments, $.10–.90 in $.01 increments, $.90–1 in $.001 increments.
Preserve per-market band metadata. Four-decimal wire prices do not imply every four-decimal number is valid.
Books/prints contain fractional quantities; documented quantity granularity is .01 contracts. Additional
minimum-spend/order restrictions were not tested by submitting an order.
[Fixed-point documentation](https://docs.kalshi.com/getting_started/fixed_point_migration).

Sampled series use `quadratic`, multiplier 1. Queried fee-change lists/event overrides supplied no
exceptions, and the current schedule lists none for these 15-minute series: current maker fee zero,
taker coefficient .07. Recheck each time; this is not a permanent promise. Direct-account fees use the
current precision/accumulator rules, and sales can incur fees too. No settlement fee.
[Schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf),
[rounding](https://docs.kalshi.com/getting_started/fee_rounding).

## Useful index feeds, not yet verified on our account

[One-second feed](https://docs.kalshi.com/websockets/cfbenchmarks-value): authenticated raw index updates
plus averages. Trailing average excludes the current tick; final-quarter-hour accumulation includes the
close tick. Preserve counts/boundaries and compare with actual settlement. `indexlist` must confirm
availability; ACK alone is insufficient.
[Five-Hz feed](https://docs.kalshi.com/websockets/cfbenchmarks-value-5hz): faster raw predictors, no averages.
[Historical passthrough](https://docs.kalshi.com/cfbenchmarks/rest-passthrough): authentication/entitlement
required, 50 read tokens/request. No entitlement check was made. Public event chart data is not verified
as the raw settlement sample and cannot silently substitute.

## Fixed current-book sample

The delegated sample used 26 sequential public API requests with at least .55 seconds between completed
requests. Four series and nearest open windows were selected before looking at their books. These
snapshots differ in time; none is a standing offer.

| Coin | Book received UTC | Cheaper outcome | Ask | Size at ask | Same-side bid |
|---|---|---|---:|---:|---:|
| BTC | 13:48:43.800 | NO | $.41 | 2,237.12 | $.40 |
| ETH | 13:48:46.608 | NO | $.39 | 1,020.83 | $.38 |
| SOL | 13:48:49.899 | NO | $.35 | 460.01 | $.34 |
| XRP | 13:48:53.073 | NO | $.42 | 450.63 | $.41 |

**No ask <=1¢** on either side in these four early-window snapshots. The responses had no book event
timestamp; HTTP Date/receipt time does not prove quote freshness. Public books contain bids for both
outcomes: own ask derives from one minus opposite bid; an exit consumes own bids.
[Book endpoint](https://docs.kalshi.com/api-reference/market/get-market-orderbook).

## Fixed previous-window prints

The preceding 13:30–13:45 window was selected by clock, not outcome. Its extension plan was written
13:49:56.252, before the first request at 13:49:56.305. Only the latest 1,000 non-block prints per coin were
read; all responses had more pages. These are incomplete late-window samples, not random observations.

| Coin | Prints with an outcome <=1¢ | Prints exactly 0.1¢ on one outcome | Quantity printed at <=1¢ |
|---|---:|---:|---:|
| BTC | 1,000 | 435 | 414,221.48 |
| ETH | 80 | 19 | 21,550.32 |
| SOL | 263 | 31 | 10,555.01 |
| XRP | 176 | 9 | 9,085.79 |

Every print has complementary outcome prices. These counts do not establish opening purchases, bot
identity, the quantity we could obtain, independent bets or profitability. They establish that these
prices occurred. [Public trade API](https://docs.kalshi.com/api-reference/market/get-trades).

## History limitations

Public historical cutoff at lookup was August 14 for market/trade history. An arbitrary August 13 BTC
window returned archival prints. The four previous windows each had 15 one-minute candles with bid/ask
OHLC but no depth/queue. A high and low in one candle do not establish which came first or a round-trip
fill. No documented public full-depth historical book archive was established.
[History tiers](https://docs.kalshi.com/getting_started/historical_data),
[archival prints](https://docs.kalshi.com/api-reference/historical/get-historical-trades),
[candles](https://docs.kalshi.com/api-reference/market/get-market-candlesticks).

We need prospective sequenced books and correctly timestamped index/spot data to test this execution
story. The snapshot retains source URLs, timestamps and aggregate evidence; long rule text is represented
by a fingerprint and source URL rather than copied into the report.

## Our execution speed is not established as competitive

Claude's 14:00 UTC WORKLOG entry reports a small 13:34–13:45 live sample (7–8 observations): median
tick-receipt-to-decision 509ms and decision-to-ack 1,173ms. This is attributed operational evidence, not a
fresh Railway check in this session or a reliable p99 estimate. PR #27, merged while this report was being
written, changes state-save performance; its resulting timing is not yet verified here. The strategy
must measure the current complete latency distribution and quote survival, not assume colocated speed
or treat a fast HTTP ping as an order round trip.

## Relevant academic evidence, with a major scope limit

[Bürgi, Deng and Whelan's Kalshi working paper](https://www2.gwu.edu/~forcpgm/2026-001.pdf) finds that
low-priced outcomes in its historical sample tended to be overpriced, especially for takers. Its data
ends April 2025 and explicitly excludes markets open less than 24 hours. Therefore it does **not** test
this modern subcent 15-minute strategy. It supports skepticism toward buying merely because a contract
is cheap, not a claim that the proposed signal cannot work.

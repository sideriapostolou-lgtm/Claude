# LucasMeow: full public-history audit and observable rulebook

Public wallet: `0x7f3c8979d0afa00007bae4747d5347122af05613`. Captured 2026-10-12, fixed activity/trade cutoff **22:25:02 UTC**. This is descriptive source research, not a fitted strategy, a Kalshi backtest, or permission to trade.

**Verdict:** the high-priced, far-strike NO pattern is real in this history. Its exact private trigger, capital limits and resting-order logic are not recoverable from fills. The wallet is much larger and less uniform than the scout suggested. It also sold, bought YES, traded SOL and politics, and received substantial outside funding. The full wallet's profit cannot all be attributed to the selected monthly BTC/ETH rule.

## 1. What was actually collected

| Public evidence | Coverage at this capture |
|---|---:|
| v2 activity, deposits/withdrawals explicitly included | 8,520 rows; 9 pages; cursor exhausted |
| Separate opt-in TIP activity | 0 rows; terminal page |
| All maker+taker trades | 8,043 fills; 9 pages; cursor exhausted |
| Taker-only trades | 338 fills; terminal page |
| Rich v2 daily P&L | 594 points, including the current partial endpoint |
| Legacy user-pnl-api daily chart | 594 points; captured separately, retained without treating it as cash |
| Gamma event/rule metadata | All 70 traded events; 223 traded conditions |
| Historical cash | 25 monthly source-block snapshots, October 2024–October 2026, three distinct token contracts |
| Indexed funding receipts | All 75 deposits and 19 withdrawals inspected through public Polygon RPC |
| Coinbase hourly BTC/ETH candles | 14,985 distinct hours each in the source-fill feature range; 10 missing hours each |

All history cursors reached their declared terminal page, with no recorded retries or 429s in the four walks. This is **complete for the available public index and requested size floor** (`0.000000001` token), not independent proof that every possible on-chain fill is indexed. The fixed cutoff limits new rows; the APIs do not provide an immutable snapshot.

Activity and trade endpoints match one-to-one on transaction, timestamp, side, token, condition and price, preserving duplicate multiplicity. **19 fills disagree on shares**: activity reports a larger size than `/trades`. These are not silently deduplicated or made equal. Cash and purchased-share statistics use the activity record; maker/taker matching uses the exact `/trades` identity. A fee/net-share explanation is plausible but was not independently proved for all 19 events. All 338 taker fills match the all-trades multiset.

Current Gamma metadata is a later snapshot, not evidence of what the wallet knew at order entry. A NO result is called resolved only when Gamma reports `umaResolutionStatus=resolved`, `closed=true` and an exact 0/1 outcome price. We did not independently replay the international venue's oracle settlement transactions.

## 2. The observed rule, with its limits

The selected cohort is **BTC or ETH, calendar-month touch ladders, BUY NO**. Annual, quarterly, Solana, ordinary terminal-price and political markets are outside this cohort. The cohort contains **3,912 buy fills, 131 strikes and 29 asset-month ladders**, with $7,450,611.70 of cumulative purchases. That last figure is turnover, not simultaneous money at risk.

| Requested rule element | What this cohort actually shows |
|---|---|
| Z threshold | No identifiable hard bar. Descriptive signed-z p10 **1.6296**, median **3.2318**, p90 **11.2554**, on 3,621 usable fills. Values run from 0.2249 to 29.8082. The fill distribution alone cannot distinguish a threshold from changing signals, portfolio decisions or exceptions. |
| Days left | p10 **1.6310 days**, median **8.7079**, p90 **26.3123**; maximum 30.3996. One fill is after the written window end. This is not one fixed 10.7-day entry rule. |
| Price cap | p10 **$0.88**, median **$0.994**, p90 **$0.998**, observed range **$0.17–$0.999**. Thus $0.99 is not this wallet's hard cap. **79.41% of buy dollars** are at $0.97 or higher. |
| Order style | **95.27% maker by fill count, but only 50.47% maker by purchase dollars.** Small maker fills and large takes produce very different impressions. Maker classification does not prove a particular order type, cancellation rule or queue position. |
| Fill size | Median **100 shares / $94.65**, p90 3,952.66 shares / $3,720. Largest fill: 600,000 shares / **$597,600**. These are fills, not parent-order sizes. |
| Size per strike | Cumulative purchase median **$34,735.20**, p90 $126,035.56, maximum $597,600. Selling and rebuying can make turnover exceed risk. No fixed dollar cap was found. |
| Size per ladder | Cumulative purchase median **$195,787.34**, p90 $739,681.79, maximum **$801,439.90**. No observed maximum establishes an intended cap. |
| Adds | Median 11 buy fills per strike, p90 64, maximum 605. Median 11 distinct recorded block-seconds, maximum 314. Repeated fills can be one resting order filling in pieces; they do not identify 314 deliberate order additions. |
| Strikes per ladder | Median **4**, p90 **8**, maximum **15 distinct purchased strikes**. This is a historical count, not a proved concurrent-position or order cap. |
| Max versus min | Both: 1,981 max-side fills / **$4,422,945.02**, and 1,931 min-side fills / **$3,027,666.69**. There is no max-only or min-only rule. |
| Hold to settlement | Many do, but not universally: this same BTC/ETH monthly family has **551 SELL fills** and **one YES buy** outside the BUY-NO cohort. A literal never-sell rule does not describe the full source history. |

### The scout's specified 96–99c price band

Keeping the originally proposed price band fixed, rather than choosing it after examining losses:

- **712 NO buys**, $2,025,278.53 purchased, **56 conditions**, of which **54 are resolved and all 54 ended NO**; two remain unresolved.
- Median price **$0.98**; median days left **11.3306** (p10 3.5918, p90 26.3263).
- **679 fills** have usable descriptive z: minimum **1.8516**, p10 **2.2212**, median **3.3539**, p90 **4.3385**.

This supports investigating the idea. It does **not** establish a true z minimum of 1.85, honest maker fill availability for us, independent trades, a forward win rate or after-fee Kalshi profit. Strikes within a ladder share the same underlying path and tail event. The 54 outcomes are not 54 independent coin flips.

For all core NO buys, **123 of 126 resolved strikes ended NO**, with five unresolved. Three losing contracts were cheap: ETH $4,900 maximum in August 2025 (22c), BTC $100,000 minimum in June 2025 (37c), and ETH $2,400 minimum in September 2026 (17c). He sold almost all the BTC $100,000 position, so its losing terminal contract outcome is not a full $1-per-share trading loss. Buying at least 97c touched 97 conditions, 95 resolved and all 95 ended NO; this overlaps the previous cohort and is not additional independent evidence.

The prior scout's **200/205 markets** is a different closed-position sample. It should not be substituted for the explicitly defined 126 resolved monthly BTC/ETH NO strikes above.

## 3. Why the recomputed z and times differ from the scout

The old `leaderboard/spot.py` saved a Coinbase hourly **close at the hour's start**. `ladder_rule.py` then used it during that same hour, allowing up to an hour of future price information. It also used absolute distance, which can incorrectly make a strike on the already-crossed side look safely far away, and clamped nonpositive time to a tiny positive value.

This audit instead uses:

1. The latest hourly close whose **start + 3,600 seconds + 5 seconds** is no later than the fill's recorded timestamp. Five seconds is a declared availability assumption, not proof of historic API delivery time.
2. Exactly **721 consecutive closes / 720 adjacent hourly log returns**. Annual volatility is population standard deviation times `sqrt(24 × 365)`. A missing hour invalidates the full affected trailing window; no interpolation or forward fill.
3. Signed safe-side distance: `ln(strike/spot)` for maximum barriers and `ln(spot/strike)` for minimum barriers, divided by `annual_vol × sqrt(days_left/365)`. Wrong-side, zero/negative time or invalid volatility produces no z.
4. The **written monthly ET end**, including daylight saving time. Older Gamma `endDate` values can be 16 or 28 hours early. We use the description's final one-minute candle through 23:59 ET; some later-listed February contracts begin on February 6 but end on February 28. Missing child end dates use the parent event only to identify the calendar year, with the written month still required. **271 core fills have a rules end different from or absent in the child metadata.**

Result: **3,621 descriptive z observations**, **290 excluded for incomplete trailing candles**, and **one expired fill excluded**. All 3,912 now have a rules-derived calendar end. The post-expiry buy was ETH $3,300 minimum in August at **$0.999**, about **1 hour 50 minutes after the end**; it must not be treated as an ordinary pre-expiry risk entry.

**These z values remain proxies, not qualification labels.** Coinbase USD is not the settlement price. The inspected international monthly markets specify **Binance BTC/USDT or ETH/USDT one-minute final highs/lows, inclusive barriers, ET calendar boundaries**. An earlier touch anywhere in the contract's own observation period matters. We did not fetch a complete historic Binance settlement feed, prove no previous touch, or verify when each public fill executed before its block timestamp. Therefore a valid descriptive z does not mean “safe untouched contract.” Kalshi's CF Benchmarks definition must be tested independently.

## 4. Funding and balances: this is not $100 compounding alone

The first indexed deposit is **$100.032650 on 2024-10-27 06:54:22 UTC**, transaction `0xbf5641d88fbf264095767cbc80ce48d2b75bee0d89edc4b7e057007a7824690e`, Polygon block **63,543,500**. Its receipt shows USDC.e entering the wallet; the preceding block has zero USDC.e and native USDC, and the after-block balance is $100.032650 USDC.e. This verifies the first indexed deposit locally; it does not prove the owner's entire wealth or every earlier activity elsewhere.

The API records that $100.03265 being withdrawn **148 seconds later**. January 2, 2025 then adds **$99.14694** in two deposits. The first trade is **2025-02-26 00:05:52 UTC**, not the first chart point:

- Two Solana February $120-minimum NO fills at **83.9c**, costing **$99.14463** combined.
- A later $118.17 redemption, followed on March 1 by **$118.16510** of Solana $190-maximum NO at **73c**.
- March 2025 then brings **$299,353.05 of new deposits**, followed by more large funding.
- The first observed BTC/ETH monthly NO buy is only in April, already a **$8,775** fill. There is no observed $100-phase BTC/ETH monthly 97–99c implementation to copy directly.

Across the complete indexed history: **$8,097,782.712288 deposited**, **$7,700,200.032646 withdrawn**, net external funding **$397,582.679642**. Gross deposits count money cycling in and out; they are not all unique capital. All 94 funding receipts were fetched and decoded. **Nine API amounts differ from receipts by one or two millionths of a dollar**, retained in the raw analysis rather than rounded into exact agreement.

`LUCAS_monthly.csv` records every month from the first funding through this capture. It keeps external funding, provider P&L, actual archived cash and timestamps in separate columns. The 2024 pre-trading months use the last Polygon block before each UTC month boundary found by binary search. From February 2025 onward, cash is read at the provider's explicit source block, which is not necessarily midnight. It tracks **USDC.e, native USDC and pUSD as distinct contracts**, using null before a contract exists.

At the latest P&L source block **95,414,594, 2026-10-12 17:46:21 UTC**, archived cash is **$4,307.588361 pUSD + $0.000002 native USDC**, with no USDC.e. Activity-derived cash is $4,307.588361; the two-millionth difference is exposed. Across monthly points the observed cash residual is only 2–4 millionths. This cash is **not** the wallet's total portfolio value or its profit: most money is in positions.

The separately captured `/v2/value` mark is **$739,637.402** at the later 22:25 UTC request. It is a current position-value snapshot, not same-block audited equity and not a historical monthly bankroll series. Monthly whole-portfolio equity, historical peak percentage drawdown of bankroll, and the owner's wealth remain unknown.

## 5. P&L record, fees and the losing month

The endpoints disagree in definitions and source timing:

| Measure | Latest value |
|---|---:|
| Legacy `user-pnl-api` chart, 22:00 UTC | **+$344,871.84** |
| v2 trade P&L, source block 17:46:21 UTC | +$344,884.927408 |
| v2 realized P&L | +$302,455.936651 |
| v2 unrealized P&L | +$40,911.476438 |
| v2 position P&L | +$343,367.413089 |
| v2 wallet income | +$2,136.658200 |
| v2 economic P&L | **+$345,504.071289** |

Do not add the legacy chart, rewards and v2 economic P&L together. The v2 fields themselves need care: `fees=-1701.022916`, `fees_paid=-1517.514319`, `fees_refunded=183.508597`. `trade_pnl + fees_paid` equals position P&L here; blindly adding the field named `fees` gives a different result. The raw field values are preserved.

Full activity reports maker rebates **$573.8885**, taker rebates **$8.8489**, rewards **$60.1952** and yield **$2,358.0410**, totaling **$3,000.9736**. The v2 wallet-income aggregate is only **$2,136.6582**, a **$864.3154 discrepancy**, even though no captured activity is after its source timestamp. We have not reclassified that difference or added it to reported profit. The tiny cash residual does not independently settle marked-position P&L or the provider's income classification.

Both monthly chart variants show **20 positive and one negative reported month** over February 2025–October 2026, including partial boundary months. The negative month is **May 2026: −$792.30 legacy, −$656.34 economic**. The scout's “worst −$1” is not supported by this full pull and UTC-boundary differencing. October 2025 remains positive: +$31,517.05 legacy / +$31,325.96 economic.

Daily-grid maximum drawdown is **$17,736.37 on the legacy chart**, or **$19,785.05 on the v2 economic chart**. These are respectively 5.13% and 5.71% of peak cumulative **profit**, not 5% of bankroll. Intraday drawdown could be worse. Most monthly source blocks are a few seconds behind the grid, but September 2026's boundary is **76,444 seconds stale**, so exact calendar-month profits are not established by the provider grid alone. The CSV retains that lag and the October partial endpoint.

## 6. What we can and cannot copy

A defensible candidate remains: selected, still-untouched monthly BTC/ETH barriers; NO bids in a stated high-price band; distance and days-left filters; carefully limited correlated exposure; wait for actual settlement. The source often supplies liquidity, but half its core purchase dollars are taker, and its fills do not reveal our queue priority or future fills.

We **cannot** honestly write an “exact learned rule” for z, order size, repricing, unfilled orders, cancellations, intended maximum simultaneous strikes or loss limits from these records. Buying every observed source fill retrospectively would condition on executions already known to have happened. The Kalshi backtest needs its own rules, price history, fee model and defensible fill assumptions; it must not inherit the international venue's winner label or these z proxies as ground truth.

No source-wallet metric here establishes that the approach works at $25–$100 after Kalshi fees or that our resting bids fill. One loss at 97c erases roughly 32 wins at the same price and size before fees. Buying several nested strikes concentrates the same tail risk.

## 7. Reproduction and evidence files

From the repository root, using the existing research virtual environment:

```bash
python research/lab9/lucas_history.py --directory /tmp/lab9-lucas
python research/lab9/lucas_history_data.py markets --directory /tmp/lab9-lucas
python research/lab9/lucas_history_data.py candles --directory /tmp/lab9-lucas
python research/lab9/lucas_history_data.py cash --directory /tmp/lab9-lucas
python research/lab9/lucas_history_data.py early-cash --directory /tmp/lab9-lucas
python research/lab9/lucas_history_analysis.py --directory /tmp/lab9-lucas --output research/lab9
```

The downloader uses an isolated copy of the already-tested `research/lab8/skip/history.py` and `history_chain.py` bound to this fixed public wallet; it never changes those modules or accesses account credentials. Research calls are read-only public data, rate spaced, stop on unrecoverable responses and honor 429s. No international trading or region workaround occurs.

- [Monthly cash, funding and provider P&L](LUCAS_monthly.csv): 25 rows.
- [Every selected monthly BTC/ETH NO strike](LUCAS_strikes.csv): 131 rows, including sales and unresolved outcomes.
- [Every selected asset-month ladder](LUCAS_ladders.csv): 29 rows.
- Raw pages, response timing, cursor manifests, receipts, candle inputs and per-fill features are under `/tmp/lab9-lucas/`, outside git. This temporary workspace is not promised durable retention; reruns can see corrected or unavailable upstream data.

The tests enforce source identity, preservation of duplicated fills, explicit share disagreements, rejecting ambiguous joins, written calendar ends/DST, refusing proposed outcomes as final settlements, and refusing expired or wrong-side z values. This public-history research has no order client and changes no application or live-money settings.

Derived evidence checksums (SHA-256, LF CSV bytes):

| Artifact | SHA-256 |
|---|---|
| `LUCAS_monthly.csv` | `59dfb5ba71df70f436eb6fe34081ca82ba610179782953eb67231034e5c50578` |
| `LUCAS_strikes.csv` | `d5573c24b1c4aaecf08625f4b05b0e19b3fd0e47735cb406e9e887478d684d36` |
| `LUCAS_ladders.csv` | `49bacd9bf945076326190fac595e3d20dc3c5bb0687dc98cfd13c9c57f6df3cd` |

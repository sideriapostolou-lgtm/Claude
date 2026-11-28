# Polymarket US crypto markets today: the venue map for lab 8

Written 2026-10-12, 14:05-17:05 UTC. Research only: read from the venue's **public** gateway
(`https://gateway.polymarket.us/v1`, no key) and its public docs (`https://docs.polymarket.us`). No order, no key,
no account, no Railway. Raw pulls and scripts are in the scratchpad (`$SCRATCH/lab8`, out of git, 24 MB); the scripts
are copied to `research/lab8/us_venue/` and the headline numbers to `research/lab8/us_venue/numbers.json`.

The question behind this map (the owner, 2026-10-12): *"this is like 100 %, there's no way bitcoin drops below that
and our bot got it at 99 cents ... if you backtest ones like these it's probably 100 % when it's that far out ...
then we give it $1,000 and scale"*. This file does **not** answer whether that bet wins (that is lab 8's
pre-registered test). It answers what the venue actually offers: which markets, settled on what, how much trades,
and how many "far out" contracts can actually be bought at 0.95-0.99 each hour.

## The answer in plain words

1. **Only Bitcoin.** The venue lists 15 crypto series and every price market among them is BTC. There is no ETH, SOL
   or XRP market on Polymarket US (the gateway's index history even answers "not available" for them). Two BTC
   series exist with **no events at all**: Up/Down 5-minute and 4-hour.
2. **Everything settles on CF Benchmarks' BRTI, not Binance.** All automated markets settle on the average of the 60
   one-second BRTI prices in the minute before the stated instant ("BTC price at 10:00 AM ET" = the mean of
   09:59:00-09:59:59 ET). Lab 4 / lab 5 history (polymarket.com) settled on Binance candles or Chainlink, so lab 8
   cannot reuse their settlement code for this venue. BRTI ran **3.7 bp below** Binance BTCUSDT on average (sd 2.9
   bp, worst 13.6 bp) over 4,823 minutes: harmless 1 % from a strike, not harmless at the strike.
3. **The hourly ladder is big and almost empty.** Each hour (23 a day; none expires at 21:00 UTC = 5 PM ET) has
   167-171 "BTC at or above $X" strikes, $100 apart, covering about +-10 % of spot. It only trades in its last
   hour. In the last 46 hourly ladders, **94.7 % of all 7,738 strikes never traded once**; the median ladder traded
   **17,756 contracts ($7,370) in total**, the median strike that traded at all 1,210 contracts ($352). Strikes
   1.5 % or more from the final price traded **11 contracts in 46 hours** (one strike, plus one 0.01-contract
   print); 1.0-1.5 % away, 6,875 contracts on 27 of 390 strikes.
4. **"Far" contracts at 0.95-0.99 are rare and small.** See "Far strikes you can actually buy" below for the live
   count: LIVE_SUMMARY_PLACEHOLDER
5. **0.99 is the ceiling.** Prices run $0.01-$0.99 in $0.01 ticks, so buying the sure side at 0.99 makes at most
   1 cent a contract before fees. Taker fee `0.0695 x C x p x (1-p)`, rounded to the cent per fill (banker's
   rounding): 10 contracts at 0.99 pay **$0.01** fee, win **+$0.09**, lose **-$9.91**; the break-even win rate is
   **99.10 %** (one loss wipes out 110 wins). At 0.96 it is about 96.3 %.
6. **The owner's example, re-read on the venue's own data.** `cpc-btc-above-hr-2026-10-12-1400z-81900` traded
   **168.78 contracts ($165.00) over its whole life**; the 10 bought at 0.99 at 13:36:02 UTC were its last print and
   6 % of everything it ever traded. At that second BRTI was **$82,451, i.e. $551 (0.67 %) above the strike, not
   $960 (1.2 %)**; BTC only reached $82,860 at 13:55. With 24 minutes left that was about **4.0 standard deviations**
   at the day's hourly volatility (0.27 %/h). It settled at 82,880.82 (Yes) 30 s after 14:00 UTC.
7. **No public trade tape.** Prints exist only behind an API key (the markets WebSocket `SUBSCRIPTION_TYPE_TRADE`,
   live only; `/v1/rfqs/trades`, RFQ-related fills only). Public data: the full book with lifetime stats (first /
   high / low / last trade price and time, contracts and dollars traded), best bid / offer, settlement, a minute
   "price history" that is **display prices, not trades** (and blank for empty books), and the BRTI index itself
   (since 2026-10-05 15:22 UTC).
8. **What it means for "$1,000 and scale"** (venue facts, not a verdict): a $1,000 ticket at 0.99 is about 1,010
   contracts. Over the last 46 hours **all** strikes 1 % or more from the final price traded 6,886 contracts
   together (about 150 an hour), and
   the biggest near-certain offer seen live was LIVE_MAXDEPTH_PLACEHOLDER contracts. The venue cannot absorb that
   ticket on far strikes; it can absorb it near the money, which is where the price is not near-certain.

## What is listed (2026-10-12 14:05 UTC)

`/v1/events?categories=crypto&closed=false` returns 20 open events, 679 open markets. Series ids from `/v1/series`.
"Lifetime $" = dollars traded over the market's life from `/markets/{slug}/book` stats, recently expired events.

| family | series (id) | slug | expiry | strikes / buckets | listed / tradable | events so far | lifetime $ per event (sample) |
|---|---|---|---|---|---|---|---|
| Above/Below, hourly | `btc-strike-hourly` (377) | `cpc-btc-above-hr-YYYY-MM-DD-HHMMz-STRIKE` (HHMM = expiry UTC) | every hour except 21:00 UTC | 167-171 strikes, **$100** apart, ladder width 20.0 % of price | created 2.7-4.0 h ahead; **opens only at the start of its last hour** | 158 since 2026-10-06 00:00 UTC | median **$7,370** (46) |
| Price Range, hourly | `btc-range-hourly` (376) | `cpc-btc-range-hr-...-LOWER` | same | 168 $100 buckets + "or below" + "or above" | same | 158 | median $159 (4) |
| Above/Below, daily | `btc-strike-daily` (379) | `cpc-btc-above-day-YYYY-MM-DD-STRIKE` | 21:00 UTC (5 PM ET), **no Friday** | 47 strikes, **$250** apart today (the FAQ says $500) | created ~25 h ahead, open all day | 7 | median $32,265 (6) |
| Price Range, daily | `btc-range-daily` (380) | `cpc-btc-range-day-...` | same | 46 + 2 tails | same | 7 | median $1,871 (6) |
| Above/Below, weekly | `btc-strike-weekly` (381) | `cpc-btc-above-wk-YYYY-MM-DD-STRIKE` | Friday 21:00 UTC | 75 strikes, $500 apart | created Friday 22:05 UTC the week before (the FAQ says Monday 00:00 ET) | 2 | $36,279 (1) |
| Price Range, weekly | `btc-range-weekly` (382) | `cpc-btc-range-wk-...` | same | 74 + 2 tails | same | 2 | $636 (1) |
| Up/Down 15 min | `btc-updown-15m` (375) | `cpc-btc-updown-15m-YYYY-MM-DD-HHMMz` (HHMM = window start) | every 15 min | 1 market; `priceToBeat` published at the open | 47 windows listed ~12 h ahead, one open at a time | 1,921 since 2026-09-22 | median **$162,946** (48) |
| Up/Down 1 h | `btc-updown-1h` (378) | `cpc-btc-updown-1h-...` (start) | hourly | 1 | 24 listed ahead, one open | 497 since 2026-09-22 | median $41,405 (48) |
| Up/Down 1 day | `btc-updown-1d` (434) | `cpc-btc-updown-1d-YYYY-MM-DD-2100z` (start) | 21:00 UTC | 1 | one open | 9 | median $35,921 (7) |
| Up/Down 5 min, 4 h | `btc-updown-5m` (387), `btc-updown-4h` (388) | - | - | - | series exist, **no events ever** | 0 | - |
| One-touch, weekly | `btc-hit-weekly` (435) | `cpc-btc-hit-h-w-DATE-TARGET` / `-l-w-` | Friday 21:00 UTC | 8 "Reaches" + 8 "Dips to", $2,500 apart | open all week | 4 | $112-$348 (2) |
| One-touch, monthly | `btc-hit-monthly` (374) | `cpc-btc-hit-h-m-YYYY-MM-TARGET` / `-l-m-` | month end 04:00 UTC | 8 + 8-9, $2,500 apart | open all month | 2 | not sampled |
| Hand-listed long-dated | `btc` (101) | `cpc-btc-150k-...`, `-100k-`, `-hitprice-high/low-yr-`, `-pricerange-yr-`, `-above-yr-` | 2026 year end | 2-28 each | open | 6 | not sampled |
| Not a price market | `mag7` (281) | `tklc-mag7-stablecoin-2026-12-31-*` | 2026-12-31 | 7 companies | open | 1 | - |

Every crypto market read (all families, about 9,800 markets: 7,738 expired hourly strikes, 1,401 other
expired markets, 679 open) has `feeCoefficient` **0.0695**,
`orderPriceMinTickSize` **0.01** and `minimumTradeQty` **0.01** (fractional contracts allowed).

The automated BTC families started on two dates: Up/Down 15 min and 1 h on **2026-09-22**; the hourly / daily /
weekly ladders, ranges, one-touch and daily Up/Down on **2026-10-05/06** (first hourly ladder
`btc-above-hr-2026-10-06-0000z`, created 2026-10-05 20:58 UTC). **So the venue's own history of the owner's market
type is 158 hours long.** The docs still say these families are "listed in the preprod environment and roll out to
production as announced"; production has them.

## Settlement rules as the venue states them

Quoted from the markets' own `description` (the rules shown in the app) and the Crypto FAQ
(`docs.polymarket.us/faqs/crypto-faqs`):

- **Above/Below** (hourly, daily, weekly): *"This market will settle to Yes if the price of Bitcoin is at or above
  $81,600 at 11:00AM ET on Oct 12, 2026 ... Outcome sourced from CF Benchmarks' Bitcoin Real-Time Index (BRTI) ...
  in the last minute before 11:00AM ET on Oct 12, 2026, 60 BRTI prices are collected. The official and final value
  is the simple average of these prices, rounded to the nearest 2 decimal places. ... A settlement value exactly
  equal to $81,600 settles to Yes. Please note that this market is about the price according to CF Benchmarks'
  BRTI, not according to other sources or spot markets."* Every strike settles independently (a nested ladder:
  every strike at or below the settlement value is Yes).
- **Price Range**: same value and minute; *"between $82,200 and $82,299.99, inclusive of both bounds ... Only one
  outcome in this event will settle to Yes."* Buckets tile the price line in one-cent steps; the lowest is "or
  below", the highest "or above".
- **Up/Down** (15 min, 1 h, 1 day): *"settle to Up if the Bitcoin price at 11:00AM ET ... is greater than or equal
  to the price at 10:00AM ET"*, both values computed the same way (60 BRTI prices in the minute before). The open
  value is published as `assetPriceTerms.priceToBeat`, the close as `settlementPrice`. A tie settles Up.
- **One-touch** (weekly, monthly): *"at or above $90,000 at any point from the later of this market's listing and
  5:00PM ET on Oct 9, 2026 until 5:00PM ET on Oct 16, 2026"*, on a rolling 60-second BRTI mean that drops the top
  and bottom 20 % of values; it **may settle early** the moment the target is touched.
- **Hand-listed** (`btc` series): BRTI trimmed mean "over any sixty second period", or over the sixty seconds ending
  at the stated time for the year-end range. The FAQ says to read each market's own rules.
- **Timing**: trading ends at the settlement instant; the instrument expires 30 minutes later (`endDate` on a
  market is +30 min, or +26 s on expired ones). The FAQ says ladders settle "within about fifteen minutes"; seven
  expired strikes read for this settled 30-113 s after the instant (the owner's market: `settlementSetTime`
  14:00:30 UTC). Missing index
  data defers settlement; nothing settles on partial data. 1-hour and 15-minute Up/Down windows that would overlap
  scheduled maintenance are not listed.
- **Price range and tick**: the fee page defines `p` from $0.01 to $0.99; books show nothing above 0.99. **0.99 is
  the cap** for a buyer; the tick is 0.01.
- **Fees** (`docs.polymarket.us/fees`, effective exchange-wide from 10 AM ET on 2026-10-07): taker `0.0695 x C x p x
  (1 - p)`; maker rebate `0.0125 x C x p x (1 - p)`, paid at the trade; table tennis 0.10 (not crypto). Fees and
  rebates are rounded to the cent with banker's rounding, per fill, and an order's total never exceeds the rounded
  exact fee. Taker rebates of 10-50 % start at $250,000 of prior-month taker volume. A single market buy in the app
  is capped at $1,000,000.

What I **verified** against the data, not just read:

- **46 / 46** expired hourly ladders: the published `settlementPrice` equals the gateway's BRTI 1-second value at
  T - 1 s to the cent; **48 / 48** Up/Down boundaries (open and close of 24 random 15-minute windows, 2026-10-06 to
  10-12) likewise. Detail that matters for code: the gateway's `ASSET_PRICE_BUCKET_1S` series is already the
  60-second average (each 1 s candle carries `tickCount` 60 and moves smoothly); the 5 s / 15 s / 1 min / 5 min
  buckets are raw ticks. **The docs' own recipe ("average the 60 one-second closes from T - 60 to T - 1") matches
  0 of 48** (off by up to $68). To get a settlement value, read the 1 s close at T - 1.
- No hourly ladder at 21:00 UTC (10-10 and 10-11 checked) and no daily ladder on Friday 10-09: as the FAQ says.
- Strike spacing: 7,692 / 7,692 neighbouring hourly strikes are $100 apart.
- A ladder's next hour exists in the event list 3-4 h ahead (status CLOSED) but its markets answer "not found" on
  `/book` and `/bbo` until the hour starts (checked 14:05 for the 16:00 ladder; see the live section for the 15:00
  opening); first prints come in the first minutes of the last hour (median first trade 57.7 min before expiry).

## Liquidity: 46 expired hourly ladders (2026-10-10 15:00 to 2026-10-12 14:00 UTC)

Every strike of every hourly ladder in the window (48 hours minus the two 21:00 slots): **7,738 markets**, lifetime
stats from `/markets/{slug}/book` (`sharesTraded`, `notionalTraded`, first / last / high / low trade and their times).
**Read contracts first**: the venue's `notionalTraded` is counted at the YES price (the owner's market: 168.78
contracts, $165.00; strike 83,200 of the 15:00 ladder: 1,426.5 contracts, $68.88, most of it bought as NO at 0.98),
so dollars understate the money at risk wherever the sure side is NO.

| per market (7,738) | value |
|---|---|
| never traded | **94.7 %** (7,326) |
| contracts traded, 99th percentile | 3,837 |
| dollars traded, mean | $55.96 |

| per traded market (412) | p10 | p25 | median | p75 | p90 | max |
|---|---|---|---|---|---|---|
| contracts | 40 | 251 | 1,210 | 3,262 | 5,808 | 15,437 |
| dollars | $7 | $55 | **$352** | $1,306 | $3,079 | $9,899 |

| per ladder (46) | p10 | p25 | median | p75 | p90 | max | total |
|---|---|---|---|---|---|---|---|
| contracts traded | 7,799 | 11,385 | **17,756** | 25,001 | 33,546 | 75,702 | 912,787 |
| dollars traded (YES price) | $3,840 | $5,300 | **$7,370** | $11,154 | $15,308 | $44,159 | $433,003 |
| strikes that traded at all | 5 | 6 | **8** | 13 | 14 | 18 | of 167-171 |

Where the money is, by the strike's distance from the **final** settlement value:

| distance | strikes | traded | share traded | contracts traded | dollars (YES price) |
|---|---|---|---|---|---|
| 0-0.25 % | 186 | 177 | 95 % | 640,613 | $307,292 |
| 0.25-0.5 % | 188 | 104 | 55 % | 155,180 | $68,624 |
| 0.5-1.0 % | 387 | 102 | 26 % | 110,108 | $52,159 |
| **1.0-1.5 %** | 390 | 27 | 7 % | **6,875** | $4,918 |
| **1.5-2.0 %** | 384 | 1 | 0.3 % | **11** | $9.93 |
| **2-3 %, 3-5 %, > 5 %** | 763, 1,534, 3,906 | 0, 0, 1 (a 0.01-contract print) | 0 | **0.01** | $0 |

The owner's $165 market sits at the 41st percentile of the traded markets; its whole ladder (14:00 UTC) traded
$10,442 on 14 strikes.

**Prints at 0.95-0.99 on the near-certain side, in the last hour, by distance from BRTI at the print.** The book
stats give up to four prints per market (first, lowest, highest, last), each with a time; 1,239 distinct prints.
This is a lower bound on all prints (the venue has no public tape) and describes the sample; it is not a test.

| distance at the print | prints at 0.95-0.99 | won | lost | mean price |
|---|---|---|---|---|
| 0-0.25 % | 330 | 316 | 14 | 0.975 |
| 0.25-0.5 % | 192 | 187 | 5 | 0.973 |
| 0.5-1.0 % | 105 | 105 | 0 | 0.973 |
| **1.0 % or more** | **2** | 2 | 0 | 0.980 |

In 46 hours, the venue's own stats show two such prints 1 % or more from spot.

## Liquidity: the other families (recently expired, lifetime dollars)

| family | events | markets | traded | per event: p10 / median / p90 | per market: median / p90 |
|---|---|---|---|---|---|
| Up/Down 15 min (last 12 h) | 48 | 48 | 48 | $33,335 / **$162,946** / $464,020 | (one market per event) |
| Up/Down 1 h (last 48 h) | 48 | 48 | 48 | $8,783 / $41,405 / $65,290 | |
| Up/Down 1 day (10-04 to 10-10) | 7 | 7 | 6 | $0 / $35,921 / $255,523 | |
| Above/Below daily (10-05 to 10-11, no Friday) | 6 | 238 | 110 | $0 / $32,265 / $50,147 | $0 / $1,313 |
| Price Range daily | 6 | 244 | 87 | $0 / $1,871 / $5,390 | $0 / $145 |
| Above/Below weekly (10-09) | 1 | 59 | 24 | $36,279 | $0 / $2,236 |
| Price Range weekly (10-09) | 1 | 60 | 9 | $636 | $0 / $19 |
| One-touch weekly (10-09) | 2 | 17 | 7 | $112 / $348 | $0 / $99 |
| Price Range hourly (4 events) | 4 | 680 | 22 | $46 / $159 / $293 | $0 / $0 |

The crowd is in the 15-minute Up/Down windows (about 20x an hourly ladder each). The hourly "above" ladder is the
thinnest product with real trading; its range twin is nearly dead.

LIVE_SECTION_PLACEHOLDER

## Is there a public trade history?

| endpoint | key? | what it gives | prints? |
|---|---|---|---|
| `GET /v1/markets/{slug}/book` | no | full depth both sides; `stats`: open / high / low / close / last trade price **with times**, `lastTradeQty`, `sharesTraded`, `notionalTraded`, `openInterest`, settlement; works on expired markets | lifetime summary only |
| `GET /v1/markets/{slug}/bbo` | no | best bid / ask with sizes, last trade, state | no |
| `GET /v1/markets/{slug}/settlement` | no | 1 / 0 | - |
| `GET /v1/price-history?symbol=SLUG&...` | no | ~1-minute **display** prices (`longPrice` "normally derived from the best ask", `shortPrice` from 1 - best bid; custom ranges up to 24 h); the docs: *"these are not individual trades"*. Checked against live books: it does **not** follow the book when one side is empty (strike 83,700 at 14:15 UTC showed 0.06 / 0.99 with only a 0.99 ask and no bid on the book) and it returns nothing for strikes with an empty or one-sided book | no |
| `GET /v1/asset-prices/history?assets=crypto:btc` | no | the BRTI index as OHLC candles, buckets 1 s to 1 day, up to 3,600 candles a call; history from **2026-10-05 15:22 UTC**; BTC only | - |
| `GET /v1/events/slug/{slug}`, `/v1/events?seriesId=` | no | events with all markets, strikes, `priceToBeat` / `settlementPrice`, rules text | - |
| `wss://api.polymarket.us/v1/ws/markets` `SUBSCRIPTION_TYPE_TRADE` | **API key** | every trade (price, quantity, time, maker / taker side) | **yes, from connection on (no backfill)** |
| `GET https://api.polymarket.us/v1/rfqs/trades` | **API key**, 1 req/s | *"anonymous original fills where either order originated from an RFQ"* | RFQ-related fills only |

Tried and not found (404) on the gateway: `/markets/{slug}/trades`, `/prices-history`, `/candles`, `/history`,
`/fills`, `/activity`, `/tape`, `/trades?market=`. Unknown query parameters on `/v1/events` are silently ignored
(they return the default sports listing), so a "search" that seems to work may not filter at all; `seriesId`,
`slug`, `categories`, `closed`, `endDateMin` do filter.

**So**: the only way to get US crypto prints without a key is to build a tape by polling `/book` stats (contracts
traded and last trade per poll), as the live recorder below does once a minute. With the owner's key, the markets
WebSocket gives true prints from the moment it connects. Neither gives history before today.

LIVE_FAR_PLACEHOLDER

## What this means for lab 8 (facts for the design, no verdict)

- **History of this exact product on this venue is 158 hours** (since 2026-10-06), and the index history 7 days.
  That is far too short for TRAIN -> VAL -> one-look TEST on venue prints. polymarket.com does not have the twin
  either: lab 4's cache (markets with $20k+ volume) holds only 4 hourly-close "above" markets (lab 5 inventory).
- The owner's claim splits in two, and they need different data:
  1. *"Is it ~100 % when it's that far out?"* is a question about Bitcoin's path: how often does BTC end a given
     number of volatility units on the wrong side of a level after N minutes? Lab 5's Binance 1-second klines
     (2026-06-01 to 10-08, out of git) answer it for thousands of hours, with BRTI's 60-second average as the
     settlement statistic and the measured basis (3.7 bp, sd 2.9 bp) as a stress. No market tape is needed for this.
  2. *"Can we buy it at 0.95-0.99?"* is a question about this venue's books, which only a forward recorder can
     answer (no public tape, no history). The recorder used here (`us_venue/live_recorder.py`) is the starting point.
- The live desk's rule cannot take most far strikes even when they are offered: it needs a bid **and** an ask within
  0.03, an ask of at least 0.97, and a prior print of at least 0.94 (`polydesk._qualifies`). Far strikes usually
  have one side only and no prints (94.7 % of strikes never trade), and the rule buys the YES side only, so the
  far strikes above spot (where NO is the sure side) are never bought.
- Size is the binding limit, before any question of edge: see "$1,000 and scale" in the summary.

## What I could and could not verify

Could: the listing and series (15 crypto series, all BTC; 5 m / 4 h empty); each family's rules text, fee,
tick, minimum size; settlement values against the index (46 / 46 ladders, 48 / 48 Up/Down boundaries); the ladder
geometry ($100 spacing, ~20 % width, 23 ladders a day); lifetime volume of 7,738 expired hourly strikes and 1,401
markets of the other families; live books of LIVE_N_PLACEHOLDER; the BRTI-Binance basis over 4,823 minutes
(2026-10-05 15:38 to 10-09 00:00 UTC); the owner's example market end to end.

Could not:
- **Individual prints.** No public tape; the expired-market numbers rest on lifetime totals and four summary prints
  per market. Who bought (the owner's desk or others) cannot be seen.
- **Books before today.** `/price-history` is display prices and blank for empty books, so the depth of far strikes
  in past hours cannot be rebuilt; the far-strike count rests on LIVE_HOURS_PLACEHOLDER of live recording on one
  Monday afternoon (UTC), not a week.
- **Raw BRTI ticks.** The 1 s series is the 60 s average; the raw index is only available at 5 s and wider buckets.
  The settlement rule itself (simple average of 60 prices) is the venue's word; I verified the published values,
  not CF Benchmarks' feed.
- **The app's "68 %".** The display price the app shows is not in the public data at the owner's minute
  (`/price-history` showed 0.99 / 0.04 at 13:36). At 13:53 it showed 0.99 / 0.61, i.e. bid 0.39, ask 0.99,
  midpoint 0.69: a thin book's midpoint can read as "68 %". That fits the owner's account; it does not prove it.
- **Fee on a real fill.** The rounding is the docs' word; no order was placed.
- Whether the daily ladder's $250 spacing (vs the FAQ's $500) and the weekly listing time (Friday 22:05 UTC vs the
  FAQ's Monday 00:00 ET) are permanent.

## How the numbers were made

All reads were public, unauthenticated, under ~10 requests a second (the documented limit is 20 per second per IP);
about 25,000 requests and 24 MB in total. Scripts (`research/lab8/us_venue/`, run with `python -I`):

- `fetch_listing.py`, `series_census.py`: the open listing and, per crypto series id, first event and event count.
- `expired_sample.py`: every hourly ladder ending 2026-10-10 15:00 to 2026-10-12 14:00 UTC; `/events/slug/...`, then
  `/book` and `/price-history` per strike. `analyze_expired.py`, `trade_points.py`: the tables above.
- `family_volume.py`, `analyze_families.py`: lifetime volume of the other families.
- `check_settle_stat.py`: published `priceToBeat` / `settlementPrice` vs the gateway's BRTI series.
- `basis.py`: raw BRTI (1-minute closes) vs raw Binance BTCUSDT 1-second closes (lab 5's cache) at the same second.
- `live_recorder.py`, `analyze_live.py`: the live books (below).
- Raw data: `$SCRATCH/lab8/{raw,expired,live}`, `family_volume.jsonl`, `settle_stat.json`, `basis.json`.

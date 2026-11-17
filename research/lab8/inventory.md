# Lab 8 inventory: what the data can carry for a distance-filtered grind (no return computed)

Written 2026-10-12, 14:05-15:10 UTC. Research only: nothing here trades, no key was used, no production system was
touched. Every number below is a COUNT (markets, prints, dollars traded, file sizes); no stage read an outcome,
computed a win rate or a P&L, except lab 5's universe rule (binary, exactly one winner) and the owner's one example,
whose settlement (1, Yes) the owner reported and the gateway confirms. Script: `research/lab8/inventory.py` (stages listed at the end);
machine-readable numbers: `research/lab8/inventory.json`. Data stays out of git under `$SCRATCH/lab8/inv` (36 MB).

**The question (owner, 2026-10-12):** *"this is like 100 %, there's no way bitcoin drops below that and our bot got
it at 99 cents ... it also sniped 96 to 99 cents; if you backtest ones like these it's probably 100 % when it's that
far out ... then we give it $1,000 and scale"*. Lab 4 found the blanket price rule (buy any 0.95-0.99 outcome) has
NO EDGE; lab 5's spot-and-volatility specialist found NO EDGE, but mostly on mid-priced contracts. Lab 8 will test the
untested combination: **price 0.95-0.99 in the last hour AND spot far from the strike in volatility units.** This
file only says how much data exists for that test.

## The answer in plain words

1. **The owner's exact market is almost absent from the history.** His example is a Polymarket US hourly Bitcoin
   strike ("BTC at or above $81,900 at 10:00 AM ET"). Lab 4's polymarket.com cache holds **4** hourly strike markets
   (1 TRAIN, 0 VAL, 3 TEST), because lab 4 only kept markets with $20,000+ volume. polymarket.com does run that
   family every hour (Gamma lists **45,160 BTC and 36,032 ETH hourly strikes** that closed 2026-07-01 .. 10-08), but
   they are tiny: the median strike that traded at all traded **$15** (VAL, TEST) to **$115** (TRAIN), and in a
   sample of 1,028 traded BTC strikes the median tape is **one fill**; none has the 50 fills lab 4 requires.
2. **The US venue's own history of that market is one week, with no tape.** Polymarket US's hourly ladders started
   2026-10-05 22:00 UTC (158 hours, 26,682 strikes settled by today), after lab 4's TEST window ended (10-08). The
   public gateway gives each market's lifetime open / high / low / last price and settlement, not its trades
   (`/markets/{slug}/trades` answers 404). See `us_venue.md` (written in parallel) for the venue itself.
3. **What the cache CAN carry** (TRAIN, markets with a buyable print at 0.97 or more in their last hour and spot at
   least 3 volatility units from the strike, independent price draws in brackets): Bitcoin/Ethereum **noon-ET
   "above" ladders 156 (41 days)** and "between" ladders 104 (41), **5-minute up/down 1,973 (882 hours)**, **15-minute 1,396 (779)**, **hourly
   up/down 633 (623)**, 4-hour 141 (134), daily 89 (45), daily touch 96 (38). Table T3 has every family, split,
   price floor (0.95 / 0.97 / 0.99) and distance floor (2 / 3 / 4 / 5).
4. **No family in the cache settles like a US family.** Every US crypto market settles on **CF Benchmarks' BRTI**
   (the average of 60 one-second prices in the minute before the hour); polymarket.com's settle on **Binance
   BTC/USDT** candles or a **Chainlink** stream. The nearest twins share the instant but not the source: hourly
   strikes (4 in the cache), the 15-minute and hourly up/down windows (same clock grid). The noon-ET ladders, the
   cache's only sizeable strike family, settle at 12:00 ET where the US daily ladder settles at 5:00 PM ET.
5. **Binance 1-second data is complete.** Lab 5's klines (BTC, ETH, SOL, XRP, 2026-06-01 .. 10-08) have **zero
   missing seconds**, and every one of the 5,621,879 buyable 0.95+ prints in the last hour has its exact 1-second
   candle 10 s before the print and a defined volatility (889 Chainlink windows without a `priceToBeat` have spot
   but no reference, so no distance). Binance archives for 10-09 .. 10-11 exist (about 2 MB a day per coin) if the
   US live days are needed.
6. **Binance monthly 1-minute klines 2019-01 .. 2026-05 are cheap.** BTC 89 months 193 MB, ETH 89 months 180 MB,
   SOL 70 months (it listed in 2020-08) 121 MB: **495 MB zipped, about 300 MB as parquet**, checksums verified on two
   sample months (44,640 rows each, no missing minute). That is seven years of "how often does a 3- or 4-sigma lead
   fail in the last hour", independent of any prediction market.
7. **The owner's example, measured.** At 13:36 UTC (the buy) Coinbase BTC-USD, a public USD proxy for BRTI, was
   **$82,464: $564 (0.69 %) above the strike, not $960 (1.2 %)**; BTC reached $82,860 only at 13:55. With 24
   minutes left that is **z = 3.7** at the previous 24 hours' volatility (27.6 % a year), or 2.9 at the cache's
   median Bitcoin volatility (35.5 %). `us_venue.md` reads the venue's own BRTI at that second as $82,451 ($551),
   which agrees. The market traded $165 over its whole life; its lowest print was 0.96 at 13:30:53.
8. **What "probably 100 %" needs before it is a fact** (arithmetic, not a result): at a price of 0.99 one loss
   costs about **106 wins**, so lab 4's bar (rule of three) needs at least **323 independent bets** even with no
   loss, and showing that a true 99.5 % win rate beats the 99.07 % break-even needs about **1,030**. At 0.97 the
   rule-of-three floor is 108 bets. Only the 5-minute, 15-minute and hourly windows reach several hundred independent
   price draws per split at 3+ volatility units; the noon-ET ladders have 41 / 31 / 23 days.

## 1. Families and splits in the lab 4 / lab 5 caches

Universe: lab 5's (polymarket.com crypto fee family, binary, one winner, a parsed price contract on BTC / ETH / SOL /
XRP, closedTime 2026-07-01 .. 2026-10-08; 38,426 markets) plus the 889 Chainlink windows lab 5 dropped for want of
a `priceToBeat` (counted, never modelled): **39,315 markets**, tapes for all (lab 4: the last 14 days of fills).
Splits on closedTime, lab 4's: TRAIN 2026-07-01 .. 08-15, VAL 08-16 .. 09-15, TEST 09-16 .. 10-08. TEST is counted
here exactly as lab 5's inventory counted it; nothing about TEST outcomes was read.

Definitions. **Last 60 minutes** = prints in [settlement - 3600 s, min(settlement, closedTime)), settlement = the
instant whose price settles the market (noon-ET ladders: 12:01:00 ET, the close of the 12:00 one-minute candle;
hourly strikes: the hour; windows: the window end; touch: the period end). **Buyable for an outcome** (lab 4
Amendment 3) = a taker BUY of that outcome or a taker SELL of the other at 1 - p; the price is that outcome's. Prints
are counted only in markets with at least 50 fills (lab 4's rule; 222 markets fall below it). **Clusters** = lab 5's
independent price draws: noon-ET ladders and touches by the ET date that settles them (all coins together), windows
by the UTC hour of the window end. The tape has no order book, so the live desk's spread check (<= 0.03) cannot be
replayed; a print is a trade that happened, not a quote that was there.

### T1. Markets, last-hour prints and buyable prints at 0.95 or more, by family and split

| family | split | markets | with >= 50 fills | prints, last 60 min | buyable prints >= 0.95 | 0.95-0.97 | 0.97-0.99 | >= 0.99 | markets with a >= 0.95 print | with a >= 0.97 print | clusters (>= 0.95) | $ notional >= 0.95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| terminal hourly above | train | 1 | 1 | 10 | 8 | 4 | 4 | 0 | 1 | 1 | 1 | $668 |
| terminal hourly above | test | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0 |
| terminal noon ET above | train | 614 | 550 | 22,894 | 8,336 | 1,060 | 3,796 | 3,480 | 162 | 162 | 41 | $2.42M |
| terminal noon ET above | val | 483 | 445 | 14,606 | 5,245 | 742 | 1,182 | 3,321 | 188 | 188 | 31 | $1.99M |
| terminal noon ET above | test | 385 | 362 | 10,050 | 3,101 | 500 | 745 | 1,856 | 154 | 154 | 23 | $1.20M |
| terminal noon ET below | train | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0 |
| terminal noon ET below | val | 12 | 7 | 65 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | $0 |
| terminal noon ET below | test | 22 | 15 | 53 | 4 | 0 | 0 | 4 | 2 | 2 | 2 | $302 |
| terminal noon ET between | train | 157 | 155 | 11,661 | 4,631 | 775 | 2,491 | 1,365 | 113 | 113 | 41 | $533k |
| terminal noon ET between | val | 63 | 62 | 3,531 | 861 | 187 | 258 | 416 | 37 | 37 | 17 | $111k |
| terminal noon ET between | test | 66 | 63 | 2,436 | 787 | 159 | 297 | 331 | 52 | 52 | 22 | $83k |
| up/down 5m (chainlink) | train | 11,901 | 11,901 | 25,558,484 | 2,380,429 | 928,056 | 737,908 | 714,465 | 11,376 | 11,100 | 1,093 | $82.54M |
| up/down 5m (chainlink) | val | 8,386 | 8,386 | 14,684,582 | 1,358,798 | 489,412 | 459,722 | 409,664 | 8,371 | 8,368 | 731 | $50.41M |
| up/down 5m (chainlink) | test | 6,087 | 6,087 | 9,271,568 | 933,178 | 347,951 | 345,170 | 240,057 | 6,082 | 6,080 | 551 | $36.74M |
| window no-ptb (chainlink) | train | 858 | 858 | 1,581,063 | 168,004 | 58,372 | 52,752 | 56,880 | 811 | 782 | 188 | $5.80M |
| window no-ptb (chainlink) | val | 31 | 31 | 59,509 | 5,187 | 2,295 | 1,585 | 1,307 | 31 | 31 | 3 | $184k |
| up/down 15m (chainlink) | train | 3,016 | 3,016 | 3,540,613 | 329,066 | 101,298 | 108,884 | 118,884 | 2,945 | 2,890 | 987 | $12.30M |
| up/down 15m (chainlink) | val | 2,127 | 2,127 | 2,498,846 | 143,895 | 56,121 | 44,689 | 43,085 | 2,124 | 2,121 | 695 | $8.66M |
| up/down 15m (chainlink) | test | 1,501 | 1,501 | 1,685,048 | 99,981 | 41,209 | 34,059 | 24,713 | 1,501 | 1,497 | 523 | $5.16M |
| up/down 1h (binance) | train | 926 | 925 | 780,483 | 85,667 | 23,629 | 31,971 | 30,067 | 910 | 898 | 883 | $4.89M |
| up/down 1h (binance) | val | 557 | 557 | 415,648 | 34,619 | 9,454 | 11,618 | 13,547 | 550 | 540 | 543 | $2.17M |
| up/down 1h (binance) | test | 439 | 438 | 362,534 | 21,946 | 6,748 | 7,694 | 7,504 | 421 | 412 | 417 | $1.27M |
| up/down 4h (chainlink) | train | 154 | 154 | 30,725 | 15,495 | 2,756 | 6,890 | 5,849 | 154 | 154 | 143 | $799k |
| up/down 4h (chainlink) | val | 144 | 144 | 33,507 | 6,673 | 1,329 | 2,331 | 3,013 | 144 | 142 | 122 | $595k |
| up/down 4h (chainlink) | test | 40 | 40 | 12,378 | 868 | 215 | 346 | 307 | 40 | 40 | 40 | $67k |
| up/down 1d (binance) | train | 96 | 96 | 18,350 | 8,383 | 1,500 | 3,409 | 3,474 | 95 | 94 | 45 | $853k |
| up/down 1d (binance) | val | 60 | 60 | 6,826 | 1,874 | 269 | 384 | 1,221 | 58 | 58 | 30 | $294k |
| up/down 1d (binance) | test | 46 | 46 | 5,963 | 841 | 160 | 328 | 353 | 45 | 44 | 23 | $153k |
| touch day | train | 242 | 220 | 2,832 | 2,288 | 208 | 1,068 | 1,012 | 96 | 96 | 38 | $584k |
| touch day | val | 148 | 139 | 909 | 689 | 15 | 152 | 522 | 47 | 47 | 23 | $162k |
| touch day | test | 125 | 117 | 736 | 485 | 33 | 145 | 307 | 67 | 67 | 22 | $104k |
| touch week | train | 104 | 95 | 261 | 183 | 2 | 124 | 57 | 9 | 9 | 6 | $13k |
| touch week | val | 114 | 100 | 355 | 168 | 5 | 18 | 145 | 21 | 21 | 5 | $63k |
| touch week | test | 84 | 83 | 153 | 107 | 0 | 0 | 107 | 21 | 21 | 4 | $50k |
| touch month | train | 137 | 132 | 129 | 55 | 1 | 3 | 51 | 9 | 9 | 2 | $93k |
| touch month | val | 98 | 96 | 47 | 4 | 0 | 0 | 4 | 2 | 2 | 1 | $12 |
| touch month | test | 86 | 83 | 43 | 23 | 0 | 0 | 23 | 12 | 12 | 1 | $14k |

Notes. The 5-minute and 15-minute rows count the 55 / 45 minutes before the window opens too (prints at about 0.5);
no 0.95+ print falls there (all but 43 of them have a model value, which needs the reference to be public). The
"terminal hourly above" rows are the owner's family on polymarket.com; the four markets are all there is in the
cache, and the three TEST ones have fewer than 50 fills each despite $20,000+ volume (a few large prints). Every family with a 0.95+ print in the last hour has one in most of its markets for the windows (96-100 %),
but only in 29-43 % of the noon-ET "above" strikes: most strikes of a ladder do not trade in the last hour at all.

### T2. Markets per underlying (TRAIN / VAL / TEST): all, and with a buyable print >= 0.95 in the last 60 min

| family | coin | markets | with a >= 0.95 print |
|---|---|---|---|
| terminal hourly above | BTC | 1 / 0 / 3 | 1 / 0 / 0 |
| terminal noon ET above | BTC | 408 / 309 / 244 | 88 / 98 / 78 |
| terminal noon ET above | ETH | 196 / 154 / 138 | 72 / 80 / 74 |
| terminal noon ET above | SOL | 2 / 12 / 3 | 0 / 6 / 2 |
| terminal noon ET above | XRP | 8 / 8 / 0 | 2 / 4 / 0 |
| terminal noon ET below | BTC | 2 / 12 / 21 | 0 / 0 / 2 |
| terminal noon ET below | ETH | 0 / 0 / 1 | 0 / 0 / 0 |
| terminal noon ET between | BTC | 141 / 59 / 59 | 104 / 34 / 45 |
| terminal noon ET between | ETH | 13 / 4 / 6 | 9 / 3 / 6 |
| terminal noon ET between | SOL | 1 / 0 / 1 | 0 / 0 / 1 |
| terminal noon ET between | XRP | 2 / 0 / 0 | 0 / 0 / 0 |
| up/down 5m (chainlink) | BTC | 11,776 / 8,349 / 6,077 | 11,269 / 8,334 / 6,072 |
| up/down 5m (chainlink) | ETH | 94 / 35 / 8 | 78 / 35 / 8 |
| up/down 5m (chainlink) | SOL | 22 / 2 / 2 | 20 / 2 / 2 |
| up/down 5m (chainlink) | XRP | 9 / 0 / 0 | 9 / 0 / 0 |
| window no-ptb (chainlink) | BTC | 853 / 31 / 0 | 806 / 31 / 0 |
| window no-ptb (chainlink) | ETH | 5 / 0 / 0 | 5 / 0 / 0 |
| up/down 15m (chainlink) | BTC | 2,989 / 2,108 / 1,499 | 2,918 / 2,106 / 1,499 |
| up/down 15m (chainlink) | ETH | 21 / 18 / 1 | 21 / 18 / 1 |
| up/down 15m (chainlink) | SOL | 5 / 1 / 1 | 5 / 0 / 1 |
| up/down 15m (chainlink) | XRP | 1 / 0 / 0 | 1 / 0 / 0 |
| up/down 1h (binance) | BTC | 897 / 548 / 433 | 882 / 543 / 417 |
| up/down 1h (binance) | ETH | 23 / 5 / 3 | 23 / 4 / 3 |
| up/down 1h (binance) | SOL | 2 / 0 / 2 | 2 / 0 / 1 |
| up/down 1h (binance) | XRP | 4 / 4 / 1 | 3 / 3 / 0 |
| up/down 4h (chainlink) | BTC | 140 / 122 / 40 | 140 / 122 / 40 |
| up/down 4h (chainlink) | ETH | 10 / 20 / 0 | 10 / 20 / 0 |
| up/down 4h (chainlink) | SOL | 4 / 1 / 0 | 4 / 1 / 0 |
| up/down 4h (chainlink) | XRP | 0 / 1 / 0 | 0 / 1 / 0 |
| up/down 1d (binance) | BTC | 45 / 30 / 23 | 45 / 28 / 23 |
| up/down 1d (binance) | ETH | 44 / 30 / 23 | 43 / 30 / 22 |
| up/down 1d (binance) | SOL | 7 / 0 / 0 | 7 / 0 / 0 |
| touch day | BTC | 204 / 126 / 112 | 79 / 44 / 60 |
| touch day | ETH | 36 / 19 / 13 | 16 / 3 / 7 |
| touch day | SOL | 2 / 0 / 0 | 1 / 0 / 0 |
| touch day | XRP | 0 / 3 / 0 | 0 / 0 / 0 |
| touch week | BTC | 68 / 66 / 49 | 5 / 9 / 8 |
| touch week | ETH | 33 / 40 / 34 | 3 / 11 / 12 |
| touch week | SOL | 1 / 4 / 0 | 1 / 1 / 0 |
| touch week | XRP | 2 / 4 / 1 | 0 / 0 / 1 |
| touch month | BTC | 42 / 34 / 28 | 3 / 0 / 3 |
| touch month | ETH | 39 / 33 / 28 | 3 / 0 / 4 |
| touch month | SOL | 30 / 15 / 19 | 1 / 1 / 3 |
| touch month | XRP | 26 / 16 / 11 | 2 / 1 / 2 |

## 2. Distance from the strike, in volatility units

For each buyable 0.95+ print, `z = Phi^-1(q)`, where `q` is lab 5's FIXED fair value of the side bought (zero-drift
lognormal; noon-ET ladders and touches use the trailing 1-day realized volatility, windows the trailing 1 hour;
Chainlink windows go through the Binance proxy with lab 5's 0.75 bp basis noise), read from Binance spot 10 s
before the print. For an "above" strike `z` is the plain distance `ln(S / K) / (sigma sqrt(tau))`; for a range or a
touch it is the distance-equivalent of `q`. `q` = 1 to machine precision shows as `z >= 6` (an already-touched
barrier, or a strike tens of sigmas away). Nothing here says whether the side won.

### T3. Markets (and independent clusters) with a buyable print at price floor X AND distance z >= k in the last hour

| family | split | >= 0.95 & z >= 2 | >= 0.95 & z >= 3 | >= 0.95 & z >= 4 | >= 0.95 & z >= 5 | >= 0.97 & z >= 2 | >= 0.97 & z >= 3 | >= 0.97 & z >= 4 | >= 0.97 & z >= 5 | >= 0.99 & z >= 2 | >= 0.99 & z >= 3 | >= 0.99 & z >= 4 | >= 0.99 & z >= 5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| terminal hourly above | train | 1 (1) | 1 (1) | 1 (1) | 1 (1) | 1 (1) | 1 (1) | 1 (1) | 1 (1) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| terminal noon ET above | train | 159 (41) | 156 (41) | 153 (41) | 141 (41) | 159 (41) | 156 (41) | 153 (41) | 141 (41) | 158 (41) | 155 (41) | 153 (41) | 141 (41) |
| terminal noon ET above | val | 188 (31) | 183 (31) | 177 (31) | 164 (31) | 188 (31) | 183 (31) | 177 (31) | 164 (31) | 188 (31) | 182 (31) | 176 (31) | 163 (31) |
| terminal noon ET above | test | 153 (23) | 147 (23) | 145 (23) | 135 (23) | 153 (23) | 147 (23) | 145 (23) | 135 (23) | 151 (23) | 147 (23) | 145 (23) | 135 (23) |
| terminal noon ET below | test | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) | 2 (2) |
| terminal noon ET between | train | 109 (41) | 104 (41) | 99 (41) | 94 (41) | 109 (41) | 104 (41) | 99 (41) | 94 (41) | 108 (41) | 103 (41) | 99 (41) | 94 (41) |
| terminal noon ET between | val | 37 (17) | 35 (17) | 33 (16) | 31 (16) | 37 (17) | 35 (17) | 33 (16) | 31 (16) | 37 (17) | 35 (17) | 33 (16) | 31 (16) |
| terminal noon ET between | test | 52 (22) | 48 (22) | 44 (22) | 41 (21) | 52 (22) | 48 (22) | 44 (22) | 41 (21) | 50 (22) | 48 (22) | 44 (22) | 41 (21) |
| up/down 5m (chainlink) | train | 5,139 (1,074) | 1,993 (887) | 876 (587) | 446 (357) | 5,065 (1,072) | 1,973 (882) | 868 (585) | 444 (357) | 4,879 (1,071) | 1,903 (870) | 850 (576) | 436 (354) |
| up/down 5m (chainlink) | val | 3,717 (720) | 1,039 (518) | 371 (283) | 193 (165) | 3,665 (719) | 1,020 (514) | 366 (281) | 192 (164) | 3,512 (716) | 947 (498) | 343 (268) | 180 (157) |
| up/down 5m (chainlink) | test | 2,434 (538) | 630 (351) | 223 (177) | 99 (92) | 2,383 (538) | 612 (348) | 223 (177) | 99 (92) | 2,236 (535) | 563 (333) | 206 (168) | 92 (87) |
| up/down 15m (chainlink) | train | 2,041 (900) | 1,405 (781) | 920 (622) | 534 (414) | 2,019 (896) | 1,396 (779) | 916 (618) | 533 (413) | 1,964 (884) | 1,376 (771) | 911 (617) | 529 (412) |
| up/down 15m (chainlink) | val | 1,419 (624) | 797 (490) | 498 (365) | 328 (260) | 1,388 (623) | 788 (486) | 497 (365) | 326 (259) | 1,314 (616) | 759 (478) | 486 (361) | 324 (257) |
| up/down 15m (chainlink) | test | 944 (466) | 557 (361) | 362 (274) | 232 (197) | 921 (460) | 551 (360) | 361 (274) | 230 (195) | 867 (451) | 529 (353) | 355 (270) | 230 (195) |
| up/down 1h (binance) | train | 784 (762) | 633 (623) | 444 (438) | 249 (246) | 777 (755) | 633 (623) | 444 (438) | 248 (245) | 762 (742) | 627 (617) | 441 (435) | 247 (244) |
| up/down 1h (binance) | val | 469 (466) | 349 (348) | 216 (215) | 132 (132) | 466 (463) | 347 (346) | 215 (214) | 131 (131) | 460 (458) | 337 (336) | 211 (210) | 128 (128) |
| up/down 1h (binance) | test | 354 (352) | 240 (240) | 132 (132) | 69 (69) | 350 (348) | 239 (239) | 132 (132) | 69 (69) | 338 (336) | 233 (233) | 130 (130) | 69 (69) |
| up/down 4h (chainlink) | train | 149 (141) | 141 (134) | 127 (122) | 108 (105) | 149 (141) | 141 (134) | 127 (122) | 108 (105) | 149 (141) | 140 (133) | 126 (121) | 107 (104) |
| up/down 4h (chainlink) | val | 140 (121) | 132 (114) | 126 (109) | 112 (101) | 139 (120) | 129 (111) | 125 (108) | 111 (100) | 137 (118) | 128 (110) | 123 (106) | 109 (98) |
| up/down 4h (chainlink) | test | 35 (35) | 30 (30) | 23 (23) | 15 (15) | 34 (34) | 30 (30) | 22 (22) | 15 (15) | 34 (34) | 30 (30) | 22 (22) | 15 (15) |
| up/down 1d (binance) | train | 93 (45) | 89 (45) | 74 (42) | 58 (37) | 93 (45) | 89 (45) | 74 (42) | 58 (37) | 91 (45) | 89 (45) | 74 (42) | 58 (37) |
| up/down 1d (binance) | val | 56 (29) | 55 (29) | 48 (28) | 37 (24) | 56 (29) | 55 (29) | 48 (28) | 37 (24) | 56 (29) | 55 (29) | 48 (28) | 37 (24) |
| up/down 1d (binance) | test | 41 (21) | 38 (21) | 33 (19) | 27 (17) | 41 (21) | 38 (21) | 33 (19) | 27 (17) | 40 (21) | 37 (21) | 33 (19) | 27 (17) |
| touch day | train | 96 (38) | 96 (38) | 96 (38) | 90 (37) | 96 (38) | 96 (38) | 96 (38) | 90 (37) | 96 (38) | 96 (38) | 96 (38) | 90 (37) |
| touch day | val | 47 (23) | 47 (23) | 47 (23) | 41 (21) | 47 (23) | 47 (23) | 47 (23) | 41 (21) | 47 (23) | 47 (23) | 47 (23) | 41 (21) |
| touch day | test | 67 (22) | 67 (22) | 64 (22) | 59 (22) | 67 (22) | 67 (22) | 64 (22) | 59 (22) | 67 (22) | 67 (22) | 64 (22) | 59 (22) |
| touch week | train | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) | 9 (6) |
| touch week | val | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) | 21 (5) |
| touch week | test | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) | 21 (4) |
| touch month | train | 9 (2) | 9 (2) | 9 (2) | 9 (2) | 9 (2) | 9 (2) | 9 (2) | 9 (2) | 8 (2) | 8 (2) | 8 (2) | 8 (2) |
| touch month | val | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) | 2 (1) |
| touch month | test | 12 (1) | 12 (1) | 11 (1) | 11 (1) | 12 (1) | 12 (1) | 11 (1) | 11 (1) | 12 (1) | 12 (1) | 11 (1) | 11 (1) |

Reading T3: a distance filter costs the noon-ET ladders almost nothing (their last-hour 0.95+ prints are already
far: median z 6.0 at the first one) and costs the windows a lot (the 5-minute market reaches 0.95 at a median z of
0.9 in Binance-proxy units; likely because in its final seconds the market sees the Chainlink value directly while
the proxy carries lab 5's 0.75 bp basis noise, which caps how far it can call a close race). The price floor matters
little: T3's 0.99 columns are within about 10 % of its 0.95 columns.

### T4. Distance at the FIRST buyable >= 0.95 print of each market (markets by z = Phi^-1(q), lab 5's model, spot 10 s old)

| family | split | z <0 | z 0-1 | z 1-2 | z 2-3 | z 3-4 | z 4-5 | z 5-6 | z >=6 | no model |
|---|---|---|---|---|---|---|---|---|---|---|
| terminal hourly above | train | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| terminal noon ET above | train | 0 | 2 | 20 | 24 | 18 | 11 | 14 | 73 | 0 |
| terminal noon ET above | val | 0 | 1 | 18 | 28 | 13 | 15 | 14 | 99 | 0 |
| terminal noon ET above | test | 0 | 0 | 20 | 19 | 13 | 11 | 12 | 79 | 0 |
| terminal noon ET below | test | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| terminal noon ET between | train | 0 | 2 | 25 | 20 | 16 | 7 | 10 | 33 | 0 |
| terminal noon ET between | val | 0 | 0 | 11 | 9 | 2 | 3 | 2 | 10 | 0 |
| terminal noon ET between | test | 0 | 0 | 15 | 10 | 6 | 6 | 1 | 14 | 0 |
| up/down 5m (chainlink) | train | 894 | 5346 | 4614 | 447 | 57 | 10 | 2 | 2 | 4 |
| up/down 5m (chainlink) | val | 476 | 4196 | 3482 | 194 | 18 | 3 | 1 | 1 | 0 |
| up/down 5m (chainlink) | test | 290 | 3149 | 2541 | 93 | 7 | 2 | 0 | 0 | 0 |
| window no-ptb (chainlink) | train | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 811 |
| window no-ptb (chainlink) | val | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 31 |
| up/down 15m (chainlink) | train | 93 | 1073 | 1679 | 95 | 4 | 0 | 0 | 0 | 1 |
| up/down 15m (chainlink) | val | 88 | 562 | 1258 | 197 | 15 | 3 | 0 | 1 | 0 |
| up/down 15m (chainlink) | test | 44 | 387 | 919 | 141 | 10 | 0 | 0 | 0 | 0 |
| up/down 1h (binance) | train | 6 | 159 | 672 | 68 | 4 | 0 | 1 | 0 | 0 |
| up/down 1h (binance) | val | 3 | 97 | 418 | 28 | 3 | 1 | 0 | 0 | 0 |
| up/down 1h (binance) | test | 4 | 55 | 309 | 52 | 1 | 0 | 0 | 0 | 0 |
| up/down 4h (chainlink) | train | 1 | 11 | 73 | 51 | 12 | 5 | 1 | 0 | 0 |
| up/down 4h (chainlink) | val | 2 | 7 | 82 | 40 | 7 | 4 | 0 | 2 | 0 |
| up/down 4h (chainlink) | test | 1 | 4 | 23 | 10 | 0 | 1 | 0 | 1 | 0 |
| up/down 1d (binance) | train | 0 | 4 | 33 | 24 | 16 | 11 | 3 | 4 | 0 |
| up/down 1d (binance) | val | 0 | 3 | 19 | 8 | 14 | 5 | 3 | 6 | 0 |
| up/down 1d (binance) | test | 0 | 4 | 16 | 9 | 4 | 3 | 1 | 8 | 0 |
| touch day | train | 0 | 0 | 5 | 11 | 12 | 8 | 8 | 52 | 0 |
| touch day | val | 0 | 1 | 2 | 7 | 3 | 6 | 7 | 21 | 0 |
| touch day | test | 0 | 1 | 5 | 5 | 2 | 8 | 8 | 38 | 0 |
| touch week | train | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 8 | 0 |
| touch week | val | 0 | 0 | 0 | 1 | 0 | 0 | 2 | 18 | 0 |
| touch week | test | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 20 | 0 |
| touch month | train | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 8 | 0 |
| touch month | val | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| touch month | test | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 11 | 0 |

### T5. Time left at the first buyable >= 0.95 print (markets)

| family | split | 0-5 min | 5-15 min | 15-30 min | 30-60 min | median min left |
|---|---|---|---|---|---|---|
| terminal hourly above | train | 0 | 0 | 0 | 1 | 33 |
| terminal noon ET above | train | 6 | 6 | 5 | 145 | 59 |
| terminal noon ET above | val | 4 | 7 | 14 | 163 | 56 |
| terminal noon ET above | test | 8 | 6 | 8 | 132 | 55 |
| terminal noon ET below | test | 0 | 0 | 0 | 2 | 38 |
| terminal noon ET between | train | 8 | 8 | 9 | 88 | 54 |
| terminal noon ET between | val | 2 | 6 | 5 | 24 | 46 |
| terminal noon ET between | test | 3 | 5 | 11 | 33 | 40 |
| up/down 5m (chainlink) | train | 11373 | 3 | 0 | 0 | 1 |
| up/down 5m (chainlink) | val | 8371 | 0 | 0 | 0 | 2 |
| up/down 5m (chainlink) | test | 6082 | 0 | 0 | 0 | 2 |
| window no-ptb (chainlink) | train | 738 | 70 | 0 | 3 | 1 |
| window no-ptb (chainlink) | val | 30 | 1 | 0 | 0 | 2 |
| up/down 15m (chainlink) | train | 1842 | 1103 | 0 | 0 | 4 |
| up/down 15m (chainlink) | val | 1451 | 673 | 0 | 0 | 3 |
| up/down 15m (chainlink) | test | 1040 | 461 | 0 | 0 | 3 |
| up/down 1h (binance) | train | 175 | 293 | 319 | 123 | 15 |
| up/down 1h (binance) | val | 129 | 170 | 180 | 71 | 14 |
| up/down 1h (binance) | test | 125 | 133 | 125 | 38 | 12 |
| up/down 4h (chainlink) | train | 9 | 11 | 22 | 112 | 56 |
| up/down 4h (chainlink) | val | 21 | 17 | 24 | 82 | 38 |
| up/down 4h (chainlink) | test | 7 | 10 | 3 | 20 | 28 |
| up/down 1d (binance) | train | 3 | 3 | 10 | 79 | 55 |
| up/down 1d (binance) | val | 0 | 3 | 9 | 46 | 55 |
| up/down 1d (binance) | test | 4 | 2 | 8 | 31 | 50 |
| touch day | train | 0 | 2 | 4 | 90 | 55 |
| touch day | val | 0 | 1 | 4 | 42 | 53 |
| touch day | test | 0 | 1 | 10 | 56 | 52 |
| touch week | train | 0 | 0 | 0 | 9 | 57 |
| touch week | val | 0 | 1 | 2 | 18 | 49 |
| touch week | test | 0 | 1 | 4 | 16 | 44 |
| touch month | train | 0 | 1 | 2 | 6 | 56 |
| touch month | val | 0 | 1 | 0 | 1 | 28 |
| touch month | test | 0 | 2 | 5 | 5 | 26 |

### T6. Dollar notional of buyable >= 0.95 prints in the last 60 min, by distance z at the print

| family | split | z < 2 | z 2-3 | z 3-4 | z 4-5 | z >= 5 | no model |
|---|---|---|---|---|---|---|---|
| terminal hourly above | train | $10 | $20 | $88 | $0 | $551 | $0 |
| terminal noon ET above | train | $156k | $238k | $300k | $293k | $1.43M | $0 |
| terminal noon ET above | val | $63k | $184k | $179k | $174k | $1.39M | $0 |
| terminal noon ET above | test | $92k | $136k | $144k | $194k | $634k | $0 |
| terminal noon ET below | test | $0 | $0 | $0 | $0 | $302 | $0 |
| terminal noon ET between | train | $85k | $148k | $83k | $50k | $166k | $0 |
| terminal noon ET between | val | $17k | $21k | $12k | $11k | $49k | $0 |
| terminal noon ET between | test | $8k | $13k | $13k | $10k | $39k | $0 |
| up/down 5m (chainlink) | train | $54.01M | $20.75M | $5.45M | $1.48M | $847k | $15k |
| up/down 5m (chainlink) | val | $36.85M | $11.09M | $1.78M | $420k | $274k | $0 |
| up/down 5m (chainlink) | test | $27.64M | $7.43M | $1.16M | $328k | $184k | $0 |
| window no-ptb (chainlink) | train | $0 | $0 | $0 | $0 | $0 | $5.80M |
| window no-ptb (chainlink) | val | $0 | $0 | $0 | $0 | $0 | $184k |
| up/down 15m (chainlink) | train | $6.13M | $3.59M | $1.30M | $670k | $600k | $301 |
| up/down 15m (chainlink) | val | $3.08M | $2.70M | $1.43M | $652k | $797k | $0 |
| up/down 15m (chainlink) | test | $2.46M | $1.63M | $596k | $262k | $216k | $0 |
| up/down 1h (binance) | train | $1.51M | $1.62M | $865k | $466k | $434k | $0 |
| up/down 1h (binance) | val | $733k | $691k | $427k | $189k | $134k | $0 |
| up/down 1h (binance) | test | $368k | $482k | $229k | $94k | $101k | $0 |
| up/down 4h (chainlink) | train | $124k | $168k | $102k | $94k | $311k | $0 |
| up/down 4h (chainlink) | val | $76k | $105k | $91k | $72k | $251k | $0 |
| up/down 4h (chainlink) | test | $12k | $11k | $11k | $8k | $25k | $0 |
| up/down 1d (binance) | train | $229k | $145k | $215k | $100k | $164k | $0 |
| up/down 1d (binance) | val | $48k | $48k | $60k | $70k | $67k | $0 |
| up/down 1d (binance) | test | $28k | $38k | $15k | $18k | $54k | $0 |
| touch day | train | $10k | $34k | $39k | $51k | $451k | $0 |
| touch day | val | $2k | $16k | $52k | $20k | $71k | $0 |
| touch day | test | $3k | $10k | $20k | $10k | $61k | $0 |
| touch week | train | $0 | $2k | $49 | $1k | $9k | $0 |
| touch week | val | $0 | $696 | $20 | $649 | $62k | $0 |
| touch week | test | $0 | $0 | $0 | $92 | $50k | $0 |
| touch month | train | $0 | $0 | $0 | $0 | $93k | $0 |
| touch month | val | $0 | $0 | $0 | $0 | $12 | $0 |
| touch month | test | $0 | $982 | $25 | $0 | $13k | $0 |

### T7. Binance 1 s coverage at the decision second (spot read 10 s before each buyable >= 0.95 print), all splits

| family | buyable >= 0.95 prints | exact 1 s candle | stale <= 5 s | stale > 5 s | no spot | volatility defined |
|---|---|---|---|---|---|---|
| terminal hourly above | 8 | 8 | 0 | 0 | 0 | 8 |
| terminal noon ET above | 16,682 | 16,682 | 0 | 0 | 0 | 16,682 |
| terminal noon ET below | 4 | 4 | 0 | 0 | 0 | 4 |
| terminal noon ET between | 6,279 | 6,279 | 0 | 0 | 0 | 6,279 |
| up/down 5m (chainlink) | 4,672,405 | 4,672,405 | 0 | 0 | 0 | 4,672,405 |
| window no-ptb (chainlink) | 173,191 | 173,191 | 0 | 0 | 0 | 0 |
| up/down 15m (chainlink) | 572,942 | 572,942 | 0 | 0 | 0 | 572,942 |
| up/down 1h (binance) | 142,232 | 142,232 | 0 | 0 | 0 | 142,232 |
| up/down 4h (chainlink) | 23,036 | 23,036 | 0 | 0 | 0 | 23,036 |
| up/down 1d (binance) | 11,098 | 11,098 | 0 | 0 | 0 | 11,098 |
| touch day | 3,462 | 3,462 | 0 | 0 | 0 | 3,462 |
| touch week | 458 | 458 | 0 | 0 | 0 | 458 |
| touch month | 82 | 82 | 0 | 0 | 0 | 82 |

## 3. Do these markets match the Polymarket US families?

US rules from the gateway's own market descriptions (`/v1/events?categories=crypto`, open and closed listings read
2026-10-12 ~14:50 UTC; `research/lab4/US/evidence_2026-10-10/forensics/gw_parsed.json` for 10-09/10). The US venue
lists **only Bitcoin**: 685 open crypto markets (678 BTC price markets, 7 non-price), no ETH, SOL or XRP.
`research/lab4/US/venue_map.md` names the `cpc-` prefix (crypto price contracts, bought in their last hour) but
does not describe their rules; it is otherwise a sports map.

| US family (slug) | US rule | settled on the US venue so far | closest family in the cache (markets) | its rule | same instant? | same source? |
|---|---|---|---|---|---|---|
| `cpc-btc-above-hr`: "BTC price at 10:00 AM ET, $81,900 or above" (the owner's example) | Yes if the simple average of the 60 BRTI prices in the minute before the hour >= strike | 158 hours, 26,682 strikes, since 2026-10-05 22:00 UTC | `bitcoin-multi-strikes-hourly` "Bitcoin above 63,000 on August 1, 9PM ET?" (**4**; 45,160 on Gamma) | Binance BTC/USDT 1-hour candle ending at the hour: close > strike | yes (same hour; last trade vs 60-s average) | **no** |
| `cpc-btc-range-hr` ($100 buckets at the hour) | 60-s BRTI average inside [L, U] | 158 hours, 26,840 | none hourly; the noon-ET "between" ladders are daily (286) | Binance 12:00 ET 1-minute close in [L, U) | no | no |
| `cpc-btc-above-day` / `range-day` (5:00 PM ET) | as above, at 17:00 ET | 6 days, 238 / 244 | noon-ET ladders "Will the price of Bitcoin be above $X on <date>?" (1,482 above, 36 below, 286 between) | Binance BTC/USDT 1-minute candle of 12:00 ET, its close (lab 5 replicated 774 / 774 TRAIN settlements) | **no** (12:00 vs 17:00 ET) | no |
| `cpc-btc-above-wk` / `range-wk` (Friday 5:00 PM ET) | as above, Friday 17:00 ET | 1 week, 59 / 60 | the same noon-ET ladders (polymarket.com's `btc-multi-strikes-weekly` series also settles at noon ET on the date in its title) | as above | no | no |
| `cpc-btc-updown-15m` | Up if the 60-s BRTI average at the end >= at the start | 1,922 since 2026-09-22 | `btc-up-or-down-15m` (6,644) | Chainlink BTC/USD stream (spot until ~08-08, then a 30 / 60 s TWAP), end >= `priceToBeat` | yes (same quarter-hours) | no |
| `cpc-btc-updown-1h` | as above, hourly | 497 since 2026-09-22 | `btc-up-or-down-hourly` (1,922) | Binance BTC/USDT 1-hour candle close >= open | yes (same ET hour) | no |
| `cpc-btc-updown-1d` (5 PM to 5 PM ET) | as above, daily | 8 | `btc-up-or-down-daily` (202) | Binance 12:00 ET 1-minute close vs the previous day's, strictly higher | no | no |
| none (US series exist with no events) | | 0 | 5-minute (26,374 + 889 without `priceToBeat`) and 4-hour (338) up/down, Chainlink | | no US twin | |
| `cpc-btc-hit-h/l-w`, `hit-h/l-m`, yearly "hit", "$150k by" | touch: a 60-second BRTI mean with the top and bottom 20 % trimmed, at or beyond the barrier at any time in the period | 17 (2 weekly events) | `bitcoin-hit-price-daily / weekly / monthly` (515 / 302 / 321) | any Binance 1-minute high / low at or beyond the barrier: one wick is enough | weeks differ (US Friday 5 PM to Friday 5 PM; .com ET calendar days); months align | **no, and a trimmed 60-s mean is much harder to touch than a wick** |

So: no cached family is a same-source, same-instant twin of a US family. The basis is small at a distance (the
parallel venue read measured BRTI 3.7 bp below Binance on average, sd 2.9 bp, worst 13.6 bp, over 4,823 minutes;
`us_venue.md`), so a 3-sigma lead (about 0.7 % with 24 minutes left) is not decided by the source; next to the
strike it is. A US rule tested on this history is tested on a proxy venue: other traders, other books, other fees
(polymarket.com crypto 0.07 x p x (1 - p) per share; US 0.0695).

## 4. Binance 1-second coverage (lab 5's cache)

| coin | days | 1-second rows | missing seconds | gaps of 2 s or more | duplicate seconds |
|---|---|---|---|---|---|
| BTC | 130 | 11,232,000 | 0 | 0 | 0 |
| ETH | 130 | 11,232,000 | 0 | 0 | 0 |
| SOL | 130 | 11,232,000 | 0 | 0 | 0 |
| XRP | 130 | 11,232,000 | 0 | 0 | 0 |

Range 2026-06-01 00:00 .. 2026-10-08 23:59:59 UTC (11,232,000 seconds), so the 7-day volatility of the first TRAIN
day is covered. Table T7 above: every buyable 0.95+ print of the last hour has its exact 1-second candle at the
decision second; no print needs a forward-filled price. Volatility scale (BTC, trailing 1 day, sampled hourly over
the cache): median 3.99e-9 per second (35.5 % a year), 10th percentile 1.15e-9 (19.0 %), 90th 1.01e-8 (56.4 %).
**Gaps that do exist:** none inside the range; the cache stops at 10-08 (the Polymarket US live period 10-09 ..
10-12 is not in it; Binance's daily 1-second files for 10-09, 10-10, 10-11 are published, 1.9-2.3 MB each for BTC);
BRTI history is not in any cache (the gateway serves BRTI only since 2026-10-05 15:22 UTC, per `us_venue.md`;
CF Benchmarks' history is licensed); Coinbase's public 1-minute BTC-USD candles answer from here (HTTP 200, 300
candles a request) and are the obvious free USD proxy if a longer BRTI-like series is needed.

## 5. Outside the cache: polymarket.com's hourly strikes (the owner's family)

Gamma `/events?series_id=11372` (BTC) and `11373` (ETH), one call per series and day, endDate 2026-07-01 ..
10-09 (200 calls, ~26 MB transferred). Listing fields only; outcome prices not kept. Series ids from
`/series?slug=bitcoin-multi-strikes-hourly` / `ethereum-multi-strikes-hourly`; no SOL / XRP hourly series and no
hourly range series exist. Every market is fee-enabled (`crypto_fees_v2`); 81,156 of the 81,228 name Binance
BTC/USDT or ETH/USDT as the source (72 leave it blank) and settle on its 1-hour candle.

| coin | split | hourly events | strikes | strikes that traded | traded $1,000+ | traded $20,000+ (in lab 4's cache) | dollars traded | median $ of a traded strike |
|---|---|---|---|---|---|---|---|---|
| BTC | train | 966 | 19,320 | 15,880 | 370 | 1 | $2.75M | $115 |
| BTC | val | 740 | 14,800 | 10,386 | 129 | 0 | $815k | $15 |
| BTC | test | 552 | 11,040 | 7,834 | 44 | 3 | $544k | $15 |
| ETH | train | 961 | 15,376 | 12,923 | 96 | 0 | $1.73M | $115 |
| ETH | val | 739 | 11,824 | 8,360 | 45 | 0 | $445k | $15 |
| ETH | test | 552 | 8,832 | 6,298 | 13 | 0 | $199k | $15 |

36 more markets closed after 10-08 (lab 4's shadow set). A ladder has 20 strikes (BTC) or 16 (ETH); the US ladder
has 167-171.

**Tape sample** (data API `/trades`, public): every BTC strike with volume > 0 on one day of each split, counted
exactly like T1:

| day | split | traded strikes | fills | median fills | strikes with >= 50 fills | strikes with a buyable >= 0.95 print in the last hour | such prints | of which >= 0.99 | $ notional >= 0.95 |
|---|---|---|---|---|---|---|---|---|---|
| 2026-07-15 | train | 364 | 1,080 | 1 | 0 | 341 (94 %) | 641 | 557 | $55,371 |
| 2026-08-25 | val | 336 | 1,209 | 1 | 0 | 309 (92 %) | 382 | 348 | $8,046 |
| 2026-09-25 | test | 328 | 882 | 1 | 0 | 299 (91 %) | 365 | 346 | $5,491 |

The typical tape is one taker buying the near-certain side (YES of strikes far below spot, NO of strikes far above;
654 and 734 of the 1,388 sample prints) at 0.999 (median price; 10th percentile 0.99), for about $20 (median print;
90th percentile $115): the grind is already being done there, in very small size (median $25 of 0.95+ notional per
traded strike). **Cost of the full family:** about 61,700 traded strikes (BTC 34,100, ETH
27,581), one data-API request each: ~17 hours at the sample's pace (~1 s a market), 4-5 hours with four workers
inside the data API's ~20 requests a second; ~100 MB transferred, ~300 MB as one parquet per market (5 KB each,
mostly overhead), a few MB as one table. Lab 4's 50-fill rule would drop every one of them, so a lab 8 test on this
family needs its own pre-registered universe rule, and each "bet" would be a single historical print.

## 6. Binance monthly 1-minute klines, 2019-01 .. 2026-05 (BTCUSDT, ETHUSDT, SOLUSDT)

HEAD of every archive `https://data.binance.vision/data/spot/monthly/klines/<SYM>/1m/<SYM>-1m-<YYYY-MM>.zip`
(267 requests, sizes only), and two months downloaded, checksummed (`.CHECKSUM`, sha256) and parsed with lab 5's
`parse_klines` (milliseconds before 2025, microseconds after; both handled).

| coin | months present | first month | zipped total | per month | not present |
|---|---|---|---|---|---|
| BTCUSDT | 89 | 2019-01 | 193.3 MB | 1.92-2.41 MB | - |
| ETHUSDT | 89 | 2019-01 | 180.4 MB | 1.75-2.31 MB | - |
| SOLUSDT | 70 | 2020-08 | 121.3 MB | 0.96-2.01 MB | 2019-01 .. 2020-07 (19, before listing) |
| all three | 248 | | **495.1 MB** | | |

| sample | zip | sha256 | rows | missing minutes | parquet (ts + OHLC) |
|---|---|---|---|---|---|
| BTCUSDT-2019-01 | 2.12 MB | ok | 44,640 | 0 | 1.01 MB |
| BTCUSDT-2026-05 | 2.12 MB | ok | 44,640 | 0 | 1.31 MB |

Feasible: ~495 MB to download (inside the ~1 GB budget, see the tally below), ~250-330 MB as parquet (+~25 % with
volume), ~500 requests (archive + checksum), about 10 minutes. The zips can be deleted after conversion; disk free
now 5.5 GB. XRPUSDT (not asked for) would add about the same as ETH.

## 7. What the counts mean for lab 8's plan (arithmetic, not results)

* **Payoff shape.** At price p a win pays (1 - p - fee) / p per dollar and a loss costs about 1. Break-even win rate
  (polymarket.com fee 0.07 x p x (1 - p); the US venue's cent rounding moves it to about 0.991 at 0.99): 0.95332 at
  0.95, 0.97204 at 0.97, **0.99069 at 0.99**. One loss wipes 20 wins at 0.95, 35 at 0.97, **106 at 0.99**.
* **Lab 4's bar** (at least 100 bets, CI lower bound > 0, at least one loss, rule-of-three worst case positive with
  fewer than five losses) needs, with almost no losses, at least **65** independent bets at 0.95, **108** at 0.97,
  **323** at 0.99. To show a true 99.5 % win rate at 0.99 (about +0.4 c per $) with a CI95 above zero takes about
  **1,030** independent bets. Bets inside one cluster (one day for the ladders, one hour for the windows) are not
  independent.
* **Where that many exist** (T3, TRAIN, 0.97 and z >= 3): 5-minute 882 hours, 15-minute 779, hourly up/down 623;
  then 4-hour 134, daily up/down 45, noon-ET ladders 41 days, daily touch 38. So a 0.99 grind can only reach lab 4's
  bar on the up/down windows, and those are the families whose blanket version lab 4 (P3) already found NO EDGE
  in, and whose distance is measured through a proxy. The noon-ET ladders, the closest thing to the owner's market,
  have 156 bets in TRAIN but only 41 independent days: lab 4's bar counts bets (156 clears the 108 needed at 0.97,
  not the 323 needed at 0.99), while its bootstrap resamples days, so 41 draws set the interval.
* **Scale.** T6 is the ceiling on what the history could absorb: in the noon-ET "above" ladders, all buyable 0.95+
  prints at z >= 4 in the last hour add up to about $1.7M in TRAIN over 46 days (about $37k a day across BTC and
  ETH); on the US venue the owner's market traded $165 in its whole life.

## Files, stages, downloads

* `research/lab8/inventory.py`, stages (run with `python -I`): `tapes` (T1-T7 counts, ~20 min cold, 3 min warm, 4
  processes), `spot-gaps`, `gamma-hourly`, `hourly-sample --days 2026-07-15 2026-08-25 2026-09-25`,
  `binance-probe`, `us-venue`, `example`, `report` (writes `inventory.json` and the table files under
  `$SCRATCH/lab8/inv`; this page's prose was written from them).
* Out of git, `$SCRATCH/lab8/inv`: `tape_counts.parquet` (one row per market), `gamma_hourly.parquet` (81,228
  listed hourly strikes), `hourly_sample/` (1,028 tapes), `binance_probe/` (two sample months), `us/` (US listing
  summary, the example's book and Coinbase candles, raw closed pages as `closed_pages.tgz`), `spot_gaps.json`.
* Downloaded today, about **235 MB** in all: Gamma ~26 MB (288 MB decoded), US gateway ~195 MB (the closed listing
  read twice, once uncompressed), data API ~5 MB, Binance 4.2 MB plus 270 HEADs, Coinbase 0.1 MB.
* Not used: `$SCRATCH/lab8/raw` (another session's US pulls); `research/lab8/us_venue.md` is that session's map of
  the US venue and is cited above only where it measured something this inventory could not (BRTI).

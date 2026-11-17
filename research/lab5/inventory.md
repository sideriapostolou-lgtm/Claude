# Lab 5 inventory: crypto price markets in lab 4's cache

Run 2026-10-09T20:30:00+00:00. Crypto-family markets in lab 4's cache: 39796 (Gamma rules fetched for 39796). In the lab 5 universe (binary, one winner, a parsed price contract on BTC / ETH / SOL / XRP, closed 2026-07-01 .. 2026-10-08): 38426; usable (>= 50 fills and >= 1 buyable print inside an entry window with a model value): 38145.

## Per hypothesis and split

| hyp | split | markets | usable |
|---|---|---|---|
| S1 | test | 476 | 440 |
| S1 | train | 774 | 707 |
| S1 | val | 558 | 514 |
| S2 | test | 8113 | 8111 |
| S2 | train | 16093 | 16092 |
| S2 | val | 11274 | 11274 |
| S3 | test | 295 | 265 |
| S3 | train | 483 | 435 |
| S3 | val | 360 | 307 |

## By type, underlying, horizon and resolution source

| hyp | kind | type | underlying | source | horizon | split | markets | usable |
|---|---|---|---|---|---|---|---|---|
| S1 | terminal | above | BTCUSDT | binance | 1h close | test | 3 | 0 |
| S1 | terminal | above | BTCUSDT | binance | 1h close | train | 1 | 1 |
| S1 | terminal | above | BTCUSDT | binance | noon ET close | test | 244 | 230 |
| S1 | terminal | above | BTCUSDT | binance | noon ET close | train | 408 | 356 |
| S1 | terminal | above | BTCUSDT | binance | noon ET close | val | 309 | 278 |
| S1 | terminal | above | ETHUSDT | binance | noon ET close | test | 138 | 129 |
| S1 | terminal | above | ETHUSDT | binance | noon ET close | train | 196 | 187 |
| S1 | terminal | above | ETHUSDT | binance | noon ET close | val | 154 | 150 |
| S1 | terminal | above | SOLUSDT | binance | noon ET close | test | 3 | 3 |
| S1 | terminal | above | SOLUSDT | binance | noon ET close | train | 2 | 2 |
| S1 | terminal | above | SOLUSDT | binance | noon ET close | val | 12 | 10 |
| S1 | terminal | above | XRPUSDT | binance | noon ET close | train | 8 | 5 |
| S1 | terminal | above | XRPUSDT | binance | noon ET close | val | 8 | 7 |
| S1 | terminal | below | BTCUSDT | binance | noon ET close | test | 21 | 15 |
| S1 | terminal | below | BTCUSDT | binance | noon ET close | train | 2 | 1 |
| S1 | terminal | below | BTCUSDT | binance | noon ET close | val | 12 | 7 |
| S1 | terminal | below | ETHUSDT | binance | noon ET close | test | 1 | 0 |
| S1 | terminal | between | BTCUSDT | binance | noon ET close | test | 59 | 56 |
| S1 | terminal | between | BTCUSDT | binance | noon ET close | train | 141 | 140 |
| S1 | terminal | between | BTCUSDT | binance | noon ET close | val | 59 | 58 |
| S1 | terminal | between | ETHUSDT | binance | noon ET close | test | 6 | 6 |
| S1 | terminal | between | ETHUSDT | binance | noon ET close | train | 13 | 12 |
| S1 | terminal | between | ETHUSDT | binance | noon ET close | val | 4 | 4 |
| S1 | terminal | between | SOLUSDT | binance | noon ET close | test | 1 | 1 |
| S1 | terminal | between | SOLUSDT | binance | noon ET close | train | 1 | 1 |
| S1 | terminal | between | XRPUSDT | binance | noon ET close | train | 2 | 2 |
| S2 | window | 15m | BTCUSDT | chainlink | 15m | test | 1499 | 1499 |
| S2 | window | 15m | BTCUSDT | chainlink | 15m | train | 2989 | 2989 |
| S2 | window | 15m | BTCUSDT | chainlink | 15m | val | 2108 | 2108 |
| S2 | window | 15m | ETHUSDT | chainlink | 15m | test | 1 | 1 |
| S2 | window | 15m | ETHUSDT | chainlink | 15m | train | 21 | 21 |
| S2 | window | 15m | ETHUSDT | chainlink | 15m | val | 18 | 18 |
| S2 | window | 15m | SOLUSDT | chainlink | 15m | test | 1 | 1 |
| S2 | window | 15m | SOLUSDT | chainlink | 15m | train | 5 | 5 |
| S2 | window | 15m | SOLUSDT | chainlink | 15m | val | 1 | 1 |
| S2 | window | 15m | XRPUSDT | chainlink | 15m | train | 1 | 1 |
| S2 | window | 1d | BTCUSDT | binance | 1d | test | 23 | 23 |
| S2 | window | 1d | BTCUSDT | binance | 1d | train | 45 | 45 |
| S2 | window | 1d | BTCUSDT | binance | 1d | val | 30 | 30 |
| S2 | window | 1d | ETHUSDT | binance | 1d | test | 23 | 23 |
| S2 | window | 1d | ETHUSDT | binance | 1d | train | 44 | 44 |
| S2 | window | 1d | ETHUSDT | binance | 1d | val | 30 | 30 |
| S2 | window | 1d | SOLUSDT | binance | 1d | train | 7 | 7 |
| S2 | window | 1h | BTCUSDT | binance | 1h | test | 433 | 433 |
| S2 | window | 1h | BTCUSDT | binance | 1h | train | 897 | 897 |
| S2 | window | 1h | BTCUSDT | binance | 1h | val | 548 | 548 |
| S2 | window | 1h | ETHUSDT | binance | 1h | test | 3 | 3 |
| S2 | window | 1h | ETHUSDT | binance | 1h | train | 23 | 23 |
| S2 | window | 1h | ETHUSDT | binance | 1h | val | 5 | 5 |
| S2 | window | 1h | SOLUSDT | binance | 1h | test | 2 | 2 |
| S2 | window | 1h | SOLUSDT | binance | 1h | train | 2 | 2 |
| S2 | window | 1h | XRPUSDT | binance | 1h | test | 1 | 0 |
| S2 | window | 1h | XRPUSDT | binance | 1h | train | 4 | 3 |
| S2 | window | 1h | XRPUSDT | binance | 1h | val | 4 | 4 |
| S2 | window | 4h | BTCUSDT | chainlink | 4h | test | 40 | 40 |
| S2 | window | 4h | BTCUSDT | chainlink | 4h | train | 140 | 140 |
| S2 | window | 4h | BTCUSDT | chainlink | 4h | val | 122 | 122 |
| S2 | window | 4h | ETHUSDT | chainlink | 4h | train | 10 | 10 |
| S2 | window | 4h | ETHUSDT | chainlink | 4h | val | 20 | 20 |
| S2 | window | 4h | SOLUSDT | chainlink | 4h | train | 4 | 4 |
| S2 | window | 4h | SOLUSDT | chainlink | 4h | val | 1 | 1 |
| S2 | window | 4h | XRPUSDT | chainlink | 4h | val | 1 | 1 |
| S2 | window | 5m | BTCUSDT | chainlink | 5m | test | 6077 | 6076 |
| S2 | window | 5m | BTCUSDT | chainlink | 5m | train | 11776 | 11776 |
| S2 | window | 5m | BTCUSDT | chainlink | 5m | val | 8349 | 8349 |
| S2 | window | 5m | ETHUSDT | chainlink | 5m | test | 8 | 8 |
| S2 | window | 5m | ETHUSDT | chainlink | 5m | train | 94 | 94 |
| S2 | window | 5m | ETHUSDT | chainlink | 5m | val | 35 | 35 |
| S2 | window | 5m | SOLUSDT | chainlink | 5m | test | 2 | 2 |
| S2 | window | 5m | SOLUSDT | chainlink | 5m | train | 22 | 22 |
| S2 | window | 5m | SOLUSDT | chainlink | 5m | val | 2 | 2 |
| S2 | window | 5m | XRPUSDT | chainlink | 5m | train | 9 | 9 |
| S3 | touch | down | BTCUSDT | binance | day | test | 61 | 56 |
| S3 | touch | down | BTCUSDT | binance | day | train | 93 | 88 |
| S3 | touch | down | BTCUSDT | binance | day | val | 57 | 56 |
| S3 | touch | down | BTCUSDT | binance | month | test | 15 | 12 |
| S3 | touch | down | BTCUSDT | binance | month | train | 18 | 16 |
| S3 | touch | down | BTCUSDT | binance | month | val | 18 | 16 |
| S3 | touch | down | BTCUSDT | binance | week | test | 23 | 23 |
| S3 | touch | down | BTCUSDT | binance | week | train | 30 | 29 |
| S3 | touch | down | BTCUSDT | binance | week | val | 28 | 28 |
| S3 | touch | down | ETHUSDT | binance | day | test | 5 | 5 |
| S3 | touch | down | ETHUSDT | binance | day | train | 14 | 6 |
| S3 | touch | down | ETHUSDT | binance | day | val | 1 | 0 |
| S3 | touch | down | ETHUSDT | binance | month | test | 16 | 12 |
| S3 | touch | down | ETHUSDT | binance | month | train | 19 | 16 |
| S3 | touch | down | ETHUSDT | binance | month | val | 17 | 16 |
| S3 | touch | down | ETHUSDT | binance | week | test | 18 | 18 |
| S3 | touch | down | ETHUSDT | binance | week | train | 13 | 12 |
| S3 | touch | down | ETHUSDT | binance | week | val | 14 | 12 |
| S3 | touch | down | SOLUSDT | binance | day | train | 1 | 1 |
| S3 | touch | down | SOLUSDT | binance | month | test | 11 | 10 |
| S3 | touch | down | SOLUSDT | binance | month | train | 13 | 11 |
| S3 | touch | down | SOLUSDT | binance | month | val | 7 | 6 |
| S3 | touch | down | SOLUSDT | binance | week | train | 1 | 1 |
| S3 | touch | down | SOLUSDT | binance | week | val | 2 | 1 |
| S3 | touch | down | XRPUSDT | binance | day | val | 2 | 0 |
| S3 | touch | down | XRPUSDT | binance | month | test | 5 | 5 |
| S3 | touch | down | XRPUSDT | binance | month | train | 10 | 9 |
| S3 | touch | down | XRPUSDT | binance | month | val | 5 | 4 |
| S3 | touch | down | XRPUSDT | binance | week | train | 1 | 0 |
| S3 | touch | up | BTCUSDT | binance | day | test | 51 | 50 |
| S3 | touch | up | BTCUSDT | binance | day | train | 111 | 107 |
| S3 | touch | up | BTCUSDT | binance | day | val | 69 | 69 |
| S3 | touch | up | BTCUSDT | binance | month | test | 13 | 7 |
| S3 | touch | up | BTCUSDT | binance | month | train | 24 | 20 |
| S3 | touch | up | BTCUSDT | binance | month | val | 16 | 6 |
| S3 | touch | up | BTCUSDT | binance | week | test | 26 | 26 |
| S3 | touch | up | BTCUSDT | binance | week | train | 38 | 36 |
| S3 | touch | up | BTCUSDT | binance | week | val | 38 | 34 |
| S3 | touch | up | ETHUSDT | binance | day | test | 8 | 6 |
| S3 | touch | up | ETHUSDT | binance | day | train | 22 | 17 |
| S3 | touch | up | ETHUSDT | binance | day | val | 18 | 13 |
| S3 | touch | up | ETHUSDT | binance | month | test | 12 | 7 |
| S3 | touch | up | ETHUSDT | binance | month | train | 20 | 16 |
| S3 | touch | up | ETHUSDT | binance | month | val | 16 | 6 |
| S3 | touch | up | ETHUSDT | binance | week | test | 16 | 15 |
| S3 | touch | up | ETHUSDT | binance | week | train | 20 | 17 |
| S3 | touch | up | ETHUSDT | binance | week | val | 26 | 24 |
| S3 | touch | up | SOLUSDT | binance | day | train | 1 | 1 |
| S3 | touch | up | SOLUSDT | binance | month | test | 8 | 8 |
| S3 | touch | up | SOLUSDT | binance | month | train | 17 | 16 |
| S3 | touch | up | SOLUSDT | binance | month | val | 8 | 6 |
| S3 | touch | up | SOLUSDT | binance | week | val | 2 | 1 |
| S3 | touch | up | XRPUSDT | binance | day | val | 1 | 1 |
| S3 | touch | up | XRPUSDT | binance | month | test | 6 | 4 |
| S3 | touch | up | XRPUSDT | binance | month | train | 16 | 16 |
| S3 | touch | up | XRPUSDT | binance | month | val | 11 | 8 |
| S3 | touch | up | XRPUSDT | binance | week | test | 1 | 1 |
| S3 | touch | up | XRPUSDT | binance | week | train | 1 | 0 |
| S3 | touch | up | XRPUSDT | binance | week | val | 4 | 0 |

## Excluded crypto-family markets

| reason | markets | example |
|---|---|---|
| no priceToBeat | 889 | Bitcoin Up or Down - August 21, 3:35PM-3:40PM ET |
| closed after 2026-10-08 (shadow set) | 231 | Bitcoin Up or Down - October 9, 11:10AM-11:15AM ET |
| underlying not in BTC/ETH/SOL/XRP | 185 | Over $50M committed to the Jumper public sale? |
| underlying not on the Binance list | 41 | BNB Up or Down on October 5? |
| not a price-level question | 12 | Will Ethereum hit $3k by September 30, 2026? |
| touch period unparsed | 12 | Will Solana reach $120 by December 31, 2026? |

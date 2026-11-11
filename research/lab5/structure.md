# Lab 5 structure checks (TRAIN only; no return computed)

Run 2026-10-09T20:32:34+00:00.

## Settlement replicated from Binance 1 s klines vs the venue's outcome

| contract | replicated | match rate | not replicable |
|---|---|---|---|
| terminal:above:binance | 615 | 100.00 % | 0 |
| terminal:below:binance | 2 | 100.00 % | 0 |
| terminal:between:binance | 157 | 100.00 % | 0 |
| touch:down:binance | 213 | 100.00 % | 0 |
| touch:up:binance | 270 | 99.63 % | 0 |
| window:15m:chainlink | 3016 | 97.65 % | 0 |
| window:1d:binance | 96 | 100.00 % | 0 |
| window:1h:binance | 926 | 100.00 % | 0 |
| window:4h:chainlink | 154 | 100.00 % | 0 |
| window:5m:chainlink | 11901 | 95.66 % | 0 |

Chainlink rows replicate with the BINANCE PROXY (the basis error rate); the bets settle on the venue's outcome.

## Chainlink basis (5m / 15m / 4h windows)

Windows 15071; venue outcome = (finalPrice >= priceToBeat) in 100.00 % of them. Residual log basis of the final value after scaling Binance by priceToBeat / Binance-at-open: sd 0.000075 (quantiles {"0.01": -0.000185, "0.05": -0.000106, "0.5": -0.0, "0.95": 0.000108, "0.99": 0.000186}); Chainlink / Binance at the open: median -0.0009019109446679896, sd 0.00020331482690984036.

## Print timing against spot

Mean squared gap between a print's price of outcome 0 and the model value of outcome 0 with spot read k seconds before the print timestamp (3000 TRAIN windows, primary vol):

| k (s) | MSE |
|---|---|
| -10 | 0.01450 |
| -5 | 0.01270 |
| -2 | 0.01183 |
| 0 | 0.01140 |
| 2 | 0.01123 |
| 5 | 0.01402 |
| 10 | 0.01793 |
| 20 | 0.02407 |
| 30 | 0.02940 |

Best k = 2 s; decision lag LAG_S = max(10, best k + 5) = 10 s (PLAN §2).

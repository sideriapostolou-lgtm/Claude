# Lab 3: systematic strategies on liquid crypto majors

Written 2026-10-09 ~12:00 UTC, before any lab-3 return was computed. Owner direction (same day): "it doesn't have
to be memecoins, it can be stocks or any crypto"; chosen arena: **crypto majors, systematic**.

## 0. Why this arena, and what to expect

Wave 1-2 (research/lab, research/lab2) tested 25+ ways to buy fresh pump.fun graduates. None passed. The market
itself drifts about -20 % per trade for an outside buyer at our speed; no rule beat that headwind. Liquid majors
have no such headwind: round-trip costs are ~0.3-0.6 % and the unconditional drift is roughly zero, so the question
becomes whether documented systematic effects (trend following, volatility targeting, cross-sectional momentum,
short-term mean reversion) survive honest costs and an out-of-sample look.

Expectations, stated before the data: a good long-only systematic program on crypto majors has historically
earned something like 10-40 % a year with 30-60 % drawdowns and a Sharpe near 0.5-1.0, mostly by sitting out the
worst months. Returns scale with capital; a $100 account makes tens of dollars a year. Nothing here turns $100 into
$20k.

## 1. Data and universe

- Source: Coinbase Exchange public candles (USD markets), daily from 2015-01-01 and hourly from 2023-01-01
  (`research/lab3/data.py`). No key, no cost. Research only.
- Universe (FIXED): coins with a Coinbase USD market that also trade on Solana through Jupiter with real liquidity
  (so a pass has a live path): SOL, BTC (cbBTC), ETH (wETH), JUP, BONK, WIF, JTO, PYTH, RAY, HNT, RENDER, W, ORCA,
  POPCAT, DRIFT, TNSR, KMNO, IO, PENGU, TRUMP, FARTCOIN, MOODENG, PNUT, ME, GRASS, MNDE, SHDW, HONEY.
- An asset enters a strategy's universe on a day only when it has >= `min_history` completed daily bars (per
  hypothesis; default 200) and a 30-day median USD volume >= $1M. Survivorship: the universe is today's list, so
  coins that delisted are missing. That biases buy-and-hold UP (favours the benchmark, not the strategy) and is
  recorded as a limitation.

## 2. Splits (walk-forward, by calendar, FIXED)

| split | period (UTC) | role |
|---|---|---|
| TRAIN | 2015-01-01 -> 2024-12-31 | choose configs (shortlist <= 2 per hypothesis) |
| VAL | 2025-01-01 -> 2025-12-31 | one look per shortlisted config; the judge reads it before TEST |
| TEST | 2026-01-01 -> last complete day | ONE look per hypothesis, `LAB3_ALLOW_TEST=1` |

Signals may use any data BEFORE the decision bar (warm-up reaches back into the previous split; outcomes never do).

## 3. Execution and costs (FIXED)

- Long / flat only (no perps, no shorts, no leverage): position in [0, 1] of the sleeve's capital per asset.
- Decision at the daily close `t` (UTC 00:00); fill at the next bar's open (crypto trades 24/7, so open(t+1) ~
  close(t)); P&L from close-to-close with the position lagged one bar.
- Cost per unit of turnover (one side): 25 bps = Jupiter route fee + Ultra fee + spread; stress x2 (50 bps).
  Network fee $0.02 per swap. Rebalance only when |target - current| > 5 % of the sleeve (no dust churn).
- Portfolio: equal weight across the assets in the universe that day, each asset's position from its own signal;
  cash earns 0.

## 4. Hypotheses and grids (counted trials; PLAN 3.4 budget 8 configs per hypothesis)

- **T1 time-series momentum**: long when the L-day return > 0, else flat. L in {30, 60, 90, 180, 365}; plus a
  "2-of-3" vote (60, 120, 240). 6 configs.
- **T2 moving-average / breakout**: long when close > SMA(N), N in {50, 100, 200}; Donchian: long on a new N-day
  high, flat on a new N/2-day low, N in {55, 100}. 5 configs.
- **V1 volatility targeting overlay** on the TRAIN-best of T1 and T2: position x min(1, target / realized 20-day
  vol), target in {40 %, 60 % annualized}. 4 configs.
- **X1 cross-sectional momentum**: weekly, rank the universe by the 90-day return, hold the top k equal weight
  (k in {3, 5}) only where the asset's own 90-day return > 0; else cash. 2 configs.
- **R1 short-term mean reversion**: buy an asset after it closes below its 5-day low while above its 200-day SMA;
  exit at the first close above the 5-day SMA or after 5 days. 1 config (and its "no trend filter" twin). 2 configs.
- **T3 majors-only trend** (added 2026-10-09 12:40 UTC, AFTER the VAL results of T1-V1 were read, BEFORE any T3
  return was computed; counted as 5 new trials): the T1 / T2 rules on a universe of BTC, ETH and SOL only, with the
  benchmarks and the placebo on that same universe. Grid: tsmom30, tsmom90, sma50, sma200, donchian55. Same splits
  and bars; the 2025 VAL look is its first out-of-sample test. Motivation (stated honestly): the wave-3 universe is
  memecoin-heavy because it had to be Solana-tradable; the owner's direction was "crypto majors".
- **Benchmarks** (not trials): buy-and-hold equal weight; SOL only; BTC only; cash.
- **Placebo** (PLAN 3.4 analogue): for each config, 200 random position series with the SAME per-asset exposure and
  the same average holding length (block-shuffled positions), costs applied: the strategy must beat its own
  exposure's luck, not just cash.

## 5. Metrics and decisions

Per config and split: CAGR, annualized volatility, Sharpe (daily log returns x sqrt(365)), max drawdown, Calmar,
exposure, turnover, cost drag, excess return vs equal-weight buy-and-hold, excess vs the exposure-matched placebo
(mean and 95 % block-bootstrap CI, monthly blocks), deflated Sharpe with the program-wide trial count (lab 2 + lab 3
ledgers).

- TRAIN qualifies: Sharpe > 0.5, Sharpe > buy-and-hold's, max drawdown < buy-and-hold's, excess vs placebo CI95
  lower bound > 0. Rank by Sharpe; shortlist the top 2 per hypothesis.
- VAL: the shortlisted config with the higher VAL Sharpe is the candidate if its VAL Sharpe > 0 and its excess vs
  placebo > 0; the judge reads VAL before TEST.
- TEST (one look): PASS needs Sharpe > 0, excess vs placebo CI95 lower bound > 0, and drawdown < buy-and-hold's.
- A TEST pass never funds real money by itself; the owner decides, probation sizing applies, risk limits and the
  kill switch stay outside learning.

## 6. Stop rules

Nothing qualifies on TRAIN -> hypothesis dead; no new grid on the same data. A VAL Sharpe < 0 closes the config.

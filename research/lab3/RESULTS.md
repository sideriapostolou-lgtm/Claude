# Lab 3 results (systematic strategies on liquid crypto majors)

Protocol: `PLAN.md`. Universe: 28 Coinbase-USD coins tradable on Solana via Jupiter (BTC and ETH as cbBTC / wETH),
daily bars, long/flat, equal weight across the universe, 25 bps per side + $0.02 network fee per swap on a $100
sleeve, exposure-matched block-shuffled placebo (200 draws). TRAIN 2015-2024, VAL 2025, TEST 2026 (one look).

## 2026-10-09: TRAIN shortlisted four hypotheses; VAL (2025) failed all of them

| hypothesis | TRAIN (2015-2024) | VAL (2025) | verdict |
|---|---|---|---|
| T1 time-series momentum | L30 Sharpe 1.31, CAGR +100 %, DD -70 %; L60 1.18 / +96 % / -60 %; buy-and-hold 0.81 / +88 % / -88 %; excess vs exposure-matched placebo +45 % / +38 % a year, CI95 > 0, DSR 0.93 / 0.85 | L30 Sharpe -0.88, -29 %, DD -45 %; L60 -0.99, -33 %; buy-and-hold -1.27, **-67 %**; vs placebo +25 % / +12 % a year but CI95 spans 0; cost drag 13 % / 8 % a year | **FAIL_VAL** |
| T2 SMA / Donchian | sma50 1.31 / +98 % / -55 %; donchian55 1.31 / +89 % / -57 % (exposure 0.42, 5 trades a year); all 5 configs qualified | donchian55 -0.82, -21 %, DD -31 %; sma50 -1.21, -35 % | **FAIL_VAL** |
| X1 cross-sectional momentum | top5 1.05 / +85 % / -63 %; top3 1.02 / +81 % | top3 -1.29, -27 %; top5 -1.31, -36 %; WORSE than the matched placebo (-10 / -13 % a year) | **FAIL_VAL** |
| V1 vol-target overlay on T2-best (sma50) | vol40 Sharpe 1.56, CAGR +56 %, DD -40 % (the best risk-adjusted TRAIN line); vol60 1.47 / +76 % / -50 % | vol60 -0.99, -20 %, DD -31 %; vol40 -1.00, -15 %, DD -23 % | **FAIL_VAL** |
| R1 short-term mean reversion | trend200 Sharpe -0.21, no-filter -0.37; turnover 34-61 a year, cost drag 10-18 % | not run | **NO_CONFIG (dead on TRAIN)** |

No TEST look was spent (nothing was SELECTED on VAL).

### Reading

- On TRAIN every trend rule did what the literature says: same or better growth than buy-and-hold with much
  smaller drawdowns, and clearly better than random position series with the same exposure. 2017 and 2020-21 carry
  most of it; 2018 and 2022 are the losing years.
- 2025 was a bear year for this universe: equal-weight buy-and-hold **-67 %** (the Solana-ecosystem names fell
  70-90 %), SOL -34 %, BTC -6 %. Long/flat trend following lost less than holding (-15 % to -35 % vs -67 %) and sat
  in cash 60-80 % of the time, but it still lost money: whipsaws plus costs. Cross-sectional momentum was worse
  than random.
- Costs matter at this size: a $100 sleeve pays 8-13 % a year in fees on the faster rules, about half of it the
  fixed $0.02 network fee per swap. The same rules on $1,000 would pay roughly 5-8 %.
- The honest summary for the owner: trend following is a real risk-management effect (lose less in bears, ride
  bulls), not a money machine; it had a negative year in 2025 like every long-only crypto approach. It earns its
  keep over cycles, with capital, not over months with $100.

### Limitations

- Survivorship: today's universe only; delisted coins are missing (biases buy-and-hold up, so the comparison is
  conservative for the strategies, not for the absolute numbers).
- The universe is memecoin-heavy because it had to be Solana-tradable; a majors-only universe (BTC, ETH, SOL) is a
  different, pre-registered hypothesis (T3), see below.

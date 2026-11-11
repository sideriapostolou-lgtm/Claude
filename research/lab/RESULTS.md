# Strategy lab: final results (judge's report)

**Verdict: NO WINNER.** None of the strategies made money on coins it had never seen. Do not trade
the $100 with any of them. No `winner.json` was written.

Judged 2026-10-08. The TEST split was opened once, at 20:27 UTC, after the finalist list had been frozen
by hash at 20:14 UTC. Everything here is a backtest on recorded history, as you asked. Nothing waited for
future data.

---

## Part 1 - Plain-English summary

### What we tested

- **Real coins.** 1,070 pump.fun coins that graduated to a real trading pool, launched between
  Oct 7 19:37 and Oct 8 18:08 UTC. We have their minute-by-minute price and volume from creation onwards.
- **Tradable coins.** 770 of them can realistically be traded with $20. Mayhem-mode coins and coins not
  priced in SOL were left out.
- **Three groups, by launch time:**
  - **Practice** (448 coins): researchers could look at these as much as they liked.
  - **Check** (150 coins): to see whether an idea still worked on new coins.
  - **Final exam** (172 coins): the newest coins, launched 13:35-18:08 UTC. Nobody was allowed to look at
    them until the judge ran each finalist on them once.
- **Real costs.** Every trade pays pump.fun's pool fee, Jupiter Ultra's fee, a slippage/MEV allowance,
  price impact and network fees. That is about 3-5% for a $20 round trip. The cost model matched live
  Jupiter quotes to within 0.07 percentage points on 6 real coins.
- **Four research teams** tried **2,575 strategy settings** in total:
  - smarter "buy the dip when buyers return" (F1);
  - momentum and breakouts (F2);
  - lifecycle timing, i.e. when in a coin's life to trade (F3);
  - a machine-learning entry filter (F4).

  Only 4 settings were sent to the final exam: two from F1 and two from F4. F2 and F3 found nothing
  worth sending. All four had already been marked "rejected" by their own researchers. The judge ran
  them anyway, under rules written down before the exam, as a final confirmation.

### What happened on the final exam (172 unseen coins)

| Strategy | Trades | Won | Average per $20 trade | $100 account after the test window |
|---|---|---|---|---|
| F1-S4: buy a 40-80% dip when volume returns | 10 | 3 | **-19.4%** (about -$3.90) | **$66** (-34%) |
| F1-S1: same, deeper 60-80% dips | 10 | 2 | **-23.2%** (about -$4.60) | **$61** (-39%) |
| F4-#1: machine-learning filter, top 2% of scores | 12 | 7 | **-5.4%** (about -$1.10) | **$85** (-15%) |
| F4-#2: machine-learning filter, top 1% of scores | 3 | 2 | **-3.2%** (about -$0.60) | **$97** (-3%) |
| *Reference: random entry time, the bot's exits* | 62 | 7 | -6.4% | $94 (-6%) |
| *Reference: buy at graduation, hold 1 hour* | 172 | 22 | -68.1% | $7 (-93%) |
| *Reference: the bot's current default strategy* | 1 | 0 | -22.1% | $96 (-4%) |

- **Every finalist lost money.** It still lost with costs ×1.5, with one candle of extra delay, and with
  the best coin removed.
- **None beat random by a meaningful margin.** The two F1 strategies did clearly *worse* than entering
  at a random time.

### Why nothing won

1. **The typical move is smaller than the costs.** A $20 round trip costs 3-5%. Most patterns that look
   profitable before costs earn about that much or less.
2. **Rugs decide everything.** Most of these coins are dumped by insiders within the first hour. One bad
   one-minute candle can wipe out the gains of 2-3 winning trades.
3. **The best-looking pattern was one anonymous operator.** The machine-learning strategy did well on
   the practice and check coins (+14% and +9% per trade), but it had only learned one thing: a single
   "launch farm".
   - The farm launches brand-name tickers (OpenAI, NVIDIA, FOMO, Apple, MrBeast...). They climb smoothly
     for about 15 minutes and are then dumped at a time only the operator knows.
   - On the exam coins, all 12 of F4's trades were farm coins. The operator dumped sooner than before:
     33% of farm coins crashed between minutes 15 and 30, against 22-24% earlier.
   - F4-#1 won 58% of its trades. It needed about 68% to break even, or about 78% if stop-loss fills
     are modelled honestly.
4. **Too few trades to prove anything.** A strategy picky enough to dodge most rugs trades only 3-24 times
   in a 4-5 hour window. Proving a real +2-3% edge would take about 400 trades, which is roughly a week or
   more of launches.

### What to expect if you traded $100 anyway (realistic ranges)

- **Expected value per trade is negative for every strategy we have:** about -$1 to -$5 per $20 trade.
- **Over a 4-5 hour window like the test:**
  - the F1 dip strategies lost 34-39% of the account;
  - the bot's default strategy lost 41-64% in earlier windows;
  - the F4 filter lost 15%.
- **Winning days happen, but by luck.** For example, F4 made +46% on the check window and then lost on
  the exam. A good day tells you nothing about the next one.
- **Honest range for one day with $100:** roughly +45% on a lucky day to -65% on a bad one. The middle of
  that range is a loss.

### Risks even beyond these numbers

- **This is one day of data.** Behaviour on other days, other weeks or other market moods is unknown.
- **One operator's habits can change at any moment.** The farm already changed between the check and
  the exam windows.
- **Real stop-losses fill worse than the default backtest assumes on rugs.** With honest "rug-aware"
  fills, every finalist lost 17-32% per trade on the exam.
- **There may be survivor bias.** The coin list comes from pump.fun's API. If it hides some deleted or
  banned coins, the real world is worse than this data.
- **Live trading adds more problems.** Failed transactions, slower landing and MEV can all make real
  results worse.

### What would most likely help

1. **Trade-flow and wallet data (most important).** Every losing trade here is an insider dump. Watching
   the creator's wallet, the top holders, bundled buys, and buy/sell counts per minute is the most
   direct way to see a rug coming. Price candles alone cannot show it.
2. **More history.** A week or more of launches would give ~400+ trades per candidate, plus a fresh exam
   set. **The current exam set is now used up.** Any new idea must be tested on coins launched after
   Oct 8 18:09 UTC. We can collect those with the same fetcher, and they are still backtest data.
3. **Trade-by-trade (sub-minute) prices.** These would show what a stop-loss really gets during a rug,
   which is the biggest unknown in the cost of losing trades.
4. **Creator history across days**, so repeat operators like the farm can be recognised or avoided.

Until then, the honest recommendation is: **paper-trade only**, and use the lab's "when not to trade"
rules to avoid the worst losses. Those rules are not a profit engine. They are:

- no entries in the first 30 minutes after graduation;
- skip coins with almost no volume;
- skip instant-graduate coins under $1M in their first 2 hours.

You asked to find a winner now from backtests instead of waiting days. We did use only backtests. Their
answer is that none of today's ideas has an edge. Picking whichever backtest looked best would have
picked F4. It made +14% per trade in practice, then lost 5% per trade on the exam: that is how lucky
backtests lose real money.

---

## Part 2 - Detailed results

### 2.1 Procedure

1. **Finalists.** All entries in `finalists/*.json` were loaded:
   - F1: S4 and S1, both REJECTED by the researcher, with `recommend_test: false`.
   - F2: none.
   - F3: none.
   - F4: #1 (q98) and #2 (q99), both REJECTED, with `recommend_test: false`.
2. **Reproduction on VALIDATION.** The judge re-ran every finalist on VALIDATION. Base, costs ×1.5 and
   +1 candle latency matched the reported numbers exactly for trades, average return, CI, portfolio
   return and P&L, on both the per-coin and portfolio runs. The F4 score table the judge rebuilt from the
   model file matches the researcher's saved validation scores on all 10,693 rows (max difference 0.0).
   Details are in `LAB/judge/validation_reproduction.json`.
3. **Freeze.** `judge/frozen_finalists.json` records:
   - each finalist's exact parameters and the model's SHA-256;
   - SHA-256 hashes of `harness.py`, `costs.py`, both strategy modules, `f4_learned_search.py`,
     `baseline.py`, `judge.py` and `splits.json`;
   - the decision rule (§2.4);
   - the multiple-testing plan.

   The TEST run checks every hash and refuses to start if anything changed.
4. **Dry run on VALIDATION.** The full TEST pipeline was run on VALIDATION first, and this caught one
   bug in the judge's statistics.
   - The first p-value method, a null-shifted bootstrap, gave p ≈ 5e-6 for F4-#2 even though its 95% CI
     included 0. The cause is that returns are capped by the take-profit, so after the shift no
     resample can reach the observed mean.
   - It was replaced, before TEST, by the CI-inversion bootstrap p-value: p = share of coin-bootstrap
     means ≤ 0. A cluster-robust t-test is kept as a cross-check.
   - The list was then re-frozen and the dry run repeated.
5. **One TEST pass** (`LAB_ALLOW_TEST=1 python research/lab/judge/judge.py test`).
   - A marker file is written before any TEST coin is loaded. The script refuses a second run.
   - The pass covers base, costs ×1.5 and ×2, +1 candle latency, worst wick fills, rug-aware fills,
     without the best coin, the two halves of the split, a lookahead audit on the TEST coins and the
     three baselines.
   - For F4 the audit uses the live-style `ModelScorer`, which computes features from the view. Its
     trades on TEST were identical to the table-based run.

**TEST split:** 172 coins in the default universe, created 13:35-18:08 UTC on Oct 8, with bars to
about 18:13 UTC. No finalist trade ended with `end_of_data`.

### 2.2 TEST results: per-coin at $20, portfolio from $100

| Finalist | Trades (coins) | Win % | Avg / trade | Median | 95% CI (coin bootstrap) | Bonferroni 98.75% CI | p (one-sided, mean > 0) | p Holm (m=4) | p Bonferroni (2,575 configs) | $100 portfolio | Max DD | Exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1-S4 | 10 (10) | 30 | -19.4% | -27.3% | [-37.7, -0.0] | [-41.9, 5.1] | 0.975 | 1.000 | 1.00 | -34.0% | 34.0% | 7 stop, 3 take-profit |
| F1-S1 | 10 (10) | 20 | -23.2% | -27.2% | [-39.6, -5.4] | [-43.4, -0.1] | 0.994 | 1.000 | 1.00 | -38.9% | 40.2% | 8 stop, 2 take-profit |
| F4-#1 (q98) | 12 (12) | 58 | -5.4% | +24.8% | [-27.6, 15.0] | [-33.5, 19.4] | 0.682 | 1.000 | 1.00 | -15.0% | 16.7% | 5 stop, 6 take-profit, 1 time stop |
| F4-#2 (q99) | 3 (3) | 67 | -3.2% | +22.9% | [-58.7, 26.3] | [-58.7, 26.3] | 0.705 | 1.000 | 1.00 | -2.8% | 12.5% | 1 stop, 1 take-profit, 1 time stop |

The cluster-robust t-test cross-check gives the same picture: p = 0.96, 0.98, 0.68 and 0.54.

### 2.3 TEST robustness

Each cell is per-coin trades, average return per trade, then the $100 portfolio return.

| Check | F1-S4 | F1-S1 | F4-#1 (q98) | F4-#2 (q99) |
|---|---|---|---|---|
| Base (default costs) | 10 tr, -19.4% / -34.0% | 10 tr, -23.2% / -38.9% | 12 tr, -5.4% / -15.0% | 3 tr, -3.2% / -2.8% |
| Costs ×1.5 | 10 tr, -20.9% / -36.0% | 10 tr, -24.7% / -40.7% | 12 tr, -6.8% / -17.8% | 3 tr, -4.6% / -3.7% |
| Costs ×2 | 10 tr, -22.4% / -37.9% | 10 tr, -26.1% / -42.4% | 12 tr, -8.3% / -20.5% | 3 tr, -6.1% / -4.5% |
| +1 candle latency | 10 tr, -16.1% / -29.0% | 10 tr, -20.6% / -34.7% | 12 tr, -5.6% / -15.3% | 3 tr, -3.4% / -3.0% |
| Worst-case wick fills | 10 tr, -33.4% / -51.6% | 10 tr, -35.1% / -53.2% | 12 tr, -18.6% / -41.1% | 3 tr, -16.8% / -11.9% |
| Rug-aware stop fills | 10 tr, -28.5% / -46.7% | 10 tr, -31.9% / -50.1% | 12 tr, -18.3% / -40.7% | 3 tr, -16.8% / -11.9% |
| Without the best coin | 9 tr, -25.1% / -38.0% (no Offchain) | 9 tr, -29.4% / -42.5% (no Offchain) | 11 tr, -8.3% / -19.7% (no FOMO) | 2 tr, -17.9% / -7.7% (no ChatGPT) |
| First half of TEST (by creation) | 7 tr, -24.3% / -30.1% | 10 tr, -23.2% / -38.9% | 8 tr, -0.6% / -3.1% | 1 tr, +26.3% / +5.3% |
| Second half of TEST | 3 tr, -8.1% / -5.7% | 0 tr / 0.0% | 4 tr, -15.0% / -12.7% | 2 tr, -17.9% / -7.7% |
| P&L without best / top-3 coins ($, per-coin) | -45.25 / -52.55 | -52.84 / -51.58 | -18.28 / -28.78 | -7.15 / 0.00 |
| Lookahead audit on TEST coins | clean | clean | clean | clean |

### 2.4 Pre-registered winner gates (TEST)

These were frozen before TEST. A WINNER needs all of them.

| Gate | Rule | F1-S4 | F1-S1 | F4-#1 | F4-#2 |
|---|---|---|---|---|---|
| W1 trades | ≥ 30 per-coin trades | FAIL | FAIL | FAIL | FAIL |
| W2 net profitable | per-coin mean > 0 and $100 portfolio > 0 | FAIL | FAIL | FAIL | FAIL |
| W3 adjusted significance | Holm p < 0.05 and Bonferroni CI above 0 | FAIL | FAIL | FAIL | FAIL |
| W4 costs ×1.5 | per-coin mean > 0 and portfolio > 0 | FAIL | FAIL | FAIL | FAIL |
| W5 +1 candle latency | per-coin mean > 0 and portfolio > 0 | FAIL | FAIL | FAIL | FAIL |
| W6 concentration | P&L > 0 without the best coin and without the top 3; portfolio > 0 without the best coin | FAIL | FAIL | FAIL | FAIL |
| W7 fill realism | per-coin mean > 0 with rug-aware stop fills | FAIL | FAIL | FAIL | FAIL |
| W8 lookahead | audit clean on TEST coins | pass | pass | pass | pass |
| **WINNER** | | no | no | no | no |

### 2.5 Multiple testing

- **Configurations tried, as logged in the run logs and counted by the judge:**

  | Family | TRAIN | VALIDATION | Unlogged exploration |
  |---|---|---|---|
  | F1 dip-rebound-plus | 828 | 6 | event study used to design the grid |
  | F2 momentum | 982 | 19 | 68 event-study checks |
  | F3 lifecycle | 487 | 8 | 13 event-study cuts (149 groups) plus 3 drill-downs |
  | F4 learned | 240 | 5 | none |
  | **Total** | **2,537** | **38** | **2,575 logged** |

- **Formal family for TEST:** the 4 finalists, corrected with Holm.
  - The smallest raw p-value is 0.68, so every Holm-adjusted p is 1.0.
  - Adjustment is not even needed: no finalist has a positive mean on TEST.
- **Deflated view:** treating all 2,575 configurations as candidates, Bonferroni would need p < 1.9e-5.
  Every finalist sits at p = 1.0 on that scale.
- **Comparison with the baselines on the same TEST coins:**
  - **Random entry** (nightcrawler exits): -6.4% per trade, CI [-10.7, -2.1], $100 → -5.7%.
  - **Buy at graduation, hold 60 min:** -68.1% per trade, $100 → -92.9%.
  - **The bot's own default dip-rebound:** 1 trade, -22.1%.
  - **Against random:**
    - F4-#1 is 1.0 point better per trade, well inside the noise;
    - F4-#2 is 3.2 points better on only 3 trades;
    - the F1 strategies are 13-17 points *worse*.
  - **Caveat:** the TEST baselines are right-censored, because the newest coins were observed for at
    most about 4.5 hours. For example, 38 of the 62 random-entry trades closed with `end_of_data`, so the
    baselines are less negative here than on TRAIN/VALIDATION (-5.8% and -8.2% per trade).

### 2.6 What came closest, and why it still fails

**F4-#1 (machine-learning "farm climb" filter)** is the only finalist that looked good in-sample.

| Split | Trades | Win % | Avg / trade | 95% CI | $100 portfolio | With rug-aware fills |
|---|---|---|---|---|---|---|
| TRAIN (out-of-fold) | 27 | 85 | +14.0% | [+1.9, +23.3] | +90% | n/a |
| VALIDATION | 24 | 79 | +9.2% | [-4.8, +19.7] | +46% | +1.3% per trade, portfolio -6.5% |
| **TEST** | **12** | **58** | **-5.4%** | **[-27.6, +15.0]** | **-15%** | **-18.3% per trade, portfolio -40.7%** |

- **What it trades:** every TEST trade was a brand-ticker farm coin (MrBeast, OpenAI, ChatGPT, NVIDIA,
  LEGO, FOMO ×3, NASA, Apple, Meta, SpaceXSI), bought 13-24 minutes after graduation.
- **Win and loss sizes:** wins are capped at about +26% (the take-profit after costs). Four of the five
  losses are rug candles, booked at -51% to -59% with the default fill and closer to -80% to -99% with
  rug-aware fills.
- **Break-even win rate:** about 68% with the default fill and about 78% with rug-aware fills. It
  achieved 58% on TEST.
- **Why it changed:** descriptive outcome statistics, not strategy inputs, show the farm's behaviour
  changed. Farm coins are 38% / 44% / 37% of the train / validation / test coins. The share of farm coins
  with a >50% one-bar crash between minutes 15 and 30 after graduation rose from 22% (train) and 24%
  (validation) to 33% (test).
- **Pooled VALIDATION + TEST:** 36 trades, mean +4.3%, CI [-7.9, +15.4]. With rug-aware fills the pooled
  mean is -5.2%.
- **Bottom line:** this is the operator's rug timing, not a market edge.

**F4-#2** is the same model with a stricter threshold. It traded only 3 times on TEST: ChatGPT +26.3%,
Meta +22.9% and FOMO -58.7%. That is too few to say anything. It depends on the same single operator.

The two F1 dip strategies lost on every split and every stress test. The dip-rebound idea does not
survive costs on these coins.

### 2.7 TEST trade lists (per-coin, $20)

**F4-#1 (q98)**

| Coin | Entry (UTC) | Min after graduation | Exit | Hold (min) | Net return |
|---|---|---|---|---|---|
| MrBeast | 14:03 | 15.7 | stop | 1 | -58.7% |
| OpenAI | 14:29 | 15.1 | take_profit | 11 | +26.3% |
| ChatGPT | 14:31 | 13.9 | take_profit | 9 | +26.3% |
| NVIDIA | 14:35 | 14.4 | stop | 3 | -23.3% |
| LEGO | 14:45 | 24.1 | take_profit | 8 | +26.3% |
| FOMO | 15:29 | 14.1 | stop | 6 | -54.5% |
| NASA | 15:52 | 15.6 | take_profit | 9 | +26.3% |
| FOMO | 16:20 | 23.7 | take_profit | 14 | +26.3% |
| Apple | 16:21 | 15.6 | stop | 4 | -51.0% |
| Meta | 16:49 | 13.2 | time_stop | 15 | +23.4% |
| SpaceXSI | 17:01 | 14.5 | take_profit | 8 | +26.3% |
| FOMO | 18:09 | 13.2 | stop | 2 | -58.6% |

**F4-#2 (q99)**

| Coin | Entry (UTC) | Exit | Net return |
|---|---|---|---|
| ChatGPT | 14:32 | take_profit | +26.3% |
| Meta | 16:50 | time_stop | +22.9% |
| FOMO | 18:10 | stop | -58.7% |

**F1-S4**

| Coin | Exit | Net return |
|---|---|---|
| 401si(k) | stop | -27.9% |
| STREAM | stop | -25.2% |
| Haaland | stop | -60.5% |
| ZERO | stop | -32.7% |
| texcat | stop | -26.7% |
| swordowl | stop | -28.9% |
| Offchain | take_profit | +32.0% |
| Offchain (a second coin with the same ticker) | take_profit | +20.3% |
| Snitch | take_profit | +16.2% |
| BCAT | stop | -60.9% |

**F1-S1**

| Coin | Exit | Net return |
|---|---|---|
| 401si(k) | stop | -27.9% |
| STREAM | stop | -27.7% |
| Haaland | stop | -60.5% |
| MM | stop | -26.4% |
| ZERO | stop | -23.1% |
| texcat | stop | -26.7% |
| swordowl | stop | -28.9% |
| LATCH | stop | -59.8% |
| DIP | take_profit | +16.8% |
| Offchain | take_profit | +32.0% |

### 2.8 Judge's VALIDATION numbers (dry run, same pipeline)

Each cell is per-coin trades, average return per trade, then the $100 portfolio return.

| Check | F1-S4 | F1-S1 | F4-#1 (q98) | F4-#2 (q99) |
|---|---|---|---|---|
| Base | 8 tr, +0.6% / -0.9% | 8 tr, -23.6% / -32.6% | 24 tr, +9.2% / +46.4% | 14 tr, +14.3% / +44.0% |
| Costs ×1.5 | 8 tr, -1.2% / -3.6% | 8 tr, -25.0% / -34.2% | 24 tr, +7.5% / +35.9% | 14 tr, +12.6% / +38.0% |
| +1 candle latency | 8 tr, -8.5% / -14.0% | 9 tr, -25.8% / -38.3% | 24 tr, +11.1% / +60.4% | 14 tr, +14.1% / +43.7% |
| Rug-aware stop fills | 8 tr, -4.1% / -9.4% | 8 tr, -29.0% / -39.1% | 24 tr, +1.3% / -6.5% | 14 tr, +8.6% / +20.3% |
| Bootstrap p (one-sided) / Holm | 0.456 / 0.912 | 0.991 / 0.991 | 0.109 / 0.327 | 0.039 / 0.158 |

Even on VALIDATION, no finalist would have passed: all have fewer than 30 trades, and no adjusted CI is
above 0.

### 2.9 Integrity notes

- **Nothing under `src/` or `tests/` was modified, and nothing was committed.**
  - `nightcrawler` was imported read-only, for its default-strategy baseline.
  - That baseline uses the current `src/nightcrawler/strategy.py`, which another team is editing, so it
    is a reference only.
- **One F4 slip.** The F4 researcher reported opening one TEST coin file before the judge's pass, and
  printing its launch flags and first 3 candles. Nothing from it was used, and the result on TEST is a
  loss either way.
- **The TEST split is now spent.** Re-using it to tune or pick a strategy would make any later TEST
  number meaningless. A future candidate needs a fresh test set: coins launched after Oct 8 18:09 UTC.

### 2.10 Files

- **Code:**
  - `research/lab/judge/judge.py` (`validate`, `freeze`, `dryrun`, `test`)
  - `research/lab/judge/report_tables.py`
- **Frozen list:** `research/lab/judge/frozen_finalists.json`
- **Data**, in `LAB/judge/` (LAB = `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/lab`):
  - `validation_reproduction.json`
  - `validation_dryrun.json`
  - `test_results.json`, with every TEST trade, variant and gate
  - `test_run.log`
  - `TEST_PASS_STARTED`

---

## Audit - independent re-check of the "no winner" verdict

Audited 2026-10-08, 20:40-21:50 UTC, after the judge's TEST pass. The auditor changed nothing the judge froze,
re-tuned or re-selected nothing on TEST, and did not touch `src/` or `tests/`. New code is in
`research/lab/audit/`; new data is in `LAB/audit/`. The auditor committed nothing. An automatic "wip: research
progress snapshot" job on this branch commits `research/` from time to time and has picked up the audit code.

**Audit verdict: CONFIRMED.** The "no winner" verdict stands, and no harness bug hides an edge. The only
material bias I found runs the other way: the backtest's default stop fill makes rug losses look about half as
bad as they really are. Replayed swap by swap, the closest finalist (F4-#1) lost about **17-18% per trade on
TEST, not 5%**, and would have taken the $100 to about **$61, not $85**.

### Plain-English summary

- **The backtest engine does what it says.** I rewrote F4-#1 from scratch without the lab's engine, feature
  code or cost code. It produced exactly the judge's trades: 12 of 12 on TEST, 24 of 24 on VALIDATION, and
  3 of 3 for F4-#2, with returns equal to within 0.0005 percentage points. On all 10,693 scored VALIDATION
  rows, its model scores equal the lab's saved scores exactly (maximum difference 0.0).
- **Real trade-by-trade prices make it worse, not better.** I downloaded all 274,857 swaps around the 36
  F4-#1 trades on VALIDATION and TEST and replayed the strategy on them.
  - **The wins are real.** Every take-profit filled at +26% on the real swaps too, and buying 1-5 seconds after
    the signal cost only about 0.2% extra (at most 0.9%).
  - **The losses are much bigger than the backtest books.** Every rug (4 on TEST, 5 on VALIDATION) was **one
    single sell transaction** of $21k-$30k that dropped the price 86-93% in one swap. No stop-loss can sell in
    between, because no price in between ever existed. The backtest booked these at -51% to -59%; the real
    outcome is -84% to -97%.
  - None of the 9 rug sells came from the coin's creator wallet, so a "watch the creator" alarm would not have
    caught them.
- **Costs are not what kills it.** Live Jupiter Ultra quotes on 7 coins trading at the strategy's market cap
  ($350k-$770k) gave a $20 round trip of 0.4-2.5% (median 2.2%). The cost model says 2.3-2.5%, so it is accurate
  to slightly cautious. With the measured costs TEST is still -4.6% per trade with the backtest's fills; with
  **zero** costs it is -2.6%.
- **Nothing else rescues it.** Entering 1-2 minutes later, missing 30% of entries, removing the top 5 coins and
  splitting by hour or market cap all leave TEST negative. The only variant that turns TEST positive assumes you
  can sell a rug at your stop price, and the swap data shows you cannot.
- **For your $100:** with realistic fills, this "best" strategy lost about 39% of the account in the 4.5-hour
  test window. Across VALIDATION and TEST together (36 trades) it averages about -1.5% per trade, which is
  no edge. Do not trade it.

### A1. Code audit (`harness.py`, `costs.py`, `strategies/f4-learned.py`, `f4_learned_search.py`, `fetch.py`)

The lab's own 50 harness and cost tests pass.

| Check | Result |
|---|---|
| Strategy sees only bars 0..i | Clean. `View` slices every array to i. The auditor's features, built row by row from `bars[:i+1]` only, reproduce every decision. The judge's `audit_lookahead` on TEST is clean. |
| Outcome-only fields as inputs | None in the F4 path or the harness. `coverage.source` is used only for the universe filter (it drops the one 5-minute-bar coin). `cost.k_now` is used only for Mayhem / non-SOL coins, which are excluded. |
| Feature normalisation | No lookahead. The GBT needs no scaling; the logistic model's scaler is fit inside each TRAIN fold. The thresholds are TRAIN out-of-fold quantiles, frozen as numbers. |
| Split leakage | None into TEST. One flattering detail for TRAIN only: the out-of-fold TRAIN scores come from fold models that were also trained on *later* TRAIN blocks. This inflates the +14% TRAIN number, not VALIDATION or TEST. |
| SOL/USD lookup | Small lookahead: `SolUsd.at(t)` returns the close of the SOL minute that *starts* at t, up to 60 s in the future. It feeds the market-cap-in-SOL feature, the gate and the fee tier. Using only closed SOL minutes gives the same F4-#1 signals on TEST (12 of 12) and VALIDATION (24 of 24), with returns within 0.001 pp (`audit/sol_lag.py`). Harmless here, but it should be fixed. |
| "Next open" fills | Correct as coded. However, swap-api's bar open equals the previous close on 99.99% of real bars (28,179 of 28,181 checked), so the "next open" fill is the price at the decision moment. Real swaps 2 s later were on average 0.2% higher (range -0.15% to +0.87%, 35 trades). This is a small optimism. |
| Synthetic candles | No effect. All 36 F4-#1 entry and exit bars on VALIDATION and TEST were real trading minutes (at least $787 of volume). Flat filler bars cannot trigger a stop or a take-profit. |
| Fills at prices that never traded | **Yes, on rug stops, in the strategy's favour.** In all 4 TEST rug exits, not one swap printed between the stop level and the post-rug price. The "half" fill ($232k-$290k market cap) never existed. On NVIDIA's ordinary stop, 4 swaps did trade in that range. Take-profit fills at the level are confirmed by swaps; the "half" take-profit rule never bound on a TEST trade. |
| Costs | The fee tiers match the saved pump.fun fee page, re-typed independently. All 70 live Ultra quotes reported `feeBps` 10. The impact model (k = 84.99 SOL x 206.9M tokens) is slightly cautious. See A4. |
| Survivorship | Small. On-chain graduations from CryptoHouse (`research/flow`, Oct 7 19:37-22:58 UTC) show 218 of 220 graduates in the census. About 1% of graduates may be hidden coins, so the real world is slightly worse than the data. The TEST window is not yet covered by on-chain data. Coins created in the TEST window that graduated after the 18:09 census are also missing, but those are slow graduates, not the farm coins F4 trades. |

### A2. Independent re-implementation (`audit/indep_f4.py`)

It imports nothing from the lab. It reads the coin JSON and SOL prices directly and recomputes the 39
features row by row from `bars[:i+1]`. It re-implements the gate, the entry rule and the exits, and rebuilds the
costs from the fee page, the Ultra fee, the MEV buffer, x*y=k impact and the network fee. The only shared
artefact is the frozen model pickle, checked by SHA-256 and loaded through a stub class, so `f4-learned.py` is
never executed.

| Run | Coins in universe | Rows scored | Judge trades | Independent trades | Identical (entry, exit, reason) | Max return difference |
|---|---:|---:|---:|---:|---:|---:|
| F4-#1 TEST | 172 | 5,063 | 12 | 12 | 12 | 0.0005 pp |
| F4-#1 VALIDATION | 150 | 9,971 | 24 | 24 | 24 | 0.0005 pp |
| F4-#2 TEST | 172 | 5,305 | 3 | 3 | 3 | 0.0002 pp |

There were no extra or missing trades on any of the 322 coins. The task asked for at least 10 TEST coins; all 172
were run. Row by row (`audit/rowcheck.py`), all 10,693 gated VALIDATION rows pass the independent gate and score
exactly like the lab's saved table: maximum difference 0.0, and 352 rows above the threshold in both.

### A3. Swap-by-swap replay (`audit/trade_replay.py`)

**Method.**

- **Data:** the swaps around each trade, from `swap-api.pump.fun/v2/coins/{mint}/trades`. Each swap's
  `priceUsd` is the pool price after that swap.
- **Entry:** the buy lands L seconds after the signal and fills at the pool price at that moment.
- **Exits:** a stop or take-profit triggers on the first swap that crosses the level. The sell lands L seconds
  later at the pool price then.
- **Costs:** the auditor's cost model.

**TEST, F4-#1.** Returns are shown at 1 s / 2 s / 5 s latency.

| Coin | Backtest (candles) | Real swaps 1 s / 2 s / 5 s | What happened |
|---|---|---|---|
| MrBeast | stop -58.7% | -93.2% / -94.4% / -96.6% | one sell of $26.3k (132.5M tokens): $700k to $58k market cap in one swap |
| OpenAI | take-profit +26.3% | +26.3% / +26.3% / +26.4% | |
| ChatGPT | take-profit +26.3% | +26.1% / +26.4% / +26.3% | |
| NVIDIA | stop -23.3% | -24.7% / -29.2% / -29.1% | ordinary sell-off (22 small sells in the trigger second) |
| LEGO | take-profit +26.3% | +26.3% / +26.4% / +26.1% | |
| FOMO | stop -54.5% | -91.4% / -91.4% / -91.4% | one sell of $27.0k (134.7M tokens): $739k to $56k |
| NASA | take-profit +26.3% | +26.2% / +26.4% / +26.7% | |
| FOMO | take-profit +26.3% | +26.4% / +26.5% / +26.5% | |
| Apple | stop -51.0% | -84.3% / -84.1% / -84.1% | one sell of $22.9k (94.6M tokens): $678k to $88k |
| Meta | time stop +23.4% | +23.7% / +23.4% / +23.3% | |
| SpaceXSI | take-profit +26.2% | +26.4% / +26.6% / +26.5% | |
| FOMO | stop -58.6% | -93.9% / -95.1% / -97.0% | one sell of $23.3k (128.7M tokens): $607k to $55k |
| **Mean** | **-5.4%** | **-17.2% / -17.7% / -18.0%** | |

**All splits.** Default (half) fills vs real swaps at 2 s latency:

| Split | Trades | Backtest per trade | Swaps per trade [95% CI] | $100 portfolio, swaps |
|---|---:|---:|---|---:|
| VALIDATION | 24 | +9.2% | +6.6% [-13.2, +21.7] (see note) | +26% |
| TEST | 12 | -5.4% | **-17.7% [-48.8, +11.7]** | **-39%** |
| Both | 36 | +4.3% | **-1.5% [-18.1, +13.4]** | -24% |

**Note on VALIDATION (Haaland).** The rug came 1 second after the signal. In the replay the buy lands after
the rug, at $93k, and a dead-cat bounce then hits the take-profit (+27%). The backtest instead bought before the
rug and lost. Counting that trade as the rug loss it would be from a faster bot (about -95%) brings VALIDATION
to about +1.5% per trade. That matches the judge's rug-aware stress (+1.3%).

**The rug signature.** All 9 rug exits share it:

- one sell of $21k-$30k (92.7M-134.7M tokens, about 9-13% of supply, with the same sizes repeating);
- a drop of 86-93% in a single swap;
- never from the creator wallet.

**The farm signature.** Before entry, the farm coins traded 440-740 swaps a minute. The median buy was
$0.02-0.08, from 99-261 distinct wallets a minute. The smooth "staircase" climb the model learned is painted by
dust-sized bot swaps.

**Break-even.** With wins at +26% and losses at their real size (TEST average -79%), F4-#1 needs about a 75%
win rate. It got 58% on TEST.

### A4. Live cost check (`audit/live_costs.py`, LAB/audit/live_costs.json)

**Method.**

- Jupiter Ultra `/order` quotes, with nothing signed, at 20:44 UTC, SOL = $109.6.
- Each coin got $20 SOL-to-token-to-SOL round trips, twice forward and twice reverse. A price drift between two
  quotes moves the forward and the reverse trips in opposite directions, so the average cancels it.
- The model is shown without the MEV buffer and network fee, because quotes include neither. The coins are
  graduates that were trading at the time, at or near the F4 entry range ($517k-$720k).

| Coin | Market cap | Routes seen | Measured round trip | Model | Difference |
|---|---:|---|---:|---:|---:|
| Pack | $553k | Meteora DLMM, OKX router, Pump.fun AMM | 0.40% | 2.31% | -1.91 pp |
| puter | $596k | OKX router, Pump.fun AMM | 1.85% | 2.30% | -0.45 pp |
| ChatGPT | $558k | Pump.fun AMM | 2.21% | 2.31% | -0.09 pp |
| Joker | $765k | Pump.fun AMM | 2.28% | 2.29% | -0.01 pp |
| OWLNIGHT | $654k | Pump.fun AMM | 1.95% | 2.30% | -0.35 pp |
| SpaceX | $455k | Pump.fun AMM | 2.26% | 2.42% | -0.16 pp |
| FOMO | $354k | Pump.fun AMM | 2.52% | 2.53% | -0.01 pp |
| **Mean / median** | | | **1.92% / 2.21%** | **2.35% / 2.31%** | **-0.43 / -0.10 pp** |

- **Model vs measured.** When Jupiter routes only through the pump.fun pool, the model is right to within
  0.0-0.35 pp. When it finds a second venue, the trip is cheaper. Pack's 0.40% is partly a deeper second pool
  (Meteora DLMM) and partly noise, because its price moved fast between quotes.
- **The model's full cost** (with the 20 bps MEV buffer and the network fee) is 2.9-3.2% per round trip.
- **TEST re-run with measured costs** (F4-#1, backtest fills):

  | Costs | Per trade |
  |---|---:|
  | Model | -5.4% |
  | Mean measured cost, no MEV buffer | -4.6% |
  | Cheapest measured cost (0.40%) applied to every trade | -3.1% |
  | Zero | -2.6% |

  With realistic swap fills and measured costs, TEST stays around -17% per trade.

### A5. Fragility (`audit/fragility.py`, LAB/audit/fragility.json)

Per-trade mean at $20, with backtest (half) fills unless noted. The portfolio is the auditor's simple $100
simulation, which matches the harness to within 0.6 points: TEST -14.9% vs -15.0%, VALIDATION +45.9% vs +46.4%.

| Variant | TEST (12) | VALIDATION (24) | Both (36) |
|---|---|---|---|
| Base | -5.4% | +9.2% | +4.3% |
| Entry 1 min later | -5.6% | +11.1% | +5.5% |
| Entry 2 min later | -3.3% | +11.0% | +6.3% |
| 30% of entries missed (10,000 draws): mean [5th, 95th percentile], share of draws > 0 | -5.5% [-16.6, +7.9], 21% | +9.2% [+2.1, +16.8], 98% | +4.2% [-2.2, +10.9], 86% |
| Same, $100 portfolio median [5th, 95th percentile] | -11% [-27, +10] | +30% [+2, +65] | +17% [-17, +61] |
| Without the top 5 coins | -28.1% (7 trades) | +4.7% (19) | +0.8% (31) |
| Rug-aware fills (judge's stress) | -18.3% | +1.3% | -5.2% |
| **Real swaps, 2 s latency** | **-17.7%** | **+6.6% (about +1.5% without Haaland's luck)** | **-1.5%** |
| Touch stop fills (sell rugs at the stop; impossible per A3) | +7.8% | +17.1% | +14.0% |
| Zero costs | -2.6% | +12.5% | +7.5% |

- **By entry hour (UTC):** each hour has 1-6 trades. Means swing from -59% to +26% with no pattern that holds
  across splits.
- **By entry market cap:** $650-750k entries lost on both splits (-14% VALIDATION, -7% TEST). $550-650k entries
  won on both (+13%, +6%). This is descriptive only. Choosing a band from it now would be fitting to TEST.
- **Latency is not the weak point.** The farm's climb is smooth, so 1-2 minutes of delay barely matters.
- **What it hinges on.** Whether the operator rugs during the 15-minute hold, and how much of the position
  survives a rug. The swaps answer the second question: almost none of it.

### A6. Verdict with numbers

**CONFIRMED: no winner.** The harness has no bug that hides an edge. The independent re-implementation matches
the judge's TEST trades exactly: 12 of 12 for F4-#1 and 3 of 3 for F4-#2.

- **Fill realism.** The harness's one material bias, the "half" fill on rug stops, flatters the strategy.
  Correcting it with real swaps moves F4-#1 on TEST from -5.4% to -17.7% per trade and from -15% to -39% on the
  $100.
- **Costs.** Measured live costs are 0.1-0.4 pp *lower* than the model. That moves TEST from -5.4% to only about
  -4.6%. Even zero costs leave -2.6%.
- **Fragility.** No fragility variant turns TEST positive except "touch" stop fills, which the swap data shows
  are impossible on these rugs.
- **Recommendation.**
  - Keep `winner.json` unwritten. Paper-trade only.
  - The farm coins are not an opportunity. The same operator paints the climb with dust trades and ends it with
    one sell of about 10% of supply.
  - If anything, the evidence argues for **skipping** brand-ticker farm coins (instant graduation, graduation
    close $250k-$500k) entirely. That is a filter to test on coins launched after Oct 8 18:09 UTC, not a
    strategy.

**Small fixes worth making** (none changes a result here):

1. Make `SolUsd.at` return only closed SOL minutes.
2. Make the default stop fill rug-aware, for example no better than the bar close, or the post-swap price when
   swaps are available.
3. Add the 0.2% entry drift seen in the swaps, or use `entry_delay_bars=2` as the default.
4. Label TRAIN out-of-fold numbers as "includes models trained on later blocks".

**Audit files.**

- Code (`research/lab/audit/`):
  - `indep_f4.py`
  - `rowcheck.py`
  - `sol_lag.py`
  - `trade_replay.py`
  - `summarize.py`
  - `live_costs.py`
  - `fragility.py`
- Data (`LAB/audit/`):
  - `indep_*.json`
  - `trades/*.json.gz`: 36 swap windows, 274,857 swaps
  - `replay_*_lat{1,2,5}.json`
  - `replay_summary.json`
  - `live_costs.json`
  - `fragility.json`
  - `sol_lag_check.json`
  - `rowcheck_validation.json`

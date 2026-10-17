# F4 Learned filter: the model only rediscovers one launch farm, and it does not pass the lab's bar

**Verdict: no F4 configuration passes the VALIDATION gate. Nothing from this family should go to the judge
for TEST, and nothing here should trade real money.**

- **What the model learned.** Every profitable F4 trade, on TRAIN and on VALIDATION, is the same thing:
  - a coin from the brand-ticker launch farm that F2 flagged (FOMO, NVIDIA, SpaceX, Anthropic, Claude, Tesla...);
  - bought about 13-15 minutes after graduation;
  - while its price climbs in a smooth staircase, with all of the last 15 one-minute bars green.

  The model is a farm detector. It is not a market-wide edge.
- **Remove the farm and nothing is left.** Models trained and traded on non-farm coins only lose money
  on every short-horizon setting. All 60 of their 15-minute configurations average -5.0% to -19.8% per trade,
  and 54 of them have a CI entirely below zero.
- **The farm finalist does not prove itself on VALIDATION.** It stays positive on average: +9.2% per trade and
  +46% on the $100 portfolio over 24 trades. But its 95% CI is [-4.8%, +19.7%], so the gain is not significant.
- **Realistic stop fills erase it.** Every losing trade is a one-bar rug to the floor. Fill those stops
  at what the bar actually traded (the bar close or low) and VALIDATION drops to about +1% per trade. The
  $100 portfolio then *loses* 7%.

Every number below comes from backtests on recorded data. Nothing here waits for future data.

## What was built

**Code.** The strategy is `strategies/f4-learned.py`, class `F4Learned`. The search driver is `f4_learned_search.py`.
The tests are `tests/test_f4_learned.py`: 14 tests, all passing (127 across the lab). Data, models and run logs are in `LAB/f4/`
and are not committed.

**Features.** There are 39 strictly causal features at each bar close (`FEATURES`, `feature_matrix`):

- log returns over 1, 5, 15 and 60 bars;
- drawdown from the 15-bar, 60-bar and post-graduation highs;
- rebound from the 15-bar and 60-bar lows;
- USD volume over 1, 5 and 60 bars and since graduation, plus two volume ratios;
- realized volatility over 15 and 60 bars, and the worst 1-bar drop over the last 15 bars;
- candle body and wick shares, the 5-bar body mean, and the share of green bars;
- the share of zero-volume minutes over 15 and 60 bars;
- minutes since creation, since graduation and since the post-graduation high, and the graduation delay;
- log market cap, distance from the graduation-level market cap (411 SOL), and price relative to the
  graduation close and to the post-graduation peak;
- six launch flags: twitter, website, telegram, description length, cashback, Token-2022.

Row i of the feature matrix of a coin cut at bar k equals row i of the full matrix, for every i ≤ k. This is
checked bit for bit on synthetic coins and on real TRAIN coins.

**Gate.** Only some bars can be scored. A bar qualifies if it is:

- after graduation, and at most 360 minutes after it;
- in a coin that traded at least $1k over the last 10 bars;
- at a market cap of at least 30 SOL, so the coin is not sitting at the dumped floor.

That gives 28,338 TRAIN rows from 448 coins and 10,693 VALIDATION rows from 150 coins.

**Label.** The label is the exact net return of the trade the strategy would make:

- buy $20 at the next bar's open;
- exit with stop `sl`, take-profit `tp` or time stop `hold`;
- use the default cost model and the harness's pessimistic exit order with "half" wick fills;
- y = 1 if the net return is above 0.

Rows whose exit window runs past the end of the data are dropped from training. The label simulator matches
the harness's net return to 1e-16 on 800 random real trades.

**Label and exit grid.** 12 settings: `tp` {15, 30, 60%} x `sl` {15, 30%} x `hold` {15, 60 min}.

**Models.** Both kinds use fixed hyperparameters, chosen before any run and never tuned:

- L2 logistic regression: standardized inputs, C = 0.05;
- `HistGradientBoostingClassifier`: depth 3, learning rate 0.05, 150 iterations, at least 400 rows per leaf,
  L2 = 5, half the features per split.

**Folds.** The 448 TRAIN coins are sorted by creation time and cut into 5 contiguous blocks. All rows of a coin
stay in one fold, so no row of a coin can leak into another fold.

- A TRAIN bar is scored only by the fold model that never saw its coin. **All TRAIN metrics below are
  out-of-fold.** No in-sample fit is ever evaluated.
- VALIDATION bars are scored by the average of the 5 fold models.

**Strategy.** Enter when the score is above the threshold, with one signal per coin. Thresholds are the
90/95/98/99/99.5% quantiles of the out-of-fold TRAIN scores, frozen as absolute numbers.

- `ModelScorer` computes the features from `view` and runs the saved model, as a live bot would.
- `TableScorer` looks up precomputed scores, which makes the search fast.
- On all 150 VALIDATION coins the two give identical decisions and trades. This is checked by
  `f4_learned_search.py audit` and by a test.

## Configurations tried: 240 on TRAIN, 5 on VALIDATION

All are logged in `LAB/f4/runs.jsonl`, and `python research/lab/f4_learned_search.py count` reproduces the counts.

| Stage | What | Configs |
|---|---|---:|
| A (TRAIN) | 12 labels x {logit, GBT} x 5 threshold quantiles, all gated rows | 120 |
| B (TRAIN) | the same grid with the farm removed from training and trading (`exclude_farm`) | 120 |
| V (VALIDATION) | the shortlist chosen by a rule written before any VALIDATION run | 5 |

**Other degrees of freedom**, not counted as configurations but listed here:

- row-level base-rate tables;
- out-of-fold AUCs for 48 fold-ensembles;
- 6 permutation-importance runs and 4 surrogate trees;
- trade-list inspections on TRAIN.

The farm definition comes from F2's TRAIN analysis: graduation within 10 s of creation, and a
graduation-bar close of $250k-500k. Both facts are known at the close of the graduation bar.

**Shortlist rule** (`shortlist_rule`, fixed before VALIDATION). A TRAIN configuration qualified if it had:

- at least 15 trades on at least 10 coins;
- a positive mean with a coin-bootstrap CI above 0;
- a positive portfolio return;
- a positive mean without the top 3 coins;
- at least one neighbouring threshold quantile that also had a positive mean and a CI above 0.

The qualifiers were ranked by the lower bound of the CI. At most 2 per label and 6 in total were kept.

## Results on TRAIN (out-of-fold)

**What the models can tell apart.** Out-of-fold AUC is 0.60-0.80 for logistic regression and 0.73-0.82 for
GBT. That sounds strong, but it mostly separates bars that will go quiet from bars that keep moving. A quiet
bar loses about 4% to costs, so it counts as a loss. Ranking well does not make a trade profitable.

| Configurations with ≥ 15 trades | Count | Median of per-config means | Best mean |
|---|---:|---:|---:|
| A, logistic, 15-min hold | 25 | -11.0% | +1.8% |
| A, logistic, 60-min hold | 16 | -9.2% | +0.9% |
| A, GBT, 15-min hold | 23 | -3.0% | **+21.2%** (farm) |
| A, GBT, 60-min hold | 8 | -0.9% | +4.6% (ticker clones) |
| B (no farm), logistic, 15 min | 29 | -14.3% | -8.4% |
| B (no farm), logistic, 60 min | 9 | -6.9% | -3.6% |
| B (no farm), GBT, 15 min | 30 | -9.1% | -5.7% |
| B (no farm), GBT, 60 min | 8 | -4.1% | +2.1% (ticker clones, 16 trades) |

- **Stage A:** 8 of 120 configurations have a CI above 0 with at least 15 trades. All 8 are GBT.
  - 5 trade only farm coins: 15-minute hold, top 1-2% of scores.
  - 2 trade only the ticker-clone cluster: coins above $5M drifting up 1-5% an hour, 60-minute hold.
  - 1 mixes the two: 19 ticker-clone trades and 6 farm trades.
- **Stage B:** 1 of 120 has a CI above 0 (ticker clones, 16 trades). Its neighbouring thresholds lose
  money, so it fails the stability rule.
- **Without the farm, the 15-minute models have nothing.** All 60 no-farm 15-minute configurations lose money,
  even at the top 0.5% of scores.
- **The threshold behaves like a cliff, not a slope.** At the 90-95% quantiles every 15-minute configuration loses
  about 75% of the $100 portfolio. Only the top 2% turns positive, because that is exactly where the farm's
  staircase pattern lives.

## The shortlist on VALIDATION

Per trade at $20. "Port" is the $100 portfolio return and "DD" its maximum drawdown.

| ID | Config | TRAIN trades | TRAIN avg % [CI] | TRAIN port / DD | VAL trades | VAL win % | VAL avg % [CI] | VAL port / DD |
|---|---|---:|---|---|---:|---:|---|---|
| bfb29fbd05 | GBT tp30 sl30 h15, q 0.99 | 17 | +21.2 [+11.0, +26.3] | +86% / 10% | 15 | 80 | +8.3 [-10.3, +26.1] | +23% / 22% |
| 314fea3f67 | GBT tp30 sl15 h15, q 0.99 | 23 | +19.0 [+8.0, +26.3] | +105% / 11% | 14 | 86 | +14.3 [-3.8, +26.3] | +44% / 19% |
| b75f089995 | GBT tp15 sl30 h60, q 0.90 (ticker clones) | 25 | +4.6 [+3.0, +6.3] | +21% / 0.5% | 4 | 50 | -11.8 [-47.4, +10.5] | -10% / 14% |
| **8e870ebcf0** | **GBT tp30 sl15 h15, q 0.98** | 27 | +14.0 [+1.9, +23.3] | +90% / 12% | **24** | 79 | **+9.2 [-4.8, +19.7]** | **+46% / 15%** |
| 372485497a | GBT tp30 sl30 h15, q 0.98 | 30 | +12.3 [+0.2, +23.2] | +87% / 11% | 25 | 76 | +5.0 [-9.7, +19.1] | +18% / 28% |

- **The farm pattern stayed positive.** All four farm configurations keep a positive mean on VALIDATION.
  F2's minute-30 farm entry turned negative there.
- **None of the CIs clears zero.** The single ticker-clone configuration makes only 4 VALIDATION trades, and
  it loses money.
- **Selection.** The two finalists are the plateau centre (q 0.98) and its neighbour (q 0.99) of the same model,
  `tp30_sl15_h15` GBT. Both are positive on VALIDATION. They are kept for the record.
- **Both fail the lab's bar.** Their VALIDATION CIs cross 0. The gates in `finalists/f4-learned.json` record
  the rest:
  - q 0.98 also loses money on the $100 portfolio with worst-case wick fills;
  - q 0.99 has only 14 VALIDATION trades, below the 15 the shortlist rule required on TRAIN.

## Finalist robustness (VALIDATION, 150 coins; per-trade mean %, $100 portfolio)

| Variant | 8e870ebcf0 (q 0.98) | 314fea3f67 (q 0.99) |
|---|---|---|
| base | +9.2 [-4.8, +19.7], port +46%, DD 15% | +14.3 [-3.8, +26.3], port +44%, DD 19% |
| costs x1.5 | +7.5, port +36% | +12.6, port +38% |
| costs x2 | +5.9 [-7.7, +16.2], port +26% | +10.9, port +32% |
| +1 bar latency | +11.1, port +60% | +14.1, port +44% |
| $10 positions | +9.0, port +22% | +14.1, port +20% |
| $40 positions | +9.2, port +100%, DD 19% | +14.2, port +80%, DD 30% |
| `wick_fill="worst"` | **+1.2 [-19.5, +16.8], port -7%, DD 36%** | +8.5 [-18.2, +26.3], port +20%, DD 33% |
| rug-aware fills (stop capped at the bar close) | **+1.3, port -6.5%, DD 36%** | +8.6, port +20%, DD 33% |
| `wick_fill="touch"` (optimistic) | +17.1, port +98% | +20.0, port +66% |
| without the best coin | +8.4 (FOMO removed) | +13.3 (Anthropic removed) |
| first half / second half of VALIDATION | +8.6 (14 trades) / +9.9 (10 trades) | +7.6 (9) / +26.3 (5) |
| TRAIN, out-of-fold, for comparison | +14.0 [+1.9, +23.3]; worst wicks +8.2; first / second half of TRAIN: 3 / 24 trades | +19.0 [+8.0, +26.3]; worst wicks +15.5 |

**The lookahead audit is clean.** The live-style `ModelScorer` passes `audit_lookahead` on all 150
VALIDATION coins (2 cuts each) and all 448 TRAIN coins (1 cut each). It also reproduces the search's decisions
and trades exactly.

**Where the money comes from (8e870ebcf0 on VALIDATION).** All 24 trades are farm coins.

- **19 wins**, each a take-profit at +26.2% net.
- **5 losses**, each a one-minute rug.
- In every loss, the bar opened 18-41% *above* the stop. It then closed at 0.4-18% of the stop level.
- The default "half" fill books those losses at -52% to -59%. A bot whose stop triggers on that bar will
  realistically sell near the close, at about -85% to -99%.

**Break-even.** At +26% per win, the break-even win rate is:

- 68% with "half" fills;
- about 78% with realistic rug fills.

VALIDATION won 79%, which is break-even. TRAIN won 85%.

## Feature importances

These are the mean drop in held-out AUC when one feature is permuted, averaged over the 5 fold models.

**`tp30_sl15_h15` GBT (the finalists' model).** Top features, in order:

1. `reb_lo60` (0.012)
2. `reb_lo15` (0.010)
3. `mcap_log10` (0.004)
4. `peak_rel_grad` (0.004)
5. `green15` (0.003)
6. `dist_grad_level` (0.003)
7. `dd_hi60` (0.003)
8. `worst_drop15` (0.002)

The two rebound features mostly encode "an instant graduate in its first hour". Bar 0 of such a coin holds
the curve's starting price, so the 60-bar low is the launch price.

**`tp30_sl15_h15` logistic.** Top features, in order:

1. `lv1` (0.045)
2. `green15` (0.022)
3. `mcap_log10` (0.020)
4. `dist_grad_level` (0.019)
5. `reb_lo60` (0.017)
6. `age_min_log` (0.015)

Its standardized coefficients:

- **positive:** volume +0.50, green share +0.40, `reb_lo60` +0.33;
- **negative:** market cap -0.42.

**`tp15_sl30_h60` GBT (the ticker-clone model).** The top features are `mcap_log10` (0.058) and `reb_lo60`
(0.054). It simply learned "market cap above about $70M".

**What the model actually selects.** A depth-3 surrogate tree reproduces the model's top-2% picks with 99.2%
accuracy. In plain words:

> All of the last 15 bars green, market cap below about 31x the graduation level (about $1.4M), and more than
> about $1.3k of volume in this bar.

That is the farm's bot-driven staircase. 100% of the selected TRAIN rows are farm coins. The q 0.99 version
adds "rising volume (`vratio_5_60` > 0.18) and low 60-bar volatility".

## Comparison with the simple-rule families

| Family | TRAIN configs | TRAIN winners | VALIDATION |
|---|---:|---|---|
| F1 dip-rebound | 828 | none with a CI above 0 | losing |
| F2 momentum | 982 | farm early-strength at minute 30, and ticker-clone trend | farm flipped to -16%; trend made 1-4 trades |
| F3 lifecycle | 487 | ticker-clone "drifter" only | 5-6 trades, CIs cross 0 |
| **F4 learned** | 240 | farm staircase at minute 13-15 (GBT only), and ticker clones | farm positive but CI crosses 0; clones -12% on 4 trades |

The learned filter adds no new source of edge. Given the full causal feature set, the GBT converges on the
same two clusters the hand-written rules found. It does find a better *timing* for the farm: minute 13-15 and
"all bars green", instead of F2's minute 30. That timing kept its sign on VALIDATION, which F2's did not.
Logistic regression finds nothing at all: its best configuration with at least 15 trades averages +1.8%,
with a CI crossing zero.

## Why it might work

- **The farm is real and mechanical.** One operator launches dozens of brand-ticker coins a day, buys out the
  curve at launch, and runs a bot that lifts the price about 3% a minute with every bar green.
  - While that bot runs, the next 30% comes with very high probability: 85% of the time on TRAIN and 79% on VALIDATION.
  - The model sees this from OHLCV alone.
- **The timing generalized across the TRAIN/VALIDATION boundary.**
  - The pattern held from about 00:00 to 13:35 UTC: roughly 3-4 trades an hour, with the same +26% / rug payoff.
  - Both halves of VALIDATION are positive.
  - It survives costs x2, +1 bar latency, and position sizes from $10 to $40.

## The strongest reasons it is probably fooling us

1. **One anonymous actor, not a market.** 100% of the profit comes from one farm.
   - The payoff depends entirely on when that operator rugs, relative to minute 13-15. The operator can change
     this at will, and could even react to outside buyers like us.
   - F2 showed the same farm's minute-30 survival falling from 94% to 70% between TRAIN and VALIDATION.
   - The pattern is also not stable inside TRAIN: the first half of TRAIN produced only 3 signals, against 24 in the second half.
2. **The fill model flatters it.** Every loss is a single-bar rug.
   - The harness default ("half") assumes we sell halfway between the stop and the bar low. For a bot that
     sees the bar after the dump, that is fiction.
   - With realistic fills (`wick_fill="worst"` or rug-aware), the q 0.98 finalist makes +1.2% per trade on
     VALIDATION, and its portfolio **loses 7%** with a 36% drawdown.
3. **Short volatility.** The strategy collects +26% about 80% of the time and loses 55-99% the rest.
   - Win rates and medians look excellent, but the mean rests on how many rugs land inside a 15-minute window.
   - That count is small: 2-4 on TRAIN, 2-5 on VALIDATION. One extra rug in 24 trades costs about 5 points of expectancy.
4. **Selection and multiple testing.**
   - 240 TRAIN configurations went through a pre-registered shortlist of 5. The finalists were then chosen on VALIDATION.
   - The VALIDATION mean is therefore slightly optimistic, and it still does not exclude zero.
   - The configurations are not independent. In effect this is one hypothesis (the farm staircase) tested once
     out of sample, with about 24 trades.
5. **One day of data.** About 22 hours of launches, one farm regime and one market. The newest coins are
   right-censored. No exits here were `end_of_data`, but the farm could stop at any time.
6. **Execution at the top of a staircase.** The entry buys a coin that rose for 15 straight minutes.
   - The harness fills at the next bar's open. A live bot would compete with the farm's own bot and with
     snipers for the same tokens.
   - The +1 bar latency test was fine (+11.1%), but sub-minute slippage on these coins is untested.

## Bottom line for the user

There is no fully mechanical F4 strategy I would trust with the $100. The one pattern the model found is
a bet on a single anonymous launch farm's rug timing:

- **with the lab's default fills:** about +9% per trade on VALIDATION, with a CI from -5% to +20%;
- **with realistic rug fills:** about +1% per trade, and the $100 portfolio loses 7%.

Do not spend the TEST split on it unless the judge explicitly wants to measure the farm hypothesis. If it is
ever tested, use `wick_fill="worst"` or rug-aware fills as the primary metric.

## Notes for the judge

- **One process slip.** While I was checking the coin-file format, `glob(...)[0]` happened to open a TEST-split
  coin file. I printed its launch flags and first 3 candles. Nothing from it was used, and no run has
  touched TEST: the harness guard was never bypassed.
- **Use realistic fills for farm coins.** For any farm-coin candidate from any family, report `wick_fill="worst"`
  or rug-aware fills as the primary result. The farm's losses are one-bar rugs to the floor.
- **Ticker clones are untested.** The ticker-clone cluster (>$5M, slow drift) appears in F2, F3 and F4 on TRAIN.
  It produces too few VALIDATION trades (4 here) to be tested on this dataset.

## Reproduce

```bash
cd /home/user/Claude
pip install scikit-learn                                   # 1.9.1 was used
python research/lab/f4_learned_search.py build             # features + labels (TRAIN, VALIDATION)
OMP_NUM_THREADS=2 python research/lab/f4_learned_search.py train          # stage A models (about 10 min)
OMP_NUM_THREADS=2 python research/lab/f4_learned_search.py train nofarm   # stage B models
python research/lab/f4_learned_search.py sweep             # 120 stage A configs
python research/lab/f4_learned_search.py sweep nofarm      # 120 stage B configs
python research/lab/f4_learned_search.py shortlist         # pre-registered rule -> 5 VALIDATION runs
python research/lab/f4_learned_search.py robust            # robustness (VALIDATION + TRAIN)
python research/lab/f4_learned_search.py audit             # live scorer == tables; audit_lookahead
python research/lab/f4_learned_search.py finalize          # finalists/f4-learned.json
python -m pytest -q research/lab/tests/test_f4_learned.py
```

# F1 dip-rebound-plus: buy the capitulation dip when buyers return, with an anti-chase cap

**Verdict: no edge. Nothing in this family beats costs on validation, and no configuration passes the
lab's bar. Do not trade it and do not spend the TEST split on it.**

Every result here comes from backtests on recorded data. Nothing waits for future data.

## What was tested

- **Strategy:** `strategies/f1-dip-rebound-plus.py`, class `DipReboundPlus`, one instance per coin.
  It decides on closed bars 0..i and fills at the next open through the harness and `costs.py`.
- **The dip:**
  - H is the highest high in the last `lookback_min` bars, counting from the graduation bar.
  - L is the lowest low after H.
  - The drawdown 1 - L/H must fall in a band, such as 40-60 %, 60-80 % or 40-80 %.
  - H must be at least `min_since_high` bars old.
- **Anti-chase:** the price must be `min_reb <= close / L <= max_reb`, with `max_reb` of 1.3, 1.6 or 2.0.
- **Confirmation** (one or more):
  - a green bar, or two green bars;
  - close above the prior bar's high;
  - volume at least `vol_mult` x the trailing 30-bar mean;
  - a higher low.
- **Regime filters:**
  - minutes since graduation;
  - market-cap band;
  - USD volume in the last 10 bars, to skip dead coins.
- **Exit variants:**
  - fixed stop and take-profit;
  - partial take-profit plus trailing stop;
  - ATR-scaled stop with an R-multiple take-profit;
  - a structural stop just under the dip low with an R-multiple take-profit;
  - time stops of 15-120 min.
- **Lookahead tests:** `tests/test_f1_dip_rebound_plus.py`, 14 tests, all passing. They cover:
  - `audit_lookahead` on synthetic and real train coins;
  - replacing future bars with garbage, which leaves earlier decisions unchanged;
  - fills at the next open;
  - the anti-chase and volume-confirmation logic;
  - no shared state between instances.

  `audit_lookahead` is also clean on all 448 train and 150 validation coins for both rejected configs.

### How many configurations were tried

All tries are logged in `LAB/f1/trials.jsonl`.

| Stage | What | Configs |
|---|---|---:|
| A | Entry grid: 3 dd bands x 3 anti-chase caps x 5 confirmations x 3 min ages x 2 min volumes, each with 2 exits | 540 |
| B | 21 exits x max_entries {1, 3} on the 6 most stable stage-A entries (stability = mean of a config and its neighbours) | 252 |
| C | One-at-a-time changes (market cap, high age, min rebound, vol_mult, vol_base, lookback, max age, min volume) around 3 bases | 36 |
| **Total on TRAIN** | | **828** |
| VALIDATION | A shortlist fixed from TRAIN before any validation run | 6 |

There was also a descriptive event study on TRAIN (`strategies/f1_explore.py`), used to design the grid.
It adds degrees of freedom that the count above does not include.

## Results

### TRAIN (448 coins)

- **No config has a coin-bootstrap CI above 0.** That holds for all 828 configs, including the 560
  with at least 15 trades and 10 coins.
- 48 of the 560 have a positive portfolio return, and 64 have a positive per-coin mean.
- **One family stands out: volume-uptick confirmation.** It is the only one that sits around zero after costs:
  - volume confirmation: median per-trade mean -6.5 % across its 108 stage-A configs;
  - green, break and higher-low confirmation: medians of -14 to -16 %.

  Deeper dips (60-80 %) do better than 40-60 %. Re-entering the same coin (max_entries 3) does worse.
- **The best config's per-trade outcome is close to a coin flip.** It ends at about +35 % (take-profit) or
  about -25 % (stop). About a third of the trades end inside their first 0-2 minutes.

### VALIDATION (150 coins, about 5.5 h of launches; the shortlist was fixed before this run)

| Shortlist | Train trades | Train avg % [CI] | Train portfolio | Val trades | Val avg % [CI] | Val portfolio | Val zero-cost avg % |
|---|---:|---|---:|---:|---|---:|---:|
| S1 vol dip, 20/40 % fixed, 60 m | 30 | +1.8 [-8.5, 11.8] | +7.9 % | 8 | **-23.6 [-38.4, -3.7]** | -32.6 % | -20.7 |
| S2 vol dip, low-stop, 1.5R, 120 m | 32 | +2.1 [-10.0, 13.7] | +18.3 % | 8 | -19.5 [-45.7, 10.9] | -29.9 % | -16.5 |
| S3 vol dip, partial 30 % + 15 % trail | 30 | +1.9 [-6.9, 10.2] | +9.0 % | 8 | **-18.8 [-35.9, -2.5]** | -27.1 % | -15.7 |
| S4 vol dip, dd 40-80 %, ≤1.6x low, $10k vol | 27 | +2.6 [-8.0, 13.8] | +17.2 % | 8 | +0.6 [-23.4, 27.2] | -0.9 % | +4.2 |
| S5 = S2 with 120 min lookback (train peak) | 30 | **+7.2** [-4.6, 21.0] | **+48.3 %** | 12 | -18.8 [-37.3, 1.8] | -38.4 % | -15.7 |
| S6 = S2 with min rebound 1.15 (train peak) | 28 | +5.9 [-7.6, 19.4] | +43.5 % | 9 | -15.8 [-41.9, 14.9] | -27.6 % | -12.6 |

- **Five of six lose 16-24 % per trade on validation, and the train peaks collapse.** The two best
  train configs (S5, S6) were kept on purpose as an overfitting control. They are among the worst on
  validation, which is what a noise-fitted peak looks like.

### Robustness

Both configs below are recorded in `finalists/f1-dip-rebound-plus.json` with
`recommend_test: false`. All robustness runs are on VALIDATION.

| Check | S4 avg % / portfolio | S1 avg % / portfolio |
|---|---|---|
| Base (default costs, half wick) | +0.6 / -0.9 % | -23.6 / -32.6 % |
| Costs x1.5 | -1.2 / -3.6 % | -25.0 / -34.2 % |
| Costs x2 | -2.9 / -6.2 % | -26.4 / -35.7 % |
| +1 candle latency | **-8.5 / -14.0 %** | -25.8 / -38.3 % |
| $10 positions | +0.5 / +0.1 % | -23.7 / -17.6 % |
| $40 positions | +0.4 / -5.1 % | -23.8 / -56.4 % |
| Worst-case wick fills | -5.1 / -10.8 % | -31.6 / -41.7 % |
| Without the best coin | **-4.4** (P&L -$6.1) | -32.0 (P&L -$44.8) |
| First / second half | +14.2 (3 trades) / -7.6 (5 trades) | -23.5 (3) / -23.6 (5) |
| Lookahead audit | clean | clean |

- **S4 fails 9 of 15 gates and S1 fails 11.** Both fail the gates for CI above 0 on train and on
  validation, and for costs x2.
- **S4 is only "flat" on validation because of 4 take-profits against 4 stops.**
  - It goes negative without its best coin, with one more candle of latency, at costs x2, or with worst-case wick fills.
  - On train it also turns negative without its top 3 coins (-1.5 %) and at costs x2 (-1.0 %).

## Why it might work (the thesis)

- After a 60-80 % flush, the coins that still trade have survived the creator dump.
- A volume burst on the rebound signals fresh demand, and the anti-chase cap keeps the entry near the low.
- On train this showed up as a small gross edge of about +5-6 % per trade at zero cost.
- Volume confirmation was clearly better than price-only confirmation such as green bars or a break of the prior high.

## Why it does not, and how it would fool us

1. **The gross edge is about the size of the costs.**
   - Train is about +5.7 % gross, minus a 3.7-5 % round trip, leaving about +2 % net.
   - The per-trade spread is about 30 %, so the standard error at 30 trades is about 5.5 %.
   - Showing a +2-3 % net edge at 2 sigma would take about 400 trades: roughly a week of launches at
     this trade rate. This day of data cannot prove it, and validation says it is not there.
2. **The best train numbers come from searching 828 configs.**
   - The highest train mean (+7.2 %, +48 % portfolio) is what the maximum of hundreds of correlated
     noisy configs looks like.
   - Neighbouring parameter values swing the train mean between -10 % and +10 %.
   - On validation those peaks lost about 16-19 % per trade.
3. **Ranking by portfolio return is path-dependent.**
   - One config (stage B #659) made +37 % on the portfolio but averaged -0.25 % per trade. The
     difference came from compounding order and the max-3 slot rule.
   - Selection here leaned on per-coin statistics for that reason.
4. **Fills decide the result.**
   - Many trades are settled inside 1-2 one-minute bars that move ±30 %.
   - One bar of latency or worst-case wick fills flips S4 from flat to -5 to -9 %.
   - A live bot that lands seconds late will see the pessimistic version.
5. **There is very little out-of-sample data.** Validation has 8-12 trades per config and covers one
   UTC morning, so the collapse could partly be a regime change. That cuts both ways: one day of
   train data cannot vouch for any regime.
6. **Fresh dips are rug continuations.** Dips less than about 10 minutes after the high had mean
   60-minute forward returns of -48 % to -76 % in the event study. Anything that buys early dips is
   catching the creator's exit.

## Recommendation

- **Do not trade any F1 configuration, and do not send any to the TEST split.**
- If the family is revisited, it needs multi-day data so that n is at least 300 trades per config,
  plus buy/sell-flow or holder data to tell real buyers from wash volume. One day of OHLCV cannot
  separate this effect from zero.

## Reproduce

All commands run from `/home/user/Claude`:

```bash
python research/lab/strategies/f1_explore.py                        # TRAIN event study
python research/lab/strategies/f1_search.py stageA                  # 540 configs
python research/lab/strategies/f1_search.py stageB                  # 252 configs
python research/lab/strategies/f1_search.py stageC                  # 36 configs
python research/lab/strategies/f1_search.py summary                 # TRAIN leaderboard and counts
python research/lab/strategies/f1_search.py validate                # the 6-config shortlist on VALIDATION
python research/lab/strategies/f1_search.py finalize                # robustness, gates, finalists JSON
python -m pytest -q research/lab/tests/test_f1_dip_rebound_plus.py
```

The trial log is `LAB/f1/trials.jsonl`; note that `stage*` appends to it rather than replacing it.
The validation shortlist is `LAB/f1/validation_shortlist.json`.

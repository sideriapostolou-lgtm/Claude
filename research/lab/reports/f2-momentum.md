# F2 Momentum / breakout continuation: no strategy beats costs out of sample

**Verdict.** No F2 configuration passes the validation gate, so there are **no finalists**:
`finalists/f2-momentum.json` is `[]`. Nothing from this family should go to the judge for TEST.

- **What was searched:**
  - 982 configurations on TRAIN, plus 68 exploratory event-study cuts before the harness search.
  - The 19 best TRAIN configurations were checked on VALIDATION.
- **TRAIN:** 16 configurations had a coin-bootstrap 95% CI above zero.
- **VALIDATION:** none of the 19 had a CI above zero with enough trades. 13 of them lost money.
- **Why the TRAIN winners failed:** their profits came from one anonymous launch farm's behavior on the train
  day. They were not a market-wide momentum effect, and that behavior changed in the validation window.

Classic momentum makes no money on these coins. New highs, volume surges, squeezes and strength right after
graduation have **negative gross returns**, even before costs. The reason is the rug: most coins collapse to
the floor in a single 1-minute bar.

## What was tested

| Family | Entry (all causal, decided at the close of bar i, filled at the next open) | TRAIN configs | Enough trades (≥ 15 trades on ≥ 10 coins) | Mean > 0 | CI low > 0 |
|---|---|---:|---:|---:|---:|
| breakout | close above the high of the last N bars; volume ≥ k x the trailing mean; minimum 5-bar volume; age, market-cap and graduation-type filters; skip coins already at the floor | 464 | 117 | 3 | 0 |
| squeeze | narrow range (volatility contraction), then a close above the range with a volume surge | 96 | 27 | 0 | 0 |
| early | one check at T minutes after graduation: price ≥ x times the graduation close, within d of the post-graduation peak, enough recent volume | 390 | 282 | 58 | 14 |
| trend | close ≥ (1+r) x the close 60 bars ago, at a new 10-bar high, optional higher lows; for old coins of $1M+ | 32 | 16 | 12 | 2 |
| **total** | | **982** | 442 | 73 | 16 |

**Exits tested:**

- fixed stop, from 8 to 30%;
- trail, either fixed (8 to 40%) or scaled by volatility (2-4 x the 15-bar ATR%);
- time stop, from 5 to 360 minutes;
- a fail-fast rule (after K bars, if the trade is not up X%, sell);
- partial take-profit with the trail armed afterwards;
- plain timed holds with no stop.

**Search stages:**

| Stage | Configs | What it varied |
|---|---:|---|
| 1. entry screening | 720 | 3 exit templates |
| 2. exit refinement | 192 | 16 exit variants on the 12 best stage-1 entries |
| 3. stability neighborhood | 38 | around the best stage-2 config |
| 4. trend sub-family | 32 | declared before it was run |

All runs used the default cost model and the $100 portfolio: 20% sizing clamped to $5-$25, at most 3
concurrent positions, `wick_fill="half"`. Every run is logged in `LAB/f2/runs.jsonl`, and
`python research/lab/f2_momentum_search.py count` reproduces the counts.

## Main findings

### 1. Breakouts lose money before costs

The exploratory event studies (TRAIN) measured the gross close-to-close return after a breakout on a coin
not yet at the floor:

- **mean -8% to -23%** at 15 to 120 minutes;
- **median -13% to -44%** at 30 to 120 minutes.

None of the 560 breakout and squeeze configurations has a CI above zero. Only 3 have a positive mean with
enough trades, and those make +0.0% to +7.4% on 17-19 trades with CIs of about [-17, +42].

### 2. The rug dominates everything

- **88%** of instant-graduated coins and **59%** of organic graduates have a one-minute bar whose low is below
  30% of the previous close.
- The median time from graduation to the ~$3k floor is **13-15 minutes**.
- A stop cannot protect against this. The harness default `"half"` fill (halfway between the stop and the
  bar low) is optimistic on these bars. In an early config with a 10% stop (21f9f408bb), 22 of 35 stop
  exits were bars that *closed* below half the stop level. A rug done in one transaction leaves nothing to sell into on the way
  down.
- I added a `rug_aware_fills` stress test in `f2_momentum_search.py`: a stop or trail fill is capped at the
  bar close. **I recommend that every researcher run it.**

### 3. The TRAIN "edge" is one launch farm

All 14 early configurations with a CI above zero live at check_min=25-30. Their trades are almost all
instant-graduated brand tickers: Gemini, NVIDIA, SpaceX, OpenAI, ChatGPT, Apple, X, Uber, FOMO, CNN, Meta,
Mr Beast and so on.

| Farm fact | Value |
|---|---|
| Share of the universe that looks like this farm (instant graduation at $250-500k) | **38% of TRAIN, 44% of VALIDATION** |
| Example ticker repeats in TRAIN | FOMO 11 times, Mr Beast 8, Claude AI 7, Anthropic 6, ... |
| Creator wallets | a fresh one for every coin, so the wallet does not identify the actor |
| Price path | climbs about **+3% per minute**, very smoothly, on about $2k/min of volume |
| End of the path | rugged to the floor at a seemingly random time |

Buying the survivors at minute 30 and holding 10 minutes made **+17.4% per trade on TRAIN**, with a CI of
[+7.2, +26.6]. On VALIDATION the same config lost **-16.1%**, with a CI of [-39.6, +6.7].

| Farm coins alive at minute 30 | TRAIN | VALIDATION |
|---|---:|---:|
| Share still alive at minute 40 | **30 of 32 (94%)** | **16 of 23 (70%)** |
| Gross 10-minute return from minute 30: median | +28% | +15% |
| Gross 10-minute return from minute 30: mean | +17% | **-19%** |
| Rugged inside the 10-minute window | 5 | 8 |

**The climb did not change; the operator's rug timing did.** The sign of the strategy depends entirely on one
anonymous actor's rug schedule. That schedule is not stationary even within a single day, and it can change
at will.

**Stability check (stage 3).** In the hold-10, no-stop configs (minimum price 1.5x the graduation close),
the result **flips sign** between nearby check times. That is a spike, not a plateau:

| Check time after graduation | Per-trade mean on TRAIN |
|---:|---:|
| 20 min | -13% |
| 25 min | +3% |
| 30 min | **+17%** |
| 40 min | -11% |
| 45 min | -4% |

### 4. The trend sub-family cannot be validated

On TRAIN it makes +3% to +8% per trade on old coins of $5M+. These coins are again a single cluster:

- They are ticker-clone coins whose prices imply absurd market caps (XRPN, RLUSD, USDP, USOF, SI276, WSOS,
  XBC...).
- They drift up about 2% per hour under steady bot bids.
- They are sometimes rugged: XBC took -61% inside a hold.

On VALIDATION they produce **1-4 trades**. The splits are by creation time, so validation coins are observed
for at most ~10 hours, and coins this old and this large are rare. Of the 4 trades, one coin (USDP, +40.6%)
is 79% of the profit. This is untestable here, not validated.

## The 19 configurations checked on VALIDATION

Per trade at $20. "Return" is the $100 portfolio return; "DD" is its max drawdown.

| ID | Config | TRAIN trades | TRAIN avg % [CI] | TRAIN return / DD | VAL trades | VAL avg % [CI] | VAL return / DD |
|---|---|---:|---|---|---:|---|---|
| 95bb3c8eae | early30, hold 10, no stop | 30 | +17.4 [+7.2, +26.6] | +120% / 23% | 20 | **-16.1** [-39.6, +6.7] | -56% / 61% |
| c21008b4f8 | early30 (price ≥ 0.5x grad), hold 10, no stop | 41 | +13.4 [+5.1, +21.1] | +127% / 23% | 28 | **-12.3** [-29.6, +4.3] | -59% / 64% |
| 7028342f06 | same, with $25k volume | 16 | +13.5 [+4.1, +22.4] | +50% / 11% | 7 | +12.6 [-1.8, +25.6] | +19% / 7% |
| b754a33c58 | early30, stop 8%, trail 8%, 20 min | 30 | +21.4 [+3.9, +40.2] | +124% / 21% | 20 | -5.7 [-25.4, +16.1] | -17% / 33% |
| af1125fe2f | early30, stop 10%, take-profit 15%, 15 min | 30 | +7.4 [+3.6, +10.5] | +52% / 5% | 20 | -7.6 [-19.5, +3.9] | -29% / 35% |
| 20e3569832 | early30, hold 5, no stop | 30 | +12.0 [+8.2, +16.6] | +86% / 5% | 20 | -6.5 [-22.9, +6.3] | -27% / 34% |
| 71c74e25eb | early30, stop 20%, hold 10 | 30 | +16.4 [+6.9, +25.4] | +113% / 18% | 20 | -8.0 [-24.2, +8.1] | -33% / 40% |
| 89dedffc42 | early30, stop 20%, hold 5 | 30 | +9.0 [+4.7, +13.4] | +64% / 6% | 20 | -4.1 [-16.0, +5.3] | -18% / 25% |
| 837254080b | early30 (0.5x), stop 20%, hold 10 | 41 | +11.2 [+3.8, +19.2] | +105% / 18% | 28 | -6.5 [-18.5, +5.2] | -37% / 44% |
| f488707dc1 | early30, stop 20%, take-profit 30% | 30 | +12.5 [+2.6, +21.7] | +79% / 18% | 20 | -4.5 [-22.5, +11.3] | -24% / 38% |
| 0b0817c7f8 | early30 (0.5x), stop 10%, take-profit 15% | 41 | +5.4 [+2.5, +8.0] | +52% / 6% | 28 | -6.3 [-15.9, +1.7] | -34% / 40% |
| 8864b4a865 | early30 (0.5x), stop 8%, trail 8% | 41 | +14.8 [+1.3, +28.6] | +102% / 21% | 28 | -4.7 [-20.6, +10.9] | -25% / 37% |
| 4eeaada088 | early30 (0.5x), stop 20%, take-profit 30% | 41 | +8.2 [+0.0, +16.0] | +64% / 18% | 28 | -4.3 [-17.7, +8.9] | -26% / 39% |
| e67463df74 | early25, stop 20%, hold 20 | 37 | +20.1 [+3.0, +37.3] | +146% / 44% | 27 | +1.0 [-17.1, +20.6] | -25% / 43% |
| 43ca5cb96b | early20, stop 20%, hold 20 | 38 | +18.5 [-0.3, +38.1] | +103% / 33% | 29 | -2.2 [-21.1, +17.1] | -10% / 39% |
| 84da234f50 | trend, $5M+, 6h+, +2%/60m, stop/trail 10%, 120m | 19 | +3.1 [+1.7, +4.7] | +5% / 2% | 1 | +8.6 [n/a] | +2% / 0% |
| a685b296b0 | trend, $5M+, 6h+, stop/trail 20%, 360m | 20 | +7.5 [-2.0, +15.4] | +11% / 2% | 1 | +10.0 [n/a] | +2% / 0% |
| e9e07c6499 | trend, $5M+, 2h+, stop/trail 20%, 360m | 22 | +6.9 [-1.8, +15.5] | +12% / 1% | 4 | +12.8 [+0.6, +31.0] | +11% / 1% |
| 6f345de233 | trend, $1M+, 6h+, stop/trail 10%, 120m | 26 | +0.6 [-4.5, +4.4] | -5% / 13% | 1 | +8.6 [n/a] | +2% / 0% |

**Notes on the table:**

- The shortlist rule was set before validation: rank by the TRAIN lower CI; keep configs with ≥ 15 trades on
  ≥ 10 coins and a positive mean; take the top 15 early/breakout/squeeze configs plus the top 4 distinct trend
  configs.
- The only early config positive on validation (7028342f06) has 7 trades. Its CI crosses 0, and one coin
  carries 45% of its profit.
- **Validation looks like short volatility.** Win rates are 50-80% and medians are positive, often +5% to
  +15%. The means are negative because a few -100% rugs erase many small wins. A high win rate here says
  nothing about profitability.

## Robustness of the three best rejected candidates (VALIDATION)

Per-trade average %. All three have a clean lookahead audit on both TRAIN and VALIDATION. Full data is in
`reports/f2-momentum-rejected.json`.

| Variant | 95bb3c8eae (TRAIN best) | e67463df74 (least-bad on VAL, ≥ 20 trades) | e9e07c6499 (trend, 4 trades) |
|---|---:|---:|---:|
| base | -16.1 (portfolio -56%) | +1.0 (portfolio -25%) | +12.8 (portfolio +11%) |
| costs x1.5 | -17.4 | -0.5 | +12.0 |
| costs x2 | -18.6 | -2.0 | +11.3 |
| +1 bar latency | -12.3 | +0.7 | +12.8 |
| `wick_fill="worst"` | -16.1 (no stops) | **-9.5** | +12.8 |
| `wick_fill="touch"` | -16.1 | +11.5 | +12.8 |
| rug-aware fills | -16.1 | **-8.4** | +12.8 |
| $10 positions | -16.3 (portfolio -33%) | +0.8 (portfolio -8%) | +12.6 |
| $40 positions | -16.1 (portfolio -84%) | +1.0 (portfolio -34%) | +12.9 |
| without the best coin | -19.0 (Tesla removed) | -2.8 (Tesla removed) | +3.6 (USDP removed; 3 trades) |
| first half / second half of VAL | -11.9 / -21.2 | +9.9 / -10.2 | +40.6 (1 trade) / +3.6 (3 trades) |

## Why it might have worked

These are the arguments for the hypothesis, recorded for completeness.

- **Survival filter.** Most coins rug within about 15 minutes, so a coin still climbing at minute 30 has
  passed a filter. If rug hazard fell with age, buying survivors would earn the climb while risking less.
  That is the logic of the early family.
- **Bot-driven climbs.** The farm's climbs are mechanical and smooth, so the 10-minute drift after minute 30
  is predictable while the bot runs.
- **Cheap, slow drift on large coins.** Old coins of $5M+ have the lowest pool-fee tier (round trip about
  1.5%) and drift slowly upward under steady bot bids, so a long hold can beat the costs.

## Strongest reasons this would fool us, and why it is rejected

1. **One actor, not a market effect.** The TRAIN profit comes from one launch farm, and the trend profit from
   a cluster of ticker-clone coins. The payoff depends on when an anonymous operator rugs, and that timing
   changed between TRAIN and VALIDATION on the same day: survival from minute 30 to 40 fell from 94% to 70%.
   The operator can also react to outside buyers.
2. **A spike in parameter space.** Moving the check from 30 to 40 minutes, or the hold from 10 to 20 minutes,
   flips the sign on TRAIN.
3. **Multiple testing.** About 1,050 looks in total (982 configs plus 68 event-study cuts), with 442 configs
   having enough trades. With no edge at all, roughly 2.5% of independent configs, about 11, would show a CI
   above 0 by chance. We saw 16 highly correlated ones, which is consistent with noise plus one actor's
   behavior on the train day. On VALIDATION, 0 of 19 pass.
4. **Optimistic rug fills.** `"half"` assumes a stop gets half the wick. On single-transaction rugs the
   realistic fill is the floor. For e67463df74, `worst` and rug-aware fills move VALIDATION from +1.0% to
   -8% or -9.5%.
5. **Fat left tail; the user cannot afford a ruin path.** The no-stop holds lose 100% on a rug. At $40 per
   position the best TRAIN config's portfolio falls 84% on VALIDATION.
6. **Right-censoring.** Long-horizon strategies (trend, 6h+) get almost no out-of-sample trades with
   creation-time splits. Their TRAIN numbers cannot be checked here.
7. **One day, one regime.** All 1,070 coins come from 22.5 hours. Even a pass would only describe that day's
   launch farms.

## Notes for the other researchers and the judge

- **The universe is dominated by launch farms.** About 40% of the default universe is one brand-ticker farm.
  Any strategy that trades in the first hour after graduation is mostly trading that farm.
- **Check how much profit comes from farm coins.** For any candidate, report the share of profit from
  instant-graduated coins that graduate at $250-500k, and from the ticker-clone coins above $5M.
- **Run rug-aware fills.** Use `wick_fill="worst"` or the rug-aware stress in `f2_momentum_search.py`. Many
  stop exits are rug bars.
- **Long-horizon ideas need a different holdout.** One option is to split trades by entry time within the
  same coins and re-fit only on the early part. The creation-time split leaves them almost no validation
  trades.

## Files and reproduction

**Files:**

- Strategy classes: `research/lab/strategies/f2-momentum.py`.
  - `F2Params` holds the parameters; `F2Momentum` is the strategy; `factory(params)` builds the zero-argument
    factory for the harness.
  - The file name has a hyphen, so load it with importlib (see `f2_momentum_search.load_f2`).
- Search, shortlist, validation and robustness: `research/lab/f2_momentum_search.py`.
- Tests: `research/lab/tests/test_f2_momentum.py`.
  - The audit is clean on synthetic coins for all four families and on 60 real TRAIN coins.
  - Garbage future bars never change past decisions or fills.
  - No state is shared at class level, and no entry happens before graduation.
- Finalists: `research/lab/finalists/f2-momentum.json` is `[]`. The rejected candidates and their robustness
  are in `research/lab/reports/f2-momentum-rejected.json`.
- Data (not committed), under `LAB/f2/`:
  - `runs.jsonl`: every TRAIN and VALIDATION run;
  - `eda_log.json`: the 68 event-study cuts;
  - `robustness_rejected.json`.

**Commands:**

```bash
cd /home/user/Claude
python research/lab/f2_momentum_search.py stage1      # 720 configs, TRAIN
python research/lab/f2_momentum_search.py stage2      # 192
python research/lab/f2_momentum_search.py stage3      # 38 new (40 incl. 2 duplicates)
python research/lab/f2_momentum_search.py stage4      # 32 trend configs
python research/lab/f2_momentum_search.py validate    # shortlist -> VALIDATION
python research/lab/f2_momentum_search.py count
python -m pytest -q research/lab/tests
```

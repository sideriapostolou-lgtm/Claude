# Lab 7 W2: adversarial skeptic's review of the TRAIN result

Written 2026-10-11 ~01:10 UTC by the W2 skeptic. It reviews `W2/train.json`: run 2026-10-10 21:26 UTC, PREREG sha256
`8184818b...`, PLAN sha256 `c6f62ddf...`. I changed no specialist file. I added no trial to `trials.json`. I never
read a VAL or TEST return.

**Verdict: the NO EDGE result stands.** The task framing said the specialist claimed a cell passed. It did not: the
specialist reports `NO_EDGE_TRAIN`, with 0 of 54 cells passing. So there is no pass to refute. Instead, I tried to
break the NO EDGE result: I looked for any bug that could make a real edge look like a loss. I rebuilt every trade of
the best cell, on all 15,842 TRAIN windows, with my own code. It matches the specialist to the last digit. I found
no code bug. I found one wrong sentence in the plain-words summary meant for the owner (§7), and two small
process notes (§8).

## In plain words (for the owner)

I redid the crypto desk's work from scratch. I wrote my own program, which uses none of the specialist's code. It
read the raw trade records, the raw Bitcoin prices and the raw settlement results. Then I replayed the best rule on
every window.

- **Same trades.** I got the same 50,934 trades, with the same prices, fees and result: a loss of about 7 cents on
  every dollar traded, $72,158 in total.
- **It loses even with no fees.** With every fee removed, the rule still loses about 0.7 cents per dollar. No
  cheaper venue or fee deal could save it.
- **The price knew better.** The "fair price" the desk trusted was a worse forecast than the market's own price.
  When the two disagreed, the market was usually right.
- **One correction to the summary you were given.** It says stop-losses "made the losses smaller". They did not.
  In all 36 versions with a stop-loss, the stop made the loss bigger. Only the $10-a-day loss limit made the total
  smaller, by trading much less. Even then it lost money on every day.

The verdict holds. This desk should not trade the idea, with pretend money or real money.

## 1. What I re-derived, independently

My scripts sit outside git, in the session scratchpad, folder `w2skeptic/`:

- `indep.py`: contract, fair, tape and simulator;
- `sample.py`: a side-by-side comparison with the specialist's pipeline;
- `full.py`: the whole of TRAIN;
- `audit40.py`: a check of 40 trades against the raw records;
- `lookahead.py`: a test that the fair never sees the future;
- `winner_check.py`: a check of who won each window.

`indep.py` imports neither `research/lab7/core.py` nor any lab 5 module. It reads only:

- lab 4's `markets.parquet` (outcomes, token ids, winner, closedTime, end date, slug);
- the raw `trades/<id>.parquet` tapes, including each print's token id;
- lab 5's `rules.parquet` (description, resolution source, TWAP length, priceToBeat);
- the Binance 1 s klines;
- the one pre-registered constant `sigma_b` from `research/lab5/structure.json`.

It recomputes all of the following by itself:

- the window contract: the start time taken from the slug, the end, the length, Chainlink or Binance, TWAP or not;
- the spot fair value, with 1 h realized variance and the Chainlink basis;
- the tape sides;
- the gap signal, the entry, the take profit (taker and maker), the stop and the time stop;
- the fees and the settlement.

The only thing it takes from the specialist is the list of TRAIN window ids, which is lab 5's catalogue by design.

**Side by side with the specialist's pipeline.** I ran `run.build_market` and `run.market_trips` on 52 seeded windows:
30 5m, 10 15m and 8 1h BTC windows, plus 4 ETH / SOL / XRP windows. I compared four cells: the best taker cell,
`m0.03|tp0.03|sl0.05|tend|taker`, `m0.05|tp0.08|sl0.1|tend|maker` and `hold|m0.05`.

- The contract fields, the winner and the fair agree at every one of the 89,201 prints (0 NaN mismatches, maximum
  difference 0).
- All 1,072 round trips are identical: signal time and price, entry time and price, exit time and price, reason,
  exit leg, fee and P&L (maximum difference 0).
- The outcome index agrees with the token id on every print (0 mismatches). Outcome 0 is the "Up" token.

**The whole of TRAIN, best cell `m0.05|tp0.08|slnone|tend|taker`:**

| quantity | specialist | skeptic (independent) |
|---|---|---|
| windows evaluated / skipped (< 50 fills) | 15,842 / 1 | 15,842 / 1 |
| round trips / missed entries / windows traded | 50,934 / 993 / 15,822 | 50,934 / 993 / 15,822 |
| mean net per $ (US fee) | -0.070835 | -0.070835 |
| CI95, clustered by the hour the window ends | [-0.0752, -0.0662] (lab 4's, B = 2000) | [-0.0754, -0.0664] (my own bootstrap) |
| CI95, clustered by UTC day (46 clusters) | - | [-0.0754, -0.0668] |
| gross mean with no fee at all, CI95 | - | **-0.0075 [-0.0120, -0.0028]** |
| total | -$72,158.47 | -$72,158.47 |
| win rate; cents kept on wins / lost on losses | 53.75 %; 8.78 / 16.98 | 53.75 %; 8.78 / 16.98 |
| exit mix: fair / tp / time / time->settle | 44.4 / 34.0 / 18.5 / 3.0 % | 44.4 / 34.0 / 18.5 / 3.0 % |
| gap at the signal / slippage / gap left at the fill | 8.06c / 4.47c / 3.60c | 8.06c / 4.47c / 3.60c |

Two more cells over all of TRAIN:

| cell | specialist (n, mean) | skeptic (n, mean, gross with no fee) |
|---|---|---|
| `hold\|m0.05` | 15,822, -0.04395 | 15,822, -0.04395, gross -0.0102 [-0.0265, +0.0072] |
| `m0.05\|tp0.08\|sl0.1\|tend\|taker` | 81,453, -0.08113 | 81,453, -0.08113, gross -0.0115 [-0.0151, -0.0079] |

## 2. Raw-row audit of 40 random trips (best cell)

I picked these 40 trips with a seed from the 203 best-cell trips of the 52 sampled windows. For each trip I re-read the
raw parquet and checked every rule from the raw rows: token id, side and price.

- The signal is a buyable print for the bought side, at the recorded price.
- The entry is the FIRST buyable print for that side at least 10 s after the signal: a taker BUY of its own token,
  or a taker SELL of the other token, at the recorded price.
- A take-profit or fair trigger is a print at or above the target, strictly after the entry's second.
- Every taker exit is the first SELL-side print for the side at least 10 s after the trigger. No buy-side print
  ever fills a sell.
- The time stop triggers exactly 60 s (5m / 15m) or 300 s (1h) before the window ends and fills before the end.
- Settlement pays the venue's outcome.
- The fee and the P&L, worked out by hand, match.

**All 40 trips pass every check.** 31 entries filled on a taker BUY of the side's own token, 9 on a taker SELL of the
other token.

| # | window | len | side | signal price | fair at signal | entry lag s | entry price | entry print | exit | exit lag s | exit price | fee $ | net / $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3574351 | 5m | Up | 0.75 | 0.8288 | 12 | 0.78 | BUY own token | tp | 10 | 0.89 | 0.4803 | 0.117 |
| 2 | 3501195 | 5m | Down | 0.38 | 0.464 | 11 | 0.26 | SELL other token | fair | 10 | 0.27 | 2.082 | -0.0657 |
| 3 | 3501195 | 5m | Down | 0.2958 | 0.4419 | 10 | 0.29 | SELL other token | time | 10 | 0.22 | 1.809 | -0.3318 |
| 4 | 3450731 | 5m | Down | 0.37 | 0.43 | 10 | 0.43 | BUY own token | fair | 11 | 0.45 | 1.592 | -0.0331 |
| 5 | 3450731 | 5m | Down | 0.29 | 0.3976 | 11 | 0.29 | SELL other token | fair | 11 | 0.35 | 2.077 | 0.103 |
| 6 | 3378678 | 15m | Up | 0.45 | 0.5104 | 15 | 0.33 | BUY own token | tp | 10 | 0.45 | 1.974 | 0.2649 |
| 7 | 3302443 | 15m | Up | 0.85 | 0.9241 | 12 | 0.88 | BUY own token | tp | 21 | 0.967 | 0.2172 | 0.088 |
| 8 | 3235409 | 5m | Down | 0.36 | 0.4681 | 11 | 0.53 | BUY own token | time | 11 | 0.16 | 1.006 | -0.7484 |
| 9 | 3124457 | 1h | Up | 0.5 | 0.5629 | 24 | 0.5 | BUY own token | tp | 62 | 0.64 | 1.335 | 0.2132 |
| 10 | 3124457 | 1h | Up | 0.47 | 0.5277 | 51 | 0.51 | BUY own token | tp | 36 | 0.59 | 1.34 | 0.0898 |
| 11 | 3123558 | 5m | Down | 0.37 | 0.424 | 12 | 0.4 | BUY own token | tp | 10 | 0.39 | 1.661 | -0.108 |
| 12 | 3067413 | 5m | Down | 0.47 | 0.5695 | 10 | 0.67 | BUY own token | tp | 10 | 0.7 | 0.8944 | 0.0001 |
| 13 | 3067413 | 5m | Up | 0.21 | 0.2956 | 10 | 0.2 | BUY own token | tp | 10 | 0.2 | 2.224 | -0.1112 |
| 14 | 3030774 | 5m | Down | 0.28 | 0.3509 | 10 | 0.22 | BUY own token | fair | 10 | 0.13 | 1.799 | -0.499 |
| 15 | 3029101 | 15m | Up | 0.35 | 0.402 | 12 | 0.49 | SELL other token | fair | 12 | 0.52 | 1.417 | -0.0096 |
| 16 | 3005378 | 1h | Down | 0.63 | 0.682 | 18 | 0.6482 | BUY own token | fair | 32 | 0.57 | 1.015 | -0.1713 |
| 17 | 3017748 | 5m | Up | 0.67 | 0.74 | 10 | 0.84 | BUY own token | time | 12 | 0.35 | 0.5989 | -0.6133 |
| 18 | 2954520 | 1h | Up | 0.5 | 0.5896 | 17 | 0.5 | BUY own token | tp | 12 | 0.6749 | 1.305 | 0.2846 |
| 19 | 2929943 | 5m | Up | 0.26 | 0.3335 | 11 | 0.23 | BUY own token | time | 10 | 0.03 | 1.246 | -0.9319 |
| 20 | 2925084 | 15m | Up | 0.43 | 0.5228 | 15 | 0.54 | BUY own token | fair | 12 | 0.58 | 1.266 | 0.0108 |
| 21 | 2925084 | 15m | Up | 0.17 | 0.254 | 10 | 0.22 | BUY own token | tp | 10 | 0.29 | 2.385 | 0.1989 |
| 22 | 2915461 | 5m | Down | 0.5 | 0.5533 | 11 | 0.48 | BUY own token | fair | 11 | 0.52 | 1.446 | 0.0111 |
| 23 | 2915461 | 5m | Down | 0.53 | 0.5808 | 11 | 0.69 | BUY own token | tp | 10 | 0.85 | 0.6877 | 0.1975 |
| 24 | 2915461 | 5m | Down | 0.83 | 0.928 | 10 | 0.89 | BUY own token | tp | 11 | 0.96 | 0.2129 | 0.068 |
| 25 | 2912546 | 5m | Up | 0.3 | 0.3539 | 11 | 0.29 | BUY own token | time | 10 | 0.03 | 1.126 | -0.9529 |
| 26 | 2905942 | 5m | Down | 0.41 | 0.4637 | 10 | 0.48 | BUY own token | fair | 11 | 0.5285 | 1.444 | 0.0288 |
| 27 | 2890600 | 15m | Down | 0.4 | 0.5076 | 11 | 0.53 | BUY own token | fair | 11 | 0.64 | 1.258 | 0.1447 |
| 28 | 2871956 | 1h | Down | 0.74 | 0.7967 | 26 | 0.76 | SELL other token | tp | 17 | 0.87 | 0.5405 | 0.1177 |
| 29 | 2861299 | 15m | Up | 0.54 | 0.6033 | 10 | 0.63 | BUY own token | tp | 10 | 0.74 | 0.9388 | 0.1277 |
| 30 | 2845174 | 1h | Up | 0.4485 | 0.5307 | 10 | 0.47 | BUY own token | tp | 12 | 0.5853 | 1.454 | 0.1726 |
| 31 | 2845174 | 1h | Up | 0.55 | 0.6153 | 55 | 0.58 | SELL other token | fair | 12 | 0.55 | 1.177 | -0.1106 |
| 32 | 2845174 | 1h | Up | 0.38 | 0.4708 | 27 | 0.37 | BUY own token | time | 11 | 0.02 | 0.9493 | -0.9934 |
| 33 | 2854056 | 15m | Down | 0.5505 | 0.6159 | 11 | 0.55 | SELL other token | fair | 21 | 0.63 | 1.215 | 0.0847 |
| 34 | 2854056 | 15m | Up | 0.38 | 0.4997 | 62 | 0.35 | BUY own token | tp | 21 | 0.49 | 1.896 | 0.3052 |
| 35 | 2834588 | 5m | Down | 0.1 | 0.1549 | 10 | 0.06 | BUY own token | time | 10 | 0.02098 | 1.782 | -0.7394 |
| 36 | 2801690 | 5m | Up | 0.7 | 0.7513 | 11 | 0.82 | SELL other token | tp | 11 | 0.9335 | 0.3554 | 0.1207 |
| 37 | 2789879 | 5m | Down | 0.48 | 0.6004 | 11 | 0.51 | BUY own token | fair | 14 | 0.7269 | 1.222 | 0.3643 |
| 38 | 2789879 | 5m | Up | 0.42 | 0.5663 | 11 | 0.27 | BUY own token | time | 10 | 0.17 | 1.741 | -0.4574 |
| 39 | 2750522 | 15m | Up | 0.43 | 0.4864 | 11 | 0.52 | BUY own token | fair | 17 | 0.6 | 1.309 | 0.0884 |
| 40 | 2750522 | 15m | Down | 0.32 | 0.3772 | 12 | 0.31 | SELL other token | time | 13 | 0.01 | 1.004 | -1.018 |

Rows 2, 6, 8 and 17 show what a 10 s lag does in a 5-minute window: the fill was 12-17c away from the signal print.
Row 35 entered at 6c on a 10c signal: the band applies to the signal print, as the plan says.

## 3. Lookahead

- **The fair on real data.** I garbled every Binance candle that opens at or after a cut and recomputed the
  specialist's fair (`run.fair_of`, which calls lab 5 `q_event`). I used 24 cuts on 8 windows: 5m, 15m, 1h, and
  TWAP windows of 30 s and 60 s. Every fair at a print stamped at or before the cut stayed bit-identical. The fairs
  after the cut did change: 96-99.9 % of them at 22 of the 24 cuts, and 32 % and 79 % at the other two. So the test
  can detect a leak.
- **Winner and closedTime** reach only the settlement payout, `settle_t` and `hard_end`. `hard_end` is always the
  window end, because closedTime comes 18 s or more after it (0 windows closed before their time stop). None of
  them reach the signal, the fair or an exit decision. priceToBeat is public when the window opens.
- **The winners themselves.** The winner index agrees with Chainlink's `final_price >= priceToBeat` on 14,092 of
  14,092 Chainlink windows. It agrees with Binance's close-at-end >= open-at-start on 897 of 897 BTC 1h windows.
  Up won 50.3 % of TRAIN windows.
- W2 has no game-start proxy, so that check does not apply.

## 4. Fills, clustering, the placebo, multiple testing

- **Impossible fills: none.** Every entry is on a buy-side print and every taker exit on a sell-side print (§2). Every
  fill comes at least 10 s after its decision.
  - The maker variant needs a trade-through and enough size. Every maker cell did worse than its taker twin.
  - The one-print fill is generous: 86.5 % of entries filled at a print smaller than our $20 order. So the true
    result is, if anything, worse.
- **Clustering.** Events are the UTC hour of the window end: 1,105 events. Clustering by UTC day instead (46
  clusters) leaves the CI95 almost unchanged: [-0.0754, -0.0668]. The upper bound sits more than 6 cents below zero
  under either choice.
- **The placebo.** I read the code: decision times are drawn uniformly over [reference public, time stop), the side
  50 / 50, the band is checked on the drawn side's last price, there are up to 25 redraws, and the counterparts are
  independent. My own placebo, with my own simulator and seeds, on a random 1,500-window subsample with 20 draws:
  - real mean -0.0751;
  - placebo mean -0.0654, p95 -0.0575;
  - the real mean sits at the 10th percentile.

  The specialist's (all windows, 200 draws) put it at the 75.5th percentile. Either way it fails, and the cell
  already fails conditions 2 to 4.
- **The reference cells "beating" their placebo** (97.5-98th percentile) does not show the signal knows something.
  `hold|m0.05` paid 51.4c on average and won 50.7 % of the time. Its gross return to settlement, before any fee, is
  -1.0 % [-2.7 %, +0.7 %]. That is what buying at the ask of a well-priced market looks like. The placebo also draws
  later times and more extreme prices, where the fee and the spread cost more per dollar, so the comparison is not
  like for like. The specialist's sentence "the gap signal carries a little information about the outcome" is not
  supported.
- **Multiple testing.**
  - W2 ran 57 trials, all with `passes = false`. The 57 ledger rows match `train.json` exactly (n, mean, CI, passes,
    hashes).
  - At the time of the run, there were 3,165 trials across labs 2-7.
  - With no pass, multiplicity cannot have created a false one.
  - No selectable cell has a positive mean (the best is -0.0708). No cell is positive under the stress fee.

## 5. Why it loses: the fair is the weaker forecast

On a 15 s grid inside every TRAIN window (553,721 points), I compared two forecasts: the last print's Up price and the
fair. I scored each with the Brier score (lower is better):

- the last price: 0.1750;
- the fair: 0.1777;
- a coin flip: 0.25.

The table looks only at the points where the fair and the price disagree by 5c or more:

| case | n | Up price | fair (Up) | Up actually won |
|---|---|---|---|---|
| fair says Up is cheap by 5c or more | 79,018 | 0.394 | 0.489 | 0.434 |
| fair says Down is cheap by 5c or more | 88,577 | 0.608 | 0.511 | 0.602 |

The model sits too close to 50 %. The market was right when the fair said Down was cheap. When the fair said Up was
cheap, the market was closer than the fair. So the "gap" the desk buys is mostly the model's own error. This
confirms the specialist's reading.

## 6. A diagnostic on speed (not pre-registered, not a trial, not a selector, TRAIN only)

The plan fixes a 10 s lag. To test the specialist's claim that "a faster trader is not obviously rescued", I re-ran
two cells with a 2 s lag:

- **The best cell:** -0.0424 per $ [-0.0456, -0.0391]. Before fees it makes +0.023, but the fees cost 6.6 % per $.
- **`hold|m0.05`:** -0.0085 [-0.025, +0.009]. Before fees it makes +0.027.

Speed cuts the loss but does not turn it into a profit after the US fee. And Polymarket US does not appear to list
these windows at all (VENUES.md: on 2026-10-09 its non-sports markets ending within 48 h were hourly / weekly
strike markets and temperature brackets). These two looks are not in `trials.json`. Anyone who builds on them should
count them as trials and pre-register any new idea on new data.

## 7. Correction needed: the plain-words summary for the owner

The specialist's plain text says "stops plus a daily loss limit only made the losses smaller". **The stop-loss half
of that is wrong.** In all 36 cells with a stop, the mean is worse than in its no-stop twin, and the total loss is
larger. For example:

| rule (m 5c, tp 8c, taker) | mean net per $ | total |
|---|---|---|
| no stop | -0.0708 | -$72,158 |
| 10c stop | -0.0811 | -$132,164 |
| 5c stop | -0.0845 | -$158,594 |

Only the $10 daily loss limit made the total smaller (-$1,216), and it did so by taking 1,485 trades instead of
50,934. It still lost every day. Suggested wording: "Stop-losses made it lose more. Only the daily loss limit
shrank the total, by trading much less, and even then it lost every day."

## 8. Process notes (none changes the verdict)

- **Frozen code.** `PLAN.md`, `core.py` and `W2/run.py` have not changed since before the PREREG: the same git blob
  hashes from the pre-registration commits to HEAD, and file times of 20:23 / 20:34 UTC. The PREREG sha `8184818b`
  matches the file, `train.json`, all 57 ledger rows and its first commit (827ae28, 21:20 UTC). That commit came
  before the result commit (d6aeff8, 21:29). `tests/test_w2.py` and `tests/test_core.py` pass (46 tests).
- **The dry run is missing from the PREREG.** PREREG §0 lists the real-data runs done before it was hashed: the
  smoke test, the catalogue counts and the synthetic tests. The specialist's report also names a 30-window pipeline
  dry run (`scratchpad/lab7w2/dry.py`, which calls `run_stage`). That script prints the stage verdict and the names
  of the placebo cells, which include the best cell by CI on those 30 windows. So "numbers not read" is slightly
  generous. It cannot have mattered here, for three reasons:
  - the grid, fees, bar and splits were fixed in PLAN.md beforehand;
  - by the specialist's account, only the PREREG's timestamp line changed afterwards;
  - the result is NO EDGE.

  For the next labs: list dry runs in the PREREG, and make them suppress the verdict line.
- **Location (state now).** The specialist's note says the W2 files are untracked. They have since been committed
  (827ae28, d6aeff8), and the working copy of `train.json` equals the committed one. I wrote only this file. My
  scripts and outputs stay in the scratchpad (`w2skeptic/`, a few MB). Nothing was pushed or deployed, and `src/`
  was not touched.

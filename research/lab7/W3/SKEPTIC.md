# Lab 7 W3: adversarial skeptic's review of the TRAIN result

Written 2026-10-11 ~02:00 UTC by the W3 skeptic. It reviews `W3/train.json` (run finished 2026-10-11 01:16 UTC; W3
PREREG sha256 `b86d459f...`, PLAN sha256 `c6f62ddf...`). This file is the only one I added. I changed no specialist
file and added no trial to `trials.json` (3,661 across labs 2-7 after the W3 run). I never read VAL or TEST.
Everything here was written AFTER the TRAIN result was read, so the extra readings below are post-hoc. They decide
nothing.

**Verdict: the NO EDGE result stands.** No W3 cell passed, so there is no pass to refute. Instead I looked for a
bug that could make a real edge look like a loss. I found none:

- I rebuilt trades from the raw files with my own code: 32,053 trip comparisons over 10 cells in 456 random
  markets. Then I rebuilt five whole cells over every TRAIN market. They match the specialist's engine exactly.
- 20 trades were re-derived by hand from the raw rows. All 20 match to 1e-9.
- The data conventions check out: the trade side, the winners and the units. So does the in-play window: the
  start and the recorded end line up with the real game.
- I then gave all 288 rules perfect execution: no spread, no delay, no missed entry, exits exactly at their levels.
  None makes money after the Polymarket US fee. All of them still lose with a fee-free entry and a fee-free take
  profit, paying the fee only on their stops.

## In plain words (for the owner)

I checked this desk's homework by redoing it from scratch, with my own program, on the raw trade records. I got
the same trades, the same prices, the same fees and the same losses, down to the cent.

Then I asked the friendliest question I could. Suppose the trader were perfect:

- it buys at exactly the price that set off the signal, with no delay;
- it sells at exactly +3c, +5c or +10c, or stops out at exactly -5c or -10c.

Would it make money then? No. All 288 versions still lose after the Polymarket US fee; the best loses about 4.3
cents per dollar. Suppose it also paid no fee to buy and no fee to take its profit, only on its stops. It still
loses about 1 cent per dollar.

The price swings do carry some information. After a team's price jumps by 5c or 10c in two to five minutes, it
tends to keep drifting the same way by another 1.5c to 3.5c (less after 5c jumps, more after 10c jumps). But much
of that drift happens in the first seconds, and the price you can actually buy at already includes it. From there,
a quick in-and-out trade loses 0.5c to 1.7c per contract to the gap between the buying and selling prices. Then the
fee takes about 3c more. Being ten times faster (1 second instead of 10) changes almost nothing.

So "get in at 50, get out at 55" does not work on live games. The best rule's take profit was hit about half the
time, but after fees it needed about two wins in every three to break even. Good risk management (stops, a daily
loss limit) makes the losses smaller. It cannot turn them into profits.

## 1. What I re-derived, independently

My scripts sit outside git, in the session scratchpad (`w3skeptic/`):

- `indep.py`: my simulator, written from PLAN §4 / §5 W3 and W3 PREREG §1-4.
  - It is pure Python with `bisect`.
  - It does not call `core.Tape`, `core.swing_signals`, `core.walk`, `core.simulate` or any core fill helper.
  - It reads `trades/<id>.parquet` raw and builds everything itself: the sides, the prices, the swing signal, the
    window and band, the entry, the taker and maker take profits, the stop, the 15 / 45 min / game-end stops,
    settlement and fees.
- `compare.py`: it runs `indep.py` side by side with the specialist's `run.market_trips`, which uses `core`.
- `full_best.py`: whole cells over every TRAIN market (both end kinds) through `indep.py`, with my own event
  bootstrap (seed 12345, against the specialist's seed 0).
- `twenty.py`: 20 trades rebuilt by hand from the raw rows with pandas filters. This is a third path.
- `conv.py`, `timing.py`, `ideal.py`, `markout.py`, `fast.py`: the readings in §1.3 and §4.

The only input I take from the specialist is `run.universe("train")`. It gives 8,259 game-winner markets; 4,392
have a recorded end and 3,867 a fallback end, as in PREREG §0. A passing test (`test_w3.py`) checks that this
universe equals lab 4 P6's own.

### 1.1 Trip-by-trip agreement

| check | result |
|---|---|
| 456 random TRAIN recorded-end markets × 10 cells (see the list below this table) | 32,053 trip comparisons: outcome, signal time, entry time and price, exit time and price, reason, exit leg, fee and P&L all identical; **0 mismatches**; missed-entry counts equal in every (market, cell). The exits covered: tp 15,425, sl 15,224, settle 955, time 395, sl->settle 51, tp->settle 2, time->settle 1; legs: taker 22,653, maker 8,391, settlement 1,009 |
| `tests/test_w3.py` and `tests/test_core.py` | 42 passed |

The 10 cells compared:

- `mom|x0.1|y5m|tp0.05|sl0.05|tend|taker` (the best cell) and its fade twin;
- `mom|x0.05|y2m|tp0.03|sl0.1|t15m|maker`, `fade|x0.05|y5m|tp0.1|sl0.05|t45m|maker`;
- `mom|x0.1|y2m|tp0.1|sl0.1|t45m|taker`, `fade|x0.1|y2m|tp0.03|sl0.05|t15m|taker`;
- `mom|x0.05|y5m|tp0.05|sl0.1|tend|maker`, `fade|x0.05|y2m|tp0.1|sl0.1|tend|maker`;
- the references `hold|mom|x0.1|y5m` and `hold|fade|x0.05|y2m`.

### 1.2 Five whole cells over every TRAIN market

Every number below is equal in `train.json` and in my `indep.py` run, to the last digit shown, except the CI
bounds. Those come from a different bootstrap seed and agree to within 0.0002 for the selectable cells and
0.0006 for the reference.

| cell | n / missed / games | mean net per $ (US) | CI95 specialist / mine | gross | win rate | total $ | fallback-end n / mean |
|---|---|---|---|---|---|---|---|
| `mom\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` (best) | 40,859 / 34 / 3,354 | -0.068758 | [-0.0709, -0.0665] / [-0.0710, -0.0666] | -0.007672 | 43.01 % | -56,188.03 | 27,078 / -0.06972 |
| `fade\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` (its mirror twin) | 40,892 / 43 / 3,354 | -0.092769 | [-0.0955, -0.0899] / [-0.0956, -0.0901] | -0.018607 | 39.91 % | -75,870.26 | 27,334 / -0.08793 |
| `mom\|x0.05\|y5m\|tp0.1\|sl0.05\|t15m\|taker` (best gross) | 47,403 / 76 / 3,452 | -0.069605 | [-0.0723, -0.0670] / [-0.0721, -0.0672] | -0.006525 | 36.63 % | -65,990.10 | 31,365 / -0.06807 |
| `fade\|x0.1\|y2m\|tp0.03\|sl0.1\|tend\|maker` (worst) | 28,455 / 22 / 3,248 | -0.131593 | [-0.1346, -0.1286] / [-0.1346, -0.1287] | -0.082518 | 60.79 % | -74,889.35 | 18,695 / -0.12977 |
| `hold\|mom\|x0.1\|y5m` (reference) | 3,898 / 10 / 3,354 | -0.021494 | [-0.0557, +0.0125] / [-0.0555, +0.0119] | +0.010482 | 54.18 % | -1,675.69 | 3,127 / +0.02256 |

More readings for the best cell, all reproduced:

- the big-entry subset: n 12,480, mean -0.0652;
- 69.5 % of entries were on a print smaller than our contracts;
- the mean fee is 0.0611 per $. That is two legs of `0.0695 x p(1 - p) / p` at the mean entry of 0.5515, about
  0.031 each;
- the exit mix: tp 50.26 %, sl 49.51 %, settle 0.16 %, sl->settle 0.07 %.

### 1.3 Data conventions (where a silent sign or timing error would hide)

- **Taker side.** I took 400 random TRAIN recorded-end markets and every pair of adjacent prints within 30 s on
  opposite sides (140,001 pairs).
  - The print that is "buyable for outcome 0" sits ABOVE the one that is "sellable for outcome 0" by +1.03c on
    average (median +1.00c). It is above in 84.3 % of pairs and below in 11.7 %.
  - So the tape's `side` is the taker's side. Entries really pay the ask and exits really hit the bid.
  - An inverted side would make the simulator buy at the bid and sell at the ask. That would flatter the rule, not
    hide an edge.
- **Winners.** In the 394 of those markets whose last 20 prints are decided, lab 4's `winner_index` agrees with the
  tape every time (394 / 394). Payouts have the right sign.
- **Units.** Tape `ts` values are integer epoch seconds. `start`, `end` and `closed_time` are epoch seconds too.
  The 10 s latency is therefore 10 seconds.
- **The in-play window is really in play** (600 random recorded-end markets, 15-minute bins):

  | | -60..-45 min | -45..-30 | -30..-15 | -15..0 | 0..15 | 15..30 | 30..45 | 45..60 |
  |---|---|---|---|---|---|---|---|---|
  | prints / min around the start | 0.72 | 0.87 | 1.14 | 2.15 | 6.34 | 7.13 | 6.72 | 6.29 |
  | summed price moves (c) around the start | 2.8 | 3.7 | 5.0 | 11.3 | 65.4 | 79.2 | 78.7 | 73.2 |
  | prints / min around the recorded end | 6.70 | 9.17 | 9.64 | 10.51 | 1.31 | 0.27 | 0.05 | 0.02 |
  | summed price moves (c) around the recorded end | 85.9 | 120.4 | 136.7 | 165.5 | 0.6 | 0.4 | 0.1 | 0.0 |

  Trading jumps six-fold at `start`, and price movement stops at Gamma's `finishedTimestamp`. The last print before
  the recorded end is already decided (within 0.05 of 0 or 1) in 97.8 % of markets. The start and the end are the
  game's, not hours off.
- **Order within a second.** In 50 markets, 50.8 % of prints share their second with another print. Within the
  second they are ordered by transaction hash (100 % of 9,974 multi-print seconds), as the specialist disclosed.
  With a 10 s latency this cannot move a fill.

## 2. Twenty trades re-derived by hand from the raw rows

`twenty.py` re-reads each market's parquet. With plain pandas filters on `ts`, `side`, `outcome_index` and `price`,
it checks five things:

1. **The signal.** It finds the reference print (the last at or before t - y) and the signal print. The move of
   outcome 0 must be at least x, with at least 5 prints since. Momentum must have bought the riser and fade the
   faller. The signal print must sit in [start + y, end) with its price in 0.20-0.80.
2. **The entry.** It is the first ask-side print for the bought outcome in [t + 10 s, t + 600 s], before the end.
3. **The trigger.** It is the first print strictly after the entry second and strictly before the time stop: at or
   below entry - sl, or (taker) at or above entry + tp. For a maker cell, the fill is the first ask-side print
   strictly above the limit, once the cumulative ask-side size at or above the limit covers our contracts, before
   the stop print.
4. **The exit.** It is the first bid-side print at least 10 s after the trigger, before closedTime. Otherwise the
   trade settles at lab 4's winner.
5. **The fee and the P&L.** The fee is `contracts x 0.0695 x p x (1 - p)` on each taker leg (0 on a maker or
   settlement leg). The P&L is `contracts x exit - 20 - fee`.

The sample is 18 trades drawn at random per (cell, exit reason) to cover every exit type. One more is an
out-of-band entry, and the last is a taker exit filled after the recorded end. **All 20 pass every check, and the
P&L equals the engine's to 1e-9.**

| # | market | sport | cell | bought | ref -> signal | entry (print size, delay) | what happened (raw rows) | exit | fee $ | P&L $ (mine = core) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2758045 | cricket | `mom\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o1 | 0.550 -> 0.652 | 0.735 (size 290, +43s) | tp trigger print 0.810 (ask-side) @+8.2 min; exit bid-side print 0.800 | tp | 0.67 | 1.09 = 1.09 |
| 2 | 3506069 | tennis | `mom\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o0 | 0.340 -> 0.480 | 0.460 (size 13, +86s) | tp trigger print 0.510 (ask-side) @+3.2 min; exit bid-side print 0.580 | tp | 1.49 | 3.73 = 3.73 |
| 3 | 3017945 | tennis | `mom\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o0 | 0.155 -> 0.780 | 0.766 (size 7508, +12s) | sl trigger print 0.583 (bid-side) @+0.6 min; exit bid-side print 0.556 | sl | 0.77 | -6.26 = -6.26 |
| 4 | 3100485 | baseball | `mom\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o1 | 0.440 -> 0.540 | 0.570 (size 5, +21s) | sl trigger print 0.490 (bid-side) @+1.2 min; exit bid-side print 0.500 | sl | 1.21 | -3.66 = -3.66 |
| 5 | 2926161 | tennis | `fade\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o1 | 0.850 -> 0.750 | 0.788 (size 10, +64s) | tp trigger print 0.870 (ask-side) @+7.1 min; exit bid-side print 0.910 | tp | 0.44 | 2.67 = 2.67 |
| 6 | 3021287 | tennis | `fade\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o1 | 0.350 -> 0.240 | 0.230 (size 4, +150s) | sl trigger print 0.170 (bid-side) @+2.1 min; exit bid-side print 0.170 | sl | 1.92 | -7.14 = -7.14 |
| 7 | 2801890 | tennis | `mom\|x0.05\|y2m\|tp0.03\|sl0.1\|t15m\|maker` | o1 | 0.450 -> 0.500 | 0.500 (size 8, +30s) | maker sell at 0.530 filled by ask-side print 0.572 (cum size 61 >= 40) | tp | 0.69 | 0.51 = 0.51 |
| 8 | 3024842 | tennis | `mom\|x0.05\|y2m\|tp0.03\|sl0.1\|t15m\|maker` | o0 | 0.580 -> 0.630 | 0.600 (size 20, +18s) | maker sell at 0.630 not filled before the stop; sl trigger print 0.500 (bid-side) @+4.1 min; exit bid-side print 0.480 | sl | 1.13 | -5.13 = -5.13 |
| 9 | 3516901 | tennis | `mom\|x0.05\|y2m\|tp0.03\|sl0.1\|t15m\|maker` | o1 | 0.500 -> 0.670 | 0.670 (size 4, +13s) | no fill or trigger in 15 min; time-stop exit at bid-side print 0.670 | time | 0.92 | -0.92 = -0.92 |
| 10 | 2783445 | baseball | `fade\|x0.05\|y5m\|tp0.1\|sl0.05\|t45m\|maker` | o1 | 0.480 -> 0.410 | 0.420 (size 22, +24s) | maker sell at 0.520 filled by ask-side print 0.550 (cum size 91 >= 48) | tp | 0.81 | 3.96 = 3.96 |
| 11 | 3099298 | tennis | `fade\|x0.05\|y5m\|tp0.1\|sl0.05\|t45m\|maker` | o0 | 0.550 -> 0.212 | 0.010 (size 8, +12s) | no print at or below the stop (-0.04) and no fill before the game end; settles 0 | settle | 1.38 | -21.38 = -21.38 |
| 12 | 2720206 | baseball | `mom\|x0.1\|y2m\|tp0.1\|sl0.1\|t45m\|taker` | o0 | 0.670 -> 0.790 | 0.850 (size 9, +16s) | no trigger in 45 min; time-stop exit at bid-side print 0.890 | time | 0.37 | 0.57 = 0.57 |
| 13 | 2840893 | tennis | `mom\|x0.1\|y2m\|tp0.1\|sl0.1\|t45m\|taker` | o0 | 0.556 -> 0.746 | 0.750 (size 12, +15s) | tp trigger print 0.860 (ask-side) @+0.1 min; exit bid-side print 0.999 | tp | 0.35 | 6.29 = 6.29 |
| 14 | 2923086 | tennis | `fade\|x0.1\|y2m\|tp0.03\|sl0.05\|t15m\|taker` | o0 | 0.554 -> 0.378 | 0.137 (size 73, +14s) | tp trigger print 0.169 @+0.3 min; no bid-side print before close; settles 0 | tp->settle | 1.20 | -21.20 = -21.20 |
| 15 | 2898380 | soccer | `mom\|x0.05\|y5m\|tp0.05\|sl0.1\|tend\|maker` | o0 | 0.120 -> 0.579 | 0.972 (size 10, +12s) | no trigger or fill before the game end; settles 1 | settle | 0.04 | 0.54 = 0.54 |
| 16 | 2801890 | tennis | `fade\|x0.05\|y2m\|tp0.1\|sl0.1\|tend\|maker` | o1 | 0.350 -> 0.200 | 0.210 (size 8, +21s) | sl trigger print 0.100 @+0.3 min; no bid-side print before close; settles 0 | sl->settle | 1.10 | -21.10 = -21.10 |
| 17 | 2898380 | soccer | `hold\|mom\|x0.1\|y5m` | o1 | 0.450 -> 0.560 | 0.700 (size 1, +17s) | held to settlement: 0 | settle | 0.42 | -20.42 = -20.42 |
| 18 | 2860496 | soccer | `hold\|fade\|x0.05\|y2m` | o1 | 0.570 -> 0.520 | 0.530 (size 10, +72s) | held to settlement: 1 | settle | 0.65 | 17.08 = 17.08 |
| 19 | 3076353 | tennis | `mom\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o1 | 0.070 -> 0.200 | 0.170 (size 101, +26s) | out-of-band entry (0.170 < 0.20); sl trigger print 0.120 (bid-side) @+1.0 min; exit bid-side print 0.120 | sl | 2.02 | -7.90 = -7.90 |
| 20 | 3279659 | soccer | `fade\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` | o1 | 0.810 -> 0.540 | 0.925 (size 12, +15s) | tp trigger print 0.979 (ask-side) @+6.0 min; exit bid-side print 0.999, 34.0 min after the recorded end | tp | 0.11 | 1.49 = 1.49 |

"ref -> signal" is the bought outcome's price at the reference print and at the signal print. Momentum rows bought
the outcome that rose (for example #3, 0.155 -> 0.780) and fade rows bought the one that fell (for example #6,
0.350 -> 0.240), so the direction has the right sign.

What the sample shows about the execution model. All of it follows PLAN §4; none of it is a W3 bug:

- **In-play prices jump.** In #3 a tennis price went from 0.155 to 0.780 in five minutes. It was bought at 0.766
  and stopped out 36 s later at 0.556.
- **#11: a one-print, out-of-band fill.** After a fall from 0.550 to 0.212, the first ask-side print 12 s later was
  0.010, an 8-contract print. The whole $20 buys 2,000 contracts there, and the game is lost: -$21.38. The stop at
  -0.04 is not reachable from a 0.010 entry.
- **#14 and #16: a triggered exit that finds no bid.** The game was decided seconds after the trigger. The tape
  shows no bid-side print for the dead outcome before close, so the trade settles at 0. Even a "take profit" can do
  this (#14).
- **#13: a taker take profit that sells at 0.999.** The match ended between the trigger and the sale.

## 3. Could a bug have hidden an edge? The checklist

| suspicion | what I checked | finding |
|---|---|---|
| wrong sign (direction or P&L) | trips 1-20 (momentum bought the riser, fade the faller); P&L = contracts x exit - 20 - fee; the mirror (momentum and fade with the same exits both lose before fees, as two takers crossing the spread should); winners 394 / 394 | correct |
| fees charged twice | my fee equals the engine's on all 32,053 compared trips, and the five whole cells' totals agree to the cent; the best cell's mean fee 0.0611 per $ is two legs at about 0.031 each; maker and settlement legs pay 0; stress equals US on the taker cells because the sports rate (0.05) is below 0.0695; com = US x 0.05 / 0.0695 on the fee part (-0.0516 for the best cell) | charged once per leg, as the plan says |
| fills stricter than the plan | the engine matches my independent reading of PLAN §4 trip for trip: entry window [t + 10 s, t + 600 s] before the end; exits at the next bid-side print 10 s later before closedTime; the maker trade-through and size rule; 15 / 45 min stops becoming the end when they fall after it; settlement at the winner. Only 34 missed entries in the best cell | not stricter than the plan. §4.1 removes every execution friction at once, and §4.3 cuts the latency to 1 s |
| a filter that drops winners | every universe filter is outcome-blind: moneyline, a known start, end > start, sport not "other", >= 50 fills (8 markets dropped), binary with a winner. Recorded-end vs fallback-end depends on Gamma's `finishedTimestamp`, and the fallback-end games lose the same (-0.0697 for the best cell). The band applies to the signal print (PLAN); in-band entries -0.0687 vs all -0.0688; out-of-band entries are 6.8 % of trips | none |
| a broken join | universe row -> tape by id -> winner / payout -> event slug: my run reads each market by id and reproduces n, missed, games, mean, gross, win rate, total and the fallback reading of five cells exactly | none |
| the in-play window (W3-specific) | `start` and `end` against the tape (§1.3): activity jumps 6x at the start and stops at the recorded end | the window is the game |
| bootstrap / bar | my own event bootstrap reproduces the CI bounds within 0.0006. 0 of 288 cells have mean > 0, CI lower > 0 or stress > 0, and the highest CI upper bound is -0.0635, so no cell reaches the placebo; `core.select_one` returns None | NO_EDGE_TRAIN is the correct verdict |
| order of work and ledger | PREREG.md, `run.py` and `test_w3.py` went into git together in 827ae28 (2026-10-10 21:20:13 UTC); the PREREG sha followed in 0b21b2c (21:20:31). The TRAIN run log starts 22:35:30, and the only later change to `run.py` (6e230be) is the walk checkpoint, which I read: engineering only, no change to any rule or reading. `core.py`, PLAN.md and PREREG.md are unchanged since 827ae28. The final run walked all 8 entry rules afresh (no checkpoint load in the log). `trials.json`: 296 W3 TRAIN rows (288 selectable, 8 reference), 0 passes, PREREG sha `b86d459fb745`, PLAN sha `c6f62ddf29a0`. Lab 7's ledger now holds 610 rows, PLAN §5's TRAIN total; `trials_count()` = 3,661 | in order |

## 4. Is NO EDGE sound? Post-hoc readings (they decide nothing and add no trial)

### 4.1 Every cell with frictionless execution: still 0 of 288 positive

`ideal.py` re-walks all 288 selectable cells on every TRAIN recorded-end market with the rule's best possible
execution:

- the entry fills at the signal print's own price, at the signal instant: no 10 s delay, no spread, never missed;
- the take profit and the stop fill exactly AT their level when any later print touches it: no gap, no bid;
- the 15 / 45 min stop fills at the last print's price; the game-end stop holds to settlement.

| fees charged (frictionless execution) | cells with mean > 0 | best cell | n | gross | net per $ | CI95 |
|---|---|---|---|---|---|---|
| US fee on every leg (the plan's taker variant) | 0 / 144 | `mom\|x0.1\|y5m\|tp0.1\|sl0.05\|tend\|taker` | 48,007 | +0.0075 | **-0.0542** | [-0.0558, -0.0525] |
| US fee, take-profit leg free (the plan's maker variant) | 0 / 144 | `mom\|x0.05\|y2m\|tp0.1\|sl0.05\|tend\|maker` | 63,406 | +0.0097 | **-0.0431** | [-0.0447, -0.0416] |
| US fee on stop and time legs only (free entry AND free take profit; not in the plan) | 0 / 144 | the same path | 63,406 | +0.0097 | **-0.0104** | [-0.0119, -0.0089] |
| polymarket.com sports fee (0.05) instead of US, take profit free | 0 / 144 | the same path | 63,406 | +0.0097 | -0.0283 | - |
| no fee at all | 33 / 144 exit paths | `fade\|x0.1\|y2m\|tp0.1\|sl0.05\|t15m` | - | +0.0107 | +0.0107 | - |

How to read it:

- The losses come from the fee. At about 1.7c per contract per leg near 50c (PLAN §2), it is larger than anything
  the swing signal earns.
- The spread, the 10 s delay, the one-print fills and the trigger conventions only make the losses worse. No
  execution bug, however large, could hide an edge here.
- Before any fee, even perfect execution earns at most about +1c per $ (about 0.5c per contract), on 33 of the 144
  exit paths.
- Even a desk that paid nothing to enter or to take profit, and paid only on its stops, would lose. A resting buy
  order would also suffer adverse selection, which this bound ignores.

### 4.2 What the signal knows: a real drift, already paid away at the fill

`markout.py` takes the signals of each entry rule, inside the window and the band, thinned to one per market every
10 minutes. It follows the bought outcome's mid-price proxy: the mean of the last ask-side and last bid-side print,
both within 120 s.

The table is in cents per contract, with CI95 by game bootstrap:

- **drift from the signal** is the mid at t + h minus the mid at t;
- **fill premium** is the plan's entry fill minus the mid at the signal;
- **fill - signal print** is the fill minus the signal print's own price;
- **taker round trip at h** is the bid proxy at fill + h minus the fill: a taker time stop at h, before fees;
- **settle** is the payout minus the fill.

The round-trip fee is about 2.96c per contract for every rule.

| rule | signals | drift from the signal, 10 s / 1 min / 5 min / 15 min | fill premium | fill - signal print | taker round trip at 1 / 5 / 15 min | settle [CI95] |
|---|---|---|---|---|---|---|
| mom x0.05 y2m | 23,734 | +1.16 / +1.93 / +2.32 / +2.40 | +2.18 | +0.34 | -1.17 / -0.85 / -0.59 | +0.51 [-0.08, +1.06] |
| mom x0.05 y5m | 26,149 | +0.85 / +1.47 / +1.68 / +1.43 | +1.62 | +0.24 | -1.12 / -0.96 / -0.91 | -0.37 [-0.93, +0.20] |
| mom x0.1 y2m | 14,896 | +2.00 / +3.09 / +3.44 / +3.36 | +3.30 | +0.36 | -1.17 / -0.89 / -0.51 | +0.60 [-0.08, +1.29] |
| mom x0.1 y5m | 18,158 | +1.53 / +2.44 / +2.56 / +2.59 | +2.57 | +0.20 | -1.11 / -1.03 / -0.70 | +0.15 [-0.56, +0.78] |
| fade x0.05 y2m | 23,734 | mirror of momentum | -1.71 | +0.14 | -1.26 / -1.39 / -1.60 | -0.97 [-1.54, -0.41] |
| fade x0.05 y5m | 26,149 | mirror | -1.18 | +0.19 | -1.29 / -1.32 / -1.23 | -0.05 [-0.60, +0.52] |
| fade x0.1 y2m | 14,896 | mirror | -2.72 | +0.22 | -1.45 / -1.46 / -1.74 | -1.18 [-1.89, -0.51] |
| fade x0.1 y5m | 18,158 | mirror | -2.12 | +0.25 | -1.36 / -1.27 / -1.56 | -0.61 [-1.25, +0.07] |

The CIs of the drift and of the round trips all exclude zero; for example, mom x0.1 y2m at 5 min is +3.44
[+3.16, +3.73] and its round trip at 5 min is -0.89 [-1.10, -0.69].

How to read it:

- **Momentum is real in live games.** After a jump, the riser keeps rising by +1.4c to +3.4c within 15 minutes. That
  is why momentum beats fade before fees in all 144 mirror pairs (by 0.7c to 3.1c per $, median 1.45c), and why
  the best cell beats random entries by 0.5c per $ (the specialist's placebo).
- **Much of the drift comes in the first 10 s.** Part of it is the proxy's stale bid at a signal that is usually an
  ask print (68 % to 74 % of momentum signal prints). By the plan's earliest fill, the price has absorbed it: the
  fill costs only +0.2c to +0.4c more than the signal print itself.
- **From the fill, every rule loses before fees** at every horizon from 1 to 15 minutes: -0.5c to -1.7c per
  contract, roughly the bid-ask gap. The fees then add about 3c per contract.
- **A take profit or a stop only chooses when to leave this path.** Stopping cannot create the missing 4c.
- **Holding to settlement from the fill** is within about a cent of zero before fees for momentum, and zero to
  negative for fade. This matches the reference cells, all of which lose after the fee.

### 4.3 Speed does not rescue it

`fast.py` runs the plan's own execution with a **1 s** latency on every leg instead of 10 s:

| cell | gross at 1 s | gross at 10 s (plan) | net at 1 s |
|---|---|---|---|
| `mom\|x0.1\|y5m\|tp0.05\|sl0.05\|tend\|taker` (best) | -0.0082 | -0.0077 | -0.0692 |
| `mom\|x0.05\|y5m\|tp0.1\|sl0.05\|t15m\|taker` (best gross) | -0.0069 | -0.0065 | -0.0700 |
| `mom\|x0.05\|y2m\|tp0.1\|sl0.05\|tend\|maker` | -0.0279 | -0.0319 | -0.0807 |
| `fade\|x0.1\|y2m\|tp0.1\|sl0.05\|t15m\|maker` | -0.0509 | -0.0480 | -0.1134 |

A faster desk still buys at the ask and sells at the bid. Being 9 s quicker moves the gross by less than half a
cent per $, in either direction.

## 5. Points for the architect (none changes W3's verdict)

1. **The specialist's report is accurate.** I re-checked these figures:
   - 0 of 288 positive net (range -0.1316 to -0.0675) and 0 positive gross (best -0.0065);
   - the highest CI upper bound -0.0635;
   - taker cells average -0.081 net / -0.014 gross, maker cells -0.103 / -0.053;
   - the best cell's figures, risk book and placebo reading;
   - 296 ledger rows and 3,661 cross-lab trials.

   I found no bug in `core.py` or `W3/run.py`.
2. **The rule-of-three "worst case" of +0.106 is cosmetic here.** I agree with the specialist. Lab 4's formula
   `(1 - 3/n) x mean win - 3/n` suits near-certain bets with almost no losses. It only enters the bar when a cell
   has fewer than 5 losses, and every W3 cell has thousands. Reports could print it only in that case.
3. **The one-print, full-size fill convention** (raised by the W4 skeptic for this desk) does no harm in W3:
   - out-of-band entry fills are 6.8 % of the best cell's trips (for example #11: 0.010 off an 8-contract print);
   - 69.5 % of entries come from a print smaller than our order;
   - but they do not drive the means: in-band -0.0687 vs all -0.0688, big entries only -0.0652;
   - the largest single trip is +$111 (+$185 in the fade twin), with no fake right tail like W4's +$13,699.

   A future amendment that caps a fill at its print's size, or refuses fills outside the band, would make any
   future pass more believable. Made now, it would come after returns were read, so it should be labelled as such.
4. **In live games a triggered exit can find no bid** (#14, #16): the game is decided within seconds and the dead
   side never trades again. This is under 0.1 % of the best cell's trips (0.07 % sl->settle). It is realistic, and
   it costs the full $20 when it happens.
5. **The grid tests only taker entries on price action.** The owner's "get in at 50" could also mean a resting buy
   order. That is not in PLAN §5, and testing it would need its own pre-registration and new trials. §4.1 already
   bounds it: with a free entry, a free take profit and perfect fills, the best path still loses 1.0c per $. That
   is before the adverse selection a resting buy suffers.
6. **The specialist's hindsight notes favour the strategy:** Gamma's `finishedTimestamp` as the entry deadline and
   the game-end stop, and the scheduled start. §1.3 shows both times sit on the real game. A live desk would know
   the end later, which can only make the result worse.

## 6. Files

- This review: `research/lab7/W3/SKEPTIC.md`, the only file I added to the repo.
- Scratch (outside git), `w3skeptic/` in the session scratchpad:
  - simulators and comparisons: `indep.py`, `compare.py`, `compared_3.parquet`, `compared_11.parquet` (32,053
    compared trips), `full_best.py`, `cmp_full.py`, `full_a.parquet` (five whole cells);
  - the hand check: `twenty.py`, `twenty.json`;
  - the readings: `conv.py`, `timing.py`, `ideal.py`, `ideal_fw.csv`, `markout.py`, `markout.parquet`, `fast.py`;
  - the universe snapshot: `u_train.pkl`.

# Lab 7 W1: adversarial skeptic's review of the TRAIN result

Written 2026-10-11 ~00:20 UTC by the W1 skeptic. It reviews `W1/train.json` (run 2026-10-10 20:56 UTC, PREREG sha256
`d421479b...`, PLAN sha256 `c6f62ddf...`). It changes no specialist file, adds no trial to `trials.json`, and never
reads VAL or TEST returns.

**Verdict: the NO EDGE result stands.** No W1 cell passed, so there is no pass to refute. I tried to break the
NO EDGE result instead, looking for any bug that could make a real edge look like a loss. I rebuilt every trade of
the best cell from the raw files with my own code. It matches the specialist's numbers. I found one real bug,
inherited from lab 6: one market had its sides mapped to the wrong team. It changes no result (the details are
below).

## In plain words (for the owner)

I checked the sports desk's homework by redoing it from scratch. I wrote my own program, which does not use the
specialist's, and took the raw trade records and the raw bookmaker prices. Then I replayed the best rule, trade by
trade. I got the same 158 trades out of 160, with the same prices, fees and losses. The other two trades came from
one game where the old lab 6 code mixed up two teams (LA Galaxy and Los Angeles FC). Fixing that changes almost
nothing: the rule still loses about 9 cents per dollar. Even with no fees at all it still loses about 1.7 cents per
dollar. It also did worse than buying at random moments. The verdict holds: this desk should not trade the idea.

## What I re-derived, independently

My scripts sit outside git, in the session scratchpad (`w1skeptic/indep.py`, `sample.py`, `placebo_indep.py`,
`patched.py`). `indep.py` imports neither `research/lab7/core.py` nor lab 6's `core.py`. It reads only these files:

- lab 4's `trades/<id>.parquet` and `markets.parquet`;
- lab 6's `pinnacle.parquet`, `matches.parquet` and `gamma_meta.parquet`.

It recomputes all of the following by itself:

- the tape sides;
- the multiplicative no-vig fair from the raw decimal odds;
- the outcome-to-Pinnacle mapping;
- the snapshot alignment;
- the cutoff and the merged entry windows;
- the signal, the entry, the take profit, the stop and the time-stop exit;
- the fees.

The only thing it takes from the specialist is the list of 3,005 TRAIN market ids, which is lab 6's matched
universe by design.

Results:

| quantity | specialist | skeptic (independent) |
|---|---|---|
| prints read | 4,690,410 | 4,690,410 |
| round trips, best cell `m0.05\|tp0.02\|sl0.03\|tcutoff\|taker` | 160 | 158 (the 2 missing: see the bug below) |
| missed entries | 14 | 14 |
| the 158 common trips: signal time and price, fair at the signal, entry time and price, exit time and price, reason, fee, net | | identical (max abs difference 0.0) |
| markets whose snapshots, fair per snapshot, commence, cutoff and payout agree | | 3,004 of 3,005 |
| mean net per $ (US fee) | -0.0893 | -0.0892 |
| CI95 by game bootstrap | [-0.0998, -0.0783] (lab 4's, B = 2000) | [-0.1001, -0.0778] (my own cluster bootstrap, B = 4000) |
| gross (no fee) mean, CI95 | -0.0172, [-0.0262, -0.0074] | -0.0170, [-0.0263, -0.0073] |
| random-entry placebo: mean, p95, real percentile | -0.0738, -0.0563, 3.5 | -0.0732, -0.0563, 6.0 (my own simulator and seeds, 100 draws) |

My placebo simulator reproduces my 158 real trips exactly when it is started at their own signal times (max
|diff| 0).

## Raw-row audit of 40 random trips (best cell)

Each row was checked against the raw parquet rows:

- the signal print and the entry print are BUYABLE for the bought outcome `o`: a taker BUY on `o`'s token, or a
  taker SELL on the other token at `1 - p`;
- every taker exit is a SELLABLE print: a taker BUY on the other token, or a taker SELL on `o`'s token;
- the fee is recomputed by hand as `0.0695 x shares x p(1-p)` per taker leg, and equals the engine's on all 40
  rows.

How to read the table:

- `+Ns` on the entry = seconds after the signal print. On a tp, sl or fair exit, `+Ns after trigger` is the delay
  from the trigger. On a `time` exit it is the offset from the cutoff: negative means sold that long before the
  start.
- `min before cutoff` is negative when the sale came after the start. That happens on late stops, and on stops
  triggered just before the start that filled after it.

| market | o | snapshot age (min) | fair | signal print (UTC, side/token@price) | entry print | exit | min before cutoff | fee $ (hand = engine) | net per $ |
|---|---|---|---|---|---|---|---|---|---|
| 2731681 | 1 | 7.6 | 0.728 | 07-01 10:08:11 BUY/tok1@0.630 | +11s BUY/tok1@0.710 (o=0.710) | time -17s after trigger BUY/tok0@0.280 (o=0.720) | 0.3 | 0.7978 | -0.0258 |
| 2744265 | 0 | 11.8 | 0.552 | 07-02 17:17:25 BUY/tok0@0.430 | +21s BUY/tok0@0.420 (o=0.420) | tp +70s after trigger BUY/tok1@0.520 (o=0.480) | 10.2 | 1.6323 | +0.0612 |
| 2791137 | 1 | 11.2 | 0.413 | 07-05 13:31:47 BUY/tok1@0.360 | +14s BUY/tok1@0.370 (o=0.370) | tp +540s after trigger BUY/tok0@0.640 (o=0.360) | 74.8 | 1.7413 | -0.1141 |
| 2791096 | 1 | 9.4 | 0.450 | 07-05 14:05:01 BUY/tok1@0.390 | +225s BUY/tok1@0.410 (o=0.410) | tp +239s after trigger BUY/tok0@0.580 (o=0.420) | 16.7 | 1.6460 | -0.0579 |
| 2840954 | 1 | 2.7 | 0.495 | 07-12 01:23:16 BUY/tok1@0.440 | +525s BUY/tok1@0.440 (o=0.440) | time -175s after trigger BUY/tok0@0.580 (o=0.420) | 2.9 | 1.5480 | -0.1229 |
| 2840996 | 0 | 9.8 | 0.688 | 07-14 22:50:28 BUY/tok0@0.600 | +15s BUY/tok0@0.600 (o=0.600) | time -236s after trigger BUY/tok1@0.410 (o=0.590) | 3.9 | 1.1154 | -0.0732 |
| 2854198 | 1 | 0.5 | 0.552 | 07-15 01:51:05 BUY/tok1@0.500 | +12s BUY/tok1@0.530 (o=0.530) | tp +14s after trigger BUY/tok0@0.475 (o=0.525) | 5.5 | 1.3074 | -0.0753 |
| 2901936 | 0 | 12.6 | 0.556 | 07-15 15:08:10 BUY/tok0@0.500 | +12s BUY/tok0@0.490 (o=0.490) | tp +1053s after trigger BUY/tok1@0.473 (o=0.527) | -1.1 | 1.4160 | +0.0044 |
| 2866816 | 0 | 5.8 | 0.595 | 07-16 19:31:22 BUY/tok0@0.530 | +51s BUY/tok0@0.530 (o=0.530) | sl +21s after trigger BUY/tok1@0.500 (o=0.500) | 22.9 | 1.3090 | -0.1221 |
| 2798260 | 1 | 13.4 | 0.442 | 07-18 18:19:03 BUY/tok1@0.390 | +117s BUY/tok1@0.390 (o=0.390) | time -29s after trigger BUY/tok0@0.600 (o=0.400) | 0.5 | 1.7033 | -0.0595 |
| 3021017 | 0 | 11.0 | 0.542 | 07-22 17:06:39 BUY/tok0@0.450 | +43s BUY/tok0@0.450 (o=0.450) | tp +23s after trigger BUY/tok1@0.550 (o=0.450) | 6.9 | 1.5290 | -0.0764 |
| 3109551 | 1 | 3.2 | 0.585 | 07-27 18:43:51 BUY/tok1@0.510 | +10s BUY/tok1@0.510 (o=0.510) | time -75785s after trigger BUY/tok0@0.500 (o=0.500) | 1263.1 | 1.3625 | -0.0877 |
| 3120829 | 1 | 9.0 | 0.774 | 07-28 21:09:34 BUY/tok1@0.720 | +18s BUY/tok1@0.660 (o=0.660) | time +38s after trigger BUY/tok0@0.340 (o=0.660) | -0.6 | 0.9452 | -0.0473 |
| 2962855 | 0 | 0.2 | 0.491 | 07-30 21:35:48 BUY/tok0@0.430 | +38s BUY/tok0@0.430 (o=0.430) | time -21s after trigger BUY/tok1@0.590 (o=0.410) | 0.4 | 1.5743 | -0.1252 |
| 2962858 | 1 | 6.5 | 0.791 | 07-30 21:42:09 BUY/tok1@0.740 | +54s BUY/tok1@0.740 (o=0.740) | time -231s after trigger BUY/tok0@0.270 (o=0.730) | 3.8 | 0.7316 | -0.0501 |
| 2989167 | 1 | 11.9 | 0.507 | 08-01 22:47:32 BUY/tok1@0.450 | +10s BUY/tok1@0.450 (o=0.450) | tp +88s after trigger BUY/tok0@0.540 (o=0.460) | 38.0 | 1.5318 | -0.0544 |
| 3241029 | 0 | 9.1 | 0.465 | 08-02 13:04:44 BUY/tok0@0.350 | +292s BUY/tok0@0.350 (o=0.350) | tp +254s after trigger BUY/tok1@0.640 (o=0.360) | -1.4 | 1.8185 | -0.0624 |
| 3253946 | 0 | 13.5 | 0.414 | 08-03 13:19:08 BUY/tok0@0.360 | +345s BUY/tok0@0.350 (o=0.350) | tp +122s after trigger BUY/tok1@0.630 (o=0.370) | -1.8 | 1.8292 | -0.0343 |
| 3320618 | 1 | 9.2 | 0.675 | 08-04 19:39:53 BUY/tok1@0.510 | +10s BUY/tok1@0.510 (o=0.510) | time -12553s after trigger SELL/tok1@0.500 (o=0.500) | 209.2 | 1.3625 | -0.0877 |
| 3030625 | 0 | 10.5 | 0.430 | 08-04 23:01:09 BUY/tok0@0.360 | +26s BUY/tok0@0.360 (o=0.360) | sl +1042s after trigger BUY/tok1@0.680 (o=0.320) | 1.6 | 1.7298 | -0.1976 |
| 3030622 | 0 | 4.6 | 0.481 | 08-04 23:30:17 BUY/tok0@0.420 | +13s BUY/tok0@0.420 (o=0.420) | time -474s after trigger BUY/tok1@0.600 (o=0.400) | 7.9 | 1.6005 | -0.1276 |
| 3325249 | 1 | 0.4 | 0.771 | 08-05 20:51:02 BUY/tok1@0.510 | +12s BUY/tok1@0.510 (o=0.510) | time -5013s after trigger SELL/tok1@0.500 (o=0.500) | 83.6 | 1.3625 | -0.0877 |
| 3325107 | 1 | 7.9 | 0.589 | 08-05 22:08:30 BUY/tok1@0.510 | +15s BUY/tok1@0.519 (o=0.519) | sl +14s after trigger BUY/tok0@0.530 (o=0.470) | 0.6 | 1.3362 | -0.1609 |
| 3059591 | 0 | 4.4 | 0.498 | 08-05 23:39:59 BUY/tok0@0.420 | +13s BUY/tok0@0.420 (o=0.420) | time -6s after trigger BUY/tok1@0.580 (o=0.420) | 0.1 | 1.6124 | -0.0806 |
| 3362096 | 0 | 8.1 | 0.420 | 08-07 13:33:46 BUY/tok0@0.369 | +282s BUY/tok0@0.370 (o=0.370) | time -90s after trigger BUY/tok1@0.650 (o=0.350) | 1.5 | 1.7304 | -0.1406 |
| 3374334 | 0 | 13.7 | 0.338 | 08-08 09:19:18 BUY/tok0@0.280 | +103s BUY/tok0@0.280 (o=0.280) | time -27s after trigger BUY/tok1@0.730 (o=0.270) | 0.4 | 1.9793 | -0.1347 |
| 3114703 | 0 | 7.0 | 0.490 | 08-08 23:32:39 BUY/tok0@0.430 | +48s BUY/tok0@0.430 (o=0.430) | time -26s after trigger BUY/tok1@0.590 (o=0.410) | 0.4 | 1.5743 | -0.1252 |
| 3304037 | 1 | 0.4 | 0.581 | 08-09 04:56:00 BUY/tok1@0.530 | +57s BUY/tok1@0.520 (o=0.520) | tp +183s after trigger BUY/tok0@0.470 (o=0.530) | 717.0 | 1.3331 | -0.0474 |
| 3304037 | 1 | 8.6 | 0.581 | 08-09 05:04:16 BUY/tok1@0.530 | +11s BUY/tok1@0.530 (o=0.530) | sl +15301s after trigger BUY/tok0@0.500 (o=0.500) | 268.3 | 1.3090 | -0.1221 |
| 3401505 | 1 | 19.0 | 0.409 | 08-09 09:24:39 SELL/tok0@0.650 | +10s BUY/tok1@0.350 (o=0.350) | sl +445s after trigger BUY/tok0@0.680 (o=0.320) | -1.8 | 1.7677 | -0.1741 |
| 3128346 | 1 | 16.6 | 0.681 | 08-10 01:37:10 BUY/tok1@0.630 | +23s BUY/tok1@0.630 (o=0.630) | fair +206s after trigger BUY/tok0@0.370 (o=0.630) | 2.1 | 1.0286 | -0.0514 |
| 3325758 | 1 | 5.9 | 0.437 | 08-10 16:11:34 BUY/tok1@0.380 | +15s BUY/tok1@0.390 (o=0.390) | time -5s after trigger BUY/tok0@0.620 (o=0.380) | 0.1 | 1.6876 | -0.1100 |
| 3320659 | 0 | 11.1 | 0.343 | 08-11 18:06:45 BUY/tok0@0.280 | +10s BUY/tok0@0.290 (o=0.290) | tp +1825s after trigger BUY/tok1@0.690 (o=0.310) | 262.4 | 2.0121 | -0.0316 |
| 3143036 | 1 | 15.2 | 0.634 | 08-12 22:50:51 BUY/tok1@0.520 | +13s BUY/tok1@0.510 (o=0.510) | tp +10s after trigger BUY/tok0@0.484 (o=0.516) | 65.3 | 1.3618 | -0.0563 |
| 3143050 | 1 | 14.0 | 0.536 | 08-13 00:59:40 BUY/tok1@0.480 | +45s BUY/tok1@0.460 (o=0.460) | sl +120s after trigger BUY/tok0@0.571 (o=0.429) | 84.9 | 1.4909 | -0.1416 |
| 3143050 | 1 | 19.5 | 0.536 | 08-13 01:05:07 BUY/tok1@0.410 | +12s BUY/tok1@0.410 (o=0.410) | sl +15s after trigger BUY/tok0@0.620 (o=0.380) | 82.5 | 1.6188 | -0.1541 |
| 3143050 | 1 | 1.9 | 0.508 | 08-13 01:07:31 BUY/tok1@0.390 | +11s BUY/tok1@0.390 (o=0.390) | tp +67s after trigger BUY/tok0@0.590 (o=0.410) | 78.9 | 1.7101 | -0.0342 |
| 3143051 | 0 | 19.2 | 0.658 | 08-13 22:24:51 BUY/tok0@0.550 | +331s BUY/tok0@0.550 (o=0.550) | sl +15s after trigger BUY/tok1@0.480 (o=0.520) | 19.0 | 1.2563 | -0.1174 |
| 3533631 | 0 | 8.9 | 0.491 | 08-14 17:19:33 BUY/tok0@0.440 | +19s BUY/tok0@0.430 (o=0.430) | time +39s after trigger BUY/tok1@0.600 (o=0.400) | -0.6 | 1.5681 | -0.1482 |
| 3314307 | 1 | 11.0 | 0.486 | 08-14 22:46:36 BUY/tok1@0.430 | +18s BUY/tok1@0.430 (o=0.430) | sl +357s after trigger BUY/tok0@0.600 (o=0.400) | 27.7 | 1.5681 | -0.1482 |

## Checks against the failure list

**Lookahead.** None found that could hide an edge.

- **Fair.** It comes from the last snapshot at or before the print, strictly before commence and at most 30 min old,
  and it is NaN at or after the cutoff. I re-derived it from the raw odds, and it matches on 3,004 of 3,005 markets
  (the exception is the bug below).
- **Snapshot timestamps.** In `pinnacle.parquet`, `last_update <= snap_ts <= requested` holds on all 216,507 rows,
  so no snapshot carries odds from after its own timestamp.
- **Entries.** All entries came 10 to 525 s after the signal, before the cutoff and before closedTime.
- **closedTime and the winner.** They are never in the signal: closedTime is only a fill bound, and the payout is
  used only at settlement. No best-cell trip settled.
- **Two small pieces of hindsight.** Both are in the rule's favour or neutral, so they cannot manufacture a loss.
  They would matter only for a pass.
  1. `commence` is the LAST pre-game snapshot's commence time, and `game_start` is Gamma's value as fetched later.
     In 1,527 of 7,224 Pinnacle events the commence time changed between snapshots (median change 135 min). A live
     desk would see the start time scheduled at that moment.
  2. The `last_before` time stop knows WHEN the last bid of the day came. In one sampled trip (market 3109551) the
     "time" sale was 21 h before the cutoff, because no later bid-side print existed.

**Impossible fills.** None found.

- All 158 entries are on buyable prints and every taker exit is on a sellable print, checked on the raw rows.
- Maker variant `m0.05|tp0.05|slnone|tcutoff|maker`: I checked all 16 maker fills independently.
  - Each one is a buyable print STRICTLY above the limit.
  - The buyable size at or above the limit since posting covers our shares.
  - The first such print is exactly the reported fill.
  - The limit sits at entry + 0.05, or at the fair when the fair was lower.
- The tape lists one row per transaction: 45,637 rows in 40 markets, and no transaction appears twice. So maker
  and taker legs are not double-listed.
- One known limit: 60 % of best-cell entries filled at a print smaller than our contracts. That favours the
  strategy, and the trips whose entry print covered the $20 lose the same (-0.088).

**Event clustering in the CI.**

- The event is the game, and a soccer game's three markets share it.
- My own game-cluster bootstrap reproduces the interval.
- Concentration does not drive the loss:
  - without the 3 busiest markets: -0.095 (gross -0.021);
  - only the first trip in each market: -0.092 (gross -0.020).
- Fresh Pinnacle snapshots lose the same as stale ones (age at the signal):

  | snapshot age | n | net | gross |
  |---|---|---|---|
  | 0-5 min | 33 | -0.087 | -0.018 |
  | 5-15 min | 103 | -0.088 | -0.015 |
  | 15-30 min | 22 | -0.097 | -0.025 |

  A stale line is therefore not the reason it loses.

**Placebo.** It is done as PLAN §7 says:

- the time is drawn uniformly over the merged entry windows;
- the side is drawn 50 / 50, not copied from the real trade;
- the band is checked on the last print;
- there are up to 25 redraws, and the same exits.

My independent re-implementation gives the same distribution (see the table above). The real entries are worse
than random in all 54 cells; the median real percentile is 0.

**Multiple testing.**

- W1 has 57 rows in `research/lab7/trials.json`: 54 selectable and 3 reference, all on TRAIN, all with
  `passes: false`. All carry the PREREG sha `d421479b92ae` and the PLAN sha `c6f62ddf29a0`.
- The cross-lab count was 3,108 at run time, and it is 3,365 now that W2 and W4 have been recorded.
- No cell passes, so there is no lucky winner to deflate. For the record, at that many trials a single pass would
  have been weak evidence on its own.

**Pre-registration integrity.**

- `PREREG.md` was committed at 20:34:45 UTC (5eba53c). The only later change is the "Written ~20:40" -> "~20:34"
  line (git diff 5eba53c..827ae28).
- `core.py`, `PLAN.md` and `tests/test_core.py` are unchanged since the lab 7 pre-registration commit (df4942d).
- `run.py` changed after the PREREG commit only in markdown rendering: the `--render` flag, pipe escaping and the
  league sort.
- `train.json` was written at 20:56:46. `python -m pytest tests/test_w1.py`: 8 passed.

**The specialist's numeric claims, checked against `train.json`:**

- 54 / 54 cells have a negative mean;
- the best mean is -0.0888;
- the best CI95 upper bound is -0.0722;
- the best gross mean is -0.0172;
- every gross CI95 upper bound is below 0. One sits barely below: `m0.05|tp0.05|sl0.05|tcutoff|taker` at
  -0.0013. "Loses before fees" is true, but for that cell it is "about zero before fees";
- the placebo p95 is above the real mean in 54 / 54 cells.

## The bug found (inherited from lab 6; immaterial here)

`research/lab6/core.py build_games` maps a soccer "Will X win" market to Polymarket's home or away team with
`name_sim(team, home) >= name_sim(team, away)`. Its `FILLER` list drops the word `fc`. That makes
"Los Angeles FC" -> {los, angeles}, which is contained in "Los Angeles Galaxy", so both names score 1.0. On the
tie, the code picks home.

- **The TRAIN case.** Market 2795894, "Will Los Angeles FC win on 2026-07-17?", got LA Galaxy's fair. The last
  snapshot's raw odds were Galaxy 3.16, LAFC 2.10, Draw 3.59. That gives a no-vig LAFC fair of 0.445, but W1 used
  0.295, which is the Galaxy's. Both of the best cell's 2 extra trips (buying No at 0.57 and 0.54 against a wrong
  "fair" of 0.70) come from this.
- **Effect.** I re-walked all 57 cells with that one market corrected, in scratch, with no ledger write:
  - the means of the selectable cells move by at most 0.0002;
  - the reference `hold|m0.05` moves from -0.079 to -0.071;
  - no cell clears conditions 1-5;
  - the best CI95 upper bound is still -0.0720.
- **Scope.** I scanned every soccer win market in lab 6's universe, on all splits, whose team name equals one of
  the title's teams verbatim: 3,714 markets. Two disagree:
  - this one (TRAIN);
  - market 3441302, "Will Dundee FC win", mapped to Dundee United (VAL; W1 never read VAL).
- **The fix**, if anyone runs W1-like work on VAL or TEST: map by an exact match of the team name against the
  event title's two teams before falling back on `name_sim`. The same market also sits in lab 6's own results.

## Caveats (not bugs; they do not change the verdict)

- **The stop and take-profit triggers look at ANY print.** By the plan's rule, an entry at the ask meets a bid-side
  print 3c lower whenever the spread is 3c or wider, and that triggers the stop.
- **This is not a no-skill trade that merely loses to fees.** The rule loses before fees too, and its entries do
  worse than random ones with the same exits. The cause is adverse selection: a Polymarket price below Pinnacle
  usually stays below it until the start. The specialist's post-hoc diagnostic puts the last ask before the start at
  2.5c below Pinnacle's close on average, in its tp0.05 no-stop cell (I did not re-derive that figure). One example is market 3325249, a tennis match
  whose market resolved 50/50 before its scheduled start (so most likely a withdrawal or walkover). The rule bought
  there 5 times against a stale 0.77 Pinnacle line.
- **Untested execution.** Maker entries and a real-time Pinnacle feed were not tested. The snapshot-age split
  above suggests a fresher feed would not rescue the rule.

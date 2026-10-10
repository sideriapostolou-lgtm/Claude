# Lab 7 W4 pre-registration: non-sports swings over hours (momentum and fade)

Written 2026-10-10 ~21:40 UTC by the W4 specialist, under `research/lab7/PLAN.md` (lab7-v1, sha256 `c6f62ddf...`).
**At the time of writing no W4 return had been computed or read.**

## 0. What has been run on real data

- **Structure counts of the universe** (`run.py --structure train|val`, and parquet row counts read from the files'
  metadata, without reading any price):
  - TRAIN: 3,122 markets in 1,253 events (weather 1,548, culture 662, politics 317, finance 305, tech 161, economics
    93, mentions 36); VAL: 1,457. These match PLAN §3.
  - TRAIN outcomes: Yes/No 3,002, Up/Down 117, two names 3. polymarket.com fee rate 0.05 for 2,303 markets and 0.04
    for 819.
  - TRAIN closedTime minus endDate: 586 markets closed more than one hour before their endDate ("closed early"); the
    median market closed 4.4 h after its endDate.
  - Tape sizes (raw rows): 161 TRAIN markets have fewer than 50; the rest have a median of 589 and a maximum of 31,119.
- **The W4 tests** (`research/lab7/tests/test_w4.py`), on hand-made and random synthetic tapes, plus a structure check
  of the universe on the real markets file.
- **A timing smoke test** on 40 random TRAIN markets (seed 7). It printed only the run time (3.6 s for all 200
  cells with 2 workers), the number of round trips (49,356 in all; 20 / 241 / 475 per cell at the min / median /
  max), and the time of one placebo block (0.208 ms per counterpart). No profit, loss, price, win rate or exit
  figure was printed or read.
- **Disclosures.** The W4 specialist saw the one-line headlines of W1's and W2's TRAIN results (NO EDGE) in the git
  log, and, while checking the ledger's format, one W1 ledger row (one W1 cell's mean) was printed. W4's grid, band,
  bar and execution are fixed by the plan, so nothing below depends on them.

This file adds only what the plan leaves open. It changes no grid value, fee, band, bar, split or execution rule.

## 1. Universe (PLAN §5 W4)

- **Markets:** lab 4's eligible markets of the split (`lab4 core.Dataset.eligible`: two outcomes, `winner_index` 0
  or 1, closedTime in the split), whose lab 4 `fee_family(feeType, feesEnabled)` is one of politics, culture,
  economics, weather, mentions, tech, finance. Families `none`, `zero`, `geopolitics` and `unknown` are not in W4.
- **Fills:** at least 50 prints, counted by `core.load_tape(id, min_fills=50)` after core's validity filter. A market
  with fewer is skipped and counted.
- **Market end:** `min(endDate, closedTime)`; closedTime when endDate is missing (NaN or not positive).
- **Settlement:** `payout = (1, 0)` if `winner_index == 0`, else `(0, 1)`. `settle_t = hard_end =` closedTime.
- **Fee rate (`rate_com`):** lab 4's `fee_rate(feeType, feesEnabled)`.
- **Event (bootstrap group):** the event slug (a weather event's brackets, a winner field's names, one politician's
  date ladder are one draw). A market without a slug is its own event (none on TRAIN).
- **Close kind (a reading only):** "closed early" when closedTime is more than one hour before endDate (the market
  resolved before its scheduled end, usually on news); "scheduled end" otherwise.
- **Order:** markets ordered by closedTime, then id. Trips are ordered by entry time, then id, before any reading.

## 2. Times and the market (PLAN §5 W4)

- **First print:** the first print of the market's tape after core's validity filter. The cache holds at most the
  last 14 days before closedTime, so for a longer-lived market this is the start of the cache, not the listing.
- **Entry window:** one interval `[first print + y, market end)` per lookback y. A market whose end is not after
  `first print + y` has no window for that y (counted as coverage).
- **Market fields:** `entry_deadline = end_t =` the market end, `end_mode = "settle"`, `hard_end = settle_t =`
  closedTime, `band = (0.15, 0.85)`, no fair, `rate_com` as above.
- **Time stops:**
  - "24h" is `Exits.hold_s = 86400`. A 24 h stop that would fall at or after the market end becomes the end (core:
    `t_entry + hold_s < end_t`, otherwise the end in mode `settle`), and the position is held to settlement;
  - "end" is `hold_s = None`: watched until the market end, then held to settlement.
- **Exits (core):** a triggered take profit or stop sells at the first sellable print at or after the trigger + 10 s,
  before closedTime. That sale may come after the market end (between endDate and closedTime). It is a real print
  and it is reported as a reading (§6).

## 3. Signals

- **Signal:** `core.swing_signals(tape, x, 60 * y_min, k=10, direction)`, computed once per (direction, x, y) per
  market and shared by that entry rule's 24 exit cells and its reference.
- **Price used:** outcome 0's price at every print (either side).
- **Reference print:** the last print at or before `t - y`. Because `t >= first print + y`, it always exists. Core's
  convention is kept unchanged.
- **Walk:** `core.walk` applies the window and the band (the bought outcome's price at the signal print).
- **Directions:** MOMENTUM buys outcome 0 after a rise of at least x, and outcome 1 after a fall. FADE does the
  opposite.

## 4. Cells (PLAN §5 W4)

- **Entry rule key:** `<mom|fade>|x<x>|y<y>m`, with x in {0.05, 0.1} and y in {60, 240}, printed with `%g`.
- **Selectable cells:** `<entry>|tp<tp>|sl<sl>|t<24h|end>|<taker|maker>`, with tp in {0.03, 0.05, 0.1} and sl in
  {0.05, 0.1}, as `Exits(tp, sl, tp_mode, hold_s)` with `fair_exit = False`. That gives
  2 x 2 x 2 x 3 x 2 x 2 x 2 = **192 cells**.
- **References:** `hold|<entry>`, `Exits(hold_to_settlement=True)`: the first filled entry per market, held to
  settlement. That gives **8 cells**, reported only.
- **Trials:** all 200 are trials on TRAIN.

## 5. Decision inputs

- **Deciding set:** every round trip of the cell in the universe (W4 has no read-apart subset).
- **Bar:** `core.bar` (PLAN §7) on `core.summarize` of those trips, with the cell's placebo.
- **TRAIN selection:** `core.select_one` among the 192 selectable cells. No pass gives **NO_EDGE_TRAIN**, and VAL and
  TEST are not run.

## 6. Readings (every cell; readings only, never a selector)

- `core.summarize` and its `risk_book`: n, events, missed entries, trips per day, win rate, mean net per $ under the
  US / com / stress fees, the event-bootstrap CI95 (B = 2000, seed 0), the rule-of-three worst case, the exit mix,
  late stops, median hold, cents per contract won and lost, the break-even win rate, the mean entry price and the
  small-entry share; max open positions and capital, the $10 daily loss stop overlay, max drawdown, worst / best
  day, daily Sharpe, longest losing streak and worst trip.
- **Gross mean** (net + US fee, per $) with its event-bootstrap CI95.
- **Entry slippage** (entry fill price minus the signal print's price, for the bought outcome) and the median entry
  delay.
- **Big-entry subset:** the trips whose entry print alone covered our contracts (n, mean, CI95).
- **Scheduled-end subset:** the trips in markets that did not close early (n, mean, CI95).
- **Far-from-the-end subset:** the trips entered at least 24 h before the market end (n, mean, CI95).
- **Exits after the end:** trips whose exit fill (not a settlement) came at or after the market end (n, share, mean).
- **Concentration:** the share of the absolute P&L carried by the ten events with the largest absolute P&L, and
  those ten events.
- **Breakdowns:** by family; by the side bought (A = Yes / Up / first-listed name, B = No / Down / second-listed) and
  by the six labels; by close kind; by the time from entry to the market end (<1 h, 1-24 h, 1-3 d, >= 3 d); by entry
  price (0.15-0.30, 0.30-0.50, 0.50-0.70, 0.70 and up).
- **Mirror table (TRAIN):** for every momentum cell, the gross and net means of its fade twin (same x, y and exits).
  On the same moves momentum and fade hold opposite sides, so with no skill one's gross gain should be roughly the
  other's gross loss. A large positive gross on BOTH would point to a simulator artifact.
- **The reference cells:** would holding the same first entry to settlement have done better than trading out?

## 7. The placebo (PLAN §7)

- **Method:** `core.placebo_matrix` with 200 draws, on the markets where the cell traded, with as many counterparts
  per draw as the market has real round trips in the cell.
- **Market:** the counterparts use the cell's own market, with the entry window `[first print + y, market end)` for
  the cell's y.
- **Seeds:** for each market,
  `numpy.random.default_rng([core.placebo_seed("W4", cell, split), crc32(market id)])`, so the result does not depend
  on worker order.
- **Decides:** every selectable cell that clears conditions 1-5 gets the placebo, with no budget limit. Only those
  cells can pass.
- **Readings on TRAIN:** the six selectable cells with the highest CI95 lower bound (ties: higher mean, then key),
  taken in rank order. A cell is skipped (and listed) when its counterparts (200 x n) would take the reading-only
  total above 40,000,000.
- **On VAL / TEST:** the cell under test always gets its own placebo.
- **References:** no placebo.
- **The bar:** `core.bar` receives any computed placebo. A reading placebo cannot change a verdict, because a cell that
  fails conditions 1-5 fails the bar anyway.

## 8. Stages, outputs, ledger, engineering

- **VAL / TEST:** the selected cell only, unchanged, on the VAL / TEST universe built the same way, with its own
  placebo. The verdicts are FAIL_VAL / SELECTED_ON_VAL, then FAIL_TEST / PASS_TEST.
  - TEST runs only if VAL's verdict is SELECTED_ON_VAL. It needs `LAB7_ALLOW_TEST=1` and is refused once
    `W4/test.json` exists (`core.first_test_look`).
- **Result files:** `W4/<stage>.json` and `W4/<stage>.md`: the decision first, plain words for the owner, the best (or
  selected) cell in detail with its risk book and breakdowns, the placebo readings, the references, the mirror table,
  then every cell in one table.
- **Ledger:** every cell of every stage goes into `research/lab7/trials.json` through `core.record_runs` (an upsert
  under a file lock). The fields are those of PLAN §9, with `plan_sha256` and `prereg_sha256` (the sha256 of this
  file, also written to `W4/PREREG.sha256` before the first TRAIN run).
- **Per-trade files:** only the selected cell (TRAIN) and the VAL / TEST cell, as zstd parquet under
  `$SCRATCH/lab7/W4/`.
- **Engineering (memory; free disk is under 9 GB and the machine is shared):**
  - the grid is walked **one entry rule at a time**: 8 passes, each over every market with its 24 exit cells and its
    reference;
  - each pass keeps only the cells' readings and their per-market trip counts (for the placebo);
  - the kept cell's trips are re-walked at the end (the walk is deterministic);
  - at most 4 fork workers, ordered `imap`, one tape in memory per worker.

## 9. Known limits (stated before any return)

- **The universe is chosen after the fact.** It holds markets that closed in the split with volume of at least
  $20,000, and the cache holds only their last 14 days. A live desk trades every open market, including many that
  will not resolve for months, are quiet, or never trade $20,000. W4's tapes therefore over-represent markets in
  their resolution phase, when prices travel to 0 or 1. This bias is strongest for markets that closed early (a
  live desk did not know they would close). The scheduled-end and far-from-the-end subsets (§6) are there to show
  how much a result rests on it. The placebo uses the same markets, so it shares the bias for random entries, but not
  for entries that follow a move.
- **endDate** is the value in lab 4's market file, fetched after the markets closed. If the venue moved a market's
  endDate, the market end used here may differ from what a live desk saw.
- **Order within a second:** the cache orders prints within one second by transaction hash, not by time. The signal
  at a print may therefore reflect a print that came later within the same second. The 10 s latency makes this
  immaterial for fills, but it is a limit.
- **Size and venue:** a taker fill takes the whole $20 at one print's price (the big-entry subset shows how much that
  carries). The tape is polymarket.com (tick 0.01 in the middle of the range), not Polymarket US, and Polymarket US
  may not list these markets at all. A pass would need the desk to confirm the venue lists them.
- **Side:** Polymarket US quotes every order on YES, so a pass that rests on No buys (side B) needs the desk to
  confirm that it can open them.
- **Correlated markets:** a weather event's brackets or a date ladder move together; the event bootstrap treats an
  event as one draw, and the risk book's max open positions counts them all.

## 10. The checks a pass would face before it is believed

These decide nothing. They are written now so they cannot be bent later. If a cell passes TRAIN (and again on VAL /
TEST), the report must show and discuss:

- its gross mean against the fees it pays;
- the big-entry subset;
- the exit mix (does it rest on `settle`, `->settle` or exits after the end?);
- the scheduled-end and far-from-the-end subsets (does it rest on markets that closed early, or on the last day?);
- the concentration by family and the ten largest events (is it one weather city, or one news day?);
- the side mix (does it rest on No buys?);
- the mirror twin (does the opposite direction lose about as much before fees?);
- the placebo percentile and drop share;
- whether the placebo's random entries are a fair comparison: they enter at random times inside the window, while
  the real entries come right after a move, when prices move fastest and markets are often nearest their resolution.

A **high win rate is not an edge** (PLAN §2). Near 50c, a 3c taker take profit loses money even when it "wins".

# Lab 7 W3 pre-registration: sports in-play swings (momentum and fade)

Written 2026-10-10 ~21:10 UTC by the W3 specialist, under `research/lab7/PLAN.md` (lab7-v1). **At the time of writing
no W3 return had been computed or read.**

## 0. What has been run on real data

- A structure count of the TRAIN universe (`run.py --structure train`): 8,259 game-winner markets in 6,998 games;
  4,392 markets (3,635 games) with a recorded end, 3,867 (3,363 games) with P6's fallback end. Recorded-end markets by
  sport: tennis 2,218, soccer 1,321, baseball 576, cricket 154, basketball 112, American football 11. Every market's
  polymarket.com fee rate is 0.05 (sports).
- The W3 tests, including a structure check that W3's mirrored universe equals lab 4 P6's own on TRAIN
  (`tests/test_w3.py`).
- A timing smoke test on 40 random TRAIN recorded-end markets. It printed only the run time (10.7 s for all 296 cells)
  and the total number of round trips across all cells (93,080), plus the time of one placebo block
  (about 0.19 ms per counterpart). No profit, loss, price, win rate or exit figure was printed or read.
- Disclosure: while reading W1's code for conventions, the W3 specialist saw the one-line headline of W1's TRAIN
  result (NO EDGE). W3's grid, band, bar and execution are fixed by the plan, so nothing below depends on it.

This file adds only what the plan leaves open. It changes no grid value, fee, band, bar, split or execution rule.

## 1. Universe (PLAN §5 W3)

- **Markets:** lab 4's eligible markets of the split: binary, one winner (`winner_index` 0 or 1), split by
  closedTime (`lab4 core.Dataset.eligible`). They are joined to P6's game facts (`$LAB4_DATA/p6_meta.parquet`, fetched
  rows, one per id).
- **P6's helpers, mirrored:** P6's `load_meta`, `with_game_facts` and `is_universe` are mirrored line for line in
  `W3/run.py`, with P6's fallback-lag table. P6's `p6.py` is not imported: it does `import core`, which would collide
  with lab 7's `core`. P6's `sports.py` (pure) is loaded directly. A test checks the mirror against P6 itself on
  TRAIN: the same ids, the same ends, the same end kinds, and 4,392 recorded-end markets.
- **Kept:** `sportsMarketType == "moneyline"`, a known start, end > start, and sport (P6 `sport_of` of the event slug)
  not `"other"`.
- **Start:** the event's `startTime`, else the market's `gameStartTime`.
- **Recorded end:** Gamma's `finishedTimestamp` when `start < end <= closedTime` (kind `final whistle`). Only these
  markets decide.
- **Fallback end:** otherwise, P6's `closedTime - L(sport)` (kind `fallback end`). These markets are walked through
  every cell and reported apart, as a breakdown. They never decide, never enter the bootstrap, the placebo or the
  ledger, and are not trials.
- **Fills:** at least 50 prints, counted by `core.load_tape(id, min_fills=50)` after core's validity filter (the same
  filter as lab 4's `Dataset.load`). A market with fewer prints is skipped and counted.
- **Settlement:** `payout = (1, 0)` if `winner_index == 0`, else `(0, 1)`. `settle_t = hard_end =` the market's
  closedTime.
- **Fee rate (`rate_com`):** lab 4's `fee_rate(feeType, feesEnabled)` (0.05 for every TRAIN market).
- **Event (bootstrap group):** the event slug (a game's markets, for example a soccer game's three Yes/No markets,
  are one draw).
- **Order:** markets ordered by closedTime, then id. Trips are ordered by entry time, then id, before any reading.

## 2. Times and the market (PLAN §5 W3)

- **Entry window:** one interval `[start + y, end)` per lookback y. A market whose end is not after `start + y` has
  no window for that y.
- **Market fields:** `entry_deadline = end_t = end`, `end_mode = "settle"`, `hard_end = settle_t = closedTime`,
  `band = (0.20, 0.80)`, no fair.
- **Time stops:**
  - the 15 / 45 minute stops are `Exits.hold_s = 900 / 2700`. A `hold_s` stop that would fall at or after the end
    becomes the end (core: `t_entry + hold_s < end_t`, otherwise the end in mode `settle`), and the position is held
    to settlement;
  - "game end" is `hold_s = None`: the position is watched until the end, then held to settlement.
- **Exits (core):** a triggered take profit or stop sells at the first sellable print at or after the trigger + 10 s,
  before closedTime. That sale may come after the recorded end. It is a real print, and it is reported as a reading
  (§6).

## 3. Signals

- **Signal:** `core.swing_signals(tape, x, 60 * y_min, k=5, direction)`, computed once per (direction, x, y) per market
  and shared by that entry rule's 36 exit cells and its reference.
- **Price used:** outcome 0's price at every print (either side).
- **Reference print:** the last print at or before `t - y`. When no print falls in `[start, t - y]`, that reference
  is the last print before the start. This is core's convention, kept unchanged. The lookback interval `[t - y, t]`
  itself is always in play, because `t >= start + y`.
- **Walk:** `core.walk` applies the window and the band (the bought outcome's price at the signal print).
- **Directions:** MOMENTUM buys outcome 0 after a rise of at least x, and outcome 1 after a fall. FADE does the
  opposite.

## 4. Cells (PLAN §5 W3)

- **Entry rule key:** `<mom|fade>|x<x>|y<y>m`, with x in {0.05, 0.1} and y in {2, 5}, printed with `%g`.
- **Selectable cells:** `<entry>|tp<tp>|sl<sl>|t<15m|45m|end>|<taker|maker>`, with tp in {0.03, 0.05, 0.1} and sl in
  {0.05, 0.1}, as `Exits(tp, sl, tp_mode, hold_s)` with `fair_exit = False`. That gives
  2 x 2 x 2 x 3 x 2 x 3 x 2 = **288 cells**.
- **References:** `hold|<entry>`, `Exits(hold_to_settlement=True)`: the first filled entry per market, held to
  settlement. That gives **8 cells**, reported only.
- **Trials:** all 296 are trials on TRAIN.

## 5. Decision inputs

- **Deciding set:** a cell's deciding readings use its round trips in recorded-end markets only.
- **Missed entries:** counted on the same set.
- **Bar:** `core.bar` (PLAN §7) on the deciding summary, with the cell's placebo.
- **TRAIN selection:** `core.select_one` among the 288 selectable cells. No pass gives **NO_EDGE_TRAIN**, and VAL and
  TEST are not run.

## 6. Readings (every cell; readings only, never a selector)

- `core.summarize` and its `risk_book`. These hold n, events, missed entries, trips per day, win rate, the mean net
  per $ under the US / com / stress fees, the event-bootstrap CI95 (B = 2000, seed 0), the rule-of-three worst case,
  the exit mix, late stops, median hold, cents per contract won and lost, the break-even win rate, the mean entry
  price and the small-entry share. The risk book holds max open positions and capital, the $10 daily loss stop
  overlay, max drawdown, worst / best day, daily Sharpe, longest losing streak and worst trip.
- **Gross mean** (net + US fee, per $) with its event-bootstrap CI95.
- **Entry slippage** (entry fill price minus the signal print's price, for the bought outcome) and the median entry
  delay.
- **Big-entry subset:** the trips whose entry print alone covered our contracts (n, mean, CI95).
- **Exits after the end:** trips whose exit fill (not a settlement) came at or after the recorded end (n, share,
  mean).
- **Concentration:** the share of the absolute P&L carried by the ten games with the largest absolute P&L.
- **Breakdowns:** by sport, by league (top 20 by n), by the side bought (A = Yes or the first-listed team,
  B = No or the second-listed team), and by the four labels yes / no / team1 / team2.
- **Fallback-end reading:** the same cell on the fallback-end markets: n, games, win rate, mean net, CI95,
  stress mean, total $.
- **Mirror table (TRAIN):** for every momentum cell, the gross and net means of its fade twin, which has the same x, y
  and exits. On the same moves, momentum and fade hold opposite sides, so with no skill one's gross gain should be
  roughly the other's gross loss. A large positive gross on BOTH would point to a simulator artifact.
- **The reference cells:** would holding the same first entry to settlement have done better than trading out?

## 7. The placebo (PLAN §7)

- **Method:** `core.placebo_matrix` with 200 draws, on the recorded-end markets where the cell traded, with as many
  counterparts per draw as the market has real round trips in the cell.
- **Market:** the counterparts use the cell's own market, with the entry window `[start + y, end)` for the cell's y.
- **Seeds:** for each market,
  `numpy.random.default_rng([core.placebo_seed("W3", cell, split), crc32(market id)])`, so the result does not depend
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
    `W3/test.json` exists (`core.first_test_look`).
- **Result files:** `W3/<stage>.json` and `W3/<stage>.md`: the decision first, plain words for the owner, the best (or
  selected) cell in detail with its risk book and breakdowns, the placebo readings, the references, the mirror table,
  then every cell in one table.
- **Ledger:** every cell of every stage goes into `research/lab7/trials.json` through `core.record_runs` (an upsert
  under a file lock). The fields are those of PLAN §9, with `plan_sha256` and `prereg_sha256` (the sha256 of this
  file, also written to `W3/PREREG.sha256` before the first TRAIN run).
- **Per-trade files:** only the selected cell (TRAIN) and the VAL / TEST cell, as zstd parquet under
  `$SCRATCH/lab7/W3/`.
- **Engineering (memory; free disk is under 9 GB and the machine is shared):**
  - the grid is walked **one entry rule at a time**: 8 passes, each over every market with its 36 exit cells and its
    reference;
  - each pass keeps only the cells' readings and their per-market trip counts (for the placebo);
  - the kept cell's trips are re-walked at the end (the walk is deterministic);
  - 4 fork workers, ordered `imap`, one tape in memory per worker.

## 9. Known limits (stated before any return)

- **Order within a second:** the cache orders prints within one second by transaction hash, not by time. The signal
  at a print may therefore reflect a print that came later within the same second. The 10 s latency makes this
  immaterial for fills, but it is a limit.
- **Start:** `startTime` is the scheduled start, so a delayed start lets pre-game prints into the window.
- **End:** `finishedTimestamp` is the recorded end. Using it as the entry deadline and the "game end" stop assumes the
  desk knows the game is over at that instant (the live desk reads a final period, with some delay).
- **Size and venue:** a taker fill takes the whole $20 at one print's price (the big-entry subset shows how much that
  carries). The tape is polymarket.com (tick 0.01 in the middle of the range), not Polymarket US.
- **Side:** Polymarket US quotes every order on YES, so a pass that rests on No buys (side B in Yes/No markets) needs
  the desk to confirm that it can open them.

## 10. The checks a pass would face before it is believed

These decide nothing. They are written now so they cannot be bent later. If a cell passes TRAIN (and again on VAL /
TEST), the report must show and discuss:

- its gross mean against the fees it pays;
- the big-entry subset;
- the exit mix (does it rest on `settle`, `->settle` or exits after the end?);
- the concentration by sport, league and the ten largest games;
- the side mix (does it rest on No buys?);
- the mirror twin (does the opposite direction lose about as much before fees?);
- the fallback-end reading (does the same rule hold on the games P6 timed roughly?);
- the placebo percentile and drop share;
- whether the placebo's random entries are a fair comparison: they enter at random in-play times, while the real
  entries come right after a swing, when prices move fastest.

A **high win rate is not an edge** (PLAN §2). Near 50c, a 3c taker take profit loses money even when it "wins".

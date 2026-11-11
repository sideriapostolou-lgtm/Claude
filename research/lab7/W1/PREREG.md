# Lab 7 W1 pre-registration: sports pre-game convergence to Pinnacle

Written 2026-10-10 ~20:34 UTC by the W1 specialist, under `research/lab7/PLAN.md` (lab7-v1). **At the time of writing
no W1 return had been computed or read.** The only code run on real data was a structure count of the TRAIN universe
(`run.py --structure train`: 2,161 matched games, 3,005 markets, 1,442 two-way and 1,563 soccer Yes/No markets,
2,974 with a closing line, a median of 6.1 hours of entry windows per market) and the W1 tests. The simulator was
timed only on a synthetic random tape. This file adds only what the plan leaves open. It changes no grid value, fee,
band, bar, split or execution rule.

## 1. Universe (PLAN §5 W1)

- **Games:** lab 6's matched games, rebuilt the way `research/lab6/run.py load_matched` builds them
  (`lab6 core.build_games` on lab 4's `markets.parquet` and lab 6's `gamma_meta.parquet`, then lab 6
  `data.active_games` with `pregame.parquet`, then `matches.parquet`). The two loaders are mirrored line for line in
  `W1/run.py load_matched`. Lab 6's `data.py` and `run.py` are not imported: both `import core`, which would collide
  with lab 7's `core`. Lab 6's `core.py` is loaded under the name `lab6_core`. A test checks that the result is lab
  6's 5,476 matched games with lab 6's split counts.
- **Split:** lab 6's split of the GAME (the earliest closedTime among the game's markets).
- **Markets:** every market of the game that lab 6 gives both sides (o = 0 and 1). A market whose outcome prices do not
  add up to one has no sides in lab 6, so it is not traded.
  - A 2-way market's outcome 0 is Polymarket's team A.
  - A soccer market's outcome 0 is Yes and outcome 1 is No.
  - A soccer game can have up to three markets (home, draw, away). Each market is its own `core.Market` (one position
    per market at a time), and the game is one event in the bootstrap.
- **Tape:** `core.load_tape(market id)`, one market at a time. A market without a tape is skipped and counted.
- **Settlement:** `payout = (final price of outcome 0, final price of outcome 1)`, which is 1 / 0, or 0.5 / 0.5 on
  a split resolution (lab 6's `final`). `settle_t` = `hard_end` = the market's own closedTime.
- **`rate_com`:** lab 4's `fee_rate` of the market (sports: 0.05), as lab 6's sides carry it.

## 2. Times

- **`commence`:** lab 6's: Pinnacle's commence time on the event's last pre-game snapshot (`matches.parquet`).
- **`cutoff`:** `min(commence, the game's gameStartTime)`, the game's start being the earliest of its markets'
  gameStartTime (lab 6).
- **Entry windows:** for each Pinnacle snapshot of the event (`lab6 core.event_lines`, method `mult`) with
  `snap_ts < commence`, the interval `[snap_ts, snap_ts + 30 min)`, clipped to `[commence - 24 h, cutoff)`. The
  intervals are **merged into disjoint intervals**, so the placebo's uniform draw does not count an overlap twice.
- **Market fields:** `entry_deadline = end_t = cutoff`, `end_mode = "last_before"`, no `hold_s`, band 0.15-0.85.

## 3. The fair (no lookahead)

`fair[o, i]` = outcome o's multiplicative no-vig fair (lab 6 `side_fair`, mapped by role with `a_is_home`) from
snapshot `j = lab6 core.snapshot_index(snap_ts, ts_i, commence, 30 min)`. That is the last snapshot at or before
print i, strictly before commence, at most 30 minutes old. The fair is **NaN** when there is no such snapshot, and
also at or after the cutoff. No position is watched at or after the cutoff (the time stop), so that last NaN changes
no trade. A 2-way Polymarket market whose Pinnacle line has a draw (three outcomes) keeps lab 6's mapping: each team's
own probability, so the two fairs add up to less than one. Tests: `tests/test_w1.py`.

## 4. Signals and cells

- **Signal:** `core.gap_signals(tape, fair, m)`, computed once per market per m and shared by every exit cell.
  `core.walk` applies the windows and the band.
- **Cell keys:**
  - selectable: `m<m>|tp<tp>|sl<sl or none>|tcutoff|<taker|maker>` (numbers printed with `%g`), with
    `Exits(tp, sl, tp_mode, fair_exit=True)`. That gives 3 x 3 x 3 x 2 = 54 cells;
  - references: `hold|m<m>`, `Exits(hold_to_settlement=True)` on the same signals (the first filled entry per market
    held to settlement). That gives 3 cells.
- **Trials:** all 57 are trials on TRAIN.

## 5. Readings (beyond `core.summarize` and `core.risk_book`, all of them readings only)

- by league and by market kind (2-way / soccer): n, games, win rate, mean net (US), total $;
- **closing-line value** of the entries: Pinnacle's closing fair for the bought outcome (lab 6 `closing_index`: the
  last snapshot strictly before the cutoff, at most 30 minutes old) minus the entry price. Reported as the mean, its
  game-bootstrap CI95 and the share above zero;
- the **gross** mean (before any fee), with its CI95;
- the mean gap at the signal print (fair - signal print price) and the mean entry slippage (entry price - signal
  print price);
- the mean net of the trips whose entry print alone covered our contracts (the one-print fill assumption);
- the median minutes between a time-stop sale and the cutoff. The `last_before` rule picks the LAST bid-side print
  before the start, which uses hindsight on WHEN the last bid came (not on its price). This reading shows how far
  from the start that sale happened.

The game bootstrap is `core.event_bootstrap_ci` with B = 2000 and seed 0 (core's defaults).

## 6. The placebo

- **Draws and seeds:** `core.placebo_matrix` with 200 draws. The generator for each market is
  `numpy.random.default_rng([core.placebo_seed("W1", cell, split), crc32(market id)])`, so the result does not depend
  on the order in which the worker processes finish.
- **Decision (PLAN §7):** the placebo is computed for every cell that clears conditions 1-5, and only those can pass.
- **Readings on TRAIN:** it is also computed for every selectable cell, unless the total counterparts
  (200 x the summed n of those cells) would exceed 40 million. In that case the reading-only placebos are limited to
  the cells clearing 1-5 plus the six selectable cells with the highest CI95 lower bound. The result file records
  which case applied.
- **References:** no placebo.

## 7. Decision, outputs and the ledger

- **Decision:** `core.bar` and `core.select_one` exactly as in PLAN §7. If there is no pass on TRAIN, the result is
  NO_EDGE_TRAIN, and VAL and TEST are not run.
- **VAL and TEST:** the selected cell only, unchanged. The universe is built in the same way on lab 6's VAL / TEST
  games, with the cell's own placebo. TEST is one look with `LAB7_ALLOW_TEST=1`, refused once `W1/test.json`
  exists.
- **Result files:** `W1/<stage>.json` and `W1/<stage>.md`, with the decision first, then every cell.
- **Ledger:** every cell goes into `research/lab7/trials.json` through `core.record_runs`. The fields are those of
  PLAN §9, with `plan_sha256` and `prereg_sha256` (the sha256 of this file).
- **Per-trade files:** only for the selected cell and the VAL / TEST cell, as zstd parquet under `$SCRATCH/lab7/W1/`.

## 8. The checks a pass would face before it is believed (decide nothing; written now so they cannot be bent later)

If a cell passes, the report must also show:

- its gross mean (is the edge larger than the fee it pays?);
- the big-entry subset (does it survive when the entry print alone covered our $20?);
- the exit mix (does it rest on `->settle` or late stops?);
- the concentration by league (does one league carry it?);
- the median time-stop lead;
- the placebo percentile.

None of these can rescue a failing cell or sink a passing one. They are the honest caveats a paper desk must hear.

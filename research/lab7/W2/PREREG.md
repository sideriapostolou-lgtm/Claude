# Lab 7 W2 pre-registration: crypto up / down windows, convergence to Binance spot

Written 2026-10-10 ~20:35 UTC by the W2 specialist, under `research/lab7/PLAN.md` (lab7-v1). **At the time of writing
no W2 return had been computed or read.** The only code run on real data was:

- a structure-only smoke test on 40 random TRAIN windows: timings and trip COUNTS only, with no profit, loss, win
  rate or exit price printed. It found 0.09 s to build a window and 0.33 s to walk all 57 cells, up to about 8 round
  trips per window per cell, a fair defined at 95 % of prints, and 0.03 s per placebo counterpart (one trip, 200 draws);
- counts of the catalogue: 15,843 TRAIN windows (11,901 5m, 3,016 15m, 926 1h); every window in the catalogue has
  polymarket.com fee rate 0.07; tape timestamps are whole seconds; closedTime comes 18-87 s after a 5m / 15m
  window's end and 660-1,021 s after a 1h window's end (20-window samples);
- the W2 tests (`research/lab7/tests/test_w2.py`), on synthetic spot and tapes.

This file adds only what the plan leaves open. It changes no grid value, fee, band, bar, split or execution rule.

## 1. Universe (PLAN §5 W2)

- **Catalogue and universe:** lab 5's, called directly: `research/lab5/run.py catalogue()` (lab 4's
  `markets.parquet` + lab 5's `rules.parquet`, parsed by lab 5's `parse_market`) and `universe(cat, split)` (binary,
  winner index 0 or 1, a parsed contract on BTC / ETH / SOL / XRP, lab 4's split by closedTime). W2 keeps
  `kind == "window"` and `sub` in {5m, 15m, 1h}. Lab 5's `parse_market` already drops a Chainlink window without
  `priceToBeat`.
- Lab 5's `core.py`, `data.py` and `run.py` are loaded under the names `lab5_core`, `lab5_data`, `lab5_run`. While
  lab 5's `run.py` loads, the names `core` and `data` point at lab 5's files, then lab 7's `core` is restored.
- **Tape:** lab 7 `core.load_tape(id, min_fills=50)`, one market at a time. Its valid-print filter is lab 5's. A
  window without a tape, or with fewer than 50 fills, is skipped and counted.
- **Symbols:** all four, in one pool. Almost every window is BTC. The breakdown is by symbol.

## 2. One window as a `core.Market`

| field | value |
|---|---|
| `id` | the market id |
| `event` | lab 5's cluster `"W:" + UTC hour of (t_final - 1)` (`lab5 run._cluster`): every window ending in the same UTC hour, on any symbol, is one event in the bootstrap |
| `split` | lab 7 `core.split_of(closedTime)` (lab 4's) |
| `payout` | (1, 0) if lab 4's winner index is 0 (Up), else (0, 1): the venue's outcome |
| `settle_t` | closedTime (the instant the venue resolves; a held position's capital is locked until then) |
| `hard_end` | min(t_final, closedTime), where t_final is lab 5's `t_final`, the window end |
| `entry_windows` | one interval `[ref_known, t_stop)`, with lab 5's `ref_known`: t0 for Chainlink windows (`priceToBeat` is public at the open), t0 + 1 s for Binance 1h windows (the 1H open is known once its first 1 s candle closes) |
| `t_stop` | t_final - 60 s (5m, 15m) or t_final - 300 s (1h) |
| `entry_deadline`, `end_t` | t_stop |
| `end_mode` | `next` |
| `band` | (0.10, 0.90) |
| `rate_com` | 0.07 |
| `fair` | §3 |
| `info` | sub, symbol, source (breakdowns only) |

A window whose closedTime falls before its time stop keeps these fields. `hard_end` then stops every fill at
closedTime. The count is reported.

## 3. The fair (no lookahead)

- `fair[0, i]` = lab 5 `q_event(m5, spot, t_i, 3600, sigma_b)`, with `t_i = floor(ts_i)` = the print's own second.
  Tape timestamps are whole seconds, so `t_i = ts_i`.
  - `q_event` reads the close of the 1 s candle opening at `t_i - 1`, which closes at `t_i`, and the 1-minute returns
    of minutes that ended by `t_i`. With lab 5's rule, at least 80 % of the 60 minutes must be present.
  - For TWAP windows, it reads the closes of candles opening in `[t_final - L, t_i)`. Kappa (priceToBeat over
    Binance's proxy at the open) is known at t0.
  - For Chainlink windows, `sigma_b = 7.54297561130444e-05` (`research/lab5/structure.json` `basis.sigma_b`, the exact
    stored value; the plan's 7.54e-5), fixed for every split. Binance 1h windows get no basis (lab 5).
  - The fair is NaN where lab 5's model is undefined: before `ref_known`, at or after `t_final`, without spot, or
    without enough variance minutes.
- `fair[1, i] = 1 - fair[0, i]` (an Up / Down window's outcome 0 is Up; lab 5's `event_outcome` is 0).
- The fair is what drives the signal and the take-profit cap (`fair_exit=True`). It is the fair known at that print,
  never a later one (core).
- Test (`test_fair_never_reads_a_candle_that_closed_after_the_print`): spot candles opening at or after a cut are
  changed, and every fair at a print stamped at or before the cut must stay identical.

## 4. Signals and cells

- **Signal:** `core.gap_signals(tape, fair, m)`, once per window per m, shared by every exit cell. `core.walk`
  applies the entry window and the band.
- **Selectable cells:** `m<m>|tp<tp>|sl<sl or none>|tend|<taker|maker>`, numbers printed with `%g`. `tend` is the
  window's time stop (§2). Each uses `Exits(tp, sl, tp_mode, fair_exit=True)`, with no `hold_s`. The grid is
  m {0.03, 0.05, 0.08} x tp {0.03, 0.05, 0.08} x sl {0.05, 0.10, none} x {taker, maker} = 54 cells.
- **References:** `hold|m<m>`, `Exits(hold_to_settlement=True)` on the same signals: the first filled entry per
  window, held to the venue's settlement. That gives 3 cells, reported and never selectable.
- **Trials:** all 57 are trials on TRAIN; VAL and TEST add at most one each.

## 5. Bar, selection, VAL, TEST

- **The bar and selection:** exactly `core.bar_checks`, `core.bar` and `core.select_one` (PLAN §7). The US fee
  selects. The bootstrap is `core.summarize`'s (lab 4's event bootstrap, B = 2000, seed 0, events as in §2).
- **Verdicts:** `NO_EDGE_TRAIN`, or a selected cell; then `SELECTED_ON_VAL` or `FAIL_VAL`; then `PASS_TEST` or
  `FAIL_TEST`.
- **VAL:** runs only if `W2/train.json` names a selected cell, and evaluates that cell alone, unchanged, with its own
  VAL placebo.
- **TEST:** runs only if `W2/val.json` has `SELECTED_ON_VAL`, with `LAB7_ALLOW_TEST=1`, once (`core.first_test_look`
  on `W2/test.json`).

## 6. The placebo

- **Required (PLAN §7):** for every selectable cell that clears conditions 1-5 on the split.
- **Per window:** `core.placebo_matrix(mk, n, exits)`, with n = the window's real round trips in that cell and 200
  draws. The generator for each window is `numpy.random.default_rng([core.placebo_seed("W2", cell, split),
  crc32(window id)])`, so the draw does not depend on the worker or the order. `core.placebo_reading` combines the
  windows.
- **Readings only, never a decision input:**
  - on TRAIN, the placebo is also computed for the ONE selectable cell with the highest CI95 lower bound (ties as
    `select_one`) when it is not already required, and for the three reference cells;
  - on VAL and TEST, it is always computed for the cell under test.

## 7. Readings (beyond `core.summarize` and `core.risk_book`; all readings, never selectors)

- **Breakdowns per cell:** by window length (5m / 15m / 1h) and by symbol. Each gives n, win rate, mean net (US) and
  total $.
- **Entry readings per cell:** how much of the gap survives the 10 s lag. The fair at a print's second is the same for
  every print of that second.
  - mean gap at the signal: fair at the signal print minus the signal print's price;
  - mean slippage: entry fill price minus the signal print's price;
  - mean gap left at the fill: the fair known at the fill print's second minus the fill price;
  - the share of fills whose gap is still >= m;
  - the share of fills above the fair.
- **Coverage:** windows in the split; evaluated and skipped; counts by length and by symbol; windows closed before
  their time stop; median prints per window; the polymarket.com fee rates found in the catalogue.
- **Markets traded per cell.**

## 8. Engineering

- **Workers:** 4 fork workers. The spot arrays (lab 5 `load_spots`, all four symbols) are loaded once, before
  forking. Each worker holds one window's tape at a time.
- **Workers return** each window's round trips as numeric arrays (cell, reason and exit leg as small integer codes).
  The parent decodes one cell at a time into lab 7's trip frame (`core.TRIP_COLUMNS`). A test proves the round trip
  is exact.
- **Output:** `W2/<stage>.json` and `W2/<stage>.md`, with the decision first in plain words, then every cell's table.
  A zstd parquet of round trips is written under `$SCRATCH/lab7/` only for the selected, VAL and TEST cell.
- **Trial ledger:** `core.record_runs` into `research/lab7/trials.json` with hyp, cell, split, stage, kind
  (`selectable` / `reference`), n, mean_net_us, ci95, mean_net_stress, passes, and the sha256 of PLAN.md and of this
  file.

## 9. Known limits, stated before any result

- **The owner's venue may not list these markets.** On 2026-10-09 Polymarket US's non-sports markets were hourly and
  weekly crypto STRIKE markets (`research/lab4/VENUES.md`). Lab 5 §5 says the same. They were not 5m / 15m / 1h
  up / down windows. A W2 pass would therefore need the desk to confirm that the venue lists up / down windows, or to
  carry the rule over to a strike market, before any pretend-money trading.
- **The fair for Chainlink windows** comes through a Binance proxy with the measured basis. The bets settle on the
  venue's outcome.
- **The latency is long for these windows.** A 10 s latency on a 240 s entry window (5m) is the plan's fixed rule and
  is conservative for a live trader with a real-time feed. Lab 5 found that prints lead a spot read at the print time
  by about 2 s, so part of any measured gap is stale spot, not a stale price.
- **The tape's tick is 0.01,** against 0.001 on the US venue (PLAN §4).

# Lab 7: in-and-out trading. Pre-registration, version lab7-v1

Written 2026-10-10 ~20:20 UTC. At the time of writing NO return of this study had been computed or read. The only
code run on real data was a structure-only smoke test of `core.py` on 30 TRAIN politics tapes: run time and
memory, no profit or loss printed. The fee arithmetic in §2 comes from the published fee formula, not from data.

## 0. In plain words (for the owner)

The idea: instead of buying near-certain outcomes at 97c and holding them (lab 4: no edge), each desk becomes a
specialist that buys a contract when it looks cheap, for example at 50c, and sells it a little higher, for
example at 55c, taking the profit. It cuts a loss quickly with a stop, never holds a trade too long, and keeps
strict risk limits.

Lab 7 tests that on four months of real Polymarket trades, the same way labs 4-6 did:

- the rules are written down here before any result is seen;
- the oldest six weeks choose at most one rule per desk;
- the next month must confirm it;
- the last three weeks are looked at once.

There are four specialists:

| desk | market | what it looks for |
|---|---|---|
| W1 | sports before the game | Polymarket's price below the sharpest bookmaker's (Pinnacle's) fair price |
| W2 | crypto up/down windows | the price below a fair value worked out from Bitcoin's live price |
| W3 | sports during the game | sharp price swings (follow them, or bet against them) |
| W4 | politics, culture, weather, economics and the rest | slower swings over hours |

The one number to keep in mind (§2): on Polymarket US a 50c contract costs about 1.7c in fees each time you buy
or sell. A 50c-to-55c trade therefore keeps about 1.5c of its 5c. A stop at 45c loses about 8.5c. To come out
ahead, that trade has to be right about 85 % of the time. Without real skill it would be right about 50 % of the
time. Lab 7 measures whether any specialist has that skill. A pass here only means "ready for pretend-money
trading on the live desk". It never means real money by itself.

## 1. What is new, and what is reused

Labs 4, 5 and 6 found NO EDGE in strategies that buy and hold to settlement:

- lab 4: near-certain outcomes;
- lab 5: crypto price markets against Binance spot fair value;
- lab 6: sports moneylines against Pinnacle's no-vig fair.

Lab 6's closing-line diagnostic found that its entry prices were 1.25c worse than Pinnacle's last line on
average. Lab 7 changes one thing: positions are **closed early**, by a take profit, a stop loss or a time stop.

Reused unchanged:

- lab 4's tapes, splits, buyable-print convention, fee families and event bootstrap (`research/lab4/core.py`,
  PLAN Amendments 1-5);
- lab 5's crypto fair value (`research/lab5/core.py`);
- lab 6's Pinnacle no-vig fair and its game matching (`research/lab6/core.py`, `run.py`);
- lab 4 P6's game start and end times (`research/lab4/P6/p6.py`).

Research only, paper only:

- no key is read, printed or stored;
- no Odds API call: lab 6's Pinnacle data is already cached;
- public endpoints only if truly needed, and gently;
- nothing in `src/`, Railway, deploys or pushes is touched.

## 2. The arithmetic that decides this lab (from the fee formula, before any data)

The Polymarket US taker fee is `0.0695 x contracts x p x (1 - p)` on every buy and every sell. A resting (maker)
order pays nothing: polymarket.com charges makers no fee, and Polymarket US pays makers a rebate, which lab 7
never counts as income (`research/lab4/VENUES.md`; lab 4 PLAN Amendments 1-2). Per one-dollar contract, assuming
no spread and exits exactly at the target or the stop:

| entry | move | fee per leg (entry) | win, taker exit | win, maker exit | loss at the stop | break-even win rate, taker / maker |
|---|---|---|---|---|---|---|
| 50c | 5c | 1.74c | +1.54c | +3.26c | -8.46c | 84.6 % / 72.2 % |
| 50c | 3c | 1.74c | **-0.47c** | +1.26c | -6.47c | never / 83.7 % |
| 50c | 10c | 1.74c | +6.59c | +8.26c | -13.41c | 67.0 % / 61.9 % |
| 30c | 5c | 1.46c | +1.96c | +3.54c | -7.76c | 79.8 % / 68.7 % |
| 80c | 5c | 1.11c | +3.00c | +3.89c | -7.42c | 71.2 % / 65.6 % |

Without a stop, the time stop plays the same role. With no edge, a price reaches +d before -d about half the
time, so these break-even win rates are the skill a specialist must show. The spread comes on top: a taker buys at
the ask and sells at the bid. Near the middle of the price range, a 2c or 3c take profit sold as a taker loses
money even when it "wins". Those cells stay in the grid (it is fixed below), and their maker twins are the only
way they can pass. **A high win rate is not an edge.** That is why every cell must beat the random-entry placebo
(§7).

## 3. Data and splits

- **Tapes:** lab 4's cache of polymarket.com per-trade tapes (`$SCRATCH/lab4/trades/<id>.parquet`, 7.6 GB, the
  last 14 days before each market's closedTime, markets closed 2026-07-01..2026-10-08 with volume >= $20,000),
  read **one market at a time** (`core.load_tape`; never all at once).
- **Splits:** lab 4's, by the market's closedTime (UTC). For a trade, the split is its market's.
  - TRAIN: 2026-07-01 to 2026-08-15.
  - VAL: 2026-08-16 to 2026-09-15.
  - TEST: 2026-09-16 to 2026-10-08. TEST is one look: it refuses without `LAB7_ALLOW_TEST=1`
    (`core.check_split_allowed`), and a second look is refused once `<W>/test.json` exists
    (`core.first_test_look`).
- W1 uses lab 6's split of the GAME (the game's earliest market closedTime), as lab 6 did.
- **Universe sizes,** from earlier inventories (structure only, no return):
  - W1: 5,476 matched games over the three splits (lab 6 `INVENTORY.md`).
  - W2: 5m / 15m / 1h windows on TRAIN, VAL and TEST: about 15,800 / 11,100 / 8,000 (lab 5 `inventory.md`;
    almost all BTC).
  - W3: TRAIN game-winner markets with a recorded end: about 4,390 (lab 4 P6 `train.md`).
  - W4: binary, single-winner markets in the seven families, before the 50-fill filter: 3,122 / 1,457 / 1,148
    (politics, culture, economics, weather, mentions, tech, finance).

## 4. The execution model (FIXED; `research/lab7/core.py`, tested in `tests/test_core.py`)

- **Sides.** A print is BUYABLE for outcome o when it is a taker BUY on o's token, or a taker SELL on the other
  token at 1 - p (lab 4 Amendment 3). It is SELLABLE for o (a taker sold into a bid for o) when it is a taker SELL
  on o's token, or a taker BUY on the other token at 1 - p. Every print is buyable for one outcome and sellable for
  the other.
- **Decisions** use only prints, snapshots and spot with timestamps at or before the decision time. Every fill is a
  real print with `ts >= decision + 10 s`, at THAT print's price. The slippage is whatever the tape shows. No fill
  is ever at a price the tape did not print for that side.
- **Entry (always a taker BUY):** the first buyable print for o at or after `t_signal + 10 s`, at most 600 s after
  the signal and before the market's entry deadline (`core.taker_buy_index`). If there is none, the entry is
  "missed" (counted), and the market accepts a new signal 600 s later.
- **Watching an open position:** every print strictly after the entry fill's second and strictly before the time
  stop.
  - **Stop loss:** a print of o at or below `entry - sl` triggers it. It exits as a taker SELL at the first
    sellable print at or after the trigger + 10 s, at that print's price, however far below the stop.
  - **Take profit (taker variant):** a print of o at or above the target triggers it. It exits the same way, at
    the next sellable print 10 s later.
  - If the stop and the take profit trigger on the same print, the stop wins.
  - A triggered exit is worked until it fills. If it never finds a bid before `hard_end`, the position settles
    (reason `sl->settle` / `tp->settle`).
- **Take profit (maker variant):** a resting limit SELL posted at entry fill + 10 s at `L` = the target known then.
  - It fills only on a TRADE-THROUGH: a buyable print STRICTLY above `L`, once the buyable size at or above `L`
    since posting covers our contracts (lab 4 Amendment 4's size rule, mirrored).
  - A print at exactly `L` never fills it. It fills at `L` (`core.maker_sell_index`).
  - It is cancelled when the stop triggers or the time stop arrives. The stop and the time stop stay taker legs.
- **The fair cap (W1, W2):** the target is `min(entry + tp, fair)` while the fair known at that print is above the
  entry price; otherwise it is `entry + tp`. ("Take profit at entry + tp or when the price reaches the fair".)
- **Time stop** = `min(entry fill + hold_s, the market's end_t)`:
  - at a `hold_s` stop, or an `end_t` stop in mode `next`: a taker SELL at the first sellable print at or after the
    stop + 10 s;
  - mode `last_before` (W1's scheduled start): the LAST sellable print in `[entry fill + 10 s, start)`. If there is
    none, the position sells at the first sellable print after the start, flagged `late_stop` and reported;
  - mode `settle`: hold to settlement.
  - A market's `end_t` stop or a settlement ends that market's trading in the cell. A `hold_s` stop does not.
- **Every open position is closed** by an exit, its time stop, or settlement (`shares x payout`, no fee).
- **Size and walking:** $20 per position, `contracts = 20 / entry price`. One position per market at a time. A new
  signal counts only strictly after the previous exit fill. A signal counts only inside the market's entry
  windows, with the bought outcome's signal-print price inside the hypothesis's band (`core.walk`).
- **Fees, per leg** (`contracts x rate x p x (1 - p)`):
  - `us`: Polymarket US taker 0.0695 on every taker leg, maker legs 0 (VENUES.md). **This is the case that
    selects.**
  - `com`: polymarket.com's family rate (sports 0.05, crypto 0.07, politics / finance / mentions / tech 0.04,
    culture / economics / weather 0.05, zero-fee families 0) on taker legs, maker 0. A reading.
  - `stress`: max(0.0695, family rate) on EVERY leg, maker legs included. It must stay positive (§7).
  - For sports the polymarket.com fee is the lower one, so the US fee is already the harsher case there. For crypto
    the family rate, 0.07, is higher, and the stress column uses it.
- **Known limits:**
  - The tape is polymarket.com, not Polymarket US: its tick is 0.01 in the middle of the price range, against
    0.001 on the US venue, and its books are its own.
  - A taker fill takes the whole $20 at one print's price whatever that print's size (lab 4's convention). The
    reported mean entry price and the share of entries whose print was smaller than our contracts show how much
    that assumption carries.

## 5. Hypotheses and grids (FIXED)

Cell keys: `<entry>|tp<tp>|sl<sl|none>|t<stop>|<taker|maker>`. Every cell exists in both variants. The **taker**
variant takes profit as a taker. The **maker** variant takes profit with a resting order; its stop and time stop
are still taker legs. Both variants are selectable. Each hypothesis also has **reference cells**: the same first
entry per market, held to settlement. They are reported only, never selectable, and counted as trials.

### W1: sports pre-game convergence to Pinnacle (`research/lab7/W1/`)

- **Universe:** lab 6's matched games (`research/lab6/run.py load_matched`). Their sides are each market's two
  outcomes; a soccer market's Yes and No are its two outcomes. Settlement is at the side's final price
  (1 / 0 / 0.5). Lab 6's split. Tapes come from lab 4's cache.
- **Fair:** `fair[o, i]` = the side's multiplicative no-vig fair (lab 6's declared method, `side_fair`), from the
  last Pinnacle snapshot at or before the print, strictly before the start and at most 30 minutes old
  (lab 6 `snapshot_index`). It is NaN otherwise, and that fair also drives the exit cap. Only that snapshot's
  fair, never a later one.
- **Cutoff:** the earlier of Pinnacle's commence and Polymarket's gameStartTime, as in lab 6.
- **Entry windows:** the instants with a usable snapshot inside `[commence - 24 h, cutoff)`: the union over
  snapshots of `[snap, snap + 30 min)`.
- **Signal:** `core.gap_signals(tape, fair, m)`. A buyable print for o at a price at least `m` below o's fair.
  Price band 0.15-0.85.
- **Grid:** m in {0.02, 0.03, 0.05} x tp in {0.02, 0.03, 0.05} (fair cap on) x sl in {0.03, 0.05, none} x
  {taker, maker}: **54 cells**.
- **Time stop:** the cutoff, mode `last_before` (sell at the last sellable print before the start). No `hold_s`.
- **Fill bounds:** entry deadline = the cutoff; `hard_end` = the market's closedTime.
- **References:** `hold|m<m>`, the first entry per market held to settlement (lab 6 H1's question with lab 7's
  entry): **3 cells**.
- **Events:** the game. **Rate (com):** lab 4's family rate.
- **Extra readings:** by league; closing-line value of the entries (lab 6 H2: closing fair - entry price).

### W2: crypto up / down convergence to Binance spot (`research/lab7/W2/`)

- **Universe:** lab 5's catalogue (`research/lab5/run.py catalogue`, `universe`). Window contracts of kind 5m,
  15m and 1h on BTC / ETH / SOL / XRP; binary, one winner, at least 50 fills; Chainlink windows need
  `priceToBeat`. Spot is Binance 1 s klines (`$SCRATCH/lab5/spot`). Settlement is the venue's outcome.
- **Fair:** `fair[o, i]` = lab 5's `q_event` model probability of o, with:
  - the decision time = the print's own timestamp (spot read from candles closed by then; the fill is 10 s or more
    later);
  - the 1 h realized-variance window (lab 5 S2's primary);
  - Chainlink basis `sigma_b = 7.54e-5` from `research/lab5/structure.json`, fixed for every split;
  - NaN where lab 5's model is undefined.
- **Entry windows:** `[reference public, time stop)`. The time stop is 60 s before the window ends for 5m and
  15m windows, and 300 s before for 1h windows.
- **Signal:** `core.gap_signals(tape, fair, m)`. **Price band 0.10-0.90:** an architect's parameter, so the largest
  take profit (8c) fits below 0.99 and the near-decided last seconds (prices at 0.99 / 0.01) are not traded.
- **Grid:** m in {0.03, 0.05, 0.08} x tp in {0.03, 0.05, 0.08} (fair cap on) x sl in {0.05, 0.10, none} x
  {taker, maker}: **54 cells**.
- **Time stop:** mode `next` at the window's time stop. A sell fills at the first sellable print at or after it
  + 10 s and before the window ends; if there is none, the position settles.
- **Fill bounds:** entry deadline = the time stop; `hard_end` = min(window end, closedTime).
- **References:** `hold|m<m>`: **3 cells**.
- **Events:** the UTC hour of the window's end (lab 5's cluster: windows in the same hour ride one price path).
- **Rate (com):** 0.07. **Breakdown:** 5m / 15m / 1h, and by symbol.

### W3: sports in-play swings, price action only (`research/lab7/W3/`)

- **Universe:** lab 4 P6's game-winner markets (`sportsMarketType == moneyline`; `p6_meta.parquet`, P6
  `with_game_facts`):
  - sport not "other"; at least 50 fills;
  - start = the event's `startTime` (else `gameStartTime`);
  - end = Gamma's `finishedTimestamp` when valid (start < end <= closedTime).
- **Only games with a recorded end decide.** Fallback-end games, the ones P6 had to time roughly (all esports,
  among others), are reported apart as a breakdown. They are never a decision input.
- **In play:** `start <= t < end`. The entry window is `[start + y, end)`, so the whole lookback is in play.
- **Signal:** `core.swing_signals(tape, x, y, k=5, direction)`, using outcome 0's last print price (any side):
  - MOMENTUM buys the outcome that rose by at least x since the last print at or before `t - y`, with at least 5
    prints since;
  - FADE buys the outcome that fell by at least x.
  - Either outcome may be bought: either team, Yes or No.
  - Price band 0.20-0.80 for the bought outcome at the signal print.
- **Grid:** direction {mom, fade} x x in {0.05, 0.10} x y in {2, 5} min x tp in {0.03, 0.05, 0.10} x sl in
  {0.05, 0.10} x time stop {15 min, 45 min, game end} x {taker, maker}: **288 cells**.
- **Time stops:** for 15 / 45 min, `hold_s` = 900 / 2700 s. "Game end" means watch until the recorded end, then
  hold to settlement (mode `settle`); a `hold_s` stop that would fall after the end also becomes the end.
- **Fill bounds:** entry deadline = the end; `hard_end` = closedTime.
- **References:** `hold|<dir>|x<x>|y<y>m`: **8 cells**.
- **Events:** the game (event slug). **Rate (com):** lab 4's family rate.
- **Breakdowns:** sport; the side bought (Yes or first-listed team vs the other). Polymarket US quotes every order
  on YES, so a pass that rests on No buys needs the desk to confirm that it can sell YES to open.

### W4: non-sports swings over hours (`research/lab7/W4/`)

- **Universe:** lab 4's markets in fee families politics, culture, economics, weather, mentions, tech and finance
  (lab 4 `fee_family`). Binary, one winner, at least 50 fills.
- **Market end:** min(endDate, closedTime), or closedTime when endDate is missing.
- **Entry window:** `[first print + y, market end)`.
- **Signal:** `core.swing_signals(tape, x, y, k=10, direction)`, as W3. Price band 0.15-0.85.
- **Grid:** direction {mom, fade} x x in {0.05, 0.10} x y in {60, 240} min x tp in {0.03, 0.05, 0.10} x sl in
  {0.05, 0.10} x time stop {24 h, market end} x {taker, maker}: **192 cells**.
- **Time stops:** for 24 h, `hold_s` = 86,400 s. "Market end" means watch until the market end, then hold to
  settlement.
- **Fill bounds:** entry deadline = the market end; `hard_end` = closedTime.
- **References:** **8 cells**.
- **Events:** the event slug (a weather event's brackets, or a winner field, are one draw).
- **Breakdown:** family.

**Totals on TRAIN:** 588 selectable cells + 22 reference cells = **610 trials**. Then VAL at most 4 and TEST at
most 4. Every one goes into `research/lab7/trials.json` (§9).

## 6. Readings (every cell; `core.summarize`, `core.risk_book`)

- **Round trips:**
  - n round trips, events, missed entries, round trips per day, win rate (net > 0 after the US fee);
  - mean net per $ at risk under the US fee, with its **event-bootstrap CI95** (B = 2000; lab 4's
    `event_bootstrap_ci`);
  - mean net under the polymarket.com and stress fees; the rule-of-three worst case;
  - exit mix (tp / fair / sl / time / settle, and their `->settle` variants), late time stops, median hold time;
  - cents per contract on wins and on losses, the break-even win rate they imply, mean entry price.
- **Risk book (the owner's "really good risk management"; a reading, never a selector):**
  - max positions open at once across the cell, and the capital that locks ($20 each);
  - a **$10 daily loss stop** overlay: an entry is skipped once the P&L realized earlier that UTC day is at or
    below -$10. The overlay reports n, mean net, total $ and the number of days the stop fired;
  - max drawdown of realized P&L in exit order; worst and best day;
  - daily Sharpe over every calendar day of the split (days with no exit count as 0, x sqrt(365));
  - longest losing streak; worst round trip.
- **The hypothesis's breakdowns (§5)** and the reference cells (would holding to settlement have done better than
  trading out?).

## 7. The bar, selection, VAL and TEST (FIXED; `core.bar_checks`, `core.bar`, `core.select_one`)

A cell **passes** only if ALL of these hold:

1. n >= 100 round trips;
2. mean net per $ (US fee) > 0;
3. event-bootstrap CI95 lower bound > 0;
4. mean net per $ under the **stress** fee > 0;
5. lab 4's loss guards: at least one losing round trip, and with fewer than five, the rule-of-three worst case
   must be positive;
6. it beats the **random-entry placebo**: the real mean must be strictly above the placebo's 95th percentile.

**The placebo** (`core.placebo_matrix`, `core.placebo_reading`):

- For every real round trip, one counterpart per draw:
  - the same market and the same exit rule (tp, sl, variant, time stops, fair cap);
  - a decision time drawn uniformly from that market's entry windows;
  - an outcome drawn 50 / 50.
- If the drawn outcome's last price at that time is outside the band, or the entry misses, the counterpart is
  redrawn, up to 25 tries; if all 25 fail it is dropped (the drop share is reported).
- 200 draws; the per-draw mean of net per $; seed `core.placebo_seed(hyp, cell, split)`.
- **Why the side is drawn too:** copying the real side would carry the signal's hindsight into counterparts drawn
  before the signal (buying the team that later rose).
- **What it catches:** take-profit / stop-loss shapes, bands and time stops that would make money (or a high win
  rate) for ANY entry. It is computed for every cell that clears conditions 1-5 (it cannot rescue a cell that
  fails them); specialists may compute it for more cells as readings.

**TRAIN** selects at most ONE cell per hypothesis: among selectable cells that pass, the highest CI95 lower bound
(ties: higher mean, then the key). If none passes, the verdict is **NO EDGE** for that hypothesis, and VAL and
TEST are not run.

**VAL:** the selected cell, unchanged, must pass the same full bar on VAL, with its own VAL placebo. If it fails:
FAIL on VAL.

**TEST:** only after VAL passes and a review. One look, the same bar: `LAB7_ALLOW_TEST=1`, refused a second time.

**Verdicts per hypothesis:** NO_EDGE_TRAIN, FAIL_VAL, or SELECTED_ON_VAL; then PASS_TEST or FAIL_TEST.

## 8. What a pass would and would not mean

A TEST pass says that, over these months, on polymarket.com's tapes, a specialist's entries plus its take
profit / stop / time stop made money after Polymarket US's fee, a 10 s lag and real-print slippage. They also did
better than random entries with the same exits. It means only **"ready for pretend-money trading on the live
desk"**:

- a paper desk on the Polymarket US public gateway, at that venue's own prices;
- for long enough to reach 100 round trips;
- the owner decides anything after that.

It does not say the next months will repeat, that the US books had depth for $20 at those prices, or that the
venue offers every side used. **Never real money by itself.**

## 9. Trial ledger and outputs

- Every cell evaluated on any split is one trial in **`research/lab7/trials.json`** (`core.record_runs`). It is
  an upsert keyed on (lab, hyp, cell, split, stage), so a re-run replaces its own row and never inflates the
  count. The read-modify-write holds a file lock (four specialists share the file) and the file is replaced
  atomically.
  - Fields: hyp, cell, split, stage, kind (`selectable` / `reference`), n, mean_net_us, ci95, mean_net_stress,
    passes, and the PLAN.md / PREREG.md sha256 values.
- The cross-lab count (labs 2-7, each ledger read in its own format, `core.trials_count`; 3,051 before lab 7) is
  printed in every result file. Lab 7 writes no other lab's ledger.
- **Per hypothesis:** `research/lab7/<W>/run.py --stage train|val|test` writes `<W>/<stage>.json` and
  `<W>/<stage>.md`, with the decision first in plain words, then the tables.
- `research/lab7/RESULTS.md` is regenerated from the result files, never by hand.
- Per-trade files: only for the selected, VAL and TEST cells, as zstd parquet under `$SCRATCH/lab7/` (outside
  git), under 100 MB in all.

## 10. Rules for the specialists

- **No change to this plan, `core.py` or the grids after any return is read.** A specialist may add
  `research/lab7/<W>/PREREG.md` with implementation details this plan leaves open (exact column choices, how a
  window is built from lab 5's contract fields, edge cases), but never a grid value, fee, band, bar, split or
  execution rule. It must be written, with its sha256 recorded, BEFORE any return of that hypothesis is computed.
- A bug found in `core.py` is fixed with a failing test first, and noted as a dated amendment here. If the fix
  comes after a return was read, the note says so.
- **Engineering:**
  - Tapes load per market. Run at most 4 worker processes (fork) with one market in memory each. W2's spot arrays
    are loaded once, before forking.
  - Signals are computed once per entry-parameter set, then every exit cell is walked on them.
  - Free disk is under 9 GB, so no large intermediate files are written.
- Tests per hypothesis go in `research/lab7/tests/test_<w>.py`: the market builder, the windows and the fair
  alignment (no lookahead). Run them with `python -m pytest research/lab7/tests -q` from the lab directory.

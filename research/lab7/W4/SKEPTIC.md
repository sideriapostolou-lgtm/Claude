# Lab 7 W4: adversarial skeptic's review of the TRAIN result

Written 2026-10-11 ~01:15 UTC by the W4 skeptic. It reviews `W4/train.json` (run 2026-10-10 23:37 UTC, W4 PREREG
sha256 `db87021b...`, PLAN sha256 `c6f62ddf...`). It changes no specialist file and adds no trial to `trials.json`:
the count was 3,365 across labs 2-7 after the W4 run, and W3's TRAIN rows, written later, bring it to 3,661. It
never reads VAL or TEST. Everything here was written AFTER the TRAIN result was read, so the extra readings below
are post-hoc. They decide nothing.

**Verdict: the NO EDGE result stands.** No W4 cell passed, so there is no pass to refute. I tried to break the
NO EDGE result instead, looking for a bug that could make a real edge look like a loss. I rebuilt trades from the
raw files with my own code: 2,245 trips over 8 cells, then the whole best cell and its mirror twin over every
TRAIN market. They match the specialist's engine exactly. The data conventions also check out: the trade side, the
winners and the fee formula. Then I gave every one of the 192 rules perfect execution. That means no spread, no
delay, no missed entry, and every exit exactly at its level. Even then, none of them makes money after the
Polymarket US fee.

## In plain words (for the owner)

I checked this desk's homework by redoing it from scratch, with my own program, on the raw trade records. I got
the same trades, the same prices, the same fees and the same losses, down to the last cent.

Then I asked the friendliest question I could. Suppose the specialist were perfect: it buys at exactly the price
that triggered the signal, with no delay, and always sells at exactly +3c, +5c or +10c, or stops out at exactly -5c
or -10c. Would it make money then? It would not. The best of the 192 versions still loses about 2.6 cents per
dollar, and the fee alone does it.

The price swings do carry a little information: after a rise, prices keep drifting up by about 1 to 2 cents. That
drift is mostly gone within 10 minutes, and buying at the asking price already gives it away. Each trade also pays
about 3.4 cents per contract in fees, buying and selling. So "get in at 50, get out at 55" cannot work on these
markets. The skill it needs (being right about 85 % of the time near 50c) is not in the price swings. Good risk
management limits the losses, but it cannot turn them into profits.

## 1. What I re-derived, independently

My scripts sit outside git, in the session scratchpad (`w4skeptic/`):

- `indep.py`: my simulator. Pure-Python loops written from PLAN §4 / §5 W4 and W4 PREREG. It does not call
  `core.simulate`, `core.walk`, `core.swing_signals` or `core.Tape`. It reads `trades/<id>.parquet` raw and builds
  the sides, prices, signal, entry, take profit (taker and maker), stop, time stop, settlement and fees itself.
- `compare.py`: it runs `indep.py` side by side with the specialist's `run.market_trips` (which uses `core`).
- `full_best.py`: the best cell and its fade twin over every TRAIN market, through `indep.py`, with my own event
  bootstrap (a different seed).
- `twenty.py`: 20 trades rebuilt by hand from the raw rows with pandas filters, a third path.
- `conv.py`, `markout.py`, `markout_fill.py`, `ideal.py`, `ideal_after_end.py`: the readings in §3-§4.

The only input I take from the specialist is `run.universe("train")`. It is lab 4's eligible markets in the seven
families, which I re-counted at 3,122 (weather 1,548, culture 662, politics 317, finance 305, tech 161, economics 93,
mentions 36), matching PLAN §3.

### Trip-by-trip agreement

| check | result |
|---|---|
| 56 random TRAIN markets plus the SPY market (3044420), 8 cells: `mom\|x0.05\|y240m\|tp0.1\|sl0.1\|t24h\|taker`, `fade\|x0.1\|y60m\|tp0.05\|sl0.05\|tend\|maker`, `mom\|x0.1\|y60m\|tp0.03\|sl0.1\|tend\|taker`, `fade\|x0.05\|y240m\|tp0.1\|sl0.05\|t24h\|maker`, `mom\|x0.05\|y60m\|tp0.05\|sl0.05\|t24h\|maker`, `fade\|x0.05\|y60m\|tp0.03\|sl0.05\|t24h\|taker`, and the references `hold\|mom\|x0.05\|y240m`, `hold\|fade\|x0.1\|y240m` | 2,245 trips: outcome, signal time, entry time and price, exit time and price, reason, exit leg, fee and P&L all identical; 0 mismatches; missed-entry counts equal in every (market, cell) |
| `W4/tests/test_w4.py` and `tests/test_core.py` | 44 passed |

### The best cell and its mirror twin, over every TRAIN market

| quantity | specialist (`train.json`) | skeptic (`indep.py`) |
|---|---|---|
| `mom\|x0.05\|y240m\|tp0.1\|sl0.1\|t24h\|taker`: n / missed / events | 16,301 / 8,134 / 1,016 | 16,301 / 8,134 / 1,016 |
| mean net per $ (US fee), CI95 | -0.03961, [-0.0877, +0.0532] | -0.03961, [-0.0878, +0.0532] (own bootstrap, other seed) |
| gross (no fee), win rate | +0.02157, 43.67 % | +0.02157, 43.67 % |
| in-band entries only (0.15 <= fill <= 0.85) | n 15,024, -0.0865, [-0.0931, -0.0797] (`train_diag`) | n 15,024, -0.08646, [-0.0933, -0.0802]; gross -0.0249 |
| largest trip | +$13,699.21 (SPY, 0.001 fill) | +$13,699.21, same trip |
| exit mix | sl 49.2 %, tp 43.8 %, time 3.8 %, settle 3.2 % | identical |
| `fade\|x0.05\|y240m\|tp0.1\|sl0.1\|t24h\|taker`: n, mean, CI95 | 16,425, -0.10329, [-0.1108, -0.0953] | 16,425, -0.10329, [-0.1106, -0.0959] |

### Data conventions (where a silent sign error would hide)

- **Taker side.** Over 400 random TRAIN markets, I took every pair of adjacent prints within 30 s on opposite sides
  (45,837 pairs). The "buyable for outcome 0" print sits ABOVE the "sellable for outcome 0" print by +1.52c on
  average (median +0.60c); it is above in 84.9 % of pairs and below in 10.2 %. The tape's `side` is therefore the
  taker's side. Entries really pay the ask and exits really hit the bid, as PLAN §4 intends. If the side were
  inverted, the simulator would buy at the bid and sell at the ask: it would flatter the rule, not hide an edge.
- **Winners.** In the 376 of those 400 markets whose last 20 prints are decided (above 0.8 or below 0.2), lab 4's
  `winner_index` agrees with the tape every time (376 / 376). Payouts are correct.
- **Units.** `end_date` and `closed_time` are both epoch seconds, so `min(endDate, closedTime)` is a real minimum.

## 2. Twenty trades re-derived by hand from the raw rows

`twenty.py` re-reads each market's parquet. With plain pandas filters on `ts`, `side`, `outcome_index` and `price`,
it checks five things:

1. the reference print (the last at or before t - y) and the signal print: the move is at least x, with at least
   10 prints since, in the right direction, inside the band and the window;
2. the entry is the first ask-side print for the bought outcome in [t + 10 s, t + 600 s], before the market end;
3. the trigger is the first print strictly after the entry second, before the time stop (the stop wins ties). For a
   maker cell, the fill is the first ask-side print strictly above the limit once the cumulative ask-side size at
   or above the limit covers our contracts;
4. the exit is the first bid-side print at least 10 s after the trigger, before closedTime; otherwise the trade
   settles at lab 4's winner;
5. the fee is `contracts x 0.0695 x p x (1 - p)` on each taker leg (0 on a maker or settlement leg), and the P&L
   is `contracts x exit - 20 - fee`.

All 20 pass every check, and the P&L equals the engine's to 1e-9.

| # | market | family | cell | bought | ref -> signal | entry (print size, delay) | what happened (raw rows) | exit | fee $ | P&L $ (mine = core) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3044420 | finance | `mom\|x0.1\|y60m\|tp0.03\|sl0.1\|tend\|taker` | o0 | 0.010 -> 0.159 | 0.001 (size 40, +477s) | trigger tp print 0.592 @+261.4min; exit bid-side print 0.701 size 10046 | tp | 292.95 | 13699.21 = 13699.21 |
| 2 | 3325425 | weather | `hold\|mom\|x0.05\|y240m` | o0 | 0.150 -> 0.317 | 0.320 (size 394, +75s) | held to settlement: 0 | settle | 0.95 | -20.95 = -20.95 |
| 3 | 2877471 | culture | `hold\|fade\|x0.1\|y240m` | o1 | 0.650 -> 0.550 | 0.550 (size 103, +11s) | held to settlement: 1 | settle | 0.63 | 15.74 = 15.74 |
| 4 | 2749909 | weather | `fade\|x0.05\|y240m\|tp0.1\|sl0.05\|t24h\|maker` | o1 | 0.620 -> 0.570 | 0.580 (size 10, +21s) | maker 0.680 unfilled, no stop; settles at 1 | settle | 0.58 | 13.90 = 13.90 |
| 5 | 2825873 | weather | `mom\|x0.05\|y240m\|tp0.1\|sl0.1\|t24h\|taker` | o0 | 0.160 -> 0.267 | 0.280 (size 58, +39s) | trigger sl print 0.180 @+16.4min; exit bid-side print 0.180 size 5 | sl | 1.73 | -8.88 = -8.88 |
| 6 | 2921698 | finance | `mom\|x0.05\|y60m\|tp0.05\|sl0.05\|t24h\|maker` | o0 | 0.520 -> 0.630 | 0.650 (size 200, +30s) | maker 0.700 never traded through; stop print 0.600; exit bid-side print 0.580 | sl | 1.01 | -3.16 = -3.16 |
| 7 | 2877471 | culture | `mom\|x0.05\|y60m\|tp0.05\|sl0.05\|t24h\|maker` | o0 | 0.670 -> 0.750 | 0.826 (size 37, +37s) | maker 0.876 never traded through; stop print 0.760; exit bid-side print 0.750 | sl | 0.56 | -2.39 = -2.39 |
| 8 | 2980868 | weather | `mom\|x0.1\|y60m\|tp0.03\|sl0.1\|tend\|taker` | o0 | 0.544 -> 0.650 | 0.650 (size 2, +12s) | trigger sl print 0.550 @+235.4min; exit bid-side print 0.542 size 30 | sl | 1.02 | -4.36 = -4.36 |
| 9 | 2877471 | culture | `mom\|x0.05\|y60m\|tp0.05\|sl0.05\|t24h\|maker` | o1 | 0.420 -> 0.810 | 0.780 (size 47, +27s) | maker 0.830 never traded through; stop print 0.627; exit bid-side print 0.780 | sl | 0.61 | -0.61 = -0.61 |
| 10 | 3095840 | culture | `mom\|x0.05\|y240m\|tp0.1\|sl0.1\|t24h\|taker` | o0 | 0.160 -> 0.210 | 0.220 (size 182, +53s) | no trigger in 24 h; time-stop exit at bid-side print 0.180 | time | 2.02 | -5.65 = -5.65 |
| 11 | 2821882 | politics | `mom\|x0.05\|y60m\|tp0.05\|sl0.05\|t24h\|maker` | o0 | 0.090 -> 0.170 | 0.180 (size 10, +250s) | maker 0.230 unfilled, no stop in 24 h; time exit bid-side 0.170 | time | 2.23 | -3.34 = -3.34 |
| 12 | 2921698 | finance | `mom\|x0.05\|y60m\|tp0.05\|sl0.05\|t24h\|maker` | o1 | 0.260 -> 0.400 | 0.420 (size 25, +79s) | maker sell at 0.470 filled by ask-side print 0.490 (cum size 152 >= 48) | tp | 0.81 | 1.57 = 1.57 |
| 13 | 3327331 | weather | `fade\|x0.05\|y240m\|tp0.1\|sl0.05\|t24h\|maker` | o0 | 0.430 -> 0.340 | 0.330 (size 5, +297s) | maker sell at 0.430 filled by ask-side print 0.440 (cum size 65 >= 61) | tp | 0.93 | 5.13 = 5.13 |
| 14 | 3146691 | weather | `fade\|x0.05\|y240m\|tp0.1\|sl0.05\|t24h\|maker` | o1 | 0.590 -> 0.498 | 0.570 (size 6, +41s) | maker sell at 0.670 filled by ask-side print 0.700 (cum size 39 >= 35) | tp | 0.60 | 2.91 = 2.91 |
| 15 | 2825873 | weather | `mom\|x0.05\|y60m\|tp0.05\|sl0.05\|t24h\|maker` | o0 | 0.170 -> 0.223 | 0.249 (size 60, +85s) | maker sell at 0.299 filled by ask-side print 0.300 (cum size 84 >= 80) | tp | 1.04 | 2.98 = 2.98 |
| 16 | 2921698 | finance | `fade\|x0.05\|y60m\|tp0.03\|sl0.05\|t24h\|taker` | o0 | 0.750 -> 0.570 | 0.520 (size 200, +217s) | trigger tp print 0.580 @+0.0min; exit bid-side print 0.500 size 20 | tp | 1.34 | -2.10 = -2.10 |
| 17 | 3507692 | weather | `fade\|x0.05\|y60m\|tp0.03\|sl0.05\|t24h\|taker` | o0 | 0.230 -> 0.170 | 0.170 (size 4, +10s) | trigger tp print 0.200 @+20.3min; exit bid-side print 0.280 size 5 | tp | 2.80 | 10.14 = 10.14 |
| 18 | 2701882 | culture | `fade\|x0.05\|y60m\|tp0.03\|sl0.05\|t24h\|taker` | o1 | 0.820 -> 0.770 | 0.770 (size 4, +171s) | trigger tp print 0.800 @+44.6min; exit bid-side print 0.790 size 49 | tp | 0.62 | -0.10 = -0.10 |
| 19 | 3323646 | culture | `mom\|x0.05\|y240m\|tp0.1\|sl0.1\|t24h\|taker` | o1 | 0.430 -> 0.510 | 0.520 (size 100, +115s) | trigger tp print 0.709 @+174.3min; exit bid-side print 0.600 size 58 | tp | 1.31 | 1.77 = 1.77 |
| 20 | 3044420 | finance | `mom\|x0.05\|y240m\|tp0.1\|sl0.1\|t24h\|taker` | o0 | 0.001 -> 0.700 | 0.050 (size 7, +74s) | trigger tp print 0.900; no bid-side print before closedTime, settles at 0 | tp->settle | 1.32 | -21.32 = -21.32 |

What the sample shows about the execution model (all per PLAN §4, none of it a W4 bug):

- **Trade 1** is the specialist's "fill that could not happen". After a 0.01 -> 0.159 rise, the first ask-side print
  for outcome 0 came 477 s later at 0.001, a 40-contract print. The whole $20 buys 20,000 contracts there, and they
  are later sold into a 10,046-contract bid at 0.701. Trade 20 is the same decided market (SPY had already opened)
  printing stray prices both ways.
- **Trade 16:** a "take profit" that loses. The trigger is any print at the target (here an ask-side print at
  0.58), and the sale goes to the next bid (0.50, under the 0.52 entry).
- **Trade 9:** a stop triggered by one stray print (0.627) that then sells at the entry price (0.78).

These are the plan's conventions. §3 below shows that removing them all, in the rule's favour, still leaves no edge.

## 3. Could a bug have hidden an edge? The checklist

| suspicion | what I checked | finding |
|---|---|---|
| wrong sign (direction or P&L) | trips 1-20: momentum bought the outcome that rose (e.g. #5 0.160 -> 0.267, bought it), fade bought the one that fell (e.g. #4 outcome 1 0.620 -> 0.570, bought outcome 1); P&L = contracts x exit - 20 - fee | correct |
| fees charged twice | my fee formula equals the engine's on 2,245 + 32,726 trips; the best cell's mean fee is 0.0612 per $, which is two legs of 0.0695 x p(1-p) / p at a mean entry of 0.548 (about 0.031 each); maker and settlement legs pay 0; the stress fee equals the US fee on taker legs because every W4 family rate (0.04 / 0.05) is below 0.0695 | charged once per leg, as the plan says |
| fills stricter than the plan | the engine matches my independent reading of PLAN §4 exactly (entry window [t + 10 s, t + 600 s], exits at the next bid-side print 10 s later, the maker trade-through and size rule, the 24 h stop, settlement at the market end) | not stricter than the plan; and §4.1 removes every execution friction at once |
| a filter that drops winners | band on the signal print (PLAN); 161 markets under 50 fills (PLAN); families `none` / `zero` / `geopolitics` / `unknown` excluded (PLAN); 12.0 % of the universe's prints fall after `min(endDate, closedTime)` and are not entry candidates (PLAN; 78 % of them are weather, whose endDate is 12:00 UTC on the day while the median weather market closes 10.4 h later); missed entries (33 % for the best cell) | all pre-registered. §4.1 also includes every missed entry, and §4.3 trades the excluded post-endDate window; neither shows an edge |
| a broken join | universe row -> tape by id -> event slug -> winner: my run, reading each market by id, reproduces n, missed, events, mean and gross of the best cell exactly; the winners agree with the tape (376 / 376) | none |
| bootstrap / bar | my own event bootstrap reproduces the CI bounds within 0.0006; 0 of 192 cells have mean > 0, a CI lower bound > 0 or stress > 0, so no cell reaches the placebo; `core.select_one` returns None | NO_EDGE_TRAIN is the correct verdict |
| ledger | 200 W4 TRAIN rows (192 selectable, 8 reference), 0 passes, all with PREREG sha256 `db87021b264c`; PREREG committed in 1e22926 (2026-10-10 21:44 UTC) before the TRAIN run (23:37 UTC; `train.json` committed in f5a7583); `trials_count()` was 3,365 after the W4 run | in order |

## 4. Is NO EDGE sound? Three post-hoc readings (they decide nothing and add no trial)

### 4.1 Every cell with frictionless execution: still 0 of 192 positive

`ideal.py` re-walks all 192 selectable cells on every TRAIN market with the rule's best possible execution:

- the entry fills at the signal print's own price at the signal instant (no 10 s delay, no spread, never missed,
  so no fill outside the band);
- the take profit and the stop fill exactly AT their level when any print touches it (no gap, no bid);
- the 24 h stop fills at the last print's price.

Only the Polymarket US fee remains: taker on the entry, stop and time legs; on the take-profit leg, taker for the
taker cells and free for the maker cells.

- **0 of 192 cells have a positive mean after the fee.** The best is `fade|x0.1|y60m|tp0.1|sl0.1|tend|maker`:
  n 16,859, gross +0.0260, net **-0.0262** per $, CI95 [-0.0327, -0.0197]. The worst is about -0.090.
- Before any fee, 64 cells are positive. Most of them (52 of 64) are fade cells, because entering at the signal print
  often gives fade a free half-spread. Its signal print is the low print, and it sits on the bid more often than
  not: 58 % of fade signal prints, against 42 % for momentum, in a 600-market check of `x0.1|y60m`. The average
  gross is fade +0.0016 and momentum -0.0113 per $.

So the losses come from the fee itself, at about 1.7c per leg near 50c (PLAN §2). The spread, the delay, the
one-print fills and the trigger conventions only make them worse. No execution bug, however large, could hide an
edge here.

### 4.2 What the signal knows: a small drift, paid away at entry

`markout.py` and `markout_fill.py` take one signal per market per hour (inside the window and the band) and follow
the bought outcome's mid-price proxy. The proxy is the mean of the last ask-side and the last bid-side print. The
table is in cents per contract, with event-clustered CI95. "fill premium" is the fill price minus the mid at the
signal. "after fill" is the mid drift after the fill. "taker at h" is the bid proxy at fill + h minus the fill price:
a taker time stop at h, before fees.

| rule | n | drift from the signal, 10 min / 1 h / 4 h | fill premium | after fill, 1 h | taker at 10 min / 1 h / 4 h / 24 h |
|---|---|---|---|---|---|
| mom x0.05 y240m | 16,293 | +0.64 / +0.93 / +0.79 | +1.96 [+1.85, +2.10] | +1.45 | -2.42 / -1.75 / -1.72 / -1.60 |
| fade x0.05 y240m | 15,960 | -0.64 / -0.93 / -0.79 (mirror) | -0.06 | +0.46 | -2.24 / -2.08 / -1.55 / -1.44 |
| mom x0.1 y60m | 6,008 | +1.70 / +1.78 / +2.06 | +3.34 [+3.13, +3.55] | +1.72 | -3.52 / -2.84 / -2.05 / -1.93 |
| fade x0.1 y60m | 6,075 | -1.70 / -1.78 / -2.06 (mirror) | -0.96 | +1.09 | -2.82 / -2.24 / -2.33 / -1.90 |

The drift from the signal counts the signals before any fill (n 28,355 and 7,743), so it is wider than the
filled n in the table.

How to read it:

- Momentum is real but small: +1 to +2c, mostly inside the first 10 minutes. Buying at the ask 10 s or more later
  already costs more than that (+2.0c to +3.3c above the signal mid).
- After the fill, a taker round trip at any horizon from 10 minutes to 24 hours loses 1.4c to 3.5c per contract
  BEFORE fees, for every rule. The fees then add about 3.4c per contract (two legs at p of about 0.55).
- A take profit or a stop only chooses when to stop on this path, and stopping cannot create the missing 5c. This
  matches the in-band gross of every cell: momentum -2.4c to -7.0c and fade -3.0c to -8.8c per $
  (`train_diag.json`), and it matches the frictionless bound above.
- The small positive "after fill" mid drift for both directions is partly a stale-quote effect in the proxy: right
  after an ask-side fill, the last bid can be old. It does not survive the bid at any horizon.

### 4.3 The excluded post-endDate window does not hide an edge either

The same frictionless bound, with entries allowed only at or after `endDate` and positions run until closedTime
(`ideal_after_end.py`), covers the window that PLAN's market end leaves out, mostly the weather day.

- **0 of 192 cells are positive after the fee.** The best, `fade|x0.1|y60m|tp0.1|sl0.1|tend|maker`, gives n 6,100,
  net -0.0056, CI95 [-0.0162, +0.0049].
- That is under perfect execution. The real spread (about 1.5c on average) and the delay would push it well below
  zero.

## 5. Points for the architect (none changes W4's verdict)

1. **The one-print, full-size fill convention (PLAN §4) needs an amendment for future work.** I agree with the
   specialist's first concern. A $20 fill at any price off one print of any size produces trades like #1 (+$13,699
   off a 40-contract print). Those trades put a fake right tail into the means, the CIs and the best day. W4 is
   not affected: the in-band reading is negative everywhere, and the frictionless bound of §4.1 has no such fills.
   W3, with its fast in-play jumps, is the desk where this artifact could manufacture a false PASS. Its skeptic
   should check for out-of-band fills and for fills far larger than their print. An amendment made now would come
   after returns were read, so it should be labelled as such, or apply only to new hypotheses.
2. **The mirror sentence in the specialist's summary is exact only for the in-band trips.** The specialist wrote
   that momentum and fade both lose before fees (-2.5c to -7c). In the full-sample mirror table of `train.json`,
   42 momentum cells have a positive gross (up to +0.026). All of it comes from out-of-band fills. In-band, every
   cell is negative (momentum -2.4c to -7.0c, fade -3.0c to -8.8c). The "+2.16 before any fee" in the plain words
   of `train.md` is inflated in the same way: the in-band figure is -2.49. The pointer to `train_diag.md` already
   says so.
3. **Two trigger conventions can look odd to a reader:** a take profit triggered by an ask-side print that sells
   at a loss (#16), and a stop triggered by one stray print (#9). They are the plan's rules. §4.1 shows the verdict
   does not depend on them.
4. **The reference cells (held to settlement) are mildly positive per $:** best +0.050, CI95 [-0.0096, +0.106].
   This is not evidence of an edge:
   - they are 8 correlated, non-selectable trials, and every CI includes zero;
   - per contract, the settlement markout from the fill is -0.5c to -1.4c before fees (§4.2, `g_settle`);
   - the per-$ figure leans on cheap entries, which carry the most contracts per $.

   Labs 4 and 6 already tested hold-to-settlement.

## 6. Files

- This review: `research/lab7/W4/SKEPTIC.md` (the only file I added to the repo).
- Scratch (outside git), `w4skeptic/` in the session scratchpad: `indep.py`, `compare.py`, `compared.parquet`
  (2,245 compared trips), `full_best.py`, `full_best.parquet`, `twenty.py`, `twenty.json`, `conv.py`, `markout.py`,
  `markout_fill.py`, `ideal.py`, `ideal_cells.csv`, `ideal_after_end.py`, `ideal_after_end_cells.csv`.

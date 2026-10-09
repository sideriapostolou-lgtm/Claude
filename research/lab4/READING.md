# Lab 4 — reading the TRAIN results (2026-10-09)

`RESULTS.md` is written by `run.py`; this note is the human reading of the same numbers.

Data: 39,644 resolved markets in the TRAIN split (2026-07-01 -> 2026-08-16), tape coverage 100 % (40,350 of
40,350 eligible markets). Trials so far across labs 2-4: 2,873. PLAN.md sha256 6785d8d2b857, Amendments 1-3.

| hypothesis | best-looking selectable cell | mean net per $ at risk | CI95 (event bootstrap) | decision |
|---|---|---|---|---|
| P1 all markets, buy at >= theta before resolution | theta 0.99, H1 | -0.0015 | [-0.0065, +0.0048] | NO EDGE |
| P2 late-game sports | theta 0.99, Hinf | -0.0042 | [-0.0075, -0.0013] | NO EDGE |
| P3 crypto up/down, last minutes | theta 0.99, H1min | +0.0010 | [-0.0037, +0.0058] | NO EDGE |
| P4 non-sports grind (the owner's venue mix) | theta 0.97, H1 | -0.0043 | [-0.0089, +0.0010] | NO EDGE |
| P5 patient bid: rest at the bid, fill only when a seller sweeps through (Amendment 4, read 19:05 UTC) | theta 0.99, H1, at the bid, maker pays the taker fee | -0.0279 | [-0.0349, -0.0214] | NO EDGE |
| C1 control: the longshot side (1 - theta) | theta 0.95, H168 | -0.1647 | [-0.2582, -0.0500] | control only: longshots lose far more |

Every selectable cell has a mean net at or below zero after the venue's taker fee, or a CI that straddles zero
with a negative rule-of-three worst case. The only positive cells in P2 are oracle-timed (they know the game
clock, which no live rule has) and are not selectable. Per PLAN §4 no cell qualifies, so VAL and TEST are not
read.

What it means: buying 95-99c outcomes and holding to resolution returns the quoted price minus fees on
average; the market already prices these events fairly or better, and the taker fee eats the rest. The live
paper desk's first day agrees (its losses were made worse by a rule that read a wide book's ask as a belief;
fixed 2026-10-09, see polydesk.py MAX_SPREAD). The Polymarket desk therefore stays a paper shadow and no real
money follows this rule. Full tables: `P1/train.md` ... `P4/train.md`, `C1/train.md`.

## P5, the patient bid (Amendment 4; TRAIN read 2026-10-09 19:05 UTC)

Pre-registered in PLAN.md Amendment 4 at ~18:45 UTC and committed before the run (4289929, "Amendment 4
pre-registers P5"); PLAN.md sha256 73d556273674 (Amendments 1-4). Same 39,644 TRAIN markets, tape coverage 100 %.
60 cells (3 theta x 5 H x 2 bid offsets x 2 fee assumptions), 30 selectable; trials across labs 2-4 now 2,963
(+60). Full table: `P5/train.md`. VAL and TEST were not run.

**What the fill model assumed.** The tape is taker-side prints (time, price, size, side) with NO book depth, so
the best bid is inferred: the last price a seller hit in the 600 s before the signal, never above the signal ask
minus one tick (tick 0.001), less 0 or 1 tick. The bid is posted 10 s after the signal and rests until the window
ends. It fills only when a later seller prints STRICTLY below it (price priority then guarantees every share at
our level was taken, whatever our place in the queue) and only once sellers at or below our level have sold at
least our 20 / b shares; a print at exactly our price never fills us (queue position unknown; the depth-based
rule could not be applied because the data has no depth). The fill price is our bid. Fees: fee0 (maker pays
nothing, polymarket.com's published schedule; reported only) and feeT (maker pays the family's taker fee, the
stress case; the only selectable cells). Settlement at resolution as P1.

**Power.** The conservative model did not starve the test: 4,198 to 18,778 fills per cell from 16,367 to 39,368
bids posted (fill rates 26 % at theta 0.99 to 50 % at theta 0.95); about 1-2 % of bids were lost to the size
condition. The test is well powered; this is a finding, not a shortage of fills.

| best selectable cell (feeT) | fills / bids | win rate | price paid | ask seen | mean net per $ at risk | CI95 (events) | decision |
|---|---|---|---|---|---|---|---|
| theta 0.99, H1, at the bid | 4,387 / 16,367 (27 %) | 0.951 | 0.976 | 0.990 | -0.0279 | [-0.0349, -0.0214] | NO EDGE |

Every one of the 60 cells has a negative mean net with the whole CI95 below zero. The fee-free twin of the best
cell is -0.0262 [-0.0333, -0.0197], so the fee is not what fails (fee0 and feeT differ by 0.2 to 0.5 cents per
dollar). The best P5 cell loses 2.8 cents per dollar at risk where P1's same cell lost 0.15 cents lifting the ask:
patience made it worse, not better.

**What it means, plainly.** The patient bid bought 1.4 cents cheaper (0.976 instead of the 0.990 ask) but won 2.7
fewer times in a hundred (95.1 % against P1's 97.8 % at theta 0.99, H1). The seller who comes down to your bid on
a near-certain market is, on average, someone who sees the outcome turning: the median fill came 7 s after the
bid was posted, in the middle of a move. The discount is adverse selection, and it costs about twice what it
saves. Crypto hourly and 5-minute markets are 93 % of the fills and the worst of it (-0.029 per $, win rate 0.949
at a price of 0.976), and they are what the owner's venue has most of; sports gave 132 fills (+0.005) and weather
93 (-0.001), too few to read and not selectable on their own (families are a breakdown, not a cell). Per PLAN §3
no P5 cell qualifies, so VAL and TEST are not read. Resting on the bid side of these markets is not a route to
the grind either; the Polymarket desk stays a paper shadow. Paper only; nothing here is a live trade.

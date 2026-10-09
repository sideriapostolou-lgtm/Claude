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

# Lab 6 — reading the TRAIN results (2026-10-09)

`RESULTS.md` is written by `run.py`; this note is the plain reading of the same numbers for the owner.

## What the sports specialist does

It watches Polymarket's game-winner markets (MLB, WNBA, NFL, college football, NHL, UFC, the big tennis
tournaments, cricket, about 50 soccer leagues) and compares every price with what Pinnacle, the sharpest bookmaker,
says the true chance is. Pinnacle's odds carry a small margin, so the specialist removes it first (each side's
1/odds scaled so they add up to 100 %). When a Polymarket side trades below that fair chance by more than a margin,
after paying one extra cent of slippage and Polymarket's fee, it buys $20 of that side and holds it to the final
whistle. One bet per game, decided only with the Pinnacle line it could have seen at that moment (never a later one),
and only before kick-off.

The rules (grid, bar, splits) were written down and committed before any price was compared with any line
(`PLAN.md`, commit b9f5811).

## The data

- 6,167 Polymarket games in covered leagues with trading before the start (July 1 to October 8); 5,476 of them
  (89 %) matched to the same game on Pinnacle. The rest are mostly UEFA qualifying rounds and minor cricket and
  tennis that The Odds API does not list (`INVENTORY.md`).
- 23,543 historical Pinnacle snapshots: one just before every start, plus nine more spread over the 24 hours before
  each matched game, densest in the last hour where most of the trading happens.
- **Credits used: 241,870 of the 300,000 budget** (about 24,200 calls at 10 credits). The raw responses (195 MB) are
  cached locally and kept out of git; the derived Pinnacle table is committed.
- TRAIN = games that finished July 1 to August 15: 2,161 matched games.

## What TRAIN says: no edge

| rule (W = how long before the start it may buy, m = margin) | bets | bets per day | result per $20 ticket | 95 % range per ticket | total over 46 days |
|---|---|---|---|---|---|
| W 1 h, m 1 cent (the best-looking) | 177 | 3.8 | -$0.63 | -$4.14 to +$2.82 | -$111 |
| W 24 h, m 1 cent (bets the most) | 203 | 4.4 | -$1.66 | -$4.81 to +$1.72 | -$337 |
| W 1 h, m 3 cents | 67 | 1.5 | -$2.13 | -$7.23 to +$3.23 | -$142 |
| W 24 h, m 5 cents | 39 | 0.9 | -$8.37 | -$13.31 to -$2.51 | -$326 |

All 12 selectable rules lost money on TRAIN; none comes close to lab 4's bar (at least 100 bets with the whole 95 %
range above zero). The alternative way of removing the margin (power method) loses as well. Per the plan, VAL and
TEST are not run: **verdict NO EDGE on TRAIN.**

## Why, in plain words

1. **Polymarket already prices sports like Pinnacle.** Across 216,000 moments where the specialist could have
   bought, the Polymarket price sat on average about 1 cent from Pinnacle's fair chance (MLB 0.6 cents, World Cup
   0.8). A gap big enough to pay for the cent of slippage, the fee and even a 1-cent margin showed up in fewer than
   2 % of those moments.
   In MLB, the biggest league, the rule found one bet in six weeks.
2. **The gaps that do appear are not free money.** The bets came mostly from thinner corners (Leagues Cup, English
   cricket, The Hundred, tennis, NBA Summer League). If Pinnacle were exactly right they would have earned $1 to $3
   per ticket; instead they won less often than even Polymarket's own price said (41 % against a 46 % price at the
   1-cent margin). When Polymarket trades away from Pinnacle, Polymarket's traders often know something (a lineup, an
   injury) that Pinnacle's last snapshot had not caught yet.
3. **Closing line (H2, the diagnostic).** Buying any side at the first available price once the window opens loses
   about 1.2 cents against Pinnacle's last pre-game line: that is just the cent of slippage, so Polymarket's prices
   end up where Pinnacle closes. The specialist's own bets did beat the close on average (by 0.1 cents at the 1-cent
   margin up to 3.8 cents at the 5-cent margin), yet still lost on the scoreboard; with 30 to 200 bets the scoreboard
   is very noisy, so this is a hint, not an edge, and it does not change the verdict.

## How often it would bet, and what it would make

About 1 to 4 bets a day at $20 each ($15 to $90 a day at risk), mostly outside the big US leagues. On TRAIN that
lost between $0.63 and $8.37 per ticket. Nothing here supports putting money behind it.

## What would change the answer

- A **live** version would see Pinnacle every few minutes instead of this snapshot schedule (the backtest used
  lines up to 30 minutes old, a median of 9 minutes at the moment of a bet). Fresher lines would remove some of the
  "Polymarket knew first" losses, but also most of the gaps.
- The owner's venue is Polymarket US, whose fee (0.0695 x p x (1 - p)) is higher than the one modelled here, so the
  result there would be worse, not better.
- A forward paper test (record Pinnacle and Polymarket US live for a few weeks, same rule) is the honest next step
  if the owner wants a second look; it costs about 1 credit per sport per poll.

Paper only; nothing here is a live trade.

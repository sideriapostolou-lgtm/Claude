# Lab 5: reading the TRAIN results (2026-10-09)

`RESULTS.md` is written by `run.py`; this note is the human reading of the same numbers. Pre-registration:
`PLAN.md` (lab5-v1, sha256 45f1000dd793), committed in 083e98d before any return was computed. Trials so far
across labs 2-5: 2,999 (lab 5 added 36).

## What the specialist does

It is a crypto price expert for Polymarket's Bitcoin / Ethereum / Solana / XRP price questions. For every trade
printed on a market it asks: "given where the coin trades on Binance right now and how much it has been moving,
what is the real chance this question resolves Yes (or Up)?" It uses the textbook answer: the price wanders like a
random walk with no drift, at the speed (volatility) it showed over the last hour, day or week. If the market sold
one side cheaper than that chance by more than a margin (2, 5 or 10 cents) after paying one extra cent of
slippage and Polymarket's taker fee, it buys $20 of that side once and holds it to the end.

Three families, 36 settings in all:

* **S1, price at a time:** "Will Bitcoin be above $74,000 at noon on Aug 23?", "between $62,000 and $64,000?".
* **S2, up or down:** "Bitcoin Up or Down, 3:10-3:15 PM ET?", also 15-minute, hourly, 4-hour and daily windows.
* **S3, touch:** "Will Bitcoin reach / dip to $X today / this week / this month?".

The data checks passed before anything else was looked at: the markets settle exactly as Binance's own candles
say (every noon close, every hourly and daily window), the Chainlink-settled windows were rebuilt from Binance
with an error of under one hundredth of a percent once scaled to the venue's published "price to beat", and the
model reads spot 10 seconds older than each trade, so it never sees the future.

## What it found: no edge in any family

| family | markets (TRAIN) | best setting with >= 100 bets | bets | bets / day | won | price paid | net per $1 | 95 % range | $ per $20 bet | $ per day |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 price at a time | 774 | 2-cent margin, last day, 1-day vol | 274 | 6 | 57.3 % | 56.5c | -0.5c | -25c .. +30c | -$0.11 | -$0.64 |
| S2 up or down | 16,093 | 10-cent margin, first half of the window, 1-hour vol | 14,268 | 310 | 37.1 % | 37.3c | -3.7c | -6.2c .. -1.3c | -$0.75 | -$232 |
| S3 touch | 483 | 10-cent margin, last day, 1-day vol | 100 | 2 | 49.0 % | 45.0c | -2.6c | -31c .. +32c | -$0.51 | -$1.11 |

All 12 S1 settings and all 12 S2 settings lost money on average; every S2 setting lost with its whole 95 % range
below zero (between -3.7 and -10.4 cents per dollar staked, -$230 to -$680 a day at $20 a bet). The bar (at
least 100 bets, a positive average whose 95 % range sits above zero, at least one loss) was met by no setting, so
per the plan nothing goes to VAL and TEST is not touched. **Verdict: NO EDGE on TRAIN.**

**How often it would bet:** S1 1-12 times a day, S2 265-350 times a day (one per 5-minute Bitcoin window,
basically always), S3 1-4 times a day. Plenty of action; the action just loses.

## Why it lost (the plain reason)

The market already knows what the model knows, and a bit more. On the first trade the model looked at in each
market, the market's own price was the better forecast in every family and window but one (Brier score, lower is
better: S1 0.0558 market vs 0.0559 model in the last day, 0.106 vs 0.110 further out; S2 0.243 vs 0.249 early in
the window, 0.162 vs 0.172 late; S3 near 0.053 vs 0.060; the one exception is S3 far out, 0.038 vs 0.037 on 215
markets). The model is honest (when it says 70 %, it happens about 70 % of the time), it is just slightly less
sharp than the crowd. So when the two disagree by a few cents, the crowd is usually the one that is right, and
the specialist buys exactly the trades it should not. On top of that the costs are heavy: Polymarket's crypto fee
is 7 % x p x (1 - p) per share, 1.75 cents at a 50-cent price (3.5 % of the ticket), plus the cent of slippage.

Is it just too slow? A check on TRAIN only (scores, no money): with spot only 2 seconds old instead of 10 the
model is still no better than the market price (5-minute windows: model 0.166, market 0.155; hourly windows a dead
tie, model 0.1668, market 0.1667). Speed alone does not rescue a spot-plus-volatility model here: the 5-minute Bitcoin markets are traded
by bots that already price exactly this.

**One thing that looked good and is NOT a finding:** S3 touch markets far from their deadline (weekly and monthly
"reach / dip to") showed positive averages in 5 of 6 settings (up to +76 cents per dollar), but on only 47-104
bets falling in just 8 independent weeks or months, with 95 % ranges that include losing. That is exactly what luck
looks like at that sample size. It is recorded as an open lead, not tested further here, and would need its own
pre-registered test on months this lab has not read.

## What it means for the owner

A specialist is only worth money if it knows something the market does not. A textbook price-and-volatility model
for crypto price questions does not: Polymarket's crypto markets (the ones with $20,000+ volume, July-September
2026) are priced at least as well as that model, and the fee plus slippage turn small disagreements into steady
losses. The Polymarket desk stays a paper shadow; no real money follows any lab 5 setting. Nothing here is a live
trade.

What could make a real crypto specialist (each would be a new, pre-registered test, not a re-run of this one):
information the crowd prices worse than spot and history, such as options-implied volatility (Deribit's public
data) for the weekly and monthly questions where the far-out touch lead appeared; resting orders instead of taking
(zero taker fee, but lab 4's patient bid showed the danger of being picked off); or Polymarket US's own hourly and
weekly Bitcoin strike books, recorded live, which may be less efficient than polymarket.com's.

Files: `PLAN.md` (the rules), `inventory.md` (what is in the data), `structure.md` (the data checks),
`S1/train.md`, `S2/train.md`, `S3/train.md` (every setting), `RESULTS.md` (the decisions).

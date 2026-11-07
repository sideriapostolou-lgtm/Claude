# Lab 5: the crypto price-market specialist. Pre-registration, version lab5-v1

Written 2026-10-09 ~20:35 UTC, before any return of this study was computed. Owner direction (same day): no more
blanket tricks ("not just by 97 cents, that's a strategy"); each desk should be a specialist "insanely good at its
own market". Lab 4's blanket grind (buy every 95-99c outcome) found NO EDGE in every cell (research/lab4/RESULTS.md).
A specialist is the opposite: it prices each contract itself from the thing the contract is about, and bets only
when the market price is wrong by more than the costs. Lab 5's first specialist covers **crypto price markets** on
Polymarket: "Bitcoin above $X at noon?", "between $X and $Y?", "will Bitcoin reach / dip to $X?", "Bitcoin Up or
Down in this 5-minute / 15-minute / hourly / 4-hour / daily window?". Its model reads the underlying's spot price
and recent volatility at the moment of the bet.

Honesty rules carried over from labs 2-4: fixed rules, time splits, one look at TEST (run separately, after an
adversarial review), paper only; real money only after TEST passes AND the owner flips it. NO EDGE is a valid answer.

Already measured before this plan was written (no return computed; `inventory.md`, `structure.md`):

* **Inventory.** Lab 4's cache holds 39,796 markets of Polymarket's crypto fee family (closedTime 2026-07-01 ..
  2026-10-08, volume >= $20,000, 14-day tapes). 38,426 are price contracts on BTC, ETH, SOL or XRP with one winner:
  terminal (S1) 774 / 558 / 476 in TRAIN / VAL / TEST, windows (S2) 16,093 / 11,274 / 8,113, touch (S3) 483 / 360
  / 295. Almost every window is Bitcoin (the $20k volume floor drops most ETH / SOL windows). Excluded: 889 windows
  without a `priceToBeat` in Gamma, 231 closed after 2026-10-08 (lab 4's live-shadow set), 226 on other
  underlyings or not price questions, 12 "by December 31" touches.
* **Rules** (Gamma `description`, read for every market). Terminal and touch markets settle on **Binance** 1-minute
  candles (`BTC/USDT` etc.): terminal on the close of the 1-minute candle that opens at 12:00 ET on the date (four
  hourly-strike markets: the close of the 1-hour candle ending at the time); touch on any 1-minute high (reach) or
  low (dip) inside the period (a day, a week or a month in ET; monthly rules count only from the market's creation).
  Hourly up-or-down: Binance 1H candle close >= open; daily: Binance noon-ET 1-minute close above the previous day's.
  5-minute, 15-minute and 4-hour windows settle on a **Chainlink** BTC/USD stream (spot until ~2026-08-08, then a
  30 s or 60 s TWAP stream; `cryptoMarketConfig.twapLookbackSeconds`), Up iff the end value >= the value at the
  window open; Gamma publishes both (`priceToBeat`, `finalPrice`).
* **Replication on TRAIN** from Binance 1-second klines (data.binance.vision, sha256-checked): terminal 774 / 774,
  hourly 926 / 926 and daily 96 / 96 windows settle exactly as the venue did; touch 482 / 483 (one June market
  unexplained); Chainlink windows: `finalPrice >= priceToBeat` reproduces the venue's outcome in 100 % of 15,071;
  Binance alone as a proxy agrees in 95.7 % (5m), 97.6 % (15m), 100 % (4h).
* **Chainlink basis.** Chainlink / Binance at the window open: median -9.0 bp, sd 2.0 bp. After scaling Binance by
  `priceToBeat` / Binance-at-open, the residual log error of the window's END value has sd **7.54e-5** (0.75 bp;
  1 % / 99 % quantiles -1.8 / +1.9 bp) on TRAIN.
* **Print timing.** Over 3,000 TRAIN windows, a print's price matches the model best when spot is read **2 s**
  before the print timestamp (MSE 0.0112), worse at 0 s (0.0114), 5 s (0.0140), 10 s (0.0179).

## 1. Data, universe, splits

* **Markets and tapes:** lab 4's cache as is (research/lab4/data.py). **Rules:** Gamma market objects, by id
  (research/lab5/data.py, `rules.parquet`). **Spot:** Binance spot 1-second klines for BTCUSDT, ETHUSDT, SOLUSDT,
  XRPUSDT, 2026-06-01 .. 2026-10-08 (research/lab5/data.py; ~0.5 GB, out of git; rebuild steps in its docstring).
* **Universe:** lab 4's crypto fee family; binary; one winner (split resolutions excluded); a contract parsed by
  `core.parse_market` (terminal / touch / window) on BTC, ETH, SOL or XRP; >= 50 fills in the tape (lab 4's rule);
  Chainlink windows need `priceToBeat`. Other underlyings (BNB, DOGE, HYPE) and non-price questions are out.
* **Splits by closedTime (UTC), lab 4's:** TRAIN 2026-07-01 -> 2026-08-15; VAL 2026-08-16 -> 2026-09-15; TEST
  2026-09-16 -> 2026-10-08 (one look; refuses without `LAB5_ALLOW_TEST=1`).

## 2. The fair-value model (FIXED)

* **Decision time** `t_d = ts - LAG_S` for a print at `ts`, with **LAG_S = 10 s** (rule: max(10, best timing k + 5);
  best k = 2 s). Everything the model reads closed at or before `t_d` (a 1 s candle opening at `u` closes at
  `u + 1`): spot `S` = the close of the candle opening at `t_d - 1`; no spot after `t_d` is ever read.
* **Volatility:** `v` = realized variance per second from Binance 1-minute log returns (closes at minute ends) over
  a trailing window of minutes that ended by `t_d`; at least 80 % of the minutes present. Windows (both in the grid):
  S1 / S3 **1 day** (primary) and **7 days** (alternative); S2 **1 hour** (primary) and **1 day** (alternative).
* **Zero drift:** the price is a martingale; ln `S_T` ~ N(ln `S` - `V`/2, `V`), `V = v x tau`.
* **S1 terminal:** P(close above K) = Phi((ln(S/K) - V/2) / sqrt(V)); below = 1 - above; between [L, U) =
  above(L) - above(U); `tau` = seconds from `t_d` to the instant the settling close is fixed (noon ET + 60 s for the
  noon 1-minute candle; the hour's end for hourly strikes).
* **S3 touch:** 1 if the running Binance 1 s high (reach) / low (dip) over [period start, `t_d`) already reached
  the barrier; else the reflection principle for a driftless log price: min(1, 2 Phi(-|ln(B/S)| / sqrt(V))), `tau`
  = seconds to the period end. Only decisions inside the period.
* **S2 windows.** Binance hourly: reference = the 1H open (public 1 s after the open); P(close >= ref) with the
  terminal formula. Binance daily: reference = the previous noon-ET 1-minute close (public at noon + 60 s); P(close
  > ref). Chainlink windows: reference = `priceToBeat` (the stream's own value at the open, public at the open);
  the stream's current level is estimated as Binance x kappa, kappa = `priceToBeat` / Binance's proxy of the
  stream at the open (the price at the open, or the TWAP of the L seconds before it), both public at the open.
  Spot stream: lognormal as above with V + sigma_b^2. TWAP stream (L seconds): F = the average of the next / remaining
  seconds of [T - L, T); arithmetic Brownian moments: mean = (known part + S kappa l) / L, variance = (S kappa)^2 v
  (l^2 g + l^3 / 3) / L^2 + (priceToBeat sigma_b)^2 (g = seconds until the averaging starts, l = averaging seconds
  still to come); P(F >= priceToBeat) normal. **sigma_b = 7.54e-5** (the TRAIN residual basis above), fixed for
  every split. Decisions only from the reference's publication to the window end.
* The model probability of the side a print could buy: `q` for Yes / Up, `1 - q` for No / Down.

## 3. Entry rule, cells, selection (FIXED)

* **Prints.** Lab 4's tape, Amendment 3 sides: a print is buyable for exactly one outcome (a BUY on that token or a
  SELL on the other at 1 - p). Only prints before settlement (and before closedTime).
* **Price and costs.** Execution price `p_x` = min(print price of that side + **0.01** (one tick), 0.999). Taker fee
  per share = rate x `p_x` x (1 - `p_x`), rate from lab 4's family table (crypto 0.07; 0 when fees are off).
  **Edge** = `q` - `p_x` - fee per share.
* **One bet per market per cell:** the FIRST buyable print inside the cell's entry window whose edge exceeds the
  margin `m`; $20 ticket (`shares = 20 / p_x`), held to settlement on the venue's outcome:
  net = (shares if won else 0) - fee - 20, per $1 staked.
* **Entry windows.** S1 / S3: **near** = 5 min <= tau < 24 h; **far** = 24 h <= tau < 7 days (S3: decision inside
  the period). S2: **early** = decision in the first half of [reference public, window end); **late** = the second
  half; never with fewer than 5 s left.
* **Grid (all cells selectable):** each hypothesis: margin `m` in {0.02, 0.05, 0.10} x 2 entry windows x 2 vol
  windows = **12 cells; 36 cells** in all. Cell key `m<m>|<window>|vol<1h|1d|7d>`.
* **Bar (`core.qualifies`, lab 4's unchanged):** n >= 100 bets, mean net per $ > 0, cluster-bootstrap CI95 lower
  bound > 0, at least one loss, and with fewer than five losses the rule-of-three worst case
  (1 - 3/n) x mean win - 3/n must be positive.
* **TRAIN:** per hypothesis, SHORTLIST the qualifying cell with the highest mean net; none = NO EDGE for that
  hypothesis (at most 3 cells go on).
* **VAL:** each shortlisted cell, unchanged, must (a) qualify again, (b) beat the calibration placebo (the real mean
  at or above the 95th percentile of 2,000 redraws of the outcomes as Bernoulli(`p_x`), i.e. "the market price was
  right"), and (c) keep a positive mean net under the **latency stress** (the same signal executed at lab 4's rule:
  the first buyable print for the same side at or after ts + 10 s, within 600 s, at that print + 0.01).
* **SELECT:** among the VAL passes, the ONE cell with the highest VAL CI95 lower bound goes to TEST. None = no
  specialist cell for TEST.
* **TEST** (a separate step, after an adversarial review; once): the selected cell, the same three conditions.

## 4. Readings (pre-registered)

Per cell: bets (n), clusters, bets per day, win rate, mean price paid, mean model probability, mean model edge,
mean net per $ with **cluster-bootstrap CI95** (B = 2000; a cluster = all bets settled by one price draw: S1 the ET
date of the settling close, across underlyings; S3 the ET date of the period end; S2 the UTC hour of the window
end), rule-of-three worst case, mean $ per $20 bet, $ per day, worst $, the latency stress, the mean net re-costed
at **Polymarket US's 0.0695** fee, and the per-type breakdown (above / below / between, 5m / 15m / 1h / 4h / 1d,
reach / dip; a breakdown, not a cell). **Who knows better:** per hypothesis and entry window, the Brier score of the
model's probability against the market's print price, on the first in-window print of each market (primary vol).
VAL / TEST add the placebo.

## 5. What a pass would and would not mean

A pass says: on polymarket.com, in these months, a spot-and-volatility model found prices wrong by more than the
costs often enough, out of sample, to make money after fees, slippage of one tick and a 10 s decision lag. It does
not say the next months will, and the tape has no order book: buying at the print + 1 cent assumes the next level
had room for a $20 ticket. The owner's venue is **Polymarket US** (lab 4 Amendment 2), whose crypto markets are
hourly and weekly BTC strike markets (the S1 model applies to them) with its own books; a pass goes to a paper desk
on the US gateway first, re-costed at 0.0695, and never to real money without the owner.

Known limits, stated now: a 10 s lag is conservative for a live trader with a real-time feed, but the tape's
timestamps cannot support a shorter one safely (prints lead a 10 s-old spot; the market sees what we cannot);
Chainlink windows are modelled through a Binance proxy with a measured basis; the universe is lab 4's $20k-volume
set (thin ETH / SOL windows are not in it).

## 6. Trial ledger

Every cell evaluated on any split is a trial in `research/lab5/trials.json` (upsert on lab, hypothesis, cell,
split, stage); the running count across labs 2-5 is printed in every result file. `RESULTS.md` is generated by
`run.py`, never edited by hand; `READING.md` is the human reading.

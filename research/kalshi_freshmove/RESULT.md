# H-K: the dangerously-skip-permissions trigger on Kalshi 15-minute Bitcoin markets

**Verdict: no tradable edge at a reaction time we can reach.** The pre-registered confirmation passed its
declared rule, but that rule's latency buckets overlap the second in which the signal forms. In the first
bucket that starts after the signal is observable, the edge is gone. No real-money change follows.

## Question
On Polymarket the wallet makes its money by buying the side Binance BTC just moved toward, 1-3 s after the move.
After a fresh Binance move during a KXBTC15M window, are Kalshi taker buys of that side profitable after Kalshi's
full fee 0.07 p(1-p), and how fast must one be? Declared 2026-10-13 13:10 UTC, before any result
(`freshmove.py` docstring states the method exactly).

## Data
- Kalshi public trades for 90 consecutive settled windows, KXBTC15M-26OCT120300-00 to KXBTC15M-26OCT130115-15
  (REST, every page; `open_time`, `close_time`, `floor_strike` and `result` from the market records).
- Binance BTCUSDT 1 s klines (official daily files, sha256-checked; a kline at `t` covers `[t, t+1)`).
- Exploratory set: the 26 most recent windows (`exploratory_windows.txt`). Confirmation: the other 64, run once.

## Results (60 s markout after the entry fee; window-clustered t)

| Cell | Exploratory (26) | Confirmation (64) |
|---|---|---|
| Placebo, every taker print | -1.29c (t -14) | -1.27c (t -14.9) |
| theta 0.02, L = 0 | +1.25c (t 4.8) | +2.06c (t 7.1) |
| theta 0.02, L = 0.5 s | +0.07c | **+0.42c (t 3.1)** |
| theta 0.02, L = 1 s | negative | -0.92c (t 0.1) |
| theta 0.04, L = 0 | +3.6c (t 4.7) | +3.85c (t 7.3) |
| theta 0.04, L = 0.5 s | +1.6c (t 2.4) | **+1.35c (t 3.2)** |
| theta 0.04, L = 1 s | -0.35c | -0.84c (t 0.4) |

Held to settlement instead: theta 0.02 L 0.5 +0.08c, theta 0.04 L 0.5 -2.5c, and worse at 1 s and beyond.

## Why the passing cells cannot be traded
The move at second `s` uses the close of the kline covering `[s, s+1)`, known only at `s+1`. The execution
proxy for latency L takes the first matching Kalshi print in `(s+L, s+L+1]`. So L = 0 uses prints entirely
inside the second the signal forms, and L = 0.5 half inside it. L = 1 is the first bucket fully after the
close is observable, and it is negative in both cells. A trader reacting to individual Binance trades could
in principle act inside the second, but these 1 s bars cannot show how much of that is reachable. Each further
half second costs about 1.5 to 2.5c. The 60 s markout also counts no exit cost: a taker exit pays a
second fee (about 1.75c near 50c), so only a fee-free maker exit could keep it.

## What it means
The transferable part of the Polymarket wallet's taker edge needs sub-second reaction to the actual Binance
trade. On 2026-10-13 the companion measured about 0.5 s from tick receipt to decision and 0.7 to 1.2 s from
decision to Kalshi's acknowledgement (PRs #26 to #28 work on that), on Coinbase ticks rather than Binance.
Re-test only with tick-level timestamps on both sides, and only once the bot's own measured latency is
within the profitable range.

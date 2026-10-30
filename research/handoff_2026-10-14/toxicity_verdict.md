# Bid-puller ML: verdict

*Written Tue Oct 13, 3:14 PM PT. Research only: no orders, keys, Railway changes, deploys or pushes, and nothing written under /home/user/Claude.*

## The short answer

**No. Machine learning does not improve the pull guard. Nothing in this study makes money, so there is nothing to launch or scale.**

TEST was not used. The rule for opening it was that an ML pull rule beat both no-pull and the simple rule on the check windows with t of 2 or more, in the strict replay. No cell met that. TEST stays sealed for a future rule.

## What was tested

- **Data.** 116 Bitcoin 15-minute windows, Sun Oct 11 11:45 PM to Tue Oct 13 9:45 AM PT, split by time:
  - learn: the oldest 70 windows (through Mon 6:15 PM)
  - check: the next 23 (Mon 6:15 PM to midnight)
  - TEST: the newest 23 (Tue midnight to 9:45 AM), untouched
- **Model.** Every second, for each side, it asks one question: is my resting bid about to be filled by someone who knows the price is moving through it?
  - It uses 119 inputs the live bot has in time: Coinbase and Binance ticks, Kalshi prints, time left, distance to strike, and our fair.
  - The bot's real delays are built in.
  - An independent skeptic re-ran everything and got identical results. It found no look-ahead.
- **Replay.** The current bot (rung 0, 5-contract clip, $10 a window) was replayed with and without pulls, at 4 cancel speeds and with two fair models.
  - Two fill models: *strict* means the price traded through our bid; *touch* means it traded at our bid. Touch matches live fills better.

## Why ML doesn't help

1. **It predicts fills, not bad fills.**
   - It is very good at "my bid is about to be hit" (AUC 0.88), but one input does most of the work: whether our bid is at or above the price takers last sold at.
   - At telling a bad fill from a fine one, it is close to a coin flip (AUC 0.52 to 0.57). The fills it calls worst mark out no worse than the rest (+0.7c, range -1.2 to +2.6).
2. **Pulling on it throws away good fills too,** including the fills that complete our pairs.
   - Pairs per window fall from about 9 to about 4.
   - The leftovers go to the costly lock buy, and the fills that remain mark out worse.
3. **Random pulls beat it.** On the check windows, 92% to 100% of random pull schedules with the same amount and timing of pulling did better.
4. **The worst fills are too fast or invisible.**
   - A quarter of the bad fills land within 0.25 s, before any cancel can arrive.
   - The takers who hit us 0.8 to 1.8 s before spot moves leave no trace in the public feeds the model reads.

## Cents per window on the check windows, vs not pulling

- **Today's speed:** about 0.7 s from a Coinbase move to a cancel landing. That is a speed-plan estimate, since live cancels aren't timed yet. It sits between the 0.5 s and 1.0 s rows.
- **Target speed** after the speed work: about 0.12 s, the 0.1 s row.
- Each cell shows cents per window vs not pulling, with t in brackets. "Binance fair" and "bot fair" are the two replays.

**ML rule** (pull a side while the model's score for that bid is above 0.02):

| Cancel speed | Strict, Binance fair | Strict, bot fair | Touch, Binance fair | Touch, bot fair |
|---|---|---|---|---|
| 0.1 s (target) | -20.8 (-0.5) | -70.4 (-1.7) | -59.1 (-1.6) | -60.7 (-1.7) |
| 0.5 s | -22.4 (-0.6) | -71.9 (-1.7) | -34.3 (-1.0) | -64.5 (-2.2) |
| 1.0 s | -57.6 (-1.7) | -74.9 (-2.0) | -60.4 (-1.7) | -69.9 (-2.5) |

It loses 21 to 75 cents a window at every speed, target speed included.

**Simple rule** (the one already built: pull both sides for 5 s after a 1c fair move within 5 s):

| Cancel speed | Strict, Binance fair | Strict, bot fair | Touch, Binance fair | Touch, bot fair |
|---|---|---|---|---|
| 0.1 s (target) | +12.1 (0.5) | -11.4 (-0.4) | -11.2 (-0.3) | +22.4 (1.0) |
| 0.5 s | +9.8 (0.3) | -10.6 (-0.3) | +41.8 (1.1) | +43.9 (1.8) |
| 1.0 s | +3.9 (0.1) | -31.3 (-1.2) | +4.3 (0.1) | +25.3 (1.0) |

- It comes out about zero: -31 to +44 cents, never reaching t 2.
- On the check windows, random pulls at the same rate did as well.
- On the learning windows it did beat random pulls (+43c, p 0.02). That is why it is worth a live test, but not worth more size.

**A result to ignore.** An ML variant that pulls both sides 65% of the time shows +55c vs not pulling (t 1.7). That gain comes only from quoting less:
- It is only +5.6c (t 0.2) better than never quoting at all.
- Random pulls at the same rate get +45c.

**The bigger picture.**
- With no pull, the current bot lost 49.6c a window on strict fills (t -1.8) and 22.8c on touch fills (t -0.7) over the check windows. In this replay, no rule beats simply not quoting.
- About 290 rule-and-setting combinations were scored. The best |t| anywhere was 2.6, and that many tries needs about 4 before anything counts.

## What to plug into the live pull guard

- **No model and no threshold.** Do not load `model/frozen/gbm_strict2.txt` or any ML rule.
- **Keep the simple guard as built.** It is on branch `claude/kalshi-pull` (703d942) and was not merged or live as of 3:14 PM PT. The settings:
  - `SPEEDDESK_KALSHI_PULL=true`
  - `SPEEDDESK_KALSHI_PULL_MOVE=0.01`
  - `SPEEDDESK_KALSHI_PULL_LOOKBACK_S=5`
  - `SPEEDDESK_KALSHI_PULL_HOLD_S=5`

  This is the replayed rule. Live, it also triggers on a 1c round trip inside 5 s, so it pulls slightly more often. Lock buys stay exempt.
- **Don't retune those numbers on this data;** that would be fitting noise.
- **Don't switch to pulling only the side the move goes against.** That version lost 20 to 26c a window in the strict Binance-fair replay. It was mixed in the other replay.
- **Judge it live against the practice twin,** which never pulls. Expect about zero.
  - If the live spread is like the replay's ($0.5 to $1.9 a window), a real +10c a window gain needs roughly 100 to 1,400 windows to show at t 2. That is 1 to 15 days of round-the-clock trading.
  - Turn it off if real trails the twin at t -2 or worse. Call it a win only at t +2 or better.
  - The twin's fills are practice fills, so a small gap means little.
- **Size:** nothing here earns more size; let the ladder decide on real P&L.
- **Stops:** nothing here supports dropping the daily or lifetime stops. The no-pull bot loses money in this replay.

## What data would make it better

1. **The new recorder's books.**
   - The recorder is on `claude/kalshi-recorder`. It is off by default and not deployed. It saves the current and next KXBTC15M order book every second.
   - That gives three things the trade tapes can't:
     - how much size is queued ahead of our bid (today we only know a fill lands somewhere between strict and touch)
     - the real best bid and ask, instead of guesses from prints
     - other makers pulling their size just before a move, the classic warning sign
   - It records KXBTC15M books only when it runs as its own Railway service; inside the bot it skips them.
   - Once its 2 GiB cap fills, it drops KXBTC15M books older than 72 h. Give it room for 2 to 3 weeks.
2. **Sub-second books.** One snapshot a second is slow for a race that lasts 0.1 to 1.8 s. The live bot already gets the WebSocket book with its key; log every change with its receive time.
3. **Our own order clock.** Log Kalshi's timestamp on every create and cancel reply, and every fill that landed after we had sent a cancel. That gives the real cancel speed and the real list of fills we were too slow to dodge.
4. **The twin's kept bids.** Each pulled bid's twin copy shows whether it would have filled and how it marked out. That is a ready-made label for the next model.
5. **More days.** 1.5 days and 116 windows is small for ML.
   - Refit after 2 to 3 weeks (about 1,500 to 2,000 windows), with the same rules: time split, one look at the check windows, one TEST.
   - Score the next model on money after the fill, not on predicting fills.

## Files

Paths are under `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_toxicity/`.

- **This verdict:** `VERDICT.md`
- **Data:** `data/manifest.json`. The TEST files are `data/out/dataset/*_test.parquet`, never opened.
- **Model lane:**
  - `model/out/policy_table.csv` and `model/out/policy_per_window.csv`
  - `model/out/train_report.json` and `model/out/conditional_toxicity.json`
  - `model/frozen/` (frozen record only; not for live use)
  - `model/code/run_test_once.py`, never run (no `model/test/USED` marker)
- **Skeptic:**
  - `skeptic/out/null_replay.json`: matched placebos and the never-quote baseline
  - `skeptic/out/cond_ci.json`
  - `skeptic/out/audit_leak.json`

# Kalshi Bitcoin bot: why the 9:00 AM window lost, and what to change

All times are Pacific (PDT, UTC-7). Kalshi names each window by its Eastern close time, so the ticker ending ...131215 is the 9:00 to 9:15 AM Pacific window.

## Bottom line

- **The 9:00 AM window lost $1.86 because of how the strategy works. Nothing broke.** The first buy was run over within a second by a Bitcoin jump. The price never came back far enough for the bot to finish the pair cheaply. The end-of-window lock then fixed the loss at a fair price.
- **No bug caused it.** One delay is unexplained: at 9:08 AM the bot placed a bid 14 seconds late. That may have cost between $0.46 and the whole loss.
- **The next window (9:15 to 9:30 AM) lost $2.98 the same way, at 10 contracts.** At 9:45 AM today was down $3.93. Lifetime is down $2.87 over 46 windows; it was up $1.97 at 9:06 AM.
- **No rule can make every window win. What can be guaranteed is a smaller worst window.** The 5-contract limit went live at 10:23 AM (PR #35) and already halves it. Going back to $5 per window makes it a hard ceiling of $5, at no measurable cost.
- **No tested change has a proven profit edge. The strategy itself shows none.** The best-supported way to raise expected profit is to trade less. The most promising new rule (an earlier stop) should run on the practice twin first.
- **Do not step up to $20 a window.**

---

## 1. Why it lost

| Time (PDT) | What happened |
|---|---|
| 9:00:11.6 AM | First buy: a resting buy of Down, 5 contracts at $0.43. The model said Down was worth 0.468. The market's best Down bid was already 0.44, so our bid sat about 1.5c below the market's midpoint, not 3c. |
| 9:00:11.7 AM | 107 milliseconds later, a buyer swept Up at 0.56, 0.57 and 0.58 as Bitcoin jumped, and took all 5 of ours ($2.15). Within 30 seconds the Down leg was worth about 20c less per contract. |
| 9:00:14 to 9:00:30 AM | Two Up bids at 0.54. Nobody sold Up below 0.58, so neither filled. |
| 9:00:30 to 9:08:38 AM | No Up bid at all. The pair cap allows at most $0.99 for both sides together, so the Up bid could be no higher than $0.99 − $0.43 = $0.56. The model's bid (its value minus 3c) was above that while Up traded at 0.62 to 0.93. The cap refused it in 455 of 473 seconds. This is the rule doing its job. |
| 9:06:28 to 9:06:43 AM | Restart for a deploy: 14 seconds down, no orders open, and the cap would have refused a bid in every one of those seconds. It cost $0. |
| 9:08:20 to 9:08:25 AM | The only chance: Up dipped to 0.52 to 0.56. The bot's first Up bid went out at 9:08:38, 14 seconds after the dip ended, while its status said "Kalshi account data stale". Its bids of 0.41, 0.49 and 0.49 then sat 4 to 10c below the market. |
| 9:11:00 AM | Lock: bought Up, 5 contracts at $0.938 plus a $0.0204 fee. That is fair value: the model said 0.946 and the market was 0.939 bid / 0.940 ask. The pair cost $1.368 for a $1 payout. |
| 9:15 AM | Settled Up. Kalshi settles on a 60-second average of Bitcoin's price, and that average beat the strike by $23.39. Result: −$1.86. Holding the Down leg would have lost $2.15, so the lock saved $0.29. |

**The plain cause:** a one-sided first buy was filled at the moment Bitcoin jumped (bad luck in which trades fill). The price never came back far enough, for long enough, to complete the pair under the $0.99 cap. The lock then turned an open loss into a fixed one, at a fair price.

**Was a bug or an execution mistake involved?**
- **Checked and cleared:**
  - The restart cost $0.
  - The lock was priced fairly.
  - The $10 sizing was not involved. The old process still limited the window to 5 contracts; at 10 contracts the same path would have lost $3.72.
  - Kalshi's 60-second-average settlement did not matter at these times.
  - The bot's fee math matches Kalshi's to $0.0001.
- **Possible execution miss, cause not proven: the late bid at 9:08 AM.** After the 9:08:38 order the bot's main loop did nothing for at least 5.5 seconds. Today the bot's last account check was more than 3 seconds old in 5 of 32 status samples.
  - In the replay, bidding during the dip would have ended the window between −$1.41 and +$0.25. That is $0.46 to $2.11 better than what happened.
  - The logs do not record how long account checks take, so we cannot tell which one was slow. Bug fixes 2 and 3 below address this.

**The 9:15 AM window (−$2.98)** followed the same pattern at 10 contracts:
- The bot bought Down, 10 contracts at $0.42. They filled 2.3 seconds after the order went in, during a rush of Up buying.
- Nobody sold Up below 0.57 before the lock, so finishing the pair cheaply was impossible.
- The lock bought Up, 10 contracts at $0.87, at the ask.
- A bug in the loss-limit math (bug 1 below) cut its balancing bids to 3 contracts. Here that cost $0.

**The bigger picture:** 15 windows have lost money since 4:08 PM yesterday, $16.71 in total. Every one was a first buy that ran away. Most came from rules that have since been fixed:

| Cause | Windows | Loss |
|---|---|---|
| Wrong strike price (fixed 11:34 PM last night) | 7 | −$8.28 |
| Model buys at the ask, overlapping with the strike windows (turned off 5:17 AM) | 5 | −$5.36 |
| Current rules | 2 losing out of 16 | −$4.84 in losses; the 16 windows made +$2.06 overall |

---

## 2. Never again: what can and cannot be promised

**What cannot be promised:** that every window wins.
- A bot that opens with a one-sided buy will sometimes be run over. In the replay of 90 windows, a loss the size of 9:00 AM's (scaled to size) happens in about 1 window in 8. The plausible range is 1 in 5 to 1 in 16. That is roughly once every 2 to 3 hours of trading.
- Every guard tested turns rare large losses into frequent small ones. Losing windows go from about 23% to about 51%.

**What can be promised:** a smaller worst window.

| Rule | Status | Worst window | Expected cost |
|---|---|---|---|
| (a) At most 5 contracts per order (`SPEEDDESK_KALSHI_CLIP=5`, PR #35) | Live since 10:23 AM | Replay worst falls from −$5.34 to −$2.67. Today's two losses at today's caps would have been −$1.86 and −$1.49, instead of −$3.72 and −$2.98. | Between 22c worse (t −1.36) and 5c better per window, depending on the fill model. Not distinguishable from zero. |
| (b) **$5 window budget** (`SPEEDDESK_KALSHI_WINDOW_USD=5`, `SPEEDDESK_KALSHI_OPEN_USD=10`) | **Recommended now** | **Hard ceiling of $5 per window, fees included.** Spending is capped at $5, and the end lock can only shrink a loss. Replay worst is about −$2.10 to −$2.70. | Against today's settings: 0c to +28c per window (section 3, #1). It also halves the wins. |

**What the day and lifetime stops really do today:**
- The "$6 day stop" counts losses from the reset point the owner set, which was −$5.99. So today it only triggers when the day reaches about −$12.
- The real limit right now is the lifetime stop: about $7.13 of room left, if it counts from zero.
- Even with zero average profit, the replay gives roughly a 3 in 5 chance of losing $6 within a full 96-window day at today's settings. Expect the day stop to trigger on ordinary days.

---

## 3. More profit: ranked changes

No tested change has a proven edge. The current rule's own edge is about zero: −2c to −19c per window in the replays, every result statistically indistinguishable from zero. The changes below are ranked by expected value after the reviewer's checks.

### #1 Go back to $5 per window and keep the 5-contract limit
- **Code:** settings only. Set `SPEEDDESK_KALSHI_WINDOW_USD=5` and `SPEEDDESK_KALSHI_OPEN_USD=10` (`speeddesk_kalshi_window_usd` and `speeddesk_kalshi_open_usd` in `config.py`). Update `docs/ACCOUNTS.md` at the same time.
- **Expected value against today's setup:**
  - +27.7c per window (t +2.46), with the replay's fair value calibrated to match the live bot and strict fills (the fill model that reproduced the live record).
  - With the stop from #2 added: +23.3c (t +3.66) strict, +3.3c with looser fills.
  - With the uncalibrated replay: +0.2c strict, +5.7c with looser fills.
  - It was never worse in any test.
- **Why it works:** with $10 behind a 5-contract limit, the bot opens a second pair in the same window. Balancing fills are where money leaks: −3c after 60 seconds and −8c by lock time.
- **Worst window:** the same or better, with a hard ceiling of $5.
- **Confidence:** medium. The reviewer found this after the fact, on 90 windows from one day. But it points the same way in every test, and it only lowers risk.
- **Reviewer:** "In practice the recommendation amounts to going back to $5 caps."
- **Decision: switch to it now, with real money.**

### #2 An earlier stop, and no new first buy in the last 8 minutes
- **The rule:** from 10 minutes before the close, if the missing side's ask plus the leg's average cost plus the taker fee reaches $1.10:
  1. Cancel the window's orders.
  2. Buy the missing side immediately at the ask (only if the ask is $0.97 or less).
  3. Stop trading that window.
  
  Separately, place no new first buy in the last 8 minutes.
- **Code:**
  - Add a stop step next to `_lock` in `speeddesk_live.py`, called from `_decide` before the reprice loop.
  - Add `can_stop` in `speeddesk_live_model.py`, exempt from the spend budgets the same way `can_lock` is.
  - Settings: stop pair cost $1.10, from 600 seconds, first-buy cutoff 480 seconds.
- **Expected value at 10 contracts:**
  - The stop alone: +8.5c per window (t 0.64) strict, −3.0c (t −0.23) with looser fills.
  - With the calibrated fair: +12.2c (t 1.10) and +9.9c (t 1.12).
  - The 8-minute cutoff: +6.1c (t 1.21) strict and +0.2c with looser fills. It only affects 3 of 90 windows.
  - **Risk:** with orders taking 1 second to reach Kalshi, the combination drops to −9.9c strict and −5.0c with looser fills, and most of the worst-window gain disappears.
- **Worst window:**
  - At 10 contracts: −$5.34 becomes −$3.68 to −$3.99.
  - With the 5-contract limit: −$2.68 becomes −$2.11.
  - On today's windows: 9:00 AM −$1.86 becomes −$0.92. 9:15 AM −$2.98 becomes −$1.74, or −$0.87 with the 5-contract limit.
- **Confidence:** low to medium. It was the most consistent of the 26 variants tested. But the parameters were chosen after seeing the results, picking the best variant on one half of the data did not hold up on the other half, and it means more small losing windows.
- **Reviewer:** the numbers reproduce. It acts like an earlier, conditional lock: it usually fires right at 10 minutes left.
- **Decision: practice twin first,** for at least 200 windows, with real order delays. If the practice desk keeps its 60-second cutoff, model Kalshi's 60-second settlement average there.

### #3 Bid at the cap instead of not bidding
- **The rule:** when the model's bid (its value minus 3c) would break the $0.99 pair cap, rest the balancing bid at the cap price ($0.99 minus the first leg's average) instead of refusing.
- **Code:** in `_decide` (`speeddesk_live.py`), when `_inventory_guard` would return `"pair_cap"`, lower the bid to `floor((pair_cap − other_side_avg)/tick)*tick`.
- **Expected value:** −8.1c per window (t −0.42) strict and −18.6c (t −1.04) with looser fills, at 10 contracts in the uncalibrated replay. It has not been re-run with the calibrated fair or at 5 contracts.
- **Worst window:**
  - −$5.34 becomes −$4.70.
  - Losses the size of 9:00 AM's drop from 10 to 4 windows out of 90 (strict fills), and from 6 to 1 (looser fills).
  - The typical swing per window halves, from $2.09 to $1.07.
  - On the 9:00 AM window: −$1.86 becomes +$0.05.
- **Confidence:** low. This gives up some expected profit for a much smaller tail.
- **Reviewer:** the reviewer proposed it, as evidence against the claim that a run-over first buy can only be limited by size.
- **Decision: practice twin, alongside #2. Your call whether to make that trade.**

### #4 React faster: fix the stale-account stalls (bugs 2 and 3 below)
- **Expected value:** cannot be measured from the logs. On the 9:00 AM window alone, bidding during the 9:08:20 dip was worth $0.46 to $2.11.
- **Decision: ship now.** These are correctness and logging fixes.

### Dropped or disproved

| Idea | Result | Verdict |
|---|---|---|
| First buy, then pair only through the lock ("policy d") | +39c per window fell to +6.3c (t 0.19) strict and −13.9c with looser fills once the replay was calibrated to the live bot | Disproved, drop |
| Trading the final minute on Kalshi's 60-second average | Kalshi already prices the average; no edge in any test (largest t 0.82) | Drop |
| Lower volatility setting (1.2x instead of about 1.45x) | −16.6c (t −0.71) strict, +13.9c (t +0.83) with looser fills | Drop for now, retest with more windows |
| First-buy filters on fair value or volatility | −5c to −17c, worst window unchanged | Drop |
| Wait 60 seconds after the open | −17.4c and −12.4c | Drop |
| Lock only near fair, or no lock | About zero, or a worse tail | Drop |
| Quote both sides from the open, or complete earlier | Same as now, or worse | Drop |
| Model buys at the ask | −3.3c to −4.1c per contract (t about −3.3) | Keep off |
| Kalshi rewards on this market | $0: no liquidity rewards ever, the volume program has ended, the maker fee is already 0, interest needs a $250 balance | Nothing to gain |
| A rewards desk on Kalshi's 15-minute currency markets | Best case +$1 to +$1.50 per window. Under the fill model that matched the live record, −$7 to −$9 per window (t −5 to −8). The practice venue pays no rewards, so it cannot be tested there. | Drop. At most, record order books for a week without placing orders. |

One zero-cost check for you: log into Kalshi and see whether the account has been offered a Deposit and Trading Reward promotion (up to $2,500). Only Kalshi can offer it; the bot cannot earn it.

---

## 4. Bugs to fix now

1. **The loss limits count balancing buys as new risk, although those buys can only shrink the loss.**
   - Where: `speeddesk_live_model.py`, `can_buy` (lines 352 to 361) adds the full `cost` to `at_risk_usd` in the open-money, day and lifetime checks. `_cancel_unsafe` in `speeddesk_live.py` (lines 590 to 604) also cancels balancing bids on a money stop.
   - Evidence: in the 9:15 AM window the balancing bids were cut to 3 contracts instead of 10, and in the 9:30 AM window to 2 and then 5. That cost $0 so far.
   - Fix: check the stops against the change in the window's worst-case loss, which is `max(0, Δworst)` over the same pending-order combinations `_inventory_guard` already goes through, instead of `+ cost`. Do not cancel balancing bids on a money stop; locks are already exempt.
   - Test: a 5-contract first buy at $0.42 after a $2 day loss, with the $6 day stop, must still allow a 5-contract balancing bid at up to $0.57.
   - Effect on profit: about zero (−2.0c, t −0.19 on a fresh day). It matters less at 5 contracts or $5 windows.
2. **Price-change cancels are skipped while account data are stale.**
   - Where: `_decide` returns at line 1179 (`if reason := self._trade_reason()`), before the reprice loop at lines 1206 to 1212.
   - Evidence: at 9:08:39 AM a bid stayed up for 20.7 seconds while fair value rose about 7c.
   - Fix: in `_cancel_unsafe`, cancel any resting bid when the fresh fair value differs from the order's fair by more than 1c, or when the bid is above fresh fair − 2c, whatever `_trade_reason()` says. Cancels never add risk.
   - Cost so far: not measurable.
3. **Account checks read the whole order history, and nothing records how long they take.**
   - Where: `_reconcile` calls `list_orders` with no `min_ts`, and reads fills from the desk's very first start.
   - Fix:
     - Pass `min_ts` = the earlier of the oldest open order and now minus 900 seconds, minus another 60 seconds.
     - Keep one unfiltered read at startup only.
     - Log the check time in milliseconds, the number of pages read, and which consistency check failed, in `speeddesk_live_status`.
   - Why: the logging is what will explain the next 9:08 AM-type delay. The read limit is a precaution.
4. **Clean-up: `fair_up` ignores the 60-second settlement average** (`speeddesk_model.py:100`).
   - Fix: use the time left minus 39.5 seconds when 60 seconds or more remain.
   - It does not change profit (−0.2c to +4.7c), because the bot places no new buys in the last 240 seconds.
5. **The analysis replay, not the live bot, uses the wrong volatility scale.** `pairing/sim.py` uses raw Binance volatility; the live bot runs at about 1.45 to 1.52 times that.
   - Fix: scale it by 1.45 before trusting any replay ranking. This is what disproved "policy d".

**Already fixed:**

| Fix | When (PDT) | What it cost before |
|---|---|---|
| Correct strike price (PR #23) | 11:34 PM yesterday | −$8.28 |
| Model buys at the ask turned off | 5:17 AM | −$5.36 |
| Kalshi "already filled" (404) cancel replies no longer pause trading (PR #14/#16) | 7:34 PM yesterday | Not separable |
| Hidden $5 window limit removed (PR #32) | 9:06 AM | It actually halved the 9:00 AM loss |
| 5-contract limit on every order (PR #35) | 10:23 AM | — |

---

## 5. Stepping up to $20 a window: not supported

- **There is no edge to scale.** Lifetime is −$2.87 over 46 windows. The current rules made +$2.06 over 16 windows, which is about half a standard error from zero (t ≈ 0.5). The replays are near zero, with the result of a single window swinging by about $2.10 at $10.
- **Losses grow in step with size.** The replay's worst window at $20 is −$10.68, more than the $7.13 of lifetime room left. The 9:00 AM path would lose about $7.44. A $20 window also needs the $12 day stop, and bug 1 would then let only 6 of 20 contracts be balanced per order.
- **A good morning is not winning.** The 13 windows at 5 contracts before today's two losses made +$6.90. That is the kind of streak chance produces, and it was picked after the fact.

**What "winning" should mean statistically:** a fixed rule set, with no changes during the test, whose total since the last rule change exceeds 2 × (typical swing per window) × √(number of windows). At 5 contracts the swing is about $1.05, so:

| Windows | Trading time | Total needed |
|---|---|---|
| 96 | 1 day | +$21 |
| 384 | 4 days | +$41 |
| 960 | 10 days | +$65 |

A real edge of 10c per window takes about 440 windows (about 4.6 days of trading around the clock) to show. An edge of 5c takes about 1,760 windows (about 18 days).

Size up only when the total clears that bar, and only if the worst replayed window at the new size is no more than a third of the remaining lifetime room. Neither is true today.
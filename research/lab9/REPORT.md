# Lab 9: the next bot to copy (2026-10-12)

The owner's brief:
- Find a public bot whose method we can reverse engineer.
- It must trade a market he can use today, work at $25-$100 and not need speed.
- It must show a bankroll that climbs.

**How far the run got:** two of the four scouts finished, the leaderboard scout and the weather scout. The write-ups scout, the cross-venue locks scout, the deep dives, the skeptics and the verdict stopped at a usage limit. So the pick below rests on the scouts' own measurements, with no independent skeptic yet. Their full results are in `scouts.json`, and their scripts are in `leaderboard/` and `weather/`. Raw pulls are gitignored; re-run the scripts to fetch them again.

## The pick: far-strike NO on monthly crypto touch ladders (the "LucasMeow" rule)

**The rule:**
- Market: "How high / how low will Bitcoin (or Ethereum) get this month".
- Buy only NO, on strikes that are far from the price for the time left:
  - median z = 4.1, using 30-day realized volatility; the 10th percentile is z = 1.7;
  - median 10.7 days before expiry;
  - median price 0.99, and 85% of buy dollars at 0.97 or more.
- Mostly resting bids: 90% of its fills are maker. Hold every position to settlement. No speed needed.

**Three independent public wallets run this rule** (measured from each wallet's daily P&L series and activity):

| Wallet | Period | P&L | Months up | Max drawdown | Other |
|---|---|---|---|---|---|
| LucasMeow `0x7f3c8979d0afa00007bae4747d5347122af05613` | 2025-02-28 .. 2026-10-12 | +$344,872 | 20 of 21 (worst -$1) | $17.7k (5% of profit) | 205 closed markets: 200 won, 5 lost (-$4,725 in all, none of them core NO-at-0.99 bets); October 2025 crash month +$30k; top 5 days = 19% of profit |
| `0x6916cc00aa1c3e75ecf4081df7cae7d2f3592fd4` | 561 days | +$492,184 | 19 of 20 | 2.2% of profit | also market-makes, so it is harder to copy exactly |
| amis `0xc1a58674dbcc1d3208f7e61a0a8b252162caf290` | 683 days | +$79,468 | 21 of 24 | — | also oil and metals; its crypto NO bets went 25 of 25 |

In the scout's fill sample, every resolved NO at z >= 1.5 won: 67 of 67, and 48 of 48 at z >= 3.

**The twin on Kalshi.** The Crypto category is open to the owner in Washington. The series:
- Monthly one-touch: `KXBTCMAXMON`, `KXBTCMINMON`, `KXETHMAXMON`, `KXETHMINMON`.
- Annual: `KXBTCMAXY`, `KXBTCMINY`, `KXETHMAXY`.
- They settle on a CF Benchmarks index; read each series' rules for the exact touch definition.

Live check, 2026-10-12: NO asks of 0.96-0.99 at z 2.5-3.9, against a model value of 0.99-1.00. That is about 1-3.5c of model edge, with 49-2,099 contracts at the ask. Kalshi charges a quadratic taker fee and no maker fee, so resting bids pay nothing.

**Why it fits:**
- The market is open now, the rules are inferable, no speed is needed, and it works at $25.
- The record is long and steady, from three wallets.
- It is the owner's own "far from the line" idea, moved to contracts with days left instead of minutes.

**What it is not:** a lock.
- Each bet earns about 1-4 cents per dollar over about 10 days.
- A miss loses about 97 cents per dollar, so one miss wipes out about 30 wins.
- Part of the "edge" is a risk premium for crashes and fat tails; the model is a driftless lognormal.
- Lab 4 found no edge in buying 97-99c outcomes in general. What is new here is the distance filter, the touch contracts and three long winning records. That still has to be backtested on Kalshi's own history before any real money.
- At $25, expect cents to a couple of dollars a month.

## Runner-up: the weather "decided bucket" (the closest thing to a true lock)

**The rule:**
- A day's maximum temperature can only go up.
- Once an official observation (METAR) shows the temperature above a bucket, that bucket's NO has already won.
- Kalshi settles on the NWS daily climate report, which is never below the METAR maximum. 0 of 243 METAR-locked Kalshi brackets settled against the lock.

**Who does it:**
- HighTempTation `0x6011655c4afb76f36dd1b08a137a1ba73466b31e`: +$92.6k over 4,358 markets since 2026-04-03. It won 99.6% of markets and was up on 96.6% of days, with a max drawdown of $1,216.
- Weatherstappen `0xb9012e0d9b60d3920286309328b935cdfa609fc4`: +$51k, 99% of markets won.
- Both buy a median 1.3-1.4 minutes after the deciding observation, at a median 0.97-0.99.
- Monthly profit is fading, as more bots do it.

**On Kalshi:**
- 24 daily-high series trade 1.06M contracts a day, plus daily lows and rain.
- The price reaches the 0.99 tick within about 5 minutes of a lock (about 3 minutes for rain).
- A late buyer gets 1% gross at 0.99, behind resting queues of 16.5k-115.5k contracts.

So this is a race at the scale of minutes, not milliseconds. The bottleneck is how fast the METAR data reaches us, not how far our server is from Kalshi.

**Unmeasured:** what prices and how many contracts are available on Kalshi in the first 1-3 minutes after a lock. That decides whether we can do it.

**Watch out:** Kalshi uses the NWS station for each city, which is not always Polymarket's station. Central Park vs LaGuardia, Midway vs O'Hare and DFW vs Love Field differ.

## Ruled out

- **15-minute two-sided crypto bots** (e.g. `0xce25e214...`): they are speed bots. Their profit fell from $212k in May to $8k in October 1-12.
- **Daily crypto ladder trader** `0xdb5ad26b...`: its rule could not be inferred, and it sits in lab 5/lab 8 territory.
- **Macro-release traders** (podairpod, perfectnostalgia): very steady, but they look discretionary, and Economics is not in the owner's confirmed open categories.
- **Weather longshot buyers**: lottery-style. A few hits made almost all the profit, and the edge decayed by mid-2026.
- **Slow 0.999 lock buyers on Polymarket**: they earn about nothing, and several lost five figures.
- **True arbitrage on the owner's venues:**
  - Kalshi YES ask + NO ask is always at least $1, because each market has one book.
  - Weather complete sets cost $1.01-1.15 after fees.
  - Kalshi vs Polymarket US daily highs were within about 1c of each other, with no cross-venue lock (best -0.17c after fees).

## Next steps (practice first; real money only on the owner's amounts)

1. **Backtest the pick on Kalshi's own history.** Settled `KXBTCMAXMON` / `KXBTCMINMON` / `KXETHMAXMON` / `KXETHMINMON` markets with their trade prints. For each z bucket and days-left bucket: the fill price available, the win rate and the P&L after fees.
2. **Pull LucasMeow's full history** and write the rule with its exact numbers: z bar, days-left window, price cap, how much per strike and per ladder, and when it adds.
3. **Build a practice desk** that rests NO bids on qualifying strikes and holds them, using the same caps machinery as the speed desk.
4. **For the runner-up, measure the Kalshi lock window:** METAR time vs Kalshi trade prints in the first 3 minutes. Only build it if we can get filled at 0.97-0.98.

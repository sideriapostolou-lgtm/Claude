# Kalshi rewards playbook

As of Tuesday, October 13, 2026. All times are Pacific, 12-hour clock. Until November 1 that is PDT; after November 1 the times tied to New York hours stay the same in Pacific.

This is research only. No orders were placed and no keys were used.

## The short version

- **How it works.** Kalshi pays people who keep buy orders resting near the top of the book in chosen markets. The program is the Liquidity Incentive Program (LIP). Your account qualifies and there is nothing to sign up for.
- **What you can earn today:**
  - the 5 FX 15-minute markets, $50 per 15 minutes each;
  - copper, platinum, palladium and natural gas 15-minute markets, $20 each;
  - Coin Race, $20 for each of its 5 coins;
  - a few hourly and daily markets: Miami temperature, rain, Treasury yields and daily FX.
  - Not KXBTC15M. It has never had a liquidity reward, so the BTC desk's resting bids earn nothing extra.
- **The reward is real but small, and getting filled costs more than the reward pays.**
  - On FX, 10 contracts per side earn about $1.74 per 15 minutes, or about $117 a day per pair before losses.
  - Fills at stale prices lose about $8.50 per 15 minutes.
  - Net is about **-$457 a day per FX pair**.
  - None of the 192 quoting styles we tested made money in any of the 14 markets we recorded.
  - In a test that carried cash from one 15-minute window to the next, a $45 account on one FX pair went to almost $0 in under 2 hours.
- **The only way we found to make money is speed.** Money appears only for a bot that sees the FX price move 0.5 to 1 second before Kalshi's market makers reprice. That needs a Pyth price feed, which we could not read without a key, so it is unproven.
- **What to do:** keep real money out of LIP for now. Build the recorder additions, the Pyth feed, shard-aware cash and a practice LIP desk, in that order. Decide only after about 800 FX 15-minute periods of new data (about 2 weekdays of all 5 pairs; 2 weeks is better).
- **Other money from Kalshi:**
  - interest at 3.5% a year, but only on balances of $250 or more ($8.75 a year at $250);
  - promotions, if Kalshi offers one to the account;
  - referral credits;
  - the market bug bounty, $25 to $1,000 or more.

---

## 1. How Kalshi rewards work

The rule is the CFTC filing "Amendment to August 2025 Liquidity Incentive Program" (rules07152610358, Appendix A). It took effect July 30, 2026 and runs until January 1, 2027, unless Kalshi changes or ends it sooner. Help article 13823851 says the same thing in plainer words.

**The steps:**

1. **Kalshi chooses the markets and posts a pool for each period.** Each program has:
   - a period, for example one 15-minute window;
   - a reward, for example $50;
   - a Target size, for example 300 contracts;
   - a discount factor, 0.5 everywhere today.

   You can see them on the market's Rewards badge and in the public `GET /incentive_programs` list. Every member except customers trading through a broker (IB or FCM) is eligible, and there is no sign-up.
2. **Once a second Kalshi takes a snapshot of the order book**, at a secret random moment within that second. A 15-minute window has 900 snapshots. Only resting orders count: an order that has already been filled scores nothing.
3. **Each side is scored separately.** There is a YES side and a NO side; an order to sell YES at 43¢ counts as a NO bid at 57¢. On each side Kalshi starts at the best price and adds whole price levels going down. The **Reference price** is the first level where the running total reaches Target ÷ 5, which is 60 contracts when the Target is 300.
4. **Kalshi keeps adding levels until the running total reaches the Target.** Every order on those levels qualifies, and the last level counts in full. Orders deeper than that count zero. If either side never reaches the Target, that second pays nobody.
5. **Each qualifying order scores its size, halved for every cent it sits below the Reference.** An order at or above the Reference gets full credit. One cent below gets half credit, two cents below a quarter.
6. **Your share is your score divided by everyone's score, on each side.** Each side is worth 1. Your score for the second is your YES share plus your NO share.
7. **Pay for the period = reward × (sum of your second-by-second scores) ÷ (2 × 900).** Seconds that paid nobody still count in the 900, so a book that is often one-sided lowers everyone's pay.
8. **The $1 minimum and rounding.** If your pay for one program is under $1.00, you get nothing; it is not carried over. Otherwise it is rounded down to the cent. There is no cap per account.
9. **Payment comes later, in a batch.** Today at 3:21 pm, the newest paid 15-minute programs were ones that ended at 3:00 am, more than 12 hours earlier, so plan for a day or more. Paid rewards appear under Rewards and under Account > Activity > Credits. UNVERIFIED: whether they land as withdrawable cash or as non-withdrawable credit. Check after the first payout.
10. **Gaming the rules can get you removed.** Examples: timing orders around snapshots, posting size you do not mean to trade, or trading with yourself. Kalshi's Chief Regulatory Officer can revoke your status.

**Worked example (checked with `lip_score.py`).** EUR/USD 15-minute: $50 reward, Target 300, discount factor 0.5. You rest 10 contracts at the Reference price on each side.

What one second of the book looks like:

| Side | Price levels (contracts) | Reference price | Total score on the side | Your 10 contracts | Your share |
|---|---|---|---|---|---|
| YES bids | 41¢: 30, 40¢: 100 (yours included), 39¢: 250 | 40¢. At 41¢ the total is only 30; at 40¢ it reaches 130, past 60. | 30 + 100 + 250 × 0.5 = 255. The walk stops at 39¢, where the total reaches 380. | at 40¢ | 10 ÷ 255 = 3.92% |
| NO bids | 57¢: 80 (yours included), 56¢: 300 | 57¢. The first level already has 80. | 80 + 300 × 0.5 = 230 | at 57¢ | 10 ÷ 230 = 4.35% |

- **Your score for that second** is 0.0392 + 0.0435 = 0.0827. Everyone together scores 2.
- **Your pay for the period:**
  - Assume 828 of the 900 seconds are two-sided (92%, typical for FX) and look like this one.
  - Pay = $50 × 0.0827 × 828 ÷ (2 × 900) = **$1.90**.
  - That is over $1, so it is paid.
- **The same share in a $20 copper pool** comes to $0.76, which is under $1, so it pays **$0**.
- **Placing the YES bid at 39¢ instead (one cent below the Reference)** cuts your YES share to 2.0% and the pay to $1.46.
- **Cash tied up:** 10 × $0.40 + 10 × $0.57 = **$9.70**.
- **Gross per day:** about 67 FX periods a day (averaged over the week) gives about $128 a day. With real, moving books the simulation measured $1.74 a period, about **$117 a day**.
- **The catch:** in the same simulation these two orders were filled about 353 times per period. Those fills lost about $8.52 per period, so the **net was -$6.79 per period**.

---

## 2. What the account can earn today, and gross per day

**The account:**
- Direct member in Washington State.
- Open categories: Crypto, Climate and Weather, Commodities, Financials.
- Blocked categories: Sports, Elections, Culture, Tech and Science, Mentions.
- Every program below has no maker fee.

**Programs open to the account:**

| Program | Pool | Target | When it runs (Pacific) | Exchange shard | Smallest size that clears $1 |
|---|---|---|---|---|---|
| FX 15-minute: EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD | $50 per 15 minutes each | 300 | Sunday 2:15 pm to Friday 2:00 pm, except Thursday 12:00 to 2:00 am. Closed Saturday. About 67 periods a day averaged over the week, 96 on a full weekday. | 0 | About 5 contracts per side. Use 10, which pays about $1.74 a period. |
| Copper, platinum, palladium 15-minute | $20 each | 300 | Weekdays (447 periods a week), with a daily gap from 2:00 to 3:15 pm. About 64 periods a day averaged over the week. | 2 | About 13 at the best bid. 10 pays $0. |
| Natural gas 15-minute | $20 | 300 | About 71 periods a day | 2 | About 13 |
| Coin Race KXCRYPTOLEAD15M (BTC, ETH, SOL, XRP, HYPE) | $20 per coin | 1000 | About 95 periods a day per coin | 2 | About 19 on BTC. 50 to 100 on ETH and SOL. |
| Miami hourly temperature KXTEMPMIAH | $100 per strike per hour, about 10 strikes | 1000 | About 23 hours a day | 0 | Depends on the strike |
| Rain KXRAIN, 10-year Treasury KXUST10AD, KXBIGGESTQUAKE, ski openings, weekly alternative-data markets | $50 to $400 per day or week | 500 to 1000 | Daily or weekly | 0 | Only worth $1 to $15 a day each |
| Hourly Treasury yields (2, 5, 7, 10 and 30 year) | $10 per strike per hour | 1000 | Weekdays 12:00 am to 1:00 pm | 0 | Usually one-sided (see section 4) |
| Daily FX KXEURUSD, KXUSDJPY | $25 per strike per day | 1000 | Weekdays | 0 | Small |

**Access unknown:** Economics markets, mostly daily gas prices by state. That is the biggest pool family, about $350,000 a week. It is neither on your open list nor on the blocked list, so check in the app whether you can trade it.

**Gross per day: the reward only, before any fill losses.**

**At $45:**

| Plan | Gross per day | How solid the number is |
|---|---|---|
| One FX pair, 10 contracts per side ($9.70 resting, the rest as a buffer for fills) | **About $117** a day averaged over the week; about $167 on a full Monday to Wednesday | The only number backed by a full replay |
| Three or four FX pairs at 10 per side | $350 to $470 | Only if fills never tie up cash. They do: one pair needed up to $92 of cash. |
| Miami temperature legs, as picked by the optimizer | About $311 | Low confidence: based on 2 hours of books, with no fill test |

So **the honest gross range at $45 is about $100 to $300 a day**. In the test that carried cash from window to window, a $45 FX account collected only $1 to $5 of reward before fills emptied it.

**At $250:**

| Plan | Gross per day |
|---|---|
| All 5 FX pairs, 10 contracts per side ($48.50 resting) | **About $585** a day averaged over the week; about $835 on a full weekday |
| The optimizer's pick, mostly two-sided 100-contract Miami temperature orders | About $812 (low confidence) |
| Interest | About $0.02 a day |

So **the honest gross range at $250 is about $585 to $810 a day**.

Bigger numbers you may have seen, $1,525 to $1,667 a day at $45 and $5,458 at $250, come from 1¢ "completion" orders (section 4). Those numbers assume:
- books stay as they were;
- the 1¢ bids are never filled;
- competitors do nothing.

They are ceilings, not plans.

---

## 3. The best quoting policy and its net per day after fills

Every result below is from FX: 10 contracts per side, Kalshi's real recorded books and trades, and fills modeled the hard way.
- **Join the back of the line.** Our order waits behind the size already resting at that price.
- **Stale quotes get hit.** If a new bid crosses our old price, we are filled.

**Sample:** 8 windows per FX pair, Tuesday Oct 13, 12:15 to 2:15 pm, 109 market-windows in all. "Per day" means 67.3 FX periods, the 7-day average.

| Policy (FX, per pair) | Reward paid per period | Net per period after fills | Net per day | 95% range per day |
|---|---|---|---|---|
| **Least bad:** rest at the Reference price, move the order whenever the Reference moves, pull everything 5 minutes before the close | $1.28 | **-$3.20** | **about -$215** | about -$647 to +$216 |
| Same, but quote until the close (the main case) | $1.74 | **-$6.79** | **about -$457** | about -$1,036 to +$123 |
| Join the best bid instead of the Reference | $1.88 | -$9.16 | about -$616 | |
| One cent below the Reference | $0.20 | -$9.81 | about -$660 | |
| Reference with a 10-contract inventory cap | | -$7.25 | about -$488 | the whole range is below $0 |
| All 5 pairs, main case, if losses were topped up | | | **about -$2,280** | |
| Lenient fills, if no one ever crossed our stale quote (judged unrealistic) | $1.74 | -$0.69 | about -$46 | about -$329 to +$236 |

**Other markets, 10 contracts at the Reference:**
- Metals and gas: -$7.30 per period. The reward is $0 because the raw $0.65 is under $1.
- Coin Race: -$2.49 per period. The reward is $0 (raw $0.21).

**What the uncertainty means:**
- The 95% ranges come from only 8 periods. They do not rule out a small profit; they do rule out a profit as large as the reward itself.
- Picking the "best" policy here was done after seeing the data. A fair test that scored the best of the 192 policies on a window it was not picked on lost $41 to $84 per period.
- The sample is one weekday lunchtime. Nights, weekends and the Tokyo session are untested.

**Where money does appear: an oracle that sees the next book in advance.** This is an upper bound for a fast bot, not something we have.

| Advance warning of the next book | Net per FX period | Per day per pair | t |
|---|---|---|---|
| 0.5 seconds | +$3.89 | about +$262 | 1.99 |
| 1.0 second | +$6.80 | about +$457 | 5.45 |
| Cancel-only: pull quotes 0.5 s before they go stale | -$2.17 at the Reference, -$0.45 at the best bid | still not positive | |

That would be a speed race against Kalshi's two designated FX market makers, not a rebate. Whether a Pyth price feed gives that warning is UNVERIFIED.

**Numbers the skeptics changed:**

| Item | First estimate | After review |
|---|---|---|
| FX net per period, Reference, 10 contracts | -$7.85 | **-$6.79**. A fill-timing bug was fixed. Across all fill models that let stale quotes get hit, the range is -$5.30 to -$9.30. |
| FX net per period, best bid, 10 contracts | -$9.52 | -$9.16 |
| Only counting crossers who profit after their taker fee | not modeled | **Worse: -$8.28.** The crosses that remain are the costly ones. |
| Lenient fills (only printed trades fill us) as a possible truth | "about break-even" | **Rejected.** On 27.8% of FX price jumps, trades printed at the stale price, and the lenient book state cannot exist on the exchange. |
| $45 accounts | every window restarted at $45 | **Cash carried between windows:** 14 accounts went from $630 to $133 in 1 hour 45 minutes. 9 of 14 fell below $1, including all 5 FX pairs. |
| $250 as 5 FX pairs | -$2,172 a day (each window restarted at $45) | Cash carried between windows: **$250 fell to $69 in 1 hour 45 minutes.** With the 5-minute early stop it fell to $207. |
| Metals holdout, +$2,890 a day | looked like a winner | **A lucky split.** The reversed split gave -$142.60 per period, and leave-one-window-out gave -$133.97. |
| Best of 192 policies at $250, +$1,540 a day in sample | | Lost $3,772 a day on the holdout. The chance-alone check gave p = 0.99. |
| EUR/USD 10-lot at the best bid | $2.00 a period | $1.99 (raw $1.9987, rounded down) |
| Smallest size that clears $1 | "only FX at 10" | FX 5, copper 13, Coin Race BTC 19 (from one snapshot) |
| "Sit at the Reference" trick | a stable rule | True for each snapshot only. The Reference moves every second, and on FX and copper it was usually the best bid itself. |
| Payment lag | about 7 hours | Paid in batches; more than 12 hours seen; plan for a day or more |
| Designated market makers can now earn LIP | stated as fact | UNVERIFIED: their agreements are confidential |
| Kalshi rate limits | unverified | **Verified:** Basic tier is 100 tokens a second; an order costs 10 and a cancel 2. 5 pairs fit on average, but moving all 10 orders at once (about 120 tokens) overflows Basic. Advanced (300 a second) is a free self-serve upgrade. |
| How much data a verdict needs | | **About 700 to 800 FX market-periods** to detect an edge as big as the reward, about 1.6 full weekdays of all 5 pairs |

---

## 4. The clever parts and the traps

**Where the score-versus-fill trade-off favors us:**

1. **Rest at the Reference price, not the top.**
   - Both get full credit, but at the Reference you wait behind more size, so you are filled less often.
   - FX: 353 contracts filled per period instead of 618, for $1.74 instead of $1.88 of reward. Net -$6.79 instead of -$9.16.
   - The gain is real only when the top level is thin. When the best price already holds 60 or more contracts, the Reference *is* the best price.
2. **Never sit one cent below the Reference.** You get half credit, often zero (when the walk stops above you), and you still get filled. It was the worst placement.
3. **The thin side pays more per contract.** Each side is worth 1 however deep it is. 10 contracts against 300 is a 3.2% share; against 1,000 it is 1.0%.
4. **Your size counts toward the Target.**
   - In a market that is often one-sided, your order can turn dead seconds into paying ones, and you then own a large share of that side.
   - Outside the 15-minute markets about 47% of the pool goes unpaid for this reason: Miami temperature 79%, hourly Treasuries 84 to 88%.
5. **Stop 5 minutes before the close.** On FX it halves the loss (-$3.20 instead of -$6.79) and keeps 74% of the reward.
6. **Concentrate, because the $1 minimum is per program.** 10 contracts in one $50 FX pool pay about $1.74. The same 10 in a $20 copper pool pay $0.
7. **Pick quiet markets.** A Miami temperature strike traded 54 to 159 contracts an hour, against 2,100 to 4,900 per FX window. Fewer trades means fewer bad fills. This is untested for fills; it is a lead, not a result.
8. **The one good fill.** If both your YES at 40¢ and your NO at 57¢ fill, you hold a sure $1 for 97¢. That is the spread market makers live on. The trouble is that fills usually come on one side, right after the price moves.

**Traps:**

1. **Stale quotes get picked off.**
   - 56 to 84% of our FX fills came from someone crossing our old price after a move.
   - The other resting orders pulled 97.5% of their stale size in time. We are the slow quote that is left.
2. **The reward per filled contract is about 0.5¢; the loss is about 2.5¢** (measured 60 seconds after the fill).
3. **Cash gets locked until settlement and the account runs dry.** Every fill holds cash until the 15-minute market settles. Cash-carrying runs emptied $45 accounts in under 2 hours.
4. **The $1 floor.** Metals and Coin Race at 10 contracts pay $0 but still get filled.
5. **Exchange shards:**
   - FX is on shard 0. Metals, gas, Coin Race and BTC 15-minute are on shard 2.
   - Bot (API) orders need cash moved to the right shard first; the app and website move it automatically.
   - $45 split across two shards is very little on each.
6. **Collateral for both sides.** Assume both orders are reserved in full ($9.70 for a 10-lot pair) until a tiny real test shows otherwise. UNVERIFIED.
7. **Pools change without warning.**
   - FX went from $20 to $50 on October 6.
   - Gold, silver and oil 15-minute rewards ended September 19.
   - Programs are listed only 8 to 24 hours ahead, and programs on hidden events are not listed at all.
   - Re-read the reward every period.
8. **Backtest traps:**
   - The best of many policies on one sample loses on fresh data.
   - Assuming only printed trades can fill you makes quoting look break-even.
9. **Rule risk:**
   - Snapshot-timing games, flickering orders, size you would not honor, and self-trades across subaccounts can all get you removed.
   - The 1¢ completion trick can look clever. A $10 bid of 1,000 contracts at 1¢ completes a dead side and takes about half the pool. But takers already sweep these bids: 25 of 42 market sides we checked were swept in the last 24 hours, and each sweep costs about $11 to $13. Kalshi could also call it "inconsistent with the purpose" (UNVERIFIED).
   - Kalshi ended the volume program amid wash-trading allegations (press reports), so incentive programs are under scrutiny.
   - LIP ends January 1, 2027 unless renewed.
10. **Payment:**
    - It may arrive as credit, not cash (UNVERIFIED).
    - An SSN is needed once rewards and credits pass $600 in a year, and they are reported on a 1099-MISC.
    - Trading these markets through a broker such as Robinhood or Webull makes you ineligible.
11. **Rate limits.** On Basic, moving 10 orders at once draws rate-limit errors (HTTP 429). Upgrade to Advanced through the API before running more than a pair or two.
12. **Closed hours.** No FX on Saturday or Thursday 12:00 to 2:00 am. Closed seconds count against the pool.

---

## 5. What to build, in order, and the bar for real money

Every step until the last uses pretend money.

1. **Recorder additions (read-only, start now).** Add an LIP lane to the existing Kalshi recorder. It should record:
   - the 14 15-minute markets (5 FX, 4 metals and gas, 5 Coin Race), plus the at-the-money Miami temperature strikes and one hourly Treasury series;
   - books about twice a second from the batch book endpoint;
   - the full trade tape with Kalshi's trade times;
   - every program's reward, Target, discount factor, start and end, and its status changes (active, closed, paid) with times, which measures the pay lag;
   - market open, pause and settlement values;
   - gap records.

   Stay inside the shared 2 requests-a-second budget, or run it as its own service. Goal: 2 weeks covering every hour and weekday, with at least 800 new FX market-periods kept sealed for the final test.
2. **A Pyth price feed.** You need to get a key: Pyth's Hermes service returned 401 without one. Alternatively, use Kalshi's authenticated Pyth Value Feed, which needs a Kalshi API key used read-only.
   - Record the 5 FX pairs and the metals feeds at least once a second.
   - First question: how often does Pyth move 0.5 seconds or more before Kalshi's market makers reprice?
   - If it rarely does, **stop the FX LIP effort there**. The simulation found money only with 0.5 seconds or more of warning.
3. **Shard-aware cash (existing task).**
   - Read each shard's cash and never place an order bigger than that shard's free cash.
   - Treat filled positions as locked until settlement.
   - Move cash between shards on purpose.
   - Upgrade to the Advanced rate tier.
   - With your approval, place one 1-contract real test to learn whether Kalshi reserves both sides of a pair in full or only the larger one.
4. **Practice LIP desk in the arena (pretend money).** It runs on live books with:
   - `lip_score.py` for the reward;
   - the reviewed timed and fee-adjusted fill models;
   - cash carried across windows and split by shard, at $45 and at $250.

   Pre-register two policies:
   - Reference, 10 per side, move with the Reference, stop 5 minutes early;
   - the same quoting to the close.

   Add a third "pull when Pyth moves" policy once step 2 exists. Daily scorecard:
   - reward;
   - contracts filled and the share from crossings;
   - fill result at 60 seconds and at settlement;
   - net, with a 95% range.
5. **Real-money canary, only after the bar below is met.**
   - One FX pair, 10 per side ($9.70), with a $10 daily loss stop, for one week.
   - Compare real fills with practice fills on the same windows.
   - Check that the first payout lands as withdrawable cash and is within 10% of `lip_score.py`.
   - Grow only through the existing earned-growth ladder.

**Go/no-go bar for real money. All of these must hold:**
- One policy, written down before the test, run on fresh data it was never tuned on.
- At least 800 FX market-periods (better, 2 weeks) across all hours and weekdays.
- Net after fills above $0 per market-period, with t of at least 2, under both the timed and the fee-adjusted fill models, at both the 60-second and the settlement mark. Lenient fills do not count.
- Positive on at least 60% of days.
- The cash-carrying run at the real size never falls below 70% of its start.
- Writes fit the rate tier.

**If the bar is missed:** no real money on LIP. Keep the recorder running; the bar can be retried if pools or competition change.

---

## 6. Every other way Kalshi could pay the account

| Source | What it pays | Status for this account | What you must do |
|---|---|---|---|
| **Liquidity rewards (LIP)** | See sections 1 to 3 | Eligible, no sign-up | Do not trade these markets through a broker. Put your SSN on file before rewards pass $600 in a year. Turn on Settings > Notifications > Market rewards. After the first payout, check whether it landed in Cash or in Credit. |
| **Interest** | 3.50% a year on cash plus positions. It accrues daily at 9:00 pm and is paid monthly in the first week. | Only on balances of $250 or more. At $45, nothing; at $250, about $8.75 a year. | Keep at least $250 in the account. Add your SSN, which is needed above $10 a year of interest. |
| **Deposit and Trading Reward promotions** (since Sep 28, 2026) | Bonus credits, up to $2,500 per promotion and $5,000 for life ($25 if there is no minimum). Credits expire after 1 to 30 days and become withdrawable only after you trade an amount equal to the credit. Only fills from 3¢ to 97¢ count. | Only if Kalshi targets the account | Check app > Explore > menu > Your rewards > Offers every week. Take one only if the required trading fits markets you would trade anyway. Wash and self-matched trades do not count. |
| **Referral credits** | Varies by offer | U.S. users; the friend must add your code within 72 hours of opening an account | Your rewards > Offers > Refer a friend. Credits may need trading and can expire. They count toward the $600 SSN threshold. |
| **Market bug bounty** | $25 to $100 minor, $100 to $250 moderate, $250 to $1,000 or more severe; first reporter only | Eligible | When the bots find a market whose rules or data are wrong, report it at forms.kalshi.com/market-bug-bounty instead of trading on it. |
| App and website bug bounty | | Paused until early 2027 | Nothing now |
| Liquidity Provider Program and Market Maker Program | Fixed rewards or lower fees for quoting obligations | Need a signed Market Maker Agreement, a financial review, and winning an auction (auctions@kalshi.com) | Not realistic at this size |
| Volume Incentive Program | | Ended (effective no earlier than Oct 13, 2026) | Nothing |
| Perps fee rebate (Oct 8 to Dec 31, 2026) and perps promotions | Refunds perps fees; perps credits stay in the perps account | Perps only; a separate account you must apply for | Only if you trade perps. It cuts costs; it is not income. |
| Sports-combo and FOOTBALLSTATS leg rewards | Share of combo fees | Blocked (sports blocked) | Nothing |
| Fee-rounding refund, collateral return | Small refunds or freed-up cash | Automatic, or an opt-in setting per event | Not income; collateral return can free cash on hedged positions |

---

## Sources and files

All paths are under `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/`.

**Rules:**
- `rules/LIP_SPEC.md`
- `rules/lip_score.py` (39 tests pass; one harmless rounding-precision bug)
- `rules/dl_cftc/rules07152610358.pdf`
- help articles 13823851 and 16076644 under `rules/dl_help/`

**Live recording:** `live_recording/rec/manifest.json` and `live_recording/backfill/trades_backfill.jsonl.gz`.

**Simulation and its review:**
- `simulate/out/table_main.txt`
- `simreview_adv/out/final_tables.txt`
- `simreview_adv/out/accounts_seq.txt`
- `simreview_adv/out/audit_data.txt`
- `simreview_adv/dl_docs/rate_limits.md`

**History and ranking:**
- `history/out/series_history.tsv`
- `history/out/unpaid_pool_by_category.txt`
- `history/out/one_cent_sweep_check.tsv`
- `history/out/rank/rank_summary.txt`

**Rules review:** `review/scripts/adversarial_test.py` and `review/scripts/book_sizes.py`.

**Worked example check:** `../playbook_work/example.py`.

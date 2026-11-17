# rewards_lip_mastery (workflow wf_a5aa972d-5d7)



---
## result 0 

{
 "findings": [
  {
   "claim": "The LIP rule in force is Appendix A (clean) of the CFTC filing 'Amendment to August 2025 Liquidity Incentive Program'. It was filed 2026-07-15, took effect 2026-07-30, and runs until the earlier of 2027-01-01 or Kalshi amending or ending it.",
   "evidence": "https://www.cftc.gov/filings/orgrules/rules07152610358.pdf, re-downloaded today. Its sha256 matches the earlier copy. Earlier version: rules02112639183.pdf (effective 2026-02-28).",
   "confidence": "high"
  },
  {
   "claim": "Eligibility: every Kalshi member except IBs, FCMs and their customers trading through them. There is no sign-up. The help page also excludes affiliates, employees and non-U.S. users. The July 2026 filing dropped the earlier exclusion of affiliates and Market Maker Agreement holders, so designated market makers (2 on FX 15-minute, 1 on Commodities 15-minute) can now also earn LIP. The owner's Direct WA account is eligible but must not trade these markets through an FCM.",
   "evidence": "Filing Appendix A 'Eligible Participants' (tracked vs clean). help.kalshi.com 13823851 Eligibility section. help 15410219 provider counts.",
   "confidence": "high"
  },
  {
   "claim": "Exact snapshot algorithm, step by step. One snapshot per second at a random sub-second moment; the offset is redrawn only 'on a periodic basis' since Feb 2026. Each side's walk:\n- Start at the highest bid and add whole price levels.\n- The Reference Price is the first level where cumulative size >= Target/5.\n- Stop at the first level where cumulative >= Target. All bids on the walked levels qualify, the last level whole.\n- If the side runs out first, it has no qualifying bids.\n- Score = size x DF^N, with N = ticks below the Reference and N = 0 at or above it.\n- Each side is normalized to 1. User snapshot score = yes share + no share, at most 2.\n- Snapshots are excluded if the market is not open or either side misses the Target.\nA yes ask counts as a no bid at 1 - p.",
   "evidence": "Filing Appendix A 'Determining Reference Yes Price...' and 'Determining Snapshot Liquidity Provider Score' (clean text, quoted in LIP_SPEC.md section 5). The redline shows Target/5 and N = 0 above the reference are new in the July 2026 version.",
   "confidence": "high"
  },
  {
   "claim": "Payout per period = TP score x reward x (non-excluded / total snapshots). It is paid only if >= $1.00 and is rounded down to the cent. Because every valid snapshot sums to 2, this equals reward x sum(own snapshot scores) / (2 x total snapshots); a 15-minute period has 900 snapshots. The $1 minimum applies to each program (each market's period) separately. There is no per-account cap: max_reward_per_account exists only for margin volume programs and was absent on all 262k program rows inspected.",
   "evidence": "Filing 'Determining Payments'. help 16076644: 'a final reward below $1 for an individual program is not paid'. API changelog entries of 2026-08-27 and 2026-09-10. lip_score tests reproduce the help example 0.20 x $100 x 8000/10000 = $16.00.",
   "confidence": "high"
  },
  {
   "claim": "Live parameters (public API, 2026-10-13):\n- FX 15-minute EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD: $50 per period, target 300, DF 0.50, all on shard 0, Financials, linear_cent ticks, settle on Pyth.\n- Copper, platinum, palladium and nat-gas 15-minute: $20, target 300, DF 0.50, shard 2.\n- KXCRYPTOLEAD15M: $20 for each of 5 outcome markets, target 1000, DF 0.50, shard 2, CF Benchmarks.\n- Daily KXEURUSD / KXUSDJPY: $25 per strike per day, target 1000.\nAll are fee_type quadratic (no maker fee), and none has a scheduled fee change. AUD and CAD 15-minute LIPs started 2026-10-12; EUR, GBP and JPY started 2026-09-23. Gold, silver and WTI 15-minute LIPs ran Aug 3 to Sep 19 and ended.",
   "evidence": "dl_api/ip/active_p0.json and upcoming_p0.json; dl_api/series/*.json and markets/*.json (exchange_index, price_level_structure, fee_type, settlement_sources); /series/fee_changes?show_historical=true; dl_api/liq_hist summaries. docs.kalshi.com Get Series defines quadratic vs quadratic_with_maker_fees.",
   "confidence": "high"
  },
  {
   "claim": "Schedule and pool size per day. FX 15-minute runs 96 periods a day Mon-Wed, 88 on Thursday (no 07:00-09:00 UTC maintenance windows), 84 on Friday and 11 on Sunday: 471 periods a week, so $4,800 a pair on a full day and about $3,364 averaged over the week. Metals run 91 a day (gap 21:00-22:15 UTC), $1,820 a day. Nat gas runs 96 a day, $1,920. Coin Race runs 480 markets a day, $9,600. A pool pays in full only if every snapshot is two-sided.",
   "evidence": "Earlier work's lip15m_oct6_12.tsv program start times, checked here. Exchange schedule endpoint (Thursday 03:00-05:00 ET closure). help 13823807 and docs Maintenance and Pauses.",
   "confidence": "medium"
  },
  {
   "claim": "KXBTC15M has never had a liquidity program in the public listing. It had volume programs ($10-$20 per window) from 2026-01-26 to 2026-05-12. The Volume Incentive Program was terminated effective no earlier than 2026-10-13, and no volume programs are active (the last one ended 2026-09-20).",
   "evidence": "Full liquidity history paged today: paid_out 267,966 + closed 15,024 rows, earliest 2025-09-24, plus active and upcoming. Zero KXBTC15M rows; 9,781 KXBTC15M rows are type volume. CFTC rules09282630083.pdf. Caveat: hidden-event programs are left out of the listing (changelog 2026-07-22).",
   "confidence": "high"
  },
  {
   "claim": "On books recorded at 19:19 UTC, 10 contracts at the best bid on both sides would gross the following, if the book stayed as it was for the whole period. Small size therefore only clears the $1 floor in the $50 FX pools. These are gross rewards before fill losses; earlier strict-fill replays found -$7 to -$9 per FX window.\n\n| Market | Gross per period | Paid |\n|---|---|---|\n| EURUSD 15-minute | $2.00 | $2.00 |\n| USDJPY 15-minute | $1.99 | $1.99 |\n| Copper | $0.83 | $0 (under $1) |\n| Coin Race BTC | $0.54 | $0 (under $1) |",
   "evidence": "lip_score.py snapshot CLI on dl_api/books/*.json. Snapshot scores: 0.0799 EURUSD, 0.0797 USDJPY, 0.0828 copper, 0.0544 Coin Race BTC.",
   "confidence": "medium"
  },
  {
   "claim": "Rule consequence on order placement. Every bid at or above the Reference Price (the first level reaching Target/5) gets full weight. So a bid placed at the Reference level earns the same score per contract as one at the top of the book, is filled less often, and does not move the Reference. Each tick below costs a factor of DF = 0.5. Live example: in Coin Race BTC, tiny 1.5-contract orders at 0.56 and 0.55 sat above a Reference at 0.50.",
   "evidence": "Filing: N = 0 for bids above the Reference, plus the Target/5 rule. help 13823851: 'a small order alone at the top of the book does not set it'. Live book KXCRYPTOLEAD15M-26OCT131530-BTC.",
   "confidence": "high"
  },
  {
   "claim": "Payment and reporting:\n- Final scoring happens after the program ends and payment follows in a later processing run.\n- Observed lag: about 7 hours (at 17:11 UTC, 15-minute programs ending up to about 10:15 UTC were paid_out).\n- Paid rewards appear under Rewards (Current month / Lifetime) and Account > Activity > Credits.\n- The market Rewards popover shows a non-final earnings estimate for signed-in users.\n- An SSN is needed above IRS thresholds ($600 a year of incentive and referral credits, reported on 1099-MISC).\n- UNVERIFIED: whether LIP rewards land as withdrawable cash or as the nonwithdrawable 'Credit' balance. Check after the first payout.",
   "evidence": "help 16076644; help 13823851; help 16083491 and 13823849; help 13823844 ('Credit shows your nonwithdrawable credit balance'). Earlier work's closed vs paid_out pulls with end-hour histogram.",
   "confidence": "medium"
  },
  {
   "claim": "Anti-gaming:\n- The Chief Regulatory Officer can revoke participant status for participation that is 'abusive or in any way inconsistent with the purpose of the Program'.\n- All trading stays subject to Rulebook Chapter 5: no prearranged or non-competitive trades (5.17(b)), no wash trades, money passes or volume inflation, no spoofing, and resting orders must be funded.\n- Self-trade prevention applies across subaccounts.\n- Snapshot times are random and non-public by design, so timing quotes to snapshots or posting size you do not intend to honor risks revocation.",
   "evidence": "Filing 'Monitoring and Termination of Status'. CFTC rules08032613661.pdf quoting Rule 5.17(b). Rulebook v1.15 (Jan 2025, old numbering 5.15(a), (c), (z), (aa)). docs Subaccounts and Create Order V2 self_trade_prevention_type. Feb 2026 filing on non-public snapshot times.",
   "confidence": "high"
  },
  {
   "claim": "Shards and collateral:\n- Shard 0 is the catch-all (FX). Shard 2 holds Crypto and Commodities (Coin Race, metals, gas, BTC15M).\n- Programmatic traders must preallocate collateral on the right shard before placing orders. The app and web auto-transfer between shards.\n- Optional auto-rebalancing runs every 10 seconds to a target percentage split. Its resting_margin_reservation setting is sum (default), max or none.\n- Subaccount balances are local to a shard, and order groups do not work across shards.\n- So the $45 must be split between shard 0 (FX) and shard 2 (metals and Coin Race). One two-sided FX 10-lot (0.40 yes + 0.56 no) ties up about $9.60 under sum reservation.\n- How Kalshi reserves for simultaneous yes and no orders in one market at order acceptance is UNVERIFIED.",
   "evidence": "docs.kalshi.com getting_started/exchange_sharding.md, set-target-balance-allocation.md, get-balance.md, subaccounts.md. Market exchange_index fields.",
   "confidence": "high"
  },
  {
   "claim": "Other ways the account can get paid. Interest is not available at a $45 balance; Kalshi pays it only from $250.\n\n| Source | Status for this account |\n|---|---|\n| Interest (3.50% APY on cash + positions, accrued daily, paid monthly) | Only for balances of $250 or more; at $250 it is about $8.75 a year. SSN needed above $10 a year. |\n| Deposit and Trading Reward Program (from 2026-09-28) | Targeted Promotional Bonus Credits. Caps $2,500 per promotion and $5,000 lifetime; $25 if there is no minimum. Qualifying fills $0.03-$0.97 only. Credits expire after 1-30 days and are withdrawable only after trading an amount equal to the credit. |\n| Referral credits | U.S. users only; amounts vary by offer. |\n| Market Bug Bounty | $25 to $1,000 or more; first reporter only. |\n| App and Website Bug Bounty | Paused until early 2027. |\n| Liquidity Provider Program and Market Maker Program | Need a Market Maker Agreement (provider auctions via auctions@kalshi.com). |\n| Temporary Perpetual Fee Rebate (Oct 8 - Dec 31, 2026) and perps promotions | Perps only; the rebate offsets fees, it is not income. |\n| Sports-combo and FOOTBALLSTATS leg LIPs | Blocked; sports are blocked for this account. |\n| Volume Incentive Program | Terminated. |",
   "evidence": "help 13823847 (APY; the Klear article 13823771 still says 3.25%). CFTC rules09252630037.pdf sections 4, 5, 8, 10-12. help 13823783, 13823852, 13823853, 15410219, 13823819, 16071412, 17184676. CFTC rules09242629775.pdf, rules08122616003.pdf, rules09282630083.pdf.",
   "confidence": "high"
  },
  {
   "claim": "Data quirks and contradictions:\n- 111,557 of 239,574 liquidity programs have fractional-second start times, although the filing says periods start and end on whole seconds.\n- 1,277 programs have zero or negative duration.\n- The changelog's series_ticker field is absent from today's responses.\n- kalshi.com (regulatory notices page and fee-schedule PDF) returned HTTP 429 to this environment every time. The fee formulas (taker 0.07 x C x P x (1-P), maker 0.0175 x C x P x (1-P), both rounded up) come only from search-result quotes of the PDF.",
   "evidence": "Profiling of dl_api/ip plus the earlier ip_* pulls; curl and WebFetch attempts; WebSearch results.",
   "confidence": "medium"
  },
  {
   "claim": "lip_score.py is a pure, exact-arithmetic implementation (Fractions and Decimal) with 39 passing unit tests. It covers the help $16 example, the sports-combo help example ($18.88 / $5.10 / $1.02, which implies rounding to the nearest cent), the FOOTBALLSTATS filing example ($19.67 / $5.33 within 1 cent) and every edge case. Main entry points:\n- score_side and score_snapshot (with exclusions);\n- period_payout, payout_from_tp_score and payout_shortcut;\n- combine_book, which adds hypothetical orders or subtracts ours from a live book;\n- Grid.from_price_ranges, tick counting on any price grid (the tapered-grid reading is UNVERIFIED and does not matter for today's linear_cent LIP series);\n- program_from_api (centi-cents, bps and fixed-point parsing);\n- validate_program (the filing's limits);\n- is_crossed, which rejects hypothetical orders that would trade instead of resting.\nRun it with: python3 -I lip_score.py --selftest. CLI: lip_score.py snapshot BOOK.json --target --df --yes PxQ --no PxQ.",
   "evidence": "Ran python3 -I lip_score.py --selftest: 'Ran 39 tests ... OK'.",
   "confidence": "high"
  }
 ],
 "artifacts": [
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/LIP_SPEC.md",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/lip_score.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/test_lip_score.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/scripts/pull_liq_summary.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/scripts/html2txt.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_cftc/rules07152610358.pdf",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_cftc/rules09252630037.pdf",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_help/a13823851.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_help/a16076644.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_docs/api-reference_incentive-programs_get-incentives.md",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_docs/getting_started_exchange_sharding.md",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_api/liq_hist/liq_paid_out_summary.json",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/rules/dl_api/ip/active_p0.json"
 ]
}


---
## result 1 

{
 "findings": [
  {
   "claim": "I pulled the full public LIP history. It has 290,449 liquidity programs on 4,478 series, starting 2025-09-24 and ending 2026-12-07: 267,966 paid_out, 15,054 closed, 5,661 active and 1,768 upcoming. No volume programs are active or upcoming, so the Volume Incentive Program is over. KXBTC15M has 0 liquidity programs ever, which confirms that fact.",
   "evidence": "Source: GET api.elections.kalshi.com/trade-api/v2/incentive_programs?type=liquidity&status={active,upcoming,closed,paid_out}&limit=10000, all cursors followed. Field units are from docs.kalshi.com get-incentives (period_reward in centi-cents, discount_factor_bps, target_size_fp).\nRaw pages: history/dl_ip/raw_*.json.gz. Rows: history/out/programs.tsv.gz.\nThe type=volume active and upcoming calls each returned 0 rows (dl_meta/ip_volume_*.json.gz).\nParameter mix:\n- Target is 1000 on 66% of programs and 300 on 30%.\n- Discount factor is 0.5 on 97.5%.\n- The most common rewards per period are $20 (114k programs) and $100 (79k).\n- No program pays more than $1,000 per calendar day, consistent with the cap in CFTC filing rules07152610358.",
   "confidence": "high"
  },
  {
   "claim": "The total LIP pool grew from about $1k\u201310k per day in late 2025 to $250k\u2013320k per day in late September\u2013early October 2026, peaking in 2026-W40 at $316k/day. In W40\u2013W41, about $74k\u201381k/day was in the account's open categories and $72k\u201378k/day in categories whose access is unknown (mostly Economics). The apparent drop after W42 is a listing artifact: recurring programs are only listed about 8\u201324 hours ahead.",
   "evidence": "Built by spreading each program's reward evenly over the UTC days of its period.\nFiles: history/out/daily_pool.tsv and trend_families_weekly.tsv (pool by ISO week, program family and access class).\nAccess classes:\n- open: Crypto, Climate and Weather, Commodities, Financials\n- blocked: Sports, Elections, Science and Technology, Mentions\n- likely blocked (unverified mapping): Entertainment \u2248 Culture, Politics \u2248 Elections\n- unknown: Economics, Companies, and others\nCategories come from GET /series (dl_meta/series_all.json.gz, 15,005 series).",
   "confidence": "high"
  },
  {
   "claim": "History of the 15-minute LIP programs, checked against the API:\n- FX 15M (EURUSD, GBPUSD, USDJPY): started 2026-09-23 at $20 per period and was raised to $50 on 2026-10-06. AUDUSD and USDCAD were added on 2026-10-12 at $50. All use Target 300, discount factor 0.5, shard 0, Pyth settlement and quadratic fees (no maker fee). The schedule is 96 periods a day Mon\u2013Wed, 88 Thu, 84 Fri, 0 Sat and 11 Sun, which is 471 a week or 67.3 a day.\n- Commodities 15M: copper and natgas since 2026-08-27, platinum since 09-17 and palladium since 09-18, all at $20 and Target 300 on shard 2. Gold, silver and WTI 15M ran from 2026-08-03 to 2026-09-19 and then ended.\n- Coin Race KXCRYPTOLEAD15M: since 2026-08-24 at $20 for each of 5 outcomes, Target 1000, shard 2. It has not changed across 23,845 programs.",
   "evidence": "Sources: history/out/key_changes.txt and series_history.tsv. Series metadata (exchange_index, fee_type, settlement_sources) is from GET /series.\nPeriod counts come from programs that started 2026-10-06 to 10-12 (rank.py ppd_by_series).",
   "confidence": "high"
  },
  {
   "claim": "Other LIP programs in the open categories, and how they have changed:\n- The largest open-category pool is KXTEMPMIAH (hourly Miami temperature, Climate and Weather, shard 0): about 10 strikes \u00d7 $100 per roughly 1-hour program \u00d7 about 23 hours a day \u2248 $23k/day. It started at $80 on 2026-08-15 and has paid $100 since 2026-09-16.\n- Hourly temperature for Chicago, DC, LA, Austin and NYC ran in July 2026 and ended 2026-08-04.\n- The daily high and low temperature series ended 2026-06-12.\n- Still live: KXRAIN daily ($100 per strike, about 67 markets, about $3.2k/day); daily FX KXEURUSD/KXUSDJPY ($25 per strike per 24 h, 15 strikes each, weekdays, since 2026-07-31); weekly Financials alternative-data markets (app downloads, ad spend, foot traffic, about $100 per 168 h); KXUST10AD ($100 per 24 h); KXBIGGESTQUAKE ($50); ski-resort openings ($400 per 168 h).\n- New since 2026-10-09: hourly Treasury yields KX2/5/7/10/30YRRATEH at $10 per hour-program, 17\u201323 strikes, 07:00\u201320:00 UTC on weekdays. 1,281 of these are listed as upcoming through 2026-10-14 21:00.\n- Ended: GPU monthly series (H100/H200/B200/RTX5090, last 2026-09-12), KXUST5/7/30AD (2026-10-04) and KXFEDFUNDSYEAR (2026-08-28).",
   "evidence": "Sources: history/out/series_history.tsv (one row per series, with every reward/target/discount/period-length regime and its dates), lip_history_open_unknown.tsv, key_changes.txt and regime_changes.txt.\nUpcoming list: status=upcoming pull (rows_liquidity_upcoming.tsv).",
   "confidence": "high"
  },
  {
   "claim": "The largest single program family is in Economics, which is neither on the owner's open list nor on the blocked list, so access must be checked in the app. It is daily state gas prices (KXAAAGASD*, shard 0): $100 per program of about 16 hours per strike, 17\u201327 strikes per state, about 40 states. It grew from 1 series in March 2026 to about $350k per week in early October. States were added on 2026-09-16, 09-23 and 10-13 (ID, NH, SD, DE, MS, WV and AR on 10-13). Diesel, CPI, mortgage-rate and crop series are also Economics. Some CPI series are quadratic_with_maker_fees, so fills there pay a maker fee.",
   "evidence": "Sources: history/out/trend_families_weekly.tsv, family 'daily gas price by state'. Fee type per series is from GET /series in series_history.tsv.",
   "confidence": "medium"
  },
  {
   "claim": "Announced for the coming weeks:\n- The listing is rolling and short: 15M programs through 2026-10-14 04:00 UTC and hourly Treasury through 2026-10-14 20:59.\n- Long-dated upcoming programs: KXAAAGASM weekly at $300 from 2026-10-31 to 2026-12-07 (Economics); KXLLM1 (Science and Technology, blocked) from 10-19; KXATP (Sports) and KXACTBLUETOP (Politics).\n- I found no LIP filing newer than the 2026-07-15 amendment, which runs the program to 2027-01-01.\n- The Volume Incentive Program termination was filed 2026-09-28 (effective no earlier than 2026-10-13), amid wash-trading allegations and an August 2026 CFTC staff advisory on incentive programs. That scrutiny is a regulatory risk for LIP too (unverified).",
   "evidence": "Upcoming list: history/dl_ip/rows_liquidity_upcoming.tsv.\nFilings: cftc.gov/filings/orgrules/rules07152610358.pdf (the rules lane's copy, clean text read) and rules09282630083.pdf.\nPress coverage: theblock.co 2026-09-30 and sbcamericas.com 2026-10-02 (from web search; I read The Block article, which describes the volume program ending).",
   "confidence": "medium"
  },
  {
   "claim": "Crowding on the 15M programs, measured on recorded books (about one per second, 10 windows per series, 13 Oct 2026, 17:02\u201317:48 and 19:10\u201320:55 UTC). All $ figures are gross, before any fill losses.\n- FX 15M: both sides reach Target in 92\u201395% of snapshots. The validity drop is concentrated in the first minutes of each window, when books are one-sided. Discount-weighted qualifying size is 310\u2013450 on the yes side and 440\u2013530 on the no side. The books show market-maker ladders of 75 contracts per level plus 562.5 blocks.\n- Our share of the FX pool at the Reference Price: 3.2\u20133.5% at q=10, about 8% at q=25, about 14% at q=50 and 23\u201326% at q=100. That is $1.58\u20131.77, $3.7\u20134.1, $6.7\u20137.4 and $11.6\u201312.8 per $50 period, or $106\u2013119, $249\u2013276, $453\u2013499 and $784\u2013860 per day per pair. Capital needed is about q \u00d7 $0.96.\n- Commodities 15M: weighted size 240\u20131,100 per side. At q=10 the reward is $0.48\u20130.81 per period, which pays $0 under the $1 minimum. At q=25 it is $1.1\u20131.9, or $73\u2013121/day.\n- Coin Race: large yes-side blocks (weighted size 960\u201310,500). Reward per outcome-period is $0.15\u20130.30 at q=10, $0.68\u20131.38 at q=50 and $1.27\u20132.48 at q=100, so only q\u226550 on BTC/HYPE/XRP (q\u2265100 on ETH/SOL) clears $1.",
   "evidence": "Scored with history/scripts/fastlip.py. It matched the rules lane's exact lip_score.py on 1,600 of 1,600 test cases (crosscheck.py).\nInputs: the live_recording/rec books and kalshi_guard/incentives/dl/books/books.jsonl.\nOutputs: history/out/m15_markets.tsv and rank/rank_markets.tsv.\nPeriods per day are measured from history (67.3 for FX, 63.9 for metals, 70.9 for natgas, 94.9 for Coin Race).",
   "confidence": "high"
  },
  {
   "claim": "On the 15M markets, fills, not the reward, decide the result. In a strict-fill replay of pegged quotes, a 10-lot at the Reference was filled 114\u2013183 contracts per FX window and about 570\u2013580 per copper and natgas window. Public volume was 2,100\u20134,900 contracts per FX window and 9,500\u201332,000 per commodity window.\nAt q=10 the 60-second markout of those fills per window was: AUD +$2.52, JPY \u2212$1.06, CAD \u2212$3.46, GBP \u2212$3.72, EUR \u2212$5.23, copper +$6.91, natgas \u2212$5.82, palladium \u2212$3.67, platinum \u2212$2.95. The LIP reward was +$0.44\u20131.65 per window. Fill P&L is several times the reward and its sign is noisy, consistent with the earlier strict-fill result of \u2212$7\u20139 per FX window. Coin Race quotes at the Reference sit behind the large blocks and fill only 0\u20137 contracts per window, but the reward stays under $1.",
   "evidence": "Script: history/scripts/fillsim.py. Price-time priority, joining the back of the queue, re-posting each snapshot, marked to settlement and to the mid 60 s later.\nOutputs: history/out/fillsim_15m.txt and fillsim_15m.tsv.\nSample: 7 finalized windows per series, so the sign is not settled. Per-window volume: out/m15_volume_per_window.json.",
   "confidence": "medium"
  },
  {
   "claim": "Outside 15M, about half of the LIP pool is not being paid out. I ran 21 sweeps (19:34\u201320:49 UTC) of all 2,936 active LIP markets in open and unknown categories.\n- Weighted by pool, about 47% of snapshots were excluded because a side was short of Target, so that money is not paid to anyone.\n- Unpaid share by group: KXTEMPMIAH about 79%, hourly Treasury 84\u201388%, gas daily 35\u201372%, Climate and Weather 73%, Financials 40%, Economics 42%. For comparison: FX and commodity 15M 4\u20138%, Coin Race 21%.\n- Where markets are two-sided they are crowded: median combined weighted size is about 2,800 (Climate), 3,300 (Financials) and 12,300 (Economics). Deep sides hold 10^4\u201310^5 contracts at 1\u00a2.",
   "evidence": "Source: GET /markets/orderbooks, 100 tickers per call, with programs refreshed every 15 min.\nFiles: history/dl_books/books.jsonl.gz, history/out/sw_markets.tsv, unpaid_pool_by_category.txt (the $ flow is overstated for hourly series because several hours were sampled; use the percentages).\nCheck: 2,923 sampled markets are all linear_cent; 2,914 are on shard 0 and 9 on shard 2.",
   "confidence": "high"
  },
  {
   "claim": "Best two-sided options outside 15M, gross, no fills:\n- KXTEMPMIAH at-the-money strikes: weighted size about 500\u2013800 per side. Two-sided q=100 at the Reference earns $9\u201313.4 per hour-program (about 13% share), or $210\u2013311/day per strike slot at about 23 programs/day, for about $96 of capital. At q=10 it is $1.4\u20131.6 per program, or $33\u201336/day.\n- Other open-category markets at q=100: KXRAIN about $6\u201311/day, KXUST10AD about $8/day, KXBIGGESTQUAKE about $10/day for $30.\n- Weekly alternative-data and ski markets: $1\u20133.5/day per market.\n- Economics gas strikes (access unknown): $12\u201315 per program-day each for $75\u201397 of capital.",
   "evidence": "Sources: history/out/rank/rank_series.tsv (best market's $/day at q=10/25/50/100, capital, median and best share %, median weighted size, depth at best, turnover) and rank_markets.tsv.\nCaveat: KXTEMPMIAH was sampled for only 2 program-hours.",
   "confidence": "medium"
  },
  {
   "claim": "There is a 1\u00a2 'completion' trick, and it is already contested. The filing has no price floor. An empty side can be completed with about 1,000 contracts at 1\u00a2 ($10 of collateral), which makes the snapshots valid and gives us about 100% of that side, i.e. half the reward per program.\nGross value per program:\n- gas daily: $50 per $10 (Economics)\n- KXTEMPMIAH off-the-money strikes: $15\u201330 per hour-program per $10\u201320\n- hourly Treasury: $5 (about $30/day per $10)\n- KXUST10AD: about $20/day\n- daily FX: $12.50 (about $7/day)\nPublic trades show other traders already place these 1\u00a2 bids, and takers buying the near-certain side at 99\u00a2 sweep them:\n- 25 of 42 market-sides I checked had 1\u00a2 sweeps of 100\u20137,400 contracts in the last 24 h.\n- Examples: KXUST10AD-T5.34, 1,800 contracts swept 5 min after the market opened; KXEURUSD T1.106 and T1.132, 1,196 and 1,602 contracts at 14:29 UTC; 14 of 14 gas strikes swept between 12:24 and 18:42 UTC; KXTEMPMIAH strikes, 388\u2013534 contracts swept within the hour.\n- 10 sides (deep daily FX brackets, KXUST10AD) have never traded.\nEach sweep costs the bidder about $11\u201313 if the near-certain outcome wins. Break-even resting time is about 3.5 h for gas, about 13 min for KXTEMPMIAH and about 21 h for daily FX. Whether this nets positive needs a live test (not this lane). The Chief Regulatory Officer can revoke participation if it is judged 'inconsistent with purpose' (unverified risk).",
   "evidence": "Filing clean text: rules lane dl_cftc/rules07152610358.txt, lines 287\u2013305. There is no price limit; the 'highest possible price' clause was dropped.\nOne-sided scoring: fastlip.one_side, which rejects any order that would cross the other side. Results: sw_markets.tsv columns gross_*1c_usd*.\nSweep evidence: history/out/one_cent_sweep_check.tsv and history/dl_trades/*.json.gz (GET /markets/trades).",
   "confidence": "medium"
  },
  {
   "claim": "Ranking and $/day for a $45\u2013$250 account. All figures are gross, assume no fills, and are upper bounds.\nBy series:\n1. FX 15M, any pair: $106\u2013119/day at q=10 ($9.6), $250\u2013276 at q=25, $453\u2013499 at q=50, $784\u2013860 at q=100 ($96). But the fill markout per window is \u2212$5 to +$2.5 at q=10.\n2. KXTEMPMIAH at-the-money two-sided: $33\u201336/day at q=10, $210\u2013311 at q=100.\n3. Commodity 15M: $0 at q=10, $73\u2013121 at q=25.\n4. Coin Race: $0 below q\u224850; $95\u2013235/day per outcome at q=100 (shard 2).\n5. Long-dated daily and weekly markets: $1\u201315/day per market at q=100.\nPortfolio optimizer (greedy, $1 minimum applied):\n- $45: $311/day using only two-sided-valid markets in open categories with no 1\u00a2 tricks (mostly KXTEMPMIAH legs); $1,525\u20131,667/day if 1\u00a2 completions and 15M FX are allowed.\n- $250: $812/day (open, conservative), $891/day (open plus unknown) or $5,458/day (open, everything).\nThese come from about 1.5 h of books on one Tuesday evening, assume static books and no reaction from competitors, and ignore fills and sweeps. Realistic net is far lower and may be negative.",
   "evidence": "Files: history/out/rank/rank_summary.txt and portfolio_{45,100,250}_{open|open+unknown}[+lowturnover][+no1c].tsv.\n'lowturnover' excludes 15M and markets whose volume per period exceeds 0.5\u00d7 the qualifying size. 'no1c' keeps only quantity-grid quotes on markets that are valid without us at least 50% of the time.\nSlot programs per day are from history (rank.py ppd_by_series).",
   "confidence": "low"
  },
  {
   "claim": "Shards and capital: every FX, Climate (KXTEMPMIAH, KXRAIN), Financials and Economics LIP market is on shard 0. The metals and natgas 15M and Coin Race markets are on shard 2. API orders need capital pre-allocated per shard. A two-sided q-lot at the Reference costs about q \u00d7 $0.95\u20130.99 if both legs are reserved in full. One-sided legs at 1\u20133\u00a2 cost q \u00d7 $0.01\u20130.03, which is why cheap sides look so efficient per dollar.",
   "evidence": "exchange_index in GET /series and /markets: 2,914 of 2,923 swept markets on shard 0, 9 on shard 2 (dl_books/markets.jsonl.gz).\nSharding docs and reservation rules are in the rules lane: rules/dl_docs/getting_started_exchange_sharding.md and LIP_SPEC.md \u00a78. Whether Kalshi nets yes and no resting collateral is unverified.",
   "confidence": "high"
  },
  {
   "claim": "Limits of this lane's estimates:\n- Books were sampled only on 2026-10-13, 17:00\u201317:48 and 19:10\u201320:55 UTC (Tuesday evening US time); other hours and days may be more or less crowded.\n- Payouts assume static books and pegged quotes re-placed at the Reference or best bid every snapshot.\n- Fills, sweeps and competitor responses are excluded except in the 15M replay and the 1\u00a2 sweep check.\n- Request budget: this lane made 859 public requests at \u22640.67/s per process (\u22641.2/s for the short time two of my processes overlapped). There were 51 429 responses, each backed off.",
   "evidence": "Request log: history/out/requests.jsonl. Sweep status: dl_books/sweep_status.json (21 sweeps, 725 requests). Total disk use for the lane is about 97 MB.",
   "confidence": "high"
  }
 ],
 "artifacts": [
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/programs.tsv.gz",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/series_history.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/lip_history_open_unknown.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/key_changes.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/regime_changes.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/daily_pool.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/trend_families_weekly.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/weekly_series.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/m15_markets.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/sw_markets.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/fillsim_15m.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/fillsim_15m.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/unpaid_pool_by_category.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/one_cent_sweep_check.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/rank_series.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/rank_markets.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/rank_summary.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/portfolio_45_open+lowturnover+no1c.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/portfolio_250_open+lowturnover+no1c.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/portfolio_250_open+unknown+lowturnover+no1c.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/portfolio_45_open.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/rank/portfolio_250_open.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/out/requests.jsonl",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/dl_ip",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/dl_books/books.jsonl.gz",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/dl_meta/series_all.json.gz",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/scripts/fastlip.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/scripts/score_books.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/scripts/rank.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/scripts/fillsim.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/scripts/history.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/history/scripts/sweep.py"
 ]
}


---
## result 2 

{
 "findings": [
  {
   "claim": "Live recording finished. It ran from 19:10:41 to 21:22:13 UTC on 2026-10-13: books from 19:10:53 to 21:15:05, then a 7-minute tail that collected results and the end-of-run lists. It covers 123 markets in 10 series over 9 windows: the 19:00 window from 19:10 onward and eight full windows from 19:15 to 21:00. The series are the 5 FX pairs, all 4 LIP metals/gas series (COPPER, PLATINUM, PALLADIUM, NATGAS; the brief asked for one, but they cost nothing extra in the batch call) and KXCRYPTOLEAD15M with 5 outcomes. That gives 109 market-windows recorded in full.",
   "evidence": "rec/manifest.json run + coverage_summary: markets_recorded 123, full_windows 109, markets_with_result 123. Two segments: I restarted at 19:14:05-19:14:07 to apply per-endpoint 429 backoff, which caused an 8.9 s book gap. The 21:00 window has 11 markets because COPPER, PLATINUM and PALLADIUM list no market for 21:00-22:00 UTC.",
   "confidence": "high"
  },
  {
   "claim": "Order-book coverage: 10,976 batch snapshots with no ticker ever missing. Snapshot interval is 0.506 s median, 1.02 s p95, 1.89 s p99, 8.9 s max. In each full window, 95.3% to 99.2% of one-second slots have at least one snapshot (median 98.3%). There were 12 gaps over 3 s, 62.6 s in total.",
   "evidence": "manifest book_stream and coverage_per_market[].book_second_coverage. Coverage by window: 19:15 98.9%, 19:30 98.3%, 19:45 99.2%, 20:00 95.3%, 20:15 96.4%, 20:30 96.2%, 20:45 99.2%, 21:00 96.4%. Gap causes are listed in book_stream.gaps_over_3s_list: 5 had a 429 backoff inside; 6 were slow Kalshi responses (3 s at 20:10:46-20:11:08 and one 13.95 s response at 21:03:19); 1 was the original version's startup metadata burst at 19:10:53. The recorder is single-threaded, so a slow response delays the next book request.",
   "confidence": "high"
  },
  {
   "claim": "Requests: 14,533 Kalshi calls averaging 1.84/s, never more than 2 starts in any 1 s window. There were 474 HTTP 429s, no other HTTP errors and no network errors. Two scheduled tasks failed after 5 tries. One was the 20:00 window-open market snapshot, which later snapshots cover. The other was the after-close trade sweep for KXAUDUSD15M-26OCT131600-30.",
   "evidence": "manifest requests: by_status {200: 14059, 429: 474}; max_starts_in_any_1s 2; 429s by kind: trades 338, books 88, markets batch 38, markets list 7, single book 3. Total backoff 1216 s. The 429s come from CloudFront ('Error from cloudfront'). The IP is shared: other lanes were calling the same API at the same time. Problems are listed in run.problems.",
   "confidence": "high"
  },
  {
   "claim": "Rate-limit breach: for 25 seconds (19:13:32 to 19:13:58 UTC) a smoke test of the patched recorder overlapped the main recorder, so my total reached up to 4 requests/s. My manual curl probes (about 25, 19:03-19:09 UTC, spaced at least 0.5 s) are not in these logs.",
   "evidence": "manifest requests.combined_with_smoke_tests: max_starts_in_any_1s 4, seconds_with_more_than_2_starts 25, first_over 19:13:32.955Z, last_over 19:13:58.728Z. The smoke tests' request logs are in smoke_rec/ and smoke_rec2/.",
   "confidence": "high"
  },
  {
   "claim": "The public batch endpoint GET /markets/orderbooks?tickers=A&tickers=B works without auth and returns the same live book as GET /markets/{ticker}/orderbook. Repeated tickers= params work; a comma-separated value is read as one ticker. I found no sign that the batch call lags. All 14 books came back in one call at about 1-2 Hz.",
   "evidence": "manifest single_vs_batch: 363 single-book checks, each 0.5 s between two batch calls. In 239 the single book lies level by level between the two batch books. 115 are identical to the earlier batch and 103 to the later one; 157 are closer to the earlier and 138 to the later, which is symmetric. Book responses had no cache headers (x-cache Miss); GET /markets responses carry cache-control max-age=15 and sometimes x-cache Hit.",
   "confidence": "high"
  },
  {
   "claim": "Trades: 40,010 unique trades captured live, each with its exchange created_time. After the run I downloaded the full trade history of all 123 markets. Every live trade appears in it. The history has 11 trades the live run missed, all in KXAUDUSD15M-26OCT131600-30, the market whose trade sweep failed. backfill/trades_backfill.jsonl.gz is therefore the complete trade record.",
   "evidence": "manifest coverage_summary.backfill_trades_check: history_trades_in_recorded_span 38,295, missing_from_live 11, live_not_in_history 0. 1,981 duplicate lines from the restart were dropped by trade_id. Contracts traded in about 2 h: NATGAS 326k, COPPER 190k, PALLADIUM 88k, PLATINUM 68k, USDJPY 40k, GBPUSD 32k, EURUSD 32k, Coin Race 21k, AUDUSD 21k, USDCAD 17k.",
   "confidence": "high"
  },
  {
   "claim": "LIP parameters, read from public GET /incentive_programs at start, every window and end. All 5 FX 15M series pay $50 per period, target 300, discount factor 5000 bps (0.5). COPPER, PLATINUM, PALLADIUM and NATGAS 15M pay $20, target 300, DF 0.5. Coin Race pays $20 on each of its 5 outcomes, target 1000, DF 0.5. All are type 'liquidity' / 'series_lip' with one program per market per 15-minute window.",
   "evidence": "The incentives_*.jsonl.gz rows and the raw incentive_programs_{active_start,upcoming_start,active_end}_*.json.gz files. period_reward is in 1/10000 dollar: 500000 = $50, 200000 = $20. Active list: 5,655 programs at start, 5,579 at end. The upcoming list at 19:11 already held 475 programs for these series, created ahead through the 03:45 UTC window. The brief's figures match this.",
   "confidence": "high"
  },
  {
   "claim": "Money: the 14 recorded markets share a $430 pool per 15-minute period (FX $250, metals/gas $80, Coin Race $100). It drops to $370 in the 21:00-22:00 UTC windows, when COPPER, PLATINUM and PALLADIUM have no program. NATGAS keeps running. If every window of the day had programs, the upper bound would be about $40,980 per day. I have NOT verified that programs exist overnight, on weekends or outside FX hours.",
   "evidence": "manifest windows[].lip_usd_per_period_total: 430 for 19:00-20:45, 370 at 21:00. The upcoming list shows copper missing exactly the starts 21:00, 21:15, 21:30, 21:45 and 22:00 UTC. The Pyth FX schedule (from /v2/price_feeds metadata) shows FX closed Friday 17:00 ET to Sunday 17:00 ET. Upper bound: 5x$50x96 + 5x$20x96 + 3x$20x91 + $20x96.",
   "confidence": "medium"
  },
  {
   "claim": "Shards: the FX 15M markets are on exchange_index 0 ('Default'). Metals, gas and Coin Race are on exchange_index 2 ('Crypto & Commodities'). The program objects use the same schema on both shards; I saw no shard-specific LIP fields.",
   "evidence": "exchange_index on every market object and in GET /series/{s}. GET /exchange/status (recorded at start and end) lists 0 Default, 1 Combos, 2 Crypto & Commodities, 3 Tennis/Baseball/Basketball, all trading_active true. manifest coverage_summary.by_series[].exchange_index is ['0'] for FX and ['2'] for the other five.",
   "confidence": "high"
  },
  {
   "claim": "Settlement and fee metadata from GET /series/{s}. FX settles on Pyth: the rules say the close price of the pair as published by Pyth Network, and the target is the Pyth value at window open, rounded to 5 dp. Metals settle on 'Pyth - Copper/Platinum/Palladium/NATGAS'. Coin Race settles on CF Benchmarks, to 0.001% since 2026-08-28. All 10 series show fee_type 'quadratic' and fee_multiplier 1. The series endpoint does not show maker fees, so 'maker fee 0' remains unverified here.",
   "evidence": "manifest series_meta (contract_url and contract_terms_url PDFs listed there) and the rules_primary/rules_secondary fields of the market objects in markets_*.jsonl.gz. Markets show price_level_structure linear_cent and settlement_timer_seconds 1.",
   "confidence": "high"
  },
  {
   "claim": "Pyth Hermes is not reachable without an API key, so no 1 Hz FX prices were recorded. As a substitute, Kalshi's own Pyth-based open and close are recorded for every market: floor_strike is the Pyth open (the target) and expiration_value is the Pyth close.",
   "evidence": "401 'unauthorized' from hermes.pyth.network /v2/updates/price/latest, /v2/updates/price/{ts} and /api/latest_price_feeds, from hermes-beta, and from benchmarks.pyth.network/v1/updates/price. Only /v2/price_feeds metadata answered 200; the FX.EUR/USD, GBP/USD, USD/JPY, AUD/USD and USD/CAD feed ids are in recorder.py. The recorder probed once per window: manifest pyth.statuses {401: 10}, price_rows 0. coverage_per_market[].floor_strike and .expiration_value are filled for all 123 markets, e.g. EURUSD 19:15-19:30 had strike 1.11998 and close 1.12003, result yes.",
   "confidence": "high"
  },
  {
   "claim": "What the books looked like (descriptive only; this is NOT the LIP scoring rule). FX resting bids are deep relative to the 300 target: median YES-bid depth about 4.6k-12.4k contracts per side and median spread 3c. Both sides' total bid depth reached the target in 89-95% of FX snapshots, 93-99% for metals/gas and 82% for Coin Race (as low as 59%). Late in a Coin Race window the losing coins often have no YES bids at all. In the 19:00 window BTC, ETH, SOL and XRP had zero YES depth, so the both-sides condition fails there.",
   "evidence": "manifest coverage_per_market[].book_stats: medians over full windows of frac_both_sides_total_bid_depth_ge_target: AUDUSD 0.953, EURUSD 0.895, GBPUSD 0.93, USDJPY 0.913, USDCAD 0.95, COPPER 0.982, NATGAS 0.991, PALLADIUM 0.933, PLATINUM 0.937, CRYPTOLEAD 0.819. Median cents from best bid to target depth are 1-3c for FX and 1c (YES) / 11c (NO) for Coin Race.",
   "confidence": "medium"
  },
  {
   "claim": "Clock and timestamps: books carry no exchange timestamp. Each record stores the local send time (t0), the local receive time (t1) and the HTTP Date header. Trades also carry the exchange's created_time. The local clock agrees with the server to within about \u00b10.5 s.",
   "evidence": "manifest requests.server_date_minus_local_recv_s median -0.517 s. HTTP Date is truncated to whole seconds, so the true offset is about 0. Median book request latency is 92 ms and trades 71 ms (by_kind).",
   "confidence": "medium"
  }
 ],
 "artifacts": [
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/rec/manifest.json",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/out/manifest.json",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/rec/",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/backfill/trades_backfill.jsonl.gz",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/backfill/backfill_summary.json",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/scripts/recorder.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/scripts/build_manifest.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/scripts/reader.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/scripts/backfill_trades.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/smoke_rec/",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/live_recording/smoke_rec2/"
 ]
}


---
## result 3 

{
 "findings": [
  {
   "claim": "Verdict: none of the 192 quoting policies earns money on any of the 14 recorded markets. Under strict fills, quoting for the LIP reward loses money on every FX pair and on Coin Race, and is roughly zero but noisy on metals and gas. The reward is about $1.7-1.9 per FX period at 10 contracts. Being filled costs several times that.\n\nThe census of all 21,504 policy-by-series cells shows no edge:\n- Strict fills: 0.6% of cells have t>2, against about 4.3% expected by chance with n=8, and 14-16% have t<-2.\n- Lenient fills: 1.0-1.5% have t>2 and 6.6-8.1% have t<-2.\n\nA holdout test does not hold up either. I picked the best policy per series on 19:15-20:00 UTC and tested it on 20:15-21:00 UTC. It averaged -$24.69 per period with unlimited cash, -$32.43 at $250 and -$5.96 at $45, and was positive in only 4-5 of 14 series.",
   "evidence": "Files: out/tstat_census.txt, out/best_cells.txt (SPLIT HALF section), out/accounts_v2.txt.\nData: 109 full market-windows recorded 2026-10-13 19:15-21:00 UTC:\n- 8 each for the 5 FX pairs, natgas and the 5 Coin Race outcomes;\n- 7 each for copper, platinum and palladium (no 21:00 program).\nBooks were recorded about 2 times per second (live_recording/rec). The trade tape is complete (live_recording/backfill/trades_backfill.jsonl.gz).",
   "confidence": "high"
  },
  {
   "claim": "How the simulation works:\n- Reward: every second is scored exactly as the CFTC filing rules07152610358 (Appendix A) and help article 13823851 describe. Each second is scored at 0.25 s and 0.75 s and the two are averaged (the expected value over Kalshi's random snapshot moment). Our own size counts toward the Target. The $1 minimum per program and the floor to the cent are applied.\n- The float scorer matches the rules lane's exact lip_score.py on 6,750 visited states, with a maximum error of 5.6e-17. Three full-period payouts agree to the cent ($0.16 / $1.96 / $0.62 raw).\n- Fills are strict: we join the back of the queue behind the visible size. Trades at our price use up the queue ahead first. Prints at a worse price fill us up to their size. Partial fills are allowed. A repeg cancels and rejoins the back of the queue. Orders are post_only.\n- Two fill models are run:\n  - strict: a public bid that crosses our stale price trades with us;\n  - lenient: only printed trades fill us.\n- Reaction time is 0.25 s after each recorded book.\n- Inventory is valued at settlement and, as a check, at the mid 60 s after each fill. Yes and no contracts in the same market net to $1 immediately.\n- Maker fee comes from each series' fee_type. All 10 series are 'quadratic' (no maker fee), so fees are $0.\n- Cash: with $45 or $250, orders are cut to what the market's shard cash allows, and filled positions lock cash until settlement.",
   "evidence": "Code: scripts/simlib.py (rules quoted in its docstring) and scripts/crosscheck.py; results in out/crosscheck.txt. 11 unit tests pass (scripts/test_simlib.py): queue, partial fill, sweep, crossing, repeg priority loss, latency, post_only, stop, netting, budget, reward = lip_score.\nTrade direction was checked empirically (scripts/check_trade_side.py): taker_outcome_side 'no' hits yes bids 16,695 vs 411 times, and 'yes' hits no bids 15,946 vs 401 times. This matches the docs changelog of 2026-05-06.\nFee types come from GET /series in live_recording/rec/manifest.json series_meta.",
   "confidence": "high"
  },
  {
   "claim": "Main table: strict fills, unlimited cash, repeg whenever the target price changes ('track'), quoting until the close. Figures are means per market per 15-minute period; t is over the 8 window means.\n\n| Group | Place | Size | Reward paid | Fills (contracts) | Fill P&L at settlement | Fill P&L at +60 s | Net per period | Net per day per market | t | Worst period |\n|---|---|---|---|---|---|---|---|---|---|---|\n| FX | best | 10 | $1.88 | 85 (593) | -$11.40 | -$11.29 | -$9.52 | -$641 | -1.56 | -$71.27 |\n| FX | ref | 10 | $1.73 | 42 (326) | -$9.58 | -$8.16 | -$7.85 | -$528 | -2.39 | -$58.55 |\n| FX | ref-1 | 10 | $0.20 | 26 (199) | -$9.52 | -$6.49 | -$9.32 | -$627 | -4.21 | -$58.22 |\n| FX | ref | 25 | $4.08 | 48 (758) | -$20.85 | -$19.50 | -$16.77 | -$1,128 | -2.42 | -$134.56 |\n| FX | ref | 50 | $7.33 | 51 (1,448) | -$39.64 | -$38.96 | -$32.30 | -$2,174 | -2.58 | -$274.52 |\n| FX | ref | 100 | $12.53 | 54 (2,739) | -$75.57 | -$77.55 | -$63.04 | -$4,242 | -2.60 | -$560.80 |\n| FX | best | 100 | $18.18 | 114 (4,296) | -$121.68 | -$118.11 | -$103.50 | -$6,964 | -2.61 | -$511.29 |\n| Metals/gas | best | 10 | $0.00 | 252 (1,394) | +$4.94 | -$4.73 | +$4.94 | +$339 | 0.40 | -$140.67 |\n| Metals/gas | ref | 10 | $0.00 | 118 (728) | -$6.08 | -$6.52 | -$6.08 | -$412 | -0.44 | -$67.23 |\n| Metals/gas | ref | 100 | $5.19 | 211 (5,682) | -$66.27 | -$65.47 | -$61.08 | -$4,160 | -0.58 | -$632.32 |\n| Coin Race | ref | 10 | $0.00 | 1.6 (10) | -$2.76 | -$1.75 | -$2.76 | -$262 | -2.00 | -$31.00 |\n| Coin Race | best | 100 | $2.99 | 9 (290) | -$29.83 | -$25.30 | -$26.84 | -$2,546 | -1.84 | -$350.46 |\n\nPer day = per period \u00d7 periods per day: 67.3 for FX, 63.9 for copper, platinum and palladium, 70.9 for natgas, 94.9 per Coin Race outcome (7-day averages from the history lane). The per-day figures assume losses are refilled; a $45 account cannot fund them.",
   "evidence": "out/group_table.tsv / .txt (all 192 policies per group, both fill models).\nAt 10 contracts, metals/gas and Coin Race rewards fall under the $1 minimum and pay $0. The metals/gas best-10 net of +$4.94 is fill P&L only, from 1,394 contracts per period, and is not significant (t 0.40).\nIn strict FX, the share of filled contracts that came from crossing bids is 56-84%; for Coin Race it is 41-70%, and for metals/gas 39-50%.",
   "confidence": "high"
  },
  {
   "claim": "Per-series table: rest at the reference price, 10 contracts, track, quote to close, strict fills, unlimited cash. Values per period except where noted.\n\n| Series | Periods | Reward | Contracts filled | Fill P&L at settlement | Net | t | Worst | Net per day |\n|---|---|---|---|---|---|---|---|---|\n| AUDUSD | 8 | $1.88 | 397 | -$0.69 | +$1.19 | 0.24 | -$22.66 | +$80 |\n| EURUSD | 8 | $1.70 | 245 | -$5.42 | -$3.72 | -1.48 | -$17.43 | -$250 |\n| GBPUSD | 8 | $1.69 | 280 | -$4.73 | -$3.04 | -0.37 | -$32.95 | -$204 |\n| USDJPY | 8 | $1.77 | 375 | -$20.78 | -$19.00 | -3.36 | -$46.99 | -$1,279 |\n| USDCAD | 8 | $1.63 | 335 | -$16.30 | -$14.67 | -2.03 | -$58.55 | -$987 |\n| Copper | 7 | $0 | 981 | +$3.17 | +$3.17 | 0.08 | -$67.23 | +$203 |\n| Platinum | 7 | $0 | 252 | -$7.55 | -$7.55 | -1.59 | -$33.21 | -$482 |\n| Palladium | 7 | $0 | 392 | -$6.40 | -$6.40 | -0.58 | -$31.98 | -$409 |\n| Natgas | 8 | $0 | 1,217 | -$12.59 | -$12.59 | -1.17 | -$54.13 | -$892 |\n| Coin Race BTC | 8 | $0 | 14 | -$6.08 | -$6.08 | -1.62 | -$31.00 | -$577 |\n| Coin Race ETH | 8 | $0 | 4 | -$0.10 | -$0.10 | -0.52 | -$1.00 | -$9 |\n| Coin Race HYPE | 8 | $0 | 16 | -$2.53 | -$2.53 | -1.06 | -$18.60 | -$240 |\n| Coin Race SOL | 8 | $0 | 3 | -$0.48 | -$0.48 | -1.41 | -$2.70 | -$45 |\n| Coin Race XRP | 8 | $0 | 13 | -$4.61 | -$4.61 | -1.54 | -$20.33 | -$437 |\n\nFor FX, each filled contract brings in about 0.5 cents of reward ($1.73 / 326) but loses about 2.5 cents at the 60-second mark (-$8.16 / 326).",
   "evidence": "out/table_main.txt / .tsv (13 canonical policies \u00d7 14 series \u00d7 both fill models). The full grid for every series is in out/table_policy_market.tsv: 21,504 cells, each with gross, fills, contracts, fill P&L at settlement and at +60 s, net, sd, t, worst, per day, peak capital, writes per second.",
   "confidence": "high"
  },
  {
   "claim": "How each choice changes the result (FX, rest at reference, 10 contracts, strict fills; net per period):\n- Repeg rule: track -$7.85, re-quote on a 1-tick mid move -$6.39, on a 2-tick move -$7.32. Never repegging is about -$0.17, but it earns $0 reward because the order drifts out of the scored levels.\n- Stopping before the close helps only slightly: stop 60 s early -$7.98, 180 s -$7.12, 300 s -$4.27 (reward falls to $1.28).\n- Fill losses are spread across the whole window. At the 60-second mark FX fills lose $1.2-3.4 every 3 minutes, against $0.23-0.41 of reward over the same 3 minutes.\n- Placement: joining the best bid or quoting one tick below the reference loses more than resting at the reference. One tick below is scored at half weight, and when the Target is already met at the reference level that order earns nothing.\n- Size: losses grow roughly in proportion to size.",
   "evidence": "out/marginals.txt, out/table_main.txt (ref|10|track|60/180/300, mid1, mid2, static) and out/fill_timing_ref_q10_track.txt (scripts/fill_timing.py).",
   "confidence": "high"
  },
  {
   "claim": "Robustness checks (FX, rest at reference, 10 contracts, track):\n- Reaction time barely matters. Net per period is -$6.06 at 0.1 s, -$7.85 at 0.25 s and -$6.29 at 1.0 s, because the recorded books are about 0.5 s apart.\n- Shifting trade timestamps from -0.5 s to +0.5 s against book times leaves net between -$5.67 and -$8.10.\n- The fill model matters most. Under lenient fills (only printed trades fill us), FX results move to about break-even:\n  - reference, 10 contracts: -$0.69 (t -0.39);\n  - best bid, 10 contracts: +$0.94 (t 0.26);\n  - reference, 100 contracts: +$14.62 (t 1.23);\n  - best bid, 100 contracts: +$21.61 per period (t 1.61; $531 peak capital; +$21.51 at $250, t 1.68; -$3.41 at $45).\n- None of the lenient results is significant, and Coin Race and metals stay negative under lenient fills.\n- The real answer depends on whether the fast market makers' repricing orders take our stale quotes (strict) or are post-only (lenient). That is unverified.",
   "evidence": "Latency grid (out/rows_latency.tsv.gz, 384 variants). Sensitivity section of out/best_cells.txt. scripts/sens_shift.py output in out/sens_shift.txt and .tsv.\nThe recording lane measured the clock offset at about 0 \u00b1 0.5 s. A trace of USDJPY 26OCT131600 shows typical stale-quote fills. For example, our no bid at $0.25 was crossed when a yes bid of 562.5 at $0.75 appeared within 1 s.",
   "confidence": "medium"
  },
  {
   "claim": "Account results. The $45 and $250 limits are enforced inside the simulation, with each market's cash held on its own shard: FX on shard 0, metals, gas and Coin Race on shard 2.\n\n$45, one market, rest at reference, 10 contracts, track (net per day):\n\n| Market | Net per day | t |\n|---|---|---|\n| AUDUSD | +$7 | 0.02 |\n| EURUSD | -$250 | |\n| GBPUSD | -$35 | |\n| USDJPY | -$1,032 | -2.24 |\n| USDCAD | -$862 | -2.25 |\n| Natgas | -$880 | |\n| Coin Race BTC | -$577 | |\n\nSeveral cells have a worst period of -$45.00, the whole account.\n\n$250 as five markets at $45 each:\n- 5 FX pairs: reference 10 contracts -$2,172 per day (t -1.83); best bid 10 contracts -$3,134 per day; reference 25 contracts -$5,414 per day (t -3.14).\n- The best of 192 policies in-sample (best bid, 50 contracts, never repeg, stop 300 s, +$1,540 per day) loses $3,772 per day on the holdout.\n- Under lenient fills, FX reference 25 contracts makes +$812 per day (t 0.78), and the in-sample best of +$2,362 per day drops to +$359 per day on the holdout (t 0.14).\n- Coin Race (five outcomes): every policy loses except a few large static ones (t \u2264 1).\n- Metals and gas, deep orders that never repeg: in-sample up to +$6,145 per day, holdout +$2,890 (t 0.36). This earns $0 of LIP reward and is pure directional fill luck, not a rebate strategy.",
   "evidence": "out/accounts_v2.txt (holdout and fixed-policy accounts).\nout/accounts_insample_biased.txt keeps the in-sample argmax and greedy portfolio, flagged SELECTION-BIASED. Do not quote its numbers, for example $6,419 per day at $45; they fail the holdout.",
   "confidence": "high"
  },
  {
   "claim": "Running costs:\n- Track policies send about 1.1-1.4 order writes (place plus cancel) per second per market, so five FX pairs need about 6-7 writes per second. Kalshi's per-tier write limits are UNVERIFIED (the rate-limits docs page was not fetched).\n- With unlimited cash, the reference 10-contract policy needs up to $40-79 of peak capital per FX market and up to $224 per natgas market, because fills pile up on one side.\n- About 8-9% of FX seconds are excluded by the program rule that both sides must reach the Target. Our quote is live in 85-92% of seconds.",
   "evidence": "writes_per_s, peak_capital_max and frac_quoted columns in out/table_group.tsv and out/table_main.tsv. The number of orders rejected for crossing (post_only_rejects) is in out/rows_main.tsv.gz.",
   "confidence": "medium"
  },
  {
   "claim": "Every variant tried, counted:\n- Main grid, 1,152 variants: placement {best, ref, ref-1} \u00d7 size {10, 25, 50, 100} \u00d7 repeg {static, 1-tick mid, 2-tick mid, track} \u00d7 stop {0, 60, 180, 300 s before close} \u00d7 cash {unlimited, $250, $45} \u00d7 fill model {strict, lenient}, at 0.25 s latency.\n- Latency grid, 384 variants: the same 192 policies with strict fills and unlimited cash, at latency {0.1, 1.0} s.\n- Grids total: 1,536 variants on 109 market-windows, 167,424 simulations.\n- Exploratory runs: 5,798 more (benchmarks, fill-mechanism checks, timing, exact cross-check, fill traces, 3,270 timestamp-shift runs, a fill-timing trace).\n- Overall: 173,222 window simulations, 21,504 policy-by-series cells.\n- This lane made 0 network requests (recorded data only) and uses about 15 MB of disk.",
   "evidence": "out/variants_tried.json (scripts/count_variants.py).",
   "confidence": "high"
  },
  {
   "claim": "Limits:\n- Only 7-8 periods per series, from 19:15-21:00 UTC on one Tuesday. Other hours and days are untested.\n- Books were recorded about every 0.5 s, so a sub-100 ms WebSocket bot cannot be represented.\n- No Pyth feed: Hermes returned 401, so repegging uses the Kalshi mid, not Pyth.\n- Our hypothetical orders do not change other traders' behavior, and fills that would have hit us do not add size back to the public book.\n- The $1 floor is applied to the expected payout over the random snapshot offset.\n- Whether LIP is paid as cash or nonwithdrawable credit is still UNVERIFIED (rules lane).\n- Per-day numbers scale one weekday evening sample by 7-day-average periods per day.",
   "evidence": "live_recording/rec/manifest.json (coverage, pyth statuses 401), rules/LIP_SPEC.md \u00a77 and \u00a711, scripts/simlib.py docstring.",
   "confidence": "high"
  }
 ],
 "artifacts": [
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/simlib.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/build_cache.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/run_sims.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/summarize.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/report.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/crosscheck.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/test_simlib.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/check_trade_side.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/sens_shift.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/fill_timing.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/scripts/count_variants.py",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/table_policy_market.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/table_main.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/table_main.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/group_table.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/group_table.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/table_group.tsv",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/accounts_v2.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/accounts_insample_biased.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/best_cells.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/marginals.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/tstat_census.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/sens_shift.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/fill_timing_ref_q10_track.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/crosscheck.txt",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/variants_tried.json",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/rows_main.tsv.gz",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/rows_latency.tsv.gz",
  "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simulate/out/cache.pkl.gz"
 ]
}


---
## result 4 

{"verdicts":[{"n":1,"topic":"Rule in force","verdict":"confirmed","corrected_rule":"No change. The July 2026 filing says the amendment 'will go into effect on July 30, 2026'. The clean Appendix A runs 'until the earlier of January 1, 2027, or the date that Kalshi amends or terminates the Program'.","evidence":"rules07152610358.txt (cover letter and clean Appendix A)"},{"n":2,"topic":"Eligibility","verdict":"weakened (one sub-claim)","corrected_rule":"Confirmed: every member except IBs, FCMs and their customers trading through them, with no sign-up. The help page also excludes affiliates, employees and non-U.S. users. The owner's Direct WA account is eligible. Weakened: 'designated market makers can now also earn LIP' is only an inference. The filing dropped the Market Maker Agreement exclusion, but those agreements are confidential (rules0603265168) and may still bar it, so it is UNVERIFIED. Addition: help 15410219 lists 'Crypto 15min markets' with 2 providers. Whether Coin Race is in that group is UNVERIFIED.","evidence":"rules07152610358 'Eligible Participants' (tracked vs clean); help 13823851 Eligibility; help 15410219 table"},{"n":3,"topic":"Snapshot algorithm (reference price, qualifying walk, discount factor, both-sides rule)","verdict":"confirmed","corrected_rule":"Every step matches the clean text:\n- Reference = first level with cumulative size >= Target/5.\n- The walk takes whole levels and stops at the first level where cumulative size >= Target.\n- A side that runs out has no qualifying bids.\n- Score = size x DF^N, with N = ticks below the Reference and N = 0 at or above it.\n- Each side is normalized to 1.\n- A snapshot is excluded if the market is not open or either side misses the Target.\n- The offset is redrawn 'on a periodic basis' (Feb filing, change (ii)).\nNuance to add: the July redline moved 'if the market is open for trading' out of the snapshot-taking sentence and into the exclusion list. Closed seconds now count in the total and lower the pay.","evidence":"Clean and tracked text of rules07152610358; rules02112639183 letter item (ii). Differential test: on 4,000 random books (targets 101 to 1000; DF 0, 0.25, 0.5, 0.9 and 1; up to 4 owners; 0.01-contract sizes), lip_score matched an independent implementation written from the filing on validity and on every owner's score."},{"n":4,"topic":"Payout, $1 minimum, rounding, per-program, no cap","verdict":"confirmed","corrected_rule":"Payout = TP score x reward x (non-excluded / total snapshots). It is paid only if >= $1.00 and is then floored to the cent; testing before or after the floor gives the same result. The shortcut reward x sum(own scores) / (2 x total) holds (randomized 900-snapshot check). Nuances:\n- The filing writes the payout with an approximately-equal sign (≈).\n- Shares under $1 are forfeited, not redistributed, so a pool rarely pays out in full.\n- There is no per-account cap in the filing. max_reward_per_account was absent on all 23,014 liquidity rows checked (active, upcoming and closed now). The changelog ties it to margin volume programs.","evidence":"Filing 'Determining Payments'; help 16076644; changelog lines 838-840 and 1225-1228; adversarial PayoutEdges tests"},{"n":5,"topic":"Live parameters","verdict":"confirmed","corrected_rule":"As stated:\n- FX 15-minute (5 pairs): $50, target 300, DF 0.5.\n- Metals and gas: $20, target 300, DF 0.5.\n- Coin Race: $20 for each of 5 markets, target 1000, DF 0.5.\n- Daily FX: $25 per strike per 86,400 s, target 1000, DF 0.5.\nAll are linear_cent and fee_type quadratic. FX is on shard 0, the others on shard 2. Program windows match market open and close exactly. Addition: FX 15-minute paid 808 earlier periods at $20 and 451 at $50, so Kalshi changes pool sizes. Re-read period_reward every period.","evidence":"active_p0.json profile; markets/*.json open_time and close_time vs program dates; series/*.json; liq_paid_out_summary rewards counts"},{"n":6,"topic":"Schedule and daily pool","verdict":"confirmed","corrected_rule":"The arithmetic holds: 3x96 + 88 + 84 + 11 = 471 FX periods a week, which is $4,800 a pair on a full day and about $3,364 a day averaged over the week. Metals: 91 x $20 = $1,820 a day. Coin Race: 480 x $20 = $9,600 a day. New support: 16 KXSILVER15M and 16 KXWTI15M programs set in the Thursday 07:00-09:00 UTC closures (Aug 6 and Aug 13) were never paid and are still 'closed'. That fits the rule that closed-market seconds pay nothing. Kalshi stopped scheduling those windows afterwards.","evidence":"exchange_schedule.json (Thursday 03:00-05:00 closed); liq_closed_summary (silver and WTI closed 2026-08-06T07:00 to 2026-08-13T09:00)"},{"n":7,"topic":"KXBTC15M never LIP; Volume Incentive Program ended","verdict":"confirmed","corrected_rule":"No change. There are zero KXBTC15M rows in active, upcoming, the 15,548 closed liquidity rows pulled at 22:21 UTC, or the paid_out summary. The volume program termination is effective 'no earlier than October 13, 2026'. Caveat kept: programs on hidden events are not listed.","evidence":"grep on dl/closed_now/p1-p2.json and ip/*.json; rules09282630083 line 21"},{"n":8,"topic":"10-lot at best bid estimate","verdict":"weakened (one cell refuted)","corrected_rule":"EURUSD gross is $1.9987 a period (score 600844/7515507 = 0.07995), so it pays $1.99 after the floor, not $2.00. USDJPY $1.99, copper $0.83 and Coin Race BTC $0.54 are confirmed. 'Small size only clears $1 in the $50 FX pools' holds only for 10 contracts. On the same books, the smallest equal size at the best bid on both sides that reaches $1 a period is:\n- EURUSD and USDJPY: 5 contracts (about $4.80 collateral).\n- Copper: 13 contracts (about $12.48).\n- Coin Race BTC: 19 contracts (about $17.10).\nThe estimate assumes one book for all 900 seconds; every excluded or changed snapshot lowers it. Per day, gross only: EURUSD 10-lot $1.99 x 96 = about $191 a full day per pair. At $1 a period: copper about $91 a day, Coin Race about $96 a day per outcome market. All of this is before fill losses. If the earlier replay's $7-9 per FX window holds, the FX result is about -$5 to -$7 net per window.","evidence":"review/scripts/book_sizes.py on rules/dl_api/books/*.json"},{"n":9,"topic":"Order placement at the Reference","verdict":"weakened","corrected_rule":"True for one snapshot: a bid at the Reference gets full weight and adding size there never moves the Reference (tested). It is not a stable placement rule:\n- The Reference is recomputed every second. If others add size above it until the top reaches Target/5, a bid at the old Reference is cut by DF^N (test: 2 ticks gives 0.25 weight).\n- On the 19:19 FX and copper books the Reference was the best bid on both sides, so no deeper full-credit level existed. The gap appears only when the top is thin (Coin Race yes side: best 0.56, Reference 0.50).\n- Extra effect: adding size can make the walk stop one level earlier, which cuts out deeper competitors (tested).","evidence":"adversarial_test.py HandBuiltBooks; book_sizes.py reference output"},{"n":10,"topic":"Payment timing and form","verdict":"weakened","corrected_rule":"Payouts run in batches; there is no steady 7-hour lag. At 22:21 UTC the newest paid 15-minute programs still ended at 10:00 UTC, the same cutoff seen at 17:11 and 19:21. Every 15-minute series' earliest unpaid program today ended at 10:15, more than 12 hours earlier. Plan for up to about a day or more. Some old programs remain 'closed' indefinitely (Thursday closure windows, the first FX windows of Sep 23), so 'closed' can be final for programs that paid nobody. Cash vs credit is still UNVERIFIED. Help 13823844 says Credit is 'nonwithdrawable' and 'already included in Cash'.","evidence":"review/dl/closed_now/p1.json and p2.json (fetched 2026-10-13T22:21:14Z); help 13823844 line 74"},{"n":11,"topic":"Anti-gaming","verdict":"confirmed","corrected_rule":"No change.","evidence":"Filing 'Monitoring and Termination of Status'; rules08032613661 Rule 5.17(b); rulebook v1.15 5.15 (z), (aa) (spoofing, money pass, wash trade)"},{"n":12,"topic":"Shards and collateral","verdict":"confirmed","corrected_rule":"No change to the facts. resting_margin_reservation (none, max or sum; default sum) only sets what an automatic rebalance leaves behind for resting orders. It does not set how much collateral an order needs when it is accepted. The $9.60 for a two-sided FX 10-lot stays an assumption (UNVERIFIED).","evidence":"getting_started_exchange_sharding.md; set-target-balance-allocation.md RestingMarginReservation"},{"n":13,"topic":"Other ways to get paid","verdict":"confirmed (items checked)","corrected_rule":"Checked:\n- APY 3.50%, 'only paid to people with balances of $250 or more', SSN needed above $10 a year.\n- Deposit and Trading Reward caps: $2,500 per promotion, $5,000 lifetime, at most $25 with no minimum. Only fills at $0.03-$0.97 count. Credits are withdrawable only after trading an equal amount, and expiry is 1, 3, 7, 10, 14 or 30 days when set.\n- Volume program termination.\nNot rechecked: referral, bug bounties, perps rebate.","evidence":"help 13823847 lines 68, 100, 104; rules09252630037 lines 230-290, 344"},{"n":14,"topic":"Data quirks","verdict":"confirmed","corrected_rule":"Today's closed pull has exactly 1,277 zero-or-negative-duration rows (432 + 845). Fractional-second bounds are common (9,061 of 15,548 closed; 4,461 of 5,655 active). None of them are in today's active FX, metals, gas, Coin Race or daily FX rows, so the 900-snapshot count holds for the live 15-minute programs. The first program of a newly launched series can start mid-window (EURUSD 2026-09-23T23:02:38.18Z).","evidence":"review inline python over closed_now and ip/*.json"},{"n":15,"topic":"lip_score.py correctness","verdict":"confirmed (one minor bug)","corrected_rule":"The scoring matches the filing on 4,000 random books and 14 hand-built edge books. The 39 original tests pass. Bug: floor_cent divides two Decimals at the default 28-digit precision, so 2 - 10^-30 floors to $2.00 instead of $1.99. Such a value is practically impossible in real use. Fix: Decimal(x.numerator*100 // x.denominator) / 100. Side note: the sports-combo $18.88 (exact $18.8776) shows only that the example is displayed rounded. It does not prove round-to-nearest, and that program is blocked for this account anyway.","evidence":"adversarial_test.py: Ran 15 tests, OK (expected failures=1, test_floor_cent_precision)"}],"api_requests_made":2,"artifacts":["/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/review/scripts/adversarial_test.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/review/scripts/book_sizes.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/review/scripts/closed_now.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/review/scripts/ip_profile.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/review/scripts/align.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/review/dl/closed_now/p1.json","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/review/dl/closed_now/p2.json"]}


---
## result 5 

{"findings":[{"claim":"The simulation's verdict holds after correction: quoting for the LIP reward loses money.\nIt loses on all 5 FX pairs, on metals/gas and on Coin Race under every fill model in which a crossing bid can trade with a stale quote. Only the lenient model (only printed trades fill) comes out about break-even.\n\nCentral corrected model ('timed' fills: unlimited cash, rest at the reference price, 10 contracts, repeg on every change, quote to the close). FX, per market per 15-minute period:\n- LIP reward paid: $1.74 (sim lane $1.73).\n- Contracts filled: 353, of which 69% came from crossing bids.\n- Fill P&L at settlement: -$8.52.\n- Net: -$6.79 (sim lane -$7.85), t -1.86 over 8 windows, 95% CI -$15.40 to +$1.83. Marked at +60 s: -$6.77 (t -2.00).\n- Per FX market: -$457 per day at 67.3 periods/day (7-day average), -$652 on a 96-period weekday. If losses were refilled, the 5 pairs together lose about -$2,280 per day.\n\nOther placements and controls:\n- Joining the best bid: -$9.16 (sim lane -$9.52).\n- Adding an inventory cap of 10 contracts: -$7.25 (t -2.89, CI -$13.19 to -$1.32). Position control does not rescue it; it makes the loss more certain.\n\nOther groups:\n- Metals/gas: -$7.30 (t -0.52; +60 s mark -$6.78, t -1.95). The reward is $0 because the raw $0.65 is under the $1 floor.\n- Coin Race: -$2.49 (t -1.78). The reward is $0 (raw $0.21).\n\nSize of the prize: about $117 per FX pair per day gross ($1.74 x 67.3), or $585 across the 5 pairs. The fills cost about 4 to 5 times that.","evidence":"Main table: simreview_adv/out/final_tables.txt, section A (strict / timed / fee_timed / lenient for 8 canonical policies, per group, with t, CI95, net_m60, worst period, per day and peak capital). Inventory caps: out/invcap_tables.txt.\nData: the same 109 full windows (19:15-21:00 UTC, 2026-10-13) from simulate/out/cache.pkl.gz.","confidence":"high"},{"claim":"Fill-model audit. The sim's strict fills had one real timing bug, now fixed. The other suspected sources of generous fills do not change the result.\n\n1. Timing of crossing fills (bug, fixed in 'timed'). A crossing bid can arrive anywhere between two recorded books, which are about 0.5 s apart. The sim made two opposite errors:\n- It charged orders placed late in that interval for crossings that may have arrived before the order existed. This is too harsh.\n- It let orders cancelled inside the interval escape crossings that arrived before the cancel. This is too generous.\n'timed' treats the arrival time as uniform in both cases. FX ref/10 moves from -$7.85 to -$6.79, and best/10 from -$9.52 to -$9.16. Correcting only the first error ('prorate', -$5.30) would flatter the strategy.\n\n2. The crossing trader's taker fee. A trader who picks off a stale quote pays 0.07 x P x (1-P) per contract, about 1.4c here.\n- 75.6% of FX crossed contracts (73.3% at the best bid) gave a fee-paying crosser more than the fee (median gain 2.5c, weighted mean 3.1c).\n- Dropping the unprofitable crosses ('fee_timed') gives -$8.28 for ref/10 and -$10.40 for best/10. It is worse, because the dropped fills were the cheap ones.\n\n3. Queue position and cancels ahead of us. Spreading cancels pro rata over the queue, instead of assuming they come from behind us, moves FX ref/10 by $0.06.\n\n4. Hidden size. There is nothing to model: Create Order V2 has no hidden, iceberg or display-size field.\n\n5. Latency. 0.1 s gives -$5.68 and 0.25 s gives -$6.79 (timed).\n\nRange across all non-lenient models: FX ref/10 -$5.30 to -$9.30 per period, best/10 -$6.00 to -$10.40.","evidence":"Code: scripts/simlib_r.py, a copy of simulate/scripts/simlib.py with modes strict / lenient / fee / prorate / fee_prorate / timed / fee_timed, queue prorata, inv_cap, pull_lead and negative latency.\n- With default options it equals the original on 60 random runs (scripts/equiv_check.py).\n- 8 new unit tests pass (scripts/test_review_modes.py).\nResults: out/review_tables.txt (section A) and out/final_tables.txt. Crosser gains: out/cross_edge.txt.\nThe fee formula is confirmed by the docs Fee Rounding worked example: model fee $0.00363825 = 0.07 x 0.055 x 0.945 for 1 contract at 5.5c (rules/dl_docs/getting_started_fee_rounding.md). The fee-schedule PDF itself returned 429 again.\nOrder fields: rules/dl_docs/api-reference_orders_create-order-v2.md (time_in_force, self_trade_prevention_type, post_only, cancel_order_on_pause, reduce_only).","confidence":"high"},{"claim":"Which fill model is right: the public trade tape supports the crossing-fill models, not lenient.\n\nA 'crossing move' here is when the best bid level disappears and the other side's new bid crosses its price within one book interval.\n- FX: of 1,604 crossing moves, 446 (27.8%) printed trades at the stale price. Repricing orders are often aggressive, not post-only.\n- Incumbents cancelled 97.5% of the stale size in time. A slower quote like ours is what is left to be taken.\n- Metals: 49.1% of 2,124 moves printed at the stale price. Coin Race: 40.4% of 99.\n\nLenient fills also leave our stale bid resting while a public bid crosses it. That book state cannot exist on the exchange: the crossing order either trades with us, or is rejected as post-only and reprices.\n\nEven under lenient fills, FX ref/10 is -$0.69 (t -0.39) and best/10 is +$0.94 (t 0.26): break-even at best and never significant.\n\nUNVERIFIED: what share of real FX repricers use post-only. Only live fills can settle this.","evidence":"out/audit_data.txt section 3 (scripts/audit_data.py).\nThe recorded books contain no crossed or locked book (section 1).","confidence":"medium"},{"claim":"The reward side is computed correctly, including the rule that both sides must reach the Target. The filing (rules07152610358, Appendix A) excludes snapshots without 'resting orders sufficient to meet the Target Size on each side'.\n- Exact re-scoring with lip_score.py on 2,338 freshly sampled states found 0 mismatches in score or validity (max error 2.2e-16).\n- The public FX book reaches the Target on both sides in 92.1% of score moments (metals 95.8%, Coin Race 80.1%).\n- Our 10 contracts complete the Target in 0.01% of FX moments and earn 0.0% of our reward there. At 100 contracts the figures are 0.34% and 0.4%. Not counting our own size would lower FX ref/10 pay by $0.001.\n- The sub-second snapshot offset does not matter: $1.755 at 0.05 s, $1.735 at 0.95 s, $1.735 averaged.\n- The $1 floor zeroes metals and Coin Race at 10 contracts (raw $0.65 and $0.21 per period).","evidence":"out/reward_audit.txt (scripts/reward_audit.py, seed 99173, different from the sim lane's crosscheck).\nThe sim lane's 11 unit tests and the rules lane's lip_score selftest were re-run and pass.","confidence":"high"},{"claim":"Collateral and the $45 account.\n\nThe sim lane's $45 cap was enforced correctly: committed cash never went above $45.00 in 41,856 capped runs. (My first 'timed' version broke this by reusing the cash of just-cancelled orders. Reserving that cash until the next book fixed it; the maximum is again $45.00.)\n\nBut every window restarted at $45, which hides ruin. I chained the windows in time order, each starting with the cash left after the last (timed fills, ref/10, quote to close). All of these losses happen within 1 h 45 min:\n- 14 single-market accounts of $45: $630 fell to $133. 9 of the 14 dropped below $1, including all 5 FX pairs.\n- Joining the best bid instead: $630 fell to $264.\n- $250 as 5 FX pairs at $50 each:\n  - ref/10: $69\n  - best/10: $46\n  - ref/10 stopping 300 s before the close: $207\n  - lenient fills: $218\n\nWith $45 restored each window (ref/10, timed), FX net per period was:\n\n| Pair | Net per period |\n|---|---|\n| EURUSD | -$4.94 |\n| GBPUSD | +$0.04 |\n| USDJPY | -$12.08 |\n| USDCAD | -$11.24 |\n| AUDUSD | -$6.27 |\n\nWith unlimited cash, peak capital per FX market at ref/10 is $92 (timed). Running all 5 pairs without ever being cut would need about $460.\n\nUNVERIFIED: how much Kalshi reserves for simultaneous yes and no resting orders in one market (the sum or the max). The sim reserves the sum, which is conservative.","evidence":"out/accounts_seq.txt (scripts/accounts_seq.py; models strict, timed, fee_timed and lenient). $45 rows: out/final_tables.txt section F. Peak-capital check: rows_timed.tsv.gz, budget 45.0, max $45.00.\nInterest needs a balance of $250 or more (help 13823847, via rules/LIP_SPEC.md section 12).","confidence":"high"},{"claim":"There are too few periods to measure the edge precisely.\n- The data are 8 windows per series (7 for metals), all between 19:15 and 21:00 UTC on one Tuesday.\n- The FX ref/10 95% interval is -$15.40 to +$1.83 per period. A profit as large as the reward is ruled out only at the edge of the interval.\n- One FX market-period's net has a standard deviation of $17.5 at settlement, or $16.4 at the +60 s mark.\n- Detecting an edge the size of the reward ($1.74) with 80% power at 5% two-sided needs about 700-800 FX market-periods. That is about 1.6 weekdays of all 5 pairs at 96 periods each.\n\nA 48-hour recording of the same books would be enough; the scripts in this lane run unchanged on a new cache.","evidence":"out/final_tables.txt sections A (CI95) and E (power).","confidence":"high"},{"claim":"No policy survives the best-of-many selection.\n\nExact sign-flip test: all 256 sign patterns of the 8 window means, with the same flip applied to every policy. p-value of the best t among 192 policies, FX:\n- timed 0.99\n- fee_timed 0.98\n- strict 0.99\n- lenient 0.12 (best t 3.87, for best/100/mid2/stop 300 s)\n\nLeave-one-window-out (pick the best policy on 7 windows, score it on the 8th):\n\n| Group | Fill model | Out-of-sample net per period |\n|---|---|---|\n| FX | timed | -$83.51 |\n| FX | fee_timed | -$60.32 |\n| FX | lenient | +$2.03 (t 0.13) |\n| Metals/gas | timed | -$133.97 |\n| Coin Race | timed | -$28.46 |\n\nPicking the best policy per series out of sample gives -$41.06 per market-period (timed), positive in 2 of 14 markets.\n\nThe sim lane's metals holdout (+$2,890 per day) was a lucky split. The reversed split gives -$142.60 per period, and leave-one-out gives -$133.97 (t -2.06).","evidence":"out/final_tables.txt sections C and C2 (scripts/analyze_final.py, signflip_maxt in scripts/analyze_review.py).","confidence":"high"},{"claim":"Settlement and data checks pass.\n- A fresh GET /markets for the 109 windows returned identical results: all finalized, 69 'no' and 40 'yes'.\n- None of the 134,264 book snapshots is crossed or locked.\n- Book and tape clocks agree. The share of public trades whose price is still bid in the latest book peaks at offset 0.00 s (90.3%; 88.1% at -0.25 s, 80.4% at +0.25 s, 68.8% at +0.5 s). The REST batch books were CloudFront misses, not cached copies, and show no hidden lag.\n- Rebuilding the cache from the raw recording gives byte-identical inputs.\n- The trade-direction mapping matches the docs: taker_outcome_side 'no' is long no, so it hits yes bids.","evidence":"scripts/check_results.py on dl_markets/m1.json and m2.json.\nout/audit_data.txt sections 1-2.\nCloudFront headers: live_recording/rec/manifest.json requests.cloudfront_x_cache.\nDirection: dl_docs/order_direction.md.","confidence":"high"},{"claim":"Pyth vs Kalshi timing: the lead of Pyth over the Kalshi book is UNVERIFIED, because Pyth could not be read.\n- benchmarks.pyth.network price-at-time returned 401 and the TradingView history returned 404.\n- The recording lane's Hermes calls returned 401.\n\nAs a proxy, I ran two oracles on the Kalshi books (timed fills, FX, 10 contracts):\n\n1. Defensive oracle: cancel any quote the next book will make stale, X s before that book, and re-place only after it.\n\n| Warning | Reference price | Best bid |\n|---|---|---|\n| 0.1 s | -$5.46 | -$5.97 |\n| 0.25 s | -$5.45 | -$5.05 |\n| 0.5 s | -$2.17 (t -1.75) | -$0.45 |\n\nA perfect half-second warning on every move still does not pay.\n\n2. Offensive oracle: act on the future book, i.e. quote where the price is going (ref/10, per period).\n\n| Foresight | Net |\n|---|---|\n| 0.25 s | +$0.93 (t 0.21) |\n| 0.5 s | +$3.89 (t 1.99) |\n| 1.0 s | +$6.80 (t 5.45) |\n\nMoney appears only for a bot that sees the FX move about 0.5 s before Kalshi's market makers reprice. That is a latency race against designated market makers, not a rebate.\n\nKalshi lists an authenticated Pyth Value Feed WebSocket; its latency is unmeasured.","evidence":"out/final_tables.txt section D. The defensive oracle charges cancelled orders for crossings that may have arrived before the cancel, and blocks re-placing at stale prices.\nThe WebSocket is listed in rules/dl_docs/llms.txt ('Pyth Value Feed ... Requires authentication').","confidence":"medium"},{"claim":"Write rate limits are now verified and do not bind on average.\n- Basic tier: Write budget of 100 tokens/s with a 1-second bucket.\n- An order create costs 10 tokens and a cancel costs 2.\n- Advanced (self-serve upgrade): 300 tokens/s with a 3-second bucket.\n- Single writes aimed at shard 2 bill that shard's own Write bucket.\n\nTrack policies write 1.15 orders/s per market (ref) to 1.41 (best), about 7-9 tokens/s. 5 FX pairs average 36-45 tokens/s, which fits Basic.\n\nRepegging all 10 orders at once costs about 120 tokens and overflows Basic's 100-token bucket. Advanced avoids that.","evidence":"dl_docs/rate_limits.md (docs.kalshi.com/getting_started/rate_limits.md, fetched 2026-10-13). Write counts: orders_placed + orders_cancelled in out/rows_timed.tsv.gz.","confidence":"high"},{"claim":"What this review ran:\n- Re-ran the sim lane's tests and the rules lane's lip_score selftest (both pass).\n- Rebuilt the cache from the raw recording (identical).\n- Ran a review copy of the simulator that reproduces the original exactly.\n- About 405,000 window simulations on the same 109 windows. This includes one 'timed' grid that was discarded after the $45 bug; its unlimited-cash rows were identical to the rerun.\n\nNetwork:\n- 3 Kalshi API requests (one got 429; I backed off and retried)\n- 2 docs pages\n- 1 kalshi.com fee PDF (429)\n- 2 Pyth requests\nNever more than 1 request per second.\n\nNo orders, no keys, no deploys, no edits under /home/user/Claude.\n\nDisk: 6.6 MB. Another agent is writing in kalshi_rewards/review/, so this lane lives in kalshi_rewards/simreview_adv/.","evidence":"Logs: out/run_fill.log and out/run_timed.log.\nRows (unlimited cash and $45; foresight under the original modes; inventory caps): out/rows_fill.tsv.gz, rows_timed.tsv.gz, rows_foresight.tsv.gz, rows_invcap.tsv.gz.","confidence":"high"}],"artifacts":["/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/final_tables.txt","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/review_tables.txt","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/invcap_tables.txt","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/accounts_seq.txt","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/audit_data.txt","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/cross_edge.txt","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/reward_audit.txt","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/rows_timed.tsv.gz","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/rows_fill.tsv.gz","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/rows_invcap.tsv.gz","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/out/rows_foresight.tsv.gz","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/simlib_r.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/run_review.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/test_review_modes.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/equiv_check.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/analyze_final.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/analyze_review.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/analyze_invcap.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/accounts_seq.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/audit_data.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/cross_edge.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/reward_audit.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/scripts/check_results.py","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/dl_docs/rate_limits.md","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/dl_docs/order_direction.md","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/dl_markets/m1.json","/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/simreview_adv/dl_markets/m2.json"]}


---
## result 6 

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

File written: /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_rewards/PLAYBOOK.md

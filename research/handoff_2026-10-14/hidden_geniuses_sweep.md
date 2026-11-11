# hidden_geniuses_sweep (workflow wf_98d97adc-9ab)



---
## result 0 

{
 "lane": "Polymarket bots and traders who published code AND a wallet or verifiable results (sweep run Oct 13, 2026, about 5-7 PM Pacific; wallet numbers read from Polymarket's public PnL/data APIs at that time)",
 "items": [
  {
   "name": "polymm (kachence) / Polymarket profile @b00k13 - sports and esports market-making + hedge arbitrage",
   "url": "https://github.com/kachence/polymm",
   "venue": "Polymarket (global), sports + esports moneylines",
   "method": "Fair price = sportsbook odds (the-odds-api, 9 books) with the vig removed by normalization (Shin's method was dropped after it overpaid favorites). Rest a limit BUY one cent above the best bid only when the quote is at least min_edge below fair (code default 5%; the live run used 7%). When one side fills, immediately bid the opposite outcome so Up+Down cost < $1.00 (locks about 7c/share); a hedge-seeker keeps chasing unfilled hedges. Cancel resting orders when fair moves (EDGE_LOST). 10-share orders, about $25 a bet. Esports (CS2, Valorant, Dota 2, LoL) carried the profit; non-esports lost.",
   "evidence_grade": "A",
   "evidence": "Author's proxy wallet is public: 0x1c5575dc20e4ea54d1bb09ccda72ccf8a3b684ce (resolved from polymarket.com/@b00k13 via gamma public-search). Polymarket user-pnl API on 2026-10-14 UTC: all-time PnL +$6,025.97; 5,143 markets traded; monthly curve Jan 7 2026 -$8 -> Feb 1 +$1,956 -> Mar 1 +$4,558 -> Apr 1 +$4,828 -> May 1 +$4,961 -> flat through Jul -> Oct 14 +$6,026. Matches the author's blog (kacho.io/polymarket-arbitrage-real-numbers): Jan 6-Apr 28 2026, 3,858 bets, $95,830 volume, 2,785 markets, net +$4,973: arbitrage legs +$8,293 (1,075 completed arbs), unhedged legs -$3,185, cancelled matches -$134, fees -$1. Win rate 47.5%. Fill rate collapsed 37.4% (Jan) -> 15.0% (Feb) -> 5.0% (Mar) -> 1.0% (Apr). Show HN 2026-07-21 (5 points, 3 comments). 113 stars, MIT.",
   "applicable_to_us": "Kalshi: yes, the rule is venue-agnostic (needs a live odds feed). Polymarket US: only where it lists the same sports markets (it launched sports-first). Note owner rule 2026-10-10a bans real money on sports; owner's Lab 6 found no taker edge vs Pinnacle, but polymm is maker-side with a 7% threshold and a hedge, a different test.",
   "still_works": "Author says the edge was real but decayed: odds were up to 30 minutes stale so bids got picked off when lines moved (a third of 2,555 matches moved 5+ points), and faster bots sat one cent ahead (fill rate 37% -> 1%). The posted Python is retired; he runs an unpublished Rust rewrite and still trades the wallet in small size (+$1,065 Jul-Oct 2026). Polymarket now charges a 5% sports taker-fee rate (makers 0, 15% rebate), which favors this maker-side design.",
   "reusable": "Yes. Clean async Python, MIT, 4 analytics scripts that reconcile any public wallet (capital_analysis.py, realized_pnl_by_month.py, position_breakdown.py, underdog_analysis.py). Needs your own odds source and Supabase. Clone was read as text only and deleted."
  },
  {
   "name": "Polymarket profile @1kto1m (wallet) plus the dev.to 'lkto1m' bot series (code links all dead)",
   "url": "https://dev.to/lkto1m/my-polymarket-trading-bot-strategy-across-11717-trades-5m15m1h-framework-explained-3gbl",
   "venue": "Polymarket (global), Bitcoin Up or Down 5-min and 15-min markets",
   "method": "Posts describe: maker-only limit orders at or just inside mid; entries only in the first 30-90 seconds of a 5-min candle; hard no-new-entry cutoff at T-90 s; unfilled orders cancelled after 30 s; minimum entry price raised from 70c to 72c after Feb 2026 fees; reference price is Chainlink Data Streams (the resolution oracle), not Binance; 15-min trades only when the 5-min signal agrees; no trading around FOMC/CPI/NFP. Wallet data shows something richer: 646 markets in a 4,000-fill sample, BUY 1,743 / SELL 2,257 (active in-and-out), mean fill $53, both sides bought in only 7% of markets.",
   "evidence_grade": "A for the wallet, D for the code (unverifiable link between the two; treat the posts as a possible content farm)",
   "evidence": "Wallet 0xa1d57d329227c75b12b09f927fb3d6d6ef8f1343 (resolved from @1kto1m): PnL API 2026-10-13: +$49,601 since first trade 2026-05-03 (May +$21.5k, Jun +$6.9k, Jul +$11.2k, Aug +$9.5k, Sep +$0.5k, Oct flat); 2,023 markets traded; 4,000 recent fills Jul 18-Oct 6 2026 = $212k volume, 95% Bitcoin Up/Down. Red flags: the dev.to posts claim 11,717 trades and only $292 total P&L over five months (EV $0.025/trade, 78 trades/day), which does not match this wallet; the posts link four different GitHub repos (Eixen30/polymarket-bot, 1kto1m/polymarket-bot, MalcolmMcGough/polymarket-trading-bot-scalping, Duclos76/confidence-surfing-bot) and all four are deleted; two near-duplicate posts; dev.to profile links a fifth GitHub account.",
   "applicable_to_us": "Kalshi: the timing rules (early-window maker entries, T-90 cutoff, 72c floor, oracle-feed reference) are portable to the owner's 15-min BTC desk as hypotheses. Polymarket US: only if 5/15-min crypto is listed there (not confirmed). Do not run any code from these links.",
   "still_works": "The wallet's monthly profit fell from +$21.5k (May) to about +$0.5k (Sep) and flat in Oct, consistent with decay. The posts themselves say the Feb 2026 fee change (taker fee up to about 1.56% at 50c, 500 ms taker delay removed) killed latency-arb takers and left maker-side bots.",
   "reusable": "Code: no (all repos gone). Rules: yes, as test hypotheses only."
  },
  {
   "name": "gabagool22 (wallet only) - both-sides maker on 5/15-min BTC and ETH Up/Down, Oct 2025-Feb 2026",
   "url": "https://polymarket.com/@gabagool22",
   "venue": "Polymarket (global), Bitcoin and Ethereum Up or Down 5m/15m/hourly",
   "method": "From the on-chain fills: buys BOTH outcomes of every market in tiny clips (mean fill $3.59, median $3.20), 100% BUY side (never sells; lets both legs settle), fills spread across the whole window (median 214 s between first and last fill in a market). Across 52 markets in an 80-minute sample the volume-weighted Up+Down cost per pair had median 99.2c (p10 95.9c, p90 103.5c; 60% of markets under $1.00), so the edge is sub-cent per pair times enormous volume, which only works as a resting maker (zero fee, rebates) and with inventory settled at $1. The replica repo strongca22-cpu/gabagool (Jan 26 2026, 0 results) codes it as: buy YES if ask < 0.48 and NO if ask < 0.48, pair cost cap 0.97, min_profit_margin 0.02, max 3 concurrent pairs; that is a cruder taker version, not what the wallet did.",
   "evidence_grade": "A for the wallet (on-chain), D for the replica code",
   "evidence": "Wallet 0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d. PnL API: first fill 2025-10-29; +$2,219 by Oct 30 2025, +$8,665 Nov 1, +$144,754 Dec 1, +$451,980 Jan 1 2026, +$724,229 Feb 1, +$868,862 Mar 1, unchanged since; last fill 2026-02-20 09:06 UTC. 28,620 markets traded. 4,000-fill sample on 2026-02-20 07:46-09:06 UTC: $14,347 volume, 2,179 BTC / 1,821 ETH fills, all BUY, both sides in 52 of 52 markets. Press coverage of a 15-min bot that turned $300 into $400k+ (Jan 2026) could not be tied to this handle.",
   "applicable_to_us": "Kalshi: the owner is already testing resting-bid pairs on 15-min BTC; this wallet is the existence proof that two-sided resting with sub-cent pair edge and no selling paid when there were no taker fees and little competition. Polymarket US: only if 15-min crypto is listed. Arena: yes.",
   "still_works": "Stopped on 2026-02-20, two weeks after Polymarket's fee/rebate overhaul (taker fee on 15-min crypto introduced Jan 6 2026; crypto taker rate now 0.07 x p(1-p), makers 0, 20% rebate) and as Telonex measured 46,945 wallets fighting over the same markets. The replica's taker-style 0.48/0.48 rule pays 1.75c/share fee at 50c, which is more than the 1-3c pair edge.",
   "reusable": "Replica code: readable Python but no backtest results, built by stitching four other repos; use only as a reference. The wallet's fill history is free to download from data-api.polymarket.com/activity?user=... for your own study."
  },
  {
   "name": "gopfan2 (wallet only) + open-source NOAA weather-bucket replicas (openclaw/simmer 'polymarket-weather-trader')",
   "url": "https://clawhub.ai/simmer/skills/polymarket-weather-trader",
   "venue": "Polymarket (global), daily high-temperature bucket markets by city",
   "method": "Replica rule: for each weather event, pull the NOAA (US) or Open-Meteo (international) forecast for the oracle station parsed from resolution_criteria, pick the temperature bucket that matches the forecast, buy that bucket when its price is below 0.15 (default entry), sell if it rises above 0.45 (default exit), size 5% of USDC capped at $2, max 5 trades per run, min 2 hours to resolution, 15% slippage cap, dry-run by default. What gopfan2 actually does is not published; the skill only says it is 'inspired by'.",
   "evidence_grade": "A for the wallet, D for the replica (no results)",
   "evidence": "gopfan2 wallet 0xf2f6af4f27ec2dcf4072095ab804016e14cd5817: PnL API +$1,664,698 all-time on 2026-10-13, climbing almost every month since Nov 2024 (+$222k Nov 28 2024 -> +$810k May 2025 -> +$1.18M Nov 2025 -> +$1.50M Apr 2026 -> +$1.66M Oct 2026) with drawdowns (e.g. -$244k in May-Jun 2025, -$182k Nov-Dec 2025); 2,048 markets; $256k currently in open positions. Replica skills report zero backtest or live P&L. A devgenius blog claims a $1,000 -> $24,000 weather bot but gives no wallet (not fetched, Medium 403). Note the Apr 2026 'hairdryer on a weather sensor' manipulation case shows the resolution risk.",
   "applicable_to_us": "Kalshi: yes, Kalshi lists daily high-temperature markets for many US cities, so the NOAA-vs-price rule is directly testable in the practice arena. Polymarket US: unknown listing. Low-frequency, so Kalshi fees matter less.",
   "still_works": "gopfan2 keeps earning in 2026 (+$137k since Jul 1), so forecast-vs-market mispricing in temperature buckets still exists for someone, but a $2-cap template with no track record is not that someone. Owner-side test needed: forecast error vs bucket prices on Kalshi history.",
   "reusable": "Yes as a hypothesis generator; the skill code is small and dry-run by default, but it wants a private key for live mode, so read it, never run it."
  },
  {
   "name": "Telonex research notebook: 'Top crypto traders on Polymarket 15-minute markets' (on-chain fills, code public)",
   "url": "https://github.com/telonex/research/blob/main/research/top_15m_crypto_traders/top_15m_crypto_traders.ipynb",
   "venue": "Polymarket (global), 15-min BTC/ETH/SOL/XRP Up or Down",
   "method": "Not a bot: a measurement of who wins. Week of Feb 2-8 2026, 2,688 resolved 15-min markets, 15.3M on-chain fills, $153M volume, 46,945 wallets. Only 36.8% of wallets finished the week positive; median wallet about -$3. Takers won 53% of fills but lost money overall; makers won 47% of fills but netted +$728,501 pre-fee. Top 10 wallets (truncated) made $61k-$271k in one week, most 61-97% maker share across 1,100-2,600 markets; two 'snipers' made $120k and $68k on just 11 and 8 markets. One 100%-maker wallet (0x82a9...c9a1) did 82,753 fills in 614 markets for +$39,337. Fill counts peak at minute 0; volume rises in the final minutes near $0 and $1.",
   "evidence_grade": "A (third-party on-chain data with published code; wallets truncated in the notebook)",
   "evidence": "Notebook pulls onchain_fills via the telonex Python client (free API key per README); outputs printed in the repo. Companion article telonex.io/research/top-crypto-traders-polymarket-15m. Repo: 6 stars, MIT.",
   "applicable_to_us": "Kalshi: the finding (makers win, takers lose, snipers with external price feeds win big on few markets) is exactly the owner's open question for the 15-min BTC desk and matches the owner's own result that model takes lose 3-4c/contract. Reusable method for the owner's Kalshi recorder data.",
   "still_works": "Measured after the Jan 2026 fee change, so the maker edge there is current as of Feb 2026. Pre-fee PnL; real taker results are worse, maker slightly better with the 20% rebate.",
   "reusable": "Yes: the notebook is a template for wallet-level maker/taker PnL attribution."
  },
  {
   "name": "kacho.io 5-minute crypto Up/Down order-book dataset (CC0) and the author's own BTC bot result",
   "url": "https://kacho.io/polymarket-5min-crypto-dataset",
   "venue": "Polymarket (global), 5-min Up or Down on BTC, ETH, SOL, XRP, DOGE, HYPE, BNB",
   "method": "Dataset, not a bot: 1-second top-of-book snapshots (best bid/ask both sides, resting size, bid depth within 5c) for about 89,000 five-minute markets, 26.8M rows, BTC from 2026-03-24 and six other coins from 2026-04-05, all to 2026-05-18, 99.8% coverage, 725 MB parquet. The author built a BTC bot on it: backtest 3-5% ROI after fees, live run lost about $600.",
   "evidence_grade": "B for the data (public, reproducible); C for the bot (author's statement, no wallet breakdown)",
   "evidence": "Hugging Face: huggingface.co/datasets/kachoio/polymarket-5-minute-crypto-up-down-markets; Kaggle mirror. Author is the polymm/@b00k13 operator whose main wallet is verifiable (see item 1). The -$600 live loss is self-reported.",
   "applicable_to_us": "Kalshi: directly useful as a free out-of-sample book history for the owner's 15-min BTC hypotheses (5-min markets are the faster cousin). Polymarket US: n/a for data.",
   "still_works": "Data is Mar-May 2026, post-fee regime, so fee math is realistic. The author's experience (backtest positive, live negative) is a warning about fill assumptions.",
   "reusable": "Yes, CC0."
  },
  {
   "name": "poly-maker (warproxxx) - maker-only political-market MM for liquidity rewards and rebates",
   "url": "https://github.com/warproxxx/poly-maker",
   "venue": "Polymarket (global), long-dated politics markets (e.g. Newsom 2028, Romania PM)",
   "method": "Fair value = depth-weighted microprice (3 levels) nudged by an EWMA of signed flow; reservation price = FV minus inventory skew (gamma 0.6-0.8); post-only bids at r - delta where delta = max(2 ticks, vol and toxicity terms); 5 regimes (QUIET, TRENDING, EVENT on a 5-6 tick jump or sweep, REDUCE_ONLY, HALTED); size at the market's rewardsMinSize on thin books; sticky repricing (ignore 2-3 tick FV jitter) to keep queue position; rank markets by reward pool + rebate pool vs vol/spread risk. Hard caps: $450 exposure, $40 daily loss kill.",
   "evidence_grade": "C (one documented live session with a small loss; no wallet published)",
   "evidence": "1.5k stars, 491 forks, MIT. TIPS.md records a real supervised session on two markets: Newsom -$5.27, Romania -$10.24, total about -$15.51, with a $4.1 taker fee on exit and a $5 adverse fill from a gapped book. README says 'can lose money' and the backtester is 'not yet built'. The GitHub handle's Polymarket profile (0x9728c4893e33b4c755fa17e9977cdf0fb073a491) shows 0 trades, so the session wallet is not public.",
   "applicable_to_us": "Kalshi: Kalshi's LIP rewards work differently and the owner's rewards playbook already found about -$457/day per FX pair, so only the microstructure pieces (regime detection, min-size on thin books, sticky quotes) transfer. Polymarket US: only if it runs a rewards program on listed markets. Arena: yes.",
   "still_works": "Economics as described by the author: rewards are a fixed daily pool split by score with diminishing returns past about a third of the pool; rebates are 20-25% of taker fees and come only with fills (adverse-selection risk). Author's net was negative on a $50 mandate.",
   "reusable": "Yes; the quoting and regime modules are pure functions designed for replay, well tested. Read-only clone, deleted."
  },
  {
   "name": "nothing-ever-happens (Sterling Crispin) - always buy NO under 65c on standalone non-sports markets",
   "url": "https://github.com/sterlingcrispin/nothing-ever-happens",
   "venue": "Polymarket (global), standalone yes/no non-sports markets",
   "method": "Scan standalone (non-grouped) yes/no markets excluding sports; buy NO when best ask < max_entry_price 0.65; 2% of cash per trade (min $5); hold to resolution and auto-redeem every 30 min; paper mode unless BOT_MODE=live, LIVE_TRADING_ENABLED=true and DRY_RUN=false. No stop, no sell.",
   "evidence_grade": "C (base-rate statistics only; no wallet, no live P&L)",
   "evidence": "981 stars, 108 forks, CC0, HN 471 points (2026-04-13). Decrypt (2026-04-15): Polymarket's accuracy page says 73.3% of resolved markets end NO; Decrypt's own 2,300-position check found 73.5% NO for markets open 90-180 days but only about 52% for markets under one week. Crispin had not published a wallet or profits; a later MEXC/BitcoinEthereumNews piece headlined that the creator 'keeps losing money' (unverified). README calls it 'mostly a meme'.",
   "applicable_to_us": "Kalshi: testable on the owner's lab4 history (it is the mirror of the owner's 'near-certain grind' test). Polymarket US: yes if long-dated event markets are listed. Capital is locked for months.",
   "still_works": "The 73% base rate is a selection artifact (markets are written about things that might happen); buying NO at up to 65c only pays if the realized NO rate in that price band beats 65%, which nobody has shown. Short-dated markets are near 50/50.",
   "reusable": "Yes, small Python, paper mode default, includes wallet_history.py to audit any wallet."
  },
  {
   "name": "theflowp_ (Reddit r/Daytrading): bot to farm Polymarket sponsored liquidity rewards at 200% APR",
   "url": "https://reddit.sentinel-team.org/posts/1rdg33c/snapshots/2026-02-27T22%3A12%3A05.0165Z",
   "venue": "Polymarket (global), reward-sponsored event markets",
   "method": "Rewards sampled every 60 s; per-order score = ((max_spread - distance_from_mid) / max_spread)^2 x size, max_spread typically 3.5c, two-sided quoting worth about 3x; discover markets via CLOB, quote both sides inside the band, cancel in <100 ms when mid approaches. Simulation: $2,000 per market; top-4 markets about $78/day on $16k (178% APR); 15 markets $84/day on $60k; one market ('Greg Hull' primary) $44/day at 83.5% pool share; worst case -$296 on a $4k position.",
   "evidence_grade": "C (author's simulation; no code, no wallet)",
   "evidence": "Post 'I built a bot to farm Polymarket's sponsored rewards (200% APR)', 29 points, 16 comments. No GitHub, no address. Commenters note picked-off fills and a 70/30 bid/ask imbalance as a trap signal.",
   "applicable_to_us": "Polymarket US only if rewards exist there; Kalshi LIP already judged NO-GO by the owner. Arena: yes.",
   "still_works": "Pool-share math means returns fall as more bots join; the Telonex 'Jesus market' study measured active makers doubling (302 -> 639) within a day of a $70k reward drop.",
   "reusable": "Formula only."
  },
  {
   "name": "realfishsam/prediction-market-arbitrage-bot (r/algotrading, 324 points) - Polymarket vs Kalshi YES/NO pairing",
   "url": "https://github.com/realfishsam/prediction-market-arbitrage-bot",
   "venue": "Polymarket (global) + Kalshi",
   "method": "Match outcomes across venues by fuzzy name score >= 0.7 (pmxt library), compute YES(Poly) + NO(Kalshi) and the reverse, trade when combined cost < $1 by at least minProfitCents (config default 0.001, README default 1c), skip legs priced <= 0.01, aggressive mode goes 'ALL IN'; the author exits when the spread closes rather than holding to settlement, aiming for about 10 turns a month. Ignores fees, gas and slippage by its own README.",
   "evidence_grade": "C (self-reported 1.5-4.5% spreads; no dollars, no wallet; top comment notes about $20 at stake)",
   "evidence": "Reddit post 2026-01-19, 324 points, 88 comments. dev.to write-up says spreads of 1.5-4.5% on Fed and election markets. Top comment (174 points): Kalshi taker fee = ceil(0.07 x C x P x (1-P)) eats most of a 2-5c spread; legging and liquidity risk; author only had about $20 deployed.",
   "applicable_to_us": "Kalshi: yes for the Kalshi leg; the Polymarket leg would have to be Polymarket US, which lists fewer markets. Owner already has a cross-venue sweep in progress.",
   "still_works": "After Kalshi's taker fee and Polymarket's category fees (politics 0.04 rate), a 2-5c gross spread is mostly fee; needs maker fills on at least one leg.",
   "reusable": "Small Node code, MIT; useful mainly for the matcher."
  },
  {
   "name": "thesoulcrancerdev/poly-trading-strategies + 'DeltaPulse $500/day' (dev.to) - EndCycle Sniper 'for sale', wallet it cites just lost $22.6k",
   "url": "https://github.com/thesoulcrancerdev/poly-trading-strategies",
   "venue": "Polymarket (global), BTC Up or Down 5/15-min",
   "method": "'TWAP-aware EndCycle Sniper': in the last part of a short window buy the dominating side while it still trades below $1, judged on the time-weighted price path; 'Momentum Spike Sniping' hits dislocations after a sharp move. The strategy itself is 'Available for Sale' via Telegram; README claims 93% win rate and $7,444 P&L from a UI snapshot and admits 'Displayed account figures are UI snapshots, not a verified track record.'",
   "evidence_grade": "D for the code (no runnable strategy; sales funnel); the cited wallet is A-grade evidence AGAINST it",
   "evidence": "README links profile @moneyforll but prints wallet 0x85fc9f25299cafb649700d9034dda5a48f408700 (the @moneyforll profile actually resolves to 0x04c2b85b8388e6255146b030f1231bcde3ffb374). PnL API for the README wallet: +$7,819 Jul 1, -$1,062 Aug 1, +$10,778 Sep 1, +$17,945 Oct 1, then -$4,646 on Oct 13 2026, i.e. about -$22,600 in 13 days; 1,059 markets; recent fills are $100-193 BUYs at 51-55c on both sides of 15-min BTC, 1,475 buys vs 25 sells. The DeltaPulse post is templated text with no rule and links the same author's Telegram/YouTube.",
   "applicable_to_us": "No. Avoid.",
   "still_works": "The wallet the seller points to blew up in October 2026.",
   "reusable": "No."
  },
  {
   "name": "strongca22-cpu/gabagool - replica of the gabagool22 pair-buying idea (Jan 2026)",
   "url": "https://github.com/strongca22-cpu/gabagool",
   "venue": "Polymarket (global), 15-min BTC/ETH/SOL Up or Down",
   "method": "Buy YES when ask < 0.48 and NO when ask < 0.48 (both legs), pair cost cap 0.97, min_profit_margin 0.02, max 3 concurrent pairs, auto-redeem and position merge; backtest assumes 0.5% slippage and 0.1% fee (real crypto taker fee is 0.07 x p(1-p) = 1.75c at 50c, 17x the assumption).",
   "evidence_grade": "D",
   "evidence": "No results, no wallet; built 2026-01-26 by combining four other repos (discountry, Trust412, warproxxx, lorine93s). 79 files, no binaries.",
   "applicable_to_us": "Arena only; the fee assumption makes the backtest meaningless.",
   "still_works": "As a taker it cannot work at current fees; as a maker it is the gabagool22 pattern, which stopped Feb 2026.",
   "reusable": "Reference only."
  },
  {
   "name": "retrovaliks/polymarket-btc-5min-trading-bot - 'public' bot with Premium funnel, 47 binaries in repo",
   "url": "https://github.com/retrovaliks/polymarket-btc-5min-trading-bot",
   "venue": "Polymarket (global), 5-min BTC",
   "method": "NautilusTrader-based BTC 5-min bot; public tier 'not claimed (educational)', Premium claims '98.8%+ win rate' trained on '200,000+ trades', proof 'shared only on a call'.",
   "evidence_grade": "D",
   "evidence": "README: proof only in private meeting via Telegram @RetroValix. The clone contained 47 binary files (.pyc/.so etc.), which is a red flag for a Python repo. No wallet.",
   "applicable_to_us": "No. Do not run.",
   "still_works": "n/a",
   "reusable": "No."
  },
  {
   "name": "HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits - Rust toolkit, prebuilt binaries, managed/copy-trading funnel",
   "url": "https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits",
   "venue": "Polymarket, Kalshi and 18 other venues (adapters)",
   "method": "Ten strategy bots (copy-trading, cross-market arb that trades only when the gap exceeds round-trip fees, market making, etc.) on one execution core; quick start is 'grab a prebuilt binary'; 'PnL Profit live' badge links to pnlpro.fit; 'Managed / copy trading (currently closed)'.",
   "evidence_grade": "D",
   "evidence": "No wallet, no results in repo; 10 Telegram links in README; distribution by binary release.",
   "applicable_to_us": "No for running; the adapter list is a reference.",
   "still_works": "n/a",
   "reusable": "No (binary distribution of a wallet-signing tool)."
  },
  {
   "name": "aulekator/Polymarket-BTC-15-Minute-Trading-Bot",
   "url": "https://github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot",
   "venue": "Polymarket (global), 15-min BTC",
   "method": "Weighted vote of spike detection (SPIKE_THRESHOLD 0.15), Coinbase/Binance divergence (DIVERGENCE_THRESHOLD 0.05), Fear & Greed sentiment, Deribit put/call ratio and order-book processors; $1 max per trade, 30% stop loss, 20% take profit; paper mode; Redis-controlled live switch 'not stable yet'.",
   "evidence_grade": "D",
   "evidence": "595 stars, 179 forks, 4 commits; FAQ claims '~75% win rate in early runs' with no data; README pushes Telegram DM; 'feedback' ML folder is a placeholder.",
   "applicable_to_us": "Arena only.",
   "still_works": "Unknown; no evidence it ever worked.",
   "reusable": "Data-source adapters only."
  },
  {
   "name": "casatrickdev/polymarket-trading-bot v3.2 (formerly casatrick) - arbitrage, DipArb, copy trading, Telegram-branded",
   "url": "https://github.com/casatrickdev/polymarket-trading-bot",
   "venue": "Polymarket (global), BTC 5/15-min and copy trading",
   "method": "Fee- and gas-aware YES+NO arbitrage executed sequentially with unwind on partial fill; 'DipArb' buys a dipped side then hedges when combined cost < threshold; copy trading filtered by leaderboard win rate, PnL, profit factor; exposure caps and wallet circuit breakers; JSONL order-book backtester. Earlier listing: trades the final 60 seconds when a side is > 0.95.",
   "evidence_grade": "D",
   "evidence": "No wallet, no P&L; 'Created by @casatrick (t.me)'; original repo path is gone (renamed). Sibling-lane clone read as text only.",
   "applicable_to_us": "Arena only.",
   "still_works": "Unknown.",
   "reusable": "Risk-control patterns readable; strategy unproven."
  },
  {
   "name": "gnanam1990/polymarket-copy-bot - copy top wallets with ROI filter",
   "url": "https://github.com/gnanam1990/polymarket-copy-bot",
   "venue": "Polymarket (global)",
   "method": "Track listed wallets (20 recent trades each), copy only entries with min_profit_pct 30 (max entry about 77c), max_entry_price 0.70, min 0.03, max 20 open positions; paper/live; Flask dashboard.",
   "evidence_grade": "D",
   "evidence": "No results, no wallet. MIT.",
   "applicable_to_us": "Polymarket US only if the same wallets trade there (they do not; global wallets are not visible on the US venue). Kalshi has no public wallets to copy.",
   "still_works": "Copy trading on-chain lags the leader by seconds to minutes; the SSRN paper found winners are early makers, so copying late at worse prices is the losing side.",
   "reusable": "Small; fine as a reference."
  },
  {
   "name": "ent0n29/polybot (+ AWARE) - Java trading infrastructure and 'strategy reverse-engineering' from user trade history",
   "url": "https://github.com/ent0n29/polybot",
   "venue": "Polymarket (global)",
   "method": "Java 21 microservices: execution (paper/live), market making runtime, ClickHouse/Redpanda ingestion of any user's trades, replication scoring that measures how well a strategy reproduces a target wallet's fills.",
   "evidence_grade": "D",
   "evidence": "No P&L, no wallet; 238 files, no binaries, no funnel words.",
   "applicable_to_us": "The ingestion + replication-scoring idea is reusable for studying gabagool22 / gopfan2 fills on Kalshi-like data; running it is heavy.",
   "still_works": "n/a",
   "reusable": "Yes as architecture reference."
  },
  {
   "name": "chainstacklabs/polymarket-alpha-bot (Alphapoly) - LLM-found covering portfolios across correlated markets",
   "url": "https://github.com/chainstacklabs/polymarket-alpha-bot",
   "venue": "Polymarket (global), politics/event groups",
   "method": "Fetch market groups, have an LLM extract and validate logical implications (if B then A), compute cost and expected profit of hedging pairs at live prices, buy pairs where the combined cost is below the guaranteed payout; trades via deposit wallets (signature type 3).",
   "evidence_grade": "D",
   "evidence": "Vendor demo (Chainstack); no results or wallet. This is the combinatorial-arbitrage idea the IMDEA paper found worth about $40M historically.",
   "applicable_to_us": "Polymarket US only if it lists multi-outcome groups; Kalshi has mutually exclusive series where the same sum-to-one check applies.",
   "still_works": "The academic study shows single-market mispricings close in seconds; cross-market ones persist longer but need capital locked to resolution and correct logic.",
   "reusable": "Yes, readable Python/Node."
  },
  {
   "name": "ImMike/polymarket-arbitrage - Polymarket + Kalshi scanner with dashboard",
   "url": "https://github.com/ImMike/polymarket-arbitrage",
   "venue": "Polymarket + Kalshi",
   "method": "Scan 5,000+ markets, match across venues, flag YES/NO combos under $1 after fees; simulation mode.",
   "evidence_grade": "D",
   "evidence": "README's only numbers ('99.6% win rate, $573 profit') are from simulated data by its own caption.",
   "applicable_to_us": "Scanner idea only.",
   "still_works": "n/a",
   "reusable": "Reference."
  },
  {
   "name": "freshtechbro/openpolytrader - event-sourced near-zero-risk YES+NO arbitrage runtime",
   "url": "https://github.com/freshtechbro/openpolytrader",
   "venue": "Polymarket (global)",
   "method": "Strategy labels: near_zero (paired YES+NO on one market with spread/depth/staleness gates), ev (one-sided from calibrated probability with edge thresholds and notional caps), plus two more; 97% test coverage; ops dashboard.",
   "evidence_grade": "D",
   "evidence": "No results, no wallet; 549 files, no binaries, no funnel.",
   "applicable_to_us": "Engineering reference only.",
   "still_works": "Same-market YES+NO under $1 on Polymarket closes in about 3.6 s median per the UC thesis; it is a latency race.",
   "reusable": "Yes as code quality reference."
  },
  {
   "name": "tufstraka/polybot - multi-market relationship arbitrage",
   "url": "https://github.com/tufstraka/polybot",
   "venue": "Polymarket (global)",
   "method": "If mutually exclusive outcomes sum > 100c sell both; if B implies A then P(B) <= P(A); min_discrepancy 2% while the README itself says fees need > 4%.",
   "evidence_grade": "D",
   "evidence": "4 stars; projections only; the README's 'good arbitrage' example breaks even.",
   "applicable_to_us": "No.",
   "still_works": "n/a",
   "reusable": "No."
  },
  {
   "name": "Drakkar-Software/OctoBot-prediction-market",
   "url": "https://github.com/Drakkar-Software/OctoBot-prediction-market",
   "venue": "Polymarket (global)",
   "method": "Copy a chosen profile with a budget and market whitelist (all three features marked work-in-progress); YES+NO under $1 arbitrage 'under development'.",
   "evidence_grade": "D",
   "evidence": "117 stars, GPL-3; nothing finished.",
   "applicable_to_us": "No.",
   "still_works": "n/a",
   "reusable": "No."
  },
  {
   "name": "Z1xus/portent - YAML-manifest signal bot (model-release watch)",
   "url": "https://github.com/Z1xus/portent",
   "venue": "Polymarket (global)",
   "method": "Poll an external API (e.g. OpenAI model list), when a condition matches buy YES fill-or-kill up to a max price (example 0.90, $10), pick the cheapest of several date-window markets.",
   "evidence_grade": "D",
   "evidence": "0 stars, no results; example manifests only.",
   "applicable_to_us": "Kalshi: the pattern (API-watch then market order on a resolution-source event) is portable to any 'announcement' market; it is a speed race.",
   "still_works": "n/a",
   "reusable": "Pattern only."
  },
  {
   "name": "danstett/openclawpoly - BTC 5/15-min momentum template (Binance momentum, dry-run default)",
   "url": "https://github.com/danstett/openclawpoly",
   "venue": "Polymarket (global), BTC 5/15-min",
   "method": "Binance momentum signal; --live flag for real trades.",
   "evidence_grade": "D",
   "evidence": "25 files including 1 binary; no README content, no results.",
   "applicable_to_us": "No.",
   "still_works": "n/a",
   "reusable": "No."
  },
  {
   "name": "ionic-typing/orbitron-polymarket-system - Go bot with copy trading and multi-wallet",
   "url": "https://github.com/ionic-typing/orbitron-polymarket-system",
   "venue": "Polymarket (global)",
   "method": "Pluggable algorithmic engine + copy trading controlled from terminal/browser/Telegram.",
   "evidence_grade": "D",
   "evidence": "No results, no wallet.",
   "applicable_to_us": "No.",
   "still_works": "n/a",
   "reusable": "No."
  },
  {
   "name": "qoery-com/pmxt - cross-venue prediction market library (Polymarket, Kalshi)",
   "url": "https://github.com/qoery-com/pmxt",
   "venue": "Polymarket + Kalshi (library)",
   "method": "Unified market/order API used by the realfishsam arb bot; no strategy.",
   "evidence_grade": "D (tooling)",
   "evidence": "15 MB clone, no claims.",
   "applicable_to_us": "Kalshi + Polymarket US client plumbing, if it supports the US venue (not checked).",
   "still_works": "n/a",
   "reusable": "Yes as a library candidate (review before use)."
  },
  {
   "name": "leolopez007/polymarket-trade-tracker - audit any wallet's realized/unrealized PnL and maker/taker role",
   "url": "https://github.com/leolopez007/polymarket-trade-tracker",
   "venue": "Polymarket (global), tooling",
   "method": "For any address: trade history, realized and unrealized PnL, maker vs taker identification, charts, JSON export.",
   "evidence_grade": "D (tool, no strategy)",
   "evidence": "Open source web tool; no funnel.",
   "applicable_to_us": "Yes for due diligence on any 'proof' wallet a seller posts (this sweep used Polymarket's own user-pnl-api and data-api instead).",
   "still_works": "n/a",
   "reusable": "Yes."
  },
  {
   "name": "aemery13/polymarket-intel - MCP/REST that classifies wallets bot vs human and scores edge 0-10",
   "url": "https://github.com/aemery13/polymarket-intel",
   "venue": "Polymarket (global), tooling",
   "method": "Daily snapshot re-scores the top-50 leaderboard wallets; streams open positions.",
   "evidence_grade": "D (tool)",
   "evidence": "Repo exists (1 MB); scoring method not validated.",
   "applicable_to_us": "Research helper only.",
   "still_works": "n/a",
   "reusable": "Maybe."
  },
  {
   "name": "chudi.dev (GitHub: Citability) - 5-min BTC bot on the Binance-to-Polymarket repricing lag",
   "url": "https://chudi.dev/blog/how-i-built-polymarket-trading-bot",
   "venue": "Polymarket (global), 5-min BTC Up or Down",
   "method": "Trigger when BTC moves >= 0.3% within a 60-second rolling window on Binance aggTrade; post-only maker order on the matching Up/Down token; $5-15 per trade; guard against secs_remaining <= 0. Claims Polymarket reprices 30-90 s after Binance.",
   "evidence_grade": "C",
   "evidence": "23 real-money trades 2026-02-13 to 02-16; author explicitly declines to publish win rate or P&L (sample too small). No repo, no wallet.",
   "applicable_to_us": "Kalshi: the owner already tested spot-lead takes (no edge, -3 to -4c/contract); this is the maker variant of the same idea.",
   "still_works": "The 500 ms taker delay removal and fees in Feb 2026 are said to have ended the pure latency version; the dev.to series claims maker-side survived.",
   "reusable": "Rule only."
  },
  {
   "name": "Paper: 'Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets' (IMDEA, AFT 2025)",
   "url": "https://arxiv.org/abs/2508.03474",
   "venue": "Polymarket (global), all markets Apr 2024-Apr 2025",
   "method": "Measures two arbitrage types from on-chain order books: market-rebalancing (YES+NO != 1 within one market) and combinatorial (logically related markets mispriced); heuristic reduction to make cross-market comparison tractable.",
   "evidence_grade": "A (academic, on-chain)",
   "evidence": "About $40M realized arbitrage profit extracted over the year studied. No code or dataset linked on arXiv.",
   "applicable_to_us": "Shows the size of the pie and that it is captured by fast actors; useful framing for Polymarket US multi-outcome markets.",
   "still_works": "Competition has grown since 2025; same-market gaps close in seconds.",
   "reusable": "Method description only."
  },
  {
   "name": "Paper: Stanford/SMU 'Polymarket 5-minute bitcoin contracts are being manipulated' (Dai, Jia, Yu, Jul 2026)",
   "url": "https://arxiv.org/html/2606.31675v1",
   "venue": "Polymarket (global), 5-min BTC Up or Down (launched 2026-02-12)",
   "method": "Finding, not a strategy: bursts of one-sided Binance spot trading in the final 10 seconds move the Chainlink-averaged settlement price by about 2.5 bp and revert within 10 s; net order flow in the last 10 s rose about 50% after launch.",
   "evidence_grade": "A (academic, market data)",
   "evidence": "About 821 of 243,000 traders (1 in 300) made about $8.2M in pushed cycles and broke even otherwise; retail bore 93% of losses in manipulated cycles. Signature 'much attenuated' in 15-minute contracts.",
   "applicable_to_us": "Kalshi 15-min BTC: explains why late-window takes near 50c are dangerous and why the owner's recorder should log the last-10-second spot path; also a legal red line, not a strategy.",
   "still_works": "Authors recommend lengthening settlement windows; Polymarket's response not found.",
   "reusable": "No (illegal pattern); defensive use only."
  },
  {
   "name": "Paper: 'Who wins and who loses in prediction markets? Evidence from Polymarket' (Akey, Gregoire, Harvie, Martineau, CEPR DP21615, May 2026)",
   "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6443103",
   "venue": "Polymarket (global), 588 million trades",
   "method": "Finding: the top 1% of users capture 76.5% of profits; winners supply liquidity with limit orders that resolve favorably; losers take liquidity with market orders; monthly performance only weakly persistent; insider trading does not explain the biggest winners. Bloomberg's follow-on (Apr 2026): about 800 bot-like accounts each cleared $100k+, together about $131M, entering earlier at better prices; 100,000+ accounts lost $1,000+.",
   "evidence_grade": "A (academic)",
   "evidence": "HN 173 points; abstract via CEPR/HEC. Full text paywalled (SSRN 403 here).",
   "applicable_to_us": "All venues: be the resting limit order, not the market order. Matches the owner's own Kalshi finding that model takes lose.",
   "still_works": "Structural.",
   "reusable": "Framing."
  },
  {
   "name": "Telonex research: effect of a $70k sponsored liquidity reward on the 'Jesus returns' market (Feb 17 2026)",
   "url": "https://telonex.io/research/sponsored-liquidity-rewards-jesus-market",
   "venue": "Polymarket (global), one long-dated market",
   "method": "Measurement for reward farmers: after the reward, active makers 302 -> 639 in a day, top-5 maker share 56.5% -> 36.9%, top-of-book depth 23.5x, spread already at the 0.001 tick floor so no spread income; reward-farmer profitability after adverse fills was not measured.",
   "evidence_grade": "A (on-chain measurement)",
   "evidence": "Notebook in github.com/telonex/research (MIT).",
   "applicable_to_us": "Shows rewards get competed away within hours; relevant if Polymarket US runs rewards.",
   "still_works": "n/a",
   "reusable": "Method."
  },
  {
   "name": "UC thesis (Jiaxin Yang): algorithmic arbitrage and insider trading in Polymarket NBA markets",
   "url": "https://escholarship.org/uc/item/67x6v3qd",
   "venue": "Polymarket (global), NBA game markets",
   "method": "Single-market YES+NO mispricings resolve in a median of about 3.6 seconds; Isolation Forest to flag insider-like trades.",
   "evidence_grade": "B (academic; PDF not text-extractable here, numbers from the search abstract)",
   "evidence": "Thesis PDF 2.6 MB; no code link found.",
   "applicable_to_us": "Confirms same-market arb is a sub-5-second race; not for a Railway-hosted bot.",
   "still_works": "n/a",
   "reusable": "No."
  },
  {
   "name": "Polymarket all-time profit leaderboard (public API) - biggest wallets, none with public code",
   "url": "https://lb-api.polymarket.com/profit?window=all&limit=25",
   "venue": "Polymarket (global)",
   "method": "Reference list of verifiable winners with no published method: Theo4 0x56687bf447db6ffa42ffe2204a05edaa20f55839 $22.05M; swisstony 0x204f72f35326db932158cba6adff0b9a1da95e14 $18.42M; Fredi9999 0x1f2dd6d473f3e824cd2f8a89d9c69fb96f6ad0cf $16.62M; RN1 0x2005d16a84ceefa912d4e380cd32e7ff827875ea $12.95M; kch123 0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee $11.35M (as of 2026-10-13).",
   "evidence_grade": "A for the numbers, D for method (none published)",
   "evidence": "Polymarket's own leaderboard API; fills for any of them are downloadable from data-api.polymarket.com/activity?user=<address>.",
   "applicable_to_us": "Study material only; several are election whales.",
   "still_works": "n/a",
   "reusable": "Addresses are public data for your own fill analysis."
  },
  {
   "name": "Polymarket fee schedule (Oct 2026) - the number that decides which of the above still work",
   "url": "https://docs.polymarket.com/polymarket-learn/trading/fees",
   "venue": "Polymarket (global)",
   "method": "Taker fee per share = feeRate x p x (1-p): crypto 0.07 (1.75c at 50c, about 3.5% of a 50c price), sports 0.05, politics/finance/tech 0.04, economics/culture/weather 0.05, geopolitics 0. Makers pay 0 and receive rebates: crypto 20%, sports 15%, others 25% of taker fees, paid daily. Introduced on 15-min crypto on 2026-01-06; a 500 ms taker delay was removed around Feb 2026.",
   "evidence_grade": "A (official docs)",
   "evidence": "Docs page plus The Block / Cointelegraph (2026-01-06). dev.to fee analysis (emilanielsen) concludes taker bots targeting about 1% per trade were wiped out; maker strategies survive only if rebates stay meaningful.",
   "applicable_to_us": "Explains why every surviving Polymarket crypto bot in this sweep is maker-side; Kalshi's taker fee (0.07 x C x P(1-P) rounded up) is the same shape.",
   "still_works": "Current as of this sweep.",
   "reusable": "Yes."
  }
 ],
 "notes": "What is actually proven (Grade A, third-party checkable on Polymarket's public user-pnl-api / data-api, read Oct 13 2026 about 5-7 PM Pacific): (1) polymm/@b00k13 is the only Polymarket bot in this lane with BOTH public code and a public wallet: +$6,026 lifetime, 5,143 markets, and the blog's trade-level numbers reconcile with the chain; it made money as a maker with a 7% edge threshold plus an immediate hedge, and it decayed because odds were stale and faster bots took the queue. (2) Three wallets with huge verified profits but no code: gabagool22 +$868,862 (Oct 29 2025 to Feb 20 2026, both-sides resting buys in $3 clips on 5/15-min BTC/ETH, pair cost median 99.2c, stopped two weeks after the fee overhaul), gopfan2 +$1.66M (weather, still rising), @1kto1m +$49.6k since May 2026 (15-min BTC in-and-out, monthly profit now near zero). (3) Three academic/on-chain studies agree on the same lesson: profits go to resting limit orders placed early; takers lose; same-market arbitrage closes in about 3.6 s; the 5-minute BTC market is manipulated in the last 10 seconds. Everything else is Grade C or D: templated repos, Telegram funnels, 'proof on a call', and one seller whose own proof wallet lost about $22,600 in the first 13 days of October 2026. Content-farm warning: the dev.to 'lkto1m' series rides a real profitable wallet's name while linking four GitHub repos that are all deleted and quoting P&L ($292) that contradicts the wallet (+$49.6k); never run code from those links. GitHub topic/star ranking was not possible: api.github.com search is blocked in this session (repository-scoped only) and github.com HTML returns 403 to curl, so repo existence was checked with git ls-remote and metadata came from WebFetch where it rendered; stars quoted are from page reads. A different repo exposed what looked like a secret in its example files; it was not recorded. Applicability: global Polymarket is not open to US persons; Polymarket US launched sports-first and this sweep could not confirm it lists 5/15-minute crypto Up/Down, so every 'Polymarket US' entry above is conditional on the market type being listed there. For the owner's Kalshi 15-minute BTC desk the transferable, testable rules are: maker-only two-sided resting with pair cost under $1 and no selling (gabagool22 pattern; needs volume and near-zero fees), early-window maker entries with a T-90 s cutoff and a 72c floor (1kto1m posts), and the Telonex/Stanford findings that late-window takes near 50c are where retail loses. Owner's own labs already found taker rules lose 3-4c/contract on Kalshi, which matches all of the above. All 20 of this lane's clones were read as text only, nothing executed, and deleted; eight clones belonging to another lane were left in place. Pure Kalshi-only repos were skipped per instructions."
}


---
## result 1 

{
 "lane": "15-minute and 5-minute crypto up/down bots: Polymarket \"Bitcoin Up or Down\" 5m/15m (plus 4h), Kalshi KXBTC15M, Polymarket US \"BTC Up or Down: 15 min\"; tricks = Binance/Chainlink latency, end-of-window sniping, buying 95c+, cross-venue hedging, order-book imbalance, both-sides accumulation. Sweep run 2026-10-13 ~4:00-5:20 PM PT; on-chain pulls from Polymarket's public data API (data-api.polymarket.com) and Gamma API; 8 repos shallow-cloned, read as text, deleted.",
 "items": [
  {
   "name": "0x8dxd (the famous $313-to-$400k bot) - full on-chain audit of its last 5 months",
   "url": "https://polymarket.com/@0x8dxd (proxy wallet 0x63ce342161250d705dc0b16df89036c8e5f9ba9a); profile: +$2.05M all-time crypto P&L, $200M volume, 34,810 markets",
   "venue": "Polymarket global (5m and 15m BTC/ETH/SOL/XRP Up or Down)",
   "method": "Dec 2025-Jan 2026 (press era): bought the side that Binance/Coinbase spot had already decided while Polymarket still showed ~50/50 (latency arb), $4-5k clips, 6,300+ bets. Mar 24-Aug 25, 2026 (what the chain shows): switched to end-of-window 99c sniping on 5-minute BTC windows: buys 100-1,000 shares at $0.99-0.999 in the final 10-15 seconds and even 0-6 seconds AFTER the window end (trading stays open ~95 s past endDate), holds to redemption.",
   "evidence_grade": "A",
   "evidence": "Pulled 5,479 unique activity rows (API caps history at 5,000 rows, so Dec-Feb is not auditable here). Mar 2026: 911 buys, $14k, mid-prices (zero buys above 95c), 560 five-minute + 136 fifteen-minute windows. Apr-Jul 2026: essentially idle (28 buys). Aug 9-25, 2026 (all post-TWAP): 3,465 buys, $569,370 spent, 3,455 of them at >=95c, average fill 0.9914, 1,958 of 3,465 fills inside -30s..+15s of window end; 860 windows bought, 849 redeemed (98.7%), 11 lost, losses $4,205 (e.g. 1,000 sh Down @0.9896 on Aug 17 11:55PM ET window = -$990; 1,000 @0.8827 on Aug 12 = -$883). Net Aug 9-25 approx -$2,524 (redeem $566,689 + rebates $158 - buys $569,370). Daily P&L swung -$1,870 (Aug 10) to +$1,738 (Aug 11). Last activity 2026-08-25 00:45 UTC (Aug 24, 5:45 PM PT); 'past day P&L $0.00' on profile 2026-10-13.",
   "applicable_to_us": "arena only for the 5m version (Polymarket US has no 5m markets); the 99c-at-the-end idea maps to Polymarket US BTC 15m and Kalshi KXBTC15M but see still_works",
   "still_works": "No. The Jan 2026 latency arb was priced out by taker fees (Jan 5-7, 2026: 1.75c/share at 50c) plus the taker delay (500ms, then 250ms with order-locking Jun 5, 50ms Aug 17, 150ms Sep 4). The Aug 2026 99c-snipe variant lost money for this wallet after TWAP settlement (Aug 7/14) and it quit Aug 24-25 PT. A 99c strategy needs >99.1% win rate just to cover losses; it hit 98.7%.",
   "reusable": "The timing data (buys 0-15 s before AND up to 6 s after window end at 0.99) is a reusable fact: Polymarket keeps accepting orders ~95 s past endDate. The strategy itself is not reusable at the owner's size or venue."
  },
  {
   "name": "norm1e69 - both-sides taker accumulation bot on 5m/15m crypto (also sold as a product on polbots.com)",
   "url": "https://polymarket.com/@norm1e69 (proxy 0x41e2e1ccf1e4940029af02259a31c6b89b9fa354); listing: https://polbots.com/bots/btc-15-minute",
   "venue": "Polymarket global 5m (88%) and 15m (11%) BTC/ETH Up or Down",
   "method": "Buys BOTH Up and Down in nearly every window (64 of 66 windows in the sample), in 5-100 share clips, continuously through the window, leaning into whichever side just got cheaper after a spot move; one printed window: 93 fills, Up 855.6 sh @0.687 avg + Down 988.8 sh @0.298 avg = pair cost ~0.985 with a 133-share Down lean; another: Up 1,021 @0.334 + Down 1,025 @0.657 = 0.991. Holds to settlement (87 redeems, 2 sells in 1,500 rows). Pays taker fees and collects the daily Taker Rebate (program since May 28, 2026; 50% of fees back at the $10M/30-day weighted-volume 'Obsidian' tier; crypto weight 2.3x). Vendor's own claim: 'more than half of the net comes from fee rebates at a high volume tier'.",
   "evidence_grade": "A",
   "evidence": "Polymarket crypto leaderboard (data API, pulled 2026-10-13 5:10 PM PT): past 30 days +$190,292 on $17.8M volume (1.07% of volume); past 7 days +$42,129 on $5.35M. On-chain sample 2026-10-13 15:17 UTC to 2026-10-14 00:11 UTC: 1,412 trades ($16k notional in ~9 hours), 1,243 in 5m windows, 710 fills at 30-70c, only 29 at >=95c, zero fills in the last 30 s. TAKER_REBATE paid 2026-10-14 00:10 UTC: $1,740.85 for the day (no MAKER_REBATE row seen by 00:16 UTC; maker payouts land ~00:45 UTC so cannot rule out a small maker share).",
   "applicable_to_us": "arena only for 5m; the 15m version maps to Polymarket US BTC 15m / Kalshi KXBTC15M but the economics depend on the Polymarket global taker-rebate tier which neither venue offers",
   "still_works": "Yes, right now (Sept-Oct 2026, post-TWAP). Why: TWAP settlement removed last-second flips so pairs assembled below $1 are safer; the taker-rebate program (May 28, 2026) refunds up to 50% of the 1.75c/share fee at $10M+ monthly weighted volume. Fragile: needs ~$9M+ notional per 30 days to reach the 50% tier; at the owner's size the rebate is 0-8% and the 3.5c/pair fee eats the ~1-1.5c gross pair edge.",
   "reusable": "The rule (accumulate both sides when combined cost < ~0.99, lean to the side that just dumped, hold to settlement) is reusable as a paper experiment on Kalshi/Polymarket US 15m where there is no taker rebate; expect it to need maker fills instead."
  },
  {
   "name": "x-MoneyForWhiskas - 5m BTC both-sides taker bot (currently #4 crypto 30-day)",
   "url": "https://polymarket.com/@x-MoneyForWhiskas (proxy 0x3048d65321be3497164cdfc2996f94f98a2e7537)",
   "venue": "Polymarket global 5m BTC Up or Down only",
   "method": "Same family as norm1e69: 1,409 buys, all 5m BTC, 96 windows in 8 hours, both sides bought in 85 of 96; fills clustered 30-70c (976 of 1,409), only 1 fill >=95c, 11 fills in the last 30 s; printed window: Up 669.7 sh @0.481 + Down 649 sh @0.505 = pair ~0.986, matched 649; buys spread across the whole 5 minutes in 5-50 share clips; never sells, redeems at settlement.",
   "evidence_grade": "A",
   "evidence": "Leaderboard 2026-10-13: +$196,963 on $14.0M volume last 30 days (1.40%); +$55,344 on $3.6M last 7 days. TAKER_REBATE $2,971.52 paid 2026-10-14 00:10 UTC for one day (implies ~$6k/day of taker fees at the 50% tier, i.e. ~$340k/day notional).",
   "applicable_to_us": "arena only (5m markets are not on Polymarket US)",
   "still_works": "Yes as of Oct 13, 2026. Same dependency on the Obsidian taker-rebate tier and on thick 5m books.",
   "reusable": "Rule is reusable for study; the rebate economics are not at retail size."
  },
  {
   "name": "dangerously-skip-permissions - 5m BTC both-sides bot (owner's lab already tested a version)",
   "url": "https://polymarket.com/@dangerously-skip-permissions (proxy 0xc53375ff94e96100f2b30a4b5775db35218d69a9)",
   "venue": "Polymarket global 5m BTC Up or Down",
   "method": "1,470 buys in ~8 hours, 100% 5m BTC, 30 windows, both sides bought in all 30; fills 30-70c (1,005), 5-30c (279), 70-95c (186), none above 95c, none in the last 30 s. Heavy per-window size (~$475 per window in the sample). Taker (TAKER_REBATE $2,776.81 for Oct 13).",
   "evidence_grade": "A",
   "evidence": "Leaderboard 2026-10-13: +$145,365 on $8.35M last 30 days (1.74% of volume); +$42,697 on $2.3M last 7 days. Note: the owner's own task list records a 'Skip-permissions trigger on Kalshi' test that passed declared cells but showed no edge once timing was aligned to 1 s (PR #29).",
   "applicable_to_us": "arena only; the owner's Kalshi replication already failed at 1 s timing alignment",
   "still_works": "Yes on Polymarket global as of Oct 13, 2026; the owner's Kalshi copy did not, which points at speed/fees/rebates rather than the signal.",
   "reusable": "Only as a benchmark for what the owner already tested."
  },
  {
   "name": "Bonereaper - early both-sides ladder + 99c adds in the final minute (the wallet two open-source teams reverse-engineered)",
   "url": "https://polymarket.com/@bonereaper (proxy 0xeebde7a0e019a63e6b476eb425505b7b3e6eba30); analysis in OleksandrFIT/polymarket-market-maker docs (2026-05-28 bonereaper-tactic, 2026-06-11 competitor-edge-analysis)",
   "venue": "Polymarket global 5m (50%), daily/other Up-or-Down (35%), 15m (12%), 4h",
   "method": "OleksandrFIT's reconstruction on 16 shared windows (May 28, 2026): enters early (43-49% into the window) near fair value (~0.50-0.52 on the eventual winner, 0.39 on the loser), ladders resting bids across many price levels to catch the dumped side at extremes (example window: Up 1,475 @0.598 + Down 1,370 @0.210 = $0.808 pair), holds to resolution, also carries large naked directional legs. Oct 13, 2026 on-chain: still buys both sides (81 of 130 windows) but one printed 5m window shows Down ladder fills at 0.09-0.44 early, then 1,361 Up shares bought at exactly 0.99 between T-51 s and T-12 s (TWAP window already 1/6 to 4/5 known).",
   "evidence_grade": "A",
   "evidence": "Leaderboard 2026-10-13: +$67,671 on $7.93M last 30 days (0.85%). OleksandrFIT doc (May 28, 2026): +$138.83 on the same 16 windows where their bot lost -$247.51; '+$14,118/day overall, 45,189 trades'; July 2026 doc: '+$764k all-time, +$4.3k/day; ~2,500 maker fills/hr; median fill ~9 shares (~$4)'. Rebate row Oct 14 00:10 UTC: TAKER_REBATE $1,066.49 (its Sept-24 peer 0xb27b showed MAKER_REBATE $2,112 vs TAKER $309, so this family mixes maker ladders with taker adds).",
   "applicable_to_us": "arena only for 5m; the early-ladder idea maps to Kalshi KXBTC15M (no maker fee on that series as of 2026-10-07) and Polymarket US BTC 15m (makers are PAID 0.0125 x p(1-p))",
   "still_works": "Yes, but shrinking: $14k/day in May -> $4.3k/day in July -> ~$2.3k/day in Sept-Oct 2026. Survived fees (maker side pays none), the taker delay, and TWAP.",
   "reusable": "Yes: 'quote both sides early near fair, cap the price you will chase, never buy the favourite late at 0.6-0.9, let the dumped side fill cheap' is a concrete maker rule; OleksandrFIT measured that violating it (late favourite chasing) cost -$208 of a -$247 loss."
  },
  {
   "name": "0xb55fa129... - multi-horizon both-sides bot (15m-heavy)",
   "url": "https://polymarket.com/profile/0xb55fa1296e6ec55d0ce53d93b9237389f11764d4",
   "venue": "Polymarket global 15m (49%), daily Up-or-Down (26%), 5m (12%), 4h (12%)",
   "method": "1,422 buys in ~8 hours across 72 windows, both sides in 54; fills mostly 30-70c (710) and 5-30c (312); 1 fill in the last 30 s; no sells; TAKER_REBATE $2,812.85 for Oct 13.",
   "evidence_grade": "A",
   "evidence": "Leaderboard 2026-10-13: +$173,162 on $20.06M last 30 days (0.86%); +$35,037 on $3.3M last 7 days.",
   "applicable_to_us": "arena only; shows the same approach works on 15m windows, which exist on Polymarket US and Kalshi",
   "still_works": "Yes as of Oct 13, 2026 (same rebate dependency).",
   "reusable": "Evidence that 15m windows (not only 5m) support the both-sides approach."
  },
  {
   "name": "The retired 99c-sniper / latency cohort (BoneReader, k9Q2mX4L8A7ZP3R, 0x1979ae6b..., PurpleThunderBicycleMountain, 0x75973c66...)",
   "url": "https://polymarket.com/leaderboard/crypto/all/profit (profiles 0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9, 0xd0d6053c3c37e727402d84c14069780d360993aa, 0x1979ae6b7e6534de9c4539d0c205e582ca637c9d, 0x589222a5124a96765443b97a3498d89ffd824ad2, 0x75973c667cec880353450be3a6f17c5da67b4421)",
   "venue": "Polymarket global 5m/15m crypto",
   "method": "BoneReader: 42 of its last 44 fills at >=95c in 5m BTC windows (99c end sniping). 0x1979ae6b: 12 of last 19 at >=95c in 5m XRP/BTC. PurpleThunder: mid-price 15m SOL/BTC trades (latency style). 0x75973c66: mid-price 5m BNB/BTC, $272k in its last 47 trades.",
   "evidence_grade": "A",
   "evidence": "All-time crypto P&L (leaderboard 2026-10-13): BoneReader +$996,490, k9Q2mX4L8A7ZP3R +$1,393,321, 0x1979ae6b +$846,468, PurpleThunder +$813,545, 0x75973c66 +$917,312. Last on-chain trade: PurpleThunder 2026-01-21 (two weeks after taker fees), 0x1979ae6b 2026-03-01, BoneReader 2026-04-05, k9Q2mX4L8A7ZP3R 2026-04-06, 0x75973c66 2026-07-17. None appear in the Sept-Oct 2026 monthly or weekly top 25.",
   "applicable_to_us": "no",
   "still_works": "No. Five of the six biggest historical winners in this lane stopped between Jan 21 and Jul 17, 2026, i.e. after taker fees (Jan 5-7), after the 250ms taker delay + June 5 order locking, and before/at TWAP (Aug 7). The money moved to both-sides accumulation (above) and to daily/weekly strike markets.",
   "reusable": "No; useful only as the decay curve of this lane."
  },
  {
   "name": "Dai, Jia & Yu, 'Settlement Manipulation in Prediction Markets' (arXiv 2606.31675, June 30, 2026) - the study that killed snapshot settlement",
   "url": "https://arxiv.org/abs/2606.31675",
   "venue": "Polymarket global 5m BTC (and 15m for comparison), Binance spot",
   "method": "Not a method to copy (market manipulation): hold a Polymarket 5m position, then fire one-sided Binance spot orders in the final ~10 s to push the single Chainlink snapshot across the price-to-beat; price reverts ~a quarter (near-even cycles) within 10 s after settlement.",
   "evidence_grade": "B",
   "evidence": "Sample Jul 1, 2025-Apr 8, 2026; manipulation analysis Feb 12-Apr 8, 2026 (56 days, 16,073 cycles with on-chain trading). Top-decile 'push intensity' = 1,613 manipulated cycles. 821 wallets (1 in ~300 of 243,000 traders) earned $8.22M in pushed cycles (+$5,096 per cycle) and ~+$6 per cycle elsewhere; retail/other lost $7.61M and bore 70-93% of losses. Final-10 s Binance notional ~$1.7M in manipulated cycles vs ~$68k normal. A push flipped a 90-100c favourite 34.2% of the time vs 1.0% normally. 15-minute contracts: manipulation 'largely absent'. Not peer reviewed.",
   "applicable_to_us": "no (illegal/ToS-violating manipulation; also the snapshot is gone)",
   "still_works": "Dead: Polymarket moved to Chainlink 60-second TWAP for both the price-to-beat and settlement (5m used 30 s Aug 7-13, 60 s from Aug 14, 2026 00:00 UTC = Aug 13 5:00 PM PT; 15m/4h 60 s from Aug 7). Live market description now cites the btc-usd-twap-60s stream.",
   "reusable": "As a warning only: the 'buy 95c+ near certainty' trades of 2026 H1 were partly feeding on these flips (favourites at 90-100c lost 34% of pushed cycles)."
  },
  {
   "name": "Guangzhe Wang, 'Does a TWAP Deter Settlement Manipulation?' (SSRN 7445139, Sept 2026) - measured what TWAP removed",
   "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7445139 (summary with numbers: https://tradoxvps.com/polymarket-twap-settlement/)",
   "venue": "Polymarket global 5m BTC, Binance 1-second data",
   "method": "Measurement paper: share of each 5-minute window's Binance volume that trades in its final 10 seconds, before/during/after snapshot settlement.",
   "evidence_grade": "B",
   "evidence": "82,752 five-minute boundaries, July 2025 to early Sept 2026. Final-10 s share: 3.05% pre-launch, 5.68% under snapshot settlement, 3.02% under 60-s TWAP; near the strike 7.46% vs 4.14% away. Excess final-10 s volume ~ $24M/day under snapshot, gone after. Average traded volume per 5m BTC cycle fell from $91,600 to $54,100 (-40%). Cannot separate TWAP from the $1M August liquidity rewards paid the same month. Single author, not peer reviewed.",
   "applicable_to_us": "no (measurement)",
   "still_works": "Confirms end-of-window sniping/pushing footprint is back to pre-launch level since mid-Aug 2026.",
   "reusable": "Yes as a calibration fact: post-TWAP 5m markets carry ~40% less volume, so both-sides accumulation has thinner books than the H1 2026 numbers suggest."
  },
  {
   "name": "gregyoung14/openmarket (arXiv 2607.26245) - synchronized Polymarket-Binance dataset and a null latency-forecast result",
   "url": "https://github.com/gregyoung14/openmarket ; dataset https://huggingface.co/datasets/gregyoung14/openmarket-btc-polymarket",
   "venue": "Polymarket global 15m BTC Up or Down + Binance BTC/USDT",
   "method": "Rust collector pairing Polymarket order-book events with Binance trades at ms resolution; walk-forward logistic model with 43 microstructure features vs the naive Polymarket mid.",
   "evidence_grade": "B",
   "evidence": "727,098,247 deduplicated rows, 202 snapshots, 2,936,031 explicit lead-lag pairs, 54 Polymarket days between 2026-02-12 and 2026-05-15. Polymarket trails Binance by a median 16 ms on source clocks (5th/95th -186/+316 ms); quotes respond to large Binance moves after a median 347 ms (collector clock). Out of sample over 559 walk-forward windows: model Brier 0.165 / ECE 0.026 vs naive 0.163 / 0.014 (model loses); simulated trading -0.116 payoff units per attempted trade after fees/slippage.",
   "applicable_to_us": "arena only for the data (global Polymarket); the 347 ms response-lag number is the best public measure of the latency window and applies to any venue a bot races",
   "still_works": "Shows the pure latency edge was already mostly gone Feb-May 2026 (pre-TWAP): a 16 ms lead and ~350 ms quote response is below the 150-250 ms taker delay plus fees.",
   "reusable": "Yes: free tick-level 15m dataset for backtesting any 15m rule; collector code is MIT/Apache."
  },
  {
   "name": "EVERYTHINGAICO/polymarket-btc-edge - pre-registered, Bonferroni-corrected null results on 15m BTC (options flow, momentum, order-book imbalance, market making)",
   "url": "https://github.com/EVERYTHINGAICO/polymarket-btc-edge",
   "venue": "Polymarket global 15m BTC Up or Down (Deribit options, Binance spot, Polymarket books)",
   "method": "11 hypotheses with frozen pre-registration, 70/30 temporal hold-out. Tested: Deribit net-buying-pressure 'D' as direction signal; BTC spot momentum (1-30 min lookbacks); order-book imbalance taker entries (644 rules); M1 maker spread-capture (spread >= 0.10, book >= 1000, >= 300 s to close, 30 s horizon); S1 Up+Down < $1 taker arb.",
   "evidence_grade": "B",
   "evidence": "9,225 windows Dec 2025-Apr 2026 backfill + live May-Jun 2026 (n=587-649). D signal: 51% live, 47.96% backfill, 46.12% hold-out. Momentum: the published '54.2%' was lookahead bias (retracted 2026-06-02); clean 49.26% hold-out; a variant with 56.55% accuracy netted only +$0.009/bet because Polymarket reprices momentum within 60 s (contract 6c dearer). Order-book imbalance: best of 644 rules +1.7c proxy EV, CI crosses 0, Bonferroni p=1.0. M1 maker spread capture: train +1.22c/decision (p<0.0001, 420 markets) but hold-out +0.78c, 95% CI -0.70c..+2.17c, p=0.141 -> 'no edge confirmed' (fills/queue/fees not modelled). S1 Up+Down<1: executable only 7 times in 100 markets, 1-2% gross, dead at a 2% fee. Buying the favourite: EV -3.2%; fading extremes with the real ask: -6.0%.",
   "applicable_to_us": "Kalshi KXBTC15M and Polymarket US BTC 15m (same market shape; redo with their books)",
   "still_works": "Order-book imbalance and spot momentum as taker signals: no (market prices them in <60 s). Maker spread capture in wide-spread moments: unproven but the only hypothesis that was positive in both train and hold-out.",
   "reusable": "Yes: the protocol (pre-register, Bonferroni, sealed hold-out, market_id as the statistical unit) and the M1 rule are directly portable to the owner's Kalshi recorder data."
  },
  {
   "name": "OlegonZo/polymarket-btc-bot - 15m momentum shadow bot with a documented negative result",
   "url": "https://github.com/OlegonZo/polymarket-btc-bot",
   "venue": "Polymarket global 15m BTC Up or Down",
   "method": "Buy Up when Chainlink/Binance impulse + acceleration + volume spike + order-book guards say P(Up) > market price; shadow-logged instead of traded.",
   "evidence_grade": "B",
   "evidence": "POSTMORTEM 2026-06-25: 1,485 resolved shadow rows across 181 markets; win rate 69.43% vs average entry price 70.38% -> -0.95c per share (-0.00956 avg virtual P&L, -14.20 total); market-clustered mean -0.038 per market; 4 simulated exits avg -0.053. Resolver bug found and fixed before the verdict; 0 stars; 'CLOSED AS NEGATIVE EDGE'.",
   "applicable_to_us": "Kalshi / Polymarket US 15m as a template for how to kill a rule honestly",
   "still_works": "Momentum-entry at the ask on 15m: no, the hit rate is real (69%) but priced in (70c).",
   "reusable": "The shadow-logger/resolver/analyzer pattern and the 'winrate minus entry price' breakeven framing."
  },
  {
   "name": "OleksandrFIT/polymarket-market-maker - maker-both bot on 5m with pre-registered live go/no-go and a real-money post-mortem",
   "url": "https://github.com/OleksandrFIT/polymarket-market-maker",
   "venue": "Polymarket global 5m/15m BTC and ETH",
   "method": "Quote both sides anchored to Binance/Chainlink spot with inventory skew; 'chop gate' stands down in trending windows ('maker edge inverts' in trends); near-end completion or sell-loser; pre-registered metric effective_pair_cost <= 0.96 = GO, > 0.995 = NO-GO on n >= 80 chop windows.",
   "evidence_grade": "B",
   "evidence": "Paper phase-13 (May 28, 2026): -$247.51 on 16 markets in 27 min, 31% win; -$208 of it from fills after 66% of the window and -$162 from buying the favourite above 0.60. Production-faithful sim pair cost by regime: chop 0.915, reversal 0.920, trend 0.936 (looser sim's 0.89 was an artifact). Live run #1, 2026-07-16 (21:20-21:40 UTC = 2:20-2:40 PM PT): 4 windows, 45 pairs merged, spent $57.23, rebate $0.68, equity 52.87 -> 42.99 (-$9.88); sell-loser order rejected 26 of 29 times ('invalid maker amount' at $0.01-0.09 prices) so losing legs rode to zero; verdict 'INSUFFICIENT n, live LOCKED OFF'. README claims best week ~+$150 on ~$100 bankroll (unverified). 336 commits, 0 stars.",
   "applicable_to_us": "Polymarket US BTC 15m (makers paid 0.0125 x p(1-p)) and Kalshi KXBTC15M (no maker fee) - arena first",
   "still_works": "Unproven; the pair-cost math (0.915-0.936 in sim vs 0.99 live pairs observed) shows the edge is 1-8c per pair and dies if one leg rides naked.",
   "reusable": "Yes: regime gate, pre-registered live stop, and the failure list (sell at sub-10c prices gets rejected; order-vanished != filled) are directly reusable."
  },
  {
   "name": "albatrossbird/housedge - Kalshi KXBTC15M vs Polymarket US BTC-15m recorder, same-claim proof, and 'best of both' backtest",
   "url": "https://github.com/albatrossbird/housedge (PRs #174, #187; lib/paperM15.js rules; CLAUDE.md measurements)",
   "venue": "Kalshi KXBTC15M and Polymarket US 'BTC Up or Down: 15 min'",
   "method": "Rules: fav-15-60s = buy the favourite with 15-60 s to close at 0.75-0.97 and spread <= 0.03; fav-15-45s = 15-45 s at 0.80-0.97; fav-60-120s = 0.65-0.95; dog-60-120s = underdog 0.05-0.35. 'Best of both' decides on Kalshi's book and buys each contract on whichever venue is cheaper all-in (never a .us book over 2 s old). Venue facts measured 2026-09-28: both settle on CF Benchmarks BRTI 60-second simple average (press says Chainlink; rules and data say BRTI), identical price-to-beat and settlement to the cent on all 24 windows checked; Kalshi taker fee 0.07 x p(1-p) rounded up per order, no maker fee on KXBTC15M (fee type 'quadratic' as of 2026-10-07); Polymarket US taker 0.0695 x p(1-p) half-even, makers PAID 0.0125 x p(1-p); .us public /book is Cloudflare-cached 30 s (live data needs the key-gated socket); .us skips some windows (e.g. 2026-10-01 10:00-11:45 UTC none listed). KXBTC15M book changes 151+ times/s, touch moved 59 times in 30 s (2026-09-26).",
   "evidence_grade": "B",
   "evidence": "PR #187 (merged ~Oct 2026), last 7 days of real recordings: fav-15-60s, 107 decisions: best-of-both +5.0c/contract, Kalshi alone +2.3c, Polymarket US alone +1.2c; .us was cheaper at 66 of 107 decisions. fav-15-45s: +4.4c / +3.4c / +1.6c. Resting (maker) orders on .us did WORSE than taking even with the rebate: filled resting orders won 74-90%, unfilled would-have-won 100% (adverse selection). All figures are upper bounds (both legs fill at once, no 50-250 ms delay; delay test deferred to PR #188). Earlier audit of a vendor's 'late favourite' rule (93% win claim): Coinbase agrees with BRTI direction 97.6% overall but only 64% inside 0.5 bp, 89% inside 1 bp (614 markets, 2026-09-11) - exactly where a late favourite trade lives. 0 stars, private-style research repo, active daily.",
   "applicable_to_us": "Kalshi + Polymarket US directly (this is the owner's exact venue pair)",
   "still_works": "Open question with the best data in the lane: +2.3c to +5.0c per contract over 7 days is before order delay and on ~100 decisions; the same 'late favourite' idea failed the owner's own Kalshi tests (-3.3c to -4.1c/contract). The cross-venue price difference (66/107 cheaper on .us) is the new, testable piece.",
   "reusable": "Yes: slug formula for .us 15m markets (cpc-btc-updown-15m-YYYY-MM-DD-HHMMz), fee formulas for both venues, the BRTI 60-s settlement proof, and the delay-table method."
  },
  {
   "name": "doge-8/btc5m-web - open strategy framework with three end-game 5m rules and a 24-day backtest claim",
   "url": "https://github.com/doge-8/btc5m-web (strategies/d1.ts, p1.ts, p2.ts)",
   "venue": "Polymarket global 5m/15m BTC/ETH/SOL Up or Down",
   "method": "d1 'Tail-Scalp': in the last 30 s, buy Up if Binance-vs-open diff > +$40 and Up probability < 80% (mirror for Down), stop if diff crosses 0, hold to settlement. p2 'End-Game Crossing': 90-30 s left, diff crosses +/-$25, entry side priced < 65%, historical fair-probability minus current >= 10 points, stop at diff -5. Uses four sockets (Polymarket book, Chainlink, fills, Binance) with Binance as the leading signal and Chainlink as the settlement quote; built-in 1-s backtest recorder and multi-core parameter sweep.",
   "evidence_grade": "C",
   "evidence": "Code comment on d1: 'Backtest 24 days: ~7 trades/day / 86% win rate / $0.70 per trade (passed all 5 validations)' - no data or report published; README: strategies 'cannot guarantee profits'. 21 stars, 18 forks, MIT, one squashed commit, 2026.",
   "applicable_to_us": "arena only (5m); the p2 'market has not caught up to the diff' rule is portable to Kalshi/Polymarket US 15m as a hypothesis",
   "still_works": "Unknown post-TWAP; 'diff' must be redefined as distance of the running 60-s average from the price-to-beat, not spot minus open.",
   "reusable": "Yes: cleanest open plugin framework for 5m/15m rules with a recorder; rules are small TS files."
  },
  {
   "name": "NotACheeto/BTC15ARB - fail-closed Polymarket US x Kalshi 15m arbitrage bot",
   "url": "https://github.com/NotACheeto/BTC15ARB",
   "venue": "Polymarket US BTC 15m + Kalshi KXBTC15M",
   "method": "Discover pairs from .us /v1/search and Kalshi series KXBTC15M; refuse unless asset=BTC, start/end match to the second, 900 s duration, both settle on BRTI 60-s, strikes match within tolerance, $1 payout; buy YES on one venue and NO on the other with concurrent IOC orders when $1 - (ask_yes + ask_no) - Kalshi fee (parabolic, rounded up) - .us fee (0.0695) - slippage - latency haircut - unwind reserve >= MIN_NET_EDGE; if one leg fills, cancel/hedge the other with orphan loss capped at $0.02.",
   "evidence_grade": "D",
   "evidence": "No P&L, fill rates, or backtest; README cites a ~20 microsecond decision hot path and 23 tests; 2 commits, 0 stars. Its BRTI-equivalence claim is independently confirmed by housedge's 24/24-window check.",
   "applicable_to_us": "Kalshi + Polymarket US directly",
   "still_works": "Unknown; housedge's data says paired taker fees are ~3.5c per pair near 50c and the two touches sit within 1c of each other nearly always, so pure riskless arb is rare; the value is in 'buy where cheaper' routing, not two-leg arb.",
   "reusable": "The equivalence checklist and fee-aware edge formula."
  },
  {
   "name": "casatrickdev/polymarket-trading-bot + dev.to 'last 60 seconds' write-up",
   "url": "https://github.com/casatrickdev/polymarket-trading-bot ; https://dev.to/casatrick/i-built-a-polymarket-trading-bot-that-tries-to-capture-the-last-60-seconds-of-market-inefficiency-4ki9",
   "venue": "Polymarket global 15m BTC/ETH (and 5m)",
   "method": "Enter in the final ~60 s on the side already priced 85-95% (author: best trades were 85-95c, not 98-99c); example entry 41 s before resolution at 85.5c; DipArb variant: after a sharp move, leg into the dumped side then hedge the other; base size 2% of capital, fee/gas-aware minimum net profit.",
   "evidence_grade": "C",
   "evidence": "Self-reported: 22 settled trades, 22 wins, +$37.84, '+3.8%' account growth, yet also lists -$13.5 of losses (internally inconsistent); no dates, no wallet. Repo: 1 star, 48 commits, v3.2 'September 2026', JSONL order-book replay harness with no published output.",
   "applicable_to_us": "Kalshi / Polymarket US 15m as a hypothesis (it is the owner's 'near-certain grind' lab4 idea)",
   "still_works": "Doubtful: the owner's lab4 and Kalshi H-F tests found -3.3c to -4.1c per contract for late favourites; housedge's upper-bound numbers are the only positive reading and are pre-delay.",
   "reusable": "Not beyond the idea."
  },
  {
   "name": "direkturcrypto/polymarket-terminal - 'Maker Rebate MM' (both-side maker bids capped at 0.98, merge via CTF)",
   "url": "https://github.com/direkturcrypto/polymarket-terminal",
   "venue": "Polymarket global 15m BTC/ETH/SOL/XRP",
   "method": "Post maker BUY limits on Up and Down simultaneously with combined price <= 0.98 (e.g. 5 shares each, $4.90 for a guaranteed $5.00 if both fill); when both fill, merge Up+Down back to USDC on the CTF contract; re-enter after 30 s; no repricing; cancel everything 60 s before close; skip when either side > 0.70; collects the maker rebate (20% of the market's taker fees shared by fee-equivalent).",
   "evidence_grade": "D",
   "evidence": "286 stars, 154 forks, MIT, 72 commits; no P&L or backtest. housedge's .us test found resting orders lose to adverse selection (filled 74-90% win vs 100% for unfilled); EVERYTHINGAICO found Up+Down < $1 displayed only 7 times in 100 markets.",
   "applicable_to_us": "Polymarket US BTC 15m (makers paid 0.0125 x p(1-p)) and Kalshi (no maker fee) - arena first",
   "still_works": "The mechanic (merge to USDC, 60-s cancel) is sound post-TWAP; the edge (both maker bids filled below $1) is thin and adverse-selected.",
   "reusable": "Yes as code for maker two-sided quoting with merge."
  },
  {
   "name": "0xb27bc932... - 'momentum take' competitor decoded by OleksandrFIT (85% matched pairs, ~$0.94 pair cost, 97% completion)",
   "url": "https://polymarket.com/profile/0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82 ; decode in OleksandrFIT docs/superpowers/plans/2026-07-08-momentum-take.md",
   "venue": "Polymarket global 5m (72%), 15m (24%), 4h",
   "method": "Taker-chase the moving side, buy the cheap fading side, merge pairs below a floor, keep only a small capped directional residual; trades at the extremes where the fee curve is ~0; ~85% of shares end up paired.",
   "evidence_grade": "A for the wallet, C for the decode",
   "evidence": "On-chain sample (535 trades on 2026-09-24): both sides in 18 of 23 windows, 28 of 535 fills in the last 30 s, rebates that day MAKER $2,112 + TAKER $309 (so mostly maker). Not in the Sept-Oct top-25 monthly/weekly crypto leaderboards; last activity on this proxy 2026-09-24 (may have rotated wallets).",
   "applicable_to_us": "arena only",
   "still_works": "Was active through TWAP (Aug-Sept 2026) as a maker; status after Sept 24 unknown.",
   "reusable": "The 'merge floor + capped residual' structure."
  },
  {
   "name": "thesoulcrancerdev/poly-trading-strategies - 'TWAP-aware EndCycle Sniper' (code for sale) with UI-snapshot results",
   "url": "https://github.com/thesoulcrancerdev/poly-trading-strategies ; https://dev.to/soulcrancerdev/how-to-build-a-polymarket-trading-bot-50ms-delay-edition-20o4",
   "venue": "Polymarket global 5m/15m BTC and ETH",
   "method": "Near expiry, identify the dominating side, compare that side's running time-weighted price with the live quote and time left, buy in clips while the average entry still sits inside the gap to $1, hold to redemption; momentum-spike variant accumulates the dislocated side. dev.to piece: 'be a maker, not a taker', fetch feeRateBps per token, post the likely winner at 90-95c around T-10 s.",
   "evidence_grade": "C",
   "evidence": "Account panel screenshot: $7,444.99 profit on 503 predictions, 93.0% win (491/37), realized +$9.44k, unrealized -$2.57k, max drawdown -$425, fees -$617.23, taker rebates +$22.05, maker rebates $0 (so it was a taker); README itself says figures are 'UI snapshots, not a verified track record'. 103 stars, 102 forks, no code, strategies offered for sale.",
   "applicable_to_us": "Kalshi / Polymarket US 15m as the same 'late favourite' hypothesis",
   "still_works": "Claimed to be designed for TWAP; unverified. 0x8dxd's audited August attempt at the same idea netted -$2.5k on $569k.",
   "reusable": "No code."
  },
  {
   "name": "AllAboutAI-YT/polymarket_bot_beginner - measured mechanics of the 5m market (spec document)",
   "url": "https://github.com/AllAboutAI-YT/polymarket_bot_beginner/blob/main/research/btc_5min_market_spec.md",
   "venue": "Polymarket global 5m BTC",
   "method": "Not a strategy; a measurement sheet: slug btc-updown-5m-<unix start>, ~288 markets pre-listed 24 h ahead; Gamma 'closed' flag and 0/1 prices lag endDate by 60-120 s; trading continued ~95 s past endDate; loser-side bids empty at T-33 s; one resolved market: 3,176 trades (3,116 inside the window, 623/min, falling to 198 in the last minute), median trade 8 shares, 2,774 buys vs 402 sells, 941 wallets, ~$2k notional per 5m market vs $23.7M/24h series volume.",
   "evidence_grade": "D (no trading results); the measurements are first-hand",
   "evidence": "Spec dated May 2026 (sample market 2026-05-11/12); fee object crypto_fees_v2 rate 0.07 exponent 1 takerOnly rebateRate 0.2 (matches the live object pulled 2026-10-13: tick 0.001, min order 5, rewardsMinSize 50, rewardsMaxSpread 4.5c).",
   "applicable_to_us": "arena only",
   "still_works": "n/a",
   "reusable": "Yes: the lag numbers (60-120 s to close flag; orders accepted ~95 s past end) and the live fee object."
  },
  {
   "name": "JREREEE/btc-5m-market-trading-bot - TypeScript maker-both with 15-s resting bids",
   "url": "https://github.com/JREREEE/btc-5m-market-trading-bot",
   "venue": "Polymarket global 5m BTC",
   "method": "Each tick post good-til-date buy orders on Up and Down below the ask (life ~15 s), target projected pair cost <= 0.98-0.99, cancel on adverse BTC move, rare taker cross to hedge if inventory stays one-sided, 'repair mode' only accepts fills that improve pair cost, stop quoting 10-60 s before close.",
   "evidence_grade": "D",
   "evidence": "4 stars, 61 commits; only a hypothetical example ($0.47 + $0.50 bids on 10 shares = $0.30 gross); README: paper fill rates are 'an optimistic ceiling'.",
   "applicable_to_us": "arena only; same shape as the Polymarket US maker idea",
   "still_works": "Unknown.",
   "reusable": "Code skeleton only."
  },
  {
   "name": "Jonmaa/btc-polymarket-bot (Jeremy Whittaker's Up+Down < $1 rule)",
   "url": "https://github.com/Jonmaa/btc-polymarket-bot ; https://jeremywhittaker.com/index.php/2024/09/24/arbitrage-in-polymarket-com/",
   "venue": "Polymarket global 15m BTC",
   "method": "Buy equal Up and Down whenever the two asks sum below $1 (WebSocket book), hold to settlement for the guaranteed $1.",
   "evidence_grade": "D",
   "evidence": "No results; Whittaker's own 2024 post says Polymarket liquidity 'isn't significant enough for me to pursue this further'. EVERYTHINGAICO measured the condition as executable 7 times in 100 markets with 1-2% gross, zero net at a 2% fee; at 50/50 the two taker fees are ~3.5c per pair.",
   "applicable_to_us": "Kalshi / Polymarket US 15m (same idea works only with maker fills)",
   "still_works": "No as a taker; marginal as a maker.",
   "reusable": "No."
  },
  {
   "name": "Benj4minCup Substack 'Ultimate Guide' (S1-S4 rules) + repo",
   "url": "https://benjamincup.substack.com/p/the-ultimate-guide-to-building-a ; https://github.com/Benj4minCup/Polymarket-Trading-Bot-python",
   "venue": "Polymarket global 5m BTC",
   "method": "S1 last-second momentum snipe (Up < 0.48 with spot momentum, 80/20 hedge, +2-4% / -1.5%); S2 order-book skew; S3 spot reversion (>0.3% rebound in 30 s while Up ~45%); S4 'oracle lead' (CEX/Chainlink delta > 0.2% while Polymarket lags, 70/30 hedge).",
   "evidence_grade": "D",
   "evidence": "No P&L, dates, wallet, or backtest; pseudocode sleeps 180 s between exit checks; targets a '65%+ win rate'; empty demo section; Telegram sales contact.",
   "applicable_to_us": "arena only",
   "still_works": "S1/S4 rely on the pre-fee, pre-delay latency window that OpenMarket measured at ~347 ms response and that 0x8dxd abandoned.",
   "reusable": "No."
  },
  {
   "name": "gist Archetapp 'Polymarket BTC 5-Minute Up/Down Trading Bot' (T-10 s composite, FOK)",
   "url": "https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69",
   "venue": "Polymarket global 5m BTC",
   "method": "From T-10 s, poll every 2 s a 7-indicator score (window delta from open dominant; 1-min momentum, acceleration, EMA 9/21, RSI 14, volume surge, tick trend); fire on confidence or a 1.5 score jump; hard deadline T-5 s; FOK market buy, fallback GTC at $0.95; 'safe' mode bets 25% of bankroll.",
   "evidence_grade": "D",
   "evidence": "Created 2026-02-13 (the day after 5m markets launched); no results; author notes four straight losses in safe mode cost ~68% of bankroll; commenter's 'is it profitable?' unanswered.",
   "applicable_to_us": "arena only",
   "still_works": "Spot-minus-open 'window delta' is the wrong target since Aug 7/14, 2026 (TWAP at both ends).",
   "reusable": "No."
  },
  {
   "name": "DeadKennedyx gist 'polymarket-edge-hunter' (full-set edge scanner + 70/30 straddle skew)",
   "url": "https://gist.github.com/DeadKennedyx/311a19166471a1b0c6e4f1e1ae5fb73c",
   "venue": "Polymarket global (15m BTC straddle module)",
   "method": "Rust daemon on the CLOB socket flags long full-set edge (ask_yes + ask_no < 1 by >= 0.2%) and short full-set edge (bids > 1); legs must be within 500 ms, lag <= 1.5 s; for 15m BTC suggests 70% on the cheaper leg / 30% other, copying a wallet that tilted to momentum.",
   "evidence_grade": "D",
   "evidence": "Log lines only (+0.0020, +0.0045 edges); straddle section titled 'still in alpha, AKA not working'; last active 2026-05-19.",
   "applicable_to_us": "arena only",
   "still_works": "The scanner finds 0.2-0.45% edges that fees (1.75c/share at 50c) erase for takers.",
   "reusable": "No."
  },
  {
   "name": "brandononchain/kalshibot - Kalshi KXBTC15M bot using Polymarket mid as a cross-venue signal (GBM + Kelly)",
   "url": "https://github.com/brandononchain/kalshibot",
   "venue": "Kalshi KXBTC15M (Polymarket Gamma/CLOB polled every 4 s as a price reference only)",
   "method": "DIR: P(Up)=Phi(move/(sigma*sqrt(T))) from Binance bookTicker vs Kalshi ask, trade if edge > 8%, only in the first 10 min and > 30 s to settle. POLY: Polymarket mid vs Kalshi ask, trade if edge > 5%. DUAL: buy YES+NO if combined ask < 0.98 (disabled: legs not atomic). Quarter-Kelly, $25 cap, fee-adjusted at 0.07.",
   "evidence_grade": "D",
   "evidence": "29 stars, 13 forks, 45 commits; README: synthetic backtest 'is not an event replay', 'profitability has not been validated'. The owner's Lab 5 (fair value from spot + volatility) already found NO EDGE on 36 cells.",
   "applicable_to_us": "Kalshi (already covered by the owner's labs); the Polymarket-mid-as-signal idea is testable against Polymarket US 15m books",
   "still_works": "Unknown; housedge found the two venues' touches within 1c nearly always, so a 5% cross-venue edge is rare.",
   "reusable": "No."
  },
  {
   "name": "Uruguabot + Poly Sniper (vendor bots that published or self-reported records)",
   "url": "https://polbots.com/bots/btc-15-minute (Uruguabot fills repo linked from its listing; Poly Sniper $29-259/mo)",
   "venue": "Polymarket global 5m/15m BTC/ETH",
   "method": "Uruguabot: 5m BTC/ETH momentum entries, dry-run default. Poly Sniper: compiled snipers for 15m BTC/ETH/SOL/XRP.",
   "evidence_grade": "C (Uruguabot leans B-minus because losses are published)",
   "evidence": "Uruguabot: two live generations lost about $270 total (execution problems, ghost-fill bug); default config +7.3% on 25 trades at a 40% win rate; a 1,934-window study found its automated signals coin-flip vs a human's 59%; logs omit market IDs so not on-chain verifiable. Poly Sniper self-report: 138 days, 3,455 closed trades, 54.6% win, +$3,501 on $2,000.",
   "applicable_to_us": "no (vendor, global Polymarket)",
   "still_works": "Uruguabot is the honest datapoint: signal bots on 5m were coin-flips in 2026.",
   "reusable": "No."
  },
  {
   "name": "Dexter's Lab / Paone X threads on 0x8dxd (the viral source of the 'latency arb' story)",
   "url": "https://x.com/DextersSolab/status/2008285935650181231 ; https://x.com/paonx_eth/status/2007958494679359852",
   "venue": "Polymarket global 15m",
   "method": "Dexter: bot watches Binance/Coinbase, buys when direction is confirmed but Polymarket still prices the old state. Paone (same wallet, same week): 'balanced straddles on 95% of markets, buys Up + Down with roughly equal sizing, one expensive leg and one cheap leg, ~$3,000 per market, does not predict direction'.",
   "evidence_grade": "C",
   "evidence": "Screenshots of the profile page (Jan 2026: $313 start, ~$414k-$515k one-month profit, 98-99% win, 6,615-7,300 bets). Press (Finbold Jan 6 and Jan 9, 2026; CoinDesk; Finance Magnates Jan 7) repeats the same screenshots. The two analysts describe different mechanics for the same wallet; my on-chain pull (Mar-Aug) shows a 99c end-sniper, so the Jan mechanics remain unverified.",
   "applicable_to_us": "no",
   "still_works": "No (see 0x8dxd item).",
   "reusable": "No."
  },
  {
   "name": "Polymarket rule timeline that decides which tricks live (official changelog + live market objects)",
   "url": "https://docs.polymarket.com/changelog/predictions ; https://docs.polymarket.com/trading/taker-rebates ; https://docs.polymarket.com/programs/maker-rebates ; live object via https://gamma-api.polymarket.com/markets?slug=btc-updown-5m-<unix>",
   "venue": "Polymarket global (crypto Up or Down)",
   "method": "Reference item.",
   "evidence_grade": "A (primary documents and live API)",
   "evidence": "Jan 5, 2026: taker fees on 15m crypto (peak 1.56% at 50c), maker rebates funded by them. Feb 12, 2026: 5m crypto markets launch with fees. Feb 18: 500 ms taker delay removed (per dev.to; not in changelog). Mar 6: fees on all crypto horizons; Mar 30: Fee V2. May 28: Taker Rebate Program (tiers by 30-day weighted volume = size x (1-price) x 2.3 for crypto: 3% at $2k, 8% at $20k, 18% at $200k, 32% at $1M, 44% at $4M, 50% at $10M+; paid daily 00:00 UTC). Jun 5: taker orders locked during the 250 ms delay (no cancel). Aug 7 00:00 UTC (Aug 6, 5:00 PM PT): Chainlink TWAP for price-to-beat AND settlement (5m 30 s; 15m/4h 60 s); Aug 14: 5m to 60 s. Aug 17 11:00 UTC (4:00 AM PT): taker delay 250 -> 50 ms. Sep 4 14:00 UTC (7:00 AM PT): 50 -> 150 ms. Live 5m and 15m objects 2026-10-13: feeSchedule {rate 0.07, exponent 1, takerOnly, rebateRate 0.2} => taker fee = shares x 0.07 x p(1-p) = 1.75c/share at 50c, 0.63c at 10/90, 0.07c at 99c; maker fee 0; tick 0.001; min order 5; resolution text cites btc-usd-twap-60s stream. Sep 22, 2026 12:00 PM ET: Polymarket US lists BTC 15m (BTC only).",
   "applicable_to_us": "Polymarket US inherits the TWAP/BRTI-style settlement but NOT the global fee/rebate programs (its fees: taker 0.0695 x p(1-p), makers paid 0.0125 x p(1-p))",
   "still_works": "Latency arb at 50c: killed by fee + delay (Jan-Sep 2026). Last-second snapshot sniping/pushing: killed Aug 7-14, 2026. Buying 95c+: fee is ~0.07c so fees did not kill it, TWAP + competition did (0x8dxd 98.7% win rate lost money). Both-sides accumulation: alive, subsidised by the taker-rebate tiers.",
   "reusable": "Yes: read fees from the market's feeSchedule and the delay from the changelog; never hard-code."
  }
 ],
 "notes": "What the chain says, in plain words (all pulls 2026-10-13 between 4:00 and 5:20 PM PT, Polymarket public data API; no credentials were seen, used or recorded; the eight clones were read as text only and deleted). 1) The famous wallets of this lane are gone. 0x8dxd (the $313-to-$400k bot) ran a 99c end-of-window sniper on 5-minute BTC in August 2026, won 849 of 860 windows and still netted about -$2,500 on $569k because 11 losses at 88-99c cost $4,205; it stopped Aug 24 (PT). The other five biggest all-time crypto winners that traded 5m/15m windows stopped between Jan 21 and Jul 17, 2026. 2) Who makes money now (30 days to Oct 13): a cluster of bots that buy BOTH Up and Down in almost every 5m/15m window at mid prices in 5-100 share clips, lean toward the side that just dumped, hold to settlement, and collect Polymarket's Taker Rebate (50% of fees back above $10M monthly weighted volume): norm1e69 +$190k on $17.8M, x-MoneyForWhiskas +$197k on $14.0M, 0xb55fa... +$173k on $20.1M, dangerously-skip-permissions +$145k on $8.3M, GoodFallen +$89k on $5.0M, Bonereaper +$68k on $7.9M. They net 0.85-1.74% of volume; their daily TAKER_REBATE rows are $1,000-$3,000 each. Bigger monthly winners (0x06dc... +$287k, Tokor +$244k, getbipped) trade daily/weekly strike markets, not this lane. 3) What changed and what it killed: taker fees (Jan 5-7, 2026; live object today = shares x 0.07 x p(1-p), 1.75c/share at 50c, ~0 at 99c) killed 50c latency arb; the taker delay (500 -> 250 -> 50 -> 150 ms, Sep 4) and the Jun 5 order lock killed cancel-gaming; Chainlink 60-s TWAP at both ends (Aug 7/14, 2026) killed last-second snapshot sniping and the Binance push manipulation documented by Dai/Jia/Yu (821 wallets, $8.2M, Feb 12-Apr 8, 2026) and measured by Wang (final-10 s volume share 5.68% -> 3.02%; 5m volume per cycle -40%). Both-sides accumulation survived because makers pay nothing, takers get up to half their fees back, and TWAP made sub-$1 pairs safer. 4) Open-source research is almost all honest nulls: OpenMarket (727M rows, 16 ms source lead, 347 ms quote response, model loses to the naive mid), EVERYTHINGAICO (options flow 48%, momentum 49-53% after fixing lookahead, order-book imbalance 0 of 644 rules, maker spread-capture +1.2c train / +0.8c hold-out not significant), OlegonZo (69.4% hits vs 70.4% price = -0.95c/share), OleksandrFIT (live -$9.88 in 4 windows; sell-loser orders rejected 26 of 29 times). 5) Most applicable to the owner: albatrossbird/housedge, which proved Kalshi KXBTC15M and Polymarket US BTC-15m are the SAME contract (BRTI 60-second average, identical price-to-beat and settlement on 24/24 windows checked 2026-09-28) and measured a 'best of both venues' late-favourite rule at +5.0c/contract vs +2.3c Kalshi-only over 7 days and 107 decisions, before order delay (upper bound); it also found resting orders on Polymarket US lose to adverse selection even with the 0.0125 x p(1-p) maker rebate. Fees there: Kalshi 0.07 x p(1-p) rounded up per order, no maker fee on KXBTC15M (fee type quadratic as of Oct 7); Polymarket US taker 0.0695 x p(1-p), makers paid. 6) Practical read for a real-money bot: (a) do not build latency or 99c end-snipers; (b) the only live winners need $9M+/month of volume for the rebate tier that Polymarket US and Kalshi do not offer, so copy the rule into the arena only; (c) the one new testable lead is cross-venue routing (Polymarket US was the cheaper venue on 66 of 107 late-favourite decisions) which the owner can test with the existing Kalshi recorder plus a .us socket feed, adding the 150-250 ms delay before believing any number; (d) manipulation (Binance pushes) is off the table legally and is dead mechanically. Data limits: the data API caps history at 5,000 rows per wallet, so 0x8dxd's Dec-Feb period could not be audited; leaderboard P&L is Polymarket's own on-chain computation; wallet classifications are from ~9 hours of fills each (1,000-1,500 rows) on Oct 13, 2026. learningworship/polymarket-latency-bot could not be cloned (repo gone or private). Kalshi-only repos were left to the other sweep except where they carried Polymarket data."
}


---
## result 2 

{
 "lane": "Academic and quant write-ups with documented prediction-market profits, 2023-2026: arbitrage (sum-to-one, negative risk, cross-venue), favorite-longshot bias, late-window/near-certain pricing, market-maker and maker-vs-taker PnL, liquidity-rewards economics, crypto-settled binary microstructure",
 "items": [
  {
   "name": "Saguillo, Ghafouri, Kiffer, Suarez-Tangil - Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets (AFT 2025, peer-reviewed; arXiv 2508.03474)",
   "url": "https://arxiv.org/abs/2508.03474",
   "venue": "Polymarket (global, on-chain Polygon order book)",
   "method": "Three rules, all held to resolution: (1) inside one market, when YES ask + NO ask < $1 buy both (or when the bids sum > $1, mint a YES/NO pair for $1 and sell both); (2) inside a multi-outcome NegRisk event, when all YES asks sum < $1 buy every YES, or when all NO asks sum < (n-1) buy every NO; (3) across two logically dependent markets (e.g. 'Trump wins' vs 'Republican wins'), buy the cheaper implied side when the pair is mispriced. Opportunities are grouped per user in a 950-block (about 1 hour) window; profit = minimum tokens held across legs minus cost.",
   "evidence_grade": "A for the phenomenon (realized profits read from the public chain, peer-reviewed); it is other people's money, not a backtest you can repeat",
   "evidence": "Markets resolving 2024-04-01 to 2025-04-01: 8,659 single markets + 1,578 NegRisk events (17,218 conditions). 7,051 conditions had at least one in-market opportunity (all were 'buy both below $1'); 662 of 1,578 NegRisk events had one. Realized profit about $39.6M: $5.9M buying single markets below $1, $4.7M selling above $1, $17.3M NO-baskets and $11.1M YES-baskets inside NegRisk events; cross-market election pairs only about $95k over 5 pairs. Top wallet 0xd218e474776403a3301422... made $2,009,631.76 over 4,049 transactions; top 10 wallets about $8.2M (21% of total); authors call them 'bot-like'. Fees were zero on Polymarket then. Caveat: the headline total assumes a $1-per-trade epsilon the paper does not fully reconcile with Table 1.",
   "applicable_to_us": "Polymarket (global) for the on-chain mechanics; the same 'do the legs sum to $1' check can be run on Kalshi and Polymarket US, but each taker leg now costs 0.07xPx(1-P) (1.76c at 50c on Kalshi, 1.74c on Polymarket US), which is bigger than typical gaps",
   "still_works": "Mostly decayed. Polymarket added taker fees on crypto (early 2026) and on all markets (2026-03-30); the follow-up paper by Gebele et al. shows per-opportunity NegRisk profit fell from about $1.00 (mid-2024) to about $0.08 (early 2026) and median executable life is 16 s; 'ghost fill' attacks (item below) now target arb bots.",
   "reusable": "As a scanner idea yes; as income for a small retail bot no (pennies per share, sub-second races, non-atomic legs)."
  },
  {
   "name": "Gebele, Mutzel, Matthes (TU Munich) - Executable Arbitrage and Market Efficiency in Prediction Markets (arXiv 2608.00666, Aug 2026)",
   "url": "https://arxiv.org/abs/2608.00666",
   "venue": "Polymarket (global) NegRisk multi-outcome markets",
   "method": "Converter-enabled negative-risk arbitrage: buy NO on every outcome of a multi-outcome event when the basket is cheap, then within about 5 Polygon blocks (10 s) call the NegRisk Adapter to convert the NO basket into $1 of collateral plus free YES tokens; also plain settlement baskets (buy all YES or all NO within 10 minutes, hold to resolution). Mispricing concentrates on the unsupported YES side.",
   "evidence_grade": "A (realized on-chain profits of identified actors) for the measurement; B for anything forward-looking",
   "evidence": "Actor-level CLOB data: 32,702 events, 259M trades through 2025-12-31; order-book sample 2026-04-14 to 2026-05-19. Realized about 1.118M USDC: 1.086M (97%) via the converter, 32,283 USDC from settlement baskets (28,644 USDC over 5,923 CLOB baskets = about $4.84 each; 3,639 USDC over 67 FPMM baskets). Weekly median converter profit per conversion: about $1.00 through Jul 2024, about $0.20 late 2024-2025, about $0.08 early 2026. Median executable episode 16.15 s (253 YES-side episodes). Top 10 addresses about 75% of converter profit; one actor about 76% of settlement-basket profit. Gas is relayed (zero to user); taker execution assumed.",
   "applicable_to_us": "Polymarket global only (the adapter is an on-chain contract); not Kalshi; Polymarket US does not expose it",
   "still_works": "Alive but almost fully competed: 8c per opportunity and falling; fees since 2026-03-30 widen the no-arb band further.",
   "reusable": "Technically yes (public contracts), economically only for the fastest bot."
  },
  {
   "name": "Gebele & Matthes - Semantic Non-Fungibility and Violations of the Law of One Price in Prediction Markets (arXiv 2601.01706, Jan 2026)",
   "url": "https://arxiv.org/abs/2601.01706",
   "venue": "Ten venues incl. Kalshi, Polymarket, PredictIt, Futuur, Limitless, Myriad, Seer; cross-venue",
   "method": "Cross-venue law-of-one-price: find the same or a logically nested event on two venues and buy YES where it is cheap plus NO where the other venue prices YES higher, so YES_A + NO_B < $1 after fees; hold to settlement. 2024 presidential case: Polymarket's contract was a strict superset of Kalshi's, so YES on Polymarket + NO on Kalshi spanned every outcome.",
   "evidence_grade": "B (execution-adjusted historical books, persistence filters of 30 min to 1 h; not realized trades)",
   "evidence": "102,275 events 2018 to Aug 2025; about 6% cross-listed (about 10% of event-days). Among the top 1,000 relations by volume, prices typically sit 2-4% from execution-adjusted parity and the gaps persist for at least an hour. Election case: execution-adjusted spread averaged about $0.03 and reached $0.07 for sustained intervals before the election-night call; annualized return 'single digits to several hundred percent' depending on whether capital is freed on election night (Nov 5-6, 2024) or at inauguration (Jan 20, 2025). Both venues charged zero fee on that market; Polymarket tick $0.001, Kalshi $0.01.",
   "applicable_to_us": "Kalshi + Polymarket US, both held by the same owner; the risk is resolution wording differing between venues and capital locked on two venues",
   "still_works": "Partly. The cause is structural (US KYC vs offshore, different resolution sources, lock-up), so gaps recur on big political/sports events. But two taker legs now cost about 3.5c at 50c combined (Kalshi 1.76c + Polymarket US 1.74c), which is bigger than the 3c average gap; you need maker fills or gaps above 4-5c, and weeks of lock-up.",
   "reusable": "Yes: a Kalshi vs Polymarket US scanner for identical-rule markets, maker-only, sized for weeks of lock-up."
  },
  {
   "name": "Cheng, Yang, Zou - Arbitrage Analysis in Polymarket NBA Markets (arXiv 2605.00864, Apr 2026)",
   "url": "https://arxiv.org/abs/2605.00864",
   "venue": "Polymarket (global) in-game NBA moneyline/spread/total",
   "method": "(1) Single market: when ask_A + ask_B < $1 buy both; when bid_A + bid_B > $1 mint and sell both. (2) Combinatorial: across moneyline, spread and total on the same game, buy the set whose combined cost is below the guaranteed payout (the theoretical 'middle').",
   "evidence_grade": "B (75M order-book snapshots; fees not modeled)",
   "evidence": "173 games, 3,042 markets, >75M snapshots. Only 7 executable single-market episodes, median life 3.6 s. 290 combinatorial episodes, concentrated in the final minutes of play, median return 101 bps; 76.9% of them capped at an average executable size of 14.8 shares; the 'middle' jackpot was never realized. Warns that summing both directions double-counts.",
   "applicable_to_us": "Kalshi and Polymarket US both list NBA markets, but the owner's rule 2026-10-10a bans real money on sports",
   "still_works": "Marginal: 1% on $15 of size is cents, and sports taker fees (Polymarket 0.05xPx(1-P), Kalshi 0.07xPx(1-P)) exceed 101 bps near 50c.",
   "reusable": "Not worth building."
  },
  {
   "name": "Burgi, Deng, Whelan (UCD) - Makers and Takers: The Economics of the Kalshi Prediction Market (UCD WP2025/19, Jan 2026; also CEPR VoxEU column)",
   "url": "https://www.karlwhelan.com/Papers/Kalshi.pdf",
   "venue": "Kalshi (all categories, 2021 to Apr 2025)",
   "method": "Favorite-longshot rules: never buy contracts under 10c (they lose more than 60% of stake); buy favorites above 70c, and do it as a maker (resting limit order) rather than a taker. Makers who bought contracts priced 50c and up earned +2.6%.",
   "evidence_grade": "B (realized returns on every traded contract with exchange-flagged maker/taker side; not an out-of-sample trading test)",
   "evidence": "46,282 contracts from 12,403 events open at least 24 h, 2021 to April 2025; 313,972 YES/NO prices (close plus 24-h steps up to 10 days out). Average pre-fee return on a Kalshi contract -20%; contracts at 10c or less lose over 60%; above 70c small but statistically significant positive post-fee returns; a 95c contract winning 98% of the time returns +3.1% pre-fee. Makers averaged -9.64% vs takers -31.46% (F-test rejects equality at very high significance). Taker fee $0.07xPx(1-P) per contract, rounded up per order, equals 1.77% of stake at 50c for 100 contracts; makers paid no fee until after April 2025. Bias is 'diminishing over time'.",
   "applicable_to_us": "Kalshi yes (directly); Polymarket US shows the same shape in politics and crypto per Cardozo et al.",
   "still_works": "Likely alive but thin: Kalshi now charges makers up to a 0.0175 rate on some markets; the +2.6% is per held contract before capital lock-up; at 95-97c the gross edge is 3-5c and the taker fee is 0.21-0.34c (about 7% of the gross), so the fee is not the problem, adverse selection and lock-up are.",
   "reusable": "Yes. This is the owner's lab4 'near-certain grind' and maker-only question with real numbers: maker-only, favorites at 70c+, never sub-10c. The owner's own 15-min BTC takes losing 3.3-4.1c/contract match the taker -31% finding."
  },
  {
   "name": "Cardozo & Rivero-Wildemauwe - The Favorite-Longshot Bias in Prediction Markets: Evidence from Polymarket (arXiv 2609.12878, Sep 2026)",
   "url": "https://arxiv.org/abs/2609.12878",
   "venue": "Polymarket (global), all categories",
   "method": "Buy favorites priced 90c and up; never buy longshots under 10c. Works in Crypto and Politics; does not work in Sports.",
   "evidence_grade": "B (588M trades, every resolved market; returns before fees and before liquidity rewards)",
   "evidence": "Trades 2022-11-11 to 2026-03-29, 588M trades by 2.48M wallets, 591,187 resolved child markets. Dollar-weighted: purchases under 10c lose 19.3c per $1; purchases at 90c+ earn +0.83c per $1. By category (equal-weight / pooled): Crypto longshots -14.84% / -12.63%, favorites +0.64% / +0.54%; Politics longshots -16.34% / -46.15%, favorites +1.04% / +1.42%; Sports longshots +2.43% / +18.11%, favorites -0.23% / +0.14%. Grouping by parent event flips longshots to +4.09%. Losses peak around 20-25c, gains near 60c. Top-decile past longshot buyers do no better; top-decile favorite buyers earn less.",
   "applicable_to_us": "Polymarket US and Kalshi, crypto and politics; the owner's BTC 15-min is 'crypto': favorites earn only +0.5 to +0.6c per $1 pre-fee",
   "still_works": "Longshot avoidance is free and permanent. The favorite side (+0.83c per $1) is roughly equal to the Polymarket US taker fee at 90c (0.63c), so only maker fills keep anything.",
   "reusable": "Yes, as filters: no buys under 10c; prefer 90c+ as a maker in crypto/politics; do not expect it in sports."
  },
  {
   "name": "Gebele & Matthes - When Certainty Is Not Worth It: Capital Lock-Up and Settlement Discounting in Prediction Markets (arXiv 2605.31431, May 2026)",
   "url": "https://arxiv.org/abs/2605.31431",
   "venue": "Polymarket (global); Kalshi used as a comparison",
   "method": "Near-certain contracts (95c+) trade below $1 mostly because money is locked until settlement. Buying them and holding earns an 'annualized settlement wedge' (ASW), i.e. a yield on locked capital, not a forecasting edge. Rule: price the hold by annualizing (1/price - 1) over the expected lock-up and compare to a risk-free rate.",
   "evidence_grade": "B (62,291 CLOB markets through 2025-12-31; 36,349 near-certain markets, 1.18M market-days; fees not in the main results)",
   "evidence": "Mean ASW 3.06% (minimum frontier), 4.36% (0.1-percentile), 6.89% (0.5-percentile) per year; curve falls sharply at short maturities, flat by about 20 days, hump at 230-260 days. Adjusting for the discount removes 47.8% to 87.6% of the near-certainty horizon gradient (residual slope p=0.53 on the conservative frontier; 56-93% on held-out events). Example: NO on 'Will Jesus Christ return in 2025?' sat near 96c for months: $1,000 earns about $41.67 (4.2%) after about a year of lock-up, about 5% annualized. A 1% fee illustration lowers the yield most at short maturities.",
   "applicable_to_us": "Both venues (Kalshi near-certain contracts settle fast after the event, so per-year rate is what matters; Polymarket US similar)",
   "still_works": "It is not mispricing, it is a 3-7%/yr yield on locked money with tail risk (resolution disputes; the Economics Letters paper below finds 3.4-12.4% of disputed Polymarket markets overturned).",
   "reusable": "Yes, but benchmark the owner's near-certain grind against about 4-5%/yr; anything above that is either luck or unpriced resolution risk."
  },
  {
   "name": "Dubach - The Anatomy of a Decentralized Prediction Market: Microstructure Evidence from the Polymarket Order Book (arXiv 2604.24366, Apr/May 2026) with follow-up Measuring Trade Direction in a Prediction Market (arXiv 2610.06412, Oct 2026)",
   "url": "https://arxiv.org/abs/2604.24366",
   "venue": "Polymarket (global) order book, 385,198 markets",
   "method": "Market-maker economics, not a strategy: spreads are about 400 bps (4c) in 40-60c markets and 1,300-1,818 bps for sub-10c longshots; crypto books are mostly one tick; makers are many (median about 32 effective makers per market, HHI 0.031), so the maker spread is competed. Trade direction must come from on-chain OrderFilled events, not the public feed.",
   "evidence_grade": "D for profits (no PnL reported); B for microstructure facts",
   "evidence": "Feed 2026-02-21 16:00 UTC to 2026-04-15 08:00 UTC (52 days), 30.3 billion events; on-chain 2026-02-28 to 2026-03-27, 255M fills; 600-market stratified panel. Crypto (348 markets) median effective half-spread -0.039 pp (negative because feed-inferred direction is wrong about 41% of the time; Kyle lambda flips sign on 60%/43% of markets). Longshot bin 0-10c median quoted spread 1,818 bps. Maker HHI median 0.031, p90 0.119 (about 8 effective makers), max 0.40. Self-counterparty wash share median 0.97%, p99 10.6%, max 22.2%. Depth is near-uniform across top 10 levels (L1 median 13.6%). Follow-up (12 days Apr-Aug 2026, 24.5M print-settlement pairs): Lee-Ready overstates effective spread by +0.43c/share vs settlement truth.",
   "applicable_to_us": "Polymarket US runs a similar CLOB; Kalshi publishes maker/taker flags so the direction problem is smaller there",
   "still_works": "n/a (measurement). Tells you the only wide spreads are on longshots, which lose, and that 15-min crypto books are one tick, so a maker's gross edge there is about 1c minus adverse selection.",
   "reusable": "As methodology (use on-chain fills for trade direction; realized-spread decomposition) for the owner's maker-vs-taker study."
  },
  {
   "name": "OpenMarket: A Synchronized Polymarket-Binance Dataset for High-Frequency Prediction-Market Research (arXiv 2607.26245, Jul 2026)",
   "url": "https://arxiv.org/abs/2607.26245",
   "venue": "Polymarket (global) BTC 15-minute Up/Down vs Binance BTC spot",
   "method": "Tests the 'latency' idea directly: measure how long Polymarket 15-min quotes lag Binance spot and simulate trading the lag. Finding: no tradeable edge.",
   "evidence_grade": "B (null result with public data and code)",
   "evidence": "2026-02-12 to 2026-05-15 (54 Polymarket days, 57 Binance days); 2,936,031 matched event pairs; median Polymarket-minus-Binance lag 16 ms (5th-95th percentile -186 to +316 ms, with about +/-99 ms clock ambiguity). After Binance moves of 5 bps or more, Polymarket's first one-tick best-bid change comes a median 347 ms later. Spread is one tick (1c) 91.9% of the time, two ticks 6.0%. Simulated positive-EV trading with 1% fee and 0.5% slippage nets -0.116 payoff units per attempted trade; out of sample the multivariate model slightly underperforms the Polymarket mid. Authors: 'We do not claim trading profitability.'",
   "applicable_to_us": "Directly: Kalshi KXBTC15M and Polymarket US 15-min BTC (launched on the US app 2026-09-22, Chainlink BTC/USD settlement)",
   "still_works": "The 300 ms lag is real but sub-second; after a taker fee of about 1.74c at 50c it is not tradeable by a retail bot. Blog claims of 30-90 s lags are not supported by this measurement.",
   "reusable": "The dataset and method yes; the latency strategy no. Supports the owner's own H-F 'no edge' result."
  },
  {
   "name": "Dai, Jia, Yu - Settlement Manipulation in Prediction Markets (arXiv 2606.31675, Jun 2026)",
   "url": "https://arxiv.org/abs/2606.31675",
   "venue": "Polymarket (global) 5-minute, 15-minute and 4-hour Bitcoin up/down",
   "method": "Not a strategy to copy: manipulators push Binance spot in the final 10 seconds of 5-minute cycles so the Chainlink settlement price flips. Defensive rule for us: never carry a near-50/50 short-cycle position into the last seconds, and prefer 15-minute (or longer) horizons and venues that settle on a time-averaged index.",
   "evidence_grade": "A (on-chain fills plus Binance order flow; realized $8.2M by identified wallets)",
   "evidence": "5-min contract launched 2026-02-12 (15-min 2025-10-09, 4-h 2025-10-15). Final-10-s Binance order flow about 50% above pre-launch; in near-even cycles (about 6% of cycles) the spike is 3.9x; price reverts about a quarter within 10 s. About 1,600 cycles in the top decile of pushes; in near-even cycles a push against the favored side flipped the winner 65% vs 41% baseline; in 90-100%-priced cycles a push reversed the outcome 34% vs 1%. 821 wallets (1 in 300 of about 243,000 traders) took $8.2M in pushed cycles and broke even elsewhere; 93% of losses fell on retail. Binance is about 2.5 bps from the oracle and matches its side 85% of the time. 15-minute contracts: manipulation 'largely absent'.",
   "applicable_to_us": "Polymarket US (15-min BTC only; no 5-min) and Kalshi (15-min shortest, settles on a 60-second average of the CF Benchmarks index), i.e. the owner's venues are the safer design",
   "still_works": "Risk is live on global 5-min markets; structurally weaker on the owner's 15-min venues.",
   "reusable": "As a risk rule only."
  },
  {
   "name": "Angelini & De Angelis - When Do Markets Fully Process Public Information? Evidence from Real-Time Prediction Markets (arXiv 2606.07811, Jun 2026)",
   "url": "https://arxiv.org/abs/2606.07811",
   "venue": "Kalshi in-game NBA winner contracts",
   "method": "Underreaction: when a scoring event moves a benchmark win probability by X points, Kalshi's mid moves only 0.64X at once and drifts the rest over 5-15 minutes. Rule tested: buy YES after a positive gap, sell after a negative gap, hold 5 minutes.",
   "evidence_grade": "B (null after spreads; fees not modeled)",
   "evidence": "2025-04-15 to 2026-05-25; 1,438 games, 2,876 contracts, 409,512 contract-minutes. Pass-through 0.638; a 10-point updating gap predicts about 2.0c of drift at 5 min and 2.4c at 15 min (4.6-4.8c net of later benchmark moves). Underreaction largest for salient events in illiquid moments and in clutch time (pass-through 0.509). Trading rule: midpoint returns +0.39% to +0.87%, but buying at the ask and selling at the bid is negative in every version (-1.20% all observations; -0.36% high-quality quotes with gap >= 200 bp). Kalshi's taker fee would add about 1.76c each way at 50c.",
   "applicable_to_us": "Kalshi yes, Polymarket US has NBA too; owner currently bans real money on sports",
   "still_works": "The mid-price edge is real but a one-tick spread plus 3.5c round-trip fee is bigger than the 2c drift; only a maker posting inside the spread right after the event could capture it.",
   "reusable": "Idea only; the BTC analog (Kalshi lagging spot) is a 0.3 s effect, not minutes."
  },
  {
   "name": "Akey, Gregoire, Harvie, Martineau - Who Wins and Who Loses in Prediction Markets? Evidence from Polymarket (SSRN 6443103; CEPR DP21615; June 21, 2026 version)",
   "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6443103",
   "venue": "Polymarket (global), full on-chain ledger (public dataset: huggingface.co/datasets/vgregoire/polymarket-users)",
   "method": "Be the maker. The strongest predictor of being profitable is the share of your volume done with resting limit orders; losers take liquidity with market orders.",
   "evidence_grade": "A (complete on-chain settlement data, academic, replicable dataset)",
   "evidence": "$67B of volume from launch to about March 2026. Top 0.1% of profitable users capture 51.2% of all gains, top 1% capture 76.5%; about 69% of users end at a loss; median user -$2, mean $0. One standard deviation more maker share = +9.0 percentage points higher chance of positive PnL (largest effect found); top 0.1% earners do 47.3% of volume as makers vs 17.1% for the bottom 95%. Month-to-month persistence is modest and concentrated in limit-order users. Insider trading unlikely to explain the biggest winners. Fee markets excluded; notes Polymarket introduced fees on all markets 2026-03-30.",
   "applicable_to_us": "Both venues",
   "still_works": "Structural: takers pay spread plus fee. Post-March-2026 fees plus maker rebates make the maker side relatively better. Consistent with the owner's own finding that model takes lost 3.3-4.1c per contract.",
   "reusable": "Yes, as a design rule for every desk: maker-only, track maker share as a KPI."
  },
  {
   "name": "Gomez-Cram, Guo, Jensen, Kung - Prediction Market Accuracy: Crowd Wisdom or Informed Minority? (SSRN 6617059, Apr 2026)",
   "url": "https://ssrn.com/abstract=6617059",
   "venue": "Polymarket (global) 2023-2025",
   "method": "A statistically skilled minority (about 3% of accounts, identified by PnL far outside coin-flip simulations) earns the profits by doing three things: trade fast on public news when it arrives; remove law-of-one-price violations (YES+NO not summing to $1, related markets out of line); buy underpriced favorites and sell overpriced longshots.",
   "evidence_grade": "B (on-chain, academic; skill test and persistence; group-level profits mostly via press coverage)",
   "evidence": "Per press coverage of the paper: 2023-2025, about $13.76B volume, 1.72M accounts, 98,906 events; fewer than 3.5% of accounts take over 30% of total profits and drive most price discovery; skill persists year to year; the other 97% fund them. SSRN blog confirms the 3% figure and the three behaviors.",
   "applicable_to_us": "Both venues",
   "still_works": "All three are permanent profit sources but competed; the longshot/favorite fade is the only one a small account can do without speed.",
   "reusable": "Yes as a playbook; the news-speed leg needs infrastructure the owner does not have."
  },
  {
   "name": "Mitts & Ofir (Columbia Law) - From Iran to Taylor Swift: Informed Trading in Prediction Markets (SSRN 7259741 / 6426778, Mar-Aug 2026)",
   "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7259741",
   "venue": "Polymarket and Kalshi",
   "method": "Not reusable: wallets flagged for large, early, one-directional, concentrated bets before news events won about 70% of the time. The only legal derivative, copy-trading flagged wallets, lags the move.",
   "evidence_grade": "A (on-chain realized profits; academic screen)",
   "evidence": "Over 210,000 suspicious wallet-market pairs, Feb 2024 to Feb 2026; flagged traders profitable on 69.9-70% of resolved trades and held the winning token in 75%; about $143M realized profit, about $119M above what execution prices implied. Case studies: Feb 2026 US-Israeli strike on Iran; pre-announcement bets on Taylor Swift's engagement. CFTC won a default judgment against a Polymarket insider in April 2026.",
   "applicable_to_us": "No (insider information; illegal on Kalshi, prosecuted)",
   "still_works": "The pattern persists, which is why the CFTC and both venues are adding surveillance.",
   "reusable": "No."
  },
  {
   "name": "Ng, Peng, Tao, Zhou - Price Discovery and Trading in Modern Prediction Markets (SSRN 5331995, rev. Apr 2026)",
   "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5331995",
   "venue": "Polymarket, Kalshi, PredictIt, Robinhood",
   "method": "Follow the leading venue: Polymarket led Kalshi in the 2024 election; on 2023-2026 matched markets Kalshi leads in sports and whenever it has higher relative volume and large-trade activity, Polymarket leads in politics and entertainment. Net order imbalance from large trades predicts subsequent returns. Cross-venue arbitrage when YES_A + NO_B < 1 minus costs.",
   "evidence_grade": "C-to-B (SSRN page blocked; abstract and Quantpedia summary only; no return figures visible)",
   "evidence": "2024 election window Oct 23 to Nov 5, 2024: persistent cross-platform spreads and arbitrage profit shown in Figure 2; authors say costs 'significantly reduce' profits. Later revision: matched Polymarket/Kalshi markets 2023-2026, bidirectional leadership as above.",
   "applicable_to_us": "Kalshi + Polymarket US",
   "still_works": "Partly; for 15-min BTC a 2026-08-21 public snapshot showed Kalshi carrying about 12x Polymarket's touch depth with near-identical prices, so expect Kalshi to lead there.",
   "reusable": "As a signal: large-trade order imbalance on the leading venue; needs the full paper for magnitudes."
  },
  {
   "name": "Krause (Marquette) - Calibration and Forecast Accuracy of Macroeconomic Prediction Markets: Evidence from Kalshi, 2025-2026 (SSRN 7117919) and Information Efficiency Across Macroeconomic Prediction Markets (SSRN 7119120), Jul 2026",
   "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7117919",
   "venue": "Kalshi macro markets (Fed funds, CPI, unemployment, GDP, etc.)",
   "method": "Sell or avoid macro longshots priced under $0.30 (overpriced by about 7 points), especially unemployment-rate markets; do not bother in Fed-funds markets, which are almost perfectly calibrated.",
   "evidence_grade": "B (calibration study on settled contracts; fees not modeled; no trading backtest)",
   "evidence": "594 markets across 9 series, 2025-2026: Brier 0.0987 (60.5% better than random); Fed funds Brier 0.0001-0.0029, unemployment 0.1302; longshots under $0.30 bias -0.0721 (p<0.001); 1-hour horizon Brier 0.0812, 30-day 0.1587. Companion: 2,668 settled contracts Jul 2021 to Jun 2026. Unemployment paper: bias -0.077 across 287 contracts 2021 to Mar 2026. CPI paper: no classic bias once zero-price contracts are included; 1-28c contracts slightly overpriced otherwise.",
   "applicable_to_us": "Kalshi yes; Polymarket US lists some economics markets",
   "still_works": "Probably alive (few participants, thin books). Posting NO at 70c+ as a maker against a 7-point mispricing leaves about 5c per contract after a 1.5c fee, but volume is small.",
   "reusable": "Yes, small size, maker-only, unemployment and CPI buckets."
  },
  {
   "name": "Le - Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics in Prediction Markets (arXiv 2602.19520, Feb/Aug 2026)",
   "url": "https://arxiv.org/abs/2602.19520",
   "venue": "Kalshi and Polymarket",
   "method": "Political markets are underconfident (prices compress toward 50%): buy political favorites, sell political longshots; on Kalshi, large political trades compress prices further, so fade big political orders.",
   "evidence_grade": "B (353M trades, 429k binary contracts; no fees, no trading rule)",
   "evidence": "Persistent underconfidence in politics on Kalshi, replicated on Polymarket; large Kalshi political trades associated with a calibration-slope gap of about one half (survives clustered bootstraps; not robust on Polymarket). Descriptive decomposition explains 87.3% in-sample and 71.5% out-of-sample variance of cell-level slopes; about half of raw slope variation is estimation noise.",
   "applicable_to_us": "Both venues",
   "still_works": "Consistent with +1.0 to +1.4% pre-fee politics-favorite returns in Cardozo et al. and +2.6% maker returns in Whelan; slow capital, lock-up until the event.",
   "reusable": "Yes, as a category filter."
  },
  {
   "name": "Portnaya - Do Prediction Markets Match Option Prices? Bitcoin Threshold Evidence from Binance and Polymarket (arXiv 2606.19517, Jun 2026)",
   "url": "https://arxiv.org/abs/2606.19517",
   "venue": "Polymarket BTC threshold markets ('BTC above $X on date') vs Binance and Deribit options",
   "method": "Compute the option-implied probability of BTC finishing above the strike from a matched call (Black-Scholes implied-vol inversion); sell Polymarket YES when it sits above that value (average 5.6-6.3 points too high), delta-hedge with options or perps, unwind as the gap mean-reverts (half-life about 4 hours).",
   "evidence_grade": "B (hourly data, HAC and block-bootstrap inference; delta-hedged proxy 'profitable after conservative transaction costs' with marginal statistical precision)",
   "evidence": "September 2023 BTC contract, 214 hourly observations: Polymarket YES 5.6 pp above Binance-implied risk-neutral value (t=6.46, p<1e-9); pooled three BTC markets (287 obs) 6.3 pp; Deribit benchmark 11 pp; wedge largest at low implied probability and long maturity; AR(1) half-life about four hours. Ethereum evidence mixed.",
   "applicable_to_us": "Kalshi lists daily/weekly BTC price-range and 'touch' markets; Polymarket US crypto listing beyond 15-min BTC is unverified",
   "still_works": "The hedged version needs an options venue; the unhedged version is just the crypto longshot fade (Cardozo: sub-10c crypto purchases lose 12.6-14.8%).",
   "reusable": "Partially (unhedged longshot fade on Kalshi BTC strike ladders)."
  },
  {
   "name": "Fabi, Marfe, Ruffo, Schonleber - Are Decentralized Prediction Markets Efficient? Evidence from Bitcoin Options (Financial Cryptography 2026 DeFi workshop talk)",
   "url": "https://fc26.ifca.ai/defi/papers/market-efficiency-prediction-markets.pdf",
   "venue": "Polymarket BTC bets (Above, Range, Reach, Dip) vs Deribit option-implied distributions",
   "method": "Path-dependent bets ('will BTC reach/dip to $X') are the most mispriced; low-probability tail events are persistently overpriced; mispricing is largest at contract inception, near expiry, on weekends and after macro shocks. Rule: sell tail YES on Reach/Dip markets at those times.",
   "evidence_grade": "C (3-page talk abstract; 255 bets Mar 2024 to May 2025; no returns reported yet)",
   "evidence": "Sample 255 bets, March 2024 to May 2025. Simple Above/Range bets align with option-implied probabilities; Reach/Dip show 'significant deviations'; tail events 'persistently overpriced'. Full paper promised as 'upcoming'.",
   "applicable_to_us": "Kalshi has BTC 'touch' markets (per arXiv 2609.14267); Polymarket US unverified",
   "still_works": "Plausibly alive (same crypto longshot pattern as Cardozo); a 10c longshot costs 0.63c in taker fee against multi-point overpricing.",
   "reusable": "Yes as a filter; wait for the full paper for sizes."
  },
  {
   "name": "Deleep, Lee, Bai, Suresh, Dhawan (UC Berkeley) - How Wise is the Crowd? Bias and Edge in Prediction Markets (SSRN 6322678, Feb/Mar 2026)",
   "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6322678",
   "venue": "Polymarket and Kalshi (tick data, wallet histories, comments)",
   "method": "Caution paper: once contract lifecycle timing is controlled, the classic favorite-longshot bias 'largely disappears'; what remains in 'mention' markets is a YES bias (traders overpay for the affirmative), so sell YES there; whales on average bleed expected value to small-order traders (fade large ideological orders); loud commenters have no edge.",
   "evidence_grade": "C (working paper; sample sizes and robustness not visible)",
   "evidence": "Abstract-level only: multivariate framework separating market-wide bias from trader edge; 'Yes bias' in mention markets; whales systematically lose EV to small traders; no statistically significant edge from commentary. Numbers not available in public summaries.",
   "applicable_to_us": "Both (Kalshi runs many mention markets)",
   "still_works": "Unknown.",
   "reusable": "Yes as a test design (control for time-to-resolution before trusting any FLB result) and a YES-bias filter."
  },
  {
   "name": "Shen, Jin, Wu, Wang, Chen - The Ghosts of Polymarket: When Off-Chain Matches Meet On-Chain Reverts (arXiv 2606.16852, Jun 2026)",
   "url": "https://arxiv.org/abs/2606.16852",
   "venue": "Polymarket (global) CTF Exchange",
   "method": "Not a strategy: attackers get an order matched off-chain, then make the on-chain settlement fail (nonce bump, balance drain, allowance revoke, proxy trap; 35 variants) so counterparties, including arbitrage bots, are left with one leg filled. Also used to game liquidity rewards.",
   "evidence_grade": "A (on-chain; attacker profit measured)",
   "evidence": "1,952,440 reverted match transactions analyzed; 980,133 fills selectively reverted; over 24.3% of fills reverted at peak hours; at least $1.49M attacker profit; $1.78B placed at risk; operator paid 2.17M POL (about $212k) in gas; flawed code reused in 167 contracts on 10 chains holding at least $23M. Disclosed; partially mitigated.",
   "applicable_to_us": "Polymarket global only; Polymarket US (CFTC DCM) and Kalshi do not have this plumbing",
   "still_works": "Partially mitigated; still a reason not to run two-leg arbitrage on global Polymarket without atomicity.",
   "reusable": "No; risk note."
  },
  {
   "name": "Telonex Research - Top Crypto Trader Strategies on Polymarket 15-minute markets (one-week on-chain study, Feb 2-8, 2026)",
   "url": "https://telonex.io/research/top-crypto-traders-polymarket-15m",
   "venue": "Polymarket (global) 15-minute BTC/ETH/SOL/XRP Up/Down",
   "method": "The maker side is the winning side: makers netted +$728,501 and takers -$728,501 pre-fee in one week, even though makers won only 47% of fills (they earn the spread). Volume clusters near $0 and $1 and in the final minutes. Profitable wallets exist at every maker ratio; the top wallet ran about 50% maker.",
   "evidence_grade": "C+ (on-chain fills but vendor analysis, a single week, pre-fee, no code)",
   "evidence": "2,688 resolved markets (672 per coin), 46,945 wallets, 15.3M fills, $153M single-counted volume. 36.8% of wallets profitable; median wallet -$3. Top wallets: 0x63ce... +$270,569 over 1,168 markets; #2 +$154,870; #3 +$133,880; #4 +$132,409; 0x7780... +$119,675 in only 11 markets; top 5 combined $811,403; biggest loser -$139,971 over 142 markets. Maker edge about 0.48% of volume. Taker fees and maker rebates not subtracted.",
   "applicable_to_us": "Directly: Kalshi KXBTC15M (and the owner's planned ETH/SOL/XRP desks) and Polymarket US 15-min BTC",
   "still_works": "Polymarket added crypto taker fees in early 2026 (0.07xPx(1-P), about 1.75c at 50c) with maker rebates, which pushes takers further negative and makers slightly positive; the maker's risk is being picked off by faster takers in the last minutes.",
   "reusable": "Yes: it is the strongest public evidence for a maker-only 15-min crypto desk. The owner's FX rewards test lost about $457/day, so crypto must be tested on its own."
  },
  {
   "name": "Wang - Do prediction markets price events or adjudication? Evidence from the disputed Polymarket markets (Economics Letters, 2026, doi 10.1016/j.econlet.2026.113176)",
   "url": "https://www.sciencedirect.com/science/article/abs/pii/S0165176526003721",
   "venue": "Polymarket (global), UMA-disputed markets",
   "method": "During the window between a bonded resolution assertion and the UMA token vote, the real-world event is already fixed but the audited rule-correct side trades at a discount; buying it earns the discount minus the chance the token vote overturns the audited answer.",
   "evidence_grade": "B (233 disputed markets with an audited rule-correct winner; peer-reviewed)",
   "evidence": "233 disputed markets. Oracle overturned the audited-correct outcome in about 3.4% of markets (paper highlight) with a 12.4% upper bound from the coding model; votes are broad and near-unanimous, consistent with information aggregation rather than self-dealing. Discount sizes are in the full paper (paywalled).",
   "applicable_to_us": "Polymarket global only (UMA oracle); Kalshi and Polymarket US resolve internally",
   "still_works": "Alive whenever a dispute happens (e.g. the roughly $60M Strategy-BTC-sale dispute), but a 3-12% overturn rate against a few-cent discount is a coin with a sharp edge.",
   "reusable": "No for the owner's venues."
  },
  {
   "name": "ChainCatcher / PANews - Polymarket 2025 six profit models from 86-95M on-chain transactions (industry article, data Apr 2024 to Dec 2025)",
   "url": "https://panews.io/articles/c1772590-4a84-46c0-87e2-4e83bb5c8ad9",
   "venue": "Polymarket (global)",
   "method": "Folk playbook with claims: (1) information edge (Theo/Fredi9999, 11 wallets, private neighbor polls); (2) sum-to-one arbitrage (cites the $40M Saguillo figure; example 45c YES + 48c NO = 93c for 7.5%); (3) 'high-probability bonds' (buy 95c, collect $1 in 72 h, 5.2%); (4) liquidity provision and rewards ('$200/day on $10k, later $700-800/day'; 'top 0.5% earn about $200k/month'); (5) domain specialists making 10-30 trades a year; (6) speed trading (10,200 high-speed trades, $4.2M).",
   "evidence_grade": "C (claims, handles and screenshots; no methodology; headline says 95M transactions, body says 86M; the '1800% annualized' on 5.2%/72h is a mis-annualization that ignores how rarely such windows exist)",
   "evidence": "Theo's $85M on election night 2024 is documented elsewhere (also SSRN 6670638 case study); 0.51% of wallets above $1,000 profit; the LP income claims come from one named user (@defiance_cr) with no public ledger shown; the arbitrage total is lifted from the peer-reviewed Saguillo paper.",
   "applicable_to_us": "Mostly Polymarket global; the 'bonds' and LP ideas map to Kalshi/Polymarket US but with fees",
   "still_works": "Items 2 and 6 are decayed per the academic papers above; item 3 is the 3-7%/yr settlement yield; item 4 is contradicted by the owner's own LIP test for FX (-$457/day) and by Akey's finding that liquidity provision pays only when limit orders 'resolve favorably'.",
   "reusable": "Only as a list of hypotheses to test, not as evidence."
  }
 ],
 "notes": "What the whole lane says, in plain words, for the owner's situation (real-money Kalshi 15-min BTC bot, Polymarket US account):\n\n1) Every dataset agrees: takers lose, makers win. Kalshi takers -31.5% vs makers -9.6% (Burgi/Deng/Whelan, 2021-Apr 2025, 46,282 contracts); Polymarket top 0.1% earners do 47% of their volume as makers vs 17% for the bottom 95% (Akey et al., $67B); Polymarket 15-min crypto makers +$728,501 vs takers -$728,501 in one week (Telonex, Feb 2-8 2026, 46,945 wallets). The owner's own result (model takes lost 3.3-4.1c per contract) is the same finding. If the BTC desk keeps running, it should be maker-only or off.\n\n2) No academic paper finds a tradeable directional or latency edge in 15-min crypto binaries. OpenMarket (arXiv 2607.26245): Polymarket lags Binance by a median 16 ms and reacts to 5-bps moves in 347 ms; a simulated positive-EV strategy nets -0.116 per trade after a 1% fee and 0.5% slippage. Vendor write-ups on Kalshi KXBTC15M (left to the separate Kalshi sweep) point the same way: BotForKalshi reports +0.67c gross vs 1.55c average taker fee over 6,298 windows; TurbineFi found 102 of 4,904 strategies profitable in a 30-day window ending 2026-04-29, all 432 mean-reversion variants losing. Grade C, vendor conflicts.\n\n3) Arbitrage was real and large ($39.6M on Polymarket Apr 2024-Apr 2025, peer-reviewed) but is captured by bots in seconds and per-opportunity profit has fallen to about 8c (Gebele et al. 2026). The one structural gap left for a human-scale operator is cross-venue Kalshi vs Polymarket US on identical-rule political/sports markets (2-4% typical, 3-7c in the 2024 election), which needs maker fills, matching resolution wording, and weeks of locked capital.\n\n4) The 'near-certain grind' (buy 95-99c, hold to settlement) is a yield, not an edge: 3.06-6.89% per year on locked capital (Gebele & Matthes), consistent with Whelan's +2.6% for makers at 50c+ and +3.1% pre-fee on a 95c contract that wins 98%. Fees are small at those prices (Kalshi taker 0.34c at 95c, 0.21c at 97c, 0.07c at 99c; Polymarket US nearly identical), so the real costs are lock-up and resolution risk (3.4-12.4% overturn on disputed Polymarket markets).\n\n5) The cheapest robust finding is longshot avoidance: sub-10c purchases lose 19.3c per $1 on Polymarket (Cardozo), over 60% on Kalshi (Whelan); Kalshi macro longshots under 30c are overpriced by about 7 points, worst in unemployment markets (Krause). Favorites at 90c+ earn only +0.83c per $1 pre-fee on Polymarket; politics +1.0 to +1.4%; sports show no bias at all (Cardozo), which matches the owner's Lab 6 'no edge vs Pinnacle'.\n\n6) Fee facts used for the 'still works' calls (public fee pages checked Oct 2, 2026, computed in scratchpad work/fees.py): Kalshi taker 0.07xPx(1-P) rounded up per order (1.76c at 50c, 0.63c at 90c, 0.34c at 95c; S&P/Nasdaq markets 0.035), maker 0 or 0.0175 depending on market; Polymarket US taker 0.0695xPx(1-P) capped 1.74c, maker rebate 0.0125 rate up to 0.31c, taker-volume rebates 10-50% above $250k/month from 2026-10-01; Polymarket global crypto 0.07 taker since early 2026, fees on all markets since 2026-03-30. Polymarket US launched 15-min BTC Up/Down (Chainlink BTC/USD) on 2026-09-22; Kalshi KXBTC15M settles on a 60-second average of the CF Benchmarks index.\n\n7) Risks documented with real money lost: 5-minute settlement manipulation on global Polymarket ($8.2M to 821 wallets; absent at 15 minutes); ghost fills reverting up to 24.3% of matched orders at peak ($1.49M attacker profit); insider flow ($143M, Mitts & Ofir) that a copy-trader cannot front-run.\n\n8) Corroborating concentration studies not listed as items: Solidus Labs via CoinDesk (Dec 2025-Feb 2026 politics, about $16M profit, 0.55% of maker wallets and 0.26% of taker wallets each took about $8M); Sergeenkov via Dune (2.5M addresses Apr 2024-Apr 2026: 84.1% lose, 0.033% = 840 addresses above $100k); Kalshi's own Kagan & Baiocchi calibration note (2,243,741 resolved markets, Brier about 0.09 at 3 months falling below 0.02 at close; platform-affiliated). Theory only: Feil & Nendel, Optimal Market Making in Prediction Markets (arXiv 2607.17991) adds settlement risk to inventory risk for a binary-market maker; Chen et al. (arXiv 2609.14038) on fee design for seeded liquidity.\n\n9) Public datasets worth pulling for the owner's lab: Akey et al.'s Polymarket user dataset (huggingface.co/datasets/vgregoire/polymarket-users, trades Nov 2022-Mar 2026), OpenMarket synchronized Polymarket-Binance 15-min data, Dubach's trade-direction replication (zenodo 10.5281/zenodo.23164515), Gomez-Cram replication repo (github JasonJSant/polymarket-skilled-traders, note operator-wallet double counting).\n\n10) Access notes: SSRN returned 403 for every paper page, so Ng et al., Krause, Mitts & Ofir and Gomez-Cram numbers come from abstracts, press coverage and the SSRN blog; the Economics Letters paper is paywalled (abstract only); kalshi.com research page returned 429 twice; the GWU 'Makers or Takers' 2026-001 PDF is a 6-page image file with no text layer, so the UCD January 2026 text was used. No GitHub repos were cloned in this lane, no credentials were seen, and nothing was written to the project repo."
}


---
## result 3 

{
 "lane": "Open-source market-making and latency bots whose machinery transfers to 15-minute binaries (Hummingbot PMM/Avellaneda/XEMM, hftbacktest, Polymarket makers, adverse-selection/VPIN tooling, inventory control, queue-position models)",
 "items": [
  {
   "name": "kachence/polymm (Polymarket sports maker/arb bot, the only wallet-backed one found)",
   "url": "https://github.com/kachence/polymm",
   "venue": "Polymarket (global CLOB), sports and esports markets",
   "method": "De-vig sportsbook odds into a fair probability. Post a limit bid 1 cent above the best bid only when edge over the price is at least 5-7%. When one leg fills, immediately bid the opposite outcome so the pair costs under $1 and the edge is locked (1 - p - q). If the hedge never fills you hold a directional bet entered at 7%+ edge. A reactive loop emits EDGE_LOST and cancels resting orders when fair value moves against them (author: 'not fast enough'). Python, async, ~10 loops, websockets for fills and book.",
   "evidence_grade": "A",
   "evidence": "Public profile polymarket.com/@b00k13 = proxy wallet 0x1c5575dc20e4ea54d1bb09ccda72ccf8a3b684ce (profile bio names polymm). Checked 2026-10-14 (PT) via Polymarket's public APIs: leaderboard all-time profit $5,785.13; 5,143 trades; my reconstruction = closed realized +$23,730 minus worthless hedge legs -$17,952 = net +$5,778 over 4,728 closed positions. Jan-Apr 2026 (the period the open-sourced Python bot ran): about +$1,862 Jan, +$2,405 Feb, +$524 Mar, +$178 Apr = +$4,969, matching the author's blog (+$4,973 net; arb leg +$8,293, directional residual -$3,185; 3,858 bets; $95,830 volume; 47.5% win rate). Jun-Oct 2026 (private Rust rewrite, not released) about +$809 with Aug -$482. Fill rate decayed 37.4% (Jan) -> 15% (Feb) -> 5% (Mar) -> 1% (Apr).",
   "applicable_to_us": "Polymarket US only if it lists the same sports markets; the owner's rule is no real money on sports. The machinery (quote at edge, hedge the pair, pull on reference move) ports to 15-min binaries with the settlement index as the reference.",
   "reusable": "MIT. The quote-at-edge + pair-hedge + EDGE_LOST cancel pattern; the author's monthly P&L accounting (realized winners minus worthless legs) is also how to audit any Polymarket maker.",
   "still_works": "Author retired it: fill rate collapsed as faster bots sat ahead in the book and stale odds got picked off (adverse selection). Needs a paid odds API (~$3/day) and Supabase. Edge was speed-dependent; expect the same decay on 15-min crypto where the reference price is public."
  },
  {
   "name": "nkaz001/hftbacktest (queue-position + latency-aware MM backtester, GLFT/grid tutorials)",
   "url": "https://github.com/nkaz001/hftbacktest",
   "venue": "Binance Futures and Bybit (backtest from L2/L3 ticks; Rust live connectors)",
   "method": "Tick-by-tick replay with feed and order latency models and pluggable queue-position models (power/log probability models; RiskAverse). GLFT quotes: half-spread = C1 + (tick/2)*sigma*C2, skew = sigma*C2, bid = fair - (half-spread + skew*q), with A and k fit by regressing log arrival intensity on distance from mid over a 10-minute window (A~2.99, k~0.042 on ETHUSDT), recalibrated every 5 s, GTX post-only, max position 20. Queue rule for large-tick assets: quote at best bid/ask, back off one tick when own top-of-book queue < 250,000 and inventory skew pushes against that side; refresh every 100 ms.",
   "evidence_grade": "B",
   "evidence": "Backtests with code: GLFT grid ETHUSDT 2022-10-03..07 Sharpe 19.77, +5.59%, max DD 0.74%; LTCUSDT 2023-07-01..05 +12.25%; raw unadjusted skew lost -2.06% in one day (Sharpe -246) until skew was scaled by 0.05. CRVUSDT Jul-Aug 2024 queue-based MM: Sharpe 13.2-16.5, return 2.5-3.95x, max DD 9.6-18%. Latency test (ETHUSDT 2023-04-01..05): live-measured latency +0.78% SR 1.54, but feed-derived or amplified latency -0.10% to -0.22%. Author attributes most profit to the 0.005% maker rebate; says educational only. No live P&L published. 4.9k stars, MIT.",
   "applicable_to_us": "Arena only as code (no Kalshi/Polymarket connector); the queue models and GLFT formulas port to the owner's recorder data.",
   "reusable": "MIT, Python (Numba) + Rust. Queue-position models, latency models, GLFT calibration, the one-tick back-off rule, markout/fill comparison harness.",
   "still_works": "Mechanisms are sound; the P&L depended on maker rebates and sub-second cancel speed that Kalshi/Polymarket US do not offer. Use it to size adverse selection, not to expect those Sharpes."
  },
  {
   "name": "Hummingbot PMM + Avellaneda V1 strategies (inventory skew, refresh tolerance, hanging orders, session-end spread)",
   "url": "https://github.com/hummingbot/hummingbot",
   "venue": "40+ CEX/DEX connectors (no Kalshi/Polymarket)",
   "method": "PMM: external price_source (another exchange or custom API) for fair value; inventory skew = piecewise-linear bid/ask size multipliers from 0 to 2 around target_base_pct within an inventory range (bid = 2 - 2x below target, 1 - 2(x-0.5) above; ask = 2 - bid); order_refresh_tolerance_pct (only replace if price moved), filled_order_delay (60 s), hanging orders, price ceiling/floor and moving band, order_optimization (join top of book ignoring dust), take_if_crossed. Avellaneda: reservation price offset grows with inventory distance from target; spread grows with volatility and book liquidity (alpha, kappa from 200-tick buffers) and shrinks as the session end approaches (execution_timeframe), gamma 1-20.",
   "evidence_grade": "C",
   "evidence": "No P&L claims; repo advertises $34B user volume, not profit. Only community case found: Jan 2021 RLC/USDT week, 1,185 trades, P&L $60.49 + $12.39 mining rewards = $72.88; same setup on XEM/ETH -1.2% after rewards. 20.4k stars, Apache-2.0.",
   "applicable_to_us": "Mechanisms only; no venue connector for Kalshi or Polymarket US.",
   "reusable": "The skew calculator formula, refresh-tolerance and filled-order-delay logic, and the time-to-session-end spread shrink (maps to time-to-close in a 15-min binary).",
   "still_works": "Generic machinery; profitability was never demonstrated publicly and depends entirely on the fair-value source and fees."
  },
  {
   "name": "Hummingbot XEMM executor + pmm_dynamic controller (hedge-reference quoting; NATR spreads, MACD shift)",
   "url": "https://hummingbot.org/v2-strategies/",
   "venue": "Hummingbot connectors (maker on one venue, hedge on another)",
   "method": "XEMM: maker price = taker quote / (1 - target_profitability - tx_cost) for sells, / (1 + ...) for buys; while resting, recompute net profitability each tick and cancel/re-place if it leaves [min_profitability, max_profitability]; on maker fill send a market hedge on the taker venue. pmm_dynamic: spread multiplier = NATR(length)/100; reference price = close * (1 + shift) where shift = 0.5*(MACD z-score) + 0.5*(MACD histogram sign), capped at NATR/2.",
   "evidence_grade": "D",
   "evidence": "No published backtests or live results; Condor docs say backtests are for parameter research and 1-minute candles only simulate about one fill per minute.",
   "applicable_to_us": "Mechanism only. The 'cancel when profitability leaves a band' rule is a clean pull-on-reference-move implementation for a Kalshi/Polymarket US quote against a Binance/BRTI reference.",
   "reusable": "Apache-2.0 Python; the band-based cancel logic and NATR-scaled spreads.",
   "still_works": "Untested publicly; cross-venue hedging is covered by another sweep."
  },
  {
   "name": "warproxxx/poly-maker (Polymarket maker with toxicity-widened spreads and a regime machine)",
   "url": "https://github.com/warproxxx/poly-maker",
   "venue": "Polymarket global CLOB (political markets)",
   "method": "Fair value = depth-weighted microprice adjusted by an EWMA of signed trade flow. Reservation r = FV - skew(inventory). Half-spread delta = base + c_vol*sigma + c_tox*toxicity, where toxicity is an EWMA of per-fill markouts. Quotes BUY-YES at r - delta and BUY-NO at (1 - r) - delta (both legs are bids; filled pairs merge to USDC at locked edge 1 - p - q). Size shrinks near a soft inventory cap, then the adding side is pulled. Regimes: QUIET (farm rewards), TRENDING (lean, widen, halve size), EVENT (pull quotes after a sweep/jump, cool off), REDUCE_ONLY, HALTED (stale data, resolution, kill switch).",
   "evidence_grade": "D",
   "evidence": "README: 'market making on Polymarket is competitive and can lose money'; 'live-verified end to end', 83 tests; no P&L or wallet. ~1.5k stars, MIT, last push Apr 2026.",
   "applicable_to_us": "Polymarket global only as code; the toxicity term, regime machine and two-bid pairing port to Polymarket US and Kalshi 15-min markets.",
   "reusable": "MIT Python: markout-EWMA spread term, EVENT-regime quote pull, size-then-pull inventory control, pair-merge accounting.",
   "still_works": "Unknown; designed for reward farming on long-dated political markets, where quiet regimes dominate. 15-min crypto is mostly TRENDING/EVENT by its definition."
  },
  {
   "name": "Polymarket/poly-market-maker (official keeper: Bands and AMM strategies)",
   "url": "https://github.com/Polymarket/poly-market-maker",
   "venue": "Polymarket global CLOB",
   "method": "Every sync_interval (30 s) fetch the CLOB midpoint, compute desired orders, diff against open orders, cancel/place. Bands: each band = [minMargin, maxMargin] from target price with size kept between minSize and maxSize (cancel down to avgSize if over, place up to avgSize if under); buy-YES and sell-NO treated as one pool. AMM: order sizes from a virtual concentrated-liquidity curve between spread and depth in steps of delta, capped by max_collateral.",
   "evidence_grade": "D",
   "evidence": "No results; 'experimental'; last push Jul 5, 2024. 327 stars, MIT.",
   "applicable_to_us": "Polymarket (global API); the band-maintenance inventory controller is venue-agnostic.",
   "reusable": "MIT Python; band bookkeeping and the AMM-curve sizing.",
   "still_works": "No fair value beyond the CLOB midpoint and a 30 s cycle: too slow for 15-min markets as-is."
  },
  {
   "name": "ctubio/Krypto-trading-bot (K) and michaelgrosner/tribeca (classic HFT MM with EWMA/trend/STDEV protection)",
   "url": "https://github.com/ctubio/Krypto-trading-bot",
   "venue": "Spot CEXs (Coinbase, Binance, Kraken, KuCoin, BitMEX, Bitfinex, HitBTC, Poloniex)",
   "method": "Fair value modes BBO / wBBO / rwBBO (rwBBO = microprice). Quoting modes Top, Mid, Join, InverseJoin, HamelinRat (quote just ahead of the largest resting order), Depth. pDiv position-divergence limit stops orders that add to the imbalance (dynamic Linear/Sine/SQRT curves); APR places larger, more aggressive orders to rebalance. EWMA protection caps new quote prices and widths; Trend protection (Ultra/Micro EMAs) stops selling in uptrends and buying in downtrends; STDEV/Bollinger limits on quote prices; PingPong/Boomerang/AK-47 pair fills with opposite-side 'pongs'.",
   "evidence_grade": "D",
   "evidence": "No profitability claims ('an art and a science'); free mode delays book updates to every 121 s and unlocking costs 0.00121 BTC per API key per exchange. K 3.7k stars (MIT), tribeca 4.1k stars.",
   "applicable_to_us": "Mechanisms only.",
   "reusable": "Trend protection (one-sided quote pull on a reference-trend trigger), STDEV-based dynamic width, pDiv divergence stop, HamelinRat queue-aware placement.",
   "still_works": "Code is C++ and tied to spot CEXs; the protection ideas are what to port."
  },
  {
   "name": "ojo-network/turbine-py-client market-maker example (binary-native MM with time decay and an adverse-selection breaker)",
   "url": "https://mintlify.wiki/ojo-network/turbine-py-client/examples/market-maker",
   "venue": "Turbine (Polygon, Pyth-priced YES/NO binaries with strikes and expiries)",
   "method": "P(YES) = Phi(z), z = % distance of price from strike / (volatility over remaining time), volatility from a rolling window floored at 3%/day; momentum EMA shifts the target. Bids below / asks above fair, spread widens with volatility and momentum, several levels with geometrically decreasing size. Inventory: YES target -= net exposure * 0.05 (exposure in [-1,1]). Adverse selection: if >= 3 fills in the last 30 s and > 80% on one side, cancel all orders for that asset and stay dark 10 s. Pull all quotes in the final 30 s, double spreads in the final 90 s. Refresh when fair moves > 2%, place new before cancelling old, min 2 s between rebalances. Skip the losing side when YES > 0.65 or < 0.35.",
   "evidence_grade": "D",
   "evidence": "No realized P&L; the page gives only target ranges (40-60% fill rate, 1-2% spread capture per round trip).",
   "applicable_to_us": "Kalshi and Polymarket US 15-min markets: this is the closest published template (strike, expiry, settlement-index reference).",
   "reusable": "Python example; the fair-probability model, time-decay rules (final 90 s / 30 s), and the one-sided-fill breaker.",
   "still_works": "Unproven; the rules are sensible defaults to test in the arena, not evidence of edge."
  },
  {
   "name": "doge-8/btc5m-web (Polymarket 5m/15m up-down framework with Binance-vs-oracle offset calibration)",
   "url": "https://github.com/doge-8/btc5m-web",
   "venue": "Polymarket global BTC/ETH/SOL 5-minute and 15-minute Up/Down",
   "method": "Four websockets: Polymarket book, Chainlink oracle, user fills, Binance price. Binance leads the oracle, so a diff signal is built after auto-calibrating the Binance-to-oracle offset with MAD outlier filtering and a trimmed mean. Example strategies: D1 tail-sweep entry on large diff with a diff-crosses-zero stop; P1 'prob-chase' enters when market probability lags a fair-probability table lookup; P2 end-game crossing at 90-30 s remaining. Limit (maker) variants supported; 1-second backtest recording.",
   "evidence_grade": "D",
   "evidence": "README disclaims any profit; 21 stars, 18 forks, 1 commit, MIT.",
   "applicable_to_us": "Polymarket global API; the offset calibration and lag-based maker entries port to Polymarket US (settles on CF Benchmarks BRTI) and Kalshi.",
   "reusable": "TypeScript; the reference-offset calibration and end-game timing windows.",
   "still_works": "Unknown; the lag it relies on is public knowledge and shrinks as more bots quote it."
  },
  {
   "name": "MalcolmMcGough/polymarket-trading-bot-scalping + 'watch Chainlink not Binance' write-up",
   "url": "https://github.com/MalcolmMcGough/polymarket-trading-bot-scalping",
   "venue": "Polymarket global crypto 5-minute markets",
   "method": "Use the settlement oracle's own feed (Chainlink Data Streams) as fair value, not Binance; treat a feed with updatedAt older than 2-3 s near resolution as stale; no new positions after T-90 s; ignore the final 15 s; skip FOMC/CPI/NFP windows. Author observed Binance and Chainlink diverging 0.3-0.8% for 10-30 s in volatile windows.",
   "evidence_grade": "C",
   "evidence": "Self-reported win rate 52% -> 57-58% after switching feeds; no sample size, period or P&L given; author promotes the bot.",
   "applicable_to_us": "Directly: Polymarket US 15-min BTC settles on CF Benchmarks BRTI (60 observations in the last minute, averaged), so 'quote off the settlement index, not Binance last' is the transferable rule.",
   "reusable": "The stale-feed gate and T-90 s cutoff.",
   "still_works": "Plausible but unmeasured; a 5-point win-rate gain at ~50 cents is still roughly break-even after taker fees."
  },
  {
   "name": "'The Market Maker's Dilemma' live top-of-book MM experiments on Binance BTC perp (paper, no repo)",
   "url": "https://arxiv.org/abs/2502.18625",
   "venue": "Binance USDT-margined BTC perpetual",
   "method": "Minimum-size maker orders at the touch, continuous and periodic quoting; fills measured by queue state; 1-second markouts; imbalance-following and contrarian ('reversal') variants.",
   "evidence_grade": "A",
   "evidence": "Live: Feb 12-19, 2024, 232,897 orders, 127,051 filled (55%); Aug 21-31, 2024, 172,800 orders, 56% filled. 1-second post-fill markouts negative in every queue state (-0.06 to -1.16 bp before rebate). Fill probability ~30% when own-side queue is large and opposite small, > 90% in the reverse case. Imbalance-based maker strategies net -0.47 bp (no cancel) and -0.49 bp (with cancel); imbalance taker +1 bp gross, -1.96 bp net of fees. Only contrarian fills during 'reversals' showed positive return.",
   "applicable_to_us": "Evidence, not code: expect every resting quote on a 15-min binary to be adversely selected on average; fill probability and post-fill return trade off.",
   "reusable": "Measurement design: queue-state-conditioned fill rate and 1 s/10 s/60 s markout curves for the owner's recorder.",
   "still_works": "Structural finding; it is why naive quoting loses."
  },
  {
   "name": "Avellaneda-Stoikov live on Hyperliquid BTC perps (archived, documented negative result)",
   "url": "https://gitea.com/aurelius/hyperliquid-hybrid-bot-aug2026",
   "venue": "Hyperliquid BTC perpetual",
   "method": "reservation = mid - normalized_inventory * gamma * volatility * mid * 150; gamma by regime (GREEN 0.015, YELLOW 0.012, RED 0.018, DEAD 0.006) from a z-score of spread/volume/fill-rate; spread_bps = base + vol * mult * regime multiplier (1.0/1.15/1.4/1.6), floor 10 bps; TP 15 bps after 30 s, SL 40 bps IOC, 120 s time exit, 60 s GTC timeout; $7 clips, max 2 positions, 25% drawdown kill.",
   "evidence_grade": "C",
   "evidence": "Self-reported live: Aug 22-25, 2026 (72 h), $45.00 -> ~$40.50 (-10%); fill rate 25.5%, win rate 31.5%, cancel rate 73.5%, about -$0.60/hour after tuning. Author's causes: low fills on GTC quotes, adverse selection in a thin book, constant replacement, micro capital, rebate too small.",
   "applicable_to_us": "Lesson only: a textbook AS quoter at small size lost to adverse selection even with a maker rebate; the same failure mode applies on 15-min binaries with no rebate.",
   "reusable": "Regime-gamma idea; the exit stack (TP/SL/time) as a template.",
   "still_works": "It did not work; included as a calibrated warning."
  },
  {
   "name": "JJJerome/mbt_gym (closed-form Avellaneda-Stoikov and Cartea-Jaimungal agents, RL benchmarks)",
   "url": "https://github.com/JJJerome/mbt_gym",
   "venue": "Simulation (model-based LOB)",
   "method": "Gym environments for market making and execution with analytically optimal baseline agents for AS and CJ (arrival intensity, fill probability, inventory penalty, terminal time), vectorized for RL training.",
   "evidence_grade": "B",
   "evidence": "ACM ICAIF 2023 paper (arXiv 2209.07823); optimal agents reproduce theory; no money. 181 stars, BSD-3.",
   "applicable_to_us": "Arena only: generate the optimal quote schedule for a 15-minute horizon (how spread and skew should tighten toward the close) and benchmark the owner's heuristics against it.",
   "reusable": "BSD-3 Python; AS/CJ optimal-quote code.",
   "still_works": "Theory; the gap is the fill-intensity and adverse-selection parameters, which must come from the owner's recorder."
  },
  {
   "name": "javifalces/HFTFramework (Alpha-AS: RL-tuned Avellaneda-Stoikov, PLOS ONE 2022)",
   "url": "https://github.com/javifalces/HFTFramework",
   "venue": "Crypto L2 (Kraken/Binance BTC/USDT) and FX via MetaTrader 5",
   "method": "Java engine + Python strategies over ZeroMQ; Avellaneda-Stoikov with dynamic spreads; Gen-AS tunes gamma etc. with a genetic algorithm; Alpha-AS-1/2 use deep RL to adjust risk aversion and the AS output; Gymnasium wrapper.",
   "evidence_grade": "B",
   "evidence": "30 days of BTC/USD L2 tick backtest: Gen-AS beat the two baselines on all indicators; Alpha-AS 'substantially outperformed Gen-AS on Sharpe, Sortino and P&L-to-MAP' but with a few heavy drawdowns. README: 'not validated in a live trading environment'. 307 stars, Apache-2.0.",
   "applicable_to_us": "Arena only.",
   "reusable": "Same-code backtest/live design; RL gamma tuning as an idea.",
   "still_works": "Backtest-only; drawdown clusters flagged by the authors."
  },
  {
   "name": "SaadSouilmi/Queue-Reactive (large-tick LOB simulator fit on Databento MBP-10)",
   "url": "https://github.com/SaadSouilmi/Queue-Reactive",
   "venue": "Simulation (US large-tick assets)",
   "method": "Limit order book as a continuous-time Markov jump process; event rates (limit, cancel, trade) conditioned on queue sizes, imbalance and spread; C++ engine with Python calibration; sample_strategy executable to test quoting rules in the simulated book.",
   "evidence_grade": "B",
   "evidence": "Code release for arXiv 2603.24137 (Noble, Rosenbaum, Souilmi); 13 stars, MIT. No trading P&L.",
   "applicable_to_us": "Arena only: a way to estimate fill probability versus queue position for a 1-cent-tick binary book from the owner's recordings.",
   "reusable": "MIT C++/Python calibration pipeline.",
   "still_works": "Research tool; needs L2-with-queue data (Kalshi publishes quotes; Polymarket only trades)."
  },
  {
   "name": "intrepidkarthi/orderbook (Go LOB engine; OFI is contemporaneous, not predictive)",
   "url": "https://github.com/intrepidkarthi/orderbook",
   "venue": "Simulator + live Coinbase L2 capture",
   "method": "Order-flow imbalance, Kyle's lambda, delta/CVD signals against a deterministic simulator; Avellaneda-Stoikov backtest; live OFI from Coinbase L2.",
   "evidence_grade": "B",
   "evidence": "OFI contemporaneous R^2 ~0.24 vs predictive R^2 ~0.0004 (577x gap, and the residual sign points the other way); a 94.5%-accurate aggressor rule still produced a CVD off by 169%; CVD divergence lost to a price-only control. Never ran live. 23 stars, MIT.",
   "applicable_to_us": "Evidence: do not use OFI/CVD as the trigger for pulling quotes on 15-min markets; use it as an explainer after the fact.",
   "reusable": "Experiment design for testing 'predictive vs contemporaneous' on the owner's tapes.",
   "still_works": "Negative result; stands."
  },
  {
   "name": "flowrisk (VPIN) + screamer microstructure operators (VPIN, QueueImbalance, MicroPrice, ContOFI, Effective/Realized spread)",
   "url": "https://github.com/hanxixuana/flowrisk",
   "venue": "Library (examples on US stocks and Deribit BTC-perp trades)",
   "method": "flowrisk: Easley-Lopez de Prado-O'Hara VPIN with bulk volume classification (MA/EWMA buckets), recursive estimator with confidence bands. screamer (github.com/screamer-labs/screamer): streaming VPIN over a volume clock, queue imbalance in [-1,1], micro-price offset proportional to imbalance, Cont-Kukanov-Stoikov OFI, effective spread 2|price-mid| and realized spread 2*D*(price - later mid); the gap is the adverse-selection cost.",
   "evidence_grade": "D",
   "evidence": "No trading results in either library (flowrisk 99 stars, MIT, last pushed 2021). The reason to care is Bartlett & O'Hara (2026, 41.6M Kalshi trades): one-sided flow predicts maker losses in single-name markets.",
   "applicable_to_us": "Kalshi (publishes taker side and quotes, so VPIN and realized spread are computable) and Polymarket US; the toxicity term feeds the spread.",
   "reusable": "MIT Python; realized-vs-effective spread as the per-fill markout metric to widen or pull quotes.",
   "still_works": "Tools, not edges; the owner's own markout EWMA is the practical version."
  },
  {
   "name": "sstoikov/microprice (fair value inside the spread from imbalance state)",
   "url": "https://github.com/sstoikov/microprice",
   "venue": "Research (BAC/CVX, March 2011)",
   "method": "Micro-price = expected future mid given order-book imbalance and spread state, estimated as a Markov chain over imbalance buckets; leans toward the thin side of the book.",
   "evidence_grade": "D",
   "evidence": "Notebook and SSRN paper by the author; no P&L. 482 stars.",
   "applicable_to_us": "Mechanism: use a micro-price (or rwBBO) for the YES book as the reservation anchor before applying inventory skew.",
   "reusable": "Notebook code; license not stated.",
   "still_works": "Standard estimator; cheap to implement on 1-cent books."
  },
  {
   "name": "chainstacklabs/hyperliquid-hip-4 (passive MM on binary outcome books)",
   "url": "https://github.com/chainstacklabs/hyperliquid-hip-4",
   "venue": "Hyperliquid HIP-4 outcome markets (YES/NO books, USDH; mainnet since 2026-05-02 with a BTC daily binary; testnet has a HYPE 15-minute binary)",
   "method": "Fair value from each book's mid (or 1 - opposite side if a book is empty); quote both YES and NO books at fair +/- half-spread (example 0.04); ~$12 orders just above the $10 minimum; per-side exposure cap after which that side stops bidding; cancel/replace only when desired price drifts past a repost threshold; cancel all on exit.",
   "evidence_grade": "D",
   "evidence": "No results; testnet by default; 10 stars.",
   "applicable_to_us": "Template for two-book quoting with per-side caps; the venue itself is not one of the owner's.",
   "reusable": "Python; the repost-threshold hysteresis and per-side cap.",
   "still_works": "Unproven; mid-based fair value with no reference feed will be picked off on crypto binaries."
  },
  {
   "name": "alihaskar/gap-mm (Bybit post-only MM; amend-over-cancel execution; gap-score skew)",
   "url": "https://github.com/alihaskar/gap-mm",
   "venue": "Bybit spot and linear",
   "method": "Rust engine keeps an L2 book, scans for empty tick ranges (gaps) per side and scores ask-side resistance 0-1; high score = contrarian sell skew (tight ask 1 tick from mid, wide bid 100 ticks), low score = contrarian buy skew, ~0.5 = both wide (sit out). Reconciles target quotes with working orders preferring amend over cancel/replace; PostOnly; ~438 us p50 pipeline on a mock server.",
   "evidence_grade": "D",
   "evidence": "README: 'no backtested edge', no inventory control, reference implementation only. 21 stars, MIT.",
   "applicable_to_us": "Execution pattern only.",
   "reusable": "Amend-vs-cancel reconciliation loop; 'sit out when the signal is ambiguous'.",
   "still_works": "Not an edge; the execution hygiene is reusable."
  },
  {
   "name": "evan-kolberg/prediction-market-backtesting + kacho.io 5-minute crypto dataset",
   "url": "https://github.com/evan-kolberg/prediction-market-backtesting",
   "venue": "Polymarket (NautilusTrader extension; BTC 5-minute sandbox); Kalshi not supported (needs L2 history)",
   "method": "Nautilus adapters for Polymarket with fee and execution modeling; v4.1-alpha adds live sandbox plumbing for BTC 5-minute markets. Companion data: kacho.io CC0 dataset of ~89,000 Polymarket 5-minute Up/Down markets (BTC from 2026-03-24, six other coins from 2026-04-05, through 2026-05-18), 1 Hz top-of-book for Up and Down tokens plus bid depth within 5 cents, ~26.8M rows, ~725 MB parquet.",
   "evidence_grade": "C",
   "evidence": "Backtester reports no results (1.2k stars, mixed MIT/LGPL/GPL). Dataset author: his BTC bot backtested 3-5% ROI after fees but lost about $600 live; 'fees largely offset the modeled return'.",
   "applicable_to_us": "Arena: the only sizable public tick dataset for crypto up/down binaries; good for testing quote-pull and skew rules offline before the owner's own recorder has months of data.",
   "reusable": "Data (CC0) and the Nautilus fill/fee modeling.",
   "still_works": "Data is 5-minute Polymarket global, not 15-minute Kalshi/Polymarket US; book shapes differ."
  },
  {
   "name": "spfunctions/polymarket-sports-mm (sfmm): 'prices for score, sizes for view' rewards MM",
   "url": "https://github.com/spfunctions/polymarket-sports-mm",
   "venue": "Polymarket global sports (liquidity rewards)",
   "method": "Bid one tick below and ask one tick above midpoint to maximize the reward score S = ((v - s)/v)^2 (two-sided scores ~3x one-sided); express inventory and view only through size: bid size = base*(1+skew), ask size = base*(1-skew), skew = view + inventory mean-reversion. Circuit breaker pulls all quotes when the midpoint jumps past a threshold, 10 s cooldown. Limits: 1,000 contracts/market, $5,000 total, $500 daily loss halt.",
   "evidence_grade": "D",
   "evidence": "Alpha (0.1.0, 2026-04-05); dry-run output and 47 tests only; no P&L. MIT.",
   "applicable_to_us": "Polymarket only where rewards exist; the size-not-price inventory control is reusable anywhere a program pays for tight quotes (the owner already judged Kalshi LIP a NO-GO).",
   "reusable": "Size-skew inventory control; jump-triggered breaker.",
   "still_works": "Reward programs change monthly; the mechanism is independent of them."
  },
  {
   "name": "Bartlett & O'Hara, 'Adverse Selection in Prediction Markets: Evidence from Kalshi' (data paper)",
   "url": "https://law.stanford.edu/publications/adverse-selection-in-prediction-markets-evidence-from-kalshi/",
   "venue": "Kalshi (all markets)",
   "method": "Kyle's lambda and Glosten-Harris decomposition plus an adapted VPIN on 41.6 million trades to measure informed price impact and maker profit per contract.",
   "evidence_grade": "A",
   "evidence": "Single-name markets show more informed price impact yet makers earn about twice as much per contract there; a frequency-magnitude decomposition shows traders overbet YES in markets that mostly settle NO (a behavioral surplus that offsets adverse selection); one-sided order flow (VPIN) predicts maker losses in single-name markets but not broad-based ones. SSRN 6615739, Apr 21, 2026; NBER version Jul 2, 2026.",
   "applicable_to_us": "Kalshi directly (it publishes taker side and quotes); Polymarket public records contain only executed trades, so VPIN is harder there.",
   "reusable": "The measurement recipe (lambda, realized vs effective spread, VPIN by market type) for the owner's recorder.",
   "still_works": "Structural; tells you where maker P&L exists (behavioral YES-overbetting) and which flow to fade."
  },
  {
   "name": "BitMEX/sample-market-maker (baseline two-sided quoter with position limits)",
   "url": "https://github.com/BitMEX/sample-market-maker",
   "venue": "BitMEX",
   "method": "Blanket bids and asks around mid at fixed offsets; if position passes a user limit, stop quoting that side. BitMEX's companion PDF rule of thumb: move both quotes by half the spread for each full clip transacted.",
   "evidence_grade": "D",
   "evidence": "Forks say it 'will likely lose money'; no results.",
   "applicable_to_us": "Mechanism only.",
   "reusable": "Half-spread-per-fill skew as the simplest inventory rule.",
   "still_works": "Baseline to beat, not an edge."
  },
  {
   "name": "CMLKevin/polypigeon (Avellaneda-Stoikov with time-to-resolution on Polymarket)",
   "url": "https://github.com/CMLKevin/polypigeon",
   "venue": "Polymarket global (150 'premium' markets, $50K-$20M volume, >= 3 days to resolution)",
   "method": "r = s - q*gamma*sigma^2*(T - t) with gamma 0.3-0.7 and T - t = time to resolution; spread = base + 2.5*sigma*sqrt(holding_period) + 0.02*|inventory_ratio|; scans every 5 s; paper mode and backtest included.",
   "evidence_grade": "D",
   "evidence": "No results; 3 stars, 7 commits, MIT.",
   "applicable_to_us": "The explicit (T - t) term is the right shape for a 15-minute contract; the parameters would need re-fitting to a 900 s horizon.",
   "reusable": "Small Python codebase; the formula.",
   "still_works": "Untested."
  }
 ],
 "notes": "Bottom line: in this lane only one repo has third-party-verifiable profit, kachence/polymm (Polymarket sports arb/maker; on-chain wallet 0x1c5575dc20e4ea54d1bb09ccda72ccf8a3b684ce, leaderboard all-time +$5,785 on 2026-10-14, ~$4,969 of it in Jan-Apr 2026 when the released code ran), and it decayed to a 1% fill rate within four months from speed and adverse selection. Everything else is backtest-grade (hftbacktest, HFTFramework, mbt_gym, Queue-Reactive) or unproven (poly-maker, official keeper, Krypto-trading-bot, turbine, HIP-4, btc5m-web). Two documented live negatives are the most useful calibration: a textbook Avellaneda-Stoikov bot on Hyperliquid lost 10% in 72 h with 25% fills and 31% wins, and the Binance BTC-perp paper found 1-second markouts negative in every queue state across 400k live orders. Mechanisms worth porting to the owner's 15-minute desks, in order: (1) fair value for a binary = Phi((reference - strike)/(sigma*sqrt(time left))) using the settlement index (Polymarket US BTC 15-min settles on CF Benchmarks BRTI, 60 observations averaged over the final minute; listed since 2026-09-22 ~9:00 AM PT), with a calibrated Binance-to-index offset (btc5m-web); (2) reservation price skewed by inventory and time left (Avellaneda via Hummingbot/polypigeon; GLFT skew via hftbacktest, scaled down ~20x as the tutorial had to); (3) spread = base + vol term + toxicity term from an EWMA of your own per-fill markouts (poly-maker), widened 2x in the final 90 s and pulled in the final 30 s (turbine); (4) pull triggers: sweep/jump EVENT regime, one-sided-fill breaker (>= 3 fills in 30 s, > 80% one side, dark 10 s), trend protection on the reference, and XEMM-style cancel when net edge leaves a band; (5) inventory via size first (Hummingbot 0-2x multipliers, sfmm size skew), then pull the adding side at a cap; (6) queue awareness: on a 1-cent book quote at the touch but back off one tick when your queue is thin and skew is against you (hftbacktest CRVUSDT rule), and measure fill probability by queue state (30% vs > 90% in the Binance paper); (7) do not use OFI/CVD as a predictive pull signal (contemporaneous R^2 0.24 vs predictive 0.0004). Kalshi rebates/rewards were already judged NO-GO by the owner, so rebate-driven profits in the hftbacktest tutorials do not transfer. Red flags seen and excluded: retrovaliks/polymarket-btc-5min-trading-bot (98.8% win-rate claim, 15%/week pooled-capital offer, proof only on a call), Benjam1nCup bot (profitable version private, asks for private key), olaxbt/ai-market-maker (not an MM, backtest only), chudi.dev 5-minute latency bot (23 trades, no numbers, $49 kit). A repo exposed a secret. Pure Kalshi-only repos (e.g. rodlaf/KalshiMarketMaker) were skipped per the sweep rule; the Bartlett-O'Hara Kalshi paper is included as data, not as a bot. No repos were cloned (page fetches and Polymarket's public data API only), so nothing to delete; working files are under /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/geniuses/work/ (profile.html, closed_*.json, open_*.json, sumpnl.py, sum2.py). No credentials were collected or used; nothing was written to /home/user/Claude."
}


---
## result 4 

{
 "name": "Polymarket profile @1kto1m (wallet 0xa1d57d329227c75b12b09f927fb3d6d6ef8f1343) plus the dev.to 'lkto1m' bot series",
 "final_grade": "Split: A for the wallet's profit (real and reproducible from public APIs, but the headline is PRE-FEE: $49,601 gross becomes about $32,720 net after $19,338 taker fees and $2,485 rebates). D for the method and code: the dev.to posts do not describe this wallet, and all four linked repos are gone and were never archived.",
 "period": "May 2, 2026 (first fill 2:42 AM PT) to Oct 6, 2026 (last fill 4:13 PM PT); 126 active days; last day with a P&L move over $50 was Sep 27, 2026",
 "pnl_usd": 32720,
 "trades": 14559,
 "real_method": "Fast in-and-out scalping of Polymarket \"Bitcoin Up or Down\" 15-minute markets, mostly entered by TAKING (81% of buys paid a taker fee) in the middle of the candle, not the first 90 seconds, at a median buy price of 38-46 cents (not a 72c floor), then exiting within a median 88 seconds (p25 39 s, p75 202 s) by selling back (72% of markets were sold out before resolution; only 462 of 2,023 markets went to redemption; median sell-minus-buy gap +2.3c per share, positive in 57.5% of round trips). After fees: BTC 15-min markets +$19.0k (827 markets), BTC 5-min +$2.1k, BTC hourly +$1.7k, S&P/SPY open-up-or-down +$2.4k, one-off bets +$3.9k (largest: MicroStrategy-sells-Bitcoin +$1,211), other-coin up/down +$1.1k; rebates +$2.5k; liquidity REWARD only $106. Not airdrops, not one lucky bet (top-10 market wins = $7.9k of $90k gross wins), not visibly wash trading (both outcomes bought in only 9.4% of markets). Capital needed was tiny: the running cash position never went below -$740 (May 3), so the account was self-funding from about a $1k start.",
 "verdict": "PROVEN that the wallet made money; REFUTED that the posted method made it, and the headline number is overstated by fees. Primary data: 15,227 unique activity rows pulled from data-api.polymarket.com (14,559 fills: 6,194 buys / 8,365 sells, $940k volume, mean fill $64.60, 2,023 markets, 467 redemptions, 83 maker-rebate and 83 taker-rebate payouts). Summing fills at size x price gives +$49,573, which matches Polymarket's PnL API (+$49,601) to within $28, proving the displayed P&L ignores fees; summing the actual USDC that moved (usdcSize, which includes the fee of about 7% x p x (1-p) per share, i.e. 1.75c per share at 50c) gives +$30,235, plus $2,485 rebates/rewards = about +$32,720 net. All 286 remaining positions are worthless losers (sum cost $22,230), nothing is open or unredeemed, so this is the final realized number. Monthly net after fees (Pacific, by cash date): May +$14,902, Jun +$4,190, Jul +$7,268, Aug +$6,006, Sep +$348, Oct +$6; fills per active day fell 181 -> 100 -> 148 -> 80 -> 12. Max drawdown: $2,663 on Polymarket's pre-fee curve (Jun 4 to Jun 8); about $4,328 on the after-fee cash curve (Jul 18 to Jul 30). Worst day -$2,637 (Jun 5, a $2,707 loss on 'Will SPY hit LOW $740 week of June 1'); best day +$2,402. Win rate 56% of markets (1,135 wins / 885 losses), mean +$16 per market, +$2.25 per fill; daily mean/stdev 0.34. The strategy has effectively stopped: 2 fills in October. Posts vs wallet: the dev.to series (9 posts Jun 16 to Jul 10, 2026 by 'lkto1m', a lookalike of the Polymarket handle '1kto1m' with an L for the 1; profile bio 'Quant & Algo trading' linking polymarket.com/@1kto1m and GitHub 'adeIane') claims 11,717 trades, 77% win rate, average entry 75c, $292 net, 78 trades/day, a bot running since at least Feb 10, 2026, XRP = 44% of positions, BNB 19%, DOGE tracked, and 'positions stuck over 48h'. The wallet began May 2, 2026, is 95% Bitcoin by volume, buys at a median 38-46c, wins 56%, netted $32.7k, and lost $106 on other coins. None of the posts' rules show up in the fills: only 96 of 8,729 15-min fills were in the first 90 s; 294 15-min buys and 504 5-min buys happened inside the 'forbidden' last 90 s; 81% of buys were taker. The posts rotate four GitHub repos under four different owners (Eixen30, 1kto1m, MalcolmMcGough, Duclos76), two posts are verbatim duplicates, and the same article is cross-posted on Medium under '@adeianer'; none of the repos exist in the Wayback Machine or Software Heritage. This is a content-farm pattern riding on a real trader's public profile; treat the posts' rules as unsupported, not as 'portable hypotheses'. For the owner's Kalshi 15-min BTC desk: (1) discount any Polymarket leaderboard P&L by fees before admiring it; (2) the only thing this wallet proves is that taker-in/quick-out BTC scalping worked on Polymarket in May 2026 and faded to nothing by September, the same style the owner's lab 7 already found no edge for on Kalshi; (3) nothing here is reusable code, and the described timing/price rules have zero evidence behind them. On-chain deposit/withdrawal totals could not be read from this sandbox (Blockscout, Polygonscan, Alchemy demo, Routescan and public RPC log ranges all blocked or capped), so no ROI percentage is given; the cash-curve bound (never more than about $740 needed) is the stand-in."
}


---
## result 5 

{
 "name": "polymm (kachence) / Polymarket @b00k13 (proxy wallet 0x1c5575dc20e4ea54d1bb09ccda72ccf8a3b684ce) - sports/esports maker + hedge arbitrage",
 "final_grade": "A (confirmed, small scale). On-chain: $2,603.33 deposited in total, $7,250.00 withdrawn, $1,127.11 still inside (1,042.46 pUSD cash + $84.65 of open positions) = +$5,773.78 real profit. Polymarket's leaderboard says +$5,785.13, Polymarket's PnL curve says +$6,025.97 (its marks run about $250 rich), my rebuild from every fill and redemption says +$5,830 before fees. All four agree within 4%. The author's blog figure for Jan 6-Apr 28 (+$4,973.06 on 3,858 bets, 2,785 markets, $95,830 volume) checks out: I get +$5,031.76 on 3,859 legs, 2,785 markets, $95,746 volume, and the PnL curve read +$4,961 on May 1.",
 "real_method": "Exactly what was claimed, no tricks: 11,570 buys vs only 68 sells (99.4% buy-and-hold-to-resolution, redeemed at $1 or $0), every buy a 10-share-ish limit bid (median leg $6.10, mean $18.81). Both sides of the same match were bought in 1,537 of 5,143 markets; in Jan-Apr those 1,013 hedged pairs locked +$7,637 while the 1,772 one-sided legs lost -$2,470 and 176 cancelled matches (refunded at 50c) cost -$135. Esports carried it: esports legs net about +$5,900 over the whole run, everything else about -$150. Not one lucky bet: biggest single win $267.75, top-10 wins total $1,802 of $23,730 gross wins; 2,940 winning legs vs 3,755 losing (43.8% leg win rate, as expected for hedged pairs). Not rewards or airdrops: REWARD $1.64, maker rebates $36.91, taker rebates $11.63, zero splits/merges/conversions. Not wash trading or hidden funding: the only money that ever came in from outside was $1,803.57 in Jan 6-20, 2026 (eight transfers from plain wallets) plus $799.76 in Jul 28-Aug 7, 2026 (three pUSD mints); all profit arrived as redemptions from Polymarket's ConditionalTokens contract. Fees were near zero in Jan-Apr (pre-fee era) and about $72-$230 total in Jun-Oct. The three largest outlays ($4,579 Man City O/U, $3,110 Knicks spread, $1,017 Brewers) were the bugs the blog admits to and were sold back for -$96, -$243 (the biggest loss) and -$84.",
 "verdict": "CONFIRMED A, but read the size and the decay. Period: first fill Jan 6, 2026 8:59 AM PT, last fill Oct 13, 2026 8:13 AM PT. Main bot run Jan 6-Apr 28, 2026: +$5,032 (my rebuild) on $95,746 of buys = 5.3% of volume, starting from $1,804 of deposits, with cash in the wallet peaking at $5,069 (Mar 14) and cost-at-risk peaking at $5,599 (Mar 17). Monthly (Polymarket curve): Jan +$1,964, Feb +$2,603, Mar +$270, Apr +$133, May-Jun flat, Jul +$627, Aug +$42, Sep +$219, Oct 1-14 +$144. Max drawdown $732 (hourly $766): peak $5,514.63 on Mar 5-6 to $4,782.45 on Mar 27-28, 2026, about 13% of equity. The restart (author's unpublished Rust rewrite) Jun-Oct 13, 2026 made only +$762 cash on $31,680 of buys (2.4%; the curve shows +$1,065 May 1 to Oct 14), with my resolution-month split showing Aug 2026 negative (-$832). Fill rate fell 37.4% (Jan) to 1.0% (Apr) per the author, and the Jan-Apr edge did not come back at the old rate. Trade counts: 11,638 fills (7,699 Jan-Apr, 3,939 Jun-Oct) across 6,774 position legs in 5,143 markets. Independent confirmation: Hacker News Show HN Jul 21, 2026 (5 points, 3 comments) and the blog post Jun 9, 2026 (11 points, 5 comments); Polymarket leaderboard maps the wallet to name b00k13 and the trade records carry the author's bio pointing at kacho.io and polymm. For the owner: this is a real, honest, third-party-verifiable +$5.8k, made by a maker-side sportsbook-fair-value bot on esports moneylines with a 7% edge gate and an immediate opposite-side hedge; it is also a $2.6k-capital hobby run whose edge faded within three months once faster bots sat a cent ahead, and whose unhedged legs lost money because the odds feed was up to 30 minutes stale. It does not transfer to 15-minute Bitcoin markets (no external fair price to lean on) and the owner's rule 2026-10-10a bans real money on sports. Two technical notes for anyone re-checking: Polymarket's data API returns short pages mid-stream, so stop only on an empty page (my first pull lost 413 redemptions and showed a fake -$8.7k); and since Apr 12, 2026 this wallet's collateral is Polymarket USD (pUSD, 0xc011a7e1...), so USDC-only chain queries miss everything after April. No credentials were seen or recorded; the repo clone was read as text and deleted. Working files: /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/geniuses/work/b00k13/ (pull3.py, reconcile.py, split.py, chain_pull2.py, pusd_pull.py, chain_combined.py) and data in /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/geniuses/data/b00k13/.",
 "pnl_usd": 5773.78,
 "trades": 11638,
 "period": "Jan 6, 2026 - Oct 13, 2026 (Pacific). Main run Jan 6-Apr 28, 2026; small-size restart Jun-Oct 13, 2026."
}


---
## result 6 

{
 "name": "gopfan2 (Polymarket wallet 0xf2f6af4f27ec2dcf4072095ab804016e14cd5817) + Simmer/openclaw \"polymarket-weather-trader\" replica",
 "final_grade": "A confirmed for the wallet's profit; D for the replica (no results); the claimed METHOD is refuted - gopfan2 is a political-favorites bettor, not a daily-temperature trader",
 "period": "Aug 20, 2024 7:51 PM PT (first fill) to Oct 13, 2026 5:50 PM PT (last fill); 784 days, 722 active days",
 "pnl_usd": 1664698,
 "trades": 79627,
 "real_method": "Hold-to-resolution betting on world politics (80% of profit), heavily in favorites priced 0.70-0.90, plus monthly/annual GLOBAL temperature-anomaly markets (16%) and \"will BTC/ETH dip to X\" No-side bets (18%); sports lost him $290k. Zero trades in daily city high-temperature bucket markets, which is what the replica trades.",
 "verdict": "PROFIT: CONFIRMED (grade A). Polymarket's own PnL API shows +$1,664,698 all-time at Oct 13, 2026 5 PM PT. I rebuilt it two independent ways from the full public trade log (82,858 activity rows, 79,627 fills, 2,048 markets, 1,772 closed + 666 open positions): (1) closed-position realized P&L +$4,372,189 plus open-position cash P&L -$2,646,431 (602 losing positions that resolved to zero, $2.72M cost, never redeemed) = +$1,725,758; (2) pure cash flow: $32.03M in (sells $10.74M, redemptions $17.18M, merges $4.08M, rewards/yield/rebates/referral $29k) minus $30.67M out (buys $26.69M, splits $3.99M) = +$1,356,977 realized cash, plus $256,401 marked value of 64 live positions = $1,613,378. All three agree within 7%. Not luck: 1,210 winning vs 502 losing closed positions; biggest single win (Mark Carney Yes, +$203k) is 3.4% of gross wins, top-10 wins 17%. Not rewards: non-trading income $29,124 = 1.7% of profit. Not wash trading: 53% of exit dollars came from redeeming at resolution. Fees negligible ($1,336 of entry fees visible). On-chain the address is a 124-byte contract (Polymarket proxy wallet); USDC balances are 0 (fully deployed; Polymarket moved to pUSD Apr 28, 2026). Deposit/withdrawal history not pulled (public RPCs cap log scans at 10,000 blocks), but the deepest outside-capital need in the trade log was about -$167k in Aug 2024 and net cash flow turned positive (+$82k) by Jan 1, 2025, so after ~4 months he was playing on house money. Average $2,100/day, roughly $64k/month. Max drawdown -$369,065 (-29%) from $1,283,093 on Nov 7, 2025 to $914,028 on Jan 4, 2026; earlier -$244k (-30%) in May 2025, driven by one bet (George Simion to win Romania, -$163k on May 18, 2025). Worst mark-to-market day -$232k Jul 19, 2026; best +$134k Jul 15, 2026.\n\nMETHOD: REFUTED as described. Where the $1.73M came from: politics/geopolitics $1,380k (1,111 positions, $18.7M staked, 7.4% ROI, 50% win rate); climate/nature $338k, of which $271k from 158 positions on monthly and annual GLOBAL temperature-anomaly markets (\"global temperature increase between 1.28-1.30C for 2024\", \"hottest year on record\") at ~16% ROI; crypto price-threshold markets $306k (188 positions, 79% win rate, mostly No at 0.70-0.90 on \"will ETH dip to $X\"); sports -$290k (602 positions, 48% win rate); other -$9k. Daily city temperature buckets: 0 of 79,627 fills; one tiny position (\"70F in NYC in December?\"). The 244 \"weather\" fills were hurricane-season markets and NHL Carolina Hurricanes games. By entry price: 0.70-0.90 made $946k on $7.0M staked (13.5% ROI, 81% win) - his real engine; 0.90-1.00 made $257k on $11.1M (2.3% ROI, 86% win); 0.30-0.50 made $300k (10.6%); longshots under 0.30 lost $225k. 64% of his buy dollars went in at 0.70 or higher. Trading hours cluster 6-11 AM PT (European afternoon).\n\nSTILL WORKS? Weaker than claimed. Since Jul 1, 2026: +$116k ($1,548,704 to $1,664,698). Realized +$269k on 41 closed positions, but $141k of it is ONE bet (United Russia most seats, Yes at 0.77, $644k staked, resolved Sep 30, 2026). Activity collapsed from 7,289 fills in Apr 2026 to 366 in Jul and 544 in Oct 2026.\n\nREPLICA (Simmer/openclaw skill): grade D. The page says \"Framework, not a production trading system\", \"Inspired by gopfan2\" with no evidence; its \"Backtest gate\" section is a KEEP/KILL rubric and states \"90-day real-capital P&L on Simmer is the lock\" - a to-do, not a result; no backtest or live P&L numbers anywhere. Default $2 cap, buy below 0.15, sell above 0.45. Live mode requires WALLET_PRIVATE_KEY in an env var (read only, never run). The \"$1,000 to $24,000\" blog: no wallet, no independent confirmation, only sales pages found (a $250/week \"PolyLabs weather bot\") - grade C at best.\n\nFOR THE OWNER: gopfan2's record does NOT justify a NOAA-vs-bucket bot on Kalshi daily highs; that remains an untested hypothesis on its own merits. What his record does support: (1) political favorites at 0.70-0.90 held to resolution beat his 0.97-0.99 \"near-certain grind\" bucket by 6x on ROI (13.5% vs 2.3%); (2) the real \"weather\" edge was monthly global temperature-anomaly ladders (resolution from published climate datasets that daily reanalysis forecasts well) - Kalshi lists annual hottest-year markets but not the monthly ladder; (3) sports lost money even for a $1.7M winner. Data files: /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/geniuses/work/{pnl_all,closed,positions,activity,rows_cat}.json. No repos were cloned; nothing written to /home/user/Claude."
}


---
## result 7 

{
 "name": "gabagool22 (wallet 0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d) - both-sides maker on Polymarket BTC/ETH Up-or-Down 5m/15m/hourly, Oct 29 2025 - Feb 20 2026",
 "final_grade": "A confirmed for the wallet (profit verified from primary data: Polymarket PnL API, 57,200 closed-position rows, 501,615 sampled fills, on-chain receipts, balances, deposit and final withdrawal). D unchanged for the replica repo strongca22-cpu/gabagool (no results, different method).",
 "real_method": "Confirmed with four corrections. The wallet bought BOTH outcomes of every BTC and ETH Up-or-Down market (28,581 of 28,619 markets two-sided) in small clips (mean $5.29, median $4.09, max $30.72), never sold (501,615 sampled fills, 100% BUY), and got the pair for less than $1.00 in 80% of markets (avgPrice Up + avgPrice Down: median 98.5c, p10 95.5c, p90 101.2c). Decomposition: $840k of profit came from matched pairs bought under $1, the unmatched directional leftovers LOST $27k, so the money is the pair discount, not direction. Corrections: (1) it did not wait for resolution; it MERGED Up+Down back into $1 USDC (merges per hour roughly equal buys per hour, redeems only $60-$415/h; median first-fill-to-first-merge 18 min, p90 46 min; 24% of merges before the window even closed), so capital recycled every ~20 minutes. (2) Not a pure resting maker: by fill count it was 89% maker in Oct, 81% Nov, 83% Dec, then 94% Jan and 98% Feb after taker fees arrived (taker share by dollars 12%, 21%, 22%, 9%, 3%). The data-api takerOnly flag was checked against on-chain OrderFilled roles: 14 of 14 agree. (3) $50,511 of the $868,862 (5.8%) is Polymarket maker rebates (44 daily payments, Jan 7 to Feb 20 2026 PT), not trading. (4) Fills sit across the whole 0-100c range (mode 40-60c), spread over the window (first fill median at 3% of the window, last at 86%), not the replica's 'buy if under 48c' rule. Capital was tiny: deposit $5 + $980.71 on Oct 29 2025 01:39/01:45 PT; cash balance in the wallet Dec 1 $3,308, Jan 1 $9,626, Feb 1 $16,046, peak seen $16,832 (Feb 17); inventory at cost peaked ~$2.8k on day 1 and ~$11.6k on the last day. Profits were swept out continuously; final sweep $15,145.66 on Feb 20 2026 14:04 PT to an external address; balance $0.00 since. Counterparties diverse (30 distinct takers hit its resting orders in 33 sampled maker fills), so no wash-trade pattern; no airdrops; referral rewards only $1,805 (Mar-Jun 2026, not in the PnL figure).",
 "verdict": "CONFIRMED, grade A. Numbers (Pacific time): first fill Oct 29 2025 02:03 PT, last fill Feb 20 2026 01:06 PT, 114 days, PnL flat since. Realized PnL $868,862.50 (Polymarket PnL API); independent reconstruction from closed positions ($813,200) + leftover dust positions ($5,674) + maker rebates ($50,511) = $869,385, within $523 (0.06%). 28,620 markets traded, 144.7M shares bought for $71.45M, about 13 million fills (estimate from sampled hours; fills per hour grew from 1,900 in Oct to 4,800 in Jan). Month-end PnL: Oct $8.5k, Nov $144.6k, Dec $451.3k, Jan $723.8k, Feb $868.9k. Mean $7,490/day; best day $17,340 (Jan 5); exactly ONE losing day in 116 (-$100, Feb 18); max hourly drawdown $1,645 (Feb 17 12:00-22:00 PT); worst single market -$300, best +$360; 81.3% of markets profitable, median market +$20.81; top 1% of markets = 7.3% of profit (no lucky bet). Where it came from: BTC 15m $423k, ETH 15m $162k, BTC hourly $140k, ETH hourly $60k, BTC 5m $29k, ETH 5m -$41, SOL/XRP tests ~0, rebates $50.5k. Edge per dollar bought decayed every month: 2.04c Oct, 1.89c Nov, 1.60c Dec, 0.92c Jan (taker fees from Jan 6; first rebate paid to this wallet Jan 7 16:17 PT), 0.66c Feb; the operator shut down at the PnL peak and swept the cash the same day, a deliberate stop, not a blow-up. Return on capital is the real story: under $1k deposited, never more than roughly $30k at work, because pairs were merged back to cash within ~20 minutes. Press 'turned $300 into $400k' (Finbold, Jan 9 2026) is profile 0x8dxd making directional BTC/ETH/SOL/XRP bets, not this wallet. Replica repo strongca22-cpu/gabagool (1.5 MB, last commit Jan 27 2026): thresholds 0.48/0.48, max pair cost 0.97, min margin 0.02, max 3 concurrent, README says 'guaranteed profit' with a 7.5%-per-pair example and has zero backtest or live results; it is a taker-style scanner and a 1.75c fee at 50c eats a 1-3c pair edge; my count-only scan also flagged possible credential strings (a repo may have exposed a secret; nothing read or recorded); clone deleted. For the owner: this is the existence proof for resting two-sided bids with sub-2c pair edge, but it needed zero maker fees, fast merge-to-cash, heavy taker flow hitting both sides, and it still lost two thirds of its per-dollar edge in four months as fees and competition arrived. On Kalshi a locked Yes+No pair only pays at window end (no merge), so turnover is slower, and the owner must check Kalshi's maker fee table before assuming the pair discount survives fees. Data and scripts: /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/geniuses/data (closed_positions.jsonl, activity_sample.jsonl, taker_sample.jsonl, pnl_max_1h.json, act_all_MAKER_REBATE.jsonl, balance_history.json, targeted_scan.json) and .../geniuses/work (analyze_closed.py, analyze_activity.py, verify_taker_semantics.py, balance_history.py, targeted_scan.py).",
 "pnl_usd": 868862.5,
 "trades": 13000000,
 "period": "2025-10-29 02:03 PT to 2026-02-20 01:06 PT (114 days); PnL flat since, wallet emptied 2026-02-20 14:04 PT"
}

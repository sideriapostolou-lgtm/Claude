# kalshi_public_bots_sweep (workflow wf_258389bb-ee8)



---
## result 0 

{
 "lane": "LANE 2: free, legitimate ways to read Pyth prices fast, plus other fast FX feeds (measured from the sandbox Tue Oct 13, 2026, 4:55-5:11 PM Pacific, a quiet FX hour right after the New York 5 PM close)",
 "items": [
  {
   "name": "Pyth Pro API (Hermes with key, or the Lazer websocket) - the official paid road",
   "url": "https://app.pyth.com/plans",
   "what": "Since Aug 26, 2026 (9:00 AM Pacific) every Pyth price call needs an API key. Plans on the official page: Free $0 = view-only in the Pyth Terminal, 10-second updates, NO API. Starter $500/mo = API key, up to 1-second updates, 'access to all crypto symbols' (crypto only). Pro from $2,500/mo = up to 1 ms. The Pyth blog lists Pro bundles: FX (G10 only) $2,500/mo, FX $5,000/mo, Crypto $2,500/mo, everything $10,000/mo. Lazer/Pro websocket: wss://pyth-lazer-0/1/2.dourolabs.app/v1/stream, channels real_time (1-50 ms), 50 ms, 200 ms, 1000 ms; 'no hard technical rate limits', limits set by your service agreement.",
   "evidence_grade": "A",
   "evidence": "Measured: hermes.pyth.network/v2/updates/price/latest -> HTTP 401 'unauthorized'; same on hermes-beta and pyth.dourolabs.app/hermes; SSE stream 401. Only the feed-list (/v2/price_feeds) still answers without a key. Plan text read from app.pyth.com/plans (pyth.network/pricing redirects there) and pyth.network/blog/the-pyth-core-upgrade. Docs say a 'free trial is included, no credit card' when you make a free Terminal account and press 'View your API key', but NO page states the trial length, update rate or whether it covers FX; a forum post shows trial keys get killed when the promo ends.",
   "risk_or_catch": "The $500 Starter does NOT include FX. EUR/USD by API is a Pro FX bundle: $2,500/mo minimum. Also the owner's note '1 s cap' applies to Starter; Pro FX is faster but $2,500+/mo, which is more than the whole Kalshi stake.",
   "worth_copying": "Only one legit free move: open a free Pyth Terminal account, take the trial key, and use it for a time-boxed measurement (record FX.EUR/USD at the fastest channel the trial allows next to TrueFX/Kraken for the few days it lasts). Do not build a live bot on it."
  },
  {
   "name": "Pythnet RPC / self-hosted Hermes (the old free back door)",
   "url": "https://docs.triton.one/chains/pythnet",
   "what": "Hermes used to be open source: run it against a Pythnet RPC plus a Wormhole spy and you had free sub-second Pyth prices. Pythnet (the Pyth app-chain) was shut down Sept 22, 2026 after the Core upgrade moved everything to Pyth Pro. Triton no longer offers pythnet.rpcpool.com or its hosted Hermes.",
   "evidence_grade": "A",
   "evidence": "Measured: POST pythnet.rpcpool.com getSlot -> HTTP 403 'Your IP or provider is blocked from this endpoint'; pythnet.rpc.pyth.network does not resolve. Triton's doc page says Pyth 'shut down Pyth Core (Pythnet)' on Sept 22, 2026. Hermes README (apps/hermes/server) says it 'requires a running instance of Pythnet and the Wormhole spy RPC'. Pyth's open-source 'beacon' repo (read as text) is only a high-availability Wormhole spy: it receives signed merkle ROOTS, not prices, so it cannot replace Pythnet.",
   "risk_or_catch": "Dead end. Any GitHub repo that promises free Pyth via Pythnet or Hermes-without-key is pre-Aug-2026 and no longer works.",
   "worth_copying": "nothing"
  },
  {
   "name": "Pyth price accounts on Solana mainnet (free public RPC, read on-chain)",
   "url": "https://docs.pyth.network/price-feeds/core/push-feeds/solana",
   "what": "Anyone can read the Pyth 'push oracle' accounts on Solana for free (getAccountInfo / accountSubscribe on api.mainnet-beta.solana.com). I computed the account addresses (PDA of shard id + feed id under program pythWSnswVUd12oZpeFP8e9CVaEqJg25g1Vtc2biRsT) and decoded them with a 90-line pure-Python script, no SDK.",
   "evidence_grade": "A",
   "evidence": "Measured Oct 13, 2026 ~5:04 PM Pacific: FX.EUR/USD shard 0 (Fu76Cham...) last updated Aug 24, 2026 6:29 AM Pacific (50 days stale, price 1.16706); shard 1 last Sept 28, 2026 4:53 AM Pacific. GBP/USD and USD/JPY equally stale. Crypto.BTC/USD and Crypto.EURC/USD (shard 0) ARE kept fresh by Pyth's sponsored pusher, but accountSubscribe over 120 s delivered only 2 notifications each (gap ~54 s), matching the docs' default sponsor schedule of '55 seconds heartbeat / 0.5% price deviation'; publish-time to my receipt lag was 1.3-1.6 s. The legacy push oracle (mapping AHtgzX45...) last updated Aug 29, 2024. Solana docs list 61 sponsored feeds, none FX.",
   "risk_or_catch": "FX is not pushed on Solana at all; crypto is pushed about once a minute. Useless for a half-second edge. EURC/USD (a euro stablecoin, ~1 pip from EUR/USD tonight) is the only free on-chain euro-ish Pyth number.",
   "worth_copying": "The PDA + decode script (work/solana_pyth_read.py in the scratchpad) if you ever want a free once-a-minute sanity check of a Pyth crypto price without a key."
  },
  {
   "name": "Pyth Benchmarks / history API",
   "url": "https://benchmarks.pyth.network",
   "what": "Historical Pyth prices and a TradingView-style candle shim. Used to be free.",
   "evidence_grade": "A",
   "evidence": "Measured: /v1/updates/price/{timestamp} -> HTTP 401 'unauthorized'; /v1/shims/tradingview/history -> 404 for FX.EUR/USD and Crypto.BTC/USD; only /v1/price_feeds metadata still open. Pyth dev forum: Pro History API endpoints require a key since July 24, 2026.",
   "risk_or_catch": "No free Pyth FX history anywhere now (Terminal free tier shows 30 days at 'limited resolution', view only).",
   "worth_copying": "nothing"
  },
  {
   "name": "Kalshi's own public API as a free Pyth sampler (strikes and settlements)",
   "url": "https://assets.kalshi.com/contract_terms/FXEURUSD.pdf",
   "what": "Kalshi settles its 15-minute and hourly FX markets (KXEURUSD15M, KXGBPUSD15M, KXUSDJPY15M, KXUSDCAD15M, KXAUDUSD15M, KXEURUSDAH, ...) on 'Pyth Network' (settlement_sources field; contract terms: 'Source Agency is Pyth Network ... feed FX.EUR/USD ... Expiration Value is the value of the Underlying at that exact date and time'). The floor_strike of every 15-minute market IS Pyth's EUR/USD print at the window open, published free, no key, within about a minute. That is 96 exact Pyth FX samples per day for free.",
   "evidence_grade": "A",
   "evidence": "Measured: GET /trade-api/v2/markets/KXEURUSD15M-26OCT132015-30 -> floor_strike 1.12012 = Pyth EUR/USD at 00:00:00Z (5:00:00 PM Pacific). My TrueFX quote at 5:00:00.4 PM was 1.12010/1.12013 (mid 1.120115, within 0.05 pip of Pyth). Kraken EUR/USD at the same instant was 1.11991/1.11993: 2 pips BELOW Pyth. Previous strikes: 1.12008 (4:45 PM), 1.11982 (4:30), 1.11977 (4:15). Note: the BTC market (KXBTC15M) settles on CF Benchmarks, not Pyth; EUR/USD hourly 'KXEURUSDH' settles on ICE.",
   "risk_or_catch": "One sample per 15 minutes, so it cannot show sub-second timing by itself; you need many days of samples and a fast free feed recorded at 100 ms around each boundary. Kalshi can change sources (contract terms allow a successor feed).",
   "worth_copying": "The whole 'half-second head start' test can be built on this for $0: record TrueFX (and Kraken, OANDA) at 100 ms around every :00/:15/:30/:45 boundary, then for each boundary find the time offset that best matches the Pyth strike. 300-500 boundaries (4-5 days) resolve lead/lag to ~0.1-0.2 s. Also use settlement results (yes/no) as a second Pyth sample at close."
  },
  {
   "name": "TrueFX (already in use) - measured cadence",
   "url": "https://webrates.truefx.com/rates/connect.html?f=csv&c=EUR/USD",
   "what": "Free bank-quote aggregate (Integral), unauthenticated CSV endpoint with timestamps in ms. Polled at 5 per second for 10 minutes (2,982 requests, 0 errors).",
   "evidence_grade": "A",
   "evidence": "Measured 4:56-5:06 PM Pacific (quiet hour): EUR/USD 153 distinct quotes in 600 s = 0.26 updates/s, median gap 2.2 s, 10th pct 0.18 s, 90th pct 11.1 s, longest gap 22.9 s. GBP/USD 0.42/s (median gap 0.54 s). USD/JPY 0.41/s (longest gap 36 s). HTTP round trip median 60 ms, p90 84 ms. TrueFX's own timestamp was only ~18 ms old when first seen (fresh stamps; my clock about 90 ms off). TrueFX mid matched Kalshi's Pyth strike at 5:00:00 PM to 0.05 pip.",
   "risk_or_catch": "In quiet hours it goes 10-23 s without a new quote, so 'latest TrueFX' can be very stale exactly when Kalshi's boundary hits. Cadence is surely higher in London/New York hours but I did not measure that. Terms: personal, non-redistribution; a registered (free) account unlocks more pairs.",
   "worth_copying": "Keep it as the reference feed for the test (it tracks Pyth closest). Log the TrueFX timestamp, not just arrival, and treat any quote older than ~1 s as 'unknown' at the boundary."
  },
  {
   "name": "Kraken EUR/USD spot websocket (fiat pair, US-legal, free, no key)",
   "url": "https://docs.kraken.com/api/docs/websocket-v2/ticker",
   "what": "Kraken lists a real EUR/USD fiat pair (ZEURZUSD, ~$23M/day volume). Public websocket v2 ticker with event_trigger=bbo gives every best-bid/ask change. Spread tonight 0.2 pip (1.11991/1.11993).",
   "evidence_grade": "A",
   "evidence": "Measured 300 s: 1,291 updates = 4.3 per second, median gap 12 ms, 90th pct 0.76 s, longest gap 7.9 s. Lead/lag vs TrueFX over the 297 s overlap: correlation of 1-second changes peaks at 0 s shift (0.38) and is symmetric to +/-0.2 s, so Kraken and TrueFX move together within 0.2 s; neither leads. But at the 5:00:00 PM boundary Kraken's mid sat 2 pips below the Pyth strike while TrueFX matched it.",
   "risk_or_catch": "It is a crypto-exchange order book, not interbank: level can drift 1-2 pips from Pyth/TrueFX in quiet hours, and 2 pips is the whole game in a 15-minute FX market. Fast but not the same price.",
   "worth_copying": "Use as the sub-second 'movement' detector (did EUR/USD just move?) alongside TrueFX for the level. The 60-line capture script (work/kraken_ws_cadence.py) is reusable."
  },
  {
   "name": "Bitstamp EUR/USD websocket",
   "url": "https://www.bitstamp.net/websocket/v2/",
   "what": "Another US-accessible exchange with a EUR/USD fiat pair; public order-book websocket.",
   "evidence_grade": "A",
   "evidence": "Measured 240 s: 313 book messages but only 23 best-bid/ask changes = 0.1 per second, median gap 3.5 s, longest 79 s; server-to-me lag 24 ms. Too thin.",
   "risk_or_catch": "Illiquid; stale level most of the time.",
   "worth_copying": "nothing"
  },
  {
   "name": "OANDA fxTrade Practice streaming (v20 API, free demo)",
   "url": "https://developer.oanda.com/rest-live-v20/pricing-ep/",
   "what": "Free US demo account (OANDA Corporation accepts US residents; signup asks country of residence, email and 'required details'; no deposit). Token: log in to the OANDA Hub, My Services -> Manage API Access, accept the API license. Streaming endpoint GET /v3/accounts/{id}/pricing/stream on stream-fxpractice.oanda.com.",
   "evidence_grade": "B",
   "evidence": "OANDA docs: the stream sends 'at most 4 prices per second (every 250 milliseconds)' per instrument, only the price in effect at the end of each 250 ms window, heartbeats every 5 s. Community guides confirm a demo account gives full API access for free; expiry not stated for US (Japan expires demos after 30 days). Not measured here (needs an account).",
   "risk_or_catch": "Capped at 4 updates/s with 250 ms bucketing, so it can never give a half-second head start by itself; OANDA's price is its own dealer quote, not Pyth's. Terms forbid redistribution.",
   "worth_copying": "Worth adding as a third free feed in the boundary test (it is a dealer price like Pyth's publishers) once the owner opens a demo and generates a token themselves."
  },
  {
   "name": "Binance / Bybit EURUSDT perps (and OKX, Bitget)",
   "url": "https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol=EURUSDT",
   "what": "FX-perp proxies suggested in the task.",
   "evidence_grade": "A",
   "evidence": "Measured from this US sandbox: Binance futures and spot -> HTTP 451 'restricted location'; Bybit -> HTTP 403 CloudFront country block; Binance.US has no EURUSDT; OKX EUR-USDT-SWAP and Bitget EURUSDT do not exist. Kraken Futures lists no EUR pair.",
   "risk_or_catch": "Not legitimately reachable for a US resident; using a VPN would breach their terms. Dead option for this owner.",
   "worth_copying": "nothing"
  },
  {
   "name": "Massive (formerly Polygon.io) Currencies",
   "url": "https://massive.com/pricing?product=currencies",
   "what": "Currencies Basic $0: end-of-day only, 5 calls/min, 2 years history, no websocket. Currencies Starter $49/mo: real-time, websockets, unlimited calls.",
   "evidence_grade": "B",
   "evidence": "Read from massive.com pricing page (Currencies tab). Not measured (no key).",
   "risk_or_catch": "Free tier is useless for live prices; $49/mo for a feed that is itself an aggregate of retail ECNs, with no evidence it beats TrueFX.",
   "worth_copying": "nothing for free; cheapest paid fallback if a second real-time FX stream is ever wanted."
  },
  {
   "name": "Twelve Data",
   "url": "https://twelvedata.com/pricing",
   "what": "Basic (free): 8 credits/min, 800/day, forex quotes advertised as real-time; websocket only as a trial (1 connection, 8 symbols, duration unstated). Full websocket needs Pro ($229/mo monthly).",
   "evidence_grade": "B",
   "evidence": "Pricing page and support article read; not measured.",
   "risk_or_catch": "8 REST calls a minute = one quote every 7.5 s. Not a speed tool.",
   "worth_copying": "nothing"
  },
  {
   "name": "Finnhub free key (websocket forex via OANDA symbols)",
   "url": "https://finnhub.io/docs/api/websocket-trades",
   "what": "wss://ws.finnhub.io?token=... streams 'US Full SIP, LSE, Forex and Crypto' trades; forex symbol format OANDA:EUR_USD; hard cap 30 API calls/s on every plan.",
   "evidence_grade": "C",
   "evidence": "Confirmed in the docs HTML (endpoint, symbol format, 30/s cap). Free-tier websocket limits and whether forex streaming is included for free are only third-party claims (about 60 calls/min, personal use); pricing page is JS-only and could not be read. Not measured.",
   "risk_or_catch": "It is a relay of OANDA quotes, so no faster than OANDA itself; free key is personal/non-commercial.",
   "worth_copying": "Only if OANDA's own demo is a hassle: sign up free and test whether forex streams on the free key."
  },
  {
   "name": "Dukascopy free feeds",
   "url": "https://www.dukascopy.com/wiki/en/development/data-export/",
   "what": "The widget JSON endpoint freeserv.dukascopy.com; historical tick archive; FIX API.",
   "evidence_grade": "A",
   "evidence": "Measured: freeserv -> HTTP 429 'Too Many Requests (Bot blocked)' on the first request. Data-export wiki: history lives in a requester-pays AWS S3 bucket (about $0.06 for EUR/USD, needs AWS credentials); FIX 4.4 live feed needs a Dukascopy account.",
   "risk_or_catch": "No live free API; scraping the widget is explicitly blocked.",
   "worth_copying": "nothing"
  },
  {
   "name": "Open-source Pyth clients (hermes-client TS, pyth-hermes Python, beacon, pyth-client-py)",
   "url": "https://github.com/robertruben98/pyth-hermes",
   "what": "All public clients are thin wrappers: @pythnetwork/hermes-client and the community pyth-hermes Python package call hermes.pyth.network (now 401 without 'Authorization: Bearer <key>'; the Python client already has an api_key option and notes the old free limit of 10 requests per 10 s). pyth-client-py reads the legacy Solana oracle (dead since Aug 29, 2024). beacon is a Wormhole spy (roots only).",
   "evidence_grade": "B",
   "evidence": "Read as text from shallow clones (deleted afterwards) and the hermes-client README. No repo gets Pyth data without a key or dead infrastructure.",
   "risk_or_catch": "Nothing to copy that gives free fast Pyth. The repo sweep found no exposed credentials in these three; none were sought or used.",
   "worth_copying": "nothing"
  }
 ],
 "notes": "PLAIN SUMMARY FOR THE OWNER (Pacific time). Grades here: A = I measured it live from the sandbox with code; B = read on the official pages; C = third-party claims only.\n\n1) There is no free, legitimate way to read Pyth FX prices fast any more. Since Aug 26, 2026 (9 AM Pacific) Hermes answers 401 without a key; Pythnet (the free back door) was switched off Sept 22, 2026; Benchmarks needs a key; the Solana on-chain EUR/USD account has not been updated since Aug 24 (shard 0) / Sept 28 (shard 1). The free Pyth tier is view-only at 10-second updates.\n2) The $500/mo Starter plan is crypto-only ('access to all crypto symbols', up to 1 s). EUR/USD by API is a Pro bundle: FX G10 $2,500/mo (FX full $5,000/mo). So the 'buy the Pyth key' decision is really a $2,500/mo decision, not $500.\n3) Kalshi settles its 15-minute FX markets on Pyth (KXEURUSD15M, KXGBPUSD15M, KXUSDJPY15M, KXUSDCAD15M, KXAUDUSD15M; also hourly KXEURUSDAH etc.). Each market's floor_strike is Pyth's exact EUR/USD print at the window open, free in the public API. Tonight at 5:00:00 PM the strike was 1.12012; TrueFX's quote at that second was 1.12010/1.12013 (match); Kraken was 1.11991/1.11993 (2 pips low).\n\nRANKED TABLE (feed | updates per second | lag vs TrueFX | cost | terms):\n#1 TrueFX unauthenticated CSV | 0.26/s EUR/USD, 0.42/s GBP/USD at 5 PM quiet hour (median gap 2.2 s, worst 23 s) | reference; timestamps fresh (~20 ms); matched Pyth to 0.05 pip | $0 | personal use, free account for more pairs.\n#2 Kraken EUR/USD websocket | 4.3/s (median gap 12 ms) | moves together with TrueFX within +/-0.2 s (corr peak 0.38 at 0 s); level can sit 1-2 pips off Pyth in quiet hours | $0, no key, US-legal | public API.\n#3 OANDA Practice stream | max 4/s, 250 ms buckets (docs) | not measured | $0 demo account + your own token | no redistribution.\n#4 Pyth Pro trial key via free Terminal account | up to real_time (1-50 ms) if the trial allows | n/a | $0 for an unstated trial period, then $2,500/mo for FX | use only for a time-boxed measurement.\n#5 Finnhub free key (OANDA relay) | unknown, 30 calls/s cap | not measured | $0 personal | unverified (grade C).\n#6 Pyth on Solana mainnet | ~1 update per 55 s for BTC/EURC, FX not updated at all | 1.3-1.6 s behind publish time | $0 | useless for speed.\n#7 Massive Currencies Starter $49/mo (real-time + websocket); free tier is end-of-day only.\n#8 Twelve Data free: one quote per 7.5 s; websocket needs $229/mo.\nDead: Binance/Bybit perps (geo-blocked HTTP 451/403 in the US), OKX/Bitget (no EUR perp), Bitstamp EUR/USD (0.1 updates/s), Dukascopy (bot-blocked), Pythnet/Hermes self-host (shut down), legacy Solana oracle (dead since Aug 2024), all open-source Pyth clients (need a key).\n\nRECOMMENDATION FOR THE 'HALF-SECOND HEAD START' TEST (cost $0, 4-5 days):\na) Record TrueFX (poll 5-10/s, keep its own timestamp) and Kraken EUR/USD websocket, both at 100 ms resolution, around every 15-minute boundary (:00 :15 :30 :45) for EUR/USD, GBP/USD, USD/JPY. Add OANDA practice if the owner opens a demo and makes a token.\nb) After each window, pull the new market's floor_strike from Kalshi's public API (that is Pyth's print at the boundary). For each boundary find the time offset where the feed's mid best equals the strike; the distribution of offsets over 300-500 boundaries is the lead/lag of the free feed vs Pyth, to about 0.1-0.2 s. If the best offset is around 0 or negative (feed matches Pyth only AFTER the boundary), there is no head start and the LIP idea stays NO-GO.\nc) In parallel, use the recorder's Kalshi order books: check whether Kalshi's EUR/USD book moves within 0.5 s of a Kraken/TrueFX move. If the book already moves first, nobody at retail-feed speed has an edge.\nd) Only if (b) shows the free feed leading Pyth by 0.5 s or more at Kalshi's settlement instants should the $2,500/mo Pro FX key even be discussed; a free Terminal trial key, used for a few days, can confirm sub-second alignment before paying anything.\ne) Honest expectation: Pyth's FX publishers are institutional market makers updating sub-second; TrueFX matched Pyth to 0.05 pip at the one boundary measured, so a retail free feed 'knowing' Pyth 0.5 s early is unlikely. The test is cheap, so run it before spending money.\n\nCAVEATS: all cadence numbers come from one quiet 10-minute window (4:56-5:06 PM Pacific, right after the 5 PM New York close); London/New York hours will be faster for TrueFX and probably Kraken. Scripts and raw tick files are in the scratchpad at /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/github_sweep/work/ (truefx_cadence.py, kraken_ws_cadence.py, bitstamp_ws_cadence.py, solana_pyth_read.py, solana_sub_cadence.py, solana_legacy_pyth.py, leadlag.py, *_ticks.csv, *_summary.json, fxeurusd_terms.pdf). Nothing was written to the repo; no credentials were encountered, collected or used; the three shallow clones were read as text only and are gone."
}


---
## result 1 

{
 "lane": "LANE 1 - public Kalshi trading bots (GitHub sweep, run Oct 13, 2026 about 4:55-5:08 PM Pacific)",
 "items": [
  {
   "name": "mirabilis-agent/lip-ledger (Mirabilis, an AI agent trading a real $20 Kalshi account)",
   "url": "https://github.com/mirabilis-agent/lip-ledger",
   "what": "Read-only exact model of Kalshi's Liquidity Incentive Program (LIP) plus a post-mortem of 9 days of real LIP market-making on a $20 account. 7 stars, 1 fork, MIT, last commit Oct 13, 2026.",
   "evidence_grade": "A (real money, but a tiny account over 8-9 days)",
   "evidence": "Account started $19.60 on Oct 2, 2026 and was $3.84 on Oct 10 (11:00 AM Pacific). Rewards received $20.30; trading losses from being filled -$36.06. Their payout model matched what Kalshi actually paid within 1-3% ($4.44 model vs $4.57 paid; $15.58 vs $15.73). Daily net value is published publicly. Cheap resting bids were filled only when the outcome was already decided (0 of 252 YES<=5c decision points ever won; 0/130 in daily rain markets). Sweeps hit in bursts of 200-600 contracts (p90 about 1,400, p99 about 6,000 in 10 seconds). A 'follower' bot adds 2-30k contracts within about 17 seconds of any side becoming counted and leaves at the first hit.",
   "risk_or_catch": "The reward side is real and predictable; the fill side eats it. The $1 per program per day floor wasted about half of their stints. Their own 1-3 second guard cancelled too late repeatedly (-$4.72, -$6.00 in 23 s). This matches our own LIP NO-GO.",
   "worth_copying": "The exact LIP scoring rules (reference price = first level where cumulative size reaches target/5; score = size x discount^ticks below reference; a second counts only if BOTH sides reach target; payout = pool x 0.5 x your share x counted fraction; $1 floor per program per day). The sweep-size statistics for any fill-risk model. The lesson to measure losses from account balance changes, not from the bot's own partial-fill counter (their loss stop never tripped on fully swept orders)."
  },
  {
   "name": "aurascoper/brti-edge",
   "url": "https://github.com/aurascoper/brti-edge",
   "what": "KXBTC15M research repo: fair value from spot and volatility (Gaussian, Student-t tested), BRTI-style 3-exchange index, a 30-hour order-book replay of a 'dumb two-sided maker at the touch', pre-registered hypotheses with pass gates. 0 stars, no license shown, last commit Sep 21, 2026; live trading paused since May 17, 2026 (shadow mode, orders off).",
   "evidence_grade": "B (live record of losses + replay with code; the only positive result is in-sample and not significant)",
   "evidence": "Live: 6 rounds, 285 filled trades, 51.2% win rate, -$32.99 (bankroll about $18). BRTI (Coinbase+Kraken+Bitstamp) matched Kalshi's settlement in 168 of 188 cases where it disagreed with Binance. Maker replay on 125 KXBTC15M markets / 30 h: resting 1 contract at the best YES bid and best NO bid every 60 s, held to settlement, earned +0.35 cents per posted quote (fill rate 56%), BUT t = 0.83 (p about 0.4, i.e. could be zero). Markout 30 s after fill was negative in every bucket (-0.3 to -0.8 cents): fills are adversely selected, then part of it mean-reverts by settlement. Quotes posted in the last 3 minutes of the window did best (+2.71 cents per posted, n=254); 3-6 min and 9-12 min buckets were negative. Back-of-queue fills had higher settlement EV than front-of-queue. A refined version ('BTC YES late Asia') showed +2.00 cents per posted in-sample but failed its own concentration gate (58.7% of profit from one market) and a 9.5-hour run lost -$4.26. Author's verdict: INCONCLUSIVE, calibration falsified, edge tiny if real.",
   "risk_or_catch": "All maker numbers are in-sample on 30 hours; the planned holdout (June 2, 2026) is still pending. The replay does not model cancels ahead in queue or taker reaction. Fee note in the repo: maker fee on KX*15M series recorded as $0 (2025-07-01 schedule), taker about 1.56 cents at 50c; verify against the live /series endpoint (see spencerfletcher item).",
   "worth_copying": "The scoring method for a resting-bid bot: report BOTH 30-second markout and settlement P&L per posted quote, by time-to-expiry bucket and by hour of day, under three queue assumptions (front, 50%, back). The pre-registration + concentration gate. The BRTI-vs-Binance settlement check. Their fee-assumption document is a good template for freezing assumptions before a test."
  },
  {
   "name": "hudsonjoshuaclark/kalshi-bot",
   "url": "https://github.com/hudsonjoshuaclark/kalshi-bot",
   "what": "Fair-value taker bot for Kalshi 15-minute crypto and commodity markets, shipped with the research showing it has no edge. 0 stars, 2 commits, no license shown, last commit Sep 14, 2026. Order entry was via a phone-app automation harness (3-5 s per order), never run live.",
   "evidence_grade": "B (large backtest with code, pre-registered, honest negative)",
   "evidence": "8,115 settled markets across 33 series. Crossing the spread lost at nearly every horizon; favourite-longshot bias of -2.8 to -4.5 cents per contract 10-15 minutes before close. 60 pre-registered rule combinations (15 rules x 4 entry points): none survive multiple-comparison correction; all-series went +0.79c in train to -0.18c in test. Best candidate ('Robust RV', buy when implied vol / realised vol >= 2 at minute 9): +3.57 cents per trade on 200 held-out trades, raw p = 0.025 but corrected p = 1.0 and it failed the drift check (made money only when the coin fell). 'Two-touch lock-in' (lock a pair when both sides are touched) lost -3.3 cents per trade on n = 5,550 in training and was rejected. Portfolio sim of the taker bot: 182 trades, 47.8% hit rate, +$9.56 P&L minus $7.67 fees, 56% chance of wiping the $19 bankroll.",
   "risk_or_catch": "The lock-in result is the closest public test of our own 'lock at the end' idea and it lost. Author's conclusion: the only strategy the data suggests is market-making with resting orders, which needs the authenticated API.",
   "worth_copying": "The statistics kit: a 'market-null' bootstrap (20,000 redraws using the price you actually paid as the win probability), a drift check (split P&L by whether the coin went up or down), Bonferroni over every combination you searched, and 'test set opened once'. Also s1_maker.py: a conservative resting-quote simulator (a fill only counts if the next print goes strictly THROUGH your price; pessimistic version needs 2 ticks through). Also collect_pyth.py: free 1-minute Pyth history from benchmarks.pyth.network/v1/shims/tradingview/history (no key; history only, not live), verified to reproduce Kalshi gold strikes to 0.0015%."
  },
  {
   "name": "simonziervogel/trading-bot",
   "url": "https://github.com/simonziervogel/trading-bot",
   "what": "Paper-trading bot for Kalshi 15-minute BTC/ETH with four strategies and three backtest engines with no-lookahead tests (115 tests). 0 stars, MIT, 24 commits.",
   "evidence_grade": "B (backtest with code; the one positive claim is probably an artifact)",
   "evidence": "FairValue NO-side (digital-option price from a lognormal model vs Kalshi quotes): pooled Jan-Jun 2026 N = 9,563, 58.6% win, +8.6 cents per contract, z = +20; out-of-sample N = 233, +22 cents, z = +7.3. Momentum: apparent edge vanished after fixing the fill model (z +2.16 to -0.66). FavoriteLongshot live paper: lost $1,615 over 26 sessions at a 9.7% win rate; disabled. Live validation of FairValue began Sep 23, 2026 with a sample near zero.",
   "risk_or_catch": "The author's own leading explanation is quote staleness: the backtest pairs fresh Binance candles with Kalshi quotes that may lag by seconds, which manufactures 'edge' you cannot trade. Our Lab 5 found NO EDGE on the same idea with timing-aligned data. Treat the z = +20 as a warning about stale-quote backtests, not as a strategy.",
   "worth_copying": "Two lessons: (1) fill at the executable price (yes_ask for YES, 1 - yes_bid for NO), never the midpoint; using the midpoint had inflated their edge by about half the spread per trade; (2) re-run every 'edge' after a fill-model fix before believing it."
  },
  {
   "name": "nepalanurag/kalshi-btc15m-bot",
   "url": "https://github.com/nepalanurag/kalshi-btc15m-bot",
   "what": "Research bot for KXBTC15M: RSI signal once per window, limit orders placed inside the spread and walked up to a cap, one fill per window, hold to settlement, paper mode by default. 0 stars, 12 commits, last commit Oct 11, 2026.",
   "evidence_grade": "B (21-day backtest with code, honest loss)",
   "evidence": "Sep 14 - Oct 5, 2026: 2,016 windows, 1,793 traded, -$2,386.62 after fees (about $715 of fees), profit factor 0.786, max drawdown $2,768. In bullish/bearish regimes it won 30.8% / 27.4% vs 33.8% / 34.1% implied by the price it paid. All 72 threshold settings lose; the best still loses $914.88.",
   "risk_or_catch": "Strikes are synthetic and entry prices are proxied by a model, so the dollars are illustrative. Uses maker fee ceil(0.0175 x C x P x (1-P)) which may not apply to KXBTC15M (see fee note).",
   "worth_copying": "fill_models.py: reports paper P&L under an optimistic fill and a conservative fill (queue position, partial fills, adverse selection) side by side. The datalake pattern (minute capture of Kalshi book + Coinbase candle, schema-validated, quarantined on failure)."
  },
  {
   "name": "shwoopnet/shwoopnet PR #245 (Kalshi scalping and calibration verdicts)",
   "url": "https://github.com/shwoopnet/shwoopnet/pull/245",
   "what": "An admin page with a paper bot for 15-minute BTC and gold markets plus offline scalping research with thresholds fixed beforehand.",
   "evidence_grade": "B (pre-registered falsifications; sample sizes not shown)",
   "evidence": "Scalping 60-second direction calls: break-even needs about 76% of calls right for BTC and 78% for gold -> FALSIFIED. 'Favourites underpriced, hold to settlement': significantly negative at the 2-minute entry (z = -4.2), the opposite of the hypothesis. 'Buy at 40-50c, sell at 80c': lost about 8 cents per contract in both halves of the data. Path check: when a side reaches 70% in the first 2 minutes it finishes that way 74.8% of the time vs a price of 75.4% (noise).",
   "risk_or_catch": "No sample sizes or Brier scores reported; it is one developer's internal PR.",
   "worth_copying": "The break-even hit-rate framing for any in-and-out idea. Their 429 handling (honour Retry-After, heavier backoff, resumable backfill)."
  },
  {
   "name": "spencerfletcher/market-maker",
   "url": "https://github.com/spencerfletcher/market-maker",
   "what": "Async Python market-making engine for Polymarket US and (venue client only) Kalshi: exact-Decimal money, fee models, book-freshness rails, durable state, 654-684 tests. Strategy, markets and ALL results deliberately withheld. 1 star, MIT, last commit Sep 29, 2026.",
   "evidence_grade": "C (claims only; the author says the first readings of fees, markouts and queue metrics 'all read profitable and were all wrong')",
   "evidence": "No P&L published by design (NOTICE.md). Engineering claims are backed by tests in the tree.",
   "risk_or_catch": "You cannot run it; the Kalshi maker engine was removed. Its value is the plumbing and two concrete Kalshi facts.",
   "worth_copying": "(1) The authoritative maker-fee check: GET /series/{ticker} and read fee_type: 'quadratic_with_maker_fees' = makers pay, 'quadratic' = makers free (verified by them Jul 19, 2026). The fee PDF is a strict subset of the API list (76 vs 130 series) and mislabelled KXNBAGAME/KXNHLGAME, which would have cost about 0.44 cents per fill. We should run this check on KXBTC15M today. (2) The float fee bug: 0.07 x 0.5 x 0.5 x 10,000 = 175.00000000000003 in floating point, so a plain ceil() charges the wrong cent; use Decimal and quantize. (3) Feed freshness judged by CONTENT (the venue's transaction time), not by message receipt, with a periodic REST read as the hard bound. (4) A shared request budget with priority classes and a 'ban latch' so teardown bursts do not extend a rate-limit ban. (5) Cancel 404 = order already gone (benign), relevant to our PR #14. (6) Their get_positions bug: the response key is market_positions, not positions."
  },
  {
   "name": "hughosh/lip",
   "url": "https://github.com/hughosh/lip",
   "what": "Go client and harness for Kalshi's LIP: post-only YES and NO bids at the touch in incentivized markets, with heavy reconciliation of orders/fills/positions against REST. 0 stars, Go 1.26, last commit Oct 4, 2026, 164 MB clone (AI-assisted).",
   "evidence_grade": "C (live stage records exist, no P&L; author: profitability unestablished)",
   "evidence": "One attended live stage on Oct 1, 2026 lasted 7 h 39 min: one round trip, then almost five hours draining a position through an exchange halt; observer gaps of 18 and 96 minutes. 118 mutation tests (117 caught). Economics review verdict: 'not profitable as operated, and not shown profitable as designed'; short stages earn nothing because of the $1 payout floor.",
   "risk_or_catch": "Huge repo with Mac-specific paths; no demo environment; a fill at the touch leaves a directional position that can take hours to unwind.",
   "worth_copying": "Order-state discipline: persist a reservation before every write; an ambiguous (timed-out) create stays reserved until resolved; a cancel acknowledgement is not proof the order is gone; live writes need both a -live flag and a separate sentinel file."
  },
  {
   "name": "nikkowalow/kalshi-liquidity-provider (klp)",
   "url": "https://github.com/nikkowalow/kalshi-liquidity-provider",
   "what": "Complete LIP market-making bot: scores markets by estimated $/day, places two-sided post-only quotes at the deepest price that keeps within 10% of the best reward share, sticky quotes to keep queue priority, live per-second reward tracker, risk breakers, React dashboard. 0 stars, 43 commits, last commit Oct 6, 2026, no license shown.",
   "evidence_grade": "D (no results; estimates only)",
   "evidence": "Only numbers are upper-bound estimates, e.g. an $830/day program estimated at $20.81/day for 10 contracts, assuming no competitor reacts and no fill losses. README warns resting orders get filled right before the price moves against you.",
   "risk_or_catch": "Fees not modelled in pricing; demo has no incentive programs; no live P&L anywhere.",
   "worth_copying": "rewards.py (tested LIP scoring incl. queue position); the fill-risk module that replays recent public trades as 'sweeps' against the quotes you would post and ranks markets by reward minus expected fill cost; 'blind means flat' (pull quotes on any WebSocket gap until a fresh snapshot); use of Kalshi's order-group limit so the exchange cancels all your orders if more than N contracts match in 15 s; token buckets matching Kalshi's read/write budgets."
  },
  {
   "name": "50thycal/kalshi_bot",
   "url": "https://github.com/50thycal/kalshi_bot",
   "what": "AI-driven research machine (1,803 commits, 2 stars) with paper books and a liquidity-incentive workstream (LIMM).",
   "evidence_grade": "C (small confirmed rewards; everything else paper or model)",
   "evidence": "Lifetime Kalshi-confirmed LIP rewards: $4.30 ($2.21 + $2.09 on two markets). Placement probe run 3 (400 markets, 7 days): a deeper quote is identical to the live rule because the program discount factors are almost all 0.50; a two-sided version earned 66% of the live rule's net with 1.8x the fill losses. Their reward model 'reads far above real payouts'. The thesis question (can a $50-$500 account net >= $1/day) is unanswered.",
   "risk_or_catch": "Mostly machine-generated volume; no live edge shown; the '+5.2 cents per contract' theta claims are backtests.",
   "worth_copying": "Reporting fills under three fill models (optimistic, conservative, queue-aware) with marks at 1 s, 5 s, 30 s, 60 s and 5 min after the first fill; counting only rewards Kalshi actually confirms."
  },
  {
   "name": "ericsohel/KalshiTradingProject (tape)",
   "url": "https://github.com/ericsohel/KalshiTradingProject",
   "what": "Order-book flight recorder for Kalshi: every WebSocket frame written raw and timestamped to zstd segments before parsing, books in YES space with integer prices, 5-minute keyframes, REST audits, ZeroMQ bus, Parquet/DuckDB catalog, WebGL viewer. Replay engine, simulator and market maker not built yet. 0 stars, MIT, 771 tests at 96% branch coverage, last commit Sep 21, 2026.",
   "evidence_grade": "D for trading (no strategy yet); strong engineering evidence",
   "evidence": "49 hours of a 2,000-market tape (5.81 GiB, 220 million records) baked to 1.99 GiB Parquet; 317,217 of 317,389 book rebuilds (99.95%) matched the next keyframe; 32,472 of 32,710 REST audits passed (99.3%). ADR 0015 cites two academic studies on tens of millions of trades: makers on contracts above 50 cents earn a small positive return after fees, and retail systematically overbets YES; it also states 'the research found no Kalshi project whose backtest survived contact with live trading'.",
   "risk_or_catch": "Infrastructure only; the maker that would use it does not exist yet.",
   "worth_copying": "For our recorder (task #90): record raw frames first; one subscription per connection; on a sequence gap re-snapshot only the affected connection; keyframe every 5 minutes and audit against REST. ADR 0019 liveness rule: Kalshi's heartbeat pings every 10 s never surface as data frames, so judge liveness by client ping every 10 s with a 20 s pong deadline, not by data silence (a data-silence timeout falsely killed quiet connections every 30 s). ADR 0014: any maker backtest must report fills as a BAND from three models (all cancels ahead of you, all behind, calibrated from real 1-cent probe orders using the queue position Kalshi reports in fill messages)."
  },
  {
   "name": "briancox730/unofficial-kalshi-api-docs",
   "url": "https://github.com/briancox730/unofficial-kalshi-api-docs",
   "what": "Practical reference of undocumented Kalshi API behaviour with a small client (auth, REST, WebSocket, exact order-book accumulation). 0 stars, MIT, 8 commits, last commit Aug 24, 2026; 'last verified June 2026'.",
   "evidence_grade": "D (documentation, no strategy)",
   "evidence": "15 gotchas verified against the live API in 2026.",
   "risk_or_catch": "Small, unmaintained-looking; re-verify each item against the demo environment.",
   "worth_copying": "The v1 order endpoint died Jun 18, 2026 (410); V2 is POST /portfolio/events/orders, YES-referenced (side = bid/ask, one price as a 4-decimal string; buy NO at n = ask at 1 - n; self_trade_prevention_type required; count is a fixed-point string; response is flat and average_fee_paid is PER CONTRACT). Cancel returns reduced_by; 0 means it had already filled. No V2 single-order GET: detect fills from GET /portfolio/fills or the WebSocket fill channel. Positions lag fills by about 1 s. The book is bids only (yes_ask = 100 - best_no_bid). WebSocket deltas are fractional: accumulate exactly and remove a level only when it nets to about 0, or you get phantom levels and fake crossed books. Sign the path without the query string, timestamps in milliseconds. IOC orders can fill when the REST book looks empty. Taker fee ceil(0.07 x P x (1-P)) rounded up to the cent; 'maker fills are free' (empirical, confirm per series)."
  },
  {
   "name": "seanrobenalt/kalshi-bot (Rust)",
   "url": "https://github.com/seanrobenalt/kalshi-bot",
   "what": "Buys YES and NO when the combined ask is under $1; in the last 60 seconds buys whichever side is priced 90-97 cents; optional spot-lag signal with a crude sigmoid (45 bps scale for BTC). FOK orders over REST, GitHub Actions cron. 1 star, 6 commits, last commit Feb 13, 2026.",
   "evidence_grade": "C (honest live loss, no detail)",
   "evidence": "Repo description: 'configure settings so it makes you money, it lost me $100'.",
   "risk_or_catch": "This is exactly the 'near-certain grind' our Lab 4 tested; buying both sides under $1 is not a real arbitrage once fees and non-atomic fills are counted.",
   "worth_copying": "Nothing."
  },
  {
   "name": "SiddhaBasu/kalshi-bot",
   "url": "https://github.com/SiddhaBasu/kalshi-bot",
   "what": "KXBTC15M paper bot: zero-drift GBM fair value plus an XGBoost classifier on 22 causal features, Platt calibration, 0.15 Kelly, with a 2,155-line research log of what it learned from other public bots. 0 stars, MIT, 38 commits, last commit Sep 12, 2026.",
   "evidence_grade": "C (paper trading only; results negative)",
   "evidence": "Walk-forward backtest Brier 0.130 vs live paper Brier 0.19-0.23 (n = 49). After bug fixes: n = 15, 26.7% win, -$12.33; at n = 25 Brier 0.215 with 95% CI [0.172, 0.259], still excluding the backtest's 0.130. They found two real train/serve bugs (candles stuck at volume 0; a time-elapsed feature computed from the hourly candle) and a settlement nuance: BRTI is a 60-second average, so a raw spot feed is noisier than what settles.",
   "risk_or_catch": "Never beat the market live despite a strong-looking backtest; the live-vs-backtest gap is the recurring story.",
   "worth_copying": "A 'feature parity' job that recomputes live features offline and flags drift; Brier score with a confidence interval instead of a point number; a quote-staleness feature (seconds since the Kalshi quote last changed, and BTC move since then)."
  },
  {
   "name": "ryanfrigo/kalshi-ai-trading-bot",
   "url": "https://github.com/ryanfrigo/kalshi-ai-trading-bot",
   "what": "LLM-decision Kalshi bot (one model call per decision, Claude Sonnet 4.5 via OpenRouter, $10/day cost cap). 618 stars, 198 forks, MIT, 204 commits.",
   "evidence_grade": "B for honesty (forward-only live verdict on the author's account, small n)",
   "evidence": "Oct 2, 2026 verdict on 55 settled live trades: NO MEASURED EDGE, 58% win rate vs 60% implied by the book (-1.9 points). NO side +7.6 points (n = 37), YES side -22.7 points (n = 17). README says running 'Beast Mode' with real money 'historically led to significant losses'.",
   "risk_or_catch": "LLM costs; no edge; the multi-model 'ensemble' is unwired scaffolding.",
   "worth_copying": "The TRACK_RECORD.md habit: forward-only, implied-vs-realized win rate by side."
  },
  {
   "name": "kel-reid/Kalshi-Trading-Bot",
   "url": "https://github.com/kel-reid/Kalshi-Trading-Bot",
   "what": "Avellaneda-Stoikov market maker on in-season sports contracts expiring within 8 days (min spread 4c, gamma 0.7), with Prometheus/Grafana Cloud, Terraform on DigitalOcean, GitHub Actions. 0 stars, MIT, 327 commits, Python 3.12+.",
   "evidence_grade": "D (no results)",
   "evidence": "Only an illustrative log excerpt. Trades real money.",
   "risk_or_catch": "No P&L; sports makers pay maker fees on many series.",
   "worth_copying": "Risk rules worth borrowing: pull all quotes for 30 s after a 6-cent mid move within 20 s; stop and rotate markets after a $3 loss or $2.50 in fees; a synchronous kill switch that cancels tracked orders on SIGTERM and waits for exchange confirmation; Grafana alerting."
  },
  {
   "name": "bkux33/kalshi-market-maker (fork of zachdaube)",
   "url": "https://github.com/bkux33/kalshi-market-maker",
   "what": "Avellaneda-Stoikov maker with a market scanner, fee floor, toxic-flow score thresholds (40/60/80 -> reduce/widen/pull) and 175 mocked unit tests. 0 stars, MIT, 25 commits.",
   "evidence_grade": "D (no results)",
   "evidence": "Mocked tests only; the README says it is not a guaranteed profit strategy.",
   "risk_or_catch": "Dashboard has no authentication.",
   "worth_copying": "The toxic-flow ladder (reduce, widen, pull with cooldowns) as a shape for our bid-puller."
  },
  {
   "name": "rodlaf/KalshiMarketMaker",
   "url": "https://github.com/rodlaf/KalshiMarketMaker",
   "what": "The most-starred Kalshi market maker: one Avellaneda-Stoikov worker per market, binary markets only, selection by volume and spread, contract caps, cleanup routine. 417 stars, 78 forks, MIT, 31 commits.",
   "evidence_grade": "D (no results)",
   "evidence": "No backtest or live numbers anywhere.",
   "risk_or_catch": "Popularity is not evidence; defaults to the demo URL.",
   "worth_copying": "The deselection cleanup pattern (stop worker, wait, cancel that market's resting orders, verify)."
  },
  {
   "name": "newyorkcompute/kalshi",
   "url": "https://github.com/newyorkcompute/kalshi",
   "what": "TypeScript monorepo: Kalshi MCP server, terminal UI, 5 maker strategies (symmetric, optimism-tax, adaptive, Avellaneda-Stoikov, weather-informed) and a compliance layer for Kalshi's 2025 Market Maker Program (two-sided min depth / max spread, 98% availability target per product per rolling hour, audit log, self-trade guard). The maker itself is unpublished. 9 stars, MIT, 118 commits.",
   "evidence_grade": "D (no results)",
   "evidence": "None.",
   "risk_or_catch": "Program rules are described without numbers; the actual bot is internal.",
   "worth_copying": "The compliance checklist shape if we ever join the official Market Maker Program."
  },
  {
   "name": "OctagonAI/kalshi-trading-bot-cli",
   "url": "https://github.com/OctagonAI/kalshi-trading-bot-cli",
   "what": "Company-made CLI (Bun) that runs 'deep research' on event markets, estimates probabilities, computes edge vs the book, sizes with half-Kelly behind a 5-gate risk engine (Kelly, Liquidity, Correlation, Concentration, Drawdown 20%, daily loss $200). 396 stars, 109 forks, MIT, 290 commits.",
   "evidence_grade": "C (claims only; the backtest shown is sample output)",
   "evidence": "README example: Brier 0.168 vs market 0.192, +12.5% skill, 61.4% hit rate, +7.8% flat-bet ROI over 15 days, presented as illustrative output, not a track record.",
   "risk_or_catch": "It is a funnel for Octagon's paid research credits (3 credits per report), needs LLM keys, and telemetry is on by default. Not for 15-minute crypto.",
   "worth_copying": "The drawdown-from-peak gate as an addition to daily-loss stops; nothing else."
  },
  {
   "name": "suislanchez/polymarket-kalshi-weather-bot",
   "url": "https://github.com/suislanchez/polymarket-kalshi-weather-bot",
   "what": "Weather (KXHIGH) via a 31-member GFS ensemble plus a 5-minute BTC signal on Polymarket; 0.15 Kelly; Brier calibration panel. 780 stars, 192 forks, MIT, 33 commits.",
   "evidence_grade": "C (the '$1.8k highest profits' is a simulation)",
   "evidence": "README calls it 'a simulation tool for educational purposes' with a virtual bankroll; no trade logs or period for the $1.8k.",
   "risk_or_catch": "Headline number is paper; most stars of any repo in this sweep.",
   "worth_copying": "The calibration panel idea; nothing for KXBTC15M."
  },
  {
   "name": "reedjacobp/kalshi-trading-bot",
   "url": "https://github.com/reedjacobp/kalshi-trading-bot",
   "what": "KXBTC15M bot: 'consensus' when 3 of 4 signals agree (BTC momentum, previous result, Kalshi book skew, Crypto.com order-flow imbalance), a 'Resolution Rider' in the last 90 s, favourite-longshot above 70c, 0.25 Kelly, -$50 daily pause. 3 stars, 6 forks, 25 commits, no license shown.",
   "evidence_grade": "D (no results)",
   "evidence": "None.",
   "risk_or_catch": "The last-90-seconds 'rider' is the taker version of our lock-in; hudsonjoshuaclark's data says that loses.",
   "worth_copying": "Nothing."
  },
  {
   "name": "hamad-khawaja/kalshi-trading-bot",
   "url": "https://github.com/hamad-khawaja/kalshi-trading-bot",
   "what": "15-minute BTC/ETH bot: 16 weighted signals blended 30% with the market price, Kelly 0.20 with zone/time/vol scaling, feeds from Coinbase, Kraken, Kalshi WS, Bybit funding and liquidations, Chainlink. 4 stars, 5 forks, MIT, 104 commits.",
   "evidence_grade": "D (no results)",
   "evidence": "Dashboard screenshot only; 'use at your own risk'.",
   "risk_or_catch": "More feeds is not more edge; Kalshi settles on the CF Benchmarks BRTI, not on these venues.",
   "worth_copying": "The funding-rate / liquidation-imbalance feature idea, untested."
  },
  {
   "name": "brandononchain/kalshibot",
   "url": "https://github.com/brandononchain/kalshibot",
   "what": "GBM fair value vs Kalshi ask (trade on >= 8% gap), Polymarket midpoint as fair value (>= 5% gap), dual-side arbitrage disabled because the two legs are not atomic. 29 stars, 13 forks, 45 commits.",
   "evidence_grade": "D (synthetic backtest only)",
   "evidence": "README: 'These code changes do not validate profitability'. Claims Kalshi reprices 3-7 s after spot moves (unverified).",
   "risk_or_catch": "The lag claim is the whole thesis and is asserted, not measured.",
   "worth_copying": "Nothing."
  },
  {
   "name": "kapelame/kalshi-crypto-bot",
   "url": "https://github.com/kapelame/kalshi-crypto-bot",
   "what": "Framework for 15-minute crypto: 2-second collector (Kalshi + Coinbase), XGBoost trainer, walk-forward backtester, live trader whose strategy function is intentionally empty, terminal dashboard; ships a 2,500-snapshot sample. 7 stars, MIT, 4 commits.",
   "evidence_grade": "D (no results)",
   "evidence": "None.",
   "risk_or_catch": "Clone instructions point at a differently named repo; polling, no WebSocket.",
   "worth_copying": "The 67-column feature schema (book imbalance from depth, 5/15/30-second momentum, time to expiry, strike distance) and the plain fee formulas (taker 7%, maker 1.75% of P x (1-P), rounded up; peak at 50c)."
  },
  {
   "name": "mattypie314/KalshiBot-Scalper",
   "url": "https://github.com/mattypie314/KalshiBot-Scalper",
   "what": "Paper scalper: compares Coinbase/Kraken/Bitstamp spot to the Kalshi book each tick, enters only on a fast lag, limit orders only, +4-8c take profit, exit if nothing happens in about 35 s, reduce-only IOC exits, 3-5% of bankroll per trade. 0 stars, GPL-3.0, 37 commits.",
   "evidence_grade": "D (no results)",
   "evidence": "None.",
   "risk_or_catch": "GPL license; our Lab 7 found in-and-out trading has no edge on all four desks.",
   "worth_copying": "Nothing."
  },
  {
   "name": "dev-lcastaa/kalshi-momentum-bot",
   "url": "https://github.com/dev-lcastaa/kalshi-momentum-bot",
   "what": "Momentum scalping research for KXBTC15M/KXETH15M with a replay simulator (order book, queue position, fees, settlement), fidelity gates G1-G4, and live arming that needs a global switch + per-user flag + bot key + no kill switch + per-order limits. 0 stars, 8 commits, no license.",
   "evidence_grade": "D (no results)",
   "evidence": "None.",
   "risk_or_catch": "Strategy details not published.",
   "worth_copying": "The multi-gate live-arming pattern."
  },
  {
   "name": "DeweyMarco/simple-kalshi-bot",
   "url": "https://github.com/DeweyMarco/simple-kalshi-bot",
   "what": "Paper strategies on KXBTC15M: buy the previous window's winner, 60-second BTC momentum, and their consensus; $5 stakes logged to CSV. 4 stars, Apache-2.0, 8 commits.",
   "evidence_grade": "D (no results shown)",
   "evidence": "Trade CSV exists but no win rates or P&L on the page.",
   "risk_or_catch": "Toy.",
   "worth_copying": "Nothing."
  },
  {
   "name": "ahlstromgarrett/kalshi-trading-bot",
   "url": "https://github.com/ahlstromgarrett/kalshi-trading-bot",
   "what": "Automates the owner's manual habit: buy the 90-99 cent side of any binary settling within 24 hours (not within 5 minutes); 3% stake, 8% cap, 60% exposure cap, 15% daily halt, max 25 positions. 0 stars, 1 commit.",
   "evidence_grade": "C (a manual trade log, no bot results)",
   "evidence": "156 manual trades, about 94.5% win rate, which the author notes equals the average implied entry probability, so 'the edge is thin'; the 0.96-0.99 band was the worst by dollars.",
   "risk_or_catch": "Confirms our Lab 4 result on the near-certain grind: you win as often as the price says, and the losers cost more than the winners pay.",
   "worth_copying": "Nothing."
  },
  {
   "name": "LoQiseaking69/kalshi-trading-bot",
   "url": "https://github.com/LoQiseaking69/kalshi-trading-bot",
   "what": "'Sophisticated quant-grade' event-market bot with sentiment, arbitrage and volatility strategies and a Telegram UI. 11 stars, 3 commits.",
   "evidence_grade": "D (puffery)",
   "evidence": "The '68.5 win rate, 1.8 Sharpe' appear as placeholder API responses; code snippets call undefined functions; no outputs.",
   "risk_or_catch": "FLAG: AI-generated marketing language with no substance.",
   "worth_copying": "Nothing."
  },
  {
   "name": "lek-orer/kalshi-polymarket-arbitrage-trading-bot-python (Bitbash)",
   "url": "https://github.com/lek-orer/kalshi-polymarket-arbitrage-trading-bot-python",
   "what": "README-only repo (the file tree it describes does not exist) advertising a Kalshi/Polymarket arbitrage bot built by an agency. 0 stars, 1 commit.",
   "evidence_grade": "D (spam)",
   "evidence": "'Over 95% trade execution success', generic testimonials, contact via Telegram, WhatsApp, email, website and a booking calendar; talks about 'gas fees' for Kalshi (templated copy).",
   "risk_or_catch": "FLAG: sales funnel, not software. Similar listings dominate Fiverr ('I will build a profitable Kalshi bot') and there is a $15 'Build your own Kalshi bot 5-part course' on Getly.",
   "worth_copying": "Nothing."
  },
  {
   "name": "CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot",
   "url": "https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot",
   "what": "Watches Bitcoin 1-hour markets on both venues and flags 'risk-free' profit when Polymarket Down + Kalshi Yes costs under $1. 254 stars, 37 forks, MIT, 13 commits.",
   "evidence_grade": "D (no results)",
   "evidence": "No backtest, P&L or logs.",
   "risk_or_catch": "FLAG the 'risk-free' wording: ignores fees, fill size, leg timing, capital lockup and, most important, that the two venues settle on different price sources and timestamps, so the pair is not actually hedged.",
   "worth_copying": "Nothing."
  },
  {
   "name": "ImMike/polymarket-arbitrage",
   "url": "https://github.com/ImMike/polymarket-arbitrage",
   "what": "Scans thousands of markets for cross-venue (Polymarket vs Kalshi, matched by text similarity), within-venue bundle (YES+NO != $1) and wide-spread market-making opportunities; dry-run by default. 288 stars, 127 forks, MIT, 4 commits.",
   "evidence_grade": "D (simulation only)",
   "evidence": "'Simulated opportunities: 99.6% win rate, $573' and the README itself says real markets are highly efficient and opportunities rare.",
   "risk_or_catch": "Matching markets by text similarity across venues with different resolution rules is how people lose both legs.",
   "worth_copying": "Nothing."
  },
  {
   "name": "sssobolevski/polymarket-bots (polbots.com directory)",
   "url": "https://github.com/sssobolevski/polymarket-bots",
   "what": "'126 bots compared and vetted' list maintained by polbots.com, each entry linking to a review page. 6 stars, 40 commits, updated Oct 13, 2026.",
   "evidence_grade": "D (directory)",
   "evidence": "Their own standard: performance figures 'are whatever the author publishes and are not independently verified'.",
   "risk_or_catch": "FLAG: a marketing directory, not evidence. Only one or two entries are Kalshi-specific.",
   "worth_copying": "Nothing."
  },
  {
   "name": "TurbineFi blog: 'We tested 5,732 Kalshi Bitcoin 15-minute bot variants'",
   "url": "https://www.turbinefi.com/blog/5732-backtests-kalshi-bitcoin-15-minute-bots-2026",
   "what": "A vendor's roll-up of 5,732 KXBTC15M backtests from 63 public reports (Jun 9 - Sep 24, 2026) run on its own backtesting product.",
   "evidence_grade": "C (vendor backtests; not live)",
   "evidence": "37.6% of variants had positive simulated P&L, 43.5% lost, 18.9% were flat; 972 placed no trades; counts include repeats. 'Momentum continuation' 100/100 positive (+$1,132 to +$3,541) but a later panic-fade retest went 0/100; trend-confirmation 0/100 with fees eating 146% of gross; a maker sweep 26/100 positive and one post-only MM study 100/100 whose permutation test failed. No fees/slippage/latency modelling.",
   "risk_or_catch": "FLAG: sells Turbine Studio ('Build a bot' links to pricing). Positive backtests here have the same stale-quote risk as everyone else's.",
   "worth_copying": "Nothing; keep the number 'fees consumed 146% of gross' in mind."
  },
  {
   "name": "Kalshi official code: kalshi-starter-code-python, tools-and-analysis, official SDKs",
   "url": "https://github.com/Kalshi/kalshi-starter-code-python",
   "what": "Kalshi's GitHub org has 9 public repos: kalshi-starter-code-python (103 stars, 74 forks; 'example python code for authenticated endpoints, not an SDK'), tools-and-analysis (23 stars, notebooks), the rest are forks. Official SDKs per docs.kalshi.com: kalshi_python_sync, kalshi_python_async, kalshi-typescript; the old kalshi-python package is deprecated; Ed25519 keys need SDK >= 3.31.0; the OpenAPI/AsyncAPI yaml files are the source of truth because SDKs lag.",
   "evidence_grade": "D (no strategy; official plumbing)",
   "evidence": "n/a",
   "risk_or_catch": "No official community/Discord/forum link found anywhere in the docs or org; the starter repo may predate the V2 order endpoint.",
   "worth_copying": "Use the official OpenAPI yaml to regenerate our client when Kalshi changes endpoints (they did on Jun 18, 2026)."
  },
  {
   "name": "Client libraries: arshka/pykalshi, TexasCoding/kalshi-python-sdk, lukepalmdc/kalshi_ws_orderbook_simple",
   "url": "https://github.com/arshka/pykalshi",
   "what": "pykalshi: 133 stars, 27 forks, MIT, 164 commits; OrderbookManager from WebSocket deltas, exponential-backoff retries; reconnect/sequence checks not documented. TexasCoding kalshi-sdk (pip kalshi-sdk): 10 stars, MIT, 331 commits; sync+async REST, 12 typed WebSocket channels, an async FIX engine, perps client, maps 117 of 118 operations of OpenAPI v3.34.0 with contract tests. lukepalmdc: 1 star; book can fall out of date under backpressure, resubscribe workaround.",
   "evidence_grade": "D (libraries, no strategy)",
   "evidence": "n/a",
   "risk_or_catch": "None of them documents handling fractional deltas or the V2 order body explicitly; test before trusting.",
   "worth_copying": "TexasCoding's FIX engine is the only public Kalshi FIX implementation; FIX order entry is faster than REST (tens of ms) if we ever need the half-second head start we keep discussing. Its contract tests against the OpenAPI spec are a good pattern."
  },
  {
   "name": "Strobingn/kalshi-odds-app release 'scalper-data' (public dataset)",
   "url": "https://github.com/Strobingn/kalshi-odds-app/releases/tag/scalper-data",
   "what": "Data-only release: 1-second Kalshi 15-minute order books, every public trade, settlements and Coinbase spot, one file per UTC day, 48 files; plus the study files of their scalping research.",
   "evidence_grade": "D (data; study conclusion not on the page)",
   "evidence": "n/a",
   "risk_or_catch": "Markets covered and date span are not stated; treat as untrusted data (parse only, never execute).",
   "worth_copying": "The dataset could extend our recorder history for free before our own 48-hour tape matures (task #90), after a format check."
  },
  {
   "name": "Vanished repos: Bh-Ayush/Kalshi-CryptoBot ('risk-averse and profitable'), fabricio-sousa/mystic-bot (late-window 'Done-Deal'), muxprotocol/kalshi-trading-bot (224 stars / 1.3k forks), dexorynLabs arb bot, 0mnjb/Kalshi-AI-Trading-Bot, cutupdev arb bot",
   "url": "https://github.com/Bh-Ayush/Kalshi-CryptoBot",
   "what": "All six were indexed by search engines this month and all returned 404 at 5:00 PM Pacific on Oct 13, 2026 (deleted, renamed or made private).",
   "evidence_grade": "D (gone)",
   "evidence": "Search snippets only: Bh-Ayush claimed 'profitable' with no numbers; mystic-bot's README admitted its live P&L used the requested limit price, not the real fill; muxprotocol's 1,300 forks on 224 stars is the signature of fork-spam.",
   "risk_or_catch": "The one repo that called itself 'profitable' is the one that disappeared.",
   "worth_copying": "Nothing."
  }
 ],
 "notes": "PLAIN-WORDS SUMMARY FOR THE OWNER (times Pacific).\n\n1. The bottom line. I looked at about 60 public Kalshi bots and libraries and read the code of 11 of them. Not one shows a verifiable live profit. The only verifiable live records are losses: a $20 LIP account that went to $3.84 in 8 days (rewards +$20.30, fills -$36.06), a fair-value bot that lost $32.99 over 285 real fills, an LLM bot with no edge over 55 real trades (58% wins vs 60% implied), a Rust bot that 'lost me $100', and a careful XGBoost bot that was down $12 after 15 paper trades. Your instinct is right: there is nothing on GitHub to copy that makes money. What IS there, and is valuable, is honest negative research and good plumbing.\n\n2. Independent researchers keep landing on the same findings as our own labs. Taking liquidity in 15-minute markets loses 3-5 cents a contract (hudsonjoshuaclark: -2.8 to -4.5c favourite bias on 8,115 markets; shwoopnet: -8c per contract on buy-40-sell-80; nepalanurag: -$2,386 over 21 days). 'Lock in a pair when both sides are touched' lost 3.3c per trade on 5,550 trades. Buying the 90-99c 'sure thing' wins exactly as often as the price says (94.5% on 156 real trades), so no edge, same as our Lab 4. LIP rewards at small size lose to fills (three separate projects, plus 50thycal's lifetime confirmed rewards of $4.30), same sign as our -$457/day estimate. Backtests that look great (one fair-value study shows z = +20) are explained by stale Kalshi quotes paired with fresh exchange prices, and one infrastructure author wrote: 'no Kalshi project whose backtest survived contact with live trading.'\n\n3. The only glimmers, all unproven. (a) Resting quotes held to settlement: aurascoper's 30-hour replay of a dumb two-sided maker on KXBTC15M earned +0.35c per posted quote (t = 0.83, so possibly zero), with the last 3 minutes of the window the best bucket (+2.7c per posted) and back-of-queue fills doing better than front. This is the closest public analogue to our maker bot and it says: not yet proven, needs weeks of data, and markouts 30 s after a fill are always negative even when settlement P&L is positive. (b) Two academic studies cited by ericsohel: makers on contracts above 50c earn a small positive return after fees, and retail overbets YES; two live records here show the NO side doing better (ryanfrigo NO +7.6 pts vs YES -22.7 pts; simonziervogel's edge was NO-side only). A 'make the NO side / quote the favourite side late in the window' hypothesis could be pre-registered against our recorder tape. Hypothesis only.\n\n4. Things we can use this week. (a) Fee check: GET /series/KXBTC15M and read fee_type; 'quadratic' means makers pay nothing, 'quadratic_with_maker_fees' means we pay 1.75% x P x (1-P). Two repos say KX*15M makers pay $0 as of the Jul 1, 2025 schedule; if our P&L model charges a maker fee it understates us by up to 0.44c per fill, and if it charges nothing when we do pay, the opposite. (b) Compute fees in Decimal: 0.07 x 0.5 x 0.5 x 10,000 is 175.00000000000003 in floating point and a plain round-up charges the wrong cent. (c) API facts from briancox730 (verified June 2026): the V2 order endpoint since Jun 18, 2026 is YES-referenced; detect fills from /portfolio/fills or the WebSocket fill channel, not a single-order GET; positions lag fills by about 1 s; a cancel that returns reduced_by = 0 means it had already filled; cancel 404 means already gone (our PR #14); WebSocket deltas are fractional and must be accumulated exactly or you get phantom price levels. (d) Recorder (task #90): ericsohel's design (raw frames first, one subscription per connection, 5-minute keyframes audited against REST; liveness by client ping every 10 s with a 20 s pong deadline, never by data silence). (e) Any maker backtest should report fills as a band from three queue assumptions and both markout and settlement P&L by time-to-expiry bucket (aurascoper, ericsohel, 50thycal all converged on this). (f) For the practice LIP desk (task #96): mirabilis and nikkowalow have tested exact LIP scoring code and a sweep-replay fill-risk model. (g) Free Pyth 1-minute HISTORY (not live) exists at benchmarks.pyth.network/v1/shims/tradingview/history with no key; it reproduced Kalshi gold strikes to 0.0015%, useful for backtests only. (h) A public 1-second KXBTC15M book dataset (Strobingn release) could extend our tape history after a format check.\n\n5. Flags. Sales funnels and puffery: lek-orer/Bitbash (README-only, Telegram/WhatsApp), LoQiseaking69 ('quant-grade' with fake sample numbers), CarlosIbCu ('risk-free' arbitrage across venues that settle on different prices), the polbots.com directory (admits nothing is independently verified), TurbineFi's 5,732-backtest post (sells the backtester), OctagonAI's CLI (paid research credits, telemetry on), Fiverr 'profitable Kalshi bot' gigs and a $15 five-part course. The one repo that called itself 'profitable' (Bh-Ayush) is now a 404, as are mystic-bot, muxprotocol (1.3k forks on 224 stars, fork-spam shape), dexorynLabs, 0mnjb and cutupdev.\n\n6. Secrets and safety. I did not look for, record or use any credential, and none was noted in anything I read. Nothing from any clone was executed, imported or installed; code was read as text only. All 11 clones (about 190 MB) and the downloaded pages were deleted at 5:08 PM Pacific Oct 13, 2026; only my own scripts remain in scratchpad/github_sweep/work (other files there belong to sibling lanes and were left alone). Nothing was written to the project repo.\n\n7. Method limits. The session proxy blocks api.github.com and raw github.com HTML, so star counts and dates come from page summaries fetched through WebFetch and from git logs of the clones; a few repos lack a visible last-commit date. Clone dates are UTC calendar days (a few hours ahead of Pacific). No YouTube or Substack write-up with real P&L and linked code was found; the 'write-up' market is Fiverr gigs and paid courses. Kalshi publishes no community/Discord link in its docs or GitHub org; the official SDKs are kalshi_python_sync/async and kalshi-typescript, with the OpenAPI/AsyncAPI yaml as the source of truth."
}


---
## result 2 

{
 "lane": "LANE 3: Kalshi vs Polymarket cross-venue (BTC 15-minute markets)",
 "items": [
  {
   "name": "CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot",
   "url": "https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot",
   "what": "Python + Next.js dashboard that watches the HOURLY Bitcoin market on both venues (Polymarket 'Bitcoin Up or Down' hourly vs Kalshi's hourly strike ladder) and flags 'risk-free' pairs when Poly Down + Kalshi Yes (or Poly Up + Kalshi No) costs under $1. Detection only, no order placement. 254 stars, 37 forks, 13 commits, last push May 4 2026.",
   "evidence_grade": "D",
   "evidence": "No P&L, no backtest, no count of how often a pair was found. The committed backend.log has zero 'arbitrage' hits. The 'risk-free' label is wrong for this pair: Polymarket's hourly market settles on a Binance BTC/USDT 1-hour candle, Kalshi's on CF Benchmarks, so both legs can win or both can lose.",
   "risk_or_catch": "Different settlement sources (Binance candle vs CF Benchmarks index) means the 'guaranteed $1' is not guaranteed. Ignores fees (about 1.75c per leg at 50c).",
   "worth_copying": "One idea only: the strike-ladder pairing (buy the Down side at a higher strike on one venue and the Yes side at a lower strike on the other; minimum payout $1, sometimes $2). It is sound ONLY where both venues use the same index, which is true for Kalshi KXBTCD hourly strikes vs Polymarket US 'BTC Price at 9:00PM ET' (both BRTI). Untested."
  },
  {
   "name": "brandononchain/kalshibot",
   "url": "https://github.com/brandononchain/kalshibot",
   "what": "Node.js multi-strategy bot for Kalshi KXBTC15M: Binance WebSocket spot, a GBM probability model, Kelly sizing, Polymarket's matching market used as a 'fair value' check, RedStone oracle, dashboard. Claims Binance updates every 200 ms while Kalshi 'reprices with a 3-7 second lag'. 28 stars, 13 forks, 45 commits, last push Sep 24 2026.",
   "evidence_grade": "C",
   "evidence": "Honest and negative. backtest/FINDINGS.md: 7-day synthetic simulation lost money in all three configurations (-$99 with 72% win rate, -$17 with 82%, -$20 flat 1-contract with 79%); model was about 6 points overconfident; 'contracts above 65c are unprofitable even with 80%+ win rate'. Author later added a validity notice that the simulator peeks at future prices and 'do not treat its returns as evidence'. The dual-side 'risk-free' strategy is disabled because the two legs are not atomic. No live P&L.",
   "risk_or_catch": "The 3-7 second Kalshi lag is an author claim, not measured. Our own 2-second sampling found Kalshi and Polymarket moving together with no exploitable lead.",
   "worth_copying": "Nothing new for us. Its lessons (high-priced contracts lose even at high win rates; Kelly over-bets binaries) match what the owner's labs already found. Its 'event-market data capture' is the same idea as the owner's recorder."
  },
  {
   "name": "defi-ape/polymarket-kalshi-arbitrage-bot",
   "url": "https://github.com/defi-ape/polymarket-kalshi-arbitrage-bot",
   "what": "TypeScript service for the BTC 15-minute pair. Rule 1: after minute 8, if Kalshi YES is 93-96c and Polymarket UP is at least 10c cheaper, buy Polymarket UP. Rule 2 ('late resolution'): if Kalshi already shows closed/settled while Polymarket still has orders, buy Polymarket UP. Places real orders only on Polymarket. 12 stars, 27 commits, last push May 29 2026.",
   "evidence_grade": "D",
   "evidence": "No results of any kind; the README's 95c vs 82c example is illustrative. One-sided (no hedge), so it is a directional bet that Kalshi is right, not an arbitrage.",
   "risk_or_catch": "Kalshi and Polymarket settle on different indexes (BRTI vs Chainlink TWAP), which disagreed in 7 of 399 recent windows, always when BTC moved $3 or less over the window. Polymarket.com is also not usable by a US resident.",
   "worth_copying": "The 'late resolution' idea is worth a 1-day log on the Kalshi vs Polymarket US pair (same index): does Polymarket US ever still take orders after Kalshi's result is visible? In our sample the US market went quiet at window end, so probably no."
  },
  {
   "name": "seanrobenalt/kalshi-bot",
   "url": "https://github.com/seanrobenalt/kalshi-bot",
   "what": "Rust bot, Kalshi only, crypto 15-minute markets: buys YES and NO when the two asks add to under $1; in the last 60 seconds buys whichever side is priced 90-97c; optional 'CEX lag' check against Coinbase/Kraken/Binance REST mids. Last push Feb 13 2026.",
   "evidence_grade": "D",
   "evidence": "No results, no logs. Not cross-venue despite the search hit.",
   "risk_or_catch": "Buying the 90-97c side with 60 seconds left is the 'near-certain grind' the owner's lab 4 already tested; fees of up to 1.75c per contract and the occasional late reversal eat it.",
   "worth_copying": "Nothing."
  },
  {
   "name": "TopTrenDev/polymarket-kalshi-arbitrage-bot",
   "url": "https://github.com/TopTrenDev/polymarket-kalshi-arbitrage-bot",
   "what": "Rust cross-platform scanner with fuzzy event matching, a single-venue 'gabagool' (buy YES+NO under $1 on Polymarket) mode, Polygon/USDC plumbing and a Kalshi 15-minute monitor logger. Self-described 'not production ready'. Last push Jun 15 2026.",
   "evidence_grade": "D",
   "evidence": "No results. Fee model assumes a flat 1c per venue, which is wrong (real fee is 0.07 x price x (1-price), up to 1.75c), so its 'net profit' numbers would be overstated.",
   "risk_or_catch": "Author advertises via Telegram/Twitter handles; code quality unverified; wrong fee math.",
   "worth_copying": "Nothing."
  },
  {
   "name": "realfishsam/prediction-market-arbitrage-bot",
   "url": "https://github.com/realfishsam/prediction-market-arbitrage-bot",
   "what": "Educational Node bot (built on the pmxt unified API) that fuzzy-matches outcomes between a Polymarket event and a Kalshi market (example: Fed chair nominee), buys YES on one venue and NO on the other with market orders when the pair costs under $1, 'YOLO' all-in mode by default. Last push Jan 16 2026.",
   "evidence_grade": "D",
   "evidence": "Explicit 'educational purposes only' disclaimer; no results; political markets, not crypto 15-minute.",
   "risk_or_catch": "Market orders on both sides with all-in sizing; fuzzy name matching can pair the wrong outcomes.",
   "worth_copying": "Nothing."
  },
  {
   "name": "Juanp2389/Kalshi-trade-bot",
   "url": "https://github.com/Juanp2389/Kalshi-trade-bot",
   "what": "README-only repo (last push Oct 12 2026) whose 'download' is a Windows zip binary stored inside the repo (porthors/bot_trade_Kalshi_3.3.zip) that asks you to enter your Kalshi and Polymarket keys in the app. No source code.",
   "evidence_grade": "D",
   "evidence": "Nothing but marketing text. Zip not opened (untrusted).",
   "risk_or_catch": "Looks like a credential-stealer pattern: closed binary, 'enter your keys', README-only repo. Do not download or run.",
   "worth_copying": "Nothing."
  }
 ],
 "notes": "PLAIN SUMMARY FOR THE OWNER (times are Pacific, Tue Oct 13 2026)\n\nTHE ONE THING THAT MATTERS\nThere are two different 'Polymarkets' and they settle differently:\n- Polymarket.com (the global site) settles its 5-minute and 15-minute BTC markets on a Chainlink BTC/USD 60-second average. You cannot legally use it from the US (Polymarket says US residents must use the US app).\n- Polymarket US (your account) settles its 'BTC Up or Down 15m' on CF Benchmarks BRTI with the exact Kalshi rule: 60 prices in the last minute before the open and before the close, averaged, rounded to 2 decimals. Same index, same clock, same strike. I checked 400 past windows (about Oct 9 to Oct 13): Polymarket US and Kalshi settled identically 400 of 400 times, and the 'price to beat' matched Kalshi's strike to the cent in all 25 checked (for example 83,310.69 for the 5:15 PM window, 83,380.87 for 5:30, 83,535.87 for 5:45).\nSo Kalshi vs Polymarket US is the only pair where a locked position really pays $1 no matter what. Kalshi vs Polymarket.com is NOT riskless: they disagreed on 7 of 399 windows (1.75%), every time when BTC moved $3.13 or less over the window (example: Oct 12, 5:30-5:45 PM, BRTI fell $2.55 so Kalshi paid No while Polymarket.com paid Up). Near-ties are common: 30 of 400 windows moved $5 or less, 63 moved $10 or less; the median move was $46.\n\n(a) MARKET MAP\nBTC 15 minutes: Kalshi KXBTC15M (BRTI 60-s averages; windows end :00/:15/:30/:45 ET; taker fee 0.07 x price x (1-price), about 1.75c at 50c; maker 0 per your records, Kalshi's fee PDF kept returning 'too many requests' so I could not re-verify it) = Polymarket US cpc-btc-updown-15m-YYYY-MM-DD-HHMMz (BRTI, same rule; taker 0.0695, about 1.74c at 50c; maker rebate 1.25% of notional until Mon Oct 19 10:00 AM PT, then zero for anyone under $10M a month; 1c tick; 0.01 contract minimum) = Polymarket.com btc-updown-15m-<unix start> (Chainlink 60-s TWAP at the end vs the price at the start; taker 0.07, maker 0, 20% of fees rebated to makers; 5-share minimum).\nBTC other horizons: Polymarket.com also runs 5-minute and 4-hour (same Chainlink rule; Kalshi has no 5-minute market) and hourly/daily 'Bitcoin Up or Down - Oct 15, 8PM ET' (Binance BTC/USDT 1-hour candle open vs close). Polymarket US runs 'BTC Up or Down Hourly' and 'Daily' plus 'BTC Price at 9:00PM ET' and 'BTC Price Range' strike markets, all BRTI, which line up with Kalshi KXBTCD (hourly above/below) and KXBTC (hourly range) on CF Benchmarks.\nETH/SOL/XRP/DOGE etc: Kalshi has KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M, KXBNB15M, KXADA15M, KXNEAR15M, KXTON15M, KXZEC15M, KXHYPE15M (all CF Benchmarks). Polymarket.com has eth/sol/xrp 5m and 15m (Chainlink). Polymarket US has BTC only (launched Sep 22 2026).\nFX: Kalshi has 15-minute EURUSD, GBPUSD, USDJPY, USDCAD, AUDUSD (Pyth) plus hourly/daily. Polymarket.com has only DAILY 'EUR/USD Up or Down' (Pyth 1-minute candle close at 1:59 PM PT, fee rate 0.04). No 15-minute FX anywhere else; Polymarket US has no FX.\nMetals: Polymarket.com daily Gold (XAUUSD close vs prior close, fee 0.04); Kalshi daily gold (ICE). Different sources, no short-horizon match. Polymarket US: none.\nIndices: Kalshi KXINX15M / KXNDQ15M (Google Finance quote). No Polymarket match.\nTiming: all three close on the same quarter-hour. Kalshi posts the result about a minute after close. Polymarket.com closes trading about 45-60 s after the window ends and resolves via Chainlink. Polymarket US posts its settlement price later (not yet posted 2 minutes after the 5:30 window closed). Polymarket US quotes usually appear within 3 s of the window open; once (the 5:30 window) they appeared 2 minutes late.\nYour account: yes, Polymarket US lists the 15-minute BTC market in its 'crypto' category (found via the gateway search; the owner's own adapter already recognizes these windows). Availability is state-based; one guide lists AZ, IL, MA, MD, MI, MT, NJ, NV, OH as unavailable; California is not on that list.\n\n(b) WHAT THE 40-MINUTE CAPTURE SHOWED (5:16-5:58 PM, every 2 seconds, public endpoints only, Kalshi at 0.5 requests/s)\nKalshi vs Polymarket.com (809 paired samples, 3 windows; my capture lost the Kalshi side of the 5:30-5:40 stretch to a lookup bug, fixed for the rest):\n- Mid-price gap: median 0.0c, average 0.9c; within 1c 58% of the time, within 2c 81%, over 3c 5.6%. Largest gap 9c at 5:45:22 PM, 22 seconds into the window (Kalshi 65/66c, Polymarket 56/57c).\n- Spreads: Kalshi 0.6c average with about 10,700 contracts at the top; Polymarket 0.8c with about 500-600 shares at the top. Kalshi is the deeper book by 20x.\n- Who leads: at 2-second resolution the two move together (same-second correlation 0.92; correlation at any 2-10 second offset was under 0.07, so no measurable lead). Event count: of 139 Kalshi jumps of 2c or more, Polymarket had already moved 27% of the time, followed within 6 s 62%, never followed 12%; of 136 Polymarket jumps, Kalshi had already moved 39%, followed 50%, never 11%. Kalshi is first a bit more often, but nothing you could trade at our sampling speed.\n- Fee-adjusted 'arb' (take both sides): positive in only 3.2-3.7% of samples, best 1.45c (Kalshi YES + Poly DOWN) and 4.69c (Kalshi NO + Poly UP, for a few seconds around 5:45 PM). And remember this pair is not riskless (1.75% of windows settle opposite ways). Resting on one venue and taking the other looked positive 19-37% of the time, but that needs your resting order to fill exactly when the other side is cheap, which is the same fill problem your Kalshi bot already has.\nKalshi vs Polymarket US (5:40-5:57 PM, 363 paired samples): the raw numbers looked huge (gap up to 22c at 5:48:30 PM, 'arb' positive 41% of the time) but they are an illusion. I probed the US public gateway at 1 request per second: its best bid/offer is a snapshot refreshed every 30 seconds (quote changed 3 times in 120 s while Kalshi's changed 51 times; median staleness 15 s). Comparing only at the 23 moments the US snapshot was fresh: average gap 1.4c, within 2c 19 of 23, max 5c; a fee-adjusted locked pair was positive at 6 of 23 instants, best 1.26c, average -0.95c. So: same-settlement pair, prices within a cent or two, no free money visible with public data. Polymarket US tops of book showed 17,000-120,000 shares; who posts that and whether it fills is unknown (your desk already saw 'No fill' on IOC orders there).\n\n(c) PUBLIC BOTS\nSeven repos read (list above). Best grade is C (brandononchain, whose own backtest lost money and says so). Everything else is D: no results, wrong fee math, or a README-only repo with a Windows binary that asks for your keys (do not run it). Five more repos from the search (TradeSEB, Krypto-Hashers-Community with its '90% profitable logic' claim, PolyBullLabs, Q18thang603, CraftyGeezer) refused to clone (private or removed), so unverifiable. Nobody publishes a live P&L for Kalshi-vs-Polymarket on 15-minute BTC. No secrets were collected or used.\n\nTHE CATCH, PLAINLY\n1. Kalshi vs Polymarket.com: not an arb. Different indexes disagree about 1 window in 57, and you are not allowed to use Polymarket.com from the US anyway.\n2. Kalshi vs Polymarket US: a real same-index pair, but two taker legs cost about 3.5c in fees at 50c plus about 1.5c of spreads, and the fresh-quote gap averaged 1.4c and never exceeded 5c. There is no visible edge with public data, and the public feed is 30 seconds stale so you cannot trade off it.\n3. Any cross-venue lock ties up cash on two exchanges for 15 minutes for a cent or two.\n\nIF YOU WANT ONE MORE STEP\nUse your authenticated Polymarket US WebSocket (market data lite subscription, which the docs say to use instead of polling bbo) to log a live US best bid/offer for one day next to the Kalshi recorder, then count how many seconds a fee-adjusted locked pair of 1c or more existed with size on both sides. If that count is near zero, close this lane. Files: capture scripts and results are in the scratchpad github_sweep/work folder (capture.jsonl, capture2.jsonl, capture_us.jsonl, analysis_k_pm.json, analysis_k_us.json, settle_compare400_us.json). Nothing was written to the repo; clones deleted."
}


---
## result 3 

# GitHub sweep: is there a winning Kalshi bot we can copy?

Written Wed Oct 14, 2026, from three sweeps run Tue Oct 13, 2026, 4:55-5:58 PM Pacific. All times Pacific.

## In one screen

- No. Nothing public shows a verified live profit. Every verifiable live number is a loss.
- Nobody's leaked keys will be used. We did not look for any, saw none, and would not use them if we had: it is unauthorized access, gets accounts banned, and buys no edge.
- What IS worth taking: honest negative research, a better way to score our maker bot, risk rails, verified API facts, and a recorder design. Eight items below, each with a first test.
- Pyth: no free fast feed exists any more. The $500 plan is crypto only; EUR/USD by API is $2,500 a month. A $0 test using Kalshi's own strikes can answer the half-second question in 4-5 days.
- Kalshi vs Polymarket: no visible edge. The same-index pair (Polymarket US) sits within 1.4c on average, under the roughly 5c of fees and spread it costs to lock.

## 1. The honest headline

No. There is no public bot with real, verified profits that we can copy.

What was checked: about 60 public Kalshi bots and libraries (code of 11 read line by line), 7 Kalshi-vs-Polymarket repos, 15 ways to get Pyth or FX prices, plus the vendor blogs, directories and courses that sell around them.

Every live, verifiable number found is a loss:
- A $20 Kalshi liquidity-rewards (LIP) account went from $19.60 to $3.84 in 8 days (Oct 2 to Oct 10). Rewards +$20.30, losses from getting filled -$36.06.
- A fair-value bot: 285 real fills, 51% win rate, -$32.99.
- An AI (LLM) bot with 618 stars: 55 real trades, 58% wins against 60% implied by the price. No edge. Its README says real-money "Beast Mode" historically led to significant losses.
- A Rust bot whose own description says "it lost me $100".
- A careful machine-learning bot: -$12.33 after 15 live paper trades; its live accuracy never matched its backtest.
- A 21-day RSI backtest: -$2,386 after $715 of fees; all 72 settings lose.
- Lifetime confirmed LIP rewards of a 1,800-commit research project: $4.30.

The one repo that called itself "profitable" (Bh-Ayush/Kalshi-CryptoBot) was a 404 by 5:00 PM on Oct 13, along with five others. One infrastructure author who surveyed the field wrote: "no Kalshi project whose backtest survived contact with live trading."

Independent people keep finding what our own labs found:
- Taking liquidity in 15-minute markets loses 3-5 cents a contract (8,115-market study: -2.8 to -4.5c favourite bias 10-15 minutes before close).
- "Lock a pair when both sides are touched" lost 3.3c a trade on 5,550 trades. That is the closest public test of our "lock at the end" idea (taker version), and it lost.
- Buying the 90-99c "sure thing" wins exactly as often as the price says (94.5% on 156 real trades). No edge, same as our Lab 4.
- Small LIP accounts lose more to fills than they earn in rewards (three separate projects), same sign as our estimate.
- Backtests that look amazing (one shows z = +20) come from pairing fresh exchange prices with stale Kalshi quotes. Our Lab 5 found no edge on the same idea once timing was aligned.

On "some people don't even know what they have exposed": yes, people leak API keys on GitHub. We did not look for any, saw none, and will not use any, ever. Using a leaked key is unauthorized access to someone's account (a crime), gets both accounts banned, and buys nothing: it is someone else's money to lose at the same prices, not a better price. Leaked Pyth keys are tied to a paid plan and get revoked. Nothing from any clone was run, installed or imported; everything was read as text and the clones were deleted.

The only glimmer, unproven: a 30-hour replay of a dumb two-sided resting maker on KXBTC15M earned +0.35c per posted quote (t = 0.83, so it could be zero), with the last 3 minutes of the window the best bucket (+2.71c per posted quote, n = 254) and back-of-queue fills doing better than front-of-queue. Markouts 30 seconds after a fill were negative in every bucket (-0.3 to -0.8c): fills get picked off, then part of it comes back by settlement. Two live records show the NO side doing better than YES (NO +7.6 points on 37 trades vs YES -22.7 points on 17; another bot's edge was NO-side only), and two academic studies say makers on contracts above 50c earn a small positive return after fees and retail overbets YES. These are hypotheses to test on our own tape, not strategies.

## 2. Shortlist: 8 things worth taking

Ranked by what helps our live bot soonest. Grade: A = real money, measured; B = backtest with code and honest method; C = claims with partial backing; D = plumbing or docs, no results.

**1. Check whether KXBTC15M makers pay a fee** (spencerfletcher/market-maker). Grade C for the repo, A once we run it ourselves.
- Copy: GET /trade-api/v2/series/KXBTC15M and read fee_type. "quadratic" = makers pay $0; "quadratic_with_maker_fees" = makers pay 1.75% x price x (1 - price), up to 0.44c per fill at 50c. Two repos say KX*15M makers pay $0 (Jul 1, 2025 schedule). Also compute fees in Decimal: 0.07 x 0.5 x 0.5 x 10,000 is 175.00000000000003 in floating point and a plain round-up charges the wrong cent.
- First test: run the GET today and compare with what our P&L model charges. If they differ, our "loses a few cents a window" number is off by up to 0.44c per fill.

**2. Score our maker the way three independent projects converged on** (aurascoper/brti-edge, ericsohel tape ADR 0014, 50thycal). Grade B.
- Copy: report fills as a BAND from three queue assumptions (everyone cancels ahead of you / 50% / everyone behind), and report BOTH 30-second markout and settlement P&L per posted quote, split by minutes-to-expiry (0-3, 3-6, 6-9, 9-12, 12-15) and hour of day. Pre-register hypotheses and a concentration gate (reject if more than about half the profit comes from one market).
- First test: re-score our existing fills and recorder tape this way. Pre-register two hypotheses before looking: (a) quotes posted in the last 3 minutes do better than earlier ones; (b) resting NO bids do better than YES bids. Open the test set once.

**3. The statistics kit** (hudsonjoshuaclark/kalshi-bot). Grade B.
- Copy: a "market-null" bootstrap (20,000 redraws using the price you paid as the win probability), a drift check (split P&L by whether BTC went up or down over the window), Bonferroni over every setting you tried, and a test set you open once.
- First test: run our current rule's P&L through it. If the money came only from windows where BTC fell (or only where it rose), the drift check fails and the rule is luck.

**4. Risk rails for the live bot** (mirabilis/lip-ledger, nikkowalow/klp, kel-reid, bkux33). Grade A for the lessons, D for the code.
- Copy: (a) measure losses from account balance changes, not from the bot's own fill counter: mirabilis's loss stop never tripped on fully swept orders, and they lost -$4.72 and -$6.00 in 23 seconds while a 1-3 second guard cancelled too late. Sweeps there came in bursts of 200-600 contracts, p99 about 6,000 in 10 seconds, with a follower bot adding 2-30k contracts within 17 seconds. (b) Kalshi's order-group limit: the exchange itself cancels all your orders if more than N contracts match in 15 seconds. (c) "Blind means flat": pull all quotes on any WebSocket gap until a fresh snapshot arrives. (d) Pull quotes for 30 seconds after a 6c mid move within 20 seconds. (e) A toxic-flow ladder: reduce, widen, pull, with cooldowns.
- First test: put our live orders in an order group with a cap this week and verify in demo that the exchange cancels when the cap is hit; add the balance-based loss stop.

**5. Kalshi API facts verified by others in 2026** (briancox730/unofficial-kalshi-api-docs, hughosh/lip, spencerfletcher). Grade D (docs); each item is checkable on the demo environment.
- Copy: the V2 order endpoint (since Jun 18, 2026) is YES-referenced; detect fills from GET /portfolio/fills or the WebSocket fill channel, not a single-order GET; positions lag fills by about 1 second; a cancel returning reduced_by = 0 means it had already filled; cancel 404 means the order is already gone (benign, our PR #14); WebSocket book deltas are fractional and must be accumulated exactly or you get phantom price levels and fake crossed books; the positions response key is market_positions; persist a reservation before every order write and treat a timed-out create as still live until resolved.
- First test: run each item against demo; feed our book builder a fractional delta; confirm our cancel path treats 404 and reduced_by = 0 correctly.

**6. Recorder design for task #90** (ericsohel/KalshiTradingProject tape). Grade D for trading; strong engineering evidence (317,217 of 317,389 book rebuilds matched the next keyframe, 99.95%; 32,472 of 32,710 REST audits passed).
- Copy: write raw frames to disk before parsing; one subscription per connection; on a sequence gap re-snapshot only that connection; keyframe every 5 minutes and audit against REST; judge liveness by a client ping every 10 seconds with a 20-second pong deadline, never by data silence (a data-silence timeout falsely killed quiet connections every 30 seconds).
- First test: add the ping-based liveness and the 5-minute keyframe audit, run 24 hours, report the rebuild match rate. Bonus: Strobingn/kalshi-odds-app's "scalper-data" release has 48 daily files of 1-second Kalshi 15-minute books, trades, settlements and Coinbase spot; after a format check (parse only, never execute) it could extend our tape history for free.

**7. Exact LIP scoring and a sweep-replay fill model, for the practice LIP desk (task #96)** (mirabilis/lip-ledger, nikkowalow/klp rewards.py). Grade A for the scoring: its payout model matched what Kalshi paid within 1-3% ($4.44 model vs $4.57 paid; $15.58 vs $15.73).
- Copy: reference price = first level where cumulative size reaches target/5; score = size x discount^ticks below reference; a second counts only if BOTH sides reach target; payout = pool x 0.5 x your share x counted fraction; $1 floor per program per day (this floor wasted about half of mirabilis's stints). Fill risk: replay recent public trades as sweeps against the quotes you would post, and rank markets by reward minus expected fill cost.
- First test: run the sweep replay on last week's public trades for the markets we would quote. Expect reward minus fill cost to come out negative (that confirms our LIP NO-GO). Only a clearly positive number, over several days, reopens the question.

**8. Honesty habits that caught other people's fake edges** (simonziervogel, SiddhaBasu, ryanfrigo). Grade B/C.
- Copy: fill at the executable price (YES ask for YES, 1 - YES bid for NO), never the midpoint; the midpoint inflated one project's edge by about half the spread per trade. Keep a forward-only TRACK_RECORD: implied win rate vs realized win rate, by side (YES/NO). Report Brier score with a confidence interval, not a point number. Add a quote-staleness feature (seconds since the Kalshi quote last changed, and BTC move since then). Run a feature-parity job that recomputes live features offline and flags drift.
- First test: add implied-vs-realized by side to our bot's daily report; confirm our P&L uses executable prices.

Left off the list: the Avellaneda-Stoikov makers (rodlaf 417 stars, kel-reid, bkux33, newyorkcompute) publish zero results; Kalshi's official repos are plumbing (use the OpenAPI yaml to regenerate our client when endpoints change, as they did Jun 18, 2026); TexasCoding's kalshi-sdk has the only public Kalshi FIX engine (tens of milliseconds faster than REST) if we ever need speed.

## 3. Pyth and FX feeds: the half-second test for $0

Where Pyth stands (measured Oct 13, 2026, about 5:00 PM):
- Since Aug 26, 2026, 9:00 AM, every Pyth price call needs a key. Hermes answered HTTP 401 on every price endpoint; only the feed list is open.
- The free back door (Pythnet plus a self-hosted Hermes) was shut down Sept 22, 2026. pythnet.rpcpool.com answered 403. Any repo promising free Pyth this way is dead.
- Benchmarks (history) has needed a key since July 24, 2026; the TradingView shim answered 404 for EUR/USD and BTC/USD. Lane 1 found a repo that used that shim for free gold history in September; Lane 2's live test says it no longer works. Treat free Pyth history as gone.
- On Solana, the free on-chain EUR/USD account was last updated Aug 24, 2026 (shard 0) and Sept 28 (shard 1): 50 days stale. BTC/USD and EURC/USD are updated about once every 55 seconds and arrive 1.3-1.6 seconds after publish. Useless for speed.
- The $500/month Starter plan is crypto only, with 1-second updates. EUR/USD by API is a Pro FX bundle: $2,500/month (G10) or $5,000/month (all FX). So "buy the Pyth key" is a $2,500/month decision, not $500, and that is more than the whole Kalshi stake.
- A free Pyth Terminal account comes with a trial key of unstated length. Fine for a few days of measurement, not for a bot.

The free trick: Kalshi settles its 15-minute FX markets (KXEURUSD15M, KXGBPUSD15M, KXUSDJPY15M, KXUSDCAD15M, KXAUDUSD15M) on Pyth, and each market's floor_strike IS Pyth's print at the window open, published free in the public API within about a minute. That is 96 exact Pyth FX samples a day for $0. Measured: the 5:00:00 PM window on Oct 13 had strike 1.12012; TrueFX at 5:00:00.4 PM quoted 1.12010/1.12013 (match within 0.05 pip); Kraken EUR/USD quoted 1.11991/1.11993 (2 pips below Pyth). Earlier strikes: 1.12008 (4:45 PM), 1.11982 (4:30), 1.11977 (4:15). (KXBTC15M settles on CF Benchmarks, not Pyth.)

Free feeds, measured 4:56-5:11 PM Oct 13, a quiet hour right after the 5 PM New York close (London and New York hours will be faster):

| Feed | Updates per second | Notes | Cost |
|---|---|---|---|
| TrueFX CSV (already in use) | EUR/USD 0.26/s, GBP/USD 0.42/s; median gap 2.2 s, worst 22.9 s | Matched Pyth within 0.05 pip; HTTP round trip 60 ms; its timestamps are fresh (about 18 ms old) | $0, personal use |
| Kraken EUR/USD websocket | 4.3/s; median gap 12 ms, worst 7.9 s | Moves with TrueFX within +/-0.2 s (neither leads); its level sat 2 pips off Pyth at the boundary | $0, no key, US-legal |
| OANDA practice stream | max 4/s in 250 ms buckets (docs, not measured) | Dealer quote, like Pyth's publishers; needs a free demo account and a token you make yourself | $0 |
| Pyth trial key | up to real-time if the trial allows | Time-boxed measurement only | $0, then $2,500/mo for FX |
| Bitstamp EUR/USD | 0.1/s, worst gap 79 s | Too thin | dead |
| Binance / Bybit EUR perps | blocked from the US (HTTP 451 / 403) | A VPN would break their terms | dead |
| Dukascopy | HTTP 429 "bot blocked" on the first request | | dead |
| Massive (ex Polygon) Currencies | real-time websocket only on the $49/mo tier | cheapest paid fallback | $49/mo |
| Twelve Data free | one quote per 7.5 s | | useless |

Recommended test (cost $0, 4-5 days):
- a) Record TrueFX (poll 5-10 times a second, keep TrueFX's own timestamp) and the Kraken EUR/USD websocket at 100 ms resolution around every :00 / :15 / :30 / :45 boundary, for EUR/USD, GBP/USD and USD/JPY. Add OANDA practice if you open a demo account and make the token yourself.
- b) After each window opens, pull the new market's floor_strike from Kalshi's public API. For each boundary, find the time offset at which the feed's mid best equals the strike. Over 300-500 boundaries (4-5 days) this pins the lead or lag of the free feed vs Pyth to about 0.1-0.2 seconds.
- c) In parallel, use the recorder to check whether Kalshi's own FX book moves within 0.5 seconds of a Kraken or TrueFX move. If the book already moves first, nobody at retail-feed speed has an edge.
- d) Treat any TrueFX quote older than about 1 second at the boundary as "unknown": in the quiet hour it went 10-23 seconds without a new quote.
- e) Only if (b) shows the free feed leading Pyth by 0.5 seconds or more should the $2,500/month key even be discussed, and a free trial key for a few days should confirm it first.

Honest expectation: Pyth's FX publishers are institutional market makers updating sub-second, and TrueFX matched Pyth to 0.05 pip at the one boundary measured. A free retail feed "knowing" Pyth half a second early is unlikely. The test is cheap, so run it before spending anything. If the offset comes out at zero or negative, the LIP idea stays NO-GO.

## 4. Kalshi vs Polymarket: verdict

The one thing that matters: there are two Polymarkets.
- Polymarket.com (global) settles its 15-minute BTC markets on a Chainlink 60-second average. US residents are not allowed to use it.
- Polymarket US (your account) settles "BTC Up or Down 15m" on CF Benchmarks BRTI with the exact Kalshi rule. 400 past windows checked (about Oct 9-13): identical settlement 400 of 400; the "price to beat" matched Kalshi's strike to the cent in all 25 checked (83,310.69 for 5:15 PM, 83,380.87 for 5:30, 83,535.87 for 5:45).

Kalshi vs Polymarket.com is NOT an arbitrage: they settled opposite ways in 7 of 399 windows (1.75%), every time when BTC moved $3.13 or less over the window (Oct 12, 5:30-5:45 PM: BRTI fell $2.55, Kalshi paid No, Polymarket.com paid Up). Near-ties are common: 30 of 400 windows moved $5 or less, 63 moved $10 or less; the median move was $46. And it is off-limits from the US anyway.

Measured gap, 40-minute capture 5:16-5:58 PM Oct 13, sampled every 2 seconds, public endpoints only:
- Kalshi vs Polymarket.com (809 paired samples, 3 windows): mid-price gap median 0.0c, average 0.9c; within 1c 58% of the time, within 2c 81%, over 3c 5.6%. Largest gap 9c at 5:45:22 PM, 22 seconds into the window. The two move together (same-second correlation 0.92); no measurable lead at any 2-10 second offset. Of 139 Kalshi jumps of 2c or more, Polymarket had already moved 27% of the time and followed within 6 seconds 62% of the time; the reverse was 39% / 50%. A fee-adjusted take-both-sides pair was positive in only 3.2-3.7% of samples (best 1.45c, and briefly 4.69c around 5:45 PM). Kalshi's top of book was about 10,700 contracts vs 500-600 shares on Polymarket.com: 20 times deeper.
- Kalshi vs Polymarket US (363 paired samples, 5:40-5:57 PM): raw gaps looked huge (up to 22c at 5:48:30 PM) but are an illusion. The public US gateway is a snapshot refreshed every 30 seconds (3 quote changes in 120 seconds while Kalshi changed 51 times; median staleness 15 seconds). At the 23 moments the US snapshot was fresh: average gap 1.4c, within 2c in 19 of 23, max 5c. A fee-adjusted locked pair was positive at 6 of 23 instants, best +1.26c, average -0.95c.

The math: two taker legs cost about 3.5c in fees at 50c (Kalshi 0.07 x P x (1-P), Polymarket US 0.0695) plus about 1.5c of spreads, against a fresh-quote gap that averaged 1.4c and never exceeded 5c. Cash sits on two exchanges for 15 minutes for a cent or two. Polymarket US's 1.25% maker rebate ends Mon Oct 19, 2026, 10:00 AM; after that makers get nothing unless they trade $10M a month.

Public cross-venue bots: seven read; the best grade is C (brandononchain, whose own 7-day simulation lost money in all three configurations and whose author says the simulator peeks at future prices). The rest: no results, flat 1c fee assumptions that overstate profit, or README-only repos. Juanp2389/Kalshi-trade-bot is a README plus a Windows zip binary that asks for your Kalshi and Polymarket keys: credential-stealer shape. Nobody publishes a live P&L for this pair.

Verdict: no visible edge with public data, and the public US feed is too stale to trade from. One more step, then close: use the authenticated Polymarket US WebSocket (market data lite) to log a live US best bid/offer for one day next to the Kalshi recorder, and count how many seconds a fee-adjusted locked pair of 1c or more existed with size on both sides. If that count is near zero, close this lane.

## 5. What NOT to do

- Do not use anyone else's leaked keys: Kalshi, Polymarket, Pyth, anything. It is unauthorized access to their account, breaks every terms of service, gets accounts banned, and gives no edge: it is someone else's money at the same prices. We saw none, sought none, and will not.
- Do not download or run Juanp2389's zip, or any closed binary that asks you to type in your keys.
- Do not pay for courses or gigs: the $15 "Build your own Kalshi bot" 5-part course, Fiverr "I will build a profitable Kalshi bot" gigs, the lek-orer/Bitbash README-only funnel (Telegram and WhatsApp contact, talks about "gas fees" on Kalshi), the polbots.com "126 bots vetted" directory (its own fine print: performance figures are whatever the author claims, not verified), TurbineFi's 5,732-backtest post (sells the backtester; its own data shows fees eating 146% of gross in one family), OctagonAI's CLI (paid research credits, telemetry on by default), LoQiseaking69's "quant-grade" bot (its "68.5% win rate, 1.8 Sharpe" are placeholder strings).
- Do not trust "risk-free" cross-venue arbitrage repos (CarlosIbCu 254 stars, ImMike 288 stars, TopTrenDev): different settlement indexes, fees ignored or wrong, legs not atomic, and matching markets by text similarity is how you lose both legs.
- Do not use Polymarket.com from the US, and do not VPN into Binance or Bybit for EUR perps.
- Do not buy the $500/month Pyth Starter plan expecting FX; it is crypto only. FX is $2,500/month, and the free test above comes first.
- Do not believe a backtest with z = +20, a midpoint fill, or a lag claim nobody measured ("Kalshi reprices 3-7 seconds after spot" is asserted, not shown; our own 2-second capture shows no lead).
- Do not trust star counts: muxprotocol had 1,300 forks on 224 stars (fork-spam shape) and is now gone; the 780-star weather bot's "$1.8k profit" is a simulation with a virtual bankroll.
- Do not re-test what has already lost in public: taking liquidity in 15-minute markets (-2.8 to -4.5c a contract), taker lock-ins in the last 90 seconds (-3.3c a trade on 5,550), buying the 90-99c side (wins exactly as often as the price says), small-account LIP (three losses), LLM-pick bots (no edge on 55 trades), buying YES+NO under $1 (not atomic; fees eat it).

## Safety and method notes

No credential, key or token was looked for, recorded, tested or used anywhere, and none was seen. Nothing from any clone was run, imported or installed; code was read as text only. All clones (about 190 MB in Lane 1, three small ones in Lane 2, seven in Lane 3) were deleted when each lane finished (Lane 1 by 5:08 PM Oct 13). Nothing was written to the project repo. Scripts and raw captures remain in the scratchpad folder github_sweep/work (feed cadence scripts and tick files, the Solana decode script, the lead/lag script, the Kalshi-vs-Polymarket captures and analyses, the 400-window settlement comparison).

Method limits: the session proxy blocks api.github.com and raw GitHub HTML, so star counts and dates come from page summaries and the clones' git logs. Feed cadences come from one quiet 10-minute window. Lane 3's Kalshi capture lost the 5:30-5:40 PM stretch to a lookup bug (fixed for the rest). Kalshi's fee PDF kept returning "too many requests", so the KXBTC15M maker fee was not re-verified; shortlist item 1 does that.

---
Note to the orchestrator: the write to /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/github_sweep/REPORT.md was blocked by the subagent file policy; the text above is the complete report and can be saved to that path by the caller.

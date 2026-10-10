# Accounts and data providers

The owner's accounts with outside services, what each is for, and the limits to watch.
**Keys never go in this repo.** They live in the cloud environment's *Network secrets* (or
Railway variables when deployed) under the variable names below.

| Service | Owner has account | Plan | Used for | Variable | Free-tier budget to track |
|---|---|---|---|---|---|
| Helius (helius.dev) | Yes (created 2026-10-08, kept for possible future subscriptions) | Free | Bot's Solana RPC on Railway (`SOLANA_RPC_URL`), research spot checks, priority-fee estimates, `getTransactionsForAddress` (works on free, oldest-first) | `HELIUS_API_KEY` | 1M credits per month |
| Dune (dune.com) | Yes | Free, API is paid-only (account showed 0 included credits on 2026-10-08) | Not used | — | — |
| Jupiter (portal.jup.ag) | Yes (key verified 2026-10-08 on `api.jup.ag`: Ultra order + Price v3 OK) | Free key | Bot swaps and quotes; with a key the bot uses `https://api.jup.ag` instead of the retiring `lite-api.jup.ag` | `JUPITER_API_KEY` (the secret `jup_…` key) | Response headers showed 100 requests per rate window |
| Jupiter publishable key | Yes (`jup_pub_…`, verified 2026-10-08) | Free | Not used by the bot. Meant for public web pages or widgets; only ~5 requests per rate window | — | — |
| Alchemy (alchemy.com) | Not yet | Free | Optional research backup for full transaction history | `ALCHEMY_API_KEY` | 30M compute units per month |
| Anthropic (console.anthropic.com) | Yes (key created 2026-10-09; the owner pasted it in chat, so it is exposed: **delete it in the console now that the Desk exam is over** and make a new one if the bot's AI judge is ever switched on) | Pay per use (prepaid credits; $25 bought) | **The Desk** lab exam, finished 2026-10-09 (`research/lab2/k1.py`; decisions cached under `research/lab2/K1/decisions/`, re-runs cost nothing): $10.32 spent, result UNDERPOWERED (the Desk never bought). Later, optionally, the bot's AI judge ("Jev") | `ANTHROPIC_API_KEY`: only ever in a process environment or a Railway variable, never in a file or the repo | Prepaid credits: ~$14.7 left of $25 after the exam; the Desk's per-decision cost was ~$0.005 panel, ~$0.0022 solo-Sonnet, ~$0.00012 solo-Haiku |
| CryptoHouse (crypto.clickhouse.com) | No account needed | Free, public | Main research source for historical pump.fun trades | — | ~90 queries/hour per IP (shared through the proxy) |
| pump.fun swap API (swap-api.pump.fun) | No account needed | Free, public, behind Cloudflare | Fallback 1m candles (`sources/pumpfun.py`). Per-coin trade history for the live trade-flow features (`sources/pumpfun_trades.py`, not wired yet) | — | ~12-20 requests/min per IP, shared by both clients: the engine's host bucket (12/min, burst 3) caps candles and trades together; trades add their own 8/min cap and take a shared token only while 2 remain, so a candle request never waits on them. A 429 means cool down for `Retry-After`; timeouts, 5xx and challenge pages back the host off 15 s, doubling. The origin also reports `x-ratelimit-limit: 1000`. Each trades page holds at most 100 trades, and a fresh graduate trades 300-1,500 times a minute |
| Coinbase Exchange public market data (api.exchange.coinbase.com) | No account needed | Free, public, no key | The trend desk's daily candles (BTC-USD, ETH-USD, SOL-USD), the same source lab 3 researched on | — | About 3 requests a day (one per coin, at start-up and once after 00:05 UTC; more only to catch up after a pause or on a retry); the public limit is about 10 requests a second per IP |
| Polymarket US (polymarket.us, QCX LLC, CFTC-regulated) | Yes (account created 2026-10-09; the owner funded it with **$25** on 2026-10-09; sports contracts available to the owner). API key created 2026-10-09; the owner shared it as a screenshot in chat and asked for it to be stored, so it is **exposed**: rotate it in the app before funding if in doubt | Free (no subscription; taker fee 0.0695 x contracts x p x (1-p), read per market as `feeCoefficient`) | The prediction-market desk. Market data is PUBLIC (gateway.polymarket.us, no key, 20 req/s per IP); the key is only for orders, positions and balances, i.e. real money. **Live from 17:27 to 17:43 UTC on 2026-10-09** at the owner's explicit instruction (before any lab4 TEST pass: the owner chose to go live with $25 and hard caps), then **switched back to paper by the assistant** (`POLYDESK_MODE=paper`) when two things surfaced: the venue filled 8 IOC buys (8 contracts, $7.80) that the desk had logged as "no fill" (its order-reply parsing missed fills, so its open-money cap counted nothing; fixed the same day: the desk now reads the venue's positions every round and adopts what it holds), and the paper rule lost 60 % of 114 settlements (it read a wide book's ask as a belief; fixed with a 0.03 max spread). Lab 4 TRAIN (2026-10-09) found NO EDGE for the rule in any cell, so real money stays off until the owner says otherwise; the 8 contracts settle at the venue and are tracked by the desk. Caps in code: 1 contract per order, at most $10 of real money open at once, a $3 daily loss stop (no more real buys that day) and a $10 total loss stop (back to paper for good until the desk state is reset). Long side only; the desk connects only after a successful balance read, and a rejected key leaves it on paper with the reason on the panel | `POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY`: **set on the Railway service `bot` (production) on 2026-10-09 16:05 UTC**, transcribed from the screenshot and **verified by the first authenticated balance read on 2026-10-09 17:27 UTC** ($22.10 cash); never in the repo. `POLYDESK_LIVE_CONFIRM` stays set; `POLYDESK_MODE` was `paper` from 2026-10-09 17:43 UTC and is **`live` again since 2026-10-10 ~04:35 UTC at the owner's explicit "Go, make it real money now"** (caps unchanged: 1 contract per order, $10 open, $3 daily loss stop, $10 total loss stop, plus the risk manager's pause; the rule's lab 4 verdict is still NO EDGE). Set it back to `paper` to switch real money off, then trigger a build: a variable change alone deploys the wrong branch, see the Railway row. `POLYDESK_GUARD` (default on, added 2026-10-09): the desk's risk manager pauses new paper and real buys while the current rule's own record is losing (95 % sure, or 99 % sure as an early stop from 10 events; a rule is its version plus `POLYDESK_THETA`, `POLYDESK_HOURS` and the max spread, so changing either starts a fresh record; a game's markets count as one event; P&L per dollar at risk), keeps the paper book at 10 open until the record is winning, and flags a winning paper record for the owner, never as a candidate for real money while lab 4 has not passed the rule; it never switches real money on; `off` is the owner's switch (`POLYDESK_GUARD_MIN_N` 30 and `POLYDESK_GUARD_WIN_N` 100 events are its thresholds; a WIN_N below MIN_N is raised to it) | None to track (no usage billing) |
| Railway (railway.com) | Yes. Project `nightcrawler`, service `bot`, volume `nightcrawler-data` at `/data`, domain `bot-production-9d67.up.railway.app` (created 2026-10-08, paper mode) | Hobby (~$5/month expected). **No volume backups on this plan** (`maxBackupsCount: 0`, checked 2026-10-09); Pro (~$20/month) would allow scheduled backups | Hosts the bot 24/7; deploys branch `claude/nightcrawler-memecoin-bot-Gwnb1S`. Pushes do NOT auto-deploy: a deploy is triggered by reconnecting the service source (Railway MCP `connect-service-source`). A variable change starts a redeploy that fails within seconds (the environment's source has no branch, so it builds the repo's default branch, which holds no app code; seen 2026-10-09 17:23 UTC): the running deployment is unaffected, and the new variables take effect on the next `connect-service-source` build | Service variables hold `JUPITER_API_KEY`, `SOLANA_RPC_URL` (Helius), `DASHBOARD_TOKEN`, `BOT_WALLET_MODE=generated`, `POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY`, `POLYDESK_MODE`, `POLYDESK_LIVE_CONFIRM`, `ODDS_API_KEY` | Watch monthly usage in the Railway dashboard |
| The Odds API (the-odds-api.com) | Yes (key verified 2026-10-09 20:02 UTC: sports list and a historical Pinnacle snapshot both OK). The owner pasted the key in chat, so it is **exposed**: regenerate it in the account if in doubt | Paid plan (about 5M credits a month; historical odds included) | Lab 6, the sports specialist: Pinnacle's sharp no-vig odds vs Polymarket game prices (`research/lab6`). Research reads the key from a private scratch file at run time, never from the repo | `ODDS_API_KEY`: **set on the Railway service `bot` (production) on 2026-10-09 20:03 UTC with deploys skipped** (takes effect on the next build); never in the repo | ~4.99M credits remaining on 2026-10-09; a historical call costs 10 credits per region per market; lab 6 is capped at 300,000 credits |
| Higgsfield (higgsfield.ai) | Yes | Plus (credits) | The cast and props in 3D (art/CAST_3D.md): 659.25 credits spent on 2026-10-09 (characters, rigs, 21 moves, 12 props) | — (used through the assistant's connector, no key in the bot) | 344.49 credits left on 2026-10-09 |

## The trend desk (paper only)

The trend desk (`src/nightcrawler/trenddesk.py`; `TRENDDESK_ENABLED`, `TRENDDESK_SLEEVE_USD`) is a paper forward test
of lab 3's only consistently positive rule, "sma50" trend following on BTC, ETH and SOL: hold a coin while its daily
close is above its 50-day average, else cash. It reads Coinbase's public daily candles once a day (no account, no key)
and keeps a pretend $100 book from the day it first ran; it has no broker, no swap, no key and no wallet, so no real
money can move through it, and the page labels it "Paper money (pretend)" everywhere. The book is kept the way a real
account would keep it: each coin has its own third, a sell puts that coin's money in its own cash and a buy spends
only that cash, and nothing is moved between the thirds. Lab 3's own figures assume the book is put back to equal
thirds every day for free; the desk keeps those only as "lab 3's way", for comparison with the lab, because that free
re-balancing alone can decide who is ahead (on lab 3's data from 2023-06-15 to 2026-10-08 the rule's three-thirds
book ended at $370 against $402 for holding the three bought once, while the lab's re-balanced figures showed the
rule ahead, $393 against $377). Real money would need all of this first: a full year (365 days) of the desk's own
forward paper results, booked day by day from its start date, in which the rule's three-thirds book beats holding the
three (bought on day one and never touched, same costs) over the same days and with a smaller worst drop; that year
read against lab 3's pre-registered bar (its 2026 TEST look failed it: promising, under-powered); and the owner's
explicit go after reading it. Even then it would be a new, separately built and capped real-money path, with any key
only in a Railway variable, never in this repo.

## Config notes

- `OWNER_TZ` (default `America/Los_Angeles`; no account, no key): the owner's time zone, an IANA name such as
  `Europe/Athens`. The 3D world's nightly recap film (`src/nightcrawler/recap.py`, `/api/page` -> `recap`) replays
  "yesterday", the previous calendar day of this zone, from the bot's own records only (the ledger and its receipts),
  and plays by itself at 00:05 in this zone when the page is open. A zone name the machine does not know is logged
  as a warning at start (`config_owner_tz_unknown`) and never stops the bot: the recap then uses the UTC day and says
  `"tz": "UTC"`, as it does on a machine with no time-zone database at all. Change it in the Railway variables when
  the owner moves.

## Keeping track

- Check provider usage before any heavy research run, and prefer the free CryptoHouse source so Helius
  credits stay available for the live bot.
- If the owner ever buys a subscription, update the plan and budget columns here.
- Keys that were pasted into a chat should be replaced with fresh ones before the bot trades real money.
- Bot wallet: with `BOT_WALLET_MODE=generated` the bot makes its own wallet and its key exists ONLY on the
  Railway volume (`/data/wallet/bot-keypair.json`); no variable, chat or file in this repo holds it. The owner
  funds it from Phantom (Send, SOL, the address on the dashboard) and takes it back with `WITHDRAW_TO`. Never
  delete the `nightcrawler-data` volume or the service while SOL is in that wallet: withdraw first.
- Bot wallet created on Railway 2026-10-09 04:13 UTC. Public address (safe to share):
  `AfRcUJ9vP5JrA66UMHV4LeGHfWZKzFKep7tRdaZm5c8W`. Owner's decision (2026-10-09): keep it, with no volume
  backups, holding only about $100 and withdrawing to Phantom when needed; revisit Pro backups if the balance
  grows.

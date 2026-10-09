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
| Anthropic (console.anthropic.com) | Not yet | Pay per use | Optional AI judge ("Jev") | `ANTHROPIC_API_KEY` | Capped by `JUDGE_MAX_DAILY_USD` |
| CryptoHouse (crypto.clickhouse.com) | No account needed | Free, public | Main research source for historical pump.fun trades | — | ~90 queries/hour per IP (shared through the proxy) |
| pump.fun swap API (swap-api.pump.fun) | No account needed | Free, public, behind Cloudflare | Fallback 1m candles (`sources/pumpfun.py`). Per-coin trade history for the live trade-flow features (`sources/pumpfun_trades.py`, not wired yet) | — | ~12-20 requests/min per IP, shared by both clients: the engine's host bucket (12/min, burst 3) caps candles and trades together; trades add their own 8/min cap and take a shared token only while 2 remain, so a candle request never waits on them. A 429 means cool down for `Retry-After`; timeouts, 5xx and challenge pages back the host off 15 s, doubling. The origin also reports `x-ratelimit-limit: 1000`. Each trades page holds at most 100 trades, and a fresh graduate trades 300-1,500 times a minute |
| Railway (railway.com) | Yes. Project `nightcrawler`, service `bot`, volume `nightcrawler-data` at `/data`, domain `bot-production-9d67.up.railway.app` (created 2026-10-08, paper mode) | Hobby (~$5/month expected). **No volume backups on this plan** (`maxBackupsCount: 0`, checked 2026-10-09); Pro (~$20/month) would allow scheduled backups | Hosts the bot 24/7; deploys branch `claude/nightcrawler-memecoin-bot-Gwnb1S`. Pushes do NOT auto-deploy: a deploy is triggered by reconnecting the service source (Railway MCP `connect-service-source`) | Service variables hold `JUPITER_API_KEY`, `SOLANA_RPC_URL` (Helius), `DASHBOARD_TOKEN`, `BOT_WALLET_MODE=generated` | Watch monthly usage in the Railway dashboard |

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

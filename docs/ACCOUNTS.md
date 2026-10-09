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
| Railway (railway.com) | Yes. Project `nightcrawler`, service `bot`, volume `nightcrawler-data` at `/data`, domain `bot-production-9d67.up.railway.app` (created 2026-10-08, paper mode) | Owner's plan (~$5/month expected) | Hosts the bot 24/7; deploys branch `claude/nightcrawler-memecoin-bot-Gwnb1S`, redeploying only on `src/**`, `pyproject.toml`, `Dockerfile`, `railway.json`, `README.md` | Service variables hold `JUPITER_API_KEY`, `SOLANA_RPC_URL` (Helius), `DASHBOARD_TOKEN` | Watch monthly usage in the Railway dashboard |

## Keeping track

- Check provider usage before any heavy research run, and prefer the free CryptoHouse source so Helius
  credits stay available for the live bot.
- If the owner ever buys a subscription, update the plan and budget columns here.
- Keys that were pasted into a chat should be replaced with fresh ones before the bot trades real money.
- Bot wallet: with `BOT_WALLET_MODE=generated` the bot makes its own wallet and its key exists ONLY on the
  Railway volume (`/data/wallet/bot-keypair.json`); no variable, chat or file in this repo holds it. The owner
  funds it from Phantom (Send, SOL, the address on the dashboard) and takes it back with `WITHDRAW_TO`. Never
  delete the `nightcrawler-data` volume or the service while SOL is in that wallet: withdraw first.

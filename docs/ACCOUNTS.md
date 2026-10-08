# Accounts and data providers

The owner's accounts with outside services, what each is for, and the limits to watch.
**Keys never go in this repo.** They live in the cloud environment's *Network secrets* (or
Railway variables when deployed) under the variable names below.

| Service | Owner has account | Plan | Used for | Variable | Free-tier budget to track |
|---|---|---|---|---|---|
| Helius (helius.dev) | Yes (created 2026-10-08, kept for possible future subscriptions) | Free | Bot's Solana RPC on Railway (`SOLANA_RPC_URL`), research spot checks, priority-fee estimates, `getTransactionsForAddress` (works on free, oldest-first) | `HELIUS_API_KEY` | 1M credits per month |
| Dune (dune.com) | Yes | Free, API is paid-only (account showed 0 included credits on 2026-10-08) | Not used | — | — |
| Jupiter (portal.jup.ag) | Not yet | Free key | Bot swaps and quotes once `lite-api.jup.ag` is retired | `JUPITER_API_KEY` | 1 request/s |
| Alchemy (alchemy.com) | Not yet | Free | Optional research backup for full transaction history | `ALCHEMY_API_KEY` | 30M compute units per month |
| Anthropic (console.anthropic.com) | Not yet | Pay per use | Optional AI judge ("Jev") | `ANTHROPIC_API_KEY` | Capped by `JUDGE_MAX_DAILY_USD` |
| CryptoHouse (crypto.clickhouse.com) | No account needed | Free, public | Main research source for historical pump.fun trades | — | ~90 queries/hour per IP (shared through the proxy) |

## Keeping track

- Check provider usage before any heavy research run, and prefer the free CryptoHouse source so Helius
  credits stay available for the live bot.
- If the owner ever buys a subscription, update the plan and budget columns here.
- Keys that were pasted into a chat should be replaced with fresh ones before the bot trades real money.

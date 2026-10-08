# Running nightcrawler on Railway

[Railway](https://railway.com) runs the bot 24/7 in the cloud, and you control it from a
phone browser. Everything here is for **paper mode**, which needs no wallet and no API keys.
Going live afterwards is a separate, deliberate step: see [GOING_LIVE.md](GOING_LIVE.md).

> These are instructions only. Nothing has been deployed for you.

## What it costs

- **Railway Hobby plan: $5/month,** which includes $5 of usage. New accounts get a one-time
  $5 trial credit (30 days, no card).
- The bot is light: one small Python process (roughly 100-200 MB of memory, little CPU) plus
  a small database. That should fit within the included $5, but check **Usage** in Railway
  after the first week. Railway bills about $10 per GB-month of memory, about $20 per
  vCPU-month, and about $0.15 per GB-month of volume storage.
- Optional extras: the AI judge (Anthropic API, about 1.5 cents per call, capped at
  `JUDGE_MAX_DAILY_USD`, default $1/day) and a Helius RPC key (free tier).

## Deploy in 8 steps (all doable on a phone)

**1. Sign in.** Go to [railway.com](https://railway.com) and sign in with GitHub.

**2. New project from this repo.** **New Project**, then **Deploy from GitHub repo**, then
pick this repository (allow Railway to access it if asked). Railway finds the `Dockerfile` and
builds it automatically. The image already includes everything, including the live-trading
and AI-judge extras. It starts with `nightcrawler run`.

**3. Add a volume at `/data`.** This is where the ledger (positions, receipts, P&L) lives.
Without it, every redeploy wipes the bot's memory.
- Open the project canvas, then **+ Create** (or right-click the canvas, or the command
  palette), then **Volume**, and connect it to the nightcrawler service.
- Set the **mount path** to `/data`.
- One volume per service. The Hobby plan allows up to 5 GB, and the bot uses a few MB a day.

**4. Set the variables.** Open the service, go to **Variables**, then **Raw Editor**, and paste
this, replacing the token with your own long random string:

```
DATA_DIR=/data
RAILWAY_RUN_UID=0
RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30
DASHBOARD_TOKEN=change-me-to-a-long-random-password-1234567890
TRADING_MODE=paper
```

- `RAILWAY_RUN_UID=0` is required. Railway mounts volumes as root, and the image runs as a
  non-root user, so without this the bot can't write to `/data`. The error message says so
  if you forget.
- `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30` gives the old container 30 seconds between "please
  stop" (SIGTERM) and the hard kill. Railway's default is **0 seconds**, and every variable change
  is a redeploy: without it, a deploy can kill the bot in the middle of a swap. The bot finishes
  the step it is on and stops cleanly. (It also writes a marker before every live swap, so even a
  hard kill is reconciled against the wallet on the next start, but a clean stop is better.)
- `DASHBOARD_TOKEN` protects the dashboard. Use 30+ random characters; a password manager
  can generate one.
- Don't set `PORT`: Railway sets it, and the dashboard and health check use it.
- Optional: `ANTHROPIC_API_KEY` (turns on the AI judge), `SOLANA_RPC_URL` (Helius URL),
  `JUPITER_API_KEY`. Every other setting is listed in [.env.example](../.env.example).

**5. Health check, restart policy, one replica.** In the service **Settings**:
- **Healthcheck Path:** `/healthz`
- **Restart Policy:** On Failure
- **Replicas:** 1. Never more than one: two bots on one ledger would fight. Railway doesn't
  allow replicas with a volume anyway.
- **Draining time:** 30 seconds (the same as `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` above).

Why by hand: the repo has a `railway.json` with these values, but Railway has deprecated
config-as-code files. New services may ignore it, and existing ones stop reading it on
2026-12-01. Setting them in the dashboard always works.

**6. Deploy.** Press **Deploy** (Railway shows your edits as staged changes until you do).
The first build takes a few minutes. When the health check passes, the deployment turns
green.

**7. Make the dashboard reachable.** **Settings**, then **Networking**, then **Generate
Domain**. Railway gives you a URL like `https://nightcrawler-production-xxxx.up.railway.app`.

**8. Open it on your phone:**

```
https://<your-domain>/?token=<your DASHBOARD_TOKEN>
```

The page removes the token from the address bar after it loads and remembers you with a
cookie for 30 days. Bookmark the page *after* it loads, or add it to your home screen. It
refreshes every 15 seconds and is read-only: nothing on it can trade.

## What you'll see

- A big **PAPER** badge (a red **LIVE** one in live mode).
- **Engine running · Xs ago:** the heartbeat. If it says "stopped", check the logs.
- Equity, today's and all-time P&L, an equity chart, open positions and recent trades.
- **Why coins were skipped:** counts of rug-filter rejections by rule (top-10 holders,
  insiders, LP unlocked ...).
- **Receipts:** the head hash, the receipt count and "verified". Tap "what is this?" for the
  explanation.

Expect hours with no trades. The bot is strict on purpose: coins must be at least 1 hour old,
pass the rug filter, and then show the dip-rebound setup.

## Logs

Open the service, go to **Deployments**, pick the active deployment, then **View Logs**.
One line per event, for example:

```
crawler_poll fetched=118 emitted=1 rejected=16 nursery=59
cocoon_reject mint=... symbol=XYZ reasons=[top10] top-10 holders own 52.1% (max 30%)
watch_add mint=... symbol=ABC warnings=1
paper_fill side=buy mint=... sol=0.186000 SOL ...
position_close id=pos_... reason=trailing_stop ...
http_retry host=api.geckoterminal.com why=status=429 ...
```

`http_retry ... 429` lines are normal now and then: the free data APIs limit how fast anyone
can ask. The bot slows down and carries on. Secrets never appear in the logs.

## Everyday controls (Variables, then Deploy)

| You want to... | Set |
|---|---|
| Stop new buys, keep managing open positions | `KILL_SWITCH=stop` |
| Sell everything now, then stop | `KILL_SWITCH=sell_all` (`sell-all` and `sell all` work too; any word the bot does not know means `stop`, never "refuse to start") |
| Resume normal trading | `KILL_SWITCH=off` |
| Clear a drawdown halt (after thinking it over) | `RESET_HALT_TOKEN=<any new value, e.g. 2026-10-20>` |
| Try different settings | edit the variable, e.g. `MAX_OPEN_POSITIONS=2` |

Every variable change needs a **Deploy**, which restarts the bot. Open positions, balances
and receipts survive restarts because they're on the volume. The watchlist is rebuilt within
minutes. If you run `nightcrawler sell-all` in a shell while the bot is running, it does not
trade itself: it writes `sell_all` into `/data/KILL` and the running bot sells (two processes
trading one ledger would race). Write `off` into that file, or delete it, to resume.

## Updating to a newer version

Push or merge to the GitHub branch Railway watches (usually `main`). Railway rebuilds and
redeploys on its own. Because the service has a volume, Railway stops the old container
before starting the new one, so there's a short downtime (well under a minute). That's
deliberate: two bots never run at once on the same ledger. Your data stays on the volume.

To roll back, go to **Deployments**, open an older deployment, and choose **Redeploy**.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Logs: `cannot open ledger ... set the service variable RAILWAY_RUN_UID=0` | Add `RAILWAY_RUN_UID=0`, then Deploy. |
| Deploy fails the health check | Is the Healthcheck Path exactly `/healthz`? Did you leave `PORT` unset? Check the logs for a config error. |
| Logs: `Invalid configuration: ...` and the bot exits | A variable has a wrong value. The message names it and gives a hint (e.g. `POSITION_PCT` is a fraction: 0.20, not 20). |
| Dashboard shows "401" / a locked page | Open it once with `?token=<DASHBOARD_TOKEN>`. |
| P&L and positions reset after a deploy | The volume is missing or not mounted at `/data`, or `DATA_DIR` isn't `/data`. |
| Live mode refuses to start | Expected unless `TRADING_MODE=live`, `LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK` and a valid `BOT_WALLET_SECRET` are all set. See [GOING_LIVE.md](GOING_LIVE.md). |

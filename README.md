# nightcrawler

An honest, provable Solana memecoin bot. It finds brand-new coins, throws out the obvious
rugs, waits for a specific price pattern, and trades with **pretend money first**. Every
decision it makes is sealed in a tamper-evident log *before* the outcome is known, so nobody
(including you) can edit the results afterwards.

It was built to test the viral "crawler + Jev judge + Grok bots" posts honestly.

> **Read this first.** This is not a money machine.
>
> - **No profit is promised.** On the two nights the viral posts showed off, this bot's
>   default strategy **lost money** (HIGGS -$8.32, HOOKI -$26.10 on a $100 start). The posts'
>   own numbers did not hold up when checked against real price data. See
>   [docs/FACTCHECK.md](docs/FACTCHECK.md) and [docs/backtests/README.md](docs/backtests/README.md).
> - About 98 % of pump.fun coins end up as pump-and-dumps. AI "judges" have shown no proven
>   edge on memecoins, and any edge that does appear tends to fade within weeks.
> - With $100, fees and slippage eat **about 1-3 % of every position on every round trip**
>   (details below). Most strategies will not beat that.
> - If you ever switch to real money, assume you can lose **all** of it.
>
> Nothing here is financial or tax advice.

---

## What it does, in plain words

Think of a night shift with six workers:

| Step | Worker | What it does |
|------|--------|--------------|
| 1 | **Crawler** | Every 30 s it reads the newest and trending Solana coins from Jupiter and DexScreener (GeckoTerminal's new-pools feed is optional, `DISCOVER_GT_NEW_POOLS`, so its small free budget is kept for price candles). Coins younger than 1 hour, or that left their bonding curve less than 30 minutes ago, wait in a "nursery" until they are old enough. Cheap checks drop coins that are too old, too small, too illiquid or made by serial launchers, and every coin outside the universe the bot was tested on: only pump.fun graduates traded against SOL (no other launchpads). |
| 2 | **Cocoon** (rug filter) | Checks each survivor with RugCheck, the Solana blockchain itself and Jupiter Shield. It **fails a coin** if: someone can still mint or freeze tokens; it has dangerous token features (transfer tax, hooks, permanent delegate); a few wallets own too much; the creator still holds a lot; an insider network holds a lot; the creator is a serial launcher; the pool's liquidity isn't locked; it is a "Mayhem mode" coin (2 billion tokens instead of 1, never tested). If any check *can't be done* (a service is down), the coin fails too. It also *warns* (never fails) about copycat tickers and names that imitate a brand or celebrity. |
| 3 | **Watchlist + strategy** | Up to 15 coins that passed are watched for up to 6 hours. The bot looks for one setup only, the "dip-rebound": the price fell at least 55 % from its recent high, then two closed green 1-minute candles show buyers coming back, and recent buys outnumber sells. Price candles come from GeckoTerminal; for pump.fun coins, from pump.fun itself when GeckoTerminal is rate-limited or behind (never a mix of both). |
| 4 | **Radar** | Right before buying, checks the last 15 minutes of big trades: if the creator, an insider or a top holder is dumping, or big sells are draining the pool, **no buy**. It keeps watching open positions too. |
| 5 | **Judge** ("Jev") | Optional. An AI (Claude, through your Anthropic API key) sees the facts and must answer yes/no **with reasons**. It only runs after every hard rule passed, can only say no to a trade (never force one), and errors count as "no". A coin's name and ticker are written by anonymous creators, so the judge only sees them cleaned, cut short and marked as untrusted. Off by default (no key needed). |
| 6 | **Broker** | Asks Jupiter for a real quote at the exact size. In **paper mode** the fill is that quote's exact amount minus the real fees: it is the same quote live mode would sign. In **live mode** it signs the transaction with the bot wallet and sends it. |

Then: **exits.** Sell half at +40 %. After that, sell the rest if the price drops 15 % from
its peak. Sell everything at -18 %, after 2 hours, or when the radar sees insiders dumping.

And always: **receipts.** Every decision ("watch this", "reject: top-10 holders own 52 %",
"buy", "sell") and every fill goes into a hash chain *before* the bot looks at any newer
price. Each receipt contains the fingerprint (hash) of the one before it, so changing or
deleting anything later breaks the chain, and `nightcrawler receipts verify` will say where.
The latest fingerprint (the "head hash") is on the dashboard. If you post it somewhere public,
you have committed to your entire history up to that moment.

## Paper mode first (the default)

Paper mode starts with a pretend $100. It uses **live Jupiter quotes** at the real size,
the real 0.1 % Jupiter fee, the pool's real fees and price impact, a network-fee model and
the ~$0.20 token-account deposit. The **only** difference from live mode is that nothing is
signed or sent. That makes paper results a fair preview, though never a promise: live fills
can still slip a little more.

Run it on paper for at least 1-2 weeks. Then run `nightcrawler report` (or look at the
dashboard) and ask: after all costs, did it make money over **dozens** of trades, not just
one lucky one? If not, don't go live. [docs/GOING_LIVE.md](docs/GOING_LIVE.md) has the full
checklist.

## The honest cost math at $100

Each position is 20 % of the bankroll, capped at $25, so about **$20**.

| Cost per round trip (buy + sell) | Typical size | On a $20 position |
|---|---|---|
| Jupiter Ultra platform fee, 0.1 % per side | 0.2 % | $0.04 |
| Pool fee: PumpSwap 0.3-1.25 % per side; pump.fun bonding curve 1.25 % per side | 0.6-2.5 % | $0.12-$0.50 |
| Price impact (small for $20 in a $30K+ pool, big in thin pools) | 0.1-2 % | $0.02-$0.40 |
| Network fees (~0.0003 SOL per swap) | ~0.3 % | ~$0.06 |
| Token-account deposit (~0.002 SOL per coin; Jupiter's sell leaves the emptied account open, so it is **not** refunded) | ~1 % | ~$0.20 |

**Measured live on 2026-10-08:** buying 0.1-0.2 SOL of a liquid memecoin (HIGGS) and selling
it immediately lost **0.9-2.2 %** of the position before network fees, about **1.2-1.5 %**
after. Over a whole round trip, plan on **1-3 %**, and more on thin coins.

So a strategy has to win, on average, more than about 2 % per trade *after* its losers
just to break even. Five round trips a day cost about 1-3 % of the whole bankroll per day.
That's why the filters are strict, and why on most days the bot buys nothing at all.

Running it costs money too: Railway is about $5/month. The AI judge is optional, about
1.5 cents per call, and capped at $1/day by default.

## Quick start

**On a phone, with Railway (recommended):** follow [docs/RAILWAY.md](docs/RAILWAY.md). You
connect this GitHub repo to Railway, add a storage volume, set a few variables and open the
dashboard link. Paper mode needs no wallet and no API keys.

**On a computer (Python 3.11+):**

```bash
pip install -e ".[live,judge]"   # or just: pip install -e .   (paper mode only)
cp .env.example .env              # optional: edit settings
nightcrawler scan                 # one-shot: what would it look at right now?
nightcrawler run                  # paper trading + dashboard on http://localhost:8080
```

## Commands

| Command | What it does |
|---|---|
| `nightcrawler run` | Run the bot and the dashboard (this is what Railway runs). |
| `nightcrawler scan [--limit N] [--json] [--include-young]` | One look at the market: candidates and why each one passed or failed the rug filter. Never trades. |
| `nightcrawler backtest PATH [--from T --until T] [--sweep --grid JSON] [--json OUT]` | Replay 1-minute candles through the same strategy with pessimistic costs and no lookahead. Try `data/samples/`. |
| `nightcrawler collect [--pools N --hours H --min-age-h H]` | Build an unbiased dataset (every new pool, including the ones that later rugged). Run it hourly; the first runs only record a census. |
| `nightcrawler report [--json]` | Profit and loss per trade and per day, checks the books against the wallet, verifies receipts. Exit code 4 means a problem was found. |
| `nightcrawler receipts head` / `verify` / `export FILE` | Show the head hash, re-check the whole chain, or export it as a file anyone can verify. |
| `nightcrawler wallet new` | Make a fresh bot wallet and show its secret **once** (Phantom's own "create account" works just as well). |
| `nightcrawler wallet show` | The bot wallet's address and balances (never the secret). |
| `nightcrawler sell-all [--yes]` | Sell every open position now (beside a running bot it writes `sell_all` into `DATA_DIR/KILL` and lets the bot sell). |
| `nightcrawler reset-halt [--yes]` | Clear a drawdown halt (also possible from Railway with `RESET_HALT_TOKEN`). |
| `nightcrawler config [--json]` | Show the settings in use (secrets are never shown). |
| `nightcrawler dashboard` | Serve only the dashboard, without trading. |
| `nightcrawler learn status [--json]` | What the learning loop has recorded, which strategy versions it is testing in the shadow, and what still waits to be receipted. |
| `nightcrawler learn run` | Replay finished days and score every strategy version now (the bot does this by itself every `LEARN_INTERVAL_MIN`). |

Exit codes: 0 ok, 1 error, 2 usage, 3 bad settings / live mode refused, 4 receipts broken or audit drift.

## Check the receipts without nightcrawler

[`scripts/verify_receipts.py`](scripts/verify_receipts.py) re-checks an export using only
Python 3's standard library. It never imports nightcrawler, so a skeptic can read the whole
file before trusting it:

```bash
nightcrawler receipts export receipts.jsonl
python3 scripts/verify_receipts.py receipts.jsonl --head <a head hash you posted earlier>
```

It applies the chain rule from [docs/DESIGN.md](docs/DESIGN.md) (section 5) to every line:
`hash = sha256(prev_hash + body)`, seq 1, 2, 3 ... starting from 64 zeros. It also checks
that the readable fields say exactly what the hashed `body` says. It prints `OK` (exit code 0)
or `BROKEN at seq N` with the reason (exit code 1). `--head` checks that a hash you published
earlier is still in the chain: someone who rewrote the history could re-link every later
receipt, but they could not reproduce a head hash that is already public.

## Settings

Every setting is an environment variable (on Railway: the service's **Variables** tab). The
full list with explanations is in [.env.example](.env.example). The important ones:

| Variable | Default | Meaning |
|---|---|---|
| `TRADING_MODE` | `paper` | `paper` or `live` (real money). |
| `LIVE_CONFIRM` | (empty) | Must be exactly `I_ACCEPT_REAL_MONEY_RISK` for live mode. |
| `BOT_WALLET_MODE` | `env` | `generated` = the bot makes and keeps its **own** wallet (nobody ever sees the key); fund it from Phantom with Send. See [docs/GOING_LIVE.md](docs/GOING_LIVE.md). |
| `BOT_WALLET_SECRET` | (empty) | With `BOT_WALLET_MODE=env`: the private key of a **dedicated** bot wallet. Secret. |
| `WITHDRAW_TO` | (empty) | Your Phantom address (the one that funded the bot): the bot buys nothing, sells everything, closes its empty coin accounts and, after a 10-minute cancel window, sends ALL its SOL there (paper mode only shows what it would send). |
| `KILL_SWITCH` | `off` | `stop` = no new buys; `sell_all` = sell everything, then stop. `sell-all` works too; an unknown word means `stop`. |
| `RESET_HALT_TOKEN` | (empty) | Change to any new value (e.g. today's date) to clear a drawdown halt once. |
| `DASHBOARD_TOKEN` | (empty) | Password for the dashboard link. **Set a long random one** on Railway: live mode refuses one shorter than 24 characters, and the checklist only ticks a strong one. |
| `KEYS_ROTATED_ON` | (empty) | The date (`YYYY-MM-DD`) you replaced every key ever pasted into a chat. Only ticks step 4 of the dashboard's "Ready for real money?" checklist; anything but a date is refused at start. |
| `DATA_DIR` | `./data` | Where the ledger lives. On Railway: `/data` (a volume). |
| `PAPER_START_USD` | `100` | Pretend bankroll at the first start. |
| `POSITION_PCT` | `0.20` | Share of equity per position (a fraction: 0.20 = 20 %). |
| `MAX_POSITION_USD` / `MIN_POSITION_USD` | `25` / `5` | Position size limits in dollars. |
| `MAX_OPEN_POSITIONS` | `3` | Most positions at once. |
| `DAILY_LOSS_LIMIT_PCT` | `0.20` | After losing 20 % in a UTC day, no new buys until tomorrow. |
| `DAILY_RISK_BUDGET_PCT` | `0.15` | Today's loss plus 95 % of every open ticket and of the new one (a rug's real loss) must fit in 15 % of the day's start, or the ticket shrinks (no buy below $5). At $100 the first ticket is $15.79. |
| `MAX_AT_RISK_PCT` | `0.25` | All open tickets together may risk at most 25 % of the money in rugs (95 % of each). |
| `MAX_DRAWDOWN_HALT_PCT` | `0.50` | After falling 50 % from the peak, no new buys until you reset. |
| `MAX_WALLET_USD` | `150` | Live: refuses new buys while the wallet holds more than this, in case you funded the wrong wallet. |
| `SOL_RESERVE` | `0.02` | SOL that is never spent (fees, deposits). |
| `MAX_PRICE_IMPACT_PCT` | `3.0` | Skip a buy whose quote moves the price more than 3 %. |
| `MIN_AGE_MIN` / `MAX_AGE_H` | `60` / `48` | Only coins between 1 hour and 2 days old. |
| `MIN_AGE_SINCE_GRAD_MIN` | `30` | ... and that left their bonding curve (graduated) at least 30 minutes ago: the lab saw the first half hour after graduation lose the most. |
| `MIN_MCAP_USD` / `MAX_MCAP_USD` | `100000` / `5000000` | Market-cap window. |
| `MIN_LIQUIDITY_USD` | `30000` | Pool liquidity floor (when known). |
| `DIP_PCT`, `TAKE_PROFIT_PCT`, `TRAIL_PCT`, `STOP_LOSS_PCT` | `0.55`, `0.40`, `0.15`, `0.18` | Strategy (fractions). |
| `ANTHROPIC_API_KEY` | (empty) | Turns the AI judge on (then `JUDGE_MODE=required` by default). Secret. |
| `JUDGE_MAX_DAILY_USD` | `1` | AI spending cap per day; past it, the judge says no. `0` blocks every judge call. |
| `SOLANA_RPC_URL` | public RPC | A free [Helius](https://www.helius.dev/) key is recommended, especially for live mode. |
| `JUPITER_API_KEY` | (empty) | Optional; higher Jupiter rate limits. |
| `USAGE_HELIUS_MONTHLY_CREDITS` | `1000000` | The dashboard's "Services used" card counts calls per provider per day and month; a bar turns amber at 80 % of a budget and a used-up budget gets a banner. This is the Helius free plan; `USAGE_JUPITER_MONTHLY_CALLS` and the other `USAGE_*` settings default to `0` (no budget). The judge's budget is `JUDGE_MAX_DAILY_USD`. |
| `TOWN_RAILWAY_USD_MONTH` | `5` | What Railway charges per month to run the bot (the Hobby plan). The page's "The town" card turns it into a cost per day, adds the AI judge's spending and compares both with what the desks made, today and since the start: the desks must earn more than the town costs to run. |
| `OWNER_TZ` | `America/Los_Angeles` | Your time zone (an IANA name such as `Europe/Athens`). The 3D world's nightly recap film replays "yesterday", the previous calendar day of this zone, from the bot's own records: by itself at 00:05 in this zone if the page is open, and on demand from the "yesterday" chip. An unknown name logs a warning and the recap uses the UTC day. |
| `TOWN_GOAL_USD` | `100` | DISPLAY ONLY: the owner's goal for the team, in real dollars a day, shown by the 3D world's goal tower (`/api/page` -> `town.goal`, `plain.goal`). Only real money counts toward it; it is a goal, never a cost (the town's real running cost stays `TOWN_RAILWAY_USD_MONTH` plus the AI judge), and no desk, limit or rule reads it. Read leniently (`$100`, `100`, `1,000`); a value it cannot read, or one outside 1 to 1,000,000, logs `town_goal_bad` and shows 100. |

"`_PCT`" knobs come in two kinds, and the bot checks you used the right one: the strategy and
risk knobs listed above are **fractions** (0.20 = 20 %), while `MAX_PRICE_IMPACT_PCT` and the
`COCOON_*`/`RADAR_*` thresholds are **percent** (3.0 = 3 %). A wrong scale refuses to start
with a hint.

## Safety guardrails

- **Paper by default.** Live mode needs `TRADING_MODE=live`, the exact confirmation phrase and
  a wallet. Without all three it refuses to start.
- **No keys to handle** with `BOT_WALLET_MODE=generated`: the bot's own key stays in
  `DATA_DIR/wallet/` (never shown, logged or sent; never replaced). You fund it with Phantom's
  Send and take it back with `WITHDRAW_TO`.
- **Dedicated wallet only,** with `MAX_WALLET_USD` as a tripwire if you load the wrong one.
- **Fail closed.** If a safety source, the radar, the judge or a quote fails, the bot doesn't buy.
- **Limits:** 20 % per position (max $25), at most 3 open positions, a daily loss stop and a
  drawdown halt measured in SOL, so a SOL price move alone can't trip them. Every limit counts 95 %
  of each ticket as at risk (a rug, not the stop), so a ticket shrinks until even all-rug days
  stay within 15 % and above the halt line.
- **Blind means out:** a position with no price for 30 s is priced by a Jupiter sell quote; two
  failed quotes in a row and it is sold.
- **Kill switch** from the Railway variables page: `stop` or `sell_all`.
- **Never double-buys.** A swap is never re-sent. If a live swap's outcome is unknown, the bot
  stops all new buys, asks the blockchain about the transaction (or, when it cannot, waits 90 s),
  reads the wallet and records what really happened.
- **Most broken settings don't strand real money.** With open live positions, an invalid setting
  starts an exits-only safe mode (stop-losses keep working, no new buys, a red dashboard chip)
  instead of refusing to start - as long as a valid live setup remains. A broken `TRADING_MODE`,
  `LIVE_CONFIRM`, `BOT_WALLET_SECRET` or `DATA_DIR` still refuses to start, and the open positions
  have NO stop-loss until you fix it.
- **Forced exits still work in thin pools:** stop-loss, trailing, time, radar and kill exits
  accept up to 25 % price impact rather than staying trapped.
- **Secrets never appear** in logs, receipts or the dashboard. The dashboard is read-only and
  can be password-protected.
- **Tamper-evident receipts** and `report`, which checks the books against the wallet.

## FAQ

**Will this make money?**
Probably not, at least not reliably. It's a measuring instrument with a strategy attached.
Run paper mode for weeks and let the receipts tell you.

**Why did it buy nothing all night?**
That's normal. Most new coins fail the rug filter or never show the setup. On the dashboard,
tap **Cocoon** (the rug filter) to see why coins were thrown out, and **Strategy** to see how
close each watched coin is to the setup.

**What are the receipts for?**
They make the results provable. Anyone with the exported file can recompute the fingerprints
and see that no decision was edited or deleted after the fact. Viral bot posts never offer
this.

**Can I use my main Phantom wallet?**
**No.** Create a separate account in Phantom just for the bot and put only what you can lose
in it. See [docs/GOING_LIVE.md](docs/GOING_LIVE.md).

**How do I stop it right now?**
On Railway, set the variable `KILL_SWITCH=sell_all` and deploy. Then, once the dashboard
shows no positions, set `KILL_SWITCH=stop`.

**The dashboard says "Halted". What now?**
Equity fell 50 % from its peak, so new buys stopped. Think before restarting. To resume, set
`RESET_HALT_TOKEN` to a new value (for example today's date) and deploy, or run
`nightcrawler reset-halt`.

**Is paper mode the same as live?**
Yes, except for signing and sending. Both use the same Jupiter Ultra quote at the same size,
with the same fees. Live fills record the *actual* amounts, so you can see the slippage
against the quote.

**Does the AI judge make it smarter?**
Unproven. It's a second opinion that can only veto. It costs money (capped at $1/day by
default) and should be judged by the receipts like everything else.

**Taxes?**
In many countries, including the US, every swap counts as a taxable sale. `nightcrawler report`
and `receipts export` give you the records. This isn't tax advice.

---

Developers: the architecture, contracts and units are in [docs/DESIGN.md](docs/DESIGN.md).
Tests run fully offline with `pip install -e ".[dev]" && pytest -q`.

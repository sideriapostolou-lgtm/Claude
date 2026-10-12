# Handoff: everything a new worker needs

Written 2026-10-12 by Claude for the next AI worker (ChatGPT/Codex or a fresh Claude session). Read `AGENTS.md`
first; its hard rules win over anything here. Older history: `git log` (320+ commits with full messages) and
`docs/ACCOUNTS.md` (every account, every real-money decision with dates).

## 0. Start here

"Nightcrawler" is one Python service (`src/nightcrawler`) running 24/7 on Railway. It runs several desks:

| desk | what it does | money |
|---|---|---|
| Polymarket desk (`polydesk.py`) | Buys near-certain crypto outcomes (mostly Bitcoin hourly "above $X" markets at 95-99c) on Polymarket US, plus Marco's NFL picks | **REAL** |
| Marco desk (`marcodesk.py`, `MARCO`) | Copies the NFL moneyline picks "Million Dollar Marco" says he loves; the Polymarket desk places them for real | practice since 2026-10-12 (`MARCO_REAL=0`, the owner's word) |
| NHL desk (`marcodesk.py`, `NHL`) | Copies Nick Martin's NHL picks from Action Network | practice only (the owner said no real money) |
| Arena (`arena.py`) | 24 bot "residents" that trade, pay $1 rent a day and get evicted when broke | practice only |
| Trend desk (`trenddesk.py`) | SMA-50 trend following on BTC, ETH and SOL | paper |
| Memecoin engine (`engine.py`, `crawler.py` ...) | The original Solana memecoin bot | paper |

The owner watches it all through a token-protected website (`dashboard.py`): a one-page money view at `/` and a 3D
town at `/world`, where real money is the only thing filmed.

**Today's state (2026-10-12 ~15:40 UTC):** real money is ON. The crypto rule is 48 bets, 48 wins, about +$3.40.
The owner wants to scale it, and lab 8 is testing his idea for a smarter version before any size goes up.

## 1. Hard rules and the emergency stop

The rules are in `AGENTS.md`. They boil down to: no real-money change without the owner's specific word, no
secrets, finished and tested small changes pushed to the deploy branch, every deploy checked, honest numbers.
Use a pull request for bigger changes or when the owner wants to review first.

**Emergency stop.** The owner can do these alone, with no AI:
1. **Fastest:** in the Polymarket app, delete the API key the bot uses. Its orders are refused at once.
2. **Stop the whole service:** in the Railway dashboard, open project `nightcrawler`, then service `bot`, then
   Deployments, and remove the active deployment.
3. **Real money off, bot keeps running:** set `POLYDESK_MODE=paper` on service `bot`. Once the new deployment is
   running, the desk sends no new real orders. It does **not** close or sell open bets; they settle at the venue (or
   the owner cashes them out in the app). The desk sends immediate-or-cancel orders, so nothing should be left
   resting on the book, but check the app's Orders tab.
4. **Kalshi speed desk:** also set `SPEEDDESK_KALSHI_MODE=paper`. The companion cancels its own resting bids
   and reconciles them before releasing their budget; filled bets remain real until settlement. If cancellation
   is unconfirmed, check the Kalshi Orders tab and cancel the bot's bids there. Its stop is separate from
   `POLYDESK_MODE`; stopping all real buying requires both switches.

## 2. System map (src/nightcrawler)

* **Wiring:** `engine.py` starts every desk thread and the scheduler. `cli.py` is the `nightcrawler` command
  (`run`, `dashboard`, `report`, `receipts`, `verify`, `wallet`, `sell-all`, `reset-halt`, `learn`, ...).
  `config.py` holds one frozen `Settings`, read from environment variables; all names and defaults are in
  `.env.example`. `logging_setup.py` logs one line per event with secrets redacted. `http.py` is the shared
  client with rate limits and retries. `clock.py` provides deterministic time.
* **Ledger and receipts:** `ledger.py` (SQLite, the single source of truth) and `hashing.py` (hash-chained receipts
  that prove nothing was edited after the fact). `audit.py` handles reconciliation and P&L.
* **Polymarket (real money):** `polydesk.py` (the desk), `polymarket_us.py` (the signed API client: balances,
  positions, orders, activity feed), `deskguard.py` (the risk manager's verdict on a desk's record),
  `sportmap.py` (game to sport), `towngoal.py` (the $100/day goal tower; it counts real money only).
* **Follow desks:** `marcodesk.py`: `Follow` dataclass; the `MARCO` (NFL) and `NHL` instances; picks come from
  `src/nightcrawler/data/marco_picks.json` / `nhl_picks.json`, a branch copy (`FOLLOW_PICKS_URL`, raw GitHub)
  and, for NHL, the Action Network profile page.
* **Practice and paper desks:** `arena.py`, `trenddesk.py`.
* **Memecoin bot (paper):** `crawler.py` (discovery), `cocoon.py` (rug filter, fails closed), `radar.py`
  (insider sells), `judge.py` (optional AI judge "Jev"), `strategy.py` (pure signals), `risk.py` (sizing and
  guardrails), `costs.py`, `backtest.py`, `dataset.py`, `flow.py`, `broker/` (paper and live Jupiter brokers,
  `keystore.py` for the bot's own wallet), `botwallet.py`, `withdraw.py` (`WITHDRAW_TO` sweep), `readiness.py`
  (the "ready for real money?" checklist), `sources/` (DexScreener, GeckoTerminal, Jupiter, pump.fun, RugCheck,
  Solana RPC).
* **Learning:** `learn/` (forward tape, shadow replays, champion/challenger; docs/LEARNING.md) and `experience/`
  (report cards, loss types, playbook; docs/EXPERIENCE.md). Both are advisory only.
* **Pages:** `dashboard.py` (HTTP server, `DASHBOARD_TOKEN` auth, `/api/page`), `page.py` + `pagestate.py`
  (the one page and its data, built from the ledger with no network calls), `world3d.py` (`/world`, three.js),
  `office.py` / `office3d.py` (older `/office` pages), `teamroom.py`, `hearts.py`, `recap.py`,
  `research_board.py` (a fixed table of lab verdicts).
* **Tests:** `tests/` (about 3,000). The real-money safety tests are `test_polydesk_live.py`,
  `test_polydesk_safety.py`, `test_polydesk_owner.py` and `test_polymarket_us.py`.

## 3. Real money: the Polymarket US desk

* **Venue:** Polymarket US (CFTC-regulated). Market data is public at `https://gateway.polymarket.us/v1/...`
  (`/markets/{slug}/book`, `/bbo`, `/settlement`, `/events`). Orders, positions, balances and the activity feed
  need the signed key (`POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY`, Railway only). Taker fee:
  0.0695 x contracts x p x (1-p).
* **Switches:** `POLYDESK_MODE` (`paper`/`live`) plus `POLYDESK_LIVE_CONFIRM`. The desk goes live only after a
  successful balance read; a rejected key leaves it on paper.
* **Caps right now (Railway variables; code defaults in brackets):** `POLYDESK_LIVE_CONTRACTS=10` [1],
  `POLYDESK_LIVE_MAX_OPEN_USD=30` [10], `POLYDESK_LIVE_DAILY_LOSS_USD=30` [3],
  `POLYDESK_LIVE_TOTAL_LOSS_USD=40` [10]. The daily and total stops count open bets as if they had all lost.
  Hitting the total stop halts real money for good (`live_halted`, `halt_reason="total_loss"`). Only the owner
  restarts it, with a new value of `POLYDESK_RESUME_TOKEN`; each value works once. An unreadable state file also
  halts it, and the resume token never clears that.
* **The rule:** buy an outcome at or above `POLYDESK_THETA` (0.97) within `POLYDESK_HOURS` (1) of resolution, with
  a spread of at most 0.03. One outcome per game or price ladder. **No real money on sports**
  (`REAL_SPORTS_ALLOWED` is empty in code), except Marco's loves when `MARCO_REAL=1`. Long side only.
* **The owner's own bets** (`RULE_OWNER`): any venue position with no desk order behind it is the owner's. It is
  shown on the page but never counted in caps or stops. Parlays bought before 2026-10-11 were moved out once by
  `_owner_migration`.
* **Cash-outs:** the owner sometimes sells the desk's bets in the app. `_book_sales` reads the activity feed
  (`polymarket_us.activities`) and books such a sale at the venue's realized figure, or corrects a booking already
  made at settlement. Those sales still count in the desk's stops.
* **Reconcile:** each round `_reconcile` reads the venue's positions and adopts fills the desk logged as missing.
  Desk orders that never filled are kept 7 days in `dropped_orders`. `_settle` books results from the venue's
  settlement prices.
* **Risk manager:** `POLYDESK_GUARD` (on by default; `deskguard.py`) pauses buys while a rule's own record is
  losing. It can only switch real money off.
* **State:** `/data/polydesk/state.json` on the Railway volume (`polydesk.state_path`). Logs use `polydesk_*` event names: `polydesk_activity`,
  `polydesk_sold_in_app`, `polydesk_sale_corrected`, `polydesk_live_halted`, `polydesk_live_resumed`,
  `polydesk_adopted`, `polymarket_us_order_reply`.

## 4. Deploy and operations

* Railway project `nightcrawler`, service `bot`, volume `nightcrawler-data` at `/data`, domain
  `bot-production-9d67.up.railway.app`. Builds use `Dockerfile` and `railway.json`. More in `docs/RAILWAY.md`
  and `docs/GOING_LIVE.md`.
* **Deploys.** The service source is `sideriapostolou-lgtm/Claude` (exact GitHub casing, capital C), branch
  `claude/nightcrawler-memecoin-bot-Gwnb1S`. **Autodeploy is ON since 2026-10-12 16:32 UTC.** Lowercase `claude`
  made Railway report `NO_INSTALLATION`; the exact casing fixed it. A push or merge to the branch deploys, but only
  when it touches a watched path: `src/**`, `pyproject.toml`, `Dockerfile`, `railway.json` or `README.md`. Other
  pushes are SKIPPED and the live deployment stays. **Deploy on push verified 2026-10-12:** the visual cleanup
  `0f55628` automatically created deployment `aeb5bc19`, SUCCESS; startup at 17:10:07 UTC shows
  `polydesk_started ... (LIVE: 10 contract(s) per order)`, with no tracebacks and a passing `/healthz`.
  After every deploy, check that Railway built that exact commit and that the logs show `polydesk_started ... (LIVE ...)` with
  no tracebacks. PR #5's merge commit 1cd27824 ran as deployment 0866daea at 16:23 UTC, triggered by setting the
  source branch rather than by the merge itself. That earlier restart alone did not verify deploy on push.
* Restarts are safe. State lives on the volume, and the desk re-reads the venue each round.
* Any worker's push to the branch deploys (see AGENTS.md rule 3). To read logs a worker needs the owner's Railway
  token in its environment as `RAILWAY_TOKEN` (Railway CLI: `railway logs`, `railway status`). Never `railway
  variables` without `--set`, because it prints secret values.

## 5. Accounts and credentials (names only)

Everything is in `docs/ACCOUNTS.md`: provider, plan, budget and variable names. Keep it updated whenever a
provider, plan or key variable changes, and never write a key in it. The keys in use live only in Railway:
`POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY`, `JUPITER_API_KEY`, `SOLANA_RPC_URL` (Helius), `ODDS_API_KEY`,
`DASHBOARD_TOKEN`, and the bot wallet (`BOT_WALLET_MODE=generated`, kept by the bot on the volume). A worker
needs none of them to write code or run tests.

## 6. The owner's pages

`/` is the one page: money, team, trades, learning, receipts. `/world` is the 3D floating-island town, "Night
Shift: Skyport". Its cinema shows real money only, practice props stay hidden, and the town district sits on an
islet. `/api/page` is the JSON behind both. Every page needs `?token=` (`DASHBOARD_TOKEN`). To see a change, run
`nightcrawler dashboard` locally in paper mode and screenshot it with Playwright/Chromium at phone and desktop
widths. The owner checks everything from a phone.

## 7. Research and its honesty rules

Labs live in `research/labN/` (`PLAN.md` pre-registration, `READING.md`, `RESULTS.md`, `core.py`, `data.py`,
`trials.json`). The rules: write the plan before computing any return; split by time; run TRAIN, then VAL, then
TEST once, behind an environment flag; use cluster bootstrap CIs, the venue fee and a latency stress; "NO EDGE" is
a valid result. Verdicts so far:

| lab | question | verdict |
|---|---|---|
| 2, 3 | memecoin flow, crypto majors | no edge, except lab 3's `sma50` trend rule (now the paper trend desk) |
| 4 | buy 95-99c outcomes before resolution (the live crypto rule) | NO EDGE: win rate about equal to price, after fees roughly zero or slightly negative |
| 5 | crypto fair value from spot and volatility | NO EDGE (the market forecasts as well as the model) |
| 6 | sports vs Pinnacle no-vig odds | NO EDGE |
| 7 | in-and-out trading on four desks | NO EDGE (588 cells) |
| 8 | **in progress:** the owner's "distance-filtered grind" | design stage (section 9) |

Data caches are **not** in git. Rebuild them with each lab's `data.py`; the steps are in its docstring. The
Binance archive is `data.binance.vision`; `api.binance.com` refuses some regions. The caches Claude used lived in a
session scratchpad that you will not have.

## 8. Live numbers (2026-10-12, from the venue's activity feed)

* **Owner deposits:** $110 in total ($25 on 10-09, $25 on 10-10, then $25, $25 and $10 on 10-11). Cash is about $14.
* **Crypto rule (real):** 48 bets, 48 won, all Bitcoin (37 hourly above-strike, 6 15-minute up/down, 5 hourly
  up/down). About +$3.40 after fees on $175 staked. A full 10-contract win pays about $0.19; one miss costs about
  $9.81, the same as about 51 wins. 48-0 is consistent with no edge: it happens 38% of the time at a fair 98c.
  Books are thin: 5 of the last 19 orders filled only 1-3 contracts, and one hourly market traded $165 in its
  whole life.
* **Marco (real, NFL, 10-11):** Saints lost (-$4.43). The owner cashed out the Packers (-$3.84) and the Commanders
  (-$5.54). Total -$13.81.
* **The owner's own parlays (not the bot's):** -$10.69, -$22.24, +$21.55, -$26.75, -$14.25, about -$52.38. They
  drained the cash, and on 10-11 they briefly tripped the total stop before the owner rule existed.
* **Real-money history in short:** live on 10-09 with $25, then paper after unparsed fills. Live again on 10-10;
  that day's audit led to rule `2026-10-10a`: no sports, one bet per ladder, stops count money at risk. 10x bets
  from 10-11 03:00. `MARCO_REAL=1` from 10-11 06:40. The total-loss halt at 20:02 on 10-11 came from the owner's
  parlays; the owner rule and the resume came at 20:31. The cash-out booking went live at 21:35. Exact times are
  in `docs/ACCOUNTS.md`.

## 9. Work in flight and backlog (in priority order)

0. **The speed desk (owner's top priority, 2026-10-12):** implementation follows `docs/SPEEDDESK_SPEC.md`,
   original **practice trial** (`speeddesk.py`, its model and venue adapters, independent engine thread). It uses Coinbase
   Bitcoin ticks with Polymarket US 15m/1h books; the public Kalshi KXBTC15M adapter is separately controlled by
   `SPEEDDESK_KALSHI_ENABLED`. All speed-desk settings are `SPEEDDESK_*`; the independent practice budgets default
   to $20 per window, $20 across open windows, and a $10 UTC daily loss stop. The owner's approved starter clip
   permits the first practice buy, then only balancing buys until the 25 % imbalance cap is satisfied. The
   original trial cannot place real orders, and `SPEEDDESK_MODE=live` is rejected. The separately gated Kalshi
   companion below is the only speed-desk live path.
   State and receipts live under `/data/speeddesk/`; `/api/page` has `money.speeddesk.today` plus the latest 31
   UTC calendar-day reports. The page labels this **PRACTICE**, keeps locked-pair and directional results apart,
   reports fill rates and latency, and never adds pretend results to cash or the town's real profit.
   Both `today` and each completed report include `venues.kalshi` and `venues.polymarket_us`; the phone page
   shows separate venue cards and expandable daily history. Uptime/Bitcoin latency are shared, while fresh
   book/trade coverage is measured per venue. Missing historical splits stay unknown. Per-venue order fill
   rates use the order's placement day; execution counts and settlement profits use their actual UTC day.
   These reports do not change the desk's shared practice budgets or the existing real-money desks.
   **Deployed and verified 2026-10-12 19:27 UTC** on `c329133` (venue reporting PR #8; initial implementation
   PR #7). Both venue
   trade feeds are verified; existing polydesk remains LIVE at 10 contracts. The at-least-three-day observation
   is still pending, with the first conservative review no earlier than 2026-10-15 19:09 UTC. See `docs/WORKLOG.md`.
   Partial days and missing/stale feeds are reported honestly. **Later owner decision, 2026-10-12:** the owner
   waived the three-day prerequisite for a separate Kalshi-only companion, with exact $2/window, $4 open,
   $3 UTC day stop and $5 total stop limits. See spec section 9. This companion ships **paper by default**,
   uses actual account fills/fees/positions and a separate honest practice twin, and never promotes itself.
   The owner activates `SPEEDDESK_KALSHI_MODE=live` and `SPEEDDESK_KALSHI_LIVE_CONFIRM=yes` only after the
   deployment check. Until Direct-account fee precision is established, conservative rounding excludes all
   positive-edge orders; the panel says why. Set the factual `SPEEDDESK_KALSHI_ACCOUNT_TYPE=direct` only
   if the owner confirms a personal account opened directly with Kalshi; `fcm` for a broker/FCM, otherwise
   leave `unknown`. This account fact does not authorize orders. Total stop requires a never-before-used resume token. Companion
   receipts live in `/data/speeddesk/kalshi_live/`; the page exposes `money.speeddesk.kalshi_live`, separately
   from Polymarket cash and town totals. Polymarket US speed trading remains practice permanently.
   **Companion deployment verified 2026-10-12 20:14 UTC:** PR #9, commit `38d8a42`, Railway SUCCESS,
   `speeddesk_live_status` PRACTICE/real_orders_available=false; existing polydesk still LIVE at 10 contracts.
   New logs: `speeddesk_live_order`, `_fill`, `_cancel`, `_reject`, `_status`. Resting bids have a 30-second
   venue expiry, cancel on cutoff/staleness/stop/startup, and keep their reservation until fills reconcile.
   Also live since 2026-10-12: the Bitcoin distance bar depends on price and time left (`btcdistance.REQUIRED_Z`),
   and `MARCO_REAL=0`.

   **Source-bot watcher and faster feed (2026-10-12 owner update):** the owner wants an evidence-backed
   real Kalshi strategy as the eventual result, within the same $2/$4/$3/$5 caps. `skipwatch.py` is an
   independent, public-only observation worker; it never sends orders or enables a strategy. See spec
   section 10 and `research/lab8/skip/PLAN.md`. It records the source wallet, international BTC five-minute
   books/trades and Coinbase ticks under `/data/skipwatch/`, and exposes a separate public-watcher panel.
   It preserves its original start time through redeploys, freezes a fixed model after 48 elapsed hours
   and checks the untouched final day after 72 hours, subject to coverage. No real rulebook or profit is
   established yet. Exact private orders/cancellations cannot be recovered from public fills.
   The Kalshi market adapter now supports the separately authorized authenticated **read-only** WebSocket,
   even when the companion is paper; REST remains a bounded fallback. This supersedes the earlier
   public-REST-only credential restriction for market data, not any live order gate. HTTP RTT probes and
   a verified US five-minute listing alert are separate from trading. No Railway region or variables
   changed. Check the newest WORKLOG entry for actual deployed behavior and remaining observation time.

1. **Lab 8, the distance-filtered grind (the owner's idea).** Buy 95-99c only when Bitcoin is far from the strike,
   measured in how much it normally moves in the time left (z = ln(S/K) / (sigma x sqrt(minutes left))). Done so
   far (`research/lab8/`): `us_venue.md` (the US crypto markets, all Bitcoin, settle on CF Benchmarks' BRTI;
   there is no public trade tape), `inventory.md` (what the caches can test; the US hourly-strike family is
   barely in them), and `tail_2019_2025.md` (`tail.py`, Binance 1m from 2019 to 2026-05, outside every split).
   The tail study's main result: at z >= 4 with 20 minutes or less left, about 0.2-0.4% of cases still flip, which
   is under the 0.93% break-even at 99c. Normal-curve math badly understates those tails.
   **Next:** write `research/lab8/PLAN.md` before any 2026 return is computed (universe, z and vol estimator,
   grid of 24 cells or fewer, cluster bootstrap by settlement draw, fees, latency, decision rule, and a capacity
   section answering "give it $1,000"). Then build, run TRAIN, review it adversarially, then VAL and one TEST.
   One correction from the inventory: in the owner's screenshot example, BTC was $564 (0.69%) above the strike at
   the buy, not $960. The $960 was the 13:55 price.
2. **Scaling brief for the current crypto rule.** The owner said "scale it", but no setting has changed. Present
   options with exact caps (`POLYDESK_LIVE_CONTRACTS`, `..._MAX_OPEN_USD`, `..._DAILY_LOSS_USD`,
   `..._TOTAL_LOSS_USD`), the cash each needs, expected $/day, and the cost of one and two misses. Note that the
   books cannot take $1,000. The owner decides.
3. Make the desk log *why* it skips a bet (open cap, stop room, price moved). Today these reasons are only
   counted in the state file. This is not real-money logic; it is safe to add.
4. Backlog: profit sweep to the owner's wallet; a "withdraw to bank" button; the live trade-flow feed
   (`flow.py`, `sources/pumpfun_trades.py`); follow-ups to lab waves 2-3; NHL desk stays practice (Nick posted no
   NHL picks on 10-11). The weekly Marco refresh was a Claude-only scheduled routine; picks are edited in
   `src/nightcrawler/data/marco_picks.json`.

## 10. Gotchas that already bit us

* The venue once filled orders that the desk logged as "no fill". The desk now reconciles against positions
  every round; never trust an order reply alone.
* A wide book's ask is not a belief. That is why `MAX_SPREAD` is 0.03.
* Owner and desk share one account. Before the owner rule, his parlays counted in the desk's stops.
* The positions list drops closed positions, so a cash-out is visible only in the activity feed.
* A Railway variable change alone builds the wrong branch (section 4).
* `FOLLOW_PICKS_URL=""` falls back to the default; use `off` to disable it.
* Moneyline sides on Polymarket US: YES is the away team, NO is the home team.
* In the app, a thin book shows a scary mark (68%) on a near-certain bet. That is the bid, not the odds.
* Streaks prove little at 98c: one loss cancels about 50 wins. Use the labs, not the streak.
* Helper agents and usage limits run out mid-task. Commit work in progress early.

## 11. How to talk to the owner

Short and plain. Numbers in dollars and in the venue's own figures. Say clearly what is real money and what is
practice. Give your recommendation, not a survey. When he asks to go bigger, show what one miss costs before
doing anything. He likes the town, the team and the "keep the town alive" framing, but the numbers must be
real. Never claim something is done or verified when it is not.

## 12. Handoff protocol between AI workers

**Setting up ChatGPT/Codex to work like Claude (owner, one time):**
1. Codex settings: connect GitHub with access to `sideriapostolou-lgtm/Claude`. It can then push to the deploy branch.
2. Railway: project `nightcrawler`, then Settings, then Tokens. Create a **project token** for environment
   `production` and paste it into Codex's environment settings as the secret `RAILWAY_TOKEN`. Paste it nowhere else.
3. Codex environment: turn on internet access, and add `npm i -g @railway/cli` to its setup script.
4. If Codex can only open pull requests in your setup, you keep tapping Merge. That is a Codex limit, not a rule.


* At the start: read `AGENTS.md`, this file and the latest `docs/WORKLOG.md` entries, then check open pull
  requests.
* At the end: add a `docs/WORKLOG.md` entry with date, who, what changed, what was verified (tests and their
  output), what was not, and the next step. Leave the tree clean. For small tested changes, pull and push the
  deploy branch per AGENTS.md; for bigger changes or owner review, push a codex/ branch and open or update its
  pull request. After a watched-path push, verify the exact deployed commit and intended startup mode.
* Never leave a half-made real-money change on a branch without a big "DO NOT MERGE" in its pull request.
* Update this file when the system changes, especially sections 3, 8 and 9.

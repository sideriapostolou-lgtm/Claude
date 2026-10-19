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
town at `/` (also `/world`), with a plain fallback at `/summary`.

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
* Normal restarts rely on intact, current state on the volume and fresh venue reconciliation. After a failed
  authoritative save or disk-full error, do not assume the old file includes every loss, pending order or
  consumed owner control. Inspect available space/inodes and state integrity, preserve the original records,
  and reconcile current venue balances, positions, orders, fills and settlements before recovery.
  A healthy web process, valid JSON or free bytes alone is not proof that restarting real trading is safe.
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

`/` and `/world` open the steady, phone-first tycoon town. The retired `/reports`, `/office`, `/office3d`
and `/team` pages redirect to `/` after authentication. `/summary` is the independent, non-WebGL fallback: a
plain account/team report with one return link and no buttons. Authentication and read-only APIs are unchanged.
The town foregrounds Kalshi account cash and Kalshi bot profit since midnight Pacific, one Menu, six tappable
workstations and a dated Kalshi real-activity line. Polymarket stays live, as the owner confirmed; its separate
account and activity are available in secondary Money details rather than mislabeled as practice. Tap a building or its name to visit; Back to town restores the overview. The menu has exactly **Money, Team, Help**. Money keeps both accounts, open bets and source ages together;
Team holds the accessible crew list. The observatory opens research. Help explains the town and stopping both
real-money desks. The camera-tour switch, old report links, Office footer and extra menu shortcuts are removed.
Legacy animation helpers retain inert hidden DOM for compatibility; saved display settings cannot restore the
old controls. No trading switches are exposed by the town.

The owner confirmed on 2026-10-12 that "today" means **since 12:00 a.m. Pacific**. The Polymarket daily display uses `real.today_pacific` (America/Los_Angeles, including daylight saving).
It sums recorded bot results only when the retained closed rows' count and profit match every overlapping UTC
day book; incomplete records show an unknown total. This checks the saved book, not complete venue reconciliation.
Cash-outs and corrections keep their recorded booking day, which may differ from venue event time. Account cash
and holdings include the owner's own activity; the bot's result excludes it. Cash is not profit. Account-bet
count/value use the separately dated venue snapshot (`real.venue_open`, `value_usd`, `venue_at`), not tracked
positions that can remain after an app sale. Each balance has its own age: a fresh page cannot freshen old cash.

Theme Park Tycoon 2-inspired grounds connect the existing cast and navigation paths: vivid lawns, wide paths,
solid colorful cutaway shops, department emblems and block trees. Six local toy costumes follow the original
characters and their recorded activity; no invisible legacy character/prop models download in town mode.
The steady phone camera fits the shops and enlarged cast; the original dome and decorative airship are hidden.
Walking remains decoration and the same real-event gates control receipts, deliveries and celebrations.
Five decorative gardens unlock at $0.01 / $0.25 / $1 / $5 / $10
of recorded Kalshi bot profit **today**, only when the complete Kalshi book covers the current
Pacific date and its source report is fresh. A missing Kalshi book never falls back to Polymarket.
They reset at Pacific midnight, can recede after losses
or corrections, and disappear when the source is unavailable. They are not purchased upgrades or lifetime wealth;
deposits, owner bets, practice gains and elapsed viewing time never unlock them. Original UTC goal props and the
practice arena are hidden. The retired camera modes are not available through the app.

Both accounts remain separate in Menu → Money, including cash, recorded holdings, partial orders, reservations,
fees and source ages. Kalshi's existing UTC result/stops stay unchanged; a separate validated full-book Pacific
result supplies its header and the Kalshi-only gardens. The new `money.connections` projection reads only saved
state, performs no network/trading calls and exposes bounded records with fee/ownership provenance. Polymarket
fees are estimated; its known cash-out accounting edge cases remain in the protected trading code. Kalshi gross
fill-derived holdings are not a current venue-position snapshot. A checkpoint is not proof of account reconciliation.
See [TOWN_CONNECTIONS.md](TOWN_CONNECTIONS.md) for exact sources, age limits and incomplete-data behavior.

The town also distinguishes Kalshi's pair-completion-only permission from new-bet permission, explains the
existing budget exceptions, and shows accounting-stop/reset reasons. Report age is not an account-check age.
Ended but unreconciled gross fills stay labeled as old records. Repeated order reconciliation no longer
creates fake fresh cancellation activity. A Polymarket day-book mismatch keeps Pacific profit unknown and
flags its secondary account details; bounded per-UTC-day counts/sums in `today_pacific.reconciliation`
diagnose the gap without changing
the trading books or substituting a partial profit total.

Voss monitors the Kalshi Bitcoin desk, Jet shows its order receipts, Rook reports its safeguards, and Mote records
its results. Pip and Nyx retain quiet background practice roles. New qualified Kalshi real events can animate these roles; generic practice
handoffs, repeated old chatter and the old UTC goal celebrations do not. First load/reconnect establishes a
baseline, so historical results never replay as new wins. Only positive bot settlements can trigger gold; fills
are receipts, and losses/rejects get caution. Effects expire after 60 seconds and cancel on stale/corrected data.
Ambient walking is decoration. The observatory also restores access to trend, arena, Marco and NHL practice
reports alongside Bitcoin practice, public-bot research and weather observation; none earns real-money growth.

`/api/page` remains the common data source. If 3D fails, a direct link opens `/summary`, which fetches that same
API independently, ages saved reports, puts Kalshi first, keeps other account/practice details collapsed, shows both clocks and bounded record details, clears money on expired
authentication and has no order path.

Every page requires `?token=` (`DASHBOARD_TOKEN`) or its authenticated cookie. Preview locally in paper mode and
screenshot the actual WebGL scene at phone and desktop widths. Preview fixtures are synthetic, never evidence
of current account balances. The owner checks everything from a phone.

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
   $3 UTC day stop and $5 total stop limits (raised by the owner on 2026-10-13 to $5/$10/$6/$10 with the
   locked-in pairs rule, spec 9.1). See spec section 9. This companion ships **paper by default**,
   uses actual account fills/fees/positions and a separate honest practice twin, and never promotes itself.
   The owner activates `SPEEDDESK_KALSHI_MODE=live` and `SPEEDDESK_KALSHI_LIVE_CONFIRM=yes` only after the
   deployment check. Until Direct-account fee precision is established, conservative rounding excludes all
   positive-edge orders; the panel says why. The owner confirmed **opened directly on Kalshi** on 2026-10-12. Record the factual
   `SPEEDDESK_KALSHI_ACCOUNT_TYPE=direct` before activation; this session did not change Railway variables.
   Portable defaults remain `unknown`; `fcm` is for broker/FCM accounts. This account fact does not authorize orders. Total stop requires a never-before-used resume token. Companion
   receipts live in `/data/speeddesk/kalshi_live/`; the page exposes `money.speeddesk.kalshi_live`, separately
   from Polymarket cash. Its real Kalshi records now supply the town foreground (section 6);
   Polymarket US speed trading remains practice permanently.
   **Companion deployment verified 2026-10-12 20:14 UTC:** PR #9, commit `38d8a42`, Railway SUCCESS,
   `speeddesk_live_status` PRACTICE/real_orders_available=false; existing polydesk still LIVE at 10 contracts.
   New logs: `speeddesk_live_order`, `_fill`, `_cancel`, `_reject`, `_status`. Resting bids have a 30-second
   venue expiry, cancel on cutoff/staleness/stop/startup, and keep their reservation until fills reconcile.
   Also live since 2026-10-12: the Bitcoin distance bar depends on price and time left (`btcdistance.REQUIRED_Z`),
   and `MARCO_REAL=0`.

   **Source-bot watcher and faster feed (2026-10-12 owner update):** the owner wants an evidence-backed
   real Kalshi strategy as the eventual result, within the owner's caps ($5/$10/$6/$10 since 2026-10-13). `skipwatch.py` is an
   independent, public-only observation worker; it never sends orders or enables a strategy. See spec
   section 10 and `research/lab8/skip/PLAN.md`. It records the source wallet, international BTC five-minute
   books/trades and Coinbase ticks under `/data/skipwatch/`, and exposes a separate public-watcher panel.
   It preserves its original start time through redeploys. **Automatic fitting is paused:** the wallet API
   timestamps blockchain inclusion after execution, so immediately preceding features could be post-trade.
   A verified execution-time labeling protocol must be preregistered before any rule verdict; reaching the
   original 48/72-hour milestones is insufficient. Raw collection continues. No real rulebook or profit is
   established yet. Exact private orders/cancellations cannot be recovered from public fills.
   The Kalshi market adapter now supports the separately authorized authenticated **read-only** WebSocket,
   even when the companion is paper; REST remains a bounded fallback. This supersedes the earlier
   public-REST-only credential restriction for market data, not any live order gate. HTTP RTT probes and
   a verified US five-minute listing alert are separate from trading. No Railway region or variables
   changed. Check the newest WORKLOG entry for actual deployed behavior and remaining observation time.

   **Expanded mission (latest owner instruction):** full public history and funding audit first, then
   multi-exchange Bitcoin observations, a preregistered held-out fill-matching target of at least 70%
   (right side, within 5 seconds, price within 2c), measured timing and a separate daily scorecard.
   See spec section 11 and `research/lab8/skip/HISTORY.md` plus its 88-point daily cash CSV. All 535,592
   indexed fills are reconciled across public APIs; provider income and cash discrepancies remain explicit.
   Independent chain evidence supports a $4,000
   opening balance in this observed wallet, not the claimed $100. Public block timestamps do not establish
   execution timing; proxy scores cannot silently pass the strict target. Three complete consecutive UTC
   days each positive after fees plus the verified rule-match target are evidence for **asking** the owner
   about higher caps, never automatic permission. The caps changed only at the owner's word ($5/$10/$6/$10, 2026-10-13).

   **Latest shipment:** PR #11, `eb44e03`, Railway reports SUCCESS at 2026-10-12 22:15:53 UTC and public
   health returns `ok`. Read-only Railway token process ended during continuation; the owner was asked to
   add an environment secret. New startup/feed/mode logs remain unverified pending restored access.
   Do not turn this platform success into a claim of healthy feed capture or money activation.

0a. **Lab 9 LucasMeow audit, completed 2026-10-12:** the owner's conditional request was practice only after
   a positive Kalshi backtest. Read `research/lab9/LUCAS_RULES.md`, `KALSHI_BACKTEST.md` and `WEATHER_WINDOW.md`;
   the earlier `REPORT.md` scout is explicitly superseded where those audits disagree. Full wallet: 8,043 fills,
   substantial outside funding, core median 99.4c and 551 sells in the monthly BTC/ETH family. Kalshi: only
   nine completed months, conflicting rule text, missing historical CF index and order-book/queue evidence;
   TRAIN printed-payoff sensitivities contain January losses but are **not strategy P&L**. Verdict is
   **INSUFFICIENT DATA**, no candidate selected, VAL/TEST unscored, no practice desk built. Weather: 1,062
   target-price printed contracts across five observation-proxy windows, only 65 hitting NO bids; actual
   sampled rules use The Weather Company, and report arrival/our fills remain unknown. Research only:
   no runtime/deploy/money change. Do not convert source-wallet wins or public prints into permission to trade.

0b. **Weather lock stopwatch (latest owner request, 2026-10-12):** build an independent **read-only**
   observation worker, not a weather trading desk. The prospective protocol is
   [WEATHERWATCH_SPEC.md](WEATHERWATCH_SPEC.md). It watches the exact station in each Kalshi
   `KXHIGH*`/`KXLOWT*`/`KXRAIN*` market's own rules, plus the five Polymarket US high-temperature
   families, and records actual weather receipt times and ten-minute book paths. Kalshi may use the
   existing market-only WebSocket signer; Polymarket US stays on its public gateway. Public US trade
   capture is unavailable. The verified public MADIS ASOS-HFM feed has five-minute observations;
   it is not a one-minute confirmation feed. One local Midway probe lagged the valid reading by
   16.2 minutes; this is not a Railway latency result. Native MADIS one-minute OMO access is
   unverified, and arrival lag/cache limits remain measured constraints. Unsupported stations, series and
   periods stay explicit.
   Two distinct accepted readings (not two copies of one METAR) are required for confirmation;
   source/day/precision differences mean even a confirmed proxy is **not an irrevocable TWC lock**.
   Separate 97c/98c one-contract scenarios require fresh quotes surviving a modeled 250 ms delay;
   fees and actual settlements are included, but these are conditional estimates, never real fills.
   Rain uses one verified positive interval as a conservative lower bound, never sums overlapping
   rolling totals or treats missing hours as zero. Official NWS CLI products are matched to their
   actual station/climate day and compared separately from venue settlements.
   State/source evidence lives under `/data/weatherwatch/`; daily JSON/Markdown reports and a separate
   MEASURE ONLY panel retain gaps and unknown achievable cents/day. Storage is bounded and pauses at
   the cap rather than deleting the source chain. Run at least three days after verified startup;
   later sessions put verified daily findings in WORKLOG. No weather orders, amounts or money switches
   are authorized by this measurement request. Check the newest WORKLOG for shipment and actual
   startup/coverage status; deployment alone does not complete the three-day observation.

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

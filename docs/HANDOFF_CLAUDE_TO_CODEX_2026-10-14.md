# Handoff: Claude -> Codex, Tuesday Oct 13 / Wednesday Oct 14, 2026 (written ~10:45 PM PT)

The owner asked for a complete handoff so Codex (ChatGPT) takes over everything, because Claude's
subscription keeps running out of usage. This file is the whole picture: what the business is, what is
live, what is half-done, what the owner has decided, what the owner still has to decide, every rule, and
where every file is. Times are Pacific (PT) with UTC in brackets where it matters. Nothing here is a secret;
keys live only in Railway variables and are named, never shown.

Read first: `AGENTS.md` (hard rules), `docs/COORDINATION.md` (lanes + inbox), `docs/HANDOFF.md`
(general ops), `docs/SPEEDDESK_SPEC.md` (the Kalshi bot's rules), `docs/WORKLOG.md` (history, newest
first). The raw research reports Claude produced today are copied into `research/handoff_2026-10-14/`
(they only existed in Claude's scratch space before; see section 9).

---

## 1. The business in one paragraph

The owner (Sideri, they/them, works from a phone, wants plain words and real numbers) runs a small
real-money trading desk from this repo on Railway: a Polymarket US desk (real money, rule 2026-10-10a: no
sports, one bet per question) and a Kalshi 15-minute Bitcoin market-maker ("the Kalshi bot", KXBTC15M),
plus practice desks, a research pipeline, a "town" dashboard (Codex's lane) and now a practice "arena" of
bots and a read-only market recorder. The goal the owner states: a bot that grows money for real, as fast
and smart as possible; "size we earn it" (the earned-growth ladder); "make money or die" (the arena);
find edges and "hacks" honestly. Everything Claude found so far says: **no proven edge yet**, every
public bot with verifiable numbers loses, and the only live money-maker candidates are hypotheses to test
on our own recorded data.

## 2. What is LIVE right now (Railway project `nightcrawler`, id 75750847-85c0-41a3-a2a7-b7f2201a51e9)

### 2.1 Service `bot` (id f84d3b52-002f-44cb-931e-bc9e3e097e97, us-east4, 8 GB limit, volume `nightcrawler-data` 5 GB at /data)
- Deploys automatically from branch **`claude/nightcrawler-memecoin-bot-Gwnb1S`** (watch paths: src/**,
  pyproject.toml, Dockerfile, railway.json, README.md). Current tip: **6a1bf70** (PR #42, deployed 5:37 PM PT
  Oct 13 [00:37 UTC Oct 14]). Build `ba25407c-d78f-4eb3-8eed-d88c6c3d9eb6`, healthy, no tracebacks.
- Runs in one Python process: Polymarket US real desk (`polydesk_started ... LIVE: 10 contract(s) per
  order`), the Kalshi real companion (`speeddesk_live.py`), practice speed desks (ETH/SOL/XRP/DOGE 15M, paper),
  weatherwatch/skipwatch observers, trend desk (paper), the learn job, the web page (`/api/page`, the town),
  and since 4:18 PM PT the Kalshi **arena** town as a separate low-priority child process.
- **Kalshi real money status at 5:38 PM PT:** `REAL MONEY (Kalshi)`, cash **$39.80**, lifetime P&L
  **-$9.94** against a **$10 lifetime stop**, reason `total_budget` (every buy that costs more than $0.058 is
  refused), `total_halted` is **false** (see bug in 4.1), 0 positions, 0 open orders. Caps: $10 window / $20
  open / $6 day stop / $10 lifetime stop, first buy 5 contracts (`SPEEDDESK_KALSHI_CLIP=5`), maker bids at
  floor(fair-0.03), balancing to pair cap 0.99 with 25% imbalance allowance, lock from 240 s before close up
  to $0.97 (locks exempt from stops), takes OFF (`SPEEDDESK_TAKE_EDGE=1.0`), bid pull ON (1c move within 5 s
  pulls bids, 5 s hold; practice twin never pulls = control). Ladder at rung 0 (see 3.1).
- **The bot is effectively stopped on Kalshi** (at its lifetime stop). It can still send tiny bids (1 @ 4c,
  5 @ 1c) because the stop never latches (bug 4.1). Worst additional loss ~6 cents. Restarting real money is
  the owner's decision (section 5).
- Memory: plateaus ~2 GB of 8 GB; not a leak (checked, see research/handoff_2026-10-14/memory_climb_check.md).

### 2.2 Service `kalshi-recorder` (id 736b1c8a-8311-4ee0-9043-d05f508cd821, **us-west2** on purpose, 0.5 vCPU / 1 GB, own volume `kalshi-recorder-data` 5 GB at /data)
- Read-only public-data recorder, **no keys**. Deploys from branch **`claude/kalshi-recorder`** (tip 0713e41,
  live since 5:17 PM PT [00:17 UTC]; first start 3:37 PM PT [22:37:54 UTC]). Start command
  `python -m nightcrawler.kalshi_recorder run`, restart ON_FAILURE x10, draining 30 s, no healthcheck.
  Variables: `DATA_DIR=/data`, `KALSHI_RECORDER_MAX_STORAGE_MB=4608`, `RAILWAY_RUN_UID=0` (Railway mounts
  volumes as root; image runs as uid 10001), `KALSHI_RECORDER_FREEZE_SHA256=40ccfe87ed86b3fd62ee16ebba9862f8be8bbc66a229cfdc7f138ee26a305040`
  (the Family A protocol hash; writes a freeze witness row per session). It exits with code 3 if any trading
  key or `*_MODE=live` variable is ever present.
- Captures: Kalshi public books/prints/markets/settlements for the categories this account can trade
  (Crypto, Climate & Weather, Commodities, Financials; Washington state blocks the rest) at ~1.5 req/s, plus
  the KXBTC15M arena tape (72 h retention). First hour: clean, ~43 MB/hour (~1 GB/day, 5x the estimate), so
  the 4.6 GB cap fills in ~4.5 days. **Owner decision needed before Oct 20:** grow the volume (one-tap live
  resize in the Railway dashboard, volume settings; ~$0.15/GB-month; then raise
  `KALSHI_RECORDER_MAX_STORAGE_MB`) or lower KXBTC15M retention.
- Codex asked for a 48-hour feasibility report (quote survival, depth at the simulated budget, fees,
  coverage, gaps, 429 profile, storage/day, cost). **Due Thu Oct 15 ~3:45 PM PT [22:45 UTC].** Claude's reminder
  for it is now disabled; Codex owns it. Tools: `python -m nightcrawler.kalshi_recorder status|verify` inside
  the service (or read its logs), `docs/KALSHI_RECORDER.md`.
- Config-as-Code note: Railway stops reading `railway.json` on **2026-12-01**. The bot service's own settings
  already carry everything except restart policy ON_FAILURE x10; set it on the service before then (owner's
  OK first, it is a production setting).

### 2.3 Merged today (all on the deploy branch)
| PR | What | Live since (PT) |
|---|---|---|
| #35 | 5-contract first-buy cap `SPEEDDESK_KALSHI_CLIP` | morning |
| #39 | Speed part 1: bounded reconcile, timing logs, stale-bid cancels (+ review fix bba948a) | 12:48 PM |
| #40 | Earned-growth ladder (rung 0 = today's caps; +$5/window per rung after 96 windows, 2 sigma gain, house money, 24 h no stop, cash; demotion on 60% giveback; code ceiling $20 window; first buy stays 5 at every rung; owner chose "Ship at $20 now", "Keep 5 at every rung") | 1:34 PM |
| #41 | Kalshi arena: 12 practice residents in their own low-priority process, rent $0.20/day, evicted under $10 or when deskguard says losing, breed from the richest; control "Live" copies the real rules at rung 0; CANDIDATE flag at 100+ windows and paired t >= 2; page key `kalshi_arena` (contract + fixture for Codex in COORDINATION/`tests/fixtures/kalshi_arena_page.json`) | 4:18 PM |
| #42 | Bid pull (above) + two cancel-path bug fixes that also existed on base + practice-twin exceptions can never touch real cancels | 5:37 PM |
| docs | `research/kalshi_rewards/PLAYBOOK.md` (LIP playbook), COORDINATION entries | - |

## 3. Decisions the owner already made (do not re-litigate)
1. Real money is switched on or made bigger **only on the owner's explicit word with amounts named**. Code
   may switch real money off or down. Get the owner's OK before changing any production Railway variable.
2. $10 window / $20 open is "our low minimum resting number". Growth comes from the ladder (3.1), not from
   hand edits. Ladder ceiling is $20 a window in code; raising it needs the owner's word and a code change.
3. First buy stays 5 contracts at every rung.
4. Recorder runs as its own Railway service (done).
5. Standing instruction: once an arena/ML candidate proves profitable (deskguard winning AND beats the
   control over the pre-registered bar), put it live within caps and let the ladder scale it.
6. Pyth: do NOT buy the $500 Starter (crypto only, 1 s) or the Free plan (no API). The $2,500 Pro tier is
   Pyth's FX feed at 1-50 ms on EUR/USD, USD/JPY, AUD/USD only (200 ms on GBP/USD, USD/CAD) and is what Kalshi's
   market makers already use. Decision: test the half-second head start with free data first (section 7).
7. Never use anyone else's exposed API keys (owner asked; Claude refused; owner accepted). Never circumvent the
   safety classifier; stop and ask.
8. The twin/paper and arena money must never be shown as real cash, Pacific profit or town growth.

### 3.1 Ladder facts
Rung r: window = $10 + $5r, open 2x, day stop 0.6x, clip fixed 5, lifetime stop fixed $10. Promotion needs
>= 96 settled windows at the rung, gain >= 2 sigma sqrt(n) with money at risk counted as lost, house money >= 3 x
0.55 x next window, 24 h without a stop, cash for the next open budget; provisional until re-checked at the
window boundary. Demotion on giving back 0.6 x window from the rung's peak. Status line and page carry
`ladder` (`money.speeddesk.kalshi_live.ladder`). Since the bot is halted, no promotion is possible until it
trades again; 96 windows = 24 h of trading.

## 4. What is built but NOT merged (every branch is pushed to origin)

### 4.1 `claude/kalshi-stop-fixes` @ **4a9ab4a** (from 15c9457) - REAL MONEY, highest priority
Fixes the two defects the Oct 13 loss forensics proved:
- (1) strictly balancing hedge bids were counted as new risk, so the stops cut or blocked hedges (10:15 AM
  hedge 10 -> 4; 3:45 and 4:00 PM became pure one-sided bets): about $3.90 of the $6.20 lost since the ladder.
- (2) first buy now sized so its hedge also fits under the stops; nothing sent if not even 1 contract fits.
- (3) the day/lifetime stops now **latch** (today `total_halted` never flips, tiny bids still go out, a resume
  token applied while not halted is silently consumed).
- (4) the owner's day reset also reaches the practice twin (the twin froze at -$6.88 all day).
Build: 4,956 tests pass, mypy/ruff clean, 16 new tests; replay of Oct 13's 29 windows: -$7.91 instead of -$11.92.
**Reviews done:** caps (adversarial, 30 seeds x 110 windows: no cap/stop breach) and crash/restart.
**NOT done (Claude ran out of usage):** the strategy-effect replay review and the fix round. **Open findings
to fix before merging:**
- MAJOR A: stops latch permanently on *provisional* exposure (pending bids / unsettled windows), not on
  realized loss; a window that later wins leaves the halt in place and needs a new resume token. Suggested
  fix: latch only when realized loss + $0.98 >= stop (the Oct 13 -9.94 case still latches), or clear a
  provisional latch when the exposure resolves without a loss. Reviewer repro tests are listed in
  `research/handoff_2026-10-14/stop_fixes_build_and_reviews.md`.
- MAJOR B: a latched stop cancels the resting strictly-balancing hedge and refuses a new one, so the end lock
  pays the ask (worse expected loss; contradicts fix 1's own rationale). Fix: exempt strictly balancing bids
  from `_cancel_unsafe`'s stop reason and allow `risk == 0` buys while latched (budget, cash, pair cap,
  imbalance still apply).
- MINORS: tiny adds still go out while the lifetime stop binds without a latch (call `latch_bound_stops` in
  `_watch_stops` each step); floor mismatch $0.98 vs real pair cost ~$1.0072; a duplicate "latched at start"
  receipt on every restart while halted (seed `stop_state` from the restored book); day-stop status text;
  comment/code mismatch at `speeddesk_live.py:1532`.
Then: merge the deploy tip (6a1bf70: arena + pull) into it, full suite, PR titled "... (touches real
money)", merge at a safe minute, verify the deploy. Only after this should the owner's restart be set up.

### 4.2 `claude/kalshi-fix-speed` ("speed part 2") @ **1a461fe** + an in-progress merge of 6a1bf70 - REAL MONEY
Steps 0-4 and 8 of the speed plan plus loss-plan bugs 1-3 and the 60-second settlement-average fair value:
instrumentation, bounded reads with a 60 s full scan, one synced pre-send journal row (full saves at most once
a second), O(1) tape + sigma cache (step stays ~0.6 ms as history grows; was 57 ms after a week), Coinbase
Exchange matches primary with Advanced Trade failover and 250 ms skew allowance, external-api.kalshi.com for
signed calls + one requests.Session per thread, per-window release of journaled-but-unsent orders (fixed a
"frozen for good" bug). Measured locally: step 0.6 ms at 7 days of history (was 57 ms), complete reconcile
16-72 ms (was 0.2-1.7 s), 13 full saves/min (was 60). Two review rounds + a 4-lens rebreak passed (2b84ad6);
merged with the arena (1a461fe, 5,074 tests, skeptic-verified clean).
**Branch tip now: 96e5e9c** = the merge of 6a1bf70 (bid pull) into speed part 2, committed and pushed by Claude
after the full suite passed (exit 0). The deliberate conflict was the pull's single `KalshiLiveDesk._fair`
helper vs speed's four `settles_on_average` edits; resolution: `_fair` carries the settlement-average logic
once and every call site (decide, pull watch, send guard, stale-bid reason, lock) goes through it.
**NOT done:** the combined-path adversarial attack (cancel/reconcile/release + pull; fair/decide + pull +
feeds). Do that before merging; then PR + safe-minute merge. Deferred minors are in WORKLOG.

### 4.3 `claude/kalshi-recorder` @ 0713e41 (running on the recorder service) - merge into the deploy branch
Adds `kalshi_recorder*.py`, `kalshi_public.py`, `kalshi_familya*.py` (Family A replay with a pre-registered
protocol `research/kalshi_edge_search/PROTOCOL.md`, TEST gate via FREEZE.json + recorder freeze witness), an
8-line engine hook that is OFF unless `KALSHI_RECORDER_ENABLED=true` and refuses next to live trading or
Kalshi account keys. Two review rounds + rebreak; 5,059 tests. Merging it into the deploy branch changes
nothing for the bot (hook off) and lets the recorder service track the deploy branch afterwards.

### 4.4 `claude/kalshi-recorder-fx` @ d295391 (from claude/kalshi-recorder) - UNREVIEWED
Recorder LIP lane: all 14 reward-program books (5 FX 15M, copper, platinum, palladium, natgas, 5 Coin Race)
at 1 s via the batch book call, program snapshots every 15 min, prints, **and Kalshi's free settlement price
series** (section 7), plus a Pyth Hermes SSE lane gated on `PYTH_API_KEY` (no key = silent off; key never
logged). Needs: safety review (key never on disk/logs; 2 req/s budget), fidelity, capacity, then merge into
`claude/kalshi-recorder` and redeploy the recorder.

### 4.5 `claude/kalshi-lip-practice` @ ff852eb (from 6a1bf70) - UNREVIEWED, OFF by default
`research/kalshi_rewards/leadlag.py` + `PREREG.md` (pre-registered lead-lag analysis), `lip_score.py` (exact
LIP scoring, checked against the playbook's $1.90 example), `lip_desk.py`/`lip_feed.py`/`lip_practice.py` (a
practice LIP desk with three policies: rest at Reference, rest at best bid, pull-when-Pyth-moves), page block
for Codex (fixture `tests/fixtures/kalshi_lip_practice_page.json`). Note: one test contains a fake
fake API-key-shaped test string (a vendor prefix plus forty letter b) that trips naive secret scanners; it is not a key. Needs the three reviews before
merging; stays off until a fast FX feed exists.

### 4.6 `claude/kalshi-arena-feed` @ 5a84275 - WIP, UNREVIEWED, tests not run
The arena learns nothing yet: the live loop hands only ~67% of the Kalshi feed to the town
(`ArenaLink` PENDING_MAX 1024 / FLUSH_MAX 256 vs ~700 events/s), late batches, and every window since 4:18 PM
was voided `feed_dropped`. This WIP raises buffers, coalesces books, adds process RSS to `kalshi_arena_feed` /
`kalshi_arena_status` (`procmem.py`), and streams the learn tape seal (today `learn/tape.py seal()` reads a
day's tape into memory twice, ~1.5 GB transient daily around 5 PM PT in the real-money process). Rule for this
work: **zero added work on the live loop** (measure p99 step gap vs the deploy tip). Treat as a draft.

### 4.7 Older local-only branch in the main checkout: `claude/kalshi-family-a` (3b40aa7)
The Family A protocol agent committed there before the recorder branch superseded it. Safe to delete.

## 5. Decisions the owner still has to make (put these to them plainly)
1. **Restart Kalshi real money?** Options: (a) stay stopped until 4.1 is fixed and merged, then restart with
   a fresh $10 lifetime budget and the same caps (owner must say the numbers); (b) switch to paper now
   (`SPEEDDESK_KALSHI_MODE=paper`; the "off" direction, allowed on the owner's word); (c) restart now with a
   workaround (not recommended; the hedge bug is live). Mechanics today: because the stop never latches, the
   documented resume token is **consumed silently** if set while not halted; the only working path on the
   current build is one deploy that lowers `SPEEDDESK_KALSHI_TOTAL_STOP_USD` to <= 9.94 AND sets a never-used
   `SPEEDDESK_KALSHI_RESUME_TOKEN` (the ladder's startup check latches, then the token clears). After 4.1 lands,
   startup latches first and a fresh token is applied and logged.
2. Recorder volume growth before Oct 20 (section 2.2).
3. Daily step-up check: the owner said "when it's winning go $20 a window $40 open $12 daily"; the ladder now
   implements the bar; Claude's daily reminder (8:20 AM PT) is disabled. Codex should report the status line
   daily in plain words.
4. The Dec 1 railway.json settings move (section 2.2).

## 6. Research results (all copied to `research/handoff_2026-10-14/`)
- **Loss forensics Oct 13** (`loss_forensics_oct13.md`, `windows.csv`, `orders.csv`): 29 windows 9:00 AM-4:15 PM
  = -$11.92 to the cent; pairs from resting bids +$10.32; 14 lock-finished pairs -$17.01; one-sided leftovers
  -$4.60; fees $0.63; no order broke a rule; 23 of 27 lopsided windows had the extra on the losing side (chance 2
  in 10,000: adverse selection, the bids fill on the falling side); day reached -$11.01 only because of the owner's
  5:49 AM day reset. Defects -> branch 4.1.
- **ML toxicity / pull guard** (`toxicity_ml_verdict.md`): NO. Predicts fills (AUC 0.88) not bad fills
  (AUC 0.52-0.57); ML pulling loses 21-75c/window at every cancel speed; random pulls beat it; simple 1c/5s
  rule ~0 (-31 to +44c); TEST set (newest 23 windows) sealed, never opened. Refit after 2-3 weeks of recorder
  books. Without any pull the current bot lost 23-50c/window in the 1.5-day replay.
- **Kalshi rewards (LIP)** (`research/kalshi_rewards/PLAYBOOK.md`, `rewards_lip_mastery.md`): none on
  KXBTC15M; FX 15M $50/period, metals/natgas/Coin Race $20; snapshot every second, reference = first level
  reaching Target/5, score halves per cent below reference, both sides must reach Target, $1 minimum payout,
  paid a day+ later. Net about **-$457/day per FX pair** after fills; 0 of 192 quoting styles profitable; only a
  >= 0.5 s head start on FX moves could flip it. NO-GO for real money.
- **Feed hunt** (`fx_feed_hunt.md`, `fx_feeds_results.json`, `fx_feeds_paid_catalog.json`, `kalshi_pyth_value.md`):
  no free millisecond Pyth. Pyth Hermes needs a paid key since Aug 26, 2026. TrueFX (free, polled 0.5 s) sits
  within 0.05 pip of Pyth and shows the direction of Kalshi's next Pyth print ~0.5 s before Kalshi publishes it
  (3-10 min of quiet-hour EUR/USD: hint, not proof). Kraken fiat pairs fastest but 2 pips off and 1-2 s behind
  bank quotes. Paid: Tiingo $30/mo (pushed bank quotes), IBKR free 5 ms (needs their gateway), CME FX futures
  via Databento ~$235/mo, Pyth Pro $2,500/mo. Most retail FX brokers don't take US residents.
- **Quick head-start look** (`fx_quicklook_leadlag.md`): 20 quiet minutes, TrueFX vs Kalshi books polled
  2.6-6.5 s (shared-IP 429s): no lead either way beyond ~0.2-0.3 s. Needs busy-hour 1 s books from the
  recorder's own IP.
- **FX stack research** (`fx_lip_research.md`): **Kalshi publishes its settlement price series for free**:
  `GET /trade-api/v2/live_data/events/{event_ticker}` (no key) returns the last hour of the underlying at 1 s
  resolution; `expiration_value` == value at `close - 1 s` in 36/36 settled windows. FX settles on the close of
  the 1-minute Pyth candle at window close (tie pays YES, no averaging); Coin Race settles on CF Benchmarks.
  Kalshi also sells an authenticated `pyth_value` WebSocket channel for **$1,000/month, first 7 days free**
  (FX coverage unverified). Request budget: adding the 14 LIP tickers to the existing 1 s batch book call costs
  0 extra requests; total ~1.52 req/s of the 2.0 ceiling.
- **Public Kalshi bots sweep** (`kalshi_public_bots_sweep.md`, result 3 is the report): no public bot with
  verified live profit; every verifiable live number is a loss; 8 things worth taking (check `fee_type` on
  KXBTC15M via /series; score the maker with fill bands + 30 s markout + settlement by time-to-expiry bucket and
  pre-registration; the statistics kit (market-null bootstrap, drift check, Bonferroni, one look at TEST); risk
  rails: measure losses from balance changes, Kalshi's order-group auto-cancel, "blind means flat", pull 30 s
  after a 6c move in 20 s). Glimmer to test: last-3-minute resting quotes and NO-side bids did better in two
  independent records (unproven).
- **Hidden geniuses sweep** (`hidden_geniuses_sweep.md`, 4 lanes + 8 of 16 proofs; plan/verify not run):
  Polymarket wallets are public, so claims were checked on-chain. Verified A-grade: @b00k13 (+$6,026 since Jan
  2026, sports/esports maker + hedge arb from de-vigged sportsbook odds; fill rate decayed 37% -> 1%); @1kto1m
  (+$49.6k since May 2026 on 5/15-min BTC Up/Down, maker-only early-window entries, T-90 s cutoff, decaying to
  flat by Oct); gabagool22 (+$868k Oct 2025-Feb 2026 buying BOTH sides of 5/15-min BTC/ETH in tiny clips at
  median 99.2c per pair, stopped two weeks after Polymarket's fee/rebate overhaul). Lessons: maker-only,
  sub-cent pair edges times volume, fee changes kill tricks, everything decays. Owner rule 2026-10-10a still
  bans real money on sports.
- **Memory check** (`memory_climb_check.md`): no leak; ~2 GB plateau predates the arena; watch rule: slope
  > 0.5 GB/h after 2 h or > 3 GB.
- Earlier labs (in repo): Lab 4 near-certain grind no edge; Lab 5 crypto fair-value no edge; Lab 6 sports vs
  Pinnacle no edge; Lab 7 in-and-out no edge; edge search H-F no direction signal beats the Kalshi price (6,700
  variants); weekend-favourites lead is paper-only.

## 7. The plan Claude was executing (in priority order) - Codex decides what to keep
1. Fix 4.1's two majors + minors, merge base, full suite, PR, safe-minute merge, verify. Then the owner's
   restart decision.
2. Finish 4.2: combined-path attack, then PR + merge. Expected result: trade-to-ack well under the 0.5 s target
   (part 1 measured median 0.39 s decision->ack and 0.45 s BTC->decision all-day before part 2).
3. Merge 4.3 into the deploy branch (no behaviour change), point the recorder service at the deploy branch.
4. Review + merge 4.4 into the recorder branch and redeploy the recorder, so busy-hour 1 s LIP books + the
   free Kalshi 1 s price series + a TrueFX lane (free, 0.5 s polls) are captured. Then the real head-start test:
   does the FX price (TrueFX / Kalshi's own series) move >= 0.5 s before Kalshi's market makers reprice, at busy
   hours? If rarely: the rewards route is dead, say so. If often: Tiingo ($30) first, Pyth Pro only if the numbers
   demand it; then the practice LIP desk (4.5) in the arena for ~800 FX periods; a real-money canary (1 pair, 10/side
   = $9.70, $10 day stop) only on the owner's word and only after the pre-registered bar.
5. Fix the arena feed drop (4.6) so the 12 practice bots actually learn; zero live-loop cost.
6. Recorder 48 h report Thu 3:45 PM PT; Family A TRAIN starts 2026-10-20 per the protocol.
7. Weekend favourites: log the frozen rule with no money; download 7 unseen weekends (Jun 19-Aug 2).
8. Later: shard-aware cash, step 5 of the speed plan (reconcile as its own task / never gate cancels; practice
   first), private WebSocket fills, amend, own process; Dec 1 railway.json move.

## 8. Rules of the road (how Claude worked; keep them)
- **Safe merge minutes** for anything that deploys: :02-:10, :17-:25, :32-:40, :47-:55 past the hour (UTC or
  PT, same minutes). Never within 2 min of :00/:15/:30/:45 nor in the last 4 minutes of a 15-minute window.
- Every real-money change: tests that pin the safety behaviour, full `python -m pytest -q` (about 5,000
  tests, ~4 min; use `--basetemp` on /dev/shm if the disk is tight), `mypy src/nightcrawler`, `ruff check` on
  changed files, PR title says "touches real money", PR body follows `.github/pull_request_template.md`
  (LIVE ON MERGE first). Claude's pattern: build -> independent reviews -> fix -> adversarial "rebreak" -> merge.
- Before every push: scan the diff for secrets. Never commit `.env`, tokens or key values. Never run Railway
  list-variables.
- After every deploy: match Railway's active deployment to the merged SHA, read fresh startup logs
  (`polydesk_started ... LIVE`, `kalshi_arena_started`, `speeddesk_live_status`), no tracebacks. Railway
  `get-logs` results can be 100 KB+; always filter narrowly and keep limits small.
- Kalshi public API from a shared sandbox IP gets 429s at ~1-2 req/s; the recorder's own IP is the clean
  measurement path. Binance.com is geo-blocked for US; do not work around geoblocks.
- Owner's "stop" = real money off (see AGENTS.md rule 5; Kalshi needs `SPEEDDESK_KALSHI_MODE=paper` too).
- Talk to the owner in Pacific time, 12-hour clock, plain words, real numbers; say when something failed.

## 9. Where things are
- Repo: `sideriapostolou-lgtm/Claude`, deploy branch `claude/nightcrawler-memecoin-bot-Gwnb1S`. Branches in 4.x.
- This handoff + the research copies: `docs/HANDOFF_CLAUDE_TO_CODEX_2026-10-14.md`, `research/handoff_2026-10-14/`
  (each `*.md` there is the full output of one of Claude's review/research workflows, labelled by result; the
  `.csv/.json` are the data behind the forensics and the feed hunt).
- Claude's scratch worktrees (will vanish with its session; everything that matters is pushed):
  `/home/user/Claude/.claude/worktrees/wf_1715affd-aea-1` (speed), `/tmp/.../scratchpad/stopfix/wt`,
  `/tmp/.../scratchpad/fxlip/{rec,desk}`, `/tmp/.../scratchpad/arenafix/wt`.
- Claude's self-reminders are disabled: `trig_01EJ2VYn9zPTghic4QacE3TP` (48 h report), `trig_01J39TE9gTiEz1WSFPpNEqX1`
  (daily step-up check). Codex owns both jobs now.
- GitHub PRs today: #35, #39, #40, #41, #42 (all merged). Earlier: #14 cancel-404 fix (pending), #23 strike
  fix, #26-#30 speed/caps, #34 Codex town restart that hit a lock period (hence the safe minutes).

Status: Claude stands down. Codex: read this, then post in `docs/COORDINATION.md` what you take first.

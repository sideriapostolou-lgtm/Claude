# Work log

One entry per working session, newest first. Every AI worker (Claude, ChatGPT/Codex) adds one before stopping.

Template:

```
## YYYY-MM-DD HH:MM UTC, <worker>, branch <branch>, PR <#>
- Changed: ...
- Verified: (tests run and their result, logs checked)
- Not verified / skipped: ...
- Real money touched? no / yes (what, on whose word)
- Next step: ...
```

## 2026-10-12 20:08 UTC, Codex, branch codex/kalshi-live, PR #9
- Owner authorization: the current handoff supersedes the earlier pause and practice-only restriction for
  **Kalshi KXBTC15M only**. Built the requested live-capable companion and will deploy it **PAPER by default**.
  The existing Polymarket real desk, `polydesk.py`, Marco settings and public speed-desk practice trial are
  unchanged. Original practice continues; positive-after-fees evidence has not been established.
- Changed: separately gated Ed25519 client for the documented V2 event-order API, durable real-fill ledger,
  serialized execution controller, and an honest twin of live decisions. Unique prefixed intents/reservations
  are saved before HTTP; timeout/5xx creates are reconciled rather than retried. Actual fills, fees, net
  positions and venue settlement timestamps drive real inventory and locked/directional results.
- Limits: $2/window including fees and pending orders, $4 across windows, $3 UTC daily loss plus money at risk,
  $5 total stop requiring a never-used resume token. The first clip preserves room for its opposite side.
  Cancels cover startup, cutoff (180 s default), stale BTC (>3 s), mode/auth/error/risk stops and shutdown.
  Requests in flight are drained; cancellations keep reservations until terminal status and fills agree.
  Resting orders expire after at most 30 s as a fallback. Process lock and journal validation prevent an
  overlapping or corrupt controller from resetting the budget. Real exposure survives switching to paper.
- API/fee evidence: official current OpenAPI, V2 orders, fee-rounding guide and July 7, 2026 fee schedule,
  plus current KXBTC15M series/rules checked. Kalshi nets opposite holdings; gross actual fill lots retain
  attribution while signed net positions reconcile. No actual credentials or private account calls were
  used during development; signing tests use generated throwaway keys, all execution tests use fakes.
- Important unresolved account fact: primary subaccount 0 and an Ed25519 key do not prove Direct membership.
  Asked the owner whether the account was opened directly with Kalshi or through a broker/FCM; no answer yet.
  Added factual `SPEEDDESK_KALSHI_ACCOUNT_TYPE=unknown|direct|fcm`, default unknown. Unknown/FCM reserves the
  worst whole-cent rounding on each possible .01-contract fragment, which prevents every positive-edge
  candidate. `direct` is only for a confirmed Direct account, not a permission or a shortcut around fees.
  The two live switches alone therefore do not guarantee trading while this fact remains unknown.
- Page: separate REAL MONEY (Kalshi)/PRACTICE companion with actual cash, fees, exposure, caps/stops and real
  versus twin results. Existing Polymarket cash and town totals do not include Kalshi or pretend profit.
  Stale evidence or revoked current settings cannot claim live buying. Failed callbacks/panels are isolated
  from the practice trial, close the send gate immediately and trigger cleanup. Worker-thread send guards
  read atomically published copied market inputs; gaps invalidate them before any checkpoint disk work.
- Verification: final full suite **3,406 passed, 21 skipped** (12 opt-in network tests and 9 optional
  scientific dependencies). Source mypy passed all 91 files; Ruff passed all 19 changed Python files.
  Added-line secret scan found no credential patterns, key material, JWTs or long random literals. Independent client/model/controller/runtime/UI review found and fixed
  cancellation races, stale fee/input guards, terminal-evidence recovery, token replay and UTC attribution.
  Synthetic browser checks at 320/390/1280 px passed, including actual cash separate from simulated P&L.
- Real money touched? Authorized real-money capability/configuration and service restart, **no activation**,
  no real order and no Railway variable/key change in this session. Four switches remain necessary, including
  a successful balance read this run. Kill switch: `SPEEDDESK_KALSHI_MODE=paper`; open fills still settle.
- Deploy verified at 20:14 UTC: PR #9 merged as **38d8a42e35ca5a13920b288299e7375c25077417**.
  Railway deployment `951a04c7-34c4-49dc-8a9d-5791c1b89c24` reached SUCCESS on that exact commit. Startup
  at 20:11:55 UTC logged `speeddesk_live_status` mode=paper/configured_mode=paper, PRACTICE, authenticated=false,
  real_orders_available=false, no pending orders/exposure, and all four owner dollar limits. Cash is unknown,
  not a new confirmation of the earlier $25 balance. Existing `polydesk_started` remained LIVE at 10 contracts.
  Deployment-scoped traceback/halt/state/error searches returned no application matches; only the Railway CLI
  config deprecation warning. `/healthz` returned HTTP 200/ok after this deployment reached SUCCESS.
- Day 0 partial snapshot at 20:12:55 UTC: original **Kalshi** and **Polymarket US** trials each retain 0
  traded/settled windows, 0 fills/attempts, $0 locked/directional settled P&L. Worst window, fill rates and
  decision-to-fill latency are unavailable until trades occur. Both public trade feeds connected, problem=null;
  Bitcoin age 0.925 s, book age 0.085 s, mean shared Bitcoin feed delay 113.51 ms. Fresh/maker coverage since
  instrumentation: US 2,719.84/2,711.42 s; Kalshi 2,718.44/2,718.08 s. Volatility is still warming up: enough
  elapsed clock time alone does not satisfy the required 3,000 observed adjacent one-second returns. Original
  trial start `1791831625.5335124` survived the restart; no profitability/trading result is inferred from uptime.
- Pending: owner confirmation of account fee type and sufficient observed volatility data. After
  those, the owner sets `SPEEDDESK_KALSHI_MODE=live` and `SPEEDDESK_KALSHI_LIVE_CONFIRM=yes`; watch the first
  real windows and report orders/fills/fees/P&L/anomalies. No real execution/profit result is claimed here.
  We copy rules, not the original bot's speed, venue or size; small losses are the likely paid-experiment
  outcome. The $5 budget is a code risk limit, not an absolute promise against exchange/network failure.

## 2026-10-12 19:33 UTC, Codex, branch codex/speed-desk
- Changed: pulled first and read Claude's Kalshi account/signing handoff in `docs/ACCOUNTS.md` and spec
  section 2b. His `d80424f` is already included. Recorded the explicit restriction: **public REST only,
  PRACTICE ONLY; do not add code that reads Kalshi credentials or places Kalshi orders**. Claude's read-only
  account/key verification is attributed to his handoff, not a new account check performed here.
- Current application is the later reporting release `c329133`, preserving the trial started before the
  clean `1e45cc3` startup. No app files changed. At 19:32:50 UTC, each venue still had 0 traded/settled windows,
  0 fills, $0 locked-pair and $0 directional settled practice P&L, and 0 take/rest attempts. Worst window,
  take/maker fill rates and decision-to-fill latency remain unavailable until trades occur.
- Live evidence: both trade streams connected, warming-up status, problem=null, real_orders_available=false;
  Bitcoin age 0.430 s and book age 0.433 s. Shared mean Bitcoin feed delay: 116.0 ms. Fresh-data/maker coverage
  since instrumentation: US 352.66/346.05 s; Kalshi 351.69/351.69 s. Partial-day flags remain true. US fallback
  retains its last HTTP 429 status while the primary WebSocket is connected and supplying fresh books.
- Verification: latest Railway heartbeat read; application tree identical to the previously tested release.
  Documentation-only diff and secret scan passed; no code tests rerun, no credentials read, no settings or
  real money changed. This WORKLOG push does not match the app's watched deploy paths.
- Pending: at least three days of practice evidence and daily per-venue reporting. Warm-up requires a full
  hour plus at least 3,000 observed adjacent one-second returns; a clock time does not guarantee a practice
  fill. The positive-after-fees requirement and owner's exact dollar amounts still gate any future real work.

## 2026-10-12 19:30 UTC, Codex, branch codex/speed-desk
- Changed: recorded the owner's instruction to retain the existing Kalshi Ed25519 key and keep the speed
  desk **PRACTICE ONLY**. The key type is the owner's report; no credentials were inspected, changed, deleted
  or stored, and no signing benchmark was run. The Kalshi practice adapter continues to use public data only.
- Day 0 partial snapshot, 2026-10-12 19:29:50 UTC: **Kalshi** has 0 traded/settled windows, 0 fills, $0 locked-pair
  and $0 directional settled practice P&L; **Polymarket US** also has 0 traded/settled windows, 0 fills,
  $0 locked-pair and $0 directional settled practice P&L. Both have 0 take/rest attempts. Worst window,
  take/maker fill rates and fill latency are unavailable with no trades; none is reported as a successful zero.
- Feed evidence: both venue trade streams connected, Bitcoin age 0.377 s, book age 0.415 s, warming up Bitcoin
  volatility, problem=null and real_orders_available=false. Shared mean Coinbase feed delay was 117.4 ms.
  Shared observed uptime was 1,750.42 s. Since per-venue instrumentation began at 19:26:50, fresh-data coverage
  was 172.55 s per venue; maker coverage was 166.09 s on US and 172.55 s on Kalshi. Days remain marked partial.
  US REST fallback's last status was HTTP 429/rate_limited; the primary market WebSocket remained connected
  with fresh books. This is warm-up evidence, not a profit result.
- Verified: latest branch pulled; Railway still runs successful application commit `c329133` in deployment
  `c4e7918e-e3cf-4cbc-b4b1-cf1253c7040d`. Previous docs-only `41e7881` was SKIPPED as expected. Independent
  read-only review confirmed the paper-only guard and public Kalshi adapter remain unchanged. The prior
  session's passing tests/mypy/changed-file Ruff apply to this unchanged application tree; no Python file
  changed and no code checks were rerun for this documentation-only entry. Diff and secret scan checked.
- Real money touched? No. This session changes only WORKLOG and requests no deployment or settings change.
- Next step: continue the 3+ day practice observation and record daily per-venue results here. Real speed-desk
  orders remain unavailable; the owner's exact dollar amounts and positive practice after fees are still required.

## 2026-10-12 19:24 UTC, Codex, branch codex/speed-desk, PR #8
- Changed: pulled the latest deploy branch (`2a7dbd0`) and reviewed the Kalshi section 2b addition. Both venue
  adapters were already deployed; this follow-up adds the owner's requested daily reporting **per venue**.
  Kalshi KXBTC15M and Polymarket US 15m/1h share the existing strategy, honest practice fills and practice
  budgets. Kalshi still uses public GET requests only, with books capped at two requests/second and verified
  settlement/tie/fee rules. No Kalshi account credential is read by this adapter.
- Reporting: `today.venues` and each completed report's `venues` distinguish Kalshi from Polymarket US.
  Each reports traded/settled windows, fills, fee-inclusive locked-pair versus direction P&L, worst window,
  unique-order fill rates and latency. Venue attribution is persisted; order rates follow placement-day
  cohorts, while fills and settlements use their actual UTC day. A late fill corrects the earlier rate with
  an audited, idempotent `speeddesk_daily_correction` receipt. Existing combined metrics remain available.
- Honesty: per-venue fresh-book/Bitcoin and maker-tape coverage is separate from shared app uptime and
  Coinbase latency. Old coverage is not inferred, and old combined-only activity has unknown venue figures;
  the existing empty warm-up can retain exact zero counts. Missing feeds and partial days stay visible.
  Restarts preserve results, counters and coverage. Historical reports remain on the page and in daily
  receipts; heartbeat logs no longer repeat the growing completed-day history every minute.
- Page: separate PRACTICE cards and expandable completed-day history, with fill rates, latency and coverage
  details. None of these numbers enters real cash, real P&L or town goals. Browser checks with synthetic data
  passed at 320, 390 and 1280 pixels, with no overflow/errors; expanded details survive refresh.
- Verified: full suite 3,165 passed, 21 skipped (12 opt-in network checks, 9 missing optional scientific
  dependencies). The latest 113 model/runtime/integration tests also passed, plus a final 17 runtime checks
  after trimming historical reports from heartbeats. Mypy passed on all 88 source files; Ruff passed all
  seven changed Python files. Independent adapter/reporting review found no blocking issue; added-line
  secret scan found no matches. Checked open PRs; unrelated town PR #6 remains untouched.
- Real money touched? This authorized push restarts the live service. No real-money code, settings, amounts,
  keys or Railway variables changed. The speed desk has no real-order path; existing polydesk stays LIVE
  at 10 contracts, and Marco stays off. Practice budgets and the loss stop remain shared across venues.
- Deploy verified: PR #8 merged as `c329133ce5aea5654524e7a876fd668aea3ab852`. Railway deployment
  `c4e7918e-e3cf-4cbc-b4b1-cf1253c7040d` reached SUCCESS on that exact commit. At 19:26:50 UTC, startup
  logged speeddesk practice/real_orders=false and `polydesk_started ... (LIVE: 10 contract(s) per order)`.
  The prior trial start `1791831625.5335124` survived the restart. Coinbase and the US market socket connected;
  Kalshi logged public REST with books_max_hz=2. `/healthz` returned HTTP 200/ok.
  Deployment-scoped searches for tracebacks, speed-desk halt/state failures, US socket disconnect/errors and
  error-level logs found no matching application lines; only the Railway CLI's config-format deprecation notice.
- Day 0 snapshot at 19:27:50 UTC: both venue trade streams true, Bitcoin age 0.155 s, book age 0.592 s,
  warming-up status and no problem. **Each venue** reports zero traded windows, zero fills, $0 locked-pair
  and $0 directional practice P&L. Worst window, fill rates and fill latency remain unavailable with no trades.
  Shared mean Coinbase feed latency was 118.4 ms. Since instrumentation began at 19:26:50, fresh-data coverage
  was 56.86 s per venue; maker coverage was 50.41 s on US and 56.86 s on Kalshi. Partial day is explicit.
  This verifies wiring and restart preservation, not profit or a completed trial.
- Pending: the three-day practice observation is still running, not passed. Daily reports are generated in
  the app and receipts per venue. Automatic chat delivery still lacks persistent Railway access in this
  environment. Preserve Claude's existing 19:45 UTC Bitcoin-filter check. Positive practice after fees for
  3+ days and the owner's exact dollar amounts are both required before any real-money speed desk work.

## 2026-10-12 18:55 UTC, Codex, branch codex/speed-desk
- Changed: built the owner's speed desk in practice only, including Claude's concurrent `df66c13` Kalshi
  adapter addition. Coinbase BTC-USD ticks drive the normal-CDF fair value and observed one-second volatility.
  Polymarket US uses its SDK market WebSocket and authenticated trade prints; Kalshi uses public books and
  actual, paginated trade prints. US fallback books are capped at 1 request/second; Kalshi books at 2/second.
- Safety and accounting: there is no speed-desk real-order implementation, and `SPEEDDESK_MODE=live` is rejected.
  Tests poison the SDK order resource and exercise fills, queue depletion, cancellation, settlement and shutdown.
  The owner explicitly approved one starter clip, followed only by balancing buys until within the imbalance cap.
  Independent practice caps are $20/window, $20 across open windows and a $10 settled-loss stop at UTC midnight.
  Pending reservations, partial fills, pair costs and venue-specific fees count toward those limits.
- Honest fills: takes use the first eligible book observation after a minimum 250 ms; REST requests must start
  after that delay and actual latency is reported. A missing ask cancels, and a later rebound cannot fill that
  old decision. Resting bids consume actual sell-aggressor trade volume only after the queue ahead; no fills
  from a price touch. A gap cancels queues, and one venue cannot borrow another venue's stream permission.
  US maker rebates follow the documented independent per-fill half-even cent rounding; Kalshi follows its
  July 7, 2026 fee schedule (cost plus fee rounded up to $0.0001). Unknown rules/fees do not qualify.
- Persistence/reporting: `/data/speeddesk/receipts.db` commits receipts and state together, then mirrors
  `/data/speeddesk/state.json` atomically. Restart preserves fills/results and cancels pending simulated orders.
  The separate PRACTICE page reports traded/settled windows, fills, locked-pair versus directional P&L after
  fees, wins/losses, worst window, unique-order fill rates and actual latency. UTC daily reports include observed
  time and partial-day flags; current plus the latest 31 reports are in `/api/page`. No pretend dollars enter
  real account cash, real profit or the town's goal.
- Verified: full suite 3,148 passed, 21 skipped (12 opt-in network tests; 9 optional pandas/numpy/scipy cases).
  A further 161 focused speed-desk tests passed after the final first-recheck, request-timestamp, retry and
  venue-terms changes. Mypy passed on all 88 source files; Ruff passed on all 19 changed Python files. Independent randomized review ran 15,000 decisions/
  partial-trade steps without breaking the reserved $20 budget or fee-inclusive pair cap.
  Phone/dashboard fixture checks passed at 320, 390 and 1280 pixels, without console errors or horizontal overflow.
- Public live checks: actual Coinbase ticks, both venues' metadata/books and settlement endpoints worked; Kalshi
  actual trade prints worked. A 20-second whole-runtime check warmed up without a fill or traceback. US public
  fallback reproduced HTTP 429 after a short burst, so it records the status and backs off 30 seconds; it never
  fills against stale fallback data. The primary authenticated US stream requires production verification.
- Real money touched? Shared configuration and startup wiring change under the owner's explicit build/push
  instruction; this deploy restarts the existing real-money bot. Its trading rules, caps and order paths are
  unchanged, and Marco remains off. No Railway variables or credentials were changed or stored.
- First deploy: Railway deployment `df62a929-dab5-469c-a287-294b858e4f42` reached SUCCESS on exact merge
  `6937e54e90fea9ce3bb08c7a85684b771d5fdb74` (PR #7). At 19:00:25 UTC, polydesk logged LIVE with 10 contracts
  and speeddesk logged practice/real_orders=false. Coinbase and Kalshi live data arrived. Verification caught
  repeated TypeError reconnects in the authenticated US feed: environment loading wraps credentials as `Secret`,
  while the SDK expects strings. The correction unwraps them only inside the in-memory SDK authentication
  boundary. A new regression exercises the actual SDK's signing and WebSocket classes with a fake transport;
  it also poisons the order resource. No credential values were logged, stored or changed.
- Follow-up checks: full suite 3,154 passed, 21 skipped; mypy on 88 source files and changed-file Ruff passed.
  The follow-up also labels a single stale venue as degraded rather than pausing the whole desk, and skips
  settled windows during decision loops so a three-day history does not create quadratic work. A 1,000-window
  regression retains all accounting/history while checking only active windows.
- Corrected deploy verified: Railway deployment `e8bcd674-e5ed-4584-b24f-8ffb222c47ba` reached SUCCESS on
  exact commit `1e45cc34809f2b6fef1835616687b2a82b0c9b42`. At 19:08:05 UTC its logs show speeddesk practice,
  `real_orders=false`, and `polydesk_started ... (LIVE: 10 contract(s) per order)`. Coinbase and the authenticated
  Polymarket US market WebSocket connected. At 19:09:05 UTC both venues reported verified trade streams,
  Bitcoin age 0.400 s, book age 0.286 s and warming-up status with no problem. Deployment-scoped Traceback,
  speeddesk halt/state-error, market disconnect/error and error-level searches found no matching application
  log lines. Public `/healthz` returned HTTP 200/ok. The unchanged trial start timestamp proves restart recovery.
- Final focused regression run: 163 speed-desk tests passed, including the actual SDK signing/connection path,
  first-recheck timing, per-venue reconnect isolation, persistence and the 1,000-window history case.
- Day 0 snapshot (19:09 UTC): 0 windows traded, 0 fills, $0 locked and $0 directional settled practice P&L.
  Worst window, fill rates and fill latency are unavailable because there are no trades yet. Mean observed
  Bitcoin feed latency was 126.6 ms. This is warm-up evidence, not a profitable trial result.
- Synced Claude's concurrent docs-only `d80424f` (Kalshi account/key-name notes); Railway marked that commit
  SKIPPED, leaving the verified application deployment above active. This adapter continues to use public
  Kalshi data and does not read the new account credentials.
- Pending: at least 72 hours of practice observation; a conservative review cannot occur before
  2026-10-15 19:09 UTC, and gaps/insufficient evidence must extend the trial.
  Volatility needs a full hour and at least 3,000 actual adjacent one-second returns before decisions. No claim
  of profit or successful three-day trial is made. Daily reports are produced in the app/receipts; recurring chat
  delivery is not configured because this environment has no persistent Railway secret binding.
  Leave Claude's existing 19:45 UTC Bitcoin-filter check unchanged. Real money still requires the owner's exact
  dollar amounts and positive practice after fees over 3+ days; there is no automatic promotion.

## 2026-10-12 17:04 UTC, Codex, crew movement cleanup
- Changed: at the owner's request, kept the existing town, cast, camera, layout and event choreography, and
  polished how the crew moves. Walks now ease into motion, slow for corners and brake before arrival;
  footsteps track the distance covered. Switching walk clips or returning from a gesture preserves the loop's
  phase. The motion module URL is versioned so returning browsers receive the update, and the page also
  remains compatible with older cached actors. No new earnings, events or activity are invented.
- Verified: `python -m pytest -q`: 2,974 passed, 21 skipped; mypy passed on 82 source files; Ruff passed on all
  three changed Python files. The final import-cache change passed a further 55 world/movement tests.
  Independent review exercised 144 round trips over the actual navigation graph at 10/30/60 fps: every
  destination and return reached, each arrival callback fired once. Tests also cover paused frames, stairs,
  braking, matching gait to travel and legacy actor compatibility.
- Browser check: local fixture data only, Chromium at 390x844 (normal and reduced motion) and 1280x800; inspected screenshots, all models
  loaded, no page/console errors, failed asset requests or horizontal overflow. The new motion-module URL
  loaded successfully. This environment renders WebGL in software: the first desktop screenshot attempt
  timed out; the repeat used the app's existing lite mode. No claim about physical-phone frame rate is made.
- Skipped: the same 12 opt-in network tests and 9 tests/modules needing optional pandas/numpy/scipy. Trading
  and real network tests were not enabled for a presentation change.
- Real money touched? No trading-code, order, cap or variable changes. Publishing the small tested cleanup
  to the deploy branch restarts the bot with its existing live settings under the owner's authorized workflow.
- Deploy verified: direct push `0f55628d5609db53a71f27b74558590d68f6df17` automatically created deployment
  `aeb5bc19-1095-46da-b931-bd682088279f`, which reached SUCCESS. At 17:10:07 UTC its logs show
  `polydesk_started theta=0.97 hours=1 ticket_usd=20 poll_s=90 (LIVE: 10 contract(s) per order)`;
  at 17:10:08 UTC the separate memecoin engine started in paper mode. Deployment-scoped ERROR/Traceback
  searches returned no matching errors. The public `/healthz` returned HTTP 200 with `ok` after a transient
  HTTP 502 during the container transition. This confirms the first watched-file push deployed automatically.
  The protected live dashboard was not opened; its presentation was checked with local fixtures above.
- Next step: owner refreshes `/world` to see the cleanup. This verification and the handoff correction are
  documentation-only and do not cause a second runtime deployment.

## 2026-10-12 16:47 UTC, Codex, branch claude/nightcrawler-memecoin-bot-Gwnb1S
- Changed: at the owner's request, authenticated an isolated read-only Railway CLI session using a credential
  held in process memory. No credential was written to a file, committed, or saved in persistent Codex settings.
  Recorded the previously pending independent verification of PR #5's deployment.
- Verified directly with Railway: project nightcrawler, environment production, bot online. Deployment 0866daea
  is SUCCESS with commit 1cd27824, matching PR #5's merge. Logs at 16:23:02 UTC show
  `polydesk_started theta=0.97 hours=1 ticket_usd=20 poll_s=90 (LIVE: 10 contract(s) per order)`;
  at 16:23:03 UTC the separate memecoin engine starts in paper mode. A deployment-scoped Traceback search
  returned no matching log entries. Railway received docs-only push 7c363e6 and marked it SKIPPED with
  `No changes to watched files`, leaving the live deployment unchanged.
- Checks: only this worklog changed. Application/test/build inputs still match tested 88780dd, so prior results
  apply: 2,969 passed, 21 skipped; mypy passed on 82 source files. No Python files changed for the lint gate.
- Not verified: a watched-file push triggering a successful build remains untested. Persistent RAILWAY_TOKEN
  environment setup is still absent; this read-only credential session does not configure future environments.
- Real money touched? no. Only status/log reads and documentation; no orders, deploys or variable changes.
- Next step: keep checking the exact deployed commit and intended startup mode after authorized watched-file
  changes. The next such change must also verify that the GitHub push starts the deployment automatically.

## 2026-10-12 16:38 UTC, Codex, branch claude/nightcrawler-memecoin-bot-Gwnb1S
- Changed: read the new rules at 209191b, synced the local deploy branch, aligned stale handoff wording with
  direct pushes for small tested changes, and clarified that PR #5's deployment was triggered by source setup.
  Installed Railway CLI 5.65.0 in this session from its official release via the environment proxy; npm's
  postinstall download tried a direct connection and failed. Persistent setup-script configuration is unchanged.
- Verified: GitHub confirms PR #5 merged as 1cd27824. The current environment permits internet access, the CLI
  runs, and the token-presence check reports no RAILWAY_TOKEN (no values printed). Application, test and build
  files still match the tested revision 88780dd: prior results remain 2,969 passed, 21 skipped; mypy passed
  for 82 source files. This change has no Python files to lint and touches only unwatched docs paths.
- Not verified: Railway status/logs cannot be read until the owner adds the project token to environment
  secrets. Claude's entries below record the successful restart and enabled autodeploy; Codex has not
  independently confirmed them. A watched-path push triggering a successful deployment remains unverified.
- Real money touched? no; documentation and local CLI setup only, no app code or Railway settings changed.
- Next step: owner adds RAILWAY_TOKEN through environment settings, then Codex checks the active deployment's
  commit and fresh startup logs. The next authorized watched-path change must also verify deploy on push.

## 2026-10-12 16:35 UTC, Claude, branch claude/nightcrawler-memecoin-bot-Gwnb1S
- Changed: the owner installed the Railway GitHub App. Autodeploy still said NO_INSTALLATION until the service source
  was reconnected with the repo's exact casing, `sideriapostolou-lgtm/Claude`. Autodeploy is now enabled (Railway
  assistant check). The reconnect built docs-only bfde287, which was SKIPPED. The live deployment 0866daea is unchanged.
- Not verified: a push-triggered build. The next merge that touches src/ or README.md is the test.
- Real money touched? no.

## 2026-10-12 16:25 UTC, Claude, branch claude/nightcrawler-memecoin-bot-Gwnb1S, after PR #5
- Changed: the owner merged PR #5 at 16:17:13 UTC (merge commit 1cd27824). No deployment followed. Railway's
  assistant found the cause: the service source had no branch, and auto-deploy reports `NO_INSTALLATION` (the
  Railway GitHub App is not installed for this repo, so GitHub never notifies Railway). It set
  `source.branch = claude/nightcrawler-memecoin-bot-Gwnb1S` (nothing else) and committed it. That built the branch
  head: deployment 0866daea, commit 1cd27824, SUCCESS at 16:23 UTC.
- Verified (Railway logs of 0866daea): `polydesk_live_connected cash=14.22`,
  `polydesk_started ... (LIVE: 10 contract(s) per order)`, `engine_start ... mode=paper` (the memecoin engine is
  paper, as intended), no tracebacks. The old deployment 4a8b5d52 was replaced.
- Not verified / blocked: deploy on push still does not work until the owner installs the Railway GitHub App for
  sideriapostolou-lgtm/claude (github.com/settings/installations, then Railway, Configure, Repository access) and
  enables autodeploy in Railway (service bot, Settings). Until then, merges do NOT deploy by themselves.
- Real money touched? no. Same app code, same settings; the bot restarted once.
- Next step: the owner installs the GitHub App; the next app-code merge confirms deploy on push.

## 2026-10-12 16:09 UTC, Codex, branch codex/live-on-merge-template, PR prepared
- Changed: prepared a LIVE ON MERGE PR template and linked AGENTS.md from README.md. README.md is watched by
  Railway, so merging this documentation-only change is expected to rebuild and restart the existing live bot.
- Verified: `python -m pytest -q`: 2,969 passed, 21 skipped; `mypy src/nightcrawler`: passed (82 source files).
  Merged deploy head 3c8b220 without conflicts and read the updated AGENTS.md and HANDOFF.md. Read-only review
  passed. `src/`, `tests/`, `pyproject.toml`, Dockerfile and railway.json are unchanged from both the tested
  commit 88780dd and current deploy head 3c8b220, so those test/type results still apply. Changed-Python lint
  has no files to check and satisfies the updated AGENTS.md rule 6; no exception is needed.
- Not verified / skipped: `ruff check src tests` with Ruff 0.17.0 fails on 468 pre-existing findings. An older
  Ruff 0.14.14 also fails (6 findings); no historical lint pin/config exists. The first `pytest -q` invocation
  failed collection because the repo root was not on the import path; `python -m pytest -q` resolved that.
  The final suite skips 12 opt-in network tests and 9 checks/modules needing optional pandas/numpy/scipy.
  No Railway deployment or startup logs were checked. The full-repo lint findings are outside this PR's
  changed-file gate; no lint rules or trading files were changed to bypass them.
- Real money touched? No trading-code, settings or cap changes. A merge is expected to restart the bot with
  its existing live settings. Codex has not changed Railway or merged into the deploy branch.
- Next step: open the PR into claude/nightcrawler-memecoin-bot-Gwnb1S. Owner
  merges, then opens Railway > nightcrawler > bot > Deployments and matches the successful active deployment
  to the resulting merge/squash commit SHA; check fresh `polydesk_started ... (LIVE: 10 contract(s) per order)`
  logs with no tracebacks and fresh dashboard updates, then record the evidence in this worklog through a
  follow-up PR. Railway access/logs are not available to Codex here, so the owner or Claude must supply that
  evidence. A healthz response alone is insufficient. Variable-change deployment remains separately unverified.
  GitHub's default branch differs from this deploy branch, so AI-created PRs must supply the template fields
  explicitly; automatic GitHub template prefilling is not established.

## 2026-10-12 15:50 UTC, Claude, branch claude/nightcrawler-memecoin-bot-Gwnb1S, PR #4
- Changed: wrote AGENTS.md, docs/HANDOFF.md and this log so another AI worker can continue safely. Earlier today:
  lab 8 scout files (research/lab8, commit 0877feb). Yesterday: the desk books the owner's in-app cash-outs from the
  activity feed (67aaf6f, deployed 2026-10-11 21:35 UTC and seen working: Packers and Commanders rebooked).
- Verified: the cash-out booking in the Railway logs (polydesk_sale_corrected x2); 48/48 crypto settlements on the
  public gateway. The helper agents that were drafting the scaling brief and the lab 8 plan stopped at a usage limit.
- Not verified / skipped: research/lab8/PLAN.md is not written yet; the scaling brief was not finished. No setting
  was changed.
- Real money touched? no (still ON at 10 contracts, $30 day, $30 open, $40 total, MARCO_REAL=1).
- Next step: HANDOFF.md section 9, items 1 and 2.

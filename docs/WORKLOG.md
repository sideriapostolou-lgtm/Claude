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

## 2026-10-12 18:08 UTC, Codex, branch codex/tycoon-town-view, PR #6
- Asked: reconcile the owner's reported $14.39 and earnings since midnight with the actual Polymarket connection.
  Asked whether that amount is cash or profit and which timezone defines midnight; no answer yet. Kept the
  existing UTC booking day and made it explicit. Earlier preview images were fixtures, not live account balances.
- Fixed: the town's account-bet card now uses the venue snapshot count and value, separately from tracked desk
  positions, which can remain after an owner cash-out. Known zero remains zero, unknown stays unknown. Old desk
  position details are explicitly records, not the current venue list. Cash always shows its own checked age;
  its details distinguish spendable cash, venue balance and buying power. Main dashboard and camera tour now
  label cash versus bot profit and expose independent source timestamps. No cash differences become profit.
- Live evidence (read-only logs/status): Railway deployment 1972f365-f1ef-4b12-9d2b-69ad519d8dd5 is SUCCESS,
  commit 03f526ea3426f25e388d110f5358aa556350109a. At 17:47:36 UTC it connected with cash/buying power $4.59
  and started LIVE with 10 contracts per order. Earlier deployment aeb5bc19 connected at 17:10:07 with $14.31.
  These are historical snapshots, neither verifies the owner's current $14.39. Venue activity logs confirm
  +$0.20 resolutions at 15:00 and 15:15, +$0.20 at 16:15, +$0.10 at 17:00 and +$0.30 at 18:00 UTC; also a $10
  deposit at 16:09 and an app sale at 15:56. This is not a complete daily ledger or proof of ownership of every
  logged account trade. No traceback/balance-failure match appeared in the queried deployment logs.
- Verified: full `python -m pytest -q`: 3,055 passed, 21 skipped; mypy passed all 87 source files; Ruff passed
  every changed Python file. Focused tests cover stale owner records versus current venue totals, missing/zero
  snapshots, invalid times, balance/buying-power separation and unchanged recorded bot profit. Browser fixture
  check passed at 320x568, 390x844 and 1280x800, including money details and the optional camera tour, with no
  page errors or horizontal overflow. Browser money was synthetic; real trading was not started locally.
- Open reconciliation limits: the protected production `/api/page` snapshot was unavailable, and logs expose
  only bounded account activity plus startup balances. Exact current cash and the complete since-midnight total
  are NOT reconciled. Booking uses detection day, not venue event day. Activity polling reads only the newest
  50 rows. Separate in-memory reproductions found two existing cash-out accounting defects: a fully sold
  break-even position remains tracked, and a late partial-sale correction can omit profit on the remaining
  shares' settlement (10 shares originally +$0.28; 4 sold at -$0.10; correction becomes -$0.10 instead of +$0.068).
  These findings are not established as the cause of the live discrepancy. They need a separate accounting fix
  and tests because those books also feed real-money loss limits; this PR does not alter them.
- Real money touched? No protected trading files, orders, strategy, caps, variables or stored account books
  changed. Only display/read-model code and tests/docs. Lint cleanup in the newly touched read-model file is
  formatting and annotations for existing exception boundaries. The same 21 network/optional dependency tests
  remain skipped. This update is on PR #6, not deployed; merge still restarts the existing live bot.
- Next: compare an authorized current dashboard/account snapshot with the owner's stated period, then address
  confirmed accounting discrepancies without changing owner bets or risk settings. After merge, verify the exact
  deployment SHA, LIVE startup and logs and record the result here.

## 2026-10-12 17:55 UTC, Codex, branch codex/tycoon-town-view, PR prepared
- Changed: the owner asked for a phone-first steady town, then named Theme Park Tycoon 2 as the visual reference.
  Kept the existing cast, buildings and navigation; added green grounds, department colors, paths on the actual
  walk graph, cutaway rooms and six selectable workstations. The camera stays put until the viewer moves it;
  the original camera tour remains available. Roof plants follow the cutaway and return with the original roofs.
- Connected: available Polymarket account cash, account-wide open bets and the bot's realized result today use
  existing `/api/page` fields. Owner bets, practice money, pending orders and bot results stay distinct. Cash
  and account-position ages are checked separately; missing data stays unknown. Actual service alerts remain
  visible. The role panel explains the separate Solana and Polymarket workflows without inventing handoffs.
  Fixed two display scope errors: Rook's whole-account open cost no longer becomes a gauge against the bot-only
  cap, and that same account total cannot create a false "full" pause in the new HUD. Trading decisions are unchanged.
- Verified: synced the deploy branch through 03f526e; `python -m pytest -q`: 3,033 passed, 21 skipped;
  `mypy src/nightcrawler`: passed, 87 source files; Ruff passed on all changed Python files; diff check and
  secret-pattern scan passed. No protected trading file differs from the deploy branch. Initial test runs
  exposed old default-mode/section-boundary assertions; those now test the new default and preserved cinema.
- Browser: inspected local fixture screenshots at 390x844, 320x568 and 1280x800, including settled Voss/Pip views.
  Final phone/desktop captures load the original models, with no page/console errors or horizontal overflow.
  Functional checks exercised all six selectors, a steady camera, the two workflow explanations, 18 account
  positions with preserved reading scroll, independent stale cash/positions, a loss, paper mode, missing values,
  disconnection/recovery and the optional camera tour. Geometry tests verify cutaway restoration, unchanged
  collisions/routes and no floating roof vegetation. Unit checks also cover service alerts and sign-in failures.
- Limits/skips: preview figures are sample data, not current venue balances. Software-rendered Chromium required
  the existing lite mode and paused frames for still captures; one earlier screenshot attempt timed out.
  Physical-phone frame rate and the protected production dashboard were not checked. The 21 skips are the same
  12 opt-in network tests and 9 checks/modules requiring optional pandas/numpy/scipy; real trading was not started locally.
- Real money touched? No order/strategy/cap/settings changes. This is a larger change, so AGENTS.md rule 4 uses
  a feature branch and pull request. Merging the watched `src/**` changes will rebuild/restart the existing live bot.
- Next step: owner reviews/merges the PR. Then match Railway's successful deployment to that exact merge SHA,
  check fresh `polydesk_started ... (LIVE: 10 contract(s) per order)` and no tracebacks, verify the live page,
  and add the deployment evidence here. This tycoon change has not been deployed yet.

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

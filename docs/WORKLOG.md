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

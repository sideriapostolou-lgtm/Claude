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

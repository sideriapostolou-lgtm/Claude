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

## 2026-10-12 16:04 UTC, Codex, branch codex/live-on-merge-template, PR pending
- Changed: prepared a LIVE ON MERGE PR template and linked AGENTS.md from README.md. README.md is watched by
  Railway, so merging this documentation-only change is expected to rebuild and restart the existing live bot.
- Verified: `python -m pytest -q`: 2,969 passed, 21 skipped; `mypy src/nightcrawler`: passed (82 source files).
  Read-only review passed. `src/`, `tests/` and `pyproject.toml` are unchanged from base commit 88780dd.
- Not verified / skipped: `ruff check src tests` with Ruff 0.17.0 fails on 468 pre-existing findings. An older
  Ruff 0.14.14 also fails (6 findings); no historical lint pin/config exists. The first `pytest -q` invocation
  failed collection because the repo root was not on the import path; `python -m pytest -q` resolved that.
  The final suite skips 12 opt-in network tests and 9 checks/modules needing optional pandas/numpy/scipy.
  No Railway deployment or startup logs were checked. Push/PR is pending an owner exception to AGENTS.md
  rule 6's green-before-push requirement; no lint rules or trading files were changed to bypass it.
- Real money touched? No trading-code, settings or cap changes. A merge is expected to restart the bot with
  its existing live settings. Nothing has been deployed or merged by Codex.
- Next step: after the lint-rule exception, open the PR into claude/nightcrawler-memecoin-bot-Gwnb1S. Owner
  merges, then opens Railway > nightcrawler > bot > Deployments and matches the successful active deployment
  to the resulting merge/squash commit SHA; check fresh `polydesk_started ... (LIVE ...)` logs and dashboard
  updates. A healthz response alone is insufficient. Variable-change deployment remains separately unverified.
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

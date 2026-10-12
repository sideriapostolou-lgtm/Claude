LIVE ON MERGE

<!-- Replace the prompts below. Keep LIVE ON MERGE first and use plain words. -->
[What changes, and what will the owner notice?]

**Touches real money:** [YES / NO — explain changes to trading code, settings or caps,
and whether deployment will restart a bot already trading real money.]

**Deploy on merge:** [Expected / skipped — name any changed watched paths:
src/**, pyproject.toml, Dockerfile, railway.json or README.md. Changes only to
docs, research or .github are skipped. Target claude/nightcrawler-memecoin-bot-Gwnb1S.]

**Checks:** [Commands run and their results, including skipped or failed checks.]

**Owner's check after a deploy:** Match Railway's successful active deployment to the
merged commit SHA, then check fresh startup logs and the desk's intended mode
(`polydesk_started ... (LIVE ...)` when live trading is intended). A successful
`/healthz` response alone does not verify trading health. See docs/HANDOFF.md section 4.

**Not verified / follow-up:** [Remaining checks and any exact owner steps needed.]

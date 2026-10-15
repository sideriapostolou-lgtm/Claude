# Continuity index: keep the original evidence

Created October 14, 2026, from repository head `fb578cf59f73dbd89d1cc75b17587943c7e4c88f`.
This is a navigation index, not a replacement for source files or a current account-status report.
The complete tracked tree and history stay in the same repository. No service, runtime state, dataset
or original research artifact is moved by the model-workflow setup.

**October15 update:** [Codex takeover checklist](CODEX_TAKEOVER.md) records verified connected access,
existing schedules, current separate service/source identities and the remaining private-state/data limits.
It supplements this index; it is not proof of an account, credential or volume migration.

**October15 release update:** [PR61 chronology correction and bounded resume](../research/kalshi_online_learning_2026-10-15/INPUT_CHRONOLOGY_RELEASE.md)
records exact live source, unchanged caps/retained losses, +$0.12 actual paired result, failed verification-timing
gate, continued execution delay and zero scored learner samples. It supersedes the earlier takeover snapshot's
read-only/latched-stop status only for the recorded owner-approved action; it grants no future resume or increase.

## Read at task start or model/session handoff

1. [AGENTS.md](../AGENTS.md): current hard rules and standing release scope.
2. [COORDINATION.md](COORDINATION.md): newest inbox, task ownership and deferred queue. Its October 14
   Claude handoff gives Codex all lanes including Kalshi; the older lane table is a file map, not a
   restriction restoring Claude's former exclusive ownership.
3. Newest [WORKLOG.md](WORKLOG.md) entries, then the entries linked to the task. Find the original owner
   decision and associated receipts before using any historic number or approval.
4. [Full Claude handoff](HANDOFF_CLAUDE_TO_CODEX_2026-10-14.md), then relevant sections of the
   [general handoff](HANDOFF.md). Their dated operating snapshots can be superseded by newer evidence.
5. [Model workflow](MODEL_WORKFLOW.md) and the task's [handoff record](WORKER_HANDOFF_TEMPLATE.md).

[CLAUDE.md](../CLAUDE.md) now points to the same entry points; its old generic scaffold is preserved
below that notice. Do not let its placeholder setup instructions override the actual application.

Check the local branch, HEAD, dirty files and current remote branch before editing. The deployment
branch is `claude/nightcrawler-memecoin-bot-Gwnb1S` in `sideriapostolou-lgtm/Claude`. Never force-push
or overwrite concurrent work. A source checkout/commit is not proof that the same commit is running.

## Where the detail lives

| Area | Canonical paths | What to preserve or verify |
| --- | --- | --- |
| Owner decisions and release rules | [AGENTS](../AGENTS.md), [coordination](COORDINATION.md), [worklog](WORKLOG.md), [accounts](ACCOUNTS.md) | Exact authorized action/amounts, dates and superseding decisions; credential names only. |
| Kalshi implementation | [controller](../src/nightcrawler/speeddesk_live.py), [real model](../src/nightcrawler/speeddesk_live_model.py), [client](../src/nightcrawler/speeddesk_kalshi_client.py), [ladder](../src/nightcrawler/speeddesk_live_ladder.py), [spec](SPEEDDESK_SPEC.md) | Real-fill inventory, fees, uncertain orders, reservations, stop/budget history and research/real separation. |
| Persistent state and startup | [ledger](../src/nightcrawler/ledger.py), [engine](../src/nightcrawler/engine.py), [settings](../src/nightcrawler/config.py), [Railway guide](RAILWAY.md) | Runtime state lives outside Git; re-read verified records before a restart/state change. Do not use a source clone to rebuild or reset live state. |
| Polymarket and owner activity | [Polymarket desk](../src/nightcrawler/polydesk.py), [US client](../src/nightcrawler/polymarket_us.py), [owner tests](../tests/test_polydesk_owner.py) | Separate real account/bot/owner attribution. The owner's app simplification did not turn this desk into practice. |
| Town and money display | [page](../src/nightcrawler/page.py), [page state](../src/nightcrawler/pagestate.py), [town summary](../src/nightcrawler/townsummary.py), [connections](TOWN_CONNECTIONS.md) | Cash is not P&L; Pacific-day display and source ages/coverage remain explicit. |
| Kalshi research and losses | [result](../research/kalshi_profitability_2026-10-14/RESULT.md), [loss audit](../research/kalshi_profitability_2026-10-14/LOSS_AUDIT.md), [comparison protocol](../research/kalshi_profitability_2026-10-14/COMPARISON_PROTOCOL.md), [Claude research archive](../research/handoff_2026-10-14/) | Negative results, original/inverse/no-trade protocol, held-out boundaries and incomplete evidence; no proven replacement edge. |
| Deployment and execution receipts | [PR47 deployment](../research/kalshi_profitability_2026-10-14/PR47_DEPLOYMENT.md), [latest trace release](../research/kalshi_profitability_2026-10-14/fill_detection_trace_release.json), [trace explanation](../research/kalshi_profitability_2026-10-14/FILL_DETECTION_TRACE.md) | Exact commit/deployment IDs, before/after snapshots, timestamps and bounded observation intervals. Latest WORKLOG can supersede these. |
| Recorder continuity | [saved manifest receipt](../research/kalshi_profitability_2026-10-14/RECORDER_SAVED_MANIFEST_RECEIPT.json), [Claude recorder review](../research/handoff_2026-10-14/recorder_preflight_and_fixes.md), full handoff section 2.2 | Separate service/volume; saved metadata is not verification of raw hashes, all venues or continuous coverage. |
| Original TJR source | [main Page snapshot](../research/tjr_mnq_2026-10-14/MAIN_HANDOFF.md), [prototype snapshot](../research/tjr_mnq_2026-10-14/MNQ_PROTOTYPE.md), [source manifest](../research/tjr_mnq_2026-10-14/SOURCE_MANIFEST.json), [review](../research/tjr_mnq_2026-10-14/REVIEW.md) | Full archived Page content/code and original tests; retain hashes and compare actual current Page versions before using changed content. |
| TJR derivative and validation | [validation](../research/tjr_validation_2026-10-14/VALIDATION.md), [derivation](../research/tjr_validation_2026-10-14/SOURCE_DERIVATION.json), [test receipts](../research/tjr_validation_2026-10-14/REGRESSION_RESULTS.json), [data access](../research/tjr_validation_2026-10-14/DATA_ACCESS.md), [profit protocol](../research/tjr_validation_2026-10-14/PROFIT_EVIDENCE_PROTOCOL.md) | Original vs calendar-fix derivative, authentic-contract requirements, fees/friction, unopened holdout and all synthetic-vs-historical limitations. |

The older handoff names `docs/KALSHI_RECORDER.md`, but that file and the recorder source are absent from
the checked main-deploy tree. Do not pretend they were read here or reconstruct them from this index.
For recorder implementation work, locate and inspect the actual recorder branch/deployment source;
existing receipt paths above preserve the currently available evidence.

## Open work carried forward, not cleared by this setup

- **Kalshi local-delay attribution:** the verified trace release recorded a 109.694 ms order-list
  callback followed by 2,476.114 ms before controller resumption in one early cycle. This isolates a
  local delay, not its exact blocker or the reason for every loss. Next: bounded callback wall/CPU
  timing joined to the existing trace, then fix the measured blocker without changing accounting.
- **Execution/research evidence:** sustained complete-window evidence and raw recorder hash/per-venue
  continuity remain open. The original/inverted/no-trade experiment is a frozen design, not a completed
  profitable backtest. Preserve gaps and unobserved outcomes; do not open sealed TEST to fill the gap.
- **Recorder operations:** the full handoff assigns the 48-hour feasibility report around October 15,
  2026, **3:45 PM Pacific**, plus a storage-capacity review before October 20. Verify fresh storage/rate
  evidence before proposing changes; old growth estimates are not current usage. These obligations
  remain pending unless newer WORKLOG evidence completes them. No new timer is claimed here.
- **TJR-MNQ-001:** explicitly reprioritized for offline validation, still blocked on authentic MNQ
  December 2025 development bars and account-cost evidence. Original 65 synthetic checks and additional
  runner checks are reproduced; historical P&L is unknown, paper has not started and live is disabled.
  Keep the saved prototype; do not rebuild it from a summary or repeat unchanged access failures.

This list is a starting index, not an exhaustive new task queue. Review the full current coordination
queue and relevant WORKLOG/handoff sections for other obligations; do not discard items absent here.

## What this preserves, and what it cannot promise

Git preserves committed bytes and history. The original documents, source snapshots, test receipts and
research outputs remain authoritative; this index only points to them. In a handoff, include exact
source/patch IDs and evidence paths rather than relying on a compressed model memory.

Git does not contain every chat message, provider entitlement, unsaved local edit or Railway volume.
Session compaction and model changes are not lossless backups. Preserve uncommitted work in its own
task branch, document decisions that matter, and state any missing context explicitly. Do not copy
credential values, private keys, auth files or secret-bearing logs into a handoff bundle.

Runtime balances, fills, fees and losses need read-only authorized venue/ledger evidence with timestamps;
the current running commit needs deployment evidence. None of those was freshly inspected as part of
this development-workflow change, and no account state was migrated or restored.

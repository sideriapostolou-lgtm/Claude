# Shard cash implementation handoff

2026-10-16 UTC; worker `/root/shard_fix_implement`; launch explicitly requested `gpt-6.1-sol`, high effort, `fork_turns=none` per MODEL_WORKFLOW (root-reported launch receipt). Base `9110d5d`; worktree `/workspace/nightcrawler-shard-cash`, branch `codex/shard-cash-backoff`. No commit, push, deployment, production test, financial action, credential/config/mode/limit/stop/resume change. Root owns documentation/release and final full suite.

Implemented:
- Preserve validated market `exchange_index` in memory; unknown stays unknown. Exact fresh public ticker metadata can hydrate old restored windows; changed known routing blocks the window. Omit routing from nested persisted Window objects at live/practice/journal paths so the old source can still read state on rollback. Restart reacquires routing and cash instead of trusting saved funding.
- New `speeddesk_live_cash.py` validates exact `GET /portfolio/subaccounts/balances` rows: subaccount0 only, distinct (subaccount,index), integer nonnegative shard, finite nonnegative USD decimal string up to six decimals. Other subaccounts/aggregate cash never fund primary shard orders. Missing, malformed, duplicate or unavailable target balance fails closed. Official field/unit evidence from `/workspace/shard-api-review.md` and API-review agent; aggregate breakdown subaccount semantics are undocumented, so exact endpoint chosen.
- Ordinary/lock admission and final transport guards subtract all same-shard active bot reservations (including cancel-pending/uncertain) and post-snapshot fill principal+fees. New risk-book per-window debit map clears only with fresh cash; no history rewriting. Reservation checks use existing open-window index, no all-history scan per tick. Unknown commitment route blocks funding.
- Foreign resting orders anywhere on primary subaccount conservatively block creates (unsupported fee/margin/netting cannot establish spendable). Cache absorbs BOTH list-order reads, preserves older commitments over recent scans, clears identified rows only on terminal/owned evidence or full scan. Malformed/unknown status cannot silently free commitments.
- Aggregate `cash_usd` remains unchanged/display/risk ceiling; panel adds `cash_total_usd`, `shard_funding` exact primary balances/source/receipt-time/error/external-rest counts/refusal, and `create_funding_cooldown`.
- Definite create `insufficient_balance` starts dedicated 60/120/240/300s cooldown shared by ordinary/lock sends and guards; successful reconciliations/general error counters cannot erase it. Definite rejection+cooldown saved atomically and durably before a released refusal becomes recoverable. Accepted creates reset escalation. Reconciliation/cancels remain available. Ambiguous creates keep their reservation and do not enter the definite-refusal path.

Changed existing files:
`src/nightcrawler/speeddesk_kalshi.py`, `speeddesk_live.py`, `speeddesk_live_model.py`, `speeddesk_model.py`;
`tests/test_speeddesk_live.py`, `test_speeddesk_live_desk_property.py`, `test_speeddesk_live_killpoints.py`, `test_speeddesk_live_reads.py`, `test_speeddesk_live_safety.py`.
After root full-suite regression review, also `tests/test_speeddesk_lock_send_freshness.py` (manual restart supplies fresh public market callback) and `tests/test_speeddesk_readtrace.py` (exact read sequence includes required subaccount balances). Root/reviewer notified before these test-only changes; frozen source unchanged.
New files: `src/nightcrawler/speeddesk_live_cash.py`, `tests/test_speeddesk_live_cash.py`.
Existing test changes only explicit fake shard metadata, exact fake balance endpoint, fake restart public-market callback, and new enforcement fixture setup. Root-authored docs/research files are separate from these worker changes.

Checks:
- New cash safety suite: 51 passed (0.46s).
- Focused controller/client/market regressions: 436 passed (14.95s), including new suite, live, safety, reads, balancing, pull, reprice, crash, runtime, timing, stop-controller review, Kalshi and Kalshi client.
- Earlier additional original focused run including desk property+killpoints: 122 passed (31.36s); before final serialization-only adjustment.
- `mypy src/nightcrawler`: success, 133 source files.
- Ruff all 11 changed Python files: passed.
- `git diff --check`: passed.
- Full-suite follow-up fixture/expectation regressions: both complete affected test files 44 passed (1.22s); Ruff both files clean. Root owns final full-suite rerun and renewed complete-patch hash.
- Interpreter: `/workspace/shared/nightcrawler-venv/bin/python`.

Source/tests frozen and root informed. Root will run full suite and independent review against complete tracked+untracked patch hash. Actual authenticated exact-subaccount endpoint behavior remains unverified while production is PAPER; no paper-mode client read added to obtain that evidence. No cash transfer/allocation implementation. Conservative foreign-resting refusal may prevent otherwise affordable bot orders until exposure is understood. Overall trading profitability/EXEC work remains outside this patch.

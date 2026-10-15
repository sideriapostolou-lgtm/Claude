# Bounded verification plan for REST/WebSocket recovery correction

Written before release and before selecting a future outcome. This is execution
correctness and startup verification, not a strategy backtest or profitability test.

1. Require the complete test suite, mypy, changed-file Ruff, exact independent review,
   credential/scope checks and matching source hashes. Preserve the rejected first
   candidate's clock-boundary failure and the corrected patch separately.
2. Integrate latest deploy-branch contents without rewriting history. Merge only in
   existing safe minutes. Verify Railway SUCCESS on that exact source commit and
   normal Polymarket startup. Do not change variables, caps, stop/resume budgets,
   fees, live strategy, observer history, trading mode or manual orders.
3. Capture original real status before release and after startup, excluding stale
   readiness reports. Compare selected financial/history/cap/ladder paths and old
   one-use control handling. Join intervening real fills/settlements to explain
   changes. Unexplained changes or missing originals stay unknown, not certified.
   `as_of` is a panel time; exact last-account-read age is not published.
4. After exact source, startup and ready-state checks, select the earliest full
   15-minute Kalshi window beginning at least 60 seconds after verification. Publish
   its exact source/deployment/window/start/end/tail before start. If verification
   misses that gate, choose the next eligible window before its start; never select
   or extend a cohort because of its outcome. Tail is fixed at end +120 seconds.
5. During that window and fixed tail, use only finite read-only queries. Collect
   original feed book/tape failure events (`invalidated=true/false`), real fills,
   settlements, status and both observer statuses. Use exact deployment/bounds and
   limits; split a saturated query before interpreting it. Preserve retrieval
   errors, nested-copy exclusions, duplicate identities and missing data.
6. Reconcile only the selected window's recorded fills, fees, matched versus
   directional quantities and settled P&L. Preserve prior/next partials separately.
   Unsettled results remain pending at cutoff; do not manufacture a zero or extend
   the window to obtain a favorable result. Practice never substitutes for real.
7. Observe rather than force the fixed branch. If no late recovered REST failure
   occurs, state that production exercise was not observed; fake reproductions and
   deployed-source identity do not establish saved dollars or improved profit.
   Likewise, a gained/lost window does not establish causation from this correction.
8. Verify bot/recorder health and bounded traceback/warning queries. Platform state
   and retained-storage usage do not certify raw coverage or current disk capacity.
   Keep the existing recorder checkpoint at 3:45 PM Pacific and storage review.

Complete the bounded release only with exact deployment/startup/runtime evidence.
Keep broader execution gaps, profitability, observer sampling, original/inverse
research and any missing verification on the existing queue. Kalshi remains first;
other business/transfer work stays deferred and TJR/MNQ last. No financial promotion
or live use of an experimental learner follows from this plan.

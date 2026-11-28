# Read-only diagnosis: reuse active-window membership within one settlement pass

Recommendation: approve a minimal performance patch in `speeddesk_live.py::_reconcile_reads`, plus focused regressions. Compute `{item.window for item in self._active()}` once immediately AFTER `_release_unsent` and use membership in the following settlement loop. `PROPOSAL_ONLY.patch` is a two-line source change and has NOT been applied. Do not narrow full-account queries, skip old terminal order validation/corrections, change reconciliation cadence, cache across awaits, or alter money/strategy settings.

Base: `d1ee16f728612275fedb0d08846e127b0ad9b88d` (source PR70 `5b2fb163`); worktree `/workspace/nightcrawler-profit-next` remains clean. `DIAGNOSTIC_RECEIPT.json` hashes the proposal, runnable private experiment, final measurements and accepted-baseline test stdout. All deliberate writes are private. Python imports in initial runs may create ignored bytecode caches; no source/tests/config/public documents were edited. No commit, network account request, key read, order, variable, stop, budget, reset, deployment or sealed research partition action occurred.

## Concrete mechanism

At current source line1937, complete reads may release an unsent intent. At line1940 the code then visits every historical traded window. For EACH window with a saved final outcome, it calls `_active()` to see whether any unfinished order belongs there. `_active()` at line638 ordinarily builds and sorts the open-intent list; with an integrity error it deliberately falls back to scanning ALL controller intents. Calling it once per historical window repeats a query whose answer cannot change during this synchronous settlement pass.

The safe boundary is important: capture active windows after `_release_unsent` because that operation can mark an intent terminal and allow settlement in the same reconciliation. No await occurs between the proposed capture and the end of the window loop. `book.settle()` either returns for an already settled window, refuses an unreconciled reservation, or settles a window already proven to have no active intent; it does not add/remove active Intent records. Stop/ladder updates and receipt append operations do not mutate active-order membership. If settlement raises, the pass aborts as before. The existing `_active()` integrity-error/length-mismatch fallback is preserved because the snapshot is built using the unchanged helper.

This removes repeated local work, including a sizeable emergency integrity-error path. It does not remove the two order lists, any page/row/fill/fee validation, position/balance/settlement read, authoritative histories or reservation checks. The multi-second production full-scan network cost remains unresolved.

## Reproduction and measurements

`profile_active_windows.py` loads the actual accepted source method and makes only the proposed textual substitution into a privately compiled method. It binds that candidate to an explicitly fake desk in memory; no repository file is patched. Fixtures reuse existing `tests/test_speeddesk_live.py::make_desk` and `tests/test_speeddesk_live_history.py::add_history`. An explicit extension populates the separately persisted `final_outcomes` field for settled history; the original fixture omits that field. Every historical window has ten finished orders, with one current open maker. The integrity case uses the existing history test's reopened-old-Intent plus `fill_after_terminal_confirmation` fallback fixture. It is synthetic, not a production incidence claim.

Each variant warms a complete real-controller reconciliation, then measures seven forced full reconciliations. Fake account responses and clocks are fixed; real client constructors, requests and socket connection paths are denied. CPU measurements refer to the event-loop thread, not all worker threads. Baseline and candidate are measured in sequential blocks, so wall-time differences include order/noise effects; deterministic call reductions are stronger evidence than tiny timing percentages.

| Synthetic history | Baseline median wall | Private candidate median wall | `_active()` calls/reconcile, before→after |
|---|---:|---:|---:|
| Fresh |1.345ms|1.436ms|8→9|
|2days /1,920old orders|21.040ms|18.442ms|200→9|
|7days /6,720old orders|66.879ms|59.710ms|680→9|
|21days /20,160old orders|207.734ms|192.167ms|2,024→9|
|7days plus integrity fallback|172.147ms|62.981ms|680→9|

The last row is approximately109.2ms less local wall time and109.1ms less event-loop thread CPU in this fixture. It avoids671 redundant full-history scans, roughly4.51million Intent terminal checks. The21day normal case removes2,015 active-list rebuilds/sorts but saves only about15.6ms here. Fresh adds one active-list lookup and is0.091ms slower in this sample. Earlier pre-equivalence runs showed2day/7day regressions of a few percent; those noisy/adverse results remain in `PROFILE_INITIAL_UNCERTIFIED.json` and `PROFILE_UNNORMALIZED_2.json`. No claim of universal, production, tail-latency, fill-rate or profit improvement follows.

Every final variant comparison matches the exact selected financial/order/practice/archive/decision receipt SHA256. The selected comparison includes the entire risk-book state, all controller intents, practice-twin state, final/foreign/changed outcomes, fatal/cash/account fields, pending rows, creates/cancels, archive parts/chunks and all receipts OTHER THAN `speeddesk_live_status` and `speeddesk_fill_markout_status`. Those two diagnostic types contain random markout session IDs and real perf-counter measurements; early full snapshot comparisons correctly failed on those paths. Initial full snapshots are retained so those exclusions are reviewable. This is NOT a claim of full ledger receipt byte equivalence; financial fields are compared separately in full.

All measured fake API call sequences/counts are unchanged: two list_orders, one fills, one positions, zero settlements for already-settled histories, one balance each complete reconciliation. No fake order/create/cancel or practice-state divergence was found. Actual settlement transitions and race boundaries still require dedicated accepted regression tests if root authorizes source work.

Current accepted-source baseline tests:12passed1.62s across `test_speeddesk_live_history.py`, `test_speeddesk_live_full_scan.py`, `test_speeddesk_live_reads.py`; exact stdout in `BASELINE_TESTS.log`. This is not a new full suite or candidate full safety certification. The fresh cloud runtime skill status was checked without printing/reading credential values; no remote data was needed.

## Failures and limits preserved

Initial diagnostic failed on an incorrect `LiveSettlement.up_won` field name; corrected to actual `up_wins`, with original traceback in `PROFILE_FAILED_1.log`. A zero-history row from that failed attempt had unequal raw receipt hashes. After deterministic UUID fixture setup, comparisons still differed on real diagnostic timing/markout session fields; full snapshots identify those exact differences. Final selected financial comparison removes only the two explicitly listed diagnostic receipt types, with unchanged full book/order/practice/archive state. No financial difference was silently normalized away. The final result is `PROFILE.json`; all five selected equality flags are true.

This experiment exercises quiet histories and the integrity fallback; it does not establish production distribution, new real settlements, API/page latency, long-run CPU allocation/memory costs, or saved financial decisions under every possible callback. Its scope is suitable for a narrow performance change after review and meaningful regression coverage, not strategy or size promotion.

## Proposed authorized implementation scope and next step

Only `src/nightcrawler/speeddesk_live.py` receives the membership snapshot change. Extend existing history tests (or a narrowly named new test file) to pin bounded helper calls with large finalized history and integrity fallback; also prove baseline/candidate matching for multiple inactive settlements, current active-window deferral, pending/uncertain orders, full-read same-pass unsent release, terminal-correction/full-read detection, and a genuine settlement-error abort. Keep original full-scan/correction/killpoint assertions. No durable schema, cache lifetime, configuration, observer, strategy, practice fill model, decision, size/cap/stop/budget/control, API request or timing-policy change.

Root should authorize/reserve that scope before source edits, then independent Astra review must test the actual frozen patch, followed by required focused/full/mypy/Ruff checks and root-only release/runtime verification. Any code release changes the source that the future PR70 fixed queue cohort declared; root must explicitly invalidate/redeclare that primary comparison instead of silently retaining its old source promise. Exact higher sizing amounts remain unspecified and unauthorized; this performance proposal supplies no basis for raising them. Overall EXEC, current first-entry edge, practice fidelity, account-network latency, count-only exports, recorder and operating-transfer tasks remain OPEN; no profitable effect is claimed.

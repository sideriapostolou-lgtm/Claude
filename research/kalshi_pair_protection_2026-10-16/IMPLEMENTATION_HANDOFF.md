# A-only implementation handoff

Requested role/model: Sol/high. Root is sole publisher/operator. Base ee0e4b520de29a8da0031d94eb90c0b0d5a4dc94; root public scope cdb032818b1ac91df82b908371d9c535b9b93a13. Source edits remain uncommitted for root integration/review. No network, production, secrets, TEST, reclaim confirmation, tuning, financial controls, config variables or Polymarket changes.

## Frozen artifact

FROZEN_PATCH.diff SHA256 23a459ed7a9ef5b32b62309f9a263de26bd7b9a6894de96fcc3f42aef76cbe6a includes tracked diff plus complete new tests/test_speeddesk_pair_protection.py. PATCH_RECEIPT.json has all six final per-file hashes. Hash covers two source files and four test files. No further edits planned unless review/full-suite findings require renewal.

## Behavior

LiveRiskBook.protected_windows is an optional top-level persisted sorted list, internally a set. _protect_pair checks each confirmed record_fill independently, before the next same-batch fill: both sides positive, equal within existing EPSILON, finite payout-minus-actual-cost-and-fees margin strictly above EPSILON. Once latched, the set never removes that window, including after race fills leave unequal or losing holdings. WINDOW_PARTS/archive schemas remain unchanged. Restore validates any present field (including rejecting null/wrong type/unknown/duplicate), validates complete accounting, then derives only current confirmed equal positive pairs for older/current snapshots. It does not infer an old intermediate balance from arbitrary fill observation ordering.

Ordinary admission refuses pair_protected when any proposed contract would increase directional risk. Existing same-side active reservation check still applies before this; balancing size uses confirmed inventory and existing unit-cost semantics. Existing window/open/cash budgets, stops, cutoff, venue terms and clip stay enforced.

_cancel_unsafe uses normal cancellation for a protected non-lock order with an active residual reservation that is no longer strictly_balancing_intent. Remaining-zero/full-filled book intents are not gratuitously canceled while controller terminal metadata catches up. Existing helper includes all same-side reservations, uncertain creates, cancel requests and locks; no requested/404/timed-out cancel releases liability. Unknown order IDs are marked cancel_needs_order_id. Existing acknowledgment/error/retry/fill/order reconciliation remains unchanged.

_send_guard rechecks protected/non-balancing after transport wait. Its existing definite-unsent refusal path releases only the confirmed unsent create; uncertain sends retain their reservations. lock intents immediately use the unchanged _lock_guard path.

Panel adds pair_protection with current open protected windows and total historical count. The first new latch in live reconciliation records speeddesk_live_pair_protected containing inventory payout/cost/floor and explicit prior-reservations caveat, once per window. inventory_floor_usd is confirmed holdings only; pending liabilities can erode it. Existing financial fill-batch checkpoint cadence persists the flag. No hot network path or extra account scan was added.

## Limits

This is a newly authorized restriction, not evidence of profitable expectancy. It prevents new directional bets after a confirmed positive full pair; it does not fix an initial losing first leg, ensure resting cancels win races, remove late hedges, or replace forward policy/queue evidence. Existing late hedges can reduce loss and remain unchanged.

Persisted flags survive restart/archive. The existing cadence saves at completed fill-batch checkpoints. If the process dies after an intermediate latch but before the existing checkpoint, and venue replay arrives in a different order ending unequal, that not-yet-persisted intermediate observation may not be reconstructed. No stronger crash-durability guarantee is claimed. Recovered current equal positive holdings are still protected. Root/Astra explicitly reviewed this boundary.

The initial private BASELINE_RESULT.json is a DIFFERENT synthetic scalar example (.50/.488 + .43) with the same terminal -1.23/+1.77 numbers; it is not an exact actual replay. The final dedicated test uses the selected actual arithmetic: Down5@.49+Up5@.45 -> cost4.70/floor+.30, then hypothetical Down3@.51 -> -1.23 or+1.77. Blocking forgoes incremental favorable1.47 as well as avoiding adverse1.53. Fill/queue counterfactuals remain unproved.

## Verification

Final command used PYTHONPATH=/workspace/nightcrawler-paired-entry/src:/workspace/nightcrawler-paired-entry/tests and /workspace/shared/nightcrawler-venv/bin/python -m pytest -q on:
- tests/test_speeddesk_pair_protection.py
- tests/test_speeddesk_live_balancing.py
- tests/test_speeddesk_live_pull.py
- tests/test_speeddesk_live_crash.py
- tests/test_speeddesk_live_stop_model_review.py
- tests/test_speeddesk_live_stop_controller_review.py
- tests/test_speeddesk_live_model.py

Result: 277 passed in10.57s. Ruff passed all six changed Python files; git diff --check passed. Root retains full-suite/mypy/credential-scan/release responsibility. Astra has exact hash and frozen file paths for independent review.

Intentional old test adaptations:
- Stop-accounting regression explicitly seeds already-existing legacy post-pair liabilities instead of requesting newly forbidden admission; all worst-loss/hedge assertions remain.
- Pull two_bids uses an explicitly labeled legacy6-contract first intent partially filled5.01 and canceled, then Down5, leaving5.01/5 unequal throughout. Current new-orderclip5 unchanged; identity/index/terminal counts and fees coherent. Twin synthetic inventory mirrors5.01/5; actual practice fill-count metrics retain10contracts versus real10.01 and are explicitly asserted separately. Original timing/cancel/practice-control and3+3 sizing assertions remain.
- Crash journal tests add deterministic unfilled, definitively canceled/reconciled starter requotes before random cases. Original >=3send and >=2journal-depth coverage bars remain unchanged; no killpoint removed.

Failed attempts retained:
1. Initial model reproduction lacked PYTHONPATH and failed import; corrected to PYTHONPATH=src.
2. Default Python lacked pytest; no dependency installation attempted. Found shared venv, then pinned PYTHONPATH to avoid its editable other checkout.
3. First existing220 focused cases:189passed/31failed, all forbidden post-pair fixture assumptions (30pull,1stop-accounting).
4. New139-case run:131passed/8failed; fixed mid-reconcile pointless full-fill cancellation via residual-active guard, corrected cancellation-history/clock expectations, distinguished ordinary cutoff from permitted late lock, and updated real5.01 metric assertion.
5. Next139:138passed/1failed; same remaining cancel-history/account clock assertion refined.
6. Next160:159passed/1failed; guard expected healthy account immediately after create, but existing controller deliberately invalidates its account clock. Added complete fake reconciliation before asserting healthy send guard.
7. Ruff initially found two import-format issues; auto-fixed only imports in new test and touched balancing test.
8. A transient local test edit accidentally placed cutoff branch into transport test; corrected before final277green/freeze.

Outstanding: root full suite/mypy/scan; Astra exact patch review/private regressions; source release/exact production retention/runtime verification; prospective multi-window policy evaluation with forgone wins/cancel races. No release or profit completion claimed.

## Final test-only amendment after root full-suite pass one

Root first full suite completed:1failed/6092passed/14skipped in302.35s. The sole failure was tests/test_speeddesk_speed2_risk_integration.py::test_conservative_pending_cost_is_preserved_when_both_sides_have_bids, independently reproduced with pair_protected before changing any repository file. After root confirmed the full suite had finished, changed only its obsolete post-positive-pair new-admission setup to explicit pre-existing legacy3+3 LiveIntent reservations. All original financial/worst-loss/restoration assertions remain unchanged. Both source hashes unchanged. Final focused suite including this sixth-case file:283passed in10.45s; Ruff7 anddiffcheckpassed. New seven-code-file patch SHA256 edaad1806ae064aa081019531bfc0d1084c8026510d86ce81b3f064d721ffc8e. V1_FROZEN_PATCH.diff andV1_PATCH_RECEIPT.json preserve the first reviewed artifact. Root docs/research changes excluded from this code patch. Final full suite/review/release still root-owned.

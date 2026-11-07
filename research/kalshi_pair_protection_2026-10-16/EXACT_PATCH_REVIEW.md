# Exact patch review: accepted within stated guarantee

Reviewed base ee0e4b520de29a8da0031d94eb90c0b0d5a4dc94 plus complete six-file patch SHA256 **23a459ed7a9ef5b32b62309f9a263de26bd7b9a6894de96fcc3f42aef76cbe6a** (sol/FROZEN_PATCH.diff). Independently checked base, patch hash and every six-file SHA256 against sol/PATCH_RECEIPT.json before final tests. Relevant later changes require renewed review.

Requested GPT-6 Astra/high launch succeeded according to root's tool receipt; actual runtime model identifier is not independently exposed in the worker context. This records the requested configuration and successful delegation without inventing runtime attestation.

**No blocking defect found in the frozen patch.** It implements A alone: fee-inclusive positive equal-inventory event, sticky window marker, ordinary new-risk refusal, aggregate-reservation-aware cancel/send guards, honest inventory-only receipt and open-window status. Caps/stops/cash/order accounting and late locks remain intact. The cancellation predicate appropriately excludes book intents with no active remaining liability even while controller terminal status lags. The marker is top-level; old strict archive chunk structure is unchanged.

Independent final command (PYTHONPATH explicitly selects this checkout):

```
PYTHONPATH=src:tests /workspace/shared/nightcrawler-venv/bin/python -m pytest -q \
  /workspace/private-handoffs/claude-2026-10-15/paired-entry-2026-10-16/astra/test_independent_pair_protection.py \
  tests/test_speeddesk_pair_protection.py \
  tests/test_speeddesk_live_stop_controller_review.py \
  tests/test_speeddesk_lock_send_freshness.py \
  tests/test_speeddesk_live_stops.py tests/test_speeddesk_live_crash.py \
  tests/test_speeddesk_live_killpoints.py
```

**149 passed in26.62seconds**: private20 independent cases, new36 implementation cases and93 existing safety cases. This is overlapping focused verification, not additive to root's full suite. Root retains full pytest/mypy/changed-file Ruff/credential scan and exact release/runtime responsibility; no production access by reviewer.

Coverage includes fractional actual fills, fee-inclusive zero/negative margin, original first/partial exposure, residual starter fill race, competing same-side liabilities, cancel request/ack404/timeout/unknown ID, pre-send completion during wait, protected repair under existing guards, late lock, strict invalid state, current-only legacy derivation, financial-field preservation, actual checkpoint/archive/reopen and real subprocess killpoints. The private archive case checks protected-but-now-imbalanced state across the real writer/reopener and exact original WINDOW_PARTS. Malformed unknown/duplicate/non-list/non-string/unhashable marker entries fail closed; existing missing-archive enforcement remains unchanged. Private tests never edit application or repository tests.

Earlier independent93-case run had91pass/2fail: seed0's old random journal fixtures no longer made3orders or depth2 after a full pair. Sol preserved the original assertions by adding deterministic canceled/unfilled requotes in the same checkpoint interval, exercising a permitted sequence. The old pull fixture now explicitly represents legacy5.01/5unequal inventory and old6-contract partial starter, with current sends still5max, rather than clearing the sticky latch. The old balancing test seeds legacy reservations directly. These are purposeful fixture updates; no failed money assertion was removed. Interim new-test failures from historical cancellation assertions/cutoff permitting a valid lock were corrected; an incomplete concurrent edit briefly produced NameError, not part of frozen patch.

Guarantee must stay bounded. Successfully checkpointed markers survive restart, including later unequal inventory. Existing liabilities can still fill after the first pair and cause loss. A legacy already-imbalanced window gets no invented historical marker. A crash after a transient per-fill marker but before the unchanged batch checkpoint, then reordered replay of the venue fill batch, can lose that unsaved observation; a private test explicitly reproduces this limitation with identical final holdings. The implementation does not promise all historical/unsaved transient pair detection. After an observed/saved marker, newly admitted ordinary quantities only reduce confirmed imbalance under every existing guard. This is a conservative exposure-policy change, not a profitable strategy result.

The adjacent ordinary cash-check asymmetry was investigated and not established as a reachable current defect; it remains excluded. The initial one-sided loss and missed later directional winners remain possible; late hedge stays enabled. Do not claim break-even, preserve-positive-P&L despite residuals, or account-wide loss prevention.

## Separate descriptive cohort arithmetic

Private audit_cohort_independent.py independently reads the10allowlisted native leaf files, validates their hashes and unsaturated counts and recomputes actual settlement/payout/fee/fill totals.50explicit native hash/count/arithmetic assertions plus summary assertions passed. COHORT_INDEPENDENT.json records results:

-15settlements,8positive/7negative; actual total−$4.0182 within floating-report precision; fees$0.2632.
-14windows' returned fill totals match settlement; first restart window remains incomplete.
-11positive equal publication-order prefixes;4subsequently endnegative,4finish above the prefix inventory floor,1finish positive but below,2have no later returned fills.

The first audit draft required exact ordinary durable-intent label and omitted lock labels from the additional later-intent log join. It was corrected to accept durable-intent prefixes; the actual settlement/prefix arithmetic was unaffected. All34later fill rows have a later intent PLATFORM log timestamp. This is deliberately not a verification of root's different cross-clock decision-time comparison; one decision can precede a prefix platform timestamp despite later publication. It neither proves authoritative controller order nor executable alternative P&L. No simulated fills, cancellation assumptions or sealed data were used. Saturated/transport-failed parent attempts are preserved separately by root and were not used to manufacture complete coverage.

Cohort clock supplement: the independent native script now preserves BOTH clocks and confirms exactly1unique later-filled order whose local intent.at does not follow the prefix platform timestamp. In KXBTC15M-26OCT152200-00, client nc-speed-aad2daeec4544969be27ccddedcd14b0 has local intent.at1792115321.6146324 (01:48:41.6146324UTC), before positive-prefix platform publication01:48:42.434076131UTC, while its intent platform publication01:48:42.435942087UTC is later. Thus all34later-fill rows join a later intent PLATFORM log, yet not all those local intent decisions were newer than the prefix publication. These cross-clock comparisons are descriptive; unknown pending/cancel lifecycle and batch physical inventory remain unknown. No claim this was a freshly authorized post-protection decision or that an alternative cancellation would have prevented its fill.

## Renewed seven-file exact review

**Accepted complete code patch SHA256 edaad1806ae064aa081019531bfc0d1084c8026510d86ce81b3f064d721ffc8e**, superseding the six-file approval identifier above. Independently verified FROZEN_PATCH.diff digest and all seven on-disk hashes against renewed sol/PATCH_RECEIPT.json. The original six source/test file hashes exactly match V1_PATCH_RECEIPT.json; both application files are unchanged.

The sole new amendment is tests/test_speeddesk_speed2_risk_integration.py: an old test constructed new3Up+3Down bids after a positive5/5pair using ordinary admission, now deliberately forbidden. It now explicitly seeds already-existing legacy LiveIntent reservations for those two bids. The financial assertions remain exactly unchanged: worst_loss$1.40, full conservative at-risk reservation$3.00, neither bid strictly balancing, and restored at-risk$3.00. No assertion was lowered or removed. This models outstanding legacy liabilities and is an appropriate fixture correction.

Independent rerun: **6passed in0.21seconds** for the entire amended test module. Prior149passing cases remain applicable to their byte-identical files/source; this renewal does not pretend a second full run. Root reported first full suite **1failed/6092passed/14skipped in302.35seconds**, sole obsolete fixture corrected here. Preserve that initial failure. Final full rerun remains root-owned and must pass before release.

During renewal current git HEAD was cdb032818b1ac91df82b908371d9c535b9b93a13 rather than the originally reviewed ee0e4b5. Independently verified that difference is only eight lines in docs/COORDINATION.md and all preexisting patch-file contents at HEAD equal their declared-base counterparts. An initial strict HEAD-equality verifier stopped on this docs-only change; subsequent explicit code-base and file-hash verification passed. No source/base ambiguity remains.

No new blocking finding. All prior limits, residual/cancel/crash/legacy caveats, unchanged late hedge, and profitability uncertainty continue to apply. No production or network action by reviewer.

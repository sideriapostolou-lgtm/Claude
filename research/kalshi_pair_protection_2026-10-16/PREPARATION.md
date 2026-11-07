# Protect completed profitable pairs

Prepared October15,2026 **8:56PM PDT** (October16UTC). This is an owner-requested reduction of newly permitted live risk. **Not a demonstrated profitable strategy or a break-even guarantee.** Source release and forward evidence are separate gates, recorded in RELEASE.md when available.

## Concrete behavior

The old policy allowed a new directional buy after a completed profitable pair. The exact-source fake and actual selected receipt arithmetic agree: Down5@$0.49 plus Up5@$0.45 costs$4.70 and guarantees$5 from those holdings. A new Down3@$0.51 is within the old25%imbalance allowance but can turn that30c inventory gain into a$1.23loss. It could also produce a$1.77gain if Down wins; blocking it forgoes that favorable$1.47increment. This is permitted old behavior being restricted, not a claim it broke existing caps.

The new risk book marks a window after each confirmed actual fill when both quantities are nonzero/equal within the existing epsilon and payout exceeds actual bought principal plus actual fees. Once marked:

- No new ordinary buy may add directional exposure. Confirmed imbalance after a residual fill may still be repaired, subject to all existing ordinary cash, fee, reservation, pair-cost, budget, stop, cutoff and ownership checks.
- Existing ordinary residual bids that are not strictly balancing are canceled through the existing lifecycle. Cancellation request,200,404,timeout or unknown orderID does not release liability without the existing fill/order reconciliation.
- The final transport guard rechecks the mark after waiting. A genuinely unsent refusal follows existing journal/refusal accounting. An uncertain create retains its full reservation and is not blindly retried.
- The existing late risk-reducing lock remains unchanged. Initial unmatched entry risk, stale/missing books and old cancellation races can still lose money.

`speeddesk_live_pair_protected` reports the first fill-triggered event and the confirmed inventory's payout/cost/`inventory_floor_usd`; outstanding orders are explicitly outside that floor. Panel `pair_protection` reports current open marked windows and a stored historical count. The historical count may include older currently qualifying holdings restored at startup, not just prospective events or profitable test windows.

## Persistence and authority limits

The irreversible per-window marker is a validated top-level `protected_windows` list. `WINDOW_PARTS` and strict existing cold-archive schemas remain unchanged. It is written with the existing fill-batch checkpoint, with no new network call, clock, save trigger, LLM or account scan. Prior real/practice financial receipts, costs, fees, losses, pending reservations, stop anchors, consumed controls and archived probability history remain authoritative.

Successfully checkpointed markers survive restart even after residual fills make holdings unequal. Older saves seed only their current confirmed positive equal holdings. They do not prove an earlier transient pair if now unequal. A process death before the existing checkpoint, followed by a differently ordered fill replay ending unequal, can miss an unsaved intermediate mark; an independent test preserves this limit. A qualifying confirmed subset within a batch is not proof that the physical account was flat then. Older code ignores the extra field and would withdraw this restriction; no automatic rollback is authorized here.

Effective dollar caps,5-contract maximum clip, existing first-entry policy, stops/resume budgets/ladder controls, Railway variables, late locks and Polymarket are unchanged. This source policy restriction adds no desk or money authority. It can reduce opportunities as well as risk. Practice/arena residents and the copied-order twin retain their existing documented pull, cancellation, lock-copy and fill differences; they are not automatically an exact new-policy counterfactual. Never manufacture practice fills from real executions.

## Broad prior-live evidence, including unfavorable tradeoffs

The cohort was fixed before this arithmetic: all returned live settlements ending **5:15–8:45PM PDT** /00:15–03:45UTC, including the partial restart window. Two known deployments were queried; no sealed research TEST, FamilyA/toxicity/MNQ, consumed reclaim confirmation or hypothetical fill simulation was accessed. This is past-production development evidence, not held out.

Fifteen actual settled markets: **8 positive,7 negative, net−$4.0182 after$0.2632fees** (within serialized-report roundoff). Fourteen returned fill totals reconcile to settlement; the first restart window is explicitly incomplete. All15 actual settlements reconcile payout minus cost/fees, including the incomplete window's reported result.11have a positive equal fill-log-publication-order prefix:4later finish negative;4finish above that earlier inventory floor;1finishes positive but below it;2have no later returned fills. Retain both lost gains and extra wins.

These prefix quantities are computed from returned actual receipts, not an authoritative timestamped controller-state replay. Of34later fill rows, all join intent platform publication after the prefix, but **one order's local intent time was earlier** than prefix publication. Existing resting orders, batched observations, delayed logs and cancellation races matter. We do not claim every later fill was a freshly admitted directional bet or that deleting them creates executable profits. No alternative P&L or strategy optimization is computed.

Ten unsaturated leaf queries support the used bounded returns. Initial3queries failed `Transport closed`; retained attempts are not called successful. A500limit parent returned501rows, so it and a saturated hourly parent were replaced by smaller unsaturated leaves, not treated complete. Broad substring filters also return82live-status rows,3practice-status rows and86unprefixed/malformed fragments; these are excluded from the three exact event families and preserved unrepaired. Two exact duplicate rows are deduplicated by platform timestamp/message. Removed old-deployment status is recorded as historical identity, not current-service failure. Complete market/account/queue coverage remains unverified.

Root's [cohort artifact](COHORT.json) and a separate [independent arithmetic audit](COHORT_INDEPENDENT.json) agree on counts/money within roundoff; the latter makes50explicit native hash/count/arithmetic checks. Both preserve clock distinctions and the incomplete first window. This supports testing a smaller exposure permission, not a profitable expectancy estimate.

## Exact patch and verification

Source base `ee0e4b520de29a8da0031d94eb90c0b0d5a4dc94`; latest coordination-only `cdb032818b1ac91df82b908371d9c535b9b93a13` was fast-forwarded before publication, with unchanged source. Final seven-Python-file patchSHA256 **edaad1806ae064aa081019531bfc0d1084c8026510d86ce81b3f064d721ffc8e**; [per-file hashes](PATCH_RECEIPT.json). Two source files, one new36-case test file and four intentionally affected old fixtures. The first six-file patch23a459ed remains preserved separately. [Implementation handoff](IMPLEMENTATION_HANDOFF.md) preserves all failed attempts and fixture changes. The earlier different synthetic scalar fixture is not relabeled as actual history.

[Independent exact review](EXACT_PATCH_REVIEW.md): no blocking defect in these exact bytes; **149focused cases pass**, overlapping new36 and existing93 plus20private independent cases. The reviewed149 and separately renewed6 speed2 cases pass; all7final hashes were rechecked, with the original6files unchanged. Sol's283focused cases also pass and overlap the full suite. No assertion about funds, stops, journal coverage or killpoints was dropped to get green. Old pull/stop tests now explicitly seed legitimate legacy unequal holdings/old liabilities; crash tests retain the original minimum sends/journal-depth bars using permitted canceled unfilled requotes. The first root full suite had6092passed/14existing skips and one obsolete post-pair-admission fixture failure. Its pending-cost assertions remain unchanged; only an explicit already-existing-liability setup replaced the newly forbidden admission. A complete final rerun is required. Review rejected an unproved adjacent cash-check hypothesis rather than expanding the patch.

Root owns full pytest, full mypy, changed-file Ruff, diff/credential review and exact release/runtime gates. [CHECKS.json](CHECKS.json) records their actual completed results; this preparation does not infer a successful deployment. Requested Sol/high and Astra/high delegation succeeded; actual runtime model IDs are not independently exposed to workers. Model names are not profitability evidence.

Probability source fingerprint remains **f2652c6b9f5f4732b5ac865d72c4748df250ad73b38d493387f9dfc478dcff6c**. This live-policy change does not alter the observer's fair-value/feed source or authorize a calibration reset. Retain current/archived epochs, pending/unknown forecasts and original losses through release.

## Forward requirement and unfinished work

Follow [FORWARD_PROTOCOL.md](FORWARD_PROTOCOL.md): after exact SUCCESS/readiness, predeclare the first eligible full quarter-hour at least120seconds after root readiness verification, with a separate two-minute tail. Freeze source/settings. Keep the selected window even if it loses, is stopped, has no orders or never exercises protection. No synthetic production orders, stop resets or forced live activation for coverage. A nonexercise stays unverified rather than becoming a success claim.

If a natural positive full-pair event occurs, join its confirmed fills, durable marker/publication, residual order IDs, cancellation/reconciliation, subsequent ordinary intents/send checks, actual settlement and successor-tail activity. Verify only actual observed outcomes. Initial one-sided losses and forgone opportunities remain in daily results. Longer prospective comparisons remain open after one window; the former profitable prefix is never claimed as an alternative realized payout.

EXEC, venue queue/print validation, full-account-scan/count exports, recorder raw-volume/retention fit beforeOctober20/measured cost and operating access/automation transfer remain OPEN. TJR LAST. This release does not resolve the remaining operating handoff or any sealed research gate.

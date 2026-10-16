# Kalshi entry and hedge correction

The owner authorized this correction after the actual-fill loss diagnosis. The
selection and evidence limits were written in [DESIGN.md](DESIGN.md) before any
deployment or outcomes of the new policy. No profitable result is established.

## What changes

An initial order can only use a price and whole-contract size supported by visible
opposite-side depth within the existing fee-inclusive pair cap. The candidate can
only become cheaper or smaller. Raw crossing maker starters remain ineligible;
the lower-price crossing fallback is for hedges of confirmed inventory. The transport check repeats this requirement;
an outstanding first-order remainder is canceled when the depth no longer covers
both confirmed unpaired shares and the remaining order. Cancellation does not
release the reservation before venue reconciliation.

Before the late-lock period, a strictly balancing IOC can complete confirmed
holdings within that same cap even when the standalone directional model dislikes
the missing side. It retains ordinary window/open/cash/clip budgets, fee and
transport checks, ownership, mode, stop classification and cancellation write
room. It does not borrow the late lock's budget exemptions. Its completion marker
is durable before submission and must agree in both saved intent records.

A maker hedge refused only by pair cost now searches lower cent prices at the
same size. A favorable model move cannot discard its existing queue position when
the best permitted replacement is the same price. Adverse-model, pull, freshness,
shutdown, stop and reconciliation cancellation rules remain effective.

## Limits retained

- Last verified configured limits: $20 per window, $40 open exposure, $12 daily
  loss, $10 total loss and 5-contract clip. No variables, anchors, consumed resume
  controls, previous losses, financial stops or existing late-lock policy change.
- Pairing is not atomic. Displayed depth can disappear and a fill can race a
  cancellation. No historical replacement fills or saved losses are invented.
- The depth calculation subtracts all original own resting quantities for the
  window, including canceled/filled quotes that may remain in a lagging public
  snapshot. This conservative choice can also remove genuine outside liquidity
  at a previously used price and cause missed trades.
- Practice stays separate. Its kept-bid and single-price take simulation does
  not fully reproduce this policy. Native status explicitly says comparisons are
  not comparable, and the page suppresses the current live-minus-practice control
  projection while retaining original records and the older-period projection.
- A saved true completion marker is a new schema field. The previous application
  cannot deserialize it and would fail closed. A rollback must not discard or
  rewrite these records to make old code load; use a compatible reviewed forward
  correction if needed.
- No Family A TEST, parameter fitting to later outcomes, paid service, order placed
  for testing or direct financial action is part of this work.

## Verification and release state

At **1:30:08 PM PDT**, the final-source full run passed **6,281 tests** with
14 existing skips (network/performance opt-ins and an absent lab cache). One
test-only pull fixture was strengthened after full-run collection; all modified
test files were then rerun: **218 passed**. Independent final selected checks:
**104 passed**; root reproduced the separate 21 adversarial cases. These suites
overlap and are not summed. Mypy passes 135 source files; changed-file Ruff
passes 13 Python files. Diff and added-content credential checks pass.

The first broad iteration had 16 failures, including the crossing-starter and
held-pull regressions that were corrected before release. A test-harness false
positive was also corrected and strengthened; details and exact logs are in
[VALIDATION.json](VALIDATION.json), [FULL_TESTS.txt](FULL_TESTS.txt), and
[MODIFIED_TESTS.txt](MODIFIED_TESTS.txt). Independent approval covers exact bundle
`3dcfe32a07a90bd708ae14f5404cae9660ffac39e27b3d2f9f1c3065ff9b6e29`;
see [review](REVIEW.md) and [file manifest](final_candidate_manifest.json).
Deployment and actual runtime verification are still pending.

The helper benchmark uses constructed states and warm indexes. Its measurements
exclude network, ledger I/O and production scheduling. They are computational
checks, not trade-fill evidence, venue latency or a profit estimate. With 999
synthetic book levels, the 55-tick maker search p95 was 0.86 / 4.73 / 21.70 ms
at 0 / 100 / 500 current-window terminal orders and 0 / 10,000 / 50,000 older
terminal orders. The 99-tick unsuccessful entry search was at most 0.31 ms p95.
See [exact outputs](HELPER_BENCHMARK.json); production scheduling remains unmeasured.

## Next evidence

After exact deployment and startup verification, inspect bounded native policy
status and actual decisions/refusals. An accepted order is not a fill, and no
eligible opportunity is not a failed test or proof of profit. The wider profitable
entry/hedge task remains open until a prospective fixed source/settings cohort
has complete actual fills, fees, settlements and explicitly accounted gaps.

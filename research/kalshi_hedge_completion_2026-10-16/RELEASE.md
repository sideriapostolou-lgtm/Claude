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
Released through [PR75](https://github.com/sideriapostolou-lgtm/Claude/pull/75),
merge `2f0bba487b4c88fa39299924b7a112e8413cb933`, at **1:33:19 PM PDT** in a safe
merge minute. The merged tree exactly equals the tested feature tree. Railway
deployment `7582010e-5681-41bb-964b-951e8b3c6767` reached SUCCESS at
**1:34:33.499 PM PDT**. Normal existing Polymarket LIVE startup is recorded.
See [deployment receipt](DEPLOYMENT.json).

The helper benchmark uses constructed states and warm indexes. Its measurements
exclude network, ledger I/O and production scheduling. They are computational
checks, not trade-fill evidence, venue latency or a profit estimate. With 999
synthetic book levels, the 55-tick maker search p95 was 0.86 / 4.73 / 21.70 ms
at 0 / 100 / 500 current-window terminal orders and 0 / 10,000 / 50,000 older
terminal orders. The 99-tick unsuccessful entry search was at most 0.31 ms p95.
See [exact outputs](HELPER_BENCHMARK.json); production scheduling remains unmeasured.

## Next evidence

Bounded release/startup verification is complete. Original native status at
**1:39:21.213 PM PDT** confirms the new policy identity, authenticated REAL MONEY,
`trading_now=true`, empty waiting reason and a clean 427.7 ms recent reconciliation.
Cash is **$47.3599**; cumulative settled P&L remains **−$27.4415**, including
**+$8.842332** locked and **−$36.283832** directional. Current UTC-day settled P&L
remains **−$7.9497**. These are retained native totals, not a newly audited complete
ledger. Cash is not trading profit. Caps, both latches, 953 fills, 242 settlements,
fees, zero reservations and zero unpaired risk exactly match the last old-source
snapshot. Three already-used resume/reset controls were ignored at startup;
anchors and consumed-control hashes were not read. [Runtime](RUNTIME.json),
[cold startup](STARTUP.json), [last old status](LAST_OLD_STATUS.json).

The current protected pair cost $0.94 and was completed before deployment. Its
eventual settlement belongs to the old policy. There were no new native
order/fill/settlement log headers returned in the unsaturated **1:34–1:40 PM PDT**
query; new entry/completion execution is therefore **not yet verified**. The
existing practice twin is explicitly noncomparable. Page projection tests pass;
an authenticated production page read was unavailable.

The first three native snapshots were blocked after full-account scans taking
6.7648 / 5.4735 / 5.8191 seconds. Later freshness is verified; minute-aligned
samples do not establish continuous staleness or continuous readiness. Periodic
slow reads remain open. The same bounded error search returned no ERROR/Traceback
lines. A separate legacy learning recorder did log `low_disk free_mb=210`; this
does not establish whole-volume capacity or recorder retention. Bot and standalone
Kalshi recorder were both online with one replica; the latter's deployment was
unchanged. No capacity setting or paid resource was changed.

Next, freeze a prospective source/settings cohort before its start and reconcile
all actual fills, fees and settlements, including failed and zero-fill windows,
with queue/markout gaps explicit. No replacement fills or saved losses are
invented. Profitable-entry evidence, periodic reconciliation delays, capacity,
town acceptance and full operating handoff stay on their existing open records.

# Storage persistence repair and loss evidence

Owner asks why the bot is off and unprofitable, and to fix both. Source repair
base `f0ce4f8c02692bcfc9ad7071080c4c1deafed098`, branch
`codex/storage-recovery-20261018`. Work began October18 around5:01PM PDT
(October19 UTC). Runtime recovery, source correctness and profitability are
separate acceptance items.

## Current facts

Read-only Railway inspection around **October18, 5:01–5:03 PM PDT** still shows
bot deployment `43f14443-2d07-4985-b879-3a2515fb8d2c`, source PR76 `f370c3c2`.
One running container is not a healthy trading desk. The5000MB bot volume is
`61e83042-65c2-4aff-855b-a24a3b7989aa`, mounted at`/data`. The requested one-hour
metric has61samples; latest disk4.99613696GB, memory1.636794368GB. Actual available
filesystem bytes/inodes and file allocation remain unknown.

The [previous audit](../daily_status_2026-10-18/REPORT.md) records October17
1:58AM Kalshi companion failure/cleanup unconfirmed and a simultaneous Polymarket
state-save traceback explicitly proving ENOSPC. Kalshi's exact failure operation
is not exposed in its log. No later native status or Polymarket startup was
returned in the bounded fresh service query throughOctober18 5:01PM PDT; it is
provider evidence, not a current venue-account certificate.

A second exact-deployment query completed **October18, 5:19:08 PM PDT**:
current active deployment remains the same, and the requested4:55–5:18:45PM
native-status/startup/halt/disk-error filter returned0rows against that exact
application deployment. The platform reports1/1online, without task-health proof.
The old October12 empty staged patch is still present and untouched.
[Bounded request and original response](FINAL_PLATFORM.json).

Current authenticated cash/positions/orders remain unverified. Last complete
native October17 1:58:44AM snapshot was cash47.0925/cumulative−27.6489/zero reported
exposure then. Effective caps20/window,40open,12daily,10total,clip5; reduction-only
policy with new starters disabled. Those facts must not be relabeled current.

## Implemented source repair

1. **Kalshi display failure no longer disables committed financial state.**
   Financial ledger/receipt/archive/pre-send-journal transactions remain required.
   Only a later optional JSON display-copy OSError is isolated. Failed display
   writes retain the previous file/source timestamp, log a bounded error, and
   retry after60seconds. Native panel status exposes degraded display persistence;
   this does not claim the existing phone UI renders the new field. Successful
   replacement publishes recovered metadata. Only this attempt's derived
   temporary file is cleaned after a successful open. A preexisting temporary
   remains untouched if opening it fails; a successful truncating open may
   replace that derived temporary. Authoritative financial state and archives
   are not deleted.
2. **Polymarket authoritative-save failure now stops explicitly.** A failed state
   save disables the order client, stops that desk's loop and logs the fault without
   trying another save on the same failed disk. Subsequent poll/save calls reject
   in that process. Existing losses, pending liability, stops and consumed-control
   fields remain intact in memory; the last committed target remains unchanged.
   The latch cannot persist to a failing disk and does **not** certify a safe restart.

There is no new strategy, entry enablement, budget reset, automatic restart or
change to financial thresholds. No observed production file is assumed disposable.
The code prevents two reproduced failure paths; it does not magically create disk
capacity or prove that the existing authoritative state includes all activity.

Reviewed four-file patch hash:
`d3cdde2f73aff37f0be3b5c883359d714b1a3481c007e52b3684bde08be8643e`.
See [implementer scope/checks](IMPLEMENTER.md) and [independent review](REVIEW.md).
Two Sol workers handled bounded implementation and receipt analysis; Astra
independently reviewed recovery/accounting and reproduced the research. Models
launched as requested; billing/token costs are not exposed.

## Profitability result

The [new reproducible loss assessment](../kalshi_recovery_loss_2026-10-18/LOSS_MECHANISM.md)
reconciles149 actual fill receipts and55 settled traded windows plus5empty
settlements fromOctober16UTC. Earliest executed orders, including all their
partials, contributed **−$16.3428** at actual outcomes; every other actual order
contributed **+$8.1730**, totaling **−$8.1698 after fees**. This is fixed-receipt
cash-flow attribution, not an executable first-order-only or hedge-only strategy.

Only5/55 first orders have retained predecision fair joins, all from selected
loss investigations. That cannot identify an unbiased profitable entry filter.
Two queue-zero observations in the PR75 losing window did not produce a hedge
fill. Its three first-fill markouts are invalid/missing. A profitable replacement,
guaranteed break-even or profitable earlier exit remains **unproved**. The prior
losses and every failed-completion tail stay included; no FamilyA TEST is opened.

The concrete next test is conditional first-fill calibration and second-leg
liquidity survival, using complete historical journal/decision coverage first,
then a frozen forward rule with conservative execution evidence. Filtering on
eventual balanced inventory would leak the future and hide the actual losses.
Existing no-new-starter containment remains in force.

## Required test gate

The initial full suite finished **6,312 passed, 2 failed, 22 skipped** in354.58s.
The failures were the unchanged arena busy-flush CPU p99 and deep-book backlog
checks. Targeted storage/accounting checks and mypy/Ruff passed as linked above;
those do not substitute for the required full suite.

A serial baseline/patch/patch/baseline comparison verified each imported source
path before running the same two test nodes, with identical thresholds:
**2passed;1failed/1passed;2failed;1failed/1passed**. Busy-flush p99 was
.392/.738/.693/.592ms against a .5ms limit. The unchanged baseline reproduces the
flush failure; the backlog failure has not been reproduced on baseline in this
comparison. Patch backlog passes in the isolated rerun and one comparison run,
but that variability does not prove baseline equivalence. Neither threshold was
changed, no failed check was waived, and these measurements do not certify
production throughput. [Original result summaries/hashes](VALIDATION.json) and
[independent final documentation/timing review](DOCUMENT_TIMING_REVIEW.md).

The first run had nine missing-scientific-dependency skips. After installing
pandas/scipy/numpy locally, the final full suite finished **6,332 passed,2failed,
14skipped in341.59s**. The same busy-flush test failed at p99.896ms (limit.5ms),
and deep backlog failed with10,660pending (required<1500), with zero drops.
The14remaining skips are12opt-in network checks,1opt-in wall-clock benchmark and
1unavailable lab3cache. Dependency versions and original log hashes are recorded.
No source/test changes were made between runs. Mypy passed135source files;
changed-file Ruff passed5files including the research script. Full release gate
is **FAILED**, not waived. No source push, PR, merge or production deployment.

The exact repair is saved as **local, unpublished** commit
`0f7eba1f26c09ea9895f8ee84381b2d164a25ed2` on
`codex/storage-recovery-20261018`. The candidate patch and source snapshot are
provided privately with the owner-facing handoff artifact; they are not deployed.
Applicable four-file patch SHA256:
`6887a85254a286aee3997f7f4f750ed6f10bcdbefcd2dbda4f65fb2a7904434e`.
This differs from the reviewed-diff-plus-raw-test hash above. Preserve every
failure; resolve the performance checks before source publication under
AGENTS.md's green-before-push rule.

## Release and operational acceptance

Source tests/review are separate from deployment. Production recovery requires:

- A bounded read-only free-space/inode/per-file inventory and integrity check of
  the actual authoritative state, preserving original files and all losses.
- Fresh authenticated venue balance/positions/open orders/fills/settlements since
  the last good snapshot. Valid JSON and free bytes alone do not reconcile missing
  losses or consumed controls after an interrupted save.
- A measured evidence-preserving capacity/recovery action, followed by exact
  safe-minute release/startup/native financial-state retention verification.

The connected Railway tools expose logs/configuration/metrics, but no raw-volume
shell/export. CLI5.70.0 was installed from the official release after npm's
download failed ECONNREFUSED; normal CLI authentication returned Unauthorized.
A standard browser sign-in was offered to the owner and expired without
completion at approximately October18 5:14 PM PDT. No credential was requested
in chat, read/listed or placed in the repository. A metadata-only bounded inventory
script is prepared locally for an authorized SSH session; it has not run on production.
A fresh normal sign-in was offered about5:17PM PDT and remains pending at this
report cutoff. No successful server access is claimed.

No storage resize, purchase, old-data pruning, variable/cap/stop/resume-token change,
order, transfer or production restart was performed. Runtime recovery and
profitability stay OPEN until their evidence exists; a tested patch is not a
claim that the bot is running or profitable.

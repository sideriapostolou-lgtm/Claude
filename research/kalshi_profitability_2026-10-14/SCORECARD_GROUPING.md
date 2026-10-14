# Reduce repeated intent scans inside the live report

Prepared October 14, 2026, 3:57 PM Pacific (PDT, UTC−7). The correction is local
until its full checks and release receipt are recorded. It changes report
computation, not order decisions, financial settings or persistence cadence.

## Observed problem and focused correction

The running diagnostic includes live-panel work inside a real read-resumption
gap: at 3:46 PM, one nested live panel used 44.885 ms of thread CPU. That does not
explain all 2,768.346 ms of the enclosing gap. See
[original active trace messages](QUIET_ACTIVE_READS_1548_PDT.json); nested work
must not be added to its enclosing span.

The scorecard loops over each ended window and scans every stored controller
intent to decide whether coverage remains unknown. A populated invented-state
profile with 200 ended windows and 3,350 intents records 670,200 generator
iterations in a panel. Its [profile receipt](panel_checkpoint_profile_receipt.json)
and [exact script, fixture and observations](panel_checkpoint_profile_evidence.zip)
preserve the source, limitations and lower-density result.

The correction groups ordinary native intents by their window **within each
scorecard call**, preserving their insertion order. Each window then evaluates
the original lazy predicate over only its matching intents. No group survives
the call; subsequent field changes, replacement or removal are seen afresh.

The fast path requires exact model/mapping types, native string identifiers and
ordinary boolean flags. Custom mappings, subclasses, custom truth/equality
behavior or malformed fields use the original scan. Twin reporting, no ended
windows and latched integrity checks do not build groups. Reservation lookups
remain lazy and occur in original window/intent order; unrelated missing records
are not accessed. No eager set of unsafe windows is computed.

A persistent active-window cache was considered and rejected because mutable
Window.slug and arbitrary public history mutations can invalidate it silently.
The separate positions-report scan is unchanged in this release.

## Behavior and timing evidence

The exact pre-change scorecard from commit
`1ef0f9270c079ca29b6074360918838fe26f8cff` is saved as a local test fixture,
SHA-256 `25d1270b5eb2c2ebaa29ad80ebb02df7cfa3d2dd020015ee5684e006c5e90f79`.
Tests require neither Git history nor network access.

There are 19 focused differential cases and 12 independent adversarial cases.
They preserve complete outputs, financial state and receipts, lazy missing-record
failures, exception identity, custom side effects, duplicate aliases and mutations
between calls. Independent review accepted the four-file source/test/fixture
bundle `5f2612a5a39bd58b70919f0f99fb75e5bbdbe67dae1f1d758ae7557e26ce872c`.

A clean six-pair alternating baseline/candidate run, with no competing local job,
ran from 3:55:40.007 to 3:55:44.364 PM PDT. Median wall timings:

| Operation | Original | Grouped |
| --- | ---: | ---: |
| Actual live panel | 69.189 ms | 28.344 ms |
| Actual practice checkpoint including live panel | 79.999 ms | 38.273 ms |

All six checkpoint pairs match decoded ledger, mirror, model, receipts and return
value; receipt chains verify. Panel outputs/model/receipts match. A panel does
not save state, so inherited prior-save snapshots are explicitly excluded from
that panel-only persistence comparison. The first run may have overlapped a
short mypy process; its observations are preserved separately, not substituted
for the clean repeat.

These fixtures use invented zero-fee paired fills, a cold Bitcoin tape, no active
orders, no account reads or network, and no arena. The positions fixture retains
200 zero-valued keys; the production density of those keys is unknown. This is
an algorithm/behavior comparison, not production replay, fill improvement or a
profitability test. Production benefit and remaining latency require actual
post-release measurements. All recorded real losses remain.

Full pytest passed: **5,502 passed /14 existing skips in304.06 seconds**, with
subprocess return code zero. Source mypy checks126 files and Ruff passes on all
three changed Python files. The first full log also reports5,502 passes, but its
tool exit code was1; preserve that discrepancy rather than assuming its cause.
The independently captured repeat resolves the successful-test-exit gate.
[Checks](scorecard_grouping_checks.json) and the [evidence archive](scorecard_grouping_evidence.zip)
retain both runs and both benchmark observations. Exact first benchmark source
bytes were not saved separately; only its source hashes and observations survive.
The clean executed source is retained exactly. No recovery of the first source is claimed.

Record the exact deployment before calling this released. EXEC-DELAY-001 remains
open until its production verification requirements are met; the second strategy
task has not started.

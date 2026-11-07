# Bounded quiet-work occupancy diagnostic

Prepared October 14, 2026, after the scalar correction. Not a new trading rule
or another strategy comparison. The first complete post-scalar active window
must finish before another source release; existing financial rules remain.

## Why retained slow spans are not complete coverage

PR #52 retains at most 512 spans taking at least 5 ms. Quiet callbacks have only
counts/maxima. Hundreds of thousands of short callbacks can consume substantial
time without a retained detail row. Early PR #53 runtime observations still
include a 2.89-second read-resumption tail; a corrected scalar converter does
not explain or solve all the delay. These early rows are restart-partial context.

## Conservative additional measurement

WorkBins adds 512 fixed bins of 31.25 ms, at most 16 seconds of history. Only completed
top-level synchronous spans contribute, including those shorter than 5 ms. Split
wall occupancy at exact binary bin boundaries; nested work is not added again.
Only bins completely contained in a requested gap count toward its wall lower
bound. Query boundaries, pre-observation time, later idle/unobserved time,
retention loss, long-span clipping and active spans stay explicit.

CPU is added only when a complete top-level span fits inside one queried full
bin. Crossing spans are omitted; CPU is never prorated by wall overlap. This is
a lower bound, not total loop CPU. Aggregate non-finite CPU fails only the
observer, preserving business execution and strict-JSON-safe publication.

The existing slow-span coverage and new all-work lower bound overlap and must
**never be added**. Existing covered/unattributed fields retain their original
slow-span meaning. The additive field is named all_sync_work_lower_bound.
This measures completed observed intervals, not all process CPU, GIL ownership,
network latency, missed messages or every uninstrumented callback.

No I/O, clock reads, locks, cross-thread traversal, per-tick log, worker thread,
account request, save, decision or await is added. Storage and record/query work
are bounded by 512 bins, including a huge-duration span/query. Publication uses
existing trace buffering/checkpoint cadence. Status/query faults disable
diagnostics only. Trading exceptions and synchronous persistence retain order.

## Verification before release

Root's eight focused cases plus six independent cases cover quiet cumulative
occupancy, nested union, excluded query edges, CPU containment, sparse/empty
intervals, retention and huge spans, random interval/CPU oracle comparisons,
representable boundaries at ordinary/large clock origins and error isolation.
Existing helper/integration checks remain unchanged. Independent review found a
finite-per-span CPU accumulation overflow; a finite aggregate guard fixes it,
and the independent regression pins failure isolation/JSON safety.

Reviewed four-file source/test bundle:
`db8dfd78384b96cf1c251cdb2614b628767392263287419a16b8e8a52c8ff135`
(sorted relative path +NUL+ exact bytes +NUL). No blocking finding remains.
Final complete checks: **5,471 passed /14 existing skips in305.84 seconds**,
source mypy126 files and changed-file Ruff all4 Python files clean.
[Exact full-run log](quiet_bins_full_pytest.log) is retained. No source/test
changed after the reviewed bundle.

[Independent overhead samples](quiet_bins_overhead.json) compare immutable
67c54a6 with the local candidate: eight alternating pairs of 3,000 two-span
samples. Median 6.929 -> 10.519 microseconds per pair, about 1.795 microseconds
added per callback. This is empty-span synthetic overhead, not a production
speed/latency claim. [Exact session script/results archive](quiet_bins_overhead_evidence.zip)
includes hashes; the original script retains session-specific paths. Unchanged
full-suite performance gates apply; no threshold is weakened.

No release, full-window coverage, profitable strategy or task completion is
claimed here. Actual deployment and post-release join results must be verified.

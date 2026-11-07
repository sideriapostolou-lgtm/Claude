# Remove repeated Python writes from the live display save

Prepared October14,2026,9:31PM Pacific (October15,04:31UTC).
This is a focused partial correction for EXEC-DELAY-001, not a new trading rule
or evidence of a profitable strategy. Running source remains PR57's `10f7f9d`;
the new correction is local until the fixed capture closes and checks pass.

## Measured reason for the change

The startup-partial identified Bitcoin-loop rejection at9:13:07.659PM has exact
complete-message acceptance→public-recv residence **2,731.530ms**. In that interval
a fully contained live display-mirror span takes **280.869ms wall/193.018ms thread
CPU**, nested in a377.893ms checkpoint. These are overlapping populations and must
not be added. Practice checkpoints and other work also contribute; this change
does not explain or remove the entire wait. The original matched event and
independent interpretation are preserved in [the preparation archive](live_mirror_preparation_evidence.zip).

The first regular window also contains a known main-loop rejection at9:22:44.833PM:
2,769.481ms local residence and3.122s sending-source age. Its conservative full-bin
work occupancy is2,157.406ms, with52slow-span details omitted. The native ring's
other overflowed receipts stay unknown. These are bounded incident observations,
not whole-feed coverage, and time before protocol acceptance remains unresolved.

**Producer limitation:** WeatherWS inherits the same receiver/logger on another
thread/process. Old session numbers are instance-local and cannot distinguish the
two. Untagged warning totals are shared-producer totals; absence of local_work
does not identify weather. Present worktrace plus verified main-only wiring
identifies the two examples above. The earlier exact review missed this surface;
its corrected startup analysis is retained, rather than retroactively assigning
unknown events to Bitcoin.

## Small implementation and unchanged recovery boundary

The live display mirror currently calls `json.dump`, whose Python iterator emits
many small writes. The practice display helper already uses one compact encoding.
Use `stream.write(json.dumps(full,allow_nan=False,separators=(",",":")))` in the
existing temporary-file context, then the same atomic rename. Keep ASCII escaping,
key insertion order, panel/archive composition, ten-second mirror schedule and
last_mirror update after successful rename. Ledger commit, receipt hashes,
durability, journal, reservations, stops, budgets and decision code stay unchanged.

The mirror is for display; constructor recovery reads the ledger and refuses a
missing ledger beside an existing mirror. It never restores money from the mirror.
Tests pin this with a committed ledger followed by failed replacement and corrupt
display. Encoding/write/replace failures preserve the prior target and timestamp,
while the already completed ledger commit remains authoritative. Silent short
returns without an exception were unchecked by the old writer and remain outside
this one-line correction; injected partial-write-plus-OSError is tested.

Timing events and gap warnings also gain reader kind, instance counter and process
ID so the base speed desk and derived readers can be distinguished. Successful
session numbers accompany the same reader identity; a failure before session entry
reports no current session instead of borrowing the previous one. IDs still require
deployment/process-incarnation scope and are not globally unique across restarts
or replicas. No timestamp replaces source freshness evidence.

## Offline performance and limitations

The deterministic synthetic1.77MB full mirror needs346,744write calls with the
iterator and one with the compact encoder. Eleven-sample median wall times are
roughly86.8–88.0ms versus14.6–17.5ms in the two recorded runs. Trials ran old then
new, not a randomized/reversed benchmark. These measurements support the mechanism
and rough offline benefit; they establish no production speedup. Benchmark CPU
is process CPU, distinct from production WorkTrace thread CPU.

Peak traced Python allocation changes from87,604to3,549,061bytes, approximately
3.46MB extra for this synthetic case. This is not a process-RSS or production-size
bound. Largest retained production display size was not directly exported.

Supported checkpoint states preserve exact bytes, including archives, panel,
Unicode/surrogates, signed zero and extreme finite floats. **Universal exception
identity is not claimed:** on the testedPython3.12,1,100nested lists fail with
RecursionError in olddump but succeed with C-backed dumps. Actual fixture state
has depth5; the checkpoint test pins a shallow supported model. This incidental
malformed display recursion threshold is not a financial safeguard. NaN/Infinity
rejection and unsupported-value failures remain covered. No generic depth guard,
ledger fast path or receipt/canonical-JSON change is included.

## Exact review and release gate

Four-file sortedpath/NUL/content/NUL bundle:
`0faa0c5d9a1fd07c4824f51b323ec5a4d068837d6d0fdf64fb4ea6cee7eccac2`.
[Independent Astra review](LIVE_MIRROR_REVIEW.md) accepts this exact partial-fix
and identity scope, after123targeted tests passed. Root targets also pass100tests
separately on websockets13.1/14.2; mypy127 and changed-file Ruff pass. Final full
pytest passed **5,564tests/14existing skips**,300.09s with capturedexit0;
the exact reviewed four-file bundle remains unchanged. No successful release claimed.
The earlier pre-review full run was interruptedexit137after the warning-identity
fix and is retained, never counted as passing.

The first PR57 capture stays frozen9:15–9:45PM with9:47PM publication tail.
No production source release before the collector closes. Then re-read current
AGENTS/COORDINATION/remotehead, retain all original evidence and losses, perform
required checks/credential scan, merge in a safe minute, verify exact Railway
SUCCESS/normal startup and selected financial-state continuity. No Railway
variables, caps, stop/resume budgets, real-money activation or orders are changed.

Use the original [prospective coarse verification criterion](FEED_FAIRNESS_VERIFICATION.md):
3,000ms actual worker-completed→read-coroutine-resumed or covering main-loop lag,
with required counters/publication/retention checks. This is not an all-read250ms
or subsecond certificate. Main-reader freshness regressions remain a separate
surface; unknown or missing evidence cannot pass it.

For the correction, freeze the first two complete15-minute windows strictly after
verified startup, with a two-minute tail and covering account status intervals.
Keep restart partial separate and every outcome. Report main versus derived
reader gaps, known/unknown receipts, account resumption/lag and callback-work
retention/omissions. Do not pool interval quantiles or subtract unrelated maxima.
Report real fills/fees/locked-versus-directional settlements and preserve all loss
history; practice stays separate. If substantial backlog/freshness problems remain,
keep EXEC open and attribute the next contributor. The strategy comparison remains
unstarted, and TJR remains blocked on authentic data/costs with paper/live disabled.

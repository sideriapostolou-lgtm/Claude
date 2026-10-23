# EXEC-DELAY-001: attribute the local pause, fix it, verify the result

Owner requested sequential completion on October 14, 2026, around 2:18 PM Pacific.
This task precedes activation of the frozen strategy comparison. It is execution
engineering; no return, fee, decision rule, risk limit or new live authority follows.

## Existing evidence and first measurement release

PR #51 recorded a 109.694 ms account callback followed by 2,476.114 ms before the
controller resumed. That establishes a local delay in one cycle. It does not
identify the task occupying the loop or establish the financial cost of the delay.

The practice trial, live companion and public feeds share one event loop. Practice
decisions synchronously checkpoint on book/trade callbacks. Those checkpoints
rebuild daily reports and state, commit the ledger, log receipts and write a page
mirror. Real checkpoints and feed decoding also perform synchronous work.

The first release observes those existing synchronous intervals with the same
monotonic clock as reconciliation. Thread CPU measures the whole interval; it
cannot be apportioned exactly to an intersecting read-resumption gap. Nested
wall times are joined by interval union, never summed. Time outside retained slow
spans stays unattributed; OS scheduling, GIL contention and uninstrumented work
remain possible.

Only 512 slow spans (at least 5 ms), 64 active nesting levels, 32 displayed spans
per query and fixed per-section aggregates are retained. Evictions, omitted
details, quiet spans and pre-observation gaps remain explicit. No private request,
trading action, asynchronous writer or per-tick log is added. Trace publication
uses the existing bounded buffer and already-selected checkpoint cadence.

Diagnostic failures affect only the observer. Trading exceptions still propagate.
Snapshot publication, feed invalidation, receipt order, first-save durability,
ledger-before-mirror ordering and shutdown cleanup retain their existing order.

## Local probe

A synthetic local workload used 288 settled empty windows and 36,000 timing
values. One **profiled** checkpoint took 169.75 ms: ledger section 98.66 ms,
historical reports 38.41 ms, state/panel 25.67 ms. Profiling attributed about
92 ms to the ledger's recursive `to_jsonable` conversion of an already-built
state. Profiling changes timing, the input is invented, and this is neither a
production attribution nor a baseline for a claimed speedup. It identifies
additional candidates to compare against the new production intervals.

## First production attribution, October 14 at 3:01 PM Pacific

Measurement PR #52 reached SUCCESS at 2:55:20 PM PDT, exact commit
`0d93fe3c764d2ac743661e681ca1911ec1bf81a9`. The
[scoped release/account/trace receipts](shared_loop_trace_release.json) preserve
the actual two early traces, pre/post financial snapshots and platform status.
The restart retained the losses, cash, exposure, caps and used-resume history.

At 2:56 PM, one 311.928 ms read-resumption gap overlaps 213.149 ms of retained
work by interval union. The practice checkpoint overlaps 185.551 ms; its ledger
span is 76.078 ms wall /39.415 ms full-span CPU. At 3 PM, one 1,814.169 ms
positions resumption gap has 450.555 ms covered and 1,363.614 ms unattributed.
A practice checkpoint inside it takes 340.712 ms wall /139.045 ms CPU, including
ledger227.757 ms wall /45.371 ms CPU and state75.324 ms wall /61.958 ms CPU.
Do not sum those nested times or prorate whole-span CPU to overlap. Bounded
detail omissions, quiet spans, retention and uncovered time remain in the receipt.

This establishes checkpoint/serialization work as a contributor, not the whole
cause of multi-second pauses. A local exact-native-scalar conversion shortcut
reduces synthetic checkpoint median wall time53.193 to39.947 ms (15 alternating
pairs, identical stored state/receipts). It is still provisional and unreleased;
the local reduction is not a promised production speedup or profitable strategy.
The initial full-suite CPU-tail failure remains recorded while controlled
diagnostics and serialized verification proceed. No thresholds were weakened.

## Partial correction release, October 14 at 3:11 PM Pacific

[PR #53's scalar shortcut](SCALAR_CHECKPOINT_FIX.md) is running on exact
`95ff8acb35294de7080460721c0a47a7934d4a37`, deployment
`f838b81d-1bee-49f3-9083-e71a6cd0ae6f`, SUCCESS3:09:32 PM PDT. The
[release receipt](scalar_fix_release.json) verifies startup, platform health and
retained financial state. Full checks pass; the earlier failed timing run and
all controlled raw observations remain archived. No strategy/risk/variable change.

The first complete post-restart window is3:15–3:30 PM Pacific. Its evidence is
pending; a cold startup save is not a comparable steady-state performance sample.
Do not claim a real speedup or task completion from the synthetic25% reduction.

Read-only source review identifies an observation limitation: short callbacks
below5ms are counted but not retained with timing. Cumulative short work can
occupy material time. Arena flush/snapshot work is already enclosed by outer
practice/feed spans, so absent inner names alone cannot explain uncovered time.
Unwrapped REST batch parsing/delivery, WebSocket dispatch/reporting and some
settlement/markout work also remain candidates. Other engine/page threads may
contend for CPU/GIL; wall-vs-thread-CPU evidence does not prove that mechanism.

If material gaps remain, the next diagnostic proposal is fixed monotonic time
bins accumulating top-level synchronous occupancy, including quiet spans. Query
only fully contained bins as a conservative lower bound, keep boundary/retention
loss explicit, never add it to overlapping slow-span coverage and never prorate
CPU by wall overlap. Bounded loop/process-CPU deltas could distinguish work from
off-thread contention as hypotheses. This is a proposal, not implemented code.
Keep no spans across await, no shared cross-thread observer and no per-tick logs.

## Quiet-work release and remaining correction, 3:50 PM Pacific

PR #54 is verified deployed on exact `89b7b6d`, SUCCESS at 3:33:15 PM PDT.
The [release and window report](QUIET_WORK_RESULTS.md) preserves original receipts,
full checks, the completed post-PR53 window, remaining timing tails and warnings.
The new bins observe accumulated short work; they do not themselves remove it.
One 1,028.850 ms resumption gap includes at least 756.031 ms of observed wall
occupancy and 568.158 ms of whole-contained-span CPU. Substantial gaps remain.

One completed window made $0.3641 after fees; cumulative recorded bot losses remain
−$14.2971 in the 3:33 PM snapshot. Neither is proof of a profitable strategy.
A naive active-window index was rejected because public mutable windows/history
can invalidate it. The next focused candidate is redundant live scorecard work
inside the measured panel/checkpoint path, subject to profiling and parity review.
No active-index correction, task completion or comparison start is claimed.

## Completion evidence required

1. Identify the measured blocking section from joined production intervals,
   preserving uncovered time and bounded retention limitations.
2. Make the smallest correction supported by those intervals. Prefer avoiding
   redundant synchronous computation; moving mutable model/ledger work into a
   background thread needs a separate snapshot/ordering design and review.
3. Reproduce equivalent decisions, receipts, accounting, exceptions, first-save
   ordering and cancellation behavior with fakes. Compare the same synthetic
   workload before/after without using a timing threshold as correctness proof.
4. Run full pytest, source mypy and changed-file Ruff, scan added content for
   credentials, obtain independent review of the exact source and release in a
   safe merge minute. Verify the exact running commit, both service health,
   normal Polymarket startup, retained losses/caps/stop history and new diagnostics.
5. Collect repeated post-fix observations during active trading, including a
   completed window beyond the restart partial window. Report actual counts,
   tails, omissions and external request variation. A single fast read does not
   resolve a tail, and improved latency does not establish a profitable strategy.

Measurement deployment alone leaves this task open. The strategy comparison
remains the second task; TJR's separate historical-data blocker remains recorded.

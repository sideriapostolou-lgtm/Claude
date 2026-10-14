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

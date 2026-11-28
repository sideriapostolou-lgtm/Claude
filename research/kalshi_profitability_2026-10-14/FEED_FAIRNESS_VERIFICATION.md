# Prospective verification of the owned-feed scheduling correction

Frozen October14,2026 at4:48 PM Pacific, before candidate deployment or any
post-candidate production result. Integration owner: Codex. Task: EXEC-DELAY-001.
The original/inverse/no-trade comparison stays unstarted until a recorded close
or a separately explicit owner reprioritization. No new trading authority follows.

Observe the **first two consecutive complete15-minute windows after the verified
restart**. Preserve the restart partial window separately. Derive actual tickers
from original events, never an assumed naming convention. Do not replace a poor
or inconclusive window with one selected for its outcome. Continue collection
through a bounded publication/settlement tail and label anything still pending.

The existing task specifies repeated observations, but no numerical latency SLO.
This proposal adopts a **coarse recurrence threshold of3,000ms** for local actual
worker-completed→`_read`-coroutine-resumed delay or observed loop lag. This is a
new engineering criterion for the recorded multi-second problem, not an existing
owner requirement, a financial safety bound, or a promise of subsecond execution.
A250ms all-read controller-resumption criterion cannot be assessed by the current
selected-trace observer; do not claim it passed. No threshold is changed in code.

For each window retain:

- Original orders, cancels, fills and settlements joined by IDs, exact prices,
  counts, fees, locked/directional P&L and observation/venue timestamps. Cancel
  requests and404 responses do not prove liability was released. Preserve all
  cumulative losses, caps, stop anchors and consumed-resume history across restart.
- Continuing market callbacks and completed account reconciliations. Record actual
  order/cancel/fill activity without causing trades or requiring a fill. Missing
  activity/coverage is inconclusive, not zero latency or a selected quiet success.
- Every retained selected trace and its actual worker completion/coroutine resume/
  wrapper return marks; external callback/page/byte/cancellation costs separately.
- Status intervals whose union covers the entire two-window period, including
  first/last straddling intervals, with per-operation done-callback count/max and
  loop lag count/max. Preserve fully contained results separately. A boundary
  interval at the threshold is conservatively failing/inconclusive if its tail
  cannot be located; never discard an edge interval for a negative claim. These
  are different endpoints/populations from actual `_read` marks. Never pool
  interval medians/p90 or subtract cumulative maxima.
- Whole-callback maxima, slow-span union and conservative quiet-bin bounds, keeping
  uncovered/boundary/retention time and omitted details. Nested CPU is not additive.

A local resume delay at least3,000ms makes its whole cycle at least3,000ms and
therefore eligible for the existing slow-cycle trace. This implication alone does
not prove delivery. Before making a bounded absence-of-recurrence claim, verify
observer enabled/error clear, suppression and dropped-buffer counters unchanged
at zero, publication tail drained, original reported rows reconciled to report
counts, no query cap/gap, no omitted reads or missing required marks and no
unfinished/straddling read capable of concealing the assessed tail. Include cycles
intersecting the windows even if they start before or finish after a boundary;
verify the active cycle completed, not merely that a query end time passed. Session
counters cannot be treated as per-window totals. All covering status intervals
must not hit their8192-sample ceiling. If these conditions cannot be verified,
record an evidence gap and leave the task open rather than inventing coverage.

Pass the finite engineering gate only if both qualifying windows have adequate
coverage and no recurrence at that threshold, no financial/freshness/cancellation
regression, and no known contributing mechanism left unexplained. Smaller residual
maxima remain in the report; individual synchronous callbacks and the separate
Polymarket SDK receive loop remain explicit limitations. A yield cannot interrupt
one expensive callback. If an identified contributing surface remains unresolved,
perform a bounded attribution investigation before closing.

Fail/open on observed recurrence or a behavioral regression. Inconclusive/open on
insufficient activity, telemetry, pending publication or unreconciled financial
records. Neither two positive financial outcomes nor an exact deployed commit
substitutes for these checks. Two qualifying observations establish only the
stated bounded result, not a causal percentage improvement, future latency bound
or profitable strategy. Do not infer that every actual read resumed below250ms.

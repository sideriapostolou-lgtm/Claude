# Arena timing release blocker: read-only triage

Current storage repair remains frozen at local commit `0f7eba1`. No source/test edits or performance threshold/global garbage collector changes made by this triage.

Both failing arena tests and `kalshi_arena.py` are unchanged by storage repair. The tests construct `LiveSnapshot` but do not run Kalshi persistence checkpoints or Polydesk persistence logic.

The failures are CPU-speed/allocation sensitive rather than simple wall-clock scheduling flakes. The busy flush test measures `time.thread_time_ns`, requires median below 0.25ms and p99 below 0.5ms, and selects index198 of200 samples. A pure off-CPU scheduling pause cannot consume this timer. The backlog test has a fake venue clock, including nominal0.3s steps without real sleeps, but retains the actual4ms own-thread CPU encoding budget. Its retained event count therefore measures how much work this CPU can encode per bounded flush. Original-source failures discussed in this section retained events without dropping them; backlog is still a real unmet performance assertion.

Root full run:6312passed/2failed/22skipped. Busy median0.138121ms/p990.920656ms, no drops, no pending. Deep700event case retained5312events after70000inputs/100flushes, zero drops:646.88events encoded/flush average versus700needed. Root later full science run:6332passed/2failed/14skipped; busy p99~0.896ms; deep pending10660. These are not waived.

Root serial baseline/patch comparison is retained in `TIMING_COMPARISON.json` and four timing logs. Baseline first run passed, subsequent baseline failed; both patch runs failed. This demonstrates baseline sensitivity but does not establish exact performance equivalence or authorize treating checks as green.

## Bounded current-source profile

Artifacts: `profile_arena.py`, `arena-profile.log`, `arena-profile.json`, `arena-backlog.prof`, `arena-backlog-cprofile.log`. Only the two failing test nodes were executed. Diagnostic process-local wrappers recorded own-thread CPU per flush and ordinary GC callback times. Profiling adds allocation overhead, so these are diagnostic measurements, not a substitute passing test receipt. No GC settings changed.

Two-node profile:1failed/1passed in11.90s. Busy median0.132ms/p991.524ms/max24.548ms. The largest measured flush included a generation2 collection taking24.368ms; another1.515ms flush had no associated collection. Deep backlog passed this diagnostic run. Some deep flushes included large collections: generation2~34.4ms inside39.1ms; generation0~25.1ms inside40.3ms. These are real own-thread costs, not elapsed off-CPU waits.

Separate cProfile of only the existing deep test:100flushes, `_encode`0.412s cumulative,37280`book_wire` calls0.317s,74560`ladder_change` calls0.291s. Budget sensitivity under cProfile is expected because profiling consumes actual CPU. The ladder comparison dominates measured encoding cost.

## Historical scratch proposal — superseded by the final rejection below

Change only `ladder_change` common-prefix/common-suffix scanning. Current scans build count/map/compress/reversed iterator chains and compare identity for every level. A scratch candidate compares16level tuple blocks in C, then uses a short identity scan to locate exact remaining boundaries. It retains same-tuple identity early return and complete initial snapshot behavior. Book sequence/order/depth/fees and every event remain unchanged. For newly allocated Level objects equal in price/size, a block may omit redundant unchanged values; reconstructed values remain equal. This distinction needs explicit equivalence tests and independent review.

Scratch artifacts `arena-diff-benchmark.py` and `.json`:4000single-level delta pairs per depth,3own-thread timing runs per implementation, exact output equality checked for this workload. Median nanoseconds current→candidate:depth3 1173→575;depth25 2945→1682;depth111 3610→2704;depth168 5989→3849. Pure Python linear scan and tuple binary search were slower on deep books and are rejected. These scratch timing samples vary and are not production latency proof.

Historical proposed next step, not carried out: integration owner declares shared arena scope before source edits. If approved, implement only local diff optimization with insertion/deletion/equal-value/identity/different-length/random round-trip and event-order equivalence coverage; run the existing two nodes and relevant deterministic arena transport suite; then required full suite. Do not change test thresholds, budgets or global GC to obtain green. Even green source checks cannot recover the production full disk or establish state/current exposure/restart safety/profitability.

## Scratch candidate validation requested by root

No source edits. `arena-candidate.py` uses an AST-loaded process-local replacement for `ladder_change`. Separate reconstruction process passed3512cases covering empty/None/same identity/recreated equal values, insertion/deletion, unequal lengths, random edits, and boundaries15/16/17/31/32. Nine encodings differed only in redundant unchanged equal-value levels; reconstructed data matched. Retained output: `arena-candidate-equivalence.json`.

Two fresh, serial processes ran exactly the original two test nodes without profiling, GC callbacks, GC setting changes, budget changes or threshold changes:

- `arena-candidate-1.log`:2passed in11.83s. Busy median0.123ms,p990.446ms,max0.800ms; no drops/pending;200frames.
- `arena-candidate-2.log`:1failed/1passed in11.82s. Busy median0.113ms,p990.641ms,max0.646ms; no drops/pending. The unchanged0.5ms p99 assertion still failed.

Deep throughput passed both candidate runs. Central cost improved; the candidate does **not** reliably clear the busy p99 release blocker. These results do not authorize a green claim or threshold waiver. A further bounded stage-cost profile would be needed to explain residual excursions before proposing broader source changes.

Exact proposed scratch function (not applied to source):

```python
def blocks(sent, levels):
    if levels is sent:
        return None
    if sent is None:
        return (0, None, _levels(levels))
    size, old = len(levels), len(sent)
    limit = min(size, old)
    start = 0
    while start + 16 <= limit and levels[start:start + 16] == sent[start:start + 16]:
        start += 16
    while start < limit and levels[start] is sent[start]:
        start += 1
    end = 0
    while (end + 16 <= limit - start
           and levels[size - end - 16:size - end] == sent[old - end - 16:old - end]):
        end += 16
    while end < limit - start and levels[size - end - 1] is sent[old - end - 1]:
        end += 1
    return (start, old - end, _levels(levels[start:size - end]))
```

## Final exact-identity investigation and stop

Independent review rejected the value-equality block candidate because signed-zero/custom numeric equality can change the old delta representation. That candidate is **rejected**, despite ordinary value reconstruction checks. It was never applied to source.

Final bounded scratch investigation compared identity-only approaches. `all(map(is_, ...))` over16element slices was slower on deep ladders, so rejected. A cursor/length-hint identity-map approach had no reliable deep speed improvement and was rejected. A takewhile experiment failed immediately because `takewhile(None, ...)` is not a supported predicate; it was not tested against source or used further.

One credible remaining candidate used explicit `is` prefix/suffix loops when minimum ladder depth<=16, retaining the original count/map/compress scans for deeper ladders; it also omitted the redundant reverse scan when no suffix can remain. Scratch microbenchmarks showed small-depth benefit but no reliable deep improvement. `arena-identity-candidate.py` passed4550 exact-delta cases, with **zero representation differences**: start/stop boundaries and payload object references matched the original, including signed zero, NaN, infinity, raising custom numeric equality, recreated equal Levels, empty/unequal lengths and insertion/deletion/block boundaries.

Exactly one fresh process then ran both existing unchanged test nodes without profiling, GC callbacks, GC settings, budgets or threshold changes: **both failed in12.75s** (`arena-identity-candidate.log`). Busy median0.128ms,p991.070ms,max5.949ms, with no dropped or retained events in that busy test. The deep backlog test overflowed and reported11536 dropped events, a more severe capacity failure than the earlier retained-only backlog failures. This exact-semantics candidate does not resolve the release blockers. No repeated favorable reruns attempted; no source or test edits made.

Per root's bounded investigation instruction, stop here. Keep the storage source fix frozen and full-suite gate failed. Do not waive thresholds, change GC/budgets or claim the arena issue resolved. Production disk/current-state/restart safety remains separately blocked by unavailable authenticated access.

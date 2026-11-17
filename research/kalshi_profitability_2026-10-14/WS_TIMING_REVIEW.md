# EXEC-DELAY-001: exact WS timing patch review

## Findings and disposition

**No unresolved blocking defect found in the final four-file bundle `4b86d13b5f2efe33626dd3c6b876086500f9377d0e9ca2ee676a1edaa2b0e405`.** Accepted as bounded incident/periodic-sample observability, contingent on the integration owner's full required checks and release verification. This is not acceptance of a scheduling correction, proof of production causality, a freshness pass, or task completion.

Three findings were returned during review and corrected before this disposition:

1. **Incorrect yield-delay attribution.** The first patch recomputed prior `yield_resume_ms` after every empty-recv timeout from the same `yielded_at`. Idle 200 ms waits accumulated into a purported `sleep(0)` resumption delay. Final source consumes and clears `yielded_at` at the first post-yield loop entry. The regression sends a complete message, two 200 ms empty receives, then a stale frame; it confirms the previous yield metric remains zero while the fake clock advances 400 ms.
2. **Diagnostic log failure escaped observation isolation.** `_timing_report()` caught its first log failure but its fallback `log.info` could raise again, changing a healthy session or replacing the original stale-data exception. A read-only injected failure reproduced an escaping RuntimeError with two logging attempts. Final source separately suppresses fallback emission failure; the original application exception remains in flight.
3. **Initial failure regression was a false positive.** Its fault injection broke every INFO message, including the preexisting snapshot-waiting status, before the stale delta reached the new path. Independent reproduction showed the gap reason was RuntimeError, not the expected source-age rejection. Final test targets only the new timing log prefix, verifies four emission attempts (status/gap plus fallbacks), and asserts the original `orderbook_delta_network:age_s=3.500` warning. The test now reaches the behavior it claims to protect.

## Exact scope

Repository `/workspace/nightcrawler-next-evidence`, base HEAD `0fc4115616bd85de5caf9c6259828cdccccc5abb`; recorded pre-change application `c8e37e5504aad04da0521b3f95c17f86dac42899`. Review was read-only; no application edits, commits, deployment, production query, credential read, financial setting, order or account action by this reviewer. This report is written under `/workspace/shared` only. Integration owner `/root` owns all repository writes and release decisions.

The final bundle was independently computed from sorted relative path + NUL + exact bytes + NUL, including untracked new files:

```text
3490a45a97d711797824c6b679f8c9346773cea38922e9d7b43650ae8e63de42  src/nightcrawler/speeddesk_kalshi_ws.py
77989b80dcc8eb452d1fee658b37ecc5bbd1daa77427d6bb104b51c6ef6c1d8b  src/nightcrawler/speeddesk_ws_timing.py
d48649f038b3a8013c809ce36e64c21dfa8bf0e81c26d997052adcca25b0998a  tests/test_speeddesk_ws_timing.py
c6021902c717d31b38cf95dba066db3c6d0edab647d0c01bcb0256e14afffdce  tests/test_speeddesk_ws_timing_integration.py
bundle: 4b86d13b5f2efe33626dd3c6b876086500f9377d0e9ca2ee676a1edaa2b0e405
```

Earlier bundle `4a5bcc75e3f468e597fb70bc559a0eb7ed07b7e294f874a4d13a5338e1c16a62` was not accepted. Source changed during the iterative review; final disposition applies only to the exact final bundle above. Concurrent `docs/COORDINATION.md` edits are outside this code review.

## What was checked

**Native behavior and matching.** `TimingClientConnection.process_event()` calls the native base implementation first and then observes successful data-frame processing. Handshake/control events do not consume ordinals. FIN text/binary and the final continuation frame create one complete-message stamp; fragmentation state rejects unexplained metadata sequencing. `recv()` delegates to native receive and advances its success ordinal only after a successful return, with no intervening await. Native cancellation and errors consume no diagnostic ordinal. Concurrent complete readers and streaming disable timing claims instead of guessing correspondence; base receive behavior remains authoritative.

The bounded deque retains 256 stamps. Overflow advances a recorded dropped-through ordinal. Earlier receives are explicitly `overflow`, cannot consume a later stamp, and exact known correspondence recovers when the consumer catches up. An unexplained missing association permanently disables claims for that connection. Observer failures clear prior receipt validity, increment errors/unknown, and preserve native return values. Native accepted count stops after disable, as documented; successful complete receives continue being counted. No claim treats unknown/disabled rows as zero delay.

**Guard and callback preservation.** Source freshness validation, sequence checks, book/trade timestamp semantics, stale/future thresholds and parser behavior are unchanged. Guard wall time remains after JSON decode. Local receipt never replaces a provider stamp. Both outcomes and all callbacks of each complete message run before the existing `await asyncio.sleep(0)`, which remains the final loop statement. The actual controller, wake cadence, financial model and persistence remain untouched.

**Gap ordering.** `_session()` stores only allowlisted message-kind and integer timestamp context on `MarketDataGap`, then rethrows the original exception. The existing `run()` inner finally sets `connected=False` and calls the existing invalidation/status callback before `_flush_timing_gap()`. The work query and timing log run after invalidation and before awaiting socket close. The integration test checks both ordering properties. No new pending financial receipt or checkpoint is introduced.

**Diagnostic failure and data handling.** Reports include fixed field names, fixed kind categories, numeric timestamps/counters, receipt metadata and fixed WorkTrace outputs. Arbitrary frame text, headers, prices, credential material and exception strings are not copied into the diagnostic report. The transport logger remains disabled. Main and fallback report log failures are isolated in the final patch. Source/domain values that fail the existing integer predicate appear as null, so missing versus invalid is not distinguished by this version.

**CPU and clock scope.** Accepted-monotonic→native-received-monotonic measures time after the library processes the final data frame; it includes buffering/scheduling and is not socket, kernel or wire arrival. Apply and return marks use monotonic time; paired wall marks allow subsequent clock checks. Backwards/nonfinite observer clocks disable association rather than manufacture a usable age. The optional WorkTrace query runs only for a gap with a known receipt, uses the accepted→apply interval and at most eight detailed spans, and preserves WorkTrace's existing loss/omission/CPU-basis fields. It adds no async span and makes no nested CPU sum. Positive local overlap can establish some local contribution; absence cannot establish upstream/provider responsibility.

## Independent validation actually run

Runtime: Python 3.12.14, websockets **15.0.1**, `/workspace/shared/nightcrawler-venv/bin/python`. Final exact-bundle command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /workspace/shared/nightcrawler-venv/bin/python -m pytest -q tests/test_speeddesk_ws_timing.py tests/test_speeddesk_ws_timing_integration.py tests/test_speeddesk_feed_fairness.py tests/test_speeddesk_feed_fairness_independent.py tests/test_speeddesk_kalshi_ws.py
```

Result: **101 passed in 1.62 seconds, exit 0**. This includes the new twenty native observer tests, six integration tests, both existing fairness files and existing Kalshi WS checks. Final file hashes were independently checked before this run. Earlier review of the intermediate patch also ran 24 observer/integration tests; that result is not substituted for the final run.

Native tests cover burst ordering, mixed fragmented/control/binary messages, fragment timeout/cancellation, overflow exactness, observer faults, retained-data restrictions, concurrent-reader and streaming disable, invalid/backwards clocks, unexplained missing stamps, and base receive error preservation. Integration tests cover native receipt/log correspondence, both stale source domains, arbitrary-text exclusion, invalidation before reporting/close, idle-timeout attribution, and logger-failure preservation.

The implementation worker reports the twenty native tests also passing on websockets 13.1 and 14.2. This reviewer did not rerun those two environments. The plain default shell has websockets 16.0, outside the declared `<16` dependency range; it was not used for the final validation. Full repository tests, mypy, changed-file Ruff, secret scan, runtime overhead evidence and release verification belong to root. Root reported the earlier full-suite attempt was interrupted; it is not a passing run. A final full-suite rerun was in progress at this review, so this report does not certify that result.

## Explicit limitations and retained work

- Status reports occur at the first processed message and about every sixty seconds per connection; source-parser gaps add incident reports. No final totals are emitted for all normal market changes, transport failures or cancellations. This version supports incident attribution and periodic samples, not complete session endpoint accounting, all-message freshness coverage, or a no-drop publication claim.
- Known residence excludes delay before native final-frame processing, including kernel/TLS/event-loop dispatch and earlier fragment arrival. Small residence does not prove provider or network delay. Missing/invalid provider timestamp categories both become null in the diagnostic fields; the original gap reason retains its existing fixed classification.
- `previous_message.processing_ms` includes synchronous periodic diagnostic reporting when that report occurred. It is elapsed wall processing, not pure business CPU. Yield delay now excludes later empty receive waits. Last-message yield resumption is not reported if the loop exits before reentering.
- Per-section work counts/maxima do not establish actual controller cause. WorkTrace details may be omitted/evicted, quiet work is a separate lower bound, full-span CPU is not apportioned, and overlapping/nested populations cannot be added.
- No controller/checkpoint-reason counters or REST-fallback counters are added. Positive local-residence observations can justify a narrower next investigation; they do not choose a controller scheduling correction by themselves.

I read `/workspace/shared/controller-replay-report.md`: its bounded actual-controller experiment reports all 24 scenarios draining 500 messages without stale failures or burst checkpoints, with increased controller turns under yielding. It preserves the real 20 ms minimum and save gates. That report expressly excludes full practice-controller and active-order/history workloads and does not attribute production warnings. I did not reexecute that experiment or independently audit its full raw result JSON in this patch review. It reinforces why the original 12 ms Event surrogate cannot select the production fix.

EXEC-DELAY-001 remains open. Keep the 3 s source guard, 250 ms skew allowance, complete-message atomicity, cancellation/invalidation paths, reservation/uncertain-order state, loss/stop/resume history and money limits intact. Strategy comparison remains unstarted. Root must finish required checks, verify any authorized exact deployment and restart accounting, then obtain repeated bounded production evidence with these coverage limits stated.

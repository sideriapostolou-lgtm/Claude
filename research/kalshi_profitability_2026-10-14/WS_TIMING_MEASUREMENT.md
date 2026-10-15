# Locate the remaining stale-feed delay

Recorded October 14, 2026, 9:05 PM Pacific (October 15, 04:05 UTC).
EXEC-DELAY-001 remains open. This is a measurement release, not a strategy change
or a claim of profitability. It preserves the existing complete-message yields,
three-second source-age rejection, sequence rules, cancellations and financial state.

## Evidence before this release

The running application was still `c8e37e5504aad04da0521b3f95c17f86dac42899`.
The bounded 8:30–8:50 PM Pacific query retained 23 source-age warnings, two normal
market-set transitions and three REST trade-gap `ValueError`s. At 8:49:58 PM,
recorded cash was $37.9131 versus cumulative settled trading P&L **−$11.4183**.
Gross open cost was $8.41, reservation $1.35 and modeled risk $1.76. These are
dated status fields, not current balances or an export of raw stop anchors.
Effective caps and both stop latches were unchanged; cash is not trading profit.

The earlier synthetic worker proof is retained but does not reproduce the live
controller. The actual loop enforces a 20 ms minimum step, coalesces wake events,
and gates checkpoints. A new offline replay runs the actual `KalshiLiveDesk`
run/step/heartbeat/on_book paths, native WebSocket assembler and market-state
guard, with an empty fake account/in-memory ledger and no order authority.

All 24 scenarios completed 500 messages without stale rejection or a checkpoint
during the burst. With explicit synthetic 5 ms per-message callback CPU, yielding
allowed 72–83 actual controller cycles versus zero before yielding. The fake-account
branch completed eight thread-backed fake reads. Drain times were 2.5439–2.5549 s
without the boundary yield and 2.5681–2.5735 s with it. The largest observed age
in the 5.8 ms-load yielding cases was 2.983735 s, still below the unchanged guard.
This demonstrates scheduling differences, not production causality or checkpoint
amplification. Empty state, invented bursts and in-memory persistence omit production
history, disk cost, fills/cancels and the complete practice controller. Cycle wall
times include awaits and must not be added as synchronous CPU occupancy.

[Exact preparation evidence](ws_timing_preparation_evidence.zip),
[member manifest](ws_timing_preparation_manifest.json) and
[extracted facts](ws_timing_preparation_summary.json) retain originals, including
two failed pre-execution harness attempts. Archive SHA256
`a4785396a23f7d6e1657cc041941d68657ece5361668e56e8bcba0332be087b9`.

## What the diagnostic can establish

The documented native `create_connection` hook installs a `ClientConnection`
subclass. After the native parser accepts a complete data message, it retains
only an ordinal and two clock readings in a 256-stamp ring. After a successful
public `recv`, it matches the exact ordinal synchronously. Fragmentation and
control frames do not create extra message stamps. Timeout/cancellation consumes
no ordinal. Eviction is explicitly unknown; an unexplained mismatch, unsupported
reader, invalid clock or observer error disables claims rather than shifting stamps.
It never retains frame bodies, headers or keys in diagnostic state.

The measured residence includes native library buffering and dispatch until
`recv` returns. **It is a positive local lower bound, not socket/kernel ingress,
network round trip or an estimate of provider delay.** Short residence leaves
earlier local/kernel and provider/network time unresolved. Source and engine
timestamps remain authoritative for the unchanged guard; local receipt never
substitutes for either. Both original timestamp domains are recorded when valid.

`speeddesk_feed_kalshi_ws_timing` logs first-message/60-second samples and rejected
message context. On a rejection the existing invalidation/cancel callbacks execute
before the timing query/log and before awaiting connection close. The optional
work-overlap query preserves retention, omitted-detail and active-span limitations;
nested/overlapping wall/CPU populations must not be added. Previous-message wall
processing includes its diagnostic cost. Yield-resume time is consumed once,
so later idle receives do not inflate it. A broken diagnostic log sink is contained.

Counters/maxima are per connection, identified by a process-local session number.
There is no final session-total publication on all transport/cancel/market-transition
exits. These are bounded incident and periodic samples, not a complete freshness
coverage or all-message latency certificate. Missing diagnostics remain missing.
No live-controller counter, policy, persistence cadence or order behavior changed.

## Exact review and checks

The four-file path/NUL/content/NUL bundle is
`4b86d13b5f2efe33626dd3c6b876086500f9377d0e9ca2ee676a1edaa2b0e405`.
[Independent Astra review](WS_TIMING_REVIEW.md) accepted this exact bundle for the
limited diagnostic scope. It caught an idle-time measurement bug, a failing-log
fallback bug and a false-positive regression test; all were corrected before
acceptance. Root then repeated the target cases on websockets 13.1 and 14.2:
94 passed separately on each; the reviewer ran 101 on 15.0.1. These exact releases
were exercised, not every supported library version or the production socket.

Final full repository pytest passed: **5,555 passed, 14 existing skips**, 305.14 s,
captured exit zero. Mypy passes all 127 source files; Ruff passes all four changed
Python files. The exact reviewed source/test bundle remains unchanged. Credential
scan and release verification follow this preparation checkpoint. An earlier full
test process was stopped after source revisions (exit137) and is not a successful
check; its partial failures are retained rather than counted as final results.

## Prospective production evidence, frozen before release

After exact Railway SUCCESS, normal startup and unchanged compared financial
state, freeze the first two complete 15-minute windows strictly after the verified
startup time. Retain the restart-partial window separately, and include covering
status intervals plus a two-minute publication tail. Record the absolute window
times before collecting their results; do not replace unfavorable windows.

Save original bounded past-time query responses, source-age/gap and timing events,
real fills/fees/settlements, selected account traces, status counters and omissions.
Split any query hitting its row cap. Match rejection timing to source domain and
session; report missing/unknown/disabled/evicted stamps and publication gaps.
Preserve real/practice separation and every loss. Fees count once; already credited
matched pairs are not paid twice. A positive pair settlement does not prove edge.

For each available rejected-message stamp, report source age at apply, exact local
protocol residence, receive-return-to-apply, previous message/yield wall time and
retained synchronous-work overlap with its omissions. Only positive measured
local residence establishes that much local delay; do not assign the remainder to
the provider. If evidence does not support a specific correction, say so and keep
EXEC-DELAY-001 open. Any correction still needs new checks, independent exact
review, safe release and repeated active-window evidence. The frozen original/
inverse/no-trade comparison remains unstarted; TJR retains its authentic-data/cost
blocker, null historical P&L, no paper start and disabled live execution.

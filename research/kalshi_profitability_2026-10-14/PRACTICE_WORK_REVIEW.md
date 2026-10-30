# Remove measured processing overhead before judging strategies

2026-10-14, Codex. Baseline: `13bf55bdd1b594ab340630e0755affdf97c6fdf5`.
This is a performance investigation with synthetic inputs, not a profitable strategy or a live experiment.

## Why this is the next step

The live status at 15:24:02 UTC (08:24:02 AM PDT) reported 12 arena residents,
zero complete windows and 64 void windows, including 56 feed voids. Its cumulative
dropped input rose from 208,297 at 15:22 to 306,919 at 15:24. At 15:24:25,
account reconciliation last took 6,892.2 ms and maximum event-loop lag was 2,895.1 ms.
These observations identify unreliable processing and evidence, not a trading edge.

The later 15:37:49 UTC status still included a 1,337.5 ms loop-lag maximum and
2,677.7 ms step maximum. Fast median HTTP requests do not exclude long local pauses.
We cannot attribute every pause or dropped event to this change's two bottlenecks.

The prior completed UTC day's real ledger remains a **$11.0074 loss**: directional
P&L -$10.7508394 and locked-pair P&L -$0.2565606. The practice twin lost
$6.8833. Both scorecards certify only 6/96 windows complete. These losses must stay
visible; a faster loop does not demonstrate positive expected returns.

## Measured causes and proposed changes

1. The arena passed the same immutable deep book to all 12 residents. Each resident
   checked every level again. Cache validity and positive ask-price membership on
   each exact, immutable `Book`; retain timestamp checks and consumed-depth state
   separately for every desk. Mutable ladders, subclasses and nonstandard numeric
   objects are always revalidated. The cache adds no serialized/dataclass field and
   lives only as long as the book.
2. `advance()` and `evaluate()` already formed a settled-window set, but then scanned
   the full settlement history again for every unresolved window. Reuse the proven
   unsettled membership within that pass. Public `blocked()` keeps its settlement
   check, and each subsequent pass sees new settlements.

Only `src/nightcrawler/speeddesk_model.py` changes application behavior. No event
sampling, retention, fill rule, decision threshold, fee, money cap, setting, loss
history or real-order client changes. The original practice desk and live twin
share their process with live execution, so merging still restarts a live-money
service and requires the owner's outstanding deployment approval.

## Reproducible measurements

| Synthetic workload | Baseline median | Proposed median | Improvement |
| --- | ---: | ---: | ---: |
| Decode, receive and drain 3,000 deep books plus 30 prints, 12 residents each with one resting order | 2.2684 CPU seconds | 0.4910 CPU seconds | 4.62x |
| 300 book callbacks across original practice and live twin, 400 windows per desk: 173 closed, 226 unresolved expired, one active | 1,304.71 CPU ms | 103.65 CPU ms | 12.59x |

Each workload uses paired book depths of 111 and 168 levels. The arena retains all
3,030 events and all 12 resting orders, with zero coalescing, late events or degraded
windows in its frozen-clock test. The mixed-history distribution is an explicit
stress case: production's unresolved-history distribution has not been retrieved.
All-closed history hides much of the repeated-scan cost.

The callback benchmark creates fresh book objects before every timed pass. An
earlier 18.59x result reused warmed book objects across passes; independent review
caught that optimistic workload and the corrected cold-object result above replaces
it. Book construction itself remains outside timing in both implementations.

Run from the repository root with the normal development dependencies:

```bash
PYTHONPATH=src python research/kalshi_profitability_2026-10-14/arena_work_benchmark.py
PYTHONPATH=src:tests python research/kalshi_profitability_2026-10-14/practice_work_benchmark.py
```

Scripts use committed local baseline source and fakes, without network, credentials
or venue orders. The neighboring JSON files preserve the measured runs. Timing is
host-dependent and is not a test pass threshold. Neither benchmark measures actual
order latency, production feed completeness or profit.

## Behavior checks

Independent regression tests cover mutable inputs and subclasses, malformed books,
stale book rejection, independent consumed depth, unchanged dataclass representation,
cache lifetime and concurrent readers. One randomized check compares 1,000 updates
with the original uncached validation behavior. History tests check bounded scans,
new settlements between passes, settled-first public checks, and identical receipts
and state for takes, rests, partial fills, moving asks, cutoff and day stops.

The full suite, repository mypy and changed-file Ruff results are recorded with the
pull request and session WORKLOG entry; targeted tests do not substitute for them.

## Access limits and next evidence

Connected Railway exposes status, logs and aggregate metrics, but no runtime shell
or volume-file download. Normal CLI `whoami` and an explicitly scoped project /
production `status` both returned **Unauthorized. Please login with railway login**.
No credential value, variable listing, key registration or login was used to bypass
that failure. Consequently raw saved-record hashes, file coverage, exact `/data`
usage and a complete replay are not verified. Recorder reconnect logs are not proof
of persisted-row continuity. The sealed TEST dataset remains unopened.

After an approved merge in a safe merge minute, verify the exact deployed commit,
normal live status with existing limits and loss history, Polymarket startup, and
bounded logs for tracebacks. Compare window-by-window drop/late counter deltas and
coverage, plus loop/step and decision/ack latency; exclude the deployment's partial
window. Do not call the bottleneck resolved from a single low-lag snapshot.

The next evidence task is a bounded recorder-only report of persisted timestamps,
row counts, hashes, gaps and storage, through existing logs or authorized read-only
file access. Only complete, untouched holdout data can support comparing the fixed
strategy against predeclared alternatives. No candidate is promoted by this review,
and no cap increase, fresh loss budget or guaranteed profit is claimed.

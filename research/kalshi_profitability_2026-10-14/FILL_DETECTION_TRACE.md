# Fill detection: cancellation overlap and bounded attribution

October 14, 2026. Public owner-facing times below are Pacific daylight time.
This is evidence instrumentation, not a change to the strategy or order rules.

## What the old logs establish

The 11.793922-second fill-detection tail has a matching cancellation on the
**same order**, not an unrelated minute-level latency statistic. Source receipts
are preserved in `fill_detection_cancel_evidence.json` from deployment
`c049df06-b245-465b-969d-2c2b7317b5ed`:

- Fill `0725d5f3-9e89-8182-d950-bc3cf226435d`, UP five contracts at $0.43, maker.
- Venue fill time: **11:09:02.225172 AM PDT**.
- The reprice cancellation took **6.6673 seconds** from cancellation decision to
  acknowledgment. Its locally recorded completion was **11:09:11.580667 AM**,
  implying a start around **11:09:04.913 AM**. The venue returned a definite 404;
  the controller correctly retained its reservation until reconciliation.
- The fills-read wrapper returned at **11:09:14.019095 AM**. The receipt reached
  the Railway log at **11:09:14.669106 AM**.
- The earlier order-create acknowledgment also took **2.2549 seconds** from
  send to acknowledgment; that is not pure network RTT either.

This establishes a substantial cancellation interval overlapping the detection
delay. It does **not** prove which account read waited, when the fills HTTP
callback completed, or how much of the delay came from worker scheduling,
event-loop resumption, pagination, or cancellation. The prior minute's timing
summaries cannot resolve one individual event. No guessed cancellation change is
justified by these receipts.

## New observation path

`speeddesk_readtrace.py` records one reconciliation cycle at a time. Every
account-read span records monotonic offsets for submission, worker start,
completion of the entire client callback, coroutine resumption, and wrapper
return. It separately records time spent in cancellation checks while the read
was pending and after it completed. Existing page/row/byte counts are included.
The cycle retains the prior successful fills-wrapper return, full/recent mode,
remaining retry delay, new-fill IDs and registration times, and the existing
accounting checkpoint's start/completion where one occurs.

These are **callback timings**, not packet-arrival or HTTP-only measurements.
All read stages share one monotonic clock; `started_at` anchors the cycle to the
local wall clock. Venue fill timestamps retain their own clock uncertainty.
The trace does not introduce a private stream, account request, order, retry,
inventory authority, or cancellation-policy change.

The bounds are 12 detailed rows per rolling 60 seconds, 12 reads and 16 new fills
per cycle, and eight cancellation spans of at least one millisecond per read.
No-op checks remain counted in totals. Slow cycles (three seconds or longer),
failed cycles, and cycles with new actual fills qualify. Quiet and suppressed
cycles, omitted details, and publication-buffer drops are counted explicitly.
There is no historical restoration: these are session observations.

Publication waits for an already-selected accounting checkpoint. A separate
12-row buffer prevents timing receipts from advancing the ordinary checkpoint
schedule. Observer exceptions disable only this diagnostic. A failed trace
publication cannot prevent the selected checkpoint, real fill accounting, or
cancellation. Detailed rows stay out of the town's latest trading-activity list;
the existing live status line includes diagnostic counters and availability.

## Validation and next evidence

Fake tests cover separation of worker/cancel/return times, real fill identity,
previous-batch timing, bounded memory/logging with omission counters, paper mode,
every observer failure stage, worker-observer failure, unchanged cancellation,
and publication failure/cadence. No network or account credentials are used.

After the root completes repository checks, review and any approved release,
verify that the exact running commit emits `speeddesk_reconcile_trace`. Join
new fills by their IDs and cycle start timestamps, then identify where the long
tails occur before changing any execution behavior. Deployment and actual
production trace verification are not claimed by this implementation note.

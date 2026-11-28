# Next evidence: locate fill-detection delay

October 14, 2026. This is an observation plan, not a trading-rule change.

The first eight version-1 fill receipts had venue-to-controller detection delay
0.466 s minimum, 1.102 s median and 11.794 s maximum. They are a short observed
cohort, not a full-day latency estimate. Exact receipts are in
`fill_markouts_v1_release.json`.

The worst example was maker UP, five contracts at $0.43, fill
`0725d5f3-9e89-8182-d950-bc3cf226435d`:

- Venue timestamp: 2026-10-14 11:09:02.225172 AM PDT.
- Fills-read wrapper returned: 11:09:14.019095 AM PDT.
- Railway log timestamp: 11:09:14.669106 AM PDT.

The last approximately 650 ms is separate log-observation lag. The venue fill
timestamp has fractional precision, so an integer-timestamp fallback does not
explain this example. Source clocks still have uncertainty.

## What the current source establishes

`speeddesk_kalshi_ws.py` subscribes to public `orderbook_delta` and `trade` channels
over an authenticated market connection. It does not consume private fill
notifications. Actual owned fills come from REST through
`speeddesk_kalshi_client.py:KalshiClient.fills` and
`speeddesk_live.py:KalshiLiveDesk._reconcile_reads`.

Reconciliation can include a complete order-list read before paginated fills,
periodic full-history scans, HTTP cooldown/backoff, worker scheduling, event-loop
resumption and ownership attribution. These are candidate mechanisms, not proven
causes for the worst sample. The normal one-second schedule is measured after
previous reconciliation completion; actual request spacing can be longer.

The `_read` wrapper also awaits `_cancel_unsafe()` after the HTTP worker has
completed, after recording its read-duration statistic. `fills_batch_returned_at`
is captured after this wrapper returns, so it includes that cancellation work.
It must not be labeled an HTTP arrival or network-RTT timestamp.

## Bounded follow-up

1. Inspect already-recorded rejects/cancels/account timing surrounding
   11:09:02-11:09:15 AM PDT. Correlate the exact fill/order IDs; do not infer
   causality from unrelated minute medians.
2. If existing receipts cannot explain it, add an observation-only reconciliation
   identifier and timestamps for reconcile start, fills request start, worker
   completion, coroutine resume, final cancellation start/end, registration and
   persistence. Include previous successful fills-read time, full/recent mode,
   page counts and active backoff. Bound memory/log volume and isolate failures.
3. Only after attribution, evaluate a read-only private fill stream observer
   alongside authoritative REST reconciliation. Measure notification timing,
   reconnect gaps and deduplication. Do not change inventory/order authority as
   part of that measurement.

Meanwhile collect version-2 markouts over complete windows, preserving every
gap, loss and partial-depth result. They are isolated hypothetical selling
quotes, not executable portfolio returns. Entry/exit policy comparisons need a
separate frozen plan, delayed execution and shared inventory/depth accounting.
No existing sealed TEST has been opened, and no profitable strategy is claimed.

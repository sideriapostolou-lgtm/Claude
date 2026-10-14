# Buffered market messages can starve ready account work

Investigation recorded October14,2026 at4:25 PM Pacific (PDT, UTC−7). This is a
separate remaining contributor to EXEC-DELAY-001. No fairness correction has
been implemented or deployed in the repository at this checkpoint.

## Actual post-report-fix evidence

PR #55's scorecard correction is running on4b0ea40. The first five minutes of its
full4:15–4:30 PM window still include a selected5,131.435ms account-read resumption
gap. Fully contained quiet bins cover at least3,905.784ms of synchronous wall work
and2,465.387ms of whole-contained-span CPU;1,225.651ms remains unattributed or at
boundaries. This contradicts a claim that the broader delay was resolved.
The full-window collector is still running; its final evidence will be linked
when closed. These selected trace values are not population latency quantiles.

## A concrete scheduling mechanism

The Kalshi session repeatedly awaits `asyncio.wait_for(ws.recv(), timeout=0.2)`
and synchronously dispatches each decoded message. On the locally installed
Python3.12.14, positive-timeout `wait_for` can await that coroutine inline. The
installed websockets15.0.1 receiver returns inline when a complete message is
already buffered. An `await` expression therefore does not guarantee that another
ready task gets a turn.

The [offline proof archive](buffered_feed_fairness_proof.zip) preserves the exact
script, observations and inspected library excerpts. It exercises the actual
Kalshi `_session`, MarketState, websocket protocol parser, Connection.recv,
data_received and assembler. Every input is synthetic; sockets, clients, keys and
threads were prohibited. A waiting synthetic account future becomes ready during
the first book callback:

| Delivery | Callback where account becomes ready | Callback count when account resumes |
| --- | ---: | ---: |
| 16 buffered single-message frames | 1 | 32, after all16 messages |
| 8 frames, then8 in a later loop turn | 1 | 16, after first batch |
| 64 frames from one11,896-byte receive chunk | 1 | 128, after all64 messages |

Each message produces two book callbacks. No artificial CPU delay was added.
This proves a scheduling opportunity, not that this mechanism caused every
millisecond of the production gap or any particular financial loss.

The configured `max_queue=16` is a high-water mark, not a hard16-frame limit.
The actual assembler accepts all64 frames emitted from that one data_received
call, pauses reading once and resumes once. Its source documents the potential
for a single receive chunk to emit more frames than the high-water mark.

## One-statement counterfactual

The separate [counterfactual archive](buffered_feed_fairness_counterfactual.zip)
retains the executed script and complete observations. It constructs an ephemeral
copy of the actual session method; AST comparison verifies exactly one appended
`await asyncio.sleep(0)` after complete message dispatch. Repository source and
the original proof artifacts remain unchanged. With16 and64 alternating book/trade
messages, ready account work resumes after the first complete message (two
callbacks), versus16/64 complete messages (32/128 callbacks) in the baseline.
Full callback contents/order, statuses, final market state, subscriptions and
transport pause/resume counts match. The64-message receive chunk is15,558 bytes;
its content differs from the original book-only proof above.

This is fixed-clock scheduling evidence with a synthetic future, not a real
account request, wall-latency improvement or proof of production causality.
Cancellation and concurrent state changes remain release-test requirements.
The installed Polymarket SDK's public `_emit` calls handlers synchronously and
ignores their return values; an async handler would not fix that reader. No SDK
patch or monkeypatch was made.

## Candidate correction and boundaries

Test a cooperative yield after **all callbacks from one complete message**,
before receiving the next. Keep decoding, state application, status, both book
sides and trades together. Do not coalesce/drop/reorder input or yield between
the two sides of one book update. Existing exchange timestamps, freshness,
sequence-gap, cancellation and financial guards must remain.

This is the same logical boundary at which an empty recv already permits other
tasks to run; another buffered message is not already-applied market information.
Kalshi cancellation must continue through its existing finally, invalidating feeds
before awaiting socket close. A yield cannot bound one expensive callback or
guarantee account progress when another task monopolizes the loop.

The owned Coinbase receive loops have the same buffered-recv pattern. Process
every trade in one message with its original receipt time before yielding. The
Polymarket SDK has its own buffered receive task with synchronous handlers; its
subscription manager's0.5-second sleep does not make that reader fair. This is a
distinct surface requiring inspection, not permission to patch SDK internals or
change Polymarket trading code.

Required proof before release: ready-task progress, unchanged complete-message
callback/data order and final state, sequence/duplicate/timeout paths, and
cancellation invalidation/cleanup at the new boundary. Preserve exact candidate
source, independent review, full tests/mypy/changed-file lint and actual deployment
verification. Do not release while the current full-window capture is unfinished.

The separate [practice-report density probe](practice_report_profile_receipt.json)
did not reproduce the203ms cold production panel maximum. It identifies ordinary
serialization costs, not a proven explanation or an additional code fix. No
strategy comparison, TJR campaign, risk increase or profitable edge follows from
these observations. All real losses remain recorded.

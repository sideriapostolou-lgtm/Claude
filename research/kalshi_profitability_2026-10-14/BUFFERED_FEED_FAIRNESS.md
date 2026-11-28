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

## Closed post-scorecard window, 4:32 PM Pacific

[Original closed receipt](POST_GROUPING_FULL_WINDOW_1630_PDT.json), SHA256
`b58a299363dba8f2f3ce542485b06be59ca84f44d80f905eea4534e3ce4b994a`,
retains exact messages, query bounds, financial chronology and timing samples for
4:15–4:30 PM PDT (`KXBTC15M-26OCT141930-30`). Seven durable intents and seven
accepted order IDs produced two actual one-contract fills: Down47¢ and Up51¢,
zero fees. Venue settlement4:30:04.143958 PM paid$1: **+$0.02 locked/$0 directional**.
Seven cancellation records include five requested and two venue404 responses;
reservations remained until reconciliation. Cancellation records are not subtracted
from fills. Event/venue timestamps and delayed log observation remain separate.

Four selected cycles contain20 reads, two new-fill cycles and the5,131.435ms
resumption gap above.84 work details were omitted, without observed read/bin
retention loss. Fifteen status samples define14 fully contained intervals; none
hit the8192-sample cap. Maxima over those intervals are fills resume2,762.8ms,
orders resume2,188.7ms and loop lag2,054ms. The first straddling interval is
excluded, explaining why those maxima omit the larger selected first-minute gap.
These are different populations; minute medians/p90 are not pooled and trace
maxima are not presented as full-population quantiles.

At4:30:55 PM, the next-window status reports cash$35.2843, cumulative settled
P&L−$14.4571, zero gross filled cost/risk and$0.21 reserved in one new-window
order. That reservation is outside the measured window. Stops are false and
integrity clear. This is the existing strategy operating, not a new order by the
observer. Four bounded traceback/live-error queries through4:31 PM returned zero;
health/deployment remained unchanged. No complete raw-feed or late-event coverage
certification follows. The collector closed4:31:55 PM, later than its requested
4:31:30 deadline; queried source end remained4:31 PM and all jobs stopped.

This window does not prove profitability or establish a causal timing change.
The next candidate is now assigned for implementation and independent review;
source release still requires full checks and subsequent production verification.

The [independent audit](post_grouping_independent_audit.zip) reparsed all79 exact
original event-prefix messages and checked financial IDs, Decimal arithmetic,
selected timing spans and status populations. Its result hash is
`9ee859712d77a0b28a995b20138fa12ba374deec61f97a70419dd56d1acd7f52`.

## Candidate and final release gates, 4:42 PM Pacific

The production patch contains exactly two `await asyncio.sleep(0)` statements and
comments: after all Kalshi callbacks and after all Coinbase ticks for each complete
message. No SDK, Polydesk, financial rule, order, persistence or cadence code changed.
Final candidate four-file source/test bundle:
`afeb6aa444d39e4f118e3b82cb50ca47bcc2c2cc1173828d737a1121bc92b040`.

The first review missed a test portability assumption: Python3.11 positive-timeout
`wait_for` can already yield while3.12 runs a buffered recv inline. Root caught it.
Generic baseline observations now permit any complete-message boundary; candidate
observations still require the first complete message. A first-received event was initially proposed for ignored Coinbase messages,
but renewed independent review found Python3.11 can swallow cancellation while
`wait_for` resumes from an already-completed recv. Final tests instead signal from
the injected receipt clock **after** the recv wrapper returned, await that event
directly inside an asyncio timeout context, and cancel at the explicit complete-
message yield. Exactly one receipt and unchanged status/cancellation assertions
remain. Exact3.12 starvation observations remain unchanged in the original archives.
Python3.11 was not locally available; no execution on that version is claimed.

Two earlier full checks were intentionally stopped (pytest return−9) before test
corrections; neither is a pass. An intervening partial log has no successful
completion receipt and is preserved separately with unknown completion/source-
version coverage. The final serialized v2 run began4:43:47 PM PDT against frozen
corrected files; result pending. Renewed independent review accepts the exact
final bundle; root focused tests pass130/130 in1.99s and four-file Ruff passes.
No timing threshold or existing safety assertion was weakened. No release yet.

Status timing uses another endpoint as well as another population: worker-resume
status metrics end in the worker task's done callback; detailed read-resumption
marks end when the actual `_read` coroutine resumes. They are not interchangeable,
and their maxima do not form a contradiction or a comparable pooled distribution.

## Final checks closed, 4:49 PM Pacific

Final serialized run4:43:46–4:48:55 PM: **5,528 passed/14 existing skips in307.02s**,
pytest return0, mypy126 source files return0, Ruff all four changed Python files
return0. Source/test hashes stayed unchanged. [Check receipt](feed_fairness_check_receipt.json)
and [exact scripts/logs/archive](feed_fairness_checks_evidence.zip) retain interrupted
runs separately. Independent final review accepted bundle`afeb6aa…`; no source
changes followed. No Python3.11 execution claimed.

The [prospective two-window verification gate](FEED_FAIRNESS_VERIFICATION.md) was
frozen before candidate deployment/results. It uses a new coarse3-second recurrence
criterion with selection/publication/edge-interval coverage checks, not a subsecond
SLO or profitability criterion. First task remains open; second comparison unstarted.

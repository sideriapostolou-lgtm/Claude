# Next evidence, before another strategy claim

This is a follow-up design, not a deployed feature or a profitable rule. The fixed03:00–03:15UTC observation and its separate tail remain unchanged. No new financial control, order or runtime API call follows from this document.

## Compare the estimated queue with the venue

Official public OpenAPI was retrieved October16 **03:03:24.784198–03:03:26.045520UTC** / October15 **8:03:24–26PM PDT**, HTTP200, rawSHA256`a33d05aaa5deab319674407d543b5c0027d41adbf2c4f8a11dab708a0debd35a`. [Extract](QUEUE_API_DOCUMENTATION.json). It documents authenticated GETs:

- `/portfolio/orders/queue_positions`, filtered by `market_tickers` or `event_ticker`, with optional primary-subaccount selector.
- `/portfolio/orders/{order_id}/queue_position`.

`queue_position_fp` is a fixed-point count of preceding contracts, expressed as a two-decimal string. The batch description explicitly uses price-time priority. This documents an available read; no authenticated request, key permission, response timing, coverage or working client implementation was verified here. The task venv lacked PyYAML; the existing system PyYAML6.0.3 parsed the public document instead, with no installation. The full raw schema stays private; the public extract contains only relevant operations and referenced response schemas.

The first closed minute of the declared observation already has an exact real-fill/twin link with a recorded practice queue still positive at cancellation. That is a reason to obtain the venue's own queue measurement, not proof that this estimate equals the actual queue at venue execution, that a print was missing, or that practice should be filled from the account receipt.

A later implementation should sample only currently acknowledged, owned BTC15m resting IDs, with one bounded background batch at most once a second, one pending task, finite bounded results and explicit loss/omission/error counters. Keep it outside the send/cancel writer and shared execution-client lock. Record request-start and response-return intervals and raw fixed-point values; do not invent a server snapshot timestamp. Missing IDs,404,filled/cancelled races,429 and stale replies remain unknown, never zero queue. Back off on errors. Never output keys or read Railway variable values. Do not use this diagnostic as trading authority or silently alter practice fills.

Before release, independently test authentication-string reuse with throwaway keys, response parsing and ownership, malformed/fractional/missing values, slow/error/backoff/shutdown cases and exact baseline send/cancel/financial behavior. Measure added CPU, API and storage cost; full required checks and exact deployment/runtime verification still apply. Existing source freeze and financial controls are not waived.

## Measure new exposure after a completed pair

The [selected prior loss](PRIOR_LOSS.md) has a real new Down3 decision about30seconds after the first positive fully paired inventory was recorded. That observation motivates a comparison; it does not prove a general improvement or a cancellation that would have prevented every loss.

Across a future predeclared cohort, distinguish a newly submitted order after a controller-observed positive full pair from a bid already resting before that event, delayed fill reconciliation, and cancel/fill races. Include all later gains and losses, forgone profitable rounds, costs, fees, unknown coverage and partials. Use actual observed inventory and exposure, not acknowledgement-as-fill or venue timestamps treated as callback timestamps. Positive-pair rounding must not mistake floating-point noise for a real locked gain.

Only after causal fill/queue inputs are adequate, freeze a separate read-only/paper comparison of unchanged policy, a precisely specified alternative and no trade. Keep independent inventory, honest delays/queues, costs, losses and uncertainty. The old chosen loss is development evidence; never call it held out or tune a gate to its favorable counterfactual. No synthetic or retrospective truncation of later fills can establish executable profits. Existing FamilyA/toxicity/MNQ TEST remains sealed, and the separate reclaim confirmation remains consumed.

EXEC remains open. Recorder raw-volume verification, retention fit beforeOctober20/measured cost and operating access remain on their existing unfinished records; TJR last. No cap increase, stop/budget/resume reset, variable change, paid resource, storage resize or new live strategy is authorized by this design.

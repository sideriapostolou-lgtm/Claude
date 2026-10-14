# Prospective fill/exit diagnostic

Implementation date: October 14, 2026. This follows the owner's request for the next
highest-leverage step after the direction/exit review. It is measurement only.
No new signal, sell order, money limit, fee policy, stop reset or promotion is added.

## Question and fixed sampling rule

For each newly reconciled, owned Kalshi KXBTC15M buy fill, what selling bids are
visible **1, 5 and 30 seconds after the complete fills account read returns**?
The actual venue fill time and its age at discovery are retained. These are
detection-relative observations, not subsecond measurements after the exchange
match. Account pagination/reconciliation delay is not relabeled network latency.

At each horizon, take the first market-book callback at or after the
monotonic deadline. Local book receipt must be after the wall-time deadline;
local and exchange timestamps must both be no older than 0.5 seconds and not in
the future. Source timestamps may precede the local deadline by normal transit
time. Actual elapsed time, local receipt, source time and their ages are recorded.
A callback more than 0.5 seconds late is unusable. No callback by that allowance
becomes an explicit gap; the first bad callback is final, never replaced by a
later profitable quote. Only WebSocket evidence qualifies; REST samples are gaps.

These are fixed diagnostic horizons, not a newly selected exit strategy. We do
not pick the best of the three and call it an executable historical policy.

## Depth, costs and interpretation

- Use the held side's selling bids, best price first, across visible depth.
- Subtract the original sizes of all own same-side orders in this window at each
  price, including already cancelled/filled orders. A fresh buffered book may
  predate an account fill/cancel update; using only current reservations can count
  our recently removed bid as outside liquidity. This deliberately conservative
  bound may understate available exit depth. Excluded sizes and the policy are
  recorded. Foreign-owner activity or integrity errors
  make available external liquidity unknown and the sample unusable.
- Record hypothetical filled/unfilled quantity, price levels, gross proceeds,
  proportionally allocated actual entry fee, and a conservative exit-fee bound.
  Full-liquidation net is null unless all contracts fit. Partial net is labeled
  separately; empty or self-only bids cannot produce a full exit.
- Exit fees use the window's coefficient times q*p*(1-p), plus one fee-precision
  unit for every possible 0.01-contract fill partition. This is a conservative
  estimate, not an independently verified exact sell-fee quote. No rebates or
  favorable price improvements are assumed.
- A visible bid is not a guaranteed fill. This observation does not simulate a
  new order's transit delay, competition, queue position or cancel/fill races.
  The record explicitly says no exit latency was simulated and no order sent.
- Every fill is evaluated in isolation. Alternative horizons and reused quote
  depth must not be summed into strategy profit. Selling one leg of a matched
  pair can reopen directional exposure; a later exit simulator must model the
  entire inventory. Settlement comparisons join the existing actual fill and
  settlement receipts by window; settlement payout is never a selling bid.

The new records have mode=diagnostic and fill_source=real. Existing actual cash,
inventory, fees, settlement P&L and practice-twin ledgers remain authoritative and
unchanged. The diagnostic cannot submit, modify or cancel an order.

## Coverage and operational behavior

Receipt names: speeddesk_fill_observed, speeddesk_fill_markout,
speeddesk_fill_markout_gap and speeddesk_fill_markout_status. They are saved and
logged through the existing receipt path but excluded from the town's real
activity list. A separate fill_markouts status is included in the live panel;
its values cannot promote a strategy or alter financial accounting.

Feed invalidation, venue-term changes, settlement and shutdown close remaining
horizons with explicit reasons. A separate 100-ms expiry task runs while the
controller awaits account reads. It does not add network requests or a second
decision loop. Slow event-loop scheduling remains visible as lateness/missing data.

State is session-only: no old horizon is reconstructed after restart. Startup
reports earlier pending coverage unknown; old fills first discovered on restart
are labeled prior_session_fill. Original real fill/settlement records survive.
Diagnostics share the existing receipt durability: normal writes can be lost on
a host/power failure before durable sync, and no gap-free restart is claimed.

Memory bounds: 1,024 pending fills, bounded deduplication, 128 levels per side,
and at most 32 detailed measurements per callback. Exceeding bounds produces
explicit gaps. The ordinary callback checks whether anything is due in O(1).
Exceptions disable the optional diagnostic and record its error type; real
orders, cancellations, account reconciliation and risk accounting continue.

## Validation and next evidence

New fake-only tests cover sampling, stale/future/missing data, conservative costs,
own bids, partial depth, bounded work, deduplication, restart exclusions and
failure isolation. Integration tests prove real-fill-only admission, no extra
account requests, persistent distinct receipts, cancellation/sending after a
diagnostic fault, and expiry while an actual reconcile awaits its fills read.

A local synthetic CPU check (not Railway latency) measured one due fill at
0.080 ms median / 0.118 ms p95 across 200 runs. A 1,024-fill simultaneous burst
took 9.77 ms including explicit bound gaps, before receipt persistence/logging.
These measurements do not prove negligible deployed overhead; monitor runtime.

After deployment, verify the exact commit, unchanged risk/stop history and the
standalone startup status. Then verify one newly discovered real fill has all
three terminal horizon records (measurements or explicit gaps). Collect repeated
complete windows and report every observed fill, gap, detection delay and cost
assumption. No profitability conclusion is possible from the first samples.

The next research comparison is separately preregistered identical entries with
existing hold/lock versus one fixed exit policy using attainable delayed bids.
Test direction changes separately first. Existing original/inverted/no-trade
protocol and sealed TEST remain untouched. TJR historical/paper work remains
queued; this diagnostic does not clear all earlier Kalshi evidence prerequisites.

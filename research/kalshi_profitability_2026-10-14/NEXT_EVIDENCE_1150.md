# Entry quality and fill-detection follow-up

Observed October 14, 2026, 11:50 AM Pacific (PDT). This is a short diagnostic
cohort, not a profitable-strategy result or a complete daily report.

## What the new sample says

The version-2 observer on running commit `1769160` recorded 17 fills and all 51
terminal checkpoints between its restart and 11:45 AM PDT. There were 32 usable
full-depth hypothetical selling quotes and 19 explicit gaps. At one second after
the account-fill read returned, 13 of 14 usable quotes were negative after the
diagnostic's conservative cost estimate; one was positive. At five seconds the
split was eight negative and one positive. At thirty seconds it was four
negative and five positive.

These are different hypothetical exits on individual fills, often on both sides
of the same market. They cannot be added into portfolio profits, and the later
positive quotes do not prove an executable take-profit rule. The sampling delay,
missing quotes, source-clock uncertainty, conservative own-order-depth removal,
unknown sell transit and competing orders all remain limitations.

Venue-fill to complete account-read return was 0.157 seconds minimum, 0.960
seconds median and 8.158 seconds maximum for these 17 fills. This is not network
latency. The read wrapper can include cancellation work, worker scheduling and
event-loop delays. Exact receipts are in `fill_markouts_followup_1150.json`.

## Current account evidence

At 11:48:19 AM PDT, the real Kalshi panel was configured live, without a latched
daily/total stop or integrity error. Cash was $37.3037; open filled cost and
modeled at-risk amount were $2.05, with no resting reservation in that snapshot.
Recorded lifetime settled trading P&L was -$10.3877 and current UTC-day settled
P&L was -$0.4456. The latter split was +$3.164759 locked and -$3.610359 directional.
Cash is not trading profit. Existing losses and the current resume-budget history
were not reset. Current observed caps remain $10/window, $20 open, $6 day,
$10 total, clip five; this session did not raise them.

The full-window/day scorecard explicitly remains incomplete. These are observed
ledger totals, not independently certified whole-account or full-day returns.
`account_timing_followup_1148.json` preserves the exact snapshot and limitations.

## Highest-value action

Investigate why fills become known late before selecting a new exit rule. One
exact earlier 11.794-second detection tail overlaps a 6.667-second cancellation
of the same order. That overlap is evidence to trace, not proof that the whole
delay belongs to the exchange or cancellation. Join each reconciliation's
request, worker, loop-resume, cleanup, fill-registration and persistence stages.
Keep the diagnostic bounded and separate from accounting and trading authority.

After that attribution, preregister one entry-quality or exit comparison on
complete synchronized observations. Preserve missing data, use attainable
prices after delay and fees, and account for both sides together. Do not reverse
signals or add take-profit rules based on this small descriptive sample.

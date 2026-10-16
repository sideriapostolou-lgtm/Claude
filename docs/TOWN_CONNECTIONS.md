# What the town's numbers and movement mean

The town is a read-only view of the running business. `/` and `/world` show the
town; `/summary` shows the same projection without 3D. The only menu choices are
Money, Team and Help. Both pages read the authenticated `GET /api/page`; neither
places orders, changes settings or requests a venue account directly.

The foreground is Kalshi: cash, Pacific-day bot profit, real activity, safeguards
and daily garden growth. Polymarket remains live at the owner’s explicit request;
its account stays separate in secondary Money details. Practice and observation
services continue behind the scenes and remain available in their detail panels.
This focus is a display choice, never a trading-mode switch.

## Real money

| Shown in the town | Saved source and meaning | Time and limits |
| --- | --- | --- |
| Polymarket available cash | `money.polymarket.real.cash_usd`: the existing spendable balance, reduced to buying power when that is lower than reported cash. This is shared account cash, including the owner's activity. | `cash_at` is its own balance-read time. Cash is not profit. |
| Polymarket account bets/value | `venue_open` and `value_usd`: the existing venue account aggregate, including the owner's bets. | `venue_at` is its own account-position check. It does not verify each retained bot row. |
| Polymarket bot profit today | `real.today_pacific`: retained real bot results reconciled against the recorded UTC day books, filtered to the current Pacific calendar day. | Midnight in `America/Los_Angeles`, including daylight-saving changes. Source time is the last completed desk poll. Owner bets, deposits and practice are excluded. |
| Kalshi cash, mode and exposure | `money.speeddesk.kalshi_live`: the existing companion panel. Available real orders require its active/authenticated/configuration checks. Exposure includes confirmed buys and orders whose reservation has not been released. | The panel and cash each have their own timestamp, with a 60-second freshness requirement. Returning to paper does not close filled bets. |
| Kalshi bot profit today, Pacific | `money.connections.kalshi.today_pacific`: the full persisted real-fill settlement book, validated before display lists are shortened. | The same Pacific day as Polymarket. Settled results use actual fill fees; fees are not subtracted again. |
| Kalshi bot result, UTC | `money.speeddesk.kalshi_live.today`: the existing companion UTC day result. | Its date must match the current UTC day. It remains separate from the Pacific result and is never added to it. |

`money.connections` reads only `polydesk/state.json` and
`speeddesk/kalshi_live/state.json` below the configured data directory. It reads
bounded files without rewriting them or creating any trading client. The
Polymarket owner classification is applied to a private copy, matching the
existing reader. Kalshi restoration validates the full saved fills, gross
inventory and settlement totals before computing its day result.

Connection details include positions, open or uncertain orders, original event
times, fee sources and any accounting issues. The Polymarket rows are **tracked
bot/owner records**, not a fresh itemized venue snapshot. Kalshi positions are
**gross unsettled real fills**, including both YES and NO, not a net account
position query. A recent Kalshi checkpoint is not proof of a successful account
reconciliation: that reconciliation timestamp and snapshot are not persisted by
the current source.

Ended Kalshi windows that lack a reconciled settlement stay visible as old fill
records, with a warning if the owner also traded that window. They are not labeled
as current account bets. Gross recorded cost alone cannot establish that real
positions remain open. The page never hides unresolved quantities to force the
saved rows to agree with a zero account-position count.

Polymarket fees in these tracked records are estimates; Kalshi fill fees are
actual. Small positive fees retain extra decimals instead of appearing as zero.
The API bounds each venue list to 50 rows after validating the full source. The
summary shows at most eight positions and eight orders per venue, plus twelve
recent events. Truncated lists are labeled and never used to total account money.

The current event producer emits **bot events only**. Owner bets remain visible
in shared account totals and labeled tracked positions; this is not a complete
history of the owner's fills or cash-outs. The browser keeps owner/bot scope
separate if an owner event is supplied in the future.

## Source freshness and missing reports

The page heartbeat must be no more than 60 seconds old for activity or growth to
count as current. That heartbeat does not refresh an account or worker timestamp.
Polymarket connection records use a 600-second display freshness limit; the desk
normally polls every 90 seconds. Kalshi connection records use 60 seconds.
An incomplete source cannot qualify current activity or town growth.

An accounting mismatch is separate from an old report: a recently updated report
can still have incomplete money records. Rook flags Kalshi records for review;
Polymarket warnings stay with its secondary account details.
The Pacific-day API includes at most two UTC-day aggregate reconciliation rows
(record counts and sums); a mismatch still leaves profit unknown. Those sums are
diagnostics, not an alternative profit figure. The town states the missing-profit
reason explicitly rather than suggesting another browser poll will resolve it.

Kalshi's live mode can mean new bets are enabled or only completing existing
Up/Down pairs is allowed. The town preserves that distinction, including the
desk's accounting-stop/reset explanation. Limits are reported as the current
new-bet budgets and loss stops. The existing pair-completion rule may spend beyond
those budgets to reduce an existing position's possible loss; no display change
enables that rule or changes its checks. Reserved cash is distinct from possible
loss: new-bet reservations count toward risk, while pair-completion reservations
are excluded by the existing risk model. Cash time, desk-report time and account
reconciliation time are never substituted for one another; an unrecorded account
check remains unknown.

Old figures may remain visible with their age and an explicit warning. A missing
report, malformed amount, unknown fee or missing current-day book is shown as
unknown, not as zero. A new Pacific day cannot reuse yesterday's result.

## Practice and research

These services appear in the observatory and summary. They never contribute to
real cash, real profit or garden upgrades.

| Service | API source | Displayed count and source time |
| --- | --- | --- |
| Bitcoin lab | `money.speeddesk` | Practice fills in its matching UTC day. The separate `kalshi_live` block is not used for this count. Report freshness: 60 seconds. |
| Bot research | `skipwatch` | Public wallet fills recorded; no orders. Report freshness: 60 seconds. |
| Weather lab | `weatherwatch` | Active watched markets; no orders. Report freshness: 120 seconds. |
| Crypto trend lab | `money.trend` | Practice positions in BTC, ETH and SOL. Timestamp is the **booked daily UTC close**, not a worker heartbeat; allow 25 hours, with the producer's behind-book warning shown. |
| Strategy arena | `money.arena` | Practice strategy population. Own report freshness: 180 seconds. |
| Marco's NFL picks | `money.marco` | Settled practice picks from its record, not the shorter visible pick list. Own report freshness: 600 seconds. |
| Hockey picks | `money.nhl` | Settled practice picks from its separate NHL record. Own report freshness: 600 seconds. |

A service without its own timestamp does not establish a zero count or claim to
be running. Shared characters can represent multiple services; the service rows
keep those records separate.

## Scene behavior

Characters represent roles such as monitoring, risk checks, order status and
recordkeeping. They are a visualization of saved work and venue receipts, not
additional trading agents. An order submission is not a fill, and a fill is not
profit. Recent qualified real Kalshi bot events can animate work; an old, incomplete,
Polymarket, owner or practice event cannot pretend to be a new bot transaction.

An order's latest reconciliation timestamp is not its cancellation time. The
current saved source does not retain an immutable terminal-cancellation time,
so the town no longer fabricates new cancellation events from repeated account
checks. Actual cancellation-request receipts remain labeled as requests and do
not trigger town movement or confirm that reserved cash was released.

Garden levels use Kalshi’s **recorded** bot profit since midnight Pacific
only when its source is complete, fresh and covers the current Pacific date.
Thresholds are $0.01, $0.25, $1, $5 and $10. Losses or corrections can remove a
garden, and Pacific midnight resets the daily calculation. These are decorations,
not purchased assets or account equity. Deposits and owner/practice results do
not unlock them. If the Kalshi book is unavailable, growth waits; Polymarket
never substitutes for it, and an unrelated Polymarket gap cannot stop Kalshi growth.

## Current accounting limits

The town faithfully shows the saved books; it does not repair their trading
accounting. Existing Polymarket limitations include zero-profit app cash-outs
being skipped by the sale booker and late partial-sale corrections potentially
replacing an already recorded settlement incorrectly. Cash-outs and later
corrections can retain the original result timestamp. A Pacific-day book that
reconciles proves coverage of **recorded results**, not all venue activity.

### Polymarket history check, 2026-10-13 05:20 UTC

The saved list retained 200 results across practice, owner and bot activity.
For October 12 UTC, its 15 retained bot results summed to **+$1.796224428**;
the durable day book held 23 results totaling **+$3.352786376**. All 23
settlement receipts matched that day-book count and sum. The eight absent rows
had receipts between 00:30 and 06:31 UTC, totaling **+$1.556561948**, with
matching prior bot-fill receipts and no matching owner or sale-correction
receipts. All eight receipts preceded midnight Pacific at 07:00 UTC.

This explains the retention gap, but **+$1.796224428 is a diagnostic retained
sum, not a verified Pacific-day total**. Receipts record append time; results
use poll-start booking time. The first missing result has no retained booking
anchor proving its original UTC day. A buy and settlement can share a poll,
so a fill receipt is not automatically a lower bound on booking time.

The complete history also lacks original ownership evidence for some old
results. The day books hold 129 results, while 131 settlement receipts remain.
Applying two traceable sale corrections and excluding two apparent historical
owner results makes the totals agree, but owner migration emitted no receipt
identifying its removals, and the missing rows' original rule and entry time
are unavailable. Matching arithmetic alone does not verify those exclusions.

No recovery code, reconstructed booking timestamps or trading-book changes
were made. Polymarket Pacific profit stays unknown until its source coverage
is verified. The current Kalshi-only gardens do not depend on this Polymarket book. Future display work must not promote these
partial sums, inferred owner exclusions or receipt timestamps into verified
profit, new settlement events or earned town growth.

Those execution issues need a separate authorized fix with accounting tests.
This UI work changes no order rules, caps, live switches or protected financial
execution files. To stop new real orders, set both `POLYDESK_MODE=paper` and
`SPEEDDESK_KALSHI_MODE=paper` on Railway, then verify both desks and cancellation
of Kalshi's resting orders. Already filled bets remain exposed until settlement.

## Futuristic workstations and workflow

The existing tycoon town keeps its buildings, six cast members and navigation.
Each original worker home now has an open holographic console. The cyan ground
connections from Voss to Rook, Jet and Mote are static role wiring, not evidence
that a transaction or an AI call happened. Console status indicators use the same
current crew projection as the phone dock; reconnecting or missing reports show
unknown. No screen chart, typing loop or moving data packet invents activity.

The dock's four workstation shortcuts show Voss's BTC desk, Rook's safeguards,
Jet's orders and Mote's records. Pip and Nyx remain background desks. The separate
“Order → Fill → Settlement” legend names receipt types; it is not a progress bar
for one transaction. Only the existing qualified real-event gates move the cast.
A recent fill can mark Jet and Mote recently active; an order marks Jet, a
settlement marks Mote, and a rejection marks Jet and Rook. A generic receipt no
longer declares every foreground worker busy. Voss reports the desk state without
claiming an unrecorded decision. Selected desks retain their current explanation
and show their own last qualified receipt when one exists. None of this grants
browser access, task execution or additional trading authority.

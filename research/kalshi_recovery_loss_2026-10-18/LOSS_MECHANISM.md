# Actual-fill mechanism assessment

Offline historical diagnosis prepared October18 PDT / October19 UTC, at repository
base `f0ce4f8c02692bcfc9ad7071080c4c1deafed098`. This uses previously published
actual Kalshi receipts only. It makes no production, rule, cap, resume or funding
change and opens no Family A recorder data or sealed TEST. These observations
have already been examined and are **development/diagnostic data**, never an
untouched test. Runtime/storage recovery is a separate acceptance item.

The new calculation strengthens the case for testing the first fill's value:
**the first executed order in each of all55 October16UTC settled traded windows
contributed −$16.3428 at the actual official outcomes, after its actual fees.
All other actual fills contributed +$8.1730. Together they reproduce −$8.1698.**

This is a cash-flow decomposition of fixed receipts, not a backtest of a
no-hedge strategy. It keeps every partial fill belonging to the earliest
venue-filled order in that first order; it does not arbitrarily select the first
receipt's size. Removing hedges or orders could change later fills, risk and
admission. The positive second component is not an independently executable
strategy. It does show why simply removing costly-looking hedge purchases is
not supported by the observed money.

## Independent reconstruction

Run from any directory:

```bash
python /workspace/nightcrawler-daily/research/kalshi_recovery_loss_2026-10-18/analyze_loss_mechanism.py
```

[LOSS_MECHANISM.json](LOSS_MECHANISM.json) records the original input SHA-256
hashes,577 assertions and every window's first-order fill IDs, quantity,
settlement payoff, remaining actual-fill contribution, opposite-fill delay and
available predecision intent. Every settlement is independently checked against
actual shares, purchase cost, fees, payout and locked/directional arithmetic.
The script has no network dependencies. Changed-file Ruff passes.

| Complete observed settlement-day population | Value |
| --- | ---: |
| Day fill receipts, including next-day carry | 149 |
| Settled traded / empty windows | 55 / 5 |
| Locked accounting component | +$4.94228322 |
| Directional accounting component | −$13.11208322 |
| Actual net | **−$8.1698** |
| First executed orders, actual quantity and actual fees | −$16.3428 |
| All other executed orders, actual quantity and actual fees | +$8.1730 |
| First-side winning / losing official outcomes | 24 / 31 |
| Sum of first-order per-contract payoff, equal weight per window | −$2.8100 |

The last row divides each first order's realized payoff by its actual filled
quantity before summing. Its mean is−5.1091c per window/contract. It is a
normalization of historical receipts, not an attainable fixed-size policy,
statistical proof of adverse selection or a new monetary total. The first orders
were maker fills with no fees in this cohort; all other actual fees remain in
the other-fill term. Neither quantity weighting nor equal-window weighting gives
evidence of a positive standalone first-leg return in these receipts.

The terminal balanced group has44 traded windows and+$3.2030; the11 unequal
windows total−$11.3728. **Terminal balance uses future information.** Selecting
the balanced group would discard the mechanism's failures and cannot serve as
an entry gate or replace the complete observed loss. Balanced windows include
losers, including the worst−$2.8509 window.

The carry window `KXBTC15M-26OCT162000-00` has two October16 fills and settles
+$0.0127 on October17UTC. It stays excluded from October16 settlement-day P&L.
The completed PR75 new-entry cohort separately includes that carry:11 traded
windows, ten gains totaling+$0.1544 and one−$0.4218 loss, net−$0.2674. This
reconciles the prior report without assigning the carry's profit to PR76.

## What the execution evidence can falsify

Exact earlier loss-oriented captures permit only **five of55** first orders to
join to their durable predecision fair/price. Every join precedes the actual fill;
quoted model edges range3.5122–5.0919c. All five first sides lose at settlement,
but the captures were chosen around losses. They are **not** an unbiased model
calibration sample and do not justify a price, fair, latency or side threshold.
The other50 remain missing, with no reconstructed fair value.

In PR75's losing target `KXBTC15M-26OCT161815-15`, the first Down fill was49c.
The first ordinary opposite-side intent followed2.425983seconds later, including
1.439595seconds between venue fill and complete paginated fill-batch return.
There were39 ordinary opposite maker intents: one49c,38 at50c; none filled.
The actual late Up hedge at92.7c plus0.48c fee reduced the actual first-side
loss from49c to42.18c. The end result does not establish a profitable earlier
executable hedge.

Two diagnostic GET samples even reported `queue_position_fp=0.00` for the
unfilled49c Up hedge. They have no server snapshot timestamp. Zero queue ahead
does not prove that a matching seller arrived, that the order stayed ahead until
a trade, or that a canceled order would have filled. This is a specific saved
counterexample to treating queue zero as a fill receipt. It is not proof that
the venue queue API is wrong.

All three target first-fill1/5/30-second markouts are gaps: `book_stale`,
`observation_late`, `book_stale`. The book level counts in those gap receipts
are not full price/quantity books and cannot supply replacement hedge quotes.
No valid earlier exit, no missing markout and no cancellation gain is imputed.

There is also a structural failure in treating entry-time opposite depth as
reserved inventory. If our starter bid is`p`, the opposite ask is`q`, and pair
fees are`f >= 0`, requiring`p + q + f <= .99` implies that the same-side bid
providing that ask is`1-q >= p+.01+f`: it has strictly better price priority
than our starter. It may trade or withdraw before our lower bid fills. A displayed
cheap second leg therefore cannot guarantee completion after our first fill.
This identifies a falsifiable liquidity-survival mechanism; it does not prove
the selected loss's exact queue history.

## Strongest next mechanism test

**Test whether quoted first-leg edge survives conditioning on an actual first
fill, and whether any apparent paired gain covers the full failed-completion
tail.** Repeat the existing EXEC-DELAY-001 work with a frozen observation protocol,
not a new live starter policy. PR76 reduction-only admission stays in force.

First obtain a read-only, integrity-checked export of the existing bot's durable
order journal, its real fill/settlement history, cancel acknowledgments and
eligible non-TEST book/queue evidence after storage recovery. Export only the
known historical development interval and explicitly enumerate missing rows.
This is necessary to replace the selected5/55 fair joins with a complete
predecision population; the money-only table cannot test a conditional entry
rule. The existing recorder's separate future Family A TEST stays unopened.

Freeze these endpoints before a fresh observation interval is opened:

1. **First-fill calibration:** log every eligible starter decision, its model
   version/fair, side, limit, intended quantity, fee schedule, actual decision
   clock and input ages; retain every nonfill/cancel/error as well as fills.
   For observed actual first-order fills, compare the frozen predicted
   after-fee edge with official-outcome cash flow and report the calibration
   residual. Estimate uncertainty in complete market windows, not individual
   reprices. No conditioning on eventual balance, eventual profit or whether a
   markout happened to be available.
2. **Completion survival:** at decision and at the first fill's venue clock,
   preserve both-side level prices/quantities, own orders and receive/source
   clocks; retain fill-detection, cancel request/ack and next hedge-send clocks.
   Count each first-fill exposure, completion cost including fees, failed pair,
   partial and terminal loss. Hypothetical immediate fills require verified
   depth through the declared dispatch interval, own-depth removal and validated
   queue/trade handling; absent evidence is unknown, never success.
3. **Primary economic endpoint:** net after all fees over **all** predeclared
   opportunities/windows, keeping losing tails, empty/no-fill windows and
   forgone paired wins. Publish coverage alongside the result. A gate uses only
   fields actually available at that decision. Develop any gate on the exposed
   history, then freeze its rule, source/settings, fixed-size accounting,
   dependence-aware uncertainty method, observation duration/sample minimum and
   missing-data rule before independent future validation. No threshold search
   or stopping as soon as an attractive run appears.

With new real starters disabled, public/shadow observation cannot manufacture
actual own-order queue fills or establish a candidate's real profit. Its role
is to reject impossible completion assumptions and evaluate the frozen signal
under conservative fill bounds. If execution fidelity remains unvalidated,
candidate profitability remains **insufficient evidence**, even if a paper
point estimate is positive. No real-order experiment or resumption is authorized
by this report; a future real-money proposal would need its own bounded authority.

The current evidence supports preserving containment and targeting conditional
first-fill value. It does not identify a profitable gate or justify increasing
size, relaxing a pair cap, removing protection or restarting first legs.

## Limits retained

Native money queries are unsaturated and every returned settlement reconciles;
this is not independent provider/raw-volume completeness certification. The day
mixes app versions, caps and pauses, so no time slice supplies a causal before/
after estimate. Current venue exposure after the storage failure is outside this
offline task and remains subject to fresh authenticated reconciliation.

Files written by this worker are limited to this report,
`analyze_loss_mechanism.py` and `LOSS_MECHANISM.json`. Parent integration owns
operating records and any release. No code/deploy, financial change, network
research, simulated fill substitution or sealed-data access was performed.

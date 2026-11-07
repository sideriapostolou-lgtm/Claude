# Real-loss audit and the “fade ourselves” idea

2026-10-14. Research only. No live settings, caps, orders, or application code changed by this audit.
The two inputs are the already-published October 13 order and settlement CSVs. No held-out TEST data
was opened and no rule was fitted. Today's post-restart trading is a different cohort.

## Result

**The loss is real, and the evidence points to adverse selection: our resting bids often filled on
the side that subsequently lost. It does not establish a profitable opposite strategy.**

Independent reconstruction from the 750 order-intent rows reconciles all 29 windows, including
per-side filled quantities, cost, fees, payout and net P&L. The exported quantity artifact
`4.999999999999999` differs from five by only 1e-15; no monetary discrepancy was found. Values in
the source settlement attribution are rounded per window, so summing their locked/directional
columns differs by a fraction of a cent from recomputing those allocations from orders.

| October 13, 16:00–23:15 UTC | Reconstructed result |
|---|---:|
| Purchase cost, excluding fees | $269.2890 |
| Settlement payout | $258.0000 |
| Fees | $0.6264 |
| Net P&L | **−$11.9154** |
| Mean per window | −$0.4109 |
| Worst window | −$2.9792 |
| Winning / losing / flat windows | 10 / 18 / 1 |
| Resting order intents / orders with fills | 727 / 123 |
| Lock order intents / orders with fills | 23 / 22 |
| Filled contracts: resting / lock | 447 / 84 |
| Windows with both sides filled | 28 / 29 |
| Windows unbalanced before locks / heavy side lost | 27 / 23 |

These are intent counts, not 750 confirmed venue orders. The prior raw-log audit identified eight
intents never sent and three venue rejections; the CSV does not include every send/cancel status.
The sample contains several earlier releases and larger pre-cap clips. It is not a clean trial of
today's five-contract policy, new stop rules, speed work, or disabled optional pull guard.

Average-cost attribution of the actual fills:

| Component | Gross P&L |
|---|---:|
| Pairs completed entirely by resting fills | +$10.3173 |
| Additional pairs completed by lock fills | −$17.0079 |
| Final unmatched contracts | −$4.5984 |
| Fees, subtracted separately | −$0.6264 |

“Lock pairs lost money” does **not** mean removing locks improves the strategy. The actual lock
legs themselves contributed **+$0.8246** versus allowing the same recorded maker legs to settle
alone; those maker legs alone total −$12.7400. This is fixed-fill accounting, not a replay of a
policy without locks: changing execution can change later cash, inventory, risk and decisions.
No losing window in this sample would have become profitable merely by eliminating its fees.

Twenty-three of 27 pre-lock heavy sides lost. This is a descriptive warning, not a validated
directional predictor. The interval was selected while investigating losses, windows are
dependent, and “which side filled heavily” is only known after those fills. The earlier report's
coin-flip probability is not an out-of-sample significance claim.

## Why negating the P&L is not a reverse backtest

For one binary contract with outcome y and purchase price p, the gross original payoff is y−p.
Buying its opposite at exactly 1−p produces −(y−p). That is an accounting identity **conditional
on obtaining that opposite price and size**. It does not demonstrate those trades were available
at the time a replacement policy could have decided and reached the exchange.

The historical rows lack:

- Both sides' executable bid/ask ladders and sizes at each decision, receipt, and simulated arrival.
- Complete cancel/send/ack times and queue position; aggregate fills only have first-fill time.
- The full contemporaneous Bitcoin ticks, fair-value input state, and settlement-index timing.
- Independent reversed-policy inventory, cash, fees, reservations, stops and future decisions.
- Public opportunities the original bot declined, including periods without an actual fill.

Choosing the opposite only at the original's subsequently successful fill timestamps conditions
on future execution. Our original resting bid may itself supply the opposing ask, so removing it
can also remove the alleged counterfactual liquidity. A replacement taking the opposite pays a
spread and possibly taker fees; a replacement posting the opposite joins a different queue and
need not fill. Equal contracts and equal dollars are different experiments.

Consequently, the generated JSON deliberately reports executable inverse P&L as **null**. It
does not turn −$11.9154 into a made-up positive result.

## What to change next

**Highest-value immediate engineering work: make cancellation and account reconciliation
predictable, preserving the existing risk checks, then measure execution with a frozen forward
comparison.** The repository's 14:07 UTC coordination receipt records a 9.922-second cancellation
and slow account reads after the restart. The current controller awaits `_reconcile()` before
its next cancellation scan. A strategy trying to react inside a second cannot rely on that
behavior. Faster execution is necessary to evaluate this idea fairly, but cannot by itself
create positive expected returns.

A separate research candidate is a strictly balancing bid clipped to the affordable pair price:
currently `_decide()` computes `fair − MAKE_EDGE`, and the risk model rejects an over-cap price
instead of selecting a cheaper compliant hedge bid. The old audit found an eight-minute gap
without a hedge bid in the 16:00 UTC window. Clipping could keep a compliant bid resting, but a
lower price might never fill; the supplied tape cannot measure its benefit. Do not quote the
old “up to $4.20 saved” as executable profit or weaken the pair cap.

The loss-control bugs are already fixed in the deployed code. Fixing them prevents unwanted
behavior; it does not erase this historical loss or prove an edge. Existing ML/pull work found
no validated alternative: on the published validation windows, no-pull lost about 23–50 cents
per window depending on the fill model, and no tested pull rule convincingly beat never
quoting. The preserved TEST split must stay sealed; this audit neither retunes on it nor
relabels already-seen data as fresh validation.

## Frozen forward comparison requirements

Write the protocol before collecting its scoring period. Define original, opposite and no-trade
policies at the **same decision-time opportunities**, including opportunities that never filled.
Specify whether the opposite is an IOC buy or a resting bid; “reverse” alone is underspecified.
Use identical declared dollar caps and stops with independent inventory and fee ledgers. Quote
equal-contract diagnostics separately from the equal-dollar primary comparison.

Record receive timestamps and actual response latencies. Charge fees using the verified venue
schedule and rounding. IOC simulations may consume only size still available when the order
arrives; makers require trades through price after conservative queued size. Cancels remain
fillable until acknowledgement. Both policies hold through the documented settlement rule.
Report fill rates, matched-pair and directional P&L, worst window, capital at risk and the
uncertainty around mean P&L. A small positive sample or one winning window is not enough.

Use newly collected chronological periods with a locked policy and one held-out check; show
every failed candidate rather than selecting only the best. Neither an outcome nor a required
number of profitable days can be promised in advance. No cap increase or budget reset follows
from this audit.

## Reproduce

`python research/kalshi_profitability_2026-10-14/loss_audit.py`

This standard-library script reads only the two named CSVs, asserts per-window reconciliation,
and writes [loss_audit_summary.json](loss_audit_summary.json), with input hashes and aggregates.
It has no network, credential, trading, replay or TEST-loading code. The aggregate output is
safe to commit. Source references: [historical forensic report](../handoff_2026-10-14/loss_forensics_oct13.md),
[published ML verdict](../handoff_2026-10-14/toxicity_ml_verdict.md), and
[independent stop-policy review](../kalshi_stop_review/REVIEW.md).

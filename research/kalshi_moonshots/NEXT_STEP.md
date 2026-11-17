# Next step: measure whether cheap offers are reachable

Decision, 2026-10-13 15:15 UTC, after reading upstream through `2681ff6`.

The highest-value next build is a **48-hour BTC-only, read-only execution recorder**. Its job is to
answer whether our actual feed/order delays leave usable entry and exit liquidity. It does not fit a
profitable model, send orders, or establish an edge in two days. This document recommends the next build;
no recorder was implemented or deployed in this session.

## Why this comes first

The existing speed desk builds Kalshi books in memory but does not retain the complete crypto book
stream needed for replay. Skipwatch's book journal covers Polymarket; weatherwatch covers weather. No
CF Benchmarks index subscription is implemented. Reuse those feed/journal primitives in a small bounded
observer rather than building a new trading engine before execution feasibility is known.

PR #29's [fresh-move study](../kalshi_freshmove/RESULT.md) found negative average price changes after
entry fees in its first fully causal one-second bucket. Its optimistic buckets overlap the second
forming the signal. This warns against assuming a reachable speed advantage, but is not a moonshot
test: it excludes the final 180 seconds, has no subcent entry filter, uses trade prints as entry proxies
and a later median print rather than executable exit proceeds, and omits exit fees. Its displayed mean
and t-statistic also use different trade/window weighting; do not quote that t-statistic as significance
for the displayed cents. No strategy change or rerun follows this review.

PR #30 changes save timing. Measure current performance before using the earlier latency samples as
today's latency distribution; a ping or local computation benchmark is not an order acknowledgement.
Use existing authorized desk receipts for order latency, never place a real measurement trade.

## Freeze this narrow observation before deployment

1. Verify read-only CF index availability through actual messages. Save official index values/averages,
   two spot feeds, current/next BTC window rules, complete book deltas and public prints with sequence,
   source time, local receipt time and gaps. No credentials in data/model artifacts.
2. Observe asks **$0.001–$0.007**. Report 10–180 and 180–720 seconds remaining separately; do not merge
   whichever group later looks favorable. Exclude closed/paused/invalid books and retain rejection counts.
3. Measure displayed entry quantity still available after **100/250/500/1,000/2,000ms**. Report every delay
   and compare with actual measured latency. An order fills only at the first valid arrival state; no
   later favorable quote substitutes for a vanished one. Quotes missing source timing are unsupported.
4. Measure actual bid depth available to sell after **1/5/10/30 seconds**, with entry and exit fees and
   rounding. These fixed horizons describe price paths; choosing the best afterward is prohibited.
   Report missing exits, partial size and zero fills. A bid touch or later chart maximum is not a sale.
5. Reconcile the final-minute index average against official settlement, including precision and ties.
   Report source gaps and mismatch counts. Label missing or interrupted coverage rather than invent ticks.
6. Report eligible windows, quote survival, available quantity, entry/exit spreads and costs, delays and
   completeness. Per-update counts are not independent trials; include window-weighted summaries.

**Decision after 48 hours:** if source integrity fails or offers do not survive plausible arrival with
usable size, fix the data issue or reject this execution route before building the model. If usable
liquidity survives, proceed to the separate frozen model/replay study in [STRATEGY.md](STRATEGY.md).
Survival alone does not show positive expectancy. No relevant opportunities in two days is inconclusive,
not proof they never exist. Positive retrospective price paths are likewise not a live-profit verdict.

No additional real-money authority is implied. Existing trading stays under its current controls.

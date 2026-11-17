# TJR source review and Kalshi direction/exit evidence

Reviewed October 14, 2026, 10:39 AM PDT (17:39 UTC). Scope: the owner's direct request to explain the saved TJR prototype and evaluate better Kalshi direction and exits. This permits the source review now; it does not declare the open Kalshi evidence work complete or start TJR historical/paper execution.

## What was actually read and run

Both current Pages were read completely, including code and limitations:
- [Main handoff](https://chatgpt.com/space/page_d0294998a7cc8191b771278fbfb98a2f), sequence 2, last updated 8:33:21 AM PDT.
- [MNQ prototype](https://chatgpt.com/space/page_33c0bb7e8dac81919e012fc502bae98a), sequence 1, last updated 8:31:57 AM PDT.

Exact block text is preserved in MAIN_HANDOFF.md and MNQ_PROTOTYPE.md. SOURCE_MANIFEST.json records the Page versions, block IDs/hashes, extracted JavaScript hashes, snapshot hashes and runtime. Saved JavaScript was run unchanged in Node v24.19.0, in a VM without broker/network objects:
- Prototype: **65 / 65 synthetic checks passed**.
- Separate BC23 feature harness: **26 / 26 passed**.
- An independent reviewer reproduced both results and reviewed causal entry/exit sequencing.
- Initial local extraction mistakenly matched the JSON fence with a JavaScript-prefix filter; this caused a SyntaxError before tests ran. Exact `js\n` fence matching corrected the extraction without changing saved source. The recorded passing outputs are from the corrected extraction.

These are invented-price tests, not historical returns or broker-paper fills. Historical trades tested: zero. Paper trading: not started. No historical/holdout outcomes fetched. No broker endpoints or production services called.

## What the saved bot does

Version TJR_BC23_MNQZ25_SWEEP_BOS_v0.1 is one older Boot Camp-inspired reversal experiment on actual December 2025 Micro E-mini Nasdaq futures (MNQ). It is not a reconstruction of every TJR rule, the newer June/October model, or a Kalshi strategy.

1. Mark the immediately preceding regular cash session's high and low on the same contract.
2. From 6:30 AM Pacific, require established descending swings into a strict break below the prior low for a possible long; mirror for a short above the high.
3. Require a later candle close through the previously known opposing swing within 15 candles. Wait one full minute after the signal closes.
4. Enter before 8:00 AM Pacific, at most one filled trade per day. Stop one tick beyond the sweep-through-confirmation extreme; target the opposite prior-session boundary.
5. Exit any remaining position at 8:30 AM Pacific. No partial exits, trailing stops or break-even moves.

The timing, level choice and complete parameter set are explicitly engineering hypotheses. The experiment omits news, higher-timeframe bias and S&P alignment. Research quantity is one contract, not an owner-approved live stake. A tick is $0.50, but total trade risk depends on stop distance and execution.

## Confirmed issue before historical validation

The original simulator uses:
```js
if(meta.calendarStatus!=="REGULAR"||meta.previousCalendarStatus!=="REGULAR")
  return out("SKIPPED","SHORT_OR_NONTRADING_SESSION");
```

Three extra synthetic probes confirmed that missing current status, missing previous status and current status UNVERIFIED all become SKIPPED. The summary reports one skipped day and **zero unresolved days**. Unknown calendar evidence therefore masquerades as a planned exclusion.

CALENDAR_PROBES.json retains the actual outputs. Preserve the source; in a separately identified implementation revision, reject unknown statuses as BLOCKED/CALENDAR_UNVERIFIED and allow only explicitly verified calendar exclusions. Add those regressions before historical evaluation. This session did not silently patch the saved Pages or relabel the original 65 checks.

No future-bar peek was found in the reviewed swing/entry ordering. That review is not a formal correctness proof. OHLC target trade-through cannot establish queue fills; spreads, real account fees and feed arrival timing are still unmeasured. Nine fee/friction combinations are sensitivity assumptions. Drawdown is only at completed-session endpoints.

## Missing inputs and exact next TJR step

The frozen historical instrument is MNQ December 2025, provider mapping still unverified. Needed: licensed, unadjusted, actual-contract minute bars for the September 19 warmup and September 22–October 31, 2025 development sessions, then the unopened November 3–December 12 holdout; independently verified exchange calendar; actual fee/spread evidence. Preserve all missing sessions and costs.

Before historical work: correct the calendar classification in a versioned derivative and reproduce the existing tests plus new regressions. Use development data first; preserve holdout isolation. No paid data was purchased or credential inspected.

December 2025 is expired. A future paper study requires its own frozen protocol with the verified current contract/roll calendar, authorized feed and persistent observation runtime. The saved source has no broker adapter or live process. Live execution remains disabled. TJR-MNQ-001 is not done; full historical/paper work stays queued behind the remaining Kalshi evidence work.

## Kalshi: direction versus exits

Existing [loss audit](../kalshi_profitability_2026-10-14/LOSS_AUDIT.md) reconstructed 29 windows from October 13, 9:00 AM–4:15 PM PDT:
- Both sides filled in 28/29 windows, but net result was **-$11.9154** after fees.
- The heavier side lost in **23/27** unbalanced pre-lock windows.
- Entirely resting-filled pairs made $10.3173 gross, yet the whole strategy lost.
- Later lock buys improved the outcome of that same recorded maker inventory by $0.8246. Removing locks is not an evidenced profitable fix.

This suggests resting bids getting filled after value moves against us, not a validated instruction to reverse every signal. The current bot buys and later buys the missing side to reduce exposure; it does not sell winners or sell filled positions when a stop blocks new buys.

The [execution audit](../kalshi_profitability_2026-10-14/EXECUTION_AUDIT.md) and [PR47 receipt](../kalshi_profitability_2026-10-14/PR47_DEPLOYMENT.md) retain the timing evidence. An early post-fix sample still had a 2.080-second account reconciliation and 711-ms loop lag. One accepted arena window and saved recorder metadata do not establish sustained synchronized raw coverage. Existing losses remain unchanged.

### Proposed next diagnostic — not running yet

Once complete synchronized tape is verified, measure every fill's attainable selling bid and available size at 1, 5 and 30 seconds after its actual receipt, plus settlement. Preserve market/event/receipt times, stale or missing quotes, fees, delay, quantity and partial-fill limits. Include every fill and loss; no selecting only moments with favorable exits.

This distinguishes immediate adverse fills from profits that could really have been taken. Selling one side of a locked pair also reopens directional risk; a future exit simulator must track both sides jointly.

Then preregister a separate comparison: identical entries with existing hold/lock management versus one fixed exit rule, using executable post-delay bids and independent ledgers. Evaluate a direction change separately before combining changes. Keep no-trade as a baseline. Do not alter the already frozen original/inverted/no-trade protocol or open its sealed TEST. No profit-taking rule is selected or promoted by this review.

No live rules, money caps, stop budgets, resume tokens, Railway variables, orders or deployments changed.

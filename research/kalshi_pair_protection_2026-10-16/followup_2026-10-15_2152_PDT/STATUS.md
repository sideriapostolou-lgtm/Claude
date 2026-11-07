# Two new completed pairs earned35¢; all settled activity since restart is nearly flat

Evidence through **October15,2026,9:52PM PDT** (October16 04:52UTC), latest financial platform snapshot **9:51:40.614626139PM**. This is a read-only follow-up to [PR69's release](../RELEASE.md). Bot deployment2af8d2be/source66d122b5 and the unchanged recorder8453were online1/1 on the connected health read. No financial settings, order, source or deployment action was made.

| Window, Pacific, October15 | Actual fills | Settled trading P&L |
|---|---|---:|
|9:00–9:15PM, inherited entry|Up1cost40¢ before update; late Down1at94.8¢ plus0.35¢fee|−$0.3515|
|9:15–9:30PM, wholly new|Up1at32¢ +Down1at56¢, zero maker fees|+$0.12|
|9:30–9:45PM, wholly new|Up1at41¢ +Down1at36¢, zero maker fees|+$0.23|
|9:45–10:00PM, wholly new|Up1at52¢ +Down1at42¢, zero maker fees|**Unsettled**;6¢matched inventory margin|

Newly opened, completed windows total **+$0.35**. Including the inherited−$0.3515settlement, total settled P&L change since the9:08:29warm snapshot is **−$0.0015**, a loss of0.15cent. Do not report35¢as the result of all activity after restart or count the pending6¢as settled. Two positive completed pairs are insufficient evidence of profitable expectancy or a100%strategy win rate.

Latest dated account report: cash **$26.3245**, cumulative settled trading P&L **−$23.4769**, current UTC-day settled P&L **−$3.9851**, cumulative fees$3.38382. All four latest samples report LIVE/authenticated/trading, no integrity error or latched stop, and the current window protected. Effective caps remain **$10/window,$20open,$6day loss,$10total loss,5-contract maximum clip**, ladder rung0.

Reported directional positions, open orders, reserved dollars and at-risk dollars are0, but the current protected pair still has **$0.94 open principal** and has not settled. Zero position count is not no inventory. Cash rose45.85¢ from the warm snapshot:4.85¢net incremental inherited-hedge cash release +12¢ +23¢ +6¢pending margin. The inherited40¢entry had already reduced cash before that baseline. Paired$1credits are already recognized; additional net settlement payout is0. Cash change is therefore neither the settled trading result nor recovery of historical losses.

Three new protection receipts appear. For the second pair, marker platform publication9:32:09.459717742PM precedes the second-fill publication9:32:09.459808501PM by90.759microseconds. The marker's local9:32:08.8806949PM timestamp follows the fill's venue9:32:08.682097PM timestamp. This is publication ordering, not anticipatory knowledge of a fill.

## Sizing request and concrete limits

The owner asked for higher size and then asked how much is needed to “ten x it.” That is an unresolved sizing question, not a named dollar/contract instruction. **No increase was made.** [AGENTS.md](../../../AGENTS.md) rule1requires owner instruction “with the amounts or caps named”; the existing financial and Railway-variable authority still applies.

Tenfold the recent actual filled size means10contracts per side instead of1. At the three observed maker-price pairs,10identically filled pairs would cost$8.80,$7.70or$9.40before any changed fees. These are hypothetical arithmetic examples, not available quotes, promised fills or expected returns. Larger orders can fill unevenly, have different queue outcomes and lose more before their other side fills. Tenfold the $10/$20ceilings would instead mean$100/window/$200open, exceeding the reported$26.32cash. Tenfold account growth has no fixed stake or guaranteed recipe.

The dollar ceiling is not the actual order size. The released code limits the clip to5, calls `starter_fit` to reserve room for a hedge under the remaining daily and total loss budgets, checks cash and inventories, then searches permitted whole-contract sizes. Static source inspection supports that mechanism; the raw current stop-anchor state was not read, so this report does not assert a uniquely proved binding budget for each1-contract intent. Raising the window ceiling alone need not increase actual size. Profit can restore remaining budget under the existing policy; no stop reset or new budget is needed merely to observe it.

Recommendation: keep current caps during a broader frozen prospective observation, retaining initial unmatched losses and execution gaps. Larger size should follow evidence and exact owner amounts, rather than extrapolating two positive pairs. The existing sizing request remains open until specified; it is not marked deployed or completed. Overall EXEC/profitability, queue/print fidelity, recorder raw-volume/retention/cost and operating takeover remain open. TJR stays last; no Pages, duplicate TJR research or automation changes.

## Verification and evidence limits

An independent direct-native audit passes **60checks**, using13money-event rows,4latest statuses and1prior warm status. All three used native responses are successful and below their query limits; seven actual fills, three settlements and three protection events reconcile to the reported financial changes. Source, venue and publication clocks remain distinct. The money filter does not include every order, cancellation, warning or quiet interval and does not prove continuous coverage, full account/volume history, queue delivery or the absence of unreported liability. No source tests were rerun because no app code changed.

[RUNTIME_MANIFEST.json](RUNTIME_MANIFEST.json) preserves6selected original files in2lossless parts, including the baseline and independent review/analysis/script. [REPRODUCE.py.txt](REPRODUCE.py.txt) verifies every original byte/hash and optionally restores into a new folder. Re-running the restored `size-review-2026-10-16/astra/status_audit.py` reproduces all60checks and the exact monetary summary; absolute provenance paths differ by restore destination. The previous55-file release archive is unchanged. Private credentials and unrelated operating handoffs are excluded.

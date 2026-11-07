# Independent strategy-effect review: inherited stop fixes

Reviewed `4a9ab4a` and handoff section 4.1 using supplied Oct 13 orders/windows CSVs, the inherited build/review reports, and archived source. No network, account reads, trading, runtime changes or held-out TEST data. Final integrated controller and risk-model paths were reviewed separately below.

## Verdict

These are defensible risk/control fixes once both major latch defects are corrected. They are not evidence of a profitable strategy. The advertised “-$7.91 instead of -$11.92” can be reconstructed as arithmetic, but cannot be represented as an executable, causal strategy replay. It sizes later counterfactual trades against losses from the original history rather than its own changed history. A one-variable correction to use its own cumulative P&L materially changes the same illustrative result to -$10.02224. Neither figure is a valid forecast.

## What is reproducible

- 29 windows, 750 order rows, 145 orders with at least one fill.
- Filled principal $269.2890, fees $0.62642, payout $258.00: reconstructed actual P&L **-$11.91542**. Rounded window P&Ls sum to -$11.9154. This verifies internal consistency of the archived CSVs, not an independent fresh exchange-ledger audit.
- Excluding lock fills, 27 of 29 windows had excess contracts on one side. In **23 of those 27**, that side lost. The inherited count holds. Do not describe its simple coin-flip tail probability as a valid significance test: fills are selected by market moves, windows need not be independent, and the statistic was selected after observing the day.
- Original `replay.py`, its `parsed.json`, the detailed cancel tape and reviewer repro test files were not carried into the handoff. No exact original executable replay is available in these workspaces.
- A fresh scratch reconstruction reproduces all 11 stated changed-window values and **-$7.90934** total. It uses actual historical cumulative realized P&L at each window's opening to size the starter; retains all actual fills in unchanged-size windows; in a shrunk-size window allows only observed subsequent fills that balance the shrunk inventory and actual lock prices; scales paid fees proportionately. This exactly explains the reported cents.
- Replacing only the starter's historical-P&L reference with the reconstruction's own cumulative P&L yields **-$10.02224**. It retains more later exposure because earlier losses were smaller. This sensitivity is not a corrected executable backtest: it still inherits the flawed fixed-fill/no-new-decision mechanics.

Artifacts: [replay_audit.py](replay_audit.py) and [replay_audit.json](replay_audit.json) alongside this report. Re-run with Python; standard library only. The code does not import the live bot or read tokens.

## Why the claimed improvement is not identified

1. **Counterfactual history mismatch.** Later limits are driven by actual losses that modified earlier trades did not incur. In the actual path, the 4 PM starter has $0.8979 of lifetime room and is dropped; in a truly improved path that remaining room changes.
2. **Policy mismatch.** The arithmetic drops adds in a window whose starter shrinks but retains every original add in other windows. The production stop fix does not globally implement “no adds after a smaller starter.”
3. **Missing state machine.** Neither cancel-on-latch, lifetime/day latch persistence, bid pull, concurrent starter intents, uncertain cancels, cash/reconciliation timing nor restart behavior is modeled. The original branch's two major findings can alter exactly the fills assumed by the replay.
4. **Missing fills/queues.** The combined fixes 1+2 illustration can match the stated -$7.91 without enlarging any hedge fill: it caps each hedge at the actual filled quantity. But changed size/order timing can alter queue position and later decisions. The separately claimed fix-1-only improvement assumes a larger hedge fills whenever the smaller actual order filled, which is not demonstrated by trade volume or queue evidence.
5. **Mixed historical releases.** Several early changes shrink starters from 7 or 10 to 5; today's live build already has a five-contract clip. About $1.56 of the illustrative $4.01 improvement comes from those five pre-cap windows. The full improvement should not be advertised as the incremental benefit over today's configuration.
6. **Fees.** Scaling observed order fees in proportion to resized quantity is an illustration. It does not replay actual fill partitions or exact rounding/accumulator behavior.
7. **Strategy still loses.** Even the favorable inherited arithmetic remains negative after fees. Stops cannot make adverse selection disappear.

## Balancing exemption and first-entry reserve

For bought inventory with q unmatched contracts, buying b <= q of the light side at total unit cost u < $1 changes maximum settlement loss by b*(u-1), which is nonpositive. This is the right exemption from day/total *new-risk* checks. Partial fills preserve the inequality; no pending fill should be credited as guaranteed inventory. Cash, full window budget, pair cap, stale data, integrity and cross-order limits must continue to apply, and no exemption may exceed the unmatched quantity after accounting for other pending orders.

A hedge can lower worst-case loss while lowering realized profit on a day the original heavy side wins. Example: 5 UP at $0.40 risks $2.00; 5 DOWN at $0.47 fixes the pair outcome at +$0.65 (zero maker fees), instead of +$3.00 when UP wins or -$2.00 when DOWN wins. It is risk reduction, not a universal profit improvement. A resting hedge has no guarantee of filling before the cutoff; it may still finish through an expensive IOC lock or remain directional.

First-entry pair-cost sizing is conservative and reduces how much inventory can be stranded near a loss stop. It does not reserve an actual hedge price, ensure a hedge fill, or remove the existing inability to bid when the fair quote violates the pair cap. A promised $0.99 pair is therefore not a promised execution. The existing lock can legally complete a pair at more than $1 total cost while still reducing worse directional loss.

## Required final integration behavior

- Only realized exhaustion should persistently latch; at-risk exposure should temporarily refuse additional risk and later resolve normally. Pending bids or an unsettled winner must not require a new owner token merely because they temporarily used risk room.
- While financially halted, strictly balancing hedges remain allowed subject to all other checks. They must not be canceled just because a financial stop latched. Real mode off, integrity failures, staleness, cutoff, fair-price pull and cancellation uncertainty retain their normal authority.
- Exact exhaustion should still allow risk-reducing hedges; arithmetic stop comparisons must not reject risk==0 merely because realized+at_risk is already at/over the limit.
- Stop floors must be internally consistent, checked each step, and should not produce duplicate durable latch receipts on restart.
- Current exhausted budget must remain exhausted across deploy. A fresh owner-authorized token/amount decision is separate from fixing the controls.

A profitable-strategy claim needs the independent recorder's pre-registered, realistic-fill evidence. This review neither opens TEST nor authorizes a restart or increased money.

## Final combined-path review

The final integration resolves the original persistent-exposure latch and hedge-cancellation defects: `latch_bound_stops` now reads settled loss; `_decide`/`_send` scan through financial stops but the risk model refuses new risk; `_send_guard` and `_cancel_unsafe` recompute strict balancing from real inventory plus all active same-side reservations. Nonfinancial reasons remain blocking.

An additional independent fake-only attack changed state after the durable intent and immediately before the transport guard. The portable [transport regression tests](test_transport_guards.py) passed all **16 cases**, each observing an actual `False` guard result with no additional fake venue create: paper mode, removed live confirmation, missing key, auth failure, no successful balance, stale account, stale Bitcoin, stale books, shutdown, foreign owner activity, changed venue terms, cutoff, bid pull, formerly balancing inventory now fully paired, unknown halt reason, and account integrity failure. No network or trading client credentials were used.

No additional real-money blocker was found in that combined-path review. This complements the model/controller regression tests and root's full-suite checks; it is not a formal guarantee for arbitrary exchange behavior. The exhausted production budget is unchanged; startup now recognizes the realized exhaustion before interpreting a resume value. An already used or pre-stop value cannot restart the desk; an owner-approved fresh value is a separate operation.

Reproduce the final-path checks from the repository root with `python -m pytest -q research/kalshi_stop_review/test_transport_guards.py`; run `python research/kalshi_stop_review/replay_audit.py` to rebuild the arithmetic audit JSON. Ruff passes both Python files.

One comparison limitation remains: the practice twin has independent fills/P&L and no matching lifetime-stop anchor; `PracticeDesk.blocked` also rejects all orders when its settled daily loss reaches the daily cap, before the new balancing exemption in `_risk_reason`. The live desk can continue a strictly balancing hedge while financially halted. The twin is therefore not an identical stop-policy control, and a gap between their results cannot be attributed solely to bid pull. This does not grant the twin any live authority or bypass a real risk check.

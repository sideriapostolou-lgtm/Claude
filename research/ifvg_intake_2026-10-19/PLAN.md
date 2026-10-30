# Asia/London sweep and one-minute IFVG: source intake

**Owner clarification, October 19, 2:51 PM PDT:** the original description is all
the owner has. A video/username is no longer a prerequisite. Proceed with our own
explicit [version 1 rules](V1_RULES.md), with engineering assumptions labeled.
The earlier source-intake request below is preserved as history, superseded by
this clarification. No claim of exact trader replication or profits follows.

October 19, 2026, 2:20 PM PDT. Owner asks how to reproduce an unidentified trader's
reported success. This is a bounded source comparison and test outline, not a
frozen strategy, implemented bot, completed backtest or permission to trade.

## What is known

The owner's description is: mark Asian/London highs and lows, watch from 9:30,
wait for a sweep, then a one-minute IFVG and a 1:2 risk/reward target. IFVG is the
likely term, not confirmed from the original clip. The trader, instrument, exact
session definitions and complete results remain unknown. Reported earnings have
not been independently verified; screenshots or selected winning trades would
not establish full-period net returns, deposits, risk or drawdown.

The source link or username has been requested. If 9:30 means the New York cash
open, that is 6:30 AM Pacific; do not assume the clip's timezone or traded market.

## Existing work that can help

At repository commit 081ec40ffd71edcc19a98d30be2431808d1656dd, the saved
[MNQ experiment](../tjr_mnq_2026-10-14/MNQ_PROTOTYPE.md) uses previous cash-session
high/low, break-of-structure confirmation and the opposite boundary as target.
It does **not** implement Asian/London levels, an IFVG entry or a fixed 2R target.
Preserve it and its unopened evaluation partition as a separate experiment.

[Later validation](../tjr_validation_2026-10-14/VALIDATION.md) already fixed the
original calendar classification defect in a versioned derivative. Recorded
65 prototype, 26 feature and 58 runner checks are software tests, not earnings.
[The saved historical receipt](../tjr_validation_2026-10-14/HISTORICAL_STATUS.json)
reports missing verified actual-contract data, zero historical trades, null P&L,
paper not started and live disabled. These checks were not rerun for this intake.

Reusable tooling includes source/data hashes, contract and calendar checks,
missing-data accounting, losses on incomplete sessions, and separated development
and holdout inputs. The existing runner accepts cash-session bars only; overnight
levels need a separately reviewed extension. It has no verified provider adapter.
Its nine cost scenarios are assumptions; exact account costs, operating-cost
accounting and statistical extensions are not a completed implementation.

The bounded repository/manifest review found no verified dataset for this new
setup. The [recorded data-access checks](../tjr_validation_2026-10-14/DATA_ACCESS.md)
found public samples with wrong dates/contract or inadequate session coverage for
the old experiment. This is not proof that all possible sources are unavailable.
No new data request, purchase, credential read or historical outcome was made.

## Historical source-intake steps (video dependency superseded above)

1. Identify the trader and instrument from the clip. Extract the actual rules and
   record source timestamps. Separate statements from assumptions and unresolved
   discretion. Verify complete performance records if available, including costs
   and losing periods; do not manufacture access to private account results.
2. Resolve session boundaries/timezones/DST, sweep versus reclaim, FVG geometry,
   selection among multiple gaps, inversion close, entry trigger/order type,
   expiry, stop, 2R basis, partials, time exit, news treatment and attempt limits.
   No guessed defaults may masquerade as the trader's strategy. Unknown rules
   stay unresolved; our own version must be explicitly labeled if needed.
3. Freeze a separate specification, development and untouched evaluation periods
   before inspecting returns. Obtain authorized data for that exact instrument,
   including overnight sessions, with original timestamps, gaps and costs. For
   futures, preserve actual contracts and roll rules. Do not substitute Kalshi
   contract prices or treat underlying direction as a Kalshi profit test.
4. Implement only the missing pieces and test causal timing. A candle-close
   signal cannot fill earlier in the same candle. Minute bars can leave stop/
   target order ambiguous: preserve ambiguity, use conservative assumptions or
   finer data, and never infer queue fills from a touch alone.
5. Evaluate all eligible sessions, including losses and no-trade days, then one
   untouched evaluation. Report net after commissions, spread/slippage and data/
   platform costs, drawdown, uncertainty and profit concentration. Preserve every
   attempted variant. No arbitrary win rate or trade count guarantees an edge.
6. If results justify it, run a separately registered forward paper observation
   with a verified feed and actual start evidence. Compare assumed versus
   observed execution before considering any separately authorized live pilot.

For intuition only: if every winner is exactly +2R and every loser exactly -1R,
gross break-even win rate is one third. With constant average costs c measured
in R per trade, it becomes (1+c)/3. Real stop slippage, partial exits and variable
costs change that model. A claimed 2R target alone establishes no profitability.

## Historical source-intake scope (video dependency superseded above)

Send the original video/post link or trader username; that is the next useful
input, not funding or a larger Kalshi stake. No new live setup, production release,
configuration, financial limit, order, funding or paid access is authorized by
this intake. Existing storage recovery stays open; the older TJR queue and paused
reminder are unchanged. This request does not prove those tasks are finished.

Review: root source comparison plus a bounded Sol inventory; later validation
corrected the reviewer's initially outdated original-only calendar/data account.
No synthetic checks were presented as historical returns and no TEST was opened.

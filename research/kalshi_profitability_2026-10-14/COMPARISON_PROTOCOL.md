# Original, inverted signal, and no trade: prospective Kalshi comparison

Written 2026-10-14. Protocol version `kalshi-shadow-three-arm-v1`.

**Status: specification only; no shadow results and no activated cohort.** Committing this document fixes the
experiment design, not its implementation or start. Activation requires the tested code hash, complete parameter
hash, a clean-feed checkpoint and a future start in an immutable `ACTIVATION.json`. No existing data is TEST for
this study. No trading setting, order, automatic promotion or real-money budget is authorized by this document.

## Question and prior evidence

Does deliberately inverting the speed desk's directional fair-value signal outperform both its original signal
and doing nothing, when each strategy pays its own obtainable prices, fees and execution delays?

Known before this protocol: October 13 loss forensics reported adverse selection, expensive late pair completion,
and profitable resting-bid pairs within an overall losing book. The toxicity study's TRAIN/VAL did not find a
useful adverse-fill predictor. The owner proposed fading the bot. Current production cancels have sometimes taken
about 10 seconds, and account reconciliation has sometimes taken about 17 seconds. These observations motivate
the question; they do not establish that inversion wins.

The separate toxicity study's newest 23 TEST windows remain sealed. The Family A protocol on the recorder branch
also retains its own dates, freeze witness and TEST gate. This experiment must not read either study's hidden
books, prints, labels or outcomes. Prior public summaries may inform this declared hypothesis, never serve as its
unseen evaluation.

## Fixed arms

| Arm | Rule | Meaning |
| --- | --- | --- |
| Original | Existing fair-value calculation and frozen live strategy parameters | A simulated strategy control, not a reconstruction of actual live fills |
| Inverted | At the same evaluation time replace fair YES probability `p` with `1-p`; fair NO becomes `p` | New decisions at the opposite side's actual book, with its own inventory and admission checks |
| No trade | Never submit a simulated order | Zero trading profit, zero exposure and zero execution fees |

Inversion never changes market outcomes, books, strikes, trade sides, source timestamps or recorded losses. It is
not `-original_pnl`, not buying the other side at `1-original_fill_price`, and not a reaction to an original fill
known only later. Because the strategy normally considers both sides, merely relabeling YES and NO would not test
anything. Flipping the fair probabilities while keeping the real books fixed is the precise hypothesis here.

All non-signal rules are identical. Freeze actual non-secret configuration from the producer's allowlisted arena
configuration, the strategy source revision, settlement-average calculation and fee terms. Fix the configured
limits at $10/window for ordinary buys, $20 open for ordinary admission, $6 UTC day stop, $10 study lifetime stop
and five-contract clips. Include resting reservations and fees. These are **not hard gross-spend ceilings**:
as in the current live rule, a confirmed strictly balancing lock can exceed the ordinary window/open spending
budgets only when it satisfies cash, inventory, freshness, uncertainty and lower-worst-loss checks. Its new
contracts cannot exceed confirmed unpaired holdings. Report such completion spend separately; do not hide it
under the phrase "$10 maximum spent." Each arm gets a separate simulated bank of $38.4993, the documented 14:09 UTC cash snapshot;
this is an experimental budget, not a claim about current cash. No arm receives deposits, a ladder raise, a fresh
resume token, re-funding or an automatic restart after its lifetime stop. A stopped arm remains in the sample
with zero subsequent trading activity; adverse outcomes must not be deleted by restarting it.

Match current live conservative ordinary admission and strictly balancing exceptions exactly; do not rely on the arena's
approximation for those rules. In particular, replacing a canceled order must wait for its acknowledged removal,
and a late pair-completion order must respect the actual cash and confirmed-inventory rules. Keep the existing
loss-budget policy rather than interpreting the lock exemption as permission for fresh directional risk. Record discrepancies
between simulated original and real execution without forcing them to match.

## Evidence and execution

Primary evidence is the existing arena's received feed: full/delta Kalshi books, public trade prints, window
metadata, venue results, Bitcoin price/time, supplied volatility, sequence numbers and gap counters. Preserve
producer-send time, child-receive time and exchange time separately. Information is usable only after receipt.
The alternative recorder tape uses about 1 Hz public REST books and polled prints and is lower fidelity; it is
a separately labeled sensitivity check, never silently substituted for missing websocket evidence.

Primary simulated create/ack delay is **1 second** and cancellation delay is **10 seconds**. These are fixed,
deliberately slower assumptions, not claims about a measured median. One prespecified cancellation stress uses
**17 seconds** to test vulnerability to a long blocked loop; it is not a measured cancellation quantile. Keep the
original and inverted arms separate at both delays. Do not select the faster, more profitable assumption later.
Record real latency separately. If the real sustained tails exceed the fixed assumptions, the result cannot be
called executable at production speed without a new future test or a more pessimistic preregistered bound.

- A maker bid becomes eligible only after its create delay and a qualifying book observation. If it would cross
  the ask, post-only means refusal, not an instant maker fill. Queue ahead starts from displayed same-price size
  when it becomes eligible; do not assume cancellations ahead of us.
- Only correctly sided, deduplicated real prints after eligibility consume queue and then fill remaining size.
  A touch or reduction in displayed size alone is never a fill. No print may be consumed twice inside one arm.
  Different arms are independent counterfactual accounts; their quantities must not be added as realizable volume.
- A cancel request leaves the bid alive, fillable and reserved until its due acknowledgment. Partial fills in
  that interval update inventory. No replacement or lock may pretend that reservation disappeared early.
- A take/lock needs the first qualifying post-delay book, actual depth and a surviving price. A vanished quote
  is rejected rather than held until it reappears. Charge actual simulated fill size and venue fee rounding.
- Fees use each window's recorded maker/taker terms and verified direct-account $0.0001 accounting. Unknown or
  inconsistent terms disqualify trading in that window. Do not assume maker fees are always zero or invent rebates.
- Book outcomes only from the venue's settlement record and exact contract rules. Coinbase is a predictor, not
  a settlement oracle. Locked and directional P&L must sum to total P&L after fees.
- The public tape cannot identify hidden queues, actual hypothetical post-only acceptance or market impact.
  Report this limitation and strict/pessimistic fill bounds; a simulated gain is not a demonstrated real return.

## Freeze, calendar and data defects

1. Implement and independently test with synthetic data only. Persist protocol and executable source hashes.
2. Collect at least 24 continuous hours of health-only evidence after the arena feed repair. At least 95% of
   expected complete BTC windows must be covered, with no unreported gaps. Do not inspect three-arm P&L in this
   calibration phase or use its outcomes for tuning. Finalize activation at least one hour before the first full
   UTC evaluation day; record the frozen parameters, source hashes, storage plan and future dates in git.
3. Evaluate exactly **14 consecutive future UTC days**, including every window and every no-trade/stop decision.
   Continue reconciling those windows for at most 48 hours after the last close. No early profitable stopping,
   breeding, best-resident selection, parameter change or automatic promotion is permitted.
4. At least **1,000 common fully covered windows**, 95% coverage, and 100 traded windows in each trading arm are
   required for a strategy comparison verdict. Otherwise report INCONCLUSIVE, including a stop that prevents
   the trade floor. Do not extend the cohort until it passes; new dates require a new versioned experiment.

A startup, restart, missing delta base, sequence loss, explicit feed gap, stale input or failed checkpoint marks
the affected whole window incomplete for all arms. Missing data is never evidence that a quote survived. Do not
delete previously simulated costs/losses: retain an operational ledger and conservative unresolved-exposure bounds
even when the inferential paired sample excludes the window. Coverage exclusions are predetermined, shared and
reported alongside their relationship to volatility. Missing results after follow-up mean INCONCLUSIVE, not $0 loss.
Persist all stop and accounting state across restart; if that cannot be established, stop the study with a stated
defect. Never silently start a fresh funded cohort.

Daily during the evaluation publish only health, coverage, counts and latency. P&L and arm rankings stay sealed
until the fixed endpoint. Actual real-money reporting continues normally and must not alter study parameters.

## Final scorecard and decision

For each arm publish net P&L, P&L/calendar day, trading and infrastructure cost separately, fills and orders per
window, acceptance/fill/cancel rates, maximum capital tied up, day/lifetime stops, drawdown, worst window, pair
cost, both-sides rate, imbalance, and locked versus directional P&L. Report included and excluded window counts,
all execution assumptions, lag distributions, lost frames and cash/position reconciliation checks.

Primary comparisons are paired daily net dollars: inverted minus original, and inverted versus no trade. Use
day blocks rather than pretending thousands of correlated 15-minute windows are independent. Fix the statistical
implementation and random seed before activation. A conservative two-comparison allocation within Family B's
0.025 error budget gives one-sided alpha 0.0125 to each; label the small 14-day sample and bootstrap limitations.
Profitability requires both a positive absolute result after fees/attributable operating cost and positive
paired improvement, with positive lower confidence bounds. Report the 17-second cancellation stress even when it
fails. A better-but-still-losing inverse is not profitable; a lucky positive point estimate is not proof.

Possible verdicts: NO EDGE, INCONCLUSIVE, or CANDIDATE FOR A NEW FORWARD TEST. This document alone never authorizes
live inversion, increased caps or a fresh budget. If original and inverse both lose, preserving cash is a valid
result and the next experiment must start with new data.

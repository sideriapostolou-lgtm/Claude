# TJR profit-evidence protocol v1

Recorded October 14, 2026, 12:15 PM PDT (19:15 UTC), before any historical returns were computed.
This fixes the decision criteria; the data and account-cost inputs remain missing. It is a test plan,
not a successful backtest or a live-trading authorization.

The owner is willing to consider a small real-money test if necessary. No futures broker, funding
amount, per-trade risk, daily loss limit or total trial loss limit has been supplied. Existing Kalshi
permissions do not transfer to MNQ. No live capability, order, financial-setting change or production
deployment is part of this protocol. The existing Kalshi evidence work continues separately.

## 1. Preserve the experiment

- Use `TJR_BC23_MNQZ25_SWEEP_BOS_v0.1.1_calendar` and the exact source/parameter hashes in
  [SOURCE_DERIVATION.json](SOURCE_DERIVATION.json). Preserve the original Pages and all test results.
  This is the saved BC23-inspired subset, not a test of every discretionary TJR rule.
- Actual, unadjusted MNQ December 2025 only: September 19 warmup; September 22–October 31 development;
  November 3–December 12 untouched holdout. No continuous futures, NQ or CFD substitution.
- Freeze provider identity, instrument definitions, permission to use the data, raw hashes, timestamp
  convention, normalization audit and independently verified cash calendar before replay. Do not
  forward-fill gaps. One-minute OHLC cannot establish exchange queue position or exact intrabar path.
- Preserve every scheduled session, zero-trade day, excluded session with reason, and known closed
  loss. Any unresolved required session leaves the whole-period P&L unknown. Missing data is not a
  zero-return day or a reason to remove a losing trade.
- Development first. Freeze reviewed code, parameters, cost manifest and this protocol before one
  controlled holdout evaluation. Record first access and all outputs. Any strategy adjustment after
  seeing holdout results requires a new version and genuinely untouched evaluation period.

## 2. Choose costs without seeing returns

The existing runner produces nine sensitivity cases: per-side fees of $0.50/$1.00/$1.50 crossed with
1/2/4 friction ticks. Retain all nine. They use the same data and rules, not nine independent
experiments; friction can change entry validity and therefore the accepted trades. None becomes the
primary case because it earned the most.

Before inspecting development returns, attach the intended account's dated all-in commission/exchange/
clearing/regulatory schedule. Choose and document the primary execution-friction assumption from
independent spread/execution observations, including their instrument, dates and coverage. If that
evidence is unavailable, results stay assumption-only. One-minute trade bars alone do not provide it.
Record whether friction includes spread to avoid charging or omitting spread twice. Verify whether
broker fees vary by entry/exit type; do not silently collapse a nonlinear fee schedule into a flat fee.

If actual costs differ from the frozen grid, add a separately reviewed exact-cost replay and retain
all nine original cases. The current runner only stores account-cost evidence and runs its fixed grid;
it does not yet implement this extra replay or the operating-cost/statistical analysis below.
Implement and verify those against the actual inputs before claiming this protocol was completed.

Report, separately:

1. Price-move gross P&L; adverse execution adjustment; commissions and other transaction fees; trading net.
   Preserve the runner's original fill-based gross definition. Reconstruct unadjusted reference prices
   for the same accepted trades to isolate friction, rather than rerunning a zero-friction strategy
   that could accept different trades. Reconcile the decomposition without deducting friction twice.
2. Operating net: trading net minus the required recurring data/platform costs, allocated in full to
   this standalone strategy. Prorate monthly charges by calendar days covered divided by days in that
   month, then allocate the period total equally across its eligible sessions, including no-trade days.
3. Incremental cash net against keeping the strategy off, identifying any subscriptions already paid
   for other work. This is secondary; it must not silently replace the more conservative operating net.
4. One-off data/research/setup purchases, plus cumulative cash net after those costs. Keep one-off costs
   visible without counting them repeatedly as recurring fees or deducting the same bill twice.

Freeze the expense list and allocations with the cost manifest before inspecting returns. Unknown
costs remain unknown. All projected-dollar figures are hypothetical one-contract results, not cash
earned, and the one-contract research unit does not approve a live position size.

## 3. Score the result, including losses and uncertainty

Primary outcome: the complete holdout's operating net in dollars under the independently selected
primary cost case. Benchmark: no new strategy and no trades. Also report trading net, each cost case,
all daily returns, number of scheduled/complete/missing/no-trade sessions, trades, win rate, average win
and loss, worst trade/day, consecutive losses, session-end drawdown and profit concentration. Label
session-end drawdown as such; it does not measure intratrade drawdown or broker margin requirements.

Report the result excluding the best session's trading contribution while retaining the full period's
fixed costs: subtract the largest daily trading net from period operating net, without refunding that
day's allocated operating costs. Separately replay with one extra adverse tick on each aggressive
fill. Neither diagnostic permits changing the actual strategy after seeing outcomes.
Early-close/holiday exclusions remain visible, with their predeclared calendar reason.

Uncertainty plan, to implement before the holdout is opened: use eligible-session operating-net
returns, including no-trade sessions. Resample overlapping, non-circular blocks of five sessions with
replacement, concatenate and truncate to the original session count. For each replicate of n sessions
and block length L, draw ceil(n/L) independent uniform integer starts from 0 through n-L inclusive.
Use 10,000 replicates with NumPy PCG64 seed 20261014, reset to that seed separately for each block-length
run, and record the NumPy version. Report the 2.5th/97.5th percentiles using linear interpolation for
mean daily net and the implied same-length total. Repeat with one-session blocks as a dependence check.
If fewer than ten eligible sessions are complete, classify uncertainty as insufficient rather than
reporting a promotion interval. Ten is only an operational minimum, not evidence of adequacy.

These intervals assume the observed days represent the process. A short period can miss rare losses,
different regimes and dependence longer than five days. Neither a positive interval, a win rate nor
an arbitrary trade count proves a durable edge. A few live wins cannot cure these limitations.

| Result | Decision for this version |
| --- | --- |
| Required data, calendar, cost provenance or outcomes unresolved | **BLOCKED** for the real-cost verdict; publish any assumption-only results separately. |
| Complete primary holdout operating net is zero or negative | **LOSS / NO-GO FOR THIS VERSION** on this period. Preserve losses; this does not prove every future version fails. |
| Positive point estimate but either interval includes zero, best-day removal loses the sign, extra-tick stress loses the sign, or execution credibility remains unresolved | **INCONCLUSIVE**; no profit claim. |
| Complete primary holdout is positive, both interval lower bounds exceed zero, and both predeclared stress checks stay positive, with credible inputs | **PROMISING FOR FORWARD PAPER ONLY**, with all OHLC, sample and regime limitations visible. |

The development result is a feasibility/debugging result, never the final verdict. If development
primary operating net is nonpositive, stop this version and retain the unopened holdout. A positive
development result permits the separately implemented and reviewed single holdout evaluation; it
does not authorize paper or live execution automatically. No changing thresholds to obtain a pass.

## 4. Prospective paper observation, then a possible execution pilot

December 2025 MNQ is expired. A forward study needs a separately verified current actual contract,
roll/calendar rules, authorized feed and persistent paper runtime. Before it starts, register its
dates and costs, freeze the strategy version, and record an actual start receipt. Every decision must
use information available then. Keep decision/quote timestamps, gaps, hypothetical order/fill/exit
events, costs and losses. Weekly reports are descriptive; do not repeatedly peek and stop when the
running total happens to become positive. Completing a fixed period does not itself establish an edge.

A later, separately approved real-money pilot would measure actual fills, slippage, latency, rejects,
stop execution and reconciliation against the frozen predictions. It is execution calibration, not
a replacement for historical or prospective evidence. Reconcile every order/fill/fee/position with
broker records, including missed orders and all losses. A matched paper twin remains a model; a
better-looking simulated result must never replace the real ledger.

Present the concrete pilot for approval only when the broker/account, verified current instrument,
feed, margin requirements, and modeled entry/stop costs are known. The owner must name the allowed
funding, per-trade risk, daily loss tolerance and total trial loss tolerance before activation. Do not
assume that "small amount" supplies those numbers or that existing Kalshi caps apply.

[CME's contract specification](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html)
sets MNQ at $2 per index point and $0.50 per 0.25-point tick. One contract is the minimum; its risk depends
on the strategy's stop distance, costs and broker requirements. If it cannot fit the approved budget,
the pilot cannot run at that size. Never shorten the strategy's stop or alter its rules just to fit.
Stop orders can slip or gap, so a software loss limit cannot guarantee a maximum realized futures loss.

## Current receipt and next action

Historical trades tested: **0**. Historical P&L: **unknown**, not zero. Paper: **not started**.
Live TJR execution: **disabled**. All previously reproduced checks are synthetic/software checks.
This document adds decision criteria; it does not add market observations or a financial result.

The owner has been asked whether an existing futures broker/data account is available. The exact next
input is the authorized MNQ December 2025 minute export for September 19–October 31, with mapping,
license and timestamp evidence; see [DATA_ACCESS.md](DATA_ACCESS.md). No paid purchase or new account
has been authorized. Once accessible: verify the real schema, write/review the lossless adapter,
freeze costs and data, then execute development. Do not repeat unchanged source/test/data-access work.

TJR-MNQ-001 remains active but blocked, not done; retain its follow-up automation. No production path,
Kalshi setting, order, stop, resume budget or account value was changed by this research plan.

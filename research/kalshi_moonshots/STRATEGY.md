# Extreme-payout Kalshi crypto: proposed strategy

2026-10-13. **Research design, not a demonstrated edge or live trading instruction.** The owner asked for
a complete strategy before a later build. No application code, money settings or orders change here.
See [sampling plan](PLAN.md), [venue/data evidence](EVIDENCE.md), [arithmetic](MATH.md), and
[implementation specification](BUILD_SPEC.md).

## Verdict

Research a bot that buys a mispriced long shot after reliable new information and sells when the bid
catches up. Compare it with holding the same entry to settlement. Do not buy because the payout looks
large. There is no basis to claim we would be first, know perfect entry/exit times, or compound a dollar
reliably into thousands. Existing traders already compete for stale prices.

The potentially useful advantage is a better model of **the actual settlement index and its final-minute
average**, combined with executable quotes, measured latency and conservative tail calibration. Whether
that leaves any opportunity for this server is unknown. “No qualifying trade” is a valid model output.

## What we verified

- The immediately preceding BTC, ETH, SOL and XRP windows all had public prints with an outcome priced at
  **$0.001 = 0.1 cent**. We inspected no outcomes for that sample. Prints prove transactions, not our fills.
- Current sampled tail grids move in $0.001 steps. One-contract taker asks of $0.007/$0.002/$0.001 can cost
  $0.0075/$0.0022/$0.0011 after direct-account rounding, yielding approximately **133x/455x/909x** winning
  payout multiples. That plausibly explains the owner's display; its exact UI convention was not inspected.
- The contracts compare CF Benchmarks averages over the final minute and the minute before opening. A
  final Coinbase tick crossing the line is not enough. Ties resolve YES; contract precision differs by coin.
- Kalshi documents an authenticated [index feed](https://docs.kalshi.com/websockets/cfbenchmarks-value)
  with running averages and a [five-Hz feed](https://docs.kalshi.com/websockets/cfbenchmarks-value-5hz).
  Account availability remains untested. These are candidate data sources, not an existing deployed feed.
- Public historical prints/candles are available. We did not find a documented public archive of full
  historical book deltas. Candles alone cannot establish entry, exit or queue execution.

## The trading hypothesis

Suppose an outcome has a real ask of 0.2¢. New index and spot information raises its defensible probability
enough that this offer is cheap after fees, but the offer is still present when an order could arrive.
If the market later offers a sufficiently high **bid**, the bot may sell. A move from 0.2¢ to 0.6¢ is a 3x
gross price change, not a 3x net return: both fees, quantity and depth matter. The bid might never reach
0.6¢ or may disappear before an exit arrives. This is an example, not an observed profitable trade.

The key test is conditional on getting filled. Slow quotes often disappear; quotes left available may
belong to participants with better information. Profitable-looking signals without achievable entries
are not an edge. Nor is a later chart high a sale receipt.

## Inputs and probability model

Start evaluation on **KXBTC15M**. Record ETH/SOL/XRP as separate observational cohorts; do not pool them
as independent opportunities or quietly promote whichever coin looks best.

For each decision preserve market rules/version, official strike, settlement precision, fee schedule,
native price bands, full YES/NO books, recent trade direction, index values, spot midpoints and both
exchange/source and local receipt times. Synchronize clock uncertainty and record sequence gaps.

The settlement variable is the correctly rounded mean of the contract's 60 index observations. During
that minute, with `k` known samples and their sum `S_known`, the model forecasts:

```text
settlement_average = round_contract((S_known + sum(future 60-k samples)) / 60)
q_yes = P(settlement_average >= official_strike | information received now)
q_no  = 1 - q_yes                  # ordinary verified binary settlement case
```

Exact index sampling boundaries must be reconciled against actual settlement. The five-Hz predictor does
not replace the one-second settlement samples. Missing observations, exceptional resolution rules or an
unverified source make the relevant signal unavailable; no invented ticks or “certain” labels.

Fit one documented empirical path model on TRAIN: causal short/long realized volatility, standardized
historical return blocks, jump observations and index/spot basis. Initial volatility horizons are 30s,
300s and 3,600s; spot moves use 0.2/1/5/30s. Resample **whole historical paths available before the training
cutoff**, scale using then-available volatility, and preserve serial dependence. Condition on direction,
time remaining and volatility regime without inventing tiny bespoke buckets. Fit parameters and any
conditioning boundaries on TRAIN only; freeze code/config hashes before CALIBRATION/VAL/TEST.

The simple Gaussian spot model is a diagnostic baseline. It must not become a trusted extreme-tail
forecast through a probability floor, smoothing constant or enormous Monte Carlo sample. Generating
more paths reduces simulation noise, not model error or the scarcity of real tail events.

Calibrate out-of-fit forecasts against actual venue outcomes and source errors. `q_L` is a conservative
model-based lower estimate, including tail calibration uncertainty and plausible index/basis error,
not a distribution-free guarantee about one order. The proposed method is a monotone logistic calibration
of the raw YES log-odds, time remaining, signed index distance and spot/index basis; freeze transformations
and regularization on TRAIN. Weight repeated candidate states so each window contributes total weight
one. Use 2,000 whole-UTC-day block refits for a nominal 95% interval, with the random seed fixed before
evaluation, and include prespecified source/basis stress cases. Require finite stable fits and no
unsupported feature extrapolation. For NO, the lower bound is **one minus the YES upper bound**; never
complement a YES lower bound to make an optimistic NO estimate.

Operational support floors are 200 distinct eligible calibration windows and ten winning/ten losing
cheap-outcome windows in the relevant predeclared time cohort (10–60, 60–180, 180–720 seconds remaining).
These are screening floors, not evidence of adequate power or accurate per-state probabilities. Sparse
tails, unstable fits, a few effective day clusters or inconsistent stress cases make the interval
unavailable. The entire frozen eligible/filled policy must be checked on VAL and untouched TEST: selection
by stale quotes, feed agreement and fills can change calibration within the same prediction band.

Use prespecified forecast-probability
bands `[0,.001), [.001,.002), [.002,.004), [.004,.008), [.008,.02), [.02,.05), [.05,1]`, reporting time/volatility
cohorts and day dependence. Bands are diagnostics: a confidence bound on their average win rate must
not be assigned to every individual state. Unsupported cohorts have `q_L=unavailable` and cannot qualify. A favorable
point forecast, Brier score, Bayesian prior or simulated confidence band cannot override that condition.

This model is a buildable research approach; its trained coefficients and calibrated bounds do not exist
yet. They cannot honestly be supplied as profitable rules before observing the required data.

## Frozen initial entry policy

These are proposed research defaults, not optimized findings or real-money settings. Freeze them again
with the recorder/model commit and exact future dates before starting an evaluated run.

1. BTC only; raw executable ask **$0.001–$0.007** on the venue's valid grid. Evaluate both outcomes without
   treating YES/NO or adjacent windows as independent bets. At most one entry intent per market window;
   no adding after losses, re-entry, opposite-side hedge or martingale in this first policy.
2. Time remaining is at most **720 seconds** and at least `max(10s, 2*tau99 + 5s)`, where `tau99` is a
   conservative decision-to-ack latency bound from comparable deployment conditions. Before measured
   latency exists, replay 100/250/500/1,000/2,000ms scenarios and report each; choose no convenient winner.
   Recheck market status and actual close time, including early changes.
3. Require a new accepted index update; the latest one-second index is no older than 1.5s. Require two
   healthy spot midpoint feeds, each no older than 500ms, whose one-second changes agree with the proposed
   outcome. These feeds are confirmation features, not two independent proofs of settlement. If midpoint
   data are unavailable, do not silently replace them with stale last trades.
4. Require synchronized book state with no sequence gap and a genuine source/update age <=250ms.
   An HTTP response time is not source freshness. Reject if clock uncertainty can erase these bounds or
   if observed decision-to-send time exceeds 50ms. These strict gates may reject nearly everything;
   report that instead of relaxing them after seeing outcomes.
5. Relative to the immediately preceding accepted index state, `q_L` must increase toward this outcome;
   the current probability cohort must be supported. Inside the final minute, its known average prefix
   must be complete and reconciled. No probability is inferred merely from a large spot spike.
6. For candidate quantity `Q`, compute depth-swept cash `C(Q)` including applicable fees and conservative
   rounding. Define `c=C(Q)/Q`. Require **`q_L >= 2*c`** and positive modeled return under the slower
   latency scenarios using only information received at decision time. Later replay books/outcomes may
   determine fills/results but may never retroactively qualify an entry. This is a substantial proposed
   error margin, not evidence we can estimate `q_L`.
   Quantity, costs and validity are rechecked after rounding down to the permitted size.
   Choose the largest permitted quantity that satisfies the paper cash/window/open/stop limits, the
   conservative fee reservation, displayed depth and all price/edge gates. If no valid minimum size fits,
   skip; never round up. Later size-capacity replays remain separately labeled alternatives.
7. IOC limit entry only in the initial experiment. Maximum price is the last accepted price tier that
   passes the whole fee/edge test, never a market order or arbitrary slippage allowance. Simulate actual
   arrival: a vanished quote yields no fill; partial size yields only that fill. Reserve the entire
   authorized premium and potential fees until terminal reconciliation.

The predictor must compute its features before the decision. A simulated fill cannot retroactively
change the entry signal. If both sides somehow qualify in contradictory models, reject the window as
inconsistent rather than spending twice. No authenticated trading client exists in the first build.

## Frozen initial exit policy

For actually filled owned quantity, sweep currently observed same-side bids from best to worst, capped
at confirmed inventory minus pending/uncertain exits. The exit tranche is the largest valid quantity
covered by that depth with positive expected net sale proceeds after fees; round down to the allowed
quantity increment. Use the worst included valid bid tier as the IOC sell limit. Accept no unseen worse
price. If no positive-net valid tranche exists, record no executable exit; zero/negative-net sales are
not submitted by this policy. Recheck worst-case fee obligations against reserved cash as well.
Let `b_net` be net proceeds per contract for that exact tranche.
Recompute current `q_L`; acquisition cost determines realized P&L but is not the prospective value of
holding one more second.

The primary policy attempts an IOC liquidation when the first condition holds:

- **Value converged:** `q_L - b_net <= max($0.0001, 0.10*q_L)`. This uses account precision, not a full
  $0.001 tick, which would be 100% of the lowest raw entry price. It is a research tolerance, not an
  optimal-stopping theorem. A falling fair value can trigger a losing exit; label that loss honestly.
- **Signal invalidated:** the supported bound falls to half its entry value, both confirmation
  feeds reverse, the verified model changes to the opposite direction, or required input validity fails.
  With stale books/model, rely only on fresh usable exit information; otherwise retain unknown exposure.
- **Time budget:** 30 seconds since the first entry fill, or `max(5s, tau99+2s)` before actual market close.

Sell no more than confirmed inventory minus pending/uncertain sell reservations. Partial exits leave
remaining inventory. Once exit mode begins, do not reopen the position because the signal recovers.
Re-attempt remaining liquidation only after a fresh book or reconciled order state, at most once per
250ms and within shared write budgets. Never blindly repeat an uncertain create.

If no acceptable bid exists, no sale is credited. Residual exposure remains at risk and settles from
the venue's result if it cannot be sold. A timer or stop is an instruction to attempt risk reduction,
not insurance. New-entry sizing must tolerate **100% loss of premium and fees**.

The comparator uses the **same hypothetical entries but holds to settlement**, in an alternative virtual
account. It does not double-spend or claim both policies could consume the same liquidity simultaneously.
Evaluate the primary once as preregistered; the comparator is a diagnostic, not a backup winner selected
after looking at TEST. No trailing stops or partial-profit ladders are added after seeing the best chart.

## Size, compounding and capacity

Use fixed-size normalized research records plus separately funded paper portfolios. Keep actual cash,
paper cash, executable liquidation value and settled profit separate. The first funded simulation uses
a hypothetical $100 bank, $0.10 maximum cash cost per window, $0.20 open, $1 UTC-day loss stop and $3 total
loss stop, fees/resting or uncertain obligations included. These are **paper-only research values**, not
the owner's balance or permission to place trades. Observation continues when the simulated bank stops;
unfunded signal diagnostics remain labeled hypothetical, not funded returns. Roughly thirty full $0.10
losses exhaust that total paper budget; future hypothetical wins cannot revive the stopped account.
The primary economic estimand is net return per eligible window under the frozen execution policy;
the separately reported funded-portfolio result answers whether the bounded bankroll can survive it.
Neither substitutes for the other. No compounding in this trial.

Independently replay capacity at $0.01/$0.10/$1/$10/$100 budget levels, without selecting the best-return
size or assuming simultaneous fills. Sweep the real book at arrival; include worse marginal prices and
exit depth. The size that works with pennies may have no capacity at $100.

For context only, even if a 909x bet had **twice its break-even probability**, 25 independent such bets
would all lose about **94.6%** of the time. On a hypothetical $25 bank, theoretical full Kelly spends
about 2.75¢ under those favorable assumptions, not $1; quarter Kelly is about 0.69¢. Known probabilities,
independence and stable fills are unrealistic assumptions here, so this is a warning about scale, not a
sizing prescription. A large win is not evidence to multiply the next stake.

Future scale requires a new frozen evaluation at the proposed size, positive conservative net estimates,
measured depth, acceptable correlated drawdown, and explicit owner-approved dollar ceilings. No automatic
funding, reinvestment, loss recovery or cap increases. Existing live Bitcoin authority does not transfer.

## Evidence required before a live proposal

The first few days establish feed access, clocks, settlement reconstruction, fees and whether offers
survive latency. They cannot prove this rare-event strategy profitable.

Earliest research schedule: **42 complete UTC days**: days 1–21 TRAIN, 22–28 CALIBRATION, 29–35 VAL and
36–42 untouched TEST. Select actual dates and freeze them before recording the evaluated cohort. Purge
positions/labels crossing split boundaries; late settlements retain their original cohort and remain
pending until known. Do not choose dates by market performance or replace losing days with “better data.”

VAL can reject the design. A change to features, gates or exits creates a new version and requires fresh
validation before opening its final test. No live self-modifying strategy. During TEST, daily operations
check coverage and integrity; profit-based decisions wait for the predeclared review date, unless using
a separately specified valid sequential test.

Report every eligible and rejected window; actual simulated entry/exit quantities; no-fill rate; both
fees; executable 1/5/10/30-second price changes after fills; final results; drawdown and losing streaks;
profit concentration; source-to-receipt, decision and order latency distributions; uncertainty and size
capacity. Cluster by window and UTC day; one thousand contracts in one window is one shared outcome.

Pass only if the primary has positive untouched net P&L with a defensible one-sided uncertainty bound,
audited settlement/source/fee accounting and achievable entry **and exit** under conservative latency.
Report sensitivity to the largest win and missing/stale data. Sparse rare-event counts mean **inconclusive**,
even after 42 days. A bootstrap does not create unseen tail events. A seven-day BTC test has at most 672
windows before eligibility filters; demonstrating a modest terminal-tail advantage may need tens of
thousands of independent opportunities and months or longer. See [MATH.md](MATH.md).

Stop pursuing this version if usable index access is absent, quote survival is inadequate, the apparent
edge vanishes after fees, source corrections drive results, or fresh evidence rejects profitability.
Do not weaken fill rules or keep reusing TEST until something passes.

## What is ready and what is not

Ready: verified venue mechanics, bounded public evidence, payout arithmetic, explicit candidate policy,
tests/accounting/architecture requirements and a falsifiable evaluation plan. Unproven: signal accuracy,
the account's index-feed access, actual post-update latency, profitable exits, frequency and scalable size.
No new recorder, model, paper desk or live strategy was deployed in this session.

# Lucas ladder audit: frozen protocol, version lucas-v1

Registered 2026-10-12, before computing any new Kalshi strategy returns. The
earlier scout's public-wallet statistics and current quotes have already been
seen. They are exploratory evidence, not held-out results. Full-wallet inference
is descriptive; it cannot recover private unfilled orders or exact hidden caps.

## Universe, dates and measurement

- Primary universe: every settled monthly market in `KXBTCMAXMON`,
  `KXBTCMINMON`, `KXETHMAXMON`, `KXETHMINMON`, including zero-volume markets,
  for contractual observation months October 2025 through September 2026.
  Assign month from the rule's named observation month in its own timezone;
  an end timestamp falling in the following UTC month does not shift the cohort.
  Store exact source-derived UTC boundaries separately.
  Collect older available months as coverage only. Annual series are inventory
  only, never silently pooled with monthly results.
- TRAIN: October 2025–March 2026 observation months; VAL: April–June 2026;
  TEST: July–September 2026. All assets/strikes within a month belong to the
  same split. Missing months are missing, never zero-return observations.
- Archive full pagination, metadata, rules, settlement, source URLs and receipt
  times. Current and historical endpoints must be reconciled without duplicate
  prints. Preserve any rule changes as separate cohorts; incompatible final
  averages are not one-touch contracts. A market title alone is insufficient.
- Use the actual contract's index, touch statistic, inclusive/strict comparison,
  observation start/end, timezone, settlement and void treatment. Never replace
  these with a raw Coinbase high/low. Unknown prior-touch state or changed rules
  makes execution qualification unknown, not an assumed uncrossed barrier.
  Days left uses the originally scheduled observation-window end, not an early
  close or resolution timestamp discovered after a touch. Include early resolved
  markets in the census; selecting only surviving open ladders leaks outcomes.
- Coinbase BTC/ETH hourly closes are a *spot/volatility proxy*. A candle starting
  at t is usable only at t+3600+5 seconds. Require 721 consecutive hourly closes
  for 720 adjacent 30-day log returns; annualize population standard deviation
  by sqrt(24*365). No filled gaps, future close, or shorter-vol substitution.
  Decisions occur hourly, five seconds after the close. Reject stale/missing
  inputs. MAX requires strike above spot; MIN requires strike below spot.
  z is signed safe-side log distance / (annualized volatility * sqrt(years left)).
  This normal-model feature does not establish the true tail probability.

## Fixed candidates and reporting buckets

24 candidates: z minimum {1.5, 2, 3, 4} × days-left band {[1,7], (7,14],
(14,21]} × fixed NO resting limit {0.97, 0.99}. No optimization outside this
grid after looking at returns. Report observed prices 0.96–0.99 separately,
including the lower-priced opportunities; do not silently change candidate bids.

Descriptive z buckets: [0,1.5), [1.5,2), [2,3), [3,4), [4,infinity).
Days-left buckets: [0,1), [1,7], (7,14], (14,21], (21,31]. Show missing-feature
counts, market/month denominators, sizes and prices per cell, asset and MAX/MIN.
Observed-fill win rates describe those records, not independent trials.

## Execution, fees and capital

- Decisions cannot use the same or a future trade. Fixed placement delay 10s;
  resting bids last at most one hour, then expire before a fresh decision.
  Post-only acceptance needs historical opposing-book evidence. No retroactive
  quoting because a favorable print appeared.
- At-limit prints never establish a queue fill. A correctly oriented NO seller
  printing strictly through our limit after the delay, with at least our size,
  is a **conditional trade-through opportunity**. Without historical accepted
  book/queue evidence it remains conditional, not a fill we certainly received.
  Never turn NO buyers into incoming sells. Unknown direction is excluded.
- Report strict execution-qualified fills separately from conditional print
  opportunities and an explicit no-fill bound. No historical order book means
  the execution-qualified return is unknown, not zero or a profitable result.
- Fixed unit trade: one contract, no adds, maximum one purchase per market,
  maximum three strikes per asset/direction/month ladder, counting both held
  positions and outstanding order reservations. Use $25 simulated
  starting cash, no deposits, and deterministic chronological decision order
  then ticker order. Reserve full bid cost and fees for all working orders;
  release only on verified cancellation/expiry or actual settlement. Settlement
  proceeds cannot be recycled earlier. These are research sizing assumptions,
  not inferred wallet limits or real-money authorization.
- Verify historical maker fee applicability; never assume current zero maker
  fees applied in every month. Also report taker-fee stress with documented
  Direct-account precision/order-level rounding. Fees never become negative;
  unverified rebates are zero. Unknown historic fees stay unqualified, with
  clearly labeled contemporary-fee sensitivity calculations if useful.
- Hold buys through actual Kalshi settlement; settlement result must come from
  Kalshi, not spot reconstruction. Preserve pending/void/revised results and
  unknown payout timing; no fabricated realized return.

## Selection, held-out test and build decision

Select at most one candidate on TRAIN by highest after-fee dollar result, with
ties broken by lower peak cash at risk, then higher z, then lower bid, then
the fixed candidate ID. Selection requires adequate complete data, actual
one-touch eligibility and execution/fee qualification. Report worst month,
monthly returns including zero-trade months, fill/miss counts, maximum capital
locked, drawdown and losses clustered by month, not by correlated ladder strike.

Qualification requires twelve complete, nonempty observed monthly cohorts with
verified universe, rules, feature-period inputs, fee history and execution data.
Distinguish a verified pre-launch/empty series month from a missing archive;
neither invents a populated month of evidence. The cash ledger is continuous:
every TRAIN candidate starts with $25, and the selected candidate's remaining
cash, reservations and unsettled holdings carry into VAL and then TEST unchanged.
There is no stage reset or hypothetical extra deposit. Outstanding bids expire
at the next hourly decision before replacements; the 10-second placement delay
reduces active lifetime. An unfilled market may be requoted in subsequent eligible
hours until its first fill. Quote priority is decision time and ticker, never the
time of a future favorable print.

Run the unchanged selection on VAL only if TRAIN qualifies and is positive.
Run TEST once only if VAL also qualifies and is positive. Save immutable result
artifacts with source/plan hashes and refuse overwritten TEST results. No choosing
another rule after VAL/TEST. A lack of twelve months, missing rules/index history,
unobservable fills, or unverified historical fees is a reported limitation.
Descriptive all-period buckets may be produced when the held-out experiment is
blocked, but must be labeled exploratory and cannot later be reused as untouched
TEST data without a new prospective holdout.

A positive execution-qualified after-fee held-out result supports building the
requested practice-only desk. Conditional tape profitability alone is not proof
of a fillable positive backtest. No profitable result is invented to satisfy the
build condition. Real money requires new owner amounts, regardless of research.

The independent weather measurement uses `WEATHER_PLAN.md`; it does not select
or tune this crypto rule. Report both good and bad findings in `docs/WORKLOG.md`.

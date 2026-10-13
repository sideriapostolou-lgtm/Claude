# Public-wallet behavioral reconstruction

Registered 2026-10-13 18:58 UTC, before new strategy-return fitting. This is descriptive exploration and
hypothesis generation requested by the owner, not TRAIN/VAL/TEST validation or permission for live trading.
Existing public-history and scouting artifacts are known exploratory evidence. Fresh samples will be
labeled by wallet, query, timestamps, filter, pagination coverage and exclusions.

## Questions

1. Which simple algorithms explain dangerously-skip-permissions's buying, sizing, time allocation,
   side imbalance, maker/taker mixture, paired cost and external incentive receipts?
2. Which observations contradict pure pair arbitrage, unconditional momentum, static market making,
   martingale, outcome prediction alone or a universal hard inventory cap?
3. Which mechanisms recur across other crypto, weather, ladder and complete-set wallets? Which have
   materially different rules despite similar-looking profit charts?

## Method and limits

- Read existing full-history audits first. Preserve their unresolved P&L, funding and timing issues.
- Collect bounded recent public trade/activity samples and actual API metadata where useful. Do not
  change a wallet's inferred strategy just to improve a backtest: none is run in this study.
- Analyze complete observed market windows separately from censored boundary windows. Preserve distinct
  identical economic fills when no unique ID can establish duplication; diagnose pagination overlap.
- Describe fill sizes, dollar sizes, time within window, BUY/SELL, both-side quantities/costs and the
  fraction of additions that reduce inventory. Same-block ordering is ambiguous: use batch summaries,
  order-sensitivity ranges or label a statistic conditional on API order.
- Maker/taker attribution needs an explicit provider cohort or role, never a guess from trade direction.
  Wallet/block timestamps are not execution timestamps. Do not align spot at block inclusion and claim
  a causal speed trigger. Do not claim unfilled/canceled orders are observed.
- Distinguish price-times-size from reported purchase cash including fees. Keep deposit, withdrawal,
  settlement, fee, rebate, reward and marked equity meanings separate. No missing field becomes zero.
- Rank hypotheses by explanatory fit to observed facts; give qualitative confidence, competing causes,
  a concrete candidate algorithm and a falsifying observation. Unidentified parameters remain explicit
  proposed choices/ranges, not allegedly discovered constants.
- Do not use a success-only wallet sample to estimate the success rate of these strategies. P&L series
  and long public histories are evidence of reported outcomes, not proof of current attainable returns.
- Future causal identification and profitability validation require a separate preregistered protocol and
  untouched observations. Existing holdouts stay untouched. No orders, auth changes or trading changes.

## Deliverables

An owner-readable comparison and a detailed Skip playbook; a machine-readable evidence summary with
coverage/provenance; and a concise inferred rule card for each comparison wallet. The output should
make specific, useful guesses instead of treating unavailable private code as a reason to stop analysis.

# Evidence, accounting and reproduction

This study answers the owner's request for concrete inferred bot rules. It does not estimate how often
random bots succeed, claim source-code recovery, or validate a deployable strategy. Wallet selection
was informed by earlier profitable-wallet scouts. Selection bias is intentional for mechanism discovery
and invalidates population-wide success-rate conclusions.

## Frozen evidence

`evidence/MANIFEST.json` lists each evidence file's stored-byte and decoded-byte SHA-256 hashes. Files
ending `.json.gz` are ordinary JSON compressed losslessly. Request manifests contain the original
public URLs and receipt timestamps. Public pagination cursors, wallet addresses, contract token IDs
and transaction hashes are not private credentials. No account authentication was used.

- `evidence/skip/`: fixed-period v2 all-fill, taker-only and activity pagination; Gamma market responses;
  original protocol; behavior, price-path and cash summaries; independent accounting output.
- `evidence/crypto_peers/`: latest two 500-row pages per all-fill and taker-only query for five wallets,
  their public daily P&L charts, request manifest and calculated summaries.
- `evidence/weather_ladders/`: latest 500 all-role fills per wallet, taker comparison responses,
  request manifest, weather activity corroboration and derived summaries. This directory also preserves
  an exploratory 500-row ce25 query; the report uses the larger crypto-peer sample for that wallet.

Collection was approximately 18:56–19:02 UTC on October 13. Individual receipt times, not this rounded
range, are authoritative. For Gamma responses the request/receipt metadata are in their envelopes.
Some older scripts and full-history raw archives remain outside this new snapshot. The new evidence
does not claim to replace the full-history audits or their unresolved reconciliation issues.

## Skip selection and roles

The fixed public query covers block timestamps **12:55:00–18:54:59 UTC**: 5,248 all-role fills and
3,724 taker fills. A whole five-minute window at each boundary is removed. The resulting nominal
window opens run 13:00–18:45 inclusive: 70 scheduled, 65 with indexed fills and 5,136 retained fills.
This fixed cursor walk completed, but public-index completion is not independent on-chain completeness.
It also cannot prove absence of pre-query inventory or unindexed off-wallet activity.

All-role and taker-only fills are matched as economic **multisets**, preserving multiplicity. Keys use
timestamp, action, token, condition, size, price and transaction hash. Complement rows are inferred
maker fills; role cannot be assigned individually between indistinguishable equal-economic rows, but
cohort totals retain the correct multiplicity. The retained snapshot contains no repeated economic
identities. Activity TRADE rows match the full all-fill multiset exactly.

The initial exploratory offset pull had overlapping pages and is superseded by this cursor snapshot.
Its raw pages are not the evidence for the final Skip counts. For the comparison wallets, live offset
pagination overlap is explicitly diagnosed: crypto-peer repeats removed across pages are 3 for mo-money,
35 for GoodFallen and 2 for DB5. Within-page multiplicity is preserved. Sampling the all/taker endpoints
is not atomic, and these bounded role estimates are less strong than the fixed Skip cohort.

## Timing and price diagnostics

Public timestamps are block/API times, not exchange execution or local receipt times. Almost 59.15%
of Skip's retained fills share a market timestamp with another fill. Sequential diagnostics therefore
use whole timestamp groups or current singleton groups with strictly earlier comparison groups.
No inferred ordering within a tied group is used to claim a causal Bitcoin signal.

The rise/dip comparison uses the strictly earlier same-side fill-group VWAP, not the market mid or
an independently observed Bitcoin move. Own-fill range versus activity correlations are endogenous:
more fills mechanically observe more of a price path. They are exploratory diagnostics only.

Weather buy/sell cases require the same token, one observed buy followed by one sale in the bounded
sample, and quantities matching within 0.01 shares. The five/six-second median gaps are ledger
timestamp differences. They neither identify exact holding time nor prove immediate reusable cash.
Existing positions, unmatched cases and other expenses prevent treating the selected pair sum as
whole-wallet profitability. The additional activity comparison checks recorded quantities and cash,
not an independent transaction-receipt audit.

## Source-wallet cash accounting

For retained window `w`, use actual recorded purchase cash `C`, shares `q`, price `p`, and recorded
redemption `R`. The calculation is:

```text
gross_purchase = sum(q * p)
purchase_cash = sum(activity.usdc_size for BUY records)
cost_increment = purchase_cash - gross_purchase
gross_result = redemption - gross_purchase
result_after_purchase_costs = redemption - purchase_cash
```

The recorded purchase cash already includes its additional costs. Do not subtract an estimated fee
again. Maker cost increments are zero to source precision; essentially all additional cost is on taker
fills. Independently calculate the winning payout from each finally resolved Gamma market and the
acquired winning quantity; require exact agreement with recorded redemption for every retained window.
All 65 agree. Later rebates and rewards are not allocated to these windows and remain separate.

For an average-cost attribution, with `m = min(q_up, q_down)`:

```text
average_pair_cost = C_up / q_up + C_down / q_down
matched_component = m * (1 - average_pair_cost)
directional_component = total_result - matched_component
```

This is a transparent allocation, not a reconstructed private lot ledger. Individual selected pairs
can have different costs. Aggregate pair prices above $1 exclude a guaranteed profitable whole-window
portfolio on these costs, not every possible private pair-selection rule. The total cash result does
not depend on this component allocation.

Historical dollar figures are re-summed from `research/lab8/skip/HISTORY_daily.csv` and reconciled to
that audit's stated scope. Public P&L charts for comparison wallets are displayed provider series,
not independently reconciled cash returns or estimates of bankroll. Lucas's detailed funding audit
supersedes its initial scouting description.

## Reproduce the central result offline

From the repository root, with Python 3.11 or later:

```bash
python research/wallet_playbooks/audit_skip.py
```

No network or credentials are required. The script verifies raw hashes, frozen queries/cursor chains,
wallet identity, economic multisets, buy-only scope, resolved winners, every redemption, total costs,
maker/taker aggregates and agreement with both frozen accounting implementations. It should report
65 windows, `frozen_comparisons_passed: true`, and `pnl_after_purchase_cash: "-514.740410"`.

The standalone accounting function was also checked on fake winning/losing windows, fees counted
once, missing/wrong redemptions, SELL/unknown activity and excess duplicate taker rows. These checks
test the accounting contract, not whether a strategy makes money. Production pytest and mypy checks
do not establish research profitability either.

## Source interpretation and limits

- Fees and incentives: [official fees](https://docs.polymarket.com/trading/fees) and
  [taker rebate program](https://docs.polymarket.com/programs/taker-rebates). Current documentation
  describes tiers; no tier is imputed to the source wallet without matching its credited income.
- Timestamp/API semantics: [public v2 schema](https://data-api.polymarket.com/v2/openapi.json).
- Historical contracts and source corrections: repository [weather audit](../lab9/WEATHER_WINDOW.md)
  and [Lucas audit](../lab9/LUCAS_RULES.md), with their own preserved evidence and caveats.
- A commercial [seller](https://polymtradebot.com/blog/do-polymarket-bots-work) claims to operate Skip.
  That is an unverified interested-party claim. The public profile snapshot authenticates the wallet's
  name, not the seller's ownership. No seller software was acquired or executed.

Precise private thresholds, canceled orders, unfilled quotes, contemporaneous source feeds, hidden
hedges and causal reaction time are absent. Concrete inferred rules are supplied despite those limits;
their confidence comes from explanatory fit, not from an invented exact-code or forward-profit claim.

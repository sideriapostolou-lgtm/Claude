# Kalshi monthly NO: evidence audit, not a completed strategy backtest

**Verdict: INSUFFICIENT DATA. The condition for building the practice desk has
not passed.** Public trade prices can describe what other traders exchanged;
they do not establish that our resting order was accepted or filled. No live or
practice desk was added, no candidate was selected, and no account was accessed.

Protocol: [LUCAS_PLAN.md](LUCAS_PLAN.md), version `lucas-v1`, frozen SHA-256
`3e39bb96d548b68beb6775dfe22d60710382055bf68adcbc47d1dfcf7c2f5534`.
The requested candidate experiment is **not completed**. The executable
[touch_backtest.py](touch_backtest.py) is deliberately a smaller, offline TRAIN
evidence analyzer. It does not simulate a capital-constrained strategy or treat
public prints as our maker fills. A positive printed-payoff sensitivity cannot
open its practice-build gate.

## Why a profitable, fillable backtest is not established

1. **The requested twelve months do not exist in the returned universe.** Both
   current and historical market endpoints and event pagination were exhausted.
   The first returned monthly markets were issued in January 2026; the requested
   October–December 2025 cohorts contain no returned contracts. January–September
   provides nine nonempty observation months, with no March ETH-MIN event. This
   is evidence about the returned public census, not proof that every possible
   older exchange record is available. Missing months are not zero-profit months.
2. **Archived rules conflict.** Some January MAX contracts describe one trimmed
   average across the entire observation period. Other metadata describes a
   cumulative trimmed average checked every minute. The current terms instead
   describe a separately trimmed within-minute index statistic. Numerous older
   MIN contracts say “below” in their primary rule but “above” in the secondary
   calculation. These are separate cohorts, never silently corrected or pooled
   as verified one-touch contracts. See [KALSHI_TOUCH_DATA.md](KALSHI_TOUCH_DATA.md).
3. **We do not have the actual CF index path or verified prior-touch state.**
   Coinbase closes give a reproducible spot/volatility proxy, not the contract's
   trimmed CF BRTI/ETHUSD_RTI observations. They cannot prove that a strike was
   still eligible for a NO purchase, nor reconstruct the venue's touch outcome.
4. **There is no historical opposing book or queue evidence.** A public trade
   does not prove post-only acceptance, queue priority, size available to us, or
   that a resting bid would fill. At-limit prints never imply a fill. A correctly
   directed, later print strictly through a previously posted limit is only a
   conditional opportunity; no such prospective order/capital simulation is
   claimed in this audit.
5. **Historical fees and publication times remain unverified.** Current series
   metadata and empty fee-change responses do not prove which precision/fee rules
   applied to every historical fill. The fee sensitivity below uses the current
   Direct-account documentation, not invented historical fee bills. Historical
   hourly candles also lack recorded publication times; end-of-hour plus five
   seconds is an explicit assumption.

The public monthly census has 339 unique contracts: 100 BTC-MAX, 93 BTC-MIN,
80 ETH-MAX and 66 ETH-MIN. Of these, 307 belong to completed January–September
observation months: 91 TRAIN, 94 VAL and 122 TEST. October's 32 markets remain
outside the experiment, including any strikes already resolved early. Annual
contracts are inventory only. The module assigns cohort month from the explicit
ET date in the primary rule, cross-checks the scheduled expiration, and retains
an early resolved loser in its original month. It never uses an early actual
close as the originally intended expiry.

## What the TRAIN diagnostic measures

Only October 2025–March 2026 TRAIN prints and outcomes enter these calculations.
**VAL and TEST strategy returns have not been computed; their print files are
not opened by this analyzer.** Full raw metadata was archived for coverage.

For each regular public NO print at 0.96–0.99, the feature timestamp is the
preceding fixed hourly decision: five seconds after the hour. It uses the latest
assumed-published Coinbase close, exactly 721 consecutive closes / 720 adjacent
hourly log returns, and the originally scheduled days remaining. Gaps, stale
latest closes, zero volatility, and strikes on the wrong side of current spot
are excluded and counted. The z statistic is a normal-model distance proxy;
it is not a probability estimate validated for crypto tails or the disputed
contract statistic. See [TOUCH_SPOT_DATA.md](TOUCH_SPOT_DATA.md).

The CSVs separate asset, MAX/MIN, rules cohort, z bucket, days-left bucket and
canonical NO maker/taker direction. The direction means the exposure of the
party on that side of the print; it does not identify our order or whether the
other party opened YES or closed NO. Conflicting/missing canonical direction is
unknown. Block or unknown-block-status prints are excluded.

- `market_win_rate` counts distinct markets observed in that cell. A market can
  occur in several cells; cells must not be summed as independent trials.
- `print_win_rate` weights by print count and can repeatedly count the same
  settled outcome. It is not an independent-trial success rate.
- Printed quantity and size-weighted price are actual tape fields. They are
  **not** a claim that the same quantity was available to our bid.
- Unit payoff sensitivity uses one contract at each observed print of at least
  one contract, with the actual Kalshi YES/NO result. It then averages those
  counterfactual per-print payoffs. It has no portfolio, selection, caps, queue,
  or opportunity-cost model and is **not strategy profit or an achievable ROI**.
- Monthly rows use the contractual observation month and retain months without
  returned markets as missing. The audit never reports a zero return for them.

## TRAIN observations: January contains real NO losses

The completed TRAIN pull contains **96,680 unique public prints across 91 markets**,
including one zero-print market. Of these, **16,675 regular NO prints at 0.96–0.99**
have all required causal spot-proxy inputs and the safe-side sign. Two source
prints outside their recorded trading intervals were excluded. No TRAIN print
in the price band was dropped for missing hourly features. This does not fix
the missing CF path or the rule conflicts.

| Observation month | Census markets | Markets with described prints | NO wins / losses among those markets | Described prints | Mean gross unit payoff at a print | Mean after current taker-fee stress |
|---|---:|---:|---:|---:|---:|---:|
| 2025-10 | 0 returned | — | — | — | unknown | unknown |
| 2025-11 | 0 returned | — | — | — | unknown | unknown |
| 2025-12 | 0 returned | — | — | — | unknown | unknown |
| 2026-01 | 32 | 23 | 19 / 4 | 4,443 | $-0.13452 | $-0.13648 |
| 2026-02 | 35 | 28 | 28 / 0 | 6,631 | $+0.02506 | $+0.02333 |
| 2026-03 | 24 | 19 | 19 / 0 | 5,601 | $+0.02568 | $+0.02391 |

**January is a negative printed-payoff month in this diagnostic.** Its four
losing NO markets were BTC monthly minima at **$77,500, $80,000 and $82,500**,
and the ETH monthly minimum at **$2,500**. Each had NO trades at 0.96 or above
before its actual Kalshi YES settlement. They remain in the census even though
they closed before the originally scheduled month end. Their primary/secondary
rule-direction text is inconsistent, so we do not claim that an index-faithful
far-strike strategy would have selected these exact records.

The bad outcomes are not confined to small model distances. Even the z≥4
printed bucket has negative mean unit payoff after the contemporary stress in
the last-day cell (**−$0.04228 across 1,085 prints**). Its 1–7-day cell averages
+$0.00350 across 2,837 prints. These are correlations in TRAIN tape, not an
optimized rule or a reason to change the frozen candidate grid. No candidate
has been chosen from them. February and March's all-winning observed markets
do not erase January's losses or qualify a strategy.

Detailed artifacts:

- [KALSHI_cells.csv](KALSHI_cells.csv): **156 nonempty cells**, with every required
  z × days-left bucket represented, separated by asset, direction, rule cohort
  and NO tape role. Cells without observations are absent, not zero-return cells.
- [KALSHI_months.csv](KALSHI_months.csv): all six requested TRAIN months, including
  the three months with no returned contracts.
- [KALSHI_coverage.csv](KALSHI_coverage.csv): all 12 requested months × four series,
  including VAL/TEST metadata coverage without evaluating their outcomes.
- [KALSHI_train_markets.csv](KALSHI_train_markets.csv): all 91 consumed TRAIN
  markets, their actual outcomes and scheduled versus actual close timestamps,
  with zero-observation markets preserved.
- [KALSHI_AUDIT.json](KALSHI_AUDIT.json): frozen plan/analyzer/input/artifact
  checksums, exclusions, and explicit false build/selection flags.

The complete four-series acquisition exhausted 309 finalized-market tapes and
returned **337,889 unique prints**, collapsing 9,168 identical current/archive
duplicates. It is not proven complete economic volume: three **June** tapes have
quantity totals below their metadata volume, documented in KALSHI_TOUCH_DATA.md.
Those June outcomes were not evaluated here. Cursor exhaustion is not a claim
that every historical exchange transaction is present.


## Fee and tail-loss sensitivity

The current Direct-account documentation first rounds model fees upward to
$0.000001, then aligns the balance debit to $0.0001. For one whole contract in
one fill, using the current quadratic taker coefficient 0.07:

| NO price | Current one-fill fee | Win after fee | Loss after fee | Wins needed to offset one loss |
|---|---:|---:|---:|---:|
| $0.96 | $0.0027 | $0.0373 | -$0.9627 | 25.81 |
| $0.97 | $0.0021 | $0.0279 | -$0.9721 | 34.84 |
| $0.98 | $0.0014 | $0.0186 | -$0.9814 | 52.76 |
| $0.99 | $0.0007 | $0.0093 | -$0.9907 | 106.53 |

These are arithmetic sensitivities, **not historical after-fee returns**.
Historical account membership, fee rules, fills split across an order and
rounding-accumulator rebates were not reconstructed. Current series metadata
indicates no maker fee under its standard quadratic fee type; zero historical
maker cost has not been proven. Even with literally zero fees, a $0.99 losing
NO costs 99 winning $0.99 NOs. Several far strikes can lose together in one
crypto move, so 200 correlated strike wins do not imply 200 independent trials.

No-fill scenario: an account that places no filled orders earns $0 and retains
its starting cash. This is an explicit scenario, **not** an observed fill bound
that makes an unqualified strategy safe or profitable. Both the executable
strategy return and the conditional capital-constrained strategy return remain
unknown. Maximum capital locked, drawdown and the worst strategy month are also
unknown; a per-print sensitivity cannot supply them.

## Reproduction and next evidence needed

The collector, rules/fee sources and raw page/trade hashes are described in
[KALSHI_TOUCH_DATA.md](KALSHI_TOUCH_DATA.md). Public raw captures stay outside
Git; the checked-in CSVs are small aggregate observations, not trading signals.
Run from the repository root after collection finishes:

```bash
python -m research.lab9.touch_backtest \
  --archive /tmp/lab9-kalshi-touch \
  --spot-root /tmp/lab9-lucas/candles \
  --output /tmp/lab9-touch-analysis
```

This command checks the frozen plan hash, each consumed TRAIN trade file's
checksum/count/identity/order, and never reads VAL/TEST trade files. It records
source and analyzer hashes in `summary.json`. It cannot promote a rule. Tests
use fake local archives and cover early resolved losses, causal feature timing,
missing data, held-out file isolation, decimal fees, tape roles and the closed
build gate.

To proceed, obtain authoritative clarification of each historical rule cohort,
the relevant CF index history, historical book/queue or prospective accepted
order evidence, and historical fee treatment. If the historical evidence cannot
be obtained, the defensible alternative is a separately approved **read-only
forward data recorder**, followed by a new preregistered prospective experiment.
That is not the requested profitable-backtest gate being declared passed. New
real-money amounts would still be required before any trading activation.

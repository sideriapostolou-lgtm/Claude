# Entry and hedge completion correction

Recorded October16,2026,1:14:55PM PDT during implementation, before any new-policy deployment or production outcomes. Owner explicitly requested a fix after the loss diagnosis. Base application is e72f4b8b; working source base530f8a6 includes only subsequent records. This changes order selection inside existing limits; it does not establish a profitable strategy.

## Problem and selected scope

The current model can take an initial directional position without visible executable hedge liquidity, discard a hedge because its sole proposed price breaches the pair cap, and wait until late in the window to take a profitable pair completion that does not meet standalone model edge. Thirty balanced settled windows net+$3.2539 versus nine unequal−$9.3328 in the prior bounded diagnosis. Those retrospective allocations motivate the scope; they are not the P&L of this untested candidate.

The authorized correction has three parts:

1. Start with the ordinary model-derived entry candidate and only lower price or quantity. Require visible opposite ask depth sufficient for the proposed quantity, including conservative rounded first-leg and taker hedge fees, within the unchanged pair cap. Recheck at submission and cancel outstanding risk-increasing starter quantity if the coverage disappears. Subtract reflected own liquidity; keep liabilities until confirmed reconciliation. Displayed depth is not a guaranteed hedge fill.
2. Prioritize an early IOC that strictly balances actual confirmed inventory and completes pairs inside the existing fee-inclusive cap. Preserve ordinary cash, clip, window and open-exposure budgets, freshness, account reconciliation, mode, ownership and transport checks. Pending/cancel-uncertain orders cannot be treated as free capacity. Explicitly identify this completion order and permit an edge exemption only for that cost-capped, risk-reducing classification. Do not reuse late-lock budget exemptions.
3. When a strictly balancing maker candidate fails solely because of pair cost, try lower cent prices at the same quantity using unchanged risk/fee checks. Keep queue position when fair rises but the admissible capped price cannot improve. Preserve adverse-fair, pull, stale-feed, close, uncertainty and stop behavior. Any exclusion used for replacement evaluation must be read-only and cannot release live reservations.

The late-lock fallback, financial limits and prior stopped/loss history are retained. No financial reset, Railway variable edit, transfer, new live desk, sealed FamilyA TEST, threshold sweep or model retraining is authorized by this implementation.

## Verification before release

Fake-account integration tests must reproduce the original rejected-but-admissible cheaper hedge, a normal-edge-rejected profitable early completion, and starter admission with absent/expensive/thin/own-only opposite liquidity. Test partial fills, cancellations and unreconciled liabilities, rounding boundaries, adverse changing prices/depth before transport, startup/restart restoration, practice copy separation, all budget gates and stale/mode/shutdown/pull protections. Counterexamples must retain missed trades and cannot assume replacement fills.

Run focused tests, the full suite, mypy and changed-file Ruff. Have an independent reviewer inspect the exact final patch and run adversarial checks. Record performance impact of bounded searches without scanning or copying complete ledger history in each decision. A passed synthetic test means the invariant is implemented, not that trading is profitable.

## Release and live verification

Use standing owner approval only after checks pass and in safe merge minutes. Fetch the deploy branch, preserve concurrent records, create a real-money-labeled PR, verify the exact running commit and healthy startup. Compare native pre/post loss totals, caps, mode, reserves and used stop controls; attribute any intervening fills/settlements instead of demanding unchanged money snapshots. Do not reset them.

Bounded runtime acceptance requires the new policy identity and either an actual guarded decision/refusal or clearly labeled absence of an eligible opportunity. Accepted orders are not fills. Do not place a trade merely to produce a test. Preserve any failure or new exposure, and do not call the complete profitability task done on startup evidence.

For a later profit assessment, freeze source/settings and a prospective cohort before looking at outcomes; include all started, stopped, rejected and zero-fill windows, current markout/queue coverage, actual fees and final settlements. This release's immediate runtime check is not that statistical validation. A required setting/source change invalidates the corresponding comparison rather than selecting a favorable substitute interval.

# Capped hedge quotes: a demonstrated mechanism, an unproved strategy

**Status: synthetic proof only. No strategy code, production order policy, activation, research gate or statistical error allocation changed.** The existing execution-work priority and unopened holdouts remain intact.

The current controller chooses a maker price from fair value minus its existing edge, then asks the risk book to admit it. When that price breaches the 99¢ pair-cost cap, the controller can skip the hedge instead of trying a cheaper quote. The candidate would search lower ticks only for an order that strictly balances confirmed inventory and fails solely at that cap. It would retain the same size and every existing fee, reservation, cash, inventory, freshness and stop check.

This is a strategy hypothesis, not a claim that the cap is defective. A cheaper hedge may remain unfilled while the first leg loses.

## What the exact-source fixture proves

The fake-only fixture uses source pinned to `0818f9c10bf6952a563be3a7bd20c30b94e00e7d`. Its three copied source files match the connected GitHub tree's blob hashes. Root independently reproduced the result JSON.

| Synthetic state | Existing proposed quote | Lower same-size quote |
|---|---|---|
| Down5 filled at57¢; Up fair65¢; zero maker fee | Up5 at62¢ fails `pair_cap` | Up5 at42¢ passes the unchanged risk book |
| Down3of5 filled at57¢; two Down contracts still reserved | Up3 at62¢ fails `pair_cap` | Up3 at42¢ passes with reservations retained |
| Same full/partial states, maker coefficient0.0175 and actual synthetic fee0.5¢ per filled share | Up5/3 at62¢ fails `pair_cap` after its edge check passes | Up5/3 at40¢ passes; conservative reserved unit cost is41¢ |

The nonzero-fee cases explicitly use fair65¢ at price selection and fresh fair67¢ at admission. With fair unchanged at65¢, the existing fee-adjusted edge check fails **before** the pair-cap check; the proposed search stays inactive. Fees cannot be ignored to manufacture an eligible opportunity.

All cases use synthetic cash$30, a900-second window, existing$10/window,$20open,$6day,$10total limits and clip5. Exact initial states and evaluated ticks are in the result file. Empty inventory still follows unchanged `starter_fit`. Ordinary buys still stop240seconds before close. The unchanged late-lock rule permits an80¢ hedge against that inventory and refuses98¢ against its97¢ ceiling.

The exact extracted `_send_guard` body accepts the admitted quote under declared healthy fake inputs and refuses invalid/adverse fair, health refusals, a post-only cross, missing maker evidence and a pull. **The underlying production health predicates are fake inputs in this fixture, not a full controller/transport integration test.** Low cash, low window/open budgets and an existing same-side reservation remain blockers.

Search enumerates descending ticks and reuses exact guards; it does not invert a price-only formula or assume binary-search monotonicity. All99ticks in each of four fixed inventory cases and eight fee-coefficient/precision combinations were checked. Their monotonicity does not establish behavior while inventory, fair, time or fee semantics change. Send-time revalidation remains necessary.

## Separate actual window: small gain with directional loss

The coordinating capture independently reconciled the October15 **5:00–5:15PM PDT** window: seven prepatch fills, Up10/Down11, cost$9.98, fees$0, official YES payout$10. Its decomposition is **+$0.509090909 locked −$0.489090909 directional = +$0.02 total**. The native settlement receipt is5:15:09PM; the official keyless result was checked at5:15:13PM.

This is a separate actual result, not PR67 performance attribution or a counterfactual test. Only2¢ of ordinary window budget remained. The proposed pair-cap-only search may have been inactive because `window_budget` blocks first. We do not claim a cheaper quote would have changed this window, and do not add this single-window decomposition to a differently scoped scorecard.

## What remains unanswered

We have no measured eligible-opportunity frequency, quote survival, queue position, additional fills or alternative-strategy P&L. A completed cheap pair in hindsight is not an entry signal. Real fill receipts and healthy recorder metadata cannot supply the missing opposite-book counterfactual.

Any later evaluation needs causally received books/deltas, correctly sided deduplicated prints, valid clocks/sequence coverage, dated fee terms, original order/cancel timing, confirmed inventory and official outcomes. It must retain queue ahead, partial fills, cancel-race exposure and post-delay price/depth checks. Unidentifiable fills remain unknown. Compare independent current-policy, candidate and no-trade ledgers after fees and attributable cost; a less-negative candidate is not profitable.

The existing original/inverse comparison remains unstarted. This note changes none of its gates, dates, error allocation or activation requirements, and does not open Family A or toxicity TEST data. Root must resolve sequencing and register any separate future evaluation before implementation or activation. No new profitable strategy is established here.

## Reproduction and provenance

The published fixture is a text artifact, `opportunity_fixture.py.txt`, rather than an installed application module. From a checkout containing commit `0818f9c10bf6952a563be3a7bd20c30b94e00e7d`, copy that artifact into a separate scratch directory alongside `OPPORTUNITY_RESULTS.json` and `SOURCE_PROVENANCE.json`, create an empty `frozen/__init__.py`, and use `git show <commit>:src/nightcrawler/<file>` to save each of `speeddesk_live.py`, `speeddesk_live_model.py` and `speeddesk_model.py` under `frozen/`. Verify the hashes below, then run `python opportunity_fixture.py.txt > actual.json` with Python3.12+. Compare parsed `actual.json` with the saved result. Do not import or start the application. The fixture prints deterministic synthetic results and imports no network client. The initial fixture attempt lacked a required fake book sequence; that harness error was corrected before the final passing result.

PR67 changes only practice-report input preparation; these three live/risk/model files remain byte-identical in deployed source `0520f7468174d6a37f0ee7dfe64284b1a6921439`. This observation does not make the hypothetical search part of that deployment.

| Artifact | SHA-256 |
|---|---|
| `opportunity_fixture.py` | `e0e8a3d902584ce164981b44aa23ef510904615af4486bc264a4682bf797b24d` |
| `OPPORTUNITY_RESULTS.json` | `eda03069370ae5689907c2e19f4df0ca5b50b4a02b14a2eeed3240d51beb72a1` |
| `SOURCE_PROVENANCE.json` | `f3bc755c87f885197268de0daeded63e31b29ac2f63630f37ba190642768ec4c` |
| `frozen/speeddesk_live.py` | `2471adff4eca63ee6abba73031da75793ae5e1b3cb0468e30e1e2d6b9934efd5` |
| `frozen/speeddesk_live_model.py` | `689207e3a681b591f64a43f03a359d2dc0dbe424cbc2f74809669866ffab36de` |
| `frozen/speeddesk_model.py` | `50ba3b4f78c6efd031fdcd8bb1cb1a59ea2988973c341b9ad275345d70de7429` |

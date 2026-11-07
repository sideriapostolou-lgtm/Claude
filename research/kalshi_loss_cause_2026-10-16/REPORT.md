# Biggest current loss source: unmatched first-leg exposure

Evidence cutoff: **October 16, 2026, 12:20:25 PM PDT** (19:20:25 UTC native status). Historical log queries end at19:22UTC. This is a retrospective actual-money diagnosis, not a new strategy test. No production or financial settings changed.

**The largest demonstrated leak is buying the first side, failing to fill the opposite side cheaply, and retaining the losing exposure through settlement. Small paired gains are outweighed by these directional losses.** The remaining causal question is why the first-leg model and hedge execution select these exposures; this review does not prove a profitable replacement or that every such entry should have been skipped.

## Current actual receipts

All42 observed settlement events for the current UTC day reconcile to119 unique day fill receipts and the native status counters. Three settlements contain no shares;116 fills belong to39 settled traded windows, and3 fills belong to the still-unsettled15:30ET window. That open window is excluded from settled P&L even though balanced contracts can receive earlier paired credits. Do not infer unbooked profit or no exposure from the venue positions counter alone.

| Observed actual settled accounting | Amount |
|---|---:|
| Gross settlement payout | $172.0000 |
| Contract purchase cost | $177.6808 |
| Fees | $0.3981 |
| Net trading P&L | **−$6.0789** |
| Matched/locked accounting component, including allocated fees | **+$4.993183** |
| Residual directional accounting component | **−$11.072083** |

The components add to net P&L; fees are already included and must not be subtracted again. Matched and directional components are accounting allocations, not separately executable strategies. Removing fees arithmetically still leaves−$5.6808.

An independent partition reaches the same conclusion:30 nonempty equal-inventory settlements net+$3.2539;9 unequal-inventory settlements net−$9.3328, with zero fees on those unequal windows. Three zero-share settlements add$0. Equal inventory alone does not guarantee profit:8 of the30 equal windows lost. The currently reported cumulative book also points the same way: matched+$8.673132, directional−$34.243832, total−$25.5707. Cumulative figures are a reported book snapshot, not a fresh full-account-history reconstruction.

The full UTC day is still open and spans earlier app versions and changing limits. Since8AM PDT,17 observed settlements net−$0.9512, split+$4.2416 matched and−$5.1928 directional. This time subset includes different sources/caps and is not a randomized before/after estimate. Current deployed app is `e72f4b8b86dc812ab333a45d54151ae44f8c713f`, deployment `a717faa1-3c47-4a62-9b74-277da85b0fc6`, SUCCESS11:50:25.620AM PDT. PR74 changed town presentation, not the entry/hedging rules. Reviewed trading files are identical to those at current source head`1a061bed`.

## Three fresh examples establish that the leak persists

| Window ends, Pacific | Actual first and only fill | Opposite-side filled quantity | Result after fees |
|---|---|---:|---:|
| October16,10:15AM | Up5 at33¢ | 0 | −$1.65 |
| October16,10:45AM | Down5 at35¢ | 0 | −$1.75 |
| October16,11:00AM | Up4 at36¢ | 0 | −$1.44 |
| Total | 14 contracts | 0 | **−$4.84** |

Tickers are respectively`KXBTC15M-26OCT161315-15`, `KXBTC15M-26OCT161345-45`, `KXBTC15M-26OCT161400-00`. Each has one exact client-ID durable intent, one acknowledged matching venue order, one actual maker fill, and a final zero winning-side payout. Fees are$0 throughout. This is selection of examples after seeing losses; the full day table above retains the wins and all observed losses.

The bot did try the other side: the bounded order captures include37,18 and29 opposite-side durable intents respectively. Intents and acknowledgements are not fills. Selected late status snapshots show`pair_cap` before the lock period; target-specific lock events then show`lock_price` and`no_ask` (plus intermittent stale-book notes for the last example). These are the controller's observations, not a complete external order-book record or proof that no cheaper liquidity ever existed.

The three initial orders were acknowledged in about91ms,40ms and66ms; accepted Coinbase input ages at decision were about66ms,47ms and77ms. The evidence does not identify slow initial sending as the primary cause of these three losses. Waiting in a maker queue and cancellation timing can still matter. Current-session markout telemetry reports5 fills and15 missing horizons, so it cannot establish adverse selection or a causal speed/P&L effect. We do not fill those gaps with simulated successful exits.

## Deployed mechanism

1. `speeddesk_model.py:220` computes a normal-CDF price proxy from spot, opening price, volatility and time. `speeddesk_live.py:2547` quotes against that estimate. A positive model-minus-price difference is not demonstrated predictive edge.
2. `speeddesk_live_model.py:607` sizes the initial buy to leave financial room for a hypothetical hedge. It checks budget and risk; it does not guarantee executable liquidity for the other side. The guard deliberately permits a sequential first side (`:567`).
3. Ordinary opposite-side orders must respect the all-in99¢ pair cap (`speeddesk_live_model.py:599`). The candidate loop changes size at the selected fair-based price; it does not search all lower hedge prices (`speeddesk_live.py:2618`). A cheaper permissible bid could still remain unfilled.
4. In the last4minutes, the lock path may buy the missing side up to97¢ (`speeddesk_live.py:2333`). A late hedge can reduce maximum loss without making the whole pair profitable. Above the allowed price or with no usable ask, exposure remains.

The prior bug that reopened profitable completed pairs already has protection. These three recent losses never formed a pair, so that protection cannot solve them. Increasing size multiplies this unresolved exposure; the receipts do not establish that a larger budget would produce a profitable fill.

## Historical confirmation and correction

The independently rechecked October15UTC cohort contains302 fills and71 settlements: matched+$4.501151, directional−$9.545851, net−$5.0447 after$0.8455 fees. Among69 day-filled windows,45 winners earned$24.4509 and24 losers lost$29.5056; the average loss was2.26 times the average win. The inherited+$0.01 pair is separate.

An old prose count in`research/kalshi_reconcile_pass_2026-10-16/OCT15_COHORT_REVIEW.md` says43 balanced windows/14 balanced losers. Direct native-record reconstruction and its existing JSON give**57 balanced/17 balanced losers** among the69 filled windows. The original file is retained; this is an explicit correction, not a financial-total revision. Historical native checks and current independent review are in`HISTORY_INDEPENDENT_REVIEW.md`.

Do not interpret negative aggregate attribution to late lock purchases as evidence to remove locks. In the earlier three worst paired losses, the initial losing-side principal lost$3/$2.45/$2.30; the late winning-side legs added+$0.2333/+$0.1538/+$0.1585 and reduced those losses. A no-lock policy has not been validated.

## Highest-value next evidence step

Focus the existing entry/hedge work on **whether the first leg merits exposure before the second leg is filled**. Preserve a fixed policy and prospective interval, exact first-fill decisions, hedge attempts/cancels, real queue/book coverage and missing fixed-horizon markouts. Compare any proposed entry gate or hedge-price rule in shadow with conservative, evidenced fills; retain missed paired wins and all losses. Require independent out-of-sample evidence before describing it as a profit improvement. Existing observed-only learner or practice success cannot substitute for real fill fidelity. Do not consume the separate sealed FamilyA TEST.

This diagnostic task is complete. Profitable strategy selection, complete opportunity/queue coverage, town acceptance and the operating takeover remain open on their existing records. No live rule, limits, stops, resume budget, orders, variables or deployments were changed.

## Reproduction and limitations

Run`python research/kalshi_loss_cause_2026-10-16/audit.py`:960 checks pass, including every observed settlement's cost/fees/shares/payout, accounting decomposition, uniqueness, the native counter match, and exact order joins for the three examples. `AUDIT.json` retains calculations and input hashes; original standalone messages are saved in`settlements.json`,`fills.json`,`orders_1700.json`,`orders_1730.json`. Status/late-tail files explicitly contain projections, not full original wrappers. None of the bounded queries hit its provider limit. The initial settlement phrase also matched75 embedded/other rows; these were excluded by exact event-header parsing and are not additional settlements.

Provider search completeness and raw-volume/account history were not independently certified. The scorecard remains partial:24 complete windows of78 eligible,54 gaps; its narrower−$0.6144 figure is not the same population as the reconciled42 settlements. Practice is excluded from every financial total in this report. No policy threshold fitting, alternative-fill backtest, sealed TEST, credential-value access or production mutation occurred.

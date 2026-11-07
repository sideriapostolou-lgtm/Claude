# Independent next-action and sizing review

**Best bounded action now: build one offline, actual-first-fill cohort audit from the already captured post-PR69 windows, then use the existing frozen natural-order cohort to test its missing-evidence questions. Do not change the entry rule or increase size on the present evidence.** No objective first-entry policy bug was established by this review. If Sol independently reproduces a reconciliation/execution defect, a narrowly equivalent correction can be assessed separately; faster accounting is not itself profitable-edge evidence.

Reviewed source base `d1ee16f728612275fedb0d08846e127b0ad9b88d` in the isolated profit-next worktree; AGENTS/MODEL_WORKFLOW/newest coordination/worklog, prior-loss/twin/hedge-quote/own-queue reports, first-entry sizing/admission/send guards and markout clock semantics. Reviewer is the existing requested Astra/high role; actual runtime model identity is not independently exposed. No application-source, production, credential, private-volume, account-client, FamilyA TEST or financial-setting access/change. Current07:19 financial values are parent-supplied latest native findings, not a new independent production fetch here.

## Why this action, rather than a new entry threshold

The reported cumulative decomposition +$4.4315 locked and −$29.0510 directional correctly focuses attention on unmatched exposure. It is an allocation of final inventory P&L, not two independently tradable strategies or proof an early hedge would make money. The selected Up2@48c/lateDown2@90c case lost77.26c afterfees; its late hedge improved worst loss18.74c. The unmatchedDown1@44c lost44c. Neither ever reached the positive full-pair condition fixed in PR69. Removing the hedge would increase worst-case loss in that example; lowering a late lock ceiling can also leave more exposure unmatched.

The capped-cheaper-maker-hedge idea remains a synthetic opportunity demonstration. A lower accepted limit price is not evidence of a fill. The original first buy may still lose while the hedge sits behind a queue. The practice model currently has demonstrated real/practice disagreement and missing first-entry markout coverage, so its zero fills cannot establish safety or rank strategies. The observe-only learner's current evidence does not establish profitable conditional maker-fill pricing either. No live automatic learning/promotion or model replacement follows.

An actual-first-fill audit should produce one row per eligible window, with nested actual fills keyed by exact client/order/fill IDs. Use a fixed calendar interval covering all already captured post-PR69 entries, including wins, losses, empty/stopped windows and inherited-boundary exposure separately; root should name the exact interval before extraction. This is already observed DEVELOPMENT evidence, never a newly claimed holdout. Restrict denominator to genuinely known inventory chronology: if the opening position or early fills are absent, label first-entry role unknown. Do not infer role from publication order.

For each first actual maker fill, join its original intent's price, size and fair **only where the original exposes them**, original local decision/ack/cancel times, venue fill time, and local fills-batch-return time. Record initial unilateral paid principal, actual fee, ordinary versus lock role, partial quantities, eventual opposite fills, matched/unmatched settlement and native gap/refusal context. Include filled-after-cancel-request cases as possible liabilities; cancel request is not cancellation proof. Report both window-weighted and contract-weighted results; multiple fills in one market are correlated, not independent experiments.

The immediately useful output is a coverage table: of actual first-entry fills, how many have valid1/5/30-second markouts, missing/stale/before-horizon/gap states, and exact decision-fair/queue joins? Existing markouts start at **fills-batch return**, not venue execution. A delayed or missing first-fill markout cannot measure immediate adverse selection. Its exit quote is isolated hypothetical depth, not actual sale liquidity for all inventory, and its conservative own-depth subtraction may omit genuine available depth. Report these bounds; do not rewrite those observations to a more favorable clock.

This audit can distinguish a genuinely repeatable stale-input/late-cancel failure from missing evidence or adverse selection conditional on maker fill. It cannot reconstruct every quote or invent alternative executions. If it produces a deterministic guard/identity/clock violation, isolate that exact violation and test it. If it only suggests a new price/time/volatility entry filter, freeze one candidate and its metrics for a separate future paper/shadow assessment; retain all forgone winners, unmatched losses and unknown fills, with no live promotion or guarantee. No thresholds should be fitted to the two losing examples.

The existing declared October16,5–6PM PDT/tail6:02 four-window own-queue cohort stays intact. It can provide natural identity/queue/coverage evidence, but four windows are not sufficient profitability validation. Do not silently move its hours, manufacture orders or reset stops. Any new source/settings change must be explicitly handled under its invalidation rule. No FamilyA TRAIN/VAL/TEST read is needed for this actual-execution audit, and its results must not be relabeled as that protocol's validation.

## What current sizing actually permits

`_decide` initially caps whole contracts by clip and, for an empty window, `floor(window_budget/pair_cap)`. `starter_fit` then searches downwards. It requires the first side **plus a conservative opposing hedge reserve** to fit strictly below both remaining day and lifetime loss room, including existing exposure. `_buy_verdict` additionally checks cash/freshness, window/open budgets, pending orders, inventory, fees and stops. A dollar cap is a ceiling, not an instruction to spend that amount. The late strictly balancing path is a separate risk-reducing exception, not permission for fresh exposure.

Crucial fee detail: at first maker price48c, opposing cap price51c, maker coefficient0/taker0.07/direct precision0.0001, reserve_unit_cost allows every0.01-contract fill partition. The first side reserves48c, the hedge **53c**, hence **$1.01 per starter-and-hedge**. It does not reserve only99c or the smooth unrounded taker fee. This conservatism protects real money and is not a bug to remove for larger sizing.

`sizing_mechanism.py` reproduces seven pure fake-book scenarios and all98 permitted one-cent first prices. The calculation assumes no pending/open risk, fresh cash, and an entirely unused$10 lifetime allowance. **Actual current lifetime anchor/remaining allowance was not audited**, so these are optimistic sizing illustrations, not exact live forecasts or authority.

| Illustration at48c first price | Largest admitted starter |
|---|---:|
| Current$5.1277 day loss,$6 stop,clip5,cash$25.1219 | 0 |
| Same stopped state with hypothetical cash$250 | 0 |
| Day loss$3.9851,otherwise illustrative fresh lifetime room | 1 |
| Day loss$3.9251,otherwise same | 2 |
| Fresh day/lifetime room,existing clip5/day6 | 5 |
| Hypothetical clip10 alone,fresh day/lifetime room/day6 | 5 |
| Hypothetical clip10/day12,fresh hard lifetime allowance10 | 9 |

The current day has only$0.8723 remaining, below the98c entry-floor latch. Deposits or clip/window increases do not clear that latch. Under the illustrated fee model, **every** tested1–98c initial maker price reserves at least$1 per capped pair; strict comparison with the hard$10 lifetime allowance prevents10 starters even at prices where the reserve is exactly$1. At common central prices10 would need more than$10.10 remaining allowance. The source independently clamps total allowance to$10, so setting a larger value alone does not make that possible. Raising/removing that safeguard is outside this task and not recommended here.

For cash alone, two hypothetical capped pairs need up to$1.98 principal before fees; five need$4.95; ten need$9.90. The current$25.1219 cash is not the obvious obstacle to those isolated principal amounts. Larger size also needs opposite liquidity and successful fills; neither can be bought into existence by depositing money. Cash is not trading P&L or remaining stop room.

If the owner later supplies exact instructions, the concrete choices to explain are (a) retain clip5 and existing caps while the present stop naturally governs, (b) an explicitly smaller contract target such as2 or5 with the same safeguards, recognizing these are already within clip5 but remaining budgets can reduce actual size, or (c) a specified larger contract/cap/stop proposal requiring separate money-sensitive design because the existing hard lifetime bound limits it. These are explanations, **not approvals or configuration recommendations**. Ten times a recent one-contract fill means10contracts/side, whereas ten times configuredclip5 means50, exceeding the source's hardclip25 as well. Neither means10×profit. No specific larger amount has been authorized in the owner's current wording.

## Deliverable and stopping rule

Deliver a compact exact-ID first-fill/markout coverage table and preserved all-window arithmetic; identify one concrete reproducible violation if present, otherwise report the specific missing causal evidence. Keep daily/lifetime stops, quantities, protective pair latch and late risk-reducing hedges unchanged. This is an executable research step using existing evidence, not a new architecture, another collector or a claim that a policy change is ready. Root owns any later source scope, required independent exact review and tested release.

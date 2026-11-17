# Reuse active membership during settlement, October 16, 2026

This is a small performance correction, not a profitable strategy. The latest verified Kalshi status is daily-stop PRACTICE with configured mode live. No limit, clip, variable, stop, resume allowance or trading rule changes in this task.

## Change and evidence

The controller rebuilt its active-order list once for each finalized historical window during one synchronous settlement pass. It now captures the active windows once, immediately after unsent-order release. No await occurs within that pass. The existing helper, full account reads, old terminal-fill corrections, settlement checks, error handling and financial state remain authoritative. Membership is never cached across reads or reconciliations.

In the synthetic seven-day integrity-fallback fixture, reconciliation measured 172.147 ms before and 62.981 ms with the proposed mechanism. Normal 21-day history measured 207.734 versus 192.167 ms; fresh history was 0.091 ms slower, and earlier small-history timings were noisy/adverse. The deterministic reduction in repeated list construction is stronger evidence than these timings. This does not resolve multi-second production account reads or demonstrate better fills or profits.

Thirteen selected emitted full-scan traces from October 16, 12:07–12:22 AM PDT (07:07–07:22 UTC) measured 3.098–5.066 seconds, median 3.785 seconds. Each returned 8,056 rows on each of two order reads and 917 account fill rows. These are selected slow reports, not an all-cycle latency distribution or 917 bot-owned fills. Callback work overlaps reads; nested spans are not additive. No claim that all read elapsed time is network time or removable CPU follows.

## Frozen source and checks

Base: `d1ee16f728612275fedb0d08846e127b0ad9b88d`, application PR70 `5b2fb163ac701042dcf93a5b14c61e7cd1bddef1`. Coordination reservation: `3ced64366e4fb88bda50b6abf4bd2486363343f2`.

Complete two-file patch SHA256: `367397773be56b752d72cc84c06fd86484da5079095d39cb41e04fcefaad64ee`.

- `src/nightcrawler/speeddesk_live.py`: `3968b78a5fcb8bcdf40415d811cbf0947b2e64fe5750afee74de06eb2cae46bd`.
- `tests/test_speeddesk_live_settlement_pass.py`: `96e4a0e14536505b5091fd0d43003be79c209572b4ef4b97384db3c1ecf0dfc6`.
- Focused: 214 passed in 33.70 seconds. Mypy: all 132 source files clean. Ruff: both changed Python files clean.
- Ten new fake cases cover bounded historical/integrity work, multiple settlements including a loss and fees, four unresolved-liability forms, same-pass unsent release, changed old fill fees and payout-error abort. Reconstructing the original method makes the two bounded-work regressions fail; the other eight safety cases pass.
- Full pytest: **6,173 passed / 14 existing skips**, 308.42 seconds. Independent exact-patch review: **30 passed**, including eight independently written differential/structural cases. Source hashes match. Exact release and actual restart-retention verification are recorded below; a tested patch alone was not treated as runtime completion.

The first test attempt had an incorrect no-cancel assertion under an existing integrity stop; the fixture now explicitly expects its two existing cleanup cancels. Initial profiling had an incorrect field name and unequal unnormalized receipt hashes; original failures are retained. Final financial/order/practice/archive comparisons match, while two diagnostic receipt types containing random sessions/performance clocks are explicitly excluded. No full-receipt byte-equivalence or production-speed guarantee is claimed.

## Actual money and sizing

Native status published October 16, **12:19:18 AM PDT** reports **$25.1219 cash**, cumulative settled trading P&L **−$24.6195**, split **+$4.431532 locked / −$29.051032 directional**; current UTC-day P&L **−$5.1277**, reported exposure/reservations/orders/positions zero. Cash is not trading profit. The daily stop is latched and total stop is not; existing limits remain **$10/window, $20 open, $6 daily loss, $10 total-loss allowance, clip 5, rung 0**. These are selected status fields, not raw-ledger or complete account certification.

The remaining daily loss room is smaller than the current minimum starter reserve, so cash and a larger maximum clip would not make a new starter eligible. Conservative hedging and rounded fees also constrain actual size. The owner's request to size up has no exact new selected amount yet; the explicit sizing question remains pending. No reset, resume or increase follows from deploying this correction.

## Entry audit and remaining work

The earlier 912-fill and 203-window counters were cumulative summaries, not complete joined original records. A separate fixed retrospective audit captures original standalone order/fill/settlement logs for the completed October 15 UTC day, including all returned losses and split query saturation. Per-order fair can be joined by exact IDs only where the original intent exists. Missing spot, volatility, markouts, logging continuity or source attribution must stay missing. This exploratory audit does not open Family A TEST, validate a counterfactual fill or promote a trading threshold.

The [successor future queue protocol](CAPTURE_DECLARATION.md) preserves the original target hour and explicitly supersedes the PR70-source primary comparison only if this exact application patch deploys. The original declaration and all prior evidence remain preserved. Broader EXEC, first-entry edge, real/practice queue fidelity, full-scan cost, recorder Phase0/raw-volume/retention/cost and operating takeover remain OPEN. TJR/MNQ stays last.

## Deployed and retained

[PR71](https://github.com/sideriapostolou-lgtm/Claude/pull/71) merged **October16,12:37:31AM PDT** (07:37:31UTC). Exact source `275392733de1458692211506228f7dd30e60c693`, tested candidate `b5da12468a3136af84f43c12f07a5d0fb345c6a7` and tree `cdd8212700011f90f4fd4438d59638370e5ad645` are bound; the merge tree equals the candidate tree and all28 candidate files read back exactly. Railway `3e6e1589-0247-4eaa-b11c-e6117a72fa0b` reached SUCCESS **12:38:55.750AM PDT**. Normal Polymarket LIVE startup reports ten contracts/order. Bot and unchanged recorder8453f919 are online1/1, no platform warnings/criticals. No returned matches in the bounded traceback query; not an all-time certificate.

Root's86selected native restart checks pass against pre-release12:33:21AM and warm12:41:06AM statuses. Cash25.1219, cumulative−24.6195/currentday−5.1277, all selected financial/cap/rung/stop fields and scalar summaries remain unchanged. Three used control values were ignored; no financial budget was renewed. Epoch2 and two archived summary objects/source fingerprint survive; full archived bodies are not claimed verified. Observer is enabled/error-null/idle with56 no-candidate opportunities and zero starts. No natural order, populated queue HTTP, real-fill coverage or profitable outcome was produced by this release. First status was cold/observer-disabled; the early empty queries and later warm evidence are retained.

## Completed-day loss findings

The [independent direct-native audit](OCT15_COHORT_REVIEW.md) passes1,105checks and reconciles every observed side quantity, fill cost and fee for69traded windows. These windows lost **$5.0547** on302fills. One inherited pair adds1cent and one zero-share settlement adds0, so all71recorded settlements total **−$5.0447**, including **$0.8455fees**. All45positive windows made$24.4509;24negative windows cost$29.5056. Forty-three windows ended with equal side quantities;14of those still lost. A completed pair need not have cost less than its payout.

All69first fills were makers with exact-client-ID decision fair joins. The first side won expiry32/69(46.38%); mean decision-side fair50.38% and first price46.64%. These unweighted, executed-fill, mixed-version development descriptions do not establish miscalibration, causal adverse selection or a profitable new threshold. The earlier source releases are not assessed causally from this day. The coverage-filtered panel's−10.0028belongs to another population and must not replace actual settlement totals. Raw provider logging/book/queue continuity remains unverified. Root independently reproduced the23MB derived manifest/report byte-for-byte from the saved originals.

Sizing remains unchanged and the explicit numeric question unanswered. This evidence argues against scaling; no strategy that is guaranteed to profit or stay even was found. The concrete next strategy step is a fixed prospective initial-fill/markout/queue assessment under the frozen current policy, preserving every loss and unknown case.

## Actual fill attribution, not a hypothetical strategy

[889 independent checks](ACTUAL_ATTRIBUTION.md) attribute actual settlement cashflows to the contracts actually bought. Ordinary makers contributed+$0.7508 across262fills;40lock fills contributed−$5.8055, net−$5.0547. The first fill in each window contributed+$3.8768; subsequent fills−$8.9315. These are separate additive partitions of the actual portfolio, **not returns of a strategy that omits later fills or locks**. Removing them would change later inventory, caps, decisions, fills and risk. Three of the worst paired losses had winning-side late locks that reduced losses; their initial losing-side positions were the large loss. No lock-removal, first-fill-only or opposite-side trading policy is justified by this attribution alone.

Independent native retention review passes **90checks**, separately reparsing originals. The pre-restart12:35AM forecast was scored **12:45:16.795AM PDT** with all15frozenfields exactly unchanged and child_restart_gap preserved. It is one prediction-score body, not a trade or a full archived-body certificate. The first score query ended before that row appeared and its audit failed for missing evidence; the zero original/failure and later successful query are both retained.

The lossless evidence archive includes exact native calls, endpoint/restart records, local parsers and independent audits. [Manifest](EVIDENCE_MANIFEST.json) and [local-only reproduction](REPRODUCE.py.txt) restore originals and reproduce the derived cohort, attribution and retention results. Provider completeness, raw storage/cost, full books and profitable execution remain unverified.

Evidence publication `420baeaebb024ef467cf3867a8a1fc9cf5225c55` read back all59files exactly and was verified SKIPPED as Railway e31b457f at **12:49:06.955AM PDT**. The source blob remains767c97c2/PR71; bot3e6e1589 and recorder8453f919 remain online1/1 with no platform alerts. [Closure metadata](CLOSURE.json) preserves the exact readbacks, financial observation timestamps, release state and unfinished tasks. No profitable strategy, increased size or resumed trading is claimed.

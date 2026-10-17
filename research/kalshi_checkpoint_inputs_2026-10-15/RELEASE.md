# PR67: deployed, history retained, fixed window +$0.11

Checked October15, 2026, Pacific time. This completes the bounded release and observation described below. **Overall execution reliability and profitability remain open.**

## What shipped

PR67 merged at **5:06:40–43 PM PDT**. Railway deployment `d32c256b-618d-4927-b44a-f182d569977b` built exact source `0520f7468174d6a37f0ee7dfe64284b1a6921439`, tree `d9eae74b5c76b28b74c85b3617ff3d2266969321`, and reached SUCCESS at **5:07:45.558 PM**.

The patch reuses safe immutable Settlement conversions within one practice-report preparation call. Application, test and build bytes match the reviewed candidate: **6,032 pytest passes / 14 existing skips, full mypy on130files, Ruff on2changed files, independent268focused checks**. No trading rule, fee, order, cap, stop, resume budget, variable, live ledger or Polymarket code changed. Normal Polymarket LIVE10-contract startup was logged at5:07:42PM. Recorder deployment8453 remained unchanged.

Synthetic7day report-preparation median49.42→42.25ms and31day618.28→502.98ms are scope-limited; adverse tails, initial small-case failure and allocation costs remain in [READY.md](READY.md). Actual retained practice-history sizes remain unknown. The completed shown practice-report span maximum later reached326.593ms; the overall practice checkpoint maximum remained1595.875ms. These nested/session maxima are not additive or comparable production speedup estimates. No measured profit gain is attributed to the patch.

## Restart and source continuity

Independent comparison retained27 whole financial/control/history values or subtrees and1,475equal flattened paths. Cash$30.2696, open cost$9.98, reported open risk$0 and cumulative settled P&L−$19.4918 were preserved. Limits stayed$10/window,$20open,$6UTCday,$10total,clip5. Existing UTC midnight rollover cleared the daily stop at5PM; no agent manually activated, reset or resumed trading.

V1 first startup matched the immediate predecessor except its timestamp:0forecasts/0scores/42unknown. V2new sourcef265 began separately: predecessor23e2 retains9forecasts/8scores/2unknown/1pending and both exact Briers, plus the distinct older5-score archive. The old pending forecast stays explicitly frozen-unresolved. No calibration transferred or learner output applied to real orders.

Cold5:08:54 and5:09:56 financial originals were account-stale/tradingfalse. Fresh original5:10:56.873, retrieved5:11:15, was LIVE/authenticated/trading_nowtrue. This supports readiness at that observation, not continuous freshness. A5.316s full account reconcile, including two7,170row/eight-page order reads, remains unfixed.

At5:32:31PM, independent post-tail deployment metadata and native health show the same d32/source0520SUCCESS; bot and unchanged recorder each had1/1replicas. The5:12PM declaration commit3590583 was SKIPPED by Railway. Root made no source, policy or variable change through the tail.

## Fixed prospective window

[Declaration](CAPTURE_DECLARATION.md)3590583 was committed before start; exact readback was recorded by5:13:04PM. Target **5:15–5:30PM PDT**, separate tail **5:30–5:32PM**. All16closed queries ran5:32:10–11PM, limit500each, unsaturated/no API errors. Independent extraction checked382unique returned original rows; this is finite filtered-log evidence, not complete books, volumes or account-ledger certification.

Target `KXBTC15M-26OCT152030-30`:

| Actual real-money quantity | Verified result |
|---|---:|
| Original fills / distinct filled orders | 7 / 6 |
| Up shares / cost | 10 / $4.09 |
| Down shares / cost | 10 / $5.80 |
| Total cost / actual fees | $9.89 / $0 |
| Matched-pair P&L | **+$0.11** |
| Directional P&L | **$0** mathematically |
| Total settled P&L | **+$0.11** |

All fills were maker receipts; the first Up5 was split1.04+3.96. Native settlement5:30:10.529 reports10paired credit already received and0additional net payout; do not add$10again. Its tiny floating directional residual is rounding noise. Public keyless GET5:30:28.705–29.641PM independently returned finalizedYES: final$82,273.40 versus$82,263.34strike. Rules use the sixty-second BRTI average, with equality resolvingYES. Public settlement timestamp5:30:06.875965 differs from native5:30:06.877566 by1.601ms; they are not asserted identical. Raw public response bytes/hash are preserved.

The frozen5:20forecast was58.5494%Up, with0prior bin observations andp=q. Its decision payload was74.7454ms after its scheduled slot; platform publication was170.015415ms after the slot (95.270015ms later); reported Bitcoin age0.7898974s and batch age0.0241364s. The original5:30:25.341score embeds that exact forecast. Independently computed Brier0.1718150381578175 agrees with the runtime score. Latest observer has1forecast/1score/1separate startup unknown/pending0. One correct forecast is not an accuracy, learned edge or profitability estimate.

The original Kalshi practice-window receipt reports **zero fills and$0P&L**. The live practice twin also reports no fills. Seven actual receipts versus zero practice fills neither proves a simulator defect nor provides a reliable counterfactual: causal decisions, queue, receipt time and coverage may differ. Explain this difference before trusting a new strategy's practice P&L; do not loosen fill rules to match a profitable outcome in hindsight.

## Separate financial windows and current snapshot

The preceding **5:00–5:15PM** restart-spanning window has7fills, Up10/Down11, cost$9.98, fees0, officialYES: **+$0.509090909locked−$0.489090909directional=+$0.02**. All its fills preceded PR67; keep it separate from performance attribution. Its$10paired credit was already reflected in cash and settlement added$0.

Last original financial snapshot **5:31:01.535PM**: LIVE/authenticated/trading_nowtrue, waitingempty, integritynull, neither stop latched; literal diagnostic reason`Window has not started`. Cash **$30.3796** is not profit. Cumulative settled trading P&L **−$19.3618**; fees$3.11672, locked+$4.29904,directional−$23.66084. Current UTC day has2settled windows/14fill receipts/**+$0.13** from the two separately reconciled windows. Next-window open orders1/reserved$1.65/filled positions0/open cost0: at-risk reservation is not omitted merely because filled open risk is0. Ladder stays rung0/promotionnotready; limits unchanged. This is a timestamped selected report, not present-time or full-ledger certification.

Prior completed **October15UTC day** = October14 5PM–October15 5PM PDT: raw real report69windows/71settlements/302fills, fees$0.8455, locked+$4.50115,directional−$9.54585, **net−$5.0447**, worst−$2.7667; maker fill rate6.2535%, no taker attempts. Reported decision→ack median81.86/p95349.65ms (3,505samples,77errors); BTC receipt→decision median167.62/p95709.72ms. These are their named intent/day cohorts, not pure strategy reaction time; maker decision→fill average3,148.55ms includes resting time. Practice-twin raw14windows/14fills, **+$0.50**, worst−$2.30, maker fill rate0.42245%, average decision→fill6,552.37ms; fees are not separately exposed by that practice-twin raw report. These raw cohorts differ from the stricter scorecard and are not directly comparable performance estimates. Only29of88eligible windows are marked complete and59have gaps; strict real scorecard26traded windows nets−$10.0028 within that narrower cohort. Preserve both losses and coverage limitations; do not replace the raw total with the narrower subset or claim full-day coverage.

## Timing and missing data

The unchanged13-check recurrence analyzer reports:

- Main reader target: **19gap receipts, all overflow/unknown**. Status:28rows,26known/2overflow, known maximum765.531ms;22known accepted after recv_call. Status observations cannot substitute for unknown gap durations.
- Main reader tail:1gap overflow/unknown;3known statuses, maximum370.968ms.
- Separate derived reader: target5gaps,4overflow and **one known4,336.016ms accepted→recv_call**. Its other statuses remain a separate population. This is local post-acceptance buffering, not network latency, CPU saturation or a unique causal attribution.
-33original gap warnings across readers;0matching timing-unavailable events or Tracebacks within these bounded filters. The warnings and timing samples are different populations, not additive rates.
-**17original combined practice messages are each81,920bytes and truncated/invalid JSON**. They remain unrepaired. Required full practice-status evidence is incomplete, although the separate target practice-window and companion financial messages parse successfully.

No saturated parents, analyzer conflicts or malformed timing payloads. Unknown/overflow and unavailable actual retained sizes prevent a claim that the release eliminated delays or improved production trading results. See [RECURRENCE_SUMMARY.json](RECURRENCE_SUMMARY.json).

## What the next strategy idea actually proves

[Capped hedge quotes](../kalshi_hedge_quote_2026-10-15/MECHANISM.md) have a source-pinned, independently reproduced synthetic opportunity proof only: a strictly balancing Up5@62c proposal fails the99c pair cap against confirmedDown5@57c;42c passes unchanged guards, with lower40c needed in the declared nonzero-fee stress. Reservations, size, cash, edge, freshness, starter and late-lock rules remain unchanged. It proves neither fillability nor profit. The preceding actual window's2c ordinary budget remainder may block this fallback; no claim it would have changed that result.

Next evidence: reconcile actual maker receipts with causal practice decisions/queue/prints and obtain permitted raw operational exports; then evaluate a separately frozen capped-quote candidate against unchanged policy and no-trade after fees. Current minute reason maps and truncated heartbeats cannot establish opportunity frequency or counterfactual fills. Existing original/inverse/no-trade gates/error allocations and all unopened FamilyA/toxicityTEST data stay unchanged. No new strategy was activated.

An independent [account-query design](ACCOUNT_QUERY_DESIGN.md) found no safe reduced scan proven yet: old terminal corrections can evade a narrowed second pass. Current official schema was fetched keylessly5:24:21PM; min_ts update semantics/snapshot guarantees remain undocumented. Public archive cutoff receipt5:26:09PM reports October1orders/August16fills; these precede the recent trial, so no current missing-history claim follows. Keep the3s freshness gate. Actual count-only practice export is still missing.

Recorder raw-volume status/verify, before-October20retention fit and measured cost remainunverified; online health alone does not clear them. Operating-transfer/access/business tasks stay deferred/open, TJR last. Workspace transport briefly failed while packaging; it recovered and the saved files were verified present. No credentials, financial variables, limits, stops, resume/day budgets, manual orders, new live desks, paid services or storage changes occurred.

## Reproduce the receipts

[NATIVE_MANIFEST.json](NATIVE_MANIFEST.json) names ordered text parts containing a lossless base64/XZ JSON archive of44evidence files (native receipts and derived reviews). Concatenate the parts, verify the manifest's SHA256, base64-decode and`lzma.decompress`with Python's standard library. Parse the JSON and write each`files[].utf8`to its safe basename`files[].name`; verify every saved SHA256. Full original truncated strings stay truncated. The archive's roundtrip was checked byte-for-byte before publication; no private handoff inventory or credential/contact values are included.

Run the unchanged [recurrence analyzer](../kalshi_probability_epochs_2026-10-15/pr66_recurrence.py.txt) on the three extracted CAPTURE_ws files with explicit declared bounds/source/deployment. Its query paths may differ locally; compare the population metrics and original hashes, not a path-dependent whole-output hash. All raw fixed query receipts include actual retrieval timestamps, filters, bounds and limit500. Independent reviews inside the archive document the financial, forecast, restart and identity checks.

The official schema raw snapshot stays private because a public documentation example triggered the private-key-pattern scan; its exact GET metadata/hash remain in the archive. No claim is made that the public example is a real credential.

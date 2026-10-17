# Pair protection deployed; first fixed window earned 12 cents

October 15, 2026, Pacific time. [PR69](https://github.com/sideriapostolou-lgtm/Claude/pull/69) is live. The predeclared **9:15–9:30 PM** window bought **Up1 at32¢ and Down1 at56¢**, both maker fills with zero fees. Its $1 payout minus88¢ cost is **+$0.12 locked /$0 directional**. The new protection marker triggered, and the returned records contain no later target-window buy intents or acknowledgements. This verifies one natural exercise of the restriction. It does **not** establish profitable expectancy or guarantee break-even.

The separate preceding window lost **$0.3515**; it remains in the account totals. At the last fixed snapshot, **9:31:36 PM**, reported cumulative settled trading P&L was **−$23.7069**, current UTC-day P&L **−$4.2151**, and cash **$25.6245**. Cash is not profit. A successor position had41¢ filled risk and44¢ additional reservations; the account was not flat.

## Exact release and checks

Candidate `41a82f2d60daae091c821327962598b69e9790a9` and merge `66d122b58000bdea98c95368bee5df912a9666bf` have identical tree `21768bc1d087655cbc40dcecf7cf942ef825f3e8`. All37candidatefiles were read back exactly before merge at **9:06:10–14 PM**, within safe minutes. Railway deployment `2af8d2be-77f7-4738-ab67-33c37c09b86b` reports SUCCESS **9:07:24.553 PM**; environment health reports `.552`, a preserved1ms metadata difference. Normal Polymarket `LIVE: 10 contract(s) per order` startup is logged **9:07:20.836490916 PM**.

Final full suite: **6,093 passed /14 existing skips**, exit0,287.07seconds; full mypy **131 source files**, changed-file Ruff **7 Python files**, diff/credential checks and independent exact-patch review passed. Focused149+6 and283cases overlap the full suite. [Checks](CHECKS.json), [exact review](EXACT_PATCH_REVIEW.md), [preparation and failure history](PREPARATION.md). Seven-file patch SHA256 `edaad1806ae064aa081019531bfc0d1084c8026510d86ce81b3f064d721ffc8e` stayed unchanged after checks. Earlier focused/full fixture failures are preserved, with original financial assertions and crash/journal coverage retained.

[SOURCE_BINDING.json](SOURCE_BINDING.json) records a post-tail exact remote readback of all7tested Python files and the selected running-source metadata. Both bot and unchanged recorder `8453f919-b891-4aa7-8478-6fcf6b9c24ee` were online1/1 on the post-tail health read, with no health-panel issues. This is service health, not a raw-volume certificate. The ancient empty staged Railway patch remains unapplied.

## What changed and what can still lose

After each actual owned fill, the risk book marks a window once nonzero Up/Down quantities are equal within the existing epsilon and guaranteed payout exceeds actual principal plus fees. It then refuses ordinary new directional buys. Existing ordinary residual bids that cannot strictly balance confirmed imbalance, including all active same-side reservations, go through normal cancellation. The transport guard rechecks protection after waiting.

Cancel requests,200/404 acknowledgements and uncertain creates retain liability until existing reconciliation. Strictly balancing buys remain subject to existing cash, fee, pair-cost, budget, ownership and timing checks. The late risk-reducing lock path and initial-entry policy are unchanged. Existing resting-order races, partial fills, feed gaps and the initial unmatched entry can still lose. Blocking later bets can also forgo gains. This is a new restriction of previously permitted risk, not repair of a proved old cap violation.

Markers use a validated top-level persisted list and the existing fill-batch checkpoint; strict cold-archive schemas and checkpoint cadence are unchanged. Legacy restore derives only currently equal positive confirmed holdings. A crash before checkpoint followed by reordered fill replay ending unequal can miss an unsaved intermediate marker. Older code ignores the new field and would withdraw the restriction; no automatic rollback is authorized. The logged inventory floor excludes outstanding liabilities. Practice, arena and copied-decision twin retain their existing cancellation, lock-copy and fill differences.

Effective limits remain **$10/window, $20 open, $6 daily stop, $10 total stop, maximum5-contract clip**, ladder rung0. No Railway variable, money limit, consumed control, loss budget, resume token, new real desk, owner Polymarket order, storage setting or paid service was changed. Polymarket code is unchanged.

## Restart retention

[Independent review](RESTART_RETENTION.md) passes95initial,22supplement and42preceding-window checks. These are bounded, overlapping receipt comparisons, not independent statistical samples or full raw state verification. Old9:06:58→new9:08:29snapshots retain reported cash25.866, filled risk.40, cumulative loss−23.4754, current-day loss−3.9836, fees, selected history, caps, stop flags and ladder history. Completed October12–15report subtrees are exact. Three control events say their values were already used. No new anchor was applied.

Reservations57¢→0 and open orders1→0 have matching old cancellation receipts and a fresh post-reconciliation panel. The final55¢order also has shutdown request/404 and startup404 receipts. These support cleanup, not complete per-order terminal-ledger proof. Zero reservations was not zero inventory.98restored historical protected windows and no open marker were not98new wins.

Probability source `f2652c6b9f5f4732b5ac865d72c4748df250ad73b38d493387f9dfc478dcff6c`, active ordinal2, current15forecasts/14scores/1pending/2unknown, two older archive summaries and legacy digest were retained. The pending9:05forecast was scored9:15:13with all15nested saved fields matching its original, including p0.17611385107685212 and q0.16772747721604964. OutcomeNO and `child_restart_gap` remain recorded. This verifies that specific saved prediction through restart; it does not prove learned edge or raw archive bytes. Temporary account-stale status, startup warnings and malformed log fragments are preserved.

The preceding9:00–9:15window retained Up1cost40¢ and added a late Down1at94.8¢ with.35¢fee. Total cost$1.3515, payout$1, actual **−$0.3515**. The hedge reduced the earlier worst-case loss by4.85¢. Its already-paid$1paired credit is counted once; additional settlement payout is0. Position count0 did not erase the still-unsettled loss. This is separate from the primary observation.

## Fixed prospective result

[Declaration](CAPTURE_DECLARATION.md), commit `c2788090aac2d220f2c39191e8247f3814fac104`, published **9:13:05 PM** and all3files read back **9:13:10 PM**, before target opening. Railway SKIPPED this docs-only commit. Target `KXBTC15M-26OCT160030-30` ran **9:15–9:30 PM**, collection tail to **9:32 PM**. Exact public market bounds were verified before opening. Source/settings stayed frozen. Readiness is a dated authenticated/trading snapshot, not proof of uninterrupted fresh input.

Eleven closed deployment-scoped queries returned **381distinct rows**, all successful and below their stated limit, including the two genuinely empty target-order intervals9:20–9:30. No source-window replacement was selected. Actual fill and market clocks remain separate:

| Venue fill time, PDT | Side | Quantity | Price | Fee |
|---|---|---:|---:|---:|
|9:16:25.980850 PM|Up, maker|1|$0.32|$0|
|9:17:14.448657 PM|Down, maker|1|$0.56|$0|

Both fills join actual durable intents, acknowledgements and order IDs. The marker's local time is **9:17:15.0107355 PM**, platform publication **9:17:15.639172561 PM**, inventory-only floor approximately12¢. Its18durable ordinary maker intents and17acknowledgements all precede the marker under both their local event and platform publication clocks. One29¢Up order was rejected with Kalshi400 `invalid_order`; this was before protection and remains in the evidence. Publication can place an acknowledgement before its intent's log line; local event clocks preserve their distinct meaning.

The returned target records contain no ordinary intent/acknowledgement after protection, no subsequent target fill, and no naturally exercised `pair_protected` residual-cancel branch or delayed-send refusal. The latter branches have fake coverage, not production exercise here. Existing cancellations before the marker retain their request/reconciliation caveats.

Actual settlement is published **9:30:05.347475328 PM**, in the separate tail, with Up1/Down1, principal88¢, fees0, payout$1: **+$0.12**. Locked contribution12¢, directional0. The$1paired credit was already paid and net additional payout0; it is not counted twice. A public unauthenticated HTTP200 read **9:30:46.609838–47.848063 PM** confirms finalizedYES, strike$81,950.72, expiration$82,002.62. The pair payout did not depend on YES winning.

Root's direct-native **61checks** and the separate [runtime review](RUNTIME_REVIEW.md), **66checks**, reconcile this bounded result. These checks overlap; they are not statistical samples. The reusable audit's exact original fills/Decimal ledger are in [RUNTIME_AUDIT.json](RUNTIME_AUDIT.json). Early owner-facing commentary accidentally reversed the two side labels; it was explicitly corrected to Up32¢/Down56¢. Original receipts were never changed.

## Practice, probabilities, gaps and current money

The copied-decision practice twin settled **−$0.56**, with only Down1at56¢; standalone Kalshi practice settled **$0 with no shares**. These are distinct from actual+$0.12. The target has18copy traces,17cancellations,2real-fill reconciliations and1practice fill. Observed trace drop/error/identity counters are0, but missing real Up exposure in the simulator remains an execution-fidelity limitation. This comparison does not certify actual venue queue position or an executable alternative strategy.

The observation-only target forecast at local **9:20:00.0684988 PM** predicted Up59.6073896% baseline/56.1803388%shadow and was scoredYES **9:30:06.8226829 PM**, with identical saved values and no post-forecast gap flag. Its platform publication was **9:20:08.372423185 PM**, approximately8.304seconds later; do not treat publication as immediate availability at its earlier local time. Neither prediction was applied to live trading. One correct forecast or profitable pair does not establish calibration improvement or profitability.

All17combined practice-status log bodies are genuinely truncated at81,920bytes and remain unrepaired. The capture retains25WS-gap warnings,2trade-gap warnings and1weather-paused warning. WS reasons include stale timestamps, timeouts and market-set changes; healthy service status does not erase them. No Traceback line was returned by the bounded supplementary filter. The real400order rejection is still an error receipt.

Of53WS timing rows, the main speeddesk reader has12gap diagnostics with receipt-overflow/unknown,21known status samples and4overflow status samples. The derived reader has4known gaps,4overflow gaps,4known statuses and4overflow statuses. These counts use platform-publication bounds; the first status's source clock predates opening. Known derived-reader residence reaches6,055.826ms; known status samples are a different population from unknown gaps. Thus buffering and missing delivery remain unresolved. Nine sampled full reconciliations have median3,775.844ms, range3,264.805–5,230.901ms; these slow/error-selected reports are not representative per-cycle latency or a causal profit estimate.

Latest fixed financial platform time **9:31:36.622896351 PM** reports LIVE/authenticated/trading, empty waiting, caps unchanged: cash$25.6245, filled successor risk$.41, additional reservations$.44, cumulative settled loss **−$23.7069**, fees$3.38382, matched+$4.9041323/directional−$28.6110323. Current UTC-day actual loss **−$4.2151**, fees$.2671, worst−$2.8509. Its positive gap-filtered subset is not the actual daily result:19eligible windows include8complete/11gaps. These are dated reported scopes, not full account/continuous coverage certification.

The partial UTC-day real-intent latency report has846observations: BTC callback-to-decision median203.008ms/p951,101.176ms;829successful decision-to-ack samples median91.129ms/p95334.681ms,17errors. These include input age/scheduling and journal/queue/HTTP respectively; maker fill latency includes resting time. Raw day maker fill rate62/846=7.3286%, while this target has2filled distinct orders/17acknowledged orders=11.7647%; denominators differ. The daily practice-twin+$1.14 is a separate incomplete population.

## Next evidence and unfinished work

The release, restart retention and this fixed natural-trigger observation are complete as bounded substeps. **Overall EXEC and profitable expectancy remain open.** This window does not compare against an executable old-policy counterfactual, and the guard can forgo later gains. Keep a prospective multi-window record including every loss, initial unmatched entry, rejected intent, residual liability and practice mismatch before judging improvement or proposing greater exposure.

Next evidence: retain this deployment, audit initial-entry risk and real venue queue/print evidence under an independently frozen comparison; do not tune on a winning window or substitute assumed fills. Continue the existing own-order queue-read validation outside the execution transport lock, full-scan/count-only-export work, and bounded input-delay attribution. No additional policy change was made on the strength of this window.

The earlier development cohort remains8wins/7losses, **−$4.0182 after$.2632fees**,14/15fill-total matches and one incomplete restart window. Its11positive-equal publication prefixes include4laterlosers,4largergains,1lowergain and2withoutlaterfills. One later fill's local intent predates prefix publication. Removing later fills is not an executable backtest. Sealed FamilyA/toxicity/MNQ TEST remained untouched.

Recorder raw-volume verification, storage/retention fit beforeOctober20, measured cost, the separate memecoin-recorder disk warning, operating access/automation transfer and other higher-priority takeover work remain open. TJR/MNQ remains LAST/queued; PR47's merged state alone does not clear these prerequisites. No Pages, duplicate TJR research or automation changes were made.

## Originals and reproduction

[RUNTIME_MANIFEST.json](RUNTIME_MANIFEST.json) binds the selected lossless original wrappers, independent reviews and analysis scripts. [REPRODUCE_RUNTIME.py.txt](REPRODUCE_RUNTIME.py.txt) verifies all parts/file hashes and optionally restores them into a new folder. Root and independent scripts use only those saved originals. The earlier [development archive](EVIDENCE_MANIFEST.json) remains byte-for-byte unchanged.

[Reproduction checks](REPRODUCTION_CHECKS.json): all55selected original files roundtrip exactly through6archive parts. Five analysis scripts rerun from the restored archive produce byte-identical analysis outputs; the portable CLI also reproduces its exact financial ledger, counts and empty issues list. These are artifact/receipt checks, not another app-suite run or evidence of expected profit.

Full deployment creator/contact metadata, unrelated private operating handoffs and credential values are excluded; selected source metadata is labeled as such. The11closed queries, empty startup attempts, wrong early `_settle`filter request, malformed originals and the approximate clock annotation on one early financial query are preserved, not upgraded into complete coverage. Archive integrity checks do not prove continuous market data, volume depth, executable fills or profitability.

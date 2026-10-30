# PR #64: first prospective probability score verified

Evidence assembled October 15, 2026, at **12:53 PM Pacific**. The separate probability observer is deployed and has completed its first original forecast-to-official-score cycle. This completes this bounded observer task. Upstream execution gaps, improved prediction accuracy and strategy profitability remain unproved.

## Release and checks

[PR #64](https://github.com/sideriapostolou-lgtm/Claude/pull/64) merged at **12:17:04 PM PDT**, during approved safe minutes. Railway deployment `2e88601d-c9c7-474f-add8-72c0a13c1a4b` built exact commit `8c8681a032a6181c49915ba88ba38d0818dc69d3`, reaching SUCCESS at **12:22:21.502 PM**. Normal Polymarket LIVE startup is recorded at 12:22:16.853 PM.

Merged app, test and build objects match candidate `4cf0734e`. All seven tested Python hashes and V2 fingerprint `e7989706…` match independent review. Full pytest passed **5,884 tests / 14 existing skips**, with captured exit zero; mypy passed 129 source files and Ruff passed all seven changed Python files. Original failed and superseded checks remain in the immutable [preparation evidence](PREPARATION.md). No source changed during the observation window; later evidence-only pushes were SKIPPED by Railway.

The new observer has separate state, history, source identity and page-feed fields. V1's module, protocol, fingerprint and history remain unchanged. Live rules, models, fees, caps, stops, budgets, used controls, persistence cadence and Polymarket code are unchanged. The observer cannot submit orders or apply its calibration to live decisions.

## Original prospective evidence

The **12:30–12:45 PM** window, with a **12:47 PM** tail, was [frozen](CAPTURE_DECLARATION.json) at 12:28:19.590 PM, 100.410 seconds before start. Its declaration was published and read through connected GitHub before start. The [forecast and V1 exclusion](SLOT_FORECAST_RECORD.json) were then published and independently read before the outcome. The exact target is `KXBTC15M-26OCT151545-45`.

| Check | Recorded result |
| --- | --- |
| Original forecast | 12:35:00.011 PM log; elapsed 300.004 seconds |
| Baseline p / shadow q for Up | Both 0.07826700568018541 |
| Prior bin | Bin 0, zero samples, zero wins |
| Bitcoin input | $82,315; original observation age 0.885 seconds |
| Parent batch | Age 0.361 seconds; qualified under frozen rules |
| Verified venue strike | $82,439.21 |
| Official result | Down; public Kalshi response finalized, result `no` |
| Original score | 12:45:28.881 PM log |
| Baseline / shadow Brier loss | Both 0.006125724178142175 |

The official contract compares sixty-second BRTI averages and resolves equality to YES. The public result reports an expiration value of $82,334.05. [Original contract and result responses](PUBLIC_SETTLEMENT.request.json) are preserved. A separate earlier `status=open` discovery returned only the prior closed window; that response remains recorded and was not substituted for target metadata.

Independent [slot](SLOT_INDEPENDENT_REVIEW.json) and [final capture](CAPTURE_INDEPENDENT_REVIEW.json) reviews reproduce the probability, timing, strict official outcome and score arithmetic. The fixed capture comprises 24 uncapped, error-free filtered reads, plus one separately labeled progress read. Anchored original parsing removes nested status copies and deduplicates overlaps. V1 still excludes this window for a pre-forecast gap; its unknown was never relabeled. The exact upstream producer cause remains unknown.

The last status inside the fixed capture predates scoring and correctly still shows a pending forecast. A separately bounded post-capture supplement, last original at **12:49:32 PM**, confirms **one forecast, one scored, zero pending, one startup-inside exclusion**, equal Brier scores and no reported observer error. The supplement does not extend or replace the selected window. No raw checkpoint/volume export was performed, so this is not independent proof of durable bin persistence.

One observation with q=p shows **no calibration advantage**. This is a conditional probability measurement using Coinbase inputs against BRTI settlement, not a continuous-feed certificate, trading simulation or profitability test. The existing qualified sigma also does not certify an entirely gap-free hour.

## Real trading remains separate

The [independent restart audit](RESTART_INDEPENDENT_REVIEW.json) compares 67 selected reported paths: **51 exact, 16 changes explained**, including one negligible floating-point difference. Seven old maker intents and three new balancing-lock intents join their acknowledgements. One real Up contract bought at 95 cents with a $0.0034 fee explains the restart changes. Cash arithmetic is $30.7239 − $0.9534 + $1 implied paired credit = $30.7705. The credit is an inferred consistency check, not a native cash-ledger export. The resulting loss-bearing pair was unsettled at the restart snapshot.

| Actual cohort | Fills and fees | Settled result |
| --- | --- | --- |
| Prior partial 12:15–12:30 PM | Earlier pair, including the 95-cent lock and $0.0034 fee | **−$0.3434**, locked; zero directional |
| Declared 12:30–12:45 PM | Down 1 at 73 cents + Up 1 at 26 cents; both maker; zero fees | **+$0.01**, locked; zero directional |
| Next window, observed in tail | Down 1 at 45 cents; zero recorded fee | Unsettled; excluded from target P&L |

The two observed settlements net **−$0.3334**, not a profit. All prior losses remain in cumulative P&L. The target's one-cent gain comes from the unchanged real bot, not the new observer.

At the separately captured **12:49:31 PM** original, Kalshi reports authenticated LIVE/readiness passed, **$30.3305 cash**, **−$18.9609 cumulative settled trading P&L**, **$0.45 open risk**, one position and zero open orders. Cash is not profit. Limits remain **$10/window, $20 open, $6 day stop, $10 total stop, clip five**, rung zero; the existing balancing-lock exception is unchanged. Both stop latches remain false. Three previously used reset/resume controls were ignored; no new budget was created.

The first three post-start heartbeats were stale and remain excluded from readiness proof. Later captured heartbeats pass. `as_of` is panel time, **not account-read time**; actual account age is unpublished. Selected reported fields and filtered receipts do not establish complete native ledger, cash-history or control-anchor coverage. A separate [bounded bridge audit](FINANCIAL_BRIDGE_INDEPENDENT_REVIEW.json) finds no original fill or settlement between the ready restart snapshot and 12:30 PM; seven nested fill copies are excluded. This supplements the original capture review without rewriting its count or certifying complete ledger coverage.

## Health, storage and remaining work

At **12:48:24 PM**, Railway reports the bot and unchanged recorder online, one instance each, with no platform warnings, criticals or recent failures. Bounded new-deployment Traceback and speeddesk-halted queries return zero. These are bounded observations, not uninterrupted uptime guarantees.

Recorder warning-keyword results are empty. The error-keyword query matches one **INFO** metrics report containing the word `errors`, with no actual error severity. Its **12:00 PM** report states 565,164,444 bytes used against a 4,831,838,208-byte retention cap, level zero. This is older self-reported retention usage, **not current filesystem free capacity**. The recorder explicitly does not certify coverage or per-venue spot ticks. The existing **3:45 PM Pacific** checkpoint and storage review before October 20 remain due.

Full deployment-list originals containing unnecessary creator contact metadata are preserved privately. Public `*.public-redacted.json` derivatives explicitly remove only creator objects; [hashes and paths](PUBLIC_METADATA_REDACTIONS.json) identify the originals. Financial/forecast log originals remain exact. No credentials or private handoff contents are published.

Highest-value next evidence: accumulate prospective official scores under this unchanged protocol, report sampling exclusions and compare shadow versus baseline on future data before proposing live use. Separately address the already reproduced producer chronology and REST/WS recovery races without rewriting V1 or V2 history. Broader EXEC remains open. [TJR-MNQ-001](QUEUE_GATE.json) remains blocked on authentic contract bars and verified costs, with historical P&L null, paper not started and live disabled; no duplicate research or automation change was made.

The release manifest records archive hashes and member sizes. Preserve the preparation archive, pre-outcome declarations, original losses and every stated coverage limit.

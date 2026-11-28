# Deployed diagnostics; fixed window lost $2.8509

Recorded October 15, 2026, **8:27 PM PDT** (October 16 UTC). Source release and its fixed observation are complete. **Profitability and EXEC-DELAY-001 remain open.** These records do not support increasing exposure or changing live trading rules.

The useful finding is that the bot takes substantial one-sided risk while waiting for the other side. The selected earlier window lost after taking additional directional exposure following a profitable completed pair. The fixed prospective window lost on its initial unmatched position; its eventual expensive hedge reduced the existing worst-case loss. Neither observation proves a general profitable replacement rule.

## Exact release and checks

[PR68](https://github.com/sideriapostolou-lgtm/Claude/pull/68) merged **7:47:08–10 PM PDT**, within the standing safe minutes. Actual application commit `66561e4ee43c962292347693e98ea00986f5db35`, tree `aa42757a2e561415af5490b086adb1de2bb16b28`, Railway deployment `99bf5b9e-72b2-4912-a7cb-8a3db414133b`. Deployment list reports SUCCESS **7:48:24.522 PM**; environment health metadata reports `.521`, a preserved one-millisecond metadata difference. Normal Polymarket `LIVE: 10 contract(s) per order` startup is logged **7:48:21.804973305 PM**.

Full checks before release: **6,057 passed /14 existing skips**, full mypy **131 files**, Ruff on **3 changed Python files**, diff/credential checks, and independent **72 focused cases**. The focused cases overlap the full suite and are not an additive count. All 14 PR files were read back exactly. A final remote-source readback matches all three tested source/test Git blob IDs and SHA256s. [Checks and failure history](CHECKS.json), [implementation and resource limits](REPORT.md).

This release changes diagnostics, not the decision model, send/cancel/fill rules, financial state schema, save cadence or money controls. The observer logs exact client/twin links, copy/skip outcomes, cancellation scope and available queue snapshots, and twin state during real-fill reconciliation. Buffers and error/drop counters are bounded; malformed diagnostics are isolated from financial work. The five initially failing malformed-result cases were fixed with regression coverage and retained in the evidence. Synthetic timing costs are disclosed separately; production cost and speed improvement are unmeasured.

The later declaration commit `1eff6461f229fbe142b5c763c4e449e270be0f69` was docs-only and Railway **SKIPPED** it. Post-tail connected inspection at **8:18:38 PM** confirms the same running source/deployment, and both bot and unchanged recorder `8453f919-b891-4aa7-8478-6fcf6b9c24ee` online **1/1**, no health-panel issues. This is service health, not raw-volume, fill or profitability verification. An ancient staged empty Railway patch remains unapplied.

## Restart and history retention

[Independent retention review](RESTART_RETENTION.md): **19 checks** support exact equality of the supplied old/new reported financial totals, caps, stops and selected probability subtrees. Cumulative losses were retained. Existing controls were ignored as already used, not reapplied. Effective caps remain **$10/window, $20 open, $6 daily stop, $10 total stop and 5-contract clips**; ladder stays rung0. Neither stop was latched at the supplied final snapshot. No limit, budget, resume token, variable or new live desk was changed.

The first new statuses were account-stale and not ready. The later payload at **7:51:40.506863 PM**, platform **7:51:40.821028964**, retrieved **7:51:51**, reports LIVE/authenticated/trading, empty waiting and no integrity error. Readiness precedes the declared opening by more than120seconds. Zero reported reservations after restart did not mean zero inventory: Up5 costing **$1.20** remained open. Earlier reservations $3.60→$3.75→$0 have visible cancellations but no complete per-order liability reconciliation; that limitation remains.

The same probability source `f2652c6b…dcff6c` and active ordinal2 retained ten forecasts/ten scores, older reported archives, and the legacy digest. Startup exclusions increased1→2. Older archived unresolved forecasts stay unresolved. This verifies supplied summaries, not full raw ledger/history/archive bytes. The learner remains observation-only and does not authorize orders.

## Fixed prospective observation

[Declared before opening](CAPTURE_DECLARATION.md), all declaration files read back by **7:54:41 PM**: `KXBTC15M-26OCT152315-15`, **8:00–8:15 PM PDT**, separate collection tail to **8:17 PM**. Source/settings were frozen through the tail. No replacement winning window was selected. Public metadata retrieved before opening confirms the actual03:00–03:15UTC bounds.

Nineteen deployment-scoped original log queries were retrieved **8:17:27–42 PM** after tail closure. They returned **279 rows /269 distinct platform-timestamp/message pairs**; ten repeated WS warnings appear in two filters. Every call succeeded and returned fewer than500 rows (largest49). This establishes bounded returned-log coverage, not complete raw market delivery or the whole private account.

| Actual venue fill time, PDT | Side / role | Quantity | Fill price | Actual fee |
|---|---|---:|---:|---:|
|8:00:28.064413 PM|Down / maker|3.12|$0.600|$0|
|8:00:28.064489 PM|Down / maker|1.88|$0.600|$0|
|8:11:21.875297 PM|Up / balancing taker|5|$0.968|$0.0109|

Three unique fill receipts join **two** actual order IDs and their real durable intents/acknowledgements. Total Down5 cost **$3**, Up5 cost **$4.84**, fees **$0.0109**. Public HTTP200 finalized YES, retrieved **8:16:14.510983–8:16:15.599905 PM**, reports strike **$81,934.59** and expiration **$82,042.16**. Actual settlement agrees:

**$5 payout −$7.84 principal −$0.0109 fees = −$2.8509.** Matched/locked contribution **−$2.8509**, directional contribution **$0** after the hedge. The $5 paired credit was already paid; the reported additional net settlement payout is $0. Do not count that credit twice. All-in pair cost **$1.57018** is a losing pair, despite the controller's “lock” label.

Before the hedge, Down5 could lose its entire $3. The late Up purchase reduced that worst-case loss by **$0.1491**. It did not create the initial exposure or make it profitable. The existing late balancing path deliberately permits risk-reducing hedges above the ordinary99c pair cap; this was not a new policy change or evidence to remove the hedge. Earlier cheap Up maker orders were acknowledged, but no actual fill receipt shows they bought a hedge.

Separate losses/exposure remain separate: preceding **7:45–8:00 PM** market settled NO for **−$1.20**, from an entry before this patch. The tail's successor market had an actual Up3@$0.68 fill, cost/risk **$2.04**, still open in the last supplied financial snapshot. Neither belongs to the primary window's P&L.

## What the new diagnostics establish

The target has **6 intents and6 acknowledgements**: five ordinary makers and one balancing lock. Its **13 trace rows** are five exact copy links, five same-parent reprice cancellations, and three real-fill observations. There is no observed target skip or demonstrated sibling cancellation in this window.

The real Down maker maps to practice twin **9349**, initial modeled queue **2823**, activation **8:00:23.477885 PM**. Cancellation at local **8:00:28.5735383 PM** records queue approximately **2305.36**, remaining5. Both actual partial fills map to that observed terminal cancellation. Their venue-created times preceded local cancellation; the subsequent real cancel returned404 “not resting,” and the fills-batch-return clock is **8:00:28.7209277 PM**. The diagnostic snapshot is explicitly not the state at venue execution. Different clocks cannot prove pure network/callback delay or actual venue queue position.

The balancing lock is a genuine durable intent with97c limit and96.8c execution. Its trace explicitly has twinID0/unknown. The existing lock path does not make the ordinary practice copy. This intentional policy difference must not be counted as a lost ordinary maker-copy outcome or invented simulated hedge. Both the distinct copied-decision twin and standalone practice settlement record **zero target shares and $0 P&L**. Practice is not yet a trustworthy executable-profit comparator.

All49 trace rows and17 live panels retain one diagnostic session/version. All six trace helper/drop/eviction/publication counters have observed maximum0, with buffers inside their declared bounds. This supports the observed diagnostic publication; it does not certify raw accepted public prints, cancellations ahead of us or intermediate queue states.

Root's independent direct-native audit passes **39 receipt/arithmetic checks**; separate Astra review passes **32 concrete checks**. The original generic audit and its eight fake cases are preserved: its overly narrow intent-label/prefix classifier initially omitted the lock and misclassified valid probability/plaintext events. A corrected independent extractor and four regression cases distinguish those from genuinely truncated JSON. Root reran those12 analysis fakes and two portable-adapter cases: **14 passed**. These are research-analysis checks, not another app-suite run or a profitability PASS.

## Gaps, timing and current numbers

All17 combined practice-status strings are genuinely truncated at **81,920 bytes**; they remain unrepaired. Of269 unique rows,240 contain valid JSON,17 invalid/truncated JSON and12 valid plaintext warnings. Ten WS-gap warnings include eight before primary close and two in the tail; two additional public-trade-gap warnings report `ValueError` (one invalidates books, one does not). Empty reject/traceback-filter returns do not erase these warnings.

The unchanged recurrence analyzer finds primary main-reader **7 gap diagnostics, all receipt-overflow/unknown**;18 status samples have15 known/3 overflow. Tail has1 unknown gap and3 known statuses. No known gap can be used to conclude buffering was eliminated; known status samples are another population. Callback timing retains21,555 evictions, separate from zero twin-trace loss counters. No complete print/queue tape was available.

Eleven sampled reconciliation diagnostics include8 full cycles: median **4,177.358ms**, range **3,164.341–5,643.88ms**. Full order scans return roughly7,820–7,836 historical rows,8pages/~6.2MB each; smaller filtered scans are separate. These are slow/error-selected reports, not representative per-cycle latency or proof of this loss's unique cause. The latest partial-UTC-day real-intent latency report has711 observations: BTC callback-to-decision median **218.437ms/p95 1336.346ms**;695 successful decision-to-ack samples median **91.776ms/p95 337.269ms**,16 errors. Callback age includes scheduling and stale accepted inputs; acknowledgement includes journal/queue/HTTP. Neither measures pure strategy computation, and maker fill time includes resting time.

A tail **8:15:48.611698406 PM** status temporarily waits on an uncertain order. Latest supplied financial **8:16:48.413984947 PM platform /8:16:48.223919 payload** reports LIVE/authenticated/trading, waiting empty, cash **$25.9193**, filled successor risk **$2.04** and additional reservations about **$0.84**. Both exposures matter. Cumulative reported settled P&L is **−$21.7821**, fees **$3.37202**; matched **+$6.828932337662324**, directional **−$28.611032337662333**. Partial UTCday actual P&L **−$2.2903**, worst **−$2.8509**. Cash is not trading profit. These are dated reported totals, not a complete account-ledger certification or a current-to-the-second balance.

The same panel's practice-twin raw day P&L **+$4.10** is not comparable full coverage. Its and real scorecards are partial/gap-filtered cohorts; the real filtered scorecard's positive subset excludes actual losing gap windows. Do not substitute it for the negative actual totals. Raw194windows/894fillrows/208settlementrows have different scopes and do not certify unique fully observed windows.

V2 issued a frozen target forecast **8:05:00.0796075 PM**, Up probability **72.78878347%**, identical baseline/shadow prediction. The actual YES score at **8:15:12.176181 PM** carries that same forecast; forecasts/scores10→11, pending0, unknown2 retained. Brier error **0.07404503050425643**; updated means approximately0.22906396baseline/0.23433893shadow. The separate older V1 pregap diagnostic remains unknown, not a contradiction or recovered producer history. One correctly scored probability does not demonstrate profitable buying prices or learned improvement.

## Next evidence and open work

[Next bounded design](NEXT_EVIDENCE.md): verify Kalshi's authenticated own-order queue read against modeled queue without slowing sends/cancels, then predeclare an honest multi-window alternative-entry comparison. Public OpenAPI documents queue endpoints, but permission, actual responses and runtime timing have not been verified. No queue read, new polling feature or policy change has been shipped.

The [selected7:30–7:45PM loss](PRIOR_LOSS.md) proves a new Down3 decision after a positive5/5pair later lost; it is development evidence, not held out. Any proposed “stop adding after a pair” comparison must include forgone later gains, existing resting orders, cancel/fill races and every loss. The primary loss here also shows the initial one-sided clip can lose before any pair exists. A cherry-picked truncation or assumed maker fill cannot establish profit.

Keep EXEC, real/practice queue/print fidelity, full-scan/count-only-export work, recorder raw-volume verification/retention fit beforeOctober20/measured cost, and operating access/automation transfer OPEN on their existing records. TJR last; FamilyA/toxicity/MNQ TEST untouched, separate reclaim confirmation consumed without promotion. Dedicated recorder health does not resolve the separate existing memecoin-recorder low-disk649MB warning. No credential values, operator orders, financial controls, Railway variables, purchases, storage or automation changes were made.

## Original receipts and reproduction

[RUNTIME_MANIFEST.json](RUNTIME_MANIFEST.json) binds the ordered lossless XZ/base64 archive, per-file hashes, selected identity extraction and explicit exclusions. It includes empty queries, exact malformed strings, pre/post financial/probability/control originals, fixed capture, independent reviews and analysis scripts. The earlier15-file [EVIDENCE archive](EVIDENCE_MANIFEST.json) stays unchanged.

Unfiltered startup logs containing unrelated owner Polymarket activity, full deployment creator/contact metadata and the large public schema with key-example text are excluded. Only selected health/source fields and the relevant public queue-schema extract are published, with excluded-original hashes where appropriate. No private operating handoff is included. See archive reproduction instructions; checksum and byte roundtrips were verified before publication. Those checks establish artifact integrity, not market completeness or profitability.

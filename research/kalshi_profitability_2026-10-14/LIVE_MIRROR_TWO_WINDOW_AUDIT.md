# Independent final post-PR58 two-window audit

**Both predetermined windows are retained: −$1.590 and +$0.261, combined −$1.329 after $0.009 fees.** Recorded account-read resumption and covering loop-lag evidence remain below the coarse3,000ms criterion. Source freshness is unresolved:47source-age/invalid-timestamp warnings, separately47gap diagnostics, four exact main-reader local-residence intervals and43overflow-unknown rejected receipts. This finite audit does not clear EXEC-DELAY-001 or establish the causal effect of PR58.

The capture is closed: complete=true, collector_jobs_running=false, persisted2026-10-15T05:32:19.240807+00:00, fixed query tail05:32. App source `1e8d0be07b280292fa873a2f5da9b22dd02f28c3`, deployment `fc0a73e9-f052-435a-94b2-ce7b1272f36e`. No production query, source edit, deployment, financial variable or money action was performed by this audit worker.

## Original evidence and fixed scope

Immutable full input `/workspace/shared/mirror-postrelease-two-window-audit-input.json`:13,672,459bytes, SHA256 `800d9bc39e3d4247312c75c2f64c41b046294f4db98b5a899b29b7eb659a9401`. Fifteen contiguous saved query responses cover04:49:27–05:32 UTC. All query artifacts match their recorded hashes, none returned an API error or hit its500-row limit (largest205rows). Independent parsing finds1,058unique original rows, no duplicates or parse errors. Filtered application logs are not raw venue/ledger exports or a complete market tape.

The financial cohorts were fixed before results:05:00–05:15 UTC (`KXBTC15M-26OCT150115-15`) and05:15–05:30 UTC (`KXBTC15M-26OCT150130-30`),22:00–22:15/22:15–22:30 PDT. All their original events and settlements in the retained tail are joined by exact ticker and IDs; no losing window was replaced. Startup04:49:27–05:00 and the05:30-next ticker remain separate.

The earlier first-window immutable input/report/parser are preserved. Final evidence changes none of its compared fill, intent, acknowledgement, cost, fee, P&L or reconciliation-completeness fields. Each fixed log-time window contains16original rows absent from the collector-derived event set (15speeddesk_status and1speeddesk_twin); this audit uses originals. The final derived artifact hash is recorded in JSON for that comparison only.

## Actual logged finances

| Fixed UTC window | Intents / accepted orders | Distinct fills | Up / Down shares | Cost | Fees | Payout | Settled P&L | Locked component | Directional component |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|05:00–05:15|40 /40|5|13 /8|$9.590|$0|$8|**−$1.590**|+$0.679230769|−$2.269230769|
|05:15–05:30|41 /40|7|11 /11|$10.730|$0.009|$11|**+$0.261**|+$0.261|$0 within rounding|
|Both|81 /80|12|24 /19 across separate windows|$20.320|$0.009|$19|**−$1.329**|+$0.940230769|−$2.269230769|

The worst settled fixed window is−$1.590. Both settled Down: first settlement published05:15:06.647204136; second05:30:08.161914550. Summed original fill cost, fee and side quantities match the unique corresponding settlement; payout, paired credit/net payout and P&L agree. Locked/directional components are independently recomputed using fee-inclusive average side cost, matching pinned `speeddesk_model.settlement` at source1e8d0be. They are accounting allocations, not separate realized strategies. All12distinct fill IDs join to durable intent and accepted order with matching client/order/side, executed price within the buy limit and total filled quantity within the intent. This establishes consistency of the retained application records, not an independent venue balance export.

First window: five maker fills (Up5@.46, Down5@.48, Up3@.50, Down3@.43, Up5@.42). Second: six maker fills (Down5@.49, Up5@.46, Down3@.57, Up5@.40, Up1@.36, Down2@.53) and one taker lock fill Down1@.85 with$.009fee. The second window's4lock intents include this eventual one-share completion. Existing source `speeddesk_live_model.py:676` explicitly permits risk-reducing completion locks outside ordinary spend budgets while retaining fresh cash, reconciliation, exact unpaired size and price checks; `speeddesk_live.py:2078,2185` implements the pre-existing lock path. Thus gross cost$10.73 plus fee is not evidence that the$10ordinary window cap was increased. No cap change was made.

The81-intent/80-ack difference is explained by exact client `nc-speed-090358bcf4984ad49c332f016d8e1f95`: durable Up5@.34rest intent at05:16:30.814201867, followed by05:16:30.815182428 original record **“not sent; prices moved before send”**. It has no accepted order or fill in the saved cohort. This is retained as a last-moment guard outcome, not silently dropped or described as a missing successful acknowledgement.

Accepted-order fill rate means distinct accepted order IDs with an observed fill divided by distinct accepted order IDs:5/40=12.5%,7/40=17.5%,combined12/80=15%. Intent fill rate uses distinct durable client IDs:5/40=12.5%,7/41=17.073%,combined12/81=14.815%. These are not win rates or volume-weighted execution rates. Exact cancellation records remain in JSON; a settlement/filled-order join does not itself prove every intermediate order state from raw venue exports.

## Scoped original real-order latency

| Metric | First samples | First median / maximum ms | Second samples | Second median / maximum ms |
|---|---:|---:|---:|---:|
|BTC exchange→decision|40|202.231 /662.100|37|276.439 /1969.490|
|BTC callback receipt→decision|40|101.141 /628.154|37|263.003 /1748.996|
|Decision→validated acknowledgement|40|84.252 /696.443|36|85.856 /318.918|

These are individual original `real_kalshi` timing samples attached to exact-ticker intent/order records, all returned with statusok. Second-window source/receipt metrics cover37regular rest intents, including the not-sent intent; acknowledgement metrics cover36accepted regular orders. Four lock orders are included in the financial accepted-order denominator but have no corresponding samples in these original metric rows. Their latency is not assumed to be zero. No pooled quantile, daily/lifetime status median or venue fill-wait statistic is substituted. Exchange/local clock uncertainty remains, callback receipt is not network ingress, and acknowledgement latency includes journal/queue/HTTP.

## Coarse account responsiveness and publication coverage

| Fixed window | Selected reconcile cycles | Retained reads | Largest worker-completed→coroutine-resumed ms | Covering loop intervals | Largest covering loop lag ms |
|---|---:|---:|---:|---:|---:|
|05:00–05:15|4|20|420.597|16|997.7|
|05:15–05:30|9|46|546.519|16|1479.7|
|Deduplicated union|13|66|546.519|31|1479.7|

All selected cycles overlap the fixed interval; every read in those cycles is retained conservatively, including straddlers. The largest actual resumption is cycle1037,list_orders: worker_completed61.254ms, coroutine_resumed607.773ms. Both windows have predecessor and following status endpoints and14fully-contained loop intervals each; the union keeps one shared boundary interval once. No required read marks or reads are omitted, no missing loop interval or8192-sample cap is observed. The second window omits43whole-cycle slow-work detail rows; zero read-resumption detail omissions are reported. No selected WorkTrace/bin retention loss or disabled observer appears. None of this implies exhaustive WebSocket freshness coverage.

Endpoint cohorts are checked as timestamped populations, not by subtracting cumulative maxima:

| Original status UTC | Begun/completed cycles | Quiet | Reported originals matching cohort |
|---|---:|---:|---:|
|04:59:52.036788536|404|395|9|
|05:14:46.264555190|1000|987|13|
|05:15:46.240553473|1041|1025|16|
|05:29:55.129865031|1585|1563|22|
|05:30:51.237373523|1626|1602|24|
|05:31:51.579082601|1670|1645|25|

At all six endpoints, active/unfinished,suppressed,buffered and dropped counts are0; reported-original cohort counts match, and no cycle-counter reset is observed. These endpoint totals include startup/tail and are not themselves fixed-window counts. Quiet cycles provide no individual read-timing rows; the coarse interpretation rests on the source's selection and covering-lag semantics, not an invented per-read complete tape.

## Source freshness and exact local intervals

First window has20source-age/invalid-timestamp warnings (18orderbook_delta_network,2trade_network) plus1market_set_changed warning. Second has27 (25orderbook_delta_network,1trade_network,1book_engine). Separately there are20/27gap diagnostics and29/32status diagnostics. Every fixed-window warning/diagnostic has explicit main reader `kind=speeddesk,instance=1,process=1`, qualified by this deployment and supplied startup incarnation; no derived or unidentified producer occurs in these fixed populations. Older pre-PR58 shared-logger evidence cannot be retrospectively classified using these new labels.

Four known rejected-message receipts prove protocol-acceptance→public-recv local residence:

| Original diagnostic UTC | Known residence ms | Full-bin synchronous-work lower bound ms | Retained full bins | Shown / retained slow spans | Omitted slow details |
|---|---:|---:|---:|---:|---:|
| 05:01:46.361 | 2895.428 | 2212.684 | 92/92 | 8/62 | 54 |
| 05:05:56.818 | 2890.691 | 1899.181 | 92/92 | 8/49 | 41 |
| 05:22:34.391 | 2695.675 | 2121.228 | 86/86 | 8/54 | 46 |
| 05:24:51.792 | 2625.561 | 2195.023 | 83/83 | 8/52 | 44 |

First-window detail examples: practice_daily_reports255.766ms wall/247.091ms threadCPU nested in practice_checkpoint461.188ms; another incident includes live_checkpoint363.577ms and nested live_ledger188.773ms wall/40.373ms threadCPU. At05:22:34, practice_checkpoint584.235ms contains practice_state331.649ms and practice_panel324.841ms (panel CPU301.931ms). At05:24:51, practice_checkpoint599.224ms includes practice_state251.633ms wall/248.449ms CPU and practice_ledger276.240ms wall/40.422ms CPU. These are positive overlaps, not exhaustive or exclusive causal assignments. Nested durations and full-bin lower bounds must not be added. Ledger wall remains distinct from serialization CPU, I/O, lock wait and descheduling.

The other43gap receipts are overflow-unknown (18first,25second). Unknown receipt is not proof of preacceptance delay or absence of local buffering. Sending and engine timestamps are retained with raw integer/null type and separately computed apply ages; provider timestamps are not receipt times. Exact acceptance still excludes earlier local/kernel/network/provider delay. Connection counts and maxima are per explicit reader/session samples, not final connection totals. Same-session candidate warning/diagnostic joins do not merge distinct log-time populations. No pooled before/after causal estimate, count-rate improvement claim or complete freshness summary is justified.

## Startup, tail and latest dated status remain separate

Startup partial04:49:27–05:00 has35source-age warnings (34main,1derived), separately36gap diagnostics (34main,2derived), with distinct log-time boundaries. Main known residence samples are2931.768ms at04:51:45,2776.308ms at04:54:07 and2994.887ms at04:55:34. Derived-reader incidents stay derived. These do not enter the two fixed observation counts.

Prior ticker `KXBTC15M-26OCT150100-00` published+$1.11 settlement at05:00:07.913777506. It includes old-process/restart inventory and is excluded from both fixed P&L totals. The new-process capture contains only six of its fills, cost$5.79; prior inventory continuity is addressed separately by `/workspace/shared/live-mirror-restart-audit.json`. Next ticker `KXBTC15M-26OCT150145-45` has one captured fill costing$2.95 with$0fee and no captured settlement; it remains an unsettled partial, excluded from fixed results.

Latest retained real status is **05:31:51.579082601 UTC**: cash$32.9304, reserved$1.60, open cost/risk approximately$2.95,1open order,1position; cumulative651fills,fees$2.71652,P&L−$13.861. That cumulative P&L is consistent with earlier−$13.642 plus the excluded+$1.11 prior settlement and fixed−$1.329; it is not a stop/resume baseline or the fixed-window result. Cash is a dated balance observation, not inferred from summing these settlement P&Ls. At this snapshot trading_now=false and waiting=`Kalshi account data stale`; no readiness claim is made.

Periodic observations retain clip5/open20/window10/day-stop6/total-stop10, authenticated and fee_precision_verified true, total_halted/day_stop_latched false, integrity_error null, cleanup_pending false. Snapshot status is not continuous proof, and consumed stop/resume anchors are not exported here. Absolute historical P&L alone does not show a budget-stop failure.

## Reproduction and receipts

JSON `/workspace/shared/mirror-postrelease-two-window-audit.json`, SHA256 `ae22e1bee4ab0f8387fb88c0ec16833c06b4df13f39f90ad6bfbd351841c4b72`.
Parser `/workspace/shared/mirror-postrelease-two-window-audit.py`, SHA256 `a5d9abeced50d9782479b7f896317366c7af9bf637b5b6248fce97736f794bc3`.
Immutable input SHA256 `800d9bc39e3d4247312c75c2f64c41b046294f4db98b5a899b29b7eb659a9401`.

The parser checks closed/stopped status, fixed tail, exact deployment/source, contiguous query coverage, below-cap responses and response-file hashes before freezing. `audit_window` can be imported for offline replay against the immutable input; the command-line entry point refuses to replace an existing different input. Pinned source hashes, original IDs, exact order/fill/settlement joins, typed timing samples, status intervals, omitted details and the earlier first-report comparison are all in JSON. Derived-comparison hashes refer to the saved derived artifact at audit time, not the independent computation's authority.

The reviewed ledger-stage diagnostic bundle is separate work and was not deployed within this capture. Its optional measurements may help separate conversion/encoding/lock/SQL/commit elapsed time, but this audit selects no further scheduler/storage correction and changes no financial guard. EXEC-DELAY-001 remains open.

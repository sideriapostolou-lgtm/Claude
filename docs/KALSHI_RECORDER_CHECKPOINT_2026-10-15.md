# Recorder feasibility checkpoint — October 15, 2026

**Checkpoint prepared at 3:52 PM PDT. Collection is online; feasibility remains INCOMPLETE / UNVERIFIED.** No trading, configuration, deployment, volume or billing change was made. This is a bounded operational checkpoint, not the completed preregistered Phase 0 report or authorization to start TRAIN.

## What is verified

At **3:45:05 PM PDT October 15** Railway reported recorder deployment `8453f919-b891-4aa7-8478-6fcf6b9c24ee` SUCCESS, 1/1 running replicas, zero platform warnings/criticals and no recent deployment failure in the requested one-hour health window. Its source is **`a0782b743a31369fe25ddf6d2eea96df8511cd8d`**, branch `claude/kalshi-recorder`, region us-west2. Deployment completed October 14 around 9:38 AM PDT. A later docs-only recorder commit was SKIPPED; it is not the running code.

Service-scoped startup/evidence queries, retrieved **3:50:52–53 PM PDT**, cover the fixed requested interval **October 13, 3:30 PM → October 15, 3:45 PM PDT**. The first returned startup is October 13 at 3:37:54.909 PM PDT (application timestamp). Five startup records are retained. Early startups explicitly say `spot=False`; the first returned `spot=True` startup is October 14 at 7:33:29.584 AM PDT. These are start records, not continuous uptime or per-exchange tick coverage.

The service-scoped evidence query returned the **same 31 original metadata messages** as the deployment-scoped query; it recovered no earlier manifests. Neither query reached its limit or returned an API error. The metadata describes 31 contiguous, hour-sized periods, **October 14, 8:00 AM → October 15, 3:00 PM PDT**. The first is a startup readback of the prior saved hour, not a new hour recorded at readback time.

## Requested evidence and its limits

| Item | Actual evidence / limitation |
|---|---|
| Captured duration excluding gaps | **Unknown.** Metadata totals 1,822 coarse sampled minutes (30 h 22 min), not a union of verified recording intervals. The October 14 9–10 AM period has only 22 sampled minutes despite `partial=false`. No raw gap intervals or verified lane coverage were available. These 31 hour-sized periods do not document the required 48 hours of actual capture. Capture before October 14, 8 AM and the October 15 3–3:45 PM tail are outside the exported manifest periods; this is missing exported evidence, not proof the raw files are absent. |
| Gaps / coverage | 31 gap records in the 31 saved periods: 29 spot reconnects, one recorder-not-running, one recovered partial segment; lanes spot=30, all=1. Counts cannot be subtracted as seconds. All receipts explicitly say `coverage_certified=false`, `segment_hashes_reverified=false`, `per_venue_spot_ticks_verified=false`. Spot envelopes contain batches, not individually verified ticks. |
| Freshness | Last saved hour reports candidate-book fresh share 1, 60 sampled/BTC-fresh minutes and zero pending backfills. This does **not** establish complete windows, complete trade tape, the protocol's decision/day coverage floors or absence of unsealed-tail gaps. |
| Quote survival | **Unverified.** No raw books/prints/arrival-and-queue reconstruction. Healthy logs cannot show that a quote survives the frozen latency or would fill. |
| Depth at frozen budget | **Unverified.** No category-by-category favourite-bid queue/depth or count-only funded-cluster calculation. Family A uses independent **SIMULATED $25 cash, $2/cluster, $4 outstanding, $3 day, $5 lifetime**, one contract per market/one quote per cluster; these are not the live bot's different limits. |
| Fees | **Unverified actual costs.** Fee-lookup metadata is not dated series/event terms or fill-level accounting. Preserve the frozen direct-account decimal rounding, per-order accumulator/rebates and scheduled fee changes; do not substitute a flat maker/taker assumption. |
| Latency | Last saved hour (2–3 PM PDT) REST book RTT p50/p95/p99 **87.442/179.550/268.184 ms**; trade-receive lag **3.771/7.456/12.117 s**. These are saved-hour percentiles, not pooled percentiles, order acknowledgement latency or measured trading speed. Host clock offset was not available. |
| 429s / errors | All saved per-lane error/429 counters are **null, not zero**. Extended service log queries returned zero matching 429 warning lines and zero Tracebacks, within their fixed bounds. The warning query returned 65 application warnings: 35 gap and 30 spot disconnect messages; no storage warning among them. The broad ERROR filter returned 61 false positives (30 WARNING disconnects containing `error=`, 31 INFO metadata lines containing `errors:null`), with **zero literal application ERROR-level messages**. These bounded searches do not certify every request or all 48 hours. |
| Raw verification | No production `status`/`verify` output or volume export was available. Metadata hashes identify saved manifest bytes/index-at-seal records, not independently rehashed gzip contents. |
| Execution / profitability | No quote/outcome joins, replay, simulated fill/P&L or live execution measurement were performed. None is inferred from uptime. |

The saved metadata's 31 gap records and the extended logs' 35 gap messages refer to different time ranges/populations; they are not interchangeable.

## Storage and cost decision before October 20

Recorder-owned saved storage rose from **217,975,859 bytes at October 14, 9:00 AM PDT** to **609,484,884 bytes at October 15, 3:00 PM PDT**. Difference: **391,509,025 bytes over exactly 30 period-end hours**, or **313,207,220 bytes/day (~0.313 GB/day)**. All 31 saved snapshots show cap **4,831,838,208 bytes (4.5 GiB / 4608 MiB)**, storage level 0 and zero deleted segments.

The separate Railway one-hour metric summary, requested at **3:45:05 PM PDT**, gives latest disk **0.799113216 GB**, memory **0.879640576 GB / 0.99999744 GB limit** (about 88%), 121 samples. It provides no individual sample timestamps. Platform disk scope and the earlier recorder-owned figure differ; neither is a verified free-space audit. CPU-limit metric reports 8, whereas the older handoff said 0.5 vCPU; no configuration was read back or changed to resolve that discrepancy.

At the observed all-lane rate, **28 additional days would add 8,769,802,160 bytes (~8.77 GB)**, exceeding the present cap even before existing data. **This is a constant-rate scenario, not a forecast or a Family-A-only requirement.** The 72-hour BTC/spot rotation has not been demonstrated at steady state, and retained Family A lane growth/free physical space remain unaudited.

Before October 20, the owner needs an evidence-backed retention decision if the planned retained data do not fit: authorize sufficient dedicated storage/cap, or authorize the protocol's **hashed, lossless compaction of all replay-required fields**. A separately approved reduction of eligible BTC/spot retention may help, but cannot erase unscored Family A evidence. No resize, cap raise, deletion or configuration change was made. The existing nominal cap meets the protocol's old 4.5-GB option; it does not prove capacity for actual TRAIN/VAL/TEST retention.

**Measured hosting cost: unavailable.** No dated Railway usage/invoice export was accessible. Resource metrics, an old price quote or storage growth are not actual billed cost. Protocol OPEX_A fallback **$0.0821/day** is a preregistered assumption (half of $5/30.4375 days), **not a measurement**.

## Access blocker and exact next evidence

The current connected Railway toolset exposes logs/metrics and management operations, but no service command execution or volume-file export. No remote verification command was attempted or claimed successful. Required evidence is an authorized **read-only, dated export** of:

1. Recorder `status` and `verify` results, `index.jsonl`, saved manifests, gap/trade-coverage intervals and lane storage/retention inventory, including unsealed-tail limitations.
2. Permitted **Phase 0 / non-TEST** books, prints, admission metadata and dated fee terms sufficient to measure queue/depth and quote survival at the unchanged simulated budget and latency. Do not include or open future TEST rows.
3. Actual incremental Railway usage/cost for the dated collection interval.

These permit gap-excluded duration, verified hashes, per-lane coverage and retention fit to be calculated before any phase start. Missing access remains open; another healthy log check cannot close it.

## Source and protocol integrity

Requested operating records were read on `claude/nightcrawler-memecoin-bot-Gwnb1S` at `f77ba0dc20961221466810d072da0ee8c04b1f38`. **`docs/KALSHI_RECORDER.md` returned GitHub 404 NOT_FOUND on that branch.** It was successfully read instead at the exact running recorder commit ([source guide](https://github.com/sideriapostolou-lgtm/Claude/blob/a0782b743a31369fe25ddf6d2eea96df8511cd8d/docs/KALSHI_RECORDER.md)), blob `562755f2fb0d39c7627b8627fd86bf6fc7caaf45`; no recorder source was copied onto the bot branch.

The exact running-branch protocol content independently hashes to **`40ccfe87ed86b3fd62ee16ebba9862f8be8bbc66a229cfdc7f138ee26a305040`** (`kalshi-familyA-v1`). It remains unchanged. Phase 0 requires at least 48 hours **actual** capture, count/depth/queue/coverage/latency analysis and no outcome joins/P&L. This incomplete checkpoint does not start TRAIN; T1 remains governed by the complete Phase 0 report and retention prerequisites. TRAIN/VAL/future TEST gates, freeze and error budget were not changed; future TEST was not opened or consumed.

Evidence: [machine summary](../research/kalshi_recorder_checkpoint_2026-10-15/EVIDENCE_SUMMARY.json), [31 original timestamped metadata messages](../research/kalshi_recorder_checkpoint_2026-10-15/SAVED_METADATA.jsonl), [bounded startup/warning/filter messages](../research/kalshi_recorder_checkpoint_2026-10-15/BOUNDED_LOGS.json). Public files are allowlisted derivatives, not complete volume exports. Private native wrapper SHA-256 `7dec23a3571d7aa605429c0de8031671f38cbbe74a37d97d528b6ee33503e479`; an independent arithmetic review passed 46 checks without certifying coverage or profitability.

PR #67 remains **ready, unmerged and undeployed** under this task's explicit read-only production instruction. Its local checks are complete; source release, integration with newer documentation and runtime evidence remain on the existing EXEC queue. Other unfinished operating transfer work stays deferred; TJR/MNQ remains last.

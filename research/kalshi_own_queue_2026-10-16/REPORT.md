# Own-order queue evidence, October 15–16, 2026

This release adds diagnostics, not a new trading strategy. Real/practice fill disagreement is demonstrated; its cause and a profitable first-entry rule are not established. The existing daily loss stop remains active. No resume, stop reset, cap increase, trading rule, Polymarket change or Railway variable change is part of this task.

## Why this is the next experiment

Two complete losing-window log exports show real fills while the copied practice desk reports no fills:

| Window ending, Pacific October 15 | Actual fills and result | Practice twin |
|---|---|---|
| 10:30 PM (`KXBTC15M-26OCT160130-30`) | Up 2 at 48¢; late Down 2 at 90¢, 1.26¢ fee; net **−77.26¢** | Eleven ordinary rests/cancels, zero shares |
| 11:00 PM (`KXBTC15M-26OCT160200-00`) | Down 1 at 44¢, no matching Up fill; net **−44¢** | Four ordinary rests/cancels, zero shares |

The first window's late hedge reduced the actual worst loss by **18.74¢**; simply removing it is not an evidenced correction. Neither window ever qualified for the existing positive equal-pair protection. Initial unmatched entries remain risky. The second window's later waiting reasons include `lock_price` and `no_ask`; those are not evidence a cheaper executable hedge existed earlier.

The simulator seeds the queue from displayed same-price bids and drains it from eligible public sell prints. Displayed-depth cancellations alone do not advance that modeled queue. A preserved synthetic reproduction demonstrates this mechanism, not the cause of either historical fill. Missing tape, priority, timing and cancellation races remain alternatives. Replacing the simulated queue with actual fills would conceal the disagreement rather than validate execution.

The original 145-row and 93-row bounded native exports, original presentation-based extraction and a separate root structured-message audit are preserved. Filtered unsaturated exports do not certify complete venue tape or all private-account activity. Initial-entry markout coverage is missing; the measured late-hedge markouts cannot establish the first entry's adverse selection.

## What the observer does

The official authenticated GET `/trade-api/v2/portfolio/orders/{order_id}/queue_position` returns `queue_position_fp`: preceding shares/contracts under price-time priority. It has no server snapshot timestamp or returned order identity. Public documentation and a selected schema extract are preserved; the full schema with unrelated key examples is excluded.

Only newly acknowledged locally owned ordinary maker IDs enter a 32-ID registry. Controller and reserved financial terms must agree; terminal, uncertain, cancellation-requested, foreign, changed-window and unsupported orders are excluded. Startup/recovered orders are not backfilled. At most one own-order read is in flight, at most one dispatch per second. No eligible order means no HTTP. Faster-lived and unselected orders can remain unsampled.

The read uses an isolated connection and one dedicated worker, existing signer, fixed HTTPS origin/path, GET only and no retry/redirect. It preserves inherited proxy/CA handling while preventing netrc/cookie authentication substitution. It claims spare existing read capacity without waiting, leaves one local account-read slot, and never acquires execution transport locks. This does not create extra venue quota or prove zero shared-resource interference. Observer 429/auth failures back off/disable the observer only.

The receipt joins dispatch and completion real/twin identity, remaining quantity, price, status and modeled queue. A partial fill, reprice, cancellation, missing order, closed gate, stale reading or error remains unknown. Raw fractional queue zero is not a fill. No observer result changes the practice model, real inventory, accounting, stops, live decisions, learner or risk book.

Selection, worker-start and return clocks are local; intervals include scheduling, budget, signing and decoding. They are neither pure network RTT nor exchange event time. Session IDs/version and explicit dropped counters separate restarts and gaps.

Publication uses existing checkpoints only, with a 64-row buffer plus one separately bounded 64-row pending batch. It does not force extra financial saves or enter latest-events history. Shutdown stops admission, completes real cancellation/reconciliation and the final durable financial checkpoint before waiting for the optional reader. A late sample may be counted unpublished. An underlying concurrent Future, rather than a canceled asyncio wrapper, determines whether the Session/account lock can close.

## Bounds and operating limitations

Response bodies are limited to 8,192 decoded bytes, with one-second connect/read phase timeouts and a two-second body-phase elapsed guard. These are **not an absolute wall deadline** for slow headers or other network phases. One stuck optional worker prevents further observer reads and can delay final process close, although real cancels and final financial durability precede observer drain.

At uninterrupted eligibility, one read/second is **86,400 reads/day**. A corrected fake-desk audit with actual-format UUIDs measured a 1,325-byte compact receipt, a 1,433-byte representative log line and a 1,771-byte queue-panel mirror property. Continuous 1 Hz projects to about 123.8 MB/day of representative log rows plus 15.3 MB/day of queue-panel bytes across existing ten-second mirrors, before database/transport/filesystem overhead. Actual checkpoint assertions confirm queue receipts never enter latest-events history. An earlier audit incorrectly assumed 20+10 queue copies in latest-events; its 371 MB/day estimate is withdrawn, with the original and correction retained. An extreme permitted Unicode-context receipt measured 19,771 bytes; the conservative 32 KiB receipt bound implies up to 2.83 GB/day receipt-only in that artificial continuous case. These are synthetic size/rate bounds, not measured production duty, storage or dollars. Bounded memory does not bound persistent growth. Actual populated logs, amplification, truncation, venue headroom and retention/cost must be measured before claiming inexpensive sustained coverage. No service, volume, storage cap or paid access is changed.

## Checks and source identity

Frozen implementation patch SHA256: `b9a08ba4a1981123dfb6e2e00bf3d1bb1d24f43df69050ff1dab29a339ee7e09`, based on coordination-only `0034dc84` over application source `66d122b5`.

- Full pytest: **6,163 passed / 14 existing skips**, 307.74 seconds; no failed tests.
- Focused execution/safety/queue groups: **294 passed** in 17.08 seconds.
- Mypy: **132 source files clean**. Ruff: all **five changed Python files clean**.
- Independent exact-patch review: **96 passed**, including **27 independently written cases**; no blocking source finding. Conditions: full suite and actual restart/retention verification.
- Identity/terminal mismatches, malformed/error/oversize responses, stale/context races, read-budget contention, blocked observer versus cancels, canceled async wrappers, bounded failed publication and financial/practice/stop invariants are exercised with fakes only. No account test order was sent.

Earlier failed fake fixtures/checks and the review's corrected source-hash transcription/network advice remain disclosed in the archived handoffs. Synthetic checks do not prove profitability or actual fills. The full public API schema, private operating handoffs, credentials and unopened research TEST are excluded.

## Release and next evidence

**Deployed and idle-verified:** [PR70](https://github.com/sideriapostolou-lgtm/Claude/pull/70) merged October 15 at **11:54:03 PM PDT**. Exact source `5b2fb163ac701042dcf93a5b14c61e7cd1bddef1` / tested tree `57bfe4d9a21d0c5bea7f71a96c225914c83e562f` is running as Railway `39d26485-3c73-4af7-b0e6-6a7e161636d2`, SUCCESS **11:55:02.591 PM PDT** (health reports .590, a one-millisecond reporting difference). All ten candidate files were read back exactly; the merge tree equals the tested candidate tree. Normal Polymarket startup at 11:55:00 reports LIVE, ten contracts/order. Bot and unchanged recorder `8453f919` were online 1/1 with no platform warnings/criticals. No returned matches in the bounded traceback queries; this is not an all-time error certificate.

Independent native audits passed **207 restart checks plus 176 follow-up checks**. Post-restart selected financial fields and scalar day/total summaries match before restart, including losses, fees and fill counts. Rung0/current limits and ignored-already-used resume/day-reset/integrity-reset receipts are retained. Dynamic ladder stop/quiet timestamps advance under the stop; the whole ladder is not claimed byte-identical. Native snapshots are not raw-ledger or volume certificates.

At **October 16, 12:01:15 AM PDT**, the observer is enabled/error-null, same session, 274 no-candidate opportunities, zero reported starts, no in-flight read, empty registry/buffer and no last sample. Cash remains $25.1219, cumulative settled −$24.6195/current UTC-day −$5.1277, reported open risk/orders/positions/reservations zero. The daily stop remains active; no cap, resume/reset or configuration change occurred.

The observe-only probability source fingerprint/active epoch2 and two archived summary objects survived unchanged. The 11:50 PM pre-restart frozen forecast was scored at **12:00:09.763 AM PDT**: all **15 frozen fields** match exactly, including original timestamp, probabilities and terms; `child_restart_gap` remains recorded. This verifies one forecast body, not every archived body or continuous coverage. Its Up outcome was a prediction score, not a real trade/profit. The earlier 25-score panel's shadow Brier0.16334 versus baseline0.15713 does not establish a calibration gain; no learner is promoted. The later empty aggregate-status query cannot certify a new aggregate count.

Early startup returned no Kalshi status before initialization, followed by a cold stale-input status and one split/truncated log fragment; these originals are retained. Feed connections/subscription followed, with `missing_book_source_timestamp` REST fallback reported. We do not claim uninterrupted fresh books or tape. The pre-release status request returned four rows despite requested limit3; neither that query nor a count below platform maximum proves completeness. Independent coverage labels were explicitly corrected with originals preserved.

The [93-file lossless evidence manifest](RUNTIME_MANIFEST.json) and six parts preserve native exports, exact code/check receipts, public schema extract, original/corrected reviews and derived audits. [Offline restoration](REPRODUCE.py.txt) verifies all bytes/hashes, reproduces both bounded losses and reruns both native audits byte-for-byte. A first archive privacy scan falsely classified nine added pytest decorators as email addresses; only that exact code string was exempted in the task-local builder, with originals/correction retained and other privacy checks unchanged. The full public API schema, private operating handoffs and unopened TEST remain excluded.

[Fixed future natural-order cohort](CAPTURE_DECLARATION.md): **October 16, 5–6 PM PDT**, tail6:02. It includes stopped/no-order/unknown cases; source/settings changes invalidate the primary comparison and must not silently shift its hours. The declaration creates no order, resume or background Codex session. Actual populated queue coverage and profitable first-entry correction remain OPEN.

Before release, retain the latest actual cash **$25.1219**, cumulative settled trading P&L **−$24.6195**, current UTC-day P&L **−$5.1277**, reported open risk/reservations/orders/positions **zero**, daily stop latched and total stop not latched. These are the 11:49:03 PM PDT October 15 returned panel (payload 11:49:01 PM), not a fresh all-account balance certificate. Caps remain **$10/window, $20 open, $6/day stop, $10 total-stop allowance, clip 5, ladder rung 0**. Loss budgets are not silently renewed by this deployment. Observe-only probability/source/archived scores must survive separately; no learner is promoted.

After exact source deployment, verify normal Polymarket startup, no returned bounded-query tracebacks, retained finances/controls/learning epochs and enabled/idle diagnostic status. With the daily stop active and no resting orders, idle health cannot validate the authenticated queue endpoint or actual queue/fill coverage. Keep that substep open until naturally eligible orders exist; do not resume or create an order for diagnostic coverage.

Next bounded experiment: declare a future fixed natural-order cohort before observing it, freeze source and financial settings, then join queue interval receipts to exact real/twin IDs, actual fills/cancels, public-print/gap context and measured logging duty. Preserve unsampled/changed/stale cases and all losses. Use the result to choose one falsifiable modeling or entry-risk correction, then validate it prospectively; do not claim a profitable counterfactual from queue decline alone. Overall EXEC/profitability, recorder raw-volume/retention/cost and operating transfer remain OPEN. TJR/MNQ stays LAST/queued; no Page, duplicate research or automation action is needed while these prerequisites remain open.

Primary documentation: [queue endpoint](https://docs.kalshi.com/api-reference/orders/get-order-queue-position), [authentication](https://docs.kalshi.com/getting_started/api_keys), [rate limits](https://docs.kalshi.com/getting_started/rate_limits). Last public check October 16 UTC; actual account tier/endpoint-specific token cost remains unverified.


Timing correction: GitHub's actual PR70 merged_at is **11:54:03 PM PDT**, one second after the 11:54:02 pre-call clock used in the earlier report; the archived pre-call clock remains unchanged.

Docs-only evidence commit `ed0dde5c87da9337d15ee5eeb168bacabc8eed0f` was verified SKIPPED as Railway `0ecedbf1-c7c2-4289-8e10-00f5ee26d82d` at 12:06:58.563 AM PDT; all 14 evidence/docs and five source/test files read back exactly. Bot39d and recorder8453 remain online1/1 with no platform warnings/criticals. [Closure metadata](CLOSURE.json) records these post-publication checks.

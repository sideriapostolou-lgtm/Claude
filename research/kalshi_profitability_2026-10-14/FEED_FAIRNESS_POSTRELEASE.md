# Feed scheduling: post-release observations, still open

Owner-facing times are October 14, 2026, Pacific daylight time. This report follows
the unchanged [prospective verification protocol](FEED_FAIRNESS_VERIFICATION.md).
It does not relax freshness checks, change trading rules or authorize deployment.
Source is `c8e37e5504aad04da0521b3f95c17f86dac42899`, verified in the
[release receipt](feed_fairness_release.json). The restart partial window is excluded.

## Closed two-window capture, 5:32 PM

Both preassigned windows and the bounded publication tail are now closed; all
collector jobs stopped at 5:32:25 PM. Root verified the immutable receipt hash.
Final independent original-query audit agrees with these results and the limits
below. It corrected omission scopes and trace/log timestamps before publication.
The earlier first-window snapshot below is
preserved; its pending settlement/publication items are resolved by this capture.

The [derived report](feed_fairness_two_window_report.json),
[exact evidence archive](feed_fairness_two_window_evidence.zip) and
[member/hash manifest](feed_fairness_two_window_evidence_manifest.json) preserve
the final raw receipts, independent audit and earlier classifier/extraction versions.
These are bounded filtered runtime logs, not a complete raw market tape or direct
volume/ledger export. Raw recorder segments and future late events are unverified.

These are **real Kalshi fills and venue settlements**, separate from simulated
events also retained in the raw archive. Both windows acquired twelve matched
Up/Down pairs; gains come from combined acquisition costs below the pair payouts.

| Pacific window | Fill events | Contract cost | Actual fees | Gross payout | Net locked P&L |
|---|---:|---:|---:|---:|---:|
| 5:00–5:15 PM | 6 | $11.58 | $0.0698 | $12 | +$0.3502 |
| 5:15–5:30 PM | 11 | $10.79 | $0.0448 | $12 | +$1.1652 |
| Both | 17 | $22.37 | $0.1146 | $24 | **+$1.5154** |

Directional residuals are floating-point noise. Both $12 pair credits were
already returned; net settlement payouts were zero. Fees are included once.
The second ticker is `KXBTC15M-26OCT142030-30`; venue settlement 5:30:04.146 PM
was observed at 5:30:08.195 PM. Its 11 fill events include two partial fills of
4.89 and 0.11 contracts. Durable intents/accepted IDs are 125/124 and 105/101,
including lock intents; every captured real fill links to an intent and accepted order.
Cancellation rows include 404 responses and retained reservations, not proof of
immediate liability release. No cap or financial rule changed.

Seventeen intersecting selected cycles contain 85 reads. Maximum actual local
resumption **among those selected reads** is **639.372 ms**, versus 512.814 ms in
the first window's selected reads alone.
Thirty-one distinct covering status intervals include both outer boundaries;
maximum loop lag is **1,280.3 ms**, maximum sample count 2,771 below the 8,192 cap.
There is no observed recurrence of the frozen coarse 3,000 ms local criterion.
Required marks/read retention, enabled/error state, report delivery and endpoint
cohort completion are checked; quiet unselected reads still lack individual marks.
Read-resumption work queries omit eight/three span details; whole-cycle callback-work
queries additionally omit seventeen/thirty-four details. These populations can overlap;
never add them as distinct missing work. No read or bin retention loss is reported.
This is neither an all-read 250 ms/subsecond claim nor a causal improvement estimate.

The last minute status at 5:31:21.409 PM has 1,619 begun = 1,599 quiet + 20
reported cycles. Railway logged the later original trace at 5:31:53.445 PM with 1,647 = 1,626
quiet + 21 reported; its payload completion was 5:31:51.952 PM and producer
logger wall was 5:31:53 PM. These are different times, not a counter mismatch. Target
endpoint cohorts 956 and 1,574 completed in later statuses with zero buffered
reports; no suppression, dropped reports, query caps or parse/query errors.

**Freshness remains unresolved:** 58 logged warnings in the target period comprise
53 source-age warnings, two market-set transitions and three REST trade-gap
`ValueError`s. Their raw timestamps and messages remain intact. A local scheduling
absence result cannot clear this surface or establish continuous fresh coverage.

At the dated 5:31:21.409 PM status, cumulative settled trading P&L remains
**−$12.9217**, cash **$37.1197**. The next window already has $4.70 gross filled
cost, zero modeled filled risk and a $1.62 reservation in one order; its guard
says uncertain order/reconciling, no new orders. Zero modeled risk is not zero
gross exposure. Authentication succeeds, both stop latches are false, integrity
is clear, and effective caps remain $10 ordinary window/$20 open/$6 UTC day/$10
total, clip five. Ladder remains rung zero, promotion not ready. These are dated
logged facts, not current cash or direct exports of raw stop anchors. Both platform
services are online; running source/deployments are unchanged.

Final original receipt: 23,055,473 bytes, SHA256
`12cb101030c3b9ded3a6a25f593fbb0830c9203ad0338043999f7bc43da96cfd`.
Its earlier intent-classifier version is preserved too (SHA256
`655dfd0dbd8c62a51da53a5b1326b24fdfdef9a461a87c0cb65e0dd880838394`).
Root verified raw queries and original events are identical across versions; only
derived interpretation was corrected to include the longer durable-lock state.
The independent audit is 194,559 bytes, SHA256
`4aab5a20c2c9574a3c92a80e4f3d17bf0d818200e9ee929a0e7c14a01b669813`.
Final archive: 5,498,164 bytes, SHA256
`d102c23b2a0211f717989dfa35314f5e9378504df79e57807b8bd4c84c04cce2`.

## First-window snapshot: 5:00–5:15 PM

Actual ticker `KXBTC15M-26OCT142015-15`. Independent original-message audit confirms
125 durable intents, 124 accepted orders and six actual fills, each linked to its
intent and accepted order. Twelve Up and twelve Down cost $11.58 plus $0.0698 fees.
The venue settlement timestamp is 5:15:04.153 PM; observed at 5:15:08.572 PM.
Gross payout $12 gives **+$0.3502 locked P&L**, with only floating-point directional
residual. The $12 paired credit had already been returned; net settlement payout
was zero. Do not credit the $12 twice or confuse cash with profit.

Gross all-in cost **$11.6498 exceeded the ordinary $10 window budget** through the
existing risk-reducing lock exception, not a cap increase. Before the lock, twelve
Up/eight Down cost $9.70 with $1.70 modeled worst-case loss. Four additional Down
at $0.47 plus the $0.0698 taker fee completed the pairs. Modeled risk became zero;
gross open cost was still $11.6498 until settlement. The existing exception is
documented in [PR #47's release report](PR47_DEPLOYMENT.md) and implemented in
`speeddesk_live_model.py:676`; ordinary buys retain their budget checks.

Seven selected cycles contain 35 reads with all required marks and no omitted
reads. Maximum actual worker-completed→read-coroutine-resumed delay is **512.814 ms**.
Maximum whole reconciliation cycle is **3,197.157 ms**, a different measurement;
its maximum individual actual resumption gap is 35.031 ms. Sixteen covering status
intervals cover both window boundaries; fourteen are fully contained. Maximum
covering loop lag is **1,046 ms**, with no sample-cap hits. Do not pool interval
quantiles or call these selected observations all-read subsecond execution.

Endpoint session counters reconcile: 956 begun = 948 quiet + 8 reported, zero
buffered. The ninth captured original report belongs to the next window, after
that status. Later publication-tail/cohort confirmation and the second window
remain pending in this first-window snapshot.

The window contains **21 source-age warnings**, one market-set transition and two
REST trade-gap `ValueError`s. Its positive settlement and coarse local timing
result do not clear feed availability. The earlier 4:15–4:30 PM source had zero
stale-age warnings in the bounded same-length query, one market-set transition
and one REST trade-gap `ValueError`. Different traffic and time periods prevent
a causal regression estimate; the increased warnings still require attribution.

Original immutable first-window receipt: 12,514,016 bytes, SHA256
`527cff43b675e116ee1278672a5f24a961eb4cca76c0b9adb89f7aacc650d8cd`.
Independent audit SHA256
`8cc5b31c7e8d91bd35aa6fc9ec13011ef367cabdf46f120cfa1e259d08eb7035`.
Exact receipts are in [the first-window evidence archive](feed_fairness_first_window_evidence.zip);
the [member/hash manifest](feed_fairness_first_window_evidence_manifest.json) records
all sizes and SHA256 values. This is an immutable first-window snapshot, not the
final two-window/publication-tail receipt.

## Offline work-amplification probe

The unchanged native parser/receiver and market-state code received the same
500-frame buffered synthetic burst. Each complete book message did an invented
5 ms synchronous workload. A separate `Event.wait()/clear()` controller surrogate
did either 12 ms per wake or zero work. The counterfactual removes exactly the
new complete-message yield; it changes neither parser nor stale threshold.

| Condition | Completed messages | Controller turns before reader ended | Account resumed after | Result |
|---|---:|---:|---:|---|
| Baseline, 12 ms work | 500 | 0 | Message 500 | Drained in 2.545 s |
| Candidate, 12 ms work | 176 | 176 | Message 1 | Message 177 rejected stale at 3.014 s |
| Baseline, zero work | 500 | 0 | Message 500 | Drained in 2.532 s |
| Candidate, zero work | 500 | 500 | Message 1 | Drained in 2.536 s |

Both book sides remain atomic. This establishes that more frequent wake-driven
work **can** improve account fairness while making buffered market data stale.
It does not run the production live controller, reproduce production traffic,
prove the cause of current warnings, or select a batch size/time budget/fix.
The unchanged three-second stale guard correctly rejected the synthetic backlog.
No socket, key, account client, order, source edit or production query was used.

Executed script SHA256
`eec9ac53e3802fa53b558ae71d342ddbdbec30bcf1cdd95fe7e94be08c0f039f`;
results SHA256 `037d301db23bd42e112c3be050269d0c9fa32da283c53843bf0a02be9c27d892`.
Session total 10.652 seconds wall; source hashes unchanged. Exact executed source,
results, baseline warning queries and failed resource query are in the same
first-window evidence archive; originals remain unchanged.

## What the callback counters can and cannot establish

An [offline status-counter inventory](feed_fairness_work_metrics_inventory.json)
was independently checked against original status messages. The candidate endpoints
5:00:13.322–5:14:16.291 PM span 842.969 seconds; prior endpoints
4:15:52.254–4:29:55.398 PM span 843.144 seconds. Only within-deployment count deltas
are compared; counters reset on restart, and neither span covers the entire window.

| Observed section count delta | Candidate | Prior |
|---|---:|---:|
| Practice checkpoints | 506 | 169 |
| Live checkpoints | 349 | 167 |
| Live panels | 612 | 275 |
| Book callbacks | 1,021,714 | 973,782 |
| Kalshi decode/apply | 542,100 | 519,186 |

These counts do **not** establish causal work amplification or CPU costs. The
prior interval starts after all seven target-window intents and both fills; it
contains no target-window order/fill/cancellation events. The candidate interval
contains 125 durable intents, 124 accepted orders, six fills and 123 cancellation
rows. Ordinary activity-driven work and different input traffic are major
confounders. Telemetry does not classify periodic versus wake-driven controller
turns or expose a dedicated REST-fallback counter. No quantiles are pooled,
cumulative maxima subtracted or nested CPU measurements added.

## Current decision and concrete next step

**EXEC-DELAY-001 remains open.** The fixed two-window capture and publication tail
are closed and independently audited. Attribute the source-age warnings
against receive/processing timestamps and controller wake/activity records before
selecting a focused correction. Current callback counts cannot isolate that cause.
Source age measured after receiving a buffered message cannot separate provider
delay from local backlog or clock effects by itself. No source release, real order,
deployment or financial-setting action is authorized by this read-only follow-up.

A candidate-only six-minute CPU metric request failed because the connector
requires integer `hoursBack`; it returned no CPU data. No mixed pre/post one-hour
aggregate is substituted. Existing telemetry may still lack queue-age or exact
controller wake counts; preserve those gaps rather than claim attribution.

The original/inverse/no-trade comparison remains unstarted. All earlier losses
remain recorded, real/practice results remain separate, and TJR authentic-data/
cost blockers and recorder verification obligations remain open. No profitability
claim, task completion, Railway variable, cap, stop or resume-budget change follows.

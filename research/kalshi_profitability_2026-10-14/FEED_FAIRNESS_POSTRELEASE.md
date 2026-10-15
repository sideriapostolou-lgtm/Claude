# Feed scheduling: post-release observations, still open

Owner-facing times are October 14, 2026, Pacific daylight time. This report follows
the unchanged [prospective verification protocol](FEED_FAIRNESS_VERIFICATION.md).
It does not relax freshness checks, change trading rules or authorize deployment.
Source is `c8e37e5504aad04da0521b3f95c17f86dac42899`, verified in the
[release receipt](feed_fairness_release.json). The restart partial window is excluded.

## First complete window: 5:00–5:15 PM

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

## Current decision and concrete next step

**EXEC-DELAY-001 remains open.** Preserve the fixed second 5:15–5:30 PM window and
bounded publication tail through about 5:32 PM. Independently audit both windows,
including observer publication/cohort coverage, financial records and freshness.
Then attribute the source-age warnings against existing callback/work counts and
timestamp definitions before selecting a focused correction. Source age measured
after receiving a buffered message cannot separate provider delay from local
backlog or clock effects by itself. No further source release during collection.

A candidate-only six-minute CPU metric request failed because the connector
requires integer `hoursBack`; it returned no CPU data. No mixed pre/post one-hour
aggregate is substituted. Existing telemetry may still lack queue-age or exact
controller wake counts; preserve those gaps rather than claim attribution.

The original/inverse/no-trade comparison remains unstarted. All earlier losses
remain recorded, real/practice results remain separate, and TJR authentic-data/
cost blockers and recorder verification obligations remain open. No profitability
claim, task completion, Railway variable, cap, stop or resume-budget change follows.

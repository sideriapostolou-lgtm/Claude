# Observe-only learning release: verified startup, no accuracy result yet

Recorded **October 15, 2026, 7:00 AM PDT** (14:00 UTC). This closes the bounded implementation/release
verification, not the open execution-delay work or a profitable-strategy experiment.

## Exact release and checks

[PR #60](https://github.com/sideriapostolou-lgtm/Claude/pull/60), **LIVE ON MERGE: observe-only Kalshi
learning; restarts real-money bot**, merged at **6:49:27 AM PDT** (13:49:27 UTC), inside a safe interval.
The owner requested real-time learning and separately gave standing approval for tested releases. The
queued TJR reminder granted no production authority and did not replace that existing task.

- Exact merge `933a43d2d7cb6d6dd27b4728d50c78ce0f488ed5` equals tested feature `6d7a123b` for the entire
  application and test trees. Controller, ledger, configuration, Kalshi client, Polymarket and build
  files match pre-release base `f0a0a9d`.
- Railway bot deployment `458e8e54-804c-46f1-aaf4-0abab4461571` reached **SUCCESS at 6:52:00.711 AM PDT**
  (13:52:00.711 UTC), exact merge confirmed in deployment metadata, region `us-east4-eqdc4a`.
- Normal Polymarket startup at **6:51:55.739 AM PDT**: `polydesk_started ... (LIVE: 10 contract(s) per order)`.
- Before release, **5,673 tests passed / 14 existing skips**, captured exit 0, mypy 128 files and Ruff
  seven changed Python files passed. Full logs, exact bytes, independent source review, rejected
  attempts and resource-test limits remain in the immutable [preparation record](PREPARATION.md).
  These application tests were not repeated for the documentation-only verification entry.

## What actually ran

The original learner startup at **6:53:03.004 AM PDT** reports enabled, `observe_only`, no error,
`live_application=false` and `profitability_proven=false`. Running and retained-history identities match:

- Protocol `kalshi-online-calibration-v1-h300-g5-b10-prior20`.
- Source fingerprint `b6112b7ef8955b20af734157c1e7f5ec533bf98f70e034558f06670578c391f2`.

The first periodic status at **6:58:03.146 AM PDT** reports **0 forecasts, 0 scored, 1 unknown**,
with the unknown explicitly classified `startup_inside`. Baseline and challenger Brier scores are both
null. A restart-partial window was excluded rather than retrospectively forecast. Earlier empty startup
queries and the initial zero counts are retained; neither was presented as an observed training update.

The first possible eligible forecast after this restart is a full future window's actual 300–305 second
slot, potentially **7:05 AM PDT**, subject to admission and fresh-data checks. This is a future opportunity,
not a forecast already observed. A same-terms official finalized result and recorded score-before-train
receipt are still needed to demonstrate an actual update. Known feed gaps may exclude observations.

The learner uses the existing arena child, data and persistence cadence. It cannot change real prices,
orders, cancellations, sizing, stops, limits, resume budgets or ladder decisions. Its optional page-feed
metadata passed contract tests and its producer logs are observed; authenticated HTTP/page rendering
was not checked. Better probability scores would still require separate fee/execution/P&L evidence.

## Fresh account and preserved losses

The first Kalshi row at **6:53:08.794 AM PDT** was authenticated but waiting for stale account data.
It is preserved and excluded as readiness evidence. Later original rows at **6:54:09, 6:55:09 and
6:56:09 AM PDT** have `trading_now=true`, empty waiting reason, authentication, no integrity error and
no cleanup pending. At the last row, account age is 0.044 seconds and cash age 0.590 seconds. The final
reason says **“Window has not started”**; preceding rows say `pair_cap`. These are not fill or profit claims.

Compared the original old **6:47:22.390 AM** publication with the fresh **6:56:09.375 AM** publication:

| Selected measure | Before / after |
| --- | ---: |
| Cash, separate from trading profit | $30.6904 / $30.6904 |
| Cumulative settled trading P&L | −$18.4910 / −$18.4910 |
| Cumulative fees | $3.10792 / $3.10792 |
| Real fills / settlements | 782 / 172, unchanged |
| Filled cost / open risk | $0.56 / $0.56, unchanged |
| Reserved / resting orders / positions | $0 / 0 / 1, unchanged |
| Ordinary window / open / day-stop / total-stop caps | $10 / $20 / $6 / $10, unchanged |
| Clip / ladder rung | 5 / 0, unchanged |
| Day-stop latch / total halt | false / false, unchanged |

The reproducible audit retains **56 selected fields: 55 exactly equal**, one ladder start-P&L display
anchor differing by −1.8e−15, within disclosed absolute tolerance `1e−10`. This ladder anchor is not the
resumed loss-budget anchor. The actual three original startup controls—resume, integrity reset and day
reset—each report **“ignored; this value was already used”**. The raw query has five rows because two
additional status rows embed prior events; they are not five control actions. No budget was reset.

This is selected status/original-log evidence, not a full native ledger, terminal-order, cash-transaction
or stop-anchor export. All existing losses remain. No result here evaluates the earlier PR59 two-window
trial, a completed UTC day, the inverse strategy or the learner's profitability.

At the **6:57:31 AM PDT** health check both bot and recorder are online 1/1, with no reported issues or
recent failures. Recorder deployment `8453f919-b891-4aa7-8478-6fcf6b9c24ee` is unchanged. The old staged,
zero-change Railway patch is retained untouched. The new deployment's bounded `Traceback` query over
**6:51–6:57:09 AM PDT** returned zero rows; it does not certify future runtime health or complete storage.

## Evidence, remaining work and queue

The [release archive](RELEASE.zip) and [external member/hash receipt](RELEASE_ARCHIVE.json) preserve raw
queries, early empty responses, cold/fresh states, source/merge checks, root audit and independent
review. A local audit initially expected `reason` where original control rows use `state`; that failed
attempt is retained, corrected and not represented as a production error or passing application test.

The independent reviewer reparsed the original evidence without rerunning application tests. Its exact
findings and limits are preserved in the archive. The preparation archive remains unchanged.

**Next evidence:** retain prospective frozen forecasts and same-terms official settlement receipts,
reproduce the score-then-update, and report both Brier scores, counts and every exclusion. Do not claim
accuracy improvement from synthetic checks, a single observation or a partial favorable sample. No
automatic live application is enabled.

**EXEC-DELAY-001 remains OPEN**; multisecond main-reader delays and unknown overflow events still need
attribution. The original/inverse comparison is unstarted. The separate frozen ledger diagnostic stays
unreleased; it was not bundled into this task.

The **6:58 AM PDT connected-GitHub queue check** at exact `933a43d` re-read AGENTS, coordination, newest
worklog and pinned PR47/historical-status evidence. Root independently matched all five returned blobs
and full contents to Git. PR47 release/restart is separately verified complete; prior explicit offline
TJR reprioritization persists. Genuine MNQZ2025 development bars and verified costs remain missing:
historical trades **0**, P&L **null**, holdout unopened, paper not started, live disabled. **TJR-MNQ-001
remains blocked and unfinished**, automation unchanged. No duplicate Page/data/test work or new complete
Page-read claim, and no routine unchanged notification. Next TJR input remains the existing verified
development-data/cost bundle; the saved implementation is retained.

This verification publishes documentation/evidence only. It creates no deployment, real order, funding,
Railway-variable change, limit increase or stop/resume reset.

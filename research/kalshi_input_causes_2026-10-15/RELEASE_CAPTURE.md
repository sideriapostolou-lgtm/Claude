# PR62: deployment and fixed-window evidence

Recorded October 15, 2026, 10:50 AM Pacific (17:50 UTC). This closes the bounded diagnostic release/capture, not EXEC-DELAY-001, learned accuracy or strategy profitability.

## Release and capture

PR62 merged during safe minutes at 10:19:44 AM PDT. Exact source `ff05beb654095ce91fefe24adfb2a94eea22be39` on Railway `c64e8199-4ce2-4234-ac53-63905e22231d` reached SUCCESS at 10:22:53.432 AM. Normal Polymarket LIVE startup, fresh authenticated Kalshi readiness, 67 unchanged selected financial/control fields and three ignored already-used controls were verified separately. Full source checks: 5,744 passed / 14 existing skips, mypy 128 source files, changed-file Ruff 5; exact source and independent reviews are in the preparation receipts. The diagnostic changes no trading decisions or money controls.

Root verification completed 10:26:56 AM. The first eligible future full window, **10:30–10:45 AM**, with a **10:47 AM** tail, was declared at 10:26:57 AM with a 184-second margin. Bounds and source never moved. The declaration documentation commit was SKIPPED; final platform reads confirm the same application deployment and both services online, with zero reported warnings/failures. A supplemental exact-bounds Traceback query returned zero. These are bounded checks, not continuous health or storage certification.

## What the learner actually did

The actual ticker is `KXBTC15M-26OCT151345-45`. At **10:35:00.117887 AM PDT**, the learner rejected it as `pregap`. The diagnostic joins exactly one original learner receipt, with matching arena source SHA, learner fingerprint/protocol and observe-only/no-live-application flags.

First/last observed effective causes are **explicit window-gap messages**, at 10:30:00.700413 and 10:34:56.826439 AM. Both the aggregate trade flag and Coinbase flag are true. At rejection, BTC input age is 0.244647 seconds and spot/sigma are valid. V1 retains the earlier gap even after recovery. The two retained frame transit times are 65.916/4.780 ms, with child waits 1.307/0.408 ms. They do not explain or clear delays elsewhere.

The unchanged wire lacks the producer reason/occurrence clock and parent FIFO residence. An explicit slug can result from trade eligibility expiry, book freshness, transport/window-set changes or errors; this evidence cannot uniquely identify which upstream branch occurred. The restart-history marker preserves unavailable older history; these are this child's observed first/last causes, not a reconstructed complete cause tape.

The **10:45:18 AM** original reports **0 forecasts, 0 scored, 16 unknown** (1 startup, 15 pregap), null Brier scores, enabled observe-only and no learner error. There is no actual learning/accuracy improvement to report. V1 history and exclusions were preserved, not relaxed or backfilled.

## Recorded real-money result, separate from learning

| Cohort | Fills | Cost | Fees | Gross payout | Trading P&L |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed 10:30–10:45 AM target | 2 maker fills: Up 1 at $0.43, Down 1 at $0.46 | $0.89 | $0 | $1.00 | **+$0.11** |
| Prior partial window settling at 10:30:04 AM; excluded from target | Not collected in this fixed window | $1.294 | $0.0025 | $1.00 | **−$0.2965** |

The target's two unique recorded fills reconcile to the recorded settlement quantities, cost, fees, gross payout and P&L. Locked P&L is +$0.11000000000000004; directional residual −5.55e−17 is floating-point arithmetic, not a directional gain. Paired credit $1 and final net settlement payment $0 are distinct from the gross payout $1. Both settlement records combined are −$0.1865; this is neither a full-day result nor the fixed target result. The two next-window tail fills remain excluded and retained. No loss is deleted.

The fill query returned 35 matching rows, of which only 4 are anchored original fills; 31 nested status copies were excluded. Two originals belong to the target and two to the next window. All 12 planned finite reads were below 500 and reported no retrieval/parse errors. This does not certify full stream/native venue-ledger coverage. Target fill-rate denominator and order-ack latency were not collected by this frozen plan and remain unknown. Practice P&L was not extracted by this plan; it is never substituted for real P&L.

## Dated post-tail account and remaining work

The last fixed-cohort status at 10:46:05 AM says account data stale; it is retained, not called healthy. A **separate** original at **10:47:13.711 AM**, with payload/account time about **10:47:05 AM**, reports authenticated LIVE/trading_now true, empty waiting and no integrity/cleanup error. At payload time account/cash ages are 0.02721/0.02869 seconds. Cash **$30.7739** differs from cumulative settled trading P&L **−$19.1275** and current UTC-day raw P&L **−$4.6804**. Total fees $3.11042 are retained. These raw scopes are not full-day certified scorecard results.

Reported filled cost $0.84 belongs to the next paired window; risk/reserve/open orders/positions are zero at that snapshot. It is not a new settled profit. Caps stay $10/window, $20 open, $6/day, $10 total, clip 5; ladder rung 0, promotion blocked. No variables, caps, losses, stops/resume budgets, manual orders, live policy or schedules changed during capture.

**Highest-value next evidence step:** implement only a separately reviewed, small producer branch/event identity and occurrence timestamp, correlated through FIFO/frame to the child's actual gap. The initial broad design is retained as a draft; independent review requires a smaller primitive context, per-slug attribution, sustained throughput limits, correct partial-send accounting and measured overhead. It is not implemented or an approved upstream fix. Preserve V1 and live decisions. Consider a separate prospective probability-quality protocol only after its own design/admission/history review; no retrospective manufactured forecasts.

EXEC/learner evidence remains OPEN. TJR remains blocked on authentic development bars and account costs: zero historical trades / P&L null, holdout unopened, paper not started, live disabled; no duplicate research or automation change. The recorder's existing 3:45 PM Pacific feasibility checkpoint and storage review before October 20 remain due. Private handoff text stays outside Git.

Machine-readable originals, request clocks, join flags, financial checks and limitations: `CAPTURE_FINDINGS.json`, `CAPTURE_AUDIT.json`, `CAPTURE_REQUESTS.json`, slot/final native files, post-capture health/source/status receipts and independent reviews. Preparation archive remains immutable; release evidence is archived separately.

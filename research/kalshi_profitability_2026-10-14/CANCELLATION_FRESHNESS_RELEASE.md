# Cancellation-freshness release and bounded restart verification

Recorded October 15, 2026, **5:15 AM Pacific** (12:15 UTC). This is a correctness fix, not a profitable-strategy result.

The owner explicitly approved deploying the tested cancellation correction in the current conversation:
“Always deploy it live … u have my approval.” Existing money limits, stops, consumed controls and Railway
variables remain unchanged. The TJR queue reminder is separate from this active Kalshi instruction.

## Exact release

- [PR #59](https://github.com/sideriapostolou-lgtm/Claude/pull/59), titled **LIVE ON MERGE: touches real money**,
  merged at **5:05:19 AM PDT** (12:05:19 UTC), inside the safe merge interval.
- Exact merge: `1bd8f2217025b098adfd2a0e8a9ca3bbe45c97da`.
- Railway bot deployment: `cdf0d895-6eed-403b-9594-4679692a4499`, **SUCCESS at 5:06:44.265 AM PDT**
  (12:06:44.265 UTC), region `us-east4-eqdc4a`.
- Normal Polymarket startup at **5:06:39.054 AM PDT**: `polydesk_started ... (LIVE: 10 contract(s) per order)`.
- The source diff is six controller insertions plus the 227-line regression file. Source/tests/settings/build
  objects equal fully tested `9d69d95`; independent review also accepted integrated head `54642904`.
  Full checks: **5,582 passed / 14 existing skips**, captured exit 0; mypy 127 / Ruff 2 passed.
  [Exact source, tests, full receipts and fixture limitations](CANCELLATION_FRESHNESS_PREPARATION.md).

The fix refreshes market snapshot/time before checking a remaining intent after a cancellation returns.
It preserves initial priority sorting, lock exceptions, reservations, reconciliation and trading thresholds.
No Polymarket code, financial settings or other candidate was included. No extra generic approval is needed
for finished releases covered by the owner's instruction; the checks and safe timing still apply.

## Startup and retained financial state

The first Kalshi status at **5:07:36.771 AM PDT** was authenticated but correctly waiting for account
freshness. It is preserved, and is **not** the readiness check. At **5:08:37.957 AM PDT**, the later status
reports authenticated/live, `trading_now=true`, empty waiting reason, no integrity error and no cleanup pending.
Its reason field says “Window has not started”; that is retained rather than claiming a fill or profit.

Compared the old **5:03:04.452 AM** status with the new **5:08:37.957 AM** status:

| Selected measure | Before / after |
| --- | ---: |
| Cash, separate from P&L | $31.7933 / $31.7933 |
| Cumulative settled P&L | −$17.7029 / −$17.7029 |
| Cumulative fees | $3.05402 / $3.05402 |
| Real fills / settlements | 761 / 165, unchanged |
| Filled contract cost / open risk | $1.8152 / $0.2452, unchanged |
| Reserved / resting orders | $0.20 / 1 → $0 / 0 |
| Modeled risk including pending orders | $0.3592 → $0.2452 |
| Caps: ordinary window / open / UTC-day stop / total stop | $10 / $20 / $6 / $10, unchanged |
| Clip / ladder rung | 5 / 0, unchanged |
| Day-stop latch / total halt | false / false, unchanged |

Independent reparse agrees on **54 selected fields**: 53 exactly equal; the ladder's displayed start-P&L
anchor changes from `−3.7461000000000055` to `−3.7461000000000073`, a `−1.8e−15` floating representation
difference. Both values are preserved; the audit discloses an absolute `1e−10` numeric tolerance.
This ladder anchor is not the resumed loss-budget anchor.

The bounded original-event queries on both deployments have **zero fill or settlement receipts** between
the snapshots. Fifty unique new resting intents match 50 accepted acknowledgements, explaining the maker-order
counter's increase of 50. The prior $0.20 Up order joins a cancellation receipt; later reconciled status has
zero orders/reservations. There are **52 cancellation receipts: 51 requested and one not-resting 404**.
Requests retain reservations until reconciliation; these are not 52 terminal cancellations.

Startup logs explicitly ignore all three already-used controls: resume, day reset and integrity reset.
No loss or budget was reset by this release. Evidence is selected status/original log data, not a raw
ledger, cash, stop-anchor or complete venue terminal-history export. Both services reported online 1/1
with no recent failures in the post-startup point check. The recorder's existing deployment is unchanged.
The existing staged zero-change Railway patch is untouched.

The exact new-deployment `Traceback` query over **5:06–5:14:27 AM PDT** returned zero rows. This is a
bounded check, not a promise that no error can occur later. An early broad startup query hit its requested
row cap and is preserved as a capped parent; precise original-event queries supply the actual audit.

[Original queries, restart audit, independent review and release receipts](CANCELLATION_FRESHNESS_RELEASE.zip)
are preserved in a 29-member archive, SHA256 `fa1c9b42e71376d72a94591c055aa74ddbf39360412c5f0514d7ccfbb6bd5c34`.
The [external archive receipt](CANCELLATION_FRESHNESS_RELEASE_ARCHIVE.json) records CRC, member hash/length
and byte checks. Audit-script failures from strict float equality and treating removed historical deployments
as still SUCCESS were corrected explicitly; neither was a production failure or a passing application check.

## Fixed post-release evidence in progress

The collector assignment was frozen before outcomes: **5:15–5:30 and 5:30–5:45 AM PDT**, publication tail
through **5:47 AM PDT** (12:15–12:45 / 12:47 UTC), exact new deployment only. Startup partial, next partial
and practice activity are excluded from the two-window real P&L. Collection starts only after the exact
SUCCESS/startup verification; no source release is allowed during this assigned capture.

Preserve all fills, fees, wins, losses, gaps, order denominators, reader identity and latency limitations.
Capped responses must be retained and subdivided; missing outcomes remain unknown when the fixed tail
closes. An order acknowledgement or cancellation count is not profitability evidence. Final two-window
outcomes are still pending at this checkpoint; EXEC remains open and the strategy comparison unstarted.

The earlier 15-of-23-window retrospective result remains partial. An optional eight-point historical
status extraction failed to persist its responses because the worker used unavailable JavaScript `btoa`;
it stopped without retries and supplies no verified observations. It neither closes that eight-slot gap
nor affects the successful release. No new historical coverage, causal avoided dollars or strategy edge
is claimed.

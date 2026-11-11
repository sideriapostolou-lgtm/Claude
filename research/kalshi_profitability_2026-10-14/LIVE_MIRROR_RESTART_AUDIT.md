# PR58 restart continuity audit

The observed restart is **consistent with continuity of the recorded financial state after one late old-process fill**. It is not an “all fields unchanged” comparison. Cash, gross cost, inventory exposure, reservations, orders, fill counters, and session diagnostics changed. The first new status also reports **`trading_now=false`, waiting for fresh account data**; this receipt does not establish trading readiness.

The final old status is `04:47:48.941173167Z` on deployment `86dabbf2-bedb-4686-b6ed-857955e0b521`; the first new status is `04:49:34.104644899Z` on `fc0a73e9-f052-435a-94b2-ce7b1272f36e`. New source is exactly **`1e8d0be07b280292fa873a2f5da9b22dd02f28c3`**.

## Exact comparison

All **53 selected financial, guard, mode, and ladder fields** exist in both statuses: 37 compare exactly equal and 16 differ. Top-level schemas have no old-only or new-only keys. The audit JSON lists every selected comparison and all changed top-level keys; it does not hide changes in nested diagnostic/reporting objects.

| Field | Final old status | First new status |
|---|---:|---:|
| Cash | $33.7994 | $36.9994 |
| Gross unsettled cost | $2.30 | $4.10 |
| Open risk / at-risk exposure | $2.30 | $0 |
| Reserved | $2.25 | $0 |
| Open orders | 1 | 0 |
| Net positions | 1 | 0 |
| Cumulative fills | 631 | 632 |
| Maker orders | 4757 | 4762 |
| Maker fills | 438 | 439 |
| Cumulative fees | $2.70752 | $2.70752 |
| Cumulative realized PnL | −$13.642000000000003 | −$13.642000000000003 |

Cumulative locked $6.198809260739254, directional −$19.840809260739256, historical worst −$2.9791999999999987, windows 131, and settled windows 144 are exactly equal. Maker fill rate and average fill latency change with their underlying counts; these are not restart performance estimates. The five additional maker orders match five durable-intent events after the old snapshot.

Effective caps remain exactly window $10, open $20, day stop $6, clip 5, total stop $10. Total/day latches are false in both; integrity error/reset null; cleanup pending false; authentication and fee precision verified; fee precision $0.0001. Ladder enabled/rung 0, pending/change/recheck fields and effective limits match. Both status labels are `REAL MONEY (Kalshi)` with configured/live mode, but **trading-now changes true→false**, waiting changes empty→`Kalshi account data stale`, and reason changes `balancing_only`→`Kalshi account data stale`. A live-mode label does not override the account-freshness gate.

Session telemetry changes as expected: reconciliation counts start again at one cycle rather than the old 1437. Loop, phase, request, markout, checkpoint, and reconciliation observations are separate sessions and are not subtracted as if they were persistent financial counters.

## Late fill explains the apparent balance discrepancy

Existing up inventory came from the immutable preceding capture: `KXBTC15M-26OCT150100-00`, up 5 at $0.46, fee $0, fill `0725ca65-fda9-a3bc-1166-2ed955301768`, logged `04:45:34.350322388Z`.

The old process subsequently records down 5 at $0.36, fee $0, fill **`0725ca73-b079-8f13-3a0a-cbc76e96a7b0`**, venue fill time `04:48:39.226696Z`, logged `04:48:41.155502492Z`. It joins to durable client `nc-speed-1858019bba6943b0aa1d03dabcdc746b`, accepted order `01a13de3-f118-7e31-8f4a-3a5d9f343088`, matching ticker, side, size and price. Original intent and accepted-order events are retained in the JSON.

The same order's reprice and shutdown cancellation responses say **404, reservation retained until reconciled**. These are not proof of cancellation before the fill, nor of premature reservation release. A subsequent observed fill and the new zero active orders/reserves are consistent with reconciliation of the filled order.

Decimal arithmetic:

- Additional cost: 5 × $0.36 = **$1.80**.
- Combined gross cost: $2.30 + $1.80 = **$4.10**, matching the new status.
- Five opposite pairs are consistent with **$5 netting credit**; $5 − $1.80 = **+$3.20**, exactly matching $36.9994 − $33.7994.
- Pair floor less total gross cost is **$0.90**. This is paired-inventory arithmetic, not a newly reported realized settlement: cumulative settled PnL remains unchanged in these receipts.

Source `speeddesk_live_model.py:332–345` defines open cost as gross cost of unsettled windows and open loss as cost minus the weaker side's $1-per-pair payout, floored at zero. Source `speeddesk_live.py:2595–2601` separately reports that risk and the count of nonzero reconciled net positions. Thus $4.10 gross cost with zero open risk and zero net positions is internally coherent; it does not mean the gross inventory history disappeared.

The $5 cash-credit explanation is **consistent with application logs and source semantics**, not an independently observed raw venue cash transaction. No raw venue cash export was supplied or queried.

## Restore and one-time-control evidence

At `04:49:27.855194329Z`, integrity reset is logged `ignored; this value was already used`; day reset has the same state at `04:49:27.855201499Z`; resume has the same state at `04:49:27.855243749Z`. Ladder startup reports `restored`. None of these records reports a newly applied reset/resume, new budget, or promotion. Raw token values and consumed stop anchors are not exported by this audit, and absolute historical PnL is not substituted for anchored stop-budget consumption.

Pinned source supports the observed ordering:

- `speeddesk_live.py:475–520` verifies the ledger chain, loads saved ledger KV and journal, validates liability/intention agreement, and reconstructs the financial book. A display mirror is not used as restore authority; a mirror without its ledger is rejected.
- `speeddesk_live.py:555–584` handles the already-used resume/integrity/day states. The controls are not reapplied merely because the process restarted.
- `speeddesk_live.py:966–989` commits receipts and state in the ledger transaction before emitting pending financial log records. The observed old fill log is therefore evidence of passing that application commit path, not merely an unpersisted in-memory fill callback.
- `speeddesk_live.py:2529–2569` drains writes, attempts cancellation, reconciles, and requests a durable shutdown checkpoint, retaining uncertainty where needed.
- `speeddesk_live.py:1000–1004` contains PR58's single-encoding display-mirror write after the ledger path. The old/new diff in this file changes only `json.dump(...)` to `stream.write(json.dumps(...))` plus its comment; restore, checkpoint transaction, replacement, shutdown, financial guards, and cadence are unchanged.

These code paths plus the new status support bounded restart continuity. They do **not** independently verify the disk's bytes/hash chain, prove every old-process receipt persisted under every crash, or distinguish ledger restoration from any supplemental startup venue reconciliation for every individual field. No ledger database was read during this audit. Matching scalar totals alone would not prove all historical state identical.

## Evidence receipts and limits

| Original saved input | Bytes | SHA256 |
|---|---:|---|
| live-mirror-release-query-1.json | 285405 | `07ef94cd78b07c1b4837ba8cc88b164ab20c94b6d5f005bd6afccdb4a3cb64e9` |
| live-mirror-old-status-before-build.json | 580817 | `95a25c335d65da5746f52befb330564a1e3ff6e9dc3e5ad28685a96305f2becb` |
| live-mirror-startup-speeddesk.json | 408571 | `caa743ed8f7a207db76b7ad16005372578d794d4247efdecd33ad18ac7bf09d8` |

Query populations are 22, 50, and 97 rows, below each 500-row limit, with no API errors. Seven duplicate overlapping structured event rows were removed; the overlapping old status agrees exactly. The prior up-fill input is the closed capture hash `fd12946730ac7847d4436caa99d6de94f3e86d370e226d03c97ecde43fb915ba`. These filtered bounded responses are not a complete venue transaction export.

Pinned source hashes: live controller `5e69c33b05afc9531b42670389e94a5a0d0e0fadda0c9f0858aeec94b3337835`; live risk model `689207e3a681b591f64a43f03a359d2dc0dbe424cbc2f74809669866ffab36de`; WS reader `d76e9dfa6a026f796f11503642a373a5a0f2799da8dabadf078c565591f82112`.

Machine-readable output: `/workspace/shared/live-mirror-restart-audit.json`; reproducible parser: `/workspace/shared/live-mirror-restart-audit.py`. No production query, source edit, financial setting/order action, or release action was performed. This audit establishes neither post-change freshness improvement nor completion of EXEC-DELAY-001; those require the separate predetermined post-change capture.

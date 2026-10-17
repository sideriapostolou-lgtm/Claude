# Independent PR72 retention and first-status review

**Selected evidence passes.** Offline comparison found retained reported P&L, activity history, caps, stop flags and ladder state. The first post-release status remains configured/effective PAPER, unauthenticated, with aggregate and shard cash unknown. No account cash availability or successful real-order behavior is established.

This review read only `BEFORE.json`, `PRE_MERGE.json`, `AFTER.json`, `SOURCE_READBACK.json`, `RETENTION_CHECKS.json` and local Git/file identities. It performed no production/API/account call, financial action, source edit or research TEST access. This document is the reviewer's sole new file.

## Identity and observation boundaries

- Reviewed source/test patch: SHA-256 `c8c2289cee038a32613ede4b9f28c30e38a2a5199ab277ed62078cdcc6579be2`.
- Candidate: `d0d3ea4f752e1363b74dc6c840d6e73ab6a24b58`.
- Merge: `c9301a1f5d102cc7ed1403c89bc19a6118942d95`.
- Candidate and merge local Git trees independently resolve to `a8ee2f2039057a6cfc97d484dd8fe392ab193991`.
- All 24 file identities in `SOURCE_READBACK.json` independently match the working-file Git blob hash, candidate blob and merge blob. This verifies the selected source/evidence identities, not a deployed filesystem or complete ledger.
- BEFORE: three selected native log rows, `2026-10-16T13:56:15.976811222Z` through `13:58:16.272988420Z`, scoped to deployment `07e8627b-7700-4dff-8e84-fd2d90ac669e`.
- PRE_MERGE: three rows, `2026-10-16T14:14:27.824801026Z` through `14:16:19.008932204Z`, same prior deployment. The final producer `as_of` is `1792160178.706947` (`14:16:18.706947 UTC`).
- AFTER: exactly one selected native row, `2026-10-16T14:22:50.451602357Z`, scoped to deployment `3a1b0098-8b07-4bc7-b586-38a24fcc625a`. Producer `as_of` is `1792160569.9807625` (approximately `14:22:49.980762 UTC`). Log arrival is about 0.471 seconds later.

The integration owner separately reports Railway SUCCESS at **14:21:47.747 UTC**, normal Polymarket LIVE startup at **14:21:38.735 UTC**, full tests **6,225 passed / 14 skipped in 293.51s**, mypy **133 files**, and Ruff **13 files**. Those platform/startup/test records are not among these five selected input files, so this offline retention review does not independently re-certify them. AFTER's query identifies the new deployment but does not itself contain a platform SUCCESS or commit-binding record.

Both pre-release queries requested limit 2 and returned 3 rows; the artifacts retain that discrepancy. These are bounded selections, not a continuous log stream or a census of account operations. The first PRE_MERGE row's log arrival follows its producer timestamp by about 9.242 seconds; producer and log times are kept separate.

## Retained selected state

Every row across BEFORE, PRE_MERGE and the one AFTER row agrees on these reported values:

| Field | Retained value |
|---|---:|
| Configured / effective mode | paper / paper |
| Reason | Practice only; live mode is off |
| Authenticated | false |
| Aggregate cash / cash timestamp | null / null |
| Window / open / daily / total caps | $10 / $20 / $6 / $10 |
| Clip | 5 contracts |
| Total halted / daily latch | false / false |
| Integrity error | null |
| Reported open risk, open cost, reserve, at-risk amount | all $0 |
| Reported open orders / positions | 0 / 0 |
| UTC-day P&L | −$5.1277 |
| Lifetime settled P&L | −$24.6195 |
| UTC-day fills / traded windows / settled windows | 86 / 23 / 25 |
| Lifetime fills / traded windows / settled windows | 912 / 203 / 220 |
| UTC-day / lifetime fees | $0.2797 / $3.39642 |
| Ladder rung / pending change / promotion ready | 0 / false / false |

Comparison used the exact parsed numeric values, including stored floating-point representations; displayed dollar figures above are rounded for readability. For both `today` and `total`, the audit also compares locked/directional components, worst-window result, take attempts/fills, maker orders/fills, and lock orders/fills. The entire ladder object matches, including rung start, loss/giveback history, pending limits and promotion blockers. Reported fills remain 912; that supports no increase in the selected bot fill counter, not a complete venue-wide no-trade certificate.

The daily latch was already false before this release. Its retained false value is not evidence that this release reset the daily allowance. Raw budget anchors, used-reset tokens and all financial-control state are not included, so their exact retention is outside this selected-field check.

## New status and interpretation

AFTER reports:

```json
{
  "cash_total_usd": null,
  "shard_funding": {
    "source": "GET /portfolio/subaccounts/balances",
    "subaccount_number": 0,
    "at": null,
    "error": "shard_cash_unknown",
    "balances": [],
    "external_resting_orders": 0,
    "external_resting_unknown": false,
    "refusal": null
  },
  "create_funding_cooldown": {
    "until": 0,
    "remaining_s": 0,
    "refusals": 0
  }
}
```

This is the expected initialized state for flat PAPER operation: the source string names the configured read endpoint; it is **not a receipt showing that endpoint was called**. Empty balances and null `at` mean unknown funding, not a zero-dollar venue balance. Zero external-resting count and false unknown flag are initial observer state, not verified absence of owner orders. Zero cooldown/count mean no recorded funding refusal under the new counter; the selected runtime evidence has not exercised a funding rejection, cooldown persistence or accepted create. Prior pre-release rejects are not retrospectively counted by this new counter.

`authenticated: false` and null cash timestamps support “no successful authenticated snapshot is reported.” They do not alone prove that no attempted HTTP request occurred. Code/offline tests establish the flat-paper no-client path; these selected logs are consistent with it.

## Checks and limitations

Independent local assertions passed for 112 selected top-level field comparisons, 210 financial/history comparisons, seven full ladder comparisons, three exact new-status blocks, three row counts, two candidate/merge tree identities, 72 file/blob comparisons, agreement with the 28 recorded retention booleans, one before/after timestamp binding, and five stable input-byte checks. All seven producer timestamps were separately verified to precede their corresponding log timestamps. These repeated comparisons are validation checks, not 450 independent market observations.

`RETENTION_CHECKS.json` reports `passed: true`, and its before/after timestamps match the selected endpoints. Its `no_authenticated_account_read` label is interpreted narrowly as the selected unauthenticated/null-cash state, not an independently proven absence of network calls.

The status scorecard still labels the day **partial**, with **58 eligible / 19 complete / 39 gap windows** in AFTER, `day_complete: false`, no automatic promotion, and incomplete discovery/history reasons retained. The narrower scorecard P&L must not replace the full-day −$5.1277. Nothing here certifies raw volume, full capture coverage, production latency, account balances, portfolio/owner exposure, a profitable edge, successful shard funding, live activation or actual rejection cooldown behavior. Later statuses, startup-control records and scoped traceback checks belong to the integration owner's continuing evidence collection and are not anticipated in this report.

## Frozen input hashes

| File | SHA-256 |
|---|---|
| BEFORE.json | `6371b7b221b2ac2f825d718e27178b90dc0f7e919d10e1d2e3f49972955ab362` |
| PRE_MERGE.json | `7b5b153e83ea899140fc6797b20920cf84e09d02ebd2e5efa49ec4f285e90de8` |
| AFTER.json | `d596176ed8ee49c876f14a77560072b56ded5bc926376734b4b66f88862e5f23` |
| SOURCE_READBACK.json | `cda5010d9a6da89563dbbec0ac6f6944824087cd178dde9fe091baee363e0c72` |
| RETENTION_CHECKS.json | `3276df8a770d70a875ce8761f6947c74a19524391363277de0ffed1285b35369` |

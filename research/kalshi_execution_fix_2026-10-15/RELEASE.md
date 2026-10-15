# PR #63: lock order freshness fix deployed

Evidence verified October 15, 2026, **11:25 AM Pacific (18:25 UTC)**. The reproduced order-submission defect is fixed and deployed. Execution-delay attribution, usable learning samples and strategy profitability remain open.

## What changed

A balancing lock order could wait in the worker or transport and still send with stale account or cash data while its order books stayed fresh. Six added lines in `_lock_guard` now recheck authentication, existing account readiness and the window's cash-freshness limit before transmission. They preserve the order's own reservation and valid balancing locks through financial stops. No model, trading threshold, cap, stop, budget, variable, fee, journal, durability or Polymarket rule changed.

Full pytest: **5,772 passed, 14 existing skips**, captured exit zero, 316.58 seconds. Mypy passed all 128 source files; Ruff passed both changed Python files. Independent exact review accepted 31 focused tests and ten transport scenarios. The original guard fails both new delayed stale-send regressions. Source, test and patch hashes match the reviewed bytes; initial fixture failures remain recorded. The immutable preparation archive has 37 members and its independently verified SHA-256 starts `5e3b7611`.

[PR #63](https://github.com/sideriapostolou-lgtm/Claude/pull/63) merged at **11:17:03 AM PDT**, during safe minutes. Railway deployment `c1fda55b-72fd-47b3-9801-dffec83b9e8b` built exact commit `59ba6a8e33c4e7368e74ca1e71645cc4f288d699`, reaching SUCCESS at **11:19:53.430 AM**. Merged app, test and build objects match the tested candidate. Connected GitHub confirms source blob `23fce969`. The normal Polymarket LIVE startup is recorded at 11:19:48.972 AM.

At 11:25 AM, bot and unchanged recorder were online, one instance each, without reported warnings or failures. The saved, bounded Traceback query returned zero. Neither check establishes uninterrupted health, disk capacity or raw-data completeness. [Independent restart review](RESTART_INDEPENDENT_REVIEW.json) accepts the bounded verification with those limits.

## Restart and financial reconciliation

Original Kalshi heartbeats at **11:21:02 and 11:22:04 AM** reported stale account data. Both remain recorded and excluded as readiness evidence. The **11:23:04 AM** heartbeat reports authenticated LIVE, trading enabled, an empty waiting reason and no integrity or cleanup error. The old resume, day-reset and integrity-reset values were explicitly ignored as already used; no new budget was created.

Of 67 selected financial and control fields, **54 match exactly; 13 changes reconcile** to the recorded activity:

| Actual fill | Running build | Contracts | Price | Recorded fee |
| --- | --- | ---: | ---: | ---: |
| Down, 11:18:57 AM | Previous | 1 | $0.41 | $0 |
| Up, 11:21:28 AM | Corrected | 1 | $0.39 | $0 |

Both fills join their original durable intent and accepted order. Cash arithmetic is **$30.7739 − $0.41 − $0.39 + $1 paired credit = $30.9739**. The pair costs $0.80, with zero reported directional risk, reservations or open orders at the captured status. It was **unsettled at capture**; this report books no 20-cent profit.

Cumulative settled trading P&L remains **−$18.9675**; incomplete UTC-day P&L remains **−$4.5204**, and cumulative recorded fees remain **$3.11042**. Cash is not profit. Ordinary limits remain **$10/window, $20 open, $6 day stop, $10 total stop, clip five**, rung zero. The existing balancing-lock exception is unchanged.

Forty-nine durable intents explain the maker-order count increase; 48 accepted receipts are available. One old acknowledgement is missing from the queried originals and remains unknown. A zero-share, zero-P&L settlement explains the settlement counter increase. The ladder start-P&L changes by only 1.776e−15, consistent with floating representation. This selected audit is not a full native cash-history or control-state export.

The new maker fills do not exercise the corrected lock branch. No live freshness-specific refusal, saved dollar amount or improved profitability is established. The existing generic refusal text cannot identify which guard condition failed. A freshness refusal may defer a hedge; tests cover durable definite-unsent release and a new order ID after reconciliation. The earlier **−$0.2965** loss used the intended late hedge, with only 9.86 ms observed before transmission; it is not evidence that this stale-wait defect caused that loss.

## Timestamp interpretation correction

Earlier derived reports, including PR #62's supplement and the initial PR #63 startup audit, incorrectly called `payload.at − as_of` account-data age. That claim is withdrawn. `as_of` is the panel clock; the difference measures panel-to-record elapsed. **The last account-read timestamp is not published, so its exact age is unknown.** Readiness passed at panel evaluation; its exact age and continuous freshness are not certified.

`cash_at` remains a local balance-observation timestamp: the 11:23:04 AM payload has local cash age 0.53019 seconds. It is not an exchange timestamp. Original responses, superseded derivatives, immutable archives and every loss remain preserved. See the [independent correction](ACCOUNT_AGE_EVIDENCE_CORRECTION.json) and [superseded-field list](TIMESTAMP_INTERPRETATION_CORRECTION.json).

## Remaining work

The learner startup original is observe-only, with the expected source/protocol identity: **zero forecasts, zero scored, 19 unknown** (two startup and 17 pre-forecast gap exclusions), null Brier scores and no reported error. These counts do not prove learning or prediction quality; numerical continuity is not independently established by this bounded review. Practice is never substituted for real P&L.

The next evidence step is the already documented upstream gap/admission mismatch: establish a small causal producer context or a separately versioned prospective probability-quality design, preserving V1 history and live rules. Deferred metadata and cancellation optimizations remain separate.

[Fresh queue review](QUEUE_GATE.json) confirms PR #47's exact deployment and follow-up are separately complete, while broader Kalshi execution/learning evidence remains open. TJR remains unfinished and blocked on authentic contract bars and verified costs; historical P&L is null, paper has not started, live remains disabled. No duplicate research or automation change was made. The recorder's existing **3:45 PM Pacific** checkpoint and storage review before October 20 remain due. No schedules, financial settings or manual orders changed.

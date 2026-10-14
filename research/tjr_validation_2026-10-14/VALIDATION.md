# TJR validation: runner ready, historical result still blocked

October 14, 2026. This follows the owner's explicit instruction to backtest the saved TJR experiment alongside the Kalshi investigation. Live execution is disabled. There is no feed, broker adapter, account funding, paper process or production deployment in this folder.

**Recommendation now: do not put money into this strategy on the present evidence.** The saved implementation is worth a bounded historical test, but we have not established that it is profitable or unprofitable. A paper-trial recommendation remains conditional on completing the actual-contract test and securing an authorized current-contract feed. The original December 2025 contract is expired.

## What is complete

- Current Pages match the preserved source; see `CURRENT_SOURCE_CHECK.json`. The original code and tests remain unchanged in `../tjr_mnq_2026-10-14/`.
- Original prototype **65/65** and independent feature harness **26/26** reproduced in Node.js. `REPRODUCTION_RESULTS.json` includes every case and source hashes. These are invented-price tests, not historical returns.
- Version `TJR_BC23_MNQZ25_SWEEP_BOS_v0.1.1_calendar` changes only the version label and the confirmed calendar bug: unknown current/prior calendar status is now `BLOCKED/CALENDAR_UNVERIFIED`, never a planned exclusion. All 65 original prototype checks still pass. `sources.mjs` checks archived hashes and creates that exact narrow derivative; `SOURCE_DERIVATION.json` records the identity.
- The development runner has **58/58** additional/combined regression checks. They include exact source reproduction, missing calendar dates, immediate-prior-session linkage, wrong contracts, duplicate/missing bars, holdout rejection, hash mismatches and losses on incomplete sessions. An independent reviewer reran all 58 and found no remaining blocking code issue.
- The independently sourced cash-session calendar has **43 civil dates, 31 regular sessions including September 19 warmup, and 30 development sessions**. The official cash calendar is not proof that CME bars exist or that a feed is complete. See `VERIFIED_DEVELOPMENT_CALENDAR.json` and `DATA_ACCESS.md`.
- `run.mjs` was actually invoked without a data bundle and returned **BLOCKED**, exit status 2, zero historical trades tested, and null historical P&L. See `HISTORICAL_STATUS.json`. It did not turn missing data into zero profit.

## What remains unavailable

The authentic, licensed, unadjusted **MNQ December 2025** minute bars for September 19–October 31, 2025 and a verified provider mapping have not been obtained. The public samples inspected are the wrong contract/date or lack the required prior session. An unauthenticated Databento metadata request returned HTTP 401. No paid access or credentials were used. Exact access receipts and alternatives are in `DATA_ACCESS.md`/`.json`.

Actual account fees, observed spread/friction, and fixed platform/data costs also remain unverified. The nine predeclared combinations are sensitivity assumptions, not quotes or nine independent samples. They cannot establish actual business profitability. The November 3–December 12 holdout has not been evaluated, and the supplied historical runner deliberately cannot run that partition.

## Run it

From the repository root, with Node 24 or another modern Node supporting `Intl` New York time:

```bash
node research/tjr_validation_2026-10-14/test.mjs
node research/tjr_validation_2026-10-14/run.mjs
```

The second command intentionally exits 2 while the data bundle is missing. It reports null P&L and no historical test. A completed local bundle can be run as:

```bash
node research/tjr_validation_2026-10-14/run.mjs \
  --bundle /path/to/development/manifest.json \
  --output /path/to/development/results-unique-name.json
```

The output must not already exist. This prevents overwriting a prior receipt. Run once for the entire nine-point frozen sensitivity grid; do not select only its best result. No network call or broker order occurs. Keep the output and raw source hashes with the research record.

Copy `MANIFEST_TEMPLATE.json`, the verified calendar and `MAPPING_TEMPLATE.json` into a local authorized dataset folder. Null fields intentionally block execution. Fill evidence fields only after inspecting actual provider documentation/instrument definitions and licensing, not to make the program pass. A hash proves bytes stayed the same; it cannot establish vendor authenticity or permission by itself. The reviewer flags likewise record assertions requiring independent evidence review.

Paths in the manifest are relative to the manifest's directory. Every source, canonical-bar file, mapping and calendar has a SHA-256. Raw source date bounds must stay within September 19–October 31. Obtain development-only files; keep the holdout in a separate location and do not pass it to this runner. Each file is bounded to 64 MiB; a larger raw export needs a reviewed streaming adapter, not truncation or omitted rows.

Canonical `bars.jsonl` has one JSON object per actual trade-minute, chronological, with these fields:

```json
{"t":1758547800000,"contract":"MNQZ2025","o":100000,"h":100004,"l":99996,"c":100001,"v":10}
```

**That line is a schema example with invented prices, not market data.** `t` is UTC epoch milliseconds at interval start; OHLC are exact integer 0.25-point ticks; volume is optional and nonnegative. Convert using the provider's documented interval alignment and verified actual-contract identity. Retain untouched raw files and normalization provenance. Do not round off-tick prices, forward-fill missing minutes, deduplicate without an audit, substitute a continuous series, or label NQ/CFD bars as MNQ.

The runner accepts only the cash interval 09:30–16:00 New York and the frozen development plus warmup dates. An adapter may select those intervals from a retained raw export; it must preserve omissions and record every exclusion. No provider adapter is supplied because no verified dataset schema was available. A future adapter must be reviewed against the real export rather than guessed now.

## Reporting behavior

Each of the 30 scheduled development sessions remains in every scenario, including no-trade, blocked, incomplete and planned shortened-session exclusions. The immediate prior cash session is mandatory; an incomplete prior session cannot be replaced with an older complete day.

The original `summary.netUSD/grossUSD` are retained for compatibility but count **complete sessions only**. Explicit aliases `completeSessionNetUSD/GrossUSD/FeesUSD` make that scope clear. Known closed trades on unresolved days retain their individual records and separately labeled gross, fees and net totals. `knownAllClosedTradesNetUSD` combines known closed trades; it is **not** total campaign P&L. `wholeCampaignNetUSD` stays null when any session is unresolved. Missing open-trade outcomes are never invented.

The report includes all fees/friction scenarios, daily trades and rejected candidates, uncertainty in intrabar exits, worst complete session, loss streak, session-end drawdown and concentration of positive session P&L. `performanceClaimAllowed` always stays false. OHLC targets are hypothetical trade-through fills; queue position and real spreads remain unmeasured. The model uses assumed bar-close availability and one-minute entry latency; it does not claim observed live timing.

A rejected supplied input has `holdoutOpened:null` and `holdoutExposureStatus:UNVERIFIED_INPUT_REJECTED`, because content may already have been parsed before rejection. `holdoutReplayed:false` is the supported claim. The no-input receipt explicitly says no data were accessed. Do not describe an inspected held-out dataset as untouched merely because the runner rejected it.

## Concrete next step

Provide an existing authorized MNQZ5 actual-contract export or data-provider access for the 31 required regular sessions, including its mapping/license and timestamp convention. Build and verify that provider's lossless normalization adapter, hash and freeze the bundle, then run the development grid. Review losses, missing days and concentration before opening any holdout. A holdout driver must bind the frozen code/parameters and record a single first evaluation; this runner intentionally leaves that step locked.

After a useful historical result, define a separate current-contract prospective study, freeze its dates and measured-cost protocol, and verify the persistent paper observation start. No paper start or live activation is implied by passing software tests. TJR-MNQ-001 remains active and blocked on data, not done.

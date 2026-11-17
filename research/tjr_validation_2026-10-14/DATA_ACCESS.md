# TJR historical-data access check

Checked October 14, 2026, 11:50–11:52 AM PDT. Exact request receipts and sample hashes are in
`DATA_ACCESS.json`. **No authentic MNQ December 2025 development bars were obtained, and no historical
strategy returns were computed.** This is a specific data-access blocker, not a negative or positive backtest.

## What is now verified

The frozen campaign needs the actual, unadjusted December 2025 MNQ contract: September 19 warmup and
September 22–October 31 development. There are 30 scheduled development cash sessions and one warmup
session, requiring 12,090 minute bars if every scheduled minute has a trade. Missing minutes must remain
missing; the runner must not invent candles or silently exclude losing/incomplete days.

`VERIFIED_DEVELOPMENT_CALENDAR.json` supplies all 43 calendar dates, with 31 regular cash sessions,
12 closed weekend dates and no scheduled early close. Nasdaq's official 2025 calendar was visually
inspected, including its color legend; the ICE/NYSE notice corroborates the dates. All regular openings
in this development period are 6:30 AM Pacific / 13:30 UTC. This verifies the planned **cash-session**
calendar used by the strategy, not actual CME feed completeness or the absence of unscheduled halts.

- [Nasdaq 2025 calendar](https://www.nasdaq.net/PublicPages/assets/MyMID/Trade_Calendar_2025.pdf): downloaded
  successfully; SHA-256 recorded. The [Nasdaq Trader page](https://www.nasdaqtrader.com/Trader.aspx?id=Calendar)
  independently links the same calendar under its own host.
- [ICE/NYSE holiday notice](https://ir.theice.com/press/news-details/2024/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/default.aspx):
  read successfully through connected web; a separate local HTTP retrieval returned 403, so no local-body hash is claimed.
- [Nasdaq standard hours](https://www.nasdaqtrader.com/content/TechnicalSupport/nasdaq_sys_hours.pdf):
  9:30 AM–4:00 PM Eastern. This current 2026 document corroborates the frozen normal-hours convention;
  the dated 2025 calendar provides holiday classification.

## Data checks and concrete failures

| Source | Actual result | Why it cannot supply this backtest now |
| --- | --- | --- |
| [Databento](https://databento.com/docs/quickstart/set-up) | Unauthenticated `GET https://hist.databento.com/v0/metadata.list_datasets` returned HTTP 401, `auth_authentication_failed`. No credential was supplied or read. | Historical requests require an API key and entitlement. No configured data credential was reported by the root agent's environment check. Signup credit is not an existing authorized account. |
| [FirstRate MNQ](https://firstratedata.com/i/futures/MNQ) | Public ZIP now downloads: 16,235 minute rows, September 28–October 13, 2026, Eastern time. | Wrong dates; sample root symbol has no contract column or proven December 2025 identity. Its readme's individual-contract end marker is also stale (`MNQZ24`), so the sample cannot establish the needed contract coverage. |
| [Portara MNQ](https://portaracqg.com/futures/int/mnq/) | Public sample now downloads: declared `MNQ2026M`, 896 rows on June 15, 2026, 08:04–23:59 Chicago time. | Wrong contract/date. It also lacks the preceding cash session, so it is insufficient even for a separate, newly frozen pilot using the same prior-session levels. |
| [CME DataMine](https://www.cmegroup.com/datamine/datamine-api.html) | Read official API documentation. | Requires entitled API ID and purchased historical files. No access, purchase or authenticated call was invented. |

Sample checks inspected headers, timestamp bounds, counts, vendor metadata and documentation only.
No sample OHLC prices were printed, no strategy was run on them, and raw sample data was not saved or
committed. The [Portara license](https://portaracqg.com/license/) allows research for purchased data within
the licensed organization but restricts raw redistribution; a public sample does not create a full-history
entitlement. No anonymous rehost was substituted for verified actual-contract data.

The November 3–December 12, 2025 holdout price data remains unopened. Calendar metadata is not trading
outcomes. No continuous NQ/MNQ series or CFD has been relabeled as this instrument.

## Costs remain assumptions

The owner has no verified futures broker/fee statement in the provided account records. A public
NinjaTrader commission-PDF request returned 404; a search snippet is not a usable account quote.
Actual per-side fees, spread, slippage, platform and data costs remain unresolved. Keep all nine frozen
scenarios ($0.50/$1.00/$1.50 per side crossed with 1/2/4 friction ticks) labeled assumptions.

The [CME MNQ contract page](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html)
confirms $2 per index point and a 0.25-point tick. That establishes tick value, not account fees, margin
approval, execution availability or safe position sizing.

## Exact next input

Obtain an existing authorized export of **MNQ December 2025**, minute trade OHLCV, for September 19
through October 31, 2025 only. Supply vendor name, permitted research use, immutable raw file, exact
contract definition/provider symbol, timestamp timezone and bar-start/end convention, plus the actual
fee schedule for the intended account. Preserve a separate unopened holdout export.

For an entitled Databento export, the candidate is `GLBX.MDP3`, `ohlcv-1m`, `stype_in=raw_symbol`,
candidate `MNQZ5`; the raw symbol is **not verified yet**. Resolve it against instrument definitions
before accepting the data. Its [symbol documentation](https://databento.com/docs/standards-and-conventions/symbology)
distinguishes raw contracts from continuous mappings; its [OHLCV documentation](https://databento.com/docs/schemas-and-data-formats/ohlcv)
states bar timestamps label interval starts and absent trades can leave gaps. Do not forward-fill them.

No new account, paid purchase, secret inspection, order, financial setting or production deployment was
performed. Live execution remains disabled. The evidence supports finishing validation when data arrives;
it does **not** support recommending live TJR trading or claiming this strategy makes money.

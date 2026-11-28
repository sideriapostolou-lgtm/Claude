# Kalshi daily status — October 17, 2026

Read-only inspection began **8:16:02 AM PDT**. Reporting day: **October 16 UTC**, or
**October 15, 5 PM through October 16, 5 PM PDT**. All amounts below are USD.

## Current operating failure

Railway reports the bot and standalone recorder online, each with one running
replica. The bot still runs source **f370c3c252927f659472ee160eb92fac2458ee51**,
deployment **43f14443-2d07-4985-b879-3a2515fb8d2c**, successful since October 16,
4:50:35.236 PM PDT. Branch head **c8fbc6e59e7a1555489116dce35f7657cd5fe208** adds
only documentation/evidence and was SKIPPED. No new deployment was performed.

**The container is online, but the trading components have failed.** Actual logs:

- **October 17, 1:58:56.596 AM PDT:** Kalshi companion halted, `OSError`.
- **1:58:57.085 AM:** Kalshi cleanup unconfirmed, `OSError`; skipwatch also halted.
- **1:59:00.714 AM:** Polymarket thread traceback reports
  `OSError: [Errno 28] No space left on device` while writing its state. Its error
  handler attempts another save and also fails.
- **1:59:02.783–1:59:03.896 AM:** Bitcoin practice desk halted; state unavailable;
  Kalshi practice arena stopped. These are distinct from other app threads that
  continue logging.

The Kalshi log records only the exception class, so the exact failing Kalshi write
or stack is not established. The simultaneous Polymarket traceback directly proves
a disk-full write failure. Do not describe all components as healthy or infer a
fresh account state from the Railway badge. The reviewed controller closes its
send gate during shutdown, but **successful cleanup and current venue exposure
remain unverified**.

A bounded **2 AM–8:18 AM PDT** exact-deployment status query returned zero Kalshi
native rows. No new Kalshi order/cancel/fill/settlement rows were returned from
October 16, 5:01:25 PM through October 17, 8:18 AM. These are provider-log results,
not a direct venue certificate. `/healthz` returned HTTP200 at **8:18:13.513 AM**;
the protected `/api/page` returned **HTTP401 at 8:18:13.702 AM** without credentials.
The health endpoint therefore does not establish trading-loop health.

## Last account evidence, explicitly stale

Last full native snapshot: **October 17, 1:58:44.461 AM PDT**, before the failure.

| Item | Last reported value, not a current account read |
| --- | --- |
| Kalshi configuration / policy | REAL MONEY authenticated; reduction-only; new starters disabled; no automatic resume |
| Trading then | `trading_now=false`; waiting for reduction-only policy, not a daily-loss latch |
| Cash | **$47.0925** |
| Cumulative trading P&L | **−$27.6489**; locked +$8.63493234, directional −$36.28383234 |
| Open risk / reservations / gross open cost / orders | **$0 / $0 / $0 / 0** before failure; unverified now |
| Limits | **$20/window, $40 open exposure, $12 daily loss, $10 total-loss allowance, 5-contract clip** |
| Day / total latch | Both false in that snapshot; neither was reset here |
| Ladder | Rung0, effective ceiling $20, no promotion pending; 26/96 qualifying-count target, rung gain −$5.5908; blocked by ceiling/windows/gain/stops |
| October17 UTC to that snapshot | Zero new fills; inherited prior-policy pair settled +$0.0127; not containment profit |

Cash includes funding and is not trading profit. The cumulative figures are a
native summary, not a fresh reconstruction of the lifetime venue ledger.

## Prior completed UTC day: real and practice separated

Real figures reconcile actual logged fills and settlements to the native daily
report. Practice figures reconcile simulated receipts; they never represent cash.
The day includes multiple source versions, interruptions and financial settings.

| October16 UTC metric | Real Kalshi | Kalshi practice twin |
| --- | ---: | ---: |
| Windows receiving fills during the day | 56 | 18 |
| Fill receipts | 149 | 20 simulated |
| Settlements with inventory | 55 | 17 |
| Additional empty settlement records | 5 | 79 |
| Fees on fills occurring during the day | $0.4993 | $0.0508 simulated |
| Fees attached to that day's settled positions | $0.4820 | $0.0508 simulated |
| Locked P&L after allocated fees | +$4.94228322 | +$0.5100 |
| Directional P&L after allocated fees | −$13.11208322 | +$1.4992 |
| **Net settled P&L** | **−$8.1698** | **+$2.0092 simulated** |
| Worst settled window | −$2.8509 | −$2.0400 |
| Maker orders filled / placed | 120 / 2,952 (**4.065%**) | 17 / 2,837 (**0.599%**) |
| Ordinary taker orders filled / placed | 5 / 5 | 3 / 4 |
| Protective lock intents filled / placed | 18 / 20 | Not the same live-lock policy |
| Average decision-to-fill latency | 4.245 seconds | 16.220 simulated seconds |

The real worst window is `KXBTC15M-26OCT152315-15`, closing **October15, 8:15 PM
PDT**. Its loss was a costly completed pair, not remaining directional exposure.
The aggregate directional loss is larger, but not every loss was directional.

Real ordinary taker and protective-lock counts are separate. Fill rates count
orders receiving any fill, not filled contract fractions. Decision-to-fill means
durable decision to venue fill timestamp and includes maker resting time; it is
not reaction time or acknowledgement latency.

Real decision-to-acknowledgement median/p95: **88.815 / 337.269 ms**, based on
2,297 acknowledged samples from2,957 ordinary intents, with **660 errors** retained.
Accepted Coinbase exchange-timestamp age at decision median/p95:
**196.182 / 944.968 ms**; callback-receipt age **152.488 / 849.070 ms**. Neither
proves a causal price-trigger reaction. Practice has no venue acknowledgements.

The day's final real pair had $0.0173 fees but settled after midnight UTC. Its
**+$0.0127** belongs to October17's settlement-day result; it is excluded from
October16 settled P&L. The practice twin also carried one unpaired simulated share
into the next day. No missing exit or hypothetical profit is substituted.

Coverage remains incomplete: the separate window-quality scorecard has **26 of96
windows complete and70 with gaps**, including only17 traded complete windows.
Its filtered real P&L of−$0.6044 must not replace the full observed settlement loss
of−$8.1698. The native `reporting_complete` practice flag does not override these
market-data gaps. Practice simulation and the real execution policy differ;
practice's positive result is not proof that the real strategy would profit.

## Recorder and storage

The separate read-only recorder remains on **a0782b743a31369fe25ddf6d2eea96df8511cd8d**,
deployment **8453f919-b891-4aa7-8478-6fcf6b9c24ee**. Its latest saved receipt at
**October17, 8:00:05.545 AM PDT** covers7–8AM:60 sampled/fresh-BTC/trade-tape minutes,
two spot reconnection gaps and no open-ended gap records. Book RTT p50/p95/p99:
66.811/118.083/165.247ms; trade-receive lag3.835/8.940/16.983s. These are one-hour
metadata statistics, not execution latency or uninterrupted recording proof.

For October16UTC,24 hourly manifests report1,440 sampled/fresh-BTC/trade-tape
minutes and19 spot reconnection gaps. One known trades429 occurred October15,
7–8PM PDT. Other429/error nulls are unknown, not zero. Counts cannot be converted
into gap-excluded duration without actual interval records.

- Recorder-owned saved bytes: **1,129,844,282 / 4,831,838,208 (23.38%)**;
  level0, no deleted segments. Growth **316,218,232 bytes during October16UTC**,
  and292,979,608bytes over the most recent comparable24hours.
- Separate one-hour Railway metric snapshots: bot disk **5.011144704 GB**,
  memory4.552237056/8GB; recorder disk1.323114496GB,
  memory **0.999727104 / 0.99999744 GB (~99.97%)**. The tool provides61 samples
  per metric but no individual sample timestamps. Platform disk and recorder-owned
  bytes have different scope; these are not fresh `df`/inode measurements.
- Recorder `coverage_certified`, `segment_hashes_reverified` and
  `per_venue_spot_ticks_verified` remain false. Raw hashes, exact capture duration,
  quote survival, depth/fill feasibility, backups, retained-test fit and measured
  hosting cost remain unverified. Healthy logs alone do not close those gaps.
- `docs/KALSHI_RECORDER.md` returned404 on the requested branch/current head;
  it was read successfully at the exact recorder source. No future TEST/outcome
  rows were opened, and Family A's frozen protocol was not changed.

## Highest-value next evidence step

Obtain a **read-only bot-volume capacity/inode/file-size inventory plus a fresh
venue balance, open-order and position reconciliation**, while preserving ledgers,
receipts and loss history. Then establish a backed-up, verifiable storage recovery
plan. The current connector exposes logs/metrics but no service-shell or raw-volume
export; protected page access returned401. No successful disk inventory, backup or
fresh post-failure account check is claimed.

Production remained read-only: no variable, limit, resume budget, trading rule,
order, funding, deployment, resize, deletion or restart action. This report records
an unresolved operating incident, not a completed repair or a profitable strategy.

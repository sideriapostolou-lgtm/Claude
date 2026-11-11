# Daily Kalshi status — October 15, 2026

Read-only inspection for the scheduled 8:20 AM Pacific task. Actual account log: **8:22:37 AM PDT**
(15:22:37 UTC); account/cash observation times are separately retained in the raw JSON. Recorder's latest
saved full hour: **7:00–8:00 AM PDT**, published8:00:01 AM. These are evidence times, not a promise of continuous monitoring.

## Running source, account and limits

- Bot exact `933a43d2d7cb6d6dd27b4728d50c78ce0f488ed5` on Railway `458e8e54`, SUCCESS. Subsequent
  `8bf1acb` and `91250c6` docs commits were SKIPPED. Bot and recorder online 1/1 with no reported issues/recent failures.
- Kalshi **paper / stopped**: “Total loss stop; no new bets until a new resume token.” Configured mode
  remains live; the loss latch overrides it. Total halted true, day-stop latch false, authenticated/fresh,
  no integrity error. **No new resume or control change.**
- **Cash $30.6904**; recorded cumulative settled trading P&L **−$19.0510**, including recorded cumulative
  fees **$3.10792**. Locked **+$3.210749**, directional **−$22.261749**. These are different from cash.
  782fill receipts /173settlement counter; no positions, orders, reserved cash or open risk.
- Ordinary caps unchanged: **$10/window, $20 open, $6 UTC-day stop, $10 total stop, clip 5 contracts**. Ladder rung 0,
  99/96 minimum windows but gain **−$15.3049** since rung start; gain / house-money / stops block promotion.
  Code ceiling remains$20/window, distinct from the larger configured ceiling. No rung/limit increase.

## Prior completed UTC day: October 14

Pacific interval: **October 13 5:00 PM–October 14 5:00 PM PDT**. Stored ledger/simulator summaries follow;
they are **not a certified complete-day or matched live/practice comparison**.

| Recorded measure | Real Kalshi | Practice twin |
| --- | ---: | ---: |
| Window counter / settlement counter | 41 /51 | 67 /67 |
| Fill receipts | 222 | 199 |
| Fees | $0.7011 | Not separately reported |
| Locked allocation | −$0.564641 | +$33.648223 simulated |
| Directional allocation | −$3.940359 | −$21.418223 simulated |
| Net recorded P&L | **−$4.5050** | **+$12.2300 simulated** |
| Worst recorded window | −$2.15 | −$3.10 simulated |
| Maker filled orders /orders; rate | 159/1,872;8.49% | 193/4,746;4.07% |
| IOC attempts /fills; rate | 0/0;not applicable | 0/0;not applicable |
| Mean decision-to-fill | 3.178s, includes resting | 6.537s simulated, includes resting |

The real41/51 window/settlement counters have not been reconciled into distinct complete windows in this
inspection. Do not equate either counter with all 96 opportunities or with the simulator's population.
Practice fee absence is **unknown**, not zero. No fee is subtracted again from the reported net figure.

| Latency from retained counters | Real median /p95 | Practice median /p95 |
| --- | ---: | ---: |
| Accepted Bitcoin exchange timestamp →decision | 213.83 /916.72ms | 203.49 /895.62ms |
| Bitcoin callback receipt →decision | 154.01 /725.24ms | 143.99 /724.79ms |
| Decision →validated order acknowledgement | 94.47 /740.10ms | Not applicable |

Real input-age samples1,872; acknowledgements1,854/1,872 with18reported errors,0timeouts/0missing.
Practice input-age samples1,513. These are order-intent cohorts, not guaranteed bot reaction times.
Exchange/local clock uncertainty remains; receipt-to-decision includes input age; acknowledgements include
journal/queue/HTTP time. Resting time makes decision-to-fill different from acknowledgement speed.

**Coverage limitation:** both real and twin scorecards flag **all 96 windows with gaps and 0 complete windows**.
Full-day discovery/recording is not certified. Therefore complete-cohort fills/P&L/worst / fee metrics are null,
not zero, even though stored raw daily counters exist and the twin says `reporting_complete=true` for its
bookkeeping. The simulated+$12.23 is not an executable profit finding or a reason to resume/raise caps.

## Recorder and evidence gaps

Recorder exact `a0782b743a31369fe25ddf6d2eea96df8511cd8d`, Railway `8453f919`, SUCCESS; separate service/volume.
Latest saved metadata reports **505,511,164/4,831,838,208bytes (10.46%)**, storage level0,0deleted segments.
The preceding saved hour used491,138,150bytes: **14,373,014bytes/hour observed growth**, not a multiday forecast.
The bounded 7:00 AM-to-query warning/error filter returned 0 matching deploy-log rows. The health point
reported no platform issues. No storage action was performed.

For7:00–8:00 AM the metadata reports60/60BTC fresh minutes and trade-tape minutes,0reported gap records.
Trade-receive lag p50 **3.656s**, p95 **6.384s**, p99 **7.429s**. Candidate book fresh share1.0 is a coarse
metadata counter, not proof of obtainable fills. `coverage_certified=false`, `segment_hashes_reverified=false`,
`per_venue_spot_ticks_verified=false`; raw files were not accessible through these log reads. REST `429` and
error fields are null in this receipt; absence is unknown rather than0. Quote survival/depth/actual operating
cost and full historical coverage remain missing. No sealed outcome/TEST records were read.

## Progress and next evidence

The observe-only learner remains unproven. At **8:31:06 AM PDT**, it reports **0 forecasts /0 scored /
7 unknown** (startup1 +pregap6), both Brier scores null, no error and no live application. The previous
31original logs and11new original rows are retained; the sixth full exclusion occurred8:20 AM. Offline
actual-child/pipeline fakes reproduce pre-start warning contamination,
delayed untimestamped gap delivery and quiet-maker eligibility exclusions. They do **not** attribute every
production exclusion. Two healthy producer snapshots around7:05 AM cannot rule out intervening gaps.

Prepare and review the narrow child chronology correction locally, preserving actual active-window gaps,
all historical unknowns, practice results, fingerprints and real controls. A separate prospective protocol is
needed before decoupling maker eligibility from prediction-input quality. Current instruction forbids production
deployment; no source was released. EXEC stays open and the inverse comparison unstarted.

The [daily evidence archive](DAILY_STATUS_2026-10-15.zip) and [member/hash receipt](DAILY_STATUS_2026-10-15.json)
retain original bounded responses, scope/parse checks, local reproductions and review corrections. Initial
literal review mistakenly overlooked the JSON embedded in status log messages; its preserved amendment
reproduces the actual prior-day numbers. Neither that review error nor a pending local receipt filename is
a production/data-access failure. All production reads used for this status succeeded.

The [Codex takeover checklist](../../docs/CODEX_TAKEOVER.md) records verified connected access, original evidence,
three existing enabled schedules and remaining account/data/session limitations. TJR still lacks authentic
development data/costs; paper/live remain off. No duplicate research or routine unchanged queue notification.

Next highest-value evidence: join actual timed gap reasons to a future eligible prediction, then retain the
pre-outcome forecast, official same-terms settlement and exactly-once score/update. Do not relax gaps, resume
real trading, reset budgets or claim profitability to make the page look active.

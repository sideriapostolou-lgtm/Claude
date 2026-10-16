# EXEC-DELAY-001 — offline checkpoint baseline

Completed bounded baseline profiling only. No application/test source, trading setting, history, financial control or production state was changed. No candidate was run. Actual production source remains root-owned; this synthetic experiment does not establish production delay causality, realized speed improvement or profitability.

Pinned application checkout: `/workspace/nightcrawler-practice-checkpoint`, HEAD `f77e1ad460c74a2eb5167ff1e243cca9cf94b329`, tree `c11957009aa127a18edd2b301cfff67db30058de`. Frozen measured harness SHA256 `8e24b69dcf884bd8b63d2f0983fc84566e909384c5e236d06f29aea601404bd8`. Exact per-child argv, source/helper hashes, exits, stdout/stderr hashes and sampled limits are in `matrix_manifest.json`. Raw timings and counts are in the twenty named child stdout JSON files; `SUMMARY.json` aggregates them.

## Measurements

Three isolated timing processes per fixture, five samples per operation/process (15 pooled samples). p95 is descriptive nearest-rank; with n=15 it equals the observed maximum. Allocation and counting each have a separate process. Timing includes the same small FakeClock.now call-counter overhead in every run. First FULL-synchronous initialization/report creation is separate from steady checkpoints.

| Synthetic fixture | Windows / settlements | Steady checkpoint wall median / p95 ms | Thread CPU median / p95 ms | daily_reports wall median ms | First FULL checkpoint median ms |
|---|---:|---:|---:|---:|---:|
| 1 completed day | 50 / 46 | 5.22 / 8.55 | 5.22 / 8.55 | 1.00 | 17.04 |
| 7 completed days | 338 / 322 | 48.10 / 50.72 | 48.10 / 50.33 | 29.76 | 101.63 |
| 31 completed days | 1,490 / 1,426 | 617.89 / 643.11 | 617.83 / 643.07 | 542.14 | 856.02 |
| 35 days, sparse older-history case | 562 / 490 | 259.50 / 281.52 | 259.47 / 281.49 | 220.48 | 380.53 |

The 1/7/31-day fixtures use 24 sparse 15-minute windows per completed day per venue, plus two crossing-midnight carry windows. The 35-day fixture uses eight per day per venue. These are not a complete 96-window daily universe. No full-day qualification or production-size equivalence is claimed. Actual retained practice-history counts are unverified. The separately reported 195 settlements belong to the real companion, so no inference or interpolation from that count to practice checkpoint cost is valid.

| Fixture | Report Settlement conversions/checkpoint | Report Window conversions/checkpoint | Counted Settlement conversion wall / CPU ms | Counted Window conversion wall / CPU ms |
|---|---:|---:|---:|---:|
| 1 day | 184 | 100 | 0.648 / 0.675 | 0.523 / 0.537 |
| 7 days | 5,152 | 2,704 | 18.343 / 19.009 | 9.959 / 10.302 |
| 31 days | 91,264 | 47,680 | 322.422 / 334.016 | 171.385 / 177.137 |
| 35 days | 35,280 | 20,232 | 126.485 / 130.650 | 72.978 / 75.319 |

Report settlement counts exactly match `(completed_days + 1) * 2 venues * retained_settlements`. Model serialization independently converts each retained Settlement once more per checkpoint. Both module/type counters are retained separately. Current-day combined summary alone converts every retained Settlement twice. Coverage, complete-day, scorecard, panel, summary and SQL counts are retained, with independent clock-call counts.

Counting instrumentation increases checkpoint median wall time by 7.3%, 35.8%, 39.1% and 36.6%, respectively; tracemalloc increases it by 5.81x, 5.78x, 4.59x and 4.63x. Consequently conversion times are instrumented observations, not projected savings. Counter/time wrappers add overhead, and inclusive nested function times must not be summed. CPU conversion timing includes a small end-clock skew relative to wall measurement. Settlement conversion alone accounts for about 28% of the *counted* seven-day checkpoint wall time and 38% of the *counted* 31-day checkpoint wall time; comparing directly against the clean timing total would overstate the attribution.

## Output, history and resources

Mirror and stored KV JSON byte lengths match (cross-store byte content was not asserted by the baseline harness): 68,590; 404,638; 1,758,496; and 1,096,342 bytes. Receipt counts are 116; 782; 3,446; and 1,370. Every receipt hash chain verifies. Output mirror SHA is identical across all five processes for each fixture, and repeated steady checkpoints leave bytes and receipts identical. State retains all synthetic windows, settlements, fees, losses, coverage and reports. Each correction phase adds exactly one audited daily correction after both venues' valid next-day partial first fills. Carry executions occur 600 seconds after midnight and 299 seconds before window expiry. Unresolved window counts are 4, 16, 64 and 72; all remain unresolved.

The older-history case advances normal evidence retention after publishing reports and proves that four older days retain the published latency/scorecard values. Allocation peaks for one warmed checkpoint are 348,266; 2,063,752; 8,436,884; and 3,734,894 traced bytes. Largest observed RSS is 78,164 KiB (76.3 MiB), separately measured from the conservative 256 MiB address-space limit. Longest child run is 10.674 seconds. Peak sampled scratch disk is 10,105,960 bytes; conservative retained-artifacts-plus-peak-scratch bound at finalization is 10,310,831 bytes, well below 100 MiB. The supervisor samples RSS/scratch every 20ms and kills on a bound breach; each child also enforces 60s alarm, CPU/address-space/file-size limits and post-operation RSS/disk checks. No cap abort occurred.

Explicit defaults construct paper-only Settings with empty Secret fields; no from_env, credential read or application run occurs. Reused `LocalFeeds`, FakeClock and snapshot-cache Companion receive the runner factory boundaries; the companion panel is explicitly inert paper. Real HttpClient, KalshiClient, KalshiLiveDesk and MarketFeeds construction is denied during the fixture. Socket creation/connection/DNS audit guards remain active throughout. Each process blocks one import-time urllib3 IPv6 capability socket probe before construction, retaining its exact stack. Runtime forbidden-attempt counters are dynamically recorded and asserted zero in all 20 successful children. The structural zero client-construction field follows from these guard assertions; it is not an observed successful-construction counter. No successful socket/client construction or remote connection occurred.

## Preserved failures and limitations

- The original pilot used an after-expiry carry execution. It is superseded and retained; no pilot numbers support this result.
- The first matrix correctly failed its zero-attempt assertion because it included the blocked import capability probe. `profile_baseline.failed-v1.py`, failed-v1 child outputs, the failed manifest and diagnostic outputs remain available. The corrected matrix distinguishes import phase and runtime attempts and retains both.
- All 20 corrected measurement children exited zero. The supervisor exited one at its final broad hash assertion because root concurrently edited only `docs/COORDINATION.md` (`ccc60ba6...` to `cc29685e...`). Application, helpers and frozen harness hashes remained identical. `matrix_manifest.before-docs-finalization.json` and supervisor stderr preserve that failure; the final manifest explicitly qualifies post-run verification rather than calling the supervisor successful. No measured cohort required rerunning for that docs-only change.
- Timing assumes an inert companion panel. Actual real-companion display cost, concurrent threads, production disk/WAL/storage contention, public-feed timings, clock-boundary races, crash/failure equivalence and future source-epoch release behavior are not validated by this baseline.

## Smallest evidence-backed next candidate

The repeated frozen flat Settlement conversion is material in the bounded seven-day cohort and grows strongly at 31 days. The smallest candidate for root to consider is lazy checkpoint-local reuse of *only* converted Settlement rows, shared by existing report summaries, with lifecycle cleanup on every exit and no persisted/cache-across-checkpoint state. This is a design recommendation, not implemented or measured. Expected count gate: report settlement preparation visits C retained rows once per checkpoint instead of `(D+1)*2*C`; separate model serialization remains unchanged.

Window is mutable, so no Window identity cache/prefilter/frozen cutoff is recommended. Every current clock call, venue/window filter and cutoff evaluation must retain its existing position and behavior. The candidate must preserve late correction receipts, report/container independence, complete history/output bytes, all save/transaction/FULL/atomic mirror boundaries and real journal behavior. No source-fingerprint alias, reset or history relabeling is permitted: a later speeddesk.py change requires a distinct existing-versioned probability epoch and preserved prior dictionaries. Root owns any source authorization, independent review, full checks and release/runtime verification. EXEC and profitability remain open.

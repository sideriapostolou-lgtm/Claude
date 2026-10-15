# Closed post-PR58 windows: loss retained, freshness unresolved

The predetermined October 14, 2026 **10:00–10:30 PM Pacific** observation is complete. Its real-money result is **−$1.329 after fees**. No losing window was replaced. The collector stopped at **10:32:19 PM PDT** after the fixed 10:32 PM query tail; no collector jobs remain. This completes the capture, not EXEC-DELAY-001 or a profitability test.

App source was `1e8d0be07b280292fa873a2f5da9b22dd02f28c3`, Railway deployment `fc0a73e9-f052-435a-94b2-ce7b1272f36e`. The earlier [release/restart receipt](LIVE_MIRROR_RELEASE.md) remains separate. No reviewer/operator-initiated production change or manual order action occurred in this bounded follow-up. The already-running desk continued its existing automated trading. Workers made no source release, service deployment, variable, limit, stop or resume change.

## Retained real-money outcomes

| Pacific window, October 14 | Actual fills | Accepted orders filled | Cost | Fees | Settled result | Locked allocation | Directional allocation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10:00–10:15 PM | 5 | 5/40, 12.5% | $9.590 | $0 | −$1.590 | +$0.679231 | −$2.269231 |
| 10:15–10:30 PM | 7 | 7/40, 17.5% | $10.730 | $0.009 | +$0.261 | +$0.261 | $0 within rounding |
| Both | 12 | 12/80, 15% | $20.320 | $0.009 | **−$1.329** | **+$0.940231** | **−$2.269231** |

The worst fixed window lost $1.590. Every distinct logged fill joins its durable intent and accepted order; independently summed quantities/costs/fees match both settlements. Root also recomputed costs, fees, payouts and P&L directly from original anchored logs. Locked and directional figures use the existing fee-inclusive average-cost allocation; they are not two separately tested strategies.

There were 81 durable intents and 80 accepted orders. The extra intent was explicitly logged **not sent because prices moved**, not treated as a missing successful order. The second window's cost above the ordinary $10 budget uses the pre-existing risk-reducing completion-lock exception; no cap was increased. Full orders, fills, cancellations, exact joins and limitations remain in the audit archive.

The prior restart-spanning window's +$1.11 and the next window's unsettled $2.95 exposure are excluded. Practice events remain in original responses but were not evaluated as a practice trial here. No practice P&L, win rate or missing-activity zero is inferred.

## What is still too slow

The four identified main-reader protocol-acceptance-to-receive delays were **2,895.428, 2,890.691, 2,695.675 and 2,625.561 ms**. Another **43 rejected-message receipts overflowed** and remain unknown. The 47 source-age warnings and 47 timing gap diagnostics are separately defined populations, not interchangeable counters. All fixed-window producers have explicit main-reader identity; older untagged records remain unclassified.

Observed synchronous work overlaps the known delays. Examples include practice panel CPU around 302 ms and practice ledger wall time around 276 ms with only 40 ms thread CPU. These are positive overlaps, not complete causal explanations; nested wall/CPU spans cannot be added. A reviewed [ledger-stage measurement candidate](LEDGER_STAGE_TIMING_PREPARATION.md) is preserved locally and in its preparation archive, not deployed. It separates conversion/encoding/lock/SQL/commit elapsed time without changing durability or trading.

Selected account-read resumption max was 546.519 ms across 13 selected cycles/66 reads; covering main-loop lag max was 1,479.7 ms across 31 distinct intervals. Required endpoints/publication cohorts reconcile without observed read/bin retention loss. These coarse responsiveness checks do **not** pass source freshness or provide complete read-by-read coverage of quiet cycles. The [independent audit](LIVE_MIRROR_TWO_WINDOW_AUDIT.md) preserves every population, interval, omitted detail and typed timestamp.

Original decision-to-ack medians were 84.252 ms (40 samples) and 85.856 ms (36 samples). Second-window regular-intent latency coverage excludes four lock orders; their latency is unknown. No pooled median or p95 is fabricated, and provider-clock uncertainty/callback-versus-network receipt remain explicit.

## Dated account and service observations

The last retained real status, **10:31:51.579 PM PDT**, reported **$32.9304 cash**, **$2.95 open risk/cost**, **$1.60 reserved**, one order and one position. Cumulative settled trading P&L was **−$13.861**, fees **$2.71652**, 651 fills. Cash is not P&L; none of these values is claimed current after that timestamp. The configured mode was live, but `trading_now=false` and account data was flagged stale at that snapshot. This is not readiness evidence.

Periodic snapshots retained ordinary window/open/day-stop/total-stop amounts of $10/$20/$6/$10, clip 5, ladder rung 0, unlatched day/total stops and no integrity error. Historical cumulative loss is not the current stop-budget baseline; raw stop anchors were not exported. No budget reset, increase or policy change was made.

Root's **10:13:53 PM PDT** point check found both services online 1/1 and the exact PR58 deployment active. It is not continuous health evidence. The recorder's **10:00:07 PM PDT** manifest reported 392,744,973/4,831,838,208 configured archive bytes, no deletions/storage warning and 60/60 reported fresh minutes for the prior hour. Coverage/raw hashes remain uncertified; this is neither disk-free verification nor proof that every venue has complete raw data. The 48-hour recorder feasibility/capacity obligations remain open.

## Reproducible evidence and next step

[Closed evidence archive](mirror-postrelease-closed-evidence.zip): **8,797,425 bytes**, SHA256 `be187899557374ce75b599ccbb4e5d6bc09045a096eb3980a1053024aab2340f`. Its [manifest](mirror-postrelease-closed-evidence.manifest.json) records 42 exact members. CRC, names, all original bytes and hashes were checked. It contains all 15 contiguous uncapped original responses, fixed assignment and stopped-collector flags, collector derivation/parser, immutable first and final audit inputs/parsers/results/reports, dated health/resource/recorder references and root verification. Original full capture SHA256 is `800d9bc39e3d4247312c75c2f64c41b046294f4db98b5a899b29b7eb659a9401`.

Filtered query coverage is not complete venue tape or independent raw ledger/account coverage. The independent parser retains 1,058 original rows, including 45 status/twin rows intentionally excluded from the collector's 1,013-event derived set. No source population or loss is erased. Earlier first-window artifacts are unchanged. Absolute source paths inside preserved receipts map to same-named archive members.

Highest-value next evidence step: continue attributing the known main-reader backlog, separating practice panel/state CPU from ledger elapsed stages before choosing another focused correction. Any later code release belongs to that existing task and requires its own exact deployment/restart verification and prospective evidence scope. EXEC-DELAY-001 remains **open**; the original/inverse/no-trade comparison is **unstarted**. TJR remains blocked on authentic MNQ data/costs, with historical P&L unknown, paper not started and live disabled. This capture does not establish a profitable strategy or a causal before/after effect of PR58.

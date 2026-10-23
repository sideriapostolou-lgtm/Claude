# Arena feed repair, 2026-10-14

This repairs the practice evidence feed. It does not establish a profitable strategy, change real-money orders,
alter budgets or thresholds, clear old void windows, or promote an arena resident.

## Observed problem

The production counters supplied by the session's Railway log check rose from 375,246 received / 1,111,037 dropped
at 14:20 UTC to 455,477 received / 1,451,104 dropped at 14:23 UTC. The combined increase was 420,298 events in
180 seconds, approximately **2,335 events/s**. At the latter observation the arena had **zero complete windows**,
60 void windows, 54 voided for feed trouble, and 74,612 late events. Those are missing evidence, not losing or
winning strategy observations.

## Narrow change

- Retain whole and partially written frames on socket backpressure. Retain subsequent events in a bounded FIFO,
  rather than dropping one batch on each blocked write. The buffer holds at most 16,384 events; overflow remains
  counted and invalidates practice results. No producer book replacement or print coalescing is used.
- Encode in small chunks within a 400 microsecond budget, at most 1,024 events per flush. Marshal, socket send and
  changed market metadata add work after that encoding budget. This is a bounded amount of work, not a hard
  wall-clock deadline; process scheduling and garbage collection can still delay the caller.
- Preserve intermediate books for every window with a pending simulated order, including resting bids. The
  child may coalesce books only where no resident has an order. Queue-ahead consumption and the requirement for
  a price to survive the simulated delay stay in the practice model.
- Hold settlement outcomes until the last queued slice so they cannot overtake final prints.
- A reported drop/sequence gap invalidates started, unsettled windows even if they have just closed or are first
  named in that same frame. Readings more than 3 seconds late still void a window. Buffering never rewrites a
  book or trade timestamp.

The unmerged `claude/kalshi-arena-feed` draft was read for context; it was not merged. Its producer book replacement
and relaxed lateness treatment were not adopted.

## Fake transport comparison

Local baseline: deployed-source ancestor `decf002f68aa706ad09caabb1299e5c69bef59d1`, prior to this repair.
Same interpreter and process, no network, account, keys, orders or real money. Each synthetic changed book had
40 levels with shared immutable levels, 90% book events / 10% prints. Socket sends retained bytes for later
decoding. Timing is the calling thread's CPU time for a complete flush, including serialization and fake send.
The steady case feeds 150 events at each of 400 nominal 50 ms steps: **3,000 events/s**, above observed production.
The backpressure case refuses 10 consecutive sends; the burst case queues all 6,000 events before draining.

Final bounded comparison, after the source was frozen:

| Case | Version | Input | Delivered | Dropped | Flushes | Median CPU/flush | p99 CPU/flush |
|---|---|---:|---:|---:|---:|---:|---:|
| Steady 3,000/s | Before | 60,000 | 60,000 | 0 | 400 | 405.3 us | 660.3 us |
| Steady 3,000/s | After | 60,000 | 60,000 | 0 | 400 | 430.3 us | 550.3 us |
| 10 blocked writes | Before | 60,000 | 58,500 | 1,500 | 400 | 399.6 us | 711.4 us |
| 10 blocked writes | After | 60,000 | 60,000 | 0 | 400 | 425.0 us | 534.2 us |
| 6,000-event burst | Before | 6,000 | 1,024 | 4,976 | 4 | 667.7 us | 711.9 us |
| 6,000-event burst | After | 6,000 | 6,000 | 0 | 34 | 490.8 us | 538.6 us |

The steady median added about **25 microseconds** for retention and budget checks. A preliminary run measured
418 us median / 466 us p99 after versus 394 us / 448 us before; timing varies on this shared machine. The final
table is not a sub-0.5 ms guarantee. A 150 us budget was also measured and rejected: it delivered only 42,432 of
60,000 events in the sustained case and dropped 17,568. The larger buffer alone does not solve insufficient drain
throughput. A trial binary-search tuple-diff optimization was slower than the existing ladder diff and was rejected.

The final 6,000-event burst needed 34 flushes, roughly 1.7 seconds at a real 50 ms cadence, **before any existing
delay**. A long live-loop stall, stalled child or sustained overload can still cross the 3 second freshness limit
and must still void the window. The local benchmark proves transport retention and bounded processing work;
only subsequent production counters can establish adequate coverage on Railway.

## Checks at source freeze

- 117 arena tests passed; one existing optional wall-clock performance test skipped and two CPU-spinning stress
  cases deselected for this focused run. Root runs the complete repository checks separately before shipment.
- The unchanged real-child busy-market test passed its existing 0.5 ms p99 CPU limit at 21 events per step.
- All 14 new backlog/adversarial cases passed: sustained 60,000 book events, exact FIFO books/prints, partial and
  zero-byte writes, bounded dequeue work, retained ask disappearance, full queue-ahead consumption, overflow
  voiding, unchanged late-event age, same-frame/new-window gap handling, post-close gap handling and delayed
  settlement facts. Changed Python files pass Ruff.
- A first busy-market run measured 0.536 ms p99 and failed its 0.5 ms bound; the standalone repeat and subsequent
  complete focused arena run passed. The test threshold was not changed.

Deployment and production complete-window counts are intentionally left to the parent session's receipt. No
positive coverage, trading edge or profitability is claimed here.

## Post-deploy failure and correction, 14:50–15:00 UTC

The first feed repair deployed in PR #45, commit `18e180f`, Railway deployment `11b6b12e`, at 14:50:52 UTC.
**It did not repair production coverage.** The shallow-book, nominal-cadence benchmark above was insufficient.
Do not use that benchmark as evidence that the deployed arena had usable windows.

Runtime evidence from this exact deployment:

| Time UTC | Received | Dropped | Late | Lag | Complete windows |
|---|---:|---:|---:|---:|---:|
| 14:51:44 | 15,334 | 69,940 | 13,280 | 49.66 s | 0 |
| 14:52:46 | 24,278 | 170,289 | 22,224 | 94.54 s | 0 |

At 14:55:45, the producer reported 75,572 accepted events, 490,490 dropped events, 1,029 frames, a full
16,384-event queue, 1,011 budget-limited flushes, and **zero blocked socket writes**. Over roughly 301 seconds
since its start, that is only **3.4 flushes/s**, not the nominal 20, and approximately 58 events per frame.
The child consumed only about 0.3% of a CPU and its pass p99 was approximately 0.6 ms. The bottleneck was before
the child, not socket backpressure. Book/print rates and the budget-limited producer overwhelmed the queue.

A read-only public book request found **111 YES levels and 168 NO levels** in the current KXBTC15M window.
The prior local fixture used 40 levels per ladder. The wire diff scans the unchanged prefix and suffix of a
changed ladder; deeper ladders reduce events encoded in the same budget. Production also reports 399 historical
practice window reasons and the main producer runs much less frequently than its nominal sleep interval. Other
session work investigates callback/checkpoint scheduling. Account calls are in a separate asynchronous task;
an awaited account read by itself does not prove it blocks the producer.

The local reproduction with 168 changed-ladder levels and 60,000 events at the nominal 3,000/s schedule showed:
the pre-PR45 fixed-size sender delivered all 60,000 in 400 flushes; PR45's 400 us time budget delivered 49,312,
dropped 10,688 and needed 599 flushes. Thus the encoding budget introduced a demonstrated capacity regression at
realistic depth, despite improving bounded-work behavior and blocked-write retention. At the observed slower
cadence, insufficient capacity was still worse. A wall-clock budget also charges time when another thread holds
the GIL or the process is descheduled, which can prematurely stop encoding after one 16-event chunk.

The follow-up changes only the encoding budget: **4 ms of the calling thread's own CPU**, with the existing hard
**1,024-event cap**. `perf_counter_ns` continues to report actual wall time separately; `thread_time_ns` measures
the encode budget. A backlogged call may now cost several milliseconds plus serialization/send work. It is
explicitly **not** a sub-0.5 ms claim. FIFO order, retained partial writes, original timestamps, queue bounds,
strict 3 second lateness, gap voiding and delayed settlement facts are unchanged.

Independent reviewer measurements with deep books, 150 calls:

| Events/call | Equivalent rate at 3.4 calls/s | Result with 4 ms CPU budget |
|---:|---:|---|
| 300 | 1,020/s | All 45,000 delivered; median 1.761 ms/call |
| 700 | 2,380/s | No drops; 12 events waiting at the last scheduled call; median 4.359 ms, p99 5.495 ms |
| 882 | About 3,000/s | 11,132 dropped out of 132,300, with 15,696 still waiting; **insufficient capacity** |

This supports the observed approximately 2,300/s workload at the observed slow cadence in that local test, with
little margin. It does not support an unconditional 3,000/s production claim. Improving producer cadence and
verifying actual depth and live counters remain necessary; a faster machine or a nominal 50 ms sleep is not
evidence of the real callback schedule.

Additional regression checks at follow-up source freeze:

- Production-style paired books with 111/168 levels, changing one bid and its opposite ask, pass at 150 events
  per 50 ms nominal step and 700 per 300 ms delayed step. Each run has 100 steps, no overflow and fewer than
  1,500 events queued before the final drain.
- An injected one-second wall-clock pause does not consume an unchanged CPU budget, while the full one-second
  wall latency is still reported. A constant fake CPU clock cannot encode beyond the 1,024-event cap.
- The 14 existing new backlog/adversarial cases and two separate-clock/cap tests pass; the four targeted
  production-depth and clock/cap cases pass. Changed Python Ruff and whitespace checks pass. Root performs
  complete checks, safe deployment and fresh runtime verification separately.

No source, settings, cap, order or deployment was changed during the initial read-only investigation. The
follow-up code was then explicitly assigned by the parent session. Existing void history remains intact, and
no profitability claim follows from either transport change.

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

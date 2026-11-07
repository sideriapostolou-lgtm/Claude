# memory_climb_check (workflow wf_ea8bd10f-a6e)



---
## result 0 

**Memory investigation: bot service, Kalshi arena deploy (82c045f), Oct 13 2026, Pacific time**

**Short answer**

The climb is not a leak and it did not keep going. The container that shipped the arena (live 4:18 PM) rose from 0.38 GB to about 2.05 GB in its first hour, then sat flat at 2.03-2.08 GB from 5:16 PM until it was replaced at 5:37 PM by the PR #42 (bid-pull) deploy. The same bot reached the same level this morning without the arena: the pre-arena container that ran 11:33 PM (Oct 12) to 5:17 AM averaged about 1.4 GB over its 5 h 44 min, and the service's 24-hour average is 1.15 GB, with a 2.2 GB peak before the arena existed (between 5 AM and 11 AM, possibly two containers overlapping at a deploy). The 1:34 PM to 4:18 PM container that sat at about 0.8 GB was the quiet outlier, which is what made the arena container's rise look new. The arena made the usual climb happen faster (a second Python process plus a lot more churn), but it did not raise the ceiling. At the plateau it never reaches the 8 GB limit.

**1. Shape of the curve (Railway's metrics API only returns window summaries, so these are 1-minute "current" readings plus nested-window reconstruction; timing is +/- a few minutes)**

- 4:18 PM start 0.38 GB, 4:27 PM 0.80, 4:38 PM 1.06, 4:40 PM 1.37, a dip to about 1.1-1.2 around 4:44-4:58 PM, 5:16 PM 2.05, peak 2.077 about 5:20-5:27 PM, then 2.03 (5:33), 1.93 (5:38) and flat around 1.95 until the container was replaced at 5:37 PM. Shape: steps with a dip, then a plateau. Not linear, not a sawtooth with a rising floor.
- Growth rate: 2.7 GB/h in the first 22 minutes, 1.1 GB/h from 4:40 to 5:16 PM, then zero to slightly negative for the last 20 minutes of its life. If the 1.1 GB/h stretch had continued it would have hit 8 GB around 10:40 PM tonight; it stopped at about 2 GB, exactly where this bot has plateaued before.
- The new PR #42 container (also runs the town; hardening line confirms it at 5:37:44 PM) was at 0.76 GB at 31 minutes old, slower than the arena container was at the same age (1.1-1.4 GB).
- CPU: 8 vCPU limit, usage about 1.0 vCPU, meaning the main Python process is at the one-core ceiling of the interpreter lock (matters below).

**2. What the arena log lines say (deployment d24c2876, 4:18 PM to 5:37 PM)**

- `kalshi_arena_status` shows no memory figure (pass times, CPU share, lag, counters only). The town was healthy the whole time: duty 1-5% of a core, pass p99 about 5 ms, lag mostly under 0.4 s, errors 0, no `kalshi_arena_step_failed`, no `kalshi_arena_exited`, no halt. Hardening applied: nice 19, idle scheduler, 1 GiB address-space limit, oom_score_adj 1000. A leaking town would hit the 1 GiB wall, fail passes with MemoryError and exit; none of that happened, so the town cannot hold more than ~1 GB and cannot take the live desk with it.
- `kalshi_arena_feed` shows the live side's hand-over counters, not buffer sizes: 2.55 M events offered, 845 K dropped (33%), 31,278 frames, 374 MB over the socket in the first hour (about 6 MB/min), flush p99 about 13 ms, worst 320 ms. Nothing in it grows except the cumulative counters.
- Side finding that matters more than memory: the town has settled zero windows. All four windows since start were voided (`kalshi_arena_void ... why=feed_dropped` at 4:45, 5:00, 5:15 PM) because the live side drops a third of the feed. The `late` counter rises in chunks of 256/768/1024 (whole batches arriving more than 3 s late), and the real-money status line shows event-loop lag up to 2.3 s and steps up to 8 s. With the whole process pinned at one core, the loop cannot hand over 256 events per step fast enough for roughly 700 Kalshi events per second, so the 1024-event list overflows. Until PENDING_MAX/FLUSH_MAX are raised (or the hand-over moves off the loop), the arena learns nothing.

**3. Code review (branch claude/nightcrawler-memecoin-bot-Gwnb1S at 82c045f, read-only)**

Live side, `/home/user/Claude` → `src/nightcrawler/kalshi_arena.py` class ArenaLink (lines 553-772): the pending list is capped at PENDING_MAX 1024 and drained 256 per step; a partially sent frame is one frame at most; the per-window ladder cache is pruned to windows closing within 2 h 15 min; the flush-time deque is capped at 1024; the socket send buffer is 1 MiB best effort. Nothing unbounded. The hook in `src/nightcrawler/speeddesk.py` (lines 255, 266, 304, 570) is one list append per book/print and one flush per step. PR #41's 323-line change to `speeddesk_model.py` adds config fields and lock/stop logic, no new retained state (the print de-dup memory stays at 10,000 per desk, 256 per town resident).

Town side (`KalshiArena`, lines 974-1300): inbox drained every pass; settled/skipped deques capped at 200; seen prints capped at 20,000 with a bounded order deque; residents at most 24; windows, members, ladders, degraded and per-window fill counts are all dropped at settle/void; graveyard trimmed to 40, events to 60, panel lists bounded; pass-time deques at 2048. Each resident's PracticeDesk prunes per-window entries in `forget()`. No unbounded structure found.

**4. The other things in the container**

- The learner child process runs for under 1 s every 30 minutes in both containers (11:35 PM... 4:19, 4:49, 5:19 PM) and replays 0 coins. Not a factor.
- The 650 MB disk drop between about 4:45 and 5:00 PM is almost certainly the learn tape seal (`src/nightcrawler/learn/tape.py` seal(), `learn/recorder.py` _seal): once every coin of an old day is closed (48 h give-up), the day's raw .jsonl tape is gzipped and deleted. It is the only code path that deletes hundreds of MB. It also reads the whole raw tape into memory twice in the main process (read_bytes, then gzip.decompress to verify), so each seal is a transient spike of about twice the raw tape size; with tapes near 1 GB/day that spike will grow. Worth streaming it in chunks before tapes get bigger.
- The volume has grown about 1 GB/day (0.3 GB two days ago, 2.0 GB now) and the bot reads and writes it constantly (SQLite ledger in WAL mode, the live companion's full mirror file every 10 s carrying 114 archived windows, journals, tapes). That is the most plausible driver of the baseline climb to about 2 GB in every long-lived container.
- Does Railway's memory number include file cache? The service Metrics page only says "Memory - RAM consumption" and does not define it; the Sandboxes page says explicitly that memory "includes the operating system and filesystem cache"; container cgroup memory on Linux normally includes page cache. So part of the 2 GB is very likely reclaimable cache (benign: the kernel drops cache before an OOM kill), but I cannot prove the split from Railway's data, and no process in the container logs its own RSS.

**5. What I would do next (small, read-only to prod until merged)**

1. Log RSS: add `resource.getrusage(RUSAGE_SELF).ru_maxrss` (or /proc/self/statm) to `kalshi_arena_feed` (live process) and `kalshi_arena_status` (town) and the engine heartbeat. One status cycle then tells you process memory vs cache.
2. Raise PENDING_MAX and FLUSH_MAX (for example 8192 and 2048; memory cost is tens of MB at most, Books share their Level objects) so the town stops voiding every window. Treat the 33% drop rate as the real arena bug.
3. Watch rule for the new container: a 1-hour slope above 0.5 GB/h after its first two hours, or any container passing 3 GB, is worth a look; a plateau at 1.5-2.5 GB is this bot's normal.


---
## result 1 

**Skeptic's verdict on the memory diagnosis (bot service, Oct 13 2026, Pacific time; checked at 5:48 PM)**

**Bottom line:** I agree with the main conclusion. This is not a memory leak and nothing needs doing tonight. The climb to about 2 GB is the shape of a bot warming up (reading its 2 GB volume, building its books, plus a second Python process), and the same bot reached the same level this morning before the arena existed. But two claims in the write-up are wrong or overstated, and one caveat is missing, so the "do nothing" verdict is softer than it reads.

**What I verified myself**

1. *The 2 GB level predates the arena: confirmed.* Rebuilding hour-by-hour averages from Railway's windows (1h, 2h, 3h ... 72h), the container that ran 11:33 PM to 5:17 AM averaged about 1.6 GB between 1:45 AM and 5:45 AM including a restart dip, so it sat near 1.7 GB for hours, and the service's 2.2 GB peak falls in that period. No arena, no town.
2. *The arena code is bounded on both sides: confirmed.* Live side: pending list capped at 1,024, 256 per flush, ladder cache pruned to recent windows, flush-time deque capped. Town side: inbox drained every pass, seen-prints trimmed to 20,000, deques capped. The hardening line in both containers reads `nice=19 sched=idle as_limit=1073741824 oom_score_adj=1000 applied=True`. The town kept pid 22 the whole 79 minutes, errors=0, duty 1-7% of a core. A town past 1 GB would fail passes and exit; it did not. So the town cannot be what grows to 8 GB.
3. *Feed drops and voids: confirmed, and real.* 2.55 M events offered, 845 K dropped (33%) in the arena container; the new container is at 32% after 5 minutes. All four windows since 4:18 PM voided `why=feed_dropped` (4:45, 5:00, 5:15, 5:30). The `late` counter rises in whole batches. This is an arena-learning bug, not a memory one, and the write-up is right to flag it.
4. *The 650 MB disk drop is almost certainly the tape seal.* I listed every code path in the bot that deletes a file: tape `finish_seal`, tmp files for the key store, ledger and town saves. Only the seal removes hundreds of MB. The seal does not log, so this stays "only candidate" rather than proven.

**Where the diagnosis is wrong or overstated**

- *"The PR #42 container was at 0.76 GB at 31 minutes old, slower than the arena container."* Wrong. It went live at 5:37:44 PM and is 10 minutes old; it read 0.96, 1.01, 1.08 and 1.12 GB between 5:45 and 5:48 PM, versus about 0.80 GB for the arena container at the same age. Same warm-up curve, if anything slightly faster. The "31 minutes" cannot be right.
- *"The 0.8 GB container was the outlier; the arena did not raise the ceiling."* Half right. Afternoon containers ran 0.7-1.1 GB (hourly averages 0.73, 0.85, 0.92, 0.98, 1.14), the overnight one about 1.7, the arena one about 2.0. The arena container is at the top of the historical range, roughly 0.3-0.5 GB above the previous highest sustained level. That is what a second Python process plus more churn should cost; it is not a runaway, but it did nudge the level up.
- *The seal's transient is bigger than "twice the tape."* `tape.py` `seal()` does `data = path.read_bytes()` and then `data = data[:data.rfind(b"\n") + 1]`, which makes a second full copy, so the peak is about 2x the raw day while compressing, then about 1x again on the verify pass. For a ~750 MB day that is ~1.5 GB of transient heap inside the real-money process, roughly daily around 5 PM, growing with the tape. Still fine at 8 GB today; worth streaming before tapes double.
- *Missing caveat: no container has lived longer than 5 h 44 min in the last two days* (about 40 deploys in 48 hours). "It plateaus" has only ever been observed for up to 6 hours. A slow leak under 0.1-0.2 GB/h would be invisible at that lifetime. Also, the bot's daily average memory went 0.24 GB (three days ago) to 0.45 to 1.1 GB (last 24 h), tracking the volume growing 0.3 to 2.6 GB and the feature set. That is a trend to watch, and it is the bot's, not the arena's.
- *Cache vs process memory: cannot be split from Railway's data.* The service docs only say "Memory: RAM consumption"; the Sandboxes page does say memory "includes the operating system and filesystem cache"; Linux cgroup accounting counts file cache. The bot logs no process memory at all (the learner's `max_rss_mb` goes into learn.db, not the logs). The write-up's uncertainty here is honest and correct.

**Is it a leak?** No evidence of one. Shape: fast rise in the first hour, then flat for the 20 minutes observed; a pre-arena container sat near 1.7 GB for hours. Consistent with warm-up plus the town's own footprint plus file cache. Unproven beyond 6 hours.

**Urgency:** none. Even a pessimistic unseen 0.2 GB/h from 2 GB is about 30 hours to 8 GB; containers restart at every deploy anyway; the kernel drops cache before an OOM kill; the town is first in line to die and dies alone.

**Safe action:** nothing operational, no restart. Two small code changes when convenient: log RSS of the live process and the town in their status lines so the next look is definitive, and stream the seal in chunks (drop the slice copy). Set a mental alarm at 3-4 GB or any container still climbing after its second hour. Separately, fix the feed drops: raising PENDING_MAX/FLUSH_MAX works, but the town already coalesces about 90% of what it receives as redundant book updates, so coalescing books per (window, side) on the live side before sending would remove most of the drops without a bigger buffer or a longer flush.

Files referenced (read-only, branch `claude/nightcrawler-memecoin-bot-Gwnb1S` at 82c045f): `/home/user/Claude/src/nightcrawler/kalshi_arena.py` (ArenaLink lines 553-772, hardening 1817-1872), `/home/user/Claude/src/nightcrawler/learn/tape.py` (`seal()` lines 364-398, `finish_seal` 405-416), `/home/user/Claude/src/nightcrawler/learn/recorder.py` (`_seal` 385-413), `/home/user/Claude/src/nightcrawler/learn/job.py` (`_usage` 161-167, `MEMORY_LIMIT_BYTES` 93).

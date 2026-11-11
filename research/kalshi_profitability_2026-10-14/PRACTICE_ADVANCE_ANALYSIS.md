# Practice advance: bounded read-only architecture review

**Source reviewed:** `1e8d0be07b280292fa873a2f5da9b22dd02f28c3`, checkout `/workspace/nightcrawler-mirror-speed`. No source/tests edits, production queries, account access, credentials, order operations, or release actions. The profiling artifacts below are synthetic offline evidence. This report selects no correction or release.

The measured history cost is real in the offline fixture: `advance` reconstructs settlement membership and visits retained windows on every call. However, its first pass also updates persisted/displayed rejection reasons when there are no orders. An empty-order early return, an order-window-only pass, or deleting settled model history would therefore change the current contract. There is no justified tiny correction that eliminates this history cost while retaining the present public-mutation and complete-state behavior. The previously rejected mutable-history cache remains rejected.

## Evidence and its limits

Original artifacts are preserved:

- [Profile script](/workspace/shared/feed-hotpath-profile.py), SHA256 `f1ca77689d8b22106efdfb4777d31fc516b620b2ccd71dd4f9bd1c86d41ee57d`.
- [Recorded methods, source hashes and limitations](/workspace/shared/feed-hotpath-profile-artifacts/SUMMARY.json).
- [All repeated timing samples and model counts](/workspace/shared/feed-hotpath-profile-artifacts/results.json).
- [512-history book cProfile](/workspace/shared/feed-hotpath-profile-artifacts/history-512-book.txt), [512-history trade cProfile](/workspace/shared/feed-hotpath-profile-artifacts/history-512-trade.txt), [zero-history book cProfile](/workspace/shared/feed-hotpath-profile-artifacts/history-0-book.txt). Matching binary `.prof` files are alongside them.

The profiling receipt records base `26875597f1ba5eba26b088d3d44fa45f6c6d8ab5`. All six recorded profiled-module SHA256 values were checked against the requested `1e8d0be` checkout and match; the reviewed callback/model source is the same. All 33 local source/artifact links were checked for existence.

Each sample processes 1,000 native WS text frames through the actual ClientProtocol parser, assembler, public `TimingClientConnection.recv`, JSON decoding, `MarketState.apply`, and 2,000 runner callbacks. Current and next Kalshi windows alternate. There are four current/next side books. A frame is supplied and received at a time; this is **not** a queued native burst or a scheduler/backlog experiment.

| Settled history per practice/twin model | Total windows per model | Book batch median wall | Trade batch median wall |
| ---: | ---: | ---: | ---: |
| 0 | 2 | 111.102 ms | 86.195 ms |
| 128 | 130 | 153.033 ms | 123.866 ms |
| 512 | 514 | 247.530 ms | 213.616 ms |

Five ordinary samples per case use real wall/process/thread timing. Median process and thread CPU closely match wall time. The default BTC warm-up uses 3,602 coherent scripted seconds; no sigma rules are weakened. BTC is refreshed before each one-second batch. Past windows are valid **zero-position** observations settled through the actual practice, live book, and twin APIs. There are no invented fills or financial histories. Practice/twin orders and live intents remain zero. This population cannot establish costs for pending orders, partial fills, reservations, locks, cancellation load, or actual live-account history.

At 512 settled windows, the instrumented book batch calls `PracticeDesk.advance` 4,000 times: 0.168 s cumulative, 0.129 s self. The zero-history book batch has the same 4,000 calls: 0.047 s cumulative, 0.010 s self. Snapshot refresh stays approximately flat at 0.024–0.025 s. The trade batch also has 4,000 `advance` calls and about 0.167 s cumulative at 512 history. These are **cProfile** times, not the ordinary batch medians. The profiler also spans one-time payload construction, native connection initialization, and one BTC refresh; ordinary batch timers exclude preparation. Nested cumulative figures must not be added.

Tracemalloc starts after fixture construction: its roughly 0.38 MB book / 0.80–0.84 MB trade peaks cover batch/setup allocations, not all fixture memory. Recorded RSS is the process-lifetime high-water mark, not a per-case allocation. SQLite fixtures and checkpoint writes happen only in fresh artifact directories before measured callbacks. No network, account client, arena, account-worker contention, native `_session` scheduling/yields, TLS/kernel/provider latency, or checkpoint/mirror work occurs inside the ordinary timed batch.

This establishes an offline mechanism and a history-dependent cost in that population. It does **not** establish production cause, an optimal candidate, real throughput capacity, a production speedup, or a financial verdict. Identified post-mirror WorkTrace evidence remains the integration owner's prerequisite for choosing further work.

## Actual work and call ordering

Exact references below refer to the reviewed SHA, even if the checkout later advances.

1. [`PracticeDesk.advance`, model:877](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:877) builds `{item.window for item in self.closed}`, then visits every `self.windows` value in insertion order. Settled slugs are skipped. For each remaining window it recomputes `_blocked_unsettled`; a nonempty reason updates `last_reason` and calls `cancel`, retaining eligible locks. Only after this entire cancellation/reason pass does the existing take-order loop resolve first eligible post-delay evidence.
2. [`_blocked_unsettled`, model:597](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:597) preserves reason priority: not-started, cutoff, daily loss stop, BTC freshness, opening, then both books' freshness. Conditions can change with time, a different book, a daily reset/settlement, or metadata; they are not functions of the incoming book alone.
3. [`cancel`, model:788](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:788) walks current orders in insertion order, produces cancellation events, removes orders and updates counters. It cannot be treated as an unordered set operation. `KEEPS_LOCKS` at model:445 and the later take-order logic at model:894–939 preserve existing lock and IOC behavior.
4. [`SpeedRunner.on_book`, runner:280](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk.py:280) observes even rejected quotes, accepts the main practice book, publishes a fresh snapshot, calls the live companion, then advances the main practice desk. [`KalshiLiveDesk.on_book`, live:1063](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_live.py:1063) independently accepts the twin book and advances the twin. Thus each accepted side book causes two model advances; a two-side market message causes four.
5. [`SpeedRunner.on_trade`, runner:298](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk.py:298) calls main-practice trade processing before live/twin trade processing. [`PracticeDesk.on_trade`, model:942](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:942) advances **before** trade identity/aggressor/freshness filtering and before queue consumption. A buy, duplicate, or otherwise rejected trade can still cause an advance. The benchmark legitimately includes this behavior.
6. [`KalshiMarketWS._session`, receiver:432](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_kalshi_ws.py:432) finishes all book/trade callbacks of one message before its explicit yield at receiver:444. A complete message is the fairness boundary, not permission to merge or defer its individual model rechecks. The offline profile omits `_session` itself.
7. [`evaluate`, model:972](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:972) begins with `advance` before lock work, sigma and strategy decisions. [`KalshiLiveDesk.step`, live:2378](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_live.py:2378) separately advances the twin before pull/client work. Coin desks and arena residents also call this shared model: coins:220, arena:1225. A shared-model change has a wider scope than the two profiled callbacks.

For closed history `C`, retained windows `W`, blocked unsettled windows `B`, and outstanding orders `Q`, the first pass is approximately `O(C + W + B*Q)` plus freshness checks. Resolving take orders adds `O(Q)` and relevant ask-depth work. The present source already avoids the older `any(closed)` rescan inside every `_blocked_unsettled` call. With 512 closed windows and only two unsettled windows, repeated `O(C+W)` work remains despite `Q=0`; this is the cost highlighted by the new fixture, not the previously corrected nested-history problem.

## Why seemingly small scan removals change behavior

**No-orders early return:** invalid for complete-state equivalence. `last_reason` is panel `window_reasons` at [runner:443](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk.py:443), serialized at [model:1223](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:1223), and restored at [model:1277](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:1277). Existing [history tests:47](/workspace/nightcrawler-mirror-speed/tests/test_speeddesk_history_hotpath.py:47) explicitly require cutoff reasons for unresolved historical windows, BTC-stale for the current window, and not-started for the future window with no orders. Moving these updates to `evaluate`, panels, or checkpoints changes intermediate saves and their timing.

**Only advance the changed window:** invalid. A book/trade for B currently cancels a blocked order in A; the clock or global day-stop/BTC state may have changed. The full window cancellation pass precedes all take fills. Resolving B first can spend liquidity or alter counters before a cancellation that previously preceded it.

**Once per pair/message or skip buy/duplicate trades:** invalid without a separately approved behavior change. The first side update can invalidate a take before the second side arrives; a later favorable book must not replace the first genuine failed recheck. Even callbacks with the same nominal input timestamp can observe different controller wall time. Existing [snapshot test:49](/workspace/nightcrawler-mirror-speed/tests/test_speeddesk_snapshot_cache.py:49) pins publication and an advance for every accepted book; [fairness tests:106](/workspace/nightcrawler-mirror-speed/tests/test_speeddesk_feed_fairness_independent.py:106) pin complete-message processing before yielding.

**Forget old windows in the main runner/twin:** not a serialization-only optimization. [`forget`, model:1131](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:1131) removes windows, inventory, closed records, books, consumed depth, reasons and reporting metadata, and bounds day/order tables. The arena intentionally uses this after its separate settlement record at [arena:1325](/workspace/nightcrawler-mirror-speed/src/nightcrawler/kalshi_arena.py:1325). The main runner and live companion do not have the same ownership/retention contract. Live checkpoint archive chunks at [live:950](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_live.py:950) change persisted serialization; they do not prune the twin's mutable model history.

## Mutation and lifecycle constraints: do not revive the rejected cache

The original rejection is explicit in [QUIET_WORK_RESULTS:87](/workspace/nightcrawler-mirror-speed/research/kalshi_profitability_2026-10-14/QUIET_WORK_RESULTS.md:87) and [SCORECARD_GROUPING:34](/workspace/nightcrawler-mirror-speed/research/kalshi_profitability_2026-10-14/SCORECARD_GROUPING.md:34). Mutable `Window.slug` and arbitrary public history mutation can invalidate an active-window cache without a version change.

- `windows` and `closed` are public mutable dict/list attributes ([model:475](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:475)). Settlement records being frozen does not make the list immutable.
- [`add_window`, model:504](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:504) can replace metadata under an existing key. The loop uses `window.slug`, which can diverge from that dictionary key after mutation.
- [`settle`, model:1156](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:1156) checks current history, cancels that window's orders, appends its settlement, and updates real model counters. A new settlement must be seen by the very next pass.
- `forget` reconstructs the list and allows a later add of the same slug. [`from_state`, model:1257](/workspace/nightcrawler-mirror-speed/src/nightcrawler/speeddesk_model.py:1257) replaces the closed list after adding windows; restart drops practice orders by design.
- The existing [history test:40](/workspace/nightcrawler-mirror-speed/tests/test_speeddesk_history_hotpath.py:40) replaces `closed` with an observable list subclass. [History test:52](/workspace/nightcrawler-mirror-speed/tests/test_speeddesk_history_hotpath.py:52) pins new settlement, settled-first behavior even with contradictory times, forget and re-add.

Concrete invalidation failures:

1. Replace one `closed[i]` record with another window identifier without changing list identity or length. An `(id, len)` membership cache remains stale.
2. Mutate an existing Window's `slug`, start/end, or venue terms. An active-key index can skip a window that the current value-based scan would check.
3. Forget/re-add a slug, restore another model, or replace a same-sized window mapping. A lifecycle counter maintained only by the obvious settle method is insufficient.
4. Cache reasons or financial summaries across callbacks while BTC/books/time/day-stop state changes. This changes cancellation priority and admission behavior.

An owned authoritative unsettled-ID index would require a new mutation/ownership contract, instrumented containers or immutable snapshots, restoration/migration rules, and fallback proof for every exposed mutation. It is not a tiny optimization under the current contract and is not proposed here. Checking only identity, length, exact outer type or an incremented settle generation does not fix these failure cases.

## Smallest separately testable work, if later production evidence warrants it

There is **no selected history-scan correction** from this read-only review. Retaining all current mutation and save semantics leaves the per-call history membership/iteration necessary. Do not substitute the prior rejected persistent cache or delete per-book advances to achieve a lower benchmark number.

A narrower, independently assessable opportunity exists only for a different population: remove repeated **order-list scans** within one `advance` call by locally grouping current orders by their current window identifier, preserving window insertion order and order insertion order. The grouping would be ephemeral, contain no reused financial snapshots, and expire when the call returns. It must preserve the exact first cancellation phase, lock exceptions, `_event`/`_count` effects, and subsequent take-resolution order. Custom model/order/window mappings, subclasses, overridden checks/cancel methods, or mutation during the pass need the unchanged original path unless explicitly proved compatible. This does **not** eliminate `O(C+W)` and cannot explain the measured `Q=0` growth. It is not currently warranted by this fixture; it should only be considered if identified production evidence shows material `B*Q` work.

Before considering any such bounded change, require:

1. Identified post-mirror spans attributing material time to the corresponding callback population, with actual order/window/history counts and coverage limits. Whole-cycle, nested and callback times must not be added as disjoint populations.
2. Differential full-state and ordered-event replay for first eligible IOC evidence, REST pre-delay requests, ask disappearance/reappearance, consumed depth, partial fills, queue-ahead ordering, duplicates/buy trades, day boundary/stops, cutoff locks, stale BTC/books, and cancellation in a window unrelated to the incoming message.
3. Mutation cases above, settlement between adjacent callbacks, restore/forget/re-add, expired-but-unresolved windows, metadata replacement, and the arena/coin shared-model callers. Compare `to_state`, reason maps, fees/counts and saves as well as fills.
4. Existing golden, history, snapshot and fairness tests plus independent review of the exact candidate, full required checks, and the integration owner's separately authorized release/verification workflow.

The immediate next action remains the root's review of identified post-mirror WorkTrace evidence. No further financial or strategy task is authorized by this performance analysis.

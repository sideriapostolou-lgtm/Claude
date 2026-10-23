# arena_build_review (workflow wf_eb0dd718-1cf)



---
## result 0 

Plan written to /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_arena/PLAN.md. The benchmark scripts behind its measured numbers (gil_bench.py, desk_bench.py, desk_bench2.py, judge_bench.py) are in the same folder.

# Kalshi arena: build plan (practice money only)

Owner's request (2026-10-13), as relayed: "Give our bots the incentive they're giving Grok bots: make money or die."
Plan written 2026-10-13 by Claude after reading arena.py, deskguard.py, speeddesk_model.py, speeddesk.py,
speeddesk_live.py, speeddesk_live_model.py, speeddesk_coins.py, speeddesk_kalshi.py, engine.py, pagestate.py,
config.py and their tests. Work on branch `claude/kalshi-arena`, cut from `origin/claude/nightcrawler-memecoin-bot-Gwnb1S`
(b539aed, which already holds this branch's starter cap). Commit locally only; do not push.

## 0. Summary

Add one new module, `src/nightcrawler/kalshi_arena.py`: 12 practice residents (one CONTROL running the live rules,
11 challengers), each a `PracticeDesk` with its own genes. They trade the live KXBTC15M windows in a daemon thread
that belongs to the speed desk's `SpeedRunner`. The thread reads the runner's existing immutable `LiveSnapshot`
(windows, Bitcoin price and time, sigma, maker windows, outcomes) and drains a bounded queue of Kalshi book, trade
and gap events. The producer side is one `deque.append` per Kalshi book or trade, measured at 0.14 us; `on_tick`
gets no new code at all. Residents pay rent, are evicted when broke, unable to pay rent, or judged `losing` by
`deskguard.judge`, and are replaced by children of the richest. A challenger becomes a CANDIDATE (display only)
when it is `winning` on 100 or more settled windows and its paired per-window difference against the control has t >= 2.

The practice model gets opt-in `SpeedConfig` fields for starter size, starter timing, rounds, whole contracts,
locks and protective stops. Every default reproduces today's behaviour, which a golden-fixture test proves. The
dashboard gets `money["kalshi_arena"]` from a small `panel.json`. No live setting, order path, client or key is
reachable from the arena.

## 1. Facts from the code that shape the design

- The live companion's event loop is the speed desk's asyncio loop. `MarketFeeds` call `SpeedRunner.on_tick/on_book/
  on_trade/on_windows/on_status` (speeddesk.py 207-285) on that loop, and `_run_live` (460) runs
  `KalshiLiveDesk.run` on the same loop. Any work in those callbacks delays real orders, so the arena hooks there and
  adds only O(1) appends.
- `SpeedRunner.live_snapshot()` (384) returns an immutable `LiveSnapshot` that is replaced atomically and documented
  as safe to read "including from the HTTP worker thread". It already holds everything except trades and the exact
  book sequence: Kalshi windows (copies), books, `bitcoin_price/at`, the runner's cached `sigma` (the same one the
  live `_decide` uses), `maker_windows` and `outcomes` (the runner's settlements). On a feed gap the runner sets
  `books={}` and `maker_windows=frozenset()` (258, 275).
- The live twin (speeddesk_live.py 240) is never asked to decide by itself. It only mirrors real placements
  (`_send` -> `twin.place`, 967), and locks are not mirrored at all (`_send_lock`, 1113). So nothing today simulates
  "the live rules" independently. Every arena resident, including the control, must run `PracticeDesk.evaluate()`
  itself, the way `SpeedRunner.step` does for the main practice desk (538).
- The live rule differs from `PracticeDesk` in ways the control needs (speeddesk_live.py `_decide` 1178,
  `_lock` 1049; speeddesk_live_model.py `LiveLimits` 48, `can_buy` 327, `can_lock` 366):
  - New buys stop at `LiveLimits.lock_s = min(899, max(LOCK_S, CUTOFF_S, 50))`, which is 240 s, not the 180 s
    cutoff. The twin's `cutoff_s=180` is harmless only because the twin never decides by itself.
  - `SPEEDDESK_KALSHI_CLIP` (5) caps every real order (starter, balancing and lock; commit c25d606), not only the
    first buy. The starter is also limited to `floor(window_usd / pair_cap)`.
  - Live orders are whole contracts. The practice model searches in 0.01 steps.
  - The live LOCK: from `lock_s` before the close until `LOCK_MARGIN_S` (20 s) before it, the lighter side is bought
    at the ask, with an IOC limit rounded up to the cent and at most `lock_max_price` (0.97). Size is
    `min(floor(unpaired), clip)`. It needs fresh books, nothing pending in the window, and no budget, pair-cap, edge
    or loss-stop check. `PracticeDesk` has no lock at all.
  - Takes are off in production (`SPEEDDESK_TAKE_EDGE=1.0` on Railway since 12:17 UTC), so the live desk is
    maker-only. The control reads the deployed settings, so it follows them.
- `PracticeDesk` costs, measured here (Python 3.13, desk_bench*.py in this scratchpad):
  - 12 desks evaluated with their own `BitcoinTape.sigma` take 9.7 ms median (0.9 ms of sigma per desk). With a
    fed sigma they take 1.27 ms, about 0.1 ms per desk.
  - Two books plus `advance` for 12 desks take 0.10 ms. With 300 settled windows kept per desk this rises to 0.77 ms
    median and 2.9 ms max, because `advance` and `evaluate` walk every window ever added. Settled windows must be pruned.
  - One desk's `to_state()` plus `json.dumps` takes 4.8 ms and 240 KB (the tape, plus `seen_trades` of up to 10,000
    ids). Residents' desks are therefore never persisted.
  - `deskguard.judge` takes 0.08 ms at n=100, 0.61 ms at n=1000 and 1.2 ms at n=2000.
- GIL contention is measured too (gil_bench.py). A main thread sleeping 1 ms wakes late by 0.075 ms median and
  0.50 ms p99 on its own. Two background-thread patterns change that:

  | Background thread | Main thread wakes late by (median / p99) |
  |---|---|
  | Continuously busy | 5.2 ms / 10.5 ms (the 5 ms switch interval) |
  | 0.3 ms work slices, then a 3 ms sleep | 0.077 ms / 0.335 ms (baseline) |

  Producer-side cost alone does not make the arena cheap; the arena thread must also yield the GIL often.
- Production runs `python:3.12-slim` (Dockerfile; `mypy python_version = "3.12"`), not 3.13, and has the GIL.
- Dashboard: `build_page_state` sets `money["arena"]` and `money["speeddesk"]` (pagestate.py 3147-3148). Each is
  built by a function that reads one saved file and returns None on failure. `town_ledger` and `_money` read
  explicit keys, so a new key is never summed. The UI files (`world3d.py`, `worldtycoon*.py`) are not touched.
- arena.py is the style reference: module docstring with rules and constants, a plain-words `_event` log, a bounded
  graveyard, `child_genes` nudging by `MUTATE` of the range, top-half parents chosen with `rng.random() ** 2`, and a
  `panel_state` read from file. engine.py starts optional desks in try/except blocks that log
  `*_not_started error=<Type>` (2702-2722).

## 2. Brief corrections, unsafe or impossible items, and the alternative

1. **"Extra cost per tick < 0.5 ms" is provable for the producer, not for the process.** Any CPU work in the
   arena's thread competes for the one GIL. Measured above, a busy thread adds about 5 ms to the loop's wake-ups.
   The alternative is built in from the start:
   - a cooperative scheduler (work slices of 0.3 ms or less, then a 2-3 ms sleep, at most about 10 % duty);
   - the runner's sigma is fed in instead of 12 recomputations;
   - settled windows are pruned;
   - no per-desk persistence, and a state file of 192 KB or less, so one `json.dumps` holds the GIL for about 1 ms or less;
   - no fsync, so the arena never competes with the live ledger's durable writes;
   - telemetry and the enable flag as a kill switch.

   Tests prove the producer cost and the slice bound, and an opt-in two-thread test measures wake-up lateness.
   Production's figure comes from the `kalshi_arena_status` log line. If that ever shows an impact of 0.5 ms or
   more, move `ArenaWorker` into a subprocess behind the same `ArenaFeed` interface (see 6.6); the producer code
   does not change.
2. **"The CONTROL runs the exact live genes" can only mean "the live rules as the practice model simulates them".**
   Some differences remain:
   - fills are simulated (maker prints with displayed queue ahead; a take is rechecked after latency);
   - live places one order per account read, about one a second; practice can place both sides in one evaluation;
   - a live lock IOC can sweep several levels up to its limit; practice fills the top level only;
   - live day and total stops count money still at risk, and the total stop halts; practice's day stop counts
     settled P&L, and the control never halts;
   - live leaves owner-traded windows and integrity stops alone.

   The control is the benchmark inside the arena, and every candidate claim is relative to it. The biases are
   largely shared, so paired differences mean more than absolute arena dollars. The panel says so.
3. **The candidate bar is weak as a proof.** About 11 challengers plus a steady flow of births, checked after every
   window (optional stopping), with genes close to the control's (small paired variance) and winner's curse after
   evictions: false candidates will appear. Keep the brief's rule as the flag, but also:
   - show the economic size (mean $ per window against the control);
   - keep "since flagged" paired statistics as a free out-of-sample check;
   - label every candidate "a lead for a pre-registered test, not proof", as arena.py does.

   Nothing is automatic.
4. **Rent arithmetic.** $5 a month / 30 days = $0.167 a day for the whole service. $0.20 a day *each* means every
   resident must earn the whole bill plus 20 %, so the town pays 12 times the real bill. That is a fair "make money
   or die" bar, but say so in the docs. The brief asks for both "make it a constant" and "a validated Settings
   field": `RENT_USD = 0.20` is the module constant and the setting's default.
5. **"$50 (the real account's size)".** docs/ACCOUNTS.md records $25.00 at the first Kalshi balance read
   (2026-10-12). Use `START_CASH = 50.0` as asked, and check the account size; update ACCOUNTS.md if the owner
   deposited more. That is a doc fact, not a key.
6. **Lock start 120-300 s against the live coupling.** `LiveLimits` raises `lock_s` to at least `CUTOFF_S` (180), and
   live buying stops when the lock starts. So the gene is `close_s` (120-300): it sets both the resident's buying
   cutoff and its lock start, exactly as live does when `SPEEDDESK_KALSHI_CUTOFF_S` equals `SPEEDDESK_KALSHI_LOCK_S`.
   Some genes cannot be adopted through settings at all and would need code plus the owner's word:
   - lock off (live cannot switch its lock off);
   - stop, rounds, starter timing and filters;
   - a starter different from the clip (live's clip caps every order).

   The candidate card lists "settings that express it" separately from "needs code".
7. **Gene ranges above the live ceilings are not adoptable.** `LiveLimits` clamps `max_imbalance` to 0.25 or less and
   `pair_cap` to 0.99 or less. So `max_imbalance` runs 0.10-0.25 and `pair_cap` 0.95-0.99.
8. **Real-money files.**
   - The hook lives in speeddesk.py, the host of the live loop, and is three one-line appends. speeddesk_live*.py is
     not edited.
   - config.py is on AGENTS.md's real-money list; only practice settings are added there.
   - speeddesk_model.py is imported by the live risk book (Window, Inventory, settlement); only opt-in fields and new
     methods are added there, and no existing path changes.
   - The commit and any PR title say "touches real money (event-loop hook only)". The pinning tests are in section 12.
9. **"Python 3.13".** The code must run on 3.12. Do not use `copy.replace` or other 3.13-only APIs.
10. **Restart.** A deploy in the middle of a window restarts every resident's desk. Restoring 12 practice desks'
    internals would cost about 5 ms and 240 KB each. Instead, a window open across a restart is **void for every
    resident** (no record, no P&L), counted in `town.void_windows`. This is fair because it is equal for everyone.

## 3. Files

New:
- `src/nightcrawler/kalshi_arena.py`, about 700 lines in arena.py's style. Its contents:
  - Constants: `GENES` (the table below), `FILTERS: dict[str, SignalFilter] = {}` (the slot).
  - `ArenaConfig`, a frozen dataclass: `data_dir`, `population`, `rent_usd`, `broke_usd`, `start_cash`, `control`
    (genes), `fixed` (SpeedConfig kwargs common to all). It holds no Settings and no Secret.
  - Functions: `arena_config(settings) -> ArenaConfig` (the only reader of Settings), `live_genes(settings)`,
    `fixed_config(settings)`, `random_genes(rng)`, `child_genes(parent, rng)`, `speed_config(genes, fixed) ->
    SpeedConfig`, `adoptable(genes) -> {"settings": {...}, "needs_code": [...]}`, `style(genes) -> str`,
    `rule_id(genes) -> str` (sha256 of canonical JSON, 12 hex characters).
  - `FedTape(BitcoinTape)`: `feed(price, at, sigma)`; `tick` just records price and time (no 3,600-entry rebuild);
    `sigma()` returns the fed value; `opening()` returns None (Kalshi opens on the venue strike).
  - `ArenaFeed`: `put(item)` is the producer side, O(1), never raises, bounded at `QUEUE_MAX`, and counts drops.
    The consumer drains with `drain(max_items)`. Counters: `put`, `dropped`, `closed`.
  - `Resident`: the record row plus its `PracticeDesk`.
  - `KalshiArena(config, snapshot: Callable[[], LiveSnapshot], *, clock)`: producer methods `feed_book`,
    `feed_trade`, `feed_gap`; lifecycle `start(stop_event)` and `stop()`; `step(now)` is one pass of the loop and
    public for tests; private `_settle_window`, `_rent`, `_evict`, `_births`, `_candidates`, `_yield`, `_save`,
    `_status`.
  - `panel_state(data_dir, now)` reads `panel.json` only.
- `tests/test_kalshi_arena.py`, `tests/test_kalshi_arena_feed.py`, `tests/test_speeddesk_model_genes.py`.
- `tests/fixtures/speeddesk_model_golden.json`, generated from the unmodified model before any model edit (step 1 in
  section 13).

Changed:
- `src/nightcrawler/speeddesk_model.py`: opt-in fields and behaviour (section 5).
- `src/nightcrawler/speeddesk.py`: construct, start and stop the arena, plus the three appends (6.1).
- `src/nightcrawler/config.py`: four settings (section 9).
- `src/nightcrawler/pagestate.py`: `kalshi_arena(settings, now)`, `money["kalshi_arena"]`, and one line in the
  schema docstring.
- `.env.example`, `docs/SPEEDDESK_SPEC.md` (new section 12, "Kalshi arena"), `docs/WORKLOG.md` (new top entry).
- Not changed: `engine.py`, because the arena's lifecycle hangs off `SpeedRunner` inside the speeddesk thread, and the
  engine's `App.close` already stops it through the shared stop event. Also unchanged: `speeddesk_live*.py`,
  `deskguard.py`, `arena.py` and all UI files.

## 4. Genes

Values not drawn from the genes are the same for every resident, the control included. They come from the deployed
live settings through `LiveLimits` clamps (`fixed_config`):
- `take_edge` = `SPEEDDESK_TAKE_EDGE` (1.0 in production, so no takes);
- `clip` = `SPEEDDESK_KALSHI_CLIP` (5), for every order after the starter;
- `window_usd`, `open_usd` and `day_stop_usd` = the LiveLimits values ($10, $20, $6);
- `latency_ms` = `SPEEDDESK_LATENCY_MS`;
- `whole_contracts=True`;
- sigma from the runner.

| Gene | Range or values (grid) | Control value (live) | Practice behaviour | SpeedConfig field (new? default = today) |
|---|---|---|---|---|
| `make_edge` | 0.020-0.060 (0.005) | `SPEEDDESK_MAKE_EDGE` | Resting bid at `floor((fair - make_edge)/tick)*tick` | `make_edge` (existing) |
| `starter` | 2-10 contracts (1) | `int(LiveLimits.clip)` | Size of the first buy of a window and of each round; capped at `floor(window_usd/pair_cap)` as live does | `starter_clip: float = 0.0` (NEW; 0 means use `clip`) |
| `pair_cap` | 0.95-0.99 (0.005) | `LiveLimits.pair_cap` | Matched pair cost limit including fees | `pair_cap` (existing) |
| `max_imbalance` | 0.10-0.25 (0.01) | `LiveLimits.max_imbalance` | Imbalance limit once balanced | `max_imbalance` (existing) |
| `starter_delay_s` | 0-180 s (5) | 0 | No starter before `start + N` (balancing and locks unaffected) | `starter_delay_s: float = 0.0` (NEW) |
| `starter_stop_s` | 0-600 s (10) | 0 | No starter at or after `end - N` (no effect when at most `close_s`) | `starter_stop_s: float = 0.0` (NEW) |
| `close_s` | 120-300 s (5) | `LiveLimits.lock_s` (240) | Buying stops (`cutoff_s`) and the lock starts here, as live couples them | `cutoff_s` (existing) = `close_s`; `lock_s` below |
| `lock` | on / off | on | On: from `close_s` before the close until 20 s before it, complete the unpaired side at the ask, up to `lock_max`, `min(floor(unpaired), clip)` contracts, IOC, bypassing budgets, pair cap, edge, cutoff and day stop | `lock_s: float = 0.0` (NEW; 0 means no lock) = `close_s` when on |
| `lock_max` | 0.90-0.99 (0.01) | `LiveLimits.lock_max_price` (0.97) | Highest price per lock contract | `lock_max_price: float = 0.97` (NEW; unused while `lock_s` = 0) |
| `stop` | on / off | off | On: from `end - stop_s`, when completing would cost at least `stop_cost` (heavy side's average cost including fees + light ask + taker fee), complete at the ask through the lock path (cap `lock_max`) | `stop_s: float = 0.0`, `stop_pair_cost: float = 0.0` (NEW; 0 means off) |
| `stop_s` (X) | 300-840 s (10) | n/a | Start of the stop period before the close | (above) |
| `stop_cost` (T) | 1.05-1.25 (0.01) | n/a | Trigger level | (above) |
| `rounds` | on / off | off | On: once a window's pair is complete (up = down > 0, nothing pending), the next buy may be a fresh starter-size buy, then balancing-only until even again | `rounds: bool = False` (NEW) |
| `filters` | `{name: params}`; none registered, all off | `{}` | A starter gate: a registered filter returning False blocks starters only | `PracticeDesk.starter_gate` attribute (NEW, default None) |

Stop semantics: the brief says "complete the pair at the ask when pair cost would reach T". This plan reads it as a
stop-loss trigger: the stop fires when the cost to complete *rises to* T. It caps the 16:00/16:15 UTC pattern (a lock
completing at a total cost of $1.37 or $1.29) at about T. If the owner meant "accept a completion cost up to T", it is
the same code with the comparison flipped. Note the choice in the spec.

Genes:
- **Random genes:** uniform draws on the grid; booleans 50/50.
- **Child genes:** each number is nudged by `U(-MUTATE, MUTATE) x range`, with `MUTATE = 0.12`, then clamped and
  rounded to the grid. With probability `NEW_VALUE_P = 0.1` a number is instead redrawn uniformly ("sometimes a new
  gene value"). Each boolean flips with probability 0.1. A registered filter is toggled with probability 0.1 (a no-op
  while none are registered).
- **Control genes:** may lie outside the ranges; its children are clamped into them.

Filter slot: `SignalFilter = Callable[[Window, float, LiveSnapshot], bool]`, where True allows the starter.
`FILTERS` ships empty. A test registers a fake filter to prove the slot works. A future filter is one entry plus its
own lab test.

## 5. Practice model changes (speeddesk_model.py)

Everything here is opt-in; with the default `SpeedConfig()` no code path changes.

1. **`SpeedConfig` gets nine fields**, with the defaults above. `__post_init__` gains:
   - `0 < lock_max_price <= 0.99`;
   - `lock_s < 900` and `stop_s < 900`;
   - `stop_pair_cost == 0` or `1 < stop_pair_cost <= 2`.

   The existing finite and nonnegative check covers the rest; booleans pass it.
2. **New module function `config_state(config) -> dict`**: `asdict(config)` without the new fields that sit at their
   defaults (the `without_default_lock` precedent, speeddesk_live_model.py 88). `to_state()` writes
   `"config": config_state(self.config)`. A rolled-back release can then still read new state files, and old states
   load because missing fields take their defaults.
3. **`PracticeOrder.lock: bool = False`.**
4. **`PracticeDesk.starter_gate: Callable[[Window, float], str] | None = None`**, an instance attribute in the
   `price_stale_s` style. It returns a reason, or "" to allow.
5. **`_starter(slug) -> bool`**: true when inventory is 0; with `rounds`, also true when up = down > 0 and nothing is
   pending in the window.
6. **`_risk_reason`**:
   - the starter clip is `starter_clip or clip`;
   - a rounds starter takes the `starter_pending` and `starter_clip` checks and is treated as bootstrap, so the
     imbalance check does not refuse it.

   With the defaults this is the same code.
7. **`_evaluate_side`**:
   - a rest's size is `starter_clip or clip` when `_starter`;
   - the starter is skipped with a `last_reason` of `starter_wait` (before `start + starter_delay_s`), `starter_late`
     (at or after `end - starter_stop_s`), or the gate's reason;
   - with `whole_contracts` the unit step is 1 instead of `min_trade_qty`.
8. **`place()`**: sets `bootstrap_order` and `bootstrap_side` when `_starter` (today, only when inventory is 0; the
   same with defaults).
9. **`_lock_step(now) -> list[Decision]`**: new; called by `evaluate()` right after `advance()`, only when
   `lock_s > 0` or `stop_s > 0`, and before the sigma and blocked loop (locks need no fair value). For each window
   that is not settled and is inside the lock or stop period (before `end - LOCK_MARGIN_S`):
   - checks: both books fresh (factor the book checks of `blocked()` into `_book_reason(window, now)`; `blocked()`
     keeps its exact result), nothing pending in the window, and `floor(unpaired + EPS) >= 1`;
   - price and size: the light side's best ask, required to be at most `lock_max_price`; size is
     `min(floor(unpaired), clip, shown - consumed)`;
   - the stop additionally needs a completion cost of at least `stop_pair_cost`;
   - placement: a `PracticeOrder(kind="take", lock=True, fair=price)` goes straight into `orders`, with
     `active_at = now + latency`, `decision_sequence = book.sequence` and the reason "lock" or "stop", and
     `lock_orders` is counted.

   `advance()` then fills or rejects it exactly like a take; an IOC remainder is dropped.
10. **`advance()`**: when `blocked()` returns cutoff, day_stop, bitcoin_stale or opening_price_missing, it calls
    `cancel(..., keep_locks=True)`, so lock orders survive. `cancel(now, window=None, reason=..., keep_locks=False)`
    defaults to today's behaviour. No lock order can exist with the defaults.
11. **`_fill`**: counters use the prefix `lock` when `order.lock`, so locks never inflate take fill rates.
12. **`forget(slug)`**: new; it drops a settled window's entries from `windows`, `inventory`, `closed`, `books`,
    `last_reason`, `bootstrap_*`, `window_venues` and `consumed`, and refuses (ValueError) when the window is not
    settled or still has orders. Only the arena calls it, and the arena never re-adds a settled slug: it keeps a
    bounded `settled_slugs` deque of 200.
13. **`LOCK_MARGIN_S = 20.0`**, with a comment naming the live constant. A test asserts it equals
    `speeddesk_live_model.LOCK_MARGIN_S`. That file is not edited.
14. **Optional, only if KXBTC15M ever shows `maker_coefficient > 0`**: `rest_fee_edge: bool = False` reproduces the
    live after-fee maker check (`fair - unit_reserve(price) >= make_edge`). With a maker fee of 0, live and practice
    agree by construction.

## 6. Feed design and latency proof

### 6.1 Producer hooks (speeddesk.py; the only code on the live loop)

```python
# SpeedRunner.__init__, after the live companion is set up (never fatal):
self.arena: Any = None
if settings.kalshi_arena_enabled and settings.speeddesk_kalshi_enabled:
    try:
        from .kalshi_arena import KalshiArena, arena_config
        self.arena = KalshiArena(arena_config(settings), self.live_snapshot, clock=self.clock.now)
    except Exception as exc:  # noqa: BLE001 - a practice town never stops the speed desk
        log.warning("kalshi_arena_not_started error=%s", type(exc).__name__)
# on_book, inside `if self.desk.on_book(book):` after self._live_call("on_book", book):
if self.arena is not None and book.window in self._live_slugs: self.arena.feed_book(book)
# on_trade, inside the existing gate, after self._live_call("on_trade", trade):
if self.arena is not None and trade.window in self._live_slugs: self.arena.feed_trade(trade)
# on_status, at the end (rare): only the gap facts, as a tuple
if self.arena is not None: self.arena.feed_gap(tuple(status.get("gap_windows", ())), bool(status.get("trade_stream")), status.get("coinbase") == "connected")
# run(): self.arena.start(self.stop) before the loop; finally: self.arena.stop()  (sets an event; never joins)
```

- `on_tick` and `on_windows` get no new code.
- `Book` and `Trade` are frozen and passed by reference.
- Windows are read from the snapshot, where they are already copies. The arena copies them again (`replace`)
  before `add_window` mutates `start_price`.
- `feed_*` is `if closed or len(q) >= QUEUE_MAX: dropped += 1; return` then `q.append(item)`, wrapped in
  try/except so it can never raise.
- There is no Lock or Condition, so the producer can never wait on the consumer.
- The live callbacks run first, so the arena always sees an event after the live desk has it.

### 6.2 Consumer (`KalshiArena._loop`, daemon thread "kalshi-arena")

Each pass, about every `POLL_S = 0.1` s:
1. `snap = snapshot(); now = clock()`.
2. Windows: KXBTC15M windows from `snap.windows` with `end > now` that are not yet known and not settled are added
   to each resident whose `born <= window.start` (a newborn joins the next window). If a known window's fee terms
   change, cancel and clear its books, mirroring `SpeedRunner.on_windows`.
3. Bitcoin: `tape.feed(snap.bitcoin_price, snap.bitcoin_at, snap.sigma)`. One `FedTape` is shared by every desk
   (`desk.tape = tape`).
4. Events: drain up to `DRAIN_MAX = 512` in arrival order, one slice per event:
   - book: `desk.on_book(b)`, then `desk.advance(now)`, for each resident;
   - trade: `desk.on_trade(t, now)`; a trade older than 3 s at processing is rejected by the model and counted as `late`;
   - gap: the runner's rule (cancel the window's orders and drop its books; a stream or Coinbase loss cancels all).
5. Settlements: each known window in `snap.outcomes` settles for every resident in one slice per resident, then the
   rules in section 7 run.
6. Voids: a window with no outcome `VOID_AFTER_S = 7200` after its end is void for all.
7. Evaluate: each resident at most every `EVAL_S = 0.25` s (live's `IDLE_STEP_S`), one resident per slice, with
   `desk.evaluate(now, makers_enabled=bool(snap.maker_windows), maker_windows=set(snap.maker_windows))`.
8. Housekeeping: save every `SAVE_EVERY_S = 60` s and after evictions, births or flags (coalesced to at most once
   every 10 s). Log `kalshi_arena_status` every `STATUS_EVERY_S = 300` s.

The `_yield()` scheduler runs between units of work:

```text
if perf_counter() - slice_started >= SLICE_S (0.0003):
    record the slice duration in a bounded reservoir of 2,048
    sleep(REST_S = 0.002)
    slice_started = perf_counter()
```

Duty is at most about 13 % by construction; the expected load is about 1 %:

| Work | Cost |
|---|---|
| 12 evaluations at 4 Hz | about 5 ms/s |
| About 50 books/s x 0.05 ms for 12 desks | about 2.5 ms/s |
| `judge` | 11 x 0.6 ms every 15 minutes |

If the work exceeds the budget, evaluations simply come less often and `lag_s` is reported: the arena slows itself,
never the live loop.

Failure handling:
- Every pass is wrapped in try/except. Each failure logs `kalshi_arena_step_failed error=<Type>` and counts in
  `errors`.
- Five consecutive failures halt the town: `problem` is set, a final save is made, `feed.closed = True` (every later
  put is a counted drop), the line `kalshi_arena_halted error=<Type>` is logged and the thread exits.
- Construction failure leaves `self.arena = None`.

### 6.3 Why snapshot plus queue rather than a queue of everything

Ticks arrive many times a second, and the fair value only needs the newest price. The runner already caches the
sigma the live desk uses, so polling the snapshot costs the live loop nothing and makes the arena use the same
sigma. Books and trades are queued because order matters: maker fills (trade versus `active_at` and the queue ahead)
and take or lock rechecks ("the first book after the latency") must see the same sequence as the runner.

### 6.4 Proof (tests in `tests/test_kalshi_arena_feed.py`; numbers recorded in the WORKLOG)

- `on_tick` gets no arena code: a spy arena records zero calls during 10,000 ticks.
- Producer cost: `SpeedRunner` (FakeClock, LocalFeeds, `prepare_kalshi`) takes 20,000 `on_book` and `on_trade` calls
  with the arena on and off. The extra cost must be a mean under 0.02 ms and a p99 under 0.5 ms (measured 0.14 us per
  put here).
- A slow arena never blocks: the consumer is parked on an Event. The producer stays under the same bound, the queue
  stays at `QUEUE_MAX`, `dropped` equals calls minus `QUEUE_MAX` exactly, `runner.step()` and a spy live companion
  keep receiving calls, and after release the arena resumes and the panel shows the drops.
- A crashed arena never crashes the live desk: `step` raises five times, so the thread halts with `problem` set and
  later puts are counted no-ops. No exception reaches `SpeedRunner`, the live spy still gets `on_book` and `on_trade`,
  and a constructor that raises leaves `runner.arena is None` while the runner trades on.
- Slice bound: a synthetic stream (12 residents; books at 50/s; trades at 3/s; ticks; two windows with settlement)
  runs through `step()`. The recorded slices must show a median under 0.2 ms and a p99 under 0.5 ms (measured here
  about 0.1 / 0.2 ms), and every slice is followed by a rest.
- Opt-in lateness test (`NIGHTCRAWLER_PERF_TESTS=1`): a main thread doing 1 ms sleeps while the arena worker runs the
  synthetic load. Its p99 lateness, compared with a run without the worker, must rise by less than 0.5 ms. It is off
  by default because CI timing is noisy; the result from one local run goes in the WORKLOG.
- Shutdown: setting the stop event makes the arena exit within 1 s, and `SpeedRunner.close()` never waits on it.

### 6.5 Production telemetry

The status line and the panel report:
- the queue depth, puts, `dropped` and `late`;
- the slice p50, p99 and max;
- duty %, `lag_s` and errors.

`KALSHI_ARENA_ENABLED=false` removes the arena entirely; with it the producer hooks are `self.arena is None` checks.

### 6.6 Fallback if production shows contention

Move the consumer into a process: `subprocess.Popen([sys.executable, "-I", "-m", "nightcrawler.kalshi_arena",
"--worker"], env=<PATH, DATA_DIR, PYTHONPATH only>, stdin=PIPE)`. A scrubbed environment means the worker never sees
`KALSHI_*` keys. The producer writes compact lines to the pipe with non-blocking writes, and a full pipe is a counted
drop. Not built now: it costs about 25 MB of RAM and the cost of managing the child process. The thread design is
the first step.

## 7. Town rules and constants (kalshi_arena.py)

```text
STATE_VERSION = 1
LABEL = "Practice (pretend money)"
START_CASH = 50.0
RENT_USD = 0.20
BROKE_USD = 10.0
POPULATION = 12 (the control is one of them)
RECORD_KEEP = 960 windows (10 days)
GRAVE_KEEP = 40
EVENTS_KEEP = 60
CANDIDATE_WINDOWS = 100
CANDIDATE_T = 2.0
MUTATE = 0.12
NEW_VALUE_P = 0.1
QUEUE_MAX = 8192
SEED = 20261013
```

- **Equity** = `START_CASH + realized window P&L - rent paid`. Every check runs right after a window settles; an
  open window is excluded, since a window lasts 15 minutes.
- **BROKE_USD default, $10.** Below that a resident cannot fund one window at the live $10 budget (arena.py's meaning
  of "broke"). The alternative is $40, the real desk's $10 total stop. It churns zero-edge residents within about a
  day of noise (per-window sd is about $1, about 90 windows a day), so selection would run on luck before
  `deskguard` can judge.
- **Window P&L** = `desk.settle(...).pnl_usd`. A resident's record holds a float when it traded (any shares) and None
  when it was alive but did not trade (P&L 0).
- **Rent:** the first settled window whose end is on a new UTC day charges `RENT_USD` to every resident, control
  included; there is no rent on the first day. A non-control resident whose equity is below the rent is evicted with
  "could not pay the rent".
- **Evictions (never the control), in this order, after each settlement:**
  1. rent failure;
  2. equity below `BROKE_USD`: "went broke";
  3. `judge(traded pnls)` returns `losing` (95 % upper bound below 0 from 30 windows, or the 99 % early stop from
     10): "losing: <verdict reason, clipped>".

  The graveyard row holds:
  - who: `id`, `name`, `gen`, `parent`, `born`, `died`, `days`;
  - record: `windows`, `traded`, `pnl_usd`, `equity_usd`, `rent_paid`;
  - outcome: `why`, `verdict`, a compact `genes`, `vs_control: {n, mean_usd, t}`.

  Newest first, at most `GRAVE_KEEP`. An evicted resident's open window is discarded with its desk.
- **Births:** every empty home goes, at once, to a child of a parent drawn from the top half by equity (control
  included), the richer more often (`rng.random() ** 2`). `gen = parent.gen + 1`. It joins the next window. A
  population setting that falls on restart evicts the poorest non-control residents ("the town shrank").
- **First town:** the control, plus `(population - 1) // 2` children of the control (local search), plus random
  residents for the rest (global search). The RNG is seeded with `SEED + next_id`, as in arena.py.
- **Verdict:** each settlement runs `deskguard.judge` on a resident's traded windows (the newest `RECORD_KEEP`; the
  reason says "of the last N"). It stores `{word, phrase, reason}`. The control is judged too: when it reads
  `losing`, the panel says "the live rules lose in practice" and a line is logged once per change. Nothing else
  happens.
- **Paired statistics** (every non-control resident): over every window settled while it was alive,
  `d = (pnl or 0) - (control pnl or 0)`. A skipped losing window is part of an edge. Running `n`, `sum` and `sumsq`
  give `t = mean / (sd / sqrt(n))`.
- **Candidate:**
  - Condition: verdict `winning` (judge already needs 100 or more draws and 3 or more losses, passed at 99 % with the
    stress test), plus a paired `n >= 100` and `t >= 2`.
  - When it holds for the first time:
    - set `candidate = {at, n, t, mean_usd, verdict_reason, adopt: adoptable(genes)}`;
    - start `since_flag` paired statistics;
    - log `kalshi_arena_candidate`;
    - record an event.
  - `candidate_now` follows the condition afterwards; the historical flag stays.
  - The card says "a lead for a pre-registered test; not proof; real money changes only on the owner's word".
- **Control rule change:** at startup `rule_id(live_genes(settings))` is compared with the saved one. On a change,
  the control's record, every paired statistic and every `since_flag` restart. The line `kalshi_arena_control_changed`
  is logged with old and new genes. Challengers keep their own records, because their genes did not change.
- **Void:** a window active at the last save before a restart, or with no outcome after `VOID_AFTER_S`, gives no
  record and no P&L to anyone and counts in `town.void_windows`.
- **Equal market for all:** each resident fills independently against the same prints. There is no competition
  between residents, nor with the real desk. The spec says so.

## 8. Persistence

The arena writes two files under `DATA_DIR/kalshi_arena/`.

`state.json` (atomic: write a `.tmp` sibling, then `os.replace`; no fsync, so the arena never competes with the
ledgers' durable writes; at most about 150 KB):

```json
{"version": 1, "label": "Practice (pretend money)", "saved_at": 0, "started_at": 0,
 "settings": {"population": 12, "rent_usd": 0.2, "broke_usd": 10.0, "start_cash": 50.0},
 "control_rule": "a1b2c3d4e5f6", "next_id": 37, "seq": 412, "rent_day": "2026-10-13",
 "active_windows": ["KXBTC15M-..."],
 "residents": [{"id": "1", "name": "Live", "control": true, "gen": 1, "parent": null, "born": 0,
   "genes": {}, "equity_usd": 50.0, "rent_paid": 0.0, "first_seq": 0, "pnl": [0.31, null, -1.2],
   "paired": {"n": 0, "sum": 0.0, "sumsq": 0.0}, "verdict": {"word": "learning", "reason": ""},
   "candidate": null, "since_flag": null}],
 "grave": [], "events": [],
 "town": {"born": 0, "evicted": 0, "windows": 0, "void_windows": 0, "rent_paid": 0.0, "candidates": 0},
 "feed": {"put": 0, "dropped": 0, "late": 0, "errors": 0}, "problem": null}
```

- `pnl` is aligned to the global `seq`: one number per settled, non-void window, rounded to 4 decimals, with at most
  `RECORD_KEEP` kept.
- Restore checks `version` and types per field. A bad or unreadable file is renamed `state.json.bad-<epoch>`, logged
  `kalshi_arena_state_reset`, and the town starts fresh.
- Residents' desks are rebuilt fresh from their genes; `active_windows` become void (2.10).

`panel.json` (at most about 16 KB, written right after the state): the compact page view in section 10, so
`/api/page` never parses the large file.

## 9. Settings (config.py)

All four are validated by the generic lo/hi check:

```python
kalshi_arena_enabled: bool = _f(True, "bool", "The Kalshi arena: a PRACTICE town of Kalshi Bitcoin 15-minute desks with their own genes; never places a real order or changes a live setting")
kalshi_arena_population: int = _f(12, "count", "Kalshi arena: residents, including the control that runs the live rules", lo=2, hi=24)
kalshi_arena_rent_usd: float = _f(0.20, "usd", "Kalshi arena: practice rent each resident pays per UTC day (about the whole Railway bill each)", lo=0, hi=5)
kalshi_arena_broke_usd: float = _f(10.0, "usd", "Kalshi arena: a resident whose practice money falls under this is evicted", lo=0, hi=49)
```

- Add an `int` check for `kalshi_arena_population`, like weatherwatch's counts.
- The arena runs only when `speeddesk_enabled`, `speeddesk_kalshi_enabled` and `kalshi_arena_enabled` are all true.
- Defaults are the module constants: `kalshi_arena.RENT_USD`, `BROKE_USD` and `POPULATION`, kept equal by a test.
- `.env.example` gets the block below, after the `SPEEDDESK_KALSHI_*` block. `test_env_example_lists_every_setting`
  then passes.

```text
# The Kalshi arena (PRACTICE only; owner 2026-10-13 "make money or die"): 12 practice Kalshi Bitcoin 15-minute
# desks with their own genes, one always on the live rules (the control). Each pays rent, is evicted when broke
# or losing (deskguard), and the richest have children. A candidate is shown to the owner, never given money.
KALSHI_ARENA_ENABLED=true
KALSHI_ARENA_POPULATION=12
KALSHI_ARENA_RENT_USD=0.20
KALSHI_ARENA_BROKE_USD=10
```

Docs:
- `docs/SPEEDDESK_SPEC.md`, new section "12. Kalshi arena (practice; owner, 2026-10-13)": the purpose, the gene
  table, the rules and constants, the feed and latency design with the measured numbers, the void rule, the
  candidate wording, and items 2-7 from section 2.
- `docs/WORKLOG.md`, a new top entry: `## 2026-10-13 HH:MM UTC, Claude, branch claude/kalshi-arena`, with
  Changed / Verified (suite, ruff, mypy, the perf numbers) / Not verified (production lateness, until the
  `kalshi_arena_status` lines are read after deploy) / "Real money touched? no: practice town; the speed desk's loop
  gains three bounded appends; no live setting or order path changed" / Next step.

## 10. Dashboard key

In pagestate.py, after `money["speeddesk"]`:

```python
money["kalshi_arena"] = kalshi_arena(settings, now)  # Kalshi practice town (never summed)
```

`kalshi_arena(settings, now)`:
- returns None when disabled;
- otherwise calls `kalshi_arena.panel_state(settings.data_dir, now)` inside try/except for
  `(KeyError, TypeError, ValueError, AttributeError, OSError, ImportError)`; on failure it logs
  `kalshi_arena_panel_failed error=<Type>` and returns None;
- whitelists fields; redacts, then clips every text (`_Text`, `_clip`);
- adds `label = PRETEND_LABEL` and `stale = as_of is None or now - as_of > 180`.

The panel keeps lists short:

```text
{label, as_of, stale, problem,
 population, rent_usd, broke_usd, start_cash,
 control: {name, equity_usd, windows, traded, pnl_usd, verdict, phrase, genes_line},
 residents: [{id, name, gen, parent, days, equity_usd, profit_usd, traded, wins, losses,
              verdict, phrase, style, vs_control: {n, mean_usd, t}, candidate, candidate_now}] (<= population),
 candidates: [{name, at, n, t, mean_usd, since_flag: {n, mean_usd, t}, adopt: {settings, needs_code}, note}] (<= 5),
 grave: [...] (<= 5),
 events: [{ts, who, text, tone, kind: born|evicted|candidate|rent|control}] (<= 24),
 town: {born, evicted, windows, void_windows, rent_paid, candidates},
 feed: {queue, dropped, late, slice_p99_ms, slice_max_ms, duty_pct, lag_s, errors}}
```

Add one line to the schema docstring. No UI file changes and no `plain` line (the town UI's owner can read the key
later).

## 11. Logging

One short line per change (`logging.getLogger("nightcrawler.kalshi_arena")`; no exception text, as elsewhere):

```text
kalshi_arena_started population=12 rent_usd=0.20 broke_usd=10.00 control_rule=<id> (practice only)
kalshi_arena_born resident=Ada-14 parent=Kai-7 gen=3 style="edge 0.035, starter 4, cap 0.98, lock 240s@0.97, rounds"
kalshi_arena_evicted resident=Bo-9 why=losing windows=41 pnl_usd=-6.12 equity_usd=43.28 days=0.6
kalshi_arena_candidate resident=Cy-21 windows=118 paired_n=160 paired_t=2.31 vs_control_usd=+0.042 (practice only; nothing changed live)
kalshi_arena_control verdict=losing reason="..." (practice; live unchanged)
kalshi_arena_control_changed old=<id> new=<id>
kalshi_arena_status residents=12 windows=412 void=3 queue=0 dropped=0 late=0 slice_p99_ms=0.19 slice_max_ms=1.1 duty_pct=0.9 lag_s=0.0 errors=0
kalshi_arena_not_started | kalshi_arena_step_failed | kalshi_arena_halted | kalshi_arena_state_reset  error=<Type>
```

The status line is every 5 minutes; logging's handler lock is contended rarely.

## 12. Tests

**`tests/test_speeddesk_model_genes.py`** (the model):
1. Golden equivalence. A scripted run covers windows, ticks, books, trades, settlements, starter, balancing,
   reprice, take, cutoff, day stop and feed-gap cancel. Run through `PracticeDesk(SpeedConfig())`, it reproduces
   `tests/fixtures/speeddesk_model_golden.json` (decisions and `to_state`) generated from the unmodified model.
   An explicit-defaults config gives the same result.
2. `to_state()` omits new fields at their defaults. An old saved state (fixture) loads. `SpeedConfig(**old_config)`
   works, and so does `SpeedConfig(**new_config)`.
3. `starter_clip`: the first buy uses it; balancing uses `clip`.
4. `starter_delay_s` and `starter_stop_s` block starters only.
5. `rounds`: after a complete pair, one starter-size buy is allowed, then balancing only. Off keeps today's
   imbalance-limited growth.
6. `whole_contracts`: every placed size is an integer.
7. Lock:
   - completes the unpaired side at the ask, up to `lock_max_price`, IOC;
   - bypasses pair cap, budgets, edge, cutoff and day stop;
   - needs fresh books;
   - never within 20 s of the close, never with nothing unpaired or something pending;
   - survives `advance()` in cutoff;
   - counts as `lock_*`.
8. Stop: fires at a completion cost of at least T inside its period, and not below T; off by default.
9. `starter_gate` blocks starters only; None means today's behaviour.
10. `forget()` drops only settled windows and refuses open ones.
11. `LOCK_MARGIN_S == speeddesk_live_model.LOCK_MARGIN_S`.
12. The live twin config sits entirely on defaults, and the existing `test_speeddesk_live*.py` pass unchanged.

**`tests/test_kalshi_arena.py`** (the town):

13. The first town has the control plus 11 residents; the control's genes equal the `LiveLimits` clamps of a
    Settings with custom live values (clip, lock_s, lock_max, pair_cap, max_imbalance, make_edge, take_edge).
14. Random and child genes stay inside ranges and grids over 2,000 draws. Children lie near their parent; booleans
    flip sometimes.
15. Each gene changes exactly its intended `SpeedConfig` field (a table-driven test).
16. Window lifecycle: settlement records traded or untraded P&L, desks forget the window, and a newborn joins the
    next window only.
17. Rent: the first settlement of a new UTC day charges everyone, the control included; a resident that cannot pay
    is evicted; totals count the rent.
18. A resident under the broke line is evicted. The graveyard is bounded and newest first.
19. Ten clearly losing windows give `losing` (early stop), so the resident is evicted with the verdict's reason;
    the control is never evicted.
20. Births pick top-half parents (control eligible) and log `kalshi_arena_born`.
21. The candidate is flagged once when winning, with paired n >= 100 and t >= 2. It is not flagged with t < 2,
    n < 100 or a non-winning verdict; the control never is. `since_flag` grows afterwards.
22. A control rule change resets the control's record and every paired statistic, and logs it.
23. Restart:
    - state is restored;
    - an active window turns void for all;
    - a bad file moves aside and the town starts fresh;
    - `state.json` and `panel.json` are written atomically (the `.tmp` sibling, then replace);
    - 30 simulated days with churn keep `state.json` at 192 KB or less and `panel.json` at 16 KB or less.
24. Practice only:
    - the module's AST imports nothing from `speeddesk_kalshi_client`, `speeddesk_live`, `requests`, `websockets`
      or `polymarket_us`;
    - it does not mention `create_order` or `KalshiClient`;
    - no attribute of a running `KalshiArena` (walking `vars()` recursively one level) is a `Settings` or `Secret`;
    - `ArenaConfig` fields hold numbers, paths and dicts only.
25. Page:
    - `money["kalshi_arena"]` carries the practice label and is None when disabled or unreadable;
    - the page reads `panel.json` only;
    - `town_ledger` income is identical with and without the arena.
26. Logs: evicted, born and candidate lines appear (caplog).

**`tests/test_kalshi_arena_feed.py`** (latency and isolation): the tests in 6.4 (no tick hook, producer cost, slow
arena, crashed arena, constructor failure, slice bound, shutdown, opt-in lateness), plus one more. The arena never
mutates the runner's windows or books: snapshot windows compare equal before and after a settlement pass.

**`tests/test_config.py`**: the defaults, bounds and int check for the four settings, and that the defaults equal
the module constants.

## 13. Build order and verification

1. `git switch -c claude/kalshi-arena origin/claude/nightcrawler-memecoin-bot-Gwnb1S`. Write the golden script and
   generate `tests/fixtures/speeddesk_model_golden.json` with the UNMODIFIED model. Commit it:
   `test: pin today's practice speed desk behaviour`.
2. Model fields and behaviour, plus `tests/test_speeddesk_model_genes.py`. Run
   `python -m pytest -q tests/test_speeddesk_*.py`. Commit:
   `feat: opt-in arena fields for the practice speed desk (defaults unchanged)`.
3. `kalshi_arena.py` with `tests/test_kalshi_arena.py`. Commit: `feat: Kalshi arena, a practice town that must pay rent`.
4. Settings, the runner hook, the page key and `tests/test_kalshi_arena_feed.py`. Commit:
   `feat: feed the Kalshi arena from the speed desk without blocking (touches real money: event-loop hook only)`.
5. Docs: `.env.example`, SPEEDDESK_SPEC section 12 and the WORKLOG entry. Run the local opt-in perf test and record
   its numbers. Commit: `docs: Kalshi arena`.
6. Verify:
   - `python -m pytest -q` (the full suite);
   - `mypy src/nightcrawler`;
   - `git diff --name-only origin/claude/nightcrawler-memecoin-bot-Gwnb1S -- '*.py' | xargs -r ruff check`;
   - scan the diff for secret-looking strings.

   Every commit ends with the session's attribution lines. Do not push.

## 14. Questions for the owner (short; none block the build)

- The Kalshi account size: is it $25 (ACCOUNTS.md) or $50 (the brief)? `START_CASH` is 50 as asked.
- The broke line: $10 (cannot fund one window; the default) or $40 (where the real desk's total stop halts it)?
- The protective stop: "complete when the cost to complete rises to T" (the plan) or "complete at any cost up to T"?
- Should a candidate's forward check, its next 200 windows after the flag, be shown as its own pass or fail line?
  This plan only displays the statistics.


---
## result 1 

The Kalshi arena is built and committed locally on `claude/kalshi-arena` (not pushed). The final full run passed: 4,779 passed, 13 skipped. The live loop's extra cost is one queue append per Kalshi book or print, about 0.13 µs.

- **Worktree:** `/home/user/Claude/.claude/worktrees/wf_eb0dd718-1cf-2`
- **Branch:** `claude/kalshi-arena`, cut from `origin/claude/nightcrawler-memecoin-bot-Gwnb1S` at 64f9322 (PR #36's docs merge on top of b539aed).
- **Head commit:** e313b83deeaede33e733069dc5128343c436e971

**Commits**
- c5d3927 test: pin today's practice speed desk behaviour (golden fixture from the unmodified model)
- 8c31eed feat: opt-in arena fields for the practice speed desk (defaults unchanged)
- 8597615 feat: Kalshi arena, a practice town that must pay rent (includes the four settings and `.env.example`)
- 28f5019 feat: feed the Kalshi arena from the speed desk without blocking (touches real money: event-loop hook only)
- a20958a fix: start receipts keep today's config keys; births test independent of log setup
- e313b83 docs: Kalshi arena

**Files changed** (19 files, +3,374 / -26)
- New: `src/nightcrawler/kalshi_arena.py`, `tests/test_kalshi_arena.py`, `tests/test_kalshi_arena_feed.py`, `tests/test_kalshi_arena_page.py`, `tests/test_speeddesk_model_genes.py`, `tests/speeddesk_golden.py`, `tests/kalshi_arena_world.py`, `tests/fixtures/speeddesk_model_golden.json`
- Modified: `src/nightcrawler/speeddesk_model.py`, `speeddesk.py`, `speeddesk_coins.py` (start receipt only), `config.py`, `pagestate.py`, `.env.example`, `docs/SPEEDDESK_SPEC.md` (new section 12), `docs/WORKLOG.md`, `docs/COORDINATION.md`, `tests/test_config.py`, `tests/fixtures/README.md`
- Not touched: `speeddesk_live*.py`, `deskguard.py`, `engine.py`, `arena.py`, and all UI files.

**Tests**
- Base branch: 4,708 passed, 12 skipped. This branch: 4,779 passed, 13 skipped; the extra skip is the opt-in wall-clock test (`NIGHTCRAWLER_PERF_TESTS=1`).
- mypy on `src/` is clean, ruff is clean on every changed Python file, and a secret scan of the diff found nothing.

**Measured live-loop overhead** (Python 3.13, shared 4-core machine at load average 8–10)
- **Per put:** about 0.13 µs.
- **Book plus print through `SpeedRunner`:** about 21 µs with or without the arena; the difference was -0.3 µs mean and +3 µs p99, inside the noise. The test bounds are under 0.02 ms mean and under 0.5 ms p99.
- **Arena work slices (CPU time):** 12 residents, about 60 books and 3 prints a second, with a settled window. Median 0.21 ms, p99 0.30 ms, p99.9 0.49 ms, about 0.5 % of one core. Three slices in 47,000 reached a few ms; they come from memory growth, not arena logic.
- **Opt-in wall-clock test:** a loop that sleeps 1 ms at a time, with the arena running and parked in alternate half-second blocks. The p99 lateness rose +0.07, -0.04 and +0.20 ms over three runs against a 0.5 ms bound; the median stayed at about 0.07 ms.
- **Isolation tests:**
  - A parked arena drops exactly the overflow and the live desk keeps getting its calls.
  - A crashing arena halts itself after 5 errors and the live desk trades on.
  - A failing constructor leaves `runner.arena = None`.
  - `close()` never waits for the arena thread.

**Where I changed the plan**
- **Slice length:** 0.2 ms, not 0.3 ms. The median therefore sits at about 0.21 ms by design, so the test checks median under 0.3 ms and p99 under 0.5 ms, measured in CPU time so a busy shared machine cannot fail it.
- **Lateness test:** blocks are interleaved. Running the baseline first and the arena second showed rises up to 0.58 ms, which was machine drift; the baseline alone swung 0.28–0.57 ms between runs.
- **Smaller slices:** residents decide a share per pass instead of all twelve at once, saves are written row by row, the panel is built in slices, and the telemetry sorts its reservoir once.
- **Bug found and fixed:** books and prints drained during a pass could be stamped later than the pass's start time, so they looked stale or "from the future". The clock now refreshes per drained event.
- **Lock and stop:** a resting balancing bid in the window is cancelled before the lock or stop fires. Otherwise a resting bid would block the stop forever.
- **Void windows:** `forget(void=True)` drops a window that never settled. Any window that started before the arena started is void, which also covers windows that appeared after the last save.
- **Page:** the function is named `kalshi_arena_town`. A missing `panel.json` returns None quietly, so the page does not log a warning every few seconds before the first save.
- **Panel size:** graveyard rows on the panel leave out the full gene table, which keeps `panel.json` under 16 KB with five candidates.
- **Receipts:** both start receipts now write only non-default config fields, so their contents are exactly as before.
- **Commit order:** the four settings went into the module commit because `arena_config` reads them.

**Left undone**
- Not pushed, as instructed.
- **Production overhead is unproven** until the `kalshi_arena_status` lines are read after deploy. The subprocess fallback is not built, and how the arena's memory use affects garbage-collection pauses in production has not been measured.
- **Owner questions:**
  - Is the account $25 (what `docs/ACCOUNTS.md` records) or $50? Each resident starts with $50 as asked; I could not re-read the balance from here.
  - Is the broke line $10 or $40?
  - The stop is coded as a stop-loss: complete the pair once completing would cost T or more. Is that what was meant?
  - Should a candidate get its own forward-check pass/fail line?
- The town UI shows nothing yet; that is Codex's lane. The page-data shape is described for Codex in `docs/COORDINATION.md`.


---
## result 2 

No blockers. Nothing in this change can place a real order, touch a key or client, or change a live setting, and the practice model's new fields leave the twin and every other practice desk exactly as before. The one major problem is that a slow or hung arena can stall the live loop with nothing to catch it. Five minor findings follow it.

**What I verified as safe**
- **Live code untouched:** `speeddesk_live*.py`, `deskguard.py`, `engine.py` and `arena.py` have no changes (diff --stat against 64f9322).
- **No keys or orders:** `kalshi_arena.py` imports only `deskguard`, `speeddesk_live_model.LiveLimits` and `speeddesk_model`. It holds no Secret, client or environment write. `adoptable()` only produces display text.
- **Hooks:** the hooks in `speeddesk.py:254`, `265` and `303` run after the live companion's own call.
  - `ArenaFeed.put` is wrapped in try/except, and a full or closed queue just counts a drop.
  - A constructor or start failure is caught and leaves `runner.arena = None`.
  - Arena exceptions are caught, and the arena halts itself after 5.
  - It reads only the immutable `LiveSnapshot` and makes its own copies of Window objects. Book and Trade are frozen.
  - It only reads the runner's shared stop event; its own stop sets a private event.
- **Defaults unchanged:**
  - The golden fixture regenerates identically from the base commit's model and from the branch's.
  - I ran a differential fuzz of the base model against the branch model at default config: 600 random runs, 0 mismatches.
    - It covered decisions, `to_state`, the `from_state` round trip, old-reads-new and new-reads-old state, and daily summaries.
    - It included the twin's direct `place()` path and 340 fills.
  - Start receipts and saved state leave out the new fields when they hold defaults.
  - The speeddesk, kalshi, page and config tests pass: 883 passed, 1 skipped. Ruff is clean.

**Findings**

1. **MAJOR. `kalshi_arena.py:586` (`_loop`), `speeddesk.py:190` and `625`: a hung or CPU-bound arena pass stalls the live loop, and nothing detects it.**
   - **Evidence:** I wrote a test, `test_a_hung_arena_pass_never_delays_the_live_loop`, and it fails.
     - Median lateness of a 1 ms sleep loop goes from 0.12 ms to 5.31 ms. That is Python's thread switch interval (5 ms), and it lasts for as long as the hang does.
     - The arena reports `errors=0` and `problem=None`.
     - A single long C call inside one pass (a 3M-element sort) gave the live loop p99 62 ms and max 98 ms, against a baseline p99 of 0.4 ms.
     - `HALT_AFTER` counts only exceptions, so a hang never trips it. The status line is written from inside `step()`, so a hang also silences it.
     - The builder's isolation tests cover only a parked arena (waiting with Python's lock released) and a crashing one, so "a slow arena never blocks" is unproven. Future `FILTERS` would run in this same thread.
   - **Fix:** the only real isolation is running the arena in its own process. Options:
     - The live loop does a non-blocking `os.write` of a compact record to a pipe and drops it on `EAGAIN`.
     - Or the child process reads the public feeds itself.
   - **Interim fix:**
     - Record a timestamp at the start of each pass.
     - `SpeedRunner.step` checks it; if a pass exceeds about 1 s, close the feed, set `arena = None` and log `kalshi_arena_hung`.
     - Add the CPU-bound test to the suite.

2. **MINOR. `speeddesk_model.py:129` and `936`, called from `speeddesk_live.py:430`: the twin's save got slightly slower, on the real-order path.**
   - **Evidence:**
     - `twin.to_state()` runs inside the live companion's durable checkpoint, which happens before the first network byte of a real order.
     - `config_state` rebuilds `fields(SpeedConfig)` and filters it on every call. It costs 8.72 µs where `asdict` cost 3.49 µs.
     - Measured in pairs, `to_state` is about 7.3 µs slower (about 1%). Behaviour is identical.
   - **Fix:** precompute the defaults once at import. Either cache `config_state` per frozen config with `lru_cache`, or compute it once in `PracticeDesk.__init__`.

3. **MINOR. `kalshi_arena.py:1098` and `1108` (`_load`), `255` (`speed_config`), `1136` and `_clean_row` (candidate rows): some corrupt state files are not moved aside, so the arena stays off or halts on every restart.**
   - **Evidence:**
     - Deeply nested JSON raises `RecursionError`, a gene `pair_cap` of 0 raises `ZeroDivisionError`, and `pair_cap=1e-320` raises `OverflowError`. None of these is in the caught list, so the constructor raises and the bad file stays in place.
     - NaN or inf inside a grave row or a candidate is restored without checks. Every later `_save` then raises `ValueError` (it writes with NaN disallowed), so the arena fails 6 of 6 passes and halts.
     - The live desk is unaffected in every case.
   - **Fix:**
     - Catch `Exception` around the JSON read and `_restore`, then call `_reset`.
     - Check grave, event and candidate rows on restore by re-dumping each with NaN disallowed, and drop bad rows.
     - Check `pair_cap > 0` before dividing.

4. **MINOR. `config.py:515–523` and `651`: a typo in a practice-only setting stops the whole engine, including the real-money Kalshi companion.**
   - **Evidence:** `Settings.from_env` raises `ConfigError` for each of these:
     - `KALSHI_ARENA_POPULATION=30` ("must be <= 24")
     - `KALSHI_ARENA_RENT_USD=0.2usd`
     - `KALSHI_ARENA_ENABLED=on?`
     - `KALSHI_ARENA_BROKE_USD=50`
     
     While the engine refuses to start, nothing can lock a half pair. The same file treats `OWNER_TZ` as cosmetic: it warns and never refuses to start.
   - **Fix:** on a bad arena value, log a warning and turn the arena off instead of raising.

5. **MINOR. `kalshi_arena.py:1075` and `1078` (`_save`): in an aged town, save slices run longer than the 0.2 ms slice and reach the 0.5 ms target.**
   - **Evidence:**
     - I aged a 12-resident town to full 960-window records, 40 graves and 5 candidates. Over 20 saves, the largest slice per save measured 0.466 ms median and 0.667 ms max (CPU time).
     - The slow pieces are dumping one 960-entry resident row (0.28 ms) and encoding and writing the 125–210 KB state file (0.35 ms).
     - The CPU-time slice test only runs a fresh town for 330 simulated seconds, so it never sees this.
   - **Fix:** keep the per-window record compact or pre-serialized and updated as it grows. Write the state file in chunks with a yield between them. Add an aged-town case to `test_work_slices_stay_short_and_each_ends_with_a_rest`.

6. **MINOR. `kalshi_arena.py:89` (`QUEUE_MAX = 8192`) and garbage collection: the arena lengthens full garbage-collection pauses for every thread in the process.**
   - **Evidence:**
     - A full `gc.collect()` measured 8.1–9.2 ms without the arena, 11.5–13.8 ms with a 3-window town, and 14.6–16.0 ms with a full queue.
     - A full queue keeps 8,192 Books alive, about 48,000 extra tracked objects.
     - The builder's own run saw 3 slices of a few ms in 47,000, put down to memory growth.
   - **Fix:**
     - Use a queue of about 1024: about 17 s of buffer at 60 books a second, and drops are already counted.
     - Keep only the latest book per window and side while the arena is behind.
     - Clear the queue if the thread is no longer alive.
     - Report garbage-collection pause times (via `gc.callbacks`) in `kalshi_arena_status`.

7. **MINOR (nit). `speeddesk.py:653–656` (`close`) and `649` (finally block in `run()`): the arena is stopped before live shutdown steps.**
   - **Evidence:** `arena.stop()` runs before `live.close()` in the same try block, and before the practice cancel and checkpoint. If it ever raised, those real-money shutdown steps would be skipped. `Event.set` practically cannot raise, so this is ordering hygiene only.
   - **Fix:** stop the arena after `live.close()`, or wrap `arena.stop()` in its own try.

**Evidence scripts** are in `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/`:
- `review_tests/test_arena_hang_review.py` (the failing hang test; run it with `PYTHONPATH` pointing at the worktree's `src`)
- `stall.py` (live-loop lateness under a spinning or hung arena)
- `fuzz_diff.py` and `fuzz_diff2.py` (base-against-branch model fuzz)
- `check_golden.py` (golden fixture against both models)
- `aged2.py` (aged-town save slices)
- `gcpause.py` (garbage-collection pauses)
- `corrupt.py` (corrupt state files)
- `cfg.py` (bad arena settings)
- `tostate.py` (twin save timing)


---
## result 3 

KALSHI ARENA ADVERSARIAL REVIEW: worktree /home/user/Claude/.claude/worktrees/wf_eb0dd718-1cf-2, branch claude/kalshi-arena, head e313b83. I only read the worktree; `git status` is still clean and I committed nothing.

Checks I re-ran:
- Full suite: 4,779 passed, 13 skipped (198 s), matching the build claim.
- The four arena and gene test files ran 4 times at once: no flakes.
- ruff and mypy are clean on the changed files.
- The town is deterministic: same output across two runs, and the same with slicing turned off.

Probe tests, read-only and outside the repo: /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/review/test_review_arena.py. Run them from the worktree with `python -m pytest -q -p no:cacheprovider -c pyproject.toml --rootdir . -s <that file>`. All 7 pass, and each pass shows the defect is there. The GC, determinism and throughput scripts are in the same folder.

No blockers. Nothing reaches a real order. A slow, crashed or failing arena cannot block or crash the live loop. I found no look-ahead and no double-booked settlement.

**MAJOR**

**1. The control does not run the live risk rules, so "ahead of the live rules" is measured against something that is not live.**
- Where: src/nightcrawler/speeddesk_model.py:456 (day stop), :506 (open budget); src/nightcrawler/kalshi_arena.py:244-249 (`fixed_config`).
- The arena copies the live numbers ($10 window, $20 open, $6 day) but not how live applies them (`LiveRiskBook.can_buy`, speeddesk_live_model.py:327-364):
  - Live's day stop counts money at risk: refuse when day loss + at-risk + cost ≥ $6. Practice stops only after a realized -$6.
  - Live's open budget counts only unpaired cost; a complete pair risks nothing. Practice counts gross spend.
  - Live has a $10 total stop. Practice has none.
  - Live resting bids expire after at most 30 s (`expiration_ts=min(end-lock_s, now+30)`, speeddesk_live.py:998) and lose queue place. Practice bids rest indefinitely, which flatters every resident's maker fills.
  - Live refuses a bid unless fair minus the rounded fee reserve is at least make_edge (speeddesk_live.py:949). This matters only if the series charges maker fees (0.0175×).
- Evidence (`test_probe_control_day_stop_and_open_budget_differ_from_the_live_risk_book`):
  - After a -$4 morning, live returns `day_stop` for a 5-lot at 0.45; the control rests the full 5.
  - With a complete $9.50 pair still unsettled and $10 open, live allows 5; the control gets 1, refused by `open_budget`.
  - SPEEDDESK_SPEC §12 says residents "share" these budgets with live, which is not accurate.
- Fix: add opt-in SpeedConfig fields whose defaults keep today's desk (the golden test still passes), and set them for every resident:
  - `day_stop_counts_risk`
  - `hedged_open_budget` (count max(0, spent − min(up, down)) plus non-lock reserves)
  - `total_stop_usd`
  - `rest_ttl_s=30` (cancel and re-place a resting bid after its TTL, re-reading the queue)
  - optionally `maker_edge_after_fee`

**2. The benchmark's identity ignores the shared live limits, so records and paired stats silently span a limit change.**
- Where: src/nightcrawler/kalshi_arena.py:554 (`self.control_rule = rule_id(config.control)`); `fixed` (window/open/day stop, take_edge, latency, clip) is never hashed.
- Evidence (`test_probe_rule_id_ignores_the_fixed_live_limits`): moving to $20 window, $40 open and $12 day stop gives the same `control_rule`. Paired n carries over (12) and the control's record carries over (12 windows).
- Effect: when the owner doubles the caps ("double tmr"), `deskguard.judge` evicts and flags on mixed-scale records. That breaks deskguard's "CURRENT rule only" contract. The paired t also mixes the two regimes.
- Fix: `self.control_rule = rule_id({**config.control, **config.fixed})`. Also store a regime id per resident, and on a change reset every resident's `pnl`/`paired`/`since_flag`, or judge only entries from the current regime.

**MINOR**

**3. `starter_stop_s` leaks: a starter that is already resting keeps going and fills inside the "no first buy" period.**
- Where: src/nightcrawler/speeddesk_model.py:769 (an unrepriced rest is kept) and :789 (the hold only blocks new orders).
- Evidence (`test_probe_starter_stop_lets_an_earlier_resting_starter_fill_inside_the_no_first_buy_period`): with starter_stop_s=600, a starter rested at END-610 is still resting at END-590 and fills 5 contracts at END-589.
- Fix: in `_evaluate_side`'s cancel loop, cancel the window's pending starter (`order.order_id == bootstrap_order.get(slug)` while `_starter` holds) once `_starter_hold(window, now)` returns a reason.
- Also: `starter_stop_s` values up to `close_s` do nothing, which covers 120-300 of its 0-600 range.

**4. Births favour untested newborns over residents that have traded.**
- Where: src/nightcrawler/kalshi_arena.py:985-990.
- A newborn sits at exactly $50 and has paid no rent, so in a town that is mostly losing (the likely case) it outranks everyone who traded.
- Evidence (`test_probe_untested_newborns_are_parents_when_the_town_loses`): a 0-window newborn ranks first and is drawn as parent in 12 of 30 draws.
- Effect: selection degrades into drift.
- Fix: rank parents by realized profit among residents with at least N traded windows (for example 20), falling back to the control.

**5. A restart voids the window that has not opened yet, and counts the current window as void twice.**
- Where: src/nightcrawler/kalshi_arena.py:1161-1162. Kalshi discovery lists the next window (max_close_ts = current + 1800), so it is in `active_windows` when the state is saved.
- Evidence (`test_probe_restart_voids_an_upcoming_window_that_never_started`): after a 60 s redeploy the not-yet-started window is voided, and `void_windows` rises by 2.
- Effect: every deploy loses two windows instead of one.
- Fix: on restore, skip only windows with `start < now` (`_windows` already voids windows that started before `started_at`), and do not add `active_windows` to the void count.

**6. Rent is charged once however many UTC days pass.**
- Where: src/nightcrawler/kalshi_arena.py:831-838.
- Evidence (`test_probe_rent_is_charged_once_for_a_three_day_gap`): four UTC days pass and only $0.20 is charged.
- Fix: charge `rent × (date(day) − date(rent_day)).days`, with a cap.

**7. Each resident keeps its own copy of the same trade-dedupe memory, which lengthens garbage collection.**
- Where: src/nightcrawler/speeddesk_model.py:710, which keeps 10,000 seen prints per desk, ×12 residents.
- Measured on Python 3.13.16: a full GC takes 8.9 ms with those memories empty and 15.4 ms with them at cap, so about +6.5 ms of global stall each time.
- Full GCs are rare: none fired in 114,000 arena events. The build had not measured this at all.
- Fix: dedupe prints once in `_drain`, and give each resident desk a small memory through a new attribute (default 10,000; arena sets about 256).

**8. Other per-desk tables grow until restart, and the day-stop counter resets on restart.**
- Where: speeddesk_model.py:624 and `forget()` at :868. `venue_filled_orders`, `filled_orders`, `traded_days`, `days` and `venue_days` are never pruned while the process runs.
- Live's day stop persists across restarts; every resident's resets.
- Fix: prune in `forget()` (keep today and yesterday), and restore day P&L from the arena state.

**9. state.json is replaced without fsync, yet it is the town's only record.**
- Where: src/nightcrawler/kalshi_arena.py:495-498.
- Effect: a torn file after power loss goes through `_reset` and the whole experiment restarts.
- Fix: write the temp file, `flush()`, `os.fsync()`, then `os.replace`. fsync releases Python's lock and runs about once a minute, on the arena thread only.

**10. The arena can reach the runner's secrets through the snapshot callable.**
- Where: src/nightcrawler/speeddesk.py:190 passes the bound method `self.live_snapshot`. Through `__self__` that reaches the whole SpeedRunner: `settings` (Kalshi key) and `live` (client).
- `test_a_running_town_holds_no_settings_or_secret` passes the `LiveSnapshot` class and skips callables, so it does not cover the production wiring.
- Fix: pass a tiny holder object the runner assigns the snapshot to, or a closure over that holder only, and test that wiring.

**11. The protective stop shares the `lock_max` cap with the lock.**
- Where: speeddesk_model.py, `_lock_step` (the ceil(ask) > lock_max_price check).
- Effect: with a cheap heavy side and a low `lock_max`, the stop can never fire. The spec's stop has no price cap.
- Fix: give the stop its own cap (0.99), or document the coupling. Separately, the owner's stop-loss reading of T is still unconfirmed.

**12. The default test suite never measures a running arena against the real SpeedRunner loop.**
- The default lateness and contention test is opt-in (`NIGHTCRAWLER_PERF_TESTS`). The always-on tests show the cost of one append and the CPU-time slices, not lock contention with the arena thread running.
- Fix: run the opt-in test in CI on a quiet runner, or add a bounded always-on variant that uses p99 against an interleaved baseline.

**Verified correct**
- Every gene maps to its practice field, and each switch changes behaviour (lock, stop and rounds observed in the simulated town).
- The fill model is the same strict PracticeDesk:
  - Takes and locks fill only on a book stamped after the latency, at the top level, immediate-or-cancel.
  - Resting bids fill only on sell prints after `active_at`.
  - A backlog makes fills more pessimistic, never optimistic.
- Default model behaviour is pinned by the golden test.
- Each settlement is booked once; `settled` plus `end <= now` stops re-adding.
- Rent and broke eviction work, and the control is never evicted.
- The paired-t formula is correct.
- A candidate needs `winning` (100 or more traded windows, from WIN_N), paired n ≥ 100 and t ≥ 2.
- Saves are atomic and bounded (tested at ≤192 KB state and ≤16 KB panel). Restore validates its input and moves a bad file aside.
- The arena's own throughput is about 2,000 events/s with slicing before the queue drops.


---
## result 4 

Review of `claude/kalshi-arena` at e313b83: 3 major and 4 minor findings, and nothing I'd call a blocker yet. Whether the first two become blockers depends on the real Kalshi delta rate in production, which the code never measures or logs. The worktree is unchanged; all my benchmarks and tests live in the scratchpad.

How I measured: Python 3.13.16 with the GIL, a shared 4-core machine at load 0.2–4. Arena-off and arena-on runs were interleaved, 3 repetitions of 40–45 s each. The live side was a real asyncio loop around `SpeedRunner`, with the companion swapped for a no-op stub. Events came from a separate process over a UNIX socket: 15 Coinbase ticks/s, 3 prints/s (2 `Trade` objects each), and N Kalshi deltas/s (2 books each, 25 levels a side, level tuples reused as `speeddesk_kalshi_ws` does). Latency is the time from the sender's stamp to the handler starting.

**Measurements**

- **Hook cost per call, arena thread idle:**
  - Guard plus `feed_book` plus `deque.append`: about 0.24 µs per call.
  - Over 60,000 interleaved calls, `on_book` changed by −0.39 µs and `on_trade` by +0.66 µs (both noise). `on_tick` runs no arena code at all.
- **Live loop with the arena thread running** (checkpoint off to isolate the arena; p99 wake latency, mean of 3 runs):

| Deltas/s (books/s) | Books p99, off → on | Ticks p99, off → on | Arena thread CPU | Arena queue and lag |
|---|---|---|---|---|
| 25 (50) | no change (2.2/3.2/2.6 vs 2.2/2.3/2.0 ms) | no change | 2.2–2.5 % of a core | none |
| 100 (200) | 1.39 → 1.57 ms (+0.18; runs ranged −0.06 to +0.55) | 1.61 → 1.67 ms | 6.4–7.0 % | none; p90 unchanged |
| 200 (400) | 1.48 → 2.08 ms (+0.60); p90 0.27 → 0.45 ms | 1.51 → 2.18 ms (+0.67) | 11.5–11.8 % | queue 700–1,180 after 40 s, lag 1.7–2.8 s and rising |

- **With the real checkpoint (fsync) running, 200 deltas/s:** the 50 ms step's maximum went from 59–78 ms to 86–125 ms. Arena slices interrupt the long checkpoint every 5 ms (Python's GIL switch interval).
- **Arena drain ceiling** (main thread only feeding):
  - At 100, 200 and 400 books/s it drained 104, 203 and 394 per second. At 400 the queue reached 489 and lag 1.2 s.
  - At 800 books/s it drained only 407 per second. The queue filled (8,192) in about 20 s, 1,736 events were dropped, lag reached 12.2 s, and fills fell from about 75 to 11.
  - Duty was only 10.6 % at saturation: the limit is the scheduler, not CPU. One 25-level book costs 215 µs for 12 residents, and 0.69 two-millisecond rests per book.
- **Memory:**
  - 24 MB after 4 simulated hours; 22.7 MB of that is 12 copies of the trade-id memory (10,000 ids per resident).
  - RSS grew 16–23 MB more while the queue was backlogged.
- **Garbage collection:**
  - A full collection rose from 8.4 to 17.5 ms because of those trade-id sets; the rest of the arena's state adds 0.1 ms.
  - Young collections: 1.5–3 a minute either way with reused levels. With freshly built levels (REST-style books), the live thread ran 240 young collections and 21 middle ones a minute, against 3 a minute without the arena.
- **Disk** (full records):
  - Each save writes state.json (116 KiB) and panel.json (12 KiB).
  - About 1.07 saves a minute, so about 137 KiB/min or 200 MB/day, with no fsync.
  - One save takes 3.5 ms of CPU, longest single unit 0.51 ms.
  - Restore at start takes 4.5 ms inside `SpeedRunner.__init__`.
- **Longest units holding the GIL:**
  - `judge` on 960 windows: 0.31–0.50 ms.
  - A mass eviction (11 evicted, 11 born): 1.9 ms.
  - Save: about 0.5 ms.
- **A CPU-bound arena** (its step spinning 50 ms without sleeping): live book wake latency went from p50 0.22 ms, p99 1.8 ms to p50 5.5 ms, p99 16.7 ms, max 106 ms. The town never halted.
- **The repo's opt-in timing test** passes here (p99 −0.086 ms), but it only exercised about 43 events/s of 1-level books at 0.72 % duty.
- **Context, not from this branch:** the live loop's own `on_tick` costs 1.6–1.7 ms median. `SpeedRunner._live_sigma` (speeddesk.py:408) recomputes `BitcoinTape.sigma` over 3,600 s on every accepted tick. That dwarfs the 0.24 µs hook and matters for the 10x work.

**Findings**

1. **[major] Throughput cliff: in a busy market the town goes stale and blind but keeps booking windows as normal.**
   - Where: kalshi_arena.py:93-94 (SLICE_S/REST_S), :616-623 (`_yield` sleeps 2 ms after every unit over 0.2 ms), :689-711 (`_drain`, one unit per event), :89-90; speeddesk_model.py:704-707 (prints older than 3 s are ignored).
   - Evidence: the ceiling is about 400 events/s whatever CPU is free, i.e. roughly 200 deltas/s.
     - With checkpoints on at 200 deltas/s: lag 3.3–5.8 s, 22–146 late prints, 0 resident orders and 0 fills.
     - Review test `test_dropped_books_and_prints_still_count_as_a_full_window` FAILS: 11 residents booked a window whose feed dropped 2,003 events.
     - `test_a_backlog_older_than_stale_s_silently_stops_the_town` FAILS: 1,200 of 1,200 prints arrived too late, 11 residents were still booked, 0 windows voided.
     - `test_one_rest_per_book_caps_the_town_near_400_books_a_second` FAILS: 0.69 rests per 25-level book.
   - Fix:
     - Coalesce books per (window, side) in the drain: keep the latest, and keep intermediate books only while a take or lock is pending in that window.
     - Pace by duty cycle (rest = k × measured slice) instead of a fixed 2 ms after every unit.
     - Void the window for every resident whenever drops grow or lag exceeds stale_s during it, and log it.
     - Write the status line every 60 s while lagging.

2. **[major] GIL contention breaks the 0.5 ms target at busy rates, and the required proof never measures contention.**
   - Where: speeddesk.py:190, :255, :266 (the town runs as a thread in the live process); tests/test_kalshi_arena_feed.py:157 (the arena thread is never started, so it only times the append); :394 (opt-in test: a 1 ms sleep loop rather than an asyncio socket loop, 1-level books, about 43 events/s).
   - Evidence: p99 rises 0.60 ms (books) and 0.67 ms (ticks) at 200 deltas/s, and p90 rises 0.18 ms. At 100 deltas/s the rise is about +0.18 ms; at 25 deltas/s there is none. The arena is on by default.
   - Fix:
     - Move the town to a subprocess. The live loop would `os.write` the raw Kalshi websocket frame bytes it already holds to a non-blocking pipe (drop and count on EAGAIN), plus small JSON lines for ticks, windows and outcomes. The subprocess re-parses with its own `MarketState`.
     - Until then, either default `KALSHI_ARENA_ENABLED` to off or auto-park the town above about 100 deltas/s, and log the measured delta rate.
     - Add an opt-in test with an asyncio socket loop at 200–400 books/s of 25-level books, asserting the p99 rise stays under 0.5 ms.

3. **[major] No CPU watchdog, so a CPU-hogging arena is not isolated from the live loop.**
   - Where: kalshi_arena.py:586-599 (it halts only after exceptions); :926-939 (future signal filters would run in the arena thread); tests/test_kalshi_arena_feed.py:187-199 (the "parked" test waits on an Event, which releases the GIL).
   - Evidence: with a spinning step, live p50 went from 0.22 to 5.5 ms, p99 from 1.8 to 16.7 ms, max 106 ms. The town stayed up.
   - Fix:
     - Time each pass with `time.thread_time`.
     - Halt and close the feed if a pass exceeds about 20 ms of CPU, or duty stays over 25 % for 10 s.
     - Add a spin-without-sleep test asserting the town halts and live latency recovers. The subprocess in finding 2 removes this class of problem entirely.

4. **[minor] The trade-id memory is duplicated 12 times: about 22 MB and +9 ms on every full garbage collection.**
   - Where: speeddesk_model.py:703-711, fed from kalshi_arena.py:705-706.
   - Evidence: tracemalloc shows speeddesk_model.py:708 at 12.0 MiB, :703 at 9.7 MB (120,000 strings) and :709 at 1 MB. A full collection goes from 8.4 to 17.5 ms.
   - Fix: dedupe each print once in the arena. Then give residents a small or disabled trade memory through an opt-in `SpeedConfig` field whose default of 10,000 keeps today's desk.

5. **[minor] The production telemetry cannot prove the live overhead after deploy.**
   - Where: kalshi_arena.py:616-628 and :997-1008. Slices are timed in wall time, so they include time the arena spent preempted. Recurring slice maxima of 3–9 ms sit near the 5 ms GIL switch interval. The status line comes only every 300 s, and the live side records no lag of its own.
   - Fix:
     - Time slices with `thread_time`.
     - Add live-loop percentiles to the `speeddesk_status` heartbeat (step lateness, tick receive to handler).
     - Log the arena status every 60 s while lag is over 1 s or drops grew.

6. **[minor] A mass eviction and birth runs as one 1.9 ms unit with no yield.**
   - Where: kalshi_arena.py:814-824 and :985-990.
   - Fix: call `_yield` after each `_evict` and each `_new_resident`.

7. **[minor] The final save after stop is not waited for, so it races teardown.**
   - Where: kalshi_arena.py:599-603; speeddesk.py:648-649 and :655-657.
   - Evidence: 2 benchmark runs failed temp-directory cleanup with "Directory not empty: .../kalshi_arena". The daemon thread wrote state.json after `runner.close()` had returned. In production, a final save takes 112 or more rows × 2 ms of rests (about 0.25 s), so interpreter exit can cut it off. The previous save stands, up to 60 s old.
   - Fix: do the final save without rests, or have `run()` join the arena thread for about 1 s after the live companion's shutdown finishes.

Everything is in /tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/:
- **Benchmarks** (in `bench/`): `b1_calls.py`, `b2_gil.py` with `sender.py`, `b4_memory.py`, `b5_gc_save.py`, `b5b.py`, `b6_throughput.py`, `b8_units.py`. Raw results are in `b2_results.txt`, `b3_results.txt` and `b7_results.txt`.
- **Failing review tests:** `review_tests/test_review_arena_load.py`. Run them from that folder with `PYTHONPATH=<worktree>/src:<worktree>/tests python -m pytest -q -s -p no:cacheprovider --rootdir=. test_review_arena_load.py`.


---
## result 5 

The Kalshi arena is fixed and committed locally on `claude/kalshi-arena` (not pushed). Every major finding reproduced before I fixed it, and each now has a regression test. The full suite passes: **4,813 passed, 13 skipped** (base 4,708 / 12). mypy is clean on `src/` and ruff on every changed file. A 300-run fuzz of the practice model against the base (×2 scripts) gives 0 mismatches at default settings, and no town processes are left running after the suite.

**Head commit:** `738349ecf01d1999d41b37c86da27e70f70035a2`. Four commits on top of e313b83:
- 05d07ad: practice-model fields
- e6ee4b9: the town in its own process, and voids
- ce2a6ee: settings leniency
- 738349e: docs

Worktree: `/home/user/Claude/.claude/worktrees/wf_eb0dd718-1cf-2`

**The main design change.** The town no longer runs as a thread inside the live desk. It is a separate Python process:
- It gets an empty environment, so no Kalshi key reaches it.
- It runs at the lowest CPU priority (the idle scheduling class plus nice 19), so it never takes a CPU from the live desk. It is first in line for the out-of-memory killer, has a 1 GiB memory limit, and the kernel kills it if a pass hangs for 120 s.
- The live loop appends each book or print to a bounded list. Once every 50 ms step it sends what arrived over a local socket and never waits; if the town is behind, the batch is dropped and counted.
- I first measured a pipe with a waiting reader: each write's p99 was 8 ms. That is why it is now a Unix socket and the town checks for data on its own timer instead of being woken.

**Major findings**
- **Hung or spinning town stalls the live loop (review 1 #1, review 3 #2 and #3):** fixed by the separate process. Tests run stand-ins that spin on every core, never read, or die. With a spinner on every core, the live loop's 1 ms sleeps wake as on time as with no town (median 0.076 → 0.073 ms, p90 0.125 → 0.133 ms); the old thread design pushed the median to 5.3 ms. A town that halts after 5 errors exits and the live desk is told nothing it has to act on.
- **Throughput cliff, and stale windows booked as normal (review 3 #1):** fixed. The old 2 ms rest per book is gone, a backlog keeps only the latest book unless a resident is waiting on a take, and 5,000 deep books drain in under 0.5 s of CPU. A window whose feed was dropped, or read more than 3 s late, is now void for every resident and logged. The reviewers' failing tests now fail the opposite way: the defects are gone.
- **The control did not use the live risk rules (review 2 #1):** fixed with new practice fields that are off by default. The day stop and open budget now count money at risk, resting bids expire after 30 s, and the edge must survive live's fee reserve. Over 400 random states, the practice desk's budget answers match the live risk book's own.
  - Not copied, on purpose: live's $10 lifetime stop. It halts the account until the owner resumes it, so a control that copied it would freeze and every comparison would be against a flat line.
- **Benchmark id ignored the shared limits (review 2 #2):** fixed. The shared limits have their own id; when they change (for example the owner doubling the budget), every resident's record and comparison restart. Money stays.

**Minor findings**
- Fixed: all of review 2 #3–#11, review 1 #2–#4 and #7, review 3 #4, #5 (in part) and #7:
  - a resting first buy is cancelled when its no-first-buy period starts;
  - only residents with 20+ traded windows can be parents;
  - a restart voids one window instead of two;
  - rent is charged for each missed day, at most 7;
  - a corrupt state file is moved aside, or only the bad row is dropped;
  - prints are de-duplicated once for the whole town;
  - per-desk day tables are pruned, and the day stop survives a restart;
  - `state.json` is fsynced;
  - the protective stop has its own 0.99 price cap;
  - `config_state` is faster again;
  - a bad `KALSHI_ARENA_*` value now turns the arena off with a warning instead of stopping the engine;
  - the arena shuts down after every real-money shutdown step, and `close()` waits up to 1 s for the town's final save;
  - the town no longer keeps a copy of every window the desk ever saw, only ones it can still use;
  - the live side now logs its own cost every 5 minutes (`kalshi_arena_feed`).
- No longer applicable, because the town has its own process: slow saves in an old town, long garbage-collection pauses, and the long mass-eviction step.
- Review 2 #12 is addressed: the default suite now runs the real town process. The wall-clock lateness test is still opt-in.
- Deferred:
  - live-loop lateness figures in the live desk's own `speeddesk_status` heartbeat (a change to the live desk's report; better done with the 10x speed work);
  - `starter_stop_s` values at or below `close_s` still do nothing (harmless).

**Measured live-loop overhead** (shared 4-core machine, load average 8–12)
- Per book or print: one append, about 0.18 µs. A Bitcoin tick costs nothing.
- Per 50 ms step at 400 books a second of 25-level ladders, in the live thread's CPU time: median 0.16 ms, p99 0.34 ms, max 0.54 ms (about 2.4 µs per book).
- Opt-in wall-clock test with the real town at about 350 books a second: the 1 ms loop's median stayed at 0.080 ms and p90 went from 0.123 to 0.132 ms. The machine's own p99 is about 3 ms either way, so p99 can't show a difference here.
- The town's process uses about 22 MB of memory at start.

**Still to check**
- Production's real figures, from the `kalshi_arena_feed` and `kalshi_arena_status` log lines after deploy.
- Since this branch was cut, the base gained the earned-growth ladder (PR #40). The arena reads the live limits at start, so check at merge whether the ladder changes them while running.
- The four owner questions are still open:
  - is the account $50 or the $25 that `docs/ACCOUNTS.md` records;
  - is the broke line $10 or $40;
  - is the protective stop meant as a stop-loss;
  - should a candidate get its own forward-check line.

**For the owner, in plain words:** The Kalshi arena is a practice town of 12 trading bots on the live Kalshi Bitcoin 15-minute markets, using pretend money only. Each bot starts with $50 and its own trading settings, and pays $0.20 rent a day. A bot is evicted if it can't pay rent, drops under $10, or the risk checker says it is losing. Empty homes go to slightly changed copies of the richest bots that have a real record. One bot, "Live", always trades exactly like the real bot and is the yardstick. A bot that is winning over 100+ windows and clearly beats "Live" is flagged for you to look at; it is a lead to test, not proof, and it is never given real money. The town now runs as a separate low-priority program with no keys, so it can't slow down or break the real-money bot.

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

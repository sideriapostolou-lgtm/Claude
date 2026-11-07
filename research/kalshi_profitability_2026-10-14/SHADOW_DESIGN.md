# Three-arm shadow implementation and available evidence

Read-only source inspection, 2026-10-14. No existing held-out TEST outcomes were opened. No secret, Railway setting,
live order or application file was changed by this inspection. This file specifies work; it does not claim a
comparison is running.

## What exists and what is missing

| Source | Available evidence | Limitation |
| --- | --- | --- |
| `kalshi_arena.py` / arena child | Same received books/prints, BTC price/time/volatility, window terms/results and gap counters as the live runner; own process with empty environment | Its evolving population is exploratory; current feed health must be repaired before scoring |
| `speeddesk_model.PracticeDesk` | Independent inventories, real-print queue depletion, post-delay IOC recheck, fee accounting, settlement split | Cancellation removes bids instantly; lock sequencing and risk admission are not a complete replica of current live execution |
| Arena `state.json` / `panel.json` | Bounded resident results and coverage telemetry | Does not preserve a lossless historical book/print/BTC tape; a good-looking resident is not an untouched holdout |
| Live receipts | Real accepted orders, cancels, fills, balances and settlement reports | Unfilled decisions are not a complete synchronized counterfactual book; cannot negate P&L to infer a reversed result |
| Separate `kalshi-recorder` service | Hashed public REST books/prints/terms/results; about 1 Hz BTC books, request and receive times | No authenticated websocket sequence; spot was off at audit start, enabled at 14:32 UTC (startup verified only); runtime files are on its private volume |
| Recorder branch optional `SpotTicks` | Public Coinbase and Kraken feeds already implemented | `KALSHI_RECORDER_SPOT_TICKS` defaults false; availability in code is not proof it has recorded a tick |
| Existing toxicity handoff | TRAIN/VAL summaries and manifests | Original parquet files were in Claude's scratch directory; newest 23 TEST windows remain sealed |

The recorder code and Family A protocol are on `origin/claude/kalshi-recorder`, not the current deploy tree.
Inspect them with `git show` or a separate read-only worktree. The older protocol section 16 says spot is not
recorded; the later implementation adds an optional off-by-default spot lane. Neither proves historical spot
coverage. The already running skip watcher also stores public spot observations under `/data/skipwatch/`, but
its host/receipt clocks and retained coverage must be checked before any join to another service's tape.

## Smallest live comparison without adding work to the live loop

Prefer a new **child-side** module `src/nightcrawler/kalshi_shadow.py` and tests
`tests/test_kalshi_shadow.py`. Feed it from the arena process's already-received frames. Leave
`SpeedRunner`, `ArenaLink._flush`, the websocket readers, live trading files, settings and order clients alone.
The only integration points in `kalshi_arena.py` are inside the child worker:

1. Construct `FixedShadowStudy` from the existing secret-free `ArenaConfig` plus the committed activation record.
2. Feed already-decoded messages at the child receive time to `study.receive(message, received_at)` before they
   are discarded. Replay `w/m/k/o/b/t/g` wire records with an independent delta base and gap counters; never share
   mutable books, inventory or ledger state with breeding residents.
3. Call `study.step(now)` under a separate bounded work allowance, and checkpoint/close it when the child exits.
   A failed/slow study suspends itself and marks gaps; it must not prevent normal arena frames being consumed.

This avoids extra live-loop serialization and new subscriptions. It still consumes shared service CPU and disk:
it is not free or guaranteed harmless. Measure end-to-end frame lag, dropped counts, worker memory, pass time,
and live producer flush time before and after. If its bounded work allowance cannot maintain complete coverage,
move the study into a separately limited child or use offline replay; never relax the coverage threshold.
Health repair takes priority over adding study work to an already losing feed.

Preserve a compact append-only study journal of causal inputs/decisions/execution receipts, UTC hour segments,
CRC/hash manifests and gaps. Put it under `DATA_DIR/kalshi_shadow/`, with a hard cap and low-disk shutdown that
stops only the study. Save every config hash and window membership. Do not write more full-depth duplicates
than necessary; deduplicate unchanged ladders with validated bases. Because the bot volume also holds its real
ledger, a bounded journal needs a measured storage budget before activation. Reusing recorder storage on a
separate service is safer for a large raw-tape archive, but cannot silently replace wire timing evidence.

## Do not treat a thin PracticeDesk wrapper as complete

The inherited `PracticeDesk.cancel()` and `cancel_order()` delete orders immediately. A new research-only
`DelayedPracticeDesk` must keep cancel deadlines and reservations, allow intervening partial fills, reject
duplicate cancel scheduling, and apply acknowledgments in causal time order. It must wait for cancel
acknowledgments before placing replacement bids **and before `_lock_step` can create a take**. The base lock
currently calls cancel then creates a take in the same method; overriding cancel alone is insufficient.

`PracticeDesk._risk_reason` also uses an incremental-risk day admission approximation, while current live admission
uses the recently corrected conservative policy. Arena `fixed_config()` explicitly omits the lifetime stop.
Therefore the new research ledger must implement and test the complete frozen cash/window/open/day/total policy,
including strictly balancing exceptions and persistent latches. Do not import a trading client or initialize
`Settings` to achieve this. A small pure shared risk helper can be considered in a separately reviewed change;
copying all of `KalshiLiveDesk` into the shadow is not the small safe implementation.

The live lock deliberately has an exception to ordinary window/open spending budgets: a strictly balancing buy
against confirmed unpaired holdings can spend above $10 gross in a window while reducing worst-case loss. This
is the existing rule, not a new budget increase. A shadow called the control must preserve that exception with
the actual cash/uncertainty/inventory/freshness/loss-reduction checks and disclose completion spend. Imposing a
new hard $10 gross limit would define a different strategy and must not be mislabeled as the current control.

For inverted decisions, keep the actual `Window`, `Book`, `Trade` and outcome unchanged. A research-only evaluation
function takes `fair_transform(p)` (identity or `1-p`), then follows the same side ordering, prices, independent
inventory and risk checks. Do not mutate global `fair_up`, monkeypatch the live module or reflect Bitcoin prices
to trick the model. The no-trade arm needs only a fixed ledger and a per-window zero-result receipt.

## Required synthetic tests before activation

- Original and inverse use opposite fair probabilities but the same actual books; their fills and P&L need not
  sum to zero. No-trade always has zero orders, fills, fees and exposure.
- No client construction, credential access, HTTP order endpoint or real-order path is reachable from the module.
  Passing an environment containing a key must not transmit it to study state or logs.
- No simulated maker fill before create eligibility; post-only cross refused; actual queue ahead depleted once;
  duplicate/wrong-side/late prints do not create fictional fills. IOC rejects an ask that disappears after latency.
- A cancellation does not release a reservation; a fill in the cancellation interval counts; replacement and lock
  wait; the acknowledgment releases only the remaining quantity. Test same-time ordering and venue expiration.
- Dollar caps, available cash, partial fills, fees, day rollover, total-stop persistence and balancing exceptions
  match the frozen rules. Restart cannot re-fund an arm, erase costs or clear the lifetime stop.
- Sequence gaps, dropped frames, missing book bases, startup mid-window and stale inputs affect all arms equally;
  excluded windows still retain previously incurred costs/exposure in the operational ledger.
- Code/config hash mismatch cannot start or resume a cohort; no scores before the fixed endpoint; a strategy
  change requires a new future activation. Test restart at the endpoint and ledger/accounting identities.
- Bounded journal/full disk/worker timeout leave production unaffected and the study explicitly incomplete.

## Safely retrieve existing evidence

Available Railway connector tools include `railway_get_logs`, `railway_get_service_metrics`,
`railway_list_deployments` and `railway_environment_status`; they do **not** expose an exec/SSH or volume-download
tool. Use them for bounded recorder health/deploy/status checks, not as a claimed substitute for raw tape.
Never list Railway variable values. Exact known recorder identifiers are service
`736b1c8a-8311-4ee0-9043-d05f508cd821`, project `75750847-85c0-41a3-a2a7-b7f2201a51e9`, production
`17f7b0e0-104c-4903-9484-0106748b3cdb`.

With an already authenticated Railway CLI/console that permits execution on **the recorder service**, existing
safe commands are:

```text
python -m nightcrawler.kalshi_recorder status --data-dir /data
python -m nightcrawler.kalshi_recorder verify --data-dir /data
```

These produce metadata/hash verification, not P&L, and do not print variable values. An export would copy only
selected sealed public-data segments plus their `index.jsonl` and coverage manifests; validate hashes after
copying. Do not copy `/data` wholesale, the bot ledger, environment, credentials or hidden TEST partitions.
No built-in recorder export CLI exists today: its supported commands are `run`, `status`, `verify`. If runtime
shell access is unavailable, add a reviewed bounded public-data export/report path on the recorder service;
do not claim those files have already been read from local GitHub copies.

Existing optional spot capture can be enabled by the named setting `KALSHI_RECORDER_SPOT_TICKS=true` on the recorder
under the owner's current public-data recording mission and broad instruction to improve the bot, as interpreted
by the coordinating worker. It requires no key and creates no order path.
It is a useful fallback acquisition route, but restarts that recorder and consumes extra storage; preserve the
Family A protocol/retention obligations and observe the restart. No such setting was applied in this inspection.

## Audit of the existing spot toggle

Inspected exact recorder commit `0713e41` in detached worktree
`/workspace/nightcrawler-shadow-recorder-audit`; no source was edited there. The setting is implemented by
`RecorderSettings.spot_ticks` and `Recorder.run`, and starts `SpotTicks` with two public subscriptions:

- Coinbase: `wss://advanced-trade-ws.coinbase.com`, BTC-USD `market_trades` plus `heartbeats`.
- Kraken: `wss://ws.kraken.com/v2`, BTC/USD `trade`, `snapshot=false`.

Neither subscription carries account credentials. It does not increase the Kalshi REST request budget. Trade rows
retain their own exchange timestamp and per-message local receive time; one-second flushing does not pretend to be
one-second exchange timing. The spot thread writes through the store's mutex and ordinary storage policy. The
`spot` lane is shed with BTC at the soft cap and old segments share the BTC retention period; unscored Family A
evidence is protected. Tick volume and extra disk growth still require measurement. Public websocket reachability
must be verified on Railway rather than assumed from an accessible workspace.

The startup receipt must say `mode=READ_ONLY_PUBLIC ... spot=True ... cap_mb=4608` on the known recorder service.
It must not say `refusing to run next to trading keys or live switches`. Check for
`kalshi_recorder_spot_disconnected`, `kalshi_recorder_gap`, `kalshi_recorder_paused`, storage-shedding warnings,
tracebacks, increased memory and lost book coverage. Record the exact deployment SHA and its status.

There is **no success log that proves ticks were persisted** in this implementation. Startup `spot=True` means
enabled only. No disconnect warning plus network flow to those two hosts supports connectivity, not data
completeness. Verify actual rows with a nonzero `bytes_by_lane.spot` in recorder `status` after a segment seals,
and inspect the matching segment metadata/coverage manifest plus `verify` hashes. Per-venue successful rows,
freshness, timestamp sanity and duplicate/sequence handling need a bounded read of the spot segment; absent that
access, explicitly report persistence unverified. The spot parser preserves raw messages but does not validate
Coinbase sequence continuity; it is public market evidence, not a perfect lossless exchange feed.

Validation on `0713e412b8077a32bced8794b2f26bbb46c59097`: all **81 tests passed** in
`test_kalshi_recorder.py`, `test_kalshi_recorder_no_orders.py` and `test_kalshi_recorder_store.py`. These include
spot parsers, fake websocket reconnect/batching, public-only transport and protected storage behavior. They do
not establish that Railway's websocket connections work or that production has persisted spot rows.

## Reproducible metadata sufficiency check

`shadow_sufficiency.py` reads bounded exported metadata only and emits allowlisted numeric/boolean facts. It
cannot read raw tape lists, calculate a return, expose hidden TEST outcomes, or claim complete execution evidence
from healthy counters. Its three inputs are optional; absent evidence remains unknown rather than zero.

```text
python research/kalshi_profitability_2026-10-14/shadow_sufficiency.py \
  --arena arena-block.json --recorder-status recorder-status.json --recorder-verify recorder-verify.json
pytest -q research/kalshi_profitability_2026-10-14/shadow_sufficiency_test.py
```

The names above are expected local exports, not files claimed already retrieved. The twelve synthetic tests
pass, as do Ruff on the two new Python files and mypy on the checker. Even clean metadata reports
`METADATA_CHECKS_ONLY`; valid cohort coverage, received spot rows, actual quotes/prints, cancellation timing,
fees and outcome terms are separate requirements. Lifetime arena counters cannot establish a new cohort's
coverage.

## Deliverable boundary

This session can honestly produce the fixed design, a synthetic-tested implementation and verified collection
health after repair. It cannot produce a valid 14-day prospective result immediately, reconstruct unavailable
queues, or turn the existing zero-valid-window arena into profit evidence. A healthy first window is a collection
milestone. Profitability remains an empirical question, including the possibility that both trading arms lose.

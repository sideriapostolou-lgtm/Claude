# Next learner evidence: observation only

Exact source: `153a12214f8763b9bf9382697fe6d6810ab04860`. Recommendation: add a small, prospective, child-only rejection diagnostic before considering a V2 input-quality protocol. Do not weaken V1 admission to obtain forecasts. This is a design review, not implementation or release authorization.

## What the new original establishes

`learning-slot-0905.json` contains an anchored original `kalshi_online_learning_unknown` at 2026-10-15T16:05:00.063125543Z (payload time 1792080300.0598047), ticker `KXBTC15M-26OCT151215-15`, reason `pregap`. At 16:05:12 the learner remains enabled and observe_only, with zero forecasts, zero scored, ten unknown (nine pregap and one startup_inside); Brier values are null. It does not establish whether the rejected input was a disconnected source, quiet maker trade expiry, explicit window gap, local drop, or child lateness. The status pending count describes frozen forecasts, not necessarily all internally admitted windows.

## Exact information loss

- `kalshi_online_learning.py:151–171`: `degrade` stores only a truncated reason in `pending[slug].pregap`, and subsequent degradations overwrite it. `gap` assigns the same `explicit_feed_gap` to three distinguishable conditions: trade_stream false, Coinbase false, or slug explicitly named. It also records global `feed_ok`.
- `kalshi_online_learning.py:236–270`: at the fixed 300–305 second slot, stored pregap OR a degraded-map entry OR feed_ok false rejects the window. The released child passes an empty degraded map. Earlier label/terms processing or lateness can finish a pending window first.
- `kalshi_online_learning.py:99–106`: `_finish` removes pending and logs generic `pregap`; neither the overwritten reason nor its time survives in the recent unknown record. Existing persistence therefore cannot reconstruct that detail after rejection.
- `kalshi_arena.py:1105–1150`: the batch already carries sequence and parent frame timestamp, but receive discards `_sent_at`; individual `g` records carry only slugs and two booleans. They have no producer occurrence timestamp. Child receive and later inbox application are separate times.
- `kalshi_arena.py:1152–1179,1230–1293`: local missing-ladder/drop/late-book/late-trade paths and gap application are separate causal routes, but the learner's final generic event does not identify the route. The local drop replay uses the original child-observed drop time.

## Why maker availability is a distinct hypothesis

`speeddesk_kalshi.py:184–192` publishes trade_stream as bool(rest-or-WebSocket maker windows), not merely socket connection. REST eligibility requires a recent trade; `speeddesk_kalshi_ws.py:331–335` additionally gates maker windows on trade age and emits gaps when prior maker eligibility disappears. Metadata-window-set changes also publish trade_stream false (`speeddesk_kalshi.py:246–255`). `speeddesk.py:322–345` forwards gap slugs, trade_stream, and Coinbase-connected into ArenaLink; `kalshi_arena.py:606–607` drops all other producer status context. Thus a producer maker-availability transition can veto a probability forecast, but the new original does not prove this happened in this window.

## Minimum useful diagnostic

Keep pure learner source, protocol, state schema, counters, old unknowns, live rules, and save cadence byte-identical. Add only bounded observation state and logging in the arena child:

1. Before each existing child learning `gap`/`degrade` call, capture a fixed-shape observation for affected admitted pending keys. Retain first effective preforecast cause plus last effective cause, not merely the latest global status. Bound the map to learner pending keys (at most 32); prune on removal. Do not persist it. On restart mark unavailable history as unknown, never reconstruct or relabel V1 history.
2. Distinguish explicit slug membership, trade_stream false, Coinbase false, sequence discontinuity, increased drop counter, missing ladder, late book, late trade, and replayed original drop. Preserve simultaneous conditions as fixed booleans, not a guessed single upstream cause. An event should count as effective only according to the existing method's start/end/forecast conditions; do not mutate admission logic.
3. Attach child receive time and child apply time, frame sequence and the already-present parent frame timestamp where available. Late book/trade observations can retain their existing received_at/at and computed lateness, with named clock meanings. A frame timestamp is not the gap occurrence time and excludes parent FIFO residence before encoding. For a gap with no occurrence clock, emit producer_event_time=null and explicit unavailable timing. Validate finite clocks; report skew/reversal as unknown, never clamp into favorable delay.
4. Immediately before unchanged `advance`, copy only bounded due pending metadata: slug/start/end/elapsed, forecast-none state, stored pregap, feed_ok, current `_feed_status`, fixed BTC-age/spot/sigma validity facts, and the compact first/last observations. After `advance`, attach the actual disposition from the resulting bounded learner recent record/counters, rather than predicting which branch ran. Emit at most once per eligible due window; include late-first-pass or earlier-termination cases explicitly when no due observation exists. No historical backfill.
5. Use one fixed-schema diagnostic event with a diagnostic schema version, exact deployment/source identity, child process/instance identity, learner protocol/fingerprint and observation coverage. Whitelist reasons and bound text/numbers. No per-tick or per-gap logging, full snapshots, extra fsync/files, resident state, credentials, orders, or profit labels. Isolate logging errors without disabling the learner or affecting practice/live decisions.

This proves which child input conditions caused or accompanied exclusion and separates frame transit from child waiting where clocks exist. It cannot, by itself, distinguish quiet trade expiry from a genuine upstream loss behind trade_stream=false. For that final distinction, a separate prospective observation-only producer context would be needed: timestamped on_status occurrence, producer reason, relevant book/trade eligibility ages and frame correlation. Do not silently extend the wire in a purported child-only patch; assess that larger scope and parent-loop overhead separately.

## Can existing evidence replace it?

The fixed capture's original feed timing/gap receipts can show observed rejected frames or local residence, and sampled producer statuses can show connection/maker availability. They may support a hypothesis with matching ticker and clock, but neither a healthy sample nor an empty error query proves there was no intervening gap. Existing gap wire has no occurrence timestamp or unique event ID shared with the learner; the generic learner event has no first trigger. There is no exact causal join for the current exclusion. Do not query outside the fixed capture to rescue its outcome or treat nearest-in-time diagnostics as a unique cause.

## Acceptance cases before any later release

- Actual child methods with fake clocks: explicit slug versus trade_stream false versus Coinbase false; simultaneous causes; recovered feed still retains first effective gap; future prestart event does not become an active cause; late book versus late trade; missing ladder before/after window announcement; sequence and drop-counter paths; original-time replay.
- Same batch delayed across start, multiple batches queued before drain, invalid clocks, absent producer occurrence timestamp, and frame send versus child receive/apply durations. No fabricated producer-to-child delay.
- Due forecast, due pregap, late first pass, label/terms termination before advance, postforecast gap, restart with old pregap, and out-of-order official outcomes. Diagnostic disposition must match actual learner behavior.
- Compare child outputs, resident decisions, serialized arena state, learner counters/receipts, source fingerprint, and save/fsync cadence with diagnostics disabled/enabled. Diagnostic exceptions must have no behavioral effect. No duplicated slot emissions; memory remains bounded after many windows/restarts.
- Measure actual child-step CPU/wall overhead and maximum diagnostic event size at maximum pending capacity; no new work in the live controller. Existing execution-delay blocker stays open.

## V2 decision

A new probability-input-quality protocol is justified only as an explicit prospective design if evidence confirms simulator maker-tape availability is imposing the wrong quality requirement for probability labels. V2 must define required BTC/strike/official-outcome quality, admission/unknown handling, independent history identity and out-of-sample comparison before use. Preserve V1 counts and unknowns; do not rewrite or backfill them. The unchanged b611 fingerprint covers pure learner/fair-model code, not arena input hooks: every diagnostic/input-path release still needs its exact source SHA. No forecast, profit, perfection, all-gaps-fixed or EXEC-completion claim follows from either option.

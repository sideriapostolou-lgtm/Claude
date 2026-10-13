# Kalshi research recorder and the Family A replay

Owner: Claude (Kalshi research lane). Protocol: [`research/kalshi_edge_search/PROTOCOL.md`](../research/kalshi_edge_search/PROTOCOL.md)
(`kalshi-familyA-v1`, SHA-256 in `PROTOCOL.sha256`). Code: `src/nightcrawler/kalshi_recorder.py` (lanes and entry
point), `kalshi_public.py` (the GET-only transport and the shared request budget), `kalshi_recorder_store.py`
(rotating storage), `kalshi_familya_universe.py` (admission rules, tick grid, risk clusters) and `kalshi_familya.py`
(the queue-aware replay and accounting).

**Plain words:** the recorder writes down what Kalshi's public market data said, second by second, so that later
we can check, honestly, whether patient one-contract bids on the favourite would have made money. It cannot trade.
Every dollar in the replay belongs to a SIMULATED $25 research account.

## 1. Safety

- Public, unauthenticated GETs only, to the allowlist of PROTOCOL.md section 2.1 (`kalshi_public.PUBLIC_PATHS`).
  No key, no signer, no Kalshi websocket, no redirect, a 16 MiB response cap, no query parameter off the
  allowlist. The transport class has exactly one public method, `get`.
- No order, cancel, amend, portfolio or account call exists in these five modules, and none of them imports an
  order or trading client. `tests/test_kalshi_recorder_no_orders.py` fails if any such import, name, non-GET call
  or `/portfolio` path appears, and it runs a full recorder pass through the real `requests` stack (only
  `Session.request` faked) to prove that every request it can reach is a keyless public GET.
- No live setting, cap, key or trading code is read or changed. `config.py` (real-money code) is untouched: the
  recorder reads its own `KALSHI_RECORDER_*` variables (validated by `RecorderSettings`).

## 2. Running it

As its own process or service (recommended):

```bash
python -m nightcrawler.kalshi_recorder run        # writes DATA_DIR/kalshi_recorder/ until SIGTERM/SIGINT
python -m nightcrawler.kalshi_recorder status     # storage by lane, lanes, coverage (status.json)
python -m nightcrawler.kalshi_recorder verify     # re-hash every sealed segment against index.jsonl
python -m nightcrawler.kalshi_recorder run --data-dir /tmp/rec --max-runtime-s 300   # a smoke run
```

Inside the bot: set `KALSHI_RECORDER_ENABLED=true` (it is **OFF by default**). `engine.build_app` then starts it
in a daemon thread (`kalshi-recorder`), guarded so a fault can never stop a desk. This is not recommended: the
bot already polls Kalshi's public API from the same IP (the BTC desk's fallback feed, coin desks, weatherwatch),
so the recorder's 1.5/s would push the IP past 2/s, and the bot's volume already holds skipwatch, weatherwatch and
the learner.

**Proposal (owner decision, not done):** a separate small Railway service in the same project, built from the same
image, start command `python -m nightcrawler.kalshi_recorder run`, its own volume mounted at `/data`
(`DATA_DIR=/data`), `KALSHI_RECORDER_MAX_STORAGE_MB=4608` on a 5 GB volume (Family A's TEST evidence needs about
4.5 GB, PROTOCOL.md section 12), no Kalshi keys in its variables, 0.25 vCPU / 256 MB is ample (one thread, about
1.5 requests a second, gzip). Its incremental cost is unmeasured; read it from the Railway usage page after a day
and record it, because Family A's verdict is judged after half of it (OPEX_A, PROTOCOL.md section 13). The
protocol's fallback is $5 per month.

## 3. Request budget (one shared limiter)

At most 2 request starts in any rolling second, spaced at `KALSHI_RECORDER_RATE_PER_S` (1.5 by default; the
ceiling cannot be raised). After a 429 the whole recorder runs 25% slower for ten minutes and every lane honours a
Retry-After; the lane that saw it also waits 2^n seconds (n = 429s in a row, at most 30 s). Lanes share the budget
by weighted fair queueing (books 8, trades 4, backfill 2, KXBTC15M metadata 2, discovery 2, sweep 1,
settlement 1, fees 1, other 0.5), so no lane starves.

| Lane | Request | Cadence |
|---|---|---|
| books | `/markets/orderbooks?tickers=...` (100 a call): current + next KXBTC15M, then the most overdue candidates | 1 s; candidates with a favourite mid in 0.45-0.97 every 20 s, the rest every 60 s |
| trades | `/markets/trades?min_ts&max_ts` exchange-wide, 5 s overlap, every page until the cursor is empty; a live window spans at most 60 s | 5 s |
| backfill | the same, for a window that failed or a backlog older than 60 s (exchange-wide and merged into one growing job, or per watched ticker when cheaper) | after a gap |
| discovery | `/series?category=` (4 open categories, daily), `/events?status=open` (all pages), `/series/{t}` for unknown series, `/markets?series_ticker&min_close_ts&max_close_ts` | hourly |
| btc15m_meta | `/series/KXBTC15M`, `/markets?series_ticker=KXBTC15M&...`, `/events/fee_changes` per new window | every window |
| sweep | `/markets?tickers=` (300 a call): quotes, volume_24h, status | 5 min |
| settlement | `/markets?tickers=` for markets past close until `finalized` with a result | 15 min |
| fees | `/series/fee_changes?show_historical=true`; `/events/fee_changes?event_ticker=` per candidate event | daily, and at once for a new event |
| other | `/historical/cutoff`, `/incentive_programs` (recorded, never credited) | daily |

**Measured from the workspace, 2026-10-13 (not Railway; this sandbox shares its outgoing IP):** two 5-minute
runs at 1.0 request/s. Run 1 (19:35-19:40 UTC): 280 GETs, 57 of them 429s (33 on the trade lane), and the live trade
window, then allowed to span 600 s, kept growing; this is why live windows are now capped at 60 s with the backlog
merged into one backfill job. Run 2 (19:41-19:46 UTC, after the fix): 290 GETs, 2 429s, at most 1 request start in
any rolling second, trade coverage contiguous from 12 s after start to the end (14,694 KXBTC15M prints kept), 140
KXBTC15M books from three windows, 49 of the ~69 open-event pages, 107 series fee changes, 5,670 incentive programs
in 6 pages, every sealed segment's hash verified, request round trip p50 84 ms / p95 128 ms, receive minus
`created_time` p50 25 s / p95 64 s (the trade lane is the one starved first). The first full discovery pass takes
longer than 5 minutes at this rate, so no Family A candidate was recorded yet. Railway's limit must be measured in
Phase 0.

Optional (`KALSHI_RECORDER_SPOT_TICKS=true`, off by default, outside protocol v1): Coinbase Advanced Trade and
Kraken v2 public BTC trade websockets into the `spot` lane. They are exchange spot prices, labelled
`exchange_spot_not_cf_benchmarks`, never the settlement index.

## 4. Admission (what gets recorded)

Discovery applies the protocol's rules U1-U11 (section 4.1) with the wider recording window of section 3
(5 h - 8 d left instead of 6 h - 7 d) and without U10 (fee completeness), which the replay applies at each
decision from the recorded fee lookups. Every market seen gets an admission row (`admissions` lane, kind
`admissions`, on first sight and whenever its decision changes) with `rule` and `reason`
(`category_blocked`, `category_unconfirmed`, `category_mismatch`, `non_binary`, `not_active`, `duration_lt_24h`,
`outside_recording_window`, `notional_not_1`, `ambiguous_settlement`, `nonstandard_settlement`,
`linked_without_mapping`, `tick_unknown`, `recorder_capacity`), plus a `discovery_summary` with counts by category
and reason and the count of events in other categories. A watched ticker gets `watch` rows (`start`, `stop`,
`resumed`): trades are kept for a ticker only while it is watched, so its tape is complete only from its start.

## 5. Files (all under `DATA_DIR/kalshi_recorder/`)

| Path | What |
|---|---|
| `segments/<lane>/<YYYY-MM-DD>/<lane>-<UTC start>-<first seq>.jsonl.gz` | sealed gzip JSONL, one per lane per UTC hour (or 64 MiB) |
| `segments/.../*.jsonl.gz.part` | the open hour; flushed every 5 s; after a crash its complete lines are re-sealed and the torn tail is counted as a gap |
| `index.jsonl` | append-only: every sealed segment (`sha256`, `prev_sha256` per lane, records, first/last seq and time, bytes) and every deletion with its reason |
| `state.json`, `recorder_state.json` | next sequence number and storage level; the watch list, fee lookups, trade coverage end and last-alive time (for restart gaps and backfill) |
| `status.json` | heartbeat each minute: lanes, storage, candidates, KXBTC15M windows |
| `manifests/coverage-<YYYY-MM-DDTHH>.json` | the hourly coverage manifest (below); a session that stops mid-hour writes `coverage-<hour>-<session>-partial.json` |

Every record: `seq` (local, monotonic across restarts), `lane`, `kind`, `at` (receive time, host UTC clock),
`session`, then the payload. Prices and sizes stay Kalshi's decimal strings.

| Lane / kind | Payload |
|---|---|
| `books` / `book`, `books_btc15m` / `book` | `ticker`, `requested_at`, `received_at`, `sha256`, raw `orderbook_fp` (written only when it changed) |
| `book_calls` / `book_call` | per batch call: `tickers`, `changed`, `unchanged`, `missing`, `status`, `body_sha256`, `rtt_ms` |
| `trades` / `trades`, `trades_btc15m` / `trades` | raw rows of watched tickers (Kalshi `created_time` in microseconds), `window`, `page`, `scope`, `rows_in_page`, `body_sha256` |
| `trade_coverage` / `trade_coverage` | `from`, `to` (whole seconds), `scope` (`exchange` or a ticker), `backfill`, `pages`, `rows`: every print of every watched ticker in the span was received |
| `discovery` / `series_list`, `events_page`, `series` | raw series rows; open-category event rows (other categories counted, and the full page hashed) |
| `markets` / `discovery_markets`, `sweep` | per ticker either `full` (the raw row, when its rules/terms changed) or `dyn` (quotes, volume, status), with `static_sha256` |
| `settlement` / `settlement` | raw market rows of Family A candidates past close |
| `btc15m_meta` / `series`, `markets`, `event_fee_changes`, `settlement` | the KXBTC15M terms and each window's row from discovery to `finalized` |
| `fees` / `series_fee_changes`, `event_fee_changes` | raw bodies |
| `other` / `cutoff`, `incentives` | raw bodies |
| `requests` / `request` | every GET: `request_lane`, path, query, status, error, request/receive time, `rtt_ms`, bytes, `sha256`, `retry_after_s` (the 429 log) |
| `gaps` / `gap`, `trade_conflict`, `handler_error`, `session_started` | `gap_lane`, `from`, `to`, `cause` (`lane_stale`, `trade_page_failed_429`, `recorder_not_running`, `clock_moved_backwards`, `storage_cap_paused`, ...) |
| `telemetry` / `coverage_manifest` | the hash of each hourly manifest |
| `spot` / `spot_trades` | optional raw Coinbase/Kraken trades with `received_at` |

Nothing is fabricated: a failed request is a request row and, when a lane goes stale for more than
max(2 x cadence, 30 s), a gap; a failed trade window is backfilled from the public tape or stays a gap; a book gap
is permanent (Kalshi has no public book history).

**Coverage manifest** (hourly, atomic): host label (`workspace`/`railway`), session, version and commit,
`read_only: true`, per-lane requests / ok / 429 / errors and request round-trip p50/p95/p99, receive-minus-
`created_time` p50/p95/p99 for prints, minutes sampled, the share of candidate-minutes with a book at most 120 s
old, trade-tape minutes, KXBTC15M minutes with a book at most 5 s old, gaps, storage, and the sealed segments
with their hashes.

## 6. Disk

Default cap 2 GiB (`KALSHI_RECORDER_MAX_STORAGE_MB=2048`), plus a free-disk reserve. The audit estimated
150-230 MB a day for every lane, so 2 GiB holds about 9-13 days; Family A's 28-day TEST needs about 4.5 GB.
**Before TRAIN starts the owner must choose** a dedicated volume with a cap of at least 4.5 GB, or a nightly
lossless compaction (PROTOCOL.md section 12). At the cap, under the default `protect` policy, the recorder:

1. deletes KXBTC15M (and spot) segments older than `KALSHI_RECORDER_BTC15M_RETENTION_H` (72 h);
2. above 95% of the cap, stops KXBTC15M/spot capture (a gap);
3. at the cap, pauses (a gap). It never deletes unscored Family A evidence. An owner-set
   `KALSHI_RECORDER_RELEASE_BEFORE` date allows Family A segments older than it to go (after a verdict).

`rotate` is a plain ring buffer (oldest first) for use outside the protocol.

## 7. The Family A replay

```bash
python -m nightcrawler.kalshi_familya check  --phase TRAIN --first-day 2026-10-20 --days 7
python -m nightcrawler.kalshi_familya replay --data-dir DATA_DIR --phase TRAIN --first-day 2026-10-20 --days 7 \
    --variant A1 [--model pessimistic] [--latency-ms 1000] [--day-stop live_style] [--unfunded] [--out a1.json]
```

Variants `A1`-`A4` and the matched baselines `MB-J`/`MB-I` (section 10). It refuses to score unless
`PROTOCOL.md` matches its published hash; it refuses **TEST** until `research/kalshi_edge_search/family_a/FREEZE.json`
and `FREEZE.sha256` exist, match, name the protocol hash, and match the run's variant, E1 and entry days; and it
refuses TRAIN/VAL entry days that reach a frozen E1.

What it models (with the tests that pin it, `tests/test_kalshi_familya_replay.py`): exact decimals on the market's
`price_ranges` grid; decisions every whole UTC minute from what was received by then; post-only at arrival and on
the first later book; the queue ahead = the larger displayed size, reduced only by prints and by displayed size
falling below it (top 10 levels); fills only from non-block prints selling into our side, after the queue, in
0.01 steps; inconsistent prints shrink the queue but never fill; a book offering at or below our bid counts once as
a print; cancels and replacements take effect after L (1 s primary), fills inside the cancel race and the
250 ms clock margin count, and the reservation is held until then; Kalshi's direct-account fee rounding (trade fee
up to $0.000001, balance down to $0.0001, per-order accumulator, capped rebates) with the series fee type and
scheduled series/event fee changes in force at each fill; the simulated $2 cluster / $4 outstanding / $3 day /
$5 lifetime / cash limits, one quote per cluster, one contract per market; rotation after 6 h without a fill;
the 6 h entry cutoff; settlement at the official result, cash at `settlement_ts`; capital-days; unresolved
positions at $0; exact cash reconciliation (a mismatch raises, it is a defect, not a result); the pessimistic
model (L >= 2 s, no queue gains from cancellations, trade-throughs fill first, no rebates).

Choices the protocol left open, fixed here before any data exists:

- A market with a partial position gets a quote for the rest (1.00 minus what is held), never the other side.
- A replacement is sent when the cancel is acknowledged (decision + L); a late fill of the old order in the
  clock margin trims the new order so the market never exceeds 1.00 contract.
- A settlement is processed when its row is received; its cash and P&L are dated `settlement_ts`.
- Trade-tape coverage for a ticker is exchange-wide coverage while the ticker is watched, or per-ticker backfill.
- The section 7.7 lower bound is the central net minus the remaining size times the price of every
  unidentifiable quote whose side lost (limits are not re-run for it).

Not built yet: the section 13 statistics (block bootstrap and t bound), the phase reports and scorecard, the
Phase 0 report, OPEX_A, and the live companion's acknowledgement latency (L stays 1,000 ms until measured).

## 8. KXBTC15M for the Kalshi arena (Family B)

The recorder simulates nothing for BTC15M. It records, for the arena to replay later with the existing parsers:
`books_btc15m` (raw full-depth `orderbook_fp` of the current and next window at about 1 Hz, with request and
receive times; `speeddesk_kalshi.parse_books({"orderbook_fp": raw}, ticker, received_at)`), `trades_btc15m` (raw
rows; `parse_trades`), and `btc15m_meta` (`/series/KXBTC15M`, each window's market row and fee changes, and its
settlement row; `parse_window`). These are deleted after 72 h by default; set the arena's retention with
`KALSHI_RECORDER_BTC15M_RETENTION_H`. REST snapshots carry no exchange sequence, so they are lower fidelity than
the arena's live websocket feed.

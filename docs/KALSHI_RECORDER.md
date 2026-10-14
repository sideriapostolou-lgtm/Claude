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

- Public, unauthenticated GETs only, to the allowlist of PROTOCOL.md section 2.1 (`kalshi_public.PUBLIC_PATHS`),
  plus one public path outside it that only the rewards (LIP) lane reads: `/live_data/events/{event}` (section 9).
  No key, no signer, no Kalshi websocket, no redirect, a 16 MiB response cap, no query parameter off the
  allowlist. The transport class has exactly one public method, `get`. Its session never reads `~/.netrc` and
  never keeps or sends a cookie (proxies from the environment still apply). A reply that is not strict JSON
  (`NaN`, `Infinity`, absurd nesting) is a failed request, never a record, and so is a number that overflows
  (`1e400`) in anything the recorder keeps (a row it drops, such as another ticker's print, fails nothing).
- No order, cancel, amend, portfolio or account call exists in these six modules (with `kalshi_recorder_pyth.py`),
  and none of them imports an order or trading client. `tests/test_kalshi_recorder_no_orders.py` fails if any such import, name, non-GET call
  or `/portfolio` path appears, and it runs full recorder passes through the real `requests` stack to prove that
  every request it can reach is a keyless public GET: once with `Session.request` faked, and once with only the
  transport adapter faked, asserting on the prepared request itself with a `~/.netrc` login for Kalshi's host and
  a cookie planted in the session (no `Authorization`, `Cookie` or `KALSHI-ACCESS-*` header is ever sent).
- `python -m nightcrawler.kalshi_recorder run` refuses to start (exit 3) when its environment or `.env` holds
  trading keys (`KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`, `BOT_WALLET_SECRET`, `POLYMARKET_US_*`) or any
  `*_MODE=live` switch. Only the names are checked; no key value is read, logged or printed. `PYTH_API_KEY` is a
  read-only price key, not a trading key (`READ_ONLY_KEYS`): it never stops the recorder, and it is used only by
  the Pyth lane (`kalshi_recorder_pyth.py`, section 9), which sends it only to an allowlisted Pyth host and never
  writes or logs it.
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

Inside the bot: set `KALSHI_RECORDER_ENABLED=true` (it is **OFF by default**; it is read from `.env` overlaid by
the real environment, as the bot's config is). `engine.build_app` then starts it in a daemon thread
(`kalshi-recorder`), guarded so a fault can never stop a desk. This is not recommended, and it is restricted:

- it **refuses to start while any desk in the process trades live** (any `*_MODE=live`, for example
  `SPEEDDESK_KALSHI_MODE` or `POLYDESK_MODE`, in `.env` or the environment, or in the Settings the bot actually
  runs with, which `engine` passes in, so a bot started with `nightcrawler --env-file other.env run` counts too):
  its 429s would come back to the live Kalshi client, which then holds every call, cancels included, for up to 30 s;
- it **refuses to start while the process holds Kalshi account keys** (`KALSHI_KEY_ID` or `KALSHI_PRIVATE_KEY`,
  in the Settings or the environment; names only), whatever the mode: a bot restarted on paper after a live Kalshi
  run still opens a real account client to read and cancel what that run left (the speed desk's companion
  recovers live orders in paper mode), and the same 429s would hold it;
- otherwise it runs a reduced profile: at most 0.25 request/s, no KXBTC15M lane, and at least 1 GiB of the bot's
  volume left free. The bot's own public Kalshi readers (the BTC desk's REST fallback, weatherwatch, skipwatch) do
  not share its limiter, so inside the bot the 2/s total is not enforced by this code.

**Proposal (owner decision, not done): a separate small Railway service.** The steps matter, because the bot's
service holds real-money keys and switches. Railway's Config as Code is deprecated and a new service cannot use
`railway.json` (the file in this repository configures only the existing `bot` service), so **every setting below
is set on the new service itself**, in its Settings and Variables tabs; nothing comes from a file:

1. In the same project, **create a new, empty service from the repository. Never use "Duplicate" on `bot`**: a
   copy carries `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`, the Polymarket keys and `*_MODE=live`, and the image's default
   command (`Dockerfile`) is `nightcrawler run`, the live bot. No `railway.json` applies to the new service, so a
   copy with a missing start command would be a second live bot on an empty volume with no record of open orders.
2. **Source branch:** the service may track `claude/kalshi-recorder` until the recorder is merged into the deploy
   branch (`claude/nightcrawler-memecoin-bot-Gwnb1S`); then switch it to the deploy branch. Every push to the
   tracked branch redeploys it (a SIGTERM, a `recorder_not_running` gap, then a backfill of the trade tape).
3. **Set the start command by hand** to `python -m nightcrawler.kalshi_recorder run`. Left empty, the image's
   default `nightcrawler run` starts the bot itself (without keys only a paper bot, but still the wrong service);
   check the first log line says `kalshi_recorder_started mode=READ_ONLY_PUBLIC`.
4. **Deploy settings, set explicitly:** restart policy **ON_FAILURE**; **no healthcheck path** (the recorder binds no
   port, so any path would fail every deploy); **draining time 30 s** (`drainingSeconds` 30, or the variable
   `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30`). Railway's default draining time is 0: SIGKILL follows SIGTERM at once,
   and the recorder's seal on SIGTERM (about 0.5 s measured) never runs. Even after a kill (an OOM kill, a host
   failure) only the last few seconds are lost: every lane's new rows reach the OS within 5 s (plus 1 s while a
   GET blocks, through a flusher thread), every lane is flushed before a GET that must wait (a Retry-After hold),
   and the restart re-seals the rest and records the gap.
5. **Add no keys.** Variables: `DATA_DIR=/data`, `KALSHI_RECORDER_MAX_STORAGE_MB=4608` and **`RAILWAY_RUN_UID=0`**.
   Railway mounts volumes as root while the image runs as `USER bot` (uid 10001), so without `RAILWAY_RUN_UID=0`
   (Railway's documented fix for a non-root image with a volume, as on `bot`) the recorder dies at its first write
   to `/data` (`PermissionError`) and ON_FAILURE restarts it until it gives up. If a key or a live switch is
   present, the recorder exits with code 3 and names it (names only).
6. Attach its own 5 GB volume at `/data` (Family A's TEST evidence needs about 4.5 GB, PROTOCOL.md section 12).
7. Size: 0.25 vCPU and **512 MB** of memory (one thread at about 1.5 requests a second; crash recovery is
   streamed: recovering a 63 MiB segment peaked at 22 MiB of process memory, down from 686 MiB, and segments now
   rotate at 8 MiB anyway).

Its incremental cost is unmeasured; read it from the Railway usage page after a day and record it, because Family
A's verdict is judged after half of it (OPEX_A, PROTOCOL.md section 13). The protocol's fallback is $5 per month.

## 3. Request budget (one shared limiter)

At most 2 request starts in any rolling second, never two starts closer than 0.5 s, and an average of
`KALSHI_RECORDER_RATE_PER_S` (1.5 by default; the ceiling cannot be raised). The average is a token bucket: with the
LIP lane on it holds 2 tokens, so a 1 s book call and the other lanes interleave at 0.5 s gaps; with it off (and in
the bot) it holds 1, which is plain spacing at the target rate, as before. After a 429 the whole recorder runs 25% slower for ten minutes and every lane honours a
Retry-After (clamped to 15 minutes; a hold of a minute or more is a `retry_after_hold` gap); the lane that saw it
also waits 2^n seconds (n = 429s in a row, at most 30 s). Lanes share the budget by weighted fair queueing
(books 8, trades 4, backfill 2, KXBTC15M metadata 2, discovery 2, LIP 2, sweep 1, settlement 1, fees 1, other
0.5), so no lane starves. While LIP books are pinned (section 9) a due book call goes first, and a lane whose start
would push the next one more than 0.1 s late waits; both are counted per lane (`preempted_by_lip_books`,
`held_for_lip_books` in the manifest) and written once a minute (`telemetry`/`degraded`).

**No reply can stop the recorder or wedge a lane.** A malformed reply (a list field that is not a list, a cursor
that is not a string, a handler error) is a `handler_error` record and counts as a failed attempt; a request the
transport refuses (a path or parameter off the allowlist, such as a lowercase series ticker) is a
`request_refused` record and is dropped at once. After `PAGE_ATTEMPTS` (5) failed attempts at the same request the
lane drops it with a gap and moves on: a trade window goes to backfill and then becomes a gap; a discovery item
(one category, the event list, one series, its detail and its markets counting as one) is skipped and the pass
continues, whatever the failure (a 5xx or a timeout included), and the next item gets its own 5 attempts. The whole
pass waits (retried in 5 minutes, `discovery_abandoned_*` naming the items) only when 3 different items strike out
on 429s, 5xx or no reply with no reply in between, and an item that was skipped in the last pass is one bad item,
never a reason to abandon the next; so a bad series can cost a pass 10 requests, never the pass. A sweep or
settlement chunk is dropped until the next round; a fee lookup is retried an hour later. A 4xx on
`/markets?tickers=`, or a reply there that cannot be read, halves the chunk within that pass (so one bad ticker is
isolated); every pass starts again at full size (300 a call), and a ticker whose own row failed alone is asked
alone, last, until it reads again (a 403 burst marks nothing). Kalshi answered 414 for a 10.2 KB URL and 200 for
6.6 KB (2026-10-13), so each chunk's encoded ticker list also stays under 5,000 bytes. A number that overflows
(`1e400`) makes a failed request (`non_finite_number`) only where the recorder keeps it: anywhere in a reply it
stores whole (sweeps, settlements, fees, KXBTC15M metadata, series lists and details), in a print of a watched
ticker (the page fails, so no coverage claims it) or an open-category event; another ticker's print or a Sports
event never fails a page. In a book reply only that ticker's book fails (a `book_unreadable` gap), the rest of the
call is recorded, and that ticker is asked again at the 60 s cadence, with or without the KXBTC15M lane. A market
row in a discovery reply that cannot be stored (`market_row_unreadable`), or that admission cannot read (an
overflowing decimal string, `row_unreadable`), is refused alone and the pass admits the rest.

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
| lip | `/incentive_programs?status=active|upcoming|closed&type=liquidity&limit=10000`, `/live_data/events/{event}` (section 9) | active every 15 min (5 s after each boundary), upcoming hourly, closed every 3 h; the series every 10 min |

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
| `segments/<lane>/<YYYY-MM-DD>/<lane>-<UTC start>-<first seq>.jsonl.gz` | sealed gzip JSONL, one per lane per UTC hour (or 8 MiB uncompressed) |
| `segments/.../*.jsonl.gz.part` | the open segment; every lane's new lines reach the OS within 5 s, quiet lanes included: the main loop flushes between GETs, a flusher thread flushes every second while a GET blocks (a read timeout), every lane is flushed before a GET that must wait (a Retry-After hold), and a wall clock that steps back flushes at once instead of waiting for the old time; so a SIGKILL or OOM kill loses only the last few seconds; prints are flushed before the `trade_coverage` row that vouches for them, and changed books before their `book_call` row; after a crash its complete lines are re-sealed (streamed, in bounded memory) and the torn tail is counted as a gap. Each line ends with its own CRC-32 (`crc`), and a salvaged line must match it and carry a higher `seq` than the line before: zeros or garbage after a host crash that zlib still decodes (copies of earlier bytes, valid-looking JSON) end the salvage as dropped bytes, never become records, and what zlib refuses is `undecoded_bytes`; a crash during that recovery never indexes a record twice (a leftover `.part` that is a prefix of its re-sealed copy is removed) |
| `index.jsonl` | append-only: every sealed segment (`sha256`, `prev_sha256` per lane, records, first/last seq and time, bytes) and every deletion with its reason |
| `state.json`, `recorder_state.json` | next sequence number and storage level; the watch list (saved before a new ticker's `start` row is written, so a restart resumes every ticker the tape says is watched), recently unwatched tickers (4 days), fee lookups, trade coverage end and last-alive time (for restart gaps and backfill) |
| `status.json` | heartbeat each minute: lanes, storage, candidates, KXBTC15M windows, the LIP pins and the Pyth streams, and `lane_bytes`: per lane the bytes on disk (and uncompressed), the bytes and records written this session, and `est_stored_bytes_per_day` at this session's rate |
| `manifests/coverage-<YYYY-MM-DDTHH>.json` | the hourly coverage manifest (below); a session that stops mid-hour writes `coverage-<hour>-<session>-partial.json` |

Every record: `seq` (local, monotonic across restarts), `lane`, `kind`, `at` (receive time, host UTC clock),
`session`, then the payload, then `crc` (the line's CRC-32 without it; readers drop it, and lines written before it
existed carry none). Prices and sizes stay Kalshi's decimal strings.

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
| `gaps` / `gap`, `trade_conflict`, `handler_error`, `request_refused`, `session_started` | `gap_lane`, `from`, `to`, `cause` (`lane_stale`, `trade_page_failed_429`, `recorder_not_running`, `clock_moved_backwards` (once per step back, with `seconds`; every schedule moves back with the clock), `storage_cap_paused`, `retry_after_hold`, `malformed_reply`, `series_ticker_unusable`, ...); `handler_error` and `request_refused` carry `handler_lane`, `error` and a one-line `detail`; `session_started` carries `keeps_prints_from`, the earliest print the new session vouches for: the replay closes, there, the watch of every ticker the tape had open that the session did not resume |
| `telemetry` / `coverage_manifest`, `chunk_halved`, `freeze_witness` | the hash of each hourly manifest; a sweep or settlement chunk halved after a 4xx; at each session start, Family A's FREEZE.json SHA-256 when `KALSHI_RECORDER_FREEZE_SHA256` is set (the TEST gate's clock, section 7) |
| `spot` / `spot_trades` | optional raw Coinbase/Kraken trades with `received_at` |
| `books_lip` / `book`, `trades_lip` / `trades` | the LIP markets' books (as `books`) and prints (as `trades`); never in a Family A lane |
| `lip` / `programs`, `book_call`, `watch`, `settlement`, `series`, `series_unavailable` | section 9 |
| `pyth` / `updates`, `connection`, `channel_downgraded`, `first_update` | section 9 |

Nothing is fabricated: a failed request is a request row and, when a lane goes stale for more than
max(2 x cadence, 30 s), a gap; a failed trade window is backfilled from the public tape or stays a gap; a book gap
is permanent (Kalshi has no public book history). A `trade_coverage` row means every print of every ticker watched
during its span was received: a backfill keeps the prints of tickers unwatched after the window began (a market
finalized before its backfill ran used to lose them while the coverage row still claimed the span).

**Coverage manifest** (hourly, atomic): host label (`workspace`/`railway`), session, version and commit,
`read_only: true`, per-lane requests / ok / 429 / errors and request round-trip p50/p95/p99, receive-minus-
`created_time` p50/p95/p99 for prints, minutes sampled, the share of candidate-minutes with a book at most 120 s
old, trade-tape minutes, KXBTC15M minutes with a book at most 5 s old, gaps, storage, and the sealed segments
with their hashes.

## 6. Disk

Default cap 2 GiB (`KALSHI_RECORDER_MAX_STORAGE_MB=2048`), plus a free-disk reserve. The cap counts every file under
`kalshi_recorder/` (segments, index, state, status and manifests). Manifests follow the segments they describe:
under `rotate` those older than every retained segment are deleted, under `protect` only those before the owner's
release date (each manifest's hash stays in the `telemetry` lane). The audit estimated
150-230 MB a day for every lane, so 2 GiB holds about 9-13 days; Family A's 28-day TEST needs about 4.5 GB.
**Before TRAIN starts the owner must choose** a dedicated volume with a cap of at least 4.5 GB, or a nightly
lossless compaction (PROTOCOL.md section 12). At the cap, under the default `protect` policy, the recorder:

1. deletes KXBTC15M (and spot) segments older than `KALSHI_RECORDER_BTC15M_RETENTION_H` (72 h), and LIP and Pyth
   segments older than `KALSHI_RECORDER_LIP_RETENTION_H` (336 h, two weeks), and only while it needs the room;
2. above 95% of the cap, stops KXBTC15M/spot, LIP and Pyth capture (gaps): none of them is a Family A candidate
   (PROTOCOL.md section 12, step 2);
3. at the cap, pauses (a gap). It never deletes unscored Family A evidence. An owner-set
   `KALSHI_RECORDER_RELEASE_BEFORE` date allows Family A segments older than it to go (after a verdict).

`rotate` is a plain ring buffer (oldest first) for use outside the protocol.

## 7. The Family A replay

```bash
python -m nightcrawler.kalshi_familya check  --phase TRAIN --first-day 2026-10-20 --days 7
python -m nightcrawler.kalshi_familya replay --data-dir DATA_DIR --phase TRAIN --first-day 2026-10-20 --days 7 \
    --variant A1 [--model pessimistic | --latency-stress --latency-ms 250 | --day-stop live_style | --unfunded] [--out a1.json]
python -m nightcrawler.kalshi_familya hashes   # the code SHA-256 a FREEZE.json must record
```

Variants `A1`-`A4` and the matched baselines `MB-J`/`MB-I` (section 10). Every run has a kind, printed in its label
and `run_kind`: primary, `--model pessimistic`, `--latency-stress` (with `--latency-ms`), `--day-stop live_style` or
`--unfunded` (one at a time; only primary and pessimistic can enter a verdict). TRAIN and VAL are exactly 7 entry
days and TEST exactly 28. It refuses to score unless `PROTOCOL.md` matches its published hash, and it refuses
TRAIN/VAL entry days that reach a frozen E1. It refuses **TEST** until `research/kalshi_edge_search/family_a/FREEZE.json`
and `FREEZE.sha256` exist, match, name the protocol hash, and:

- the run's variant is the frozen one or its matched baseline (MB-J for A1/A3, MB-I for A2/A4);
- E1 and the 28 entry days match, and `parameters` records `protocol`, `variant`, `first_day`, `days`,
  `latency_ms` (L) and `epsilon_ms`, all equal to the run's (only a latency stress may use another L);
- `code_sha256` equals the SHA-256 of `kalshi_familya.py`, `kalshi_familya_universe.py` and
  `kalshi_recorder_store.py` now (`python -m nightcrawler.kalshi_familya hashes` prints them);
- `frozen_at` (UTC) is at least 1 hour before E1, **and so is git's own record of the freeze**: FREEZE.json must be
  committed exactly as it is on disk, and the last commit that changed it (the later of its author and committer
  times) must be at least 1 hour before E1, because `frozen_at` is only what the file says about itself;
- the FREEZE.json SHA-256 is written in `docs/WORKLOG.md`;
- **the recorder saw the hash first, by its own clock.** Git's dates are set by whoever commits
  (`GIT_COMMITTER_DATE` backdates a commit), so they only catch accidents. Set `KALSHI_RECORDER_FREEZE_SHA256` to
  the FREEZE.json SHA-256 on the recorder service at least 1 hour before E1 (the variable restarts it, and each
  session start writes a `freeze_witness` row with the recording host's time); the last such row at or before
  E1 - 1 h, in the recorder data the run reads, must name this hash. `replay` passes its `--data-dir`; `check
  --phase TEST` needs `--data-dir` too. Only forging hashed recorder segments could get past this.

A TEST account (`FamilyAReplay`) is built only from the permit that check returns, and the permit proves nothing by
itself: `FamilyAReplay` and `tape()` run the check again on the permit's files, so a copied, edited or hand-built
permit is refused, as is one whose FREEZE.json has changed since. Without a TEST permit, no run of any label or
length may have entry days at or after a frozen E1 (the freeze is read from the permit's research directory, else
this checkout's `research/kalshi_edge_search`; an installed copy with no research directory beside it, such as the
Docker image, refuses to build a replay without a permit rather than assume no freeze exists), `tape()` refuses to
read the TEST days' books and prints and never hands one out through its look-backs (the seed books up to 9 days
back, the day of earlier prints for the volume fallback), and `feed()` refuses a TEST-day book or print.

Every run reports **coverage per entry day** (section 12): `entry_days` lists each day's decisions over the markets
passing section 4.1 (counting the fee lookups as fresh, so an outage makes decisions uncovered instead of making
markets vanish), how many were covered (book at most 120 s old, a complete tape over the last 120 s), whether a
market with a resting quote had an unrecovered trade gap, and whether the day is covered (at least 90% of its
decisions and no such gap; a day with no decision over an admitted market is not covered, because a missing
recorder and an empty universe look the same). `covered_entry_days`, `decision_coverage` and `coverage_floor_met`
apply the floors: TRAIN/VAL need 5 of 7 covered days (else `INCOMPLETE_DATA ... the phase restarts on new days`),
TEST 26 of 28 and 90% of all decisions (else `INCONCLUSIVE`), whatever the time of the last tape item.

What it models (with the tests that pin it, `tests/test_kalshi_familya_replay.py`): exact decimals on the market's
`price_ranges` grid; decisions every whole UTC minute from what was received by then; post-only at arrival and on
the first later book; the queue ahead = the larger displayed size, reduced only by prints and by displayed size
falling below it (top 10 levels; a price outside the 10 best at arrival leaves the queue unknown, so no print
reaches us until a book shows our price); fills only from non-block prints selling into our side, after the queue,
in 0.01 steps; inconsistent prints shrink the queue but never fill; a book offering at or below our bid counts once
as a print; cancels and replacements take effect after L (1 s primary), fills inside the cancel race and the
250 ms clock margin count, and the reservation is held until the cancel is acknowledged; Kalshi's direct-account
fee rounding (trade fee up to $0.000001, balance down to $0.0001, per-order accumulator, capped rebates) with the
series fee type and scheduled series/event fee changes in force at each fill; the simulated $2 cluster / $4
outstanding / $3 day / $5 lifetime / cash limits, one quote per cluster, one contract per market; rotation after
6 h without a fill; the 6 h entry cutoff; settlement at the official result, cash at `settlement_ts`;
capital-days; unresolved positions at $0; the 24 h volume fallback sums every recorded print, block trades
included; settlement-day blocks per cluster (the New York date of its last settlement; unresolved positions are
reported outside the blocks, and D then runs to the follow-up end); reconciliation rebuilt from the fill and
settlement ledger (cash, each fill's cash against its fees, fee/rounding/rebate totals, inventory and cost by
market and side, settled P&L, open exposure, day P&L), where any mismatch raises, as a defect, never a result; the
pessimistic model (L >= 2 s, no queue gains from cancellations, trade-throughs fill first, no rebates). Books are
read from 10 minutes before the phase, after each watched ticker's newest earlier book, because the recorder
writes a book only when it changes.

Choices the protocol left open, fixed here before any data exists:

- A market with a partial position gets a quote for the rest (1.00 minus what is held), never the other side.
- A replacement is decided at the minute and sent when the cancel is acknowledged (decision + L), without
  re-checking books that arrived in between (the target was checked at the decision). From the decision to the
  acknowledgement the extra budget it needs is held back from that decision's new quotes (section 5.9: resting
  quotes first). An acknowledged cancel can still fill in the clock margin (until it takes effect + epsilon,
  section 7.4), so it stays in every limit and cash check until it dies (section 6: every possible loss is
  reserved in advance), net of its own live replacement: a late fill of the old order trims the new one to the
  rest (the market never exceeds 1.00 contract), so the pair can cost at most the dearer of the two. The
  replacement's own check uses that dearer price; once it is out, the old order counts only its excess over it, so
  two quotes repriced up one tick at one decision both go out (the old ones add nothing), while budget a
  cancelled-but-fillable order can still use never goes to another quote. Section 6's wording ("held until its
  cancel is acknowledged") and 7.4's margin pull apart here; this reads them the conservative way, and the owner
  may want the protocol text to say so.
- A tape that ends before the last entry day is never `resolution_complete` (`INCOMPLETE_DATA`), and a quote
  still live when the tape ends rested past the end of the tape: it is unidentifiable (section 7.7), so the
  verdict uses the lower bound. A tape that reaches past the last entry day but misses most of them is caught by
  the per-day coverage floor above, not by its end time.
- A settlement is processed when its row is received; its cash and P&L are dated `settlement_ts`.
- Trade-tape coverage for a ticker is exchange-wide coverage while the ticker is watched, or per-ticker backfill.
- The section 7.7 lower bound is the central net minus, for every unidentifiable quote whose side lost or never
  resolved, its remaining size (at most 1.00 contract per market, less what filled) times its price plus maker fee
  plus the $0.0100 rounding pad (limits are not re-run for it). When any quote is unidentifiable, `verdict_net_usd`
  and `verdict_net_per_day_usd_before_opex` are this bound (`verdict_basis: lower_bound_7_7`).

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

## 9. The rewards (LIP) and Pyth lanes (outside protocol v1)

Research: `research/kalshi_rewards/PLAYBOOK.md` and the FX rewards note of 2026-10-13 (settlement source, Pyth
access, request budget). Nothing here trades or scores; it records what a later analysis needs to answer one
question: does Pyth's price move before Kalshi's FX, metals and natural-gas 15-minute books reprice, and how often?
Family A never reads these lanes, and they never write into a Family A lane.

**Switches.** `KALSHI_RECORDER_LIP` (true; the in-bot profile turns it off), `KALSHI_RECORDER_LIP_MAX_PERIOD_S` (900:
a program whose period is at most this is "fast"), `KALSHI_RECORDER_LIP_MAX_PINNED` (40), `..._LIP_PROGRAMS_INTERVAL_S`
(900), `..._LIP_UPCOMING_INTERVAL_S` (3600), `..._LIP_CLOSED_INTERVAL_S` (10800), `..._LIP_SERIES_INTERVAL_S` (600),
`..._LIP_RETENTION_H` (336); `KALSHI_RECORDER_PYTH_BASE` (`https://pyth.dourolabs.app/hermes`, or
`https://hermes.pyth.network`; nothing else is accepted) and `KALSHI_RECORDER_PYTH_CHANNEL` (`real_time`).

**What the LIP lane records.**

- **Programs** (`lip`/`programs`): every liquidity program from `/incentive_programs` (all ~5,600, not only the
  15-minute ones): active every 15 minutes, 5 s after each boundary; upcoming hourly; closed every 3 hours (a program
  leaving the closed list was paid, so the pay lag can be measured). The first snapshot of each status in a session
  and on each UTC day is `full` (every row, raw); the others list only `added`, `changed` and `removed` against the
  snapshot before (lossless: replaying them rebuilds every list exactly), with each page's `body_sha256`.
- **Books** (`books_lip`, and `lip`/`book_call`): the markets of the fast programs, found from that list (today the
  5 FX, copper, platinum, palladium, natural gas and the 5 Coin Race markets: 14), ride in the existing
  `/markets/orderbooks` call from 5 s before their period starts to 2 s after it ends, at most 40, current windows
  first (the overflow is counted, `lip_pins_dropped`). The call then runs on a fixed 1 s grid (Kalshi scores once a
  second), costing no extra request; raw `orderbook_fp`, request and receive time, written when changed and listed
  as unchanged otherwise. The Family A `book_call` row lists only Family A and KXBTC15M tickers (and `lip_tickers`, a
  count); the LIP part of the same call is its own row in `lip`. Family A books displaced from a call by the pins are
  counted (`familya_books_displaced`), and a spare slot refreshes a candidate only when its book is at least 5 s old
  (a short candidate list would otherwise be asked every second).
- **Prints** (`trades_lip`): the exchange-wide tape keeps the LIP markets' prints while they are watched (from the
  pin to `finalized`); `trade_coverage` vouches for them as for every watched ticker.
- **Settlement** (`lip`/`settlement`): the settlement lane's raw rows for those markets (floor strike, expiration
  value, result, `settlement_ts`); watch `start`/`stop` rows are in `lip`, never in `admissions`.
- **The free 1 s settlement series** (`lip`/`series`): `/live_data/events/{event}` for each Pyth-settled series every
  10 minutes. Each reply holds the trailing hour at 1 s, rounded to the settlement digits, and its value at
  `close - 1 s` equalled `expiration_value` in 36 of 36 windows checked; only points newer than the last stored one
  are kept (`new`), an overlapping point whose value changed is listed (`revised`), and a hole (the recorder was down
  over an hour) is a `lip_series_hole` gap. A series with no public live data (Coin Race: 404) is a
  `series_unavailable` row and is asked again a day later.

**The Pyth lane** (`pyth`, `kalshi_recorder_pyth.py`). Only when `PYTH_API_KEY` is in the service's environment
(set by the owner as a Railway variable on `kalshi-recorder`); without it there is no thread, no request and no record,
and one info line says so. Hermes' SSE stream (`/v2/updates/price/stream`, `Authorization: Bearer`) for the nine feeds
Kalshi settles on (EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, copper and natural-gas 24/7 indices, platinum,
palladium), grouped by the fastest channel each feed allows (real_time for EUR, JPY, AUD; 50 ms for the two indices;
200 ms for the rest). Every parsed update is recorded as `[id, price, conf, expo, publish_time, prev_publish_time,
received_at]` (Pyth's integer strings; real price = price x 10^expo; `publish_time` is whole seconds, so a lead under a
second is timed by `received_at`), batched about once a second per stream. A dropped stream reconnects with backoff
(2^n s, at most 60 s, 5 minutes once silent for 10 minutes, straight back after the server's 24-hour close); the
silence from the last update to the next is one `gap` row with the failure that began it. A 401 (key refused) waits
15 minutes and logs an error naming only the status; a 400 or 403 steps the stream down to the next slower channel
(`channel_downgraded`), and a 403 on the slowest waits 30 minutes (the plan lacks those feeds). The key is held in a
`PythKey` that prints as `<redacted>`, is sent only in that header to an allowlisted https Pyth host with redirects
refused, and never appears in a segment, status, manifest or log line: errors are recorded as an exception's type or
an HTTP status, and an error body's 120-character excerpt is redacted first (tested with a server that echoes it).

**Measured from the workspace, 2026-10-14 00:52-00:58 UTC (FX, metals and Coin Race open; no Pyth key):** 528 GETs in
359 s (1.47/s), at most 2 starts in any rolling second, 1 429. The LIP book call carried all 14 markets every time:
358 calls, interval p50 1.000 s, p95 1.003 s, max 1.15 s, none missing. 89% of LIP book reads were a changed book
(4,471 written). Before the token bucket and the hold, target-rate spacing plus round trips gave the same call
every 2.67 s (p50, 129 calls in 331 s, 00:39-00:45 UTC), so "1 s" books were not 1 s. The other lanes still ran (trades 0.27/s,
discovery 0.14/s, LIP lane 0.033/s).

**Storage estimates (gzip on disk).**

| Lane | Estimate | Basis |
|---|---|---|
| `books_lip` | about 140 MB a day on a full weekday, about 110 MB a day averaged over a week | measured: 129 B per changed book, 89% of 14 books a second; FX, metals and gas close part of the week |
| `trades_lip` | about 15-25 MB a day | measured 17.6 MB a day at that hour's FX and Coin Race volume |
| `lip` | about 10 MB a day | book-call rows (~5), program snapshots (one full list of each status a day plus diffs, ~2), the 1 s series of 9 feeds (~3) |
| `pyth` | about 7 MB a day at 1 update/s per feed, 30 at 5/s, 110 at 20/s (all 9 feeds streaming all day) | the real store path on synthetic updates: 7-9 B per update |
| side effect | KXBTC15M books (`books_btc15m`) about 2.7 times as often as before | the book call now really runs every second |

So the LIP lanes add about 150-200 MB a day before Pyth, about 2-3 GB over their two-week retention. They are
sheddable (stopped above 95% of the cap, deleted past their retention only when room is needed), so they can never
make Family A pause sooner; but on a 5 GB volume already holding about 1 GB a day the owner must choose a larger
volume or cap, a shorter `KALSHI_RECORDER_LIP_RETENTION_H`, or `KALSHI_RECORDER_LIP=false`.

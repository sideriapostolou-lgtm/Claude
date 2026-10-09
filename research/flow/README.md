# research/flow: on-chain trade-flow data from CryptoHouse

This folder builds the wave-2 trade-flow dataset (PLAN §6) from **CryptoHouse**, the free public ClickHouse
run by Goldsky and ClickHouse. It needs no API key and does not touch pump.fun's swap-api, whose rate limit
belongs to another collector.

- **Data location.** The data lives in the session scratchpad, which is not committed:
  `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/flow/`. Below it is
  called `FLOW`.
- **What is research-only.** Nothing here is wired into the bot. Do not import it from `src/`.

| File | What it does |
|---|---|
| `cryptohouse.py` | Quota-aware HTTP client. It keeps a persisted query log, a cross-process lock, a rolling-hour budget, error-specific backoff and JSONCompact parsing. |
| `decode.py` | Event discriminators and byte offsets, Python decoders that mirror the SQL, base58, and safe SQL rendering. |
| `sql/curve.sql` | Graduates: completion, creation, curve-life and launch features, and the canonical pool. One row per graduate. |
| `sql/b2.sql` | B2 server-side PumpSwap aggregates: clock-minute bars, AGENT candidates and the first 120/300 s after graduation. One row per pool per chain hour. |
| `sql/b3.sql` | B3 per-(wallet, coin) position summaries, packed one row per coin. |
| `sql/raw.sql` | Raw trades from the curve and PumpSwap with tx signatures and full fields, packed per coin. Used by validation. |
| `sql/b1c.sql` | B1 raw trades for P4b: one row per **piece** (a coin's window cut to a ≤ 30-minute slab), compact 43-byte tuples, no wallet dictionary, no trade cap, an overflow guard. |
| `b1c.py` | P4b: per-minute trade estimator, sweep packer, unit runner (split on error, resume from the residual), decoder and B1 consolidation. |
| `run_b1.sh` | One command: waits for the running P1, finishes discovery down to TRAIN, then B1 TRAIN → VAL → TEST. |
| `sql/b1.sql` | Old P4 coin-batch template (slim tuples + wallet dictionary). Not run: P4 cannot reach the 95 % coverage gate. |
| `sql/slot_map.sql` | Slot ↔ time anchors from `solana.blocks`, at 15-minute granularity. |
| `backfill.py` | Resumable phases P1-P3 and P4b. It checkpoints after every query and consolidates the results to Parquet. |
| `features.py` | Offline helpers: AGENT detection, B2 merging across chunks, and price repair. |
| `validate.py` | Gates V0-V7. It writes `FLOW/VALIDATION.md` and `FLOW/validation.json`. |
| `tests/` | Offline pytest. The fixtures are real CryptoHouse rows from 2026-10-08, plus the matching swap-api launch trades. |
| `collect_trades.py`, `dune.py` | Older swap-api collector and Dune client. Not used here. |

## Running

```bash
# P1: graduates + launch features + B2 for the last 7 days.
# The census day runs first, then whole days going back.
python research/flow/backfill.py --phase P1 --days 7 --out $FLOW [--max-minutes 80] [--max-queries 200]

# P2: the same, extended to 21 days. U_ext starts on 2026-09-16; done hours are skipped.
python research/flow/backfill.py --phase P2 --days 21 --out $FLOW

# P3: B3 wallet summaries for every graduate found by P1/P2.
python research/flow/backfill.py --phase P3 --out $FLOW [--b3-batch 12]

# P1 down to an absolute start (hour-aligned), never past --until (hours outside every split are skipped)
python research/flow/backfill.py --phase P1 --since 2026-10-01 --until 2026-10-09 --out $FLOW
python research/flow/backfill.py --check-discovery --since 2026-10-01 --until 2026-10-09 --out $FLOW  # exit 0 = done

# P4b: B1 raw non-dust trades (>= 0.01 SOL) over [c_ts, g + 120 min) for the lab2 S1 universe, TRAIN first.
python research/lab2/b1_select.py                      # FLOW/b1_select.json (re-run after every consolidation)
python research/flow/backfill.py --phase P4b --splits train,val,test --out $FLOW [--dry-run] [--retry-errors]

# Everything above in one command (waits for a running P1/P2/P3; see "B1 (P4b)" below)
bash research/flow/run_b1.sh

# Rebuild the Parquet tables from the raw chunks. Offline; no queries.
python research/flow/backfill.py --consolidate --out $FLOW

# Validation gates. Uses about 10 queries for raw launch windows; cached under FLOW/validation/.
python research/flow/validate.py --out $FLOW [--max-hours 10] [--offline]

# Tests (offline)
python -m pytest -q research/flow/tests
```

- **Stopping and resuming.** Every phase can be stopped at any time with Ctrl-C, `--max-minutes` or
  `--max-queries`. A rerun continues from `FLOW/state.json` (P1-P3) or `FLOW/state_b1.json` (P4b). Each query
  result is written to `FLOW/raw/<kind>/*.json.gz` before the state is updated and before the next query is sent.
- **One process per state file.** P1-P3 hold `FLOW/state.lock` and P4b holds `FLOW/state_b1.lock`; a second process
  on the same state file waits (each one rewrites its state file whole). P1 and P4b may run together.
- **Consolidation is atomic.** Every Parquet table is written to a temporary file and moved into place
  (`os.replace`) under an exclusive `flock` on `FLOW/consolidate.lock`, so readers never see half a table.
- **The query log is the budget.** `FLOW/ch_query_log.jsonl` holds one line per request, whether it
  succeeded or failed, with its timing, rows read and error code. Restarts and parallel processes (the
  backfill, `validate.py`, the CLI) read this log, so they respect the same rolling-hour budget. Set
  `CH_QUERY_LOG` to share it with other tools.
- **One query at a time.** A machine-wide `flock` keeps a single query in flight.
- **Checking the budget.** `python research/flow/cryptohouse.py --usage` prints the budget, and
  `FLOW/manifest.json` has coverage and query stats.

### Budget and error policy (`cryptohouse.py`)

| Limit or error | Behaviour |
|---|---|
| Rolling-hour budget | At most 90 queries and 4,500 s of execution in any 3,600 s (`Budget`). The server allows 120 and 6,000 s per **client IP**. The IP is this environment's proxy egress, which is shared and has been seen to rotate: .131, .132 and .140. |
| `QUOTA_EXCEEDED` (201) | Sleep until the "interval will end at" time in the error, otherwise to the top of the next hour, then retry. At most 3 waits. |
| `TIMEOUT_EXCEEDED` (159) | Raised to the caller. `backfill.py` halves the chunk in time; the minimum chunk is 15 minutes. |
| `TOO_MANY_ROWS_OR_BYTES` (396 / 158 / 307 / 241) | Raised to the caller. `backfill.py` halves the pool or coin batch. |
| Network errors, 5xx, 202 | Exponential backoff of 5 → 10 → 20 → 40 s, 4 retries. |

### Measured cost (pilot, 2026-10-08)

Server time for the **same** query varied 3-7x within an hour: the service is shared. Timeouts happen,
and chunks are split automatically when they do.

| Query | Covers | Execution (median / p90) | Notes |
|---|---|---|---|
| `curve.sql` | 1 chain hour, plus a 30-minute lookback | 33 s / 60 s | ~150-300M rows read; 7 of 46 timed out and were split |
| `b2.sql` | 1 chain hour, ~160-260 active pools | 23 s / 60 s | One query per hour since the batch cap was raised to 260; 5 of 41 timed out and were split |
| `b3.sql` (P3 test) | 6 busy coins, [created, g + 60 min] | 8.7 s | ~10k wallets ≥ 0.01 SOL; just under the 1 MB cap. P3 now keeps wallets ≥ 0.05 SOL |
| `b1.sql` (P4 test) | 3 organic coins, [created, g + 120 min] | 22 s | 7,721 non-dust trades: 1.07 MB of **JSON**, ~0.58 MB native. The 1 MB cap counts native (in-memory) bytes, not JSON |
| `b1.sql` (P4 sizing, 2026-10-09) | 13 coins, 2.75 h of chain time | 60.4 s **timeout** | 243 M rows read; P4 cannot work at 3-4 M rows/s |
| `b1c.sql` tail (M2 / M4, 2026-10-09) | one 30-minute slab, 12 / 23 pieces | 15.0 s / 4.9 s | 52-53 M rows read; 17,969 / 19,937 trades = 867 / 994 kB native (passed) |
| `raw.sql` (validation) | ~8 coins × 2 minutes | 3-47 s | |
| `slot_map.sql` | 18 days | ~1 s | |

**Pilot (2026-10-08 20:26-21:46 UTC):**

- 89 backfill queries covered the census day: curve 10-07 16:00 → 10-08 20:00, B2 10-07 19:00 → 10-08 20:00.
- That is **3.1 queries and ~100 s of wall time per chain hour**, i.e. ~29 chain hours per wall hour. At
  that pace the 90 queries/hour budget is what limits throughput.
- **Realistic ETAs at 90 queries/hour:**

  | Phase | Queries | Hours |
  |---|---:|---:|
  | P1, 7 days | ~520 | ~5.7 (~4.6 still to go) |
  | P2, 21.8 days in total | ~1,600 | ~18 |
  | P3, 21.8 days (60-minute horizon, ~12 coins/query) | ~2,400 | ~28 |
  | P4b (B1), TRAIN 10-01 → 10-05 (S1 universe, compact tuple, ~2.8 queries per hour of coin creation) | ~311 (230-360) | ~3.5 |
  | P4b (B1), VAL 10-05 → 10-06 12:00 | ~86 | ~1 |
  | P4b (B1), TEST 10-06 12:00 → 10-07 19:37 (418 coins, 2.31 M trades; `--dry-run`: 117 units) | ~123 | ~1.4 |

  The old P4 (coin batches of 4) needed ~7.5 queries per chain hour, ~1,290 for TRAIN-TEST, and timed out on every
  query at 3-4 M rows/s. It is disabled (`--phase P4` exits with code 2).

- `FLOW/pilot_report.json` and `manifest.json` have the measured numbers.

## Output tables (`FLOW/*.parquet`, built by `--consolidate`)

All times are UTC epoch seconds. SOL amounts are in SOL; token amounts are whole tokens (6 decimals
removed).

- **User-side SOL.** "User-side SOL" is what the trader paid on a buy, fees included, or received on a
  sell, fees deducted.
- **swap-api convention.** swap-api's `amountSol` is net of fees on buys. To compare, subtract `pfee`,
  `cfee` and `lp_fee`.

### `graduates.parquet`: one row per curve that completed (`sql/curve.sql`)

| Column | Meaning |
|---|---|
| `mint`, `g_slot`, `g_ts` | Graduation = the `CompleteEvent` block time, accurate to the second. |
| `completer` | `CompleteEvent.user`, the wallet whose buy completed the curve. |
| `rsol_complete` | Real SOL in the curve at completion: ~85 for normal coins, < 80 for Mayhem. |
| `c_slot`, `c_ts`, `has_create` | Creation. `has_create = 0` means the `CreateEvent` lay before the 30-minute lookback, so the curve-life and launch features are partial or empty. |
| `creator`, `create_user`, `name`, `symbol`, `uri`, `token_program` | From `CreateEvent`. |
| `is_mayhem`, `mayhem` | `CreateEvent.is_mayhem_mode`. `mayhem` = that flag OR `rsol_complete < 80`. |
| `curve_quote_mint` | `11111111111111111111111111111111` means native SOL. |
| `vsol0` | Initial virtual SOL: 30 for SOL curves. |
| `grad_delay_s` | `g_ts − c_ts`. |
| `curve_buy_sol`, `curve_sell_sol`, `curve_buy_tok`, `curve_sell_tok`, `curve_n_buys`, `curve_n_sells` | Over the whole scanned curve life. |
| `curve_n_buyers`, `curve_n_sellers` | Distinct wallets with ≥ 0.01 SOL. |
| `curve_top1_buy_sol`, `curve_top3_buy_sol` | Curve buy SOL of the top 1 and top 3 wallets. Divide by `curve_buy_sol` for the G1 shares. |
| `completer_sol`, `completer30` | Largest buyer, and its SOL, among buys made while real SOL ≥ 55 (the last 30 SOL; PLAN COMPLETER). |
| `l_*` | Launch window, the first 120 s after creation, on the curve: buy/sell SOL and tokens, number of buys/sells, distinct buyers/sellers (≥ 0.01 SOL), distinct wallets, top-3 buy SOL, max real SOL. |
| `l_bundle_slots`, `l_max_buyers_slot` | Slots with ≥ 2 distinct buyers, and the most buyers in one slot. |
| `z_n_buyers`, `z_n_buyers_noncreator`, `z_buy_sol`, `z_buy_tok` | Creation-slot buys (BUNDLE). G1 `bundle_share` = `z_buy_tok / 793.1e6`. |
| `sn60_n_buyers`, `sn60_buy_sol` | Non-creator buyers in the first 60 s (SNIPER). |
| `creator_buy_sol`, `creator_sell_sol`, `creator_buy_tok`, `creator_sell_tok`, `l_creator_*` | Creator buys and sells, over the curve life and over the launch window. |
| `first20_buy_sol` | Curve buy SOL of the first 20 distinct buyers. Ties inside a slot are broken by wallet bytes. |
| `pool`, `pool_slot`, `pool_ts`, `pool_quote_mint`, `pool_creator`, `pool_base0`, `pool_quote0`, `n_pools` | Canonical PumpSwap pool: the first `CreatePool` with base = mint. `sol_quoted` = quote is WSOL. |

### `b2_bars.parquet`: one row per (pool, clock minute) in [g, g + 180 min) with ≥ 1 trade (`sql/b2.sql`)

| Column | Meaning |
|---|---|
| `mint`, `pool`, `g_ts`, `minute_ts` | `minute_ts` is the start of a clock minute. |
| `minute_idx` | Minutes since the graduation minute; the graduation minute is 0 and is partial. |
| `n_buys`, `n_sells`, `n_dust` | Trades; dust is < 0.01 SOL. |
| `buy_sol`, `sell_sol`, `buy_tok`, `sell_tok` | User-side SOL and tokens. |
| `n_buyers`, `n_sellers`, `top5_buy_sol` | Wallets with ≥ 0.01 SOL in the minute, and the top 5 buyers' SOL. |
| `open`, `high`, `low`, `close` | SOL per whole token from pool reserves. `open` is the price before the minute's first trade; the others are after trades. |
| `x_close`, `y_close` | Real SOL and token reserves after the last trade. |
| `agent_buy_sol` | SOL bought by the detected AGENT in this minute. |
| `price_repaired` | 1 = the price was rebuilt from the reserves (see caveats). |

- **Price.** Price = (x + virt) / y, where `virt` is the pool's virtual quote reserve (see caveats).
- **Intra-slot order** is (slot, tx index in the block, parent index, index). It comes from
  `transactions_non_voting.index`.

### `b2_coins.parquet`: one row per graduate pool

| Column | Meaning |
|---|---|
| `virt_sol` | The pool's virtual quote reserve (median over chunks). |
| `n_chunks` | Chain hours merged. |
| `w120_*`, `w300_*` | The first 120 s and 300 s after g: buy/sell SOL, distinct buyers/sellers (≥ 0.01 SOL), and the top-10 buyers as JSON `[wallet, buy_sol, sell_sol]`. |
| `w_exact` | 0 = the 300 s window straddled two chain hours: sums are exact, counts are a lower bound and the top lists are per part. |
| `w120_top5_share_ex_agent` | G1 `amm_top5_share_2m` with the AGENT removed. |
| `agent_present`, `agent_wallet`, `agent_slices`, `agent_sol`, `agent_median_gap`, `agent_gap_cv`, `agent_first_offset_s` | Detected AGENT. |
| `agent_known_at` | The AGENT's 4th buy. **Do not use the AGENT role before this time.** |
| `grad_delay_s` | As in `graduates.parquet`. |

**AGENT rule.** A pool wallet with ≥ 4 buys in [g, g + 420 s), no sells, a median gap of 11-13 s, and
**≥ 60% of gaps within 10-14 s**. For a decision at t, call `features.detect_agent(..., as_of=t - 20)`; the
stored `agent_*` columns use the whole window and are not causal.

- **Why not the PLAN's rule.** PLAN §3.2 asks for a gap coefficient of variation < 0.15. On real data one
  skipped 12 s slice creates a 24 s gap and pushes the CV to 0.2-0.4, so the PLAN's rule missed 26% of BOOST
  agents on the census night. `b2_coins.agent_plan_rule` records whether the PLAN's rule also matched.
- **Server and offline split.** `b2.sql` only pre-filters candidates (≥ 2 buys, no sells, median gap
  9-15 s). `features.detect_agent` applies the rule after merging the chunks.
- **Observed on 2026-10-08 (audit, raw events of 5 graduates):** BOOST makes **29-30 fee-free slices** and
  spends **exactly 17.5845 SOL**; first buy 1-4 s after g, gap 12 s, last slice at g + 341-353 s. The pilot's
  "28 slices / 16.2 SOL" came from the old 330 s window, which cut off the last 1-3 slices.

### `b3_positions.parquet`: one row per (wallet, coin) with ≥ 0.05 SOL of volume (`sql/b3.sql`)

The window is [created, g + 60 min]. Change it with `--b3-horizon-min`; 180 doubles the cost and times out
more often. Columns:

- `wallet_h` = `cityHash64` of the raw 32-byte key. It is stable across queries and the registry key.
- `wallet` = the base58 address, only for wallets that bought ≥ 0.5 SOL. Otherwise `''`, to stay under the
  1 MB cap.
- `n_buys`, `n_sells`, `buy_sol`, `sell_sol`, `buy_tok`, `sell_tok`, `curve_buy_sol`, `curve_sell_sol`;
- `first_ts`, `last_ts`, `first_buy_ts`, `last_sell_ts`;
- `peak_tok` and `end_tok`, from the running position in chain order;
- `orphan_tok` = tokens sold beyond the wallet's holding at that moment (PLAN orphan_part, a TRANSFEREE
  signal);
- `n_sell_without_holding`.

**Per-coin aggregates over all wallets, dust included.** Each raw chunk row also has `n_buyers_all`,
`n_sellers_all`, `n_orphan_sellers`, `orphan_seller_sell_sol`, `orphan_tok` and `n_sell_only_wallets`.

> **Finding from the P3 test (6 census coins, first hour).** Factory coins (self-graduated in the creation
> slot: FOMO, Open AI, Mr Beast, Coinbase) had **1,545-2,149 wallets that sold tokens they never bought**.
> Most sold ~360k-465k tokens each, and only 38-392 wallets bought. The two organic coins had 20-25 such
> wallets. The creator side spreads supply across thousands of wallets that dump into the pool. That is
> the insider-distribution and TRANSFEREE signal of V1/S1, and it is visible within minutes.

**Using it for reputation (PLAN §6.6).** A row summarises the whole window, so a decision at t may use it
only if the coin's window ended before t − 20 s. Never use rows of the coin being traded. Treat a position
as closed only when `end_tok` ≤ 1% of `peak_tok`. A position still open when the window ended is censored:
it contributes nothing (PLAN §6.6 rule 2), and must never be scored as realized at the window end.

**Wallet identity.** `user` in curve and PumpSwap events is the token-account authority, not the transaction
signer. Some are pooled program accounts: `ARu4n5mF…` signs with a different user on every trade and sits in the
first-5-minute top-10 buyers of 227 of 1,444 pools. Exclude such accounts from registries, repeat-buyer counts
and orphan/TRANSFEREE logic, or attribute trades to the fee payer.

### B1 (P4b): `b1_trades.parquet`, `b1_coins.parquet`, `b1_manifest.json`

**Who reads B1.** lab2 S1 (checkpoints g + 6 … g + 120 min) and D1 (decisions at tau in [g + 600, g + 7180], flow
exits up to g + 7200). Both refuse tau ≥ g + 7200 and need every trade from creation (curve roles, insider ledgers,
orphan sells).

**Selection** (`research/lab2/b1_select.py` → `FLOW/b1_select.json`): the S1 universe of each split = lab2 usable
(SOL-quoted, not Mayhem, virtual reserve known, B2 window complete under `completeness_from_flow`) ∧ creation
scanned ∧ `created_exact` ∧ `grad_delay_s` > 5. It is exactly the denominator of `s1.coverage_counts` and of
`d1.b1_coverage` (D1's ORGANIC universe lies inside it). Window [c_ts, g_ts + 7200). Every filter is a
graduation-time fact. Counts and windows only; re-run it after every consolidation.

**How P4b fetches** (`b1c.py`, `sql/b1c.sql`):

- **Estimate** trades per (coin, clock minute) offline: pool = B2 `n_buys + n_sells − n_dust` (exact on the pilot);
  curve = 0.95 × (`l_n_buys + l_n_sells`) over [c, c + 120 s) and the rest of 0.95 × (`curve_n_buys +
  curve_n_sells`) spread over [c + 120, g). Slab totals were within 1-2.5 % of the truth.
- **Pack**: sweep the minutes in time order, every active coin in mint order, 43 B per estimated trade + 60 B per
  piece with trades; close the unit before it would pass 920 kB or when its span reaches 30 min. Each coin's window
  becomes consecutive pieces with no gap and no overlap. Units run split by split in the order given (TRAIN first).
- **Packing is on the residual** (window minus pieces already fetched, from `state_b1.json`), so a restart, a
  `--retry-errors` or a newly selected coin only fetches what is missing.
- **Errors**: `ResultTooLarge` splits the unit at its time midpoint (inside one minute: by coin halves).
  `QueryTimeout` splits at the 15-minute anchor nearest the middle; a unit inside one anchor is retried later (3
  times per coin, then the coin is an error: splitting cannot reduce the rows read). `n_overflow > 0` marks the coin.
- **Cost**: a 30-minute slab reads ~53 M rows (5-18 s measured, ≤ 38 s at 2.9 M rows/s); ~2.8 queries per hour of
  coin creation. `--dry-run` prints the plan (units, estimated MB and trades per split) without a query.

**Compact tuple** (43 B; the old one was 68 B): `slot` UInt32, `tx_idx` UInt16, `pix` UInt8, `ix` UInt8,
`ts − lo` UInt16, `venue + 2·is_buy` UInt8, `wallet_h` UInt64, `usol` µSOL UInt32, `tok` whole tokens UInt32,
`x0` Float32, `y0` whole tokens UInt32, `fees` µSOL UInt32, `virt` k-lamports UInt32. Checked against the
old-format pilot rows of the same trades: keys, ts, venue, side and wallet identical; usol and fees ≤ 1e-6 SOL,
tok and y0 ≤ 0.5 token, x0 relative ≤ 1e-7 (`tests/test_b1c.py`).

**`b1_trades.parquet`**: same schema as before, one row per non-dust trade (≥ 0.01 SOL), **complete coins only**
(fetched pieces cover [c_ts, g_ts + 7200)), sorted by mint then (slot, tx_idx, pix, ix), duplicate keys dropped:

| Columns | Meaning |
|---|---|
| `slot`, `tx_idx`, `pix`, `ix` | Total chain order and unique key. |
| `ts`, `mint` | |
| `venue` | 0 = curve, 1 = PumpSwap. |
| `is_buy`, `wallet_h`, `usol` | `wallet_h` = `cityHash64` of the raw 32-byte user key (uint64). `usol` in lamports, user-side (µSOL precision). |
| `tok` | Raw units, 6 decimals (whole-token precision). |
| `x0`, `y0` | Reserves **before** the trade. Curve: virtual SOL/token. PumpSwap: real quote/base. |
| `fees` | Lamports: protocol + creator + LP (µSOL precision). |
| `virt_ksol` | PumpSwap virtual quote reserve / 1000 lamports in force before each pool trade, buys and sells. |
| `src` | 0 = CryptoHouse. |

- **Price before the trade:** (x0 + virt_ksol × 1000) / y0 (lamports per raw token). Fills use X = x + v.
- **Virtual reserve at piece starts.** The SQL carries `virt` along each piece's pool chain, so pool sells before a
  piece's first buy come back 0; consolidation forward-fills them from the coin's previous value (19 of 16,327
  pool trades in M2; the error is far below 0.1 % of price). Rows before the coin's first non-zero value stay 0.
- **No `wallet_dict.parquet`.** S1 and D1 hash pooled accounts locally (`s1.pooled_hashes`), so they never needed it.
- **No trade cap.** `s1.B1_MAX_TRADES` / `d1.B1_MAX_TRADES` are `None` (the old 20,000 cap skipped the late
  checkpoints of the 3.4 % busiest coins, a non-random subset).

**`b1_coins.parquet`**: one row per fetched or selected coin: `split`, `selected`, `lo`/`hi` (the window),
`complete`, `missing_s`, `pieces` (JSON list of the fetched [lo, hi) intervals), `n_pieces`, `n_chunks`,
`overflow_pieces`, `n_trades`, `n_pool_trades`, `n_dup_dropped`, `n_virt_ffilled`, and the **B1 = B2 gate**:
B1 pool trades per clock minute vs B2's non-dust count over the minutes fully inside [g, g + 7200)
(`gate_b1_pool`, `gate_b2_pool`, `gate_abs_diff`, `gate_ok` = difference ≤ 0.5 %; expected exact).

**`b1_manifest.json`** (written at every consolidation): per split, selected / complete coins and the fraction
(S1 and D1 need ≥ 95 %), incomplete coins, coins with overflow, gate flags, trades. **`b1_progress.json`** (written
by each P4b run): fetched / errors / units left per split before and after the run, and the run's query counts.

`sql/raw.sql` has the same selection, with tx signatures, base58 wallets and full fee fields. It is used by
`validate.py` and by ad-hoc pulls.

### Other files in `FLOW`

| File | Contents |
|---|---|
| `manifest.json` | Coverage: graduates, with creation, with pool, Mayhem, curve and B2 hours done and their spans, B3/B1 coins, errors, and query stats by tag. |
| `state.json` | Resumable state of P1-P3: done hours and parts, pools done per B2 hour, and errors. |
| `state_b1.json` | Resumable state of P4b: fetched intervals per coin (`b1c.cov`), coin errors (`b1c.err`), timeout counts, and one record per unit (estimated vs actual bytes, exec time). |
| `b1_select.json` | The P4b selection (lab2 S1 universe per split, windows, counts). |
| `b1_manifest.json`, `b1_progress.json`, `run_b1.log` | B1 coverage per split, P4b run progress, the `run_b1.sh` log. |
| `consolidate.lock`, `state.lock`, `state_b1.lock`, `run_b1.lock` | `flock` files (see "Running"). |
| `slotmap.json` | Slot anchors per 15 minutes. |
| `raw/<kind>/*.json.gz` | The verbatim query results with their parameters. They are append-only, and the source of truth for `--consolidate`. |
| `ch_query_log.jsonl` | The query log. |
| `VALIDATION.md`, `validation.json` | Gate results. |

## Caveats strategy researchers must know

### 1. Failed transactions are in `solana.instructions`

Events from failed transactions appear as trades that never happened. On 2026-10-08 they were 2.6-4.4% of
PumpSwap events, ~0.7% of curve trades and ~4% of `CreateEvent`s.

- **What the templates do.** Every template keeps only `solana.transactions_non_voting.err = ''`.
- **`token_transfers` also contains failed transactions,** so it is only a prefilter.

### 2. PumpSwap virtual quote reserve

The pool prices with **x + virt**, not with the emitted quote reserve x.

- **Where it is.** `virt` is a u64 that only Buy events carry, at byte `446 + len(ix_name)`. It starts at
  17.584505289 SOL on 2026-10 migration pools and is **not constant**: between trades x and v move by opposite
  amounts (X = x + v is conserved, verified exactly on 3,981 transitions). Price and fills must use the v in force
  at that trade (carried through sells along the chain), never a per-pool constant. A constant v mis-priced
  closes by up to 0.42 % within 45 minutes.
- **What goes wrong without it.** Ignoring it under-prices fresh pools by ~7%, and by more as the pool
  drains. It is also why dumped graduates "floor" at ~17.6 SOL market cap.
- **Pools with no buy in a chain hour.** Their bars come back with virt = 0. `--consolidate` repairs the
  close exactly from `x_close`/`y_close` and scales the open, high and low (`price_repaired = 1`).
- **Before using it on September data,** check that the field exists and is constant there. It is read only
  when 0 < virt < 100 SOL.

### 3. Reserve semantics

- **PumpSwap** Buy and Sell events carry **pre-trade** reserves (V5).
- **Curve** TradeEvents carry **post-trade** virtual reserves.
- **Mayhem curves** change their SOL reserve outside TradeEvents, so their reserve chain breaks by design.
  Mayhem coins are not tradeable; exclude them.

### 4. Event layouts change over time

- **What changes.** Events grow fields at the end, and `ix_name` is a variable-length string in the middle
  of Buy events (`buy`, `buy_exact_quote_in`, `buy_exact_quote_in_v2`, …).
- **What is stable.** The leading fields used here kept their offsets through October 2026. The templates
  use wide `length(data)` windows (`decode.LEN_RANGES`).
- **What to check.** Before trusting a new month, run `validate.py` and spot-check `tests/test_decode.py`
  against a few fresh rows. In particular, check September 2026 for the virtual-reserve field and the
  CreateEvent `is_mayhem_mode` / `quote_mint` tail.

### 5. BOOST and AGENT

- BOOST started on 2026-07-21, so every U_ext coin (from 2026-09-16) is in the BOOST era.
- AGENT detection is a fingerprint (12 s cadence, no sells). It is not an address list: the address
  differs on every coin.
- If V7 drifts (presence, slice count, SOL), treat it as a **policy change** and re-check S1.

### 6. Shared and variable quota

- **Shared quota.** The quota key is the proxy egress IP, which other sessions may share and which has been
  seen to rotate.
- **Variable timing.** Server time for one query varied 3-7x within an hour.
- **Planning.** Plan with the ETAs in the pilot report, not the best case. If `QUOTA_EXCEEDED` appears
  while our own log shows < 90 queries, someone else is using the IP.

### 7. Coverage limits of P1

- **Launch and curve-life features are exact only when `has_create = 1`.** That requires creation within
  30 minutes before the graduation hour. On the pilot 88 of 1,233 tradeable graduates (7 %; 17 % of the
  non-instant ones that G1/S1 care about) have `has_create = 0`: launch, bundle, sniper and creator columns are
  NULL (patched consolidate) and curve-life totals are partial (`curve_partial = 1`).
- **The B2 windows** (`w120`, `w300`) are exact only when [g, g + 330 s) lies inside one chain hour
  (`w_exact`). Otherwise their sums are exact and their counts are approximate.
- **The last 3 hours before a run** have incomplete [g, g + 180 min) windows. A later run that extends the
  range fills them in, because B2 hours are keyed by hour and pool.

### 8. No lookahead (PLAN §3.2, §6.6)

These tables are storage, not features.

- **Bars.** Per-minute bars are complete only for minutes that ended before the decision: use
  `features.bars_asof(bars, tau)`.
- **Early windows.** `w120_*` is usable only from t = g + 140 s and `w300_*` from g + 320 s (τ = t − 20 s).
- **Not features.** `n_chunks`, `n_pools`, `b2_coins.virt_sol` and repaired prices are built from data after g
  (survival, later pools, later chunks).
- **Graduation-time features.** `graduates.parquet` columns about the curve are known at `g_ts`. The
  completion-time ones (`completer*`, `rsol_complete`) are known only at `g_ts`, never before.
- **Reputation.** Use only coins whose window **ended** before the decision.
- **The `features(mint, tau)` function** must recompute from `b1_trades` / `b2_bars` with
  ts ≤ τ = t − 20 s.

### 9. Conventions

- `usol` is user-side SOL. swap-api's `amountSol` mixes conventions by instruction. We measured this on
  24k trades matched by transaction:

  | swap-api trade | `amountSol` equals |
  |---|---|
  | PumpSwap sells and `buy` instructions | User-side SOL (our `usol`) |
  | PumpSwap `buy_exact_quote_in` (and `_v2`) | Net of all fees (`usol − pfee − cfee − lp_fee`) |
  | Curve buys and sells | The curve's `sol_amount`: fees excluded on buys, included on sells |

  `validate.net_swap_sol` converts trade by trade. Mixing conventions shifts SOL totals by ~1.1-1.25%.
- Prices are in SOL. Join minute SOL/USD (`LAB/sol_usd.json`, or Coinbase/Binance klines) for USD.
- **Non-SOL-quoted coins** (USDC, WLD, `pumpCm…` and others; ~8% of graduates): identify them by
  `pool_quote_mint`, which comes from CreatePool and is reliable.
  - Their curve events use another tail layout. `rsol_complete` reads 0, `curve_quote_mint` is garbage,
    and curve SOL features are in quote units or invalid.
  - Their PumpSwap prices are in quote units.
  - Exclude them, as the lab does (`sol_quoted = False`).

### 10. Transaction version 1

Transaction v1 activated on 2026-09-15 at slot 447,120,000. CryptoHouse includes v1 transactions; nothing
here depends on the version.

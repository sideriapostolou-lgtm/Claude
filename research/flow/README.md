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
| `sql/b1.sql` | B1 raw trades for P4 in slim tuples: no tx signature, wallets as `cityHash64` plus a per-coin dictionary. |
| `sql/slot_map.sql` | Slot ↔ time anchors from `solana.blocks`, at 15-minute granularity. |
| `backfill.py` | Resumable phases P1-P4. It checkpoints after every query and consolidates the results to Parquet. |
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

# P4: B1 raw non-dust trades (>= 0.01 SOL), [created, g + 120 min], for tradeable non-factory coins
#     (SOL-quoted, not Mayhem, graduated more than 5 s after creation).
python research/flow/backfill.py --phase P4 --out $FLOW [--raw-batch 6]

# Rebuild the Parquet tables from the raw chunks. Offline; no queries.
python research/flow/backfill.py --consolidate --out $FLOW

# Validation gates. Uses about 10 queries for raw launch windows; cached under FLOW/validation/.
python research/flow/validate.py --out $FLOW [--max-hours 10] [--offline]

# Tests (offline)
python -m pytest -q research/flow/tests
```

- **Stopping and resuming.** Every phase can be stopped at any time with Ctrl-C, `--max-minutes` or
  `--max-queries`. A rerun continues from `FLOW/state.json`. Each query result is written to
  `FLOW/raw/<kind>/*.json.gz` before the next query is sent.
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
| `curve.sql` | 1 chain hour, plus a 30-minute lookback | ~20 s / ~55 s | ~190-300M rows read. About 1 in 7 hours timed out and was split |
| `b2.sql` | 1 chain hour, ~180-260 active pools | ~17 s / ~56 s | One query per hour since the batch cap was raised to 260 (~0.6 MB of result) |
| `b3.sql` (P3 test) | 6 busy coins, [created, g + 60 min] | 8.7 s | ~10k wallets ≥ 0.01 SOL; just under the 1 MB cap. P3 now keeps wallets ≥ 0.05 SOL |
| `b1.sql` (P4 test) | 3 organic coins, [created, g + 120 min] | 22 s | 7,721 non-dust trades; just under the 1 MB cap, so ~3-4 coins per query |
| `raw.sql` (validation) | ~8 coins × 2 minutes | 3-47 s | |
| `slot_map.sql` | 18 days | ~1 s | |

**P1 throughput:**

- About 2-4 queries per chain hour (curve + B2, including splits) and 1-2 minutes of wall time.
- That is roughly **20-30 chain hours per wall hour**, which sits at the 90 queries/hour budget.
- **Realistic ETAs:** P1 for 7 days ≈ 6-8 h; P2 to 21.8 days ≈ 18-24 h in total.
- **P3** (60-minute horizon, ~12 coins/query): ~100 queries per chain day ≈ 24-26 h for 21.8 days.
- **P4** (tradeable non-factory coins only, ~3.5 coins/query): ~100-150 queries per chain day ≈ 25-40 h
  for 21.8 days.
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

**AGENT rule.** A pool wallet with ≥ 4 buys in [g, g + 330 s), no sells, a median gap of 11-13 s, and
**≥ 60% of gaps within 10-14 s**.

- **Why not the PLAN's rule.** PLAN §3.2 asks for a gap coefficient of variation < 0.15. On real data one
  skipped 12 s slice creates a 24 s gap and pushes the CV to 0.2-0.4, so the PLAN's rule missed 26% of BOOST
  agents on the census night. `b2_coins.agent_plan_rule` records whether the PLAN's rule also matched.
- **Server and offline split.** `b2.sql` only pre-filters candidates (≥ 2 buys, no sells, median gap
  9-15 s). `features.detect_agent` applies the rule after merging the chunks.
- **Observed on 2026-10-07/08 census coins** (SOL-quoted, not Mayhem, `boost_mode = COMPLETED`): present on
  100%; **28 slices** (p10-p90 25-28, not 25); **16.2 SOL** (p10-p90 15.2-16.7); first buy ~2 s after g;
  gap 12.0 s.
- **Expect revision.** The candidate window stops at g + 330 s. If later data shows more than 28 slices,
  widen `g_ts + 330` in `b2.sql` (BOOST may run past 330 s).

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
as closed when `end_tok` ≤ 1% of `peak_tok` or the window ended.

### `b1_trades.parquet` (P4) and `wallet_dict.parquet`

`b1_trades.parquet` comes from `sql/b1.sql`: non-dust trades (≥ 0.01 SOL) over [created, g + 120 min] for
non-factory coins. One row per trade:

| Columns | Meaning |
|---|---|
| `slot`, `tx_idx`, `pix`, `ix` | Total chain order and unique key. |
| `ts`, `mint` | |
| `venue` | 0 = curve, 1 = PumpSwap. |
| `is_buy`, `wallet_h`, `usol` | `usol` is in lamports, user-side. |
| `tok` | Raw units, 6 decimals. |
| `x0`, `y0` | Reserves **before** the trade. Curve: virtual SOL/token. PumpSwap: real quote/base. |
| `fees` | Lamports: protocol + creator + LP. |
| `virt_ksol` | PumpSwap virtual quote reserve / 1000 lamports, on buys only. |
| `src` | 0 = CryptoHouse. |

**Price before the trade:** (x0 + virt) / y0, with virt = the pool's `virt_sol` from `b2_coins`.

`wallet_dict.parquet` maps `wallet_h` → base58 for every wallet that moved ≥ 1 SOL in a coin.

`sql/raw.sql` has the same selection, with tx signatures, base58 wallets and full fee fields. It is used by
`validate.py` and by ad-hoc pulls.

### Other files in `FLOW`

| File | Contents |
|---|---|
| `manifest.json` | Coverage: graduates, with creation, with pool, Mayhem, curve and B2 hours done and their spans, B3/B1 coins, errors, and query stats by tag. |
| `state.json` | Resumable state: done hours and parts, pools done per B2 hour, and errors. |
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

- **Where it is.** `virt` is a u64 that only Buy events carry, at byte `446 + len(ix_name)`. It was
  ~17.58 SOL, nearly constant, on 2026-10 migration pools.
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
  30 minutes before the graduation hour. Slower graduates (~3-5%) have partial curve stats and no launch
  window.
- **The B2 windows** (`w120`, `w300`) are exact only when [g, g + 330 s) lies inside one chain hour
  (`w_exact`). Otherwise their sums are exact and their counts are approximate.
- **The last 3 hours before a run** have incomplete [g, g + 180 min) windows. A later run that extends the
  range fills them in, because B2 hours are keyed by hour and pool.

### 8. No lookahead (PLAN §3.2, §6.6)

These tables are storage, not features.

- **Bars.** Per-minute bars are complete only for minutes that ended before the decision.
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
- **Non-SOL-quoted coins:** check `pool_quote_mint`. Their prices are in quote units; exclude them, as
  the lab does.

### 10. Transaction version 1

Transaction v1 activated on 2026-09-15 at slot 447,120,000. CryptoHouse includes v1 transactions; nothing
here depends on the version.

-- b3.sql: per-(wallet, coin) position summaries over each coin's window, packed one row per coin.
--
-- Params: s0, s1, t0, t1 (scan range), win = array of (mint, pool, ts_lo, ts_hi) (pool '1' = none),
--         mints (token_transfers prefilter), min_wallet_usol (lamports; wallets whose buy + sell volume is
--         below it are dropped but counted in n_dust_wallets).
-- Successful transactions only, curve and PumpSwap combined, ordered by (slot, tx_idx, parent_index, index).
-- Each wallet tuple (wallet_h = cityHash64 of the raw 32-byte key, stable across queries; the base58 address
-- is included only for wallets that bought >= 0.5 SOL, to keep results under the 1 MB cap):
--   (wallet_h, wallet, n_buys, n_sells, buy_sol, sell_sol, buy_tok, sell_tok, curve_buy_sol, curve_sell_sol,
--    first_ts, last_ts, first_buy_ts, last_sell_ts, peak_tok, end_tok, orphan_tok, n_sell_before_buy)
-- SOL user-side (fees in for buys, out for sells); tokens whole; peak/end position from the ordered
-- running sum of signed tokens; orphan_tok = tokens sold beyond the wallet's holding at that moment
-- (PLAN 3.2 orphan_part, a TRANSFEREE signal: tokens obtained outside these trades).
WITH
  $win AS win_arr,
wn AS (
  SELECT mint, ts_lo, ts_hi, tupleElement(kv, 1) AS key_b, tupleElement(kv, 2) AS venue
  FROM (
    SELECT tupleElement(t, 1) AS mint, toUInt32(tupleElement(t, 3)) AS ts_lo, toUInt32(tupleElement(t, 4)) AS ts_hi,
           arrayJoin([(base58Decode(tupleElement(t, 1)), toUInt8(0)), (base58Decode(tupleElement(t, 2)), toUInt8(1))]) AS kv
    FROM (SELECT arrayJoin(win_arr) AS t)
  )
),
okt AS (
  SELECT signature, index AS tx_idx FROM solana.transactions_non_voting
  WHERE block_timestamp >= toDateTime64('$t0', 6) AND block_timestamp < toDateTime64('$t1', 6) AND err = ''
    AND signature IN (
      SELECT tx_signature FROM solana.token_transfers
      WHERE block_timestamp >= toDateTime64('$t0', 6) AND block_timestamp < toDateTime64('$t1', 6)
        AND mint IN $mints)
),
ev AS (
  SELECT block_slot AS slot, toUInt32(block_timestamp) AS ts, tx_signature AS tx, parent_index AS pix, index AS ix,
         program_id = '$AMM' AS amm, base58Decode(data) AS r,
         if(amm, substring(r, 129, 32), substring(r, 17, 32)) AS key_b
  FROM solana.instructions
  PREWHERE block_slot BETWEEN $s0 AND $s1 AND program_id IN ('$CURVE', '$AMM') AND parent_index >= 0
    AND length(data) BETWEEN $L_CURVE_TRADE_LO AND $L_AMM_TRADE_HI
  WHERE block_timestamp >= toDateTime64('$t0', 6) AND block_timestamp < toDateTime64('$t1', 6)
    AND tx_signature IN (SELECT signature FROM okt)
),
tr AS (
  SELECT w.mint AS mint, (e.slot, o.tx_idx, e.pix, e.ix) AS okey, e.ts AS ts, toUInt8(e.amm) AS venue,
    if(e.amm, substring(e.r, 9, 8) = unhex('$D_AMM_BUY'), reinterpretAsUInt8(substring(e.r, 65, 1)) = 1) AS is_buy,
    if(e.amm, substring(e.r, 161, 32), substring(e.r, 66, 32)) AS user_b,
    if(e.amm, reinterpretAsUInt64(substring(e.r, 113, 8)), reinterpretAsUInt64(substring(e.r, 49, 8))) AS qd,
    if(e.amm, reinterpretAsUInt64(substring(e.r, 105, 8)) + reinterpretAsUInt64(substring(e.r, 361, 8)),
              reinterpretAsUInt64(substring(e.r, 178, 8)) + reinterpretAsUInt64(substring(e.r, 226, 8))) AS fees,
    if(is_buy, qd + fees, toUInt64(qd - least(qd, fees))) AS usol,
    if(e.amm, reinterpretAsUInt64(substring(e.r, 25, 8)), reinterpretAsUInt64(substring(e.r, 57, 8))) AS tok
  FROM ev AS e
  INNER JOIN wn AS w ON w.key_b = e.key_b AND w.venue = toUInt8(e.amm)
  INNER JOIN okt AS o ON o.signature = e.tx
  WHERE substring(e.r, 1, 8) = unhex('$PREFIX')
    AND substring(e.r, 9, 8) IN (unhex('$D_CURVE_TRADE'), unhex('$D_AMM_BUY'), unhex('$D_AMM_SELL'))
    AND (e.amm OR substring(e.r, 9, 8) = unhex('$D_CURVE_TRADE'))
    AND e.ts >= w.ts_lo AND e.ts < w.ts_hi
),
wc AS (
  SELECT mint, user_b,
    countIf(is_buy) AS nb, countIf(NOT is_buy) AS ns,
    sumIf(usol, is_buy) AS bs, sumIf(usol, NOT is_buy) AS ss,
    sumIf(tok, is_buy) AS bt, sumIf(tok, NOT is_buy) AS st,
    sumIf(usol, is_buy AND venue = 0) AS cbs, sumIf(usol, NOT is_buy AND venue = 0) AS css,
    min(ts) AS t_first, max(ts) AS t_last, minIf(ts, is_buy) AS t_fbuy, maxIf(ts, NOT is_buy) AS t_lsell,
    arrayMap(x -> x.2, arraySort(x -> x.1, groupArray((okey, if(is_buy, toInt64(tok), -toInt64(tok)))))) AS d,
    arrayCumSum(d) AS pos,
    arrayMax(arrayConcat([0], pos)) AS peak, arrayReduce('sum', d) AS endp,
    -- orphan: on each sell, tokens beyond the holding before it
    arraySum(arrayMap((dd, p) -> if(dd < 0, greatest(0, -dd - greatest(p - dd, 0)), 0), d, pos)) AS orphan,
    arrayCount((dd, p) -> dd < 0 AND p - dd <= 0, d, pos) AS n_sell_wo_hold
  FROM tr
  GROUP BY mint, user_b
)
SELECT mint,
  count() AS n_wallets,
  countIf(bs + ss < $min_wallet_usol) AS n_dust_wallets,
  -- coin-level aggregates over ALL wallets (including those below min_wallet_usol)
  countIf(nb > 0) AS n_buyers_all, countIf(ns > 0) AS n_sellers_all,
  countIf(orphan > 0) AS n_orphan_sellers, sumIf(ss, orphan > 0) / 1e9 AS orphan_seller_sell_sol,
  sum(orphan) / 1e6 AS orphan_tok, countIf(nb = 0 AND ns > 0) AS n_sell_only_wallets,
  arrayMap(x -> (cityHash64(x.1), if(x.4 >= 500000000, base58Encode(x.1), ''), x.2, x.3,
                 toFloat32(x.4 / 1e9), toFloat32(x.5 / 1e9), toFloat32(x.6 / 1e6), toFloat32(x.7 / 1e6),
                 toFloat32(x.8 / 1e9), toFloat32(x.9 / 1e9), x.10, x.11, x.12, x.13,
                 toFloat32(x.14 / 1e6), toFloat32(x.15 / 1e6), toFloat32(x.16 / 1e6), x.17),
    groupArrayIf((user_b, toUInt32(nb), toUInt32(ns), bs, ss, bt, st, cbs, css, t_first, t_last, t_fbuy, t_lsell, peak, endp, orphan, toUInt32(n_sell_wo_hold)),
                 bs + ss >= $min_wallet_usol)) AS wallets
FROM wc
GROUP BY mint

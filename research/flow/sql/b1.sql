-- b1.sql: slim raw curve + PumpSwap trades for P4 (B1), packed one row per coin.
-- Same selection as raw.sql (successful transactions, chain order) but compact tuples so ~15k trades fit
-- in the 1 MB result cap: no tx signature (the key is slot, tx_idx, pix, ix) and wallets as cityHash64
-- of the raw key, with a per-coin dictionary {wallet_h: base58} for wallets that moved >= 1 SOL.
--
-- Params: s0, s1 (slot range), t0, t1 (UTC bounds of the scan), win = array of (mint, pool, ts_lo, ts_hi)
--         (pool may be '1' for "no pool"), mints = the mints (token_transfers prefilter),
--         min_usol (lamports; trades below it are dropped, 0 keeps dust), max_trades (per coin).
-- Successful transactions only. Each trade is a tuple
--   (slot, tx_idx, pix, ix, ts, tx, venue, is_buy, user, usol, tok, x0, y0, x1, y1, qamt, lp_fee, pfee, cfee, ix_name, virt)
-- virt = PumpSwap virtual quote reserve from Buy events (0 on sells and curve trades); AMM price = (x + virt) / y.
-- venue 0 = curve (x/y = virtual SOL/token reserves; x0/y0 derived from the post-trade values),
-- venue 1 = PumpSwap (x/y = pool quote/base reserves; x0/y0 as emitted, x1/y1 derived),
-- amounts in raw units (lamports, token base units with 6 decimals), sorted by (slot, tx_idx, pix, ix).
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
  SELECT w.mint AS mint, w.ts_lo AS ts_lo, e.slot AS slot, o.tx_idx AS tx_idx, e.pix AS pix, e.ix AS ix, e.ts AS ts, e.tx AS tx,
    toUInt8(e.amm) AS venue,
    if(e.amm, substring(e.r, 9, 8) = unhex('$D_AMM_BUY'), reinterpretAsUInt8(substring(e.r, 65, 1)) = 1) AS is_buy,
    if(e.amm, substring(e.r, 161, 32), substring(e.r, 66, 32)) AS user_b,
    -- curve fields
    reinterpretAsUInt64(substring(e.r, 49, 8)) AS c_sol, reinterpretAsUInt64(substring(e.r, 57, 8)) AS c_tok,
    reinterpretAsUInt64(substring(e.r, 106, 8)) AS c_vx, reinterpretAsUInt64(substring(e.r, 114, 8)) AS c_vy,
    reinterpretAsUInt64(substring(e.r, 178, 8)) AS c_fee, reinterpretAsUInt64(substring(e.r, 226, 8)) AS c_cfee,
    -- amm fields
    reinterpretAsUInt64(substring(e.r, 25, 8)) AS a_base, reinterpretAsUInt64(substring(e.r, 57, 8)) AS a_y0,
    reinterpretAsUInt64(substring(e.r, 65, 8)) AS a_x0, reinterpretAsUInt64(substring(e.r, 73, 8)) AS a_qamt,
    reinterpretAsUInt64(substring(e.r, 89, 8)) AS a_lp, reinterpretAsUInt64(substring(e.r, 105, 8)) AS a_pf,
    reinterpretAsUInt64(substring(e.r, 113, 8)) AS a_qd, reinterpretAsUInt64(substring(e.r, 361, 8)) AS a_cf,
    if(e.amm, a_pf, c_fee) AS pfee, if(e.amm, a_cf, c_cfee) AS cfee,
    if(e.amm, a_qd, c_sol) AS qd,
    if(is_buy, qd + pfee + cfee, toUInt64(qd - least(qd, pfee + cfee))) AS usol,
    if(e.amm, a_base, c_tok) AS tok,
    if(e.amm, a_x0, if(is_buy, toUInt64(c_vx - least(c_vx, c_sol)), c_vx + c_sol)) AS x0,
    if(e.amm, a_y0, if(is_buy, c_vy + c_tok, toUInt64(c_vy - least(c_vy, c_tok)))) AS y0,
    if(e.amm, if(is_buy, a_x0 + a_qd, toUInt64(a_x0 - least(a_x0, a_qd))), c_vx) AS x1,
    if(e.amm, if(is_buy, toUInt64(a_y0 - least(a_y0, a_base)), a_y0 + a_base), c_vy) AS y1,
    if(e.amm, a_qamt, c_sol) AS qamt, if(e.amm, a_lp, 0) AS lp_fee,
    reinterpretAsUInt32(substring(e.r, 410, 4)) AS a_ixn_len,
    if(e.amm AND is_buy AND length(e.r) >= 454 + a_ixn_len AND a_ixn_len < 40,
       reinterpretAsUInt64(substring(e.r, 446 + a_ixn_len, 8)), 0) AS virt_raw,
    if(virt_raw < 100000000000, virt_raw, 0) AS virt,
    if(e.amm, if(is_buy AND a_ixn_len < 40, substring(e.r, 414, a_ixn_len), ''), substring(e.r, 271, reinterpretAsUInt32(substring(e.r, 267, 4)))) AS ix_name
  FROM ev AS e
  INNER JOIN wn AS w ON w.key_b = e.key_b AND w.venue = toUInt8(e.amm)
  INNER JOIN okt AS o ON o.signature = e.tx
  WHERE substring(e.r, 1, 8) = unhex('$PREFIX')
    AND substring(e.r, 9, 8) IN (unhex('$D_CURVE_TRADE'), unhex('$D_AMM_BUY'), unhex('$D_AMM_SELL'))
    AND (e.amm OR substring(e.r, 9, 8) = unhex('$D_CURVE_TRADE'))
    AND e.ts >= w.ts_lo AND e.ts < w.ts_hi
    AND usol >= $min_usol
),
packed AS (
  SELECT mint, count() AS n_trades, n_trades > $max_trades AS truncated,
    -- per-minute totals over ALL trades (never truncated): (minute since ts_lo, venue, n, n_buys, buy_usol, sell_usol)
    groupArray((toUInt32(intDiv(ts - ts_lo, 60)), venue, toUInt8(is_buy), usol)) AS mv,
    arrayDistinct(arrayMap(x -> (x.1, x.2), mv)) AS mk,
    arraySort(arrayMap(k -> (k.1, k.2,
        length(arrayFilter(x -> x.1 = k.1 AND x.2 = k.2, mv)),
        length(arrayFilter(x -> x.1 = k.1 AND x.2 = k.2 AND x.3 = 1, mv)),
        arraySum(arrayMap(x -> if(x.1 = k.1 AND x.2 = k.2 AND x.3 = 1, x.4, 0), mv)),
        arraySum(arrayMap(x -> if(x.1 = k.1 AND x.2 = k.2 AND x.3 = 0, x.4, 0), mv))), mk)) AS minutes,
    arraySlice(arraySort(x -> (x.1, x.2, x.3, x.4), groupArray((toUInt32(slot), toUInt16(tx_idx), toUInt8(pix), toUInt8(ix), ts,
        venue, toUInt8(is_buy), cityHash64(user_b), usol, tok, x0, y0, toUInt32(pfee + cfee + lp_fee), toUInt32(virt / 1000)))),
        1, $max_trades) AS trades,
    sumMap([user_b], [usol]) AS wsum,
    arrayMap(x -> (cityHash64(x.1), base58Encode(x.1)), arrayFilter(x -> x.2 >= 1000000000, arrayZip(wsum.1, wsum.2))) AS wallet_dict
  FROM tr
  GROUP BY mint
)
SELECT mint, n_trades, truncated, minutes, trades, wallet_dict FROM packed

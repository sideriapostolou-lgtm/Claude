-- b1c.sql: B1 raw curve + PumpSwap trades for P4b, one row per PIECE, compact 43-byte tuples.
-- Same selection as b1.sql up to `trf` (successful transactions only, chain-order virtual-reserve carry,
-- dust < min_usol dropped). A query covers one time slab [t0, t1) (<= 30 min) and carries every selected coin
-- active in it as a piece (mint, pool, ts_lo, ts_hi) = the coin's B1 window [created, g + 120 min) cut to the slab.
-- No minutes array, no wallet dictionary, no max_trades cut: S1/D1 hash pooled accounts locally.
--
-- Params: s0, s1 (slot range from the 15-minute anchors), t0, t1 (exact UTC bounds = [min ts_lo, max ts_hi)),
--         win = array of (mint, pool, ts_lo, ts_hi) pieces (pool may be '1' for "no pool"; a mint appears at most
--         once per query in practice; windows, the carry and the output are per (mint, ts_lo) anyway),
--         mints = the mints (token_transfers prefilter), min_usol (lamports).
-- Output per piece with >= 1 trade (an empty piece returns no row):
--   mint, lo (= ts_lo), n_trades, trades (sorted by slot, tx_idx, pix, ix), b_trades = byteSize(trades),
--   n_overflow = trades whose values do not fit the compact types (must be 0; the backfill marks the coin as an error).
-- Trade tuple (43 B):
--   (slot UInt32, tx_idx UInt16, pix UInt8, ix UInt8, ts - lo UInt16, flags UInt8 = venue + 2 * is_buy,
--    wallet_h UInt64 = cityHash64(raw 32-byte user key), usol UInt32 (micro-SOL, user-side, truncated),
--    tok UInt32 (whole tokens, rounded), x0 Float32 (lamports), y0 UInt32 (whole tokens, rounded),
--    fees UInt32 (micro-SOL: protocol + creator + LP), virt UInt32 (k-lamports: PumpSwap virtual quote reserve
--    in force BEFORE the trade, carried through sells within the piece; 0 on curve trades and on pool sells
--    before the piece's first buy, which consolidation forward-fills)).
-- venue 0 = curve (x0/y0 = virtual SOL/token reserves before the trade), venue 1 = PumpSwap (real quote/base before).
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
    if(virt_raw < 100000000000, virt_raw, 0) AS virt
  FROM ev AS e
  INNER JOIN wn AS w ON w.key_b = e.key_b AND w.venue = toUInt8(e.amm)
  INNER JOIN okt AS o ON o.signature = e.tx
  WHERE substring(e.r, 1, 8) = unhex('$PREFIX')
    AND substring(e.r, 9, 8) IN (unhex('$D_CURVE_TRADE'), unhex('$D_AMM_BUY'), unhex('$D_AMM_SELL'))
    AND (e.amm OR substring(e.r, 9, 8) = unhex('$D_CURVE_TRADE'))
    AND e.ts >= w.ts_lo AND e.ts < w.ts_hi
),
-- PumpSwap pricing reserve X = x + v; v is emitted on Buy events only and moves opposite to x between trades.
-- Carry it along the per-piece pool chain BEFORE dropping dust (see b2.sql): v_k = (v + C)_last_buy - C_k.
trj AS (
  SELECT *, if(venue = 1 AND toInt64(y0) = lagInFrame(toInt64(y1), 1, toInt64(y0)) OVER wj,
               toInt64(x0) - lagInFrame(toInt64(x1), 1, toInt64(x0)) OVER wj, 0) AS brk
  FROM tr WINDOW wj AS (PARTITION BY mint, ts_lo, venue ORDER BY slot, tx_idx, pix, ix ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)
),
trc AS (
  SELECT *, sum(brk) OVER (PARTITION BY mint, ts_lo, venue ORDER BY slot, tx_idx, pix, ix ROWS UNBOUNDED PRECEDING) AS cbrk FROM trj
),
trv AS (
  SELECT *,
    last_value(if(virt > 0, toInt64(virt) + cbrk, NULL)) OVER (PARTITION BY mint, ts_lo, venue ORDER BY slot, tx_idx, pix, ix ROWS UNBOUNDED PRECEDING) AS vc,
    if(venue = 1, toUInt64(greatest(ifNull(vc - cbrk, 0), 0)), 0) AS virt_t
  FROM trc
),
trf AS (SELECT * FROM trv WHERE usol >= $min_usol),
packed AS (
  SELECT mint, ts_lo AS lo, count() AS n_trades,
    arraySort(x -> (x.1, x.2, x.3, x.4), groupArray((toUInt32(slot), toUInt16(tx_idx), toUInt8(pix), toUInt8(ix),
        toUInt16(ts - ts_lo), toUInt8(venue + 2 * toUInt8(is_buy)), cityHash64(user_b),
        toUInt32(least(intDiv(usol, 1000), 4294967295)),
        toUInt32(least(intDiv(tok + 500000, 1000000), 4294967295)),
        toFloat32(x0), toUInt32(least(intDiv(y0 + 500000, 1000000), 4294967295)),
        toUInt32(least(intDiv(pfee + cfee + lp_fee, 1000), 4294967295)),
        toUInt32(virt_t / 1000)))) AS trades,
    countIf(pix > 255 OR ix > 255 OR tx_idx > 65535 OR ts - ts_lo > 65535 OR usol >= 4294967295000) AS n_overflow
  FROM trf
  GROUP BY mint, ts_lo
)
SELECT mint, lo, n_trades, trades, byteSize(trades) AS b_trades, n_overflow FROM packed

-- b2.sql: server-side PumpSwap aggregates for graduates' pools over one chain chunk [t0, t1).
--
-- Params: s0, s1 (slot range covering [t0, t1) with margin), t0, t1 (exact UTC clock boundaries),
--         act = array of (pool, mint, g_ts) for pools whose window [g_ts, g_ts + horizon_s) meets the chunk,
--         mints = the same mints (for the token_transfers prefilter), horizon_s.
-- Only successful transactions (transactions_non_voting.err = '') are used; their in-block index gives
-- the intra-slot order (slot, tx_idx, parent_index, index).
-- One output row per pool:
--   bars: clock-minute bars [(minute_ts, n_buys, n_sells, n_dust, buy_sol, sell_sol, buy_tok, sell_tok,
--          n_buyers, n_sellers, top5_buy_sol, open, high, low, close, x_close, y_close)], prices in SOL per
--          whole token from pool reserves (open = before the minute's first trade, others after trades),
--          x = SOL reserve, y = token reserve; buyers/sellers/top5 count wallets with >= 0.01 SOL in the minute.
--   agent candidates: wallets with >= 2 buys, 0 sells in [g, g+330 s) inside this chunk: (user, [ts], [sol]).
--   early windows (exact only if [g, g + 300) lies inside the chunk; flag w_complete):
--          totals over 120 s and 300 s after g, plus the top 10 buyers of each window.
WITH
  $act AS act_arr,
act AS (
  SELECT base58Decode(tupleElement(t, 1)) AS pool_b, tupleElement(t, 2) AS mint, toUInt32(tupleElement(t, 3)) AS g_ts
  FROM (SELECT arrayJoin(act_arr) AS t)
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
         base58Decode(data) AS r, substring(r, 129, 32) AS ev_pool_b
  FROM solana.instructions
  PREWHERE block_slot BETWEEN $s0 AND $s1 AND program_id = '$AMM' AND parent_index >= 0
    AND length(data) BETWEEN $L_AMM_TRADE_LO AND $L_AMM_TRADE_HI
  WHERE block_timestamp >= toDateTime64('$t0', 6) AND block_timestamp < toDateTime64('$t1', 6)
    AND tx_signature IN (SELECT signature FROM okt)
),
tr AS (
  SELECT e.slot AS slot, e.ts AS ts, (e.slot, o.tx_idx, e.pix, e.ix) AS okey,
    substring(e.r, 9, 8) = unhex('$D_AMM_BUY') AS is_buy,
    a.pool_b AS pool_b, a.mint AS mint, a.g_ts AS g_ts,
    substring(e.r, 161, 32) AS user_b,
    reinterpretAsUInt64(substring(e.r, 25, 8)) AS base_amt,
    reinterpretAsUInt64(substring(e.r, 57, 8)) AS y0,
    reinterpretAsUInt64(substring(e.r, 65, 8)) AS x0,
    reinterpretAsUInt64(substring(e.r, 113, 8)) AS qdelta,
    reinterpretAsUInt64(substring(e.r, 105, 8)) + reinterpretAsUInt64(substring(e.r, 361, 8)) AS xfees,
    if(is_buy, qdelta + xfees, toUInt64(qdelta - least(qdelta, xfees))) AS usol,
    if(is_buy, toUInt64(y0 - least(y0, base_amt)), y0 + base_amt) AS y1,
    if(is_buy, x0 + qdelta, toUInt64(x0 - least(x0, qdelta))) AS x1,
    (x1 / 1e9) / greatest(y1 / 1e6, 1e-9) AS p1,
    (x0 / 1e9) / greatest(y0 / 1e6, 1e-9) AS p0
  FROM ev AS e
  INNER JOIN act AS a ON a.pool_b = e.ev_pool_b
  INNER JOIN okt AS o ON o.signature = e.tx
  WHERE substring(e.r, 1, 8) = unhex('$PREFIX')
    AND substring(e.r, 9, 8) IN (unhex('$D_AMM_BUY'), unhex('$D_AMM_SELL'))
    AND e.ts >= a.g_ts AND e.ts < a.g_ts + $horizon_s
),
pmu AS (
  SELECT pool_b, intDiv(ts, 60) * 60 AS m, user_b,
    countIf(is_buy) AS u_nb, countIf(NOT is_buy) AS u_ns,
    sumIf(usol, is_buy) AS u_bs, sumIf(usol, NOT is_buy) AS u_ss,
    sumIf(base_amt, is_buy) AS u_bt, sumIf(base_amt, NOT is_buy) AS u_st,
    countIf(usol < 10000000) AS u_nd,
    min(okey) AS u_k0, argMin(p0, okey) AS u_p0,
    max(okey) AS u_k1, argMax((p1, x1, y1), okey) AS u_s1,
    max(p1) AS u_hi, min(p1) AS u_lo
  FROM tr GROUP BY pool_b, m, user_b
),
pm AS (
  SELECT pool_b, m,
    sum(u_nb) AS nb, sum(u_ns) AS ns, sum(u_nd) AS nd,
    sum(u_bs) / 1e9 AS bs, sum(u_ss) / 1e9 AS ss, sum(u_bt) / 1e6 AS bt, sum(u_st) / 1e6 AS st,
    countIf(u_bs >= 10000000) AS n_buyers, countIf(u_ss >= 10000000) AS n_sellers,
    arraySum(arraySlice(arrayReverseSort(groupArray(u_bs)), 1, 5)) / 1e9 AS top5,
    argMin(u_p0, u_k0) AS o, max(u_hi) AS h, min(u_lo) AS l, argMax(u_s1, u_k1) AS s1
  FROM pmu GROUP BY pool_b, m
),
bars AS (
  SELECT pool_b,
    arraySort(x -> x.1, groupArray((toUInt32(m), toUInt32(nb), toUInt32(ns), toUInt32(nd),
        toFloat32(bs), toFloat32(ss), toFloat32(bt), toFloat32(st), toUInt32(n_buyers), toUInt32(n_sellers),
        toFloat32(top5), o, h, l, s1.1, toFloat32(s1.2 / 1e9), toFloat32(s1.3 / 1e6)))) AS bars,
    min(m) AS first_m, max(m) AS last_m, sum(nb) + sum(ns) AS n_trades
  FROM pm GROUP BY pool_b
),
ag AS (
  SELECT pool_b,
    groupArray((base58Encode(user_b), ts_arr, sol_arr)) AS agent_cands
  FROM (
    SELECT pool_b, user_b, arraySort(groupArrayIf(ts, is_buy)) AS ts_arr,
           arrayMap(x -> toFloat32(x.2 / 1e9), arraySort(x -> x.1, groupArrayIf((ts, usol), is_buy))) AS sol_arr,
           countIf(NOT is_buy) AS n_s
    FROM tr WHERE ts < g_ts + 330
    GROUP BY pool_b, user_b
    HAVING n_s = 0 AND length(ts_arr) >= 2
       AND (length(ts_arr) < 3 OR arrayReduce('median', arrayDifference(ts_arr)) BETWEEN 9 AND 15)
  )
  GROUP BY pool_b
),
w AS (
  SELECT pool_b,
    sum(w2_b) / 1e9 AS w120_buy_sol, sum(w2_s) / 1e9 AS w120_sell_sol,
    countIf(w2_b >= 10000000) AS w120_n_buyers, countIf(w2_s >= 10000000) AS w120_n_sellers,
    sum(w5_b) / 1e9 AS w300_buy_sol, sum(w5_s) / 1e9 AS w300_sell_sol,
    countIf(w5_b >= 10000000) AS w300_n_buyers, countIf(w5_s >= 10000000) AS w300_n_sellers,
    arraySlice(arrayReverseSort(x -> x.2, groupArrayIf((base58Encode(user_b), toFloat32(w2_b / 1e9), toFloat32(w2_s / 1e9)), w2_b > 0)), 1, 10) AS w120_top10,
    arraySlice(arrayReverseSort(x -> x.2, groupArrayIf((base58Encode(user_b), toFloat32(w5_b / 1e9), toFloat32(w5_s / 1e9)), w5_b > 0)), 1, 10) AS w300_top10
  FROM (
    SELECT pool_b, user_b,
      sumIf(usol, is_buy AND ts < g_ts + 120) AS w2_b, sumIf(usol, NOT is_buy AND ts < g_ts + 120) AS w2_s,
      sumIf(usol, is_buy) AS w5_b, sumIf(usol, NOT is_buy) AS w5_s
    FROM tr WHERE ts < g_ts + 300
    GROUP BY pool_b, user_b
  )
  GROUP BY pool_b
)
SELECT base58Encode(a.pool_b) AS pool, a.mint AS mint, a.g_ts AS g_ts,
  (a.g_ts >= toUInt32(toDateTime('$t0')) AND a.g_ts + 300 <= toUInt32(toDateTime('$t1'))) AS w_complete,
  b.n_trades, b.first_m, b.last_m, b.bars,
  ag.agent_cands,
  w.w120_buy_sol, w.w120_sell_sol, w.w120_n_buyers, w.w120_n_sellers,
  w.w300_buy_sol, w.w300_sell_sol, w.w300_n_buyers, w.w300_n_sellers, w.w120_top10, w.w300_top10
FROM act AS a
LEFT JOIN bars AS b ON b.pool_b = a.pool_b
LEFT JOIN ag ON ag.pool_b = a.pool_b
LEFT JOIN w ON w.pool_b = a.pool_b
WHERE b.n_trades > 0

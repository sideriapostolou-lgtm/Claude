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
--          x = real SOL reserve as emitted, y = token reserve; price = (x + virt) / y where virt is the
--          pool's virtual quote reserve read from Buy events (~17.58 SOL on 2026-10 migration pools; sells do
--          not carry it, so a pool with no buy in the chunk gets virt = 0 and its prices must be redone
--          offline from x_close/y_close); buyers/sellers/top5 count wallets with >= 0.01 SOL in the minute.
--   agent candidates: wallets with >= 2 buys, 0 sells in [g, g+420 s) inside this chunk: (user, [ts], [sol]).
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
    reinterpretAsUInt32(substring(e.r, 410, 4)) AS ixn_len,
    if(is_buy AND length(e.r) >= 454 + ixn_len AND ixn_len < 40,
       reinterpretAsUInt64(substring(e.r, 446 + ixn_len, 8)), 0) AS virt_raw,
    if(virt_raw < 100000000000, virt_raw, 0) AS virt,
    if(is_buy, qdelta + xfees, toUInt64(qdelta - least(qdelta, xfees))) AS usol,
    if(is_buy, toUInt64(y0 - least(y0, base_amt)), y0 + base_amt) AS y1,
    if(is_buy, x0 + qdelta, toUInt64(x0 - least(x0, qdelta))) AS x1,
    x0 AS x0r
  FROM ev AS e
  INNER JOIN act AS a ON a.pool_b = e.ev_pool_b
  INNER JOIN okt AS o ON o.signature = e.tx
  WHERE substring(e.r, 1, 8) = unhex('$PREFIX')
    AND substring(e.r, 9, 8) IN (unhex('$D_AMM_BUY'), unhex('$D_AMM_SELL'))
    AND e.ts >= a.g_ts AND e.ts < a.g_ts + $horizon_s
),
-- The pool prices with X = x + v. v (virtual quote reserve) is emitted on Buy events only and is NOT constant:
-- between trades x and v move by opposite amounts (X is conserved). Carry v through sells along the chain:
-- v_k = (v + C)_last_buy - C_k, C = cumulative quote-side jumps x0_k - x1_(k-1) where the token side chains.
trj AS (
  SELECT *, if(toInt64(y0) = lagInFrame(toInt64(y1), 1, toInt64(y0)) OVER wj,
               toInt64(x0) - lagInFrame(toInt64(x1), 1, toInt64(x0)) OVER wj, 0) AS brk
  FROM tr WINDOW wj AS (PARTITION BY pool_b ORDER BY okey ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)
),
trc AS (
  SELECT *, sum(brk) OVER (PARTITION BY pool_b ORDER BY okey ROWS UNBOUNDED PRECEDING) AS cbrk FROM trj
),
trp AS (
  SELECT *, max(virt) OVER (PARTITION BY pool_b) AS pv,
    last_value(if(virt > 0, toInt64(virt) + cbrk, NULL)) OVER (PARTITION BY pool_b ORDER BY okey ROWS UNBOUNDED PRECEDING) AS vc,
    toUInt64(greatest(ifNull(vc - cbrk, toInt64(pv)), 0)) AS pv_t,
    ((x1 + pv_t) / 1e9) / greatest(y1 / 1e6, 1e-9) AS p1,
    ((x0 + pv_t) / 1e9) / greatest(y0 / 1e6, 1e-9) AS p0
  FROM trc
),
-- per (pool, clock minute, wallet); everything downstream is a single linear pipeline (CTEs referenced
-- more than once are re-executed by ClickHouse, which would repeat the whole scan).
pmu AS (
  SELECT pool_b, intDiv(ts, 60) * 60 AS m, user_b,
    any(mint) AS u_mint, any(g_ts) AS u_g, any(pv) AS u_pv, max(virt) AS u_virt,
    countIf(is_buy) AS u_nb, countIf(NOT is_buy) AS u_ns,
    sumIf(usol, is_buy) AS u_bs, sumIf(usol, NOT is_buy) AS u_ss,
    sumIf(base_amt, is_buy) AS u_bt, sumIf(base_amt, NOT is_buy) AS u_st,
    countIf(usol < 10000000) AS u_nd,
    min(okey) AS u_k0, argMin(p0, okey) AS u_p0,
    max(okey) AS u_k1, argMax((p1, x1, y1), okey) AS u_s1,
    max(p1) AS u_hi, min(p1) AS u_lo,
    sumIf(usol, is_buy AND ts < g_ts + 120) AS u_w2b, sumIf(usol, NOT is_buy AND ts < g_ts + 120) AS u_w2s,
    sumIf(usol, is_buy AND ts < g_ts + 300) AS u_w5b, sumIf(usol, NOT is_buy AND ts < g_ts + 300) AS u_w5s,
    arraySort(x -> x.1, groupArrayIf((ts, toFloat32(usol / 1e9)), is_buy AND ts < g_ts + 420)) AS u_agb,
    countIf(NOT is_buy AND ts < g_ts + 420) AS u_ags
  FROM trp GROUP BY pool_b, m, user_b
),
pm AS (
  SELECT pool_b, m, any(u_mint) AS mint, any(u_g) AS g_ts, any(u_pv) AS pv, max(u_virt) AS m_virt,
    sum(u_nb) AS nb, sum(u_ns) AS ns, sum(u_nd) AS nd,
    sum(u_bs) / 1e9 AS bs, sum(u_ss) / 1e9 AS ss, sum(u_bt) / 1e6 AS bt, sum(u_st) / 1e6 AS st,
    countIf(u_bs >= 10000000) AS n_buyers, countIf(u_ss >= 10000000) AS n_sellers,
    arraySum(arraySlice(arrayReverseSort(groupArray(u_bs)), 1, 5)) / 1e9 AS top5,
    argMin(u_p0, u_k0) AS o, max(u_hi) AS h, min(u_lo) AS l, argMax(u_s1, u_k1) AS s1,
    groupArrayIf(user_b, u_w5b + u_w5s > 0) AS w_users,
    groupArrayIf(u_w2b, u_w5b + u_w5s > 0) AS w_2b, groupArrayIf(u_w2s, u_w5b + u_w5s > 0) AS w_2s,
    groupArrayIf(u_w5b, u_w5b + u_w5s > 0) AS w_5b, groupArrayIf(u_w5s, u_w5b + u_w5s > 0) AS w_5s,
    groupArrayIf((user_b, u_agb, u_ags), length(u_agb) > 0 OR u_ags > 0) AS ag_parts
  FROM pmu GROUP BY pool_b, m
),
pp AS (
  SELECT pool_b, any(mint) AS mint, any(g_ts) AS g, any(pv) AS pool_pv, max(m_virt) AS virt_max,
    sum(nb) + sum(ns) AS n_trades, min(m) AS first_m, max(m) AS last_m,
    arraySort(x -> x.1, groupArray((toUInt32(m), toUInt32(nb), toUInt32(ns), toUInt32(nd),
        toFloat32(bs), toFloat32(ss), toFloat32(bt), toFloat32(st), toUInt32(n_buyers), toUInt32(n_sellers),
        toFloat32(top5), o, h, l, s1.1, toFloat32(s1.2 / 1e9), toFloat32(s1.3 / 1e6)))) AS bars,
    sumMap(w_users, w_2b, w_2s, w_5b, w_5s) AS wm,
    arrayFlatten(groupArray(ag_parts)) AS ag_flat
  FROM pm GROUP BY pool_b
)
SELECT base58Encode(pool_b) AS pool, mint, g AS g_ts,
  (g >= toUInt32(toDateTime('$t0')) AND g + 420 <= toUInt32(toDateTime('$t1'))) AS w_complete,
  n_trades, first_m, last_m, pool_pv / 1e9 AS virt_sol, virt_max / 1e9 AS virt_max_sol, bars,
  -- early windows after g (sums over wallets; buyers/sellers count wallets with >= 0.01 SOL)
  arraySum(wm.2) / 1e9 AS w120_buy_sol, arraySum(wm.3) / 1e9 AS w120_sell_sol,
  length(arrayFilter(x -> x >= 10000000, wm.2)) AS w120_n_buyers, length(arrayFilter(x -> x >= 10000000, wm.3)) AS w120_n_sellers,
  arraySum(wm.4) / 1e9 AS w300_buy_sol, arraySum(wm.5) / 1e9 AS w300_sell_sol,
  length(arrayFilter(x -> x >= 10000000, wm.4)) AS w300_n_buyers, length(arrayFilter(x -> x >= 10000000, wm.5)) AS w300_n_sellers,
  arraySlice(arrayReverseSort(x -> x.2, arrayFilter(x -> x.2 > 0, arrayMap((u, b, s) -> (base58Encode(u), toFloat32(b / 1e9), toFloat32(s / 1e9)), wm.1, wm.2, wm.3))), 1, 10) AS w120_top10,
  arraySlice(arrayReverseSort(x -> x.2, arrayFilter(x -> x.2 > 0, arrayMap((u, b, s) -> (base58Encode(u), toFloat32(b / 1e9), toFloat32(s / 1e9)), wm.1, wm.4, wm.5))), 1, 10) AS w300_top10,
  -- AGENT candidates: wallets with >= 2 buys and no sell in [g, g+330) within this chunk: (wallet, [ts], [sol])
  arrayFilter(c -> length(c.2) >= 2 AND c.4 = 0
                   AND (length(c.2) < 3 OR arrayReduce('median', arrayDifference(c.2)) BETWEEN 9 AND 15),
    arrayMap(u -> (base58Encode(u),
                   arraySort(arrayFlatten(arrayMap(x -> arrayMap(y -> y.1, x.2), arrayFilter(x -> x.1 = u, ag_flat)))),
                   arrayMap(y -> y.2, arraySort(y -> y.1, arrayFlatten(arrayMap(x -> x.2, arrayFilter(x -> x.1 = u, ag_flat))))),
                   arraySum(arrayMap(x -> x.3, arrayFilter(x -> x.1 = u, ag_flat)))),
             arrayDistinct(arrayMap(x -> x.1, ag_flat)))) AS agent_cands
FROM pp

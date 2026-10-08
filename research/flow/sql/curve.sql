-- curve.sql: one row per pump.fun bonding curve that COMPLETED (graduated) in slots [s0, s1].
--
-- Scans curve events over [s_lo, s1] (s_lo = s0 - lookback) from successful transactions only and
-- returns, per graduate:
--   * completion: g_slot, g_ts, completer (CompleteEvent.user), rsol_complete (real SOL at completion),
--   * creation (if the CreateEvent lies inside the scan, has_create = 1): name, symbol, uri, creator,
--     is_mayhem, quote_mint, token_program,
--   * curve-life aggregates over the scanned part of the curve (exact when has_create = 1),
--   * launch features over the first launch_s seconds after creation (creation slot = "bundle"),
--   * the canonical PumpSwap pool (CreatePool with base = mint, scanned over [s0, s1_pool]).
-- SOL amounts are user-side (fees included for buys, excluded for sells), in SOL; tokens are whole.
WITH
failed AS (
  SELECT signature FROM solana.transactions_non_voting
  WHERE block_timestamp BETWEEN toDateTime64('$t_lo', 6) AND toDateTime64('$t_hi', 6)
    AND block_slot BETWEEN $s_lo AND $s1_pool AND err != ''
),
raw AS (
  SELECT block_slot AS slot, toUInt32(block_timestamp) AS ts, base58Decode(data) AS r
  FROM solana.instructions
  WHERE block_slot BETWEEN $s_lo AND $s1
    AND program_id = '$CURVE' AND parent_index >= 0
    AND length(data) BETWEEN $L_CURVE_COMPLETE_LO AND 900
    AND tx_signature NOT IN failed
),
ev AS (
  SELECT slot, ts,
    substring(r, 9, 8) AS d,
    multiIf(d = unhex('$D_CURVE_TRADE'), 1, d = unhex('$D_CURVE_CREATE'), 2, d = unhex('$D_CURVE_COMPLETE'), 3, 0) AS k,
    if(k = 2, 21 + reinterpretAsUInt32(substring(r, 17, 4)), 0) AS o2,
    if(k = 2, o2 + 4 + reinterpretAsUInt32(substring(r, o2, 4)), 0) AS o3,
    if(k = 2, o3 + 4 + reinterpretAsUInt32(substring(r, o3, 4)), 0) AS o4,
    multiIf(k = 1, substring(r, 17, 32), k = 2, substring(r, o4, 32), k = 3, substring(r, 49, 32), '') AS mint_b,
    if(k = 1, substring(r, 66, 32), '') AS user_b,
    if(k = 1, reinterpretAsUInt8(substring(r, 65, 1)), 0) AS is_buy,
    if(k = 1, reinterpretAsUInt64(substring(r, 49, 8)), 0) AS sol,
    if(k = 1, reinterpretAsUInt64(substring(r, 57, 8)), 0) AS tok,
    if(k = 1, reinterpretAsUInt64(substring(r, 122, 8)), 0) AS rsol,
    if(k = 1, reinterpretAsUInt64(substring(r, 178, 8)) + reinterpretAsUInt64(substring(r, 226, 8)), 0) AS fees,
    if(is_buy = 1, sol + fees, toUInt64(sol - least(sol, fees))) AS usol,
    if(k = 2, substring(r, o4 + 96, 32), '') AS creator_b,
    if(k = 2, substring(r, o4 + 64, 32), '') AS cuser_b,
    if(k = 2, substring(r, 21, o2 - 21), '') AS name,
    if(k = 2, substring(r, o2 + 4, o3 - o2 - 4), '') AS symbol,
    if(k = 2, substring(r, o3 + 4, o4 - o3 - 4), '') AS uri,
    if(k = 2, reinterpretAsUInt8(substring(r, o4 + 200, 1)), 0) AS is_mayhem,
    if(k = 2, substring(r, o4 + 201, 32), '') AS quote_b,
    if(k = 2, substring(r, o4 + 168, 32), '') AS tokprog_b,
    if(k = 2, reinterpretAsUInt64(substring(r, o4 + 144, 8)), 0) AS vsol0,
    if(k = 3, substring(r, 17, 32), '') AS completer_b
  FROM raw
  WHERE substring(r, 1, 8) = unhex('$PREFIX') AND k > 0
),
ev2 AS (
  SELECT *,
    minIf(slot, k = 3 AND slot BETWEEN $s0 AND $s1) OVER w AS g_slot,
    minIf(ts, k = 3 AND slot BETWEEN $s0 AND $s1) OVER w AS g_ts,
    minIf(slot, k = 2) OVER w AS c_slot,
    minIf(ts, k = 2) OVER w AS c_ts,
    anyIf(creator_b, k = 2) OVER w AS creator_w
  FROM ev
  WINDOW w AS (PARTITION BY mint_b)
),
mu AS (
  SELECT mint_b, user_b,
    any(g_slot) AS m_g_slot, any(g_ts) AS m_g_ts, any(c_slot) AS m_c_slot, any(c_ts) AS m_c_ts,
    any(creator_w) AS m_creator_b,
    -- create / complete info (only in the user_b = '' group)
    anyIf(name, k = 2) AS m_name, anyIf(symbol, k = 2) AS m_symbol, anyIf(uri, k = 2) AS m_uri,
    anyIf(cuser_b, k = 2) AS m_cuser_b, anyIf(is_mayhem, k = 2) AS m_is_mayhem, anyIf(quote_b, k = 2) AS m_quote_b,
    anyIf(tokprog_b, k = 2) AS m_tokprog_b, anyIf(vsol0, k = 2) AS m_vsol0,
    anyIf(completer_b, k = 3) AS m_completer_b,
    -- curve life (scanned part, up to completion)
    sumIf(usol, k = 1 AND is_buy = 1) AS m_b_usol, sumIf(usol, k = 1 AND is_buy = 0) AS m_s_usol,
    sumIf(tok, k = 1 AND is_buy = 1) AS m_b_tok, sumIf(tok, k = 1 AND is_buy = 0) AS m_s_tok,
    countIf(k = 1 AND is_buy = 1) AS m_nb, countIf(k = 1 AND is_buy = 0) AS m_ns,
    minIf(slot, k = 1 AND is_buy = 1) AS m_fb_slot,
    maxIf(rsol, k = 1) AS m_rsol_max,
    sumIf(usol, k = 1 AND is_buy = 1 AND rsol >= 55000000000) AS m_l30_b_usol,
    -- launch window: first $launch_s s after creation
    sumIf(usol, k = 1 AND is_buy = 1 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_b_usol,
    sumIf(usol, k = 1 AND is_buy = 0 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_s_usol,
    sumIf(tok, k = 1 AND is_buy = 1 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_b_tok,
    sumIf(tok, k = 1 AND is_buy = 0 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_s_tok,
    countIf(k = 1 AND is_buy = 1 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_nb,
    countIf(k = 1 AND is_buy = 0 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_ns,
    maxIf(rsol, k = 1 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_rsol_max,
    groupUniqArrayIf(slot, k = 1 AND is_buy = 1 AND c_slot > 0 AND ts <= c_ts + $launch_s) AS m_l_buy_slots,
    -- creation slot ("bundle") and 60 s snipers
    sumIf(usol, k = 1 AND is_buy = 1 AND slot = c_slot) AS m_z_b_usol,
    sumIf(tok, k = 1 AND is_buy = 1 AND slot = c_slot) AS m_z_b_tok,
    sumIf(usol, k = 1 AND is_buy = 1 AND c_slot > 0 AND ts <= c_ts + 60) AS m_sn_b_usol
  FROM ev2
  WHERE g_slot > 0
  GROUP BY mint_b, user_b
),
coins AS (
  SELECT mint_b,
    any(m_g_slot) AS g_slot, any(m_g_ts) AS g_ts, any(m_c_slot) AS c_slot, any(m_c_ts) AS c_ts,
    any(m_creator_b) AS creator_b,
    anyIf(m_name, user_b = '') AS name, anyIf(m_symbol, user_b = '') AS symbol, anyIf(m_uri, user_b = '') AS uri,
    anyIf(m_cuser_b, user_b = '') AS cuser_b, anyIf(m_is_mayhem, user_b = '') AS is_mayhem,
    anyIf(m_quote_b, user_b = '') AS quote_b, anyIf(m_tokprog_b, user_b = '') AS tokprog_b,
    anyIf(m_vsol0, user_b = '') AS vsol0, anyIf(m_completer_b, user_b = '') AS completer_b,
    max(m_rsol_max) / 1e9 AS rsol_complete,
    sum(m_b_usol) / 1e9 AS curve_buy_sol, sum(m_s_usol) / 1e9 AS curve_sell_sol,
    sum(m_b_tok) / 1e6 AS curve_buy_tok, sum(m_s_tok) / 1e6 AS curve_sell_tok,
    sum(m_nb) AS curve_n_buys, sum(m_ns) AS curve_n_sells,
    countIf(m_b_usol >= 10000000) AS curve_n_buyers, countIf(m_s_usol >= 10000000) AS curve_n_sellers,
    arraySlice(arrayReverseSort(groupArrayIf(m_b_usol, user_b != '')), 1, 3) AS top3_b,
    arraySum(top3_b) / 1e9 AS curve_top3_buy_sol, if(length(top3_b) > 0, top3_b[1], 0) / 1e9 AS curve_top1_buy_sol,
    max(m_l30_b_usol) / 1e9 AS completer_sol, argMax(user_b, m_l30_b_usol) AS completer30_b,
    sum(m_l_b_usol) / 1e9 AS l_buy_sol, sum(m_l_s_usol) / 1e9 AS l_sell_sol,
    sum(m_l_b_tok) / 1e6 AS l_buy_tok, sum(m_l_s_tok) / 1e6 AS l_sell_tok,
    sum(m_l_nb) AS l_n_buys, sum(m_l_ns) AS l_n_sells,
    countIf(m_l_b_usol >= 10000000) AS l_n_buyers, countIf(m_l_s_usol >= 10000000) AS l_n_sellers,
    countIf(m_l_nb + m_l_ns > 0) AS l_n_wallets,
    arraySlice(arrayReverseSort(groupArrayIf(m_l_b_usol, user_b != '')), 1, 3) AS l_top3_b,
    arraySum(l_top3_b) / 1e9 AS l_top3_buy_sol,
    max(m_l_rsol_max) / 1e9 AS l_rsol_max,
    arrayFlatten(groupArray(m_l_buy_slots)) AS l_slots_all,
    length(arrayFilter(s -> countEqual(l_slots_all, s) >= 2, arrayDistinct(l_slots_all))) AS l_bundle_slots,
    if(length(l_slots_all) > 0, arrayMax(arrayMap(s -> countEqual(l_slots_all, s), arrayDistinct(l_slots_all))), 0) AS l_max_buyers_slot,
    countIf(m_z_b_usol > 0) AS z_n_buyers,
    countIf(m_z_b_usol > 0 AND user_b != m_creator_b) AS z_n_buyers_noncreator,
    sum(m_z_b_usol) / 1e9 AS z_buy_sol, sum(m_z_b_tok) / 1e6 AS z_buy_tok,
    countIf(m_sn_b_usol > 0 AND user_b != m_creator_b) AS sn60_n_buyers,
    sumIf(m_sn_b_usol, user_b != m_creator_b) / 1e9 AS sn60_buy_sol,
    sumIf(m_b_usol, user_b = m_creator_b) / 1e9 AS creator_buy_sol, sumIf(m_s_usol, user_b = m_creator_b) / 1e9 AS creator_sell_sol,
    sumIf(m_b_tok, user_b = m_creator_b) / 1e6 AS creator_buy_tok, sumIf(m_s_tok, user_b = m_creator_b) / 1e6 AS creator_sell_tok,
    sumIf(m_l_b_usol, user_b = m_creator_b) / 1e9 AS l_creator_buy_sol, sumIf(m_l_s_usol, user_b = m_creator_b) / 1e9 AS l_creator_sell_sol,
    arraySlice(arraySort(x -> x.1, groupArrayIf((m_fb_slot, m_b_usol), m_nb > 0)), 1, 20) AS first20,
    arraySum(arrayMap(x -> x.2, first20)) / 1e9 AS first20_buy_sol
  FROM mu
  GROUP BY mint_b
),
pools AS (
  SELECT mint_b, argMin(pool_b, slot) AS pool_b, min(slot) AS pool_slot, argMin(ts, slot) AS pool_ts,
         argMin(quote_b, slot) AS pool_quote_b, argMin(pcreator_b, slot) AS pool_creator_b,
         argMin(pbase, slot) AS pool_base0, argMin(pquote, slot) AS pool_quote0, count() AS n_pools
  FROM (
    SELECT block_slot AS slot, toUInt32(block_timestamp) AS ts, base58Decode(data) AS r,
           substring(r, 59, 32) AS mint_b, substring(r, 182, 32) AS pool_b, substring(r, 91, 32) AS quote_b,
           substring(r, 27, 32) AS pcreator_b,
           reinterpretAsUInt64(substring(r, 141, 8)) AS pbase, reinterpretAsUInt64(substring(r, 149, 8)) AS pquote
    FROM solana.instructions
    WHERE block_slot BETWEEN $s0 AND $s1_pool
      AND program_id = '$AMM' AND parent_index >= 0
      AND length(data) BETWEEN $L_AMM_CREATE_POOL_LO AND $L_AMM_CREATE_POOL_HI
      AND tx_signature NOT IN failed
  )
  WHERE substring(r, 1, 16) = unhex('$PREFIX$D_AMM_CREATE_POOL')
  GROUP BY mint_b
)
SELECT
  base58Encode(c.mint_b) AS mint, c.g_slot, c.g_ts, c.c_slot, c.c_ts, c.c_slot > 0 AS has_create,
  base58Encode(c.completer_b) AS completer, c.rsol_complete,
  base58Encode(c.creator_b) AS creator, base58Encode(c.cuser_b) AS create_user,
  c.name, c.symbol, c.uri, c.is_mayhem, base58Encode(c.quote_b) AS curve_quote_mint,
  base58Encode(c.tokprog_b) AS token_program, c.vsol0 / 1e9 AS vsol0,
  c.curve_buy_sol, c.curve_sell_sol, c.curve_buy_tok, c.curve_sell_tok, c.curve_n_buys, c.curve_n_sells,
  c.curve_n_buyers, c.curve_n_sellers, c.curve_top1_buy_sol, c.curve_top3_buy_sol,
  c.completer_sol, base58Encode(c.completer30_b) AS completer30,
  c.l_buy_sol, c.l_sell_sol, c.l_buy_tok, c.l_sell_tok, c.l_n_buys, c.l_n_sells, c.l_n_buyers, c.l_n_sellers,
  c.l_n_wallets, c.l_top3_buy_sol, c.l_rsol_max, c.l_bundle_slots, c.l_max_buyers_slot,
  c.z_n_buyers, c.z_n_buyers_noncreator, c.z_buy_sol, c.z_buy_tok, c.sn60_n_buyers, c.sn60_buy_sol,
  c.creator_buy_sol, c.creator_sell_sol, c.creator_buy_tok, c.creator_sell_tok,
  c.l_creator_buy_sol, c.l_creator_sell_sol, c.first20_buy_sol,
  base58Encode(p.pool_b) AS pool, p.pool_slot, p.pool_ts, base58Encode(p.pool_quote_b) AS pool_quote_mint,
  base58Encode(p.pool_creator_b) AS pool_creator, p.pool_base0 / 1e6 AS pool_base0, p.pool_quote0 / 1e9 AS pool_quote0,
  p.n_pools
FROM coins c
LEFT JOIN pools p ON p.mint_b = c.mint_b
ORDER BY c.g_slot

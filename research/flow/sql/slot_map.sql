-- slot_map.sql: slot <-> time anchors from solana.blocks at 15-minute granularity for [t0, t1).
-- One row per 15-minute bucket: (bucket start, first slot, last slot, blocks). <= 2,000 rows => <= 20 days per query.
SELECT toUInt32(toStartOfFifteenMinutes(block_timestamp)) AS t, min(slot) AS s_lo, max(slot) AS s_hi, count() AS n
FROM solana.blocks
WHERE block_timestamp >= toDateTime64('$t0', 6) AND block_timestamp < toDateTime64('$t1', 6)
GROUP BY t
ORDER BY t

# tests/fixtures/flow

`parity.json.gz` (147 KB) feeds `tests/test_flow_parity.py` and `tests/test_flow.py`. It holds six real coins from
the 2026-10-07/08 census. For each coin it has two sources: the recorded swap-api trades of the coin's first two
minutes, and the wave-2 lab's own rows for the same coins.

| Key | Source |
|---|---|
| `swap` | `GET swap-api.pump.fun/v2/coins/{mint}/trades` rows as served. The fields kept are `slotIndexId, tx, timestamp, userAddress, type, program, priceSol, amountSol, baseAmount`. They come from `LAB/trades_launch/*.json.gz` (`research/flow/collect_trades.py`), and both windows of each coin are complete. |
| `ch_trades`, `ch_minutes` | CryptoHouse `raw.sql` rows (successful transactions only, untruncated), from the validation cache `FLOW/validation/raw_*.json.gz`. The field order is in `source.ch_trade_fields`. |
| `graduate`, `b2_coin`, `b2_bars` | `FLOW/graduates.parquet`, `b2_coins.parquet`, and the `b2_bars.parquet` minutes that end inside the recorded window. |

The coins:

| Mint | Why it is here |
|---|---|
| `8Tj1fv3M…`, `CmCHvr99…`, `BdHJj3wQ…` | Instant graduates (g = creation). The BOOST AGENT shows up inside the window. `BdHJj3wQ` also has a pooled-account (`ARu4n5mF…`) trade. |
| `FBsA4Beg…` | 59 s on the curve, then PumpSwap. Nobody traded in the creation second. |
| `5ZbEkbmN…` | A Mayhem curve. SOL leaves the curve outside trades, so the reserve chain must break. |
| `3siP5yjv…` | Slow graduate (226 s). The window covers the launch only. |

The builder script is `build_fixtures.py` in the session scratchpad. It only reads research data. To regenerate the
fixture, rerun it against the same `FLOW` and `LAB` folders.

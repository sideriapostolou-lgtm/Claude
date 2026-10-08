# Test fixtures

Real API responses captured live on 2026-10-08 (trimmed to a few items),
unless marked **synthetic**. Use them through `fakes.load_fixture(name)` and
`FakeHttp.register_fixture(pattern, name)`.

| File | Endpoint | Notes |
|------|----------|-------|
| `dexs_token_profiles_latest.json` | DexScreener `/token-profiles/latest/v1` | list; item 2 is NOT solana (chain-filter test) |
| `dexs_boosts_latest.json`, `dexs_boosts_top.json` | `/token-boosts/latest/v1`, `/top/v1` | list; latest has a non-solana item (ethereum) |
| `dexs_search.json` | `/latest/dex/search?q=HIGGS` | `{pairs}` |
| `dexs_tokens_batch.json` | `/tokens/v1/solana/{csv}` | one top pair per token |
| `dexs_token_pairs.json` | `/token-pairs/v1/solana/{mint}` | list of pairs |
| `dexs_pair.json` | `/latest/dex/pairs/solana/{pair}` | `{pairs, pair}` |
| `gt_new_pools.json` | GeckoTerminal `new_pools?include=base_token,quote_token,dex` | includes meteora-dbc curve pool (reserve 0) |
| `gt_trending_pools.json` | `trending_pools` | |
| `gt_pool.json` | `pools/{pool}?include=...` | |
| `gt_trades.json` | `pools/{pool}/trades` | newest first |
| `gt_ohlcv_minute.json` | `pools/{pool}/ohlcv/minute?aggregate=1` | 10 rows, NEWEST FIRST, `[ts,o,h,l,c,vol_usd]` |
| `gt_ohlcv_invalid_aggregate_400.json` | same with `aggregate=7` | HTTP 400 error body |
| `gt_token.json` | `tokens/{mint}?include=top_pools` | launchpad_details |
| `gt_token_info.json` | `tokens/{mint}/info` | graduated token, holders populated |
| `gt_token_info_bondingcurve.json` | `tokens/{mint}/info` | curve token, holders null |
| `gt_tokens_multi.json` | `tokens/multi/{csv}` | |
| `jup_ultra_order_buy.json` | Jupiter `ultra/v1/order` SOL->HIGGS 0.1 SOL, no taker | `transaction: null`, `priceImpactPct` NEGATIVE (adverse), `feeBps: 10` |
| `jup_ultra_order_buy_insufficient_funds.json` | same with an unfunded taker | `transaction: ""`, `errorCode: 1`, `error: "Insufficient funds"`, amounts valid |
| `jup_ultra_order_sell.json` | `ultra/v1/order` HIGGS->SOL (selling the buy's output) | round trip ~ -1.6 % before network fees |
| `jup_ultra_shield.json` | `ultra/v1/shield?mints=` | severity `info` |
| `jup_ultra_holdings_empty.json` | `ultra/v1/holdings/{pubkey}` | empty wallet |
| `jup_ultra_holdings_synthetic.json` | **synthetic** holdings with one token | shape per docs |
| `jup_ultra_execute_success_synthetic.json` | **synthetic** `ultra/v1/execute` Success | shape per docs |
| `jup_ultra_execute_failed_synthetic.json` | **synthetic** `ultra/v1/execute` Failed | shape per docs |
| `jup_quote_buy.json`, `jup_quote_sell.json`, `jup_quote_bondingcurve.json` | legacy `swap/v1/quote` | NOT Ultra; positive `priceImpactPct`; reference only |
| `jup_price_v3.json` | `price/v3?ids=` | includes SOL |
| `jup_tokens_v2_recent.json` | `tokens/v2/recent` | `audit.isSus` example |
| `jup_tokens_v2_search.json` | `tokens/v2/search?query=` | full stats5m/1h/6h/24h |
| `jup_tokens_v2_toptrending.json` | `tokens/v2/toptrending/1h?limit=3` | |
| `rugcheck_report.json` | RugCheck `/tokens/{mint}/report` | clean graduated token; pool account in topHolders (exclude it!) |
| `rugcheck_report_risky.json` | same, risky token | danger risks, curve pool holds 50 %, creator history |
| `rugcheck_summary.json`, `rugcheck_summary_risky.json` | `/report/summary` | `lpLockedPct` unreliable |
| `rugcheck_report_unavailable_400.json` | **synthetic** body of HTTP 400 for very new mints | `{"error": "unable to generate report"}` |
| `rugcheck_report_not_found_400.json` | body of HTTP 400 from `/tokens/{mint}/report` for a mint RugCheck has not indexed yet (seen live 2026-10-08 on 6 s - 3 min old mints) | `{"error": "not found"}` -> `ReportUnavailable` (retry later) |
| `rugcheck_stats_*.json`, `rugcheck_rugs_ticker.json` | misc RugCheck stats | not used yet |
| `rpc_getAccountInfo_mint.json` | Solana RPC `getAccountInfo` jsonParsed (Token-2022 mint) | authorities null |
| `rpc_getTokenSupply.json` | `getTokenSupply` | |
| `rpc_getTokenLargestAccounts_429.json` | `getTokenLargestAccounts` on public RPC | DISABLED - do not depend on it |
| `pumpfun_candles_1m.json` | pump.fun `swap-api.pump.fun/v1/coins/{mint}/candles?interval=1m&limit=40` (INU `AACtro...pump`, captured 2026-10-08 20:58:38Z) | ASCENDING, `timestamp` in ms, USD decimal strings; only minutes WITH trades (12 no-trade minutes missing); the newest candle was still open. Used by `sources/pumpfun.py` (candle fallback) |
| `pumpfun_coins_v2.json`, `pumpfun_swap_*.json` | other pump.fun frontend APIs | reference only (not used: unofficial) |
| `pumpfun_census_coins.json` | pump.fun census `frontend-api-v3.pump.fun/coins?offset=0&limit=70&sort=created_timestamp&order=DESC&includeNsfw=true&complete=true`, saved by the strategy lab (`research/lab/fetch.py`) 2026-10-08 18:09:41Z | the 8 newest rows of the offset-0 page, raw (the lab's `_fetched_ts` removed); DESC by `created_timestamp` (ms); `PMX` is a Mayhem coin (`mayhem_state`). Used by the learning recorder tests |
| `pumpfun_candles_jet_1m.json` | pump.fun `swap-api.pump.fun/v1/coins/{mint}/candles?interval=1m&limit=1000` for JET `BhMNZt...pump` (created 1791404554), saved by the strategy lab, fetched 2026-10-08 18:11:54Z | 147 rows (< 1000: complete from creation), ascending, raw. Used by `raw_candles` and the recorder tests |
| `costs_golden.json` | **generated** from `nightcrawler.costs` on 2026-10-08 | monotone-pessimism golden file: round-trip cost % on a grid; `test_costs_port.py` fails if any value drops |
| `learn_trainval_returns.json` | **derived** from the strategy lab (TRAIN+VALIDATION coins only, never TEST) | 500 real per-trade net returns (random early entries, nightcrawler-like exits, lab costs), zero-centred; `test_evidence.py`'s null stream |

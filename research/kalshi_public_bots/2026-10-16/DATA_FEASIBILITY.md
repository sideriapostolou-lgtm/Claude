# Strobingn release: bounded dataset feasibility audit

**Verdict:** useful historical, approximately one-second REST quote samples and a limited depth sample; **not a sufficient tape for continuous quote survival, maker queue/fill reconstruction, subsecond exchange latency or verified fee-adjusted executable P&L.** No backtest, signal selection or tuning performed. Only the four authorized October 3/October 9 assets were downloaded. No other release data, sealed TEST or future Family A data was read.

## Provenance and exact source separation

[Release API](https://api.github.com/repos/Strobingn/kalshi-odds-app/releases/tags/scalper-data) returned **46 assets**. Its body describes daily cloud-recorder books, trades, settlements and spot files, and points to tools/research/recordings.py. Those producer and completeness claims are audited below. Release created October 9, 17:02:03Z, published 17:02:20Z.

The requested app pin `8e2cc6b4ab8e5fa8b1476894620fb217e67a27f7` has no `tools/research/recordings.py` (recursive tree absent; raw URL returned404). **Release tag resolves to a different commit, `df83fa93dd3bfb074929b40a7b516e516e742b20`.** At that tag, reader and cloud recorder sources exist and were read as text only:

- [cloud_recorder.py](https://github.com/Strobingn/kalshi-odds-app/blob/df83fa93dd3bfb074929b40a7b516e516e742b20/tools/research/cloud_recorder.py#L7): lines7–14 explicitly describe REST polling and runner receipt timestamps, with trade timestamps instead taken from exchange `created_time`.
- [book serialization](https://github.com/Strobingn/kalshi-odds-app/blob/df83fa93dd3bfb074929b40a7b516e516e742b20/tools/research/cloud_recorder.py#L81): lines81–89 take best YES/NO bid levels and derive asks by complement. Lines178–198 fetch Coinbase tickers and Kalshi orderbooks sequentially, then stamp `time.time()` after each request returns.
- [quantity parser](https://github.com/Strobingn/kalshi-odds-app/blob/df83fa93dd3bfb074929b40a7b516e516e742b20/tools/research/arb_scan.py#L234): lines234–256 round prices to4decimals and **floor quantities to whole contracts**. Thus these are normalized snapshots, not lossless exchange payloads.
- [reader schema](https://github.com/Strobingn/kalshi-odds-app/blob/df83fa93dd3bfb074929b40a7b516e516e742b20/tools/research/recordings.py#L14): dollars0–1, quantities contracts, spotUSD, epoch milliseconds, blank=missing. Reader's phone-specific sampling description differs from cloud REST polling; use the cloud source for this release's claimed producer.

**Still unverified:** no per-file producer commit, run identifier, clock synchronization evidence, request start/RTT, exchange book timestamps, raw response hashes or independent exchange reconciliation. The release tag's cloud recorder and reader do **not** define/write the `depth_*` schema. No depth recorder source was identified at either inspected tree. The observed15-level cap is an empirical property, not a certified collector setting. The separate WebSocket recorder writes `ws_*.csv.gz` with `recv_ns,...,exch_ms`, a different schema not among these inspected assets; it must not be used to describe them.

**Root independent spot-check:** the official public market response for `KXBTC15M-26OCT030545-45` gives strike **84585.68**, while release book/settlement rows store **84585.7**. Root response is preserved at `root/venue/market_oct3.json`, SHA256 `fc00b9cf271be98a21fa3a09548016a56f7c15f56223324cdef658b38e2d2e95`. Source `cloud_recorder.py` line61 formats floats with **six significant digits**, which explains this precision loss; spot values are serialized by the same formatter. Near-strike calculations must not treat these as exact official levels. Root also confirmed the official contract compares separate preceding60second BRTI averages, rounded to2decimals, with ties YES; Coinbase last trade is not the settlement definition.

No LICENSE/COPYING file found in either inspected tree; repository API license=null. Release body supplies no dataset license. Public download availability is not an established redistribution/reuse license.

## Download identity

All four entire gzip/CSV files fit the bound, totaling **4,545,172 compressed/plain bytes**. Each SHA256 exactly matches the GitHub release asset digest. Gzip decompression completed normally, without truncation salvage. October3 assets were uploaded October9 17:02Z; October9 depth was uploaded October10 05:10:54Z. These upload times do not certify collection provenance.

| File | SHA256 | Bytes |
|---|---|---:|
| book_2026-10-03.csv.gz | c448ac7e2a0003614be41a21ba0137d82497b810102a1c1f8c62d8561e84bb0e | 2,313,170 |
| spot_2026-10-03.csv.gz | f72bacfa203e07d5dbace85612182a18d2a834abf2e07be8eda0839dc828035c | 682,436 |
| settle_2026-10-03.csv | f082445049a0c8ba7ddff11cade77ba8557aec2586853fa5620aff65966c7db8 | 8,459 |
| depth_2026-10-09.csv.gz | a07e4f542c8db9e1757aa88ea6ea22b5602c9b637d9c3ef3dcd5b8a15acfdd66 | 1,541,107 |

Exact download URL prefix: `https://github.com/Strobingn/kalshi-odds-app/releases/download/scalper-data/` followed by each filename. Fully expanded URLs are preserved in `download_receipts.json`; original API metadata in `release.json`.

## Schemas and actual rows

Book CSV line1:
```
ts_ms,ticker,strike,close_ms,yes_bid,yes_bid_qty,yes_ask,yes_ask_qty,no_bid,no_bid_qty,no_ask,no_ask_qty
```
Line2:
```
1791019951771,KXBTC15M-26OCT030545-45,84585.7,1791020700000,0.46,5172,0.47,511,0.53,511,0.54,5172
```
This is a top-of-book snapshot: YES bid46c/5,172contracts; YES ask47c/511; no candle OHLC. YES ask is derived from NO bid, not an independent orderbook side. Timestamp=October3 09:32:31.771Z; scheduled close=09:45Z. No exchange sequence or source timestamp is stored.

Spot lines1–2:
```
ts_ms,product,price
1791019951637,BTC-USD,84570.1
```
This is a Coinbase last-trade ticker price in USD sampled at local receipt time, **not CF BRTI settlement reference** or a source-exchange timestamp. Source discards Coinbase ticker timestamp.

Settlement lines1–2:
```
ticker,close_ms,strike,result
KXBTC15M-26OCT030545-45,1791020700000,84585.7,no
```
Source polls market result every30s and writes scheduled close time into the file (`cloud_recorder.py`217–230); no actual observation/settlement-publication timestamp or underlying final index value. This is publisher-recorded API result, not an account receipt.

Depth line1: `ts_ms,ticker,yes_levels,no_levels`. Line2 begins:
```
1791568877568,KXBTC15M-26OCT091415-15,0.26:1795|0.25:6126|0.24:4615|... ,0.73:11182|0.72:6440|0.71:3291|...
```
Ellipses above abbreviate the actual complete line. Each side contains descending price:quantity pairs separated by `|`, at most15levels. The first row's best bids sum99c. Interpretation as YES/NO bid ladders is consistent with Kalshi semantics and schema, but exact depth writer and receipt-time meaning remain unverified.

## Measured coverage, without trading outcomes

Our own standard-library `inspect_samples.py` parses only these files. Full outputs are in `sample_stats.json`.

| Sample | Rows / markets | UTC span | Median spacing | Largest gap |
|---|---:|---|---:|---:|
| Oct3 BTC book | 49,765 / 58 |09:32:31.771–23:59:59.491|1,000ms|65.705s across observations;34.845s within one market|
| Oct3 BTC spot |51,905|09:32:31.637–23:59:59.298|1,000ms|34.970s|
| Oct3 BTC settlements |57 /57|09:45–23:45|15minutes|15minutes|
| Oct9 BTC depth |19,885 /24|18:01:17.568–23:59:59.537|1,000ms|573.962s, **within the same market**|

October3 book has149,145rows across BTC/ETH/SOL; spot155,715rows; settlement171rows. No input timestamp reversal or duplicate timestamp per asset observed. BTC book has872missingYESbid and1,016missingYESask rows;11rows timestamped after scheduled close. No crossed YES quote among complete pairs; complement identities agree. No fractional book quantity survives in these samples, consistent with flooring in source. The final book market closes atOctober4 00:00 and is absent from October3 settlement file, as expected; its result was not fetched.

Within the observed span,94.11% of BTC book second-bins and98.58% of BTC spot second-bins contain a row. These are descriptive occupied bins, **not feed completeness or fresh-quote coverage**; scheduling jitter creates multiple/missing bins. Entire first9½hours of October3 are outside the file. Depth occupies91.22% of its observed second-bins; both sides individually have563empty-ladder rows.15levels appear in18,473YES and18,639NO rows; prices range0.001–0.999. Missing beyond-level15 liquidity is unknown.

## What can honestly be tested

- **Yes, exploratory:** visible top quotes/spreads, sampled quote changes and persistence, level-limited depth sensitivity, coarse second-scale cross-feed association, and descriptive joins to publisher settlement labels. Explicitly exclude gaps and late rows. Same quote on adjacent samples does not prove it survived between samples.
- **No, from these files alone:** subsecond quote survival, causal exchange lead/lag, measured network/order latency, queue rank/cancellations, adverse selection at actual fills, full-depth execution, cancel races, or real profit/fees. No order IDs, acknowledgments, participant fill receipts, fee receipts, sequence numbers or raw book deltas are present. Fee schedules could be supplied externally for hypothetical calculations, but that does not make fills real.
- Release's “every public trade” claim is **not verified**. Authorized sample scope excluded trade downloads. Moreover, tag cloud recorder polls `/markets/trades` with limit1000 without cursor pagination (lines200–215), discards trade IDs from output and floors fractional trade count (lines92–104). A busy interval or restart could compromise completeness/deduplication. This is a source-level limitation, not a measured missing-trade count.

Dataset can augment TRAIN/exploratory engineering checks after provenance/license resolution. It cannot replace our own recorder and required sequence/coverage audit or certify a profitable maker replay. No future TEST read and no trading/configuration changes.

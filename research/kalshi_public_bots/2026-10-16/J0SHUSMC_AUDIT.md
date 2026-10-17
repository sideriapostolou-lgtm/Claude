# J0shusmc/Kalshi-BTC supplemental audit

Pinned source: `d5a55bf10c02ddc2b429eec78b1fd847fa1b6760`, read2026-10-16 UTC. [MIT](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/LICENSE#L1) covers original code/documentation, expressly excludes third-party market-data rights. Read-only public GitHub content only; no repository code imported/executed/installed, no private account or credentials accessed, no orders/Railway/owner sealed TEST. Only private audit files written.

**This repository supplies stronger evidence than a README claim: a positive public receipt subset reconciles internally. It still does not establish a profitable complete account, a validated current strategy, or executable historical backtest edge.** Its public source has serious paper-accounting and cutoff/parity problems, and its current source runs two lanes despite the historical three-lane headline.

## Independently recomputed public receipts

Input: [reports/btc15_trade_log.json L431](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_trade_log.json#L431) fills and [L2113](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_trade_log.json#L2113) settlements. Raw file SHA256 `d0d3f6176bcb1a23d93616fa0a53965634129d1613dc69281d8b894bcbea8df6`.

Our independent standard-library standard-library Decimal reconstruction (prepared privately) reads only the downloaded JSON and uses Decimal arithmetic; it never imports repository code. [per-market arithmetic](J0SHUSMC_RECEIPT_RECHECK.json) has every31 ticker with quantities, cost, fees, payout, local strategy tag and entry-order receipt join. All84 fill IDs and31 settlement tickers are unique. For **all31 tickers**, fill YES/NO quantities, side-price costs and fees exactly match the committed settlement export. All31 non-ERROR local buy order IDs join at least one actual-format fill record.

| Public-export calculation | Result |
|---|---:|
| Winning-side payout equivalent | $853.000000 |
| Both-side acquisition costs | $758.595000 |
| Fees in export | $16.271000 |
| Net subset P&L | **+$78.134000** |
| Positive / negative settled windows | 24 /7 |
| Fill coverage | 2026-08-27 23:48:20.924022Z through2026-09-16 16:24:46.145582Z |
| Settlement coverage | 2026-08-28 00:00:05.929012Z through2026-09-16 16:30:08.427734Z |

V2 export represents YES acquisitions as bid/action buy/outcome_side yes, and NO acquisitions as ask/action sell/outcome_side no. Closing YES/NO trades appear as acquiring the complementary outcome. The payout-equivalent minus both acquisition costs recovers the same trading cash result; never interpret raw `action:sell` on a NO acquisition as a sold NO without reading book/outcome side.

Tag attribution below uses each ticker's unique local non-ERROR buy strategy label. It is an **internally joined descriptive subset**, not proof that no manual/other strategy intervened or that the current commit ran at those historical times.

| Local entry tag | Settled windows | Net public-subset P&L | Fees |
|---|---:|---:|---:|
| Old PULLBACK_99 |18|−$1.646900|$6.251900|
| NO_RECLAIM_80 |2|+$6.014300|$1.365700|
| BTC_FADE_90 |8|+$32.050000|$6.640000|
| RECLAIM_70 |3|+$41.716600|$2.013400|
| Three newer tags combined |13|**+$79.780900**|$10.019100|

The small subset cannot establish durable edge;40 of84 fill rows report zero fees. Use actual posted fees in this calculation; do not generalize them into an always-free fee assumption.

The [committed snapshot L2](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_live_latest.json#L2) separately reports account+$81.22 versus selected starting$115, cash$195.62 +position value$0.60. The exact receipt subset differs by$3.086; the source also rounds each market's P&L to whole cents, producing+$78.14 in its local stats. We have no funding, withdrawals, adjustments, rebates or complete start-of-period account history to explain the gap. Public file authenticity and omissions are unverified. Do not label this independently authenticated full-account profit.

## Actual entry, timing, exit and size

Shared current entry predicate: [btc15_live_monitor.py L2095–2184](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L2095). Wait first5 minutes; examine first5 side-ask lows, minute5 close and latest candle body/close. The last received candle is indexed6–10, closes above minute5 close, and has positive ask body. Require current side ask in lane band and>=5min before market close ([L2644–2647](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L2644)). At most one entry per ticker/side/strategy via entered-signals. No calibrated probability or fee-net expected-value model is used to generate these signals.

| Lane | Exact reconstructed gates | Target / status |
|---|---|---|
| RECLAIM_70 YES | First5 ask low **>15c and<=30c**; latest completed/received candle close35c<=x<55c and green/reclaims m5; live ask35–55c inclusive; first5 BTC return−20<=USD<=20; BTC distance to15m EMA21−150<=USD<−50 | Sell70c. Active current config at [L2068–2070](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L2068). |
| BTC_FADE_90 YES, historical | First5 low>25c<=30c; minute6–10 side close45c<=x<65c, green/reclaims m5; live ask<=65c; first5 BTC moved−75 to−25USD | Advertised90c. **Retired September22** in [L49–51](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L49); absent from current configs and selected-signal reasons. Gates reconstructed from [first5 recovery report L37](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_first5_btc_recovery_research.md#L37) and historical snapshot signals; not a current implemented branch. |
| NO_RECLAIM_80 NO | First5 side ask low>35c<=40c; latest close50c<=x<70c, green/reclaims m5; current ask50–70c inclusive; side-signed first5 BTC change−75 to−25USD, meaning actual BTC **rose25–75USD** against NO; no EMA gate | Sell80c. Active current configL2070. |

The historical [default-strategy report](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_default_strategy.md#L6) claims60/58/44 signals,162 total/66.95days, net8.48/6.02/7.57c per contract after general quadratic taker fees, no slippage. Those are selected historical candle-score claims, not independent future tests. The current source and current two-lane combination do not reproduce that three-lane report simply by running monitor.

Sizing: [L1319–1341](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1319) defaults20% of cash and **ceil(budget/entry_price)**, so quantity can exceed the named budget by nearly one contract before fees. Risk_pct0 uses fixed5contracts. No per-window/daily stop/max total-risk cap is evident in this path; entered/pending guards are not a global budget reservation. Paper mode sizes from marked **equity**, not available cash ([L1813–1815](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1813)). These are author's defaults, not recommended settings or money authority.

Live: [L489–529](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L489) uses modern event-order bid/ask, fixed-point counts/YES-price, hard-coded exchange_index2, GTC, post_only false, STP. Limit buys at observed ask can rest if book moves. Exit is separately staged GTC sell at target after observed position; no ordinary stop-loss. There is no cancellation/repricing lifecycle that pulls a resting buy when its signal vanishes in this inspected source. No durable intent before create: pending/entered bookkeeping and file save occur after send. Broad exception path stores a failed-entry record and retries after60s rather than proving an uncertain create absent. Position reconciliation uses current-market positions/resting orders, not per-fill sequence as execution authority ([L1535–1611](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1535)). Old GET-single-order helper remains defined; no current call was tested.

## Historical live exits do not match advertised targets

[lane exit comparison](J0SHUSMC_LANE_EXITS.json) joins all13 newer-tag entries to fills and complementary close legs. All12 winners closed at effective **70c**, including7 BTC_FADE entries advertised90c and2 NO_RECLAIM entries advertised80c; one BTC_FADE entry never closed and lost$26.84. Every closed local record is tagged **ACCOUNT_SYNC** with70c price. This agrees with a known source bug, rather than demonstrating80/90c target performance.

Current [sync_open_positions L1482–1511](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1482) explicitly explains that adopting a newly filled entry too soon assigns generic Reclaim70 target to other strategies; the current guard skips adoption when matching pending buy exists. The repair is not proof that all races/restarts are solved, but it corroborates why the historical receipt behavior differs. Generic account adoption still uses70c. The successful small public subset is a **different realized policy** from the published high-target backtest.

## Paper ledger cannot validate hit rate or drawdown

- [manage_paper_trades L1366–1396](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1366) processes only positions whose ticker equals the current market, and closes only when current bid>=target. There is **no paper expiry/official settlement or full-loss path**. An expired loser can remain open forever, omitted from closed hit rate.
- [compute_paper_stats L1246–1264](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1246) then marks every open position using **the current market's same-side quote without ticker matching**, even for old markets. That can contaminate paper equity and next position size. Missing bid is marked zero; current unrelated bid is not a valid old-market valuation.
- [L1404–1439](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1404) instantly fills requested entry quantity at observed ask, no delayed depth/partial fill. Target exit similarly assumes full quantity at observed bid; no order queue/liquidity or cancellation risk. A GTC target fill and a later observable top bid are different evidence.
- Fee function [L86–97](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L86) uses7% quadratic rounded0.0001USD per order, closer to current direct-member debit granularity than old whole-cent models, but no complete per-fill/per-order accumulator or current series schedule. Paper open valuation reserves estimated roundtrip to target rather than actual fee receipts.
- Committed paper ledger at [JSON L2571](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_trade_log.json#L2571) contains only **2 buys /2 sells**, both old Reclaim70 winners at71c with old flat6.5c/contract fee. Exact stored gross1548c−fee357.5c=net1190.5c ($11.905); source rounds individual trade stats to1190c ($11.90). Those records are not a current three-lane forward paper sample. Full-loss handling missing in source makes100% closed paper hit rate unusable.

## Lookahead and research/live parity

**Concrete one-minute lookahead in the first5/EMA research BTC join.** [fetch_btc_coinbase.py L71–73](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/fetch_btc_coinbase.py#L71) preserves raw Coinbase candle timestamp as `ts`. Coinbase timestamp labels candle **start**, as the live source itself recognizes by adding1minute when checking availability. But [btc15_first5_btc_recovery_research.py L53–62](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_first5_btc_recovery_research.py#L53) and [btc15_ema_decision_research.py L65–80](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_ema_decision_research.py#L65) join Kalshi **minute_end** to BTC **ts** with nearest tolerance45s, then use that BTC close/high/low/volume.

At claimed decision00:05, the exact matching BTC timestamp00:05 is the candle that closes00:06. Thus first5 BTC close includes one extra future minute, and first BTC open starts00:01 instead of00:00. EMA research resamples start-labelled BTC candles `closed='right', label='right'` ([L47–60](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_ema_decision_research.py#L47)), producing different15m close boundaries too. Selection bins conditioned on those features are affected. This is a source-level causal-clock defect; we did not rerun third-party research to quantify its return impact.

Live source instead checks `open_time < row.ts+1min <=decision_time`, and computes15m bucket closes from actual close times ([L1977–2027](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1977)). Therefore the published selected historical regimes and live regimes are not feature-identical. Another research file already understands this correctly: btc_classifier_research.py shifts feature cutoff−1minute before joining; that correction is not used by the two relevant scripts.

Other limitations:

- The EMA/first5 scripts search many low/close bands, sides, targets, BTC/EMA bins and inspect chronological quartiles/weeks **on the same sample** ([EMA L151–182](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_ema_decision_research.py#L151), [L208–265](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_ema_decision_research.py#L208)). Quartile positivity after selection is not an untouched future holdout or multiple-testing correction.
- Broad research scores target from `future_max_bid`, otherwise **full entry loss**, even if official settlement would pay. This is conservative for non-target payouts, but cannot cure optimistic target fills, feature leakage, or search bias. Backtest entry=signal ask close; live additionally requires the later current ask in-band and uses that changed ask. Source updates candles15s and BTC context60s, with60s429backoff; stale cached candle sequence has no independent age/complete-bar gate before entry.
- Live side candles and source backtests enumerate available candles as minute1,2,… rather than proving timestamps/no holes ([L2039–2044](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L2039)). Missing candles can shift the claimed first5/latest minute.
- Published first5/EMA research imports `reports/btc15_minute_candidates.parquet`, whose complete generation path was not found in the inspected published scripts. We did not independently regenerate that parquet/default60/58/44 counts. The different directional-dip research does exclude the fill candle for target hits and uses discovery folds0–2 vs fold3 validation, but then ranks filters using both positive sets. It is not the implementation used for default-lane return claims.
- `sync_kalshi_live_records` overwrites previous fill/settlement arrays with one limit1000 API page ([L1040–1048](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/scripts/btc15_live_monitor.py#L1040)); no cursor archive, immutable append receipt or account-wide completeness certificate. The committed before_stats_reset file preserves older mixed/failed orders separately; current snapshot/source are later than the receipt period.

## Concrete transferable experiment

J0shusmc is worth a **narrow independent replication**, not wholesale deployment: it has public real-format receipts with positive internally consistent arithmetic and a precise candle-reclaim hypothesis. In existing research only, freeze source-correct timestamps/first-visible prices and two explicit exit policies (all70c versus advertised70/80/90c). Reconstruct current two-lane and historical three-lane rules separately, enumerate every searched configuration, reserve future validation before viewing it, and report net per-contract/window P&L, dollar risk, bid-depth survival, queue/cancel uncertainty and losses. Compare no-BTC-context/market-only controls. The source-correct cutoff must first be shown to preserve or destroy the candidate edge; the leaky selected backtest numbers cannot be accepted.

For implementation feasibility, independent offline fixtures should force expired paper losers to official settlement, reject cross-ticker marks, reconcile partial entry/exit receipts and retain uncertain creates. No live code/settings/caps/stop/resume authority follows. This audit does not solve our current practice0 vs7real receipt gap or demonstrate our own bot profitable.

All selected public fetches succeeded. Full raw source inventory/checksums are in SOURCES.json. No third-party tests/backtests executed; verification consists of immutable source inspection, source/schema reasoning and our independent Decimal arithmetic over committed public JSON. Public source may be edited or incomplete outside this pin; exact historical executable/config hashes remain unknown.

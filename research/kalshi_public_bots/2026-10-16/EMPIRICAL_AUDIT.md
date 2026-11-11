# Independent source audit: six public Kalshi research bots

Audit date: 2026-10-16 UTC (2026-10-15 Pacific at retrieval). Requested role: Astra/high. Public research copy; integration owner owns publication. Project instructions read from connected GitHub at cc55c07b9cd01e4231f86124e6a446d0439f306b, including newest Kalshi-first work order. Local stale checkout lookup initially failed to resolve current docs; resolved through connected GitHub, not evidence that the repository lacked those docs. Prior REPORT and October14 sweep read before research. All third-party code read as text, never executed/imported/installed. Own standard-library arithmetic only; no private account, orders, credentials, Railway, runtime/config or public-repository writes. No local sealed TEST read.

**No independently verified profitable live bot found.** Best forward lead is a mixed-rule paper ledger; best maker lead remains statistically inconclusive. All six API license fields are null and recursive trees contain no LICENSE/COPYING file: no explicit reuse license established. Learn concepts; do not assume permission to copy source.

## Exact pins

| Repository | Default branch | Exact HEAD | Commit UTC |
|---|---|---|---|
| aurascoper/brti-edge | master | df709577eebdf39efdb6d148d30cd2daff125668 | 2026-09-21 22:24:55 |
| mlysophia/kxbtc15m-overbet-study | main | a904abe18bba500c9ac5d04fd43dfd61b18c6485 | 2026-08-30 10:43:46 |
| artyomderkach-bit/btc-15m-vol-backtest | main | 8796d10d5e9d8bf99f16de769a758911a0f74759 | 2026-04-29 17:04:13 |
| rodiiipooo/kalshi-crypto-regime-edge | master | 73708296532ae163e369fe1f494d47ef6a41f099 | 2026-06-27 08:55:30 |
| elhamwork/btcbot | claude/btc-kalshi-backtester-w74k71 | 708f0a26aa58fcd6e45e9a5e621aea5f61b82b4c | 2026-10-16 00:44:02 |
| hudsonjoshuaclark/kalshi-bot | master | 8c2dd221ab9432dd8c91cbebb0e73f7dc60e26d8 | 2026-09-14 04:19:42 |

API push time is not commit time: aurascoper metadata says October10 push, but default HEAD commit remains September21. `SOURCES.json`, six metadata/commit/tree files and local source copies preserve exact evidence. URLs below use immutable commit pins.

## 1. elhamwork: forward paper history, with a material strategy mixture

[README](https://github.com/elhamwork/btcbot/blob/708f0a26aa58fcd6e45e9a5e621aea5f61b82b4c/README.md), [decision source](https://github.com/elhamwork/btcbot/blob/708f0a26aa58fcd6e45e9a5e621aea5f61b82b4c/check.py), [published state](https://github.com/elhamwork/btcbot/blob/708f0a26aa58fcd6e45e9a5e621aea5f61b82b4c/cloud_state/check_memory.json).

Reconstruction: Gaussian probability from log(spot/strike), recent volatility and remaining time; Coinbase-to-BRTI level adjustment; calibration bins updated with settled outcomes and a historical prior. Favor the model's side; ask price70–90c, model-minus-ask>=7c, spread<=5c, at least 10 minutes remaining, same-side qualifying observation>=1.5 minutes earlier (README says two minutes), no intervening side reversal. Re-fetch price and spot before recording a call (check.py2153 onward); one call per market. Full hypothetical stake at displayed ask, no execution or queue simulation. Compounding stake defaults10% in current code, with other historical variants.

**Independently verified publisher-data arithmetic:**628 distinct settled paper markets,520 wins,108 losses, first recorded call August24 04:00:43Z through October15 23:02:10Z. Summed `paid`=$1,400.78; summed fee=$1,616.42. Published bank=$2,400.82 from$1,000 differs by4c from sum; historical quantities rounded to0.1 contracts produce per-row reconciliation differences up to5c. These small discrepancies are not the main disqualifier. No venue fill receipt exists: this is a signal/paper ledger, not live P&L.

**New important finding:**628 is not a frozen advertised-rule record.613 `GOOD` calls yield506wins/107losses,+$1,093.45;6 `REVENGE` calls explicitly labeled50%bank at92–98c all win,+$229.75;9 `WEAK`/`NONE` calls net+$77.58. Revenge calls span September10–14. Excluding their dollars does not reconstruct the compounding counterfactual, since they alter subsequent sizing. Historical records also contain stale first-observation fields explicitly acknowledged in code. Thus628/520 is descriptive, not validation of today's70–90c rule.

Mean price=79.8231%, which matches README's79.8% purported break-even but omits fees. Mean(price+fee/contracts)=80.9321% across these recorded trades (equal-trade diagnostic, not exact variable-stake portfolio break-even). Observed82.8025% is still above that point estimate; inferential/selection and execution problems remain. Full-ask-fill assumptions do not establish size availability, latency, market impact or feasible phone execution. Published archive includes53days of orderbook files, but this audit did not join all of them to calls or certify capture completeness.

Earlier report honestly records a bar-start look-ahead bug turning+28.7%ROI into−29.30%; current report's dates June17–August20 span63days while stale prose still says14days. Around130 ideas inspected and historical bands selected; forward rule-version provenance would be needed to claim out-of-sample performance. This is worth further **fixed-rule paper validation**, not copying live or compounding aggressively.

## 2. aurascoper: useful maker mechanics, old glimmer unconfirmed

[May passive study](https://github.com/aurascoper/brti-edge/blob/df709577eebdf39efdb6d148d30cd2daff125668/docs/research/kalshi-passive-policy-btc-touch-depth50-2026-05-26.md), [queue source](https://github.com/aurascoper/brti-edge/blob/df709577eebdf39efdb6d148d30cd2daff125668/apps/data-collector/src/replay/queueModel.ts), [August close](https://github.com/aurascoper/brti-edge/blob/df709577eebdf39efdb6d148d30cd2daff125668/analysis/w2/w2prime-close-report.txt).

The prior sweep's30h result is present:125KXBTC15M markets, one-contract best YES/NO bids each60s, front/back/50%-depth queue assumptions. At50%-depth/to-expiry:56.3%fills, settlementEV~+0.35c/posted;2,860 usable quotes,t~0.83,zero not rejected. Last3minutes254quotes,+2.71c/posted is exploratory bucket selection, not new proof. Queue source consumes appropriately sided historical trades at exact price, tracks initial queue ahead and partial fills; does not identify cancellations ahead. Quotes share market outcomes and can share historical tape, so quote-count t-stat is not a robust independent-trade significance test. Ignoring cancellations need not conservatively bound P&L: queue position changes which adverse fills occur.

**Additional caveat checked at source:**the original125market settlement labels were inferred from late-market mid;117high-confidence,4low,4none. Authoritative REST settlements were listed as unfinished. Original+0.35c is therefore weaker than a verified official-settlement replay. No raw30h corpus reproduced here.

Later scorer rejects dumb strategy robustness: NO side negative, removing best time bucket flips total negative. RefinedYES/late/Asia fails single-market concentration58.7%; partial9.53h shakeout−$4.263 is explicitly not eligible holdout. May30v2 run on design corpus is VOID, not genuine OOS rejection (59.7%coverage,15hgap;109posted/21filled). Preserve those distinctions.

**Newer than prior sweep coverage:**August6–20W2prime close saysNO-GO(data),shadow29.82%coverage/max228.01hgap,collector94.94%/3hmissingrun,1327exchange settlements vs1299local(28missing),freeze passed,scorer not consulted. Separate W2doubleprime precommit corrects an earlier outage diagnosis to scheduled exchange maintenance; an August4power gap remains real. These files do not turn ineligible results into a profitable validation. README's six live rounds285fills/51.2%/−$32.99 are **author-reported live losses**; committed JSONL contains aggregate rounds, not285venue receipts, so do not call independently reconciled live results.

## 3. mlysophia: positive backtest highly sensitive to tradability

[Study source](https://github.com/mlysophia/kxbtc15m-overbet-study/blob/a904abe18bba500c9ac5d04fd43dfd61b18c6485/study.py), [complete sensitivity table](https://github.com/mlysophia/kxbtc15m-overbet-study/blob/a904abe18bba500c9ac5d04fd43dfd61b18c6485/results/threshold_080_ladder_summary.csv).

Rule:carry latest public trade prices forward; either side>80c for more than half a1–10minute observation window; then select favorite at first following trade, assume$100 purchased there; hold settlement. It can change favored side during qualifying time and buy a different side at entry. Fees0.07*N*p*(1−p), archived historical rounding; no actual ask/depth/latency. Public tape trade price is not a standing executable offer.

Published universe23,462 finalized markets December10,2025–August19,2026;19,497signal rows over4,960markets. Five-minute selected version1,393trades/1,288wins,+$2,998.22 afterfees; +1cslippage+$1,512.59;+2c+$72.71. Capacity filter using observed print quantity leaves103trades,+$130.01 at0slip;2c leaves110trades,**−$16.78**. Capacity counts rise because$100 buys fewer contracts at higher prices. Even this filter cannot demonstrate that historic taker's liquidity remained for us.

Ten-minute variant4,734trades−$1,454.87; regime boundaries selected after observing return path. README admits inspected windows/no untouched OOS and omitted0.70/0.90runs. Raw8.8GiB trade archive excluded, so signal extraction cannot be independently rebuilt from this repo. Committed summaries checked against source and downloaded Parquet, but Parquet arithmetic not rerun because no reader installed; no dependency install or third-party execution. Treat numbers as published backtest, not independently reproduced profit.

## 4. artyomderkach: large candle-simulated returns, fills unestablished

[Strategy](https://github.com/artyomderkach-bit/btc-15m-vol-backtest/blob/8796d10d5e9d8bf99f16de769a758911a0f74759/btc15m_backtest/strategy.py), [current ledger](https://github.com/artyomderkach-bit/btc-15m-vol-backtest/blob/8796d10d5e9d8bf99f16de769a758911a0f74759/btc15m_backtest/charts/btc_main/current_strat_full_tradelog.csv).

Default rule:post10c buys both sides, cancel opposite after fill, cancel remaining entries after4minutes, seek40c resale, settle leftovers; risk1%bankroll per side. Candle low/high touching limit supplies assumed fill capped at10%of total candle volume. No price-level volume, queue-ahead or taker-side proof. TP fill probability defaults1; optional random thinning is not measured queue position. Same-bar buy/resale guard is useful, but does not establish real fills. Stops can assume exact stop-price execution and apply maker fee; cancellation is instantaneous. Fee hardcoded maker0.0175 formula, not current-series verified.

Independent ledger inventory:3,322rows/1,389markets,December12,2025–April6,2026;1,674buy-fill rows,879sell-fill rows,769settlements. Final simulated bank19,493.89 from1,000 =>+$18,493.89; **not live**. Do not sum its `pnl` column: buy rows are cash debits, sale/settlement rows are net-P&L, giving meaningless−$55,253.91 when combined. Published parameter-sweep summary ranges+$5,422.26baseline to+$20,283.18selectedvariant, using repeatedly inspected corpus. No untouched/live account evidence or feasible size demonstrated. Good negative-control candidate:rerun logic only under conservative recorded queue/price-level trade constraints.

## 5. rodiiipooo: in-sample midpoint fantasy is not executable alpha

[Feature source](https://github.com/rodiiipooo/kalshi-crypto-regime-edge/blob/73708296532ae163e369fe1f494d47ef6a41f099/cross_asset_15m.py), [backtest](https://github.com/rodiiipooo/kalshi-crypto-regime-edge/blob/73708296532ae163e369fe1f494d47ef6a41f099/make_figures.py).

At minute 5, use BTC/ETH direction since open and realized/prewindow volatility bins; selected joint-down states buy NO, selected joint-up states buy YES, then hold to resolution. Positive correlation dominated 99.5% of the 10-day May 31–June 10 sample. Claim: 833 trades, 72.9% wins, $26.05. `make_figures.py` lines 371–382 explicitly invent execution as midpoint ±0.5c, with fee 7%*p*(1−p). README abstract calls the total gross but code subtracts fees; no ledger/data available to resolve the claim. Data are gitignored and external cached inputs absent.

Source loads Alpaca one-minute close at unchanged bar timestamp and matches it directly to Kalshi timestamp (`cross_asset_15m.py` lines 90–93, 182–192), with no demonstrated bar-end correction. Potential one-minute lookahead must be resolved against provider timestamp semantics before reusing conclusions. It uses its own spot window-open value rather than actual strike for direction. Many repeated observations per contract underlie apparent thousand-observation confidence. State selection and exclusion of the losing up/excess state after seeing PnL are explicitly in-sample. Net-edge tables subtract half-spread even from negative signed edges, exaggerating negative magnitude if interpreted as tradable NO profit. This repository cannot independently establish profitability.

## 6. hudsonjoshuaclark: honest failed tests, inconsistent recommendation

[Volatility results](https://github.com/hudsonjoshuaclark/kalshi-bot/blob/8c2dd221ab9432dd8c91cbebb0e73f7dc60e26d8/research/VOLATILITY_RESULTS.md), [calculation](https://github.com/hudsonjoshuaclark/kalshi-bot/blob/8c2dd221ab9432dd8c91cbebb0e73f7dc60e26d8/research/volatility_common.py), [recommendation](https://github.com/hudsonjoshuaclark/kalshi-bot/blob/8c2dd221ab9432dd8c91cbebb0e73f7dc60e26d8/research/FINAL_RESEARCH_RESULTS.md).

Strongest published rule: at minute 9, use realized standard deviation of 120 returns, scaled by spot; implied volatility comes from Phi^-1(mid), spot/strike displacement and time left minus 40 seconds. Require abs(z)>=0.15 and IV/RV>=2; buy spot's side at ask (or 1−bid), then hold. Code corrects the old 90x IV/RV units bug and aligns Coinbase bar start at entry−60s. Uses one contract and cent-rounded taker fee. No depth/latency model; fee rounding must not transfer to the current account unchanged.

Author-heldout 200 trades earn $7.148 (3.574c/trade), raw p=.0253; 152 close-time clusters give CI −0.86c to +8.01c. Corrected p=1.0 after 114 volatility configurations or 298 total recommendation searches. Underlying-down PnL is +$15.555 and underlying-up −$8.407. BTC subset is 58 trades and about +$1.58, not 200 BTC trades. Official study verdict is FAIL, size 0; later recommendation changes wording to TRADE SMALL without satisfying gates. No evidence the author traded profitably.

Negative evidence preserved: corrected original IV/RV heldout −$8.53/208; cost-filtered −$8.70/172; two-touch TRAIN −$184.295/5,550; quote-impulse TRAIN −$6.164/1,092; spot-shock heldout +$0.515/51, corrected p=1. This is not a new independent replication: published reports and implementation were read, without outcome rerun or raw withheld-data consumption.

## Best next hypothesis, not a live winner

The best *new forward-record lead* is elhamwork's persistent 70–90c favorite disagreement, after fixing one rule/version and removing the heterogeneous bet history. The best *fit to our existing maker recorder* remains the already-known late-window maker/adverse-selection hypothesis. Neither is new proof. Preregister a small fixed comparison using the existing Kalshi KXBTC15M recorder only: official settlements, contemporaneous reference/quote timestamps, actual series fees, realistic arrival delay, available depth, conservative queue bands, partial fills and cancel races, and clustering by window/day. Include costs and all skips. Keep author history exploratory; future TEST stays unopened until the freeze. No real cap, stop or resume change follows.

Failure/limit record: initial stale local document lookup resolved with connected GitHub. Broad text-fetch filter accidentally excluded the artyom backtest folder by name; required sources were subsequently fetched individually. All 257 initial remote fetches succeeded. No Parquet reader installed; raw archives/producer data often absent. No full book-call join or official settlement reconciliation performed. Evidence arithmetic is limited to published ledger fields, not exchange authenticity. No full independent strategy backtest was run. Reproduce bounded ledger arithmetic with our own `audit_arithmetic.py`; it imports no third-party repository code.

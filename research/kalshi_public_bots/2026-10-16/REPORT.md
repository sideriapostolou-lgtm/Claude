# Public Kalshi BTC 15-minute bots: source and evidence review

Source retrieval began October 15, 2026, 5:45 PM PDT (October 16 UTC); review and publication resumed after 6:33 PM PDT following an interrupted worker session. Exploratory public research, building on the October 13/14 surveys. This report changes no trading code, production service, financial settings or orders. No sealed TEST or future Family A observations were opened.

**A substantially better lead was found:** J0shusmc publishes a positive, internally reconciled fill/settlement subset for actual `KXBTC15M` tickers. Two independent Decimal calculations agree on **+$78.134 after $16.271 fees across 31 settled markets**, with 24 positive and seven negative markets. This is stronger than a screenshot or backtest, but still a publisher-supplied export, not an authenticated complete account audit. Its current rules differ from the historical rules. There is no basis yet to call any reviewed project a proven profitable replacement for our live bot.

## What was searched and checked

Four GitHub queries (`KXBTC15M`, `kalshi 15-minute bot`, `kalshi bitcoin bot`, `kalshi market maker`) returned 134 rows / **123 distinct repository names**. These are metadata discoveries, not 123 audited bots. Keyword spam, duplicates in query results, thin README projects and unrelated markets were not treated as successful implementations. Eighteen selected projects received pinned source/evidence reviews; this includes research projects and a data/Android app, not eighteen verified trading bots. Selected relevant files were inspected, not every file in each repository. Search coverage is bounded and cannot prove that no profitable public bot exists elsewhere.

Root reviewed six projects; an implementation reviewer inspected six others; an independent evidence reviewer inspected six empirical projects, the external dataset and the positive ledger. All external code was read as untrusted text. No dependency installation, external imports/execution, account access, order calls, binaries or commercial service purchase. Our own standard-library arithmetic and CSV diagnostics are separate from a strategy backtest. Exact pins are in [SOURCES.json](SOURCES.json); discovery-only rows are in [DISCOVERY.json](DISCOVERY.json).

Earlier reports remain valid historical records. New work here includes the internally reconciled public receipt subset, current-versus-historical rule differences, additional source-level accounting failures, newer negative/invalid maker validations, mixed-rule paper history, and an actual bounded format/coverage audit of the previously unverified Strobingn release.

## Ranked leads

| Project | What actually merits attention | Evidence and decision |
|---|---|---|
| [J0shusmc/Kalshi-BTC](https://github.com/J0shusmc/Kalshi-BTC/tree/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760) | Cheap-side reclaim after an early dip; selected Bitcoin trend/regime context; target resale | Best public receipt lead: 84 unique fill rows / 31 settled markets reconcile exactly to +$78.134 after fees. Historical rules/targets vary, current source retires BTC_FADE, and research has a timestamp leak. Investigate causal reclaim independently; do not copy historical headline EV or deploy its paper ledger. |
| [elhamwork/btcbot](https://github.com/elhamwork/btcbot/tree/708f0a26aa58fcd6e45e9a5e621aea5f61b82b4c) | Persistent favorite: model disagreement with a displayed 70–90c ask, confirmed on two observations | 628 settled paper calls / 520 wins; own arithmetic sums +$1,400.78 and $1,616.42 fees. Mixes 613 GOOD, six 50%-bankroll REVENGE and nine other calls. No realistic fill proof or single frozen-rule history. Useful second hypothesis, not a live return. |
| [zhangmatt/kalshi-btc-mm](https://github.com/zhangmatt/kalshi-btc-mm/tree/24cde982c8a154308dd24a693edfa79ff59ec2e8) | Actual BRTI-average pricing, inventory skew, toxicity filter, queue-ahead and delayed cancel replay | Best engineering reference among root's reviews, but forward paper **−$2.54/window over 71 windows**. Relative improvement over a worse baseline is not profitability. Study loss avoidance and settlement modeling; not a winner to copy. |
| [hudsonjoshuaclark/kalshi-bot](https://github.com/hudsonjoshuaclark/kalshi-bot/tree/8c2dd221ab9432dd8c91cbebb0e73f7dc60e26d8) | Minute-nine implied/realized volatility disagreement | Published held-out +$7.148 / 200 multi-asset trades; BTC only about +$1.58 / 58. Multiple-testing-adjusted p=1, confidence interval crosses zero. Source's formal gate says FAIL. Measurement reference only. |

### The positive receipt subset: exactly what it proves

[Pinned public export](https://github.com/J0shusmc/Kalshi-BTC/blob/d5a55bf10c02ddc2b429eec78b1fd847fa1b6760/reports/btc15_trade_log.json), SHA256 `d0d3f6176bcb1a23d93616fa0a53965634129d1613dc69281d8b894bcbea8df6`. Fill timestamps span August 27, 4:48:20 PM PDT through September 16, 9:24:46 AM PDT; settlement timestamps span August 27, 5:00:05 PM through September 16, 9:30:08 AM PDT. Sparse selected markets over this period do not establish continuous collection or trading every window.

For each ticker, independently total YES/NO receipt quantity, outcome-side purchase cost and actual `fee_cost`; match them to the settlement export. Payout is the winning-side quantity, including already-netted pairs. Do **not** treat a zero cash `revenue` field as zero economic payout, nor add fill fees and settlement fees twice. All 31 markets match exactly on counts, costs and fees; no fill-only ticker remains in this export. Sum: $853 gross payout − $758.595 gross purchase costs − $16.271 fees = **+$78.134**. This verifies arithmetic/internal consistency, not exchange authenticity or history completeness. [Per-market reconciliation](J0SHUSMC_RECEIPT_RECHECK.json).

| Local entry tag, joined by ticker/order ID | Markets | Net public-subset P&L |
|---|---:|---:|
| Older PULLBACK_99 |18|−$1.6469|
| NO_RECLAIM_80 |2|+$6.0143|
| BTC_FADE_90, now retired |8|+$32.0500|
| RECLAIM_70 |3|+$41.7166|
| All |31|+$78.1340|

These tags identify observed historical windows, not sole-strategy causality or a reproducible counterfactual. The worst market is **−$26.84** (`KXBTC15M-26SEP101915-15`, BTC_FADE). Keep that loss. Historical gross purchases reach $59.013 including fees in one window; this is not peak simultaneous risk and cannot be scaled directly to our account. There is no evidence that removing a losing tag or copying only the profitable tags would preserve the reported return. The publisher's separate chosen-$115-base account snapshot claims +$81.22, a $3.086 difference from this subset, and no deposits/withdrawals/rebates/full funding history establish a complete account return.

Critical rule/source differences: the old report advertises three lanes, but the current source explicitly retires BTC_FADE on September 22. Many historical BTC_FADE/NO_RECLAIM exits are account-synchronized around 70c rather than the advertised 90c/80c targets. The historical research aligns Kalshi minute-end observations to Coinbase minute-start candle closes, introducing approximately one minute of future information; the live feature builder restricts itself to closed candles. The favorable historical EVs therefore cannot be transferred to causal live features. Its tiny paper log closes successful current-market target hits without establishing full losing/official-settlement handling. See [reconstruction and source anchors](J0SHUSMC_AUDIT.md).

### Exact second hypothesis: persistent favorites

Elhamwork's current source combines Gaussian spot/strike/volatility/time fair value, a Coinbase-to-BRTI basis adjustment and settled-outcome calibration. Qualify the model's side at 70–90c ask, at least 7c model-minus-ask, spread at most 5c, at least ten minutes remaining, and a same-side qualifying observation at least 1.5 minutes earlier without an intervening reversal. It refreshes quote/spot before recording one call per market. Its README says two minutes, another version discrepancy to resolve before freezing a test.

The paper ledger buys its whole hypothetical stake at the displayed ask, without proving depth/arrival fills. Its 613 GOOD calls alone record 506 wins / 107 losses and +$1,093.45, but excluding REVENGE dollars does not reconstruct compounding without those bets. Mean entry 79.823% excludes fees; mean recorded price-plus-fee per contract is 80.932%, so the README's 79.8% break-even shortcut understates cost. A previous bug-corrected historical run changed +28.7% ROI to −29.30%. Current source/history/version and fill feasibility must be audited together. [Detailed empirical audit](EMPIRICAL_AUDIT.md).

## All eighteen selected projects

| Project | Rule/evidence checked | Material limitation |
|---|---|---|
| J0shusmc/Kalshi-BTC | Reclaim/fade source, ledger, candle studies | Positive receipt subset, incomplete account; historical lookahead and changed rules |
| elhamwork/btcbot | Persistent-favorite source and paper state | Mixed strategy/sizing history; ask fills without depth |
| zhangmatt/kalshi-btc-mm | BRTI moment model, maker strategy/replay, experiments | Forward paper loses; fallback pre-close tick is not official average settlement |
| aurascoper/brti-edge | Maker queue study and later validations | Original +0.35c/quote t≈0.83, inferred settlements; newer NO-GO data coverage |
| mlysophia/kxbtc15m-overbet-study | Persistent >80c favorite, sensitivity tables | +$2,998 baseline becomes **−$16.78** with published capacity filter and 2c slippage |
| artyomderkach-bit/btc-15m-vol-backtest | Buy both at 10c, cancel opposite, target 40c | $1k→$19.5k simulation uses candle-touch fills and arbitrary 10% volume participation |
| rodiiipooo/kalshi-crypto-regime-edge | BTC/ETH regime direction at minute five | Invented midpoint ±0.5c fills, unavailable cached inputs, unresolved candle timestamp alignment |
| hudsonjoshuaclark/kalshi-bot | Volatility/spot-shock/two-touch studies | Nominal gains fail multiple-testing/cluster gates; adverse results retained |
| sarthak-p/Kalshi-BTC-Dashboard | Drift fair value, 20s persistence, taker/hold | Default series differs; partials/cancels and future-neighbor backtest lookup unreliable |
| hamad-khawaja/kalshi-trading-bot | Multi-signal directional and maker source | Submitted resting sell can become booked profit; cumulative partial fills double-count |
| carterl96/KalshiBot | Directional/hedge/trail and modern event orders | Unknown acknowledgement can count as full fill; proxy settlement and ask-as-sell backtest |
| preceptress/btc-15-minute-prediction-model | Strong momentum, one contract, 2–12min left | Ten-market hit-rate claim; V2 cost/fee parser ignores documented average fields |
| seanrobenalt/kalshi-bot | Paired asks or final-minute favorite | Separate legs, missing fees/reconciliation; author reports $100 loss without receipts |
| DeweyMarco/simple-kalshi-bot | Momentum/consensus/evolution source | Paper overview also ships live paths; acknowledgements booked as fills |
| danielsilvaperez/kalshi-trading-bot | Scalper, swing source and helper | Only three-trade claimed pilot; source/README rules differ, fee estimates/false exit accounting |
| TylerShep/quant-kbtc | OBI/ROC/ATR paper and contract replay | +$10,648 screenshot is paper; exit-mark fallback; cited live examples are KXBTC, not KXBTC15M |
| OffGrid0xDAO/cross-platform-arbitrage | Cross-venue paper and data inventory | Wallet P&L is Polymarket evidence, not identified Kalshi account P&L; source-settlement disagreement |
| Strobingn/kalshi-odds-app | App, release recorder source and four data files | App says its model has not beaten market; sampled REST books cannot prove continuous queue fills |

The two independent six-project reports contain immutable line anchors: [execution audit](EXECUTION_AUDIT.md), [empirical audit](EMPIRICAL_AUDIT.md). Source defects are static traces, not claims that those defects happened on an independently observed private account. Legacy create-order code differs from the documented current event-order shape; we did not submit orders or prove every legacy route rejects today.

Root's other source checks: Daniel's scalper enters 12–60c asks with at least 3c spread, posts near midpoint, applies momentum checks, and seeks 3–5c price gains versus 6–8c stops. Any successful order acknowledgement can update exit P&L before confirming quantity; its assumed 0.5%-of-notional fee differs from current quadratic fees. Swing has a separate loop, partial-fill/status handling and a different 2.5%-notional fallback, so neither the helper nor scalper represents the whole README's ML claim. Tyler's contract replay can use midpoint entry/exit fallbacks even when executable mode lacks a quote; paper trader fills supplied prices without available-depth/arrival checks. Its old spot-only backtest is deprecated and was not used to discredit the current contract engine. The April 28 diagnosis retracts one alleged accounting bug yet contains contradictory descriptions of four old short losses; none is erased here. A paper dashboard is not a reconciled live ledger.

## A useful dataset, with measured limits

The Strobingn `scalper-data` release has **46 assets**, not the earlier unverified description of 48. We downloaded exactly four permitted pre-period files: October 3 book/spot/settlement, October 9 depth, totaling 4,545,172 bytes; all hashes match release digests. Release-tag collector source is pinned separately at `df83fa93dd3bfb074929b40a7b516e516e742b20`, not the current app head. No other release data or TEST was consumed.

The October 3 BTC book has 49,765 rows / 58 markets, 2:32:31 AM–4:59:59 PM PDT. Median sample interval is one second; the largest within-market gap is 34.845s, and 1,016 rows lack a YES ask. October 9 depth has 19,885 rows / 24 markets, 11:01:17 AM–4:59:59 PM PDT, a 573.962s same-market gap, and at most fifteen levels per side. The October 3 book/spot schema matches the normalized REST receipt-time collector. October 9 depth resembles sampled ladder snapshots, but its writer and timestamp semantics remain unverified. These are not certified lossless sequenced WebSocket books. The first market's recorded strike 84585.7 differs from the official 84585.68, consistent with the collector's six-significant-digit formatter; the exact per-file producer commit remains unknown.

It can support **coarse exploratory quote/depth sensitivity**, with gaps and precision disclosed. It cannot establish continuous quote survival between samples, subsecond lead/lag, order-ack latency, maker queue rank/cancel races or actual fills/fees. Public-trade capture completeness is unverified; the producer polls a bounded trade page without cursor pagination and discards IDs. No depth-writer provenance/per-file producer commit was established. No dataset license was found. The files can inform a licensing/provenance decision and private diagnostics, not replace our own recorder and its required sequence/coverage audit or certify a profitable replay. [Full feasibility, schemas, exact hashes and coverage](DATA_FEASIBILITY.md).

## Current Kalshi compatibility checked independently

At **5:52:10 PM PDT October 15**, keyless `GET /series/KXBTC15M` succeeded: fifteen-minute frequency, quadratic taker fee multiplier 1, CF Benchmarks source. At **5:54:12 PM PDT**, the sampled October 3 market confirmed final sixty BRTI seconds before close versus sixty seconds before open, official strike, final average rounded to two decimals, tie resolves YES and a tapered deci-cent price grid. Coinbase spot alone is not the settlement outcome. Original response identities are in [VENUE_EVIDENCE.json](VENUE_EVIDENCE.json).

The [current fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) uses general taker 0.07×quantity×p×(1−p); KXBTC15M is not a maker-fee exception in the inspected schedule, so default maker multiplier is zero. [Current rounding documentation](https://docs.kalshi.com/getting_started/fee_rounding) specifies direct-member $0.0001 balance precision, six-decimal trade fees and a per-order accumulator across partial maker/taker fills. Do not transplant whole-cent-per-fill or flat-notional assumptions. Historical receipt checks above use published actual fees, not today's schedule retroactively. Fee/endpoint compatibility is necessary but does not establish alpha.

## Concrete next work, kept on the queue

1. Finish the already-open real-versus-practice maker receipt reconciliation first: our last fixed target had seven real receipts versus zero reported practice fills. Queue/coverage differences are not yet a proven simulator bug. A model comparison cannot use that as a trustworthy counterfactual until explained. Preserve the recorded cumulative losses and all prior timing gaps.
2. Keep the positive public ledger and both current reclaim rule cards as **exploratory hypotheses**. Resolve candle close-time causality, historical target differences and missing loss/settlement accounting in an independent implementation. Do not transplant its order client, paper simulator, compounding or disabled fade rule.
3. After current execution evidence is reliable, freeze one reclaim variant and one persistent-favorite comparator, with market-only/simple momentum/no-trade controls, actual official settlements, actual series/account fees, arrival delay, depth, partial fills and conservative queue/cancel cases. Score dollars per window, locked versus directional P&L, worst losses, capacity, fees and uncertainty clustered by window/day, not hit rate alone. Do not pick a profitable slice after inspecting it or expand a parameter sweep until something wins.
4. Preserve the existing original/inverse/no-trade plan and Family A preregistration. This report is not an amendment, new freeze or permission to open their TEST. Any new prospective protocol needs its own declared source, split, budget, coverage and pass/fail criteria before observations; first run without real orders under existing authorization.

The source-search/audit milestone is complete; profitable independent validation, recorder volume/retention/cost checks, execution evidence and operating takeover are **not** complete. TJR remains last. No private account or Railway state was read this session, so previous financial evidence is dated, not represented as current. No live strategy/caps/stops/resume/configuration or deployments changed.

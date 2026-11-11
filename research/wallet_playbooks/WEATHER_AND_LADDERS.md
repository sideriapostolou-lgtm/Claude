# Weather and ladder wallet playbooks — 2026-10-13

Scope: public read-only research, no orders, no credentials, no application or trading-code edits. This is a behavioral reconstruction, not recovered private code or a forecast of our profits. Historical numbers come from committed lab9 analysis; bounded current observations are new. Raw data, request timestamps, URLs and hashes are in `evidence/weather_ladders/manifest.json`; derived calculations are alongside. Larger JSON responses are stored losslessly as `.json.gz`. Latest-500 samples cover very different durations and are not comparable full histories.

## Most important new result: rapid buy/sell recycling in the observed ledger

HighTempTation's latest 500 all-role fills (Oct 4–13) are 239 BUY / 261 SELL. All 239 buys match the separate taker-only response. Every buy is <=0.98, median 0.9725. Of 261 sales, 225 print exactly 0.99; 234 sales are taker-classified. In 226 same-asset cases there is exactly one recorded buy and one later sell, with shares equal within 0.01. Their public timestamp gaps are p10=4, median=5, p90=6 seconds. This is direct evidence against describing the wallet simply as a buy-and-hold weather-lock trader.

A second public `/activity?type=TRADE` retrieval matches 498/500 transaction/asset/side/time identities; two new trades displaced two oldest rows while requests were apart. For 225 of the simple pairs both activity rows remain available and share quantities agree. Their recorded sell usdcSize minus buy usdcSize sums to +$2,182.03, all 225 positive, versus +$2,313.94 from price*size alone. This is **a selected matched-subset cash-flow difference**, NOT whole-wallet profit, a prospective return, or independent chain audit. Excluded/unmatched positions, other costs and selection effects remain. The important finding is the buy/resell mechanism, not the selected sum.

LowTempTation appears to combine a similar buy/resell pattern with another signal: latest500 (Sep13–Oct13) 158 BUY/342 SELL, all buys taker-classified. NO buys:103, median97.2698c; YES buys:55, median46.4633c. Sales median99c,256/342 exactly99c.114 simple equal-size round trips have median public timestamp gap6s (p90 315s). All114 matched activity cash-flow differences positive, totaling+$1,350.00, also explicitly selected subset, not wallet P&L. Its cheapest YES fills can therefore be an observation/nowcast-to-repricing trade, not a tiny chance held to expiration.

**Timing limitation:** these are public API/on-chain timestamps, not synchronized exchange execution timestamps or measured bot reaction latency. A 5-second ledger gap does not establish a 5-second decision speed. The prospective collector should record causal weather publication, both book sides, exchange times, and data arrival to distinguish stale-price sniping from another liquidity route. Market metadata Gamma GET returned403 this session; current exact station/source was not independently refreshed. No access workaround attempted.

### 1. HighTempTation — observation-driven taker, then buy/resell recycling

Best guess, high confidence in execution pattern / medium in trigger:
- On a fresh station reading, identify buckets whose NO probability is now extremely high under the contract's actual source and rules.
- Sweep still-cheap NO offers, typically <=98c. This looks like a real entry ceiling: all239 current buys are at or below it, with81 exactly98c. A few YES near97c represent the equivalent nearly-decided side.
- Size to the cheap visible depth / available capital, not a fixed share clip: median54.67 shares, p90~442, wide variation. This depth rule is a hypothesis, not proved order sizing.
- As other buyers reprice the outcome, sell the same quantity into about99c bids, usually taking rather than waiting; potentially reuse the proceeds across other cities once available. Hold/handle exceptions only when exit liquidity fails.
- Expect entries to cluster immediately after newly available observations; expect a99c exit quote to appear within seconds, with little new directional news between entry and exit.
- Alternative: book/venue arbitrage or another faster information source rather than an observation signal. Disprove the weather-trigger explanation if causal source arrivals add no predictive power beyond book spreads or counterparty flow; check whether full cash-ledger reconciliation preserves the apparent gains.

Historical scout:862 assessed buys,81% of purchase dollars compatible with already-decided observations, median1.4 minutes from observation VALID time, not publication. Do not treat that valid-time statistic as actual data latency. Source: `research/lab9/scouts.json` weather section; profile https://polymarket.com/profile/0x6011655c4afb76f36dd1b08a137a1ba73466b31e .

### 2. Weatherstappen — passive near-certain inventory recycling

Best guess, high confidence in near-certain NO and recycling / medium in trigger:
- After the same kind of weather evidence, bid NO at99 or99.5c; wait for sellers. Of285 current buys,122 round to99c and119 to99.5c;222/285 buys infer maker, median maker buy99.5c.
- Sell acquired shares at99.8c passively, or take an available99.9c bid. Of215 current sales,172 round to99.8c and43 to99.9c;155 are makers. All82 conditions in this latest500 sample have both buys and sells.
- Taker buys also happen when discounts are attractive:63, median98.8902c. Median maker buy10 shares vs taker buy167.01, consistent with fragmented standing orders plus larger opportunities, NOT proved parent-order sizes.
- Hypothesis: its edge is queue priority + many capital turns with very small markups, with a faster information filter protecting bids from unresolved outcomes.
- Alternative: it quotes constantly and profits from ordinary spread capture rather than waiting for an observation. Test pre-observation open-order estimates and fills vs post-observation fills; the signal hypothesis predicts a marked change after source confirmation.
- The exact-size subset24 has median19.5s buy-to-sell public timestamp gap, but is not representative of all multi-fill positions; first observed buy to first later sale across82 assets is4.79 minutes.

Old weather scout:98.3% purchase dollars compatible with decided outcomes; median1.3 minutes from observation valid time; these are proxy classifications. Source `scouts.json`; https://polymarket.com/profile/0xb9012e0d9b60d3920286309328b935cdfa609fc4 .

### 3. LowTempTation — two engines: locked-side NO plus peak-bucket YES

Best guess, high confidence in two price modes / medium-low in exact forecast logic:
- Reuse HighTempTation's NO<=98c taker/recycle engine.
- Additionally, when a fresh afternoon observation puts the running day's maximum in a bucket and a local forecast suggests little further warming, buy that bucket's YES before the market reprices. Current YES median46.46c, range includes15.2c; these are predictions, not completed locks.
- Resell near99c after repricing. Current158 buys all taker;232/342 sells infer maker, so it is more willing to post exits than HighTempTation.
- Expected features: local solar/time-of-day, temperature relative to running max, recent trend, remaining cloud/wind/forecast changes, exact source/station precision. A naked 'it reached the bucket' rule is inadequate because temperatures can continue rising.
- Competing explanation: already-final outcomes or a faster official source not captured by METAR, rather than clever nowcasting. To distinguish, reconstruct exact source publication and event end for the mid-price YES trades. If readings before entry already made the bucket final under those rules, the mechanism is resolution-latency arbitrage instead.
- Do not infer shared ownership from similar names/exit code-like behavior.

Historical source `scouts.json` and `weather/nowcast_probe.py`:172 not-yet-decided proxy buys at median50.5c,97.7% eventual wins, with timing/source limitations and no untouched evaluation. https://polymarket.com/profile/0x8e40e10d9b34b28c77c4962be5026c6fdd1f3797 .

## Crypto/commodity ladder wallets

### 4. LucasMeow — sells remote-event insurance, mostly holds

High confidence in broad behavior; low confidence in a hard numerical entry rule. Full audit dominates the earlier scout. Core BTC/ETH monthly NO cohort:3,912 buys,131 strikes,29 asset-month ladders; median price99.4c, signed-z proxy3.2318,8.7079 days remaining.95.27% maker by fill count but only50.47% of purchase dollars: small passive fills and occasional large takes. There are551 sells in the same monthly family, so 'never sells' is false. Median4 purchased strikes per ladder is not a simultaneous position cap.

Concrete best-guess rule:
- For an untouched monthly upper/lower barrier, estimate remaining touch probability using spot, time, volatility and tail/jump allowance.
- Buy NO when `1 - modeled_touch_probability - purchase_price - fees > required_margin`; supply a standing bid, but take a large discount when available.
- Allocate by correlated ladder risk, not independently by strike. Most entries are high-priced NO; hold most until settlement but trim when barrier risk or opportunity cost rises.
- Add fills while premium remains attractive; repeated fills can be one large resting order, so do not treat them as deliberate martingale additions.
- A near-expiry or very distant barrier permits paying99.4–99.8c if modeled risk is below the tiny remaining premium. The descriptive z distribution does not establish a fixedz=3 trigger.

Prediction: stable volatility/time-adjusted threshold should explain fill/no-fill timing better than raw strike distance; sizing should decrease as several nearby/nested strikes create concentrated crash risk. Alternatives: options hedges elsewhere, discretionary information, plain market making, and external capital create smoother results. Disprove a stand-alone tail model if it cannot explain incremental choices versus all available nonbought strikes or cannot reconcile losses across correlated ladders.

Fresh latest500(Jun23–Oct12):493 buys/7sells;444NO buys median98c.444 maker buys median144.44shares vs49 taker buys median3,662.36shares, near-equal dollars. Strongly corroborates 'many small passive pieces, occasional big takes'. Fresh sample also includes sports/YES: it is not a pure strategy wallet.

Funding correction: net external funding$397,582.68; March2025 alone added$299,353.05. It did not simply compound$100 into the displayed balance. `research/lab9/LUCAS_RULES.md` and LUCAS_monthly.csv contain full reconciliation, including source P&L differences. https://polymarket.com/profile/0x7f3c8979d0afa00007bae4747d5347122af05613 .

### 5. x6916 — an actual two-sided ladder market maker

High confidence in market-making activity, low-medium in fair-value/risk model. Fresh500(Oct11–13):254buys/246sells;all500 infer maker;109conditions,61 with bothbuys andsells. Buys148YES at median20c and106NO median91.45c. These are different contracts/prices, not automatic paired arbitrage. Weekly/monthly/year-end BTC/ETH touched-price contracts dominate.

Concrete best-guess rule:
- Build a monotone, no-arbitrage probability curve over related barriers/horizons from spot and volatility, probably using other market prices too.
- Quote both directions around that curve; buy YES/NO when others hit discounted bids, sell inventory when bids become rich relative to model.
- Skew quotes away from accumulated exposure; update prices when BTC/ETH or adjacent strikes move. Resell and recycle instead of mechanically waiting for resolution.
- Expected signature: both-side trading across the ladder, near-balanced buy/sell dollar turnover, price updates correlated with spot delta, and shorter holds than Lucas.
- Competing explanation: uninformed spread capture with no independent price model, or cross-market arb rather than predictive alpha. Test whether inventory/neighbor prices explain decisions after controlling spot-model residual; check whether profits survive eliminating rewards and marking all remaining positions.

Prior scout's '+$492k' and z2.1 are not a full audit; its z computation inherited a lookahead bug fixed only in Lucas's full reconstruction. Do not promote these to validated strategy parameters. https://polymarket.com/profile/0x6916cc00aa1c3e75ecf4081df7cae7d2f3592fd4 ; `research/lab9/scouts.json`, `leaderboard/ladder_rule.py`.

### 6. amis — diversified remote-barrier insurance with profit-taking

Medium confidence (bounded sample/old scout, no full audit). Fresh500(Apr21–Oct9):328buys/172sells;326NO buys median94c,171NO sales median98.7c.223/328 buys maker,134/172 sales maker; taker amounts much larger. Instruments include oil/silver distant upper barriers and crypto downside barriers.

Concrete best-guess rule:
- Look for unusually expensive tail insurance after attention/volatility events; buy NO around90–99c on distant month-end commodity/crypto barriers.
- Use patient bids for ordinary size; take when a large block is offered below internal fair value.
- Sell near98.5–99.8c once most premium decays when that cash earns more elsewhere, rather than hold universally. One simple complete pair bought NO at95c and sold98.936c about24.34days later; one pair is illustrative, not a typical duration estimate.
- Spread capital across distinct assets/events but explicitly budget common macro/crash risk. Current sample has fourteen conditions with both buys and sells.
- Alternative: discretionary commodity views or external futures hedges, not generic tail selling. Falsify the generic model if asset/event-specific discretionary variables dominate, or cash P&L depends on hedges not visible here.

Prior z2.6/about30days is a scout proxy with the same temporal issues as the original ladder script, not a recovered threshold. Kalshi terminal commodity closes are not one-touch twins. https://polymarket.com/profile/0xc1a58674dbcc1d3208f7e61a0a8b252162caf290 ; `research/lab9/scouts.json`.

## Transfer caveats that matter to mechanism, not generic disclaimers

- Weather: `research/lab9/WEATHER_WINDOW.md` corrected the original scout. All252 sampled Kalshi markets settle primarily on TWC, not automatically NWS CLI/METAR. Station/source precision, revisions and day boundary must match. The earlier universal 'METAR lock safely transfers' claim is not established. Only65 of1,062 target97–98c historical shares had a taker direction consistent with hitting a resting NO bid; queues and public receipt timing unknown.92/92 proxy outcomes agreeing is not proof of a certain lock.
- Slow ladders: original `leaderboard/ladder_rule.py` used hour-close prices available up to an hour in the future, absolute distance and metadata expiration. Lucas full audit fixed these; do not carry the other wallets' old z bars over as recovered private logic.
- Capital mechanics differ: Lucas mostly earns small yield on substantial cash over days; weather winners turn capital rapidly; x6916 repeatedly recycles inventory; none alone proves the owner's desired small-bankroll trajectory.
- All-six stats describe visible fills. Order cancellations, missed/unfilled opportunities, offsite hedges and true reaction time remain latent. To learn a rule, model all eligible decision times including nontrades, then test future data, not just fit executed winners.

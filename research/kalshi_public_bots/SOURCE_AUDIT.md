# Source-level reconstruction

Inspected 2026-10-13; public source text only, no third-party code execution or credentials. Revision links
freeze the behavior reviewed. This is a bounded audit of relevant paths, not a certification of every file.
No candidate below established an independently reconciled profitable live account record.

## Inventory-skewed maker: ksubramanian709/Kalshi-Market-Making

Commit `cbc8cd62ffcf8f098fe20c009ada4b72475be841`.

- [Quotes](https://github.com/ksubramanian709/Kalshi-Market-Making/blob/cbc8cd62ffcf8f098fe20c009ada4b72475be841/strategy.py#L24):
  `center = midpoint - net_yes / max_position * max_skew`; bid/ask are center ± half-spread, clipped to
  integer cents 1–99. Size is clipped to position room. Optional fair value is clamped near midpoint.
- [Live call](https://github.com/ksubramanian709/Kalshi-Market-Making/blob/cbc8cd62ffcf8f098fe20c009ada4b72475be841/live_trader.py#L204)
  supplies no fair value: actual strategy is midpoint/inventory quoting. Defaults are 2¢ half-spread,
  one contract, skew equal to half-spread.
- [Queue model](https://github.com/ksubramanian709/Kalshi-Market-Making/blob/cbc8cd62ffcf8f098fe20c009ada4b72475be841/queue_model.py#L35)
  puts current depth ahead, consumes it with crossing prints, then fills excess. Partial fills are tracked,
  but aggressor side is absent and priority behavior simplified.
- [Paper accounting](https://github.com/ksubramanian709/Kalshi-Market-Making/blob/cbc8cd62ffcf8f098fe20c009ada4b72475be841/portfolio.py#L17)
  omits fees. [Order creation](https://github.com/ksubramanian709/Kalshi-Market-Making/blob/cbc8cd62ffcf8f098fe20c009ada4b72475be841/kalshi_orders.py#L69)
  uses GTC without explicit post-only. [OMS](https://github.com/ksubramanian709/Kalshi-Market-Making/blob/cbc8cd62ffcf8f098fe20c009ada4b72475be841/oms.py#L40)
  uses 3-second/1¢ repricing and submitted rather than reconciled remaining count.

Extract quote/inventory and queue concepts; independently rebuild execution and fee accounting.

## Avellaneda–Stoikov maker: zachdaube/kalshi-market-maker

Commit `212c957c2b63a1a775949f9e7562911fdc033f28`.

- [Quote rule](https://github.com/zachdaube/kalshi-market-maker/blob/212c957c2b63a1a775949f9e7562911fdc033f28/src/quotes.py#L81):
  reservation price `mid - q*gamma*sigma²`; spread `2/gamma*log(1+gamma/k)`. Defaults gamma=.1, sigma=2,
  k=1.5; cent quotes and a fee spread floor. YES asks become complementary NO buys. Above 80% inventory,
  halve the increasing-side size, minimum one contract.
- [Execution](https://github.com/zachdaube/kalshi-market-maker/blob/212c957c2b63a1a775949f9e7562911fdc033f28/src/execution.py#L99)
  reads positions/books/trades, adjusts for order flow and requotes after a 1¢ change. Net positions are
  not a complete dollar-risk model including resting orders.
- [Cancellation failure](https://github.com/zachdaube/kalshi-market-maker/blob/212c957c2b63a1a775949f9e7562911fdc033f28/src/execution.py#L280)
  retries once, then clears local tracking while replacement can continue. This can orphan exposure.
- [Fees](https://github.com/zachdaube/kalshi-market-maker/blob/212c957c2b63a1a775949f9e7562911fdc033f28/src/fees.py#L26)
  use an unrounded quadratic, without complete series-specific applicability or current direct-member
  rounding/accumulator behavior. Do not substitute the older blanket cent assumption either.

Useful mathematical baseline; unsafe to adopt its order lifecycle unchanged.

## BTC fair-value bot: yougotsam/KalshiBot

Commit `a01af900f96a6038db081de18ebbb1e98cb3cbb2`.

- [Signal](https://github.com/yougotsam/KalshiBot/blob/a01af900f96a6038db081de18ebbb1e98cb3cbb2/bot/strategy.js#L141):
  Binance spot return from observed opening, recent volatility and normal-CDF fair value. Defaults: first
  four minutes, no final 30 seconds, asks 35–65¢, fee-adjusted edge above 10¢. A separate Polymarket-price
  signal buys Kalshi YES; it is unhedged. Two-sided arbitrage is explicitly disabled for non-atomic legs.
- [Probability defect](https://github.com/yougotsam/KalshiBot/blob/a01af900f96a6038db081de18ebbb1e98cb3cbb2/bot/strategy.js#L62):
  independently evaluating its written polynomial gives `normalCDF(0)=0.8005288599987548`, not 0.5.
  There is also a jump across zero. This can manufacture apparent directional edge.
- [Order manager](https://github.com/yougotsam/KalshiBot/blob/a01af900f96a6038db081de18ebbb1e98cb3cbb2/bot/order-manager.js#L77)
  values fill increments at limit rather than actual cost; zero-fill-only timeout leaves partial remainders
  outside that cancellation condition.
- [Fee helper](https://github.com/yougotsam/KalshiBot/blob/a01af900f96a6038db081de18ebbb1e98cb3cbb2/lib/kalshi-economics.js#L2)
  uses upward whole-cent rounding. It needs current member-type/schedule validation.
- The author's [backtest validity notice](https://github.com/yougotsam/KalshiBot/blob/a01af900f96a6038db081de18ebbb1e98cb3cbb2/backtest/FINDINGS.md#L1)
  disclaims future within-window leakage and early recognition of settlement cash in synthetic GBM tests.

Do not use its probability output or quoted historical returns as evidence.

## “Safe compounder”: ryanfrigo/kalshi-ai-trading-bot

Commit `7b9667bb7e7e7b263f14b54ab8647a05cbdd1383`.

The [strategy](https://github.com/ryanfrigo/kalshi-ai-trading-bot/blob/7b9667bb7e7e7b263f14b54ab8647a05cbdd1383/src/strategies/safe_compounder.py#L62)
buys NO, excludes selected sports/entertainment/mention categories, requires NO ask ≥80¢ and defaults to
3¢ edge, despite README's 5¢. It bids a cent below inferred ask; half-Kelly, at most 10% of portfolio and
200 contracts. Estimated NO probability is `1-last_yes_price` plus a hand-set 1–4¢ bonus. This supplies no
independent evidence that fair probability exceeds the market.

In the same file, the ask fallback at [line 527](https://github.com/ryanfrigo/kalshi-ai-trading-bot/blob/7b9667bb7e7e7b263f14b54ab8647a05cbdd1383/src/strategies/safe_compounder.py#L527)
invents an ask at NO bid +2¢ when the opposite bid is absent; edge/profit omit fees. At
[line 685](https://github.com/ryanfrigo/kalshi-ai-trading-bot/blob/7b9667bb7e7e7b263f14b54ab8647a05cbdd1383/src/strategies/safe_compounder.py#L685),
sizing ignores its cash argument, floors to one contract and does not reserve across candidates in that
function. The call lacks explicit post-only. These are call-site findings, not a complete client audit.

## Observation crossing: evanfoglia/weather-arb-bot

Commit `e90898163c371b3d7c3adfdf0b79c2db51963097`.

- [Predicate](https://github.com/evanfoglia/weather-arb-bot/blob/e90898163c371b3d7c3adfdf0b79c2db51963097/src/arbitrage_engine.py):
  for above thresholds, observed maximum ≥ threshold+1°F implies YES; for below/range, maximum > upper
  bound+1°F implies NO. Orchestration filters to its “CERTAIN” branch, a label not a demonstrated guarantee.
- [Defaults](https://github.com/evanfoglia/weather-arb-bot/blob/e90898163c371b3d7c3adfdf0b79c2db51963097/src/config.py):
  fair=.99 and minimum edge=.03 imply ask ≤.96; $50/50-contract caps, 300-second polling. README examples
  differ. These are the author's values, not our recommended amounts.
- [Weather inputs](https://github.com/evanfoglia/weather-arb-bot/blob/e90898163c371b3d7c3adfdf0b79c2db51963097/src/weather_client.py):
  maximum among IEM/NWS/METAR, static station map, local-midnight window. No demonstrated per-contract
  source/day verification. Multiple feeds may share one underlying observation; taking their maximum
  is not independent confirmation of a suspect value.
- [Paper accounting](https://github.com/evanfoglia/weather-arb-bot/blob/e90898163c371b3d7c3adfdf0b79c2db51963097/src/bot.py#L244)
  credits expected profit on placement. [Simulation](https://github.com/evanfoglia/weather-arb-bot/blob/e90898163c371b3d7c3adfdf0b79c2db51963097/src/simulation.py)
  assumes 90% execution/99% wins. Neither is historical execution/settlement evidence.

Extract the crossing hypothesis only. Require actual contract source, first-visible timestamps, confirmation,
executable depth after delay, proper fees and final venue settlement. Our existing stopwatch covers this
measurement question; no second live implementation is justified by this repository.

## Calibrated weather forecasting: mifisher/kalshi-weather-bot

Commit `45e69671040fb342e934bc3368835607e53ade1c`.

The [README](https://github.com/mifisher/kalshi-weather-bot/blob/45e69671040fb342e934bc3368835607e53ade1c/README.md)
reports roughly 950 simulated trades over 14 months/four stations: all three models lost about 3–4¢ per
trade after fees despite predicted 15–18¢ edges. We did not independently rerun this historical test.

[Evaluation](https://github.com/mifisher/kalshi-weather-bot/blob/45e69671040fb342e934bc3368835607e53ade1c/src/kalshi_bot/evaluation.py)
requires ≥100 settled observations per station/lead, five-bin calibration error ≤.05 and Brier improvement
over climatology. Forecast age ≤6h, no entries within 12h of close. Bid when model minus price minus fee
minus two ticks is positive; at most one passive demo contract per run.
[Fees](https://github.com/mifisher/kalshi-weather-bot/blob/45e69671040fb342e934bc3368835607e53ade1c/src/kalshi_bot/fees.py)
reserve quadratic taker fees with old upward cent rounding. Useful negative control: being better than
climatology is not being better than executable market prices.

## Small paper weather claim: AwpDemon/kalshi-weather-bot

Commit `d699fe5dacf17b50f2fcb737e2653447259f608f`.

The [README](https://github.com/AwpDemon/kalshi-weather-bot/blob/d699fe5dacf17b50f2fcb737e2653447259f608f/README.md)
reports 20 settled paper trades, 9 wins/11 losses, +$3.89. No raw ledger was found in the inspected tree.
[Model](https://github.com/AwpDemon/kalshi-weather-bot/blob/d699fe5dacf17b50f2fcb737e2653447259f608f/src/forecast/bracket_model.py):
31-member GFS bucket frequency, probability clipped .05–.95, city/season residual correction.
[Config](https://github.com/AwpDemon/kalshi-weather-bot/blob/d699fe5dacf17b50f2fcb737e2653447259f608f/src/config.py):
NYC/Chicago every two hours, ≥1 day left, .10–.90 prices, ≥10¢ raw edge and ≥.55 agreement; quarter-Kelly.
[Edge](https://github.com/AwpDemon/kalshi-weather-bot/blob/d699fe5dacf17b50f2fcb737e2653447259f608f/src/engine/edge.py)
has no explicit fee deduction. [Paper executor](https://github.com/AwpDemon/kalshi-weather-bot/blob/d699fe5dacf17b50f2fcb737e2653447259f608f/src/engine/executor.py)
places immediately at observed ask without demonstrated delay/depth/queue treatment. Profit is not proof
of real executable opportunity.

## Recommendation scoring: rockmundada/kalshi-weather-bot

Commit `e164062e668b0f4ba4aed5673d1de6d20694f1cf`.

The headline calls them executed trades, but [report enrichment](https://github.com/rockmundada/kalshi-weather-bot/blob/e164062e668b0f4ba4aed5673d1de6d20694f1cf/dashboard/enrich_predictions.py)
scores textual BUY recommendations as one contract against IEM-derived weather outcomes, without actual
fills, fees or Kalshi settlement receipts. Independently counting the
[CSV](https://github.com/rockmundada/kalshi-weather-bot/blob/e164062e668b0f4ba4aed5673d1de6d20694f1cf/dashboard/enriched_predictions.csv)
gave 2,643 rows, 361 actionable/360 scored signals, 183 wins, **−$3.20 gross**, only 86 unique tickers.
Repeated evaluations are not independent markets. YES: 32/124, −$2.98; NO: 151/236, −$0.22.
These are hypothetical signal scores, not executed account returns.

## Cross-cutting findings

Useful parts are mathematical baselines, transparent negative results and logging/reconciliation ideas.
Common weaknesses are missing fee treatment, optimistic fills, incorrect source/clock assumptions and
unreconciled orders. None of these is remedied by copying a high win-rate threshold. Source publication
does not establish a license to redistribute code; check each license before reuse. This session copies
no implementation into the application and changes no money authority.

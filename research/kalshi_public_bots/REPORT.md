# Public Kalshi bots: what we could actually reverse engineer

Public-source audit, 2026-10-13 UTC. Exploratory research under [PLAN.md](PLAN.md), not a backtest,
funding recommendation or change to the running desks. Sources were read as text; no third-party bot ran.

We found observable Kalshi trading activity and reproducible strategy code. **We did not establish a
profitable bot whose complete rules, execution and small-account returns we can independently reproduce.**
The strongest account lead trades differently from the Polymarket skip bot. Several attractive code
examples manufacture apparent edge through bad probability math, assumed fills or premature profit.

## 1. Actual public account activity: szg.szg

Kalshi's documented [public tape](https://docs.kalshi.com/api-reference/market/get-trades) is anonymous.
However, some traders make activity visible through Kalshi Social. Of the top six all-time accounts in
each of Crypto and Climate/Weather, ten hid their histories; two exposed them. We respected those settings.
Leaderboard `projected_pnl` is not audited realized profit, and a busy account is not necessarily a bot.

[szg.szg's public profile](https://kalshi.com/ideas/profiles/szg.szg) was active today. We collected three
pages: **300 unique fills across eight KXBTC15M windows**, 05:40–13:13 UTC. This is a bounded sample, not
a full day or lifetime history. [Saved rows](szg_fills.csv), [window aggregates](szg_windows.json),
[reconstruction details](DATA.md).

| Observation | Result | What it does and does not show |
|---|---:|---|
| Maker fills | 229/300 = 76.3% | By fill count; about 59.3% by contracts. Not the fraction of orders. |
| Median / largest fill | 80.185 / 44,444 contracts | A fill can be part of a larger order. Not a bankroll estimate. |
| Exact matches to documented exchange tape | 220/300 | Timestamp, quantity, ticker and YES price agreed. |
| Economic price of those 220 matched fills | 99.5–99.9¢ | The 80 unmatched fills are excluded; this is a selected subset. |
| Direction in matched records | One outcome per window | Six NO windows, two YES. Opening versus closing is unknown. |
| Time before close, all 300 fills | 30.8–348 seconds | 71 fills occurred in the final minute. |
| Final market result versus matched direction | 8/8 agreed | Descriptive outcomes, not verified account P&L or a trading edge. |

**Provisional behavior:** substantial maker activity near expiry, with many matched transactions taking
the heavily favored outcome. This does not establish the signal, cancellation policy, earlier inventory,
true buy/sell lifecycle or fee-adjusted return. Recent-tape pagination favors recent matches: the
unmatched Social YES-scale prices span 0.006–0.058, so the matched price range cannot describe all 300.
There is no basis here to claim an exact rule or a 100% winning bot.

This is different from buying both sides early at 30–70¢. At 99.9¢ a winning contract earns only 0.1¢ gross;
one loss erases 999 such wins before fees. At 99.5¢ it erases 199 wins. A few dollars cannot reproduce the
observed scale, and eight winning windows cannot establish the extremely high success rate required.

Important parser finding: Social `price_dollars` can be a YES-scale price even when this participant takes
NO exposure. A displayed 0.002 can correspond to NO at 0.998. We used exact trade-ID joins and v2 canonical
direction, not the ambiguous legacy `taker_action`/`taker_side` combination. Integer fields also truncate
subcent prices and fractional quantities. A second reviewer independently rebuilt the 220 matches.

## 2. A commercial bot with visible activity: Kalshi Sniper

The operator's [live page](https://www.kalshi-sniper.com/live) advertised +$6,776.37 over 5,125 closed
trades, with a $2,000 deposit, at lookup. Its [method description](https://www.kalshi-sniper.com/how-it-works)
describes crypto 15-minute signals, three-to-five-filter agreement, entry price bands, per-signal stakes
and holding to settlement. It withholds the exact filters; a paid executable is not inspectable source.

Public Social activity under `csniper` contained 100 visible fills across 27 BTC/ETH/XRP windows, all taker,
median 15 contracts. However, profile lookup returned nickname `qfrzxrx`; the alias relationship was not
established. Public metrics omitted P&L and deposits. **We corroborated visible trading activity, not the
advertised return, account ownership or bankroll.** It is a second observation candidate, not a verified
winner. No package was installed, subscription purchased or account key supplied.

## 3. Rules we can reconstruct from public source

The [source audit](SOURCE_AUDIT.md) pins eight repositories to exact commits and details their mechanics.

| Candidate | Reconstructed rule | Critical finding |
|---|---|---|
| ksubramanian709 / Kalshi-Market-Making | Quote either side of midpoint; shift quotes to reduce inventory; model queue ahead. | Useful baseline. Paper accounting omits fees; live orders are not explicitly post-only. |
| zachdaube / kalshi-market-maker | Inventory-adjusted reservation price and spread; cancel/requote after price movement. | Failed cancellations can clear local tracking before replacement. Do not copy its order path. |
| yougotsam / KalshiBot | BTC move and volatility imply fair probability; buy when fee-adjusted edge exceeds threshold. | Its normal CDF returns about 0.8005 at zero instead of 0.5. Its own backtest notice disclaims future-data leakage. |
| evanfoglia / weather-arb-bot | Observe a temperature crossing, then buy the supposedly decided side below a price cap. | Paper mode credits expected winnings on placement. This is not settlement profit. |
| mifisher / kalshi-weather-bot | Calibrated weather probabilities, conservative bid placement and eligibility gates. | Author reports roughly 950 simulated trades losing 3–4¢ each after fees. Useful negative evidence. |

No reviewed repository supplied a reconciled, independently verifiable profitable live record. Public code
reveals how a bot works; it does not establish that the rules make money at executable prices.

## 4. Longer performance records are less flattering than headlines

**3rd Eyes weather bot:** its [published ledger](https://3rdeyes.io/track) contains 317 rows totaling
**+$201.16**, April 23–September 4. The last 50 total **−$62.25** despite 39 positive rows. The operator
closed the service and described fading opportunity/thin books. We recomputed publisher-data arithmetic;
the rows lack quantities, separate fees and venue fill IDs, so this is not account reconciliation.
[Saved arithmetic](ledger_audit.json). A high win rate does not protect against occasional larger losses.

**Prophet Arena:** the [paper](https://arxiv.org/html/2607.06166v3) describes public-information forecasting
every two hours, trading forecast/price disagreement and resizing positions. Its
[author-hosted ledger](https://prophets-profit.onrender.com/) supports inspection but does not reconcile
fully with the paper: 226 rows versus 236 reported; row fees $22.348 versus $26.31. Two positions labeled
open contribute $119.075 of its $160.67 reported profit. The $200 base is defined in ledger metadata as
rounded peak capital deployed, not verified initial cash. This is a research lead, not independently
verified repeatable “80% monthly.” Full execution code and operating costs were not established.

## 5. Current venue facts that change the experiment

- [Current fee rounding](https://docs.kalshi.com/getting_started/fee_rounding): direct-member balances align
  to $0.0001; model fees round up to $0.000001, with an order-level accumulator handling rounding rebates.
  The owner opened directly on Kalshi. Do not impose a blanket one-cent charge per fill. Use the applicable
  [fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf), series parameters and actual fee receipts.
- The current KXHIGHNY series and [October 13 contract](https://api.elections.kalshi.com/trade-api/v2/markets/KXHIGHNY-26OCT13-T78)
  name **The Weather Company**, consistent with our existing Lab 9 audit.
  A METAR crossing alone cannot guarantee settlement under a different source, station or day definition.
  Read each contract. The prior blanket NWS/CLI assumption is unsafe.
- The current public tape does not expose queue priority, canceled orders, private positions or deposits.
  Exact fills can support behavior inference; they cannot reveal a complete strategy by themselves.

## Research decision

**Best account to study next: szg.szg, with csniper as a contrasting taker-heavy lead.** Record fresh public
fills alongside full books, the actual settlement reference and spot feeds. Freeze a forward protocol
before scoring it: deduplicate partial fills, model observation delay, infer candidate triggers on TRAIN,
validate once, then score a held-out day. Include false signals, skipped windows, fees and adverse price
movement; matching only the trader's fills is insufficient. Today's observed records are exploratory and
cannot later serve as untouched TEST.

**Best code to learn from: inventory-skewed maker quoting.** Rebuild only its quote and queue concepts in
an isolated simulator; compare executable post-fill prices and settlement returns after all costs.
Quotes may get filled precisely when the market is about to move against us. A spread is not guaranteed
profit. The existing weather stopwatch remains a separate source/latency hypothesis, not a proven lock.

No new collector has been deployed or multi-day trial completed in this session. No source, app,
credentials, trading settings, caps or orders changed. No reviewed candidate currently earns a live-copy
recommendation. The next useful result is a measured trigger and executable return, not another screenshot.

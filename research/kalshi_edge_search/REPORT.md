# Kalshi edge search — 2026-10-13

**Verdict: no currently executable profitable strategy has been established.** The best-supported lead in this search is passive buying of favored outcomes on slower Kalshi markets. A separate Bitcoin 15-minute market-making experiment is the closest match to the owner's desired pace, but has weaker profit evidence. Neither is ready for new real-money deployment.

This session audited existing research, checked primary venue documents and public implementations, and collected fresh public books. It did not run a new historical strategy backtest, observe three days of trading, or reconcile the live account. Trading code, keys, modes and caps were untouched.

## What I would investigate first

**Patiently bid for the favored side, while limiting how much can be lost on one event.** Become the maker: other traders must accept our price. The hypothesis is that impatient buyers of unlikely outcomes sometimes overpay, leaving their counterparties a margin. The favored side can be YES or NO. This is not a rule to buy every expensive NO, and a high win rate is not proof of a positive return.

The strongest external evidence located is [Bürgi, Deng and Whelan's Kalshi study](https://www2.gwu.edu/~forcpgm/2026-001.pdf). In its 2021–April 2025 sample, makers buying at 50c or more averaged about **+2.6% after the study's commissions**, with 33% return standard deviation; makers paid no maker fee in that sample. The sample covered markets open at least 24 hours, not 15-minute crypto. It studied observed fills, not our attainable queue position or portfolio. Its final-volume/spread selection cannot be copied prospectively using future information. Today's fees and cash lockup also require new measurement. This is a research lead, not a current expected return.

**For speed, test a separate BTC15M maker with strict inventory control.** Use the actual settlement definition, cancel stale quotes, price the risk of being filled just before an adverse move, and charge for completing or exiting an unbalanced position. A close [public implementation's retrospective](https://github.com/zhangmatt/kalshi-btc-mm/blob/main/docs/PROJECT_RETROSPECTIVE.md) reports roughly **−$2.50 per window in later forward paper trading** despite sophisticated data and replay work. The author attributes much of the failure to directional inventory held to settlement. This is author-reported evidence, not an independently reproduced account result.

The closest fast bot is therefore a warning, not a profitable codebase to copy. A plausible slower edge should not be relabeled a high-frequency one to match the owner's preference.

## Evidence comparison

| Candidate | What the evidence supports | Decision |
| --- | --- | --- |
| Favored-outcome passive bids | Positive historical population association; our fills, present fees and small-bank economics unproved | First research priority |
| BTC15M passive maker with inventory/toxicity controls | Mechanism fits frequent trading; close public forward test lost money | Separate, falsifiable speed experiment |
| Buy YES and NO immediately | Complementary asks in an uncrossed book already sum to at least $1 before fees | Reject as a standalone edge |
| Complete a cheap pair over time | Can lock a profit after both fills; the first fill can instead strand a losing position | Include all failed pairs, not only completed winners |
| Chase a fresh Bitcoin move as taker | Repo's first fully causal one-second buckets were negative; subsecond executable edge unproved | Do not promote old results |
| 97–99c weather “locks” | Settlement-source mismatch and hypothetical fills invalidate a guaranteed-lock claim | Measurement only |
| Far-strike monthly crypto NO | Existing audit has losses and missing path/queue evidence; slower capital turnover | No validated strategy |
| Liquidity rewards | Some real programs, with eligibility and competing size; none for the checked BTC15M series in this snapshot | Account separately; never invent rebates |
| Cross-market structural mispricing | Can be tested only after rules, all settlement scenarios, executable depth and leg risk are verified | Feasibility scan, not a demonstrated profit source |
| Extreme-odds “moonshots” | Large payout multiples do not establish mispricing | No evidence to fund a bot |

## Fresh executable-book diagnostic

The protocol was recorded at **17:47:59 UTC** before collection. Between **17:48:03 and 17:48:14 UTC**, we requested three books each for the current BTC, ETH, SOL and XRP 15-minute windows. Sixteen public requests, including market discovery, returned without errors. Raw responses, timestamps and rules are in [book_sample/](book_sample/); [summary.json](book_sample/summary.json) contains the calculations.

- All **12 snapshots** had complementary best asks totaling **$1.01 before fees**.
- Assuming standard multiplier-one taker fees, one full fill per leg, a direct account and no fee-rebate carry-in, the nominal one-contract pair cost was **$1.0408–$1.0443**. A pair pays $1.
- **11 of 12** snapshots had at least one contract on both best asks. One ETH snapshot had only 0.40 on one side: its one-contract top-price calculation is not executable at that size. Even the depth-supported 0.40 pair cost $0.4165 for a $0.40 payout under the stated assumptions.
- The best bid pairs totaled $0.99. That is a nominal one-cent margin only if both resting bids eventually fill and fees permit it. These snapshots do not show that they would fill, when they would fill, or the losses on incomplete pairs.

This is a seconds-long diagnostic, not a profitability backtest or evidence that all other times lack an opportunity. Request duration here is not Railway latency, exchange event age or order-acknowledgment latency.

The [order-book convention](https://docs.kalshi.com/getting_started/orderbook_responses) explains the result: YES ask = 1 − NO bid; NO ask = 1 − YES bid. Adding the bids and calling them immediately purchasable prices creates fake arbitrage.

## Fees, settlement and the size problem

Read the [current fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf), [direct-account rounding rules](https://docs.kalshi.com/getting_started/fee_rounding), and each series/event override. Standard taker fees depend on `0.07 × multiplier × count × p × (1-p)`. Some series also charge makers. Direct-account rounding includes a sub-cent balance grid and order-level rebate accounting; “one cent per fill” is not a faithful universal model.

[arithmetic.json](arithmetic.json) gives explicit one-fill, one-contract illustrations, not trading results:

- Two 49c taker buys cost **$1.0150** under the stated assumptions: a 1.5c loss on a matched pair.
- Two fee-free 49c maker fills cost **98c**, but neither fill is guaranteed.
- A 97c taker buy costs **97.21c**; one loss erases about **34.8 wins**. At 99c the corresponding figure is about **106.5 wins**.
- A pair completed at $1.37 loses 37c per pair, erasing 37 one-cent pair wins before other differences in costs.

The captured [KXBTC15M rules](book_sample/summary.json) compare the final 60-second CF Benchmarks average against the opening 60-second average, with an “at least” tie rule and specified rounding. Coinbase spot is a predictor, not the settlement value. Official index WebSocket entitlement remains unverified in this research session.

The fresh [incentive-program snapshot](incentives_summary.json) contained 5,462 active liquidity programs, none on KXBTC15M at retrieval. The [program rules](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program) require qualifying book depth on both sides and allocate relative rewards. Target size is a book eligibility condition, not the trader's personal minimum stake. A $1 payout threshold and competing quotes matter. Count credited, attributable rewards separately from trading profit; do not assume incentives will rescue negative execution.

## What the existing repository actually establishes

These are reviews of prior artifacts, not fresh reproductions of their full datasets:

- [Skip wallet history](../lab8/skip/HISTORY.md): observed opening funding was $4,000, not a verified $100 bootstrap; the two P&L sources disagree materially. October's median combined-side purchase cost was $1.016883 before later rebates. Buying both sides alone does not explain the returns.
- [Skip rules](../lab8/skip/RULES.md): causal fitting is paused because public wallet timestamps can be block inclusion after execution. Private orders, cancellations and precise execution times are unavailable. The assertion in [freshmove/RESULT.md](../kalshi_freshmove/RESULT.md) that his exact trigger is known is stronger than this evidence supports.
- The fresh-move audit's first fully causal one-second entry buckets showed roughly **−0.92c / −0.84c** after entry fees. Its profitable faster buckets overlapped signal formation; later prints also do not prove our executable exits. No net-profit claim follows.
- [WORKLOG's 17:15 entry](../../docs/WORKLOG.md) reports recent live windows of **−$1.86 / −$2.98** and a review finding no detectable edge. Those numbers are Claude's account notes, not a new account reconciliation in this session.
- [Weather measurement](../lab9/WEATHER_WINDOW.md): only 5 of 92 proxy-lock windows contained the cited 97–98c prints, and far fewer prints were compatible with resting NO bids. Public observation valid time was not our arrival time. The [contract terms](https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf) use The Weather Company, so a METAR is not a contractual guarantee.
- [Monthly-touch audit](../lab9/KALSHI_BACKTEST.md): only nine months and incomplete index/path/execution evidence; negative training price sensitivities are not a finished strategy backtest. [Lucas's funding audit](../lab9/LUCAS_RULES.md) also does not support simple $100 compounding as the whole explanation.

## The decision and the next deliverable

Use [CLAUDE_PROMPT.md](CLAUDE_PROMPT.md) to build an isolated, read-only research harness, starting with a 48-hour data and execution feasibility report. Run the slower favorite-maker hypothesis and the fast BTC maker hypothesis as separate experiments; score net dollars per elapsed calendar day, with actual capital tied up and every loss included. The slow lane is the evidence priority; the fast lane tests whether the desired cadence is achievable.

Do not promise a return, multiply theoretical cents by every visible print, or keep changing rules on the same test data until a chart turns green. Future holdouts take weeks, and monthly settlement can take longer. A positive result may justify an owner-reviewed live proposal; a negative result kills or revises the hypothesis on new data. Nothing in this report authorizes new live orders or a cap increase.

# What the public bots appear to be doing

2026-10-13. Owner-requested reconstruction of dangerously-skip-permissions and eleven comparison wallets.
This is a completed descriptive study with concrete hypotheses, not recovered private code or a validated
trading strategy. All new collection used public, read-only endpoints. No live configuration changed.

**My best reconstruction of Skip is a two-sided pricing and execution business with substantial rebate
income.** It repeatedly buys temporary discounts, combines aggressive buys with standing bids, manages
the resulting Up/Down inventory, and settles the window. A faster Bitcoin signal is one possible input;
the observed fills also fit book-driven price fluctuation harvesting. The distinction remains unresolved.

The most consequential discovery is that the recent trading looks profitable before fees and loses money
before later rebates. Copying its entry prices without its effective fee economics can copy the activity
while losing the profit.

## 1. Skip: what we actually reconstructed

Wallet: [dangerously-skip-permissions](https://polymarket.com/profile/0xc53375ff94e96100f2b30a4b5775db35218d69a9).
Fresh collection retained 65 traded BTC five-minute windows opening 13:00–18:45 UTC on October 13;
the last closes at 18:50. There were 70 scheduled windows, with no indexed fills in five consecutive
windows opening 15:20–15:40. Query boundaries were excluded before analysis.

| Observed in this sample | Result | What it suggests |
|---|---:|---|
| Buys / sells | 5,136 / 0 | Accumulation and settlement; opposite buys can hedge earlier buys |
| Traded windows buying both outcomes | 65/65 | Managing complementary inventory is central |
| Taker share of fills / shares / purchase dollars before fees | 70.93% / 85.93% / 85.04% | Aggressive execution carries most of the economic activity |
| Median taker / maker fill | 30 / 6.19 shares | Repeated taker clips plus smaller passive fragments |
| Most repeated taker sizes | 1,144 fills of 30; 523 of 60 | A clip-based sizing mechanism is plausible; submitted orders are unseen |
| Median purchases before fees / fills per window | $822.89 / 75 | Many repeated decisions, not one large prediction |
| Fills priced 30–70¢ | 68.40% | Most trading occurs while both outcomes are plausible |
| Fills in final minute | 2.16% | A strong late-window reduction, not proof of an exact cutoff |
| Acquired shares matchable into pairs | 90.16% | Most share exposure can offset at settlement |
| Median final imbalance | 10.35% | Usually balanced, but meaningful exceptions exist |

Imbalance means `abs(Up shares - Down shares) / (Up shares + Down shares)`. The 90th percentile was 25.07%
and maximum 87.65%; no universal 15% or 25% cap is recovered. The median is a distribution summary, not
a setting. Maker/taker attribution comes from matching the public all-fill and taker-only cohorts.

### His money, with the fees restored

Two independent Decimal implementations reconciled every retained window's winning shares, resolved
Gamma outcome and indexed redemption. This is the source wallet's observed cash accounting, not a
simulation of trades we could have obtained.

| Component | Amount |
|---|---:|
| Purchase price × shares | $60,194.92 |
| Recorded purchase cash, including costs | $61,820.42 |
| Recorded redemptions | $61,305.68 |
| Result before purchase fees | **+$1,110.75** |
| Additional purchase costs, effectively all on taker fills | **$1,625.49** |
| Result after purchase costs, before later rebates | **−$514.74** |

Thirty-one of the 65 windows were positive before later credits. The best was +$270.12; the worst was
−$249.94. A weighted-average cost allocation attributes the gross result to about +$1,132.22 from matched
inventory and −$21.47 from the remainder. After purchase costs those components become −$334.46 and
−$180.28. This is an accounting convention, not identification of the bot's private paired lots or signals.

The sample would break even if 31.67% of those taker costs returned, before maker rewards. Fee recovery
of 32%, 44% or 50% would change its result to +$5.42, +$200.48 or +$298.01. **These are sensitivity
calculations, not observed credits or verified eligibility for this sample.** The public
[taker rebate program](https://docs.polymarket.com/programs/taker-rebates) contains those tiers; the
wallet's actual tier and allocation of later credits were not established here.

The committed full-history audit independently supports rebates being material. Through its earlier
cutoff it records approximately $8.10 million of purchases, +$98,590 of trading cashflow, and $97,499 of
separate credits: $85,135 taker rebates, $11,320 maker rebates and $1,044 rewards. Those are comparable
magnitudes, **not an audited division of lifetime net profit**. Open inventory, cutoff differences and a
provider-income reconciliation gap remain. The old raw archive is absent from this workspace; these
historical totals were re-summed from the committed daily CSV, not freshly recollected.

### The best concrete guess at his loop

1. Maintain an estimate of what Up and Down are worth right now, with time remaining and inventory.
   Either the book itself, a faster Bitcoin input, or a combination can supply that estimate.
2. Buy a small clip when an available ask is sufficiently cheap after effective costs. Rest bids when
   waiting offers better expected economics. Current repeated taker fills suggest a 30-share base unit
   and occasional 60-share fills; this does not recover parent-order sizes or a doubling trigger.
3. Permit a temporary directional position when the pricing opportunity justifies it. Increase the
   penalty for further exposure as inventory grows; make the opposite side more attractive.
4. Buy the complement when it becomes attractive. One Up plus one Down settles to $1, so this can
   economically hedge an earlier purchase without any SELL appearing in the wallet history.
5. Reduce participation late in the window, settle, and reuse capital. There can still be residual
   direction and losing windows. Turnover is not bankroll or compounded profit.
6. Evaluate trading cash, fees and separately paid incentives together. A large-volume fee schedule
   can change whether a small apparent edge is worth taking.

This is medium confidence in the pricing/inventory logic and high confidence in the observed execution
pattern. The exact fair-value model, feed, coefficients, order lifetime and cancel rules remain unknown.
The [detailed Skip playbook](SKIP_PLAYBOOK.md) gives a proposed objective function, competing models,
specific counterexamples and tests that could distinguish them.

### Guesses the trades already weaken

- **Always buy the side with less inventory:** only 51.17% of singleton ledger-timestamp buys
  purchased the previously smaller side. Separately, 48.54% shrank the absolute share gap; an
  underweight-side buy can overshoot. A soft preference fits better than a universal rule.
- **Every new fill must be cheaper than his preceding same-side fill:** among 1,725 singleton taker
  buys, 933 were above the strictly earlier same-side fill-group price and 655 below it; 137 were
  unchanged. The 60-share subset had 123 rises and 123 falls. This weakens a simple fill-to-fill
  averaging-down rule; it cannot rule out buying dips relative to an unobserved intervening market peak.
- **Every window is a guaranteed cheap pair:** only 29/65 weighted-average pair costs were below $1
  after purchase costs. Individual lot-pair choices remain unobservable; aggregate costs do not prove
  that a particular private lot rule was violated.
- **Only buy almost-certain late winners:** just two fills were at least 90¢, and almost all fills
  preceded the last minute.
- **The public chart proves a $100 compounding story:** the full audit's first observed funding was
  $4,000. Earlier capital elsewhere remains unknown. Neither turnover nor a profit chart verifies it.

## 2. Eleven other wallets: different businesses behind the charts

These are selected visible winners and one low-activity comparison, not a random sample of trading bots.
Their automation, common ownership and offsite hedges have not been independently verified.
The following entries are **inferred game plans**. Counts/prices are fresh observations; signal and
risk models are hypotheses. Bounded samples cover different periods, and none proves executable profit
on our account. Profiles, raw responses, sample windows, alternatives and falsifiers are in the linked
playbooks.

| Wallet | Best guess at its game plan | Most useful observed clue |
|---|---|---|
| **GoodFallen** | Skip-like BTC pricing loop: frequent takes, some passive bids, both sides and a soft inventory target | 16/16 covered windows both-sided; 77.1% taker fills; median imbalance 6.71% |
| **ce25** | Selective multi-asset short-window buyer; take mispriced odds, sometimes buy the complement | 95.3% taker; median four fills per covered window; both sides in 89/126 |
| **mo-money** | Predominantly passive crypto bids, inventory skew and complementary accumulation | 84.95% maker fills; both sides in 64/129 covered windows; more late fills than Skip |
| **DB5** | Reprice related terminal strikes/bands and trade inventory around a probability curve | 43.89% sells; 74.35% of turnover in terminal above-strikes, with meaningful band/touch activity |
| **rwo** | Historical passive crypto accumulator whose current activity has faded | Latest 1,000 fills span Aug 9–Oct 9; chart change in September −$215, October about +$5 |
| **HighTempTation** | Buy weather outcomes before the book fully reprices, then sell near 99¢ and recycle | All 239 sampled buys were takers at ≤98¢; 225 of 261 sales at 99¢ |
| **Weatherstappen** | Patiently buy near-certain weather NO, then resell at a smaller markup | Common buys 99–99.5¢, common sales 99.8–99.9¢; most fills maker |
| **LowTempTation** | Combine cheap near-certain NO with selected mid-price YES, then exit after repricing | 103 NO buys at median 97.27¢; 55 YES buys at median 46.46¢; 256 sales at 99¢ |
| **LucasMeow** | Sell remote-event insurance through expensive NO; mostly passive pieces, occasional large takes, mostly hold | Full audit: 95.27% maker fill count but only 50.47% of purchase dollars; sells also exist |
| **x6916** | Make markets on related crypto barriers; buy either outcome when cheap and resell inventory | 254 buys / 246 sells, all 500 sampled fills inferred maker |
| **amis** | Buy remote barrier NO, then recycle as its price approaches one dollar | 326 NO buys at median 94¢; 171 NO sales at median 98.7¢ |

Detailed cards: [Crypto peers](CRYPTO_PEERS.md) and [Weather and ladders](WEATHER_AND_LADDERS.md).
Medians of buys and sales across different contracts are not matched round-trip profits.

### The clearest additional mechanism: weather buy/resell recycling

HighTempTation has 226 simple same-asset, equal-size buy-then-sell cases in its bounded sample. The median
public timestamp gap is five seconds. A separate activity query retains both legs of 225 cases and
corroborates their quantities and positive recorded cash differences. This is selected matched-subset
evidence, not whole-wallet P&L, actual execution latency, or a five-second usable-cash guarantee.

My concrete guess is: **observe information that makes an outcome nearly decided; take remaining cheap
offers; sell into the repricing near 99¢.** Weatherstappen appears to capture a narrower margin with more
patient bids. LowTempTation also buys mid-priced YES, which needs either a forecast/nowcast or earlier
knowledge of the final result; a simple dead-bucket NO rule cannot explain all of it.

Exact causal weather publication has not been matched to these trades. The alternatives include ordinary
book arbitrage and another faster source. The earlier METAR-to-Kalshi transfer claim needs correction:
the repository's own contract audit found TWC as the primary source in all 252 sampled Kalshi contracts.
Matching a station or a favorable historical outcome does not turn a METAR into a contractual lock.

### Why the long-term ladder winners are different

Lucas generally earns small premiums for accepting rare, correlated barrier-touch risk over days. Its
full audit shows substantial external capital, including roughly $397,583 net funding; it does not verify
a simple $100-to-fortune compounding account. A rare miss can consume many premiums. x6916 repeatedly
buys and sells both outcomes, while amis takes profits instead of universally holding. They should not
all inherit one far-strike NO algorithm simply because their charts look similar.

## 3. What I would reconstruct first from this evidence

For the owner's Skip-like objective, **GoodFallen is the best comparison wallet and Skip's fee-aware,
inventory-managed two-sided loop is the right family to reconstruct.** The exact signal remains a contest
between external-price fair value and book/inventory-driven harvesting. Both deserve explicit candidate
models; the public trades do not justify asserting that a normal-CDF fair-value formula is his source code.

For a different mechanism with a clearer observed exit, HighTempTation's buy/resell pattern is especially
informative. It gives a concrete entry-price region and repeatable exit behavior. Whether our permitted
venue leaves sufficient executable liquidity after the correct source arrives is still unproved.

On Kalshi, carry over the architecture and re-estimate the economics. Do not import Polymarket's rebate
tier, settlement definition, five-minute turnover, apparent holding time or source-wallet dollar size.
The earlier Kalshi public snapshot found no KXBTC15M incentive program, so a source strategy depending
on rebates may fail there even with very similar fills. Existing owner caps and live rules are unchanged.

## Evidence and reproduction

- [PLAN.md](PLAN.md): descriptive scope; this study never opens an existing TEST or claims a new holdout.
- [SKIP_PLAYBOOK.md](SKIP_PLAYBOOK.md): inferred algorithm, parameter evidence and falsification.
- [METHOD.md](METHOD.md): sampling, accounting, provenance and offline verification instructions.
- [evidence/MANIFEST.json](evidence/MANIFEST.json): SHA-256 hashes of the frozen public evidence files.
- Existing audits: [Skip history](../lab8/skip/HISTORY.md), [Lucas rules](../lab9/LUCAS_RULES.md),
  [Kalshi weather correction](../lab9/WEATHER_WINDOW.md).
- Primary references: [public API schema](https://data-api.polymarket.com/v2/openapi.json),
  [fees](https://docs.polymarket.com/trading/fees),
  [rebates](https://docs.polymarket.com/programs/taker-rebates).

No commercial bot was purchased or run. A seller claims to operate Skip, but the reviewed public profile
does not authenticate that claim. The reconstruction above relies on public trading/accounting evidence,
not the seller's asserted ownership or performance.

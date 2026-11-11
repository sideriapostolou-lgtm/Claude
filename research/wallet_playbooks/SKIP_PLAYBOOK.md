# Skip: the most likely private loop, reconstructed from visible behavior

2026-10-13. **This is a specific proposed reconstruction, not recovered code.** Evidence is the 65-window
fresh sample in [REPORT.md](REPORT.md), plus the earlier full-history audit. All new totals and public
inputs are frozen under `evidence/skip/`. No prediction target or forward profit test has passed here.

## 1. The state it probably tracks

At minimum, per window: time remaining, Up and Down shares/costs, current available prices, outstanding
orders and available capital. The last two are necessary implementation state but invisible in the fill
history. Likely additional state is a fair Up probability, recent book/underlying movement, signal
confidence and effective fees after verified incentives.

The directly visible choices are both-side accumulation, frequent aggressive buys, some passive fills,
variable imbalance and early/middle-window concentration. External exchange selection and the existence
of a separate momentum signal remain guesses.

## 2. A concrete objective that fits the behavior

Let `u` be estimated fair Up probability, `D = Up shares - Down shares`, and `s` be +1 for buying Up and
−1 for buying Down. For a proposed purchase of `q` at price `p`, one plausible objective is:

```text
fair(side) = u for Up, 1-u for Down

score = q * (fair(side) - p)
        - estimated actual execution fee
        + conservative earned incentive estimate
        - lambda * u * (1-u) * ((D + s*q)^2 - D^2)
        - allowance for stale prices / adverse selection
```

This is expected terminal value less costs and an inventory-risk penalty. `D²*u*(1-u)` corresponds to
the variance of an unhedged binary payout under the model. `lambda` is a proposed risk preference, not
a recovered parameter. A finite penalty allows some buys to increase imbalance and rewards useful
complement purchases. It does not impose a universal cheap-pair rule.

For an immediate take, compare the score with a threshold. For a resting bid, account for fill
probability and the fact that fills may arrive precisely when the value estimate worsens. An immediate
and a passive threshold need not be equal. The inferred business chooses between price improvement,
speed, inventory and effective fees.

**Fair probability has two live hypotheses:**

- **External-price model:** use the exact contractual settlement reference, time remaining, relevant
  realized/short-horizon volatility and recent BTC moves to update odds faster than the book. A
  probability formula must match the actual contract, including any averaging interval; blindly using
  terminal spot crossing is not justified.
- **Book/inventory model:** use book prices, depth, spreads and recent price changes as the estimate;
  lean into temporarily attractive quotes while gradually offsetting inventory. This needs no large
  independently predictive BTC forecast. Rebate income may make small gross margins viable.

Both explain the current visible purchases. A third possibility is separate directional taker and
passive inventory modules sharing one wallet. Different fill sizes alone do not establish that design:
resting orders naturally fragment into smaller fills.

## 3. Specific guessed operating rules

```text
when a new eligible window opens:
    initialize inventory from actual fills and existing positions
    obtain fresh market state; no trade merely because the clock opened

on a meaningful price / book / inventory update:
    update fair probabilities and signal confidence
    recompute effective cost and directional inventory
    evaluate both Up and Down, including complement buys that hedge inventory

    if an available ask clears the immediate score threshold:
        buy a bounded clip; occasionally allow a larger clip

    maintain passive bids where a conditional fill has positive expected value
    reprice/cancel when the value, inventory or remaining time changes enough

as the final minute approaches:
    sharply reduce new accumulation and cancel obsolete quotes
    retain only risk justified by the remaining signal

at settlement:
    collect winning payouts
    record trading result, fees and later incentive income separately
    release capital for subsequent windows
```

The cancel/reprice logic is an implementation hypothesis; canceled/unfilled orders are not in the
dataset. There is no identified exact trigger of "$X Bitcoin move," "Y milliseconds," or "Z¢ edge."
Filling 30 or 60 shares does not prove these were the submitted sizes. An implementation experiment
must declare its own values rather than falsely label them his recovered settings.

| Candidate rule | Evidence and confidence | What is still a guess |
|---|---|---|
| Evaluate both complementary outcomes | 65/65 traded windows both-sided; high | Whether both quotes are always simultaneously live |
| Mostly take immediate opportunities, with passive bids too | 85.04% of gross purchase dollars taker; high | IOC/FOK/GTC instructions and actual order lifetime |
| Use repeated base-sized purchases | 30 and 60 shares repeatedly fill; medium | Base parent-order size, double-clip threshold and hidden partial fills |
| Prefer balance without requiring it on every buy | Median imbalance 10.35%, but most singleton buys do not reduce the absolute share gap; medium | Penalty coefficient and any separate hard maximum |
| Back off late | 97.84% of fills timestamped before last minute; high in this sample | Exact cancel clock and whether late fills are delayed or intentional |
| Hold rather than sell, using complement buys to hedge | No sells in this sample or earlier audited history; high for the observed strategy | Off-wallet hedges and whether another future regime can sell |
| Count rebates in the business economics | Historical credits material; high | Current eligible tier, incremental threshold and attribution to each window |
| Predict short-horizon BTC moves | Plausible, not established; low-medium | Feed, feature, time horizon, model and actual response latency |

## 4. Actual windows show the exposure it tolerates

**13:30 UTC, Down ultimately wins.** It bought 1,113.31 Up shares at a gross average of 50.7212¢ and
1,687.28 Down at 48.4701¢. Total recorded purchase cash was $1,417.17 including $34.65 of costs. The
recorded payout was $1,687.28: **+$270.12 before later rebates**. On the weighted-average convention,
the matched component lost $18.98 and the residual Down inventory gained $289.09.

**13:55 UTC, Down also wins.** It bought 2,079.81 Up at 40.1906¢ and 1,599.87 Down at 59.9998¢. It
paid $1,849.81 including $54.00 costs and received $1,599.87: **−$249.94 before later rebates**.
The same convention allocates −$49.85 to matched inventory and −$200.09 to the unmatched Up.

Both examples accumulated both sides. The unequal quantities explain why the two-sided strategy still
has material directional outcomes. A separately selected private lot allocation could produce a
different component attribution while leaving the total unchanged.

## 5. Models weakened by the fresh evidence

| Simple proposed explanation | Counterexample / limitation |
|---|---|
| Buy only when the new price plus opposing historical average is below $1 | Only 54.15% of eligible buys pass against strictly earlier opposing VWAP. This is an average-cost diagnostic, not identification of individual paired lots. |
| Every buy must shrink the absolute share gap, `abs(Up-Down)` | Only 48.54% of 2,050 singleton buys do. Atomic timestamp-group analysis gives the same qualitative result. |
| A universal 25% final imbalance cap | Five-minute final imbalances reach 87.65%. A temporary cap, changing denominator or early-exit regime cannot be recovered from final positions alone. |
| Every new taker fill must exceed the preceding same-side fill price | 655 of 1,725 singleton taker buys are below the previous same-side timestamp-group VWAP. This is not a test against unobserved market momentum. |
| Always average down against the previous own fill, including larger clips | 933 observations are above that earlier VWAP; the 60-share subset splits 123 rising / 123 falling / 16 unchanged. Dips relative to an intervening unobserved peak remain possible. |
| Final winner prediction explains the whole gain | The larger side wins only 29/65 windows in this sample; gross matched-inventory attribution is positive and gross residual-direction attribution slightly negative. This does not prove the signal never predicts short-horizon moves. |
| Pure tiny-odds moonshot hunting | Prices mostly fall in 30–70¢; no fills below 12¢ in this sample. |
| Every scheduled window gets traded | No indexed fills in five consecutive interior windows; cause unknown. |
| Big gross chart means fees are negligible | $1,625.49 of purchase costs exceeds the $1,110.75 gross result in the fresh slice. |

Nearly 59.15% of fills share their market timestamp with another fill. Statistics above use only
singleton ledger-timestamp groups or strictly earlier groups where ledger ordering matters. Neither block
timestamps nor its own selected fill-price path establish a causal trigger or a trading latency.

## 6. Ranked explanations and decisive distinguishing observations

1. **Hybrid fair pricing + inventory + effective fees.** Strong overall fit. It predicts buys when
   available prices improve relative to a current value estimate, with thresholds varying by exposure.
   Weaken it if out-of-sample choices are explained just as well by static clip/clock rules, or if
   inferred residual value never improves selection after costs.
2. **Book-based oscillation harvesting + rebates.** Plausible and comparatively parsimonious. It
   predicts opposing inventory and turnover tied to price fluctuations without a necessary external
   BTC lead. Weaken it if a causally earlier external price signal consistently explains actions the
   book model misses. Own-fill ranges cannot settle this because more fills mechanically sample more
   prices.
3. **Directional taker plus separate passive module.** Plausible. It predicts systematically different
   post-fill markouts and inventory sensitivities by role. Weaken it if conditional differences vanish
   once partial-fill fragmentation, prices and queue selection are controlled.
4. **Guaranteed pair arbitrage or a late winner sniper.** Poor descriptions of the full observed
   business. Losing windows, after-cost aggregate pair prices and timing contradict their simplest
   forms. Selected profitable pairs can still occur inside a broader strategy.

The next identifying analysis should use all eligible decision times, including nontrades, synchronized
source/book arrivals, and fees/rebates actually attributable to the account. Otherwise many flexible
models can explain executed fills after the fact. This does not erase the concrete reconstruction
already supported above; it identifies the remaining private component instead of pretending it known.

## 7. Applying the reconstruction to our business

The portable elements are complementary inventory accounting, distinct immediate/passive decisions,
an explicit inventory penalty, measured data freshness and full fee accounting. The nonportable
elements are Skip's private speed, market source, participant advantages, rebate tier and capital scale.

The current research changes no real strategy. Claude can compare these candidate families inside the
existing arena under its registered protocol. Filling a guessed rule into code would not establish an
edge, and the observed 30/60-share fills are not permission to change the owner's limits.

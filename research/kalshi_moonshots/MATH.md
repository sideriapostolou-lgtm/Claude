# Payout, exits, losing streaks and evidence

Own arithmetic, 2026-10-13. [Machine-readable calculations](arithmetic.json). These are illustrations under
stated assumptions, not observed probabilities, expected profits or the owner's current balance.

## Price versus fee-inclusive multiple

Current sampled series use the standard quadratic taker coefficient 0.07. For one fill at price `p`,
quantity `Q`, and a direct account, this illustration ceilings the model fee to $0.000001 and the total
debit to $0.0001. Multiple partial fills need the full order-accumulator model, not independent copies of
this shortcut. [Official fee rounding](https://docs.kalshi.com/getting_started/fee_rounding) and
[schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf).

```text
model_fee = ceil_to(.000001, .07 * Q * p * (1-p))
cash_debit = ceil_to(.0001, Q*p + model_fee)
winning_gross_multiple = Q / cash_debit
break_even_probability = cash_debit / Q
```

| Raw ask | One-contract debit | Winning payout/debit | Quantity for a $1 total debit, one full fill |
|---:|---:|---:|---:|
| $0.007 = 0.7¢ | $0.0075 | 133.33x | 133.57 |
| $0.002 = 0.2¢ | $0.0022 | 454.55x | 467.35 |
| $0.001 = 0.1¢ | $0.0011 | 909.09x | 934.64 |

The right column assumes quantity increments of .01, sufficient depth at a single price and no other
minimum-order restriction. It is not an executable offer. A winning settlement pays that many dollars;
net profit subtracts the $1 spent. A loss consumes the full $1. Changing quantity changes fee rounding,
which is why multiplying a one-contract UI multiple by $1 is not exact.

For `N` bought contracts, true terminal win probability `q` and all-in cash spent `C`:
`expected_terminal_profit = N*q - C`. A high payout establishes neither `q` nor positive expected profit.

For actual exit quantities `r_j` at bids `b_j`, sale fees `F_out`, residual quantity `N_remaining` and result `Y`:
`net_profit = sum(r_j*b_j) - F_out + N_remaining*Y - C`.
The offered ask, chart high or a stop trigger does not enter this equation unless a real/simulated honest
fill occurs there. An early sale can lose money after fees even when the displayed price is higher.

## Why a large edge can still have a long losing streak

Hypothetical constant all-in cost `c=.0011`, and assume `q=.0022`, **twice break-even**. No such edge has
been measured. With independent trials:

| Quantity | Calculation | Result |
|---|---|---:|
| First 25 bets all lose | `(1-q)^25` | 94.64% |
| First 100 bets all lose | `(1-q)^100` | 80.23% |
| Theoretical full-Kelly fraction spent | `(q-c)/(1-c)` | 0.11012% of bankroll |
| Quarter of that fraction | `0.25*(q-c)/(1-c)` | 0.02753% |
| Full Kelly on hypothetical $25 | `25*(q-c)/(1-c)` | $0.02753 |
| Quarter Kelly on hypothetical $25 | `6.25*(q-c)/(1-c)` | $0.00688 |

Kelly assumes known stable probabilities, repeated independent trials and executable size. Those are
not established here. It is a diagnostic explaining why $1 per attempt is large for a small bankroll,
not a recommendation to place these tiny orders. Shared crypto moves and model errors add correlation.

## Rare-event sample size

Illustrative exact binomial power calculation: iid equal-cost windows, null probability .0011, one-sided
alpha .05, 80% power, search sample size in increments of 100. Critical wins `k` satisfy
`P_null(X>=k)<=.05`; power is `P_alternative(X>=k)`. First qualifying grid points:

| Hypothetical true probability | Advantage over break-even | Independent opportunities |
|---:|---:|---:|
| .00132 | 20% | 153,500 |
| .00165 | 50% | 27,400 |
| .00220 | 100% | 8,300 |

These favorable simplifying assumptions exclude correlated windows, varying prices, selection and
multiple testing. Even 27,400 windows require about 285 days at 96 BTC windows/day if every one qualified;
the actual eligible count is lower. Thousands of fills within a few windows do not supply that evidence.

Zero wins in 3,000 iid trials give a one-sided 95% upper probability bound
`1 - .05^(1/3000) = .00099808`, below the illustrative .0011 cost. Losses cannot be excused indefinitely
as merely waiting for a jackpot. The actual varying-cost/dependent strategy requires a suitable clustered
analysis, not this simple binomial shortcut.

## Settlement-average diagnostic

Under arithmetic Brownian motion only, with dollar volatility `sigma` per square-root second, averaging
length `L=60` and time `h` until averaging starts, average variance is `sigma²*(h+L/3)`. Inside the interval,
with `r` seconds remaining and known integral `I`, mean is `(I+r*S_now)/L` and variance `sigma²*r³/(3*L²)`.
For discrete remaining sample offsets `d_i`, use `sigma²/L² * sum_ij min(d_i,d_j)`.

These formulas diagnose why instantaneous-spot probability is wrong near expiry. They do not capture
jumps, changing volatility, index basis or parameter error and are not a trustworthy rare-tail signal.
Correct discrete timestamps, contract rounding and empirical calibration remain necessary.

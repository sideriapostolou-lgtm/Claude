# Lab 4: prediction markets. The "near-certain grind". Pre-registration, version lab4-v1

Written 2026-10-09 ~14:45 UTC, before any return of this study was read. Owner direction (same day): the team
should "be working all day making money... stocks, prediction markets, crypto, anything... $1, 50-cent profits
all day long" to pay for the town's infrastructure. The one strategy family in public markets that literally
looks like that is **buying outcomes that are almost decided**: a contract at 97-99 cents pays $1 at resolution
minutes or hours later, a 1-3 % gain per trade, available many times a day (every finished match, every
5-minute crypto market). The catch is the tail: the few times a 98-cent contract loses, it loses 98 cents. Whether
the many small wins pay for the rare large loss, after fees, is an empirical question with a long literature
(the favourite-longshot bias says favourites are *under*priced on average: that would be our edge). This lab
tests it the way labs 2 and 3 did: fixed rules, time splits, one look at TEST.

Honesty rules carried over: no trade on screen that did not happen on the venue; paper first; real money only
after TEST passes AND the owner flips it; a TEST pass never funds real money by itself.

## 1. Data and universe (research/lab4/data.py)

- **Venue:** Polymarket (public, keyless): the Gamma market list (resolved markets, final outcome prices, fee
  flags) and the Data API trade tape (every fill with time, price, size, side, outcome). The CLOB price history is
  empty once a market resolves, so the tape is the price path. Fetched from this environment on 2026-10-09;
  collection parameters fixed before any result was read: markets with `closedTime` from **2026-07-01**, volume
  >= **$20,000**, tape = the last **14 days** before `closedTime` plus one hour after.
- **Universe:** binary markets (2 outcomes) with a single winner (one outcome priced 1 at resolution; split
  resolutions excluded), >= 50 fills in the tape. Category = the venue's `feeType` family (sports_*, crypto_*,
  politics_*, culture_*, finance_*, zero_fees, none) because Gamma carries no category field; the event slug is
  kept for reading.
- **Kalshi** (US-legal) is NOT in this study: its public API rate-limits anonymous candlestick reads to a trickle
  (HTTP 429 after a handful of calls on 2026-10-09); a free account key would lift that. A Kalshi replication is a
  follow-up, pre-registered separately, if Polymarket shows an edge.
- **Splits by `closedTime` (UTC):** TRAIN 2026-07-01 -> 2026-08-15 23:59; VAL 2026-08-16 -> 2026-09-15 23:59;
  TEST 2026-09-16 -> 2026-10-08 23:59 (one look; the run refuses without `LAB4_ALLOW_TEST=1`). Markets that
  resolved after 2026-10-08 are the live-shadow set, not part of this study.

## 2. Fills, costs and latency (FIXED)

- We only ever BUY an outcome and hold to resolution (no selling before the end: that is a different study).
- **Signal:** a fill on outcome `o` at price `p >= theta` observed at time `t`, within the last `H` hours before
  `closedTime`. One trade per market per cell: the FIRST such fill.
- **Latency tau = 10 s:** our order executes at the first fill on the same outcome at or after `t + tau`, at THAT
  fill's price `p_exec` (whatever it is: this is the slippage model). No fill within 10 minutes = the trade is
  skipped and counted as "missed".
- **Ticket:** $20 per trade (`shares = 20 / p_exec`). Payout: `shares * 1` if `o` wins, else 0.
- **Fees:** the venue's taker fee for that market, computed from the market's own fee flags (`feesEnabled`,
  `takerBaseFee`, `feeType`) with the formula published by Polymarket. The exact formula and its source URL are
  fixed in **Amendment 1** below before any TRAIN return is read (the venue research was still running when this
  plan was written). Gas: Polymarket relays orders gas-free; $0.
- **Net return per $1 at risk:** `(payout - fee - 20) / 20`.

## 3. Hypotheses (grid fixed; the TRAIN stage picks at most ONE cell per hypothesis)

- **P1 near-certain, all markets:** theta in {0.95, 0.97, 0.99}, H in {1, 6, 24, 168} hours. 12 cells.
- **P2 late-game sports:** P1 restricted to the sports fee families, H in {0.25, 0.5, 1, 2} hours. 12 cells.
  (The practical "all day" source: matches finish around the clock.)
- **P3 crypto up/down:** P1 restricted to the crypto fee families (5-minute / hourly price markets), H in
  {1/60, 5/60} hours, tau = 10 s as everywhere. 6 cells.
- **Control C1 longshots:** buy at `p <= 1 - theta` (the other side of the same fills). The favourite-longshot bias
  predicts this LOSES; it must not beat P1 for the story to hold. Not a candidate for selection.

Selection in TRAIN: the cell with the highest mean net return whose market-bootstrap CI95 lower bound is > 0 and
with n >= 100 trades; none qualifying = NO EDGE for that hypothesis. VAL: the selected cell must again show mean
net return > 0 with CI95 lower bound > 0, n >= 100, AND beat the calibration placebo (below). TEST: one look at
the selected cell only.

## 4. Readings (pre-registered)

Per cell: n trades (and missed), win rate vs mean `p_exec` (the calibration gap: win rate minus price is the
gross edge), mean net return per $1 with market-bootstrap CI95 (B = 2000), mean $ profit per $20 ticket, worst
single loss, longest losing streak, **throughput** (trades available per day in the window: the "all day"
question), capital lock time (hours from entry to resolution), daily P&L series (markets grouped by resolution
day) with its Sharpe-like ratio and max drawdown, and the per-category breakdown.

**Calibration placebo:** the same trades with outcomes re-drawn as Bernoulli(`p_exec`) (perfect calibration),
2000 draws: the distribution of mean net return under "no edge". The real mean must sit above its 95th
percentile at VAL.

## 5. What a pass would and would not mean

A pass says: on Polymarket, over these months, buying near-certain outcomes made more on the wins than it lost on
the upsets, after fees, with enough trades per day to matter. It does not say the next months will; the live
shadow set (markets resolving after 2026-10-08) is the first out-of-sample check, read weekly. **Access:**
Polymarket blocks trading from the United States (and other countries); whether the owner can trade there at all
is a question for the owner, not this lab. A Kalshi replication would be needed for a US path.

## 6. Trial ledger

Every cell evaluated on any split is a trial in `research/lab4/trials.json`; the running count across labs 2, 3
and 4 is reported in every result file.

## Amendment 1 (2026-10-09 ~14:55 UTC, before any TRAIN return was read): fees and access, from the venue docs

Source: https://docs.polymarket.com/trading/fees (read 2026-10-09; the page carries no date). polymarket.com fees are
**taker-only**: `fee = shares x rate x p x (1 - p)`, charged at match time in the market's currency; resting
(maker) orders pay nothing. Taker rates by category: Crypto 0.07; Sports 0.05; Economics, Culture, Weather, Other
0.05; Finance, Politics, Mentions, Tech 0.04; Geopolitics 0. In this study the rate is read from the market's
Gamma `feeType` family (`crypto_*` 0.07; `sports_*`, `culture_*`, `economics_*`, `weather_*` 0.05; `politics_*`,
`finance_*`, `mentions_*`, `tech_*` 0.04; `zero_fees` or `feesEnabled = false` 0; an unknown family is charged the
most expensive rate, 0.07, so an unknown never flatters a result). Every trade in this study is a taker (we hit a
printed price), so it pays the fee. At p = 0.98 the fee is 0.05 x 0.98 x 0.02 = $0.00098 per share, about 0.1 %
of the ticket: the costs that decide this study are the upsets, not the fees. Gas is $0 (orders are relayed).

**Access (for the owner, not for the lab):** polymarket.com lists the United States, the United Kingdom, France,
Germany, Italy, Australia, Singapore, Canada (several provinces) and others as "close-only on frontend and API"
(https://docs.polymarket.com/api-reference/geoblock, read 2026-10-09): no new positions may be opened from there,
and a VPN is a terms-of-service violation. The US-regulated path is Polymarket US (QCX LLC, a CFTC-regulated
exchange) whose fee is `0.0695 x shares x p x (1 - p)` for takers with a maker rebate
(https://docs.polymarket.us/fees, effective 2026-10-01), or Kalshi. A pass in this lab would therefore be
re-costed at 0.0695 before any paper desk is built, and the venue would be the owner's choice.

The trade tape used here (Data API `/trades`) is the fills of polymarket.com; the Data API v2 `/v2/prices-history`
(1-minute buckets kept at least 7 days, 5-minute at least 60 days, 30-minute at least 90 days) is a documented
alternative for coarser history and is not used in version lab4-v1.

## Amendment 2 (2026-10-09 ~15:05 UTC, before any TRAIN return was read): the owner's venue and P4

The owner is in Washington State and will trade, if anything passes, on **Polymarket US** (QCX LLC, the
CFTC-regulated venue), where sports contracts are not offered to them. On 2026-10-09 the venue's public gateway
(`gateway.polymarket.us`, no key) listed 5,000 open markets: sports 4,402, culture 227, politics 217, crypto 47,
finance 46, technology 36, macro 12, geopolitics 7, science 6; of the ~3,000 markets settling per day, ~2,900 are
sports, ~30 climate (daily weather), ~5 crypto, a handful of culture / politics / finance. Its taker fee is
`0.0695 x shares x p x (1 - p)` (`feeCoefficient` on each market), tick 0.001, minimum 1 contract.

Added hypothesis, same mechanics as P1: **P4 non-sports grind**, the markets the owner can actually trade:
fee families `crypto`, `politics`, `culture`, `finance`, `economics`, `weather`, `mentions`, `tech` (everything
but `sports`), theta in {0.95, 0.97, 0.99}, H in {1, 6, 24, 168} hours (12 cells, selectable). The published
evidence (Cardozo and Rivero-Wildemauwe 2026) finds the favourite edge in crypto and politics and none in sports,
so P4 is the hypothesis that matters for the owner's path; P2 (sports) stays as written for the record.

Re-costing rule: a cell selected on polymarket.com data is re-evaluated with the US fee (0.0695) before any paper
desk is built; the US venue's own books are then recorded live (a recorder on the public gateway) so the paper desk
fills at that venue's printed prices, not at polymarket.com's.

Correction to the counts above (2026-10-09 15:12 UTC, still before any TRAIN return): the recorder's first live
poll of the US gateway found **537** non-sports markets ending within 48 hours: 477 crypto (hourly and weekly
"BTC above / below a strike" markets) and 60 climate (daily city high-temperature brackets). The "~5 crypto per
day" settlement count above undercounts the hourly crypto series; the recorder measures the real supply.

Correction (2026-10-09 15:40 UTC, still before any TRAIN return): the owner confirms that Polymarket US does
offer sports contracts where they are, so P2 (late-game sports) is a live candidate for their desk as well, not
only for the record; the published evidence still predicts no favourite edge in sports, and the lab decides. The
US recorder is extended to sports markets in progress (from game start until settlement), capped to stay under the
gateway's public rate limit.

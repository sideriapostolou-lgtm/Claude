# Backtests: the HIGGS and HOOKI nights

The viral post claimed one night of bot trading made **+$5,479 on HIGGS**, starting from
$12,161, and another night made **+$6,271 on HOOKI**, starting from $17,608. Here, nightcrawler's
default "dip-rebound" strategy is replayed on the real 1-minute candles of those same two nights.
The candles come from GeckoTerminal and live in `data/samples/`. Every trade is listed in
[`samples.json`](samples.json).

## Results with default settings ($100 start)

| Coin | Night (UTC) | Trades | Wins | Net P&L | Return | Max drawdown | Paid in costs |
|------|-------------|-------:|-----:|--------:|-------:|-------------:|--------------:|
| HIGGS | Oct 4 22:00 to Oct 5 06:00 | 5 | 2 | **-$8.32** | -8.3 % | 17.0 % | $2.37 |
| HOOKI | Oct 5 22:00 to Oct 6 07:00 | 9 | 1 | **-$26.10** | -26.1 % | 27.1 % | $3.89 |
| Both | | 14 | 3 | **-$34.42** | -17.2 % | | $6.26 |

How the trades closed:
- HIGGS: 2 stop losses, 2 time stops (one of them a winner) and 1 take-profit followed by a trailing stop.
- HOOKI: 8 stop losses and 1 take-profit followed by a trailing stop.

These numbers fill every stop where its market sell really lands (G22, 2026-10-09). With the
earlier fill model (a stop at `min(level, close)` of the minute that triggered it) the same
nights gave HIGGS -$2.08 and HOOKI -$25.79: that model was optimistic, because a falling coin
keeps falling while the sell is on its way.

## Compared with the post's claims (its bankroll, ~$2.7K positions)

| Coin | Start | Claimed | Backtest, with costs | Backtest, zero costs (impossible best case) |
|------|------:|--------:|---------------------:|--------------------------------------------:|
| HIGGS | $12,161 | +$5,479 | **-$2,311.15** (6 trades) | -$800.44 (5 trades) |
| HOOKI | $17,608 | +$6,271 | **-$4,604.05** (9 trades) | -$2,367.53 (8 trades) |

For these runs, positions were set with `POSITION_PCT 0.25` and capped at `MAX_POSITION_USD $2,700`.
At $2.7K per trade, the linear impact model charges about 4 % per side, so costs alone take
$1.4K on HIGGS and $2.3K on HOOKI. Even with every fee removed, the strategy does not get
anywhere near the claimed profits on either night.

**Bottom line:** on the very nights the post shows, a mechanical, no-hindsight version of
"buy the dip after buyers come back" loses money. These results don't prove that the post was
faked: it could have used another strategy, other coins, or luck. They do show that its numbers
can't be reproduced by the kind of strategy it described, and that fees and price impact eat
most of whatever edge such a strategy has.

## How the replay works (no lookahead)

- The strategy decides only on **closed** candles. At the close of candle `i`, it sees candles
  `0..i` and nothing else.
- Tests append arbitrary future candles and replace every candle after a cut with garbage. In
  both cases, no earlier decision changes.
- Entries fill at the **next** candle's open, plus fee (100 bps), linear impact (150 bps per
  $1K) and $0.05 network fee per side. You never get the close you decided on.
- Exits are checked inside each candle in **pessimistic** order, filled the way a bot that
  polls the price every 10 seconds could fill them:
  - A stop, a trailing stop or a time exit is a market sell. It fills at the lowest price
    (`min(open, low)`) of the minute it lands in: the next minute when the stop was crossed
    inside a minute, the same minute when the price gapped through the stop at its open (or the
    time ran out). It never fills better than the stop level, or the close of a minute that
    closed below it. So a gap fills below the stop, and a rug is booked where the sell really
    filled, not at the stop.
  - The take-profit fills only when the candle **closes** at or above it; a one-minute wick
    through it is not a fill.
  - If the stop and the take-profit are both inside one candle, the stop wins.
  - The trailing stop follows the **closes** of earlier candles, not their wicks.
  - The candle a position was filled in can already stop it out.
- Missing minutes are filled with flat, zero-volume candles, exactly like the live candle
  client does, so a gap breaks a run of green candles in both.
- This fill model is part of `CostModel` (`stop_fill`, `tp_needs_close`, `peak_from`) and is
  recorded with every result. `CostModel(stop_fill="close")` is the model used until
  2026-10-09 (HIGGS -$2.08, HOOKI -$25.79). The optimistic model the first published runs used is
  `CostModel(stop_fill="level", tp_needs_close=False, peak_from="high")`; it gave HIGGS -$1.42
  and HOOKI -$23.66 on these nights.
- Position size uses the same `risk.size_position_usd` math as the live bot, and starting
  equity is $100. There is one position at a time and a 30-minute cooldown after each exit.
- Entries are allowed only inside the night window. A position still open when the window ends
  is managed by its normal exits.

## What the backtest does NOT model (each makes it look better than live)

- The rug filter (cocoon), the big-sell radar, the AI judge and the 5-minute buy/sell-ratio gate
  are all skipped. They can only block trades, and blocking can't be scored without the data
  those checks would have seen at the time.
- Pool liquidity isn't known, so the $30K liquidity floor isn't checked. The age window and the
  market-cap window (`supply x close`) are checked.
- These runs allow any token age up to 48 h. Both coins were viral and trending, and the live
  crawler re-discovers a trending coin every 6 hours, so that is the closer model for them. For
  ordinary fresh launches the live bot watches a coin only from its first hour for
  `WATCHLIST_TTL_H` (6 h). `nightcrawler backtest` mirrors that by default (the coin must pass
  the market-cap window at maturity, and entries stop 7 h after launch); add `--any-age` to lift
  it. With that window, HIGGS (launched at 12:26 UTC) could not be traded at all on its night.
- Only 1-minute data is used. Within a candle, the order of the high and the low is unknown, and
  the pessimistic ordering covers that.

## Dataset collector smoke test (live, 2026-10-08)

**The new-pools listing is short.** GeckoTerminal's `new_pools` pages 1-10 hold only the
~200 newest Solana pools, which is about **3 minutes** of launches (checked live). A pool
that's already 12-24 h old never appears there. So `nightcrawler collect` keeps a **census**
(`census.jsonl`): every listed pool is recorded when it's born, before its fate is known, and
its candles are downloaded once it's old enough. Run `collect` periodically (for example,
hourly) to build an unbiased dataset.

**What the smoke run covered.** The run was done twice: first with 12 pools (as planned),
then extended to every census pool at least 45 minutes old. That makes **40 pools**, all
created between 15:28 and 15:31 UTC: 28 pump.fun curve pools, 5 meteora-dbc,
5 meteora-damm-v2, 1 PumpSwap and 1 raydium-launchlab. None had 12 h of history yet, so each
file holds the ~2 h that existed. Forty files were written, with no pool failures.

GeckoTerminal answered **98 of 136 calls with HTTP 429** (a shared IP). The client retried
until all but 2 listing pages succeeded. The pages it missed are simply not in the census.

**What the data showed.**
- 11 of the 40 pools traded in only **one** minute ever, and 24 in five minutes or fewer.
- 6 pools fell more than 90 % from their first price, and they are kept.
- Real peaks topped out at a market cap of about $65K. One 2-candle pool printed a bogus
  $23.7M high from a single mispriced trade, which the $5M cap excludes anyway.
- None closed above the strategy's $100K market-cap floor.

`run_many` result: **40 series, 0 trades, $0 P&L**. That's the honest base rate. Almost every
new pool dies within minutes, which is why no survival filter is applied: filtering out the
dead pools would hide exactly this. A meaningful multi-coin test needs a census collected over
days, because only a small share of pools ever enters the trading universe (0 of 40 here).

## Reproduce

```python
from nightcrawler.backtest import Backtester, load_series
from nightcrawler.models import StrategyParams

candles, meta = load_series("data/samples/higgs_1m.json")
# default $100 run (the HOOKI night is trade_from=1791237600, trade_until=1791270000)
r = Backtester(StrategyParams()).run(candles, meta, trade_from=1791151200, trade_until=1791180000)
print(r.metrics)
# the post's bankroll
r = Backtester(StrategyParams(), start_usd=12161, position_pct=0.25, max_position_usd=2700).run(
    candles, meta, trade_from=1791151200, trade_until=1791180000)
```

If `entry_signal`, the sizing or the cost model changes, `tests/test_backtest.py::test_published_sample_results_reproduce`
fails. When that happens, regenerate `samples.json`.

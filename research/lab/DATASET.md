# Strategy lab: dataset, costs and harness

This lab is for finding out, honestly, whether a fully mechanical strategy has a real edge on freshly
graduated pump.fun coins after realistic costs, or whether none exists.

A backtest that looks good only because of lookahead, survivorship, low cost estimates, overfitting
or one lucky coin is worse than having no strategy. It would lose real money.

The data lives in the session scratchpad, which is not committed:
`/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/lab/`.
Below it is called `LAB`. You can override it with the env `LAB_DATA`.

## 1. The universe

**What it is.** Every coin returned by the pump.fun census for graduated coins:
`GET frontend-api-v3.pump.fun/coins?sort=created_timestamp&order=DESC&complete=true&includeNsfw=true`.
The census ran on **2026-10-08 at 18:09:40 UTC** and returned **1,070 coins**. Their creation times run
from **2026-10-07 19:37 to 2026-10-08 18:08 UTC**, a window of about 22.5 hours. Graduations arrive at
about 47 per hour.

**Why this window.** The API stops at `offset=1000` with `limit` at most 70. Offset 1001 and above
returns `[]`. No other query reaches older graduates without survivor bias:

- `order=ASC` returns the first graduates of 2024.
- Sorting by `market_cap` or `ath_market_cap` ranks coins by their outcome.
- Time filters (`created_timestamp_lt`, `createdTs`, `before`, `endTimestamp`, `cursor`, ...) are ignored.
- The only valid sort keys are `created_timestamp`, `market_cap`, `ath_market_cap`, `reply_count`,
  `last_reply` and `last_trade_timestamp`.

**What it is NOT:**

- Not many regimes. This is one day.
- Not coins that graduated after the census.
- Not coins created before 2026-10-07 19:37, even if they traded during the window.
- Possibly not coins that pump.fun hid or removed. We cannot detect those.

**Default universe.** `harness.in_default_universe` keeps **770 coins**: train 448, validation 150,
test 172. It uses only facts known at launch and the data source:

| Excluded | Coins | Why |
|---|---:|---|
| **Mayhem-mode coins** (opt-in at launch) | 218 | They "complete" with about 0.1-10 SOL instead of 85 SOL. Their pools are 100-10,000x shallower (the median pool k is 0.16 % of a normal graduate's), and after "graduation" their prices sit at $1-$50 market caps. A $20 trade on them is fiction: modelling them as normal pools produced fake +22,000 % trades. |
| **Non-SOL quote** (USDC, WLD, `pumpCm…` and others) | 86 | Jupiter would need a second hop through a pool we do not model. |
| **5m bars** | 1 (BABYBATON, non-SOL quote) | The early history exists only as 5m bars. Bar size would leak future activity, because only coins that later trade a lot get truncated 1m data. |

## 2. Files

| File | Content |
|---|---|
| `LAB/census.json` | Every raw census field, plus `_fetched_ts` per row and the census start and finish times. Outcome-only fields stay here: ath, market caps, reserves, complete, mayhem_state, reply_count, last_trade. |
| `LAB/pools.json` | GeckoTerminal `pool_created_at` (the graduation time, to the second) and reserves at fetch time. |
| `LAB/sol_usd.json` | SOL/USD, 1m, from the Orca SOL/USDC pool via GeckoTerminal. Covers 2026-10-07 08:57 onward. |
| `LAB/raw/<mint>_1m.json`, `_5m.json`, `_gt1m.json` | Raw API responses. |
| `LAB/coins/<mint>.json` | The coin files (format below). |
| `LAB/calibration.json`, `LAB/k_verification.json` | Live Jupiter Ultra checks of the cost model (section 4). |
| `LAB/pumpfun_fees_snapshot.html` | The fee page as fetched. |
| `LAB/baseline_results.json`, `LAB/stats.json` | Outputs of `baseline.py` and `stats.py`. |

The coin files follow the nightcrawler backtest format, with extra keys:

```
{"coin": symbol, "name", "mint", "pool": pump_swap_pool, "supply": 1e9, "created_ts", "graduated_ts",
 "graduated_src": "geckoterminal", "launch": {creation-time flags}, "cost": {k inputs, costs.py only},
 "candles": [[ts, o, h, l, c, vol_usd], ...],
 "coverage": {"first_ts", "last_trade_ts", "end_ts", "first_1m_ts", "complete_from_creation", "source",
              "n_candles", "n_synthetic", "fetched_ts", "gt_splice_scale", ...}}
```

**Candles.** `swap-api.pump.fun/v1/coins/{mint}/candles?interval=1m&limit=1000` returns the latest
1,000 or fewer minutes that had trades. It covers both bonding-curve and PumpSwap trades.

- Valid intervals: 1s, 15s, 30s, 1m, 5m, 15m, 30m, 1h, 4h, 6h, 12h, 24h.
- No pagination parameter works: `startTime`, `from`, `to`, `endTime`, `offset`, `page`, `createdTs`.
- Units, checked minute by minute against GeckoTerminal on 3 pools:
  - volume = **USD** (median ratio 1.000-1.002);
  - price = **USD per whole token** (within 0.1-0.8 %; pump.fun's SOL/USD conversion differs slightly);
  - market cap = price x total_supply / 10^6 = price x 1e9 for every coin.
- 1,054 coins are covered fully by the 1m response.
- 15 busy coins traded for more than 1,000 minutes, so their 1m response did not reach back to creation.
  For them, true 1m bars come from GeckoTerminal (the bonding-curve "pool", then the PumpSwap pool),
  rescaled to swap-api's USD basis. The scale factors are 0.998-1.010.
- Result: **1,069 of 1,070 coins have complete history from creation** (`source` = `1m` or `gt1m+1m`).

**Gaps.** Minutes without trades are flat bars with zero volume at the previous close. After the last
trade, each series continues flat until the minute it was fetched, because an AMM price does not move
without trades. **86 % of all 786,810 bars are synthetic.** Most coins die quickly.

## 3. Descriptive statistics (default universe; outcome data, never strategy inputs)

| Statistic | Value |
|---|---|
| Graduation delay after creation | **65 % graduate within 5 s of creation** (creator buys out the curve in the launch transaction); p75 2.5 min, p90 13 min, p99 2.4 h |
| Died within 1 h of graduation (no minute with ≥ $100 volume afterwards) | **68.8 %** (489 of 711 observable) |
| Died within 6 h | **79.2 %** (415 of 524 observable) |
| Peak high after the graduation bar / graduation-bar close | p10 1.07x, p25 1.19x, **median 1.48x**, p75 2.19x, p90 3.47x, p99 13.9x; ≥ 2x: 28.4 %, ≥ 10x: 1.4 %, < 1.1x: 14.8 % |
| Minutes from graduation to that peak | p25 2.4, **median 6.8**, p75 19, p90 80 |
| Price at census / graduation-bar close | p25 0.006x, **median 0.036x**, p90 0.55x, p99 2.4x; 81 % below 0.1x |
| At the floor market cap at census | **74.9 %** (see below) |
| USD volume in the first hour | p10 $17k, median $65k, p90 $364k |
| Hours observed after graduation | p10 2.0, median 12.4, p90 20.9 (the newest coins are right-censored) |

**The floor.** A dumped graduate settles at about **17.6 SOL market cap (about $1.9k)**. That happens
when the whole supply is back in the pool: x = k / 1e9 tokens. Most launches look like this: the
creator buys out the curve, the price spikes for a few minutes, and the whole supply is sold back.

## 4. Costs (`costs.py`)

Each side of a trade pays these costs. Sources were checked on 2026-10-08.

- **Pool fee**, from https://pump.fun/docs/fees (last updated 20 May 2026):
  - bonding curve: 1.25 %;
  - PumpSwap canonical pools: tiered by market cap in SOL (price x 1e9), from 1.25 % below 420 SOL down
    to 0.30 % above 98,240 SOL;
  - USDC-paired coins use the USDC table. `fee_bps(mcap_usd, phase, sol_usd, quote)` implements both tables.
- **Jupiter Ultra platform fee**: 10 bps. Every Ultra order quote reported `feeBps: 10`.
- **Price impact**, from constant-product math with k = **K_GRAD = 84.990 SOL x 206.9M tokens ≈ 1.7585e10**.
  These are the migrated reserves of every SOL-paired graduate. The quote reserve at price p (in SOL) is
  sqrt(k·p). The bonding curve uses virtual reserves of 30 SOL x 1.073B tokens.
  - K_GRAD is leak-free, because it needs no future reserve snapshot. It is also slightly conservative,
    because k only grows.
  - **Do not use GeckoTerminal `reserve_in_usd` for k.** Live quote impact shows that it understates k
    on dead pools by about 4x (table below).
- **MEV/slippage buffer**: `mev_bps` = 20 bps per side.
- **Network**: 5,000 lamports plus priority `priority_sol` = 0.0002 SOL per swap, at that minute's SOL
  price, which is about $0.022 per swap. Token-account rent is refunded, so it counts as 0.
- **Stress knobs**: `fee_mult`, `impact_mult`, `CostModel.stressed(f)`.
- Non-SOL quotes pay the top tier plus a 100 bps extra hop.

**Round trip** (`round_trip_cost_pct`), all costs included, SOL = $107.7:

| Market cap | Pool fee/side | $5 | $20 | $50 |
|---:|---:|---:|---:|---:|
| $2k (floor) | 1.25 % | 4.45 % | 5.22 % | 7.83 % |
| $41k (graduation) | 1.25 % | 4.07 % | **3.73 %** | 4.24 % |
| $100k | 1.20 % | 3.93 % | 3.48 % | 3.76 % |
| $1M | 1.00 % | 3.49 % | 2.89 % | 2.89 % |
| $10M | 0.35 % | 2.19 % | 1.55 % | 1.46 % |

**Calibration against live Jupiter Ultra.** These are `GET lite-api.jup.ag/ultra/v1/order` quotes,
nothing signed: buy about $20 of SOL into the token, then sell the quoted `outAmount` back to SOL.

- The model is compared without the MEV buffer and without network fees, because quotes include neither.
- The model uses K_GRAD.
- Result: **within 0.07 percentage points on all 6 coins**, from a $2k to an $800M market cap. No
  adjustment was needed.

| Coin | Market cap | Route (buy / sell) | Measured round trip | Model round trip |
|---|---:|---|---:|---:|
| SHARKCAT | $6.7k | Pump.fun Amm / Pump.fun Amm | 3.726 % | 3.748 % |
| SCraft | $15k | Pump.fun Amm / Pump.fun Amm | 3.326 % | 3.391 % |
| Holdoween | $1.9k | Pump.fun Amm / OKX router | 4.635 % | 4.658 % |
| Meta | $1.9M | Pump.fun Amm / OKX router | 2.044 % | 2.054 % |
| RLUSD | $12M | Pump.fun Amm / Pump.fun Amm | 0.823 % | 0.824 % |
| XRPN | $802M | Pump.fun Amm / Pump.fun Amm | 0.800 % | 0.802 % |

**k check** (`costs.py verify_k`). Quote 0.01 SOL and 1 SOL buys. The ratio of the two effective prices
gives the quote reserve x, and k = x²/p.

- 5 dead coins: k = **1.01-1.04 x K_GRAD**. GeckoTerminal's reserves imply 0.22-0.37x.
- The busy SharkTank: 1.44x, because of LP fees.

So K_GRAD is right and conservative. Real fills also pay priority fees and MEV. That is why the model
adds the 20 bps buffer and the network fee, on top of the measured round trips.

## 5. Harness (`harness.py`)

```python
class Strategy:                       # one instance PER COIN (factory = the class)
    name: str; horizon_s: float | None   # optional: stop calling me when flat and now - graduated_ts > horizon_s
    def on_coin_start(self, meta): ...   # meta: mint, symbol, name, created_ts, supply, launch{...}
    def on_candle(self, i, view, position) -> Buy | Sell | SetExits | None
```

**`view`: bars 0..i only, at the close of bar i.**

- Bar data: `view.ts/o/h/l/c/v/dur`, as read-only numpy slices of length i+1.
- `view.bar(k)` returns one bar (`k=-1` is bar i). It raises beyond i.
- Time: `view.now` is the close of bar i. `view.age_s` is also available.
- Graduation: `view.graduated`. `view.graduated_ts` is **None until it has happened**.
- Also available: `view.mcap(k)`, `view.supply`, `view.sol_usd`, `view.meta`.
- Not exposed: coverage, end of data, last trade time, reserves, k, census outcome fields.
  `coverage.source` and `complete_from_creation` would leak future activity.

**`position`** is a read-only snapshot with these fields: `entry_ts`, `entry_price` (fill mid),
`cost_basis`, `size_usd`, `tokens`, `peak` (max high since entry, bars up to i), `bars_held`, `exits`,
`partial_taken`, `unrealized_pct`.

**Actions:**

- `Buy(usd=None, exits=Exits(...), priority=0, tag="")`
- `Sell(fraction=1.0)`
- `SetExits(Exits(...))`
- `None` = hold.

`Exits` takes:

- absolute prices: `stop_price`, `take_profit_price`, `trail_pct`, `time_stop_ts`;
- relative values, resolved at the fill against the entry mid: `stop_pct`, `take_profit_pct`, `max_hold_s`;
- `tp_fraction`: sell this fraction once at the take-profit;
- `trail_after_tp`: arm the trail only after the partial take-profit.

### Rules

**Entries and fills**

- A decision taken at the close of bar i fills at the **open of bar i+1** (`entry_delay_bars`).
  Costs come from costs.py. Pre-graduation prices use the curve.
- There are **no entries before graduation**. The universe is "coins that graduated", so buying on the
  curve would use that future fact.
- `Sell` also fills at the next open.

**Exits** are managed inside each bar, pessimistically:

- A gap through the stop, the time stop or the trail fills at the open.
- The stop beats the take-profit inside the same bar.
- The trail uses only earlier peaks.
- After a partial take-profit, the trail is checked in the same bar against the previous peak.
- The fill bar itself can stop the trade out.

**Wick fills** (`SimConfig.wick_fill`):

- `"half"` (default): stops and trails fill halfway between the level and the bar low. A take-profit
  fills at its level only if the bar closed at or above it; otherwise it fills halfway between the level
  and the top of the bar body.
- `"touch"`: fills exactly at the level (optimistic).
- `"worst"`: stops fill at the low; take-profits fill at the top of the body.
- Report all three for any candidate. A memecoin wick is often a single transaction.

### Two run modes

- **`run_per_coin(Strat, coins)`**: each coin independent, $20 per entry. Gives clean per-trade
  statistics.
- **`run_portfolio(Strat, coins)`**: all coins merged chronologically.
  - $100 start; size = `nightcrawler.risk.size_position_usd(equity, 0.20, 5, 25)`, capped by free cash.
    Below $25 of equity this skips every entry.
  - At most 3 concurrent positions; pending buys count.
  - One position per coin; 30 min per-coin cooldown; compounding; equity marked at mid every minute.
  - When buy requests collide, they are served by `priority`, then creation time, then mint.

### Metrics (`result.metrics()`)

`trades, coins_traded, win_rate_pct, avg_ret_pct, median_ret_pct, profit_factor, expectancy_usd,
exp_ci95_pct, total_return_pct, max_drawdown_pct, best_coin_share_pct, top3_share_pct,
pnl_without_best_coin_usd, pnl_without_top3_usd, exit_reasons, costs_usd, by_hour_utc`.

`exp_ci95_pct` is a **coin-level bootstrap** 95 % confidence interval of the mean per-trade return.
Coins are resampled, not trades.

### Safety guards

- **`audit_lookahead(Strat, coins)`** reruns every coin truncated at random bars. Every decision and fill
  up to the cut must be identical. It catches any peek at the future, even reaching into private
  attributes. **Run it on every candidate.**
- **Splits** (`splits.json`) divide all 1,070 census coins by `created_ts`:
  - oldest 60 % TRAIN (642): created 10-07 19:37 to 10-08 08:06;
  - next 20 % VALIDATION (214): 08:08 to 13:35;
  - newest 20 % TEST (214): 13:35 to 18:08.
- `load_split("test")`, `load_coins(split="test")` and any run containing a TEST coin raise
  `TestSplitLocked` unless `LAB_ALLOW_TEST=1`. Only the judge sets it. `load_coins()` with no split
  silently leaves the test coins out.

**Example strategy:**

```python
import sys; sys.path.insert(0, "research/lab")
from harness import Strategy, Buy, Exits, load_coins, run_per_coin, run_portfolio, audit_lookahead

class GradBreakout(Strategy):
    name = "grad_breakout"
    horizon_s = 2 * 3600                       # only the first 2 h after graduation
    def on_coin_start(self, meta):
        self.done = False
    def on_candle(self, i, view, position):
        if self.done or position is not None or not view.graduated or i < 5:
            return None
        if view.c[-1] > view.h[-6:-1].max() and view.v[-1] > 2 * view.v[-6:-1].mean():
            self.done = True
            return Buy(exits=Exits(stop_pct=0.2, take_profit_pct=0.6, tp_fraction=0.5,
                                   trail_pct=0.25, trail_after_tp=True, max_hold_s=3600))
        return None

coins = load_coins(split="train")
print(run_per_coin(GradBreakout, coins).summary())
print(run_portfolio(GradBreakout, coins).summary())
assert audit_lookahead(GradBreakout, coins[:50]) == []
```

## 6. Baselines (`baseline.py`), default universe

Per-coin results use $20 per trade. Portfolio results start from $100.

| Split | Strategy | Trades (coins) | Win % | Avg % | Median % | Profit factor | Avg 95 % CI | Portfolio return | Max drawdown |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| train | nightcrawler dip-rebound | 61 (15) | 31.1 | -7.2 | -21.4 | 0.56 | [-14.8, -0.3] | -64.0 % | 69.0 % |
| train | buy at graduation, hold 60 min | 448 (448) | 15.2 | -64.2 | -96.0 | 0.18 | [-71.8, -55.5] | -82.3 % | 82.6 % |
| train | random entry, nightcrawler exits | 448 (448) | 9.6 | -5.8 | -5.1 | 0.21 | [-6.9, -4.7] | -46.6 % | 48.6 % |
| validation | nightcrawler dip-rebound | 16 (4) | 12.5 | -15.4 | -21.5 | 0.20 | [-22.6, -11.6] | -41.1 % | 68.1 % |
| validation | buy at graduation, hold 60 min | 150 (150) | 16.7 | -60.9 | -96.7 | 0.21 | [-76.0, -41.7] | -82.8 % | 92.9 % |
| validation | random entry, nightcrawler exits | 146 (146) | 4.8 | -8.2 | -5.2 | 0.07 | [-10.0, -6.4] | -29.5 % | 31.8 % |

Sensitivity of the per-coin average return (base / zero costs / costs x2 / touch wicks / worst wicks):

- nightcrawler on train: -7.2 / -4.0 / -10.4 / -4.0 / -10.5
- nightcrawler on validation: -15.4 / -12.4 / -18.3 / -11.7 / -19.0

So the bot's default strategy **has no gross edge even at zero cost**. Buying graduation loses a median
96 % within an hour, which is the rug pattern. All three baselines pass `audit_lookahead`.

## 7. What strategy researchers must know

1. **Gates every candidate must pass:**
   - positive net expectancy on TRAIN **and** VALIDATION, with the coin-bootstrap CI above 0;
   - still positive without the best coin and without the top 3 coins;
   - survives `costs x2` and `wick_fill="worst"`;
   - a portfolio max drawdown you could live with;
   - `audit_lookahead == []`.

   Only then ask the judge for TEST, and only once per candidate.
2. **Only OHLCV + launch flags.** There are no trades, holders, buy/sell counts or creator history.
   - A creator-reputation feature built from other coins is legitimate only in `run_portfolio`, which is
     chronological, and only if it is computed causally.
   - **Never share state across Strategy instances** (class attributes) in `run_per_coin`. Coins run one
     after another there, so shared state leaks the future.
3. **The sample is small and comes from one day.** About 450 train coins, but a selective strategy
   trades 15-60 of them. Count your parameter tries and prefer few, round parameters. Validation is
   about 5 hours of launches.
4. **Two kinds of coins.** Two thirds graduate instantly in a creator-bundled launch, and their
   graduation bar already contains a 10-1,000x move. Bar 0 is a mixed curve and pool bar.
5. **Prices floor at about 17.6 SOL market cap**, about $1.9k. Most coins end there within an hour.
   Flat synthetic bars mean no trading. Buying a dead coin just pays about 5 % in costs.
6. **The newest coins are right-censored**: they were observed for only 0-5 hours. An open position is
   closed at the last bar with `end_of_data`. Check how many exits are `end_of_data`.
7. **Never use `cost.*`, `coverage.*` or census outcome fields** (ath, market caps, reserves, complete,
   mayhem_state, reply_count, last_trade_timestamp) as inputs.
   - The `launch` flags are believed to be fixed at creation, because pump.fun metadata is immutable on IPFS.
   - `mayhem` is the launch opt-in. The current `mayhem_state` is an outcome field.
8. **Hour buckets**: `metrics()["by_hour_utc"]` groups trades by the UTC hour of entry. With 22 hours of
   data, each hour appears once or twice, so do not fit to the hour.

## 8. How to run

```bash
cd /home/user/Claude
python research/lab/fetch.py all          # census -> pools -> sol -> candles -> gt1m -> build (resumable)
python research/lab/harness.py splits     # (re)write splits.json from the census
python research/lab/costs.py              # round-trip table
python research/lab/costs.py calibrate 6  # live Ultra quotes vs model -> LAB/calibration.json
python research/lab/costs.py verify_k 6   # live k from quote impact -> LAB/k_verification.json
python research/lab/stats.py              # descriptive stats (section 3)
python research/lab/baseline.py --json LAB/baseline_results.json
python -m pytest -q research/lab/tests    # 50 offline tests (lookahead, costs, intrabar, portfolio, split guard)
```

`fetch.py all` reuses what is on disk. To take a **new** census snapshot, point `LAB_DATA` at a new
directory, so the old snapshot and its splits stay reproducible.

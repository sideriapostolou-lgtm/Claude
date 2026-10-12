# Speed desk: build spec (for ChatGPT/Codex; written by Claude 2026-10-12)

Goal: copy the method of the public Polymarket bot "dangerously-skip-permissions" as closely as our venue allows,
**in practice mode first**. Read `AGENTS.md` first: real money only on the owner's exact word with amounts named.

## 1. What the original bot does (measured, research/lab8/skip/READING.md)

From its newest 2,000 public fills (2026-10-12, 3.2 hours, 38 windows), with `pull.py`, `an.py` and
`deep.py` in research/lab8/skip and the scratchpad:

- **Markets:** only Bitcoin Up/Down 5-minute windows on Polymarket international. It trades every window.
- **Holding:** buys only, never sells, holds to settlement.
- **Two-sided:** it buys **both Up and Down** in 37 of 38 windows, nearly balanced (median imbalance 13 %).
- **Prices:** anywhere from 0.10 to 0.90, mostly 0.30-0.70. It buys whichever side is cheap at that moment.
- **Timing:** fills spread over the first ~4 minutes of each window, almost none in the last minute.
- **Fill type:** **67 % taker** (it takes resting asks) and **33 % maker** (its resting bids get hit).
- **Size:** about 3,500 shares (~$1,800) per window, median fill 24 shares.
- **Pricing:** at 1-minute resolution, the price it paid equals fair value on average (median fair minus price
  -0.006). So its edge is **speed**: it reacts to Bitcoin ticks before the book reprices, faster than a minute.
- **Result:** +$1,067 before fees over 38 windows. 25 won, 13 lost; best +$202, worst -$193. About a third came
  from matched pairs under $1 (+$344) and two-thirds from direction (+$723).

## 2. Our venue's limits (do not work around them)

- The owner's account is **Polymarket US**. It lists Bitcoin Up/Down **15-minute** and **1-hour** windows (series
  `btc-updown-15m`, `btc-updown-1h`; slugs `cpc-btc-updown-15m-YYYY-MM-DD-HHMMz`, where the time is the window
  start). The 5-minute series exists but has never had a window. Polymarket international is not for US
  accounts. Never route around that.
- US settlement: CF Benchmarks BRTI, the 60-second average before the window end (research/lab8/us_venue.md).
  Up wins when the end value is at or above the start value; check the market text for ties.
- Fees: taker 0.0695 x contracts x p x (1-p). Read the maker fee or rebate from the market's `feeCoefficient` and
  the venue docs. Do not assume a rebate.
- US books are thin (one hourly ladder traded $165 in its life). Expect much less than the original's ~$3k/day.

## 2b. Kalshi: the better venue for this (checked 2026-10-12 18:45 UTC)

- Kalshi lists **Bitcoin Up/Down 15-minute** windows (series `KXBTC15M`, e.g. `KXBTC15M-26OCT121445-45`).
  It has no 5-minute series. The books are much deeper than Polymarket US: one live window showed **6,074 contracts
  at the best ask** and **166,913 contracts traded in 24 hours**. That is the closest match to the original's
  markets that a US account can trade.
- Public market data needs no key: REST `https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXBTC15M`
  and `/markets/{ticker}/orderbook`; prices come as `yes_ask_dollars` / `no_ask_dollars` and sizes as `*_size_fp`.
  Kalshi's WebSocket, balances and all orders need the owner's Kalshi API key: an **Ed25519** key in variables
  `KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY` (PKCS#8 PEM), set on the Railway `bot` service on 2026-10-12 and verified
  with a read-only balance call ($25.00 cash). Never print, log or commit them. Sign each request with headers
  `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (ms) and `KALSHI-ACCESS-SIGNATURE` = base64 Ed25519 signature of
  timestamp + METHOD + path (path includes `/trade-api/v2`, no query string). Washington blocks Kalshi sports and
  politics for this account; Crypto stays open, so `KXBTC15M` is tradable.
- Read the window's rules for its settlement source and tie rule, and Kalshi's fee schedule for taker and maker
  fees. Do not assume either.
- Build the speed desk with a **venue adapter**: Polymarket US (15m/1h) and Kalshi (KXBTC15M), same rules and
  practice fills. Practice on Kalshi can start now from public REST books (poll at most 2 per second). Real money on
  Kalshi needs the key and the owner's amounts.

## 3. Architecture

New module `src/nightcrawler/speeddesk.py`, started by `engine.py` as its own thread with an asyncio loop. It has
its own state file `/data/speeddesk/state.json`, its own receipts, and an `/api/page` panel. It never shares caps
or stops with `polydesk.py`.

1. **Bitcoin ticks:** a WebSocket to Coinbase Advanced Trade `wss://advanced-trade-ws.coinbase.com`, `ticker` or
   `market_trades` for BTC-USD (public, no key). Keep the last price, a rolling 60-minute set of 1-second returns
   for sigma, and a staleness clock. Warm up for a full hour and require at least 3,000 observed adjacent
   one-second returns in the trailing hour; never invent zero returns across gaps. Stale over 3 s means no new
   orders, and resting orders are cancelled.
2. **Books:** the Polymarket US markets WebSocket (`polymarket_us` SDK `client.ws.markets()`; it needs the key
   variables already in Railway), subscribed to the current and next 15m and 1h windows. Fall back to REST
   `/v1/markets/{slug}/book` at most once per second if the stream drops.
3. **Orders:** the SDK `orders` resource. Use IOC limit orders for takes, and GTC limit orders for resting bids
   (cancel and replace on reprice). In practice mode **no order is ever sent**; fills are simulated (section 5).
4. **Fair value:** `P(Up) = Phi( ln(S/S0) / (sigma * sqrt(t_left)) )`. S is the live Bitcoin price, S0 the
   window's start price (BRTI proxy: Coinbase price at the start second; log both), sigma per sqrt(second) from
   the rolling window, t_left in seconds. Down = 1 - Up.

## 4. Strategy rules (all numbers are settings with these defaults)

Per window, from its start until `CUTOFF_S` (60 s) before its end:
- **Take:** when a side's best ask <= fair - `TAKE_EDGE` (0.02) - taker fee, buy up to `CLIP` shares (25) at that ask
  (IOC). This is the 67 % taker part, the speed edge.
- **Rest:** keep a bid on each side at fair - `MAKE_EDGE` (0.03), size `CLIP`. Reprice when fair moves by more than
  0.01, or cancel. This is the 33 % maker part.
- **Pair discipline:** never let avg(Up paid) + avg(Down paid) + fees go above `PAIR_CAP` (0.99) on the matched
  shares. A buy that would break it is skipped.
- **Imbalance cap:** |Up shares - Down shares| <= `MAX_IMBALANCE` (25 %) of the window's total. The heavy side
  stops buying until the light side catches up.
  **Owner-approved practice start (2026-10-12):** an empty window may place one starter order of at most `CLIP`
  shares, still within all dollar budgets. While the starter is pending or the holdings exceed the imbalance
  cap, only buys on the lighter side that reduce the gap are allowed; they cannot overshoot it. Normal 25 %
  enforcement resumes once balanced enough. Unfilled opposite-side orders never count as already balanced
  holdings. This exception permits practice to start from zero; it authorizes no real orders.
- **Window budget:** at most `WINDOW_USD` ($20 in practice; real only by the owner's number) spent per window, and
  at most `OPEN_USD` across open windows. `OPEN_USD` defaults conservatively to **$20 in practice**. Fees and
  outstanding order reservations count toward both budgets.
- **Hold to settlement**, as the original does. No selling.
- **Day stop:** if the day's settled P&L <= -`DAY_STOP_USD` ($10), no new buys until 00:00 UTC.

## 5. Practice mode (the first deliverable): honest fills only

- **Taker fills:** fill at the ask at the moment of decision, for at most the ask size shown, then add latency:
  re-check the book no earlier than `LATENCY_MS` (250) later, and fill only if the ask is still there at that price.
  Use the first qualifying observation, never a later favorable rebound: a REST request must start after that
  delay, or a WebSocket update must have a post-delay exchange timestamp. Report actual decision-to-fill latency;
  REST may take longer than 250 ms. Cancel if fresh evidence does not arrive within a further 3 seconds.
- **Maker fills:** a resting bid fills only when the venue's trade stream prints at or below our price, after the
  size resting ahead of us at that price (queue position from the book when the bid was placed) has traded. Never
  fill a bid just because the price touched it.
- Settle each window from the venue's settlement endpoint. Book P&L per window, split into the matched-pair
  (locked) part and the directional part, fees included.
- Polymarket US fee implementation: the standard non-combo schedule at
  <https://docs.polymarket.us/fees> (checked 2026-10-12) gives taker coefficient `0.0695` and maker coefficient
  `-0.0125`, rounded per execution to cents using half-even (banker's) rounding. The maker rebate is used only
  for a market matching that documented standard schedule; an unknown schedule disables maker simulation.
  These are Polymarket US fees, not a fee assumption for another venue.
- Kalshi uses <https://kalshi.com/docs/kalshi-fee-schedule.pdf> (effective July 7, 2026) with verified series
  `fee_type` and `fee_multiplier`. Current `KXBTC15M` is quadratic with multiplier 1: taker coefficient 0.07,
  maker fee zero. Its cost-plus-fee rounds upward to $0.0001. Unknown event fee overrides disable that window;
  public trade prints require complete pagination, valid venue quantities and explicit aggressor direction.

## 6. Logging and page

- Log one line per decision (`speeddesk_take`, `speeddesk_rest`, `speeddesk_fill`, `speeddesk_window`) with: window,
  side, price, size, fair, edge, latency ms, Bitcoin price and staleness.
- Page panel: windows traded today, fills, matched-pair profit vs directional profit, win/loss windows, worst
  window, and a clear **PRACTICE** label.
- Trial days and the day stop use **UTC midnight**. The desk writes daily reports to its independent state and
  receipts, including observed seconds, whether a day is partial, fill rates, and average latency. Fill rates
  count unique orders with a fill divided by orders placed, not contracts; maker fill latency includes resting
  time. Bitcoin feed latency is reported separately.
- `/api/page` exposes the current report under `money.speeddesk.today` and the latest 31 completed calendar
  days under `money.speeddesk.reports`; the visible page labels all figures **PRACTICE**. Missing or stale data
  is identified, never invented as zero. None of these results adds to account cash, real profit or town goals.

## 7. Tests (required before any push)

1. Fair value math, including its edge cases.
2. Pair-cap and imbalance enforcement.
3. Cutoff and staleness: no orders.
4. Practice fills: no fill without a printed trade, queue position, and latency re-check.
5. Settlement booking, split into the locked and directional parts.
6. Day stop.
7. Practice mode never calls an order method: the test fails if the SDK order client is touched.

Use the repo's fake clocks and fakes (`tests/fakes.py`). Tests and mypy must pass, and ruff on changed files.

## 8. Rollout

1. Build it in practice, deploy (pushes to `src/**` auto-deploy), and run it **at least 3 days**.
2. Report per day: windows, fills, locked vs directional P&L, worst window, fill rates, and average latency.
3. Real money only if practice is positive after fees over 3+ days **and** the owner names the amounts
   (`WINDOW_USD`, `OPEN_USD`, `DAY_STOP_USD`). Start small.
   The implementation accepts only `SPEEDDESK_MODE=paper`; there is no automatic promotion or real-order path.
4. Log every session in `docs/WORKLOG.md`. Claude reviews when back.

Honest expectation: the original makes money on deep international 5-minute books with speed and about
$1,800 per window. Ours runs on thin 15m and 1h US books, so the practice run decides whether it earns anything.
Report what happens, good or bad.

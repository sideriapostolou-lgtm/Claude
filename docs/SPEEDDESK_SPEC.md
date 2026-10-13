# Speed desk: build spec (for ChatGPT/Codex; written by Claude 2026-10-12)

Goal: copy the method of the public Polymarket bot "dangerously-skip-permissions" as closely as our venue allows,
**in practice mode first**. Read `AGENTS.md` first: real money only on the owner's exact word with amounts named.

**Owner update, 2026-10-12:** section 9 authorizes a separate, tightly capped Kalshi live companion before the
three-day practice trial finishes. The original trial continues, and the Polymarket US leg remains practice.
Deployment itself must leave the new companion in paper mode; the owner activates its two live switches.

## 1. What the original bot does (measured, research/lab8/skip/READING.md)

From its newest 2,000 public fills (2026-10-12, 3.2 hours, 38 windows), with `pull.py`, `an.py` and
`deep.py` in research/lab8/skip and the scratchpad:

- **Markets in this sample:** only Bitcoin Up/Down 5-minute windows on Polymarket international. It trades every sampled window. The later full-history audit also found Ethereum five-minute trades; do not generalize this recent sample to its whole history.
- **Holding:** buys only, never sells, holds to settlement.
- **Two-sided:** it buys **both Up and Down** in 37 of 38 windows, nearly balanced (median imbalance 13 %).
- **Prices:** anywhere from 0.10 to 0.90, mostly 0.30-0.70. It buys whichever side is cheap at that moment.
- **Timing:** fills spread over the first ~4 minutes of each window, almost none in the last minute.
- **Fill type:** **67 % taker** (it takes resting asks) and **33 % maker** (its resting bids get hit).
- **Size:** about 3,500 shares (~$1,800) per window, median fill 24 shares.
- **Pricing:** at 1-minute resolution, the price it paid equals the scout's fair-value proxy on average
  (median fair minus price -0.006). Faster reactions are a hypothesis, not proof of its private signal or edge.
  The prospective watcher in section 10 tests specified patterns without treating this coarse sample as validation.
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
   for sigma, and a staleness clock. Warm up for a full hour and require at least 1,500 observed adjacent
   one-second returns in the trailing hour (3,000 until 2026-10-12, never reached in quiet hours); never invent zero returns across gaps. Stale over 3 s means no new
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
- **Per venue (owner, 2026-10-12):** each current and completed daily report includes `venues.kalshi` and
  `venues.polymarket_us`, with traded/settled windows, fills, locked-pair and directional results after fees,
  worst window, fill rates and latency. Per-venue fill rates follow orders placed that UTC day; executions
  count on the fill day and profits on the settlement day. A late first fill revises its placement-day rate
  with a `speeddesk_daily_correction` receipt. Existing combined reports remain available.
  Shared app uptime and Coinbase feed latency are explicitly labeled shared. Fresh-data coverage is measured
  separately for each venue (fresh Bitcoin and both books of at least one active window); maker coverage also
  needs that window's verified trade stream. Coverage includes volatility warm-up and does not prove profit.
  Coverage begins when instrumentation starts, never from inferred historical uptime. Older combined-only
  days with activity have unknown venue metrics; an empty warm-up day can retain exact zero counts. Splitting
  reports does not split the shared speed-desk practice budgets or loss stop.

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
2. Report per day **per venue**: windows, fills, locked vs directional P&L, worst window, fill rates, and average
   latency, with partial-day/data-coverage limitations visible.
3. Real money only if practice is positive after fees over 3+ days **and** the owner names the amounts
   (`WINDOW_USD`, `OPEN_USD`, `DAY_STOP_USD`). Start small.
   The implementation accepts only `SPEEDDESK_MODE=paper`; there is no automatic promotion or real-order path.
4. Log every session in `docs/WORKLOG.md`. Claude reviews when back.

Honest expectation: the original makes money on deep international 5-minute books with speed and about
$1,800 per window. Ours runs on thin 15m and 1h US books, so the practice run decides whether it earns anything.
Report what happens, good or bad.

## 9. Kalshi live companion: owner's explicit decision, 2026-10-12

The owner superseded the earlier pause and the three-day prerequisite for **Kalshi only**. Build and test the
live-capable companion, ship it in paper mode, then give the owner the activation settings. Do not change
`polydesk.py`, the existing real Polymarket desk or the Polymarket US practice leg. Continue the original
practice trial and keep an additional honest practice twin of the live companion's decisions for comparison.

### Owner's hard limits

| Setting | Default and maximum | Includes |
| --- | ---: | --- |
| `SPEEDDESK_KALSHI_WINDOW_USD` | $2 | Actual buys, fees, unfilled reservations and uncertain requests in one KXBTC15M window |
| `SPEEDDESK_KALSHI_OPEN_USD` | $4 | All unsettled windows and pending orders |
| `SPEEDDESK_KALSHI_DAY_STOP_USD` | $3 | UTC-day settled drawdown plus money still at risk; resets at 00:00 UTC without dropping carried exposure |
| `SPEEDDESK_KALSHI_TOTAL_STOP_USD` | $5 | Settled drawdown since the last authorized resume plus money still at risk |
| `SPEEDDESK_KALSHI_CUTOFF_S` | 180 seconds | End real buying after the first 12 minutes; configured cutoff may never be below 60 seconds |

Fees and resting orders count at their worst permitted cost. Kalshi cash is another limit, never permission
to exceed a strategy cap. A total stop persists through restarts and returns the companion to paper. A new
nonempty `SPEEDDESK_KALSHI_RESUME_TOKEN` acknowledges a fresh $5 stop budget; it must preserve lifetime P&L,
fills, fees, existing exposure and the current day's stop. Store only a fingerprint, never the token value.
Reusing an old/pre-halt token or changing ordinary settings cannot silently clear the halt or corrupt state.

A reconciliation stop (the book's `integrity_error`: venue data contradicted the bot's accounting) also returns
the companion to paper and persists. The panel's `integrity_error` (shown on the page too) and a
`speeddesk_live_integrity` receipt (once per stop and after each restart) name the check that tripped.
`SPEEDDESK_KALSHI_INTEGRITY_RESET_TOKEN` is the owner's one-time reset (owner, 2026-10-13: "Yes, reset it"). A
value is spent the moment the companion first sees it; its fingerprint is kept with the resume fingerprints,
which the previous release also keeps, so no restart or rollback can let it approve a second stop. It approves
only the stop present at that startup (set while no stop exists, it approves nothing). The approval is saved
with the books, so it survives a restart, and is withdrawn for good if a different check trips. It clears the
approved stop only right after a complete, fresh, matching reconcile with no order open, uncertain or reserved,
every bot window settled, and no Bitcoin 15-minute position or resting order left on the Kalshi account (the
owner's included). The panel's `integrity_reset` shows `armed` or what it is waiting for, and
`speeddesk_live_integrity_reset` receipts record each step. A rollback drops the approval, never the spent value.

These are risk controls for a paid experiment, not a profit promise or an absolute guarantee against an
exchange failure. We copy the observed rules, not the original bot's speed, 5-minute venue, liquidity or size.

### Activation and stop

New buys require all of the following in the current process:

1. `SPEEDDESK_KALSHI_MODE=live` (default `paper`).
2. `SPEEDDESK_KALSHI_LIVE_CONFIRM=yes`.
3. Both `KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY` are present.
4. An authenticated balance read has succeeded this run.

Valid window rules, fresh data, conservative fee allowances, reconciled account state and remaining budget are
also required. Any authentication failure leaves this companion in paper with a visible reason; it must not
stop the existing polydesk process. Record the correct account type before activation; do not set `direct` merely to bypass missing fee evidence.
The owner confirmed on 2026-10-12 that this account was opened **directly on Kalshi**.
The factual setting is `SPEEDDESK_KALSHI_ACCOUNT_TYPE=direct`; the portable default remains `unknown`.
No account-type or live variable was changed in this session. The owner records the account type and sets
the activation variables on Railway **after** the paper deployment is verified. The kill switch is `SPEEDDESK_KALSHI_MODE=paper`.

Fresh paper operation never constructs the authenticated client. Returning from live to paper still needs
authenticated, cancel/read-only recovery for prior live orders; this recovery cannot submit a new order.
Already filled exposure remains real until it settles, and the page must say so even with new buying off.

### Verified API and accounting

- Use the current official V2 event-order endpoint, `POST /trade-api/v2/portfolio/events/orders`, rather than
  guessing legacy request fields. Prices are fixed-point YES dollars; `bid` buys YES and `ask` is the economic
  equivalent of buying NO at `1 - yes_price`. Count and price use the documented fixed-point strings.
- Kalshi nets opposite outcomes. Preserve actual gross fill lots to attribute locked versus directional
  results, but reconcile their signed difference against actual net positions. Never fabricate a gross
  account position or double-count the cash released by a matched pair. Unattributed positions/orders in a
  target market block it; the bot must not offset or cancel the owner's activity.
- Use a fixed bot prefix and a unique `client_order_id` on every request. Persist the intent and full
  reservation before sending. Never blindly retry a create after timeout/5xx; reconcile by client ID. An
  empty or delayed list is not proof that no order exists. Unknown requests retain their budget.
- IOC takes use the edge after rounded fees. Resting orders are post-only, use venue expiry, and are repriced
  when fair value moves more than 1c. Self-trade prevention is `taker_at_cross`, so the incoming bot order is
  cancelled rather than an owner's resting order. Mutation routing follows the documented exchange shard;
  account reads must cover all relevant shards and complete pagination.
- Live accounting uses actual fill `fee_cost`, not simulated fee estimates. The July 7, 2026 schedule and
  current fee-rounding guide distinguish Direct balance precision ($0.0001) from non-direct ($0.01), with
  six-decimal trade fees and a per-order rounding accumulator. Fractional executions can occur even for a
  whole-contract request. Subaccount 0 exists for both account types and does **not** prove Direct membership.
  Until the owner confirms the account type, reserve using the conservative $0.01 grid and show that reason.
  At the smallest permitted partial fill this costs at least $1 per contract, so no binary price can clear
  a positive edge: live switches alone will not produce orders while precision remains unverified. Direct
  precision must be explicitly established before enabling the cheaper bound. The nonsecret
  `SPEEDDESK_KALSHI_ACCOUNT_TYPE` records the owner's factual confirmation: `direct` for a personal direct
  Kalshi account, `fcm` for a broker/FCM account, `unknown` by default. It never grants live permission. Reservations remain conservative
  about partial fills and do not spend an expected rounding rebate.
- KXBTC15M rules use the 60-second average of CF Benchmarks BRTI at each boundary; YES wins ties. Read and
  validate current rules/fees for every eligible window. Unknown terms disable that window.
- Cancel only bot-owned resting orders at startup, cutoff, stale Bitcoin (>3 s), shutdown, repeated errors
  and mode changes. A cancel request alone does not release exposure: reconcile terminal status and all
  actual fills. Prevent overlapping processes from independently spending the same persisted budget.

Official sources checked for this implementation:

- <https://docs.kalshi.com/api-reference/orders/create-order-v2>
- <https://docs.kalshi.com/openapi.yaml>
- <https://docs.kalshi.com/getting_started/fee_rounding>
- <https://docs.kalshi.com/getting_started/subaccounts>
- <https://kalshi.com/docs/kalshi-fee-schedule.pdf>

### Evidence before activation

Fake-only tests must cover all four switches, permanent Polymarket US isolation, paper/no-create behavior,
fees and partial fills within every cap, UTC rollover and durable total stops, cancellation triggers,
unknown-create reconciliation, startup recovery, process overlap, actual-fill accounting, net settlement
attribution, and throwaway-key signing of the exact documented message. Run the full tests, source mypy and
changed-file Ruff. Independent reviewers check the safety invariants before merging.

Logs use `speeddesk_live_order`, `_fill`, `_cancel`, `_reject` and `_status`, without credentials. The page
separates **REAL MONEY (Kalshi)** from practice and keeps Kalshi cash/results separate from Polymarket cash
and the existing town figures. Verify the exact deployed commit and a paper `speeddesk_live_status` before
giving the owner the activation settings. After the owner activates, inspect the first windows and record
orders, fills, fees, locked/directional P&L, gaps and anomalies in `docs/WORKLOG.md`.

### 9.1 Raised caps and locked-in pairs (owner, 2026-10-13)

The owner chose "2.5x": $5 per window, $10 open, $6 UTC daily loss stop, $10 total loss stop, and asked that
pairs be "completely locked in" and that the bot "knows when to sell".

- **Money at risk** is what can still be lost: per unsettled window, its cost (fees included) minus $1 for
  each complete up+down pair (Kalshi nets the pair to $1 at once), plus pending non-lock reservations. The
  open budget and both loss stops use it. Gross cost is still reported as `open_cost_usd`.
- **New buys stop** `SPEEDDESK_KALSHI_LOCK_S` (240) seconds before the close, never later than the cutoff.
- **Lock:** from then until 20 s before the close, a window holding more of one side buys the other side at
  the ask (immediate-or-cancel) for exactly the unpaired whole contracts, at up to
  `SPEEDDESK_KALSHI_LOCK_MAX_PRICE` (0.97). Buying the other side is the same as selling the extra side back:
  every contract ends in a $1 pair and the window's result is known. Above that price the window is already
  decided and is left as it is.
- At any price below $1 including fees a lock lowers the worst-case loss, so window budget, pair cap, edge
  and the loss stops do not block it; a pending lock holds cash but is not added to money at risk. So the $5
  per window bounds new buys, and a window's gross spend can exceed it only by a lock (its possible loss
  cannot). During a money stop the panel says new buys are stopped and that locks still complete pairs.
- Saved state leaves out the lock fields while they hold defaults, so a rollback to the release before
  locks can still read it (a lock pending at that moment would not be readable by the old release). It never
  runs with live switches off, after a failure or integrity error, in a window the owner traded, or before
  every order in the window is reconciled. Locks are kept out of the speed measurements and the twin.

## 10. Public source-bot watcher and faster market data (owner, 2026-10-12)

The owner wants real Kalshi trading as the eventual result of learning the source bot, within the owner's
caps (2026-10-12: $2/window, $4 open, $3 UTC daily stop, $5 total stop; raised 2026-10-13, see 9.1). Observation and statistical fitting do not themselves
authorize an automatic strategy change. The existing live companion remains separately gated; the watcher
never places an order, trades on Polymarket international, changes money settings or moves the Railway region.

### Public observations

`skipwatch.py` runs in its own engine thread. Its public-only adapter observes wallet
`0xc53375ff94e96100f2b30a4b5775db35218d69a9`, current and next international Bitcoin five-minute Up/Down
windows, CLOB market books/trade prints and Coinbase BTC-USD ticks. The current Data API is `/v2/trades`:
explicit `taker_only=false`, complete cursor pagination, stable row deduplication and a rolling overlap.
Polls default to 2.5 seconds; rate limits extend the interval. Both maker and taker fills must be included.
Window start comes from `eventStartTime`, not the market creation date. Keep each discovered market's rules
and settlement evidence. These international markets use the specified Chainlink reference; Kalshi uses
BRTI. Coinbase opening/fair probability is a labeled research proxy, not either settlement oracle.

Every observation records source time where available and local receipt time. Price/size/time matches to
public prints are inferred, ambiguous or unmatched; they do not establish private decision milliseconds,
submitted order size, maker/taker identity or cancellations. Unknowns remain unknown. CLOB has no documented
market-channel sequence counter, so observed reconnect gaps do not prove that every silent loss is detectable.
The wallet API's integer timestamp is **block inclusion time**, not execution time. A public probe on
October 12 found same-transaction prints 1.333–3.674 seconds earlier. Preserve both clocks; do not demand
that their timestamps agree within one second or treat the block clock as a trading decision clock.
The journal retains reconstructible prices/sizes/timestamps; opaque delta book hashes and validated redundant
fields may be omitted from its normalized representation. Source data cannot enter a feature before receipt.

Records live under `/data/skipwatch/`: UTC-dated, hash-chained JSONL batches and losslessly compressed sealed
segments. A UTC day can contain multiple segments rather than one huge file. Batched fsync bounds unflushed
data to about one second; restarts and interrupted tails are recorded as gaps. Checkpoint witnesses reject
missing durable records. Default storage cap is 4096 MiB, with a 128 MiB free-space reserve for the other desks.
Reaching either bound stops observation visibly; it never silently deletes evidence. These limits do not
guarantee three days of storage during an unusually busy feed. Actual storage/coverage must be monitored.
Per-window summaries and late revisions use `skipwatch_window_summary`; current health uses `skipwatch_status`.

### Fixed research protocol and later rulebook

`research/lab8/skip/PLAN.md` is registered before prospective analysis. Its packaged implementation is
`skipwatch_fit.py`; `research/lab8/skip/fit.py` is the offline command. The original persisted start time defines
the proposed splits: hours 0–36 fit, 36–48 validation, 48–72 untouched test. A fixed 24-candidate grid uses fair/quote
edge, time remaining, observed side balance, displayed depth and Bitcoin movement. One causal opportunity
per side/second predicts the next complete public timestamp second, with covered negative examples and a
30-second reporting grace. Compare precision, recall and F1 against never-buy, always-buy and fixed-prevalence
baselines; report sizing error, coverage, quiet periods and mismatches. Inadequate evidence is a valid result.

**Timing amendment, before any model result:** automatic fitting and rule verdicts are paused with
`awaiting_verified_execution_time`. Features preceding a block timestamp can follow the actual trade,
so the original public-second target cannot establish execution triggers. Observation and the original
clock continue. A separately preregistered, verified execution-time labeling and coverage protocol is
required before fitting can resume; complementary-outcome and aggregated public prints need explicit
treatment. Passing 48 or 72 hours alone does not release this block. Explicit offline block-publication
association research remains noncausal and cannot supply a trading rule or net-profit claim.

The research-only sigma uses at least 300 actual adjacent one-second returns; opening uses an actual tick
already known at window start and at most three seconds old. Missing observations never become zero returns.
The financial desk's warm-up bar is 1,500 returns since 2026-10-12: at 3,000 it never warmed up in quiet hours
(2,086-2,979 seen all evening). Its status shows the actual sample count.
Once a valid timing protocol exists, freeze the selected rule and its protocol/input digests before
evaluating any held-out data, and retain that immutable result. Slow research runs in a separate process,
so fitting does not hold the trading interpreter. Artifacts and the resulting rulebook live under
`/data/skipwatch/research/`; repository `RULES.md` stays pending until verified findings are copied back.

Fill prediction is not net profit, and copying five-minute patterns to fifteen-minute Kalshi markets is an
untested transfer. Public fills do not establish our queue, fees, rebates or achievable fills. No fitter output
is imported into an execution rule automatically. Report the evidence and its gaps before implementing a
funded strategy change. Never claim the exact private algorithm or a profitable clone from a short sample.

### Kalshi speed, latency and the US five-minute alert

`SPEEDDESK_KALSHI_WS_ENABLED=true` enables a narrow market-only Ed25519 signer for
`wss://external-api-ws.kalshi.com/trade-api/ws/v2`. The owner explicitly authorized use of the existing Railway
key for this read-only feed, even when the companion is paper. Sign timestamp + `GET` + `/trade-api/ws/v2`;
subscribe only to public-market `orderbook_delta` and `trade`, with explicit YES-price normalization.
Validate snapshot/delta sequencing by subscription ID. Gaps, stale or backlogged data invalidate maker queues;
REST remains capped at two book requests per second. Source timestamp or conservative request-start evidence,
not receipt time invented as exchange time, is required for honest delayed practice fills.

Public `GET /exchange/status` probes report successful HTTP round-trip median/p95 separately from timeout/error
counts, WebSocket age and order latency. One region's timings do not establish that a move will help; no
Railway region or stored data is moved. Account reconciliation still contributes to full execution latency.

The public US probe checks the five-minute series and validates an actual market's BTC/UP_DOWN/5m/BRTI terms
and start/end before logging `skipwatch_us_5m_listing`. Its first verified observation stays on the page.
The series alone is not a listing; failed requests are unknown. This bounded latest-event check does not
prove completeness across long outages, and discovering a market never adds it to a trading universe.
All watcher data is shown outside cash, profit and town totals. It describes observed public activity, not
money earned by this account.

Official references checked: <https://data-api.polymarket.com/v2/openapi.json>,
<https://docs.polymarket.com/migrate/data-api-v1-to-v2.md>,
<https://docs.polymarket.com/developers/CLOB/websocket/market-channel>,
<https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-channels>,
<https://docs.kalshi.com/websockets/orderbook-updates>, and
<https://docs.kalshi.com/websockets/public-trades>. Current provider schemas take precedence over old examples.


## 11. Expanded replication mission (latest owner instruction, 2026-10-12)

This supersedes earlier informal promises to copy an exact private algorithm. The objective is a measured
approximation on a venue the owner may use. Public observations cannot guarantee recovery of private
cancellations, intentions, hidden liquidity or reaction time. Five-minute international Polymarket and
15-minute Kalshi differ in settlement reference, fees, market duration, available size and execution.
The source bot's apparent speed advantage and alleged $100 beginning are hypotheses to test.

### History and funding

`research/lab8/skip/history.py` collects official public activity/trades with a fixed cutoff, complete cursor
pagination, rate-limit backoff and raw-page digests. `history_chain.py` independently checks public Polygon
receipts. Funding, holdings value, fees, rebates, realized/unrealized position result and economic result
remain separate. `HISTORY.md` states coverage and unknowns, including daily balance/drawdown limitations.
The observed wallet was created on July 17 and initially funded with $4,000; this is not evidence of the
owner's complete bankroll or a $100 phase. Never fabricate a small-bankroll playbook from that claim.

### New observations and evaluation target

Record genuine Coinbase, Kraken and Gemini BTC/USD trades, source timestamps, local receipt clocks,
identifiers and feed gaps. Keep independent feature clocks for new feeds without resetting the original
watcher origin. Local reachability is not proof of Railway reachability. Never route around a restricted
exchange or label apparent source-clock age as proven predictive leadership. The financial desk keeps its
existing Coinbase input and volatility rules; research does not silently choose a faster money feed.

The owner's target is **at least 70% of held-out source fills**, correct side, within **5 seconds**, and
price within **2 cents**. Freeze protocol, candidates and predictions before evaluation; fit on earlier
days and test on a held-out day. Match predictions one-to-one, report precision, false positives and simple
baselines, and retain all observed source fills in the denominator with unknown-label bounds. Public-event
proxy scoring is separate from qualified causal execution scoring. Block inclusion is not execution time;
unknown clock/linkage evidence blocks the strict gate. A new feature/protocol epoch cannot borrow earlier
unrecorded features or manufacture a completed three-day trial. See `PLAN.md` and `RULES.md` for the pinned
protocol, current status and remaining timing qualification. No fitter output activates an execution rule.

### Timing and daily comparison

Record median/p95 and sample/missing/error counts for public Kalshi HTTP round trip, age of the exact
Bitcoin input at each decision, local receipt-to-decision time, and real decision-to-order acknowledgment.
Clock uncertainty is explicit. Paper has no real acknowledgment samples. Acknowledgment is not a fill, and
input age does not prove that the tick caused the decision. One Railway region's observations cannot
establish that moving would help; do not move the service or stored data.

The daily comparison keeps source observations, Kalshi real, its practice twin, and the original two
practice venues separate. Use window-end UTC cohorts for both-sides rate, actual taker share, final share
imbalance, quantity-weighted matched-pair cost including fees, fills/window, settled locked/directional
result and worst settled window. Fully observed eligible zero-fill windows remain in the activity
denominator. Historical missing coverage stays unknown; pending settlements do not become zero profit.
Targets: both sides in at least 90% of windows, taker share about two-thirds, median imbalance at most 15%,
and average pair cost below $1 including fees. These are comparisons, never instructions to force trades.

A higher-cap proposal requires **three consecutive complete UTC days, each positive after fees**, and the
qualified held-out rule-match target. Unknown evidence fails the gate. Only the owner changes caps.
Ship the companion in paper, verify the exact deployment and existing polydesk, then provide activation
settings. After the owner activates, record actual orders, fills, fees and settlement results. Future
three-day observations and first live fills cannot be claimed during the implementation session.

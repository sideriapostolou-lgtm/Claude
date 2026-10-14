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
   window's start price, sigma per sqrt(second) from the rolling window, t_left in seconds. Down = 1 - Up. On
   Kalshi, S0 is the market's own strike (`floor_strike`), which equals the previous window's settlement, a
   60-second BRTI average before the open (all 2,843 consecutive pairs in 2026-09-13..10-13). A Coinbase print in
   the start second missed it by $19.61 on average and up to $100 (41 windows, 2026-10-12/13), about 5 cents of
   fair value at the open, so a Kalshi window never opens from Coinbase and waits for the strike. Other venues
   keep the Coinbase start-second proxy; the opening receipt logs both.

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
| `SPEEDDESK_KALSHI_WINDOW_USD` | $10 | Actual buys, fees, unfilled reservations and uncertain requests in one KXBTC15M window |
| `SPEEDDESK_KALSHI_OPEN_USD` | $20 | All unsettled windows and pending orders |
| `SPEEDDESK_KALSHI_DAY_STOP_USD` | $6 | UTC-day settled drawdown plus money still at risk; resets at 00:00 UTC without dropping carried exposure |
| `SPEEDDESK_KALSHI_TOTAL_STOP_USD` | $10 | Settled drawdown since the last authorized resume plus money still at risk |

History: $2/$4/$3/$5 at launch (2026-10-12); $5/$10/$6/$10 (owner, 2026-10-13, "2.5x"); window and open raised to
$10/$20 (owner, 2026-10-13 15:15 UTC, "ten now double tmr if it works"), both stops unchanged; the code ceilings
allow one step to $20/$40 and a $12 day stop "when it's winning" (owner, 16:00 UTC); since the owner's "Max $50,000 a window build the ladder" (2026-10-13 ~18:40 UTC) the settings above are the earned-growth ladder's rung 0 and the bot takes that step itself (9.2). The stops count
money still at risk, so they also bound each window: an unpaired position can never put more at risk than is
left under the day and total stops (a complete up+down pair risks nothing).
| `SPEEDDESK_KALSHI_CLIP` | 5 contracts | Most contracts per real order, so the first buy in a window is at most 5 (owner, 2026-10-13, after two 10-contract first buys were run over), at every ladder rung (9.2: "Keep 5 at every rung"); balancing and lock orders follow it |
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
`SPEEDDESK_KALSHI_DAY_RESET_TOKEN` is the owner's one-time fresh daily budget (owner, 2026-10-13: "U can reset it
go ahead", "Approve everything"). The first time the companion sees a new value, today's loss counts again from
that moment's result, until 00:00 UTC; the next day starts from zero as always. The $6 daily cap, the $10 lifetime
stop and every other limit are unchanged, so the lifetime stop still bounds the total. The value is spent on first
sight with its own fingerprint kind (a resume or integrity value never matches it), the reset point is saved with
the books, and a `speeddesk_live_day_reset` receipt records it. A rollback ignores the saved point and returns to
the plain daily stop.

Other coins (owner, 2026-10-13: "scale ... to other markets but let's perfect it first"): `SPEEDDESK_COINS`
(any of eth, sol, xrp, doge; empty by default) runs the same practice rules on Kalshi's KXETH15M, KXSOL15M,
KXXRP15M and KXDOGE15M windows (src/nightcrawler/speeddesk_coins.py). Practice only: no account client, key or
order path. Each coin has its own ledger, budget and report under `speeddesk/coins/<coin>`, all on one thread
and event loop separate from the Bitcoin desk's, reading public Kalshi REST data slowly (books every 2 s,
trades every 4 s, no websocket) and one public Coinbase trade feed. Because these coins print far less often
on Coinbase, the opening is Kalshi's own strike (the 60-second index average, as on Bitcoin), volatility is the realized
variance of consecutive prints per elapsed second over the trailing hour (at least 120 pairs), and the last
print may be 15 s old (30 s for DOGE). Real money on a coin needs its practice record, one account controller
shared by every coin (one cash view, one set of caps, one read budget) and the owner's numbers.

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
  validate current rules/fees for every eligible window. Unknown terms disable that window. Fair value accounts
  for the average (loss plan item 4, 2026-10-13): the mean of sixty one-second values varies like the index 39.5 s
  before the close, so with 60 s or more left the live desk and the Kalshi practice windows use the time left
  minus 39.5 s (`fair_up(..., settles_on_average=True)`); the last minute is unchanged and no buy is made then.
  Polymarket US windows are unchanged.
- Cancel only bot-owned resting orders at startup, cutoff, stale Bitcoin (>3 s), shutdown, repeated errors
  and mode changes, and a resting bid priced from an old fair value: fresh fair more than 1c from the fair it
  was priced at, or the bid above fresh fair minus 2c. The last runs on every step and between account reads,
  whether or not account data are fresh (loss plan bug 2: at 9:08:39 AM PT on 2026-10-13 a bid stayed up for
  20.7 s while fair rose about 7c, because the reprice waited for a fresh account read). A cancel never adds risk;
  new bids still wait for a fresh, matching reconcile. A cancel request alone does not release exposure: reconcile terminal status and all
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

- **Money at risk** is what can still be lost: per unsettled window, the largest value, over every
  combination of its pending orders filling or not, of its cost (fees included, pending orders at their full
  reserved cost) minus $1 for each complete up+down pair (Kalshi nets the pair to $1 at once). The loss is
  convex in each order's filled amount, so these extremes bound every partial fill. The open budget and both
  loss stops use it, and each new order is checked against what it adds to its window's worst case: all of its
  cost for a first buy, nothing for a balancing bid that only completes pairs. Until 2026-10-13 every pending
  non-lock reservation was added in full, so a balancing bid counted as new risk and the stops cut it to 3
  contracts instead of 10 (loss plan bug 1); a money stop also cancelled balancing bids. A money stop (day or
  total) now leaves a resting bid that only completes pairs: on its window's light side, and no worse on its own
  than no pending order at all (judged against no orders, not the other pending one: a pair of bids on both
  sides of a balanced window each passed against the other though together they added risk; caps review,
  2026-10-13). It still stops new orders, and a reconciliation stop, stale feed, old price or the cutoff still
  cancel it. The window budget still counts every dollar spent and reserved. Gross cost is still reported as
  `open_cost_usd`. With the earned-growth ladder (9.2) the open and daily checks use the window's rung and the
  lifetime check the configured $10 stop, as before.
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

### 9.2 Earned-growth ladder (owner, 2026-10-13 ~18:40 UTC)

After Claude proposed this rule the owner wrote: "Max $50,000 a window build the ladder". Code: `src/nightcrawler/speeddesk_live_ladder.py`; the
risk book asks it for each window's limits (`LiveRiskBook.limits_for`, `limits_now`).

- **Rungs.** Rung r >= 0: window = base + $5r, where base is `SPEEDDESK_KALSHI_WINDOW_USD` (Railway: $10, the
  owner's floor); open = 2 x window; day stop = 0.6 x window; the contract cap (so the first buy) stays the
  configured `SPEEDDESK_KALSHI_CLIP` (5) at every rung (owner's choice, 2026-10-13 ~20:15 UTC: "Keep 5 at every
  rung"). Rung 0 is exactly the configured limits ($10/$20/$6, 5 contracts) and no rung goes below a configured
  value. The $10 lifetime stop never scales: real money still switches off when total P&L since launch (with money
  at risk) reaches -$10. Ceilings: $50,000 a window, or `SPEEDDESK_KALSHI_LADDER_MAX_WINDOW_USD` when lower, and
  the risk book's own clamp first: the top is the last rung `LiveLimits` leaves unchanged (the ladder asks the
  clamp; it never copies its numbers). **This release keeps the code ceilings at $20/$40/$12 and 25 contracts**
  (config.py `hi` and `speeddesk_live_model.HARD_*`, `HARD_CLIP`), so from $10 the ladder has two rungs:
  $15/$30/$9, then $20/$40/$12, both with 5 contracts. Raising the money ceilings toward $50,000 is a separate
  change that needs the owner's explicit go-ahead; the contract cap no longer grows, so `HARD_CLIP` never sets the
  top (tests check that the top rung would then be exactly $50,000/$100,000/$30,000 with 5 contracts, whatever
  `HARD_CLIP` is).
- **Promotion**, one rung, when all five hold since the current rung began: (1) at least 96 settled windows traded
  at this rung; (2) gain G (the settled P&L of this rung's windows) less money still at risk >= 2 sigma sqrt(n),
  sigma = max(realized SD of per-window P&L at this rung, 0.105 x window); (3) house money: the room above the
  lifetime stop, total P&L + $10 less money at risk (and less a resume anchor above zero), >= 3 x 0.55 x the next
  rung's window; (4) no stop now and none in the last 24 h: a reconciliation error, the total stop, or the daily
  stop (its flag, today's settled loss within $1 of it, or even a one-contract buy refused by the day or total
  stop; a refusal that only trims a bigger order is not a stop); (5) available cash (cash less pending reservations
  and unconfirmed spending) >= the next rung's open budget, from a balance read within the last minute. A promotion
  also waits while total P&L less money at risk is at or below the demotion line (`giveback`).
- **A promotion is provisional until its boundary.** When it is decided, the rung in force keeps its limits, its
  counters and its own demotion line; any stop cancels it. At the first look at or after the boundary (the desk looks
  at once then, not only once a second, before any order in the new window) every condition and the demotion line are
  checked again with money still at risk counted as lost; it applies (`confirm`) only if all still hold and no
  window from the boundary on has traded yet (`window_started`), otherwise it is cancelled and the limits stay as
  they are (the rung's counters are untouched, and the next look may decide it again for the following window).
- **Demotion**, one rung and never below 0: total P&L <= its peak at this rung - 0.6 x the rung's window (settled
  P&L, as the rule says). At rung 0 a give-back changes nothing. While a promotion waits, the line is the rung in
  force's, and crossing it demotes from that rung (dropping the promotion).
- **Never mid-window.** A decision takes effect at the next window boundary (the close of the window under way):
  every window's limits are fixed by its start, so a window that has begun keeps the limits it started with, and
  windows starting from the boundary use the new rung. Only one change waits at a time. The counters (n, G, the
  peak) restart when a change applies (a confirmed promotion, a demotion, a lowered maximum) and cover only windows
  that start at or after the rung began: a window of the earlier rung that settles later moves the starting P&L and
  the peak with it, so neither its gain nor its loss counts at the new rung.
- **Every check uses the window's rung:** window budget, open budget, day stop, contract cap (starter, balancing
  and lock orders), the size search in `_decide` and `_lock`, the status report and the practice twin (its window,
  open, day stop and cap follow the rung). The total stop, cash bound, pair cap, imbalance, cutoff and lock rules are
  unchanged. Note: the unchanged lifetime stop still caps money at risk at once below $10 (less any loss since
  launch), so above rung 1 it binds before the day stop; a bigger rung adds paired volume, not unpaired risk.
- **Saved and restored.** The ladder is a top-level `ladder` key in the saved state (version 2: rung, the rung
  windows before the boundary keep, the boundary, whether a promotion still waits for its re-check, the start of the
  counted windows, start time and P&L, peak, last stop, the latest 192 per-window results, the last change and the
  configured limits it was earned on). On restart the counters (count, starting P&L, peak) are rebuilt from the saved
  books (saved in the same write), so saved numbers can never inflate them, and the ladder looks at the books once
  before a resume or day-reset token can clear a saved stop. The previous release ignores the key and nothing inside
  the books or intents changed, so a rollback runs at the configured limits; it then saves without the ladder and
  the next upgrade starts at rung 0. An unreadable ladder, a schedule this code could not have written (two rungs
  at one boundary, a change beyond the next boundary), changed configured limits (`rebased`),
  `SPEEDDESK_KALSHI_LADDER=false` (it also restarts at rung 0) or a lower maximum (`clamped`, counters restart) only
  ever lowers the limits.
- **Shown and logged.** The panel and the `speeddesk_live_status` line carry `ladder`: rung in force, limits,
  promotion progress (n/96, G and G less money at risk vs needed, sigma, room vs needed, cash vs needed, last stop,
  what blocks it), the demotion line of the rung in force (peak, give-back vs limit), any waiting change and
  whether it still waits for its re-check (`recheck_pending`); `caps` are the rung's limits now (plus `clip`).
  `/api/page` exposes it as `kalshi_live.ladder` (pagestate whitelist). Each decision logs one
  `speeddesk_live_ladder` line with every number (`action` promote, confirm, demote or cancel), and each start
  logs one.
- **Owner decision taken (2026-10-13 ~20:15 UTC): "Keep 5 at every rung".** The first ladder draft grew the
  contract cap with the window (floor(window / 2): 7 contracts at $15, 10 at $20), which would have brought back
  the 10-contract first buy the owner's 16:20 UTC rule stopped after two were run over. Asked to choose, the owner
  kept the configured cap: every rung's contract cap, so every first buy, balancing and lock order, is at most
  `SPEEDDESK_KALSHI_CLIP` (5). A bigger rung adds window, open budget and day stop, not a bigger first buy.

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

Live loop speed (2026-10-13; owner: "Move to Virginia!!"; the service already ran in Virginia, so the gain is
inside the bot). The companion steps on each accepted Bitcoin tick or Kalshi book change, at most every 20 ms
and at least every 250 ms, instead of a fixed 250 ms sleep. The private client counts reads and writes in
separate rolling one-second budgets, 10 reads and 5 writes per second (half of Kalshi's Basic-tier 20 and 10),
so an order never waits behind the account reads that came just before it. Before this change every call waited
200 ms after the previous one, so a reconcile (six reads) blocked decisions for over a second. A reconcile
reads settlements only while a traded window has ended and is not yet settled. One durable write before the
send holds the intent, its full reservation and its practice-twin order id (since step 2 below, a journal row
rather than the whole state); the reply's facts follow in the next full save.

Small saves (2026-10-13). Every save rewrote every order the companion had ever made, twice (the risk book and
the intent journal): 206 ms per save on Railway by 13:45 UTC, about 87 us more per stored order, several saves a
second on the shared event loop. A window an hour past its close, settled and with nothing open, now moves once
into a write-once ledger chunk (`kalshi_live_archive/<n>`, committed in the same transaction as the state that
lists it); saves hold only the other windows. A restart merges the chunks under the saved state before the
book is rebuilt, so every restore check sees the full books; a missing or inconsistent chunk refuses to start.
An archived window with new activity is saved in full again and archived anew once finished (later copies win).
The release before this cannot read the archive and fails closed (companion halted, no orders): roll forward.
`state.json` stays the display copy the money page rebuilds and checks the whole real book from: it holds
every window (archived ones from memory, newer saved copies win), at most every 10 s and at shutdown, without
an fsync (the ledger is the durable record; the page treats data older than 60 s as stale). The status line
splits each save into build_ms, ledger_ms and mirror_ms.
Money math over open windows only (2026-10-13; latency review). The archive keeps saves small, but a restart
merges every archived window back into memory, and the risk book summed money at risk over every order and window
ever made, five times per status and once per open order in each cancel pass: a step took 0.6 ms on a fresh book
and 57 ms with a week of finished history (build machine), and a complete reconcile checked each listed order's id
against every order ever made (1.7 s with three days). The book now keeps an index (each window's orders in
creation order, the windows that can still lose money, the owner of each Kalshi order id), updated by the methods
that add orders, settle windows and record order ids, and rebuilt whenever its dicts changed any other way; the
sums over it are exactly the full sums (the randomized book test checks them after every event). Unfinished
orders come from the open windows too, with the full scan kept for an integrity error, the one state in which a
settled window can hold a reservation again. Money at risk is worked out once per status and the money stop once
per cancel pass. With a week of history a step now takes 0.6 ms and a complete reconcile with every old order
listed 135 ms of local work (linear in the orders Kalshi lists).
Only saves that must survive a host or power failure sync the ledger's write-ahead log at commit: the one
before an order's first network byte (orders and lock buys; since step 2 the pre-send journal row), startup,
shutdown, and any that records an owner's one-time action. The others (about 57 ms of fsync each on Railway on 2026-10-13, twice a second in reconcile)
commit with SQLite synchronous=NORMAL: a process crash loses nothing, a host failure can lose account facts the
next reconcile reads again, and the next synced commit makes every earlier commit durable.

Bounded account reads (2026-10-13; loss plan bug 3, speed plan step 1). Every reconcile read the whole order
history twice and every fill since the desk first started (about 0.5 MB/s on the live connection). Between
complete reads, the two order reads and the fill read now pass Kalshi's `min_ts` = the earlier of the oldest
unfinished, uncertain or reserved order's decision time and one window (900 s) ago, minus 60 s. Every order that
can still change the books was created after its decision, and its fills after that, so it is inside the bound
whether `min_ts` filters orders on creation or on last update (the docs do not say which); so is every order and
fill of a window open now. The complete history (orders unfiltered, fills since start) is still read at startup,
every 60 s, on the first read that starts after any window opens (an owner's bid placed before the window opened
is normally seen before the bot's first order there; a read already under way at the open can let one bot order
through first, and the complete read about a second later then marks the window as the owner's), and on every read
while an owner's integrity reset waits, the only reads
that may clear it. An untracked bot order or a late fill stamped before the bound is caught by the next complete
read (at most 60 s). Positions and settlements are unchanged. The status line's `reconcile` block reports, since
the previous line: complete and recent reconcile times (`full_ms`, `recent_ms`), each read's time, the total
pages, rows and bytes read, failures, and how often each consistency check failed (`check_<name>`:
`position_mismatch`, `order_list_behind_fills`, `fills_behind_order_list`, `order_found_after_fills`,
`unattributed_fill_beside_unresolved_order`, `settlement_row_missing`, `reconcile_slow` over 3 s); `last` is the
most recent reconcile with its reads.

Measurement (2026-10-13; speed plan step 0; logging only, no order changes). Accepted order and cancel records
carry `venue`: Kalshi's reply time `ts_ms` (the client already validated it), the local send and reply times and
the clock offset they imply (Kalshi minus local, uncertain by half the round trip). Cancel records also carry
`reduced_by` and `timing` (decision to Kalshi's reply, and the request alone). The status line adds `phases`
(median, p90 and maximum ms of each part of `step()`: observe, cancel_unsafe, startup or reconcile, lock, decide,
heartbeat, and the whole step), `loop` (`event_loop_lag`: the oversleep of a 10 ms timer, and the cancel
timings) and `clock` (Coinbase Exchange `/time` once a minute while real money is on, and Kalshi from every reply;
each source's shortest round trip since the previous line, or the last one with `fresh: false`). A failed time
probe is only counted. Accepted orders' `stages` keep their three fields for the existing log parsers.

Bitcoin tape (2026-10-13; speed plan step 3). The one-second tape rebuilt both of its dictionaries on every
accepted trade (1.6 to 1.7 ms on Railway, twice per trade: practice desk and live twin), and the live snapshot's
volatility cache was keyed on every accepted tick, so each trade recomputed the hour of returns. The tape now
updates in place and drops seconds older than an hour and a second oldest first (0.0007 ms a trade against
0.37 ms on the build machine), and counts accepted ticks (`revision`). The cache key holds the number of accepted
ticks in completed seconds instead: a trade in the current second cannot change volatility, a late one stamped
in a completed second does and recomputes it; a query more than a second before the newest tick is never
cached. Volatility is therefore computed about once a second (0.7 ms) instead of on every trade. When the newest
tick is stamped in a later second than the local clock (the bounded skew below), the key is that second and the
ticks before it, so it is still cached (latency review: it recomputed on every snapshot refresh, 7.2 times a second
at -240 ms skew). Results are identical: `tests/test_speeddesk_tape.py` replays 3,000 recorded Coinbase trades six times, with late revisions
of the current and the just-completed second, against the previous code.

Bitcoin feed (2026-10-13; speed plan step 4). Coinbase Exchange's `matches` channel
(`wss://ws-feed.exchange.coinbase.com`, with `heartbeat`) delivers each trade on its own, 50 to 61 ms (median)
before Advanced Trade's batches. Two Exchange connections are the primary source and Advanced Trade
(`market_trades`) stays as the backup; the three share one trade-id space (no price mismatch in 4,280 shared
trades), so each trade id is delivered once, by whichever connection brings it first (the last 20,000 ids are
remembered). Exchange `last_match` and Advanced Trade `snapshot` events, both replays of past trades on every
(re)connect, are not ticks. Bitcoin data reads `connected` while any connection is up; the status also lists each
connection (`coinbase_feeds`), and every gate that cancels on a feed gap is unchanged. Freshness allows a bounded
clock skew: a trade stamped up to 250 ms after the local clock (`FUTURE_SKEW_S`) is accepted by the practice
desk, the live companion, the practice model's staleness check and the timing reports (which count it as 0 ms
old), because the Exchange feed has no batching delay to hide the clocks' difference (the 2026-10-13 recording
ran 18 ms behind Coinbase; on one container 91% of Exchange ticks would have been dropped). Every staleness limit
is unchanged: with no trade for 3 s the live companion still cancels its bids ("Bitcoin feed stale"), and a stamp
further ahead than 250 ms is refused, before its trade id is marked as delivered, so a later copy of the same trade
from another connection that is inside the bound still arrives (latency review: with the local clock about 0.3 s
behind Coinbase every Exchange copy was refused and used up the id the Advanced Trade copy needed, while the status
read "connected"); the refusals are counted per connection in the status (`coinbase_future_stamped`, at most every
10 s). The live companion's stale-feed check counts from the earlier of the newest tick's stamp and its local
receipt, so a tick stamped ahead no longer keeps the feed "fresh" up to 250 ms past 3 s of silence. The step-0
`clock` report compares the clocks.

Hosts and connections (2026-10-13; speed plan step 8). The signed client sends to `https://external-api.kalshi.com`,
the dedicated Trade API host Kalshi recommends for API traders (`api.elections.kalshi.com` stays supported;
signatures cover the path only, so they are unchanged). The speed desk's public pollers (Kalshi REST books,
trades and metadata in `speeddesk_kalshi`, the Polymarket US gateway in `speeddesk_feeds`, and the Coinbase time
probe) keep one HTTP session per worker thread instead of a new TCP and TLS connection per request (from the
build container, through its proxy: about 480 ms per new connection against 46 ms kept alive); the public
poller keeps its host. Not changed: `exchange_index` stays -1 (automatic routing; an explicit shard needs that
shard's collateral, the shard-aware cash task), and `polydesk`, `weatherwatch_markets` and `skipwatch_alerts` keep
their own HTTP (a separate real-money desk, a separate desk with streamed, locked reads, and a probe that measures
a fresh connection's round trip on purpose).

Pre-send journal (2026-10-13; speed plan step 2). The write before an order's first network byte was a full
save of the whole state, synced (1.65 ms median on the build machine with 12 orders, 24.7 KB, against 0.54 ms for
the row that replaces it, each with one `fdatasync`; on Railway the fsync itself, about 57 ms, stays in both). It
is now one row, `kalshi_live_journal`, committed with synchronous=FULL: for each order sent since the last full
save, its complete reservation, its intent, its window's terms when new and whether it is the window's first
buy, exactly the rows a full save would hold for it. The fsync before every create stays, and so does every
reservation before every send. One `fdatasync` per row is the usual case, not a guarantee (rebreak, 2026-10-14): the
ledger's WAL checkpoints itself every 1000 frames, so a row that is the first commit after a checkpoint also syncs
the restarted log's header (2), and a row whose commit takes the log past 1000 frames runs the checkpoint inside it
(3, plus copying the changed pages into the database), all before the create's first byte. The old full save had
the same, more often (about 11 frames a save against the row's 2). Moving checkpoints off the send path is
deferred (work log, 2026-10-14). The full state is saved at most once a second (heartbeat), at once after a fill,
settlement, stop, release or owner action, and at startup and shutdown; each full save empties the journal in
the same transaction. A cancel writes nothing before or after its request (it only lowers exposure, the
reservation is kept until Kalshi's list confirms it, and a restart cancels every open order again). A restart
reads the last full save plus the journal (`replay_journal`; `durable_state` in tests) and records "restored from
the pre-send journal" for each order it adds; what a crash can lose is only what the next reconcile proves again
(an order id from Kalshi's reply, a release the order list confirms, cash), so until then the restored stops are
as strict or stricter. A reconcile that changes nothing of record (no order's status, id, fill count or
reservation, no window newly marked as the owner's, settled by outcome or with changed terms) no longer marks the
state for the next second's save; it waits for the five-second save (a quiet desk saved every second). The
practice desk's ledger commits with synchronous=NORMAL and its display copy is no longer synced, except the first
save on a fresh ledger, which is synced so a host failure cannot leave the display copy without its ledger state
(the "missing beside existing report" check would then keep the whole speed desk, real-money companion included,
from starting). An order journaled but never sent (a crash between the row and the send, or a create lost before
Kalshi) used to keep its reservation for good and hold a restart in "Reconciling startup orders". It is now
released, and never sent again, only once its market has closed and two complete order lists read after the
close, at least 30 s apart, leave it out while that window's own facts agree: neither order list is behind the
fills, Kalshi lists no fill in that window under an order id the bot does not know (it could be this order's; a
fill of an order Kalshi lists as the owner's, without the bot's client-id prefix, is the owner's and marks the
window as the owner's instead, unless that order has an unsent order's exact market, side, size and price: it
could be that order listed without its client id, so its fill holds the order, as before),
and the position matches the books or Kalshi has settled the market (its settlement row, and a flat position; in
a window the owner also traded, the lists and fills decide). A slow read or a mismatch in another window no
longer holds it. The release runs before the settlement pass, so the window settles in the same read and its
payout check audits the books against Kalshi's revenue. (Review blocker, 2026-10-13: Kalshi settles about 5 s
after the close, KXBTC15M-26OCT131145 at 15:45:04.68 UTC, and a settled market leaves the unsettled positions
list; the release used to need a read with no failed check at all, so an unsent balancing bid or lock, which
always sits in an unpaired window, failed position_mismatch on every read and real trading stopped for good.)
While such an order waits after the close, complete lists are read at once and then every 30 s, so it is
released about 30 s after the close. Until then it counts in every cap and stop, and the bot places no new order
anywhere (an unresolved order pauses all new orders, as before; a restart waits at most the rest of its window
plus about a minute): absence alone proves nothing while the market trades, since a request held up on the way
could still arrive, and Kalshi accepts no order on a closed market. An order that did reach Kalshi is listed
whatever its status and is adopted, canceled and released on Kalshi's word as before; a late copy that turns up
while the market trades is adopted the same way. A definite refusal (the send guard's last check, or a definite
4xx) rewrites that order's journal entry at once (synchronous=NORMAL: nothing was sent, so a host failure can
only bring back the reservation the synced row holds), so a crash in the second before the next full save no
longer restores a never-sent order as reserved. After a restart replayed the journal, the next full save empties
the journal on disk as well.
`tests/test_speeddesk_live_crash.py` kills a child process (`os._exit`) after the journal row and before the
send, and after the send before the reply; checks at every send that the journal plus the last full save equals
the full save made at that moment; and restarts from mid-run copies of the ledger (crash and after a full save)
to check that the stop math is identical after the restart's first reconcile. `tests/test_speeddesk_live_release.py`
kills it between the row and the send of a balancing bid and of a lock, loses a balancing create in the running
desk, settles a minute late, and kills within a second of a refusal; `tests/test_speeddesk_live_killpoints.py`
takes crash images at ten points of the order path and runs each restart through the close and Kalshi's
settlement (`KILLPOINT_SEEDS=6 KILLPOINT_CAP=1000` repeats the review's 350 images).

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

## 12. Kalshi arena (practice; owner, 2026-10-13)

The owner: "Give our bots the incentive they're giving Grok bots: make money or die." `nightcrawler/kalshi_arena.py`
runs a town of practice Kalshi Bitcoin 15-minute desks that must earn their rent or be evicted. **Practice money
only.** Nothing in it holds a client, a key or a Settings object after start-up, places an order or changes a live
setting. A candidate is shown to the owner; real money stays with the live companion and its own rules.

### The town

- **Residents:** `KALSHI_ARENA_POPULATION` (12) practice desks (`PracticeDesk`), each with its own genes, trading the
  same live `KXBTC15M` books and prints the live desk sees. Each fills on its own; no resident competes with another
  or with the real desk.
- **Control:** one resident (`Live`) always runs the live rules. Its genes come from the deployed settings through
  `LiveLimits`' own clamps (`live_genes`). It is never evicted, and every comparison is against it.
  **It runs the configured limits, which are the earned-growth ladder's rung 0 (9.2):** the town reads Settings once
  at start and never the ladder, so after a live promotion (rung 1: $15/$30/$9) live trades a bigger window than
  every resident, the control included. The panel's note says so; nothing here reads or writes the ladder's state.
- **Start cash:** $50 of pretend money each (`START_CASH`, the account size the owner gave; `docs/ACCOUNTS.md`
  records $25.00 at the first balance read on 2026-10-12, to be confirmed).
- **Rent:** the first window settled on a new UTC day charges every resident, the control included,
  `KALSHI_ARENA_RENT_USD` ($0.20) for each day since the last rent (a town that was down pays the missed days, at
  most 7 at once). There is no rent on the town's first day. Railway is about $5 a month, or $0.17 a
  day for the whole service, so $0.20 each means every resident must earn the whole bill plus 20 % by itself: the
  town pays twelve times the real bill. That is the "make money or die" bar, chosen on purpose.
- **Eviction (never the control), checked after each settled window, in this order:**
  1. it cannot pay the rent ("could not pay the rent");
  2. its money falls under `KALSHI_ARENA_BROKE_USD` ($10: it could not fund one $10 window; "went broke");
  3. `deskguard.judge` on its traded windows says `losing` (the 95 % upper bound below zero from 30 windows, or the
     99 % early stop from 10).

  The graveyard keeps the newest 40 rows: who, the record, why, the verdict, the genes and the paired comparison.
- **Births:** every empty home goes at once to a child of a parent drawn from the richest half of the residents
  with a record: at least 20 traded windows, the control always counts (the richer more often, `random() ** 2`). A
  newborn's untouched $50 is not a record; in a losing town it used to outrank everyone who had traded. Each number gene moves by up to 12 % of its range and is redrawn one time
  in ten; each switch flips one time in ten. The first town is the control, five children of the control and six
  newcomers with random genes. A newborn joins the next window. A population setting that falls on restart sends the
  poorest challengers away.
- **Equity** is $50 plus settled window P&L minus rent. An open window is not counted.
- **Paired statistics:** for every challenger, over every window both it and the control held,
  `d = (its P&L or 0) - (the control's or 0)`. A window it skipped while the control lost is part of an edge.
- **Candidate (shown only):** `judge` says `winning` (100 or more traded windows, at least 3 losses, the 99 % bound
  and the stress test) AND paired `n >= 100` AND `t >= 2`. The flag is set once. It records `n`, `t`, the mean dollars
  a window ahead of the control, the verdict, and how the genes could be adopted. From then on a `since_flag` record
  gives a free out-of-sample check, and `candidate_now` follows the condition. **A candidate is a lead for a
  pre-registered test, not proof.** False candidates will appear: about 11 challengers plus births are checked after
  every window (optional stopping), their genes sit close to the control's, and eviction selects survivors (winner's
  curse).
- **Control rule change:** at start the control's rule id (`rule_id(live_genes)`) is compared with the saved one. On
  a change, the control's record and every paired and `since_flag` statistic restart (`kalshi_arena_control_changed`).
  Challengers keep their own records.
- **Shared limits change (the regime):** the limits every resident shares (`fixed_config`: budgets, clip, the live
  risk book's rules) have their own id. When they change (the owner's "double tomorrow", say), every resident's
  record, verdict and comparison restart, because each was earned under other rules and `deskguard` judges the
  current rule only; money, rent and lifetime counts stay (`kalshi_arena_regime_changed`).
- **Void:** these windows count for nobody, equal for all (`town.void_windows`):
  - one that had started at a restart (every desk is rebuilt fresh); one listed but not started yet is joined;
  - one still without an outcome two hours after its close;
  - one whose feed was incomplete for the town (`town.void_feed`, logged `kalshi_arena_void ... why=`): the live
    loop dropped events while it was open (`feed_dropped`), or the town read an event more than 3 s after it
    arrived, the desks' freshness (`feed_late`). Otherwise a town that fell behind would book windows it could not
    trade as if it had seen the market.

### Genes

| Gene | Range (grid) | Control (live) | Practice behaviour (`SpeedConfig`) |
|---|---|---|---|
| `make_edge` | 0.020-0.060 (0.005) | `SPEEDDESK_MAKE_EDGE` | resting bid at `floor(fair - make_edge)` |
| `starter` | 2-10 contracts | the live clip (5) | a window's first buy, and each round's, held to whole pairs at the pair cap (`starter_clip`) |
| `pair_cap` | 0.95-0.99 (0.005) | `LiveLimits.pair_cap` | matched pair cost limit, fees included |
| `max_imbalance` | 0.10-0.25 (0.01) | `LiveLimits.max_imbalance` | imbalance limit once balanced |
| `starter_delay_s` | 0-180 s (5) | 0 | no starter in a window's first N s (`starter_delay_s`) |
| `starter_stop_s` | 0-600 s (10) | 0 | no starter in a window's last N s (`starter_stop_s`) |
| `close_s` | 120-300 s (5) | `LiveLimits.lock_s` (240) | buying stops and the lock starts here (`cutoff_s`, `lock_s`), as live couples them |
| `lock` | on/off | on | complete the unpaired side at the ask from `close_s` until 20 s before the close |
| `lock_max` | 0.90-0.99 (0.01) | `LiveLimits.lock_max_price` (0.97) | most a lock pays a contract (the stop has its own cap, 0.99) |
| `stop` | on/off | off | the protective stop (`stop_s`, `stop_pair_cost`) |
| `stop_s` (X) | 300-840 s (10) | n/a | the stop watches from X s before the close |
| `stop_cost` (T) | 1.05-1.25 (0.01) | n/a | it completes the pair at the ask once completing would cost at least T a pair |
| `rounds` | on/off | off | after a complete pair (nothing pending), one fresh first-size buy, then balancing only |
| `filters` | registered names | none | a starter gate (`FILTERS` ships empty; a filter is one entry plus its own lab test) |

Every resident shares these with the live desk (`fixed_config`):
- takes (`SPEEDDESK_TAKE_EDGE`, 1.0 in production, so maker only);
- the 5-contract clip for every order after the first;
- the $10 window, $20 open and $6 day budgets, applied the way the live risk book applies them
  (`LiveRiskBook.can_buy`): the day stop refuses a buy once today's settled loss plus the money still at risk plus
  its cost reaches $6, and the open budget counts money at risk (a complete pair risks nothing), not gross spend;
- a resting bid expires 30 s after the whole second it was sent (live's `expiration_ts = int(now) + 30`), and its
  replacement queues behind the book again;
- the edge must survive live's fee reserve rounded to the account's grid ($0.0001 for the attested direct account;
  an unattested account reserves a whole cent per 0.01-contract fill, so live, and with it the whole town, sends
  nothing);
- the latency and whole contracts;
- the speed desk's own sigma.

Live's lifetime total stop ($10) is not copied: it halts the account until the owner resumes it, so a control that
copied it would freeze and every comparison would be against a flat line. Challengers have the broke line instead.

**The stop's meaning (a choice to confirm):** "complete the pair at the ask when pair cost would reach T" is read as
a stop-loss. It fires when the cost to complete *rises to* T, which caps a run-over window at about T (compare the
16:00 and 16:15 UTC locks at $1.37 and $1.29). If the owner meant "accept a completion cost up to T", it is the same
code with the comparison flipped.

### Practice model fields (opt-in; the defaults are today's desk)

`SpeedConfig` gains thirteen fields: `starter_clip`, `starter_delay_s`, `starter_stop_s`, `rounds`,
`whole_contracts`, `lock_s`, `lock_max_price`, `stop_s`, `stop_pair_cost`, and the live risk book's rules
`day_stop_counts_risk`, `hedged_open_budget`, `rest_ttl_s` and `edge_fee_precision`. `PracticeDesk` gains a
`starter_gate` slot, a `trade_memory` (prints remembered for de-duplication; 10,000 by default, 256 for a resident,
since the town de-duplicates once for all of them) and `forget()`, which drops a settled window and keeps only today
and yesterday in the day tables. The arena keeps its own record and never adds a settled window again, so
`advance()` and `evaluate()` stay short. A starter still resting when its no-first-buy period (or a filter) begins
is cancelled there. The protective stop pays up to 0.99 a contract (completing a pair below $1 always lowers the
loss); the lock keeps `lock_max_price`.

The lock mirrors live:
- it needs both books fresh, no take pending in the window and at least one whole unpaired contract;
- it buys at the best ask, as a whole-cent limit of at most `lock_max_price`, `min(unpaired, clip, depth)` contracts;
- it fills like a take: the first book after the latency, the top level, immediate-or-cancel;
- no budget, pair cap, edge, cutoff or day stop applies;
- it survives `advance()` in the cutoff and the day stop, and counts as `lock_*`, never as a take.

With the defaults no lock exists. `tests/fixtures/speeddesk_model_golden.json` was generated from the model before
these fields, and it replays exactly (`tests/test_speeddesk_model_genes.py`). Saved configs leave out fields at their
defaults, so a rollback still reads them. The live twin and the main practice desk run on the defaults.

### Speed: the town runs in its own process

The review of 2026-10-13 showed that a town in a thread of the live process can stall the live loop: a pass that
spins or hangs holds Python's lock (a 1 ms loop's median lateness went from 0.12 to 5.3 ms, and nothing noticed), a
busy market capped the town near 400 books a second and its lock contention raised the live p99 by 0.6 ms, and its
objects lengthened every garbage collection. A process boundary removes all of it.

- **The live loop's side (`ArenaLink`):** `on_book` and `on_trade` append the Kalshi book or print to a list
  (bounded at 1,024; beyond it they are dropped and counted), and `on_status` appends the gap facts. `on_tick` and
  `on_windows` have no arena code. Once per runner step (every 50 ms) `flush` encodes at most 256 events plus the
  market facts that changed (windows, price, sigma, maker windows, outcomes) into one frame and writes it to a Unix
  stream socket without waiting: a full socket drops the whole frame (counted; the next frame carries every fact and
  whole ladders again), and a dead town is noticed (`kalshi_arena_exited`) and never fed again. Nothing in it raises.
  - A book's ladders travel as changes to the ladder last sent: the Kalshi socket rebuilds a ladder around the one
    level a delta changes, so a frame carries about one level a book, found by a C-level identity scan.
  - Not a pipe: a pipe's reader holds a lock its writer needs while it copies, so a descheduled town would make the
    live loop wait. A socket's sender only takes spinlocks.
  - Measured on 2026-10-13 (Python 3.13, a shared 4-core machine at load average 8 to 12): 400 books a second of
    25-level ladders cost **0.16 ms of the live thread's CPU a flush (median), p99 0.34 ms, max 0.54 ms**, about 2.4
    us a book; a put is about 0.15 us.
- **The town's side (`worker_main`):** the same interpreter, started isolated (`-I`) with an environment of `PATH`,
  `LANG` and `TZ` only (no `KALSHI_*` key or any other secret reaches it), in the idle scheduling class at nice 19
  (it never takes a CPU from the live desk), first in line for the out-of-memory killer, under a 1 GiB address-space
  limit, with no core dump (its working directory is DATA_DIR, the live desk's volume), and killed by the kernel if
  a pass hangs for 120 s (SIGALRM) or spends 5 s of CPU (SIGVTALRM, re-armed every pass; neither has a handler: a
  spin dies after 5 s of a core, not 2 minutes, and a town merely starved of CPU spends none). What took effect is
  read back after these steps and logged once (`kalshi_arena_hardened nice= sched= as_limit= oom_score_adj=
  applied=`, a WARNING when the town would compete for the CPU at normal priority) and shown in the panel's
  `feed.hardening`: a runtime that refuses a step (a seccomp or gVisor profile, a read-only /proc) is visible. It
  sleeps on its own timer,
  takes what arrived, then runs a pass, so a write never wakes a process: with a waiting reader a write's p99 was
  8 ms, without one 0.1 ms. A book is applied to the residents only if it is the latest for its window and side in
  the pass, or a resident waits on a take or lock there (a take is checked against the first book after its
  latency); prints are de-duplicated once for all residents.
  - Its boot takes the idle class and nice 19 BEFORE it imports this package (the imports are most of a start's
    CPU, about 70 ms; at a restart they would otherwise compete at normal priority with the live desk's own start).
  - One town per DATA_DIR: it holds `DATA_DIR/kalshi_arena/town.lock` (an exclusive `flock`) for its life; a second
    town (a wedged one outliving its bot outside a container, or a second bot on the same volume, whose live desk the
    controller lock refuses but whose arena would otherwise start) waits 5 s for it (an old town's final save after
    a quick restart), then exits without writing (`kalshi_arena_busy`, exit 4).
  - It imports no `speeddesk_live*` module (`LiveLimits` is imported only where the live process builds the
    configuration), nothing of an order path and nothing that speaks HTTP or TLS, and it inherits no file of the
    live desk (`close_fds`: not the companion's `controller.lock`, not a ledger). Shown on the real process
    (`test_the_real_town_imports_no_order_path_and_inherits_no_live_file`). Its empty environment is not an OS
    boundary: a process of the same user (root on Railway) can read its parent's `/proc/<pid>/environ`; the town's
    code never does, and nothing else in it reaches a key.
  - A write that fails (a full disk) removes its temporary file, since DATA_DIR is the live desk's volume too. A
    halt writes the panel first and on its own (its brief form when the whole panel does not fit), so the page says
    "halted" even when the larger state file cannot be written.
  - Frames that arrive with the configuration (the link's first flush, 50 ms after start, lands while the town is
    still importing; it carries the window list and whole ladders) are read before the first pass, never dropped.
- **Isolation, proven by tests (`tests/test_kalshi_arena_feed.py`):**
  - a stand-in hardened like the town spinning on every core: the live loop's 1 ms sleeps wake as on time as with
    no town (median 0.076 -> 0.073 ms, p90 0.125 -> 0.133 ms);
  - a town that never reads: every flush returns at once (CPU p99 under 1.5 ms with 80 books a flush), whole frames
    are dropped and counted;
  - a town that dies: noticed, logged, never fed again, never an error;
  - the town halts itself after 5 failed passes in a row (`kalshi_arena_halted`, saved for the page) and exits;
  - the opt-in wall-clock test (`NIGHTCRAWLER_PERF_TESTS=1`): with the real town at about 350 books a second, a 1 ms
    loop's lateness p50 0.080 -> 0.080 ms and p90 0.123 -> 0.132 ms against the same loop without it (the shared
    machine's own p99 is about 3 ms either way).
- **Shutdown:** the runner closes the link after every real-money shutdown step (the live companion's shutdown, the
  practice cancel and checkpoint), and `close()` gives the town up to 1 s for its final save after the live companion
  closed (the bot is the container's first process, whose exit ends every other).
- **Production's own figure:** `kalshi_arena_feed` (the live side, every 5 minutes: put, dropped, frames, flush p50,
  p99 and max in us) and `kalshi_arena_status` (the town: received, dropped, late, coalesced, pass CPU p99 and max,
  duty, lag, and the live loop's flush p99 and max, which the link sends; every minute while the feed lags or drops).
  `duty_pct` is the town process's whole CPU over wall time (reading and decoding frames too, about half of it at
  400 books a second, not only the pass).
  The town's process costs memory of its own (about 22 MB at start).

### Files, page and logs

- `DATA_DIR/kalshi_arena/state.json` is written atomically (a `.tmp` sibling, then a rename) and stays at about
  100 KB after 30 days. It is fsynced (it is the town's only record) only after a change that matters (a settlement,
  birth, eviction, void, flag or halt): the minute's heartbeat save, which only keeps the panel and its counters
  current, is a plain rename, so the town fsyncs a few times an hour on the volume and journal the live desk's own
  pre-send fsync uses, not every minute. `panel.json` stays under 32 KB (each resident's genes and money lines).
- Desks are never saved (each would be about 240 KB with its tape); they are rebuilt from their genes at start. A bad
  state file (unreadable, too deep, genes no desk accepts, a broken day) is renamed `state.json.bad-<epoch>` and the
  town starts fresh; a single display row that is not plain finite JSON (a grave, an event, a candidate flag) is
  dropped instead, so every later save works. Each resident's settled P&L today is saved, so the day stop survives
  a restart as live's does.
- The page: the top-level `kalshi_arena` block (`pagestate.kalshi_arena_block`; the contract with the town and its
  fixture `tests/fixtures/kalshi_arena_page.json` are in docs/COORDINATION.md, "kalshi_arena contract and fixture")
  reads `panel.json` only, and refuses one over 256 KiB unread (the page builder runs in the live desk's process).
  It is always a block: schema_version 1, mode "paper" and real_orders_enabled false (page constants), a status
  (fresh, degraded, stale, halted, missing, off) with a reason, and every figure null when nothing is known. It
  whitelists every field, labels it "Practice (pretend money)", and is stale after 180 s (three heartbeats). It is
  never summed into any money total, the town ledger, the goal, the hearts or the plain words; a test checks the
  whole page is otherwise the same with the arena on or off.
- Logs: `kalshi_arena_started`, `_town` and `_hardened` (the process), `_born`, `_evicted`, `_candidate`, `_control`,
  `_control_changed`, `_regime_changed`, `_void`, `_status`, `_feed` (the live side), `_state_reset`, `_step_failed`,
  `_halted`, `_busy`, `_exited`, `_stopped`, `_not_started` and `_close_failed`, with no exception text.
- A bad `KALSHI_ARENA_*` value turns the arena off with `config_kalshi_arena_off bad=<NAME>` (never the value); it
  never stops the engine, and with it the real-money Kalshi companion.

### What the control can and cannot copy (plan corrections, 2026-10-13)

1. **"The control runs the exact live genes"** means the live rules as the practice model simulates them. The
   differences, largely shared by every resident (so paired differences mean more than arena dollars):
   - fills are simulated (maker prints against the displayed queue; a take or lock is rechecked after the latency);
   - live sends one order per account read;
   - a live lock IOC can sweep several levels; practice fills the top level;
   - live's lifetime total stop halts the account; the control never halts (see above);
   - live leaves owner-traded windows alone.

   The day stop, the open budget, the 30 s order expiry and the fee-reserve edge check are copied (review of
   2026-10-13; `tests/test_speeddesk_model_genes.py` compares the budgets with `LiveRiskBook.can_buy` on 400 random
   states).
2. **Gene ranges stop at the live ceilings:** `LiveLimits` clamps `pair_cap` to 0.99 and `max_imbalance` to 0.25.
3. **Lock start and cutoff are one gene (`close_s`, 120-300 s).** Live raises its lock start to at least its cutoff
   (180 s by default) and stops buying when the lock starts. A candidate's `close_s` is therefore expressed by setting
   both `SPEEDDESK_KALSHI_CUTOFF_S` and `SPEEDDESK_KALSHI_LOCK_S` to it.
4. **Some genes need code (and the owner's word) to adopt:** lock off (live cannot switch its lock off), the stop,
   rounds, starter timing, filters, and a first buy different from the clip (live's clip caps every order). The
   candidate card lists "settings that express it" apart from "needs code".
5. **Python 3.12 in production:** nothing 3.13-only is used.
6. **Real-money files:**
   - the hook lives in `speeddesk.py` (three bounded appends, one flush a step, start, and a close after every
     real-money shutdown step);
   - `speeddesk_live*.py`, `deskguard.py` and `engine.py` are unchanged;
   - `config.py` gains only the four practice settings, and a bad one turns the arena off instead of stopping the
     engine.

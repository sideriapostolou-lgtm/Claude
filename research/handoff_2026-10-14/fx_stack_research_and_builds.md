# fx_stack_research_and_builds (workflow wf_4396cb42-76e)



---
## result 0 

# FX rewards (LIP) research: settlement source, Pyth access, request budget

Research only, done Tue Oct 13, 2026, 23:45 to 00:05 UTC (4:45 to 5:05 pm Pacific). No code was changed, nothing was committed, and nothing was pushed. Every Kalshi call was a public GET with no key. No authenticated endpoint was called. No secret was read or stored, and no Railway setting was touched. The Pyth calls were keyless and only confirmed that the price endpoints refuse requests without a key. The branches were read with `git show origin/<branch>:<path>`, so no worktree was needed and the main checkout was not touched. Evidence (3.9 MB) is under `fxlip/dl/`; every path below is relative to `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/`.

## Bottom line

1. **Kalshi already publishes its settlement price series for free.** `GET /trade-api/v2/live_data/events/{event_ticker}` is public (`security: []`) and needs no key. For any FX, metals or natural-gas 15-minute event it returns the **last hour of the underlying price at 1-second resolution**:
   - 3,600 points, about 115 KB, `cache-control: public, max-age=1`;
   - the newest point's label falls between 1.7 s before and 0.2 s after the request time (14 polls);
   - in all **36 of 36** settled windows we checked, across 9 series, `expiration_value` equals the value at second label `close - 1 s`. In 18 of those windows the value at `close` differs, so the match is not luck.

   This is a free, keyless, settlement-exact 1 Hz feed. The playbook said we had no Pyth data at all; this partly closes that gap. It still cannot show a lead under 1 second.
2. **How these markets settle.**
   - The settlement value is the **close of the 1-minute Pyth candle that ends at the window close**, which is the last Pyth price before HH:MM:00.
   - The strike is the same value at the window open, which is the previous window's settlement value.
   - The market pays YES if close ≥ strike, so a tie pays YES.
   - There is no averaging.
   - Coin Race is different. It settles on **CF Benchmarks**, not Pyth, using a 60-second time-weighted average of each coin's price at the start and at the end of the window.
3. **Kalshi sells its own Pyth feed.** The authenticated WebSocket channel `pyth_value` costs **$1,000 a month, with the first 7 days free**.
   - It needs a Kalshi API key (signed handshake). A key limited to the `read` scope can be created.
   - Messages carry `source_ts_ms` (Pyth's time) and `received_at` (Kalshi's receive time), both in milliseconds.
   - Kalshi's coverage table lists the metals and natural-gas feeds but **not FX** (UNVERIFIED that FX is included).
4. **Pyth.**
   - **Hermes has required `Authorization: Bearer <key>` since Aug 26, 2026, 16:00 UTC.** We confirmed 401 `unauthorized` on both Hermes hosts, for latest prices and for the stream.
   - Pyth Terminal plans:
     - Free: no API access.
     - **Starter: $500 a month, but "all crypto symbols" only and at most 1 update per second**, so it covers none of our 9 feeds.
     - **Pro: from $2,500 a month.** This is the plan that covers FX and metals, at up to 1 ms.
   - Copper and natural gas are "Pyth Indices", which are sold by Pyth's sales team, not self-service.
   - A free Pro trial key is documented, but its length and contents are not published (UNVERIFIED).
5. **Request budget.**
   - Add the 14 LIP 15-minute tickers to the recorder's **existing once-a-second batch book call**. That captures every LIP book at 1 s for **0 extra requests**.
   - Add a 15-minute rewards (incentive programs) pull and a 10-minute pull of the free 1 s price series.
   - Total is about **1.52 requests a second, against the 2.0 ceiling**.
   - All 5,631 LIP markets at 1 s would need 57 requests a second, which is impossible.
6. **Suggested order.**
   - (a) Record the free 1 s price series and 1 s LIP books now, at no cost, and measure how often Kalshi's books are still stale a second after the price moves.
   - (b) Only if that happens often, use the Pyth trial, or Kalshi's 7 free days, to measure leads under a second.
   - (c) Pay $1,000 to $2,500 a month only after (b) shows an edge. For scale: one FX pair's gross reward is about $117 a day before fill losses (PLAYBOOK §2). Pyth Pro is about $83 a day and Kalshi's feed about $33 a day.

---

## 1. The 15-minute rewards series: tickers, settlement, hours, structure

### 1.1 Series (public `GET /series/{ticker}` [K1], `GET /incentive_programs` [K2], `GET /markets` [K3])

| Series ticker | Underlying | Pyth symbol (source) | Shard (`exchange_index`) | Fee type | Reward per window / Target (active now) | Settlement rounding | Market suffix |
|---|---|---|---|---|---|---|---|
| `KXEURUSD15M` | EUR/USD | `FX.EUR/USD` (contract terms: "e.g., FX.EUR/USD") | 0 | `quadratic`, ×1 | $50 / 300 | 5 dp | `-30` |
| `KXGBPUSD15M` | GBP/USD | `FX.GBP/USD` (series source URL) | 0 | `quadratic`, ×1 | $50 / 300 | 5 dp | `-30` |
| `KXUSDJPY15M` | USD/JPY | `FX.USD/JPY` | 0 | `quadratic`, ×1 | $50 / 300 | 3 dp | `-30` |
| `KXAUDUSD15M` | AUD/USD | `FX.AUD/USD` | 0 | `quadratic`, ×1 | $50 / 300 | 5 dp | `-30` |
| `KXUSDCAD15M` | USD/CAD | `FX.USD/CAD` | 0 | `quadratic`, ×1 | $50 / 300 | 5 dp | `-30` |
| `KXCOPPER15M` | Copper | `Commodities.Index.CU/USD` (series source URL) | 2 | `quadratic`, ×1 | $20 / 300 | 5 dp | `-00/-15/-30/-45` |
| `KXPLATINUM15M` | Platinum | `Metal.XPT/USD` | 2 | `quadratic`, ×1 | $20 / 300 | 3 dp | same |
| `KXPALLADIUM15M` | Palladium | `Metal.XPD/USD` | 2 | `quadratic`, ×1 | $20 / 300 | 3 dp | same |
| `KXNATGAS15M` | Natural gas | `Commodities.Index.NATGAS/USD` | 2 | `quadratic`, ×1 | $20 / 300 | 5 dp | same |
| `KXCRYPTOLEAD15M` (Coin Race) | Highest 15-min return of BTC, ETH, SOL, XRP, HYPE | **CF Benchmarks**, not Pyth | 2 | `quadratic`, ×1 | $20 per coin market / 1000 | returns to 3 dp (in %) | `-BTC/-ETH/-SOL/-XRP/-HYPE` |

- **The 14 market tickers that earn a 15-minute reward right now** (from the live `/incentive_programs` pull at 23:46 UTC): one per FX and commodity series plus five Coin Race markets. Example: `KXEURUSD15M-26OCT132000-30`.
  - Event tickers use the New York close time: `KX<SERIES>-<YYMONDD><HHMM ET>`.
  - Programs are `incentive_description: "series_lip"` with `discount_factor_bps: 5000`.
  - `period_reward` is in centi-cents: 500000 means $50.
- **Fees.** Kalshi's series schema defines `quadratic` as the General Trading Fees Table, which is taker-only. Maker fees apply only to `quadratic_with_maker_fees` and `quadratic_with_combo_maker_fees` [K4]. Every series above is `quadratic`, so **resting (maker) orders pay no fee**.
  - Not re-checked today: the fee-schedule PDF answered 429, so the taker formula itself was not re-read.
- **Tick size and structure.**
  - Every market has `price_level_structure: linear_cent` and `price_ranges` 0.00 to 1.00, step 0.01, so the **tick is 1¢**. The contract terms say "Minimum Tick … $0.01" [T1].
  - `notional_value_dollars` is 1.00. There is one binary market per window (five for Coin Race).
  - `strike_type: greater_or_equal`. `floor_strike` is the opening value. `custom_strike.round_digits` is 5 or 3.
  - Position accountability is $25,000 per strike per member [T1].
- **Settlement speed (measured).** `settlement_ts − close_time` was:
  - FX: 14.5 to 14.6 s;
  - metals and natural gas: 19.5 to 24.7 s;
  - Coin Race: 24.6 to 94.6 s (median 34.6 s).

### 1.2 Settlement formula: primary sources and the check

- **FX market rules** (`rules_primary` / `rules_secondary` of `KXUSDJPY15M-26OCT132000-30` [K3]):
  - "If the value of the USD/JPY exchange rate is **at least** the value … as published by Pyth Network at 7:45 PM EDT … At 8:00 PM EDT … resolves to Yes."
  - "The market resolves based on the **Close price** of the USD/JPY exchange rate as published by Pyth Network At 8:00 PM EDT … The Target Price … equals the value … at the opening of the 15-minute window … Rounding to 3 decimal places."
- **FX contract terms** [T1] (`assets.kalshi.com/contract_terms/FXEURUSD.pdf`):
  - The Source Agency is Pyth Network, using its feed "identified by feed name and/or price feed ID, e.g., 'FX.EUR/USD'".
  - "Where the Source Agency publishes both a price and an associated confidence interval, the Underlying shall refer to the **midpoint/aggregate price only**."
  - A substantially equivalent replacement feed may be used if the feed goes away.
- **Metals and natural-gas market rules** (`KXCOPPER15M-26OCT132000-00`) [K3]:
  - "If the **close price of the 1-minute candlestick** for Copper … at 8:00 PM EDT is at least the close price of the 1-minute Pyth COPPER candlestick at 7:45 PM EDT …"
  - "… the close price for the 1-minute candlestick at a given time is **the price at the end of the immediately preceding one-minute interval**. For example, the candlestick timestamped 4:59 PM reflects trading during 4:59:00 PM to 4:59:59 PM and closes at 5:00:00 PM. If no data is published … the most recently available published data will be used."
- **Coin Race rules** (`KXCRYPTOLEAD15M-26OCT132000-XRP`) [K3]:
  - "Return = (Ending Price − Starting Price) / Starting Price × 100."
  - "The Starting Price and Ending Price are defined as the **time-weighted average of the Spot Rate values published by CFBenchmarks during the 60-second intervals immediately preceding** the start and end."
  - Returns are rounded to 3 dp in percent, and there are tie rules.
  - The series lists `settlement_sources: CF Benchmarks`.
- **Empirical check** (script output in this session; data in `fxlip/dl/kalshi/live_*.json.gz` and `rec_*.json`):
  - For all 9 Pyth series, `expiration_value` equals the public 1 s series at label `close_time − 1 s` in **36 of 36** finalized windows.
  - In **18** of those, the value at label `close_time` was different. Example: AUD/USD 19:45 window, close−1 s = 0.69841 (equal to the settlement value), close = 0.69838.
  - The next window's `floor_strike` equalled the previous `expiration_value` every time, and equalled the series at `open − 1 s`.
  - Results agreed with "≥" in 45 of 45 windows, including one exact tie (GBP/USD 18:45 window, 1.32544 vs 1.32544, result YES).
  - The boilerplate line '"Above" means strictly greater than' in `rules_secondary` does not decide these markets. `strike_type` and "at least" do.
- **So, for practice settlement:** use the last Pyth aggregate price strictly before the boundary (the second labelled HH:MM:59), rounded to `round_digits`. Pay YES on ≥.

### 1.3 Trading hours

- **Kalshi maintenance:** every **Thursday 3:00 to 5:00 am ET** there is a trading pause. Orders cannot be placed or amended; cancels are allowed [K5]. `GET /exchange/schedule` shows the same [K6].
- **Reward windows observed Oct 7 to 14** (from the rewards research's `/incentive_programs` history pulls, `kalshi_rewards/history/dl_ip/rows_liquidity_*.tsv`). Times are ET, with Pacific in brackets:

| Series | Windows in 7 days | First window of the week → last window | Daily gap | Other gap |
|---|---|---|---|---|
| FX: EUR, GBP and JPY identical. AUD and CAD rewards only started Oct 12, 21:32 UTC (122 windows, no gap yet) | 471 | Sun 17:15 [2:15 pm] → ends Fri 17:00 [2:00 pm] | none | Thu 03:00 to 05:00 |
| Copper, platinum and palladium (identical) | 447 | Sun 18:15 [3:15 pm] → ends Fri 17:00 | 17:00 to 18:15 ET Mon to Thu [2:00 to 3:15 pm] | Thu 03:00 to 05:00 |
| Natural gas | 496 | Sun 18:00 [3:00 pm] → ends Sat 00:00 [Fri 9:00 pm] | none | Thu 03:00 to 05:00 |
| Coin Race | 664 | 24/7 | none | Thu 03:00 to 05:00 |

- **Pyth feed hours** (`schedule` field, public `GET /v2/price_feeds` [P6]):
  - FX: `America/New_York;O,O,O,O,0000-1700,C,1700-2400`, which is Sunday 17:00 to Friday 17:00 ET. Dec 24 and Dec 31 close at 17:00.
  - XPT and XPD: CME-style hours, with a daily 17:00 to 18:00 ET break and a CME holiday list.
  - The copper and natural-gas indices are 24/7 (`O,O,O,O,O,O,O`), but Kalshi still lists only the windows above.

## 2. Does Kalshi offer an authenticated value feed of the Pyth price? Yes.

- **Channel:** `pyth_value` on the Trade API WebSocket [K7].
  - Address: `wss://external-api-ws.kalshi.com/trade-api/ws/v2`. The older `wss://api.elections.kalshi.com/trade-api/ws/v2` still works [K8].
  - Added July 23, 2026 (changelog [K9]).
- **Cost:** "The Pyth data feed costs **$1,000/month**, with the **first seven days free**." The subscription link is `buy.stripe.com/eVqaEXfmu9eN2ZB8gr4ZG0a` [K7].
- **Auth:**
  - The connection itself is authenticated. "Authentication is required to establish the connection … Some channels carry only public market data, but the connection itself still requires authentication" [K10].
  - The handshake sends the headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE` and `KALSHI-ACCESS-TIMESTAMP` (ms). The signature is over `timestamp + "GET" + "/trade-api/ws/v2"` [K8].
  - Kalshi API keys can be limited to scopes. `scopes: ["read"]` grants read endpoints only, without `write` or `write::trade` [K11]. So a key that cannot trade is possible. Whether such a key is accepted on this channel is UNVERIFIED; the docs do not say.
  - The recorder refuses to start when Kalshi keys are present (`docs/KALSHI_RECORDER.md` §1). This feed would therefore need its own process, and the owner would have to decide.
- **Subscribe:**

  ```json
  {"id":1,"cmd":"subscribe","params":{"channels":["pyth_value"],"underlying_tickers":["Metal.XPT/USD","Commodities.Index.NATGAS/USD"]}}
  ```

  - `["all"]` subscribes to everything.
  - `update_subscription` accepts the actions `subscribe_underlyings`, `unsubscribe_underlyings` and `underlying_list`. The list shows tickers seen in the last 2 hours and is not a full catalog.
  - "Pass the exact Pyth symbol … The numeric Pyth feed IDs are reference information" [K7].
- **Message:**

  ```json
  {"type":"pyth_value","sid":1,"seq":42,"sending_ts_ms":…,
   "msg":{"underlying_ticker":"Commodities.Index.PYTHOIL/USD","value_usd":"82.12345000","source_ts_ms":1710000000100,"received_at":1710000000123}}
  ```

  - `value_usd` has 8 decimal places.
  - Duplicate and out-of-order source timestamps are dropped per ticker.
- **Coverage:** the reference table lists metals, commodity futures and indices, including:
  - `Commodities.Index.CU/USD` (3525), `Commodities.Index.NATGAS/USD` (3265), `Metal.XPT/USD` (1781) and `Metal.XPD/USD` (1780);
  - "only a subset". **FX symbols are not listed**, so FX coverage is UNVERIFIED. Check it with `underlying_list` during the free week.
- **Rate limits:**
  - No numeric limit is published for WebSocket connections or messages.
  - The documented WebSocket errors include 25 (subscription buffer overflow), 26 (market limit per subscription) and **27 ("Too many requests - The subscription exceeded its command rate limit")** [K10].
  - REST reads are token-bucketed: Basic tier 200 tokens a second, 10 tokens per default request; Advanced 300 [K12].
- **Related, not needed for LIP:** `cfbenchmarks_value` (about 1 tick a second, with 60-second and final-minute averages) and `cfbenchmarks_value_5hz` (BTC, ETH, SOL, XRP and DOGE only) [K13]. These are the Coin Race settlement source. No price is listed on that page.
- **Free public alternative (found today):** `GET /live_data/events/{event_ticker}` [K14].
  - Added July 30, 2026, "previously only available on the internal API" [K9].
  - Returns `{"live_data":{"type":"commodity","details":{"asset":"EURUSD","cadence":"15min","interval":"1s","start_ms","end_ms","event_ticker","timeseries":[{"t":<ms>,"v":<number>}…]}}}`.
  - 3,600 to 3,601 points covering the trailing hour, about 115 KB, **not gzip-compressed**, `cache-control: public, max-age=1`.
  - The `range` parameter is ignored for this type (`range=15min` still returned an hour).
  - Any event of the series works, including the next, unopened window.
  - The KXCRYPTOLEAD15M event returns 404.
  - The values are rounded to the settlement digits, so this shows changes at the settlement precision, not Pyth's raw `price`/`conf`.
  - Measured price changes per hour: EUR 642, GBP 819, JPY 1,420, AUD 854, CAD 963, copper 2,621, platinum 1,821, palladium 1,147, natural gas 2,165.

## 3. Pyth

### 3.1 Hermes after the upgrade [P1–P5]

- **Cutover:** Aug 26, 2026, 16:00 UTC. "Every Hermes user needs a Pyth API Key … `hermes.pyth.network` now requires authentication" [P1].
- **Base URLs:**
  - `https://hermes.pyth.network`, which was upgraded automatically;
  - `https://pyth.dourolabs.app/hermes`, the "early upgrade" endpoint Pyth recommends. It has "the same routes and response shapes, same API key" [P1][P2].
  - Since the upgrade, Hermes is the "Lazer Hermes API … lazer prices in Hermes format", fed by five Pyth Pro routers with a 3-of-5 signature quorum [P3][P4].
- **Auth:** `Authorization: Bearer $PYTH_API_KEY` on every request [P2].
- **Endpoints** (OpenAPI `https://pyth.dourolabs.app/docs/hermes/openapi.json`, security scheme `http bearer` [P4]):
  - `GET /v2/updates/price/latest?ids[]=<hex>…&parsed=true&encoding=hex|base64&channel=…`
  - `GET /v2/updates/price/stream?ids[]=<hex>…`: the **SSE stream**. Options: `parsed`, `encoding`, `allow_unordered`, `benchmarks_only`, `ignore_invalid_price_ids` and `channel`. "The connection will automatically close after 24 hours", so the client must reconnect.
  - `GET /v2/updates/price/{publish_time}/{interval}`: every update in a window of up to 60 s, at most 100 ids. Useful for backfilling a gap.
  - `GET /ws`: WebSocket in the legacy Hermes format.
  - `GET /v2/price_feeds?asset_type=fx|metal|commodities`: metadata. **This one is public and needs no key** (confirmed 200).
  - **`channel`** is one of `real_time`, `fixed_rate@50ms`, `fixed_rate@200ms` or `fixed_rate@1000ms`. **The default is `fixed_rate@1000ms`** [P4]. What a key may use depends on its plan.
- **Message shape** (one SSE `data:` line):

  ```json
  {"binary":{"encoding":"hex","data":["504e4155…"]},
   "parsed":[{"id":"<hex>","price":{"price":"<int string>","conf":"<int string>","expo":-5,"publish_time":<unix seconds>},
              "ema_price":{…same fields…},
              "metadata":{"slot":…,"proof_available_time":…,"prev_publish_time":…}}]}
  ```

  - Real price = `price × 10^expo`.
  - **`publish_time` is in whole seconds** [P2][P4], so a lead under one second must be timed with our own receive clock.
  - Pyth Pro's payload has `timestampUs` and `feedUpdateTimestamp` [P5].
- **Confirmed refusals without a key** (today, `fxlip/dl/pyth/`):

| Request | Result |
|---|---|
| `hermes.pyth.network/v2/updates/price/latest?ids[]=0xa995…` (EUR/USD) | **401** `unauthorized` (text/plain) |
| `hermes.pyth.network/v2/updates/price/stream?ids[]=0xa995…` | **401** `unauthorized` |
| `pyth.dourolabs.app/hermes/v2/updates/price/latest?…` | **401** `unauthorized` |
| `pyth.dourolabs.app/v1/real_time/history?symbol=FX.EUR/USD…` (Pro History API) | **401** "this request requires authorization" |
| `pyth-lazer.dourolabs.app/v1/latest_price` (Pro REST), `wss://pyth-lazer-0.dourolabs.app/v1/stream` | **403** "no token specified" |
| `benchmarks.pyth.network/v1/shims/tradingview/history` (the old free candles) | **404**. The forum lists "Pyth Benchmarks `/v1/shims/tradingview` Endpoints — Sunset August 26, 2026" [P8] |
| `hermes.pyth.network/v2/price_feeds?asset_type=fx`, `pyth.dourolabs.app/v1/symbols` | **200**: metadata stays public |

### 3.2 Feed IDs (Hermes hex ID / Pyth Pro numeric ID), from public metadata [P6][P7]

| Symbol | Hermes ID (hex) | Pro ID | expo | Pro `min_channel` | Kalshi rounding |
|---|---|---|---|---|---|
| `FX.EUR/USD` | `a995d00bb36a63cef7fd2c287dc105fc8f3d93779f062f09551b0af3e81ec30b` | 327 | −5 | `real_time` | 5 dp |
| `FX.GBP/USD` | `84c2dde9633d93d1bcad84e7dc41c9d56578b7ec52fabedc1f335d673df0a7c1` | 333 | −5 | `fixed_rate@200ms` | 5 dp |
| `FX.USD/JPY` | `ef2c98c804ba503c6a707e38be4dfbb16683775f195b091252bf24693042fd52` | 340 | −3 | `real_time` | 3 dp |
| `FX.AUD/USD` | `67a6f93030420c1c9e3fe37c1ab6b77966af82f995944a9fefce357a22854a80` | 315 | −5 | `real_time` | 5 dp |
| `FX.USD/CAD` | `3112b03a41c910ed446852aacf67118cb1bec67b2cd0b9a214c58cc0eaa2ecca` | 338 | −5 | `fixed_rate@200ms` | 5 dp |
| `Commodities.Index.CU/USD` ("COPPER 24/7") | `b2b238aeb6ef5a722c5cf278595bf40434e174cac4f88c8ad5b6f5009b548c59` | 3525 | −5 | `fixed_rate@50ms` | 5 dp |
| `Metal.XPT/USD` | `398e4bbc7cbf89d6648c21e08019d878967677753b3096799595c78f805a34e5` | 1781 | −3 | `fixed_rate@200ms` | 3 dp |
| `Metal.XPD/USD` | `80367e9664197f37d89a07a804dffd2101c479c7c4e8490501bc9d9e1e7f9021` | 1780 | −3 | `fixed_rate@200ms` | 3 dp |
| `Commodities.Index.NATGAS/USD` ("NATGAS 24/7") | `45f95717fbe158e896415d1cea33814d73e54169022a8f7bcbb815ebef92f71c` | 3265 | −5 | `fixed_rate@50ms` | 5 dp |

- **Why these are the right feeds:**
  - The exponents match Kalshi's `round_digits` in every row.
  - The Pro IDs for copper, natural gas, XPT and XPD match Kalshi's `pyth_value` table [K7].
  - Kalshi's series pages link the exact symbols for GBP/USD, copper, natural gas, XPT and XPD [K1].
  - Copper and natural gas are in the Pro group `pyth-indices` with `min_publishers: 1`. FX and metals need at least 3 publishers.

### 3.3 Update frequency

- **Hermes:** the default channel is `fixed_rate@1000ms`. Faster channels need the right plan [P4].
- **Pyth Pro streams FX** on `real_time` (EUR, JPY, AUD; "1–50ms") or at its fastest every 200 ms (GBP, CAD) [P5][P7]. This is Pro's minimum per feed.
- **Starter plan:** "Up to 1 second update frequency" [P9].
- **The free Kalshi series** is sampled at 1 s.

### 3.4 Plans and pricing (Pyth Terminal, `https://app.pyth.com/plans`, read today [P9])

| Plan | Price | API access | Speed | Coverage |
|---|---|---|---|---|
| Free | $0 | **No API access** (view only in Terminal) | 10 s | view all |
| Starter | **$500 a month** + tax | API key | up to 1 s | **"Access to all crypto symbols"** (no FX, metals or commodities) |
| Pro | **from $2,500 a month** + tax | API key | up to 1 ms | "Access to all symbols: Equities, futures, commodities, rates, crypto & more"; display and non-display rights |
| Pyth Indices / 24/7 | by quote ("Not self-service") | | | index feeds such as the copper and natural-gas 24/7 indices (UNVERIFIED whether Pro includes them) |

- **Bigger bundles:** Pyth's blog names a U.S. Equities plan at $5,000 a month and All Asset Classes at $10,000 a month [P10].
- **Free trial:** the docs promise a "free Pyth Pro API trial key … instantly, no credit card required" [P11], and the upgrade guide says "a free trial is included, paid plans cover ongoing use" [P1]. But Pyth's May 26, 2026 post says "API keys and production integrations require a paid plan" [P12]. **The trial's length and contents are not published (UNVERIFIED).**
- **Rate limits:**
  - Pyth Pro: "does not impose hard technical rate limits"; connections, feeds and channels are set by the service agreement [P13].
  - No limit per key is published for the upgraded Hermes. The old Core rate-limit page now redirects to the Pro page. One SSE connection for 9 IDs needs no request budget.
- **Do we need Pyth Pro (Lazer)?**
  - Only Pro gives timing under one second: `real_time`/200 ms channels, microsecond `timestampUs`, and three redundant endpoints `wss://pyth-lazer-{0,1,2}.dourolabs.app/v1/stream` with numeric IDs [P5].
  - The playbook's simulated edge needs **0.5 to 1.0 s** of warning. Starter (1 s, crypto only) cannot measure that, and neither can the free Kalshi series (1 s).
  - Pro costs at least $2,500 a month, and Kalshi's `pyth_value` costs $1,000 a month. Kalshi's feed carries millisecond Pyth timestamps plus Kalshi's own receive time, but its FX coverage is unconfirmed.

### 3.5 Owner signup steps (owner actions; the key never goes into chat or into the repo)

1. Open `https://pythdata.app/signup` (pythdata.app redirects to app.pyth.com) and create a Pyth Terminal account [P1][P14].
2. Before paying, take the **free Pro trial key**, if it is offered, and check in Terminal that it covers the asset types **fx** and **metal**, plus the copper and natural-gas index feeds, and how long it lasts. Pyth keys are limited by "asset types … minimum channel … optional specific feed IDs" [P15].
3. If paying: on `https://app.pyth.com/plans` choose **Pro (from $2,500 a month)**. **Do not choose Starter ($500)**: it is crypto-only at 1 s. For copper and natural gas, ask Pyth's team whether the indices are included (`data@dourolabs.xyz` [P1]).
4. In Terminal click **"🔑 View your API key"** [P14] and copy the key.
5. Set the key as the Railway variable `PYTH_API_KEY` on the read-only service **kalshi-recorder** (owner only).
6. Smoke test (send the key to Pyth hosts only):
   - `curl -H "Authorization: Bearer $PYTH_API_KEY" "https://pyth.dourolabs.app/hermes/v2/updates/price/latest?ids[]=0xa995d00b…c30b&channel=real_time"`
   - 200 means it works. 401 means a bad key. 403 means the plan is not entitled to this feed or channel.
- **Alternative:** Kalshi's own `pyth_value` 7-day trial (Stripe link above). This needs a Kalshi key; prefer one limited to `read`, and keep it off the recorder, which refuses keys.

## 4. Request budget

### 4.1 Today

- **The recorder:** one shared public limiter with at most 2 request starts in any rolling second, a 1.5 per second target, and lane weights books 8, trades 4, others ≤2 [R1].
- **The books lane** makes **one `/markets/orderbooks` call every second** (`book_interval_s = 1.0`).
  - Each call holds up to 100 tickers: KXBTC15M current and next, then the most overdue Family A candidates.
  - "the call happens anyway: spare slots refresh the soonest-due books for free" [R2].
  - So about 1.0 of the 1.5 requests a second is books, and the other 0.5 is trades, sweeps, discovery and fees.

### 4.2 Measurements (public, from this sandbox, Oct 13 23:46 to 00:01 UTC)

| Call | Result |
|---|---|
| `GET /markets/orderbooks?tickers=…` with the **14 LIP 15-minute tickers** (repeated `tickers=` form; a comma list returns 400) | 200, **18.3 to 18.7 KB**, 0.15 to 0.47 s total (TTFB about 0.15 s), full depth: FX 11 to 86 levels a side, Coin Race 0 to 20. **Not gzip-compressed**, even with `Accept-Encoding: gzip` (no `content-encoding`) |
| Same call with 100 other LIP tickers | 200, 37.6 KB, 0.17 s |
| 101 tickers | **400**: "Field validation for 'Tickers' failed on the 'max' tag". The documented cap is `maxItems: 100` [K15] |
| All active LIP markets | 5,631 programs on 5,631 distinct tickers: 14 are 15-minute, 10 hourly (Miami temperature), 1,374 daily, 4,233 longer. That is **57 calls** for one pass (about 2.1 MB) |
| `GET /incentive_programs?status=active&type=liquidity&limit=10000` | one page (`next_cursor: ""`), 5,631 rows, **2.15 MB raw / 288 to 298 KB gzip** (`content-encoding: gzip`), 0.32 to 0.59 s |
| `GET /live_data/events/{event}` (9 Pyth series) | 200, 114.7 to 117.5 KB each, 0.16 to 0.53 s, not compressed, `max-age=1` |
| Storage, if every LIP book changed every second | 1,320 B raw, **94 B gzip-in-stream** per book snapshot (14× compression over 84 snapshots), so at most 14 × 86,400 × 94 B ≈ **114 MB a day**; less in practice because books are written only when they change and FX is closed about a third of the week |
| Book depth needed for LIP scoring | 1 to 11 levels a side reach the Target. The full depth is still useful for fill and queue modelling |
| 429s | Seen at under 1 request a second on this sandbox's shared IP. Kalshi does not document limits for unauthenticated public requests, so the 2 requests a second is our own protocol ceiling |

### 4.3 Proposed cadence (one recorder, ≤ 2 requests a second)

| Lane | What | Cadence | Extra requests a second |
|---|---|---|---|
| books (existing call) | **Pin** the 14 current LIP 15-minute tickers into the existing 1 s call, next to KXBTC15M. In the 2 s around each :00/:15/:30/:45 boundary also pin the next window's 14. Optionally pin the 10 hourly KXTEMPMIAH reward strikes. That is at most 40 pinned slots; Family A candidates keep at least 60 of the 100 | **1 s**, the same rate Kalshi scores | **0** |
| trades (existing exchange-wide tape) | Add the LIP tickers to the watched set | 5 s | **0** |
| sweep / settlement (existing) | Add the LIP tickers. This brings `floor_strike`, `expiration_value`, `result` and `settlement_ts` | 5 / 15 min | **0** |
| incentives (new, `other` lane) | `status=active&type=liquidity&limit=10000` every 15 min; `status=upcoming` hourly; `status=paid_out` daily, to measure the pay lag | 15 min | **≈0.0013** |
| settlement series (new; add `/live_data/events/{t}` to `PUBLIC_PATHS`) | 9 Pyth series × one call each. Each call returns the trailing 3,600 s at 1 s, so every 10 min gives 6× overlap and no gaps | 10 min | **0.015** |
| Pyth SSE (when the key exists) | One Hermes SSE connection for the 9 IDs. It is a separate host and does not count toward Kalshi's budget. Reconnect every 24 h | stream | 0 (Kalshi) |
| **Total** | | | **≈1.5 + 0.017 ≈ 1.52 requests a second** |

**Trade-offs and limits:**

- **Family A pays in spare slots, not requests.**
  - The spare-slot refresh drops from 98 to 60 to 84 slots a second.
  - The guaranteed 20 s / 60 s candidate cadence holds while (fast candidates ÷ 20) + (slow ÷ 60) ≤ about 60 a second, for example up to about 1,200 fast candidates.
  - The current candidate count must be read from the recorder's `status.json` (UNVERIFIED here).
- **One sample a second is not Kalshi's random scoring instant.** Changes within a second are invisible, and REST books carry no exchange sequence number. The playbook's "about twice a second" would need a second book call (+1.0 request a second, 2.5 total), which breaks the 2.0 ceiling. Two a second is possible only with a separate IP and budget, or the authenticated `orderbook_delta` WebSocket. The docs call that channel private, so it needs a Kalshi key [K8].
- **Storage.** LIP books add up to about 114 MB a day, or about 1.6 GB per 2 weeks. That competes with the 5 GB volume Family A needs (about 4.5 GB, `docs/KALSHI_RECORDER.md` §6). The owner must choose: a larger cap or second volume, or a separate retention rule for the LIP lane.
- **A separate service is an alternative.** It would have its own limiter, a 1 s LIP call of up to 100 tickers, and the Pyth stream. But whether Railway services share an outbound IP is UNVERIFIED. If they do, the two budgets add up to 2.5 requests a second, over the ceiling. Pinning inside the existing call is the safe choice.
- **Rewards on daily and weekly markets** (5,600 markets) cannot be sampled at 1 s. A full pass in the spare 0.45 requests a second takes about 127 s. Sample only a chosen subset at 60 to 300 s, if at all.

## 5. Unverified items to settle next

1. Whether Kalshi's `pyth_value` carries FX symbols (check `underlying_list` in the 7 free days), and whether a key limited to `read` can open it.
2. The Pyth free trial's length and entitlements; whether Pro includes the `Commodities.Index.*` feeds; Hermes rate limits per key after the upgrade.
3. How far the free Kalshi 1 s series lags Pyth's real-time price. The newest point arrives within about 1 s of the wall clock, but its lag behind Pyth needs a Pyth key to measure.
4. The count of Family A candidates competing for book slots, and whether Railway services share an outbound IP.
5. Whether reward payouts land as withdrawable cash (carried over from PLAYBOOK §1.9).

## Sources

Kalshi (fetched Oct 13, 2026; local copies under `fxlip/dl/docs/`, `fxlip/dl/kalshi/`, `fxlip/dl/terms/`)
- [K1] `GET https://api.elections.kalshi.com/trade-api/v2/series/{KXEURUSD15M,KXGBPUSD15M,KXUSDJPY15M,KXAUDUSD15M,KXUSDCAD15M,KXCOPPER15M,KXPLATINUM15M,KXPALLADIUM15M,KXNATGAS15M,KXCRYPTOLEAD15M}`: `fxlip/dl/kalshi/series_*.json`
- [K2] `GET /trade-api/v2/incentive_programs?status=active&type=liquidity&limit=10000`: `fxlip/dl/kalshi/ip_active.json.gz`; schema at https://docs.kalshi.com/api-reference/incentive-programs/get-incentives.md
- [K3] `GET /trade-api/v2/markets?series_ticker=…&min_close_ts=…&max_close_ts=…`: `fxlip/dl/kalshi/rec_*.json` (rules text, strikes, settlement values, results, `settlement_ts`)
- [K4] Series `fee_type` definition: https://docs.kalshi.com/api-reference/market/get-series.md (copy: `kalshi_rewards/rules/dl_docs/api-reference_market_get-series.md`)
- [K5] https://docs.kalshi.com/getting_started/maintenance_and_pauses.md
- [K6] `GET /trade-api/v2/exchange/schedule`: `kalshi_rewards/rules/dl_api/exchange_schedule.json`
- [K7] Pyth Value Feed: https://docs.kalshi.com/websockets/pyth-value.md
- [K8] https://docs.kalshi.com/getting_started/quick_start_websockets.md
- [K9] Changelog (Jul 23, 2026 `pyth_value`; Jul 30, 2026 `/live_data/events`): https://docs.kalshi.com/changelog/index.md
- [K10] https://docs.kalshi.com/websockets/websocket-connection.md (connection auth; error codes 25 to 28)
- [K11] API key scopes: https://docs.kalshi.com/api-reference/api-keys/generate-api-key.md
- [K12] https://docs.kalshi.com/getting_started/rate_limits.md
- [K13] https://docs.kalshi.com/websockets/cfbenchmarks-value.md
- [K14] https://docs.kalshi.com/api-reference/live-data/get-event-live-data.md, and `GET /trade-api/v2/live_data/events/{event_ticker}`: `fxlip/dl/kalshi/live_*.json.gz`, `lp_*.json.gz`
- [K15] https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md; measured calls `fxlip/dl/kalshi/ob15_*.json`, `ob100.json`, `ob101.json`
- [T1] Contract terms and certifications: https://assets.kalshi.com/contract_terms/FXEURUSD.pdf (also FXGBPUSD15M, FXUSDJPY, FXAUDUSD, FXUSDCAD, COMMODITIES, CRYPTORETURNCOMPARE) and https://assets.kalshi.com/regulatory/product-certifications/*.pdf: `fxlip/dl/terms/`
- LIP snapshot rule ("a snapshot of the book … taken once for each second, with the exact time … drawn from a random uniform distribution"): CFTC filing rules07152610358, Appendix A, `kalshi_rewards/rules/dl_cftc/rules07152610358.txt` lines 123 to 129
- Reward-window history: `kalshi_rewards/history/dl_ip/rows_liquidity_*.tsv`

Pyth (fetched Oct 13, 2026; local copies under `fxlip/dl/pyth/`)
- [P1] https://docs.pyth.network/price-feeds/core/upgrade/preparing.mdx
- [P2] https://docs.pyth.network/llms-price-feeds-core.txt and https://docs.pyth.network/price-feeds/core/fetch-price-updates.mdx
- [P3] https://docs.pyth.network/price-feeds/core/upgrade/how-it-works.mdx
- [P4] Hermes OpenAPI: https://pyth.dourolabs.app/docs/hermes/openapi.json (`openapi_hermes.json`)
- [P5] https://docs.pyth.network/llms-price-feeds-pro.txt
- [P6] `GET https://hermes.pyth.network/v2/price_feeds?asset_type={fx,metal,commodities}` (public): `hermes_feeds_*.json`
- [P7] `GET https://pyth.dourolabs.app/v1/symbols` (public, 5.2 MB, not kept); fields `pyth_lazer_id`, `hermes_id`, `exponent`, `min_channel`, `schedule`
- [P8] https://dev-forum.pyth.network/c/announcements/7 (list of titles)
- [P9] https://app.pyth.com/plans (`plans.html.gz`)
- [P10] https://www.pyth.network/blog/extended-hours-us-equity-data-moves-to-pyth-pro
- [P11] https://docs.pyth.network/price-feeds/pro/pyth-terminal.mdx
- [P12] https://pyth.substack.com/p/api-access-is-changing (May 26, 2026; `substack_api.html.gz`)
- [P13] https://docs.pyth.network/price-feeds/pro/rate-limits.mdx
- [P14] https://docs.pyth.network/price-feeds/pro/acquire-api-key.mdx
- [P15] https://docs.pyth.network/price-feeds/pro/faq.mdx

Repository (read with `git show`, no worktree)
- [R1] `origin/claude/kalshi-recorder:docs/KALSHI_RECORDER.md` §3 and `src/nightcrawler/kalshi_public.py` (`RATE_CEILING_PER_S = 2.0`, `PUBLIC_PATHS`)
- [R2] `origin/claude/kalshi-recorder:src/nightcrawler/kalshi_recorder.py` (`BOOKS_PER_CALL = 100`, `book_interval_s = 1.0`, `_plan_books`)
- `origin/claude/nightcrawler-memecoin-bot-Gwnb1S:research/kalshi_rewards/PLAYBOOK.md` and `src/nightcrawler/kalshi_arena.py`. The local `claude/nightcrawler-memecoin-bot-Gwnb1S` branch is stale and lacks both; read `origin/`.


---
## result 1 

I built the analyzer and the practice desk and committed them locally as **SHA `ff852eb`**, on top of a pre-registration commit `0e76c7b`, on branch `claude/kalshi-lip-practice`. Nothing was pushed or merged, and no Railway setting was touched. There is still no Pyth data (no key yet), so the question of whether Pyth gives us a 0.5-second head start is still unanswered. The analyzer and the Pyth policy have only been run on made-up test data.

**Checks:** 108 new tests. Full suite: 5,052 passed, 13 skipped. mypy on `src` is clean (125 files) and ruff is clean on every changed Python file. Diff: 18 files, about 6,670 lines added.

**What was built:**
- **The test rules, written first.** `research/kalshi_rewards/PREREG.md` was committed on its own before any analysis code existed. It fixes the definitions, the split by trading day (2 days to explore, 2 to confirm, 4 for a single final test) and the pass bar:
  - **CONTINUE** if, in at least half of Kalshi's price changes (counting the 95% range's low end), the old price was still showing 0.5 s after we got the Pyth move. This only earns the next test; it does not justify real money.
  - **STOP** if that share's high end is under 25% on a Pyth feed that updates at least every 250 ms.
  - **MARGINAL** otherwise; FX rewards real money stays off.
- **One rule change after the fact.** While testing, I found the Pyth policy would put a pulled order straight back into the same stale price on the next book check. I changed it (it now waits for a book that shows the move, or 5 s) and recorded this as dated addendum 1. No practice result existed at that point.
- **The analyzer** (`research/kalshi_rewards/leadlag.py`) implements those rules. Kalshi's free 1-second price series can be run through it for a quick look, but by the rules it can never decide anything.
- **The practice desk** (`src/nightcrawler/lip_*.py`): four policies (rest at the Reference price, the same to the close, rest at the best bid, and pull-when-Pyth-moves) under two fill models, plus $45 and $250 practice accounts that carry cash between windows, and a daily scorecard with 95% ranges.
- **It matches the earlier simulation exactly.** Across all 654 recorded window, policy and fill-model cases it gives the same numbers as the rewards research's simulator: FX Reference to the close loses $6.785 a period, the playbook's -$6.79. The playbook's worked example pays $1.90, as it should.
- **Isolation:** the desk has no order path, no client, no key and no network connection, and a test checks the source for these. It runs in its own child process with only PATH, LANG and TZ in its environment (checked on a real process), at the lowest CPU priority, and refuses to start next to trading keys.
- **Page data:** a new top-level key `kalshi_lip_practice` on the page feed, a sample file for Codex (`tests/fixtures/kalshi_lip_practice_page.json`), and the field-by-field contract in `docs/COORDINATION.md`. No Codex town files were touched.

**What's live vs off:** nothing is live. The desk is off by default (`KALSHI_LIP_PRACTICE_ENABLED=false`, its own setting; `config.py` untouched), and the page shows "off". The only shared code changed is the page builder, which adds the new key, and a one-line change to the page-size test so the new block gets its own size allowance like the other desk reports.

**Before any of this can run for real:**
- **Recorder formats.** The desk reads the recorder's LIP files in the formats on the in-progress `claude/kalshi-recorder-fx` branch (Build A). They need re-checking when that branch merges.
- **Where it runs.** The desk is only useful beside the recorder, on the `kalshi-recorder` service. The bot's page reads the panel from the bot's own disk, so on the bot it will show off or missing until they share a disk. Owner decision.
- **The Pyth key.** The final test needs a Pyth feed that updates at least every 250 ms to be able to say STOP.

Files are in `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/fxlip/desk/`:
- research/kalshi_rewards/PREREG.md
- research/kalshi_rewards/PREREG.sha256
- research/kalshi_rewards/leadlag.py
- src/nightcrawler/lip_score.py
- src/nightcrawler/lip_feed.py
- src/nightcrawler/lip_desk.py
- src/nightcrawler/lip_practice.py
- src/nightcrawler/pagestate.py
- tests/fixtures/lip_desk_window.json.gz
- tests/fixtures/kalshi_lip_practice_page.json
- docs/COORDINATION.md
- docs/WORKLOG.md


---
## result 2 

The LIP lane and the Pyth lane are built and committed locally as `d295391` on branch `claude/kalshi-recorder-fx`. Nothing was pushed or merged, and no Railway setting was touched. The full suite passed (5094 passed, 12 skipped), mypy is clean on all of `src`, and ruff is clean on the changed files. The Pyth lane has not been run against real Hermes, because there is no key yet.

**What changed:** 11 files, +2197/−90, all under `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/fxlip/rec/`.
- **New modules and tests:** `src/nightcrawler/kalshi_recorder_pyth.py`, `tests/test_kalshi_recorder_lip.py` (16 tests) and `tests/test_kalshi_recorder_pyth.py` (12 tests).
- **Edited:** `kalshi_recorder.py`, `kalshi_public.py`, `kalshi_recorder_store.py`, `test_kalshi_public.py` (+2 tests), `test_kalshi_recorder_no_orders.py` (now also checks the Pyth module), `test_kalshi_recorder_faults.py` (one test helper fixed), `docs/KALSHI_RECORDER.md` (new section 9) and `.env.example`.
- **Base:** I rebased the empty branch onto 0713e41, which was pushed after the worktree was created.

**Measured live** (public Kalshi only, from this sandbox's shared IP, 2026-10-14 00:52–00:58 UTC, no Pyth key):
- **Request rate:** 528 GETs in 359 s, which is 1.47 per second. At most 2 started in any rolling second, and there was one 429.
- **LIP book call:** all 14 markets every call (5 FX, copper, platinum, palladium, natural gas, 5 Coin Race), none missing. The gap between calls was p50 1.000 s, p95 1.003 s, max 1.15 s.
- **Before my limiter fix,** a run at 00:39–00:45 showed the same call every 2.67 s (p50). The existing books lane was never really running at 1 s: fixed spacing at 1.5 requests a second plus round trips stretched it.
- **Other lanes kept running:** trades 0.27/s, discovery 0.14/s, the LIP lane's own calls 0.033/s. That is about 0.017/s once the start-up pulls are done.
- **Program list:** active had 5,663 rows on one page (2.28 MB uncompressed); upcoming had 2,747.
- **Free 1 s settlement series:** 9 series came back with 3,600 points each. Coin Race returns 404, so it is skipped for a day at a time.
- **Book changes:** 89% of LIP book reads were a changed book.

**Estimated disk use (compressed):**

| Lane | Per day |
|---|---|
| LIP books | about 140 MB on a full weekday, about 110 MB averaged over a week (129 bytes per changed book) |
| LIP prints | about 15–25 MB (17.6 measured) |
| Program snapshots, call rows, settlement series | about 10 MB |
| Pyth | about 7 MB at 1 update a second per feed, 30 MB at 5, 110 MB at 20 |

The LIP lanes add about 150–200 MB a day before Pyth, or 2–3 GB over their 14-day retention. Side effect: KXBTC15M books are now recorded about 2.7 times as often, because the book call really runs every second.

**Decisions you or the owner should check:**
1. **Shared rate limiter changed.** It is now a token bucket. With a burst of 1 (the default, and in-bot) it behaves exactly as before; the old limiter tests pass unchanged. The recorder uses a burst of 2 only when the LIP lane is on. The 2-per-rolling-second ceiling and the 1.5/s average are unchanged; two requests can now start 0.5 s apart.
2. **Scheduling priority.** A due book call carrying LIP books goes first. Any other request that would make that call more than 0.1 s late waits. Both are counted per lane and written once a minute, along with Family A books pushed out of a call and any LIP markets dropped over the 40-market cap.
3. **New allowlisted path.** I added `/live_data/events/{event}` to `PUBLIC_PATHS`. It is public and keyless, only the LIP lane reads it, but it is outside the list in PROTOCOL.md section 2.1.
4. **Family A refresh floor.** Spare slots now refresh a Family A candidate at most every 5 s. This only matters when the candidate list is short; it stops 1 s calls from re-reading every candidate every second.
5. **Storage policy.** LIP and Pyth data are shed above 95% of the cap and deleted past 14 days only when room is needed, so Family A is never paused sooner because of them. With roughly 1 GB a day already on a 5 GB volume, the owner needs to choose: a bigger volume or cap, a shorter `KALSHI_RECORDER_LIP_RETENTION_H`, or `KALSHI_RECORDER_LIP=false`.
6. **LIP is on by default.** Merging this into `claude/kalshi-recorder`, which auto-deploys to Railway, starts LIP recording at once.
7. **One existing test changed.** The 403-burst sweep test assumed the sweep lane's backoff ended within 100 steps. It now waits for its pass to start.
8. **Pyth key handling.** The key is read only from the environment, never from `.env`. It is sent only in the Authorization header to `pyth.dourolabs.app/hermes` or `hermes.pyth.network`. A test with a server and error messages that echo the key confirms it never appears in any written byte or log record. The trading-key guard lets `PYTH_API_KEY` through, also tested. Without the key the lane is off, with exactly one info line.
9. **Not done:** I did not add a WORKLOG entry, to avoid merge conflicts. The 401 / 403-step-down / 24-hour-reconnect handling is built from Pyth's docs and is unproven until the owner sets `PYTH_API_KEY` on `kalshi-recorder`.

Scratch is cleaned up. Everything left is in `fxlip/scripts`: `smoke_stats.py`, `pyth_bytes.py` and `smoke_run2.log`.

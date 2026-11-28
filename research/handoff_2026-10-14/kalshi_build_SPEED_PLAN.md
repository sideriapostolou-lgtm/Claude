# Kalshi BTC bot: 10x speed build plan (Tue Oct 13, 2026, written 11:25 AM PT)

## 0. Bottom line

- **Speed:** a Coinbase trade reaches a Kalshi order ack in a median **879 ms** per order (p10 464, p90 1,915; 7:50 to 9:40 AM PT). The bot learns about its own fills **1.9 to 2.9 s** late. A reprice leaves no bid on the book for **1.0 to 1.7 s**. After a new order, the bot cannot cancel it for **0.8 to 1.5 s**.
- **10x is reachable where the losses happen.** That means the cancel blackout (goes to 0), fill knowledge (10 to 100x), reprice (7 to 15x), and the stale-quote cancel path (6x normally, 10 to 20x on a fresh order).
- **10x is not reachable on trade-to-new-order-ack.** The realistic target is 5 to 7x. Three things set the floor: Kalshi's own send-to-ack floor (27 to 30 ms or less), the Virginia-to-Ohio hop (about 19 ms), and the safety fsync before each send (35 to 60 ms), which should stay.
- **Money:** speed alone shows no P&L effect we can detect. For 50 vs 500 ms the strict fill model gives +9.7 c/window (t 0.47) and the touch model gives -35.8 c (t -1.92). With 90 windows, nothing under about 40 to 45 c/window is detectable. What speed does measurably improve is fill quality in the first 0 to 10 s, worth +15 to 20 c/window (t 2.3 to 4.9), and that gain fades to about 0 by 30 to 60 s. Build speed to cut adverse fills and tail risk. Do not expect it to make the rule profitable by itself.
- **Today's money (real):** -$4.41 after the 11:00 to 11:15 AM window, over 50 windows (-8.8 c/window). **About $1.59 is left before the $6 daily stop**, which resets at **5:00 PM PT**. Lifetime is about -$3.35 against the $10 stop.

## 1. The most recent losses (pulled from Railway just now)

| Window (PT) | Result |
|---|---|
| 9:00 to 9:15 AM | -$1.86 |
| 9:15 to 9:30 AM | -$2.98 |
| 9:30 to 9:45 AM | $0.00 |
| 9:45 to 10:00 AM | +$1.60 |
| 10:00 to 10:15 AM | +$1.09 |
| **10:15 to 10:30 AM** | **-$1.70** |
| 10:30 to 10:45 AM | +$0.26 |
| 10:45 to 11:00 AM | +$0.02 |
| **11:00 to 11:15 AM** (newest) | **-$1.75** |

Whole day so far: 966 maker orders, 109 maker fills (11.3%), 33 locks, locked pairs +$5.75, unpaired direction -$8.41, fees $1.06.

**Newest loss, 11:00 to 11:15 AM (KXBTC15M-26OCT131415): no speed could have saved it.**

1. At 11:01:38.48 AM the bot rested **Down 5 @ 0.38** (fair 0.418). Kalshi acked it 0.46 s later.
2. At 11:01:43.23 to 43.37 AM, 4.3 s after the ack, one taker took all 5 contracts in 7 fills over 143 ms.
3. Binance BTCUSDT was flat at $83,100.00 to $83,100.01 from 11:01:36.5 to 11:01:43.5. It first rose at 11:01:44.0 (+$1.48), then +$13.85 by 11:01:45.0 and +$21 by 11:01:48. **The Kalshi taker bought 0.8 to 1.8 s before spot moved.**
4. The bot booked the fill at 11:01:44.31. At that moment its Up fair was still 0.582; it reached 0.636 by 11:01:50.8. The bot's Up bids at 0.55 to 0.61 never filled.
5. The 0.99 pair cap (Up at 0.61 or less) stopped quoting at about 11:03 AM.
6. At 11:11:08 AM the lock bought Up 5 @ 0.968. A pair cost $1.348, so the window lost $1.75. Up won.

The 5-contract first buy (PR #35) was live in this window. At the old 10 contracts it would have lost about $3.50.

**10:15 to 10:30 AM (131330): this one was a race, and it happened inside the blackout.**

1. At 10:15:33.59 AM the bot rested **Down 10 @ 0.33** (fair 0.369).
2. Binance buyers lifted the price +$6.6 at 10:15:34.613. Kalshi Down 10 was taken at 10:15:34.673: **60 ms after Binance moved, and 1.09 s after the bot decided.** At that point the order was still inside the window where the bot cannot cancel it.
3. The bot did not see the fill until about 10:15:39.5 (4.8 s later). By then Up fair was 0.687.
4. Up 4 @ 0.65 filled at 10:18:57. The remaining 6 were locked at 0.958 to 0.965 at 10:26. The window lost $1.70.

Today's bot had no chance on this one. A 10x bot would be at best a coin flip.

**Lesson.** Of the two newest losses, one was a sub-100 ms race that a 10x bot might win about half the time. The other was an informed or momentum taker that no public feed could warn about. (Caveat: these use Binance time as a stand-in for Coinbase, with about tens of ms of clock uncertainty.)

## 2. Latency budget, hop by hop

"Today" comes from real Kalshi orders. "Target" is after steps 0 to 8.

| Hop | Today, median (p90) | Target | Speed-up | 10x possible? |
|---|---|---|---|---|
| Coinbase trade stamp to our socket | 126 ms (p90 343); Advanced Trade batching adds 50 to 61 ms of this | about 40 to 70 ms on the Exchange feed | 2 to 3x | **No.** Coinbase publish time and clock skew (about ±35 ms) are not ours to fix. |
| Receipt to decision | 378 ms (p90 1,203) | 5 to 10 ms after the triggering tick | 40x on the metric, but data is only 80 to 190 ms fresher | Yes on the metric. About 200 ms of today's figure is just the gap between ticks. |
| Pre-send durable save | 97 ms (p90 211, max 472) | 35 to 60 ms (one small row, still fsync'd) | 2 to 3x | **No.** The fsync floor of 33 to 60 ms stays on purpose. |
| Hand-off (thread, budget, signing, guard) | 7.8 ms (p90 37) | about 1 ms | 8x | Yes |
| Send to ack | 122 ms (p10 50, p90 558; minimum 27 to 30) | about 40 to 60 ms | 2 to 3x | **No.** Kalshi's floor is 27 to 30 ms or less. About 95 ms of excess has an unknown cause until we log the venue's reply time. |
| Fill seen by the bot | 1.9 to 2.9 s (p90 3.3 to 4.3 s) | about 20 to 200 ms (Kalshi push delay not measured) | 10 to 100x | Yes |
| Reprice (old quote off, new quote live) | 1.0 to 1.7 s (p90 up to 7.5 s) | 0.1 to 0.25 s with amend | 7 to 15x | Yes |
| Post-create blackout (cannot cancel a new order) | 0.8 to 1.5 s | 0 | no longer exists | Yes |
| Stale-quote cancel, Coinbase move to cancel landing (estimate; cancels are not timed) | about 715 ms, or 1.5 to 2.2 s on a fresh order | about 115 to 135 ms | 6x, or 10 to 20x on a fresh order | Mostly |
| **Whole path, trade to new-order ack** | **879 ms (p10 464, p90 1,915)** | **150 to 195 ms** (115 to 135 ms if the owner accepts an overlapped fsync) | **5 to 7x** | **No:** fsync plus Kalshi floor plus Coinbase stamp |

Fixed costs no build removes:
- Kalshi's processing floor (27 to 30 ms or less).
- Railway Virginia to Kalshi Ohio, about 19 ms. Railway has no Ohio region.
- Kalshi's push delay for fills (unpublished).
- Coinbase's time from match to publish.
- Kalshi takers who trade 0 to 100 ms after a move. Their excess flow peaks there; a 50 ms bot beats about a third of a sweep.
- Takers who know before spot moves, as in the newest loss.

## 3. Build steps, in order

Effort: S is a day or less, M is 2 to 4 days, L is 1 to 2 weeks. "Safety" means the $10/window, $20 open, $6 day and $10 lifetime caps stay exact.

**Step 0. Measure first. S. Ship to real money now.**
- **Files:** `speeddesk_live.py` (`_submit`, `_cancel`, `step`, `_reconcile`).
- **Changes:**
  - Log the venue `ts_ms` from create and cancel replies. The client already checks it but never records it.
  - Log per-GET time, size and page count inside `_reconcile`.
  - Log time spent in each phase of `step()` (`_cancel_unsafe`, `_reconcile`, `_lock`, `_decide`).
  - Add an event-loop lag probe (a 10 ms timer that measures oversleep).
  - Log decision-to-ack time for cancels.
  - Log the Railway clock offset against Coinbase `/time` and Kalshi.
- **ms saved:** 0. This splits the 95 ms of unexplained send-to-ack and sizes everything below.
- **Money:** none. **Safety:** logging only.
- **Tests:** the new record fields exist and the metrics parser accepts them.

**Step 1. Stop downloading the whole order history. S. Ship to real money now.**
- **Files:** `speeddesk_kalshi_client.list_orders` (add `event_ticker`, `min_ts`, `status`) and `speeddesk_live._reconcile`.
- **Changes:**
  - Orders: filter by the event tickers of every window open for trading, plus `status=resting`.
  - Fills: filter by ticker list, with `min_ts` = last booked fill minus 10 s.
  - Keep one unfiltered scan at startup and every 60 s, so untracked `nc-speed-` orders and owner orders are still caught.
  - Before relying on it, confirm whether `min_ts` filters on creation time or update time.
- **ms saved:** the live connection downloads about 0.5 MB/s today; this goes to a few KB. Reconcile time is estimated to fall from 0.8 to 1.5 s to 250 to 500 ms; step 0 will confirm.
- **Money:** none detectable. It removes some of the "account data stale" pauses (about 18% of heartbeats; roughly half of those are by design right after an order).
- **Safety:** read-only change. Startup cancels and reconciles every older intent before trading, so the filter cannot hide tracked orders.
- **Tests:** the fake client checks filter parameters; a late fill outside the filter is caught by the 60 s scan; an owner order in a new window is seen before the bot's first order there.

**Step 2. Small durable intent row; full saves off the critical path. M. Ship to real money after crash tests pass.**
- **Files:** `speeddesk_live.py` (`checkpoint`, `_send`, `_send_lock`, `_cancel`, `_heartbeat`), `ledger.py` (append API), `speeddesk.py` (`_atomic_json`, practice ledger).
- **Changes:**
  - Before each send, write one row with `synchronous=FULL`: `client_order_id`, window, side, price, count, and worst-case reservation including the taker fee.
  - Save the full state at most once a second and after fills. Drop `panel()` and `_daily_reports` from the per-order save.
  - Drop both synchronous saves in `_cancel`.
  - Set the practice runner's ledger to NORMAL with no fsync on its mirror file.
  - Add a release path for a durable intent that never reached Kalshi. Today that case is stuck forever in "Reconciling startup orders".
- **ms saved:**
  - Pre-send save: 97 ms to 35 to 60 ms.
  - Before each cancel: about 91 ms to 0.
  - Loop blocking: about 0.5 s per reprice cycle goes away (6 to 8 saves of 51 to 439 ms each).
- **Money:** none detectable.
- **Safety:** the fsync before every create stays, so the guarantee after a host crash is unchanged. A cancel only lowers exposure, and the reservation is held until Kalshi confirms.
- **Tests:**
  - Kill the process between the row write and the send.
  - Kill it after the send but before the ack.
  - Replaying the journal plus the last snapshot must equal today's checkpoint.
  - A property test that stop math is identical across restarts.

**Step 3. Make the Bitcoin tape O(1) and fix the sigma cache. S. Ship to real money now.**
- **Files:** `speeddesk_model.BitcoinTape.tick` and `sigma`; `speeddesk._live_sigma` cache key (it includes `_bitcoin_revision`).
- **ms saved:** 1.6 to 1.7 ms per trade, which runs twice (practice desk and live twin). That is about 7 ms/s now and up to 170 ms/s in a 100 trades/s burst.
- **Money:** none. **Safety:** unaffected.
- **Tests:** output matches the current code on a recorded tape, including late ticks that revise the same second or the previous second.

**Step 4. Coinbase Exchange `matches` feed as the main Bitcoin source. S. Ship to real money after the clock check.**
- **Files:** `speeddesk_feeds._coinbase` and `coinbase_ticks` (today `COINBASE_WS` is Advanced Trade). Freshness gates: `speeddesk.py:209`, `speeddesk_live.py:480` and `:529`, `speeddesk_model.py:402`, `speeddesk_metrics.py:35`.
- **Changes:**
  - Keep Advanced Trade as a backup and dedupe by `trade_id` (same id space; 0 price mismatches in 4,280 shared trades).
  - Skip `last_match` and reconnect replays.
  - Add a second Exchange connection for failover.
- **Must fix first:** today the bot drops any tick stamped later than its own clock. The Exchange feed has no 50 to 100 ms batching to hide clock skew; on this container's clock 91% of Exchange ticks would be dropped. Judge freshness on local receipt time, or allow a bounded negative skew such as -250 ms.
- **ms saved:** 50 to 61 ms median (p90 about 92 to 107).
- **Money:** removes $0.35 to 0.60 of average price staleness (0.2 to 0.35 c of fair at 4 minutes left). In the fastest 10% of moves it is about $2 (1.2 c at 4 minutes, 2.5 c at 1 minute). No P&L test exists.
- **Safety:** caps unaffected. The stale-feed cancel must still fire.
- **Tests:** parser on recorded messages; a tick stamped 5 ms in the future is accepted; dedupe across both feeds.

**Step 5. Never gate cancels; decide on the tick; run reconcile as its own task. M. Practice twin first.**
- **Files:** `speeddesk_live.py` (`run`, `step`, `_decide`, `_waiting_reason`, `_reconcile`, `_submit` tail with `account_at=None`).
- **Changes:**
  - The reprice and cancel check runs on every tick wake and never waits for fresh account data. `_waiting_reason` then gates new buys only.
  - Reconcile runs as its own task. All changes to the risk book go through one writer queue, so there is still one serialized controller.
  - Stop forcing a full reconcile after every create. Keep that gate only for ambiguous outcomes: timeouts, 5xx errors, unconfirmed cancels.
  - The `cancel_requested` block on new orders also needs relaxing, using the cancel reply's `reduced_by` plus the retained reservation.
- **ms saved:** the 0.8 to 1.5 s blackout goes to 0; receipt-to-decision goes from 378 ms to 5 to 10 ms; reprice gap goes from 1.0 to 1.7 s to about 0.3 s.
- **Money:** this step targets fills like the 10:15 AM one. About 17% of maker-filled orders (14 of 81) filled while the bot could have cancelled them; the rest filled before the ack (no cancel could help) or long after.
  - Sim P&L, 50 vs 500 ms: +9.7 c (t 0.47) strict, -35.8 c (t -1.92) touch.
  - Sim P&L, 50 vs 1000 ms: +36.3 c (t 1.45) strict, -14.1 c (t -0.64) touch.
  - With the live loop's gating modelled: +4.0 c (t 0.15).
  - Fill value at 0 to 10 s: +15 to 20 c/window (t 2.3 to 4.9). Against the Kalshi mid at 1 s: +11.9 c (t 3.6).
- **Safety:** the caps stay exact only because every reservation is made before its send and released only on venue proof. Keep the per-side `order_pending` rule in `LiveRiskBook.can_buy` and the conservative cash rule (cash minus reserved minus debits, 5 s maximum age).
- **Tests:**
  - Fill arrives while a cancel is in flight.
  - Cancel returns 404 "not resting".
  - Reconcile and decide interleave under a deterministic scheduler.
  - Property test: no cap exceeded over 10,000 randomized event orders.
- **Risk:** medium-high.

**Step 6. Kalshi private websocket for fills and orders. M. Practice twin first.**
- **Files:** `speeddesk_kalshi_ws.py` (subscribe to `fill`, `user_orders`, `market_positions`), `speeddesk_live_model.record_fill` (idempotent on `trade_id`, which equals `fill_id`).
- **Changes:** REST stays the authority. Audit by REST every 5 to 10 s, after every reconnect, and before any settlement or terminal decision.
- **ms saved:** fill knowledge from 1.9 to 2.9 s to an estimated 20 to 200 ms.
- **Money:** none detectable. The tempting use, an instant taker hedge when a first buy fills, was already tested and loses. "Taker-complete whenever pair cost is 0.99 or less" changes P&L by -19.2 c/window (t -1.27) strict and -31.3 c (t -2.72) touch against the live rule. The websocket is for safety and stale-quote control, not a hedging hack.
- **Safety:** the fill channel has no sequence number, so it cannot prove nothing was missed. The websocket may only add inventory or reservations early, never release them.
- **Tests:** a fill seen on the websocket and then REST is counted once; a websocket gap is caught up by REST; reconnect; a fill on an unknown order still takes the existing untracked path.

**Step 7. Reprice with amend. M. Kalshi demo first, then practice twin.**
- **Files:** `speeddesk_kalshi_client` (new `amend_order` on POST `/portfolio/events/orders/{id}/amend`, with count = filled + remaining and an updated `client_order_id`), `_decide` reprice branch, re-terms in `speeddesk_live_model`.
- **Changes:**
  - The amend request has no `post_only` field and can cross the book. So amend only when the new price is below the best ask minus one tick at send-guard time; otherwise cancel and send a `post_only` create.
  - While an amend is unconfirmed, reserve the larger of the old and new terms at the taker fee.
  - Confirm through the order list or websocket, not the amend reply (Kalshi fixed amend reply bugs on May 21 and Sep 3).
- **ms saved:** reprice from 1.0 to 1.7 s to about 0.25 s (about 0.1 s after steps 2 and 5). Writes per reprice go from 2 to 1 (12 tokens to 10).
- **Money:** not in the sim. It removes the race where a reprice cancel hits an already-filled order (5 of 96 reprices today).
- **Tests:** an amend racing a fill; an upward amend refused when it would touch the ask.

**Step 8. Hosts and connections. S. Ship to real money now.**
- **Changes:**
  - Point the signed client's `BASE_URL` at `external-api.kalshi.com` (Kalshi's recommended host). Estimated 2 to 10 ms saved; not measured on Railway.
  - Send an explicit `exchange_index=2` read from market metadata, falling back to -1. This needs shard-2 collateral, so it ties to the shard-aware cash task.
  - Give each poller thread its own `requests.Session` (`speeddesk_kalshi._public_get`, `speeddesk_feeds._public_get`, `weatherwatch_markets`, `polydesk`, `skipwatch_alerts`). That removes about 9 to 13 new TLS connections per second.
  - Do not move the public poller to the new host before it has a Session; without one it would cost about 40 to 60 ms per call.

**Step 9. Run the real-money path in its own process. L. Practice twin first. Owner approves any extra Railway cost.**
- **Files:** `engine.py`, `speeddesk.py`, `speeddesk_live.py`.
- **Changes:** the feed, Kalshi websocket, decision and order client run alone. Everything else moves out: practice runner, twin, panel, coin desks, weatherwatch, dashboard. The ledger lock already prevents two controllers.
- **ms saved:** not quantified; this targets the tails (decision-to-ack p95 1,320 ms). Start it only after step 0 shows the send-to-ack excess is on our side.

**Step 10. Owner actions.**
- **Advanced API tier** (self-serve; the bot already qualifies). 0 ms today: the bot sends about 4 to 5 GETs/s against its own 10/s cap. Needed only for subaccounts.
- **Bot subaccount on shard 2.** Isolates the owner's trades and makes cancel-all safe at startup and shutdown. Requires Advanced tier and key actions by the owner.
- **FIX order entry, AWS Ohio hosting.** Last, and only if speed is ever shown to pay. The floor would go from about 27 ms to 5 to 15 ms per request.

## 4. Strategy changes

| Change | Evidence (c/window, t) | Verdict |
|---|---|---|
| Live rule as is | about -5 c in replay (SD about $2.1); -8.8 c real today | No detectable edge |
| 5-contract first buy (already live) | +5.3 c (t 0.32); worst window -$2.67 vs -$5.34; daily-stop odds 0.62 vs 0.76 | Keep |
| **Quote pulling:** pull all bids for 5 s after the quoted side's fair moves 1 c or more within 5 s | +28.1 c (t 1.14) strict, -8.7 c (t -0.38) touch; 60 s markout +24 to 28 c (t 1.4 to 1.7); 18% fewer fills; best of 68 rules tried, and noise alone would give a best t near 2.57 | **Practice twin only.** Pre-register it. About 250 windows (about 3 days) to detect +28 c at t 2. |
| Bitcoin price at the BRTI level: Coinbase + Kraken average, Kraken only as a slow basis term | Settlement error falls from $3.10 to $2.30 out of sample (t 4.0; all six 6-hour blocks positive); about 0.5 to 1 c of fair; no P&L test | **Practice twin first.** It is the one accuracy gain with strong evidence. |
| Cancel trigger from the Coinbase level2 book mid | Leads trade prints by 25 to 40 ms median, 134 to 187 ms mean, on $5 moves; 7.7 to 10.7% false alarms per quiet 4.5 s stretch, about 15 to 20 per window | Replay on Kalshi tapes, then the twin. Not real money now. |
| Kalshi taker-burst signal: the 11:01 AM sweep came 0.8 to 1.8 s before spot | Untested; Kalshi with-move prints run about 3x normal in the 100 ms before a Binance move | Test under the pending Kalshi-signals task |
| Momentum no-starter rules, vol-widening, one-side quoting, cancel-on-move at 0 c | 8 of 9 no-starter rules below 0 (best +8.0 c); cancel-on-move 0 c: -6.8 c strict, -39.1 c touch, 12x the orders | **Do not ship** |
| Instant taker hedge after the first buy fills | -19.2 c (t -1.27) strict, -31.3 c (t -2.72) touch | **Do not ship** |
| Lock tweaks (no lock; stop when pair cost is 1.10 or more after 10 minutes in) | +12.2 c (t 0.69) but worst window -$7.25; +8.5 c (t 0.64) | Noise; leave the lock alone |

**Shipping:**
- **Real money now:** steps 0, 1, 2, 3, 4 and 8. They do not change which orders go out.
- **Practice twin first, for 1 to 2 days (96 to 192 windows):** steps 5, 6, 7, quote pulling and the BRTI price. Check: zero cap breaches, zero integrity errors, latency, and 1 s and 10 s markouts.
- **No new strategy goes to real money today.**

## 5. What not to do

- **Do not drop the fsync before sends (the 2 to 5 ms option).** After a host crash, an order sent with no record comes back as an orphan. Its fills are treated as the owner's, so the $6 and $10 stops would miss up to one order's loss (up to $10).
- **Do not let writes run in parallel.** `_send_guard` and the budget wait rely on the client lock serializing every write.
- **Do not instant-hedge on a fill**, or ship momentum, vol or cancel-on-move-0 c rules. All tested flat or negative.
- **Do not raise caps or contract size because the bot got faster.** The scorecard says `cap_change_allowed` is false; speed is not an edge.
- **Do not move to AWS Ohio or FIX now.** At most 15 to 20 ms per request, large effort, and no money effect shown.
- **Do not use Binance.com feeds without a terms-of-service check**, because US persons are excluded. Do not put the bookTicker firehose (about 350 messages/s) on the shared event loop either.
- **Do not use cancel-all without a bot subaccount.** It hits the owner's orders and can cancel orders placed in the following minute.
- **Do not use order groups at clip 5.** A 25-contract limit never trips, and a limit of 5 trips on the first fill and blocks the hedge.
- **Do not spend time on** turning off websocket compression (0 ms), extra Advanced Trade connections (still 26 ms behind one Exchange connection), or Kraken, Bitstamp or Gemini as speed sources (150 to 200 ms late).
- **Do not judge sub-second ideas on the 1 s simulator.** Use `sim2` with `inflight=True` plus the live gating (`verify/sim3.py strict_gate`), and report 0 to 10 s markouts next to P&L.

Data and scripts: `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_speed/` (lanes), `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/recent_loss/dl/` (Binance trades around the two newest losses), `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_review/pairing/out/final.txt` and `/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/kalshi_guard/guards/out/guards.txt` (strategy tests).
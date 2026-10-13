# Kalshi Family A: favourite-side passive bids on slower markets (preregistered protocol)

Version `kalshi-familyA-v1`. Written 2026-10-13, finished about 18:53 UTC, by Claude on branch `claude/kalshi-family-a` (from deploy commit `c3ab6f8`). It implements sections 2-4 of [CLAUDE_PROMPT.md](CLAUDE_PROMPT.md) for Family A, plus the shared public-data recorder both families need. It is frozen when committed: its SHA-256 is in `PROTOCOL.sha256` (check with `cd research/kalshi_edge_search && sha256sum -c PROTOCOL.sha256`). Results, the selection file and the freeze file will live in `research/kalshi_edge_search/family_a/`.

**When this was written, nobody had computed a Family A return, no quote had been simulated, and the recorder did not exist.** Every rule below is fixed before any of the data it scores has been recorded.

This is research on public data. It sends no orders, uses no keys, changes no live setting, cap or trading code, and authorizes nothing live. Every dollar in it belongs to a **SIMULATED** research account.

## 0. What was seen before writing

- Codex's `REPORT.md` and `CLAUDE_PROMPT.md` (2026-10-13). The hypothesis comes from Bürgi, Deng and Whelan's Kalshi study: in 2021 to April 2025, makers buying at 50c or more averaged about +2.6% after the study's commissions (markets open at least 24 h, observed fills, no maker fee then). That is a lead, not an expected return for us.
- Claude's read-only pre-build audit, 2026-10-13 18:10-18:30 UTC (141 public requests, no key; its scripts and data are in the session scratchpad, not the repo). At 18:12 UTC it counted the markets passing this protocol's category and time rules: Crypto 710, Climate and Weather 672, Commodities 447, Financials 485 (2,314 markets in 151 events and 102 series). Of these, 1,108 were two-sided and 832 had a favourite mid of 0.50-0.95 (NO favourite 591, YES 241), and 506 of those had traded in the prior 24 h. It also measured median spreads (Crypto 7c, Weather 3c, Commodities 4c, Financials 10c), the median size already queued at the favourite's best bid (Crypto 500, Commodities 500, Weather 12, Financials 26), tick grids, request rates, 429 behaviour, trade rates and disk sizes.
- The audit looked only at best bids, asks and depth. It simulated no quote, joined no fill to any outcome and computed no return. It read the settlement fields of one finished weather market (KXHIGHNY-26OCT12-T76), only to check the status string; that market closed before any phase below starts.
- The round-number thresholds in sections 4 and 5 (spread, volume, ages, time-outs) were chosen with those structural counts in view, never from a return. The four variants and both price bands are taken unchanged from `CLAUDE_PROMPT.md`.
- Codex's 12 crypto 15-minute book snapshots (`book_sample/`) and incentive snapshot (5,462 programs, none on KXBTC15M) were also read. Neither says anything about Family A outcomes.

## 1. The question

Can a one-contract passive bid on the favourite side of slower Kalshi markets, in the categories this account may trade, earn positive net dollars per calendar day at a $25 simulated bank? The net must be after fees, after counting only the fills we could really have had in the queue, with cash locked until settlement, every loss, and operating costs.

- Null hypothesis: net dollars per calendar day ≤ 0. Alternative: > 0. One-sided.
- Not claimed: that this reproduces the study's sample, that either band has an edge, or that a positive result would last. Family A tests four fixed variants once. It does not search for new ones.

## 2. Safety and isolation

1. Only public, unauthenticated GET requests, to these paths under `https://api.elections.kalshi.com/trade-api/v2`: `/events`, `/series`, `/series/{ticker}`, `/series/fee_changes`, `/events/fee_changes`, `/markets`, `/markets/{ticker}`, `/markets/orderbooks`, `/markets/{ticker}/orderbook`, `/markets/trades`, `/historical/cutoff`, `/historical/markets`, `/historical/trades` and `/incentive_programs`. No key, no signer, no websocket (Kalshi's market websocket needs a key).
2. The recorder and replay code contain no order create, cancel or amend call. They import no order, portfolio or account client (`speeddesk_kalshi_client`, `speeddesk_live*`, `polymarket_us`, `broker/`). An automated test fails if any such import, any non-GET method, or any `/portfolio` or order path is reachable. Fakes are used only inside automated tests.
3. The recorder is its own module and entry point (planned: `python -m nightcrawler.kalshi_recorder`). It can run as a separate process or service, and its engine hook is OFF by default. All its public polling stays at or below 2 requests per second in total, with backoff on 429. Its data live under `DATA_DIR/kalshi_recorder/`, in rotating compressed files with a configurable cap (default 2 GB).
4. No live setting, cap, mode, credential or line of trading code changes. The limits in section 6 are simulated and never replace the live account's limits. Simulated results are never shown as real money and never added to the town's real totals.
5. The recommended host is a separate small Railway service with its own volume, because the bot's IP and volume are already busy (audit sections 4-5). Any new paid service, volume or region is a proposal for the owner. This protocol does not authorize one.
6. No verdict here turns anything live. `QUALIFIED FOR OWNER-REVIEWED LIVE PROPOSAL` means only that a proposal may be written. A live trial needs the owner's fresh, exact amounts and scope.

## 3. What the recorder records for Family A

**Candidates (what gets polled).** Markets in the four open categories (rule U1 in section 4.1) that are binary, are scheduled to last at least 24 h, and close between 5 hours and 8 days from now. This is wider than section 4's 6 h-7 d window, so the 24 hours before a market enters the window are already on tape.

**Lanes.** The cadences below are targets. Scoring depends only on the coverage rules in section 12. The total is at most 2.0 requests per second, aiming at about 1.5 on average.

| Lane | Request | Target cadence |
|---|---|---|
| Books | `/markets/orderbooks?tickers=...` (up to 100 tickers per call). Every call also carries the current and next KXBTC15M (section 16). | Every candidate at least every 60 s. Candidates whose last favourite mid is in 0.45-0.97 at least every 20 s. |
| Trades | `/markets/trades` exchange-wide. `min_ts` overlaps the previous poll by 5 s; pages are followed until the cursor is empty. | Every 5 s. Rows are kept for candidates and KXBTC15M. |
| Trade backfill | `/markets/trades?ticker=...&min_ts=...&max_ts=...` | After any trade-lane gap, for every candidate |
| Quote sweep | `/markets?tickers=...` (up to 300 tickers): best bid and ask with sizes, `volume_24h_fp`, open interest, status, `price_ranges` | Every 5 min |
| Discovery | `/events?status=open` (no nested markets); `/series?category=...` for the four categories; `/markets?series_ticker=...&min_close_ts=...&max_close_ts=...` | Hourly (series daily) |
| Fees | `/series/fee_changes?show_historical=true`; `/events/fee_changes?event_ticker=...` for each candidate event | Daily |
| Settlement | `/markets?tickers=...` for candidates past their close | Every 15 min until the `status` is `finalized` (or `settled`) with a result |
| Other | `/historical/cutoff`; `/incentive_programs` (recorded, never credited) | Daily |

**What it stores for each response:**
- the request start time and receive time (from the host's UTC clock) and a host label (workspace or Railway);
- the HTTP status, the path and query, and the byte count;
- the SHA-256 of the body and a local sequence number;
- the raw body, with prices and sizes kept as the decimal strings Kalshi sent.

Trades also carry Kalshi's `created_time` (in microseconds). Books carry no exchange time or sequence number, so a book is dated by the time it was received.

**Rate limits.**
- A rolling one-second budget is shared by all lanes.
- After a 429, that lane waits 2^n seconds (n = the number of 429s in a row, at most 30 s), or the Retry-After value if Kalshi sends one.
- After a 429 the recorder should also cut its average rate by 25% for 10 minutes.
- Every 429 is logged. The 2 req/s ceiling is never raised to catch up after a gap.

**Gaps.** A lane with no successful poll for more than twice its cadence opens a gap record: start, end, lane and cause. Trade gaps are backfilled, because Kalshi's full trade history is public. Book history is not public, so a book gap is permanent.

**Timing telemetry.**
- For each lane and hour: request round-trip p50/p95/p99, labelled by host.
- For each hour: receive time minus trade `created_time` at p50/p95/p99. This is network latency plus clock offset.
- The live Kalshi companion's existing order acknowledgement times, read from its receipts, read-only. No order is ever sent to measure latency.

## 4. Universe, exclusions and risk clusters

Every decision at time *t* uses only what had been received by *t*: the latest metadata snapshot, the latest book, and trades whose **receive** time is at or before *t*. Nothing uses a market's eventual final volume, spread or outcome.

### 4.1 Static admission

A market must pass all of these. Exclusions are counted against the first rule that fails, in this order.

| Rule | Requirement | Exclusion reason |
|---|---|---|
| U1 | The event's `category` is exactly `Crypto`, `Climate and Weather`, `Commodities` or `Financials`, and the series' category agrees | `category_blocked` for Sports, Elections, Politics, Entertainment/Culture, Science and Technology and Mentions, which are blocked for this Washington account. `category_unconfirmed` for Economics, Companies and every other category, which the owner has not confirmed. `category_mismatch` if the event and series disagree. |
| U2 | `market_type` is `binary` | `non_binary` |
| U3 | `status` is `active` | `not_active` |
| U4 | The published scheduled duration, `close_time − open_time`, is at least 24 h | `duration_lt_24h` |
| U5 | The time left, `close_time − t`, is between 6 h and 7 d inclusive | `outside_6h_7d` |
| U6 | `notional_value_dollars` is 1 | `notional_not_1` |
| U7 | `rules_primary` is non-empty, and the event or series lists at least one settlement source with a URL | `ambiguous_settlement` |
| U8 | The market's `settlement_bounds_type` is `default` and the event's `collateral_return_type` is empty | `nonstandard_settlement` |
| U9 | Not a multivariate or combo market: no `mve_*` collection fields, no `KXMVE...` ticker, and the series' fee type is not `quadratic_with_combo_maker_fees` | `linked_without_mapping` |
| U10 | Complete fee terms: the series' `fee_type` is `quadratic` or `quadratic_with_maker_fees`, `fee_multiplier` is numeric, and both the series fee-change list and the event's fee-change lookup were received within the last 26 h | `fee_incomplete` |
| U11 | `price_ranges` parse into steps covering 0 to 1 | `tick_unknown` |

Each UTC day, the reports publish by category how many markets each rule excluded, and how many were admitted.

Linked markets inside one event (strike ladders, or ranges where only one can win) are allowed. They share a risk cluster, and their worst cases are added together with no credit for any hedge, so no scenario mapping is needed. Markets that would need one (multivariate combos) are excluded by U9.

### 4.2 Checks at each decision (per market and variant)

A market that passes section 4.1 may receive or keep a quote at decision time *t* only if all of these hold:

- Its latest book is at most 120 s old, both sides have a bid, and the book is not crossed or locked (best YES bid + best NO bid < 1).
- A favourite exists and the paid price is inside the variant's band (section 5).
- Trailing liquidity is at least **25 contracts**. This is `volume_24h_fp` from the latest quote sweep received by *t*, if that sweep is at most 10 minutes old. Otherwise it is the sum of recorded trades over the previous 24 h.
- The YES spread is at most **$0.10**. The YES spread is YES ask − YES bid, where the YES ask is 1 − the best NO bid.
- *t* is before the entry cutoff (section 5.7) and inside an entry day of the running phase.

### 4.3 Risk clusters

A risk cluster is one underlying on one date: `cluster = (family, date)`.

**date** is the `YYMMMDD` token right after the series prefix in the event ticker. For example, `KXHIGHNY-26OCT14` gives `26OCT14` and `KXINX-26OCT16H1600` gives `26OCT16`. If the event ticker has no such token, the date is the America/New_York calendar date of the market's `close_time`.

**family** comes from the series ticker, using the first rule that matches:
- **Crypto:** prefix `KXBTC` → BTC; `KXETH` → ETH; `KXSOL` → SOL; `KXXRP` → XRP; `KXDOGE` → DOGE; `KXBNB` → BNB; `KXHYPE` → HYPE.
- **Commodities:** `KXWTI` or `KXBRENT` → OIL; `KXNATGAS` → NATGAS; `KXGOLD` → GOLD; `KXSILVER` → SILVER; `KXCOPPER` → COPPER.
- **Financials:** `KXINX` or `KXNASDAQ100` → US_EQUITY; `KXUST` or `KX10YRDIR` → US_RATES; any series tagged `Foreign Exchange` → FX; `KXDDR5` → DDR5.
- **Climate and Weather:** `KXHIGHT<city>`, `KXHIGH<city>`, `KXLOWT<city>` and `KXLOW<city>` → TEMP_<city>. `KXHIGHT` is stripped before `KXHIGH`, and `KXLOWT` before `KXLOW`. `NYC` and `NY` count as the same city. Prefix `KXRAIN` → RAIN.
- **Anything else:** the series ticker itself.

Series that appear later fall to the last rule and are listed in the reports. This table is not edited after the protocol is frozen.

### 4.4 Settlement-day blocks (for confidence bounds)

For the confidence bounds in section 13, clusters are grouped into settlement-day blocks. A cluster's block is the America/New_York calendar date of the last `settlement_ts` among its positions. A block holds every category that settles that day, so same-day moves across crypto, commodities, rates and weather count as a single draw.

## 5. The four variants (candidate count: 4)

Prices are exact decimals. *S* is the side we bid. The YES ask is 1 − the best NO bid, and the NO ask is 1 − the best YES bid.

| ID | Paid-price band | Price |
|---|---|---|
| A1 | 0.50 ≤ p < 0.80 | Join the best bid |
| A2 | 0.50 ≤ p < 0.80 | Improve the best bid by one valid tick |
| A3 | 0.80 ≤ p ≤ 0.95 | Join the best bid |
| A4 | 0.80 ≤ p ≤ 0.95 | Improve the best bid by one valid tick |

**5.1 Favourite.** From the latest book, the YES mid is m = (best YES bid + YES ask) / 2. The favourite is YES if m > 0.5 and NO if m < 0.5; there is none if m = 0.5. *S* is the favourite.

**5.2 Paid price.** p is our bid price.
- Join: p = the best bid on *S*.
- Improve: p = the next valid price above the best bid on *S*, on the market's `price_ranges` grid (one tick up). An improve quote is placed only where p is below the ask on *S*, so the spread must be at least two ticks. Improve never falls back to joining.
- The band applies to p.

**5.3 Size.** Every quote is for one contract (1.00). In each market, an account holds at most 1.00 contract, counting filled and resting together. Fills may be fractional, in steps of 0.01.

**5.4 Post-only.** Every quote is post-only and may never take liquidity (section 7.2).

**5.5 Decision cadence and repricing.** Decisions happen at every whole UTC minute (hh:mm:00). At each decision, a resting quote at price q is handled like this:
- Join keeps the quote while q equals the best bid on *S*. Improve keeps it while q is the best bid on *S* or the next valid price above it. Otherwise the quote is replaced at the new target.
- A quote is kept only while every check in section 4.2 still holds at price q. If a check fails, the quote is cancelled, and it is replaced only if the new target passes.
- A replacement starts with a cancel. The new order is sent when the cancel is acknowledged (section 7.1) and joins the back of the queue. So a market is repriced at most once a minute.

**5.6 Stale-quote cancel.** A resting quote is cancelled at the first decision where:
- its market's book is more than 120 s old;
- the book is crossed, locked or one-sided;
- the ask on *S* has come down to q or below (section 7.4);
- the favourite has flipped;
- the market's status is no longer active; or
- any check in section 4.2 fails.

**5.7 Entry cutoff.** No new quote is sent, and resting quotes are cancelled, once less than 6 h remain to the scheduled `close_time`. The same happens at the end of the phase's last entry day (23:59:59 UTC).

**5.8 Rotation.** If a market's quote, counting its replacements, has rested 6 h in a row without a fill, it is cancelled. That account then sends no new quote in that market for 6 h.

**5.9 Allocation when the budget is short.** At each decision, resting quotes are reviewed first. New quotes are then considered in this order:
1. markets in clusters where the account has no exposure;
2. then the highest score, where score = `volume_24h` ÷ (size displayed at the target price + 1);
3. then ticker, A to Z.

At most one quote rests per risk cluster at a time. A quote is sent only if it passes every limit in section 6.

**5.10 Hold to settlement.** Filled contracts are held to official settlement. There are no exits, stop-losses or sales, and no exit chosen after seeing the price path.

## 6. The simulated account and its limits

Each variant, each baseline and each phase gets its **own independent $25.0000 SIMULATED account**, started at 00:00 UTC on the phase's first entry day. It is never reset, topped up or shared. Family A never shares a bank with Family B.

Definitions at any time *t*:

- **Reservation** of a resting quote with remaining size r at price q: r × (q + the maker fee per contract rounded up to $0.000001 + $0.0100). The $0.0100 covers the balance rounding on up to 100 partial fills of 0.01.
- **At risk:** every reservation, held until its cancel is acknowledged, plus the cash paid for every unsettled position.
- **Cluster risk:** the same, counted inside one cluster.
- **Day loss** on UTC day d: max(0, −the net realized P&L of positions settled on day d).
- **Day new risk** on day d: the part of at risk that comes from orders sent on day d. A replacement counts as a new order.
- **Lifetime loss:** max(0, −the net realized P&L since the account started).

A new order (including a replacement) with reservation w is sent only if all of these hold:

| Limit | Check |
|---|---|
| $2 per risk cluster | cluster risk + w ≤ $2.00 |
| $4 outstanding | at risk + w ≤ $4.00 |
| $3 daily loss/risk stop | day loss + day new risk + w < $3.00 |
| $5 lifetime loss stop | lifetime loss + at risk + w < $5.00 |
| Cash | free cash (cash − reservations) ≥ w |

A stop only blocks new orders. Resting quotes stay until a rule in section 5 cancels them, and filled contracts are held to settlement. Every possible loss is reserved in advance, so these checks keep the account from ever losing $5 or more. A breach would be an accounting defect (section 18), not a result.

The daily stop counts today's new risk, not risk carried from earlier days. That way the $4 outstanding limit can still bind when positions are held for several days. The live Kalshi companion's day stop counts all open risk. That stricter version is reported as a sensitivity (section 10) but not used for the verdict.

Capital use is charged in full. A reservation ties up cash from the moment its order is sent until its cancel is acknowledged. A position ties up the cash paid from the fill until its `settlement_ts`, not its close time. Capital-days and the account's idle time are reported.

## 7. Execution model (primary)

**7.1 Latency.** The primary latency L is the larger of 1,000 ms and the p99 order acknowledgement time measured on the live Kalshi companion over TRAIN and VAL. L is fixed in `FREEZE.json`; it is 1,000 ms if no such telemetry exists.
- A new order decided at *t* arrives at *t* + L.
- A replacement arrives at *t* + 2L (cancel, then send).
- A cancel decided at *t* takes effect at *t* + L.
- The clock margin is ε = 250 ms.

Events are processed in time order: books by receive time, prints by `created_time`.

**7.2 Post-only check at arrival.** The order is rejected, and never rests or fills, if q is at or above the ask on *S* in either of two books: the last book received at or before arrival, or the first book received within 120 s after it.

**7.3 Queue ahead.**
- At arrival, the queue ahead Q is the larger of the two sizes displayed at q on *S* in those same two books (0 if the level is absent). Size that appears at q later is behind us.
- After each new book, Q = min(Q, the size displayed at q). So cancellations move us up only when the displayed size falls below Q.
- If q is outside the 10 best bids in a book, that book leaves Q unchanged.

This never assumes that cancelled size was ahead of us.

**7.4 Prints that fill us.** Only non-block trades in the same market count, with a `created_time` from arrival + ε up to the moment the cancel takes effect + ε.
- A print sells into *S*'s bids when:
  - for *S* = YES: (`taker_outcome_side`, `taker_book_side`) = (`no`, `ask`) and `yes_price_dollars` ≤ q;
  - for *S* = NO: (`yes`, `bid`) and `no_price_dollars` ≤ q.
- Each such print of size c first uses up the queue ahead: x = min(c, Q), then Q −= x. It then fills us for min(c − x, our remaining size), rounded down to 0.01. Prints below our price (trade-throughs) are treated the same way.
- A print with missing or inconsistent side fields, at or below q, reduces Q but never fills us.
- Crossing books: if a book received while the quote rests shows the ask on *S* at or below q, the order behind that ask would have traded with ours. The size offered at or below q counts once as a print selling into *S*'s bids, at that ask's price and the book's receive time. Later books add only size beyond what was already counted, and the quote is cancelled at the next decision (section 5.6).
- A print is used only once per account. Fills happen at q and are maker fills.
- Fills from prints before the cancel takes effect count, including during a replacement or a cancel race.

**7.5 Market end.** A quote dies at the earlier of `close_time` and the receipt of a non-active status + L. Markets that close early settle normally.

**7.6 Settlement.** A position settles when the market's `status` is `finalized` (or `settled`) with a result.
- Payout per contract: YES gets `settlement_value_dollars`; NO gets 1 − `settlement_value_dollars`.
- Cash arrives at `settlement_ts`, or at the first time the finalized status was received if `settlement_ts` is missing.
- A payout never comes from a last trade, midpoint, candle or later price.

**7.7 Fills the data cannot identify.** If an unrecovered trade-tape gap overlaps a resting quote, that quote is *unidentifiable*.
- The central result treats it as unfilled.
- The lower bound treats it as filled at q for its remaining size if that side lost, and as unfilled if it won.
- Whenever any quote is unidentifiable, every verdict uses the lower bound. The number of such quotes is reported.

## 8. Pessimistic execution model and latency stresses

The pessimistic model is preregistered, and it must also be profitable for a pass (section 14). It changes only these things:

- The latency is the larger of 2,000 ms and the measured p99 (section 7.1).
- Q never falls on cancellations, only on prints.
- A trade-through print (price below q) fills us first, before Q, so adverse fills always reach us. Prints at q still use up Q first.
- No rounding rebate is credited.

**Latency stresses** are reported for the frozen variant and for the TRAIN and VAL variants, and are never used to choose one. Each uses the primary model with L = 100, 250, 500, 1,000 and 2,000 ms, plus the measured p95 and p99 where they exist. The fastest profitable assumption is never picked.

## 9. Fees and accounting

- **Account type:** a direct Kalshi account (confirmed by the owner on 2026-10-12), so balances move on a $0.0001 grid.
- **Fee rate in force at the time of each fill.** This uses the series fee type and multiplier M, with any scheduled series or event fee change applied.
  - The maker model fee is 0.0175 × M × c × p × (1 − p) when the fee type is `quadratic_with_maker_fees`, and 0 otherwise.
  - Taker fees (0.07 × M × c × p × (1 − p)) never arise, because Family A never takes liquidity.
  - There is no settlement fee.
  - Every current universe market is plain `quadratic` × 1, so maker fills cost nothing today.
- **Per fill, per order** (Kalshi's fee rounding rules):
  1. revenue r = −p × c;
  2. trade fee = the model fee rounded up to $0.000001;
  3. aligned change = (r − trade fee) rounded down to $0.0001;
  4. rounding fee = (r − trade fee) − aligned change, added to the order's accumulator;
  5. rebate = the accumulator in whole $0.0001 steps, capped so the fill's net fee (trade fee + rounding fee − rebate) is not negative; the rebate is taken out of the accumulator;
  6. cash change = aligned change + rebate.

  A replacement is a new order with a new accumulator.
- **Fixed-point arithmetic only** (Python `Decimal`), on the market's real tick grid.
- **Tests must pin all of these:**
  - Kalshi's two published examples: one fill on the $0.01 grid, and three fills adding $0.004 each, rebating $0.010 on the third and carrying $0.002;
  - their $0.0001-grid versions;
  - a split fill;
  - a zero-fee maker fill whose revenue falls between grid steps;
  - a series with maker fees;
  - a reservation that covers 100 partial fills;
  - a scheduled fee change that takes effect between two fills.
- **Exact reconciliation at every report:**
  - cash = $25 + Σ cash changes for fills (each negative for a buy) + Σ settlement payouts;
  - free cash = cash − reservations;
  - total fees, rounding, rebates, inventory by market and side, settled P&L and open exposure all reconcile to $0.0001.

  Any mismatch is a defect (section 18).
- **All P&L is directional.** Family A has no pairs, no exits and no exit fees. Any mix of YES and NO inside a cluster gets no hedge credit.
- **Incentives:** liquidity incentives are recorded but never credited, because a simulated quote cannot earn a verified, attributable reward.

## 10. Baselines, sensitivities and diagnostics

- **No trade.** $0 per day; the $25 sits idle. This is the primary comparison.
- **Matched maker baselines, MB-J and MB-I.** These use the same universe, liquidity checks, cadence, execution model, fees and limits as the join and improve variants, but without the favourite restriction:
  - The side is YES if the first byte of SHA-256(`familyA-baseline-v1|<ticker>`) is even, and NO otherwise.
  - The favourite check in section 4.2 and the favourite flip in section 5.6 are dropped.
  - The paid-price band is 0.05 ≤ p ≤ 0.95. A band starting at 0.50 would quietly bring the favourite rule back.

  Each baseline has its own $25 account in every phase. In TEST, only the baseline matching the frozen variant runs. The baselines and their difference from the frozen variant are reported, but they are not a pass gate. If a baseline does as well as the frozen variant, the report says the favourite restriction was not shown to matter.
- **Sensitivity: live-style day stop.** The frozen variant with a day stop that counts all open risk, as the live companion does. Reported only.
- **Diagnostic: unfunded.** The frozen variant with only the $2 cluster limit (no outstanding, daily, lifetime or cash limit), labelled UNFUNDED. It shows how many clusters the rule would trade with a bigger bank. It is never a funded trial, never counts toward a floor and never enters a verdict.

## 11. Schedule

| Phase | Entry days | Then |
|---|---|---|
| 0. Feasibility | At least 48 h of actual capture on the intended host | A report (below). Never scored. |
| TRAIN | 7 consecutive UTC days, T1-T7 | Resolve: wait until every TRAIN position settles, or 14 days after T7 ends |
| VAL | 7 consecutive UTC days, V1-V7 | Resolve the same way |
| Selection and freeze | (none) | `SELECTION.md`, `FREEZE.json` and its published hash |
| TEST | 28 consecutive UTC days, E1-E28 | Follow every position to settlement. Follow-up ends 30 days after E28 ends. |

**Phase 0** needs a persistent recorder; if none is running, the report says so. The report covers:
- the time actually captured, with coverage and gaps by lane;
- 429s, request latency by host, and clock offset;
- depth and queue at the favourite's best bid, by category;
- the rate of prints into favourite bids, and quote admissions per day;
- a count-only estimate of how many clusters the section 6 limits could fund in 28 days.

It joins no settlement outcome to any quote and computes no P&L.

**Start days.**
- **T1** is the first UTC day that starts after the Phase 0 report is committed and the retention option (section 12) is in place.
- **V1** is the first UTC day that starts after the TRAIN cohort is resolved and its report is committed.
- **E1** is the first UTC day that starts at least 1 hour after the freeze commit, and after the VAL cohort is resolved.

**Scoring and coverage.**
- If fewer than 5 of the 7 TRAIN (or VAL) entry days are covered (section 12), that phase restarts on new future days. This depends on coverage only, never on P&L.
- Each phase scores **every** position its entry days created, including ones that settle late. TRAIN or VAL positions still unresolved at the resolution limit count at $0 and are listed.
- The likely calendar is about 2 + 7 + 8 + 7 + 8 + 28 + up to 30 days, or roughly 60 to 90 days from the recorder's start.

**Selection** is deterministic and happens after VAL resolves:
1. Eligible variants are those with TRAIN primary net $/day ≥ 0. If none qualifies, all four are eligible.
2. Choose the eligible variant with the highest VAL primary net $/day. Ties go to more VAL traded clusters, then to the lower variant number.
3. The chosen variant goes to TEST whatever its sign. TRAIN and VAL make no inferential claim and spend no error budget.

**Freeze.** `family_a/FREEZE.json` records:
- this protocol's SHA-256 and the chosen variant;
- the commits of the recorder and replay code;
- every parameter value used, plus L and its source;
- OPEX_A (section 13);
- E1, E28 and the follow-up end;
- the retention option, the bootstrap seed and the host details.

Its SHA-256 is committed and written in `docs/WORKLOG.md` at least 1 hour before E1 starts.

**During TEST** a daily integrity run checks coverage, limit compliance and the accounting identity, with every P&L field hidden. Nothing may change: no parameter, no early stop (even if the chart looks good), and no extra entry days. The owner may stop the experiment at any time. That ends it as INCONCLUSIVE (stopped), never as a pass.

## 12. Coverage, gaps and data retention

**Coverage.**
- A decision for a market is **covered** if its book is at most 120 s old and its trade tape is complete (after backfill) over the last 120 s.
- An uncovered decision sends no new quote, and the stale rule (section 5.6) cancels any resting one.
- Exposure lost to gaps is never hidden: gap time, cancelled quotes and unidentifiable quotes (section 7.7) are all reported.
- An entry day is **covered** if at least 90% of its decisions (over the markets passing section 4.1) are covered and no market with a resting quote has an unrecovered trade gap.
- **TEST data floor:** at least 26 of the 28 entry days covered, and at least 90% of all TEST decisions covered. Otherwise the verdict is INCONCLUSIVE.

**What the replay reads:** at most the 10 best bid levels on each side, every trade field listed in section 7.4, and the metadata, fee and settlement fields named in sections 4 and 7.6.

**Retention.**
- Every input the replay reads for a phase is kept until that phase's verdict is published, either raw or as a lossless derived copy of those fields, with SHA-256 manifests. TRAIN and VAL inputs are kept until the TEST verdict.
- The recorder never deletes unscored Family A evidence to make room. At the cap it does these in order:
  1. drops KXBTC15M data older than the arena's declared retention;
  2. stops polling markets that are not candidates;
  3. pauses (and a pause is a gap).

**Disk decision before T1.** The audit estimates about 150-230 MB a day for all lanes, so the 2 GB default holds only 9-13 days. Family A needs its 28 TEST entry days: about 2.8 GB at the estimated 100 MB a day for Family A alone. One of these two options must be in place before T1, and the choice is recorded in `FREEZE.json`:
- (a) a dedicated volume with a cap of at least 4.5 GB (the owner's decision; it may cost money); or
- (b) a nightly, hashed, lossless compaction of the fields the replay reads (changed books only, 10 levels a side, all candidate trades, metadata), after which raw files may rotate after 72 h.

No decision rule depends on which option is chosen.

## 13. Statistics and the error budget

**Primary statistic** (TEST, frozen variant, primary model):
- The trading net N = cash at the end − $25, once every position has settled.
- D = the number of days from 00:00 UTC on E1 to the later of the end of E28 and the last TEST position's `settlement_ts`, capped at the follow-up end.
- Net per calendar day = N / D − OPEX_A.

**OPEX_A** is half the recorder's actual incremental hosting cost over the D days, divided by D, because Family A and Family B share the recorder equally. If that cost cannot be read, OPEX_A = $5.00 per 30.4375 days × 0.5 = $0.0821 per day. Results are shown both before and after OPEX_A; the pass uses the after-OPEX figure.

**Lower confidence bound (LCB).** The units are risk clusters: each cluster's total net, fees included. They are summed into the settlement-day blocks of section 4.4. With n_b blocks whose sums have mean x̄ and standard deviation s, the LCB is the smaller of two bounds, each at level α:
- (i) the α quantile of a percentile bootstrap over blocks (resampled with replacement, 100,000 draws, seed 20261013);
- (ii) the one-sided Student-t bound n_b × (x̄ − t(1−α, n_b−1) × s / √n_b).

Each bound is converted to $/day as (bound / D) − OPEX_A. D is not resampled.

**Error budget.** Family A has a familywise one-sided α of 0.025 for this batch, split before any testing:
- **0.020** for TEST cohort 1;
- **0.005** for at most one replacement cohort (section 18).

There is no third cohort in this batch. Only the one frozen variant is tested, so TEST needs no further multiplicity adjustment. Family B has its own 0.025 in the arena's protocol.

**Floors** (section 4 of `CLAUDE_PROMPT.md`):
- at least **200** distinct traded, resolved risk clusters (traded = at least 0.01 contract filled in TEST);
- at least **14** distinct settlement days (blocks).

With fewer, the bound is not trusted and the verdict is INCONCLUSIVE.

**Tails.** A bootstrap cannot show losses that never happened in the sample. The report therefore shows the worst cluster and the worst day, and the result after removing the best cluster and after removing the best day. For a pass, the net must stay positive with the best day removed: (N − the best block's sum) / D − OPEX_A > 0.

**Reported, but not gates:**
- an event-cluster bootstrap, resampling clusters one by one;
- the same bounds for the matched baseline;
- the difference between the frozen variant and the baseline.

## 14. Verdicts

The rows are checked in order; the first that applies decides.

| Verdict | When |
|---|---|
| VOID | A defect that could change a decision is found in TEST cohort 1 (section 18). Cohort 1 makes no claim, and a single replacement cohort may run. If the replacement is also void, the verdict is NO EDGE when the cause was an accounting or limit failure that could not be fixed, and INCONCLUSIVE otherwise. |
| INCONCLUSIVE (data) | A position is still unresolved at the follow-up end (remaining exposure disclosed at cost), the TEST data floor (section 12) is missed, or the owner stopped the experiment. |
| NO EDGE (cannot execute) | The data floor is met, but fewer than 20 clusters traded in TEST: the rule cannot trade usefully within these limits. |
| INCONCLUSIVE (too little evidence) | Fewer than 200 traded, resolved clusters or fewer than 14 settlement days. The report gives the observed sign and both bounds. |
| NO EDGE | All floors are met and the primary net per day after OPEX_A is ≤ 0. This means no usable edge for this fixed candidate, not that none exists on Kalshi. |
| INCONCLUSIVE (not significant) | The primary net is positive, but the LCB, the pessimistic net or the net without the best day is not above zero. |
| QUALIFIED FOR OWNER-REVIEWED LIVE PROPOSAL | All floors are met, the accounting reconciles exactly, no limit was breached, and after OPEX_A: primary net > 0, LCB > 0 at α, pessimistic net > 0, and net without the best day > 0. |

A qualified result is still uncertain, and it authorizes nothing live. If Family A does not qualify, the finding is published, and any new idea gets a new protocol and new future data. The same holdout is never mined again.

## 15. Reports

Each phase and account gets an owner-readable report in plain words, plus machine-readable files, covering:

- **Money:** total net and net per calendar day (before and after OPEX_A), at the simulated bank and limits, including idle days, stops, fees, every loss and cash locked until settlement.
- **Activity:** quotes sent, post-only rejections, replacements, cancels by reason, fills, fill rate and time to fill, and queue ahead at arrival.
- **Capital and limits:** exposure duration and capital-days; the days on which a limit blocked a quote, by limit.
- **Splits:** results by YES and NO favourite, by category, by band, and by 5-cent paid-price bucket.
- **Fill versus eventual loss:** the win rate of filled quotes against quotes that never filled at similar prices (an adverse-selection check).
- **Concentration and tails:** the worst cluster and worst day, the drawdown of realized equity, the share of net from the top five clusters, and the result without the best cluster and without the best day.
- **Robustness:** the latency stresses (section 8), the pessimistic model, the matched baseline, the live-style day stop and the unfunded diagnostic, each labelled.
- **Data quality:** coverage, gaps and 429s; unidentifiable quotes with their bounds; exclusions by reason and category; host latency labelled workspace or Railway.
- **Capacity at a bigger size:** unknown, because the simulation trades one contract.

A sector, band or side that looks best in TEST is reported as an observation, never as a preregistered strategy.

## 16. Family B (KXBTC15M): what the recorder adds and how the arena uses it

Family B, the BTC15M inventory-controlled maker, lives in the Kalshi arena, which is built by a separate job. Its variants, toxicity rule, thresholds, inventory policies and its own 0.025 error budget are registered in the arena's protocol, not here. The recorder simulates nothing for BTC15M; it is not a second BTC15M simulator. It adds a persistent public tape so the arena can replay its windows later.

**What it records:**
- **Books:** every batch book call carries the current and next KXBTC15M tickers, so both windows' full-depth raw `orderbook_fp` is captured at about 1 Hz, with request and receive times.
- **Trades:** every KXBTC15M trade from the exchange-wide tape, with per-ticker backfill after any gap.
- **Terms:** `/series/KXBTC15M` (fee type, multiplier, rules, settlement sources) and the fee changes, each window.
- **Results:** each window's market row, from discovery until it is finalized: open and close times, strike fields, rules, status, `result`, `expiration_value`, `settlement_value_dollars` and `settlement_ts`.

**What it does not record:**
- The authenticated websocket (it needs a key), so there are no exchange sequence numbers.
- Coinbase, Kraken or CF Benchmarks ticks, in this version. The CF settlement average appears only as each window's `expiration_value` after the window closes. A replay that needs spot prices must take them from another recorded source with its own provenance. Windows without one are marked not replayable for spot-based rules.

**How the arena's frozen candidate uses it.** Breeding counts as TRAIN. A flagged candidate's configuration is frozen and its hash published before its TEST. The TEST then runs unchanged on at least 14 future completed UTC days with at least 1,000 fully covered windows. The tape lets that TEST be:
1. re-scored offline afterwards, deterministically, with the existing parsers: `speeddesk_kalshi.parse_books` on each raw book item, `parse_trades` on the raw trade rows, and `parse_window` on the market and series rows;
2. checked window by window against the arena's in-process ledger;
3. covered when the arena's own feed has a gap.

The arena's protocol decides which source is primary. This protocol recommends using the more conservative result whenever the two disagree, and requires every disagreement to be reported. The tape is lower fidelity than the live websocket (1 Hz snapshots, no exchange sequence), so queue position is only partly identifiable from it.

## 17. Known risks, stated before any data

- **The 200-cluster floor may be out of reach.** With one contract per quote, $2 per cluster, $4 outstanding and holds of 1-7 days, the account can probably fund about 2-5 clusters a day: roughly 55-140 in 28 days. The likely verdict is therefore INCONCLUSIVE for lack of evidence. The limits are not enlarged to avoid that. A bigger bank needs a new protocol and the owner's word.
- Only 151 events (Crypto 14, Commodities 12) were in the window at audit time, and correlated ladders shrink the effective count further.
- Queues are long in Crypto and Commodities (a median of 500 contracts at the favourite's best bid), so join quotes may almost never fill there.
- REST books have no exchange time or sequence number, so queue position is only partly identifiable. Section 7 assumes the worst plausible case.
- In the sandbox, public 429s arrived below 1 req/s after large responses. Railway's limit must be measured in Phase 0.
- A favourite's loss is large compared with its wins, so a short sample can look good while hiding the tail.
- Every result comes from one host and one recorder, so a recorder defect affects every phase.

## 18. Changes and corrections

- **Before T1:** this protocol may be replaced only by a new versioned file with its own hash. This file is kept, and the reason goes in `docs/WORKLOG.md`. Phase 0 findings may justify a new version; no TRAIN outcome can, because none exists yet.
- **After T1:** any change that could alter an admission, quote, fill, fee, limit or accounting result voids the running phase.
  - TRAIN or VAL then restart on new future days.
  - TEST cohort 1 becomes VOID, and at most one replacement cohort runs on new future days at α = 0.005, after the fix, a new freeze and a new hash.
  - A defect report that triggers a replacement must be committed before the replacement starts. Only a defect, never a result, may trigger one.
- Changes that cannot alter a decision (report wording, extra labelled diagnostics) are allowed and logged.
- A defect found after a verdict withdraws that verdict. The status becomes INCONCLUSIVE until a new future cohort is run.

## 19. Parameters at a glance (the sections above govern)

| Item | Value |
|---|---|
| Categories | Crypto, Climate and Weather, Commodities, Financials |
| Duration / time left | At least 24 h scheduled; 6 h-7 d left |
| Bands | 0.50 ≤ p < 0.80; 0.80 ≤ p ≤ 0.95 (paid price) |
| Prices | Join the best bid, or improve it by one valid tick |
| Size | 1 contract per quote, at most 1 per market |
| Liquidity | `volume_24h` ≥ 25; YES spread ≤ $0.10; book at most 120 s old |
| Decisions | Every whole UTC minute; repricing at most once a minute |
| Cutoff / rotation | 6 h before close; 6 h without a fill → cancel, then 6 h off |
| Latency | 1,000 ms primary (or the measured p99 if larger); stresses 100-2,000 ms; pessimistic 2,000 ms; ε 250 ms |
| Simulated limits | $25 cash; $2 per cluster; $4 outstanding; $3 day loss/risk; $5 lifetime |
| Schedule | Phase 0 ≥ 48 h; TRAIN 7 days; VAL 7 days; TEST 28 days; follow-up 30 days |
| Floors | 200 traded, resolved clusters; 14 settlement days; 26 of 28 days covered; 90% of decisions covered |
| Error budget | α 0.020 for TEST cohort 1; 0.005 for one replacement |
| OPEX_A fallback | $0.0821 per day |
| Seeds | Bootstrap 20261013; baseline side `familyA-baseline-v1` |

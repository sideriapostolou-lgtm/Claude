# Kalshi rewards (LIP): pre-registration of the Pyth lead-lag test and the practice desk policies

Written Wednesday, October 14, 2026, before any Pyth price had been read (Pyth's Hermes service answers 401 without
a key; no key exists yet) and before any line of the analyzer (`leadlag.py`) or the practice desk existed. **No
lead-lag number has been computed.** The only data looked at so far are the rewards research's recordings and the
FX research's evidence (`PLAYBOOK.md`, the FX research notes of October 13): Kalshi books, prints, programs, and
the free 1 s settlement series. This file fixes the question, the definitions, the split and the pass bar. It is
committed alone, and its SHA-256 is in `PREREG.sha256`. A change after this commit is an addendum below the line
at the end, dated, with its reason, and it can never touch a definition for a phase that has already been looked
at.

## 1. The question

`PLAYBOOK.md` §3 found money in FX LIP only for a bot that sees the next Kalshi book 0.5 to 1 second early. Step 2 of
its §5 asks: **how often does the Pyth price move 0.5 seconds or more before Kalshi's FX market makers reprice?**
If rarely, the FX LIP effort stops there.

Two warnings, fixed now so they cannot be bent later:

- A "continue" here is a **necessary** condition, never a sufficient one. The playbook's cancel-only oracle (pull
  quotes 0.5 s before they go stale) still lost money (-$2.17 a period at the Reference, -$0.45 at the best bid).
  Real money needs the practice desk's Pyth policy (§8) to pass the playbook's go/no-go bar (§5) on fresh data.
- This measures a race against Kalshi's designated FX market makers, not a rebate.

## 2. Data and clocks

- **Kalshi:** the public batch book call `GET /markets/orderbooks` as the recorder writes it (`books` lane, kind
  `book`, written only when a book changed; `book_calls` lane, kind `book_call`, listing every ticker asked as
  `changed`, `unchanged` or `missing`). A poll of ticker T is one `book_call` row that lists T as changed or
  unchanged; its book is the newest `book` row of T at or before it. The snapshot instant of a poll is unknown
  inside `[requested_at, received_at]`.
- **Pyth:** one price per update, the aggregate price (never the confidence interval), with **our own receive time**
  from the same host clock as the Kalshi polls. Pyth's `publish_time` is whole seconds and is not used for timing.
  Out-of-order and duplicate updates are dropped per symbol. Sources:

  | Source tag | What | Can say CONTINUE | Can say STOP |
  |---|---|---|---|
  | `pyth_hermes` | Pyth Hermes SSE, `parsed` prices, our receive time per message | yes | only if its median update interval is at most 250 ms (§6) |
  | `kalshi_pyth_value` | Kalshi's authenticated `pyth_value` channel, our receive time | yes | same |
  | `pyth_pro` | Pyth Pro (Lazer) stream, our receive time | yes | same |
  | `kalshi_live_data` | Kalshi's free 1 s settlement series, timed at label + 1 s | **no** (descriptive only) | **no** |

  The free series is only a quick look: its points are labelled with Pyth's second, not a receive time, and a bot
  cannot receive it in time. Timing its event at label + 1 s (the latest moment the move can have happened) makes
  its warning a lower bound, so it never decides anything.
- A Pyth source recorded on another host than the Kalshi polls is descriptive only.
- **Cache check:** the batch book call answered `x-cache: Miss from cloudfront` with no `cache-control` on
  2026-10-13 (FX research, `fxlip/dl/kalshi/ob_hdr.txt`; all 1,382 book calls of the rewards recording had no
  cache header). If the recorder ever logs a cache hit or an `age` header on a book call, those polls are dropped.

## 3. Definitions

**Markets.** The five FX 15-minute series (`KXEURUSD15M`, `KXGBPUSD15M`, `KXUSDJPY15M`, `KXAUDUSD15M`,
`KXUSDCAD15M`) are the primary family. Copper, platinum, palladium and natural gas (`KXCOPPER15M`, `KXPLATINUM15M`,
`KXPALLADIUM15M`, `KXNATGAS15M`) are reported, never decided on. Coin Race settles on CF Benchmarks and is out. The
Pyth symbol of each series is in `nightcrawler.lip_feed.SERIES`. At time t the series' market is the one whose
liquidity program window (`start_date` <= t < `end_date`, from `GET /incentive_programs` rows) contains t; without
a program row, the market row's `open_time`/`close_time`.

**Kalshi mid.** `mid = (best YES bid + 1 - best NO bid) / 2`, in dollars. A book with an empty side has no mid.

**Pyth event.** For symbol s with updates `(t_i, x_i)` (t = our receive time): `r_i = 10,000 * ln(x_i / x_ref)`,
where `x_ref` is the price of the newest update with `t <= t_i - 1.0 s` (lookback D = 1 s). The event is the first
update with `|r_i| >= k`; its direction is the sign of `r_i`; no further event on s until `t_i + 5 s` (refractory
R = 5 s). Grid: FX `k` in {0.5, 1, 2} bp; metals and gas {1, 2, 5} bp.

**Exclusions** (counted, never silently dropped): the event is in the window's first 30 s or last 60 s; there is
no Kalshi poll with `received_at <= t - D` in the same window (no baseline); the baseline mid is outside
[0.05, 0.95]; two consecutive polls of the market more than 2.5 s apart anywhere in `[t - D - 2.5, t + H]`
(coverage); Thursday 3:00 to 5:00 am ET (maintenance).

**Response.** Baseline `m0` = the mid of the newest poll with `received_at <= t - D` (before the move began).
Scanning later polls in order, up to the first poll with `requested_at > t + H` (horizon H = 10 s): the first poll
whose mid differs from `m0` is the response poll J. `same` if it moved in the event's direction, `opposite` if
against, `none` if no poll within the horizon differs.

**Warning (interval-censored).** For a `same` event, the reprice happened after the last stale poll was snapshotted
and before the response poll answered:

- `W_lo = requested_at(J-1) - t` (J-1 is the newest stale poll; it may be the baseline poll itself);
- `W_hi = received_at(J) - t`.

**The primary indicator:** `warn05 = (W_lo >= 0.5 s)`: a poll that began at least 0.5 s after we received the
Pyth update still showed the stale book. This is conservative: with polls about 1 s apart it estimates the share of
reprices still pending somewhere in the 0.5-1.5 s after the update, which is never more than the share pending at
exactly 0.5 s. `kalshi_first = (W_hi <= 0)`: Kalshi repriced before our Pyth update arrived.

**Reported for every cell:** events, exclusions by reason, `same`/`opposite`/`none`, `P_same = same / (same +
opposite)`, the quantiles (10, 25, 50, 75, 90 %) of `W_lo` and `W_hi` over `same` events, the share `S` (below),
`kalshi_first`, the Pyth move size at the event (bp) and at the response, and the same table per series and per UTC
hour, plus the source's update interval (median, 90 %) per symbol.

## 4. The statistic

`S = mean(warn05)` over the `same` events of the cell, pooled over the five FX pairs. Its 95 % range is a
percentile cluster bootstrap over market-windows (B = 2,000, seed 20261014): events of one market-window move
together. `P_same` gets the same bootstrap.

**Primary cell (the only one that decides):** FX pooled, `k = 1 bp`, D = 1 s, R = 5 s, H = 10 s, any same-direction
change of the mid. Every other grid value, the metals and gas, the per-pair and per-hour tables and the free-series
quick look are readings only.

## 5. Split by time

- An **FX day** is a UTC calendar day with at least 12 hours of FX trading hours (Sunday 17:00 to Friday 17:00 ET,
  minus Thursday's maintenance) covered by both an eligible Pyth source and Kalshi polls of all five FX markets.
- **TRAIN** = the first 2 FX days. **VAL** = the next 2. **TEST** = the 4 after those. Days are counted from the
  first FX day of the source being judged; a new source starts its own count.
- **TRAIN** is for data checks and code: every cell may be read. After TRAIN only bug fixes are allowed, each in a
  dated addendum before VAL is computed. **VAL** reports the primary cell, decides nothing, and freezes the code.
- **TEST is one look.** `leadlag.py --phase TEST` refuses to run unless `leadlag/FREEZE.json` exists, names this
  file's SHA-256, the source, the four TEST days and the SHA-256 of `leadlag.py`, all matching now; it refuses again
  once `leadlag/TEST_RESULT.json` exists. It first checks the counts in §6 and prints only counts when they fail.

## 6. The decision (TEST, primary cell)

1. **Enough data:** at least 300 `same` events in at least 100 FX market-windows. If not, TEST is extended by whole
   FX days, decided on counts alone, before S is computed.
2. **Kalshi follows Pyth:** the 95 % lower bound of `P_same` is at least 0.55. If not: **INCONCLUSIVE** (at this k
   Kalshi's mid does not reliably follow Pyth, so a lead cannot be read).
3. **CONTINUE** if the 95 % lower bound of S is at least **0.50**: in at least half of Kalshi's same-direction
   reprices, the stale book was still showing 0.5 s after we received the Pyth move. The next step is the practice
   desk's Pyth policy against the playbook's go/no-go bar; no real money follows from this alone.
4. **STOP** if the 95 % upper bound of S is below **0.25** AND the source's median update interval on the FX symbols
   during TEST is at most 250 ms: warning of 0.5 s or more is rare. Per the playbook, the FX LIP effort stops; the
   recorder keeps running; the Pyth subscription is not bought or is cancelled.
5. Otherwise **MARGINAL**: it does not meet the continue bar. FX LIP real money stays off; the recorder and the
   practice desk keep running; nothing is bought.

A STOP from a source slower than 250 ms applies only to a bot on that source and is written as such.

## 7. Known limits (fixed now, decide nothing)

- Kalshi's book is polled once a second, so a lead is only known to within a poll interval; `warn05` is built to
  err toward "no warning".
- A REST book has no exchange sequence; a change and its reversal inside one second are invisible.
- The analyzer cannot see who repriced (market maker or taker), only that the best prices moved.
- A source's latency to us (Hermes adds its own) is inside the measurement, which is right for a bot on that source.

## 8. Practice desk policies (fixed before any practice result)

The practice LIP desk (`nightcrawler.lip_desk`, pretend money, no order path) runs these and only these:

| Policy | Quote | Size | Moves | Stop |
|---|---|---|---|---|
| `ref_stop5` | each side's Reference price | 10 per side | cancel and re-place (back of the queue) on every book where the target price changed | cancel everything 300 s before the close |
| `ref_close` | the Reference | 10 | same | quotes to the close |
| `best_stop5` | each side's best bid | 10 | same | 300 s before the close |
| `ref_pyth_pull` | as `ref_stop5`, plus: when the Pyth price moves at least `k` (FX 0.5 bp, metals and gas 1 bp) from its value at the newest Kalshi book, cancel the side the move makes stale (up: the NO bid; down: the YES bid) at once, and re-place only on a later Kalshi book | 10 | same | 300 s |

- **Guards, every policy:** post-only (an order that would cross the newest book is not placed); a side is quoted
  only when, with our size, both sides reach the Target (otherwise the second scores nothing); self-trade
  prevention; whole contracts; decisions take effect 0.25 s after the book that caused them.
- **`ref_pyth_pull` is active only** in a window whose Pyth symbol had an update in at least 90 % of the window's
  seconds. Otherwise the window is "inactive" for that policy and not scored (Coin Race never has Pyth).
- **Fill models:** `timed` (the rewards review's central model: back of the queue, prints at our price eat the queue
  first, prints through our price fill us, a public bid crossing our stale price fills us in proportion to the time
  our order was exposed, and a cancelled order stays exposed until the next book shows whether the crossing came
  first) and `fee_timed` (the same, but a crosser takes us only when it gains more than the taker fee). Lenient
  fills are never shown.
- **Reward:** the exact LIP formula (`nightcrawler.lip_score`) at two offsets per second (0.25 and 0.75 s) against
  the newest book, the $1 minimum per program, rounded down to the cent; no recorded program, no reward.
- **Marks:** each fill at the public mid 60 s later (the settlement value after the close) and at settlement (the
  official result). A window without a result 2 hours after its close is void and counts nowhere.
- **Accounts:** per market-period with no budget (the research metric of the go/no-go bar) for every policy and
  both fill models; and two cash-carrying accounts on the `timed` model for every policy: **A45** (EUR/USD only, $45
  on shard 0) and **A250** (all five FX pairs, $250 on shard 0). Cash is locked by resting orders and open
  positions until settlement; the reward is credited at the window's settlement (real payouts come a day or more
  later, so practice cash is optimistic on timing).
- **Daily scorecard (UTC day), per policy, fill model and family:** market-periods, reward paid, contracts filled,
  the share filled by crossings, fill P&L at 60 s and at settlement, net at both, the mean net per period with its
  95 % range (mean +- 1.96 standard errors over market-periods) and the same per day of 67.3 FX periods (the
  playbook's 7-day average).
- **Real money:** none, ever, from this desk. The go/no-go bar for real money is the playbook's §5, unchanged.

---

Addenda (dated, newest last):

1. **2026-10-14, before any practice result existed (the desk had run only on synthetic test data and on the
   rewards research's already-published windows, which have no Pyth prices), section 8, `ref_pyth_pull`.** "Re-place
   only on a later Kalshi book" is replaced by: **re-place the pulled side only on a later Kalshi book whose mid has
   moved the Pyth move's way since the pull (up for a pulled NO bid, down for a pulled YES bid), or on the first
   book 5 s or more after the pull.** Reason: with books polled about once a second, the next poll usually still
   shows the stale book, so the original wording re-placed the order into the very price the pull was meant to
   avoid. Nothing else in section 8, and nothing in sections 1 to 7, changes.

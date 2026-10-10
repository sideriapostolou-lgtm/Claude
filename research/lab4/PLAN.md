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

## Amendment 3 (2026-10-09 ~16:45 UTC, before any TRAIN return was read): execution, windows, power

From an adversarial code review of the engine against the real tapes (structure only; no return was computed).
Three things were wrong in version lab4-v1 as written, and they are fixed before the first TRAIN read:

1. **Buyable prints only.** The Data API tape is taker-side: a SELL print on outcome o's token at price p means
   someone HIT THE BID at p; a buyer could not have paid p. A print is *buyable for outcome o* only if it is a BUY
   on o's token or a SELL on the other token at 1 - p. Under lab4-v1 most "fills" at 0.97-0.999 were bid-side
   prints, which would have inflated every cell. Rule now: the signal is the first buyable print for o at or
   above theta; execution is the first buyable print for the SAME outcome at or after t + 10 s (within 600 s, and
   before the end). Each cell reports the share of its trades whose old-rule execution print was bid-side, so the
   size of the correction is visible.
2. **Windows a live trader can know.** The `closedTime` (UMA resolution) is not known in advance, and for short
   windows it sat entirely after the outcome was decided (crypto: median 54 s after `endDate`; sports: about 2 h
   after the game). Windowed cells are now anchored on **`endDate`** (published when the market opens):
   signal and execution must lie in `[endDate - H, endDate)`. For sports, `endDate` is often a deadline rather
   than the final whistle, so P2's windowed cells are labelled **oracle-timed** and are NOT selectable; P2's
   selectable cell is **H = infinity**: the first buyable print at or above theta anywhere in the 14-day tape
   before resolution, held to resolution (the honest "buy the near-certain side whenever it appears"). P1 and P4
   also gain an H = infinity cell. Lock time is still measured to `closedTime`.
3. **Power and degenerate cells.** A cell with zero observed losses cannot qualify, whatever its CI: with n
   wins and no loss the 95 % upper bound on the loss rate is 3 / n (rule of three), and at a 0.1 % gain per win
   that is a losing rule. Each cell reports that worst case (`worst_case_net = (1 - 3/n) x mean win - 3/n`)
   and `qualifies` additionally requires at least one observed loss and `worst_case_net > 0` when losses are
   fewer than 5. The bootstrap resamples **events** (`event_slug`), not markets: 44 % of markets sit in
   multi-market events whose outcomes are one draw (weather brackets, winner fields).

Also fixed: TRAIN refuses to run until every eligible market of the split has a tape (coverage is written into
the result); the trial ledger keeps one entry per (hypothesis, cell, split, stage), so a re-run does not inflate
the count; the cross-lab count reads lab 2's and lab 3's ledgers in their own formats; the shadow paper desk's
window has an upper bound (no entry after a market's end; a game's end is its last live quote) and the
recorder writes its files atomically. Fee rates stay the family table of Amendment 1 (verified against Gamma's
per-market `feeSchedule.rate` on the listed markets; the 22 `general_fees` markets are charged the most
expensive rate).

## Amendment 4 (2026-10-09 ~18:45 UTC, before any P5 return was read): P5 "patient bid", rest a bid instead of lifting the ask

Why: P1-P4 found no edge taking the ask on near-certain outcomes (TRAIN read 18:00-18:05 UTC; RESULTS.md,
READING.md). Those rules paid the spread and the taker fee on every trade: they bought at the ask. P5 asks whether
the same markets and the same signals are worth having when we wait on the bid side and let a seller come to us,
paying no spread and, per the venue's own schedule, no fee. The known danger is adverse selection: a seller only
reaches our bid when the price falls, which is exactly when a "near-certain" outcome is less certain than it
looked. This amendment is written after the P1-P4 TRAIN returns were read (they are its motive) and before any P5
number was computed; P5 is a new rule, not a re-selection among P1-P4 cells, and it is run on TRAIN only.

**Hypothesis P5 (patient bid, all markets, selectable).** Same universe, splits, $20 ticket, 10 s latency and
signal as P1: the first buyable print for outcome `o` at or above `theta` inside `[endDate - H, endDate)`
(`H = inf`: anywhere before resolution). Instead of lifting the next ask we post a bid for `o` at
`tp = t_signal + 10 s` at price `b` and leave it resting until it fills or the window ends (`end_bound` =
min(`endDate`, `closedTime`) for windowed cells, `closedTime` for `H = inf`), when it is cancelled unfilled.

**Resting price.** The tape has no book, so the best bid is inferred from the prints a buyer could NOT get (the
bid-side prints of Amendment 3: a SELL on `o`'s token, or a BUY on the other token at `1 - p`; each one is a level
a seller actually hit). `b_ref` = the price of the most recent bid-side print for `o` in the 600 s before
`t_signal` (the same 600 s as §2's execution window), else `p_signal - tick` (the top of a one-tick-wide book);
in every case `b_ref = min(b_ref, p_signal - tick)`, a bid never sits at or above the ask we saw. Cells: offset
`k` in {0, 1} ticks, `b = b_ref - k x tick`, rounded to the tick grid. **Tick = 0.001**: polymarket.com's tick
above 0.96, and Polymarket US's tick everywhere. (Structural check, no return computed: in a 400-market TRAIN
sample, 399 markets show sub-cent prints at >= 0.95, about half of all such prints.)

**Fill model (conservative; the tape is taker-side prints with price, size and side, and NO depth).** The bid at
`b` is filled only by a bid-side print for `o` at a price STRICTLY below `b`, strictly after `tp` and before
`end_bound`: a taker sold through our level, so by price priority every share resting at `b`, ours included, was
taken whatever our place in the queue. A print at exactly `b` never fills us: our queue position is unknown, and
the book-aware rule ("filled at `b` once the cumulative sell size at `b` since `tp` exceeds the displayed bid depth
at `tp`") cannot be applied because the data carries no depth; strictly-below only, stated here. Size: the fill
is complete only once the cumulative size of bid-side prints for `o` at or below `b` since `tp`, through the
filling print, is at least our order `shares = 20 / b`; the first strictly-below print at which that holds is the
fill, at its time `t_fill`, at price `b` (a resting order fills at its own limit, never better). Otherwise the
trade is "missed" (posted, never filled) and counted, so every cell reports its fill rate. Settlement as P1:
`shares x 1` if `o` wins, else 0; lock time from `t_fill` to `closedTime`; no sale before resolution.

**Fees (two stated assumptions, both run).** polymarket.com's published schedule (Amendment 1) charges takers
only: a resting order pays nothing. Polymarket US charges takers `0.0695 x shares x p x (1 - p)` and pays makers a
rebate, which is not modelled (a rebate is never counted as income here). Every P5 cell is therefore run twice:
**fee0** (maker pays 0, the documented case) and **feeT** (maker pays the full taker fee of the market's family,
Amendment 1 table: the stress case). Only the **feeT** cells are selectable; the fee0 cells are reported as the
fee-free upper bound and tagged not selectable, like P2's oracle-timed cells. A cell that qualifies under feeT
qualifies under fee0 as well (the fee only lowers `net`), so "qualifies under both" and "qualifies under feeT" are
the same bar.

**Cells.** `theta` in {0.95, 0.97, 0.99} x `H` in {1, 6, 24, 168, inf} hours x `k` in {0, 1} x fee in
{fee0, feeT}: 60 cells, 30 selectable. Cell key `theta<t>|H<h>|b-<k>|<fee>`. Families: all, as P1; the
per-family breakdown is reported as everywhere (the owner's non-sports mix is read from it).

**Qualification bar (unchanged: PLAN §3 + Amendment 3, `core.qualifies`).** `n >= 100` fills, mean net per $ at
risk > 0, event-bootstrap CI95 lower bound > 0, at least one observed loss, and with fewer than five losses the
rule-of-three worst case `(1 - 3/n) x mean win - 3/n` must be positive. TRAIN selects the selectable cell with the
highest mean net among those that qualify; none = NO EDGE for P5. **Placebo:** §4's calibration placebo,
unchanged, at VAL: outcomes redrawn as Bernoulli(`b`), the fill price, 2000 draws; the real mean must sit above
the 95th percentile. VAL and TEST are separate decisions and are NOT run under this amendment; if P5 qualifies on
TRAIN the stage stops there and says so.

**Readings added for P5:** signals (bids posted), fill rate (fills / signals), mean signal ask against mean fill
price (the price improvement patience bought), median wait from posting to fill, and how many bids saw a
strictly-below print but never enough size (lost to the size condition). The "bid-side share (old rule)" column
does not apply (every P5 fill is a maker fill) and prints n/a.

**Power.** The conservative fill model may leave a cell with a handful of fills; such a cell is underpowered and
cannot qualify (`n >= 100`), which is the intended behaviour, not a finding of no edge, and the reading must say
so with the fill counts.

**Trial ledger.** Each of the 60 cells evaluated on TRAIN is one trial in `research/lab4/trials.json`, written by
`run.py` as everywhere (upsert on hypothesis, cell, split and stage); the cross-lab count is reported in
`P5/train.md`. `RESULTS.md` is regenerated by `run.py`, never by hand.

## Amendment 5 (2026-10-10, before any P6 return was read): P6 sport by sport

Written 2026-10-10 ~18:15 UTC. Why: the Polymarket US desk has traded real money since 2026-10-10 05:05 UTC with the
rule "buy the YES side at >= 0.97 when bid and ask are within 0.03; non-sports in their last hour, sports
match-winner markets while the game is in play; hold to settlement". It hit its $3 daily loss stop, and the owner
asked which sports are losing us money. P2 (sports, pooled) found no edge on TRAIN, but its selectable cell bought
pre-game prints too and pooled every sport. P6 asks the owner's question with the desk's own in-play rule, one sport
at a time. This amendment is written after the P1-P5 TRAIN returns and the desk's real record were read (they are its
motive) and before any P6 number was computed. The desk's seven real losses name leagues; they are NOT evidence for
any filter (a filter picked by looking at them proves nothing). Only the history below decides, by the lab's protocol:
fixed here, TRAIN selects, VAL confirms, TEST one look.

**(a) Sport map.** `research/lab4/P6/sports.py` (sha256 c1fdfe1e95dac2eb..., fixed at this amendment): the league is
the first dash-separated word of the event slug; `sport_of` maps it to one of tennis (atp, wta, itf, utr, challenger,
daviscup, ...), table tennis (setka*, wtt*), e-soccer (ebfsa, ebattles, efootball, ...), esports (cs2, lol, dota2,
val, codmw, r6siege, hok, mlbb, sc2, ...), soccer (the listed league codes), basketball (nba, wnba, euroleague, bk*,
...), baseball (mlb, kbo, npb), hockey (nhl, khl, shl, del, ...), american football (nfl, cfb, cfl), mma/boxing (ufc,
zuffa, boxing), cricket (cric*, crint) or other (f1, golf, rugby, darts, ...). "other" is a mixed bucket: reported,
never ALLOWED. The map also carries the US venue's codes and tags for later use by the desk; the history uses the
polymarket.com codes only.

**(b) Data and the desk-faithful rule.**
- *Game facts* (new data, metadata only, no price): `research/lab4/P6/meta.py` fetched once, on 2026-10-10 from
  Gamma's public `/markets` (no key, 100 ids per request, 0.5 s apart), for the 43,093 binary single-winner markets of
  the three splits whose event is a sport by (a) or whose fee family is sports: `sportsMarketType`, `gameStartTime`,
  the rules text, and the embedded event's `startTime`, `finishedTimestamp` (when the game ended), `score`, `period`.
  Written to `$LAB4_DATA/p6_meta.parquet`.
- *Game-winner markets* = `sportsMarketType == "moneyline"`. Structural check on TRAIN (no tape read): 8,351
  moneyline markets; tennis, baseball, basketball, american football, mma/boxing, table tennis and most esports and
  cricket are two-team markets; all 2,580 soccer moneylines are Yes/No ("Will X win?" and the draw), the three-way
  game; map, set and half winners are `child_moneyline` / props and are excluded. This matches the US desk's
  MONEYLINE + DRAWABLE_OUTCOME types (the US gateway's types on 2026-10-10).
- *Start* = the event's `startTime` (equal to the market's `gameStartTime` within 60 s for 99.9 %+ of TRAIN
  moneylines; it is the same field the US event's `startTime` that the desk reads). Why not `endDate`: for sports it is
  a deadline, not the start (TRAIN median endDate - startTime: tennis 167 h, baseball 168 h, soccer 0 h, esports 6 h).
  `startTime` is the SCHEDULED start: a delayed start lets pre-match prints in (the desk also checks the live period;
  the tape cannot).
- *End* = the event's `finishedTimestamp` when it is valid (start < finished <= closedTime): "games with a recorded
  end". Why an end is needed at all: the desk stops buying a game once its period reads final, while the market
  resolves later (TRAIN median closedTime - finishedTimestamp: baseball 16 min, tennis 31, basketball 31, soccer 123),
  and in that gap the winner trades at 0.99+: a first print at >= 0.97 there is a near-sure win the desk cannot buy.
  Gamma records a valid end for some leagues only (TRAIN: tennis 2,218 of 2,836 - ATP and WTA yes, ITF no; soccer 1,321
  of 2,580; baseball 576 of 614 - MLB yes, KBO/NPB no; basketball 112 of 219; cricket 154 of 241; esports 0 of 1,761;
  mma/boxing 0 of 72, its finished times fall after resolution). A game without a valid end gets a *fallback end*:
  closedTime minus the 90th percentile of that sport's resolution lag on TRAIN games with a valid end (tennis 38 min,
  baseball 20, basketball 42, soccer 172, cricket 238, american football 94; 139 min, the all-sports figure, where a
  sport has none: esports, mma/boxing, table tennis, e-soccer, hockey, other). Fallback-end games are read apart:
  their timing is rough and leans toward post-game wins, so they can only ever ADD a block (c), never an ALLOWED.
- *Buy*: the first BUYABLE print (Amendment 3) at or above theta for an allowed outcome with `start <= t < end`
  (and before closedTime); the YES side only in a Yes/No market (the US venue prices every order on YES; the desk buys
  long only), either team in a two-team market; executed at the first buyable print for the same outcome at or after
  t + 10 s, within 600 s and still before the end (else "missed"); one trade per market; hold to resolution; $20
  tickets as in lab 4, readings per $1 at risk. The real desk buys only the listed-first ("long") side of a two-team
  market: a reported-only cell "theta0.97|first-listed side only" checks that this does not change the picture.
- *Fees*: the owner's venue, Polymarket US, `0.0695 x shares x p x (1 - p)` (selects), and polymarket.com's own fee
  family (Amendment 1 table: sports 0.05; NFL / college football markets carry `zero_fees`, 0) as the second column.
  The polymarket.com fee is the LOWER of the two, so the US fee is the stress case here.
- *Clusters*: the event (one game: a soccer game's three markets are one draw); event bootstrap, B = 2000.
- *Cells*: theta 0.97 (decides), 0.98 and 0.99 (reported only, context), first-listed side only at 0.97 (reported
  only); per league (reported only). Readings per sport and league: markets, games, missed, win rate, mean price paid,
  gap (win rate - price), loss rate against the price-implied loss rate, net per $ with the US fee and its CI95, the
  gap's CI95, net per $ with the polymarket.com fee, cents per one-dollar contract, losses, the rule-of-three worst
  case. Also reported: the share of first prints that would have come after the final whistle had the window run to
  resolution (the size of the bias the end bound removes); for tennis, the retirement sentence of the rules text and
  the buys split by how the match ended (final score: completed or not, a heuristic).
- *Not testable from the tape*: the desk's bid/ask spread check (no book: a buyable print stands in for the ask), the
  desk's live-period check beyond start and end times, and the US venue's own prices (history is polymarket.com,
  markets with >= $20,000 volume; many small US leagues - Setka Cup table tennis, eBattles e-soccer, DEL and Swiss
  hockey - are not in it at all).
- Universe: >= 50 fills (lab 4's MIN_FILLS); every universe market of the split must have a tape (Amendment 3).

**(c) TRAIN selection (theta 0.97, US fee, games with a recorded end), per sport, in this order:**
1. "other" -> NOT ALLOWED (mixed bucket).
2. >= 30 games and the gap's event-bootstrap CI95 upper bound < 0 (loses more often than the price says, CI
   excluding zero the wrong way) -> **BLOCKED: proven loser**. The same test on the sport's fallback-end games (>= 30
   games) also blocks ("proven loser in its games without a recorded end"); their bias favours the favourite, so a
   loss signal there is conservative.
3. < 30 games with a recorded end -> **BLOCKED: no proof** (no proof = no real money).
4. CI95 lower bound of net per $ > 0, and the loss guards of `core.qualifies` (at least one observed loss; with fewer
   than five losses the rule-of-three worst case must be positive; added from Amendment 3: a sport with no loss proves
   nothing) -> **ALLOWED**.
5. Otherwise -> NOT ALLOWED: unknown (enough games, no proof either way).
Eleven sports are judged: a sport passing by luck is expected now and then; VAL is the guard.

**(d) VAL.** Only if TRAIN allows at least one sport: the POOLED allowed set at theta 0.97 on VAL (games with a
recorded end, US fee) must pass `core.qualifies` with n >= 100 (mean > 0, CI95 lower > 0, loss guards) AND sit at or
above the 95th percentile of `core.calibration_placebo`. Per-sport VAL readings are reported only and cannot change
the set. No allowed sport -> VAL is not run.

**(e) TEST.** Only if VAL passes: one look at the same pooled set, same bar, `LAB4_ALLOW_TEST=1`; the runner refuses
a second look (`P6/test.json` exists) and refuses unless VAL passed.

**(f) What each outcome means for the live desk** (P6 changes no code; code may only ever make the desk buy less):
- *TEST passes*: real sports buys may be restricted to the ALLOWED sports (a filter that only buys less), caps
  unchanged; a pass is history, not a promise, and the owner decides.
- *Nothing ALLOWED on TRAIN, or VAL / TEST fails*: no sport has history showing its 97c+ in-play favourites pay
  after the US fee; the history-backed safe setting is no real-money sports buys (paper only) until a sport passes.
- *Whatever happens*: BLOCKED sports (proven losers, and sports with no or too little history - table tennis,
  e-soccer and hockey among them) get no real money; their only other evidence would be the desk's own record, which
  is far too small to prove anything either way.
- The non-sports half of the desk is not addressed by P6.

**Trials.** Each (cell, sport, split) evaluated is one trial in `trials.json` (`kind` "cell" for theta 0.97 sports,
"reported" for the rest), plus the pooled rows; league rows are readings and are not logged. `RESULTS.md` carries a
P6 row written by `run.py`'s results writer.

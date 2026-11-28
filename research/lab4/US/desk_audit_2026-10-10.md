# Desk audit, 2026-10-10: where the real-money path leaks

> **Update, same day:** the fixes landed as the desk's rule `2026-10-10a`. The audit's tests below were moved into
> `tests/test_polydesk_safety.py` (adjusted where a later fix changes what they can see: sports are now practised on
> paper only, and one order goes out per game or ladder) and now pass there with the rest of the suite.

**What was read:** all of `src/nightcrawler/polydesk.py`, `polymarket_us.py`, `deskguard.py`, the desk part of `config.py`, `tests/test_polydesk.py` and `tests/test_polydesk_live.py`, at commit 84d5ba9.
**What was checked against:** the desk's own history (`/api/polydesk` snapshot at 2026-10-10 17:50 UTC: state file plus 190 desk receipts), and about 100 gentle public reads of `gateway.polymarket.us`, no more than one a second and no key. No API key was used, printed or stored. No source file was edited. Railway was not touched.
**Tests that prove each leak:** `research/lab4/US/desk_audit_2026-10-10_tests.py`. All 12 leak tests fail on today's code, and the one guard test (a normal game still buys once) passes. See "The tests" below.

Paper and real are never added together in this document. Every number comes from the history file or the venue's public data.

---

## The short answer

1. **The e-soccer game was worse than "two bets".** At 13:12 the desk bought **all three** outcomes of one eBattles game (Sassuolo win, draw, Roma win) at 0.98 each, in under a second. It paid $2.94 for three outcomes that pay out $1.00 in total, so it was certain to lose $1.94 whatever happened. That one game is **40 % of the whole real loss** ($1.94 of $4.89).
2. **Those three prices were not real prices.** The venue's own records show that our three orders were the *first trades those markets ever had*. The 0.97/0.98 quotes were resting offers nobody had traded. The lab's rule is defined on trades that actually happened. The desk only looks at quotes.
3. **The $10 open-money cap was broken with real money.** At 13:14:16 the venue held 11 contracts worth **$10.74**. When the venue does not confirm an order at once (this happened 34 times in 91 bets), the desk does not count that money and lets the next order through.
4. **The $3 daily and $10 total loss stops only count bets that have already finished.** Money still riding on open bets is ignored. When the daily stop fired at 13:25, nine bets ($8.78) were still open. In the worst case the "$3 day" could have lost about $12. The "$10 total stop" can end near -$20: the stop itself plus a full $10 of open bets.
5. **The risk manager, the "since the fix" scorecard and the lessons leave out 26 of today's 83 real bets.** Those were the desk's own orders that the venue confirmed late; the desk files them under "venue". The caps do count them.
6. **"Paper won 73 of 73" is not the same bet as the real money.** The 73 paper bets were made overnight (22:29 to 05:12 UTC). 47 of them were "NO" bets that real money cannot make. And while real money is on, the paper desk buys nothing at all. So the paper record has been frozen since 05:05, and its "a losing paper record stops real buys" protection cannot fire.

Fixing these leaks stops money from being lost for silly reasons. It does **not** make the rule profitable. Even if the e-soccer game had never happened, the real record would be 88 bets, 83 won, **-$2.94**. Lab 4 found no edge for this rule. And the real win rate (84 of 91, 92.3 %) is below what each price needs just to break even (97 % at 0.97, 98 % at 0.98, 99 % at 0.99).

---

## What checked out (good news, verified)

| Check | Result |
|---|---|
| Settlement prices | Every one of the 91 real results the desk booked equals the venue's settlement for that market (`/markets/{slug}/settlement`). |
| Desk money vs venue cash, 10-10 | Venue cash went from $20.384 (05:14, nothing open) to $17.4279 (17:21, nothing open): **-$2.9561**. The desk says -$3.1091 for the day, of which $0.1530 is the taker fee the desk *models*. -3.1091 + 0.1530 = **-2.9561, exact to the cent.** So the desk's results are right, and the venue charged **no fee** on these 83 bets. The real 10-10 loss was **$2.96**, not $3.11. |
| Restarts | 6 connections (2 on 10-09, 4 on 10-10). No market was bought twice; no result was booked twice (each of the 91 markets has exactly one buy and one settlement receipt). |
| Daily stop | It did stop new real buys at 13:25:43, right after the day reached -$3.29 (modelled; about -$3.15 at the venue). No real buy happened after that. |
| Phantom fills | None: the cash match above rules out the desk booking a bet the venue never filled. |
| Shorts | Real money never placed a "NO" bet (the venue prices every order on the YES side). |

The ITF tennis markets show a "settlement" of 0.99 in the venue's book statistics, but the desk booked 1.0. This is **not** a mismatch. Those markets sit in a `MARKET_STATE_CLOSED` state, where that field is a 0.99 closing mark. Their settlement endpoint says 1, and the cash above confirms the desk was paid 1.0.

---

## The leaks, worst first

| # | What goes wrong | Proven on real money? | Severity | Fix in one line | Test |
|---|---|---|---|---|---|
| F1 | Buys several outcomes of one game, even when their prices cannot all be true | Yes: -$1.94 certain loss | **Critical** | Skip any game whose outcome bids add up to more than 1; hold at most one real bet per game | `test_an_incoherent_three_way_book_buys_nothing` |
| F2 | Treats offers in a market that never traded as a price | Yes: the same three orders were those markets' first trades | **Critical** | Require at least one past trade at or above theta, and the market state OPEN | `test_a_market_that_never_traded_is_not_near_certain` |
| F3 | An order the venue has not confirmed is not counted against the open cap | Yes: $10.74 held vs $10 cap | **High** | After an unconfirmed order, stop real buys for that round and check the venue | `test_an_unconfirmed_order_counts_against_the_open_cap_in_the_same_round` |
| F4 | The daily and total stops ignore money still at risk | Partly: $8.78 still open when the stop fired | **High** | Count every open real bet as if it could lose | `test_the_daily_stop_counts_money_still_at_risk`, `test_the_total_stop_counts_money_still_at_risk` |
| F5 | The desk's own late-confirmed buys are filed as "venue", outside the rule's record | Yes: 26 of today's 83 real bets | **High** (hides risk) | Remember each order sent; stamp the contract with the rule when the venue shows it | `test_an_unconfirmed_fill_of_the_desks_own_order_counts_in_the_rules_record` |
| F6 | Prices are about 20 s old when the order goes; no re-check | Yes: 7 of 57 fills came in below the price seen, one at 0.93 | Medium | Re-read that one market's price just before the order | `test_a_real_order_rechecks_the_quote_first` |
| F7 | "Is the game in play?" ignores the venue's own live/ended flags | Not proven (the period is not saved with a bet) | Medium | Require `live` true and `ended` not true | `test_ended_and_postponed_games_are_not_in_play` |
| F8 | Several real bets ride on one BTC price | Risk only: 4 bets ($3.93) settled on one BTC price | Medium | One real bet per ladder (same key the risk manager uses) | `test_one_real_position_per_ladder` |
| F9 | The paper record is a different bet and stops while live; the page label says "never gets real money" | Yes (data, not money) | Medium (honesty) | Keep a long-only paper shadow while live; fix the label and the comparison | (sketch below) |
| F10 | A finished market can stay unbooked for up to an hour | Yes: median 5.2 min late, max 66 min | Low-Medium | Book as soon as the market's quote says CLOSED/EXPIRED | `test_a_closed_market_still_on_the_live_list_is_settled_this_round` |
| F11 | If the venue check fails, the desk buys anyway | Not seen | Low | No real buys in a round whose venue check failed | `test_no_real_buys_when_the_venue_book_cannot_be_read` |
| F12 | The desk models a fee the venue did not charge | Yes: $0.15 on 10-10 | Low (safe side) | None needed; label the figure "after modelled fees" | none |
| F13 | The "already tried" list drops sports markets first once it passes 5,000 | Latent | Low | Keep it in the order tried; drop the oldest | `test_the_tried_list_drops_the_oldest_not_the_sports_slugs` |
| F14 | An unreadable or reset state file silently resets the loss stops | Latent | Low | Rebuild the real P&L from the ledger's receipts at start | (sketch below) |
| F15 | A market with no settlement ever (404 forever) is never closed | Latent | Low (safe side) | Close after 7 days once the venue no longer holds it | (sketch below) |
| F16 | "Daily loss cap reached" stays on the page into the next day | Display only | Low | Recompute the status line every round | (sketch below) |
| F17 | A settled contract could be found at the venue and adopted a second time | Latent: not seen in 91 | Low | Never adopt a market that is already in the closed rows | (sketch below) |

**Before real money goes back on, ship at least F1 to F5 and F11.** F6, F7, F8 and F10 should follow.

---

## Each leak in detail

### F1 (Critical): several outcomes of one game, with prices that cannot all be true

**Failure scenario.** A three-way game (home, draw, away) has three separate markets. All three showed bid 0.97 / ask 0.98, 2 minutes into the game. Each one passes the rule on its own: ask at least 0.97, spread at most 0.03, game in play. The desk checks each market alone and has no "one bet per game" check, so it bought all three. Three outcomes of one game can never all be worth 0.98: their chances add up to 1.00, and here the bids alone added up to 2.91.

**Evidence (history file).**

| Market | Quote at entry | Bought | Result |
|---|---|---|---|
| `atc-ebfsa-sas-roma-2026-10-10-dh4-sas` | 0.97 / 0.98 | 13:12:36 at 0.98 | won +$0.019 |
| `atc-ebfsa-sas-roma-2026-10-10-dh4-draw` | 0.97 / 0.98 | 13:12:36 at 0.98 | lost -$0.981 |
| `atc-ebfsa-sas-roma-2026-10-10-dh4-roma` | 0.97 / 0.98 | 13:12:37 at 0.98 | lost -$0.981 |

Together: **-$1.944** on $2.94 staked. Game start 13:10 UTC, bought 2.2 minutes in, settled at the venue 13:21:29. The brief said "Roma-win and draw". It was all three outcomes. The "1 won" in the e-soccer line is the Sassuolo leg of the same game.

The same three-markets-per-game layout covers most soccer. In the venue's listing at 18:4x UTC, 93 of 200 sports events had three outcome markets and 101 had one match-winner market. Paper made three bets on one game twice since the fix (long the leader, short the draw and the trailer). Those quotes were consistent, so paper only bet three times the stake on one result; no sure loss was involved.

**Minimal fix** (`_apply_rule`, before the buy loop). Group this round's markets by game (event title plus start time; for non-sports, category plus end time, as `_cluster_of` does).
- If the best bids of a game's outcomes add up to more than 1.02, or more than one outcome qualifies, buy none of them and mark them tried.
- Never place a real order on a game where a real bet is already open.

**Test.** `test_an_incoherent_three_way_book_buys_nothing` uses three outcomes, each quoted 0.97/0.98. Today's code places 3 orders; the test expects 0. A guard test, `test_a_coherent_three_way_book_still_buys_the_leader_once` (leader 0.97/0.98, draw and trailer 0.01/0.02), expects exactly one order. It passes today and must keep passing.

### F2 (Critical): offers in a market that never traded are treated as a price

**Failure scenario.** At the start of a game, a market maker (or anyone) leaves resting offers on every outcome. Nobody has traded yet, so there is no price, only offers. The desk reads bid/ask and nothing else.

**Evidence (venue's public book statistics, read today).** Each market's first-ever trade (`openSetTime`) was our own order:

| Market | First trade ever | Our receipt |
|---|---|---|
| sas | 13:12:35.947 at 0.98 | 13:12:36 |
| draw | 13:12:36.269 at 0.98 | 13:12:36 |
| roma | 13:12:36.625 at 0.98 | 13:12:37 |

After us, the draw and Roma markets traded about 14 more shares, all near 0.01 to 0.03: the real belief.

Across all 91 real bets, 4 were a market's first trade (these three, plus one BTC rung that won). The 5 other losses were in busy markets (88,000 to 340,000 shares traded). This count describes what happened; it is **not** the reason for the fix. The reason is the rule's own definition: lab 4's rule fires on trade prints at or above theta (the code says so at line 945-947). A market with no trade cannot fire it.

**What the venue's quote reply contains** (read today): `bestBid`, `bestAsk`, `bidShares`, `askShares`, `lastTradePx`, `sharesTraded`, `state` (`MARKET_STATE_OPEN` when trading), `lastPriceSample.ts`. The desk's `bbo()` keeps only bid, ask and `last`, and never uses `last`. Nothing about size is checked. With 1-contract orders, a thin ask only means a partial fill. A thin **bid** is the weak spot, because the spread test leans on it.

**Minimal fix.** In `bbo()`, also return `sharesTraded`, `state`, `bidShares` and `askShares`. In `_apply_rule`, require:
- `state == "MARKET_STATE_OPEN"`;
- `sharesTraded > 0`;
- `lastTradePx >= theta - MAX_SPREAD`.

Save bid/ask sizes and the last trade with every position, so the lab can set a size floor from history, not from our 7 losses.

**Test.** `test_a_market_that_never_traded_is_not_near_certain`: two markets, both 0.97/0.98, one with no trade. Today's code buys both; the test expects only the traded one. (Note: the existing fake gateway in `tests/test_polydesk.py` returns no trade fields. When the fix lands, the fake must return `lastTradePx` and `sharesTraded`, or the old tests will stop buying.)

### F3 (High): an unconfirmed order is not counted against the open-money cap

**Failure scenario.** The venue often replies "no fill" to an order that did fill (34 of 91 real bets: 8 on 10-09, 26 on 10-10). It also shows the contract in its positions only a little later. The desk logs "No fill" and moves on. The next order in the same round is checked against an open total that leaves the first one out. The contract is found ("REAL position found at the venue") only when the venue is checked at the end of the round. If the round's reported fills were all "no fill", that check is skipped (`if bought and ...`, line 791), and the contract waits a full round.

**Evidence (desk events, 13:13:43 round, in order).**
1. "No fill at 0.980: … Bakken Bears …"
2. "REAL buy: … Botic Van de Zandschulp …". The cap check saw $8.79 + $0.97 = $9.76 and let it through.
3. "REAL position found at the venue: … Bakken Bears … 1 contract at 0.980".

Rebuilt from the receipts, the venue then held **11 contracts, $10.74, against the $10.00 cap.** The same path applies when an order times out (the desk logs it as "rejected", but it may have filled).

**Minimal fix.** After any real order whose fill is not confirmed (a "no fill" reply, or an error), place no more real orders that round. Always run the end-of-round venue check when an order was sent, not only when one was confirmed. (Equivalent alternative: count each unconfirmed order at its limit price until the venue check settles it.)

**Test.** `test_an_unconfirmed_order_counts_against_the_open_cap_in_the_same_round` uses a fake venue that lags like the real one, a $2 cap and three markets at 0.98. Today the venue ends up holding $2.94; the test expects at most $2.00. (The existing `test_silent_fills_are_found_in_the_venues_book` uses a venue that shows the fill at once, which the real venue did not do 34 times. It also counts 2 errors in `test_live_caps_open_money_rejections_and_no_fills`, which the fix will change to 1.)

### F4 (High): the loss stops ignore money still at risk

**Failure scenario.** `_live_allows` compares only *finished* results with the stop. With the $10 open cap, a day can sit at -$2.99 with ten open bets ($9.80) and every one of them can still lose: **about -$12.8 in a "$3" day.** The total stop works the same way: finished results can creep to just above -$10 while $10 more is open, so the account can reach **about -$20** before the halt fires (from today's -$4.89, one bad day can already reach about -$17.7: -$2.99 more finished plus $9.80 open). The halt itself only fires after a settlement, never before a buy.

**Evidence.**
- At 13:14:16 the day was -$1.44 (finished bets) with $10.74 open: worst case -$12.18.
- At 13:24:48 the e-soccer losses pushed the day past the stop (-$3.29 modelled by the end of that round); 9 bets ($8.78) were still open.
- They happened to win. The day ended at -$3.11 modelled, -$2.96 at the venue.

**Minimal fix** (`_live_allows`). Block a buy when either of these is true:
- finished day P&L - money in open real bets - this order's cost < -daily stop;
- finished total P&L - money in open real bets - this order's cost < -total stop.

On a flat day with the $3 stop, that allows at most 3 open bets. This only makes the desk buy less.

**Tests.**
- `test_the_daily_stop_counts_money_still_at_risk`: $3 stop, five markets. Today's code places $4.90 of orders; the test expects at most $3.00.
- `test_the_total_stop_counts_money_still_at_risk`: total at -$9, $10 stop. Today's code places $4.90 of orders; the test expects at most $1.00.

(`test_live_caps_open_money_rejections_and_no_fills` and `test_daily_and_total_loss_stops` encode the old counts and need new numbers.)

### F5 (High, hides risk): the desk's own late-confirmed buys are filed as "venue"

**Failure scenario.** A contract the venue confirms late (F3) is adopted with `rule: "venue"`, no quote and no order time. The rule's real record is `by_rule[rule]["real"]`, and that record is what the risk manager judges, what the panel's "since the fix" shows, and what the "tight books" lesson uses. All three leave these bets out. The panel puts them under **"before the fix"** instead.

**Evidence.** All 26 venue-stamped bets of 10-10 were the desk's own orders. The pattern repeats in the events: "No fill at 0.970: BTC Price at 9:00AM ET" and then "REAL position found … BTC Price at 9:00AM ET" in the same 12:51:13 round; Bakken Bears the same at 13:13:43.

| Record (real, 10-10) | Bets | Won | Result |
|---|---|---|---|
| What the risk manager and "since the fix" judge (rule-stamped) | 57 | 53 | -$2.69 |
| Filed as "venue" (the same rule's buys, confirmed late) | 26 | 25 | -$0.41 |
| **The rule's true real record for 10-10** | **83** | **78** | **-$3.11** (desk) / **-$2.96** (venue cash) |
| Panel "before the fix", real (8 from 10-09 plus these 26) | 34 | 31 | -$2.19 |

The lesson "Tight books: … 53 of 57 won (real)" leaves them out. They appear instead as "Unknown book (no quote saved at entry): 25 of 26 won, -$0.41 (real)".

The caps do see these bets. The open cap counts them from the next venue check (see F3), and the daily and total stops count them at settlement.

The risk manager's verdict is "unclear" either way: 53 events judged now, 73 if the adopted bets are included. On this payoff (win about 2 %, lose about 100 % of the stake) it would pause real buys only after **3 more lost games** on the record it judges, or **2 more** on the full 83. It cannot protect a $10 account; only the caps can.

**Minimal fix.** When an order goes out with no confirmed fill, keep `st["pending_orders"][slug] = {rule, bid_in, ask_in, spread_in, t_in, order_id}`. When `_reconcile` finds that slug at the venue, stamp the position with that rule, quote and time, plus `adopted: True`. Keep `rule: "venue"` only for contracts the desk never ordered. Expire pending entries after a day.

**Test.** `test_an_unconfirmed_fill_of_the_desks_own_order_counts_in_the_rules_record`. Today the adopted position carries `rule == "venue"`; the test expects the rule's id, and after settlement `by_rule[rule]["real"]["settled"] == 1`.

### F6 (Medium): prices are about 20 s old at order time

**Failure scenario.** Every round reads about 600 quotes first, then walks the list and orders. There is no second look at the one market being bought. A favourite whose price is falling (a goal, a break of serve) can be bought below theta, because a buy limit fills at any price at or below the limit.

**Evidence.**
- Rule orders went out 20 to 25 s after the round began (for example, the round started 13:12:13 and the orders went 13:12:36).
- 7 of 57 rule fills came in **below the quoted ask**, so the book had moved. One filled at **0.93** on a quote of 0.95/0.97: `aec-setkameua-mukvit-konvas`, below the 0.97 the rule requires.
- All 7 won. This is a break of the rule, not a proven loss.

**Minimal fix.** Just before each real order, call `bbo(slug)` again and re-apply the whole test (theta, spread, trades and state from F2, the game check from F1). Use the fresh ask as the limit. That is one extra request per real order.

**Test.** `test_a_real_order_rechecks_the_quote_first`: the round's quote is 0.97/0.98 and the fresh one 0.90/0.93. Today's code orders; the test expects no order.

### F7 (Medium): "in play" ignores the venue's own flags

**Failure scenario.** `live_sports_markets` calls a game in play when its `period` text is not on a short "not live" list. The venue sends `live`, `ended`, `score`, `elapsed` and `eventState.finishedTimestamp`, and the desk ignores them.

**Evidence (venue listing, 2026-10-10 18:4x UTC, 200 sports events).** 112 events pass the desk's test. 2 of them are not in play by the venue's own flags:
- `"VFT"`: Man Utd v Spurs, `ended: true`, `live: false`;
- `"POST"`: a postponed basketball game, `live: false`.

Our positions do not save the period, score or elapsed time, so we cannot tell whether a real bet was ever placed in such a game.

**Minimal fix.** Require `ev.get("live") is True and not ev.get("ended")`, and keep the period list as a second check. Save `period`, `score`, `elapsed` and `game_start` in each position (this changes no buying; it lets lab 4 study the situation at entry).

**Test.** `test_ended_and_postponed_games_are_not_in_play`. Today's code lists all three games; the test expects only the live one.

### F8 (Medium): one BTC price decides several real bets

**Failure scenario.** The crypto ladders ("BTC above 82,400 / 82,500 / 82,600 at 08:00") end together on one price, and the rule can buy every rung. One move past the strikes loses all of them at once.

**Evidence.** Grouped the way the risk manager groups them (same category, same end time), four real bets ($3.93) ended together at 08:30 UTC on BTC's price: BTC up/down 07:00-08:00, plus above 82,400, 82,500 and 82,600 at 08:00. That is more than the $3 daily stop, on a single price. Two other end times had 3 bets each, and one had 2. All won, so this is risk, not loss. The risk manager already counts each such group as one event; the caps do not.

**Minimal fix.** At most one open real bet per cluster (`_cluster_of`: game, or category plus end time). This is the same check as F1's "one per game".

**Test.** `test_one_real_position_per_ladder`: three rungs. Today's code places 3 orders; the test expects 1.

### F9 (Medium, honesty): paper is a different bet, and it stops while live

**Evidence.**

| | Paper (current rule) | Real (10-10) |
|---|---|---|
| Bought | 10-09 22:29 to 10-10 05:12 UTC (overnight) | 05:17 to 13:13 UTC (daytime) |
| Sides | 26 YES, **47 NO** ("short") | 83 YES; real money cannot buy NO |
| Kinds | 50 sports, 23 crypto | 66 sports, 17 crypto |
| Result | 73 of 73 won, +$29.79 (on $20 tickets) | 78 of 83 won, -$3.11 |

In live mode every path in `_apply_rule` ends before the paper branch (lines 961-1013), so **the paper desk has bought nothing since 05:05.** The risk manager's "a losing paper record stops real buys" (module docstring, `real_paused = paper_paused or …`) therefore cannot fire while real money is on. The rule label shown on the page still ends "…so this rule never gets real money" (line 656-658), while it trades real money.

**Minimal fix.**
- In live mode, also write a paper "shadow" row for every market where a real order is attempted (long side only, same price, `$ticket`), so paper and real are the same bets at the same time. This is pretend money only; real buying does not change.
- Change the label to say real money is on and lab 4 found no edge.
- On the panel, state the paper window and that most paper bets were NO bets.

**Test (sketch).** A live desk with one qualifying long market: after `poll`, there is exactly one real order and one paper row with the same slug, `side == "long"`, and `live False`.

### F10 (Low-Medium): finished markets are booked late

**Failure scenario.** A sports bet is booked only when its game drops off the live list. A finished game can stay listed (its period not yet updated) after the venue has closed and settled the market. Until the desk books the result, the daily stop cannot see it.

**Evidence (desk receipts vs the venue's `settlementSetTime`, all 91 bets).** The desk booked results a median **5.2 minutes** after the venue settled, and at most **66 minutes** after: 14 ITF tennis matches waited about 64 minutes. The 7 losses were booked 2.8 to 6.8 minutes late.

**Minimal fix.** Pass this round's quotes to `_settle`. For any open position whose quote `state` is not `MARKET_STATE_OPEN`, try the settlement at once, even if the game is still listed.

**Test.** `test_a_closed_market_still_on_the_live_list_is_settled_this_round`. Today the position is still open; the test expects it booked.

### F11 (Low): buying blind when the venue check fails

**Failure scenario.** If `positions()` fails at the start of a round, `_reconcile` returns 0 and the desk buys anyway. Any unconfirmed fills from the last round are then unknown to the caps.

**Minimal fix.** In live mode, place no real orders in a round whose venue check failed.

**Test.** `test_no_real_buys_when_the_venue_book_cannot_be_read`. Today's code places 1 order; the test expects 0.

### F12 (Low, safe side): the fee the venue did not charge

The desk subtracts `0.0695 x p x (1 - p)` per contract: $0.153 over the 83 bets of 10-10. The venue cash shows no fee was charged (the reconciliation above is exact). The daily stop fired on the modelled -$3.29, while the venue-side figure at that moment was about -$3.15. Both are past $3, so the stop was right. Keep the conservative model, and show the venue's cash result next to it. **The owner's real 10-10 loss is $2.96.** The 10-09 figure (-$1.78, 8 bets, older looser rule) cannot be checked to the cent from this file, so the all-time real loss at the venue is about -$4.72 if 10-09 also had no fee.

### F13 (Low, latent): the "already tried" list is trimmed alphabetically

`st["tried"] = sorted(tried)[-5000:]` keeps the alphabetically *last* 5,000 names, so once the list is full it drops every `aec-…`/`atc-…` (sports) market first, not the oldest. A market whose order was rejected could then be ordered again every round. Its present size is unknown, because `/api/polydesk` strips it.

**Fix.** Keep the list in the order tried, append new names, and drop from the front.

**Test.** `test_the_tried_list_drops_the_oldest_not_the_sports_slugs`.

### F14 (Low, latent): a lost state file resets the loss stops

`load_state` returns an empty state for a file it cannot read, or one with a different `STATE_VERSION`. That silently forgets `live_pnl_total_usd` (-$4.89 today), `live_halted` and today's losses.

**Fix.** On start in live mode, rebuild today's and the total real result from the ledger's `polydesk_settled` receipts, and use the worse of file and ledger. Refuse live mode if the file existed but could not be read.

**Test (sketch).** Write receipts totalling -$9.50, start with no state file and a $10 total stop: no order above $0.50 is placed.

### F15 (Low, safe side): a market that never settles is never closed

The 7-day "unresolved" drop in `_settle` runs only when the settlement reply is 200 with no value. A market the venue never settles (it answers 404, as it does for open markets) stays open forever. It keeps counting against the $10 cap, and a loss settled some other way is never booked.

**Fix.** After 7 days past the end, if the venue no longer holds the contract, close it as unresolved, with an event that asks the owner to check the venue's statement.

### F16 (Low, display): a stale "daily loss cap" line

`_live_allows` sets "Daily loss cap reached: no more real buys today." and never clears it. A restart clears it (`_connect`) even though the stop still holds that day: it was set at 13:25:43, cleared by the 17:21 restart, and set again at 17:21:29.

**Fix.** Recompute the line every round from the stop itself.

### F17 (Low, latent): adopting a settled contract twice

After the desk books a result and deletes the position, the next venue check would adopt the same contract again if the venue still listed it as held and not expired. The venue lagged on fills today. This was not seen in 91 bets.

**Fix.** `_reconcile` never adopts a slug that is in the closed rows.

---

## What this audit does not show

- **Which sports to drop.** That is task #65 on lab 4 history (TRAIN selects, VAL confirms, TEST one look). A cut-off chosen by looking at our 7 losses is not evidence. In particular, "how far into the game" (real bets were placed 1 to 176 minutes after the start) is a rule question for the lab, not a bug. The fixes above stop leaks; none of them is an edge.
- **The period, score and quote sizes at entry** of past bets. The desk never saved them (F2, F7).
- **The 10-09 cash to the cent.** The first connect (22.104) may already have included open positions.
- **Railway logs and the full ledger.** Only the 190 desk receipts in the snapshot were read.

---

## The tests

`research/lab4/US/desk_audit_2026-10-10_tests.py` (13 tests). It uses the repo's own fake gateway and fake exchange, extended with:
- the quote fields the real venue sends (last trade, shares traded, state, sizes);
- a second, fresher quote;
- a venue that confirms fills late, as the real one did 34 times.

It is not collected by default (`testpaths = ["tests"]`). Run it with:

```
PYTHONPATH=src:. python3 -m pytest -q -p no:cacheprovider research/lab4/US/desk_audit_2026-10-10_tests.py
```

On 84d5ba9: **12 failed, 1 passed** (the passing one is the coherent-game guard). Each failure is the leak itself:

| Test | Today's code does |
|---|---|
| incoherent three-way book | places 3 orders (sas, draw, roma) |
| one bet per ladder | places 3 orders |
| unconfirmed order vs open cap | venue holds $2.94 against a $2.00 cap |
| venue check failed | places 1 order |
| daily stop vs money at risk | $4.90 at risk under a $3 stop |
| total stop vs money at risk | -$9.00 - $4.90 = -$13.90 under a $10 stop |
| late-confirmed buy in the rule's record | stamped `venue` |
| re-check the quote | orders at 0.98 when the market is 0.90/0.93 |
| never-traded market | buys it |
| ended / postponed games | lists both as in play |
| closed market still listed | not booked |
| tried list | drops the newest `aec-` name |

When the fixes land, move the file into `tests/`. Update the old fake gateway to return a last trade, shares traded and an OPEN state. Re-set the numbers in the three older live tests named above (F3, F4).

---

## How the numbers were made

The scripts are in the session scratchpad (`audit/exposure.py`, `over.py`, `windows.py`, `leagues.py`, `first_trade.py`, `settle_lag.py`). They read only the history snapshot and the venue's public book files (`pub/books/*.json`, one per real market).

Public reads made: 102 GETs to `gateway.polymarket.us/v1`, at most one a second:
- 91 market books;
- 5 reads on the e-soccer markets;
- 2 sports-event pages;
- 4 single reads (one market list, one quote, two settlement checks).

No key was used.
